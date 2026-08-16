# Orphans

Every element in this engine that exists and does no work, what it was
evidently for, and what is missing to make it live.

> ### Read the corrections, not just the text
>
> The survey below was executed against `1c1a80e` (2026-08-13). Two commits
> have landed since — `701bbb5` deleted 1,306 lines and wired the cheap
> dormant items, and `ce66ce5` mounted the collision stack — and **most of
> this document's individual findings are now spent**. That is the intended
> outcome, not rot: a list of orphans is supposed to shrink.
>
> Corrections are marked inline as blockquotes reading
> **CORRECTED AT `<commit>`**, and the original claim is left standing above
> each one. Nothing here has been silently rewritten. The point of a survey
> is that you can tell what was true when it was taken, and a document that
> quietly updates itself cannot be audited against the commit it describes.
>
> Re-verified in full at `ce66ce5` on 2026-08-14, from a clean
> `git archive HEAD` rather than the working tree — there were 557 lines of
> another agent's uncommitted work in the tree at the time, and reading it
> would have credited HEAD with features it does not have.
>
> **What is still true, in one line:** the ratio finding in §3 survives
> intact — this codebase's problem was never rot, it was mounting — and §4's
> ①, ②, ④ and ⑥ are still missing subsystems.

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

> **CORRECTED AT `ce66ce5`.** Four of those five have moved:
>
> - **Collision importers are no longer zero.** `editor/ui/canvas.py` imports
>   both `editor.core.collision` and `editor.ui.collision_view`
>   (`canvas.py:68`, `:86`), and `editor/ui/main_window.py` imports
>   `MaskPalette` and `build_mode_actions` (`:40`). `ce66ce5` mounted it.
> - **`movement.py` no longer fails to import** because `701bbb5` deleted the
>   file. So did `behavior/viewport.py`, `widget/viewport.py`,
>   `behavior/transform.py`, `camera.py`, `align.py`, `event_decorator.py`,
>   `icebox/` and all of `archive/`.
> - **All seven trace channels emit.** Counted at HEAD across `scripts/`,
>   `editor/`, `config/` and `main.py`, excluding `log.py`'s own docstring and
>   every check file: assets 13, mouse 5, lifecycle 4, keyboard 3, events 3,
>   render 2, input 2 — 32 production call sites. See §F.
> - **`main.py:169` now passes `pygame.RESIZABLE`** (`701bbb5`), which is what
>   turned §2 item 3 and §4 ③ live.
>
> Still true: `TRANSFORM_COMPONENT` and `RESIZE_COMPONENT` do not exist on
> `GameEventType`, and `TRANSFORM` does.

### One correction to the synthesis below

It states `GameEventType` has 64 members. **It has 54**, confirmed by
executing the enum. The argument is unaffected -- the per-member cost of
`__translate`'s linear scan is ~0.23 us rather than ~0.19 us -- but the
number is wrong and is left corrected here rather than silently.

> **CORRECTED AT `ce66ce5`.** **49 members**, confirmed the same way, by
> executing the enum rather than counting lines. `701bbb5` deleted five:
> `SHOW`, `HIDE`, `ACTIVATE`, `DEACTIVATE` and `USER_EVENT`. The scan
> argument is unaffected again; the number is not.

---

**Scale for reference:** `scripts/` 10,623 lines · `editor/` 11,811 · `tools/` 8,137 · `archive/` 641 · 46 commits total, one of which (`de13389`) is the entire editor.

> **CORRECTED AT `ce66ce5`.** `scripts/` 12,773 · `editor/` 12,947 ·
> `tools/` 11,118 · `archive/` **deleted** · 49 commits. `tools/` grew 37%
> in the two commits since, which is the shape of this project working as
> intended and also the reason §3's closing observation still holds.

---

## 1. WHAT SHAPE IS THE DEAD WEIGHT?

Seven clusters. Only one of them is rot.

### A. The viewport/camera fork — four simultaneous answers to one question (~225 lines)

`scripts/game/camera.py` (136), `scripts/core/ui/widget/viewport.py` (35), `scripts/core/ui/widget/behavior/viewport.py` (13), `OldGameCamera` (46 lines inside `game_camera.py`), plus `GameCamera.__offset_type` and its three `OFFSET_*` string constants.

"A rectangle that shows part of a bigger thing" got attempted as a game camera, a widget, a behavior mixin, and a typed anchor enum — and the version that shipped was the fifth one, written *inside* `GameComponent` (`is_view` / `get_viewport_component` / `clipped_working_area` at component.py:326-400) plus the live Panel↔Scroll `VIEWPORT_SCROLLED` chain. `draw.py:58` is the fossil record: a single commented line that names both `GameCamera` and `Viewport` as alternatives, then commits to neither. `ViewportAnchor` is the typed version of the same idea `GameCamera` already does with three bare `str` constants that are themselves unbranched.

**What it tells you:** every refactor this engine attempted as a *new sibling file* died — `movement.py`, `behavior/viewport.py`, `widget/viewport.py`, `behavior/transform.py`, `camera.py`. Five for five. Every refactor that landed was written *into* the incumbent class: the bounds cascade (`92caae6`), anchor reflow (`05b8cdb`), scroll rebuild (`1e38567`). That is the single most actionable pattern in this dataset.

> **SPENT AT `701bbb5`.** Every file named in this cluster is deleted,
> including `OldGameCamera` and `GameCamera.__offset_type` with its three
> `OFFSET_*` constants. The *pattern* is the part worth keeping, and two
> commits later it has a counter-example worth recording: `ce66ce5` moved
> `EditMode` out of `collision_view.py` and into the incumbent
> `editor/core/paint.py` rather than leaving it beside the code that
> declared it — same lesson, applied deliberately for once.

### B. Shed skins — superseded generations kept in the tree (~750 lines)

`archive/` (641 lines, 21 files, two component generations), `OldGameCamera` (46), `DrawComponent.__parent_moved` (16), `ScrollComponent.__percentage_ratio` (9), `__calculate_bar_fill` (7), `GameComponent.__get_difference` (3), `LayerRenderer.__get_map` + `tiled_maps` (3), `needs_update` (1), `TextBox.update_` (2), `Layer.container`, `EntityLayer.sprites`, `movement.py` (39), `transform.py` (58).

Every one was replaced by something demonstrably better, and every replacement has a named commit. The engine keeps the previous generation *in the tree* rather than in git — but with only 46 commits and each supersession findable by message, git already is the archive.

> **SPENT AT `701bbb5`.** All of it, and the argument was accepted rather
> than merely agreed with: `archive/` is gone and git is the archive.
> Verified at HEAD, zero references remain to `OldGameCamera`,
> `__parent_moved`, `__percentage_ratio`, `__calculate_bar_fill`,
> `__get_difference`, `needs_update`, `TextBox.update_`, `Layer.container`
> or `EntityLayer.sprites`.

### C. The event vocabulary that outran its dispatcher (~60 lines, 64 enum members)

`GameEventType` has 54 members. Dead or unreachable: `SHOW`/`HIDE`/`ACTIVATE`/`DEACTIVATE`, `USER_EVENT`, `POST_DISPOSE`, `WINDOW_RESIZE`, `WINDOW_FOCUS_LOST`, `WINDOW_FOCUS_GAINED`, `PARENT_RESIZED`, `PARENT_CHANGED` (bound, never emitted), `USE`, `CUSTOM_EVENT`, `REBUILD` — plus `EventPriority` (22 lines), `__on_component_bound`, `auto_clear`, the whole async buffering block.

**The structural insight this list buries:** `WINDOW_FOCUS_LOST`, `WINDOW_FOCUS_GAINED`, `WINDOW_RESIZE` and `USER_EVENT` are not four orphans. They are *one missing function* — an `event.type`-keyed dispatch route, versus the constant `INPUTS` the scene path uses today. The enum is a design document written ahead of the dispatcher.

This is also the only cluster where deletion has a *measured* argument: PLAN_EVENT_SYSTEM clocks `__translate`'s linear scan at 12.2 µs/event across the member list. At 54 members that is ~0.23 µs per member, per event, forever.

> **CORRECTED AT `ce66ce5`.** The structural insight was acted on and it was
> right. `701bbb5` added the `event.type`-keyed route table
> (`scene_manager.py:32`) and the `RESIZABLE` flag, so `WINDOW_RESIZE`,
> `WINDOW_FOCUS_LOST` and `WINDOW_FOCUS_GAINED` are live — one function, four
> orphans, exactly as predicted. The same commit deleted `SHOW`, `HIDE`,
> `ACTIVATE`, `DEACTIVATE`, `USER_EVENT`, `EventPriority`, `auto_clear` and
> `__on_component_bound`.
>
> **Still dormant at HEAD:** `POST_DISPOSE` (definition only — waiting on
> scene teardown, correctly), `PARENT_RESIZED` and `PARENT_CHANGED` (bound,
> never emitted), `CUSTOM_EVENT`, `REBUILD`, and `USE` — which is emitted
> exactly once, at `text_box.py:209`, and bound by nobody.
>
> The 12.2 µs is PLAN_EVENT_SYSTEM's number, timed before either deletion.
> Five members are gone, so the *total* should have fallen by roughly a
> tenth. Nobody has re-timed it, so that is arithmetic and not a
> measurement — say so if you quote it.
>
> `behavior/async_.py` survives at 85 lines and still buffers.

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

> **CORRECTED AT `ce66ce5` — half of it. This was the document's headline
> finding and it worked.**
>
> The editor half is mounted. `EditMode` moved out of `collision_view.py`
> into `editor/core/paint.py:90`, so the enum that gates the feature is no
> longer trapped inside the unmounted module. `CollisionOverlay` lives on
> `MapCanvas`, survives scene clears, and rebakes from
> `collision_stack()`; `build_mode_actions()` and `MaskPalette` hang off the
> toolbar (`main_window.py:247`, `:154`). Collision painting *reuses*
> `paint.Stroke` rather than duplicating it, so a mask stroke inherits
> one-transaction undo and an exact inverse for free.
> `tools/check_collision_mount.py` (507 lines) covers the seam.
>
> Line counts moved with it: `collision_view.py` is now **820**, not 862, so
> the stack is **2,752** lines, of which **1,909** (`collision.py` +
> `collision_view.py`) are now reachable from production code.
>
> **`map_events.py` is not.** 843 lines with a 497-line check, and at HEAD
> its only importer is its own check — the same shape this whole section
> described, at a third of the size. It is now the worst effort ratio on the
> board.
>
> **And the runtime half is untouched.** `grep -rn collision scripts/` still
> finds no decoder; the new hits are `blitmap.py`'s converter plumbing and
> `tileset_file.py`'s `.blitmask` reference, neither of which reads a mask.
> The asymmetry did not close, it *sharpened*: the editor now authors masks
> through a mounted, discoverable UI that the engine still cannot read.
>
> One caveat the mount ships with: collision painting requires a tileset
> literally named `collision` in the map, and the canvas tells you to "add
> one in Tiled first" (`canvas.py:752`) — while `map.tileset.add` and a
> 479-line `editor/ui/tileset_dialog.py` both exist, the latter with **no
> production importer at all**. See `docs/NEXT.md` item 3.

### E. The editor's addressing layer, one commit old (~90 lines)

`PROJECT`/`GENRE`/`ASSETS`, `known_scopes` (20), `open_here` (5), `to_jsonl`+`to_json` (11), `pending_bundles` (12), `last_bundle` (2), `Section.collapsible`, `Selection.select_parent`/`back`/`__history` (~15), `is_object`, `is_tile_layer`, `Project.is_map_open`, `wrap_with_prompt` (16).

Not rot — a data model that landed complete against a Qt layer that has caught up to ~80% of it. The tell is `known_scopes` deliberately returning tables the genre *declares but that do not exist* (session.py:119-122): only a picker wants targets the user hasn't created. That one missing widget is the consumer for `known_scopes`, and the same `PromptStrip` is where `last_bundle` and `to_jsonl` would surface.

> **PARTLY CORRECTED AT `701bbb5`.** Resolved in both directions:
>
> - **Wired:** `PROJECT`/`GENRE`/`ASSETS` are consumed by `session.py`;
>   `Selection.select_parent` is a real `QAction` (`main_window.py:179`), and
>   so is `back`.
> - **Deleted rather than wired:** `pending_bundles`, `wrap_with_prompt`,
>   `Selection.is_object`, `Selection.is_tile_layer`, `Project.is_map_open`.
>   That is the correct answer to "a knob with no consumer" as often as
>   wiring is.
>
> **Still orphaned at HEAD**, each with exactly one reference — its own
> definition: `known_scopes` (`session.py:104`), `open_here`
> (`session.py:125`), `Command.to_jsonl` (`commands.py:391`), and
> `Section.collapsible` (`inspect.py:62`). `Session.last_bundle` has two
> references and both are writes (`session.py:37`, `:77`) — nothing ever
> reads it, which is the more interesting kind of orphan.
>
> The diagnosis above therefore stands unchanged for the survivors: the
> missing consumer is still one picker widget.

### F. Symmetric vocabularies, asymmetric fill (~25 lines)

`log.py` advertises 7 channels. Actual call sites: **assets 12, mouse 5, lifecycle 3, render 2, keyboard 0, events 0, input 0.** Three of seven advertised, validated, enableable channels are structurally incapable of emitting. Same shape: `PyoneerPerformanceWarning` beside a heavily-wired `warn_content`; `PyoneerEventDispatchError.listener` with no handler that recovers.

The house style is "design the vocabulary as a complete set, fill on demand." Mostly good — but it produces one specific failure: a switch that turns on and does nothing.

> **CORRECTED AT `ce66ce5`. The trace half of this finding is spent: all
> seven channels emit.**
>
> | channel | call sites at HEAD | where the silent three were filled |
> |---|---|---|
> | assets | 13 | `map_document.py` ×12, `map_loader.py:263` |
> | mouse | 5 | `behavior/mouse.py` |
> | lifecycle | 4 | `spawn.py:221`, `async_.py:21`, `behavior/grid.py` ×2 |
> | keyboard | **3** | `behavior/keyboard.py:154`, `:170`, `:181` |
> | events | **3** | `component.py:709`, `:716`, `:966` |
> | input | **2** | `input.py:128`, `:194` |
> | render | 2 | `renderer.py:287`, `:391` |
>
> 32 production call sites. Counted at HEAD across `scripts/`, `editor/`,
> `config/` and `main.py`, excluding `log.py`'s own docstring and comment
> (which name `trace_mouse` without calling it) and excluding every file
> under `tools/` — a `trace_*` written inside a check is not evidence that a
> channel emits, and counting one as evidence is how this stayed wrong.
> `701bbb5` filled keyboard, events and input; `ce66ce5` added the two spawn
> and map-loader sites. `PYONEER_DEBUG=events` now prints.
>
> **The other two examples in this section stand.**
> `PyoneerPerformanceWarning` still has its `warn_performance` helper at
> `errors.py:296` and **zero callers** anywhere in `scripts/`, `editor/` or
> `main.py`. `PyoneerEventDispatchError.listener` is unchanged.
>
> So the section's *thesis* survives and only its headline example does not:
> "design the vocabulary as a complete set, fill on demand" still produced
> one switch that turns on and does nothing — there is just one of them left
> instead of four.

### G. Orphans that actively lie (~40 lines, disproportionate risk)

Worth breaking out because these cost more than their line count:

- `__calculate_bar_fill` — an **unclamped** duplicate of the clamped inline thumb math. "Restoring" it is a regression.
- `__parent_moved` — commented body references a `GameEventType` that does not exist. Uncommenting it crashes.
- `__reset_mouse` — implies a reset that never runs; a mid-drag hide leaves `dragging = True`.
- `Button.__font_color`, `GameCamera(offset_type=…)` — constructor parameters advertising knobs that do nothing.
- `trace_keyboard`/`trace_events`/`trace_input` — `PYONEER_DEBUG=events` validates, enables, emits silence.

> **SPENT AT `ce66ce5`. Every item in this section is resolved**, which is
> the outcome it argued for — these cost more than their line count, so they
> were worth doing first.
>
> - `__calculate_bar_fill`, `__parent_moved`, `Button.__font_color` and
>   `GameCamera(offset_type=…)`: **deleted** (`701bbb5`). Zero references at
>   HEAD.
> - `__reset_mouse`: **fixed rather than deleted.** It is now bound to both
>   `WINDOW_FOCUS_LOST` and `DISPOSE` (`behavior/mouse.py:92-93`) and clears
>   the latches that actually gate the drag. The sticky-drag bug this section
>   predicted is closed.
> - The three trace channels: **filled**, see §F.

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

> **CORRECTED AT `ce66ce5`. Nine of the ten are done.** Verified individually
> at HEAD, not inferred from commit messages:
>
> | # | at HEAD |
> |---|---|
> | 1 | **done** — `Alt+Up` → `select_parent` and `Alt+Left` → `back` are real `QAction`s (`main_window.py:179`) |
> | 2 | **done** — `session.py` consumes the `PROJECT`/`GENRE`/`ASSETS` constants |
> | 3 | **done** — `SceneManager.routes` is the `event.type`-keyed table (`scene_manager.py:32`), and `main.py:169-170` passes `pygame.RESIZABLE`. It cost about what the table said |
> | 4 | **done** — `__reset_mouse` bound to `DISPOSE` and `WINDOW_FOCUS_LOST` (`behavior/mouse.py:92-93`) |
> | 5 | **done** — see §F |
> | 6 | **done** — `sprint` is in `config/inputs.json` and `game_player.py:64` reads `held("sprint")` through all four `move_direction` calls |
> | 7 | **done** — `GameSceneMap.core_lifecycle_build` calls `super()`. Its three body comments ("load the map / the entities / the player") are still comments |
> | 8 | **not done, correctly.** `POST_DISPOSE` still appears only at its own definition. The table said to do it *with* scene teardown; teardown still does not exist, so this is the one entry it would have been wrong to clear |
> | 9 | **done** — the mount landed. See §D |
> | 10 | **not done.** `ImageComponent` is 116 lines and its only three references are inside its own file |
>
> The estimates held up. Items 1–8 were called "under 30 lines" and the
> commit that did most of them is a net *deletion* of 729 lines. Item 9 was
> called "~100–150 lines against 2,794 lines of tested code, worst ratio on
> this table, highest absolute return"; it shipped with a 507-line check of
> its own and it is the reason this document needed rewriting.

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

> **CORRECTED AT `ce66ce5`. The deletable column is spent; the dormant
> column is smaller and its composition has changed.**
>
> `701bbb5` deleted 1,306 lines against this table's ~1,220 estimate — close
> enough that the estimate was doing real work. One straggler survives:
> `scripts/game/entity/game_bounding_box.py`, 19 lines, referenced at HEAD
> only by a docstring in `editor/core/map_events.py:52`.
>
> **Waiting on something, at HEAD:**
>
> | group | lines |
> |---|---|
> | `editor/core/map_events.py` (843) + its unmounted authoring dialog `editor/ui/tileset_dialog.py` (479) | 1,322 |
> | `.blitmap` / `.tileset` — a format the engine cannot read (`blitmap.py` 1,113 + `tileset_file.py` 967) | 2,080 |
> | `scripts/core/spawn.py` (235) + `scripts/loaders/map_loader.py` (272) — written, checked, called only by their check | 507 |
> | `ImageComponent` | 116 |
> | `ListBoxComponent` — 30 lines that declare three selection fields and assign none | 30 |
> | Editor addressing (`known_scopes`, `open_here`, `to_jsonl`, `last_bundle`, `collapsible`, `override_at`, `clear_override`, `set_glyphs`) | ~40 |
> | `warn_performance` + dispatch-error detail | ~15 |
> | Event members awaiting a dispatcher (`POST_DISPOSE`, `PARENT_*`, `USE`, `CUSTOM_EVENT`, `REBUILD`) | ~15 |
> | `game_bounding_box.py` | 19 |
> | **total** | **~4,140** |
>
> **The ratio finding did not just survive, it got starker.** Deletable
> today is now roughly the 19 lines of `game_bounding_box.py`. Dormant is
> ~4,140 — *larger* than the ~3,030 it was, because mounting the collision
> stack was accompanied by three new subsystems that are finished, tested,
> and attached to nothing. This engine's failure mode is not writing bad
> code. It is writing good code and not plugging it in, and it does it
> faster than it unplugs.
>
> `tools/` is 11,118 lines now, and the share of it verifying unreachable
> code is roughly 2,000 (`check_map_events` 497, `check_blitmap` 745,
> `check_spawn` 525, plus the share of `check_tileset_verbs` that drives the
> unmounted dialog).

---

## 4. WHAT THE ORPHANS REVEAL IS MISSING ENTIRELY

**① Runtime collision — the largest asymmetry in the repo.** Authoring: 100% built and tested. Runtime: 0%. `PLAN_EDITOR.md:341` says it plainly. *Lights up:* the whole 2,794-line editor stack gets a reason to exist, `BoundingBox` (19), and `editor/genres/platformer/RULES.md` stops describing a story the engine can't tell.

**② Scene lifecycle / switching.** Nothing in `main.py` or `SceneManager` ever tears a scene down. *Lights up:* `POST_DISPOSE`, `GameSceneMap` (16), `PRE_DISPOSE`'s third beat, and `__reset_mouse`'s `DISPOSE` bind.

**③ OS window integration.** No `RESIZABLE` flag, no `event.type` dispatch. *Lights up:* `WINDOW_RESIZE`, both `WINDOW_FOCUS_*`, `USER_EVENT`, `__reset_mouse`. Cost to build: ~5 lines. Cheapest missing subsystem here by an order of magnitude.

**④ Entity spawning / object instantiation.** The map loads tiles; nothing turns a tmx object into a live entity. *Lights up:* `ComponentFactory` + `COMPONENT_POOL`, `OBJECT_CONVERTER`, `map_loader.py`, and both middle comments in `GameSceneMap` ("load the entities / load the player").

**⑤ Action / interaction system.** `GameEventType.USE` is emitted exactly once and bound by nobody — that is the hole. *Lights up:* `icebox/game_action_queue.py` (53), `USE`, `PlayerState.sprinting`, the missing `sprint` binding.

**⑥ Bitmap widgets.** Every widget is shape+text. *Lights up:* `ImageComponent` (116) — and `IMPROVEMENT_PLAN.md:363` already names its first consumer, the S11 tileset palette.

> **CORRECTED AT `ce66ce5`, subsystem by subsystem.**
>
> **① Runtime collision — still 0%, and now the sharpest asymmetry in the
> repo.** Authoring is no longer merely built, it is *mounted and in daily
> reach*. Nothing in `scripts/` decodes a mask. `BoundingBox` (19 lines) is
> still defined and used nowhere.
>
> **② Scene lifecycle / switching — still missing.** Nothing in `main.py` or
> `SceneManager` tears a scene down. `POST_DISPOSE` still waits on it.
>
> **③ OS window integration — BUILT (`701bbb5`).** `pygame.RESIZABLE` at
> `main.py:169-170`, the `event.type` route table at `scene_manager.py:32`,
> and `__reset_mouse` bound to both `DISPOSE` and `WINDOW_FOCUS_LOST`. This
> was called "the cheapest missing subsystem here by an order of magnitude"
> at ~5 lines; that was right, and it lit up exactly the members predicted.
>
> **④ Entity spawning — HALF built (`ce66ce5`).** `scripts/core/spawn.py`
> (235) and `scripts/loaders/map_loader.py` (272) turn tmx objects into
> entities, with `check_spawn.py` (525) behind them and a `SPAWN_REGISTRY`
> seeded only with classes that are actually concrete — `GameEntity` is
> abstract and four of `OBJECT_CONVERTER`'s six keys name classes that do not
> exist, which is a trap this document should have caught and did not.
> **Nothing calls `spawn_objects` outside its own check**, so the subsystem
> is written, proven and unreachable. `map_loader.py` is no longer the
> 13-line stub named in §3.
>
> **⑤ Action / interaction system — unchanged.** `USE` is still emitted once
> (`text_box.py:209`) and bound by nobody. `icebox/game_action_queue.py` was
> deleted rather than wired, so the "lights up" list is one item shorter and
> the hole is the same shape.
>
> **⑥ Bitmap widgets — unchanged.** `ImageComponent` is still 116 lines with
> three self-references.

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

> **CORRECTED AT `ce66ce5`. Phases 0–2 and 4–6 are done; 3 and 7 are
> partial.**
>
> | phase | at HEAD |
> |---|---|
> | 0 | **done** (`701bbb5`) |
> | 1 | **done** (`701bbb5`) — 1,306 lines against the ~1,220 estimated |
> | 2 | **done** (`701bbb5`) |
> | 3 | **partial.** `EventPriority`, `SHOW`/`HIDE`/`ACTIVATE`/`DEACTIVATE`, `USER_EVENT`, `__on_component_bound` and `auto_clear` are gone. The async buffering block survives at 85 lines. `PARENT_RESIZED` and the three `WINDOW_*` members were kept, as instructed |
> | 4 | **done** — every name in the sweep list is at zero references |
> | 5 | **done** — `LayerType` has zero references at HEAD |
> | 6 | **done** (`ce66ce5`). See §D. It did force the decision on ① and the decision was "later", which is a real answer and is now `docs/NEXT.md` item 2 |
> | 7 | **partial.** Traces done, `sprinting` done. `POST_DISPOSE` correctly still waiting on teardown; `ImageComponent` still waiting on S11 |
>
> The ordering was the load-bearing part and it held: doing Phase 1 before
> Phase 6 meant the collision mount was written against a tree with 1,306
> fewer lines to read.
>
> **What this plan did not anticipate** is worth recording, because it is the
> pattern §3 now names: while Phases 0–6 were executed, three *new* finished
> subsystems arrived with no consumer — `.blitmap`/`.tileset`, the spawn
> path, and the tileset import dialog. A cleanup plan that only enumerates
> today's orphans will always be behind a codebase that produces them faster
> than it retires them. The next revision of this document should be taken
> against the *rate*, not the inventory.

### Delete outright, no argument

Whole files: `movement.py`, `behavior/viewport.py`, `widget/viewport.py`, `behavior/transform.py`, `camera.py` (both classes), `game_bounding_box.py`, `align.py`, `icebox/game_action_queue.py`, `map_loader.py`, `event_decorator.py`, all of `archive/`.

In-file: `OldGameCamera`, `GameCamera.__offset_type` + 3 `OFFSET_*`, `EventPriority`, SHOW/HIDE/ACTIVATE/DEACTIVATE, `USER_EVENT`, `__on_component_bound`, `__parent_moved` + its commented bind, `__calculate_bar_fill`, `__percentage_ratio`, `__get_difference`, `__get_map` + `tiled_maps`, `__unpack_mouse_move`, `needs_update`, `TextBox.update_`, `__base_bounds`, `header_border_thickness`, `Button.__font_color`, `Layer.container`, `EntityLayer.sprites` + `AbstractGroup`, `LayerType`, `DemoWindow.grid_label` + import, `DataAnimationCategory.description`, `auto_clear`, `pending_bundles`, `wrap_with_prompt`, `Selection.is_object`, `Selection.is_tile_layer`, `clear_override`, `Project.is_map_open`, `Session.last_bundle`.

### Do not delete, whatever else you do

`PARENT_RESIZED` (target of a measured plan), `trace_keyboard`/`trace_events`/`trace_input` (deleting the handle while the channel stays in `CHANNELS` is strictly worse than today), `GameSceneMap`, `override_at`, `to_jsonl`, `known_scopes`, `open_here`, `set_glyphs`, `layer_from_companion`, `Section.collapsible`, `PyoneerPerformanceWarning`, `ImageComponent`, and every line of the collision stack. And do not delete `PROJECT`/`GENRE`/`ASSETS` individually — they are one construct on three consecutive lines consumed by one consecutive pair of lines; wire all three or delete all three.

> **CORRECTED AT `ce66ce5`.** Both lists were executed and neither caused a
> regression, which is the only evidence that matters for a delete list.
>
> - **"Delete outright"** — every whole file named is gone, and every in-file
>   name in that paragraph is at zero references at HEAD, verified by grep
>   across `scripts/`, `editor/` and `main.py`.
> - **"Do not delete"** — respected. Three of its entries have since gone
>   live: the three trace channels emit, `layer_from_companion` is called
>   from `canvas.py:258`, and the collision stack is mounted.
>   `PROJECT`/`GENRE`/`ASSETS` were wired as a unit, as asked.
>
> One entry on the keep list needs re-argument rather than re-verification:
> `PyoneerPerformanceWarning` has now survived two cleanup passes with no
> caller. "Keep the handle so the channel does not lie" was the right
> argument for the traces because someone was going to fill them. Nobody has
> filled this one. Either give it a call site or admit it is a vocabulary
> entry with no vocabulary behind it.

---

## Errata elsewhere, not fixed here

Found while re-verifying, in files this pass does not own. Listed so the
next person does not have to rediscover them:

- **`docs/ENGINE_REVIEW.md`'s banner says "47 commits have landed on top of
  it."** `git rev-list --count cd96542..HEAD` is **48**. The banner is
  otherwise exactly right to exist and exactly right to be verbatim; it just
  needs a number that a command can produce.
- **`docs/PLAN_EDITOR.md` says "20 checks in the suite" and "22 verbs".**
  The roster names **29** checks, and `editor/core/verbs.py` declares **29**
  verbs plus the registry's own `noop`. Its "Not built yet" list also still
  names `map.layer.add`/`map.layer.remove` (landed in `4537598`) and the
  object-layer spawn path (half-landed in `ce66ce5`).
- **`scripts/loaders/__init__.py:8`** describes `map_loader` as "(empty)
  reserved for the pytmx -> scene-graph spawn path". It is 272 lines and no
  longer empty.