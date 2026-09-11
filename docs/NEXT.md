<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every item below was re-measured against the working tree on 2026-08-29 by the command printed beside it. The old item 1 (README's three false gap claims) is gone because README.md was corrected in the same pass; the old items 2-5 kept their text and moved rank. Items 2, 4, 6, 7 and 10 are new and are the open half of the tileset revamp. On 2026-09-03 items 1 and 7 were re-measured and CORRECTED: item 7 had named `tileset_geometry` as the reader that miscounts, with a worked example that was false in both halves -- the divergent reader is pytmx and the axis is margin, not spacing -- and item 1 had counted a `__pycache__` hit as a third prose site. Both now carry the command that produced the numbers they state. On 2026-09-03 the whole list was re-measured again at the finalize of the repair pass: the old item 3 (grow/rename unreachable) is GONE because the tile palette's header menu now constructs all three tileset verbs, the old item 2 lost its tabbed-swatches half because the mask palette is no longer tabified, and the old item 10's folded-companion bullet is GONE because removing an art layer now takes its companion with it. Items 4-10 kept their text and moved rank to 3-9, and a new item 10 records that the credential module deleted in that pass left behind no check that would refuse the next one. Also on 2026-09-03, at the finalize of the entity-editing pass: item 11 is new and records the collision dock floor the author reported and chose to defer, with the Qt numbers measured rather than asserted, and item 10's roster count moved from 51 to 54 in the change that added the three rows. On 2026-09-04, at the finalize of the four-defect repair pass: items 12, 13 and 14 are new and each carries the grep that measured it that day. Item 14 is a recorded DECISION rather than a task, in the shape of item 11. Items 1-11 were not re-measured in that pass and keep their own dates. On 2026-09-04, at the finalize of the audio + map + queue pass: items 15, 16 and 17 are new, each carrying the grep that measured it that day. Item 15 is the fourth ACTIVE WARNING's shape again and is the most expensive of the three: an entire op vocabulary that no running game can reach. Items 1-14 were not re-measured in that pass and keep their own dates. On 2026-09-04, at the finalize of the spawn-funnel + boot-path pass, item 18 is new and carries the grep that measured it that day. It is a recorded DECISION rather than a task, in the shape of items 11 and 14: the rename it describes was possible in that pass and was deliberately not done, because three checks assert the two names as data and a partial rename is a red suite for the next reader. Items 1-17 were not re-measured in that pass and keep their own dates. On 2026-09-10, at the finalize of the reachability pass: items 10, 15, 16 and 17 are STRUCK THROUGH and each carries the command that now returns the opposite of what it recorded. Two of the four also record that their own prescription was measurably WRONG -- item 10's regex would have fired 13 times on this repository's render-queue and behavior tokens, and item 16's one-line repair reads the translated member and never touches the duplicates the branch was aimed at -- which is why they were retired rather than re-run. Item 17 landed in a different module than it prescribed, and says so. Items 1, 2, 4, 5, 7, 9, 13 and 18 were re-measured that day and kept: item 4's second command was CORRECTED (it was written in capitals the source does not use, so it returned 0 and read like the refusal had gone), item 7's `QUIT` count moved from 0 to 1 without the fact moving (the one hit is prose), and item 18's count GREW from 28 to 35 because the script wire added two more readers of both names. Items 19 and 20 are new: both were found by the pass that deleted item 16's dead branch, both are the same type-confusion shape, and one of them is live in a public accessor. Items 3, 6, 8, 11, 12 and 14 were not re-measured and keep their own dates. -->

# Next — what is open, ranked, and the command that measured it

## Why this file is one screen long

The previous version of this file was a ranked list written against `ce66ce5`.
By the time it was next read, four of its items had shipped — and it still sat
at the address a reader is routed to for *"what should I do next"*. It is now
[`history/NEXT_ce66ce5.md`](history/NEXT_ce66ce5.md), and it is the local proof
of the failure this format exists to prevent: **a plan that describes finished
work reads as an instruction, and the work gets done a second time.** Five
refactors in this repository were attempted as new sibling files and all five
died; every refactor written into the incumbent class landed. A stale plan is
how a reader chooses the sibling.

So, two rules, and they are what make this file cheap enough to keep true:

1. **An entry carries the command that produced it, and the commit.** If you
   are acting on an entry, run the command first. An entry whose command you
   have not run is a claim, not a fact.
2. **The inventory is not here.** [`../CLAUDE.md`](../CLAUDE.md)'s *Known gaps*
   says what each hole *is*; this file says only what order to fill them in and
   what each one costs. Copying the descriptions down here would create the
   second home that goes stale first.

## Before you read the list: three commands that answer it without prose

    .venv/Scripts/python.exe tools/check_all.py          what is broken now
    .venv/Scripts/python.exe tools/smoke.py --frames 60  whether the frame moved
    grep -n "| \`" docs/BEHAVIORS.md                     what is actually wired

The third one is the one people skip. [`BEHAVIORS.md`](BEHAVIORS.md)'s
integration column is *measured* — it builds a real entity and runs frames — so
it outranks every sentence of prose in this tree, including this one. Measured
at `d8c303f`: every registered token reports `live`, so "the behavior is not
wired" is no longer a true answer to anything.

## The list

Ranked by *cost of being wrong × cheapness of the fix*, not by size.

**1. `docs/BEHAVIORS.md`'s preamble declares an unregistered behavior token.**
The document is generated, so it matches its generator; the token is in the
generator's *hand-written* preamble, which is the one part generation does not
protect. Cost: a `.tmx` written from the example raises at load — and this is
the only remaining document in the tree that can hand a reader a string the
engine refuses.
Measured: `grep -rn "tile_collision" scripts/game/behavior/ --include=*.py` —
**two** sites, both prose: the `BEHAVIORS` docstring (`#TAG:BEHAVIORS`) and the
`_PREAMBLE` literal in `#TAG:scripts/game/behavior/registry.py`. Drop the
`--include` and a stale `__pycache__` entry makes it look like three.
`tools/check_docs.py` pins the string so it cannot get worse, and the pin must
be deleted in the same change that fixes it.

**2. Collision is still a MODE.** Half of this entry is paid off: the swatches
are no longer behind a tab. `__build_mask_palette` adds its dock to the same
left area as the tile palette and Qt splits the strip, so both vocabularies are
painted at once with no mode change — and a hand-arranged layout now survives
the next launch. What is left is the *mode*: switching still retitles a dock,
re-enables a different tool set and prints a timed status line explaining that
a palette click now means something else. Cost: the two halves of one question
— *what am I painting with* — are now visible together, but the tool still has
a state the author has to hold in their head. The shape is exactly one thing
selected at a time across both palettes, with `EditMode` DERIVED from that
selection instead of toggled. The same edit retires
`#TAG:tile_mask_is_level_one`'s apology: with All-layers off the overlay draws
one companion's raw cells, which is level two, so the default view cannot show
a tile mask the author just baked and the canvas prints a sentence saying so.
Measured on 2026-09-03:
`grep -c "tabifyDockWidget(self.palette_dock" editor/ui/main_window.py` returns
**0** (it returned 1), and `grep -c "EditMode.COLLISION"
editor/ui/main_window.py` returns **4** — the branches that would go away.

**3. Nobody has measured whether Tiled preserves a reserved `firstgid` gap.**
Headroom is what makes growth cost zero cell rewrites instead of a whole-map
renumber, and it is a hole in the gid space that only the file records. Tiled's
writer is expected to assign `firstgid` by running total and remap the layer
data to match — lossless for the art, destructive to the reservation. Cost: not
corruption (`MapDocument.tileset_headroom` recomputes from the declarations
every time, so a repacked file simply has less room), but every refusal message
about headroom would be describing a guarantee the author's own round trip
quietly removes.
Measured: nothing. Tiled is not installed here. The measurement is: author a
map with a gap, open it in Tiled, save, and
`git diff --word-diff data/maps/<that>.tmx | grep firstgid`.

**4. A native `.blitmap` gets no collision at all, and now it is dropping a
declaration it carries.** `field_from_map` answers None for any source that
serves its own `object_records`, so every body on a native map is ungated.
`#TAG:declared_collision` lifts a tmx `<tileset>`'s `pyoneer_collision` into
`TilesetFile.collision`, so a converted map's `.tileset` now carries
`collision <ref>` on its own line and nothing opens it. Cost: a map converted
away from .tmx walks differently from the map it was converted from — the
Paralax shape, one format later, and silent in the direction that looks like it
works. Level one is the only level worth building here: a `.blitmap` has no
companion layers either.
Re-measured 2026-09-10, and one of the two commands below was CORRECTED
rather than re-run: the second was written in capitals the source does not
use, so it returned 0 and read like the refusal had gone.
`grep -rn "\.collision" scripts/loaders/*.py` names `tileset_file.py`'s own
field, its suffix guard and its writer -- four lines, none of them a reader --
and `grep -n "A native .blitmap answers None" scripts/core/collision_runtime.py`
returns **1**, which is the refusal that says so.

**5. A tileset has a name and no internal structure.** A sheet of 768 tiles is
one undifferentiated wall in the palette, and the terrain resolver already
depends on structure nobody can see: `TerrainSet` identifies an autotile group
by its top-left gid and carries a `name` field that every one of the 32 origins
in `TileA2` leaves empty. The format work is already done and costs nothing —
`<tile id="N"><properties><property name="pyoneer_group" value="walls"/>` round
-trips byte for byte through `MapDocument`, and pytmx hands the engine those
properties through `get_tile_properties` with no new code. What is missing is a
verb that writes one and a palette that draws labelled sections instead of one
grid. Cost: low, and it is the last clause of the tileset ask still unbuilt —
"nameable, with structure of control" is currently only the first half.
Measured: `grep -rn "pyoneer_group\|pyoneer_terrain" --include=*.py .` returns
nothing, and `grep -n "class TerrainSet" -A 6 editor/core/autotile.py` shows
the empty `name` the group would fill.

**6. The editor and the engine disagree about a tileset's pixels in two
places, both silent.** A collection-of-images tileset (`<tile><image/></tile>`
children, no sheet of its own) renders correctly through pytmx and draws as
procedural colour swatches in the editor, with nothing reported missing; and
**pytmx counts a margined sheet's tiles differently from everyone else**,
because its count is margin-INDEPENDENT — it walks
`range(margin, dim + margin - tiledim + 1, tiledim + spacing)`, where the two
`margin` terms cancel — so at `margin > 0` pytmx claims rows that
`tileset_geometry` and Tiled both say are not there. Cost: two readers
disagreeing about what a gid looks like raises nowhere, which is the exact
failure mode the region-crop import path was built to avoid. This editor
writes neither shape; Tiled writes both.

**`tileset_geometry` is not the wrong half, and spacing is not the axis.** The
divergence is margin-only: at `margin 0` pytmx agrees with the other two at
every spacing. And `tileset_geometry` reduces algebraically to Tiled's own
`columnCountForWidth`, `(W - margin + spacing) // (tile + spacing)` — a sweep
of 16,335 shapes finds zero disagreements — so an agent who "corrects" it is
editing correct code. Fix pytmx's side, in a reader of our own, or not at all.
Measured: `grep -n "def __load" -A 20 editor/ui/tileset.py` shows the branch
that only reports missing art `if source and image is None`, and the sweep
below reports, over 16335 shapes: **0** disagreements between
`tileset_geometry` and Tiled, **4230** between `tileset_geometry` and pytmx,
and **0** between those two once the margin is 0. Its last line is
`48px sheet, 16px tiles, margin 4, spacing 0 -> geo 2 Tiled 2 pytmx 3`.

Fenced rather than indented, because the continuation lines are Python source
inside one `-c` argument and four leading spaces make them an IndentationError:

```bash
.venv/Scripts/python.exe -c "from itertools import product
from scripts.loaders.map_document import tileset_geometry as geo
tiled = lambda W,t,m,s: (W-m+s)//(t+s) if W-m>=t else 0
ptmx  = lambda W,t,m,s: len(range(m, W+m-t+1, t+s))
cases = list(product(range(8,129),(8,16,24),range(0,9),range(0,5)))
cols  = lambda c: geo(c[0],c[0],c[1],c[1],c[2],c[3])[0]
say = lambda n,f: print(n, sum(1 for c in cases if f(c)), 'of', len(cases))
say('geo != Tiled           ', lambda c: cols(c) != tiled(*c))
say('geo != pytmx           ', lambda c: cols(c) != ptmx(*c))
say('geo != pytmx, margin 0 ', lambda c: c[2] == 0 and cols(c) != ptmx(*c))
print('48px sheet, 16px tiles, margin 4, spacing 0 -> geo',
      geo(48,48,16,16,4,0)[0], 'Tiled', tiled(48,16,4,0),
      'pytmx', ptmx(48,16,4,0))"
```

**7. Four `GameEventType` members are not named anywhere in `scripts/` outside
their own definition.** `POST_DISPOSE`, `PARENT_RESIZED`, `QUIT` and
`WINDOW_FOCUS_GAINED`. Cost: an event member with no listener is an API promise
the engine does not keep, and `USE` is the standing proof of what that costs.
Do not add a member before a listener exists; delete or wire these.
Anchor: `#TAG:post_dispose_unwired`. Measured by walking `scripts/` for each
member name and counting references outside `scripts/core/event_types.py`.
Re-measured 2026-09-10: `POST_DISPOSE` **0**, `PARENT_RESIZED` **0**,
`WINDOW_FOCUS_GAINED` **0**, `QUIT` **1** -- and that one is PROSE, a sentence
in `scripts/core/event_manager.py` saying what would have to be true before a
consumer wanted it. Still no listener; the count moved and the fact did not.

**8. The two silent-failure sites, in the order they will bite.**
Both are described in `CLAUDE.md`'s *Known gaps*; the ranking is the addition:
`#TAG:GameAnimationHandler.__init__` starts a sequence before any behavior
attaches, so a side-on-only or portrait-only sprite sheet raises inside the
entity constructor — that is the *first* wall a new art set hits, and it hits
before anything else in this list matters. `#TAG:GameEntity.allowed_move`
returns an unrecognised direction's vector unclamped, which is harmless only
while `move_direction` is its sole caller — so it becomes urgent the moment a
second caller exists, and not before.

**9. Two small, real and cheap.** Each is one edit; neither is worth its own
rank. There were three until 2026-09-03; the folded companion the `−`
button could not reach is the one that went.
- A per-tile `<objectgroup>` injects a nameless phantom layer into
  `MapDocument.layer_names()` and into `pytmx.layers`, because
  `_layer_elements` walks `root.iter()` where `_tileset_elements` deliberately
  uses `findall`. Nothing writes that shape here and Tiled does. Measured:
  `grep -n "root.iter()" scripts/loaders/map_document.py`.
- Palette zoom is per-session. It needs a key beside `grid_step`. The store to
  put it in now exists — `main_window.layout_store()` writes the dock
  arrangement to the same `QSettings` — but zoom is a typed preference and
  belongs in `editor/core/settings.py`, not in an opaque blob. Measured:
  `grep -n "grid_step" editor/core/settings.py` names the file and the shape,
  and `grep -c "zoom" editor/core/settings.py` returns 0.

**~~10. Nothing in the suite refuses a committed plaintext credential.~~ --
PAID OFF 2026-09-10.** `tools/check_secrets.py` is on the roster and walks
`git ls-files` with two detectors of different kinds: a credential-shaped NAME
bound to a non-trivial literal (Python files PARSED, so `self.api_key = ...`,
dict keys, call keywords and an `os.environ.get(KEY, default)` whose committed
default is the credential are all seen; every other tracked file gets a
`name = value` line match, which is what reaches a `.json`, a `.env` or an
`.ini`), and a high-entropy KEY-SHAPED literal even under an innocent name.
A `Finding` stores the path, the line, the name and `len(value)` and NEVER the
value, so no code path can print a secret into a CI log.
**This entry's own prescription was measurably wrong and that is why it is
being retired rather than re-run.** It named the regex
`^\s*(password|api_key|secret|token)\s*=\s*["'][^"']{3,}["']`, and bare
`token` in this repository is a render-queue `BlitToken` and a behavior token:
13 hits over the tracked tree, all 13 false. Only the qualified spellings
(`auth_token`, `access_token`, ...) are in the vocabulary, with two of the
false shapes pinned as corpus negatives so the exemption cannot widen. Its
measurement command inverts by design too -- `grep -rniE
"api_key|apikey|credential|password|secret" tools/*.py` returns **70** now,
because the check module is the thing that spells those words.
Re-measured 2026-09-10: `.venv/Scripts/python.exe tools/check_secrets.py`
reports 33 assertions, 422 tracked files swept, **0** findings. The two limits
are stated in the module and are real: it cannot unpublish a blob already
pushed (rotate the credential at the provider), and it does not scan history.
THE SEAM STILL OPEN, and it is why this closure is not the whole job: there is
no pre-commit hook, so the refusal lands at check time, after the commit
exists. Command: `grep -rn "check_secrets" .githooks/ .git/hooks/` (today: 0).

**11. The collision palette has a hard floor, so the split it insists on
cannot be made small.** `#TAG:mask_palette_is_never_tabbed` says the mask dock
is put beside the tile palette and never behind it, because a tab is a control
that hides its own contents. `#TAG:_MaskSurface.__init__` then calls
`setMinimumSize(COLUMNS * size, rows * size)` on the grid — 4 columns and 5
rows at `cell + 6` — and there is no `QScrollArea` anywhere in
`editor/ui/collision_view.py`, so that number becomes the whole dock's floor
and nothing below it is reachable by dragging the splitter. The tile palette
next door has no such floor, because its body sits in a scroll area. THE
AUTHOR HIT THIS, could not shrink the dock, re-tabbed it by hand as a
workaround, and said to leave it — so this entry is a record, not a task. It
is worth recording anyway for one reason: a hand-arranged layout now survives
the next launch, so that workaround persists, and the only gesture available
for reclaiming the strip is the exact gesture `mask_palette_is_never_tabbed`
exists to prevent. Cost: low while one person knows why their layout looks
like that. The fix is either wrapping the surface the way the tile palette is
wrapped, or letting the surface shrink and scroll instead of declaring a
minimum at all; do NOT "fix" it by deleting the tabbing guard, which reads the
symptom as the design. Measured 2026-09-03, and measured rather than asserted,
because the load-bearing number is the one Qt computes and not the one the
source spells:

    grep -n "setMinimumSize" editor/ui/collision_view.py

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'tools'); import _bootstrap; from PySide6.QtWidgets import QApplication; from editor.ui.collision_view import MaskPalette; a = QApplication([]); p = MaskPalette(); print(p.minimumSizeHint(), p.surface.minimumSize())"

The grep returns exactly **one** line, which is `#TAG:_MaskSurface.__init__`.
The probe prints `QSize(168, 222) QSize(160, 200)`. Mounted in the window the
dock itself reports a `minimumSizeHint` of **168x238**, and `resizeDocks`
asking for one pixel leaves it **238** tall; the tile palette dock asked the
same way reports **178x133** and shrinks. That 105-pixel difference between two
docks sharing one strip is the whole complaint.

**12. `SelectedObject` lives in a Qt module, so the two headless readers
resolve an object by id and act on whatever answers.** The canvas learned that
an id is not an identity, and on 2026-09-04 the hierarchy tree learned it too
-- by IMPORTING the canvas's record rather than inventing a second one. Two
readers still have no card: `#TAG:object_at` (the behavior panel's) and
`#TAG:inspect._describe_object` (the inspector's) both resolve
`layer.find(int(scope.require("object")))` and hand the panel whatever
is at that address, and every `Field`'s `emit` writes `map.object.set` /
`map.object.property.set` back to that same scope. Narrower than the menu was,
and that is why it is here rather than in the suite: `EditorWindow.refresh_all`
rebuilds both panels on every command, so what is displayed matches what a
write would hit. It is still the identical unguarded idea, and it cannot be
closed by importing, because `editor/core/` may not import `editor/ui/` (law
2). THE SHAPE OF THE FIX: move the `SelectedObject` dataclass verbatim out of
`editor/ui/canvas.py` into a new `editor/core/identity.py` -- it is Qt-free
already, which is what makes core the right home -- plus a free
`identify(document, layer, object_id)`; the canvas, the tree, the inspector and
the behavior panel then all import one record. Nothing about the record
changes. Cost: low today and rising, because every new headless reader of an
object scope is written by copying one of these two.
Measured 2026-09-04:
`grep -rn "layer.find(int(" editor/ --include=*.py` returns **2**
(`behavior_view.py`, and `#TAG:request._describe_object`, the relay's
read-only renderer, which is correct as an address);
`grep -rn "class SelectedObject" editor/ --include=*.py` returns **1**, in
`editor/ui/canvas.py`.

**13. `Session.ask(..., also=...)` has no control anywhere in the window.** The
scoped-bundle gate landed with a declared widening -- a request may name a
second address, ship its verbs and accept a response aimed at it -- and the one
flow that needs it is the main one: attaching an event script is
`script.create` at `script:<id>` plus `map.object.property.set` at the object
that runs it (`docs/PLAN_SCENES.md` section 6), which is two addresses and no
new verb. Today an author can only widen from code or a tool. This is the
fourth ACTIVE WARNING's shape exactly: a capability that is complete, checked,
and unreachable by the person who asked for it. The seam that wants it is
`#TAG:ScriptEditor.ask_here`, which asks about a script and knows which object
runs it. Cost: low while the refusal names the three reachable ways on (an
ordinary source edit described in NOTES.md, asking again with both addresses,
or Ship unscoped) -- and all three are wired.
Measured 2026-09-04: `grep -rn "also=" editor/ui/ --include=*.py` returns
**0**; `grep -rn "session.ask(" editor/ui/ --include=*.py` returns **2**
(`prompt.py`, `script_editor.py`), neither passing a second address.

**14. Painting a TILE on a hidden layer is unguarded, and that is a decision.**
On 2026-09-04 both object-creation paths learned to refuse a hidden layer --
`#TAG:hidden_layer_refuses_creation` on the canvas double-click and
`#TAG:a_paste_is_a_creation_too` on the tree's Paste. The three tile commits
did not, deliberately, and the asymmetry is real rather than squeamish: for an
OBJECT, hidden means UNREACHABLE, because `objects_under` skips the layer, so
what lands can never be selected, dragged, right-clicked or deleted and the
gesture stacks duplicates. For a TILE nothing becomes unreachable -- a cell is
addressed by coordinate, painting the same cell twice writes the same gid
rather than stacking, and the very next stroke after re-ticking the box reaches
it. This entry exists so the next reader finds the reasoning instead of
rediscovering the gap; if the author ever asks for it, the shape is identical
to the two refusals above. Cost: an author can paint into a layer they cannot
see, once, and see it the moment they tick the box back.
Measured 2026-09-04: `grep -n "hidden_layers" editor/ui/canvas.py` returns
**10** lines, none of them inside `#TAG:MapCanvas.__commit_stroke`,
`#TAG:MapCanvas.__commit_terrain` or `#TAG:MapCanvas.__commit_collision`.

**~~15. The audio ops cannot be reached from a running game.~~ -- PAID OFF
2026-09-10, and the shortcut was DELETED rather than left beside the real
route.** `prepare_test_scene` reads `data/project/scripts/` beside the tables
and before the map bind (absent is `{}` and silent, a document that will not
parse RAISES naming the file, before a display exists). `pyoneer_script` on a
tmx object joins by `(layer_name, object_id)` to a spawned body -- naming an
absent document raises, and a scripted body missing `interact_action` /
`action_relay` WARNS. `load_test_objects` routes the `action` verb to one
handler that builds a `ScriptRun` into `SceneManager`'s flow slot; a mid-run
press is refused as a START and spent as the ADVANCE, and both halves of that
decision have their own assertion. `MainGame.play_interaction_sound` and
`INTERACT_SOUND` are gone: two ways to make one noise is worse than one.
THE GESTURE: `.venv/Scripts/python.exe main.py`, then press `e`.
Re-measured 2026-09-10: `grep -rn "load_scripts\|load_script" main.py demos/`
returns **3** where it returned 0; `grep -rln "pyoneer_script" data/maps/`
returns **1** where it returned 0; `docs/EVENTS.md`'s reachability table reads
`no` on **one** of six rows where it read `no` on four.

**~~16. `pump_pyo`'s event-coalescing branch has never executed.~~ -- PAID
OFF 2026-09-10 by DELETION, and this entry's proposed repair was measured and
is WRONG.** The branch, `PyoneerEvent.append_event` and `__PROBLEM_EVENTS` are
gone; `pump_pyo` is one unconditional append per fanned-out event and the
whole measurement is in its docstring under `#TAG:no_event_pooling`.
The repair this entry named -- `last_event.type == GameEventType.PYGAME` --
reads the TRANSLATED member, so it is true only for events no member names: it
folds an unrelated `WindowShown` and `TextInput` together and still never
touches the `MOUSEMOTION` duplicates the branch was aimed at. Two more reasons
it could not be repaired as written: `append_event`'s `self.event is not list`
compares an instance to the `list` TYPE and always nests, and the pooled shape
has NO consumer -- 27 sites read `event.event.<attr>` off a single pygame
event, so a pooled event raises `AttributeError` at the first click.
This entry also predicted a re-baseline. There was none: the branch was
entered **0** times in 568 instrumented opportunities, so deleting it is
arithmetically a no-op. `tools/smoke.py --frames 60` reported NO DRIFT before
and after.
Re-measured 2026-09-10: `grep -c "last_event == GameEventType.PYGAME"
scripts/core/event_manager.py` returns **1**, and that one line is now the
DOCSTRING recording why the fix above is wrong -- read it before re-filing.

**~~17. `driven_record` is three lines of `main.py` copied into
`demos/runtime.py`.~~ -- PAID OFF 2026-09-10, in a DIFFERENT place than this
entry prescribed.** The helper and `PLAYER_TOKEN` now live in
`scripts/loaders/map_loader.py`, beside `SpawnedEntity` and `spawn_counts`,
with `main.py` and `demos/runtime.py` both importing it and the demo package
re-exporting the name so `from demos.runtime import driven_record` still
works. This entry said "one function in `main.py` imported by the demo"; that
would have made the ENGINE's own record query reachable only through the
game's entry point, and law 2's corollary says shared logic lives in
`scripts/` and the layer above re-exports it. `DemoGame.load_test_objects` was
NOT deleted -- it and `MainGame`'s have genuinely diverged since the script
wire landed -- so `check_demos`'s pinned overridden set is unmoved.
Re-measured 2026-09-10: exactly **1** definition tree-wide (by AST, at
`scripts/loaders/map_loader.py`), and **2** real call sites above it, both on
the boot path. `grep -c "driven_record" demos/runtime.py` returns **4** and
`grep -c "PLAYER_TOKEN" main.py` returns **4**; both counts are now imports,
re-exports and uses rather than a second copy of the loop, which is why the
raw counts are the wrong instrument and the AST one is in
`tools/check_demo_map.py`.

**18. `prepare_test_scene` and `load_test_objects` are named for a map that no
longer exists.** They are `MainGame`'s two boot hooks and the extension points
every demo overrides, and the "test" in both of them meant `data/maps/test.tmx`
-- the author's private canvas, retired on 2026-09-04 and replaced by the
shipped `data/maps/starter.tmx`. A reader meeting `load_test_objects` in the
boot path reasonably concludes it is scaffolding, which is the opposite of true:
it is where the game adopts its player and registers its one action route.
DEFERRED DELIBERATELY, and this entry is the decision rather than the task: the
rename is mechanical but it is not local, and three checks assert the two
strings as data -- `check_demos` pins the exact overridden/inherited name sets,
`check_prototype` pins the one name `StoryGame` adds, and `check_spawn_runtime`
finds the scene builder by AST name -- so a partial rename is a red suite for
whoever runs it next. It wants a pass that owns `main.py`, `demos/` and
`tools/` together and does all of it in one commit, with
`tools/gen_map.py --write` in the same change. `docs/history/` keeps the old
names either way; an archive is supposed to.
STILL DEFERRED, and re-measured 2026-09-10 rather than carried: the finalize
pass that owned the whole tree left it alone on purpose, because a rename is
not a finalize and `demos/narrative.py` overriding `load_test_objects` with a
`super()` call makes a partial rename strictly worse than none.
`grep -rn "load_test_objects\|prepare_test_scene" --include=*.py --include=*.md .`
returns **35** lines in **11** files once `docs/map/` and `docs/history/` are
excluded, **6** of those files under `tools/` -- the count GREW, because the
script wire added two more readers of both names.

**19. `EventManager.get_pyo`'s two filtering arms are the SAME type-confusion
bug item 16 just deleted, and this one is in the public accessor.** `elif event
is int and event is not pygame.event.Event:` and `elif event is
pygame.event.Event:` compare the ARGUMENT to the TYPE OBJECT, so both are
constant False for every real argument and the function falls through to
`return []`. Cost: the filtered form of the engine's own event accessor has
never worked, and it fails by returning an empty list rather than raising --
law 7's shape exactly. It is harmless only because the one live caller,
`SceneManager`, passes no argument and takes the `event is None` path. That is
also why it was left alone in the pass that found it: repairing it changes the
return value for a form nothing calls, which is how an unreachable layer gets
built. The honest fix is to decide whether the filtered form should exist at
all -- if it should, it takes a real `isinstance` and a caller in the same
change; if not, delete both arms and the parameter.
Measured 2026-09-10: with one KEY_DOWN in `PYO_QUEUE`,
`EventManager.get_pyo(pygame.KEYDOWN)` returns `[]`, silently, rather than the
event. `grep -n "event is int\|event is pygame.event.Event"
scripts/core/event_manager.py` returns **2**.

**20. Two dead functions in `scripts/core/event_manager.py`, one of them
wrong.** `PyoneerEvent.update_data` has zero callers anywhere and contains
`self.data[key].core_frame_update(value)` where a dict merge was meant -- the
fossil of a global rename of `update` to `core_frame_update` that caught a
dict method. `EventManager.queue()` also has zero callers; it differs from
`pump_pyo` only in appending without clearing, and it is covered by
`tools/check_event_queue.py`, so deleting it is a check edit as well as a
source one. Cost: low and real -- both read as live API, and the first would
raise `AttributeError` the moment anybody believed it. Ranked here rather than
higher because neither can bite a player; they bite the next reader.
Measured 2026-09-10: `grep -rn "update_data" --include=*.py .` returns **1**
(its own `def`), and `grep -rn "EventManager.queue()\|\.queue()" --include=*.py
scripts/ main.py demos/` returns nothing outside that module.

## What is NOT on this list, and why

- **Anything the suite already covers.** `tools/check_all.py` is the work list
  for defects; this file is for holes, which are different — a hole has no
  failing assertion because nothing asserts it yet.
- **A whole-map gid remap verb.** Growth past a neighbour is refused and the
  refusal prices the alternative in painted cells. Reserved headroom is the
  path that means nobody needs the expensive one, so building it now would be
  building the escape hatch before anyone has been trapped.
- **Anything in [`history/`](history/).** Those documents were true when
  written. If one of them names work you think is open, re-measure it before
  believing it; that is what filing them there means.
