<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every item below was re-measured against the working tree on 2026-08-29 by the command printed beside it. The old item 1 (README's three false gap claims) is gone because README.md was corrected in the same pass; the old items 2-5 kept their text and moved rank. Items 2, 4, 6, 7 and 10 are new and are the open half of the tileset revamp. -->

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
Measured: `grep -rn "tile_collision" scripts/game/behavior/` — three sites, all
prose. `tools/check_docs.py` pins the string so it cannot get worse, and the
pin must be deleted in the same change that fixes it.

**2. Collision is still a MODE, and the mask swatches are still behind a tab.**
The companion layer is gone from the hierarchy and a mask can be applied with
shift+click without leaving tile mode, so the plain words of the ask are met —
but the seventeen swatches plus the no-opinion chip live in a dock tabified
*behind* the tile palette, and switching still retitles a dock, re-enables a
different tool set and prints a timed status line explaining that a palette
click now means something else. Cost: the two halves of one question — *what am
I painting with* — cannot be seen at the same time, which is the grievance the
whole revamp was about. The shape is one palette with the swatches as a strip
above the stacked sheets, exactly one thing selected at a time, and `EditMode`
derived from that selection instead of toggled. The same edit retires
`#TAG:tile_mask_is_level_one`'s apology: with All-layers off the overlay draws
one companion's raw cells, which is level two, so the default view cannot show
a tile mask the author just baked and the canvas prints a sentence saying so.
Measured: `grep -n "tabifyDockWidget(self.palette_dock" editor/ui/main_window.py`
returns the line that puts them behind each other, and
`grep -c "EditMode.COLLISION" editor/ui/main_window.py` counts the branches
that would go away.

**3. `map.tileset.grow` and `map.tileset.rename` exist and no editor control
calls either.** A tileset can be grown by whole rows into reserved gid headroom
and renamed with its `.blitmask` header following it, both with exact
inverses — and the author cannot reach either from the window. The seam is a
destination combo on the import view ("a new tileset" plus every existing one)
and a rename affordance on the palette's section header.
Cost: this is the shape `CLAUDE.md`'s fourth ACTIVE WARNING now records four
sightings of — a layer that is complete, checked, and unreachable by the person
who asked for it. Measured at this commit:
`grep -rn "map.tileset.grow\|map.tileset.rename" editor/ui/` returns nothing,
while `grep -rn "#TAG:map.tileset.grow" editor/` returns the declaration.

**4. Nobody has measured whether Tiled preserves a reserved `firstgid` gap.**
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

**5. A native `.blitmap` gets no collision at all, and now it is dropping a
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

**6. A tileset has a name and no internal structure.** A sheet of 768 tiles is
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

**7. The editor and the engine disagree about a tileset's pixels in two
places, both silent.** A collection-of-images tileset (`<tile><image/></tile>`
children, no sheet of its own) renders correctly through pytmx and draws as
procedural colour swatches in the editor, with nothing reported missing; and
`tileset_geometry` counts tiles the way Tiled does only at margin 0, so a
Tiled-authored spaced sheet gets a tile *count* the two disagree about. Cost:
two readers disagreeing about what a gid looks like raises nowhere, which is
the exact failure mode the region-crop import path was built to avoid. This
editor writes neither shape; Tiled writes both.
Measured: `grep -n "def __load" -A 20 editor/ui/tileset.py` shows the branch
that only reports missing art `if source and image is None`, and
`tileset_geometry(40, 40, 16, 16, 4, 4)` returns 2x2 where Tiled's own rule
gives 1x1.

**8. Four `GameEventType` members are not named anywhere in `scripts/` outside
their own definition.** `POST_DISPOSE`, `PARENT_RESIZED`, `QUIT` and
`WINDOW_FOCUS_GAINED`. Cost: an event member with no listener is an API promise
the engine does not keep, and `USE` is the standing proof of what that costs.
Do not add a member before a listener exists; delete or wire these.
Anchor: `#TAG:post_dispose_unwired`. Measured by walking `scripts/` for each
member name and counting references outside `scripts/core/event_types.py`.

**9. The two silent-failure sites, in the order they will bite.**
Both are described in `CLAUDE.md`'s *Known gaps*; the ranking is the addition:
`#TAG:GameAnimationHandler.__init__` starts a sequence before any behavior
attaches, so a side-on-only or portrait-only sprite sheet raises inside the
entity constructor — that is the *first* wall a new art set hits, and it hits
before anything else in this list matters. `#TAG:GameEntity.allowed_move`
returns an unrecognised direction's vector unclamped, which is harmless only
while `move_direction` is its sole caller — so it becomes urgent the moment a
second caller exists, and not before.

**10. Three small, real and cheap.** Each is one edit; none is worth its own
rank.
- A per-tile `<objectgroup>` injects a nameless phantom layer into
  `MapDocument.layer_names()` and into `pytmx.layers`, because
  `_layer_elements` walks `root.iter()` where `_tileset_elements` deliberately
  uses `findall`. Nothing writes that shape here and Tiled does. Measured:
  `grep -n "root.iter()" scripts/loaders/map_document.py`.
- Palette zoom is per-session. It needs a key beside `grid_step`. Measured:
  `grep -n "grid_step" editor/core/settings.py` names the file and the shape.
- A folded collision companion has no hierarchy row, so the `−` button cannot
  reach it and `map.layer.remove` on the art layer does not take it along.
  Undo, a script or Tiled are the routes left. Measured:
  `grep -rn "map.layer.remove" editor/ui/hierarchy.py`.

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
