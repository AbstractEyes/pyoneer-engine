# Pyoneer — Segmented Improvement Plan

**178 verified findings → 12 independently-shippable segments.** Each segment ends in a working engine and a commit. Nothing here is a rewrite; every step is a diff against the running code.

## Conventions used below

- **Verify** = a command that must pass before the segment's commit. Pre-S0 commands need the PyCharm PYTHONPATH; from S1 onward they use `tools/smoke.py`.
- **Size**: S ≈ half a day, M ≈ 1–2 days, L ≈ 3+ days.
- **Risk**: chance the segment silently breaks rendering/input without an error.
- Several findings arrived under duplicate ids from different review dimensions. They are merged and both ids listed, e.g. `entity-cull-rect-offset-by-half-size` / `-half-sprite`.

## Segment order at a glance

| # | Title | Risk | Size | Gate for |
|---|---|---|---|---|
| 0 | Import decoupling + repo baseline | med | M | everything |
| 1 | Verification harness | low | S | everything |
| 2 | Delete the dead | low | M | honest greps in 5–8 |
| 3 | Crash-class + visibly-wrong fixes | low | S | 4, 9 |
| 4 | Measured hot-path wins | low | M | perf baseline for 8 |
| 5 | One event contract | **high** | L | 7, 8 |
| 6 | Depth & layer ordering model | med | M | 8, 11 |
| 7 | Lifecycle & ownership | med | M | 8 |
| 8 | **GameComponent decomposition** | **high** | L | 9 |
| 9 | Widget hardening + demo extraction | med | M | — |
| 10 | Entity / input / camera | low | M | parallel with 5–9 |
| 11 | Map I/O boundary + factory (.tmx authoring) | med | L | — |

Segment 10 has no dependency on 5–9 and can be run by a second worker (or interleaved) any time after Segment 1.

---

# Segment 0 — Import decoupling and repo baseline

**Resolves:** `dual-module-identity-breaks-renderer-dispatch`, `module-identity-duplication`, `component-package-shadowed-by-module`, `main-depends-on-cold-deprecated`, `requirements-phantom-deps`, `empty-package-inits-and-dead-global-registry` (re-export half), `dual-viewport-modules-dead` (name-shadowing half)

This must be first: no other change can be *verified* while the engine only runs under PyCharm's 14 injected source roots, and the module-identity duplication silently breaks `isinstance` in exactly the code you are about to refactor.

### Changes

**0.a — Commit the baseline before touching anything.**
```
git add -A && git commit -m "baseline: engine as it runs under PyCharm source roots"
```
Add `.gitignore` for `.venv/`, `__pycache__/`, `.idea/`, `desktop.ini`.

**0.b — Resolve the two name collisions *before* rewriting imports.**
- `scripts/core/component/` (no `__init__.py`, contains `simple_component.py` + `behavior/`) is permanently shadowed by `scripts/core/component.py`. Rename the directory to `scripts/core/component_legacy/`. Do this now, because Segment 8 will create `scripts/core/component/__init__.py` and the flip would break all 18 `from component import …` sites at once.
- Two live modules named `viewport` (`scripts/core/ui/widget/viewport.py` wins over `scripts/core/ui/widget/behavior/viewport.py`) and two named `transform`. Both losers are dead; delete them here rather than in Segment 2 so the rewrite has one target per name.

**0.c — Rewrite every bare import to its dotted path.** 40+ files; the mechanical set is `from component import`, `from event_types import`, `from image import`, `from behavior import`, `from game_camera import`, `from draw import` (image.py:6), `from keyboard import` (panel.py:6), `from async_ import` (movement.py:3, being deleted anyway). Script it, then verify no module basename resolves twice.

**0.d — Add `__init__.py` re-exports.** `scripts/core/__init__.py` exports `PyoneerGameObject`, `GameComponent`, `BlitPool`, `LayerRenderer`, `PyoneerEvent`, `GameEventType`. This is what makes "one canonical dotted path per symbol" enforceable.

**0.e — Add the duplication guardrail** at the *end* of the rewrite (it would fire today):
```python
# scripts/core/component.py, bottom of file
import sys
_m = sys.modules.get("component")
assert _m is None or _m is sys.modules[__name__], \
    "component.py imported under two module names — check for a bare-import site"
```

**0.f — Unpin cold storage from the boot path.** Delete `main.py:20` (`from scripts.core.ui.deprecated.widget_drawable_group import WidgetDrawableGroup`) and drop `WidgetDrawableGroup` from the union annotation at `main.py:102`. The list at 104–118 only ever receives `GamePlayer`. This single import is the only thing making the explicitly-excluded `scripts/core/ui/deprecated/` tree undeletable.

**0.g — `requirements.txt`** → `pygame~=2.6.0` and `pytmx~=3.32` only. `PyBuiltins` and `strictpy` have zero imports repo-wide and install no `.pth`.

### Verify
```bash
cd "S:/Dropbox/Pyoneer" && SDL_VIDEODRIVER=dummy .venv/Scripts/python.exe main.py
```
with **no PYTHONPATH set**. Plus:
```bash
.venv/Scripts/python.exe -c "import sys; sys.argv=['x']; import main; \
  base={}; [base.setdefault(m.split('.')[-1],[]).append(m) for m in list(sys.modules) if m.startswith(('scripts','component','draw','keyboard'))]; \
  dupes={k:v for k,v in base.items() if len(v)>1}; assert not dupes, dupes"
```

**Risk:** medium (an import typo is a hard failure, which is the good kind). **Size:** M.

---

# Segment 1 — Verification harness

**Resolves:** none directly. Gates everything after it.

You cannot ship 11 more segments against "it looked fine when I ran it." Build the instrument once.

### Changes

Create `tools/smoke.py` (headless, `SDL_VIDEODRIVER=dummy`) that boots `MainGame`, runs N frames, and emits JSON:

- `component_census`: total node count + per-class counts under the bound `GameWindow` (today: 112 descendants — 34 `ShapeComponent`, 26 `MouseComponentAsync`, 19 `TextComponent`, 17 `Button`, 5 `Checkbox`, 4 `KeyboardComponentAsync`, 4 `ScrollComponent`, 2 `Panel`, 1 `TextBox`).
- `blit_census`: `{depth: token_count}` from `ORGANIZED_BLITS` before the flush (today: 13 depth keys, 69 tokens, buckets `10,30,40,41,50,60,100..106`).
- `dispatch_counters`: calls/frame of `DrawComponent.__blits` (64), `get_viewport_component` (59), `send_event_to_children_advanced` (619), `GameAnimationHandler.image()` (30), `LayerRenderer.update` (2), `PyoneerEvent.__init__`, `BlitToken.__init__` (138).
- `frame_ms`: median over N frames (today ≈ 5.1 ms).
- `frame_hash`: SHA of the composited screen surface after frame 10.

Create `tools/baseline.json` from a run on the Segment 0 commit. Add `tools/compare.py` that diffs a fresh run against a named baseline and fails on unexpected drift.

Add `tests/` with three tests that already pass, to prove the harness catches things:
1. `assert DrawComponent(bounds=Rect(0,0,4,4)).core_image().get_at((0,0))[3] == 0` — **currently fails**; mark xfail, un-xfail in Segment 3.
2. `LayerRenderer.bind` accepts a `GameComponent` subclass imported via the dotted path (regression for Segment 0).
3. One frame produces exactly 69 tokens across 13 depths.

### Verify
```bash
.venv/Scripts/python.exe tools/smoke.py --frames 120 --out run.json && \
.venv/Scripts/python.exe tools/compare.py tools/baseline.json run.json
```

**Risk:** low. **Size:** S.

---

# Segment 2 — Delete the dead

**Resolves:** `event-decorator-dead-unimportable` / `event-decorator-module-nameerror`, `movement-dead-unimportable` / `behavior-movement-viewport-dead-and-broken`, `widget-behavior-transform-dead` / `gametransform-noop-duplicate`, `game-scene-map-dead`, `bounding-box-dead`, `old-game-camera-dead` (×2), `viewport-camera-dead-and-broken` / `game-camera-viewportcamera-dead-truncated`, `global-object-registry-dead`, `blitpool-unused-statics`, `get-blit-pool-unused-wrong-annotation`, `renderer-rotate-image-dead-duplicate`, `queue-function-dead-and-duplicating`, `event-manager-dead-functions`, `update-data-nonfunctional`, `event-listener-decorator-noop` (×2) / `component-event-listener-noop-decorator`, `send-empty-event-broken` / `send-empty-event-to-self-unreachable`, `send-event-dead-wrappers`, `component-unused-public-api`, `get-components-by-type-broken`, `get-component-by-type-str-identity`, `adjusted-bounds-discards-work`, `unreferenced-bounds-properties-with-dead-copies`, `viewport-property-dead-contradictory`, `scale-rotation-write-only`, `base-bounds-write-only`, `misc-unused-public-methods`, `gamemap-depth-map-unused-and-built-twice`, `camera-scale-and-offset-type-unimplemented`, `transform-corner-helpers-use-scale-as-size`, `transform-operators-mutate-self`, `player-core-image-duplicates-parent`, `depth-object-converter-phantom-classes`, `rectutils-cold-only`, `event-priority-cold-only`, `unused-imports-core`, `unused-imports-ui`, `unused-imports-game-config`, `unused-imports-scene-manager`, `widget-color-unused-setters`, `component-factory-and-align-unwired` (align.py half), `listbox-and-grid-dead-chain`

~1,100 lines removed. Do this before the structural segments: every subsequent "grep for X" answer becomes trustworthy, and you stop maintaining parallel implementations of things you are about to split.

### Changes

**Whole files deleted:**
`scripts/core/event_decorator.py` (unimportable — `NameError: pygame`), `scripts/core/ui/widget/behavior/movement.py` (unimportable — `AttributeError: TRANSFORM_COMPONENT`), `scripts/core/ui/widget/behavior/viewport.py` and `scripts/core/ui/widget/viewport.py` (if not already gone in 0.b), `scripts/core/ui/widget/behavior/transform.py`, `scripts/core/scene/game_scene_map.py`, `scripts/game/entity/game_bounding_box.py`, `scripts/game/camera.py` (truncated mid-implementation; move its 10-point goals comment at lines 64–79 into `GameCamera`'s docstring first), `scripts/core/ui/widget/align.py`, `config/managers/depth_data.py` + `config/depth.json` (see Segment 6 for the single-source decision).

**Blocks deleted:**
- `scripts/game/game_camera.py:121-166` `OldGameCamera`; `:43-47` `within_bounds`; the unused `PyoneerGameObject` import at `:5`; `scale`/`offset_type` params and the three `OFFSET_*` constants.
- `scripts/core/renderer.py:305-322` `rotate_image` (duplicate of `ImageComponent.__rotate_image`, and note the surviving copy is the buggy one — it early-returns on `self.rotation` rather than the `angle` argument; keep the renderer's `if angle == 0` semantics when consolidating).
- `scripts/core/blitpool.py:67-73` `get_blit_pool`, `:87-90` `clear_organized_blits`.
- `scripts/core/event_manager.py:91-97` `queue()`, `:55-63` `update_data()`.
- `scripts/core/component.py`: `event_listener` decorator (484–491), `send_empty_event` (587), `send_pygame_event` (530), `__get_difference` (342), `adjusted_bounds` (252), `viewport` (264), `clipped_working_area` (305), `__base_bounds` (59), `__scale`/`__rotation` + `scale()`/`rotate()` (67, 69, 180–190) and their `__transform_component` branches, the commented async block (475–481, 493–498, 526–528). **Fix rather than delete**: `get_components_by_type` (458 → `isinstance`), `get_component_by_type` (450 → `isinstance`).
- `scripts/game/entity/game_transform.py`: four corner helpers (71–81, they treat `scale` as pixel extents), `clone` (65), and the four arithmetic dunders `__add__`/`__sub__`/`__mul__`/`__truediv__` (83–104) — they mutate the left operand and return `self`, and `__mul__` assigns a float because pygame's `Vector2 * Vector2` is a dot product. Zero callers.
- `scripts/game/game_map.py`: `depth_map` (17), `create_depth_map` (19–23) and its call at 42 — 10,000 cells built twice per boot, zero readers. Also delete the six pure-`super()` overrides at 25–33, 37–38, 44–48.
- `scripts/game/entity/game_player.py:50-53` `core_image` (identical to the inherited one); `scripts/game/entity/game_entity.py:114-115` the shadowed `__started`/`__stopped`.
- `scripts/core/depth.py:27-30` — the four phantom entries `GameFloorEntity`, `GameBackgroundEntity`, `GameForegroundEntity`, `GameUIEntity` have no implementing classes anywhere.
- `scripts/core/utils.py`: `RectUtils` (6–18; only referenced from `deprecated/`), and the misplaced unused imports at 28–30.
- `scripts/core/ui/widget_color.py`: `set_r/set_g/set_b/set_a/scale_alpha/opacity` (33–56) and the `copy = set` alias (31).
- `scripts/core/event_types.py:9-30` `EventPriority` (referenced only from excluded `scripts/core/component/behavior/`).
- The 26 zero-call-site methods in `misc-unused-public-methods` — keep the `unbind_*` family (Segment 7 needs it), delete `text_box.update_` (:83, body is `pass`), `renderer.remove_camera` (:230), `checkbox.is_checked` (:66).

**Moved to icebox, not deleted:** `scripts/core/ui/widget/containers/listbox.py` + `scripts/core/ui/widget/behavior/grid.py` (+ `window.py:14` and `:55`). Never executed once; a list box is worth having but should be re-derived on the post-Segment-8 base class, not resurrected cold.

**Unused imports:** apply the pyflakes-verified list across `game_object.py` (6, 9–10, 12, 14, 15, 17), `utils.py` (28, 30), `scene_manager.py` (2, 7, 10, 13), `window.py:17`, `grid.py:1`, `component_factory.py:1-2`, `game_player.py` (6, 9, 10, 12), `game_entity.py` (4, 7, 13), `game_animation.py` (4, 6, 8), `game_transform.py:2`, `game_camera.py:5`, `core_asset_manager.py:8`. Note the two dead `from scripts.core.blitpool import BlitPool` imports in `game_entity.py:13` / `game_player.py:12` actively mislead about the render architecture — entities never touch `BlitPool`; `EntityLayer.core_blits` blits on their behalf.

### Verify
`tools/compare.py` must show **zero drift** on every counter — this segment removes only unexecuted code. Then `python -m pyflakes scripts/ config/ main.py` reports zero unused imports.

**Risk:** low (the harness catches any accidental live deletion immediately). **Size:** M.

---

# Segment 3 — Crash-class and visibly-wrong fixes

**Resolves:** `drawcomponent-opaque-black-default-surface`, `dispose-drawable-arity-mismatch`, `blits-after-dispose-crashes`, `animation-image-none-deref-before-guard` / `animation-active-scan-and-none-deref` (guard half), `animation-resume-is-copy-of-pause`, `animation-start-leaves-stale-frame`, `scroll-thumb-double-bound` / `scroll-thumb-bound-twice`, `components-dict-mutation-during-dispatch` / `children-dict-mutation-during-dispatch`, `unbind-listener-during-dispatch-skips`, `viewport-search-aborts`, `entity-cull-rect-offset-by-half-size` / `-half-sprite` (×3), `text-center-offsets-instead-of-centering`, `core-image-attributeerror` / `gamecomponent-core-image-name-mangled` (minimal fix), `bind-component-no-parent-no-dedupe` (dedupe half), `blittoken-shared-mutable-defaults`, `blittoken-stores-live-rect-references`, `mutable-default-args`

Every one of these is between one and ten lines. Together they are the highest value-per-byte in the whole review.

### Changes

- **`scripts/core/ui/widget/draw.py:28`** → `Surface((clamped.width, clamped.height), pygame.SRCALPHA)`. `pygame.Surface(size)` without the flag is opaque black and `.convert_alpha()` does not zero it. Three live widgets (2 `Panel`, 1 `TextBox`) currently punch black rectangles into the frame — ~18.6k wrong pixels per frame today. Un-xfail test #1 from Segment 1.
- **`draw.py:61`** → `def dispose_drawable(self, event: Optional[PyoneerEvent] = None):`. The dispatcher at `component.py:512` always passes the event; this is the only zero-arg listener in the entire live tree (bound on 56 components). Currently a guaranteed `TypeError` on the first scene teardown. In the same edit set `self.draws = False` before nulling `__image`, and add `if self.__image is None: return` at the top of `__blits` (draw.py:74) — the viewport branch at :111 otherwise queues a token with `image=None` that fails later inside `blits()` with no indication of the culprit.
- **`scripts/game/entity/game_animation.py:93-95`** → move the `if active is None` guard above `changed = active.frame_changed()`. Reachable today via `pause()`/`stop()`, and guaranteed the moment anyone adds a `loop: false` animation. Also: `resume()` (123–125) is a byte-copy of `pause()` and calls `stop(False)`; give the handler a `self._paused` reference so resume can restore without touching `current_frame`. And `start()` (110) → `self._animations[name].start(from_beginning=True)` plus `_frame_changed = True`, so switching back to a previously-consumed animation stops rendering the old sprite (verified: `start('idle_down')` after `walk_right` keeps showing the walk frame at offset (0,128) for up to ~60s).
- **`scripts/core/ui/widget/containers/scroll.py:174`** → **delete the line.** It binds `self.scroll_thumb` under a second key `"scroll_bar"`; the real bar is already bound as `"bar"` at :170. Consequence measured: 16 extra event deliveries per phase, 8 duplicate `BlitToken`s per frame, and the thumb composited on top of itself. Add a guard in `bind_component` that raises when the instance is already a value in `self.components`.
- **`scripts/core/component.py:581`** → `for name, component in list(self.components.items()):`, and **`:519`** → `for callback in tuple(self.callbacks[typ]):`. Without the first, any handler that binds or unbinds a sibling raises `RuntimeError: dictionary changed size during iteration` — `window.py:275-277` is one line away from this. Without the second, a self-unsubscribing handler silently skips the *next* listener (verified: `a,b,c` where `a` unbinds itself yields `['a','c']`).
- **`component.py:313-340`** — rewrite `get_viewport_component` as an explicit skip-count walk. The `while par is not None and use_this_viewport:` guard at :332 is False on entry whenever `use_immediate_viewport` is False and the immediate parent is not a view, so the ancestor walk never runs. Verified live: every `ScrollComponent` child (`arrow_1`, `arrow_2`, `thumb`, `bar`, and their `ShapeComponent` bodies) resolves to `None` and takes the unclipped `else` branch at `draw.py:113-116`.
- **`scripts/core/renderer.py:96-102`** → `img = entity.core_image(); r = img.get_rect(topleft=entity.transform.position); if camera.view_area.colliderect(r):`. The current rect origin is `position + size/2` while the blit uses `position` — sprites vanish 22 px early on the right edge and 32 px early on the bottom, and off-screen sprites are blitted for an extra half-sprite on the left/top. This also collapses five `core_image()` calls to one.
- **`scripts/core/ui/widget/text.py:66-70`** → `dst = self.core_image().get_rect(); pos = text.get_rect(center=dst.center) if self.center else text.get_rect(topleft=(0,0))`, blitting shadow at `pos + text_shadow_offset`. Currently blits at `text_rect.centerx` — half the *text* width, unrelated to the destination. The close button's "X" sits 7 px left of centre today, and vertical centering does not exist.
- **`component.py:650`** → add `self._image: Surface | None = None` in `__init__` and return that. `self.__image` mangles to `_GameComponent__image`, never assigned. Do **not** delete the override: `PyoneerGameObject.core_image` is `@abstractmethod` with no body, so removing it makes `GameWindow`, `Button`, `Checkbox` and `ScrollComponent` uninstantiable. Full storage unification lands in Segment 8.
- **`scripts/core/blitpool.py:9-10`** → `None` sentinels for `destination`/`draw_area`, materialized in the body. Verified: two default-constructed tokens share one `Vector2` and one `Rect`, and the corruption is process-lifetime permanent. In the same pass make `__rect_or_tup`/`__tup_or_vec` copy on *every* input type, not just tuples — `renderer.py:162` currently hands the camera's live `view_area` to all four `MapLayer` tokens, and `draw.py:115` hands a component's live `world_bounds`.
- **`component.py:373`, `:435`** → `commands: list | None = None` etc. `bind_component(x, y, commands=None)` — a call the annotation explicitly invites — raises `TypeError` at :375 today.

### Verify
Full smoke run; expect exactly three drifts and assert each:
1. `frame_hash` changes (the black panels are gone) — capture a new baseline hash and eyeball one PNG.
2. Blit token count drops 69 → 61 (the 8 duplicate thumb tokens).
3. Event deliveries/phase drops 129 → 113.

Plus new tests: `DrawComponent(...).core_dispose(PyoneerEvent(DISPOSE, sender=None))` does not raise; `handler.pause(); handler.image()` does not raise; a built `Panel`'s `vscroll.arrow_1.get_viewport_component()` is not `None`.

**Risk:** low. **Size:** S.

---

# Segment 4 — Measured hot-path wins

**Resolves:** `map-layers-blitted-uncomposited-every-frame`, `maplayer-unconditional-convert-alpha`, `unconverted-spritesheet-15x-blit-cost`, `blittoken-double-construction` / `blit-token-double-allocation`, `core-image-called-five-times-per-entity` / `entity-blits-five-core-image-calls` / `entity-core-image-called-5x-per-entity`, `text-font-recreated-every-mutation` / `sysfont-constructed-per-text-change`, `mouse-prints-in-event-hot-path`, `shape-convert-alpha-result-discarded`, `has-callback-uses-keys-contains`, `deploy-blits-sorts-static-layer-keys`, `send-event-to-children-allocates-dead-dict`, `input-redundant-get-pressed-calls` / `input-get-pressed-called-per-action-per-binding`

No architecture changes — only work removal, all of it measured. Doing this before the decomposition gives you a fast, honest baseline to regress against in Segment 8.

### Changes

- **`renderer.py:197-217` — composite the static map layers.** The four `MapLayer`s are 1600×1600 SRCALPHA surfaces alpha-blitting a 1024×768 region every frame: **2.43 ms of a 5.14 ms frame (47%)**. But they are *not* collapsible into one: they sit at depths 10/30/50/60 with `EntityLayer`s interleaved at 40 and 41. The legal composite is **two** surfaces — `Floor + GroundClutter` → `.convert()` (Floor sampled fully opaque), and `PlayerDepth + Foreground` → `convert_alpha()` (both are >98% transparent). Measured pair cost: **0.674 ms — a 1.76 ms / 34% frame saving.** Do **not** copy the 51% figure from the review; that measurement collapsed all four and produces a visually broken build.
  - Once the base layer is opaque and always covers the viewport (`GameCamera` clamps `view_area` inside `full_area`), `self.screen.fill((0,0,0))` at `main.py:264` is dead work — another 0.156 ms.
  - Keep `convert_alpha()` on the two sparse layers; `renderer.py:153`'s unconditional call is only wrong for `Floor`.
- **`scripts/game/entity/game_animation.py:73`** → `pygame.image.load(self._data.file).convert_alpha()`. Spritesheet masks are `(255, 65280, 16711680, 4278190080)` vs display `(16711680, 65280, 255, 0)` — a full channel-order mismatch. Measured: **36.6 µs vs 2.35 µs per 44×64 sprite blit, 15.6×.** Negligible at today's 6 entities, but it is the hard ceiling on entity count. Frames are subsurfaces, so the sheet must be converted *before* any slice is taken. Add a debug assertion in `BlitPool.blit_to_layer` that `image.get_masks() == pygame.display.get_surface().get_masks()`.
- **`blitpool.py:20`** → `if blit is not None: self.copy(blit)`. Every token currently builds a second throwaway token (measured 138 constructions/frame for 69 tokens). Add `__slots__ = ("image","destination","draw_area","depth","priority","sender")`. Measured 1.87 µs → 1.16 µs. Small today (~0.05 ms), scales 1:1 with sprite count.
- **`scripts/core/ui/widget/text.py:60`** → module-level `_FONT_CACHE: dict[tuple[str,int], Font]`. `SysFont` costs **0.37 ms** vs `render` at **0.0034 ms** — 108×. `prepare_text` runs on every text assignment (`text_box.py:118` per keystroke) and is bound to `PREPARE` (`text.py:44`), so with 19 `TextComponent`s one PREPARE broadcast costs ~7 ms — more than a frame. Add an equality early-return in the `text` setter (`:52-55`).
- **`scripts/core/ui/widget/shape.py:58, 68, 75`** → delete. Bare `self.core_image().convert_alpha()` expression statements; `convert_alpha()` returns a *new* surface. Each allocates and immediately frees a full copy — the 1000×1000 panel background alone is ~4 MB per PREPARE.
- **Gate every hot-path `print()`** behind the existing `DEBUGGING`/`VERBOSE` from `scripts/core/utils.py` (the idiom `game_object.py` already uses): `mouse.py` 118/135/173/186/201, `async_.py:31`, `window.py` 212/214/276. One `GameWindow` construction emits 30 lines; a motion burst blocks on synchronous console writes.
- **`component.py` 466/473/503/642** → `typ in self.callbacks` instead of `self.callbacks.keys().__contains__(typ)` (2.45×, 649 calls/frame). While there, collapse `__has_callback` + `__get_callback` into one `cbs = self.callbacks.get(typ)` in `__send_event` — removes a double lookup per node per event.
- **`component.py:578-585`** → drop the `output` dict. `__send_event` has no `return`, so `call_return` is unconditionally `None` and the dict is always `{}` — 619 empty dicts/frame allocated and discarded.
- **`renderer.py:238`** → maintain `self.__sorted_layers` rebuilt at bind time instead of `sorted(self.layers.keys())` per frame. Sub-microsecond today; it is on the list because Segment 6 rewrites this line anyway.
- **`scripts/core/input.py:63`** → pass the already-captured `self.keyboard` snapshot into `_pressed`/`_released`/`_held` (100/121/142) instead of re-calling `pygame.key.get_pressed()` per action.

### Verify
`tools/compare.py` must show `frame_ms` down from ~5.1 ms to **~3.1 ms**, `BlitToken.__init__` 138 → 69, `GameAnimationHandler.image()` 30 → 6, and **`frame_hash` unchanged**. The unchanged hash is the whole point of this segment: if it moves, the map composite got the depth bands wrong.

**Risk:** low, *provided* the frame hash is checked. **Size:** M.

---

# Segment 5 — One event contract

**Resolves:** `event-none-silently-drops-dispatch` / `lifecycle-none-event-noop`, `handled-does-not-stop-fanout`, `visible-active-not-gating-dispatch`, `panel-core-update-never-runs`, `pump-pyo-pooling-branch-dead`, `translate-linear-enum-scan` / `pyoneer-event-translate-linear-enum-scan`, `get-length-check-after-clear`, `get-returns-first-match-only`, `get-pyo-type-identity-branches`, `get-pyo-returns-live-global`, `update-default-arg-side-effect`, `send-event-advanced-wrong-variable`

This is the highest-risk segment in the plan and the one that unblocks Segment 8. Everything here is a *semantics* decision, not a bug fix, and each decision changes behavior across all 113 live components at once. Land it in five separate commits, running the harness between each.

### Changes

**5.a — Synthesize the missing event.** `send_event_advanced` (`component.py:542`) requires both `e_type` and `event__` non-`None` at :575, and `event__` is only assigned for `dict`/`PyoneerEvent` (567–574). Add: `if event__ is None and e_type is not None: event__ = self.__create_event(e_type, {}, sender=self)`, then drop the `event__ is not None` term.

Be precise about what this fixes. It does **not** mean "every lifecycle call is a no-op today" — the overridden method bodies still run, which is why `Panel.core_build` and the whole widget tree get constructed. What is dropped is the *listener dispatch* and the *child fan-out*. Two real consequences: (1) `GameScene.core_dispose` (`game_scene.py:80-82`) calls `core_dispose()` with no event, so `DrawComponent.dispose_drawable` never fires and surfaces are never released; (2) `bind_component`'s `"prepare"` stage never runs `ShapeComponent.prepare_background` or `TextComponent.prepare_text` — it only works because `GameScene.begin` re-issues a real PREPARE afterwards. Also fix `PyoneerEvent.__init__` (`event_manager.py:35`) to default `data` to `{}` rather than storing `None`.

**5.b — Make `handled` mean handled.** `__send_event`'s `break` at :514-515 exits the local callback loop, then line 516 fans out to children unconditionally. Add `if event is not None and event.handled and not event.trickle: return` at the top of `__send_event`, and skip :516 when handled. `PyoneerEvent.trickle` (`event_manager.py:41`) already exists as the intended opt-out and is read nowhere. This is the change that lets `window.py:293`'s `mark_event_handled` actually consume a click, and it will retire most of `mouse.py`'s ~12 `if event.handled: return` guards.

**5.c — Gate input on visibility.** Neither `visible` nor `active` is consulted anywhere in the event path. Add `accepts_input = visible and active` checked at the top of `__send_event` for INPUTS and the `MOUSE_*`/`KEY_*` set. Note this is already a *live rendering* defect, not just an input one: `draw.py:82` returns from the node's own `__blits` but the child fan-out at :516 is unconditional, so `panel.py:191` sets `vertical_scroll.visible = False` every frame while its bar/arrows/thumb keep blitting. Wire `GameEventType.SHOW`/`HIDE` (dispatched nowhere today) to the flag.

**5.d — Pick one dispatch mechanism.** `Panel.core_update` (`panel.py:194-199`) calls `__clamp_scroll()`, `__hide_unhide_scroll()` and `force_update_transforms()` and is instrumented at **0 calls/frame**. Only objects registered directly with `GameScene` or `GameComponentLayer` ever get their `core_*` methods invoked; children receive `send_event_advanced`, never `core_update`. Choose **(b)**: child components subscribe via `bind_sync_listener` — which `ShapeComponent`, `DrawComponent` and `AsyncEventComponent` already do — and convert `Panel.core_update` to a bound UPDATE listener. Option (a) (have the fan-out call `core_*`) reintroduces the double-dispatch problem you are removing.

**5.e — Repair the EventManager query surface.** `__translate` (`event_manager.py:65-74`) does a 54-member linear enum scan per event, measured at **10.5 µs matching / 24.6 µs non-matching** vs a 0.63 µs baseline — ~95% of construction cost. Replace with a module-import-time `_PYGAME_TO_GAME_TYPE = {m.value[1]: m for m in GameEventType if m.value[1] is not None}`. Then: `get()` at :106 tests `len(QUEUE)` *after* clearing it (return type flips between `Event` and `list`) — always return a list; `get()` at :109 returns only the first match per type, dropping the second simultaneous keypress; `get_pyo`'s filtered branches at :148/:158 compare against the `int` and `pygame.event.Event` *type objects*, so every filtered query returns `[]`; `get_pyo(consume=False)` at :146 returns the live `PYO_QUEUE` global that `scene_manager.py:65` then iterates. And `update(delta=pygame.time.Clock().tick(60)/1000)` at :80 evaluates a blocking clock tick at import and freezes delta at 0.016 forever.

Do **not** try to repair the `pump_pyo` pooling branch (:126). The comparison is `PyoneerEvent == GameEventType.PYGAME` (always False), and the obvious fix still fails because `__translate` has already rewritten `.type`. More importantly the design is unsound: pooling by "previous event was PYGAME" would merge heterogeneous event types into one wrapper. Delete the branch and the `__PROBLEM_EVENTS` macOS dedupe with it; if per-frame coalescing is wanted later, do it on `pygame.event.get(eventtype=...)` before wrapping.

**5.f — Delete the manager gate.** `component.py:575` reads `event.sender` (the raw parameter) instead of `event__.sender`, crashing in two of the three documented call forms. It is unreachable only because `bind_manager` is never called with `True` and `self.manager` is universally `None`. **WONTFIX the feature** — delete `self.manager`, the `bind_manager` parameter, and the guard clause. It is a second, unexercised authorization layer stacked on an event bus that is about to be extracted.

### Verify
Harness counters must move in specific, asserted directions: `send_event_to_children_advanced` calls/frame **drops** (5.b prunes handled subtrees), `PyoneerEvent.__init__` cost drops ~95%, `Panel.core_update` goes 0 → 1/frame. `frame_hash` **will** change (5.c stops the hidden scrollbar children from blitting) — capture and eyeball. Add tests: a 3-level tree where the root handles an UPDATE fires exactly one callback; `bind_component` with a PREPARE listener records a hit; `EventManager.get(pygame.KEYDOWN)` with two queued returns both.

**Risk:** **high** — five behavior changes across every component. Mitigate with per-commit harness runs. **Size:** L.

---

# Segment 6 — Depth and layer ordering model

**Resolves:** `ui-layer-depth-arithmetic-collision` / `ui-component-layer-depth-drift`, `additive-entity-depth-escapes-layer`, `depth-double-counts`, `checkbox-depth-double-counted`, `gamecomponent-depth-property-drops-setter`, `depth-property-walks-parent-chain-per-access`, `three-sources-of-truth-for-depth`, `depth-asset-manager-dead`, `bind-ui-component-default-layer-raises`, `unused-surface-per-ui-bind` / `unused-surface-per-ui-component-layer`, `blitpool-dict-of-dict-rebuilt-each-frame`, `organized-blits-no-frame-start-clear`

Four separate findings share one root cause: depth is composed by *addition* across three independent levels, so bands overflow into each other. Fix it once.

### Changes

**6.a — Composite sort key.** Replace the additive scheme with a tuple key in `ORGANIZED_BLITS`: `(layer_depth, object_depth, priority)`. Concretely:
- `renderer.py:282` currently files a layer under dict key `depth` while giving it `layer_depth = depth + len(self.layers[depth])`. Verified: binding a second `GameWindow` to `"UI_LAYER_1"` gives it `layer_depth=101`, colliding with window #1's depth-1 children, and window #1's title bar draws over window #2's background. Keep `layer_depth = depth` and use the existing per-token `priority` field (`blitpool.py:80` already sorts priority within depth) for sibling order.
- `renderer.py:102` `entity.depth + self.layer_depth` — with `OBJECT_CONVERTER` wired up, a player on layer 40 with depth 50 lands at 90, which is `FOREGROUND_2`. Composite instead.
- `draw.py:79-80` `depth += event.data["layer_depth"]` — same treatment.

**6.b — Decide what `depth` means.** `GameComponent.depth` (`component.py:147-152`) accumulates the parent chain, but callers seed children from the already-accumulated value (`checkbox.py:39` `depth=self.depth + 1`). Verified live: `checkbox.depth == 1` but its background reports 3 and its checkmark 4, while `Button` (`button.py:46, 51`) uses the correct relative literals. Choose **relative**: keep the accumulation, forbid `self.depth` as a seed. Fix `checkbox.py:39, 49` → `depth=1`, `depth=2`. Audit with `grep -rn 'depth=self.depth'`. Document on the property that the constructor argument is relative to the parent.

**6.c — Cache the accumulated depth and restore the setter.** `GameComponent` redefines `depth` as a getter-only property, which *deletes* the inherited `@depth.setter` from `game_object.py:45-47` — `ShapeComponent(...).depth = 5` raises `AttributeError`, so bring-window-to-front is impossible through the obvious API. Add the setter back and cache the walk: 277 `depth` reads/frame cost **0.32 ms (6.3%)** today at chain length 3, and it grows as O(components × tree depth). Invalidate in `bind_parent` (:358), the `parent` setter (:158), and the new depth setter, pushing down to `self.components.values()`.

**6.d — One depth source.** Three declarations disagree: `scripts/core/depth.py:3` `Parallax: 1`, `config/maps.json:3` `Parallax: 0`, `config/depth.json:4-6` `UI_LAYER_1: 1000` vs `depth.py:13` `UI_LAYER_1: 100`. Only `depth.py` is live. **Decision: make `depth.py` the single source** (not `depth.json` — `DepthAssetManager` cannot even parse its own file, since `load_depths` iterates the top-level `.items()` and `Depth.__init__` indexes `config[1]` on a list of dicts, raising `IndexError`). Delete `config/depth.json`, delete `config/managers/depth_data.py`, delete the `layers` block from `config/maps.json`. Renumber `MAP_DEPTH`/`OBJECT_DEPTH` onto non-overlapping ranges (map layers 0–999, object depths 1000–1999) so the `|` merge at `depth.py:33` can no longer produce two names meaning one bucket — today `MAP_DEPTH["PlayerDepth"] == OBJECT_DEPTH["ENTITY"] == 50`, and three more pairs collide.

**6.e — Housekeeping on the same lines.** `renderer.py:278` default `layer_name="UI"` is not a key in `DEPTH` and raises; change to `"UI_LAYER_1"`. `renderer.py:282`'s fourth argument allocates a `Surface(widget.world_bounds.size)` (0.64 MB for the live window) that nothing ever reads — pass `None` and make `Layer.__init__` accept `Surface | None`. Reuse one `GameComponentLayer` per depth (as `__bind_entity` already does at :261-269) instead of one per widget. Call `BlitPool.clear_organized_blits()` at the top of `__deploy_blits` and wrap the layer walk in `try/finally` (`organized-blits-no-frame-start-clear` is the one **unverified** finding in the set — the fix is cheap and harmless regardless).

Replace the `dict[int, dict[int, list]]` with a pre-sized list of buckets reused across frames via `bucket.clear()`. This is structural cleanup, **not** a perf win: real measured cost of the current sorting machinery is ~0.017 ms/frame. The review's "0.74 ms / 10.7 µs per blit" figure is cProfile-inflated by ~4× and misattributes `BlitToken` construction cost.

### Verify
`frame_hash` unchanged, `blit_census` bucket *keys* change (composite) but token counts per visual layer stay identical. New test: bind two `GameWindow`s to `"UI_LAYER_1"` and assert window #2's every token sorts strictly above every token of window #1. New test: `ShapeComponent(...).depth = 5` succeeds. Depth reads/frame should drop to ~64 (one per drawn component, no chain walk).

**Risk:** medium. **Size:** M.

---

# Segment 7 — Lifecycle and ownership

**Resolves:** `triple-core-prepare`, `core-build-flag-never-set`, `gamescene-begin-reruns-prepare`, `lifecycle-order-inverted-in-main`, `super-core-prepare-empty-abstract`, `no-unbind-symmetry-renderer-leak`, `scene-depth-key-is-write-only`, `renderer-bind-isinstance-chain-not-extensible`, `singleton-init-reruns-destroys-loaded-state`, `bare-exception-no-error-taxonomy`, `bind-order-coupling-camera-before-renderer`, `renderer-update-called-twice-per-frame` (×3), `gamescene-seven-identical-loops`, `scene-allocates-event-per-object-per-phase`, `gamescene-mutable-default-event-data` / `gamescene-make-event-shared-mutable-default`, `gamemap-core-dispose-returns-none`

### Changes

**7.a — One prepare, one build.** Three uncoordinated `core_prepare` callers exist: `GameComponentLayer.bind` (`renderer.py:125`), `main.py:90`, and `GameScene.begin` (`game_scene.py:68-73`). Verified: **3 calls per component**. `GameWindow` survives only via a private `flags["prepared_window"]` guard it invented for itself. Move the guard into the base — `GameComponent.core_prepare` returns early on `flags['prepared']` and sets it at the end — then delete `renderer.py:125` (bind should not run lifecycle) and make `begin()` flip `flags['active']` and fire a BEGIN event rather than re-running prepare.

Same for build: `component.py:123` reads `flags["built"]` which nothing ever writes. Note the actual behavior is the *opposite* of what the finding narrates — `core_build(None)` dispatches **zero** events because the None-event guard drops it, so child components never receive BUILD at all, while the scene path (which passes a real event) repeats unguarded. After Segment 5.a both paths dispatch; add `self.flags["built"] = True` before the return. Factor both into one `_run_once(flag)` helper so the pattern cannot be half-implemented a third time.

**7.b — Fix the inverted order in `main.py`.** `main.py:66-68` runs `prepare()` → `build()` → `begin()`, but `prepare()` calls the three prepare phases at `main.py:89-91`, so the declared contract (build → pre/prepare/post) runs backwards. Strip 89–91 out of `prepare_test_scene` (leave it doing only binds) and put them in `build()` *after* `core_build()`. `GameWindow` gets away with the current order only because it has no BUILD handler at all — i.e. the codebase already abandoned the build phase to work around this.

Give `PyoneerGameObject`'s abstract lifecycle methods real no-op bodies (`game_object.py:57-107`) so `super().core_prepare(event)` — faithfully repeated in `scroll.py:53`, `panel.py:36`, `mouse.py:101` — is honest, fix the `-> surface` annotation (it names the *module*), and add `core_pre_prepare`/`core_post_prepare` overrides on `GameComponent` matching the existing PRE/POST_UPDATE ones, so those two stages become subscribable.

**7.c — Symmetric bind/unbind.** `SceneManager.bind` writes an object into two owners (`scene_manager.py:38-40`) and there is no unbind on either `SceneManager` or `LayerRenderer`. Verified: after `scene.unbind(...)`, the object is still in `renderer.layers[100][0].components` and still gets `core_blits` every frame — a frozen ghost that also strands its own dead `Surface`. Add `SceneManager.unbind` mirroring `bind`, plus `LayerRenderer.unbind(layer, obj)` that resolves depth via `__prepare_depth`, calls the existing (currently unreachable) `EntityLayer.unbind`/`GameComponentLayer.unbind`, and drops the `Layer` and its dict entry when empty. Also fix `GameScene.unbind` (`game_scene.py:66`), which uses bare `list.remove` and raises `ValueError` when called with the wrong key.

**7.d — Separate depth from identity in `GameScene`.** All twelve lifecycle loops bind `game_object_type` and discard it; the key is used only for `in`/`append`/`remove`. `main.py` currently mixes int-meaning-depth (`40`, `41`), string-meaning-depth-name (`"UI_LAYER_1"`) and string-meaning-nothing (`"MAP"`) in one dict. Change to `bind(self, game_object, *, depth: int | str, tag: str | None = None)` with a flat `self.__objects: list` plus an optional `self.__by_tag`. `GameScene.core_blits` returns `[]` unconditionally today, which proves the key was never a depth inside the scene.

**7.e — Collapse the twelve identical loops.** `game_scene.py` repeats `for type, list in items(): for obj in list:` twelve times (lines 24, 32, 40, 48, 70, 75, 81, 86, 91, 96, 101, 113) and they have already drifted — `core_post_prepare:50` ignores its passed event, `core_dispose:83` and `core_post_dispose:88` pass none at all. Replace with one `__dispatch(method, event)` over the flat list, building the event **once outside the loop** (`renderer.py:237` already does this correctly). Fix `__make_event`'s `data: dict = {}` shared mutable default at :52.

**7.f — Extensible bind + error taxonomy.** `renderer.py:244-253` is a closed three-branch `isinstance` chain ending in bare `Exception`. Replace with `self._binders: dict[type, Callable]` resolved over `type(obj).__mro__`, seeded with the current three, plus `register_binder`. This is what lets a particle system, lighting pass, or a `.tmx` object layer bind without editing `renderer.py`.

Add `scripts/core/errors.py` with `PyoneerError` and `BindError`, `DepthNotFoundError`, `MissingCameraError`, `ComponentNotFoundError`, `SceneError`. Convert all seven bare-`Exception` sites (`renderer.py` 253/276/293/303, `scene_manager.py:42`, `component.py:390`, `depth_data.py:18` — the last dies with its file in Segment 6) and replace the three tuple-form raises with f-strings. Without this, a game that wants to survive an AI-authored `.tmx` referencing an unknown layer name can only write `except Exception`, which also swallows every real bug.

**7.g — Fix the singleton and the double update.** `CoreAssetManager.__init__` (`core_asset_manager.py:29`) re-runs on every construction, rebinding all five sub-managers. It is constructed at import time in `component.py:16` and `window.py:25` plus `main.py:154`, so all config JSON is re-read three times at startup and `MainGame.input` (`main.py:155`) desyncs from `Config.inputs`. Add an `_initialized` guard. Delete `main.py:266` (`SceneManager.update` at `scene_manager.py:58-59` already drives the renderer — currently **2 calls/frame**). Take the renderer in `SceneManager.__init__` so `__bind_camera`'s dereference of `self.renderer` (:28) cannot precede it.

### Verify
`triple_prepare` counter goes 3 → 1 per component; `LayerRenderer.update` 2 → 1; `PyoneerEvent` allocations 25.8 → ~3 per frame. New test: `SceneManager.bind` then `SceneManager.unbind` leaves the object absent from *both* `scene.__objects` and `renderer.layers`, and the frame's blit count drops accordingly. `frame_hash` unchanged.

**Risk:** medium. **Size:** M.

---

# Segment 8 — GameComponent decomposition *(the named priority)*

**Resolves:** `monolith-decomposition`, `screen-area-mangled-shadow` / `panel-shadows-screen-area-breaking-clipping`, `use-immediate-viewport-no-inherit`, `move-drops-local-bounds`, `transform-scale-signature-clash`, `bind-component-no-parent-no-dedupe` (parent-link half), `parent-changed-never-dispatched`, `async-module-vestigial`, `draw-blits-rect-churn-and-viewport-walk`, `core-image-attributeerror` (storage unification half)

677 lines carrying nine responsibilities. Everything in Segments 3–7 was a prerequisite: the broken lookups now work, the event contract is settled, depth is composite, and the harness can prove behavior is preserved.

### Changes

Extract in this order — **lowest risk first, each independently landable, each keeping the existing public method names as thin forwarders** so no widget file changes in the same commit.

**8.1 — `Transform2D`** (`scripts/core/transform2d.py`). Owns local/world `Rect`, offset, parent ref, `set_local`, `set_world`, `recompute()`. Single-underscore fields, no properties shadowing name-mangled state.
- Fixes `move-drops-local-bounds` by construction: `component.py:169-170`'s parented branch writes only `__world_bounds`, so `__update_world_bounds` recomputes from stale `__local_bounds` and the move is erased on the next parent transform. `move()` gets exactly one authoritative write (local) with world derived.
- Fixes `screen-area-mangled-shadow`: `GameComponent` has four properties backed by `__`-mangled state (`__local_bounds`, `__world_bounds`, `__screen_area`, `__working_area`), and `Panel` re-declares `screen_area` into `_Panel__screen_area`, forking the rect. Rename to single-underscore and make every internal read go through the property — `clipped_working_area` currently reads the raw attribute and gets 340×162 where `Panel.screen_area` reports 1000×1000. Then delete `Panel`'s override, or rename its concept to `scrollable_area`, which is what it actually is.
- Rename `DrawComponent.scale(width, height, destination)` (`draw.py:58`) to `resize_image(...)` — it is a surface operation colliding with `GameComponent.scale(Vector2, sender)`, and a TRANSFORM event carrying `scale` crashes every drawable.

**8.2 — `EventBus`** (`scripts/core/event_bus.py`). Callbacks dict, bind/unbind, dispatch, `handled` semantics, `__create_event`. Segment 5 already decided the semantics; this makes them a single testable object rather than eleven methods on a god class.
- Collapse the **four** parallel listener registries onto it: `callbacks`, `async_callbacks` (`async_.py:33-38`, identical in shape to `bind_sync_listener`), `mouse_listeners` (`mouse.py:70-98`), `key_callbacks` (`keyboard.py:82-98`). A contributor binding MOUSE_DOWN currently has four plausible entry points, three of which silently do nothing — which is exactly the `button-consume-click-never-fires` bug.
- Rename `async_.py` → `buffered_events.py` and `AsyncEventComponent` → `BufferedEventComponent`. **WONTFIX making it actually async**: there is no `async def` or `await` anywhere in the widget tree; it is a synchronous buffer drained on UPDATE in the same frame it is filled. Stop the name promising concurrency. Delete the tautological `isinstance(self, AsyncEventComponent)` at `async_.py:77` and the `event` rebinding at :82.

**8.3 — `ComponentRegistry`** (`scripts/core/component_registry.py`). The children dict, bind/unbind, snapshot iteration, spatial queries.
- `bind_component` becomes atomic: registration **and** `component_in.bind_parent(self)`. Today they are two independent wiring steps (`bind_component` never touches `parent`; the link is set via the `parent=` kwarg at construction) with no consistency check, so a component bound without `parent=` receives events but computes `world_bounds` as if it were root-level.
- Consolidate reparenting onto one path: the `parent` setter (`:158-160`) currently assigns `__parent` without updating world bounds, `bind_parent` (`:358-370`) updates them inline, and the `PARENT_CHANGED` listener bound at `:118` can never fire because nothing dispatches it. Make the setter delegate to `bind_parent`, have `bind_parent` dispatch `PARENT_CHANGED` with `{'old','new'}`, and let `__on_parent_changed` own the bounds update.
- Return dict keyed by `component.uuid` (`:584`) while the input dict is keyed by name — pick one identity scheme.

**8.4 — `ViewportResolver`** (`scripts/core/viewport.py`). `is_view`, screen/working area, the fixed skip-count ancestor walk from Segment 3.
- Make `use_immediate_viewport` **inherited, not copied**. The setter at `:141-145` pushes into children present at assignment time, which is why `ScrollComponent.__init__` sets it at `scroll.py:49` (children not yet built) and then re-sets all four by hand at `scroll.py:178-181`. Store `bool | None` and have the getter fall back to the parent. **Order matters**: fix the ancestor walk (Segment 3) *before* this, or inheritance spreads the `None`-viewport result further.
- Cache `get_viewport_component`'s result (59 calls/frame, each a parent-chain walk), invalidated in `bind_parent` and the `is_view`/`use_immediate_viewport` setters. Then flatten `DrawComponent.__blits` (`draw.py:74-116`): read `event.data["layer_depth"]` once instead of twice, drop the `destination` Rect at 105–108 (used only for `.x`/`.y`), and cache the composed `drawn_section`/destination pair, recomputing only on TRANSFORM.
- Decide whether `working_area`, `screen_area` and `clipped_working_area` are three concepts or one. Currently `working_area` is what the draw path uses and the other two have zero callers.

**8.5 — Unify image storage.** One `_image` slot per object, set in `PyoneerGameObject.__init__`, used by `GameComponent.core_image` and `DrawComponent` alike, instead of one mangled slot per class in the MRO (`_PyoneerGameObject__image`, `_GameComponent__image`, `_DrawComponent__image`).

**8.6 — What stays on `GameComponent`:** lifecycle wrappers and interaction flags (`visible`/`focused`/`active`/`clickable`/`draggable`). That is the actual public surface. Replace `is_clickable`'s hard-coded `self.get_component("mouse")` string lookup with the now-working `get_component_by_type`.

### Verify
This is the segment the harness exists for. After **each** of 8.1–8.6: `frame_hash` identical, `component_census` identical, all `dispatch_counters` identical or lower, `frame_ms` not worse than the Segment 4 baseline. Any drift means a forwarder is wrong. Add unit tests per extracted object (they are now testable in isolation, which was impossible before).

**Risk:** **high**. **Size:** L.

---

# Segment 9 — Widget hardening and demo extraction

**Resolves:** `gamewindow-hardcodes-test-widgets`, `panel-attach-vs-bind-dichotomy`, `panel-background-sized-to-virtual-content`, `scroll-thumb-never-resizes`, `button-consume-click-never-fires`, `mouse-drag-events-unbindable`, `mouse-down-time-unit-mismatch` / `mouse-drag-time-unit-mixing`, `widget-color-copy-breaks-pygame-contract`, `image-loads-from-disk-uncached`

With the base class split and the event contract settled, the widgets can be cleaned without fighting the framework.

### Changes

- **Strip `GameWindow` to chrome.** `window.py:126-162` constructs a checkbox, two Panels, a TextBox and four more checkboxes inside `core_prepare`, at literal offsets like `Rect(4, header_height + 4 + 40 + 4 + 40 + 4 + 40 + 4, 40, 40)`. Worse, `__event__mouse_clicked_inside` (`:268-294`) dereferences `self.text_box` in four branches with no `None` guard, so removing the demo widgets makes every left-click an `AttributeError`. Reduce to `body`, `header_bar`, `header_text`, `close_button`, `mouse`, `keyboard`; replace the text_box-specific logic with a generic focus protocol (set `focused` on the hit widget, clear it on the previous one) so the window never names a concrete child type. Move the demo tree to `scripts/game/demo_window.py` so `main.py` still renders the same thing. This is the single biggest blocker to the class being usable by anyone but its author: one empty 400×400 window instantiates **112 components**.
- **Delete `Panel.attach_component`.** `panel.py:115-126` accepts `depth` and `offset` and ignores both, calls `bind_component`, then *also* appends to a shadow `self.children` list. The `get_components_at`/`get_clickable_components_at` overrides (`:128-140`, `:148-160`) then iterate only `children`, so the panel's own `vertical_scroll`, `horizontal_scroll`, `background` and `dead_corner` are invisible to hit-testing — and the offset the overrides exist for is always `Vector2(0,0)`, because `__offset_children` sets offset on the *children*, never on the Panel. Delete `attach_component`, `__add_child`, `self.children` and both overrides; store the scroll offset on the Panel so the inherited `adjusted_position` does real work.
- **`panel.py:43`** → size the background from `local_bounds`, not `screen_area`. Verified: `Panel(bounds=Rect(0,0,200,200), working_area=Rect(0,0,1000,1000))` allocates a **1000×1000** surface — 4 MB for a 200×200 visible panel, 96% never seen; a 4000×4000 document allocates ~64 MB. Nothing about a scroll viewport requires a content-sized surface when rendering is a deferred blit pool. This directly gates the scrollable `.tmx`-editing surface in Segment 11.
- **Make bounds changes propagate to surfaces.** `scroll.py:190-191` reassigns `local_bounds` on `scroll_bar` and `scroll_thumb`, but the `Button`'s `body` `ShapeComponent` keeps its construction-time bounds and surface. Verified live: on the **first** scroll, `scroll_bar.local_bounds` goes `(326,0,14,134)` → `(326,14,14,120)` while its body surface stays `(14,134)` — the bar graphic is drawn 14 px taller than its logical bounds and offset from them, today. Add `DrawComponent.resize(w, h)` that reallocates the surface and re-fires PREPARE, plus a bounds-changed hook on `GameComponent` that cascades it.
- **`button.py:65`** → `self.mouse.bind_mouse_listener(GameEventType.MOUSE_DOWN_INSIDE, self.__consume_mouse_click)`. It currently registers into `GameComponent.callbacks`, but `MOUSE_DOWN_INSIDE` is produced only by `MouseComponentAsync.__execute_event_callbacks` (`mouse.py:187`), which reads `mouse_listeners`. `consume_click` is dead configuration. Add `if event is None: return` at :68. (After 8.2's registry collapse this becomes moot — do it now anyway; it is one line and unblocks the scroll cleanup.)
- **`mouse.py:16-30`** → add `MOUSE_DRAG_BEGIN` and `MOUSE_DRAG_END` to `EVENT_TYPES`. Both are *emitted* (`:257`, `:236`) but absent from the gate list, so `bind_mouse_listener` silently refuses them and the emissions are no-ops. This is why `GameWindow` and `ScrollComponent` each keep their own `dragging_component`/`dragging_scroll_thumb` boolean cleared from a MOUSE_UP handler that must run before the spurious unconditional `MOUSE_DRAGGING` at `:233` — an undocumented ordering dependency. Remove that unconditional emission.
- **`mouse.py:181/244/253`** → split the press timestamp from the elapsed duration. `mouse_down_time` is assigned `pygame.time.get_ticks()` (absolute ms) at :181, then `+= EventManager.FRAME_DELTA` (seconds) at :244, then compared against `mouse_drag_delay = 0.5` at :253. After 500 ms of uptime that comparison is unconditionally true, so both the 0.5 s hold threshold and the 10 px travel threshold are permanently bypassed. (Note `FRAME_DELTA` is `(ms_delta)/target_tick_rate` — not seconds at all under the current config; give the unit one owner while you are here.)
- **`widget_color.py:31`** → delete `copy = set`. It replaces `pygame.Color.copy()` (no args, returns new) with a one-arg mutator; `WidgetColor(...).copy()` raises `TypeError`. Rename `set` → `set_from`. Fix `:50-51, :55` to use `is not None` instead of truthiness so `scale_alpha(0)` and `opacity(0)` stop being no-ops.
- **`image.py`** → forward `image_in` to `super().__init__` at :16 (currently `DrawComponent` allocates a full world_bounds surface that `ImageComponent.core_image` never returns), route string paths through `CoreAssetManager` instead of a bare per-instance `pygame.image.load`, and clip the section at :53 (`self.section.clip(self.base_image.get_rect())`) like the sibling `image_snip` already does.

### Verify
`component_census` for a bare `GameWindow` drops from 112 to ~8. `main.py` renders the identical frame via `demo_window.py` — `frame_hash` unchanged after the move. New tests: clicking a `Panel`'s scrollbar resolves the scrollbar as top widget; `Panel(bounds=200×200, working_area=1000×1000)` background surface is 200×200; scrolling then reading `scroll_bar.body.core_image().get_size()` matches `scroll_bar.local_bounds.size`.

**Risk:** medium. **Size:** M.

---

# Segment 10 — Entity, input and camera

**Resolves:** `input-released-latches-true-forever`, `input-multi-binding-self-cancels`, `input-controller-map-missing-config-keys`, `input-pressed-is-held-and-raises-on-unknown`, `entity-transform-arg-ignored-mutable-default` / `entity-transform-arg-silently-dropped`, `entity-move-direction-allocates-transform`, `camera-update-four-branch-duplication`, `camera-clamp-uses-width-not-right`, `camera-updates-before-scene-one-frame-lag`, `viewport-move-argument-silently-ignored`, `animation-order-never-plumbed`

**Independent of Segments 5–9** — assign to a second worker or interleave any time after Segment 1.

### Changes

- **`scripts/core/input.py` — one pass, three edges.** Replace `_pressed`/`_released`/`_held` (91–151, ~60 lines of triple-duplicated scanning) with:
  ```python
  for action in self.actions.values():
      raw = self._raw_down(action, keyboard_snapshot)
      action.pressed  = raw and not action.held
      action.released = action.held and not raw
      action.held     = raw
  ```
  This fixes three findings at once: `released()` currently reads `True` on frame 1 with no key ever pressed (it is a level, not an edge); `_pressed` ORs "is down" while `_released` ORs "is not down" over the same binding list, so any action with two satisfiable bindings self-cancels; and `pressed()` means "held" with no edge available at all, which the first jump/interact/confirm feature will need.
  Rename to `down(name)` / `just_pressed(name)` / `just_released(name)`, each via `self.actions.get(name)` returning `False` when absent — `input.pressed('jump')` before `jump` exists in `inputs.json` currently raises an uncaught `KeyError` mid-frame.
  Resolve binding names to codes **once** in `BaseAction.__init__` and raise a clear `Unknown binding 'gamepad:button_0'` at load. `CONTROLLER` (`:33-39`) is missing every name `config/inputs.json` actually uses, and `pygame.key.get_pressed()[None]` raises `TypeError` on any keyboard typo. **Defer actual gamepad support** — `set_gamepad()` has zero callers; just make the config validate.
- **`game_entity.py:30`** → honor the `transform` argument: `self.transform = transform.copy() if transform is not None else Transform(position=position, ...)`. Currently every entity is unconditionally constructed at (0,0) and `main.py:107/113` works around it with `moveto()`. **Change the three shared mutable defaults in the same commit** — `game_entity.py:51`, `:108`, and `game_player.py:36` (`world_transform=Transform()`, the one on the live path, missed by the original finding) → `None`. Fixing the drop without the defaults converts a placement bug into a shared-state bug where moving one entity moves all of them.
- **`game_entity.py:88`** → replace the throwaway `Transform()` and string-compare dispatch with a module-level `_DIRS = {"left": (-1,0), ...}` and direct arithmetic. Also removes a latent bug: `if sprint: changes.position *= self.sprint_mult` is correct only because each call happens to touch one axis. (`sprint` is never passed `True` by any caller — dead today.)
- **`game_camera.py:55-102`** → collapse the four near-identical `isinstance` branches into one `_anchor()` helper + one dirty-check + one clamp (~48 lines → ~15). They currently *disagree*: `:64` uses `transform.position` (a center), `:76` uses `topleft`, `:88` uses `(world_bounds.x, y)`, and all four assign to `view_area.center`. Only `:81` copies the vector. **Decide once whether `transform.position` is a center or a topleft** — the camera says center, `renderer.py:100-101` says topleft, and that disagreement is the root of the cull-rect bug fixed in Segment 3.
- **`game_camera.py:111-118`** → `Rect.clamp_ip(self.full_area)`, plus an explicit center when `full_area` is smaller than `view_area` in either axis. The current code uses `.width`/`.height` (assuming `full_area.x == 0`) and produces negative origins on sub-window maps — reproduced: a 320×320 map against an 800×600 view yields `view_area = (-480, -280, 800, 600)`, which then reaches `blits()` as a negative-origin `draw_area`.
- **`scene_manager.py:56`** → move `self.camera.update()` from `update()` to `post_update()`. The camera currently reads `target.transform.position` *before* `GamePlayer.input_move` mutates it, so it renders one tick behind (~2.2 px of constant lead at the configured speed). This is precisely what the pre/update/post split exists for.
- **`game_animation.py`** → plumb `DataAnimationCategory.order` (parsed from `animations.json`, stored on the category, never reaching `GameAnimation.frame()`), or better: pre-slice every frame's `Surface` at load in `_build_animations` where the order is already known, making `image()` a list index. That also retires the consuming-`frame_changed()` dirty flag and the O(n) `_active_animation()` scan in one move.
- **`game_map.py:34-35`** → `return super().core_dispose(event)`. Annotated `-> bool`, returns `None`, while `Layer.core_dispose` returns `True` — inconsistent on the same lifecycle contract, and it fails the moment scene unloading exists.

### Verify
`frame_hash` unchanged (the camera timing fix moves the view by ~2 px — capture and eyeball once, then re-baseline). New tests: `released('left')` is `False` on frame 1 and stays `False` until a real press-and-release; `GamePlayer(world_transform=Transform(position=(500,300))).transform.position == (500,300)`; `GameCamera(Vector2(800,600), Rect(0,0,320,320)).update(Vector2(160,160))` produces a non-negative, centered `view_area`.

**Risk:** low. **Size:** M.

---

# Segment 11 — Map I/O boundary and factory *(the .tmx authoring goal)*

**Resolves:** `map-loader-empty-dead-package` / `loaders-package-empty`, `component-factory-dead` / `component-factory-and-align-unwired`, `maplayer-full-map-surface-memory`

Everything before this was prerequisite. This is the segment that serves the stated goal: a human edits in Tiled, an AI edits programmatically, both against one boundary.

### Changes

**11.a — Claim `scripts/loaders/map_loader.py`.** Today it is two 0-byte files, while map loading is split across `config/managers/map_data.py` (pytmx file I/O) and `renderer.py:197-217` (rasterization), with `GameMap` owning neither. Move the pytmx load into `MapLoader` and give it a **save** path — **pytmx is read-only**, so writing `.tmx` needs an `xml.etree` round-trip that preserves Tiled's element order, custom properties and tileset references so a human reopening the file in Tiled sees no spurious diff. This is the load-bearing constraint: a lossy writer makes the human/AI co-authoring workflow impossible after the first AI edit.

Design the API around Tiled's actual document model, not the renderer's: `MapLoader.load(path) -> MapDocument`, `MapDocument.layer(name).set_tile(x, y, gid)`, `MapDocument.object_layer(name).add(...)`, `MapLoader.save(doc, path)`. `LayerRenderer` consumes a `MapDocument`, never a file path.

**11.b — Chunked map baking.** Now, not earlier — it only matters once maps get big, but it gates every generated map of interesting size. `renderer.py:206` allocates one full-map surface per tile layer: 40.96 MB for the shipped 100×100@16px map; a 200×200@32px map is **163.8 MB per layer**. Cache per-chunk surfaces (16×16 tiles) keyed by chunk coordinate; `core_blits` emits one token per chunk intersecting `camera.view_area`; evict outside a camera margin. Bounds memory at O(viewport) instead of O(map), and incidentally makes the two sparse layers (99.6% and 98.2% transparent) stop paying a full-viewport alpha blend to deliver <2% coverage. Combine with Segment 4's two-surface composite: composite *within* a chunk, per depth band.

Add `MapDocument.invalidate(chunk_coords)` so a programmatic tile edit re-bakes one chunk rather than the whole map — that is what makes AI authoring interactive rather than a restart.

**11.c — Wire `ComponentFactory`.** `scripts/core/ui/widget/factory/component_factory.py` is a complete, correct, name→constructor registry connected to nothing (`main.py:24, 49-50` are commented out; `COMPONENT_POOL` is permanently empty). It is exactly the seam a declarative UI or `.tmx`-object-layer description resolves against. Have each container module self-register at import (`ComponentFactory().register('Panel', Panel)` for `Panel`, `Button`, `Checkbox`, `TextBox`, `GameWindow`, `ImageComponent`, `TextComponent`, `ShapeComponent`), call `mark_ready()` after the widget package imports, and build the demo window's children through `factory.make(...)`. Drop the dead imports at lines 1–2 and rename the `callable` parameter (shadows the builtin) to `constructor`. Then register the same factory as a `LayerRenderer` binder (Segment 7.f) so a `.tmx` object layer can spawn entities and widgets by name.

**11.d — Round-trip test.** `tests/test_tmx_roundtrip.py`: load `data/maps/test.tmx`, save to a temp path, assert byte-level or canonical-XML equality. Then: load, `set_tile`, save, reload, assert the one tile changed and nothing else did.

### Verify
```bash
.venv/Scripts/python.exe -m pytest tests/test_tmx_roundtrip.py
.venv/Scripts/python.exe tools/smoke.py --frames 120 --out run.json && \
.venv/Scripts/python.exe tools/compare.py tools/baseline.json run.json
```
`frame_hash` unchanged after chunking (this is the assertion that makes chunking safe). Memory census: 40.96 MB of map surfaces → bounded by viewport + margin. New test: a 200×200@32px generated map loads and renders under 50 MB.

**Risk:** medium (11.b changes the render path; the frame hash is the guard). **Size:** L.

---

# Explicitly DEFERRED

| Finding(s) | Why deferred |
|---|---|
| `maplayer-full-map-surface-memory` (chunking) | Real, but 41 MB is harmless today. Deferred to S11 where it is a prerequisite for generated maps rather than speculative work. |
| `input-controller-map-missing-config-keys` (gamepad half) | `set_gamepad()` has zero callers. S10 adds **load-time validation** so a bad binding fails loudly; actual gamepad support waits for a real requirement. |
| `listbox-and-grid-dead-chain` | Iceboxed in S2. A list box is worth having, but `ListBoxComponent`/`GridComponent` have literally never executed a single method. Re-derive on the post-S8 base class rather than debugging cold code. |
| `blittoken-stores-live-rect-references` (full motivation) | The copy-on-ingest fix lands in S3 because it is two lines. The *reason* it matters — second camera, retained/interpolated frames, threaded flush — is deferred; do not build those on the current renderer. |
| `image-loads-from-disk-uncached` (asset-manager routing) | `ImageComponent` is never instantiated. S9 fixes the surface-waste and the unclipped subsurface; full `CoreAssetManager` routing waits for S11, when the tileset palette actually needs shared surfaces. |
| `draw-blits-rect-churn-and-viewport-walk` (Rect caching) | The viewport-walk cache lands in S8.4. Caching the composed `drawn_section`/destination pair is deferred until there is a reliable bounds-changed hook (S9) to invalidate it — cached stale bounds is a worse bug than the allocation. |
| `translate-linear-enum-scan` beyond the dict fix | The dict lookup lands in S5. Per-frame event coalescing (the thing the dead pooling branch was reaching for) is deferred until a profile shows motion floods actually mattering; it needs `pygame.event.get(eventtype=...)`, not a wrapper-level dedupe. |

# Explicitly WONTFIX

| Finding | Decision |
|---|---|
| `event-listener-decorator-noop` (×2), `component-event-listener-noop-decorator`, `event-decorator-dead-unimportable` | **Delete, do not implement.** A `@staticmethod` decorator cannot register a per-instance callback without a metaclass or `__init_subclass__` collection pass. `bind_sync_listener` is the mechanism; document it as the only one. |
| `event-priority-cold-only` | **Delete `EventPriority`.** Listener-level priority is speculative; the blit pool already has a working `priority` field for the case that actually exists (render order). Adding a second, unrelated priority concept to the event bus during its extraction is exactly the wrong time. |
| `send-event-advanced-wrong-variable` | **Delete the feature, not the bug.** The `manager` access-control gate (`component.py:100-104`, `:358-363`, `:575`) is a second authorization layer on an event bus that already has `handled`, `visible`, and `trickle`. `bind_manager` is never called with `True`. Remove the field and the guard. |
| `scale-rotation-write-only`, `transform-scale-signature-clash` (the `scale` event key) | **Do not implement `scale`/`rotate` on `GameComponent`.** The blit path is `BlitPool.blit_to_layer` → `surface.blits`, which has no rotation or scale slot — the values *cannot* be honored. Delete the write-only fields and remove `scale`/`rotation` from `__transform_component`'s vocabulary so the event contract stops advertising them. Revisit only if the renderer grows a transform stage. |
| `camera-scale-and-offset-type-unimplemented` | **Delete the parameters.** `scale` needs a `pygame.transform.scale` stage in `render()` plus a divide in the entity blit offset; `offset_type` needs the branch collapse. Both can return *with* those features. Accepting them silently today is worse than not offering them. |
| `async-module-vestigial` (the async part) | **Never make it async.** pygame's event pump and surface operations are not thread-safe in the way this would need. S8.2 renames it to `BufferedEventComponent` and collapses it into the one bus. |
| `pump-pyo-pooling-branch-dead` (the pooling design) | **Do not repair the branch.** Pooling keyed on "previous event was PYGAME" merges heterogeneous event types into one wrapper — the design is wrong, not just the comparison. Delete it and the macOS `__PROBLEM_EVENTS` dedupe with it. |
| `get-blit-pool-unused-wrong-annotation` | **Delete rather than fix the annotation.** The `pygame` variant is the only one on the hot path; a second snapshot API with shallow-copy aliasing semantics is a trap, not a feature. |
| `bare-exception-no-error-taxonomy` (the commented `try/except`) | Do **not** restore the commented-out `try/except Exception: print(e)` at `renderer.py:298-301`. S7.f gives you typed exceptions to catch selectively; a blanket catch around the main blit would swallow every bug the rest of this plan exists to surface. |

---

## Two things to watch across the whole plan

**Do not trust cProfile numbers from the review.** Three findings quote cumulative profiler time as real cost and are inflated ~4×: `blitpool-dict-of-dict-rebuilt-each-frame` (claims 0.74 ms/frame, real 0.017 ms), `send-event-to-children-allocates-dead-dict` (claims #2 hotspot, real 0.035 ms), `has-callback-uses-keys-contains` (claims 3.4%, real 1.1%). They are all still worth fixing — they are one-line deletions — but do not budget a segment around them. The three *real* measured wins are the map composite (1.76 ms), the depth-property cache (0.32 ms), and the spritesheet convert (15.6× per sprite blit, which only bites above ~50 entities).

**`frame_hash` is the contract.** Segments 2, 4, 6, 7, 8 and 11 must all leave it unchanged; Segments 3, 5, 9 and 10 change it in exactly one enumerated way each. If a segment that should be invisible moves the hash, stop and find out why before committing — that is the failure mode this whole plan is structured to catch, because every remaining bug class in this engine (wrong depth, dropped dispatch, stale surface, unclipped viewport) is silent.