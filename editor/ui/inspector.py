"""The Inspector dock -- everything about the selected thing, editable.

A thin frame around `InspectionView`. All the rendering lives there because
the Database window needs exactly the same form; all the *describing* lives
in `editor.core.inspect` because that has to be testable without Qt.

What is left here is the wiring: follow the selection, re-describe after a
command, hand commands to the window's single mutation point.

ONE THING IS TAKEN OUT OF THE FORM HERE
---------------------------------------
`describe` renders every custom property as an untyped text box, which is
right for `hp` and wrong for the behavior vocabulary: `pyoneer_behaviors` is
the declaration site of the composition model, and a free-text box offers no
completion, no parameters and -- the part that matters -- no refusal, so a
list naming two behaviors that declare they conflict is authored happily and
fails at map load. The Behaviors panel offers all four. Two doors onto one
property where only one of them validates is the same thing as no validation,
so the raw rows are removed from the generic Properties section and the note
says where they went.

It is done HERE rather than in `editor/core/inspect.py` because this pass
owns this file and not that one; the move is mechanical and belongs beside
the other describers, exactly as `describe_actions` does.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from editor.core.behavior_view import strip_vocabulary
from editor.core.inspect import describe
from editor.ui.docks import ScopedDock
from editor.ui.fields import InspectionView


class InspectorDock(ScopedDock):
    follows_selection = True

    def build_content(self) -> QWidget:
        self.view = InspectionView()
        self.view.command_requested.connect(self.__on_command)
        self.view.reveal_requested.connect(
            lambda path: self.window().reveal(path))
        return self.view

    def refresh(self) -> None:
        self.view.show_inspection(
            strip_vocabulary(describe(self.session, self._scope)))

    def __on_command(self, command) -> None:
        # run() reports rejections to the user and returns False; either way
        # the form must be rebuilt from the document rather than left showing
        # the value the user typed.
        self.window().run(command)
        self.refresh()
