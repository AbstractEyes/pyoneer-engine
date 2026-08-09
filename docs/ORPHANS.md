# Orphans

Every element in this engine that exists and does no work, what it was
evidently for, and what is missing to make it live.

## How this was produced, and how far to trust it

Five independent sweeps, each blind to the others and each using a different
modality: an AST census of every top-level symbol, a real import graph plus
an attempt to import every module, the event and lifecycle surface, config
and data, and the subtle one -- things that ARE referenced but whose
reference does nothing.

209 raw candidates, 196 after dedup, 64 taken through adversarial
verification whose instruction was to DISPROVE each claim. Two were killed
as false positives.

That last number is the reason for the process. A zero-grep proves nothing
here: `@command()` mutates a registry at import time, `ComponentFactory`
registers by string, `check_all.py` names checks as strings, and pygame,
pytmx and Qt all call back into subclass methods by name. Every verdict
below states which dynamic path was ruled out.

### Independently re-verified before publishing

- collision stack production importers: **zero** (the only import of
  `collision.py` is from `collision_view.py` -- the stack imports itself)
- `movement.py` genuinely fails to import: `AttributeError:
  TRANSFORM_COMPONENT`
- trace channel call sites: assets 12, mouse 7, lifecycle 3, render 2,
  **keyboard 0, events 0, input 0**
- `main.py:169` is `set_mode((w, h))` with no flags, so no `RESIZABLE`
- `TRANSFORM_COMPONENT` and `RESIZE_COMPONENT` do not exist on
  `GameEventType`; `TRANSFORM` does

### One correction to the synthesis below

It states `GameEventType` has 64 members. **It has 54**, confirmed by
executing the enum. The argument is unaffected -- the per-member cost of
`__translate`'s linear scan is ~0.23 us rather than ~0.19 us -- but the
number is wrong and is left corrected here rather than silently.

---

**Scale for reference:** `scripts/` 10,623 lines · `editor/` 11,811 · `tools/` 8,137 · `archive/` 641 · 46 commits total, one of which (`de13389`) is the entire editor.

---

## 1. WHAT SHAPE IS THE DEAD WEIGHT?

Seven clusters. Only one of them is rot.

### A. The viewport/camera fork — four simultaneous answers to one question (~225 lines)

`scripts/game/camera.py` (136), `scripts/core/ui/widget/viewport.py` (35), `scripts/core/ui/widget/behavior/viewport.py` (13), `OldGameCamera` (46 lines inside `game_camera.py`), plus `GameCamera.__offset_type` and its three `OFFSET_*` string constants.

"A rectangle that shows part of a bigger thing" got attempted as a game camera, a widget, a behavior mixin, and a typed anchor enum — and the version that shipped was the fifth one, written *inside* `GameComponent` (`is_view` / `get_viewport_component` / `clipped_working_area` at component.py:326-400) plus the live Panel↔Scroll `VIEWPORT_SCROLLED` chain. `draw.py:58` is the fossil record: a single commented line that names both `GameCamera` and `Viewport` as alternatives, then commits to neither. `ViewportAnchor` is the typed version of the same idea `GameCamera` already does with three bare `str` constants that are themselves unbranched.

**What it tells you:** every refactor this engine attempted as a *new sibling file* died — `movement.py`, `behavior/viewport.py`, `widget/viewport.py`, `behavior/transform.py`, `camera.py`. Five for five. Every refactor that landed was written *into* the incumbent class: the bounds cascade (`92caae6`), anchor reflow (`05b8cdb`), scroll rebuild (`1e38567`). That is the single most actionable pattern in this dataset.

### B. Shed skins — superseded generations kept in the tree (~750 lines)

`archive/` (641 lines, 21 files, two component generations), `OldGameCamera` (46), `DrawComponent.__parent_moved` (16), `ScrollComponent.__percentage_ratio` (9), `__calculate_bar_fill` (7), `GameComponent.__get_difference` (3), `LayerRenderer.__get_map` + `tiled_maps` (3), `needs_update` (1), `TextBox.update_` (2), `Layer.container`, `EntityLayer.sprites`, `movement.py` (39), `transform.py` (58).

Every one was replaced by something demonstrably better, and every replacement has a named commit. The engine keeps the previous generation *in the tree* rather than in git — but with only 46 commits and each supersession findable by message, git already is the archive.

### C. The event vocabulary that outran its dispatcher (~60 lines, 64 enum members)

`GameEventType` has 54 members. Dead or unreachable: `SHOW`/`HIDE`/`ACTIVATE`/`DEACTIVATE`, `USER_EVENT`, `POST_DISPOSE`, `WINDOW_RESIZE`, `WINDOW_FOCUS_LOST`, `WINDOW_FOCUS_GAINED`, `PARENT_RESIZED`, `PARENT_CHANGED` (bound, never emitted), `USE`, `CUSTOM_EVENT`, `REBUILD` — plus `EventPriority` (22 lines), `__on_component_bound`, `auto_clear`, the whole async buffering block.

**The structural insight this list buries:** `WINDOW_FOCUS_LOST`, `WINDOW_FOCUS_GAINED`, `WINDOW_RESIZE` and `USER_EVENT` are not four orphans. They are *one missing function* — an `event.type`-keyed dispatch route, versus the constant `INPUTS` the scene path uses today. The enum is a design document written ahead of the dispatcher.

This is also the only cluster where deletion has a *measured* argument: PLAN_EVENT_SYSTEM clocks `__translate`'s linear scan at 12.2 µs/event across the member list. At 54 members that is ~0.23 µs per member, per event, forever.

### D. Collision — built, tested, and never mounted (2,794 lines) ← **the actual story**

The individual findings (`CollisionOverlay`, `layer_from_companion`, `set_glyphs`, `override_at`, `clear_override`) understate this by roughly 12×. The real object:

| module | lines | its check | lines |
|---|---|---|---|
| `editor/core/collision.py` | 1,089 | `check_collision.py` | 652 |
| `editor/ui/collision_view.py` | 862 | `check_collision_view.py` | 437 |
| `editor/core/map_events.py` | 843 | `check_map_events.py` | 497 |
| **total** | **2,794** | | **1,586** |

All three checks are in `check_all.py`'s roster and pass. Production importers: **zero**. `canvas.py` imports `autotile`, `commands`, `paint`, `scope`, `tileset` — not `collision`. `main_window.py` imports `paint.Tool`; the string `COLLISION` appears nowhere in `paint.py`, `canvas.py` or `main_window.py`. `EditMode` itself lives *inside* `collision_view.py:134`, so the enum that gates the feature is trapped inside the unmounted module.

And on the runtime side: `grep -rn collision scripts/` returns four hits, all of them the English word in a comment (`id() collision`, `collision-free firstgid`). **The engine cannot read a mask the editor is fully equipped to author.**

### E. The editor's addressing layer, one commit old (~90 lines)

`PROJECT`/`GENRE`/`ASSETS`, `known_scopes` (20), `open_here` (5), `to_jsonl`+`to_json` (11), `pending_bundles` (12), `last_bundle` (2), `Section.collapsible`, `Selection.select_parent`/`back`/`__history` (~15), `is_object`, `is_tile_layer`, `Project.is_map_open`, `wrap_with_prompt` (16).

Not rot — a data model that landed complete against a Qt layer that has caught up to ~80% of it. The tell is `known_scopes` deliberately returning tables the genre *declares but that do not exist* (session.py:119-122): only a picker wants targets the user hasn't created. That one missing widget is the consumer for `known_scopes`, and the same `PromptStrip` is where `last_bundle` and `to_jsonl` would surface.

### F. Symmetric vocabularies, asymmetric fill (~25 lines)

`log.py` advertises 7 channels. Actual call sites: **assets 12, mouse 5, lifecycle 3, render 2, keyboard 0, events 0, input 0.** Three of seven advertised, validated, enableable channels are structurally incapable of emitting. Same shape: `PyoneerPerformanceWarning` beside a heavily-wired `warn_content`; `PyoneerEventDispatchError.listener` with no handler that recovers.

The house style is "design the vocabulary as a complete set, fill on demand." Mostly good — but it produces one specific failure: a switch that turns on and does nothing.

### G. Orphans that actively lie (~40 lines, disproportionate risk)

Worth breaking out because these cost more than their line count:

- `__calculate_bar_fill` — an **unclamped** duplicate of the clamped inline thumb math. "Restoring" it is a regression.
- `__parent_moved` — commented body references a `GameEventType` that does not exist. Uncommenting it crashes.
- `__reset_mouse` — implies a reset that never runs; a mid-drag hide leaves `dragging = True`.
- `Button.__font_color`, `GameCamera(offset_type=…)` — constructor parameters advertising knobs that do nothing.
- `trace_keyboard`/`trace_events`/`trace_input` — `PYONEER_DEBUG=events` validates, enables, emits silence.

---

## 2. DORMANT, ORDERED BY VALUE-PER-EFFORT

| # | The one missing connection | Effort | Unlocks |
|---|---|---|---|
| 1 | Two `QAction` entries in `main_window`: `Alt+Up → selection.select_parent`, `Alt+Left → selection.back` | **2 lines** | ~15 lines of complete navigation (`Scope.parent()`, `__history`, `changed` signal, three panels already listening) |
| 2 | Replace `Scope.of("project"/"genre"/"assets")` at `session.py:106-107` with the constants | **2 lines** | All three singletons; zero risk (`Scope` is frozen and value-comparing) |
| 3 | `event.type`-keyed route in `scene_manager.inputs()` + `pygame.RESIZABLE` at `main.py:169` (currently `set_mode((bounds[2], bounds[3]))`, no flags) | **~5 lines** | `WINDOW_FOCUS_LOST`, `WINDOW_FOCUS_GAINED`, `WINDOW_RESIZE`, `USER_EVENT` **and** gives `__reset_mouse` its hook. Best leverage-per-line in the engine |
| 4 | Bind `__reset_mouse` to `DISPOSE` + `WINDOW_FOCUS_LOST`; add `self.dragging = False`, `self.mouse_down = False` | **3 lines** (after #3) | 9 dormant lines + a real sticky-drag bug |
| 5 | 8–10 `trace_keyboard`/`trace_events`/`trace_input` calls mirroring `behavior/mouse.py:128-212` | **~10 lines** | 3 of 7 channels stop lying |
| 6 | `sprint` in `config/inputs.json`; `self.state.sprinting = self.action_manager.held("sprint")`; `sprint=` through the four `move_direction` calls at `game_player.py:68/72/76/80` | **~6 lines** | The only listed orphan whose consumer is already built |
| 7 | `GameSceneMap.core_lifecycle_build` calls `super()` | **1 line** | Degrades to base behavior instead of silence |
| 8 | `game_scene.py:88` → `core_lifecycle_dispose_post(...POST_DISPOSE)` | **1 line** | Inert until scene teardown exists — do it *with* that, not before |
| 9 | **Mount `CollisionOverlay` on `MapCanvas`**: construct sized to map, `addItem`, re-add across scene clears, `bake_resolved()` on rebuild, `set_cell()` per stroke; hang `build_mode_actions()`/`mode_icon()`/`MaskPalette` off the toolbar | **~100–150 lines** | **2,794 lines of tested code.** Worst ratio on this table, highest absolute return on the board |
| 10 | `ImageComponent`: forward `image_in` to `super().__init__`, route paths through `CoreAssetManager`, clip the subsurface — then the S11 tileset palette | 3 fixes + a feature | 116 lines; blocked on a consumer, not a wire |

Items 1–8 total **under 30 lines** and clear seven separate findings.

---

## 3. TOTAL WEIGHT

**Deletable today, zero behaviour change:**

| group | lines | files |
|---|---|---|
| 7 whole dead modules (movement, behavior/viewport, widget/viewport, transform, camera, game_bounding_box, align) | 310 | 7 |
| Already-known whole-file dead (game_action_queue 53, map_loader 13, event_decorator 8) | 74 | 3 |
| `archive/` | 641 | 21 |
| In-file deletions (OldGameCamera 46, EventPriority 22, `__parent_moved` 16, `wrap_with_prompt` 16, `pending_bundles` 12, `is_tile_layer` 10, `__percentage_ratio` 9, `__calculate_bar_fill` 7, SHOW/HIDE/ACTIVATE/DEACTIVATE 6, offset_type+constants 6, LayerType 7 sites, and ~35 one-and-two-liners) | ~195 | ~25 |
| **total** | **~1,220** | **~56** |

**Waiting on something (finished code, no connection):**

| group | lines |
|---|---|
| Collision stack (`collision.py` + `collision_view.py` + `map_events.py`) | 2,794 |
| `ImageComponent` | 116 |
| Editor addressing (known_scopes, open_here, to_jsonl, select_parent, scope constants, collapsible, override_at) | ~55 |
| Traces + perf warning + dispatch-error detail | ~25 |
| Event members awaiting one dispatch line | ~20 |
| `GameSceneMap` | 16 |
| **total** | **~3,030** |

**The ratio is the finding.** Excluding `archive/`, there are ~580 deletable lines against ~3,030 dormant ones — **5 lines of finished, unattached inventory for every 1 line of dead weight.** This codebase does not have a rot problem. It has a *mounting* problem. And 1,586 of the 8,137 lines in `tools/` exist to verify code that nothing in the application can reach.

---

## 4. WHAT THE ORPHANS REVEAL IS MISSING ENTIRELY

**① Runtime collision — the largest asymmetry in the repo.** Authoring: 100% built and tested. Runtime: 0%. `PLAN_EDITOR.md:341` says it plainly. *Lights up:* the whole 2,794-line editor stack gets a reason to exist, `BoundingBox` (19), and `editor/genres/platformer/RULES.md` stops describing a story the engine can't tell.

**② Scene lifecycle / switching.** Nothing in `main.py` or `SceneManager` ever tears a scene down. *Lights up:* `POST_DISPOSE`, `GameSceneMap` (16), `PRE_DISPOSE`'s third beat, and `__reset_mouse`'s `DISPOSE` bind.

**③ OS window integration.** No `RESIZABLE` flag, no `event.type` dispatch. *Lights up:* `WINDOW_RESIZE`, both `WINDOW_FOCUS_*`, `USER_EVENT`, `__reset_mouse`. Cost to build: ~5 lines. Cheapest missing subsystem here by an order of magnitude.

**④ Entity spawning / object instantiation.** The map loads tiles; nothing turns a tmx object into a live entity. *Lights up:* `ComponentFactory` + `COMPONENT_POOL`, `OBJECT_CONVERTER`, `map_loader.py`, and both middle comments in `GameSceneMap` ("load the entities / load the player").

**⑤ Action / interaction system.** `GameEventType.USE` is emitted exactly once and bound by nobody — that is the hole. *Lights up:* `icebox/game_action_queue.py` (53), `USE`, `PlayerState.sprinting`, the missing `sprint` binding.

**⑥ Bitmap widgets.** Every widget is shape+text. *Lights up:* `ImageComponent` (116) — and `IMPROVEMENT_PLAN.md:363` already names its first consumer, the S11 tileset palette.

---

## 5. THE ORDER I WOULD ACTUALLY DO IT IN

**Phase 0 — the sub-5-line wires (one sitting).** Items 1, 2, 7 from the table above. These are literally cheaper to *do* than to keep writing down.

**Phase 1 — delete 31 files in one commit (1,025 lines).** `movement.py`, `behavior/viewport.py`, `widget/viewport.py`, `behavior/transform.py`, `camera.py`, `game_bounding_box.py`, `align.py`, `icebox/game_action_queue.py`, `map_loader.py`, `event_decorator.py`, and all of `archive/`. No signature changes, no risk, and it shrinks the surface every later pass has to read. Do this **before** anything structural.

**Phase 2 — the 5-line window dispatch.** `RESIZABLE` + `event.type` route + `__reset_mouse` binds. Turns four declared-only enum members live and fixes a real bug.

**Phase 3 — the `event_types` pass, one commit.** Delete `EventPriority`, SHOW/HIDE/ACTIVATE/DEACTIVATE, `USER_EVENT`, `__on_component_bound`, and the async buffering block per `PLAN_EVENT_SYSTEM.md:279` (including `auto_clear` — wiring it preserves a mechanism the plan deletes). **Keep** `PARENT_RESIZED` (named landing zone of a measured optimisation) and the three `WINDOW_*` members, which now fire.

**Phase 4 — the shed-skin sweep (~110 lines).** Start with `__calculate_bar_fill` and `__parent_moved` — the two that are actively dangerous. Then `__percentage_ratio`, `__get_difference`, `__get_map` + `tiled_maps`, `needs_update`, `update_`, `__unpack_mouse_move`, `__base_bounds`, `header_border_thickness`, `__font_color`, `Layer.container`, `EntityLayer.sprites` + the `AbstractGroup` import, `grid_label` + its `TextComponent` import, `last_bundle`, `pending_bundles`, `wrap_with_prompt`, `is_object`, `is_tile_layer`, `is_map_open`, `clear_override`, `DataAnimationCategory.description`. **While in `component.py`, fix the class docstring at :45-69** — it documents nine `__`-prefixed attributes that do not exist.

**Phase 5 — `LayerType`, alone.** The only deletion that is a signature change: 4 `__init__` signatures + 4 construction sites. Its successor (`editor/core/layers.py`'s `Capability`/`LayerProfile`) is already read at renderer.py:200, :236, :618.

**Phase 6 — mount collision.** This is a project, not a cleanup, and it is the highest-value thing on the list. It also forces the decision on subsystem ①, because an editor that authors masks the runtime cannot read is a half-product either way.

**Phase 7 — the rest.** Traces, `sprinting`, `POST_DISPOSE` alongside scene teardown, `ImageComponent` alongside S11.

### Delete outright, no argument

Whole files: `movement.py`, `behavior/viewport.py`, `widget/viewport.py`, `behavior/transform.py`, `camera.py` (both classes), `game_bounding_box.py`, `align.py`, `icebox/game_action_queue.py`, `map_loader.py`, `event_decorator.py`, all of `archive/`.

In-file: `OldGameCamera`, `GameCamera.__offset_type` + 3 `OFFSET_*`, `EventPriority`, SHOW/HIDE/ACTIVATE/DEACTIVATE, `USER_EVENT`, `__on_component_bound`, `__parent_moved` + its commented bind, `__calculate_bar_fill`, `__percentage_ratio`, `__get_difference`, `__get_map` + `tiled_maps`, `__unpack_mouse_move`, `needs_update`, `TextBox.update_`, `__base_bounds`, `header_border_thickness`, `Button.__font_color`, `Layer.container`, `EntityLayer.sprites` + `AbstractGroup`, `LayerType`, `DemoWindow.grid_label` + import, `DataAnimationCategory.description`, `auto_clear`, `pending_bundles`, `wrap_with_prompt`, `Selection.is_object`, `Selection.is_tile_layer`, `clear_override`, `Project.is_map_open`, `Session.last_bundle`.

### Do not delete, whatever else you do

`PARENT_RESIZED` (target of a measured plan), `trace_keyboard`/`trace_events`/`trace_input` (deleting the handle while the channel stays in `CHANNELS` is strictly worse than today), `GameSceneMap`, `override_at`, `to_jsonl`, `known_scopes`, `open_here`, `set_glyphs`, `layer_from_companion`, `Section.collapsible`, `PyoneerPerformanceWarning`, `ImageComponent`, and every line of the collision stack. And do not delete `PROJECT`/`GENRE`/`ASSETS` individually — they are one construct on three consecutive lines consumed by one consecutive pair of lines; wire all three or delete all three.