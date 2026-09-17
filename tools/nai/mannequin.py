"""Layouts, poses, and the synthetic mannequin init image (brief 4.1-4.3).

OWNER: implementer B.

RESPONSIBILITY
--------------
Say where each frame of a strip sits on the canvas (`LAYOUTS`, `strip`), how
the mannequin stands in each frame (`POSES`), and draw the init image an
img2img request starts from (`render_init`), returning the snapped centers
every request for that strip must carry -- generate included, which sends no
image but still needs the centers.

INVARIANTS
----------
* CENTERS ARE COMPUTED, NEVER TYPED. `render_init` measures each drawn
  figure's bounding box (outline included), converts its center to canvas
  pixels, divides by width/height and applies `model.snap`. Two frames
  snapping to the same (x, y) RAISE ValueError naming both frame indices.
* A CENTER STAYS IN ITS CELL. A snapped center that, mapped back to canvas
  pixels, lies outside its own cell's canvas rect RAISES ValueError: the
  character box would sit on a neighbour, even when no two frames collide.
* SOURCE SCALE, THEN NEAREST. Every figure is drawn at source scale
  (layout.src_w x layout.src_h) and the flattened image is upscaled by
  exactly layout.k with Image.Resampling.NEAREST, so every source pixel is a
  k x k block aligned with the 1/8 latent grid.
* OPAQUE, GREY, RGB. The output PNG is mode RGB (PNG colour type 2) on
  model.BACKGROUND_RGB, exactly layout.width x layout.height.
* A FIGURE STAYS IN ITS CELL. Any opaque pixel of frame i (outline included)
  outside cell i's source rect RAISES ValueError -- the pose or the layout
  is wrong, and a figure bleeding into a neighbour poisons the mask too.
* DETERMINISTIC. The same (layout, poses, colours) gives byte-identical PNG
  bytes and identical centers; `params_sha256` names that input, and
  `DRAW_VERSION` is part of it so a change to the drawing code renames it.
* Pillow and the standard library only. No numpy.

DRAWING (brief 4.3), at H_SRC = 40 source pixels
------------------------------------------------
head 8x8 (top 3 rows hair plus BACK_HAIR at the back of the skull, rest
skin, 1 px dark eye on the facing side, corners rounded); torso 6x12 (tunic;
top 2 rows scarf, a SCARF_TAIL px scarf tail trailing behind, belt colour on
the bottom row); thigh 9 and shin 9, width 3 (pants; the last 3 px of the
shin in boots) and a FOOT_W x 2 boot at the ankle, heel under the shin, toe
forward, square to the shin; upper arm 7 and forearm 6, width 2 (tunic
sleeve; 2 px hand in skin). Standing, the body is exactly H_SRC rows: head
8 + torso 12 + thigh 9 + shin 9 + foot 2.

GARMENTS (author, 2026-09-17), model.Garments, drawn at source scale
-------------------------------------------------------------------
Every garment is a shape in source pixels, so the x8 upscale can only make
it blockier, never smaller: a wizard HAT is a one-row brim HAT_BRIM_W across
the crown plus a HAT_CONE_H cone that leans back and bends further back over
its top HAT_BEND_ROWS rows, drawn after the head so it covers the crown and
leaves the hair showing below it at the back; a CAPE is a `_flare` from the
shoulders' back edge, drawn FIRST so the far arm lies on top of it, rooted
CAPE_BACK px behind the torso plus CAPE_LEAN_BACK per degree of lean and hung
at CAPE_ANGLE behind straight down plus CAPE_LEAN_SWING per degree of lean and
CAPE_LIFT_SWING per px of lift, so it trails in a run and streams in a jump;
a DRESS colours the torso and both sleeves and hangs an A-line skirt of
SKIRT_LEN rows from the waist, its hem carried SKIRT_SWING toward the
leading thigh, drawn after the far leg and before the near one so the
leading knee stays in front of it, with both legs in `skin` below the hem;
HEELS replace the boot with `_in_heel`'s sole, post and toe and take the
boot shaft and the boot-coloured ankle off the shin. A dress also ends both
sleeves at the elbow (`_arm`'s `forearm`), so the arms read against it, with
WRIST_PX of OUTLINE_RGB between that bare forearm and its hand -- a forearm
and a hand in one skin value is a blunt plank, not an arm.

Draw order: cape, far arm, far leg, torso, skirt, head, hat, near leg, near
arm. Far limbs use
colours x FAR_SHADE; near limbs use base colours. INNER LINES, one rule in
one direction -- THE PART BEHIND IS DARKENED to x INNER_SHADE of its own
colour: a near limb laid over the torso or a far limb would vanish into the
same tunic or pants colour, so every pixel of another part 4-adjacent to a
near limb is darkened; and the cape, which is drawn first and so lies behind
everything, is itself darkened wherever it touches another part, or its hem
ends inside the skirt with no boundary and the two garments read as one
two-tone flare. Outline: 1 source px model.OUTLINE_RGB,
made with alpha.filter(ImageFilter.MaxFilter(3)), ring filled, figure
composited on top.

Geometry: angles are degrees from straight down, + toward the facing side
(right); a limb at angle a points along (sin a, cos a) in image coordinates.
Shin and forearm angles are absolute. The torso rises from the hip along
(sin lean, -cos lean), so a positive lean tips the shoulders forward. The
shoulder sits SHOULDER_DROP px below the top of the torso on its axis.

Placement: hip column = cell.hip_x_src; the row is whatever puts the LOWEST
OPAQUE ROW OF THE OUTLINED FIGURE on cell.baseline_src - pose.lift -- which,
for every shipped pose, is the outline under a boot. That is the row
post-processing P7 aligns on, so a faithful generation needs no shift. Hip
height therefore follows from the joint angles, and walk bob comes out of
the geometry for free.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from types import MappingProxyType
from typing import Mapping, Sequence

from PIL import Image, ImageFilter

from tools.nai.model import (BACKGROUND_RGB, DEFAULT_GARMENTS, DIM_MULTIPLE,
                             FAR_SHADE, H_SRC, INIT_K, INNER_SHADE,
                             MASK_ALIGN, MAX_AREA, MIN_DIM, OUTLINE_RGB,
                             CellSpec, Garments, Layout, Pose, garment_parts,
                             garments_text, shade, snap)

# ---------------------------------------------------------------------------
# Skeleton (source pixels)
# ---------------------------------------------------------------------------

HEAD = 8
HAIR_ROWS = 3
TORSO_W = 6
TORSO_H = 12
SCARF_ROWS = 2
THIGH = 9
SHIN = 9
LEG_W = 3
BOOT_ROWS = 3
FOOT_W = 4
FOOT_H = 2
UPPER_ARM = 7
FOREARM = 6
ARM_W = 2
HAND_PX = 2
# FAR_SHADE and INNER_SHADE are imported from model (and hashed below like
# every skeleton constant): characters judges the shades a colour is drawn in.

BACK_HAIR = 2
"""Hair columns at the back of the head below HAIR_ROWS: the back of the skull
is what makes an 8x8 head read as a profile facing right."""
EYE_ROW = 4
EYE_COL = 6
"""The 1 px eye, in head-local (row, column); column 7 is the facing edge."""
SHOULDER_DROP = 1.5
SCARF_TAIL = 3
SCARF_TAIL_W = 2
DRAW_VERSION = 1
"""Bump when the drawing code changes in a way no constant above names."""

_SKELETON_NAMES: tuple[str, ...] = (
    "HEAD", "HAIR_ROWS", "TORSO_W", "TORSO_H", "SCARF_ROWS", "THIGH", "SHIN",
    "LEG_W", "BOOT_ROWS", "FOOT_W", "FOOT_H", "UPPER_ARM", "FOREARM", "ARM_W",
    "HAND_PX", "FAR_SHADE", "BACK_HAIR", "EYE_ROW", "EYE_COL",
    "SHOULDER_DROP", "SCARF_TAIL", "SCARF_TAIL_W", "INNER_SHADE",
    "DRAW_VERSION", "H_SRC", "BACKGROUND_RGB", "OUTLINE_RGB",
)
"""The constants the DEFAULT outfit is drawn from: `params_sha256` hashes
exactly these for a default-garment figure, so the shipped scout keeps the
name it has always had."""

# ---------------------------------------------------------------------------
# Garments (author, 2026-09-17): drawn at source scale, because a shape that
# only appears after the x8 upscale is a shape img2img cannot follow.
# ---------------------------------------------------------------------------

HAT_BRIM_W = 11
HAT_BRIM_ROW = 1
HAT_BRIM_BACK = 0.0
"""The brim is one row, HAT_BRIM_W wide, on head row HAT_BRIM_ROW, its centre
HAT_BRIM_BACK px behind the head's: it covers the crown, leaves the hair below
it showing at the back, and OVERHANGS THE HEAD ON BOTH SIDES. At the 1.0 it
was first drawn at, the brim's front edge was flush with the forehead and
every one of the 2.5 px of overhang sat at the back, so the silhouette was a
cone with a rear flange and the model had to invent the half of the shape
that sits over the face."""
HAT_CONE_H = 6
HAT_CONE_W = 6
HAT_TIP_W = 2
HAT_LEAN = 0.75
"""Source px the cone axis moves BACK per row, so the cone tilts backwards."""
HAT_BEND = 1.5
"""Extra px back for the top HAT_BEND_ROWS rows: the bent tip."""
HAT_BEND_ROWS = 2

CAPE_LEN = 15
"""MEASURED, so the next tuner does not retry it blind: the cape's hem ends
INSIDE the skirt (its lowest row 2-4 against the skirt's 6-8) and cannot be
lengthened out of it. 17 is the most that fits -- at 19 jump frame 2 leaves
its cell -- and 17 only reaches the skirt's hem row in the best frame while
burning the whole left margin (jump f2 to 0 source px). The cape's own
darkened line against the part in front of it, not its length, is what
separates it from the skirt; see `_figure`'s inner-line pass."""
CAPE_TOP_W = 6
CAPE_HEM_W = 9
CAPE_DROP = 0.0
"""Source px below the shoulder the cape's top edge hangs from."""
CAPE_ANGLE = 12.0
"""Degrees behind straight down a cape hangs at rest."""
CAPE_LEAN_SWING = 1.0
CAPE_LIFT_SWING = 1.2
"""Degrees further back per degree of torso lean and per px of pose lift: the
cape trails in a run and streams in a jump, out of the pose, not a table."""
CAPE_MAX_ANGLE = 38.0
CAPE_BACK = 2.0
"""Source px behind the torso's axis the cape hangs from."""
CAPE_LEAN_BACK = 0.06
"""Further px back per degree of FORWARD lean (a backward lean moves nothing).
The swing is already clamped at CAPE_MAX_ANGLE in a deep crouch, so rotating
the cape further cannot clear the near arm's backswing; moving its ROOT back
with the lean can. MEASURED on wizard_girl's jump: at lean 35 the crouch
frames' cape fell to 41 and 74 px against 94 at the apex, 17 of them under
the near arm, which chopped what was left into islands."""

WRIST_PX = 1
"""Source rows of OUTLINE_RGB between a BARE forearm and its hand. Drawn only
when the sleeve stops at the elbow (a dress): a sleeved forearm and its hand
are already two colours."""

SKIRT_LEN = 7
SKIRT_TOP_W = 6
SKIRT_HEM_W = 12
SKIRT_SWING = 3.0
"""The A-line skirt: SKIRT_LEN rows from the waist (the hip row) to a hem
just above the knee (THIGH is 9), widening from the torso's width to
SKIRT_HEM_W, its hem carried SKIRT_SWING px toward the LEADING thigh."""

HEEL_SOLE_H = 1
HEEL_SOLE_W = 4
HEEL_DROP = 1
HEEL_POST_W = 1
HEEL_TOE_W = 2
"""The heel: a HEEL_SOLE_W sole one row under the ankle, then a HEEL_POST_W
post at the back and a HEEL_TOE_W toe at the front dropping HEEL_DROP rows
further, with the arch between them open. The shin keeps the leg's own
colour all the way down (no boot shaft, no boot-coloured ankle), which is
what makes the ankle read straight."""

GARMENT_DRAW_VERSION = 1
"""Bump when the GARMENT drawing code changes in a way no constant above
names. It is hashed only for a figure that wears one (see `params_sha256`)."""

_GARMENT_SKELETON_NAMES: tuple[str, ...] = (
    "HAT_BRIM_W", "HAT_BRIM_ROW", "HAT_CONE_H", "HAT_CONE_W", "HAT_TIP_W",
    "HAT_BRIM_BACK", "HAT_LEAN", "HAT_BEND", "HAT_BEND_ROWS", "CAPE_LEN",
    "CAPE_TOP_W",
    "CAPE_HEM_W", "CAPE_DROP", "CAPE_BACK", "CAPE_LEAN_BACK", "CAPE_ANGLE",
    "CAPE_LEAN_SWING",
    "CAPE_LIFT_SWING", "CAPE_MAX_ANGLE", "SKIRT_LEN", "SKIRT_TOP_W",
    "SKIRT_HEM_W", "SKIRT_SWING", "HEEL_SOLE_H", "HEEL_SOLE_W", "HEEL_DROP",
    "HEEL_POST_W", "HEEL_TOE_W", "WRIST_PX", "GARMENT_DRAW_VERSION",
)

# ---------------------------------------------------------------------------
# Layouts (brief 4.2)
# ---------------------------------------------------------------------------

LAYOUTS: Mapping[str, Layout] = MappingProxyType({
    "L5": Layout(
        name="L5", width=1216, height=832, k=8, src_w=152, src_h=104,
        cells=tuple(
            CellSpec(rect_canvas=(8 + 240 * i, 0, 248 + 240 * i, 832),
                     hip_x_src=16 + 30 * i, baseline_src=80)
            for i in range(5)),
    ),
    "G6": Layout(
        name="G6", width=1216, height=832, k=8, src_w=152, src_h=104,
        cells=tuple(
            CellSpec(rect_canvas=(8 + 400 * col, 416 * row,
                                  408 + 400 * col, 416 + 416 * row),
                     hip_x_src=26 + 50 * col, baseline_src=48 + 52 * row)
            for row in range(2) for col in range(3)),
    ),
})
"""L5: one row of 5 cells, walk (4 + idle) and jump. G6: 3 x 2, run.
Cells are in reading order, which is caption order."""

# ---------------------------------------------------------------------------
# Poses (brief 4.3), TUNED BY EYE at source scale from the brief's starting
# table. What changed and why, so the next tuner does not undo it blind:
#   walk  arm swing widened (the brief's +-20 vanished into the torso); the
#         passing leg's thigh raised to +25/-40 so its bent knee shows in
#         front of the support leg. W3/W4 are exactly W1/W2 swapped.
#   run   R2's swing knee raised to +70 ("knee raised high" read as a bent
#         standing leg at +50); R3's front leg made knee-up (+65/0) so flight
#         no longer repeats R1's silhouette.
#   jump  the brief's J3 (arms 100/120) and J5 (arms 60/80) drew outside
#         their cells. J1 and J5 are deeper crouches with the two legs apart
#         (identical angles hid the far leg): at the brief's depth their y
#         centers sat 0.8 and ~2 canvas px from a snap boundary. J2's arms go
#         up-forward so they no longer cover the face; J4's arms flail out to
#         both sides so fall no longer repeats rise; J3's lift is 26.
# ---------------------------------------------------------------------------

_W1 = Pose(25, 20, -25, -45, -35, -20, 30, 50)
_W2 = Pose(0, 0, 25, -40, -5, 5, 5, 15)
_R1 = Pose(30, 15, -35, -80, -45, 45, 45, 135, lean=15, lift=0)
_R2 = Pose(5, -10, 70, -20, -20, 70, 20, 110, lean=15, lift=0)
_R3 = Pose(-35, -65, 65, 0, 45, 135, -45, 45, lean=15, lift=3)

POSES: Mapping[str, tuple[Pose, ...]] = MappingProxyType({
    "walk": (
        _W1,                                             # W1 contact
        _W2,                                             # W2 pass
        _W1.swapped(),                                   # W3 contact
        _W2.swapped(),                                   # W4 pass
        Pose(4, 4, -4, -4, 0, 5, 0, 5),                  # idle
    ),
    "run": (
        _R1, _R2, _R3,                                   # R1-R3
        _R1.swapped(), _R2.swapped(), _R3.swapped(),     # R4-R6
    ),
    "jump": (
        Pose(80, -45, 72, -52, -65, -35, -55, -30, lean=35, lift=0),     # J1
        Pose(-5, -15, -15, -25, 135, 160, 125, 150, lean=5, lift=8),     # J2
        Pose(80, -30, 70, -40, 120, 140, 100, 130, lean=10, lift=26),    # J3
        Pose(10, 0, -10, -15, -120, -150, 105, 140, lean=-5, lift=12),   # J4
        Pose(82, -42, 74, -50, 15, 45, 5, 35, lean=25, lift=0),          # J5
    ),
})
"""Argument order is Pose's field order: near thigh, near shin, far thigh,
far shin, near upper arm, near forearm, far upper arm, far forearm."""


def _lcm(a: int, b: int) -> int:
    return a * b // math.gcd(a, b)


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def strip(n: int, width: int, height: int, *, k: int = INIT_K) -> Layout:
    """A single-row layout of `n` cells on a width x height canvas.

    Rules (ValueError when any cannot be met):
      * 1 <= n <= 5 (only five distinct x values exist on the grid);
      * width and height are multiples of 64, width*height <= MAX_AREA,
        width % k == 0 and height % k == 0;
      * a = lcm(k, MASK_ALIGN); cell width = the largest multiple of `a` with
        n * cell_w <= width - 2k; left margin = ((width - n * cell_w) // 2)
        rounded DOWN to a multiple of `a`, and must be >= k;
      * every cell spans the full height; hip_x_src = cell source x0 +
        (cell source width) // 2; baseline_src = (src_h * 10) // 13, and
        baseline_src - H_SRC must be >= 1 (the figure fits);
      * the expected centers snap(hip_x_src * k / width) are pairwise
        distinct.
    Name: f"strip{n}_{width}x{height}". strip(5, 1216, 832) has exactly
    LAYOUTS["L5"]'s cells.
    """
    for label, v in (("n", n), ("width", width), ("height", height), ("k", k)):
        if not _is_int(v):
            raise ValueError(f"strip(): {label} must be an int, got {v!r}")
    if not 1 <= n <= 5:
        raise ValueError(f"strip(): n={n}; legal 1..5 (the grid has five x "
                         f"values)")
    if k <= 0:
        raise ValueError(f"strip(): k={k} must be positive")
    for label, dim in (("width", width), ("height", height)):
        if dim < MIN_DIM or dim % DIM_MULTIPLE:
            raise ValueError(f"strip(): {label} {dim} is not a multiple of "
                             f"{DIM_MULTIPLE} >= {MIN_DIM}")
        if dim % k:
            raise ValueError(f"strip(): {label} {dim} is not a multiple of "
                             f"k={k}")
    if width * height > MAX_AREA:
        raise ValueError(f"strip(): {width}x{height} = {width * height} px "
                         f"exceeds {MAX_AREA}")
    a = _lcm(k, MASK_ALIGN)
    cell_w = ((width - 2 * k) // n) // a * a
    if cell_w <= 0:
        raise ValueError(f"strip(): no cell width that is a multiple of {a} "
                         f"fits {n} cells in {width} px with {k} px margins")
    margin = ((width - n * cell_w) // 2) // a * a
    if margin < k:
        raise ValueError(f"strip(): left margin {margin} is below k={k}")
    src_w, src_h = width // k, height // k
    baseline = (src_h * 10) // 13
    if baseline - H_SRC < 1:
        raise ValueError(f"strip(): baseline row {baseline} leaves no room "
                         f"for a {H_SRC} px figure in {src_h} source rows")
    cells = []
    for i in range(n):
        x0 = margin + i * cell_w
        sx0 = x0 // k
        cells.append(CellSpec(rect_canvas=(x0, 0, x0 + cell_w, height),
                              hip_x_src=sx0 + (cell_w // k) // 2,
                              baseline_src=baseline))
    expected = [snap(c.hip_x_src * k / width) for c in cells]
    for i in range(n):
        for j in range(i):
            if expected[i] == expected[j]:
                raise ValueError(
                    f"strip(): cells {j} and {i} both snap to x "
                    f"{expected[i]} on a {width} px canvas")
    return Layout(name=f"strip{n}_{width}x{height}", width=width,
                  height=height, k=k, cells=tuple(cells), src_w=src_w,
                  src_h=src_h)


# ---------------------------------------------------------------------------
# Figure geometry: pure Python rasterisation at source scale
# ---------------------------------------------------------------------------

RGB = tuple[int, int, int]
_Pixels = dict[tuple[int, int], tuple[RGB, str]]


_shade = shade
"""model.shade, the one shade rule characters judges a colour by."""


def _limb_dir(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return (math.sin(r), math.cos(r))


def _segment(px: _Pixels, a: tuple[float, float], u: tuple[float, float],
             length: float, width: float, colour_at, tag: str) -> None:
    """Fill every pixel whose center lies in the rectangle swept from `a`
    along unit `u` for `length`, `width` wide: 0 <= along < length and
    -width/2 <= perp < width/2 (half-open, so an axis on a pixel center gives
    an exact integer width)."""
    ux, uy = u
    nx, ny = -uy, ux
    hw = width / 2.0
    ex, ey = a[0] + ux * length, a[1] + uy * length
    xs = (a[0] + nx * hw, a[0] - nx * hw, ex + nx * hw, ex - nx * hw)
    ys = (a[1] + ny * hw, a[1] - ny * hw, ey + ny * hw, ey - ny * hw)
    for y in range(math.floor(min(ys)) - 1, math.ceil(max(ys)) + 1):
        for x in range(math.floor(min(xs)) - 1, math.ceil(max(xs)) + 1):
            dx, dy = x + 0.5 - a[0], y + 0.5 - a[1]
            along = dx * ux + dy * uy
            perp = dx * nx + dy * ny
            if 0.0 <= along < length and -hw <= perp < hw:
                px[(x, y)] = (colour_at(along, perp), tag)


def _disc(px: _Pixels, c: tuple[float, float], radius: float, rgb: RGB,
          tag: str) -> None:
    """Fill every pixel whose center is within `radius` of `c` (a joint)."""
    for y in range(math.floor(c[1] - radius) - 1, math.ceil(c[1] + radius) + 1):
        for x in range(math.floor(c[0] - radius) - 1,
                       math.ceil(c[0] + radius) + 1):
            if (x + 0.5 - c[0]) ** 2 + (y + 0.5 - c[1]) ** 2 <= radius ** 2:
                px[(x, y)] = (rgb, tag)


def _add(p: tuple[float, float], u: tuple[float, float],
         s: float) -> tuple[float, float]:
    return (p[0] + u[0] * s, p[1] + u[1] * s)


def _in_boot(along: float, fwd: float, heel: float) -> bool:
    """The boot: FOOT_H rows past the ankle along the shin, from the heel (the
    shin's back edge) FOOT_W px toward the toe, square to the shin."""
    return 0.0 <= along < FOOT_H and heel <= fwd < heel + FOOT_W


def _in_heel(along: float, fwd: float, heel: float) -> bool:
    """The high heel: a sole row, then a post at the back and a toe at the
    front, with the arch between them open -- the notch is the whole read."""
    if 0.0 <= along < HEEL_SOLE_H:
        return heel <= fwd < heel + HEEL_SOLE_W
    if HEEL_SOLE_H <= along < HEEL_SOLE_H + HEEL_DROP:
        return (heel <= fwd < heel + HEEL_POST_W
                or heel + HEEL_SOLE_W - HEEL_TOE_W <= fwd < heel + HEEL_SOLE_W)
    return False


def _leg(px: _Pixels, hip: tuple[float, float], thigh: float, shin: float,
         leg: RGB, shoe: RGB, tag: str, *, shaft: bool = True,
         heeled: bool = False) -> None:
    """One leg in `leg`, its footwear in `shoe`.

    `shaft` draws the boot's BOOT_ROWS shaft up the shin and its ankle;
    `heeled` swaps the boot's block for `_in_heel`'s sole, post and toe.
    """
    ut = _limb_dir(thigh)
    us = _limb_dir(shin)
    knee = _add(hip, ut, THIGH)
    ankle = _add(knee, us, SHIN)
    _segment(px, hip, ut, THIGH, LEG_W, lambda al, pe: leg, tag)
    _disc(px, knee, LEG_W / 2.0, leg, tag)
    _segment(px, knee, us, SHIN, LEG_W,
             lambda al, pe: shoe if shaft and al >= SHIN - BOOT_ROWS else leg,
             tag)
    _disc(px, ankle, LEG_W / 2.0, shoe if shaft else leg, tag)
    fx, fy = us[1], -us[0]          # forward, perpendicular to the shin
    heel = -LEG_W / 2.0
    inside = _in_heel if heeled else _in_boot
    for y in range(math.floor(ankle[1]) - FOOT_W - 2,
                   math.ceil(ankle[1]) + FOOT_W + 3):
        for x in range(math.floor(ankle[0]) - FOOT_W - 2,
                       math.ceil(ankle[0]) + FOOT_W + 3):
            dx, dy = x + 0.5 - ankle[0], y + 0.5 - ankle[1]
            along = dx * us[0] + dy * us[1]
            fwd = dx * fx + dy * fy
            if inside(along, fwd, heel):
                px[(x, y)] = (shoe, tag)


def _flare(px: _Pixels, root: tuple[float, float], u: tuple[float, float],
           length: float, top_w: float, hem_w: float, rgb: RGB,
           tag: str) -> None:
    """`_segment` with a width that grows from `top_w` at `root` to `hem_w`
    at the far end, measured square to `u`: the ONE shape a cape and a skirt
    are both cut from, so they widen by one rule."""
    ux, uy = u
    nx, ny = -uy, ux
    widest = max(top_w, hem_w) / 2.0
    ex, ey = root[0] + ux * length, root[1] + uy * length
    xs = (root[0] + nx * widest, root[0] - nx * widest, ex + nx * widest,
          ex - nx * widest)
    ys = (root[1] + ny * widest, root[1] - ny * widest, ey + ny * widest,
          ey - ny * widest)
    for y in range(math.floor(min(ys)) - 1, math.ceil(max(ys)) + 1):
        for x in range(math.floor(min(xs)) - 1, math.ceil(max(xs)) + 1):
            dx, dy = x + 0.5 - root[0], y + 0.5 - root[1]
            along = dx * ux + dy * uy
            perp = dx * nx + dy * ny
            if not 0.0 <= along < length:
                continue
            hw = (top_w + (hem_w - top_w) * (along / length)) / 2.0
            if -hw <= perp < hw:
                px[(x, y)] = (rgb, tag)


def _hat(px: _Pixels, left: int, top: int, rgb: RGB) -> None:
    """The wizard hat on an 8x8 head whose top-left is (`left`, `top`): a
    wide brim across the crown, and a cone above it whose tip bends back."""
    center = left + HEAD / 2.0
    brim_axis = center - HAT_BRIM_BACK
    brim = top + HAT_BRIM_ROW
    for c in range(math.floor(brim_axis - HAT_BRIM_W / 2.0) - 1,
                   math.ceil(brim_axis + HAT_BRIM_W / 2.0) + 1):
        if -HAT_BRIM_W / 2.0 <= c + 0.5 - brim_axis < HAT_BRIM_W / 2.0:
            px[(c, brim)] = (rgb, "hat")
    for i in range(HAT_CONE_H):
        t = i / max(1, HAT_CONE_H - 1)
        width = HAT_CONE_W + (HAT_TIP_W - HAT_CONE_W) * t
        axis = center - HAT_LEAN * i
        if i >= HAT_CONE_H - HAT_BEND_ROWS:
            axis -= HAT_BEND * (i - (HAT_CONE_H - HAT_BEND_ROWS) + 1)
        row = brim - 1 - i
        for c in range(math.floor(axis - width / 2.0) - 1,
                       math.ceil(axis + width / 2.0) + 1):
            if -width / 2.0 <= c + 0.5 - axis < width / 2.0:
                px[(c, row)] = (rgb, "hat")


def _arm(px: _Pixels, shoulder: tuple[float, float], upper: float,
         fore: float, sleeve: RGB, hand: RGB, tag: str,
         forearm: RGB | None = None) -> None:
    """One arm: `sleeve` to the elbow, `forearm` (the sleeve's own colour
    when None) past it, HAND_PX of `hand` at the end.

    A dress passes the skin as `forearm` -- a short sleeve -- because a red
    arm swinging over a red skirt is a silhouette nobody can read. The hand
    is then the SAME value as the forearm it hangs off, so WRIST_PX of
    OUTLINE_RGB is drawn between them: without it the forearm and the hand
    are one blunt plank, in the same value as the bare far leg beside it
    (MEASURED on wizard_girl: four distinct far-limb colours collapsed into
    one 40 px mass, and the far arm read as a held staff). A sleeved arm
    needs no wrist -- the sleeve's own colour already breaks it -- so the
    default outfit draws exactly what it always drew.

    THE WRIST IS THE OUTLINE COLOUR, NOT A DARKER SKIN, because the inner
    line pass darkens any pixel 4-adjacent to a near limb: a hand drawn at
    x INNER_SHADE becomes x INNER_SHADE AGAIN there, a fourth shade outside
    the family `characters` judges and 29.7 from the outline. OUTLINE_RGB
    darkens to a shade of itself, which is already drawn everywhere.
    """
    uu = _limb_dir(upper)
    uf = _limb_dir(fore)
    lower = sleeve if forearm is None else forearm
    wrist = FOREARM - HAND_PX

    def forearm_colour(al: float, _pe: float) -> RGB:
        if al >= wrist:
            return hand
        if forearm is not None and al >= wrist - WRIST_PX:
            return OUTLINE_RGB
        return lower
    elbow = _add(shoulder, uu, UPPER_ARM)
    _disc(px, shoulder, ARM_W / 2.0, sleeve, tag)
    _segment(px, shoulder, uu, UPPER_ARM, ARM_W, lambda al, pe: sleeve, tag)
    _disc(px, elbow, ARM_W / 2.0, sleeve, tag)
    _segment(px, elbow, uf, FOREARM, ARM_W, forearm_colour, tag)


def _figure(pose: Pose, colours: Mapping[str, RGB],
            garments: Garments = DEFAULT_GARMENTS) -> _Pixels:
    """The un-outlined figure in local coordinates: the hip column is x 0 and
    the hip sits on the boundary above row 0 (legs start at row 0, the torso
    ends at row -1).

    `colours` holds exactly `model.garment_parts(garments)`; what each
    garment draws is in the module docstring's GARMENTS section.
    """
    px: _Pixels = {}
    hip = (0.5, 0.0)
    lean = math.radians(pose.lean)
    up = (math.sin(lean), -math.cos(lean))
    forward = (math.cos(lean), math.sin(lean))
    shoulder = _add(hip, up, TORSO_H - SHOULDER_DROP)
    neck = _add(hip, up, TORSO_H)

    skin, hair, belt = colours["skin"], colours["hair"], colours["belt"]
    dressed = garments.legwear == "dress"
    heeled = garments.footwear == "heels"
    # The body colour clothes the torso AND the sleeves: a dress has no
    # separate tunic, so one name carries both.
    body = colours["dress"] if dressed else colours["tunic"]
    leg = skin if dressed else colours["pants"]
    shoe = colours["heels"] if heeled else colours["boots"]
    scarf = colours["scarf"] if garments.neck == "scarf" else None

    if garments.cape:
        # Behind everything, including the far arm: the cape hangs off the
        # shoulders' back edge and trails further the harder the pose moves.
        back = CAPE_BACK + CAPE_LEAN_BACK * max(0.0, pose.lean)
        cape_root = _add(_add(shoulder, up, CAPE_DROP), forward, -back)
        angle = -min(CAPE_MAX_ANGLE,
                     max(CAPE_ANGLE, CAPE_ANGLE + CAPE_LEAN_SWING * pose.lean
                         + CAPE_LIFT_SWING * pose.lift))
        _flare(px, cape_root, _limb_dir(angle), CAPE_LEN, CAPE_TOP_W,
               CAPE_HEM_W, colours["cape"], "cape")

    far_skin = _shade(skin, FAR_SHADE)
    far_forearm = far_skin if dressed else None
    near_forearm = skin if dressed else None
    _arm(px, shoulder, pose.far_upper, pose.far_fore,
         _shade(body, FAR_SHADE), far_skin, "far_arm", far_forearm)
    _leg(px, hip, pose.far_thigh, pose.far_shin,
         _shade(leg, FAR_SHADE), _shade(shoe, FAR_SHADE), "far_leg",
         shaft=not heeled, heeled=heeled)

    def torso_colour(along: float, perp: float) -> RGB:
        if scarf is not None and along >= TORSO_H - SCARF_ROWS:
            return scarf
        if along < 1.0:
            return belt
        return body
    _segment(px, hip, up, TORSO_H, TORSO_W, torso_colour, "torso")
    if scarf is not None:
        # Scarf tail: from the back of the scarf, trailing behind and down;
        # the faster the lean, the flatter it flies.
        tail_root = _add(_add(hip, up, TORSO_H - SCARF_ROWS / 2.0),
                         forward, -(TORSO_W / 2.0 - 0.5))
        tail_angle = -min(100.0, max(55.0, 55.0 + 3.0 * pose.lean))
        _segment(px, tail_root, _limb_dir(tail_angle), SCARF_TAIL,
                 SCARF_TAIL_W, lambda al, pe: scarf, "torso")

    if dressed:
        # The A-line skirt hangs from the waist under gravity -- NOT along the
        # torso's axis, which is why it is cut from the same `_flare` as the
        # cape rather than from `_segment` -- and swings toward the LEADING
        # thigh.
        swing = SKIRT_SWING * math.sin(math.radians(max(pose.near_thigh,
                                                        pose.far_thigh)))
        fall = math.hypot(swing, SKIRT_LEN)
        _flare(px, (hip[0], 0.0), (swing / fall, SKIRT_LEN / fall), fall,
               SKIRT_TOP_W, SKIRT_HEM_W, colours["dress"], "skirt")

    # Head: axis-aligned 8x8, bottom on the neck row, half a column forward.
    top = round(neck[1]) - HEAD
    left = math.floor(neck[0]) - (HEAD // 2 - 1)
    for r in range(HEAD):
        for c in range(HEAD):
            corner = (r in (0, HEAD - 1)) and (c in (0, HEAD - 1))
            if corner:
                continue
            if r < HAIR_ROWS or (r < HEAD - 2 and c < BACK_HAIR) or (
                    r == HEAD - 2 and c == 0):
                rgb = hair
            elif r == EYE_ROW and c == EYE_COL:
                rgb = OUTLINE_RGB
            else:
                rgb = skin
            px[(left + c, top + r)] = (rgb, "head")

    if garments.hat == "wizard":
        _hat(px, left, top, colours["hat"])

    _leg(px, hip, pose.near_thigh, pose.near_shin, leg, shoe, "near_leg",
         shaft=not heeled, heeled=heeled)
    _arm(px, shoulder, pose.near_upper, pose.near_fore, body, skin,
         "near_arm", near_forearm)

    # Inner lines: darken every other part's pixel 4-adjacent to a near limb.
    darken: dict[tuple[int, int], RGB] = {}
    for (x, y), (rgb, tag) in px.items():
        if tag not in ("near_leg", "near_arm"):
            continue
        for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            other = px.get(q)
            if other is None or other[1] == tag:
                continue
            if tag == "near_leg" and other[1] == "near_arm":
                continue
            darken[q] = _shade(other[0], INNER_SHADE)
    # The same rule, and the same direction -- THE PART BEHIND IS DARKENED --
    # applied to the cape, which is drawn first and therefore lies behind
    # every other part. Without it the cape's hem ends INSIDE the skirt with
    # no boundary at all (MEASURED on wizard_girl: the cape's lowest row 2-4
    # against the skirt's 6-8 in all 16 frames), so purple and red share one
    # flare and read as a two-tone skirt rather than a cape hanging behind.
    # Only against ANOTHER PART: the cape's edge on the background already
    # carries the outline, and darkening that too would eat a 1 px sliver
    # whole.
    for (x, y), (rgb, tag) in px.items():
        if tag != "cape":
            continue
        for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            other = px.get(q)
            if other is not None and other[1] != "cape":
                darken[(x, y)] = _shade(rgb, INNER_SHADE)
                break
    for q, rgb in darken.items():
        px[q] = (rgb, px[q][1])
    return px


def _outlined(px: _Pixels) -> tuple[Image.Image, int, int]:
    """(RGBA image of the outlined figure, local x, local y of its (0, 0))."""
    xs = [x for x, _ in px]
    ys = [y for _, y in px]
    ox, oy = min(xs) - 1, min(ys) - 1
    w, h = max(xs) - ox + 2, max(ys) - oy + 2
    fig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for (x, y), (rgb, _) in px.items():
        fig.putpixel((x - ox, y - oy), rgb + (255,))
    ring = fig.getchannel("A").filter(ImageFilter.MaxFilter(3))
    outline = Image.new("RGBA", (w, h), OUTLINE_RGB + (0,))
    outline.putalpha(ring)
    return Image.alpha_composite(outline, fig), ox, oy


def _colours(identity_colours: Mapping[str, RGB],
             garments: Garments = DEFAULT_GARMENTS) -> dict[str, RGB]:
    """The colours `garments` are drawn in: exactly `garment_parts(garments)`.

    KeyError naming a part the garments draw and the mapping does not hold;
    ValueError for a colour that is not three ints 0..255, and for a part the
    mapping holds that these garments never draw -- a `pants` colour on a
    figure wearing a dress is a colour nobody would ever see, which is the
    same mistake `characters.parts_problem` refuses in a file.
    """
    wanted = garment_parts(garments)
    out: dict[str, RGB] = {}
    for part in wanted:
        if part not in identity_colours:
            raise KeyError(f"identity colours have no part {part!r}; these "
                           f"garments ({garments_text(garments)}) draw "
                           f"{wanted}")
        rgb = identity_colours[part]
        if (not isinstance(rgb, (tuple, list)) or len(rgb) != 3
                or not all(_is_int(c) and 0 <= c <= 255 for c in rgb)):
            raise ValueError(f"identity colour {part!r} must be three ints "
                             f"0..255, got {rgb!r}")
        out[part] = (rgb[0], rgb[1], rgb[2])
    unused = sorted(set(identity_colours) - set(wanted))
    if unused:
        raise ValueError(f"identity colours carry {unused}, which these "
                         f"garments ({garments_text(garments)}) do not draw; "
                         f"they draw {wanted}")
    return out


def _placed(layout: Layout, index: int, pose: Pose,
            colours: Mapping[str, RGB],
            garments: Garments = DEFAULT_GARMENTS
            ) -> tuple[Image.Image, int, int]:
    """(outlined figure, source x, source y of its top-left) for one cell."""
    if not isinstance(pose, Pose):
        raise TypeError(f"frame {index}: expected a Pose, got "
                        f"{type(pose).__name__}")
    cell = layout.cells[index]
    fig, ox, oy = _outlined(_figure(pose, colours, garments))
    bbox = fig.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"frame {index}: the figure drew nothing")
    lowest_local = oy + bbox[3] - 1
    dx = cell.hip_x_src
    dy = (cell.baseline_src - pose.lift) - lowest_local
    x0, y0 = ox + dx, oy + dy
    fx0, fy0, fx1, fy1 = (x0 + bbox[0], y0 + bbox[1],
                          x0 + bbox[2], y0 + bbox[3])
    sx0, sy0, sx1, sy1 = layout.rect_src(index)
    if fx0 < sx0 or fy0 < sy0 or fx1 > sx1 or fy1 > sy1:
        raise ValueError(
            f"layout {layout.name}: frame {index} draws source px "
            f"[{fx0}, {fx1}) x [{fy0}, {fy1}), outside its cell "
            f"[{sx0}, {sx1}) x [{sy0}, {sy1}); pose {pose}")
    return fig, x0, y0


def render_init(layout: Layout, poses: Sequence[Pose],
                identity_colours: Mapping[str, tuple[int, int, int]],
                garments: Garments = DEFAULT_GARMENTS
                ) -> tuple[bytes, tuple[tuple[float, float], ...]]:
    """Draw the mannequin strip; return (RGB PNG bytes, snapped centers).

    `poses` has one Pose per layout cell (ValueError otherwise).
    `identity_colours` must hold exactly the parts `garments` draw
    (`model.garment_parts`; model.IDENTITY_PARTS for the default outfit) --
    KeyError naming a missing part, ValueError naming one the garments do
    not draw, so a colour map and a set of garments that disagree is refused
    instead of half-drawn. Centers are ((x, y), ...) in cell order, each
    coordinate a model.GRID value. See the module docstring for the drawing
    rules and the invariants this raises on -- a garment that pushes a
    figure out of its cell raises there, like any other pixel.
    """
    poses = tuple(poses)
    if len(poses) != layout.count:
        raise ValueError(f"layout {layout.name} has {layout.count} cells, "
                         f"got {len(poses)} poses")
    colours = _colours(identity_colours, garments)
    src = Image.new("RGBA", (layout.src_w, layout.src_h),
                    BACKGROUND_RGB + (255,))
    centers: list[tuple[float, float]] = []
    for i, pose in enumerate(poses):
        fig, x0, y0 = _placed(layout, i, pose, colours, garments)
        src.alpha_composite(fig, dest=(x0, y0))
        bx0, by0, bx1, by1 = fig.getchannel("A").getbbox()
        cx = (x0 + bx0 + x0 + bx1) * layout.k / 2.0
        cy = (y0 + by0 + y0 + by1) * layout.k / 2.0
        center = (snap(cx / layout.width), snap(cy / layout.height))
        # Collision first: a shared center can never lie inside two
        # non-overlapping cells, so checked second it could never fire.
        for j, other in enumerate(centers):
            if other == center:
                raise ValueError(
                    f"layout {layout.name}: frames {j} and {i} both snap to "
                    f"{center}")
        rx0, ry0, rx1, ry1 = layout.cells[i].rect_canvas
        px_x, px_y = center[0] * layout.width, center[1] * layout.height
        if not (rx0 <= px_x < rx1 and ry0 <= px_y < ry1):
            raise ValueError(
                f"layout {layout.name}: frame {i}'s figure center "
                f"({cx:.0f}, {cy:.0f}) snaps to {center}, which is canvas "
                f"({px_x:.1f}, {px_y:.1f}), outside its cell "
                f"{layout.cells[i].rect_canvas}")
        centers.append(center)
    rgb = src.convert("RGB").resize((layout.width, layout.height),
                                    Image.Resampling.NEAREST)
    buf = io.BytesIO()
    rgb.save(buf, format="PNG")
    return buf.getvalue(), tuple(centers)


def params_doc(layout: Layout, poses: Sequence[Pose],
               identity_colours: Mapping[str, tuple[int, int, int]],
               garments: Garments = DEFAULT_GARMENTS) -> dict:
    """The document `params_sha256` hashes -- what a mannequin name MEANS.

    {"layout": layout.as_row(), "poses": [p.as_row() ...], "colours": {part:
    [r, g, b]}, "skeleton": the module's skeleton constants by name}, plus
    "garments" for a non-default outfit. Angles are written as floats and
    lift as an int, so Pose(25, ...) and Pose(25.0, ...) -- the same drawing
    -- share a name; colours are the parts `garments` draw, the parts
    render_init reads.

    Split out of `params_sha256` so a check can assert WHAT IS NAMED rather
    than only that two hashes differ: a hash tells nobody that a garment
    constant left the document (CLAUDE.md law 5 -- an assertion that cannot
    fail). The constants are read out of `globals()` at call time, so
    patching one in this module moves the name, which is the other half.
    """
    colours = _colours(identity_colours, garments)
    rows = []
    for p in poses:
        row = p.as_row()
        rows.append({key: (int(v) if key == "lift" else float(v))
                     for key, v in row.items()})
    g = globals()
    names = _SKELETON_NAMES
    if garments != DEFAULT_GARMENTS:
        names += _GARMENT_SKELETON_NAMES
    skeleton = {name: (list(g[name]) if isinstance(g[name], tuple)
                       else g[name]) for name in names}
    doc = {"layout": layout.as_row(), "poses": rows,
           "colours": {part: list(rgb) for part, rgb in colours.items()},
           "skeleton": skeleton}
    if garments != DEFAULT_GARMENTS:
        doc["garments"] = dict(garments._asdict())
    return doc


def params_sha256(layout: Layout, poses: Sequence[Pose],
                  identity_colours: Mapping[str, tuple[int, int, int]],
                  garments: Garments = DEFAULT_GARMENTS) -> str:
    """Hex sha256 naming a render_init input, for the ledger.

    Canonical JSON (sort_keys, compact separators) of `params_doc`. Changes
    when any angle, colour, cell or skeleton constant changes.

    A NON-DEFAULT outfit adds "garments" to the document and the
    `_GARMENT_SKELETON_NAMES` constants to "skeleton". A figure in
    model.DEFAULT_GARMENTS is hashed over exactly what it always was, so the
    shipped scout's name does not move when a hat constant does -- and no
    hat was drawn to be named.
    """
    text = json.dumps(params_doc(layout, poses, identity_colours, garments),
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()
