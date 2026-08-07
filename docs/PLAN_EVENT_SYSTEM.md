Probes cleaned up. Here is the corrected plan.

---

> ## CORRECTION (verified after this document was written)
>
> This plan's V5 table lists `Panel.core_lifecycle_build` and
> `ScrollComponent.core_lifecycle_build` as running "0 times" and marks them for
> deletion. **That is wrong, and acting on it destroys the window.**
>
> `GameComponent.bind_component` (`scripts/core/component.py:442-449`) calls
> `core_lifecycle_prepare_pre/prepare/prepare_post/build` **directly**, not through
> the event bus. Measured on the live scene: `Panel.core_lifecycle_build` runs
> **2x**, `ScrollComponent.core_lifecycle_build` runs **4x**, and between them
> they construct most of the UI.
>
> What the `event=None` hole actually swallows is only the **listener fan-out
> inside** those methods -- `send_event_advanced` requires a non-None event. The
> methods themselves run fine. Re-derive the V5 table by instrumenting real call
> counts before migrating anything.

# PYONEER — EVENT SYSTEM REPAIR PLAN (corrected)

## 0. Why the draft needed rewriting

The draft was written against a version of `scripts/core/component.py` that no longer exists. That file is now **771 lines**, not 677, and another worker has already landed roughly half of what the draft proposes. Every line number in the draft is wrong, and five of its ten segments are either already done or now actively harmful.

The draft also claimed its measurements came from five probes in `tools/`. **Those files do not exist.** `tools/` contains `_bootstrap.py`, `baseline.json`, `check_animation.py`, `check_events.py`, `check_imports.py`, `check_input.py`, `check_singletons.py`, `smoke.py` (plus another worker's live `_adv_probe_*`/`check_window.py`). Everything below was re-measured this session with throwaway probes that have since been deleted.

### Already landed — do not re-do

| draft claim | reality |
|---|---|
| "`handled` breaks only the local loop; nothing has ever consumed an event" | **Fixed.** `component.py:570` entry guard, `:582` post-callback `return`, `:673` child-loop `break`. Measured: consumer at `root/body` fires, **1 of 129** tree nodes sees the event afterward (itself). |
| "`PyoneerEvent.trickle` read at zero sites — DELETE" | **Read at 3 sites** (`component.py:570, 582, 673`) and asserted by `tools/check_events.py` → *"trickle overrides consumption"*. It is now the deliberate escape hatch. Deleting it deletes a tested feature. |
| "gate input on `active`" (§3, all of E9c) | **Installed.** `component.py:576` gates on `INPUT_EVENT_TYPES`; `accepts_input` property at `:586` returns `self.active`; `INPUT_EVENT_TYPES` frozenset at `:18-30`. `check_events.py` asserts hidden-but-active still receives input and inactive receives none. |
| "biggest risk: 95 components are `active=False`" (E9b) | **False.** `component.py:73` defaults `active: bool = True`. Measured `active_false_total = 0`, `active_true_total = 129`. |
| "split focus off `active`" (E9a) | **Done.** `component.py:103` `focused`, `:118` `focusable`, `:594` `accepts_focus`. `window.py:284/300/303/305` and `text_box.py:29/73/93/98/107` all use `focused`. |
| "mutate/unbind during dispatch → RuntimeError" (E10) | **Fixed.** `component.py:604` snapshots callbacks, `:671` snapshots `self.components.items()`. Measured: `"no error"`. |
| "E5 ⚠ EXPECT DRIFT; `frame_hash`/`blit_tokens` will move" | **False.** I simulated the whole None-hole fix by wrapping `GameComponent.core_prepare`/`core_build` and ran `smoke.run(60)`: **NO DRIFT**. Simulated it again *with `Panel.core_update`'s body resurrected as a bound UPDATE listener*: still **NO DRIFT**, `visible_flip = 0`. |

### Three defects the draft missed

**(A) The same object is bound under two names.** 113 unique components, **129 walk-visits**. `ScrollComponent` binds one `Button` as both `thumb` and `scroll_bar`, dragging its `mouse`/`background`/`text` children along — 4 scrolls × 4 nodes = 16 duplicate visits. Every event reaches those nodes **twice**, and any listener bound on them fires twice per delivery. This must be fixed before any consumption or ordering work, because it changes what "the first claimant" means.

**(B) Input handlers do not run during the input dispatch.** Measured by binding a `MOUSE_DOWN` listener to all 30 mouse behaviors and recording the dispatch phase at fire time:

```
phase_counts: { "UPDATE": 54 }      <-- zero during INPUTS
fire_order:   root/close_button/mouse, root/mouse, root/checkbox/mouse, ...
```

`AsyncEventComponent` buffers on `INPUTS` (`async_.py:28`) and replays on `UPDATE` (`async_.py:29 → :74`). So real handler order is the **UPDATE** traversal — top-down, insertion order — not the input traversal. **The draft's E8 (sort the input fan-out deepest-first) is a no-op until the async buffer is deleted.** So is most of E7.

**(C) The draft's E4 breaks input, and it is scheduled before the fix.** E4 changes the routing key from `INPUTS` to `event.type`. `AsyncEventComponent.__init__:28` is `bind_sync_listener(GameEventType.INPUTS, self.buffer_custom_events)` — the *only* reason `INPUTS` means anything. Landing E4 before E6 leaves the engine with zero input for one segment.

---

## 1. The override contract

**`bind_sync_listener` is canonical. `core_*` is not an extension point.**

`send_event_to_children_advanced` (`component.py:675`) calls the child's `send_event_advanced`, never its `core_update`. A `core_*` override on an in-tree class is therefore unreachable **after bind time**. Measured over 5 steady frames: `Panel.core_update`, `Panel.core_build`, `Panel.core_prepare`, `GameWindow.core_prepare`, `ScrollComponent.core_build`, `MouseComponentAsync.core_prepare` — **0 calls each**.

> **Rule.** A `core_*` override is legal only on a class invoked from outside the component graph: `GameScene`, `Layer`/`EntityLayer`/`GameComponentLayer`/`MapLayer`, `GameEntity`/`GamePlayer`/`GameMap`, and the single root `GameComponent` bound into a `GameComponentLayer` (`renderer.py:139`). Anything reached through `self.components` uses `event_bind`.

Enforcement is **one assertion inside the existing `tools/check_events.py`**, not a new tool: walk the live tree, collect `type(node)` for every node with a parent, fail if any of those classes has a `core_` key in `vars()`.

### In-tree migration list (verified against current line numbers)

| site | verdict | action |
|---|---|---|
| `containers/panel.py:35` `Panel.core_prepare` | pure `super()` passthrough | delete |
| `containers/scroll.py:52` `ScrollComponent.core_prepare` | pure `super()` passthrough | delete |
| `containers/panel.py:38` `Panel.core_build` | real body | `event_bind(BUILD, self.__build_panel)` |
| `containers/scroll.py:55` `ScrollComponent.core_build` | real body | `event_bind(BUILD, self.__make)` |
| `containers/window.py:88` `GameWindow.core_prepare` | real, guarded by `flags["prepared_window"]` (`:90, :208`) | `event_bind(PREPARE, self.__build_window)` |
| `behavior/mouse.py:100` `MouseComponentAsync.core_prepare` | real; 4 binds behind `flags["prepared_mouse"]` | move the 4 binds into `__init__`, delete override + flag |
| `containers/panel.py:194` `Panel.core_update` | real body, 0 calls/frame | `event_bind(UPDATE, ...)` — **but see §5, it is not free** |
| `component.py:741` `GameComponent.core_image` | returns `self.__image` → `_GameComponent__image`, **assigned nowhere**; only `_DrawComponent__image` exists (`draw.py:23/28`) | `raise NotImplementedError` |
| `widget/draw.py:65`, `widget/image.py:59` `core_image` | real, called by `draw.py:111/115`, not dispatched | keep |
| `behavior/transform.py:22` `GameTransform.core_prepare` | dead class, 0 importers (grep), 0 instantiations | archive whole file |

### Signature drift outside the tree (fix while touching)

- `renderer.py:40` `Layer.core_prepare(self)` drops the ABC's `event` parameter entirely; `:127` `GameComponentLayer.core_update(self, delta)` and `:170` `MapLayer.core_update(self, delta)` disagree with `:43` `Layer.core_update(self, event)`. All three bodies are `pass`. Unify to `(self, event=None)`.
- `game_scene.py:90/95/100` take `delta: float` and build the event internally; the ABC says `Optional[PyoneerEvent]`. Move construction into `scene_manager.py:50-62`.
- `renderer.py:59` `Layer.core_inputs(self, events: list[pygame.event.Event] | ...)` — actually receives a `PyoneerEvent` from `game_scene.py:115`.
- `draw.py:61` `dispose_drawable(self)` has **no `event` parameter** and is bound to `DISPOSE` at `:54`. Latent — `core_dispose` is dispatched by nothing today.

---

## 2. Consumption semantics — already correct, leave alone

`component.py:564-584` is the current dispatcher, and it is right:

```python
def __send_event(self, typ, event, *args, **kwargs):
    if event is not None and event.handled and not event.trickle:
        return                                   # GUARD 1 - entry
    if typ in INPUT_EVENT_TYPES and not self.accepts_input:
        return                                   # GATE - active, never visible
    if self.__has_callback(typ):
        for callback in self.__get_callback(typ):
            callback(event, *args, **kwargs)
            if event is not None and event.handled and not event.trickle:
                return                           # GUARD 2 - stops the fan-out
    self.send_event_to_children_advanced(...)
```

Plus `component.py:673` breaks the child loop once a child consumes. `tools/check_events.py` locks all of it in. **No change required.** The one real gap is that consumption is not *type-gated*: a stray `event.handle()` inside a `BLITS` callback would blank the rest of the UI, because `DrawComponent.__blits` shares one `PyoneerEvent` across all 113 components. Add `CONSUMABLE_EVENTS` in V3 and make GUARD 1/2 consult it.

`trickle` **stays**. It is read at three sites and asserted by an existing test. It is the per-event override for "reach children anyway."

---

## 3. Bloat inventory (re-verified)

### Dispatch surface — `scripts/core/component.py`

| method | line | callers | action |
|---|---|---|---|
| `send_event_advanced` | 626 | 14 internal | rename `event_send`; delete the 4-branch polymorphism at 649-660 |
| `send_event_to_children_advanced` | 662 | 6 | fold in as `_event_send_children` |
| `send_event` | 618 | 1 (`panel.py:104`) | delete, rewrite the caller |
| `send_event_to_children` | 622 | 0 | delete |
| `send_pygame_event` | 614 | 0 | delete |
| `send_empty_event` | 680 | 0 | delete — both branches drop on the None hole |
| `event_listener` | 539 | 0 | delete — the decorator binds nothing; `wrapper` never touches `self.callbacks` |
| `mark_event_handled` | 687 | 4 (`mouse.py:157,165`; `window.py:289,293`) | delete → `event.handle()` (`event_manager.py:45`) |
| `events()` / `rebuild()` | 705 / 709 | 0 / 0 | delete — `CUSTOM_EVENT`, `REBUILD` bound nowhere |
| `manager` + `bind_manager` | 139, 412-416, clause at 659 | `bind_manager=True` passed **nowhere** (grep) | delete. The clause at 659 reads `event.sender` — the **raw argument**, not `event__` — so it `AttributeError`s the first time anyone sets a manager |
| `has_event_type` / `unbind_event_listener` | 526 / 555 | 0 / 0 | keep, rename; fix `unbind` returning `True` only when the list empties |
| `core_inputs` | 701 | — | stamps `INPUTS` over an event whose `.type` is already `MOUSE_DOWN` |

### Four listener registries

| registry | line | action |
|---|---|---|
| `GameComponent.callbacks` | `component.py:132` | **canonical** |
| `GameComponent.async_callbacks` | `component.py:134` | delete — a duplicate declaration of a field `async_.py:25` re-declares |
| `AsyncEventComponent.async_callbacks` | `async_.py:25` | merge into `callbacks`; the whole class then empties → delete it |
| `MouseComponentAsync.mouse_listeners` | `mouse.py:70` | merge. Deletes `EVENT_TYPES` (`:16-30`) and its silent refusal of `MOUSE_DRAG_BEGIN`/`MOUSE_DRAG_END` at `:79-85` — refused into an unconfigured `logging.debug`, while `:236/:257` emit both. **13 call sites.** |
| `KeyboardComponentAsync.key_callbacks` | `keyboard.py:63` | merge. Deletes `KeyBindingType` (`:26-29`) with its fabricated constant `69696969`, and `__update` (`:135`, 0 callers, would `KeyError`). **8 call sites.** |

### Dead files (verified)

- `scripts/core/event_decorator.py` — **cannot be imported**: uses `pygame.event.Event` as an annotation with no `import pygame` and no `from __future__ import annotations`. 0 importers.
- `scripts/core/ui/widget/behavior/movement.py` — **cannot be imported**: references `GameEventType.TRANSFORM_COMPONENT` / `.RESIZE_COMPONENT`, neither of which exists. 0 importers.
- `scripts/core/ui/widget/behavior/transform.py` — imports, 0 importers, 0 instantiations. Its `__transform_event` compares `position is Vector2` against the **type object** (`:35-52`) — always `False`. Archive.
- `scripts/core/ui/widget/viewport.py` — 0 importers. Archive. (Keep `behavior/grid.py`; `listbox.py:1` imports it.)

### `event_manager.py`

| item | line | action |
|---|---|---|
| `update_data` | 55 | delete — 0 callers, and `:59` calls `self.data[key].core_update(value)`, a component lifecycle method, on a dict value |
| `queue()` | 91 | delete — 0 callers; appends to `PYO_QUEUE`, which `pump_pyo:121` clears first thing |
| `append_event` | 51 | fix — `if self.event is not list` is identity against the `list` **type object**, always `True`, so it re-wraps on every append |
| `pump_pyo` coalescing | 126 | `last_event == GameEventType.PYGAME` compares a `PyoneerEvent` to an enum member — always `False`. The coalescing branch **and** `__PROBLEM_EVENTS` are unreachable. Either fix the comparison or delete both. |
| `get()` | 106 | `if len(QUEUE) == 1: return cop[0]` returns a bare `Event` where every other path returns a list. **Latent, not live** — both callers (`main.py:252, 255`) pass an event and take the `elif` branch. |
| `get_pyo()` | 148, 158 | `event is int` / `event is pygame.event.Event` — identity against type objects, unreachable. Reduce to `get_pyo(consume=False)`; the only caller is `scene_manager.py:65`. |

### `event_types.py`

| item | measured | action |
|---|---|---|
| `GameEventType` tuple-Enum | `__translate` = **12.2 µs/event**, 54 members, `MOUSE_DOWN` at scan index 22 (`event_manager.py:70-73` linear-scans per event) | plain `Enum` of unique strings + module-level `PYGAME_TO_GAME: dict[int, GameEventType]` built once; `__translate` becomes one dict lookup |
| `WINDOW_FOCUS_LOST` / `WINDOW_FOCUS_GAINED` | **both `'window_focus'`** — confirmed, `duplicate_enum_string_values: {"window_focus": 2}` | give distinct values **in the same edit**, or flattening aliases them into one member |
| `EventPriority` | **0 references** outside its own definition | delete the enum |

---

## 4. Target surface — six names, no new module

Rename **in place on `GameComponent`**. No `event_router.py`, no mixin.

```python
def event_bind(self, event_type, callback) -> bool          # was bind_sync_listener
def event_unbind(self, event_type, callback=None) -> bool   # was unbind_event_listener
def event_has(self, event_type) -> bool                     # was has_event_type
def event_send(self, event, to_children=True) -> None       # was send_event_advanced
def event_emit(self, event_type, **data) -> PyoneerEvent    # new sugar; replaces the None default
@property
def accepts_input(self) -> bool                             # exists, component.py:586

# private
def _event_send_children(self, event) -> None               # was send_event_to_children_advanced
def _event_children_ordered(self, event) -> tuple[...]      # new, ~6 lines
def _event_make(self, event_type, data) -> PyoneerEvent     # was __create_event
```

**Seventeen public names → six.** `<domain>_<verb>` puts the whole event surface behind typing `self.event_` and nothing else — which is the "relational name schema for the autocompletes" the owner asked for. Applying the same schema to the hierarchy API (`component_bind`, `component_get_at`, …) is a follow-on and is **not** part of this plan; naming it here only so the two plans agree.

---

## 5. Ordered segments

`SMOKE` = `SDL_VIDEODRIVER=dummy .venv/Scripts/python.exe tools/smoke.py --frames 60 --baseline tools/baseline.json`
`EVENTS` = `SDL_VIDEODRIVER=dummy .venv/Scripts/python.exe tools/check_events.py`
`IMPORTS` = `.venv/Scripts/python.exe tools/check_imports.py`

Current baseline: `frame_hash bec3f3153713a6b2`, `ui_component_total 113`, `blit_tokens 69`, 13 depths.

---

### V0 — Extend the instruments, re-baseline

Add two fields to `tools/smoke.py`'s `run()`:
- `ui_component_visits` — the **un-deduped** walk count (`_census` dedupes by `id`, which is exactly what hides defect A). Today: **129** vs `ui_component_total` **113**.
- `dispatch_counts` — a per-frame `Counter` of `GameEventType` names, from a temporary wrap of `send_event_advanced`.

Add to `tools/check_events.py`: the in-tree-`core_*` assertion from §1 (advisory print only at this point).

Then `--write-baseline`. **This is the only re-baseline in the plan.**
**Verify:** `SMOKE` NO DRIFT against the new baseline; `EVENTS` PASS; `IMPORTS` PASS.

---

### V1 — Dead-code excision. Zero behaviour change.

Delete files: `scripts/core/event_decorator.py`, `scripts/core/ui/widget/behavior/movement.py`.
Archive: `scripts/core/ui/widget/behavior/transform.py`, `scripts/core/ui/widget/viewport.py` → `archive/`.
From `component.py`: `event_listener` (539), `send_pygame_event` (614), `send_event_to_children` (622), `send_empty_event` (680), `events()` (705), `rebuild()` (709), `manager` (139) + `bind_manager` (412/416) + the manager clause in the guard at 659, and the commented-out blocks at 529-535 / 547-552 / 610-612.
Rewrite `panel.py:104` to construct the event, then delete `send_event` (618).
From `event_manager.py`: `update_data` (55), `queue()` (91).
From `keyboard.py`: `__update` (135). From `mouse.py`: `send_mouse_event` (109).
Delete `print("Input component initialized.")` (`async_.py:31`, fires 34× per boot) and the `print` calls at `mouse.py:118, 135, 173, 186, 201`.
Reduce the `DEBUGGING` print stubs at `game_object.py:62, 71, 76, 86, 100` to `pass`.

**Verify:** `IMPORTS` PASS; `EVENTS` PASS; `SMOKE` NO DRIFT including `dispatch_counts`.

---

### V2 — Fix the double-binding. Must precede all ordering work.

`ScrollComponent` binds the same `Button` under both `thumb` and `scroll_bar`. Pick one name; delete the other bind. Measured today: **113 unique / 129 visits**; every listener on those 16 nodes fires twice per delivery.

**Verify:** `SMOKE` — `ui_component_visits` drifts **129 → 113**, an expected and reviewed drift. `ui_component_total` stays **113**, `frame_hash` and `blit_tokens` unchanged (`_census` already deduped, so pixels cannot move). New `EVENTS` assertion: tree visits == unique node count.

---

### V3 — `event_types` reshape

`GameEventType` → plain `Enum` with **unique** string values (fix the `window_focus` collision). Module-level `PYGAME_TO_GAME`; `PyoneerEvent.__translate` becomes one dict lookup. Move `INPUT_EVENT_TYPES` out of `component.py:18` into `event_types.py`; add `CONSUMABLE_EVENTS = INPUT_EVENT_TYPES | {VIEWPORT_SCROLLED, CUSTOM_EVENT, USE}` and make GUARDs 1/2 consult it. Delete `EventPriority`. Fix `append_event` (51), `get()` (106), `get_pyo()` (148/158); fix or delete the `pump_pyo` coalescing branch (126) and `__PROBLEM_EVENTS`.

**Verify:** `EVENTS` PASS plus a new assertion — 20 000 `PyoneerEvent(PYGAME, mousedown)` constructions must fall from **12.2 µs to under 1.0 µs** each, and `len(list(GameEventType))` must still be **54**. New assertion: a `BLITS` handler calling `event.handle()` must **not** reduce `blit_tokens`. `SMOKE` NO DRIFT.

---

### V4 — Close the None hole. Measured: NO DRIFT.

`event_send` raises `TypeError` on a `None` event. `bind_component` (`component.py:426-437`) builds a real `PyoneerEvent` per command. `MouseComponentAsync.__init__` (`:71-72`) supplies events. `core_build` sets `self.flags["built"] = True` — the guard at `component.py:164` reads a flag that **nothing writes** (grep: one hit, the read itself). `dispose_drawable` (`draw.py:61`) takes `event=None`. `GameComponent.core_image` (`:741`) → `raise NotImplementedError`.

Today's drops: **PREPARE 142, BUILD 142** at boot, **0** in steady state. There are **zero** `bind_sync_listener(BUILD, …)` sites, so the BUILD fan-out is pure cost until someone binds it — which is exactly why `flags["built"]` must start working in this landing.

**Verify:** `dispatch_counts` shows no dropped-on-None entries. `SMOKE` **NO DRIFT** — this was measured by monkey-patching `core_prepare`/`core_build` and running `smoke.run(60)`; `prepare_background`/`prepare_text` are idempotent. If drift appears, that idempotence broke and it is a new bug, not something to re-baseline over.

---

### V5 — Migrate the in-tree `core_*` overrides

Per the §1 table. Only safe **after** V4: `event_bind(BUILD, …)`/`event_bind(PREPARE, …)` only fire at bind time once `bind_component` sends real events.

`Panel.core_update` is the judgement call. Measured with its body bound as an `UPDATE` listener: `frame_hash` unchanged, `visible_flip = 0`, **but `__transform_component` goes from 0 to 1130 calls over 10 frames** (~113/frame) because `force_update_transforms` fans `TRANSFORM` across both panel subtrees every frame. That is pure cost for zero pixel movement. **Bind it, measure `frame_ms_median`, and if it regresses, drive `__clamp_scroll`/`__hide_unhide_scroll` off `VIEWPORT_SCROLLED` and `PARENT_RESIZED` instead of `UPDATE`.** Do not assume "this is the landing that moves pixels" — it is not.

Also fix the `renderer.py` / `game_scene.py` / `game_player.py` signature drift listed in §1.

Flip the `check_events.py` in-tree-`core_*` assertion from advisory to failing.

**Verify:** `SMOKE` NO DRIFT; `EVENTS` PASS with the new assertion; record `frame_ms_median` before and after the `Panel.core_update` bind.

---

### V6 — Collapse the four registries **and** switch the routing key. One landing.

These cannot be split. `bind_sync_listener(INPUTS, buffer_custom_events)` (`async_.py:28`) is the only thing that gives `INPUTS` meaning; changing the routing key first kills all input, deleting the buffer first orphans the handlers.

Delete `async_callbacks` (both declarations), `event_buffer`, `buffer_custom_events`, `clear_custom_events`, `__update_custom_events`, `__post_update_custom_events`, `bind_async_listener`, `unbind_async_listener`, `accepts_inputs`, `auto_clear` → `AsyncEventComponent` empties → delete the class. Delete `mouse_listeners`, `EVENT_TYPES`, `__execute_event_callbacks` (29 lines; `mouse.py:148` rebinds the loop variable inside `for event in event`, destroying the outer reference; always called with `consumes=False`), `has_mouse_listener`, `bind/unbind_mouse_listener`. Delete `key_callbacks`, `KeyBindingType`, `bind/unbind_key_event`, `unbind_all_key_events`. Rename `MouseComponentAsync` → `MouseBehavior`, `KeyboardComponentAsync` → `KeyboardBehavior`, both deriving `GameComponent` directly.

In the same landing: routing keys on `event.type`; `core_inputs` stops stamping `INPUTS`; `GameEventType.INPUTS` leaves `INPUT_EVENT_TYPES` (the per-type entries carry the gate). `MOUSE_DRAG_BEGIN`/`MOUSE_DRAG_END` become bindable for the first time.

**This is the segment where handlers stop executing under `UPDATE` and start executing under the input dispatch.**

**Verify:** `SMOKE` — `ui_component_census` keys change (`MouseComponentAsync` → `MouseBehavior`, `KeyboardComponentAsync` → `KeyboardBehavior`): expected, reviewed drift. `ui_component_total` **113**, `ui_component_visits` **113**, `blit_tokens` **69**, `frame_hash` unchanged. New `EVENTS` assertions: (1) a `MOUSE_DOWN` listener fires during the input dispatch, **0 times under `UPDATE`** — today the measurement is the exact inverse, 54 under `UPDATE` and 0 under `INPUTS`; (2) `event_bind(MOUSE_DRAG_BEGIN, cb)` succeeds and the callback fires.

---

### V7 — Deepest-first input order. Meaningful only now.

```python
def _event_children_ordered(self, event):
    children = tuple(self.components.values())
    if event.type in INPUT_EVENT_TYPES:
        return sorted(children, key=lambda c: -c.depth)
    return children
```

Six lines, not a two-pass capture/bubble. Lifecycle events stay parent-first: a parent's `UPDATE` repositions children before their `UPDATE` reads `world_bounds`, and `BLITS` parent-first is correct painter order at equal depth. A real capture phase would cost a second full traversal per input event to buy a `capture=True` option nothing wants.

Measured problems this fixes: `GameWindow@root` dispatches `body, title, title_text, close_button, mouse, keyboard, checkbox, panel, panel2` while z-order is `body, mouse, keyboard, title, checkbox, panel, panel2, title_text, close_button`; every `Panel` and every `ScrollComponent` mismatches too. At (300, 300) there are **2 claimants** and the shallowest — `root/mouse` on `GameWindow`, the background — is reached first.

**Verify:** new `EVENTS` assertion — at (300, 300), `root/panel/mouse` is the first claimant, not `root/mouse`. `SMOKE` **NO DRIFT** — `BLITS` is not in `INPUT_EVENT_TYPES`, so an unchanged `frame_hash` and `blit_depths` is the assertion that the split actually held.

---

### V8 — Rename to the `event_*` schema, fix unbind symmetry

Rename per §4, in place on `GameComponent`. Fix `unbind_event_listener` (`component.py:555-562`) returning `True` only when the list empties. Make `unbind_component` (`:439`) call the child's `core_dispose` and clear its `callbacks` — today it just `del`s the dict entry and leaks every listener (`archive/README.md` flags this: gen 2 "has no working unbind path at all").

**Verify:** `IMPORTS` PASS; `EVENTS` PASS; `SMOKE` NO DRIFT; new assertion — after `unbind_component`, the child's callback count is 0 and it receives no further events.

---

## 6. Explicitly not fixed here

1. **The duplicate hit-test.** `MouseBehavior` tests raw `self.parent.world_bounds.collidepoint` (`mouse.py:249-252`) with no occlusion and no viewport clip — `clipped_working_area` (`component.py:358`) is never consulted — while `GameWindow.top_widget_at_position` (`window.py:227`) runs a second, independent max-depth resolution. V7 makes the *first* claimant the correct one, which is all consumption needs. Collapsing the two is geometry work.
2. **`Panel.screen_area` shadowing.** `panel.py:107-113` declares its own `screen_area` property backed by `self.__screen_area`, which mangles to `_Panel__screen_area` — a *different* attribute from `GameComponent`'s `_GameComponent__screen_area` (`component.py:144`). So `Panel.screen_area` and `Panel.clipped_working_area` read different rects. This blocks the hit-test unification; hand it to the geometry owner.
3. **`Config = CoreAssetManager()` at `component.py:16`.** Import-time, pygame-dependent side effect on the event path. Belongs to the singleton plan; `tools/check_singletons.py` already exists.

---

## Removed from the draft

- **§0 "five probes are in `tools/`" and all measurements sourced from them.** The files do not exist; the numbers (129 components, 30 mouse behaviors, 258 receipts, 190 inactive, 95 `active=False`) are stale or wrong. Re-measured: 113 unique / 129 visits, 26 unique mouse behaviors, 129 receipts, 0 inactive.
- **§2.1/§2.2 "add three guards" and all of E7's consumption work.** Already landed at `component.py:570/582/673` and locked in by `tools/check_events.py`. Only the `CONSUMABLE_EVENTS` type-gate survives, folded into V3.
- **§2.3 "DELETE `PyoneerEvent.trickle`".** It is now read at three sites and asserted by a passing test. Deleting it removes a deliberate, tested escape hatch.
- **§3 and E9 (a/b/c) in full — the `active` gate, the default flip, the focus split.** All three already landed: `component.py:73/103/118/576/586/594`, `window.py`, `text_box.py`.
- **E10's mutation-safety work.** Already landed via `tuple()` snapshots at `component.py:604` and `:671`; measured `"no error"`.
- **E3 and `scripts/core/event_router.py`.** A new module plus a new mixin class plus a whole segment whose stated goal is to change nothing is the exact bloat the owner asked to cut. Rename in place.
- **`tools/check_overrides.py`.** A transitive `__subclasses__` walker to police four methods. It is one assertion in the `check_events.py` that already exists.
- **`probe_events.py`, `probe_input_order.py`, `probe_event_cost.py`, `probe_active_census.py`, `probe_hittest.py`, `probe_consume.py`, `probe_gate.py`, `probe_drag.py`** — eight permanent new tools. Two new `smoke.py` fields and assertions added to `check_events.py` cover every one of them.
- **"Adopt `EventPriority` on bind with sorted insertion."** Zero references today and no consumer in the plan. V7's deepest-first ordering is the only ordering anyone has asked for. Delete the enum; re-adding a `priority=` argument later is three lines.
- **gen3's per-frame `handled_events` debug counter.** Speculative instrumentation on 113 objects.
- **§6.3's hierarchy rename table (`component_bind`, `component_get_all_by_type`, …).** The draft itself marks it out of scope. Reduced to one sentence in §4.
- **E5's "⚠ EXPECT DRIFT — re-baseline after review".** Measured NO DRIFT, twice, including with `Panel.core_update` resurrected. The plan now re-baselines exactly once, in V0, before any engine code changes.
- **E4 as a standalone segment.** Splitting the routing-key change from the registry merge leaves the engine with zero input for one segment. Merged into V6.
- **E8 as scheduled (before the registry merge).** A no-op there: handlers execute under `UPDATE`, not under the input dispatch. Moved to V7, after V6.