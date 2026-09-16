<!-- pyoneer-doc: L3 -->
<!-- pyoneer-archive: an APPEND-ONLY ledger, exempt from fact checks. Every row was true when it was recorded. A row is never edited or deleted, and closing an instance does not unmake the sighting -- the value of this file is the count. New sightings are APPENDED to the right table, and the count beside that warning in CLAUDE.md is updated in the same change. -->

# Sightings — the record behind CLAUDE.md's warnings

`CLAUDE.md`'s ACTIVE WARNINGS keep each warning to three things: the move people
make, the counter-move, and a count. This file is where the count comes from:
one table per warning, one row per sighting, oldest first.

The rows were moved here from `CLAUDE.md` on 2026-09-16, during the markdown
cleanup, with nothing dropped. Rows marked **(NEXT n)** were filed in
`docs/NEXT.md` as this shape at the time, and were never counted in
`CLAUDE.md` until that day. "Recorded" names the commit that first wrote the
sighting down, where the commit that caused it is not known.

The second part, **Gaps paid off**, holds the *Known gaps* entries that closed.

## 1. You will reach for a sibling file

| # | when | commit | sighting |
|---|---|---|---|
| 1–5 | undated | — | Five refactors were attempted as a new module beside the incumbent (`foo_v2.py`, `new_foo.py`, a clean reimplementation to switch over to later). All five died; every refactor written into the incumbent class landed. The five were only ever recorded as a count. |
| 6 | 2026-08-16 | `29fbfc1` | The same thing at package scale, and the reason for law 2's corollary: a second copy of the collision model shipped in `editor/` with 37 shared symbols, 35 of them textually identical. **425 duplicate lines** were deleted. The "differential" guard meant to catch it compared 11 of the 37 symbols and missed the gate itself. |

## 2. You will read a finished plan as an instruction

| # | when | commit | sighting |
|---|---|---|---|
| 1 | before 2026-08-16 | `ce66ce5` | `docs/NEXT.md`'s ranked list was written against `ce66ce5`. By the next time anyone read it, four of its items had shipped, and it was still where "what should I do next" sends a reader. Archived as `docs/history/NEXT_ce66ce5.md`. |
| 2 | 2026-08-16 | `d8c303f` | `docs/PLAN_EDITOR.md`'s "not built yet" list named four things that had already shipped. One was the object-layer spawn path, and the plan gave its absence as the reason not to build the action queue. Nothing in the document said it was stale, and CLAUDE.md sent readers there for editor architecture. |
| 3 | 2026-09-16 | markdown cleanup | It happened again, to both plans. `docs/PLAN_SCENES.md` still described its built stages 1, 4 and 5 as the build spec ("unbuilt until its stages say otherwise"), and `docs/PLAN_EDITOR.md` had grown stale "not built yet", status and action-queue sections again. The full scenes plan was frozen as `docs/history/PLAN_SCENES_2026-09-03.md`. The live one was cut down to unbuilt work, and the editor plan to architecture only. |

## 3. You will forget to regenerate the map

| # | when | commit | sighting |
|---|---|---|---|
| 1 | 2026-08-16 | — | Two modules landed in `demos/` without `tools/gen_map.py --write`. `docs/MAP.md` did not know they existed, so the next agent's `check_docs` run would have gone red because of someone else's change. |

## 4. You will ship your own layer and leave the wire to whoever owns the next file

| # | when | commit | sighting |
|---|---|---|---|
| 1 | 2026-08-17 | `b438c85` → `62c5677` | Sub-cell collision landed in the engine, and a click could not reach a sub-cell until the next commit. |
| 2 | 2026-08-08 → 2026-08-18 | `2ddee3d` → `6794bde` | The editor's Database window wrote `data/project/tables/` for ten days before anything in `scripts/` read it. During that time seventeen `source="actors"` parameters looked authored but were really the declared default. This one runs the other way: the editor was ahead of the engine. The problem is that nobody owns the seam, whichever side is ahead. |
| 3 | 2026-08-18 | `6794bde` → `8915ee0` → `19c3e04` | Tile masks took four passes to reach a click: first the engine read, then the overlay and a working `map.tileset.mask.set` (while `grep -rn "map.tileset.mask" editor/ui/` still found nothing, so the one thing the author had asked for could not be done), then `Canvas.bake_tile_mask`. The gap was nearly filed twice: a re-measure one minute before filing found `bake_tile_mask` already in a sibling's working tree. |
| 4 | 2026-08-29 → 2026-09-03 | `7d253d0` → `ef0ea70` | `map.tileset.grow` and `map.tileset.rename` shipped with exact inverses and tests covering both refusals, but no control in the window called either, so the tileset the author asked to grow and rename could do neither. Closed by the palette's header menu. |
| 5 | 2026-09-04 | — | **(NEXT 13)** `Session.ask(..., also=...)` shipped a declared widening, and nothing in the window can use it. The one flow that needs it (attach an event script: two addresses) is the main one. Still open. |
| 6 | 2026-09-04 → 2026-09-10 | → `0b6227c` | **(NEXT 15)** The audio ops were a complete op vocabulary that no running game could reach. It was closed when a key press started a scripted event, and the action-route shortcut that had stood in for it was deleted. |
| 7 | 2026-09-11 | → `5be433e` | **(NEXT 27)** The detectors behind `docs/BEHAVIORS.md`'s measured-integration column had never been seen reporting `no`. The audit found a third blind detector as well: row 4 measured the READ and never the ATTACH, so deleting every `attach_all` left it green. |

## 5. You will fix the route that ships and let its SIBLING route grow without the fix

| # | when | commit | sighting |
|---|---|---|---|
| 1 | 2026-09-04 | `569c3dd` | Delete and create. Delete refused on a hidden object layer, but the double-click that CREATES did not refuse, and neither did the hierarchy's Paste. Objects stacked up on the layer where nobody could see, click or delete them. |
| 2 | 2026-09-04 | `569c3dd` | Canvas and tree. The canvas refused a stale object id that had been recycled, and the hierarchy tree's menu went ahead and deleted by it. |
| 3 | 2026-09-04 | `0da8720` | The map spawn and `SceneManager.spawn`: `spawn_defaults` reached only the map route, so every body spawned at runtime was collision-gated at the top of its head. |
| 4 | by 2026-09-11 | recorded `8c3850a` | The same pair again: `pyoneer_script` reached only the map route. A runtime body naming a missing document did nothing, silently, while a map-placed one raised. Closed with one shared reader, `script_of`. One mutation (`if False and script_id not in scripts`) turned both `tools/check_spawn_runtime.py` and `tools/check_script_runtime.py` red in a single run. |
| 5 | by 2026-09-11 | recorded `8c3850a` | `main.py`'s boot hook and `DemoGame`'s override of it: three copied lines cost the demo path the script join, the `say` host, the action route and both map guards at once. |
| 6 | by 2026-09-11 | recorded `8c3850a` | Twice inside the CHECK suite. Two reachability rows read a JSON file and reported it as a built wire, while the sibling instrument one file away already said "the loaded pack only, never the raw `genre.json` beside it". After those two were fixed, a third row of the same shape was still there, reading `config/inputs.json` with `json.load` and printing **yes** for a verb the loader might never have registered. |
| 7 | 2026-09-11 | recorded `6ea1d61` | Created by the previous pass's own fix. `main.py`'s press guard was changed to let a finished flow through, but it checked by IDENTITY. That let our own finished run through and not the other kind, so one finished cutscene silently disabled event scripts for the rest of the session. |
| 8 | 2026-09-11 | recorded `6ea1d61` | `map.object.action.unset` had always carried `if not list(found.element): found.element.text = None`, with the reason in a comment. `map.object.property.remove`, one screenful away, never had it, so declaring a script and pressing Ctrl+Z left two lines of diff nobody wrote. |
| 9 | 2026-09-11 | recorded `6ea1d61` | `map.object.set` declared `choices=_OBJECT_ATTRIBUTES`, and its inverse `map.object.unset` declared `Param("key", str)` with no choices, so the verb that could not WRITE `id` could DELETE it. Closed by making both name the same tuple. Rows 7–9 each live in ONE file, two of them within thirty lines of each other, so distance is not the cause. |
| 10 | 2026-09-11 | recorded `5be433e` | `MapDocument._append_child`'s middle branch carried the comment "Recomputing looked equivalent and was not ... Inheriting makes the pair exactly reversible" and then recomputed the very next separator it wrote, three lines below. So did the branch after it: one function, three branches, one rule, and two of the branches broke it. |
| 11 | 2026-09-11 | recorded `5be433e` | `Project.dirty_scripts` learned to check what EXISTS instead of trusting a `removed` set, and `ScriptLibrary.dirty` one layer down did not. Nothing read it, so nothing broke, and the first code to call it would have inherited a bug already fixed one layer up. It still counts as a sibling even though nobody can date it. |
| 12 | 2026-09-11 | recorded `99a1888` | `map.object.restore`'s `xml` argument got a guard, and `next_object_id`, three lines below in the same args dict, did not. The verb could still write `nextobjectid="not-a-number"` and make the whole map unloadable. |
| 13 | 2026-09-11 | recorded `99a1888` | `map.object.set` looked guarded because its sibling argument `key` declared `choices`. That checked WHICH attribute was written and never WHAT went into it, so `width="not-a-number"` went through the relay to the same unloadable map. Found by listing every input rather than by a prover: 51 verbs and 136 parameters were dumped from the live registry, five were in the defect class, and four of those had no validation at all. |
| 14 | 2026-09-11 | recorded `99a1888` | `_refuse_smuggled_names` read every NAME in a restored element's subtree and never a single VALUE. `<object pyoneer_x="1"/>` was refused, while `<object width="abc"/>`, with the same cost (whole map lost), was accepted by all three restore verbs. Closed by moving the table to `scripts/core/layer_profile.py` as `ATTRIBUTE_TEXT`, so the engine-side and editor-side guards read one table. |
| 15 | 2026-09-11 | recorded `99a1888` | `_release_object_id` checks whether an id is one below the counter, but the real invariant is "this session handed it out". A guard written for the claim route is simply wrong on the restore route. Still open: `docs/NEXT.md` item 37. |
| 16 | 2026-09-11 | — | **(NEXT 31)** `GenrePack.validate` resolves `pyoneer_script`, `pyoneer_actor` and `pyoneer_behaviors` through the engine's own readers, but not `pyoneer_param_<key>`, the fourth per-object link. Still open. |
| 17 | 2026-09-11 | — | **(NEXT 32)** `check_behavior_docs` switched from bare-name AST call matching to `calls_through`, while `check_demo_map` and `check_log` still match by `func.id`/`func.attr`. Still open. |
| 18 | 2026-09-11 | — | **(NEXT 33)** `check_event_docs`' picker-row gate uses a name-shaped `hasattr(ops_module, n)`. The sibling rejection passed only because the name happens to live in another module. Still open. |
| 19 | 2026-09-16 | — | **(NEXT 44)** Found by the markdown cleanup while re-measuring PLAN_SCENES stage 1. Three windows build a `PromptStrip`, and only the dock's (`editor/ui/docks.py`) connects `staged` to `refresh_manifest`. The Database window's and the Script editor's strips stage a note that the Manifest dock does not show until something else refreshes it. Still open. |

The counter-move this family earned, recorded with its proof: the four copies
of the self-closing guard in `editor/core/verbs.py` became one line at
`childless_parent_closes_itself`. Now one mutation turns four rows red, where
it used to take four separate mutations.

## Gaps paid off

Entries that left `CLAUDE.md`'s *Known gaps* because they closed.

| closed | what | how it closed | measured by |
|---|---|---|---|
| 2026-08-17 (`dc4b060`) | Two documents addressed code by line number | DIAGNOSE's four anchors became `#TAG:` addresses; NEXT's seven went with the `ce66ce5`-era list into `docs/history/NEXT_ce66ce5.md` | `tools/check_docs.py`'s `LINE_ANCHOR_DEBT` is the empty dict |
| 2026-08-18 (`6794bde`) | No engine-side reader for `data/project/tables/` | `scripts/loaders/table_file.py` reads them; `actor_row` joins `pyoneer_actor` to a row on both spawn routes | the parameter chain's step 2 fires and an `hp` column reaches the runtime |
| 2026-08-18 (`6794bde`) | No genre-pack default behavior list | `GenreLayer.object_classes`; `map.object.add` copies the list into `pyoneer_behaviors` once, as a starting value, and a pack token the registry does not know raises at pack load | `tools/check_editor.py` |
| 2026-08-28 (`74ff126`) | No `needs_art` flag on the check roster | Removed the need instead: generated art ships under `data/art/`, and `resolve_art` tries `data/graphics/` first, then `data/art/` | with `data/graphics` moved aside, `tools/check_all.py` reports `FAILED: []` |
| 2026-09-03 | README's three false gap claims (collision masks, object spawn, `.blitmap` reader) and its stale check count | README corrected | reading the section |
| 2026-09-03 | `docs/BEHAVIORS.md`'s preamble said nothing in `scripts/` reads `data/project/` | preamble corrected; the `tile_collision` lie in the same preamble stayed | reading the preamble against `scripts/loaders/table_file.py` |
| 2026-09-03 | `map.tileset.grow` / `map.tileset.rename` had no caller in the window | palette header menu: Rename / Grow / Remove, disabled entries carry their reason | `grep -rn "map.tileset.grow\|map.tileset.rename" editor/ui/ --include=*.py` returned 6; `tools/check_palette.py` drives a real right-click and undo |
| 2026-09-16 | `docs/BEHAVIORS.md`'s preamble showed the unregistered token `tile_collision`, which makes a map raise at load | the preamble and the `BEHAVIORS` docstring were corrected in the markdown cleanup, and `tools/check_docs.py`'s pin was removed | `grep -rn "tile_collision" docs/BEHAVIORS.md scripts/ --include=*.py --include=*.md` returns 0 |
| 2026-09-10 (`0b6227c`) | Nothing but a script could make a noise, and no script ran | the boot reads `data/project/scripts/`, `pyoneer_script` joins a body, one press of `action` starts a `ScriptRun`; `MainGame.play_interaction_sound` deleted | `grep -rn "load_scripts" main.py` hits; `tools/check_script_runtime.py`; `main.py`, press `e` |
