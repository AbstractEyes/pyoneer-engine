# What to do next — one ranked list

**State this describes:** commit `ce66ce5` — *Mount collision, tileset verbs,
.blitmap format, entity spawn* — read on 2026-08-14. 49 commits.

## How this was measured, and why it matters here

Every number below was taken from a clean `git archive HEAD` unpacked to a
scratch directory, not from the working tree. That is not fastidiousness:
while this was being written the tree had uncommitted edits to `main.py`,
`scripts/core/renderer.py`, `scripts/core/scene/scene_manager.py`,
`scripts/core/scene/game_scene_map.py`, `editor/core/verbs.py` and
`editor/ui/canvas.py`, plus untracked `tools/check_spawn_runtime.py`,
`editor/ui/actions_panel.py` and `tools/check_actions_panel.py` — hundreds
of lines of other agents' half-finished work, growing while this was typed.
Reading it would have credited HEAD with features it does not have, which is
exactly the failure the previous two versions of this document were written
to stop.

**Re-read the tree before trusting any single entry below.** On the evidence
above, **items 1 and 5 are being built right now** — the file names line up
with them exactly. If they landed, this list starts at item 2.

- `tools/check_all.py`'s roster names **29** checks. `ce66ce5`'s own commit
  message says `ALL 29 CHECKS PASS, NO DRIFT`. Counted at each commit, the
  roster has gone 18 (`de13389`) → 20 (`4537598`) → 24 (`e01d06f`) → 25
  (`701bbb5`) → 29 (`ce66ce5`).
- **20 of the 29 pass with no art at all**; the other nine read the image
  files. Measured, not estimated: the checks were run one at a time against
  a pristine HEAD with `data/graphics` moved aside, then again after
  `tools/make_placeholder_art.py`, where all 29 pass. Eight of the nine boot
  the engine through `GameAnimationHandler`; `check_blitmap` is the odd one,
  reading a real PNG to prove asset interning copies bytes.
- **All seven advertised trace channels have production call sites**: assets
  13, mouse 5, lifecycle 4, keyboard 3, events 3, render 2, input 2 — 32 in
  all, counted at HEAD across `scripts/`, `editor/`, `config/` and `main.py`,
  excluding `log.py`'s own docstring and the check files.
- Every other number below is either counted from a file at HEAD, timed this
  session with the method stated, or attributed to a named commit.

## Done since the last version of this list

- **The collision stack is mounted** (`ce66ce5`). That was item 3 and it is
  finished, not partially: `EditMode` moved out of `collision_view.py` into
  `editor/core/paint.py`, the overlay lives on `MapCanvas` and survives scene
  clears, and `build_mode_actions()` / `MaskPalette` hang off the toolbar
  (`editor/ui/main_window.py:247`, `:154`). 1,909 lines that no production
  path could reach now have one, and `check_collision_mount.py` (507 lines)
  covers the seam.
- **The spawn path exists** (`ce66ce5`). `scripts/core/spawn.py` (235) and
  `scripts/loaders/map_loader.py` (272) turn tmx objects into entities, with
  `check_spawn.py` (525) behind them. That was item 1 — but only its first
  half; see item 1 below for what is still missing.
- **`.blitmap` / `.tileset`** landed as a format, a converter and asset
  interning (`scripts/loaders/blitmap.py` 1,113, `tileset_file.py` 967).
  Deliberately format-only: nothing in the engine reads one. Item 6.
- **`map.tileset.add` / `.remove` / `.restore`** are registered verbs. The
  `MapDocument` half shipped in `e01d06f` with nothing able to call it.
- **Items 1–7 and 9 of `docs/ORPHANS.md` §2 are wired**, verified
  individually at HEAD: `Alt+Up`/`Alt+Left` are real `QAction`s, the scope
  constants are consumed, the `event.type` route table exists on
  `SceneManager` and `main.py:169` now passes `pygame.RESIZABLE`,
  `__reset_mouse` is bound to both `DISPOSE` and `WINDOW_FOCUS_LOST`, all
  seven trace channels emit, `sprint` is bound and consumed, and
  `GameSceneMap.core_lifecycle_build` calls `super()`. Item 8
  (`POST_DISPOSE`) was always conditional on scene teardown existing, and it
  still does not; item 10 (`ImageComponent`) is untouched.

---

## The ranked list

### 1. Bind spawned entities into a running scene — **S** — *check the tree first*

**What:** call `spawn_objects` from the map load path and hand what comes
back to the scene and the renderer.

**Why first:** this is the missing half of a feature that otherwise looks
finished. `spawn_objects(...)` returns `SpawnedEntity` records with depths
already resolved, and `check_spawn.py` proves it — but at HEAD the only
callers of `spawn_objects` anywhere in the repository are inside
`tools/check_spawn.py`. `GameSceneMap.core_lifecycle_build` still reads

```python
        # load the map
        # load the entities
        # load the player
```

with nothing under the comments. `ce66ce5`'s own message says so plainly:
"Binding into the scene is still the integrator's, not done here."

**Status:** almost certainly in flight. The uncommitted edits listed above
touch `renderer.py`, `scene_manager.py`, `game_scene_map.py` and `main.py`
together, and the untracked file is called `check_spawn_runtime.py`. Read
those before writing a line.

**Verify:** against a fixture map. `data/maps/test.tmx` is the author's
canvas and five red suites have come from checks that pinned its contents.

### 2. Runtime collision — **L**

**What:** make the engine read the mask the editor now writes.

**Why here:** this is the largest asymmetry in the repository, and `ce66ce5`
sharpened it in the useful way — authoring is no longer merely built, it is
mounted, discoverable, and pleasant enough to use that maps will start
carrying masks. `grep -rn collision scripts/` at HEAD returns the English
word in comments plus the `.blitmap` converter's plumbing; nothing decodes a
companion layer. Until this lands,
`editor/genres/platformer/RULES.md` describes a story the engine cannot tell,
and the collision mode is an authoring tool for a file nothing consumes.

The encoding is already decided and already tested, which is most of the
usual cost of a subsystem: a mask lives in a companion tile layer as
`first_gid + mask`, gid 0 means NO_DATA rather than "open", and
`editor/core/collision.py`'s three-level resolution is what the engine has to
agree with. Read that file before inventing a second spelling.

**Depends on item 1** for anything that collides with an entity, but not for
tile-versus-player, which is the half worth having first.

### 3. Hang the tileset import dialog off a menu — **XS**

**What:** construct `TilesetImportDialog` from a `QAction`.

**Why this high, at this size:** `editor/ui/tileset_dialog.py` is 479 lines
with a live grid preview and geometry measurement, its verbs are registered,
`tools/check_tileset_verbs.py` (616 lines) passes — and its only importer at
HEAD is that check. Nothing in `editor/ui/main_window.py` mentions a tileset
dialog at all.

It is also the one manual step left in the feature that just shipped.
Collision painting needs a tileset literally named `collision` in the map,
and without one the canvas says so and stops:

```
this map has no 'collision' tileset, so a mask has no gid to be
stored as — add one in Tiled first
```

(`editor/ui/canvas.py:752`). "Go and use the tool this one replaces" is a
poor last step for a 1,909-line feature, and the code that removes it is
already written and already tested. Wiring the dialog is the fix; offering it
from that status message is the polish.

### 4. Live reload from the editor — **S**

**What:** after `Project.save()`, tell a running game to re-read.

**Why here:** cheapest item on the list that changes what the editor feels
like to use. Both halves exist — `AssetMapManager.load_assets(name,
reload=True)` and `LayerRenderer.invalidate` / `rebake_map`. What is missing
is a channel. An mtime poll in the game loop is enough for v1; do not build a
socket protocol before something has pushed on the shape.

**Verify:** edit a tile, save, watch it change in a running `main.py` without
a restart.

### 5. An authoring surface for map events — **M** — *in flight, check first*

`editor/core/map_events.py` is 843 lines with a 497-line check, and at HEAD
its only importer is its own check — the same shape the collision stack had
one commit ago, at a third of the size. It owns the trigger vocabulary,
collision filters and a tmx round trip; nothing offers them to a human.

**Status:** an untracked `editor/ui/actions_panel.py` and
`tools/check_actions_panel.py` appeared in the tree while this was being
written, and `editor/core/verbs.py` has 157 uncommitted added lines that
import `map_events`. Read all three before starting.

**Read `docs/PLAN_EDITOR.md`'s "Why the action queue is not built yet" first
and decide whether it still holds.** Its four reasons were: entities are not
on the event bus, most `GameEventType` members are not dispatched, there is
no entity collision, and the object layer is skipped at runtime. Item 1
retires the fourth. The other three stand, so a trigger authored today still
executes nowhere — which argues for shipping the panel *with* the caveat
already written into the verb summaries, not for shipping it silently.

### 6. Make the engine read `.blitmap` — **L**

The format, the converter and asset interning all landed in `ce66ce5` and
nothing reads one. That was a deliberate call and the commit says why:
"making the engine READ them touches renderer, asset manager and scene at
once and is deliberately a later step." It is still the right call, and it is
still a debt — a second map format that only the checks exercise is a format
that will drift from the first.

### 7. `GameComponent` decomposition — **L**

Still the author's named priority and still the right destination.
`docs/IMPROVEMENT_PLAN.md:307` sequences it as Segment 8;
`docs/ENGINE_REVIEW.md:349`'s `monolith-decomposition` finding enumerates the
nine responsibilities by line range — but that review is banner-marked as a
snapshot of `cd96542`, which is **48** commits back, so re-derive every line
number before cutting. (Its banner still says 47; see the note at the end of
`docs/ORPHANS.md`.)

**Why not higher:** it is a multi-session change, and items 1–5 are each one
session that leaves a green tree.

### 8. `ListBoxComponent`, then drag-and-drop — **M**

`scripts/core/ui/widget/containers/listbox.py` is 30 lines and has never run:
outside its own file, `ListBox` appears only in prose — `README.md`,
`COMPONENT_TODO.txt`, the two review documents and here. The grid it needed exists
and is live (`behavior/grid.py`, used by `panel.py` and `demo_window.py`,
asserted by `check_grid.py`), and the class already builds a
`GridComponent(max_columns=1)` and forwards `add`/`remove`/`clear` to it.
What is missing is row selection — it declares `__selected_index`,
`__selected_item` and `__selected_items` and never assigns any of them —
keyboard navigation, and a row template.

Drag-and-drop is next and small: `GridComponent.snap()` places by pixel
position and `MOUSE_DRAG_BEGIN`/`END` are bindable. Nothing joins them.

### 9. The scroll bar's construction formula — **S**

`__scroll_bar_bounds` (`scroll.py:55`) and `__scroll_bar_with_offsets`
(`scroll.py:62`) are two formulas for one rectangle: the bar is built from
the first (`:154`) and switched to the second on the first scroll event
(`:215`). Cosmetic, isolated, well understood.

**The previous draft said the 14 px figure had no source in the tree. That
was wrong, and it is corrected here rather than dropped.** The source is
`docs/IMPROVEMENT_PLAN.md:358`, which measured it live: on the first scroll,
`scroll_bar.local_bounds` goes `(326,0,14,134)` → `(326,14,14,120)` while the
`Button`'s body `ShapeComponent` keeps its construction-time surface, so the
bar graphic is drawn 14 px taller than its logical bounds and offset from
them.

The code agrees, which is why it is 14 and not some other number: comparing
the two vertical formulas, the bar's `y` goes `0 → scroll_height` and its
height loses another `scroll_height`, and `scroll_height` is a constructor
default of `14` (`scroll.py:24`) that `Panel` does not override
(`panel.py:49`, `:56`). Note that the fix IMPROVEMENT_PLAN prescribes is
larger than picking one formula — it wants `DrawComponent.resize(w, h)` and a
bounds-changed cascade, because the surface is stale as well as the rect.

### 10. Boot cost — **M** — *measured, and smaller than advertised*

Timed this session at HEAD, headless (`SDL_VIDEODRIVER=dummy`), constructing
`MainGame(autostart=False)` in five fresh processes: **330–446 ms, median
352**. One full `renderer.rebake_map()` immediately afterwards costs
**243–252 ms**, so the compositing proof really is about 70% of boot — the
mechanism the old note named was right even though its numbers were not.

The previous drafts quoted "230 ms → 640 ms". Neither number appears anywhere
in the repository and neither is reproducible; they are dropped rather than
repeated. Note that both figures above are on the demo map *as currently
painted*, on the author's machine, with the real art — repaint the map and
they move.

**Do not** solve it by caching the proof. That was tried; it broke live map
editing, which item 4 depends on.

### 11. Replace the art — **M**

`data/graphics/` is not in the repository or its history and cannot come
back; see `docs/ASSETS.md` for why (the working copy matches RPG Maker VX Ace
RTP by filename and pixel dimensions, which is licensed for use and not for
redistribution). `tools/make_placeholder_art.py` writes the three files and
takes the suite from 20/29 to 29/29 — measured, see above. Each genre pack
ships an `ART.md` written to be pasted straight into an image model, and the
editor has **AI → Copy the art brief** (`editor/ui/main_window.py:202`).

---

## Not yet, and why

- **A socket protocol between editor and game.** Item 4 does not need one,
  and building it first would fix a shape before anything has pushed on it.
- **More genre packs.** Two is enough to prove the abstraction. A third
  before the platformer pack has produced a real game is speculation.
- **Mechanising "do not restructure the event system".** It is prose in every
  `RULES.md` today. Mechanise it the first time it is violated, not before.
- **`scripts/core/engine.py` singleton facade.** Additive, zero behaviour
  change, unblocks nothing.
- **V8 renames.** Rename once, at the end, not twice. Checks and docs bind
  the current names.
- **`POST_DISPOSE`.** One line, and inert until scene teardown exists. Do it
  *with* teardown, not before — `docs/ORPHANS.md` §2 item 8 has said so
  through three revisions and has been right each time.

## Standing corrections

Carried forward because each one has already cost a session. Re-verified at
`ce66ce5`; the line numbers below were read at HEAD, not inherited.

1. **`bind_component`'s command list is NOT a no-op.** `component.py:565-571`
   calls `core_lifecycle_prepare_pre` / `prepare` / `prepare_post` / `build`
   on the child **directly**. Deleting `Panel.core_lifecycle_build` or
   `ScrollComponent.core_lifecycle_build` on the theory that they never run
   destroys the window. They run, and they build most of the UI.
2. **`flags["built"]` guards the fan-out, not subtree construction.** Both
   overrides above call `super()` first and then run their body
   unconditionally. Harmless today; a trap the moment anything rebuilds.
3. **The layer is spelled `Paralax`, with one L**, in `test.tmx` and in both
   genre packs. `scripts/core/depth.py:36-43` aliases it rather than renaming
   it, to keep the file byte-identical for Tiled. 39 authored tiles were
   silently dropped for as long as the renderer looked up the correct
   spelling.
4. **A check may assert what the CODE does, never what the MAP contains.**
   `data/maps/test.tmx` is the author's canvas. Build fixtures.
5. **An assertion that cannot fail is not an assertion.** `ce66ce5`'s
   reviewer found three in one pass — one comparing against a constructor
   argument, one driving a single frame where the property under test only
   exists on the second, one asserting identity against a pygame singleton
   that `set_mode` mutates in place. Break the code your check covers and
   confirm the check goes red, every time.
