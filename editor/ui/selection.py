"""What is currently selected, shared by every panel that cares.

WHY THIS EXISTS
---------------
A dock's own scope is right for the *prompt strip* -- a note left on the
Layers panel is about layers, a note on the Tables panel is about tables,
and they should not drag each other around. It is wrong for everything else:
clicking an object on the canvas has to light it up in the hierarchy, fill
the inspector and re-aim the prompt, which three panels each keeping their
own idea of "the current thing" cannot do.

So there are two notions, deliberately:

  Selection    ONE global "what am I looking at", driven by clicking
               anything anywhere. Panels that inspect follow it.
  dock scope   what a given PANEL is about. Follows the selection for
               inspectors; stays put for Tables, Problems, Manifest.

`ScopedDock.follows_selection` picks which. A panel that follows still owns
its prompt strip, so a note typed in the inspector lands on the selected
object and a note typed in Problems lands on the project.

SELECTION IS A SCOPE, NOT AN OBJECT
-----------------------------------
It holds `map:test/layer:entity/object:14`, never a `MapObject` instance.
Holding the instance would go stale the moment a command rebuilt the
document, and a stale reference that still answers questions is exactly the
failure mode this codebase keeps producing. A scope re-resolves every time
and raises loudly if the thing is gone.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from editor.core.scope import Scope


class Selection(QObject):
    """The one global cursor into the project."""

    changed = Signal(object)          # emits the new Scope (never None)

    def __init__(self, initial: Scope, parent: QObject | None = None):
        super().__init__(parent)
        self.__scope = initial
        self.__history: list[Scope] = [initial]

    # -- reading -----------------------------------------------------------

    @property
    def scope(self) -> Scope:
        return self.__scope

    @property
    def kind(self) -> str:
        return self.__scope.kind

    def history(self) -> list[Scope]:
        return list(self.__history)

    # -- writing -----------------------------------------------------------

    def select(self, scope: Scope | str) -> bool:
        """Point at something. Returns True if this was a change."""
        resolved = scope if isinstance(scope, Scope) else Scope.parse(scope)
        if resolved == self.__scope:
            return False
        self.__scope = resolved
        self.__history.append(resolved)
        del self.__history[:-64]
        self.changed.emit(resolved)
        return True

    def reselect(self) -> None:
        """Re-emit without changing. Used after a command rebuilds a document
        so inspectors re-read rather than showing a stale form."""
        self.changed.emit(self.__scope)

    def select_parent(self) -> bool:
        parent = self.__scope.parent()
        return self.select(parent) if parent is not None else False

    def back(self) -> bool:
        if len(self.__history) < 2:
            return False
        self.__history.pop()
        self.__scope = self.__history[-1]
        self.changed.emit(self.__scope)
        return True
