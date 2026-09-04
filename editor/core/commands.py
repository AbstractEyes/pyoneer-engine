"""The command stream -- the editor's only way to change anything.

THE ONE IDEA
------------
A human clicking a tile and an AI answering a request must go through the
*same* door. Not similar doors. The same one.

    click on the canvas  --> Command("map.tile.set", scope, {...}) --+
    response.jsonl line  --> Command("map.tile.set", scope, {...}) --+--> apply

Everything the editor is supposed to be falls out of that:

  * **Undo is free and honest.** Applying a command returns its *inverse*
    command, not a snapshot. The undo stack is a list of commands, which
    means it is serialisable, inspectable, and diffable. You can read what
    the AI did as a list of sentences.
  * **Review is possible.** The command log is the review surface. "It
    changed 41 tiles and added 3 rows to actors" is a fact, not a diff you
    have to interpret.
  * **The instruction set cannot go stale.** `describe_all()` generates the
    vocabulary documentation that goes into every request bundle, straight
    from the registry that executes it. A verb that is not implemented
    cannot appear in the docs, and an implemented verb cannot be missing
    from them.
  * **Failure is atomic.** A response is applied as one transaction. If
    command 7 of 12 raises, the first 6 are rolled back by applying their
    inverses in reverse.

PARAMETERS ARE CHECKED, NOT COERCED
-----------------------------------
`gid: "5"` from a JSON response is a type error, not a 5. Coercion is how a
plausible-wrong value gets in, and this repo has a documented history of
exactly that (`depth` arriving as the string `'50'` from pytmx). The one
exception is int-where-float-is-wanted, which is safe and constant.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Sequence

from editor.core.errors import (
    PyoneerCommandApplyError,
    PyoneerCommandArgumentError,
    PyoneerCommandScopeError,
    PyoneerCommandUnknownError,
)
from editor.core.scope import Scope

# --------------------------------------------------------------------------
# Parameter specs
# --------------------------------------------------------------------------

_TYPE_NAMES: dict[type, str] = {
    int: "int", float: "float", str: "str", bool: "bool",
    list: "list", dict: "dict",
    # `object` means "any JSON scalar" -- used where the value's type is the
    # user's business, as in a table cell or a tmx custom property. It skips
    # the bool guard below, because there `True` is a real value and not the
    # accidental-int mistake the guard exists to catch.
    object: "any",
}


@dataclass(frozen=True)
class Param:
    """One argument of a verb.

    `doc` is not decoration -- it is copied verbatim into the generated
    COMMANDS.md that conditions the responding model, so it is the actual
    interface description.
    """

    name: str
    type: type
    doc: str
    required: bool = True
    default: Any = None
    choices: tuple[Any, ...] | None = None

    @property
    def type_name(self) -> str:
        return _TYPE_NAMES.get(self.type, self.type.__name__)

    def check(self, value: Any, *, verb: str) -> Any:
        if self.type is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        # bool is a subclass of int; an int param must not silently take True.
        if self.type not in (bool, object) and isinstance(value, bool):
            raise PyoneerCommandArgumentError(
                f"{verb}: argument {self.name!r} wants {self.type_name}, got bool",
                verb=verb, argument=self.name)
        if not isinstance(value, self.type):
            raise PyoneerCommandArgumentError(
                f"{verb}: argument {self.name!r} wants {self.type_name}, "
                f"got {type(value).__name__} ({value!r})",
                verb=verb, argument=self.name)
        if self.choices is not None and value not in self.choices:
            raise PyoneerCommandArgumentError(
                f"{verb}: argument {self.name!r} must be one of "
                f"{list(self.choices)}, got {value!r}",
                verb=verb, argument=self.name)
        return value


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Command:
    """A single, serialisable, reversible change."""

    verb: str
    scope: Scope
    args: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.args:
            return f"{self.verb} @ {self.scope}"
        shown = ", ".join(f"{k}={_short(v)}" for k, v in self.args.items())
        return f"{self.verb} @ {self.scope} ({shown})"

    def to_json(self) -> dict[str, Any]:
        return {"verb": self.verb, "scope": str(self.scope), "args": self.args}

    @classmethod
    def from_json(cls, obj: Any) -> "Command":
        if not isinstance(obj, dict):
            raise PyoneerCommandArgumentError(
                f"a command must be a JSON object, got {type(obj).__name__}")
        missing = [k for k in ("verb", "scope") if k not in obj]
        if missing:
            raise PyoneerCommandArgumentError(
                f"a command needs {missing}", got=sorted(obj))
        args = obj.get("args", {})
        if not isinstance(args, dict):
            raise PyoneerCommandArgumentError(
                f"'args' must be an object, got {type(args).__name__}",
                verb=obj["verb"])
        return cls(str(obj["verb"]), Scope.parse(str(obj["scope"])), dict(args))


def _short(value: Any, limit: int = 40) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------

# An apply function takes (project, command) and returns the command that
# undoes it. Returning None means "this changed nothing", which is legal and
# makes the transaction skip it on rollback.
ApplyFn = Callable[[Any, Command], "Command | None"]


@dataclass(frozen=True)
class Verb:
    name: str
    summary: str
    scopes: tuple[str, ...]
    params: tuple[Param, ...]
    apply: ApplyFn
    example: str | None = None
    destructive: bool = False

    def param(self, name: str) -> Param | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    def validate(self, command: Command) -> dict[str, Any]:
        """Check scope and arguments; return the filled argument dict.

        Defaults are materialised here, so an apply function never has to
        write `args.get("x", 0)` and can never disagree with the documented
        default.
        """
        if not any(command.scope.matches(pattern) for pattern in self.scopes):
            raise PyoneerCommandScopeError(
                f"{self.name} cannot act on {command.scope}; "
                f"it accepts {list(self.scopes)}",
                verb=self.name, scope=str(command.scope))

        known = {p.name for p in self.params}
        unknown = sorted(set(command.args) - known)
        if unknown:
            raise PyoneerCommandArgumentError(
                f"{self.name}: unknown argument(s) {unknown}",
                verb=self.name, accepts=sorted(known))

        filled: dict[str, Any] = {}
        for spec in self.params:
            if spec.name in command.args:
                filled[spec.name] = spec.check(command.args[spec.name], verb=self.name)
            elif spec.required:
                raise PyoneerCommandArgumentError(
                    f"{self.name}: missing required argument {spec.name!r}"
                    f" ({spec.type_name}) -- {spec.doc}",
                    verb=self.name, missing=spec.name)
            else:
                filled[spec.name] = spec.default
        return filled


_REGISTRY: dict[str, Verb] = {}


def command(name: str, *, summary: str, scopes: Sequence[str],
            params: Sequence[Param] = (), example: str | None = None,
            destructive: bool = False):
    """Register a verb.

        @command("map.tile.set", summary="Set one tile.",
                 scopes=["map:*/layer:*"],
                 params=[Param("x", int, "column"), ...])
        def _set_tile(project, cmd): ...
    """
    def decorate(fn: ApplyFn) -> ApplyFn:
        if name in _REGISTRY:
            raise PyoneerCommandArgumentError(
                f"verb {name!r} is already registered", verb=name)
        _REGISTRY[name] = Verb(name, summary, tuple(scopes), tuple(params),
                               fn, example, destructive)
        return fn
    return decorate


def verb(name: str) -> Verb:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise PyoneerCommandUnknownError(name, sorted(_REGISTRY)) from None


def all_verbs() -> list[Verb]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def verbs_accepting(scopes: Sequence[Scope]) -> list[Verb]:
    """Every verb that would let at least one of `scopes` through.

    THE SAME TEST `Verb.validate` RUNS, deliberately reusing
    `Scope.matches` against the verb's own `scopes` patterns rather than
    re-deriving "what is a layer verb" from the name. A filter that agreed
    with the validator by coincidence would ship a vocabulary whose verbs
    are refused on arrival -- the exact failure a generated interface doc
    exists to make impossible.

    An empty `scopes` selects NOTHING, not everything: this answers "which
    verbs accept these addresses", and the answer for no addresses is none.
    Callers that mean "the whole registry" call `all_verbs`.
    """
    return [spec for spec in all_verbs()
            if any(scope.matches(pattern)
                   for scope in scopes for pattern in spec.scopes)]


def verb_names() -> list[str]:
    return sorted(_REGISTRY)


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

@dataclass
class Transaction:
    """A group of commands applied together, undone together."""

    label: str
    commands: list[Command] = field(default_factory=list)
    inverses: list[Command] = field(default_factory=list)
    source: str = "editor"          # "editor" | "response:<id>" | "script"

    def __str__(self) -> str:
        return f"{self.label} ({len(self.commands)} command"           \
               f"{'' if len(self.commands) == 1 else 's'}, {self.source})"

    def summary_lines(self) -> list[str]:
        return [f"  {c}" for c in self.commands]


class CommandStream:
    """Applies commands to a project and remembers how to take them back.

    Not thread-safe and not meant to be; the GUI drives it from the main
    thread and the response watcher marshals onto that thread before
    applying.
    """

    def __init__(self, project: Any):
        self.project = project
        self.done: list[Transaction] = []
        self.undone: list[Transaction] = []
        self.listeners: list[Callable[[Transaction, str], None]] = []

    # -- notification ------------------------------------------------------

    def subscribe(self, fn: Callable[[Transaction, str], None]) -> None:
        """`fn(transaction, action)` where action is apply|undo|redo."""
        self.listeners.append(fn)

    def __announce(self, transaction: Transaction, action: str) -> None:
        for listener in self.listeners:
            listener(transaction, action)

    # -- applying ----------------------------------------------------------

    def apply(self, commands: Command | Iterable[Command], *,
              label: str | None = None, source: str = "editor") -> Transaction:
        """Apply one or more commands atomically.

        On failure every command already applied in this call is reversed,
        and `PyoneerCommandApplyError` is raised carrying which command
        failed and whether the rollback held.
        """
        batch = [commands] if isinstance(commands, Command) else list(commands)
        if not batch:
            raise PyoneerCommandArgumentError("nothing to apply (empty batch)")

        transaction = Transaction(
            label=label or _auto_label(batch), source=source)

        for index, cmd in enumerate(batch):
            spec = verb(cmd.verb)
            try:
                filled = spec.validate(cmd)
                inverse = spec.apply(self.project, replace(cmd, args=filled))
            except Exception as exc:
                rolled = self.__rollback(transaction)
                raise self.__wrap(exc, cmd, index, len(batch), rolled) from exc
            transaction.commands.append(cmd)
            transaction.inverses.append(inverse if inverse is not None else _NOOP)

        self.done.append(transaction)
        self.undone.clear()
        self.__announce(transaction, "apply")
        return transaction

    def __wrap(self, exc: Exception, cmd: Command, index: int, total: int,
               rolled: bool) -> PyoneerCommandApplyError:
        detail = exc.message if hasattr(exc, "message") else str(exc)
        error = PyoneerCommandApplyError(
            f"command {index + 1} of {total} failed: {cmd.verb} -- {detail}",
            rolled_back=rolled,
            verb=cmd.verb, scope=str(cmd.scope), args=cmd.args,
            cause=type(exc).__name__)
        # Carry the original's own context trail if it had one.
        for frame in getattr(exc, "frames", []):
            error.push_frame(**frame)
        return error

    def __rollback(self, transaction: Transaction) -> bool:
        for inverse in reversed(transaction.inverses):
            if inverse is _NOOP:
                continue
            try:
                spec = verb(inverse.verb)
                spec.apply(self.project, replace(inverse, args=spec.validate(inverse)))
            except Exception:
                return False
        return True

    # -- undo / redo -------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self.done)

    @property
    def can_redo(self) -> bool:
        return bool(self.undone)

    def undo(self) -> Transaction | None:
        if not self.done:
            return None
        transaction = self.done.pop()
        for inverse in reversed(transaction.inverses):
            if inverse is _NOOP:
                continue
            spec = verb(inverse.verb)
            spec.apply(self.project, replace(inverse, args=spec.validate(inverse)))
        self.undone.append(transaction)
        self.__announce(transaction, "undo")
        return transaction

    def redo(self) -> Transaction | None:
        if not self.undone:
            return None
        transaction = self.undone.pop()
        rebuilt = Transaction(transaction.label, source=transaction.source)
        for cmd in transaction.commands:
            spec = verb(cmd.verb)
            inverse = spec.apply(self.project, replace(cmd, args=spec.validate(cmd)))
            rebuilt.commands.append(cmd)
            rebuilt.inverses.append(inverse if inverse is not None else _NOOP)
        self.done.append(rebuilt)
        self.__announce(rebuilt, "redo")
        return rebuilt

    # -- reading -----------------------------------------------------------

    def history(self) -> list[Transaction]:
        return list(self.done)

    def to_jsonl(self) -> str:
        """Every applied command, in order, as a replayable script."""
        lines = []
        for transaction in self.done:
            for cmd in transaction.commands:
                lines.append(json.dumps(cmd.to_json(), sort_keys=True))
        return "\n".join(lines)


# A sentinel inverse for commands that changed nothing.
_NOOP = Command("noop", Scope.of("project"))


@command("noop", summary="Does nothing. The inverse of a command that changed nothing.",  # #TAG:noop
         scopes=["project"])
def _noop(project: Any, cmd: Command) -> None:
    return None


def _auto_label(batch: list[Command]) -> str:
    if len(batch) == 1:
        return batch[0].verb
    verbs = {c.verb for c in batch}
    if len(verbs) == 1:
        return f"{len(batch)}x {next(iter(verbs))}"
    return f"{len(batch)} commands"


# --------------------------------------------------------------------------
# Generated documentation
# --------------------------------------------------------------------------

def describe_all(*, title: str = "Command vocabulary",
                 scopes: Sequence[Scope] = (), sample: str = "") -> str:
    """Render the registry as markdown -- all of it, or one scope's slice.

    This is what goes into every request bundle. It is generated from the
    registry rather than written by hand precisely because a hand-written
    interface doc is the thing most likely to drift out from under an AI
    that trusts it.

    `scopes` narrows the output to the verbs those addresses accept, through
    `verbs_accepting` -- the same `Scope.matches` test `Verb.validate` runs.
    A request about one tile layer needs 8 of the 37 verbs, and shipping the
    other 29 costs about 5,000 tokens of vocabulary the responder cannot
    legally use on that address.

    `sample` replaces the worked line at the top. IT EXISTS BECAUSE THE
    CANNED ONE WAS A LIE IN A SCOPED BUNDLE: `map.tile.set @
    map:test/layer:Floor` was printed into every COMMANDS.md ever cut,
    including one cut for `script:toll` -- where `BundleContract` refuses
    that exact line, so the file's own first demonstration was the thing
    that costs the responder the whole batch. `write_bundle` hands over
    `_worked_example`'s lines, built from a verb this bundle really shipped
    at an address it really declared. Nothing here invents one: an empty
    `sample` keeps the canned line, which is what the unscoped rendering
    wants. #TAG:the_header_sample_is_a_permitted_line

    **EMPTY `scopes` IS BYTE-IDENTICAL TO THE UNSCOPED OUTPUT**, and that is
    load-bearing rather than tidy: `tools/check_docs.py` regenerates
    `docs/COMMANDS.md` from this function and compares it byte for byte, so
    any difference on the default path turns the suite red for a change that
    only meant to add a filter. `tools/check_relay.py` asserts the identity
    against a copy taken before the keyword existed. `sample` is defaulted
    for the same reason and `write_bundle` passes it only when there is a
    scope to build one from.
    """
    wanted = tuple(scopes)
    selected = verbs_accepting(wanted) if wanted else all_verbs()
    out: list[str] = [
        f"# {title}",
        "",
        "Every change to the project is one of these. Emit them as JSON",
        "Lines -- one object per line -- into `response.jsonl`.",
        "",
        "```json",
        sample or ('{"verb": "map.tile.set", "scope": "map:test/layer:Floor",'
                   ' "args": {"x": 4, "y": 7, "gid": 65}}'),
        "```",
        "",
        "Rules that are enforced, not suggested:",
        "",
        "- Unknown verb, unknown argument, missing argument, or wrong",
        "  argument type stops the whole response. Nothing is half-applied.",
        "- Types are checked and never coerced. `\"5\"` is not `5`.",
        "- A response is one transaction. One bad line rolls back the rest.",
        "",
        f"{len(selected)} verbs:",
        "",
    ]
    if wanted:
        # Only ever appended on the scoped path, so the default rendering
        # stays byte-identical to what `docs/COMMANDS.md` was generated from.
        out[-2:-2] = [
            "Scoped to " + ", ".join(f"`{s}`" for s in wanted) + ". These are",
            "the only verbs that address it -- every other verb in this",
            "editor is refused on this scope, so a response that reaches for",
            "one is rejected whole. If what you need cannot be said with",
            "these, say so in the reply rather than improvising a verb.",
            "",
            "The `scope` in each verb's own example below shows the SHAPE of",
            "the field, not an address you may aim at: those examples are",
            "registered once, for the whole editor. The worked line above is",
            "the one built for this bundle.",
            "",
        ]
    for spec in selected:
        out.append(f"### `{spec.name}`")
        out.append("")
        out.append(spec.summary + ("  **Destructive.**" if spec.destructive else ""))
        out.append("")
        out.append(f"*Scopes:* {', '.join('`' + s + '`' for s in spec.scopes)}")
        out.append("")
        if spec.params:
            out.append("| arg | type | required | meaning |")
            out.append("|---|---|---|---|")
            for p in spec.params:
                need = "yes" if p.required else f"no (default `{p.default!r}`)"
                doc = p.doc
                if p.choices:
                    doc += f" One of {list(p.choices)}."
                out.append(f"| `{p.name}` | {p.type_name} | {need} | {doc} |")
            out.append("")
        else:
            out.append("*No arguments.*")
            out.append("")
        if spec.example:
            out.append("```json")
            out.append(spec.example)
            out.append("```")
            out.append("")
    return "\n".join(out)
