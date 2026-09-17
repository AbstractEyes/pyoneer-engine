"""The shared parts: one command value, and six widgets that carry no policy.

OWNER: this module is the vocabulary the three panes speak, as
`tools.nai.model` is for the pipeline. It imports `tools.nai.model` for the
position grid and the free-tier numbers, and `tools.nai.characters` for the
two spellings of a COLOUR that already live there -- `HEX_RX`, the format,
and `SHADES`, the factors the mannequin draws a colour at and the words for
what each one paints. It imports nothing else from `tools.nai`, so a widget
can never be the place a limit is re-decided, and the format of a colour is
not spelled twice.

WHAT LIVES HERE
---------------
    NaiCommand      one `python -m tools.nai ...` invocation, as data
    ColourSwatch    one `#RRGGBB` of a character part, clickable
    PositionGrid    NovelAI's 5x5 character-position picker
    LockedField     a control the free-tier guard forbids, greyed, with the
                    reason visible
    CommandBox      the exact command line, read-only and selectable
    ImageView       a PNG on disk, fitted, with its path and sha256 under it
    field_row       one labelled row, the editor's QFormLayout idiom

THE RULES EVERY WIDGET HERE OBEYS
---------------------------------
* NO WIDGET SENDS ANYTHING. Nothing here opens a socket, spawns a process
  or writes a file. A widget emits; a pane decides.
* NO WIDGET RE-DECIDES A LIMIT. `PositionGrid`'s five values ARE
  `model.GRID`; `LockedField`'s reasons are handed to it by
  `request_pane.NAI_FIELDS`. A number typed into this module is a second
  spelling of a rule that lives in `tools.nai.model`, and
  `tools/check_nai_ui.py` compares the two.
* NO WIDGET JUDGES A VALUE. `ColourSwatch.set_refused` and
  `PositionGrid.set_markers` are TOLD what is wrong -- by the pane, which
  was told by the loader. A widget that decided for itself whether a
  colour is legal would be the second copy of a rule, which is the sibling
  route CLAUDE.md's ACTIVE WARNINGS name. The one thing a widget does
  judge is a FORMAT: `#RRGGBB`, and a coordinate that is on `model.GRID`.
* NOTHING HERE READS AN ENVIRONMENT VARIABLE. In particular, nothing reads
  the key, and no widget may be given its value to display, disable
  against, or hash.
* LAW 12: a widget that swaps its body uses `takeWidget()` ->
  `setParent(self)` -> `hide()` -> `deleteLater()` -> `setWidget(new)`.
  `setParent(None)` appears nowhere in this package; the check asserts it.
"""
from __future__ import annotations

import hashlib
import os
import shlex
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QColorDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from tools.nai import model
from tools.nai.characters import HEX_RX, SHADES
from tools.nai_ui import theme


def quote_argv(parts) -> str:
    """`parts` as ONE command line that re-splits into exactly `parts`.

    The platform's own rule, because the point of the line is that it can
    be pasted into a shell at the repo root and run the same command:

    * POSIX -- `shlex.quote` per element, which `shlex.split` inverts.
    * Windows -- the MS C runtime rule `CommandLineToArgvW` parses and
      `subprocess.list2cmdline` writes: a backslash run before a double
      quote doubles, an embedded double quote is escaped with a backslash,
      and an element that is empty or holds a space or a tab is wrapped.
      Written out here rather than imported, because `subprocess` is
      spelled in exactly one module of this package (`run_pane`) and
      `tools/check_nai_ui.py` asserts that -- so the check compares this
      function against `list2cmdline` instead, which makes the two
      independent spellings of one rule prove each other.

    This does no redaction and drops nothing: an argv this package builds
    never carries a credential.
    """
    parts = [str(part) for part in parts]
    if os.name != "nt":
        return " ".join(shlex.quote(part) for part in parts)
    out = []
    for part in parts:
        wrap = (not part) or (" " in part) or ("\t" in part)
        chunk = ['"'] if wrap else []
        slashes = 0
        for char in part:
            if char == "\\":
                slashes += 1
            elif char == '"':
                chunk.append("\\" * (slashes * 2 + 1))
                slashes = 0
            else:
                chunk.append("\\" * slashes)
                slashes = 0
            if char != "\\":
                chunk.append(char)
        if wrap:
            chunk.append("\\" * (slashes * 2))
            chunk.append('"')
        else:
            chunk.append("\\" * slashes)
        out.append("".join(chunk))
    return " ".join(out)


@dataclass(frozen=True)
class NaiCommand:
    """One `python -m tools.nai ...` invocation, as data, before it runs.

    `argv` is COMPLETE and literal -- interpreter first, then `-m`,
    `tools.nai`, the subcommand and its flags -- so `run_pane` never
    assembles anything and `CommandBox` shows exactly what will run. It is
    a tuple so a command cannot be edited after it was shown.

    `sends` is True for a subcommand that opens a socket (`run`, `infill`,
    `probe`, `account`). `RunPane` refuses to start a sending command that
    was not armed by the human, and `app.NaiWindow` colours it.

    `blocked` is the reason this command cannot run as it stands -- an
    offline guard condition `plan` already failed, a `--from` file that is
    not there, a required field left empty -- or "" when it can. A blocked
    command is still SHOWN, because seeing the line you cannot run yet is
    the point of a composer.

    `cwd` is the repository root the child runs in.
    """

    argv: tuple[str, ...]
    sends: bool
    blocked: str = ""
    cwd: str = ""

    def text(self) -> str:
        """The command line as one string, for `CommandBox` and the clipboard.

        The interpreter is printed as the repo-relative
        `.venv/Scripts/python.exe` when `argv[0]` is inside `cwd`, so the
        line matches docs/NAI_SPRITES.md and can be pasted into a shell at
        the repo root. NOTHING is elided and nothing is redacted, because
        nothing secret is ever in an argv this package builds.

        THE LINE RE-SPLITS INTO THE ARGV. Quoting is `quote_argv`'s, which
        is the platform's own rule, not a bare pair of double quotes around
        anything with a space in it. `--phase`, `--lever`, `--from` and the
        strip path are free-text fields: a value spelling `x" --steps 99
        "y` used to render as a line carrying a `--steps 99` that no argv
        element contained, so the box -- and the Copy button -- showed a
        DIFFERENT command from the one that ran. The box is the promise
        this whole window rests on, and a promise that is only usually true
        is not one.

        ValueError for an empty `argv`: a command line with no command is
        not a shorter command line, it is a bug (law 7).
        """
        if not self.argv:
            raise ValueError("a NaiCommand with no argv has no command line; "
                             "an argv holds the interpreter, -m, tools.nai "
                             "and a subcommand at least")
        parts = list(self.argv)
        if self.cwd:
            head = os.path.normpath(parts[0])
            root = os.path.normpath(self.cwd) + os.sep
            if head.startswith(root):
                parts[0] = head[len(root):].replace(os.sep, "/")
        return quote_argv(parts)

    def runnable(self) -> bool:
        """True when `blocked` is empty. The ONE place that question is asked."""
        return not self.blocked


class _Chip(QFrame):
    """One flat rectangle of colour, bordered so a pale colour still reads.

    `clicked` is a real Signal and `mouseReleaseEvent` a real override:
    PySide6 dispatches a virtual through the CLASS, so a handler assigned
    onto an instance would simply never be called.
    """

    clicked = Signal()

    def __init__(self, side: int, parent=None) -> None:
        """A `side` x `side` chip, painted the key grey until `set_rgb`."""
        super().__init__(parent)
        self.setFixedSize(side, side)
        self.setFrameShape(QFrame.NoFrame)
        self.set_rgb(model.BACKGROUND_RGB)

    def set_rgb(self, rgb: tuple[int, int, int]) -> None:
        """Repaint to `rgb`."""
        self.setStyleSheet(f"background: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); "
                           f"border: 1px solid palette(mid);")

    def mouseReleaseEvent(self, event) -> None:       # noqa: N802 (Qt's spelling)
        """Emit `clicked` for a left button release."""
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


def _hex(rgb: tuple[int, int, int]) -> str:
    """(r, g, b) as upper-case `#RRGGBB`, the spelling a character file uses."""
    return "#%02X%02X%02X" % tuple(rgb)


class ColourSwatch(QWidget):
    """One character part's colour: its name, its `#RRGGBB`, and a chip.

    Clicking the chip opens `QColorDialog` and emits `colour_picked(str,
    str)` -- (part, "#RRGGBB") -- upper-case hex, which is how a character
    file spells it. The hex is typable too, for a colour that came out of a
    palette somewhere else; a string that is not yet `#RRGGBB` emits
    nothing and marks the box, because half a colour is not a colour and
    law 7 forbids reading it as one.

    The swatch does NOT judge the colour: the key-distance and shade rules
    (`characters.MIN_KEY_DISTANCE`, `characters.MIN_SHADE_KEY_DISTANCE`)
    are the loader's, and `CharacterPane` hands the loader's own refusal
    back to `set_refused`. What the swatch DOES show is the two shades the
    mannequin will draw from it (`model.FAR_SHADE`, `model.INNER_SHADE`,
    read off `characters.SHADES` together with the words for what each one
    paints) as two smaller chips beside the main one, so a colour whose far
    leg would be keyed out is visible before the file is saved.

    Signals:
        colour_picked(str, str)     (part, "#RRGGBB")
    """

    colour_picked = Signal(str, str)

    def __init__(self, part: str, hex_colour: str, parent=None) -> None:
        """One swatch for `part` at `hex_colour` (either case, `#RRGGBB`).

        ValueError, naming the part, for a string that is not six hex
        digits behind a `#` -- law 7: a bad colour is not drawn as black.
        """
        super().__init__(parent)
        self.__part = str(part)
        self.__colour = self.__judge_format(hex_colour)
        self.__refusal = ""
        self.__loading = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.__chip = _Chip(26, self)
        self.__chip.setCursor(Qt.PointingHandCursor)
        self.__chip.clicked.connect(self.__chip_clicked)
        row.addWidget(self.__chip)

        self.__shades: list[_Chip] = []
        for _factor, _drawn in SHADES:
            chip = _Chip(13, self)
            self.__shades.append(chip)
            row.addWidget(chip)

        self.__hex = QLineEdit(self)
        self.__hex.setMaxLength(7)
        self.__hex.setFixedWidth(82)
        self.__hex.setStyleSheet(theme.MONO_STYLE)
        self.__hex.textChanged.connect(self.__typed)
        row.addWidget(self.__hex)

        self.__note = QLabel(self)
        self.__note.setWordWrap(True)
        self.__note.setStyleSheet(theme.CAPTION_STYLE)
        row.addWidget(self.__note, 1)

        self.set_colour(self.__colour)

    # -- reading -----------------------------------------------------------

    def part(self) -> str:
        """The part this swatch paints -- one of `model.PARTS`."""
        return self.__part

    def colour(self) -> str:
        """The current colour, upper-case `#RRGGBB`."""
        return self.__colour

    def rgb(self) -> tuple[int, int, int]:
        """The current colour as (r, g, b), the triple the loader judges."""
        text = self.__colour
        return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))

    def refusal(self) -> str:
        """The loader's refusal for this part, or "" while it has none."""
        return self.__refusal

    def shade_text(self) -> str:
        """The two shades the mannequin will draw, as one line of hex."""
        return "  ".join(f"x{factor:g} {_hex(model.shade(self.rgb(), factor))}"
                         for factor, _drawn in SHADES)

    # -- writing -----------------------------------------------------------

    def set_colour(self, hex_colour: str) -> None:
        """Repaint to `hex_colour`; emits nothing (this is the model talking)."""
        self.__colour = self.__judge_format(hex_colour)
        self.__loading = True
        try:
            self.__hex.setText(self.__colour)
        finally:
            self.__loading = False
        self.__repaint()

    def set_refused(self, reason: str) -> None:
        """Mark this swatch with the LOADER's refusal, or clear it with "".

        The sentence is written by `tools.nai.characters`, handed down by
        `CharacterPane`, and shown here verbatim -- under the chips and as
        the tooltip. The swatch decides nothing: it is told.
        """
        self.__refusal = str(reason)
        if self.__refusal:
            self.__hex.setStyleSheet(theme.MONO_STYLE + theme.PROBLEM_STYLE)
            self.__note.setStyleSheet(theme.PROBLEM_STYLE)
            self.__note.setText(self.__refusal)
        else:
            self.__hex.setStyleSheet(theme.MONO_STYLE)
            self.__note.setStyleSheet(theme.CAPTION_STYLE)
            self.__note.setText(self.shade_text())
        self.__hex.setToolTip(self.__refusal)
        self.__note.setToolTip(self.__note.text())

    # -- internals ---------------------------------------------------------

    def __judge_format(self, hex_colour: object) -> str:
        """`hex_colour` upper-cased; ValueError naming the part when it is
        not `#RRGGBB`.
        """
        if not isinstance(hex_colour, str) or not HEX_RX.fullmatch(hex_colour):
            raise ValueError(f"the colour of part {self.__part!r} is "
                             f"{hex_colour!r}, which is not a '#RRGGBB' hex "
                             f"colour")
        return hex_colour.upper()

    def __repaint(self) -> None:
        """Repaint the three chips and the shade line from the current
        colour.
        """
        rgb = self.rgb()
        self.__chip.set_rgb(rgb)
        self.__chip.setToolTip(f"{self.__part}: {self.__colour}")
        for chip, (factor, drawn) in zip(self.__shades, SHADES):
            shaded = model.shade(rgb, factor)
            chip.set_rgb(shaded)
            chip.setToolTip(f"x{factor:g} {_hex(shaded)}, {drawn}")
        if not self.__refusal:
            self.__note.setText(self.shade_text())
            self.__note.setToolTip(self.__note.text())

    def __typed(self, text: str) -> None:
        """A hex typed by hand: emit for a whole `#RRGGBB`, mark the box for
        anything less.
        """
        if self.__loading:
            return
        if not HEX_RX.fullmatch(text):
            self.__hex.setStyleSheet(theme.MONO_STYLE + theme.LOCKED_STYLE)
            self.__hex.setToolTip("a colour is '#RRGGBB': a '#' and six hex "
                                  "digits. Nothing is read from a partial "
                                  "one.")
            return
        self.__colour = text.upper()
        self.set_refused("")
        self.__repaint()
        self.colour_picked.emit(self.__part, self.__colour)

    def __chip_clicked(self) -> None:
        """Open the colour dialog on the chip, and emit what comes back."""
        chosen = QColorDialog.getColor(QColor(self.__colour), self,
                                       f"the {self.__part} colour")
        if chosen.isValid():
            self.set_colour(chosen.name().upper())
            self.colour_picked.emit(self.__part, self.__colour)


class PositionGrid(QWidget):
    """NovelAI's character-position picker, at V4.5's 5x5.

    CONFIRMED against docs.novelai.net/en/image/multiplecharacters: "The V4
    and V4.5 models are limited to a 5x5 grid for custom character
    positioning"; the choice between letting the model place a character
    and placing it yourself is the site's "AI's Choice" / "Custom" pair,
    and the picker opens from a Character Positions button.

    Ours are the same five values, `model.GRID` == (0.1, 0.3, 0.5, 0.7,
    0.9), and the widget stores nothing else: a click sets (x, y) to the
    centre of the cell clicked, which is already a GRID value, so
    `model.snap` is never needed and a near-miss centre cannot exist.

    OURS IS READ-ONLY BY DEFAULT. Our centres are DERIVED, not typed:
    `mannequin.render_init` returns them from the drawn bounding boxes and
    `recipes.frames_for` puts them on the wire. The grid therefore renders
    the derived cell filled and the rest empty, with `editable=False`, and
    `request_pane` labels it derived. `editable=True` exists for one use
    only: showing what a hand-placed centre WOULD be, beside the derived
    one, without changing the command.

    EVERY FRAME AT ONCE. `set_markers` paints the whole strip's centres on
    every grid, so a reader sees the layout rather than one cell of it; and
    with `distinct` -- which is the rule `mannequin.render_init` enforces
    by RAISING, "frames {j} and {i} both snap to {center}" -- a cell
    another frame holds cannot be picked. The refusal is a signal, never a
    silence.

    Signals:
        cell_picked(float, float)   (x, y), both `model.GRID` values;
                                    emitted only when `editable`
        cell_refused(str)           why that cell could not be taken
    """

    cell_picked = Signal(float, float)
    cell_refused = Signal(str)

    def __init__(self, x: float, y: float, *, editable: bool = False,
                 parent=None) -> None:
        """A 5x5 grid with (`x`, `y`) filled.

        ValueError when either coordinate is not exactly a `model.GRID`
        value (`model.on_grid`): an off-grid centre is a bug upstream, not
        a value to snap here.
        """
        super().__init__(parent)
        self.__center = self.__judge(x, y)
        self.__editable = bool(editable)
        self.__markers: tuple[tuple[float, float, str], ...] = ()
        self.__distinct = True
        self.__label = ""
        side = 21 * len(model.GRID)
        self.setMinimumSize(QSize(side, side))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor if self.__editable
                       else Qt.ArrowCursor)
        self.setToolTip(self.__tooltip())

    # -- reading -----------------------------------------------------------

    def center(self) -> tuple[float, float]:
        """The filled cell as (x, y), both `model.GRID` values."""
        return self.__center

    def editable(self) -> bool:
        """True when a click moves the filled cell.

        False by default: our centres are derived by
        `mannequin.render_init`, never typed.
        """
        return self.__editable

    def markers(self) -> tuple[tuple[float, float, str], ...]:
        """Every centre this grid draws, as ((x, y, label), ...)."""
        return self.__markers

    def label(self) -> str:
        """The name of this grid's own frame, or "" when it has none."""
        return self.__label

    def taken_by(self, x: float, y: float) -> str:
        """Which OTHER frame holds (`x`, `y`), or "" when none does."""
        return self.__taken(self.__judge(x, y))

    # -- writing -----------------------------------------------------------

    def set_center(self, x: float, y: float) -> None:
        """Move the filled cell; emits nothing. Same ValueError as __init__.

        ValueError naming the other frame when `distinct` and that cell is
        already a marker's -- the rule `mannequin.render_init` raises on.
        """
        center = self.__judge(x, y)
        taken = self.__taken(center)
        if taken and self.__distinct:
            raise ValueError(self.__collision(center, taken))
        self.__center = center
        self.setToolTip(self.__tooltip())
        self.update()

    def set_markers(self, markers, *, distinct: bool = True) -> None:
        """Paint every frame's centre; `markers` is ((x, y, label), ...).

        `distinct` True refuses a pick on a cell another marker holds,
        which is what `mannequin.render_init` does by raising. A marker on
        this grid's own centre is this grid's own frame and blocks nothing.
        ValueError for a coordinate off `model.GRID`, or for a marker that
        is not an (x, y, label) triple.
        """
        rows: list[tuple[float, float, str]] = []
        for marker in markers:
            fields = tuple(marker)
            if len(fields) != 3:
                raise ValueError(f"a marker is (x, y, label), got {marker!r}")
            point = self.__judge(fields[0], fields[1])
            rows.append((point[0], point[1], str(fields[2])))
        self.__markers = tuple(rows)
        self.__distinct = bool(distinct)
        self.setToolTip(self.__tooltip())
        self.update()

    def set_label(self, label: str) -> None:
        """Name this grid's own frame, so its marker reads as its own."""
        self.__label = str(label)
        self.setToolTip(self.__tooltip())
        self.update()

    # -- internals ---------------------------------------------------------

    def __judge(self, x: object, y: object) -> tuple[float, float]:
        """(x, y) as floats; ValueError naming the coordinate that is off
        `model.GRID`.
        """
        for name, value in (("x", x), ("y", y)):
            if not model.on_grid(value):
                raise ValueError(
                    f"{name}={value!r} is not a centre this model can take: "
                    f"V4.5 places a character on the 5x5 grid {model.GRID}, "
                    f"and an off-grid centre is a bug upstream, not a value "
                    f"to snap here")
        return (float(x), float(y))

    def __taken(self, center: tuple[float, float]) -> str:
        """The label of the OTHER frame holding `center`, or ""."""
        for x, y, label in self.__markers:
            if label and label == self.__label:
                continue                 # this grid's own frame holds nothing
            if (x, y) == center and (x, y) != self.__center:
                return label or "another frame"
        return ""

    def __collision(self, center: tuple[float, float], taken: str) -> str:
        """The one sentence this widget says about two frames on one cell."""
        return (f"({center[0]}, {center[1]}) is already {taken}'s cell, and "
                f"two frames that snap to one centre are refused when the "
                f"strip is drawn")

    def __tooltip(self) -> str:
        """This grid in one line: whose cell, which centre, derived or
        clickable.
        """
        who = f"{self.__label}: " if self.__label else ""
        how = "click to move it" if self.__editable else "derived, read-only"
        return (f"{who}({self.__center[0]}, {self.__center[1]}) on NovelAI's "
                f"5x5 grid -- {how}")

    def paintEvent(self, event) -> None:              # noqa: N802 (Qt's spelling)
        """Draw the 5x5 cells: this frame's filled, every other frame's shaded."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        mid = self.palette().mid().color()
        highlight = self.palette().highlight().color()
        count = len(model.GRID)
        side = min(self.width(), self.height()) / count
        font = painter.font()
        font.setPointSizeF(max(6.0, side * 0.36))
        painter.setFont(font)
        for row in range(count):
            for column in range(count):
                left, top = int(column * side), int(row * side)
                box = (left, top, int(side), int(side))
                center = (model.GRID[column], model.GRID[row])
                mine = center == self.__center
                taken = self.__taken(center)
                if mine:
                    painter.fillRect(left + 1, top + 1, int(side) - 2,
                                     int(side) - 2, highlight)
                elif taken:
                    shaded = QColor(mid)
                    shaded.setAlpha(70)
                    painter.fillRect(left + 1, top + 1, int(side) - 2,
                                     int(side) - 2, shaded)
                painter.setPen(QPen(mid, 1))
                painter.drawRect(*box)
                text = self.__label if mine else taken
                if text:
                    painter.setPen(QPen(
                        self.palette().highlightedText().color() if mine
                        else self.palette().windowText().color(), 1))
                    painter.drawText(left, top, int(side), int(side),
                                     Qt.AlignCenter, text)
        painter.end()

    def mouseReleaseEvent(self, event) -> None:       # noqa: N802 (Qt's spelling)
        """Pick the cell under the cursor, when this grid is editable."""
        if not self.__editable or event.button() != Qt.LeftButton:
            return
        count = len(model.GRID)
        side = min(self.width(), self.height()) / count
        column = int(event.position().x() // side)
        row = int(event.position().y() // side)
        if not (0 <= column < count and 0 <= row < count):
            return
        center = (model.GRID[column], model.GRID[row])
        taken = self.__taken(center)
        if taken and self.__distinct:
            self.cell_refused.emit(self.__collision(center, taken))
            return
        self.__center = center
        self.setToolTip(self.__tooltip())
        self.update()
        self.cell_picked.emit(center[0], center[1])


VALUE_KEEPS_ITS_WIDTH = "nai_ui_value"
"""The dynamic property a `LockedField`'s VALUE label wears.

`request_pane.fix_wrapped_labels` makes every wrapped label
`QSizePolicy.Ignored` across so twenty captions cannot demand a window
nobody has -- and a label that asks for nothing, in a row beside one that
asks for everything, is drawn at zero width. The value of a locked control
is the one thing that row exists to show, so it is exempt, by this
property rather than by the pane guessing at a type."""


class LockedField(QWidget):
    """A control the free-tier guard forbids: shown, greyed, and explained.

    SHOWN AND LOCKED, NEVER HIDDEN. A reader has to be able to see where
    the free allowance ends, so the row keeps NovelAI's own label and its
    real value, renders non-editable under `theme.LOCKED_STYLE`, and
    carries `reason` as visible text beside it AND as the tooltip --
    visible text first, because a tooltip is not on a screenshot.

    `reason` is a sentence from `request_pane.NAI_FIELDS`, e.g. "Opus tier:
    28 steps max", "one sample", "<= 1,048,576 px", "V5 draws on the usage
    battery". THERE IS NO FREE TIER: the 28-step allowance is an Opus
    subscription benefit (docs.novelai.net/en/image/stepsguidance), so a
    reason that says "free tier" tells a reader on any other plan that a
    generation is free when every one of theirs costs Anlas. It is never
    composed here.

    The widget is inert: it has no signal, cannot be focused, and its value
    never reaches a `NaiCommand`.
    """

    def __init__(self, label: str, value: str, reason: str,
                 parent=None) -> None:
        """A locked row reading `label`, `value`, `reason`.

        ValueError for an empty `reason`: a control locked without a reason
        is indistinguishable from a bug, which is the whole failure this
        widget exists to prevent.
        """
        super().__init__(parent)
        if not str(reason).strip():
            raise ValueError(f"the locked field {label!r} was given no "
                             f"reason; a control locked without one cannot "
                             f"be told from a control that is broken, and a "
                             f"reader cannot see where the free "
                             f"allowance ends")
        self.__label = str(label)
        self.__reason = str(reason)
        self.setFocusPolicy(Qt.NoFocus)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.__value = QLabel(str(value), self)
        # WRAPPED, and MARKED. The value is the widest unbreakable thing in
        # some of these rows -- "Euler Ancestral (k_euler_ancestral)" alone
        # asked for 415 px -- so it wraps. But it is the THING THE ROW IS
        # FOR, and `request_pane.fix_wrapped_labels` gives a wrapped label
        # `QSizePolicy.Ignored` across, which handed this one nothing and
        # left the lock showing its reason with no value beside it. The
        # property says "this one keeps its width"; the reason beside it is
        # what gives way.
        self.__value.setWordWrap(True)
        self.__value.setProperty(VALUE_KEEPS_ITS_WIDTH, True)
        self.__value.setStyleSheet(theme.LOCKED_STYLE)
        self.__value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.__value, 2)
        self.__why = QLabel(self.__reason, self)
        self.__why.setWordWrap(True)
        self.__why.setStyleSheet(theme.CAPTION_STYLE)
        row.addWidget(self.__why, 3)
        self.setToolTip(f"{self.__label}: {self.__reason}")

    def set_value(self, value: str) -> None:
        """Change the displayed value; the reason and the lock do not move."""
        self.__value.setText(str(value))

    def value(self) -> str:
        """The value shown."""
        return self.__value.text()

    def reason(self) -> str:
        """Why this control is locked -- the sentence, never empty."""
        return self.__reason


class CommandBox(QWidget):
    """The exact command line, read-only, selectable, copyable.

    This is the promise the whole window rests on: what is in this box is
    what will run, character for character. So it is a real text control
    (selectable, Ctrl+C, and a Copy button) rather than a label, it is
    `setReadOnly(True)` rather than disabled -- a disabled control greys the
    text it exists to let you read -- and it wraps rather than scrolls
    sideways.

    A blocked command is shown in full with its `blocked` reason under it,
    in `theme.PROBLEM_STYLE`. A sending command is shown with
    `theme.BANNER_STYLE` and the words this window uses for it, "this opens
    a socket", so the two kinds never look alike.

    Signals:
        copy_requested()    the Copy button was pressed
    """

    copy_requested = Signal()

    SOCKET = "this opens a socket"
    """What this window calls a command that sends. One spelling, here."""

    OFFLINE = "no network: nothing leaves this machine"
    """What this window calls a command that does not send."""

    EMPTY = "nothing composed yet"
    """What the box says before the first `set_command`."""

    def __init__(self, parent=None) -> None:
        """An empty box. `set_command` fills it."""
        super().__init__(parent)
        self.__command: NaiCommand | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.__kind = QLabel(self.EMPTY, self)
        self.__kind.setWordWrap(True)
        self.__kind.setStyleSheet(theme.CAPTION_STYLE)
        column.addWidget(self.__kind)

        self.__text = QPlainTextEdit(self)
        self.__text.setReadOnly(True)
        self.__text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.__text.setStyleSheet(theme.MONO_STYLE)
        self.__text.setFixedHeight(74)
        column.addWidget(self.__text)

        self.__blocked = QLabel(self)
        self.__blocked.setWordWrap(True)
        self.__blocked.setStyleSheet(theme.PROBLEM_STYLE)
        self.__blocked.hide()
        column.addWidget(self.__blocked)

        self.__copy = QPushButton("Copy", self)
        self.__copy.setToolTip(
            "Copy this line to the clipboard. It is the whole command and "
            "it re-splits into the argv that runs, so it can be pasted "
            "into a shell at the repo root.")
        self.__copy.clicked.connect(self.copy_requested.emit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.__copy)
        column.addLayout(row)

    def set_command(self, command: NaiCommand) -> None:
        """Show `command.text()`, its kind, and its `blocked` reason if any."""
        self.__command = command
        self.__text.setPlainText(command.text())
        self.__kind.setText(self.SOCKET if command.sends else self.OFFLINE)
        self.__kind.setStyleSheet(theme.BANNER_STYLE if command.sends
                                  else theme.CAPTION_STYLE)
        if command.runnable():
            self.__blocked.setText("")
            self.__blocked.hide()
        else:
            self.__blocked.setText(command.blocked)
            self.__blocked.show()

    def command(self) -> NaiCommand | None:
        """The command shown, or None before the first `set_command`."""
        return self.__command

    def text(self) -> str:
        """The line as it is shown, for a check and for a reader's eye."""
        return self.__text.toPlainText()


class ImageView(QWidget):
    """One PNG on disk, fitted to the pane, with its path and sha256 under it.

    Shows what `render` drew, what `run` returned, or what `pixelize`
    wrote. It reads the file at the path it is given and NOTHING else: it
    never searches, never guesses a sibling, and never caches, so an
    `--out` written twice shows the second one.

    A missing or unreadable file is shown as that sentence in
    `theme.PROBLEM_STYLE`, naming the path -- law 7: no placeholder image,
    because a flat grey rectangle is exactly what a correct mannequin init
    looks like and a reader could not tell them apart.

    The sha256 under the image is the one the CLI prints (`render` prints
    `png sha256`), so the two can be compared by eye.

    Signals:
        reveal_requested(str)       the path, for the file manager
    """

    reveal_requested = Signal(str)

    EMPTY = "nothing drawn yet"
    """What the view says before any PNG has been shown."""

    def __init__(self, parent=None) -> None:
        """An empty view reading "nothing drawn yet"."""
        super().__init__(parent)
        self.__path = ""
        self.__pixmap: QPixmap | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.__image = QLabel(self.EMPTY, self)
        self.__image.setAlignment(Qt.AlignCenter)
        # 48, not 110. Three stacked views in the run pane put the
        # window's own minimum height at 858, and a 768-pixel screen could
        # not open it. The pixmap is scaled to whatever the pane has, so
        # this number buys nothing but a taller window.
        self.__image.setMinimumHeight(48)
        self.__image.setStyleSheet(theme.CAPTION_STYLE)
        self.__image.setWordWrap(True)
        # The width hint is ignored here as well: a missing-file message
        # NAMES the path, a path is one unbreakable word, and a label left
        # to ask would widen the whole window to fit the file that is not
        # there. The pixmap is scaled to whatever width the pane has.
        self.__image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.__image.setMinimumWidth(1)
        column.addWidget(self.__image, 1)

        self.__caption = QLabel("", self)
        self.__caption.setWordWrap(True)
        self.__caption.setStyleSheet(theme.CAPTION_STYLE + theme.MONO_STYLE)
        self.__caption.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # A path and a sha256 are ONE WORD each, and word wrap cannot break
        # a word: left to ask, this label would make the whole pane as wide
        # as the longest path it ever showed. Its width hint is ignored and
        # it takes whatever the pane has.
        self.__caption.setSizePolicy(QSizePolicy.Ignored,
                                     QSizePolicy.Preferred)
        self.__caption.setMinimumWidth(1)
        column.addWidget(self.__caption)

        self.__reveal = QPushButton("Show the file", self)
        self.__reveal.setToolTip(
            "Open the PNG shown above in the system viewer. Enabled once a "
            "command has written one; nothing has been written yet.")
        self.__reveal.setEnabled(False)
        self.__reveal.clicked.connect(self.__reveal_clicked)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.__reveal)
        column.addLayout(row)

    def show_png(self, path: str) -> None:
        """Load and fit the PNG at `path`; show its path and sha256 under it."""
        self.__path = str(path)
        self.__pixmap = None
        try:
            with open(self.__path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            self.__fail(f"{self.__path} cannot be read: {exc}")
            return
        pixmap = QPixmap()
        if not raw or not pixmap.loadFromData(raw, "PNG"):
            self.__fail(f"{self.__path} is {len(raw)} bytes that are not a "
                        f"PNG this window can draw")
            return
        self.__pixmap = pixmap
        self.__image.setStyleSheet(theme.CAPTION_STYLE)
        self.__reveal.setEnabled(True)
        self.__caption.setText(f"{self.__path}\npng sha256    "
                               f"{hashlib.sha256(raw).hexdigest()}")
        self.__fit()

    def clear(self) -> None:
        """Back to "nothing drawn yet"; forgets the path."""
        self.__path = ""
        self.__pixmap = None
        self.__image.setPixmap(QPixmap())
        self.__image.setText(self.EMPTY)
        self.__image.setStyleSheet(theme.CAPTION_STYLE)
        self.__caption.setText("")
        self.__reveal.setEnabled(False)

    def path(self) -> str:
        """The path shown, or "" when empty."""
        return self.__path

    def caption(self) -> str:
        """The path and sha256 under the image, or "" when empty."""
        return self.__caption.text()

    def __reveal_clicked(self) -> None:
        """Emit the path, once there is one."""
        if self.__path:
            self.reveal_requested.emit(self.__path)

    def __fail(self, message: str) -> None:
        """Say why there is no image, in `theme.PROBLEM_STYLE`, and draw
        nothing.
        """
        self.__image.setPixmap(QPixmap())
        self.__image.setText(message)
        self.__image.setStyleSheet(theme.PROBLEM_STYLE)
        self.__caption.setText("")
        self.__reveal.setEnabled(False)

    def __fit(self) -> None:
        """Rescale the held pixmap into the label, keeping its aspect ratio."""
        if self.__pixmap is None:
            return
        area = self.__image.size()
        self.__image.setText("")
        self.__image.setPixmap(self.__pixmap.scaled(
            max(32, area.width()), max(32, area.height()),
            Qt.KeepAspectRatio, Qt.FastTransformation))

    def resizeEvent(self, event) -> None:             # noqa: N802 (Qt's spelling)
        """Refit the PNG. A sprite strip is rescaled with no smoothing."""
        super().resizeEvent(event)
        self.__fit()


def field_row(form, label: str, widget, caption: str = "") -> object:
    """Add one labelled row to `form` (a QFormLayout); return `widget`.

    The editor's idiom, in one function so every pane spells a row the same
    way: the label is plain, `caption` goes under the widget in
    `theme.CAPTION_STYLE`, and an empty `caption` adds no second row at
    all. `label` is NovelAI's own label text wherever one exists -- the
    mapping table is `request_pane.NAI_FIELDS`, which also records whether
    each label was confirmed against docs.novelai.net.
    """
    form.addRow(label, widget)
    if caption:
        note = QLabel(caption)
        note.setWordWrap(True)
        note.setStyleSheet(theme.CAPTION_STYLE)
        form.addRow("", note)
    return widget
