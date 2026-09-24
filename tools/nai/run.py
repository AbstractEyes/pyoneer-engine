"""The one function that sends a generation, and everything around the send.

OWNER: implementer A.

RESPONSIBILITY
--------------
`run_request` is THE ONLY caller of `Transport.post_json` in this package.
It reads the balance, checks the chain, runs the guard, marks the request in
flight, sends exactly one POST, reads the balance again no matter what
happened, classifies the delta, records every balance event as a WARNING in
the row, records proof rows for clean probes, stores the bytes, writes the
ledger row, and releases the in-flight marker. It never retries, and it
NEVER WRITES LOCK: since 2026-09-24 a balance event warns and never stops
(the author's decision -- the account is shared; guard's module docstring).

THE SEQUENCE (every step is part of the contract)
-------------------------------------------------
 1. Latch (condition 12): a second call in the same process raises
    guard.Refused(12). Nothing read, nothing written.
 2. probe=True requires context.probe_flag_used True, else Refused(1).
 3. Local precheck (condition 10): state.locked() or state.inflight() ->
    Refused(10), naming what INFLIGHT holds. No account read, no row. LOCK
    is only ever the author's own emergency stop: nothing here writes it.
 4. body = request.build_body(req); request_sha256 = canonical_sha256(body);
    ledger_id = state.new_ledger_id(); cid = new_correlation_id().
 5. before = tools.nai.transport.read_account(transport). A failure
    propagates: no request is sent and no row is written.
 6. guard.chain_verdict(state.last_balance(), before.sum) and
    guard.open_boundaries(state.rows()). A ledger that cannot give the
    previous balance, or a boundary whose balances cannot be READ at all (a
    malformed row, a LOST ledger: see state.last_balance) -> Refused(9), no
    row -- a row would restart the chain from here and forget the loss.
    An unsigned fall, whether already in the ledger or seen live by this
    call's own before-read, is a WARNING: its text goes into this call's
    row and the call goes on. THE TEXT SAYS WHICH BOUNDARY THIS CALL SAW,
    FIRST, with the figure: `_chain_note` puts the drop this before-read saw
    at the front (named by this call's own ledger id, which the row it
    writes will carry, so the command it prints can be typed) and lists
    every older gap after it. It classifies rather than assumes -- EXTERNAL
    only where the earlier row SENT NOTHING, AMBIGUOUS wherever a request of
    ours could be the cause -- and it never says an action is charged. It
    also names every proof this read refutes FOR GOOD -- decided by
    guard.proof_standing itself, over the ledger without and with this
    read.
 7. guard.assert_free(body, before, state.proofs(), state,
    url=model.GENERATE_URL, probe=probe). Refused(n) for n in 1-9 or 11 ->
    write a `refused` row (carrying step 6's warning), re-raise. Refused(10)
    here -> no row, re-raise. A refused row has account_after ==
    account_before and delta 0, so the chain stays exact. The verdicts that
    passed WITH a warning are added to the row's warning -- all but
    condition 9's, which step 6 already wrote naming this row.
 8. state.acquire_inflight(ledger_id, before.sum). Refused(10) -> no row,
    re-raise. The latch is set here: from now on this process has sent.
    (Before 8: the generation row, with every response field still null, is
    passed through state.validate_row. A row that could not be written
    raises ValueError HERE, while nothing has been sent.)
    FROM HERE ON THE BOOKKEEPING IS UNCONDITIONAL: steps 10 and 11 catch
    BaseException, not Exception, so a Ctrl-C (KeyboardInterrupt) or a
    SystemExit cannot skip the after-read or the row. An interrupt of the
    POST is recorded, the balance is still read, the row is written with a
    warning (the request's outcome is unknown), INFLIGHT released, and the
    interrupt is re-raised. Anything that escapes steps 12-15 propagates
    and leaves INFLIGHT for the author -- the one stop left, because a row
    may be missing from the books; the request blob stored in step 9 then
    also makes an empty ledger a LOST one (state.last_balance), so a
    first-run chain cannot forget it.
 9. Store image and mask PNGs and the REDACTED body JSON as blobs
    (request_path = the json blob). Headers: {"x-correlation-id": cid}.
    The json blob is request.canonical_json(body), so its name IS the
    request_sha256.
10. One `transport.post_json(GENERATE_URL, body, headers, TIMEOUT_S)`.
    TransportTimeout / TransportError are caught and recorded
    (error_message), never retried. Any OTHER exception out of post_json is
    recorded the same way, steps 11-15 still run (the balance is read and
    the row written), and it is re-raised after INFLIGHT is released; an
    interrupt (a BaseException that is not an Exception) is also a warning:
    its outcome is unknown.
11. after = read_account(transport), ALWAYS -- success, HTTP error,
    timeout, interrupt. If this read fails (an interrupt included): a
    warning (zero cost cannot be shown), write the row with account_after
    null and delta null, release INFLIGHT, re-raise. (The row also stores
    any 2xx output first, and marks inconclusive true.) When both the POST
    and this read raised, an interrupt is re-raised first, then the read's
    failure.
12. delta = after.sum - before.sum. delta < 0 -> a warning naming the
    ledger id: OUR charge, measured inside this row (for any img2img or
    infill -- probe or production -- it adds "<action> is charged";
    guard.proof_standing refutes that pair's proof over this row, which is
    itself a warning from then on). delta > 0 -> inconclusive true (a
    refill can hide a charge). Every warning of steps 6-12 goes into the
    row's `warning`, cut to state.MAX_ROW_STRING with a pointer to
    `account`, which prints every boundary in full; `locked` is always
    false.
13. On 2xx: store the ZIP blob, transport.unzip_image(...) -> store the PNG
    blob (output_path); ANY exception out of unzip_image is recorded in
    error_message, never raised, so the row is still written. For an
    infill with context.target_rect: differs_outside_mask =
    masks.differs_outside(req.image_png, output_png, target_rect).
14. A probe whose written row guard.probe_row_problem accepts -- 2xx, an
    image_*.png of the requested size extracted and stored, delta == 0, no
    LOCK -> state.add_proof(Proof(action, model, size_class, UTC date,
    ledger_id)); verdict "probe" on every probe row. A 2xx that is an HTML
    page, an empty body, a 204 or JSON extracts no image and writes no
    proof: nothing shows a generation happened. The guard counts a proof by
    the same function, so the two routes cannot disagree.
    ORDER (DESIGN): the proof is added AFTER step 15's write_row and before
    INFLIGHT is released, so a proof row never names a ledger row that was
    not written; if add_proof raises, INFLIGHT stays for the author. A probe
    that was interrupted writes no proof (it is not a clean 2xx).
    A written proof is still only PENDING: guard.proof_standing counts it
    once the next balance read equals this row's balance after.
15. state.write_row(row); then state.release_inflight(ledger_id); return
    the row. If write_row raises, INFLIGHT is NOT released: the next call
    is refused on it (condition 10) until the author compares the account
    with the balance it names.

NEVER LOGGED, STORED OR RETURNED: the key, the Authorization header, any
base64 image data. Printing is the CLI's job; this module prints nothing.
Server-supplied text (an error message, a content type) goes through
state.scrub_text -- which removes a whole `pst-` token, Bearer value or
Authorization value, not just its marker -- and is cut to
state.MAX_ROW_STRING before it enters a row, so a server echoing a header
cannot make the row unwritable after the request was sent, and cannot put a
token body in it either.

PUBLIC NAMES
------------
new_correlation_id, run_request, reset_latch_for_checks.
"""
from __future__ import annotations

import hashlib
import secrets
import string
import time
from datetime import datetime, timezone

import tools.nai.transport as nai_transport
from tools.nai import masks
from tools.nai.guard import (Refused, assert_free, boundaries_note,
                             chain_rows, chain_verdict, live_boundary,
                             open_boundaries, probe_row_problem,
                             proof_standing)
from tools.nai.model import (CORRELATION_ID_LEN, GENERATE_URL,
                             IMG2IMG_KEY, INPAINT_STRENGTH_KEY, LEDGER_FIELDS,
                             PROOF_ACTIONS, TIMEOUT_S, Account, LedgerContext,
                             Proof, Request, size_class)
from tools.nai.request import build_body, canonical_json, canonical_sha256
from tools.nai.state import MAX_ROW_STRING, State, scrub_text
from tools.nai.transport import Transport

_SENT_THIS_PROCESS = False
"""Condition 12's latch. Set when INFLIGHT is acquired (step 8)."""

_CID_ALPHABET = string.ascii_letters + string.digits


def new_correlation_id() -> str:
    """model.CORRELATION_ID_LEN characters of [A-Za-z0-9] from `secrets`."""
    return "".join(secrets.choice(_CID_ALPHABET)
                   for _ in range(CORRELATION_ID_LEN))


def _scrub(text: object) -> str | None:
    """Server or exception text made safe for a ledger row."""
    if text is None:
        return None
    return scrub_text(text)[:MAX_ROW_STRING]


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(bytes(data)).hexdigest()


def _refuted_note(state: State, new_row: dict) -> str:
    """Step 6's text naming every proof that `new_row` refutes.

    A proof is named when guard.proof_standing did not refute it over the
    ledger as it stands and does refute it (ok False, NOT ok None) once
    `new_row` is appended -- the same function the guard runs, so the note
    names exactly the proofs every later img2img or infill will WARN about
    for good -- which includes a fall in the read that FOLLOWS one of that
    pair's own sent rows, because a late debit for that request (risk R4)
    and somebody else's spend are byte-identical, and no signature undoes
    it. An unreadable proofs.json is said so instead of raising: the
    warning is recorded either way, and the guard refuses on it by itself.

    The row it names is the last link in `guard.chain_rows`, never `rows[-1]`
    -- a signature annotation sits in the ledger and sent nothing, and naming
    one as "a later img2img call" in the text the author reads to decide
    about money is exactly the confusion the chain filter exists to stop.
    """
    rows = state.rows()
    try:
        proofs = state.proofs()
    except ValueError as exc:
        return (f" proofs.json cannot be read ({exc}), so no proof was "
                f"checked against this read.")
    note = ""
    links = chain_rows(rows)
    last_id = links[-1].get("ledger_id") if links else None
    for proof in proofs:
        was, _ = proof_standing(proof, rows, None)
        now, _why = proof_standing(proof, rows + [new_row], None)
        if was is not False and now is False:
            what = (f"the {proof.action} probe" if last_id == proof.ledger_id
                    else f"a later {proof.action} call")
            note += (f" Ledger row {last_id} was {what} of "
                     f"{proof.model}: this read REFUTES its proof (probe "
                     f"{proof.ledger_id}) for good -- a warning, so "
                     f"{proof.action} is still sent. {_why}")
    return note


def _warning_text(parts: list[str]) -> str | None:
    """Every warning a call met, as ONE row value, or None when there is none.

    Scrubbed like every other server-touched string, and cut to
    MAX_ROW_STRING with the command that prints the whole of it, because a
    ledger row refuses a longer string and a warning that could not be
    written would lose the row it belongs to."""
    if not parts:
        return None
    text = scrub_text(" | ".join(parts))
    if len(text) <= MAX_ROW_STRING:
        return text
    tail = (" [cut here: `python -m tools.nai account` prints every open "
            "boundary in full]")
    return text[:MAX_ROW_STRING - len(tail)] + tail


def _chain_note(state: State, previous: int | None, before: int,
                new_row: dict, open_gaps, chain: str) -> str:
    """Step 6's warning: WHICH boundary THIS call saw, then every older one.

    THE DROP THIS CALL SAW COMES FIRST. When `chain` is "charged" the
    before-read just taken is below the chain, and `new_row` -- a stub
    carrying this call's own ledger id and time, the ones the row it writes
    will carry -- is the row that records it, so the boundary is named with
    that id and the command the note prints can really be typed. Older
    unsigned boundaries are listed after it, with their figures, so no
    warning ever reports the oldest gap and leaves the author with a figure
    that is short.

    `guard.boundaries_note` is the one wording, shared with condition 9's
    verdict and `cli._cmd_account`, so a mutation of it turns every route
    red -- and it classifies rather than assumes: EXTERNAL only where the
    earlier row sent nothing, AMBIGUOUS wherever a request of ours could be
    the cause. Raises ValueError when nothing fell: step 6 only calls this
    when something did.
    """
    gaps = list(open_gaps)
    this_read = chain == "charged"
    if this_read:
        gaps.insert(0, live_boundary(state.rows(), previous, before,
                                     observed_row=new_row.get("ledger_id"),
                                     observed_time=new_row.get("utc_time")))
    if not gaps:
        raise ValueError(f"the balance went {previous} -> {before} but no "
                         f"boundary accounts for it; nothing is sent")
    return boundaries_note(gaps, this_read=this_read)


def _base_row(req: Request, body: dict, context: LedgerContext, *,
              ledger_id: str, kind: str, utc_time: str,
              request_sha256: str, before: Account, chain: str,
              probe: bool) -> dict:
    """Every LEDGER_FIELDS key, filled from the request side; the response
    side starts null and a refused row starts with after == before."""
    params = body["parameters"]
    color_correct = params.get("color_correct")
    if color_correct is None and isinstance(params.get(IMG2IMG_KEY), dict):
        color_correct = params[IMG2IMG_KEY].get("color_correct")
    row = dict.fromkeys(LEDGER_FIELDS)
    row.update({
        "ledger_id": ledger_id,
        "kind": kind,
        "utc_time": utc_time,
        "strip": context.strip,
        "strip_version": context.strip_version,
        "round": context.round,
        "phase": context.phase,
        "lever_changed": context.lever_changed,
        "action": body["action"],
        "model": body["model"],
        "width": params.get("width"),
        "height": params.get("height"),
        "steps": params.get("steps"),
        "scale": params.get("scale"),
        "sampler": params.get("sampler"),
        "noise_schedule": params.get("noise_schedule"),
        "seed": params.get("seed"),
        "extra_noise_seed": params.get("extra_noise_seed"),
        "strength": params.get("strength"),
        "noise": params.get("noise"),
        INPAINT_STRENGTH_KEY: params.get(INPAINT_STRENGTH_KEY),
        "color_correct": color_correct,
        "add_original_image": params.get("add_original_image"),
        "target_cell": context.target_cell,
        "base_caption": req.base_caption,
        "frames": [{"caption": f.caption, "uc": f.uc,
                    "center": [f.center[0], f.center[1]]} for f in req.frames],
        "negative_caption": req.negative,
        "ucPreset": params.get("ucPreset"),
        "qualityToggle": params.get("qualityToggle"),
        "request_sha256": request_sha256,
        "init_png_sha256": _sha(req.image_png),
        "mask_png_sha256": _sha(req.mask_png),
        "mannequin_sha256": context.mannequin_sha256,
        "account_before": before.as_row(),
        "account_after": before.as_row(),
        "delta": 0,
        "chain_ok": chain in ("first", "ok", "refill"),
        "refill_seen": chain == "refill",
        "inconclusive": False,
        "probe_flag_used": context.probe_flag_used,
        "locked": False,
        "verdict": "probe" if probe else None,
    })
    return row


def run_request(req: Request, transport: Transport, state: State, *,
                probe: bool = False,
                context: LedgerContext = LedgerContext()) -> dict:
    """Send `req` once, following the module docstring's sequence exactly.

    Returns the ledger row as written (keys = model.LEDGER_FIELDS). Raises
    guard.Refused when nothing was sent; re-raises an account-read failure,
    or an interrupt (KeyboardInterrupt, SystemExit), after the row is
    written when the request WAS sent. A non-2xx response, a timeout, an
    unreadable ZIP or a balance event is not an exception: the row records
    it and is returned.

    Row values: kind "generation"; utc_time ISO-8601 with Z; the request
    fields from the body (strength / noise / inpaintImg2ImgStrength /
    extra_noise_seed null when absent); frames as [{caption, uc, center:
    [x, y]}]; negative_caption = req.negative; init_png_sha256 /
    mask_png_sha256 of the raw PNG bytes; account_before / account_after =
    Account.as_row(); chain_ok = verdict in ("first", "ok", "refill");
    refill_seen = verdict == "refill"; locked false, always (nothing writes
    LOCK); warning = `_warning_text` of every balance event this call met,
    or null;
    elapsed_ms around the POST only; content_type from the response
    headers (recorded, never gated on); post, reason, sprite_sha256 null;
    verdict "probe" for a probe, else null. LedgerContext fields are copied
    as named. A `refused` row carries the refusal message in error_message
    and a null correlation_id (nothing was sent under it). color_correct is
    the top-level value, else the nested img2img object's, else null.
    """
    global _SENT_THIS_PROCESS

    # 1. condition 12
    if _SENT_THIS_PROCESS:
        raise Refused(12, "this process has already sent a generation "
                          "request; one command sends at most one")
    # 2. the probe flag is the author's
    if probe and not context.probe_flag_used:
        raise Refused(1, "a probe needs the author's own probe flag on the "
                         "command line")
    # 3. condition 10, locally
    if state.locked() or state.inflight():
        present = [name for name, on in (("LOCK", state.locked()),
                                         ("INFLIGHT", state.inflight())) if on]
        detail = (f" (INFLIGHT: {state.inflight_detail()}; compare the "
                  f"account with that balance before deleting it)"
                  if state.inflight() else "")
        raise Refused(10, f"{' and '.join(present)} present under "
                          f"{state.root}{detail}")

    # 4. the body and its identity
    body = build_body(req)
    request_sha256 = canonical_sha256(body)
    ledger_id = state.new_ledger_id()
    cid = new_correlation_id()
    utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # 5. balance before; a failure propagates with nothing sent or written
    before = nai_transport.read_account(transport)

    warnings: list[str] = []

    def refused_row(chain: str, exc: Refused) -> dict:
        row = _base_row(req, body, context, ledger_id=ledger_id,
                        kind="refused", utc_time=utc_time,
                        request_sha256=request_sha256, before=before,
                        chain=chain, probe=probe)
        row["refusal_condition"] = exc.condition
        row["error_message"] = _scrub(exc.message)
        row["warning"] = _warning_text(warnings)
        return row

    # 6. the chain: an unreadable one refuses; a fallen one only warns
    try:
        previous = state.last_balance()
        open_gaps = open_boundaries(state.rows())
    except ValueError as exc:
        raise Refused(9, f"the balance chain cannot be read, so nothing is "
                         f"sent and no row is written: {exc}") from None
    chain = chain_verdict(previous, before.sum)
    if open_gaps or chain == "charged":
        # A stub under THIS call's id, never written: it names the boundary
        # for the row this call does write, and lets _refuted_note judge the
        # proofs over this read exactly as the guard will.
        seen = refused_row(chain, Refused(9, "chain check"))
        warnings.append(
            _chain_note(state, previous, before.sum, seen, open_gaps, chain)
            + _refuted_note(state, seen))

    # 7. the guard: a refusal is still a refusal; a warning is recorded
    try:
        warned = assert_free(body, before, state.proofs(), state,
                             url=GENERATE_URL, probe=probe)
    except Refused as exc:
        if exc.condition != 10:
            state.write_row(refused_row(chain, exc))
        raise
    # condition 9's own text is step 6's, already written naming this row
    warnings.extend(verdict.message for verdict in warned
                    if verdict.condition != 9)

    row = _base_row(req, body, context, ledger_id=ledger_id,
                    kind="generation", utc_time=utc_time,
                    request_sha256=request_sha256, before=before, chain=chain,
                    probe=probe)
    row["correlation_id"] = cid
    row["account_after"] = None
    row["delta"] = None
    row["warning"] = _warning_text(warnings)
    state.validate_row(row)   # unwritable -> ValueError, nothing sent

    # 8. in flight; from here this process has sent
    state.acquire_inflight(ledger_id, before.sum)
    _SENT_THIS_PROCESS = True

    # 9. the bytes that go out
    if req.image_png is not None:
        state.save_blob(req.image_png, "png")
    if req.mask_png is not None:
        state.save_blob(req.mask_png, "png")
    _json_sha, request_path = state.save_blob(canonical_json(body), "json")
    row["request_path"] = request_path
    headers = {"x-correlation-id": cid}

    # 10. exactly one POST; nothing that escapes it skips steps 11-15
    status: int | None = None
    response_headers: dict[str, str] = {}
    response_body = b""
    errors: list[str] = []
    unexpected: BaseException | None = None
    started = time.perf_counter()
    try:
        status, response_headers, response_body = transport.post_json(
            GENERATE_URL, body, headers, TIMEOUT_S)
    except nai_transport.TransportTimeout as exc:
        errors.append(f"timeout: {exc}")
    except nai_transport.TransportError as exc:
        errors.append(f"transport error: {exc}")
    except BaseException as exc:  # recorded, balance still read, re-raised
        errors.append(f"{type(exc).__name__}: {exc}")
        unexpected = exc
        if not isinstance(exc, Exception):
            warnings.append(
                f"{ledger_id} was interrupted ({type(exc).__name__}) while "
                f"its request was being sent, so whether it was charged is "
                f"unknown")
    row["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))

    # 11. balance after, whatever happened -- an interrupt included
    after: Account | None = None
    after_failure: BaseException | None = None
    try:
        after = nai_transport.read_account(transport)
    except BaseException as exc:
        after_failure = exc
        errors.append(f"balance read after the request failed: "
                      f"{type(exc).__name__}: {exc}")

    try:
        # 12. the delta: every balance event is a warning in the row
        if after is None:
            warnings.append(f"the balance read after {ledger_id} failed, "
                            f"so zero cost cannot be shown")
            row["inconclusive"] = True
        else:
            delta = after.sum - before.sum
            row["account_after"] = after.as_row()
            row["delta"] = delta
            if delta < 0:
                reason = (f"OUR CHARGE, measured INSIDE {ledger_id}: the "
                          f"balance fell by {-delta} ({before.sum} -> "
                          f"{after.sum}) between that request's own "
                          f"before-read and its own after-read, with only "
                          f"this {body['action']} of {body['model']} between "
                          f"them. This is not external drift and "
                          f"`acknowledge-drift` cannot touch it")
                if body["action"] in PROOF_ACTIONS:   # a probe or not
                    reason += (f"; {body['action']} is charged, and every "
                               f"further {body['action']} may be too")
                warnings.append(reason)
            row["inconclusive"] = delta > 0
        row["warning"] = _warning_text(warnings)

        # 13. the response
        row["http_status"] = status
        row["content_type"] = _scrub(response_headers.get("content-type"))
        ok_status = status is not None and 200 <= status < 300
        if status is not None and not ok_status:
            errors.append(f"HTTP {status}: "
                          f"{nai_transport.parse_error(response_body)}")
        if ok_status:
            zip_sha, _zip_path = state.save_blob(response_body, "zip")
            row["zip_sha256"] = zip_sha
            try:
                png = nai_transport.unzip_image(
                    response_body, body["parameters"]["width"],
                    body["parameters"]["height"])
            except Exception as exc:  # recorded; the row is still written
                errors.append(f"bad response: {type(exc).__name__}: {exc}")
            else:
                png_sha, png_path = state.save_blob(png, "png")
                row["output_png_sha256"] = png_sha
                row["output_path"] = png_path
                if req.action == "infill" and context.target_rect is not None:
                    try:
                        row["differs_outside_mask"] = masks.differs_outside(
                            req.image_png, png, context.target_rect)
                    except Exception as exc:
                        errors.append(f"differs_outside failed: "
                                      f"{type(exc).__name__}: {exc}")
        row["error_message"] = _scrub("; ".join(errors)) if errors else None

        # 15 (then 14). the row, the proof, the release
        state.write_row(row)
        if probe and probe_row_problem(row) is None:
            state.add_proof(Proof(
                action=body["action"], model=body["model"],
                size_class=size_class(body["parameters"]["width"],
                                      body["parameters"]["height"]),
                date=datetime.now(timezone.utc).date().isoformat(),
                ledger_id=ledger_id))
        state.release_inflight(ledger_id)
    except BaseException:
        # The row or the proof may be missing from the books, so INFLIGHT
        # stays where it is: condition 10 refuses on it, naming the balance
        # before, until the author has compared the account. No LOCK.
        raise

    # an interrupt first, then the after-read's failure, then the POST's
    for raised in (unexpected, after_failure):
        if raised is not None and not isinstance(raised, Exception):
            raise raised
    if after_failure is not None:
        raise after_failure
    if unexpected is not None:
        raise unexpected
    return row


def reset_latch_for_checks() -> None:
    """Clear the condition-12 latch. A check that drives several scripted
    requests in one process calls this between them; the CLI never does."""
    global _SENT_THIS_PROCESS
    _SENT_THIS_PROCESS = False
