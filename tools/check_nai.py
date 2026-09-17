"""Verify tools/nai with every socket refused: the body, the free-tier guard, the one POST, the key, the inits, the masks, pixelize and the CLI.

    .venv/Scripts/python.exe tools/check_nai.py

NO SOCKET, NO KEY
-----------------
Before `tools.nai` is imported, every socket entry point this process could
reach -- `socket.socket.connect` / `connect_ex`, `socket.create_connection`,
`getaddrinfo`, `gethostbyname`, both `http.client` connection classes and
`urllib.request.urlopen` -- is replaced by a function that records the attempt
and raises `NetworkForbidden`, a BaseException so that no `except Exception`
in the package under test can swallow it (run.run_request catches
BaseException around the POST only to record it, and re-raises it; the
attempt is in NETWORK_ATTEMPTS either way). Section 0 proves the guard fires,
and the last assertion is that nothing but section 0's own probes ever hit it.
The only "server" is `transport.RecordingTransport` or, where the key has to
really travel, the real `UrllibTransport` with a fake HTTPS handler installed
through `transport._TEST_HANDLERS`, so urllib's own error and header
machinery runs and still opens nothing -- and, for the header-validation
case, the stdlib's own HTTPSHandler with a bare SSLContext, which refuses the
header before it could connect.

The process's NAI_KEY is OVERWRITTEN with an obviously fake canary before
anything is imported. It is never read first, so whatever key the machine
holds cannot reach any line below, and the canary is what every leak search
looks for. The canary starts with a SHORT `pst-` (nowhere near a real token's
64 characters), so a scrub that removes only the marker is caught: every leak
search looks for the canary's BODY, which such a scrub leaves behind.

WHAT IS COVERED, EACH WITH BOTH HALVES
-------------------------------------
  0. the guard: every patched entry point raises, and records the attempt.
  1. `request.build_body`: every built body equals brief Templates A/B/C
     PINNED HERE AS LITERALS -- key order, every fixed parameter, the
     author's strength 0.45 / noise 0.05 / infill noise 0 -- with only the
     image and mask masked; the recipes' base captions, negative, character
     caption template and empty UC pinned as literals from brief 3.2-3.4; the
     three caption arrays parallel and equal to the frames, with their own
     center objects; img2img and infill add exactly their fields; the infill
     init is the SOURCE outside the cell and the mannequin inside it; the
     author's band refuses 0.34 / 0.56 and noise and scale out of range; an
     opaque RGBA source is accepted and a transparent one refused -- and the
     builder refuses every request it cannot spell.
  2. `guard.assert_free`: a legal generate, img2img and infill pass; every
     refusal condition of brief 2.2 -- and every sub-rule inside conditions
     1, 6 and 7 (image keys bound to the action, a proof the chain has not
     confirmed or has refuted, a proof naming a probe row with no image, no
     2xx, a moved balance or LOCK, a proof refuted by a LATER charged call of
     its pair -- and left standing by a charged call of any other pair, a
     rise, or a charge before its probe -- the infill probe's every strength, enabled,
     prompt/uc parity, use_coords, over-long arrays, the token budget, uc
     text) -- is refused with ITS OWN condition number, its own reason, and
     no other condition failing.
  3. `run.run_request` over a scripted transport: one POST between two balance
     reads on success, HTTP error and a raised timeout; no retry; a decrease
     writes LOCK and the next call is refused before any request; the SUM is
     compared, through the real subscription parser, and grace / inactive /
     tier 2 are refused after one read; an inconclusive row chains on its
     own balance after; a Ctrl-C in the POST or in the after-read still
     writes the row and LOCK; a lost ledger (blobs, no rows) is refused; a
     corrupt deflate stream is recorded, not raised; a probe writes a proof
     only on 2xx carrying an image of the requested size with delta 0 (an
     HTML page, an empty body, a 204, JSON or a wrong-size image write none),
     and a late debit refutes it for good; a production img2img or infill
     charged, unread after, or followed by a late debit refutes its proof,
     so deleting LOCK sends nothing, and its LOCK says to stay on the
     generate track; the
     one-send latch; the response-shape and redirect rules of brief 1.4.
     Then the canary key, through the real urllib transport and the CLI:
     present in every Authorization header, absent from every state file,
     ledger row, exception and captured stdout/stderr -- including a server
     echoing it raw, JSON-escaped, or after the scrub, and a key with a line
     break inside it.
  4. `transport.api_key`: present -> stripped value; absent, blank, or not a
     bare visible-ASCII token -> MissingKey naming NAI_KEY, with a message
     that does not depend on the value.
  5. mannequin: every layout's centers are on the grid, distinct, inside
     their own cell and re-measured from the PNG's pixels; the init is exactly
     width x height, RGB (opaque) and k-blocky; render_init refuses two frames
     sharing a center and a center outside its cell; `strip` refuses n > 5,
     sizes off the 64 grid and areas over MAX_AREA.
  6. masks: RGBA, alpha 255, white exactly over the cell and 8-aligned;
     composite changes nothing outside the rect; differs_outside sees one pixel
     outside and ignores one inside; bad indexes, sizes and rects raise.
  7. `post.pixelize` on synthetic upscaled, noised, blurred strips drawn here:
     k and phase recovered, every frame's alpha exact and colours within 8,
     background keyed without the fallback, every emitted colour a palette
     entry; a ground frame drawn above its anchor lands on the baseline, a
     hold_arc strip keeps its arc; a strip with a missing frame, swapped
     centers, a bulky frame (opaque_px only) or a squashed ground frame
     (ground_height only) is rejected; used_colours refuses more colours
     than the palette holds.
  8. the CLI: `plan` prints no key and builds no transport; `probe` without
     --accept-max-2-anlas -- or with any abbreviation of it -- is refused
     before any account read, and with it reads, sends once and writes the
     proof -- but not for a 200 with no image; after a charged production
     img2img and LOCK deleted, `plan` reports the proof REFUTED and `run`
     sends nothing; `infill` sends the mannequin-in-source init and composites the
     returned cell; `render` never overwrites different bytes and no command
     writes inside a checkout outside data/nai/; a linked worktree resolves
     the main checkout's state root and sees its LOCK.

State lives in a temporary directory, never under data/nai/ or data/art/;
the check asserts at the end that it did not create data/nai/.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede the tools.nai imports)

import base64
import contextlib
import copy
import dataclasses
import hashlib
import http.client
import io
import json
import os
import random
import shutil
import socket
import ssl
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
import urllib.response
import zipfile

# ===========================================================================
# The network guard and the canary key -- BEFORE tools.nai is imported
# ===========================================================================
NETWORK_ATTEMPTS: list[str] = []


class NetworkForbidden(BaseException):
    """Raised by every patched socket entry point. A BaseException on purpose:
    run.run_request records and re-raises any Exception out of a send, and a
    guard that could be recorded could also be swallowed."""


def _refuse(name: str):
    def refuse(*_args, **_kwargs):
        NETWORK_ATTEMPTS.append(name)
        raise NetworkForbidden(f"check_nai opens no socket; {name} was called")
    return refuse


GUARDED = (
    (socket.socket, "connect"), (socket.socket, "connect_ex"),
    (socket, "create_connection"), (socket, "getaddrinfo"),
    (socket, "gethostbyname"), (socket, "gethostbyname_ex"),
    (http.client.HTTPConnection, "connect"),
    (http.client.HTTPSConnection, "connect"),
    (urllib.request, "urlopen"),
)


def install_network_guard() -> None:
    for owner, name in GUARDED:
        setattr(owner, name, _refuse(f"{getattr(owner, '__name__', owner)}.{name}"))


install_network_guard()

CANARY = "pst-fake-key-for-tests"
"""Obviously fake, and the only key this process ever holds. Assigned, never
read first: the machine's own NAI_KEY is gone from this process before any
module under test is imported. Its short `pst-` prefix is on purpose (see
the module docstring); a real token's body is 64 characters."""
CANARY_BODY = CANARY[len("pst-"):]
"""What every leak search looks for: present whether or not a scrub took the
marker off the front."""
os.environ["NAI_KEY"] = CANARY

from PIL import Image, ImageChops, ImageFilter  # noqa: E402

import tools.nai  # noqa: E402
from tools.nai import (cli, guard, mannequin, masks, post, recipes,  # noqa: E402
                       request, run)
from tools.nai import transport as tp  # noqa: E402
from tools.nai.model import (BACKGROUND_RGB, DEFAULT_COLOURS,  # noqa: E402
                             GENERATE_URL, GRID, IMG2IMG_KEY,
                             INPAINT_STRENGTH_KEY, LEDGER_FIELDS, MAX_AREA,
                             MODEL_CURATED, MODEL_CURATED_INPAINTING,
                             MODEL_FULL, MODEL_FULL_INPAINTING,
                             NEVER_SEND_KEYS, NEVER_SEND_PREFIXES,
                             OUTLINE_RGB, PROBE_STRENGTH, QUALITY_TAIL,
                             RATING_TAG, SUBSCRIPTION_URL, Account, CellSpec,
                             Frame, Layout, LedgerContext, Proof, on_grid,
                             snap)
from tools.nai import state as nai_state  # noqa: E402
from tools.nai.state import State  # noqa: E402

failures: list[str] = []
asserted: list[int] = []


def expect(label, got, want):
    asserted.append(1)
    ok = got == want
    shown_got, shown_want = str(got), str(want)
    if len(shown_got) > 100:
        shown_got = shown_got[:97] + "..."
    if len(shown_want) > 100:
        shown_want = shown_want[:97] + "..."
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<66} got={shown_got} "
          f"want={shown_want}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    expect(label, bool(got), True)


def expect_raises(label, exception, call, *fragments):
    """`call` must raise `exception` with every fragment in its message."""
    asserted.append(1)
    try:
        call()
    except exception as exc:
        missing = [f for f in fragments if f not in str(exc)]
        if missing:
            print(f"  FAIL {label:<66} raised {type(exc).__name__} without "
                  f"{missing}: {str(exc).splitlines()[0][:120]}")
            failures.append(label)
            return exc
        print(f"  ok   {label:<66} raised {type(exc).__name__}")
        return exc
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<66} raised {type(exc).__name__}, wanted "
              f"{exception.__name__}: {str(exc)[:120]}")
        failures.append(label)
        return exc
    print(f"  FAIL {label:<66} did not raise")
    failures.append(label)
    return None


REPO_STATE = os.path.join(_bootstrap.REPO_ROOT, "data", "nai")
REPO_STATE_EXISTED = os.path.lexists(REPO_STATE)
SCRATCH = tempfile.mkdtemp(prefix="pyoneer_check_nai_")
_scratch_count = [0]


def scratch_state(tag: str) -> State:
    """A fresh, empty State under this run's temporary directory."""
    _scratch_count[0] += 1
    return State(os.path.join(SCRATCH, f"{_scratch_count[0]:02d}_{tag}"))


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


print("check_nai -- the NovelAI pipeline, offline, with every socket refused")
print(f"  package: {os.path.dirname(tools.nai.__file__)}")
print(f"  scratch: {SCRATCH}")

try:
    # =======================================================================
    print("\n0. the network guard fires, and records what tried")
    # =======================================================================
    before = len(NETWORK_ATTEMPTS)
    expect_raises("socket.create_connection is refused", NetworkForbidden,
                  lambda: socket.create_connection(("127.0.0.1", 9), 1),
                  "opens no socket")
    probe_socket = socket.socket()
    try:
        expect_raises("socket.socket().connect is refused", NetworkForbidden,
                      lambda: probe_socket.connect(("127.0.0.1", 9)),
                      "opens no socket")
        expect_raises("...and connect_ex too", NetworkForbidden,
                      lambda: probe_socket.connect_ex(("127.0.0.1", 9)),
                      "opens no socket")
    finally:
        probe_socket.close()
    expect_raises("name resolution is refused", NetworkForbidden,
                  lambda: socket.getaddrinfo("localhost", 9), "opens no socket")
    expect_raises("urllib.request.urlopen is refused", NetworkForbidden,
                  lambda: urllib.request.urlopen("http://127.0.0.1:9/"),
                  "opens no socket")
    expect_raises("an http.client connection is refused", NetworkForbidden,
                  lambda: http.client.HTTPConnection("127.0.0.1", 9).connect(),
                  "opens no socket")
    expect("every refusal was recorded", len(NETWORK_ATTEMPTS) - before, 6)
    NETWORK_ATTEMPTS.clear()

    # -- fixtures shared by every section below ------------------------------
    SEED = 1234567890
    WALK = recipes.RECIPES["walk"]
    L5 = WALK.layout
    COLOURS = WALK.identity.as_dict()
    INIT_PNG, WALK_CENTERS = mannequin.render_init(L5, WALK.poses, COLOURS)
    # The infill source is NOT the init: a flat colour, so pasting the
    # mannequin into the target cell is visible in the bytes that are sent.
    FLAT_RGB = (40, 160, 90)
    FLAT_PNG = png_bytes(Image.new("RGB", (L5.width, L5.height), FLAT_RGB))
    REQ_GEN = recipes.make_request("walk", "generate", SEED)
    REQ_I2I = recipes.make_request("walk", "img2img", SEED)
    REQ_INF = recipes.make_request("walk", "infill", SEED,
                                   source_png=FLAT_PNG, cell=2)
    BODY_GEN = request.build_body(REQ_GEN)
    BODY_I2I = request.build_body(REQ_I2I)
    BODY_INF = request.build_body(REQ_INF)
    BODIES = (("generate", REQ_GEN, BODY_GEN), ("img2img", REQ_I2I, BODY_I2I),
              ("infill", REQ_INF, BODY_INF))

    # Pinned HERE from brief 1.5 "Never send", and compared to the package's
    # copy: a detector reading the package's own list goes blind with it.
    PINNED_NEVER_KEYS = {"sm", "sm_dyn", "uncond_scale", "image_format",
                         "stream", "characterRef"}
    PINNED_NEVER_PREFIXES = ("tag_hint_", "director_reference", "reference_")

    def never_send_paths(obj, path=""):
        found = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                here = f"{path}.{key}" if path else str(key)
                if key in PINNED_NEVER_KEYS or str(key).startswith(
                        PINNED_NEVER_PREFIXES):
                    found.append(here)
                found += never_send_paths(value, here)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                found += never_send_paths(value, f"{path}[{index}]")
        return found

    def array_problems(body, req):
        """Every way the three caption arrays disagree with req.frames."""
        p = body["parameters"]
        prompts = p["characterPrompts"]
        positive = p["v4_prompt"]["caption"]["char_captions"]
        negative = p["v4_negative_prompt"]["caption"]["char_captions"]
        problems = []
        n = len(req.frames)
        if not len(prompts) == len(positive) == len(negative) == n:
            problems.append(f"lengths {len(prompts)}/{len(positive)}/"
                            f"{len(negative)} for {n} frames")
        for i, frame in enumerate(req.frames[:min(len(prompts), len(positive),
                                                  len(negative))]):
            want = {"x": frame.center[0], "y": frame.center[1]}
            if prompts[i]["center"] != want:
                problems.append(f"characterPrompts[{i}] center")
            if positive[i]["centers"] != [want]:
                problems.append(f"v4_prompt[{i}] centers")
            if negative[i]["centers"] != [want]:
                problems.append(f"v4_negative_prompt[{i}] centers")
            if (prompts[i]["prompt"], positive[i]["char_caption"]) != (
                    frame.caption, frame.caption):
                problems.append(f"frame {i} caption")
            if (prompts[i]["uc"], negative[i]["char_caption"]) != (frame.uc,
                                                                   frame.uc):
                problems.append(f"frame {i} uc")
            if prompts[i]["enabled"] is not True:
                problems.append(f"characterPrompts[{i}] not enabled")
            objects = (prompts[i]["center"], positive[i]["centers"][0],
                       negative[i]["centers"][0])
            if len({id(o) for o in objects}) != 3:
                problems.append(f"frame {i} arrays share a center object")
        return problems

    def edited(body, change):
        out = copy.deepcopy(body)
        change(out)
        return out

    def outcome(call):
        """call() or "<ExceptionClass>: <message>" -- a refusal that should
        not happen fails its assertion instead of ending the check."""
        try:
            return call()
        except Exception as caught:  # noqa: BLE001 - the class is the answer
            return f"{type(caught).__name__}: {caught}"

    # =======================================================================
    print("\n1. build_body: one frames list, three parallel arrays, the right fields")
    # =======================================================================
    expect("the package's never-send keys are brief 1.5's list",
           (set(NEVER_SEND_KEYS), tuple(NEVER_SEND_PREFIXES)),
           (PINNED_NEVER_KEYS, PINNED_NEVER_PREFIXES))
    for action, req, body in BODIES:
        params = body["parameters"]
        expect(f"{action}: the recipe gives 5 frames on 5 distinct grid centers",
               (len(req.frames), len({f.center for f in req.frames}),
                all(on_grid(v) for f in req.frames for v in f.center)),
               (5, 5, True))
        expect(f"{action}: the three arrays are parallel and equal the frames",
               array_problems(body, req), [])
        expect(f"{action}: input == v4_prompt base_caption == the recipe's",
               (body["input"], params["v4_prompt"]["caption"]["base_caption"]),
               (req.base_caption, req.base_caption))
        expect(f"{action}: negative_prompt == the negative base_caption",
               (params["negative_prompt"],
                params["v4_negative_prompt"]["caption"]["base_caption"]),
               (req.negative, req.negative))
        expect_true(f"{action}: rating:general closes the base caption",
                    body["input"].endswith(QUALITY_TAIL)
                    and QUALITY_TAIL.endswith("rating:general")
                    and RATING_TAG == "rating:general")
        char_texts = ([c["prompt"] for c in params["characterPrompts"]]
                      + [c["uc"] for c in params["characterPrompts"]]
                      + [c["char_caption"] for c in
                         params["v4_prompt"]["caption"]["char_captions"]]
                      + [c["char_caption"] for c in
                         params["v4_negative_prompt"]["caption"]["char_captions"]])
        expect(f"{action}: no character caption or uc carries rating:",
               [t for t in char_texts if "rating:" in t], [])
        expect(f"{action}: no never-send key at any depth",
               never_send_paths(body), [])
        expect(f"{action}: action and model on the wire",
               (body["action"], body["model"]), (action, req.model))

    # -- brief Templates A/B/C and 3.2-3.4, PINNED HERE as literals ---------
    # Every value below is copied from the brief (with the author's strength
    # override), never read from the package: a comparison against the
    # package's own constants goes blind with them.
    PIN_INPAINT_KEY = "".join(("inpaint", "Img2Img", "Strength"))
    PIN_IDENTITY = ("brown hair, short hair, red scarf, blue tunic, brown "
                    "belt, tan pants, brown boots")
    PIN_TAIL = "very aesthetic, masterpiece, no text, rating:general"
    PIN_HEAD = "1boy, multiple views, pixel art, sprite sheet, full body, from side"
    PIN_STYLE = ("simple background, grey background, limited palette, flat "
                 "color, black outline")
    PIN_BASE = {
        "walk": (f"{PIN_HEAD}, walking, {PIN_STYLE}, {PIN_IDENTITY}, a retro "
                 "video game walk cycle: the same boy drawn five times in one "
                 "row from left to right, four walking poses then one "
                 "standing pose, every copy facing right, all feet on the "
                 f"same ground line, {PIN_TAIL}"),
        "run": (f"{PIN_HEAD}, running, {PIN_STYLE}, {PIN_IDENTITY}, a retro "
                "video game run cycle: the same boy drawn six times in two "
                "rows of three, every copy facing right and leaning forward, "
                f"the feet in each row on the same ground line, {PIN_TAIL}"),
        "jump": (f"{PIN_HEAD}, jumping, {PIN_STYLE}, {PIN_IDENTITY}, a retro "
                 "video game jump sequence: the same boy drawn five times in "
                 "one row from left to right, crouching, leaping up, at the "
                 "top of the jump, falling, landing, every copy facing right, "
                 f"{PIN_TAIL}"),
    }
    PIN_NEGATIVE = (
        "nsfw, lowres, artistic error, film grain, scan artifacts, worst "
        "quality, bad quality, jpeg artifacts, very displeasing, chromatic "
        "aberration, dithering, halftone, screentone, logo, too many "
        "watermarks, watermark, signature, text, blurry, 3d, realistic, "
        "gradient background, detailed background, scenery, shadow, cropped, "
        "out of frame, from behind, facing viewer")
    PIN_CAPTION = "boy, brown hair, red scarf, blue tunic, from side, facing right, "
    W_CONTACT = "walking, mid-stride, legs apart, front heel on ground, arms swinging"
    W_PASS = ("walking, passing pose, standing on one leg, other knee bent, "
              "legs close together")
    R_POSES = ("running, leaning forward, legs spread wide, front heel "
               "touching ground, arms bent",
               "running, leaning forward, standing on one leg, other knee "
               "raised high, arms bent",
               "running, leaning forward, midair, both feet off ground, legs "
               "split, arms bent")
    PIN_POSES = {
        "walk": (W_CONTACT, W_PASS, W_CONTACT, W_PASS,
                 "standing, legs slightly apart, arms at sides"),
        "run": R_POSES * 2,
        "jump": ("crouching, knees bent, leaning forward, arms swung back",
                 "jumping, midair, legs straight, toes pointed down, arms "
                 "raised up",
                 "jumping, midair, knees up, legs tucked, arms spread",
                 "falling, midair, legs stretched down, arms raised",
                 "landing, squatting, knees bent, arms forward"),
    }
    PIN_WALK_CENTERS = [(0.1, 0.5), (0.3, 0.5), (0.5, 0.5), (0.7, 0.5),
                        (0.9, 0.5)]
    MASKED = object()

    def template(action, variant="full"):
        """Brief Template A (generate), B (img2img) or C (infill) for the walk
        strip at SEED, filled from the PINNED captions; image/mask MASKED."""
        model_id = {("generate", "full"): "nai-diffusion-4-5-full",
                    ("img2img", "full"): "nai-diffusion-4-5-full",
                    ("infill", "full"): "nai-diffusion-4-5-full-inpainting",
                    ("generate", "curated"): "nai-diffusion-4-5-curated",
                    ("img2img", "curated"): "nai-diffusion-4-5-curated",
                    ("infill", "curated"):
                        "nai-diffusion-4-5-curated-inpainting"}[(action,
                                                                  variant)]
        captions = [PIN_CAPTION + words for words in PIN_POSES["walk"]]
        centers = PIN_WALK_CENTERS
        p = {"params_version": 3, "width": 1216, "height": 832, "scale": 5,
             "sampler": "k_euler_ancestral", "steps": 23, "n_samples": 1,
             "seed": SEED}
        if action != "generate":
            p["extra_noise_seed"] = SEED - 1
            p["image"] = MASKED
        if action == "img2img":
            p.update({"strength": 0.45, "noise": 0.05, "color_correct": False})
        if action == "infill":
            p.update({"mask": MASKED, "strength": 0.45, "noise": 0,
                      PIN_INPAINT_KEY: 0.45,
                      "img2img": {"strength": 0.45, "color_correct": True}})
        p.update({
            "noise_schedule": "karras", "cfg_rescale": 0,
            "skip_cfg_above_sigma": None, "dynamic_thresholding": False,
            "deliberate_euler_ancestral_bug": False, "prefer_brownian": True,
            "qualityToggle": False,
            "ucPreset": 4 if variant == "full" else 3,
            "autoSmea": False, "controlnet_strength": 1, "legacy": False,
            "legacy_v3_extend": False, "legacy_uc": False,
            "normalize_reference_strength_multiple": True,
            "add_original_image": action != "infill", "use_coords": True,
            "characterPrompts": [
                {"prompt": c, "uc": "", "center": {"x": x, "y": y},
                 "enabled": True} for c, (x, y) in zip(captions, centers)],
            "v4_prompt": {
                "caption": {"base_caption": PIN_BASE["walk"], "char_captions": [
                    {"char_caption": c, "centers": [{"x": x, "y": y}]}
                    for c, (x, y) in zip(captions, centers)]},
                "use_coords": True, "use_order": True},
            "v4_negative_prompt": {
                "caption": {"base_caption": PIN_NEGATIVE, "char_captions": [
                    {"char_caption": "", "centers": [{"x": x, "y": y}]}
                    for x, y in centers]},
                "legacy_uc": False},
            "negative_prompt": PIN_NEGATIVE,
        })
        return {"input": PIN_BASE["walk"], "model": model_id,
                "action": action, "parameters": p}

    def template_diff(got, want, path="body"):
        """Every place `got` differs from `want`: key sets AND key order,
        bool vs number kept apart (False == 0 in Python, not on the wire)."""
        if want is MASKED:
            return [] if isinstance(got, str) and got else [f"{path} missing"]
        if isinstance(want, dict):
            if not isinstance(got, dict):
                return [f"{path} is {type(got).__name__}, not an object"]
            if list(got) != list(want):
                missing = [k for k in want if k not in got]
                extra = [k for k in got if k not in want]
                return [f"{path} keys: missing {missing} extra {extra}"
                        if missing or extra else f"{path} key order differs"]
            out = []
            for key in want:
                out += template_diff(got[key], want[key], f"{path}.{key}")
            return out
        if isinstance(want, list):
            if not isinstance(got, list) or len(got) != len(want):
                return [f"{path} is not a list of {len(want)}"]
            out = []
            for i, (g, w) in enumerate(zip(got, want)):
                out += template_diff(g, w, f"{path}[{i}]")
            return out
        if isinstance(want, bool) or want is None:
            return [] if got is want else [f"{path} = {got!r}, want {want!r}"]
        if isinstance(want, (int, float)):
            ok = (not isinstance(got, bool) and isinstance(got, (int, float))
                  and got == want)
            return [] if ok else [f"{path} = {got!r}, want {want!r}"]
        return [] if got == want else [f"{path} = {str(got)[:40]!r}, want "
                                       f"{str(want)[:40]!r}"]

    expect("the infill strength's wire key is the brief's spelling",
           INPAINT_STRENGTH_KEY, PIN_INPAINT_KEY)
    for action, req, body in BODIES:
        expect(f"{action}: the body IS brief Template "
               f"{'ABC'[('generate', 'img2img', 'infill').index(action)]} "
               f"(order, every fixed value)",
               template_diff(body, template(action)), [])
    for action in ("generate", "img2img", "infill"):
        extra = ({"source_png": FLAT_PNG, "cell": 2} if action == "infill"
                 else {})
        curated = request.build_body(recipes.make_request(
            "walk", action, SEED, variant="curated", **extra))
        expect(f"{action} curated: the template with ucPreset 3",
               template_diff(curated, template(action, "curated")), [])
    control = template("img2img")
    control["parameters"]["image"] = "iVBORw0KGgo="
    control["parameters"]["dynamic_thresholding"] = 0
    expect("control: the template diff tells False from 0 and sees order",
           (template_diff(control, template("img2img")),
            template_diff(dict(reversed(list(template("generate").items()))),
                          template("generate"))),
           (["body.parameters.dynamic_thresholding = 0, want False"],
            ["body key order differs"]))
    for name in ("walk", "run", "jump"):
        recipe = recipes.RECIPES[name]
        frames = recipes.frames_for(recipe, mannequin.render_init(
            recipe.layout, recipe.poses, recipe.identity.as_dict())[1])
        expect(f"{name}: base caption, negative, captions and empty UC are "
               f"brief 3.2-3.4's text",
               (recipe.base_caption == PIN_BASE[name],
                recipe.negative == PIN_NEGATIVE,
                [f.caption for f in frames],
                [f.uc for f in frames]),
               (True, True, [PIN_CAPTION + w for w in PIN_POSES[name]],
                [""] * len(PIN_POSES[name])))

    # -- the author's strength rule, as literals ----------------------------
    for label, action, key, value in (
            ("img2img 0.34 (below the band)", "img2img", "strength", 0.34),
            ("img2img 0.56 (above the band)", "img2img", "strength", 0.56),
            ("img2img 1.0 (full repaint is infill's only)", "img2img",
             "strength", 1.0),
            ("infill 0.34", "infill", "inpaint_strength", 0.34),
            ("infill 0.56", "infill", "inpaint_strength", 0.56),
            ("infill 0.99", "infill", "inpaint_strength", 0.99)):
        extra = ({"source_png": FLAT_PNG, "cell": 2} if action == "infill"
                 else {})
        expect_raises(f"strength {label} is refused", ValueError,
                      lambda a=action, k=key, v=value, e=extra:
                      recipes.make_request("walk", a, SEED, **{k: v}, **e),
                      "outside the author's band")
    expect("infill accepts 0.35, 0.55 and the full repaint 1.0",
           [request.build_body(recipes.make_request(
               "walk", "infill", SEED, source_png=FLAT_PNG, cell=2,
               inpaint_strength=s))["parameters"][PIN_INPAINT_KEY]
            for s in (0.35, 0.55, 1.0)], [0.35, 0.55, 1.0])
    for label, action, overrides, fragment in (
            ("img2img noise 1.5", "img2img", {"noise": 1.5}, "noise must lie"),
            ("img2img noise -0.01", "img2img", {"noise": -0.01},
             "noise must lie"),
            ("infill noise 7", "infill", {"noise": 7.0, "source_png": FLAT_PNG,
                                          "cell": 2}, "noise must lie"),
            ("generate scale 0", "generate", {"scale": 0}, "scale must be > 0"),
            ("img2img scale -3", "img2img", {"scale": -3.0},
             "scale must be > 0")):
        expect_raises(f"{label} is refused", ValueError,
                      lambda a=action, o=overrides:
                      recipes.make_request("walk", a, SEED, **o), fragment)
    expect("...while noise 0.99 and scale 0.5 build",
           (recipes.make_request("walk", "img2img", SEED, noise=0.99).noise,
            recipes.make_request("walk", "generate", SEED, scale=0.5).scale),
           (0.99, 0.5))

    # -- the source image: one rule for img2img and infill ------------------
    def rgba_of(rgb_png, alpha_at=None):
        image = opened(rgb_png).convert("RGBA")
        if alpha_at is not None:
            (x, y), alpha = alpha_at
            r, g, b, _ = image.getpixel((x, y))
            image.putpixel((x, y), (r, g, b, alpha))
        return png_bytes(image)

    def decoded(req):
        return opened(req.image_png).convert("RGB")

    flat_image = opened(FLAT_PNG).convert("RGB")
    init_image = opened(INIT_PNG).convert("RGB")
    for action, extra in (("img2img", {}), ("infill", {"cell": 2})):
        for label, source in (("opaque RGBA", rgba_of(FLAT_PNG)),
                              ("RGBA with one alpha of 254 (metadata bits)",
                               rgba_of(FLAT_PNG, ((3, 3), 254)))):
            req = outcome(lambda a=action, src=source, e=extra:
                          recipes.make_request("walk", a, SEED,
                                               source_png=src, **e))
            if isinstance(req, str):
                expect(f"{action}: an {label} source is accepted and sent as "
                       f"RGB", req, "a Request")
                continue
            outside = decoded(req)
            outside.paste((0, 0, 0), L5.cells[2].rect_canvas)
            want = flat_image.copy()
            want.paste((0, 0, 0), L5.cells[2].rect_canvas)
            expect(f"{action}: an {label} source is accepted and sent as RGB",
                   (request.png_header(req.image_png)[2],
                    outside.tobytes() == want.tobytes()), (2, True))
        expect_raises(f"{action}: a source with a transparent pixel is refused",
                      ValueError, lambda a=action, e=extra: recipes.make_request(
                          "walk", a, SEED, source_png=rgba_of(
                              FLAT_PNG, ((3, 3), 100)), **e),
                      "transparent")
    expect("img2img: --from's source replaces the mannequin init; absent, "
           "the init is sent",
           (decoded(recipes.make_request("walk", "img2img", SEED,
                                         source_png=FLAT_PNG)).tobytes()
            == flat_image.tobytes(), REQ_I2I.image_png == INIT_PNG),
           (True, True))
    rect2 = L5.cells[2].rect_canvas
    sent = decoded(REQ_INF)
    outside_sent, outside_flat = sent.copy(), flat_image.copy()
    outside_sent.paste((0, 0, 0), rect2)
    outside_flat.paste((0, 0, 0), rect2)
    expect("infill init: the SOURCE outside cell 2, the mannequin inside it",
           (outside_sent.tobytes() == outside_flat.tobytes(),
            sent.crop(rect2).tobytes() == init_image.crop(rect2).tobytes(),
            sent.crop(rect2).tobytes() != flat_image.crop(rect2).tobytes()),
           (True, True, True))
    expect("infill with paste_mannequin=False sends the source unchanged",
           decoded(recipes.make_request(
               "walk", "infill", SEED, source_png=FLAT_PNG, cell=2,
               paste_mannequin=False)).tobytes() == flat_image.tobytes(), True)

    # -- the init encodes left/right only through far-limb shading ----------
    init_colours = {rgb for _n, rgb in init_image.getcolors(1 << 16)}
    pants = COLOURS["pants"]
    expect("the walk init draws the pants colour AND the far-limb pants at x0.7",
           (pants in init_colours,
            tuple(int(round(c * 0.7)) for c in pants) in init_colours),
           (True, True))

    # The detectors above can see what they claim to see.
    planted = edited(BODY_GEN, lambda b: b["parameters"]["v4_negative_prompt"][
        "caption"]["char_captions"][3]["centers"][0].__setitem__("x", 0.1))
    expect_true("control: a moved negative center is a problem",
                array_problems(planted, REQ_GEN))
    planted = edited(BODY_GEN, lambda b: b["parameters"]["v4_prompt"].__setitem__(
        "director_reference_images", []))
    planted["parameters"]["sm"] = False
    expect("control: planted never-send keys are found",
           sorted(never_send_paths(planted)),
           ["parameters.sm", "parameters.v4_prompt.director_reference_images"])

    gen_keys = set(BODY_GEN["parameters"])
    i2i_keys = set(BODY_I2I["parameters"])
    inf_keys = set(BODY_INF["parameters"])
    image_fields = {"image", "mask", "strength", "noise", "extra_noise_seed",
                    INPAINT_STRENGTH_KEY, IMG2IMG_KEY, "color_correct"}
    expect("generate carries no image field at all",
           sorted(gen_keys & image_fields), [])
    expect("img2img adds exactly image, strength, noise, extra_noise_seed, "
           "color_correct",
           (sorted(i2i_keys - gen_keys), sorted(gen_keys - i2i_keys)),
           (sorted(["image", "strength", "noise", "extra_noise_seed",
                    "color_correct"]), []))
    p = BODY_I2I["parameters"]
    expect("img2img: image is the init's own bytes, base64, no data: prefix",
           (base64.b64decode(p["image"]) == REQ_I2I.image_png
            and REQ_I2I.image_png == INIT_PNG, p["image"].startswith("data:")),
           (True, False))
    expect("img2img: strength 0.45 (author), noise, extra_noise_seed = seed-1",
           (p["strength"], p["noise"], p["extra_noise_seed"],
            p["add_original_image"], p["color_correct"]),
           (0.45, 0.05, SEED - 1, True, False))
    expect("generate: add_original_image true, model full",
           (BODY_GEN["parameters"]["add_original_image"], BODY_GEN["model"]),
           (True, MODEL_FULL))
    p = BODY_INF["parameters"]
    expect("infill adds image, mask, strength, noise, extra_noise_seed, the "
           "inpaint strength and img2img; no color_correct",
           (sorted(inf_keys - gen_keys), sorted(gen_keys - inf_keys)),
           (sorted(["image", "mask", "strength", "noise", "extra_noise_seed",
                    INPAINT_STRENGTH_KEY, IMG2IMG_KEY]), []))
    expect("infill: an inpainting model, add_original_image false",
           (BODY_INF["model"], BODY_INF["model"].endswith("-inpainting"),
            p["add_original_image"]),
           (MODEL_FULL_INPAINTING, True, False))
    expect("infill: the mask is present and is the RGBA mask of cell 2",
           (base64.b64decode(p["mask"]) == masks.cell_mask(L5, 2),
            request.png_header(base64.b64decode(p["mask"]))),
           (True, (L5.width, L5.height, 6)))
    expect("infill: every strength is the author's 0.45, extra_noise_seed = "
           "seed-1",
           (p["strength"], p[INPAINT_STRENGTH_KEY], p[IMG2IMG_KEY],
            p["noise"], p["extra_noise_seed"]),
           (0.45, 0.45, {"strength": 0.45, "color_correct": True}, 0,
            SEED - 1))
    full = request.build_body(recipes.make_request(
        "walk", "infill", SEED, source_png=FLAT_PNG, cell=2,
        inpaint_strength=1.0))
    expect("infill at 1.0 sends no nested img2img object",
           IMG2IMG_KEY in full["parameters"], False)
    expect("the same Request builds an equal body twice",
           request.build_body(REQ_INF) == BODY_INF, True)

    # -- the builder refuses what it cannot spell ---------------------------
    rgb_mask = png_bytes(Image.new("RGB", (L5.width, L5.height)))
    expect_raises("generate carrying an image is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(
                      REQ_GEN, image_png=INIT_PNG)), "must not carry image_png")
    expect_raises("img2img without a strength is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(
                      REQ_I2I, strength=None)), "needs strength")
    expect_raises("infill carrying a top-level strength is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(
                      REQ_INF, strength=0.45)), "must not carry strength")
    expect_raises("an infill mask that is RGB, not RGBA, is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(
                      REQ_INF, mask_png=rgb_mask)), "colour type 2")
    expect_raises("an image of the wrong size is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(
                      REQ_I2I, image_png=png_bytes(Image.new("RGB", (64, 64))))),
                  "64x64")
    expect_raises("a seed below 2 is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(REQ_GEN,
                                                                 seed=1)),
                  "seed 1")
    expect_raises("a center that is not a pair is refused", ValueError,
                  lambda: request.build_body(dataclasses.replace(
                      REQ_GEN, frames=(Frame("boy", "", (0.1,)),))),
                  "not an (x, y) pair")
    expect_raises("the brief's old img2img strength 0.60 is outside the band",
                  ValueError,
                  lambda: recipes.make_request("walk", "img2img", SEED,
                                               strength=0.6),
                  "outside the author's band")
    expect("...and both ends of the 0.35-0.55 band are accepted",
           [recipes.make_request("walk", "img2img", SEED, strength=s).strength
            for s in (0.35, 0.55)], [0.35, 0.55])
    expect_raises("a rating tag in pose words is refused", ValueError,
                  lambda: recipes.character_caption(WALK.identity,
                                                    "walking, rating:general"),
                  "rating tag")

    # =======================================================================
    print("\n2. assert_free: the legal request passes, each refusal has its own reason")
    # =======================================================================
    ACCOUNT = Account(tier=3, active=True, grace=None, fixed=1000, purchased=0)
    CLEAN = scratch_state("clean")
    PROOF_I2I = Proof("img2img", MODEL_FULL, "1216x832", "2026-09-17",
                      "probe-i2i")
    PROOF_INF = Proof("infill", MODEL_FULL_INPAINTING, "1216x832", "2026-09-17",
                      "probe-inf")
    PROOF_INF_CURATED = Proof("infill", MODEL_CURATED, "1216x832",
                              "2026-09-17", "probe-inf-curated")

    def ledger_row(total: int, *, ledger_id="fixture", after=None,
                   action=None, model=None, verdict=None) -> dict:
        row = dict.fromkeys(LEDGER_FIELDS)
        before_row = Account(3, True, None, total, 0).as_row()
        after_row = Account(3, True, None,
                            total if after is None else after, 0).as_row()
        row.update(ledger_id=ledger_id, kind="generation", action=action,
                   model=model, verdict=verdict, account_before=before_row,
                   account_after=after_row, delta=after_row["sum"] - total,
                   locked=False)
        return row

    def probe_row(proof, total=1000, **fields):
        """A probe row as run.run_request writes a clean one: 2xx, the image
        extracted and stored, delta 0, no LOCK. `fields` overrides any key."""
        row = ledger_row(total, ledger_id=proof.ledger_id,
                         action=proof.action, model=proof.model,
                         verdict="probe")
        row.update(http_status=200, output_png_sha256="ab" * 32,
                   output_path="blobs/" + "ab" * 32 + ".png")
        row.update(fields)
        return row

    CHAINED = scratch_state("chained")
    CHAINED.write_row(ledger_row(1000))
    # Every proof a passing test uses names a probe row of its own pair, and
    # each probe row is followed by a read at the same balance (or, for the
    # last one, confirmed by the ACCOUNT read itself): the chain confirms it.
    PROVEN = scratch_state("proven")
    for proven_by in (PROOF_I2I, PROOF_INF, PROOF_INF_CURATED):
        PROVEN.write_row(probe_row(proven_by))
    LOCKED = scratch_state("locked")
    LOCKED.lock("fixture", "check_nai fixture")
    INFLIGHT = scratch_state("inflight")
    INFLIGHT.acquire_inflight("fixture")

    def failing(body, *, account=ACCOUNT, proofs=(), state=CLEAN,
                url=GENERATE_URL, probe=False):
        return [v.condition for v in guard.evaluate(
            body, account, proofs, state, url=url, probe=probe)
            if v.ok is not True]

    def passes(label, body, **kwargs):
        asserted.append(1)
        try:
            guard.assert_free(body, kwargs.get("account", ACCOUNT),
                              kwargs.get("proofs", ()),
                              kwargs.get("state", CLEAN),
                              url=kwargs.get("url", GENERATE_URL),
                              probe=kwargs.get("probe", False))
        except Exception as exc:  # noqa: BLE001 - reporting tool
            print(f"  FAIL {label:<66} {type(exc).__name__}: {str(exc)[:120]}")
            failures.append(label)
            return
        print(f"  ok   {label:<66} passed")
        expect("...and evaluate agrees: no condition fails",
               failing(body, **kwargs), [])

    def refused(label, condition, fragment, body, **kwargs):
        """Refused with exactly `condition`, naming `fragment`, and no other
        condition failing -- so the reason is this refusal's own."""
        asserted.append(1)
        try:
            guard.assert_free(body, kwargs.get("account", ACCOUNT),
                              kwargs.get("proofs", ()),
                              kwargs.get("state", CLEAN),
                              url=kwargs.get("url", GENERATE_URL),
                              probe=kwargs.get("probe", False))
        except guard.Refused as exc:
            got = (exc.condition, fragment in exc.message,
                   failing(body, **kwargs))
            want = (condition, True, [condition])
            ok = got == want
            print(f"  {'ok  ' if ok else 'FAIL'} {label:<66} condition "
                  f"{exc.condition}: {exc.message[:90]}"
                  + ("" if ok else f"  got={got} want={want}"))
            if not ok:
                failures.append(label)
            return
        except Exception as exc:  # noqa: BLE001 - reporting tool
            print(f"  FAIL {label:<66} raised {type(exc).__name__}: {exc}")
            failures.append(label)
            return
        print(f"  FAIL {label:<66} was NOT refused")
        failures.append(label)

    def set_param(key, value):
        return lambda b: b["parameters"].__setitem__(key, value)

    passes("a legal generate passes", BODY_GEN)
    passes("the curated variant passes too", request.build_body(
        recipes.make_request("walk", "generate", SEED, variant="curated")))
    passes("img2img passes WITH its confirmed proof row", BODY_I2I,
           proofs=(PROOF_I2I,), state=PROVEN)
    passes("infill passes WITH its confirmed proof row", BODY_INF,
           proofs=(PROOF_INF,), state=PROVEN)
    passes("an img2img probe in probe shape passes with no proof yet",
           guard.probe_body("img2img", seed=SEED), probe=True)
    passes("a balance equal to the last row passes the chain", BODY_GEN,
           state=CHAINED)
    passes("a balance ABOVE the last row (a refill) passes the chain", BODY_GEN,
           state=CHAINED, account=dataclasses.replace(ACCOUNT, fixed=1500))
    passes("grace False is not grace", BODY_GEN,
           account=dataclasses.replace(ACCOUNT, grace=False))
    passes("1024x1024 is the largest legal area", edited(
        BODY_GEN, lambda b: (b["parameters"].__setitem__("width", 1024),
                             b["parameters"].__setitem__("height", 1024))))

    refused("area 1280x1024 is over 1048576", 3, "exceeds 1048576",
            edited(BODY_GEN, lambda b: (
                b["parameters"].__setitem__("width", 1280),
                b["parameters"].__setitem__("height", 1024))))
    refused("width 1200 is not a multiple of 64", 3, "width 1200",
            edited(BODY_GEN, set_param("width", 1200)))
    refused("height 830 is not a multiple of 64", 3, "height 830",
            edited(BODY_GEN, set_param("height", 830)))
    refused("steps 29 is over 28", 4, "steps 29",
            edited(BODY_GEN, set_param("steps", 29)))
    refused("n_samples 2 always costs", 4, "n_samples 2",
            edited(BODY_GEN, set_param("n_samples", 2)))
    refused("a V5 model is refused", 2, "nai-diffusion-5-full",
            edited(BODY_GEN, lambda b: b.__setitem__(
                "model", "nai-diffusion-5-full")))
    refused("a V3 model is refused", 2, "nai-diffusion-3",
            edited(BODY_GEN, lambda b: b.__setitem__("model", "nai-diffusion-3")))
    refused("an inpainting model is refused for generate", 2,
            "not legal for generate",
            edited(BODY_GEN, lambda b: b.__setitem__("model",
                                                     MODEL_CURATED_INPAINTING)))
    refused("a base model is refused for infill", 2, "not legal for infill",
            edited(BODY_INF, lambda b: b.__setitem__("model", MODEL_CURATED)),
            proofs=(PROOF_INF, PROOF_INF_CURATED), state=PROVEN)
    for key, value, where in (
            ("director_reference_images", [], "parameters"),
            ("reference_image_multiple", [], "parameters"),
            ("characterRef", {}, "parameters"),
            ("stream", True, "parameters"),
            ("image_format", "png", "parameters"),
            ("sm", True, "parameters"),
            ("tag_hint_x", 1, "parameters.v4_prompt")):
        def plant(b, key=key, value=value, where=where):
            target = b["parameters"]
            if where.endswith("v4_prompt"):
                target = target["v4_prompt"]
            target[key] = value
        refused(f"never-send key {where}.{key} is refused", 5,
                f"{where}.{key}", edited(BODY_GEN, plant))

    seven = dataclasses.replace(REQ_GEN, frames=REQ_GEN.frames + (
        Frame("boy, standing", "", (0.1, 0.3)),
        Frame("boy, standing", "", (0.3, 0.3))))
    refused("7 frames is over V4.5's 6", 6, "7 character captions",
            request.build_body(seven))
    passes("...while 6 frames pass", request.build_body(dataclasses.replace(
        seven, frames=seven.frames[:6])))
    off_grid = dataclasses.replace(REQ_GEN, frames=(
        dataclasses.replace(REQ_GEN.frames[0], center=(0.2, 0.5)),)
        + REQ_GEN.frames[1:])
    refused("an off-grid center (0.2) is refused", 6, "not on the 0.1..0.9 grid",
            request.build_body(off_grid))
    duplicate = dataclasses.replace(REQ_GEN, frames=(
        REQ_GEN.frames[0],
        dataclasses.replace(REQ_GEN.frames[1], center=REQ_GEN.frames[0].center))
        + REQ_GEN.frames[2:])
    refused("two frames sharing a center are refused", 6, "share the center",
            request.build_body(duplicate))
    refused("a characterPrompts center edited after the build is refused", 6,
            "center differs",
            edited(BODY_GEN, lambda b: b["parameters"]["characterPrompts"][2][
                "center"].__setitem__("x", 0.9)))
    refused("a negative center edited after the build is refused", 6,
            "center differs",
            edited(BODY_GEN, lambda b: b["parameters"]["v4_negative_prompt"][
                "caption"]["char_captions"][4]["centers"][0].__setitem__("y",
                                                                        0.1)))
    refused("input edited away from base_caption is refused", 6,
            "input differs",
            edited(BODY_GEN, lambda b: b.__setitem__("input", QUALITY_TAIL)))
    refused("negative_prompt edited away from its base is refused", 6,
            "negative_prompt differs",
            edited(BODY_GEN, set_param("negative_prompt", "lowres")))
    non_ascii = dataclasses.replace(REQ_GEN, frames=(
        dataclasses.replace(REQ_GEN.frames[0],
                            caption=REQ_GEN.frames[0].caption + ", café"),)
        + REQ_GEN.frames[1:])
    refused("a non-ASCII caption is refused", 7, "is not ASCII",
            request.build_body(non_ascii))
    refused("a rating tag in a character caption is refused", 7,
            "carries a rating tag",
            request.build_body(dataclasses.replace(REQ_GEN, frames=(
                dataclasses.replace(REQ_GEN.frames[0],
                                    caption="boy, rating:general"),)
                + REQ_GEN.frames[1:])))
    refused("a base caption not closed by rating:general is refused", 7,
            "does not end with",
            request.build_body(dataclasses.replace(
                REQ_GEN, base_caption=REQ_GEN.base_caption[:-len(RATING_TAG)]
                + "rating:safe")))
    refused("tier 2 is not Opus", 8, "tier is 2", BODY_GEN,
            account=dataclasses.replace(ACCOUNT, tier=2))
    refused("an inactive subscription is refused", 8, "active is False",
            BODY_GEN, account=dataclasses.replace(ACCOUNT, active=False))
    refused("a grace period is refused", 8, "grace period", BODY_GEN,
            account=dataclasses.replace(ACCOUNT, grace=True))
    refused("a balance BELOW the last ledger row is refused", 9,
            "balance fell from 1000 to 998", BODY_GEN, state=CHAINED,
            account=dataclasses.replace(ACCOUNT, fixed=998))
    refused("LOCK present is refused", 10, "LOCK present", BODY_GEN,
            state=LOCKED)
    refused("INFLIGHT present is refused", 10, "INFLIGHT present", BODY_GEN,
            state=INFLIGHT)
    refused("img2img without a proof row is refused", 1,
            "no proof row for (img2img, nai-diffusion-4-5-full)", BODY_I2I)
    refused("infill without a proof row is refused", 1,
            "no proof row for (infill", BODY_INF, proofs=(PROOF_I2I,))
    refused("an img2img proof does not unlock the curated model", 1,
            "no proof row", request.build_body(recipes.make_request(
                "walk", "img2img", SEED, variant="curated")),
            proofs=(PROOF_I2I,))
    refused("a probe of a pair already proven is refused", 1,
            "already has a proof row", guard.probe_body("img2img", seed=SEED),
            probe=True, proofs=(PROOF_I2I,))
    refused("a probe body sent as production is refused", 1, "no proof row",
            guard.probe_body("infill", seed=SEED))
    refused("a probe at the production strength 0.45 is refused", 1,
            f"a probe uses exactly {PROBE_STRENGTH}",
            edited(guard.probe_body("img2img", seed=SEED),
                   set_param("strength", 0.45)), probe=True)
    refused("a probe at production steps is refused", 1,
            "steps is 23", BODY_I2I, probe=True)
    # -- condition 1: the probe's every strength, and no generate probe -----
    refused("an infill probe whose nested img2img.strength is 0.45 is refused",
            1, "parameters.img2img.strength is 0.45",
            edited(guard.probe_body("infill", seed=SEED),
                   lambda b: b["parameters"]["img2img"].__setitem__(
                       "strength", 0.45)), probe=True)
    refused("an infill probe whose top-level strength is 0.45 is refused", 1,
            "parameters.strength is 0.45",
            edited(guard.probe_body("infill", seed=SEED),
                   set_param("strength", 0.45)), probe=True)
    refused("a probe of generate is refused", 1, "a probe exists only for",
            BODY_GEN, probe=True)

    # -- condition 1: the body's image keys belong to its action ------------
    PIN_IMAGE_KEYS = ("image", "mask", "strength", "noise", "extra_noise_seed",
                      PIN_INPAINT_KEY, "img2img", "color_correct")
    donor = {**BODY_I2I["parameters"], **BODY_INF["parameters"]}

    def planted_key(body, key, value=None):
        return edited(body, lambda b: b["parameters"].__setitem__(
            key, copy.deepcopy(donor[key] if value is None else value)))

    def dropped_key(body, key):
        return edited(body, lambda b: b["parameters"].pop(key))

    for key in PIN_IMAGE_KEYS:
        refused(f"generate carrying parameters.{key} is refused", 1,
                f"may not carry parameters.{key}", planted_key(BODY_GEN, key))
    for key in ("mask", PIN_INPAINT_KEY, "img2img"):
        refused(f"img2img carrying parameters.{key} is refused, even proven",
                1, f"may not carry parameters.{key}",
                planted_key(BODY_I2I, key), proofs=(PROOF_I2I,), state=PROVEN)
    for key in ("image", "strength", "noise", "extra_noise_seed",
                "color_correct"):
        refused(f"img2img without parameters.{key} is refused", 1,
                f"must carry parameters.{key}", dropped_key(BODY_I2I, key),
                proofs=(PROOF_I2I,), state=PROVEN)
    refused("infill carrying parameters.color_correct is refused", 1,
            "may not carry parameters.color_correct",
            planted_key(BODY_INF, "color_correct", False),
            proofs=(PROOF_INF,), state=PROVEN)
    for key in ("image", "mask", "strength", "noise", "extra_noise_seed",
                PIN_INPAINT_KEY):
        refused(f"infill without parameters.{key} is refused", 1,
                f"must carry parameters.{key}", dropped_key(BODY_INF, key),
                proofs=(PROOF_INF,), state=PROVEN)
    refused("infill at 0.45 without its nested img2img object is refused", 1,
            "must carry parameters.img2img", dropped_key(BODY_INF, "img2img"),
            proofs=(PROOF_INF,), state=PROVEN)
    refused("infill at 1.0 WITH a nested img2img object is refused", 1,
            "may not carry parameters.img2img",
            planted_key(full, "img2img"), proofs=(PROOF_INF,), state=PROVEN)

    # -- condition 1: a proof counts only when the chain confirms it --------
    refused("a proof naming no ledger row is refused", 1, "not in the ledger",
            BODY_I2I, proofs=(dataclasses.replace(PROOF_I2I,
                                                  ledger_id="no-such-row"),),
            state=PROVEN)
    refused("a proof naming a row that is not its probe is refused", 1,
            "which is not a probe of",
            BODY_I2I, proofs=(dataclasses.replace(PROOF_I2I,
                                                  ledger_id="fixture"),),
            state=CHAINED)
    LATE = scratch_state("late_debit")
    LATE.write_row(probe_row(PROOF_I2I))
    LATE.write_row(ledger_row(998, ledger_id="after-the-probe"))
    refused("a proof the NEXT read refutes (a late debit of 2) is refused for "
            "good", 1, "REFUTED", BODY_I2I, proofs=(PROOF_I2I,), state=LATE,
            account=dataclasses.replace(ACCOUNT, fixed=998))
    PENDING = scratch_state("pending_proof")
    PENDING.write_row(probe_row(PROOF_I2I))
    refused("a pending proof whose next read is a refill (+50) is refuted: a "
            "refill can hide a charge", 1, "REFUTED", BODY_I2I,
            proofs=(PROOF_I2I,), state=PENDING,
            account=dataclasses.replace(ACCOUNT, fixed=1050))
    passes("a pending proof that this very read confirms passes", BODY_I2I,
           proofs=(PROOF_I2I,), state=PENDING)
    expect("offline, a pending proof is ok=None -- needs the read -- not a pass",
           [(v.condition, v.ok) for v in guard.evaluate(
               BODY_I2I, None, (PROOF_I2I,), PENDING, url=GENERATE_URL)
            if v.condition == 1], [(1, None)])

    # -- condition 1: the probe row a proof names must have MEASURED something
    # Each field of the one rule gets its own hollow probe row, so a mutation
    # that drops any clause turns exactly its line red. Every one of these
    # rows would be confirmed by the read (balance unchanged since it).
    for label, fields, total in (
            ("2xx whose response gave NO image (HTML, empty, 204, JSON)",
             dict(output_png_sha256=None, output_path=None), 1000),
            ("HTTP 500", dict(http_status=500), 1000),
            ("no HTTP status (a timeout)", dict(http_status=None), 1000),
            ("a balance that fell 1000 -> 998",
             dict(account_after=Account(3, True, None, 998, 0).as_row(),
                  delta=-2), 998),
            ("LOCK written (an interrupted send)", dict(locked=True), 1000)):
        hollow = scratch_state("hollow_probe")
        hollow.write_row(probe_row(PROOF_I2I, **fields))
        refused(f"a proof naming a probe row with {label} is refused", 1,
                "which proves nothing", BODY_I2I, proofs=(PROOF_I2I,),
                state=hollow, account=dataclasses.replace(ACCOUNT, fixed=total))

    # -- condition 1: a LATER charged call of the pair refutes the proof ----
    def pair_row(before, after, ledger_id, *, action="img2img", model=MODEL_FULL,
                 kind="generation", **fields):
        row = ledger_row(before, ledger_id=ledger_id, after=after,
                         action=action, model=model)
        row.update(kind=kind, locked=after < before)
        row.update(fields)
        return row

    def ledger_of(tag, *rows):
        made = scratch_state(tag)
        for row in rows:
            made.write_row(row)
        return made

    refused("a CONFIRMED proof is refuted by a later img2img call charged "
            "1000 -> 992", 1, "REFUTED by ledger row i2i-charged", BODY_I2I,
            proofs=(PROOF_I2I,), state=ledger_of(
                "later_charged", probe_row(PROOF_I2I),
                pair_row(1000, 992, "i2i-charged")),
            account=dataclasses.replace(ACCOUNT, fixed=992))
    refused("...and by a later img2img call whose balance after was never read",
            1, "never read", BODY_I2I, proofs=(PROOF_I2I,), state=ledger_of(
                "later_unread", probe_row(PROOF_I2I),
                pair_row(1000, 1000, "i2i-unread", account_after=None,
                         delta=None, locked=True)))
    refused("...and by a debit landing after a clean later img2img call (the "
            "next read is 995)", 1, "a late charge", BODY_I2I,
            proofs=(PROOF_I2I,), state=ledger_of(
                "later_late_debit", probe_row(PROOF_I2I),
                pair_row(1000, 1000, "i2i-clean"),
                pair_row(995, 995, "chain-charged", action="generate",
                         kind="refused", locked=True)),
            account=dataclasses.replace(ACCOUNT, fixed=995))
    expect("...and by THIS read when it is below the last img2img call's after "
           "(condition 9 fails beside it)",
           guard.proof_standing(PROOF_I2I, [probe_row(PROOF_I2I),
                                            pair_row(1000, 1000, "i2i-clean")],
                                995)[0], False)
    passes("but a later CLEAN img2img call and a charged GENERATE call leave "
           "it standing", BODY_I2I, proofs=(PROOF_I2I,), state=ledger_of(
               "later_other_pair", probe_row(PROOF_I2I),
               pair_row(1000, 1000, "i2i-clean"),
               pair_row(1000, 998, "gen-charged", action="generate")),
           account=dataclasses.replace(ACCOUNT, fixed=998))
    passes("...a charged img2img call of the CURATED model leaves the full "
           "model's proof standing", BODY_I2I, proofs=(PROOF_I2I,),
           state=ledger_of("later_other_model", probe_row(PROOF_I2I),
                           pair_row(1000, 992, "curated-charged",
                                    model=MODEL_CURATED)),
           account=dataclasses.replace(ACCOUNT, fixed=992))
    passes("...a rise across a later img2img call (+50) does not refute it",
           BODY_I2I, proofs=(PROOF_I2I,), state=ledger_of(
               "later_rise", probe_row(PROOF_I2I),
               pair_row(1000, 1050, "i2i-rise")),
           account=dataclasses.replace(ACCOUNT, fixed=1050))
    passes("...and a charged img2img call BEFORE a fresh probe does not refute "
           "that probe's proof", BODY_I2I, proofs=(PROOF_I2I,),
           state=ledger_of("charged_before_reprobe",
                           pair_row(1000, 992, "i2i-old-charged"),
                           probe_row(PROOF_I2I, total=992),
                           # a row AFTER the probe, so the later-call scan runs
                           pair_row(992, 992, "i2i-after-reprobe")),
           account=dataclasses.replace(ACCOUNT, fixed=992))

    # -- condition 6: every parallel-array sub-rule --------------------------
    refused("characterPrompts[1].enabled false is refused", 6,
            "enabled is not true",
            edited(BODY_GEN, lambda b: b["parameters"]["characterPrompts"][1]
                   .__setitem__("enabled", False)))
    refused("a prompt edited in characterPrompts only is refused", 6,
            "prompt differs",
            edited(BODY_GEN, lambda b: b["parameters"]["characterPrompts"][2]
                   .__setitem__("prompt", REQ_GEN.frames[2].caption
                                + ", smiling")))
    refused("a uc edited in characterPrompts only is refused", 6,
            "uc differs",
            edited(BODY_GEN, lambda b: b["parameters"]["characterPrompts"][0]
                   .__setitem__("uc", "lowres")))
    refused("parameters.use_coords false is refused", 6,
            "parameters.use_coords is not true",
            edited(BODY_GEN, set_param("use_coords", False)))
    refused("parameters.v4_prompt.use_coords false is refused", 6,
            "parameters.v4_prompt.use_coords is not true",
            edited(BODY_GEN, lambda b: b["parameters"]["v4_prompt"]
                   .__setitem__("use_coords", False)))

    def sixth(path):
        def change(b):
            target = b["parameters"]
            for part in path:
                target = target[part]
            extra = copy.deepcopy(target[0])
            if "center" in extra:
                extra["center"] = {"x": 0.1, "y": 0.3}
            else:
                extra["centers"] = [{"x": 0.1, "y": 0.3}]
            target.append(extra)
        return change
    refused("a 6th entry in characterPrompts only is refused", 6,
            "characterPrompts has 6 entries",
            edited(BODY_GEN, sixth(("characterPrompts",))))
    refused("a 6th negative char_caption only is refused", 6,
            "v4_negative_prompt has 6 captions",
            edited(BODY_GEN, sixth(("v4_negative_prompt", "caption",
                                    "char_captions"))))

    # -- condition 7: the token budget and the UC text -----------------------
    def everywhere(b, index, caption):
        b["parameters"]["characterPrompts"][index]["prompt"] = caption
        b["parameters"]["v4_prompt"]["caption"]["char_captions"][index][
            "char_caption"] = caption
    refused("a caption 400 words past the token budget is refused", 7,
            "exceeds the budget",
            edited(BODY_GEN, lambda b: everywhere(
                b, 0, REQ_GEN.frames[0].caption + ", "
                + ", ".join(["walking"] * 400))))
    for label, uc, fragment in (("a non-ASCII uc", "lowres, caf\u00e9",
                                 "is not ASCII"),
                                ("rating: in a uc", "rating:general",
                                 "carries a rating tag")):
        refused(f"{label} (both parallel arrays) is refused", 7, fragment,
                request.build_body(dataclasses.replace(REQ_GEN, frames=(
                    dataclasses.replace(REQ_GEN.frames[0], uc=uc),)
                    + REQ_GEN.frames[1:])))

    # -- condition 9: a lost ledger is not a first run -----------------------
    LOST = scratch_state("lost_ledger")
    LOST.save_blob(request.canonical_json(BODY_GEN), "json")
    refused("an empty ledger beside blobs/ is a LOST ledger, refused", 9,
            "LOST", BODY_GEN, state=LOST)
    LOST_PROOFS = scratch_state("lost_ledger_proofs")
    LOST_PROOFS.add_proof(PROOF_I2I)
    refused("...and beside proofs.json", 9, "LOST", BODY_GEN,
            state=LOST_PROOFS)

    for url in ("https://api.novelai.net/ai/generate-image",
                "https://image.novelai.net/ai/generate-image-stream",
                "http://image.novelai.net/ai/generate-image",
                SUBSCRIPTION_URL):
        refused(f"endpoint {url.split('//')[1][:44]} is refused", 11,
                "not an allowlisted generation endpoint", BODY_GEN, url=url)
    expect("assert_endpoint lets GET /user/subscription through",
           guard.assert_endpoint("GET", SUBSCRIPTION_URL), None)
    for method, url in (("GET", GENERATE_URL), ("POST", SUBSCRIPTION_URL),
                        ("GET", "https://api.novelai.net/user/subscription"),
                        ("POST", "https://image.novelai.net/ai/upscale")):
        exc = expect_raises(f"assert_endpoint refuses {method} "
                            f"{url.split('//')[1][:40]}", guard.Refused,
                            lambda m=method, u=url: guard.assert_endpoint(m, u),
                            "not an allowlisted endpoint")
        expect("...as condition 11", getattr(exc, "condition", None), 11)
    expect_raises("assert_free with no account read refuses to judge",
                  TypeError, lambda: guard.assert_free(
                      BODY_GEN, None, (), CLEAN, url=GENERATE_URL),
                  "live account read")

    # =======================================================================
    print("\n3. run_request: one POST between two balance reads, never a retry")
    # =======================================================================
    OUT_PNG = INIT_PNG

    def sub(total: int, **kwargs):
        return (200, {"content-type": "application/json"},
                tp.fake_subscription_body(fixed=total, **kwargs))

    def zipped():
        return (200, {"content-type": "binary/octet-stream"},
                tp.fake_zip(OUT_PNG))

    def error(status: int, message: str):
        return (status, {"content-type": "application/json"},
                json.dumps({"statusCode": status, "message": message}).encode())

    GET = ("GET", SUBSCRIPTION_URL)
    POST = ("POST", GENERATE_URL)

    def scripted(req, responses, *, state=None, probe=False,
                 context=LedgerContext(), reset=True):
        if reset:
            run.reset_latch_for_checks()
        state = state or scratch_state("run")
        transport = tp.RecordingTransport(list(responses))
        row, exc = None, None
        try:
            row = run.run_request(req, transport, state, probe=probe,
                                  context=context)
        except Exception as caught:  # noqa: BLE001 - inspected below
            exc = caught
        pattern = [(c.method, c.url) for c in transport.calls]
        return transport, state, row, exc, pattern

    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(), sub(1000),
                                                  zipped()])
    expect("success: GET, POST, GET -- the balance read before AND after",
           (pattern, exc), ([GET, POST, GET], None))
    expect("success: exactly one POST, and the spare response untouched",
           (len(t.posts), len(t.responses)), (1, 1))
    expect("success: the row says 200, delta 0, stored the PNG, no LOCK",
           (row["http_status"], row["delta"], row["locked"],
            bool(row["output_path"]), st.locked(), st.inflight()),
           (200, 0, False, True, False, False))
    expect("success: the body sent is build_body's",
           t.posts[0].body == request.build_body(REQ_GEN), True)
    t2, _st, _row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(),
                                                     sub(1000)], reset=False)
    expect("a second send in the same process is refused (condition 12), "
           "reading nothing",
           (getattr(exc, "condition", None), pattern), (12, []))

    for label, failure, want_status, fragment in (
            ("HTTP 500", error(500, "internal"), 500, "HTTP 500"),
            ("HTTP 429", error(429, "concurrent generation"), 429, "HTTP 429"),
            ("a raised timeout", tp.TransportTimeout("POST timed out"), None,
             "timeout"),
            ("a connection error", tp.TransportError("POST connection failed"),
             None, "transport error")):
        t, st, row, exc, pattern = scripted(
            REQ_GEN, [sub(1000), failure, sub(1000), zipped(), sub(1000)])
        expect(f"{label}: GET, POST, GET -- read after, whatever happened",
               (pattern, exc), ([GET, POST, GET], None))
        expect(f"{label}: no retry -- one POST, two responses left over",
               (len(t.posts), len(t.responses)), (1, 2))
        expect(f"{label}: the row records it, delta 0, no LOCK, INFLIGHT gone",
               (row["http_status"], fragment in (row["error_message"] or ""),
                row["delta"], st.locked(), st.inflight(), len(st.rows())),
               (want_status, True, 0, False, False, 1))

    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(), sub(998)])
    expect("a decrease across the call writes LOCK and says so in the row",
           (pattern, row["delta"], row["locked"], st.locked()),
           ([GET, POST, GET], -2, True, True))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(998), zipped(), sub(998)],
                                         state=st)
    expect("...and the next call is refused (10) before ANY request, no row",
           (getattr(exc, "condition", None), pattern, len(t.responses),
            len(st.rows())), (10, [], 3, 1))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(998), zipped(), sub(998)],
                                        state=CHAINED)
    expect("a charge landing BETWEEN invocations: refused (9), LOCK, no POST",
           (getattr(exc, "condition", None), pattern, st.locked(),
            st.rows()[-1]["kind"], st.rows()[-1]["locked"]),
           (9, [GET], True, "refused", True))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(),
                                                  error(500, "down")])
    expect("a failed balance read AFTER the send: LOCK, row written, raised",
           (pattern, type(exc).__name__, st.locked(), st.inflight(),
            st.rows()[-1]["account_after"] if st.rows() else "no row"),
           ([GET, POST, GET], "AccountReadError", True, False, None))
    t, st, row, exc, pattern = scripted(REQ_GEN, [error(401, "Unauthorized")])
    expect("a failed balance read BEFORE the send: nothing sent, no row",
           (pattern, type(exc).__name__, len(st.rows()), st.locked()),
           ([GET], "AccountReadError", 0, False))
    t, st, row, exc, pattern = scripted(REQ_I2I, [sub(1000), zipped(), sub(1000)])
    expect("img2img with no proof row: refused (1) after the read, no POST",
           (getattr(exc, "condition", None), pattern, st.rows()[-1]["kind"]),
           (1, [GET], "refused"))

    PROBE_CTX = LedgerContext(strip="walk", phase="probe", probe_flag_used=True)
    probe_i2i = guard.probe_request("img2img", seed=SEED)
    probe_inf = guard.probe_request("infill", seed=SEED)
    t, st, row, exc, pattern = scripted(probe_i2i, [sub(1000), zipped(),
                                                    sub(1000)],
                                        probe=True, context=PROBE_CTX)
    expect("probe, 2xx, delta 0: the proof row is written",
           (pattern, [(p.action, p.model) for p in st.proofs()],
            row["verdict"], st.proofs()[0].ledger_id == row["ledger_id"]
            if st.proofs() else False),
           ([GET, POST, GET], [("img2img", MODEL_FULL)], "probe", True))
    passes("...and that proof then unlocks production img2img", BODY_I2I,
           proofs=st.proofs(), state=st)
    t, _st, _row, exc, pattern = scripted(probe_i2i, [sub(1000), zipped(),
                                                      sub(1000)],
                                          state=st, probe=True,
                                          context=PROBE_CTX)
    expect("...and a second probe of the same pair is refused, no POST",
           (getattr(exc, "condition", None), pattern), (1, [GET]))
    t, st, row, exc, pattern = scripted(probe_inf, [sub(1000), zipped(),
                                                    sub(1000)],
                                        probe=True, context=PROBE_CTX)
    expect("infill probe, 2xx, delta 0: the proof names the inpainting model",
           [(p.action, p.model) for p in st.proofs()],
           [("infill", MODEL_FULL_INPAINTING)])
    for label, script, locks in (
            ("2xx with delta -2", [sub(1000), zipped(), sub(998)], True),
            ("2xx with delta +50 (inconclusive)", [sub(1000), zipped(),
                                                   sub(1050)], False),
            ("HTTP 500 with delta 0", [sub(1000), error(500, "x"), sub(1000)],
             False),
            ("a timeout with delta 0", [sub(1000), tp.TransportTimeout("t"),
                                        sub(1000)], False),
            # 2xx with an unchanged balance but NO image: nothing shows a
            # generation happened, so nothing is measured.
            ("HTTP 200 carrying an HTML page, delta 0",
             [sub(1000), (200, {"content-type": "text/html"},
                          b"<html>maintenance</html>"), sub(1000)], False),
            ("HTTP 200 with an empty body, delta 0",
             [sub(1000), (200, {}, b""), sub(1000)], False),
            ("HTTP 204, delta 0", [sub(1000), (204, {}, b""), sub(1000)],
             False),
            ("HTTP 200 carrying JSON, delta 0",
             [sub(1000), (200, {"content-type": "application/json"},
                          b'{"queued":true}'), sub(1000)], False),
            ("HTTP 200 with a ZIP whose image is the wrong size, delta 0",
             [sub(1000), (200, {}, tp.fake_zip(png_bytes(
                 Image.new("RGB", (64, 64), (1, 2, 3))))), sub(1000)], False)):
        t, st, row, exc, pattern = scripted(probe_i2i, script, probe=True,
                                            context=PROBE_CTX)
        expect(f"probe, {label}: NO proof row",
               (pattern, st.proofs(), st.locked()),
               ([GET, POST, GET], (), locks))
    t, st, row, exc, pattern = scripted(
        probe_inf, [sub(1000), (200, {"content-type": "text/html"},
                                b"<html>maintenance</html>"), sub(1000)],
        probe=True, context=PROBE_CTX)
    expect("infill probe, HTTP 200 carrying an HTML page, delta 0: NO proof row",
           (pattern, st.proofs(), row["output_path"] if row else "no row"),
           ([GET, POST, GET], (), None))

    # -- a later charged call of a proven pair refutes its proof ------------
    def proven_pair(tag, probe_req=probe_i2i):
        made = scratch_state(tag)
        scripted(probe_req, [sub(1000), zipped(), sub(1000)], state=made,
                 probe=True, context=PROBE_CTX)
        return made

    def lock_text_of(made):
        if not made.locked():
            return ""
        with open(made.lock_path, encoding="utf-8") as handle:
            return handle.read()

    for action, req, probe_req in (("img2img", REQ_I2I, probe_i2i),
                                   ("infill", REQ_INF, probe_inf)):
        seq = proven_pair(f"charged_{action}", probe_req)
        t, _st, row, exc, pattern = scripted(req, [sub(1000), zipped(),
                                                   sub(992)], state=seq)
        expect(f"a production {action} charged 1000 -> 992 after its proof: "
               f"LOCK says '{action} is charged: stay on the generate track'",
               (pattern, row["delta"] if row else exc,
                f"{action} is charged: stay on the generate track"
                in lock_text_of(seq)), ([GET, POST, GET], -8, True))
        if seq.locked():
            os.remove(seq.lock_path)   # the author, by hand
        t, _st, row, exc, pattern = scripted(req, [sub(992), zipped(),
                                                   sub(984)], state=seq)
        expect(f"...LOCK deleted by hand: the next {action} is refused (1) as "
               f"REFUTED after one GET, no POST",
               (getattr(exc, "condition", None), "REFUTED" in str(exc),
                pattern), (1, True, [GET]))
    seq = proven_pair("unread_img2img")
    scripted(REQ_I2I, [sub(1000), zipped(), error(500, "down")], state=seq)
    if seq.locked():
        os.remove(seq.lock_path)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(1000), zipped(),
                                                   sub(992)], state=seq)
    expect("a production img2img whose after-read failed refutes the proof: "
           "LOCK deleted, the next img2img is refused (1), no POST",
           (getattr(exc, "condition", None), "never read" in str(exc),
            pattern), (1, True, [GET]))
    seq = proven_pair("late_after_img2img")
    scripted(REQ_I2I, [sub(1000), zipped(), sub(1000)], state=seq)
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995)], state=seq)
    lock_text = lock_text_of(seq)
    expect("a debit landing after a CLEAN production img2img: refused (9), "
           "LOCK naming the proof it refutes",
           (getattr(exc, "condition", None), "refutes its proof" in lock_text,
            "img2img is charged: stay on the generate track" in lock_text),
           (9, True, True))
    if seq.locked():
        os.remove(seq.lock_path)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...LOCK deleted: img2img is refused (1) as REFUTED, no POST",
           (getattr(exc, "condition", None), "REFUTED" in str(exc), pattern),
           (1, True, [GET]))
    seq = proven_pair("late_after_generate")
    scripted(REQ_GEN, [sub(1000), zipped(), sub(1000)], state=seq)
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995)], state=seq)
    expect("but a debit landing after a GENERATE call names no proof in LOCK",
           (getattr(exc, "condition", None), "refutes its proof"
            in lock_text_of(seq)), (9, False))
    if seq.locked():
        os.remove(seq.lock_path)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and img2img is still sent once LOCK is gone: the proof stands",
           (exc, pattern), (None, [GET, POST, GET]))
    t, st, row, exc, pattern = scripted(probe_i2i, [sub(1000), zipped(),
                                                    sub(1000)], probe=True)
    expect("a probe without the author's flag is refused before any request",
           (getattr(exc, "condition", None), pattern, st.proofs()),
           (1, [], ()))

    # -- the balance is the SUM, read through the real subscription parser --
    def sub_split(fixed: int, purchased: int):
        return (200, {"content-type": "application/json"},
                tp.fake_subscription_body(fixed=fixed, purchased=purchased))

    t, st, row, exc, pattern = scripted(REQ_GEN, [sub_split(500, 500), zipped(),
                                                  sub_split(500, 498)])
    expect("a decrease in PURCHASED Anlas alone is a charge: sum 1000 -> 998, "
           "LOCK", (pattern, row["account_before"]["sum"], row["delta"],
                    row["locked"], st.locked()),
           ([GET, POST, GET], 1000, -2, True, True))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub_split(500, 500), zipped(),
                                                  sub_split(0, 1000)])
    expect("subscription Anlas converted into paid Anlas is no change: delta "
           "0, no LOCK", (row["delta"], st.locked()), (0, False))
    for label, fields, fragment in (
            ("in its grace period", {"grace": True}, "grace period"),
            ("inactive", {"active": False}, "active is False"),
            ("on tier 2", {"tier": 2}, "tier is 2")):
        t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000, **fields),
                                                      zipped(), sub(1000)])
        expect(f"an account {label}, parsed from the wire: refused (8) after "
               f"one GET, no POST",
               (getattr(exc, "condition", None), fragment in str(exc), pattern,
                [r["kind"] for r in st.rows()]), (8, True, [GET], ["refused"]))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(),
                                                  sub(1050)])
    expect("a rise across the call (+50) is recorded inconclusive, no LOCK",
           (row["delta"], row["inconclusive"], row["locked"], st.locked()),
           (50, True, False, False))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(1048), zipped(),
                                                   sub(1048)], state=st)
    expect("...and the next read chains on that row's AFTER (1050): 1048 is a "
           "charge, refused (9), LOCK",
           (getattr(exc, "condition", None), pattern, st.locked()),
           (9, [GET], True))

    # -- an interrupt cannot skip the after-read, the row or LOCK -----------
    def interrupted(req, responses, *, state=None, probe=False,
                    context=LedgerContext()):
        run.reset_latch_for_checks()
        state = state or scratch_state("interrupt")
        transport = tp.RecordingTransport(list(responses))
        raised = None
        try:
            run.run_request(req, transport, state, probe=probe,
                            context=context)
        except KeyboardInterrupt as caught:   # only the scripted Ctrl-C
            raised = caught
        except Exception as caught:  # noqa: BLE001 - reported below
            raised = caught
        return (transport, state, type(raised).__name__,
                [(c.method, c.url) for c in transport.calls])

    t, st, raised, pattern = interrupted(REQ_GEN, [sub(1000), KeyboardInterrupt(),
                                                   sub(983)])
    rows = st.rows()
    expect("Ctrl-C during the POST: the after-read, the row and LOCK happen, "
           "THEN it is re-raised",
           (raised, pattern, len(t.responses), [r["delta"] for r in rows],
            [r["locked"] for r in rows], st.locked(), st.inflight()),
           ("KeyboardInterrupt", [GET, POST, GET], 0, [-17], [True], True,
            False))
    t, st, raised, pattern = interrupted(REQ_GEN, [sub(1000), KeyboardInterrupt(),
                                                   sub(1000)])
    lock_text = open(st.lock_path, encoding="utf-8").read() if st.locked() else ""
    expect("...with no visible charge it still LOCKs: the outcome is unknown",
           (raised, [r["delta"] for r in st.rows()], "interrupted" in lock_text,
            st.inflight()), ("KeyboardInterrupt", [0], True, False))
    t, st, raised, pattern = interrupted(REQ_GEN, [sub(1000), zipped(),
                                                   KeyboardInterrupt()])
    expect("Ctrl-C during the after-read: the row (after null), LOCK, "
           "INFLIGHT released, then re-raised",
           (raised, pattern, [r["account_after"] for r in st.rows()],
            st.locked(), st.inflight()),
           ("KeyboardInterrupt", [GET, POST, GET], [None], True, False))
    if st.locked():
        os.remove(st.lock_path)   # the author, after checking the account
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(983)], state=st)
    expect("...and on that once-empty ledger the next read still catches the "
           "17: refused (9), LOCK",
           (getattr(exc, "condition", None), pattern, st.locked()),
           (9, [GET], True))
    t, st, raised, pattern = interrupted(
        guard.probe_request("img2img", seed=SEED),
        [sub(1000), KeyboardInterrupt(), sub(1000)], probe=True,
        context=LedgerContext(strip="walk", phase="probe",
                              probe_flag_used=True))
    expect("an interrupted probe writes no proof, even at delta 0",
           (raised, st.proofs(), st.locked()), ("KeyboardInterrupt", (), True))

    killed = scratch_state("killed")
    killed.acquire_inflight("killed-mid-request", 1000)
    killed.save_blob(request.canonical_json(BODY_GEN), "json")
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(983)], state=killed)
    expect("a process killed mid-request leaves INFLIGHT, and the refusal "
           "names the balance to compare",
           (getattr(exc, "condition", None), "balance_before 1000" in str(exc),
            pattern), (10, True, []))
    os.remove(killed.inflight_path)   # the author
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(983), zipped(),
                                                   sub(983)], state=killed)
    expect("...INFLIGHT deleted beside an empty ledger and a request blob: a "
           "LOST ledger, refused (9), no row, no POST",
           (getattr(exc, "condition", None), "LOST" in str(exc), pattern,
            killed.rows(), killed.locked()), (9, True, [GET], [], False))

    # -- brief 1.4: the response shape --------------------------------------
    def corrupt_zip() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("image_0.png", OUT_PNG)
        data = bytearray(buffer.getvalue())
        start = 30 + len("image_0.png")   # local header, name, no extra field
        data[start:start + 40] = b"\xff" * 40
        return bytes(data)

    small = png_bytes(Image.new("RGB", (64, 64)))
    decoy = io.BytesIO()
    with zipfile.ZipFile(decoy, "w") as archive:
        archive.writestr("thumb.png", small)
        archive.writestr("image_0.png", OUT_PNG)
    expect("unzip_image: a non-ZIP 2xx body is BadResponse",
           str(outcome(lambda: tp.unzip_image(b"<html>busy</html>", 1216, 832)))
           .startswith("BadResponse: response body is not a ZIP"), True)
    expect("unzip_image: image_0.png of the wrong size is BadResponse",
           str(outcome(lambda: tp.unzip_image(tp.fake_zip(small), 1216, 832))),
           "BadResponse: image_0.png is 64x64; the request was 1216x832")
    expect("unzip_image: a decoy thumb.png first -- image_0.png is the one taken",
           outcome(lambda: tp.unzip_image(decoy.getvalue(), 1216, 832))
           == OUT_PNG, True)
    expect("unzip_image: a corrupt deflate stream is BadResponse, nothing else",
           str(outcome(lambda: tp.unzip_image(corrupt_zip(), 1216, 832)))
           .startswith("BadResponse: response ZIP cannot be read"), True)
    t, st, row, exc, pattern = scripted(REQ_GEN, [
        sub(1000), (200, {"content-type": "binary/octet-stream"}, corrupt_zip()),
        sub(983)])
    saved_unzip = tp.unzip_image

    def unzip_that_breaks(*_args, **_kwargs):
        raise RuntimeError("an unzip failure that is not BadResponse")
    tp.unzip_image = unzip_that_breaks
    try:
        t2, st2, row2, exc2, pattern2 = scripted(REQ_GEN, [sub(1000), zipped(),
                                                         sub(1000)])
    finally:
        tp.unzip_image = saved_unzip
    expect("run_request records ANY exception out of unzip_image: the row is "
           "written, INFLIGHT released, nothing raised",
           (type(exc2).__name__, "RuntimeError" in (row2 or {}).get(
               "error_message", ""), len(st2.rows()), st2.inflight()),
           ("NoneType", True, 1, False))
    expect("read_account maps JSON nested past the recursion limit to "
           "AccountReadError",
           str(outcome(lambda: tp.read_account(tp.RecordingTransport(
               [(200, {}, b"[" * 200000)])))).startswith("AccountReadError"),
           True)
    expect("...and through run_request: recorded, the row and LOCK written, "
           "INFLIGHT released, nothing raised",
           (exc, pattern, "bad response" in (row or {}).get("error_message", ""),
            (row or {}).get("delta"), (row or {}).get("output_path"),
            len(st.rows()), st.locked(), st.inflight()),
           (None, [GET, POST, GET], True, -17, None, 1, True, False))

    # -- the scrub removes a whole token, not its marker --------------------
    expect("scrub_text removes every marker AND the token body after it",
           [marker for marker in ("Authorization: ", "Bearer ", "pst-")
            if (lambda out: marker.strip() in out or "fake-key-for-tests" in out)(
                nai_state.scrub_text("x " + marker + "fake-key-for-tests y"))],
           [])
    t, st, row, exc, pattern = scripted(REQ_GEN, [
        sub(1000), error(401, "Unauthorized token " + CANARY), sub(1000)])
    expect("an echo with no transport redaction (the recording transport): the "
           "row and ledger carry neither the key nor its body",
           (row["http_status"], CANARY_BODY in (row["error_message"] or ""),
            CANARY_BODY in open(st.ledger_path, encoding="utf-8").read()),
           (401, False, False))
    echo_err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(echo_err):
        echo_code = cli.main(["account"], transport=tp.RecordingTransport(
            [error(401, "Unauthorized token " + CANARY)]),
            state=scratch_state("echo_account"))
    expect("...and the same echo on the balance read reaches stderr scrubbed "
           "(the sibling route: an AccountReadError)",
           (echo_code, "status 401" in echo_err.getvalue(),
            CANARY_BODY in echo_err.getvalue()), (1, True, False))

    # -- the canary key through the REAL urllib transport -------------------
    class FakeHTTPS(urllib.request.HTTPSHandler):
        """Answers https from a script inside urllib; opens nothing."""

        def __init__(self):
            super().__init__()
            self.script: list = []
            self.seen: list[tuple[str, str, dict]] = []
            self.placement: list[tuple[bool, bool]] = []

        def https_open(self, req):
            self.seen.append((req.get_method(), req.full_url,
                              {k.lower(): v for k, v in req.header_items()}))
            self.placement.append((
                "authorization" in {k.lower() for k in req.unredirected_hdrs},
                "authorization" in {k.lower() for k in req.headers}))
            if not self.script:
                raise AssertionError(f"unscripted {req.get_method()} "
                                     f"{req.full_url}")
            entry = self.script.pop(0)
            if isinstance(entry, BaseException):
                raise entry
            status, headers, body = entry
            message = http.client.HTTPMessage()
            for name, value in headers.items():
                message[name] = value
            response = urllib.response.addinfourl(io.BytesIO(body), message,
                                                  req.full_url, code=status)
            response.msg = http.client.responses.get(status, "")
            return response

    FAKE = FakeHTTPS()
    caught: list[BaseException] = []
    printed: list[str] = []
    leak_states: list[State] = []
    saved_handlers = tp._TEST_HANDLERS
    # ProxyHandler({}) keeps a machine's HTTPS_PROXY from routing around FAKE.
    tp._TEST_HANDLERS = (urllib.request.ProxyHandler({}), FAKE)
    try:
        def cli_send(state, script, argv=("run", "walk", "--action",
                                          "generate", "--seed", str(SEED))):
            run.reset_latch_for_checks()
            FAKE.script = list(script)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cli.main(list(argv), transport=tp.UrllibTransport(),
                                    state=state)
                except Exception as exc:  # noqa: BLE001 - inspected below
                    caught.append(exc)
                    code = f"raised {type(exc).__name__}"
            printed.extend((out.getvalue(), err.getvalue()))
            return code, out.getvalue() + err.getvalue()

        echo = "Unauthorized: Bearer " + CANARY
        leak = scratch_state("leak")
        leak_states.append(leak)
        code, text = cli_send(leak, [sub(1000), zipped(), sub(1000)])
        expect("urllib success through the CLI exits 0 with a stored PNG",
               (code, "output" in text), (0, True))
        code, text = cli_send(leak, [
            sub(1000),
            (401, {"Content-Type": "application/json",
                   "WWW-Authenticate": "Bearer " + CANARY},
             json.dumps({"statusCode": 401, "message": echo}).encode()),
            sub(1000)])
        expect("a 401 whose body and header ECHO the key exits 1",
               (code, "HTTP 401" in text or "http status   401" in text),
               (1, True))
        code, text = cli_send(leak, [
            sub(1000), urllib.error.URLError(TimeoutError("timed out")),
            sub(1000)])
        expect("a timeout inside urllib exits 1 and is recorded as a timeout",
               (code, "timeout" in text), (1, True))
        code, text = cli_send(leak, [
            sub(1000), zipped(),
            (500, {"Content-Type": "application/json"},
             json.dumps({"statusCode": 500, "message": "boom " + CANARY}).encode())])
        expect("an after-read failure echoing the key: exit 1, LOCK",
               (code, leak.locked()), (1, True))
        seen_before = len(FAKE.seen)
        code, text = cli_send(leak, [])
        expect("...and the next run is refused (2) and asks nothing",
               (code, len(FAKE.seen) - seen_before), (2, 0))
        escaped = CANARY[:-1] + "\\u%04x" % ord(CANARY[-1])
        escaped_body = ('{"statusCode": 401, "message": "Unauthorized token '
                        + escaped + '"}').encode("ascii")
        expect("control: the escaped echo decodes to the canary",
               CANARY in json.loads(escaped_body)["message"], True)
        FAKE.script = [(401, {"Content-Type": "application/json"},
                        escaped_body)]
        status_, _headers, returned = tp.UrllibTransport().get(
            SUBSCRIPTION_URL, {}, 5.0)
        expect("a JSON echo with one character ESCAPED is redacted in its "
               "decoded text", (status_, CANARY_BODY in json.loads(
                   returned.decode("utf-8"))["message"]), (401, False))
        escaped_state = scratch_state("leak_escaped")
        leak_states.append(escaped_state)
        code, text = cli_send(escaped_state, [
            sub(1000), (401, {"Content-Type": "application/json"},
                        escaped_body), sub(1000)])
        expect("...and through the CLI it exits 1 with the row printed",
               (code, "http status   401" in text), (1, True))
        seen_before = len(FAKE.seen)
        FAKE.script = [(302, {"Location": "https://image.novelai.net/elsewhere"},
                        b"")]
        redirected = outcome(lambda: tp.UrllibTransport().get(
            SUBSCRIPTION_URL, {}, 5.0))
        expect("a 302 is refused: TransportError after exactly ONE request",
               (str(redirected).startswith("TransportError"),
                "redirect" in str(redirected), len(FAKE.seen) - seen_before),
               (True, True, 1))
        FAKE.script = []
        charged = scratch_state("leak_charged")
        leak_states.append(charged)
        code, text = cli_send(charged, [sub(1000), zipped(), sub(990)])
        expect("a charge through urllib: exit 1, LOCK written",
               (code, charged.locked()), (1, True))
        direct = scratch_state("leak_direct")
        leak_states.append(direct)
        run.reset_latch_for_checks()
        FAKE.script = [sub(1000), zipped(),
                       (503, {}, ("down, Bearer " + CANARY).encode())]
        try:
            run.run_request(REQ_GEN, tp.UrllibTransport(), direct)
        except Exception as exc:  # noqa: BLE001 - inspected below
            caught.append(exc)
        FAKE.script = []
        for bad_url in ("https://api.novelai.net/user/subscription",):
            try:
                tp.UrllibTransport().get(bad_url, {}, 1.0)
            except Exception as exc:  # noqa: BLE001 - inspected below
                caught.append(exc)
    finally:
        tp._TEST_HANDLERS = saved_handlers
        FAKE.script = []

    auths = [headers.get("authorization") for _m, _u, headers in FAKE.seen]
    expect("NON-VACUOUS: the canary really rode in every Authorization header",
           (len(auths) >= 16, set(auths)), (True, {"Bearer " + CANARY}))
    expect("...always as an UNREDIRECTED header, never a forwardable one",
           set(FAKE.placement), {(True, False)})
    expect("...and never in a URL",
           [u for _m, u, _h in FAKE.seen if CANARY in u], [])
    expect("every exception raised on those routes was collected",
           [type(e).__name__ for e in caught],
           ["AccountReadError", "Refused"])

    def files_holding(root: str, needle: bytes) -> list[str]:
        hits = []
        for base, _dirs, names in os.walk(root):
            for name in names:
                path = os.path.join(base, name)
                with open(path, "rb") as handle:
                    if needle in handle.read():
                        hits.append(os.path.relpath(path, root))
        return hits

    control = os.path.join(SCRATCH, "control")
    os.makedirs(control)
    with open(os.path.join(control, "planted.txt"), "wb") as handle:
        handle.write(b"x[redacted]" + CANARY_BODY.encode("ascii") + b"x")
    expect("control: the file search finds a planted canary BODY",
           files_holding(control, CANARY_BODY.encode("ascii")), ["planted.txt"])
    shutil.rmtree(control)
    for state in leak_states:
        expect_true(f"{os.path.basename(state.root)}: rows were written",
                    state.rows())
        expect(f"{os.path.basename(state.root)}: no file under the state "
               f"root holds the key's body",
               files_holding(state.root, CANARY_BODY.encode("ascii")), [])
        expect(f"{os.path.basename(state.root)}: no ledger row holds the key "
               f"body or a Bearer header",
               [r["ledger_id"] for r in state.rows()
                if CANARY_BODY in json.dumps(r) or "Bearer " in json.dumps(r)],
               [])
    expect("no exception message, repr or traceback holds the key's body",
           [type(e).__name__ for e in caught
            if CANARY_BODY in str(e) + repr(e)
            + "".join(traceback.format_exception(e))], [])
    expect_true("the CLI printed something to search",
                sum(len(t) for t in printed) > 500)
    expect("no captured stdout or stderr holds the key's body",
           [i for i, t in enumerate(printed) if CANARY_BODY in t], [])

    # -- a key with a line break inside: the stdlib's own header check -------
    broken = CANARY[:8] + "\n" + CANARY[8:]
    halves = (CANARY[:8], CANARY[8:])
    real_handlers = (urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
    saved_handlers = tp._TEST_HANDLERS
    tp._TEST_HANDLERS = real_handlers
    newline_out: list[str] = []
    try:
        os.environ["NAI_KEY"] = broken
        for argv in (["account"], ["run", "walk", "--action", "generate",
                                   "--seed", str(SEED)]):
            run.reset_latch_for_checks()
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cli.main(argv, transport=tp.UrllibTransport(),
                                    state=scratch_state("newline_key"))
                except NetworkForbidden as forbidden:
                    code = f"opened a socket: {forbidden}"
            newline_out.append(out.getvalue() + err.getvalue())
            expect(f"NAI_KEY with a line break inside: `{argv[0]}` exits 1 "
                   f"naming NAI_KEY's shape, echoing no part of it",
                   (code, "NAI_KEY holds a character" in err.getvalue(),
                    [h for h in halves if h in out.getvalue() + err.getvalue()]),
                   (1, True, []))
        os.environ["NAI_KEY"] = CANARY
        saved_api_key = tp.api_key
        tp.api_key = lambda: broken   # as if api_key's own refusal were gone
        try:
            wall = outcome(lambda: tp.UrllibTransport().get(SUBSCRIPTION_URL,
                                                            {}, 5.0))
        except NetworkForbidden as forbidden:
            wall = f"opened a socket: {forbidden}"
        finally:
            tp.api_key = saved_api_key
        expect("...and past api_key, the stdlib's header ValueError leaves "
               "_send as a TransportError naming no part of the key",
               (str(wall).startswith("TransportError"), "ValueError" in str(wall),
                [h for h in halves if h in str(wall)]), (True, True, []))
    finally:
        tp._TEST_HANDLERS = saved_handlers
        os.environ["NAI_KEY"] = CANARY

    # =======================================================================
    print("\n4. api_key: the value comes back, its absence names NAI_KEY only")
    # =======================================================================
    expect("present: the canary comes back", tp.api_key(), CANARY)
    os.environ["NAI_KEY"] = "  " + CANARY + "\n"
    expect("present with whitespace: stripped", tp.api_key(), CANARY)
    del os.environ["NAI_KEY"]
    absent = expect_raises("absent: MissingKey naming NAI_KEY", tp.MissingKey,
                           tp.api_key, "NAI_KEY", "absent or blank")
    os.environ["NAI_KEY"] = " \t\n "
    blank = expect_raises("blank: MissingKey too", tp.MissingKey, tp.api_key,
                          "NAI_KEY")
    expect("the message does not depend on the value (none is echoed)",
           str(blank), str(absent))
    shaped = []
    for label, value in (("a line break inside", CANARY[:8] + "\n" + CANARY[8:]),
                         ("a space inside", CANARY[:8] + " " + CANARY[8:]),
                         ("a curly quote around it",
                          "\u201c" + CANARY + "\u201d")):
        os.environ["NAI_KEY"] = value
        shaped.append(expect_raises(f"{label}: MissingKey naming NAI_KEY",
                                    tp.MissingKey, tp.api_key, "NAI_KEY",
                                    "cannot carry"))
    expect("...one message for every such value, holding no part of it",
           (len({str(e) for e in shaped}), [str(e) for e in shaped
                                             if CANARY[:8] in str(e)
                                             or CANARY[8:] in str(e)]),
           (1, []))
    del os.environ["NAI_KEY"]
    NETWORK_BEFORE = len(NETWORK_ATTEMPTS)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["account"], state=scratch_state("nokey"))
    expect("with no key, `account` exits 1 naming NAI_KEY and opens nothing",
           (code, "NAI_KEY" in err.getvalue(),
            len(NETWORK_ATTEMPTS) - NETWORK_BEFORE), (1, True, 0))
    os.environ["NAI_KEY"] = CANARY

    # =======================================================================
    print("\n5. mannequin: centers computed, distinct, in their cells; strip's limits")
    # =======================================================================
    def measured_center(image, rect, width, height):
        crop = image.crop(rect)
        box = ImageChops.difference(
            crop, Image.new("RGB", crop.size, BACKGROUND_RGB)).getbbox()
        if box is None:
            return None
        cx = rect[0] + (box[0] + box[2]) / 2
        cy = rect[1] + (box[1] + box[3]) / 2
        return (snap(cx / width), snap(cy / height))

    layouts = [(name, r.layout, r.poses) for name, r in
               sorted(recipes.RECIPES.items())]
    layouts += [(f"strip({n},{w},{h})", mannequin.strip(n, w, h),
                 mannequin.POSES["walk"][:n])
                for n, w, h in ((5, 1216, 832), (3, 1024, 1024),
                                (4, 1024, 1024), (2, 640, 512))]
    for name, layout, poses in layouts:
        try:
            png, centers = mannequin.render_init(layout, poses, COLOURS)
        except Exception as exc:  # noqa: BLE001 - reported
            asserted.append(1)
            failures.append(f"{name}: render_init")
            print(f"  FAIL {name}: render_init raised {type(exc).__name__}: "
                  f"{str(exc)[:120]}")
            continue
        image = opened(png)
        expect(f"{name}: one center per cell, all on the grid, all distinct",
               (len(centers), all(on_grid(v) for c in centers for v in c),
                len(set(centers))), (layout.count, True, layout.count))
        outside = [i for i, (x, y) in enumerate(centers)
                   if not (layout.cells[i].rect_canvas[0] <= x * layout.width
                           < layout.cells[i].rect_canvas[2]
                           and layout.cells[i].rect_canvas[1] <= y * layout.height
                           < layout.cells[i].rect_canvas[3])]
        expect(f"{name}: every center lies inside its own cell", outside, [])
        expect(f"{name}: re-measured from the PNG's pixels, the same centers",
               [measured_center(image, c.rect_canvas, layout.width,
                                layout.height) for c in layout.cells],
               list(centers))
        expect(f"{name}: the init is exactly {layout.width}x{layout.height}, "
               f"RGB (opaque, PNG colour type 2)",
               (image.size, image.mode, request.png_header(png)),
               ((layout.width, layout.height), "RGB",
                (layout.width, layout.height, 2)))
        k = layout.k
        blocky = image.resize((layout.width // k, layout.height // k),
                              Image.Resampling.NEAREST).resize(
            image.size, Image.Resampling.NEAREST)
        expect(f"{name}: every {k}x{k} block is one colour",
               blocky.tobytes() == image.tobytes(), True)
    expect("strip(5, 1216, 832) is exactly L5's cells",
           mannequin.strip(5, 1216, 832).cells, mannequin.LAYOUTS["L5"].cells)

    idle = mannequin.POSES["walk"][4]

    def tight(width_px):
        return Layout(name="tight", width=1216, height=832, k=4, src_w=304,
                      src_h=208, cells=(
                          CellSpec((0, 0, width_px, 832), width_px // 8, 120),
                          CellSpec((width_px, 0, 2 * width_px, 832),
                                   width_px // 4 + width_px // 8, 120)))
    expect_raises("two frames snapping to one center are refused", ValueError,
                  lambda: mannequin.render_init(tight(160), (idle, idle),
                                                COLOURS), "both snap to")
    expect_raises("a center that snaps outside its own cell is refused",
                  ValueError, lambda: mannequin.render_init(
                      tight(120), (idle, idle), COLOURS), "outside its cell")
    expect_raises("a pose count that is not the cell count is refused",
                  ValueError, lambda: mannequin.render_init(
                      L5, WALK.poses[:4], COLOURS), "got 4 poses")
    for args, fragment in (((6, 1216, 832), "legal 1..5"),
                           ((0, 1216, 832), "legal 1..5"),
                           ((5, 1200, 832), "multiple of 64"),
                           ((5, 1216, 830), "multiple of 64"),
                           ((5, 1280, 1024), "exceeds 1048576"),
                           ((3, 1536, 768), "exceeds 1048576")):
        expect_raises(f"strip{args} is refused", ValueError,
                      lambda a=args: mannequin.strip(*a), fragment)
    expect("...while the largest legal square builds",
           (mannequin.strip(3, 1024, 1024).name,
            1024 * 1024 <= MAX_AREA), ("strip3_1024x1024", True))

    # =======================================================================
    print("\n6. masks: 8-aligned, white exactly over the cell, a local composite")
    # =======================================================================
    for layout in (mannequin.LAYOUTS["L5"], mannequin.LAYOUTS["G6"]):
        for i, cell in enumerate(layout.cells):
            data = masks.cell_mask(layout, i)
            mask = opened(data)
            rect = cell.rect_canvas
            area = (rect[2] - rect[0]) * (rect[3] - rect[1])
            grey = mask.convert("RGB").convert("L")
            hist = grey.histogram()
            white = Image.eval(grey, lambda v: 255 if v == 255 else 0)
            expect(f"{layout.name} cell {i}: RGBA, alpha 255, colour type 6",
                   (mask.mode, mask.getchannel("A").getextrema(),
                    request.png_header(data)[2]), ("RGBA", (255, 255), 6))
            expect(f"{layout.name} cell {i}: white is exactly the cell, black "
                   f"is everything else, nothing between",
                   (white.getbbox(), hist[255], hist[0],
                    sum(hist[1:255])),
                   (rect, area, layout.width * layout.height - area, 0))
            expect(f"{layout.name} cell {i}: every edge is a multiple of 8",
                   [e % 8 for e in rect], [0, 0, 0, 0])
    expect_raises("cell -1 is not a cell", IndexError,
                  lambda: masks.cell_mask(L5, -1), "not -1")
    expect_raises("cell 5 of a 5-cell layout is not a cell", IndexError,
                  lambda: masks.cell_mask(L5, 5), "not 5")
    expect_raises("a layout whose cell edge is off the 8 grid cannot exist",
                  ValueError, lambda: Layout(
                      name="off", width=1216, height=832, k=4, src_w=304,
                      src_h=208, cells=(CellSpec((0, 0, 124, 832), 10, 100),)),
                  "not a multiple of 8")

    rect = L5.cells[2].rect_canvas
    returned = png_bytes(Image.new("RGB", (L5.width, L5.height), (10, 200, 30)))
    merged = opened(masks.composite(INIT_PNG, returned, rect)).convert("RGB")
    original = opened(INIT_PNG).convert("RGB")

    def blanked(image, box):
        copy_ = image.copy()
        copy_.paste((0, 0, 0), box)
        return copy_.tobytes()
    expect("composite: every pixel outside the rect is the original's",
           blanked(merged, rect) == blanked(original, rect), True)
    expect("composite: every pixel inside the rect is the returned image's",
           merged.crop(rect).tobytes()
           == opened(returned).convert("RGB").crop(rect).tobytes(), True)
    expect_raises("composite of two sizes is refused", ValueError,
                  lambda: masks.composite(INIT_PNG, png_bytes(
                      Image.new("RGB", (64, 64))), rect), "sizes differ")
    expect_raises("a rect outside the image is refused", ValueError,
                  lambda: masks.composite(INIT_PNG, returned,
                                          (1200, 0, 1280, 832)), "not inside")
    expect("differs_outside: identical images differ nowhere",
           masks.differs_outside(INIT_PNG, INIT_PNG, rect), False)
    x0, y0, x1, y1 = rect
    for label, point, want in (("just left of", (x0 - 1, 400), True),
                               ("just right of", (x1, 400), True),
                               ("just inside the left edge of", (x0, 400), False),
                               ("just inside the right edge of", (x1 - 1, 400),
                                False),
                               ("at the bottom row inside", (x0 + 5, y1 - 1),
                                False)):
        touched = original.copy()
        r, g, b = touched.getpixel(point)
        touched.putpixel(point, (255 - r, 255 - g, 255 - b))
        expect(f"differs_outside: one pixel {label} the rect -> {want}",
               masks.differs_outside(INIT_PNG, png_bytes(touched), rect), want)

    # =======================================================================
    print("\n7. pixelize: k, phase, sprite and palette back out of a noisy strip")
    # =======================================================================
    PARTS = ((0x6B, 0x42, 0x26), (0xE8, 0xB4, 0x8C), (0xC8, 0x3C, 0x3C),
             (0x3C, 0x64, 0xC8), (0xC8, 0xA0, 0x64), (0x2E, 0x8B, 0x57))
    HAIR, SKIN, SCARF, TUNIC, PANTS, BOOTS = PARTS

    def figure(h: int, gap: int):
        """A blocky outlined figure about h pseudo-pixels tall; (RGBA, hip)."""
        u = h / 40.0
        head = max(3, round(8 * u))
        torso_w = max(3, round(6 * u)) | 1
        torso_h = max(4, round(12 * u))
        leg_w = max(2, round(3 * u))
        arm_w = max(1, round(2 * u))
        boot = max(1, round(2 * u))
        leg = (h - 2) - head - torso_h - boot
        width = torso_w + 2 * (arm_w + 1) + 2 * gap + 2 * leg_w + 6
        mid = width // 2
        x0 = mid - torso_w // 2
        rects = [((x0, 1, x0 + head, 1 + max(1, head // 3)), HAIR),
                 ((x0, 1 + max(1, head // 3), x0 + head, 1 + head), SKIN)]
        y = 1 + head
        rects += [((x0, y, x0 + torso_w, y + max(1, torso_h // 6)), SCARF),
                  ((x0, y + max(1, torso_h // 6), x0 + torso_w, y + torso_h),
                   TUNIC),
                  ((x0 - arm_w - 1, y + 1, x0 - 1, y + torso_h - 1), TUNIC),
                  ((x0 + torso_w + 1, y + 1, x0 + torso_w + 1 + arm_w,
                    y + torso_h - 1), SKIN)]
        y += torso_h
        for lx in (mid - gap // 2 - leg_w, mid + (gap + 1) // 2):
            rects += [((lx, y, lx + leg_w, y + leg), PANTS),
                      ((lx, y + leg, lx + leg_w + 1, y + leg + boot), BOOTS)]
        body = Image.new("RGBA", (width, y + leg + boot + 1), (0, 0, 0, 0))
        for box, rgb in rects:
            body.paste(rgb + (255,), box)
        ring = body.getchannel("A").filter(ImageFilter.MaxFilter(3))
        outlined = Image.new("RGBA", body.size, OUTLINE_RGB + (0,))
        outlined.putalpha(ring)
        outlined.alpha_composite(body)
        box = outlined.getbbox()
        return outlined.crop(box), mid - box[0]

    def synthetic_strip(layout, k, phase_x, phase_y, *, seed, skip=(),
                        lift=None, figures=None):
        """An upscaled, noised (+-6), blurred (0.6 px) strip on grid k/phase.

        Returns (png, source RGBA on the pseudo-pixel grid, centers, anchors):
        each figure's hip column and lowest row sit exactly on the grid
        column/row pixelize anchors that cell to, so a faithful pixelize
        needs no shift and its frames can be compared to the source --
        except frame i in `lift`, drawn lift[i] pseudo-pixels ABOVE its
        anchor. `figures` replaces frame i's (figure, hip) outright."""
        lift = lift or {}
        figures = figures or {}
        width, height = layout.width, layout.height
        ox = phase_x - k if phase_x else 0
        oy = phase_y - k if phase_y else 0
        nx, ny = -(-(width - ox) // k), -(-(height - oy) // k)
        source = Image.new("RGBA", (nx, ny), BACKGROUND_RGB + (0,))
        centers, anchors = [], []
        for i, cell in enumerate(layout.cells):
            hip_u = (cell.hip_x_src * layout.k + layout.k // 2 - ox) // k
            base_v = (cell.baseline_src * layout.k + layout.k // 2 - oy) // k
            anchors.append((hip_u, base_v))
            fig, hip = figures.get(i) or figure(round(400 / k), 1 + i % 3)
            u0, v0 = hip_u - hip, base_v - lift.get(i, 0) - (fig.size[1] - 1)
            if i in skip:
                centers.append((0.1 + 0.2 * i, 0.5))
                continue
            source.alpha_composite(fig, (u0, v0))
            cx = ox + (2 * u0 + fig.size[0]) * k / 2
            cy = oy + (2 * v0 + fig.size[1]) * k / 2
            centers.append((snap(cx / width), snap(cy / height)))
        flat = Image.new("RGB", (nx, ny), BACKGROUND_RGB)
        flat.paste(source, (0, 0), source)
        canvas = flat.resize((nx * k, ny * k), Image.Resampling.NEAREST).crop(
            (-ox, -oy, -ox + width, -oy + height))
        rng = random.Random(seed)
        table = bytes(v % 13 for v in range(256))
        noise = Image.frombytes("RGB", (width, height),
                                rng.randbytes(width * height * 3).translate(table))
        canvas = ImageChops.subtract(ImageChops.add(canvas, noise),
                                     Image.new("RGB", (width, height), (6, 6, 6)))
        canvas = canvas.filter(ImageFilter.GaussianBlur(0.6))
        return png_bytes(canvas), source, centers, anchors

    def frame_errors(result, source, anchors):
        """(alpha mismatches, worst channel error) of every frame vs source."""
        sc = result.sidecar
        mismatches, worst = 0, 0
        for i, frame_png in enumerate(result.frames):
            got = opened(frame_png).convert("RGBA").tobytes()
            hip_u, base_v = anchors[i]
            left, top = hip_u - sc["anchor_x"], base_v - sc["baseline_y"]
            want = source.crop((left, top, left + sc["frame_w"],
                                top + sc["frame_h"])).tobytes()
            if len(got) != len(want):
                return (-1, -1)
            for p in range(0, len(got), 4):
                if (got[p + 3] > 0) != (want[p + 3] > 0):
                    mismatches += 1
                elif got[p + 3]:
                    worst = max(worst, abs(got[p] - want[p]),
                                abs(got[p + 1] - want[p + 1]),
                                abs(got[p + 2] - want[p + 2]))
        return mismatches, worst

    def lowest_rows(result):
        """Each emitted frame's lowest opaque row."""
        return [opened(f).getchannel("A").getbbox()[3] - 1
                for f in result.frames]

    def margins(result):
        """(frame_w, frame_h, left, top, right, bottom) transparent margins of
        the union of every frame's opaque box."""
        sc = result.sidecar
        boxes = [opened(f).getchannel("A").getbbox() for f in result.frames]
        return (sc["frame_w"], sc["frame_h"], min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                sc["frame_w"] - max(b[2] for b in boxes),
                sc["frame_h"] - max(b[3] for b in boxes))

    def failing_validators(result):
        return [key for key in post.VALIDATION_KEYS
                if not result.validation[key]["ok"]]

    seen_margins = []
    GROUND = [True] * L5.count
    first_png = first_centers = None
    for k, phase_x, phase_y in ((6, 5, 2), (10, 4, 7), (12, 0, 0)):
        png, source, centers, anchors = synthetic_strip(L5, k, phase_x, phase_y,
                                                        seed=k)
        if first_png is None:
            first_png, first_centers = png, centers
        result = post.pixelize(png, L5, centers=centers, ground=GROUND)
        tag = f"k={k} phase=({phase_x},{phase_y})"
        seen_margins.append(margins(result))
        expect(f"{tag}: grid recovered", (result.k, result.phase,
                                          result.sidecar["k"],
                                          result.sidecar["phase"]),
               (k, (phase_x, phase_y), k, [phase_x, phase_y]))
        expect(f"{tag}: validation passes with no flag",
               (result.validation["ok"], result.validation["flags"],
                [key for key in post.VALIDATION_KEYS
                 if not result.validation[key]["ok"]]), (True, [], []))
        expect(f"{tag}: every frame's alpha is the drawn sprite's, colours "
               f"within 8", (lambda m_w: (m_w[0], m_w[1] <= 8))(
                   frame_errors(result, source, anchors)), (0, True))
        strip_image = opened(result.strip_rgba_png).convert("RGBA")
        corners = [strip_image.getpixel(p)[3] for p in (
            (0, 0), (strip_image.width - 1, 0), (0, strip_image.height - 1),
            (strip_image.width - 1, strip_image.height - 1))]
        key = result.validation["background"]["rgb"]
        key_rgb = tuple(int(key[i:i + 2], 16) for i in (1, 3, 5))
        expect(f"{tag}: background keyed: corners transparent, no flood fill, "
               f"the key is the grey",
               (corners, result.validation["background"]["flood_fill"],
                max(abs(a - b) for a, b in zip(key_rgb, BACKGROUND_RGB)) <= 4),
               ([0, 0, 0, 0], False, True))
        palette = opened(result.palette_png)
        entries = palette.getpalette() or []
        palette_rgb = {tuple(entries[i:i + 3])
                       for i in range(0, len(entries), 3)}
        raw = strip_image.tobytes()
        emitted = {raw[p:p + 3] for p in range(0, len(raw), 4) if raw[p + 3]}
        expect(f"{tag}: palette bound: a mode-P palette of <= "
               f"{DEFAULT_COLOURS}, every emitted colour one of its entries",
               (palette.mode, len(entries) // 3 <= DEFAULT_COLOURS,
                sorted(tuple(c) for c in emitted if tuple(c) not in palette_rgb),
                len(result.sidecar["palette"]) == len(emitted)),
               ("P", True, [], True))

    # -- P7: baseline alignment, and hold_arc ------------------------------
    png, source, centers, anchors = synthetic_strip(L5, 8, 3, 5, seed=81,
                                                    lift={1: 3})
    result = post.pixelize(png, L5, centers=centers, ground=GROUND)
    seen_margins.append(margins(result))
    expect("P7: a ground frame drawn 3 pseudo-pixels high lands on the "
           "baseline like the rest, and the strip stays valid",
           (lowest_rows(result), result.validation["ok"]),
           ([result.sidecar["baseline_y"]] * 5, True))
    ARC = {0: 2, 1: 5, 2: 9, 3: 5, 4: 3}
    png, source, centers, anchors = synthetic_strip(L5, 8, 3, 5, seed=82,
                                                    lift=ARC)
    result = post.pixelize(png, L5, centers=centers,
                           ground=[True, False, False, False, True],
                           hold_arc=True)
    seen_margins.append(margins(result))
    expect("hold_arc: EVERY frame takes the first ground frame's shift, so "
           "the drawn arc survives (the last ground frame too)",
           (lowest_rows(result), result.validation["ok"]),
           ([result.sidecar["baseline_y"] - ARC[i] + ARC[0] for i in range(5)],
            True))
    expect("P7 frame box: both sides even, a 1 px margin left and bottom, 1 "
           "or 2 (the even-rounding) right and top",
           [m for m in seen_margins
            if m[0] % 2 or m[1] % 2 or m[2] != 1 or m[5] != 1
            or m[3] not in (1, 2) or m[4] not in (1, 2)], [])
    expect("NON-VACUOUS: some strip rounded its width up and some its height",
           (any(m[4] == 2 for m in seen_margins),
            any(m[3] == 2 for m in seen_margins)), (True, True))

    # -- P9: one strip per validator, failing only that validator ----------
    def doubled(fig_hip, offset):
        fig, hip = fig_hip
        both = Image.new("RGBA", (fig.size[0] + offset, fig.size[1]),
                         (0, 0, 0, 0))
        both.alpha_composite(fig, (0, 0))
        both.alpha_composite(fig, (offset, 0))
        return both, hip + offset // 2

    def squashed(fig_hip, share):
        fig, hip = fig_hip
        return fig.resize((fig.size[0], round(fig.size[1] * share)),
                          Image.Resampling.NEAREST), hip

    png, source, centers, anchors = synthetic_strip(
        L5, 8, 3, 5, seed=85, figures={2: doubled(figure(50, 3), 8)})
    result = post.pixelize(png, L5, centers=centers, ground=GROUND)
    expect("a frame holding a doubled (fused) figure is REJECTED by opaque_px "
           "alone", (result.validation["ok"], failing_validators(result)),
           (False, ["opaque_px"]))
    png, source, centers, anchors = synthetic_strip(
        L5, 8, 3, 5, seed=84, figures={3: squashed(figure(50, 1), 0.8)})
    result = post.pixelize(png, L5, centers=centers, ground=GROUND)
    expect("a ground frame squashed to 80% height is REJECTED by ground_height "
           "alone", (result.validation["ok"], failing_validators(result)),
           (False, ["ground_height"]))
    three = Image.new("RGBA", (6, 2), (0, 0, 0, 0))
    for x, rgb in ((0, (200, 10, 10)), (1, (10, 200, 10)), (2, (10, 10, 200))):
        three.putpixel((x, 0), rgb + (255,))
    three.putpixel((4, 1), (1, 2, 3, 0))   # transparent: never counted
    expect("used_colours: 3 opaque colours break a 2-entry palette, fit a "
           "3-entry one",
           (post.used_colours_verdict(png_bytes(three), 2)["ok"],
            post.used_colours_verdict(png_bytes(three), 3)["ok"]),
           (False, True))

    png, source, centers, anchors = synthetic_strip(L5, 7, 3, 1, seed=7,
                                                    skip=(2,))
    result = post.pixelize(png, L5, centers=centers, ground=GROUND)
    expect("a strip with frame 2 missing is REJECTED, frame_count failing",
           (result.validation["ok"], result.validation["frame_count"]["ok"],
            result.validation["frame_count"]["detail"]["per_cell"],
            "empty_frame:2" in result.validation["flags"]),
           (False, False, [1, 1, 0, 1, 1], True))
    swapped = list(reversed(first_centers))
    result = post.pixelize(first_png, L5, centers=swapped, ground=GROUND)
    expect("the right strip with its centers reversed is REJECTED",
           (result.validation["ok"], result.validation["center_snap"]["ok"]),
           (False, False))
    expect_raises("a strip that is not layout-sized is refused", ValueError,
                  lambda: post.pixelize(png_bytes(Image.new("RGB", (640, 512))),
                                        L5, centers=first_centers,
                                        ground=GROUND), "640x512")
    expect_raises("colours outside 8..32 is refused", ValueError,
                  lambda: post.pixelize(first_png, L5, centers=first_centers,
                                        ground=GROUND, colours=7), "outside 8..32")
    expect_raises("a palette that is not mode P is refused", ValueError,
                  lambda: post.pixelize(first_png, L5, centers=first_centers,
                                        ground=GROUND,
                                        palette_png=png_bytes(
                                            Image.new("RGB", (4, 1)))),
                  "expected P")
    expect_raises("4 centers for 5 cells is refused", ValueError,
                  lambda: post.pixelize(first_png, L5,
                                        centers=first_centers[:4],
                                        ground=GROUND), "4 centers")

    # =======================================================================
    print("\n8. the CLI: plan sends nothing, probe needs the author's flag")
    # =======================================================================
    class NoTransport:
        """Stands in for UrllibTransport; being constructed is the failure."""
        built = 0

        def __init__(self):
            NoTransport.built += 1
            raise AssertionError("a command built a real transport")

    def cli_call(argv, transport, state):
        run.reset_latch_for_checks()
        out, err = io.StringIO(), io.StringIO()
        saved = tp.UrllibTransport
        tp.UrllibTransport = NoTransport
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cli.main(argv, transport=transport, state=state)
                except Exception as exc:  # noqa: BLE001 - reported
                    code = f"raised {type(exc).__name__}: {exc}"
        finally:
            tp.UrllibTransport = saved
        return code, out.getvalue(), err.getvalue()

    plan_argv = ["plan", "walk", "--action", "generate", "--seed", str(SEED)]
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
    plan_state = scratch_state("plan")
    code, out, err = cli_call(plan_argv, recorder, plan_state)
    expect("plan exits 0 and reports every offline condition passing",
           (code, "every offline condition passes" in out), (0, True))
    expect("plan asks the transport for nothing and writes no ledger",
           (recorder.calls, len(recorder.responses), plan_state.rows(),
            os.path.exists(plan_state.root)), ([], 3, [], False))
    expect("plan prints no key and no Authorization or Bearer text",
           [s for s in (CANARY, "Authorization", "Bearer ")
            if s in out + err], [])
    NoTransport.built = 0
    code, out, err = cli_call(plan_argv, None, scratch_state("plan_none"))
    expect("plan with no transport given builds none", (code, NoTransport.built),
           (0, 0))
    code, out, err = cli_call(plan_argv + ["--steps", "29"], None,
                              scratch_state("plan_steps"))
    expect("plan still judges: 29 steps is REFUSED offline (exit 2)",
           (code, "REFUSED offline" in out, NoTransport.built), (2, True, 0))

    for action in ("img2img", "infill"):
        recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
        probe_state = scratch_state(f"probe_{action}")
        code, out, err = cli_call(["probe", action, "--seed", str(SEED)],
                                  recorder, probe_state)
        expect(f"probe {action} WITHOUT the flag: exit 2, NOT SENT",
               (code, "NOT SENT" in out), (2, True))
        expect(f"...no account read, no request, no row, no proof",
               (recorder.calls, len(recorder.responses), probe_state.rows(),
                probe_state.proofs()), ([], 3, [], ()))
        code, out, err = cli_call(["probe", action, "--seed", str(SEED)], None,
                                  scratch_state(f"probe_{action}_none"))
        expect("...and with no transport given, none is built",
               (code, NoTransport.built), (2, 0))
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
    probe_state = scratch_state("probe_flag")
    code, out, err = cli_call(["probe", "img2img", "--accept-max-2-anlas",
                               "--seed", str(SEED)], recorder, probe_state)
    expect("probe WITH the flag: read, one POST, read, proof written, exit 0",
           (code, [(c.method, c.url) for c in recorder.calls],
            [(p.action, p.model) for p in probe_state.proofs()],
            "proof         WRITTEN" in out),
           (0, [GET, POST, GET], [("img2img", MODEL_FULL)], True))

    # -- the probe flag cannot be abbreviated --------------------------------
    for abbreviation in ("--a", "--accept", "--accept-max"):
        recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
        abbrev_state = scratch_state("probe_abbrev")
        NoTransport.built = 0
        code, out, err = cli_call(["probe", "img2img", abbreviation, "--seed",
                                   str(SEED)], recorder, abbrev_state)
        expect(f"probe img2img {abbreviation}: NOT the flag -- exit 2, nothing "
               f"built, read, sent or written",
               (code, "unrecognized arguments" in err, NoTransport.built,
                recorder.calls, abbrev_state.rows(), abbrev_state.proofs()),
               (2, True, 0, [], [], ()))

    # -- where a command may write ------------------------------------------
    outside = os.path.join(SCRATCH, "outside_every_checkout", "walk_init.png")
    os.makedirs(os.path.dirname(outside))
    with open(outside, "wb") as handle:
        handle.write(b"an accepted file")
    code, out, err = cli_call(["render", "walk", "--out", outside], None,
                              scratch_state("render_existing"))
    with open(outside, "rb") as handle:
        kept = handle.read()
    expect("render --out onto an existing file with different bytes: exit 1, "
           "the file untouched",
           (code, "refusing to overwrite" in err, kept),
           (1, True, b"an accepted file"))
    os.remove(outside)
    code, out, err = cli_call(["render", "walk", "--out", outside], None,
                              scratch_state("render_new"))
    with open(outside, "rb") as handle:
        written = handle.read()
    expect("...while a new path outside every checkout is written",
           (code, written == INIT_PNG), (0, True))
    for rel in (("data", "maps", "starter.tmx"), ("tools", "baseline.json"),
                ("data", "reference", "sprites", "nai_walk"),
                ("data", "art", "sprite.png")):
        expect_raises(f"no output inside this checkout at {'/'.join(rel)}",
                      ValueError, lambda r=rel: cli.assert_untracked_output(
                          os.path.join(_bootstrap.REPO_ROOT, *r)),
                      "outside its gitignored data/nai/")
    expect("...while data/nai/ inside it, and a path outside every checkout, "
           "are allowed",
           (outcome(lambda: cli.assert_untracked_output(os.path.join(
               _bootstrap.REPO_ROOT, "data", "nai", "renders", "x.png"))),
            outcome(lambda: cli.assert_untracked_output(outside))),
           (None, None))
    fake_checkout = os.path.join(SCRATCH, "fake_checkout")
    tracked_map = os.path.join(fake_checkout, "data", "maps", "starter.tmx")
    os.makedirs(os.path.dirname(tracked_map))
    with open(tracked_map, "wb") as handle:
        handle.write(b"<map/>")
    reference_png = os.path.join(fake_checkout, "data", "reference", "sprites",
                                 "nai_walk", "init.png")
    reference_dir = os.path.dirname(reference_png)
    strip_file = os.path.join(SCRATCH, "strip_for_pixelize.png")
    with open(strip_file, "wb") as handle:
        handle.write(first_png)
    in_checkout_state = State(os.path.join(fake_checkout, "tools", "nai_state"))
    in_checkout_recorder = tp.RecordingTransport([sub(1000), zipped(),
                                                  sub(1000)])
    saved_roots = cli.checkout_roots
    cli.checkout_roots = lambda: (fake_checkout,)
    try:
        map_code, _o, map_err = cli_call(
            ["render", "walk", "--out", tracked_map], None,
            scratch_state("render_map"))
        ref_code, _o, _e = cli_call(["render", "walk", "--out", reference_png],
                                    None, scratch_state("render_ref"))
        pix_code, _o, _e = cli_call(["pixelize", strip_file, "--recipe", "walk",
                                     "--out", reference_dir], None,
                                    scratch_state("pixelize_ref"))
        run_code, _o, _e = cli_call(["run", "walk", "--action", "generate",
                                     "--seed", str(SEED)],
                                    in_checkout_recorder, in_checkout_state)
    finally:
        cli.checkout_roots = saved_roots
    with open(tracked_map, "rb") as handle:
        map_after = handle.read()
    expect("render --out onto a checkout's data/maps/starter.tmx: exit 1, "
           "untouched", (map_code, "outside its gitignored" in map_err,
                         map_after), (1, True, b"<map/>"))
    expect("render --out and pixelize --out into a checkout's data/reference/: "
           "exit 1 each, nothing written",
           (ref_code, pix_code, os.path.exists(reference_dir)), (1, 1, False))
    expect("run with a state root inside the checkout but outside data/nai: "
           "exit 1, nothing read or sent",
           (run_code, in_checkout_recorder.calls, os.path.exists(
               in_checkout_state.root)), (1, [], False))

    # -- one state root for every worktree of a checkout ---------------------
    main_repo = os.path.join(SCRATCH, "main_checkout")
    worktree = os.path.join(main_repo, ".claude", "worktrees", "w1")
    worktree_meta = os.path.join(main_repo, ".git", "worktrees", "w1")
    os.makedirs(worktree_meta)
    os.makedirs(worktree)
    with open(os.path.join(worktree_meta, "commondir"), "w",
              encoding="utf-8") as handle:
        handle.write("../..\n")
    with open(os.path.join(worktree, ".git"), "w", encoding="utf-8") as handle:
        handle.write("gitdir: " + worktree_meta.replace(os.sep, "/") + "\n")
    main_root = os.path.normcase(os.path.join(main_repo, "data", "nai"))
    expect("a linked worktree resolves the MAIN checkout's data/nai; the main "
           "checkout resolves its own",
           (os.path.normcase(nai_state.default_root(worktree)),
            os.path.normcase(nai_state.default_root(main_repo))),
           (main_root, main_root))
    saved_default = nai_state.default_root
    nai_state.default_root = lambda repo_root=worktree: saved_default(repo_root)
    try:
        resolved = State().root
    finally:
        nai_state.default_root = saved_default
    expect("State() with no root takes default_root(): from the worktree, the "
           "main checkout's", os.path.normcase(resolved), main_root)
    State(nai_state.default_root(main_repo)).lock(
        "main-checkout", "a LOCK written from the main checkout")
    t, _st, row, exc, pattern = scripted(
        REQ_GEN, [sub(1000), zipped(), sub(1000)],
        state=State(nai_state.default_root(worktree)))
    expect("...so the main checkout's LOCK refuses a run from the worktree, "
           "before any read", (getattr(exc, "condition", None), pattern),
           (10, []))
    no_gitdir = os.path.join(SCRATCH, "broken_worktree")
    os.makedirs(no_gitdir)
    with open(os.path.join(no_gitdir, ".git"), "w", encoding="utf-8") as handle:
        handle.write("not a gitdir line\n")
    expect_raises("a .git file with no gitdir line raises, never guesses a root",
                  ValueError, lambda: nai_state.default_root(no_gitdir),
                  "no 'gitdir:' line")
    no_git = os.path.join(SCRATCH, "no_git_at_all")
    os.makedirs(no_git)
    expect("a tree with no .git at all is its own root",
           os.path.normcase(nai_state.default_root(no_git)),
           os.path.normcase(os.path.join(no_git, "data", "nai")))

    # -- infill through the CLI: the init sent, the composite kept -----------
    infill_state = scratch_state("infill_cli")
    code, out, err = cli_call(["probe", "infill", "--accept-max-2-anlas",
                               "--seed", str(SEED)],
                              tp.RecordingTransport([sub(1000), zipped(),
                                                     sub(1000)]), infill_state)
    expect("infill track: the author's infill probe writes its proof",
           (code, [(p.action, p.model) for p in infill_state.proofs()]),
           (0, [("infill", MODEL_FULL_INPAINTING)]))
    source_file = os.path.join(SCRATCH, "accepted_strip.png")
    with open(source_file, "wb") as handle:
        handle.write(FLAT_PNG)
    RETURNED_RGB = (200, 30, 160)
    elsewhere = png_bytes(Image.new("RGB", (L5.width, L5.height), RETURNED_RGB))

    def infill_via_cli(returned):
        recorder = tp.RecordingTransport([sub(1000), (200, {},
                                                      tp.fake_zip(returned)),
                                          sub(1000)])
        code, out, err = cli_call(["infill", "walk", "--cell", "2", "--from",
                                   source_file, "--seed", str(SEED)],
                                  recorder, infill_state)
        sent_image = (opened(base64.b64decode(recorder.posts[0].body[
            "parameters"]["image"])).convert("RGB") if recorder.posts else None)
        lines = [line for line in out.splitlines()
                 if line.startswith("composite")]
        kept_image = None
        if lines:
            with open(lines[0].split(None, 1)[1], "rb") as handle:
                kept_image = opened(handle.read()).convert("RGB")
        return code, sent_image, kept_image, infill_state.rows()[-1]

    code, sent_image, kept_image, row = infill_via_cli(elsewhere)
    want_kept = flat_image.copy()
    want_kept.paste(RETURNED_RGB, rect2)
    want_sent = flat_image.copy()
    want_sent.paste(init_image.crop(rect2), rect2[:2])
    expect("infill via the CLI: the sent image is the source with the "
           "mannequin in cell 2; the kept composite is the source with the "
           "RETURNED cell 2; the return differed outside the mask",
           (code, getattr(sent_image, "tobytes", lambda: None)()
            == want_sent.tobytes(),
            getattr(kept_image, "tobytes", lambda: None)()
            == want_kept.tobytes(), row["differs_outside_mask"]),
           (0, True, True, True))
    faithful = want_sent.copy()
    faithful.paste(RETURNED_RGB, rect2)
    code, sent_image, kept_image, row = infill_via_cli(png_bytes(faithful))
    expect("...and a return that changed only cell 2 is recorded as not "
           "differing outside the mask",
           (code, row["differs_outside_mask"]), (0, False))

    # -- risk R4 through the CLI: a late debit refutes the probe's proof -----
    r4 = scratch_state("late_debit_cli")
    for argv in (["run", "walk", "--action", "generate", "--seed", str(SEED)],
                 ["probe", "img2img", "--accept-max-2-anlas", "--seed",
                  str(SEED)]):
        cli_call(argv, tp.RecordingTransport([sub(1000), zipped(), sub(1000)]),
                 r4)
    code, out, err = cli_call(["run", "walk", "--action", "generate", "--seed",
                               str(SEED)], tp.RecordingTransport([sub(998)]), r4)
    lock_text = ""
    if r4.locked():
        with open(r4.lock_path, encoding="utf-8") as handle:
            lock_text = handle.read()
    expect("R4 via the CLI: the probe's debit lands late -- refused (9), LOCK "
           "naming the probe whose proof it refutes",
           (code, [p.action for p in r4.proofs()], "refutes its proof" in
            lock_text, "stay on the generate track" in lock_text),
           (2, ["img2img"], True, True))
    if r4.locked():
        os.remove(r4.lock_path)   # the author, after checking the account
    recorder = tp.RecordingTransport([sub(998), zipped(), sub(998)])
    code, out, err = cli_call(["run", "walk", "--action", "img2img", "--seed",
                               str(SEED)], recorder, r4)
    expect("...LOCK deleted by hand: production img2img is STILL refused (1), "
           "one GET, no POST",
           (code, "REFUTED" in err, [c.method for c in recorder.calls]),
           (2, True, ["GET"]))

    # -- a probe answered 200 with no image proves nothing, via the CLI ------
    hollow_cli = scratch_state("hollow_probe_cli")
    code, out, err = cli_call(
        ["probe", "img2img", "--accept-max-2-anlas", "--seed", str(SEED)],
        tp.RecordingTransport([sub(1000), (200, {"content-type": "text/html"},
                                           b"<html>maintenance</html>"),
                               sub(1000)]), hollow_cli)
    expect("probe answered 200 text/html at delta 0 via the CLI: exit 1, "
           "'proof not written', proofs.json unchanged",
           (code, "proof         not written" in out, "WRITTEN" in out,
            hollow_cli.proofs()), (1, True, False, ()))
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(990)])
    code, out, err = cli_call(["run", "walk", "--action", "img2img",
                               "--strength", "0.55", "--seed", str(SEED)],
                              recorder, hollow_cli)
    expect("...so production img2img at 0.55 is refused (exit 2), no POST",
           (code, [c.method for c in recorder.calls]), (2, ["GET"]))

    # -- a charged production img2img, LOCK deleted: plan and run refuse -----
    charged_cli = scratch_state("charged_after_proof_cli")
    i2i_argv = ["walk", "--action", "img2img", "--strength", "0.55", "--seed",
                str(SEED)]
    cli_call(["probe", "img2img", "--accept-max-2-anlas", "--seed", str(SEED)],
             tp.RecordingTransport([sub(1000), zipped(), sub(1000)]),
             charged_cli)
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(992)])
    code, out, err = cli_call(["run"] + i2i_argv, recorder, charged_cli)
    lock_text = ""
    if charged_cli.locked():
        with open(charged_cli.lock_path, encoding="utf-8") as handle:
            lock_text = handle.read()
        os.remove(charged_cli.lock_path)   # the author, by hand
    expect("run img2img charged 1000 -> 992 after its proof: exit 1, one POST, "
           "LOCK says stay on the generate track",
           (code, len(recorder.posts), "stay on the generate track" in lock_text),
           (1, 1, True))
    code, out, err = cli_call(["plan"] + i2i_argv, None, charged_cli)
    expect("...LOCK deleted: plan img2img is REFUSED offline (exit 2), "
           "condition 1 REFUTED, not 'confirmed by'",
           (code, "REFUSED offline" in out, "REFUTED by ledger row" in out,
            "confirmed by" in out), (2, True, True, False))
    recorder = tp.RecordingTransport([sub(992), zipped(), sub(984)])
    code, out, err = cli_call(["run"] + i2i_argv, recorder, charged_cli)
    expect("...and run img2img is refused (exit 2) after one GET, no POST",
           (code, [c.method for c in recorder.calls]), (2, ["GET"]))

    # -- every sending command prints the balances, a bad ZIP included -------
    code, out, err = cli_call(["run", "walk", "--action", "generate", "--seed",
                               str(SEED)], tp.RecordingTransport([
                                   sub(1000), (200, {}, corrupt_zip()),
                                   sub(983)]), scratch_state("corrupt_cli"))
    expect("a corrupt deflate stream via the CLI: exit 1, the balance line "
           "and LOCK printed",
           (code, "balance       before 1000 -> after 983, delta -17" in out,
            "LOCK          written" in out), (1, True, True))

    # -- img2img --from, the consistency re-pass ------------------------------
    code, out, err = cli_call(["plan", "walk", "--action", "img2img", "--from",
                               source_file, "--seed", str(SEED)], None,
                              scratch_state("plan_from"))
    expect("plan img2img --from: the file's sha256 is the image the body sends",
           (f"image         sha256:{hashlib.sha256(FLAT_PNG).hexdigest()}"
            in out, NoTransport.built), (True, 0))
    code, out, err = cli_call(["plan", "walk", "--action", "generate", "--from",
                               source_file, "--seed", str(SEED)], None,
                              scratch_state("plan_from_generate"))
    expect("...while generate --from is refused (exit 1)",
           (code, "do not apply to generate" in err), (1, True))
    lost_cli = scratch_state("lost_cli")
    lost_cli.save_blob(b"{}", "json")
    code, out, err = cli_call(["account"], tp.RecordingTransport([sub(1000)]),
                              lost_cli)
    expect("account on a LOST ledger prints the balance and says the chain "
           "cannot start", (code, "sum           1000" in out,
                            "chain         CANNOT START" in out),
           (0, True, True))

    # -----------------------------------------------------------------------
    print("\n8b. a sync client holding a file: local file operations settle")
    # -----------------------------------------------------------------------
    # Measured 2026-09-17: the repo lives in Dropbox, and a real, already-sent
    # request lost its bookkeeping to [WinError 32] on a blob's temp file.
    class _Sleeps(list):
        def __call__(self, seconds):
            if len(self) > 1000:
                raise AssertionError("_settle never stopped sleeping")
            self.append(seconds)

    def _held(times, result="done"):
        calls = []

        def operation(*args):
            calls.append(args)
            if len(calls) <= times:
                raise PermissionError(32, "being used by another process")
            return result
        return operation, calls

    naps = _Sleeps()
    op, calls = _held(2)
    expect("_settle returns once a held operation is released",
           (nai_state._settle(op, "a", sleep=naps), len(calls), naps),
           ("done", 3, [0.05, 0.1]))
    naps = _Sleeps()
    op, calls = _held(10 ** 6)
    expect_raises("_settle gives up after its budget and raises the "
                  "PermissionError unchanged", PermissionError,
                  lambda: nai_state._settle(op, sleep=naps, budget=1.0),
                  "another process")
    expect("...having slept exactly its budget, no more",
           round(sum(naps), 6), 1.0)
    naps = _Sleeps()

    def _missing(*_args):
        raise FileNotFoundError("gone")
    expect_raises("_settle does not retry anything but PermissionError",
                  FileNotFoundError,
                  lambda: nai_state._settle(_missing, sleep=naps))
    expect("...and did not sleep for it", list(naps), [])

    held_state = scratch_state("held")
    real_replace, real_remove = os.replace, os.remove
    replace_held = {"left": 2}
    remove_held = {"left": 2}

    def held_replace(src, dst):
        if replace_held["left"] > 0:
            replace_held["left"] -= 1
            raise PermissionError(32, "being used by another process")
        return real_replace(src, dst)

    def held_remove(path):
        if remove_held["left"] > 0:
            remove_held["left"] -= 1
            raise PermissionError(32, "being used by another process")
        return real_remove(path)

    os.replace, os.remove = held_replace, held_remove
    try:
        digest, rel = held_state.save_blob(b"held-by-dropbox", "json")
        blob_dir = os.path.join(held_state.root, nai_state.BLOBS_DIR)
        expect("save_blob lands its blob while the rename is briefly held",
               (os.path.isfile(os.path.join(held_state.root, rel)),
                sorted(n for n in os.listdir(blob_dir) if ".tmp-" in n)),
               (True, []))
        replace_held["left"] = 2
        held_state.acquire_inflight("held-row", 1000)
        remove_held["left"] = 2
        held_state.release_inflight("held-row")
        expect("release_inflight removes INFLIGHT while the delete is "
               "briefly held", held_state.inflight(), False)
    finally:
        os.replace, os.remove = real_replace, real_remove

finally:
    shutil.rmtree(SCRATCH, ignore_errors=True)


# ===========================================================================
print("\n9. nothing escaped")
# ===========================================================================
expect("no socket entry point was called outside section 0's own probes",
       NETWORK_ATTEMPTS, [])
expect("the repository's data/nai/ was not created by this check",
       os.path.lexists(REPO_STATE), REPO_STATE_EXISTED)
expect("the temporary state directory is gone", os.path.exists(SCRATCH), False)

print()
print(f"{sum(asserted)} assertions")
if failures:
    print(f"FAILED ({len(failures)}):")
    for label in failures:
        print(f"  - {label}")
    sys.exit(1)
print("PASS")
