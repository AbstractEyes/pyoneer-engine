"""Verify the collision overlay, its glyphs and the mode switch.

Not a screenshot test, but it does look at pixels -- because the whole point
of this module is that a human can tell seventeen masks apart at 16px, and
"the code ran" says nothing about that. So it asserts:

  * every mask in the domain renders a DISTINCT image, and the open cell
    renders nothing at all
  * a blocked edge's bar lands on THAT edge -- the failure mode of a
    four-way glyph is a transposed bit, which looks perfectly fine until you
    walk into a wall that is not there
  * the overlay builds a 100x100 field inside the frame budget, and shows
    different pixels for different masks once composited
  * one cell can be changed in place without disturbing its neighbour, which
    is the property the private pixmap exists to protect
  * the resolve treats an empty cell and a star as abstention, which is the
    bug that silently erased a region of blocked water in the prototype
  * a mode switch does not rebind a single tool key

Builds every fixture in this file. Nothing here reads data/maps/test.tmx:
the author paints in it, so a check that asserted what it contains would be
red by lunchtime.

Skips cleanly when PySide6 is not installed; the engine does not depend on
it and a bare clone should not fail here.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import importlib.util
import os
import sys
import time

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt                                  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap            # noqa: E402
from PySide6.QtWidgets import (                                        # noqa: E402
    QApplication,
    QGraphicsScene,
    QStyleOptionGraphicsItem,
    QWidget,
)

from editor.core.layers import (                                       # noqa: E402
    BLOCK_ALL,
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    PASS_ALL,
    STAR,
)
from editor.core.paint import Tool                                     # noqa: E402
from editor.ui import collision_view as view                           # noqa: E402
from editor.ui.collision_view import (                                 # noqa: E402
    MASK_DOMAIN,
    NO_DATA,
    CollisionOverlay,
    EditMode,
    MaskPalette,
    build_mode_actions,
    glyph_pixmaps,
    layer_from_masks,
    masks_from_layer,
    resolve_field,
)

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got} want={want}")
    if not ok:
        failures.append(label)


application = QApplication.instance() or QApplication([])

TILE = 16


def fingerprint(pixmap: QPixmap) -> bytes:
    """Every pixel of a glyph, in a format that does not depend on Qt's
    internal premultiplication choice."""
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    return image.bits().tobytes()


def opaque_pixels(image: QImage, rect: tuple[int, int, int, int]) -> int:
    """How many pixels in a region are more than faintly inked.

    The wash is alpha 52, so the threshold sits above it: this counts BARS
    and RINGS, not the tint they sit on.
    """
    left, top, width, height = rect
    count = 0
    for y in range(top, top + height):
        for x in range(left, left + width):
            if image.pixelColor(x, y).alpha() > 128:
                count += 1
    return count


def glyph_image(mask: int) -> QImage:
    return glyphs[mask].toImage().convertToFormat(QImage.Format_ARGB32)


# --------------------------------------------------------------------------
print("the rules come from editor/core/collision.py, not from the view")
# --------------------------------------------------------------------------
# This module draws; it does not decide. What is asserted here is only what
# the DRAWING depends on -- collision.py has its own check for the rules.
expect("no-data is outside the authorable mask domain, so it can have no glyph",
       NO_DATA in MASK_DOMAIN, False)
expect("the domain is 0..STAR inclusive, seventeen masks",
       (len(MASK_DOMAIN), MASK_DOMAIN[0], MASK_DOMAIN[-1]), (17, 0, STAR))
expect("the view resolves through collision.resolve, with no second copy",
       [name for name in ("resolve_masks", "_fallback_resolve_masks")
        if hasattr(view, name)], [])


# --------------------------------------------------------------------------
print()
print("every mask draws a different thing, and 'open' draws nothing")
# --------------------------------------------------------------------------
glyphs = glyph_pixmaps(TILE, TILE)
expect("one pixmap per authorable mask", len(glyphs), len(MASK_DOMAIN))
expect("each is exactly one cell",
       {(g.width(), g.height()) for g in glyphs.values()}, {(TILE, TILE)})
expect("the set is cached, not rebuilt",
       glyph_pixmaps(TILE, TILE) is glyphs, True)
expect("a different keyline is a different cache entry",
       glyph_pixmaps(TILE, TILE, QColor(0, 0, 0)) is glyphs, False)

prints = {mask: fingerprint(pixmap) for mask, pixmap in glyphs.items()}
expect("every mask is visually distinct", len(set(prints.values())),
       len(MASK_DOMAIN))
# A fresh QPixmap is uninitialised, so the blank has to be filled explicitly.
empty = QPixmap(TILE, TILE)
empty.fill(Qt.transparent)
blank = fingerprint(empty)
expect("an open cell is drawn as nothing at all",
       prints[PASS_ALL] == blank, True)
expect("and every other mask is not",
       [m for m in MASK_DOMAIN if m and prints[m] == blank], [])


# --------------------------------------------------------------------------
print()
print("a blocked edge's bar is on THAT edge -- the transposed-bit guard")
# --------------------------------------------------------------------------
STRIP = 3            # the outer three pixels of a 16px cell
EDGES = {
    "up": (0, 0, TILE, STRIP),
    "down": (0, TILE - STRIP, TILE, STRIP),
    "left": (0, 0, STRIP, TILE),
    "right": (TILE - STRIP, 0, STRIP, TILE),
}
for bit, name in ((BLOCK_UP, "up"), (BLOCK_DOWN, "down"),
                  (BLOCK_LEFT, "left"), (BLOCK_RIGHT, "right")):
    image = glyph_image(bit)
    inked = {edge: opaque_pixels(image, rect) > 0 for edge, rect in EDGES.items()}
    expect(f"blocking {name} inks only the {name} edge",
           sorted(edge for edge, hit in inked.items() if hit), [name])

image = glyph_image(BLOCK_ALL)
expect("a fully blocked cell inks all four edges",
       sorted(edge for edge, rect in EDGES.items()
              if opaque_pixels(image, rect) > 0),
       ["down", "left", "right", "up"])
expect("but leaves the corners open, so a wall run stays countable",
       opaque_pixels(image, (0, 0, 2, 2)), 0)
expect("and washes the whole cell so it survives being zoomed out",
       image.pixelColor(TILE // 2, TILE // 2).alpha() > 0, True)

star = glyph_image(STAR)
expect("star owns the centre",
       opaque_pixels(star, (6, 6, 4, 4)) > 0, True)
expect("and touches no edge, so it can never read as a direction",
       sorted(edge for edge, rect in EDGES.items()
              if opaque_pixels(star, rect) > 0), [])
expect("while a direction leaves the centre alone, so the two can combine",
       opaque_pixels(glyph_image(BLOCK_UP), (7, 7, 2, 2)), 0)


# --------------------------------------------------------------------------
print()
print("the overlay builds a 100x100 field inside the frame budget")
# --------------------------------------------------------------------------
WIDTH = HEIGHT = 100
CELLS = WIDTH * HEIGHT
# A field with something in every mask, arranged so neighbours differ.
field = [MASK_DOMAIN[(x * 7 + y * 3) % len(MASK_DOMAIN)]
         for y in range(HEIGHT) for x in range(WIDTH)]

view.clear_cache()                       # bake from cold, so the budget is honest
started = time.perf_counter()
overlay = CollisionOverlay(WIDTH, HEIGHT, TILE, TILE)
overlay.bake(field)
elapsed_ms = (time.perf_counter() - started) * 1000.0
print(f"       cold build of {CELLS:,} cells took {elapsed_ms:.1f} ms")
expect("a cold 100x100 build costs under 50 ms", elapsed_ms < 50.0, True)
expect("it covers the whole map",
       overlay.boundingRect(), QRectF(0, 0, WIDTH * TILE, HEIGHT * TILE))
expect("it sits above the grid and below the stroke ghost",
       (1000 < overlay.Z < 2000, overlay.zValue()), (True, 1600))
expect("it remembers what it was given",
       [overlay.mask_at(x, 0) for x in range(4)], field[:4])

blocked = next(i for i, m in enumerate(field) if m == BLOCK_ALL)
opened = next(i for i, m in enumerate(field) if m == PASS_ALL)
starred = next(i for i, m in enumerate(field) if m == STAR)
cells = {name: overlay.cell_image(index % WIDTH, index // WIDTH)
         for name, index in (("blocked", blocked), ("open", opened),
                             ("star", starred))}
expect("distinct masks composite to distinct pixels",
       len({c.convertToFormat(QImage.Format_ARGB32).bits().tobytes()
            for c in cells.values()}), 3)
expect("an open cell composites to nothing",
       opaque_pixels(cells["open"].convertToFormat(QImage.Format_ARGB32),
                     (0, 0, TILE, TILE)), 0)


# --------------------------------------------------------------------------
print()
print("one cell changes in place, and only that cell")
# --------------------------------------------------------------------------
before_neighbour = overlay.cell_image(3, 0).convertToFormat(
    QImage.Format_ARGB32).bits().tobytes()
overlay.set_cell(2, 0, BLOCK_ALL)
expect("the mask it was told", overlay.mask_at(2, 0), BLOCK_ALL)
expect("the neighbour is untouched",
       overlay.cell_image(3, 0).convertToFormat(
           QImage.Format_ARGB32).bits().tobytes() == before_neighbour, True)
expect("the edited cell shows the new glyph",
       overlay.cell_image(2, 0).convertToFormat(
           QImage.Format_ARGB32).bits().tobytes()
       == glyph_image(BLOCK_ALL).bits().tobytes(), True)
overlay.set_cell(2, 0, NO_DATA)
expect("erasing a cell clears it rather than blending over it",
       opaque_pixels(overlay.cell_image(2, 0).convertToFormat(
           QImage.Format_ARGB32), (0, 0, TILE, TILE)), 0)
expect("an out-of-bounds write is ignored, not a crash",
       overlay.set_cell(WIDTH, 0, BLOCK_ALL), None)


# --------------------------------------------------------------------------
print()
print("paint() blits only what the view exposed")
# --------------------------------------------------------------------------
scene = QGraphicsScene()
scene.setSceneRect(overlay.boundingRect())
scene.addItem(overlay)
target = QPixmap(64, 64)
target.fill(Qt.transparent)
painter = QPainter(target)
option = QStyleOptionGraphicsItem()
option.exposedRect = QRectF(0, 0, 64, 64)
overlay.paint(painter, option, None)
painter.end()
expect("painting an exposed region drew something",
       opaque_pixels(target.toImage().convertToFormat(QImage.Format_ARGB32),
                     (0, 0, 64, 64)) > 0, True)
option.exposedRect = QRectF(-500, -500, 10, 10)
painter = QPainter(target)
expect("an exposed region off the item is a no-op",
       overlay.paint(painter, option, None), None)
painter.end()
scene.removeItem(overlay)


# --------------------------------------------------------------------------
print()
print("all layers resolve to one answer, top-most first")
# --------------------------------------------------------------------------
# Three 2x2 layers. Cell 0: the top decides. Cell 1: the top abstains by
# being empty. Cell 2: the top abstains by starring. Cell 3: nobody says
# anything at all.
stack = [
    layer_from_masks([BLOCK_UP, NO_DATA, STAR, NO_DATA], 2, "top"),
    layer_from_masks([BLOCK_DOWN, BLOCK_LEFT, NO_DATA, STAR], 2, "middle"),
    layer_from_masks([BLOCK_LEFT, BLOCK_LEFT, BLOCK_RIGHT, NO_DATA], 2, "bottom"),
]
masks, owners, conflicts = resolve_field(stack, 2, 2)
expect("the top-most layer that says something decides",
       masks, [BLOCK_UP, BLOCK_LEFT, BLOCK_RIGHT, NO_DATA])
expect("and the view records which layer that was", owners, [0, 1, 2, -1])
expect("an empty cell abstains, it does not unblock what is under it",
       masks[1], BLOCK_LEFT)
expect("a star abstains too -- that is what star MEANS",
       masks[2], BLOCK_RIGHT)
expect("a disagreement below the decider is flagged",
       conflicts, [True, False, False, False])
expect("an unauthored cell is drawn as nothing, not as an assertion",
       masks[3], NO_DATA)
expect("though the runtime's own default is still available",
       resolve_field(stack, 2, 2, undecided=PASS_ALL)[0][3], PASS_ALL)
expect("no layers at all resolves to no data",
       resolve_field([], 2, 1), ([NO_DATA, NO_DATA], [-1, -1], [False, False]))
expect("reversing the stack changes who decides -- order is a contract",
       resolve_field(list(reversed(stack)), 2, 2)[0][0], BLOCK_LEFT)

stacked = CollisionOverlay(2, 2, TILE, TILE)
stacked.bake_resolved(stack)
expect("the overlay agrees with the plain resolve",
       [stacked.mask_at(x, y) for y in range(2) for x in range(2)], masks)
expect("the deciding layer is legible per cell",
       stacked.owner_at(1, 0), 1)
expect("a conflicted cell says so in the status line",
       "disagrees" in stacked.describe(0, 0), True)
expect("an undecided cell says it has no opinion",
       (stacked.owner_at(1, 1), stacked.describe(1, 1)),
       (-1, "no opinion"))
# Provenance ticks the top-left 2x2; a plain bake must not, or a single-layer
# view grows a channel that means nothing.
tick = stacked.cell_image(0, 0).convertToFormat(QImage.Format_ARGB32)
expect("a resolved cell carries its provenance tick",
       tick.pixelColor(0, 0), view.PROVENANCE[0])
plain = CollisionOverlay(2, 2, TILE, TILE)
plain.bake([BLOCK_UP, PASS_ALL, PASS_ALL, PASS_ALL])
expect("a single-layer bake is the glyph and nothing else",
       plain.cell_image(0, 0).convertToFormat(
           QImage.Format_ARGB32).bits().tobytes()
       == glyph_image(BLOCK_UP).bits().tobytes(), True)
short = CollisionOverlay(2, 2, TILE, TILE)
short.bake([BLOCK_UP])
expect("a layer smaller than the map is padded rather than refused",
       [short.mask_at(x, y) for y in range(2) for x in range(2)],
       [BLOCK_UP, NO_DATA, NO_DATA, NO_DATA])
expect("an unbaked overlay says nothing anywhere",
       CollisionOverlay(2, 2, TILE, TILE).mask_at(1, 1), NO_DATA)


# --------------------------------------------------------------------------
print()
print("a layer's gids become masks")
# --------------------------------------------------------------------------
class _Layer:
    """The smallest thing `masks_from_layer` accepts. Built here on purpose:
    asserting against the shipped map's collision layer would pin content."""

    width = 2
    height = 2

    def __init__(self, gids):
        self.gids = gids

    def get_tile(self, x, y):
        return self.gids[y * self.width + x]


expect("gids map to opinions row-major, and 0 means 'nothing here'",
       masks_from_layer(_Layer([0, 1793, 1793 + BLOCK_ALL, 1793 + STAR]), 1793),
       [NO_DATA, PASS_ALL, BLOCK_ALL, STAR])
expect("a gid from some other tileset is no opinion, not 'open'",
       masks_from_layer(_Layer([65, 65, 65, 65]), 1793), [NO_DATA] * 4)
expect("an authored open cell and an empty one stay distinguishable",
       masks_from_layer(_Layer([1793, 0, 0, 0]), 1793)[:2],
       [PASS_ALL, NO_DATA])


# --------------------------------------------------------------------------
print()
print("the mode changes what the tools act on, never which key they are")
# --------------------------------------------------------------------------
expect("two modes, no more", [m.value for m in EditMode],
       ["tiles", "collision"])
expect("every mode has a label and a tip",
       [m for m in EditMode if not (m.label and m.tip)], [])
expect("tiles mode disables nothing", EditMode.TILES.disabled_tools, frozenset())
expect("collision mode disables only terrain",
       EditMode.COLLISION.disabled_tools, frozenset({Tool.AUTOTILE}))
expect("brush, fill, rectangle, eraser and picker all still work",
       [t.value for t in Tool if not EditMode.COLLISION.allows(t)],
       ["autotile"])
expect("the mode shortcut is not a tool shortcut",
       view.MODE_SHORTCUT.upper() in {"B", "R", "G", "E", "I"}, False)
expect("toggling twice comes home", EditMode.TILES.other.other, EditMode.TILES)

parent = QWidget()
seen: list[EditMode] = []
switch = build_mode_actions(parent, seen.append)
expect("it starts in tiles mode", switch.mode, EditMode.TILES)
expect("all-layers is meaningless until collision mode",
       switch.all_layers.isEnabled(), False)
expect("the mode buttons are mutually exclusive",
       switch.group.isExclusive(), True)
switch.toggle.trigger()
expect("the shortcut flips the mode", switch.mode, EditMode.COLLISION)
expect("and the caller heard about it exactly once", seen, [EditMode.COLLISION])
expect("all-layers turns on with the mode",
       switch.all_layers.isEnabled(), True)
switch.all_layers.setChecked(True)
expect("all-layers only counts inside collision mode",
       switch.all_layers_on, True)
switch.set_mode(EditMode.COLLISION)
expect("re-selecting the live mode does not re-notify the canvas",
       seen, [EditMode.COLLISION])
switch.toggle.trigger()
expect("and back", (switch.mode, switch.all_layers_on),
       (EditMode.TILES, False))
expect("every mode has an icon",
       [m for m in EditMode if view.mode_icon(m).isNull()], [])

# Which mode may address something smaller than a tile. Both halves, because
# the interesting failure is not "collision forgot to subdivide" -- that is
# loud -- but "tiles started to", which quietly quarters the grid an author
# paints floor on the moment a companion declares `pyoneer_subcell="4"`.
expect("collision mode addresses whatever the companion declares",
       EditMode.COLLISION.subdivides, True)
expect("...and tile mode never does, whatever the map declares",
       EditMode.TILES.subdivides, False)
expect("...so exactly one mode subdivides, not zero and not both",
       [m for m in EditMode if m.subdivides], [EditMode.COLLISION])


# --------------------------------------------------------------------------
print()
print("the mask palette offers exactly what is authorable")
# --------------------------------------------------------------------------
palette = MaskPalette(parent)
picked: list[int] = []
palette.mask_picked.connect(picked.append)
expect("one swatch per authorable mask",
       [palette.mask_at(index % palette.COLUMNS, index // palette.COLUMNS)
        for index in range(len(MASK_DOMAIN))], list(MASK_DOMAIN))
expect("and nothing past the end",
       palette.mask_at(palette.COLUMNS - 1, palette.rows - 1), None)
palette.select_mask(STAR)
expect("picking emits a mask, not a gid", picked, [STAR])
expect("the selection sticks", palette.mask, STAR)
palette.select_mask(999)
expect("an unauthorable mask is refused", palette.mask, STAR)


# --------------------------------------------------------------------------
print()
print("a 4px sub-cell still reads as red, amber and washed")
# --------------------------------------------------------------------------
# `pyoneer_subcell="4"` asks this module to draw a quarter-tile cell. Every
# accent here has a one-device-pixel floor that the shape underneath it does
# not, so at 4px the 1px keyline exactly covered the 1px bar and the star's
# 1px outline swallowed its 0.6px ring. Measured before `_wants_keyline`: a
# fully blocked 4px cell held ZERO pixels of BAR and rendered near-black.
SUB = 4


def dominant(pixmap):
    """The most common fully-opaque colour in a glyph, as an (r, g, b)."""
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    tally: dict[tuple[int, int, int], int] = {}
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() <= 128:
                continue
            key = (colour.red(), colour.green(), colour.blue())
            tally[key] = tally.get(key, 0) + 1
    return max(tally, key=tally.get) if tally else None


def redness(colour):
    """Is this colour on the BAR side of the palette rather than the keyline
    side? BAR is (255, 74, 74) and KEYLINE is (40, 0, 6), so one number
    separates them and no threshold has to be tuned."""
    return colour is not None and colour[0] > 128


fine = glyph_pixmaps(SUB, SUB)
expect("the whole domain still draws at a sub-cell size",
       (len(fine), {(g.width(), g.height()) for g in fine.values()}),
       (len(MASK_DOMAIN), {(SUB, SUB)}))
expect("a blocked 4px cell reads as the bar's red, not the keyline's black",
       redness(dominant(fine[BLOCK_ALL])), True)
expect("...and its 16px sibling still does too, so nothing regressed",
       redness(dominant(glyphs[BLOCK_ALL])), True)
# The other half of the keyline rule: at 16px the hairline is still THERE.
# Dropping it everywhere would pass the two assertions above and quietly
# undo the design this module was verified at. The keyline's signature is an
# opaque pixel inside the bar that is DARKER than the bar, which is what it
# is for and needs no threshold tuning: BAR's red is 255 and KEYLINE's is 40.
def darkened(image, rect) -> int:
    left, top, width, height = rect
    count = 0
    for y in range(top, top + height):
        for x in range(left, left + width):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 128 and colour.red() < 200:
                count += 1
    return count


up_16 = glyph_image(BLOCK_UP)
expect("the 16px bar keeps its inward keyline",
       (darkened(up_16, (3, 0, 10, 5)) > 0,
        opaque_pixels(up_16, (3, 0, 10, 5)) > 0), (True, True))
up_4 = fine[BLOCK_UP].toImage().convertToFormat(QImage.Format_ARGB32)
expect("while the 4px bar is bar and nothing else",
       (darkened(up_4, (0, 0, SUB, SUB)), opaque_pixels(up_4, (0, 0, SUB, SUB)) > 0),
       (0, True))
expect("which is the rule, stated where the drawing reads it",
       view._wants_keyline(SUB / 16.0, SUB / 16.0), False)
expect("while an 8px sub-cell still has room, so the rule is not 'never'",
       view._wants_keyline(8 / 16.0, 8 / 16.0), True)

star_fine = fine[STAR].toImage().convertToFormat(QImage.Format_ARGB32)
amber = [star_fine.pixelColor(x, y)
         for y in range(SUB) for x in range(SUB)
         if star_fine.pixelColor(x, y).alpha() > 0]
expect("a 4px star is still amber rather than a dark blob",
       all(c.red() > 128 and c.green() > 96 and c.blue() < 160 for c in amber)
       and bool(amber), True)
blank_sub = QPixmap(SUB, SUB)
blank_sub.fill(Qt.transparent)
expect("and 'open' still draws nothing at any size",
       fingerprint(fine[PASS_ALL]), fingerprint(blank_sub))
expect("...while a blocked one at the same size draws something",
       fingerprint(fine[BLOCK_ALL]) == fingerprint(blank_sub), False)

# The overlay at sub-cell resolution costs the same PIXMAP -- 400 cells of
# 4px is the same 1600x1600 surface as 100 cells of 16px -- which is the
# whole reason this is affordable. Do not "supersample" it: 400x400 at 16px
# would be a 6400x6400 pixmap, ~164 MB.
coarse_overlay = CollisionOverlay(4, 4, TILE, TILE)
fine_overlay = CollisionOverlay(4 * SUB, 4 * SUB, TILE // SUB, TILE // SUB)
expect("a 4x overlay covers exactly the same scene rectangle",
       fine_overlay.boundingRect(), coarse_overlay.boundingRect())
fine_overlay.bake([BLOCK_ALL if (x // SUB, y // SUB) == (1, 1) and y % SUB == 2
                   else NO_DATA
                   for y in range(4 * SUB) for x in range(4 * SUB)])
expect("and it can ink part of a map tile and leave the rest alone",
       (fine_overlay.mask_at(4, 6), fine_overlay.mask_at(4, 5)),
       (BLOCK_ALL, NO_DATA))
inked = opaque_pixels(fine_overlay.cell_image(4, 6)
                      .convertToFormat(QImage.Format_ARGB32), (0, 0, SUB, SUB))
bare = opaque_pixels(fine_overlay.cell_image(4, 5)
                     .convertToFormat(QImage.Format_ARGB32), (0, 0, SUB, SUB))
expect("which is visible in the pixels, not only in the model",
       (inked > 0, bare), (True, 0))

# A 1x layer read into a 4x overlay. Without the scale the wall does not
# vanish -- it moves to a quarter of its coordinates, which still looks like
# collision working.
FIRST_GID = 5


class _Cells:
    """A stand-in for `MapDocument`'s TileLayer, INCLUDING the part that bites.

    The previous version of this fixture answered 0 for any coordinate,
    which made every read past its edge look harmless -- and that is exactly
    why the crash below shipped: the real layer RAISES out of range, so the
    check proved the scale arithmetic against a reader that behaves like
    nothing in production. `get_tile` raises here for the same reason, and
    `layer_from_companion` is now asserted never to call it out of range.
    """

    name = "ForegroundCollision"
    width = height = 4

    def gids(self):
        return [FIRST_GID + BLOCK_ALL if (x, y) == (0, 3) else 0
                for y in range(self.height) for x in range(self.width)]

    def get_tile(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise AssertionError(
                f"tile ({x}, {y}) is outside layer {self.name!r} "
                f"({self.width}x{self.height})")
        return FIRST_GID + BLOCK_ALL if (x, y) == (0, 3) else 0


def answers(layer, x, y):
    """The opinion, or the name of the exception that escaped instead.

    Every read below goes through this. A field is as large as its FINEST
    layer, so a stack that mixes resolutions asks every coarser or partial
    companion for coordinates it does not have -- routinely, not
    exceptionally -- and an escaping exception here would be reported as a
    traceback rather than as the assertion that actually failed.
    """
    try:
        return layer.opinion_at(x, y)
    except Exception as exc:                                    # noqa: BLE001
        return type(exc).__name__


scaled = view.layer_from_companion(_Cells(), FIRST_GID, scale=SUB)
plain_layer = view.layer_from_companion(_Cells(), FIRST_GID)
expect("a 1x companion read at 4x answers over its whole map tile",
       [answers(scaled, 0, y) for y in (11, 12, 15, 16)],
       [NO_DATA, BLOCK_ALL, BLOCK_ALL, NO_DATA])
expect("...where the unscaled read puts the same wall four times higher",
       (answers(plain_layer, 0, 3), answers(plain_layer, 0, 12)),
       (BLOCK_ALL, NO_DATA))

# The other half, and the one that used to take the editor down: `resolve`
# reads a coordinate past a layer as abstention, and `MapDocument` reads it
# as an error.
expect("a read past a companion's own edge abstains rather than raising",
       [answers(plain_layer, x, y) for x, y in ((4, 0), (0, 4), (99, 99))],
       [NO_DATA] * 3)
expect("...and the scaled reader is bounded by the LAYER, not by the field",
       [answers(scaled, 0, y) for y in (15, 16, 400)],
       [BLOCK_ALL, NO_DATA, NO_DATA])
expect("...which is the fixture being strict, not lenient: a direct read "
       "past the edge really does raise",
       answers(view.CollisionLayer(companion=lambda x, y: _Cells().get_tile(x, y)),
               4, 0), "AssertionError")

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
