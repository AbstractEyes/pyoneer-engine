"""The command line: one human command, at most one generation request.

OWNER: implementer C.

    .venv/Scripts/python.exe -m tools.nai <command> ...

COMMANDS
--------
account                     GET the subscription once; print tier, active,
                            grace, fixed, purchased, sum, the chain verdict
                            against the ledger, EVERY open boundary in full
                            (the same classifier and the same wording the run
                            route refuses with), every accounting figure, and
                            LOCK / INFLIGHT presence. The last line is a
                            WHOLE-STATE verdict, not the tier alone. Writes
                            NOTHING (no row, no LOCK). Exit 0 only when the
                            tier is free-usable AND nothing is outstanding;
                            2 otherwise.
render <recipe> [--character NAME] [--out PNG]
                            mannequin.render_init in the character's colours
                            and garments;
                            write the init PNG (default
                            <state>/renders/<character>_<recipe>_init.png, so
                            two characters never share a file); print the
                            character, the centers and the params sha256. No
                            network. An existing file with DIFFERENT bytes is
                            never overwritten (exit 1).
plan <recipe> --action generate|img2img [--character NAME] [--seed N]
     [--strength S] [--noise N] [--variant full|curated] [--steps N]
     [--scale X] [--color-correct] [--from PNG]
                            --from (img2img only) is the source of a
                            consistency re-pass (brief 3.5), a layout-sized
                            RGB or opaque RGBA PNG; the mannequin init
                            otherwise. The ledger's init_png_sha256 names
                            it, so chained passes (at most 2) can be seen.
                            DRY RUN. recipes.make_request, request.build_body,
                            then print the character and a summary of
                            request.redacted(body)
                            (model, action, size, steps, seed, strength,
                            noise, base caption, each frame's caption and
                            center, request sha256) and one line per
                            guard.evaluate verdict with account=None:
                            conditions 1-7, 10, 11 judged, 8 and 9 printed as
                            "needs the live account read" (and so is 1 when
                            its proof is pending the next balance read). No
                            network. Exit 0 when every offline condition
                            passes, else 2.
run <recipe> --action generate|img2img [same options as plan]
     [--lever NAME] [--round N] [--phase TEXT] [--strip-version N]
                            EXACTLY ONE generation via run.run_request with
                            recipes.context_for(...). Prints the character,
                            ledger id,
                            balance before / after, delta, HTTP status,
                            output blob path, and LOCK if written.
infill <recipe> --cell N --from PNG [--character NAME] [--strength S]
     [--noise N] [--variant full|curated] [--keep-cell] [--seed N]
     [--lever NAME] [--round N] [--phase TEXT] [--strip-version N]
                            EXACTLY ONE infill. --from is the accepted strip
                            (layout-sized RGB or opaque RGBA PNG, such as the
                            blob `run` returned); --strength is the
                            inpaint strength; --keep-cell sets
                            paste_mannequin False. On 2xx also writes
                            masks.composite(source, output, cell rect) as a
                            blob and prints its path.
probe img2img|infill --accept-max-2-anlas [--variant full|curated] [--seed N]
                            Always the default character (no --character).
                            WITHOUT the flag: print what the probe costs at
                            worst (model.PROBE_MAX_ANLAS) and that only the
                            author may pass the flag; exit 2; no network at
                            all. WITH it: guard.probe_request, then
                            run.run_request(probe=True, context with
                            probe_flag_used True). Prints whether a proof row
                            was written.
pixelize PNG --recipe R [--character NAME] [--palette PNG] [--ledger-id ID]
     [--strip-version N] [--colours N] [--remove-orphans] [--out DIR]
                            post.pixelize with the recipe's layout, ground,
                            hold_arc, fps_hint and the centers from
                            mannequin.render_init. Writes strip.png,
                            strip.json (the sidecar), frame_<i>.png and (when
                            --palette is absent) palette.png under DIR
                            (default <state>/sprites/<character>/<recipe>/
                            <first 12 hex of the input PNG's sha256>/). A
                            file already
                            there with DIFFERENT bytes is never overwritten
                            (exit 1, nothing written): a frozen reference
                            palette or an accepted strip is not replaced
                            silently. Prints the validation. Exit 0 when
                            valid, 3 when rejected.
ledger [--last N]           Print the last N rows (default 10), one line
                            each: ledger id, kind, action, model, seed, HTTP
                            status, sum before -> after, delta, locked,
                            refusal condition, verdict -- a `drift` row in
                            its own shape (the boundary it signs, as whose,
                            by whom) and a marker line wherever the balance
                            fell BETWEEN two rows -- then every accounting
                            figure, which are never added together. No
                            network.
acknowledge-drift --anlas N --by NAME --checked TEXT [--previous ID]
                  [--observed ID] [--note TEXT]
                            Sign ONE EXTERNAL boundary: a fall the ledger
                            shows between one row's after-read and the next
                            row's before-read, where the earlier row SENT
                            NOTHING, so no request of ours can have caused
                            it. --anlas must be exactly the figure measured
                            and --checked says what was looked at, because
                            calling a drop somebody else's is a judgement,
                            not a measurement. Appends one `drift` row and
                            prints every figure, every still-open boundary
                            and each proof's standing. That row re-baselines
                            THAT ONE BOUNDARY for the chain; it NEVER
                            restores a proof, never deletes LOCK, and can
                            never reach a charge measured INSIDE one of our
                            own rows. Exit 0 when a row was written, 2
                            otherwise. No network.
resolve-boundary --anlas N --attribute theirs|ours --by NAME --checked TEXT
                 [--previous ID] [--observed ID] [--note TEXT]
                            The louder verb, for an AMBIGUOUS boundary: the
                            earlier row SENT a request of ours, so a debit
                            the server applied after that row's own
                            after-read (risk R4) and somebody else's spend
                            are byte-identical here. Records the author's
                            hand check and WHICH SIDE he attributes it to;
                            `ours` is counted on its own line as his
                            judgement, never as a measurement. Same
                            guarantees, same exits.

INVARIANTS
----------
* ONE REQUEST PER INVOCATION. `run`, `infill` and `probe` call
  run.run_request exactly once; no command loops, sweeps or retries, and no
  option repeats a request.
* EVERY SENDING COMMAND PRINTS the ledger id, the balance before and after,
  and the delta -- on success, HTTP error and timeout alike. When
  run.run_request raises after writing a row (a refusal after the balance
  read, a failed balance read after the send, a Ctrl-C), the rows it wrote
  are printed from the ledger before the error.
* A SENDING COMMAND EXITS 0 only for a 2xx whose PNG was stored and that
  wrote no LOCK; an HTTP error, a timeout, a bad ZIP or a LOCK exits 1 with
  the row printed.
* --seed absent -> a seed from `secrets` in [SEED_MIN, SEED_MAX], printed
  before anything is sent so the author can repeat it.
* --character NAME (render, plan, run, infill, pixelize; default
  characters.DEFAULT_CHARACTER) is a file stem under tools/nai/characters/.
  An unknown name is an argparse error (exit 2, the available files listed)
  before any command body runs, so nothing is built, read or sent; a
  malformed file is refused by its loader, and a file whose tags and anchor
  exceed the token budget in ANY recipe by recipes.build_recipe (exit 1
  each), before a mannequin is drawn or a request exists.
  The character is spelled into every default output path it changes.
* THE PROBE FLAG IS HUMAN-ONLY. Its absence refuses before any network
  call; nothing in this package sets it on anyone's behalf. No option may
  be ABBREVIATED (every parser has allow_abbrev=False): argparse would
  otherwise read `--a` or `--accept` as the probe flag, and a rule that
  matches the literal flag text would not see them.
* NO OUTPUT INSIDE A CHECKOUT EXCEPT ITS data/nai/. Every path this CLI
  writes -- render and pixelize targets, and the state root that run,
  infill and probe write blobs under -- goes through
  `assert_untracked_output` before anything is written or sent: inside this
  checkout or the main checkout it shares git metadata with, only the
  gitignored data/nai/ is writable (data/art/, data/maps/, tools/ and
  data/reference/ are all refused). A path outside every checkout is the
  author's own business.
* Refused -> print str(exc), exit 2. MissingKey, AccountReadError,
  TransportError, ValueError, OSError -> print the message (never a
  traceback with locals, never a header), exit 1. Errors go to stderr, and
  every printed error goes through state.scrub_text first: an
  AccountReadError carries server text, the same sibling route into a
  terminal that a ledger row is into a file.
* `transport` and `state` are injectable so a check can drive every command
  with transport.RecordingTransport and a scratch State; the CLI never
  builds a real transport for `plan`, `render`, `pixelize` or `ledger`, nor
  for `probe` without the flag.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from typing import Callable, Sequence

from tools.nai import (characters, guard, mannequin, masks, post, recipes,
                       request, run)
from tools.nai import transport as nai_transport
from tools.nai.model import (DRIFT_ATTRIBUTIONS, DRIFT_KIND, GENERATE_URL,
                             INPAINT_STRENGTH_KEY,
                             LEDGER_FIELDS, PROBE_MAX_ANLAS, SEED_MAX,
                             SEED_MIN, OPUS_TIER, DEFAULT_COLOURS, VARIANTS)
from tools.nai.state import (REPO_ROOT, RENDERS_DIR, SPRITES_DIR,
                             STATE_SUBPATH, State, main_checkout, scrub_text)
from tools.nai.transport import Transport

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 2
EXIT_REJECTED = 3

PROBE_FLAG = "--accept-max-2-anlas"

_ERRORS = (nai_transport.MissingKey, nai_transport.AccountReadError,
           nai_transport.TransportError, ValueError, OSError)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _generation_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--seed", type=int, default=None,
                   help=f"uint in [{SEED_MIN}, {SEED_MAX}]; random and "
                        f"printed when absent")
    p.add_argument("--strength", type=float, default=None,
                   help="img2img strength (author band 0.35-0.55, default "
                        "0.45)")
    p.add_argument("--noise", type=float, default=None)
    p.add_argument("--variant", choices=VARIANTS, default=None)
    p.add_argument("--steps", type=int, default=None)
    p.add_argument("--scale", type=float, default=None)
    p.add_argument("--color-correct", action="store_true",
                   help="img2img color_correct true (lever L11)")
    p.add_argument("--from", dest="source", default=None,
                   help="img2img only: a layout-sized PNG to re-pass instead "
                        "of the mannequin init (at most 2 chained passes)")


def _character_name(value: str) -> str:
    """argparse `type` for --character: the name when it is one of
    characters.available(), else ArgumentTypeError listing the files."""
    try:
        names = characters.available()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if value not in names:
        raise argparse.ArgumentTypeError(characters.unknown_character(value))
    return value


def _character_option(p: argparse.ArgumentParser) -> None:
    p.add_argument("--character", type=_character_name, metavar="NAME",
                   default=characters.DEFAULT_CHARACTER,
                   help=f"a character file stem under tools/nai/characters/ "
                        f"(default {characters.DEFAULT_CHARACTER})")


def _acknowledged_by(value: str) -> str:
    """A name an acknowledgement is signed with: 1-64 printable ASCII.

    An acknowledgement nobody signed is an acknowledgement nobody can ask
    about later, so the argparse type refuses it (exit 2) before the ledger
    is read.
    """
    text = value.strip()
    if not text or len(text) > 64 or not all(32 <= ord(c) < 127 for c in text):
        raise argparse.ArgumentTypeError(
            f"--by takes 1-64 printable ASCII characters naming who is "
            f"recording this drop, got {value!r}")
    return text


def _checked_text(value: str) -> str:
    """What the author says he checked: 3-400 printable ASCII characters.

    Refused by argparse (exit 2) before the ledger is read, like `--by`. A
    boundary is signed on a judgement, so the judgement is recorded with it;
    "it is theirs" with nothing behind it is what this argument exists to
    stop being the only outcome on offer.
    """
    text = " ".join(value.split())
    if not (3 <= len(text) <= 400) or not all(32 <= ord(c) < 127
                                              for c in text):
        raise argparse.ArgumentTypeError(
            f"--checked takes 3-400 printable ASCII characters saying what "
            f"you checked before signing, got {value!r}")
    return text


def _ledger_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lever", default=None,
                   help="the ONE lever this round changes (ledger)")
    p.add_argument("--round", type=int, default=None)
    p.add_argument("--phase", default=None)
    p.add_argument("--strip-version", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    """The argparse tree for every command in the module docstring."""
    recipe_names = sorted(recipes.RECIPE_NAMES)
    parser = argparse.ArgumentParser(
        prog="python -m tools.nai",
        description="NovelAI V4.5 sprite pipeline, Opus free tier only. "
                    "One command sends at most one generation request.",
        allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    def command(name: str, help: str) -> argparse.ArgumentParser:
        # A subparser does not inherit allow_abbrev: every one says it.
        return sub.add_parser(name, help=help, allow_abbrev=False)

    command("account", "read the balance once; writes nothing")

    p = command("render", help="draw a mannequin init; no network")
    p.add_argument("recipe", choices=recipe_names)
    _character_option(p)
    p.add_argument("--out", default=None)

    p = command("plan", help="dry run: build and judge one request")
    p.add_argument("recipe", choices=recipe_names)
    p.add_argument("--action", choices=("generate", "img2img"), required=True)
    _character_option(p)
    _generation_options(p)

    p = command("run", help="send EXACTLY ONE generate or img2img")
    p.add_argument("recipe", choices=recipe_names)
    p.add_argument("--action", choices=("generate", "img2img"), required=True)
    _character_option(p)
    _generation_options(p)
    _ledger_options(p)

    p = command("infill", help="send EXACTLY ONE infill of one cell")
    p.add_argument("recipe", choices=recipe_names)
    p.add_argument("--cell", type=int, required=True)
    _character_option(p)
    p.add_argument("--from", dest="source", required=True,
                   help="the accepted strip, a layout-sized RGB PNG")
    p.add_argument("--strength", type=float, default=None,
                   help="inpaint strength (band 0.35-0.55 or 1.0)")
    p.add_argument("--noise", type=float, default=None)
    p.add_argument("--variant", choices=VARIANTS, default=None)
    p.add_argument("--keep-cell", action="store_true",
                   help="do not paste the mannequin into the cell first")
    p.add_argument("--seed", type=int, default=None)
    _ledger_options(p)

    p = command("probe", help="the author's cost probe for "
                                     "img2img or infill")
    p.add_argument("action", choices=("img2img", "infill"))
    p.add_argument(PROBE_FLAG, dest="accept_max_2_anlas",
                   action="store_true",
                   help=f"the author accepts up to {PROBE_MAX_ANLAS} Anlas; "
                        f"only the author may pass this")
    p.add_argument("--variant", choices=VARIANTS, default="full")
    p.add_argument("--seed", type=int, default=None)

    p = command("pixelize", help="post-process a strip; no network")
    p.add_argument("png")
    p.add_argument("--recipe", choices=recipe_names, required=True)
    _character_option(p)
    p.add_argument("--palette", default=None,
                   help="the character's reference palette (mode-P PNG)")
    p.add_argument("--ledger-id", default=None)
    p.add_argument("--strip-version", type=int, default=1)
    p.add_argument("--colours", type=int, default=DEFAULT_COLOURS)
    p.add_argument("--remove-orphans", action="store_true",
                   help="lever P8")
    p.add_argument("--out", default=None)

    p = command("ledger", help="print the last ledger rows and the two "
                                "accounting figures")
    p.add_argument("--last", type=int, default=10)

    p = command("acknowledge-drift",
                help="sign an EXTERNAL boundary: a fall across a window in "
                     "which this tool sent nothing")
    _signing_options(p, checked="what you checked before calling this drop "
                                "somebody else's -- the provider's own usage "
                                "page, who else uses the account")

    p = command("resolve-boundary",
                help="record a hand check at an AMBIGUOUS boundary, where a "
                     "request of ours could be the cause")
    _signing_options(p, checked="what you checked by hand: the provider's "
                                "own usage page, the other person, the "
                                "timestamps")
    p.add_argument("--attribute", choices=DRIFT_ATTRIBUTIONS, required=True,
                   help="whose the money was, as you found it: `theirs` or "
                        "`ours` (a charge of ours that landed late). Neither "
                        "restores a refuted proof")
    return parser


def _signing_options(p: argparse.ArgumentParser, *, checked: str) -> None:
    """The options both signing verbs take, declared ONCE.

    `--checked` is required on both: a signature is the author's judgement
    about a shared account, and a figure with nobody's reasoning beside it
    is exactly what a reader cannot use a month later.
    """
    p.add_argument("--anlas", type=int, required=True,
                   help="the exact number of Anlas that fell; a figure that "
                        "is not the measured one is refused")
    p.add_argument("--by", type=_acknowledged_by, required=True,
                   metavar="NAME", help="who is signing this boundary")
    p.add_argument("--checked", type=_checked_text, required=True,
                   metavar="TEXT", help=checked)
    p.add_argument("--previous", default=None, metavar="LEDGER_ID",
                   help="the ledger id on the earlier side of the boundary; "
                        "without it, the oldest open boundary this verb may "
                        "sign")
    p.add_argument("--observed", default=None, metavar="LEDGER_ID",
                   help="the ledger id on the later side of the boundary")
    p.add_argument("--note", default=None,
                   help="anything else worth recording, in ASCII")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inside(path: str, root: str) -> bool:
    target = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    base = os.path.normcase(os.path.realpath(os.path.abspath(root)))
    try:
        return os.path.commonpath([target, base]) == base
    except ValueError:  # different drives
        return False


def checkout_roots() -> tuple[str, ...]:
    """This package's checkout and the main checkout it shares git metadata
    with (the same path twice collapses to one)."""
    roots = [os.path.abspath(REPO_ROOT)]
    main = main_checkout(REPO_ROOT)
    if os.path.normcase(main) != os.path.normcase(roots[0]):
        roots.append(main)
    return tuple(roots)


def assert_untracked_output(path: str) -> None:
    """ValueError when `path` resolves inside any of `checkout_roots()` but
    not inside that checkout's gitignored data/nai/.

    data/art/ (tracked; promotion there is the author's decision), data/maps/
    (law 11), tools/ and data/reference/ (committed CC0 sheets) are all
    refused by that one rule. A path outside every checkout is allowed.
    """
    for root in checkout_roots():
        allowed = os.path.join(root, *STATE_SUBPATH)
        if _inside(path, root) and not _inside(path, allowed):
            art = os.path.join(root, "data", "art")
            why = (" Promoting a sprite to data/art/ is the author's decision, "
                   "made by hand." if _inside(path, art) else "")
            raise ValueError(
                f"refusing to write {path}: it is inside the checkout {root} "
                f"but outside its gitignored {'/'.join(STATE_SUBPATH)}/, so "
                f"it could overwrite or stage a tracked file.{why}")


def _out(text: str = "") -> None:
    print(text)


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _seed(given: int | None) -> int:
    if given is not None:
        _out(f"seed          {given}")
        return given
    seed = SEED_MIN + secrets.randbelow(SEED_MAX - SEED_MIN + 1)
    _out(f"seed          {seed} (random; pass --seed {seed} to repeat)")
    return seed


def _overrides(args: argparse.Namespace) -> dict:
    out: dict = {}
    for name in ("variant", "steps", "scale", "strength", "noise"):
        value = getattr(args, name, None)
        if value is not None:
            out[name] = value
    if getattr(args, "color_correct", False):
        out["color_correct"] = True
    source = getattr(args, "source", None)
    if source is not None:
        with open(source, "rb") as handle:
            out["source_png"] = handle.read()
        _out(f"from          {source} (sha256 "
             f"{hashlib.sha256(out['source_png']).hexdigest()})")
    return out


def _fmt(value: object) -> str:
    return "-" if value is None else str(value)


def _sum_of(account: object) -> object:
    return account.get("sum") if isinstance(account, dict) else None


def _print_sent(row: dict, state: State) -> None:
    before = _sum_of(row.get("account_before"))
    after = _sum_of(row.get("account_after"))
    _out(f"ledger id     {row.get('ledger_id')} ({row.get('kind')})")
    _out(f"balance       before {_fmt(before)} -> after "
         f"{'unknown' if after is None else after}, delta "
         f"{'unknown' if row.get('delta') is None else row.get('delta')}")
    if row.get("kind") == "refused":
        _out(f"http status   not sent (refused by condition "
             f"{row.get('refusal_condition')})")
    else:
        _out(f"http status   {_fmt(row.get('http_status'))}")
    if row.get("output_path"):
        _out(f"output        "
             f"{os.path.normpath(os.path.join(state.root, row['output_path']))}")
    if row.get("inconclusive"):
        _out("inconclusive  the balance rose or could not be read: a refill "
             "can hide a charge")
    if row.get("error_message"):
        _out(f"error         {row['error_message']}")
    if row.get("locked"):
        _out(f"LOCK          written: {state.lock_path} -- everything is "
             f"refused until the author deletes it by hand")


def _send(req, transport: Transport | None, state: State, *, probe: bool,
          context) -> dict:
    """run.run_request once; print every row it wrote, raise or not.

    The ONE place the state root of a sending command is checked against
    data/art, before the ledger is read or anything is sent.
    """
    assert_untracked_output(state.root)
    seen = len(state.rows())
    if transport is None:
        transport = nai_transport.UrllibTransport()
    try:
        row = run.run_request(req, transport, state, probe=probe,
                              context=context)
    except BaseException:
        for written in state.rows()[seen:]:
            _print_sent(written, state)
        raise
    _print_sent(row, state)
    return row


def _sent_exit(row: dict) -> int:
    """EXIT_OK only for a 2xx with a stored output PNG and no LOCK."""
    status = row.get("http_status")
    clean = (isinstance(status, int) and 200 <= status < 300
             and row.get("output_path") and not row.get("locked"))
    return EXIT_OK if clean else EXIT_ERROR


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _cmd_account(args, transport, state: State) -> int:
    if transport is None:
        transport = nai_transport.UrllibTransport()
    account = nai_transport.read_account(transport)
    _out(f"tier          {account.tier}"
         f"{' (Opus)' if account.tier == OPUS_TIER else ''}")
    _out(f"active        {account.active}")
    _out(f"grace period  {_fmt(account.grace)}")
    _out(f"fixed         {account.fixed}")
    _out(f"purchased     {account.purchased}")
    _out(f"sum           {account.sum}")
    problems: list[str] = []
    gaps: list = []
    unreadable = None
    try:
        rows = state.rows()
        gaps = list(guard.open_boundaries(rows))
        previous = state.last_balance()
    except ValueError as exc:
        unreadable = scrub_text(exc)
        problems.append("the balance chain cannot be read")
        _out(f"chain         CANNOT BE READ: {unreadable}")
    else:
        verdict = guard.chain_verdict(previous, account.sum)
        if verdict == "charged":
            # THE SAME CLASSIFIER THE RUN ROUTE USES. This line used to
            # state, as fact, that nothing this tool sent was charged --
            # including in the one case guard refuses to classify -- and to
            # advise signing our own possible charge off as somebody else's.
            gaps.insert(0, guard.live_boundary(rows, previous, account.sum))
        meaning = {
            "first": "empty ledger, nothing to compare",
            "ok": "equals the last ledger row",
            "refill": "above the last ledger row (a refill)",
            "charged": "BELOW the last ledger row -- see the boundary below",
        }[verdict]
        if verdict != "charged" and gaps:
            meaning += (", but the chain BELOW it is broken: see the "
                        "boundaries below")
        _out(f"chain         {verdict}: last row {_fmt(previous)}, now "
             f"{account.sum} -- {meaning}")
    if unreadable is None:
        _out("boundaries    " + ("none open" if not gaps else
                                 f"{len(gaps)} OPEN, "
                                 f"{sum(g.delta for g in gaps):+d} Anlas"))
        for gap in gaps:
            problems.append(f"{gap.previous_row}->{gap.observed_row} unsigned")
            _out(f"              {guard.boundary_note(gap)}")
    try:
        for line in _accounting_lines(state):
            _out(line)
    except ValueError as exc:
        problems.append("the books cannot be read")
        _out(f"accounting    CANNOT BE READ: {scrub_text(exc)}")
    _out(f"LOCK          {'PRESENT ' + state.lock_path if state.locked() else 'absent'}")
    _out(f"INFLIGHT      {'PRESENT ' + state.inflight_path if state.inflight() else 'absent'}")
    free = (account.tier == OPUS_TIER and account.active is True
            and account.grace is not True)
    if not free:
        problems.append("the tier is not free-usable (needs tier 3, active, "
                        "not in grace)")
    if state.locked():
        problems.append("LOCK present")
    if state.inflight():
        problems.append("INFLIGHT present")
    # THE LAST LINE IS THE WHOLE STATE, not the tier alone: "free tier
    # usable" used to read as the bottom line while LOCK, an unsigned
    # boundary and an unreadable chain sat on the same screen.
    _out("verdict       " + ("free tier usable, nothing outstanding"
                             if not problems else
                             f"REFUSED: {'; '.join(problems)}"))
    return EXIT_OK if free and not problems else EXIT_REFUSED


def _cmd_render(args, transport, state: State) -> int:
    recipe = recipes.get_recipe(args.recipe, args.character)
    colours = recipe.identity.as_dict()
    garments = recipe.identity.garments
    out = args.out or os.path.join(state.root, RENDERS_DIR,
                                   f"{args.character}_{recipe.name}_init.png")
    assert_untracked_output(out)
    png, centers = mannequin.render_init(recipe.layout, recipe.poses, colours,
                                         garments=garments)
    if args.out is None:
        state.subdir(RENDERS_DIR)
    _write_all([(out, png)])
    layout = recipe.layout
    _out(f"render        {out}")
    _out(f"character     {args.character}")
    _out(f"layout        {layout.name} {layout.width}x{layout.height} "
         f"k={layout.k}, {layout.count} frames")
    for i, center in enumerate(centers):
        _out(f"frame {i}       center {center}")
    params = mannequin.params_sha256(layout, recipe.poses, colours,
                                     garments=garments)
    _out(f"params sha256 {params}")
    _out(f"png sha256    {hashlib.sha256(png).hexdigest()}")
    return EXIT_OK


def _cmd_plan(args, transport, state: State) -> int:
    _out(f"plan          {args.recipe} {args.action} (dry run: nothing is "
         f"sent)")
    _out(f"character     {args.character}")
    seed = _seed(args.seed)
    req = recipes.make_request(args.recipe, args.action, seed,
                               character=args.character, **_overrides(args))
    body = request.build_body(req)
    shown = request.redacted(body)
    params = shown["parameters"]
    _out(f"model         {shown['model']}")
    _out(f"action        {shown['action']}")
    _out(f"size          {params['width']}x{params['height']}")
    _out(f"steps         {params['steps']}   scale {params['scale']}   "
         f"sampler {params['sampler']}/{params['noise_schedule']}")
    _out(f"strength      {_fmt(params.get('strength'))}   noise "
         f"{_fmt(params.get('noise'))}   inpaint "
         f"{_fmt(params.get(INPAINT_STRENGTH_KEY))}   color_correct "
         f"{_fmt(params.get('color_correct'))}")
    if "image" in params:
        _out(f"image         {params['image']}")
    if "mask" in params:
        _out(f"mask          {params['mask']}")
    _out(f"base caption  {shown['input']}")
    _out(f"negative      {params['negative_prompt']}")
    for i, frame in enumerate(params["characterPrompts"]):
        center = frame["center"]
        _out(f"frame {i}       ({center['x']}, {center['y']}) "
             f"{frame['prompt']}"
             + (f"  [uc: {frame['uc']}]" if frame["uc"] else ""))
    _out(f"request sha256 {request.canonical_sha256(body)}")
    verdicts = guard.evaluate(body, None, state.proofs(), state,
                              url=GENERATE_URL)
    _out("conditions")
    offline_ok = True
    for verdict in verdicts:
        title = guard.CONDITION_TITLES.get(verdict.condition, "")
        if verdict.condition not in guard.OFFLINE_CONDITIONS:
            mark = "needs the live account read"
        elif verdict.ok is None:
            # condition 1 with a proof pending its read, or condition 9 with
            # its ledger half clean and only the live balance missing. A
            # condition 9 that FAILS offline -- an unsigned boundary already
            # in the ledger -- falls through to FAIL below, so `plan` can
            # never report a clean bill over books with money missing.
            mark = "needs the live account read"
        elif verdict.ok is True:
            mark = "ok"
        else:
            mark = "FAIL"
            offline_ok = False
        detail = (f" -- {verdict.message}"
                  if verdict.message and verdict.message != mark else "")
        _out(f"  {verdict.condition:>2} [{mark}] {title}{detail}")
    for condition in guard.OFFLINE_CONDITIONS:
        if not any(v.condition == condition for v in verdicts):
            offline_ok = False
            _out(f"  {condition:>2} [FAIL] no verdict returned")
    _out("verdict       " + ("every offline condition passes" if offline_ok
                             else "REFUSED offline"))
    return EXIT_OK if offline_ok else EXIT_REFUSED


def _cmd_run(args, transport, state: State) -> int:
    _out(f"run           {args.recipe} {args.action} (ONE request)")
    _out(f"character     {args.character}")
    seed = _seed(args.seed)
    req = recipes.make_request(args.recipe, args.action, seed,
                               character=args.character, **_overrides(args))
    context = recipes.context_for(
        args.recipe, character=args.character,
        strip_version=args.strip_version, round=args.round,
        phase=args.phase, lever_changed=args.lever)
    row = _send(req, transport, state, probe=False, context=context)
    return _sent_exit(row)


def _cmd_infill(args, transport, state: State) -> int:
    _out(f"infill        {args.recipe} cell {args.cell} (ONE request)")
    _out(f"character     {args.character}")
    with open(args.source, "rb") as handle:
        source = handle.read()
    seed = _seed(args.seed)
    overrides: dict = {"source_png": source, "cell": args.cell,
                       "paste_mannequin": not args.keep_cell}
    if args.variant is not None:
        overrides["variant"] = args.variant
    if args.strength is not None:
        overrides["inpaint_strength"] = args.strength
    if args.noise is not None:
        overrides["noise"] = args.noise
    req = recipes.make_request(args.recipe, "infill", seed,
                               character=args.character, **overrides)
    context = recipes.context_for(
        args.recipe, character=args.character, cell=args.cell,
        strip_version=args.strip_version, round=args.round,
        phase=args.phase, lever_changed=args.lever)
    row = _send(req, transport, state, probe=False, context=context)
    status = row.get("http_status")
    if (isinstance(status, int) and 200 <= status < 300
            and row.get("output_png_sha256")):
        returned = state.read_blob(row["output_png_sha256"], "png")
        rect = recipes.get_recipe(
            args.recipe, args.character).layout.cells[args.cell].rect_canvas
        merged = masks.composite(source, returned, rect)
        _sha, rel = state.save_blob(merged, "png")
        _out(f"composite     {os.path.normpath(os.path.join(state.root, rel))}")
        _out(f"differs outside mask {_fmt(row.get('differs_outside_mask'))}")
    return _sent_exit(row)


def _cmd_probe(args, transport, state: State) -> int:
    if not args.accept_max_2_anlas:
        _out(f"probe {args.action}: NOT SENT.")
        _out(f"A probe measures whether {args.action} is free on this "
             f"account. If it is charged, it costs at most "
             f"{PROBE_MAX_ANLAS} Anlas by the client formula.")
        _out(f"Only the author may pass {PROBE_FLAG}; an agent never "
             f"passes it on anyone's behalf.")
        return EXIT_REFUSED
    _out(f"probe         {args.action} {args.variant} (ONE request, the "
         f"author accepted at most {PROBE_MAX_ANLAS} Anlas)")
    seed = _seed(args.seed)
    req = guard.probe_request(args.action, seed=seed, variant=args.variant)
    context = recipes.context_for(
        "walk", cell=1 if args.action == "infill" else None, phase="probe",
        probe_flag_used=True)
    before = {(p.action, p.model) for p in state.proofs()}
    row = _send(req, transport, state, probe=True, context=context)
    added = [p for p in state.proofs() if (p.action, p.model) not in before]
    if added:
        for proof in added:
            _out(f"proof         WRITTEN: {proof.action} {proof.model} "
                 f"{proof.size_class} ({proof.ledger_id}); it counts once the "
                 f"next balance read still shows "
                 f"{_fmt(_sum_of(row.get('account_after')))}")
    else:
        _out(f"proof         not written (delta {_fmt(row.get('delta'))}, "
             f"HTTP {_fmt(row.get('http_status'))}); {args.action} stays "
             f"refused")
    return _sent_exit(row)


def _write_all(files: list[tuple[str, bytes]]) -> None:
    """Write every file, or none: an existing file with different bytes
    refuses the whole set. The caller has passed every path through
    assert_untracked_output."""
    for path, data in files:
        if os.path.exists(path):
            with open(path, "rb") as handle:
                if handle.read() != data:
                    raise ValueError(
                        f"refusing to overwrite {path}: it exists with "
                        f"different bytes (bump --strip-version or pass "
                        f"--out)")
    for path, data in files:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if os.path.exists(path):
            continue
        with open(path, "wb") as handle:
            handle.write(data)


def _cmd_pixelize(args, transport, state: State) -> int:
    recipe = recipes.get_recipe(args.recipe, args.character)
    with open(args.png, "rb") as handle:
        png = handle.read()
    palette = None
    if args.palette is not None:
        with open(args.palette, "rb") as handle:
            palette = handle.read()
    out_dir = args.out or os.path.join(
        state.root, SPRITES_DIR, args.character, recipe.name,
        hashlib.sha256(png).hexdigest()[:12])
    assert_untracked_output(out_dir)
    _, centers = mannequin.render_init(recipe.layout, recipe.poses,
                                       recipe.identity.as_dict(),
                                       garments=recipe.identity.garments)
    result = post.pixelize(
        png, recipe.layout, centers=centers, ground=recipe.ground,
        hold_arc=recipe.hold_arc, palette_png=palette, colours=args.colours,
        fps_hint=recipe.fps_hint, ledger_id=args.ledger_id,
        strip_version=args.strip_version, remove_orphans=args.remove_orphans)
    files = [(os.path.join(out_dir, "strip.png"), result.strip_rgba_png),
             (os.path.join(out_dir, "strip.json"),
              (json.dumps(result.sidecar, indent=2) + "\n").encode("ascii"))]
    files += [(os.path.join(out_dir, f"frame_{i}.png"), data)
              for i, data in enumerate(result.frames)]
    if palette is None:
        files.append((os.path.join(out_dir, "palette.png"),
                      result.palette_png))
    if args.out is None:
        state.subdir(SPRITES_DIR)
    _write_all(files)
    sidecar = result.sidecar
    validation = result.validation
    _out(f"pixelize      {args.png} as {recipe.name} ({recipe.layout.name})")
    _out(f"character     {args.character}")
    _out(f"grid          k={result.k} phase={list(result.phase)}")
    _out(f"frames        {sidecar['count']} x {sidecar['frame_w']}x"
         f"{sidecar['frame_h']}, anchor_x {sidecar['anchor_x']}, "
         f"baseline_y {sidecar['baseline_y']}")
    _out(f"palette       {len(sidecar['palette'])} used: "
         f"{' '.join(sidecar['palette'])}")
    _out(f"background    {json.dumps(validation.get('background'))}")
    for key in post.VALIDATION_KEYS:
        entry = validation[key]
        _out(f"  [{'ok' if entry['ok'] else 'FAIL'}] {key}: "
             f"{json.dumps(entry['detail'])}")
    if validation.get("flags"):
        _out(f"flags         {', '.join(validation['flags'])}")
    _out(f"written       {out_dir}")
    if palette is None:
        _out(f"palette.png   the reference palette: pass --palette "
             f"{os.path.join(out_dir, 'palette.png')} for this character's "
             f"later strips")
    _out("verdict       " + ("valid" if validation["ok"] else
                             "REJECTED (nothing was repaired)"))
    return EXIT_OK if validation["ok"] else EXIT_REJECTED


def _accounting_lines(state: State) -> list[str]:
    """Every accounting figure, one per line, NEVER added together.

    Each command that summarises the ledger prints these same lines from
    this one function, so a reader sees the same words wherever he looks and
    a mutation of it turns every route red.

    THE LINE THAT HAD TO EXIST is `unsigned`: money the ledger MEASURED
    leaving the account at a boundary nobody has signed for. Without it the
    default state of these books was "nothing left the account" until the
    author typed a command -- on a real ledger, `theirs +0` printed directly
    under seventeen rows across which 1911 Anlas had gone. The spent and
    refilled halves of OURS are separate for the same reason: netting them
    lets a refill inside one row cancel a charge measured inside another.
    """
    books = guard.accounting(state.rows())
    lines = [
        f"ours spent    {books.ours_spent:+d} Anlas across "
        f"{books.rows_counted} rows this tool wrote -- each row's OWN "
        f"after-read minus its own before-read, so a charge shows negative. "
        f"THIS is what the tool has been measured to cost.",
        f"ours refilled {books.ours_refilled:+d} Anlas that arrived INSIDE "
        f"one of our own rows"
        + (f" ({', '.join(books.refilled_rows)})" if books.refilled_rows
           else "")
        + " -- never netted against what was spent.",
        f"theirs        {books.theirs_signed:+d} Anlas across "
        f"{books.signatures_counted} signature(s), the part recorded by hand "
        f"as SOMEBODY ELSE'S on a shared account. A judgement, not a "
        f"measurement.",
    ]
    if books.ours_signed:
        lines.append(f"ours by hand  {books.ours_signed:+d} Anlas signed at "
                     f"an AMBIGUOUS boundary as a late charge of ours, from "
                     f"a hand check rather than a measurement.")
    if books.unsigned:
        listed = ", ".join(f"{gap.previous_row}->{gap.observed_row} "
                           f"({gap.delta:+d}{', AMBIGUOUS' if gap.ambiguous else ''})"
                           for gap in books.open_boundaries)
        lines.append(f"UNSIGNED      {books.unsigned:+d} Anlas across "
                     f"{len(books.open_boundaries)} boundary(ies) NOT in any "
                     f"figure above: {listed}. This money HAS left the "
                     f"account. Sign each one -- acknowledge-drift for an "
                     f"external boundary, resolve-boundary for an ambiguous "
                     f"one.")
    if books.unmeasured:
        lines.append(f"unmeasured    {len(books.unmeasured)} row(s) whose "
                     f"after-read failed, counted in NO figure above: "
                     f"{', '.join(books.unmeasured)}")
    return lines


def _sign_boundary(args, state: State, *, external: bool) -> int:
    """`acknowledge-drift` and `resolve-boundary`: ONE implementation.

    The two verbs differ in exactly three things -- which class of boundary
    they may sign, what `drift_attribution` they write, and how loud they
    are -- so everything else is here and neither can grow its own copy of
    the rule (CLAUDE.md's sibling-route warning).

    THE SEQUENCE, in this order, because it is money:
      * refuse while INFLIGHT exists. A signature is a claim about a window
        in which nothing of ours was outstanding, and INFLIGHT is this
        tool's own statement that something is.
      * hold INFLIGHT ourselves across the read and the write, so two
        processes cannot both read the ledger before either appends and sign
        one boundary twice; re-read the ledger inside the hold and refuse if
        the boundary or the figure moved.
      * refuse an --anlas that is not the figure measured, and refuse a
        boundary of the wrong class for this verb.
      * write ONE `drift` row, then print the books, every still-open
        boundary IN FULL, and what the signature did NOT do.

    It never deletes LOCK -- a signature that could would be able to clear
    the LOCK a charge measured INSIDE one of our own rows wrote -- and it
    never restores a proof: `guard.proof_standing` reads no allowance, and
    the command prints each proof's standing before and after so the author
    can see that for himself.
    """
    verb = "acknowledge-drift" if external else "resolve-boundary"
    if state.inflight():
        _err(f"refused: INFLIGHT is present under {state.root} "
             f"({state.inflight_detail()}). A request of ours is recorded as "
             f"outstanding, so this is not a window in which nothing of ours "
             f"was in the air, and signing it now could book our own charge "
             f"to somebody else. Finish or resolve that request first.")
        return EXIT_REFUSED

    def chosen(rows):
        """The boundary this command is about, or (None, message)."""
        gaps = guard.open_boundaries(rows)
        if not gaps:
            return None, ("nothing to sign: no unsigned fall between two "
                          "ledger rows.")
        if args.previous is None and args.observed is None:
            wanted = [gap for gap in gaps if gap.ambiguous != external]
            if not wanted:
                return None, (f"nothing for {verb} to sign: every open "
                              f"boundary is "
                              f"{'ambiguous' if external else 'external'}. "
                              f"{guard.boundaries_note(gaps)}")
            return wanted[0], ""
        wanted = [gap for gap in gaps
                  if (args.previous in (None, gap.previous_row)
                      and args.observed in (None, gap.observed_row))]
        if not wanted:
            return None, (f"no open boundary matches --previous "
                          f"{args.previous!r} --observed {args.observed!r}. "
                          f"{guard.boundaries_note(gaps)}")
        return wanted[0], ""

    rows = state.rows()
    gap, why = chosen(rows)
    if gap is None:
        _err(f"refused: {why}")
        _out("A charge measured INSIDE one of our own rows is not signed "
             "here: read LOCK, check the account by hand.")
        return EXIT_REFUSED
    if gap.ambiguous == external:
        _err(f"refused: {guard.boundary_note(gap)}")
        return EXIT_REFUSED
    if args.anlas != -gap.delta:
        _err(f"refused: --anlas {args.anlas} is not the {-gap.delta} Anlas "
             f"that fell: {gap.describe}. Type the figure you are signing "
             f"for; one signature covers one boundary, exactly.")
        return EXIT_REFUSED

    before_standing = _proof_standing(state)
    holder = f"{verb}-{state.new_ledger_id()}"
    try:
        state.acquire_inflight(holder, gap.low)
    except guard.Refused as exc:
        _err(f"refused: {exc.message} Another process may be signing this "
             f"same boundary; nothing was written.")
        return EXIT_REFUSED
    try:
        fresh = state.rows()
        again, _why = chosen(fresh)
        if again != gap:
            _err(f"refused: the ledger changed while this command was "
                 f"reading it -- the boundary is now "
                 f"{'nothing' if again is None else again.describe}, not "
                 f"{gap.describe}. Nothing was written; run {verb} again.")
            return EXIT_REFUSED
        row = dict.fromkeys(LEDGER_FIELDS)
        row.update({
            "ledger_id": state.new_ledger_id(),
            "kind": DRIFT_KIND,
            "utc_time": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"),
            "account_before": {"sum": gap.high},
            "account_after": {"sum": gap.low},
            "delta": gap.delta,
            "reason": scrub_text(args.note) if args.note else None,
            "drift_previous_row": gap.previous_row,
            "drift_observed_row": gap.observed_row,
            "drift_acknowledged_by": scrub_text(args.by),
            "drift_attribution": "theirs" if external else args.attribute,
            "drift_checked": scrub_text(args.checked),
        })
        state.write_row(row)
    finally:
        state.release_inflight(holder)
    _out(f"recorded      {row['ledger_id']}")
    _out(f"boundary      {gap.describe}")
    _out(f"as            {row['drift_attribution']}"
         + ("" if external else " -- your judgement at an AMBIGUOUS "
                               "boundary, not a measurement"))
    _out(f"by            {row['drift_acknowledged_by']}")
    _out(f"checked       {row['drift_checked']}")
    if row["reason"]:
        _out(f"note          {row['reason']}")
    for line in _accounting_lines(state):
        _out(line)
    still = guard.open_boundaries(state.rows())
    _out("chain         " + ("re-baselined: this boundary no longer refuses"
                             if not still else
                             f"STILL OPEN: {guard.boundaries_note(still)}"))
    for line in _proof_lines(before_standing, _proof_standing(state)):
        _out(line)
    _out("LOCK          " + (f"PRESENT {state.lock_path} -- this command "
                             f"never deletes it. Read it, check the account, "
                             f"then delete it by hand." if state.locked()
                             else "absent"))
    return EXIT_OK


def _proof_standing(state: State) -> dict:
    """{(action, model): guard.proof_standing's ok} over the ledger as it is.

    Read either side of a signature so the command can SAY whether signing
    moved a proof. It must not: `guard.proof_standing` reads no allowance,
    so a signature can never re-arm img2img, and printing the two sides is
    how the author sees that rather than being told it.
    """
    try:
        rows, proofs = state.rows(), state.proofs()
    except ValueError:
        return {}
    return {(proof.action, proof.model): guard.proof_standing(proof, rows,
                                                              None)[0]
            for proof in proofs}


def _proof_lines(before: dict, after: dict) -> list[str]:
    """One line per proof, saying whether the signature moved it. It cannot."""
    lines = []
    for pair, was in before.items():
        now = after.get(pair)
        action, model = pair
        word = {True: "stands", False: "REFUTED for good",
                None: "pending the next balance read"}
        lines.append(f"proof         {action} ({model}): {word[now]}"
                     + ("" if now == was else
                        f" -- it was {word[was]} before this row; a signature "
                        f"must never move a proof, so this is a defect"))
    if lines:
        lines.append("              A signature records WHOSE money left a "
                     "shared account. It never measures an action free: a "
                     "refuted proof is re-measured by removing it from "
                     "proofs.json by hand and probing again.")
    return lines


def _cmd_acknowledge_drift(args, transport, state: State) -> int:
    """Sign an EXTERNAL boundary as somebody else's. See `_sign_boundary`."""
    return _sign_boundary(args, state, external=True)


def _cmd_resolve_boundary(args, transport, state: State) -> int:
    """Record a hand check at an AMBIGUOUS boundary. See `_sign_boundary`.

    The louder verb, and deliberately harder to type: at an ambiguous
    boundary a request of ours went out, so a debit the server applied late
    (risk R4) and somebody else's spend are byte-identical in this ledger.
    `--attribute` makes the author say which he found, after `--checked`
    makes him say what he looked at.
    """
    return _sign_boundary(args, state, external=False)


def _cmd_ledger(args, transport, state: State) -> int:
    rows = state.rows()
    if not rows:
        _out(f"ledger is empty: {state.ledger_path}")
        for line in _accounting_lines(state):
            _out(line)
        return EXIT_OK
    try:
        signed = {(s.previous_row, s.observed_row): s
                  for s in guard.signatures(rows)}
        open_gaps = {(g.previous_row, g.observed_row): g
                     for g in guard.open_boundaries(rows)}
    except ValueError as exc:
        signed, open_gaps = {}, {}
        _out(f"boundaries    CANNOT BE READ: {scrub_text(exc)}")
    shown = state.last_rows(args.last)
    previous_link = None
    for row in shown:
        if row.get("kind") == DRIFT_KIND:
            # A SIGNATURE IS NOT A REQUEST, so it does not wear a request's
            # columns: the row a reader must be able to reconstruct the day
            # from is the boundary, as whose, by whom, on what check.
            _out("  ".join((
                _fmt(row.get("ledger_id")), "drift",
                f"{_sum_of(row.get('account_before'))} -> "
                f"{_sum_of(row.get('account_after'))}",
                f"{_fmt(row.get('delta'))}",
                f"between {_fmt(row.get('drift_previous_row'))} and "
                f"{_fmt(row.get('drift_observed_row'))}",
                f"as {_fmt(row.get('drift_attribution'))}",
                f"by {_fmt(row.get('drift_acknowledged_by'))}",
                f"checked {_fmt(row.get('drift_checked'))}",
            )) + (f"  note {row['reason']}" if row.get("reason") else ""))
            continue
        before = _sum_of(row.get("account_before"))
        after = _sum_of(row.get("account_after"))
        key = (None if previous_link is None
               else (str(previous_link.get("ledger_id")),
                     str(row.get("ledger_id"))))
        # THE GAP IS MARKED WHERE IT HAPPENED. Fourteen lines of an
        # unchanged balance followed by a lower one said nothing about the
        # money that left between them.
        if key in open_gaps:
            gap = open_gaps[key]
            _out(f"  -- {-gap.delta} Anlas left the account here, UNSIGNED "
                 f"({'AMBIGUOUS' if gap.ambiguous else 'external'}: "
                 f"{gap.high} -> {gap.low}) --")
        elif key in signed:
            sign = signed[key]
            _out(f"  -- {-sign.delta} Anlas left the account here, signed as "
                 f"{sign.attribution} by {sign.by} (row {sign.ledger_id}) --")
        previous_link = row
        _out("  ".join((
            _fmt(row.get("ledger_id")),
            _fmt(row.get("kind")),
            _fmt(row.get("action")),
            _fmt(row.get("model")),
            f"seed {_fmt(row.get('seed'))}",
            f"http {_fmt(row.get('http_status'))}",
            f"sum {_fmt(before)} -> {_fmt(after)}",
            f"delta {_fmt(row.get('delta'))}",
            f"locked {_fmt(row.get('locked'))}",
            f"refused {_fmt(row.get('refusal_condition'))}",
            f"verdict {_fmt(row.get('verdict'))}",
        )))
    for line in _accounting_lines(state):
        _out(line)
    return EXIT_OK


_COMMANDS: dict[str, Callable[..., int]] = {
    "account": _cmd_account,
    "render": _cmd_render,
    "plan": _cmd_plan,
    "run": _cmd_run,
    "infill": _cmd_infill,
    "probe": _cmd_probe,
    "pixelize": _cmd_pixelize,
    "ledger": _cmd_ledger,
    "acknowledge-drift": _cmd_acknowledge_drift,
    "resolve-boundary": _cmd_resolve_boundary,
}


def main(argv: Sequence[str] | None = None, *,
         transport: Transport | None = None,
         state: State | None = None) -> int:
    """Parse `argv` (sys.argv[1:] when None) and run one command.

    `transport` None -> transport.UrllibTransport(), constructed only by the
    commands that use the network (account, run, infill, probe with the
    flag). `state` None -> State() (data/nai/ in the main checkout, shared
    by every worktree). Returns an exit
    code from the EXIT_* constants; argparse usage errors exit 2.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(None if argv is None else list(argv))
    except SystemExit as exc:
        if exc.code is None:
            return EXIT_OK
        return exc.code if isinstance(exc.code, int) else EXIT_REFUSED
    try:
        if state is None:
            state = State()   # ValueError for a .git it cannot read
        return _COMMANDS[args.command](args, transport, state)
    except guard.Refused as exc:
        _err(scrub_text(exc))
        return EXIT_REFUSED
    except _ERRORS as exc:
        _err(f"error: {scrub_text(exc)}")
        return EXIT_ERROR
