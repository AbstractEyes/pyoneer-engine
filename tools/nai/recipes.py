"""Prompts and recipes: identity, captions, negatives, and request assembly.

OWNER: implementer B.

RESPONSIBILITY
--------------
Hold the example character (`IDENTITY`, brief 3.1), the three strip recipes
(`RECIPES`: walk, run, jump; brief 3.2-3.4), turn a recipe plus computed
centers into wire frames (`frames_for`), and assemble a complete
`model.Request` for one action (`make_request`) -- rendering the mannequin,
applying the author's strength default and band, and building the infill
mask and init.

INVARIANTS
----------
* RATING AND QUALITY ONLY AT THE END OF THE BASE CAPTION. Every base caption
  ends with model.QUALITY_TAIL, which ends with model.RATING_TAG; no
  character caption and no UC ever contains "rating:" (model.Recipe
  validates the recipe; `frames_for` re-asserts on what it builds).
* A CHARACTER CAPTION IS `boy, <ANCHOR>, from side, facing right, <POSE
  WORDS>`: it starts with boy/girl/other, carries no count, no quality and
  no rating tag. Count tags (`1boy`) live only in the base caption.
* CENTERS COME FROM `mannequin.render_init`, never from a literal, for every
  action -- generate included.
* STRENGTH (author): img2img `strength` defaults to model.DEFAULT_STRENGTH
  and must lie in the closed model.STRENGTH_BAND; infill
  `inpaint_strength` defaults to model.DEFAULT_INPAINT_STRENGTH and must lie
  in the band or equal model.INFILL_FULL_REPAINT. This band check lives
  HERE ONLY, so `plan` and `run` (both call make_request) share it.
  `guard.probe_request` deliberately does not come through here.
* NOISE AND SCALE ARE BOUNDED HERE TOO: noise in the closed
  model.NOISE_RANGE, scale > 0, for every action that takes them, so a typo
  is refused before `plan` or `run` builds anything.
* ONE SOURCE-IMAGE RULE. img2img's optional `source_png` (the consistency
  re-pass of brief 3.5, default the mannequin init) and infill's required
  one go through the same `_source_png`: a layout-sized PNG that is RGB, or
  RGBA whose every alpha is >= OPAQUE_ALPHA_MIN (converted to RGB). What
  `run` returns is stored exactly as NovelAI sent it, and a PNG carrying
  metadata in its alpha channel is still opaque; real transparency is
  refused, never flattened onto a guessed background.
* UC IS EMPTY BY DEFAULT (brief 3.3); lever L9 is not implemented by the
  contract.
* Cells 1/3 and 2/4 of the walk (and R1/R4, R2/R5, R3/R6 of the run) carry
  IDENTICAL pose words on purpose: which leg leads is carried only by the
  init image.
"""
from __future__ import annotations

import io
import math
import re
from types import MappingProxyType
from typing import Mapping, Sequence

from PIL import Image, UnidentifiedImageError

from tools.nai import masks
from tools.nai.mannequin import LAYOUTS, POSES, params_sha256, render_init
from tools.nai.model import (ACTIONS, DEFAULT_IMG2IMG_NOISE,
                             DEFAULT_INFILL_NOISE, DEFAULT_INPAINT_STRENGTH,
                             DEFAULT_SCALE, DEFAULT_STEPS, DEFAULT_STRENGTH,
                             INFILL_FULL_REPAINT, NOISE_RANGE, QUALITY_TAIL,
                             STRENGTH_BAND, UC_PRESET_NONE, Frame, Identity,
                             Layout, LedgerContext, Recipe, Request,
                             model_for, on_grid)

OPAQUE_ALPHA_MIN = 254
"""An RGBA source counts as opaque when no alpha is below this. 254, not 255:
a generator that hides metadata in the alpha channel's low bit still sends an
opaque picture."""

# ---------------------------------------------------------------------------
# Identity (brief 3.1; the author replaces these)
# ---------------------------------------------------------------------------

IDENTITY = Identity(
    tags="brown hair, short hair, red scarf, blue tunic, brown belt, "
         "tan pants, brown boots",
    anchor="brown hair, red scarf, blue tunic",
    colours=(
        ("skin", (0xE8, 0xB4, 0x8C)),
        ("hair", (0x6B, 0x42, 0x26)),
        ("scarf", (0xC8, 0x3C, 0x3C)),
        ("tunic", (0x3C, 0x64, 0xC8)),
        ("belt", (0x5A, 0x3A, 0x1E)),
        ("pants", (0xC8, 0xA0, 0x64)),
        ("boots", (0x7A, 0x4A, 0x24)),
    ),
)

# ---------------------------------------------------------------------------
# Caption pieces (brief 3.2-3.4)
# ---------------------------------------------------------------------------

BASE_HEAD = ("1boy, multiple views, pixel art, sprite sheet, full body, "
             "from side")
BASE_STYLE = ("simple background, grey background, limited palette, "
              "flat color, black outline")
CHARACTER_PREFIX = "boy"
CHARACTER_VIEW = "from side, facing right"

NEGATIVE = (
    "nsfw, lowres, artistic error, film grain, scan artifacts, worst quality, "
    "bad quality, jpeg artifacts, very displeasing, chromatic aberration, "
    "dithering, halftone, screentone, logo, too many watermarks, watermark, "
    "signature, text, blurry, 3d, realistic, gradient background, "
    "detailed background, scenery, shadow, cropped, out of frame, "
    "from behind, facing viewer"
)
"""V4.5 Full Heavy minus `multiple views`, `negative space`, `blank page`,
plus sprite negatives; `nsfw` first. Same text for Curated (ucPreset 3)."""

WALK_SENTENCE = (
    "a retro video game walk cycle: the same boy drawn five times in one row "
    "from left to right, four walking poses then one standing pose, every "
    "copy facing right, all feet on the same ground line")
RUN_SENTENCE = (
    "a retro video game run cycle: the same boy drawn six times in two rows "
    "of three, every copy facing right and leaning forward, the feet in each "
    "row on the same ground line")
JUMP_SENTENCE = (
    "a retro video game jump sequence: the same boy drawn five times in one "
    "row from left to right, crouching, leaping up, at the top of the jump, "
    "falling, landing, every copy facing right")

WALK_CONTACT = ("walking, mid-stride, legs apart, front heel on ground, "
                "arms swinging")
WALK_PASS = ("walking, passing pose, standing on one leg, other knee bent, "
             "legs close together")
WALK_IDLE = "standing, legs slightly apart, arms at sides"
RUN_CONTACT = ("running, leaning forward, legs spread wide, front heel "
               "touching ground, arms bent")
RUN_PASS = ("running, leaning forward, standing on one leg, other knee "
            "raised high, arms bent")
RUN_FLIGHT = ("running, leaning forward, midair, both feet off ground, "
              "legs split, arms bent")
JUMP_WORDS: tuple[str, ...] = (
    "crouching, knees bent, leaning forward, arms swung back",
    "jumping, midair, legs straight, toes pointed down, arms raised up",
    "jumping, midair, knees up, legs tucked, arms spread",
    "falling, midair, legs stretched down, arms raised",
    "landing, squatting, knees bent, arms forward",
)


def _base(verb: str, sentence: str) -> str:
    return (f"{BASE_HEAD}, {verb}, {BASE_STYLE}, {IDENTITY.tags}, "
            f"{sentence}, {QUALITY_TAIL}")


RECIPES: Mapping[str, Recipe] = MappingProxyType({
    "walk": Recipe(
        name="walk", layout=LAYOUTS["L5"],
        base_caption=_base("walking", WALK_SENTENCE), negative=NEGATIVE,
        frame_poses=tuple(zip(
            (WALK_CONTACT, WALK_PASS, WALK_CONTACT, WALK_PASS, WALK_IDLE),
            POSES["walk"])),
        identity=IDENTITY, fps_hint=8, hold_arc=False,
    ),
    "run": Recipe(
        name="run", layout=LAYOUTS["G6"],
        base_caption=_base("running", RUN_SENTENCE), negative=NEGATIVE,
        frame_poses=tuple(zip(
            (RUN_CONTACT, RUN_PASS, RUN_FLIGHT) * 2, POSES["run"])),
        identity=IDENTITY, fps_hint=12, hold_arc=False,
    ),
    "jump": Recipe(
        name="jump", layout=LAYOUTS["L5"],
        base_caption=_base("jumping", JUMP_SENTENCE), negative=NEGATIVE,
        frame_poses=tuple(zip(JUMP_WORDS, POSES["jump"])),
        identity=IDENTITY, fps_hint=10, hold_arc=True,
    ),
})
"""fps_hint values are DESIGN starting points for the sidecar, not research."""

OVERRIDE_KEYS: frozenset[str] = frozenset({
    "variant", "steps", "scale", "strength", "noise", "color_correct",
    "inpaint_strength", "source_png", "cell", "paste_mannequin",
})
"""Every keyword `make_request` accepts in **overrides."""

_ACTION_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "generate": frozenset({"variant", "steps", "scale"}),
    "img2img": frozenset({"variant", "steps", "scale", "strength", "noise",
                          "color_correct", "source_png"}),
    "infill": frozenset({"variant", "steps", "scale", "inpaint_strength",
                         "noise", "source_png", "cell", "paste_mannequin"}),
})
"""Which of OVERRIDE_KEYS apply to each action. Their union IS OVERRIDE_KEYS,
asserted below at import, so a key added to one and not the other raises
before any request is built."""

if frozenset().union(*_ACTION_KEYS.values()) != OVERRIDE_KEYS or set(
        _ACTION_KEYS) != set(ACTIONS):
    raise RuntimeError("recipes: _ACTION_KEYS disagrees with OVERRIDE_KEYS "
                       "or model.ACTIONS")

_COUNT_TAG = re.compile(r"\d+\s*(?:boy|girl|other)s?")
_QUALITY_TAGS: frozenset[str] = frozenset(
    t.strip() for t in QUALITY_TAIL.split(","))


def get_recipe(name: str) -> Recipe:
    """RECIPES[name]; ValueError listing the recipe names when unknown."""
    if not isinstance(name, str) or name not in RECIPES:
        raise ValueError(f"unknown recipe {name!r}; legal: "
                         f"{', '.join(sorted(RECIPES))}")
    return RECIPES[name]


def character_caption(identity: Identity, pose_words: str) -> str:
    """f"{CHARACTER_PREFIX}, {identity.anchor}, {CHARACTER_VIEW}, {pose_words}".

    ValueError when pose_words contains "rating:" or is not ASCII. The
    finished caption is checked as a whole too -- the anchor is author text
    and is the sibling route into the same caption -- so ValueError also when
    any tag of it carries "rating:", is a count tag (`1boy`, `2girls`), or is
    one of QUALITY_TAIL's tags.
    """
    if not isinstance(pose_words, str):
        raise ValueError(f"pose words must be a string, got {pose_words!r}")
    if "rating:" in pose_words:
        raise ValueError(f"a rating tag belongs only at the end of the base "
                         f"caption, not in pose words {pose_words!r}")
    if not pose_words.isascii():
        raise ValueError(f"pose words are not ASCII: {pose_words!r}")
    caption = (f"{CHARACTER_PREFIX}, {identity.anchor}, {CHARACTER_VIEW}, "
               f"{pose_words}")
    if not caption.isascii():
        raise ValueError(f"character caption is not ASCII: {caption!r}")
    for tag in (t.strip() for t in caption.split(",")):
        if "rating:" in tag:
            raise ValueError(f"character caption carries a rating tag "
                             f"{tag!r}: {caption!r}")
        if _COUNT_TAG.fullmatch(tag):
            raise ValueError(f"character caption carries a count tag "
                             f"{tag!r}; counts live in the base caption only")
        if tag in _QUALITY_TAGS:
            raise ValueError(f"character caption carries the quality tag "
                             f"{tag!r}; quality lives in the base caption only")
    return caption


def frames_for(recipe: Recipe, centers: Sequence[tuple[float, float]]
               ) -> tuple[Frame, ...]:
    """One Frame per cell: character_caption(recipe.identity, words), uc "",
    center = centers[i] (as a tuple of two floats).

    ValueError when len(centers) != recipe.layout.count, or a center is not
    two model.GRID values, or two centers are equal. Order = cell order.
    """
    centers = list(centers)
    if len(centers) != recipe.layout.count:
        raise ValueError(f"recipe {recipe.name}: {len(centers)} centers for "
                         f"a {recipe.layout.count}-cell layout")
    frames: list[Frame] = []
    seen: dict[tuple[float, float], int] = {}
    for i, (words, center) in enumerate(zip(recipe.pose_words, centers)):
        if (not isinstance(center, (tuple, list)) or len(center) != 2
                or not all(on_grid(v) for v in center)):
            raise ValueError(f"recipe {recipe.name}: center {i} {center!r} is "
                             f"not two grid values")
        c = (float(center[0]), float(center[1]))
        if c in seen:
            raise ValueError(f"recipe {recipe.name}: frames {seen[c]} and {i} "
                             f"share the center {c}")
        seen[c] = i
        frames.append(Frame(caption=character_caption(recipe.identity, words),
                            uc="", center=c))
    return tuple(frames)


def _real(key: str, value: object) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"{key} must be a finite number, got {value!r}")
    return float(value)


def _in_band(value: float) -> bool:
    return STRENGTH_BAND[0] <= value <= STRENGTH_BAND[1]


def _source_png(value: object, layout: Layout) -> bytes:
    """The one source-image rule (module docstring): PNG bytes of the
    layout's size, RGB as given, or RGBA with every alpha >= OPAQUE_ALPHA_MIN
    re-encoded as RGB. ValueError naming the problem otherwise."""
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"source_png must be PNG bytes, got "
                         f"{type(value).__name__}")
    data = bytes(value)
    want = (layout.width, layout.height)
    try:
        with Image.open(io.BytesIO(data)) as src:
            fmt, mode, size = src.format, src.mode, src.size
            if fmt == "PNG" and mode == "RGBA" and size == want:
                src.load()
                lowest = src.getchannel("A").getextrema()[0]
                if lowest < OPAQUE_ALPHA_MIN:
                    raise ValueError(
                        f"source_png is RGBA with transparent pixels (alpha "
                        f"down to {lowest}); it must be opaque, and a "
                        f"transparent area is refused rather than flattened "
                        f"onto a guessed background")
                buffer = io.BytesIO()
                src.convert("RGB").save(buffer, format="PNG")
                return buffer.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"source_png is not a readable image: {exc}") from exc
    if fmt != "PNG" or mode != "RGB" or size != want:
        raise ValueError(
            f"source_png must be an RGB (or opaque RGBA) PNG of "
            f"{layout.width}x{layout.height}, got {fmt} {mode} "
            f"{size[0]}x{size[1]}")
    return data


def make_request(recipe_name: str, action: str, seed: int,
                 **overrides: object) -> Request:
    """A complete Request for one strip and one action.

    Always: recipe = get_recipe(recipe_name); (init_png, centers) =
    mannequin.render_init(recipe.layout, recipe.poses,
    recipe.identity.as_dict()); frames = frames_for(recipe, centers); model
    = model.model_for(action, variant) with variant default "full"; ucPreset
    = UC_PRESET_NONE[model]; width/height from the layout; steps and scale
    default to model.DEFAULT_STEPS / DEFAULT_SCALE; base_caption and
    negative from the recipe.

    generate: no image, mask or strengths. Accepts variant, steps, scale.
    img2img:  image_png = source_png when given (a consistency re-pass on an
              accepted strip, brief 3.5; `_source_png`'s rule), else
              init_png; strength (default DEFAULT_STRENGTH, must be in
              STRENGTH_BAND); noise (default DEFAULT_IMG2IMG_NOISE);
              color_correct (default False).
    infill:   source_png (REQUIRED: the accepted strip, `_source_png`'s rule)
              and cell (REQUIRED: 0-based index); mask_png =
              masks.cell_mask(layout, cell); image_png = source_png with
              cell's rect replaced by init_png's (masks.composite) when
              paste_mannequin (default True), else source_png unchanged;
              inpaint_strength (default DEFAULT_INPAINT_STRENGTH, band or
              INFILL_FULL_REPAINT); noise (default DEFAULT_INFILL_NOISE).

    TypeError for a keyword not in OVERRIDE_KEYS; ValueError for a keyword
    that does not apply to `action` (e.g. strength on generate), a strength
    outside its rule, or a missing infill requirement. Seed range and cost
    rules are NOT checked here (request.build_body and guard do that).
    Value TYPES are checked here, as ValueError: steps an int, scale /
    strength / noise finite numbers, scale > 0, noise inside the closed
    NOISE_RANGE, color_correct and paste_mannequin bools, cell an int inside
    the layout, source_png as `_source_png`.
    """
    unknown = sorted(set(overrides) - OVERRIDE_KEYS)
    if unknown:
        raise TypeError(f"make_request() got unknown keyword(s) {unknown}; "
                        f"legal: {sorted(OVERRIDE_KEYS)}")
    recipe = get_recipe(recipe_name)
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; legal: {ACTIONS}")
    stray = sorted(set(overrides) - _ACTION_KEYS[action])
    if stray:
        raise ValueError(f"{stray} do not apply to {action}; it accepts "
                         f"{sorted(_ACTION_KEYS[action])}")

    variant = overrides.get("variant", "full")
    model = model_for(action, variant)  # type: ignore[arg-type]
    steps = overrides.get("steps", DEFAULT_STEPS)
    if not isinstance(steps, int) or isinstance(steps, bool):
        raise ValueError(f"steps must be an int, got {steps!r}")
    scale = _real("scale", overrides.get("scale", DEFAULT_SCALE))
    if scale <= 0:
        raise ValueError(f"scale must be > 0, got {scale!r}")

    layout = recipe.layout
    init_png, centers = render_init(layout, recipe.poses,
                                    recipe.identity.as_dict())
    common = dict(
        action=action, model=model, seed=seed,
        base_caption=recipe.base_caption, negative=recipe.negative,
        frames=frames_for(recipe, centers), ucPreset=UC_PRESET_NONE[model],
        width=layout.width, height=layout.height, steps=steps, scale=scale,
    )
    if action == "generate":
        return Request(**common)

    noise_default = (DEFAULT_IMG2IMG_NOISE if action == "img2img"
                     else DEFAULT_INFILL_NOISE)
    noise = _real("noise", overrides.get("noise", noise_default))
    if not NOISE_RANGE[0] <= noise <= NOISE_RANGE[1]:
        raise ValueError(f"noise must lie in {NOISE_RANGE}, got {noise!r}")

    if action == "img2img":
        strength = _real("strength",
                         overrides.get("strength", DEFAULT_STRENGTH))
        if not _in_band(strength):
            raise ValueError(
                f"img2img strength {strength} is outside the author's band "
                f"{STRENGTH_BAND} (default {DEFAULT_STRENGTH})")
        color_correct = overrides.get("color_correct", False)
        if not isinstance(color_correct, bool):
            raise ValueError(f"color_correct must be a bool, got "
                             f"{color_correct!r}")
        image_png = (_source_png(overrides["source_png"], layout)
                     if "source_png" in overrides else init_png)
        return Request(**common, image_png=image_png, strength=strength,
                       noise=noise, color_correct=color_correct)

    # infill
    if "source_png" not in overrides:
        raise ValueError("infill needs source_png: the accepted strip")
    if "cell" not in overrides:
        raise ValueError("infill needs cell: the 0-based index to repaint")
    source_png = _source_png(overrides["source_png"], layout)
    cell = overrides["cell"]
    if (not isinstance(cell, int) or isinstance(cell, bool)
            or not 0 <= cell < layout.count):
        raise ValueError(f"cell must be an int in 0..{layout.count - 1} for "
                         f"{recipe.name}, got {cell!r}")
    paste = overrides.get("paste_mannequin", True)
    if not isinstance(paste, bool):
        raise ValueError(f"paste_mannequin must be a bool, got {paste!r}")
    inpaint = _real("inpaint_strength",
                    overrides.get("inpaint_strength", DEFAULT_INPAINT_STRENGTH))
    if not (_in_band(inpaint) or inpaint == INFILL_FULL_REPAINT):
        raise ValueError(
            f"infill strength {inpaint} is outside the author's band "
            f"{STRENGTH_BAND} and is not {INFILL_FULL_REPAINT} (full repaint)")
    rect = layout.cells[cell].rect_canvas
    image_png = (masks.composite(source_png, init_png, rect) if paste
                 else source_png)
    return Request(**common, image_png=image_png,
                   mask_png=masks.cell_mask(layout, cell),
                   inpaint_strength=inpaint, noise=noise)


def context_for(recipe_name: str, *, cell: int | None = None,
                strip_version: int | None = None, round: int | None = None,
                phase: str | None = None, lever_changed: str | None = None,
                probe_flag_used: bool = False) -> LedgerContext:
    """The LedgerContext for a request made from `recipe_name`.

    strip = recipe name; target_cell = cell; target_rect = the cell's
    rect_canvas when cell is not None; mannequin_sha256 =
    mannequin.params_sha256(layout, poses, identity colours); the rest copied.
    ValueError for a cell that is not an int inside the recipe's layout.
    """
    recipe = get_recipe(recipe_name)
    rect = None
    if cell is not None:
        if (not isinstance(cell, int) or isinstance(cell, bool)
                or not 0 <= cell < recipe.layout.count):
            raise ValueError(f"cell must be an int in 0.."
                             f"{recipe.layout.count - 1} for {recipe.name}, "
                             f"got {cell!r}")
        rect = recipe.layout.cells[cell].rect_canvas
    return LedgerContext(
        strip=recipe.name, strip_version=strip_version, round=round,
        phase=phase, lever_changed=lever_changed, target_cell=cell,
        target_rect=rect,
        mannequin_sha256=params_sha256(recipe.layout, recipe.poses,
                                       recipe.identity.as_dict()),
        probe_flag_used=probe_flag_used,
    )

