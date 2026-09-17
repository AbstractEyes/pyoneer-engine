"""Pick, read, edit and save ONE character file. The only file this window writes.

OWNER: this pane owns `tools/nai/characters/<name>.json` and nothing else.
It writes a character file because that is DATA, not a request: no
credential, no network, no spend. Every other byte this window puts on disk
is written by a child process, under `data/nai/`.

WHAT IT SHOWS, IN FILE ORDER
----------------------------
    Character        a combo of `characters.available()`, plus Copy As...
    Subject          `model.SUBJECT_NAMES` -- boy (the default) or girl
    Garments         one control per `model.GARMENT_SLOTS`, in that order:
                     hat none|wizard, cape false|true, neck scarf|none,
                     legwear pants|dress, footwear boots|heels
    Tags             the base-caption tags, one line
    Anchor           the per-frame tags, one line, with a chip per tag it
                     may legally use -- the anchor repeats a tag of `tags`
                     verbatim and adds none, so the chips ARE that rule
                     offered rather than restated
    Colours          one `widgets.ColourSwatch` per part, and EXACTLY the
                     parts these garments draw
                     (`model.garment_parts(garments)`)

EVERY VOCABULARY IS READ, NOT TYPED. The subjects, the garment slots, each
slot's choices and its default, the parts each choice draws and the fields
a file may hold are all read off `tools.nai.model` and
`tools.nai.characters` when the form is built, so a slot added there grows
a control here in the same change. `edited_json` RAISES for a field of
`characters.FIELDS` this pane has no control for (law 7), rather than
writing a file that quietly drops it.

THE LOADER IS THE JUDGE, NOT THIS PANE
--------------------------------------
Every rule -- the field set, the tag rules (`characters.tag_problem`: no
count, no `rating:`, no quality tail, no rating word, no view that fights
the side view, no negative tag, no contradicting subject word), the anchor
subset rule, the exact-parts rule, the key-distance and shade rules -- is
`tools.nai.characters`'. This pane calls `characters.parse` on the bytes it
is about to write and SHOWS the refusal verbatim, in
`theme.PROBLEM_STYLE`. It never reimplements a rule and never pre-filters
what the author may type, because a second copy of a rule is the sibling
route that drifts (CLAUDE.md, ACTIVE WARNINGS).

The ONE thing this pane reads out of a refusal is which FIELD it named --
`characters._refused` writes `field 'colours.dress'` -- so the sentence can
be shown beside the control it is about as well as in the banner. The
judgement is never parsed, only the address.

One rule is NOT the loader's: the token budget depends on the recipe's
words, so `recipes.budget_problem(identity)` is called too and its refusal
shown the same way. A file that fits `walk` but not `run` is refused for
both, before anything is drawn.

NOTHING IS INVENTED FOR A NEW PART. Switching legwear to `dress` asks for
a colour this file has never had, and this pane does not pick one: the
`dress` row shows as missing, `edited_json` omits the key, and the loader
says `missing part(s) ['dress']` in its own words. A plausible default here
would be a colour nobody chose, drawn into a sprite, for money (law 7).

THE DEFAULT IS NOT EDITABLE HERE. `scout.json` is pinned equal to
`recipes.IDENTITY` by `tools/check_nai.py`, so this pane opens it read-only
with that sentence as the reason, and offers Copy As... An outfit change is
a new file, never an edit to that one.

THE LIVE INIT PREVIEW
---------------------
The init is the picture the whole pipeline turns on -- what the model is
handed, and what `pixelize` keys out -- so the pane draws it as you edit:
`recipes.build_recipe` then `mannequin.render_init`, THE SAME TWO CALLS
`cli._cmd_render` makes, on a worker thread, debounced, into a scratch
directory of its own. It never draws from an identity the loader refused,
and it never blocks the window.

That is a DRAWING, not a request. It opens no socket, spends nothing,
starts no process and writes nothing under `data/nai/` -- which is why it
may follow a keystroke at all, while a command a human types may not (see
`tools/nai_ui/__init__.py`: one generation is one command a human typed).
The `render` BUTTON is the other half: it emits `render_requested` and the
window composes the real `python -m tools.nai render ...` line, so the
author can see the same PNG arrive by the route the ledger records, and
compare the two `png sha256` lines by eye.

WHAT IT EMITS
-------------
One signal, carrying one value: `character_changed(CharacterState)`. It
fires when the combo changes, when the file on disk is re-read, and after a
save -- NEVER on every keystroke, because `RequestPane` turns it into a
command line and a command that rewrites itself as you type is a command
nobody read. An edit in flight is announced by `dirty_changed(bool)`
instead, which only greys the Send controls.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QVBoxLayout,
                               QWidget)

from tools.nai import characters, mannequin, model, recipes
from tools.nai_ui import theme
from tools.nai_ui.widgets import ColourSwatch, ImageView, PositionGrid, field_row

FIELD_RX = re.compile(r"field '([^']+)'")
"""How `characters._refused` spells the field it refused: `field 'colours.hair'`.
The pane reads the ADDRESS out of a refusal and never the judgement, so the
sentence can stand beside the control it is about as well as in the banner."""

MISSING = "no colour yet"
"""What a part these garments draw but this file has never coloured says.
Nothing is invented for it -- the loader refuses the file by name (law 7)."""


@dataclass(frozen=True)
class CharacterState:
    """What the rest of the window knows about the chosen character.

    `name` is the file stem, the string that goes into `--character NAME`
    and into every default output path. `path` is the file it came from.

    `identity` is the `model.Identity` the loader built, or None when the
    file is unreadable or refused -- and then `problem` is the loader's own
    message, naming the file and the field. Exactly one of the two is set,
    always: `identity is None` is the same question as `problem != ""`.

    `parts` is `model.garment_parts(identity.garments)` -- the parts this
    outfit draws, in `model.PARTS` order -- repeated here so `RequestPane`
    and the swatches do not each recompute it.

    `dirty` is True when the pane holds an unsaved edit. A dirty state
    still carries the identity of what is ON DISK, because that is what a
    command would use.
    """

    name: str
    path: str
    identity: object | None
    problem: str
    parts: tuple[str, ...]
    dirty: bool

    def ok(self) -> bool:
        """True when `identity` is not None and `problem` is empty."""
        return self.identity is not None and not self.problem


class _PreviewSignals(QObject):
    """The one channel a preview worker answers on, owned by the pane.

    Parented to the pane, so Qt drops the connection when the pane dies and
    a worker that finishes afterwards delivers to nobody instead of into
    freed memory.
    """

    done = Signal(int, str, str, object)


class _PreviewTask(QRunnable):
    """Draw one mannequin init off the GUI thread; answer once.

    The same two calls `cli._cmd_render` makes -- `recipes.build_recipe`
    then `mannequin.render_init` -- and then one file written into the
    pane's own scratch directory. No socket, no child process, nothing
    under `data/nai/`.
    """

    def __init__(self, signals: _PreviewSignals, token: int, identity,
                 recipe_name: str, out_path: str) -> None:
        """Draw `recipe_name` for `identity` into `out_path`, tagged `token`."""
        super().__init__()
        self.__signals = signals
        self.__token = token
        self.__identity = identity
        self.__recipe = recipe_name
        self.__out = out_path

    def run(self) -> None:
        """Draw it, write it, and emit (token, path, problem, centers)."""
        try:
            recipe = recipes.build_recipe(self.__recipe, self.__identity)
            png, centers = mannequin.render_init(
                recipe.layout, recipe.poses, self.__identity.as_dict(),
                garments=self.__identity.garments)
            partial = self.__out + ".part"
            with open(partial, "wb") as handle:
                handle.write(png)
            os.replace(partial, self.__out)
        except Exception as exc:                                # noqa: BLE001
            self.__answer(self.__token, "", f"{type(exc).__name__}: {exc}", ())
            return
        self.__answer(self.__token, self.__out, "", centers)

    def __answer(self, token: int, path: str, refusal: str, centers) -> None:
        """Emit, unless the pane that asked has been destroyed meanwhile.

        A drawing outlives the window that wanted it when the window is
        closed mid-draw; Qt has already freed the signal's owner by then
        and emitting raises. There is nobody to tell, so this is the one
        place the answer is dropped -- and only this one.
        """
        try:
            self.__signals.done.emit(token, path, refusal, centers)
        except RuntimeError:
            pass


class CharacterPane(QWidget):
    """The character form.

    Signals:
        character_changed(object)   a `CharacterState`; on selection, on
                                    re-read and after a save -- never per
                                    keystroke
        dirty_changed(bool)         an edit is in flight / was saved
        render_requested(str)       the character name: "draw this one",
                                    which `app.NaiWindow` turns into a
                                    `render` command. The pane does not
                                    build or run it.
    """

    character_changed = Signal(object)
    dirty_changed = Signal(bool)
    render_requested = Signal(str)

    CHIP_COLUMNS = 3
    """How many anchor chips stand side by side before the next row."""

    PREVIEW_DELAY_MS = 250
    """How long the init preview waits for typing to stop. It debounces a
    DRAWING; nothing that sends is ever on a timer."""

    def __init__(self, parent=None) -> None:
        """Build the form and select `characters.DEFAULT_CHARACTER`.

        Emits `character_changed` once, synchronously, at the end of
        construction, so a window that connects before showing has a state
        without asking for one.
        """
        super().__init__(parent)
        self.__name = ""
        self.__path = ""
        self.__file_identity = None
        self.__file_problem = ""
        self.__colours: dict[str, str] = {}
        self.__swatches: dict[str, ColourSwatch] = {}
        self.__chips: list[QPushButton] = []
        self.__chip_tags: tuple[str, ...] = ()
        self.__dirty = False
        self.__loading = True
        self.__loaded_form: tuple = ()
        self.__preview_dir = ""
        self.__preview_temp = None
        self.__preview_token = 0
        self.__preview_busy = False

        self.__build()

        self.__preview_signals = _PreviewSignals(self)
        self.__preview_signals.done.connect(self.__preview_done)
        self.__preview_timer = QTimer(self)
        self.__preview_timer.setSingleShot(True)
        self.__preview_timer.setInterval(self.PREVIEW_DELAY_MS)
        self.__preview_timer.timeout.connect(self.__draw_preview)

        self.__loading = False
        self.__load(characters.DEFAULT_CHARACTER)

    # -- construction ------------------------------------------------------

    def __build(self) -> None:
        """Lay the form out once: picker, subject, garments, tags, anchor,
        colours, init.
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        column = QVBoxLayout(body)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(8)

        heading = QLabel("Character", body)
        heading.setStyleSheet(theme.HEADING_STYLE)
        column.addWidget(heading)

        picker = QHBoxLayout()
        self.__character = QComboBox(body)
        self.__character.currentIndexChanged.connect(self.__character_chosen)
        picker.addWidget(self.__character, 1)
        self.__reload_button = QPushButton("Re-read", body)
        self.__reload_button.setToolTip(
            "read the file from disk again, discarding any edit here")
        self.__reload_button.clicked.connect(self.__reload_clicked)
        picker.addWidget(self.__reload_button)
        self.__save_button = QPushButton("Copy As...", body)
        self.__save_button.setToolTip(
            "write these fields to a NEW tools/nai/characters/<name>.json; "
            "a save never overwrites")
        self.__save_button.clicked.connect(self.__save_clicked)
        picker.addWidget(self.__save_button)
        column.addLayout(picker)

        self.__readonly = QLabel(body)
        self.__readonly.setWordWrap(True)
        self.__readonly.setStyleSheet(theme.LOCKED_STYLE)
        self.__readonly.hide()
        column.addWidget(self.__readonly)

        who = QFormLayout()
        who.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        column.addLayout(who)

        subjects = QWidget(body)
        subject_row = QHBoxLayout(subjects)
        subject_row.setContentsMargins(0, 0, 0, 0)
        self.__subject_group = QButtonGroup(self)
        self.__subject_buttons: dict[str, QRadioButton] = {}
        for name in model.SUBJECT_NAMES:
            entry = model.subject(name)
            button = QRadioButton(f"{entry.name} ({entry.count_tag})",
                                  subjects)
            button.toggled.connect(self.__field_edited)
            self.__subject_group.addButton(button)
            self.__subject_buttons[name] = button
            subject_row.addWidget(button)
        subject_row.addStretch(1)
        field_row(who, "Subject", subjects,
                  "the count at the head of the base caption, the first word "
                  "of every frame caption, and which subject words a tag may "
                  "not carry")

        garments = QGroupBox("Garments", body)
        garment_form = QFormLayout(garments)
        self.__garment_boxes: dict[str, QComboBox] = {}
        for slot in model.GARMENT_SLOTS:
            box = QComboBox(garments)
            for choice in slot.choices:
                spelled = ("true" if choice is True else
                           "false" if choice is False else str(choice))
                if type(choice) is type(slot.default) and choice == slot.default:
                    spelled += "  (default)"
                box.addItem(spelled)
            box.currentIndexChanged.connect(self.__garments_edited)
            self.__garment_boxes[slot.name] = box
            garment_form.addRow(slot.name, box)
        column.addWidget(garments)

        caption = QFormLayout()
        caption.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        column.addLayout(caption)

        self.__tags = QLineEdit(body)
        self.__tags.textChanged.connect(self.__tags_edited)
        field_row(caption, "Tags", self.__tags,
                  "comma separated; they go into the base caption once")

        self.__anchor = QLineEdit(body)
        self.__anchor.textChanged.connect(self.__field_edited)
        field_row(caption, "Anchor", self.__anchor,
                  "repeated in EVERY frame caption; every anchor tag is "
                  "verbatim a tag of Tags")

        self.__chip_box = QWidget(body)
        chip_column = QVBoxLayout(self.__chip_box)
        chip_column.setContentsMargins(0, 0, 0, 0)
        chip_column.setSpacing(2)
        chip_label = QLabel("Anchor may use, verbatim:", self.__chip_box)
        chip_label.setStyleSheet(theme.CAPTION_STYLE)
        chip_column.addWidget(chip_label)
        # A GRID, not a row: a row of chips is as wide as the tags are long,
        # and it is the pane's width that would pay for it.
        self.__chip_layout = QGridLayout()
        self.__chip_layout.setContentsMargins(0, 0, 0, 0)
        self.__chip_layout.setSpacing(4)
        chip_column.addLayout(self.__chip_layout)
        column.addWidget(self.__chip_box)

        self.__colour_box = QGroupBox("Colours", body)
        self.__colour_layout = QFormLayout(self.__colour_box)
        column.addWidget(self.__colour_box)

        self.__problem = QLabel(body)
        self.__problem.setWordWrap(True)
        self.__problem.setStyleSheet(theme.PROBLEM_STYLE)
        self.__problem.hide()
        column.addWidget(self.__problem)

        init = QLabel("Mannequin init", body)
        init.setStyleSheet(theme.HEADING_STYLE)
        column.addWidget(init)

        init_row = QHBoxLayout()
        self.__recipe = QComboBox(body)
        for name in recipes.RECIPE_NAMES:
            self.__recipe.addItem(name)
        self.__recipe.currentIndexChanged.connect(self.__field_edited)
        init_row.addWidget(self.__recipe)
        self.__render_button = QPushButton("Draw it with the render command",
                                           body)
        self.__render_button.setToolTip(
            "compose `python -m tools.nai render <recipe> --character "
            "<name>`; no network")
        self.__render_button.clicked.connect(
            lambda: self.render_requested.emit(self.__name))
        init_row.addWidget(self.__render_button, 1)
        column.addLayout(init_row)

        self.__preview = ImageView(body)
        column.addWidget(self.__preview)

        self.__preview_note = QLabel(body)
        self.__preview_note.setWordWrap(True)
        self.__preview_note.setStyleSheet(theme.CAPTION_STYLE)
        column.addWidget(self.__preview_note)

        centres = QHBoxLayout()
        self.__grid = PositionGrid(model.GRID[0], model.GRID[2], parent=body)
        centres.addWidget(self.__grid)
        self.__grid_note = QLabel(body)
        self.__grid_note.setWordWrap(True)
        self.__grid_note.setStyleSheet(theme.CAPTION_STYLE)
        centres.addWidget(self.__grid_note, 1)
        column.addLayout(centres)

        column.addStretch(1)

    # -- reading -----------------------------------------------------------

    def state(self) -> CharacterState:
        """The current state. The same value the last signal carried."""
        identity = self.__file_identity
        parts = (model.garment_parts(identity.garments)
                 if identity is not None else ())
        return CharacterState(name=self.__name, path=self.__path,
                              identity=identity, problem=self.__file_problem,
                              parts=parts, dirty=self.__dirty)

    def dirty(self) -> bool:
        """True while the form differs from the file it was read from."""
        return self.__dirty

    def subject(self) -> str:
        """The subject the form holds -- one of `model.SUBJECT_NAMES`."""
        for name, button in self.__subject_buttons.items():
            if button.isChecked():
                return name
        raise RuntimeError("no subject is chosen; the form always holds one")

    def garments(self):
        """The `model.Garments` the form holds."""
        values = {}
        for slot in model.GARMENT_SLOTS:
            box = self.__garment_boxes[slot.name]
            values[slot.name] = slot.choices[box.currentIndex()]
        return model.Garments(**values)

    def parts(self) -> tuple[str, ...]:
        """The parts the form's garments draw, in `model.PARTS` order."""
        return model.garment_parts(self.garments())

    def tags(self) -> str:
        """The Tags line, as the form holds it."""
        return self.__tags.text().strip()

    def anchor(self) -> str:
        """The Anchor line, as the form holds it."""
        return self.__anchor.text().strip()

    def colours(self) -> dict[str, str]:
        """The colours the form would write: the drawn parts it has, in order."""
        return {part: self.__colours[part] for part in self.parts()
                if part in self.__colours}

    def recipe(self) -> str:
        """The recipe the init preview draws -- one of `recipes.RECIPE_NAMES`."""
        return self.__recipe.currentText()

    def preview_dir(self) -> str:
        """The scratch directory the init preview draws into, or "" unused.

        It is a temporary directory of this pane's own, never `data/nai/`:
        a preview is a drawing, and the ledger's tree belongs to the child
        process that writes it.
        """
        return self.__preview_dir

    def preview_path(self) -> str:
        """The PNG the preview last drew, or "" -- `ImageView.path()`."""
        return self.__preview.path()

    def preview_note(self) -> str:
        """What the preview says about itself: drawing, drawn, or refused."""
        return self.__preview_note.text()

    def preview_pending(self) -> bool:
        """True while a drawing is waited for or in flight.

        The window greys nothing on it: it is there so a reader -- and a
        check -- can tell "no init yet" from "this init".
        """
        return self.__preview_timer.isActive() or self.__preview_busy

    def swatch(self, part: str) -> ColourSwatch:
        """The swatch for `part`; KeyError when these garments do not draw it."""
        if part not in self.__swatches:
            raise KeyError(f"no swatch for part {part!r}; these garments draw "
                           f"{self.parts()}")
        return self.__swatches[part]

    # -- selection ---------------------------------------------------------

    def select(self, name: str) -> None:
        """Choose character `name` and re-read it from disk.

        ValueError listing `characters.available()` for an unknown name --
        it is never mapped to the default (`characters.unknown_character`).
        Refuses, without changing anything, while `dirty`: the caller asks
        `confirm_discard` first.
        """
        if not isinstance(name, str) or name not in characters.available():
            raise ValueError(characters.unknown_character(name))
        if self.__dirty:
            raise RuntimeError(
                f"{self.__name} has an unsaved edit, so selecting {name!r} "
                f"would discard it; ask confirm_discard() first, or "
                f"reload()")
        self.__load(name)

    def reload(self) -> None:
        """Re-read the selected file from disk, discarding any edit.

        Nothing here caches, so this is how an edit made in a text editor
        reaches the window.
        """
        self.__load(self.__name)

    # -- editing -----------------------------------------------------------

    def set_subject(self, name: str) -> None:
        """Choose the subject; ValueError listing `model.SUBJECT_NAMES`."""
        model.subject(name)
        self.__subject_buttons[name].setChecked(True)

    def set_garment(self, slot_name: str, choice) -> None:
        """Choose one garment; ValueError naming the slot's legal choices."""
        for slot in model.GARMENT_SLOTS:
            if slot.name != slot_name:
                continue
            for index, value in enumerate(slot.choices):
                if type(value) is type(choice) and value == choice:
                    self.__garment_boxes[slot_name].setCurrentIndex(index)
                    return
            raise ValueError(model.garment_problem(slot, choice))
        raise ValueError(f"unknown garment slot {slot_name!r}; the slots are "
                         f"{tuple(s.name for s in model.GARMENT_SLOTS)}")

    def set_colour(self, part: str, hex_colour: str) -> None:
        """Set one part's colour; ValueError for a part these garments miss.

        The FORMAT is judged here (`#RRGGBB`, by `ColourSwatch`) and
        nothing else: whether the colour keeps its distance from the key
        grey, and whether its shades do, is the loader's answer and arrives
        through `problem()`.
        """
        if part not in self.parts():
            outfit = model.garments_text(self.garments())
            raise ValueError(f"these garments ({outfit}) do not draw "
                             f"{part!r}; they draw {self.parts()}")
        if (not isinstance(hex_colour, str)
                or not characters.HEX_RX.fullmatch(hex_colour)):
            raise ValueError(f"the colour of part {part!r} is {hex_colour!r}, "
                             f"which is not a '#RRGGBB' hex colour")
        self.__colours[part] = hex_colour.upper()
        if part in self.__swatches:
            # The swatch is told, and stays silent about it: a colour set
            # by code is the model talking, and it must not come back as
            # an edit the pane then re-applies.
            self.__swatches[part].set_colour(hex_colour)
        else:
            self.__rebuild_colours()
        self.__field_edited()

    def set_tags(self, text: str) -> None:
        """Replace the Tags line."""
        self.__tags.setText(str(text))

    def set_anchor(self, text: str) -> None:
        """Replace the Anchor line."""
        self.__anchor.setText(str(text))

    def set_recipe(self, name: str) -> None:
        """Choose the recipe the init preview draws; ValueError if unknown."""
        if name not in recipes.RECIPE_NAMES:
            raise ValueError(f"unknown recipe {name!r}; legal: "
                             f"{', '.join(sorted(recipes.RECIPE_NAMES))}")
        self.__recipe.setCurrentText(name)

    def edited_json(self) -> bytes:
        """The form as the file bytes it would be saved as.

        UTF-8, two-space indent, the fields in `characters.FIELDS` order,
        an optional field omitted when it equals its default -- so a file
        with no `subject` and no `garments` round-trips unchanged and a
        pre-garments file does not grow two fields it never had.

        RuntimeError for a field `characters.FIELDS` names and this pane
        has no control for: a file format that grew a field is a change to
        make here, not one to write out silently missing (law 7).
        """
        garments = self.garments()
        document: dict[str, object] = {}
        for field in characters.FIELDS:
            if field == "tags":
                document[field] = self.__tags.text().strip()
            elif field == "anchor":
                document[field] = self.__anchor.text().strip()
            elif field == "colours":
                document[field] = self.colours()
            elif field == "subject":
                if self.subject() != model.DEFAULT_SUBJECT:
                    document[field] = self.subject()
            elif field == "garments":
                if garments != model.DEFAULT_GARMENTS:
                    document[field] = {slot.name: getattr(garments, slot.name)
                                       for slot in model.GARMENT_SLOTS}
            else:
                raise RuntimeError(
                    f"characters.FIELDS names {field!r}, which this pane has "
                    f"no control for; a character file would be saved "
                    f"without it")
        text = json.dumps(document, indent=2, ensure_ascii=False)
        return (text + "\n").encode("utf-8")

    def problem(self) -> str:
        """Why `edited_json()` would be refused, or "".

        `characters.parse(self.edited_json(), path)` then
        `recipes.budget_problem(identity)`, in that order, both messages
        verbatim. This is the ONE place the pane judges anything, and it
        judges by calling the loader.
        """
        return self.__judge()[1]

    def save_as(self, name: str) -> str:
        """Write `edited_json()` to `tools/nai/characters/<name>.json`.

        Returns the path written. Refuses, with ValueError and nothing
        written, when: `name` does not match `characters.NAME_RX`; the file
        already exists (a save never overwrites -- Copy As... is how a new
        outfit is made and `reload` is how an old one is re-read); `name`
        is `characters.DEFAULT_CHARACTER`; or `problem()` is non-empty.

        Emits `character_changed` with the new name afterwards, so the
        command line follows the file that now exists.
        """
        if not isinstance(name, str) or not characters.NAME_RX.fullmatch(name):
            raise ValueError(f"{name!r} is not a character name; a name is "
                             f"its file stem and matches "
                             f"{characters.NAME_RX.pattern}")
        if name == characters.DEFAULT_CHARACTER:
            raise ValueError(
                f"{name} is the default character, pinned equal to "
                f"recipes.IDENTITY by tools/check_nai.py; an outfit change "
                f"is a new file, never an edit to that one")
        path = characters.file_for(name)
        if os.path.exists(path):
            raise ValueError(f"{path} already exists; a save never "
                             f"overwrites -- re-read it, or choose another "
                             f"name")
        refusal = self.problem()
        if refusal:
            raise ValueError(f"{name} is not saved, because the loader "
                             f"refuses it: {refusal}")
        raw = self.edited_json()
        with open(path, "wb") as handle:
            handle.write(raw)
        self.__load(name)
        return path

    def drop_preview(self) -> str:
        """Delete the preview scratch directory. Returns the path it removed.

        Idempotent, and "" when there was never one. Called by
        `NaiWindow.closeEvent`; `tempfile.TemporaryDirectory`'s own
        finalizer is the backstop for a process that dies without one, so
        a window session cannot leave a strip PNG in the system temp
        directory for good the way it used to.
        """
        temp, self.__preview_temp = self.__preview_temp, None
        gone, self.__preview_dir = self.__preview_dir, ""
        if temp is None:
            return ""
        temp.cleanup()
        return gone

    def free_name(self) -> str:
        """A character name no file uses yet, suggested from the one open.

        `<name>_2`, `<name>_3`, ... until `characters.file_for` names a
        path that is not there. The default character's own stem is never
        offered, because `save_as` refuses it by name.

        RuntimeError after 999 tries (law 7): a suggestion box is not the
        place to guess, and a directory holding 999 copies of one outfit is
        a thing the author wants told.
        """
        stem = self.__name or characters.DEFAULT_CHARACTER
        for index in range(2, 1000):
            wanted = f"{stem}_{index}"
            if (characters.NAME_RX.fullmatch(wanted)
                    and wanted != characters.DEFAULT_CHARACTER
                    and not os.path.exists(characters.file_for(wanted))):
                return wanted
        raise RuntimeError(
            f"every name from {stem}_2 to {stem}_999 already has a file in "
            f"{os.path.dirname(characters.file_for(stem))}; name this one "
            f"yourself")

    def confirm_discard(self) -> bool:
        """Ask before losing an unsaved edit; True to go ahead.

        LAW 13: this is the pane's ONLY modal, and it is reachable only
        from a user action. `tools/check_nai_ui.py` drives this pane with
        this method replaced, exactly as `tools/check_editor_ui.py`
        replaces `editor.ui.ask`, so no check can ever block on it.
        """
        answer = QMessageBox.question(
            self, "Discard the edit?",
            f"{self.__name} has an unsaved edit. Discard it?",
            QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return answer == QMessageBox.Discard

    # -- loading -----------------------------------------------------------

    def __load(self, name: str) -> None:
        """Read `name` from disk into the form and announce the state."""
        path = characters.file_for(name)
        self.__name = name
        self.__path = path
        try:
            self.__file_identity = characters.load_file(path)
            self.__file_problem = ""
        except ValueError as exc:
            self.__file_identity = None
            self.__file_problem = str(exc)

        was = self.__loading
        self.__loading = True
        try:
            self.__refresh_names()
            self.__fill_from(path)
        finally:
            self.__loading = was
        self.__loaded_form = self.__snapshot()
        self.__set_dirty(False)
        # THE RULE IS ON SCREEN BEFORE THE REFUSAL, FOR EVERY CHARACTER.
        # `save_as` never overwrites -- of any file, not only the default
        # one -- so the button is a Copy button always, and the sentence
        # saying why is shown always. It used to say "Save As..." on every
        # other character and pre-fill the name that save is guaranteed to
        # refuse, which made the most natural edit-and-save gesture in the
        # window fail every single time.
        self.__readonly.setText(
            f"{name}.json is the default character, pinned equal to "
            f"recipes.IDENTITY by tools/check_nai.py. Edit it here and save "
            f"it under a new name: an outfit change is a new file."
            if name == characters.DEFAULT_CHARACTER else
            "A save here never overwrites: an outfit change is a new file. "
            "Edit this one and copy it under a new name, or press Re-read "
            "to throw the edit away.")
        self.__readonly.setVisible(True)
        self.__save_button.setText("Copy As...")
        self.__revalidate()
        # A debounce still counting down belongs to the file that was just
        # replaced; the new file draws now, not after it.
        self.__preview_timer.stop()
        self.__preview.clear()
        self.__draw_preview()
        self.character_changed.emit(self.state())

    def __refresh_names(self) -> None:
        """Re-read `characters.available()` into the combo, keeping the
        selection.
        """
        names = characters.available()
        current = [self.__character.itemText(i)
                   for i in range(self.__character.count())]
        if current != list(names):
            self.__character.clear()
            for name in names:
                self.__character.addItem(name)
        if self.__name in names:
            self.__character.setCurrentText(self.__name)

    def __fill_from(self, path: str) -> None:
        """Put the file's fields into the form, field by field.

        A file the loader REFUSES still fills the form, from the raw JSON,
        so the author can see and fix the field that was refused. A file
        that is not JSON at all fills nothing: there is no field to show.
        """
        document: dict = {}
        try:
            with open(path, "rb") as handle:
                document = json.loads(handle.read().decode("utf-8-sig"))
        except (OSError, ValueError):
            document = {}
        if not isinstance(document, dict):
            document = {}

        subject = document.get("subject", model.DEFAULT_SUBJECT)
        if subject not in self.__subject_buttons:
            subject = model.DEFAULT_SUBJECT
        self.__subject_buttons[subject].setChecked(True)

        wearing = document.get("garments", {})
        wearing = wearing if isinstance(wearing, dict) else {}
        for slot in model.GARMENT_SLOTS:
            value = wearing.get(slot.name, slot.default)
            index = next((i for i, choice in enumerate(slot.choices)
                          if type(choice) is type(value) and choice == value),
                         slot.choices.index(slot.default))
            self.__garment_boxes[slot.name].setCurrentIndex(index)

        self.__tags.setText(str(document.get("tags", "")))
        self.__anchor.setText(str(document.get("anchor", "")))

        self.__colours = {}
        palette = document.get("colours", {})
        if isinstance(palette, dict):
            for part, value in palette.items():
                if (isinstance(part, str) and isinstance(value, str)
                        and characters.HEX_RX.fullmatch(value)):
                    self.__colours[part] = value.upper()
        self.__rebuild_chips()
        self.__rebuild_colours()

    # -- the form talking --------------------------------------------------

    def __character_chosen(self, index: int) -> None:
        """The combo moved: confirm a discard first, then load the new file."""
        if self.__loading or index < 0:
            return
        wanted = self.__character.itemText(index)
        if wanted == self.__name:
            return
        if self.__dirty and not self.confirm_discard():
            self.__loading = True
            try:
                self.__character.setCurrentText(self.__name)
            finally:
                self.__loading = False
            return
        self.__set_dirty(False)
        self.__load(wanted)

    def __reload_clicked(self) -> None:
        """The Re-read button: confirm a discard first, then re-read."""
        if self.__dirty and not self.confirm_discard():
            return
        self.__set_dirty(False)
        self.reload()

    def __save_clicked(self) -> None:
        """The Copy As... button: ask for a name, then `save_as`, and show
        its refusal.

        The suggestion is `free_name()` -- a name no file has yet -- and
        never the name of the file already open, which `save_as` is
        guaranteed to refuse.
        """
        name, chose = QInputDialog.getText(
            self, "Copy the character to",
            "a file stem matching " + characters.NAME_RX.pattern,
            text=self.free_name())
        if not chose:
            return
        try:
            self.save_as(name)
        except ValueError as exc:
            self.__show_problem(str(exc))

    def __tags_edited(self, _text: str = "") -> None:
        """Tags changed: rebuild the anchor's chips, then revalidate."""
        if self.__loading:
            return
        self.__rebuild_chips()
        self.__field_edited()

    def __garments_edited(self, _index: int = -1) -> None:
        """A garment changed: rebuild the swatches, then revalidate."""
        if self.__loading:
            return
        self.__rebuild_colours()
        self.__field_edited()

    def __colour_picked(self, part: str, hex_colour: str) -> None:
        """A swatch handed back a colour: keep it and revalidate."""
        self.__colours[part] = hex_colour
        self.__field_edited()

    def __field_edited(self, *_args) -> None:
        """Any field changed: re-judge the form, and re-draw the init after
        a pause.
        """
        if self.__loading:
            return
        self.__set_dirty(self.__snapshot() != self.__loaded_form)
        self.__revalidate()
        self.__preview_timer.start()

    def __set_dirty(self, dirty: bool) -> None:
        """Set the dirty flag, and announce it only when it moves."""
        if dirty == self.__dirty:
            return
        self.__dirty = dirty
        self.dirty_changed.emit(dirty)

    def __snapshot(self) -> tuple:
        """The form as one comparable value -- what `dirty` compares
        against.
        """
        # The recipe is NOT in here: it chooses which strip the init preview
        # draws, and is not a field of the character file. Choosing another
        # one re-draws; it never makes the file dirty.
        return (self.subject(), tuple(self.garments()),
                self.__tags.text().strip(), self.__anchor.text().strip(),
                tuple(sorted(self.colours().items())))

    # -- the loader talking ------------------------------------------------

    def __judge(self) -> tuple[object, str]:
        """(identity, "") when the loader accepts the form, else (None, why)."""
        try:
            identity = characters.parse(self.edited_json(), self.__path)
        except ValueError as exc:
            return (None, str(exc))
        over = recipes.budget_problem(identity)
        return (None, over) if over else (identity, "")

    def __revalidate(self) -> None:
        """Show the loader's refusal in the banner AND beside the field it
        named.
        """
        _identity, refusal = self.__judge()
        self.__show_problem(refusal)
        field = ""
        found = FIELD_RX.search(refusal)
        if found:
            field = found.group(1)
        # Only a refusal that names ONE part marks a swatch. A `colours`
        # refusal is about the SET -- an unused part, a missing one -- and
        # names every part it wanted, so matching those names here would
        # paint the same sentence onto every row and say nothing. That one
        # goes to the banner, where a sentence about the set belongs.
        for part, swatch in self.__swatches.items():
            swatch.set_refused(refusal if field == f"colours.{part}" else "")
        self.__mark(self.__tags, refusal if field == "tags" else "")
        self.__mark(self.__anchor, refusal if field == "anchor" else "")

    def __mark(self, widget, refusal: str) -> None:
        """Mark one control with a refusal, or clear it with ""."""
        widget.setStyleSheet(theme.PROBLEM_STYLE if refusal else "")
        widget.setToolTip(refusal)

    def __show_problem(self, refusal: str) -> None:
        """Put the refusal in the banner, with the file's own refusal under
        it.
        """
        text = refusal
        if self.__file_problem and self.__file_problem != refusal:
            note = (f"the file on disk is refused as well: "
                    f"{self.__file_problem}")
            text = f"{text}\n\n{note}" if text else note
        self.__problem.setText(text)
        self.__problem.setVisible(bool(text))

    # -- the bodies that come and go ---------------------------------------

    def __clear(self, layout) -> None:
        """Empty `layout`, obeying law 12.

        A child is reparented to THIS pane and hidden -- never
        `setParent(None)`, which promotes it to a top-level window -- and
        freed with `deleteLater()`, never synchronously, because a
        control's own signal may still be on the stack.
        """
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)
                widget.hide()
                widget.deleteLater()

    def __rebuild_colours(self) -> None:
        """One row per part these garments draw -- a swatch, or the missing
        note.
        """
        wanted = self.parts()
        self.__clear(self.__colour_layout)
        self.__swatches = {}
        for part in wanted:
            if part in self.__colours:
                swatch = ColourSwatch(part, self.__colours[part],
                                      self.__colour_box)
                swatch.colour_picked.connect(self.__colour_picked)
                self.__swatches[part] = swatch
                self.__colour_layout.addRow(part, swatch)
                continue
            missing = QLabel(
                f"{MISSING} -- {part} is drawn by these garments and this "
                f"file has never coloured it", self.__colour_box)
            missing.setWordWrap(True)
            missing.setStyleSheet(theme.LOCKED_STYLE)
            self.__colour_layout.addRow(part, missing)
        self.__colour_box.setTitle(
            f"Colours -- {', '.join(wanted)}"
            if wanted else "Colours")

    def __rebuild_chips(self) -> None:
        """One chip per tag the anchor may legally use, read off the Tags
        line.
        """
        tags = tuple(tag.strip() for tag in self.__tags.text().split(",")
                     if tag.strip())
        if tags == self.__chip_tags and self.__chips:
            self.__sync_chips()
            return
        self.__chip_tags = tags
        self.__clear(self.__chip_layout)
        self.__chips = []
        for index, tag in enumerate(tags):
            chip = QPushButton(tag, self.__chip_box)
            chip.setCheckable(True)
            chip.setToolTip(f"put {tag!r} in the anchor, or take it out; the "
                            f"anchor repeats a tag of Tags verbatim and adds "
                            f"none")
            chip.clicked.connect(self.__chip_toggled)
            self.__chips.append(chip)
            self.__chip_layout.addWidget(chip, index // self.CHIP_COLUMNS,
                                         index % self.CHIP_COLUMNS)
        self.__sync_chips()

    def __sync_chips(self) -> None:
        """Tick the chips the anchor already carries, without re-emitting."""
        anchor = [tag.strip() for tag in self.__anchor.text().split(",")
                  if tag.strip()]
        for chip in self.__chips:
            was = chip.blockSignals(True)
            try:
                chip.setChecked(chip.text() in anchor)
            finally:
                chip.blockSignals(was)

    def __chip_toggled(self, _checked: bool = False) -> None:
        """Write the ticked chips back into the anchor line."""
        wanted = [chip.text() for chip in self.__chips if chip.isChecked()]
        self.__anchor.setText(", ".join(wanted))

    # -- the init preview --------------------------------------------------

    def __draw_preview(self) -> None:
        """Start one drawing, if the loader accepts the form. Never blocks."""
        identity, refusal = self.__judge()
        if identity is None:
            self.__preview_busy = False
            self.__preview.clear()
            self.__preview_note.setStyleSheet(theme.PROBLEM_STYLE)
            self.__preview_note.setText(
                "the init is not drawn while the loader refuses the file: "
                + refusal.splitlines()[0])
            self.__grid.set_markers(())
            self.__grid_note.setText("")
            return
        if self.__preview_temp is None:
            # A TemporaryDirectory, not a bare mkdtemp: every window
            # session used to leave one behind for good, with a strip PNG
            # in it. This one is torn down by `closeEvent`, and by its own
            # finalizer if the process dies without one.
            self.__preview_temp = tempfile.TemporaryDirectory(
                prefix="pyoneer_nai_ui_")
            self.__preview_dir = self.__preview_temp.name
        self.__preview_token += 1
        out = os.path.join(self.__preview_dir,
                           f"{self.__name}_{self.recipe()}_init.png")
        self.__preview_note.setStyleSheet(theme.CAPTION_STYLE)
        self.__preview_note.setText(f"drawing {self.recipe()} ...")
        self.__preview_busy = True
        QThreadPool.globalInstance().start(_PreviewTask(
            self.__preview_signals, self.__preview_token, identity,
            self.recipe(), out))

    def __preview_done(self, token: int, path: str, refusal: str,
                       centers) -> None:
        """A drawing came back: show it, or say why it could not be drawn."""
        if token != self.__preview_token:
            return
        self.__preview_busy = False
        if refusal:
            self.__preview.clear()
            self.__preview_note.setStyleSheet(theme.PROBLEM_STYLE)
            self.__preview_note.setText(
                f"the mannequin refused to draw this outfit: {refusal}")
            self.__grid.set_markers(())
            self.__grid_note.setText("")
            return
        self.__preview.show_png(path)
        self.__preview_note.setStyleSheet(theme.CAPTION_STYLE)
        self.__preview_note.setText(
            f"{self.recipe()}: what `render` draws, and what the model is "
            f"handed. Drawn here, in this window, from "
            f"mannequin.render_init -- no network.")
        markers = tuple((x, y, str(i)) for i, (x, y) in enumerate(centers))
        if markers:
            self.__grid.set_label(markers[0][2])
            self.__grid.set_markers(markers)
            self.__grid.set_center(markers[0][0], markers[0][1])
        else:
            self.__grid.set_markers(markers)
        self.__grid_note.setText(
            "Character Positions, derived: every frame's centre on NovelAI's "
            "5x5 grid, computed by mannequin.render_init from what it drew. "
            + ", ".join(f"frame {i} ({x}, {y})"
                        for i, (x, y) in enumerate(centers)))
