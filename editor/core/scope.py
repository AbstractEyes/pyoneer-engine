"""Scopes -- the addressing scheme that ties a panel, a note, and a command
to the same place.

WHY THIS EXISTS
---------------
The whole editor rests on one idea: *a request must know where it lands.*
A prompt typed into the Floor layer panel is about the Floor layer. A note
left on the actors table is about the actors table. Without a shared
address, the AI receives "make them tougher" with no referent and has to
guess -- and guessing is the failure mode this project is built to avoid.

So every dock declares a scope, every note carries it, and every command
targets one. The same string appears in the UI title bar, in the manifest,
in the generated context file, and in the response the AI writes back.

FORM
----
A scope is a `/`-separated path of `kind:name` segments:

    project
    map:test
    map:test/layer:Floor
    map:test/layer:entity/object:14
    table:actors
    table:actors/row:hero
    genre

Names may not contain `/` or `:`. That is a real constraint and it is
checked -- a layer called "a/b" is rejected at the door rather than
producing an address that reparses into something else.

CODE LOCATIONS ARE NOT SCOPES
-----------------------------
A scope addresses the *document*. The engine and editor source files that
own that part of the document are looked up FROM the scope by
`code_locations()`, not encoded into it. That keeps the address stable when
code moves, and it is what fills the "where do I edit?" section of a
request bundle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from editor.core.errors import PyoneerScopeSyntaxError

# The kinds a segment may declare. A closed set on purpose: an unknown kind
# in a response is a sign the AI improvised an address, and that should stop
# the transaction rather than create a scope nothing can resolve.
SCOPE_KINDS: tuple[str, ...] = (
    "project",   # the whole project; terminal, no name
    "genre",     # the genre pack itself; terminal, no name
    "map",       # a .tmx document, by its config name
    "layer",     # a layer inside a map
    "object",    # an object inside an object layer, by id
    "table",     # a data table (actors, weapons, ...)
    "row",       # a row inside a table, by id
    "field",     # a column inside a table
    "assets",    # the art/audio pool; terminal
    "code",      # source the request may touch; terminal, name is a label
)

# Kinds that take no name (`project`, not `project:something`).
UNNAMED_KINDS: frozenset[str] = frozenset({"project", "genre", "assets"})


@dataclass(frozen=True, order=True)
class Segment:
    kind: str
    name: str = ""

    def __str__(self) -> str:
        return self.kind if self.kind in UNNAMED_KINDS else f"{self.kind}:{self.name}"


@dataclass(frozen=True)
class Scope:
    """An immutable document address.

    Hashable and comparable, so notes and commands can be grouped by scope
    with a plain dict.
    """

    segments: tuple[Segment, ...]

    # -- construction ------------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> "Scope":
        raw = (text or "").strip().strip("/")
        if not raw:
            raise PyoneerScopeSyntaxError("a scope may not be empty",
                                          got=text)
        segments = []
        for index, part in enumerate(raw.split("/")):
            segments.append(cls.__parse_segment(part, index, raw))
        return cls(tuple(segments))

    @staticmethod
    def __parse_segment(part: str, index: int, whole: str) -> Segment:
        if not part:
            raise PyoneerScopeSyntaxError(
                "empty segment (a doubled '/')", scope=whole, position=index)
        if ":" not in part:
            if part not in UNNAMED_KINDS:
                raise PyoneerScopeSyntaxError(
                    f"segment {part!r} needs a name, as {part}:<name>",
                    scope=whole, position=index,
                    unnamed_kinds=sorted(UNNAMED_KINDS))
            return Segment(part)
        kind, _, name = part.partition(":")
        if kind not in SCOPE_KINDS:
            raise PyoneerScopeSyntaxError(
                f"unknown scope kind {kind!r}", scope=whole, position=index,
                known=list(SCOPE_KINDS))
        if kind in UNNAMED_KINDS:
            raise PyoneerScopeSyntaxError(
                f"{kind!r} takes no name, write it as {kind!r}",
                scope=whole, position=index)
        if not name:
            raise PyoneerScopeSyntaxError(
                f"{kind!r} needs a name after the colon",
                scope=whole, position=index)
        if ":" in name:
            raise PyoneerScopeSyntaxError(
                f"a name may not contain ':' (got {name!r})",
                scope=whole, position=index)
        return Segment(kind, name)

    @classmethod
    def of(cls, *pairs: str | tuple[str, str]) -> "Scope":
        """Build without going through the string form.

            Scope.of("project")
            Scope.of(("map", "test"), ("layer", "Floor"))
        """
        segments = []
        for pair in pairs:
            if isinstance(pair, str):
                segments.append(Segment(pair))
            else:
                segments.append(Segment(pair[0], pair[1]))
        scope = cls(tuple(segments))
        # Round-trip through the parser so `of` cannot mint an address the
        # string form would reject.
        return cls.parse(str(scope))

    # -- reading -----------------------------------------------------------

    def __str__(self) -> str:
        return "/".join(str(segment) for segment in self.segments)

    def __repr__(self) -> str:
        return f"Scope({str(self)!r})"

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)

    def __len__(self) -> int:
        return len(self.segments)

    @property
    def kind(self) -> str:
        """The kind of the last segment -- what this scope *is*."""
        return self.segments[-1].kind

    @property
    def name(self) -> str:
        """The name of the last segment."""
        return self.segments[-1].name

    @property
    def root_kind(self) -> str:
        return self.segments[0].kind

    def get(self, kind: str) -> str | None:
        """The name of the first segment of `kind`, or None.

        `scope.get("map")` is how a command finds which map it is in,
        regardless of how deep the scope goes.
        """
        for segment in self.segments:
            if segment.kind == kind:
                return segment.name
        return None

    def require(self, kind: str) -> str:
        value = self.get(kind)
        if value is None:
            raise PyoneerScopeSyntaxError(
                f"this scope has no {kind!r} segment",
                scope=str(self), needed=kind)
        return value

    def parent(self) -> "Scope | None":
        if len(self.segments) <= 1:
            return None
        return Scope(self.segments[:-1])

    def child(self, kind: str, name: str = "") -> "Scope":
        return Scope.of(*[(s.kind, s.name) for s in self.segments],
                        (kind, name) if name else kind)

    def is_under(self, other: "Scope") -> bool:
        """True when `other` is this scope or one of its ancestors."""
        n = len(other.segments)
        return len(self.segments) >= n and self.segments[:n] == other.segments

    def matches(self, pattern: str) -> bool:
        """Match against a pattern where `*` stands in for any one name.

        `Scope.parse("map:test/layer:Floor").matches("map:*/layer:*")` is
        True. Used by verb specs to declare what they accept.
        """
        want = pattern.strip().strip("/").split("/")
        if len(want) != len(self.segments):
            return False
        for expected, segment in zip(want, self.segments):
            kind, _, name = expected.partition(":")
            if kind != segment.kind:
                return False
            if name and name != "*" and name != segment.name:
                return False
        return True


PROJECT = Scope.of("project")
GENRE = Scope.of("genre")
ASSETS = Scope.of("assets")


# --------------------------------------------------------------------------
# Scope -> source locations
# --------------------------------------------------------------------------
# This is the "attach the code hierarchy to the request" half. A request
# about `map:test/layer:Floor` should tell the responder that tile layers
# are rendered by `scripts/core/renderer.py` and written by
# `scripts/loaders/map_document.py`, so it does not have to go looking.
#
# Patterns are matched most-specific-first. The lists name real paths; the
# check tool asserts every one of them exists, so this table cannot rot
# quietly the way a comment would.

_CODE_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("map:*/layer:*/object:*", (
        "scripts/loaders/map_document.py",
        "scripts/core/renderer.py",
        "scripts/game/entity/game_entity.py",
        "scripts/core/depth.py",
    )),
    ("map:*/layer:*", (
        "scripts/loaders/map_document.py",
        "scripts/core/renderer.py",
        "scripts/core/depth.py",
    )),
    ("map:*", (
        "scripts/loaders/map_document.py",
        "scripts/core/renderer.py",
        "config/managers/map_data.py",
        "config/maps.json",
    )),
    ("table:*/row:*", (
        "editor/core/project.py",
        "config/managers/config_data.py",
    )),
    ("table:*", (
        "editor/core/project.py",
        "editor/core/genre.py",
        "config/managers/config_data.py",
    )),
    ("genre", (
        "editor/core/genre.py",
        "editor/genres/",
    )),
    ("assets", (
        "docs/ASSETS.md",
        "tools/make_placeholder_art.py",
        "config/animations.json",
    )),
    ("code:*", ()),
    ("project", (
        "main.py",
        "editor/core/project.py",
        "docs/PLAN_EDITOR.md",
    )),
)


def code_locations(scope: Scope) -> tuple[str, ...]:
    """Repo-relative paths a request against `scope` will probably touch.

    Advisory, not a permission list. It exists so a responder starts in the
    right file instead of grepping.
    """
    for pattern, paths in _CODE_MAP:
        if scope.matches(pattern):
            return paths
    # Fall back to the nearest ancestor that does match.
    parent = scope.parent()
    while parent is not None:
        for pattern, paths in _CODE_MAP:
            if parent.matches(pattern):
                return paths
        parent = parent.parent()
    return ()
