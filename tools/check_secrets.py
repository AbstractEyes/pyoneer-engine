"""Refuse a plaintext credential in a TRACKED file.

    .venv/Scripts/python.exe tools/check_secrets.py
    .venv/Scripts/python.exe tools/check_secrets.py --scan <path>   # one file

Why this exists, and it is not hypothetical. A module in this repository
assigned a live account name and password as module-level constants, was
committed, and was pushed to a public remote. It was deleted on 2026-09-03.
The deletion had no teeth: not one check in the roster read a tracked file
looking for a credential, so re-adding that exact file was silently green
across the whole suite. That is law 5's shape in its purest form -- not a gate
proved in one direction, but no gate at all.

WHAT THIS CANNOT DO. Two limits, and a reader who believes otherwise is worse
off than one who knows them:

  * IT CANNOT UNPUBLISH A BLOB THAT WAS ALREADY PUSHED.
    The blob that earned this check is still reachable in the published
    history of the remote even though the file is gone from the tree. A
    credential that reaches a public remote is burned: the only repair is to
    ROTATE IT AT THE PROVIDER. Deleting the file does not, and this check does
    not.
  * IT DOES NOT SCAN HISTORY. It reads the working tree at `git ls-files` and
    nothing else -- not earlier commits, not the reflog, not stashes, not
    packed objects. It refuses the NEXT one. It says nothing about the last.

Two further limits, smaller but real: it reads only files that decode as
UTF-8, so a credential inside a PNG or a WAV is invisible to it; and it walks
TRACKED files only, because an untracked scratch file is nobody's business and
a check that fails on one is a check people turn off.

HOW IT LOOKS. Two detectors, and they are deliberately different in kind:

  1. A CREDENTIAL-SHAPED NAME bound to a non-trivial string literal. In a
     Python file this is read from the AST -- assignment, annotated
     assignment, attribute assignment, dict literal key, call keyword, and an
     `os.environ.get(key, default)` whose DEFAULT is the credential. In any
     other text file it is a `name = value` / `"name": value` line match.
  2. A HIGH-ENTROPY KEY-SHAPED LITERAL even when the name is innocent,
     because `endpoint_seed = "aB3kZq91LmXv72RtNc04Wp"` is a key whatever it
     is called.

Detector 2 is the one that decides whether anybody keeps this check switched
on, so its net was MEASURED rather than guessed, over all 433 tracked files:

    free-token scan of every text file   15 hits, all 15 false (they are
                                         paths -- data/graphics/tilesets/
                                         System/TileA2 is mixed-case, has a
                                         digit, and is 36 characters)
    same scan, path-shaped tokens out     0 hits
    every Python string literal           0 hits

So a token carrying `/`, `\` or `.` is never key-shaped here, and the length
cap is applied to the MAXIMAL run rather than to a 128-character slice of one
-- otherwise a base64 `<data>` block in a .tmx would be chopped into hundreds
of perfect-looking keys. A check that cries wolf gets exempted, and an
exempted check sees nothing.

READING FROM `os.environ` IS THE CORRECT PATTERN AND IS NEVER FLAGGED. Neither
is a placeholder, a pointer name (`secret_path` names a credential, it is not
one), a format template, a shell variable, or this module's own decoys -- a
credential-shaped string INSIDE a list literal is data, which is exactly why
the Python path parses instead of grepping.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import math
import os
import re
import subprocess
import sys

ROOT = _bootstrap.REPO_ROOT

# ---------------------------------------------------------------- vocabulary

# Credential-shaped names. Two words that belong on every generic list of
# these are absent, and both absences were MEASURED against this tree rather
# than reasoned about:
#
#   `key`    is claimed by every dict walk in the repository.
#   `token`  is claimed by the engine itself. A BlitToken is the unit the
#            renderer sorts, and a BEHAVIOR TOKEN is a file-format string
#            (law 8). Bare `token` produced THIRTEEN hits over the tracked
#            tree and every one was false: `PLAYER_TOKEN = "player_input"` in
#            main.py, a script trigger's `{"token": ...}` in PLAN_SCENES.md,
#            and eleven `tokens:` parameters echoed into the generated code
#            map. Only the qualified spellings survive.
#
# A word that matches everything is a word that gets the whole check exempted,
# which is how the modal census came to miss fourteen of eighteen spellings.
_WORDS = (
    "password", "passwd", "passphrase", "pwd",
    "secret", "client_secret", "secret_key",
    "auth_token", "access_token", "refresh_token", "bearer_token",
    "api_token", "secret_token", "session_token", "id_token",
    "api_key", "apikey", "access_key", "private_key", "secret_access_key",
    "session_key", "encryption_key", "signing_key", "ssh_key",
    "credential", "credentials", "authorization",
)
_NAME_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])(" + "|".join(sorted(_WORDS, key=len, reverse=True)) +
    r")s?$", re.IGNORECASE)

# A name ending in one of these POINTS AT a credential rather than being one:
# `secret_path` is a path, `token_pattern` is a regex, `API_KEY_ENV` is the
# name of an environment variable. Flagging them is how a check earns the
# reputation that gets it turned off.
_POINTER_SUFFIX = (
    "_path", "_paths", "_file", "_files", "_filename", "_dir", "_root",
    "_url", "_uri", "_host", "_port", "_env", "_var", "_name", "_names",
    "_field", "_fields", "_column", "_header", "_prefix", "_suffix",
    "_pattern", "_patterns", "_re", "_regex", "_words", "_list", "_set",
    "_map", "_type", "_id", "_label", "_hint", "_prompt", "_error", "_msg",
    "_message", "_doc", "_docs", "_help", "_text", "_title", "_tag",
    "_length", "_len", "_min", "_max", "_count", "_index", "_kind",
)

# Values that are obviously not a credential. The historical defect's password
# was nine characters, so the floor sits well under that.
_MIN_VALUE_LEN = 5
_PLACEHOLDER_WORDS = (
    "changeme", "change_me", "placeholder", "example", "sample", "dummy",
    "fake", "notreal", "not_real", "redacted", "elided", "todo", "tbd",
    "replace", "insert", "here", "yourpassword", "your_password", "yourkey",
    "your_key", "secret", "password", "token", "apikey", "api_key", "none",
    "null", "unset", "empty", "default", "test", "testing", "xxx", "abc",
)
_SHELL_VAR = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$|^%[A-Za-z_][A-Za-z0-9_]*%$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://")

# Detector 2. Anchored, so the length cap applies to the whole literal, and
# separator-free, so a path is never key-shaped -- both measured, see the
# module docstring.
_KEYISH = re.compile(r"^[A-Za-z0-9+=_-]{20,128}$")
_TEXT_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_.\\-])[A-Za-z0-9+/=_.\\-]+"
                         r"(?![A-Za-z0-9+/=_.\\-])")
_MIN_ENTROPY = 3.5

# Detector 1, non-Python line form: `name = "value"`, `name: "value"`,
# `NAME=value`, `"name": "value"`.
_TEXT_ASSIGN = re.compile(
    r"""["']?\b(?P<name>[A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*[:=]\s*"""
    r"""(?P<q>["']?)(?P<value>[^"'\s,;)\]}]+)(?P=q)""")


def shannon(text: str) -> float:
    """Bits per character. A generated key sits high; a word sits low."""
    if not text:
        return 0.0
    total = 0.0
    for ch in set(text):
        p = text.count(ch) / len(text)
        total -= p * math.log2(p)
    return total


def credential_name(name: str) -> bool:
    """True when `name` reads as a credential and not as a pointer at one."""
    lowered = name.lower()
    if lowered.endswith(_POINTER_SUFFIX):
        return False
    return _NAME_RE.search(lowered) is not None


def trivial_value(value: str) -> bool:
    """True when a string cannot plausibly BE a credential."""
    stripped = value.strip()
    if len(stripped) < _MIN_VALUE_LEN:
        return True
    lowered = stripped.lower()
    if any(word in lowered for word in _PLACEHOLDER_WORDS):
        return True
    if _SHELL_VAR.match(stripped) or _URL.match(lowered):
        return True
    if stripped[0] in "<{[(" and stripped[-1] in ">}])":
        return True
    if "{" in stripped and "}" in stripped:          # a format template
        return True
    if "%s" in stripped or "%(" in stripped or "%d" in stripped:
        return True
    if len(set(stripped)) <= 2:                      # ****, xxxxxx, ------
        return True
    if "[" in stripped and stripped.endswith("]"):   # Sequence[str], a[0]
        return True
    if "/" in stripped or "\\" in stripped:          # a path, not a password
        return True
    if " " in stripped:                              # prose, not a credential
        return True
    return False


def keyish_value(value: str) -> bool:
    """True for a literal that looks like a GENERATED key, name aside."""
    if not _KEYISH.match(value):
        return False
    if not (any(c.isdigit() for c in value)
            and any(c.islower() for c in value)
            and any(c.isupper() for c in value)):
        return False
    if any(word in value.lower() for word in _PLACEHOLDER_WORDS):
        return False
    return shannon(value) >= _MIN_ENTROPY


# ------------------------------------------------------------------ findings

class Finding:
    """A hit, WITHOUT the value. Printing the credential is the one thing this
    module must never do -- a check whose failure output is the secret has
    copied it into every CI log that ever ran red."""

    def __init__(self, path: str, line: int, name: str, value: str, why: str):
        self.path = path
        self.line = line
        self.name = name
        self.why = why
        self.length = len(value)

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}  {self.name}  "
                f"<{self.why}, len={self.length}>")


def _scan_python(path: str, source: str) -> list[Finding]:
    """AST, not grep. A credential-shaped string INSIDE a literal is data."""
    found: list[Finding] = []
    tree = ast.parse(source)

    def literal(node) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def named(name: str, node, line: int) -> None:
        value = literal(node)
        if value is None or not credential_name(name) or trivial_value(value):
            return
        found.append(Finding(path, line, name, value, "credential-shaped name"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    named(target.id, node.value, node.lineno)
                elif isinstance(target, ast.Attribute):
                    named(target.attr, node.value, node.lineno)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                named(node.target.id, node.value, node.lineno)
            elif isinstance(node.target, ast.Attribute):
                named(node.target.attr, node.value, node.lineno)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    named(key.value, value, getattr(key, "lineno", node.lineno))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg:
                    named(kw.arg, kw.value, node.lineno)
            # os.environ.get("API_KEY", "<the credential>") -- reading the
            # environment is correct, and a committed FALLBACK is not.
            func = node.func
            attr = getattr(func, "attr", None)
            if attr in ("get", "getenv") and len(node.args) == 2:
                key = literal(node.args[0])
                if key is not None:
                    named(key, node.args[1], node.lineno)

    # Detector 2 over every string literal in the file.
    for node in ast.walk(tree):
        value = literal(node)
        if value is not None and keyish_value(value):
            found.append(Finding(path, node.lineno, "<literal>", value,
                                 "high-entropy key-shaped literal"))
    return found


def _scan_text(path: str, source: str) -> list[Finding]:
    """Line shapes, for everything that is not Python."""
    found: list[Finding] = []
    for number, line in enumerate(source.splitlines(), 1):
        for match in _TEXT_ASSIGN.finditer(line):
            name, value = match.group("name"), match.group("value")
            if credential_name(name) and not trivial_value(value):
                found.append(Finding(path, number, name, value,
                                     "credential-shaped name"))
        for token in _TEXT_TOKEN.findall(line):
            if keyish_value(token):
                found.append(Finding(path, number, "<token>", token,
                                     "high-entropy key-shaped literal"))
    return found


def scan_source(path: str, source: str) -> list[Finding]:
    """Route by extension. A .py that will not parse falls back to lines
    rather than becoming a blind spot."""
    if path.endswith(".py"):
        try:
            return _scan_python(path, source)
        except SyntaxError:
            pass
    return _scan_text(path, source)


def scan_file(path: str, relative: str | None = None):
    """Returns (findings, readable). `readable` is False for a file that does
    not decode as UTF-8 -- a PNG, a WAV -- which this check cannot see into."""
    try:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
    except (UnicodeDecodeError, OSError):
        return [], False
    return scan_source(relative or path, source), True


def tracked_files() -> list[str] | None:
    """Every tracked path, or None when git cannot answer."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
    except Exception:                                        # pragma: no cover
        return None
    if out.returncode != 0:                                  # pragma: no cover
        return None
    return [p for p in out.stdout.split("\0") if p.strip()]


# ------------------------------------------------------- one file, on demand

if "--scan" in sys.argv:
    # `--scan <path>` is how the historical defect is re-proved without the
    # blob ever entering the tree. Recover it to a SCRATCH file outside the
    # repository, point this at it, and read the redacted verdict:
    #
    #     git show <baseline>:scripts/tests/naitest.py > <scratch>/defect.py
    #     .venv/Scripts/python.exe tools/check_secrets.py --scan <scratch>/defect.py
    #     ->  HIT  defect.py:15  password  <credential-shaped name, len=9>
    #
    # Measured: it fires, on the line that was pushed, and it prints the NAME
    # and the LENGTH and never the value. Do not write that file into the tree
    # and do not commit it -- recovering a burned credential to prove a gate
    # works is not a reason to publish it a second time.
    #
    # Exit 1 means a credential was found, which is the same polarity the
    # suite uses.
    target = sys.argv[sys.argv.index("--scan") + 1]
    hits, readable = scan_file(target, os.path.basename(target))
    if not readable:
        print(f"unreadable (not UTF-8): {target}")
        sys.exit(2)
    for hit in hits:
        print(f"  HIT  {hit}")
    print(f"{len(hits)} finding(s) in {os.path.basename(target)}")
    sys.exit(1 if hits else 0)


# ------------------------------------------------------------- the check run

failures: list[str] = []


def expect(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"         got {got!r}, want {want!r}")
        failures.append(label)


# 1. The detector fires. Every string below is SYNTHETIC -- invented for this
#    corpus, bound to no account anywhere -- and every one is a snippet held
#    inside a list, which is why scanning this very file finds nothing.
# Held in halves so that no 20-character key-shaped run exists as a literal in
# this module -- detector 2 reads every string constant in every tracked file,
# including this one, and a decoy that fires is a decoy that has escaped.
_SEED = "aB3kZq91Lm" + "Xv72RtNc04Wp"

MUST_FIRE = [
    ('PASSWORD = "Tr0ub4dor&3x"',            "module constant, the shape that was pushed"),
    ('passwd = "Qv71mLz4Bn"',                "the spelling the historical module used"),
    ('self.api_key = "9f2c1b7e4a8d3f06b5c9"', "attribute assignment"),
    ('ACCESS_TOKEN: str = "ya29LmQpXv73Bd21Kc"', "annotated assignment"),
    ('conn = connect(user="svc", password="Xk29qLm4Pz")', "call keyword"),
    ('CONFIG = {"client_secret": "8Qv2LmRt4Xb9Nc0Ws"}', "dict literal key"),
    ('key = os.environ.get("API_KEY", "Zk84Lq02MnRv")',
     "a committed fallback beside a correct environment read"),
    ('endpoint_seed = "%s"' % _SEED,
     "detector 2: innocent name, generated key"),
]
for snippet, why in MUST_FIRE:
    expect(f"fires: {why}", bool(scan_source("corpus.py", snippet)), True)

# 2. The other half of every one of those gates (law 5). A check that only
#    ever says yes is not a gate.
MUST_NOT_FIRE = [
    ('PASSWORD = os.environ["PYONEER_PASSWORD"]',
     "reading os.environ is the CORRECT pattern"),
    ('password = os.getenv("PYONEER_PASSWORD")', "os.getenv with no fallback"),
    ('api_key = os.environ.get("PYONEER_API_KEY", "")',
     "an empty fallback is not a credential"),
    ('PASSWORD_ENV = "PYONEER_PASSWORD"', "a pointer name, not a credential"),
    ('secret_path = "data/project/secret.key"', "a path, not a password"),
    ('TOKEN_PATTERN = r"(password|secret)=[A-Za-z]+"',
     "a regex describing the rule"),
    ('password = ""', "empty"),
    ('password = "changeme"', "placeholder vocabulary"),
    ('api_key = "<your-api-key>"', "angle-bracketed placeholder"),
    ('token = "${API_TOKEN}"', "a shell variable"),
    ('password = "{password}"', "a format template"),
    ('secret = "****"', "a mask"),
    ('"""Never write password = \\"Tr0ub4dor&3x\\" in a module."""',
     "a docstring describing the rule is prose, not an assignment"),
    ('frame_hash = "a3f5c9d2e1b40768a3f5c9d2e1b40768"',
     "detector 2: a hex digest is not a generated key"),
    ('SHEET = "data/art/tilesets/System/TileA2.png"',
     "detector 2: a path is not a generated key"),
    ('BLOB = "%s"' % (_SEED * 20),
     "detector 2: a base64 block is over the cap, not hundreds of keys"),
    ('PLAYER_TOKEN: str = "player_input"',
     "a BEHAVIOR TOKEN is a file-format string, not a credential"),
    ('refusals(tokens: Sequence[str], registry: Mapping[str, str])',
     "a signature echoed into the generated code map"),
    ('for token in tokens:\n    token = "left"',
     "a short loop variable named token"),
]
for snippet, why in MUST_NOT_FIRE:
    hits = scan_source("corpus.py", snippet)
    expect(f"silent: {why}", [str(h) for h in hits], [])

# 3. The same two halves through the NON-Python path, because a credential in
#    a .json or a .env never reaches the AST.
expect("fires: a json config carrying a password",
       bool(scan_source("conf.json", '{"host": "db", "password": "Xk29qLm4Pz"}')),
       True)
expect("fires: a dotenv line",
       bool(scan_source(".env", "PYONEER_API_KEY=Zk84Lq02MnRvTt")), True)
expect("silent: a dotenv line pointing at the environment",
       [str(h) for h in scan_source(".env", "PYONEER_API_KEY=${API_KEY}")], [])
expect("silent: prose naming the rule",
       [str(h) for h in scan_source(
           "doc.md", "Never commit a password = <the real one> to the tree.")],
       [])

# 4. The tree as it stands is CLEAN. This is the assertion the roster row is
#    for: it is the one that goes red when somebody commits the next one.
tracked = tracked_files()
if tracked is None:                                          # pragma: no cover
    print("  SKIP git ls-files is unavailable -- the tree was not swept")
else:
    swept = 0
    unreadable = 0
    entropy_hits = 0
    tree_findings: list[Finding] = []
    for relative in tracked:
        hits, readable = scan_file(os.path.join(ROOT, relative), relative)
        if not readable:
            unreadable += 1
            continue
        swept += 1
        tree_findings.extend(hits)
        entropy_hits += sum(1 for h in hits if h.why.startswith("high-entropy"))
    print(f"  ..   tracked files swept   : {swept} "
          f"({unreadable} binary/undecodable, skipped)")
    print(f"  ..   detector 2 hits, tree : {entropy_hits} "
          f"(a non-zero number here is the cry-wolf failure)")
    for hit in tree_findings:
        print(f"       HIT {hit}")
    expect("no tracked file carries a plaintext credential",
           [str(h) for h in tree_findings], [])

# 5. This module is full of credential-shaped strings, so it is its own
#    hardest negative -- and the sweep above does NOT cover it while the file
#    is in flight. Measured: `git ls-files` lists a check module only once it
#    is tracked, and `tools/check_docs.py` deliberately leaves an untracked,
#    unrostered check unjudged ("in flight, not judged"), so between writing
#    this file and its roster row landing there is a window in which step 4
#    cannot see it at all. Reading `__file__` directly closes that window, and
#    keeps closing it afterwards for the same cost.
own_hits, _ = scan_file(os.path.abspath(__file__), "tools/check_secrets.py")
expect("this check's own decoys do not fire",
       [str(h) for h in own_hits], [])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
