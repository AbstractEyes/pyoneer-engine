"""Show one command, arm it if it sends, run it ONCE, stream what it says.

OWNER: this pane is the ONLY thing in `tools.nai_ui` that starts a process.
Nothing else here calls `subprocess`, `QProcess`, `os.system` or `exec`,
and `tools/check_nai_ui.py` asserts that.

THE SHAPE OF ONE RUN
--------------------
    set_command(cmd)    show it in the `widgets.CommandBox`; DISARM
    arm()               the explicit confirm step; only legal for a
                        sending command, and only when `cmd.runnable()`
    start()             run it, exactly once; DISARM immediately, before
                        the child has said anything

A non-sending command (`render`, `plan`, `pixelize`, `ledger`) runs from
`start()` with no arm. A sending command (`account`, `run`, `infill`) runs
only from an armed state, and arming is a separate deliberate act by a
human -- a second button, never a checkbox that stays ticked and never a
keyboard shortcut. `arm()` is cleared by ANY change to the command, so a
command armed and then edited must be armed again: the thing armed is the
line in the box, not the button.

AND FOR `run`, ARMING NEEDS A GREEN DRY RUN OF THE SAME REQUEST.
`plan` builds the same body the send would and prints the guard's eleven
numbered verdicts without opening a socket. So this pane remembers the
request key (`request_key`) of the last `plan` THE CHILD ACTUALLY PARSED
and that exited 0 -- `_launched`, captured by `start()`, never `_command`,
which is the line in the box and follows the form while a child runs --
and `arm()` refuses a `run` whose key is not that one -- a different
seed, a different character, a different strength, a changed steps value,
or no dry run at all. `CLEARANCE` gives EVERY sending subcommand its verdict in one table,
because `account` and `infill` have no dry run to be cleared by: the CLI's
`plan` takes only generate and img2img, and `account` builds no request at
all. The arm banner says which of the two it is, in words, before the
human presses anything. A new sending subcommand raises at import until
somebody puts it in that table.

ONE GENERATION IS ONE COMMAND A HUMAN TYPED. There is NO queue, NO batch,
NO sweep, NO loop, NO auto-retry and NOTHING on a timer. `start()` on an
already-running pane raises; it does not enqueue. A child that exits
non-zero is reported and stopped at -- a 429, a 5xx and a timeout are all
just an exit code with output, and this pane never sends the command again.
A finished SEND drops the clearance as well, so one green dry run can never
pay for two requests.

THE KEY
-------
The child inherits this process's environment, so `NAI_KEY` reaches
`tools.nai.transport.api_key` in the child, at send time, exactly as it
does from a shell. THIS PANE NEVER READS ITS VALUE. `key_present()`
answers a bool from the NAME being in `os.environ` and that bool is all the
window ever learns; no widget, tooltip, window title, log line or saved
setting may carry the value, and the environment is passed to the child
whole rather than rebuilt, so nothing here ever holds it in a variable.

The output view shows the child's stdout and stderr verbatim. That is safe
by the pipeline's own contract: `tools.nai.state.scrub_text` runs on every
error the CLI prints, no ledger row or message may carry the key or an
Authorization header, and `tools/check_nai.py` measures that with a canary
key. This pane adds no redaction of its own, because a second redactor
would be a second thing to get wrong.

WHAT `app.py` MUST WIRE, OR THREE BUTTONS HERE DO NOTHING
---------------------------------------------------------
This pane builds no argv, so its three no-network buttons ask for one:

    RunPane.command_requested(str)  ->  NaiWindow.compose(sub)
                                    ->  RunPane.start()

with `sub` one of `NO_NETWORK_BUTTONS` -- "plan", "pixelize", "ledger" --
and nothing else; the signal refuses to carry a sending subcommand. The
window's own buttons (Draw the mannequin, Send, Infill one cell, Read the
balance) go through `compose` and `set_command` as before, and the Arm and
Send controls stay here, under the human's hand.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from tools.nai_ui import request_pane, theme, widgets

# ---------------------------------------------------------------------------
# Reading what the child said
# ---------------------------------------------------------------------------

REQUEST_FLAGS: tuple[str, ...] = ("--action", "--character", "--seed",
                                  "--variant", "--steps", "--scale",
                                  "--strength", "--noise", "--from")
"""The options that change the request BODY, and therefore what the guard
judged. `plan` and `run` both accept every one of them."""

REQUEST_SWITCHES: tuple[str, ...] = ("--color-correct",)
"""The body-changing options that take no value."""

LEDGER_FLAGS: tuple[str, ...] = ("--round", "--phase", "--lever",
                                 "--strip-version")
"""Bookkeeping the ledger row carries and the request body does not. Two
argvs that differ only here describe the SAME request, so a dry run cleared
with `--round 1` still clears the send that records round 2. Named, rather
than simply left out, so the omission is a decision a reader can see -- and
asserted below to be disjoint from `REQUEST_FLAGS`, so a flag cannot come
to mean both."""

SWITCHES: tuple[str, ...] = ("--color-correct", "--keep-cell",
                             "--remove-orphans")
"""Every option this window writes that takes NO value. `request_key` walks
an argv in flag/value pairs, so it has to know which flags stand alone."""

if set(REQUEST_FLAGS) & set(LEDGER_FLAGS):
    raise RuntimeError(
        f"{sorted(set(REQUEST_FLAGS) & set(LEDGER_FLAGS))} is named as both "
        f"a request flag and ledger bookkeeping; one of the two decides "
        f"whether a dry run still clears a send, and it cannot be both")
if set(REQUEST_SWITCHES) - set(SWITCHES):
    raise RuntimeError(
        f"{sorted(set(REQUEST_SWITCHES) - set(SWITCHES))} changes the body "
        f"and is not listed as a switch, so request_key would read the next "
        f"argument as its value")

PLAN_CLEARED = "plan"
"""This sending subcommand may be armed only after a green `plan` of the
same request key."""

NO_DRY_RUN = "none"
"""This sending subcommand has no dry run in the CLI at all, so arming it
rests on the two deliberate presses and the banner alone."""

NEVER_ARMED = "never"
"""This sending subcommand is not armed here under any circumstances."""

CLEARANCE: dict[str, str] = {
    "run": PLAN_CLEARED,
    "infill": NO_DRY_RUN,
    "account": NO_DRY_RUN,
    "probe": NEVER_ARMED,
}
"""Every sending subcommand and what must be true before it may be armed.

A verdict for each, in ONE table, because the failure this repository keeps
catching is a rule applied to the route that ships and not to its sibling.
`run` is the one `plan` can judge. `infill` has no `plan --action infill`
in `tools/nai/cli.py`, and `account` builds no request, so neither can be
cleared by a dry run -- the banner says so rather than pretending. `probe`
is never composed or armed by this window.
"""

if set(CLEARANCE) != set(request_pane.SENDING_SUBCOMMANDS):
    raise RuntimeError(
        f"CLEARANCE covers {sorted(CLEARANCE)} and the senders are "
        f"{sorted(request_pane.SENDING_SUBCOMMANDS)}: every subcommand that "
        f"opens a socket needs its own verdict here before it can be armed")

BUTTON_TIPS: dict[str, str] = {
    "plan": "Build this exact request and print the guard's verdicts. "
            "Opens no socket, spends nothing, and is what clears a send.",
    "run": "Run the line in the box. Enabled only while that line opens no "
           "socket: a sender is armed and sent by the two buttons on the "
           "right instead.",
    "pixelize": "Post-process a strip that is already on disk into per-frame "
                "PNGs. Opens no socket and spends nothing.",
    "ledger": "Print the tail of data/nai/ledger.jsonl. Opens no socket, "
              "writes nothing, and spends nothing.",
    "arm": "Unlock SEND ONE REQUEST for this exact line. Sends nothing "
           "itself; for `run` it needs a green dry run of this very "
           "request, and any edit to the line drops it again.",
    "send": "Open one connection to NovelAI and send this request ONCE, "
            "against the live account. Armed only, no retry, no queue.",
    "interrupt": "Kill the running child. If its request had already been "
                 "sent, whether it was charged is unknown and the child "
                 "writes LOCK.",
}
"""One sentence per button in this pane, so a control that is shut explains
itself without the banner. Kept beside `NO_NETWORK_BUTTONS` rather than
typed at each `QPushButton`, because the failure this repository counts is
the rule applied to one route and not its sibling: the window's top bar had
these and the run pane did not."""

NO_NETWORK_BUTTONS: tuple[str, ...] = ("plan", "pixelize", "ledger")
"""The subcommands this pane's own buttons may ask the window to compose.
None of them opens a socket, so asking for one and running it is a single
press. Everything that sends is composed by a window button and still needs
the arm and the send here."""

_CONDITION_RX = re.compile(r"^ {1,4}(\d{1,2}) \[([^\]]+)\] (.*)$", re.M)
"""One guard verdict as `plan` prints it: two spaces, the number right
aligned to width 2, the mark in brackets, then the title and its detail."""

_VERDICT_RX = re.compile(r"^verdict {2,}(.*)$", re.M)
"""The CLI's own one-line summary, in its aligned-to-column-14 format."""

_PNG_RX = re.compile(r"^(render|output|composite) {2,}(\S.*\.png)\s*$", re.M)
"""The three keys under which the CLI prints a PNG it wrote: `render` for a
mannequin init, `output` for a strip a send returned, `composite` for an
infill merged back into its strip. NOTHING ELSE is treated as an image
path: `pixelize` prints the DIRECTORY it wrote, and joining a file name
onto it here would be this window guessing at the child's naming."""

_FAIL_COLOUR = QColor(255, 120, 120)
"""The refusal red of `theme.PROBLEM_STYLE`, for a failed condition."""


def key_present() -> bool:
    """True when NAI_KEY is a name in `os.environ`.

    `"NAI_KEY" in os.environ` -- the name only. This function does not
    read, return, log, hash, measure the length of, or otherwise touch the
    value, and it is the ONLY place in `tools.nai_ui` that mentions the
    name at all. A window started before the variable was set sees False,
    which is the true answer for that process (docs/NAI_SPRITES.md, "The
    key").
    """
    return "NAI_KEY" in os.environ


def subcommand_of(argv) -> str:
    """The `tools.nai` subcommand inside a complete argv, or "".

    The argv is `[interpreter, -m, tools.nai, SUBCOMMAND, ...]`, so the
    subcommand is the first token after the interpreter that is not an
    option, not `-m`, and carries no dot. A subcommand never carries a dot
    and every module or script path does, which is also how this reads an
    argv whose head is a driver script rather than `-m tools.nai`.
    """
    for token in list(argv)[1:]:
        if token == "-m" or token.startswith("-") or "." in token:
            continue
        return token
    return ""


def request_key(argv) -> tuple:
    """What a `plan` and a `run` must agree on to be the same request.

    The positional (the recipe) plus every `REQUEST_FLAGS` option present
    and its value, plus every `REQUEST_SWITCHES` flag present, as a sorted
    tuple. `LEDGER_FLAGS` and `--cell` are left out: they change the row
    that is written, not the body that is judged.

    An argv with no `--seed` yields a key whose seed is absent, and
    `clearance_problem` refuses to clear on one: the CLI would draw a fresh
    seed for the send, so the two commands would not be the same request
    however equal their argvs look.
    """
    tokens = list(argv)
    items: list[tuple[str, str]] = []
    positional = ""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in SWITCHES:
            if token in REQUEST_SWITCHES:
                items.append((token, "true"))
            index += 1
            continue
        if token.startswith("--"):
            # Every remaining option of this CLI takes a value, so the pair
            # is consumed together: a ledger flag's value can never be read
            # as the next option.
            value = tokens[index + 1] if index + 1 < len(tokens) else ""
            if token in REQUEST_FLAGS:
                items.append((token, value))
            index += 2
            continue
        index += 1
    subcommand = subcommand_of(tokens)
    if subcommand:
        after = tokens.index(subcommand) + 1
        for token in tokens[after:]:
            if token.startswith("-"):
                break
            positional = token
            break
    return (positional, tuple(sorted(items)))


def clearance_problem(subcommand: str, cleared, wanted) -> str:
    """Why `subcommand` may not be armed for `wanted`, or "".

    `cleared` is the `request_key` of the last dry run that exited 0, or
    None. `wanted` is this command's own key. One function for every
    sending subcommand, from `CLEARANCE`; a subcommand missing from that
    table is refused by name rather than waved through (law 7).
    """
    rule = CLEARANCE.get(subcommand)
    if rule is None:
        return (f"{subcommand!r} is not in CLEARANCE: this window arms only "
                f"a command whose clearance rule somebody wrote down")
    if rule == NEVER_ARMED:
        return (f"{subcommand} is never armed here: it is the author's own "
                f"decision, typed by hand in a terminal")
    if rule == NO_DRY_RUN:
        return ""
    if cleared is None:
        return ("no dry run has cleared this line: press Dry run and read "
                "the verdicts before arming a send")
    if not dict(wanted[1]).get("--seed"):
        return ("this line leaves the seed to the CLI, so the dry run and "
                "the send would be two different requests: press Randomise "
                "to fix one seed, then Dry run again")
    if cleared != wanted:
        return ("the dry run that passed was for a different request; run "
                "Dry run again on the line as it stands now")
    return ""


def conditions_in(text: str) -> tuple[tuple[int, str, str], ...]:
    """Every guard verdict in `text` as (number, mark, title), in order.

    Read out of the child's own printed lines -- this window does not
    evaluate a condition, it reads the one the guard evaluated in the
    child. An output with no condition lines gives an empty tuple.
    """
    return tuple((int(number), mark, title.strip())
                 for number, mark, title in _CONDITION_RX.findall(text))


class RunPane(QWidget):
    """The command box, the arm/send controls, and the output view.

    Signals:
        started(object)         the `widgets.NaiCommand` that just started
        output(str)             one chunk of the child's stdout or stderr,
                                verbatim, as it arrives
        finished(int)           the child's exit code: 0 ok, 1 error, 2
                                refused, 3 strip rejected (tools/nai/cli.py)
        armed_changed(bool)     the arm state, for the window's chrome
        refused(str)            a control was pressed and the API refused
                                it, in its own words: the window puts it in
                                the status bar. A refusal is REPORTED, not
                                thrown out of a Qt slot into a terminal.
        command_requested(str)  one of `NO_NETWORK_BUTTONS`: "compose this
                                and hand it back to me". The pane builds no
                                argv, so this is how its own Dry run,
                                Pixelize and Ledger buttons reach one.
    """

    started = Signal(object)
    output = Signal(str)
    finished = Signal(int)
    armed_changed = Signal(bool)
    refused = Signal(str)
    command_requested = Signal(str)

    _line = Signal(str)
    _exited = Signal(int)

    def __init__(self, parent=None) -> None:
        """Build the box, the buttons and the output view; disarmed, idle.

        The pane shows `key_present()` as one line -- "NAI_KEY: present" or
        "NAI_KEY: not set for this process" -- and nothing more about it.
        """
        super().__init__(parent)
        self._command = None
        self._armed = False
        self._active = False
        self._process = None
        self._chunks: list[str] = []
        self._cleared = None
        self._launched = None
        self._free_blocked: dict[str, str] = {}
        self._build()
        self._line.connect(self._append, Qt.QueuedConnection)
        self._exited.connect(self._finished, Qt.QueuedConnection)
        self._refresh_controls()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        """Lay out the key line, the command box, the controls and the views."""
        column = QVBoxLayout(self)

        self._key_label = QLabel(
            "NAI_KEY: present" if key_present()
            else "NAI_KEY: not set for this process")
        self._key_label.setStyleSheet(theme.CAPTION_STYLE)
        self._key_label.setToolTip(
            "Whether the name is set, and nothing else. The value is read "
            "by the child process at send time; this window never sees it.")
        column.addWidget(self._key_label)

        self._box = widgets.CommandBox()
        column.addWidget(self._box)

        column.addLayout(self._build_buttons())

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(theme.BANNER_STYLE)
        column.addWidget(self._banner)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self._build_conditions())
        split.addWidget(self._build_output())
        split.addWidget(self._build_result())
        split.setStretchFactor(1, 2)
        column.addWidget(split, 1)
        request_pane.fix_wrapped_labels(self)

    def _build_buttons(self) -> QVBoxLayout:
        """The two rows of controls: the free ones, then the sending pair."""
        rows = QVBoxLayout()
        row = QHBoxLayout()
        self._plan_button = QPushButton("Dry run (plan)")
        self._plan_button.setToolTip(BUTTON_TIPS["plan"])
        self._plan_button.clicked.connect(self._ask_plan)
        self._run_button = QPushButton("Run")
        self._run_button.setToolTip(BUTTON_TIPS["run"])
        self._run_button.clicked.connect(self._run_clicked)
        self._pixelize_button = QPushButton("Pixelize")
        self._pixelize_button.setToolTip(BUTTON_TIPS["pixelize"])
        self._pixelize_button.clicked.connect(self._ask_pixelize)
        self._ledger_button = QPushButton("Ledger")
        self._ledger_button.setToolTip(BUTTON_TIPS["ledger"])
        self._ledger_button.clicked.connect(self._ask_ledger)
        self._arm_button = QPushButton("Arm the send...")
        self._arm_button.setToolTip(BUTTON_TIPS["arm"])
        self._arm_button.clicked.connect(self._arm_clicked)
        self._send_button = QPushButton("SEND ONE REQUEST")
        self._send_button.setToolTip(BUTTON_TIPS["send"])
        self._send_button.clicked.connect(self._send_clicked)
        self._interrupt_button = QPushButton("Interrupt")
        self._interrupt_button.setToolTip(BUTTON_TIPS["interrupt"])
        self._interrupt_button.clicked.connect(self._interrupt_clicked)
        for button in (self._plan_button, self._run_button,
                       self._pixelize_button, self._ledger_button):
            row.addWidget(button)
        row.addStretch(1)
        rows.addLayout(row)
        sending = QHBoxLayout()
        sending.addStretch(1)
        for button in (self._arm_button, self._send_button,
                       self._interrupt_button):
            sending.addWidget(button)
        rows.addLayout(sending)
        return rows

    def _build_conditions(self) -> QWidget:
        """The guard's numbered verdicts, as a checklist rather than a log."""
        box = QGroupBox("Guard conditions")
        column = QVBoxLayout(box)
        caption = QLabel("as the last dry run printed them")
        caption.setWordWrap(True)
        caption.setStyleSheet(theme.CAPTION_STYLE)
        column.addWidget(caption)
        self._conditions = QListWidget()
        self._conditions.setMinimumHeight(52)
        self._conditions.setStyleSheet(theme.MONO_STYLE)
        column.addWidget(self._conditions)
        self._verdict = QLabel("no dry run yet")
        self._verdict.setWordWrap(True)
        self._verdict.setStyleSheet(theme.CAPTION_STYLE)
        column.addWidget(self._verdict)
        return box

    def _build_output(self) -> QWidget:
        """The child's stdout and stderr, verbatim, as they arrive."""
        box = QGroupBox("Output")
        column = QVBoxLayout(box)
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMinimumHeight(56)
        self._view.setStyleSheet(theme.MONO_STYLE)
        self._view.setPlaceholderText("nothing has run in this window yet")
        column.addWidget(self._view)
        return box

    def _build_result(self) -> QWidget:
        """The PNG the child printed, and the ledger rows it printed."""
        box = QGroupBox("Result")
        column = QVBoxLayout(box)
        self._image = widgets.ImageView()
        column.addWidget(self._image)
        self._ledger_view = QPlainTextEdit()
        self._ledger_view.setReadOnly(True)
        self._ledger_view.setStyleSheet(theme.MONO_STYLE)
        self._ledger_view.setPlaceholderText(
            "the ledger tail: press Ledger to read the last rows")
        self._ledger_view.setMinimumHeight(40)
        self._ledger_view.setMaximumHeight(140)
        column.addWidget(self._ledger_view)
        return box

    # -- the command -------------------------------------------------------

    def set_command(self, command: object) -> None:
        """Show `command` (a `widgets.NaiCommand`) and DISARM.

        Disarming is unconditional and comes first: a pane armed for one
        command must never be armed for the next one, even when the two
        argvs happen to be equal.
        """
        self.disarm()
        self._command = command
        self._box.set_command(command)
        self._refresh_controls()

    def command(self) -> object | None:
        """The command shown, or None before the first `set_command`."""
        return self._command

    def launched(self) -> object | None:
        """The command the RUNNING child parsed, or None when none is.

        `command()` is the line in the box and follows the form; this is
        what was actually started. `_finished` reads THIS, so an edit made
        while a child runs cannot make its exit code describe a different
        request.
        """
        return self._launched

    def set_free_blocked(self, reasons: dict) -> None:
        """Why each of `NO_NETWORK_BUTTONS` cannot run, as {subcommand: why}.

        The window composes those three lines and owns the answer; this
        pane only shows it, so a button whose line the loader would refuse
        is shut and wears the refusal, instead of raising out of a Qt slot
        into a terminal the author may not have.

        KeyError naming any subcommand outside `NO_NETWORK_BUTTONS` (law
        7): this pane's own buttons ask for those three and nothing else,
        and a reason filed against a fourth would silently shut nothing.
        """
        extra = sorted(set(reasons) - set(NO_NETWORK_BUTTONS))
        if extra:
            raise KeyError(
                f"{extra} is not one of this pane's own buttons "
                f"{list(NO_NETWORK_BUTTONS)}; a reason filed against a "
                f"subcommand with no button here would shut nothing")
        self._free_blocked = {str(k): str(v) for k, v in reasons.items()}
        self._refresh_controls()

    # -- arming ------------------------------------------------------------

    def arm(self) -> None:
        """The explicit confirm step for a sending command.

        RuntimeError when there is no command, when `command.sends` is
        False (a non-sending command is not armed, it is simply run), when
        `command.runnable()` is False, while a child is running, or when
        `clearance_problem` has something to say -- for `run`, that is a
        green dry run of this very request. Emits `armed_changed(True)`.
        """
        command = self._command
        if command is None:
            raise RuntimeError("nothing to arm: no command is shown")
        if not command.sends:
            raise RuntimeError(
                "this command opens no socket; it is not armed, it is run")
        if not command.runnable():
            raise RuntimeError(command.blocked)
        if self._active:
            raise RuntimeError(
                "a child is still running; this pane runs one command at a "
                "time and never queues a second")
        problem = self._clearance()
        if problem:
            raise RuntimeError(problem)
        self._armed = True
        self._refresh_controls()
        self.armed_changed.emit(True)

    def armed(self) -> bool:
        """True when a sending command is armed and has not yet been run."""
        return self._armed

    def disarm(self) -> None:
        """Drop the arm. Idempotent; emits `armed_changed(False)` when it moved."""
        if not self._armed:
            return
        self._armed = False
        self._refresh_controls()
        self.armed_changed.emit(False)

    def _clearance(self) -> str:
        """Why the shown command may not be armed right now, or ""."""
        command = self._command
        if command is None:
            return "nothing to arm: no command is shown"
        return clearance_problem(subcommand_of(command.argv), self._cleared,
                                 request_key(command.argv))

    # -- running -----------------------------------------------------------

    def start(self) -> None:
        """Run the shown command ONCE, in `command.cwd`, and stream it.

        Disarms BEFORE the child is started, so no path through this method
        can leave a second send armed. Raises, and starts nothing, when:
        there is no command; `command.runnable()` is False; a child is
        already running; or `command.sends` is True and `armed()` is False.

        The child is `subprocess.Popen(command.argv, cwd=command.cwd)` with
        the environment INHERITED WHOLE -- not rebuilt, not filtered, not
        added to -- its stdout and stderr merged and read line by line into
        `output`. There is no timeout and no kill on a slow child: the
        pipeline's own `model.TIMEOUT_S` governs the request, and killing a
        child mid-send would produce exactly the "sent, outcome unknown"
        state that writes LOCK.
        """
        command = self._command
        if command is None:
            raise RuntimeError("nothing to run: no command is shown")
        if not command.runnable():
            raise RuntimeError(command.blocked)
        if self._active:
            raise RuntimeError(
                "a child is already running; this pane runs one command at "
                "a time and never queues a second")
        if command.sends and not self._armed:
            raise RuntimeError(
                "this command opens a socket and is not armed; arming is a "
                "separate, deliberate act")
        self.disarm()
        self._active = True
        self._launched = command
        self._chunks = []
        # The argv, as the FIRST line of the transcript. A silent child used
        # to leave "nothing has run in this window yet" on screen for the
        # whole of its run, and the output that followed was attached to no
        # line. `text()` is what the CHILD said and does not include this.
        self._view.setPlainText("$ " + command.text() + chr(10))
        self._conditions.clear()
        self._verdict.setText("running...")
        self._refresh_controls()
        self._process = subprocess.Popen(
            list(command.argv), cwd=command.cwd or None,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        reader = threading.Thread(target=self._pump, args=(self._process,),
                                  daemon=True)
        reader.start()
        self.started.emit(command)

    def _pump(self, process) -> None:
        """Read the child line by line until EOF, then post its exit code.

        Runs in a plain daemon thread and touches no widget: every line
        goes out through `_line`, which Qt delivers to the GUI thread, and
        the exit code through `_exited`. There is no timeout here -- see
        `start` for why a kill is the author's decision and never ours.
        """
        try:
            for line in process.stdout:
                self._line.emit(line)
        finally:
            process.stdout.close()
            self._exited.emit(process.wait())

    def running(self) -> bool:
        """True while a child is alive."""
        return self._active

    def interrupt(self) -> None:
        """Ask a running child to stop, and say what that costs.

        Shows, before doing anything, the sentence from
        docs/NAI_SPRITES.md: a request interrupted AFTER it was sent writes
        `LOCK`, because whether it was charged is unknown, and the author
        then deletes `LOCK` by hand. Never called automatically -- there is
        no timer, no watchdog and no cancel-on-close.
        """
        if not self._active or self._process is None:
            raise RuntimeError("nothing is running")
        self._append(
            "\n-- interrupt requested by the author. If the request had "
            "already been sent, whether it was charged is unknown: the "
            "child writes LOCK and everything is refused until the author "
            "deletes that file by hand.\n")
        self._process.terminate()

    # -- output ------------------------------------------------------------

    def text(self) -> str:
        """Everything THIS child has said so far, verbatim.

        `start` empties it, so the transcript, the condition checklist and
        `output_png` all describe the run now on screen. A `plan` after a
        `render` must not be able to answer with the render's PNG. The
        echoed `$ <argv>` line `start` writes into the view is NOT part of
        this: what the child said is what the child said.
        """
        return "".join(self._chunks)

    def clear(self) -> None:
        """Empty the output view. Refuses while `running()`.

        Takes the guard verdicts and any clearance with it: the verdicts
        are the evidence a send was armed on, so a reader who clears them
        away must run the dry run again.
        """
        if self.running():
            raise RuntimeError(
                "a child is still writing into this view; let it finish or "
                "press Interrupt")
        self._chunks = []
        self._view.setPlainText("")
        self._conditions.clear()
        self._verdict.setText("no dry run yet")
        self._cleared = None
        self._launched = None
        self.disarm()
        self._refresh_controls()

    def output_png(self) -> str:
        """The path the last run printed as its image, or "".

        Parsed from the CLI's own aligned output: `render` prints
        "render        <path>", a sending command prints
        "output        <path>", and an infill prints "composite     <path>".
        The path is READ from the output, never guessed and never
        reconstructed from the form, so `widgets.ImageView` shows the file
        that exists rather than the file we expected. `pixelize` prints the
        directory it wrote and no PNG line, so it answers "" here and the
        written path stays in the output view where the child put it.
        """
        found = _PNG_RX.findall(self.text())
        return found[-1][1].strip() if found else ""

    # -- internals ---------------------------------------------------------

    def _append(self, text: str) -> None:
        """One chunk of the child's output: keep it, show it, announce it."""
        self._chunks.append(text)
        self._view.moveCursor(QTextCursor.End)
        self._view.insertPlainText(text)
        self._view.ensureCursorVisible()
        self.output.emit(text)

    def _finished(self, code: int) -> None:
        """The child exited: read its output, update the clearance, announce.

        The clearance moves in exactly two places, both here: a `plan` that
        exited 0 records the request it judged, and any command that SENT
        drops it, because the balance chain and the ledger have moved and
        the verdicts on screen describe the world before that.

        THE COMMAND READ HERE IS `_launched`, NEVER `_command`. The form
        stays live while a child runs, so every edit recomposes the line in
        the box; reading that line here credited this exit code to whatever
        had since been composed, and one nudge of the Steps spinner during
        a `render` recorded a plan clearance for a request no dry run ever
        judged -- which put SEND live over an empty verdict list, the one
        thing a reader is told to read before arming. The clearance must
        describe the argv the CHILD parsed, and nothing else does.
        """
        command = self._launched
        self._launched = None
        self._active = False
        self._process = None
        subcommand = subcommand_of(command.argv) if command else ""
        self._show_conditions()
        if subcommand == "plan":
            self._cleared = (request_key(command.argv) if code == 0
                             else None)
        if command is not None and command.sends:
            self._cleared = None
        if subcommand == "ledger":
            self._ledger_view.setPlainText(self.text())
        png = self.output_png()
        if png:
            self._image.show_png(png)
        self._refresh_controls()
        self.finished.emit(code)

    def _show_conditions(self) -> None:
        """Put the child's own verdict lines into the checklist."""
        self._conditions.clear()
        found = conditions_in(self.text())
        for number, mark, title in found:
            item = QListWidgetItem(f"{number:>2}  [{mark}]  {title}")
            if mark.strip() == "FAIL":
                item.setForeground(_FAIL_COLOUR)
            self._conditions.addItem(item)
        verdict = _VERDICT_RX.findall(self.text())
        if verdict:
            self._verdict.setText(f"verdict: {verdict[-1].strip()}")
        elif not found:
            self._verdict.setText(
                "this command printed no guard conditions")

    def _refresh_controls(self) -> None:
        """Enable exactly the controls the current state allows, and say why."""
        command = self._command
        idle = not self._active
        runnable = bool(command) and command.runnable()
        sends = bool(command) and command.sends
        for name, button in (("plan", self._plan_button),
                             ("pixelize", self._pixelize_button),
                             ("ledger", self._ledger_button)):
            why = self._free_blocked.get(name, "")
            button.setEnabled(idle and not why)
            button.setToolTip(why or BUTTON_TIPS[name])
            button.setStyleSheet(theme.LOCKED_STYLE if why else "")
        self._run_button.setEnabled(idle and runnable and not sends)
        # THE CLEARANCE TERM. `arm()` refuses without one and always has;
        # the button did not know that, so a press the guard was certain to
        # refuse raised RuntimeError out of a Qt slot and the user saw
        # nothing. A button the guard would refuse is not live.
        self._arm_button.setEnabled(
            idle and runnable and sends and not self._armed
            and not self._clearance())
        self._send_button.setEnabled(idle and self._armed)
        self._interrupt_button.setEnabled(self._active)
        self._banner.setText(self._banner_text())
        self._banner.setStyleSheet(
            theme.PROBLEM_STYLE if self._armed else theme.BANNER_STYLE)

    def _banner_text(self) -> str:
        """What the controls above will do, in words, before anything runs."""
        command = self._command
        if command is None:
            return "No command yet. Compose one and it will appear above."
        if self._active:
            return ("A child is running. Its output is below. Nothing is "
                    "queued behind it.")
        if not command.runnable():
            return f"This line cannot run: {command.blocked}"
        if not command.sends:
            return ("This command opens no socket and spends nothing. "
                    "Press Run.")
        subcommand = subcommand_of(command.argv)
        if self._armed:
            return (f"ARMED. Pressing SEND ONE REQUEST runs `{subcommand}` "
                    f"once: it opens one connection to NovelAI and sends "
                    f"one request against the live account, under this "
                    f"window's own environment. It is not a dry run, there "
                    f"is no retry, and the arm is dropped the moment the "
                    f"line changes or the command finishes.")
        problem = self._clearance()
        if problem:
            return f"Cannot arm `{subcommand}` yet: {problem}"
        if CLEARANCE.get(subcommand) == NO_DRY_RUN:
            return (f"`{subcommand}` opens a socket and has NO dry run in "
                    f"the CLI, so nothing has judged it offline. Arm it "
                    f"only if you mean to send it.")
        return (f"`{subcommand}` is cleared by the dry run above. Arm it to "
                f"unlock the send.")

    def _ask(self, subcommand: str) -> None:
        """Ask the window to compose `subcommand`; refuse a sending one."""
        if subcommand not in NO_NETWORK_BUTTONS:
            raise RuntimeError(
                f"this pane's own buttons ask only for "
                f"{list(NO_NETWORK_BUTTONS)}, never {subcommand!r}: a "
                f"command that opens a socket is composed by the window and "
                f"armed by hand")
        self.command_requested.emit(subcommand)

    def _ask_plan(self) -> None:
        """The Dry run button: compose and run `plan`."""
        self._ask("plan")

    def _ask_pixelize(self) -> None:
        """The Pixelize button: compose and run `pixelize`."""
        self._ask("pixelize")

    def _ask_ledger(self) -> None:
        """The Ledger button: compose and run `ledger`."""
        self._ask("ledger")

    def _refused(self, exc: RuntimeError) -> None:
        """Show a refusal the API raised, where the human can read it.

        `arm`, `start` and `interrupt` raise -- that is their contract and
        it does not change. A Qt SLOT must not: PySide6 prints the
        traceback to a terminal a window launched from a shortcut does not
        have, and the press then looks like a button that does nothing. So
        every slot below catches, and the refusal goes into the banner and
        out through `refused` for the window's status bar. No dialog
        (law 13).
        """
        self._banner.setText(str(exc))
        self._banner.setStyleSheet(theme.PROBLEM_STYLE)
        self.refused.emit(str(exc))

    def _run_clicked(self) -> None:
        """The Run button: start the shown non-sending command."""
        try:
            self.start()
        except RuntimeError as exc:
            self._refused(exc)

    def _arm_clicked(self) -> None:
        """The Arm button: the first of the two deliberate presses."""
        try:
            self.arm()
        except RuntimeError as exc:
            self._refused(exc)

    def _send_clicked(self) -> None:
        """The Send button: the second press. Runs once and disarms."""
        try:
            self.start()
        except RuntimeError as exc:
            self._refused(exc)

    def _interrupt_clicked(self) -> None:
        """The Interrupt button: a user action, never a watchdog."""
        try:
            self.interrupt()
        except RuntimeError as exc:
            self._refused(exc)
