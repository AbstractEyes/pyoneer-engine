"""Character spritesheets, drawn from arithmetic.

Two bodies, both on the 176x256 grid `config/animations.json` declares:
frames 44 wide by 64 tall, four rows at y=0/64/128/192 and four columns at
x=0/44/88/132, with every `idle_*` sequence sitting on the middle column
(x=88, column 2) and every `walk_*` sequence running columns 0..3.

    .venv/Scripts/python.exe -m tools.art.sprites
    .venv/Scripts/python.exe -m tools.art.sprites --list

THE FOUR COLUMNS ARE FOUR DIFFERENT POSES                #TAG:art_walk_differs
------------------------------------------------------------------------
A walk cycle whose frames are the same picture satisfies every dimension
check and looks broken the moment it moves, so the columns are a real cycle:
contact, passing (the body rides one pixel higher and the legs close),
stand, contact again with the other leg leading. Column 2 is the stand,
which is why it is also the idle frame -- the idle pose is a MEMBER of the
walk cycle rather than a fifth drawing that has to be kept in step with it.

THE SIDE-ON SHEET AND `idle_down`                       #TAG:art_side_down_row
------------------------------------------------------------------------
`GameAnimationHandler.__init__` ends with `self.start('idle_down')`, and
`start` RAISES for a sequence the category does not carry. A side-on
category holding only left/right sequences therefore dies inside
`GameAnimatedEntity.__init__`, before `animation_drive.attach` gets to name
the `initial_sequence` a platformer map authored. `sidestep_sheet` declares a
`down` row for that reason alone, and that row is the RIGHT-facing walk pixel
for pixel: the one frame the construction trap can show is then a correct
standing pose rather than a wrong one.

That is an accommodation, not a design. The fix is an engine change -- the
opening sequence belongs to the CATEGORY, so a side-on category can declare
`idle_right` and the handler starts what its own data names -- and it is not
made here.

The `up` row carries the airborne poses: launch, rise, apex, fall, with the
apex on the idle column. A side-on body never names them, because
`GamePlatformerMoveBehavior` writes `state.facing` as only "left" or "right"
and `GameAnimationDriveBehavior` formats from that, so `walk_up` is never
asked for. They are on the sheet because the eight-name vocabulary has no
`jump_*` and a jumping body has nowhere else to look. A TOP-DOWN body given
this sheet will show a jumping sprite when it walks north; that is the cost
of a fixed vocabulary, and it is written down here so nobody meets it as a
mystery.
"""
from __future__ import annotations

from typing import NamedTuple

import pygame

from tools.art import Builder, render_cli
from tools.art.palette import OUTLINE, Ramp, bevel, fill, ramp, surface

RGB = tuple[int, int, int]

# --------------------------------------------------------------------------
# The grid, read out of config/animations.json rather than chosen here.
# `GameAnimation.frame_rect` reads x + index*width for a left-to-right
# sequence, so the furthest extents the config asks for are x=132+44 and
# y=192+64. A sheet smaller than that makes `slice_frames` raise naming the
# sequence and the frame; a sheet larger than that wastes nothing but says
# something the config does not.
# --------------------------------------------------------------------------
FRAME_W, FRAME_H = 44, 64
COLUMNS, ROWS = 4, 4
SHEET_W, SHEET_H = FRAME_W * COLUMNS, FRAME_H * ROWS      # 176 x 256

ROW_DOWN, ROW_LEFT, ROW_RIGHT, ROW_UP = 0, 1, 2, 3
"""Row order, from the `y` each sequence declares: 0, 64, 128, 192."""

IDLE_COLUMN = 2
"""x=88 / 44. Where every `idle_*` sequence points."""

CX = 22
"""The figure's centre column inside a frame."""

GROUND = 62
"""The row the soles rest on. `demos/sidestep.py` anchors collision at
(22.0, 63.0) in this frame, one row below the sole, so a body gated there
stands ON this line rather than hovering above it."""


class Body(NamedTuple):
    """The five materials one character is made of, by palette name.

    Names, not colours: every sheet in the pack pulls its shades through
    `palette.ramp`, so a character and the grass under it are lit by the same
    two constants and a colour changed there moves both.
    """

    skin: str
    hair: str
    shirt: str
    trouser: str
    boot: str
    accent: str


SCOUT = Body(skin="skin", hair="clay", shirt="cloth",
             trouser="granite", boot="bark", accent="gold")
"""The four-direction body. Mid-value and warm, so it separates from grass,
dirt and stone without being the brightest thing on the map."""

RUNNER = Body(skin="skin", hair="obsidian", shirt="brick",
              trouser="granite", boot="obsidian", accent="gold")
"""The side-on body. A platformer draws it against sky as often as against
ground, so it leans on the darkest hair and the reddest shirt the palette
has: value contrast is what survives being 44 pixels wide over a gradient."""


class Kit(NamedTuple):
    """A `Body` with every name already resolved to its ramp."""

    skin: Ramp
    hair: Ramp
    shirt: Ramp
    trouser: Ramp
    boot: Ramp
    accent: Ramp

    @classmethod
    def of(cls, body: Body) -> "Kit":
        return cls(*(ramp(name) for name in body))


# --------------------------------------------------------------------------
# Primitives. Three, and they are all this needs: limbs are rectangles,
# heads are ellipses, and the rim is what makes either one read.
# --------------------------------------------------------------------------

def _plate(target: pygame.Surface, rect, material: Ramp) -> None:
    """A limb: flat base, lit top and left, unlit bottom and right.

    One pixel of each, because a 5-pixel forearm has nothing left over.
    """
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return
    fill(target, (x, y, w, h), material.base)
    bevel(target, (x, y, w, h), material)


def _orb(target: pygame.Surface, rect, material: Ramp) -> None:
    """A head: three ellipses, dark to light, lit from the upper left.

    The shadow pass is offset down and right, so the mass reaches two rows
    BELOW the rect it was given. Anything that has to stop at an exact row --
    a hairline, and it is always a hairline -- wants `_cap` instead.
    """
    x, y, w, h = rect
    pygame.draw.ellipse(target, material.shadow, pygame.Rect(x + 1, y + 2, w, h))
    pygame.draw.ellipse(target, material.base, pygame.Rect(x, y, w, h))
    if w > 7 and h > 8:
        pygame.draw.ellipse(target, material.light,
                            pygame.Rect(x + 2, y + 2, w - 7, h - 8))


def _cap(target: pygame.Surface, rect, material: Ramp) -> None:
    """Hair: one ellipse that ends exactly where it is told, plus a sheen.

    A hairline two rows lower than intended costs the whole face -- the brow,
    the eye and the nose all land inside the hair mass and the head reads as
    a helmet with a chin.
    """
    x, y, w, h = rect
    pygame.draw.ellipse(target, material.base, pygame.Rect(x, y, w, h))
    if w > 8 and h > 5:
        pygame.draw.ellipse(target, material.light,
                            pygame.Rect(x + 3, y + 1, w // 2, max(3, h // 3)))


def _outlined(figure: pygame.Surface) -> pygame.Surface:
    """A copy with a one-pixel rim around every opaque pixel.

    The rim is what makes a 44x64 figure read as a figure over arbitrary
    terrain; without it the trouser granite and a night sky are the same
    object. Run on the FIGURE alone and never on a composed frame: a rim
    traced around a soft shadow ellipse turns the shadow into a drawn hole.
    """
    width, height = figure.get_size()
    opaque = [[figure.get_at((x, y))[3] > 0 for y in range(height)]
              for x in range(width)]
    out = figure.copy()
    rim = (*OUTLINE, 255)
    for x in range(width):
        for y in range(height):
            if opaque[x][y]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and opaque[nx][ny]:
                    out.set_at((x, y), rim)
                    break
    return out


SHADOW_COLOUR = (0, 0, 0, 74)
SHADOW_RECT = (9, 56, 26, 7)
"""Under the soles, inside the frame, and one row clear of the bottom edge so
a frame never bleeds into the row beneath it on the sheet."""


def _compose(figure: pygame.Surface, shadow: bool = True) -> pygame.Surface:
    """Ground shadow first, then the outlined figure over it.

    A frame with no shadow reads as airborne, which is what the `up` row of
    the side-on sheet wants and the whole reason this is a parameter.
    """
    frame = surface(FRAME_W, FRAME_H)
    if shadow:
        pygame.draw.ellipse(frame, SHADOW_COLOUR, pygame.Rect(SHADOW_RECT))
    frame.blit(_outlined(figure), (0, 0))
    return frame


# --------------------------------------------------------------------------
# The cycle. (lead, bob): which leg is forward, and how far the body rides.
# The passing frame is the only one off the ground line, which is the whole
# difference between a walk and a shuffle.
# --------------------------------------------------------------------------
WALK_POSES = ((1, 0), (0, 1), (0, 0), (-1, 0))


def _front_figure(kit: Kit, lead: int, bob: int, back: bool) -> pygame.Surface:
    """One figure seen from the front, or from behind when `back`."""
    fig = surface(FRAME_W, FRAME_H)

    def y(value: int) -> int:
        return value - bob

    # Legs part sideways on a contact frame and the trailing boot LIFTS a
    # pixel; without that lift the two contacts read as one repeated pose.
    # Lifts rather than drops: a boot pushed one row down puts its rim on
    # row 63, which is the next frame's territory on the sheet.
    left_x = CX - 7 + (-2 if lead > 0 else 0)
    right_x = CX + 1 + (2 if lead < 0 else 0)
    for leg_x, lift in ((left_x, 1 if lead > 0 else 0),
                        (right_x, 1 if lead < 0 else 0)):
        _plate(fig, (leg_x, y(44), 6, 11), kit.trouser)
        _plate(fig, (leg_x - 1, y(54) - lift, 8, 8), kit.boot)

    _plate(fig, (CX - 9, y(28), 18, 17), kit.shirt)
    # A lit collar across the shoulders: an 18x17 rectangle of one colour is
    # a slab, and two pixels of light at the top of it is a garment.
    _plate(fig, (CX - 5, y(28), 10, 2), Ramp(kit.shirt.name, kit.shirt.light))
    _plate(fig, (CX - 9, y(42), 18, 3), kit.accent)
    # Sleeves one step down from the chest. Same colour and the torso plus
    # both arms is one 26-pixel slab with a bevel through it.
    sleeve = Ramp(kit.shirt.name, kit.shirt.dark)
    for arm_x in (CX - 13, CX + 8):
        _plate(fig, (arm_x, y(30), 5, 12), sleeve)
        _plate(fig, (arm_x, y(40), 5, 4), kit.skin)
    _plate(fig, (CX - 3, y(25), 6, 4), kit.skin)
    _orb(fig, (CX - 10, y(9), 20, 18), kit.skin)

    if back:
        # Hair to the collar. A back view has no face, so the hairline and
        # the nape are the only things saying which way the body points.
        _cap(fig, (CX - 11, y(6), 22, 19), kit.hair)
        _plate(fig, (CX - 3, y(23), 6, 4), kit.hair)
    else:
        _cap(fig, (CX - 11, y(6), 22, 11), kit.hair)
        fill(fig, (CX - 9, y(14), 18, 2), kit.hair.dark)
        for eye_x in (CX - 6, CX + 4):
            fill(fig, (eye_x, y(18), 2, 3), OUTLINE)
        fill(fig, (CX - 1, y(22), 3, 1), kit.skin.shadow)
    return fig


def _side_figure(kit: Kit, *, lift: int = 0, near_dx: int = 0, far_dx: int = 0,
                 leg_h: int = 11, boot_dx: int = 0, arm_dx: int = 0,
                 arm_dy: int = 0, scarf: int = 0) -> pygame.Surface:
    """One figure in profile, FACING RIGHT.

    Every offset is a parameter so the walk cycle and the airborne poses come
    out of ONE renderer. Two renderers would be two characters wearing the
    same palette, and they would drift apart the first time a limb moved.

    `lift` raises the whole body, `leg_h` shortens the legs into a tuck,
    `boot_dx` slides the soles ahead of the shins into a bent knee, and
    `scarf` trails the accent backwards. The left-facing row is this surface
    flipped, so the two directions cannot come to disagree.
    """
    fig = surface(FRAME_W, FRAME_H)

    def y(value: int) -> int:
        return value - lift

    leg_top = y(44)
    boot_top = leg_top + leg_h - 1
    # The far leg is drawn first and one step darker, and so is the far arm.
    # Depth at this size is VALUE, not perspective: two limbs in one colour
    # merge into a single thick one and the stride stops reading.
    far_leg = Ramp(kit.trouser.name, kit.trouser.dark)
    far_boot = Ramp(kit.boot.name, kit.boot.dark)
    far_arm = Ramp(kit.shirt.name, kit.shirt.dark)
    _plate(fig, (CX - 4 + far_dx, leg_top, 6, leg_h), far_leg)
    _plate(fig, (CX - 5 + far_dx + boot_dx, boot_top, 8, 8), far_boot)
    _plate(fig, (CX - 4 + near_dx, leg_top, 6, leg_h), kit.trouser)
    _plate(fig, (CX - 5 + near_dx + boot_dx, boot_top, 8, 8), kit.boot)

    # The trailing arm, behind the chest and swinging against the near one.
    _plate(fig, (CX - 8 - arm_dx, y(30) - arm_dy, 4, 11), far_arm)
    if scarf:
        # Back to the collar, not just backwards: a bar that stops short of
        # the neck reads as a separate object floating behind the shoulder.
        _plate(fig, (CX - 6 - scarf, y(26), scarf + 8, 2), kit.accent)
    # A profile chest is narrower than a front one, and the head overhangs it
    # by five pixels. That overhang is most of what says "this is a profile".
    _plate(fig, (CX - 6, y(28), 12, 17), kit.shirt)
    _plate(fig, (CX - 6, y(42), 12, 3), kit.accent)
    _plate(fig, (CX + 3 + arm_dx, y(30) + arm_dy, 5, 11), far_arm)
    _plate(fig, (CX + 3 + arm_dx, y(39) + arm_dy, 5, 4), kit.skin)
    _plate(fig, (CX - 2, y(25), 6, 4), kit.skin)
    _orb(fig, (CX - 7, y(9), 16, 17), kit.skin)

    # Hair over the CROWN and the nape, stopping above the brow. The face is
    # the front third of the skull and it needs a brow, an eye, a nose and a
    # mouth; take any of them away and the head is a helmet with a chin.
    _cap(fig, (CX - 8, y(6), 15, 10), kit.hair)
    _plate(fig, (CX - 8, y(11), 5, 9), kit.hair)
    fill(fig, (CX + 1, y(15), 6, 1), kit.hair.dark)
    fill(fig, (CX + 3, y(17), 2, 3), OUTLINE)
    fill(fig, (CX + 7, y(18), 2, 3), kit.skin.shadow)
    fill(fig, (CX + 4, y(22), 3, 1), kit.skin.shadow)
    return fig


def _walk_side(kit: Kit, lead: int, bob: int) -> pygame.Surface:
    """One profile frame of the walk cycle.

    The arm swings against the near leg, which is what stops the two contact
    frames from being each other's mirror and therefore indistinguishable
    once the sheet is flipped for the left-facing row.
    """
    if lead == 0:
        # Not 1 and -1: an 8-wide boot at each makes ONE 10-wide boot, and
        # the stand loses the far leg it is supposed to be standing on.
        near_dx, far_dx = 1, -3
    else:
        near_dx = 5 * lead
        far_dx = -near_dx
    return _side_figure(kit, lift=bob, near_dx=near_dx, far_dx=far_dx,
                        arm_dx=-near_dx // 2, scarf=2 + abs(near_dx) // 2)


# Launch, rise, apex, fall -- and the apex lands on the idle column, so
# `idle_up` on the side-on sheet is a body hanging at the top of a jump.
#
# WHAT MAKES THESE READ AS AIRBORNE is the GAP under the soles, not the body
# height. `lift` cannot carry it: the hair sits at y=5 and the rim needs the
# row above it, so anything past 3 draws on the frame's own border. Short
# `leg_h` does carry it -- a five-pixel leg puts the boot nine rows clear of
# `GROUND` -- and `_compose(shadow=False)` takes away the one mark that would
# argue the feet are still down.
AIR_POSES = (
    dict(lift=-1, near_dx=3, far_dx=-3, leg_h=9, boot_dx=1, arm_dx=-3,
         arm_dy=2, scarf=3),
    dict(lift=3, near_dx=2, far_dx=-3, leg_h=5, boot_dx=3, arm_dx=2,
         arm_dy=-5, scarf=6),
    dict(lift=3, near_dx=4, far_dx=-4, leg_h=6, boot_dx=2, arm_dx=4,
         arm_dy=-4, scarf=5),
    dict(lift=2, near_dx=-3, far_dx=4, leg_h=7, boot_dx=-2, arm_dx=3,
         arm_dy=-2, scarf=7),
)


# --------------------------------------------------------------------------
# The sheets
# --------------------------------------------------------------------------

def character_sheet() -> pygame.Surface:
    """The four-direction body: down, left, right, up on rows 0..3."""
    kit = Kit.of(SCOUT)
    sheet = surface(SHEET_W, SHEET_H)
    for column, (lead, bob) in enumerate(WALK_POSES):
        right = _compose(_walk_side(kit, lead, bob))
        rows = {
            ROW_DOWN: _compose(_front_figure(kit, lead, bob, back=False)),
            ROW_LEFT: pygame.transform.flip(right, True, False),
            ROW_RIGHT: right,
            ROW_UP: _compose(_front_figure(kit, lead, bob, back=True)),
        }
        for row, frame in rows.items():
            sheet.blit(frame, (column * FRAME_W, row * FRAME_H))
    return sheet


def sidestep_sheet() -> pygame.Surface:
    """The side-on body. `#TAG:art_side_down_row` is why it has a down row."""
    kit = Kit.of(RUNNER)
    sheet = surface(SHEET_W, SHEET_H)
    for column, (lead, bob) in enumerate(WALK_POSES):
        right = _compose(_walk_side(kit, lead, bob))
        air = _compose(_side_figure(kit, **AIR_POSES[column]), shadow=False)
        rows = {
            ROW_DOWN: right,
            ROW_LEFT: pygame.transform.flip(right, True, False),
            ROW_RIGHT: right,
            ROW_UP: air,
        }
        for row, frame in rows.items():
            sheet.blit(frame, (column * FRAME_W, row * FRAME_H))
    return sheet


SHEETS: dict[str, Builder] = {
    # The slot `config/animations.json -> entity.file` names. The filename is
    # the engine's, not a claim about what is drawn on it.
    "data/graphics/tilesets/Characters/~Garet.png": character_sheet,
    "data/graphics/tilesets/Characters/Sidestep.png": sidestep_sheet,
}


if __name__ == "__main__":
    raise SystemExit(render_cli(SHEETS, "the character spritesheets"))
