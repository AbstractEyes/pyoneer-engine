"""The command line: one human command, at most one generation request.

OWNER: implementer C.

    .venv/Scripts/python.exe -m tools.nai <command> ...

COMMANDS
--------
account                     GET the subscription once; print tier, active,
                            grace, fixed, purchased, sum, the chain verdict
                            against the ledger, LOCK / INFLIGHT presence.
                            Writes NOTHING (no row, no LOCK). Exit 0 when
                            tier 3, active and not in grace, else 2.
render <recipe> [--out PNG] mannequin.render_init; write the init PNG (default
                            <state>/renders/<recipe>_init.png); print the
                            centers and the params sha256. No network. An
                            existing file with DIFFERENT bytes is never
                            overwritten (exit 1).
plan <recipe> --action generate|img2img [--seed N] [--strength S]
     [--noise N] [--variant full|curated] [--steps N] [--scale X]
     [--color-correct] [--from PNG]
                            --from (img2img only) is the source of a
                            consistency re-pass (brief 3.5), a layout-sized
                            RGB or opaque RGBA PNG; the mannequin init
                            otherwise. The ledger's init_png_sha256 names
                            it, so chained passes (at most 2) can be seen.
                            DRY RUN. recipes.make_request, request.build_body,
                            then print a summary of request.redacted(body)
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
                            recipes.context_for(...). Prints ledger id,
                            balance before / after, delta, HTTP status,
                            output blob path, and LOCK if written.
infill <recipe> --cell N --from PNG [--strength S] [--noise N]
     [--variant full|curated] [--keep-cell] [--seed N]
     [--lever NAME] [--round N] [--phase TEXT] [--strip-version N]
                            EXACTLY ONE infill. --from is the accepted strip
                            (layout-sized RGB or opaque RGBA PNG, such as the
                            blob `run` returned); --strength is the
                            inpaint strength; --keep-cell sets
                            paste_mannequin False. On 2xx also writes
                            masks.composite(source, output, cell rect) as a
                            blob and prints its path.
probe img2img|infill --accept-max-2-anlas [--variant full|curated] [--seed N]
                            WITHOUT the flag: print what the probe costs at
                            worst (model.PROBE_MAX_ANLAS) and that only the
                            author may pass the flag; exit 2; no network at
                            all. WITH it: guard.probe_request, then
                            run.run_request(probe=True, context with
                            probe_flag_used True). Prints whether a proof row
                            was written.
pixelize PNG --recipe R [--palette PNG] [--ledger-id ID] [--strip-version N]
     [--colours N] [--remove-orphans] [--out DIR]
                            post.pixelize with the recipe's layout, ground,
                            hold_arc, fps_hint and the centers from
                            mannequin.render_init. Writes strip.png,
                            strip.json (the sidecar), frame_<i>.png and (when
                            --palette is absent) palette.png under DIR
                            (default <state>/sprites/<recipe>/<first 12 hex
                            of the input PNG's sha256>/). A file already
                            there with DIFFERENT bytes is never overwritten
                            (exit 1, nothing written): a frozen reference
                            palette or an accepted strip is not replaced
                            silently. Prints the validation. Exit 0 when
                            valid, 3 when rejected.
ledger [--last N]           Print the last N rows (default 10), one line
                            each: ledger id, kind, action, model, seed, HTTP
                            status, sum before -> after, delta, locked,
                            refusal condition, verdict. No network.

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
from typing import Callable, Sequence

from tools.nai import guard, mannequin, masks, post, recipes, request, run
from tools.nai import transport as nai_transport
from tools.nai.model import (GENERATE_URL, INPAINT_STRENGTH_KEY,
                             PROBE_MAX_ANLAS, SEED_MAX, SEED_MIN, OPUS_TIER,
                             DEFAULT_COLOURS, VARIANTS)
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


def _ledger_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lever", default=None,
                   help="the ONE lever this round changes (ledger)")
    p.add_argument("--round", type=int, default=None)
    p.add_argument("--phase", default=None)
    p.add_argument("--strip-version", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    """The argparse tree for every command in the module docstring."""
    recipe_names = sorted(recipes.RECIPES)
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
    p.add_argument("--out", default=None)

    p = command("plan", help="dry run: build and judge one request")
    p.add_argument("recipe", choices=recipe_names)
    p.add_argument("--action", choices=("generate", "img2img"), required=True)
    _generation_options(p)

    p = command("run", help="send EXACTLY ONE generate or img2img")
    p.add_argument("recipe", choices=recipe_names)
    p.add_argument("--action", choices=("generate", "img2img"), required=True)
    _generation_options(p)
    _ledger_options(p)

    p = command("infill", help="send EXACTLY ONE infill of one cell")
    p.add_argument("recipe", choices=recipe_names)
    p.add_argument("--cell", type=int, required=True)
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
    p.add_argument("--palette", default=None,
                   help="the character's reference palette (mode-P PNG)")
    p.add_argument("--ledger-id", default=None)
    p.add_argument("--strip-version", type=int, default=1)
    p.add_argument("--colours", type=int, default=DEFAULT_COLOURS)
    p.add_argument("--remove-orphans", action="store_true",
                   help="lever P8")
    p.add_argument("--out", default=None)

    p = command("ledger", help="print the last ledger rows")
    p.add_argument("--last", type=int, default=10)
    return parser


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
    try:
        previous = state.last_balance()
    except ValueError as exc:
        _out(f"chain         CANNOT START: {exc}")
    else:
        verdict = guard.chain_verdict(previous, account.sum)
        meaning = {
            "first": "empty ledger, nothing to compare",
            "ok": "equals the last ledger row",
            "refill": "above the last ledger row (a refill)",
            "charged": "BELOW the last ledger row: the next run will write "
                       "LOCK",
        }[verdict]
        _out(f"chain         {verdict}: last row {_fmt(previous)}, now "
             f"{account.sum} -- {meaning}")
    _out(f"LOCK          {'PRESENT ' + state.lock_path if state.locked() else 'absent'}")
    _out(f"INFLIGHT      {'PRESENT ' + state.inflight_path if state.inflight() else 'absent'}")
    free = (account.tier == OPUS_TIER and account.active is True
            and account.grace is not True)
    _out("free tier     " + ("usable" if free else
                             "NOT usable: needs tier 3, active, not in grace"))
    return EXIT_OK if free else EXIT_REFUSED


def _cmd_render(args, transport, state: State) -> int:
    recipe = recipes.get_recipe(args.recipe)
    colours = recipe.identity.as_dict()
    out = args.out or os.path.join(state.root, RENDERS_DIR,
                                   f"{recipe.name}_init.png")
    assert_untracked_output(out)
    png, centers = mannequin.render_init(recipe.layout, recipe.poses, colours)
    if args.out is None:
        state.subdir(RENDERS_DIR)
    _write_all([(out, png)])
    layout = recipe.layout
    _out(f"render        {out}")
    _out(f"layout        {layout.name} {layout.width}x{layout.height} "
         f"k={layout.k}, {layout.count} frames")
    for i, center in enumerate(centers):
        _out(f"frame {i}       center {center}")
    _out(f"params sha256 "
         f"{mannequin.params_sha256(layout, recipe.poses, colours)}")
    _out(f"png sha256    {hashlib.sha256(png).hexdigest()}")
    return EXIT_OK


def _cmd_plan(args, transport, state: State) -> int:
    _out(f"plan          {args.recipe} {args.action} (dry run: nothing is "
         f"sent)")
    seed = _seed(args.seed)
    req = recipes.make_request(args.recipe, args.action, seed,
                               **_overrides(args))
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
        elif verdict.ok is None and verdict.condition == 1:
            mark = "needs the live account read"   # a proof pending its read
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
    seed = _seed(args.seed)
    req = recipes.make_request(args.recipe, args.action, seed,
                               **_overrides(args))
    context = recipes.context_for(
        args.recipe, strip_version=args.strip_version, round=args.round,
        phase=args.phase, lever_changed=args.lever)
    row = _send(req, transport, state, probe=False, context=context)
    return _sent_exit(row)


def _cmd_infill(args, transport, state: State) -> int:
    _out(f"infill        {args.recipe} cell {args.cell} (ONE request)")
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
    req = recipes.make_request(args.recipe, "infill", seed, **overrides)
    context = recipes.context_for(
        args.recipe, cell=args.cell, strip_version=args.strip_version,
        round=args.round, phase=args.phase, lever_changed=args.lever)
    row = _send(req, transport, state, probe=False, context=context)
    status = row.get("http_status")
    if (isinstance(status, int) and 200 <= status < 300
            and row.get("output_png_sha256")):
        returned = state.read_blob(row["output_png_sha256"], "png")
        rect = recipes.get_recipe(args.recipe).layout.cells[args.cell].rect_canvas
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
    recipe = recipes.get_recipe(args.recipe)
    with open(args.png, "rb") as handle:
        png = handle.read()
    palette = None
    if args.palette is not None:
        with open(args.palette, "rb") as handle:
            palette = handle.read()
    out_dir = args.out or os.path.join(
        state.root, SPRITES_DIR, recipe.name,
        hashlib.sha256(png).hexdigest()[:12])
    assert_untracked_output(out_dir)
    _, centers = mannequin.render_init(recipe.layout, recipe.poses,
                                       recipe.identity.as_dict())
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


def _cmd_ledger(args, transport, state: State) -> int:
    rows = state.rows()
    if not rows:
        _out(f"ledger is empty: {state.ledger_path}")
        return EXIT_OK
    for row in state.last_rows(args.last):
        before = _sum_of(row.get("account_before"))
        after = _sum_of(row.get("account_after"))
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
