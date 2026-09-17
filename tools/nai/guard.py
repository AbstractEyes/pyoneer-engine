"""The free-tier guard: every refuse-to-send condition, in one place.

OWNER: implementer A.

RESPONSIBILITY
--------------
Decide, from a built body, an account read, the proof rows and the local
state files, whether a generation request is in the free class and may be
sent (brief 2.2 conditions 1-11). `evaluate` returns one verdict per
condition; `assert_free` raises on the first failure; `plan` (offline) and
`run` (online) both go through `evaluate`, so there is ONE implementation of
each condition and a mutation of any one turns both routes red.

INVARIANTS
----------
* PURE. Nothing here writes a file, opens a socket or reads the environment.
  The guard READS `state` (LOCK, INFLIGHT, last balance) and never writes it;
  writing LOCK is `run.run_request`'s job, driven by `chain_verdict`.
* JUDGES THE BODY, NOT THE REQUEST. The conditions read the dict that will be
  serialised, so a body edited after `request.build_body` is still judged.
* A CONDITION THAT CANNOT BE CHECKED IS NOT A PASS. `evaluate` without an
  account reports conditions 8 and 9 as ok=None; `assert_free` requires an
  account and refuses any ok that is not exactly True.
* SIZE RULE (task override of brief 2.2 #3's DESIGN clause): ANY width and
  height that are ints, multiples of 64, each >= 64, with area <= MAX_AREA,
  are allowed. There is no preset list and no size-keyed proof.
* PROBES ARE NARROW. `probe=True` waives only condition 1's proof
  requirement, only for img2img/infill, only for a body in probe shape
  (steps == PROBE_STEPS, strength or the INPAINT_STRENGTH_KEY value ==
  PROBE_STRENGTH), and only while no proof row exists for that pair yet.
  For infill EVERY strength the body carries (top-level strength, the
  INPAINT_STRENGTH_KEY value, the nested img2img strength) must equal
  PROBE_STRENGTH, since any of them could be the one the server charges by.
* Condition 12 (one generation per process) is not here: it is a process
  latch in `run.run_request`. Its number is reserved in CONDITION_TITLES.
* Condition 6 also requires every characterPrompts entry to carry
  `enabled: true`: a disabled box would make the three arrays mean different
  things while staying the same length.
* THE KEYS BELONG TO THE ACTION. Condition 1 reads model.ACTION_BODY_KEYS
  before any proof: a generate body carrying image, mask or a strength, an
  img2img body carrying a mask or the inpaint strength, an infill body
  without its mask -- each is refused, because condition 1's proof gate is
  keyed on the action string alone and would otherwise wave such a body
  through as the action it claims to be.
* A PROOF NAMES A PROBE THAT MEASURED SOMETHING. `probe_row_problem` is the
  ONE rule for "this probe row proves its pair free": 2xx, an image_*.png of
  the requested size extracted and stored, delta 0, no LOCK. `run.run_request`
  writes a proof only when it answers None for the row just written, and
  `proof_standing` counts a proof only when it answers None for the row the
  proof names -- so a 2xx carrying an HTML page, an empty body, a 204 or JSON
  proves nothing on either route.
* A PROOF COUNTS ONLY WHEN THE CHAIN CONFIRMS IT. A probe with delta 0 writes
  a proof row at once, but a debit can land after the probe's own after-read
  (risk R4). `proof_standing` accepts a proof only when the balance read that
  FOLLOWS the probe -- the next ledger row's account_before, or, while there
  is none, the read being judged -- equals the probe's account_after. Any
  other value refutes it for good (a refill can hide a charge), and a proof
  naming no probe row of its own pair in the ledger counts for nothing.
* A LATER CHARGE REFUTES IT TOO. Every `generation` row of the proof's
  (action, model) after its probe is scanned: a balance that fell across it,
  a balance after it that was never read, or a balance lower at the read
  that follows it (a late debit) refutes the proof for good. A confirmed
  proof is evidence about the account at the time of the probe, not a
  licence the account's own later answer cannot withdraw.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

from tools.nai.model import (ACTION_BODY_KEYS, ACTIONS, ALLOWED_ENDPOINTS,
                             DIM_MULTIPLE, IMG2IMG_KEY, INFILL_FULL_REPAINT,
                             INPAINT_STRENGTH_KEY, MAX_AREA, MAX_FRAMES,
                             MAX_STEPS, MIN_DIM, MODELS_BY_ACTION, N_SAMPLES,
                             NEVER_SEND_KEYS, NEVER_SEND_PREFIXES, OPUS_TIER,
                             PROBE_STEPS, PROBE_STRENGTH, PROOF_ACTIONS,
                             QUALITY_TAIL, TOKEN_BUDGET, TOKENS_PER_WORD,
                             UC_PRESET_NONE, Account, Proof, Request,
                             model_for, on_grid)

if TYPE_CHECKING:  # state imports Refused from here; no runtime cycle
    from tools.nai.state import State

CONDITION_TITLES: Mapping[int, str] = {
    1: "action is generate/img2img/infill, its keys match it; img2img and "
       "infill need a confirmed proof row",
    2: "model is a V4.5 id legal for the action",
    3: "width and height are multiples of 64, each >= 64, area <= 1048576",
    4: "steps <= 28 and n_samples == 1",
    5: "no reference, vibe, stream, image_format, sm or tag_hint key",
    6: "1..6 frames, centers on the grid and distinct, arrays parallel",
    7: "ASCII captions, token budget, rating:general closes the base caption",
    8: "account is Opus (tier 3), active, not in grace period",
    9: "balance chain unbroken: before == previous after, or a refill",
    10: "no LOCK file and no INFLIGHT file",
    11: "endpoint is POST https://image.novelai.net/ai/generate-image",
    12: "one generation request per process (run.run_request latch)",
}

OFFLINE_CONDITIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 10, 11)
"""What `plan` can judge with no network: everything but 8 and 9."""


class Refused(Exception):
    """A request was refused before any byte was sent.

    `condition` is the brief 2.2 number (1-12); `message` says what was
    wrong in terms of the body, never quoting a credential (the guard never
    sees one). str(): "refused (condition N): message".
    """

    def __init__(self, condition: int, message: str) -> None:
        super().__init__(condition, message)
        self.condition = condition
        self.message = message

    def __str__(self) -> str:
        return f"refused (condition {self.condition}): {self.message}"


@dataclass(frozen=True)
class Verdict:
    """One condition's outcome. `ok` is True, False, or None (not checked)."""
    condition: int
    ok: bool | None
    message: str


def chain_verdict(previous_after: int | None, before: int) -> str:
    """Classify a balance read against the previous ledger row (2.2 #9).

    Returns "first" when previous_after is None (empty ledger), "ok" when
    equal, "refill" when before > previous_after, "charged" when
    before < previous_after. Pure; `run.run_request` writes LOCK on
    "charged" and `evaluate` fails condition 9 on it.
    """
    if previous_after is None:
        return "first"
    if before == previous_after:
        return "ok"
    if before > previous_after:
        return "refill"
    return "charged"


def _row_sum(row: Mapping[str, object], key: str) -> int | None:
    account = row.get(key)
    if isinstance(account, Mapping):
        total = account.get("sum")
        if isinstance(total, int) and not isinstance(total, bool):
            return total
    return None


def probe_row_problem(row: Mapping[str, object]) -> str | None:
    """Why ledger `row` cannot prove its (action, model) free; None when it can.

    THE ONE RULE (module docstring): `run.run_request` writes a proof only
    when this answers None for the probe row it just wrote, and
    `proof_standing` counts a proof only when this answers None for the row
    the proof names. A row proves only when ALL of these hold:
      * kind "generation" and verdict "probe", for an action in
        PROOF_ACTIONS;
      * http_status an int in 200..299;
      * output_png_sha256 a non-empty string -- `transport.unzip_image`
        extracted an image_*.png of the requested size and it was stored. A
        2xx carrying an HTML page, an empty body, a 204 or JSON shows no
        generation happened, so its unchanged balance measures nothing;
      * integer account_before.sum and account_after.sum that are equal, and
        delta exactly 0;
      * locked is not True (an interrupted probe proves nothing, whatever
        its delta).
    Pure.
    """
    if not (row.get("kind") == "generation" and row.get("verdict") == "probe"
            and row.get("action") in PROOF_ACTIONS):
        return (f"it is not a {'/'.join(PROOF_ACTIONS)} probe row (kind "
                f"{row.get('kind')!r}, verdict {row.get('verdict')!r}, action "
                f"{row.get('action')!r})")
    status = row.get("http_status")
    if not (_is_int(status) and 200 <= status < 300):
        return f"its HTTP status is {status!r}, not 2xx"
    output = row.get("output_png_sha256")
    if not (isinstance(output, str) and output):
        return ("no image was extracted from its response, so nothing shows a "
                "generation happened")
    before = _row_sum(row, "account_before")
    after = _row_sum(row, "account_after")
    delta = row.get("delta")
    if before is None or after is None:
        return "it has no integer balance before and after"
    if not (after == before and _is_int(delta) and delta == 0):
        return (f"its balance went {before} -> {after} (delta {delta!r}), "
                f"not unchanged")
    if row.get("locked") is True:
        return "it wrote LOCK"
    return None


def proof_standing(proof: Proof, rows: Sequence[Mapping[str, object]],
                   current_sum: int | None) -> tuple[bool | None, str]:
    """Whether the balance chain confirms `proof` (module docstring).

    `rows` is the ledger in file order; `current_sum` is the balance read
    being judged, or None offline. Returns (True, why) when confirmed,
    (None, why) when only the next balance read can tell (offline, no row
    after the probe yet), (False, why) otherwise:
      * no row in `rows` has the proof's ledger_id, or that row is not a
        `generation` row with verdict "probe" for the proof's (action,
        model), or `probe_row_problem` finds it proves nothing (no 2xx, no
        extracted image, a balance that moved, LOCK);
      * the row after the probe row has an account_before.sum that is not
        the probe's account_after.sum (a late charge, or a refill that can
        hide one) -- refuted for good;
      * there is no row after it and `current_sum` differs from the probe's
        account_after.sum;
      * any LATER `generation` row of the same (action, model) -- the one
        that confirmed the probe included -- has an account_after.sum below
        its account_before.sum, or a negative delta, or no integer
        account_after.sum at all (its after-read failed); or the balance
        read that follows it (the next row's account_before.sum, or
        `current_sum` when it is the last row) is below its
        account_after.sum -- refuted for good. A rise across or after such
        a call does NOT refute: the next call of the pair measures again,
        and a charge there refutes it then.
    Pure: reads nothing but its arguments.
    """
    pair = f"({proof.action}, {proof.model})"
    index = next((i for i, row in enumerate(rows)
                  if row.get("ledger_id") == proof.ledger_id), None)
    if index is None:
        return False, (f"the proof for {pair} names ledger row "
                       f"{proof.ledger_id!r}, which is not in the ledger")
    probe_row = rows[index]
    if not (probe_row.get("kind") == "generation"
            and probe_row.get("verdict") == "probe"
            and probe_row.get("action") == proof.action
            and probe_row.get("model") == proof.model):
        return False, (f"the proof for {pair} names ledger row "
                       f"{proof.ledger_id!r}, which is not a probe of {pair}")
    problem = probe_row_problem(probe_row)
    if problem is not None:
        return False, (f"the proof for {pair} names probe row "
                       f"{proof.ledger_id!r}, which proves nothing: {problem}")
    probe_after = _row_sum(probe_row, "account_after")
    advice = (f"{proof.action} stays refused: {proof.action} is charged, so "
              f"stay on the generate track. Re-measuring it means the author "
              f"removes that proof from proofs.json by hand and probes again")
    refuted = (f"proof for {pair} REFUTED: the probe {proof.ledger_id} left "
               f"the balance at {probe_after}, and the next balance read")
    late = "a late charge, or a refill that can hide one. " + advice
    if index + 1 < len(rows):
        after_row = rows[index + 1]
        next_before = _row_sum(after_row, "account_before")
        if next_before != probe_after:
            return False, (f"{refuted} (ledger row "
                           f"{after_row.get('ledger_id')}) was {next_before}: "
                           f"{late}")
        confirmed = (True, f"proof for {pair} confirmed by ledger row "
                           f"{after_row.get('ledger_id')}")
    elif current_sum is None:
        return None, (f"proof for {pair} is pending: the next balance read "
                      f"confirms it")
    elif current_sum == probe_after:
        return True, f"proof for {pair} confirmed by this balance read"
    else:
        return False, f"{refuted} (this one) is {current_sum}: {late}"

    for later in range(index + 1, len(rows)):
        row = rows[later]
        if not (row.get("kind") == "generation"
                and row.get("action") == proof.action
                and row.get("model") == proof.model):
            continue
        where = (f"proof for {pair} REFUTED by ledger row "
                 f"{row.get('ledger_id')}, a later {proof.action} call of "
                 f"{proof.model}")
        before = _row_sum(row, "account_before")
        after = _row_sum(row, "account_after")
        delta = row.get("delta")
        if after is None:
            return False, (f"{where}: the balance after it was never read, so "
                           f"it may have been charged. {advice}")
        if (before is not None and after < before) or (
                _is_number(delta) and delta < 0):
            return False, (f"{where}: the balance fell {before} -> {after} "
                           f"across it. {advice}")
        following = (_row_sum(rows[later + 1], "account_before")
                     if later + 1 < len(rows) else current_sum)
        if following is not None and following < after:
            return False, (f"{where}: it left the balance at {after} and the "
                           f"next balance read was {following}, a late "
                           f"charge. {advice}")
    return confirmed


# ---------------------------------------------------------------------------
# Body access that never raises anything but _Bad
# ---------------------------------------------------------------------------


class _Bad(Exception):
    """A body key is missing or mistyped; the message names its path."""


_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_PARAMS = ("parameters",)
_V4_CAPTIONS = _PARAMS + ("v4_prompt", "caption", "char_captions")
_NEG_CAPTIONS = _PARAMS + ("v4_negative_prompt", "caption", "char_captions")


def _dotted(path: Sequence[object]) -> str:
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_KINDS = {
    "int": (_is_int, "an int"),
    "number": (_is_number, "a number"),
    "str": (lambda v: isinstance(v, str), "a string"),
    "bool": (lambda v: isinstance(v, bool), "a bool"),
    "list": (lambda v: isinstance(v, list), "a list"),
    "map": (lambda v: isinstance(v, Mapping), "an object"),
}


def _at(body: object, path: Sequence[object], kind: str | None = None) -> object:
    """body[path...], or _Bad naming the first missing step or a wrong type."""
    cur = body
    for depth, part in enumerate(path):
        here = _dotted(path[:depth + 1])
        if isinstance(part, int):
            if not isinstance(cur, list) or not 0 <= part < len(cur):
                raise _Bad(f"{here} is missing")
            cur = cur[part]
        else:
            if not isinstance(cur, Mapping) or part not in cur:
                raise _Bad(f"{here} is missing")
            cur = cur[part]
    if kind is not None:
        test, label = _KINDS[kind]
        if not test(cur):
            raise _Bad(f"{_dotted(path)} is {type(cur).__name__}, not {label}")
    return cur


# ---------------------------------------------------------------------------
# Conditions 1-7 and 11: the body and the URL
# ---------------------------------------------------------------------------


def _c1_keys(body: Mapping[str, object], action: str) -> str | None:
    """model.ACTION_BODY_KEYS for `action`, plus the infill nested-object
    rule; the problem as text, or None."""
    params = _at(body, _PARAMS, "map")
    required, forbidden = ACTION_BODY_KEYS[action]
    present = sorted(key for key in forbidden if key in params)
    if present:
        return (f"a {action} body may not carry "
                f"{', '.join('parameters.' + key for key in present)}")
    missing = sorted(key for key in required if key not in params)
    if missing:
        return (f"a {action} body must carry "
                f"{', '.join('parameters.' + key for key in missing)}")
    if action == "infill":
        inpaint = _at(body, _PARAMS + (INPAINT_STRENGTH_KEY,), "number")
        nested = IMG2IMG_KEY in params
        if nested != (inpaint != INFILL_FULL_REPAINT):
            return (f"an infill body at inpaint strength {inpaint} "
                    f"{'may not' if nested else 'must'} carry "
                    f"parameters.{IMG2IMG_KEY} (present exactly when the "
                    f"strength is not {INFILL_FULL_REPAINT})")
    return None


def _c1(body: Mapping[str, object], proofs: Sequence[Proof], probe: bool,
        state: "State", account: Account | None) -> tuple[bool | None, str]:
    action = _at(body, ("action",), "str")
    if action not in ACTIONS:
        return False, f"action {action!r} is not one of {ACTIONS}"
    wrong_keys = _c1_keys(body, action)
    if wrong_keys:
        return False, wrong_keys
    if action not in PROOF_ACTIONS:
        if probe:
            return False, (f"a probe exists only for {PROOF_ACTIONS}; "
                           f"{action} is never probed")
        return True, f"{action} needs no proof row"
    model = _at(body, ("model",), "str")
    matching = [p for p in proofs if p.action == action and p.model == model]
    proven = bool(matching)
    if not probe:
        if not proven:
            return False, (f"no proof row for ({action}, {model}); only a "
                           f"probe the author approved can create one")
        try:
            rows = state.rows()
        except ValueError as exc:
            return False, (f"the ledger cannot be read to confirm the proof "
                           f"for ({action}, {model}): {exc}")
        return proof_standing(matching[0], rows,
                              None if account is None else account.sum)
    if proven:
        return False, (f"probe refused: ({action}, {model}) already has a "
                       f"proof row, so there is nothing left to measure")
    steps = _at(body, _PARAMS + ("steps",), "int")
    if steps != PROBE_STEPS:
        return False, (f"probe refused: steps is {steps}, a probe uses "
                       f"exactly {PROBE_STEPS}")
    if action == "img2img":
        paths = [_PARAMS + ("strength",)]
    else:
        paths = [_PARAMS + (INPAINT_STRENGTH_KEY,)]
        params = _at(body, _PARAMS, "map")
        if "strength" in params:
            paths.append(_PARAMS + ("strength",))
        if IMG2IMG_KEY in params:
            paths.append(_PARAMS + (IMG2IMG_KEY, "strength"))
    for path in paths:
        value = _at(body, path, "number")
        if value != PROBE_STRENGTH:
            return False, (f"probe refused: {_dotted(path)} is {value}, a "
                           f"probe uses exactly {PROBE_STRENGTH}")
    return True, (f"probe of ({action}, {model}) in probe shape, no proof "
                  f"row yet")


def _c2(body: Mapping[str, object]) -> tuple[bool, str]:
    action = _at(body, ("action",), "str")
    model = _at(body, ("model",), "str")
    if action not in MODELS_BY_ACTION:
        return False, (f"model {model!r} cannot be legal for unknown action "
                       f"{action!r}")
    legal = MODELS_BY_ACTION[action]
    if model not in legal:
        return False, f"model {model!r} is not legal for {action}; legal: {legal}"
    return True, f"{model} is legal for {action}"


def _c3(body: Mapping[str, object]) -> tuple[bool, str]:
    width = _at(body, _PARAMS + ("width",), "int")
    height = _at(body, _PARAMS + ("height",), "int")
    for name, dim in (("width", width), ("height", height)):
        if dim < MIN_DIM or dim % DIM_MULTIPLE:
            return False, (f"{name} {dim} is not a multiple of {DIM_MULTIPLE} "
                           f">= {MIN_DIM}")
    if width * height > MAX_AREA:
        return False, (f"{width}x{height} = {width * height} pixels exceeds "
                       f"{MAX_AREA}")
    return True, f"{width}x{height} = {width * height} pixels"


def _c4(body: Mapping[str, object]) -> tuple[bool, str]:
    steps = _at(body, _PARAMS + ("steps",), "int")
    n_samples = _at(body, _PARAMS + ("n_samples",), "int")
    if not 1 <= steps <= MAX_STEPS:
        return False, f"steps {steps} is outside 1..{MAX_STEPS}"
    if n_samples != N_SAMPLES:
        return False, f"n_samples {n_samples} is not {N_SAMPLES}"
    return True, f"steps {steps}, n_samples {n_samples}"


def _forbidden_keys(obj: object, path: tuple = ()) -> list[str]:
    found: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            here = path + (key,)
            if isinstance(key, str) and (key in NEVER_SEND_KEYS
                                         or key.startswith(NEVER_SEND_PREFIXES)):
                found.append(_dotted(here))
            found.extend(_forbidden_keys(value, here))
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            found.extend(_forbidden_keys(value, path + (index,)))
    return found


def _c5(body: Mapping[str, object]) -> tuple[bool, str]:
    found = _forbidden_keys(body)
    if found:
        return False, f"never-send keys present: {', '.join(found)}"
    return True, "no never-send key at any depth"


def _one_center(body: Mapping[str, object], path: tuple, what: str
                ) -> tuple[object, object]:
    x = _at(body, path + ("x",))
    y = _at(body, path + ("y",))
    if not (on_grid(x) and on_grid(y)):
        raise _Bad(f"{what} center ({x!r}, {y!r}) at {_dotted(path)} is not "
                   f"on the 0.1..0.9 grid")
    return x, y


def _c6(body: Mapping[str, object]) -> tuple[bool, str]:
    captions = _at(body, _V4_CAPTIONS, "list")
    count = len(captions)
    if not 1 <= count <= MAX_FRAMES:
        return False, f"{count} character captions; legal 1..{MAX_FRAMES}"
    centers: list[tuple[object, object]] = []
    for i in range(count):
        _at(body, _V4_CAPTIONS + (i, "char_caption"), "str")
        listed = _at(body, _V4_CAPTIONS + (i, "centers"), "list")
        if len(listed) != 1:
            return False, (f"{_dotted(_V4_CAPTIONS + (i, 'centers'))} has "
                           f"{len(listed)} centers; exactly 1")
        centers.append(_one_center(body, _V4_CAPTIONS + (i, "centers", 0),
                                   "v4_prompt"))
    for i in range(count):
        for j in range(i):
            if centers[i] == centers[j]:
                return False, (f"frames {j} and {i} share the center "
                               f"{centers[i]}")
    prompts = _at(body, _PARAMS + ("characterPrompts",), "list")
    negatives = _at(body, _NEG_CAPTIONS, "list")
    if len(prompts) != count:
        return False, (f"characterPrompts has {len(prompts)} entries, "
                       f"v4_prompt has {count}")
    if len(negatives) != count:
        return False, (f"v4_negative_prompt has {len(negatives)} captions, "
                       f"v4_prompt has {count}")
    for i in range(count):
        cp = _PARAMS + ("characterPrompts", i)
        if _one_center(body, cp + ("center",), "characterPrompts") != centers[i]:
            return False, (f"{_dotted(cp)} center differs from v4_prompt "
                           f"frame {i}")
        neg_listed = _at(body, _NEG_CAPTIONS + (i, "centers"), "list")
        if len(neg_listed) != 1:
            return False, (f"{_dotted(_NEG_CAPTIONS + (i, 'centers'))} has "
                           f"{len(neg_listed)} centers; exactly 1")
        if _one_center(body, _NEG_CAPTIONS + (i, "centers", 0),
                       "v4_negative_prompt") != centers[i]:
            return False, (f"v4_negative_prompt frame {i} center differs "
                           f"from v4_prompt frame {i}")
        if (_at(body, cp + ("prompt",), "str")
                != _at(body, _V4_CAPTIONS + (i, "char_caption"), "str")):
            return False, (f"{_dotted(cp)}.prompt differs from v4_prompt "
                           f"frame {i}'s char_caption")
        if (_at(body, cp + ("uc",), "str")
                != _at(body, _NEG_CAPTIONS + (i, "char_caption"), "str")):
            return False, (f"{_dotted(cp)}.uc differs from v4_negative_prompt "
                           f"frame {i}'s char_caption")
        if _at(body, cp + ("enabled",)) is not True:
            return False, f"{_dotted(cp)}.enabled is not true"
    base = _at(body, _PARAMS + ("v4_prompt", "caption", "base_caption"), "str")
    if _at(body, ("input",), "str") != base:
        return False, "input differs from v4_prompt base_caption"
    neg_base = _at(body, _PARAMS + ("v4_negative_prompt", "caption",
                                    "base_caption"), "str")
    if _at(body, _PARAMS + ("negative_prompt",), "str") != neg_base:
        return False, "negative_prompt differs from v4_negative_prompt base_caption"
    if _at(body, _PARAMS + ("use_coords",)) is not True:
        return False, "parameters.use_coords is not true"
    if _at(body, _PARAMS + ("v4_prompt", "use_coords")) is not True:
        return False, "parameters.v4_prompt.use_coords is not true"
    return True, f"{count} frames, centers on the grid, distinct, arrays parallel"


def _c7(body: Mapping[str, object]) -> tuple[bool, str]:
    base_path = _PARAMS + ("v4_prompt", "caption", "base_caption")
    base = _at(body, base_path, "str")
    texts: list[tuple[tuple, str]] = [
        (("input",), _at(body, ("input",), "str")),
        (base_path, base),
        (_PARAMS + ("negative_prompt",),
         _at(body, _PARAMS + ("negative_prompt",), "str")),
        (_PARAMS + ("v4_negative_prompt", "caption", "base_caption"),
         _at(body, _PARAMS + ("v4_negative_prompt", "caption", "base_caption"),
             "str")),
    ]
    char_texts: list[tuple[tuple, str]] = []   # positive character captions
    uc_texts: list[tuple[tuple, str]] = []
    for i in range(len(_at(body, _V4_CAPTIONS, "list"))):
        path = _V4_CAPTIONS + (i, "char_caption")
        char_texts.append((path, _at(body, path, "str")))
    for i in range(len(_at(body, _NEG_CAPTIONS, "list"))):
        path = _NEG_CAPTIONS + (i, "char_caption")
        uc_texts.append((path, _at(body, path, "str")))
    for i in range(len(_at(body, _PARAMS + ("characterPrompts",), "list"))):
        cp = _PARAMS + ("characterPrompts", i)
        char_texts.append((cp + ("prompt",), _at(body, cp + ("prompt",), "str")))
        uc_texts.append((cp + ("uc",), _at(body, cp + ("uc",), "str")))
    for path, text in texts + char_texts + uc_texts:
        if not text.isascii():
            return False, f"{_dotted(path)} is not ASCII"
    words = len(_WORD_RE.findall(base)) + sum(
        len(_WORD_RE.findall(_at(body, _V4_CAPTIONS + (i, "char_caption"), "str")))
        for i in range(len(_at(body, _V4_CAPTIONS, "list"))))
    tokens = TOKENS_PER_WORD * words
    if tokens > TOKEN_BUDGET:
        return False, (f"{words} words ~ {tokens:g} tokens exceeds the "
                       f"budget of {TOKEN_BUDGET}")
    for path, text in ((("input",), texts[0][1]), (base_path, base)):
        if not text.endswith(QUALITY_TAIL):
            return False, f"{_dotted(path)} does not end with {QUALITY_TAIL!r}"
    for path, text in char_texts + uc_texts:
        if "rating:" in text:
            return False, (f"{_dotted(path)} carries a rating tag; it belongs "
                           f"only at the end of the base caption")
    return True, f"ASCII, {words} words ~ {tokens:g} tokens, rating closes the base"


def _c11(url: object) -> tuple[bool, str]:
    if isinstance(url, str) and ("POST", url) in ALLOWED_ENDPOINTS:
        return True, f"POST {url}"
    return False, f"POST {url!r} is not an allowlisted generation endpoint"


def _judge(condition: int, fn, *args) -> Verdict:
    """Run one body condition; a malformed body fails it, never raises. Only
    condition 1 ever answers ok=None (a proof pending the next read)."""
    try:
        ok, message = fn(*args)
    except _Bad as exc:
        return Verdict(condition, False, str(exc))
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return Verdict(condition, False,
                       f"malformed body ({type(exc).__name__}: {exc})")
    return Verdict(condition, ok, message)


def evaluate(body: Mapping[str, object], account: Account | None,
             proofs: Sequence[Proof], state: State, *, url: str,
             probe: bool = False) -> tuple[Verdict, ...]:
    """Judge `body` against conditions 1-11; one Verdict each, in order.

    1  body["action"] in model.ACTIONS, and the parameters carry exactly the
       image keys model.ACTION_BODY_KEYS gives that action (the infill's
       nested img2img object present exactly when its inpaint strength is
       not INFILL_FULL_REPAINT). If the action is in model.PROOF_ACTIONS:
       without `probe`, a Proof with equal (action, model) must be in
       `proofs` AND `proof_standing` over state.rows() and account.sum must
       confirm it -- the probe row it names proving something
       (`probe_row_problem`), the read after the probe unchanged, and no
       later call of the pair charged -- ok=None while only the next balance
       read can tell (account None); with `probe`, see the module docstring (probe shape,
       no existing proof). A probe of `generate` fails.
    2  body["model"] in model.MODELS_BY_ACTION[action].
    3  parameters width/height are ints (not bool), multiples of
       DIM_MULTIPLE, each >= MIN_DIM, width*height <= MAX_AREA.
    4  1 <= parameters.steps <= MAX_STEPS; parameters.n_samples present and
       == N_SAMPLES.
    5  no key at ANY depth in NEVER_SEND_KEYS or starting with
       NEVER_SEND_PREFIXES.
    6  1 <= len(v4_prompt.caption.char_captions) <= MAX_FRAMES; each has
       exactly one center; every x and y satisfies model.on_grid; no two
       frames share (x, y); characterPrompts and v4_negative_prompt
       char_captions have the same length and the same centers in the same
       order; characterPrompts[i].prompt == char_captions[i].char_caption
       and .uc == negative char_captions[i].char_caption; input ==
       v4_prompt base_caption; negative_prompt == v4_negative_prompt
       base_caption; use_coords is True at the top level and in v4_prompt.
    7  every caption and uc string is ASCII; TOKENS_PER_WORD * words <=
       TOKEN_BUDGET, words counted as re.findall(r"[A-Za-z0-9]+") over the
       base caption plus every character caption; the base caption ends
       with QUALITY_TAIL; no character caption or uc contains "rating:".
    8  account.tier == OPUS_TIER, account.active is True, account.grace is
       not True. ok=None when account is None.
    9  chain_verdict(state.last_balance(), account.sum) != "charged".
       ok=None when account is None.
    10 not state.locked() and not state.inflight().
    11 ("POST", url) in model.ALLOWED_ENDPOINTS.

    Never raises for a malformed body: a missing or mistyped key fails the
    condition that reads it, with a message naming the key. A ledger that
    cannot give the previous balance fails condition 9 (it does not pass).
    """
    verdicts = [
        _judge(1, _c1, body, proofs, probe, state, account),
        _judge(2, _c2, body),
        _judge(3, _c3, body),
        _judge(4, _c4, body),
        _judge(5, _c5, body),
        _judge(6, _c6, body),
        _judge(7, _c7, body),
    ]

    if account is None:
        verdicts.append(Verdict(8, None, "needs the live account read"))
        verdicts.append(Verdict(9, None, "needs the live account read"))
    else:
        problems = []
        if not (_is_int(account.tier) and account.tier == OPUS_TIER):
            problems.append(f"tier is {account.tier!r}, not {OPUS_TIER} (Opus)")
        if account.active is not True:
            problems.append(f"active is {account.active!r}")
        if account.grace is True:
            problems.append("the subscription is in its grace period")
        verdicts.append(Verdict(8, not problems, "; ".join(problems) or
                                f"tier {account.tier}, active, not in grace"))
        try:
            previous = state.last_balance()
        except ValueError as exc:
            verdicts.append(Verdict(
                9, False, f"the ledger cannot give the previous balance: {exc}"))
        else:
            chain = chain_verdict(previous, account.sum)
            if chain == "charged":
                verdicts.append(Verdict(
                    9, False, f"balance fell from {previous} to {account.sum} "
                              f"since the last ledger row: an unexplained charge"))
            else:
                verdicts.append(Verdict(
                    9, True, f"chain {chain}: previous {previous}, now "
                             f"{account.sum}"))

    locked, inflight = state.locked(), state.inflight()
    if locked or inflight:
        present = [name for name, on in (("LOCK", locked),
                                         ("INFLIGHT", inflight)) if on]
        detail = (f" (INFLIGHT: {state.inflight_detail()})" if inflight
                  else "")
        verdicts.append(Verdict(10, False, f"{' and '.join(present)} present "
                                           f"under {state.root}{detail}"))
    else:
        verdicts.append(Verdict(10, True, "no LOCK, no INFLIGHT"))

    verdicts.append(_judge(11, _c11, url))
    return tuple(verdicts)


def assert_free(body: Mapping[str, object], account: Account,
                proofs: Sequence[Proof], state: State, *, url: str,
                probe: bool = False) -> None:
    """Raise Refused for the lowest-numbered condition whose ok is not True.

    TypeError when `account` is None: the online gate has no offline mode.
    Called by `run.run_request` immediately before INFLIGHT is taken, and by
    nothing else that sends.
    """
    if account is None:
        raise TypeError("assert_free needs a live account read; use "
                        "evaluate(account=None) for an offline plan")
    for verdict in evaluate(body, account, proofs, state, url=url, probe=probe):
        if verdict.ok is not True:
            raise Refused(verdict.condition, verdict.message)


def assert_endpoint(method: str, url: str) -> None:
    """Refused(11) unless (method, url) is in model.ALLOWED_ENDPOINTS.

    Called by every Transport implementation before it opens a socket, so
    the allowlist holds for the balance read too, not only for generation.
    """
    if not (isinstance(method, str) and isinstance(url, str)
            and (method, url) in ALLOWED_ENDPOINTS):
        raise Refused(11, f"{method!r} {url!r} is not an allowlisted endpoint")


def probe_request(action: str, *, seed: int, variant: str = "full") -> Request:
    """The probe for `action` ("img2img" or "infill"), as a Request (2.3).

    Same shape as production: the walk recipe's base caption, negative and
    frames (recipes.RECIPES["walk"], recipes.frames_for with the centers
    from mannequin.render_init), its rendered init as image_png, the layout's
    width and height, model = model.model_for(action, variant), ucPreset =
    UC_PRESET_NONE[model], steps = PROBE_STEPS, noise = 0. img2img:
    strength = PROBE_STRENGTH. infill: inpaint_strength = PROBE_STRENGTH and
    mask_png = masks.cell_mask(layout, 1). Built directly, NOT through
    recipes.make_request, whose strength band would refuse 0.3. ValueError
    for action "generate" or anything unknown. Imports recipes, mannequin
    and masks (implementer B) inside the function body, never at module
    level, so the guard imports with B's bodies still unimplemented.
    """
    if action not in PROOF_ACTIONS:
        raise ValueError(
            f"a probe exists only for {PROOF_ACTIONS}, not {action!r}")
    from tools.nai import mannequin, masks, recipes

    recipe = recipes.RECIPES["walk"]
    layout = recipe.layout
    init_png, centers = mannequin.render_init(
        layout, recipe.poses, recipe.identity.as_dict())
    frames = recipes.frames_for(recipe, centers)
    model = model_for(action, variant)
    common = dict(
        action=action, model=model, seed=seed,
        base_caption=recipe.base_caption, negative=recipe.negative,
        frames=frames, ucPreset=UC_PRESET_NONE[model],
        width=layout.width, height=layout.height, steps=PROBE_STEPS,
        noise=0.0, image_png=init_png,
    )
    if action == "img2img":
        return Request(strength=PROBE_STRENGTH, **common)
    return Request(inpaint_strength=PROBE_STRENGTH,
                   mask_png=masks.cell_mask(layout, 1), **common)


def probe_body(action: str, *, seed: int, variant: str = "full") -> dict:
    """`request.build_body(probe_request(action, seed=seed, variant=variant))`.

    The only route to a probe body; it exists so no probe dict is written by
    hand anywhere.
    """
    from tools.nai.request import build_body

    return build_body(probe_request(action, seed=seed, variant=variant))
