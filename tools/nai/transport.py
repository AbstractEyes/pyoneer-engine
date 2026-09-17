"""The socket boundary: the only code that talks HTTP, and the only key reader.

OWNER: implementer A.

RESPONSIBILITY
--------------
A `Transport` moves bytes to and from the two allowlisted endpoints and
nothing else. `UrllibTransport` is the real one (stdlib `urllib.request`);
`RecordingTransport` is the scripted one every network-free check uses.
`read_account` parses the balance read; `unzip_image` pulls the PNG out of a
generation response.

INVARIANTS
----------
* THE KEY EXISTS IN ONE PLACE. `api_key()` is called only inside
  `UrllibTransport`, at send time, and its value goes only into that
  request's Authorization header. Callers never pass, see, log or store it;
  `RecordingTransport` never calls `api_key()`, so no check needs NAI_KEY.
  No exception message, repr or return value built here contains the key or
  the Authorization header. Every exception raised out of a urllib failure
  is raised `from None`, so no chained urllib object rides along with it.
  A response body or header value that ECHOES the key has it replaced by
  "[redacted]" before `UrllibTransport` returns it -- in the raw bytes AND,
  for a JSON body, in its DECODED strings, since a server that escapes one
  character of the key (`\\u0074`) defeats a byte search and `parse_error`
  would decode it straight back.
* A KEY A HEADER CANNOT CARRY IS REFUSED BEFORE ANY REQUEST IS BUILT.
  `api_key` accepts only visible ASCII (after stripping the ends): http.client
  rejects a CR or LF inside a header value with a ValueError whose message IS
  the header value, key included. As a second wall, `_send` turns any
  exception other than TransportError out of `_perform` into a TransportError
  that names only the exception's class.
* ALLOWLIST BEFORE SOCKET. Every `post_json` and `get` -- in every Transport
  implementation, the recording one included -- calls
  `guard.assert_endpoint(method, url)` before doing anything else.
* CALLER HEADERS ARE CHECKED THE SAME WAY BY BOTH TRANSPORTS: a caller header
  named Authorization, Accept or Content-Type (any case) is ValueError in
  `UrllibTransport` AND in `RecordingTransport`, so a network-free check sees
  the same refusal the real send would.
* NO REDIRECTS. `UrllibTransport` refuses to follow any redirect
  (TransportError), because a redirect is a request to a URL nobody
  allowlisted. The Authorization header is also added as an UNREDIRECTED
  header, so even a redirect handler that did follow would not forward it.
* NO RETRIES, NO ACCEPT HEADER. One call is one HTTP request. No `Accept`
  header is sent, so a generation answers with a ZIP. A fixed User-Agent is
  sent in place of urllib's default "Python-urllib/3.x" (DESIGN, unverified:
  CDNs commonly refuse that default).
* HTTP errors are RETURNED as (status, headers, body), not raised; only a
  timeout (TransportTimeout) or a connection-level failure (TransportError)
  raises. `run.run_request` reads the balance afterwards either way.

PUBLIC NAMES
------------
Response, TransportError, TransportTimeout, MissingKey, BadResponse,
AccountReadError, Transport, api_key, UrllibTransport, Call,
RecordingTransport, read_account, unzip_image, parse_error,
fake_subscription_body, fake_zip.
"""
from __future__ import annotations

import copy
import http.client
import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from tools.nai import guard
from tools.nai.model import SUBSCRIPTION_URL, TIMEOUT_S, Account
from tools.nai.request import encode_body, png_header

Response = tuple[int, dict[str, str], bytes]
"""(status, headers with lower-cased names, body bytes)."""

_KEY_VARIABLE = "NAI_KEY"
_KEY_SHAPE = re.compile(r"[\x21-\x7e]+")
"""Visible ASCII, no space: all a Bearer header value can carry intact."""
_USER_AGENT = "pyoneer-tools-nai/1"
_CALLER_MAY_NOT_SET = ("authorization", "accept", "content-type")
_ZIP_MAGIC = b"PK\x03\x04"
_MAX_PNG_BYTES = 64 * 1024 * 1024
_MAX_ERROR_CHARS = 1000
_TEST_HANDLERS: tuple = ()
"""Extra urllib handlers appended to the real opener. EMPTY in production; a
network-free check puts a fake HTTPS handler here so the real redirect and
error machinery runs against scripted responses without opening a socket."""


class TransportError(Exception):
    """The request could not complete at the connection level. Message names
    the URL and the failure class, never headers or the key."""


class TransportTimeout(TransportError):
    """No complete response within the timeout. A charge may still land."""


class MissingKey(RuntimeError):
    """NAI_KEY is absent, blank, or not a bare visible-ASCII token. The
    message names the variable and the kind of problem, never the value."""


class BadResponse(ValueError):
    """A 2xx body that is not the expected ZIP-with-one-PNG shape."""


class AccountReadError(RuntimeError):
    """GET /user/subscription did not yield a usable Account.

    `status` is the HTTP status (None for a parse failure of a 2xx body);
    the message names the missing or mistyped field or the server message.
    """

    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(status, message)
        self.status = status
        self.message = message

    def __str__(self) -> str:
        return f"account read failed (status {self.status}): {self.message}"


class Transport(Protocol):
    """What `run`, `read_account` and the CLI need from HTTP.

    Implementations call `guard.assert_endpoint` first; add authentication
    themselves if they need it; never retry.
    """

    def post_json(self, url: str, body: Mapping[str, object],
                  headers: Mapping[str, str], timeout: float) -> Response:
        """POST `body` (a JSON-ready dict) to `url`; return the response."""
        ...

    def get(self, url: str, headers: Mapping[str, str],
            timeout: float) -> Response:
        """GET `url`; return the response."""
        ...


def api_key() -> str:
    """Return os.environ["NAI_KEY"], stripped.

    Raises MissingKey when the variable is absent or blank, with a message
    that names NAI_KEY and says it is a Windows USER environment variable
    read at process start (so a new shell is needed after setting it). Also
    MissingKey when the stripped value holds anything but visible ASCII (a
    line break or space inside it, a curly quote from a paste): a message
    that names NAI_KEY and the kind of problem, the same for every such
    value. Never echoes any part of a value. Called only by UrllibTransport.
    """
    value = os.environ.get(_KEY_VARIABLE)
    if value is None or not value.strip():
        raise MissingKey(
            f"{_KEY_VARIABLE} is absent or blank. It is a Windows USER "
            f"environment variable, read when a process starts: set it, then "
            f"open a new shell and run the command again.")
    value = value.strip()
    if not _KEY_SHAPE.fullmatch(value):
        raise MissingKey(
            f"{_KEY_VARIABLE} holds a character an HTTP header cannot carry "
            f"(a line break or space inside it, or a non-ASCII character such "
            f"as a curly quote from a paste). Set it again as the bare token, "
            f"then open a new shell and run the command again.")
    return value


def _check_caller_headers(headers: Mapping[str, str]) -> None:
    """ValueError when a caller header is one the transport owns or forbids.
    Shared by both transports so a scripted check refuses what a send would."""
    for name in headers:
        if not isinstance(name, str) or name.lower() in _CALLER_MAY_NOT_SET:
            raise ValueError(
                f"caller headers may not set {name!r}: the transport sets "
                f"Authorization and Content-Type itself and sends no Accept")


def _lower_headers(message: object) -> dict[str, str]:
    if message is None:
        return {}
    return {str(k).lower(): str(v) for k, v in message.items()}


class _RedirectRefused(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Replaces urllib's default redirect handler: every redirect raises."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            fp.read()
            fp.close()
        except Exception:  # the redirect is refused whatever the body does
            pass
        raise _RedirectRefused(code)


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirectHandler(), *_TEST_HANDLERS)


def _perform(request: urllib.request.Request, method: str, url: str,
             timeout: float) -> Response:
    """Open `request` once; map every failure onto the transport's errors."""
    where = f"{method} {url}"
    try:
        with _build_opener().open(request, timeout=timeout) as response:
            status = response.getcode()
            headers = _lower_headers(response.headers)
            body = response.read()
        return int(status), headers, body
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read() if exc.fp is not None else b""
        except TimeoutError:
            raise TransportTimeout(
                f"{where}: timed out reading the HTTP {exc.code} body") from None
        except (OSError, http.client.HTTPException) as inner:
            raise TransportError(
                f"{where}: HTTP {exc.code} body unreadable "
                f"({type(inner).__name__})") from None
        finally:
            exc.close()
        return int(exc.code), _lower_headers(exc.headers), body
    except _RedirectRefused as exc:
        raise TransportError(
            f"{where}: refused to follow an HTTP {exc.code} redirect") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise TransportTimeout(
                f"{where}: timed out after {timeout:g} s") from None
        raise TransportError(
            f"{where}: connection failed ({type(exc.reason).__name__}: "
            f"{str(exc.reason)[:200]})") from None
    except TimeoutError:
        raise TransportTimeout(f"{where}: timed out after {timeout:g} s") from None
    except (OSError, http.client.HTTPException) as exc:
        raise TransportError(
            f"{where}: connection failed ({type(exc).__name__})") from None


_REDACTED = "[redacted]"


def _redact_decoded(body: bytes, key: str) -> bytes:
    """A JSON body whose DECODED strings hold `key` comes back re-serialised
    with it redacted; any other body comes back unchanged."""
    if body.lstrip()[:1] not in (b"{", b"["):
        return body
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return body
    found = []

    def clean(value: object) -> object:
        if isinstance(value, str):
            if key in value:
                found.append(True)
                return value.replace(key, _REDACTED)
            return value
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {clean(name): clean(item) for name, item in value.items()}
        return value

    cleaned = clean(data)
    if not found:
        return body
    return json.dumps(cleaned, ensure_ascii=True).encode("ascii")


def _send(method: str, url: str, data: bytes | None,
          headers: Mapping[str, str], timeout: float) -> Response:
    request = urllib.request.Request(url, data=data, method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", _USER_AGENT)
    # The key is read here, at send time, and goes nowhere but this header.
    key = api_key()
    request.add_unredirected_header("Authorization", "Bearer " + key)
    try:
        status, response_headers, body = _perform(request, method, url, timeout)
    except TransportError as exc:
        if key in str(exc):
            raise type(exc)(str(exc).replace(key, _REDACTED)) from None
        raise
    except Exception as exc:
        # http.client's header validation, for one, raises a ValueError whose
        # message is the header value itself. Name the class, never the text.
        raise TransportError(
            f"{method} {url}: the request could not be built or read "
            f"({type(exc).__name__})") from None
    finally:
        request.unredirected_hdrs.clear()
    # A server that echoes the key back (an error message quoting the header,
    # say) must not hand it to a caller that logs response text.
    raw_key = key.encode("utf-8")
    if raw_key in body:
        body = body.replace(raw_key, _REDACTED.encode("ascii"))
    body = _redact_decoded(body, key)
    response_headers = {name: value.replace(key, _REDACTED)
                        for name, value in response_headers.items()}
    return status, response_headers, body


class UrllibTransport:
    """The real transport: urllib.request, no redirects, no retries.

    post_json sends Authorization "Bearer <key>" from api_key(),
    Content-Type application/json, the caller's headers (x-correlation-id),
    and request.encode_body(body). ValueError if the caller's headers
    already contain an Authorization header (any case). get sends the same
    Authorization and the caller's headers. An HTTPError is returned as a
    Response; socket timeout -> TransportTimeout; URLError, a refused
    redirect or any OSError -> TransportError. The caller's headers may not
    carry Accept or Content-Type either (ValueError), and a fixed User-Agent
    replaces urllib's default.
    """

    def __repr__(self) -> str:
        return "UrllibTransport()"

    def post_json(self, url: str, body: Mapping[str, object],
                  headers: Mapping[str, str], timeout: float) -> Response:
        guard.assert_endpoint("POST", url)
        _check_caller_headers(headers)
        return _send("POST", url, encode_body(body), headers, timeout)

    def get(self, url: str, headers: Mapping[str, str],
            timeout: float) -> Response:
        guard.assert_endpoint("GET", url)
        _check_caller_headers(headers)
        return _send("GET", url, None, headers, timeout)


@dataclass(frozen=True)
class Call:
    """One request a RecordingTransport received. `body` is None for GET."""
    method: str
    url: str
    headers: dict[str, str]
    body: dict | None


@dataclass
class RecordingTransport:
    """A scripted transport for network-free checks. Never opens a socket.

    `responses` is consumed in order, one entry per call (GET or POST): a
    Response tuple is returned; a BaseException instance is raised (e.g.
    TransportTimeout()). A call with no scripted entry left raises
    RuntimeError naming the method and URL -- it never invents a response.
    Every call is appended to `calls` AFTER guard.assert_endpoint passes, so
    a refused endpoint leaves `calls` unchanged. Never calls api_key().
    Caller headers are checked exactly as UrllibTransport checks them, before
    the call is recorded. A POST body is recorded as a deep copy.
    """
    responses: list[Response | BaseException]
    calls: list[Call] = field(default_factory=list)

    def _answer(self, method: str, url: str) -> Response:
        if not self.responses:
            raise RuntimeError(
                f"RecordingTransport has no scripted response left for "
                f"{method} {url}")
        entry = self.responses.pop(0)
        if isinstance(entry, BaseException):
            raise entry
        return entry

    def post_json(self, url: str, body: Mapping[str, object],
                  headers: Mapping[str, str], timeout: float) -> Response:
        guard.assert_endpoint("POST", url)
        _check_caller_headers(headers)
        self.calls.append(Call("POST", url, dict(headers),
                               copy.deepcopy(dict(body))))
        return self._answer("POST", url)

    def get(self, url: str, headers: Mapping[str, str],
            timeout: float) -> Response:
        guard.assert_endpoint("GET", url)
        _check_caller_headers(headers)
        self.calls.append(Call("GET", url, dict(headers), None))
        return self._answer("GET", url)

    @property
    def posts(self) -> list[Call]:
        """Only the POST calls, in order."""
        return [call for call in self.calls if call.method == "POST"]


def _account_field(data: Mapping[str, object], path: tuple[str, ...],
                   kind: type) -> object:
    cur: object = data
    for depth, part in enumerate(path):
        if not isinstance(cur, Mapping) or part not in cur:
            raise AccountReadError(
                None, f"subscription field {'.'.join(path[:depth + 1])} is missing")
        cur = cur[part]
    ok = isinstance(cur, kind) and not (kind is int and isinstance(cur, bool))
    if not ok:
        raise AccountReadError(
            None, f"subscription field {'.'.join(path)} is "
                  f"{type(cur).__name__}, not {kind.__name__}")
    return cur


def read_account(transport: Transport) -> Account:
    """GET model.SUBSCRIPTION_URL once and parse it into an Account (2.3).

    Timeout model.TIMEOUT_S, no extra headers. Non-2xx -> AccountReadError
    with the status and parse_error(body). Parsing is lenient about EXTRA
    fields and strict about the ones used: `tier` int (not bool), `active`
    bool, `trainingStepsLeft.fixedTrainingStepsLeft` int,
    `trainingStepsLeft.purchasedTrainingSteps` int -- any missing or
    mistyped -> AccountReadError naming the field. `isGracePeriod` absent ->
    grace None; present -> must be bool. `usage`, when present, is kept as
    compact JSON in usage_json. Timeouts and TransportError propagate.
    """
    status, _headers, body = transport.get(SUBSCRIPTION_URL, {}, TIMEOUT_S)
    if not 200 <= status < 300:
        raise AccountReadError(status, parse_error(body))
    try:
        data = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise AccountReadError(None, "subscription body is not JSON") from None
    if not isinstance(data, dict):
        raise AccountReadError(None, "subscription body is not a JSON object")
    tier = _account_field(data, ("tier",), int)
    active = _account_field(data, ("active",), bool)
    fixed = _account_field(
        data, ("trainingStepsLeft", "fixedTrainingStepsLeft"), int)
    purchased = _account_field(
        data, ("trainingStepsLeft", "purchasedTrainingSteps"), int)
    grace = None
    if "isGracePeriod" in data:
        grace = _account_field(data, ("isGracePeriod",), bool)
    usage_json = None
    if "usage" in data:
        usage_json = json.dumps(data["usage"], sort_keys=True,
                                separators=(",", ":"), ensure_ascii=True)
    return Account(tier=tier, active=active, grace=grace, fixed=fixed,
                   purchased=purchased, usage_json=usage_json)


def unzip_image(body_bytes: bytes, width: int, height: int) -> bytes:
    """The PNG inside a 2xx generation response (brief 1.4).

    BadResponse unless: body starts with b"PK\\x03\\x04"; it opens with
    zipfile; the FIRST entry in archive order whose name starts with
    "image_" and ends with ".png" exists (message lists the names otherwise);
    and request.png_header of that entry reports (width, height). Content-Type
    is never consulted. An entry larger than 64 MiB is BadResponse too. NO
    OTHER EXCEPTION LEAVES THIS FUNCTION: a corrupt deflate stream raises
    zlib.error inside zipfile, which is none of zipfile's own classes, so
    every Exception out of reading the archive becomes BadResponse.
    """
    data = bytes(body_bytes)
    if not data.startswith(_ZIP_MAGIC):
        raise BadResponse(
            f"response body is not a ZIP (starts {data[:8]!r}, "
            f"{len(data)} bytes)")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            chosen = next((info for info in infos
                           if info.filename.startswith("image_")
                           and info.filename.endswith(".png")), None)
            if chosen is None:
                raise BadResponse(
                    f"ZIP has no image_*.png entry; names: "
                    f"{[info.filename for info in infos]}")
            if chosen.file_size > _MAX_PNG_BYTES:
                raise BadResponse(
                    f"{chosen.filename} is {chosen.file_size} bytes; refusing "
                    f"more than {_MAX_PNG_BYTES}")
            png = archive.read(chosen)
    except BadResponse:
        raise
    except Exception as exc:  # zipfile, zlib.error, OSError, EOFError, ...
        raise BadResponse(
            f"response ZIP cannot be read ({type(exc).__name__}: {exc})") from None
    try:
        got_w, got_h, _colour = png_header(png)
    except ValueError as exc:
        raise BadResponse(f"{chosen.filename}: {exc}") from None
    if (got_w, got_h) != (width, height):
        raise BadResponse(
            f"{chosen.filename} is {got_w}x{got_h}; the request was "
            f"{width}x{height}")
    return png


def _one_line(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", text).strip()


def parse_error(body_bytes: bytes) -> str:
    """A one-line error message from a non-2xx body. Never raises.

    JSON {"statusCode", "message", "details"?} -> message (plus details when
    present); anything else -> the first 200 characters decoded as UTF-8
    with replacement, newlines collapsed; empty body -> "". A JSON message is
    cut at 1000 characters so it always fits a ledger string.
    """
    try:
        if not body_bytes:
            return ""
        text = bytes(body_bytes).decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict) and "message" in data:
            message = _one_line(str(data["message"]))
            details = data.get("details")
            if details not in (None, "", [], {}):
                if not isinstance(details, str):
                    details = json.dumps(details, sort_keys=True,
                                         ensure_ascii=True)
                message = f"{message} ({_one_line(details)})"
            return message[:_MAX_ERROR_CHARS]
        return _one_line(text[:200])
    except Exception:  # the contract: never raises
        return "<unreadable error body>"


def fake_subscription_body(*, tier: int = 3, active: bool = True,
                           fixed: int = 1000, purchased: int = 0,
                           grace: bool | None = None) -> bytes:
    """A JSON subscription body for RecordingTransport scripts.

    Shape: {"tier", "active", "trainingStepsLeft": {"fixedTrainingStepsLeft",
    "purchasedTrainingSteps"}, "perks": {}, "usage": {}} plus
    "isGracePeriod" only when grace is not None. For checks only.
    """
    data: dict = {
        "tier": tier,
        "active": active,
        "trainingStepsLeft": {"fixedTrainingStepsLeft": fixed,
                              "purchasedTrainingSteps": purchased},
        "perks": {},
        "usage": {},
    }
    if grace is not None:
        data["isGracePeriod"] = grace
    return json.dumps(data).encode("ascii")


def fake_zip(png_bytes: bytes, *, names: Sequence[str] = ("image_0.png",)) -> bytes:
    """A generation-shaped ZIP holding `png_bytes` under each of `names`.

    For checks only; lets a check put a decoy entry first.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, png_bytes)
    return buffer.getvalue()
