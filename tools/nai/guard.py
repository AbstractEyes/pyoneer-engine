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
  The guard READS `state` (LOCK, INFLIGHT, last balance) and never writes it.
  Nothing in the package writes LOCK at all any more: it exists only when the
  author places it by hand, as an emergency stop, and condition 10 honours it.
* A BALANCE EVENT WARNS; IT NEVER STOPS. The author's decision, 2026-09-24:
  "Don't worry about the costs, it's a shared account. Downgrade the LOCK to
  a warning, and don't stop the process via a warning." So an unsigned fall
  between two of our rows, or a live read below the chain, is condition 9
  ok=True WITH `warning` set; a proof the balance has refuted is condition 1
  ok=True WITH `warning` set; `assert_free` returns those warnings instead of
  raising; and `run.run_request` records each one in its row's `warning`.
  Everything is still MEASURED, classified and printed, and the books carry
  every figure. What still REFUSES is what decides what we send, never what
  the balance did: the body's shape (2-7, 11), the account's tier (8), an
  action with no proof, or a proof that never measured anything (1), a
  ledger that cannot be read (9), and LOCK or INFLIGHT on disk (10).
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
  PROBE_STRENGTH), and only while no proof row covers that pair yet.
  For infill EVERY strength the body carries (top-level strength, the
  INPAINT_STRENGTH_KEY value, the nested img2img strength) must equal
  PROBE_STRENGTH, since any of them could be the one the server charges by.
* Condition 12 (one generation per process) is not here: it is a process
  latch in `run.run_request`. Its number is reserved in CONDITION_TITLES.
* Condition 6 also requires every characterPrompts entry to carry
  `enabled: true`: a disabled box would make the three arrays mean different
  things while staying the same length.
* NO CHARACTER AT ALL IS LEGAL: the three arrays empty together and the base
  caption alone describes the image -- a whole sheet has no one character
  to place. The author, 2026-09-25: "You don't need a character prompt."
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
* A PROOF STANDS ONLY WHEN THE CHAIN CONFIRMS IT. A probe with delta 0
  writes a proof row at once, but a debit can land after the probe's own
  after-read (risk R4). `proof_standing` accepts a proof only when the
  balance read that FOLLOWS the probe -- the next ledger row's
  account_before, or, while there is none, the read being judged -- equals
  the probe's account_after. Any other value refutes it for good (a fall is
  R4's own shape, and a rise can hide a charge) -- and a refuted proof is a
  WARNING, never a stop (above). A proof naming no probe row of its own pair,
  or a probe row that measured nothing, is not refuted by the balance: it
  never proved anything (`proof_problem`), and condition 1 REFUSES on it.
* ONE PROOF, BOTH VARIANTS. A proof answers for its action on the full AND
  the curated V4.5 model (`model.Proof.covers`), never for another action.
  The author, 2026-09-24: "The curated model is in the same system, the
  same costs apply. So in our case no costs." So a curated call rides the
  full model's proof and the reverse, a probe of a pair whose twin is proven
  has nothing left to measure, and a charged call on EITHER variant refutes
  the one proof they share.
* A LATER FALL REFUTES IT TOO. Every `generation` row the proof covers
  after its probe is scanned. A balance that fell INSIDE one
  of them (its own after below its own before) refutes the proof for good:
  that row's two reads bracket one request of ours and nothing else, so the
  charge is ours. A balance after it that was never read refutes it too. And
  a fall in the read that FOLLOWS one of those rows refutes it for good as
  well -- that request went out, so R4's late debit and somebody else's
  spend are byte-identical there, and the unsafe reading is the one that
  counts. A confirmed proof is evidence about the account at the time of the
  probe, not a licence the account's own later answer cannot withdraw.
* NO SIGNATURE REACHES A PROOF. `proof_standing` reads no allowance at all:
  `acknowledge-drift` and `resolve-boundary` re-baseline the CHAIN, which
  silences condition 9's warning for that boundary, and never condition 1's
  for a refuted proof. The one way to stand a proof again is to remove it by
  hand and probe again.
* THE TWO MEASUREMENTS ARE NEVER MIXED. See the block above `Boundary`:
  within a row is OURS; between two rows is a boundary, EXTERNAL only when
  the earlier row sent nothing and AMBIGUOUS whenever a request of ours could
  be its cause, warned about until it is signed and then recorded on its own
  line. `accounting` reports every figure separately -- measured, signed and
  unsigned -- and adds none of them together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Mapping, Sequence

from tools.nai.model import (ACTION_BODY_KEYS, ACTIONS, ALLOWED_ENDPOINTS,
                             CHAIN_KINDS, DIM_MULTIPLE, DRIFT_KIND,
                             IMG2IMG_KEY, INFILL_FULL_REPAINT,
                             INPAINT_STRENGTH_KEY, MAX_AREA, MAX_FRAMES,
                             MAX_STEPS, MIN_DIM, MODELS_BY_ACTION, N_SAMPLES,
                             NEVER_SEND_KEYS, NEVER_SEND_PREFIXES, OPUS_TIER,
                             PROBE_STEPS, PROBE_STRENGTH, PROOF_ACTIONS,
                             QUALITY_TAIL, TOKEN_BUDGET, TOKENS_PER_WORD,
                             UC_PRESET_NONE, Account, Proof, Request,
                             drift_row_problem, model_for, on_grid,
                             rating_tag_in)

if TYPE_CHECKING:  # state imports Refused from here; no runtime cycle
    from tools.nai.state import State

CONDITION_TITLES: Mapping[int, str] = {
    1: "action is generate/img2img/infill, its keys match it; img2img and "
       "infill need a proof row that measured something (a balance that "
       "later refutes it is a warning)",
    2: "model is a V4.5 id legal for the action",
    3: "width and height are multiples of 64, each >= 64, area <= 1048576",
    4: "steps <= 28 and n_samples == 1",
    5: "no reference, vibe, stream, image_format, sm or tag_hint key",
    6: "0..6 frames, centers on the grid and distinct, arrays parallel",
    7: "ASCII captions, token budget, rating:general closes the base caption",
    8: "account is Opus (tier 3), active, not in grace period",
    9: "balance chain readable; an UNSIGNED fall between our rows, or a "
       "read below the chain, is a warning",
    10: "no LOCK file (the author's emergency stop) and no INFLIGHT file",
    11: "endpoint is POST https://image.novelai.net/ai/generate-image",
    12: "one generation request per process (run.run_request latch)",
}

OFFLINE_CONDITIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11)
"""What `plan` can judge with no network. Condition 9 is here for its LEDGER
half: an unsigned boundary already written down is a warning a plan can see
coming. Only its live half -- the balance now -- needs the network, so a plan
reports 9 as ok=None (with `warning` set over an open boundary), and 8
always is."""


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
    """One condition's outcome. `ok` is True, False, or None (not checked).

    `warning` is True when the condition passes (or cannot yet be judged)
    OVER a balance event -- an unsigned fall (9), a proof the balance refuted
    (1). A warning never stops anything: `assert_free` raises only on an `ok`
    that is not True, and returns the warnings for the row to record."""
    condition: int
    ok: bool | None
    message: str
    warning: bool = False


def chain_verdict(previous_after: int | None, before: int) -> str:
    """Classify a balance read against the previous ledger row (2.2 #9).

    Returns "first" when previous_after is None (empty ledger), "ok" when
    equal, "refill" when before > previous_after, "charged" when
    before < previous_after. Pure; `run.run_request` records a warning on
    "charged" and `evaluate` passes condition 9 on it WITH a warning.
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


# ---------------------------------------------------------------------------
# TWO KINDS OF MONEY MOVEMENT, AND THEY ARE NEVER THE SAME MEASUREMENT
# ---------------------------------------------------------------------------
# WITHIN A ROW: account_after.sum < account_before.sum. That row's OWN two
# reads bracket ONE request this tool sent, so the drop is OURS. It is
# recorded in that row's `warning` and refutes that action's proof for good
# (a warning too, since 2026-09-24: nothing here stops on a balance). Nothing
# below can absorb, clear or excuse it -- the comparison is inside one row,
# so no signature can reach it.
#
# BETWEEN TWO ROWS: one row's account_after.sum, then the NEXT row's
# account_before.sum, lower. NO ROW OF OURS LIES BETWEEN THOSE TWO READS --
# which is NOT the same claim as "nothing of ours was charged there". A
# provider may debit asynchronously, and a charge the server applied after
# the earlier row's own after-read (risk R4) lands at exactly this boundary,
# byte-identical to somebody else's spend. So a fallen boundary is
# CLASSIFIED, never assumed:
#
#   EXTERNAL   the earlier row SENT NOTHING -- a `refused` row, written
#              after the balance was read and before any byte left. No
#              request of ours was outstanding across that window, so the
#              drop cannot be a late charge of ours. `acknowledge-drift`
#              signs it, and the author still records what he checked.
#   AMBIGUOUS  the earlier row is a `generation`: a request of ours went out
#              (or may have -- an interrupted POST is recorded the same
#              way), or that row's own after-read failed. A late charge for
#              THAT request and a friend's spend cannot be told apart from
#              this ledger. `acknowledge-drift` refuses it; the louder
#              `resolve-boundary` records the author's own hand check and
#              WHICH SIDE he attributes it to, and that attribution is
#              reported as his judgement, never as a measurement.
#
# A signature re-baselines exactly the ONE boundary it names, for the chain
# `chain_verdict` walks. IT NEVER RESTORES A PROOF: `proof_standing` reads
# no allowance at all, so no signature can re-arm img2img -- the R4 rule
# this engine has always stated stands (see `model.Proof`).

_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

EXTERNAL = "external"
AMBIGUOUS = "ambiguous"
LIVE_ROW = "(this balance read, not yet a ledger row)"


@dataclass(frozen=True)
class Boundary:
    """One fall between two balance reads, and WHY it is classed as it is.

    `high` is the balance the earlier read left the chain at (a signature's
    allowance already applied), `low` the one the later read saw. `delta` is
    negative. `cause` is EXTERNAL or AMBIGUOUS and `why` says, in words,
    what makes it ambiguous ("" when it is not). `live` marks the one case
    that is not yet a pair of rows: a balance read this process just took,
    which nothing can sign until a row records it.
    """
    previous_row: str
    observed_row: str
    high: int
    low: int
    cause: str = EXTERNAL
    why: str = ""
    previous_time: str | None = None
    observed_time: str | None = None
    live: bool = False

    @property
    def delta(self) -> int:
        """low - high: NEGATIVE. Never added to anything a row measured."""
        return self.low - self.high

    @property
    def ambiguous(self) -> bool:
        """Whether a request of ours could be the cause of this fall."""
        return self.cause == AMBIGUOUS

    @property
    def window(self) -> str:
        """The reads' timestamps and the time between them, in words.

        ONLY THE TIMESTAMPS THERE ARE. The elapsed time needs both; one
        timestamp is quoted alone; none at all says so. Nothing is guessed,
        and an absent timestamp is never printed as "None".
        """
        start_text, end_text = self.previous_time, self.observed_time
        if start_text and end_text:
            try:
                start = datetime.strptime(start_text, _UTC_FORMAT)
                end = datetime.strptime(end_text, _UTC_FORMAT)
            except ValueError:
                return f"{start_text} -> {end_text}"
            seconds = int((end - start).total_seconds())
            sign = "-" if seconds < 0 else ""
            seconds = abs(seconds)
            return (f"{start_text} -> {end_text}, {sign}{seconds // 3600}h "
                    f"{seconds % 3600 // 60}m {seconds % 60}s apart")
        if start_text:
            return f"the earlier read was at {start_text}"
        if end_text:
            return f"the later read was at {end_text}"
        return "neither read carries a timestamp"

    @property
    def describe(self) -> str:
        """The ONE phrase every route prints for this boundary.

        `cli._cmd_account`'s list, `acknowledge-drift`'s STILL OPEN line and
        every refusal print THIS, so two routes cannot describe one drop in
        two ways, and no route can print a bare window as a verdict.
        """
        return (f"{self.high} -> {self.low} ({-self.delta} Anlas) between "
                f"ledger row {self.previous_row} and "
                f"{'' if self.live else 'ledger row '}{self.observed_row} "
                f"({self.window})")


def chain_rows(rows: Sequence[Mapping[str, object]]) -> list:
    """`rows` without the signature annotations: the links in the chain.

    A `drift` row measured nothing; it says what happened between two rows
    that did. Everything that walks the chain positionally -- the previous
    balance, the row after a probe, the read that follows a later call --
    walks THIS list, so an annotation can never be taken for the next
    request. Pure.
    """
    return [row for row in rows if row.get("kind") != DRIFT_KIND]


@dataclass(frozen=True)
class Signature:
    """One `drift` row: what the author recorded at ONE boundary, as whose.

    `attribution` is "theirs" (somebody else's spend) or "ours" (a charge of
    ours that landed late, recorded by hand at an AMBIGUOUS boundary).
    `checked` is what he says he checked. `delta` is negative.
    """
    previous_row: str
    observed_row: str
    high: int
    low: int
    attribution: str
    by: str
    checked: str
    ledger_id: str

    @property
    def delta(self) -> int:
        return self.low - self.high


def signatures(rows: Sequence[Mapping[str, object]]) -> tuple:
    """Every signature in `rows`, in file order.

    ValueError, naming the row, for a `drift` row `model.drift_row_problem`
    rejects: a money row this cannot read is never treated as absent. And
    ValueError naming BOTH rows when two of them sign the SAME boundary --
    one gap takes exactly one signature, and two would count the same money
    twice and re-baseline the chain twice. Pure.
    """
    out: list = []
    for row in rows:
        if row.get("kind") != DRIFT_KIND:
            continue
        problem = drift_row_problem(row)
        if problem is not None:
            raise ValueError(f"ledger row {row.get('ledger_id')!r} says it "
                             f"records a boundary, but {problem}")
        signature = Signature(
            previous_row=str(row["drift_previous_row"]),
            observed_row=str(row["drift_observed_row"]),
            high=_row_sum(row, "account_before"),
            low=_row_sum(row, "account_after"),
            attribution=str(row["drift_attribution"]),
            by=str(row["drift_acknowledged_by"]),
            checked=str(row["drift_checked"]),
            ledger_id=str(row.get("ledger_id")))
        for earlier in out:
            if (earlier.previous_row, earlier.observed_row) == (
                    signature.previous_row, signature.observed_row):
                raise ValueError(
                    f"ledger rows {signature.previous_row!r} -> "
                    f"{signature.observed_row!r} are signed TWICE, by ledger "
                    f"row {earlier.ledger_id!r} and by ledger row "
                    f"{signature.ledger_id!r}: one boundary takes exactly one "
                    f"signature, and two would count the same money twice. "
                    f"Neither command writes a second one, so this file was "
                    f"edited by hand: take one of the two rows back out")
        out.append(signature)
    return tuple(out)


def signed_allowance(rows: Sequence[Mapping[str, object]],
                     previous_row: object, observed_row: object) -> int:
    """How much is signed for at EXACTLY this boundary; 0 or below.

    Keyed on BOTH ledger ids, so a signature covers the one gap it names and
    no other one, earlier or later. Either id None -- a live read, which no
    row can sit inside -- answers 0. READ BY THE CHAIN ONLY:
    `proof_standing` never calls this, so no signature can restore a proof.
    Pure.
    """
    if previous_row is None or observed_row is None:
        return 0
    return sum(signature.delta for signature in signatures(rows)
               if signature.previous_row == previous_row
               and signature.observed_row == observed_row)


def expected_next_read(rows: Sequence[Mapping[str, object]],
                       earlier: Mapping[str, object],
                       later: "Mapping[str, object] | None",
                       high: int, low: "int | None") -> int:
    """What the read after `earlier` must show, a signature at THIS boundary
    allowed.

    `high` is the balance `earlier` left, `low` the one that followed it.
    THE ONE PLACE a signature is allowed to move a comparison, and the chain
    is its only caller.

    ValueError when MORE is signed for at this boundary than ever fell
    across it: a signature can only ever record a drop that happened, and a
    comparison this cannot justify is never waved through (law 7). `later`
    None means the live read, which no row sits inside, so the allowance is
    0 and this answers `high`.
    """
    allowed = signed_allowance(
        rows, earlier.get("ledger_id"),
        None if later is None else later.get("ledger_id"))
    if allowed < 0 and low is not None and low > high + allowed:
        raise ValueError(
            f"ledger rows {earlier.get('ledger_id')!r} -> "
            f"{None if later is None else later.get('ledger_id')!r} "
            f"are signed for {-allowed} Anlas of external drift, but the "
            f"balance only went {high} -> {low} across them: a signature can "
            f"never exceed the drop it records")
    return high + allowed


def _sent(row: Mapping[str, object]) -> str:
    """What `row` put on the wire, in words; "" when it sent nothing.

    A `refused` row sent nothing: the guard refused it after the balance was
    read and before any byte left. A `generation` row sent, or may have --
    an interrupted POST is recorded with no status and could still have
    reached the server, so it counts as sent here. THIS IS THE ONE TEST that
    decides EXTERNAL from AMBIGUOUS, on both the written and the live
    boundary, so a mutation of it turns both red.
    """
    if row.get("kind") != "generation":
        return ""
    status = row.get("http_status")
    what = f"a {row.get('action')} of {row.get('model')}"
    if _is_int(status):
        return f"{what} that reached the server (HTTP {status})"
    return (f"{what} whose response never arrived, so whether it reached the "
            f"server at all is unknown")


def _boundary(rows: Sequence[Mapping[str, object]],
              earlier: Mapping[str, object],
              later: Mapping[str, object]) -> "Boundary | None":
    """The UNSIGNED part of the drop between two adjacent chain rows.

    None when the balance did not fall across them, or when a signature
    covers the whole fall. ValueError -- never a pass -- only when the
    balance genuinely cannot be READ across the boundary: the later row has
    no integer account_before.sum, or the earlier row read no integer
    balance on either side of itself. A boundary that can be read but cannot
    be BLAMED is AMBIGUOUS, which is a verdict the author can answer
    (`resolve-boundary`), not a raise he could only hand-edit his way out
    of: an append-only ledger must never hold a row that makes every later
    call raise for good.
    """
    low = _row_sum(later, "account_before")
    if low is None:
        raise ValueError(f"ledger row {later.get('ledger_id')!r} has no "
                         f"integer account_before.sum, so the balance chain "
                         f"cannot be read across it")
    why = ""
    high = _row_sum(earlier, "account_after")
    if high is None:
        high = _row_sum(earlier, "account_before")
        if high is None:
            raise ValueError(f"ledger row {earlier.get('ledger_id')!r} read "
                             f"no integer balance on either side of itself, "
                             f"so the chain cannot be read across it")
        why = (f"the balance after ledger row {earlier.get('ledger_id')} was "
               f"never read -- that row's own after-read failed -- so a "
               f"charge the request itself caused would show at exactly this "
               f"boundary")
    else:
        sent = _sent(earlier)
        if sent:
            why = (f"ledger row {earlier.get('ledger_id')} sent {sent}, so a "
                   f"debit the server applied AFTER that row's own after-read "
                   f"(risk R4) would show at exactly this boundary")
    expected = expected_next_read(rows, earlier, later, high, low)
    if low >= expected:
        return None
    return Boundary(previous_row=str(earlier.get("ledger_id")),
                    observed_row=str(later.get("ledger_id")),
                    high=expected, low=low,
                    cause=AMBIGUOUS if why else EXTERNAL, why=why,
                    previous_time=earlier.get("utc_time"),
                    observed_time=later.get("utc_time"))


def open_boundaries(rows: Sequence[Mapping[str, object]]) -> tuple:
    """EVERY unsigned fall between two of our rows, oldest first.

    ONE function answers both questions -- the refusal ("is there one?") and
    the books ("how much is unsigned, and where?") -- so a mutation of the
    walk turns both red and neither can grow its own copy (CLAUDE.md's
    sibling-route warning). Condition 9 WARNS while this answers anything,
    so a between-row drop is reported every time it is seen until it is
    signed, and is never absorbed by the row that observed it. A drop
    measured INSIDE one row is not here: that one is ours, and
    `run.run_request` records it in that row's own `warning`.

    ValueError for a boundary that cannot be read (`_boundary`). Pure.
    """
    links = chain_rows(rows)
    return tuple(filter(None, (_boundary(rows, links[index], links[index + 1])
                               for index in range(len(links) - 1))))


def open_boundary(rows: Sequence[Mapping[str, object]]) -> "Boundary | None":
    """The oldest unsigned boundary in `rows`, or None.

    `open_boundaries` with one taken off the front, so a command that asks
    for one and a command that lists them all can never disagree.
    """
    return next(iter(open_boundaries(rows)), None)


def live_boundary(rows: Sequence[Mapping[str, object]], high: int, low: int,
                  *, observed_row: object = None,
                  observed_time: object = None) -> Boundary:
    """The drop a LIVE balance read sees below the chain, as a Boundary.

    `high` is `state.last_balance()`, `low` the read just taken. The earlier
    side is the last row that measured a balance, so `_sent` decides this
    one's cause exactly as it decides a written boundary's. `observed_row`
    names the row that WRITES this read down (the row the calling
    `run.run_request` is about to write) when there is one, and the note
    then prints a command that can really be
    typed; without it the boundary is `live`, and nothing can sign it until
    a row records it. ValueError when no chain row precedes the read.
    """
    links = chain_rows(rows)
    if not links:
        raise ValueError("a live balance read below the chain needs a chain: "
                         "this ledger holds no row that measured a balance")
    earlier = links[-1]
    why = ""
    sent = _sent(earlier)
    if sent:
        why = (f"ledger row {earlier.get('ledger_id')} sent {sent}, so a "
               f"debit the server applied AFTER that row's own after-read "
               f"(risk R4) would show at exactly this boundary")
    return Boundary(previous_row=str(earlier.get("ledger_id")),
                    observed_row=(LIVE_ROW if observed_row is None
                                  else str(observed_row)),
                    high=high, low=low,
                    cause=AMBIGUOUS if why else EXTERNAL, why=why,
                    previous_time=earlier.get("utc_time"),
                    observed_time=(None if observed_time is None
                                   else str(observed_time)),
                    live=observed_row is None)


def boundary_note(boundary: Boundary) -> str:
    """The ONE sentence every route prints for one fallen boundary.

    IT SAYS WHAT WAS MEASURED AND WHAT WAS NOT, and never states a cause it
    did not measure: an EXTERNAL boundary had no request of ours
    outstanding, and calling the drop somebody else's is STILL the author's
    judgement; an AMBIGUOUS one had, and this tool cannot tell a late charge
    of ours from a friend's spend. Condition 9's verdict,
    `run.run_request`'s warning text and `cli._cmd_account` all call this,
    so there is one wording and a mutation of it turns every route red. It
    never says the fall stopped anything: since 2026-09-24 it does not.
    Pure.
    """
    fell = f"the balance fell {boundary.describe}"
    if boundary.ambiguous:
        note = (f"AMBIGUOUS BOUNDARY -- this tool CANNOT say whose spend this "
                f"was: {fell}. {boundary.why}. No row of ours lies between "
                f"those two reads, so nothing this tool sent was MEASURED as "
                f"charged -- and nothing measured that it was not. A late "
                f"charge of ours and somebody else's spend on a shared "
                f"account are byte-identical here.")
        how = (f" This is a warning and stops nothing, but it stays on the "
               f"books as UNSIGNED, and `acknowledge-drift` cannot sign this "
               f"one. Check the provider's own usage page and whoever else "
               f"uses the account, then record what you found: "
               f"`python -m tools.nai resolve-boundary --previous "
               f"{boundary.previous_row} --observed {boundary.observed_row} "
               f"--anlas {-boundary.delta} --attribute ours|theirs --by NAME "
               f"--checked \"what you looked at\"`.")
    else:
        note = (f"EXTERNAL DRIFT -- no request of ours was outstanding across "
                f"it: {fell}. Ledger row {boundary.previous_row} sent nothing "
                f"(the guard refused it before any byte left) and no row of "
                f"ours lies between those two reads, so nothing this tool "
                f"sent was MEASURED as charged here. On a shared account the "
                f"likeliest cause is somebody else's spend; recording it as "
                f"theirs is your judgement, not a measurement. Rows whose own "
                f"after-read failed are listed separately, and this says "
                f"nothing about them.")
        how = (f" This is a warning and stops nothing, but it stays on the "
               f"books as UNSIGNED until you sign it with `python -m tools.nai "
               f"acknowledge-drift "
               f"--previous {boundary.previous_row} --observed "
               f"{boundary.observed_row} --anlas {-boundary.delta} --by NAME "
               f"--checked \"what you looked at\"`.")
    if boundary.live:
        how = (" This read is not a ledger row yet, so no command can sign it "
               "as it stands: the next run writes the row that records it, "
               "and it can be signed once it is written down.")
    return note + how


def boundaries_note(boundaries: Sequence[Boundary], *,
                    this_read: bool = True) -> str:
    """`boundary_note` for the FIRST, then every other open boundary named.

    The caller puts the boundary THIS call observed at the front, so the
    author always reads about the drop that just happened rather than the
    oldest one on the books, and never carries away a figure that is short.
    `this_read` False says out loud that the warning is about something
    recorded earlier. ValueError for an empty sequence: there is no note
    about nothing. Pure.
    """
    if not boundaries:
        raise ValueError("boundaries_note needs at least one boundary")
    opening = "" if this_read else (
        "NOT the balance read just taken -- that one is level with the "
        "chain; a boundary recorded EARLIER is open: ")
    note = opening + boundary_note(boundaries[0])
    rest = boundaries[1:]
    if not rest:
        return note
    listed = ", ".join(f"{other.previous_row}->{other.observed_row} "
                       f"({other.delta:+d})" for other in rest)
    return (f"{note} AND {len(rest)} OTHER unsigned boundary(ies), "
            f"{sum(other.delta for other in rest):+d} Anlas in all: "
            f"{listed}. None of that is in `theirs` either.")


@dataclass(frozen=True)
class Accounting:
    """The figures that answer different questions, NEVER ONE FIGURE.

    MEASURED, from our own rows' two reads, which bracket one request of
    ours and nothing else:
      `ours_spent`    the sum of the NEGATIVE in-row deltas: 0 or below, and
                      THE one number that says what this tool has cost.
      `ours_refilled` the sum of the positive ones -- a refill that landed
                      between one row's own two reads. Kept apart so it can
                      never cancel a charge measured inside another row.
    RECORDED BY HAND, at a boundary, which measured nothing about who spent:
      `theirs_signed` what the author attributed to somebody else.
      `ours_signed`   what he attributed to US at an AMBIGUOUS boundary --
                      his judgement after a hand check, not a measurement.
    MEASURED AND UNATTRIBUTED, which is the default state of a shared
    account and the figure that used to be invisible:
      `unsigned`      the sum of every open boundary's delta, with
                      `open_boundaries` naming them. Money that HAS left the
                      account and that nobody has signed for. It is in no
                      other figure, and it is never 0 merely because nobody
                      typed a command.
    `unmeasured` names the rows whose after-read failed (in no figure at
    all) and `refilled_rows` the rows that rose inside themselves.
    NO FIGURE HERE IS EVER ADDED TO ANOTHER: a single total would answer no
    question and would hide the one fact worth seeing at a glance.
    """
    ours_spent: int
    ours_refilled: int
    theirs_signed: int
    ours_signed: int
    unsigned: int
    open_boundaries: tuple
    rows_counted: int
    signatures_counted: int
    unmeasured: tuple
    refilled_rows: tuple


def accounting(rows: Sequence[Mapping[str, object]]) -> Accounting:
    """Every figure in `Accounting` over `rows`.

    ValueError (law 7: the books never fall back to a plausible figure) when
    a signature cannot be read, when two sign one boundary, when one names a
    pair of rows that are not adjacent links in this chain, when one exceeds
    the drop it records, or when the chain cannot be read across a boundary.
    Pure.
    """
    spent = refilled = 0
    counted = 0
    unmeasured: list = []
    refilled_rows: list = []
    links = chain_rows(rows)
    for row in links:
        before = _row_sum(row, "account_before")
        after = _row_sum(row, "account_after")
        if before is None or after is None:
            unmeasured.append(str(row.get("ledger_id")))
            continue
        counted += 1
        if after < before:
            spent += after - before
        elif after > before:
            refilled += after - before
            refilled_rows.append(str(row.get("ledger_id")))
    signed = signatures(rows)
    adjacent = {(str(links[index].get("ledger_id")),
                 str(links[index + 1].get("ledger_id")))
                for index in range(len(links) - 1)}
    for signature in signed:
        if (signature.previous_row, signature.observed_row) not in adjacent:
            raise ValueError(
                f"ledger row {signature.ledger_id!r} signs for "
                f"{-signature.delta} Anlas between ledger rows "
                f"{signature.previous_row!r} and {signature.observed_row!r}, "
                f"which are not two rows side by side in this chain: a "
                f"signature names the boundary it covers, and this one names "
                f"none, so the money it carries is counted in nothing")
    gaps = open_boundaries(rows)
    return Accounting(
        ours_spent=spent, ours_refilled=refilled,
        theirs_signed=sum(s.delta for s in signed if s.attribution == "theirs"),
        ours_signed=sum(s.delta for s in signed if s.attribution == "ours"),
        unsigned=sum(gap.delta for gap in gaps), open_boundaries=gaps,
        rows_counted=counted, signatures_counted=len(signed),
        unmeasured=tuple(unmeasured), refilled_rows=tuple(refilled_rows))


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


def _proof_probe(proof: Proof, links: Sequence[Mapping[str, object]]
                 ) -> tuple[int | None, str | None]:
    """(index of the proof's probe row in `links`, None), or (None, why).

    THE STRUCTURAL HALF of `proof_standing`, and the ONE rule for "this proof
    names a probe that measured something": a row in the chain `links` with
    the proof's ledger_id, which is a `generation` probe of the proof's own
    (action, model) that `probe_row_problem` accepts. A proof failing this
    was never a measurement, so condition 1 REFUSES on it whatever the
    balance policy; one passing it can only be refuted by what the balance
    did afterwards, which is a warning. `proof_standing` and `proof_problem`
    both call it -- one function, so a mutation of it turns both routes red.
    Pure.
    """
    pair = f"({proof.action}, {proof.model})"
    index = next((i for i, row in enumerate(links)
                  if row.get("ledger_id") == proof.ledger_id), None)
    if index is None:
        return None, (f"the proof for {pair} names ledger row "
                      f"{proof.ledger_id!r}, which is not in the ledger")
    probe_row = links[index]
    if not (probe_row.get("kind") == "generation"
            and probe_row.get("verdict") == "probe"
            and probe_row.get("action") == proof.action
            and probe_row.get("model") == proof.model):
        return None, (f"the proof for {pair} names ledger row "
                      f"{proof.ledger_id!r}, which is not a probe of {pair}")
    problem = probe_row_problem(probe_row)
    if problem is not None:
        return None, (f"the proof for {pair} names probe row "
                      f"{proof.ledger_id!r}, which proves nothing: {problem}")
    return index, None


def proof_problem(proof: Proof,
                  rows: Sequence[Mapping[str, object]]) -> str | None:
    """Why `proof` never proved anything over the ledger `rows`, or None
    when it names a probe of its own pair that measured something. The
    structural half of `proof_standing` (`_proof_probe`). Pure."""
    return _proof_probe(proof, chain_rows(rows))[1]


def proof_standing(proof: Proof, rows: Sequence[Mapping[str, object]],
                   current_sum: int | None) -> tuple[bool | None, str]:
    """Whether the balance chain confirms `proof` (module docstring).

    `rows` is the ledger in file order; `current_sum` is the balance read
    being judged, or None offline. Returns (True, why) when confirmed,
    (None, why) ONLY when nothing has been read since the probe (offline,
    no row after it yet), (False, why) otherwise:
      * no row in `rows` has the proof's ledger_id, or that row is not a
        `generation` row with verdict "probe" for the proof's (action,
        model), or `probe_row_problem` finds it proves nothing (no 2xx, no
        extracted image, a balance that moved, LOCK);
      * the read that FOLLOWS the probe -- the next chain row's
        account_before.sum, or `current_sum` while there is no next row --
        is not the probe's account_after.sum. BELOW it: the probe's own
        request went out, so a debit the server applied after the probe's
        after-read (risk R4) lands exactly there and cannot be told from
        somebody else's spend; the safe reading of an unreadable fall is
        that the action is charged. ABOVE it: a rise can hide a charge.
        Either way REFUTED FOR GOOD;
      * any LATER `generation` row the proof covers (`Proof.covers`: its
        action, on either V4.5 variant) has an
        account_after.sum below its account_before.sum, or a negative delta,
        or no integer account_after.sum at all (its after-read failed), or
        the read that follows IT is below its account_after.sum -- the same
        R4 reading, refuted for good. A RISE across or after such a call
        does not refute by itself: the next call of the pair measures again.

    The first bullet is the STRUCTURAL half (`_proof_probe`, which
    `proof_problem` also answers from): such a proof never measured anything,
    and condition 1 refuses on it. Every other False is the BALANCE half, and
    condition 1 passes it with a warning (module docstring).

    NO SIGNATURE IS READ HERE. `signed_allowance` and `expected_next_read`
    re-baseline the CHAIN and nothing else, so no `acknowledge-drift` and no
    `resolve-boundary` can turn a refuted proof back into a standing one, and
    condition 1 keeps warning about it. An author who believes the fall was
    somebody else's removes the proof from proofs.json by hand and probes
    again, paying the probe's cost knowingly. Pure: reads nothing but its
    arguments.
    """
    pair = f"({proof.action}, {proof.model})"
    links = chain_rows(rows)
    index, problem = _proof_probe(proof, links)
    if problem is not None:
        return False, problem
    probe_row = links[index]
    probe_after = _row_sum(probe_row, "account_after")
    remeasure = (f"Re-measuring it means the author removes that proof from "
                 f"proofs.json by hand and probes again")
    charged = (f"{proof.action} IS CHARGED -- a drop measured INSIDE one of "
               f"our own {proof.action} rows, between that request's own "
               f"before-read and after-read, so every further "
               f"{proof.action} may be charged too. {remeasure}")
    unclear = (f"This proof can no longer be trusted. NOTHING measured a "
               f"charge inside an {proof.action} row -- the balance simply "
               f"cannot be followed across this point, and a rise can hide a "
               f"charge. {remeasure}")

    def late(row, fell_to: int, left_at: int) -> tuple[bool, str]:
        """A fall in the read that FOLLOWS one of our own sent rows.

        Refuted FOR GOOD, and the words say exactly why the tool cannot be
        kinder: that row's request went out, so a debit the server applied
        after its own after-read is indistinguishable from a friend's
        spend, and a signature at that boundary is a judgement about a
        shared account -- never a measurement that this action is free.
        """
        return False, (
            f"proof for {pair} REFUTED: ledger row {row.get('ledger_id')} "
            f"sent a request of ours and left the balance at {left_at}, and "
            f"the next balance read was {fell_to}, BELOW it. A debit the "
            f"server applied after that row's own after-read (risk R4) looks "
            f"exactly like this, and so does somebody else's spend on a "
            f"shared account: nothing here can tell them apart, so the "
            f"unsafe reading is the one that counts. Signing that boundary "
            f"as somebody else's records WHO the author believes spent it; "
            f"it never restores this proof. {unclear}")

    if index + 1 < len(links):
        after_row = links[index + 1]
        next_before = _row_sum(after_row, "account_before")
        if next_before is None:
            return False, (f"proof for {pair} REFUTED: the balance before "
                           f"ledger row {after_row.get('ledger_id')}, the row "
                           f"after the probe, was never read. {unclear}")
        if next_before < probe_after:
            return late(probe_row, next_before, probe_after)
        if next_before != probe_after:
            return False, (f"proof for {pair} REFUTED: the probe "
                           f"{proof.ledger_id} left the balance at "
                           f"{probe_after}, and the next balance read (ledger "
                           f"row {after_row.get('ledger_id')}) was "
                           f"{next_before}, above it. {unclear}")
        confirmed = (True, f"proof for {pair} confirmed by ledger row "
                           f"{after_row.get('ledger_id')}")
    elif current_sum is None:
        return None, (f"proof for {pair} is pending: the next balance read "
                      f"confirms it")
    elif current_sum == probe_after:
        return True, f"proof for {pair} confirmed by this balance read"
    elif current_sum < probe_after:
        return late(probe_row, current_sum, probe_after)
    else:
        return False, (f"proof for {pair} REFUTED: the probe "
                       f"{proof.ledger_id} left the balance at {probe_after} "
                       f"and this balance read is {current_sum}, above it. "
                       f"{unclear}")

    for later in range(index + 1, len(links)):
        row = links[later]
        if not (row.get("kind") == "generation"
                and proof.covers(row.get("action"), row.get("model"))):
            continue
        where = (f"proof for {pair} REFUTED by ledger row "
                 f"{row.get('ledger_id')}, a later {proof.action} call of "
                 f"{row.get('model')}")
        before = _row_sum(row, "account_before")
        after = _row_sum(row, "account_after")
        delta = row.get("delta")
        if after is None:
            return False, (f"{where}: the balance after it was never read, so "
                           f"it may have been charged and nothing can tell "
                           f"that apart from drift. {unclear}")
        if (before is not None and after < before) or (
                _is_number(delta) and delta < 0):
            return False, (f"{where}: the balance fell {before} -> {after} "
                           f"INSIDE that row -- between its own before-read "
                           f"and its own after-read, with only that one "
                           f"request between them. {charged}")
        following_row = links[later + 1] if later + 1 < len(links) else None
        following = (_row_sum(following_row, "account_before")
                     if following_row is not None else current_sum)
        if following is not None and following < after:
            return late(row, following, after)
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
    matching = [p for p in proofs if p.covers(action, model)]
    proven = bool(matching)
    if not probe:
        if not proven:
            return False, (f"no proof row for ({action}, {model}) on either "
                           f"V4.5 variant; only a probe the author approved "
                           f"can create one")
        try:
            rows = state.rows()
        except ValueError as exc:
            return False, (f"the ledger cannot be read to confirm the proof "
                           f"for ({action}, {model}): {exc}")
        never_measured = proof_problem(matching[0], rows)
        if never_measured is not None:
            return False, never_measured
        standing, why = proof_standing(matching[0], rows,
                                       None if account is None else account.sum)
        if standing is False:
            # THE BALANCE HALF: a warning, never a stop (module docstring).
            return True, (f"{why} -- a WARNING, not a stop: the account is "
                          f"shared, so {action} is sent anyway"), True
        return standing, why
    if proven:
        return False, (f"probe refused: ({action}, {model}) already has a "
                       f"proof row, ({matching[0].action}, "
                       f"{matching[0].model}), so there is nothing left to "
                       f"measure")
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
    if count > MAX_FRAMES:
        return False, f"{count} character captions; legal 0..{MAX_FRAMES}"
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
    for path, text in ((("input",), texts[0][1]), (base_path, base)):
        if rating_tag_in(text[:-len(QUALITY_TAIL)]):
            return False, (f"{_dotted(path)} carries a rating tag before its "
                           f"closing {QUALITY_TAIL!r}; the rating is written "
                           f"once, at the end")
    for path, text in char_texts + uc_texts:
        if rating_tag_in(text):
            return False, (f"{_dotted(path)} carries a rating tag; it belongs "
                           f"only at the end of the base caption")
    return True, f"ASCII, {words} words ~ {tokens:g} tokens, rating closes the base"


def _c11(url: object) -> tuple[bool, str]:
    if isinstance(url, str) and ("POST", url) in ALLOWED_ENDPOINTS:
        return True, f"POST {url}"
    return False, f"POST {url!r} is not an allowlisted generation endpoint"


def _offline_chain(state: State) -> Verdict:
    """Condition 9 with no account read: the half that CAN be judged offline.

    `open_boundaries` is pure and reads only the ledger, so a plan over a
    ledger holding an unsigned fall SAYS SO, with `warning` set -- a
    condition that can be checked offline is checked. The live half (is the
    balance now below the chain?) stays ok=None either way, so the
    invariant "a condition that cannot be checked is not a pass" is
    untouched. Without this, `plan` gave a clean bill over books with money
    missing from them. An unreadable ledger still FAILS: that is not a
    balance event, it is books nothing can be added to.
    """
    try:
        gaps = open_boundaries(state.rows())
    except ValueError as exc:
        return Verdict(9, False, f"the balance chain cannot be read: {exc}")
    if gaps:
        return Verdict(9, None, boundaries_note(gaps, this_read=False),
                       warning=True)
    return Verdict(9, None, "no unsigned boundary in the ledger; the live "
                            "balance read is what is still missing")


def _judge(condition: int, fn, *args) -> Verdict:
    """Run one body condition; a malformed body fails it, never raises. Only
    condition 1 ever answers ok=None (a proof pending the next read), and
    only condition 1 answers a third element: True when it passes over a
    proof the balance refuted, which is a warning."""
    try:
        ok, message, *warned = fn(*args)
    except _Bad as exc:
        return Verdict(condition, False, str(exc))
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return Verdict(condition, False,
                       f"malformed body ({type(exc).__name__}: {exc})")
    return Verdict(condition, ok, message, warning=bool(warned and warned[0]))


def evaluate(body: Mapping[str, object], account: Account | None,
             proofs: Sequence[Proof], state: State, *, url: str,
             probe: bool = False) -> tuple[Verdict, ...]:
    """Judge `body` against conditions 1-11; one Verdict each, in order.

    1  body["action"] in model.ACTIONS, and the parameters carry exactly the
       image keys model.ACTION_BODY_KEYS gives that action (the infill's
       nested img2img object present exactly when its inpaint strength is
       not INFILL_FULL_REPAINT). If the action is in model.PROOF_ACTIONS:
       without `probe`, a Proof that covers (action, model) (`Proof.covers`:
       its action, on either V4.5 variant) must be in
       `proofs` AND `proof_problem` must find it names a probe row of its
       own pair that measured something (`probe_row_problem`) -- else ok
       False. `proof_standing` over state.rows() and account.sum then
       confirms it (ok True), finds it pending (ok None, only with account
       None), or finds the BALANCE refuted it -- the read after the probe
       moved, or a later call of the pair was charged, unread, or followed
       by a fall -- which is ok True WITH `warning` set: a warning, never a
       stop. With `probe`, see the module docstring (probe shape, no
       existing proof). A probe of `generate` fails.
    2  body["model"] in model.MODELS_BY_ACTION[action].
    3  parameters width/height are ints (not bool), multiples of
       DIM_MULTIPLE, each >= MIN_DIM, width*height <= MAX_AREA.
    4  1 <= parameters.steps <= MAX_STEPS; parameters.n_samples present and
       == N_SAMPLES.
    5  no key at ANY depth in NEVER_SEND_KEYS or starting with
       NEVER_SEND_PREFIXES.
    6  0 <= len(v4_prompt.caption.char_captions) <= MAX_FRAMES; each has
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
    9  TWO DIFFERENT MEASUREMENTS, and this condition is about only one of
       them. The ledger must be readable (else ok False). An UNSIGNED fall
       between two of our rows (`guard.open_boundaries(state.rows())`), or
       chain_verdict(state.last_balance(), account.sum) == "charged" (a live
       read below the chain is the same drop, not yet written down), is ok
       True WITH `warning` set. Every open boundary is reported, THE ONE
       THIS CALL SAW FIRST, through `boundaries_note` -- which says which of
       the two measurements it is, what was NOT measured, and the command
       that signs it. A drop measured INSIDE one of our rows is NOT this
       condition: that one is ours, and `run.run_request` records it in
       that row's own `warning`. With account None this condition is still
       judged OFFLINE over the ledger (`_offline_chain`): an unsigned
       boundary is reported there too, with `warning`, and the live half
       leaves it ok=None.
    10 not state.locked() and not state.inflight(). Nothing in the package
       writes LOCK: it is the author's emergency stop, placed by hand.
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
        verdicts.append(_offline_chain(state))
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
            rows = state.rows()
            gaps = list(open_boundaries(rows))
            previous = state.last_balance()
        except ValueError as exc:
            verdicts.append(Verdict(
                9, False, f"the balance chain cannot be read: {exc}"))
        else:
            chain = chain_verdict(previous, account.sum)
            this_read = chain == "charged"
            if this_read:
                gaps.insert(0, live_boundary(rows, previous, account.sum))
            if gaps:
                verdicts.append(Verdict(9, True, boundaries_note(
                    gaps, this_read=this_read), warning=True))
            else:
                verdicts.append(Verdict(
                    9, True, f"chain {chain}: previous {previous}, now "
                             f"{account.sum}; no unsigned boundary"))

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
                probe: bool = False) -> tuple[Verdict, ...]:
    """Raise Refused for the lowest-numbered condition whose ok is not True;
    otherwise return every verdict that passed WITH a warning, in condition
    order, for the row to record. A warning never raises (module docstring).

    TypeError when `account` is None: the online gate has no offline mode.
    Called by `run.run_request` immediately before INFLIGHT is taken, and by
    nothing else that sends.
    """
    if account is None:
        raise TypeError("assert_free needs a live account read; use "
                        "evaluate(account=None) for an offline plan")
    verdicts = evaluate(body, account, proofs, state, url=url, probe=probe)
    for verdict in verdicts:
        if verdict.ok is not True:
            raise Refused(verdict.condition, verdict.message)
    return tuple(verdict for verdict in verdicts if verdict.warning)


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
        layout, recipe.poses, recipe.identity.as_dict(),
        garments=recipe.identity.garments,
        build_name=recipe.identity.build)
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
