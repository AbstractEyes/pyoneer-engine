# What to do next — one ranked list

**State this describes:** commit `701bbb5` — *Delete 1,306 lines of dead code,
wire the dormant, fix the offset bug* — read on 2026-08-14.

Other agents were editing this tree while this was written. Where something is
in flight it says so, rather than pretending the working tree is settled. The
untracked files present at the time were `scripts/core/spawn.py` +
`tools/check_spawn.py` (item 1), `tools/check_collision_mount.py` (item 3),
`scripts/loaders/blitmap.py` — a `.blitmap` native map format and tmx
converter, which is not on this list because nothing but its own docstring
described it yet — plus tileset work in `editor/` and `scripts/loaders/`.
**Re-read the tree before trusting any single entry below.**

## What is measured here, and what is only inherited

- `tools/check_all.py`'s roster names **25** checks. Counted in the file, not
  run: the tree was moving, and a suite run against a half-finished working
  tree reports someone else's state as yours. Some entries SKIP when PySide6
  is absent, so the suite's own closing line prints a number at or below 25.
  The previous version of this document said "ALL 18 CHECKS PASS": 18 was
  correct at `de13389`, where that draft was written, and the roster has
  grown 18 → 20 → 24 → 25 over the 12 commits since.
- **All seven advertised trace channels have at least one production call
  site.** Measured this session by `tools/check_log.py` across 107 files in
  `scripts/`, `editor/`, `config/` and `main.py`. `docs/ORPHANS.md` §F records
  three of seven as structurally silent; that is now out of date, and the
  check no longer counts a `trace_*` call written inside a check file as
  evidence, which it used to.
- Every other number below is either counted from a file or attributed to a
  named commit. **Where the previous draft quoted a measurement with no source
  in the tree, this one says so instead of repeating it.**

## Done since the last version of this list

- **`MapDocument.add_layer` / `remove_layer` / `restore_layer`** — landed in
  `4537598` *Add and remove map layers*, nine commits before HEAD. It was
  item 2 on the previous list.
- **`docs/ORPHANS.md` §2 items 1–7** are wired. Verified individually:
  `Alt+Up` / `Alt+Left` are real `QAction`s (`editor/ui/main_window.py:150`);
  `session.py` imports the `PROJECT`/`GENRE`/`ASSETS` constants; the
  `event.type` route table exists on `SceneManager` with `WINDOW_RESIZE` in
  it; focus loss clears the drag latch; the trace channels emit; `sprint` is
  bound *and* consumed; `GameSceneMap.core_lifecycle_build` calls `super()`.
- **The Phase 1 deletion happened** (`701bbb5`, 1,306 lines). `archive/`,
  `ui/deprecated/`, `camera.py`, both `viewport.py`, `behavior/transform.py`,
  `behavior/movement.py`, `align.py`, `icebox/` and `event_decorator.py` are
  all gone. One straggler from that list survives:
  `scripts/game/entity/game_bounding_box.py`, 18 lines, still unreferenced.

---

## The ranked list

### 1. Object layer → entity spawn — **M** — *in flight, check before starting*

**What:** make an object placed on the `entity` layer become a live entity in
the running game.

**Status:** `scripts/core/spawn.py` and `tools/check_spawn.py` were untracked
in the working tree when this was written, so this item is being built right
now by someone else. Read those two files before touching anything here.

**Why it is still first:** the authoring half is finished and the runtime half
is missing, which is the worst possible split. `MapDocument` writes objects
byte-exactly, the editor places them with a click, and `OBJECT_CONVERTER`
(`scripts/core/depth.py:25`) maps class names to depths — while
`renderer.py:465` still reads `if not isinstance(layer_data,
pytmx.TiledTileLayer): continue`, so object groups are skipped with no seam at
all. It is also the gate on three other things:
`docs/PLAN_EDITOR.md`'s action queue, runtime collision, and `GameSceneMap`'s
two remaining comments ("load the entities / load the player").

**A trap that is still live in the tree:** four of the six names in
`OBJECT_CONVERTER` — `GameFloorEntity`, `GameBackgroundEntity`,
`GameForegroundEntity`, `GameUIEntity` — are classes that do not exist. A
spawn path that trusts that table will resolve a depth for a class it cannot
construct.

**Verify:** against a fixture map, not `data/maps/test.tmx`. The author repaints
that file constantly and four red suites have come from checks that pinned its
contents.

### 2. Live reload from the editor — **S**

**What:** after `Project.save()`, tell a running game to re-read.

**Why here:** it is the cheapest item on the list and it changes what the
editor feels like to use. Both halves exist —
`AssetMapManager.load_assets(name, reload=True)` (named in
`scripts/loaders/map_document.py:889`) and `LayerRenderer.invalidate`
(`renderer.py:507`) / `rebake_map` (`renderer.py:544`). What is missing is a
channel. An mtime poll in the game loop is enough for v1; do not build a
socket protocol before something has pushed on the shape.

**Verify:** edit a tile, save, watch it change in a running `main.py` without
a restart.

### 3. Mount the collision stack in the editor — **M**

**What:** put `CollisionOverlay` on `MapCanvas` — construct it sized to the
map, `addItem`, re-add it across scene clears, `bake_resolved()` on rebuild,
`set_cell()` per stroke — and hang `build_mode_actions()` / `mode_icon()` /
`MaskPalette` off the toolbar.

**Why here:** `editor/core/collision.py` (1,089 lines),
`editor/ui/collision_view.py` (862) and `editor/core/map_events.py` (843) are
finished, and their three checks are in the roster and pass. Production
importers at `701bbb5`: **zero** — the string `collision` appears nowhere in
`editor/ui/canvas.py` or `editor/ui/main_window.py`, verified against HEAD.
`EditMode`, the enum that gates the feature, lives *inside* the unmounted
module. This is roughly 100–150 lines of Qt wiring against 2,794 lines of
tested code: the worst effort ratio on the board and the highest absolute
return.

**In flight:** `editor/ui/collision_view.py` and `editor/ui/canvas.py` both
had uncommitted edits while this was written, and an untracked
`tools/check_collision_mount.py` describes itself as covering exactly this
seam. Read it before starting.

### 4. Runtime collision — **L** — after 1 and 3

`grep -rn collision scripts/` returns only the English word in comments. The
editor is fully equipped to author a mask the engine cannot read. Until this
lands, `editor/genres/platformer/RULES.md` describes a story the engine cannot
tell, and item 3 ships an authoring tool for a file nothing consumes.

### 5. `GameComponent` decomposition — **L**

Still the author's named priority and still the right destination.
`docs/IMPROVEMENT_PLAN.md:307` sequences it as Segment 8;
`docs/ENGINE_REVIEW.md`'s `monolith-decomposition` finding enumerates the nine
responsibilities by line range — but that review is now banner-marked as a
snapshot of `cd96542`, 47 commits back, so re-derive every line number before
cutting.

**Why not higher:** it is a multi-session change, and items 1–3 are each one
session that leaves a green tree. The dead-code purge that was supposed to
precede it has now happened, which was the point of doing it first.

### 6. `ListBoxComponent`, then drag-and-drop — **M**

`scripts/core/ui/widget/containers/listbox.py` has never run: outside its own
file, `ListBox` appears only in `README.md`, `COMPONENT_TODO.txt` and the two
review documents — no production importer. The grid it needed now exists and
is live (`behavior/grid.py`, used by `panel.py` and `demo_window.py`, asserted
by `check_grid.py`). What is missing is row selection, keyboard navigation and
a row template on `GridComponent(max_columns=1)`.

Drag-and-drop is next and small: `GridComponent.snap()` places by pixel
position and `MOUSE_DRAG_BEGIN`/`END` are bindable. Nothing joins them.

### 7. The scroll bar's construction formula — **S**

`__scroll_bar_bounds` (`scroll.py:55`) and `__scroll_bar_with_offsets`
(`scroll.py:62`) are two formulas for one rectangle: the bar is built from the
first (`:154`) and switched to the second on the first scroll event (`:215`).
Cosmetic, isolated, well understood. The previous draft quoted a 14 px shift;
that number has no source in the tree — measure it before quoting it.

### 8. Boot cost — **M** — *re-measure before acting*

The previous draft ranked this as "230 ms → 640 ms", attributed to the map
compositor proving its merges with `pygame.mask` work at startup. Neither
number appears anywhere else in the repository, and no measurement in the tree
supports them. The mechanism is real — `renderer.py`'s composite path does
verify itself — but the cost is unmeasured. Time a boot before deciding this
is worth a session.

**Do not** solve it by caching the proof. That was tried; it broke live map
editing, which item 2 depends on.

### 9. Replace the art — **M**

`data/graphics/` is not in the repository or its history and cannot come back;
see `docs/ASSETS.md` for why (the working copy matches RPG Maker VX Ace RTP by
filename and pixel dimensions, which is licensed for use and not for
redistribution). `tools/make_placeholder_art.py` unblocks the checks. Each
genre pack ships an `ART.md` written to be pasted straight into an image
model, and the editor has **AI → Copy the art brief**
(`editor/ui/main_window.py:173`).

**Note for anyone running the suite on a fresh clone:** `check_animation`,
`check_input` and `smoke` all load the real spritesheet through
`GameAnimationHandler`. Without art or placeholders they fail at construction,
not at an assertion.

---

## Not yet, and why

- **A socket protocol between editor and game.** Item 2 does not need one, and
  building it first would fix a shape before anything has pushed on it.
- **The event action queue.** `docs/PLAN_EDITOR.md` explains the deferral at
  length and the reasoning still holds: `GameEntity` derives
  `PyoneerGameObject`, not `GameComponent`, so entities are not on the bus at
  all. Item 1 first, then a small `EntityActionComponent`, then the panel.
- **More genre packs.** Two is enough to prove the abstraction. A third before
  the platformer pack has produced a real game is speculation.
- **Mechanising "do not restructure the event system".** It is prose in every
  `RULES.md` today. Mechanise it the first time it is violated, not before.
- **`scripts/core/engine.py` singleton facade.** Additive, zero behaviour
  change, unblocks nothing.
- **V8 renames.** Rename once, at the end, not twice. Checks and docs bind the
  current names.

## Standing corrections

Carried forward because each one has already cost a session. Re-verified at
`701bbb5`; the line numbers below were read, not inherited.

1. **`bind_component`'s command list is NOT a no-op.** `component.py:563-571`
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

*(The previous list's fourth correction, about `COMPONENT_TODO.txt`
misstating the scroll thumb symptom, has been applied to that file and is
dropped.)*
