"""Prompts and recipes: identity, captions, negatives, and request assembly.

OWNER: implementer B.

RESPONSIBILITY
--------------
Hold the example character (`IDENTITY`, brief 3.1), the three strip recipes
(`RECIPES`: walk, run, jump; brief 3.2-3.4), build those recipes for any
character file (`build_recipe`, `get_recipe(name, character=...)`), turn a
recipe plus computed centers into wire frames (`frames_for`), and assemble a
complete `model.Request` for one action (`make_request`) -- rendering the
mannequin, applying the author's strength default and band, and building the
infill mask and init.

INVARIANTS
----------
* RATING AND QUALITY ONLY AT THE END OF THE BASE CAPTION. Every base caption
  ends with model.QUALITY_TAIL, which ends with model.RATING_TAG; no
  character caption and no UC ever contains "rating:" (model.Recipe
  validates the recipe; `frames_for` re-asserts on what it builds).
* A CHARACTER CAPTION IS `<subject>, <ANCHOR>, from side, facing right,
  <POSE WORDS>`: it starts with the identity's own subject noun (`boy` or
  `girl`, model.Subject.noun), carries no count, no quality and no rating
  tag. The COUNT (`1boy`, `1girl`) is that same subject's count_tag and
  lives only in the base caption, which also fills every recipe sentence's
  `{noun}` from it -- one subject, three spellings, one source. The per-tag
  rule is characters.tag_problem, the same function a character file's tags
  and anchor are refused by, judged against that subject -- and
  `build_recipe` applies it again to the Identity it is handed, because an
  Identity built in code (`dataclasses.replace`) never passed the loader.
* A RECIPE FITS THE TOKEN BUDGET FOR EVERY RECIPE OR IS NOT BUILT.
  `build_recipe` counts words exactly as guard condition 7 does (guard's
  own `_WORD_RE`, model.TOKENS_PER_WORD, model.TOKEN_BUDGET) over the base
  caption and every character caption of EVERY recipe in RECIPE_NAMES, and
  refuses the identity when the worst one is over, naming the source and
  'tags' and 'anchor' -- so a character file that fits walk but not run is
  refused for walk too, before any request exists, instead of passing at
  load and failing at plan.
* A RECIPE IS BUILT FOR A CHARACTER. `get_recipe`, `make_request` and
  `context_for` take `character` (a file under tools/nai/characters/,
  default characters.DEFAULT_CHARACTER) and build the base caption, every
  character caption, the mannequin colours AND the garments it draws them
  on (`render_init(..., garments=recipe.identity.garments)`) from THAT
  file, on every call -- the default included -- so an outfit change is a
  data file, never an edit here. `RECIPES` is the same three recipes built for the `IDENTITY`
  literal; scout.json reproduces that literal exactly (tools/check_nai.py
  pins it), so the brief's caption pins hold for the default character. An
  unknown character raises, listing the files that exist.
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
  one go through the same `source_png`: a layout-sized PNG that is RGB, or
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
from types import MappingProxyType
from typing import Mapping, Sequence

from PIL import Image, UnidentifiedImageError

from tools.nai import characters, masks
from tools.nai.guard import _WORD_RE as WORD_RE
from tools.nai.mannequin import LAYOUTS, POSES, params_sha256, render_init
from tools.nai.model import (ACTIONS, DEFAULT_IMG2IMG_NOISE,
                             DEFAULT_INFILL_NOISE, DEFAULT_INPAINT_STRENGTH,
                             DEFAULT_SCALE, DEFAULT_STEPS, DEFAULT_STRENGTH,
                             INFILL_FULL_REPAINT, NEGATIVE, NOISE_RANGE,
                             QUALITY_TAIL, STRENGTH_BAND,
                             TOKEN_BUDGET, TOKENS_PER_WORD, UC_PRESET_NONE,
                             Frame, Identity, Layout, LedgerContext, Recipe,
                             Request, build_problem, garments_problem,
                             model_for, on_grid, rating_tag_in, subject)

OPAQUE_ALPHA_MIN = 254
"""An RGBA source counts as opaque when no alpha is below this. 254, not 255:
a generator that hides metadata in the alpha channel's low bit still sends an
opaque picture."""

# ---------------------------------------------------------------------------
# Identity (brief 3.1). The author changes an outfit with a character file,
# tools/nai/characters/<name>.json, never here: characters/scout.json is this
# literal, and tools/check_nai.py pins the two equal.
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

BASE_VIEWS = "multiple views, pixel art, sprite sheet, full body, from side"
"""What follows the count tag at the head of every base caption. The COUNT
itself is the identity's subject (model.Subject.count_tag, `1boy` or
`1girl`), written here and nowhere else."""
BASE_STYLE = ("simple background, grey background, limited palette, "
              "flat color, black outline")
CHARACTER_VIEW = "from side, facing right"

# NEGATIVE, every recipe's negative prompt, is imported from model: it is
# spelled there because characters.tag_problem refuses its tags.

# The sentences carry ONE `{noun}` each: the identity's subject noun, so
# "the same boy" and "the same girl" are one sentence, not two that can drift.
WALK_SENTENCE = (
    "a retro video game walk cycle: the same {noun} drawn five times in one "
    "row from left to right, four walking poses then one standing pose, every "
    "copy facing right, all feet on the same ground line")
RUN_SENTENCE = (
    "a retro video game run cycle: the same {noun} drawn six times in two "
    "rows of three, every copy facing right and leaning forward, the feet in "
    "each row on the same ground line")
JUMP_SENTENCE = (
    "a retro video game jump sequence: the same {noun} drawn five times in "
    "one row from left to right, crouching, leaping up, at the top of the "
    "jump, falling, landing, every copy facing right")

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


def _base(verb: str, sentence: str, identity: Identity) -> str:
    who = subject(identity.subject)
    return (f"{who.count_tag}, {BASE_VIEWS}, {verb}, {BASE_STYLE}, "
            f"{identity.tags}, {sentence.format(noun=who.noun)}, "
            f"{QUALITY_TAIL}")


def _caption_text(identity: Identity, pose_words: str) -> str:
    return (f"{subject(identity.subject).noun}, {identity.anchor}, "
            f"{CHARACTER_VIEW}, {pose_words}")


RECIPE_NAMES: tuple[str, ...] = ("walk", "run", "jump")

_RECIPE_WORDS: Mapping[str, tuple[str, str, tuple[str, ...]]] = \
    MappingProxyType({
        "walk": ("walking", WALK_SENTENCE,
                 (WALK_CONTACT, WALK_PASS, WALK_CONTACT, WALK_PASS,
                  WALK_IDLE)),
        "run": ("running", RUN_SENTENCE, (RUN_CONTACT, RUN_PASS,
                                          RUN_FLIGHT) * 2),
        "jump": ("jumping", JUMP_SENTENCE, JUMP_WORDS),
    })
"""Per recipe: (base-caption verb, sentence, pose words per frame) -- the
text `build_recipe` writes and `caption_words` counts, from ONE table."""


def caption_words(name: str, identity: Identity) -> int:
    """The words guard condition 7 counts for recipe `name` built for
    `identity`: guard's `_WORD_RE` over the base caption plus every character
    caption. KeyError for an unknown recipe name."""
    verb, sentence, pose_words = _RECIPE_WORDS[name]
    captions = [_base(verb, sentence, identity)] + [
        _caption_text(identity, words) for words in pose_words]
    return sum(len(WORD_RE.findall(text)) for text in captions)


def budget_problem(identity: Identity) -> str | None:
    """None when every recipe in RECIPE_NAMES built for `identity` fits
    model.TOKEN_BUDGET (TOKENS_PER_WORD * caption_words); otherwise the
    refusal text for the recipe with the most words."""
    worst = max(RECIPE_NAMES, key=lambda n: caption_words(n, identity))
    words = caption_words(worst, identity)
    tokens = TOKENS_PER_WORD * words
    if tokens <= TOKEN_BUDGET:
        return None
    frames = len(_RECIPE_WORDS[worst][2])
    return (f"recipe {worst} would carry {words} words ~ {tokens:g} tokens, "
            f"over the token budget of {TOKEN_BUDGET} (the tags once in its "
            f"base caption, the anchor in each of its {frames} frame "
            f"captions); every recipe is judged, so shorten 'tags' or "
            f"'anchor'")


def build_recipe(name: str, identity: Identity, source: str | None = None
                 ) -> Recipe:
    """Recipe `name` (one of RECIPE_NAMES) for `identity`: its tags in the
    base caption, its anchor in every character caption, its colours in the
    init. Everything else about a strip is the same for every character.

    ValueError for an unknown recipe name; for an identity whose `subject`
    is not one of model.SUBJECT_NAMES, whose `garments` are not legal
    (model.garments_problem) or whose `build` is not one of
    model.BUILD_NAMES (model.build_problem); for colours that are not exactly the parts
    those garments draw (characters.parts_problem); for a tag of
    identity.tags or identity.anchor that characters.tag_problem refuses --
    judged against THIS identity's subject; and for an identity
    `budget_problem` refuses -- each naming `source` (the character file)
    when given, else "identity".
    """
    if name not in RECIPE_NAMES:
        raise ValueError(f"unknown recipe {name!r}; legal: "
                         f"{', '.join(sorted(RECIPE_NAMES))}")
    where = "identity" if source is None else f"character file {source}"
    try:
        subject(identity.subject)
    except ValueError as exc:
        raise ValueError(f"{where}, field 'subject': {exc}") from exc
    garment_bad = garments_problem(identity.garments)
    if garment_bad is not None:
        raise ValueError(f"{where}, field 'garments': {garment_bad}")
    build_bad = build_problem(identity.build)
    if build_bad is not None:
        raise ValueError(f"{where}, field 'build': {build_bad}")
    parts_bad = characters.parts_problem(dict(identity.colours),
                                         identity.garments)
    if parts_bad is not None:
        raise ValueError(f"{where}, field 'colours': {parts_bad}")
    for field, text in (("tags", identity.tags), ("anchor", identity.anchor)):
        for tag in text.split(","):
            problem = characters.tag_problem(tag, identity.subject)
            if problem is not None:
                raise ValueError(
                    f"{where}, field {field!r}: "
                    f"{characters.tag_refusal(tag, problem, identity.subject)}")
    over = budget_problem(identity)
    if over is not None:
        raise ValueError(f"{where}, fields 'tags' and 'anchor': {over}")
    verb, sentence, pose_words = _RECIPE_WORDS[name]
    layout, fps_hint, hold_arc = {
        "walk": (LAYOUTS["L5"], 8, False),
        "run": (LAYOUTS["G6"], 12, False),
        "jump": (LAYOUTS["L5"], 10, True),
    }[name]
    return Recipe(
        name=name, layout=layout,
        base_caption=_base(verb, sentence, identity),
        negative=NEGATIVE,
        frame_poses=tuple(zip(pose_words, POSES[name])),
        identity=identity, fps_hint=fps_hint, hold_arc=hold_arc,
    )


RECIPES: Mapping[str, Recipe] = MappingProxyType({
    name: build_recipe(name, IDENTITY) for name in RECIPE_NAMES})
"""The default mapping: every recipe built for `IDENTITY`. fps_hint values
are DESIGN starting points for the sidecar, not research."""

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


def get_recipe(name: str, character: str = characters.DEFAULT_CHARACTER
               ) -> Recipe:
    """Recipe `name` built for the character file `character`:
    build_recipe(name, characters.load(character)).

    ValueError listing the recipe names when `name` is unknown -- judged
    first -- and listing the available character files when `character` is
    unknown; the file's own refusal when it is malformed; build_recipe's
    refusal, naming the file, when it is over the token budget.
    """
    if not isinstance(name, str) or name not in RECIPE_NAMES:
        raise ValueError(f"unknown recipe {name!r}; legal: "
                         f"{', '.join(sorted(RECIPE_NAMES))}")
    return build_recipe(name, characters.load(character),
                        source=characters.file_for(character))


def character_caption(identity: Identity, pose_words: str) -> str:
    """f"{subject noun}, {identity.anchor}, {CHARACTER_VIEW}, {pose_words}".

    The noun is model.subject(identity.subject).noun -- `boy` or `girl`, the
    same word the base caption counts.

    ValueError when pose_words carries a rating tag (model.rating_tag_in) or is
    not ASCII. The finished caption is checked as a whole too -- the anchor
    is author text and is the sibling route into the same caption -- so
    ValueError also when any tag of it fails
    `characters.tag_problem(tag, identity.subject)` (a control character, a
    rating, count, quality, view or negative tag, a rating word, or a word
    naming a subject other than this identity's; the noun this function
    writes is that subject's own, so a caption that opens with the wrong one
    is refused here).
    """
    if not isinstance(pose_words, str):
        raise ValueError(f"pose words must be a string, got {pose_words!r}")
    if rating_tag_in(pose_words):
        raise ValueError(f"a rating tag belongs only at the end of the base "
                         f"caption, not in pose words {pose_words!r}")
    if not pose_words.isascii():
        raise ValueError(f"pose words are not ASCII: {pose_words!r}")
    caption = _caption_text(identity, pose_words)
    if not caption.isascii():
        raise ValueError(f"character caption is not ASCII: {caption!r}")
    for tag in caption.split(","):
        problem = characters.tag_problem(tag, identity.subject)
        if problem is not None:
            raise ValueError(
                f"character caption "
                f"{characters.tag_refusal(tag, problem, identity.subject)}: "
                f"{caption!r}")
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


# THE VALUE RULES, ONE FUNCTION EACH. `make_request` applies them to a recipe
# and `spec.parse` to a request file, so a band, a range or a type is decided
# once and both routes refuse with the same sentence: the sibling route
# CLAUDE.md's ACTIVE WARNINGS count is a second copy of exactly these.

def steps_value(value: object) -> int:
    """`value` as the steps of a request: an int (never a bool). The cost cap
    of 28 is guard condition 4's, not this rule's."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"steps must be an int, got {value!r}")
    return value


def scale_value(value: object) -> float:
    """`value` as Prompt Guidance: a finite number above 0."""
    scale = _real("scale", value)
    if scale <= 0:
        raise ValueError(f"scale must be > 0, got {scale!r}")
    return scale


def noise_value(value: object) -> float:
    """`value` as img2img or infill noise: a finite number in NOISE_RANGE."""
    noise = _real("noise", value)
    if not NOISE_RANGE[0] <= noise <= NOISE_RANGE[1]:
        raise ValueError(f"noise must lie in {NOISE_RANGE}, got {noise!r}")
    return noise


def img2img_strength(value: object) -> float:
    """`value` as an img2img strength: inside the author's STRENGTH_BAND."""
    strength = _real("strength", value)
    if not _in_band(strength):
        raise ValueError(
            f"img2img strength {strength} is outside the author's band "
            f"{STRENGTH_BAND} (default {DEFAULT_STRENGTH})")
    return strength


def infill_strength(value: object) -> float:
    """`value` as an infill strength: inside the author's STRENGTH_BAND, or
    INFILL_FULL_REPAINT when the pose itself is wrong."""
    inpaint = _real("inpaint_strength", value)
    if not (_in_band(inpaint) or inpaint == INFILL_FULL_REPAINT):
        raise ValueError(
            f"infill strength {inpaint} is outside the author's band "
            f"{STRENGTH_BAND} and is not {INFILL_FULL_REPAINT} (full repaint)")
    return inpaint


def color_correct_value(value: object) -> bool:
    """`value` as img2img's color_correct: a bool, never a truthy stand-in."""
    if not isinstance(value, bool):
        raise ValueError(f"color_correct must be a bool, got {value!r}")
    return value


def _source_png(value: object, layout: Layout) -> bytes:
    """`source_png` at the layout's size."""
    return source_png(value, layout.width, layout.height)


def source_png(value: object, width: int, height: int) -> bytes:
    """The one source-image rule (module docstring): PNG bytes of exactly
    width x height, RGB as given, or RGBA with every alpha >=
    OPAQUE_ALPHA_MIN re-encoded as RGB. ValueError naming the problem
    otherwise. A request file's image passes it too (`spec`)."""
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"source_png must be PNG bytes, got "
                         f"{type(value).__name__}")
    data = bytes(value)
    want = (width, height)
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
            f"{width}x{height}, got {fmt} {mode} "
            f"{size[0]}x{size[1]}")
    return data


def make_request(recipe_name: str, action: str, seed: int, *,
                 character: str = characters.DEFAULT_CHARACTER,
                 **overrides: object) -> Request:
    """A complete Request for one strip and one action, for one character.

    Always: recipe = get_recipe(recipe_name, character); (init_png, centers) =
    mannequin.render_init(recipe.layout, recipe.poses,
    recipe.identity.as_dict(), garments=recipe.identity.garments,
    build_name=recipe.identity.build); frames =
    frames_for(recipe, centers); model
    = model.model_for(action, variant) with variant default "full"; ucPreset
    = UC_PRESET_NONE[model]; width/height from the layout; steps and scale
    default to model.DEFAULT_STEPS / DEFAULT_SCALE; base_caption and
    negative from the recipe.

    generate: no image, mask or strengths. Accepts variant, steps, scale.
    img2img:  image_png = source_png when given (a consistency re-pass on an
              accepted strip, brief 3.5; `source_png`'s rule), else
              init_png; strength (default DEFAULT_STRENGTH, must be in
              STRENGTH_BAND); noise (default DEFAULT_IMG2IMG_NOISE);
              color_correct (default False).
    infill:   source_png (REQUIRED: the accepted strip, `source_png`'s rule)
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
    the layout, source_png as `source_png`.
    """
    unknown = sorted(set(overrides) - OVERRIDE_KEYS)
    if unknown:
        raise TypeError(f"make_request() got unknown keyword(s) {unknown}; "
                        f"legal: {sorted(OVERRIDE_KEYS)}")
    recipe = get_recipe(recipe_name, character)
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; legal: {ACTIONS}")
    stray = sorted(set(overrides) - _ACTION_KEYS[action])
    if stray:
        raise ValueError(f"{stray} do not apply to {action}; it accepts "
                         f"{sorted(_ACTION_KEYS[action])}")

    variant = overrides.get("variant", "full")
    model = model_for(action, variant)  # type: ignore[arg-type]
    steps = steps_value(overrides.get("steps", DEFAULT_STEPS))
    scale = scale_value(overrides.get("scale", DEFAULT_SCALE))

    layout = recipe.layout
    init_png, centers = render_init(layout, recipe.poses,
                                    recipe.identity.as_dict(),
                                    garments=recipe.identity.garments,
                                    build_name=recipe.identity.build)
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
    noise = noise_value(overrides.get("noise", noise_default))

    if action == "img2img":
        strength = img2img_strength(
            overrides.get("strength", DEFAULT_STRENGTH))
        color_correct = color_correct_value(
            overrides.get("color_correct", False))
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
    inpaint = infill_strength(
        overrides.get("inpaint_strength", DEFAULT_INPAINT_STRENGTH))
    rect = layout.cells[cell].rect_canvas
    image_png = (masks.composite(source_png, init_png, rect) if paste
                 else source_png)
    return Request(**common, image_png=image_png,
                   mask_png=masks.cell_mask(layout, cell),
                   inpaint_strength=inpaint, noise=noise)


def context_for(recipe_name: str, *,
                character: str = characters.DEFAULT_CHARACTER,
                cell: int | None = None,
                strip_version: int | None = None, round: int | None = None,
                phase: str | None = None, lever_changed: str | None = None,
                probe_flag_used: bool = False) -> LedgerContext:
    """The LedgerContext for a request made from `recipe_name` for
    `character`.

    strip = recipe name; target_cell = cell; target_rect = the cell's
    rect_canvas when cell is not None; mannequin_sha256 =
    mannequin.params_sha256(layout, poses, the CHARACTER's colours, its
    garments and its build); the rest
    copied. The ledger has no character column: the row's base_caption names
    the outfit. ValueError for a cell that is not an int inside the recipe's
    layout, and for an unknown character (get_recipe).
    """
    recipe = get_recipe(recipe_name, character)
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
                                       recipe.identity.as_dict(),
                                       garments=recipe.identity.garments,
                                       build_name=recipe.identity.build),
        probe_flag_used=probe_flag_used,
    )

