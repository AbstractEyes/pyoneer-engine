"""File > Settings.

Generated from `editor.core.settings.SETTINGS`, so adding a preference is
one entry there and no dialog code. Deliberately short: these are things
about the person using the editor, not about the game, and the fastest way
to make a settings dialog useless is to let those two mix.

Changes apply live rather than on OK, because the only way to judge a theme
is to look at it.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from editor.core.settings import SETTINGS, EditorSettings


class SettingsDialog(QDialog):
    changed = Signal(str, object)          # key, new value

    def __init__(self, settings: EditorSettings, parent: QWidget | None = None,
                 *, ide_choices: list[tuple[str, str]] | None = None):
        super().__init__(parent)
        self.settings = settings
        self.ide_choices = ide_choices or []
        self.setWindowTitle("Editor settings")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        intro = QLabel("These are about you, not about the game. Anything "
                       "that describes the project lives in the project or "
                       "its genre pack.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: palette(mid);")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for setting in SETTINGS:
            editor = self.__editor_for(setting)
            label = QLabel(setting.label)
            label.setToolTip(setting.doc)
            editor.setToolTip(setting.doc)
            form.addRow(label, editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Close
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self.__restore)
        layout.addWidget(buttons)

    # -- widgets -----------------------------------------------------------

    def __editor_for(self, setting) -> QWidget:
        current = self.settings.get(setting.key)

        if setting.type == "bool":
            box = QCheckBox()
            box.setChecked(bool(current))
            box.toggled.connect(
                lambda value, k=setting.key: self.__apply(k, bool(value)))
            return box

        choices = list(setting.choices)
        if setting.key == "ide":
            choices = [("", "Best available")] + self.ide_choices

        combo = QComboBox()
        for value, label in choices:
            combo.addItem(label, value)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.activated.connect(
            lambda _i, k=setting.key, c=combo: self.__apply(k, c.currentData()))
        return combo

    # -- applying ----------------------------------------------------------

    def __apply(self, key: str, value: Any) -> None:
        self.settings.set(key, value)
        self.changed.emit(key, self.settings.get(key))

    def __restore(self) -> None:
        self.settings.reset()
        for setting in SETTINGS:
            self.changed.emit(setting.key, self.settings.get(setting.key))
        # Rebuild so the widgets show the restored values.
        self.close()
        replacement = SettingsDialog(self.settings, self.parent(),
                                     ide_choices=self.ide_choices)
        replacement.changed.connect(self.changed.emit)
        replacement.show()
