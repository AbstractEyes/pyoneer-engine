# Pyoneer Engine — Code Review

**151 verified findings.** Produced by eight parallel subsystem reviewers followed by an
adversarial verification pass; 17 claims were refuted and dropped. Findings were checked by
*executing* the cited code path, not by reading it — every "Failure" line below describes an
observed result, not a hypothesis.

Companion document: [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) sequences these into 12 shippable segments.

## Summary

| Category | High | Medium | Low | Total |
|---|---:|---:|---:|---:|
| broken | 20 | 31 | 20 | 71 |
| faulty-dichotomy | 1 | 2 | 0 | 3 |
| structural | 1 | 9 | 1 | 11 |
| performance | 2 | 9 | 7 | 18 |
| redundancy | 0 | 6 | 5 | 11 |
| confusing | 0 | 0 | 2 | 2 |
| unused | 0 | 2 | 33 | 35 |
| **Total** | **24** | **59** | **68** | **151** |

High-severity findings are documented in full. Medium and low are summarised to one line each;
the full evidence for those lives in the workflow transcript.


---

## Broken — crashes, or silently wrong behaviour

### CoreAssetManager.__init__ re-runs on every construction, silently discarding the loaded tmx cache and orphaning every held sub-manager reference

`singleton-init-reruns-destroys-loaded-state` · **HIGH** · `config/managers/core_asset_manager.py:29`

**Evidence.** `Singleton.__new__` (core_asset_manager.py:22-25) returns the cached instance, but `CoreAssetManager.__init__` (line 29) is still invoked by Python on every `CoreAssetManager()` call and unconditionally rebinds `self.config`, `self.entity`, `self.animations`, `self.maps`, `self.inputs` to brand-new objects (lines 32-39). It is constructed at MODULE IMPORT TIME in two places: component.py:16 `Config = CoreAssetManager()` and window.py:25 `Config = CoreAssetManager()`, plus main.py:154.

**Failure.** Verified at runtime: `c = CoreAssetManager(); c.maps.load_assets('test')` (parses and caches the pytmx map); then a second `CoreAssetManager()` — which is exactly what a newly-imported module doing `Config = CoreAssetManager()` performs — yields `inputs preserved: False`, `maps manager preserved: False`, `config manager preserved: False`, `tmx cache preserved: False -> now: None`. Also measured: today's import graph already runs `__init__` twice before main.py runs it a third time, re-reading all 8 config/*.json off disk each time. Concretely: add one new widget module containing `Config = CoreAssetManager()` and import it lazily after the map is loaded — the map cache is silently emptied (next `load_assets` re-parses the whole tmx mid-frame) and `MainGame.input` (main.py:155) becomes a stale InputActionManager that no component sharing `Config.inputs` is looking at anymore, so input…

**Fix.** Guard re-initialization: in `Singleton.__new__` set `cls._instance._initialized = False` only on first creation, and open `CoreAssetManager.__init__` with `if getattr(self, '_initialized', False): return` / close it with `self._initialized = True`. Then remove the import-time construction: replace `Config = CoreAssetManager()` in component.py:16 and window.py:25 with a lazy accessor `def _config(): return CoreAssetManager()` (or inject the manager through the constructor) so import order stops being load-bearing.

### Any dispatch with event=None is silently discarded, making bind_component's prepare/build commands no-ops

`event-none-silently-drops-dispatch` · **HIGH** · `scripts/core/component.py:575`

**Evidence.** `send_event_advanced` only builds `event__` from a `dict` (line 567) or a `PyoneerEvent` (line 570). With `event=None` it stays `None`, and the `event__ is not None` guard at line 575 returns `None` without invoking a single callback. Meanwhile `bind_component` (lines 375-382) calls `component_in.core_pre_prepare(None)`, `core_prepare(None)`, `core_post_prepare(None)`, `core_build(None)` — all of which funnel into `send_event_advanced(event_type=..., event=None)`.

**Failure.** Verified: a component with a bound PREPARE listener, added via `root.bind_component('child', child)`, records zero hits; `root.core_prepare(None)` also records zero hits; only `root.core_prepare(PyoneerEvent(GameEventType.PREPARE, ...))` fires. Every widget built through bind_component (window.py:181-199, panel.py:60-81, button.py:62-64, checkbox.py:55-57, text_box.py:54-57, scroll.py:170-174) never receives its BUILD or PREPARE event from that call. Today this is masked only because GameScene.begin() (game_scene.py:68-73) re-runs core_prepare with a real event on top-level scene objects; anything bound after scene start is never prepared or built.

**Fix.** Synthesize the event when it is missing: in `send_event_advanced`, if `event__ is None` and `e_type is not None`, do `event__ = self.__create_event(e_type, {}, sender=self)`. Then drop the `event__ is not None` term from the guard.

### event.handled breaks only the local callback loop; the child fan-out at line 516 runs unconditionally, so mark_event_handled cannot consume an event

`handled-does-not-stop-fanout` · **HIGH** · `scripts/core/component.py:516`

**Evidence.** ``` if self.__has_callback(typ): for callback in self.__get_callback(typ): callback(event, *args, **kwargs) if event.handled: break self.send_event_to_children_advanced(event_type=typ, event=event, ...) ``` The `break` exits the callback loop, then line 516 fans out to children regardless. Neither `send_event_advanced` (542) nor `send_event_to_children_advanced` (578) inspects `event.handled` on entry.

**Failure.** Verified: a 3-level tree root->child->grandchild where root's first UPDATE callback calls `ev.handle()`. Result: root's own second callback is correctly skipped, but child and grandchild both still fire. Concretely, window.py:293-294 `self.mouse.mark_event_handled(event_)` after a close-button click cannot stop the same click reaching sibling windows or the panel/text_box beneath — every consumer in the tree processes the click. mouse.py's ~12 `if event.handled: return` guards (lines 113,132,170,178,195,238) are the only thing partially papering over this, and they only work for components whose handler happens to run after the consumer in dict-insertion order.

**Fix.** Guard at both entry points: at the top of `__send_event`, `if event is not None and event.handled and not event.trickle: return`; and skip line 516 when `event.handled`. `PyoneerEvent.trickle` (event_manager.py:41) already exists as the intended opt-out flag and is currently read nowhere in the repo.

### send_event_to_children_advanced iterates self.components.items() live, so binding or unbinding any component from an event handler raises RuntimeError

`components-dict-mutation-during-dispatch` · **HIGH** · `scripts/core/component.py:581`

**Evidence.** `for name, component in self.components.items():` — dispatched into directly, with no snapshot. `bind_component` (line 383 `self.components[name] = component_in`) and `unbind_component` (line 388 `del self.components[identifier]`) both mutate that dict.

**Failure.** Verified twice. (a) A child's UPDATE callback calling `parent.bind_component('z', NewComponent())` -> `RuntimeError: dictionary changed size during iteration`. (b) A child's UPDATE callback calling `parent.unbind_component('sibling')` -> same RuntimeError. This is the single most ordinary UI operation there is: window.py:275-277 already detects the close-button click and only `print`s — the moment that becomes an actual `parent.unbind_component('window')` the frame dies. Same for any click-to-spawn-dialog or dynamic list.

**Fix.** Snapshot before dispatch: `for name, component in list(self.components.items()):`. Better, add a deferred structural-change queue (`self.__pending_binds` / `__pending_unbinds`) flushed at POST_UPDATE, so a mid-dispatch removal doesn't leave half the tree seeing the old topology.

### Neither `visible` nor `active` is consulted anywhere in the event path — hidden components still receive and consume mouse input

`visible-active-not-gating-dispatch` · **HIGH** · `scripts/core/component.py:510`

**Evidence.** `self.visible` is set at component.py:77 and read only in the *render* path (draw.py:82 `if not self.visible: return`, shape.py:48). `__send_event` (510), `send_event_advanced` (542) and `send_event_to_children_advanced` (578) have no visibility or active check. mouse.py's hit-testing (`__event__mouse_move`, line 249) tests only `self.parent.world_bounds.collidepoint(pos)`.

**Failure.** Verified: a component constructed with `visible=False` still receives its INPUTS callback. Consequence: hide a window (`window.visible = False`) and it disappears from the screen but still swallows clicks in its old rectangle, still fires MOUSE_CLICK_INSIDE on its close button, and still drags when you press in its former header. `GameEventType.SHOW`/`HIDE` exist (event_types.py:73-74) and are dispatched nowhere, so there is not even a hook to fix this per-widget.

**Fix.** Gate at the single choke point: at the top of `__send_event`, for input-class event types (INPUTS and the MOUSE_*/KEY_* set) return early when `not self.visible` — or add an explicit `self.accepts_input` flag defaulting to `self.visible and self.active` and check that. Doing it in `__send_event` covers the whole subtree in one place.

### GameComponent.core_image() always raises AttributeError due to private-name mangling against the wrong class

`core-image-attributeerror` · **HIGH** · `scripts/core/component.py:650`

**Evidence.** component.py:648-650 `def core_image(self, image_in=None) -> surface.Surface: return self.__image`. Inside `GameComponent` this mangles to `self._GameComponent__image`, which is never assigned anywhere. The only `__image` assignment is `PyoneerGameObject.__init__` (game_object.py:25) which creates `_PyoneerGameObject__image`.

**Failure.** Verified: `class Bare(GameComponent): pass; Bare(bounds=Rect(0,0,10,10)).core_image()` -> `AttributeError: 'Bare' object has no attribute '_GameComponent__image'`. Today this is masked only because every live subclass happens to override core_image (draw.py:65, shape.py, text.py). The first new component added in the same paradigm that does NOT override it (a pure behavior/logic component, a MouseComponentAsync consumer, etc.) crashes the frame the renderer or any consumer touches it. Note the abstract contract at game_object.py:105-107 declares core_image mandatory, so callers are entitled to call it.

**Fix.** Either delete the override entirely so `PyoneerGameObject.core_image` is inherited, or add a non-mangled backing field. Minimal: in `GameComponent.__init__` add `self._image: surface.Surface | None = None` and change line 650 to `return self._image`. Then make `DrawComponent` (draw.py:23/28/59/63/66) use the same `_image` field instead of its own mangled `_DrawComponent__image`, so there is one image slot per object rather than one per class in the MRO.

### move() on a parented component never updates local_bounds, so the move is erased by the next parent transform

`move-drops-local-bounds` · **HIGH** · `scripts/core/component.py:169`

**Evidence.** ``` if self.__parent is None: self.__local_bounds = Rect(x + offset.x, y + offset.y, local.w, local.h) self.__world_bounds = Rect(...) else: self.__world_bounds = Rect(x + offset.x, y + offset.y, world.w, world.h) ``` The `else` branch (lines 169-170) writes world_bounds only. `__update_world_bounds` (243-250) then recomputes `world = local + parent.world + offset` from the stale `__local_bounds`.

**Failure.** Verified live. parent Rect(0,0,200,200), child local/world Rect(10,10,50,50). `child.move(100,100)` -> local stays (10,10,50,50), world becomes (100,100,50,50). Then `parent.move(5,5)` broadcasts TRANSFORM -> child's `__transform_component` -> `__update_world_bounds` -> world becomes (15,15,50,50). The child teleports back to its original relative slot and the 100,100 move is gone. Since `Panel.core_update` calls `force_update_transforms()` every single frame (panel.py:199), any `move()` on a panel child is undone within one frame.

**Fix.** In the parented branch, convert the requested world position to local and store it: `self.__local_bounds.topleft = (x - self.__parent.world_bounds.x, y - self.__parent.world_bounds.y)` and then call `self.__update_world_bounds()` rather than writing `__world_bounds` directly. `move()` should have exactly one authoritative write (local) with world derived, or take an explicit `space: 'local'|'world'` argument.

### get_viewport_component returns None instead of searching ancestors whenever use_immediate_viewport is False and the immediate parent is not a view

`viewport-search-aborts` · **HIGH** · `scripts/core/component.py:332`

**Evidence.** ``` use_this_viewport = self.use_immediate_viewport # 316 if self.is_view: ... # 317-321 par = self.parent if par is None: return None # 324-325 if par.is_view: # 326 if use_this_viewport: return par else: use_this_viewport = True while par is not None and use_this_viewport: # 332 <-- loop gated on the flag par = par.parent ... return None ``` `use_this_viewport` is only flipped to True inside the two `is_view` branches. If neither `self` nor the immediate parent is a view and the flag started False, the `while` guard is False on entry and the ancestor walk never runs.

**Failure.** Verified live: `view(is_view=True) -> mid(is_view=False) -> leaf`. With `leaf.use_immediate_viewport = True`, `leaf.get_viewport_component is view` -> True. Set `leaf.use_immediate_viewport = False` and it returns None. In the real widget tree, a built Panel's ScrollComponent children (`arrow_1`, `arrow_2`, `thumb`, `bar`, all forced to `use_immediate_viewport = False` at scroll.py:178-181) all resolve to None. `DrawComponent.__blits` (draw.py:113-116) then takes the `else` branch and blits them at raw world coordinates with no clipping, so scroll widgets escape their panel.

**Fix.** Rewrite as an explicit skip-count walk with no flag mutation inside the loop: ``` skip = 0 if self.use_immediate_viewport else 1 node = self if self.is_view else self.parent while node is not None: if isinstance(node, GameComponent) and node.is_view: if skip == 0: return node skip -= 1 node = node.parent return None ``` This also removes the duplicated `is_view` check at lines 317-330.

### GameComponent redefines `depth` as a read-only property, silently deleting the inherited setter

`gamecomponent-depth-property-drops-setter` · **HIGH** · `scripts/core/component.py:147`

**Evidence.** game_object.py:41-47 defines `depth` with both a getter and `@depth.setter`. component.py:147-152 redefines `@property def depth` with no setter, which replaces the entire property object in the subclass namespace — the inherited `fset` is gone, not inherited.

**Failure.** Verified: `ShapeComponent(bounds=Rect(0,0,10,10)).depth = 5` -> `AttributeError: property 'depth' of 'ShapeComponent' object has no setter`. Every GameComponent is therefore depth-immutable after construction, so bringing a window to front on click, or re-sorting a UI stack, is impossible through the obvious API — even though `PyoneerGameObject` advertises the setter and `GameEntity` objects (which do not override the property) accept it fine. The same call works on entities and fails on components, which reads as a random inconsistency. Additionally the getter at 149-151 walks `self.__parent` on every read, and `get_components` (component.py:444) sorts by `x.depth`, making the sort O(n log n * tree-height) per call.

**Fix.** Add the setter back in GameComponent: `@depth.setter def depth(self, value: int): PyoneerGameObject.depth.fset(self, value)`. Since the getter is now a parent-chain walk, also cache it: invalidate a `self.__cached_depth` in `bind_parent` (component.py:358) and in the setter, rather than recomputing per access inside sort keys.

### InputActionManager.released() latches True on the first frame and never resets

`input-released-latches-true-forever` · **HIGH** · `scripts/core/input.py:116`

**Evidence.** `_released` is guarded by `if action and not action.released` (line 116) - it never runs again once `released` is True. The only place `released` is set back to False is inside `_pressed`'s success branch (line 108), which itself is guarded by `if action and not action.pressed` (line 95). Nothing resets `released` at frame boundaries.

**Failure.** Verified by execution on the real config: `im = InputActionManager().prepare(inputs.json); im.update()` -> `released('left')` is **True** on the very first frame despite the key never having been pressed, and stays True across every subsequent update. Any `if input.released('pause'): toggle_menu()` fires every frame forever, from startup. There is no working edge-trigger in this input system.

**Fix.** Restructure `update()` to compute raw state once per action, then derive edges from the previous frame: ``` for action in self.actions.values(): raw = self._raw_down(action) action.pressed = raw and not action.held action.released = action.held and not raw action.held = raw ``` This also deletes `_pressed`/`_released`/`_held` (60 lines of triple-duplicated scanning, lines 91-151) in favour of one `_raw_down`.

### __bind_ui_component's `depth + len(self.layers[depth])` collides with the child-component depths of the previous UI layer

`ui-layer-depth-arithmetic-collision` · **HIGH** · `scripts/core/renderer.py:282`

**Evidence.** `layer = GameComponentLayer(LayerType.UI, layer_name, depth + len(self.layers[depth]), Surface(widget.world_bounds.size))` then `self.layers[depth].append(layer)`. The layer is filed under dict key `depth` but carries `layer_depth = depth + n`. GameComponentLayer.core_blits (renderer.py:120) pushes that `layer_depth` into `event.data["layer_depth"]`, and DrawComponent.__blits (draw.py:79-80) adds it to each component's own depth: `depth += event.data["layer_depth"]`.

**Failure.** Verified live with the current test scene: one GameWindow bound at "UI_LAYER_1" (depth 100) produces tokens spread across depth buckets 100, 101, 102, 103, 104, 105 and 106 — the widget tree's own nesting depths added to layer_depth 100. Binding a SECOND window to the same "UI_LAYER_1" gives it `layer_depth = 100 + len(self.layers[100]) = 101`, so window #2's root component emits at depth 101 — exactly where window #1's depth-1 children already sit. The two windows interleave: window #1's title bar can draw on top of window #2's background. No error, no warning, just corrupted z-order. Adding a third window (layer_depth 102) makes it worse.

**Fix.** Stop deriving layer depth from list length. Either (a) give each UI layer a reserved depth band — `layer_depth = depth + n * COMPONENT_DEPTH_STRIDE` with STRIDE larger than any realistic widget-tree depth (e.g. 1000) — or (b) drop the additive scheme entirely and make the pool key a tuple `(layer_depth, component_depth, priority)` so the layer's slot can never be escaped by a child's local depth. Option (b) also fixes the fact that `self.layers[key]` and `layer.layer_depth` are two independent sources of truth that this line makes disagree by construction.

### EntityLayer culling rect is offset by +w/2,+h/2 — visible entities are culled at the right/bottom edge

`entity-cull-rect-offset-by-half-size` · **HIGH** · `scripts/core/renderer.py:96`

**Evidence.** `if camera.view_area.colliderect((entity.transform.position.x + (entity.core_image().get_width() / 2), entity.transform.position.y + (entity.core_image().get_height() / 2), entity.core_image().get_width(), entity.core_image().get_height())):` — the rect ORIGIN is shifted by half the sprite size while the width/height stay full-size. That is not a centering transform (which would subtract w/2), it translates the test rect down-and-right by half a sprite. The actual draw two lines below at renderer.py:100-101 uses the UNSHIFTED position (`x = entity.transform.position.x - camera.view_area.x`), so the cull rect and the draw rect describe different rectangles.

**Failure.** Verified numerically against the live camera (view_area = Rect(0,0,1024,768)) with a 44x64 player sprite: an entity at world x=1002, x=1010 or x=1023 is genuinely visible (its left portion overlaps the viewport) but `colliderect` returns False, so it vanishes. Sprites pop out of existence up to 22 px (w/2) before they actually leave the right edge, and 32 px (h/2) before the bottom edge — a visible flicker on every entity that walks off-screen. Symmetrically, an entity at x=-44 is entirely off-screen to the left yet still passes the test and is blitted, wasting a blit every frame.

**Fix.** Use the entity's true rect and cache the image once: `img = entity.core_image(); r = img.get_rect(topleft=entity.transform.position); if camera.view_area.colliderect(r):`. If the intent was actually to treat `transform.position` as the sprite CENTER, then use `img.get_rect(center=entity.transform.position)` and apply the same convention to the draw at renderer.py:100-101 — currently the cull and the draw use different conventions, which is the root of the bug.

### LayerRenderer.bind's isinstance dispatch rejects any component imported via the clean `scripts.core.component` path

`dual-module-identity-breaks-renderer-dispatch` · **HIGH** · `scripts/core/renderer.py:250`

**Evidence.** renderer.py:15 `from component import GameComponent`; renderer.py:250 `elif isinstance(game_object, GameComponent):` ... renderer.py:253 `raise Exception(f"Game object type {type(game_object)} not supported.")`. Verified at runtime: `import component` and `import scripts.core.component` produce two DISTINCT module objects from the same file (`c1 is c2 -> False`), so `component.GameComponent is scripts.core.component.GameComponent -> False`. A widget subclassing the dotted import returns `isinstance(w, bare.GameComponent) -> False`.

**Failure.** Executed: `from scripts.core.component import GameComponent as CleanGameComponent; class MyWidget(CleanGameComponent): ...; LayerRenderer(scr).bind("UI_LAYER_1", MyWidget(bounds=Rect(0,0,10,10)))` -> `Exception: Game object type <class 'MyWidget'> not supported.` The class IS a GameComponent by every reasonable reading; the renderer says it is not. This fires the moment the owner starts the stated PyCharm-decoupling migration file-by-file: every converted file's components silently become un-bindable, and the error message points at the type, not at module identity, so it is near-undebuggable.

**Fix.** Pick ONE canonical import path and enforce it. Concretely: make `scripts/core/component.py` the only entry, rewrite the 21 `from component import ...` sites to `from scripts.core.component import ...`, and delete the bare source roots. As a migration guardrail, add to `scripts/core/component.py` a module-level assert: `import sys; _m = sys.modules.get('component'); assert _m is None or _m is sys.modules[__name__], 'component.py imported under two module names'` so the duplication fails loudly at import instead of silently at isinstance.

### Every UI component gets core_prepare called three times; the lifecycle has three uncoordinated entry points

`triple-core-prepare` · **HIGH** · `scripts/core/renderer.py:125`

**Evidence.** Three independent callers: (1) `GameComponentLayer.bind` renderer.py:125 `component.core_prepare(PyoneerEvent(GameEventType.PREPARE, sender=self))` fires during bind; (2) main.py:90 `self.scene.current_scene.core_prepare()` -> game_scene.py:39-45 fans out to all objects; (3) `GameScene.begin` game_scene.py:68-73 calls `game_object.core_prepare(...)` AGAIN, gated only on `self.flags.get("active")` which is the scene's flag, not the object's — and main.py:209 calls `begin()` unconditionally.

**Failure.** Verified with an instrumented component: 1 core_prepare immediately after `SceneManager.bind`, 3 total after `core_prepare()` + `begin()`. GameWindow survives this only because it self-guards with `flags["prepared_window"]` (window.py:86/204) and GameComponent with `flags["prepared_base"]` (component.py:117/120). Every new component in the same paradigm that allocates a surface, registers a listener, or spawns children in core_prepare without inventing its own private flag will do it three times — three surfaces, three duplicate callbacks in `self.callbacks[typ]` (component.py:466-469 appends unconditionally), so one click fires three handlers. That is a silent triple-fire, not a crash.

**Fix.** Move the guard into the base class instead of asking every subclass to reinvent it: in `GameComponent.core_prepare` (component.py:114) return early on `self.flags.get('prepared')` and set it at the end, so re-entry is idempotent for all subclasses. Then delete the redundant call at renderer.py:125 (bind should not run lifecycle) and make `GameScene.begin` (game_scene.py:72) not re-run core_prepare — it should only flip `flags['active']` and fire a START/BEGIN event.

### SceneManager.bind writes an object into two structures but there is no unbind on either SceneManager or LayerRenderer, so removal leaks

`no-unbind-symmetry-renderer-leak` · **HIGH** · `scripts/core/scene/scene_manager.py:38`

**Evidence.** scene_manager.py:38-40 `self.current_scene.bind(...)` AND `self.renderer.bind(...)` — one call, two owners. `grep 'def unbind'` shows: `GameScene.unbind` (game_scene.py:64) exists; `EntityLayer.unbind` (renderer.py:72) and `GameComponentLayer.unbind` (renderer.py:127) exist but are unreachable from outside because `LayerRenderer` exposes no unbind and `self.layers` is the only handle; `SceneManager` has no unbind at all. Verified at runtime: `hasattr(sm,'unbind') -> False`, `hasattr(renderer,'unbind') -> False`.

**Failure.** Verified: bind a component through `SceneManager.bind("UI_LAYER_1", p)`, then call the only removal API that exists, `scene.unbind("UI_LAYER_1", p)`. Result: the scene stops updating it, but `renderer.layers[100]` still contains a GameComponentLayer holding `p`, which keeps calling `p.core_blits(event)` every frame. The object is now rendered but never updated — a frozen ghost that is also unreachable for cleanup. Its Surface (renderer.py:282) is retained forever. Every dead enemy, closed window, or unloaded scene in a real game leaks this way, and the visual symptom (a stuck sprite) points nowhere near the cause.

**Fix.** Add `SceneManager.unbind(depth_or_definition, game_object)` that mirrors bind exactly: call `self.current_scene.unbind(...)` AND a new `LayerRenderer.unbind(layer, game_object)` that resolves depth via `__prepare_depth`, walks `self.layers[depth]`, calls the matching `EntityLayer.unbind`/`GameComponentLayer.unbind`, and drops the Layer (and its dict entry) when its container empties. Better: stop double-storing — have the renderer hold weak references, or make the scene the sole owner and have the renderer query it, so there is one place an object can live.

### ScrollComponent resizes the thumb's local_bounds but the Button's ShapeComponent keeps its build-time bounds and surface, so the thumb never visually changes size

`scroll-thumb-never-resizes` · **HIGH** · `scripts/core/ui/widget/containers/scroll.py:190`

**Evidence.** scroll.py:188-191 `__event__update_scroll` does `self.scroll_bar.local_bounds = self.__scroll_bar_with_offsets()` and `self.scroll_thumb.local_bounds = self.__scroll_thumb_bounds()`. But `scroll_thumb` is a `Button` (scroll.py:165), and Button.__make (button.py:45-49) creates its `body` ShapeComponent with `bounds=Rect(0, 0, self.world_bounds.width, self.world_bounds.height)` captured once at construction. DrawComponent.__init__ (draw.py:25-28) allocates the Surface from world_bounds at construction and nothing ever reallocates it -- `DrawComponent.scale` (draw.py:58) is never called from any bounds-change path.

**Failure.** Verified live on a real Panel: at build the thumb has `local_bounds = rect(186,14,14,124)` and its body surface is `(14,124)`. After setting `scrollable_bounds = Rect(0,0,200,4000)` and calling `__event__update_scroll`, `thumb.local_bounds` becomes `rect(186,14,14,6)` but `body.core_image().get_size()` is still `(14,124)` and `body.local_bounds` is still `rect(0,0,14,124)`. The user sees a thumb whose size never reflects how much content there is -- a 4000px document and a 210px document show an identical thumb. The same applies to `scroll_bar`, whose local_bounds is switched from `__scroll_bar_bounds()` at build (scroll.py:148) to `__scroll_bar_with_offsets()` on first scroll (scroll.py:190) with no redraw.

**Fix.** Give DrawComponent a `resize(w, h)` that reallocates `self.__image` and re-fires PREPARE, and give GameComponent a bounds-changed hook that cascades it. Then in scroll.py:188-191, after assigning local_bounds, propagate the new size into the Button's `body`/`text` children and re-run `prepare_background`. Alternatively make the thumb a bare ShapeComponent rather than a Button so there is only one surface to keep in sync.

### DrawComponent's auto-created image is opaque black, not transparent

`drawcomponent-opaque-black-default-surface` · **HIGH** · `scripts/core/ui/widget/draw.py:28`

**Evidence.** `self.__image: Surface = Surface((clamped.width, clamped.height)).convert_alpha()` — `pygame.Surface(size)` is constructed WITHOUT the `pygame.SRCALPHA` flag, so it is created opaque-black. Calling `.convert_alpha()` afterwards adds an alpha channel but does NOT zero it. Verified with pygame 2.6.0: `pygame.Surface((4,4)).convert_alpha().get_at((0,0))` -> `(0, 0, 0, 255)`, whereas `pygame.Surface((4,4), pygame.SRCALPHA).convert_alpha().get_at((0,0))` -> `(0, 0, 0, 0)`.

**Failure.** Any DrawComponent constructed without an explicit `image_in` (i.e. every widget that relies on the default) gets a fully opaque black rectangle as its backing surface. `__blits` (draw.py:111/115) queues that surface unconditionally, so a component that only partially paints itself — or paints nothing at all, e.g. a bare layout/spacer/container — punches an opaque black rectangle of its `world_bounds` size into the frame, occluding every lower-depth token in the pool. Because the blit pool has no per-pixel alpha check, this is silent: nothing errors, the frame is just wrong.

**Fix.** Construct with the alpha flag and skip the redundant conversion of an already-display-format surface: `self.__image = Surface((clamped.width, clamped.height), pygame.SRCALPHA).convert_alpha()`. Add a regression assertion in tests that `core_image().get_at((0,0))[3] == 0` for a default-constructed DrawComponent.

### DrawComponent.dispose_drawable takes no event argument but the dispatcher always passes one

`dispose-drawable-arity-mismatch` · **HIGH** · `scripts/core/ui/widget/draw.py:61`

**Evidence.** draw.py:54 binds `self.bind_sync_listener(GameEventType.DISPOSE, self.dispose_drawable)`, but draw.py:61 declares `def dispose_drawable(self):` with no event parameter. The dispatcher at scripts/core/component.py:513 invokes every callback as `callback(event, *args, **kwargs)` — the event is always passed. Note the sibling listener `__blits` (draw.py:74) DOES accept `event`, so the two listeners on the same object disagree on the contract.

**Failure.** Executed live: `DrawComponent(bounds=Rect(0,0,50,50)).core_dispose(PyoneerEvent(GameEventType.DISPOSE, sender=None))` raises `TypeError: DrawComponent.dispose_drawable() takes 1 positional argument but 2 were given`. Since `core_dispose` (component.py:637-639) fans DISPOSE out through `send_event_advanced`, tearing down ANY widget subtree containing a DrawComponent throws, aborting the dispose walk mid-tree and leaving the remaining children bound to their parent and still in the blit pool. Nothing in the engine currently calls core_dispose in the main loop, which is the only reason this has not been hit yet — the first scene transition or window close will trip it.

**Fix.** Change the signature to `def dispose_drawable(self, event: Optional[PyoneerEvent] = None):`. Then audit every other `bind_sync_listener` callback for the same arity mismatch — grep for `bind_sync_listener` and check each target accepts a leading event parameter.

### GameAnimationHandler.start() bypasses GameAnimation.start(), leaving the previous animation's sprite on screen

`animation-start-leaves-stale-frame` · **HIGH** · `scripts/game/entity/game_animation.py:110`

**Evidence.** ``` def start(self, name=None): self.stop() if name: self._animations[name].active = True # line 110 - sets the flag directly ``` It never calls `GameAnimation.start()` (lines 42-46), which is the method that resets `current_frame = 0`, `current_time = 0`. It also never sets `_frame_changed = True`, and `image()` (lines 102-105) re-slices the spritesheet ONLY when `frame_changed()` returns True - a flag that `image()` itself consumes (lines 23-26).

**Failure.** Verified by execution against the real config: `start('idle_down'); image()` -> offset (88,0). `start('walk_right'); image()` -> offset (0,128). `start('idle_down'); image()` -> **offset (0,128)** - still showing the walk_right frame, because idle_down's `_frame_changed` was already consumed on the first call. In game this is exactly the stop-moving path: GamePlayer.input_move (game_player.py:87) calls `self.animation.start(f"idle_{last_direction}")`, and the player keeps rendering the walking sprite. idle_down's frame duration is 1000 (config/animations.json), so it never self-corrects. Separately verified: `wr.current_frame = 3; start('walk_right')` leaves current_frame at **3**, so re-entering a walk animation resumes mid-stride instead of at frame 0.

**Fix.** Line 110 -> `self._animations[name].start(from_beginning=True)`, and add `self._frame_changed = True` to `GameAnimation.start` (line 42) so the handler re-slices on the next `image()`. This whole class of bug goes away if frames are pre-sliced into `list[Surface]` at load and `image()` becomes `self._active.surfaces[self._active.current_frame]` with no dirty flag at all.

### GameEntitySimple silently discards the `transform` argument, and `Transform()` is used as a shared mutable default

`entity-transform-arg-ignored-mutable-default` · **HIGH** · `scripts/game/entity/game_entity.py:30`

**Evidence.** ``` def __init__(self, transform: Transform = None, position=(0,0), rotation=0, scale=(1,1), image_path=""): super().__init__() self.transform = Transform(position=position, rotation=rotation, scale=scale) # line 30 - `transform` never read ``` `GameEntity.__init__` (line 52) passes `transform=transform`, and `GameAnimatedEntity.__init__` (line 111) passes `transform=transform` - both land on the parameter line 30 ignores. Separately, lines 51 and 108 declare `transform: Transform = Transform()`, a default evaluated once at class-definition time and shared by every entity that omits the argument.

**Failure.** `GamePlayer(world_transform=Transform(position=(500,300)))` constructs a player at (0,0). main.py works around this by calling `moveto()` afterwards (main.py:107, 113) - the workaround is the only reason placement works today. Worse, the moment line 30 is fixed to honour the argument, the module-level `Transform()` default activates: every entity constructed without an explicit transform shares ONE Transform object, and since `transform.position +=` mutates in place (verified), moving one entity moves all of them.

**Fix.** Line 30: `self.transform = transform if transform is not None else Transform(position=position, rotation=rotation, scale=scale)`. Lines 51 and 108: change the default to `None` and construct in the body. Do both in one commit - fixing only the first converts a placement bug into a shared-state bug.


### Medium and low — broken

| Sev | Finding | Location | Fix |
|---|---|---|---|
| medium | BlitToken's default destination/draw_area are shared mutable singletons that permanently corrupt all future… | `blitpool.py:9` | Use `None` sentinels: `destination: ... | None = None, draw_area: ... | None = None`, and materialize inside the body. Note `__rect_or_tup(None)`… |
| medium | ORGANIZED_BLITS is only cleared on successful flush, so an aborted frame leaks ghost tokens into the next… | `blitpool.py:60` | Call `BlitPool.clear_organized_blits()` at the top of `__deploy_blits` (renderer.py:235) and wrap the layer walk in `try/finally` so the pool is… |
| medium | send_empty_event dispatches nothing in any configuration — the to_children return short-circuits to_self, and… | `component.py:587` | Build a real event once and dispatch both ways: `ev = self.__create_event(event_type, {}, sender=self); if to_self:… |
| medium | __get_callback yields directly from the live callbacks list, so unbinding a listener from inside a handler… | `component.py:518` | Snapshot: `for callback in tuple(self.callbacks[typ]):`. The generator indirection buys nothing here — inline it into `__send_event` over a tuple… |
| medium | depth property accumulates the parent chain, so any construction-time `depth=self.depth + N` double-counts… | `component.py:148` | Pick one model. Either (a) `depth` is absolute — remove the parent accumulation from the property and have `bind_parent`/`bind_component` assign… |
| medium | Panel's screen_area override silently forks into a second attribute; GameComponent.clipped_working_area reads… | `component.py:310` | Stop using double-underscore names for state that has a public property. Rename to single-underscore (`self._screen_area`) and make every internal… |
| medium | get_components_by_type compares an instance against a class with `is`, so it always returns an empty list | `component.py:458` | `if isinstance(component, component_type):`. Add a `recursive: bool = False` parameter while you are in there, since the string-keyed sibling… |
| medium | get_component_by_type compares str(type(x)) with `is` — identity on freshly built strings, not equality | `component.py:450` | Delete this method and keep only the fixed `get_components_by_type`, or if a by-name lookup is genuinely wanted, use `type(component).__name__ ==… |
| medium | DrawComponent.scale overrides GameComponent.scale with an incompatible signature; a TRANSFORM event carrying… | `component.py:213` | Rename the DrawComponent method to `resize_image(width, height, destination=None)` — it is a surface operation, not a transform. Then either… |
| medium | send_event_advanced dereferences the raw `event` parameter instead of the normalized `event__`, crashing… | `component.py:575` | Change line 575 to `... event__.sender is self.manager`. While there, hoist the guard into a helper `def _accepts(self, ev) -> bool: return… |
| medium | GameComponent.core_build's idempotency guard reads a flag that is never written, so build re-fires on every… | `component.py:123` | Add `self.flags["built"] = True` immediately before the return at component.py:127. Same class of fix as the `prepared` guard in the triple-prepare… |
| medium | pump_pyo compares a PyoneerEvent object to a GameEventType enum, so event pooling and the macOS… | `event_manager.py:126` | Compare the pygame event types, not the wrapper: `if last_event is not None and last_event.event.type == event.type:` — and move the… |
| medium | get_pyo's filtered branches compare the argument against the `int` and `pygame.event.Event` *types*, making… | `event_manager.py:148` | `elif isinstance(event, int): ... compare pyo_event.event.type == event` and `elif isinstance(event, pygame.event.Event): ... compare pyo_event.event… |
| medium | get() checks len(QUEUE) *after* clearing it, so the unfiltered return type flips between Event and list… | `event_manager.py:106` | Always return a list from the unfiltered path (`return cop`) and let callers index. If the scalar convenience is wanted, test `len(cop) == 1`, not… |
| medium | get(type) returns only the first matching event, silently dropping every other event of that type in the frame | `event_manager.py:109` | Collect all matches into a list and return it: `matches = [ev for ev in QUEUE if ev.type == event]; if consume: QUEUE[:] = [ev for ev in QUEUE if… |
| medium | PyoneerEvent.update_data calls .core_update() on a plain dict and assumes keys pre-exist; every branch of it… | `event_manager.py:59` | `self.data[key].update(value)` for the dict branch; `self.data.setdefault(key, []).extend(value)` for the list branch; and in `__init__` line 35… |
| medium | get_pyo() with consume=False returns the live PYO_QUEUE global rather than a copy, and scene_manager iterates… | `event_manager.py:146` | `cop = list(PYO_QUEUE)` in the non-consume branch too. The copy is cheap relative to the tree fan-out it precedes. |
| medium | An action bound to more than one input source cancels its own press every frame | `input.py:119` | `_released` must be `not any(down)`, not `any(not down)`. Folding both into the single-pass `_raw_down` scan proposed in… |
| medium | CONTROLLER map is missing every gamepad button name used in config/inputs.json | `input.py:103` | Resolve names to codes ONCE in `BaseAction.__init__` (input.py:46): build `self.inputs: list[tuple[str,int]]` there and raise a clear `Unknown… |
| medium | `entity.depth + self.layer_depth` lets an entity escape its layer band and land on a map layer's depth | `renderer.py:102` | Make depth composite rather than additive so bands cannot overflow — sort on `(layer_depth, entity.depth, entity.priority)` (a tuple key in… |
| medium | SceneManager.update() moves the camera before the player moves, so the camera is permanently one frame behind | `scene_manager.py:55` | Move `self.camera.update()` out of `update()` and into `post_update()` (line 61), after `current_scene.core_post_update(delta)`. That is precisely… |
| medium | mouse_down_time mixes milliseconds-since-init with seconds-of-frame-delta, making the drag delay threshold… | `mouse.py:181` | Pick one unit. Store `self.mouse_down_time = 0.0` on mousedown as an *elapsed-seconds accumulator*, keep the `+= FRAME_DELTA` at line 244, and change… |
| medium | MouseComponentAsync.mouse_down_time mixes absolute milliseconds with elapsed frame-delta, so mouse_drag_delay… | `mouse.py:253` | Store the press timestamp and the elapsed duration in two separate fields. Set `self.mouse_down_at_ms = pygame.time.get_ticks()` in… |
| medium | MOUSE_DRAG_BEGIN and MOUSE_DRAG_END are emitted by MouseComponentAsync but are absent from EVENT_TYPES, so… | `mouse.py:16` | Add `GameEventType.MOUSE_DRAG_BEGIN` and `GameEventType.MOUSE_DRAG_END` to EVENT_TYPES (mouse.py:16-30), and remove the unconditional… |
| medium | behavior/movement.py cannot be imported at all and behavior/viewport.py cannot be constructed; both are… | `movement.py:10` | Delete scripts/core/ui/widget/behavior/movement.py and scripts/core/ui/widget/behavior/viewport.py, or move them into the icebox alongside the other… |
| medium | Button.consume_click is wired through bind_sync_listener for MOUSE_DOWN_INSIDE, an event type that is only… | `button.py:65` | Replace button.py:65 with `self.mouse.bind_mouse_listener(GameEventType.MOUSE_DOWN_INSIDE, self.__consume_mouse_click)` (the Button already owns… |
| medium | Checkbox passes self.depth + N to its children, but GameComponent.depth already accumulates the parent chain,… | `checkbox.py:39` | Change checkbox.py:39 to `depth=1` and checkbox.py:49 to `depth=2`, matching Button. Then audit for the same pattern engine-wide with `grep -rn… |
| medium | TextComponent centering blits the text at half its own width from the left edge instead of centering it in… | `text.py:68` | Replace text.py:66-70 with `dst = self.core_image().get_rect()`; `pos = text.get_rect(center=dst.center) if self.center else… |
| medium | GameAnimationHandler.image() dereferences the active animation before the None guard | `game_animation.py:94` | Move the guard above the dereference: `if active is None: return self._image if self._image else ...` then `changed = active.frame_changed()`. Also… |
| medium | GameAnimationHandler rescans all animations to find the active one, and dereferences it before the None check | `game_animation.py:91` | Move `changed = active.frame_changed()` below the `if not active:` guard. Cache the active animation as `self._active` set in `start`/`stop`… |
| medium | Camera clamp uses full_area.width/height instead of .right/.bottom, and yields negative offsets on maps… | `game_camera.py:115` | Use `Rect.clamp_ip(self.full_area)` for the normal case - it handles .right/.bottom correctly by definition - and explicitly center the view on… |
| low | BlitToken stores live Rect references for destination and draw_area rather than copies | `blitpool.py:30` | Copy on ingest: return `Rect(tup)` / `Vector2(tup)` in both helpers for every input type, not just tuples. The extra copy is ~0.1 us and is dwarfed… |
| low | GameComponent.event_listener is a decorator that binds nothing and swallows the return value | `component.py:484` | Either delete it and document `bind_sync_listener` as the only mechanism, or make it real: have the decorator stash `func.__pyoneer_event_type__ =… |
| low | __scale and __rotation are written but never read by anything, and the int branch silently divides rotation… | `component.py:227` | Delete `scale()`, `rotate()`, `__scale`, `__rotation` and their `__transform_component` branches until there is a draw path that consumes them; the… |
| low | adjusted_bounds computes the adjusted rect then returns the unadjusted one | `component.py:257` | `return bounds`, and fix `adjusted_position` to apply `self.offset` on all three input branches (it currently only applies it to the Vector2 branch… |
| low | Mutable default arguments on three public methods, and bind_component's `list | None` default explodes if you… | `component.py:373` | `commands: list | None = None` with `commands = commands if commands is not None else ('pre_prepare','prepare','post_prepare','build')`, same pattern… |
| low | event_decorator.py raises NameError on import: pygame is never imported and the module has no import… | `event_decorator.py:5` | Delete the file — `GameComponent.event_listener` already occupies this design slot. If it is meant to survive, add `import pygame`, `from __future__… |
| low | event_manager.update()'s default delta constructs a pygame Clock and ticks it at import time, freezing delta… | `event_manager.py:80` | `def update(delta: float = 0.0):` — or make it required. Never put a side-effecting call in a default argument. |
| low | __bind_ui_component's default layer_name "UI" is not a key in DEPTH and raises | `renderer.py:278` | Change the default to `"UI_LAYER_1"`, or drop the default and make the parameter required so the layer is always an explicit choice. |
| low | GameScene.__make_event uses a shared mutable dict as its default `data` | `game_scene.py:52` | `def __make_event(self, event_type, data: dict | None = None): return PyoneerEvent(event_type, sender=self, data=data if data is not None else {})`.… |
| low | GameScene.__make_event shares one dict instance across every build/prepare/dispose event ever created | `game_scene.py:52` | Change to `data: dict | None = None` and `return PyoneerEvent(event_type, sender=self, data={} if data is None else data)`. The same mutable-default… |
| low | GameTransform.__transform_event uses `is` identity checks against type objects, so every branch is dead, and… | `transform.py:35` | Delete scripts/core/ui/widget/behavior/transform.py. GameComponent already handles TRANSFORM correctly at component.py:195-236 with proper isinstance… |
| low | Panel redeclares screen_area with its own name-mangled field, so the base class's clipping properties read a… | `panel.py:108` | Delete the Panel property at panel.py:107-113 and let the base `screen_area` (component.py:279-292) own the field, or rename Panel's concept to… |
| low | __blits has no guard for a disposed (None) image, so a disposed-but-still-bound component crashes the render… | `draw.py:74` | In `dispose_drawable`, set `self.draws = False` before nulling the image. Add an early `if self.__image is None: return` at the top of `__blits`. And… |
| low | Viewport.move(position) is a no-op - GameCamera.update ignores `position` whenever a target is attached | `viewport.py:35` | Give GameCamera an explicit precedence rule - `if position is not None: use it; elif self.target is not None: derive` - or, better, split into… |
| low | WidgetColor aliases copy = set, replacing pygame.Color.copy() with an incompatible mutating method, and… | `widget_color.py:31` | Delete the `copy = set` alias at widget_color.py:31 and rename `set` to `set_from` to avoid further shadowing (`Color` has no `set`, but the name is… |
| low | GameAnimationHandler.resume() is a copy-paste of pause() and stops the animation instead of restarting it | `game_animation.py:123` | pause/resume need a stored `self._paused: GameAnimation | None`, because setting `active=False` erases the very state `_active_animation()` searches… |
| low | DataAnimationCategory.order is parsed from config and never reaches GameAnimation.frame() | `game_animation.py:28` | Plumb it: have `DataAnimation.__init__` accept the category's order and store it, then call `active.frame(active.order)`. Better still - and this… |
| low | Transform's arithmetic dunders mutate self and return self, so `a + b` destroys `a` | `game_transform.py:101` | Make the four dunders pure - `return Transform(self.position + other.position, self.rotation + other.rotation, self.scale + other.scale)` - and add… |
| low | Transform.upper_left/upper_right/lower_left/lower_right treat `scale` as pixel extents when it is a multiplier | `game_transform.py:71` | Either delete the four methods, or give Transform a real `size: Vector2` distinct from `scale` and compute corners as `position +/- (size * scale) /… |
| low | GameMap.core_dispose is annotated -> bool but returns None, and six sibling overrides are pure super()… | `game_map.py:34` | `return super().core_dispose(event)`. Then delete the six other no-op overrides (lines 25-33, 37-38, 44-48) - inheriting them is behaviorally… |


---

## Faulty dichotomy — two APIs for one concept

### Child components' core_* overrides are never called — the event bus bypasses them entirely (Panel's per-frame scroll clamping is dead)

`panel-core-update-never-runs` · **HIGH** · `scripts/core/ui/widget/containers/panel.py:194`

**Evidence.** `Panel.core_update` (panel.py:194-199) calls `__clamp_scroll()`, `__hide_unhide_scroll()` and `force_update_transforms()` and is clearly written to run every frame. It never does. `GameComponent.core_update` (component.py:633-635) is `return self.send_event_advanced(event_type=GameEventType.UPDATE, event=event)`; `send_event_advanced` -> `__send_event` (component.py:510-516) invokes the node's registered callbacks and then calls `send_event_to_children_advanced`, which calls `component.send_event_advanced(...)` on each child — never `component.core_update(...)`. Only the objects registered directly with `GameScene` (game_scene.py:95-98) or with `GameComponentLayer` (renderer.py:118-121) ever get their `core_*` methods invoked.

**Failure.** Instrumented over the live loop: `Panel.core_update` = 0 calls/frame, `GameComponent.force_update_transforms` = 0 calls/frame. Consequences today: scroll positions are never clamped per-frame, `vertical_scroll.visible` is never recomputed, and child world_bounds are never re-derived unless a mouse/keyboard event happens to fire. Consequence for any new work: a developer adding `def core_update(self)` to a Button, Checkbox or TextBox in the same paradigm as Panel gets a method that silently never executes — the failure mode is invisible, there is no error.

**Fix.** Pick one dispatch mechanism. Either (a) have `send_event_to_children_advanced` call the child's matching `core_*` entry point so subclass overrides participate, or (b) delete the `core_*` overrides on child components and require them to `bind_sync_listener(GameEventType.UPDATE, ...)` — which is what ShapeComponent (shape.py:43), DrawComponent (draw.py:54-55) and AsyncEventComponent (async_.py:28-30) already do. Whichever is chosen, `Panel.core_update` must be converted to a bound UPDATE listener so its clamping actually runs.


### Medium and low — faulty-dichotomy

| Sev | Finding | Location | Fix |
|---|---|---|---|
| medium | GameScene keys __game_objects by the layer-depth argument but never reads the key — the layer/type dichotomy… | `game_scene.py:55` | Split the concern the API is currently conflating. Give GameScene its own signature: `bind(self, game_object, *, depth: int | str, tag: str | None =… |
| medium | Panel.attach_component and GameComponent.bind_component are two names for the same operation plus a shadow… | `panel.py:115` | Delete `attach_component`, `__add_child` and `self.children` (panel.py:33, 115-126), delete both `get_*_components_at` overrides (panel.py:128-140,… |


---

## Structural — breaks as soon as the engine is extended

### GameComponent carries nine distinct responsibilities in 677 lines; here is the concrete split

`monolith-decomposition` · **HIGH** · `scripts/core/component.py:20`

**Evidence.** Enumerated by line range: (1) **Transform/bounds** — 59-70, 162-263, 342-357, 392-400 (base/local/world rects, offset, scale, rotation, move/scale/rotate, __update_world_bounds, adjusted_position/adjusted_bounds). (2) **Hierarchy** — 89-91, 147-161, 358-370 (parent, bind_parent, accumulating depth). (3) **Child registry** — 98, 372-462 (bind/unbind/get_component, get_components_at, get_clickable_components_at, the two by_type lookups). (4) **Event bus** — 93-96, 464-524, 530-601 (callbacks dict, bind/unbind listeners, six send_* variants, __send_event, __get_callback, __create_event, mark_event_handled, the no-op event_listener decorator). (5) **Viewport/clipping** — 105-110, 137-145, 264-340 (is_view, screen_area, working_area, clipped_working_area, viewport, get_viewport_component, use_immediate_viewport). (6) **Interaction flags** — 75-86, 652-653…

**Failure.** The concrete cost is measurable in this review: seven of the defects above are cross-responsibility collisions that could not exist in a split design — the transform system reaching into the render system (`scale` clashing with `DrawComponent.scale`), the event system silently disabling the lifecycle system (`event=None`), the viewport system forking off the bounds system (`__screen_area` shadowing), the hierarchy system corrupting the depth system (double-counted `depth`). Every new widget subclass inherits all nine axes and must be tested against all nine.

**Fix.** Split into composed objects held by a thin GameComponent, in this order (lowest risk first, each independently landable): 1. `Transform2D` (own local/world Rect, offset, parent ref, `set_local`, `set_world`, `recompute()`), single-underscore fields, no properties that shadow. Fixes move()/local_bounds divergence by construction. 2. `EventBus` (callbacks dict, bind/unbind, dispatch, handled semantics). Fixes the None-event no-op in one place and makes handled-propagation semantics explicit — note `__send_event` line 516 forwards to children *regardless* of `event.handled`, which today is undocumented. 3. `ComponentRegistry` (the components dict, bind/unbind with parent-link + dedupe,…


### Medium and low — structural

| Sev | Finding | Location | Fix |
|---|---|---|---|
| medium | main.py runs the prepare phase before core_build, inverting the documented lifecycle contract | `main.py:66` | Reorder main.py to `self.load_config(); self.load_renderer(); self.prepare_test_scene()` (bind only), then `core_build()`, then the three prepare… |
| medium | bind_component neither sets the parent link nor rejects duplicates; the scroll widget already double-binds… | `component.py:383` | Have `bind_component` call `component_in.bind_parent(self, preserve_world_bounds=False)` so registration and hierarchy are one atomic operation, and… |
| medium | use_immediate_viewport propagates only to children present at assignment time, forcing per-child fixups | `component.py:142` | Make it inherited rather than copied: store `self.__use_immediate_viewport: bool | None = None` and have the getter return… |
| medium | scripts/core/component/ has no __init__.py and is permanently shadowed by scripts/core/component.py | `component.py:1` | Resolve the name collision before starting the refactor: rename the cold directory to `scripts/core/component_legacy/` (or delete it), and when… |
| medium | LayerRenderer.bind is a closed isinstance chain that raises bare Exception on anything it does not already… | `renderer.py:244` | Replace the chain with a dispatch table on the renderer: `self._binders: dict[type, Callable[[object, int|str], None]]` seeded with the three current… |
| medium | Every engine error path raises bare Exception, so no caller can catch anything selectively | `renderer.py:253` | Add `scripts/core/errors.py` with `class PyoneerError(Exception)` and subclasses `BindError`, `DepthNotFoundError`, `MissingCameraError`,… |
| medium | GameScene.begin() re-runs core_prepare on every object instead of activating the scene | `game_scene.py:68` | `begin()` should set `flags['active'] = True` and dispatch a distinct SCENE_BEGIN / activate event - not re-run prepare. If lazy prepare is the… |
| medium | GameWindow.core_prepare hard-codes a checkbox, two Panels, a TextBox and four more checkboxes, and its click… | `window.py:126` | Strip window.py:126-162 and 192-199 down to `body`, `header_bar`, `header_text`, `close_button`, `mouse`, `keyboard`. Replace the text_box-specific… |
| medium | draw, keyboard and async_ are each loaded twice under two module paths, producing two distinct DrawComponent… | `image.py:6` | Change image.py:6 to `from scripts.core.ui.widget.draw import DrawComponent`, panel.py:6 to `from scripts.core.ui.widget.behavior.keyboard import… |
| low | SceneManager.__bind_camera dereferences self.renderer, so binding a camera before the renderer crashes with a… | `scene_manager.py:28` | Make the dependency explicit rather than incidental: take the renderer in `SceneManager.__init__(self, game, renderer: LayerRenderer)` so it cannot… |


---

## Efficiency killers

### 4 static map layers are alpha-blitted full-screen every frame — 49% of the entire frame budget

`map-layers-blitted-uncomposited-every-frame` · **HIGH** · `scripts/core/renderer.py:159`

**Evidence.** `MapLayer.core_blits` (renderer.py:159-162) queues `BlitPool.blit_to_layer(depth=self.layer_depth, image=self._image, destination=(0,0), draw_area=camera.view_area)`. `__prepare_map_layers` (renderer.py:197-217) creates ONE MapLayer per named tile layer, each with its own `pygame.Surface((w*tw, h*th), pygame.SRCALPHA)` (renderer.py:206-208) and `self._image = self._image.convert_alpha()` (renderer.py:153). Measured on the shipped test map: 4 MapLayers, each a 1600x1600 per-pixel-alpha surface, each blitting a 1024x768 region to the screen, every frame. These surfaces are written exactly once in `core_prepare` and never mutate afterwards.

**Failure.** Measured headless (SDL dummy, 1024x768, 6 entities, 113 UI components, 69 blit tokens): full frame = 5.404 ms (185 fps ceiling). Isolating just the 4 map blits: 2.656 ms/frame. Pre-compositing the same 4 layers into one SRCALPHA surface: 0.521 ms. Pre-compositing into one `.convert()` opaque surface: 0.179 ms — a 14.8x reduction. Applying only this change to the live engine took the frame from 5.293 ms to 2.574 ms (51% of the whole frame). The cost is per-map-layer, so adding the 3 unimplemented FOREGROUND/Parallax layers listed in config/depth.json would push this past 4 ms/frame on its own.

**Fix.** At map-bind time, composite all static MapLayer surfaces that occupy the same depth band into a single surface, `.convert()` the bottom-most (it is fully opaque), and register one MapLayer that owns it. Keep separate MapLayers only for layers that must interleave with entity depths. Additionally, once the base map layer is opaque and always covers the viewport (GameCamera.update clamps view_area inside full_area, game_camera.py:111-118), the `self.screen.fill((0,0,0))` at main.py:264 becomes dead work — measured 0.157 ms/frame.

### Entity spritesheets are never converted to display format; every sprite blit is 15.7x slower

`unconverted-spritesheet-15x-blit-cost` · **HIGH** · `scripts/game/entity/game_animation.py:73`

**Evidence.** `self._spritesheet: Surface = pygame.image.load(self._data.file)` — no `.convert()` / `.convert_alpha()`. Every animation frame is a `subsurface` of this sheet (game_animation.py:99, 104), and a subsurface inherits the parent's pixel format and cannot be converted independently. Measured live: spritesheet masks `(255, 65280, 16711680, 4278190080)` vs display masks `(16711680, 65280, 255, 0)` — a full channel-order mismatch, so SDL takes the slow per-pixel conversion blit path.

**Failure.** Benchmarked on this machine with pygame 2.6.0: a 44x64 sprite blit costs 36.30 us unconverted vs 2.31 us after `convert_alpha()` — a 15.7x penalty. At 100 on-screen entities that is 3.63 ms/frame instead of 0.23 ms — 22% of the entire 16.67 ms frame budget at 60 FPS, burned purely on pixel-format conversion. The cost scales linearly with entity count, so it is the hard ceiling on how many entities the engine can render.

**Fix.** In `GameAnimationHandler.__init__` convert the sheet before any subsurface is taken: `self._spritesheet = pygame.image.load(self._data.file).convert_alpha()`. This requires `pygame.display.set_mode()` to have run first (it has — main.py:160 precedes entity construction at main.py:104). Better still, centralize this in the asset manager so no raw `pygame.image.load` result ever reaches the blit pool, and add a debug assertion in `BlitPool.blit_to_layer` that `image.get_masks() == pygame.display.get_surface().get_masks()`.


### Medium and low — performance

| Sev | Finding | Location | Fix |
|---|---|---|---|
| medium | Every BlitToken constructs a second throwaway BlitToken; token building costs 2.7 us where 0.33 us is… | `blitpool.py:20` | Delete the `self.copy(blit)` call from `__init__` and handle the copy-construct case with an explicit early branch, or drop the constructor-overload… |
| medium | GameComponent.depth recurses the whole parent chain on every read, 277 reads per frame | `component.py:147` | Cache the absolute depth on the component and invalidate it in `bind_parent` (component.py:358-370), the `parent` setter (component.py:158-160), and… |
| medium | __translate does an O(54) linear enum scan with tuple indexing on every event construction — 10-24us per event | `event_manager.py:70` | Build the reverse map once at module import: `_PYGAME_TO_GAME_TYPE = {m.value[1]: m for m in GameEventType if m.value[1] is not None}`, then… |
| medium | MapLayer bakes one full-map surface per layer — 41 MB for a 50x50 test map, quadratic in map dimensions | `renderer.py:206` | Bake in chunks instead of one surface: cache per-chunk surfaces (e.g. 16x16 tiles) keyed by chunk coordinate, and in `core_blits` emit one token per… |
| medium | EntityLayer.core_blits calls core_image() five times per entity per frame, each triggering a linear scan of… | `renderer.py:96` | Two independent changes. (1) renderer.py:96-102: hoist once - `img = entity.core_image(); w, h = img.get_size()` - and reuse. (2) game_animation.py:… |
| medium | MouseComponentAsync and GameWindow print() on every mouse enter/leave/down/up/scroll, and 26 independent… | `mouse.py:136` | Gate every print in mouse.py (118, 136, 174, 187, 202), async_.py:31 and window.py (212, 214, 276) behind the existing `from scripts.core.utils… |
| medium | Panel allocates its background Surface at the full virtual content size rather than the visible panel size,… | `panel.py:40` | Size the background from the panel's own visible bounds -- `bounds=Rect(0, 0, self.local_bounds.width, self.local_bounds.height)` at panel.py:43 --… |
| medium | DrawComponent.__blits allocates 5 Rects and walks the parent chain twice per drawn component per frame | `draw.py:74` | Cache `get_viewport_component`'s result on the component and invalidate it in `bind_parent` (component.py:358-370) and the… |
| medium | TextComponent.prepare_text constructs a fresh pygame.font.SysFont on every call and prepare_text runs on… | `text.py:60` | Add a module-level `_FONT_CACHE: dict[tuple[str,int], pygame.font.Font]` in text.py and look the font up by `(self.font, self.font_size)` instead of… |
| low | ORGANIZED_BLITS tears down and rebuilds a dict-of-dict-of-list every frame, with 14 sorted() calls, for a… | `blitpool.py:118` | Replace the dict-of-dict with a pre-sized list of buckets indexed by depth (depth values are dense small ints from depth.py), reuse the buckets… |
| low | Callback lookups go through dict.keys().__contains__ — 649 times per frame at 2.3x the cost of `in` | `component.py:641` | Replace all four occurrences with `typ in self.callbacks`. Also collapse the double check: `__send_event` (component.py:510-513) can do `cbs =… |
| low | InputActionManager caches pygame.key.get_pressed() and then never uses the cache, re-calling it up to 22x per… | `input.py:63` | Use the cache that is already being built - pass `self.keyboard` into the scan and index it. Combined with the single-pass restructure in… |
| low | Every map layer is convert_alpha() even when opaque, costing 2.9x per blit | `renderer.py:153` | After baking, scan for any pixel with alpha < 255 (or read Tiled's layer opacity / a per-layer `opaque` custom property) and choose `convert()` for… |
| low | __deploy_blits re-sorts the layer depth keys every frame though layers only change on bind | `renderer.py:238` | Keep a `self.__sorted_layers: list[tuple[int, list[Layer]]]` rebuilt in `bind`/`__bind_entity`/`__bind_ui_component`/`__prepare_map_layers`, and… |
| low | ImageComponent loads from a filesystem path during construction with no cache, subsurfaces without clipping,… | `image.py:46` | Route string paths through CoreAssetManager so surfaces are shared, and accept a pre-loaded Surface as the primary contract. Forward `image_in` to… |
| low | GameEntity.move_direction allocates a throwaway Transform (and two Vector2s) on every directional input,… | `game_entity.py:88` | Replace with a module-level table and direct arithmetic: ``` _DIRS = {"left": (-1,0), "right": (1,0), "up": (0,-1), "down": (0,1)} dx, dy =… |


---

## Redundancy and inefficient shapes

| Sev | Finding | Location | Fix |
|---|---|---|---|
| medium | LayerRenderer.update() runs twice every frame - once from SceneManager, once from the main loop | `main.py:266` | Delete main.py:266 - SceneManager owns the frame; main.py should only call `scene.pre_update/update/post_update` then `renderer.render()`.… |
| medium | Layer depth has three declarations — depth.py, config/maps.json, config/depth.json — that disagree, and two… | `depth.py:2` | Make config/depth.json the single source and delete the duplicates. Construct `DepthAssetManager` inside `CoreAssetManager.__init__` (alongside the… |
| medium | GameScene repeats the same dict-of-lists loop in 11 methods and allocates one PyoneerEvent per object per… | `game_scene.py:23` | One private dispatcher plus a flat cache: ``` def __dispatch(self, method: str, event: PyoneerEvent): for obj in self.__flat: # list kept in sync by… |
| medium | The async_ module contains no async/await; it is a second synchronous callback dictionary drained during… | `async_.py:25` | Rename the module and class to `buffered_events.py` / `BufferedEventComponent` and rename `bind_async_listener` -> `bind_buffered_listener` so the… |
| medium | ScrollComponent binds scroll_thumb under two keys and never binds the real scroll_bar Button under its own… | `scroll.py:174` | Change scroll.py:174 to `self.bind_component("scroll_bar", self.scroll_bar)` -- or delete the line, since `"bar"` already registers it. Separately,… |
| medium | GameCamera.update has four near-identical isinstance branches whose anchor semantics silently disagree | `game_camera.py:55` | Collapse to one body: ``` def _anchor(self) -> Vector2 | None: t = self.target if t is None: return None if isinstance(t, GameEntity): return… |
| low | BlitPool.get_blit_pool has no callers and a return annotation that describes a shape it cannot return | `blitpool.py:68` | Either delete `get_blit_pool` (the pygame variant is the only one in use), or narrow the annotation to `dict[int, dict[int, list[BlitToken]]]` and… |
| low | The `viewport` property builds a rect over three branches and then throws it away; it is also entirely unused | `component.py:270` | Delete the `viewport` property. Keep `get_viewport_component` as the single ancestor lookup and derive everything else from it. |
| low | Four event-send wrappers are pure pass-throughs with a `{}` literal used as a type annotation | `component.py:534` | Keep `send_event(event_type, event=None, *args, **kwargs)` and `send_event_to_children(...)` as the public names, rename the `_advanced`… |
| low | InputActionManager calls pygame.key.get_pressed() once per action per phase and discards the one result it… | `input.py:63` | Read `pygame.key.get_pressed()` once at input.py:63 into a local and pass it into `_pressed`/`_released`/`_held`, replacing lines 100, 121 and 142… |
| low | GamePlayer.core_image duplicates its parent, and GameAnimatedEntity re-declares dead __started/__stopped… | `game_player.py:50` | Delete `GamePlayer.core_image` (lines 50-53) - the inherited implementation is correct and identical. Delete game_entity.py:114-115. If… |


---

## Confusing or detrimental

| Sev | Finding | Location | Fix |
|---|---|---|---|
| low | core_prepare calls super().core_prepare(event) which is an abstractmethod with an empty body, and… | `component.py:116` | Give the abstract methods real no-op bodies (or make them non-abstract hooks) so `super()` calls are honest, fix the `-> surface` annotation to `->… |
| low | InputActionManager.pressed() means 'held' with no edge semantics, and raises KeyError on an unbound action… | `input.py:69` | Rename to reflect reality and supply the missing edge: `down(name)` (level), `just_pressed(name)` (edge), `just_released(name)` (edge), each via… |


---

## Completely unused

| Sev | Finding | Location | Fix |
|---|---|---|---|
| medium | main.py imports from scripts/core/ui/deprecated/, pinning cold storage into the live boot path for one type… | `main.py:20` | Drop `WidgetDrawableGroup` from the union at main.py:102 (the list only ever receives GamePlayer instances, see main.py:104-118) and delete the… |
| medium | Eleven public GameComponent methods/properties have zero call sites; three of them are also incorrect | `component.py:253` | Before splitting GameComponent, triage these eleven: delete adjusted_bounds, send_pygame_event, send_event_to_children, send_empty_event and… |
| low | Root __init__.py global object registry (bind/unbind/get_global_pyoneer_object) is never called and the… | `__init__.py:7` | Delete the three functions and `__object_registry__` from __init__.py, or — if a global registry is genuinely wanted for the AI-authoring goal — move… |
| low | All package __init__.py files are empty except the root, which defines a global object registry nothing uses | `__init__.py:1` | Populate the package inits with explicit re-exports and `__all__` — at minimum `scripts/core/__init__.py` exporting `PyoneerGameObject`,… |
| low | config/managers/depth_data.py is never instantiated, and config/depth.json is loaded but never read — plus… | `depth_data.py:12` | Either delete depth_data.py + config/depth.json (the live depth source is the hardcoded scripts/core/depth.py MAP_DEPTH/OBJECT_DEPTH/DEPTH), or… |
| low | requirements.txt lists PyBuiltins and strictpy, neither of which is imported anywhere in the repo | `requirements.txt:3` | Reduce requirements.txt to `pygame~=2.6.0` and `pytmx~=3.32`. Verified sufficient: the engine boots and enters the main loop with only those two… |
| low | BlitPool.get_blit_pool and BlitPool.clear_organized_blits have zero call sites | `blitpool.py:68` | Delete both statics. If a snapshot API is later needed, return `{d: {p: list(v) for p, v in pr.items()} for d, pr in ORGANIZED_BLITS.items()}` — a… |
| low | PARENT_CHANGED listener is bound in core_prepare but the event is never sent by anything | `component.py:118` | Make the `parent` setter delegate to `bind_parent`, have `bind_parent` dispatch PARENT_CHANGED (with `{'old': ..., 'new': ...}` in data) after… |
| low | __base_bounds is assigned in __init__ and never read anywhere — the 'three bounds' model is really two | `component.py:59` | Delete it, and update the class docstring (21-45) which currently documents nine `__`-prefixed callback attributes that do not exist on the class at… |
| low | send_event_to_children_advanced allocates a result dict that can never be populated — 516 dead dicts per frame | `component.py:580` | Either make `__send_event` return something meaningful (e.g. the aggregated callback results) so the dict earns its keep, or drop the dict and make… |
| low | adjusted_bounds, viewport and clipped_working_area have no call sites, and adjusted_bounds' Rect.copy() is… | `component.py:252` | Either delete all three, or fix and wire them up: `adjusted_bounds` should `return bounds`; `viewport` should consistently return a copy (or… |
| low | OBJECT_CONVERTER maps four class names that do not exist in the codebase | `depth.py:24` | Delete the four phantom entries from OBJECT_CONVERTER (depth.py:27-30), keeping only GamePlayer and GameEntity, and delete the unused depth imports… |
| low | event_manager.queue() is unreachable and would double-populate PYO_QUEUE if called | `event_manager.py:91` | Delete it. If deferred queuing is actually wanted, add a separate `DEFERRED: list[PyoneerEvent]` that `pump_pyo` drains into PYO_QUEUE *after* the… |
| low | EventPriority enum is referenced only from cold storage | `event_types.py:9` | Either delete EventPriority from event_types.py, or make it real: give bind_sync_listener a priority parameter and sort self.callbacks[typ] by it in… |
| low | Unused imports across scripts/core/ (verified with pyflakes) | `game_object.py:6` | Delete: game_object.py lines 6, 9-10, 14, 15's `Rect`, 12's `abstractproperty`, 17's `VERBOSE`; utils.py lines 28-30; scene_manager.py lines 2, 7,… |
| low | __bind_ui_component allocates a Surface per bind that is never read | `renderer.py:282` | Pass `None` for the layer surface here and make `Layer.__init__` accept `Surface | None`. If per-layer compositing is wanted later, allocate lazily… |
| low | LayerRenderer.rotate_image is dead and is a byte-for-byte duplicate of ImageComponent.__rotate_image | `renderer.py:305` | Delete LayerRenderer.rotate_image (renderer.py:305-322) and hoist the surviving implementation out of ImageComponent into a shared helper next to… |
| low | scripts/core/scene/game_scene_map.py::GameSceneMap is an empty dead stub | `game_scene_map.py:7` | Delete scripts/core/scene/game_scene_map.py, or implement it and route main.py:79 through it. Do not leave it as a stub. |
| low | SceneManager imports the entire depth module and three types it never uses | `scene_manager.py:10` | Delete lines 2, 7, 10 and 13 of scene_manager.py. Worth a repo-wide pass with `ruff --select F401` before open-sourcing — the same dead-coupling… |
| low | scripts/core/ui/widget/behavior/transform.py::GameTransform is dead and duplicates two live mechanisms | `transform.py:10` | Delete scripts/core/ui/widget/behavior/transform.py. If a transform behavior component is wanted, build it against GameComponent's existing bounds… |
| low | ListBoxComponent (and therefore GridComponent) is reachable only through a type annotation that is never… | `listbox.py:6` | Either (a) delete listbox.py, GridComponent and DummyParent, and remove window.py:14 + window.py:55; or (b) uncomment window.py:172, wire the list… |
| low | Unused imports across scripts/core/ui/ (verified with pyflakes) | `window.py:17` | Delete: window.py:17's `KeyBindingType`; grid.py:1; component_factory.py:1 and the `Type, TypeVar` names on line 2. Rename grid.py:77's `uuid`… |
| low | ComponentFactory and WidgetAlign are complete, unreferenced modules in the live source tree — including the… | `component_factory.py:21` | Either wire it -- have each container module self-register at import (`ComponentFactory().register('Panel', Panel)` etc.), call `mark_ready()` after… |
| low | ShapeComponent calls convert_alpha() and throws away the result — a full surface copy allocated for nothing | `shape.py:58` | Delete lines 58, 68 and 75. The surface is already in the display's alpha format from draw.py:28. |
| low | Both viewport modules are dead, and one permanently shadows the other on the bare-import path | `viewport.py:7` | Delete both viewport.py files. Viewport/clipping semantics already live on GameComponent as `is_view` + `get_viewport_component` + `screen_area` +… |
| low | WidgetColor's six fluent setters are all unused | `widget_color.py:33` | Delete set_r/set_g/set_b/set_a/scale_alpha/opacity and the `copy = set` alias. If mutation is wanted later, add a single `with_alpha(a) ->… |
| low | RectUtils is referenced only from cold storage (scripts/core/ui/deprecated/), not from any live file | `utils.py:6` | Delete the RectUtils class from scripts/core/utils.py at the same time as scripts/core/ui/deprecated/. utils.py then contains only… |
| low | scripts/game/camera.py is a third camera implementation that is both unreferenced and non-functional | `camera.py:134` | Pick one. Either delete scripts/game/camera.py, or finish it - it has the right shape for the composition-based refactor - and retire GameCamera in… |
| low | Twenty-six other public methods on live classes have zero call sites | `game_animation.py:119` | Delete the clearly-vestigial ones: text_box.update_ (:83), game_camera.within_bounds (:43), renderer.remove_camera (:230), game_transform's four… |
| low | scripts/game/entity/game_bounding_box.py::BoundingBox is dead | `game_bounding_box.py:4` | Delete scripts/game/entity/game_bounding_box.py. |
| low | Unused imports across scripts/game/ and config/ (verified with pyflakes) | `game_player.py:6` | Delete: game_player.py lines 6, 9, 12 and `GameEntity` from line 10; game_entity.py line 13, `overload` from line 4, `rect` from line 7;… |
| low | OldGameCamera is 46 lines of dead code sitting inside the live camera module | `game_camera.py:121` | Delete lines 121-166. If it is being kept as reference, move it into the existing cold-storage convention (scripts/game/icebox/) rather than leaving… |
| low | GameCamera's scale/zoom and offset_type are accepted, stored, and never applied | `game_camera.py:30` | Either drop the parameters and the three constants from the signature, or implement them. `offset_type` is precisely the switch that would let the… |
| low | GameMap builds a 10,000-cell depth_map that nothing ever reads, twice per startup | `game_map.py:19` | Delete `depth_map` and `create_depth_map` (game_map.py:17, 19-23, and the call at 42). If per-tile depth sorting is planned, it belongs as a sparse… |
| low | scripts/loaders/ is an empty package - map_loader.py and __init__.py are both 0 bytes | `map_loader.py:1` | Delete scripts/loaders/, or make it real. A `MapLoader` owning both load AND save is the natural home for the AI-authoring goal - note pytmx is… |
