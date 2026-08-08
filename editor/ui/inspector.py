"""The Inspector dock -- everything about the selected thing, editable.

A thin frame around `InspectionView`. All the rendering lives there because
the Database window needs exactly the same form; all the *describing* lives
in `editor.core.inspect` because that has to be testable without Qt.

What is left here is the wiring: follow the selection, re-describe after a
command, hand commands to the window's single mutation point.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

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
        self.view.show_inspection(describe(self.session, self._scope))

    def __on_command(self, command) -> None:
        # run() reports rejections to the user and returns False; either way
        # the form must be rebuilt from the document rather than left showing
        # the value the user typed.
        self.window().run(command)
        self.refresh()
