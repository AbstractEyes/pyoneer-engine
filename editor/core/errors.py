"""The editor's exception hierarchy.

Extends the engine's, so the `Pyoneer` prefix still enumerates the whole
error surface across both applications and `except PyoneerError` still
catches everything.

The editor has a failure mode the engine does not: **an untrusted author** --
not malicious, but an AI emitting a plausible-looking command against a
schema it half-remembered. Hence a specific, loud error per failure rather
than a generic ValueError.

    PyoneerError                      (from scripts.core.errors)
    +-- PyoneerEditorError
        +-- PyoneerCommandError       a command could not be run
        |   +-- PyoneerCommandUnknownError
        |   +-- PyoneerCommandArgumentError
        |   +-- PyoneerCommandScopeError
        |   +-- PyoneerCommandApplyError
        +-- PyoneerScopeError         a scope path is malformed or unresolvable
        |   +-- PyoneerScopeSyntaxError
        |   +-- PyoneerScopeMissingError
        +-- PyoneerGenreError         a genre pack is missing or incoherent
        |   +-- PyoneerGenreMissingError
        |   +-- PyoneerRuleViolationError
        +-- PyoneerProjectError       the project on disk is not usable
        |   +-- PyoneerTableMissingError
        |   +-- PyoneerRowMissingError
        +-- PyoneerRequestError       a request bundle or response is malformed
            +-- PyoneerResponseParseError

THE ROLLBACK CONTRACT
---------------------
`PyoneerCommandApplyError` is special: it means a command raised *after*
earlier commands in the same transaction had already been applied. The
stream rolls those back before re-raising, and records on the exception
whether the rollback itself succeeded. A failed rollback is the one state
the editor cannot reason about, so it says so in the message rather than
carrying on.
"""
from __future__ import annotations

from typing import Any

from scripts.core.errors import PyoneerError


class PyoneerEditorError(PyoneerError):
    """Base for every editor error."""


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

class PyoneerCommandError(PyoneerEditorError):
    """A command could not be validated or run."""


class PyoneerCommandUnknownError(PyoneerCommandError, KeyError):
    """No such verb is registered.

    Raised rather than skipped: invented verbs are the signal that whatever
    wrote the response was working from a stale vocabulary.
    """

    def __init__(self, verb: str, known: list[str] | None = None, **context: Any):
        near = _nearest(verb, known or [])
        hint = f"; did you mean {near!r}?" if near else ""
        super().__init__(f"unknown command verb {verb!r}{hint}", **context)
        self.verb = verb


class PyoneerCommandArgumentError(PyoneerCommandError):
    """A command's arguments are missing, unknown, or the wrong type."""


class PyoneerCommandScopeError(PyoneerCommandError):
    """A command was aimed at a scope its verb cannot act on."""


class PyoneerCommandApplyError(PyoneerCommandError):
    """A command raised while being applied.

    `rolled_back` is True when the transaction was restored cleanly. False
    means the project is in a partially-applied state and the caller should
    reload from disk rather than trust what is in memory.
    """

    def __init__(self, message: str, *, rolled_back: bool = True, **context: Any):
        if not rolled_back:
            message += (" -- AND THE ROLLBACK FAILED; in-memory state is"
                        " partially applied, reload the project from disk")
        super().__init__(message, **context)
        self.rolled_back = rolled_back


# --------------------------------------------------------------------------
# Scopes
# --------------------------------------------------------------------------

class PyoneerScopeError(PyoneerEditorError):
    """A scope path is malformed or does not resolve."""


class PyoneerScopeSyntaxError(PyoneerScopeError):
    """A scope string is not `kind:name/kind:name/...`."""


class PyoneerScopeMissingError(PyoneerScopeError, KeyError):
    """A well-formed scope points at something that is not there."""


# --------------------------------------------------------------------------
# Genre packs
# --------------------------------------------------------------------------

class PyoneerGenreError(PyoneerEditorError):
    """A genre pack is missing, malformed, or contradicts the project."""


class PyoneerGenreMissingError(PyoneerGenreError, KeyError):
    """No genre pack by that id."""


class PyoneerRuleViolationError(PyoneerGenreError):
    """A command would break a hard rule the current genre declares.

    Soft rules do not raise -- they surface in the Problems view as
    `RuleViolation` records, because a project is allowed to be
    work-in-progress. Hard rules are the ones whose breach would make the
    game unloadable.
    """


# --------------------------------------------------------------------------
# Project data
# --------------------------------------------------------------------------

class PyoneerProjectError(PyoneerEditorError):
    """The project on disk cannot be used as-is."""


class PyoneerTableMissingError(PyoneerProjectError, KeyError):
    """A data table was addressed by a name the project does not define."""


class PyoneerRowMissingError(PyoneerProjectError, KeyError):
    """A row id was addressed and is not in the table."""


class PyoneerFieldMissingError(PyoneerProjectError, KeyError):
    """A column was addressed and is not in the table's schema."""


# --------------------------------------------------------------------------
# Requests and responses
# --------------------------------------------------------------------------

class PyoneerRequestError(PyoneerEditorError):
    """A request bundle could not be written, or a response could not be read."""


class PyoneerResponseParseError(PyoneerRequestError):
    """A response file is not the agreed format.

    Carries the offending line number, because a 400-command response with
    one bad line should not read as "the response is broken".
    """

    def __init__(self, message: str, *, line: int | None = None, **context: Any):
        if line is not None:
            context["line"] = line
        super().__init__(message, **context)
        self.line = line


# --------------------------------------------------------------------------
# Small helper: nearest-name hint
# --------------------------------------------------------------------------

def _nearest(needle: str, haystack: list[str]) -> str | None:
    """Cheapest useful typo hint: longest shared prefix, then edit distance.

    Deliberately dependency-free and deliberately conservative -- a wrong
    suggestion is worse than none, so it returns None unless the match is
    close.
    """
    if not haystack:
        return None
    best, best_score = None, 0.0
    for candidate in haystack:
        score = _similarity(needle, candidate)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= 0.6 else None


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    # Normalised Levenshtein, iterative two-row.
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1,
                               current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return 1.0 - previous[-1] / max(len(a), len(b))
