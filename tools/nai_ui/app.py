"""The window: three panes, one command line between them.

Two of the panes are the editors and share a tab stack; the third is the
runner and never moves. The module docstring's LAYOUT section says what a
screenshot taught about why.

OWNER: this module owns the WIRING and nothing else. It builds no argv, it
runs no process, it judges no character file and it holds no limit. Every
one of those lives in the pane that owns it, and this window connects them:

    CharacterPane.character_changed  -> RequestPane.set_character
    CharacterPane.dirty_changed      -> the status bar, and nothing else
    CharacterPane.render_requested   -> compose `render` and run it
    RequestPane.command_changed      -> RunPane.set_command  (which DISARMS)
    RequestPane.plan_requested       -> compose `plan` and run it
    RunPane.command_requested        -> compose that one and run it
    RunPane.refused                  -> the status bar: a control was
                                        pressed and the API refused it, in
                                        its own words. `arm`, `start` and
                                        `interrupt` RAISE -- that is their
                                        contract -- and a Qt slot must not,
                                        because the traceback goes to a
                                        terminal a window launched from a
                                        shortcut does not have
    _blocked_reasons()               -> the window's own buttons AND
                                        RunPane.set_free_blocked, so a line
                                        that cannot run shuts its control
                                        on BOTH routes from one answer
    a window button or menu item     -> RequestPane.command(subcommand)
                                        -> RunPane.set_command

THE LAYOUT -- TWO TABS AND A SPLITTER, AND WHY NOT THREE PANES
--------------------------------------------------------------
A `QSplitter`, left to right:

    a QTabWidget    CharacterPane  who is drawn, what she wears, what
                                   colour, and the init strip as drawn
                    RequestPane    NovelAI's own form -- Prompt, Character
                                   Prompts with their 5x5 position grids
                                   and Undesired Content in the left
                                   column; Model, Image Size, Number of
                                   Images, Steps, Prompt Guidance, Prompt
                                   Guidance Rescale, Sampler, Noise
                                   Schedule, Seed and the Image to Image
                                   group in the right column; the Anlas
                                   line at the bottom
    RunPane         the command box, the arm and send controls, the output
                    view, and the `ImageView` under it

The first draft put all three side by side, and a screenshot killed it.
MEASURED: `RequestPane`'s scrolled body asked for 973 px at its MINIMUM,
because it carried NovelAI's two columns side by side, and `RunPane`'s
minimum was 644. Three panes at once therefore needed 1937 px before the
character pane got a single pixel -- so on a 1920 screen NovelAI's whole
right-hand settings column, the Steps cap and the Seed among it, sat off
the right edge behind a horizontal scrollbar. The one thing the author
asked to be recognisable was the thing that fell off.

So the two EDITORS share a tab stack and the RUNNER never moves: the form
gets the whole left half, and the command line stays on screen while the
buttons that compose it are pressed, which is the design in one sentence.
`setChildrenCollapsible(False)` and the two minimum widths below keep the
splitter from handing a child less than its minimum -- the failure that
makes a wrapped reason draw over the row beneath it.

AND TWO TABS WERE STILL NOT ENOUGH. MEASURED AGAIN, by looking at the
same window on a laptop: below about 1660 px NovelAI's settings column
went behind a horizontal scrollbar anyway, because the two columns inside
the form were pinned beside each other whatever the form's width -- and
the window's own `minimumSizeHint` came out at 1367x838, so a 1366x768
screen could not open it in EITHER dimension. Three things fixed that and
all three are asserted in `tools/check_nai_ui.py` section 18:
`request_pane._Columns` STACKS the two columns below
`request_pane.COLUMN_WIDTH` twice; every caption in the form is
`QSizePolicy.Ignored` across and every `QFormLayout` wraps a long row, so
the form is tall rather than wide; and the controls in this file and in
`run_pane` sit on TWO ROWS rather than one, because seven buttons side by
side were a hard 1338 px minimum by themselves. The window's minimum is
now 1002x751.

The splitter's stretch is 1:0 -- the FORM takes the growth, not the
runner. Every pixel the run pane gains past the command box is empty
output view; every pixel the tab stack gains is one closer to NovelAI's
two columns sitting side by side.

Switching tabs is the only "body swap" here and a `QTabWidget` does not
swap one: it stacks both panes and shows one. Nothing is reparented,
nothing is freed, so law 12's `takeWidget` sequence has nothing to govern
in this file -- and `setParent(None)` appears nowhere in the package,
which the check asserts over the code.

The palette is the editor's (`theme.apply`), so the two windows are light
or dark together and this one is not foreign beside it.

THE BUTTONS, AND WHICH OF THEM OPEN A SOCKET
--------------------------------------------
`WINDOW_ACTIONS` is the table -- one row per member of
`request_pane.OFFERED_SUBCOMMANDS`, and this module RAISES AT IMPORT if
those two ever part, so a subcommand the pane learns to compose cannot
reach the window without a row saying in words what it does.

    Draw the mannequin      render      no network    one press runs it
    Dry run (plan)          plan        no network    one press runs it
    Pixelize                pixelize    no network    one press runs it
    Ledger                  ledger      no network    one press runs it
    Send one request        run         ONE REQUEST   composes only
    Infill one cell         infill      ONE REQUEST   composes only
    Read the balance        account     opens a socket, composes only

A press on a FREE row composes the line, shows it, and runs it: nothing
leaves this machine, so a second press would be ceremony. A press on a
SENDING row composes the line and stops there. The send then costs two
more deliberate acts in `RunPane` -- Arm, then SEND ONE REQUEST -- and
`_press` refuses outright to start anything `request_pane` calls a sender,
so there is no path from one window press to one request.

`probe` has NO ROW. It is the author's own decision, typed by hand in a
terminal with the accept flag spelled out in full; this package does not
compose it, `RequestPane.command` raises for it, and
`tools/check_nai_ui.py` asserts the flag text appears nowhere here.

WHAT THIS WINDOW REFUSES TO DO
------------------------------
No queue, no batch, no sweep, no "generate all three recipes", no
auto-retry, nothing on a timer, and no action on a value change. A value
change reaches exactly one place: `RunPane.set_command`, which rewrites a
line of text and DISARMS. Every generation is one command a human typed
(docs/NAI_SPRITES.md, "The loop").

LAW 13: THIS MODULE OPENS NO MODAL AT ALL. A refusal is a status-bar
sentence and a disabled control, never a dialog, so every path through the
window can be driven by a check. The two modals in the package belong to
`CharacterPane` (`confirm_discard` and the save-name dialog) and are
reached only from a click inside that pane; `closeEvent` deliberately does
not call either, which is why an unsaved outfit edit is announced in the
title bar and the status bar while it is in flight rather than asked about
on the way out.

WHAT IS REMEMBERED BETWEEN SESSIONS
-----------------------------------
`SAVED_KEYS`, and `_remember` raises for anything else: the geometry, the
main window state, the splitter's sizes and the name of the character that
was open. NOT the form. A window that reopened with a seed, a source image
and a strength already filled in would show a line the author did not
compose this session, one arm away from being sent; re-typing four fields
is cheaper than that. The store is this window's own `QSettings`
application (`SETTINGS_APPLICATION`), beside the editor's, and nothing
from the environment is ever put in it.
"""
from __future__ import annotations

import os
from typing import NamedTuple

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from tools.nai import characters, state as nai_state
from tools.nai_ui import request_pane, run_pane, theme
from tools.nai_ui.character_pane import CharacterPane
from tools.nai_ui.request_pane import RequestPane
from tools.nai_ui.run_pane import RunPane

WINDOW_TITLE = "Pyoneer - NovelAI command composer"
"""The title bar. It carries the window's job and never a value: no path,
no seed, no character file and above all nothing from the environment."""

SETTINGS_ORGANISATION = "Pyoneer"
SETTINGS_APPLICATION = "PyoneerNaiComposer"
"""This window's own `QSettings` application, beside the editor's
`PyoneerEditor` rather than inside it: the editor's `EditorSettings` knows
a fixed list of keys and raises for anything else, and a window geometry
is not an editor preference."""

SAVED_KEYS: frozenset[str] = frozenset(
    {"geometry", "window_state", "splitter", "character"})
"""EVERYTHING this window may write to disk. `_remember` raises for a key
outside it, so growing the store is a deliberate edit here and not a line
somebody added in a hurry -- and so "what could this file possibly
contain" is answered by reading four words."""

MIN_SIZE: tuple[int, int] = (1000, 700)
"""The smallest window this one will become.

MEASURED, AND THE REASON IT IS THIS SMALL: at (1360, 780) the window's own
`minimumSizeHint` came out at 1367x838, which does not fit a 1366x768
laptop in EITHER dimension -- so the one screen size most likely to be
reading this window was the one size it refused to be. It is safe to go
this small now because `request_pane._Columns` stacks NovelAI's two columns
instead of letting them run off the right-hand edge, and because every
caption in the form is `QSizePolicy.Ignored` across and wraps. Nothing is
clipped at 1000 px; the form is simply taller and the scroll area does the
work it was always there to do."""

EDITOR_MIN_WIDTH = 460
"""Minimum width of the tab stack. NovelAI's columns ask for 410 (left) and
446 (right) at their own minimum and STACK below the sum of the two, so 460
is a width at which the whole form is readable with nothing clipped -- it
is above the wider column, not above the pair. It was 700, chosen when the
two columns were pinned side by side and the honest answer was "a scrollbar
you will have to drag"."""

RUN_MIN_WIDTH = 520
"""Minimum width of the run pane: at or just under `RunPane`'s own measured
`minimumSizeHint().width()` (552 with the controls on two rows), so the
command box never has to scroll the line it exists to show. It was 644,
measured when all seven controls sat on ONE row and the pane demanded 1032
px of a window that then could not fit a laptop."""

FIRST_RUN_SIZE: tuple[int, int] = (1900, 1040)
"""The window a first run opens at, clamped to the screen. Chosen so the
tab stack is comfortably past `request_pane._Columns`' measured 862 px
threshold, with both NovelAI columns side by side."""

RUN_FIRST_RUN_WIDTH = 720
"""What the run pane gets on a first run; the tab stack gets everything
else, because every pixel past the command box is empty output view and
every pixel short of 862 in the tab stack stacks NovelAI's settings column
under the prompt column instead of beside it.

MEASURED, and the reason this is applied in `showEvent` rather than in
`_build`: a `QSplitter` sized before the window has its real geometry
redistributes on the first resize and ignores what it was told. Asked for
(1180, 720) at build time, it laid out (704, 1173) -- the form squeezed to
704 px, which is the clipped right-hand column all over again."""

TAB_TITLES: tuple[str, str] = ("Character && outfit",
                               "Request - NovelAI's form")
"""The two tabs. Qt reads a single ampersand in a tab title as a mnemonic,
so it is doubled here; what a reader sees is one."""

DIRTY_MARK = " *"
"""What the Character tab gains while an outfit edit is unsaved, so the
fact is visible from the other tab."""


class WindowAction(NamedTuple):
    """One row of `WINDOW_ACTIONS`: a button, a menu item and what it costs.

    `subcommand` is a member of `request_pane.OFFERED_SUBCOMMANDS`.
    `label` is what the button says, `shortcut` a `QKeySequence` string or
    "", and `tooltip` the sentence a reader gets before pressing anything.

    `sends` is not a field: it is read from
    `request_pane.SENDING_SUBCOMMANDS`, which is the one place in the
    package that classifies a subcommand. A second spelling of that
    classification is exactly the sibling route CLAUDE.md's ACTIVE
    WARNINGS name, and getting it wrong here would mean a window button
    that sends one request per press.
    """

    subcommand: str
    label: str
    shortcut: str
    tooltip: str


WINDOW_ACTIONS: tuple[WindowAction, ...] = (
    WindowAction(
        "render", "Draw the mannequin", "Ctrl+R",
        "Draw this outfit's init strip locally. Opens no socket, spends "
        "nothing, and writes one PNG under the state root. One press runs "
        "it."),
    WindowAction(
        "plan", "Dry run (plan)", "Ctrl+D",
        "Build this exact request and print the guard's numbered verdicts "
        "without sending it. Opens no socket, spends nothing, and is what "
        "clears a send. One press runs it."),
    WindowAction(
        "run", "Send one request", "",
        "Compose the `run` line and show it. Pressing this sends NOTHING: "
        "the send costs two more presses in the pane on the right, Arm and "
        "then SEND ONE REQUEST, and the arm needs a green dry run of this "
        "very request first."),
    WindowAction(
        "infill", "Infill one cell", "",
        "Compose the `infill` line and show it. Pressing this sends "
        "NOTHING. Infill has no dry run in the CLI at all, so arming it is "
        "the only judgement there is -- the pane says so in those words."),
    WindowAction(
        "account", "Read the balance", "",
        "Compose the `account` line and show it. Pressing this sends "
        "NOTHING. `account` writes nothing, but it does open a socket, so "
        "it is armed like any other sender."),
    WindowAction(
        "pixelize", "Pixelize", "",
        "Quantise a finished strip to the palette and cut the frames. "
        "Local, opens no socket. One press runs it."),
    WindowAction(
        "ledger", "Ledger", "",
        "Print the last rows of the ledger. Local, opens no socket. One "
        "press runs it."),
)

if {row.subcommand for row in WINDOW_ACTIONS} != set(
        request_pane.OFFERED_SUBCOMMANDS):
    raise RuntimeError(
        f"WINDOW_ACTIONS covers "
        f"{sorted(row.subcommand for row in WINDOW_ACTIONS)} and "
        f"request_pane.OFFERED_SUBCOMMANDS is "
        f"{sorted(request_pane.OFFERED_SUBCOMMANDS)}: a subcommand the "
        f"pane can compose must reach the window through a row that says "
        f"in words what pressing it costs, and a button for something the "
        f"pane does not offer would raise ValueError on its first press")

LOCK_REASON = ("data/nai/LOCK is present: a request was sent whose outcome "
               "is unknown, so the guard refuses everything that sends "
               "until the author deletes that file by hand. This window "
               "offers no way to delete it.")
"""Why every sending control is disabled while LOCK exists. The guard in
the child would refuse anyway (condition 10); a button that looks live and
is not teaches the reader the wrong thing."""


def settings_store() -> QSettings:
    """This window's `QSettings`. The ONE place the store is named.

    AN INI FILE, EXPLICITLY, not the platform default. On Windows the
    default is the registry, and two things follow from that which this
    window cannot accept: a check cannot redirect it (measured --
    `QSettings.setDefaultFormat(IniFormat)` did not move
    `QSettings(org, app)` off `HKEY_CURRENT_USER`, so a check would write
    into the author's own machine), and nobody can read back what was
    stored without a registry tool. An ini is a file a human can open and
    a check can read as text, which is how "the credential is not in
    anything this window saved" is measured rather than argued.

    `QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, dir)`
    redirects it, so what a check writes and what the window writes go
    through this same function.
    """
    return QSettings(QSettings.IniFormat, QSettings.UserScope,
                     SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


class NaiWindow(QMainWindow):
    """The composer window.

    It is a `QMainWindow` so it gets a menu bar, a status bar and the same
    chrome as the editor. The status bar carries the facts a reader needs
    at a glance and nothing else: whether the credential is present (the
    bool from `run_pane.key_present`, never the value), whether
    `data/nai/LOCK` exists, whether an outfit edit is unsaved, and whether
    a child is running or a send is armed.
    """

    def __init__(self, parent=None) -> None:
        """Build the three panes, wire them, and restore the window geometry.

        The panes are built in dependency order -- character, request, run
        -- and wired before the window is shown. `CharacterPane` emits its
        `character_changed` once, synchronously, at the END OF ITS OWN
        `__init__`, which is before anything can be connected to it, so
        this constructor pushes `self.character.state()` into
        `RequestPane.set_character` by hand afterwards. That one call is
        why the command box is already filled when the window appears.

        No command runs during construction, nothing is armed, and nothing
        is written: `_restore` only reads.
        """
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(*MIN_SIZE)

        self.character = CharacterPane()
        self.request = RequestPane()
        self.run = RunPane()
        self._actions: dict[str, QAction] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._split_restored = False
        self._split_applied = False

        self._build()
        self._connect()
        # The first announcement already happened, inside CharacterPane's
        # own constructor. Hand it over now, so the form and the command
        # box describe the character the pane is actually showing.
        self.request.set_character(self.character.state())
        self._restore()
        self._refresh_chrome()
        request_pane.fix_wrapped_labels(self)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        """The command bar, the three panes in a splitter, the status bar."""
        central = QWidget(self)
        column = QVBoxLayout(central)
        column.addLayout(self._build_command_bar())

        self._tabs = QTabWidget()
        self._tabs.addTab(self.character, TAB_TITLES[0])
        self._tabs.addTab(self.request, TAB_TITLES[1])
        self._tabs.setMinimumWidth(EDITOR_MIN_WIDTH)
        self.run.setMinimumWidth(RUN_MIN_WIDTH)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._tabs)
        self._splitter.addWidget(self.run)
        # THE FORM TAKES THE GROWTH, not the runner. Every pixel the run
        # pane gains past the command box is empty output view, and every
        # pixel the tab stack gains is one closer to NovelAI's two columns
        # sitting side by side (request_pane.COLUMN_WIDTH twice). It was
        # 3:2, which at 1920 left the form at 851 px -- under the threshold
        # -- so a wide screen still read the stacked layout.
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        column.addWidget(self._splitter, 1)
        self.setCentralWidget(central)

        self._build_menus()
        self._build_status_bar()

    def _build_command_bar(self) -> QVBoxLayout:
        """One button per `WINDOW_ACTIONS` row, free ones first.

        The bar is ordered free-then-sending rather than in table order, so
        the three controls that can reach NovelAI sit together behind their
        own label instead of being mixed in among the ones that cannot --
        and on their OWN ROW, because seven buttons side by side were a
        hard 1338 px minimum for the whole window and a 1366x768 screen
        could not open it.
        """
        rows = QVBoxLayout()
        for sending in (False, True):
            row = QHBoxLayout()
            row.addWidget(self._bar_label(
                "Sends one request:" if sending else "Compose:"))
            for entry in WINDOW_ACTIONS:
                if self._sends(entry.subcommand) is not sending:
                    continue
                button = QPushButton(entry.label)
                button.setToolTip(entry.tooltip)
                button.clicked.connect(
                    lambda _checked=False, name=entry.subcommand:
                    self._press(name))
                self._buttons[entry.subcommand] = button
                row.addWidget(button)
            row.addStretch(1)
            rows.addLayout(row)
        return rows

    def _bar_label(self, text: str) -> QLabel:
        """A muted caption in the command bar, in the editor's idiom."""
        label = QLabel(text)
        label.setStyleSheet(theme.CAPTION_STYLE)
        return label

    def _build_menus(self) -> None:
        """A Command menu mirroring the bar, and File > Close.

        The menu exists so the shortcuts have a home a reader can find, and
        every item goes through `_press`, the same seam as the buttons: a
        menu item that took a shortcut past the send refusal would be a
        second route with its own rules.
        """
        commands = self.menuBar().addMenu("&Command")
        for entry in WINDOW_ACTIONS:
            action = QAction(entry.label, self)
            action.setToolTip(entry.tooltip)
            action.setStatusTip(entry.tooltip)
            if entry.shortcut:
                action.setShortcut(QKeySequence(entry.shortcut))
            action.triggered.connect(
                lambda _checked=False, name=entry.subcommand:
                self._press(name))
            self._actions[entry.subcommand] = action
            commands.addAction(action)

        window_menu = self.menuBar().addMenu("&Window")
        close = QAction("Close", self)
        close.setShortcut(QKeySequence.Close)
        close.triggered.connect(self.close)
        window_menu.addAction(close)

    def _build_status_bar(self) -> None:
        """Four permanent labels: credential, LOCK, unsaved edit, activity.

        The credential label asks `run_pane.key_present()` -- the one
        function in this package that looks at the environment at all --
        and shows the word it answers with. The name of the variable is not
        spelled in this file, and the value is never read anywhere.
        """
        bar = self.statusBar()
        self._key_label = QLabel("")
        self._key_label.setToolTip(
            "Whether the credential is set for this process, and nothing "
            "else. Its value is read by the child at send time; this "
            "window never sees it.")
        self._lock_label = QLabel("")
        self._dirty_label = QLabel("")
        self._activity_label = QLabel("")
        for label in (self._key_label, self._lock_label, self._dirty_label,
                      self._activity_label):
            label.setStyleSheet(theme.CAPTION_STYLE)
            bar.addPermanentWidget(label)

    def _connect(self) -> None:
        """Every signal in the window, in one readable place.

        `command_changed` reaching `set_command` is the whole of "an argv
        change disarms the send control": `RunPane.set_command` disarms
        unconditionally and first, so every edit in the form -- a seed, a
        strength, a recipe, a different character -- drops an arm that was
        standing.
        """
        self.character.character_changed.connect(self._character_changed)
        self.character.dirty_changed.connect(self._dirty_changed)
        self.character.render_requested.connect(self._render_requested)
        self.request.command_changed.connect(self.run.set_command)
        # AND the chrome, on the same edit. A control is shut when its own
        # line cannot run, and which lines cannot run changes with the
        # form: switch the action to infill and `plan` becomes unrunnable
        # while `infill` becomes runnable. Without this the buttons would
        # carry the verdict of whatever the form said when a button was
        # last pressed -- a gate that is correct once and stale after.
        self.request.command_changed.connect(self._command_changed)
        self.request.plan_requested.connect(self._plan_requested)
        self.run.command_requested.connect(self._press)
        self.run.armed_changed.connect(self._armed_changed)
        self.run.refused.connect(self._say)
        self.run.started.connect(self._started)
        self.run.finished.connect(self._finished)

    # -- the seam every button goes through --------------------------------

    def compose(self, subcommand: str) -> object:
        """Ask `RequestPane` for `subcommand`'s command and show it in `RunPane`.

        Returns the `widgets.NaiCommand`. This is the ONE path from a
        button to the command box: a button never builds an argv and never
        starts anything, so "what would this button run" is answered by
        reading one line of text before pressing anything else.

        ValueError for a subcommand outside
        `request_pane.OFFERED_SUBCOMMANDS`.
        """
        command = self.request.command(subcommand)
        self.run.set_command(command)
        self._refresh_chrome()
        return command

    def _press(self, subcommand: str) -> None:
        """A window button, a menu item, or a pane asking for a free command.

        Composes the line, and then runs it ONLY when `request_pane` says
        the subcommand does not send. A sender is composed and left in the
        box: RuntimeError if anything ever tries to start one from here, so
        there is no path from a single press to a single request.

        Refuses, with a status-bar sentence and no dialog, while a child
        is running, while the composed line is BLOCKED, or -- for a sender
        -- while `data/nai/LOCK` exists.

        The blocked check is the one that was missing. `RunPane.start`
        raises `RuntimeError(command.blocked)`, which is its contract; a Qt
        slot that lets that out prints a traceback to a terminal a window
        launched from a shortcut does not have, and the press then looks
        like a button that does nothing. Reachable in the window's default
        state from one press of Pixelize, and from Dry run while the action
        is infill, and from all four free buttons the moment a character
        file the loader refuses is selected.
        """
        if self.run.running():
            self._say("A child is still running. Its output is in the pane "
                      "on the right; nothing is queued behind it.")
            return
        if self._sends(subcommand) and self.locked():
            self._say(LOCK_REASON)
            return
        command = self.compose(subcommand)
        if not command.runnable():
            self._say(command.blocked)
            return
        if self._sends(subcommand):
            self._say(f"`{subcommand}` is composed, not sent. Read the line, "
                      f"then Arm and SEND ONE REQUEST in the pane on the "
                      f"right.")
            return
        if command.sends:
            raise RuntimeError(
                f"{subcommand!r} is not in request_pane.SENDING_SUBCOMMANDS "
                f"and yet composed a command that says it sends; one press "
                f"must never reach a socket")
        self.run.start()

    def _sends(self, subcommand: str) -> bool:
        """Whether `subcommand` opens a socket, asked of `request_pane`.

        The classification is never restated here. `_press` checks it, and
        then checks the composed command's own `sends` as well, because
        those are two different spellings of it inside `request_pane` and
        one press must be safe under both.
        """
        return subcommand in request_pane.SENDING_SUBCOMMANDS

    # -- the state root ----------------------------------------------------

    def state_root(self) -> str:
        """`data/nai/` in the main checkout -- `tools.nai.state.default_root()`.

        Used for the LOCK indicator and for the paths the status bar names.
        The window never writes under it; the child process does.
        """
        return nai_state.default_root()

    def locked(self) -> bool:
        """True when `data/nai/LOCK` exists.

        When it does, the status bar says so and every SENDING button and
        menu item is disabled with `LOCK_REASON` as its reason -- the guard
        in the child would refuse anyway (condition 10). The window offers
        NO way to delete `LOCK`: the author deletes it by hand. This is a
        `os.path.exists` and nothing more; it creates nothing.
        """
        return os.path.exists(os.path.join(self.state_root(),
                                           nai_state.LOCK_NAME))

    # -- chrome ------------------------------------------------------------

    def _blocked_reasons(self) -> dict:
        """Why each offered subcommand's line cannot run, as {sub: reason}.

        ONE computation, read by the window's own buttons AND handed to
        `RunPane.set_free_blocked` for the three the run pane owns, because
        the shape this repository counts most is a rule applied to the
        route that ships and not to its sibling: `run` was gated on
        `runnable` and `render`, `plan`, `pixelize` and `ledger` were not.

        Composes only; `RequestPane.command` builds an argv and reads the
        character file, and starts nothing.
        """
        return {name: self.request.command(name).blocked
                for name in request_pane.OFFERED_SUBCOMMANDS}

    def _refresh_chrome(self) -> None:
        """Enable exactly the controls the current state allows, and say why."""
        locked = self.locked()
        busy = self.run.running()
        blocked = self._blocked_reasons()
        self.run.set_free_blocked(
            {name: blocked.get(name, "")
             for name in run_pane.NO_NETWORK_BUTTONS})
        for entry in WINDOW_ACTIONS:
            sending = self._sends(entry.subcommand)
            refused = sending and locked
            why = blocked.get(entry.subcommand, "")
            allowed = not busy and not refused and not why
            reason = LOCK_REASON if refused else (why or entry.tooltip)
            for control in (self._buttons.get(entry.subcommand),
                            self._actions.get(entry.subcommand)):
                if control is None:
                    continue
                control.setEnabled(allowed)
                control.setToolTip(reason)
            # MEASURED, by looking at a screenshot: a disabled QPushButton
            # in this palette is a shade lighter than a live one and no
            # more, so three buttons the guard has shut sat there reading
            # as live. A control that is forbidden and explained wears
            # LOCKED_STYLE -- amber, not red, because nothing is wrong.
            button = self._buttons.get(entry.subcommand)
            if button is not None:
                button.setStyleSheet(
                    theme.LOCKED_STYLE if (refused or why) else "")

        self._key_label.setText(
            "credential: present" if run_pane.key_present()
            else "credential: not set for this process")
        self._lock_label.setText(
            "LOCK: present -- sending refused" if locked else "LOCK: none")
        self._lock_label.setToolTip(
            LOCK_REASON if locked
            else f"no LOCK in {self.state_root()}")
        self._activity_label.setText(
            "running" if busy else
            ("ARMED" if self.run.armed() else "idle"))

    def _say(self, message: str) -> None:
        """Put one sentence in the status bar. This window opens no dialog."""
        self.statusBar().showMessage(message, 15000)

    # -- what the panes announce -------------------------------------------

    def _character_changed(self, state: object) -> None:
        """A different character, a re-read, or a save: hand it to the form.

        `RequestPane.set_character` redraws the derived Prompt, Character
        Prompts and Character Positions and re-emits the command line; the
        init preview is `CharacterPane`'s own and refreshes itself. Nothing
        runs here.
        """
        self.request.set_character(state)
        self._refresh_chrome()
        self._say(f"character: {state.name}"
                  + ("" if state.ok() else f" -- {state.problem}"))

    def _dirty_changed(self, dirty: bool) -> None:
        """An unsaved outfit edit: say so in the title bar and the status bar.

        It does not disable anything. A command uses the file ON DISK, and
        that file is still exactly what the composed line would read, so
        the honest report is "there is an edit you have not saved", not "you
        may not send".
        """
        self._dirty_label.setText("unsaved outfit edit" if dirty else "")
        self._tabs.setTabText(
            0, TAB_TITLES[0] + (DIRTY_MARK if dirty else ""))
        self.setWindowTitle(
            f"{WINDOW_TITLE} - unsaved outfit edit" if dirty
            else WINDOW_TITLE)

    def _render_requested(self, name: str) -> None:
        """The character pane's own draw button: compose `render` and run it.

        `name` is the character the pane is showing. It is CHECKED against
        the line the form composes rather than used to build one, because
        the two disagreeing would mean the button drew a different outfit
        from the one on screen -- and this window has exactly one way to
        build an argv (law 7: it raises rather than draw the wrong one).
        """
        composed = self.request.command("render")
        if name not in composed.argv:
            raise RuntimeError(
                f"the character pane asked to draw {name!r} and the form "
                f"composed {' '.join(composed.argv[3:])}: the two panes "
                f"disagree about who is on screen")
        self._press("render")

    def _plan_requested(self) -> None:
        """The request pane asking for its own dry run."""
        self._press("plan")

    def _command_changed(self, _command: object) -> None:
        """The form was edited: re-read which lines can run. Runs nothing.

        `RunPane.set_command` has already shown the new line and dropped
        any arm; this only re-asks `_blocked_reasons` so a button's shut
        state follows the form instead of the last press.
        """
        self._refresh_chrome()

    def _armed_changed(self, armed: bool) -> None:
        """A send was armed or dropped: say it where a reader is looking."""
        self._refresh_chrome()
        self._say("ARMED: the next press of SEND ONE REQUEST opens one "
                  "connection and sends one request."
                  if armed else "the arm was dropped.")

    def _started(self, command: object) -> None:
        """A child started: grey the composer so nothing queues behind it."""
        self._refresh_chrome()
        self._say(f"running: {' '.join(command.argv[2:])}")

    def _finished(self, code: int) -> None:
        """A child exited: re-enable the composer and say how it went."""
        self._refresh_chrome()
        png = self.run.output_png()
        self._say(f"exit {code}" + (f" -- wrote {png}" if png else ""))

    # -- what is remembered ------------------------------------------------

    def _remember(self, key: str, value: object) -> None:
        """Write one `SAVED_KEYS` entry. ValueError for any other key.

        The whole of what this window puts on disk goes through here, so
        "could the store contain something it should not" is answered by
        four words and one raise rather than by reading every call site.
        """
        if key not in SAVED_KEYS:
            raise ValueError(
                f"{key!r} is not in SAVED_KEYS {sorted(SAVED_KEYS)}: this "
                f"window remembers a geometry and a character name, and "
                f"adding to that list is a deliberate edit in app.py")
        settings_store().setValue(key, value)

    def _restore(self) -> None:
        """Read the remembered geometry, splitter and character. Writes nothing.

        A remembered character that no longer has a file is NOT silently
        ignored: the pane keeps its own default and the status bar says
        which name went missing, because a window that quietly opens on a
        different outfit than it closed on is the shape law 7 is about.
        """
        store = settings_store()
        geometry = store.value("geometry")
        if geometry is None or not self.restoreGeometry(geometry):
            self._first_run_geometry()
        window_state = store.value("window_state")
        if window_state is not None:
            self.restoreState(window_state)
        splitter = store.value("splitter")
        # A state saved by an earlier LAYOUT of this window -- it had three
        # children, not two -- comes back False here. Qt's own answer is
        # the return value, and `_split_on_show` then does the sizing.
        self._split_restored = bool(
            splitter is not None and self._splitter.restoreState(splitter))

        name = store.value("character")
        if not name or name == self.character.state().name:
            return
        if name not in characters.available():
            self._say(f"the remembered character {name!r} has no file any "
                      f"more; showing {self.character.state().name}")
            return
        self.character.select(str(name))

    def showEvent(self, event) -> None:  # noqa: N802  (Qt's own spelling)
        """Size the splitter the first time the window is actually shown.

        Not in `_build`: see `RUN_FIRST_RUN_WIDTH` for the measurement. A
        remembered splitter state wins, and this runs once, so dragging
        the splitter and then minimising does not undo the drag.
        """
        super().showEvent(event)
        if self._split_restored or self._split_applied:
            return
        self._split_applied = True
        total = self._splitter.width()
        run_width = min(RUN_FIRST_RUN_WIDTH, max(RUN_MIN_WIDTH, total // 2))
        self._splitter.setSizes([max(EDITOR_MIN_WIDTH, total - run_width),
                                 run_width])

    def _first_run_geometry(self) -> None:
        """`FIRST_RUN_SIZE`, clamped to the screen that is actually there.

        A window that opens bigger than the display cannot be dragged back
        by its title bar, and the size this one wants -- wide enough for
        both of NovelAI's columns beside the command box -- is bigger than
        some screens.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(*FIRST_RUN_SIZE)
            return
        room = screen.availableGeometry()
        self.resize(min(FIRST_RUN_SIZE[0], room.width()),
                    min(FIRST_RUN_SIZE[1], room.height()))

    def closeEvent(self, event) -> None:  # noqa: N802  (Qt's own spelling)
        """Save the geometry; refuse to close while a child is running.

        A close mid-send would leave the child orphaned and the outcome
        unknown, which is the state that writes `LOCK`. The window says so
        in the status bar and stays open; `RunPane.interrupt` is the
        deliberate way out. No dialog is opened on either path (law 13).
        """
        if self.run.running():
            self._say(
                "A child is still running. Closing now would orphan it and "
                "leave the outcome unknown, which is the state that writes "
                "LOCK. Use Interrupt in the pane on the right.")
            event.ignore()
            return
        self._remember("geometry", self.saveGeometry())
        self._remember("window_state", self.saveState())
        self._remember("splitter", self._splitter.saveState())
        self._remember("character", self.character.state().name)
        # The character pane's init preview writes into a scratch directory
        # of its own; this is where it goes away.
        self.character.drop_preview()
        event.accept()
