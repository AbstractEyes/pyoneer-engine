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
 1b. characters: an outfit is a data file. A legal file loads (spacing
     normalised, parts in IDENTITY_PARTS order, the distance and shade
     rules' boundaries accepted, near misses such as `cropped jacket`
     accepted); every loader rule -- not JSON, not an object, a duplicate
     key, an unknown or missing field or part, non-ASCII, a control
     character, an empty tag, a count / rating / quality-tail / rating-word
     / view / negative tag in tags or anchor, including through NovelAI's
     `{}` and `1.5::` wrappers and inside a longer tag, an anchor tag that
     is not a tag verbatim, bad hex, a colour within 48 of the grey key or
     the outline, a colour whose x0.7 or x0.6 shade is within 40 of the key
     -- is refused with ITS OWN message naming the file and the field, and
     the same tag rule refuses a bad anchor through
     `recipes.character_caption` and a bad Identity built in code through
     `recipes.build_recipe`. The optional `subject` and `garments` fields
     carry the same weight: a file that writes neither is the boy in the
     default outfit it always was; a girl in a wizard hat, cape, dress and
     heels loads with her colours in model.PARTS order; and an unknown
     subject, a garment or a garment value nobody wrote (`0` is not
     `false`), a colour for a part these garments never draw (UNUSED, as
     against a part no garment draws at all), a missing one, and a word
     naming another subject (`male` in a girl file, `woman` in a boy one,
     while `boyish` names nobody) are each refused by their own message. A
     subject word spelled the booru way with an UNDERSCORE is refused on
     every route into a caption -- a file, an Identity built in code, a
     character caption -- because `judged` normalises the underscore for
     every rule at once rather than COUNT_RX spelling it alone; and a girl
     file's refusal names the subject it judged against instead of telling
     her the file is a boy.
     `available` lists only legal stems of regular files. A character over the token budget in ANY recipe is refused for
     every recipe, naming the file, counted exactly as guard condition 7
     counts (300 words builds and the guard agrees; 301 is refused). scout.json IS recipes.IDENTITY and the
     default; the blue-scarf file differs from it ONLY in the scarf tag and
     the scarf colour, reaches every caption and the init's pixels, and
     leaves no red scarf in the body; an unknown character is refused,
     listing the files. The default outfit still draws the sha256-PINNED
     bytes it drew before any garment vocabulary existed, for every recipe
     and for the image img2img sends, and wizard_girl.json carries her
     subject and garments all the way: 1girl at the head of every base
     caption, 'the same girl' in every sentence, every character caption
     opening 'girl,', no boy word anywhere in a built body or a printed
     plan, and a sent init wearing the hat above the head, the cape behind
     the dress, an A-line skirt and a heel at each foot, in her colours
     only, with nothing outside a cell -- while the same judge, shown the
     same girl with her hat and cape taken off, reports each of those
     missing. EVERY GARMENT SHAPE IS BOUNDED FROM BOTH SIDES, each half
     proved by mutating the constant it reads and asserting the judge, the
     brim geometry, the heel's notch or the mannequin's own name goes red:
     ten such mutations were measured leaving this suite green. Her hat and
     her cape carry different purples; a dressed arm draws the dress, bare
     skin and an outline wrist where a sleeved one draws two colours; the
     cape carries its own darkened line against every part in front of it
     and its root moves back with the lean; and a garmented mannequin's
     NAME is taken over the garments and every garment constant while the
     default outfit's is taken over neither.
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
  5. mannequin: every layout's centers -- the three recipes for scout, the
     same three for the wizard girl in her own garments, and four `strip`
     sizes -- are on the grid, distinct, inside their own cell and
     re-measured from the PNG's pixels; the init is exactly
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
     the main checkout's state root and sees its LOCK. `--character`
     reaches the plan's captions, an unknown name -- a path or a file name
     included -- exits 2 before anything is built, read or sent, a file
     the loader or the budget refuses exits 1 before a mannequin is drawn,
     and the default render file and sprites directory differ per
     character, each command printing the character's name.

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
import re
import shutil
import socket
import ssl
import sys
import tempfile
import traceback
import types
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
from tools.nai import (characters, cli, guard, mannequin, masks,  # noqa: E402
                       post, recipes, request, run)
from tools.nai import transport as tp  # noqa: E402
from tools.nai.model import (BACKGROUND_RGB, DEFAULT_COLOURS,  # noqa: E402
                             DEFAULT_GARMENTS, DEFAULT_SUBJECT, GENERATE_URL,
                             GRID, IDENTITY_PARTS, IMG2IMG_KEY,
                             INPAINT_STRENGTH_KEY, LEDGER_FIELDS, MAX_AREA,
                             MODEL_CURATED, MODEL_CURATED_INPAINTING,
                             MODEL_FULL, MODEL_FULL_INPAINTING,
                             NEVER_SEND_KEYS, NEVER_SEND_PREFIXES,
                             OUTLINE_RGB, PARTS, PROBE_STRENGTH, QUALITY_TAIL,
                             RATING_TAG, SUBJECT_NAMES, SUBSCRIPTION_URL,
                             Account, CellSpec, Frame, Garments, Identity,
                             Layout, LedgerContext, Pose, Proof,
                             garment_parts, on_grid,
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


@contextlib.contextmanager
def patched(module, name, value):
    """`module.name` is `value` inside the block, its old value after.

    THE OTHER HALF OF A DRAWING ASSERTION (CLAUDE.md law 5). A constant that
    only ever holds its shipped value is a constant no assertion covers: the
    checks below mutate one here and assert that the judge, or the mannequin
    name, goes red -- which is the mutation testing the law asks for, run on
    every suite pass instead of once by hand.
    """
    old = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, old)


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
    print("\n1b. characters: an outfit is a data file; a bad file is refused by name")
    # =======================================================================
    CHAR_DIR = os.path.join(SCRATCH, "characters")
    os.makedirs(CHAR_DIR)
    LEGAL_CHARACTER = {
        "tags": "black hair,  green cloak , two-tone boots, 2 buttons, "
                "boyish, aesthetic",
        "anchor": "black hair ,green cloak",
        # deliberately NOT in IDENTITY_PARTS order, and one part lower-case
        "colours": {"boots": "#7a4a24", "skin": "#E8B48C", "hair": "#6B4226",
                    "scarf": "#46A5E6", "tunic": "#3C64C8", "belt": "#5A3A1E",
                    "pants": "#C8A064"},
    }

    def character_file(stem, doc=None, raw=None):
        path = os.path.join(CHAR_DIR, f"{stem}.json")
        with open(path, "wb") as handle:
            handle.write(raw if raw is not None
                         else json.dumps(doc).encode("ascii"))
        return path

    def legal_but(change):
        doc = copy.deepcopy(LEGAL_CHARACTER)
        change(doc)
        return doc

    WANT_LEGAL = Identity(
        tags="black hair, green cloak, two-tone boots, 2 buttons, boyish, "
             "aesthetic",
        anchor="black hair, green cloak",
        colours=(("skin", (0xE8, 0xB4, 0x8C)), ("hair", (0x6B, 0x42, 0x26)),
                 ("scarf", (0x46, 0xA5, 0xE6)), ("tunic", (0x3C, 0x64, 0xC8)),
                 ("belt", (0x5A, 0x3A, 0x1E)), ("pants", (0xC8, 0xA0, 0x64)),
                 ("boots", (0x7A, 0x4A, 0x24))))
    legal_path = character_file("legal", LEGAL_CHARACTER)
    expect("a legal character file loads: tags and anchor re-joined with ', ', "
           "colours in IDENTITY_PARTS order, lower-case hex read, '2 buttons', "
           "'boyish' and 'aesthetic' are not count or quality tags",
           outcome(lambda: characters.load_file(legal_path)), WANT_LEGAL)
    expect("...the same file by name from its directory, and with a UTF-8 BOM",
           (outcome(lambda: characters.load("legal", CHAR_DIR)),
            outcome(lambda: characters.load_file(character_file(
                "legal_bom", raw=b"\xef\xbb\xbf" + json.dumps(
                    LEGAL_CHARACTER).encode("ascii"))))),
           (WANT_LEGAL, WANT_LEGAL))

    def set_colour(part, value):
        return lambda d: d["colours"].__setitem__(part, value)

    colour_pairs = ", ".join(f'"{k}": "{v}"'
                             for k, v in LEGAL_CHARACTER["colours"].items())
    DUPLICATE_RAW = ('{"tags": ' + json.dumps(LEGAL_CHARACTER["tags"])
                     + ', "anchor": ' + json.dumps(LEGAL_CHARACTER["anchor"])
                     + ', "colours": {' + colour_pairs
                     + ', "scarf": "#C83C3C"}}').encode("ascii")
    NON_ASCII_RAW = json.dumps(legal_but(lambda d: d.__setitem__(
        "tags", d["tags"] + ", CAFE_TUNIC")), ensure_ascii=False).replace(
        "CAFE_TUNIC", "caf\u00e9 tunic").encode("utf-8")
    CHARACTER_REFUSALS = (
        # (label, stem, doc, raw, field, the rule's own fragment)
        ("a file that is not JSON", "not_json", None, b'{"tags": ', None,
         "is not valid JSON"),
        ("a JSON list instead of one object", "a_list", [LEGAL_CHARACTER],
         None, None, "must be one JSON object"),
        ("a colour part written twice", "duplicate", None, DUPLICATE_RAW,
         "scarf", "duplicate key"),
        ("an unknown field", "unknown_field",
         legal_but(lambda d: d.__setitem__("hat", "red hat")), None, "hat",
         "unknown field"),
        ("a missing field", "missing_field",
         legal_but(lambda d: d.pop("anchor")), None, "anchor",
         "missing field"),
        ("tags that are not a string", "tags_list",
         legal_but(lambda d: d.__setitem__("tags", ["black hair"])), None,
         "tags", "must be a non-empty string"),
        ("non-ASCII tags (raw UTF-8)", "non_ascii_tags", None, NON_ASCII_RAW,
         "tags", "is not ASCII"),
        ("a non-ASCII anchor (JSON escape)", "non_ascii_anchor",
         legal_but(lambda d: d.__setitem__("anchor", "black hair, gr\u00fcn")),
         None, "anchor", "is not ASCII"),
        ("an empty tag", "empty_tag",
         legal_but(lambda d: d.__setitem__("tags", "black hair, , green cloak")),
         None, "tags", "empty tag"),
        ("a count tag in tags", "count_tags",
         legal_but(lambda d: d.__setitem__("tags", "1boy, " + d["tags"])),
         None, "tags", "count tag"),
        ("a capitalised count tag in the anchor", "count_anchor",
         legal_but(lambda d: d.__setitem__("anchor", "black hair, 2Girls")),
         None, "anchor", "count tag"),
        ("a 6+ count tag in tags", "count_plus",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", 6+others")),
         None, "tags", "count tag"),
        ("a rating tag in tags", "rating_tags",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", rating:general")),
         None, "tags", "rating tag"),
        ("a rating tag in the anchor", "rating_anchor",
         legal_but(lambda d: d.__setitem__("anchor",
                                           "black hair, rating:sensitive")),
         None, "anchor", "rating tag"),
        ("a quality-tail tag in tags", "quality_tags",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", masterpiece")),
         None, "tags", "quality tag"),
        ("a quality-tail tag in the anchor, any case", "quality_anchor",
         legal_but(lambda d: d.__setitem__("anchor",
                                           "black hair, Very Aesthetic")),
         None, "anchor", "quality tag"),
        ("an anchor word that is not in tags", "anchor_word",
         legal_but(lambda d: d.__setitem__("anchor", "black hair, red cloak")),
         None, "anchor", "not a tag of 'tags'"),
        ("an anchor tag assembled from tag words", "anchor_recombined",
         legal_but(lambda d: d.__setitem__("anchor", "green hair")), None,
         "anchor", "not a tag of 'tags'"),
        ("colours that are not an object", "colours_string",
         legal_but(lambda d: d.__setitem__("colours", "#E8B48C")), None,
         "colours", "must be an object"),
        ("a part no garment draws at all", "unknown_part",
         legal_but(set_colour("wings", "#46A5E6")), None, "colours",
         "unknown part"),
        ("a real part THESE garments do not draw", "unused_part",
         legal_but(set_colour("cape", "#46A5E6")), None, "colours",
         "unused part"),
        ("a missing part", "missing_part",
         legal_but(lambda d: d["colours"].pop("boots")), None, "colours",
         "missing part"),
        ("hex with five digits", "hex_five",
         legal_but(set_colour("scarf", "#46A5E")), None, "colours.scarf",
         "is not a '#RRGGBB'"),
        ("hex without the #", "hex_bare",
         legal_but(set_colour("scarf", "46A5E6")), None, "colours.scarf",
         "is not a '#RRGGBB'"),
        ("hex with a digit that is not hex", "hex_g",
         legal_but(set_colour("scarf", "#46A5EG")), None, "colours.scarf",
         "is not a '#RRGGBB'"),
        ("a colour written as a number", "hex_number",
         legal_but(set_colour("scarf", 4630246)), None, "colours.scarf",
         "is not a '#RRGGBB'"),
        ("the grey key itself", "grey_key",
         legal_but(set_colour("hair", "#808080")), None, "colours.hair",
         "grey key background"),
        ("a colour 47 from the grey key", "grey_47",
         legal_but(set_colour("pants", "#AF8080")), None, "colours.pants",
         "grey key background"),
        ("a colour 47 from the outline", "outline_47",
         legal_but(set_colour("belt", "#204F20")), None, "colours.belt",
         "near-black outline"),
        # -- what the model reads, not how the comma-separated tag is spelled
        ("a count tag in NovelAI braces", "count_braces",
         legal_but(lambda d: d.__setitem__("tags", "{2girls}, " + d["tags"])),
         None, "tags", "count tag"),
        ("a count tag in braces in the anchor", "count_braces_anchor",
         legal_but(lambda d: d.__setitem__("anchor", "black hair, {2girls}")),
         None, "anchor", "count tag"),
        ("a count tag inside a numeric weight", "count_weight",
         legal_but(lambda d: d.__setitem__("tags",
                                           "1.5::2girls::, " + d["tags"])),
         None, "tags", "count tag"),
        ("a count after a space inside one tag", "count_inside",
         legal_but(lambda d: d.__setitem__("tags", "black hair 2girls, "
                                           "green cloak")),
         None, "tags", "count tag"),
        ("a spaced count, '2 girls'", "count_spaced",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", 2 girls")),
         None, "tags", "count tag"),
        ("a two-digit count, '10girls'", "count_ten",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", 10girls")),
         None, "tags", "count tag"),
        ("'multiple girls'", "count_multiple",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", multiple girls")),
         None, "tags", "count tag"),
        ("'no humans'", "count_no_humans",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", no humans")),
         None, "tags", "count tag"),
        ("a quality-tail tag in braces", "quality_braces",
         legal_but(lambda d: d.__setitem__("tags",
                                           "{masterpiece}, " + d["tags"])),
         None, "tags", "quality tag"),
        ("a newline inside a tag", "control_newline",
         legal_but(lambda d: d.__setitem__("tags", "black hair\n2girls, "
                                           "green cloak")),
         None, "tags", "control character"),
        ("a NUL inside a tag", "control_nul",
         legal_but(lambda d: d.__setitem__("tags", "black hair\x00, "
                                           "green cloak")),
         None, "tags", "control character"),
        ("a tab inside an anchor tag", "control_tab",
         legal_but(lambda d: d.__setitem__("anchor", "black\thair")),
         None, "anchor", "control character"),
        ("a rating tag in braces", "rating_braces",
         legal_but(lambda d: d.__setitem__("tags",
                                           "{rating:explicit}, " + d["tags"])),
         None, "tags", "rating tag"),
        ("a rating tag after a word in the anchor", "rating_inside",
         legal_but(lambda d: d.__setitem__("anchor",
                                           "black hair rating:explicit")),
         None, "anchor", "rating tag"),
        ("rating:general itself in braces, which no other rule refuses",
         "rating_general_braces",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", {rating:general}")),
         None, "tags", "rating tag"),
        ("a rating tag spaced before its colon", "rating_spaced",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", rating :explicit")),
         None, "tags", "rating tag"),
        ("nsfw in tags", "rating_word_nsfw",
         legal_but(lambda d: d.__setitem__("tags", "nsfw, " + d["tags"])),
         None, "tags", "rating word"),
        ("explicit and nude in tags", "rating_word_explicit",
         legal_but(lambda d: d.__setitem__("tags",
                                           "explicit, nude, " + d["tags"])),
         None, "tags", "rating word"),
        ("nude in the anchor", "rating_word_anchor",
         legal_but(lambda d: d.__setitem__("anchor", "black hair, nude")),
         None, "anchor", "rating word"),
        ("a contradicting view in the anchor", "view_anchor",
         legal_but(lambda d: d.__setitem__(
             "anchor", "from behind, facing viewer, facing left, black hair")),
         None, "anchor", "view tag"),
        ("facing left in braces in tags", "view_tags",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", {facing left}")),
         None, "tags", "view tag"),
        ("a negative-prompt tag in tags", "negative_tags",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", watermark")),
         None, "tags", "negative tag"),
        ("a negative-prompt tag in braces in the anchor", "negative_anchor",
         legal_but(lambda d: d.__setitem__("anchor", "black hair, {blurry}")),
         None, "anchor", "negative tag"),
        ("a negative-prompt tag inside a numeric weight", "negative_weight",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", 1.5::watermark::")),
         None, "tags", "negative tag"),
        ("a negative-prompt tag in square brackets", "negative_square",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", [[3d]]")),
         None, "tags", "negative tag"),
        ("a negative-prompt tag inside a negative weight", "negative_minus",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", -1::logo::")),
         None, "tags", "negative tag"),
        ("an anchor tag that differs from its tag only in case",
         "anchor_case",
         legal_but(lambda d: d.__setitem__("anchor", "Black Hair, green cloak")),
         None, "anchor", "not a tag of 'tags'"),
        ("hex with eight digits", "hex_eight",
         legal_but(set_colour("scarf", "#46A5E6FF")), None, "colours.scarf",
         "is not a '#RRGGBB'"),
        # -- the shades the mannequin draws, not only the base colour
        ("a colour whose x0.7 shade IS the grey key", "shade_far_key",
         legal_but(set_colour("pants", "#B7B7B7")), None, "colours.pants",
         "x0.7 shade"),
        ("a light grey whose x0.7 shade is 36.4 from the key", "shade_tunic",
         legal_but(set_colour("tunic", "#D5D5D5")), None, "colours.tunic",
         "x0.7 shade"),
        ("a colour whose x0.7 shade is 5.2 from the key", "shade_far_near",
         legal_but(set_colour("boots", "#BBBBBB")), None, "colours.boots",
         "x0.7 shade"),
        ("a colour whose x0.7 shade is 39.3 from the key", "shade_far_39",
         legal_but(set_colour("skin", "#D69696")), None, "colours.skin",
         "x0.7 shade"),
        ("a colour whose x0.6 shade alone is 16 from the key", "shade_inner",
         legal_but(set_colour("hair", "#F0D6D6")), None, "colours.hair",
         "x0.6 shade"),
        ("a colour whose x0.6 shade alone is 39.3 from the key",
         "shade_inner_39",
         legal_but(set_colour("belt", "#96E1E1")), None, "colours.belt",
         "x0.6 shade"),
    )
    RULE_FRAGMENTS = {row[5] for row in CHARACTER_REFUSALS}
    for label, stem, doc, raw, field, fragment in CHARACTER_REFUSALS:
        path = character_file(stem, doc, raw)
        where = [f"{stem}.json"] + ([f"field {field!r}"] if field else [])
        caught = expect_raises(f"{label} is refused, naming the file and field",
                               ValueError,
                               lambda p=path: characters.load_file(p),
                               *where, fragment)
        expect(f"...with its own message and no other rule's",
               sorted(other for other in RULE_FRAGMENTS - {fragment}
                      if other in str(caught)), [])
    boundary = []
    for stem, change, part in (
            ("grey_48", set_colour("pants", "#B08080"), "pants"),
            ("outline_48", set_colour("belt", "#205020"), "belt")):
        loaded = outcome(lambda c=change, s=stem: characters.load_file(
            character_file(s, legal_but(c))))
        boundary.append(loaded.colour(part) if isinstance(loaded, Identity)
                        else loaded)
    expect("...while 48 from the grey key and 48 from the outline both load",
           boundary, [(0xB0, 0x80, 0x80), (0x20, 0x50, 0x20)])
    expect("...and an anchor that is a subset of the tags loads",
           getattr(outcome(lambda: characters.load_file(character_file(
               "anchor_subset", legal_but(lambda d: d.__setitem__(
                   "anchor", "green cloak"))))), "anchor", None),
           "green cloak")
    expect_raises("an unknown character name is refused, listing the files",
                  ValueError, lambda: characters.load("nobody", CHAR_DIR),
                  "unknown character 'nobody'", "legal (legal.json)")
    expect_raises("...and a path in place of a name is an unknown name, never "
                  "a file read", ValueError,
                  lambda: characters.load(os.path.join("..", "characters",
                                                       "legal"), CHAR_DIR),
                  "unknown character")
    shade_boundary = []
    for stem, change, part in (
            ("shade_far_40", set_colour("pants", "#7DB7B7"), "pants"),
            ("shade_inner_40", set_colour("tunic", "#92D5D6"), "tunic")):
        loaded = outcome(lambda c=change, s=stem: characters.load_file(
            character_file(s, legal_but(c))))
        shade_boundary.append(loaded.colour(part)
                              if isinstance(loaded, Identity) else loaded)
    expect("...while an x0.7 shade exactly 40 from the key (#7DB7B7) and an "
           "x0.6 shade exactly 40 (#92D5D6) both load",
           (shade_boundary,
            [characters.distance_sq(mannequin._shade(rgb, factor),
                                    BACKGROUND_RGB)
             for rgb, factor in zip(shade_boundary, (0.7, 0.6))
             if isinstance(rgb, tuple)]),
           ([(0x7D, 0xB7, 0xB7), (0x92, 0xD5, 0xD6)], [1600, 1600]))
    expect("...and the mannequin draws exactly the shades the loader judged",
           (mannequin._shade is characters.shade,
            (mannequin.FAR_SHADE, mannequin.INNER_SHADE),
            tuple(factor for factor, _drawn in characters.SHADES)),
           (True, (0.7, 0.6), (0.7, 0.6)))
    NEAR_MISS_TAGS = ("black hair, green cloak, cropped jacket, logo patch, "
                      "text on shirt, boy scout hat, other knee pad, "
                      "sensitivity charm, backpack, 1.5::two-tone boots::, "
                      "{{aesthetic}}")
    expect("near misses load verbatim: a negative tag inside a longer tag, "
           "boy/other without a count, a rating word inside a longer word, "
           "and wrappers around legal tags",
           getattr(outcome(lambda: characters.load_file(character_file(
               "near_misses", legal_but(lambda d: d.__setitem__(
                   "tags", NEAR_MISS_TAGS))))), "tags", None),
           NEAR_MISS_TAGS)
    LIST_DIR = os.path.join(SCRATCH, "character_listing")
    os.makedirs(os.path.join(LIST_DIR, "dir.json"))
    for listed in ("good_one.json", "...json", "Bad-Name.json", "x.y.json",
                   ".json", "9lives.json", "notes.txt"):
        with open(os.path.join(LIST_DIR, listed), "wb") as handle:
            handle.write(json.dumps(LEGAL_CHARACTER).encode("ascii"))
    expect("available lists only a legal stem of a regular .json file: not "
           "'..', a capital or hyphen, a dot, an empty stem, a leading digit, "
           "another extension or a directory named dir.json",
           outcome(lambda: characters.available(LIST_DIR)), ("good_one",))
    for smuggled in ("..", "dir", "x.y", "Bad-Name"):
        expect_raises(f"...and load({smuggled!r}) from that directory is an "
                      f"unknown character", ValueError,
                      lambda n=smuggled: characters.load(n, LIST_DIR),
                      f"unknown character {smuggled!r}",
                      "good_one (good_one.json)")

    # -- an Identity built in code: build_recipe applies the same tag rule ------
    for field, bad, fragment in (
            ("tags", recipes.IDENTITY.tags + ", {2girls}", "count tag"),
            ("tags", recipes.IDENTITY.tags + ", {rating:explicit}",
             "rating tag"),
            ("anchor", "brown hair, nsfw", "rating word"),
            ("anchor", "brown hair, facing left", "view tag")):
        expect_raises(f"build_recipe refuses an in-code identity whose "
                      f"{field} field carries a {fragment}", ValueError,
                      lambda f=field, b=bad: recipes.build_recipe(
                          "walk", dataclasses.replace(recipes.IDENTITY,
                                                      **{f: b})),
                      f"identity, field {field!r}", fragment)
    saved_style = recipes.BASE_STYLE
    recipes.BASE_STYLE = saved_style + ", rating:explicit"
    try:
        expect_raises("a rating tag anywhere in the base caption before its "
                      "quality tail is refused by the Recipe itself",
                      ValueError,
                      lambda: recipes.build_recipe("walk", recipes.IDENTITY),
                      "a rating tag sits in the base caption")
    finally:
        recipes.BASE_STYLE = saved_style

    # -- the token budget: every recipe, counted as guard condition 7 counts --
    RANGER_TAGS = ("silver hair, long hair, ponytail, green eyes, white "
                   "headband, red scarf, blue tunic, brown leather gloves, "
                   "brown belt, belt pouch, tan pants, knee pads, brown "
                   "boots, short sword on back")
    RANGER_ANCHOR = ("silver hair, ponytail, white headband, red scarf, blue "
                     "tunic, brown leather gloves, belt pouch, short sword on "
                     "back")
    ranger_files = {}
    for stem, tags in (
            ("ranger", RANGER_TAGS),
            ("ranger_301", RANGER_TAGS.replace(", green eyes", "")
             .replace(", knee pads", "")),
            ("ranger_300", RANGER_TAGS.replace(", green eyes", "")
             .replace(", knee pads", "").replace("brown belt", "belt"))):
        ranger_files[stem] = character_file(stem, legal_but(
            lambda d, t=tags: d.update(tags=t, anchor=RANGER_ANCHOR)))
    ranger = outcome(lambda: characters.load_file(ranger_files["ranger"]))
    expect("the ranger file (14 tags, 8 anchor tags) counts 266 / 305 / 247 "
           "words for walk / run / jump, as guard condition 7 counts",
           ([outcome(lambda n=n: recipes.caption_words(n, ranger))
             for n in ("walk", "run", "jump")], recipes.WORD_RE is guard._WORD_RE),
           ([266, 305, 247], True))
    for name in ("walk", "run", "jump"):
        expect_raises(f"build_recipe({name!r}) refuses the ranger file: run is "
                      f"over the budget, so every recipe is, naming the file",
                      ValueError,
                      lambda n=name: recipes.build_recipe(
                          n, ranger, source=ranger_files["ranger"]),
                      "ranger.json", "fields 'tags' and 'anchor'",
                      "recipe run would carry 305 words ~ 457.5 tokens",
                      "token budget of 450")
    saved_dir = characters.CHARACTERS_DIR
    characters.CHARACTERS_DIR = CHAR_DIR
    try:
        expect_raises("get_recipe for a character one word over (301 words ~ "
                      "451.5 tokens) is refused, naming its file", ValueError,
                      lambda: recipes.get_recipe("jump", "ranger_301"),
                      os.path.normpath(ranger_files["ranger_301"]),
                      "fields 'tags' and 'anchor'",
                      "recipe run would carry 301 words ~ 451.5 tokens")
        fit = outcome(lambda: recipes.make_request("run", "generate", SEED,
                                                   character="ranger_300"))
        fit_c7 = ([(v.ok, v.message) for v in guard.evaluate(
            request.build_body(fit), None, (), scratch_state("budget_300"),
            url=GENERATE_URL) if v.condition == 7]
            if hasattr(fit, "frames") else fit)
    finally:
        characters.CHARACTERS_DIR = saved_dir
    expect("...while exactly 300 words (450 tokens) builds, and guard condition "
           "7 counts the same 300 and passes it",
           fit_c7, [(True, "ASCII, 300 words ~ 450 tokens, rating closes the "
                           "base")])

    # -- the other route into a character caption: one tag rule ----------------
    for bad_anchor, fragment in (("brown hair, 1boy", "count tag"),
                                 ("brown hair, masterpiece", "quality tag"),
                                 ("brown hair, rating:general", "rating tag"),
                                 ("brown hair, {2girls}", "count tag"),
                                 ("brown hair, from behind", "view tag"),
                                 ("brown hair, blurry", "negative tag"),
                                 ("brown hair\x00", "control character")):
        expect_raises(f"character_caption refuses the anchor {bad_anchor!r}",
                      ValueError,
                      lambda a=bad_anchor: recipes.character_caption(
                          dataclasses.replace(recipes.IDENTITY, anchor=a),
                          "walking"), fragment)
    expect("...while the scout anchor builds the pinned caption",
           recipes.character_caption(recipes.IDENTITY, "walking"),
           PIN_CAPTION + "walking")

    # -- 1c. the subject and the garments: one table, every route ----------
    PIN_DEFAULT_PARTS = ("skin", "hair", "scarf", "tunic", "belt", "pants",
                         "boots")
    PIN_PARTS = PIN_DEFAULT_PARTS + ("dress", "heels", "cape", "hat")
    PIN_SUBJECTS = ("boy", "girl")
    expect("the DEFAULT outfit draws the seven parts it always drew, the "
           "vocabulary adds dress, heels, cape and hat, and a file with "
           "neither new field is a boy in those default garments",
           (IDENTITY_PARTS, PARTS, SUBJECT_NAMES, DEFAULT_SUBJECT,
            DEFAULT_GARMENTS, garment_parts(DEFAULT_GARMENTS),
            (WANT_LEGAL.subject, WANT_LEGAL.garments)),
           (PIN_DEFAULT_PARTS, PIN_PARTS, PIN_SUBJECTS, "boy",
            Garments("none", False, "scarf", "pants", "boots"),
            PIN_DEFAULT_PARTS, ("boy", Garments())))
    LEGAL_GIRL = {
        "subject": "girl",
        "tags": "blonde hair, pointed hat, crimson dress, violet cape, "
                "blue shoes, boyish",
        "anchor": "blonde hair, pointed hat, crimson dress",
        "garments": {"hat": "wizard", "cape": True, "neck": "none",
                     "legwear": "dress", "footwear": "heels"},
        # deliberately NOT in model.PARTS order
        "colours": {"hat": "#8C3CC8", "cape": "#8C3CC8", "heels": "#1E5AF0",
                    "dress": "#C83232", "belt": "#5A3A1E",
                    "hair": "#E8C85A", "skin": "#E8B48C"},
    }
    WANT_GIRL = Identity(
        tags="blonde hair, pointed hat, crimson dress, violet cape, "
             "blue shoes, boyish",
        anchor="blonde hair, pointed hat, crimson dress",
        colours=(("skin", (0xE8, 0xB4, 0x8C)), ("hair", (0xE8, 0xC8, 0x5A)),
                 ("belt", (0x5A, 0x3A, 0x1E)), ("dress", (0xC8, 0x32, 0x32)),
                 ("heels", (0x1E, 0x5A, 0xF0)), ("cape", (0x8C, 0x3C, 0xC8)),
                 ("hat", (0x8C, 0x3C, 0xC8))),
        subject="girl",
        garments=Garments("wizard", True, "none", "dress", "heels"))
    girl_path = character_file("legal_girl", LEGAL_GIRL)
    expect("a girl in a wizard hat, a cape, a dress and heels loads: her "
           "subject, her garments, her colours in model.PARTS order, and "
           "'boyish' names nobody",
           outcome(lambda: characters.load_file(girl_path)), WANT_GIRL)

    def girl_but(change):
        doc = copy.deepcopy(LEGAL_GIRL)
        change(doc)
        return doc

    def set_garment(name, value):
        return lambda d: d.__setitem__("garments", {name: value})

    GARMENT_RAW = ('{"tags": ' + json.dumps(LEGAL_CHARACTER["tags"])
                   + ', "anchor": ' + json.dumps(LEGAL_CHARACTER["anchor"])
                   + ', "colours": {' + colour_pairs
                   + '}, "garments": {"cape": false, "cape": true}}'
                   ).encode("ascii")
    OUTFIT_REFUSALS = (
        # (label, stem, doc, raw, field, the rule's own fragment)
        ("an unknown subject", "subject_woman",
         legal_but(lambda d: d.__setitem__("subject", "woman")), None,
         "subject", "is not a subject"),
        ("a subject that is not a string", "subject_number",
         legal_but(lambda d: d.__setitem__("subject", 1)), None, "subject",
         "is not a subject"),
        ("garments that are not an object", "garments_string",
         legal_but(lambda d: d.__setitem__("garments", "wizard")), None,
         "garments", "must be an object"),
        ("an unknown garment", "garments_gloves",
         legal_but(set_garment("gloves", "leather")), None, "garments",
         "unknown garment"),
        ("a garment written twice", "garments_duplicate", None, GARMENT_RAW,
         "cape", "duplicate key"),
        ("a hat nobody wrote", "hat_crown",
         legal_but(set_garment("hat", "crown")), None, "garments.hat",
         "is not a legal hat"),
        ("a cape written as 0, which is not false", "cape_zero",
         legal_but(set_garment("cape", 0)), None, "garments.cape",
         "is not a legal cape"),
        ("a cape written as the string 'true'", "cape_string",
         legal_but(set_garment("cape", "true")), None, "garments.cape",
         "is not a legal cape"),
        ("a neck nobody wrote", "neck_tie",
         legal_but(set_garment("neck", "tie")), None, "garments.neck",
         "is not a legal neck"),
        ("legwear nobody wrote", "legwear_kilt",
         legal_but(set_garment("legwear", "kilt")), None, "garments.legwear",
         "is not a legal legwear"),
        ("footwear nobody wrote", "footwear_sandals",
         legal_but(set_garment("footwear", "sandals")), None,
         "garments.footwear", "is not a legal footwear"),
        ("a scarf colour under 'neck': 'none'", "unused_scarf",
         legal_but(set_garment("neck", "none")), None, "colours",
         "unused part"),
        ("a dress outfit still carrying pants and tunic", "unused_trousers",
         girl_but(lambda d: d["colours"].update(pants="#C8A064",
                                                tunic="#3C64C8")), None,
         "colours", "unused part"),
        ("a dress outfit with no dress colour", "missing_dress",
         girl_but(lambda d: d["colours"].pop("dress")), None, "colours",
         "missing part"),
        ("a hat garment with no hat colour", "missing_hat",
         girl_but(lambda d: d["colours"].pop("hat")), None, "colours",
         "missing part"),
        ("a boy tag in a girl file", "girl_boy_tag",
         girl_but(lambda d: d.__setitem__("tags", d["tags"] + ", boy")), None,
         "tags", "subject word"),
        ("'male' in a girl file, inside a longer tag", "girl_male_tag",
         girl_but(lambda d: d.__setitem__("tags",
                                          d["tags"] + ", male knight")), None,
         "tags", "subject word"),
        ("'man' in a girl file's anchor, in NovelAI braces", "girl_man_anchor",
         girl_but(lambda d: d.__setitem__("anchor",
                                          d["anchor"] + ", {old man}")),
         None, "anchor", "subject word"),
        ("'woman' in a boy file", "boy_woman_tag",
         legal_but(lambda d: d.__setitem__("tags", d["tags"] + ", woman")),
         None, "tags", "subject word"),
        ("'female' in a boy file, inside a numeric weight", "boy_female_tag",
         legal_but(lambda d: d.__setitem__("tags",
                                           d["tags"] + ", 1.5::female::")),
         None, "tags", "subject word"),
    )
    OUTFIT_FRAGMENTS = RULE_FRAGMENTS | {row[5] for row in OUTFIT_REFUSALS}
    for label, stem, doc, raw, field, fragment in OUTFIT_REFUSALS:
        path = character_file(stem, doc, raw)
        where = [f"{stem}.json"] + ([f"field {field!r}"] if field else [])
        caught = expect_raises(f"{label} is refused, naming the file and field",
                               ValueError,
                               lambda p=path: characters.load_file(p),
                               *where, fragment)
        expect(f"...with its own message and no other rule's",
               sorted(other for other in OUTFIT_FRAGMENTS - {fragment}
                      if other in str(caught)), [])
    partial = outcome(lambda: characters.load_file(character_file(
        "partial_garments", legal_but(
            lambda d: (d.__setitem__("garments", {"neck": "none"}),
                       d["colours"].pop("scarf"))))))
    expect("a garments object writes only what it changes: 'neck': 'none' "
           "keeps the other four defaults, and the colours then name exactly "
           "the six parts left",
           (getattr(partial, "garments", partial),
            tuple(part for part, _rgb in getattr(partial, "colours", ()))),
           (Garments("none", False, "none", "pants", "boots"),
            ("skin", "hair", "tunic", "belt", "pants", "boots")))
    expect("tag_problem judges a word against the subject it is GIVEN: "
           "'male' and 'man' name a boy, 'woman' and 'female' a girl, and "
           "'boyish' names nobody",
           [characters.tag_problem(tag, who)
            for tag, who in (("male", "girl"), ("male", "boy"),
                             ("old man", "girl"), ("old man", "boy"),
                             ("woman", "boy"), ("woman", "girl"),
                             ("female", "boy"), ("female", "girl"),
                             ("boyish", "girl"), ("brown hair", "girl"))],
           ["subject word", None, "subject word", None, "subject word", None,
            "subject word", None, None, None])
    expect_raises("...and refuses to judge against a subject nobody declared",
                  ValueError,
                  lambda: characters.tag_problem("brown hair", "robot"),
                  "unknown subject 'robot'")
    # A BOORU TAG IS WRITTEN WITH UNDERSCORES AS OFTEN AS WITH SPACES, and
    # every word rule here is a `\b`-bounded phrase, so an underscore used to
    # hide all of them at once: `magical_girl` loaded into a boy file and
    # `old_man` into a girl file, each building a caption that asks for two
    # people -- the exact failure the subject rule exists to stop. COUNT_RX
    # was the only rule that spelled `[\s_-]` itself; `judged` now normalises
    # it for every rule, so ONE mutation turns them all red (CLAUDE.md,
    # ACTIVE WARNINGS: the sibling route).
    expect("judged() normalises an underscore to a space, so every rule reads "
           "the same text: the weight syntax, the underscore and runs of "
           "space all collapse",
           (characters.judged("Magical_Girl"),
            characters.judged("{2girls}"),
            characters.judged("1.5::female_focus::"),
            characters.judged("brown__hair")),
           ("magical girl", "2girls", "female focus", "brown hair"))
    expect("...so an underscored subject word is refused in EITHER "
           "direction, an underscored count and negative tag with it, and a "
           "word that merely contains one is still nobody",
           [characters.tag_problem(tag, who) for tag, who in (
               ("magical_girl", "boy"), ("school_girl", "boy"),
               ("female_focus", "boy"), ("cow_girl", "boy"),
               ("the_woman", "boy"), ("male_focus", "girl"),
               ("old_man", "girl"), ("salary_man", "girl"),
               ("boy_scout", "girl"), ("man_made", "girl"),
               ("1_girl", "boy"), ("jpeg_artifacts", "boy"),
               ("boyish", "girl"), ("brown_hair", "girl"))],
           ["subject word"] * 10 + ["count tag", "negative tag", None, None])
    GIRL = characters.load_file(girl_path)
    for label, identity, field, fragment in (
            ("an unknown subject",
             dataclasses.replace(recipes.IDENTITY, subject="robot"),
             "subject", "unknown subject"),
            ("garments that are not a Garments",
             dataclasses.replace(recipes.IDENTITY,
                                 garments={"hat": "wizard"}),
             "garments", "must be a Garments"),
            ("a garment choice nobody wrote",
             dataclasses.replace(recipes.IDENTITY,
                                 garments=Garments(hat="crown")),
             "garments", "is not a legal hat"),
            ("colours that do not match the garments",
             dataclasses.replace(recipes.IDENTITY,
                                 garments=Garments(legwear="dress")),
             "colours", "unused part"),
            ("a boy word in a girl identity's tags",
             dataclasses.replace(GIRL, tags=GIRL.tags + ", male"),
             "tags", "subject word")):
        expect_raises(f"build_recipe refuses an in-code identity with "
                      f"{label}", ValueError,
                      lambda i=identity: recipes.build_recipe("walk", i),
                      f"identity, field {field!r}", fragment)
    expect("character_caption opens with the identity's OWN subject noun",
           (recipes.character_caption(GIRL, "walking"),
            recipes.character_caption(recipes.IDENTITY, "walking")),
           (f"girl, {WANT_GIRL.anchor}, from side, facing right, walking",
            PIN_CAPTION + "walking"))
    expect_raises("...and refuses an anchor that names another subject",
                  ValueError,
                  lambda: recipes.character_caption(
                      dataclasses.replace(GIRL, anchor="blonde hair, male"),
                      "walking"), "subject word")
    # The same hole, end to end on every route into a caption: a file, an
    # in-code identity and a character caption.
    for label, call in (
            ("a character file",
             lambda: characters.load_file(character_file(
                 "underscored", legal_but(lambda d: d.__setitem__(
                     "tags", d["tags"] + ", magical_girl"))))),
            ("an in-code identity through build_recipe",
             lambda: recipes.build_recipe("walk", dataclasses.replace(
                 recipes.IDENTITY,
                 tags=recipes.IDENTITY.tags + ", magical_girl"))),
            ("a character caption",
             lambda: recipes.character_caption(dataclasses.replace(
                 recipes.IDENTITY,
                 anchor=recipes.IDENTITY.anchor + ", school_girl"),
                 "walking"))):
        expect_raises(f"an UNDERSCORED subject word is refused through "
                      f"{label}", ValueError, call, "subject word")
    girl_refusal = expect_raises(
        "a GIRL file refusing a boy word names the subject it judged "
        "against, and never calls her a boy", ValueError,
        lambda: characters.load_file(character_file(
            "girl_male_focus", legal_but(lambda d: (
                d.__setitem__("subject", "girl"),
                d.__setitem__("tags", d["tags"] + ", male_focus"))))),
        "subject word", "the subject judged here is 'girl'")
    expect("...and that refusal carries no claim that this file is a boy, "
           "which is what \"(default 'boy')\" inside \"this file's 'subject' "
           "field\" said to every girl who tripped the rule",
           ("boy" in str(girl_refusal),
            "subject word" in characters.TAG_PROBLEMS,
            "boy" in characters.TAG_PROBLEMS["subject word"]),
           (False, True, False))
    expect_raises("render_init refuses colours missing a part the garments "
                  "draw", KeyError,
                  lambda: mannequin.render_init(
                      L5, WALK.poses, COLOURS,
                      garments=Garments(legwear="dress")), "'dress'")
    expect_raises("...and colours for a part they never draw", ValueError,
                  lambda: mannequin.render_init(
                      L5, WALK.poses, dict(COLOURS, hat=(0x8C, 0x3C, 0xC8))),
                  "do not draw")

    # -- the shipped files ----------------------------------------------------
    SCOUT = characters.load("scout")
    BLUE = characters.load("scout_blue_scarf")
    expect("scout.json IS recipes.IDENTITY -- tags, anchor and colours -- and "
           "scout is the default character",
           (SCOUT == recipes.IDENTITY, characters.DEFAULT_CHARACTER),
           (True, "scout"))
    expect("...so its tags and anchor are the brief's pinned identity text",
           (SCOUT.tags, SCOUT.anchor),
           (PIN_IDENTITY, "brown hair, red scarf, blue tunic"))
    # MEASURED 2026-09-17 on the shipped scout BEFORE the garment vocabulary
    # existed, and pinned here as literals: the default outfit must draw the
    # same pixels and answer to the same mannequin name afterwards.
    PIN_SCOUT_INIT = {
        "walk": "9a7c03a2ab8585516a32556d947aa36f80a8c3b47fe0af51121bb12ca4ec536a",
        "run": "e6011966819876ff76567d7a9f993af7c4eb50c605d2d4ab9272547f514f998f",
        "jump": "b48d64e56616906ee4ceafa0a306b0107f7f660254c9dd9c8d7387457afd1811",
    }
    PIN_SCOUT_PARAMS = {
        "walk": "607042448f45d2477a5f53b94603d6a0503519d21dde007feea82e0d2f22a9fc",
        "run": "72c94e2504390765582323bad47c22b089c784f4cea6de50a1550f38c513db7d",
        "jump": "aa244a876960234c8bf0a578fa33fbc1a0f691457922566a798c983454582dc5",
    }
    scout_drawn = {}
    for name in ("walk", "run", "jump"):
        recipe = recipes.RECIPES[name]
        drawn, _c = mannequin.render_init(recipe.layout, recipe.poses,
                                          SCOUT.as_dict(),
                                          garments=SCOUT.garments)
        sent = recipes.make_request(name, "img2img", SEED).image_png
        scout_drawn[name] = (
            hashlib.sha256(drawn).hexdigest(),
            hashlib.sha256(sent).hexdigest(),
            mannequin.params_sha256(recipe.layout, recipe.poses,
                                    SCOUT.as_dict(),
                                    garments=SCOUT.garments),
            mannequin.params_sha256(recipe.layout, recipe.poses,
                                    SCOUT.as_dict()))
    expect("the default outfit still draws the pinned bytes: the init of "
           "every recipe, the image img2img sends, and the mannequin name -- "
           "with the garments passed and left out alike",
           scout_drawn,
           {name: (PIN_SCOUT_INIT[name], PIN_SCOUT_INIT[name],
                   PIN_SCOUT_PARAMS[name], PIN_SCOUT_PARAMS[name])
            for name in ("walk", "run", "jump")})
    expect("get_recipe for the default character, and for scout, equals "
           "RECIPES for every recipe",
           [(recipes.get_recipe(n) == recipes.RECIPES[n],
             recipes.get_recipe(n, character="scout") == recipes.RECIPES[n])
            for n in ("walk", "run", "jump")], [(True, True)] * 3)

    def tag_changes(a, b):
        left, right = a.split(", "), b.split(", ")
        return (len(left) == len(right),
                [(x, y) for x, y in zip(left, right) if x != y])
    expect("scout_blue_scarf differs from scout ONLY in the scarf tag, in tags "
           "and in anchor",
           (tag_changes(SCOUT.tags, BLUE.tags),
            tag_changes(SCOUT.anchor, BLUE.anchor)),
           ((True, [("red scarf", "blue scarf")]),
            (True, [("red scarf", "blue scarf")])))
    expect("...and ONLY in the scarf colour, a light sky blue #46A5E6",
           ([part for part in IDENTITY_PARTS
             if SCOUT.colour(part) != BLUE.colour(part)],
            BLUE.colour("scarf")), (["scarf"], (0x46, 0xA5, 0xE6)))
    expect("...which stays at least 48 (Euclidean RGB) from the tunic blue",
           characters.distance_sq(BLUE.colour("scarf"), BLUE.colour("tunic"))
           >= 48 * 48, True)
    for name in ("walk", "run", "jump"):
        blue_recipe = recipes.get_recipe(name, character="scout_blue_scarf")
        blue_req = recipes.make_request(name, "generate", SEED,
                                        character="scout_blue_scarf")
        blue_text = json.dumps(request.build_body(blue_req))
        expect(f"{name} for scout_blue_scarf: the brief's base caption with "
               f"the scarf swapped, every character caption blue, and no "
               f"red scarf anywhere in the body",
               (blue_recipe.base_caption
                == PIN_BASE[name].replace("red scarf", "blue scarf"),
                blue_req.base_caption == blue_recipe.base_caption,
                [f.caption for f in blue_req.frames]
                == [PIN_CAPTION.replace("red scarf", "blue scarf") + words
                    for words in PIN_POSES[name]],
                "red scarf" in blue_text, blue_text.count("blue scarf")),
               (True, True, True, False, 2 + 2 * len(PIN_POSES[name])))
    RED_SCARF, BLUE_SCARF = SCOUT.colour("scarf"), BLUE.colour("scarf")

    def scarf_shades(rgb):
        return (rgb, mannequin._shade(rgb, mannequin.FAR_SHADE),
                mannequin._shade(rgb, mannequin.INNER_SHADE))
    blue_i2i = recipes.make_request("walk", "img2img", SEED,
                                    character="scout_blue_scarf")
    blue_init = opened(blue_i2i.image_png).convert("RGB")
    scout_init = opened(INIT_PNG).convert("RGB")
    blue_colours = {rgb for _n, rgb in blue_init.getcolors(1 << 20)}
    scout_colours = {rgb for _n, rgb in scout_init.getcolors(1 << 20)}
    recolour = dict(zip(scarf_shades(RED_SCARF), scarf_shades(BLUE_SCARF)))
    expect("the blue img2img init draws the new scarf colour and no red "
           "(base, x0.7 or x0.6); the scout init is the reverse",
           (BLUE_SCARF in blue_colours,
            sorted(set(scarf_shades(RED_SCARF)) & blue_colours),
            RED_SCARF in scout_colours,
            sorted(set(scarf_shades(BLUE_SCARF)) & scout_colours)),
           (True, [], True, []))
    expect("...and it IS the scout init with only the scarf pixels recoloured",
           sum(1 for a, b in zip(scout_init.getdata(), blue_init.getdata())
               if recolour.get(a, a) != b), 0)
    expect("context_for names each character's own mannequin",
           (recipes.context_for("walk").mannequin_sha256
            == mannequin.params_sha256(L5, WALK.poses, SCOUT.as_dict()),
            recipes.context_for("walk", character="scout_blue_scarf")
            .mannequin_sha256
            == mannequin.params_sha256(L5, WALK.poses, BLUE.as_dict()),
            SCOUT.as_dict() != BLUE.as_dict()), (True, True, True))
    for label, call in (
            ("get_recipe", lambda: recipes.get_recipe(
                "walk", character="scout_green")),
            ("make_request", lambda: recipes.make_request(
                "walk", "generate", SEED, character="scout_green")),
            ("context_for", lambda: recipes.context_for(
                "walk", character="scout_green"))):
        expect_raises(f"{label} for an unknown character raises, listing the "
                      f"shipped files", ValueError, call,
                      "unknown character 'scout_green'", "scout.json",
                      "scout_blue_scarf.json")

    # -- 1d. wizard_girl: a girl in a wizard hat, a cape, a dress and heels --
    def shades_of(rgb):
        """Every shade of `rgb` the mannequin can draw: the colour, its far
        and inner shades, and a far pixel an inner line darkened again."""
        far = mannequin._shade(rgb, mannequin.FAR_SHADE)
        return {rgb, far, mannequin._shade(rgb, mannequin.INNER_SHADE),
                mannequin._shade(far, mannequin.INNER_SHADE)}

    WIZARD = characters.load("wizard_girl")
    PIN_WIZARD_TAGS = ("blonde hair, wizard hat, purple headwear, red dress, "
                       "purple cape, cape, high heels, blue footwear")
    PIN_WIZARD_ANCHOR = ("blonde hair, wizard hat, red dress, purple cape, "
                         "blue footwear")
    PIN_WIZARD_CAPTION = f"girl, {PIN_WIZARD_ANCHOR}, from side, facing right, "
    PIN_GIRL_HEAD = PIN_HEAD.replace("1boy", "1girl")
    # The girl's base caption is the brief's, with EXACTLY three changes: the
    # count, the outfit tags, and the sentence's noun. Anything else the code
    # writes differently turns this red.
    PIN_WIZARD_BASE = {
        name: text.replace(PIN_HEAD, PIN_GIRL_HEAD)
                  .replace(PIN_IDENTITY, PIN_WIZARD_TAGS)
                  .replace("the same boy", "the same girl")
        for name, text in PIN_BASE.items()}
    PIN_SCOUT_PANTS, PIN_SCOUT_TUNIC = (0xC8, 0xA0, 0x64), (0x3C, 0x64, 0xC8)
    expect("wizard_girl.json is a GIRL wearing a wizard hat, a cape, no "
           "scarf, a dress and heels, with one colour per part they draw",
           (WIZARD.subject, WIZARD.garments, WIZARD.tags, WIZARD.anchor,
            WIZARD.colours),
           ("girl", Garments("wizard", True, "none", "dress", "heels"),
            PIN_WIZARD_TAGS, PIN_WIZARD_ANCHOR,
            (("skin", (0xE8, 0xB4, 0x8C)), ("hair", (0xE8, 0xC8, 0x5A)),
             ("belt", (0x5A, 0x3A, 0x1E)), ("dress", (0xC8, 0x32, 0x32)),
             ("heels", (0x1E, 0x5A, 0xF0)), ("cape", (0x8C, 0x3C, 0xC8)),
             ("hat", (0x5A, 0x28, 0xA0)))))
    expect("...and her hat is NOT her cape's purple: two garments in one RGB "
           "are one garment to the model, and the judge below would have to "
           "work around the collision to see either",
           (WIZARD.colour("hat") != WIZARD.colour("cape"),
            characters.distance_sq(WIZARD.colour("hat"),
                                   WIZARD.colour("cape")) >= 60 * 60,
            sorted(shades_of(WIZARD.colour("hat"))
                   & shades_of(WIZARD.colour("cape")))),
           (True, True, []))

    def boy_words(text):
        """Every word of any subject but hers, anywhere in a built body."""
        return sorted(set(re.findall(r"[a-z]+", text.lower()))
                      & {"boy", "boys", "male", "man", "men"})

    for name in ("walk", "run", "jump"):
        recipe = recipes.get_recipe(name, "wizard_girl")
        req = recipes.make_request(name, "generate", SEED,
                                   character="wizard_girl")
        body_text = json.dumps(request.build_body(req))
        expect(f"{name} for wizard_girl: 1girl heads the base caption, its "
               f"sentence says 'the same girl', every character caption opens "
               f"'girl,', and no boy word anywhere in the body",
               (recipe.base_caption == PIN_WIZARD_BASE[name],
                req.base_caption == recipe.base_caption,
                [f.caption for f in req.frames]
                == [PIN_WIZARD_CAPTION + words for words in PIN_POSES[name]],
                "the same girl" in recipe.base_caption,
                boy_words(body_text)),
               (True, True, True, True, []))

    SKIRT_MIN_HEM = 9
    """A drawn A-line hem is at least this wide, against a 6 px bodice:
    measured 10-12 over her fifteen figures."""
    SKIRT_MAX_HEM = 14
    """...and AT MOST this wide. The other half: `>= SKIRT_MIN_HEM` alone
    leaves SKIRT_HEM_W free to grow without bound, and 12 -> 18 measured
    11-18 px hems with the suite green."""
    SKIRT_MAX_WAIST = 8
    """The skirt's TOP row -- the first below the belt -- is at most this
    wide, so the hem being >= 9 means the skirt actually flares. MEASURED
    1-7 on her fifteen figures; SKIRT_TOP_W 6 -> 12 (a straight tube, no
    A-line at all) measured up to 12 and was green."""
    HEEL_MAX_PX = 20
    """A heel draws at most this many shoe pixels in a cell. MEASURED: heels
    10-16, and the same figures in boots 20-37, because a boot adds a shaft
    up the shin and a boot-coloured ankle."""
    HEEL_MIN_PX = 8
    """...and at least this many. MEASURED 9-16; HEEL_DROP 1 -> 0 (the sole
    alone, no post and no toe) measured 5-9 and HEEL_SOLE_W 4 -> 2 measured
    6-9, both with the suite green."""
    CAPE_MIN_STANDOFF = 3
    """The cape's leftmost pixel sits at least this far behind the dress's.
    MEASURED 4-11; merely `behind the dress` left CAPE_BACK, CAPE_LEN and
    CAPE_MAX_ANGLE free -- zeroing CAPE_BACK measured 2 and was green."""
    CAPE_MIN_FLARE = 3
    """The cape's widest row is at least this much wider than its top row: it
    is a FLARE, not a band. MEASURED 4-9; CAPE_HEM_W 9 -> 6 (top and hem
    equal, no flare) measured 2 and was green."""

    def components(points):
        """4-connected pieces `points` falls into."""
        left, pieces = set(points), 0
        while left:
            stack, pieces = [left.pop()], pieces + 1
            while stack:
                x, y = stack.pop()
                for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if q in left:
                        left.discard(q)
                        stack.append(q)
        return pieces

    def outfit_problems(src, layout, identity):
        """Every way a drawn strip fails to wear identity's outfit: nothing
        drawn, a hat that is not above the head, a missing dress, a skirt
        that is not wider than the bodice or not narrower at the waist or
        wider than any hem should be, a cape that is not behind the dress, is
        not far enough behind it, does not flare, or has been cut into
        pieces, a heel that is not at the foot, a shoe with a boot's bulk or
        with no heel's worth of pixels. A part this identity does not wear
        simply has no pixels, so the same function judges a girl who took her
        hat off.

        EVERY TEST IS BOUNDED FROM BOTH SIDES. Each shape was drawn from a
        constant that had only a floor or only a ceiling, and ten mutations
        of those constants -- a brim narrower than the head, a heel with no
        notch, a skirt with no A-line, a cape that stops flaring -- were
        measured leaving this suite green at 790 assertions (CLAUDE.md law 5:
        one half of an invariant is the dominant failure shape). The
        mutations below prove each new half can fail.
        """
        problems = []
        for i, cell in enumerate(layout.cells):
            sx0, sy0, sx1, sy1 = layout.rect_src(i)
            crop = src.crop((sx0, sy0, sx1, sy1))
            where = {}
            for y in range(crop.height):
                for x in range(crop.width):
                    where.setdefault(crop.getpixel((x, y)), []).append((x, y))

            def points(part):
                try:
                    rgb = identity.colour(part)
                except KeyError:
                    return []
                return [p for drawn_rgb in shades_of(rgb)
                        for p in where.get(drawn_rgb, ())]
            drawn = [p for rgb, ps in where.items() if rgb != BACKGROUND_RGB
                     for p in ps]
            body = points("skin") + points("hair")
            if not drawn or not body:
                problems.append(f"cell {i}: nothing drawn")
                continue
            head_top = min(y for _x, y in body)
            floor = max(y for _x, y in drawn)
            if not [p for p in points("hat") if p[1] < head_top]:
                problems.append(f"cell {i}: no hat above the head")
            if not points("dress"):
                problems.append(f"cell {i}: no dress")
            else:
                rows = {}
                for x, y in points("dress"):
                    rows.setdefault(y, []).append(x)
                hem = max(max(xs) - min(xs) + 1 for xs in rows.values())
                if hem < SKIRT_MIN_HEM:
                    problems.append(f"cell {i}: the skirt is {hem} px wide, "
                                    f"no wider than the bodice")
                elif hem > SKIRT_MAX_HEM:
                    problems.append(f"cell {i}: the skirt is {hem} px wide, "
                                    f"wider than any hem")
                # The A-line, bounded at the WAIST as well as the hem: the
                # skirt's first row below the belt is the waist, and a skirt
                # as wide there as at the hem is a tube.
                belt = points("belt")
                waist_rows = sorted(y for y in rows if not belt
                                    or y > max(b[1] for b in belt))
                if waist_rows:
                    xs = rows[waist_rows[0]]
                    waist = max(xs) - min(xs) + 1
                    if waist > SKIRT_MAX_WAIST:
                        problems.append(f"cell {i}: the skirt is {waist} px "
                                        f"wide at the waist, no narrower "
                                        f"than its hem")
                # The cape is judged over the WHOLE CELL: her hat carries its
                # own colour, so nothing else purple can stand in for it.
                cape = points("cape")
                dress = points("dress")
                if not cape:
                    problems.append(f"cell {i}: no cape beside the dress")
                else:
                    standoff = (min(x for x, _y in dress)
                                - min(x for x, _y in cape))
                    if standoff < CAPE_MIN_STANDOFF:
                        problems.append(f"cell {i}: the cape stands {standoff}"
                                        f" px behind the dress, not enough to"
                                        f" read as a second garment")
                    cape_rows = {}
                    for x, y in cape:
                        cape_rows.setdefault(y, []).append(x)
                    widths = {y: max(xs) - min(xs) + 1
                              for y, xs in cape_rows.items()}
                    flare = max(widths.values()) - widths[min(widths)]
                    if flare < CAPE_MIN_FLARE:
                        problems.append(f"cell {i}: the cape widens by "
                                        f"{flare} px from its shoulder to "
                                        f"its hem; it does not flare")
                    pieces = components(cape)
                    if pieces > 1:
                        problems.append(f"cell {i}: the cape is cut into "
                                        f"{pieces} pieces")
            shoe = points("heels")
            if not [p for p in shoe if p[1] >= floor - 2]:
                problems.append(f"cell {i}: no heel at the foot")
            elif len(shoe) > HEEL_MAX_PX:
                problems.append(f"cell {i}: the shoe has a boot's bulk "
                                f"({len(shoe)} px)")
            elif len(shoe) < HEEL_MIN_PX:
                problems.append(f"cell {i}: the shoe is {len(shoe)} px, too "
                                f"little for a sole, a post and a toe")
        return problems

    for name in ("walk", "run", "jump"):
        recipe = recipes.get_recipe(name, "wizard_girl")
        layout = recipe.layout
        # The image img2img would SEND, not one drawn here: make_request is
        # the route that has to carry her garments to the mannequin.
        sent = recipes.make_request(name, "img2img", SEED,
                                    character="wizard_girl").image_png
        image = opened(sent).convert("RGB")
        source = image.resize((layout.src_w, layout.src_h),
                              Image.Resampling.NEAREST)
        palette = {rgb for _n, rgb in source.getcolors(1 << 20)}
        allowed = {BACKGROUND_RGB} | shades_of(OUTLINE_RGB)
        for part, _rgb in WIZARD.colours:
            allowed |= shades_of(WIZARD.colour(part))
        outside = source.copy()
        for cell in layout.cells:
            sx0, sy0, sx1, sy1 = [v // layout.k for v in cell.rect_canvas]
            outside.paste(BACKGROUND_RGB, (sx0, sy0, sx1, sy1))
        expect(f"{name} for wizard_girl: the sent init wears the hat above "
               f"the head, an A-line skirt, a cape that stands off, flares "
               f"and is in one piece, and a heel at each foot, in her "
               f"colours only, with nothing outside a cell",
               (outfit_problems(source, layout, WIZARD),
                sorted(palette - allowed),
                sorted({PIN_SCOUT_PANTS, PIN_SCOUT_TUNIC} & palette),
                outside.getcolors(1 << 20)),
               ([], [], [], [(layout.src_w * layout.src_h, BACKGROUND_RGB)]))

    # -- the OTHER HALF of every garment constant: mutate one, go red -------
    # Each row below was measured leaving the suite green before these
    # assertions existed. `drawn_problems` redraws her walk with one constant
    # changed and asks the SAME judge, so a row that stops firing is a
    # judge that stopped looking, not a constant that stopped mattering.
    def drawn_problems(**changes):
        """Every problem the judge reports over ALL THREE strips, stripped of
        cell numbers and measurements. All three, because a pose the walk
        does not strike is a constant the walk cannot test: the walk leans 0,
        so CAPE_MAX_ANGLE never binds there and clamping it to 12 changed not
        one walk pixel."""
        found = set()
        for recipe_name in ("walk", "run", "jump"):
            shape = recipes.get_recipe(recipe_name, "wizard_girl")
            with contextlib.ExitStack() as stack:
                for name_, value in changes.items():
                    stack.enter_context(patched(mannequin, name_, value))
                png, _c = mannequin.render_init(
                    shape.layout, shape.poses, WIZARD.as_dict(),
                    garments=WIZARD.garments)
            drawn = opened(png).convert("RGB").resize(
                (shape.layout.src_w, shape.layout.src_h),
                Image.Resampling.NEAREST)
            found |= {p.split(": ", 1)[1].split(" (")[0].split(" px")[0]
                      for p in outfit_problems(drawn, shape.layout, WIZARD)}
        return sorted(found)

    for label, changes, wanted in (
            ("SKIRT_TOP_W 6 -> 12 (a tube, no A-line)",
             {"SKIRT_TOP_W": 12}, "the skirt is"),
            ("SKIRT_HEM_W 12 -> 18 (a hem wider than the figure)",
             {"SKIRT_HEM_W": 18}, "the skirt is"),
            ("CAPE_BACK 2.0 -> 0.0 (the cape hangs on the torso)",
             {"CAPE_BACK": 0.0}, "the cape stands"),
            ("CAPE_HEM_W 9 -> 6 (a band, not a flare)",
             {"CAPE_HEM_W": 6}, "the cape widens by"),
            ("CAPE_MAX_ANGLE 38 -> 12 (the cape hides behind the figure)",
             {"CAPE_MAX_ANGLE": 12.0}, "the cape"),
            ("HEEL_DROP 1 -> 0 (a sole with no post and no toe)",
             {"HEEL_DROP": 0}, "the shoe is"),
            ("HEEL_SOLE_W 4 -> 2 (half a sole)",
             {"HEEL_SOLE_W": 2}, "the shoe is")):
        found = drawn_problems(**changes)
        expect_true(f"the judge goes red on {label}",
                    found and any(p.startswith(wanted) for p in found))
    expect("...and reports nothing at all on the shipped constants, so those "
           "seven rows are the mutation and not the judge",
           drawn_problems(), [])

    # The hat's brim and the heel's notch are the same geometry in every
    # frame -- only what covers them changes -- so they are asserted on the
    # drawing code itself, where an arm cannot hide half the answer.
    brim_px = {}
    mannequin._hat(brim_px, 0, 0, (0x5A, 0x28, 0xA0))   # an 8x8 head at (0, 0)
    brim_rows = {}
    for (x, y), _v in brim_px.items():
        brim_rows.setdefault(y, []).append(x)
    widest = max(brim_rows, key=lambda y: len(brim_rows[y]))
    expect("the wizard hat's brim is WIDER THAN THE HEAD ON BOTH SIDES and "
           "sits on the head, not above it: the front edge overhangs the "
           "face, which is the half of the shape the model has to draw",
           (len(brim_rows[widest]) >= mannequin.HEAD + 2,
            widest > 0, widest <= mannequin.HAT_BRIM_ROW,
            0 - min(brim_rows[widest]), max(brim_rows[widest]) - 7),
           (True, True, True, 2, 1))
    for label, changes, wanted in (
            ("HAT_BRIM_W 11 -> 8 (a cone with no brim at all)",
             {"HAT_BRIM_W": 8}, "width"),
            ("HAT_BRIM_ROW 1 -> 0 (the brim above the head, not on it)",
             {"HAT_BRIM_ROW": 0}, "row"),
            ("HAT_BRIM_BACK 0.0 -> 1.0 (the front edge flush with the face)",
             {"HAT_BRIM_BACK": 1.0}, "front"),
            ("HAT_BRIM_BACK 0.0 -> 4.0 (a rear flange, no brim at the face)",
             {"HAT_BRIM_BACK": 4.0}, "front")):
        with contextlib.ExitStack() as stack:
            for name_, value in changes.items():
                stack.enter_context(patched(mannequin, name_, value))
            mutant = {}
            mannequin._hat(mutant, 0, 0, (0x5A, 0x28, 0xA0))
        rows_ = {}
        for (x, y), _v in mutant.items():
            rows_.setdefault(y, []).append(x)
        wy = max(rows_, key=lambda y: len(rows_[y]))
        broken = {"width": len(rows_[wy]) < mannequin.HEAD + 2,
                  "row": not 0 < wy <= mannequin.HAT_BRIM_ROW,
                  "front": max(rows_[wy]) - 7 < 1}
        expect_true(f"...and that is false for {label}", broken[wanted])

    heel = [[mannequin._in_heel(a + 0.5, f + 0.5, 0.0)
             for f in range(mannequin.HEEL_SOLE_W)]
            for a in range(mannequin.HEEL_SOLE_H + mannequin.HEEL_DROP)]
    expect("the high heel is a SOLE WITH A NOTCH UNDER IT -- a solid sole "
           "row, then a row that is a post at the back and a toe at the "
           "front with the arch open between them; the notch is the whole "
           "read, and a solid block is a boot",
           (len(heel) >= 2, heel[0], all(heel[0]),
            heel[-1][0], heel[-1][-1], False in heel[-1]),
           (True, [True] * 4, True, True, True, True))
    for label, changes in (
            ("HEEL_DROP 1 -> 0 (the sole alone, nothing under it)",
             {"HEEL_DROP": 0}),
            ("HEEL_SOLE_W 4 -> 2 (post and toe meet, the arch closes)",
             {"HEEL_SOLE_W": 2})):
        with contextlib.ExitStack() as stack:
            for name_, value in changes.items():
                stack.enter_context(patched(mannequin, name_, value))
            mutant_heel = [[mannequin._in_heel(a + 0.5, f + 0.5, 0.0)
                            for f in range(mannequin.HEEL_SOLE_W)]
                           for a in range(mannequin.HEEL_SOLE_H
                                          + mannequin.HEEL_DROP)]
        expect_true(f"...and that is false for {label}",
                    len(mutant_heel) < 2 or False not in mutant_heel[-1])

    def block_heel(along, fwd, heel_):
        """`_in_heel` with its post/toe branch replaced by the full sole: a
        solid two-row block, the shape the notch exists not to be."""
        return (0.0 <= along < mannequin.HEEL_SOLE_H + mannequin.HEEL_DROP
                and heel_ <= fwd < heel_ + mannequin.HEEL_SOLE_W)

    with patched(mannequin, "_in_heel", block_heel):
        blocked = [[mannequin._in_heel(a + 0.5, f + 0.5, 0.0)
                    for f in range(mannequin.HEEL_SOLE_W)]
                   for a in range(mannequin.HEEL_SOLE_H
                                  + mannequin.HEEL_DROP)]
    expect("...and false when the post/toe branch is the whole sole, which "
           "is the mutation the notch assertion exists to catch",
           (len(blocked), False in blocked[-1]), (2, False))

    # -- the cape's own line, and the root that moves with the lean --------
    def cape_pixels(pose, identity=None):
        who = identity or WIZARD
        px = mannequin._figure(pose, who.as_dict(), who.garments)
        base = who.colour("cape")
        unlined = 0
        for (x, y), (rgb, tag) in px.items():
            if tag != "cape" or rgb != base:
                continue
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                other = px.get(q)
                if other is not None and other[1] != "cape":
                    unlined += 1
                    break
        return ([rgb for rgb, tag in px.values() if tag == "cape"], unlined)

    lined = {name: [cape_pixels(p) for p in
                    recipes.get_recipe(name, "wizard_girl").poses]
             for name in ("walk", "run", "jump")}
    expect("THE CAPE CARRIES ITS OWN LINE. It is drawn first, so every other "
           "part lies over it: in all sixteen frames no cape pixel at the "
           "base colour touches another part, and every frame draws a "
           "darkened cape edge. Without it the cape's hem ends INSIDE the "
           "skirt -- measured cape row 2-4 against skirt row 6-8 in every "
           "frame -- with no outline and no inner line between purple and "
           "red, so the two garments read as one two-tone flare",
           (sorted({u for rows in lined.values() for _px, u in rows}),
            min(sum(1 for rgb in px if rgb != WIZARD.colour("cape"))
                for rows in lined.values() for px, _u in rows) >= 8),
           ([0], True))
    with patched(mannequin, "INNER_SHADE", 1.0):
        flat = [cape_pixels(p)[1] for p in WALK.poses]
    expect("...and with nothing to darken it with, the same measurement "
           "finds bare cape pixels against the dress in every walk frame, so "
           "that assertion can fail",
           (all(u > 0 for u in flat), len(flat)), (True, 5))

    UPRIGHT = Pose(0, 0, 0, 0, 0, 0, 0, 0, lean=0)
    CROUCH = dataclasses.replace(UPRIGHT, lean=35)
    LEANT_BACK = dataclasses.replace(UPRIGHT, lean=-5)
    with patched(mannequin, "CAPE_LEAN_BACK", 0.0):
        rooted = {p.lean: len(cape_pixels(p)[0])
                  for p in (UPRIGHT, CROUCH, LEANT_BACK)}
    swung = {p.lean: len(cape_pixels(p)[0])
             for p in (UPRIGHT, CROUCH, LEANT_BACK)}
    expect("THE CAPE'S ROOT MOVES BACK WITH THE LEAN, not only its angle: in "
           "a deep crouch the swing is already clamped at CAPE_MAX_ANGLE, so "
           "rotating it further cannot clear the near arm's backswing and "
           "only the root can. A crouch therefore draws MORE cape than the "
           "same crouch with CAPE_LEAN_BACK zeroed, while an upright or "
           "backward-leaning figure draws exactly the same (max(0, lean))",
           (swung[35] > rooted[35], swung[0] == rooted[0],
            swung[-5] == rooted[-5]), (True, True, True))
    BARE = dataclasses.replace(
        WIZARD, garments=Garments("none", False, "none", "dress", "boots"),
        colours=tuple((part, rgb) for part, rgb in WIZARD.colours
                      if part not in ("hat", "cape", "heels"))
        + (("boots", (0x1E, 0x5A, 0xF0)),))
    bare_png, _bare_centers = mannequin.render_init(
        L5, WALK.poses, BARE.as_dict(), garments=BARE.garments)
    bare_image = opened(bare_png).convert("RGB")
    bare_colours = {rgb for _n, rgb in bare_image.getcolors(1 << 20)}
    expect("...and the same girl with the hat and the cape taken off and her "
           "blue in boots draws no purple at all, and the SAME judge then "
           "reports the missing hat, the missing cape and no heel in every "
           "cell -- so those assertions can fail",
           (sorted(bare_colours & shades_of((0x8C, 0x3C, 0xC8))),
            outfit_problems(bare_image.resize((L5.src_w, L5.src_h),
                                              Image.Resampling.NEAREST),
                            L5, BARE)),
           ([], [problem for i in range(5)
                 for problem in (f"cell {i}: no hat above the head",
                                 f"cell {i}: no cape beside the dress",
                                 f"cell {i}: no heel at the foot")]))

    # -- the dress's SHORT SLEEVE and its wrist, in the drawing itself -----
    # Judged on BARE, which wears no cape: the cape's own inner line would
    # otherwise put a darkened shade into the arm and blur the exact sets.
    def arm_values(identity, tag, pose=None):
        px = mannequin._figure(pose or WALK.poses[0], identity.as_dict(),
                               identity.garments)
        return {rgb for rgb, t in px.values() if t == tag}

    BARE_SKIN, BARE_DRESS = BARE.colour("skin"), BARE.colour("dress")
    far = lambda rgb: mannequin._shade(rgb, mannequin.FAR_SHADE)
    expect("a DRESSED figure's arm is three values: the dress to the elbow, "
           "BARE SKIN past it, and an OUTLINE_RGB wrist before the hand -- "
           "the far arm the same, in far shades. Without the wrist the "
           "forearm and the hand are one skin value, in the same value as "
           "the bare far leg: a blunt plank that reads as a held object",
           (arm_values(BARE, "near_arm"),
            arm_values(BARE, "far_arm"),
            OUTLINE_RGB in arm_values(BARE, "near_arm")),
           ({BARE_DRESS, BARE_SKIN, OUTLINE_RGB},
            {far(BARE_DRESS), far(BARE_SKIN),
             OUTLINE_RGB},
            True))
    expect("...and a SLEEVED figure's arm is two, with no wrist at all: the "
           "tunic's own colour already breaks it, so the shipped scout draws "
           "exactly what it always drew",
           (arm_values(SCOUT, "near_arm"), arm_values(SCOUT, "far_arm")),
           ({SCOUT.colour("tunic"), SCOUT.colour("skin")},
            {far(SCOUT.colour("tunic")),
             far(SCOUT.colour("skin"))}))

    def skin_px(identity, tag, shade=lambda rgb: rgb):
        """Per walk pose, the pixels of `tag` drawn in `identity`'s skin."""
        wanted = shade(identity.colour("skin"))
        return [sum(1 for rgb, t in mannequin._figure(
            pose, identity.as_dict(), identity.garments).values()
            if t == tag and rgb == wanted) for pose in WALK.poses]

    # COUNTED, not merely named: `lower = sleeve` -- the dress's short sleeve
    # deleted -- leaves the SET of arm colours untouched, because the hand is
    # skin either way. A dressed arm has to draw skin BEYOND its hand.
    expect("the dress's sleeve stops at the ELBOW: a dressed arm draws more "
           "skin than its hand alone, strictly more than the same arm in a "
           "tunic, which draws the hand and nothing else -- and the two "
           "figures share one skin colour, so that is a fair count",
           (min(skin_px(BARE, "near_arm")) > max(skin_px(SCOUT, "near_arm")),
            max(skin_px(BARE, "far_arm", far))
            > max(skin_px(SCOUT, "far_arm", far)),
            BARE.colour("skin") == SCOUT.colour("skin")),
           (True, True, True))
    with patched(mannequin, "WRIST_PX", 0):
        no_wrist = (arm_values(BARE, "near_arm"), arm_values(BARE, "far_arm"))
    expect("...and with WRIST_PX 0 the dressed arm collapses to two values "
           "and the far arm's are exactly the far leg's, so this assertion "
           "can fail",
           (no_wrist[0], no_wrist[1] == {far(BARE_DRESS),
                                         far(BARE_SKIN)},
            far(BARE_SKIN) in arm_values(BARE, "far_leg")),
           ({BARE_DRESS, BARE_SKIN}, True, True))

    # -- what a mannequin NAME means for a figure wearing something --------
    # `params_sha256` is a hash, and a hash tells nobody what left the
    # document: dropping _GARMENT_SKELETON_NAMES, dropping the "garments"
    # key, and bumping GARMENT_DRAW_VERSION were each measured moving (or
    # failing to move) a garmented name with the suite green. These assert
    # the DOCUMENT and the RELATION, not a literal, so tuning a constant
    # does not make them red.
    wizard_doc = mannequin.params_doc(L5, WALK.poses, WIZARD.as_dict(),
                                      garments=WIZARD.garments)
    scout_doc = mannequin.params_doc(L5, WALK.poses, SCOUT.as_dict())
    expect("a garmented mannequin's name is taken over its GARMENTS and "
           "every garment constant; the default outfit's over neither, so "
           "the shipped scout's name cannot move when a hat constant does",
           (sorted(set(mannequin._GARMENT_SKELETON_NAMES)
                   - set(wizard_doc["skeleton"])),
            wizard_doc.get("garments"),
            sorted(set(mannequin._GARMENT_SKELETON_NAMES)
                   & set(scout_doc["skeleton"])),
            "garments" in scout_doc,
            "GARMENT_DRAW_VERSION" in wizard_doc["skeleton"]),
           ([], dict(WIZARD.garments._asdict()), [], False, True))
    for constant, value in (("GARMENT_DRAW_VERSION",
                             mannequin.GARMENT_DRAW_VERSION + 1),
                            ("HAT_BRIM_W", mannequin.HAT_BRIM_W + 1),
                            ("CAPE_LEAN_BACK", mannequin.CAPE_LEAN_BACK + 1),
                            ("WRIST_PX", mannequin.WRIST_PX + 1)):
        with patched(mannequin, constant, value):
            moved = mannequin.params_sha256(L5, WALK.poses, WIZARD.as_dict(),
                                            garments=WIZARD.garments)
            still = mannequin.params_sha256(L5, WALK.poses, SCOUT.as_dict())
        expect(f"...so changing {constant} renames HER mannequin and leaves "
               f"the default outfit's alone",
               (moved != mannequin.params_sha256(L5, WALK.poses,
                                                 WIZARD.as_dict(),
                                                 garments=WIZARD.garments),
                still == PIN_SCOUT_PARAMS["walk"]), (True, True))

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

    def drift_ack(ledger_id, previous, observed, high, low, by="phil",
                  attribution="theirs", checked="the usage page"):
        """One signature row, as the signing commands write it: the two
        balances, the negative delta, the two row ids the boundary sits
        between, who signed it, WHOSE he says the money was and what he
        checked. Nothing else is filled."""
        row = dict.fromkeys(LEDGER_FIELDS)
        row.update(ledger_id=ledger_id, kind="drift",
                   utc_time="2026-09-17T14:00:00.000000Z",
                   account_before={"sum": high}, account_after={"sum": low},
                   delta=low - high, drift_previous_row=previous,
                   drift_observed_row=observed, drift_acknowledged_by=by,
                   drift_attribution=attribution, drift_checked=checked)
        return row

    def acknowledge(state, by="check_nai"):
        """Sign the ledger's oldest open boundary THROUGH THE CLI, so no
        check ever grows a second copy of the rule -- the right verb for
        the boundary's own class. Returns (exit code, what it printed). It
        does not delete LOCK -- nothing does but the author."""
        gap = guard.open_boundary(state.rows())
        argv = (["resolve-boundary", "--attribute", "theirs"] if gap.ambiguous
                else ["acknowledge-drift"]) + [
            "--anlas", str(-gap.delta), "--by", by,
            "--checked", "the provider usage page"]
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed),                 contextlib.redirect_stderr(printed):
            code = cli.main(argv, transport=None, state=state)
        return code, printed.getvalue()

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
    refused("a live balance BELOW the last ledger row is refused as an "
            "AMBIGUOUS boundary -- the last row SENT a request of ours, so a "
            "late debit for it looks exactly like this", 9,
            "AMBIGUOUS BOUNDARY -- this tool CANNOT say whose spend this "
            "was: the balance fell 1000 -> 998 (2 Anlas)", BODY_GEN,
            state=CHAINED, account=dataclasses.replace(ACCOUNT, fixed=998))
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
    late_failed = [v for v in guard.evaluate(
        BODY_I2I, dataclasses.replace(ACCOUNT, fixed=998), (PROOF_I2I,), LATE,
        url=GENERATE_URL) if v.ok is not True]
    expect("a debit landing BETWEEN the probe and the next row REFUTES the "
           "proof FOR GOOD (1) and refuses the chain (9) as an AMBIGUOUS "
           "boundary: the probe's own request went out, so risk R4's late "
           "debit and a friend's spend are byte-identical there",
           ([v.condition for v in late_failed],
            [v.ok for v in late_failed],
            ["REFUTED" in v.message and "risk R4" in v.message
             for v in late_failed if v.condition == 1],
            # the fall is already written down and the read just taken is
            # level with the chain, so the note says THAT before it describes
            # the boundary: the author is never pointed at the wrong event
            [v.message.startswith("NOT the balance read just taken")
             and "AMBIGUOUS BOUNDARY" in v.message
             for v in late_failed if v.condition == 9]),
           ([1, 9], [False, False], [True], [True]))
    LATE_ACKED = scratch_state("late_debit_acked")
    LATE_ACKED.write_row(probe_row(PROOF_I2I))
    LATE_ACKED.write_row(ledger_row(998, ledger_id="after-the-probe"))
    LATE_ACKED.write_row(drift_ack("ack-late", PROOF_I2I.ledger_id,
                                   "after-the-probe", 1000, 998))
    refused("...and SIGNING that boundary does not bring it back: the chain "
            "is re-baselined so work can go on, and img2img stays refused. "
            "THE MONEY ESCAPE: without this, one typed figure re-arms the "
            "action whose cost is the open question and OURS still reads 0",
            1, "REFUTED", BODY_I2I, proofs=(PROOF_I2I,), state=LATE_ACKED,
            account=dataclasses.replace(ACCOUNT, fixed=998))
    expect("...and the signature really did re-baseline the chain: condition "
           "9 passes over the same ledger, so only condition 1 refuses",
           [(v.condition, v.ok) for v in guard.evaluate(
               BODY_I2I, dataclasses.replace(ACCOUNT, fixed=998),
               (PROOF_I2I,), LATE_ACKED, url=GENERATE_URL)
            if v.condition in (1, 9)], [(1, False), (9, True)])
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
    LATE_AFTER_CALL = (probe_row(PROOF_I2I), pair_row(1000, 1000, "i2i-clean"),
                       pair_row(995, 995, "chain-charged", action="generate",
                                kind="refused", locked=True))
    after_call_failed = [v for v in guard.evaluate(
        BODY_I2I, dataclasses.replace(ACCOUNT, fixed=995), (PROOF_I2I,),
        ledger_of("later_late_debit", *LATE_AFTER_CALL), url=GENERATE_URL)
        if v.ok is not True]
    expect("...and a debit landing AFTER a clean later img2img call refutes "
           "it too: that call went out, so the fall in the read that follows "
           "it is R4's own shape and cannot be told from somebody else's",
           ([v.condition for v in after_call_failed],
            [v.ok for v in after_call_failed],
            ["REFUTED" in v.message for v in after_call_failed]),
           ([1, 9], [False, False], [True, False]))
    refused("...and signing exactly that boundary still does not let it "
            "through: a signature re-baselines the CHAIN, never a proof",
            1, "REFUTED", BODY_I2I, proofs=(PROOF_I2I,), state=ledger_of(
                "later_late_debit_acked", *LATE_AFTER_CALL,
                drift_ack("ack-after", "i2i-clean", "chain-charged",
                          1000, 995)),
            account=dataclasses.replace(ACCOUNT, fixed=995))
    expect("...and THIS read, below the last img2img call's after, refutes it "
           "for good and says R4 in so many words",
           (lambda r: (r[0], "risk R4" in r[1], "REFUTED" in r[1]))(
               guard.proof_standing(PROOF_I2I,
                                    [probe_row(PROOF_I2I),
                                     pair_row(1000, 1000, "i2i-clean")], 995)),
           (False, True, True))
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
    expect("a debit landing AFTER a clean production img2img is refused (9) "
           "as an AMBIGUOUS boundary, and LOCK names the proof it refutes "
           "FOR GOOD -- it never says 'img2img is charged', because nothing "
           "measured that, and never calls the drop somebody else's",
           (getattr(exc, "condition", None), "AMBIGUOUS BOUNDARY" in lock_text,
            "REFUTES its proof" in lock_text,
            "img2img is charged" in lock_text,
            "EXTERNAL DRIFT" in lock_text),
           (9, True, True, False, False))
    if seq.locked():
        os.remove(seq.lock_path)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...LOCK deleted by hand: img2img is STILL refused and sends "
           "nothing -- on the UNSIGNED boundary (9)",
           (getattr(exc, "condition", None), "AMBIGUOUS BOUNDARY" in str(exc),
            pattern), (9, True, [GET]))
    ack_code, _ack_out = acknowledge(seq)
    expect("...signing it leaves LOCK exactly where it was: only the author "
           "removes that", (ack_code, seq.locked()), (0, True))
    os.remove(seq.lock_path)   # the author, after checking the account
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and img2img is STILL refused, now on its refuted proof (1), "
           "with NOTHING sent: the signature freed the chain so the work can "
           "go on, and left the action whose cost is in question locked",
           (getattr(exc, "condition", None), "REFUTED" in str(exc), pattern),
           (1, True, [GET]))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...while generate, which never needed a proof, sends again: "
           "signing a boundary unblocks the work, never the open question",
           (exc, pattern), (None, [GET, POST, GET]))
    seq = proven_pair("late_after_generate")
    scripted(REQ_GEN, [sub(1000), zipped(), sub(1000)], state=seq)
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995)], state=seq)
    expect("but a debit landing after a GENERATE call names no proof in LOCK",
           (getattr(exc, "condition", None), "REFUTES its proof"
            in lock_text_of(seq)), (9, False))
    if seq.locked():
        os.remove(seq.lock_path)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and img2img is refused only on the unsigned boundary, never "
           "on its proof: the fall sits behind a GENERATE row, so nothing "
           "about the img2img probe moved",
           (getattr(exc, "condition", None), "REFUTED" in str(exc)),
           (9, False))
    acknowledge(seq)
    if seq.locked():
        os.remove(seq.lock_path)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and once that boundary is signed img2img is sent: the proof "
           "stood the whole time", (exc, pattern), (None, [GET, POST, GET]))
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

    layouts = [(name, r.layout, r.poses, COLOURS, DEFAULT_GARMENTS)
               for name, r in sorted(recipes.RECIPES.items())]
    layouts += [(f"wizard_girl {name}", r.layout, r.poses,
                 r.identity.as_dict(), r.identity.garments)
                for name, r in ((n, recipes.get_recipe(n, "wizard_girl"))
                                for n in ("walk", "run", "jump"))]
    layouts += [(f"strip({n},{w},{h})", mannequin.strip(n, w, h),
                 mannequin.POSES["walk"][:n], COLOURS, DEFAULT_GARMENTS)
                for n, w, h in ((5, 1216, 832), (3, 1024, 1024),
                                (4, 1024, 1024), (2, 640, 512))]
    for name, layout, poses, colours, garments in layouts:
        try:
            png, centers = mannequin.render_init(layout, poses, colours,
                                                 garments=garments)
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
    expect("R4 via the CLI: a debit landing BETWEEN the probe and the next "
           "read is an AMBIGUOUS boundary -- refused, and LOCK names the "
           "proof it refutes FOR GOOD rather than calling the drop external",
           (code, [p.action for p in r4.proofs()],
            "AMBIGUOUS BOUNDARY" in lock_text,
            "REFUTES its proof" in lock_text,
            "EXTERNAL DRIFT" in lock_text),
           (2, ["img2img"], True, True, False))
    if r4.locked():
        os.remove(r4.lock_path)   # the author, after checking the account
    recorder = tp.RecordingTransport([sub(998), zipped(), sub(998)])
    code, out, err = cli_call(["run", "walk", "--action", "img2img", "--seed",
                               str(SEED)], recorder, r4)
    expect("...LOCK deleted by hand: production img2img is STILL refused and "
           "sends nothing -- on the unsigned boundary AND on the refutation",
           (code, "AMBIGUOUS BOUNDARY" in err, "REFUTED" in err,
            [c.method for c in recorder.calls]), (2, True, False, ["GET"]))
    ack_code, ack_out = acknowledge(r4)
    if r4.locked():
        os.remove(r4.lock_path)
    recorder = tp.RecordingTransport([sub(998), zipped(), sub(998)])
    code, out, err = cli_call(["run", "walk", "--action", "img2img", "--seed",
                               str(SEED)], recorder, r4)
    expect("...and once the boundary is SIGNED the books say so on their own "
           "lines -- and img2img still sends NOTHING: the signature cleared "
           "the chain, not the proof, and the command said which proof "
           "stayed refuted while it wrote the row",
           (ack_code, "ours spent    +0 Anlas" in ack_out,
            "theirs        -2 Anlas" in ack_out,
            "REFUTED for good" in ack_out, code,
            [c.method for c in recorder.calls]),
           (0, True, True, True, 2, ["GET"]))
    expect("...and THAT is the money escape closed: on the same ledger at "
           "HEAD's reading, one typed figure would have re-armed img2img "
           "while `ours` still read 0",
           ("REFUTED" in err, guard.proof_standing(
               r4.proofs()[0], r4.rows(), 998)[0]), (True, False))

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
    expect("account on a LOST ledger prints the balance, says the chain "
           "cannot be read, and REFUSES: a status line that cannot follow "
           "the money is not an exit 0",
           (code, "sum           1000" in out,
            "chain         CANNOT BE READ" in out,
            "verdict       REFUSED" in out),
           (2, True, True, True))

    # -- --character: the outfit reaches the body; an unknown one builds nothing
    code, out, err = cli_call(plan_argv + ["--character", "scout_blue_scarf"],
                              None, scratch_state("plan_blue"))
    base_lines = [line for line in out.splitlines()
                  if line.startswith("base caption")]
    frame_lines = [line for line in out.splitlines()
                   if line.startswith("frame ")]
    expect("plan --character scout_blue_scarf: exit 0, the name printed, blue "
           "scarf in the base caption and all 5 frame captions, no red scarf",
           (code, "character     scout_blue_scarf\n" in out,
            [("blue scarf" in line) for line in base_lines],
            [("blue scarf" in line) for line in frame_lines],
            "red scarf" in out), (0, True, [True], [True] * 5, False))
    code, out, err = cli_call(plan_argv + ["--character", "wizard_girl"],
                              None, scratch_state("plan_wizard"))
    base_lines = [line for line in out.splitlines()
                  if line.startswith("base caption")]
    frame_lines = [line for line in out.splitlines()
                   if line.startswith("frame ")]
    expect("plan --character wizard_girl: exit 0, the name printed, 1girl and "
           "her dress in the base caption, every frame caption opening "
           "'girl,', and no boy word in the whole plan",
           (code, "character     wizard_girl\n" in out,
            [("1girl" in line and "red dress" in line) for line in base_lines],
            [line.split(") ", 1)[-1].startswith("girl, blonde hair,")
             for line in frame_lines],
            sorted(set(re.findall(r"[a-z]+", out.lower()))
                   & {"boy", "boys", "male", "man", "men"})),
           (0, True, [True], [True] * 5, []))
    code, out, err = cli_call(plan_argv, None,
                              scratch_state("plan_default_character"))
    expect("...while plan with no --character prints scout and its red scarf",
           (code, "character     scout\n" in out, "red scarf" in out,
            "blue scarf" in out), (0, True, True, False))
    BLUE_PARAMS = mannequin.params_sha256(L5, WALK.poses, BLUE.as_dict())

    def blue_body_problems(body):
        """Every way a sent body fails to be the blue-scarf walk."""
        p = body["parameters"]
        texts = ([body["input"]] + [c["prompt"] for c in p["characterPrompts"]]
                 + [c["char_caption"] for c in
                    p["v4_prompt"]["caption"]["char_captions"]])
        problems = [f"text {i} has no blue scarf" for i, t in enumerate(texts)
                    if "blue scarf" not in t]
        if "red scarf" in json.dumps(body):
            problems.append("red scarf in the body")
        return problems
    blue_run_state = scratch_state("run_blue")
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
    code, out, err = cli_call(["run", "walk", "--action", "generate", "--seed",
                               str(SEED), "--character", "scout_blue_scarf"],
                              recorder, blue_run_state)
    blue_rows = blue_run_state.rows()
    expect("run --character scout_blue_scarf: exit 0, the name printed, the "
           "POSTed body blue throughout, the ledger row's base caption and "
           "mannequin sha256 the blue character's",
           (code, "character     scout_blue_scarf\n" in out,
            [blue_body_problems(post.body) for post in recorder.posts],
            [("blue scarf" in (row.get("base_caption") or ""),
              row.get("mannequin_sha256") == BLUE_PARAMS) for row in blue_rows]),
           (0, True, [[]], [(True, True)]))
    recorder = tp.RecordingTransport([sub(1000), (200, {},
                                                  tp.fake_zip(elsewhere)),
                                      sub(1000)])
    code, out, err = cli_call(["infill", "walk", "--cell", "2", "--from",
                               source_file, "--seed", str(SEED), "--character",
                               "scout_blue_scarf"], recorder, infill_state)
    sent_cell = (opened(base64.b64decode(recorder.posts[0].body["parameters"][
        "image"])).convert("RGB").crop(rect2) if recorder.posts else None)
    sent_colours = ({rgb for _n, rgb in sent_cell.getcolors(1 << 20)}
                    if sent_cell is not None else set())
    blue_last = infill_state.rows()[-1]
    expect("infill --character scout_blue_scarf: exit 0, the name printed, the "
           "body blue, the pasted mannequin's scarf blue and not red, the "
           "ledger row the blue character's",
           (code, "character     scout_blue_scarf\n" in out,
            [blue_body_problems(post.body) for post in recorder.posts],
            BLUE_SCARF in sent_colours, RED_SCARF in sent_colours,
            "blue scarf" in (blue_last.get("base_caption") or ""),
            blue_last.get("mannequin_sha256") == BLUE_PARAMS),
           (0, True, [[]], True, False, True, True))
    built: list[str] = []
    saved_calls = (recipes.make_request, recipes.get_recipe,
                   mannequin.render_init)

    def counting(label, real):
        def wrapper(*args, **kwargs):
            built.append(label)
            return real(*args, **kwargs)
        return wrapper
    recipes.make_request = counting("make_request", saved_calls[0])
    recipes.get_recipe = counting("get_recipe", saved_calls[1])
    mannequin.render_init = counting("render_init", saved_calls[2])
    try:
        for argv in (
                ["plan", "walk", "--action", "generate", "--seed", str(SEED)],
                ["run", "walk", "--action", "generate", "--seed", str(SEED)],
                ["render", "walk"],
                ["infill", "walk", "--cell", "2", "--from", source_file,
                 "--seed", str(SEED)],
                ["pixelize", strip_file, "--recipe", "walk"]):
            recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
            unknown_state = scratch_state("unknown_character")
            del built[:]
            code, out, err = cli_call(argv + ["--character", "scout_green"],
                                      recorder, unknown_state)
            expect(f"{argv[0]} --character scout_green: exit 2 listing the "
                   f"files; nothing built, read, sent or written",
                   (code, "unknown character 'scout_green'" in err,
                    "scout_blue_scarf.json" in err, out, list(built),
                    recorder.calls, os.path.exists(unknown_state.root)),
                   (2, True, True, "", [], [], False))
        for how, smuggled in (
                ("a relative path", os.path.join("..", "characters", "scout")),
                ("an absolute path", os.path.join(characters.CHARACTERS_DIR,
                                                  "scout")),
                ("a file name", "scout.json")):
            recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
            del built[:]
            code, out, err = cli_call(plan_argv + ["--character", smuggled],
                                      recorder, scratch_state("smuggled"))
            expect(f"plan --character given {how} to scout: exit 2 at parse, "
                   f"empty stdout, nothing built or sent",
                   (code, "unknown character" in err, out, list(built),
                    recorder.calls), (2, True, "", [], []))
        CLI_CHAR_DIR = os.path.join(SCRATCH, "cli_characters")
        os.makedirs(CLI_CHAR_DIR)
        with open(os.path.join(characters.CHARACTERS_DIR, "scout.json"),
                  "rb") as handle:
            scout_doc = json.loads(handle.read())
        refused_characters = {
            "adv_nsfw": (dict(scout_doc, tags="nsfw, " + scout_doc["tags"]),
                         "rating word"),
            "adv_view": (dict(scout_doc,
                              tags="from behind, facing viewer, facing left, "
                                   + scout_doc["tags"],
                              anchor="from behind, facing viewer, facing "
                                     "left, brown hair"), "view tag"),
            "adv_count": (dict(scout_doc,
                               tags="{2girls}, " + scout_doc["tags"],
                               anchor="{2girls}, brown hair"), "count tag"),
            "adv_ranger": (dict(scout_doc, tags=RANGER_TAGS,
                                anchor=RANGER_ANCHOR), "token budget"),
        }
        for stem, (doc, _fragment) in refused_characters.items():
            with open(os.path.join(CLI_CHAR_DIR, f"{stem}.json"), "wb") as out_:
                out_.write(json.dumps(doc).encode("ascii"))
        with open(os.path.join(CLI_CHAR_DIR, "scout.json"), "wb") as out_:
            out_.write(json.dumps(scout_doc).encode("ascii"))
        saved_dir = characters.CHARACTERS_DIR
        characters.CHARACTERS_DIR = CLI_CHAR_DIR
        try:
            for stem, (doc, fragment) in list(refused_characters.items()) + [
                    ("adv_ranger", (None, "token budget"))]:
                recipe_name = ("jump" if doc is None else "walk")
                recorder = tp.RecordingTransport([sub(1000), zipped(),
                                                  sub(1000)])
                refused_state = scratch_state("refused_character")
                del built[:]
                code, out, err = cli_call(
                    ["plan", recipe_name, "--action", "generate", "--seed",
                     str(SEED), "--character", stem], recorder, refused_state)
                expect(f"plan {recipe_name} --character {stem}: exit 1, the "
                       f"{fragment} refusal names the file; no mannequin, no "
                       f"request, no verdict, nothing sent or written",
                       (code, fragment in err, f"{stem}.json" in err,
                        "render_init" in built, "request sha256" in out,
                        "verdict" in out, recorder.calls,
                        os.path.exists(refused_state.root)),
                       (1, True, True, False, False, False, [], False))
        finally:
            characters.CHARACTERS_DIR = saved_dir
    finally:
        (recipes.make_request, recipes.get_recipe,
         mannequin.render_init) = saved_calls
    code, out, err = cli_call(plan_argv + ["--char", "scout_blue_scarf"], None,
                              scratch_state("plan_char_abbrev"))
    expect("--char is not --character: exit 2, unrecognized",
           (code, "unrecognized arguments" in err), (2, True))
    code, out, err = cli_call(["probe", "img2img", "--character",
                               "scout_blue_scarf", "--seed", str(SEED)],
                              tp.RecordingTransport([sub(1000)]),
                              scratch_state("probe_character"))
    expect("probe takes no --character: it keeps the default (exit 2, "
           "unrecognized)", (code, "unrecognized arguments" in err), (2, True))
    per_character = scratch_state("outputs_per_character")
    rendered, pixelized, named = {}, {}, {}
    for name in ("scout", "scout_blue_scarf"):
        code, out, err = cli_call(["render", "walk", "--character", name], None,
                                  per_character)
        named[name] = [f"character     {name}\n" in out]
        lines = [line.split(None, 1)[1] for line in out.splitlines()
                 if line.startswith("render ")]
        data = None
        if code == 0 and lines and os.path.isfile(lines[0]):
            with open(lines[0], "rb") as handle:
                data = handle.read()
        rendered[name] = (code, os.path.basename(lines[0]) if lines else None,
                          data)
        code, out, err = cli_call(["pixelize", strip_file, "--recipe", "walk",
                                   "--character", name], None, per_character)
        named[name].append(f"character     {name}\n" in out)
        lines = [line.split(None, 1)[1] for line in out.splitlines()
                 if line.startswith("written ")]
        pixelized[name] = (code in (0, 3), os.path.normcase(lines[0])
                           if lines else None)
    code, out, err = cli_call(["render", "walk"], None, per_character)
    expect("render per character into one state: two files, each named for "
           "its character, scout's bytes the init, blue's different; a "
           "default render lands on scout's own file (exit 0)",
           (rendered["scout"][:2], rendered["scout_blue_scarf"][:2],
            rendered["scout"][2] == INIT_PNG,
            rendered["scout_blue_scarf"][2] not in (None, INIT_PNG),
            code, "scout_walk_init.png" in out),
           ((0, "scout_walk_init.png"),
            (0, "scout_blue_scarf_walk_init.png"), True, True, 0, True))
    expect("render and pixelize each print the character they drew",
           named, {"scout": [True, True], "scout_blue_scarf": [True, True]})
    sha12 = hashlib.sha256(first_png).hexdigest()[:12]
    expect("pixelize per character: the default sprites directory is "
           "sprites/<character>/<recipe>/<sha12>/, so the two never share one",
           (pixelized["scout"], pixelized["scout_blue_scarf"]),
           ((True, os.path.normcase(os.path.join(
               per_character.root, "sprites", "scout", "walk", sha12))),
            (True, os.path.normcase(os.path.join(
                per_character.root, "sprites", "scout_blue_scarf", "walk",
                sha12)))))

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

    # =======================================================================
    print("\n8b. the money: which measurement a fall was, whose it was, and "
          "the figures a reader meets when nobody has typed anything")
    # =======================================================================
    # A balance can fall in two places and they are NOT the same measurement.
    # INSIDE one of our rows (its own after below its own before) the drop is
    # ours: LOCK, refused for good, the proof refuted for good, and nothing
    # here may soften it. BETWEEN two rows it is a BOUNDARY, and the only
    # thing the ledger knows about it is whether the earlier row SENT
    # anything: a `refused` row sent nothing, so the drop is EXTERNAL; a
    # `generation` row did, so a debit the server applied after that row's
    # own after-read (risk R4) is byte-identical to somebody else's spend,
    # and the boundary is AMBIGUOUS and stays that way until the author
    # records a hand check.
    #
    # THE FIGURES MUST TELL THE TRUTH WITH NOBODY SIGNING ANYTHING. The
    # measured ledger this pass was written against holds 1911 Anlas of
    # falls and printed `theirs +0` over them.
    #
    # Every rule below is bounded from both sides and proved red by a MUTANT
    # COPY of the module under test. `mutant` refuses to build one unless the
    # text it mutates appears EXACTLY ONCE in the shipped file, so a mutant
    # that compiles at all is the sentinel that the copy is the code under
    # test and not a stale duplicate of it.
    MUTATIONS: list[tuple[str, str]] = []

    def mutant(relpath: str, *pairs, tag: str):
        """A COPY of `relpath` with each (old, new) applied, imported alone."""
        path = os.path.join(_bootstrap.REPO_ROOT, relpath)
        with io.open(path, encoding="utf-8") as handle:
            source = handle.read()
        for old, new in pairs:
            if source.count(old) != 1:
                raise AssertionError(
                    f"mutant {tag}: {relpath} contains {old!r} "
                    f"{source.count(old)} times, wanted exactly 1 -- the copy "
                    f"is not the code under test")
            source = source.replace(old, new)
        name = f"_mutant_{tag}"
        module = types.ModuleType(name)
        module.__file__ = path
        sys.modules[name] = module   # @dataclass looks its own module up
        try:
            exec(compile(source, f"{path} [mutant {tag}]", "exec"),
                 module.__dict__)
        finally:
            sys.modules.pop(name, None)
        return module

    def goes_red(label, relpath, pairs, call, tag):
        """`call(module)` must answer differently on the mutant: law 5's
        other half, run on every suite pass rather than once by hand."""
        real = call(sys.modules[relpath.replace("/", ".")[:-3]])
        broken = call(mutant(relpath, *pairs, tag=tag))
        MUTATIONS.append((f"{relpath} :: {pairs[0][0].strip()[:56]}",
                          f"{real} -> {broken}"))
        expect(label, broken != real, True)

    def cli_run(argv, state, module=cli):
        """(exit code, everything printed) for one CLI command, no network."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(argv, transport=None, state=state)
        return code, out.getvalue() + err.getvalue()

    DRIFT_MODEL = BODY_I2I["model"]

    def row_of(ledger_id, kind, before, after,
               *, utc="2026-09-17T12:00:00.000000Z", **fields):
        row = dict.fromkeys(LEDGER_FIELDS)
        row.update(
            ledger_id=ledger_id, kind=kind, utc_time=utc,
            account_before=Account(3, True, None, before, 0).as_row(),
            account_after=(None if after is None
                           else Account(3, True, None, after, 0).as_row()),
            delta=(None if after is None else after - before), locked=False)
        row.update(fields)
        return row

    def gen_row(ledger_id, before, after, **fields):
        fields.setdefault("action", "img2img")
        fields.setdefault("model", DRIFT_MODEL)
        fields.setdefault("http_status", 200)
        fields.setdefault("output_png_sha256", "cd" * 32)
        return row_of(ledger_id, "generation", before, after, **fields)

    def refused_row(ledger_id, balance, **fields):
        """A row that SENT NOTHING: the guard refused after the balance read."""
        fields.setdefault("refusal_condition", 9)
        return row_of(ledger_id, "refused", balance, balance, **fields)

    def stated(state, *rows):
        for row in rows:
            state.write_row(row)
        return state

    D_PROOF = Proof("img2img", DRIFT_MODEL, "1216x832", "2026-09-17", "probe")
    PROBE = gen_row("probe", 1000, 1000, verdict="probe",
                    utc="2026-09-17T10:00:00.000000Z")
    CALL = gen_row("call", 1000, 1000, utc="2026-09-17T11:00:00.000000Z")
    SEEN = refused_row("seen", 800, action="img2img", model=DRIFT_MODEL,
                       utc="2026-09-17T13:40:41.000000Z")
    ACK = drift_ack("ack", "call", "seen", 1000, 800)
    CHARGED = gen_row("charged", 1000, 900, utc="2026-09-17T15:00:00.000000Z")
    # An EXTERNAL boundary is a fall across a window in which this tool sent
    # NOTHING: two `refused` rows, the guard having refused each one after
    # reading the balance and before any byte left.
    EXT1 = refused_row("ext1", 1000, utc="2026-09-17T11:00:00.000000Z")
    EXT2 = refused_row("ext2", 800, utc="2026-09-17T13:40:41.000000Z")

    # -- (a) a charge INSIDE one of our rows: ours, and nothing softens it --
    for label, rows_in in (
            ("with no signature in the ledger", [PROBE, CALL, CHARGED]),
            ("with a signed boundary already in the ledger",
             [PROBE, gen_row("g1", 1000, 1000, action="generate"),
              refused_row("seen-g", 800),
              drift_ack("ack-g", "g1", "seen-g", 1000, 800),
              gen_row("charged", 800, 700)])):
        standing, why = guard.proof_standing(D_PROOF, rows_in, None)
        expect(f"a charge INSIDE one of our img2img rows refutes for good, "
               f"{label}",
               (standing, "INSIDE that row" in why, "IS CHARGED" in why),
               (False, True, True))
    goes_red("...proved red: drop the within-row comparison and the charge "
             "reads as no charge at all", "tools/nai/guard.py",
             [("        if (before is not None and after < before) or (\n"
               "                _is_number(delta) and delta < 0):",
               "        if False and ((before is not None and after < before) "
               "or (\n                _is_number(delta) and delta < 0)):")],
             lambda g: g.proof_standing(D_PROOF, [PROBE, CALL, CHARGED],
                                        None)[0], tag="within_row_blind")
    for label, seed_rows in (
            ("with no signature in the ledger",
             [row_of("old", "generation", 800, 800)]),
            ("with a signed boundary in the ledger",
             [gen_row("old", 1000, 1000), refused_row("seen", 800),
              drift_ack("ack", "old", "seen", 1000, 800)])):
        charged_state = scratch_state("within_row")
        _t, st_c, row_c, exc_c, _p = scripted(
            REQ_GEN, [sub(800), zipped(), sub(790)],
            state=stated(charged_state, *seed_rows))
        with io.open(st_c.lock_path, encoding="utf-8") as handle:
            lock_text = handle.read()
        expect(f"run_request still LOCKs on a charge inside its own row, "
               f"{label}, and its LOCK says WHICH measurement that was",
               (row_c["delta"], row_c["locked"], st_c.locked(), exc_c,
                "OUR CHARGE, measured INSIDE" in lock_text,
                "`acknowledge-drift` cannot touch it" in lock_text,
                "EXTERNAL DRIFT" in lock_text),
               (-10, True, True, None, True, True, False))

    # -- (b) the classifier: what the earlier row SENT, and nothing else ----
    external = guard.open_boundary([EXT1, EXT2])
    ambiguous = guard.open_boundary([CALL, SEEN])
    expect("a boundary whose earlier row SENT NOTHING is EXTERNAL; one whose "
           "earlier row sent a request of ours is AMBIGUOUS. The ledger "
           "knows that and nothing else about whose money it was",
           (external.cause, external.ambiguous, external.delta,
            ambiguous.cause, ambiguous.ambiguous, ambiguous.delta),
           ("external", False, -200, "ambiguous", True, -200))
    expect("...and the EXTERNAL note says what was measured and whose "
           "judgement the rest is, never that a cause was measured",
           ("nothing this tool sent was MEASURED as charged"
            in guard.boundary_note(external),
            "your judgement, not a measurement"
            in guard.boundary_note(external),
            "not a charge for anything this tool sent"
            in guard.boundary_note(external)), (True, True, False))
    expect("...and the AMBIGUOUS note says outright that the tool cannot "
           "tell a late charge of ours from somebody else's spend",
           ("CANNOT say whose spend this was"
            in guard.boundary_note(ambiguous),
            "risk R4" in guard.boundary_note(ambiguous),
            "byte-identical" in guard.boundary_note(ambiguous)),
           (True, True, True))
    goes_red("...proved red: let the classifier forget what the earlier row "
             "sent and an ambiguous boundary reads as somebody else's",
             "tools/nai/guard.py",
             [('    if row.get("kind") != "generation":\n        return ""',
               '    if True:\n        return ""')],
             lambda g: g.open_boundary([CALL, SEEN]).cause, tag="sent_blind")

    # -- (c) THE MONEY ESCAPE: a provider that debits one minute late -------
    # Five img2img rows, each with before == after == delta 0, each one's
    # before-read 10 BELOW the previous row's after-read: the server debits
    # after our after-read. Nothing shows a non-zero in-row delta anywhere,
    # and the account goes 1000 -> 950 with every Anlas of it spent by this
    # tool. The reading under review booked all 50 to THEIRS, left `ours` at
    # 0 and re-armed img2img after five typed figures.
    LATE_ROWS = [gen_row("r0", 1000, 1000, verdict="probe",
                         utc="2026-09-17T16:26:04.000000Z")]
    for index in range(1, 6):
        LATE_ROWS.append(gen_row(f"r{index}", 1000 - 10 * index,
                                 1000 - 10 * index,
                                 utc=f"2026-09-17T16:2{index}:04.000000Z"))
    LATE_PROOF = Proof("img2img", DRIFT_MODEL, "1216x832", "2026-09-17", "r0")
    late_gaps = guard.open_boundaries(LATE_ROWS)
    expect("an asynchronous debit lands at a boundary: five falls, every one "
           "AMBIGUOUS, and the proof REFUTED for good -- not pending, "
           "because the row before each fall sent a request of ours",
           ([gap.cause for gap in late_gaps],
            sum(gap.delta for gap in late_gaps),
            guard.proof_standing(LATE_PROOF, LATE_ROWS, None)[0]),
           (["ambiguous"] * 5, -50, False))
    LATE_STATE = stated(scratch_state("late_debits"), *LATE_ROWS)
    code, printed = cli_run(["acknowledge-drift", "--anlas", "10", "--by",
                             "phil", "--checked", "the usage page"],
                            LATE_STATE)
    expect("`acknowledge-drift` REFUSES every one of them: it signs only a "
           "boundary across which this tool sent nothing, and writes nothing",
           (code, len(LATE_STATE.rows()), "AMBIGUOUS BOUNDARY" in printed,
            "resolve-boundary" in printed), (2, 6, True, True))
    for _round in range(5):
        gap = guard.open_boundary(LATE_STATE.rows())
        code, printed = cli_run(
            ["resolve-boundary", "--anlas", str(-gap.delta), "--attribute",
             "ours", "--by", "phil", "--checked",
             "the provider usage page shows these as mine"], LATE_STATE)
        expect_true(f"resolve-boundary signs {gap.previous_row}->"
                    f"{gap.observed_row} at {-gap.delta} Anlas", code == 0)
    books = guard.accounting(LATE_STATE.rows())
    _code, printed = cli_run(["ledger", "--last", "12"], LATE_STATE)
    expect("...and signed as OURS the 50 Anlas land on their own line, in NO "
           "figure that says somebody else spent them, while `ours spent` "
           "keeps saying what was MEASURED inside our rows: 0",
           (books.ours_spent, books.ours_signed, books.theirs_signed,
            books.unsigned, "ours by hand  -50 Anlas" in printed,
            "theirs        +0 Anlas" in printed),
           (0, -50, 0, 0, True, True))
    expect("...and after all five signatures img2img is STILL refused for "
           "good. THE ESCAPE: under the reading this pass replaced, the same "
           "five figures re-armed it while `ours` read 0",
           (guard.proof_standing(LATE_PROOF, LATE_STATE.rows(), None)[0],
            [v.ok for v in guard.evaluate(
                BODY_I2I, Account(3, True, None, 950, 0), (LATE_PROOF,),
                LATE_STATE, url=GENERATE_URL) if v.condition in (1, 9)]),
           (False, [False, True]))
    goes_red("...proved red: let the proof read the chain's allowance and "
             "one signature re-arms the action whose cost is the question",
             "tools/nai/guard.py",
             [("        if next_before < probe_after:\n"
               "            return late(probe_row, next_before, probe_after)\n"
               "        if next_before != probe_after:",
               "        allowed = expected_next_read(rows, probe_row, "
               "after_row, probe_after, next_before)\n"
               "        if next_before < allowed:\n"
               "            return late(probe_row, next_before, probe_after)\n"
               "        if next_before != allowed:"),
              ("        if following is not None and following < after:",
               "        if following is not None and following < "
               "expected_next_read(rows, row, following_row, after, "
               "following):")],
             lambda g: g.proof_standing(LATE_PROOF, LATE_STATE.rows(),
                                        None)[0], tag="proof_reads_allowance")

    # -- (d) the books with NOBODY signing anything -------------------------
    UNSIGNED = [gen_row("u1", 1000, 1000), refused_row("u2", 800),
                gen_row("u3", 800, 800), refused_row("u4", 700)]
    books = guard.accounting(UNSIGNED)
    UNSIGNED_STATE = stated(scratch_state("unsigned_books"), *UNSIGNED)
    _code, printed = cli_run(["ledger", "--last", "10"], UNSIGNED_STATE)
    expect("300 Anlas have left the account and nobody has typed a command: "
           "`unsigned` says so, names both boundaries, and is in NO other "
           "figure. This is the line whose absence made the books read "
           "`theirs +0` over 1911 Anlas of real falls",
           (books.unsigned, len(books.open_boundaries), books.theirs_signed,
            books.ours_spent, "UNSIGNED      -300 Anlas across 2" in printed,
            "u1->u2 (-200" in printed and "u3->u4 (-100" in printed),
           (-300, 2, 0, 0, True, True))
    expect("...and the per-row listing marks each fall WHERE it happened, "
           "rather than leaving two balances to be compared by eye",
           (printed.count("left the account here, UNSIGNED"),
            "200 Anlas left the account here, UNSIGNED (AMBIGUOUS: 1000 -> "
            "800)" in printed), (2, True))
    goes_red("...proved red: report only the first boundary and the figure a "
             "reader carries away is short", "tools/nai/guard.py",
             [("    return tuple(filter(None, (_boundary(rows, links[index], "
               "links[index + 1])\n                               for index "
               "in range(len(links) - 1))))",
               "    return tuple(filter(None, (_boundary(rows, links[index], "
               "links[index + 1])\n                               for index "
               "in range(len(links) - 1))))[:1]")],
             lambda g: g.accounting(UNSIGNED).unsigned, tag="first_gap_only")
    SIGNED_ONE = UNSIGNED + [drift_ack("s1", "u1", "u2", 1000, 800)]
    books = guard.accounting(SIGNED_ONE)
    expect("...signing one of them moves exactly that one out of `unsigned` "
           "and into `theirs`; the other is untouched",
           (books.unsigned, books.theirs_signed,
            [gap.previous_row for gap in books.open_boundaries]),
           (-100, -200, ["u3"]))

    # -- (e) OURS is never netted, in either direction ----------------------
    NETTED = [gen_row("refilled", 1000, 1500), gen_row("spent", 1500, 1000)]
    books = guard.accounting(NETTED)
    NET_STATE = stated(scratch_state("netted"), *NETTED)
    _code, printed = cli_run(["ledger", "--last", "4"], NET_STATE)
    expect("a refill that landed INSIDE one row can never cancel a charge "
           "measured INSIDE another: 500 spent and 500 refilled are two "
           "figures, and the tool says it was charged 500",
           (books.ours_spent, books.ours_refilled, books.refilled_rows,
            "ours spent    -500 Anlas" in printed,
            "ours refilled +500 Anlas" in printed,
            "ours spent    +0" in printed),
           (-500, 500, ("refilled",), True, True, False))
    expect("...and the words beside the figure state the same sign "
           "convention the arithmetic uses: after-read minus before-read",
           ("each row's OWN after-read minus its own before-read" in printed,
            "before-read minus its own after-read" in printed), (True, False))
    goes_red("...proved red: net the two directions into one figure and a "
             "charge of 500 reports as nothing at all", "tools/nai/guard.py",
             [("        if after < before:\n            spent += after - "
               "before\n        elif after > before:",
               "        if after != before:\n            spent += after - "
               "before\n        elif False:")],
             lambda g: g.accounting(NETTED).ours_spent, tag="ours_netted")
    goes_red("...proved red: invert the printed sign convention and the "
             "sentence disagrees with the number beside it", "tools/nai/cli.py",
             [('f"after-read minus its own before-read, so a charge shows '
               'negative. "', 'f"before-read minus its own after-read. "')],
             lambda c: "after-read minus its own before-read" in cli_run(
                 ["ledger", "--last", "4"], NET_STATE, module=c)[1],
             tag="sign_words_inverted")

    # -- (f) no figure is ever added to another -----------------------------
    MIXED = stated(scratch_state("mixed_books"),
                   gen_row("a", 20000, 19993, action="generate"),
                   gen_row("call", 19993, 19993),
                   refused_row("seen", 18247),
                   drift_ack("ack2", "call", "seen", 19993, 18247))
    _code, printed = cli_run(["ledger", "--last", "4"], MIXED)
    expect("`ledger` prints every figure and NEVER their sum: -7 and -1746 "
           "are both there, -1753 is nowhere",
           ("ours spent    -7 Anlas" in printed,
            "theirs        -1746 Anlas" in printed, "1753" in printed),
           (True, True, False))
    goes_red("...proved red: add one total line and the sum appears",
             "tools/nai/cli.py",
             [("    if books.unmeasured:",
               '    lines.append(f"total {books.ours_spent + '
               'books.theirs_signed}")\n    if books.unmeasured:')],
             lambda c: "1753" in cli_run(["ledger", "--last", "4"],
                                         MIXED, module=c)[1],
             tag="summed_total")
    expect("...and the drift row is listed as an accounting entry -- the "
           "boundary it signs, as whose, by whom, on what check -- not as a "
           "request with every column blank",
           ("between call and seen" in printed, "as theirs" in printed,
            "by phil" in printed, "checked the usage page" in printed,
            "seed -" in printed.split("ack2")[1].split("\n")[0]),
           (True, True, True, True, False))

    # -- (g) one boundary, one signature ------------------------------------
    TWICE = [CALL, SEEN, ACK, drift_ack("ack-again", "call", "seen", 1000, 800)]
    expect_raises("two signatures at ONE boundary are refused outright, both "
                  "rows named: the alternative is `theirs` counting the same "
                  "money twice", ValueError,
                  lambda: guard.accounting(TWICE),
                  "are signed TWICE", "'ack'", "'ack-again'")
    goes_red("...proved red: let the second one through and theirs doubles",
             "tools/nai/guard.py",
             [("            if (earlier.previous_row, earlier.observed_row) "
               "== (\n                    signature.previous_row, "
               "signature.observed_row):",
               "            if False and (earlier.previous_row, "
               "earlier.observed_row) == (\n                    "
               "signature.previous_row, signature.observed_row):")],
             lambda g: str(outcome(lambda: g.accounting(TWICE).theirs_signed)),
             tag="double_signature")
    RACE = stated(scratch_state("race"), EXT1, EXT2)
    stale = guard.open_boundary(RACE.rows())
    code_a, _out_a = cli_run(["acknowledge-drift", "--anlas", "200", "--by",
                              "phil", "--checked", "the usage page"], RACE)
    code_b, out_b = cli_run(["acknowledge-drift", "--anlas",
                             str(-stale.delta), "--by", "phil", "--checked",
                             "the usage page"], RACE)
    expect("...and the CLI cannot make one: the second process re-reads the "
           "ledger inside its own hold and finds the boundary gone",
           (code_a, code_b, len(RACE.rows()),
            "nothing to sign" in out_b or "changed while" in out_b),
           (0, 2, 3, True))
    HELD = stated(scratch_state("held_inflight"), EXT1, EXT2)
    HELD.acquire_inflight("some-other-process", 800)
    code, printed = cli_run(["acknowledge-drift", "--anlas", "200", "--by",
                             "phil", "--checked", "the usage page"], HELD)
    expect("a signature is refused while INFLIGHT says a request of ours is "
           "in the air: that is the tool's own statement that this is NOT a "
           "window in which nothing of ours was outstanding",
           (code, len(HELD.rows()), "INFLIGHT is present" in printed,
            "some-other-process" in printed), (2, 2, True, True))
    HELD.release_inflight("some-other-process")
    STRAY = [EXT1, EXT2, drift_ack("stray", "nowhere", "elsewhere", 1000, 800)]
    expect_raises("a signature naming a boundary that is not two rows side "
                  "by side is refused, not counted in full while the real "
                  "gap stays open", ValueError,
                  lambda: guard.accounting(STRAY),
                  "are not two rows side by side")

    # -- (h) the boundary nobody can blame is answerable, never terminal ----
    LOST = [gen_row("lost", 1000, None, locked=True, http_status=None,
                    output_png_sha256=None),
            refused_row("after-lost", 900)]
    gap = guard.open_boundary(LOST)
    expect("a fall after a row whose own after-read FAILED is AMBIGUOUS, not "
           "a raise: it is read, classified and reported, because a raise "
           "from a function every command calls bricks an append-only "
           "ledger for good",
           (gap.cause, gap.high, gap.low, "after-read failed" in gap.why,
            "resolve-boundary" in guard.boundary_note(gap)),
           ("ambiguous", 1000, 900, True, True))
    LOST_STATE = stated(scratch_state("lost_after"), *LOST)
    code, printed = cli_run(["resolve-boundary", "--anlas", "100",
                             "--attribute", "ours", "--by", "phil",
                             "--checked", "the usage page, by hand"],
                            LOST_STATE)
    expect("...and the command the message names really clears it: the "
           "ledger is usable again, and the 100 is on the books as ours by "
           "hand rather than quietly gone",
           (code, guard.open_boundary(LOST_STATE.rows()),
            guard.accounting(LOST_STATE.rows()).ours_signed,
            guard.accounting(LOST_STATE.rows()).unmeasured),
           (0, None, -100, ("lost",)))
    _t, _st, _row, exc, pattern = scripted(
        REQ_GEN, [sub(900), zipped(), sub(900)], state=LOST_STATE)
    expect("...and a run goes through afterwards: before this, the only exit "
           "from that ledger was hand-editing a money file",
           (exc, pattern), (None, [GET, POST, GET]))
    goes_red("...proved red: raise on the unclassifiable boundary again and "
             "the ledger is a dead end", "tools/nai/guard.py",
             [('        why = (f"the balance after ledger row '
               '{earlier.get(\'ledger_id\')} was "',
               '        raise ValueError("check the account by hand")\n'
               '        why = (f"the balance after ledger row '
               '{earlier.get(\'ledger_id\')} was "')],
             lambda g: str(outcome(lambda: g.open_boundary(LOST)))[:40],
             tag="lost_after_raises")
    expect("...and a row whose after-read failed is counted in NO figure, "
           "and the EXTERNAL wording never claims every row of ours measured "
           "both sides of itself",
           ("every row of ours measured the balance on both sides"
            in guard.boundary_note(external),
            "listed separately" in guard.boundary_note(external)),
           (False, True))

    # -- (i) the refusal names the drop THIS call saw, with its own figure --
    OLD_GAP = stated(scratch_state("old_gap"),
                     gen_row("old-a", 10000, 10000,
                             utc="2026-09-17T09:00:00.000000Z"),
                     refused_row("old-b", 8000,
                                 utc="2026-09-17T12:00:00.000000Z"),
                     gen_row("new-a", 8000, 8000,
                             utc="2026-09-17T12:30:00.000000Z"))
    _t, _st, _row, exc, pattern = scripted(REQ_GEN, [sub(7990)],
                                           state=OLD_GAP)
    message = str(exc)
    expect("a call that sees 8000 -> 7990 is told about THAT, first, with "
           "the 10 it saw -- and the older 2000 gap is listed after it. The "
           "live LOCK this pass was written against blamed a drop from three "
           "hours earlier and printed its figure instead",
           (getattr(exc, "condition", None),
            message.index("8000 -> 7990")
            < message.index("old-a->old-b (-2000)"),
            "(10 Anlas)" in message, "1 OTHER unsigned boundary" in message,
            "-2000 Anlas in all" in message),
           (9, True, True, True, True))
    expect("...and the command it prints for the drop just seen names the "
           "row that recorded it, so it can actually be typed",
           (f"--observed {_st.rows()[-1]['ledger_id']}" in message,
            "not yet a ledger row" in message), (True, False))
    goes_red("...proved red: report the oldest open gap first and the "
             "author is pointed at the wrong event with the wrong figure",
             "tools/nai/run.py",
             [("    if this_read:\n        gaps.insert(0, live_boundary(",
               "    if this_read and False:\n        gaps.insert(0, "
               "live_boundary(")],
             lambda r: str(outcome(lambda: r._chain_note(
                 OLD_GAP, 8000, 7990,
                 row_of("pending", "refused", 7990, 7990),
                 guard.open_boundaries(OLD_GAP.rows()), "charged")))[:90],
             tag="oldest_gap_first")
    if OLD_GAP.locked():
        os.remove(OLD_GAP.lock_path)

    # -- (j) the sibling routes: account, plan and the run route agree ------
    SIB = stated(scratch_state("sibling_account"),
                 gen_row("s-lost", 1000, None, locked=True, http_status=None,
                         output_png_sha256=None))
    def account_run(state, balance, module=cli):
        """`account` against a scripted balance read, no socket."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = module.main(["account"], state=state,
                               transport=tp.RecordingTransport([sub(balance)]))
        return code, out.getvalue()

    code, printed = account_run(SIB, 900)
    expect("`account` classifies with the SAME function the run route uses: "
           "over a ledger whose last row's after-read failed it says "
           "AMBIGUOUS, and never that nothing this tool sent was charged",
           (code, "AMBIGUOUS BOUNDARY" in printed,
            "Nothing this tool sent was charged" in printed,
            "EXTERNAL DRIFT" in printed), (2, True, False, False))
    expect("...and its last line is a WHOLE-STATE verdict, so a reassuring "
           "word never sits on the same screen as an open boundary",
           ("verdict       REFUSED" in printed,
            "free tier     usable" in printed), (True, False))
    goes_red("...proved red: hard-code the chain sentence again and the "
             "account route states a cause the run route refuses to state",
             "tools/nai/cli.py",
             [('            gaps.insert(0, guard.live_boundary(rows, '
               'previous, account.sum))',
               '            gaps.insert(0, guard.live_boundary(rows, '
               'previous, account.sum));'
               ' _out("Nothing this tool sent was charged")')],
             lambda c: "Nothing this tool sent was charged"
             in account_run(SIB, 900, module=c)[1], tag="account_hardcoded")
    PLAN_STATE = stated(scratch_state("plan_drift"), CALL, SEEN)
    code, printed = cli_run(["plan", "walk", "--action", "generate",
                             "--seed", str(SEED)], PLAN_STATE)
    expect("`plan` is offline and open_drift is pure, so a plan over books "
           "with money missing says so and REFUSES: it used to print "
           "'every offline condition passes' over a certain refusal",
           (code, " 9 [FAIL]" in printed,
            "every offline condition passes" in printed,
            "AMBIGUOUS BOUNDARY" in printed), (2, True, False, True))
    goes_red("...proved red: skip the ledger half offline and plan gives a "
             "clean bill over an open boundary", "tools/nai/guard.py",
             [("    if gaps:\n        return Verdict(9, False, "
               "boundaries_note(gaps, this_read=False))",
               "    if gaps and False:\n        return Verdict(9, False, "
               "boundaries_note(gaps, this_read=False))")],
             lambda g: [v.ok for v in g.evaluate(
                 BODY_GEN, None, (), PLAN_STATE, url=GENERATE_URL)
                 if v.condition == 9], tag="plan_blind_offline")

    # -- (k) what the signing command prints --------------------------------
    SIGN = stated(scratch_state("sign_output"), PROBE, CALL, SEEN)
    SIGN.add_proof(D_PROOF)
    code, printed = cli_run(["resolve-boundary", "--anlas", "200",
                             "--attribute", "theirs", "--by", "phil",
                             "--checked",
                             "the provider usage page, and my friend said so",
                             "--note", "a friend, on the shared account"],
                            SIGN)
    row = SIGN.rows()[-1]
    expect("a signing command writes ONE row carrying everything a reader "
           "needs a month later: both balances, the delta, the two ids, who "
           "signed, as whose, and what he checked",
           (code, row["kind"], row["delta"], row["account_before"]["sum"],
            row["account_after"]["sum"], row["drift_previous_row"],
            row["drift_observed_row"], row["drift_acknowledged_by"],
            row["drift_attribution"], row["drift_checked"] is not None),
           (0, "drift", -200, 1000, 800, "call", "seen", "phil", "theirs",
            True))
    expect("...and it SAYS what it did not do: the proof it could not "
           "restore is printed with its standing beside it",
           ("re-baselined" in printed, "proof         img2img" in printed,
            "REFUTED for good" in printed,
            "never measures an action free" in printed),
           (True, True, True, True))
    expect("...and signing did not move that proof, which is the whole rule",
           guard.proof_standing(D_PROOF, SIGN.rows(), None)[0], False)
    TWO_OPEN = stated(scratch_state("two_open"), EXT1, EXT2,
                      refused_row("more", 800), refused_row("seen3", 750))
    code, printed = cli_run(["acknowledge-drift", "--anlas", "200", "--by",
                             "phil", "--checked", "the usage page"], TWO_OPEN)
    expect("...and STILL OPEN is a figure and a boundary, never a bare "
           "window: the second gap is named, priced and given its command",
           (code, "STILL OPEN" in printed, "(50 Anlas)" in printed,
            "more" in printed.split("STILL OPEN")[1]), (0, True, True, True))
    LOCKED_SIGN = stated(scratch_state("sign_locked"), EXT1, EXT2)
    LOCKED_SIGN.lock("seen", "check_nai fixture")
    _code, locked_out = cli_run(["acknowledge-drift", "--anlas", "200",
                                 "--by", "phil", "--checked",
                                 "the usage page"], LOCKED_SIGN)
    expect("signing NEVER deletes LOCK: one that could would be able to "
           "clear the LOCK a charge measured INSIDE one of our rows wrote",
           (LOCKED_SIGN.locked(), "never deletes it" in locked_out),
           (True, True))
    expect("a figure that is not the one measured is refused, and writes "
           "nothing",
           cli_run(["acknowledge-drift", "--anlas", "199", "--by", "phil",
                    "--checked", "the usage page"],
                   stated(scratch_state("wrong_figure"), EXT1, EXT2))[0], 2)
    expect("a signature with nothing recorded about what was checked is "
           "refused by the parser, before the ledger is read at all",
           cli_run(["acknowledge-drift", "--anlas", "200", "--by", "phil",
                    "--checked", "  "],
                   stated(scratch_state("unchecked"), EXT1, EXT2))[0], 2)
    CHARGE_ONLY = stated(scratch_state("charge_not_boundary"), PROBE, CALL,
                         CHARGED, gen_row("next", 900, 900))
    code, printed = cli_run(["acknowledge-drift", "--anlas", "100", "--by",
                             "phil", "--checked", "the usage page"],
                            CHARGE_ONLY)
    expect("a charge INSIDE a row shows at NO boundary, so there is nothing "
           "for a signature to attach to: the command says exactly that and "
           "writes nothing",
           (code, len(CHARGE_ONLY.rows()), "nothing to sign" in printed,
            "INSIDE one of our own rows is not signed here" in printed),
           (2, 4, True, True))

    # -- (l) the messages print commands that work --------------------------
    LIVE = stated(scratch_state("live_read"), PROBE)
    standing, why = guard.proof_standing(D_PROOF, LIVE.rows(), 900)
    expect("a live read below the probe refutes it and prints NO timestamp "
           "it does not have -- the second half of that window is not a row",
           (standing, "None" in why, "risk R4" in why), (False, False, True))
    live = guard.live_boundary(LIVE.rows(), 1000, 900)
    note = guard.boundary_note(live)
    expect("...and a boundary whose later side is a live read prints no "
           "command at all: nothing can sign a read that is not written "
           "down, and a printed command that exits 2 is worse than none",
           ("not yet a ledger row" in note, "--anlas 100" in note,
            "-> None" in live.window), (True, False, False))
    printed_command = [word for word in
                       guard.boundary_note(external).split("`")
                       if word.startswith("python -m tools.nai")]
    head, _sep, _quoted = printed_command[0].partition("--checked")
    argv = head.split()[3:] + ["--checked", "the provider usage page"]
    argv[argv.index("NAME")] = "phil"
    code, _printed = cli_run(argv, stated(scratch_state("printed_command"),
                                          EXT1, EXT2))
    expect("...and the command an EXTERNAL note prints is one that runs: "
           "typed exactly as printed (with a name) it exits 0",
           (code, argv[0]), (0, "acknowledge-drift"))

    # -- (m) _refuted_note walks the chain, never the raw rows --------------
    # the proof stands over these rows -- the fall is behind a GENERATE row,
    # and the boundary it left is signed -- so the new row is what refutes it
    NOTE_STATE = stated(scratch_state("refuted_note"), PROBE, CALL,
                        gen_row("g-mid", 1000, 1000, action="generate"),
                        refused_row("seen-n", 800),
                        drift_ack("sig-last", "g-mid", "seen-n", 1000, 800))
    NOTE_STATE.add_proof(D_PROOF)
    note = run._refuted_note(NOTE_STATE, gen_row("fresh", 800, 750))
    expect("the LOCK text names the last row that SENT something, never a "
           "signature annotation sitting at the end of the ledger",
           ("sig-last" in note, "seen-n" in note, "REFUTES its proof" in note),
           (False, True, True))
    goes_red("...proved red: read rows[-1] positionally and the text calls "
             "an annotation 'a later img2img call'", "tools/nai/run.py",
             [("    links = chain_rows(rows)\n    last_id = "
               "links[-1].get(\"ledger_id\") if links else None",
               "    last_id = rows[-1].get(\"ledger_id\") if rows else None")],
             lambda r: "sig-last" in r._refuted_note(
                 NOTE_STATE, gen_row("fresh", 800, 750)),
             tag="refuted_note_positional")
    expect("...and it names the proof as REFUTED FOR GOOD, which is what the "
           "author reads before deciding about money",
           guard.proof_standing(D_PROOF, NOTE_STATE.rows(), None)[0], True)

    # -- (n) a drift row is a drift row, and nothing else -------------------
    SHAPE = scratch_state("drift_shape")
    expect_raises("a drift row carrying an action is refused: the whitelist "
                  "keeps it from ever reading as a generation", ValueError,
                  lambda: SHAPE.write_row(dict(ACK, action="img2img",
                                               model=DRIFT_MODEL)),
                  "a drift row fills only", "also fills ['action', 'model']")
    for masquerade, named in (({"verdict": "probe"}, "['verdict']"),
                              ({"http_status": 200}, "['http_status']"),
                              ({"output_png_sha256": "ab" * 32},
                               "['output_png_sha256']"),
                              ({"strip": "walk", "sprite_sha256": "ab" * 32},
                               "['sprite_sha256', 'strip']"),
                              ({"locked": True}, "['locked']")):
        expect_raises(f"...nor one carrying {sorted(masquerade)}", ValueError,
                      lambda m=masquerade: SHAPE.write_row(dict(ACK, **m)),
                      "a drift row fills only", named)
    expect_raises("...nor one that does not say WHOSE the money was",
                  ValueError,
                  lambda: SHAPE.write_row(dict(ACK, drift_attribution="maybe")),
                  "not one of ('theirs', 'ours')")
    expect_raises("...nor one with nothing recorded about what was checked",
                  ValueError,
                  lambda: SHAPE.write_row(dict(ACK, drift_checked=None)),
                  "its drift_checked is None")
    expect_raises("a GENERATION row that fills a drift field is refused too "
                  "-- the other half of the same rule", ValueError,
                  lambda: SHAPE.write_row(dict(CALL, drift_previous_row="x")),
                  "may not fill ['drift_previous_row']")
    expect("a drift row proves nothing: probe_row_problem reads its kind "
           "first, so it is never a probe and never becomes a proof",
           guard.probe_row_problem(ACK).startswith(
               "it is not a img2img/infill probe row (kind 'drift'"), True)
    STRAY_ROW = drift_ack("stray", "elsewhere", "elsewhere2", 900, 800)
    expect("a drift row sitting where the row after a probe would be is "
           "STEPPED OVER, not read as that row's balance",
           guard.proof_standing(D_PROOF, [PROBE, STRAY_ROW, CALL], None)[0],
           True)
    goes_red("...proved red: let the chain keep drift rows and an annotation "
             "becomes the read that judges the probe", "tools/nai/guard.py",
             [('    return [row for row in rows if row.get("kind") != '
               'DRIFT_KIND]', "    return list(rows)")],
             lambda g: g.proof_standing(D_PROOF, [PROBE, STRAY_ROW, CALL],
                                        None)[0], tag="chain_keeps_drift")
    goes_red("...proved red: drop the whitelist and a drift row can be "
             "written wearing an action", "tools/nai/model.py",
             [("    filled = sorted(key for key, value in row.items()",
               "    filled = [] and sorted(key for key, value in row.items()")],
             lambda m: m.drift_row_problem(dict(ACK, action="img2img")),
             tag="whitelist_off")

    # -- (o) one signature covers ONE boundary, exactly ---------------------
    LATER_GAP = [PROBE, CALL, SEEN, gen_row("after", 800, 800),
                 refused_row("seen2", 600), ACK]
    later_gap = guard.open_boundary(LATER_GAP)
    expect("a signature does not cover a LATER drop, not even one of the "
           "same size: that boundary is open on its own",
           (later_gap.previous_row, later_gap.observed_row, later_gap.delta),
           ("after", "seen2", -200))
    BIGGER = [PROBE, CALL, refused_row("seen", 700), ACK]  # ACK names call->seen
    bigger = guard.open_boundary(BIGGER)
    expect("...and it does not cover a LARGER drop at its own boundary: the "
           "residual 100 stays open, measured from the re-baselined 800",
           (bigger.high, bigger.low, bigger.delta), (800, 700, -100))
    goes_red("...proved red: let the expected read follow the balance down "
             "and the residual disappears", "tools/nai/guard.py",
             [("    return high + allowed\n",
               "    return high + allowed if low is None else "
               "min(high + allowed, low)\n")],
             lambda g: g.open_boundary(BIGGER), tag="residual_absorbed")
    goes_red("...proved red: an allowance not keyed on ITS OWN boundary "
             "stops telling the gaps apart", "tools/nai/guard.py",
             [("               if signature.previous_row == previous_row\n"
               "               and signature.observed_row == observed_row)",
               "               if True or (signature.previous_row == "
               "previous_row\n               and signature.observed_row == "
               "observed_row))")],
             lambda g: str(outcome(lambda: g.open_boundary(LATER_GAP)))[:40],
             tag="allowance_global")
    FORGED = [PROBE, CALL, CHARGED,
              drift_ack("forge", "call", "charged", 1000, 900)]
    expect("a signature forged onto the boundary in FRONT of a charged row "
           "cannot absorb it: that boundary never fell, so it is refused",
           (guard.proof_standing(D_PROOF, FORGED, None)[0],
            str(outcome(lambda: guard.open_boundary(FORGED)))[:68]),
           (False, "ValueError: ledger rows 'call' -> 'charged' are signed "
                   "for 100 Anlas"))
    goes_red("...proved red: let a signature exceed the drop it records and "
             "the forgery is allowed for", "tools/nai/guard.py",
             [("    if allowed < 0 and low is not None and "
               "low > high + allowed:", "    if False:")],
             lambda g: str(outcome(lambda: g.open_boundary(FORGED)))[:30],
             tag="allowance_unbounded")

    print("\n  mutation table -- each mutant compiled from the shipped file, "
          "its mutated text found there exactly once:")
    for where, shift in MUTATIONS:
        print(f"    {where:<74} {shift}")

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
