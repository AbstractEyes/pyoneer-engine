"""The ONE builder of a NovelAI generate-image body, and its canonical hash.

OWNER: implementer A.

RESPONSIBILITY
--------------
`build_body` turns a `model.Request` into the exact JSON-ready dict that is
POSTed (brief 1.5-1.8). `redacted` and `canonical_sha256` give the ledger a
stable identity for that body without ever storing base64 image data.
`canonical_json` is the byte form both of them agree on: `run` stores those
bytes as the request blob, so the blob's filename IS the request_sha256.

INVARIANTS (the builder rule, brief 1.8)
----------------------------------------
* ONE FRAMES LIST, THREE ARRAYS. `req.frames` alone produces
  `parameters.characterPrompts`, `parameters.v4_prompt.caption.char_captions`
  and `parameters.v4_negative_prompt.caption.char_captions`, in the same
  order, with the same centers. No other function in this package may build
  any of those keys, `input`, `negative_prompt`, or the negative
  `base_caption` -- `guard.probe_body` included, which goes through here.
  Each array gets its OWN center dicts, never a shared one, so an edit to
  one array after the build is visible to the guard as a divergence.
* ONE POSITIVE STRING, ONE NEGATIVE STRING. `input` and
  `v4_prompt.caption.base_caption` are both `req.base_caption`;
  `negative_prompt` and `v4_negative_prompt.caption.base_caption` are both
  `req.negative`.
* THE BUILDER DOES NOT JUDGE COST. A 40-step request builds fine and
  `guard.evaluate` refuses it; that split is what lets a check mutate one
  condition at a time. The builder raises ValueError only for a Request that
  cannot be spelled as a body at all (the per-action field rule below).
* NEVER-SEND KEYS ARE NEVER WRITTEN: nothing in `model.NEVER_SEND_KEYS` or
  starting with `model.NEVER_SEND_PREFIXES`, at any depth.
* EVERY FIXED PARAMETER IS WRITTEN EXACTLY ONCE. The two ordered name lists
  below must cover `FIXED_PARAMETERS` exactly; the module raises at import
  when they do not, so a new fixed parameter cannot be silently dropped.
* Key order follows brief Templates A/B/C, so a body diffs cleanly against
  the brief. Output is deterministic: the same Request gives an equal dict.
* THE INFILL STRENGTH KEY IS model.INPAINT_STRENGTH_KEY, never a literal:
  spelled whole, tools/check_secrets.py reads it as a generated key. Same
  for any other 20+ character literal carrying a digit and mixed case.

PUBLIC NAMES
------------
FIXED_PARAMETERS, REDACTED_PREFIX, build_body, encode_body, png_header,
redacted, canonical_json, canonical_sha256.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import struct
from types import MappingProxyType
from typing import Mapping

from tools.nai.model import (ACTIONS, IMG2IMG_KEY, INPAINT_STRENGTH_KEY,
                             N_SAMPLES, PARAMS_VERSION, SEED_MAX, SEED_MIN,
                             Request)

FIXED_PARAMETERS: Mapping[str, object] = MappingProxyType({
    "params_version": PARAMS_VERSION,
    "n_samples": N_SAMPLES,
    "cfg_rescale": 0,
    "skip_cfg_above_sigma": None,
    "dynamic_thresholding": False,
    "deliberate_euler_ancestral_bug": False,
    "prefer_brownian": True,
    "qualityToggle": False,
    "autoSmea": False,
    "controlnet_strength": 1,
    "legacy": False,
    "legacy_v3_extend": False,
    "legacy_uc": False,
    "normalize_reference_strength_multiple": True,
    "use_coords": True,
})
"""Parameters whose value never varies in this design (brief 1.5). The
builder copies them verbatim into `parameters`; `add_original_image`,
`extra_noise_seed` and the image fields depend on the action and are
derived in `build_body`."""

REDACTED_PREFIX = "sha256:"
"""`redacted` replaces image and mask with this prefix plus the hex sha256 of
the DECODED PNG bytes, so the value equals the blob filename and the ledger's
init_png_sha256 / mask_png_sha256."""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_RGB = 2
_PNG_RGBA = 6

# Template order (brief 1.6-1.8). The fixed parameters fall into two runs,
# split by `ucPreset`; `n_samples`, `params_version` and `use_coords` sit at
# their own places. Together these lists must name FIXED_PARAMETERS exactly.
_FIXED_BEFORE_UC: tuple[str, ...] = (
    "cfg_rescale", "skip_cfg_above_sigma", "dynamic_thresholding",
    "deliberate_euler_ancestral_bug", "prefer_brownian", "qualityToggle",
)
_FIXED_AFTER_UC: tuple[str, ...] = (
    "autoSmea", "controlnet_strength", "legacy", "legacy_v3_extend",
    "legacy_uc", "normalize_reference_strength_multiple",
)
_FIXED_PLACED: tuple[str, ...] = ("params_version", "n_samples", "use_coords")

_written = _FIXED_BEFORE_UC + _FIXED_AFTER_UC + _FIXED_PLACED
if len(set(_written)) != len(_written) or set(_written) != set(FIXED_PARAMETERS):
    raise RuntimeError(
        "request.py: the template order lists do not name FIXED_PARAMETERS "
        f"exactly once each; missing {sorted(set(FIXED_PARAMETERS) - set(_written))}, "
        f"extra {sorted(set(_written) - set(FIXED_PARAMETERS))}")
del _written

_IMAGE_FIELDS: tuple[str, ...] = (
    "image_png", "mask_png", "strength", "noise", "inpaint_strength",
)


def _need(req: Request, name: str) -> None:
    if getattr(req, name) is None:
        raise ValueError(f"{req.action} request needs {name}")


def _forbid(req: Request, name: str) -> None:
    if getattr(req, name) is not None:
        raise ValueError(f"{req.action} request must not carry {name}")


def _check_png(req: Request, name: str, colour_type: int) -> None:
    data = getattr(req, name)
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError(f"{name} must be PNG bytes, got {type(data).__name__}")
    width, height, colour = png_header(bytes(data))
    if (width, height) != (req.width, req.height):
        raise ValueError(
            f"{name} is {width}x{height}; the request is "
            f"{req.width}x{req.height}")
    if colour != colour_type:
        raise ValueError(
            f"{name} has PNG colour type {colour}; it must be {colour_type} "
            f"({'RGB, opaque' if colour_type == _PNG_RGB else 'RGBA'})")


def _check_fields(req: Request) -> None:
    """The per-action field rule of `build_body`'s docstring."""
    if req.action == "generate":
        for name in _IMAGE_FIELDS:
            _forbid(req, name)
        if req.color_correct is not False:
            raise ValueError("generate request must have color_correct False")
    elif req.action == "img2img":
        for name in ("image_png", "strength", "noise"):
            _need(req, name)
        for name in ("mask_png", "inpaint_strength"):
            _forbid(req, name)
        if not isinstance(req.color_correct, bool):
            raise ValueError("img2img color_correct must be a bool")
        _check_png(req, "image_png", _PNG_RGB)
    else:  # infill
        for name in ("image_png", "mask_png", "inpaint_strength", "noise"):
            _need(req, name)
        _forbid(req, "strength")
        if req.color_correct is not False:
            raise ValueError(
                "infill request must have color_correct False; the nested "
                "img2img object's color_correct is derived by the builder")
        _check_png(req, "image_png", _PNG_RGB)
        _check_png(req, "mask_png", _PNG_RGBA)


def _center(frame_index: int, center: object) -> dict:
    """A FRESH {"x", "y"} dict for one frame; called once per array."""
    if not isinstance(center, (tuple, list)) or len(center) != 2:
        raise ValueError(
            f"frame {frame_index} center {center!r} is not an (x, y) pair")
    return {"x": center[0], "y": center[1]}


def _b64(data: bytes) -> str:
    return base64.b64encode(bytes(data)).decode("ascii")


def build_body(req: Request) -> dict:
    """Build the generate-image JSON body for `req` (brief 1.6 / 1.7 / 1.8).

    Shape: {"input", "model", "action", "parameters": {...}}.

    Per-action field rule -- ValueError naming the field when violated:
      generate: image_png, mask_png, strength, noise, inpaint_strength all
                None; color_correct False. Body has no image keys;
                add_original_image True.
      img2img:  image_png, strength, noise required; mask_png and
                inpaint_strength None. Body adds image (base64, no data:
                prefix), strength, noise, extra_noise_seed = seed - 1,
                color_correct; add_original_image True.
      infill:   image_png, mask_png, inpaint_strength, noise required;
                strength None and color_correct False (both are derived).
                Body adds image, mask, strength = inpaint_strength, noise,
                model.INPAINT_STRENGTH_KEY, extra_noise_seed = seed - 1;
                `model.IMG2IMG_KEY: {"strength": inpaint_strength,
                "color_correct": true}` ONLY when inpaint_strength != 1; no top-level
                color_correct; add_original_image False.
    Also ValueError when: action is not in model.ACTIONS; seed is outside
    [SEED_MIN, SEED_MAX]; noise_schedule is "native"; a PNG does not start
    with the PNG signature; an image's IHDR size is not width x height or its
    colour type is not 2 (RGB, opaque); a mask's IHDR size is not width x
    height or its colour type is not 6 (RGBA).

    Every frame yields {"prompt": caption, "uc": uc, "center": {"x", "y"},
    "enabled": true} in characterPrompts, {"char_caption": caption,
    "centers": [{"x", "y"}]} in v4_prompt, and {"char_caption": uc,
    "centers": [same]} in v4_negative_prompt. v4_prompt carries
    use_coords true and use_order true; v4_negative_prompt carries
    legacy_uc false. `ucPreset` is `req.ucPreset`.
    """
    if req.action not in ACTIONS:
        raise ValueError(f"action {req.action!r} is not one of {ACTIONS}")
    if (isinstance(req.seed, bool) or not isinstance(req.seed, int)
            or not SEED_MIN <= req.seed <= SEED_MAX):
        raise ValueError(
            f"seed {req.seed!r} is not an int in [{SEED_MIN}, {SEED_MAX}]")
    if req.noise_schedule == "native":
        raise ValueError(
            "noise_schedule 'native' is refused on V4/V4.5 (brief 1.5); "
            "use karras")
    _check_fields(req)

    fixed = FIXED_PARAMETERS
    p: dict = {}
    p["params_version"] = fixed["params_version"]
    p["width"] = req.width
    p["height"] = req.height
    p["scale"] = req.scale
    p["sampler"] = req.sampler
    p["steps"] = req.steps
    p["n_samples"] = fixed["n_samples"]
    p["seed"] = req.seed
    if req.action != "generate":
        p["extra_noise_seed"] = req.seed - 1
        p["image"] = _b64(req.image_png)
    if req.action == "img2img":
        p["strength"] = req.strength
        p["noise"] = req.noise
        p["color_correct"] = req.color_correct
    elif req.action == "infill":
        p["mask"] = _b64(req.mask_png)
        p["strength"] = req.inpaint_strength
        p["noise"] = req.noise
        p[INPAINT_STRENGTH_KEY] = req.inpaint_strength
        if req.inpaint_strength != 1:
            p[IMG2IMG_KEY] = {"strength": req.inpaint_strength,
                              "color_correct": True}
    p["noise_schedule"] = req.noise_schedule
    for name in _FIXED_BEFORE_UC:
        p[name] = fixed[name]
    p["ucPreset"] = req.ucPreset
    for name in _FIXED_AFTER_UC:
        p[name] = fixed[name]
    p["add_original_image"] = req.action != "infill"
    p["use_coords"] = fixed["use_coords"]

    frames = tuple(req.frames)
    p["characterPrompts"] = [
        {"prompt": f.caption, "uc": f.uc, "center": _center(i, f.center),
         "enabled": True}
        for i, f in enumerate(frames)]
    p["v4_prompt"] = {
        "caption": {
            "base_caption": req.base_caption,
            "char_captions": [
                {"char_caption": f.caption, "centers": [_center(i, f.center)]}
                for i, f in enumerate(frames)],
        },
        "use_coords": fixed["use_coords"],
        "use_order": True,
    }
    p["v4_negative_prompt"] = {
        "caption": {
            "base_caption": req.negative,
            "char_captions": [
                {"char_caption": f.uc, "centers": [_center(i, f.center)]}
                for i, f in enumerate(frames)],
        },
        "legacy_uc": fixed["legacy_uc"],
    }
    p["negative_prompt"] = req.negative

    return {
        "input": req.base_caption,
        "model": req.model,
        "action": req.action,
        "parameters": p,
    }


def encode_body(body: Mapping[str, object]) -> bytes:
    """The exact bytes POSTed: compact JSON, ASCII-escaped, key order kept.

    `json.dumps(body, separators=(",", ":"), ensure_ascii=True)` encoded as
    ASCII. Used by `transport.UrllibTransport.post_json` and nowhere else.
    NaN and infinities raise ValueError (they are not JSON).
    """
    return json.dumps(body, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def png_header(png: bytes) -> tuple[int, int, int]:
    """(width, height, colour_type) from a PNG's IHDR, standard library only.

    ValueError when the bytes do not start with the 8-byte PNG signature
    followed by an IHDR chunk. Shared by `build_body` and
    `transport.unzip_image`.
    """
    if not isinstance(png, (bytes, bytearray, memoryview)):
        raise ValueError(f"PNG data must be bytes, got {type(png).__name__}")
    head = bytes(png[:33])
    if len(head) < 33 or head[:8] != _PNG_SIGNATURE:
        raise ValueError("not a PNG: the 8-byte signature and IHDR are missing")
    length, chunk_type = struct.unpack(">I4s", head[8:16])
    if chunk_type != b"IHDR" or length != 13:
        raise ValueError("not a PNG: the first chunk is not a 13-byte IHDR")
    width, height = struct.unpack(">II", head[16:24])
    return width, height, head[25]


def _redact_value(key: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"parameters.{key} must be a base64 string, got "
            f"{type(value).__name__}")
    if value.startswith(REDACTED_PREFIX):
        return value
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"parameters.{key} is not valid base64") from None
    return REDACTED_PREFIX + hashlib.sha256(raw).hexdigest()


def redacted(body: Mapping[str, object]) -> dict:
    """A deep copy of `body` with parameters.image and parameters.mask replaced.

    Each present value becomes REDACTED_PREFIX + sha256(base64decode(value)).
    Idempotent: a value already starting with REDACTED_PREFIX is kept (':' is
    not a base64 character, so the two cannot be confused). Never mutates
    `body`. No other key is touched. ValueError when a present image or mask
    is not a string of valid base64.
    """
    out = copy.deepcopy(dict(body))
    params = out.get("parameters")
    if isinstance(params, Mapping):
        params = dict(params)
        out["parameters"] = params
        for key in ("image", "mask"):
            if key in params:
                params[key] = _redact_value(key, params[key])
    return out


def canonical_json(body: Mapping[str, object]) -> bytes:
    """The canonical bytes of `redacted(body)`, the ONE spelling of them.

    json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    allow_nan=False).encode("ascii"). `canonical_sha256` hashes these bytes
    and `run.run_request` stores them as the request blob, so the stored
    blob's sha256 equals the ledger's request_sha256.
    """
    return json.dumps(redacted(body), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def canonical_sha256(body: Mapping[str, object]) -> str:
    """Hex sha256 of the canonical JSON of `redacted(body)`.

    Canonical = json.dumps(..., sort_keys=True, separators=(",", ":"),
    ensure_ascii=True).encode("ascii"). Equal for a body and its redacted
    copy; changes when any parameter, caption, center or image byte changes.
    This is the ledger's request_sha256.
    """
    return hashlib.sha256(canonical_json(body)).hexdigest()
