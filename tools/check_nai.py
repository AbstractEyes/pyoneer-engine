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
     1, 6 and 7 (image keys bound to the action, no proof, a proof naming a
     probe row with no image, no 2xx, a moved balance or LOCK, the infill
     probe's every strength, enabled, prompt/uc parity, use_coords,
     over-long arrays, the token budget, uc text) -- is refused with ITS OWN
     condition number, its own reason, and no other condition failing. A
     BALANCE EVENT IS A WARNING, NEVER A REFUSAL (the author's decision,
     2026-09-24: the account is shared): a live read below the chain, an
     unsigned fall, a proof the chain has refuted -- by a late debit, a
     refill, or a LATER charged or unread call of its pair -- each PASSES
     with a warning on exactly its own condition; a proof is left standing
     by a charged call of any other pair, a rise, or a charge before its
     probe; and each half is proved red by a mutant of the guard.
  3. `run.run_request` over a scripted transport: one POST between two balance
     reads on success, HTTP error and a raised timeout; no retry; a decrease
     is a WARNING in its own row and the next call is sent; the SUM is
     compared, through the real subscription parser, and grace / inactive /
     tier 2 are refused after one read; an inconclusive row chains on its
     own balance after, and a row whose after-read failed on its balance
     before; a Ctrl-C in the POST or in the after-read still writes the row,
     with a warning; a lost ledger (blobs, no rows) is refused; a corrupt
     deflate stream is recorded, not raised; a probe writes a proof only on
     2xx carrying an image of the requested size with delta 0 (an HTML page,
     an empty body, a 204, JSON or a wrong-size image write none), and a
     late debit refutes it for good; a production img2img or infill charged,
     unread after, or followed by a late debit refutes its proof, and every
     later call of the pair is SENT warning so; NOTHING in tools/nai calls
     State.lock, and a mutant that writes LOCK on a charge, or refuses on a
     fallen chain, goes red; the
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
     outside and ignores one inside; bad indexes, sizes and rects raise. A
     SHAPED mask (an L of whole latent blocks): composite pastes inside the
     L only and differs_outside sees a pixel in the L's bounding box but
     outside the L -- each proved red by pasting / blanking the box instead.
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
     img2img, `plan` passes WITH a warning that the proof is REFUTED and
     `run` sends again, printing it; `infill` sends the mannequin-in-source init and composites the
     returned cell; `render` never overwrites different bytes and no command
     writes inside a checkout outside data/nai/; a linked worktree resolves
     the main checkout's state root and sees its LOCK. `--character`
     reaches the plan's captions, an unknown name -- a path or a file name
     included -- exits 2 before anything is built, read or sent, a file
     the loader or the budget refuses exits 1 before a mannequin is drawn,
     and the default render file and sprites directory differ per
     character, each command printing the character's name.
 8c. request files (`spec`, `plan-request`, `run-request`,
     `request-catalog`): a file stating a recipe's generate, img2img or
     infill builds that recipe's body key for key; a slice loads with ONE
     tail, the pipeline's sampler and schedule, its mask's bounding
     rectangle as target_rect, and its images read beside it or inline; a
     mask of two separate latent-aligned rectangles loads; 29 steps, an
     area over the cap and a width off the grid LOAD and are refused by the
     guard's own condition in `plan-request`; every other rule -- an
     unknown, missing or stray key, a bad seed, band, noise, prompt,
     character, path, image or mask, and bytes that are not a JSON object
     -- is refused naming the file and the key; the shared band, decode
     and mask rules are proved to be recipes', characters' and masks' own
     by mutating each; the rating tag is ONE rule, `model.rating_tag_in`,
     however cased or spaced: no module but model.py names RATING_RX, the
     recipe, character, file and guard routes all call it, and a second
     rating tag before the closing tail is guard condition 7's refusal;
     `plan-request` prints exactly `plan`'s judgement for
     the same request; `run-request` sends ONCE, needs the author's proof
     for img2img, composites an infill and records differs_outside_mask;
     `request-catalog` prints the catalog, and the form names every key a
     person sets and locks every control a file has no key for.

State lives in a temporary directory, never under data/nai/ or data/art/;
the check asserts at the end that it did not create data/nai/.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede the tools.nai imports)

import ast
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
                       model, post, recipes, request, run, spec)
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


MUTATIONS: list[tuple[str, str]] = []

def mutant(relpath: str, *pairs, tag: str):
    """A COPY of `relpath` with each (old, new) applied, imported alone.

    THE SENTINEL IS THE COUNT. Each (old, new) must match the shipped file
    EXACTLY ONCE, so a mutation whose text has been renamed, reformatted or
    deleted raises here instead of quietly mutating nothing and reporting a
    green "the mutant answers the same" -- which is the one way a mutation
    table lies. A copy is compiled and imported under its own name, so the
    real module the rest of the suite is asserting on is never touched.
    """
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
    PIN_PARTS = PIN_DEFAULT_PARTS + ("dress", "heels", "cape", "hat",
                                     "brim", "coat", "mask")
    PIN_SUBJECTS = ("boy", "girl")
    expect("the DEFAULT outfit draws the seven parts it always drew, the "
           "vocabulary adds dress, heels, cape and hat and then brim, coat "
           "and mask -- APPENDED, never inserted, so a scout file's colours "
           "are still read in the order they always were -- and a file with "
           "none of the optional fields is a boy in those default garments "
           "on the default build",
           (IDENTITY_PARTS, PARTS, SUBJECT_NAMES, DEFAULT_SUBJECT,
            DEFAULT_GARMENTS, garment_parts(DEFAULT_GARMENTS),
            (WANT_LEGAL.subject, WANT_LEGAL.garments, WANT_LEGAL.build)),
           (PIN_DEFAULT_PARTS, PIN_PARTS, PIN_SUBJECTS, "boy",
            Garments("none", False, "scarf", "pants", "boots", False,
                     "none"),
            PIN_DEFAULT_PARTS, ("boy", Garments(), "standard")))
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
            ("a build nobody wrote -- the SIBLING ROUTE to the loader's own "
             "'build' refusal, judged by the one model.build_problem",
             dataclasses.replace(recipes.IDENTITY, build="tall"),
             "build", "'tall' is not a build"),
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
            mutant_hat = {}
            mannequin._hat(mutant_hat, 0, 0, (0x5A, 0x28, 0xA0))
        rows_ = {}
        for (x, y), _v in mutant_hat.items():
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
    wizard_drawn = {name for part in model.garment_parts(WIZARD.garments)
                    for name in mannequin._PART_SKELETON_NAMES.get(part, ())}
    expect("A GARMENTED MANNEQUIN'S NAME IS TAKEN OVER WHAT IT DRAWS: its "
           "non-default GARMENT SLOTS, and the constants of the PARTS those "
           "slots paint -- not over every garment in the vocabulary. The "
           "default outfit's name is taken over neither, so the shipped "
           "scout cannot be renamed by a hat constant; and a girl in a hat, "
           "a cape, a dress and heels cannot be renamed by a TRENCHCOAT "
           "she has never worn",
           (sorted(wizard_drawn - set(wizard_doc["skeleton"])),
            sorted(set(wizard_doc["skeleton"])
                   & (set(mannequin._GARMENT_SKELETON_NAMES)
                      - wizard_drawn - {"GARMENT_DRAW_VERSION"})),
            wizard_doc.get("garments"),
            sorted(set(mannequin._GARMENT_SKELETON_NAMES)
                   & set(scout_doc["skeleton"])),
            "garments" in scout_doc,
            "GARMENT_DRAW_VERSION" in wizard_doc["skeleton"]),
           ([], [], {"hat": "wizard", "cape": True, "neck": "none",
                     "legwear": "dress", "footwear": "heels"}, [], False,
            True))
    # MEASURED at b08e0bd, BEFORE the trenchcoat, the mask and the brim
    # existed, and pinned here as literals. Her drawn bytes never changed by
    # one pixel, yet all three of these moved when the coat was added --
    # because the whole constant block and two new `false`/`none` slots went
    # into her document. THREE ROWS OF data/nai/ledger.jsonl CARRY THE `run`
    # ONE, two of them real img2img spends, and a spend that can no longer be
    # reproduced from the code is a spend nobody can check.
    PIN_WIZARD_PARAMS = {
        "walk": "17e44eaa4d4c374d116b0f06e7dcc4e645ce3e5369e2b95f71e41512aa70bf28",
        "run": "de1446894a68d243975421b149ff6a7c18160855983e38043c4ebb0aeaa73930",
        "jump": "6cccb4438385fb3bbe3f040fbee6f0ccb174efd6b7416fedc49d782bbca72132",
    }
    expect("...and that is not a principle but a LITERAL: wizard_girl's "
           "three mannequin names are the ones the ledger already paid for, "
           "measured before any of these garments existed",
           {name: mannequin.params_sha256(
               recipes.get_recipe(name, "wizard_girl").layout,
               recipes.get_recipe(name, "wizard_girl").poses,
               WIZARD.as_dict(), garments=WIZARD.garments)
            for name in recipes.RECIPE_NAMES},
           dict(PIN_WIZARD_PARAMS))
    for constant, value in (("COAT_LEN", mannequin.COAT_LEN + 1),
                            ("BRIM_W", mannequin.BRIM_W + 1),
                            ("MASK_ROWS", mannequin.MASK_ROWS + 1),
                            ("COAT_COLLAR_IS_MASK", False)):
        with patched(mannequin, constant, value):
            moved = mannequin.params_sha256(L5, WALK.poses, WIZARD.as_dict(),
                                            garments=WIZARD.garments)
        expect(f"...so changing {constant} -- a garment she does not wear -- "
               f"leaves HER name exactly where the ledger left it",
               moved, PIN_WIZARD_PARAMS["walk"])
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


    # -- 1e. garet: the PROPORTION axis, and the gunslinger garments --------
    # The author drew ~Garet.png years ago and said one thing about it: "I
    # never did like how short his legs were." MEASURED off that file's side
    # pose before any of this was written -- 45 px tall, the coat hem 41 px
    # down, 3 px of boot below it, 6.7% of the figure. A long coat over a low
    # hip is a barrel with a hat on it, and no caption fixes a silhouette.
    GARET = characters.load("garet")
    PIN_GARET_GARMENTS = Garments("brim", False, "none", "pants", "boots",
                                  True, "mask")
    PIN_GARET_PARTS = ("skin", "hair", "tunic", "belt", "pants", "boots",
                       "brim", "coat", "mask")
    expect("garet.json is a boy on the LONG build in the gunslinger garments, "
           "and those garments draw exactly nine colour parts -- no scarf, "
           "because his neck is bare, and no `hat`, because a wide brim is "
           "its own part",
           (GARET.subject, GARET.build, GARET.garments,
            model.garment_parts(GARET.garments),
            tuple(part for part, _rgb in GARET.colours)),
           ("boy", "long", PIN_GARET_GARMENTS, PIN_GARET_PARTS,
            PIN_GARET_PARTS))

    # THE THIRD ROUTE. A file is judged by characters._build, an in-code
    # Identity by recipes.build_recipe (both above, both through
    # model.build_problem) -- and the mannequin is handed a bare string by
    # neither of them. It RAISES rather than falling back to the standard
    # build (CLAUDE.md law 7), because a silent fallback would draw a
    # perfectly good figure with the wrong proportions and nothing would say
    # so.
    for where, call in (
            ("_bones", lambda: mannequin._bones("tall")),
            ("_figure", lambda: mannequin._figure(
                WALK.poses[0], SCOUT.as_dict(), SCOUT.garments, "tall")),
            ("render_init", lambda: mannequin.render_init(
                L5, WALK.poses, SCOUT.as_dict(), build_name="tall")),
            ("params_sha256", lambda: mannequin.params_sha256(
                L5, WALK.poses, SCOUT.as_dict(), build_name="tall"))):
        expect_raises(f"mannequin.{where} RAISES on a build name nobody "
                      f"wrote; it does not fall back to the standard one",
                      ValueError, call, "unknown build 'tall'",
                      "('standard', 'original', 'long')")

    # -- the vocabulary, and the arithmetic that makes a build a build ------
    expect("the build vocabulary is three names, the DEFAULT FIRST and "
           "adding nothing to any bone, and every other build gives the "
           "torso exactly what it takes from the legs -- a build moves the "
           "HIP, it never resizes the figure",
           (model.BUILD_NAMES, model.DEFAULT_BUILD,
            tuple(b[1:] for b in model.BUILDS),
            sorted({b.thigh + b.shin + b.torso for b in model.BUILDS}),
            [b.hip_rise for b in model.BUILDS]),
           (("standard", "original", "long"), "standard",
            ((0, 0), (-2, -1), (2, 1)), [0], [0, -3, 3]))
    expect("...and `_bones` adds them to the shipped skeleton, so the "
           "standard build IS the shipped skeleton",
           {name: mannequin._bones(name) for name in model.BUILD_NAMES},
           {"standard": (9, 9, 12), "original": (7, 8, 15),
            "long": (11, 10, 9)})
    expect("the hat slot has THREE choices, each drawing its OWN part, and "
           "`coat` and `face` were APPENDED so every positional Garments and "
           "every file written before them still means scout's outfit",
           (dict(model.GARMENT_SLOTS[0].drawn),
            tuple(slot.name for slot in model.GARMENT_SLOTS),
            model.Garments("wizard", True, "none", "dress", "heels"),
            model.PARTS[-3:], model.IDENTITY_PARTS),
           ({"none": (), "wizard": ("hat",), "brim": ("brim",)},
            ("hat", "cape", "neck", "legwear", "footwear", "coat", "face"),
            Garments("wizard", True, "none", "dress", "heels", False, "none"),
            ("brim", "coat", "mask"), PIN_DEFAULT_PARTS))

    # -- the loader refuses each new word by name --------------------------
    def garet_doc(**changes):
        """garet.json's own fields with `changes` applied; None deletes."""
        doc = {"subject": "boy", "build": GARET.build,
               "tags": GARET.tags, "anchor": GARET.anchor,
               "garments": dict(PIN_GARET_GARMENTS._asdict()),
               "colours": {part: "#%02X%02X%02X" % rgb
                           for part, rgb in GARET.colours}}
        for key, value in changes.items():
            if value is None:
                doc.pop(key)
            else:
                doc[key] = value
        return json.dumps(doc).encode("utf-8")

    expect("...and that reconstruction loads back to the shipped file, so "
           "every refusal below is one field away from a legal character",
           characters.parse(garet_doc(), "rebuilt") == GARET, True)
    for label, changes, fragments in (
            ("a build that is not one of the three", {"build": "tall"},
             ("field 'build'", "'tall' is not a build",
              "('standard', 'original', 'long')")),
            ("a build that is not even a string", {"build": 3},
             ("field 'build'", "3 is not a build")),
            ("a hat choice the mannequin cannot draw",
             {"garments": dict(PIN_GARET_GARMENTS._asdict(), hat="stetson")},
             ("field 'garments.hat'", "'stetson' is not a legal hat",
              "'none', 'wizard', 'brim'")),
            ("a coat that is a JSON number, not a boolean",
             {"garments": dict(PIN_GARET_GARMENTS._asdict(), coat=1)},
             ("field 'garments.coat'", "1 is not a legal coat",
              "False, True")),
            ("a face covering that is not the mask",
             {"garments": dict(PIN_GARET_GARMENTS._asdict(), face="veil")},
             ("field 'garments.face'", "'veil' is not a legal face",
              "'none', 'mask'")),
            ("a garment slot that does not exist at all",
             {"garments": dict(PIN_GARET_GARMENTS._asdict(), spurs=True)},
             ("field 'garments'", "unknown garment(s) ['spurs']"))):
        expect_raises(f"a garet file with {label} is refused by name",
                      ValueError,
                      lambda c=changes: characters.parse(garet_doc(**c),
                                                         "garet_bad.json"),
                      "garet_bad.json", *fragments)

    def garet_colours(**changes):
        out = {part: "#%02X%02X%02X" % rgb for part, rgb in GARET.colours}
        for key, value in changes.items():
            if value is None:
                out.pop(key)
            else:
                out[key] = value
        return out

    for label, colours, fragments in (
            ("no colour for the coat it wears", garet_colours(coat=None),
             ("field 'colours'", "missing part(s) ['coat']")),
            ("no colour for the mask it wears", garet_colours(mask=None),
             ("field 'colours'", "missing part(s) ['mask']")),
            ("no colour for the brim it wears", garet_colours(brim=None),
             ("field 'colours'", "missing part(s) ['brim']")),
            ("a scarf colour under a bare neck",
             garet_colours(scarf="#C83C3C"),
             ("field 'colours'", "unused part(s) ['scarf']")),
            ("a wizard hat's colour under a wide brim",
             garet_colours(hat="#5A28A0"),
             ("field 'colours'", "unused part(s) ['hat']"))):
        expect_raises(f"a garet file with {label} is refused by name",
                      ValueError,
                      lambda c=colours: characters.parse(
                          garet_doc(colours=c), "garet_bad.json"),
                      "garet_bad.json", *fragments)
    expect("...and the colours rule is EXACTLY the parts these garments "
           "draw: garet's nine load, scout's seven under garet's garments do "
           "not, and garet's nine under scout's garments do not either. "
           "`parts_problem` answers with the FIRST kind of mismatch it finds, "
           "so scout's seven are refused for the scarf they carry rather "
           "than for the brim, coat and mask they lack -- one refusal names "
           "one field, and the next attempt meets the next one",
           (characters.parse(garet_doc(), "ok").colours == GARET.colours,
            str(outcome(lambda: characters.parse(
                garet_doc(colours={part: "#%02X%02X%02X" % SCOUT.colour(part)
                                   for part in PIN_DEFAULT_PARTS}),
                "g.json")))[:80],
            str(outcome(lambda: characters.parse(
                garet_doc(garments={}), "g.json")))[:80]),
           (True,
            "ValueError: character file g.json, field 'colours': unused "
            "part(s) ['scarf']; th",
            "ValueError: character file g.json, field 'colours': unused "
            "part(s) ['brim', 'coa"))

    # -- THE SCOUT PINS, ASSERTED AGAINST THIS AXIS ------------------------
    # PIN_SCOUT_INIT and PIN_SCOUT_PARAMS above were measured before the
    # garment vocabulary and before builds existed. These say WHY they still
    # hold: the default build is written into no document at all.
    scout_doc_b = mannequin.params_doc(L5, WALK.poses, SCOUT.as_dict())
    garet_doc_b = mannequin.params_doc(L5, WALK.poses, GARET.as_dict(),
                                       garments=GARET.garments,
                                       build_name=GARET.build)
    expect("a NON-DEFAULT build is named in the mannequin document by its "
           "name AND its two bone deltas -- retuning Build('long', 2, 1) "
           "would otherwise draw a different figure under the same name -- "
           "while the default build writes no key, so the shipped scout's "
           "pinned name cannot move when a build row does",
           (garet_doc_b.get("build"), "build" in scout_doc_b,
            mannequin.params_sha256(L5, WALK.poses, SCOUT.as_dict())
            == PIN_SCOUT_PARAMS["walk"],
            mannequin.params_sha256(L5, WALK.poses, SCOUT.as_dict(),
                                    garments=SCOUT.garments,
                                    build_name="standard")
            == PIN_SCOUT_PARAMS["walk"]),
           (["long", 2, 1], False, True, True))
    scout_on_builds = {
        name: hashlib.sha256(mannequin.render_init(
            L5, WALK.poses, SCOUT.as_dict(), garments=SCOUT.garments,
            build_name=name)[0]).hexdigest() == PIN_SCOUT_INIT["walk"]
        for name in model.BUILD_NAMES}
    expect("...and drawn: the shipped scout on the STANDARD build is the "
           "pinned bytes to the byte, and on either other build is not -- so "
           "this axis is proved to be off by default AND proved to do "
           "something when it is on",
           scout_on_builds,
           {"standard": True, "original": False, "long": False})
    for constant, value in (("COAT_LEN", mannequin.COAT_LEN + 1),
                            ("BRIM_W", mannequin.BRIM_W + 2),
                            ("MASK_ROWS", mannequin.MASK_ROWS + 1)):
        with patched(mannequin, constant, value):
            moved = mannequin.params_sha256(L5, WALK.poses, GARET.as_dict(),
                                            garments=GARET.garments,
                                            build_name=GARET.build)
            still = mannequin.params_sha256(L5, WALK.poses, SCOUT.as_dict())
        expect(f"...so changing {constant} renames HIS mannequin and leaves "
               f"the default outfit's alone",
               (moved != mannequin.params_sha256(
                   L5, WALK.poses, GARET.as_dict(), garments=GARET.garments,
                   build_name=GARET.build),
                still == PIN_SCOUT_PARAMS["walk"]), (True, True))

    # -- WHAT THE BUILD HOLDS AND WHAT IT MOVES, measured on the drawing ---
    def stance(build_name, recipe_name="walk"):
        """Per frame: (total height, head above the sole, shoulder above the
        sole, hip above the sole). The first three must NOT move with the
        build; the last must move by exactly its hip_rise."""
        who = dataclasses.replace(GARET, build=build_name)
        rows = []
        for pose in recipes.build_recipe(recipe_name, who).poses:
            px = mannequin._figure(pose, who.as_dict(), who.garments,
                                   build_name)
            ys = [y for _x, y in px]
            _t, _s, torso = mannequin._bones(build_name)
            sole = max(ys)
            rows.append((max(ys) - min(ys) + 1, sole - min(ys),
                         sole + (torso - mannequin.SHOULDER_DROP), sole))
        return rows

    held = {name: [row[:3] for row in stance(name)]
            for name in model.BUILD_NAMES}
    hips = {name: [row[3] for row in stance(name)]
            for name in model.BUILD_NAMES}
    expect("ON THE WALK STRIP THE HIP MOVES AND NOTHING ELSE DOES. Frame for "
           "frame, all three builds draw the same TOTAL HEIGHT, the same "
           "head above the ground line and the same SHOULDER above it -- so "
           "the arms hang from the same place and the ground line never "
           "shifts -- while the hip sits exactly hip_rise px higher",
           (held["original"] == held["standard"] == held["long"],
            {name: [h - b for h, b in zip(hips[name], hips["standard"])]
             for name in model.BUILD_NAMES}),
           (True, {"standard": [0] * 5, "original": [-3] * 5,
                   "long": [3] * 5}))

    # -- and what that equality is a property OF ---------------------------
    # `stance` has always taken a recipe and all four call sites left it at
    # "walk", so the sentence above was written as a claim about the AXIS
    # when it is a claim about GROUNDED, STRAIGHT-LEG POSES. It is not true
    # of a crouch: a bent leg's VERTICAL PROJECTION is shorter than its
    # bone, so moving 3 px out of the torso and into the legs subtracts 3 px
    # of height and adds less than 3 back -- `long` is SHORTER than
    # `standard` in a deep crouch and `original` is TALLER. Pass the recipe
    # and the absolute claim is red. What IS true of all three strips is a
    # BOUND, so that is what is asserted.
    BUILD_MAX_DRIFT = 6
    """Source px a build may move a figure's total height, its head above
    the ground line, or its shoulder above it, on ANY shipped pose. It is 0
    on walk; the worst is jump frame 0, where the shoulder moves 6 px
    between `original` and `long`. Bounded rather than left unsaid so that a
    retuned pose or a fourth build cannot widen it silently behind a
    `well, we already knew it was not exactly equal`."""

    def drift(table):
        """The worst px any build moves any of the three, over one strip."""
        return max(max(table[name][i][k] for name in table)
                   - min(table[name][i][k] for name in table)
                   for i in range(len(table["standard"]))
                   for k in range(3))
    every = {rn: {name: [row[:3] for row in stance(name, rn)]
                  for name in model.BUILD_NAMES}
             for rn in recipes.RECIPE_NAMES}
    expect("...and THAT equality is a property of grounded, straight-leg "
           "poses rather than of the axis: on the crouch and flight frames a "
           "build DOES move the height and the shoulder. What holds on every "
           "shipped strip is a BOUND -- no build moves any of the three by "
           "more than BUILD_MAX_DRIFT px -- and the walk strip's exact zero "
           "is what that bound is measured against",
           ({rn: drift(every[rn]) for rn in recipes.RECIPE_NAMES},
            all(drift(every[rn]) <= BUILD_MAX_DRIFT
                for rn in recipes.RECIPE_NAMES)),
           ({"walk": 0, "run": 3.0, "jump": 6.0}, True))
    with patched(model, "BUILDS",
                 model.BUILDS + (model.Build("giant", 9, 9),)),             patched(model, "BUILD_NAMES", model.BUILD_NAMES + ("giant",)):
        wild = {name: [row[:3] for row in stance(name, "jump")]
                for name in model.BUILD_NAMES}
    expect("...and a fourth build that redistributed 18 px instead of 3 "
           "breaks that bound, so it is an assertion and not a restatement "
           "of the arithmetic",
           drift(wild) > BUILD_MAX_DRIFT, True)

    # -- EVERY BUILD DRAWS EVERY STRIP, for the default outfit and for his -
    # This is the assertion `scout_on_builds` above should have been: it
    # renders three builds but only ever on WALK, so three shipped
    # combinations that could not be drawn AT ALL sat behind it. garet on
    # `standard` and on `original` could not draw `jump`, and neither could
    # the DEFAULT outfit on `original` -- a build docs/NAI_SPRITES.md
    # invites the author to ask for by saying "short legs". Everything that
    # WAS measured about the axis was vertical; the break was horizontal,
    # because a leaning pose carries the torso forward off the hip the
    # placement starts from.
    def unplaceable(module):
        out = []
        for who_name, who in (("scout", SCOUT), ("garet", GARET)):
            for build_name in model.BUILD_NAMES:
                for recipe_name in recipes.RECIPE_NAMES:
                    shape = recipes.build_recipe(recipe_name, who)
                    try:
                        module.render_init(shape.layout, shape.poses,
                                           who.as_dict(),
                                           garments=who.garments,
                                           build_name=build_name)
                    except ValueError:
                        out.append((who_name, build_name,
                                    recipe_name))
        return out
    expect("EVERY BUILD DRAWS EVERY STRIP, for the DEFAULT outfit and for "
           "garet's: 3 builds x 3 recipes x 2 outfits, every frame placed "
           "inside its own cell. A vocabulary value that cannot draw a third "
           "of the shipped strips is not a vocabulary",
           unplaceable(mannequin), [])
    goes_red("...and with the figure PINNED to the hip column instead of "
             "shifted the least that keeps its drawn box in its cell, three "
             "of those eighteen raise again -- so that loop measures the "
             "PLACEMENT, and the placement is what was wrong",
             "tools/nai/mannequin.py",
             [("    if bbox[2] - bbox[0] <= sx1 - sx0:\n"
               "        left, right = ox + dx + bbox[0], ox + dx + bbox[2]\n"
               "        dx += max(0, sx0 - left) - max(0, right - sx1)",
               "    if False:\n"
               "        pass")],
             unplaceable, tag="hip_pinned")
    goes_red("...and a placement that shifted a figure that ALREADY FITS "
             "would move every snapped centre the shipped scout is pinned "
             "on, so the shift is proved to be the least, not merely some",
             "tools/nai/mannequin.py",
             [("        dx += max(0, sx0 - left) - max(0, right - sx1)",
               "        dx += max(0, sx0 - left) - max(0, right - sx1) + 1")],
             lambda m: hashlib.sha256(m.render_init(
                 L5, WALK.poses, SCOUT.as_dict(),
                 garments=SCOUT.garments)[0]).hexdigest(),
             tag="hip_overshift")
    for bad_label, bad_bones in (
            ("legs that grow without the torso giving anything back",
             lambda name: (mannequin.THIGH + model.build(name).thigh,
                           mannequin.SHIN + model.build(name).shin,
                           mannequin.TORSO_H)),
            ("a torso that shrinks without the legs taking it",
             lambda name: (mannequin.THIGH, mannequin.SHIN,
                           mannequin.TORSO_H + model.build(name).torso))):
        with patched(mannequin, "_bones", bad_bones):
            broken = {name: [row[:3] for row in stance(name)]
                      for name in model.BUILD_NAMES}
        expect(f"...and with {bad_label} that equality fails, so it is an "
               f"assertion and not an identity",
               broken["original"] == broken["standard"] == broken["long"],
               False)
    with patched(mannequin, "_bones",
                 lambda name: (mannequin.THIGH, mannequin.SHIN,
                               mannequin.TORSO_H)):
        deaf = {name: [row[3] for row in stance(name)]
                for name in model.BUILD_NAMES}
    expect("...and with a `_bones` that ignores the build entirely the HIP "
           "stops moving, so that half can fail too",
           deaf["original"] == deaf["standard"] == deaf["long"], True)

    # -- the brim and the crown, on the drawing code itself ----------------
    # The same place the wizard brim is judged, and for the same reason: an
    # arm or a coat cannot hide half the answer in a bare dict of pixels.
    BRIM_MIN_BACK = 2
    BRIM_MIN_FRONT = 2
    """Source px the brim must overhang the 8 px head at the BACK and at the
    FACE. Both, and separately: the wizard brim was first drawn with all
    2.5 px of its overhang at the back and read as a cone with a flange, so
    a single `wider than the head` bound is the vacuous half again."""
    brim_px = {}
    mannequin._brim_hat(brim_px, 0, 0, GARET.colour("brim"))
    brim_rows = {}
    for (x, y), _v in brim_px.items():
        brim_rows.setdefault(y, []).append(x)
    widest = max(brim_rows, key=lambda y: len(brim_rows[y]))
    # THE CROWN IS ABOVE THE BRIM ROW AND THE DROOP IS BELOW IT, so they are
    # split by SIGN and not by "not the widest": read as `everything else`,
    # the droop counted as a fourth crown row and CROWN_H stopped being
    # measured at all.
    crown_rows = {y: xs for y, xs in brim_rows.items() if y < widest}
    droop_rows = {y: xs for y, xs in brim_rows.items() if y > widest}
    droop_cols = sorted({x for xs in droop_rows.values() for x in xs})
    cone_px = {}
    mannequin._hat(cone_px, 0, 0, GARET.colour("brim"))
    cone_rows = {}
    for (x, y), _v in cone_px.items():
        cone_rows.setdefault(y, []).append(x)
    cone_widest = max(cone_rows, key=lambda y: len(cone_rows[y]))
    expect("THE GUNSLINGER BRIM IS FLAT, BROAD AND FRONT-HEAVY: one row, on "
           "the head and not above it, overhanging the 8 px head at the back "
           "AND further at the face -- and over it a LOW crown, CROWN_H rows "
           "that never narrow past CROWN_TAPER. Beside it the wizard cone "
           "from the same head: twice the rows above the brim and narrowing "
           "to a point. That difference IS the character at 15 px",
           (len(brim_rows[widest]), widest, widest <= mannequin.BRIM_ROW,
            0 - min(brim_rows[widest]) >= BRIM_MIN_BACK,
            max(brim_rows[widest]) - (mannequin.HEAD - 1) >= BRIM_MIN_FRONT,
            len(crown_rows), min(len(xs) for xs in crown_rows.values()),
            len(cone_rows) - 1, min(len(xs) for xs in cone_rows.values())),
           (mannequin.BRIM_W, 1, True, True, True,
            mannequin.CROWN_H, mannequin.CROWN_W - mannequin.CROWN_TAPER,
            mannequin.HAT_CONE_H, mannequin.HAT_TIP_W))
    expect("THE BRIM HAS DEPTH, AND ONLY OVER ITS OVERHANG: the columns "
           "past the 8 px head fall BRIM_DROOP_ROWS further, the columns "
           "resting on the crown do not fall at all, and the widest row is "
           "still the flat brim. One hat-coloured row between two outline "
           "rows is a plank; the author's own brim is nine sculpted rows "
           "deep. This buys depth at ZERO extra width, which is the "
           "dimension the cell forbids",
           (len(droop_rows),
            sorted(droop_rows) == [widest + d + 1
                                   for d in range(len(droop_rows))],
            bool(droop_cols) and max(droop_cols) > mannequin.HEAD - 1,
            bool(droop_cols) and min(droop_cols) < 0,
            all(not 0 <= x < mannequin.HEAD for x in droop_cols),
            len(brim_rows[widest]) > max((len(xs) for xs
                                          in droop_rows.values()),
                                         default=0)),
           (mannequin.BRIM_DROOP_ROWS, True, True, True, True, True))
    with patched(mannequin, "BRIM_DROOP_ROWS", 0):
        flat = {}
        mannequin._brim_hat(flat, 0, 0, GARET.colour("brim"))
    expect("...and at BRIM_DROOP_ROWS 0 the hat is that plank again -- one "
           "row below the crown and nothing under it -- so the depth is "
           "asserted and not merely described",
           (len({y for _x, y in flat}), len(brim_rows)),
           (mannequin.CROWN_H + 1, mannequin.CROWN_H + 1
            + mannequin.BRIM_DROOP_ROWS))
    expect("...and the two hats are two SHAPES, not one shape with two "
           "names: the cone reaches higher above the head than the crown "
           "does, and the brim reaches wider than the cone's",
           (min(cone_rows) < min(brim_rows),
            len(brim_rows[widest]) > len(cone_rows[cone_widest])),
           (True, True))

    def brim_shape(**changes):
        """(widest row's width, back overhang, front overhang, crown rows)
        for a `_brim_hat` drawn with `changes` patched in."""
        with contextlib.ExitStack() as stack:
            for name_, value in changes.items():
                stack.enter_context(patched(mannequin, name_, value))
            out = {}
            mannequin._brim_hat(out, 0, 0, GARET.colour("brim"))
        rows = {}
        for (x, y), _v in out.items():
            rows.setdefault(y, []).append(x)
        wide = max(rows, key=lambda y: len(rows[y]))
        return (len(rows[wide]), 0 - min(rows[wide]),
                max(rows[wide]) - (mannequin.HEAD - 1), len(rows) - 1)

    def brim_row(**changes):
        """The row the brim's widest row sits on, with `changes` patched."""
        with contextlib.ExitStack() as stack:
            for name_, value in changes.items():
                stack.enter_context(patched(mannequin, name_, value))
            out = {}
            mannequin._brim_hat(out, 0, 0, GARET.colour("brim"))
        rows = {}
        for (x, y), _v in out.items():
            rows.setdefault(y, []).append(x)
        return max(rows, key=lambda y: len(rows[y]))

    for label, changes, wanted in (
            ("BRIM_W 15 -> 8 (no brim at all, just a crown)",
             {"BRIM_W": 8}, "width"),
            ("BRIM_FWD 0.5 -> -4.0 (every px of overhang at the back)",
             {"BRIM_FWD": -4.0}, "front"),
            ("BRIM_FWD 0.5 -> 4.0 (every px of overhang at the face)",
             {"BRIM_FWD": 4.0}, "back"),
            ("BRIM_ROW 1 -> 0 (the brim floating above the head)",
             {"BRIM_ROW": 0}, "row"),
            ("CROWN_H 3 -> 6, CROWN_TAPER 2 -> 5 (a cone by another name)",
             {"CROWN_H": 6, "CROWN_TAPER": 5}, "low")):
        width, back, front, crown = brim_shape(**changes)
        broken = {"width": width < mannequin.HEAD + BRIM_MIN_BACK
                  + BRIM_MIN_FRONT,
                  "back": back < BRIM_MIN_BACK,
                  "front": front < BRIM_MIN_FRONT,
                  "row": not 0 < brim_row(**changes) <= mannequin.BRIM_ROW,
                  "low": crown > mannequin.CROWN_H}
        expect_true(f"...and that is false for {label}", broken[wanted])

    # -- the judge: every way a drawn garet strip fails to be a gunslinger --
    HEM_MIN_FRACTION = 0.70
    HEM_MAX_FRACTION = 0.80
    """Where the coat's hem falls between the top of the figure and the
    ground, on the LONG build. Bounded from BOTH sides on purpose: below
    0.70 it is a tunic and above 0.80 it is the reference's barrel, and a
    bound in one direction only is the half that cannot fail."""
    MASK_MAX_INSET = 2
    """Source px a mask row may fall short of the head's own width and still
    be a mask. The drawing covers the whole 8 px head, but the head's LAST
    row has rounded corners (`_figure` skips c 0 and c HEAD-1 there), so the
    mask's bottom row is legitimately 6 of 8. A mask over half a face is 4
    px and is refused."""
    COAT_MIN_SETBACK = 1.0
    """Source px the coat's SKIRT must sit behind the hip column. The
    bodice's own offset is COAT_BODICE_BACK 1.5, and the shipped frames
    measure 1.0 to 2.0 because COAT_SWING carries the hem toward the
    leading thigh. At COAT_BODICE_BACK 0 they measure 0.0 to +1.0 -- the
    coat closed over the shirt, which is the mutation this exists for."""
    COAT_MIN_FLARE = 3
    """Source px the coat's hem must be WIDER than its waist. COAT_HEM_W is
    COAT_WAIST_W + 4 in the drawing and the narrowest shipped frame keeps 4,
    so 3 is the floor; setting COAT_HEM_W equal to COAT_WAIST_W -- a coat
    with no flare at all, 701 source px changed, and a mutation that used to
    survive a full green run -- fails it."""
    COAT_MIN_SPAN = 0.45
    """Collar to hem, as a fraction of the figure. A hem raised to show leg
    and nothing else done is a TUNIC; this is the other end of that trade."""
    LONG_MIN_LEG = 9
    """Source px of leg that must show below the hem in every walk frame of
    the LONG build, counted on the DRAWN strip, so the outline's own row
    under the boot is in it. MEASURED there: long draws 10-11, standard
    7-8, original 4-5, and the author's own reference 3 of 45. The standard
    build is asserted BELOW this number in the same breath, so the axis is
    proved to be the thing that moved it."""

    def gunslinger_problems(src, layout, identity, min_leg=None,
                            hem_bounds=False):
        """Every way a drawn strip fails to wear garet's outfit: no brim
        above the head or a brim that does not overhang both ways, a mask
        that leaves the jaw or covers the eyes, no coat, a hem outside its
        bounds, a coat too short to be a coat, a closed coat with no shirt
        showing, or too little leg below the hem.

        `min_leg` None skips the leg bound and `hem_bounds` False skips the
        hem's, and the run and the jump ask for neither. Both measure from
        the LOWEST DRAWN ROW, and in a crouch or a flight frame that row is
        a boot tucked up under a coat that keeps hanging: 0.97 of the
        figure in jump frame 0, where the man has not changed shape at all.
        Those two bounds are a PROPORTION, so they are judged on the strip
        that stands on the ground. Everything else here -- the brim, the
        mask, the coat's span, the open front -- is judged in all sixteen
        frames.
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
            if not drawn:
                problems.append(f"cell {i}: nothing drawn")
                continue
            top = min(y for _x, y in drawn)
            floor = max(y for _x, y in drawn)
            coat = points("coat")
            brim = points("brim")
            mask = points("mask")
            hair = points("hair")
            # THE HEAD BOX IS THE HAIR AND THE MASK, and skin is only read
            # inside it. Skin is also the HANDS, and jump frames 2 and 3
            # throw both hands up beside the ear: judged by "skin above the
            # collar" the head grew an arm, and the brim's own overhang
            # measured -3 px on a brim nobody had touched.
            #
            # THE HAIR IS WHAT FIXES THE BOX, and the mask is only read
            # INSIDE IT: the mask's colour is also the trench COLLAR's
            # (mannequin.COAT_COLLAR_IS_MASK), which is wider than the head
            # and sits across the shoulders. Taken into the box the way it
            # was when a mask was only ever a face, it dragged the box out
            # to the shoulders and the brim's overhang measured -1 px on a
            # brim nobody had touched -- the same shape as the hands above,
            # arriving from the other side.
            if not hair:
                problems.append(f"cell {i}: no head")
                continue
            # THE HAIR FIXES THE BOX, IN BOTH AXES, and nothing else may
            # widen it. The mask's colour is ALSO the trench collar's
            # (mannequin.COAT_COLLAR_IS_MASK) and the collar is wider than
            # the head and sits across the shoulders, so a box that took the
            # mask's extent was dragged out to the shoulders and the brim's
            # overhang measured -1 px on a brim nobody had touched -- the
            # same shape as the hands below, arriving from the other side.
            # The hair is the one part only a head wears, and its fringe row
            # is the full width of the head.
            head_top = min(y for _x, y in hair)
            lo, hi = min(x for x, _y in hair), max(x for x, _y in hair)
            face_rows = range(head_top, head_top + mannequin.HEAD)
            mask_face = [p for p in mask
                         if p[1] in face_rows and lo <= p[0] <= hi]
            face = [p for p in points("skin")
                    if p[1] in face_rows and lo <= p[0] <= hi]
            head = hair + mask_face + face
            if not [p for p in brim if p[1] < head_top]:
                problems.append(f"cell {i}: no brim above the head")
            else:
                rows = {}
                for x, y in brim:
                    rows.setdefault(y, []).append(x)
                wide = max(rows, key=lambda y: len(rows[y]))
                band = [x for x, y in head if y >= wide]
                if band:
                    back = min(band) - min(rows[wide])
                    front = max(rows[wide]) - max(band)
                    if back < BRIM_MIN_BACK or front < BRIM_MIN_FRONT:
                        problems.append(
                            f"cell {i}: the brim overhangs the head by "
                            f"{back} px at the back and {front} at the face; "
                            f"it has to do both")
            # WHAT THE IMAGE CAN ANSWER ABOUT THE MASK, now that the
            # collar is drawn in the same colour on purpose: where the dark
            # STARTS relative to the face, and that it does not stop at the
            # chin. How many ROWS of it are the face and how WIDE they are
            # cannot be read off a flat image at all once the two colours
            # are one -- those are asserted on the drawing's own tags, in
            # `coat_shape` below, which is exact.
            if not mask_face:
                problems.append(f"cell {i}: no mask on the face")
            else:
                mask_top = min(y for _x, y in mask_face)
                if not face or min(y for _x, y in face) >= mask_top:
                    problems.append(f"cell {i}: the mask leaves no face "
                                    f"above it; it covers the eyes")
                elif [p for p in face if p[1] > mask_top]:
                    problems.append(f"cell {i}: skin shows BELOW the top of "
                                    f"the mask; it does not cover the jaw")
                elif not [p for p in mask if not lo <= p[0] <= hi]:
                    # ONE UNBROKEN MASS, which is the whole reason the
                    # collar wears the mask's colour: in the author's own
                    # reference the dark runs from under the single blue eye
                    # across the jaw and out over BOTH shoulders. Stopped at
                    # the head's own columns it is a band floating on a
                    # face, and on an 8 px head a band under a fringe reads
                    # as a beard.
                    problems.append(f"cell {i}: the mask stops at the head's "
                                    f"own columns; a masked man in a "
                                    f"turned-up collar is ONE dark mass out "
                                    f"across the shoulders")
            if not coat:
                problems.append(f"cell {i}: no coat")
                continue
            hem = max(y for _x, y in coat)
            # THE COAT'S TOP IS ITS COLLAR, and on a masked man the collar
            # answers to `mask`, not to `coat`. Read without it a
            # trenchcoat's span starts COAT_COLLAR_ROWS down and every span
            # bound moves under a colour change nobody meant as one.
            worn = set(mask_face)
            collar = min([y for _x, y in coat]
                         + [y for p in mask if p not in worn for y in (p[1],)])
            span = (hem - collar + 1) / (floor - top + 1)
            if span < COAT_MIN_SPAN:
                problems.append(f"cell {i}: the coat covers {span:.2f} of the "
                                f"figure; that is a tunic, not a trenchcoat")
            fraction = (hem - top) / (floor - top)
            if hem_bounds and fraction < HEM_MIN_FRACTION:
                problems.append(f"cell {i}: the hem falls at {fraction:.2f} "
                                f"of the figure, too high for a trenchcoat")
            elif hem_bounds and fraction > HEM_MAX_FRACTION:
                problems.append(f"cell {i}: the hem falls at {fraction:.2f} "
                                f"of the figure, over the legs")
            if not points("tunic"):
                problems.append(f"cell {i}: no shirt at the open front; the "
                                f"coat is drawn closed")
            if min_leg is not None and floor - hem < min_leg:
                problems.append(f"cell {i}: {floor - hem} px of leg below the "
                                f"hem, under the {min_leg} this build owes")
        return problems

    for name in ("walk", "run", "jump"):
        recipe = recipes.get_recipe(name, "garet")
        layout = recipe.layout
        # The image img2img would SEND, not one drawn here.
        sent = recipes.make_request(name, "img2img", SEED,
                                    character="garet").image_png
        image = opened(sent).convert("RGB")
        source = image.resize((layout.src_w, layout.src_h),
                              Image.Resampling.NEAREST)
        palette = {rgb for _n, rgb in source.getcolors(1 << 20)}
        allowed = {BACKGROUND_RGB} | shades_of(OUTLINE_RGB)
        for part, _rgb in GARET.colours:
            allowed |= shades_of(GARET.colour(part))
        outside = source.copy()
        for cell in layout.cells:
            sx0, sy0, sx1, sy1 = [v // layout.k for v in cell.rect_canvas]
            outside.paste(BACKGROUND_RGB, (sx0, sy0, sx1, sy1))
        expect(f"{name} for garet: the sent init wears a brim over the head "
               f"that overhangs front and back, a mask over the jaw with the "
               f"eyes left clear, and a trenchcoat whose hem falls between "
               f"its bounds over an open shirt -- in his colours only, with "
               f"NOTHING outside a cell",
               (gunslinger_problems(source, layout, GARET,
                                    LONG_MIN_LEG if name == "walk" else None,
                                    hem_bounds=name == "walk"),
                sorted(palette - allowed),
                sorted({PIN_SCOUT_PANTS, PIN_SCOUT_TUNIC} & palette),
                outside.getcolors(1 << 20)),
               ([], [], [], [(layout.src_w * layout.src_h, BACKGROUND_RGB)]))

    def built(build_name, recipe_name="walk"):
        """(the source-scale strip, its layout, that identity) for garet on
        `build_name` -- the one thing the axis changes, drawn."""
        who = dataclasses.replace(GARET, build=build_name)
        shape = recipes.build_recipe(recipe_name, who)
        png, _c = mannequin.render_init(shape.layout, shape.poses,
                                        who.as_dict(), garments=who.garments,
                                        build_name=build_name)
        return (opened(png).convert("RGB").resize(
            (shape.layout.src_w, shape.layout.src_h),
            Image.Resampling.NEAREST), shape.layout, who)

    def legs_below_hem(build_name):
        src, layout, who = built(build_name)
        out = []
        for i in range(layout.count):
            sx0, sy0, sx1, sy1 = layout.rect_src(i)
            crop = src.crop((sx0, sy0, sx1, sy1))
            drawn, coat = [], []
            for y in range(crop.height):
                for x in range(crop.width):
                    rgb = crop.getpixel((x, y))
                    if rgb == BACKGROUND_RGB:
                        continue
                    drawn.append(y)
                    if rgb in shades_of(who.colour("coat")):
                        coat.append(y)
            out.append(max(drawn) - max(coat))
        return out

    measured = {name: legs_below_hem(name) for name in model.BUILD_NAMES}
    expect("THE FLAW, FIXED AND MEASURED IN PIXELS. On the walk strip, the "
           "LONG build leaves at least LONG_MIN_LEG px of leg below the hem "
           "in every frame; the STANDARD build leaves strictly less than "
           "that, and the ORIGINAL -- the author's own proportion -- less "
           "again, at the 3-4 px his reference drew. One coat, one hem "
           "length, three hips",
           (min(measured["long"]) >= LONG_MIN_LEG,
            max(measured["standard"]) < LONG_MIN_LEG,
            max(measured["original"]) < min(measured["standard"]),
            measured),
           (True, True, True,
            {"standard": [7, 8, 7, 8, 8], "original": [4, 5, 4, 5, 5],
             "long": [10, 11, 10, 11, 11]}))
    for other in ("standard", "original"):
        src, layout, who = built(other)
        found = gunslinger_problems(src, layout, who, LONG_MIN_LEG,
                                    hem_bounds=True)
        expect_true(f"...and the SAME judge, handed the {other} build and "
                    f"asked for the long build's leg, reports the short leg "
                    f"AND a hem over it in every cell -- so both of those "
                    f"assertions can fail",
                    all(any(p.startswith(f"cell {i}: ") and w in p
                            for p in found)
                        for i in range(layout.count)
                        for w in ("the hem falls at",
                                  "px of leg below the hem")))

    # -- the other half of every new garment constant ----------------------
    def garet_problems(**changes):
        """Every problem the judge reports over ALL THREE strips with one
        constant changed, stripped of cell numbers and measurements."""
        found = set()
        for recipe_name in ("walk", "run", "jump"):
            shape = recipes.get_recipe(recipe_name, "garet")
            with contextlib.ExitStack() as stack:
                for name_, value in changes.items():
                    stack.enter_context(patched(mannequin, name_, value))
                png, _c = mannequin.render_init(
                    shape.layout, shape.poses, GARET.as_dict(),
                    garments=GARET.garments, build_name=GARET.build)
            drawn = opened(png).convert("RGB").resize(
                (shape.layout.src_w, shape.layout.src_h),
                Image.Resampling.NEAREST)
            found |= {p.split(": ", 1)[1].split(" (")[0].split(" px")[0]
                      for p in gunslinger_problems(
                          drawn, shape.layout, GARET,
                          hem_bounds=recipe_name == "walk")}
        return sorted(found)

    for label, changes, wanted in (
            ("COAT_LEN 13 -> 4 (a hem at the waist)",
             {"COAT_LEN": 4}, "the hem falls at"),
            ("COAT_LEN 13 -> 21 (the reference's barrel, hem past the sole)",
             {"COAT_LEN": 21}, "the hem falls at"),
            ("COAT_BODICE_BACK 1.5 -> 0.0 (the coat closed over the shirt)",
             {"COAT_BODICE_BACK": 0.0}, "no shirt at the open front"),
            ("MASK_TOP_ROW 5 -> 2 (a mask over the eyes)",
             {"MASK_TOP_ROW": 2}, "the mask leaves no face above it"),
            ("MASK_TOP_ROW 5 -> 4 (the mask over the eye row itself)",
             {"MASK_TOP_ROW": 4}, "skin shows BELOW the top of"),
            ("COAT_COLLAR_IS_MASK True -> False (the dark stops at the "
             "chin and the shoulders go brown)",
             {"COAT_COLLAR_IS_MASK": False}, "the mask stops at the head's"),
            ("BRIM_W 15 -> 9 (a brim narrower than its own overhang)",
             {"BRIM_W": 9}, "the brim overhangs the head by"),
            ("BRIM_FWD 0.5 -> -3.0 (the whole brim behind the face)",
             {"BRIM_FWD": -3.0}, "the brim overhangs the head by"),
            ("BRIM_ROW 1 -> 6 (the brim down at the jaw)",
             {"BRIM_ROW": 6}, "no brim above the head")):
        found = garet_problems(**changes)
        expect_true(f"the judge goes red on {label}",
                    found and any(p.startswith(wanted) for p in found))
    expect("...and reports nothing at all on the shipped constants, so those "
           "rows are the mutation and not the judge",
           garet_problems(), [])

    # -- THE COAT AND THE MASK, ON THE DRAWING'S OWN TAGS -------------------
    # Everything above reads a flat image, which is the right place to judge
    # what a generation will be judged against -- but a flat image cannot
    # answer a WIDTH question about this outfit at all. `coat` is also both
    # SLEEVES (a trenchcoat brings its own), and `mask` is also the COLLAR.
    # Measured through colour, the coat's waist is whichever arm is furthest
    # out that frame. So the widths are measured here, on `_figure`'s tags,
    # where the drawing says which pixel is which -- and this is the half
    # that was missing: FIVE drawing mutations survived a full green run,
    # including deleting the trenchcoat's collar outright (189 source px)
    # and flattening its flare (701 px), because the coat was only ever read
    # as its topmost and bottommost rows.
    def coat_shape(module=mannequin, garments=None, colours=None, **changes):
        """Per walk frame, off the tagged pixels:
        (collar width, head width, waist width, hem width, the skirt's
        x-centre minus the torso's, the mask's rows as (top, bottom) in head
        rows, the mask's narrowest row, the head's width, the collar's
        colours)."""
        wearing = GARET.garments if garments is None else garments
        palette = GARET.as_dict() if colours is None else colours
        out = []
        for pose in recipes.get_recipe("walk", "garet").poses:
            with contextlib.ExitStack() as stack:
                for name_, value in changes.items():
                    stack.enter_context(patched(module, name_, value))
                px = module._figure(pose, palette, wearing, GARET.build)
            def tagged(*names):
                return [p for p, (_rgb, tg) in px.items() if tg in names]

            def width(points):
                return (max(x for x, _y in points)
                        - min(x for x, _y in points) + 1) if points else 0
            coat = tagged("coat")
            head = tagged("head", "mask")
            mask = tagged("mask")
            top = min(y for _x, y in coat)
            collar = [p for p in coat
                      if p[1] < top + max(1, module.COAT_COLLAR_ROWS)]
            # The hip is local row 0 by construction (`_figure`: the legs
            # start at row 0 and the torso ends at row -1), so the waist and
            # the hem need no build-dependent fraction.
            waist = [p for p in coat if p[1] in (0, 1)]
            hem_y = max(y for _x, y in coat)
            hem = [p for p in coat if p[1] >= hem_y - 1]
            # AGAINST THE HIP COLUMN, which is `_figure`'s own origin
            # (`hip = (0.5, 0.0)`) and therefore cannot be occluded. The
            # visible TORSO can be: at COAT_BODICE_BACK 0 the bodice covers
            # it edge to edge and there is no torso left to measure from --
            # which is the same mutation this assertion has to catch.
            skirt = [p for p in coat if p[1] >= 0]
            centre = ((min(x for x, _y in skirt)
                       + max(x for x, _y in skirt)) / 2.0) - 0.5
            # THE EYE IS THE ANCHOR for where the mask sits, not the
            # head's own tag: `_brim_hat` is drawn OVER the head and RETAGS
            # its top two rows, so the topmost `head` pixel is head row 2.
            # The eye is also the thing the mask must leave, so measuring
            # from it says the rule out loud: one row under the eye, down
            # to the chin.
            eye = [p for p, (rgb, tg) in px.items()
                   if tg == "head" and rgb == model.OUTLINE_RGB]
            rows = {}
            for x, y in mask:
                rows.setdefault(y, []).append(x)
            out.append((width(collar), width(head), width(waist), width(hem),
                        centre,
                        (min(rows) - min(y for _x, y in eye),
                         max(rows) - min(y for _x, y in eye))
                        if rows and eye else None,
                        min((len(xs) for xs in rows.values()), default=0),
                        {px[p][0] for p in collar}))
        return out

    shape = coat_shape()
    expect("THE TRENCH COLLAR IS WIDER THAN THE MAN: in every walk frame the "
           "coat's top rows out-span the head, which is what a turned-up "
           "collar looks like and what COAT_COLLAR_W's docstring has always "
           "claimed. Nothing measured it, and deleting the collar outright "
           "-- 189 source px -- passed",
           ([(collar, head) for collar, head, *_ in shape],
            all(collar > head for collar, head, *_ in shape)),
           ([(mannequin.COAT_COLLAR_W, mannequin.HEAD)] * 5, True))
    expect("THE COAT FLARES BELOW THE HIP: its hem is at least "
           "COAT_MIN_FLARE px wider than its waist in every frame. Read "
           "through colour this cannot be measured at all -- the coat's "
           "colour is also both sleeves -- so it is measured here, and "
           "COAT_HEM_W = COAT_WAIST_W, a coat with no flare at all, used to "
           "pass",
           ([(waist, hem) for _c, _h, waist, hem, *_ in shape],
            all(hem - waist >= COAT_MIN_FLARE
                for _c, _h, waist, hem, *_ in shape)),
           ([(7, 12), (8, 12), (8, 12), (8, 12), (8, 12)], True))
    expect("THE SKIRT IS SET BACK BEHIND THE TORSO, by at least "
           "COAT_BODICE_BACK px, which is the same offset that leaves the "
           "shirt showing down the open front -- asserted on the SKIRT "
           "because `no shirt at the open front` only ever measured the "
           "bodice, and moving the skirt's root forward passed",
           ([round(row[4], 1) for row in shape],
            all(row[4] <= -COAT_MIN_SETBACK for row in shape)),
           ([-1.0, -1.0, -1.0, -1.0, -2.0], True))
    expect("THE MASK STARTS ONE ROW UNDER THE EYE AND ENDS AT THE CHIN, and "
           "covers the full width of the head on every row but the head's "
           "last, whose two corners are rounded. The eye is the one thing "
           "left of the face; the width was promised by the drawing's "
           "docstring and measured by nothing, so a mask over HALF the face "
           "passed in all sixteen frames",
           (sorted({row[5] for row in shape}),
            sorted({row[6] for row in shape}),
            all(row[6] >= row[1] - MASK_MAX_INSET for row in shape)),
           ([(1, mannequin.HEAD - 1 - mannequin.EYE_ROW)],
            [mannequin.HEAD - MASK_MAX_INSET], True))
    expect("A MASKED MAN'S COLLAR IS THE MASK'S COLOUR, in every shade it "
           "is drawn in -- that is the unbroken black from under the eye "
           "out across both shoulders, and it is the single thing that "
           "makes this figure read as the author's character rather than as "
           "a bearded prospector",
           sorted({rgb for row in shape for rgb in row[7]}
                  - shades_of(GARET.colour("mask"))), [])
    BARE_COAT = GARET.garments._replace(face="none")
    bare_palette = {part: rgb for part, rgb in GARET.as_dict().items()
                    if part != "mask"}
    expect("...and an UNMASKED coat keeps the coat's own colour, so this "
           "adds no colour part, changes no character file, and cannot be "
           "satisfied by a collar that is simply always dark",
           sorted({rgb
                   for row in coat_shape(garments=BARE_COAT,
                                         colours=bare_palette)
                   for rgb in row[7]}
                  - shades_of(GARET.colour("coat"))), [])
    for label, changes, reads in (
            ("COAT_COLLAR_W 10 -> 5 (a collar narrower than the head)",
             {"COAT_COLLAR_W": 5}, lambda r: r[0] > r[1]),
            ("COAT_COLLAR_ROWS 2 -> 0 (no collar rows at all)",
             {"COAT_COLLAR_ROWS": 0}, lambda r: r[0] > r[1]),
            ("COAT_HEM_W 12 -> 8 = COAT_WAIST_W (no flare at all)",
             {"COAT_HEM_W": mannequin.COAT_WAIST_W},
             lambda r: r[3] - r[2] >= COAT_MIN_FLARE),
            ("COAT_BODICE_BACK 1.5 -> 0.0 (the skirt on the torso's axis)",
             {"COAT_BODICE_BACK": 0.0},
             lambda r: r[4] <= -COAT_MIN_SETBACK),
            ("MASK_ROWS 3 -> 0 (no mask at all)",
             {"MASK_ROWS": 0}, lambda r: r[5] is not None),
            ("MASK_ROWS 3 -> 1 (the mouth covered, the jaw bare)",
             {"MASK_ROWS": 1},
             lambda r: r[5] == (1, mannequin.HEAD - 1 - mannequin.EYE_ROW)),
            ("COAT_COLLAR_IS_MASK True -> False (the dark stops at the chin)",
             {"COAT_COLLAR_IS_MASK": False},
             lambda r: not (r[7] - shades_of(GARET.colour("mask"))))):
        expect_true(f"...and that goes red on {label}",
                    not all(reads(row) for row in coat_shape(**changes)))
    goes_red("THE COLLAR IS DRAWN AT ALL: delete its `_segment` and the "
             "coat's top rows are the bodice, narrower than the head it is "
             "supposed to out-span -- 189 source px that used to change "
             "with the suite green",
             "tools/nai/mannequin.py",
             [("    collar = _add(back, up, torso_h - COAT_COLLAR_ROWS)\n"
               "    _segment(px, collar, up, COAT_COLLAR_ROWS, "
               "COAT_COLLAR_W,\n             lambda al, pe: collar_rgb, "
               "\"coat\")",
               "    pass")],
             lambda m: [row[0] for row in coat_shape(module=m)],
             tag="collar_deleted")
    goes_red("THE SKIRT HANGS FROM THE COAT'S OWN AXIS, NOT THE TORSO'S: "
             "root the flare at the hip's column and the set-back goes, the "
             "open front closes, and 1083 source px move with the suite "
             "green",
             "tools/nai/mannequin.py",
             [("    _flare(px, (back[0], hip[1]), (swing / fall, COAT_LEN / "
               "fall), fall,",
               "    _flare(px, (hip[0], hip[1]), (swing / fall, COAT_LEN / "
               "fall), fall,")],
             lambda m: [round(row[4], 1) for row in coat_shape(module=m)],
             tag="skirt_on_torso_axis")
    goes_red("THE MASK IS THE FULL WIDTH OF THE HEAD: mask only the back "
             "half of it and 163 source px move -- a half-face that was "
             "accepted in all sixteen frames, because nothing measured the "
             "mask's width at all",
             "tools/nai/mannequin.py",
             [("            masked = (garments.face == \"mask\"\n"
               "                      and MASK_TOP_ROW <= r < MASK_TOP_ROW + "
               "MASK_ROWS)",
               "            masked = (garments.face == \"mask\"\n"
               "                      and MASK_TOP_ROW <= r < MASK_TOP_ROW + "
               "MASK_ROWS\n                      and c < HEAD // 2)")],
             lambda m: [row[6] for row in coat_shape(module=m)],
             tag="half_mask")

    # -- the hem swings with the stride ------------------------------------
    def hem_centres(**changes):
        """Each walk frame's coat-hem centre, in source px from the hip."""
        out = []
        for pose in recipes.get_recipe("walk", "garet").poses:
            with contextlib.ExitStack() as stack:
                for name_, value in changes.items():
                    stack.enter_context(patched(mannequin, name_, value))
                px = mannequin._figure(pose, GARET.as_dict(), GARET.garments,
                                       GARET.build)
            coat = [(x, y) for (x, y), (_rgb, tag) in px.items()
                    if tag == "coat"]
            low = max(y for _x, y in coat)
            xs = [x for x, y in coat if y >= low - 1]
            out.append((min(xs) + max(xs)) / 2.0)
        return out

    expect("THE HEM SWINGS WITH THE STRIDE. The four striding frames carry "
           "their hem toward the leading thigh and the standing frame does "
           "not, so a garet at rest and a garet mid-stride are two "
           "silhouettes; at COAT_SWING 0 every frame's hem sits in the same "
           "place and the coat hangs like a board",
           (len(set(hem_centres())) > 1,
            len(set(hem_centres(COAT_SWING=0.0))) == 1),
           (True, True))


    # -- law 5 on COMPILED COPIES, not on a patched constant ---------------
    # `patched` above proves a CONSTANT matters. These four prove the CODE
    # does: each compiles a copy of the shipped mannequin.py with one
    # statement changed and asks the same question of it. `mutant`'s
    # exactly-once sentinel is what makes the row trustworthy -- a mutation
    # whose text has been reformatted away raises instead of reporting a
    # cheerful "no difference".
    GARET_POSE = recipes.get_recipe("walk", "garet").poses[0]

    def drawn_by(module, build_name=None, want="height"):
        """One measurement of garet drawn by `module`, for goes_red."""
        names = ([build_name] if build_name
                 else list(model.BUILD_NAMES))
        out = []
        for name in names:
            px = module._figure(GARET_POSE, GARET.as_dict(), GARET.garments,
                                name)
            ys = [y for _x, y in px]
            if want == "height":
                out.append(max(ys) - min(ys) + 1)
            elif want == "leg":
                hem = max(y for (_x, y), (_rgb, tag) in px.items()
                          if tag == "coat")
                out.append(max(ys) - hem)
            elif want == "near_leg":
                out.append(sum(1 for _rgb, tag in px.values()
                               if tag == "near_leg"))
        return tuple(out)

    goes_red("_bones GIVES THE TORSO BACK WHAT THE LEGS TOOK: let the legs "
             "grow and keep TORSO_H and the three builds stop drawing one "
             "height, so a `long` garet grows out of his cell instead of "
             "standing in it",
             "tools/nai/mannequin.py",
             [("    return (THIGH + chosen.thigh, SHIN + chosen.shin,\n"
               "            TORSO_H + chosen.torso)",
               "    return (THIGH + chosen.thigh, SHIN + chosen.shin,\n"
               "            TORSO_H)")],
             lambda m: drawn_by(m, want="height"), tag="bones_no_giveback")
    goes_red("THE COAT'S SKIRT HANGS FROM THE HIP, NOT THE SHOULDER: give "
             "it back the px the torso lost and its hem stops moving with "
             "the build, so all three builds show the same leg and the axis "
             "does nothing at all",
             "tools/nai/mannequin.py",
             [("    fall = math.hypot(swing, COAT_LEN)\n"
               "    _flare(px, (back[0], hip[1]), (swing / fall, COAT_LEN / "
               "fall), fall,",
               "    _len = COAT_LEN + (TORSO_H - torso_h)\n"
               "    fall = math.hypot(swing, _len)\n"
               "    _flare(px, (back[0], hip[1]), (swing / fall, _len / "
               "fall), fall,")],
             lambda m: drawn_by(m, want="leg"), tag="coat_off_shoulder")
    goes_red("THE COAT IS DRAWN AFTER THE NEAR LEG: swap them and the near "
             "leg lies on top of the coat it is supposed to be under, so "
             "the thigh shows through and there is no hem to measure from",
             "tools/nai/mannequin.py",
             [('    _leg(px, hip, pose.near_thigh, pose.near_shin, leg, shoe, "near_leg",\n         shaft=not heeled, heeled=heeled, thigh_px=thigh_px, shin_px=shin_px)\n    if coated:',
               '    if coated:'),
              ('              collar_rgb)',
               '              collar_rgb)\n    _leg(px, hip, pose.near_thigh, pose.near_shin, leg, shoe, "near_leg",\n         shaft=not heeled, heeled=heeled, thigh_px=thigh_px, shin_px=shin_px)')],
             lambda m: drawn_by(m, build_name="long", want="near_leg"),
             tag="coat_under_leg")

    def brim_overhang(module):
        out = {}
        module._brim_hat(out, 0, 0, GARET.colour("brim"))
        rows = {}
        for (x, y), _v in out.items():
            rows.setdefault(y, []).append(x)
        wide = max(rows, key=lambda y: len(rows[y]))
        return (0 - min(rows[wide]), max(rows[wide]) - (module.HEAD - 1))

    goes_red("BRIM_FWD MOVES THE BRIM TOWARD THE FACE: flip its sign and "
             "the overhang piles up at the back, which is the exact shape "
             "the wizard brim was first drawn as and had to be fixed from",
             "tools/nai/mannequin.py",
             [("    brim_axis = center + BRIM_FWD",
               "    brim_axis = center - BRIM_FWD")],
             brim_overhang, tag="brim_backwards")

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
        expect("...and evaluate agrees: no condition fails, and none warns",
               (failing(body, **kwargs), warned_conditions(body, **kwargs)),
               ([], []))

    def warned_conditions(body, *, account=ACCOUNT, proofs=(), state=CLEAN,
                          url=GENERATE_URL, probe=False):
        return [v.condition for v in guard.evaluate(
            body, account, proofs, state, url=url, probe=probe) if v.warning]

    def warns(label, condition, fragment, body, *, also=(), **kwargs):
        """SENT, with a warning: assert_free does not raise and returns
        exactly `condition` (and `also`) as warnings, `condition`'s own
        message names `fragment`, and no condition fails. A balance event
        warns and never stops (guard's module docstring, 2026-09-24)."""
        asserted.append(1)
        try:
            warned = guard.assert_free(body, kwargs.get("account", ACCOUNT),
                                       kwargs.get("proofs", ()),
                                       kwargs.get("state", CLEAN),
                                       url=kwargs.get("url", GENERATE_URL),
                                       probe=kwargs.get("probe", False))
        except Exception as exc:  # noqa: BLE001 - reporting tool
            print(f"  FAIL {label:<66} {type(exc).__name__}: {str(exc)[:120]}")
            failures.append(label)
            return
        got = (sorted(v.condition for v in warned),
               [fragment in v.message for v in warned
                if v.condition == condition],
               failing(body, **kwargs))
        want = (sorted((condition,) + tuple(also)), [True], [])
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<66} sent, WARNING "
              f"{got[0]}" + ("" if ok else f"  got={got} want={want}"))
        if not ok:
            failures.append(label)

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
    refused("...and capitalised, Rating:General, it is refused too", 7,
            "carries a rating tag",
            request.build_body(dataclasses.replace(REQ_GEN, frames=(
                dataclasses.replace(REQ_GEN.frames[0],
                                    caption="boy, Rating:General"),)
                + REQ_GEN.frames[1:])))

    def doubled(b):
        text = "Rating:general, " + b["input"]
        b["input"] = text
        b["parameters"]["v4_prompt"]["caption"]["base_caption"] = text
    refused("a second rating tag before the closing tail is refused", 7,
            "carries a rating tag before its closing",
            edited(BODY_GEN, doubled))
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
    warns("a live balance BELOW the last ledger row is SENT, warning of an "
          "AMBIGUOUS boundary -- the last row SENT a request of ours, so a "
          "late debit for it looks exactly like this", 9,
          "AMBIGUOUS BOUNDARY -- this tool CANNOT say whose spend this "
          "was: the balance fell 1000 -> 998 (2 Anlas)", BODY_GEN,
          state=CHAINED, account=dataclasses.replace(ACCOUNT, fixed=998))
    goes_red("...proved red: fail condition 9 on a fallen chain again and a "
             "friend's spend on the shared account stops every send",
             "tools/nai/guard.py",
             [("                verdicts.append(Verdict(9, True, "
               "boundaries_note(\n                    gaps, "
               "this_read=this_read), warning=True))",
               "                verdicts.append(Verdict(9, False, "
               "boundaries_note(\n                    gaps, "
               "this_read=this_read), warning=True))")],
             lambda g: [v.ok for v in g.evaluate(
                 BODY_GEN, dataclasses.replace(ACCOUNT, fixed=998), (),
                 CHAINED, url=GENERATE_URL) if v.condition == 9],
             tag="fallen_chain_refuses")
    refused("LOCK present is refused", 10, "LOCK present", BODY_GEN,
            state=LOCKED)
    refused("INFLIGHT present is refused", 10, "INFLIGHT present", BODY_GEN,
            state=INFLIGHT)
    refused("img2img without a proof row is refused", 1,
            "no proof row for (img2img, nai-diffusion-4-5-full)", BODY_I2I)
    refused("infill without a proof row is refused", 1,
            "no proof row for (infill", BODY_INF, proofs=(PROOF_I2I,))
    # ONE PROOF, BOTH VARIANTS (model.Proof.covers). The author, 2026-09-24:
    # "The curated model is in the same system, the same costs apply. So in
    # our case no costs." Each half below is proved red further down.
    BODY_I2I_CURATED = request.build_body(recipes.make_request(
        "walk", "img2img", SEED, variant="curated"))
    BODY_INF_CURATED = request.build_body(recipes.make_request(
        "walk", "infill", SEED, source_png=FLAT_PNG, cell=2,
        variant="curated"))
    passes("the full model's img2img proof stands for the curated model: "
           "NovelAI bills the two alike", BODY_I2I_CURATED,
           proofs=(PROOF_I2I,), state=PROVEN)
    passes("...and its infill proof for the curated inpainting model",
           BODY_INF_CURATED, proofs=(PROOF_INF,), state=PROVEN)
    refused("...but an img2img proof never stands for infill, on either "
            "variant", 1, "no proof row for (infill", BODY_INF_CURATED,
            proofs=(PROOF_I2I,))
    refused("a probe of the curated twin of a proven pair is refused: its "
            "proof already stands for it", 1, "already has a proof row",
            guard.probe_body("img2img", seed=SEED, variant="curated"),
            probe=True, proofs=(PROOF_I2I,))
    goes_red("...proved red: match a proof to its own model only and the "
             "curated model is refused on a proof that covers it",
             "tools/nai/guard.py",
             [("    matching = [p for p in proofs if p.covers(action, model)]",
               "    matching = [p for p in proofs if p.action == action "
               "and p.model == model]")],
             lambda g: [v.ok for v in g.evaluate(
                 BODY_I2I_CURATED, ACCOUNT, (PROOF_I2I,), PROVEN,
                 url=GENERATE_URL) if v.condition == 1],
             tag="proof_one_variant")
    goes_red("...proved red at the rule: drop the other variant from "
             "Proof.covers and the full proof covers the curated call no more",
             "tools/nai/model.py",
             [("        if self.model == model:\n            return True\n"
               "        pair = MODELS_BY_ACTION.get(action, ())\n"
               "        return self.model in pair and model in pair",
               "        return self.model == model")],
             lambda m: m.Proof("img2img", MODEL_FULL, "1216x832",
                               "2026-09-24", "p").covers("img2img",
                                                         MODEL_CURATED),
             tag="covers_one_variant")
    goes_red("...and the other half: drop the action test from Proof.covers "
             "and an img2img proof answers for a generate call of its model",
             "tools/nai/model.py",
             [("        if self.action != action:\n            return False\n",
               "        if False:\n            return False\n")],
             lambda m: m.Proof("img2img", MODEL_FULL, "1216x832",
                               "2026-09-24", "p").covers("generate",
                                                         MODEL_FULL),
             tag="covers_any_action")
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
    late_seen = [v for v in guard.evaluate(
        BODY_I2I, dataclasses.replace(ACCOUNT, fixed=998), (PROOF_I2I,), LATE,
        url=GENERATE_URL) if v.ok is not True or v.warning]
    expect("a debit landing BETWEEN the probe and the next row REFUTES the "
           "proof FOR GOOD (1) and opens the chain (9) as an AMBIGUOUS "
           "boundary -- two WARNINGS, and neither is a stop: the probe's own "
           "request went out, so risk R4's late debit and a friend's spend "
           "are byte-identical there",
           ([v.condition for v in late_seen],
            [(v.ok, v.warning) for v in late_seen],
            ["REFUTED" in v.message and "risk R4" in v.message
             for v in late_seen if v.condition == 1],
            # the fall is already written down and the read just taken is
            # level with the chain, so the note says THAT before it describes
            # the boundary: the author is never pointed at the wrong event
            [v.message.startswith("NOT the balance read just taken")
             and "AMBIGUOUS BOUNDARY" in v.message
             for v in late_seen if v.condition == 9]),
           ([1, 9], [(True, True), (True, True)], [True], [True]))
    LATE_ACKED = scratch_state("late_debit_acked")
    LATE_ACKED.write_row(probe_row(PROOF_I2I))
    LATE_ACKED.write_row(ledger_row(998, ledger_id="after-the-probe"))
    LATE_ACKED.write_row(drift_ack("ack-late", PROOF_I2I.ledger_id,
                                   "after-the-probe", 1000, 998))
    warns("...and SIGNING that boundary does not bring the proof back: the "
          "chain is re-baselined and stops warning, and condition 1 keeps "
          "warning that img2img's proof is REFUTED. THE MONEY ESCAPE: "
          "without this, one typed figure would make the action whose cost "
          "is the open question look proven free while OURS still reads 0",
          1, "REFUTED", BODY_I2I, proofs=(PROOF_I2I,), state=LATE_ACKED,
          account=dataclasses.replace(ACCOUNT, fixed=998))
    expect("...and the signature really did re-baseline the chain: condition "
           "9 passes CLEAN over the same ledger, so only condition 1 warns",
           [(v.condition, v.ok, v.warning) for v in guard.evaluate(
               BODY_I2I, dataclasses.replace(ACCOUNT, fixed=998),
               (PROOF_I2I,), LATE_ACKED, url=GENERATE_URL)
            if v.condition in (1, 9)], [(1, True, True), (9, True, False)])
    goes_red("...proved red: refuse on a refuted proof again and the shared "
             "account's own traffic stops img2img for good",
             "tools/nai/guard.py",
             [("            # THE BALANCE HALF: a warning, never a stop "
               "(module docstring).\n",
               "            return False, why\n")],
             lambda g: [v.ok for v in g.evaluate(
                 BODY_I2I, dataclasses.replace(ACCOUNT, fixed=998),
                 (PROOF_I2I,), LATE_ACKED, url=GENERATE_URL)
                 if v.condition == 1], tag="refuted_proof_refuses")
    PENDING = scratch_state("pending_proof")
    PENDING.write_row(probe_row(PROOF_I2I))
    warns("a pending proof whose next read is a refill (+50) is refuted -- a "
          "refill can hide a charge -- and the send WARNS", 1, "REFUTED",
          BODY_I2I, proofs=(PROOF_I2I,), state=PENDING,
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
    goes_red("...proved red: read the structural half as a balance event and "
             "a proof that never measured anything sends img2img with a mere "
             "warning", "tools/nai/guard.py",
             [("        never_measured = proof_problem(matching[0], rows)",
               "        never_measured = None")],
             lambda g: [v.ok for v in g.evaluate(
                 BODY_I2I, ACCOUNT, (PROOF_I2I,), hollow, url=GENERATE_URL)
                 if v.condition == 1], tag="hollow_proof_warns")

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

    warns("a CONFIRMED proof is refuted by a later img2img call charged "
          "1000 -> 992, and the send WARNS", 1,
          "REFUTED by ledger row i2i-charged", BODY_I2I,
          proofs=(PROOF_I2I,), state=ledger_of(
              "later_charged", probe_row(PROOF_I2I),
              pair_row(1000, 992, "i2i-charged")),
          account=dataclasses.replace(ACCOUNT, fixed=992))
    warns("...and by a later img2img call whose balance after was never read",
          1, "never read", BODY_I2I, proofs=(PROOF_I2I,), state=ledger_of(
              "later_unread", probe_row(PROOF_I2I),
              pair_row(1000, 1000, "i2i-unread", account_after=None,
                       delta=None, inconclusive=True)))
    LATE_AFTER_CALL = (probe_row(PROOF_I2I), pair_row(1000, 1000, "i2i-clean"),
                       pair_row(995, 995, "chain-charged", action="generate",
                                kind="refused", locked=True))
    after_call_seen = [v for v in guard.evaluate(
        BODY_I2I, dataclasses.replace(ACCOUNT, fixed=995), (PROOF_I2I,),
        ledger_of("later_late_debit", *LATE_AFTER_CALL), url=GENERATE_URL)
        if v.ok is not True or v.warning]
    expect("...and a debit landing AFTER a clean later img2img call refutes "
           "it too: that call went out, so the fall in the read that follows "
           "it is R4's own shape and cannot be told from somebody else's -- "
           "two warnings, no refusal",
           ([v.condition for v in after_call_seen],
            [(v.ok, v.warning) for v in after_call_seen],
            ["REFUTED" in v.message for v in after_call_seen]),
           ([1, 9], [(True, True), (True, True)], [True, False]))
    warns("...and signing exactly that boundary silences the chain and "
          "never the proof: a signature re-baselines the CHAIN, never a proof",
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
    warns("...but a charged img2img call of the CURATED model refutes the "
          "full model's proof: the two share it, so a charge on either is a "
          "charge on both", 1, "REFUTED by ledger row curated-charged",
          BODY_I2I, proofs=(PROOF_I2I,),
          state=ledger_of("later_other_model", probe_row(PROOF_I2I),
                          pair_row(1000, 992, "curated-charged",
                                   model=MODEL_CURATED)),
          account=dataclasses.replace(ACCOUNT, fixed=992))
    goes_red("...proved red: scan only the proof's own model for later "
             "calls and a charge on the curated twin leaves it standing",
             "tools/nai/guard.py",
             [("                and proof.covers(row.get(\"action\"), "
               "row.get(\"model\"))):",
               "                and row.get(\"action\") == proof.action\n"
               "                and row.get(\"model\") == proof.model):")],
             lambda g: g.proof_standing(
                 PROOF_I2I, [probe_row(PROOF_I2I),
                             pair_row(1000, 992, "curated-charged",
                                      model=MODEL_CURATED)], 992)[0],
             tag="later_scan_one_variant")
    passes("...while a charged INFILL call of the curated inpainting model "
           "leaves an img2img proof standing: one action never covers the "
           "other", BODY_I2I, proofs=(PROOF_I2I,),
           state=ledger_of("later_other_action", probe_row(PROOF_I2I),
                           pair_row(1000, 992, "inf-curated-charged",
                                    action="infill",
                                    model=MODEL_CURATED_INPAINTING)),
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
    PROOF_I2I_CURATED = Proof("img2img", MODEL_CURATED, "1216x832",
                              "2026-09-24", "probe-i2i-curated")
    TWINNED = scratch_state("proof_twin")
    TWINNED.add_proof(PROOF_I2I)
    expect_raises("proofs.json refuses a proof for the curated twin of a "
                  "proven pair: the first already covers it", ValueError,
                  lambda: TWINNED.add_proof(PROOF_I2I_CURATED),
                  "already exists", "(img2img, nai-diffusion-4-5-full)")
    TWINNED.add_proof(PROOF_INF)
    expect("...while a proof of the other action is added beside it",
           [(p.action, p.model) for p in TWINNED.proofs()],
           [("img2img", MODEL_FULL), ("infill", MODEL_FULL_INPAINTING)])
    goes_red("...proved red: refuse only an identical pair and proofs.json "
             "takes a second proof for what the first already covers",
             "tools/nai/state.py",
             [("            if known.covers(proof.action, proof.model):",
               "            if (known.action, known.model) == "
               "(proof.action, proof.model):")],
             lambda s: (lambda twin: outcome(
                 lambda: twin.add_proof(PROOF_I2I) or
                 twin.add_proof(PROOF_I2I_CURATED)) is None)(
                 s.State(scratch_state("proof_twin_mutant").root)),
             tag="add_proof_exact_pair")

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

    # -- NOTHING WRITES LOCK: a balance event is a warning in its row -------
    def lock_calls(source: str) -> list[int]:
        """Line numbers of every `<anything>.lock(...)` call in `source`."""
        return [node.lineno for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "lock"]

    nai_dir = os.path.join(_bootstrap.REPO_ROOT, "tools", "nai")
    callers = {}
    for name in sorted(os.listdir(nai_dir)):
        if name.endswith(".py"):
            with io.open(os.path.join(nai_dir, name), encoding="utf-8") as handle:
                found = lock_calls(handle.read())
            if found:
                callers[name] = found
    expect("no module under tools/nai/ calls .lock(): LOCK is only ever the "
           "author's own emergency stop, placed by hand",
           (callers, lock_calls("state.lock(ledger_id, 'reason')\n")),
           ({}, [1]))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(), sub(998)])
    expect("a decrease across the call is a WARNING in its own row -- OUR "
           "charge, measured inside it -- and writes no LOCK",
           (pattern, row["delta"], row["locked"], st.locked(),
            "OUR CHARGE, measured INSIDE" in (row["warning"] or "")),
           ([GET, POST, GET], -2, False, False, True))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(998), zipped(), sub(998)],
                                         state=st)
    expect("...and the next call is SENT: a warning never stops anything, "
           "and this one met no new balance event, so it carries none",
           (exc, pattern, len(st.rows()), (row or {}).get("warning", "no row")),
           (None, [GET, POST, GET], 2, None))

    def charged_lock(module):
        """What LOCK a module's run_request leaves after a charged send."""
        module.reset_latch_for_checks()
        made = scratch_state("mutant_charge")
        module.run_request(REQ_GEN, tp.RecordingTransport(
            [sub(1000), zipped(), sub(990)]), made)
        return made.locked()
    goes_red("...proved red: write LOCK on a charge again and the next send "
             "is stopped by a balance event", "tools/nai/run.py",
             [("                warnings.append(reason)\n",
               "                warnings.append(reason)\n"
               "                state.lock(ledger_id, reason)\n")],
             charged_lock, tag="charge_locks_again")
    between = scratch_state("between_calls")
    between.write_row(ledger_row(1000))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(998), zipped(), sub(998)],
                                        state=between)
    expect("a charge landing BETWEEN invocations: SENT, and the row's warning "
           "names the AMBIGUOUS boundary with its figure -- no LOCK, and no "
           "refused row in front of it",
           (exc, pattern, st.locked(), [r["kind"] for r in st.rows()],
            "AMBIGUOUS BOUNDARY" in ((row or {}).get("warning") or ""),
            "(2 Anlas)" in ((row or {}).get("warning") or "")),
           (None, [GET, POST, GET], False, ["generation", "generation"], True,
            True))

    def fallen_chain_send(module):
        """What a module's run_request does with a read below the chain."""
        module.reset_latch_for_checks()
        made = scratch_state("mutant_chain")
        made.write_row(ledger_row(1000))
        transport = tp.RecordingTransport([sub(998), zipped(), sub(998)])
        try:
            module.run_request(REQ_GEN, transport, made)
        except guard.Refused as refusal:
            return f"refused ({refusal.condition})"
        return f"{len(transport.posts)} POST"
    goes_red("...proved red: refuse on a fallen chain again and a friend's "
             "spend stops the next send", "tools/nai/run.py",
             [("        warnings.append(\n            _chain_note(",
               "        raise Refused(9, 'a fallen chain')\n"
               "        warnings.append(\n            _chain_note(")],
             fallen_chain_send, tag="chain_refuses_again")
    unread = scratch_state("unread_after")
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(),
                                                  error(500, "down")],
                                        state=unread)
    expect("a failed balance read AFTER the send: the row is written with "
           "its warning, INFLIGHT released, the failure raised -- no LOCK",
           (pattern, type(exc).__name__, st.locked(), st.inflight(),
            st.rows()[-1]["account_after"] if st.rows() else "no row",
            "zero cost cannot be shown" in (st.rows()[-1]["warning"] or "")
            if st.rows() else False),
           ([GET, POST, GET], "AccountReadError", False, False, None, True))
    goes_red("...proved red: key the failed-after-read rule on LOCK again and "
             "that ledger raises on every later call, since nothing writes "
             "LOCK any more", "tools/nai/state.py",
             [("                and (last.get(\"inconclusive\") is True\n"
               "                     or last.get(\"locked\") is True)):",
               "                and last.get(\"locked\") is True):")],
             lambda s: str(outcome(lambda: s.State(unread.root)
                                   .last_balance()))[:30],
             tag="unread_keyed_on_lock")
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(1000), zipped(),
                                                   sub(1000)], state=unread)
    expect("...and the next call chains on that row's balance BEFORE (1000), "
           "the last one anybody read: sent, with nothing to warn about",
           (exc, pattern, (row or {}).get("warning", "no row")),
           (None, [GET, POST, GET], None))
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
    for label, script, warned in (
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
        expect(f"probe, {label}: NO proof row, no LOCK, and a warning "
               f"exactly when the balance fell",
               (pattern, st.proofs(), st.locked(),
                bool((row or {}).get("warning"))),
               ([GET, POST, GET], (), False, warned))
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

    def warning_of(row) -> str:
        return (row or {}).get("warning") or ""

    for action, req, probe_req in (("img2img", REQ_I2I, probe_i2i),
                                   ("infill", REQ_INF, probe_inf)):
        seq = proven_pair(f"charged_{action}", probe_req)
        t, _st, row, exc, pattern = scripted(req, [sub(1000), zipped(),
                                                   sub(992)], state=seq)
        expect(f"a production {action} charged 1000 -> 992 after its proof: "
               f"its own row's warning says '{action} is charged', no LOCK",
               (pattern, row["delta"] if row else exc,
                f"{action} is charged" in warning_of(row), seq.locked()),
               ([GET, POST, GET], -8, True, False))
        t, _st, row, exc, pattern = scripted(req, [sub(992), zipped(),
                                                   sub(992)], state=seq)
        expect(f"...and the next {action} is SENT, warning that its proof is "
               f"REFUTED: a warning never stops a send",
               (exc, "REFUTED" in warning_of(row), pattern),
               (None, True, [GET, POST, GET]))
    seq = proven_pair("unread_img2img")
    scripted(REQ_I2I, [sub(1000), zipped(), error(500, "down")], state=seq)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(1000), zipped(),
                                                   sub(1000)], state=seq)
    expect("a production img2img whose after-read failed refutes the proof: "
           "the next img2img is SENT, warning 'never read', and no LOCK",
           (exc, "never read" in warning_of(row), pattern, seq.locked()),
           (None, True, [GET, POST, GET], False))
    seq = proven_pair("late_after_img2img")
    scripted(REQ_I2I, [sub(1000), zipped(), sub(1000)], state=seq)
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("a debit landing AFTER a clean production img2img: the next call "
           "is SENT, and its warning names the AMBIGUOUS boundary and the "
           "proof it refutes FOR GOOD -- it never says 'img2img is charged', "
           "because nothing measured that, and never calls the drop "
           "somebody else's",
           (exc, pattern, "AMBIGUOUS BOUNDARY" in warning_of(row),
            "REFUTES its proof" in warning_of(row),
            "img2img is charged" in warning_of(row),
            "EXTERNAL DRIFT" in warning_of(row), seq.locked()),
           (None, [GET, POST, GET], True, True, False, False, False))
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...img2img is SENT too, warning about the UNSIGNED boundary (9) "
           "AND the refuted proof (1)",
           (exc, "AMBIGUOUS BOUNDARY" in warning_of(row),
            "REFUTED" in warning_of(row), pattern),
           (None, True, True, [GET, POST, GET]))
    ack_code, _ack_out = acknowledge(seq)
    expect("...signing it writes no LOCK: there is nothing to lift",
           (ack_code, seq.locked()), (0, False))
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and once signed the boundary stops warning, while img2img "
           "still warns on its refuted proof: the signature re-baselined the "
           "CHAIN and never the proof, so the question of its cost stays on "
           "the books",
           (exc, "AMBIGUOUS BOUNDARY" in warning_of(row),
            "REFUTED" in warning_of(row), pattern),
           (None, False, True, [GET, POST, GET]))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...while generate, which never needed a proof, sends with no "
           "warning at all", (exc, pattern, (row or {}).get("warning")),
           (None, [GET, POST, GET], None))
    seq = proven_pair("late_after_generate")
    scripted(REQ_GEN, [sub(1000), zipped(), sub(1000)], state=seq)
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("but a debit landing after a GENERATE call names no proof in its "
           "warning", (exc, "AMBIGUOUS BOUNDARY" in warning_of(row),
                       "REFUTES its proof" in warning_of(row)),
           (None, True, False))
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and img2img warns only about the unsigned boundary, never "
           "its proof: the fall sits behind a GENERATE row, so nothing "
           "about the img2img probe moved",
           (exc, "AMBIGUOUS BOUNDARY" in warning_of(row),
            "REFUTED" in warning_of(row)), (None, True, False))
    acknowledge(seq)
    t, _st, row, exc, pattern = scripted(REQ_I2I, [sub(995), zipped(),
                                                   sub(995)], state=seq)
    expect("...and once that boundary is signed img2img is sent with no "
           "warning at all: the proof stood the whole time",
           (exc, pattern, (row or {}).get("warning")),
           (None, [GET, POST, GET], None))
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
           "a warning in the row, no LOCK",
           (pattern, row["account_before"]["sum"], row["delta"],
            row["locked"], st.locked(), "OUR CHARGE" in warning_of(row)),
           ([GET, POST, GET], 1000, -2, False, False, True))
    t, st, row, exc, pattern = scripted(REQ_GEN, [sub_split(500, 500), zipped(),
                                                  sub_split(0, 1000)])
    expect("subscription Anlas converted into paid Anlas is no change: delta "
           "0, no LOCK, no warning", (row["delta"], st.locked(), row["warning"]),
           (0, False, None))
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
    expect("a rise across the call (+50) is recorded inconclusive, no LOCK, "
           "no warning",
           (row["delta"], row["inconclusive"], row["locked"], st.locked(),
            row["warning"]), (50, True, False, False, None))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(1048), zipped(),
                                                   sub(1048)], state=st)
    expect("...and the next read chains on that row's AFTER (1050): 1048 is a "
           "fall, SENT with the boundary in its warning",
           (exc, pattern, st.locked(), "1050 -> 1048" in warning_of(row)),
           (None, [GET, POST, GET], False, True))

    # -- an interrupt cannot skip the after-read or the row, and it warns ---
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
    expect("Ctrl-C during the POST: the after-read and the row happen, the "
           "row warns, THEN it is re-raised -- no LOCK",
           (raised, pattern, len(t.responses), [r["delta"] for r in rows],
            [r["locked"] for r in rows],
            ["interrupted" in (r["warning"] or "") for r in rows],
            st.locked(), st.inflight()),
           ("KeyboardInterrupt", [GET, POST, GET], 0, [-17], [False], [True],
            False, False))
    t, st, raised, pattern = interrupted(REQ_GEN, [sub(1000), KeyboardInterrupt(),
                                                   sub(1000)])
    expect("...with no visible charge it still WARNS: the outcome is unknown",
           (raised, [r["delta"] for r in st.rows()],
            ["interrupted" in (r["warning"] or "") for r in st.rows()],
            st.inflight()), ("KeyboardInterrupt", [0], [True], False))
    t, st, raised, pattern = interrupted(REQ_GEN, [sub(1000), zipped(),
                                                   KeyboardInterrupt()])
    expect("Ctrl-C during the after-read: the row (after null) with its "
           "warning, INFLIGHT released, then re-raised -- no LOCK",
           (raised, pattern, [r["account_after"] for r in st.rows()],
            ["zero cost cannot be shown" in (r["warning"] or "")
             for r in st.rows()], st.locked(), st.inflight()),
           ("KeyboardInterrupt", [GET, POST, GET], [None], [True], False,
            False))
    t, _st, row, exc, pattern = scripted(REQ_GEN, [sub(983), zipped(),
                                                   sub(983)], state=st)
    expect("...and on that once-empty ledger the next read still catches the "
           "17: SENT, with the fall in its warning",
           (exc, pattern, st.locked(), "1000 -> 983" in warning_of(row)),
           (None, [GET, POST, GET], False, True))
    t, st, raised, pattern = interrupted(
        guard.probe_request("img2img", seed=SEED),
        [sub(1000), KeyboardInterrupt(), sub(1000)], probe=True,
        context=LedgerContext(strip="walk", phase="probe",
                              probe_flag_used=True))
    expect("an interrupted probe writes no proof, even at delta 0",
           (raised, st.proofs(), st.locked()), ("KeyboardInterrupt", (), False))

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
    expect("...and through run_request: recorded, the row written with the "
           "fall as its warning, INFLIGHT released, nothing raised, no LOCK",
           (exc, pattern, "bad response" in (row or {}).get("error_message", ""),
            (row or {}).get("delta"), (row or {}).get("output_path"),
            len(st.rows()), st.locked(), st.inflight(),
            "OUR CHARGE" in warning_of(row)),
           (None, [GET, POST, GET], True, -17, None, 1, False, False, True))
    expect("a warning longer than a ledger string is cut with the command "
           "that prints it whole; a short one is kept as it is; none is null",
           (len(run._warning_text(["x" * 5000])),
            run._warning_text(["x" * 5000]).endswith(
                "prints every open boundary in full]"),
            run._warning_text(["short"]), run._warning_text([])),
           (nai_state.MAX_ROW_STRING, True, "short", None))

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
        expect("an after-read failure echoing the key: exit 1, no LOCK",
               (code, leak.locked()), (1, False))
        seen_before = len(FAKE.seen)
        code, text = cli_send(leak, [sub(1000), zipped(), sub(1000)])
        expect("...and the next run is SENT: it chains on the last balance "
               "anybody read and asks the account, the generator and the "
               "account once each",
               (code, len(FAKE.seen) - seen_before), (0, 3))
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
        expect("a charge through urllib: exit 0 with the WARNING printed, and "
               "no LOCK",
               (code, "WARNING       OUR CHARGE" in text, charged.locked()),
               (0, True, False))
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

    # A SHAPED mask -- NovelAI takes any shape of whole latent blocks (the
    # author, 2026-09-25) -- here an L. The corner of its bounding box that
    # the L leaves out is OUTSIDE the mask: composite keeps it and
    # differs_outside sees a change there.
    ell = Image.new("RGBA", (L5.width, L5.height), (0, 0, 0, 255))
    for box in ((64, 64, 192, 128), (64, 128, 128, 256)):
        ell.paste((255, 255, 255, 255), box)
    ELL = png_bytes(ell)
    ell_inside = ell.convert("RGB").convert("L")
    corner, leg = (160, 200), (100, 200)

    def blanked_by(image, inside):
        copy_ = image.copy()
        copy_.paste((0, 0, 0), (0, 0) + image.size, inside)
        return copy_.tobytes()
    merged_l = opened(masks.composite(INIT_PNG, returned, ELL)).convert("RGB")
    expect("composite through an L: every pixel outside the L -- the corner "
           "of its box included -- is the original's",
           (blanked_by(merged_l, ell_inside) == blanked_by(original, ell_inside),
            merged_l.getpixel(corner) == original.getpixel(corner)),
           (True, True))
    expect("composite through an L: a pixel inside it is the returned image's",
           merged_l.getpixel(leg), (10, 200, 30))

    def touched_at(point):
        touched = original.copy()
        r, g, b = touched.getpixel(point)
        touched.putpixel(point, (255 - r, 255 - g, 255 - b))
        return png_bytes(touched)
    for label, point, want in (("in the L's box but outside the L", corner, True),
                               ("inside the L", leg, False)):
        expect(f"differs_outside through an L: one pixel {label} -> {want}",
               masks.differs_outside(INIT_PNG, touched_at(point), ELL), want)
    split = ell.copy()
    split.paste((255, 255, 255, 255), (300, 300, 304, 308))
    expect_raises("composite through a mask that splits a latent block is "
                  "refused", ValueError,
                  lambda: masks.composite(INIT_PNG, returned, png_bytes(split)),
                  "splits the 8 px latent block at (296, 296)")
    goes_red("...proved red: let composite paste the mask's bounding box and "
             "the corner the L leaves out is repainted", "tools/nai/masks.py",
             [("    result.paste(returned, (0, 0), inside)\n",
               "    result.paste(returned.crop(inside.getbbox()), "
               "inside.getbbox()[:2])\n")],
             lambda module: opened(module.composite(
                 INIT_PNG, returned, ELL)).convert("RGB").getpixel(corner),
             tag="composite_shape")
    goes_red("...proved red: let differs_outside blank the mask's bounding box "
             "and a change in the L's corner goes unseen", "tools/nai/masks.py",
             [("    a.paste(MASK_KEEP_RGB, full, inside)\n"
               "    b.paste(MASK_KEEP_RGB, full, inside)\n",
               "    a.paste(MASK_KEEP_RGB, inside.getbbox())\n"
               "    b.paste(MASK_KEEP_RGB, inside.getbbox())\n")],
             lambda module: module.differs_outside(
                 INIT_PNG, touched_at(corner), ELL),
             tag="differs_shape")

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
                               str(SEED)], tp.RecordingTransport(
                                   [sub(998), zipped(), sub(998)]), r4)
    expect("R4 via the CLI: a debit landing BETWEEN the probe and the next "
           "read is an AMBIGUOUS boundary -- SENT, exit 0, and the printed "
           "WARNING names the proof it refutes FOR GOOD rather than calling "
           "the drop external",
           (code, [p.action for p in r4.proofs()],
            "AMBIGUOUS BOUNDARY" in out, "REFUTES its proof" in out,
            "EXTERNAL DRIFT" in out, r4.locked()),
           (0, ["img2img"], True, True, False, False))
    recorder = tp.RecordingTransport([sub(998), zipped(), sub(998)])
    code, out, err = cli_call(["run", "walk", "--action", "img2img", "--seed",
                               str(SEED)], recorder, r4)
    expect("...production img2img is SENT as well, warning about the "
           "unsigned boundary AND the refutation",
           (code, "AMBIGUOUS BOUNDARY" in out, "REFUTED" in out,
            [c.method for c in recorder.calls]),
           (0, True, True, ["GET", "POST", "GET"]))
    ack_code, ack_out = acknowledge(r4)
    recorder = tp.RecordingTransport([sub(998), zipped(), sub(998)])
    code, out, err = cli_call(["run", "walk", "--action", "img2img", "--seed",
                               str(SEED)], recorder, r4)
    expect("...and once the boundary is SIGNED the books say so on their own "
           "lines and the chain stops warning -- while img2img still warns "
           "that its proof is REFUTED: the signature cleared the chain, not "
           "the proof, and the command said which proof stayed refuted "
           "while it wrote the row",
           (ack_code, "ours spent    +0 Anlas" in ack_out,
            "theirs        -2 Anlas" in ack_out,
            "REFUTED for good" in ack_out, code,
            "AMBIGUOUS BOUNDARY" in out, "REFUTED" in out,
            [c.method for c in recorder.calls]),
           (0, True, True, True, 0, False, True, ["GET", "POST", "GET"]))
    expect("...and THAT is the money escape closed: the one function the "
           "guard asks still reads the proof as refuted, so a typed figure "
           "never makes img2img look proven free while `ours` reads 0",
           guard.proof_standing(r4.proofs()[0], r4.rows(), 998)[0], False)

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

    # -- a charged production img2img: plan and run WARN, and send ---------
    charged_cli = scratch_state("charged_after_proof_cli")
    i2i_argv = ["walk", "--action", "img2img", "--strength", "0.55", "--seed",
                str(SEED)]
    cli_call(["probe", "img2img", "--accept-max-2-anlas", "--seed", str(SEED)],
             tp.RecordingTransport([sub(1000), zipped(), sub(1000)]),
             charged_cli)
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(992)])
    code, out, err = cli_call(["run"] + i2i_argv, recorder, charged_cli)
    expect("run img2img charged 1000 -> 992 after its proof: exit 0, one POST, "
           "the printed WARNING says img2img is charged, and no LOCK",
           (code, len(recorder.posts), "img2img is charged" in out,
            charged_cli.locked()), (0, 1, True, False))
    code, out, err = cli_call(["plan"] + i2i_argv, None, charged_cli)
    expect("...plan img2img passes offline WITH a warning (exit 0): condition "
           "1 marked WARNING and REFUTED, never 'confirmed by'",
           (code, "every offline condition passes, with 1 WARNING(s)" in out,
            "   1 [ok, WARNING]" in out, "REFUTED by ledger row" in out,
            "confirmed by" in out), (0, True, True, True, False))
    recorder = tp.RecordingTransport([sub(992), zipped(), sub(984)])
    code, out, err = cli_call(["run"] + i2i_argv, recorder, charged_cli)
    expect("...and run img2img is SENT again, exit 0, one POST -- charged "
           "again, and warned again",
           (code, [c.method for c in recorder.calls], "OUR CHARGE" in out),
           (0, ["GET", "POST", "GET"], True))

    # -- every sending command prints the balances, a bad ZIP included -------
    code, out, err = cli_call(["run", "walk", "--action", "generate", "--seed",
                               str(SEED)], tp.RecordingTransport([
                                   sub(1000), (200, {}, corrupt_zip()),
                                   sub(983)]), scratch_state("corrupt_cli"))
    expect("a corrupt deflate stream via the CLI: exit 1, the balance line "
           "and the WARNING printed",
           (code, "balance       before 1000 -> after 983, delta -17" in out,
            "WARNING       OUR CHARGE" in out), (1, True, True))

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
    # ours: a warning in that row, the proof refuted for good, and nothing
    # here may soften it. Neither kind stops a send any more (the author's
    # decision, 2026-09-24: the account is shared) -- both are MEASURED,
    # printed and kept on the books. BETWEEN two rows it is a BOUNDARY, and the only
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
        said = (row_c or {}).get("warning") or ""
        expect(f"run_request WARNS on a charge inside its own row, {label}: "
               f"the row's warning says WHICH measurement that was, and no "
               f"LOCK is written",
               (row_c["delta"], row_c["locked"], st_c.locked(), exc_c,
                "OUR CHARGE, measured INSIDE" in said,
                "`acknowledge-drift` cannot touch it" in said,
                "EXTERNAL DRIFT" in said),
               (-10, False, False, None, True, True, False))

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
    expect("...and after all five signatures img2img's proof is STILL "
           "refuted for good: condition 1 warns, condition 9 is clean. THE "
           "ESCAPE, closed: under the reading an earlier pass replaced, the "
           "same five figures re-armed it as proven while `ours` read 0",
           (guard.proof_standing(LATE_PROOF, LATE_STATE.rows(), None)[0],
            [(v.ok, v.warning) for v in guard.evaluate(
                BODY_I2I, Account(3, True, None, 950, 0), (LATE_PROOF,),
                LATE_STATE, url=GENERATE_URL) if v.condition in (1, 9)]),
           (False, [(True, True), (True, False)]))
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

    # -- (i) the warning names the drop THIS call saw, with its own figure --
    OLD_GAP = stated(scratch_state("old_gap"),
                     gen_row("old-a", 10000, 10000,
                             utc="2026-09-17T09:00:00.000000Z"),
                     refused_row("old-b", 8000,
                                 utc="2026-09-17T12:00:00.000000Z"),
                     gen_row("new-a", 8000, 8000,
                             utc="2026-09-17T12:30:00.000000Z"))
    _t, _st, _row, exc, pattern = scripted(REQ_GEN, [sub(7990), zipped(),
                                                     sub(7990)],
                                           state=OLD_GAP)
    message = warning_of(_row)
    expect("a call that sees 8000 -> 7990 is told about THAT, first, with "
           "the 10 it saw -- and the older 2000 gap is listed after it. The "
           "live LOCK an earlier pass was written against blamed a drop from "
           "three hours earlier and printed its figure instead",
           (exc, "8000 -> 7990" in message and "old-a->old-b (-2000)" in message
            and message.index("8000 -> 7990")
            < message.index("old-a->old-b (-2000)"),
            "(10 Anlas)" in message, "1 OTHER unsigned boundary" in message,
            "-2000 Anlas in all" in message),
           (None, True, True, True, True))
    expect("...and the command it prints for the drop just seen names the "
           "row that recorded it -- this call's own row -- so it can "
           "actually be typed",
           (f"--observed {(_row or {}).get('ledger_id')}" in message,
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
            "EXTERNAL DRIFT" in printed), (0, True, False, False))
    expect("...and its last line is a WHOLE-STATE verdict: the open boundary "
           "is IN it as a WARNING, so 'nothing outstanding' never sits on "
           "the same screen as an open boundary",
           ("verdict       free tier usable, sends go ahead -- WARNING: "
            in printed, "nothing outstanding" in printed), (True, False))
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
           "with money missing SAYS SO: condition 9 is marked WARNING beside "
           "the boundary and the verdict counts it -- it used to print "
           "'every offline condition passes' over books it had not read",
           (code, " 9 [needs the live account read, WARNING]" in printed,
            "every offline condition passes, with 1 WARNING(s)" in printed,
            "AMBIGUOUS BOUNDARY" in printed), (0, True, True, True))
    goes_red("...proved red: skip the ledger half offline and plan gives a "
             "clean bill over an open boundary", "tools/nai/guard.py",
             [("    if gaps:\n        return Verdict(9, None, "
               "boundaries_note(gaps, this_read=False),\n"
               "                       warning=True)",
               "    if gaps and False:\n        return Verdict(9, None, "
               "boundaries_note(gaps, this_read=False),\n"
               "                       warning=True)")],
             lambda g: [(v.ok, v.warning) for v in g.evaluate(
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
    expect("signing NEVER deletes LOCK: nothing in the package writes one, "
           "so a LOCK is the author's own emergency stop and only the "
           "author lifts it",
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
    expect("the warning text names the last row that SENT something, never "
           "a signature annotation sitting at the end of the ledger",
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

    # =======================================================================
    print("\n8c. request files: another way in, the same builder, guard and "
          "send")
    # =======================================================================
    REQUEST_FILES = os.path.join(SCRATCH, "request_files")
    os.makedirs(REQUEST_FILES)
    TAIL = ", very aesthetic, masterpiece, no text, rating:general"
    DROP = object()

    def request_file(doc=None, *, raw=None, images=None):
        """A request file in a folder of its own, with `images` (name ->
        bytes) written beside it; its path."""
        folder = tempfile.mkdtemp(dir=REQUEST_FILES)
        for name, data in (images or {}).items():
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(data)
        path = os.path.join(folder, "request.json")
        with open(path, "wb") as handle:
            handle.write(raw if raw is not None
                         else json.dumps(doc, indent=1).encode("utf-8"))
        return path

    def as_file(req):
        """The request file that states exactly what a recipe's `req`
        states, and the images it names."""
        doc = {"format": "pyoneer.nai.request", "version": 1,
               "action": req.action,
               "variant": "curated" if "curated" in req.model else "full",
               "width": req.width, "height": req.height, "seed": req.seed,
               "steps": req.steps, "scale": req.scale,
               "prompt": req.base_caption[:-len(TAIL)],
               "negative": req.negative,
               "characters": [{"prompt": f.caption, "uc": f.uc,
                               "center": list(f.center)} for f in req.frames]}
        images = {}
        if req.action == "img2img":
            doc.update(image="init.png", strength=req.strength,
                       noise=req.noise, color_correct=req.color_correct)
            images["init.png"] = req.image_png
        elif req.action == "infill":
            doc.update(image="init.png", mask="mask.png",
                       inpaint_strength=req.inpaint_strength, noise=req.noise)
            images.update({"init.png": req.image_png,
                           "mask.png": req.mask_png})
        return doc, images

    expect("every recipe request closes its base caption with the tail a "
           "request file leaves to tools.nai (brief 3.2, pinned here)",
           [req.base_caption.endswith(TAIL) for _l, req, _b in BODIES],
           [True, True, True])
    for label, req, body in BODIES:
        doc, images = as_file(req)
        loaded = outcome(lambda: spec.load(request_file(doc, images=images)))
        expect(f"a request file stating the recipe's {label} builds the SAME "
               f"body as recipes.make_request, key for key",
               getattr(loaded, "request", None) is not None
               and request.build_body(loaded.request) == body, True)
    doc, images = as_file(REQ_INF)
    loaded = spec.load(request_file(doc, images=images))
    expect("...and the infill file's mask rectangle is cell 2's, as the "
           "ledger's target_rect, exactly what context_for gives the recipe",
           (loaded.mask_rect, loaded.context.target_rect),
           (rect2, recipes.context_for("walk", cell=2).target_rect))

    # -- a slice: the shape the Pioneer Pixel Editor writes -------------------
    SLICE_W, SLICE_H = 384, 512
    SLICE_RECT = (48, 64, 336, 448)
    slice_image = Image.new("RGB", (SLICE_W, SLICE_H), (128, 128, 128))
    slice_image.paste((90, 60, 30), SLICE_RECT)
    SLICE_PNG = png_bytes(slice_image)

    def mask_png(*rects, mode="RGBA", size=(SLICE_W, SLICE_H)):
        """Black, with each rect white: pinned here, not model's colours."""
        mask = Image.new(mode, size, (0, 0, 0, 255)[:len(mode)])
        for rect in rects:
            mask.paste((255, 255, 255, 255)[:len(mode)], rect)
        return png_bytes(mask)
    SLICE_MASK = mask_png(SLICE_RECT)
    SLICE_IMAGES = {"init.png": SLICE_PNG, "mask.png": SLICE_MASK}

    def slice_doc(action, /, **changes):
        """A legal slice for `action`, then `changes` (DROP removes a key).
        Positional-only, so a change may itself be spelled `action=`."""
        doc = {"format": "pyoneer.nai.request", "version": 1,
               "action": action, "variant": "full",
               "width": SLICE_W, "height": SLICE_H, "seed": SEED,
               "steps": 23, "scale": 5,
               "prompt": "pixel art, 1boy, full body, from side, grey "
                         "background",
               "negative": "nsfw, lowres",
               "characters": [{"prompt": "boy, brown hair, red scarf",
                               "uc": "", "center": [0.5, 0.5]}],
               "label": "a slice",
               "source": {"app": "check_nai", "rect": [6, 8, 36, 48]}}
        if action == "img2img":
            doc.update(image="init.png", strength=0.45, noise=0.05,
                       color_correct=False)
        elif action == "infill":
            doc.update(image="init.png", mask="mask.png",
                       inpaint_strength=0.45, noise=0.0)
        for key, value in changes.items():
            if value is DROP:
                doc.pop(key, None)
            else:
                doc[key] = value
        return doc

    def slice_file(action, /, images=None, **changes):
        return request_file(slice_doc(action, **changes),
                            images=SLICE_IMAGES if images is None else images)

    generated = spec.load(slice_file("generate"))
    expect("a generate slice loads: ONE tail appended, the V4.5 model, the "
           "pipeline's sampler and schedule, the model's 'none' preset, no "
           "image, no rectangle, no strip, its label (pinned from brief 1.5)",
           (generated.request.base_caption, generated.request.model,
            generated.request.sampler, generated.request.noise_schedule,
            generated.request.ucPreset, generated.request.image_png,
            generated.mask_rect, generated.context.strip, generated.label),
           ("pixel art, 1boy, full body, from side, grey background" + TAIL,
            "nai-diffusion-4-5-full", "k_euler_ancestral", "karras", 4, None,
            None, None, "a slice"))
    expect("...a trailing comma in the prompt still gives one ', ' before the "
           "tail, never ', , '",
           spec.load(slice_file(
               "generate", prompt="pixel art, 1boy ,  ")).request.base_caption,
           "pixel art, 1boy" + TAIL)
    inpainted = spec.load(slice_file("infill", variant="curated"))
    expect("an infill slice loads: the curated inpainting model and its "
           "preset, the mask's own rectangle as target_rect, image and mask "
           "exactly as written",
           (inpainted.request.model, inpainted.request.ucPreset,
            inpainted.mask_rect, inpainted.context.target_rect,
            inpainted.request.image_png == SLICE_PNG,
            inpainted.request.mask_png == SLICE_MASK,
            inpainted.request.inpaint_strength, inpainted.request.noise),
           ("nai-diffusion-4-5-curated-inpainting", 3, SLICE_RECT, SLICE_RECT,
            True, True, 0.45, 0.0))
    # NovelAI takes the whole image and a mask of ANY shape (the author,
    # 2026-09-25); only a latent block split between repaint and keep is
    # refused. Two separate rectangles on the grid are one legal mask.
    two_blocks = mask_png((0, 0, 64, 64), (128, 128, 192, 192))
    shaped = spec.load(slice_file(
        "infill", images={"init.png": SLICE_PNG, "mask.png": two_blocks}))
    expect("a mask of two separate latent-aligned rectangles loads, its "
           "bounding box the target_rect and the mask itself sent",
           (shaped.mask_rect, shaped.context.target_rect,
            shaped.request.mask_png == two_blocks),
           ((0, 0, 192, 192), (0, 0, 192, 192), True))
    ledgered = spec.load(slice_file("generate", round=3, phase="slices",
                                    lever="L4"))
    expect("round, phase and lever reach the LedgerContext; strip stays None",
           (ledgered.context.round, ledgered.context.phase,
            ledgered.context.lever_changed, ledgered.context.strip),
           (3, "slices", "L4", None))
    inline = spec.load(slice_file(
        "infill", images={},
        image="base64:" + base64.b64encode(SLICE_PNG).decode("ascii"),
        mask="base64:" + base64.b64encode(SLICE_MASK).decode("ascii")))
    expect("the same images carried inline as base64: the same body",
           request.build_body(inline.request)
           == request.build_body(spec.load(slice_file("infill")).request),
           True)
    opaque = spec.load(slice_file(
        "img2img", images={"init.png": png_bytes(slice_image.convert("RGBA"))}))
    expect("an opaque RGBA image is accepted and sent as RGB, pixel for pixel",
           (opened(opaque.request.image_png).mode,
            opened(opaque.request.image_png).tobytes()
            == slice_image.tobytes()), ("RGB", True))

    # -- what the GUARD decides is not decided here ---------------------------
    expect("29 steps, 1,114,112 px and a width off the 64 grid all LOAD: "
           "conditions 4 and 3 are the guard's, judged by plan-request below",
           (spec.load(slice_file("generate", steps=29)).request.steps,
            outcome(lambda: spec.load(slice_file(
                "generate", width=1088, height=1024)).request.width),
            outcome(lambda: spec.load(slice_file(
                "generate", width=100)).request.width)),
           (29, 1088, 100))

    # -- every refusal names the file and the key -----------------------------
    transparent = slice_image.convert("RGBA")
    transparent.putpixel((0, 0), (128, 128, 128, 0))
    wrong_size = png_bytes(Image.new("RGB", (SLICE_W, SLICE_W), (1, 2, 3)))
    seven = [{"prompt": "boy", "uc": "", "center": [x, y]}
             for x in (0.1, 0.3, 0.5, 0.7) for y in (0.1, 0.3)][:7]
    REFUSED_FILES = (
        ("an unknown key: a sampler", "generate", None,
         {"sampler": "k_dpmpp_2m"}, ("key 'sampler'", "unknown key(s)")),
        ("a missing seed", "generate", None, {"seed": DROP},
         ("key 'seed'", "missing key(s) ['seed']")),
        ("another format", "generate", None, {"format": "pyoneer.recipe"},
         ("key 'format'",)),
        ("version 2", "generate", None, {"version": 2},
         ("key 'version'", "reads version 1")),
        ("an unknown action", "generate", None, {"action": "upscale"},
         ("key 'action'",)),
        ("a V5 variant", "generate", None, {"variant": "v5"},
         ("key 'variant'",)),
        ("generate carrying an image", "generate", None,
         {"image": "init.png"}, ("key 'image'", "do not belong to generate")),
        ("img2img carrying a mask", "img2img", None, {"mask": "mask.png"},
         ("key 'mask'", "do not belong to img2img")),
        ("img2img without its strength", "img2img", None,
         {"strength": DROP}, ("key 'strength'", "nothing is defaulted")),
        ("infill without its noise", "infill", None, {"noise": DROP},
         ("key 'noise'", "nothing is defaulted")),
        ("a seed of 1", "generate", None, {"seed": 1},
         ("key 'seed'", "[2, 4294967287]")),
        ("a seed past the top", "generate", None, {"seed": 4294967288},
         ("key 'seed'", "[2, 4294967287]")),
        ("a seed of true", "generate", None, {"seed": True},
         ("key 'seed'", "must be an int")),
        ("steps as a string", "generate", None, {"steps": "23"},
         ("key 'steps'", "steps must be an int")),
        ("a scale of 0", "generate", None, {"scale": 0},
         ("key 'scale'", "scale must be > 0")),
        ("img2img strength 0.56", "img2img", None, {"strength": 0.56},
         ("key 'strength'", "outside the author's band")),
        ("img2img strength 0.34", "img2img", None, {"strength": 0.34},
         ("key 'strength'", "outside the author's band")),
        ("infill strength 0.9", "infill", None, {"inpaint_strength": 0.9},
         ("key 'inpaint_strength'", "(full repaint)")),
        ("noise 1.0", "img2img", None, {"noise": 1.0},
         ("key 'noise'", "noise must lie in")),
        ("color_correct 1", "img2img", None, {"color_correct": 1},
         ("key 'color_correct'", "must be a bool")),
        ("a prompt carrying rating:general", "generate", None,
         {"prompt": "pixel art, rating:general"},
         ("key 'prompt'", "rating tag")),
        ("a prompt carrying Rating:General, capitalised", "generate", None,
         {"prompt": "pixel art, Rating:General"},
         ("key 'prompt'", "rating tag")),
        ("a character prompt carrying RATING :explicit", "generate", None,
         {"characters": [{"prompt": "boy, RATING :explicit", "uc": "",
                          "center": [0.5, 0.5]}]},
         ("key 'characters[0]'", "'prompt' carries a rating tag")),
        ("a blank prompt", "generate", None, {"prompt": "  "},
         ("key 'prompt'", "empty")),
        ("a prompt of commas", "generate", None, {"prompt": " , ,"},
         ("key 'prompt'", "nothing but commas")),
        ("a negative that is not text", "generate", None, {"negative": None},
         ("key 'negative'", "must be a string")),
        ("no characters", "generate", None, {"characters": []},
         ("key 'characters'", "1 to 6")),
        ("seven characters", "generate", None, {"characters": seven},
         ("key 'characters'", "1 to 6")),
        ("a center off the grid", "generate", None,
         {"characters": [{"prompt": "boy", "uc": "", "center": [0.4, 0.5]}]},
         ("key 'characters[0]'", "'center'")),
        ("two characters on one cell", "generate", None,
         {"characters": [{"prompt": "boy", "uc": "", "center": [0.5, 0.5]},
                         {"prompt": "girl", "uc": "",
                          "center": [0.5, 0.5]}]},
         ("key 'characters[1]'", "shares the center")),
        ("a character with a key of its own", "generate", None,
         {"characters": [{"prompt": "boy", "uc": "", "center": [0.5, 0.5],
                          "weight": 1}]},
         ("key 'characters[0]'", "exactly")),
        ("a rating tag in a character's UC", "generate", None,
         {"characters": [{"prompt": "boy", "uc": "rating:explicit",
                          "center": [0.5, 0.5]}]},
         ("key 'characters[0]'", "'uc' carries a rating tag")),
        ("an image path up a directory", "img2img", None,
         {"image": os.path.join("..", "init.png")},
         ("key 'image'", "not a bare file name")),
        ("an image path into a folder", "img2img", None,
         {"image": "images/init.png"},
         ("key 'image'", "not a bare file name")),
        ("an absolute image path", "img2img", None,
         {"image": os.path.join(SCRATCH, "init.png")},
         ("key 'image'", "not a bare file name")),
        ("an image that is not there", "img2img", None, {"image": "gone.png"},
         ("key 'image'", "cannot be read")),
        ("an image that is not base64", "img2img", None,
         {"image": "base64:not base64!"}, ("key 'image'", "not valid base64")),
        ("an image of the wrong size", "img2img",
         {"init.png": wrong_size}, {}, ("key 'image'", "384x512")),
        ("an image with one transparent pixel", "img2img",
         {"init.png": png_bytes(transparent)}, {},
         ("key 'image'", "refused rather than flattened")),
        ("a mask off the 8 px grid", "infill",
         {"init.png": SLICE_PNG, "mask.png": mask_png((52, 64, 336, 448))},
         {}, ("key 'mask'", "splits the 8 px latent block at (48, 64)")),
        ("a mask whose second rectangle splits a latent block", "infill",
         {"init.png": SLICE_PNG,
          "mask.png": mask_png((0, 0, 64, 64), (130, 128, 192, 192))},
         {}, ("key 'mask'", "splits the 8 px latent block at (128, 128)")),
        ("a mask in RGB", "infill",
         {"init.png": SLICE_PNG, "mask.png": mask_png(SLICE_RECT,
                                                      mode="RGB")},
         {}, ("key 'mask'", "RGBA PNG")),
        ("a mask that repaints nothing", "infill",
         {"init.png": SLICE_PNG, "mask.png": mask_png()}, {},
         ("key 'mask'", "repaints nothing")),
        ("a label that is a number", "generate", None, {"label": 3},
         ("key 'label'", "must be a string")),
        ("a source that is a list", "generate", None, {"source": [1, 2]},
         ("key 'source'", "must be an object")),
        ("a negative round", "generate", None, {"round": -1},
         ("key 'round'",)),
        ("an empty phase", "generate", None, {"phase": ""},
         ("key 'phase'",)),
    )
    for label, action, images, changes, fragments in REFUSED_FILES:
        path = slice_file(action, images=images, **changes)
        expect_raises(f"refused: {label}", ValueError,
                      lambda p=path: spec.load(p),
                      f"request file {os.path.normpath(path)}", *fragments)
    for label, raw, fragment in (
            ("bytes that are not UTF-8", b"\xff\xfe{}", "is not UTF-8"),
            ("text that is not JSON", b"{\"format\": ", "is not valid JSON"),
            ("a key written twice", b'{"seed": 2, "seed": 3}',
             "duplicate key"),
            ("a list, not an object", b"[]", "one JSON object")):
        path = request_file(raw=raw)
        expect_raises(f"refused: {label}", ValueError,
                      lambda p=path: spec.load(p),
                      f"request file {os.path.normpath(path)}", fragment)

    # -- ONE RULE, TWO ROUTES: spec has no copy of its own --------------------
    def spec_through(name, path):
        """goes_red's call: load `path` with spec's `name` module replaced."""
        def call(module):
            with patched(spec, name, module):
                result = outcome(lambda: spec.load(path))
            return ("loads" if isinstance(result, spec.Spec)
                    else str(result).split(": ", 2)[-1][:48])
        return call
    goes_red("...proved red: widen recipes' ONE img2img band and the file "
             "route accepts 0.56 as well", "tools/nai/recipes.py",
             [("    if not _in_band(strength):\n", "    if False:\n")],
             spec_through("recipes",
                          slice_file("img2img", strength=0.56)),
             tag="spec_band")
    goes_red("...proved red: let characters' ONE decode rule keep a duplicate "
             "key and the request file loads with it",
             "tools/nai/characters.py",
             [("            raise _DuplicateKey(key)\n",
               "            pass\n")],
             spec_through("characters", request_file(
                 raw=json.dumps(slice_doc("generate"))[:-1].encode("utf-8")
                 + b', "seed": 7}')),
             tag="spec_duplicates")
    goes_red("...proved red: drop masks.region_of's latent-block rule and an "
             "unaligned mask loads", "tools/nai/masks.py",
             [("        if mean not in (0, 255):\n",
               "        if False:\n")],
             spec_through("masks", slice_file(
                 "infill", images={"init.png": SLICE_PNG,
                                   "mask.png": mask_png((52, 64, 336, 448))})),
             tag="spec_mask_grid")

    # -- ONE RATING RULE, EVERY ROUTE: model.rating_tag_in is asked, never
    # RATING_RX itself. The file route once searched the raw text, so
    # "Rating:General" passed spec and the guard and went out as a second
    # rating tag.
    def rating_rule_use(text: str) -> tuple[bool, bool]:
        """(names RATING_RX, calls rating_tag_in) in Python source `text`."""
        names = calls = False
        for node in ast.walk(ast.parse(text)):
            if (isinstance(node, ast.Name) and node.id == "RATING_RX"
                    or isinstance(node, ast.Attribute)
                    and node.attr == "RATING_RX"):
                names = True
            if isinstance(node, ast.Call):
                func = node.func
                called = (func.id if isinstance(func, ast.Name)
                          else func.attr if isinstance(func, ast.Attribute)
                          else "")
                calls = calls or called == "rating_tag_in"
        return names, calls

    def source_of(relpath: str) -> str:
        with io.open(os.path.join(_bootstrap.REPO_ROOT, relpath),
                     encoding="utf-8") as handle:
            return handle.read()

    nai_modules = sorted(
        f"tools/{package}/{name}" for package in ("nai", "nai_ui")
        for name in os.listdir(os.path.join(_bootstrap.REPO_ROOT, "tools",
                                            package))
        if name.endswith(".py"))
    expect("no module under tools/nai or tools/nai_ui but model.py names "
           "RATING_RX", [rel for rel in nai_modules
                         if rel != "tools/nai/model.py"
                         and rating_rule_use(source_of(rel))[0]], [])
    rating_routes = ("tools/nai/model.py", "tools/nai/recipes.py",
                     "tools/nai/characters.py", "tools/nai/spec.py",
                     "tools/nai/guard.py")
    expect("...and the recipe, the character file, the request file and guard "
           "condition 7 all ask rating_tag_in",
           [rel for rel in rating_routes
            if not rating_rule_use(source_of(rel))[1]], [])
    expect("...proved red: a route that searches RATING_RX itself again is "
           "seen", rating_rule_use(source_of("tools/nai/spec.py").replace(
               "rating_tag_in(prompt)", "RATING_RX.search(prompt)")),
           (True, True))
    goes_red("...proved red: search the raw text in rating_tag_in and "
             "Rating:General is no rating tag", "tools/nai/model.py",
             [("    return RATING_RX.search(text.lower()) is not None\n",
               "    return RATING_RX.search(text) is not None\n")],
             lambda m: m.rating_tag_in("pixel art, Rating:General"),
             tag="rating_case")

    # -- through the CLI --------------------------------------------------------
    def from_model(out):
        """plan's printout from its `model` line on: the judgement itself."""
        at = out.find("\nmodel ")
        return out[at:] if at >= 0 else None
    doc, images = as_file(REQ_GEN)
    walk_file = request_file(doc, images=images)
    _code, plan_out, _err = cli_call(plan_argv, None,
                                     scratch_state("plan_beside_request"))
    NoTransport.built = 0
    request_plan_state = scratch_state("plan_request")
    code, out, err = cli_call(["plan-request", walk_file], None,
                              request_plan_state)
    expect("plan-request of the file stating the walk's generate prints "
           "exactly what plan prints from the model line on -- request sha256 "
           "and every verdict -- exit 0, no transport built, nothing written",
           (code, from_model(out) is not None
            and from_model(out) == from_model(plan_out),
            NoTransport.built, f"seed          {SEED} (the file's)" in out,
            os.path.exists(request_plan_state.root)),
           (0, True, 0, True, False))
    for label, changes, condition in (
            ("29 steps", {"steps": 29}, 4),
            ("1,114,112 px", {"width": 1088, "height": 1024}, 3),
            ("a width of 100", {"width": 100}, 3)):
        code, out, err = cli_call(
            ["plan-request", slice_file("generate", **changes)], None,
            scratch_state("plan_request_guard"))
        failed = [line.split("[")[0].strip() for line in out.splitlines()
                  if "[FAIL]" in line]
        expect(f"plan-request of {label}: REFUSED offline by condition "
               f"{condition} alone, exit 2",
               (code, "REFUSED offline" in out, failed),
               (2, True, [str(condition)]))
    code, out, err = cli_call(
        ["plan-request", slice_file("img2img")], None,
        scratch_state("plan_request_unproven"))
    expect("plan-request of an img2img slice with no proof row: condition 1 "
           "FAILS offline, exit 2 -- a file does not skip the probe",
           (code, [line.split("[")[0].strip() for line in out.splitlines()
                   if "[FAIL]" in line]), (2, ["1"]))
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
    code, out, err = cli_call(
        ["plan-request", slice_file("generate", sampler="k_dpmpp_2m")],
        recorder, scratch_state("plan_request_refused"))
    expect("plan-request of a file spec refuses: exit 1, the file and the key "
           "on stderr, stdout empty, nothing asked of the transport",
           (code, "request file" in err and "key 'sampler'" in err, out,
            recorder.calls), (1, True, "", []))

    SLICE_OUT = Image.new("RGB", (SLICE_W, SLICE_H), (10, 200, 10))
    run_state = scratch_state("run_request")
    generate_file = slice_file("generate", round=2, phase="slices",
                               lever="L1")
    recorder = tp.RecordingTransport([sub(1000), (200, {}, tp.fake_zip(
        png_bytes(SLICE_OUT))), sub(1000)])
    code, out, err = cli_call(["run-request", generate_file], recorder,
                              run_state)
    expect("run-request of a generate slice: GET, ONE POST, GET; the POSTed "
           "body is build_body of what spec.load returns; one generation row "
           "with strip None and the file's round, phase and lever; exit 0",
           (code, [(c.method, c.url) for c in recorder.calls],
            [p.body == request.build_body(spec.load(generate_file).request)
             for p in recorder.posts],
            [(r["kind"], r["strip"], r["round"], r["phase"],
              r["lever_changed"]) for r in run_state.rows()]),
           (0, [GET, POST, GET], [True],
            [("generation", None, 2, "slices", "L1")]))
    expect("...and it prints the ledger id, both balances and the output "
           "path, like every sending command",
           ["ledger id" in out, "balance       before 1000 -> after 1000"
            in out, "output" in out], [True, True, True])
    unproven_state = scratch_state("run_request_unproven")
    recorder = tp.RecordingTransport([sub(1000), zipped(), sub(1000)])
    code, out, err = cli_call(["run-request", slice_file("img2img")],
                              recorder, unproven_state)
    expect("run-request of an img2img slice with no proof row: one balance "
           "read, NO POST, a refused row for condition 1, exit 2",
           (code, [(c.method, c.url) for c in recorder.calls],
            [(r["kind"], r["refusal_condition"])
             for r in unproven_state.rows()]),
           (2, [GET], [("refused", 1)]))

    infill_request_state = scratch_state("run_request_infill")
    code, out, err = cli_call(
        ["probe", "infill", "--accept-max-2-anlas", "--seed", str(SEED)],
        tp.RecordingTransport([sub(1000), zipped(), sub(1000)]),
        infill_request_state)
    expect("infill track for request files: the author's probe writes its "
           "proof first", (code, [(p.action, p.model) for p in
                                  infill_request_state.proofs()]),
           (0, [("infill", MODEL_FULL_INPAINTING)]))
    RETURNED_SLICE = Image.new("RGB", (SLICE_W, SLICE_H), (200, 30, 160))
    recorder = tp.RecordingTransport([sub(1000), (200, {}, tp.fake_zip(
        png_bytes(RETURNED_SLICE))), sub(1000)])
    code, out, err = cli_call(["run-request", slice_file("infill")], recorder,
                              infill_request_state)
    kept = None
    for line in out.splitlines():
        if line.startswith("composite"):
            with open(line.split(None, 1)[1], "rb") as handle:
                kept = opened(handle.read()).convert("RGB")
    want_kept = slice_image.copy()
    want_kept.paste((200, 30, 160), SLICE_RECT)
    last = infill_request_state.rows()[-1]
    expect("run-request of an infill slice: ONE POST of the file's own image "
           "and mask; the kept composite is the image with the RETURNED "
           "rectangle; the row records its mask and that the return differed "
           "outside it; exit 0",
           (code, len(recorder.posts),
            getattr(kept, "tobytes", lambda: None)() == want_kept.tobytes(),
            last["mask_png_sha256"] == hashlib.sha256(SLICE_MASK).hexdigest(),
            last["init_png_sha256"] == hashlib.sha256(SLICE_PNG).hexdigest(),
            last["differs_outside_mask"]),
           (0, 1, True, True, True, True))
    faithful_slice = slice_image.copy()
    faithful_slice.paste((200, 30, 160), SLICE_RECT)
    recorder = tp.RecordingTransport([sub(1000), (200, {}, tp.fake_zip(
        png_bytes(faithful_slice))), sub(1000)])
    code, out, err = cli_call(["run-request", slice_file("infill")], recorder,
                              infill_request_state)
    expect("...and a return that changed only the rectangle is recorded as "
           "not differing outside it",
           (code, infill_request_state.rows()[-1]["differs_outside_mask"]),
           (0, False))
    goes_red("...proved red: without _print_composite's 2xx gate a refused "
             "run-request would still try to composite",
             "tools/nai/cli.py",
             [("    if not (isinstance(status, int) and 200 <= status < 300\n"
               "            and row.get(\"output_png_sha256\")):\n"
               "        return\n",
               "    if False:\n        return\n")],
             lambda m: outcome(lambda: m._print_composite(
                 {"http_status": None}, infill_request_state, SLICE_PNG,
                 SLICE_RECT)),
             tag="composite_gate")

    NoTransport.built = 0
    code, out, err = cli_call(["request-catalog"], None,
                              scratch_state("request_catalog"))
    catalog = outcome(lambda: json.loads(out))
    expect("request-catalog prints spec.catalog() as JSON, exit 0, no "
           "transport built",
           (code, catalog == json.loads(json.dumps(spec.catalog())),
            NoTransport.built), (0, True, 0))
    limits = catalog["limits"] if isinstance(catalog, dict) else {}
    expect("the catalog carries the free-tier numbers of brief 2.1-2.2 and "
           "the grid of 4.1, pinned here",
           (limits.get("max_area"), limits.get("max_steps"),
            limits.get("dim_multiple"), limits.get("min_dim"),
            limits.get("seed_min"), limits.get("seed_max"),
            limits.get("max_characters"), limits.get("mask_align"),
            catalog.get("grid") if isinstance(catalog, dict) else None,
            catalog.get("background") if isinstance(catalog, dict) else None),
           (1048576, 28, 64, 64, 2, 4294967287, 6, 8,
            [0.1, 0.3, 0.5, 0.7, 0.9], "#808080"))
    CONTROL_KEYS = {"variant", "prompt", "negative", "characters", "steps",
                    "scale", "seed", "image", "mask", "strength", "noise",
                    "color_correct", "inpaint_strength"}
    form_keys = {row.key for row in spec.FORM if row.key}
    expect("every request-file key a person sets is a row of the form, and "
           "no row writes a key the file cannot hold",
           (sorted(CONTROL_KEYS - form_keys),
            sorted(form_keys - set(spec.FIELDS))), ([], []))
    expect("every capped, derived or locked row says why, and no editable "
           "row carries a reason; every state, column and action is legal",
           [row.label for row in spec.FORM
            if (row.state == spec.EDITABLE) == bool(row.reason)
            or row.state not in spec.STATES
            or row.column not in ("left", "right", "cost")
            or not set(row.actions) <= set(model.ACTIONS)], [])
    expect("the controls a request file has no key for are LOCKED on the "
           "form: sampler, schedule, rescale, Variety+, Decrisper, SMEA, "
           "batch, quality tags, presets, vibe, reference",
           sorted(row.label for row in spec.FORM if row.state == spec.LOCKED),
           sorted(["Model: V5 Full / Curated", "Add Quality Tags",
                   "Undesired Content presets", "AI's Choice / Custom",
                   "Vibe Transfer", "Precise Reference", "Number of Images",
                   "Prompt Guidance Rescale", "Variety+", "Decrisper", "SMEA",
                   "Sampler", "Noise Schedule", "Overlay Original Image"]))

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
