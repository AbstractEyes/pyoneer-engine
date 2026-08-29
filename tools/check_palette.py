"""The stacked tile palette, and importing a tileset by selecting a region.

WHAT THIS IS FOR
----------------
Two surfaces the author judges the editor by, and two failure shapes that
raise nowhere:

  * THE PALETTE. Every tileset the map declares, stacked in one scroll, with
    the selection stored as a tileset NAME plus a rectangle in that
    tileset's own local ids. The failure it prevents is silent: a selection
    keyed on position slides onto ANOTHER sheet's tiles the moment a tileset
    above it is added or removed, and the author paints the wrong art with a
    highlight that still looks right.

  * THE IMPORT. A region of any image, offset, resized and truncated, and
    then CROPPED to its own PNG so the tileset is a plain 0/0 grid. The
    failure that shape exists to prevent is the editor and the engine
    disagreeing about which pixels a gid names -- measured, they agree only
    at margin 0, spacing 0, and a full-width column count.

BOTH HALVES, EVERY TIME
-----------------------
The dominant failure in this tree is one half of an invariant, so a
selection asserted to SURVIVE a command is also asserted not to survive onto
different tiles; a crop asserted to be the offset region is also asserted
NOT to be the region a margin-ignoring cut would have produced; and every
assertion about a list is paired with one about the PIXELS that list was
supposed to draw.

ITS OWN FIXTURE, NEVER data/maps/test.tmx (law 4). Three tilesets over three
generated sheets, with cells painted in two of them, built in a temporary
workspace and thrown away.

Skips cleanly when PySide6 is not installed.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import importlib.util
import json
import os
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QRect, Qt                       # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent              # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

from editor.core.commands import Command                           # noqa: E402
from editor.core.scope import Scope                                # noqa: E402
from editor.core.session import Session                            # noqa: E402
from editor.ui.canvas import _PaletteSurface                       # noqa: E402
from editor.ui.main_window import EditorWindow                     # noqa: E402
from editor.ui.tileset import TilesetAtlas                         # noqa: E402
from editor.ui.tileset_dialog import (                             # noqa: E402
    TilesetImportDialog,
    safe_stem,
    write_region,
)

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


application = QApplication.instance() or QApplication([])

# --------------------------------------------------------------------------
# The fixture
# --------------------------------------------------------------------------
# Three sheets whose every tile is a different flat colour, so "the editor
# cut the pixels the engine will cut" is a comparison of images rather than
# of coordinates. The gutters of the spaced sheet are a colour no tile uses,
# which is what makes a margin-ignoring crop detectable instead of merely
# suspicious.

TILE = 16
GUTTER = QColor(9, 9, 9)


def paint_grid(path: str, columns: int, rows: int, *,
               margin: int = 0, spacing: int = 0, seed: int = 0) -> None:
    width = margin + columns * TILE + max(0, columns - 1) * spacing
    height = margin + rows * TILE + max(0, rows - 1) * spacing
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(GUTTER)
    for row in range(rows):
        for column in range(columns):
            index = seed + row * columns + column
            colour = QColor((index * 53) % 256, (index * 97 + 40) % 256,
                            (index * 29 + 90) % 256)
            left = margin + column * (TILE + spacing)
            top = margin + row * (TILE + spacing)
            for x in range(left, left + TILE):
                for y in range(top, top + TILE):
                    image.setPixelColor(x, y, colour)
    if not image.save(path, "PNG"):
        raise OSError(f"could not write the fixture sheet {path}")


FIXTURE_TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" width="4" height="4" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="1">
 <tileset firstgid="1" name="Alpha" tilewidth="16" tileheight="16" \
tilecount="16" columns="4">
  <image source="sheets/alpha.png" width="64" height="64"/>
 </tileset>
 <tileset firstgid="17" name="Beta" tilewidth="16" tileheight="16" \
tilecount="4" columns="2">
  <image source="sheets/beta.png" width="32" height="32"/>
 </tileset>
 <tileset firstgid="21" name="Spaced" tilewidth="16" tileheight="16" \
tilecount="4" columns="2" margin="4" spacing="2">
  <image source="sheets/spaced.png" width="38" height="38"/>
 </tileset>
 <tileset firstgid="25" name="collision" tilewidth="16" tileheight="16" tilecount="17" columns="17">
  <image source="sheets/collision.png" width="272" height="16"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
17,18,19,20,
21,22,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
</map>
"""


def build_workspace() -> str:
    root = tempfile.mkdtemp(prefix="pyoneer-palette-")
    maps = os.path.join(root, "data", "maps")
    sheets = os.path.join(maps, "sheets")
    os.makedirs(sheets)
    os.makedirs(os.path.join(root, "config"))
    paint_grid(os.path.join(sheets, "alpha.png"), 4, 4, seed=0)
    paint_grid(os.path.join(sheets, "beta.png"), 2, 2, seed=40)
    paint_grid(os.path.join(sheets, "spaced.png"), 2, 2,
               margin=4, spacing=2, seed=80)
    paint_grid(os.path.join(sheets, "collision.png"), 17, 1, seed=200)
    # The image the import selects out of: bigger than any region taken from
    # it, so offset, resize and truncate all have somewhere to go.
    paint_grid(os.path.join(root, "source.png"), 5, 4, seed=120)
    with open(os.path.join(maps, "fixture.tmx"), "w", encoding="utf-8",
              newline="") as handle:
        handle.write(FIXTURE_TMX)
    with open(os.path.join(root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)
    return root


def ascii_fold(text: str) -> str:
    """The typography out, so a failure can be printed on any console."""
    for fancy, plain in (("×", "x"), ("·", "."), ("–", "-"),
                         ("…", "...")):
        text = text.replace(fancy, plain)
    return " ".join(text.split())


def press(surface, point, kind):
    handler = (surface.mousePressEvent if kind == "press"
               else surface.mouseMoveEvent if kind == "move"
               else surface.mouseReleaseEvent)
    buttons = Qt.LeftButton if kind != "release" else Qt.NoButton
    event_type = (QEvent.Type.MouseButtonPress if kind == "press"
                  else QEvent.Type.MouseMove if kind == "move"
                  else QEvent.Type.MouseButtonRelease)
    handler(QMouseEvent(event_type, point, Qt.LeftButton, buttons,
                        Qt.NoModifier))


def pick_range(palette, name, left, top, right, bottom):
    """Select a rectangle through the palette's own mapping, no mouse."""
    start = palette.tile_point(name, left, top)
    end = palette.tile_point(name, right, bottom)
    palette.begin_at(start.x(), start.y())
    palette.extend_at(end.x(), end.y())
    palette.commit()
    application.processEvents()


def drag_palette(palette, start, end):
    """A real press-move-release across the palette surface."""
    surface = palette.surface
    press(surface, start, "press")
    press(surface, end, "move")
    press(surface, end, "release")
    application.processEvents()


workspace = build_workspace()
try:
    session = Session.open(workspace, genre_id="topdown_rpg")
    ORIGINAL = session.project.map("fixture").to_bytes()
    window = EditorWindow(session)
    window.show()
    application.processEvents()
    palette = window.palette
    map_dir = os.path.join(workspace, "data", "maps")

    # ----------------------------------------------------------------
    print("every tileset is on screen at once, each cut its own way")
    # ----------------------------------------------------------------
    expect("all three ART sheets are sections, in gid order",
           [(s.name, s.columns, s.rows) for s in palette.sections],
           [("Alpha", 4, 4), ("Beta", 2, 2), ("Spaced", 2, 2)])
    # THE MASK SHEET IS NOT ART. Both halves: the atlas has to KEEP it --
    # the overlay and every gid sum need it -- and the picker has to not
    # offer it, because its seventeen glyphs are an encoding, and painting
    # one onto a floor is legal TMX that draws a wall symbol.
    expect("the collision sheet is in the atlas, where the overlay needs it",
           [e.name for e in window.canvas.atlas.entries],
           ["Alpha", "Beta", "Spaced", "collision"])
    expect("...and out of the picker, where it would pose as scenery",
           palette.section("collision"), None)
    expect("...and none of them is a chooser any more",
           hasattr(palette, "chooser"), False)
    # Stacked means STACKED: each section starts below the one above it, and
    # the surface is tall enough to hold the last. A layout that overlapped
    # would still answer every question above correctly.
    tops = [s.top for s in palette.sections]
    expect("each section starts below the previous one's tiles",
           [tops[i] >= palette.sections[i - 1].bottom
            for i in range(1, len(tops))], [True, True])
    expect("...and the surface is as tall as the stack",
           palette.surface.height() >= palette.sections[-1].bottom, True)

    # THE HEADER REACHED THE PIXELS, not just the layout. A section whose
    # name is never drawn is a stack of anonymous sheets, which is the thing
    # the chooser was replaced to fix.
    drawn = palette.surface._PaletteSurface__pixmap.toImage()
    expect("a header strip is painted above every sheet",
           [drawn.pixelColor(3, s.top + 3) == _PaletteSurface.HEADER_FILL
            for s in palette.sections], [True, True, True])
    header_band = [drawn.pixelColor(x, palette.sections[0].top + 8)
                   for x in range(4, 60)]
    expect("...with the tileset's name inked into it",
           any(colour != _PaletteSurface.HEADER_FILL for colour in header_band),
           True)

    # ----------------------------------------------------------------
    print()
    print("a drag picks a stamp, and cannot pick across two tilesets")
    # ----------------------------------------------------------------

    drag_palette(palette, palette.tile_point("Alpha", 0, 0),
                 palette.tile_point("Alpha", 1, 1))
    expect("a real drag inside one sheet is a rectangle of its gids",
           (window.canvas.stamp.width, window.canvas.stamp.height,
            window.canvas.stamp.gids), (2, 2, (1, 2, 5, 6)))

    # THE CLAMP, with the half that makes it an assertion: the point really
    # is over Beta -- `locate` says so -- and the stamp is still all Alpha.
    into_beta = palette.tile_point("Beta", 1, 1)
    located = palette.locate(into_beta.x(), into_beta.y())
    expect("dragging down out of Alpha does land over Beta",
           located[0].name, "Beta")
    drag_palette(palette, palette.tile_point("Alpha", 0, 0), into_beta)
    stamp = window.canvas.stamp
    # The exact tiles, not "none of them is Beta's": `stamp()` resolves
    # every cell through the ANCHOR's section, so a membership test would
    # pass however far the rectangle ran -- an assertion that cannot fail.
    expect("...and the stamp is clamped to the sheet it started in",
           stamp.gids, (1, 2, 5, 6, 9, 10, 13, 14))
    expect("...which is a real rectangle, not a single cell",
           (stamp.width, stamp.height), (2, 4))

    # ----------------------------------------------------------------
    print()
    print("the pick readout names tiles, not the size of the rectangle")
    # ----------------------------------------------------------------
    drag_palette(palette, palette.tile_point("Beta", 0, 0),
                 palette.tile_point("Beta", 1, 1))
    # ASCII-folded before comparing: the caption is spelled with an
    # interpunct and a multiplication sign, and a check that cannot PRINT
    # its own failure on a cp1252 console turns a red line into a traceback.
    expect("a full pick counts what it holds",
           ascii_fold(palette.caption.text()), "2x2 . 4 tiles from gid 17")
    # A ragged sheet: Spaced holds 4 tiles in a 2x2, so a drag to its last
    # cell is full. Alpha's 16 in a 4x4 likewise. The honest case here is a
    # pick that runs off a SHORT last row, which this fixture makes by
    # picking past Beta's end via the clamp -- so assert the other half:
    # nothing is reported empty when nothing is.
    expect("...and says nothing about holes when there are none",
           "empty" in palette.caption.text(), False)

    # ----------------------------------------------------------------
    print()
    print("the selection is an address, so a command cannot move it")
    # ----------------------------------------------------------------
    pick_range(palette, "Spaced", 0, 0, 1, 1)
    remove_alpha = Command("map.tileset.remove", Scope.of(("map", "fixture")),
                           {"name": "Alpha"})
    before = (palette.selection, palette.stamp().gids)
    expect("a 2x2 in the third sheet is held by name",
           palette.selection, ("Spaced", 0, 0, 2, 2))

    window.canvas.set_active_layer("Floor")
    window.run(Command("map.tile.set_many",
                       Scope.of(("map", "fixture"), ("layer", "Floor")),
                       {"tiles": [[3, 3, 17]]}))
    application.processEvents()
    expect("a command rebuilds the palette and the selection survives",
           (palette.selection, palette.stamp().gids), before)
    window.undo()
    application.processEvents()

    # THE HALF THAT MATTERS. Removing a tileset ABOVE the selection shifts
    # every index below it. A position-keyed selection lands on a different
    # sheet's tiles and looks exactly as correct as it did before.
    window.run(remove_alpha)
    application.processEvents()
    expect("removing the sheet above it renumbers the sections",
           [s.name for s in palette.sections], ["Beta", "Spaced"])
    expect("...and the highlight is still on the SAME tiles",
           (palette.selection, palette.stamp().gids), before)
    window.undo()
    application.processEvents()
    expect("...and undo puts the sheet back",
           [s.name for s in palette.sections], ["Alpha", "Beta", "Spaced"])
    expect("...with the selection still where it was",
           (palette.selection, palette.stamp().gids), before)

    # And the third case: a selection whose tileset is GONE is dropped
    # rather than clamped onto whatever now sits at that index.
    pick_range(palette, "Alpha", 1, 1, 1, 1)
    window.run(remove_alpha)
    application.processEvents()
    expect("a selection whose sheet is removed is dropped, not moved",
           palette.selection, None)
    window.undo()
    application.processEvents()

    # ----------------------------------------------------------------
    print()
    print("picking on the map scrolls the palette to what it picked")
    # ----------------------------------------------------------------
    palette.scroll.setFixedSize(140, 70)
    palette.scroll.verticalScrollBar().setValue(0)
    application.processEvents()
    spaced = palette.section("Spaced")
    bar = palette.scroll.verticalScrollBar()

    def visible(section, row) -> bool:
        top = section.grid_top + row * section.cell
        return (bar.value() <= top
                and top + section.cell
                <= bar.value() + palette.scroll.viewport().height())

    expect("the bottom sheet starts out below the fold", visible(spaced, 1),
           False)
    window.canvas.picked_gid.emit(spaced.entry.first_gid + 3)
    application.processEvents()
    expect("...and picking one of its tiles scrolls it into view",
           visible(spaced, 1), True)
    expect("...with the highlight on the picked tile",
           palette.selection, ("Spaced", 1, 1, 1, 1))

    # ----------------------------------------------------------------
    print()
    print("the editor cuts the pixels the ENGINE cuts, gutters and all")
    # ----------------------------------------------------------------
    # The measurement that decides the import design, asserted in both
    # directions. `Spaced` declares margin 4 and spacing 2, which the engine
    # honours; the editor must cut the same rect, and must NOT cut the rect
    # a naive `column * tile_width` would produce.
    atlas = window.canvas.atlas
    entry = atlas.entries[2]
    sheet = QImage(os.path.join(map_dir, "sheets", "spaced.png"))
    agree, naive = [], []
    for index in range(entry.tile_count):
        gid = entry.first_gid + index
        drawn_tile = atlas.pixmap(gid).toImage().convertToFormat(sheet.format())
        engine = sheet.copy(QRect(
            entry.margin + (index % entry.columns) * (TILE + entry.spacing),
            entry.margin + (index // entry.columns) * (TILE + entry.spacing),
            TILE, TILE))
        blind = sheet.copy(QRect((index % entry.columns) * TILE,
                                 (index // entry.columns) * TILE, TILE, TILE))
        agree.append(drawn_tile == engine)
        naive.append(drawn_tile == blind)
    expect("every tile of a spaced sheet is the rect the engine reads",
           agree, [True] * entry.tile_count)
    expect("...and NOT the rect a margin-blind cut would read",
           naive, [False] * entry.tile_count)

    # ----------------------------------------------------------------
    print()
    print("import: a region of any image, offset, resized and truncated")
    # ----------------------------------------------------------------
    source = os.path.join(workspace, "source.png")
    window.add_tileset()
    application.processEvents()
    view = window.tileset_import
    expect("the importer opened, and did not block",
           (isinstance(view, TilesetImportDialog), view.isVisible(),
            view.isModal()), (True, True, False))
    view.set_image_path(source)
    expect("a fresh sheet is selected whole, so the common case is one click",
           (view.x_spin.value(), view.y_spin.value(),
            view.columns, view.rows, view.tile_count), (0, 0, 5, 4, 20))
    expect("...and a whole selection needs no crop", view.whole_sheet, True)

    # OFFSET, RESIZE, TRUNCATE -- the three the ask names, as three numbers.
    view.select_region(TILE, TILE, 3, 2)
    view.count_spin.setValue(5)
    view.set_name("Cut")
    expect("the readout names the region, the drop and the gids it will take",
           ascii_fold(view.summary_text()),
           "x=16 y=16 . 3 x 2 = 5 tiles . gids 42-46 (1 dropped off the end)")
    expect("...and a partial selection is a crop", view.whole_sheet, False)

    crop = view.crop_path()
    expect("the crop lands beside the map, named after the tileset",
           os.path.relpath(crop, map_dir).replace(os.sep, "/"),
           "tilesets/Cut.png")
    view.add_button.click()
    application.processEvents()

    document = session.project.map("fixture")
    expect("Add declared it through the command stream",
           ([c.verb for c in session.history()[-1].commands],
            document.tileset_names()),
           (["map.tileset.add"], ["Alpha", "Beta", "Spaced", "collision",
                                  "Cut"]))
    added = [ref for ref in document.tilesets() if ref.name == "Cut"][0]
    expect("...at the truncated tile count, over the region's columns",
           (added.first_gid, added.tile_count, added.columns), (42, 5, 3))

    # THE PIXELS, not the numbers. The crop has to BE the offset region --
    # and, the other half, must not be the region an ignored offset gives.
    written = QImage(crop)
    original = QImage(source)
    expect("the crop is the offset region of the source",
           written == original.copy(QRect(TILE, TILE, 3 * TILE, 2 * TILE)),
           True)
    expect("...and NOT the region an ignored offset would have taken",
           written == original.copy(QRect(0, 0, 3 * TILE, 2 * TILE)), False)
    expect("...at exactly the resized size", (written.width(), written.height()),
           (3 * TILE, 2 * TILE))

    # THE DECLARATION the crop is cut for: a plain 0/0 grid, which is the
    # one geometry the editor and the engine agree on.
    element = [e for e in document.root.findall("tileset")
               if e.get("name") == "Cut"][0]
    expect("the tmx declares no margin and no spacing at all",
           (element.get("margin"), element.get("spacing")), (None, None))

    # AND IT REACHED THE PALETTE, which is the wire a check about lists
    # cannot see. The truncated end must be unreachable, not merely
    # uncounted.
    fresh = TilesetAtlas(document, tile_width=TILE, tile_height=TILE)
    expect("the last declared tile resolves", fresh.entry_for(46) is not None,
           True)
    expect("...and the truncated one does not", fresh.entry_for(47), None)
    tile_two = fresh.pixmap(43).toImage().convertToFormat(original.format())
    expect("...and its second tile is the second tile of the REGION",
           tile_two == original.copy(QRect(2 * TILE, TILE, TILE, TILE)), True)
    expect("the palette drew a section for it",
           [s.name for s in palette.sections],
           ["Alpha", "Beta", "Spaced", "Cut"])

    # THE RAGGED END, both halves. Five tiles in three columns leaves one
    # hole, and a pick landing entirely in it would set a brush that paints
    # nothing -- which looks exactly like a click that worked.
    quiet = len(session.history())
    pick_range(palette, "Cut", 2, 1, 2, 1)
    expect("a pick entirely past a ragged end sets no brush, and says so",
           (len(session.history()), palette.caption.text()),
           (quiet, "that rectangle holds no tiles"))
    pick_range(palette, "Cut", 1, 1, 1, 1)
    expect("...while the real tile beside it does",
           window.canvas.stamp.gids, (46,))

    # ----------------------------------------------------------------
    print()
    print("the import is one undoable command, and the crop is not a lie")
    # ----------------------------------------------------------------
    window.undo()
    application.processEvents()
    expect("one undo takes the declaration back byte-identically",
           session.project.map("fixture").to_bytes() == ORIGINAL, True)
    expect("...and the palette forgets the section with it",
           [s.name for s in palette.sections], ["Alpha", "Beta", "Spaced"])
    # The bargain `map.tileset.mask.set` already strikes with its .blitmask:
    # undo removes the DECLARATION and leaves the file, because an
    # unreferenced PNG is harmless and a map raising FileNotFoundError at
    # load is not.
    expect("...but the written sheet stays on disk", os.path.isfile(crop), True)

    # NEVER OVERWRITES DIFFERENT PIXELS, both halves.
    expect("re-writing the identical crop is a no-op, so re-adding works",
           write_region(original, QRect(TILE, TILE, 3 * TILE, 2 * TILE), crop),
           False)
    clash = "no refusal"
    try:
        write_region(original, QRect(0, 0, 3 * TILE, 2 * TILE), crop)
    except OSError as exc:
        clash = "already holds different pixels" in str(exc)
    expect("...and writing DIFFERENT pixels over it raises, naming the file",
           clash, True)

    # THE OFF-BY-ONE CLAUSE, which is the one thing that catches a 16px
    # sheet cut at 15 -- legal TMX, believable tilecount, every tile
    # carrying a seam of its neighbour. Both halves, because it is now
    # conditional: a partial tile's worth of leftover is the symptom, and a
    # selection that deliberately stops short is not.
    view.select_region(0, 0, 5, 4)
    view.tile_width_spin.setValue(15)
    view.tile_height_spin.setValue(15)
    view.refresh()
    expect("a sheet cut at the wrong size names the pixels no tile claims",
           ("px to the right" in view.summary_text(),
            "px below" in view.summary_text()), (True, True))
    view.tile_width_spin.setValue(TILE)
    view.tile_height_spin.setValue(TILE)
    view.select_region(TILE, TILE, 2, 2)
    expect("...and a region that deliberately stops short says nothing",
           "claimed by no tile" in view.summary_text(), False)

    expect("a name with nothing usable in it has no file to write to",
           safe_stem("(!)"), "")
    view.set_name("(!)")
    expect("...so the button greys with the reason",
           (view.add_button.isEnabled(), "no letters or digits" in
            (view.problem() or "")), (False, True))
    view.close()
    application.processEvents()
    expect("closing the importer lets the door open again",
           window.tileset_import, None)

    window.close()
finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("PASS")
