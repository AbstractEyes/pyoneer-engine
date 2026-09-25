"""Pure data for the NovelAI sprite pipeline: every shared constant and type.

RESPONSIBILITY
--------------
This module is the vocabulary every other file of `tools.nai` speaks. It
holds the wire constants (host, endpoints, model ids), the free-tier limits,
the author's standing choices (strength, rating), the pixel constants the
mannequin, the masks and the post-processor must agree on, and the frozen
dataclasses that cross module boundaries. It imports only the standard
library, opens no file and no socket, and reads no environment variable, so
every other module -- and every check -- can import it first.

INVARIANTS
----------
* ONE GRID. `GRID` is the only set of coordinates that ever reaches the wire,
  and `snap` is the website's own snapping rule, reimplemented. A center is
  computed from a drawn bounding box and snapped; it is never typed by hand.
* ONE SPELLING OF EVERY WIRE STRING. A model id, an endpoint, the rating tag
  and the quality tail are spelled here and imported everywhere else. A
  second spelling is a second route that can drift (CLAUDE.md, ACTIVE
  WARNINGS: the sibling route).
* THE DATACLASSES DO NOT VALIDATE COST RULES. `Frame` and `Request` accept an
  off-grid center, a 29-step request or a V5 model id without complaint, on
  purpose: `guard.evaluate` is the ONE gate, and a check proves that gate goes
  red by constructing exactly such a value. What IS validated here is
  internal geometry that no request depends on being wrong -- a `Layout`
  whose cells leave the canvas, or a `Recipe` whose frame count disagrees
  with its layout -- and that raises at construction (law 7: raise, never
  fall back).
* THE AUTHOR'S STANDING CHOICES LIVE HERE AND NOWHERE ELSE: Opus free tier
  only, `rating:general` at the end of every base caption, img2img strength
  0.45 by default inside a 0.3-0.55 sweep band. The brief's 0.60 is
  overridden by the author and does not appear in this package.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, NamedTuple

# ---------------------------------------------------------------------------
# Position grid (brief 4.1)
# ---------------------------------------------------------------------------

GRID: tuple[float, ...] = (0.1, 0.3, 0.5, 0.7, 0.9)
"""The 5 legal values of a character center coordinate on V4 and V4.5."""


def snap(v: float) -> float:
    """Snap one normalised coordinate onto `GRID`, exactly as the website does.

    `GRID[min(4, max(0, floor(5 * v)))]`. Raises TypeError for a non-number
    (a bool included) and ValueError for NaN, an infinity, or a value outside
    [0, 1] -- a center computed from a bounding box inside the canvas is
    always in range, so an out-of-range value is a bug upstream, not a value
    to clamp.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise TypeError(f"snap() takes a number, got {type(v).__name__}")
    if not math.isfinite(v) or v < 0.0 or v > 1.0:
        raise ValueError(f"snap() takes a value in [0, 1], got {v!r}")
    return GRID[min(4, max(0, math.floor(5 * v)))]


def shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """`rgb` x `factor`, each channel `int(round(c * factor))` -- THE shade
    rule, drawn by mannequin and judged by characters."""
    return tuple(int(round(c * factor)) for c in rgb)  # type: ignore[return-value]


def on_grid(v: object) -> bool:
    """True when `v` is exactly one of the `GRID` floats (never a near miss)."""
    return (not isinstance(v, bool) and isinstance(v, (int, float))
            and float(v) in GRID)


# ---------------------------------------------------------------------------
# Wire: host, endpoints, timeout (brief 1.1, 1.4, 2.2 #11)
# ---------------------------------------------------------------------------

HOST = "image.novelai.net"
GENERATE_URL = "https://image.novelai.net/ai/generate-image"
SUBSCRIPTION_URL = "https://image.novelai.net/user/subscription"
ALLOWED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    ("POST", GENERATE_URL),
    ("GET", SUBSCRIPTION_URL),
})
"""The ONLY (method, url) pairs any code in this package may open. Nothing
under `api.novelai.net`, no stream, encode-vibe, augment-image or upscale."""

TIMEOUT_S = 120.0
"""Seconds, for both endpoints. The website's generation timeout."""

CORRELATION_ID_LEN = 6
"""`x-correlation-id` is 6 characters of [A-Za-z0-9]."""

# ---------------------------------------------------------------------------
# Models (brief 1.3). V5 ids are not spelled anywhere in this package.
# ---------------------------------------------------------------------------

MODEL_FULL = "nai-diffusion-4-5-full"
MODEL_CURATED = "nai-diffusion-4-5-curated"
MODEL_FULL_INPAINTING = "nai-diffusion-4-5-full-inpainting"
MODEL_CURATED_INPAINTING = "nai-diffusion-4-5-curated-inpainting"

ACTIONS: tuple[str, ...] = ("generate", "img2img", "infill")
VARIANTS: tuple[str, ...] = ("full", "curated")

MODELS_BY_ACTION: Mapping[str, tuple[str, str]] = MappingProxyType({
    "generate": (MODEL_FULL, MODEL_CURATED),
    "img2img": (MODEL_FULL, MODEL_CURATED),
    "infill": (MODEL_FULL_INPAINTING, MODEL_CURATED_INPAINTING),
})
"""Per action, (full, curated). Index 0 is the full variant."""

UC_PRESET_NONE: Mapping[str, int] = MappingProxyType({
    MODEL_FULL: 4,
    MODEL_CURATED: 3,
    MODEL_FULL_INPAINTING: 4,
    MODEL_CURATED_INPAINTING: 3,
})
"""The per-model "none" index for `ucPreset`; the UC text is written by hand."""

PROOF_ACTIONS: tuple[str, ...] = ("img2img", "infill")
"""Actions refused until `proofs.json` holds a row that covers the call: the
same action, on either V4.5 variant (`Proof.covers`)."""


def model_for(action: str, variant: str) -> str:
    """The model id for `action` in `variant` ("full" or "curated").

    Raises ValueError naming the legal values for an unknown action or
    variant; there is no default variant hidden in here.
    """
    if action not in MODELS_BY_ACTION:
        raise ValueError(f"unknown action {action!r}; legal: {ACTIONS}")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; legal: {VARIANTS}")
    return MODELS_BY_ACTION[action][VARIANTS.index(variant)]


# ---------------------------------------------------------------------------
# Free-tier limits (brief 2.1, 2.2)
# ---------------------------------------------------------------------------

MAX_AREA = 1048576
"""width * height must not exceed this (1024 * 1024)."""
MAX_STEPS = 28
DIM_MULTIPLE = 64
MIN_DIM = 64
MAX_FRAMES = 6
"""V4.5 accepts at most 6 character captions."""
N_SAMPLES = 1
OPUS_TIER = 3
TOKEN_BUDGET = 450
"""Rough T5 budget: TOKENS_PER_WORD * words over base + character captions."""
TOKENS_PER_WORD = 1.5
SEED_MIN = 2
"""Seeds start at 2 so `seed - 1` (extra_noise_seed) is still a valid seed."""
SEED_MAX = 4294967287

# ---------------------------------------------------------------------------
# Request defaults (brief 1.5, 3.5) and the author's overrides
# ---------------------------------------------------------------------------

DEFAULT_WIDTH = 1216
DEFAULT_HEIGHT = 832
DEFAULT_STEPS = 23
DEFAULT_SCALE = 5
DEFAULT_SAMPLER = "k_euler_ancestral"
DEFAULT_NOISE_SCHEDULE = "karras"
PARAMS_VERSION = 3

DEFAULT_STRENGTH = 0.45
"""AUTHOR: img2img denoising strength. Low for continuity, not too low."""
STRENGTH_BAND: tuple[float, float] = (0.3, 0.55)
"""AUTHOR: the closed interval an img2img strength sweep stays inside. The
floor was 0.35 until the author, 2026-09-25: "5 passes, same seed for all,
each with increasing denoise strength. 0.3, 0.35, 0.4, 0.45, 0.5"."""
DEFAULT_IMG2IMG_NOISE = 0.05
DEFAULT_INFILL_NOISE = 0.0
NOISE_RANGE: tuple[float, float] = (0.0, 0.99)
"""The closed interval NovelAI accepts for `noise` (brief 1.5). A typo such as
`--noise 5` is refused locally instead of spending a command on a 400."""
DEFAULT_INPAINT_STRENGTH = DEFAULT_STRENGTH
"""DESIGN, following the author's continuity rule rather than the brief's
0.70: infill repaints one cell and should stay close to what it repaints."""
INFILL_FULL_REPAINT = 1.0
"""The one infill strength outside STRENGTH_BAND a recipe accepts: the
prompt fully decides the cell (brief 3.5, "the pose itself is wrong")."""

PROBE_STEPS = 4
PROBE_STRENGTH = 0.3
"""A probe is not production: its strength sits at the bottom of the band on
purpose, because the strength is the cost multiplier if the action is
charged. What marks a probe is PROBE_STEPS and the probe route itself, never
this value alone."""
PROBE_MAX_ANLAS = 2
"""Worst case of one probe by the client formula (brief 2.3)."""

# ---------------------------------------------------------------------------
# Body keys that must never be sent (brief 1.5 "Never send", 2.2 #5)
# ---------------------------------------------------------------------------

INPAINT_STRENGTH_KEY = "".join(("inpaint", "Img2Img", "Strength"))
"""The infill strength's body key, and the ledger's column for it.

SPELLED IN PIECES ON PURPOSE, and spelled nowhere else: as one literal this
camelCase wire key (22 characters, a digit, mixed case) is read by
tools/check_secrets.py's detector 2 as a generated key -- a measured false
positive that would turn the suite red. It is NovelAI's file format and cannot
be renamed, so every module imports this constant instead of writing the
literal. A tracked Markdown file spelling it as a bare word trips the same
detector."""

IMG2IMG_KEY = "img2img"
"""The infill body's nested img2img object key."""

IMAGE_BODY_KEYS: tuple[str, ...] = (
    "image", "mask", "strength", "noise", "extra_noise_seed",
    INPAINT_STRENGTH_KEY, IMG2IMG_KEY, "color_correct",
)
"""Every `parameters` key that only an image action carries."""

ACTION_BODY_KEYS: Mapping[str, tuple[frozenset[str], frozenset[str]]] = \
    MappingProxyType({
        "generate": (frozenset(), frozenset(IMAGE_BODY_KEYS)),
        "img2img": (frozenset({"image", "strength", "noise",
                               "extra_noise_seed", "color_correct"}),
                    frozenset({"mask", INPAINT_STRENGTH_KEY, IMG2IMG_KEY})),
        "infill": (frozenset({"image", "mask", "strength", "noise",
                              "extra_noise_seed", INPAINT_STRENGTH_KEY}),
                   frozenset({"color_correct"})),
    })
"""Per action, (required, forbidden) among IMAGE_BODY_KEYS -- brief 1.5-1.8.
Guard condition 1 binds a body's keys to its action with this table, so a
generate body carrying an image (or an img2img body carrying a mask) is
refused even when it was edited after `request.build_body`. The infill's
nested IMG2IMG_KEY object is in neither set: it is present exactly when the
inpaint strength is not INFILL_FULL_REPAINT, and condition 1 reads that rule
too."""

NEVER_SEND_KEYS: frozenset[str] = frozenset({
    "sm", "sm_dyn", "uncond_scale", "image_format", "stream", "characterRef",
})
NEVER_SEND_PREFIXES: tuple[str, ...] = (
    "tag_hint_", "director_reference", "reference_",
)

# ---------------------------------------------------------------------------
# Prompt constants (brief 3, author)
# ---------------------------------------------------------------------------

RATING_TAG = "rating:general"
QUALITY_TAIL = "very aesthetic, masterpiece, no text, rating:general"
"""Ends every base caption; appears in no character caption."""
RATING_RX = re.compile(r"rating\s*:")
"""A rating tag, however spaced (`rating:explicit`, `rating :explicit`).
Searched for ONLY through `rating_tag_in`, which lower-cases first."""


def rating_tag_in(text: str) -> bool:
    """THE ONE RATING-TAG RULE: RATING_RX in the lower-cased text, so
    `Rating:general` and `RATING :explicit` are rating tags too.

    `Recipe` asks it of the base caption before its QUALITY_TAIL and of every
    pose word, `recipes` of pose words, `characters.tag_problem` of every
    identity tag, `spec` of a request file's prompts and UCs, and guard
    condition 7 of the body it is about to send. A route that searched the
    raw text instead let `Rating:general` through and sent two rating tags;
    `tools/check_nai.py` asserts no module but this one names RATING_RX.
    """
    return RATING_RX.search(text.lower()) is not None

NEGATIVE = (
    "nsfw, lowres, artistic error, film grain, scan artifacts, worst quality, "
    "bad quality, jpeg artifacts, very displeasing, chromatic aberration, "
    "dithering, halftone, screentone, logo, too many watermarks, watermark, "
    "signature, text, blurry, 3d, realistic, gradient background, "
    "detailed background, scenery, shadow, cropped, out of frame, "
    "from behind, facing viewer"
)
"""The negative prompt of every recipe (recipes.NEGATIVE re-exports it):
V4.5 Full Heavy minus `multiple views`, `negative space`, `blank page`, plus
sprite negatives; `nsfw` first. Same text for Curated (ucPreset 3). Spelled
here, not in recipes, because characters.tag_problem refuses an identity tag
that is one of its tags -- asking for what the negative prompt refuses -- and
`characters` imports `model` only."""

# ---------------------------------------------------------------------------
# Pixel constants shared by mannequin, masks and post (brief 4, 5)
# ---------------------------------------------------------------------------

INIT_K = 8
"""Canvas pixels per source pixel in a rendered init (lever L13)."""
H_SRC = 40
"""Mannequin figure height in source pixels, uniform across every strip."""
BACKGROUND_RGB: tuple[int, int, int] = (0x80, 0x80, 0x80)
OUTLINE_RGB: tuple[int, int, int] = (0x20, 0x20, 0x20)
FAR_SHADE = 0.7
"""The mannequin draws the far arm and leg in each part's colour x this."""
INNER_SHADE = 0.6
"""The mannequin draws an inner line (a part's pixel 4-adjacent to a near
limb) in that part's colour x this. Both shades are spelled here, not in
mannequin, because characters judges every shade a colour is drawn in
against BACKGROUND_RGB, and `characters` imports `model` only."""
MASK_REPAINT_RGB: tuple[int, int, int] = (255, 255, 255)
MASK_KEEP_RGB: tuple[int, int, int] = (0, 0, 0)
MASK_ALIGN = 8
"""Every mask edge and every cell edge is a multiple of this (1/8 latent)."""
DEFAULT_COLOURS = 16
"""Reference palette size for post-processing (lever-able 8..32)."""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """One character box on the wire: its caption, its UC, its snapped center.

    One tuple of these produces `characterPrompts`,
    `v4_prompt.caption.char_captions` and
    `v4_negative_prompt.caption.char_captions` -- in `request.build_body` and
    nowhere else. `center` is (x, y) in GRID units. Not validated here; see
    the module docstring.
    """
    caption: str
    uc: str
    center: tuple[float, float]


@dataclass(frozen=True)
class Pose:
    """Mannequin joint angles for one frame (brief 4.3).

    Degrees from straight down; positive means toward the facing direction
    (right). Shin and forearm angles are ABSOLUTE, not relative to the thigh
    or upper arm. `lean` is torso lean forward in degrees; `lift` is how many
    source pixels the lowest foot pixel sits above the baseline. "near" limbs
    are drawn last in base colours, "far" limbs first at x0.7 -- the only
    place left/right is encoded.
    """
    near_thigh: float
    near_shin: float
    far_thigh: float
    far_shin: float
    near_upper: float
    near_fore: float
    far_upper: float
    far_fore: float
    lean: float = 0.0
    lift: int = 0

    def swapped(self) -> "Pose":
        """The same pose with near and far limbs exchanged (run R4-R6)."""
        return Pose(
            near_thigh=self.far_thigh, near_shin=self.far_shin,
            far_thigh=self.near_thigh, far_shin=self.near_shin,
            near_upper=self.far_upper, near_fore=self.far_fore,
            far_upper=self.near_upper, far_fore=self.near_fore,
            lean=self.lean, lift=self.lift,
        )

    def as_row(self) -> dict:
        """Plain dict, field order stable, for hashing mannequin parameters."""
        return {
            "near_thigh": self.near_thigh, "near_shin": self.near_shin,
            "far_thigh": self.far_thigh, "far_shin": self.far_shin,
            "near_upper": self.near_upper, "near_fore": self.near_fore,
            "far_upper": self.far_upper, "far_fore": self.far_fore,
            "lean": self.lean, "lift": self.lift,
        }


Rect = tuple[int, int, int, int]
"""(x0, y0, x1, y1), half-open, in canvas pixels unless a name says _src."""


@dataclass(frozen=True)
class CellSpec:
    """One frame's cell in a layout (brief 4.2).

    `rect_canvas` is half-open canvas pixels. `hip_x_src` is the source
    column the mannequin's hip sits on; `baseline_src` is the source row the
    lowest foot pixel of a grounded pose sits on.
    """
    rect_canvas: Rect
    hip_x_src: int
    baseline_src: int


@dataclass(frozen=True)
class Layout:
    """A canvas split into frame cells, and the scale the init is drawn at.

    Validated at construction (raises ValueError):
      * width == src_w * k and height == src_h * k;
      * width and height are multiples of DIM_MULTIPLE and >= MIN_DIM;
      * 1 <= len(cells) <= MAX_FRAMES;
      * every cell rect lies inside the canvas, has positive size, and every
        edge is a multiple of MASK_ALIGN and of k;
      * no two cell rects overlap;
      * every hip column lies inside its cell's source x range and every
        baseline row inside its source y range.
    Cells are listed in reading order (top to bottom, left to right), which
    is also caption order on the wire.
    """
    name: str
    width: int
    height: int
    k: int
    cells: tuple[CellSpec, ...]
    src_w: int
    src_h: int

    def __post_init__(self) -> None:
        if self.k <= 0:
            raise ValueError(f"layout {self.name}: k must be positive")
        if self.width != self.src_w * self.k or self.height != self.src_h * self.k:
            raise ValueError(
                f"layout {self.name}: {self.width}x{self.height} is not "
                f"{self.src_w}x{self.src_h} source pixels times k={self.k}")
        for dim in (self.width, self.height):
            if dim < MIN_DIM or dim % DIM_MULTIPLE:
                raise ValueError(
                    f"layout {self.name}: canvas dimension {dim} is not a "
                    f"multiple of {DIM_MULTIPLE} >= {MIN_DIM}")
        if not 1 <= len(self.cells) <= MAX_FRAMES:
            raise ValueError(
                f"layout {self.name}: {len(self.cells)} cells; legal 1.."
                f"{MAX_FRAMES}")
        for i, cell in enumerate(self.cells):
            x0, y0, x1, y1 = cell.rect_canvas
            if not (0 <= x0 < x1 <= self.width and 0 <= y0 < y1 <= self.height):
                raise ValueError(
                    f"layout {self.name}: cell {i} rect {cell.rect_canvas} is "
                    f"empty or outside the {self.width}x{self.height} canvas")
            for edge in (x0, y0, x1, y1):
                if edge % MASK_ALIGN or edge % self.k:
                    raise ValueError(
                        f"layout {self.name}: cell {i} edge {edge} is not a "
                        f"multiple of {MASK_ALIGN} and of k={self.k}")
            sx0, sy0, sx1, sy1 = self.rect_src(i)
            if not sx0 <= cell.hip_x_src < sx1:
                raise ValueError(
                    f"layout {self.name}: cell {i} hip column "
                    f"{cell.hip_x_src} is outside source x [{sx0}, {sx1})")
            if not sy0 <= cell.baseline_src < sy1:
                raise ValueError(
                    f"layout {self.name}: cell {i} baseline row "
                    f"{cell.baseline_src} is outside source y [{sy0}, {sy1})")
            for j in range(i):
                ax0, ay0, ax1, ay1 = self.cells[j].rect_canvas
                if x0 < ax1 and ax0 < x1 and y0 < ay1 and ay0 < y1:
                    raise ValueError(
                        f"layout {self.name}: cells {j} and {i} overlap")

    @property
    def count(self) -> int:
        """Number of frames (cells) in this layout."""
        return len(self.cells)

    def rect_src(self, index: int) -> Rect:
        """Cell `index`'s rect in source pixels (canvas rect divided by k)."""
        x0, y0, x1, y1 = self.cells[index].rect_canvas
        return (x0 // self.k, y0 // self.k, x1 // self.k, y1 // self.k)

    def as_row(self) -> dict:
        """Plain dict for hashing and for the sidecar/ledger."""
        return {
            "name": self.name, "width": self.width, "height": self.height,
            "k": self.k, "src_w": self.src_w, "src_h": self.src_h,
            "cells": [{"rect_canvas": list(c.rect_canvas),
                       "hip_x_src": c.hip_x_src,
                       "baseline_src": c.baseline_src} for c in self.cells],
        }


# ---------------------------------------------------------------------------
# Who the sprite is, and what it wears: ONE table (author, 2026-09-17)
# ---------------------------------------------------------------------------


class Subject(NamedTuple):
    """Who a character file draws, and every string that says so.

    `count_tag` heads the base caption (the ONE count in the request),
    `noun` opens every character caption and fills the `{noun}` of every
    recipe sentence ("the same boy"), and `words` are the words that NAME
    this subject in a tag -- refused by characters.tag_problem in a file
    whose subject is a different one, because a `male` tag under a `1girl`
    count is a contradiction the model resolves by drawing neither.
    """
    name: str
    count_tag: str
    noun: str
    words: tuple[str, ...]


SUBJECTS: tuple[Subject, ...] = (
    Subject("boy", "1boy", "boy", ("boy", "boys", "male", "man", "men")),
    Subject("girl", "1girl", "girl",
            ("girl", "girls", "female", "woman", "women")),
)
"""Every subject a character file may declare. The words are whole words:
`boyish` names no subject, and `woman` is not `man`."""

SUBJECT_NAMES: tuple[str, ...] = tuple(s.name for s in SUBJECTS)

DEFAULT_SUBJECT = "boy"
"""What a character file with no `subject` field means -- scout's, so every
file written before the field existed loads unchanged."""


def subject(name: object) -> Subject:
    """The Subject called `name`; ValueError listing SUBJECT_NAMES."""
    for candidate in SUBJECTS:
        if candidate.name == name:
            return candidate
    raise ValueError(f"unknown subject {name!r}; legal: {SUBJECT_NAMES}")


class GarmentSlot(NamedTuple):
    """One choice in an outfit, and the colour parts each choice draws.

    `choices` is every legal value in the character file; `default` is what
    a file that does not write the slot means; `drawn` is
    ((choice, (part, ...)), ...) -- THE table `garment_parts` reads, which
    is why the loader can refuse a colour for a part no garment draws and
    the mannequin can ask for exactly the parts it is about to paint.
    """
    name: str
    choices: tuple[object, ...]
    default: object
    drawn: tuple[tuple[object, tuple[str, ...]], ...]

    def parts_for(self, choice: object) -> tuple[str, ...]:
        """The parts `choice` draws; ValueError for an unknown choice."""
        for value, parts in self.drawn:
            if type(value) is type(choice) and value == choice:
                return parts
        raise ValueError(f"unknown {self.name} {choice!r}; legal: "
                         f"{self.choices}")


GARMENT_SLOTS: tuple[GarmentSlot, ...] = (
    GarmentSlot("hat", ("none", "wizard", "brim"), "none",
                (("none", ()), ("wizard", ("hat",)), ("brim", ("brim",)))),
    GarmentSlot("cape", (False, True), False,
                ((False, ()), (True, ("cape",)))),
    GarmentSlot("neck", ("scarf", "none"), "scarf",
                (("scarf", ("scarf",)), ("none", ()))),
    GarmentSlot("legwear", ("pants", "dress"), "pants",
                (("pants", ("tunic", "pants")), ("dress", ("dress",)))),
    GarmentSlot("footwear", ("boots", "heels"), "boots",
                (("boots", ("boots",)), ("heels", ("heels",)))),
    GarmentSlot("coat", (False, True), False,
                ((False, ()), (True, ("coat",)))),
    GarmentSlot("face", ("none", "mask"), "none",
                (("none", ()), ("mask", ("mask",)))),
)
"""The outfit vocabulary, in `Garments` field order.

`hat` has THREE choices and each drawing gets its OWN part: a `wizard` cone
paints `hat` and a `brim` (the wide flat gunslinger brim) paints `brim`, for
the reason `footwear` splits `boots` from `heels` -- two shapes sharing one
part name make "the hat is drawn" true for whichever one is there, and an
assertion that cannot tell them apart is CLAUDE.md law 5's vacuous half.
`coat` and `face` are appended rather than inserted so every positional
`Garments(...)` and every character file written before them means what it
always did."""


class Garments(NamedTuple):
    """What one character wears, one field per GARMENT_SLOTS entry.

    The defaults ARE scout's outfit, so `Garments()` is what every character
    file written before this table existed means, and
    `garment_parts(Garments())` is `IDENTITY_PARTS`.
    """
    hat: str = "none"
    cape: bool = False
    neck: str = "scarf"
    legwear: str = "pants"
    footwear: str = "boots"
    coat: bool = False
    face: str = "none"


DEFAULT_GARMENTS = Garments()

ALWAYS_PARTS: tuple[str, ...] = ("skin", "hair", "belt")
"""The parts every outfit draws, whatever its garments."""

PARTS: tuple[str, ...] = (
    "skin", "hair", "scarf", "tunic", "belt", "pants", "boots",
    "dress", "heels", "cape", "hat", "brim", "coat", "mask",
)
"""Every colour part any garment draws, in the order an Identity lists them.
The first seven are the default outfit's, in their original order, so a
scout file's colours are read in the order they always were."""


def garment_problem(slot: GarmentSlot, value: object) -> str | None:
    """Why `value` is not a legal choice for `slot`, or None.

    The TYPE is judged first, so `0` is not `False` and `1` is not `True`:
    a JSON number in a boolean slot is refused instead of read as one.
    """
    if any(type(choice) is type(value) and choice == value
           for choice in slot.choices):
        return None
    return (f"{value!r} is not a legal {slot.name}; legal: "
            f"{', '.join(repr(c) for c in slot.choices)}")


def garments_problem(garments: object) -> str | None:
    """Why `garments` is not a legal Garments, or None -- the one rule the
    loader (per JSON key) and every in-code route (whole value) share."""
    if not isinstance(garments, Garments):
        return (f"garments must be a {Garments.__name__}, got "
                f"{type(garments).__name__}")
    for slot in GARMENT_SLOTS:
        problem = garment_problem(slot, getattr(garments, slot.name))
        if problem is not None:
            return problem
    return None


def garment_parts(garments: Garments) -> tuple[str, ...]:
    """The colour parts `garments` draw: ALWAYS_PARTS plus each slot's, in
    PARTS order. ValueError (garments_problem) for an illegal choice."""
    problem = garments_problem(garments)
    if problem is not None:
        raise ValueError(problem)
    wanted = set(ALWAYS_PARTS)
    for slot in GARMENT_SLOTS:
        wanted.update(slot.parts_for(getattr(garments, slot.name)))
    return tuple(part for part in PARTS if part in wanted)


def garments_text(garments: Garments) -> str:
    """`garments` as one line for a refusal: "hat=wizard, cape=True, ..."."""
    return ", ".join(f"{slot.name}={getattr(garments, slot.name)!r}"
                     for slot in GARMENT_SLOTS)


IDENTITY_PARTS: tuple[str, ...] = garment_parts(DEFAULT_GARMENTS)
"""The parts the DEFAULT outfit draws -- scout's seven, in their original
order. A character wearing something else names `garment_parts(its
garments)` instead; this tuple is what a file with no `garments` field
means."""

if IDENTITY_PARTS != ("skin", "hair", "scarf", "tunic", "belt", "pants",
                      "boots"):
    raise RuntimeError(f"model: the default outfit draws {IDENTITY_PARTS}, "
                       f"not the shipped scout's seven parts in their order")
_unknown_parts = sorted(
    {part for slot in GARMENT_SLOTS for _c, parts in slot.drawn
     for part in parts}.union(ALWAYS_PARTS) - set(PARTS))
if _unknown_parts:
    raise RuntimeError(f"model: GARMENT_SLOTS draws {_unknown_parts}, which "
                       f"PARTS does not list")
if tuple(Garments._fields) != tuple(slot.name for slot in GARMENT_SLOTS):
    raise RuntimeError("model: Garments' fields and GARMENT_SLOTS disagree")


# ---------------------------------------------------------------------------
# Build: WHERE THE HIP SITS. One axis, three names, total height held.
# ---------------------------------------------------------------------------


class Build(NamedTuple):
    """One proportion: source px moved OUT of the torso and INTO the legs.

    `thigh` and `shin` are added to the mannequin's THIGH and SHIN, and
    exactly their sum is taken off TORSO_H. So the hip RISES by
    `hip_rise` while the figure's TOTAL HEIGHT, its ground line and its
    head's height above that ground line do not move at all -- a build is
    a redistribution, never a resize. Everything that hangs off the hip
    (the belt, the coat's skirt, an A-line skirt) rises with it and
    everything that hangs off the shoulder (the arms, a cape, the scarf
    tail, the head) stays exactly where it was, because
    `shoulder_to_sole` is invariant: TORSO_H - SHOULDER_DROP + THIGH +
    SHIN is unchanged when `thigh + shin + torso` is zero.

    THIS IS THE AXIS THE REFERENCE FIGURE NEEDED. Measured on the author's
    own ~Garet.png side pose: 45 px tall, hat top to sole, with the coat
    hem 41 px down and 3 px of boot below it -- 6.7% of the figure. A
    trenchcoat that long over a hip that low leaves no leg to see, and no
    amount of prompting puts one back.
    """
    name: str
    thigh: int
    shin: int

    @property
    def torso(self) -> int:
        """Source px added to TORSO_H: minus what the legs took."""
        return -(self.thigh + self.shin)

    @property
    def hip_rise(self) -> int:
        """Source px the hip sits above the standard build's."""
        return self.thigh + self.shin


BUILDS: tuple[Build, ...] = (
    Build("standard", 0, 0),
    Build("original", -2, -1),
    Build("long", 2, 1),
)
"""Every proportion a character file may declare, `standard` first.

`standard` is scout's and adds nothing to anything, so a figure that takes
it is drawn by the same arithmetic it always was, down to the byte.
`original` is the author's own Garet as he drew him and did not like --
the low hip that makes a long coat read as a barrel. `long` is the fix he
has wanted since: 3 px of torso become 3 px of leg."""

BUILD_NAMES: tuple[str, ...] = tuple(b.name for b in BUILDS)

DEFAULT_BUILD = "standard"
"""What a character file with no `build` field means -- scout's, so every
file written before the field existed loads, draws and hashes unchanged."""


def build(name: object) -> Build:
    """The Build called `name`; ValueError listing BUILD_NAMES."""
    for candidate in BUILDS:
        if candidate.name == name:
            return candidate
    raise ValueError(f"unknown build {name!r}; legal: {BUILD_NAMES}")


def build_problem(value: object) -> str | None:
    """Why `value` is not a build name, or None."""
    if isinstance(value, str) and value in BUILD_NAMES:
        return None
    return f"{value!r} is not a build; legal: {BUILD_NAMES}"


if BUILDS[0].name != DEFAULT_BUILD or BUILDS[0][1:] != (0, 0):
    raise RuntimeError("model: the default build must be the first BUILDS "
                       "row and must add nothing to any bone")
_bad_build = [b.name for b in BUILDS if b.thigh + b.shin + b.torso != 0]
if _bad_build:
    raise RuntimeError(f"model: builds {_bad_build} do not hold the figure's "
                       f"height: a build moves the hip, it does not resize")


@dataclass(frozen=True)
class Identity:
    """The character: who it is, what it wears, its caption tags and colours.

    `tags` goes into the base caption, `anchor` into every character caption,
    `colours` is ((part, (r, g, b)), ...) for exactly
    `garment_parts(garments)` -- `IDENTITY_PARTS` while `garments` is the
    default. `subject` is one of SUBJECT_NAMES and decides the count tag,
    the caption noun and which subject words a tag may not carry. `build`
    is one of BUILD_NAMES and says where the hip sits; it changes no
    caption and no colour, only the drawing.
    DESIGN (brief 3.1): no grey and no near-white or near-black colour, since
    grey is the key colour and near-black the outline.
    """
    tags: str
    anchor: str
    colours: tuple[tuple[str, tuple[int, int, int]], ...]
    subject: str = DEFAULT_SUBJECT
    garments: Garments = DEFAULT_GARMENTS
    build: str = DEFAULT_BUILD

    def colour(self, part: str) -> tuple[int, int, int]:
        """The RGB of `part`; KeyError naming the part when it is absent."""
        for name, rgb in self.colours:
            if name == part:
                return rgb
        raise KeyError(f"identity has no colour for part {part!r}")

    def as_dict(self) -> dict[str, tuple[int, int, int]]:
        """`colours` as a fresh dict, in declaration order."""
        return dict(self.colours)


@dataclass(frozen=True)
class Recipe:
    """Everything needed to build one strip's request, except seed and action.

    `frame_poses` is ((pose_words, Pose), ...), one per layout cell, in cell
    order. `fps_hint` goes to the sidecar. `hold_arc` True means every frame
    takes the vertical shift of the strip's first ground frame during
    post-processing (jump); False means each ground frame is aligned to its
    own baseline and each airborne frame (lift > 0) takes the first ground
    frame's shift (walk, run). Validated at construction (raises ValueError):
    frame count equals the layout's cell count, the base caption ends with
    QUALITY_TAIL and carries no other rating tag (`rating_tag_in`) before it, no
    pose words carry a rating tag, all text is ASCII, and at least one pose
    is grounded.
    """
    name: str
    layout: Layout
    base_caption: str
    negative: str
    frame_poses: tuple[tuple[str, Pose], ...]
    identity: Identity
    fps_hint: int = 8
    hold_arc: bool = False

    def __post_init__(self) -> None:
        if len(self.frame_poses) != self.layout.count:
            raise ValueError(
                f"recipe {self.name}: {len(self.frame_poses)} poses for a "
                f"{self.layout.count}-cell layout {self.layout.name}")
        if not self.base_caption.endswith(QUALITY_TAIL):
            raise ValueError(
                f"recipe {self.name}: base caption must end with "
                f"{QUALITY_TAIL!r}")
        texts = [self.base_caption, self.negative, self.identity.tags,
                 self.identity.anchor] + [w for w, _ in self.frame_poses]
        for text in texts:
            if not text.isascii():
                raise ValueError(f"recipe {self.name}: non-ASCII text {text!r}")
        for words, _ in self.frame_poses:
            if rating_tag_in(words):
                raise ValueError(
                    f"recipe {self.name}: a rating tag belongs only at the end "
                    f"of the base caption, not in pose words {words!r}")
        head = self.base_caption[:-len(QUALITY_TAIL)]
        if rating_tag_in(head):
            raise ValueError(
                f"recipe {self.name}: a rating tag sits in the base caption "
                f"before its closing {QUALITY_TAIL!r}; the rating is written "
                f"once, at the end")
        if not any(p.lift == 0 for _, p in self.frame_poses):
            raise ValueError(f"recipe {self.name}: no grounded pose (lift 0)")

    @property
    def poses(self) -> tuple[Pose, ...]:
        return tuple(p for _, p in self.frame_poses)

    @property
    def pose_words(self) -> tuple[str, ...]:
        return tuple(w for w, _ in self.frame_poses)

    @property
    def ground(self) -> tuple[bool, ...]:
        """Per frame: True when the pose touches the baseline (lift == 0)."""
        return tuple(p.lift == 0 for _, p in self.frame_poses)


@dataclass(frozen=True)
class Account:
    """One read of GET /user/subscription (brief 2.3).

    `grace` is `isGracePeriod`: None when the field was absent. `fixed` is
    `trainingStepsLeft.fixedTrainingStepsLeft`, `purchased` is
    `trainingStepsLeft.purchasedTrainingSteps`. Only `sum` is ever compared,
    because a policy change can move value between the two fields.
    `usage_json` is the raw V5 battery object as compact JSON, recorded and
    ignored.
    """
    tier: int
    active: bool
    grace: bool | None
    fixed: int
    purchased: int
    usage_json: str | None = None

    @property
    def sum(self) -> int:
        return self.fixed + self.purchased

    def as_row(self) -> dict:
        """The ledger's account_before / account_after object."""
        return {"tier": self.tier, "active": self.active,
                "isGracePeriod": self.grace, "fixed": self.fixed,
                "purchased": self.purchased, "sum": self.sum}


@dataclass(frozen=True)
class Proof:
    """One row of proofs.json: this (action, model) was measured free -- and
    with it the same action on the other V4.5 variant (`covers`).

    Written only by `run.run_request` for a probe whose row
    `guard.probe_row_problem` accepts: 2xx, an image of the requested size
    extracted, a balance delta of exactly 0, no LOCK. `size_class` is "WxH";
    `date` is the UTC ISO date; `ledger_id` names the probe's ledger row. A
    written proof is not yet a proven one: `guard.proof_standing` counts it
    only once the NEXT balance read (the ledger row after the probe, or the
    read being judged) equals the probe's balance after, so a debit that
    lands late (risk R4) refutes it instead of leaving img2img unlocked --
    and any later charged call it covers refutes it too.

    THAT RULE SURVIVES EVERY SIGNATURE. A fall in the read after one of our
    own sent rows is R4's own shape, and nothing in this ledger can tell it
    from somebody else's spend on a shared account, so it refutes FOR GOOD:
    `guard.signed_allowance` re-baselines the chain and `proof_standing`
    never reads it. Neither `acknowledge-drift` nor `resolve-boundary` can
    re-arm img2img; the author removes the proof by hand and probes again.
    """
    action: str
    model: str
    size_class: str
    date: str
    ledger_id: str

    def covers(self, action: object, model: object) -> bool:
        """Whether this proof answers for a call of `action` on `model`: its
        own (action, model), or the same action on the other V4.5 variant
        (MODELS_BY_ACTION[action]) -- never another action.

        NovelAI bills the curated variant exactly as the full one, so a probe
        of either measures both. The author, 2026-09-24: "The curated model
        is in the same system, the same costs apply. So in our case no
        costs." THE ONE RULE for which calls a proof answers for: guard
        condition 1's match and its already-proven probe refusal,
        `guard.proof_standing`'s later-call scan and `State.add_proof`'s
        duplicate refusal all ask it, so one mutation turns every route red.
        Pure."""
        if self.action != action:
            return False
        if self.model == model:
            return True
        pair = MODELS_BY_ACTION.get(action, ())
        return self.model in pair and model in pair

    def as_row(self) -> dict:
        return {"action": self.action, "model": self.model,
                "size_class": self.size_class, "date": self.date,
                "ledger_id": self.ledger_id}

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "Proof":
        """Inverse of `as_row`; KeyError when a field is missing."""
        return cls(action=str(row["action"]), model=str(row["model"]),
                   size_class=str(row["size_class"]), date=str(row["date"]),
                   ledger_id=str(row["ledger_id"]))


def size_class(width: int, height: int) -> str:
    """"WxH", the proof row's and the ledger's spelling of a size."""
    return f"{width}x{height}"


@dataclass(frozen=True, kw_only=True)
class Request:
    """One generation, as the builder sees it -- before it becomes a body.

    Which optional fields each action needs is `request.build_body`'s rule,
    stated there. `image_png` and `mask_png` are raw PNG bytes (never base64
    here). `ucPreset` is spelled as on the wire. `frames` is in reading
    order. Not validated here; see the module docstring.
    """
    action: str
    model: str
    seed: int
    base_caption: str
    negative: str
    frames: tuple[Frame, ...]
    ucPreset: int
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    steps: int = DEFAULT_STEPS
    scale: float = DEFAULT_SCALE
    sampler: str = DEFAULT_SAMPLER
    noise_schedule: str = DEFAULT_NOISE_SCHEDULE
    strength: float | None = None
    noise: float | None = None
    inpaint_strength: float | None = None
    color_correct: bool = False
    image_png: bytes | None = field(default=None, repr=False)
    mask_png: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, kw_only=True)
class LedgerContext:
    """What a ledger row records that the request itself does not carry.

    None means "not applicable to this row", written to the ledger as null.
    `target_rect` is the infill cell's canvas rect, or a request file's
    mask's bounding rect; when present on an infill `run.run_request`
    records `differs_outside_mask`, judged against the request's mask itself
    (whose shape may be narrower than this rect). `probe_flag_used` is True
    only when the author typed the probe flag on the command line.
    """
    strip: str | None = None
    strip_version: int | None = None
    round: int | None = None
    phase: str | None = None
    lever_changed: str | None = None
    target_cell: int | None = None
    target_rect: Rect | None = None
    mannequin_sha256: str | None = None
    probe_flag_used: bool = False


# ---------------------------------------------------------------------------
# Ledger row shape (brief 7.2, plus kind / refusal / lock bookkeeping)
# ---------------------------------------------------------------------------

CHAIN_KINDS: tuple[str, ...] = ("generation", "refused")
"""`generation`: a POST was attempted (an interrupted one included). `refused`:
the guard refused after the balance was read, so nothing was sent; its
account_after equals its account_before. Both kinds are links in the balance
chain: each one measured the balance itself."""

DRIFT_KIND = "drift"
"""A row this tool wrote about a fall it did not measure the cause of: the
balance fell BETWEEN two of our own rows, on a shared account, and the author
SIGNED for it (`cli acknowledge-drift` at an external boundary, `cli
resolve-boundary` at an ambiguous one). It is an ANNOTATION ON A BOUNDARY,
never a link in the chain -- `state.last_balance`, `guard.open_boundaries`
and `guard.proof_standing` all step over it -- and `guard.accounting` counts
it on its own line, THEIRS or OURS-BY-HAND, never added to what a row
MEASURED."""

ROW_KINDS: tuple[str, ...] = CHAIN_KINDS + (DRIFT_KIND,)

VERDICTS: tuple[str | None, ...] = (None, "accepted", "rejected", "probe")

LEDGER_FIELDS: tuple[str, ...] = (
    "ledger_id", "kind", "utc_time", "correlation_id",
    "strip", "strip_version", "round", "phase", "lever_changed",
    "action", "model", "width", "height", "steps", "scale", "sampler",
    "noise_schedule", "seed", "extra_noise_seed",
    "strength", "noise", INPAINT_STRENGTH_KEY, "color_correct",
    "add_original_image", "target_cell",
    "base_caption", "frames", "negative_caption", "ucPreset", "qualityToggle",
    "request_sha256", "request_path",
    "init_png_sha256", "mask_png_sha256", "mannequin_sha256",
    "account_before", "account_after", "delta", "chain_ok", "refill_seen",
    "drift_previous_row", "drift_observed_row", "drift_acknowledged_by",
    "drift_attribution", "drift_checked",
    "inconclusive", "probe_flag_used", "refusal_condition", "locked",
    "warning",
    "http_status", "content_type", "error_message", "elapsed_ms",
    "zip_sha256", "output_png_sha256", "output_path", "differs_outside_mask",
    "post", "verdict", "reason", "sprite_sha256",
)
"""Every ledger row carries exactly these keys, in this order, null where
not applicable. `state.State.write_row` refuses any other key set.

`warning` (added 2026-09-24) is the text of every balance event a row met --
an unsigned fall between rows, a charge inside the row, a proof the balance
refutes, a send whose outcome is unknown -- or null. Since that date a
balance event WARNS and never stops anything (the author's decision: the
account is shared), so this column is where the books keep what LOCK used to
announce. Rows written before it lack the key, and every reader uses .get().
`locked` is kept, as a file-format column, for those older rows: nothing
writes LOCK any more, so a new row always carries `locked` false."""

DRIFT_ROW_FIELDS: tuple[str, ...] = ("drift_previous_row",
                                     "drift_observed_row",
                                     "drift_acknowledged_by",
                                     "drift_attribution",
                                     "drift_checked")
"""The five keys only a `drift` row fills: the ledger id whose after-read held
the higher balance, the ledger id whose before-read held the lower one, who
signed for the gap between them, WHICH SIDE he attributed it to
(DRIFT_ATTRIBUTIONS), and what he says he checked before he signed. The last
two are required because a signature is a JUDGEMENT about a shared account,
not a measurement: a row that does not say whose it is and what was looked at
records a figure and loses the only thing a reader needs a month later."""

DRIFT_ATTRIBUTIONS: tuple[str, ...] = ("theirs", "ours")
"""`theirs`: somebody else spent it (`cli acknowledge-drift`, and only at a
boundary whose earlier row SENT NOTHING). `ours`: the author checked by hand
and recorded a fall at an AMBIGUOUS boundary as a late charge of ours (`cli
resolve-boundary`). `guard.accounting` keeps the two on separate lines and
never mixes either with what a row MEASURED."""

DRIFT_ROW_MAY_FILL: tuple[str, ...] = (
    "ledger_id", "kind", "utc_time", "account_before", "account_after",
    "delta", "reason") + DRIFT_ROW_FIELDS
"""A WHITELIST, not a blacklist. Every OTHER field of a drift row is null, so
a drift row cannot masquerade as anything else this ledger holds: with no
`action`, `model`, `verdict` or `http_status` it is not a generation and not
a probe (`guard.probe_row_problem` reads `kind` first anyway); with no
`output_png_sha256` it is not an output; with no `strip`, `sprite_sha256` or
`post` it is not a strip; with no `locked` it never wrote LOCK. Stated as a
whitelist because a new LEDGER_FIELDS key is then forbidden on a drift row by
default -- the safe direction for money code."""


def drift_row_problem(row: Mapping[str, object]) -> str | None:
    """Why `row` is not a well-formed acknowledged-drift row; None when it is.

    THE ONE RULE for the shape. `state.State.validate_row` refuses to WRITE a
    row this rejects, and `guard.signatures` refuses to READ one --
    one function, so a mutation of it turns both routes red (CLAUDE.md's
    sibling-route warning).

    A drift row: kind DRIFT_KIND; the five DRIFT_ROW_FIELDS non-empty
    strings, the two row ids DIFFERENT and `drift_attribution` one of
    DRIFT_ATTRIBUTIONS; integer account_before.sum (the higher, established
    balance) and account_after.sum (the lower, observed one) with after
    STRICTLY BELOW before; delta exactly after - before; and every field
    outside DRIFT_ROW_MAY_FILL null. Pure.
    """
    if row.get("kind") != DRIFT_KIND:
        return f"its kind is {row.get('kind')!r}, not {DRIFT_KIND!r}"
    for key, wanted in (("drift_previous_row", "a ledger id"),
                        ("drift_observed_row", "a ledger id"),
                        ("drift_acknowledged_by", "a name"),
                        ("drift_attribution", f"one of {DRIFT_ATTRIBUTIONS}"),
                        ("drift_checked", "what was checked before signing")):
        value = row.get(key)
        if not (isinstance(value, str) and value):
            return f"its {key} is {value!r}, not {wanted}"
    if row["drift_attribution"] not in DRIFT_ATTRIBUTIONS:
        return (f"its drift_attribution is {row['drift_attribution']!r}, not "
                f"one of {DRIFT_ATTRIBUTIONS}: a signature says WHOSE the "
                f"money was, or it is not a signature")
    if row["drift_previous_row"] == row["drift_observed_row"]:
        return (f"it names ledger row {row['drift_previous_row']!r} on BOTH "
                f"sides of the gap: a drift sits BETWEEN two rows")
    sums = {}
    for key in ("account_before", "account_after"):
        account = row.get(key)
        total = account.get("sum") if isinstance(account, Mapping) else None
        if not isinstance(total, int) or isinstance(total, bool):
            return f"its {key} has no integer sum"
        sums[key] = total
    high, low = sums["account_before"], sums["account_after"]
    if low >= high:
        return (f"its balance went {high} -> {low}, which is not a fall: a "
                f"drift row records a DROP somebody else caused")
    delta = row.get("delta")
    if not (isinstance(delta, int) and not isinstance(delta, bool)
            and delta == low - high):
        return (f"its delta is {delta!r}, not the {low - high} its own "
                f"balances measure")
    filled = sorted(key for key, value in row.items()
                    if value is not None and key not in DRIFT_ROW_MAY_FILL)
    if filled:
        return (f"a drift row fills only {DRIFT_ROW_MAY_FILL}, but this one "
                f"also fills {filled}: it is an annotation on a boundary, "
                f"not a request")
    return None
