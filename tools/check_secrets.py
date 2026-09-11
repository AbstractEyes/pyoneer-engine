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

WHAT THIS CANNOT DO. Six limits, and a reader who believes otherwise is worse
off than one who knows them. The last one was found by ADVERSARIALLY PROBING
this detector with twelve credential shapes it had never been shown; five were
caught, seven were not, and the seven are written down rather than quietly
hoped about:

  * IT CANNOT UNPUBLISH A BLOB THAT WAS ALREADY PUSHED.
    The blob that earned this check is still reachable in the published
    history of the remote even though the file is gone from the tree. A
    credential that reaches a public remote is burned: the only repair is to
    ROTATE IT AT THE PROVIDER. Deleting the file does not, and this check does
    not.
  * IT DOES NOT SCAN HISTORY. It reads the working tree at `git ls-files` and
    nothing else -- not earlier commits, not the reflog, not stashes, not
    packed objects. It refuses the NEXT one. It says nothing about the last.
    WHAT A HISTORY SCAN WOULD COST, measured on this repository rather than
    guessed: `git cat-file --batch-all-objects` reports 2057 blobs / 82 MiB
    over 100 commits, and feeding every UTF-8-decodable blob through
    `scan_source` is seconds, not minutes -- affordable, and NOT the reason it
    is absent. The reason is that its verdict is UNACTIONABLE and PERMANENT:
    a hit in history cannot be fixed by editing a file, only by rotating the
    credential at the provider and rewriting published history, so a roster
    row for it would be red forever over a working tree that is clean -- and a
    check that can never go green is a check somebody exempts, which is how
    this one would die. If you want the sweep, run it by hand off this
    module's public surface (`scan_source` over `git cat-file` output); do not
    put it on the roster until there is a written allowlist of already-rotated
    blobs to subtract from it.
  * IT READS ONLY UTF-8. A credential inside a PNG or a WAV is invisible to
    it; the tracked files that cannot be decoded are COUNTED and reported as
    skipped on every run, rather than silently passing.
  * IT WALKS TRACKED FILES ONLY, because an untracked scratch file is nobody's
    business and a check that fails on one is a check people turn off.
  * IT DOES NOT READ CODE INSIDE A PYTHON STRING. A config blob embedded as a
    triple-quoted literal -- one spelling `password = ...` on a line of its
    own inside the quotes -- is a single string constant to the AST and is not
    read as an assignment. That is the SAME rule that makes this module's own
    corpus safe to keep in the tree: a credential-shaped string inside a
    literal is DATA, and a scanner that reads strings as code fires on every
    check, every doc example and every error message that quotes the rule.
    Detector 3 still reads inside such a blob, because a PEM block or a
    connection URL is one whatever it is nested in; only the name form is
    excused.
  * IT SEES A LITERAL, NOT A COMPUTATION, AND NOT PROSE. Four measured
    misses, none of them closeable without wrecking the false-positive half:
      - A PASSPHRASE WITH SPACES. `trivial_value` treats any spaced value as
        prose, and that single line is the largest false-positive suppressor
        in the module -- without it every sentence in 173 tracked `.md` files
        that contains the word `password:` becomes a finding.
      - A VALUE BUILT AT RUNTIME: `PREFIX + suffix`, `"".join([...])`,
        `chr(88) + ...`. Constant folding stops at the first non-constant,
        deliberately -- this module's own decoys rely on it (see `decoy`).
        This is an EVASION shape, and evasion is not the threat model: the
        incident this check exists for was a plain module constant.
      - A HEX KEY UNDER AN INNOCENT NAME -- see THE HEX LIMIT below.
      - A POSITIONAL ARGUMENT: `connect("db", "svc", "Xk29qLm4Pz")` binds the
        credential to no name at all, so detector 1 has nothing to read and a
        ten-character password has no entropy signal for detector 2. Nothing
        short of taint-tracking catches this one.

NO PATH IS EXEMPT, and that is deliberate: the historical defect lived under
a `tests/` directory. An "it is only a test fixture" exemption would have made
this check green on the exact incident it was written for, so the corpus below
pins a credential under a `tests/` path as firing.

HOW IT LOOKS. Three detectors, deliberately different in kind, and each one
runs on BOTH routes -- the AST route for Python and the line route for
everything else. That pairing is the failure shape this repository keeps
paying for: a gate added to one route while its sibling grows without it.

  1. A CREDENTIAL-SHAPED NAME bound to a non-trivial string. In a Python file
     this is read from the AST: assignment, annotated assignment, attribute
     assignment, SUBSCRIPT assignment (`cfg["password"] = ...`), TUPLE
     UNPACK, dict literal key, call keyword, FUNCTION DEFAULT ARGUMENT, and
     an `os.environ.get(key, default)` whose DEFAULT is the credential. The
     value is read through a folder that sees past an f-string with no
     placeholders, an explicit `"a" + "b"` concatenation, a bytes literal and
     a `b64decode(...)` wrapper. Python COMMENTS are scanned too, through the
     line form, because a credential in a comment is not in the AST. In any
     other text file it is a `name = value` / `"name": value` line match,
     PLUS an XML attribute-pair form, because `<property name="pyoneer_X"
     value="Y"/>` is this engine's entire configuration vocabulary and the
     line form reads it as two innocent bindings called `name` and `value`;
     and a `.json` file is additionally walked STRUCTURALLY so a nested or
     pretty-printed key is not a blind spot.
     The credential word only has to be a TOKEN of the name, not its tail:
     `PASSWORD_PROD` and `api_key_2` are the ordinary spellings and the
     anchored form excused both.
  2. A HIGH-ENTROPY KEY-SHAPED LITERAL even when the name is innocent,
     because `endpoint_seed = "aB3kZq91LmXv72RtNc04Wp"` is a key whatever it
     is called.
  3. A STRUCTURALLY CREDENTIAL string, whatever it is called and whatever
     vocabulary it contains: a provider-prefixed token, a PEM private key
     header, a JWT, an `Authorization` value, a connection URL carrying
     `user:password@`, and a credential handed over in a URL QUERY STRING.
     Detector 3 exists because detectors 1 and 2 both miss those last two
     twice over -- `DATABASE_URL` ends in a POINTER suffix and a `scheme://`
     value is declared trivial, while `?api_key=...` welds the name to the
     value so the token scanner sees one unkeyish run -- and a credential in
     a URL is one of the most common ways this incident actually happens.

MEASURED, not guessed. Detector 2 decides whether anybody keeps this check
switched on, so its net was measured over all 425 readable tracked files at
every widening:

    free-token scan of every text file    15 hits, all 15 false (they are
                                          paths -- data/graphics/tilesets/
                                          System/TileA2 is mixed-case, has a
                                          digit, and is 36 characters)
    same scan, path-shaped tokens out      0 hits
    requiring digit AND lower AND upper    0 hits
    requiring any TWO of digit/lower/    702 hits, the cry-wolf failure --
      upper, which is the obvious way       690 of them CamelCase identifiers
      to widen it                           carrying NO DIGIT AT ALL, which is
                                            why the digit is mandatory and the
                                            three classes are not symmetric
    requiring a digit and one letter      10 hits, all prose slugs and
                                            `NAME=value` pairs
    `=` restricted to trailing padding     8 hits (the `NAME=value` pairs go)
    plus the SLUG rule                     0 hits

Those counts exclude THIS file, which is deliberately full of corpus strings
and is asserted clean separately, by step 5 reading `__file__`. Including it,
the same ladder reads 4 / 711 / 19 / 16 / 4 / 0 -- the corpus is carrying the
shapes the rules are there to reject, which is the point of it.

So: a token carrying `/`, `\` or `.` is never key-shaped; the length cap
applies to the MAXIMAL run rather than to a slice of one, or a base64 `<data>`
block in a .tmx would be chopped into hundreds of perfect-looking keys; and
three shapes are subtracted by name because they are indistinguishable from a
key by entropy alone and this tree is full of them -- a PURE HEX RUN (a digest
or a git sha), a UUID, and the base64 magic of an embedded image.

THE HEX LIMIT IS REAL AND IT IS NOT CLOSEABLE BY DETECTOR 2. A 32-character
hex digest and a 32-character hex-encoded key are THE SAME STRING to an
entropy test, and this repository carries the former in its smoke baseline and
its plan documents. So a hex key under an INNOCENT name is not reported, and
that is a stated miss rather than an oversight. Under a credential-shaped name
it IS reported, by detector 1, which does not consult entropy at all -- the
corpus asserts both halves of exactly that.

READING FROM `os.environ` IS THE CORRECT PATTERN AND IS NEVER FLAGGED.
Neither is a `getpass` call, a placeholder, a pointer name (`secret_path`
names a credential, it is not one), a format template, a shell variable, a
hash, a UUID, a git sha, a base64 image, or this module's own decoys -- a
credential-shaped string INSIDE a list literal is data, which is exactly why
the Python path parses instead of grepping.

A PLACEHOLDER IS A WORD, NOT A SUBSTRING, and that distinction was the widest
hole this check ever had. Matching the placeholder vocabulary anywhere inside
a value made `Qv71mLzabc4Bn` trivial for containing `abc`, and with it
`Zm3testQ9pL`, `Rt4kXhere9Ws`, `P7default2Qx`, and every provider token whose
published sample form carries the word `example`. The words are matched
against non-alphanumeric-separated PARTS of the value now -- never against a
case transition, or `Zm3testQ9pL` would be swallowed all over again -- and the
corpus pins all four of those strings as firing.

DO NOT PRINT THE VALUE. Redaction here is structural, not a habit: `Finding`
takes `value` and keeps only `len(value)`; no attribute holds it, and every
print site goes through `Finding.__str__`. A check whose failure output is the
secret has copied it into every CI log that ever ran red.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import tokenize

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
# The match is anchored at the END of the name, so every compound whose tail
# is a listed word -- `db_password`, `aws_secret_access_key`,
# `oauth_client_secret` -- is covered without being listed.
_WORDS = (
    "password", "passwd", "passphrase", "pwd",
    "secret", "client_secret", "secret_key", "app_secret", "api_secret",
    "consumer_secret", "webhook_secret", "signing_secret", "jwt_secret",
    "auth_token", "access_token", "refresh_token", "bearer_token",
    "api_token", "secret_token", "session_token", "id_token",
    "private_token", "user_token", "admin_token",
    "api_key", "apikey", "access_key", "private_key", "secret_access_key",
    "session_key", "encryption_key", "signing_key", "ssh_key", "auth_key",
    "client_key", "consumer_key", "master_key", "app_key",
    "credential", "credentials", "authorization",
)
#
# THE WORD IS A TOKEN, NOT A SUFFIX. This regex used to anchor the word at the
# END of the name (`...s?$`), and that quietly excused the most ordinary
# spelling there is: `PASSWORD_PROD`, `password_2`, `api_key_2` and
# `SECRET_PROD` all read as innocent. The word now only has to be a whole
# token of the name, which is also what makes `_POINTER_SUFFIX` below
# LOAD-BEARING -- under the anchored form no name could reach it, so it was a
# guard that could not fire, which is law 5's shape sitting in the detector
# instead of in a test. Mutation M16 found that: deleting the entire pointer
# list left the corpus green.
_NAME_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])(" + "|".join(sorted(_WORDS, key=len, reverse=True)) +
    r")s?(?:[^A-Za-z0-9]|$)", re.IGNORECASE)

# A name ending in one of these POINTS AT a credential rather than being one:
# `secret_path` is a path, `token_pattern` is a regex, `API_KEY_ENV` is the
# name of an environment variable. Flagging them is how a check earns the
# reputation that gets it turned off. `_url` is on this list, which is exactly
# why detector 3 does not consult the name at all.
_POINTER_SUFFIX = (
    "_path", "_paths", "_file", "_files", "_filename", "_dir", "_root",
    "_url", "_uri", "_host", "_port", "_env", "_var", "_name", "_names",
    "_field", "_fields", "_column", "_header", "_prefix", "_suffix",
    "_pattern", "_patterns", "_re", "_regex", "_words", "_list", "_set",
    "_map", "_type", "_id", "_label", "_hint", "_prompt", "_error", "_msg",
    "_message", "_doc", "_docs", "_help", "_text", "_title", "_tag",
    "_length", "_len", "_min", "_max", "_count", "_index", "_kind",
    # A DERIVED value is not the credential. Publishing a bcrypt digest is a
    # different (and much smaller) problem than publishing the password, and
    # a check that shouts about `password_hash` is a check people mute.
    "_hash", "_hashes", "_digest", "_checksum", "_md5", "_sha", "_sha1",
    "_sha256", "_salt", "_rounds", "_algo", "_algorithm", "_encoding",
    "_format", "_schema", "_version", "_policy", "_rule", "_rules", "_mode",
    "_flag", "_flags", "_enabled", "_required", "_size", "_bytes", "_class",
)

# Values that are obviously not a credential. The historical defect's password
# was nine characters, so the floor sits well under that.
_MIN_VALUE_LEN = 5

# Matched against non-alphanumeric-separated PARTS of the value, and against
# the whole value -- never as a bare substring, and never across a case
# transition. See the module docstring: the substring form swallowed four real
# credential shapes and every provider token carrying the word `example`.
_PLACEHOLDER_WORDS = frozenset((
    "changeme", "change_me", "changethis", "placeholder", "example",
    "sample", "dummy", "fake", "notreal", "not_real", "redacted", "elided",
    "todo", "tbd", "replace", "insert", "here", "your", "yourpassword",
    "your_password", "yourkey", "your_key", "yourtoken", "yoursecret",
    "mysecret", "mypassword", "secret", "password", "passwd", "token",
    "apikey", "api_key", "key", "none", "null", "nil", "unset", "empty",
    "blank", "default", "test", "testing", "xxx", "xxxx", "abc", "abcdef",
    "foo", "bar", "baz", "lorem", "ipsum",
))
_SHELL_VAR = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$|^%[A-Za-z_][A-Za-z0-9_]*%$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://")

# Detector 2. Anchored, so the length cap applies to the whole literal;
# separator-free, so a path is never key-shaped; and `=` only as TRAILING
# base64 padding, because allowing it mid-token made the scanner swallow
# `NAME=value` whole and call the pair a key.
_KEYISH = re.compile(r"^[A-Za-z0-9+_-]{20,128}={0,2}$")
_TEXT_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_.\\-])[A-Za-z0-9+/=_.\\-]+"
                         r"(?![A-Za-z0-9+/=_.\\-])")
_MIN_ENTROPY = 3.5

# The three shapes subtracted from detector 2 by name, because entropy cannot
# tell them from a key. See the docstring's HEX LIMIT paragraph.
_HEX_RUN = re.compile(r"^[0-9a-fA-F]+$")
_UUID = re.compile(r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                   r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$")
# base64 magic of an embedded image or document: PNG, JPEG, GIF, RIFF/WebP,
# BMP, ICO, PDF, and a data: URI outright. An asset is not a credential
# however high its entropy.
_BINARY_B64_PREFIX = ("iVBORw0KGgo", "/9j/", "R0lGOD", "UklGR", "Qk0",
                      "AAABAA", "JVBERi0", "data:")

# Detector 1, non-Python line form: `name = "value"`, `name: "value"`,
# `NAME=value`, `"name": "value"`.
_TEXT_ASSIGN = re.compile(
    r"""["']?\b(?P<name>[A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*[:=]\s*"""
    r"""(?P<q>["']?)(?P<value>[^"'\s,;)\]}]+)(?P=q)""")

# Detector 1, XML attribute-pair form -- and this one is not generic, it is
# THIS repository's entire configuration vocabulary. Every authored setting in
# a `.tmx` is `<property name="pyoneer_X" value="Y"/>`, and to the line form
# above that reads as two innocent bindings: a key called `name` and a key
# called `value`. The credential-shaped word sits in a VALUE, so the line form
# is structurally blind to it, across all five tracked maps and every `.xml`.
# Both attribute orders, because Tiled writes one and a hand edit writes the
# other.
_XML_PAIRS = (
    re.compile(r"""\bname\s*=\s*"(?P<name>[^"]{1,120})"[^>]{0,200}?"""
               r"""\bvalue\s*=\s*"(?P<value>[^"]{0,400})\""""),
    re.compile(r"""\bvalue\s*=\s*"(?P<value>[^"]{0,400})"[^>]{0,200}?"""
               r"""\bname\s*=\s*"(?P<name>[^"]{1,120})\""""),
)

# Detector 3. Name-blind and vocabulary-blind: these shapes ARE credentials,
# so neither a pointer suffix nor the word `example` inside them buys silence.
# Measured over the tracked tree: 0 hits, every pattern.
_STRUCTURAL = (
    ("aws access key id",
     re.compile(r"\b(?:A3T[A-Z0-9]{2}|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    ("github token",
     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"
                r"|\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack token",
     re.compile(r"\bxox[abporsu]-[A-Za-z0-9]{8,}-[A-Za-z0-9-]{8,}")),
    ("google api key", re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b")),
    ("openai-style key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("stripe key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("private key block",
     re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("json web token",
     re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}"
                r"\.[A-Za-z0-9_\-]{8,}")),
    ("http authorization value",
     re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_\-]{20,}={0,2}")),
    ("url with inline credentials",
     re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:@/\"'<>]+:[^\s:@/\"'<>]+@")),
)

# Detector 3's second half: a credential handed over in a URL QUERY STRING.
# Neither of the other detectors can see one -- the whole value starts
# `https://`, which detector 1 declares trivial, and the parameter is welded
# to its `=` so detector 2 reads name and value as one unkeyish token. The
# name list is `_WORDS` plus the spellings that only ever appear in a query,
# where a bare `token=` is not the engine's BlitToken and really is a secret.
_QUERY_WORDS = _WORDS + ("token", "auth", "sig", "signature", "session")
_URL_QUERY = re.compile(
    r"[?&](?P<name>[A-Za-z][A-Za-z0-9_.\-]{0,60})=(?P<value>[^&\s\"'<>]{5,200})")

# A value node worth reading THROUGH the call: a committed credential is as
# committed when it arrives base64-encoded.
_DECODERS = ("b64decode", "b64encode", "b32decode", "b16decode", "a85decode",
             "unhexlify", "fromhex", "unquote")


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
    """True when `name` reads as a credential and not as a pointer at one.

    A HYPHEN IS AN UNDERSCORE HERE. Every HTTP header and every URL query
    parameter that carries a credential is spelled with hyphens -- `X-Api-Key`,
    `x-auth-token` -- and without this line the whole header family read as
    innocent while `x_api_key` did not."""
    lowered = name.lower().replace("-", "_")
    if lowered.endswith(_POINTER_SUFFIX):
        return False
    return _NAME_RE.search(lowered) is not None


def _parts(value: str, separators: str = r"[^A-Za-z0-9]+") -> list[str]:
    """The value split into wordish parts. NOT split on case transitions:
    `Zm3testQ9pL` must stay ONE part, or the placeholder rule swallows a
    credential for containing `test` exactly as the substring form did."""
    return [p for p in re.split(separators, value) if p]


def placeholder_value(value: str) -> bool:
    """True when the value is placeholder vocabulary -- as a WORD."""
    lowered = value.strip().lower()
    if lowered in _PLACEHOLDER_WORDS:
        return True
    return any(part in _PLACEHOLDER_WORDS for part in _parts(lowered))


def _sluggy(value: str) -> bool:
    """True for a hyphen/underscore-joined run of words -- prose, not a key.
    THREE alphabetic parts, because a real `github_pat_<body>` has two."""
    pieces = _parts(value, r"[-_]+")
    wordish = [p for p in pieces if p.isalpha() and len(p) >= 3]
    return len(pieces) >= 3 and len(wordish) >= 3


def _pathish(value: str) -> bool:
    """True for a filesystem path: an extension, an obvious prefix, or two
    alphabetic segments. `data/graphics/tilesets/System/TileA2` is a path and
    `aGVsbG8vd29ybGQrZm9v` is base64 that happens to carry a slash."""
    if re.search(r"\.[A-Za-z0-9]{1,5}$", value):
        return True
    if value.startswith(("./", "../", "/", "~/")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    segments = _parts(value, r"[/\\]+")
    return len([s for s in segments if s.isalpha() and len(s) >= 3]) >= 2


def _base64ish(value: str) -> bool:
    """A single high-entropy base64 run, slash and all -- the shape the flat
    `"/" means path` rule used to declare trivial and skip."""
    if not re.match(r"^[A-Za-z0-9+/]{20,}={0,2}$", value):
        return False
    if value.startswith(_BINARY_B64_PREFIX) or _pathish(value):
        return False
    classes = sum((any(c.isdigit() for c in value),
                   any(c.islower() for c in value),
                   any(c.isupper() for c in value)))
    return classes >= 2 and shannon(value) >= _MIN_ENTROPY


def trivial_value(value: str) -> bool:
    """True when a string cannot plausibly BE a credential."""
    stripped = value.strip()
    if len(stripped) < _MIN_VALUE_LEN:
        return True
    lowered = stripped.lower()
    if placeholder_value(stripped):
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
    if ("/" in stripped or "\\" in stripped) and not _base64ish(stripped):
        return True                                  # a path, not a password
    if " " in stripped:                              # prose, not a credential
        return True
    return False


def keyish_value(value: str) -> bool:
    """True for a literal that looks like a GENERATED key, name aside."""
    if not _KEYISH.match(value):
        return False
    if not any(c.isdigit() for c in value):
        return False
    if not (any(c.islower() for c in value) or any(c.isupper() for c in value)):
        return False
    if _HEX_RUN.match(value) or _UUID.match(value):
        return False
    if value.startswith(_BINARY_B64_PREFIX):
        return False
    if _sluggy(value) or placeholder_value(value):
        return False
    return shannon(value) >= _MIN_ENTROPY


def structural_credential(text: str) -> str | None:
    """Detector 3 over one line or one literal: the label, or None."""
    for label, pattern in _STRUCTURAL:
        if pattern.search(text):
            return label
    return None


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


def _rank(why: str) -> int:
    """Detector 1 names the BINDING, which is the most useful thing to print;
    detector 3 names the provider; detector 2 says only `high entropy`."""
    if why == "credential-shaped name":
        return 0
    return 2 if why.startswith("high-entropy") else 1


def _dedupe(found: list[Finding]) -> list[Finding]:
    """One string, reported once. Three detectors seeing one literal is the
    NORMAL case -- a github token bound to a name spelled `api_key` is a
    detector 1 hit, a detector 2 hit and a detector 3 hit -- and printing it
    three times inflates the count a reader uses to judge the incident."""
    best: dict[tuple, Finding] = {}
    for hit in found:
        key = (hit.path, hit.line, hit.length)
        keep = best.get(key)
        if keep is None or _rank(hit.why) < _rank(keep.why):
            best[key] = hit
    return sorted(best.values(), key=lambda h: (h.line, h.name))


# ------------------------------------------------------- the value, unfolded

def _string_value(node) -> str | None:
    """The string a value node ACTUALLY carries. A credential written as an
    f-string, as `"a" + "b"`, as a bytes literal or inside `b64decode()` is
    the same credential; the plain `ast.Constant` read saw none of them."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            try:
                return node.value.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None
    if isinstance(node, ast.JoinedStr):
        pieces = []
        for piece in node.values:                    # f"..." with no {slots}
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                pieces.append(piece.value)
            else:
                return None
        return "".join(pieces)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_value(node.left), _string_value(node.right)
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.Call):
        called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if called in _DECODERS and node.args:
            return _string_value(node.args[0])
        if called in ("decode", "encode") and not node.args:
            return _string_value(getattr(node.func, "value", None))
    return None


# ---------------------------------------------------------------- the routes

def _scan_structural(path: str, source: str) -> list[Finding]:
    """Detector 3, over RAW TEXT, for every file type there is. Raw rather
    than parsed on purpose: a PEM block or a connection URL is as much a
    credential in a comment, a docstring, a markdown fence or a JSON value,
    and writing it ONCE is what keeps the two routes from disagreeing."""
    found: list[Finding] = []
    # Token form, not tail form, for the same reason `_NAME_RE` uses it: an
    # anchored version could never reach the pointer-suffix line below, so
    # that guard would be unreachable and untestable. Mutation M27 found
    # exactly that -- deleting the whole guard left the corpus green.
    query_re = re.compile(
        r"(?:^|[^A-Za-z0-9])("
        + "|".join(sorted(_QUERY_WORDS, key=len, reverse=True))
        + r")s?(?:[^A-Za-z0-9]|$)", re.IGNORECASE)
    for number, line in enumerate(source.splitlines(), 1):
        for label, pattern in _STRUCTURAL:
            match = pattern.search(line)
            if match:
                found.append(Finding(path, number, "<literal>",
                                     match.group(0), label))
        for match in _URL_QUERY.finditer(line):
            name, value = match.group("name"), match.group("value")
            normalised = name.lower().replace("-", "_")
            if normalised.endswith(_POINTER_SUFFIX) or trivial_value(value):
                continue
            if query_re.search(normalised):
                found.append(Finding(path, number, name, value,
                                     "credential in a url query string"))
    return found


def _text_names(path: str, source: str, offset: int = 0) -> list[Finding]:
    """Detector 1, line form."""
    found: list[Finding] = []
    for number, line in enumerate(source.splitlines(), 1 + offset):
        for match in _TEXT_ASSIGN.finditer(line):
            name, value = match.group("name"), match.group("value")
            if credential_name(name) and not trivial_value(value):
                found.append(Finding(path, number, name, value,
                                     "credential-shaped name"))
        for pattern in _XML_PAIRS:
            for match in pattern.finditer(line):
                name, value = match.group("name"), match.group("value")
                if credential_name(name) and not trivial_value(value):
                    found.append(Finding(path, number, name, value,
                                         "credential-shaped name"))
    return found


def _text_tokens(path: str, source: str) -> list[Finding]:
    """Detector 2, line form."""
    found: list[Finding] = []
    for number, line in enumerate(source.splitlines(), 1):
        for token in _TEXT_TOKEN.findall(line):
            if keyish_value(token):
                found.append(Finding(path, number, "<token>", token,
                                     "high-entropy key-shaped literal"))
    return found


def _python_comments(source: str):
    """(line, text) for every `#` comment. A credential in a comment is not
    in the AST, so the Python route is blind to it without this."""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.start[0], tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return


def _scan_python(path: str, source: str) -> list[Finding]:
    """AST, not grep. A credential-shaped string INSIDE a literal is data."""
    found: list[Finding] = []
    tree = ast.parse(source)

    def named(name: str, node, line: int) -> None:
        value = _string_value(node)
        if value is None or not credential_name(name) or trivial_value(value):
            return
        found.append(Finding(path, line, name, value, "credential-shaped name"))

    def target(node, value, line: int) -> None:
        """Every binding shape, including the two that were blind spots:
        `cfg["password"] = ...` and `user, password = ...`."""
        if isinstance(node, ast.Name):
            named(node.id, value, line)
        elif isinstance(node, ast.Attribute):
            named(node.attr, value, line)
        elif isinstance(node, ast.Subscript):
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                named(key.value, value, line)
        elif isinstance(node, (ast.Tuple, ast.List)):
            paired = (isinstance(value, (ast.Tuple, ast.List))
                      and len(value.elts) == len(node.elts))
            values = value.elts if paired else [value] * len(node.elts)
            for element, bound in zip(node.elts, values):
                target(element, bound, line)

    def defaults(args: ast.arguments, line: int) -> None:
        """`def connect(password="...")` -- a committed credential with a
        signature wrapped round it."""
        positional = list(args.posonlyargs) + list(args.args)
        if args.defaults:
            for arg, default in zip(positional[len(positional) - len(args.defaults):],
                                    args.defaults):
                named(arg.arg, default, getattr(default, "lineno", line))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is not None:
                named(arg.arg, default, getattr(default, "lineno", line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for element in node.targets:
                target(element, node.value, node.lineno)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target(node.target, node.value, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            defaults(node.args, node.lineno)
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
            called = (getattr(node.func, "attr", None)
                      or getattr(node.func, "id", None))
            if called in ("get", "getenv") and len(node.args) == 2:
                key = _string_value(node.args[0])
                if key is not None:
                    named(key, node.args[1], node.lineno)

    # Detector 2 over every string the file carries, folded the same way.
    for node in ast.walk(tree):
        value = _string_value(node)
        if value is not None and keyish_value(value):
            found.append(Finding(path, getattr(node, "lineno", 1), "<literal>",
                                 value, "high-entropy key-shaped literal"))

    # Detector 1 over comments, which the AST cannot see.
    for line, text in _python_comments(source):
        found.extend(_text_names(path, text, offset=line - 1))
    return found


def _scan_json(path: str, source: str) -> list[Finding] | None:
    """Detector 1, structurally. A pretty-printed or nested config is the
    NORMAL shape of a real `.json`, and the line form sees only the flat
    one-line case. None when the document will not parse -- the caller falls
    back to the line form rather than going blind."""
    try:
        document = json.loads(source)
    except (ValueError, RecursionError):
        return None
    lines = source.splitlines()
    found: list[Finding] = []

    def locate(name: str, value: str) -> int:
        needle = f'"{name}"'
        for number, line in enumerate(lines, 1):
            if needle in line and value in line:
                return number
        for number, line in enumerate(lines, 1):
            if needle in line:
                return number
        return 1

    def walk(node) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                if (isinstance(name, str) and isinstance(value, str)
                        and credential_name(name) and not trivial_value(value)):
                    found.append(Finding(path, locate(name, value), name,
                                         value, "credential-shaped name"))
                walk(value)
        elif isinstance(node, list):
            for element in node:
                walk(element)

    walk(document)
    return found


def scan_source(path: str, source: str) -> list[Finding]:
    """Route by extension, and give detector 3 to EVERY route. A .py that
    will not parse falls back to lines rather than becoming a blind spot."""
    found = _scan_structural(path, source)
    if path.endswith(".py"):
        try:
            return _dedupe(found + _scan_python(path, source))
        except (SyntaxError, ValueError):
            pass
    if path.endswith(".json"):
        structured = _scan_json(path, source)
        if structured is not None:
            return _dedupe(found + structured + _text_tokens(path, source))
    return _dedupe(found + _text_names(path, source) + _text_tokens(path, source))


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
    #     git show <baseline>:<the retired module> > <scratch>/defect.py
    #     .venv/Scripts/python.exe tools/check_secrets.py --scan <scratch>/defect.py
    #
    # Measured: it fires, on the line that was pushed, and it prints the NAME
    # and the LENGTH and never the value. Do not write that file into the tree
    # and do not commit it -- recovering a burned credential to prove a gate
    # works is not a reason to publish it a second time.
    #
    # Exit 1 means a credential was found, which is the same polarity the
    # suite uses.
    target_path = sys.argv[sys.argv.index("--scan") + 1]
    hits, readable = scan_file(target_path, os.path.basename(target_path))
    if not readable:
        print(f"unreadable (not UTF-8): {target_path}")
        sys.exit(2)
    for hit in hits:
        print(f"  HIT  {hit}")
    print(f"{len(hits)} finding(s) in {os.path.basename(target_path)}")
    sys.exit(1 if hits else 0)


# ------------------------------------------------------------- the check run

failures: list[str] = []


def expect(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"         got {got!r}, want {want!r}")
        failures.append(label)


def decoy(*parts: str) -> str:
    """Assemble a synthetic credential AT RUNTIME. Every corpus string below
    is invented and bound to no account anywhere -- and it still must not
    exist as a literal in this module, because detectors 2 and 3 read every
    tracked file INCLUDING THIS ONE, and a decoy that fires is a decoy that
    has escaped. `"".join(...)` is a call, not a foldable `+`, so
    `_string_value` deliberately cannot see through it; step 5 below is the
    assertion that keeps that true."""
    return "".join(parts)


_SEED = decoy("aB3kZq91Lm", "Xv72RtNc04Wp")
_LOWER_SEED = decoy("q7wme2", "ndk4zx", "vb8rt5", "cyu3ph", "6sla9g")
# The slash is the POINT of this one, and the first draft did not contain one
# -- `aGVsbG8v` ends in a letter v. It read as a plain key-shaped token, so
# detector 2 caught it, so removing the `_base64ish` relaxation left the
# corpus GREEN and the case was asserting nothing. Mutation testing found
# that; reading the string did not.
_B64_SLASH = decoy("aGVsbG8", "/", "d29ybGQr", "Zm9vYmFyMTIz", "/", "NA==")
_AWS = decoy("AKIA", "IOSFODNN7EXAMPLE")
# Every part here is deliberately under detector 2's 20-character floor. The
# first draft of this line held the body as ONE 36-character literal and step
# 5 went red on it -- which is the assertion doing its job, and the reason the
# parts are this small rather than this tidy.
_GITHUB = decoy("ghp_", "A1b2C3d4E5f6", "G7h8I9j0K1l2", "M3n4O5p6Q7r8")
_SLACK = decoy("xoxb-", "24681012141", "-", "97531086420", "-", "Lm4QvXk29Pz")
_JWT = decoy("eyJhbGciOiJIUzI1NiJ9.", "eyJzdWIiOiIxMjMifQ.", "Kq9Lm4XvPz27Bd")
_PEM = decoy("-----BEGIN ", "RSA ", "PRIVATE KEY", "-----")
_DSN = decoy("postgres://svc:", "Xk29qLm4Pz", "@db.internal:5432/app")
# The query-string decoys must be assembled too: detector 3 reads RAW TEXT,
# so a query credential written as a literal here fires on this very file.
# Step 5 caught exactly that, for the second time this pass.
_QUERY_KEY = decoy("Zk84Lq", "02MnRvTt")
_QUERY_SHORT = decoy("Qv71m", "Lz4Bn")

# 1. THE POSITIVE CORPUS -- the ways a credential actually gets written. Each
#    entry is a SHAPE, named so a reader can see which route it exercises and
#    which detector is meant to catch it.
MUST_FIRE = [
    ('PASSWORD = "Tr0ub4dor&3x"', "py: module constant, the shape that was pushed"),
    ('passwd = "Qv71mLz4Bn"', "py: the spelling the historical module used"),
    ('self.api_key = "9f2c1b7e4a8d3f06b5c9"', "py: attribute assignment"),
    ('ACCESS_TOKEN: str = "ya29LmQpXv73Bd21Kc"', "py: annotated assignment"),
    ('class Client:\n    client_secret = "Xk29qLm4Pz7Bd"', "py: CLASS ATTRIBUTE"),
    ('conn = connect(user="svc", password="Xk29qLm4Pz")', "py: call keyword"),
    ('CONFIG = {"client_secret": "8Qv2LmRt4Xb9Nc0Ws"}', "py: DICT LITERAL key"),
    ('def connect(host="db", password="Xk29qLm4Pz"):\n    pass',
     "py: DEFAULT ARGUMENT"),
    ('def sign(*, signing_key="Qv71mLz4BnRt"):\n    pass',
     "py: keyword-only default argument"),
    ('user, password = "svc", "Xk29qLm4Pz"', "py: TUPLE UNPACK"),
    ('cfg["password"] = "Xk29qLm4Pz"', "py: SUBSCRIPT assignment"),
    ('PASSWORD = f"Xk29qLm4Pz"', "py: FORMATTED STRING with no placeholders"),
    ('PASSWORD = "Xk29" + "qLm4Pz"', "py: explicit concatenation"),
    ('PASSWORD = b"Xk29qLm4Pz"', "py: bytes literal"),
    ('PASSWORD = base64.b64decode("czNjcjN0cGFzc3dk")', "py: BASE64 BLOB"),
    ('password = "%s"' % _B64_SLASH,
     "py: base64 carrying a slash, once read as a path and skipped"),
    ('key = os.environ.get("API_KEY", "Zk84Lq02MnRv")',
     "py: a committed fallback beside a correct environment read"),
    ('key = getenv("API_KEY", "Zk84Lq02MnRv")',
     "py: the bare `getenv` spelling, whose sibling `os.getenv` was covered"),
    ('# password = Xk29qLm4Pz', "py: a COMMENT, which is not in the AST"),
    ('endpoint_seed = "%s"' % _SEED, "py d2: innocent name, generated key"),
    ('_BUILD_MARK = "%s"' % _LOWER_SEED,
     "py d2: an ALL-LOWERCASE generated key, once invisible to detector 2"),
    ('PASSWORD_PROD = "Xk29qLm4Pz"',
     "py: a credential word that is not the LAST token of the name -- the "
     "anchored form excused every environment-suffixed spelling there is"),
    ('password_2 = "Xk29qLm4Pz"', "py: the same, numbered"),
    ('API_KEY_2: str = "Zk84Lq02MnRv"', "py: the same, on a compound word"),
    ('password = "Qv71mLzabc4Bn"', "py: a credential CONTAINING `abc`"),
    ('password = "Zm3testQ9pL"', "py: a credential CONTAINING `test`"),
    ('password = "Rt4kXhere9Ws"', "py: a credential CONTAINING `here`"),
    ('password = "P7default2Qx"', "py: a credential CONTAINING `default`"),
    ('AWS = "%s"' % _AWS,
     "py d3: an aws key id, whose published sample form says EXAMPLE"),
    ('MARK = "%s"' % _GITHUB, "py d3: a github token under an innocent name"),
    ('MARK = "%s"' % _SLACK, "py d3: a slack token"),
    ('MARK = "%s"' % _JWT, "py d3: a json web token"),
    ('BLOCK = """%s"""' % _PEM, "py d3: a PEM private key header"),
    ('ENDPOINT = "https://api.internal/v1?api_key=%s"' % _QUERY_KEY,
     "py d3: a credential in a URL QUERY STRING -- the value starts "
     "`https://` so detector 1 excuses it, and the parameter is welded to its "
     "`=` so detector 2 reads name and value as one unkeyish token"),
    ('ENDPOINT = "https://api.internal/v1?token=%s"' % _QUERY_SHORT,
     "py d3: the same, with a value too short for any entropy test"),
    ('headers = {"X-Api-Key": "Zk84Lq02MnRvTt"}',
     "py: a HYPHENATED header name -- every HTTP credential is spelled this "
     "way and `api-key` did not match the underscore vocabulary"),
    ('DATABASE_URL = "%s"' % _DSN,
     "py d3: a CONNECTION URL with inline credentials -- a pointer-suffixed "
     "name holding a scheme:// value, which detectors 1 and 2 both excuse"),
]
for snippet, why in MUST_FIRE:
    expect(f"fires: {why}", bool(scan_source("corpus.py", snippet)), True)

# The historical defect's own address gets no exemption. A `tests/` opt-out
# would have made this check green on the incident it exists for.
expect("fires: a credential under a tests/ path is not excused",
       bool(scan_source("scripts/tests/naitest.py", 'password = "Qv71mLz4Bn"')),
       True)

# 2. The other half of every one of those gates (law 5). A check that only
#    ever says yes is not a gate, and this is the half that decides whether
#    the check survives contact with a person.
MUST_NOT_FIRE = [
    ('PASSWORD = os.environ["PYONEER_PASSWORD"]',
     "reading os.environ is the CORRECT pattern"),
    ('password = os.getenv("PYONEER_PASSWORD")', "os.getenv with no fallback"),
    ('api_key = os.environ.get("PYONEER_API_KEY", "")',
     "an empty fallback is not a credential"),
    ('password = getpass.getpass()', "a GETPASS call"),
    ('password = getpass.getpass("Password for the service: ")',
     "a getpass call carrying its own prompt"),
    ('PASSWORD_ENV = "PYONEER_PASSWORD"', "a pointer name, not a credential"),
    ('secret_path = "data/project/secret.key"', "a path, not a password"),
    ('password_pattern = "Qv71mLz4Bn"',
     "a POINTER name the widened word rule now reaches -- this half of the "
     "invariant was unreachable and therefore untested before"),
    ('api_key_field = "Zk84Lq02MnRv"', "the same, on a compound word"),
    ('password_hash = "Qv71mLz4BnRt9X"',
     "a DERIVED value: publishing a digest is not publishing the password"),
    ('secret_count = "Qv71mLz4Bn"', "a count named after the thing counted"),
    ('SHEET = "data/graphics/tilesets/System/TileA2"',
     "a path with no extension is still a path"),
    ('TOKEN_PATTERN = r"(password|secret)=[A-Za-z]+"',
     "a regex describing the rule"),
    ('password = ""', "empty"),
    ('password = "changeme"', "PLACEHOLDER vocabulary"),
    ('api_key = "your-api-key"', "a hyphenated placeholder"),
    ('api_key = "<your-api-key>"', "an angle-bracketed placeholder"),
    ('token = "${API_TOKEN}"', "a shell variable"),
    ('password = "{password}"', "a format template"),
    ('secret = "****"', "a mask"),
    ('"""Never write password = \\"Tr0ub4dor&3x\\" in a module."""',
     "a DOCSTRING describing the rule is prose, not an assignment"),
    ('# a fixture password is still a password -- name it, never write it',
     "a comment describing the rule"),
    ('frame_hash = "a3f5c9d2e1b40768a3f5c9d2e1b40768"',
     "a HASH is not a generated key"),
    ('BASELINE = "9f86d081884c7d659a2feaa0c55ad015"',
     "d2: a bare hex run under an innocent name is a digest here -- the "
     "stated miss, and the reason detector 1 does not consult entropy"),
    ('COMMIT = "0b6227c742e76f6e43e24b6980f28892d49fca68"', "a GIT SHA"),
    ('RUN_ID = "4f8a2b3c-1d2e-4f5a-8b9c-0d1e2f3a4b5c"', "a UUID"),
    ('ICON = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"',
     "d2: the base64 of an embedded PNG is an ASSET, not a key"),
    ('SHEET = "data/art/tilesets/System/TileA2.png"',
     "d2: a path is not a generated key"),
    ('BLOB = "%s"' % (_SEED * 20),
     "d2: a base64 block is over the cap, not hundreds of keys"),
    ('PLAYER_ID = "user00000000000000001"',
     "d2: a padded identifier is key-SHAPED and low-entropy -- the only "
     "negative the entropy floor itself decides, and without it that "
     "constant is untested tuning"),
    ('MARKER = "AAAAAAAAAAAAAAAAAAAA1"',
     "d2: a repeated-character run is not a generated key"),
    ('SLUG = "0001-set-up-a-parallax-scrolling-system-for-the"',
     "d2: a hyphenated prose slug is not a key"),
    ('NOTE = "39-silently-dropped-tiles"', "d2: the same slug shape, shorter"),
    ('PLAYER_TOKEN: str = "player_input"',
     "a BEHAVIOR TOKEN is a file-format string, not a credential"),
    ('refusals(tokens: Sequence[str], registry: Mapping[str, str])',
     "a signature echoed into the generated code map"),
    ('for token in tokens:\n    token = "left"',
     "a short loop variable named token"),
    ('AUTH = "Bearer <your-token-here>"',
     "d3: a documented Authorization placeholder"),
    ('PUBLIC = "-----BEGIN PUBLIC KEY-----"',
     "d3: a PUBLIC key block is publishable by definition"),
    ('SERVICE = "https://api.example.com/v1/tokens"',
     "d3: a plain URL carries no inline credential"),
    ('SERVICE = "https://svc@api.internal/v1"',
     "d3: a URL with a user and NO password"),
    ('DOCS = "https://api.example.com/v1?api_key=<your-api-key>"',
     "d3: a documented query placeholder"),
    ('FEED = "https://api.internal/v1?page=2&sort=name&format=json"',
     "d3: ordinary query parameters are not credentials"),
    ('DOCS = "https://api.example.com/v1?api_key=changeme"',
     "d3: a PLACEHOLDER in a query string -- the half of that guard the "
     "angle-bracketed form never reaches, because the regex stops at `<`"),
    ('DOCS = "https://api.internal/v1?token_path=data/project/x.key"',
     "d3: a POINTER name in a query string"),
    ('FEED = "https://api.internal/v1?session_id=Zk84Lq02MnRvTt"',
     "d3: a session IDENTIFIER is a pointer, not the credential"),
    ('HEADERS = {"Content-Type": "application/json"}',
     "a hyphenated header that names no credential"),
]
for snippet, why in MUST_NOT_FIRE:
    hits = scan_source("corpus.py", snippet)
    expect(f"silent: {why}", [str(h) for h in hits], [])

# 3. THE SIBLING ROUTE. Every case above reached the AST; a credential in a
#    .json, a .env, a .md, a .yaml or a .tmx never does. This repository's
#    standing failure shape is a gate added to one route while its sibling
#    grows without it -- SIX sightings before this pass -- so each half below
#    is the line-route twin of a case above.
TEXT_MUST_FIRE = [
    ("conf.json", '{"host": "db", "password": "Xk29qLm4Pz"}',
     "json: a flat config carrying a password"),
    ("conf.json",
     '{\n  "database": {\n    "host": "db",\n    "password": "Xk29qLm4Pz"\n  }\n}',
     "json: NESTED and pretty-printed"),
    ("conf.json",
     '{\n  "database": {\n    "password":\n      "Xk29qLm4Pz"\n  }\n}',
     "json: the key and the value on DIFFERENT LINES, which the line form "
     "cannot see at all -- the case the structural walk exists for"),
    ("conf.json",
     '{"services": [{"name": "db", "api_token": "Zk84Lq02MnRvTt"}]}',
     "json: inside a LIST of objects"),
    (".env", "PYONEER_API_KEY=Zk84Lq02MnRvTt", "env: a dotenv-shaped line"),
    ("deploy.yaml", "  db_password: Xk29qLm4Pz", "yaml: a mapping value"),
    ("notes.md", "api_key: Zk84Lq02MnRvTt", "md: a tracked document"),
    ("conf.ini", "password=Qv71mLz4Bn", "ini: no quotes, no spaces"),
    ("fixture.tmx", '  <property name="pyoneer_password" value="Qv71mLz4Bn"/>',
     "tmx: THIS ENGINE'S OWN config vocabulary -- the credential word is in "
     "an attribute VALUE, so the `name = value` line form cannot see it"),
    ("fixture.tmx", '  <property value="Qv71mLz4Bn" name="pyoneer_api_key"/>',
     "tmx: the same pair written in the other order"),
    ("LICENSE", "password=Qv71mLz4Bn",
     "a tracked file with NO EXTENSION still takes the text route"),
    ("notes.md", "connect to %s" % _DSN, "md d3: an inline-credential URL"),
    ("deploy.yaml", "  marker: %s" % _GITHUB, "yaml d3: a github token"),
    ("keys.txt", _PEM, "txt d3: a PEM private key header"),
    ("notes.md", 'curl -H "X-Api-Key: Zk84Lq02MnRvTt" https://api/x',
     "md: a curl HEADER, hyphenated, on the text route"),
    ("notes.md", "GET https://api.internal/v1?access_token=%s" % _QUERY_KEY,
     "md d3: a query-string credential on the text route"),
    ("conf.json", '{"seed": "%s"}' % _SEED, "json d2: a generated key"),
]
for text_path, body, why in TEXT_MUST_FIRE:
    expect(f"fires: {why}", bool(scan_source(text_path, body)), True)

TEXT_MUST_NOT_FIRE = [
    (".env", "PYONEER_API_KEY=${API_KEY}", "env: pointing at the environment"),
    (".env", "PYONEER_API_KEY=", "env: an empty value"),
    ("doc.md", "Never commit a password = <the real one> to the tree.",
     "md: prose naming the rule"),
    ("conf.json", '{"secret_path": "data/project/secret.key"}',
     "json: a pointer name"),
    ("conf.json", '{"password": "changeme"}', "json: a placeholder"),
    ("baseline.json", '{"frame_hash": "5d1d2ad35acd80da"}',
     "json: the smoke baseline's own digest"),
    ("doc.md", "run `git show 0b6227c742e76f6e43e24b6980f28892d49fca68`",
     "md: a git sha in prose"),
    ("map.tmx", '<data encoding="base64">%s</data>' % (_SEED * 20),
     "tmx: a base64 layer block is one run over the cap"),
    ("map.tmx",
     '  <property name="pyoneer_behaviors" value="player_input,topdown_move"/>',
     "tmx: a BEHAVIOR TOKEN list is the shape the shipped map actually has"),
    ("map.tmx",
     '  <property name="pyoneer_secret_path" value="data/project/x.key"/>',
     "tmx: a pointer name in the attribute form obeys the same rule"),
    ("map.tmx", '  <property name="pyoneer_collision" value="Collision"/>',
     "tmx: the shipped collision declaration"),
]
for text_path, body, why in TEXT_MUST_NOT_FIRE:
    expect(f"silent: {why}", [str(h) for h in scan_source(text_path, body)], [])

print(f"  ..   positive corpus       : "
      f"{len(MUST_FIRE) + 1 + len(TEXT_MUST_FIRE)} shapes, all caught "
      f"({len(MUST_FIRE) + 1} python, {len(TEXT_MUST_FIRE)} text)")
print(f"  ..   negative corpus       : "
      f"{len(MUST_NOT_FIRE) + len(TEXT_MUST_NOT_FIRE)} shapes, all silent "
      f"({len(MUST_NOT_FIRE)} python, {len(TEXT_MUST_NOT_FIRE)} text)")

# 3b. REDACTION, asserted rather than believed. The module docstring claims
#     this is STRUCTURAL -- that `Finding` keeps a length and never the value
#     -- and until this block existed nothing tested it: adding
#     `self.leaked = value` to the constructor left the whole corpus green.
#     A check whose failure output is the secret has copied it into every CI
#     log that ever ran red, so this is the one property worth proving twice:
#     once on a hand-built Finding and once on one the scanner produced.
_REDACT = decoy("Qv71mLz", "4BnRt9X")
_hand = Finding("corpus.py", 1, "password", _REDACT, "credential-shaped name")
_scanned = scan_source("corpus.py", 'password = "%s"' % _REDACT)
expect("redaction: the scanner produced exactly one finding to test",
       len(_scanned), 1)
for _label, _hit in (("hand-built", _hand), ("scanned", _scanned[0])):
    expect(f"redaction: no attribute of a {_label} Finding holds the value",
           [a for a, v in vars(_hit).items() if isinstance(v, str) and _REDACT in v],
           [])
    expect(f"redaction: str() of a {_label} Finding does not carry the value",
           _REDACT in str(_hit), False)
    expect(f"redaction: repr() of a {_label} Finding does not carry the value",
           _REDACT in repr(_hit), False)
    expect(f"redaction: the {_label} Finding still reports the LENGTH",
           _hit.length, len(_REDACT))

# 4. The tree as it stands is CLEAN. This is the assertion the roster row is
#    for: it is the one that goes red when somebody commits the next one.
tracked = tracked_files()
if tracked is None:                                          # pragma: no cover
    print("  SKIP git ls-files is unavailable -- the tree was not swept")
else:
    started = time.perf_counter()
    swept = 0
    unreadable = 0
    entropy_hits = 0
    structural_hits = 0
    tree_findings: list[Finding] = []
    for relative in tracked:
        hits, readable = scan_file(os.path.join(ROOT, relative), relative)
        if not readable:
            unreadable += 1
            continue
        swept += 1
        tree_findings.extend(hits)
        entropy_hits += sum(1 for h in hits if _rank(h.why) == 2)
        structural_hits += sum(1 for h in hits if _rank(h.why) == 1)
    print(f"  ..   tracked files swept   : {swept} "
          f"({unreadable} binary/undecodable, skipped) "
          f"in {time.perf_counter() - started:.1f}s")
    print(f"  ..   detector 2 hits, tree : {entropy_hits} "
          f"(a non-zero number here is the cry-wolf failure)")
    print(f"  ..   detector 3 hits, tree : {structural_hits} "
          f"(same, and these carry a provider's name)")
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
