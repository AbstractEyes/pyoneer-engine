"""Requests described by a file: how a tool that composes a request, but must
never send one, hands it to this package.

OWNER: the author writes the file, through a composing tool -- the Pioneer
Pixel Editor writes one for each selection it sends. This module refuses a
bad file and turns a good one into the `model.Request` and
`model.LedgerContext` every other route builds. It opens no socket, reads no
environment variable and writes no file.

    editor/requests/0012-nai-garet-head/request.json      (gitignored)
    {
      "format": "pyoneer.nai.request", "version": 1,
      "label": "~Garet.png 44x64 at (44, 0), x8",
      "action": "img2img", "variant": "full",
      "width": 384, "height": 512, "seed": 1234567, "steps": 23, "scale": 5,
      "prompt": "pixel art, 1boy, full body, from side, grey background",
      "negative": "nsfw, lowres, ...",
      "characters": [{"prompt": "boy, brown hair, red scarf", "uc": "",
                      "center": [0.5, 0.5]}],
      "image": "init.png", "strength": 0.45, "noise": 0.05,
      "color_correct": false,
      "source": {"app": "pioneer-pixel-editor", "rect": [44, 0, 44, 64]}
    }

WHY A FILE, AND WHY THROUGH HERE
--------------------------------
This package is the only NovelAI client the project has, and that is what
keeps the books: one guard, one ledger, one LOCK. A second client -- an
editor with its own HTTP call on the same login -- spends where
`guard.chain_verdict` can see only an unexplained fall between two of our
rows (docs/NAI_SPRITES.md, "The books"). So a tool that wants to send what
no recipe draws -- a slice of an image, cut from its selection -- writes the
request as DATA, and a human runs it:

    python -m tools.nai plan-request FILE    no network: the guard's verdicts
    python -m tools.nai run-request FILE     ONE request, via run.run_request

What `load` returns passes the same builder (`request.build_body`), the same
guard (`guard.evaluate`, `guard.assert_free`) and the same send
(`run.run_request`) as a recipe, and it decides nothing the guard decides:
29 steps, 1,048,577 px, a width off the 64 px grid and img2img with no proof
all BUILD here and are refused THERE, by condition number, exactly as they
are for a recipe.

WHAT THIS MODULE DOES DECIDE: WHAT A FILE MAY SAY
-------------------------------------------------
* ONE DECODE RULE. `characters.strict_json`: UTF-8, valid JSON, no key
  written twice at any depth. Then one object, `format` and `version`
  exactly, every REQUIRED key, and no key outside FIELDS.
* THE TAIL IS OURS. `prompt` is the author's positive text WITHOUT the
  quality tail; this module appends ", " + model.QUALITY_TAIL, so
  rating:general closes every base caption, the author's standing choice.
  A prompt that already carries a rating tag is refused, never doubled.
* EACH ACTION'S KEYS, WRITTEN OUT, AND ONLY THEM (ACTION_KEYS). img2img
  needs image, strength, noise and color_correct; infill needs image, mask,
  inpaint_strength and noise; generate carries none of them. Nothing is
  defaulted: a file that says less than the request it asks for is refused
  (law 7), and one that says more is refused rather than half-read.
* THE AUTHOR'S BANDS, BY THE RECIPES' OWN FUNCTIONS: `recipes.steps_value`,
  `scale_value`, `noise_value`, `img2img_strength`, `infill_strength` and
  `color_correct_value`. One rule, two routes, one sentence.
* THE IMAGES. `image` and `mask` each name a file BESIDE the request file --
  a bare name, no directory part -- or carry BASE64_PREFIX and the PNG
  itself. The image passes `recipes.source_png`, the one source-image rule:
  RGB, or opaque RGBA re-encoded as RGB, of exactly width x height. A
  transparent pixel is refused and never flattened onto a guessed
  background, so a composing tool keys transparency itself, onto
  model.BACKGROUND_RGB. The mask passes `masks.region_of`: white on black,
  alpha 255, any shape made of whole model.MASK_ALIGN latent blocks (a head
  and a margin, two rectangles), which is the shape NovelAI repaints; the
  whole image goes with it. `run-request` composites locally inside that
  shape and the ledger records `differs_outside_mask` against it.
* THE CHARACTERS. 1 to model.MAX_FRAMES objects of exactly `prompt`, `uc`
  and `center`, each center two numbers exactly on model.GRID, no two
  alike, and no rating tag in any of them. Refused here in the file's own
  words; guard condition 6 judges the built body again.
* NO SAMPLER, NO SCHEDULE, NO FIXED PARAMETER. The file route sends
  model.DEFAULT_SAMPLER / DEFAULT_NOISE_SCHEDULE and request.FIXED_PARAMETERS
  exactly as every recipe does: the one configuration the research measured
  (brief 1.5). A key for any of them is an unknown key.
* `source` is the composing tool's own memory of where the request came
  from. It must be an object; it is never sent and never judged further.

THE LEDGER
----------
`Spec.context` is a LedgerContext with strip None -- a request file is not a
recipe strip, as a probe is not -- round, phase and lever from the file, and
for infill target_rect = the mask's bounding rectangle, so `run.run_request`
records `differs_outside_mask` (against the mask's own shape, the request's
mask_png).

THE FORM
--------
`FORM` is NovelAI's form in NovelAI's order, as THIS route fills it: which
control a composing tool lets the author set, which it caps, which it
derives and which it shows locked, and why, in sentences a tool prints
verbatim. Every number in it is formatted from `model`, never retyped. It is
the recipe route's `tools/nai_ui/request_pane.NAI_FIELDS` restated for a
route whose prompt, characters and positions are the author's own.
`catalog()` is that table with every limit and default a composing tool
needs; `python -m tools.nai request-catalog` prints it as JSON, and the
Pioneer Pixel Editor generates its design/novelai.json from that output.
"""
from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, NamedTuple

from tools.nai import characters, masks, recipes
from tools.nai.guard import _WORD_RE as WORD_RE
from tools.nai.model import (ACTIONS, BACKGROUND_RGB, DEFAULT_IMG2IMG_NOISE,
                             DEFAULT_INFILL_NOISE, DEFAULT_INPAINT_STRENGTH,
                             DEFAULT_NOISE_SCHEDULE, DEFAULT_SAMPLER,
                             DEFAULT_SCALE, DEFAULT_STEPS, DEFAULT_STRENGTH,
                             DIM_MULTIPLE, GRID, INFILL_FULL_REPAINT, INIT_K,
                             MASK_ALIGN, MAX_AREA, MAX_FRAMES, MAX_STEPS,
                             MIN_DIM, MODELS_BY_ACTION, NEGATIVE, NOISE_RANGE,
                             QUALITY_TAIL, SEED_MAX, SEED_MIN,
                             STRENGTH_BAND, TOKEN_BUDGET, TOKENS_PER_WORD,
                             UC_PRESET_NONE, VARIANTS, Frame, LedgerContext,
                             Rect, Request, model_for, on_grid,
                             rating_tag_in)

FORMAT = "pyoneer.nai.request"
VERSION = 1
BASE64_PREFIX = "base64:"
"""An `image` or `mask` value that carries the PNG itself: this prefix, then
standard base64 with no line breaks. A tool that cannot write a file beside
the request (a browser with no folder to write into) sends one file."""

REQUIRED: tuple[str, ...] = (
    "format", "version", "action", "variant", "width", "height", "seed",
    "steps", "scale", "prompt", "negative", "characters",
)
ACTION_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "generate": (),
    "img2img": ("image", "strength", "noise", "color_correct"),
    "infill": ("image", "mask", "inpaint_strength", "noise"),
})
"""Per action, the keys a file for it must write, and the only image keys it
may write. `request.build_body`'s per-action field rule, stated for a file."""
OPTIONAL: tuple[str, ...] = ("label", "source", "round", "phase", "lever")
IMAGE_KEYS: tuple[str, ...] = tuple(sorted(
    {key for keys in ACTION_KEYS.values() for key in keys}))
FIELDS: tuple[str, ...] = REQUIRED + IMAGE_KEYS + OPTIONAL
CHARACTER_KEYS: tuple[str, ...] = ("prompt", "uc", "center")
TRAILING = ", \t\n\r"
"""What is stripped from the end of `prompt` before the tail is appended:
commas and whitespace, in any order, so "a, b ,  " still gives "a, b, "
+ the tail and never ", , "."""


def _refused(source: str, key: str | None, message: str) -> ValueError:
    where = (f"request file {source}, key {key!r}" if key is not None
             else f"request file {source}")
    return ValueError(f"{where}: {message}")


@dataclass(frozen=True)
class Spec:
    """One request file, read and judged.

    `request` and `context` go to `run.run_request` unchanged. `label` is the
    file's own name for itself ("" when it wrote none). `mask_rect` is the
    infill rectangle (None for the other actions), for the local composite.
    """
    source: str
    label: str
    request: Request
    context: LedgerContext
    mask_rect: Rect | None


def load(path: str) -> Spec:
    """`parse` of the file at `path`, its images read from beside it."""
    source = os.path.normpath(path)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise _refused(source, None, f"cannot be read: {exc}") from exc
    return parse(raw, source, os.path.dirname(os.path.abspath(path)))


def _int(doc: Mapping[str, object], key: str, source: str, *,
         low: int | None = None, high: int | None = None) -> int:
    value = doc[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _refused(source, key, f"must be an int, got {value!r}")
    if low is not None and value < low or high is not None and value > high:
        bound = (f"lie in [{low}, {high}]" if high is not None
                 else f"be >= {low}")
        raise _refused(source, key, f"must {bound}, got {value}")
    return value


def _text(doc: Mapping[str, object], key: str, source: str, *,
          blank: bool) -> str:
    value = doc[key]
    if not isinstance(value, str):
        raise _refused(source, key, f"must be a string, got {value!r}")
    if not blank and not value.strip():
        raise _refused(source, key, "must say something; it is empty")
    return value


def _rule(rule, value: object, key: str, source: str):
    """One of the recipes' value rules, its refusal naming this file."""
    try:
        return rule(value)
    except ValueError as exc:
        raise _refused(source, key, str(exc)) from exc


def _png(value: object, key: str, source: str, directory: str) -> bytes:
    """The bytes an `image` or `mask` value names: a bare file name beside
    the request file, or BASE64_PREFIX and the PNG."""
    if not isinstance(value, str) or not value:
        raise _refused(source, key, f"must name a PNG beside the request "
                                    f"file, or carry {BASE64_PREFIX!r} and "
                                    f"the PNG; got {value!r}")
    if value.startswith(BASE64_PREFIX):
        try:
            return base64.b64decode(value[len(BASE64_PREFIX):], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _refused(source, key, f"is not valid base64: {exc}") from exc
    if (os.path.basename(value) != value or "/" in value or "\\" in value
            or value in (".", "..")):
        raise _refused(source, key, f"{value!r} is not a bare file name: an "
                                    f"image lives beside the request file, "
                                    f"so a path cannot point anywhere else")
    try:
        with open(os.path.join(directory, value), "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _refused(source, key, f"{value!r} cannot be read beside the "
                                    f"request file: {exc}") from exc


def _characters(doc: Mapping[str, object], source: str) -> tuple[Frame, ...]:
    listed = doc["characters"]
    if not isinstance(listed, list) or not 1 <= len(listed) <= MAX_FRAMES:
        raise _refused(source, "characters",
                       f"must be a list of 1 to {MAX_FRAMES} characters, "
                       f"got {listed!r}"[:400])
    frames: list[Frame] = []
    for index, entry in enumerate(listed):
        where = f"characters[{index}]"
        if not isinstance(entry, dict) or set(entry) != set(CHARACTER_KEYS):
            raise _refused(source, where,
                           f"must be an object of exactly "
                           f"{list(CHARACTER_KEYS)}, got {entry!r}"[:400])
        prompt, uc, center = entry["prompt"], entry["uc"], entry["center"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise _refused(source, where, f"'prompt' must be a string that "
                                          f"says something, got {prompt!r}")
        if not isinstance(uc, str):
            raise _refused(source, where, f"'uc' must be a string, got "
                                          f"{uc!r}")
        for text, name in ((prompt, "prompt"), (uc, "uc")):
            if rating_tag_in(text):
                raise _refused(source, where,
                               f"'{name}' carries a rating tag; the one "
                               f"rating tag closes the base caption and "
                               f"tools.nai writes it")
        if (not isinstance(center, list) or len(center) != 2
                or not all(on_grid(value) for value in center)):
            raise _refused(source, where,
                           f"'center' must be [x, y], each exactly one of "
                           f"{list(GRID)}, got {center!r}")
        point = (float(center[0]), float(center[1]))
        for other, earlier in enumerate(frames):
            if earlier.center == point:
                raise _refused(source, where,
                               f"shares the center {list(point)} with "
                               f"characters[{other}]; NovelAI places one "
                               f"character per cell of the 5x5 grid")
        frames.append(Frame(caption=prompt, uc=uc, center=point))
    return tuple(frames)


def parse(raw: bytes, source: str, directory: str) -> Spec:
    """The Spec a request file's bytes describe, by the module docstring's
    rules. ValueError naming `source` and the key otherwise. `directory` is
    where a bare image name is read from: the request file's own folder."""
    doc = characters.strict_json(raw, lambda key, message:
                                 _refused(source, key, message))
    if not isinstance(doc, dict):
        raise _refused(source, None, f"must be one JSON object, got "
                                     f"{type(doc).__name__}")
    unknown = sorted(set(doc) - set(FIELDS))
    if unknown:
        raise _refused(source, unknown[0],
                       f"unknown key(s) {unknown}: a request file holds "
                       f"{list(REQUIRED)}, its action's keys "
                       f"{ {a: list(k) for a, k in ACTION_KEYS.items()} } "
                       f"and optionally {list(OPTIONAL)}")
    missing = [key for key in REQUIRED if key not in doc]
    if missing:
        raise _refused(source, missing[0], f"missing key(s) {missing}")
    if doc["format"] != FORMAT:
        raise _refused(source, "format", f"must be {FORMAT!r}, got "
                                         f"{doc['format']!r}")
    version = _int(doc, "version", source)
    if version != VERSION:
        raise _refused(source, "version", f"this tool reads version "
                                          f"{VERSION}, got {version}")
    action = doc["action"]
    if action not in ACTIONS:
        raise _refused(source, "action", f"must be one of {list(ACTIONS)}, "
                                         f"got {action!r}")
    wanted = ACTION_KEYS[action]
    stray = sorted(key for key in IMAGE_KEYS if key in doc and
                   key not in wanted)
    if stray:
        raise _refused(source, stray[0],
                       f"{stray} do not belong to {action}, which takes "
                       f"{list(wanted) or 'no image keys'}")
    lacking = [key for key in wanted if key not in doc]
    if lacking:
        raise _refused(source, lacking[0],
                       f"{action} needs {list(wanted)}, written out: nothing "
                       f"is defaulted from a file; missing {lacking}")
    variant = doc["variant"]
    if variant not in VARIANTS:
        raise _refused(source, "variant", f"must be one of {list(VARIANTS)}, "
                                          f"got {variant!r}")

    width = _int(doc, "width", source, low=1)
    height = _int(doc, "height", source, low=1)
    seed = _int(doc, "seed", source, low=SEED_MIN, high=SEED_MAX)
    steps = _rule(recipes.steps_value, doc["steps"], "steps", source)
    scale = _rule(recipes.scale_value, doc["scale"], "scale", source)

    prompt = _text(doc, "prompt", source, blank=False)
    if rating_tag_in(prompt):
        raise _refused(source, "prompt",
                       f"carries a rating tag; tools.nai appends "
                       f"{QUALITY_TAIL!r}, which closes the base caption with "
                       f"the one rating tag, so the prompt holds none")
    base = prompt.rstrip(TRAILING).strip()
    if not base:
        raise _refused(source, "prompt", "is nothing but commas")
    negative = _text(doc, "negative", source, blank=True)
    frames = _characters(doc, source)

    label = doc.get("label", "")
    if not isinstance(label, str):
        raise _refused(source, "label", f"must be a string, got {label!r}")
    if "source" in doc and not isinstance(doc["source"], dict):
        raise _refused(source, "source", f"must be an object, got "
                                         f"{type(doc['source']).__name__}")
    round_ = _int(doc, "round", source, low=0) if "round" in doc else None
    phase = _text(doc, "phase", source, blank=False) if "phase" in doc \
        else None
    lever = _text(doc, "lever", source, blank=False) if "lever" in doc \
        else None

    model = model_for(action, variant)
    fields: dict = dict(
        action=action, model=model, seed=seed,
        base_caption=f"{base}, {QUALITY_TAIL}", negative=negative,
        frames=frames, ucPreset=UC_PRESET_NONE[model],
        width=width, height=height, steps=steps, scale=scale,
        sampler=DEFAULT_SAMPLER, noise_schedule=DEFAULT_NOISE_SCHEDULE)
    rect: Rect | None = None
    if action == "img2img":
        image = _png(doc["image"], "image", source, directory)
        fields.update(
            image_png=_rule(lambda v: recipes.source_png(v, width, height),
                            image, "image", source),
            strength=_rule(recipes.img2img_strength, doc["strength"],
                           "strength", source),
            noise=_rule(recipes.noise_value, doc["noise"], "noise", source),
            color_correct=_rule(recipes.color_correct_value,
                                doc["color_correct"], "color_correct",
                                source))
    elif action == "infill":
        image = _png(doc["image"], "image", source, directory)
        mask = _png(doc["mask"], "mask", source, directory)
        rect = _rule(lambda v: masks.region_of(v, (width, height)), mask,
                     "mask", source)
        fields.update(
            image_png=_rule(lambda v: recipes.source_png(v, width, height),
                            image, "image", source),
            mask_png=mask,
            inpaint_strength=_rule(recipes.infill_strength,
                                   doc["inpaint_strength"],
                                   "inpaint_strength", source),
            noise=_rule(recipes.noise_value, doc["noise"], "noise", source))
    context = LedgerContext(strip=None, round=round_, phase=phase,
                            lever_changed=lever, target_rect=rect)
    return Spec(source=source, label=label, request=Request(**fields),
                context=context, mask_rect=rect)


# ---------------------------------------------------------------------------
# The form a composing tool shows
# ---------------------------------------------------------------------------

EDITABLE = "editable"
CAPPED = "capped"
DERIVED = "derived"
LOCKED = "locked"
STATES: tuple[str, ...] = (EDITABLE, CAPPED, DERIVED, LOCKED)


class FormRow(NamedTuple):
    """One control of NovelAI's form, as the file route fills it.

    `label` is NovelAI's own wherever the recipe route's NAI_FIELDS confirmed
    it. `column` is "left", "right" or "cost", and tuple order inside a column
    is top to bottom. `key` is the request-file key the control writes, ""
    when it writes none. `state` is one of STATES. `ours` is what this route
    puts there; `reason` is why it is capped, derived or locked, "" for an
    editable row. `actions` lists the actions the control exists for.
    """
    label: str
    column: str
    key: str
    state: str
    ours: str
    reason: str
    actions: tuple[str, ...]


_ALL = ACTIONS
_IMAGE = ("img2img", "infill")

FORM: tuple[FormRow, ...] = (
    # -- left: NovelAI puts the model directly above the prompt box ----------
    FormRow("Model", "left", "variant", EDITABLE,
            f"NovelAI Diffusion V4.5 Full or Curated ({MODELS_BY_ACTION['generate'][0]} "
            f"/ {MODELS_BY_ACTION['generate'][1]}; inpainting sends their "
            f"-inpainting twins)", "", _ALL),
    FormRow("Model: V5 Full / Curated", "left", "", LOCKED, "not offered",
            "V5 draws on the usage battery; the guard allows only V4.5", _ALL),
    FormRow("Prompt", "left", "prompt", EDITABLE,
            "the author's text; tools.nai appends "
            f"', {QUALITY_TAIL}'", "", _ALL),
    FormRow("Add Quality Tags", "left", "", LOCKED, "off",
            "qualityToggle is False in request.FIXED_PARAMETERS; the tail is "
            "written into the caption instead, so the ledger row says what "
            "was sent", _ALL),
    FormRow("Undesired Content", "left", "negative", EDITABLE,
            "the pipeline's negative unless the author writes another", "",
            _ALL),
    FormRow("Undesired Content presets", "left", "", LOCKED,
            "none: ucPreset is the model's 'none' index",
            "a preset adds tags the ledger never records", _ALL),
    FormRow("Character Prompts", "left", "characters", EDITABLE,
            f"1 to {MAX_FRAMES}, each with its own Undesired Content", "",
            _ALL),
    FormRow("Character Positions", "left", "characters", EDITABLE,
            f"one cell of the 5x5 grid ({', '.join(str(v) for v in GRID)}) "
            f"per character, no two alike", "", _ALL),
    FormRow("AI's Choice / Custom", "left", "", LOCKED, "always Custom",
            "use_coords is True in request.FIXED_PARAMETERS: every character "
            "is sent with its position", _ALL),
    FormRow("Vibe Transfer", "left", "", LOCKED, "none",
            "guard condition 5 refuses any reference or vibe key; encoding a "
            "vibe costs 2 Anlas on every tier, Opus included", _ALL),
    FormRow("Precise Reference", "left", "", LOCKED, "none",
            "guard condition 5 refuses director_reference keys; each "
            "reference costs Anlas and cancels the free image", _ALL),
    # -- right: the settings column ------------------------------------------
    FormRow("Image Size", "right", "", DERIVED,
            f"multiples of {DIM_MULTIPLE}, each at least {MIN_DIM}, at most "
            f"{MAX_AREA:,} px",
            "the composing tool derives it from what it sends; guard "
            "condition 3 judges it", _ALL),
    FormRow("Number of Images", "right", "", LOCKED, "1",
            "n_samples is 1 in request.FIXED_PARAMETERS; a batch costs Anlas "
            "on every tier", _ALL),
    FormRow("Steps", "right", "steps", CAPPED,
            f"{DEFAULT_STEPS} by default",
            f"Opus tier: {MAX_STEPS} steps max (guard condition 4)", _ALL),
    FormRow("Prompt Guidance", "right", "scale", EDITABLE,
            f"{DEFAULT_SCALE:g} by default; any number above 0", "", _ALL),
    FormRow("Prompt Guidance Rescale", "right", "", LOCKED, "0",
            "cfg_rescale is fixed at 0 in request.FIXED_PARAMETERS", _ALL),
    FormRow("Variety+", "right", "", LOCKED, "off",
            "skip_cfg_above_sigma is None in request.FIXED_PARAMETERS", _ALL),
    FormRow("Decrisper", "right", "", LOCKED, "off",
            "dynamic_thresholding is False in request.FIXED_PARAMETERS", _ALL),
    FormRow("SMEA", "right", "", LOCKED, "off",
            "autoSmea is False; V4.5 takes no SMEA and request.build_body "
            "never sends sm or sm_dyn", _ALL),
    FormRow("Sampler", "right", "", LOCKED,
            f"Euler Ancestral ({DEFAULT_SAMPLER})",
            "the one sampler the research measured together with "
            "request.FIXED_PARAMETERS' companion flags; a request file has "
            "no sampler key", _ALL),
    FormRow("Noise Schedule", "right", "", LOCKED, DEFAULT_NOISE_SCHEDULE,
            "no key; 'native' is refused on V4/V4.5 by request.build_body",
            _ALL),
    FormRow("Seed", "right", "seed", EDITABLE,
            f"an int in [{SEED_MIN}, {SEED_MAX}], always written: a blank "
            f"seed would let the dry run and the send draw different ones",
            "", _ALL),
    FormRow("Image to Image: base image", "right", "image", DERIVED,
            f"the composing tool's canvas: an RGB PNG of Image Size, the "
            f"selection drawn on it and a transparent pixel keyed onto "
            f"#{'%02x%02x%02x' % BACKGROUND_RGB} by the tool, never guessed "
            f"here", "the tool draws it from its selection; "
            "recipes.source_png judges it, the rule every recipe's image "
            "passes", _IMAGE),
    FormRow("Image to Image: Strength", "right", "strength", CAPPED,
            f"{DEFAULT_STRENGTH:g} by default",
            f"the author's band {STRENGTH_BAND[0]:g}-{STRENGTH_BAND[1]:g}",
            ("img2img",)),
    FormRow("Image to Image: Noise", "right", "noise", EDITABLE,
            f"{DEFAULT_IMG2IMG_NOISE:g} for image to image, "
            f"{DEFAULT_INFILL_NOISE:g} for inpainting; "
            f"{NOISE_RANGE[0]:g}-{NOISE_RANGE[1]:g}", "", _IMAGE),
    FormRow("Color Correct", "right", "color_correct", EDITABLE,
            "off by default, the website's value for image to image", "",
            ("img2img",)),
    FormRow("Inpaint Strength", "right", "inpaint_strength", CAPPED,
            f"{DEFAULT_INPAINT_STRENGTH:g} by default",
            f"the author's band {STRENGTH_BAND[0]:g}-{STRENGTH_BAND[1]:g}, or "
            f"{INFILL_FULL_REPAINT:g} to repaint from the prompt alone",
            ("infill",)),
    FormRow("Inpainting mask", "right", "mask", DERIVED,
            f"white on black, any shape made of whole {MASK_ALIGN} px blocks "
            f"of the latent grid, over the whole image",
            "the tool draws it from its selection; masks.region_of refuses "
            "a block split between repaint and keep, or a grey edge",
            ("infill",)),
    FormRow("Overlay Original Image", "right", "", LOCKED, "off",
            "add_original_image is False for inpainting in "
            "request.build_body: run-request composites locally "
            "(masks.composite) and records differs_outside_mask, so what "
            "NovelAI changed outside the mask is measured, not painted over",
            ("infill",)),
    # -- cost: ours, not NovelAI's --------------------------------------------
    FormRow("Anlas", "cost", "", DERIVED,
            f"0 expected for generate: V4.5, at most {MAX_STEPS} steps, at "
            f"most {MAX_AREA:,} px, one image, Opus tier",
            "UNPROVEN for image to image and inpainting (risks R1, R2): the "
            "guard refuses both until the author's own probe writes a proof "
            "row, and no composing tool runs that probe", _ALL),
)


def catalog() -> dict:
    """The form, the limits and the defaults a composing tool needs, as one
    JSON-ready dict. Every value is read from `model`, `guard` or this
    module, never retyped."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "base64_prefix": BASE64_PREFIX,
        "keys": {
            "required": list(REQUIRED),
            "actions": {action: list(keys)
                        for action, keys in ACTION_KEYS.items()},
            "optional": list(OPTIONAL),
            "character": list(CHARACTER_KEYS),
        },
        "actions": list(ACTIONS),
        "variants": list(VARIANTS),
        "models": {action: dict(zip(VARIANTS, MODELS_BY_ACTION[action]))
                   for action in ACTIONS},
        "limits": {
            "max_area": MAX_AREA, "max_steps": MAX_STEPS,
            "dim_multiple": DIM_MULTIPLE, "min_dim": MIN_DIM,
            "max_characters": MAX_FRAMES, "token_budget": TOKEN_BUDGET,
            "tokens_per_word": TOKENS_PER_WORD,
            "word_pattern": WORD_RE.pattern,
            "seed_min": SEED_MIN, "seed_max": SEED_MAX,
            "mask_align": MASK_ALIGN,
            "strength_band": list(STRENGTH_BAND),
            "infill_full_repaint": INFILL_FULL_REPAINT,
            "noise_range": list(NOISE_RANGE),
        },
        "defaults": {
            "steps": DEFAULT_STEPS, "scale": DEFAULT_SCALE,
            "strength": DEFAULT_STRENGTH,
            "img2img_noise": DEFAULT_IMG2IMG_NOISE,
            "infill_noise": DEFAULT_INFILL_NOISE,
            "inpaint_strength": DEFAULT_INPAINT_STRENGTH,
            "color_correct": False, "negative": NEGATIVE, "init_k": INIT_K,
            "sampler": DEFAULT_SAMPLER,
            "noise_schedule": DEFAULT_NOISE_SCHEDULE,
        },
        "grid": list(GRID),
        "quality_tail": QUALITY_TAIL,
        "background": "#%02x%02x%02x" % BACKGROUND_RGB,
        "states": list(STATES),
        "form": [dict(row._asdict(), actions=list(row.actions))
                 for row in FORM],
    }
