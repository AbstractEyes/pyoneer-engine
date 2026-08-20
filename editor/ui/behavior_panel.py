"""The composition of the selected object, as a checklist rather than a string.

`pyoneer_behaviors` is the declaration site of the engine's central
abstraction -- an entity is one class carrying a list of tokens read off the
tmx object at spawn -- so this panel authors it as a checklist with types,
parameters and refusals. Rendered as free text, a list naming a token that
does not resolve, or two behaviors that declare they conflict, is authored
happily and fails at map load with the object id in the exception.

Everything about what to show lives in `editor/core/behavior_view.py`, which
imports no Qt. This file is the frame: build the view, hand it a description,
send what it emits to the window's single mutation point. That split is why
`tools/check_behavior_ui.py` can assert "ticking `platformer_move` on a body
that already carries `topdown_move` emits NOTHING and names both sides"
without opening a window.

NO NEW VERB
-----------
Every edit here is `map.object.property.set` or `map.object.property.remove`
-- the pair that already writes any tmx custom property and returns an exact
inverse, so this panel inherits undo, one-step rollback, the History panel
and the generated `COMMANDS.md`. Validation cannot move into a verb: a
command that raises inside a transaction takes the rollback with it, so a
refused list must never reach the stream. The panel refuses first and emits
second.

THE TWO QT TRAPS
----------------
Both live on exactly the path this panel takes -- a checkbox emitting a
command that refreshes the form the checkbox is in:

  * `widget.setParent(None)` does not detach a widget, it PROMOTES it to a
    top-level window. Clearing a layout that way leaks about twenty
    miniature windows per Ctrl+Z (59 top-level widgets at rest, 85 after one
    undo, still 85 afterwards).
  * `QScrollArea.setWidget()` frees the widget it replaces SYNCHRONOUSLY, so
    the naive cure for the first frees a checkbox while its own `toggled`
    signal is still on the stack -- a hard STATUS_HEAP_CORRUPTION
    (0xC0000374) crash of the whole editor.

The one sequence that survives both is `takeWidget()` -> `setParent(self)` ->
`hide()` -> `deleteLater()` -> `setWidget(new)`, written once in
`InspectionView.show_inspection`. So this panel rebuilds NOTHING of its own:
the chrome below is built once in `build_content` and only ever has its text
set, and every field widget is `InspectionView`'s.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from editor.core.behavior_view import describe_behaviors
from editor.ui.docks import ScopedDock
from editor.ui.fields import InspectionView

#: Sits above the form, always. Not a caveat like the Actions panel's banner:
#: `LayerRenderer` really does read this property at spawn, and this is the
#: one fact an author needs before ticking anything.
IS_WIRED = (
    "The .tmx object is the whole truth. This list is read at spawn and the "
    "behaviors are attached before the entity binds, so a map plays the same "
    "way whether or not the editor has ever opened it."
)

_BANNER_STYLE = ("background: rgba(120, 180, 255, 30); "
                 "border-left: 3px solid rgb(120, 180, 255); "
                 "padding: 7px 9px; font-size: 11px;")

_PROBLEM_STYLE = ("background: rgba(255, 120, 120, 40); "
                  "border-left: 3px solid rgb(255, 120, 120); "
                  "padding: 6px 9px; font-size: 11px;")


class BehaviorDock(ScopedDock):
    """Which behaviors the selected object composes, and what they read."""

    follows_selection = True

    def build_content(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = QLabel(IS_WIRED)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(_BANNER_STYLE)
        layout.addWidget(self.banner)

        self.view = InspectionView(show_header=True, show_sources=False)
        self.view.command_requested.connect(self.__on_command)
        layout.addWidget(self.view, 1)

        # An emitter that refuses to build a command returns None, which the
        # view treats as a silent no-op -- right for "nothing changed", wrong
        # for "your value was rejected", which is what this label says. Its
        # text is set and it is never rebuilt, so neither Qt trap applies.
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(_PROBLEM_STYLE)
        self.problem.hide()
        layout.addWidget(self.problem)
        return holder

    # -- refreshing --------------------------------------------------------

    def refresh(self) -> None:
        # Cleared BEFORE describing, never after: describing installs the
        # emitters that call `report`, and one firing during this refresh
        # must not have its message wiped.
        self.report("")
        self.view.show_inspection(
            describe_behaviors(self.session, self._scope, on_error=self.report))

    def report(self, message: str) -> None:
        """Show why an edit produced no command, or clear it."""
        self.problem.setText(message)
        self.problem.setVisible(bool(message))

    # -- emitting ----------------------------------------------------------

    def __on_command(self, command: Any) -> None:
        # run() reports a rejection to the user and returns False; either way
        # the form is rebuilt from the document rather than left showing what
        # was ticked, so a refused edit cannot leave the panel lying.
        self.window().run(command)
        self.refresh()
