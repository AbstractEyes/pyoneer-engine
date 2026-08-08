"""An editing session: a project, its command stream, and its staged notes.

The single object the GUI holds. Everything the GUI does goes through one
of three methods -- `run`, `stage`, `ship` -- so a panel never touches the
project directly and there is exactly one place to look when asking "what
can change this?".

Importing this module registers the command vocabulary as a side effect
(`editor.core.verbs`). That import is load-bearing and deliberate.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Iterable

from editor.core import verbs as _verbs             # noqa: F401  (registers verbs)
from editor.core.commands import Command, CommandStream, Transaction
from editor.core.genre import RuleViolation
from editor.core.project import Project
from editor.core.request import (
    Bundle,
    Manifest,
    Note,
    read_response,
    write_bundle,
)
from editor.core.scope import Scope


class Session:
    """One open project, with undo history and a staged manifest."""

    def __init__(self, project: Project):
        self.project = project
        self.stream = CommandStream(project)
        self.manifest = Manifest()
        self.last_bundle: Bundle | None = None

    # -- opening -----------------------------------------------------------

    @classmethod
    def open(cls, root: str, *, genre_id: str | None = None) -> "Session":
        return cls(Project.load(root, genre_id=genre_id))

    # -- changing ----------------------------------------------------------

    def run(self, commands: Command | Iterable[Command], *,
            label: str | None = None, source: str = "editor") -> Transaction:
        """The only way anything changes. Atomic; raises on any failure."""
        return self.stream.apply(commands, label=label, source=source)

    def undo(self) -> Transaction | None:
        return self.stream.undo()

    def redo(self) -> Transaction | None:
        return self.stream.redo()

    def save(self) -> list[str]:
        return self.project.save()

    @property
    def dirty(self) -> bool:
        return self.project.dirty

    # -- notes -------------------------------------------------------------

    def stage(self, scope: Scope | str, text: str, kind: str = "change") -> Note:
        """Attach a note to a scope. This is the prompt strip's whole job."""
        resolved = scope if isinstance(scope, Scope) else Scope.parse(scope)
        return self.manifest.add(Note(resolved, text, kind))

    def ship(self, *, title: str = "") -> Bundle:
        """Write the staged notes as a request bundle and clear them."""
        if title:
            self.manifest.title = title
        bundle = write_bundle(self.project, self.manifest)
        self.last_bundle = bundle
        self.manifest = Manifest()
        return bundle

    # -- responses ---------------------------------------------------------

    def apply_response(self, path: str) -> Transaction:
        """Apply a `response.jsonl` as one undoable transaction."""
        commands = read_response(path)
        identifier = os.path.basename(os.path.dirname(os.path.abspath(path)))
        return self.run(commands,
                        label=f"response {identifier}",
                        source=f"response:{identifier}")

    # -- reading -----------------------------------------------------------

    def problems(self) -> list[RuleViolation]:
        return self.project.problems()

    def history(self) -> list[Transaction]:
        return self.stream.history()

    def subscribe(self, fn: Callable[[Transaction, str], None]) -> None:
        self.stream.subscribe(fn)

    # -- scopes the UI can offer -------------------------------------------

    def known_scopes(self) -> list[Scope]:
        """Every scope currently worth naming, for pickers and validation."""
        found: list[Scope] = [Scope.of("project"), Scope.of("genre"),
                              Scope.of("assets")]
        for map_name in self.project.map_names():
            map_scope = Scope.of(("map", map_name))
            found.append(map_scope)
            try:
                document = self.project.map(map_name)
            except Exception:                                   # noqa: BLE001
                continue
            for layer in document.layer_names():
                found.append(map_scope.child("layer", layer))
        for table_name in self.project.table_names():
            found.append(Scope.of(("table", table_name)))
        for declared in self.project.genre.tables:
            scope = Scope.of(("table", declared.name))
            if scope not in found:
                found.append(scope)
        return found


def open_here(genre_id: str | None = None) -> Session:
    """Open the repository this file lives in. Convenience for tools."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return Session.open(root, genre_id=genre_id)
