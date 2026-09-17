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

WHAT THIS CANNOT DO. Seven limits, and a reader who believes otherwise is worse
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
  * ALL THREE DETECTORS READ UTF-8 (with or without a BOM) AND UTF-16 BEHIND
    A BOM. EVERYTHING ELSE GETS DETECTOR 3 ALONE, OR NOTHING. A file that
    starts `FF FE` or `FE FF` is decoded as UTF-16, because that is what
    Windows PowerShell 5.1 writes on a `>` redirect and what `reg export`
    writes. A UTF-8 BOM is dropped before parsing, because `ast.parse` refuses
    a leading U+FEFF and a BOM `.py` used to lose its whole literal pass. A
    file that is NOT valid UTF-8 and carries no UTF-16 BOM -- a cp1252 `.md`
    with a curly apostrophe, PowerShell 5.1 `Set-Content`, `set > env.txt` --
    is read as latin-1 BYTES and handed to detector 3 only: a provider token
    is ASCII, so no codepage guess is needed to see one, while detectors 1
    and 2 would be reading a guess. Those files are COUNTED as not-UTF-8 in
    the summary. BOM-LESS UTF-16LE -- what PowerShell 5.1's `>>` appends onto
    a BOM-less UTF-8 file -- is valid UTF-8 whenever its text is ASCII, with a
    NUL after every character; the NOVELAI entry's provider view deletes the
    NULs and reads it, and nothing else does. A file with NUL bytes that is
    not valid UTF-8 and carries no run of 32 UTF-16 ASCII characters is BINARY
    (PNG, OGG, WAV -- the longest such run in the 11 tracked binaries is 6)
    and is SKIPPED and counted as skipped. Still invisible: a credential
    inside a binary with no such run, a key inside compressed or encoded
    bytes, a name-bound or entropy-only credential in a non-UTF-8 file, and
    any encoding whose ASCII range is not ASCII bytes (UTF-32, EBCDIC).
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
        Detector 3 reads a little further, and no further than the parser:
        every string literal as the parser joined it (adjacent literals, even
        wrapped across lines), every run of CONSECUTIVE literal operands in a
        `+` chain, and an f-string's literal parts with its placeholders
        dropped -- so `"pst-" + "<body>"` and `f"pst-<half>{x}<half>"` are
        named. `"pst-" + BODY` is not: a NAME is never resolved, and only
        detector 2 reading BODY's own literal stands behind that shape.
      - A HEX KEY UNDER AN INNOCENT NAME -- see THE HEX LIMIT below.
      - A POSITIONAL ARGUMENT: `connect("db", "svc", "Xk29qLm4Pz")` binds the
        credential to no name at all, so detector 1 has nothing to read and a
        ten-character password has no entropy signal for detector 2. Nothing
        short of taint-tracking catches this one.
  * THE PROVIDER VIEW IS THE NOVELAI ENTRY'S ALONE, AND IT UNDOES A FIXED
    LIST OF WRAPPINGS, NOT EVERY ONE. It deletes NULs, then spaces out a CSI
    control sequence (colour, erase-line, cursor, empty-parameter reset) whose
    ESC is real or escaped as backslash-u001b or backslash-x1b in either hex
    case, backslash-033, backslash-e or backtick-e; backslash-uXXXX and
    backslash-xXX in either hex case; a backslash or a PowerShell backtick
    before one of n r t 0 a b f v e; and `%XX` in either hex case. No other
    pattern and no other detector reads it: run for every provider it made an
    `Authorization` value out of an escaped newline and prose. The view only
    ever SEPARATES, so its one over-reading is the opposite kind: an escaped
    BACKSLASH before one of those letters (a Windows path in JSON,
    `\\\\new`), or a backtick code span opening on one, is read as an escape,
    so `npst-<64 mixed characters>` there would be named.
    Still missed, each measured by a verifier (the last two are not misses):
      - UTF-16LE WITH a BOM, then an 8-bit append (`Out-File -Encoding utf8`).
      - ESC lost in a copy: shown as an arrow (U+2190), as `^[`, or dropped.
      - A colour reset BETWEEN `pst-` and the body (grep colouring a match).
      - A CJK or kana character before the token in BOM-less UTF-16LE.
      - A non-UTF-8 file with NULs and no 32-character UTF-16 run: skipped.
      - Every provider but novelai in BOM-less UTF-16LE: no view, no NULs out.
      - Double percent-encoding: `%2520`.
      - Octal byte runs: `\\342\\200\\231`.
      - Quoted-printable: `=E2=80=99`.
      - Eight-digit backslash-U, and PyYAML's backslash-N, -L and -P.
      - A name-resolved Python split: `"pst-" + BODY`.
      - Label only: `NOVELAI_API_KEY=<tok>` is reported as credential-shaped name.
      - Accepted false positive: a 64+ `pst-` slug with A-Z, a-z and 0-9.
    Placement: a token the raw-line reading sees as a PREFIX of a longer
    literal -- `("pst-<64>" "abc")` -- is reported twice, once at each
    length, because `_dedupe` merges only equal lengths; both are on the
    same line. A tracked path that is not UTF-8 makes the sweep raise, naming
    the byte, rather than skip it.

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
     On a `.py` it reads twice: the raw lines, and every string the PARSER
     sees, so a token split across adjacent literals or `+` is still one
     token (see `_literal_runs`). Both readings run every pattern over the
     text AS WRITTEN, and the novelai pattern alone again over its PROVIDER
     VIEW (`provider_view`), where an escape, a control sequence, a
     percent-encoded byte and a NUL no longer sit in front of a token
     pretending to be a letter.
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
import codecs
import io
import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
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
_NOVELAI_LABEL = "novelai persistent token"
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
    # `pst-` + 64 URL-safe characters. The author's real one lives in the
    # Windows user environment as NAI_KEY and is read with os.environ, which
    # no detector flags. Every guard reads the TOKEN and never the rest of the
    # line, and each is pinned from both sides and proved by mutation:
    #
    #   a 64-character FLOOR, and 64 is MEASURED rather than chosen: two REAL
    #     persistent tokens, one revoked and one live, were tested as booleans
    #     only and never printed. Both carry a body of EXACTLY 64 characters,
    #     all inside [A-Za-z0-9_-], each with an uppercase letter, a lowercase
    #     letter and a digit, and both match this rule. The floor used to be
    #     40, and 40 named every dated slug and branch name that happened to
    #     carry a capital and a digit (`report-pst-2026-09-16-...-NOTES.md`,
    #     `claude/pst-fix-2026-09-16-UTF16-BOM-...`); under 64 characters all
    #     of those are silent now. A body of 64 is named and one of 63 is not.
    #   a LOOKBEHIND that refuses a LETTER OR DIGIT before `pst-` (`xpst-`,
    #     `Xpst-`, `7pst-`, `inputpst-` are somebody's identifier) and ACCEPTS
    #     everything else, `_` and `-` included. It carries NO escape
    #     alternative any more: `provider_view` has already turned `\n`,
    #     `\u2019`, `\u001b[K`, `%20`, a PowerShell backtick escape and a
    #     NUL into a space or nothing
    #     before this runs, so an escape's letter never reaches the lookbehind.
    #     The escape alternative it replaces read only `\n` `\r` `\t`, and was
    #     measured missing 0/2000 behind a `json.dumps` smart quote, an escaped
    #     ANSI colour code and a `%20`.
    #   an UPPERCASE letter, a LOWERCASE letter AND a DIGIT, each looked for
    #     only inside the token's own charset. The first draft looked for a
    #     capital-or-digit with a lookahead that could run off the token, so a
    #     lowercase slug followed by `(PR 42)` depended on where the regex
    #     happened to stop. A random 64-character URL-safe body lacks a digit
    #     with probability (54/64)**64 ~ 1.9e-5 and a capital or a lowercase
    #     letter with (38/64)**64 ~ 3e-15; the seeded 20000-body sample below
    #     re-measures that on every run. A dated lowercase slug has no
    #     capital, an all-caps placeholder (`pst-` + `X`*64, or
    #     `YOUR_..._TOKEN_GOES_HERE_000`) has no lowercase, and a Title-Case
    #     slug has no digit, so all three stay silent.
    #
    # Stated misses. This ASSUMES a mixed-case URL-safe alphabet of at least
    # 64: a token whose real alphabet were lowercase-only or hex, or a future
    # format with a shorter body, would be missed outright. ACCEPTED FALSE-
    # POSITIVE CLASS: a slug that starts `pst-`, runs 64+ characters and
    # carries a capital, a lowercase letter and a digit fires, and a row in
    # PROVIDER_MUST_NAME pins it firing, so the class is a recorded decision
    # rather than a surprise. Measured 2026-09-16: `git grep -ni "pst-"` over
    # the tracked tree names no file but this one. Detector 2 already catches
    # many of these shapes by entropy, which is why the fixtures for this entry
    # assert its LABEL rather than a bare hit -- see PROVIDER_MUST_NAME.
    (_NOVELAI_LABEL,
     re.compile(r"(?<![A-Za-z0-9])pst-"
                r"(?=[A-Za-z0-9_\-]*[A-Z])(?=[A-Za-z0-9_\-]*[a-z])"
                r"(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{64,}")),
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
    """Detector 3 over one line or one literal: the label, or None. Reads the
    provider view exactly as `_scan_structural` does, through the same call."""
    view = provider_view(text)
    for label, pattern in _STRUCTURAL:
        if _provider_search(label, pattern, text, view):
            return label
    return None


# THE PROVIDER VIEW. Every provider pattern guards the ONE character before its
# prefix, and every serialiser a key passes through on its way into a tracked
# file puts something letter-shaped there. Measured by two verifiers, each a
# total miss (0 of 2000) before this existed: `json.dumps` writes a smart quote
# as `\u2019`, so the character before `pst-` is the escape's last hex digit; a
# chat transcript writes a colour code as `\u001b[32m`, so it is `m`; a URL
# writes a space as `%20`, so it is `0`; and PowerShell 5.1's `>>` appends
# UTF-16LE with no BOM, so every character is followed by a NUL. Each is
# replaced by ONE SPACE -- a NUL is deleted -- and nothing here can match or
# remove a newline, so a line number read off the view is the line number of
# the text. A space only ever SEPARATES; the one thing that joins is deleting a
# NUL, which is what BOM-less UTF-16 needs.
#
#   NULs are deleted FIRST, before any substitution: in `>>`-appended UTF-16LE
#   an escaped newline is `\ NUL n NUL`, and it is an escape only once the NULs
#   are gone. A corpus row pins that order.
#   (a) a CSI control sequence -- ESC, `[`, parameters from `0-9;?` (none at
#       all is `ESC[m`), ONE final letter of either case: colour, erase-line
#       `ESC[K`, cursor `ESC[1G` `ESC[H`, `ESC[?25h`. The ESC is real, or
#       escaped as `\u001b` or `\x1b` in either hex case, `\033`, `\e`, or
#       PowerShell's backtick-e. Tried FIRST, or (b) and (c) eat its head and
#       leave `[32m` in front of the token;
#   (b) `\uXXXX` and `\xXX`, either hex case (System.Text.Json and Jackson
#       write UPPERCASE; Python and Go write lowercase);
#   (c) a BACKSLASH or a PowerShell BACKTICK before one of `_ESCAPE_LETTERS`;
#   (d) a percent-encoded byte `%XX`, either hex case.
#
# It is a SECOND reading, never a replacement: the pattern still reads the text
# as written first, because a connection URL whose password is spelled `p%40ss`
# is a credential the view would break in two at the `%40`.
#
# AND IT IS THE NOVELAI ENTRY'S ALONE (`_READS_VIEW`). Run for every provider,
# verifier B measured it making credentials the file does not contain: an
# escaped newline welds `Bearer` to the next word of prose, and a `%2F` or an
# escaped newline puts a word boundary in front of `sk-learn-...`. HEAD fired
# on none of those, so every other pattern reads the text as written, only.
_ESCAPE_LETTERS = "nrt0abfve"          # one string for BOTH escape characters
_READS_VIEW = frozenset((_NOVELAI_LABEL,))
_PROVIDER_NOISE = re.compile(
    r"(?:\x1b|\\(?:u001[bB]|x1[bB]|033|e)|`e)\[[0-9;?]*[A-Za-z]"
    r"|\\u[0-9A-Fa-f]{4}|\\x[0-9A-Fa-f]{2}"
    r"|[\\`][" + _ESCAPE_LETTERS + r"]"
    r"|%[0-9A-Fa-f]{2}")


def provider_view(text: str) -> str:
    """`text` with NULs deleted, THEN escapes, control sequences and
    percent-encoding spaced out -- for the patterns in `_READS_VIEW` only.
    Detectors 1 and 2 never read it: an entropy test over a view is a second
    chance to cry wolf, and so is every other provider pattern."""
    return _PROVIDER_NOISE.sub(" ", text.replace("\x00", ""))


def _provider_search(label: str, pattern, text: str, view: str):
    """The first match in the text AS WRITTEN; failing that, and only for a
    pattern in `_READS_VIEW`, the first match in its provider view."""
    match = pattern.search(text)
    if match is None and label in _READS_VIEW:
        match = pattern.search(view)
    return match


def _lines(source: str) -> list[str]:
    """Physical lines, split on `\\n` ALONE -- the separator `decode_text`
    leaves and the one the parser counts. `str.splitlines` also breaks on
    U+0085, and a cp1252 ellipsis read as latin-1 IS U+0085, so every line
    after one was placed a line late."""
    return source.split("\n")


def _placed(lines: list[str], first: int, last: int, text: str, match) -> int:
    """The physical line a literal-pass hit belongs on. The first line of the
    literal whose text carries the whole match, which is where the raw-line
    pass found it too; otherwise, for a token the source wrote in PIECES, the
    literal's first line plus the newlines before the match, never past its
    last. Counting the VALUE's newlines alone put a token behind an ESCAPED
    `\\n` in a triple-quoted literal one line late, and it was reported twice.
    The line's provider view is NOT consulted, and that is not an omission:
    only the novelai pattern reads a view, its match never includes the
    character before `pst-`, and the view only inserts SPACES except where it
    deletes a NUL -- which `ast.parse` refuses, so no parsed line has one."""
    token = match.group(0)
    for number in range(first, min(last, len(lines)) + 1):
        if token in lines[number - 1]:
            return number
    return min(last, first + text.count("\n", 0, match.start()))


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


def _literal_text(node) -> str | None:
    """A str constant's value, or an f-string's LITERAL parts joined with its
    placeholders dropped. The f-string half is a deliberate over-reading, not
    a fact about the runtime value: it exists so a token split round a
    placeholder -- `f"pst-<half>{sep}<half>"` -- is still read as one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(piece.value for piece in node.values
                       if isinstance(piece, ast.Constant)
                       and isinstance(piece.value, str))
    return None


def _literal_runs(tree):
    """(first line, last line, text) for every run of literal text a Python
    file carries AS THE PARSER SEES IT, for detector 3. The raw-line reading
    is blind to a token the source wrote in pieces, and three joins close the
    ordinary spellings of that without evaluating anything:

      * a str constant -- adjacent literals, even wrapped across lines, are
        already ONE constant by the time the parser hands them over;
      * a `+` chain, flattened, each run of CONSECUTIVE literal operands
        joined: `x + "a" + "b"` contains `ab` at runtime whatever `x` is,
        and `"a" + x + "b"` is not read as `ab`. A NAME is never resolved;
      * an f-string, through `_literal_text`.

    A chain is read once, from its outermost `+`, and its literal operands
    are not read again on their own -- a shorter read of the same operand is
    a second finding of a different length, which `_dedupe` cannot merge."""
    in_chain: set[int] = set()
    for node in ast.walk(tree):
        if id(node) in in_chain:
            continue
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
            text = _literal_text(node)
            if text is not None:
                yield node.lineno, getattr(node, "end_lineno", node.lineno), text
            continue
        run: list = []
        stack = [node]
        while stack:
            current = stack.pop()
            in_chain.add(id(current))
            if isinstance(current, ast.BinOp) and isinstance(current.op, ast.Add):
                stack.extend((current.right, current.left))
                continue
            text = _literal_text(current)
            if text is None:
                if run:
                    yield (run[0].lineno, run[-1].end_lineno,
                           "".join(_literal_text(n) for n in run))
                run = []
            else:
                run.append(current)
        if run:
            yield (run[0].lineno, run[-1].end_lineno,
                   "".join(_literal_text(n) for n in run))


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
    for number, line in enumerate(_lines(source), 1):
        view = provider_view(line)
        for label, pattern in _STRUCTURAL:
            match = _provider_search(label, pattern, line, view)
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
    for number, line in enumerate(_lines(source), 1 + offset):
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
    for number, line in enumerate(_lines(source), 1):
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

    # Detector 3 again, over the strings the PARSER sees. The raw-line pass in
    # `_scan_structural` already reads every line of this file; this pass is
    # for a token the source wrote in PIECES. Each string is read as the parser
    # decoded it, FIRST and by every pattern -- a DSN whose password carries
    # `%40` and is split across adjacent literals is named by that reading
    # alone -- and then, for a pattern in `_READS_VIEW` only, through its
    # provider view, because a decoded literal still carries `%20`, a real ESC
    # control sequence, and a raw string's `\n`, which is the case the raw-line
    # pass cannot rescue when the token is also split. A hit is placed by
    # `_placed`, so a token both passes see lands on ONE line at ONE length.
    lines = _lines(source)
    for first, last, text in _literal_runs(tree):
        view = provider_view(text)
        for label, pattern in _STRUCTURAL:
            viewed = label in _READS_VIEW and view != text
            for read in ((text, view) if viewed else (text,)):
                for match in pattern.finditer(read):
                    found.append(Finding(path,
                                         _placed(lines, first, last, read, match),
                                         "<literal>", match.group(0), label))

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
    lines = _lines(source)
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


_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)

# How `scan_file` read a file: TEXT ran all three detectors, BYTES ran detector
# 3 alone over a latin-1 reading of a file that is not UTF-8, and None is a
# binary that was skipped.
TEXT, BYTES = "text", "bytes"

# A file with NUL bytes that is not UTF-8 is BINARY unless it carries this: 32
# UTF-16 ASCII characters in a row, a printable byte then a zero byte. Measured
# over the 11 tracked binaries (nine PNG, an OGG, a WAV): the longest such run
# in any of them is 6. A novelai token alone is a run of 68, so no floor at or
# under that can skip a file carrying one IN UTF-16; what 32 decides is a file
# whose token is in its 8-bit text beside a short UTF-16 run, and a corpus row
# pins it from both sides -- a run of exactly 32 is read, a WAV's 31 is not.
_UTF16_ASCII_RUN = re.compile(rb"(?:[\t\n\r\x20-\x7e]\x00){32}")


def _one_newline(text: str) -> str:
    """Every line ending as `\\n`, exactly as a text-mode `open` did before
    this module read bytes -- plus `\\r NUL \\n`, which is a CRLF of BOM-less
    UTF-16LE read as UTF-8 or latin-1, and which the two replacements after it
    would otherwise count as TWO lines."""
    return text.replace("\r\x00\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def decode_text(raw: bytes) -> str:
    """A tracked file's text, or UnicodeDecodeError. UTF-16 ONLY behind its
    byte-order mark, which is the one encoding signal that is not a guess --
    Windows PowerShell 5.1's `>` redirect and `reg export` both write one, and
    both used to be skipped as unreadable. UTF-8 through `utf-8-sig`, so a BOM
    is dropped rather than handed to `ast.parse` as U+FEFF, which refuses it
    and silently took the whole literal pass off a BOM `.py`."""
    if raw.startswith(_UTF16_BOMS):
        text = raw.decode("utf-16")                  # the codec eats the BOM
    else:
        text = raw.decode("utf-8-sig")
    return _one_newline(text)


def scan_file(path: str, relative: str | None = None):
    """Returns (findings, how). `how` is TEXT for a file `decode_text` reads;
    BYTES for one that is not UTF-8 -- read as latin-1, detector 3 only,
    because a provider token is ASCII in every codepage and a name or an
    entropy reading of a guessed codepage is a guess; and None for a binary
    (NUL bytes and no UTF-16 ASCII run) or a file that cannot be opened,
    which this check cannot see into and counts as skipped."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return [], None
    name = relative or path
    try:
        source = decode_text(raw)
    except UnicodeDecodeError:
        if b"\x00" in raw and not _UTF16_ASCII_RUN.search(raw):
            return [], None
        source = _one_newline(raw.decode("latin-1"))
        return _dedupe(_scan_structural(name, source)), BYTES
    return scan_source(name, source), TEXT


def split_ls_files(raw: bytes) -> list[str]:
    """`git ls-files -z` output as paths, decoded as UTF-8 EXPLICITLY. With
    `-z` git neither quotes nor escapes a path, it writes the path's bytes,
    and those are UTF-8. The previous reader passed `text=True`, which
    decodes with the LOCALE -- cp1252 on the author's machine -- so `é`
    arrived as two characters naming no file, which was then skipped as
    unopenable in silence; and a path holding byte 0x81 (`ā` is C4 81),
    undefined in cp1252, made the pipe's reader thread raise, left stdout
    None, and killed the check on an AttributeError."""
    return [p for p in raw.decode("utf-8").split("\0") if p.strip()]


def tracked_files(root: str = ROOT) -> list[str] | None:
    """Every tracked path under `root`. None ONLY when git cannot be started
    at all; a git that starts and does not answer raises RuntimeError naming
    why, because an empty or unread tree must never pass as a clean one."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                             capture_output=True, timeout=60)
    except OSError:                                          # pragma: no cover
        return None
    except subprocess.TimeoutExpired as exc:                 # pragma: no cover
        raise RuntimeError(f"git ls-files timed out after {exc.timeout}s "
                           f"in {root}") from exc
    if out.returncode != 0 or out.stdout is None:
        stderr = (out.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"git ls-files exited {out.returncode} in {root}: "
                           f"{stderr or 'no output'}")
    try:
        return split_ls_files(out.stdout)
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"git ls-files in {root} printed a path that is not "
                           f"UTF-8 at byte {exc.start}") from exc


def sweep(root: str = ROOT) -> dict | None:
    """Every tracked file under `root` through `scan_file` -- the tree
    assertion's whole input. None ONLY when git cannot be started at all.
    A git that starts and FAILS is not an empty tree: its error is a line of
    `verdict`, the very list the tree assertion demands be empty. It used to
    be a separate assertion, and deleting that one line left the check green
    over a sweep of nothing, because git works on the author's tree; a
    corpus row now sweeps a broken repository through this function."""
    report = {"error": None, "findings": [], "swept": 0, "as_bytes": 0,
              "skipped": 0}
    try:
        tracked = tracked_files(root)
    except RuntimeError as exc:
        report["error"] = str(exc)
        tracked = []
    if tracked is None:                                      # pragma: no cover
        return None
    for relative in tracked:
        hits, how = scan_file(os.path.join(root, relative), relative)
        if how is None:
            report["skipped"] += 1
            continue
        report["swept"] += 1
        report["as_bytes"] += how == BYTES
        report["findings"].extend(hits)
    report["verdict"] = (
        ([f"git ls-files failed: {report['error']}"] if report["error"] else [])
        + [str(hit) for hit in report["findings"]])
    return report


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
    hits, how = scan_file(target_path, os.path.basename(target_path))
    if how is None:
        print(f"skipped: binary (not UTF-8, NUL bytes, no UTF-16 text run) "
              f"or unopenable: {target_path}")
        sys.exit(2)
    if how == BYTES:
        print("not UTF-8: read as bytes, detector 3 (provider patterns) only")
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
# A NovelAI persistent token's shape: `pst-` and 64 URL-safe characters, both
# `_` and `-` included on purpose. The prefix is its own part so no line of
# this file ever spells `pst-` followed by the body.
_NOVELAI = decoy("pst-", "Xk29qLm4PzRt7Bd2", "Nc04WpaB3kZq91Lm",
                 "Qv71mLz4BnRt9X_e", "Zk84Lq02MnRvTt-y")
# The floor, from BOTH sides, with the same high-entropy alphabet: `_NOVELAI`
# is a body of exactly 64 -- the length both real tokens measured -- and this
# is one of 63, every character class present in both, so the only thing that
# separates them is the number the floor names.
_NOVELAI_63 = _NOVELAI[:-1]
_NOVELAI_BODY = _NOVELAI[len("pst-"):]
# THE ACCEPTED FALSE-POSITIVE CLASS: a 71-character dated slug carrying a
# capital, a lowercase letter and a digit. Assembled, because spelled out it
# would fire on this file.
_NOVELAI_SLUG = decoy("pst-", "2026-09-16", "-Collision", "-Companion",
                      "-Migration", "-Notes-And", "-Followups", "-For-Review")

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
    ('NAI_KEY = os.environ["NAI_KEY"]',
     "the NovelAI key read from the user environment, which is where it lives"),
    ('NAI_KEY = os.environ.get("NAI_KEY")',
     "the same through .get with no fallback"),
    ('NAI_ENV = "NAI_KEY"', "the environment variable's NAME is a pointer"),
    ('NAI_KEY = os.environ.get("NAI_KEY", "")',
     "the NovelAI read with an EMPTY fallback -- no `pst-` in it, so this row "
     "pins detector 1's empty-value rule and no novelai regex change can "
     "turn it red; the rows that can are in TEXT_MUST_NOT_FIRE"),
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
    ("notes.md", "NAI_KEY", "md: the NovelAI variable's NAME, alone"),
    ("notes.md", "Compare the pst-v2 draft against pst-final before merging.",
     "md: a SHORT pst- word in prose -- the half the novelai floor exists for"),
    ("notes.md", "see pst-migration-notes-for-the-collision-companion-layer (PR 42)",
     "md: a lowercase pst- slug with no digit and no capital in the token and "
     "both later on the line"),
    # The slugs verifier B measured FIRING under the old 40-character floor:
    # each carries a capital, a lowercase letter and a digit, and each body is
    # 40 to 63 characters, so the floor's value is the only thing silencing
    # it. A floor back at 40 turns all four red.
    ("notes.md",
     "docs/history/report-pst-2026-09-16-collision-companion-migration-NOTES.md",
     "md: a dated report filename with a capitalised tail, 46 characters"),
    ("notes.md", "branch claude/pst-fix-2026-09-16-UTF16-BOM-decode-in-check-secrets",
     "md: a branch name, 48 characters"),
    ("server.log", "started pst-run-20260916T100000Z-abc123def456-worker-01 ok",
     "log: a run identifier, 43 characters"),
    ("notes.md", "NAI_KEY=pst-Your_Persistent_Token_Goes_Here_" + "0" * 10,
     "md: a Title-Case placeholder with a digit tail, 42 characters"),
    # Each row below pins ONE lookahead from both directions: removing it makes
    # the token satisfy the rest, and widening it from the token's charset to
    # `.*` lets the trailing text on the same line satisfy it instead. Every
    # body here is OVER the 64 floor, or the floor would silence it first and
    # the lookahead would be untested.
    ("notes.md", "see pst-2026-09-16-collision-companion-migration-notes-and-"
                 "followups-for-review (PR 42)",
     "md: the CAPITAL lookahead -- a dated lowercase slug over the floor has "
     "digits and lowercase and no capital, and `PR` sits later on the line"),
    ("notes.md",
     "see pst-Migration-Notes-For-The-Collision-Companion-Layer-And-Its-"
     "Followup-Review (PR 42)",
     "md: the DIGIT lookahead -- a Title-Case slug over the floor has capitals "
     "and lowercase and no digit, and `42` sits later on the line"),
    ("notes.md",
     "NAI_KEY=pst-YOUR_PERSISTENT_TOKEN_GOES_HERE_" + "0" * 32 + " (paste yours)",
     "md: the LOWERCASE lookahead -- an all-caps placeholder with digits has "
     "no lowercase letter, and `paste yours` sits later on the line"),
    (".env", "NAI_KEY=pst-" + "X" * 64,
     "env: an all-caps placeholder body with neither digit nor lowercase"),
]
for text_path, body, why in TEXT_MUST_NOT_FIRE:
    expect(f"silent: {why}", [str(h) for h in scan_source(text_path, body)], [])

# 3a. A PROVIDER ENTRY MUST NAME ITSELF. A bare `bool(hits)` cannot prove a
#     detector 3 entry is alive when detector 2 already reads the same string
#     by entropy -- measured before the novelai entry existed: a synthetic
#     `pst-` token under `NAI_KEY` in a .py, in prose and in a tmx attribute
#     was ALREADY caught (as a high-entropy literal), while the same token in a
#     python comment and on a dotenv `NAI_KEY=` line was not caught at all. So
#     a dead regex would leave a bool corpus green on three of five shapes.
#     These rows assert the LABEL is among the verdicts, which only the entry
#     under test can produce. Not the exact verdict list: on half these shapes
#     detector 2 legitimately reads a run of a DIFFERENT length beside it --
#     `_<token>_`, `auth-<token>`, the body operand of a `+` -- and a row that
#     demanded detector 2's silence would be asserting something about
#     detector 2. PROVIDER_MUST_NOT_NAME is the other half: the label ABSENT,
#     whatever detector 2 says, which is what lets its negatives carry a real
#     high-entropy body instead of one chosen to dodge the entropy test.
PROVIDER_MUST_NAME = [
    # THE PROVIDER VIEW, one row per thing it spaces out, each on a route with
    # no parser behind it so the raw-line reading is the only reader. The
    # escaped letters first -- `n`, `r`, `t` are the ones the deleted escape
    # lookbehind knew about.
    ("conf.json", '{"note": "my NovelAI key:\\n%s"}' % _NOVELAI, _NOVELAI_LABEL,
     "json: after an escaped NEWLINE inside a one-line string"),
    ("transcript.jsonl",
     '{"role": "user", "content": "persistent token\\t%s"}' % _NOVELAI,
     _NOVELAI_LABEL, "jsonl: after an escaped TAB in a chat transcript line"),
    ("deploy.yaml", 'voice_note: "rotated\\r%s"' % _NOVELAI, _NOVELAI_LABEL,
     "yaml: after an escaped CARRIAGE RETURN in a quoted scalar"),
    ("corpus.py", 'print("NovelAI token:\\n%s")' % _NOVELAI, _NOVELAI_LABEL,
     "py: after an escaped newline in a print"),
    # The lookbehind's ACCEPTING half: punctuation that is not a letter/digit.
    ("notes.md", "the key is _%s_ and nothing else" % _NOVELAI, _NOVELAI_LABEL,
     "md: a token in _italics_, underscore before `pst-`"),
    ("server.log", "2026-09-16T12:00:01 accepted auth-%s" % _NOVELAI,
     _NOVELAI_LABEL, "log: `auth-<token>`, a hyphen before `pst-`"),
    # A backslash is not an escape LETTER: a Windows path puts one directly
    # before the token, and a view that ate `\p` would hide it. Written the
    # way PowerShell 5.1's `>>` appends it -- UTF-16LE with no BOM, read as
    # UTF-8, a NUL after every character -- because written plainly the text
    # AS WRITTEN already names it and a greedy view is never noticed.
    # Measured: the plain row survived a view widened to backslash-[a-z].
    ("paths.txt", "\0".join("C:\\Users\\me\\" + _NOVELAI) + "\0",
     _NOVELAI_LABEL, "txt: a BACKSLASH before `pst-` in a Windows path, "
     "NUL-interleaved, so only the view reads it"),
    # The floor's accepting side. Its refusing side is PROVIDER_MUST_NOT_NAME.
    ("notes.md", "token %s rotated" % _NOVELAI, _NOVELAI_LABEL,
     "md: a body of EXACTLY 64 characters, on the floor -- the length both "
     "real tokens measured"),
    ("notes.md", "docs/history/report-%s.md" % _NOVELAI_SLUG, _NOVELAI_LABEL,
     "md: THE ACCEPTED FALSE POSITIVE -- a 71-character dated slug with a "
     "capital and a digit fires, and that is recorded, not overlooked"),
    # The rest of the view: what `json.dumps(ensure_ascii=True)` writes for a
    # character the editor saves under data/project/, what a transcript
    # writes for a colour code, what a URL writes for a space, and a
    # percent-encoded DSN whose `%40` the view must NOT be the only reader of.
    ("scripts.json", json.dumps({"say": "key\u2019" + _NOVELAI}), _NOVELAI_LABEL,
     "json: an ESCAPED SMART QUOTE `\\u2019` directly before the token, as "
     "json.dumps writes it"),
    ("scripts.json", '{"html": "\\u003cb\\u003e%s"}' % _NOVELAI, _NOVELAI_LABEL,
     "json: a Go-style HTML escape `\\u003e` directly before the token"),
    ("session.jsonl",
     json.dumps({"type": "tool_result", "content": "\x1b[32m%s\x1b[0m" % _NOVELAI}),
     _NOVELAI_LABEL,
     "jsonl: an ESCAPED ANSI colour code `\\u001b[32m` directly before the token "
     "-- tried before `\\uXXXX`, or `[32m` is left in front of it"),
    ("build.log", "\x1b[1;32m%s\x1b[0m" % _NOVELAI, _NOVELAI_LABEL,
     "log: a REAL ESC colour code directly before the token"),
    ("repr.txt", "echo -e '\\x1b[32m%s'" % _NOVELAI, _NOVELAI_LABEL,
     "txt: a colour code escaped as `\\x1b[32m`"),
    ("run.sh", "printf '\\033[32m%s\\033[0m'" % _NOVELAI, _NOVELAI_LABEL,
     "sh: a colour code escaped in octal as `\\033[32m`"),
    ("repr.txt", "'voice key:\\xa0%s'" % _NOVELAI, _NOVELAI_LABEL,
     "txt: a Python repr's `\\xa0` directly before the token"),
    ("corpus.py", 'NOTE = "pasted as%%20%s"' % _NOVELAI, _NOVELAI_LABEL,
     "py: a PERCENT-ENCODED space `%20` before the token in a string"),
    ("corpus.py", "# pasted as%%20%s" % _NOVELAI, _NOVELAI_LABEL,
     "py: the same `%20` in a COMMENT, which only the raw-line reading sees"),
    ("corpus.py",
     'NAI_KEY = (\n    "note%%20%s"\n    "%s"\n)' % (_NOVELAI[:36], _NOVELAI[36:]),
     _NOVELAI_LABEL,
     "py: `%20` before a token SPLIT across adjacent literals -- no physical "
     "line holds it, so only the literal pass's own provider view can name it"),
    ("notes.md", "connect to %s" % decoy("postgres://svc:", "Xk29%40qLm4Pz",
                                        "@db.internal:5432/app"),
     "url with inline credentials",
     "md: a DSN whose password carries `%40` -- the view breaks it in two, so "
     "the text AS WRITTEN must still be read first"),
    ("corpus.py",
     'DATABASE_URL = (\n    "%s"\n    "%s"\n)'
     % (decoy("postgres://svc:", "Xk29%40"), decoy("qLm4Pz", "@db.internal:5432/app")),
     "url with inline credentials",
     "py: the same `%40` DSN SPLIT across adjacent literals -- no physical line "
     "holds it and the view breaks it, so the literal pass must read the "
     "parser's text as written, not only its view"),
    # Python pieces, which the raw-line reading cannot join. `_literal_runs`.
    ("corpus.py", 'NAI_KEY = "pst-" + "%s"' % _NOVELAI_BODY, _NOVELAI_LABEL,
     "py: `\"pst-\" + body`, an explicit concatenation"),
    ("corpus.py",
     'NAI_KEY = "pst-" + "%s" + "%s"' % (_NOVELAI_BODY[:32], _NOVELAI_BODY[32:]),
     _NOVELAI_LABEL, "py: a 32 + 32 split behind the prefix"),
    ("corpus.py",
     'NAI_KEY = (\n    "%s"\n    "%s"\n)' % (_NOVELAI[:36], _NOVELAI[36:]),
     _NOVELAI_LABEL, "py: ADJACENT literals wrapped across two lines"),
    ("corpus.py", 'NAI_KEY = f"%s{SEP}%s"' % (_NOVELAI[:36], _NOVELAI[36:]),
     _NOVELAI_LABEL, "py: an f-string split round a placeholder"),
    ("corpus.py", 'NAI_KEY = PREFIX + "%s" + "%s"' % (_NOVELAI[:36], _NOVELAI[36:]),
     _NOVELAI_LABEL,
     "py: consecutive literals AFTER a name in a `+` chain still join"),
    ("corpus.py", 'NAI_KEY = "%s"' % _NOVELAI, _NOVELAI_LABEL,
     "py: a novelai token under the very name its environment variable has"),
    ("corpus.py", 'voice = os.environ.get("NAI_KEY", "%s")' % _NOVELAI,
     _NOVELAI_LABEL,
     "py: a committed novelai FALLBACK beside a correct NAI_KEY read"),
    ("corpus.py", "# NovelAI: %s" % _NOVELAI, _NOVELAI_LABEL,
     "py: a novelai token in a COMMENT, which detector 2 never reads"),
    (".env", "NAI_KEY=%s" % _NOVELAI, _NOVELAI_LABEL,
     "env: a novelai token welded to its name by `=` -- detector 2 reads one "
     "unkeyish run and `NAI_KEY` carries no credential word"),
    ("notes.md", "Paste your token (%s) into the prompt strip." % _NOVELAI,
     _NOVELAI_LABEL, "md: a novelai token bare in prose"),
    ("conf.json", '{\n  "novelai": {\n    "persistent": "%s"\n  }\n}' % _NOVELAI,
     _NOVELAI_LABEL, "json: a novelai token nested and pretty-printed"),
    ("fixture.tmx",
     '  <property name="pyoneer_param_voice" value="%s"/>' % _NOVELAI,
     _NOVELAI_LABEL, "tmx: a novelai token in an xml attribute value"),
]
# The other one-letter escapes, and the four characters verifier A
# measured 0/2000 behind as `json.dumps` writes them -- a non-breaking space, a
# zero-width space, an ellipsis, an em dash (the smart quote is a row above).
PROVIDER_MUST_NAME += [
    ("escapes.log", "key\\%s%s" % (_letter, _NOVELAI), _NOVELAI_LABEL,
     "log: after an escaped `\\%s`" % _letter) for _letter in "fvb0ea"]
# THE WIDENED VIEW, one row for every spelling a mutant could drop. The letters
# are SPELLED here, never read off `_ESCAPE_LETTERS`: a loop over the constant
# under test cannot notice a letter deleted from it. PowerShell's backtick
# escapes are what a hand-typed `"key:`n<token>"` puts in front of the token.
PROVIDER_MUST_NAME += [
    ("profile.ps1", '$note = "voice key:`%s%s"' % (_letter, _NOVELAI),
     _NOVELAI_LABEL, "ps1: after a PowerShell backtick escape `%s" % _letter)
    for _letter in "nrt0abfve"]
# A CSI sequence is not only colour: a spinner erases its line with `ESC[K` or
# `ESC[2K`, moves with `ESC[1G`, homes with `ESC[H`, shows the cursor with
# `ESC[?25h`; `tput sgr0` and git reset with the EMPTY-parameter `ESC[m`; GNU
# grep --color=always writes `ESC[01;31mESC[K`.
PROVIDER_MUST_NAME += [
    ("build.log", _csi + _NOVELAI, _NOVELAI_LABEL,
     "log: a real ESC sequence %s directly before the token" % ascii(_csi)[1:-1])
    for _csi in ("\x1b[m", "\x1b[K", "\x1b[2K", "\x1b[1G", "\x1b[?25h",
                 "\x1b[H", "\x1b[01;31m\x1b[K")]
PROVIDER_MUST_NAME += [
    ("session.jsonl", '{"content": "\\u001B[32m%s"}' % _NOVELAI, _NOVELAI_LABEL,
     "jsonl: an escaped ESC in UPPERCASE hex, as System.Text.Json and Jackson "
     "write it"),
    ("session.jsonl", '{"content": "\\u001b[m%s"}' % _NOVELAI, _NOVELAI_LABEL,
     "jsonl: an escaped EMPTY-parameter reset `ESC[m`"),
    ("session.jsonl", '{"content": "working\\r\\u001b[K%s"}' % _NOVELAI,
     _NOVELAI_LABEL, "jsonl: a progress line's escaped CR and erase-line"),
    ("run.sh", "echo -e '\\x1B[32m%s'" % _NOVELAI, _NOVELAI_LABEL,
     "sh: `\\x1B[32m`, hand-written in UPPERCASE hex"),
    ("run.sh", "printf '\\033[2K%s'" % _NOVELAI, _NOVELAI_LABEL,
     "sh: `\\033[2K`, an octal ESC before an erase-line"),
    ("styles.yaml", 'banner: "\\e[32m%s"' % _NOVELAI, _NOVELAI_LABEL,
     "yaml: `\\e[32m`, the ESC escape of bash and PyYAML"),
    ("profile.ps1", 'Write-Host "`e[32m%s"' % _NOVELAI, _NOVELAI_LABEL,
     "ps1: PowerShell 7's backtick-e ESC before a colour code"),
    ("scripts.json", '{"html": "\\u003Cb\\u003E%s"}' % _NOVELAI, _NOVELAI_LABEL,
     "json: an UPPERCASE-hex unicode escape, as System.Text.Json writes `>`"),
    ("repr.txt", "'voice key:\\xA0%s'" % _NOVELAI, _NOVELAI_LABEL,
     "txt: an UPPERCASE-hex `\\xA0` directly before the token"),
    ("corpus.py", 'CALLBACK = "https%%3A%%2F%%2Fx%%2Fy%%3Ftoken%%3D%s"' % _NOVELAI,
     _NOVELAI_LABEL, "py: `%3D` before the token, a LETTER in the hex"),
    ("corpus.py", 'NOTE = "pasted as%%3d%s"' % _NOVELAI, _NOVELAI_LABEL,
     "py: a LOWERCASE `%3d` before the token"),
    ("notes.md", "keys%%2C%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: `%2C`, a percent-encoded comma, before the token"),
]
PROVIDER_MUST_NAME += [
    ("tables.json", json.dumps({"note": "key" + _char + _NOVELAI}),
     _NOVELAI_LABEL, "json: after json.dumps's %s" % ascii(_char)[1:-1])
    for _char in " ​…—"]
for text_path, body, label, why in PROVIDER_MUST_NAME:
    expect(f"names {label}: {why}",
           label in [h.why for h in scan_source(text_path, body)], True)

PROVIDER_MUST_NOT_NAME = [
    ("notes.md", "token %s rotated" % _NOVELAI_63, _NOVELAI_LABEL,
     "md: a body of 63 characters, ONE under the floor"),
    ("notes.md", "see x%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: a LETTER before `pst-` -- somebody's identifier, not the token"),
    ("notes.md", "see X%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: a CAPITAL before `pst-` -- the refused class is not lowercase-only"),
    ("notes.md", "see 7%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: a DIGIT before `pst-`, the other half of the alphanumeric class"),
    # The deleted escape lookbehind's letters WITHOUT their backslash. A view
    # or a lookbehind that forgot the backslash reads every identifier ending
    # in n, r or t as an escape.
    ("notes.md", "see input%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: `inputpst-`, an identifier ending in t, no backslash"),
    ("notes.md", "see owner%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: `ownerpst-`, an identifier ending in r, no backslash"),
    ("notes.md", "see hidden%s" % _NOVELAI, _NOVELAI_LABEL,
     "md: `hiddenpst-`, an identifier ending in n, no backslash"),
    # A NAME between two literals is never resolved: `_literal_runs` must
    # restart its run at the name, not carry `pst-` across it.
    ("corpus.py", 'NAI_KEY = "pst-" + SEP + "%s"' % _NOVELAI_BODY, _NOVELAI_LABEL,
     "py: `\"pst-\" + SEP + body` -- a name between the two literals"),
    # THE VIEW IS NOVELAI'S ALONE. Each of these was named by another provider
    # pattern reading the view and by nothing else -- verifier B, synthetic,
    # and HEAD fired on none of them. Written as `json.dumps` writes them.
    ("notes.json", '{"note": "see\\nBearer tokens_are_described_in_the_auth_docs"}',
     "http authorization value",
     "json: an escaped newline BEFORE the word Bearer, then prose"),
    ("notes.json", '{"note": "Bearer\\ntokens_are_described_in_the_auth_docs"}',
     "http authorization value",
     "json: the word Bearer, an escaped newline, then prose"),
    ("notes.json",
     '{"note": "## Basic\\ndata/graphics/tilesets/System/TileA2 is the sheet"}',
     "http authorization value",
     "json: a Basic heading, an escaped newline, then a path"),
    ("notes.json", '{"note": "see\\nsk-something-longer-than-twenty"}',
     "openai-style key", "json: an escaped newline before an `sk-` slug"),
    ("corpus.py",
     'TUTORIAL = "https%3A%2F%2Fexample.org%2Fsk-learn-classification-tutorial"',
     "openai-style key",
     "py: `%2F` before an `sk-` slug, which the raw lines AND the literal pass "
     "would both have named through the view"),
]
for text_path, body, label, why in PROVIDER_MUST_NOT_NAME:
    expect(f"does not name {label}: {why}",
           label in [h.why for h in scan_source(text_path, body)], False)

# ONCE, AND ON THE RIGHT LINE. A `.py` is read by detector 3 twice -- raw lines
# and `_literal_runs` -- so a token both readings see must land on one line at
# one length or it is reported twice. Every provider finding is listed with
# its line; other detectors' findings are filtered out, for the reason above.
PROVIDER_PLACED = [
    ("corpus.py", 'X = """\nabout the key\n%s\n"""' % _NOVELAI,
     [(3, _NOVELAI_LABEL)],
     "py: a token on the THIRD line of a triple-quoted literal is placed on "
     "line 3, where the raw-line reading also found it"),
    ("corpus.py", 'print("NovelAI token:\\n%s")' % _NOVELAI,
     [(1, _NOVELAI_LABEL)],
     "py: an ESCAPED newline in a one-line literal is not a new line"),
    ("corpus.py", 'NAI_KEY = "%s" + "%s" + "%s"'
     % (_NOVELAI[:40], _NOVELAI[40:], _NOVELAI_BODY[:8]),
     [(1, _NOVELAI_LABEL)],
     "py: a three-operand `+` chain is read ONCE, from its outermost `+` -- "
     "its inner `+` alone already spells a 64-character body"),
    ("corpus.py", 'X = """\nabout the key\\n%s\n"""' % _NOVELAI,
     [(2, _NOVELAI_LABEL)],
     "py: an ESCAPED `\\n` inside a TRIPLE-QUOTED literal is not a physical "
     "line -- counting the value's newlines put it on line 3 as well"),
]
for text_path, body, placed, why in PROVIDER_PLACED:
    expect(f"places: {why}",
           [(h.line, h.why) for h in scan_source(text_path, body)
            if h.why == _NOVELAI_LABEL], placed)

# A STATED LIMIT, pinned so the docstring cannot outlive it: a credential-shaped
# NAME outranks the provider label in `_dedupe` at the same line and length. The
# token is still reported, once -- as a credential-shaped name.
expect("dedupe: `NOVELAI_API_KEY=<token>` is reported once, as a "
       "credential-shaped name and not as the novelai label",
       [(h.line, h.why) for h in scan_source(".env", "NOVELAI_API_KEY=%s" % _NOVELAI)],
       [(1, "credential-shaped name")])

# 3a'. RECALL, measured rather than argued. Every row above is one token; the
#      three lookaheads are a claim about a whole ALPHABET, so a seeded sample
#      of random 64-character URL-safe bodies re-measures it on every run.
#      Expected misses are 20000 * 1.9e-5 ~ 0.4 (a body with no digit); a guard
#      that quietly narrowed the alphabet -- a floor above 64, a required `_`
#      -- misses thousands. The bodies are never printed, only counted.
_NOVELAI_RE = dict(_STRUCTURAL)[_NOVELAI_LABEL]
# Built, not spelled: the alphabet written out as one literal is itself a
# 64-character high-entropy run, and step 5 went red on it.
_URL_SAFE = string.ascii_letters + string.digits + "_-"
_sampler = random.Random(20260916)
_sample_misses = sum(
    1 for _ in range(20000)
    if not _NOVELAI_RE.search("pst-" + "".join(_sampler.choices(_URL_SAFE, k=64))))
print(f"  ..   novelai recall sample : {_sample_misses} of 20000 random "
      f"64-character bodies missed")
expect("novelai recall: at most 3 of 20000 random URL-safe bodies missed",
       _sample_misses <= 3, True)

# 3a''. THE ENCODING ROUTE, through `scan_file`, which is what the tree sweep
#       calls -- `scan_source` is handed text and never sees a byte. A key in
#       a file Windows PowerShell 5.1 wrote with `>` arrives as UTF-16LE behind
#       FF FE; `reg export` writes the same; and a genuinely binary file must
#       still be skipped rather than decoded into noise.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as _scratch:
    def _written(name: str, data: bytes) -> str:
        where = os.path.join(_scratch, name)
        with open(where, "wb") as handle:
            handle.write(data)
        return where

    _line = "NAI_KEY=%s\r\n" % _NOVELAI
    for _codec, _bom in (("utf-16-le", codecs.BOM_UTF16_LE),
                         ("utf-16-be", codecs.BOM_UTF16_BE)):
        _hits, _how = scan_file(
            _written(f"nai-{_codec}.txt", _bom + _line.encode(_codec)),
            f"nai-{_codec}.txt")
        expect(f"encoding: a BOM-marked {_codec} .txt is READ as text",
               _how, TEXT)
        expect(f"encoding: ...and names {_NOVELAI_LABEL} on line 1",
               [(h.line, h.why) for h in _hits], [(1, _NOVELAI_LABEL)])
    expect("encoding: a PNG header is still skipped as binary",
           scan_file(_written("sprite.png", b"\x89PNG\r\n\x1a\n" + bytes(16)),
                     "sprite.png"), ([], None))
    expect("encoding: an FF FE file that is not valid UTF-16 is skipped too",
           scan_file(_written("odd.bin", codecs.BOM_UTF16_LE + b"\x00"),
                     "odd.bin"), ([], None))

    def _provider_lines_at(where: str, name: str):
        """A raise is a VERDICT here, not a traceback: a codec that dies on
        one file kills the whole sweep, and must turn one row red."""
        try:
            hits, how = scan_file(where, name)
        except Exception as exc:
            return f"raised {type(exc).__name__}"
        return [(h.line, h.why) for h in hits if h.why == _NOVELAI_LABEL], how

    def _provider_lines(name: str, data: bytes):
        return _provider_lines_at(_written(name, data), name)

    # CRLF, past line 1. `_one_newline` must fold `\r\n` BEFORE it folds a bare
    # `\r`, or every CRLF is two lines and line 3 is reported as 5.
    expect("encoding: a CRLF .md with the token on line 3 reports line 3",
           _provider_lines("crlf.md", ("one\r\ntwo\r\nkey %s\r\n"
                                       % _NOVELAI).encode("ascii")),
           ([(3, _NOVELAI_LABEL)], TEXT))
    # A UTF-8 BOM. `ast.parse` refuses U+FEFF, and the fallback line route
    # cannot join a token split across adjacent literals.
    expect("encoding: a UTF-8-BOM .py with the token wrapped across adjacent "
           "literals is named",
           _provider_lines("bom.py", codecs.BOM_UTF8 + (
               'NAI_KEY = (\n    "%s"\n    "%s"\n)\n'
               % (_NOVELAI[:36], _NOVELAI[36:])).encode("utf-8")),
           ([(2, _NOVELAI_LABEL)], TEXT))
    # PowerShell 5.1 `>>` onto a BOM-less UTF-8 file: UTF-16LE, no BOM. All
    # ASCII, it is valid UTF-8 with a NUL after every character, so it takes
    # the TEXT route and only the view's NUL deletion lets detector 3 read it;
    # `\r NUL \n` is one line ending, not two.
    _header = "# voice notes\r\n".encode("utf-8")
    expect("encoding: BOM-less UTF-16LE appended after a UTF-8 header is "
           "named, on its own line 3",
           _provider_lines("appended.md", _header + (
               "rotated today\r\nNAI_KEY=%s\r\n" % _NOVELAI).encode("utf-16-le")),
           ([(3, _NOVELAI_LABEL)], TEXT))
    # The same append carrying one non-ASCII character is NOT valid UTF-8 and
    # has NUL bytes -- the shape a binary has too -- and its UTF-16 ASCII run
    # is what keeps it from being skipped as one.
    expect("encoding: BOM-less UTF-16LE with a non-ASCII character is read as "
           "bytes and named",
           _provider_lines("appended-accent.md", _header + (
               "clé tournée\r\nNAI_KEY=%s\r\n"
               % _NOVELAI).encode("utf-16-le")),
           ([(3, _NOVELAI_LABEL)], BYTES))
    # A legacy codepage. 0x92 is a curly apostrophe and 0x85 an ellipsis in
    # cp1252; to latin-1 0x85 is U+0085, which `str.splitlines` calls a line
    # break, so the token on line 2 was placed on line 3.
    expect("encoding: a cp1252 .md with a curly apostrophe and an ellipsis is "
           "read as bytes and names the token on line 2",
           _provider_lines("cp1252.md", ("Tom’s voice key…\r\n"
                                         "NAI_KEY=%s\r\n"
                                         % _NOVELAI).encode("cp1252")),
           ([(2, _NOVELAI_LABEL)], BYTES))
    # Line folding runs on the BYTES route too. A CRLF file cannot show it --
    # split on `\n` alone, CRLF still counts right -- so this one ends its lines
    # with a bare CR, as a classic Mac editor does.
    expect("encoding: a bare-CR cp1252 file names the token on line 3",
           _provider_lines("classic-cr.md", b"Tom\x92s voice key\rrotated\r"
                           b"NAI_KEY=" + _NOVELAI.encode("ascii") + b"\r"),
           ([(3, _NOVELAI_LABEL)], BYTES))
    # latin-1, not cp1252: cp1252 leaves 0x81 0x8D 0x8F 0x90 0x9D UNDEFINED, and
    # 0x90 is the low byte of an arrow in UTF-16LE. Decoded as cp1252 they
    # raise, and one such file ends the whole sweep.
    expect("encoding: a non-UTF-8 file holding the five bytes cp1252 leaves "
           "undefined is read, not raised on",
           _provider_lines("undefined.md", b"voice key \x81\x8d\x8f\x90\x9d\r\n"
                           b"NAI_KEY=" + _NOVELAI.encode("ascii") + b"\r\n"),
           ([(2, _NOVELAI_LABEL)], BYTES))
    # ...and latin-1, not UTF-8 with `replace`: a pasted cp1252 document puts a
    # NO-BREAK SPACE (0xA0) after `Bearer`. latin-1 keeps it as U+00A0, which
    # `\s` matches; `replace` turns it into U+FFFD, which it does not.
    _hits, _how = scan_file(_written("pasted.md", b"curl -H \"Authorization: Bearer\xa0"
                                     + _SEED.encode("ascii") + b"\" https://api/x\r\n"),
                            "pasted.md")
    expect("encoding: a cp1252 no-break space after Bearer is still whitespace",
           ([h.why for h in _hits], _how), (["http authorization value"], BYTES))
    # DETECTOR 3 ALONE on the BYTES route. The TEXT route names both lines of
    # this file at once -- a credential-shaped binding and a generated key --
    # and a name or an entropy reading of a latin-1 GUESS is a guess.
    _hits, _how = scan_file(_written("legacy.env", (
        b"# Tom\x92s settings\r\npassword=" + _QUERY_SHORT.encode("ascii")
        + b"\r\nseed: " + _SEED.encode("ascii") + b"\r\n")), "legacy.env")
    expect("encoding: a cp1252 .env gets detector 3 only -- no credential-shaped "
           "name and no high-entropy finding",
           ([str(h) for h in _hits], _how), ([], BYTES))
    # NULs are deleted BEFORE escapes are spaced. PowerShell 5.1 `>>` appending
    # a JSON line: its escaped newline is backslash NUL n NUL, an escape only
    # once the NULs are gone -- substituted first, the `n` is left before `pst-`.
    expect("encoding: an escaped newline INSIDE NUL-interleaved UTF-16LE is "
           "named on line 2",
           _provider_lines("appended.jsonl", b'{"role": "system"}\r\n' + (
               '{"content": "my key:\\n%s"}\r\n' % _NOVELAI).encode("utf-16-le")),
           ([(2, _NOVELAI_LABEL)], TEXT))
    # THE UTF-16 RUN FLOOR, from both sides. 32 sits between the longest run in
    # the tracked binaries (6) and the shortest line worth reading; a novelai
    # token alone is 68, so this floor matters for what ELSE is in the file. A
    # UTF-8 .env carrying the token in its own 8-bit text, with an accented
    # line `>>` appended, has a run of EXACTLY 32 -- tab, CR and LF counted --
    # and must be read; a WAV whose UTF-16 device name is 31 is still binary.
    expect("encoding: a token in 8-bit text beside a UTF-16LE run of exactly "
           "32 is read as bytes and named",
           _provider_lines("deploy.env", b"NAI_KEY=" + _NOVELAI.encode("ascii")
                           + b"\r\n" + ("caf\xe9\tmodified by deploy.ps1 at 9am"
                                        "\r\n\xe9").encode("utf-16-le")),
           ([(1, _NOVELAI_LABEL)], BYTES))
    expect("encoding: a WAV whose longest UTF-16 ASCII run is 31 is still "
           "skipped as binary",
           scan_file(_written("chime.wav", b"RIFF\x24\x08\x00\x00WAVEfmt "
                              b"\x10\x00\x00\x00"
                              + "Microsoft Sound Mapper - Output".encode("utf-16-le")
                              + b"\xff\xfe\x81\x00"), "chime.wav"),
           ([], None))

    # TRACKED PATHS. Decoded from git's bytes as UTF-8, directly and then end
    # to end through a throwaway repository. `ā` is C4 81 in UTF-8, and
    # 0x81 is the byte cp1252 does not define -- the one that crashed the
    # reader thread.
    _odd_name = "notes-āé.md"
    expect("paths: git -z bytes holding a UTF-8 path decode to that path",
           split_ls_files(b"a.md\0" + _odd_name.encode("utf-8") + b"\0")
           == ["a.md", _odd_name], True)
    # ...and a path that is NOT UTF-8 raises, naming nothing silently. Decoded
    # with `replace` or `surrogateescape` it would name no file on disk and be
    # skipped as unopenable -- a tracked file nobody swept.
    _latin_path = b"a.md\0caf\xe9.md\0"
    try:
        _split = f"returned {split_ls_files(_latin_path)!r}"
    except UnicodeDecodeError:
        _split = "raised UnicodeDecodeError"
    expect("paths: git -z bytes holding a path that is not UTF-8 RAISE",
           _split, "raised UnicodeDecodeError")
    if shutil.which("git") is None:                          # pragma: no cover
        print("  SKIP git is not installed -- the throwaway repository was not built")
    else:
        _repo = os.path.join(_scratch, "repo")
        os.makedirs(_repo)
        with open(os.path.join(_repo, _odd_name), "wb") as _handle:
            _handle.write(("voice\nNAI_KEY=%s\n" % _NOVELAI).encode("utf-8"))
        try:
            for _args in (["init", "-q"], ["add", "--", _odd_name]):
                subprocess.run(["git", *_args], cwd=_repo, capture_output=True,
                               timeout=60, check=True)
            _listed = tracked_files(_repo)
        except Exception as exc:
            _listed = [f"raised {type(exc).__name__}"]
        expect("paths: a tracked path carrying U+0101 and U+00E9 is listed "
               "exactly", _listed == [_odd_name], True)
        # A git that RUNS and fails must not read as an empty, clean tree. A
        # `.git` FILE pointing nowhere fails the same way whatever repository
        # the scratch directory happens to sit inside.
        _broken = os.path.join(_scratch, "broken")
        os.makedirs(_broken)
        with open(os.path.join(_broken, ".git"), "w", encoding="ascii") as _handle:
            _handle.write("gitdir: nowhere-at-all\n")
        try:
            _answer = f"returned {tracked_files(_broken)!r}"
        except RuntimeError:
            _answer = "raised RuntimeError"
        expect("paths: a git that runs and fails RAISES rather than answering",
               _answer, "raised RuntimeError")
        # The SWEEP step 4 runs, over that same broken repository: its verdict,
        # the list step 4 demands be empty, carries the failure.
        _broken_sweep = sweep(_broken)
        expect("paths: a sweep over a git that fails is RED, never a clean tree",
               [line.startswith("git ls-files failed:")
                for line in _broken_sweep["verdict"]], [True])
        expect("paths: ...and a sweep over the working one names the token",
               [(h.line, h.why) for h in sweep(_repo)["findings"]],
               [(2, _NOVELAI_LABEL)])
        expect("paths: ...and the file behind it is read and names the token",
               [_provider_lines_at(os.path.join(_repo, p), p)
                for p in (_listed or [])],
               [([(2, _NOVELAI_LABEL)], TEXT)])
    # Reading bytes gave up the text-mode `open`'s newline translation, and
    # exactly one reader noticed, measured over every corpus row in CRLF and
    # CR form: `_python_comments` splits on `\n` alone, so in a file that
    # ends its lines with a bare CR every comment is reported on LINE 1.
    _hits, _readable = scan_file(
        _written("classic.py", b"x = 1\r# password = Xk29qLm4Pz\r"), "classic.py")
    expect("encoding: a bare-CR .py keeps its comment on line 2",
           [(h.line, h.why) for h in _hits], [(2, "credential-shaped name")])

print(f"  ..   positive corpus       : "
      f"{len(MUST_FIRE) + 1 + len(TEXT_MUST_FIRE) + len(PROVIDER_MUST_NAME)} "
      f"shapes, all caught ({len(MUST_FIRE) + 1} python, "
      f"{len(TEXT_MUST_FIRE)} text, {len(PROVIDER_MUST_NAME)} named by provider)")
print(f"  ..   negative corpus       : "
      f"{len(MUST_NOT_FIRE) + len(TEXT_MUST_NOT_FIRE)} shapes, all silent "
      f"({len(MUST_NOT_FIRE)} python, {len(TEXT_MUST_NOT_FIRE)} text), plus "
      f"{len(PROVIDER_MUST_NOT_NAME)} not named by provider")

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
started = time.perf_counter()
_tree = sweep()
if _tree is None:                                            # pragma: no cover
    print("  SKIP git is not installed -- the tree was not swept")
else:
    if _tree["error"]:
        print(f"  ..   git ls-files FAILED   : {_tree['error']}")
    print(f"  ..   tracked files swept   : {_tree['swept']} "
          f"({_tree['as_bytes']} not UTF-8, read as bytes for detector 3 only; "
          f"{_tree['skipped']} binary, skipped) "
          f"in {time.perf_counter() - started:.1f}s")
    print(f"  ..   detector 2 hits, tree : "
          f"{sum(1 for h in _tree['findings'] if _rank(h.why) == 2)} "
          f"(a non-zero number here is the cry-wolf failure)")
    print(f"  ..   detector 3 hits, tree : "
          f"{sum(1 for h in _tree['findings'] if _rank(h.why) == 1)} "
          f"(same, and these carry a provider's name)")
    for hit in _tree["findings"]:
        print(f"       HIT {hit}")
    expect("git ls-files answered and no tracked file carries a plaintext "
           "credential", _tree["verdict"], [])

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
