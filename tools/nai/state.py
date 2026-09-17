"""On-disk state: the ledger, the proofs, LOCK, INFLIGHT, and the blob store.

OWNER: implementer A.

RESPONSIBILITY
--------------
`State(root)` is the only code that reads or writes files under the state
root (default `data/nai/` in the MAIN checkout of the repository,
gitignored; see `default_root`). Everything that must survive a process --
the balance chain, the proof rows, the lock, the in-flight marker,
request/response bytes -- goes through it.

ONE ROOT PER ACCOUNT, NOT PER CHECKOUT. LOCK, INFLIGHT and the chain guard an
account, and a second working tree of the same repository (`git worktree
add`, as under .claude/worktrees/) is the same author on the same account.
So the default root is resolved through git's common directory to the main
working tree: every linked worktree sees the one LOCK. A separate CLONE has
its own .git and is not found this way (DESIGN limit, stated in
docs/NAI_SPRITES.md); the lost-ledger rule in `last_balance` is the net under
a clone that inherits blobs or proofs.json without the ledger.

LAYOUT
------
    <root>/ledger.jsonl        append-only JSONL, one row per attempt
    <root>/proofs.json         JSON list of model.Proof rows
    <root>/LOCK                text: ledger id + reason; present = refuse all
    <root>/INFLIGHT            text: ledger id, pid, balance before; present =
                               refuse all
    <root>/blobs/<sha256>.<ext> content-addressed bytes, ext png|zip|json
    <root>/renders/            written by the CLI's `render`
    <root>/sprites/            written by the CLI's `pixelize`

INVARIANTS
----------
* APPEND-ONLY. `write_row` appends one line and fsyncs; nothing in this
  package rewrites, truncates or deletes a ledger line. A malformed line
  makes `rows()` RAISE (naming the line number), never skip.
* EVERY ROW HAS EXACTLY model.LEDGER_FIELDS, in that order; `write_row`
  refuses any other key set, a `kind` outside model.ROW_KINDS, and any row
  whose serialised text contains "Authorization", "Bearer " or "pst-", or a
  string value longer than 4096 characters (base64 never enters the ledger).
  `validate_row` is that same refusal without the write, so `run` can prove
  a row is writable BEFORE it sends anything; `write_row` calls it.
* THE CHAIN. `last_balance()` is the `account_after.sum` of the LAST row
  (both kinds carry one). An empty ledger answers None -- unless blobs/ or
  proofs.json already exist under the root: a request was sent from here
  before, so the ledger is LOST, not new, and `last_balance` RAISES rather
  than let the next read chain as a first run. A last row without a balance
  RAISES -- with ONE exception, stated in `last_balance`: a `generation`
  row whose after-read failed carries `account_after` null and `locked`
  true, and for that row the chain value is its `account_before.sum`.
* ONE SCRUB. `scrub_text` is the only function that makes server or
  exception text safe for a row, and it removes WHOLE credential-shaped
  runs (a `pst-` token with its body, a Bearer value, an Authorization
  value), never just the marker: a marker-only scrub also disarms
  `validate_row`'s refusal while leaving the token body in the row.
* NOTHING HERE DELETES LOCK. The author deletes it by hand; `lock()` only
  creates it (and leaves an existing one untouched). INFLIGHT is created
  exclusively (O_CREAT | O_EXCL) and removed only by `release_inflight`,
  which `run.run_request` calls after the row is durably written -- a crash
  leaves INFLIGHT behind on purpose, for the author to inspect.
* proofs.json is replaced atomically (write a temp file beside it, then
  os.replace); a missing file is an empty proof list; a malformed one
  RAISES.
* Blobs are create-only: an existing <sha256>.<ext> is left as is (same name
  means same bytes). A new blob is written to a temp file and renamed into
  place, so a crash never leaves a partial blob under its final name.

PUBLIC NAMES
------------
REPO_ROOT, STATE_SUBPATH, main_checkout, default_root, LEDGER_NAME,
PROOFS_NAME, LOCK_NAME, INFLIGHT_NAME, BLOBS_DIR, RENDERS_DIR, SPRITES_DIR,
BLOB_EXTS, MAX_ROW_STRING, FORBIDDEN_ROW_TEXT, scrub_text, State (with
validate_row beside write_row).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

from tools.nai.guard import Refused  # noqa: F401  (acquire_inflight raises it)
from tools.nai.model import LEDGER_FIELDS, ROW_KINDS, Proof

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
"""The working tree this copy of the package lives in (maybe a worktree)."""
STATE_SUBPATH: tuple[str, ...] = ("data", "nai")
"""The state root's path inside a checkout; gitignored."""

LEDGER_NAME = "ledger.jsonl"
PROOFS_NAME = "proofs.json"
LOCK_NAME = "LOCK"
INFLIGHT_NAME = "INFLIGHT"
BLOBS_DIR = "blobs"
RENDERS_DIR = "renders"
SPRITES_DIR = "sprites"
BLOB_EXTS: tuple[str, ...] = ("png", "zip", "json")
MAX_ROW_STRING = 4096
FORBIDDEN_ROW_TEXT: tuple[str, ...] = ("Authorization", "Bearer ", "pst-")

_REDACTED = "[redacted]"
_SCRUB_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"authorization\s*[:=]?\s*(?:bearer\s+)?\S*", re.IGNORECASE),
    re.compile(r"bearer\s+\S*", re.IGNORECASE),
    re.compile(r"pst-[A-Za-z0-9_\-]*", re.IGNORECASE),
)
"""One pattern per FORBIDDEN_ROW_TEXT marker, each swallowing the whole run
the marker introduces. Case-insensitive, so each is a superset of its
marker."""


def scrub_text(text: object) -> str:
    """`str(text)` with every credential-shaped run replaced by "[redacted]".

    An Authorization value (with or without a Bearer word), a Bearer value,
    and a `pst-` token INCLUDING its body. The result never contains a
    FORBIDDEN_ROW_TEXT marker. Not a length cut; `run` cuts afterwards.
    """
    out = str(text)
    for pattern in _SCRUB_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


def main_checkout(repo_root: str) -> str:
    """The main working tree that `repo_root` shares its git metadata with.

    * <repo_root>/.git is a directory, or absent (a copy with no git
      metadata, where there is no other checkout to find) -> repo_root.
    * <repo_root>/.git is a FILE (a linked worktree): its `gitdir: <path>`
      line names <common>/worktrees/<name>, whose `commondir` file names
      <common> (relative to that directory, or absolute); the main working
      tree is <common>'s parent.
    Any other shape -- a .git file with no gitdir line, a gitdir with no
    commondir, a common directory not named `.git` (a bare repository) --
    raises ValueError naming the file: a state root guessed wrong is a LOCK
    that the other checkout never sees (law 7).
    """
    dot_git = os.path.join(repo_root, ".git")
    if not os.path.lexists(dot_git) or os.path.isdir(dot_git):
        return os.path.abspath(repo_root)
    with open(dot_git, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()
    gitdir = next((line[len("gitdir:"):].strip() for line in lines
                   if line.startswith("gitdir:")), "")
    if not gitdir:
        raise ValueError(f"{dot_git} is a file with no 'gitdir:' line; cannot "
                         f"find the main checkout that shares NovelAI state")
    gitdir = os.path.normpath(os.path.join(repo_root, gitdir))
    commondir_file = os.path.join(gitdir, "commondir")
    try:
        with open(commondir_file, "r", encoding="utf-8",
                  errors="replace") as handle:
            common = handle.read().strip()
    except OSError:
        raise ValueError(f"{dot_git} names {gitdir}, which has no readable "
                         f"commondir file; cannot find the main checkout "
                         f"that shares NovelAI state") from None
    common = os.path.normpath(os.path.join(gitdir, common))
    if os.path.basename(common).lower() != ".git":
        raise ValueError(f"{dot_git} resolves to the common git directory "
                         f"{common}, which is not a main checkout's .git (a "
                         f"bare repository?); pass an explicit state root")
    return os.path.dirname(common)


def default_root(repo_root: str = REPO_ROOT) -> str:
    """<main checkout of repo_root>/data/nai: the one state root every
    worktree of this repository shares. ValueError as `main_checkout`."""
    return os.path.join(main_checkout(repo_root), *STATE_SUBPATH)

_SUBDIRS: tuple[str, ...] = (BLOBS_DIR, RENDERS_DIR, SPRITES_DIR)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROOF_KEYS: tuple[str, ...] = ("action", "model", "size_class", "date",
                                "ledger_id")
_LAST_ID_MICROS = 0
"""The microsecond stamp of the last id this process issued."""


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _long_strings(value: object, path: str = "") -> list[str]:
    """Paths of every string (value or key) longer than MAX_ROW_STRING."""
    found: list[str] = []
    if isinstance(value, str):
        if len(value) > MAX_ROW_STRING:
            found.append(path or "<row>")
    elif isinstance(value, dict):
        for key, inner in value.items():
            here = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and len(key) > MAX_ROW_STRING:
                found.append(here + " (key)")
            found.extend(_long_strings(inner, here))
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            found.extend(_long_strings(inner, f"{path}[{index}]"))
    return found


def _fsync_write(path: str, data: bytes, mode: str) -> None:
    with open(path, mode) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


class State:
    """The state root and every operation on it. Construct with an explicit
    `root` in checks (a scratch directory); the CLI uses `default_root()`.

    Creating a State touches nothing on disk; the first write creates the
    directories it needs.
    """

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        """`root` None means `default_root()` (ValueError as
        `main_checkout`). Stores an absolute path in .root."""
        self.root = os.path.abspath(os.fspath(default_root() if root is None
                                              else root))

    def __repr__(self) -> str:
        return f"State({self.root!r})"

    # -- paths -------------------------------------------------------------

    @property
    def ledger_path(self) -> str:
        return os.path.join(self.root, LEDGER_NAME)

    @property
    def proofs_path(self) -> str:
        return os.path.join(self.root, PROOFS_NAME)

    @property
    def lock_path(self) -> str:
        return os.path.join(self.root, LOCK_NAME)

    @property
    def inflight_path(self) -> str:
        return os.path.join(self.root, INFLIGHT_NAME)

    def subdir(self, name: str) -> str:
        """Absolute path of <root>/<name> (blobs, renders, sprites), created
        if absent. ValueError for any other name."""
        if name not in _SUBDIRS:
            raise ValueError(f"unknown state subdirectory {name!r}; legal: "
                             f"{_SUBDIRS}")
        path = os.path.join(self.root, name)
        os.makedirs(path, exist_ok=True)
        return path

    def _ensure_root(self) -> None:
        os.makedirs(self.root, exist_ok=True)

    # -- ledger ------------------------------------------------------------

    def new_ledger_id(self) -> str:
        """A fresh id: UTC "%Y%m%dT%H%M%S" + 6 decimal microseconds + "Z-" +
        4 lowercase hex from `secrets`. Unique without holding INFLIGHT.

        The Windows clock advances in steps of milliseconds, and 4 hex digits
        are only 16 bits (measured: 200 ids in a loop shared ONE microsecond
        value and collided), so the timestamp part is made strictly increasing
        within a process: a call that reads a time not after the previous
        id's uses the previous time plus one microsecond."""
        global _LAST_ID_MICROS
        micros = time.time_ns() // 1000
        if micros <= _LAST_ID_MICROS:
            micros = _LAST_ID_MICROS + 1
        _LAST_ID_MICROS = micros
        seconds, micro = divmod(micros, 1_000_000)
        stamp = datetime.fromtimestamp(seconds, timezone.utc)
        return (stamp.strftime("%Y%m%dT%H%M%S") + f"{micro:06d}Z-"
                + secrets.token_hex(2))

    def rows(self) -> list[dict]:
        """Every ledger row in file order; [] when the file is absent.
        ValueError naming the 1-based line for a line that is not a JSON
        object."""
        try:
            with open(self.ledger_path, "r", encoding="utf-8",
                      newline="") as handle:
                text = handle.read()
        except FileNotFoundError:
            return []
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()   # the newline that ends the last row
        out: list[dict] = []
        for number, line in enumerate(lines, start=1):
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if not isinstance(row, dict):
                raise ValueError(
                    f"{self.ledger_path} line {number} is not a JSON object")
            out.append(row)
        return out

    def last_rows(self, n: int) -> list[dict]:
        """The last `n` rows in file order (n >= 1, else ValueError)."""
        if not _is_int(n) or n < 1:
            raise ValueError(f"last_rows needs an int n >= 1, got {n!r}")
        return self.rows()[-n:]

    def history(self) -> list[str]:
        """What under the root shows a request was sent from it before:
        "blobs/" when that directory holds any entry, "proofs.json" when it
        exists. Only `run.run_request` writes blobs (from the moment it holds
        INFLIGHT) and proofs, so either one beside an empty ledger means the
        ledger was lost, not that this is a first run."""
        found: list[str] = []
        blobs = os.path.join(self.root, BLOBS_DIR)
        try:
            if os.path.isdir(blobs) and os.listdir(blobs):
                found.append(f"{BLOBS_DIR}/")
        except OSError:
            found.append(f"{BLOBS_DIR}/ (unreadable)")
        if os.path.lexists(self.proofs_path):
            found.append(PROOFS_NAME)
        return found

    def last_balance(self) -> int | None:
        """account_after.sum of the last row; None for an empty ledger;
        ValueError when the last row has no integer account_after.sum.

        THE LOST LEDGER. An empty (or missing) ledger beside a non-empty
        `history()` RAISES instead of answering None: None makes the next
        read chain as "first", which would forget whatever the lost rows --
        or a request killed before its row was written -- had charged.

        The one exception: a `generation` row with `account_after` null AND
        `locked` true is the row `run.run_request` writes when the balance
        read AFTER a send failed. That row also wrote LOCK, so nothing runs
        until the author deletes LOCK by hand; after that, the chain value is
        the row's `account_before.sum` -- the last balance anyone measured.
        A charge that call caused then shows as a decrease on the next read
        and LOCKs again. Without this, a failed after-read would make every
        later invocation raise forever, since the ledger is append-only.
        """
        rows = self.rows()
        if not rows:
            history = self.history()
            if history:
                listed = " and ".join(history)
                raise ValueError(
                    f"the ledger {self.ledger_path} is empty or missing, but "
                    f"{listed} exist under {self.root}: a request was sent "
                    f"from this root before, so the ledger was LOST and the "
                    f"balance chain cannot start over. Restore "
                    f"{LEDGER_NAME}; if it is truly gone, check the account "
                    f"by hand, then move {listed} out of {self.root}.")
            return None
        last = rows[-1]
        after = last.get("account_after")
        if isinstance(after, dict) and _is_int(after.get("sum")):
            return after["sum"]
        if (after is None and last.get("kind") == "generation"
                and last.get("locked") is True):
            before = last.get("account_before")
            if isinstance(before, dict) and _is_int(before.get("sum")):
                return before["sum"]
        raise ValueError(
            f"the last ledger row ({last.get('ledger_id')!r}) has no integer "
            f"account_after.sum")

    def validate_row(self, row: dict) -> str:
        """The compact JSON line `write_row` would append, or ValueError.

        Refuses, naming the problem: keys that differ from
        model.LEDGER_FIELDS (missing and extra listed); kind not in
        model.ROW_KINDS; a string anywhere longer than MAX_ROW_STRING; a
        value JSON cannot spell (NaN, an object); serialised text containing
        any FORBIDDEN_ROW_TEXT (the message names which, never the text
        around it). Writes nothing.
        """
        if not isinstance(row, dict):
            raise ValueError(f"a ledger row is a dict, got {type(row).__name__}")
        missing = [k for k in LEDGER_FIELDS if k not in row]
        extra = [k for k in row if k not in LEDGER_FIELDS]
        if missing or extra:
            raise ValueError(f"ledger row keys differ from LEDGER_FIELDS: "
                             f"missing {missing}, extra {extra}")
        if row["kind"] not in ROW_KINDS:
            raise ValueError(f"ledger row kind {row['kind']!r} is not one of "
                             f"{ROW_KINDS}")
        long = _long_strings(row)
        if long:
            raise ValueError(f"ledger row strings longer than {MAX_ROW_STRING} "
                             f"characters: {long}")
        ordered = {key: row[key] for key in LEDGER_FIELDS}
        try:
            line = json.dumps(ordered, separators=(",", ":"), ensure_ascii=True,
                              allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ledger row is not JSON-serialisable: "
                             f"{type(exc).__name__}") from None
        bad = [text for text in FORBIDDEN_ROW_TEXT if text in line]
        if bad:
            raise ValueError(f"ledger row contains forbidden text {bad}; "
                             f"nothing written")
        return line

    def write_row(self, row: dict) -> None:
        """Append `row` as one compact JSON line, flush, fsync.

        ValueError (and nothing written) when: keys differ from
        model.LEDGER_FIELDS (message lists missing and extra keys); kind is
        not in model.ROW_KINDS; the serialised line contains any
        FORBIDDEN_ROW_TEXT; any string value anywhere is longer than
        MAX_ROW_STRING. Key order is model.LEDGER_FIELDS order.
        """
        line = self.validate_row(row)
        self._ensure_root()
        _fsync_write(self.ledger_path, (line + "\n").encode("ascii"), "ab")

    # -- LOCK and INFLIGHT -------------------------------------------------

    def locked(self) -> bool:
        return os.path.lexists(self.lock_path)

    def lock(self, ledger_id: str, reason: str) -> None:
        """Create LOCK containing ledger_id and reason; leave an existing LOCK
        untouched. Never deletes."""
        self._ensure_root()
        text = f"{ledger_id}\n{reason}\n".encode("utf-8")
        try:
            _fsync_write(self.lock_path, text, "xb")
        except FileExistsError:
            pass

    def inflight(self) -> bool:
        return os.path.lexists(self.inflight_path)

    def acquire_inflight(self, ledger_id: str,
                         balance_before: int | None = None) -> None:
        """Create INFLIGHT exclusively: ledger_id, os.getpid() and
        "balance_before <sum>" on three lines, so an author who finds a stale
        INFLIGHT (a process killed mid-request) knows what to compare the
        account against. guard.Refused(10) when it already exists."""
        self._ensure_root()
        try:
            fd = os.open(self.inflight_path,
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            raise Refused(10, f"INFLIGHT already exists under {self.root}: "
                              f"another request is in flight or crashed") from None
        try:
            os.write(fd, f"{ledger_id}\n{os.getpid()}\nbalance_before "
                         f"{balance_before}\n".encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def inflight_detail(self) -> str:
        """INFLIGHT's contents on one line ("" when absent or unreadable)."""
        try:
            with open(self.inflight_path, "r", encoding="ascii",
                      errors="replace") as handle:
                return " / ".join(line.strip() for line in handle
                                  if line.strip())[:200]
        except OSError:
            return ""

    def release_inflight(self, ledger_id: str) -> None:
        """Remove INFLIGHT. ValueError, and nothing removed, when the file
        names a different ledger id or is absent."""
        try:
            with open(self.inflight_path, "r", encoding="ascii",
                      errors="replace") as handle:
                owner = handle.readline().strip()
        except FileNotFoundError:
            raise ValueError(f"INFLIGHT is absent; cannot release it for "
                             f"{ledger_id}") from None
        if owner != ledger_id:
            raise ValueError(f"INFLIGHT belongs to {owner!r}, not {ledger_id!r}; "
                             f"left in place")
        os.remove(self.inflight_path)

    # -- proofs ------------------------------------------------------------

    def proofs(self) -> tuple[Proof, ...]:
        """Every proof row; () when proofs.json is absent; ValueError when it
        is not a JSON list of complete proof objects."""
        try:
            with open(self.proofs_path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError:
            return ()
        try:
            data = json.loads(text)
        except ValueError:
            raise ValueError(f"{self.proofs_path} is not JSON") from None
        if not isinstance(data, list):
            raise ValueError(f"{self.proofs_path} is not a JSON list")
        out: list[Proof] = []
        for index, item in enumerate(data):
            if not (isinstance(item, dict)
                    and all(isinstance(item.get(k), str) and item.get(k)
                            for k in _PROOF_KEYS)):
                raise ValueError(f"{self.proofs_path} entry {index} is not a "
                                 f"complete proof object {_PROOF_KEYS}")
            out.append(Proof.from_row(item))
        return tuple(out)

    def add_proof(self, proof: Proof) -> None:
        """Append `proof` and replace proofs.json atomically. ValueError when
        a proof for the same (action, model) already exists."""
        existing = self.proofs()
        for known in existing:
            if (known.action, known.model) == (proof.action, proof.model):
                raise ValueError(f"a proof for ({proof.action}, {proof.model}) "
                                 f"already exists (ledger {known.ledger_id})")
        rows = [p.as_row() for p in existing] + [proof.as_row()]
        data = (json.dumps(rows, indent=2, ensure_ascii=True) + "\n").encode("ascii")
        self._ensure_root()
        temp = f"{self.proofs_path}.tmp-{secrets.token_hex(4)}"
        try:
            _fsync_write(temp, data, "xb")
            os.replace(temp, self.proofs_path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)

    # -- blobs -------------------------------------------------------------

    def save_blob(self, data: bytes, ext: str) -> tuple[str, str]:
        """Store `data` as blobs/<sha256>.<ext>; return (sha256 hex, path
        relative to root with forward slashes). ValueError for ext outside
        BLOB_EXTS. Create-only."""
        if ext not in BLOB_EXTS:
            raise ValueError(f"blob extension {ext!r} is not one of {BLOB_EXTS}")
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError(f"blob data must be bytes, got {type(data).__name__}")
        data = bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        name = f"{digest}.{ext}"
        final = os.path.join(self.subdir(BLOBS_DIR), name)
        if not os.path.exists(final):
            temp = f"{final}.tmp-{secrets.token_hex(4)}"
            try:
                _fsync_write(temp, data, "xb")
                os.replace(temp, final)
            finally:
                if os.path.exists(temp):
                    os.remove(temp)
        return digest, f"{BLOBS_DIR}/{name}"

    def read_blob(self, sha256: str, ext: str) -> bytes:
        """The bytes of blobs/<sha256>.<ext>; FileNotFoundError when absent;
        ValueError when the bytes do not hash to `sha256`."""
        if ext not in BLOB_EXTS:
            raise ValueError(f"blob extension {ext!r} is not one of {BLOB_EXTS}")
        if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
            raise ValueError(f"{sha256!r} is not a lowercase hex sha256")
        path = os.path.join(self.root, BLOBS_DIR, f"{sha256}.{ext}")
        with open(path, "rb") as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError(f"blob {sha256}.{ext} does not hash to its name")
        return data
