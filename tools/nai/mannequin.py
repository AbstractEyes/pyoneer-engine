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
* DETERMINISTIC. The same (layout, poses, colours, garments, build) gives
  byte-identical PNG bytes and identical centers; `params_sha256` names
  that input, and `DRAW_VERSION` is part of it so a change to the drawing
  code renames it. A DEFAULT outfit on the DEFAULT build is named over
  exactly what it always was, so the shipped scout's pinned bytes and
  pinned name cannot move when a garment or a build constant does.
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

BUILD (author, 2026-09-17), model.Build, and what it may NOT move
-----------------------------------------------------------------
A build redistributes those rows and never adds one. `_bones` adds the
build's px to THIGH and SHIN and takes exactly their sum off TORSO_H, so
9/9/12 becomes 7/8/15 (`original`) or 11/10/9 (`long`) and the sum is
always 30. THE CONSEQUENCE IS THE POINT: total height, the lowest drawn row
(the ground line `_placed` aligns on), the top of the head above it and the
SHOULDER above it are identical on every build, so the arms hang where they
hung, a cape ends where it ended, no snapped centre moves and no build can
push a figure out of its cell. What moves is the HIP -- and with it the
belt, which is drawn on the torso's bottom row, an A-line skirt, which
hangs from the waist, and the trenchcoat's skirt, which is the reason the
axis exists. A garment's length is a CUT in source px and does not stretch
with the wearer, so raising the hip under a coat of unchanged length hands
the difference to the leg: 10-11 px of visible leg on `long` against 4-5 on
`original`, from one COAT_LEN.

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
boot shaft and the boot-coloured ankle off the shin; a BRIM hat is a flat
one-row brim BRIM_W across on head row BRIM_ROW, its axis BRIM_FWD px
FORWARD of the head's so it overhangs the face further than the back, under
a LOW crown of CROWN_H rows that never narrows past CROWN_TAPER -- the
opposite silhouette to the wizard cone, from the same 8 px head; a COAT is
a collar, a bodice set COAT_BODICE_BACK px behind the torso so a strip of
the shirt shows down the open front, and a `_flare` skirt COAT_LEN px from
the HIP carried COAT_SWING toward the leading thigh, drawn AFTER the near
leg so it covers the thigh, and taking both sleeves with it; a MASK is
MASK_ROWS head rows from MASK_TOP_ROW, the full width of the head, starting
on the row under the eye. A dress also ends both
sleeves at the elbow (`_arm`'s `forearm`), so the arms read against it, with
WRIST_PX of OUTLINE_RGB between that bare forearm and its hand -- a forearm
and a hand in one skin value is a blunt plank, not an arm.

Draw order: cape, far arm, far leg, torso, skirt, head (the mask is part of
it), hat or brim, near leg, COAT, near arm. The coat sits between the near
leg and the near arm on purpose: before the leg it would be covered by the
thigh it exists to cover, and after the arm it would swallow the hand. Far limbs use
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

Placement: the hip column STARTS at cell.hip_x_src and is then shifted by
the least that brings the drawn box inside the cell, and only when it is
outside -- see `_placed`, where the reason is measured. The row is whatever
puts the LOWEST OPAQUE ROW OF THE OUTLINED FIGURE on
cell.baseline_src - pose.lift -- which, for every shipped pose, is the
outline under a boot. That is the row post-processing P7 aligns on, so a
faithful generation needs no shift. Hip height therefore follows from the
joint angles, and walk bob comes out of the geometry for free.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from types import MappingProxyType
from typing import Mapping, Sequence

from PIL import Image, ImageFilter

from tools.nai import model as _model
from tools.nai.model import (BACKGROUND_RGB, DEFAULT_BUILD, DEFAULT_GARMENTS,
                             DIM_MULTIPLE, FAR_SHADE, GARMENT_SLOTS, H_SRC,
                             INIT_K, INNER_SHADE, MASK_ALIGN, MAX_AREA,
                             MIN_DIM, OUTLINE_RGB, PARTS, CellSpec, Garments,
                             Layout, Pose, build, garment_parts,
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
"""The A-line skirt: SKIRT_LEN rows from the waist (the hip row),
widening from the torso's width to SKIRT_HEM_W, its hem carried SKIRT_SWING
px toward the LEADING thigh.

WHERE THAT HEM FALLS RELATIVE TO THE KNEE IS A PROPERTY OF THE BUILD, NOT
OF THIS CONSTANT. A length is a CUT in source px from the waist and a cut
does not stretch with the wearer, so against a THIGH a build moves (7 on
`original`, 9 on `standard`, 11 on `long`) the same seven rows sit at the
knee, just above it, and well above it in turn. The same caution binds
BOOT_ROWS and HEEL_DROP: no constant here may spell a bone length as a
number now that a build moves two of the three."""

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

BRIM_W = 15
BRIM_ROW = 1
BRIM_FWD = 0.5
"""The GUNSLINGER brim: one flat row BRIM_W across, on head row BRIM_ROW,
its axis BRIM_FWD px FORWARD of the head's centre -- the opposite sign to
HAT_BRIM_BACK, and forward on purpose. The wizard brim overhangs 2 px at the
back and 1 at the face; this one overhangs 2 at the back and 3 at the face,
because the shape a gunslinger is recognised by at thumbnail size is the
shadow the brim throws over the eyes. MEASURED against the cells at 13,
15 and 17: 15 is the WIDEST THAT FITS. It overhangs
the 8 px head by 3 at the back and 4 at the face, and ON THE IDLE FRAME IT
IS THE WIDEST ROW OF THE WHOLE FIGURE: 17 px with its outline, against the
14 px coat hem, 1.21 to 1. THE BRIM IS NOT NARROW, AND THE NEXT TUNER MUST
NOT SPEND THE CELL TRYING TO WIDEN IT. Measured on the author's own
reference for the same ratio: a 30 px brim over a 25 px body, 1.20 to 1;
and relative to the head this brim overhangs MORE than his does (3 back
and 4 front on an 8 px head, against 6 and 7 on a 17 px head). What the
brim lacked was never width but DEPTH, which costs no cell width at all --
see BRIM_DROOP_ROWS."""
BRIM_DROOP_ROWS = 1
"""Rows below the brim row that the OVERHANG droops into -- every brim
column outside the head's own HEAD columns, and none of the columns resting
on the crown, which is what a felt brim does and where it does it.

WHY IT EXISTS: one hat-coloured row between two outline rows reads as a
plank at 1x and can be swallowed by its own outline. The author's reference
spends NINE source rows (y=10..18 of a 45 px figure) on a sculpted drooping
disc. This buys some of that mass back at ZERO extra width, which is the
dimension a 30 px cell actually forbids -- BRIM_W is already the widest row
on the figure."""

CROWN_H = 3
CROWN_W = 7
CROWN_TAPER = 2
"""The LOW crown: CROWN_H rows above the brim row, CROWN_W wide, its top row
CROWN_TAPER px narrower. It is EXPLICITLY NOT A CONE -- HAT_CONE_H is 6 rows
and narrows to HAT_TIP_W 2, and the whole difference between a wizard and a
gunslinger at 40 px is that one silhouette goes up and the other goes out."""

COAT_LEN = 13
"""Source px the coat's skirt falls BELOW THE HIP, and the one number the
whole design turns on. It hangs off the HIP, not the shoulder, so a build
that raises the hip raises the hem with it and hands the difference to the
leg: at `standard` the sole is 20 px below the hip and 7 px of leg show, at
`long` 23 and 10, at `original` 17 and 4. MEASURED on the author's own
reference: 3 px of a 45 px figure, which is the barrel this exists to undo.
Shoulder to hem is 23.5 px of a 40 px figure at `standard` and 20.5 at
`long` -- over half the body either way, so it is still a coat and not a
tunic."""
COAT_WAIST_W = 8
COAT_HEM_W = 12
COAT_SWING = 2.5
"""The coat's skirt, cut from the same `_flare` as the cape and the A-line
skirt: COAT_WAIST_W at the hip to COAT_HEM_W at the hem, its hem carried
COAT_SWING px toward the LEADING thigh, so the hem swings with the stride
instead of hanging like a board."""
COAT_BODICE_W = 7
COAT_BODICE_BACK = 1.5
"""The coat's body over the torso: COAT_BODICE_W wide (the torso is
TORSO_W 6, so the coat is bulkier than the man), its axis COAT_BODICE_BACK
px BEHIND the torso's. That offset is what makes the coat read as OPEN: the
torso's front column stays uncovered, so a strip of the shirt under it runs
down the chest and the belt's buckle shows at the bottom of it, and `tunic`
is a colour somebody can see rather than paint nobody looks at. MEASURED:
at 1.0 the bodice still covered the torso's last column edge to edge and
the shirt drew ZERO pixels in every frame of every strip -- the offset has
to exceed (COAT_BODICE_W - TORSO_W) / 2 or the coat is simply closed."""
COAT_COLLAR_ROWS = 2
COAT_COLLAR_W = 10
"""The collar: COAT_COLLAR_ROWS rows at the top of the torso, COAT_COLLAR_W
across -- wider than the bodice and than the head, so the coat flares at the
shoulders the way a turned-up trench collar does."""
COAT_COLLAR_IS_MASK = True
"""A MASKED man's collar is drawn in the MASK's colour, not the coat's.

MEASURED on the author's own reference, side pose, row by row: there the
mask and the turned-up collar are ONE value (#0D0401 / #010000), so the
dark runs unbroken from under the single blue eye, across the jaw, and out
over both shoulders. That one mass is the character's signature after the
hat. Drawn in the coat's own brown instead, the dark stops at the chin and
the mask is a band floating on a face -- and on an 8 px head, a band under
a fringe reads as a BEARD, which is the opposite of a covered mouth.

An UNMASKED coat keeps the coat's own colour, so this adds no colour part
and changes no character file. It is a CONSTANT rather than a
GARMENT_DRAW_VERSION bump on purpose: see that constant."""

MASK_TOP_ROW = EYE_ROW + 1
MASK_ROWS = 3
"""The face mask: head rows MASK_TOP_ROW to MASK_TOP_ROW + MASK_ROWS, the
whole width of the head. It starts on the row UNDER the eye
(EYE_ROW + 1), so the eye is the one thing left of the face -- take a row
off the top and it covers the eye, add one and the mouth shows."""

GARMENT_DRAW_VERSION = 1
"""Bump when the GARMENT drawing code changes in a way no constant above
names. It is hashed only for a figure that wears one (see `params_sha256`)."""

_PART_SKELETON_NAMES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "hat": ("HAT_BRIM_W", "HAT_BRIM_ROW", "HAT_BRIM_BACK", "HAT_CONE_H",
            "HAT_CONE_W", "HAT_TIP_W", "HAT_LEAN", "HAT_BEND",
            "HAT_BEND_ROWS"),
    "cape": ("CAPE_LEN", "CAPE_TOP_W", "CAPE_HEM_W", "CAPE_DROP", "CAPE_BACK",
             "CAPE_LEAN_BACK", "CAPE_ANGLE", "CAPE_LEAN_SWING",
             "CAPE_LIFT_SWING", "CAPE_MAX_ANGLE"),
    "dress": ("SKIRT_LEN", "SKIRT_TOP_W", "SKIRT_HEM_W", "SKIRT_SWING",
              "WRIST_PX"),
    "heels": ("HEEL_SOLE_H", "HEEL_SOLE_W", "HEEL_DROP", "HEEL_POST_W",
              "HEEL_TOE_W"),
    "brim": ("BRIM_W", "BRIM_ROW", "BRIM_FWD", "BRIM_DROOP_ROWS", "CROWN_H",
             "CROWN_W", "CROWN_TAPER"),
    "coat": ("COAT_LEN", "COAT_WAIST_W", "COAT_HEM_W", "COAT_SWING",
             "COAT_BODICE_W", "COAT_BODICE_BACK", "COAT_COLLAR_ROWS",
             "COAT_COLLAR_W", "COAT_COLLAR_IS_MASK"),
    "mask": ("MASK_TOP_ROW", "MASK_ROWS"),
})
"""THE CONSTANTS EACH DRAWN PART IS MADE OF, keyed by `model.PARTS` name --
the same table `model.GarmentSlot.drawn` is, one level down.

`params_sha256` unions the entries for the parts a figure ACTUALLY DRAWS, so
appending a garment cannot rename a character who does not wear it. It did
once: the trenchcoat put the whole block into wizard_girl's document and
moved all three of her mannequin names, two of which `data/nai/ledger.jsonl`
had already paid for, for a figure whose drawn bytes did not change by one
pixel. A part with no shape constants of its own (`scarf`, `pants`, ...) is
drawn from `_SKELETON_NAMES` and is absent here."""

_GARMENT_SKELETON_NAMES: tuple[str, ...] = tuple(sorted(
    {name for names in _PART_SKELETON_NAMES.values() for name in names}
)) + ("GARMENT_DRAW_VERSION",)
"""Every garment constant, as an inventory -- the union of the table above
plus the version every garment-wearer hashes. Nothing reads it to build a
document; the guard below reads it so a constant that is added to one and
not the other cannot pass."""

_unfiled = sorted(
    {name for name in globals()
     if not hasattr(_model, name)                # MASK_ALIGN is the latent
     and (name.split("_")[0] in ("HAT", "CAPE", "SKIRT", "HEEL", "BRIM",
                                 "CROWN", "COAT", "MASK")
          or name == "WRIST_PX")}
    - set(_GARMENT_SKELETON_NAMES))
if _unfiled:
    raise RuntimeError(
        f"mannequin: garment constants {_unfiled} are filed under no part in "
        f"_PART_SKELETON_NAMES, so a figure that wears that garment would be "
        f"named over a constant its drawing reads")
_unknown_named = sorted(set(_PART_SKELETON_NAMES) - set(PARTS))
if _unknown_named:
    raise RuntimeError(f"mannequin: _PART_SKELETON_NAMES files constants "
                       f"under {_unknown_named}, which model.PARTS does not "
                       f"list")

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
         heeled: bool = False, thigh_px: float = THIGH,
         shin_px: float = SHIN) -> None:
    """One leg in `leg`, its footwear in `shoe`.

    `shaft` draws the boot's BOOT_ROWS shaft up the shin and its ankle;
    `heeled` swaps the boot's block for `_in_heel`'s sole, post and toe.
    `thigh_px` and `shin_px` are the BONE LENGTHS, THIGH and SHIN plus the
    build's (model.Build); they default to the shipped bones, so every call
    that does not name a build draws what it always drew.
    """
    ut = _limb_dir(thigh)
    us = _limb_dir(shin)
    knee = _add(hip, ut, thigh_px)
    ankle = _add(knee, us, shin_px)
    _segment(px, hip, ut, thigh_px, LEG_W, lambda al, pe: leg, tag)
    _disc(px, knee, LEG_W / 2.0, leg, tag)
    _segment(px, knee, us, shin_px, LEG_W,
             lambda al, pe: shoe if shaft and al >= shin_px - BOOT_ROWS
             else leg, tag)
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


def _brim_hat(px: _Pixels, left: int, top: int, rgb: RGB) -> None:
    """The gunslinger hat on an 8x8 head whose top-left is (`left`, `top`).

    A BROAD BRIM, one row BRIM_W across whose OVERHANG then droops
    BRIM_DROOP_ROWS further, overhanging the head at the back AND further at
    the face; over it a LOW CROWN of CROWN_H rows, CROWN_W wide, its top row
    CROWN_TAPER narrower. Nothing tapers to a point and nothing leans: that
    is the whole distinction from `_hat`, and it is the distinction a 13 px
    silhouette has to carry.
    """
    center = left + HEAD / 2.0
    brim_axis = center + BRIM_FWD
    brim = top + BRIM_ROW
    for c in range(math.floor(brim_axis - BRIM_W / 2.0) - 1,
                   math.ceil(brim_axis + BRIM_W / 2.0) + 1):
        if -BRIM_W / 2.0 <= c + 0.5 - brim_axis < BRIM_W / 2.0:
            px[(c, brim)] = (rgb, "brim")
            # THE DROOP, and only over the OVERHANG: a column resting on the
            # crown cannot fall and a column past the head can. That rule
            # needs no second width -- it is BRIM_W minus HEAD -- which is
            # why this depth costs the cell nothing.
            if not left <= c < left + HEAD:
                for d in range(BRIM_DROOP_ROWS):
                    px[(c, brim + 1 + d)] = (rgb, "brim")
    for i in range(CROWN_H):
        width = CROWN_W - (CROWN_TAPER if i == CROWN_H - 1 else 0)
        row = brim - 1 - i
        for c in range(math.floor(center - width / 2.0) - 1,
                       math.ceil(center + width / 2.0) + 1):
            if -width / 2.0 <= c + 0.5 - center < width / 2.0:
                px[(c, row)] = (rgb, "brim")


def _coat(px: _Pixels, hip: tuple[float, float], up: tuple[float, float],
          forward: tuple[float, float], torso_h: float, pose: Pose,
          rgb: RGB, collar_rgb: RGB) -> None:
    """The trenchcoat: a collar, a bodice over the torso, a flared skirt.

    `collar_rgb` is the MASK's colour on a masked man and the coat's own on
    anyone else (COAT_COLLAR_IS_MASK), so a masked man's dark is ONE mass
    from under the eye out across both shoulders instead of a band that
    stops at the chin.

    Drawn AFTER the near leg, so the coat lies over the thigh it is supposed
    to cover and the leg shows only below the hem -- and then the inner-line
    pass draws the boundary between them, because a coat and a trouser leg
    that touch with no line are one dark mass.

    The bodice rides the SHOULDER (it is TORSO_H long) and the skirt rides
    the HIP (it is COAT_LEN long). That split is the build axis's whole
    mechanism: raise the hip and the hem comes up with it while the collar
    stays where the collarbone is.
    """
    back = _add(hip, forward, -COAT_BODICE_BACK)
    _segment(px, back, up, torso_h, COAT_BODICE_W, lambda al, pe: rgb, "coat")
    collar = _add(back, up, torso_h - COAT_COLLAR_ROWS)
    _segment(px, collar, up, COAT_COLLAR_ROWS, COAT_COLLAR_W,
             lambda al, pe: collar_rgb, "coat")
    swing = COAT_SWING * math.sin(math.radians(max(pose.near_thigh,
                                                   pose.far_thigh)))
    fall = math.hypot(swing, COAT_LEN)
    _flare(px, (back[0], hip[1]), (swing / fall, COAT_LEN / fall), fall,
           COAT_WAIST_W, COAT_HEM_W, rgb, "coat")


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


def _bones(build_name: str = DEFAULT_BUILD) -> tuple[float, float, float]:
    """(thigh, shin, torso) in source px for `build_name`.

    THE SUM IS INVARIANT. `model.Build` takes off the torso exactly what it
    adds to the legs, so thigh + shin + torso is TORSO_H + THIGH + SHIN for
    every build and the figure's total height -- and therefore its ground
    line, its cell and its snapped centre -- cannot move. What moves is the
    hip, which is the only thing this axis exists to move.
    """
    chosen = build(build_name)
    return (THIGH + chosen.thigh, SHIN + chosen.shin,
            TORSO_H + chosen.torso)


def _figure(pose: Pose, colours: Mapping[str, RGB],
            garments: Garments = DEFAULT_GARMENTS,
            build_name: str = DEFAULT_BUILD) -> _Pixels:
    """The un-outlined figure in local coordinates: the hip column is x 0 and
    the hip sits on the boundary above row 0 (legs start at row 0, the torso
    ends at row -1).

    `colours` holds exactly `model.garment_parts(garments)`; what each
    garment draws is in the module docstring's GARMENTS section.
    `build_name` is one of model.BUILD_NAMES and moves the hip only
    (`_bones`); ValueError for an unknown one.
    """
    px: _Pixels = {}
    thigh_px, shin_px, torso_h = _bones(build_name)
    hip = (0.5, 0.0)
    lean = math.radians(pose.lean)
    up = (math.sin(lean), -math.cos(lean))
    forward = (math.cos(lean), math.sin(lean))
    shoulder = _add(hip, up, torso_h - SHOULDER_DROP)
    neck = _add(hip, up, torso_h)

    skin, hair, belt = colours["skin"], colours["hair"], colours["belt"]
    dressed = garments.legwear == "dress"
    heeled = garments.footwear == "heels"
    coated = garments.coat
    # The body colour clothes the torso AND the sleeves: a dress has no
    # separate tunic, so one name carries both. A COAT takes the sleeves off
    # both of them -- a trenchcoat has its own -- and leaves the torso's
    # front column showing under its open bodice, which is where the shirt
    # is seen.
    body = colours["dress"] if dressed else colours["tunic"]
    sleeve_body = colours["coat"] if coated else body
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
         _shade(sleeve_body, FAR_SHADE), far_skin, "far_arm", far_forearm)
    _leg(px, hip, pose.far_thigh, pose.far_shin,
         _shade(leg, FAR_SHADE), _shade(shoe, FAR_SHADE), "far_leg",
         shaft=not heeled, heeled=heeled, thigh_px=thigh_px, shin_px=shin_px)

    def torso_colour(along: float, perp: float) -> RGB:
        if scarf is not None and along >= torso_h - SCARF_ROWS:
            return scarf
        if along < 1.0:
            return belt
        return body
    _segment(px, hip, up, torso_h, TORSO_W, torso_colour, "torso")
    if scarf is not None:
        # Scarf tail: from the back of the scarf, trailing behind and down;
        # the faster the lean, the flatter it flies.
        tail_root = _add(_add(hip, up, torso_h - SCARF_ROWS / 2.0),
                         forward, -(TORSO_W / 2.0 - 0.5))
        tail_angle = -min(100.0, max(55.0, 55.0 + 3.0 * pose.lean))
        _segment(px, tail_root, _limb_dir(tail_angle), SCARF_TAIL,
                 SCARF_TAIL_W, lambda al, pe: scarf, "torso")

    if dressed:
        # The A-line skirt hangs from the waist under gravity -- NOT along the
        # torso's axis, which is why it is cut from the same `_flare` as the
        # cape rather than from `_segment` -- and swings toward the LEADING
        # thigh.
        # SKIRT_LEN is a CUT, in source px from the waist, and a cut does
        # not stretch with the wearer: a long-built girl in the same skirt
        # wears it higher up a longer thigh, which is the axis working.
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
            masked = (garments.face == "mask"
                      and MASK_TOP_ROW <= r < MASK_TOP_ROW + MASK_ROWS)
            if masked:
                rgb = colours["mask"]
            elif r < HAIR_ROWS or (r < HEAD - 2 and c < BACK_HAIR) or (
                    r == HEAD - 2 and c == 0):
                rgb = hair
            elif r == EYE_ROW and c == EYE_COL:
                rgb = OUTLINE_RGB
            else:
                rgb = skin
            px[(left + c, top + r)] = (rgb, "mask" if masked else "head")

    if garments.hat == "wizard":
        _hat(px, left, top, colours["hat"])
    elif garments.hat == "brim":
        _brim_hat(px, left, top, colours["brim"])

    _leg(px, hip, pose.near_thigh, pose.near_shin, leg, shoe, "near_leg",
         shaft=not heeled, heeled=heeled, thigh_px=thigh_px, shin_px=shin_px)
    if coated:
        # The collar carries the MASK across the shoulders when there is one
        # to carry (COAT_COLLAR_IS_MASK); an unmasked coat keeps its own
        # colour, so nothing any other outfit drew moves.
        collar_rgb = (colours["mask"]
                      if COAT_COLLAR_IS_MASK and garments.face == "mask"
                      else colours["coat"])
        _coat(px, hip, up, forward, torso_h, pose, colours["coat"],
              collar_rgb)
    _arm(px, shoulder, pose.near_upper, pose.near_fore, sleeve_body, skin,
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
            garments: Garments = DEFAULT_GARMENTS,
            build_name: str = DEFAULT_BUILD
            ) -> tuple[Image.Image, int, int]:
    """(outlined figure, source x, source y of its top-left) for one cell."""
    if not isinstance(pose, Pose):
        raise TypeError(f"frame {index}: expected a Pose, got "
                        f"{type(pose).__name__}")
    cell = layout.cells[index]
    fig, ox, oy = _outlined(_figure(pose, colours, garments, build_name))
    bbox = fig.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"frame {index}: the figure drew nothing")
    lowest_local = oy + bbox[3] - 1
    sx0, sy0, sx1, sy1 = layout.rect_src(index)
    dx = cell.hip_x_src
    # THE HIP IS WHERE THE FIGURE IS ANCHORED, NOT WHERE IT IS PINNED. The
    # hip column puts an UPRIGHT figure in the middle of its cell, but a
    # leaning one reaches forward off it: the torso rises along
    # (sin lean, -cos lean), so at jump frame 0's lean of 35 degrees a
    # 15 px torso carries the head 8.6 px forward of the hip and the brim
    # 8 px forward of that, while nine columns of the cell go unused
    # BEHIND him. MEASURED: garet on `standard` and on `original`, and the
    # DEFAULT outfit on `original`, each overran the right edge of a jump
    # cell by 1-4 px with that margin sitting idle on the left.
    # So the hip is a starting point and this is the rule that finishes it:
    # shift by the LEAST that brings the drawn box inside the cell, and
    # only when it is outside. A figure that already fits is not moved by
    # one pixel -- which is why every strip that drew before this existed
    # draws the same bytes, the shipped scout's pinned init included -- and
    # a figure WIDER than its cell still raises below, because that is a
    # pose or a layout nothing can place (law 7).
    if bbox[2] - bbox[0] <= sx1 - sx0:
        left, right = ox + dx + bbox[0], ox + dx + bbox[2]
        dx += max(0, sx0 - left) - max(0, right - sx1)
    dy = (cell.baseline_src - pose.lift) - lowest_local
    x0, y0 = ox + dx, oy + dy
    fx0, fy0, fx1, fy1 = (x0 + bbox[0], y0 + bbox[1],
                          x0 + bbox[2], y0 + bbox[3])
    if fx0 < sx0 or fy0 < sy0 or fx1 > sx1 or fy1 > sy1:
        raise ValueError(
            f"layout {layout.name}: frame {index} draws source px "
            f"[{fx0}, {fx1}) x [{fy0}, {fy1}), outside its cell "
            f"[{sx0}, {sx1}) x [{sy0}, {sy1}); pose {pose}")
    return fig, x0, y0


def render_init(layout: Layout, poses: Sequence[Pose],
                identity_colours: Mapping[str, tuple[int, int, int]],
                garments: Garments = DEFAULT_GARMENTS,
                build_name: str = DEFAULT_BUILD
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
        fig, x0, y0 = _placed(layout, i, pose, colours, garments,
                              build_name)
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
               garments: Garments = DEFAULT_GARMENTS,
               build_name: str = DEFAULT_BUILD) -> dict:
    """The document `params_sha256` hashes -- what a mannequin name MEANS.

    {"layout": layout.as_row(), "poses": [p.as_row() ...], "colours": {part:
    [r, g, b]}, "skeleton": the module's skeleton constants by name}, plus
    "garments" for a non-default outfit. Angles are written as floats and
    lift as an int, so Pose(25, ...) and Pose(25.0, ...) -- the same drawing
    -- share a name; colours are the parts `garments` draw, the parts
    render_init reads.

    A non-default BUILD adds "build": [name, thigh, shin]; the default
    build adds nothing, so scout's document is the document it always was.

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
    names = list(_SKELETON_NAMES)
    if garments != DEFAULT_GARMENTS:
        # ONLY THE CONSTANTS THE CHOSEN GARMENTS DRAW, so a garment appended
        # to the vocabulary cannot rename a character who does not wear it.
        names.append("GARMENT_DRAW_VERSION")
        for part in colours:
            names.extend(_PART_SKELETON_NAMES.get(part, ()))
    skeleton = {name: (list(g[name]) if isinstance(g[name], tuple)
                       else g[name]) for name in names}
    doc = {"layout": layout.as_row(), "poses": rows,
           "colours": {part: list(rgb) for part, rgb in colours.items()},
           "skeleton": skeleton}
    if garments != DEFAULT_GARMENTS:
        # ONLY THE SLOTS THAT ARE NOT THE DEFAULT, for the same reason and by
        # the same rule the BUILD below writes no key for `standard`: a slot
        # appended to GARMENT_SLOTS otherwise grows a `"coat": false` in the
        # document of everyone who has never worn one.
        doc["garments"] = {
            slot.name: getattr(garments, slot.name)
            for slot in GARMENT_SLOTS
            if not (type(getattr(garments, slot.name)) is type(slot.default)
                    and getattr(garments, slot.name) == slot.default)}
    chosen = build(build_name)
    if chosen.name != DEFAULT_BUILD:
        # The BONES, not only the name: renaming a build would otherwise be
        # invisible, and retuning Build("long", 2, 1) to (3, 1) would draw a
        # different figure under the same mannequin name.
        doc["build"] = [chosen.name, chosen.thigh, chosen.shin]
    return doc


def params_sha256(layout: Layout, poses: Sequence[Pose],
                  identity_colours: Mapping[str, tuple[int, int, int]],
                  garments: Garments = DEFAULT_GARMENTS,
                  build_name: str = DEFAULT_BUILD) -> str:
    """Hex sha256 naming a render_init input, for the ledger.

    Canonical JSON (sort_keys, compact separators) of `params_doc`. Changes
    when any angle, colour, cell or skeleton constant changes.

    A NON-DEFAULT outfit adds "garments" -- ONLY the slots that are not
    their slot's default -- and, to "skeleton", GARMENT_DRAW_VERSION plus
    `_PART_SKELETON_NAMES` for the parts it actually DRAWS. Both halves are
    that way so appending a garment to the vocabulary cannot rename a
    character who does not wear it. A NON-DEFAULT build
    adds "build" -- its name AND its two bone deltas. A figure in
    model.DEFAULT_GARMENTS on model.DEFAULT_BUILD is hashed over exactly
    what it always was, so the shipped scout's name does not move when a hat
    constant or a build row does -- and no hat was drawn to be named.
    """
    text = json.dumps(params_doc(layout, poses, identity_colours, garments,
                                 build_name),
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()
