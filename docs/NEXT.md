<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every item below was re-measured against the working tree on 2026-08-29 by the command printed beside it. The old item 1 (README's three false gap claims) is gone because README.md was corrected in the same pass; the old items 2-5 kept their text and moved rank. Items 2, 4, 6, 7 and 10 are new and are the open half of the tileset revamp. On 2026-09-03 items 1 and 7 were re-measured and CORRECTED: item 7 had named `tileset_geometry` as the reader that miscounts, with a worked example that was false in both halves -- the divergent reader is pytmx and the axis is margin, not spacing -- and item 1 had counted a `__pycache__` hit as a third prose site. Both now carry the command that produced the numbers they state. On 2026-09-03 the whole list was re-measured again at the finalize of the repair pass: the old item 3 (grow/rename unreachable) is GONE because the tile palette's header menu now constructs all three tileset verbs, the old item 2 lost its tabbed-swatches half because the mask palette is no longer tabified, and the old item 10's folded-companion bullet is GONE because removing an art layer now takes its companion with it. Items 4-10 kept their text and moved rank to 3-9, and a new item 10 records that the credential module deleted in that pass left behind no check that would refuse the next one. Also on 2026-09-03, at the finalize of the entity-editing pass: item 11 is new and records the collision dock floor the author reported and chose to defer, with the Qt numbers measured rather than asserted, and item 10's roster count moved from 51 to 54 in the change that added the three rows. -->

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
Measured: `grep -rn "collision" scripts/loaders/` names `tileset_file.py`'s own
field and nothing that opens it, and
`grep -n "A NATIVE .blitmap ANSWERS None" scripts/core/collision_runtime.py`
is the refusal that says so.

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

**10. Nothing in the suite refuses a committed plaintext credential.**
`scripts/tests/` was deleted this pass because one of its seven modules
assigned a password in source. The deletion holds, and it has no teeth: not one
check in the 54-row roster reads a tracked file looking for a credential, so
re-adding that exact file is silently green across the whole suite. That is
law 5's shape in its purest form — not a gate proved in one direction, but no
gate at all. The fix is one new `tools/check_<name>.py` -- written as a
placeholder here because `tools/check_docs.py` refuses a live document that
names a check module the roster has not got, which is the same rule in the
other direction -- walking `git ls-files` for
`^\s*(password|api_key|secret|token)\s*=\s*["'][^"']{3,}["']` with an
allow-list for the fixtures that legitimately spell those words, plus its
roster row in `tools/check_all.py` in the SAME change (law 6). Cost: it is last
here only because the one blob it would have caught is already reachable in
published history and no check can unpublish it — a gate is still cheap, and
the second occurrence will arrive with no warning at all.
Measured 2026-09-03: `grep -rniE "api_key|apikey|credential|password|secret"
tools/*.py` returns **0**, and the `git ls-files` sweep above returns **0**
tracked files now and returned `scripts/tests/naitest.py` before the deletion.

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
