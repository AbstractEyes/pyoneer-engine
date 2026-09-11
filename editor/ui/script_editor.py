"""The event screen: pages, an indented command list, a picker, and the box.

The author asked for this twice -- *"where is the event screen?"*, then
*"I still don't see any entity actions, scripting, or event-flow control in
the entity editing screen"* -- and the second half of that sentence is the
design, not the complaint:

    "The json scripting required human interactive utilization, the
     developer is likely not going to be coding anything, but instead will
     be communicating through the engine to the AI for curative changes."

So this is NOT a JSON editor with syntax colouring. It is a structured
screen for someone who never opens the file, plus a relay box aimed at the
script, so the sentence *"make the keeper ask for 100 coins instead of 50"*
is a gesture on the surface they are already standing on.

WHERE EVERY PART OF IT COMES FROM
---------------------------------
Nothing here decides what a script may say. Four layers already do, and
this module composes them:

    what an op IS, and what it may take    `scripts/game/flow/ops.py`
    whether a document would LOAD          `scripts/loaders/script_file.py`
                                           (through `ScriptDocument.validate`)
    where a node IS, and what may be set   `editor/core/event_script.py`
    every change                           the fourteen `script.*` verbs

THE READER IS STILL THE ONLY JUDGE, INCLUDING FOR WHAT THIS SCREEN OFFERS
------------------------------------------------------------------------
A picker has to grey a button that cannot act and say why (the palette's
header menu is the same rule). The tempting way to decide that is a table
in this file: *`set` needs a variable schema, `ask` needs one too, an op
outside the document's loadouts is out*. That table would be a second
implementation of the reader's rules living in a Qt module, and law 2's
corollary was paid for at 425 duplicate lines.

So `refusal_for` ASKS THE READER instead: it builds a throwaway one-page
document carrying the node the button would add and runs
`ScriptDocument.validate`, which is `script_file.parse_script`, which is
what the engine runs at boot. A button is greyed exactly when the engine
would refuse the node, with the engine's own sentence underneath it. An op
that becomes authorable -- because a scene finally declares its `vars`, or
because the document gains a loadout -- un-greys itself with no edit here.

The starting arguments come from the same place: an `OpSpec` carries an
`example` of itself, so `seed_for` parses that and drops `id` and `do`. A
new op ships its seed in the same commit that registers it, and this
module never learns a per-op fact.

PICKING IS NOT INSERTING
------------------------
RPG Maker's picker opens the chosen command's OWN form and the line lands
only once its arguments are filled. Same here, and for the same reason: a
picker that drops a bare node hands the author a broken script and then
makes them go and find the fields. `ArgumentForm` is that form, and it is
DERIVED -- one row per `BehaviorParam` the op declares, typed by that
declaration, one row per `OpArg` it declares dynamic, and nothing else. A
hand-written form per op would be a second home for the op's signature and
it would rot the first time somebody registered one, which is the failure
`docs/BEHAVIORS.md`'s categories already track.

The same form, populated, is what `Edit…` reopens on an existing node. Two
forms for one node is two places for the argument vocabulary to drift.

And Insert does not send blindly: the node it would make goes through
`refusal_for` -- the reader again -- and a refusal stays IN the form with
the field still filled in, because a rejection the author has to retype is
a rejection that costs them the sentence they had already written.

THE FORM IS NOT A DIALOG. It is a panel where the picker was, swapped in
and out with `setVisible`. `editor/ui/ask.py` is the editor's one dialog
seam and it stays that -- one decision, and the only decision on this
screen that is genuinely the author's alone is the ID OF A NEW SCRIPT.
An argument form is not that: it is the work, it wants the map and the
command list visible beside it, and `QuickForm` disables OK while any text
row is blank -- which would make `who`, the optional half of `say`, a
field an author cannot clear.

CONDITIONS ARE BUILT, NOT TYPED -- AND THE READER STILL JUDGES THEM
-------------------------------------------------------------------
A condition is a comparison RECORD with six closed comparators
(`docs/PLAN_SCENES.md` 3.4), never a string, precisely so that it renders
as a form with no parsing: a variable, one comparator from a list of six, a
value. So the same `ArgumentForm` builds one, and `+ when` / `− when`
author the list on a page and on an `if` alike.

What is NOT invented here is the variable schema. Only a scene's `vars`
block says whether a variable exists or what type it is; scenes are stage 6
of `docs/PLAN_SCENES.md`, and until one lands `ScriptLibrary.variables` is
None and the READER refuses every condition -- so the builder opens, the
sentence the reader would say at load is shown in it, and nothing is
written. Inventing a permissive schema to make the form look finished is
the plausible default law 7 forbids, and it would let an author write a
condition on a variable that will never exist. The moment a schema is in
hand the same builder writes, the variable row becomes the closed list of
declared names, and no line of this file changes.

`refusal_for_when` is how that judgement is asked, and it is the reason a
record carrying two comparators is refused HERE naming both: the rule is
the reader's, borrowed, not restated.

ASSISTANCE AT A PLACEMENT, NOT ONLY IN A CORNER
-----------------------------------------------
*"ease-of-assistance at most given placements"*, so the relay is offered at
two grains. `PromptStrip` at the bottom carries the whole script. The row
above the picker carries THE SAME ANCHOR THE PICKER WOULD HAVE USED -- the
page, the container, the arm and the sibling to follow -- so the request
says "insert here" instead of "somewhere in this script".

The anchor travels in the request TEXT, spelled in the verbs' own
vocabulary (`into` / `arm` / `after`), because `Scope` has no way to name a
node and a Scope kind is a permanent string that is not one module's to
mint. `anchor_sentence` is that spelling, and it is a transcription of what
`script.node.add` takes rather than a new notation.

The relay is an ACCELERATOR and never a dependency: every gesture above
works with it switched off, which `tools/check_script_editor.py` proves by
building a branching script that really runs without the relay being
touched once.

THE VIEW CHOICE, STATED
-----------------------
RPG Maker draws a nested branch as a FLAT list with a `Branch End` row.
This draws the real tree: `then` bodies hang under the `if` row, and
`else if` / `else` are DRAWN ARM HEADERS with the arm's nodes under them.
The file is genuinely nested (`docs/PLAN_SCENES.md` 3.4), containment is
what an insert has to address, and a flat rendering would have to invent a
row that is not a node and then explain why it cannot be selected. The one
thing borrowed from the flat rendering is that an empty body still draws a
row -- a dim placeholder carrying the address, so "put a command in this
else arm" is a click rather than a thing that cannot be said.

PAGES ARE A LIST, NOT TABS. `docs/PLAN_SCENES.md` 5.3's reason, kept: a tab
bar stops being readable past six, and list order IS evaluation order here
(the FIRST page whose `when` all pass runs), so a row that can be moved up
and down is the honest control for a semantic ordering.

NOT MODAL, AND IT MUST NEVER BECOME MODAL
-----------------------------------------
`show()`, never a blocking call (law 13). `tools/check_editor_ui.py`
censuses every `editor/ui/*.py` by `os.listdir` and fails on any blocking
call it finds, arguments or not. The one dialog this screen opens is
`editor/ui/ask.py`'s form, held as `self.ask` so a check can replace it --
and it opens for exactly one decision, the id of a new script, which cannot
be minted for the author because a script id is a FILE FORMAT string: it is
the file stem, the scope, and what `call` addresses it by.
"""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from editor.core import event_script
from editor.core.commands import Command
from editor.core.inspect import Field, Inspection, Section
from editor.core.scope import Scope
from editor.ui.ask import ask_form
from editor.ui.fields import InspectionView
from editor.ui.prompt import PromptStrip

from scripts.game.flow import ops as op_registry
from scripts.loaders.script_file import COMPARATORS, SCRIPT_PROPERTY

SCRIPT: str = SCRIPT_PROPERTY
"""The tmx object property naming the event script an object runs.

RE-EXPORTED, never composed here. A FILE FORMAT string, minted by
`docs/PLAN_SCENES.md` 4.6 and permanent under law 8, so the window that
WRITES it and the boot that READS it must spell it identically forever. It
was composed independently on both sides for a day; law 2's corollary says
shared logic lives in `scripts/` and the editor re-exports it, so the one
declaration is `script_file.SCRIPT_PROPERTY` and this name is an alias kept
because the rest of this file reads better for it.

It needs no verb of its own: `map.object.property.set` already writes it,
already has an exact inverse, and already refuses a reserved name.
"""

#: What the placeholder row in an empty body says. It is not a node: it
#: cannot be removed, it carries the address of the body it stands in, and
#: picking a command with it selected puts the first node exactly there.
NOTHING_YET = "(nothing here yet — pick a command below)"

NO_SCRIPTS = (
    "No event script in this project yet.\n\n"
    "A script is a document several objects can share: a keeper at a gate, "
    "a chest, a sign. Press New… to make one, then give an object its name "
    "in the entity screen."
)

NO_PAGES = (
    "This script has no page yet.\n\n"
    "A page is one way the script can answer: a trigger, the conditions "
    "that have to hold, and a list of commands. Pages are tried TOP DOWN "
    "and the first one whose conditions all pass is the one that runs, so "
    "the order of this list is the order it thinks in."
)

NO_PAGE_SELECTED = "Pick a page above to see what it does."

NO_NODE_SELECTED = (
    "Pick a row in the command list to edit what it says.\n\n"
    "With nothing selected, a command from the picker goes at the END of "
    "this page."
)

#: Why a condition row is not a text box. Never shown alone: the READER's
#: own sentence goes with it -- see `ScriptEditor.condition_note`.
CONDITIONS_ARE_BUILT = (
    "A condition is a comparison, not a sentence: a variable, one of six "
    "comparators, and a value. Build one with + when."
)

#: The empty state for a body of conditions, on a page and on an `if`.
NO_CONDITIONS = "always (no conditions)"

#: What the placement relay row says it will do. The anchor itself is
#: appended by `ScriptEditor.anchor_sentence`, which spells the verbs'
#: own `into` / `arm` / `after`.
ASK_HERE = (
    "Ask for a command here — the request carries this exact insertion "
    "point, not just the script."
)

#: The ids the throwaway document in `refusal_for` uses. They never reach a
#: file: that document is built, judged and dropped inside one call.
PROBE_PAGE = "probe_page"
PROBE_NODE = "probe_node"

#: What a page body is addressed by. `""` is a page's one body, and it is
#: also `NO_ANCHOR` -- the same empty string means two different things in
#: two different arguments, which is the verbs' own vocabulary.
PAGE_BODY = ""

_NOTE_STYLE = "color: palette(mid); font-size: 11px;"
_TITLE_STYLE = ("color: palette(mid); font-size: 10px; font-weight: 700; "
                "padding-top: 6px;")
_EMPTY_STYLE = "color: palette(mid); font-size: 12px; padding: 24px;"
_WARN_STYLE = ("background: rgba(255, 190, 90, 40); "
               "border-left: 3px solid rgb(255, 190, 90); "
               "padding: 6px 9px; font-size: 11px;")
_FOOTER_STYLE = "color: palette(mid); font-size: 11px; padding: 4px 2px;"


# --------------------------------------------------------------------------
# Rendering a node in words
# --------------------------------------------------------------------------

def value_words(value: Any) -> str:
    """One argument value as words rather than as JSON.

    `bool` is tested first because in Python `True` IS an int, so without
    the guard an `once` renders as `1` -- the same confusion
    `BehaviorParam.coerce` orders its branches to avoid.
    """
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "—"
    if isinstance(value, str):
        return '"%s"' % value
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(value_words(item) for item in value)
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def condition_words(condition: Any) -> str:
    """`{"var": "coins", "at_least": 100}` drawn as `coins at_least 100`.

    The comparator is FOUND rather than assumed. A condition carrying two
    operator keys is refused by the reader naming both, and a renderer that
    picked the first one would draw a legal-looking row for a document that
    does not load.
    """
    if not isinstance(condition, dict):
        return value_words(condition)
    name = condition.get("var", "?")
    parts = ["%s %s" % (key, value_words(condition[key]))
             for key in COMPARATORS if key in condition]
    return "%s %s" % (name, " and ".join(parts)) if parts else str(name)


def when_words(conditions: Any) -> str:
    """A whole `when` list. Empty always passes, and says so."""
    rows = list(conditions or ())
    if not rows:
        return "always"
    return " and ".join(condition_words(row) for row in rows)


def node_words(node: dict, table) -> str:
    """One row of the command list: the op, then its arguments in words.

    An op the registry does not know still renders -- marked, with its raw
    keys -- because refusing to draw a hand-edited document is how a typo
    becomes unfixable.
    """
    if "do" in node:
        spec = table.get(node["do"])
        if spec is None:
            keys = [k for k in node if k not in ("id", "do", "note")]
            if not keys:
                return "%s  ⚠ unknown op" % node["do"]
            return "%s  ⚠ unknown op  —  %s" % (
                node["do"], ", ".join("%s %s" % (k, value_words(node[k]))
                                      for k in keys))
        parts = ["%s %s" % (key, value_words(node[key]))
                 for key in spec.arg_keys if key in node]
        return "%s  —  %s" % (node["do"], ", ".join(parts)) if parts \
            else node["do"]
    kind = "if" if "if" in node else "while"
    return "%s  —  %s" % (kind, when_words(node.get(kind)))


def seed_for(spec) -> dict:
    """The arguments a newly picked op starts with, from its OWN example.

    Every `OpSpec` declares `example`: a legal node, written by whoever
    registered the op. Parsing it and dropping `id` and `do` gives a
    starting node that LOADS -- and it means a new op ships its seed in the
    same commit that registers it, rather than this module growing a table
    of per-op knowledge that can disagree with the registry in silence.

    An op with no example, or one whose example is not a JSON object, falls
    back to the declared defaults of the arguments it requires. If that is
    not enough the reader refuses the node and the button is greyed with
    the reason, which is the correct outcome rather than a gap.
    """
    raw = getattr(spec, "example", None)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return {k: v for k, v in parsed.items()
                    if k not in ("id", "do", "note")}
    return {p.key: p.default for p in spec.params if p.required}


def one_line(text: str, *, limit: int = 240) -> str:
    """A reader's refusal on one line, for a label that has room for one.

    The reader blames a fault by PATH first and puts the sentence on the
    next line, so taking `splitlines()[0]` -- which is what a status bar
    does -- yields `keeper_gate.json pages[0] 'probe_page' body[0]` and
    none of the reason. Whitespace-collapsing keeps the whole sentence.
    """
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def mint(taken, prefix: str) -> str:
    """The first `prefix<n>` no page and no node in this document claims.

    An id has to be minted somewhere: something must produce one when a
    command is added. It is minted ONCE, here, and then never changes. What
    `docs/PLAN_SCENES.md` 3.4 refuses is an id minted at SAVE time, which
    moves under a relay response that addressed it.
    """
    used = set(taken)
    index = 1
    while "%s%d" % (prefix, index) in used:
        index += 1
    return "%s%d" % (prefix, index)


def refusal_for(document, node: dict, *, variables, registry) -> str:
    """`""` if the reader would accept this node here, else its refusal.

    THE PICKER'S ONE PIECE OF JUDGEMENT, AND IT BORROWS IT. A throwaway
    one-page document is built carrying `node` and nothing else, and
    `ScriptDocument.validate` -- which is `script_file.parse_script`, which
    is what the engine runs at boot -- decides. So the greying covers every
    reason at once, present and future, with no list in this file: an op
    outside the document's `loadouts`, an op naming a variable when no
    scene has declared one, an argument the op's own `check` refuses.

    The document's real `loadouts` travel with the trial, because that is
    one of the things being asked about. Its pages do not: the question is
    whether THIS node loads, and a document that is already broken
    elsewhere would grey every button for a reason that has nothing to do
    with the one being pressed.
    """
    trial = event_script.ScriptDocument(
        id=document.id, title=document.title,
        loadouts=list(document.loadouts),
        pages=[{"id": PROBE_PAGE, "trigger": "use", "when": [],
                "body": [dict(node, id=PROBE_NODE)]}])
    try:
        trial.validate(variables=variables, registry=registry)
    except Exception as exc:                                    # noqa: BLE001
        # Broad on purpose: the reader raises several kinds and the picker
        # wants the SENTENCE, not the class. A narrower catch here would
        # let one refusal shape through as a traceback out of a paint.
        return str(exc)
    return ""


def refusal_for_when(document, conditions, *, variables, registry) -> str:
    """`""` if the reader would accept this `when` list, else its refusal.

    The same borrow as `refusal_for`, aimed at the other half of the format.
    It is what makes the condition builder honest about the two things it
    cannot decide for itself: whether a variable exists at all, and whether
    a record is a legal comparison.

    A record carrying `at_least` AND `at_most` is refused HERE naming both,
    because the sentence comes from `_read_condition`. Restating that rule
    in this module would be the second implementation law 2's corollary was
    paid 425 lines for -- and it would drift the first time a seventh
    comparator was added.
    """
    trial = event_script.ScriptDocument(
        id=document.id, title=document.title,
        loadouts=list(document.loadouts),
        pages=[{"id": PROBE_PAGE, "trigger": "use",
                "when": list(conditions or ()), "body": []}])
    try:
        trial.validate(variables=variables, registry=registry)
    except Exception as exc:                                    # noqa: BLE001
        return str(exc)
    return ""


def argument_value(raw: Any) -> Any:
    """What an author typed into a row whose type nothing declares.

    An `OpArg` carries no type on purpose -- `set`'s `to` is whatever the
    variable it names was declared as, and `ask`'s `options` is a list --
    so there is nothing here to coerce AGAINST. JSON is the one reading
    that covers every shape the format can hold, and text that is not JSON
    stays the text it is: `Pay half` is a string, `100` is a number,
    `["a", "b"]` is a list.

    This is a READING and not a fallback. Nothing is invented when it
    fails: the value goes to the reader as typed, and `set`'s own `check`
    refuses a string handed to an int variable, naming both.
    """
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except ValueError:
        return raw


# --------------------------------------------------------------------------
# The argument form -- what a pick opens, and what an edit reopens
# --------------------------------------------------------------------------

class ArgumentForm(QWidget):
    """One `Field` per row, an Insert button, and a place for a refusal.

    NOT A DIALOG. It takes the picker's place in the column and gives it
    back, so the command list, the page and the map stay visible while an
    argument is being written -- and so law 13 has nothing to catch.

    It knows about `Field.kind` and about nothing else. The rows come from
    the op's own declaration (`ScriptEditor.argument_fields`) or from the
    six closed comparators (`ScriptEditor.condition_fields`), and this
    class cannot tell which -- which is exactly why registering an op makes
    its form appear with no edit here.
    """

    accepted = Signal(dict)         # {key: value}, typed by the row's kind
    cancelled = Signal()

    #: The tri-state row's first entry. A `BehaviorParam` whose declared
    #: default is None means "absent and null both pass", so "leave it out"
    #: is a real answer and not an empty string pretending to be one.
    LEAVE_OUT = "— leave it out —"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.rows: list[Field] = []
        self.editors: dict[str, QWidget] = {}
        self.title = QLabel("")
        self.title.setStyleSheet(_TITLE_STYLE)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(_NOTE_STYLE)
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(_WARN_STYLE)
        self.problem.hide()

        self.area = QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setWidget(QWidget())

        self.ok_button = QPushButton("Insert")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.title)
        column.addWidget(self.note)
        column.addWidget(self.area, 1)
        column.addWidget(self.problem)
        column.addLayout(buttons)

    # -- opening -----------------------------------------------------------

    def open(self, title: str, rows, *, note: str = "",
             ok_label: str = "Insert") -> None:
        """Show these rows. Replaces whatever was in it."""
        self.rows = list(rows)
        self.editors = {}
        self.title.setText(title)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.ok_button.setText(ok_label)
        self.refuse("")

        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(2, 2, 2, 2)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for entry in self.rows:
            editor = self.__editor_for(entry)
            if entry.doc:
                editor.setToolTip(entry.doc)
            self.editors[entry.key] = editor
            form.addRow(entry.label, editor)
        # Law 12's one correct sequence, spelled the way `InspectionView`
        # spells it: never `setParent(None)`, and never free the old body
        # while the signal that replaced it is still on the stack.
        old = self.area.takeWidget()
        if old is not None:
            old.setParent(self)
            old.hide()
            old.deleteLater()
        self.area.setWidget(body)
        self.show()
        first = self.editors.get(self.rows[0].key) if self.rows else None
        if first is not None:
            first.setFocus()

    def __editor_for(self, entry: Field) -> QWidget:
        if entry.kind == "choice":
            combo = QComboBox(self)
            combo.addItems([str(choice) for choice in entry.choices])
            combo.setCurrentText(str(entry.value))
            return combo
        if entry.kind == "bool":
            combo = QComboBox(self)
            # A tri-state param -- one whose declared default is None --
            # gets the third answer. Rendering it as a two-way tickbox
            # would make "leave it out" unsayable, and `hold` is three of
            # them: clearing one axis and leaving the others alone is the
            # gesture the op exists for.
            tri = entry.value is None or self.LEAVE_OUT in entry.choices
            if tri:
                combo.addItem(self.LEAVE_OUT)
            combo.addItems(["true", "false"])
            combo.setCurrentText(self.LEAVE_OUT if entry.value is None
                                 else ("true" if entry.value else "false"))
            return combo
        if entry.kind == "int":
            spin = QSpinBox(self)
            spin.setRange(-10 ** 7, 10 ** 7)
            spin.setValue(int(entry.value or 0))
            return spin
        if entry.kind == "float":
            spin = QDoubleSpinBox(self)
            spin.setRange(-10.0 ** 7, 10.0 ** 7)
            spin.setDecimals(3)
            spin.setValue(float(entry.value or 0.0))
            return spin
        line = QLineEdit(self)
        line.setText("" if entry.value is None else str(entry.value))
        return line

    # -- reading -----------------------------------------------------------

    def values(self) -> dict:
        """What is in the form right now, typed by each row's kind."""
        answer: dict = {}
        for entry in self.rows:
            editor = self.editors.get(entry.key)
            if editor is None:
                continue
            if isinstance(editor, QComboBox):
                text = editor.currentText()
                if entry.kind == "bool":
                    answer[entry.key] = (None if text == self.LEAVE_OUT
                                         else text == "true")
                else:
                    answer[entry.key] = text
            elif isinstance(editor, QSpinBox):
                answer[entry.key] = int(editor.value())
            elif isinstance(editor, QDoubleSpinBox):
                answer[entry.key] = float(editor.value())
            else:
                answer[entry.key] = editor.text()
        return answer

    def labels(self) -> list[str]:
        """Every row label, in order. What a check reads."""
        return [entry.label for entry in self.rows]

    def keys(self) -> list[str]:
        return [entry.key for entry in self.rows]

    # -- answering ---------------------------------------------------------

    def refuse(self, message: str) -> None:
        """Say why this cannot be inserted, and keep the form open.

        The values stay: a refusal that made the author retype their line
        would cost them the work rather than the press.
        """
        self.problem.setText(message)
        self.problem.setVisible(bool(message))

    def accept(self) -> None:
        self.accepted.emit(self.values())

    def cancel(self) -> None:
        self.hide()
        self.cancelled.emit()


# --------------------------------------------------------------------------
# The picker
# --------------------------------------------------------------------------

class OpPicker(QWidget):
    """Every registered op as a button, grouped by loadout, badged.

    Built from the REGISTRY and never from a list in this file, so an op
    that is registered is offered and one that is not cannot be picked --
    the property `docs/EVENTS.md` measures as "an editor module reaches the
    op registry".

    Core is the first section and its buttons carry NO badge: portability
    is the default, so its absence is the signal. Every other loadout badges
    every one of its buttons, which answers "does this script port?" by
    scanning rather than by opening anything.
    """

    chosen = Signal(str)        # an op name, or a control kind

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        #: {op name: its button}. The control shapes are NOT in here -- see
        #: `control_buttons`. `op_names()` is exactly the registry.
        self.buttons: dict[str, QPushButton] = {}
        #: {"if": button, "while": button}. A control node is not an op and
        #: never enters the registry: one word cannot mean both, which is
        #: what `script.node.add` refuses loudly if an op ever claims one.
        self.control_buttons: dict[str, QPushButton] = {}
        #: {op name: the reader's refusal}, for every op that cannot be
        #: added to this document right now.
        self.blocked: dict[str, str] = {}
        self.__sections: list[tuple[QLabel, list[QPushButton]]] = []

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("search the commands…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.__filter())

        self.core_only = QCheckBox("core only", self)
        self.core_only.setToolTip(
            "Hide everything that is not portable. A script built from core "
            "alone runs unchanged in every game mode.")
        self.core_only.toggled.connect(lambda _v: self.__filter())

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.search, 1)
        top.addWidget(self.core_only)

        self.area = QScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setWidget(QWidget())

        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        self.note.setStyleSheet(_NOTE_STYLE)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addLayout(top)
        column.addWidget(self.area, 1)
        column.addWidget(self.note)

    # -- building ----------------------------------------------------------

    def op_names(self) -> list[str]:
        """Exactly the ops this picker is offering, sorted."""
        return sorted(self.buttons)

    def rebuild(self, table, *, declared, refusal) -> None:
        """Draw one button per registered op. `refusal(name) -> str`.

        `declared` is the document's own `loadouts`, used only for the
        section headers -- whether a button can ACT is `refusal`'s answer,
        because the reader is the judge of that and a second rule here
        could disagree with it.
        """
        self.buttons.clear()
        self.control_buttons.clear()
        self.blocked.clear()
        self.__sections.clear()

        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(2, 2, 2, 2)
        column.setSpacing(2)

        for loadout in op_registry.loadouts(table):
            specs = [s for s in op_registry.ops_in((loadout,), table)]
            if not specs:
                continue
            head = "%s%s" % (loadout.upper(),
                             "" if loadout in declared
                             else "   (this script does not declare it)")
            column.addWidget(self.__heading(head))
            grid, holder = self.__grid()
            column.addWidget(holder)
            row = self.__sections[-1][1]
            for index, spec in enumerate(specs):
                button = self.__button(spec, refusal(spec.name))
                self.buttons[spec.name] = button
                row.append(button)
                grid.addWidget(button, index // 4, index % 4)

        column.addWidget(self.__heading("CONTROL — the flow itself"))
        grid, holder = self.__grid()
        column.addWidget(holder)
        row = self.__sections[-1][1]
        for index, kind in enumerate(event_script.CONTROL_KINDS):
            button = QPushButton(kind, self)
            button.setToolTip(
                "%s — a branch, filled by picking commands with one of its "
                "arms selected. Its condition is a `when` list, which is "
                "read-only on this screen for the same reason a page's is."
                % kind)
            button.clicked.connect(
                lambda _c=False, k=kind: self.chosen.emit(k))
            self.control_buttons[kind] = button
            row.append(button)
            grid.addWidget(button, 0, index)

        column.addStretch(1)
        # The one correct sequence law 12 names, spelled the way
        # `InspectionView` spells it: never `setParent(None)`, which
        # promotes a widget to a top-level window, and never free the old
        # body while the signal that replaced it is still on the stack.
        old = self.area.takeWidget()
        if old is not None:
            old.setParent(self)
            old.hide()
            old.deleteLater()
        self.area.setWidget(body)
        self.__say_blocked()
        self.__filter()

    def __heading(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setStyleSheet(_TITLE_STYLE)
        self.__sections.append((label, []))
        return label

    def __grid(self) -> tuple[QGridLayout, QWidget]:
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        return grid, holder

    def __button(self, spec, refusal: str) -> QPushButton:
        """One op. Badged with its loadout, marked when it does not run."""
        label = spec.name if spec.loadout == op_registry.CORE \
            else "%s · %s" % (spec.name, spec.loadout)
        if spec.status != "live":
            label += " ⚠"
        button = QPushButton(label, self)
        button.setProperty("op", spec.name)
        button.setProperty("loadout", spec.loadout)
        tip = [spec.summary]
        if spec.status != "live":
            # AUTHORABLE AND MARKED, never hidden: `docs/EVENTS.md` measures
            # this column and the screen must not contradict it.
            tip.append("status %s — it can be authored now; it does not run "
                       "yet." % spec.status)
        if refusal:
            self.blocked[spec.name] = refusal
            button.setEnabled(False)
            tip.append("Cannot be added here: " + refusal)
        else:
            button.clicked.connect(
                lambda _c=False, n=spec.name: self.chosen.emit(n))
        button.setToolTip("\n\n".join(tip))
        return button

    def __say_blocked(self) -> None:
        """List every greyed op with the reader's reason, permanently.

        A tooltip is not enough: a DISABLED widget receives no mouse events,
        so its tooltip never opens and the reason is unreachable by hand.
        The reasons therefore live in a label under the grid, where they can
        be read without hovering anything.
        """
        if not self.blocked:
            self.note.setText("")
            self.note.hide()
            return
        lines = ["These cannot be added to this script yet — the engine's "
                 "own reader says why:"]
        for name in sorted(self.blocked):
            lines.append("· %s — %s" % (name, one_line(self.blocked[name])))
        self.note.setText("\n".join(lines))
        self.note.show()

    def __filter(self) -> None:
        """Hide what does not match, and hide a heading with nothing under
        it. `setVisible`, never `setParent` (law 12)."""
        wanted = self.search.text().strip().lower()
        core_only = self.core_only.isChecked()
        for heading, buttons in self.__sections:
            shown = 0
            for button in buttons:
                name = button.property("op") or button.text()
                loadout = button.property("loadout")
                ok = (not wanted or wanted in name.lower()
                      or wanted in (button.toolTip() or "").lower())
                if core_only and loadout not in (None, op_registry.CORE):
                    ok = False
                button.setVisible(ok)
                shown += 1 if ok else 0
            heading.setVisible(bool(shown))


# --------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------

class ScriptEditor(QMainWindow):
    """One event script at a time, and every change is a `script.*` verb."""

    command_requested = Signal(object)      # a Command, or a list of them

    #: Which item role holds what, on every row of the command tree. The
    #: node id is a STRING in `Qt.UserRole`, the way `HierarchyDock` stores
    #: its identity: a command rebuilds the widget wholesale and an
    #: index-keyed selection lands on the wrong row.
    NODE_ROLE = Qt.UserRole
    INTO_ROLE = Qt.UserRole + 1
    ARM_ROLE = Qt.UserRole + 2
    KIND_ROLE = Qt.UserRole + 3         # "node" | "arm" | "empty"

    def __init__(self, session, script_id: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._script_id = script_id
        #: Which page and which command are being looked at, as IDS. Never
        #: as indices: a command rebuilds the widgets wholesale and an
        #: index-keyed selection slides onto whatever now sits at that row.
        self.__page_id = ""
        self.__node_id = ""
        self.__rebuilding = False
        self.__last: tuple | None = None
        #: Whatever this window last said, whether or not a status bar heard
        #: it. A check drives this window without an `EditorWindow` around
        #: it, and "the gesture reported something" has to stay assertable.
        self.last_notice = ""
        # The dialog seam, held on the instance so a check can replace it.
        # See `editor/ui/ask.py`: one decision, and it is the author's --
        # a script id is the file stem, the scope and what `call` names.
        self.ask = ask_form

        self.setWindowFlag(Qt.Window, True)
        self.resize(1280, 820)

        # -- left: the scripts in this project ---------------------------
        left = QWidget()
        left_column = QVBoxLayout(left)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(3)
        left_column.addWidget(self.__heading("SCRIPTS"))
        self.script_list = QListWidget()
        self.script_list.currentItemChanged.connect(self.__on_pick_script)
        left_column.addWidget(self.script_list, 1)
        self.new_button = QPushButton("New…")
        self.new_button.setToolTip(
            "Create an event script. You choose its name: that name is the "
            "file, the address and what another script's `call` names, so "
            "it cannot be picked for you.")
        self.new_button.clicked.connect(self.create_script)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_script)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.delete_button)
        left_column.addLayout(buttons)
        self.document_view = InspectionView(show_header=False,
                                            show_sources=False)
        self.document_view.command_requested.connect(self.__on_command)
        left_column.addWidget(self.document_view, 1)

        # -- middle: the pages, the page, and the commands ----------------
        middle = QWidget()
        middle_column = QVBoxLayout(middle)
        middle_column.setContentsMargins(0, 0, 0, 0)
        middle_column.setSpacing(3)
        middle_column.addWidget(self.__heading("PAGES — tried top down, the "
                                               "first that passes runs"))
        self.page_list = QListWidget()
        self.page_list.setMaximumHeight(120)
        self.page_list.currentItemChanged.connect(self.__on_pick_page)
        middle_column.addWidget(self.page_list)
        self.page_buttons = self.__button_row(middle_column, (
            ("+ page", "Add a page after the selected one.", self.add_page),
            ("− page", "Remove the selected page. Ctrl+Z brings it back "
                       "with every command on it.", self.remove_page),
            ("▲", "Move it earlier — an earlier page shadows a later one "
                  "whose conditions also pass.", lambda: self.move_page(-1)),
            ("▼", "Move it later.", lambda: self.move_page(1)),
            ("+ when", "Add a condition this page has to pass: a variable, "
                       "one of six comparators, and a value.",
             lambda: self.add_condition("page")),
            ("− when", "Take the last condition off this page. An empty "
                       "list always passes.",
             lambda: self.remove_condition("page")),
        ))
        self.page_view = InspectionView(show_header=False, show_sources=False)
        self.page_view.command_requested.connect(self.__on_command)
        self.page_view.setMaximumHeight(260)
        middle_column.addWidget(self.page_view)

        middle_column.addWidget(self.__heading("COMMANDS"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(self.__on_pick_node)
        # THE GESTURE RPG MAKER TRAINED EVERYONE ON: double-click, or Enter,
        # on the blank line at the end of a body opens the picker AT that
        # position. `itemActivated` is both of those in one signal, and the
        # row is already the insertion target by the time it fires.
        self.tree.itemActivated.connect(
            lambda _item, _column=0: self.open_picker_here())
        middle_column.addWidget(self.tree, 1)
        self.node_buttons = self.__button_row(middle_column, (
            ("Edit…", "Reopen this command's own form, filled in. The SAME "
                      "form the picker opened when it was inserted.",
             self.edit_node),
            ("− command", "Remove the selected command and everything under "
                          "it. Ctrl+Z puts it back in the same arm.",
             self.remove_node),
            ("▲", "Move it up among its siblings.",
             lambda: self.move_node(-1)),
            ("▼", "Move it down among its siblings.",
             lambda: self.move_node(1)),
            ("+ else-if", "Give the selected `if` another arm. Its condition "
                          "is authored through the box below.",
             self.add_arm),
            ("− else-if", "Take the last else-if arm off the selected `if`, "
                          "with everything in it. Ctrl+Z is exact.",
             self.remove_arm),
            ("+ when", "Add a condition to the selected `if` or `while`.",
             lambda: self.add_condition("node")),
            ("− when", "Take the last condition off the selected `if` or "
                       "`while`. An empty list always passes.",
             lambda: self.remove_condition("node")),
        ))

        # THE RELAY AT A PLACEMENT. The same anchor the picker would use,
        # spelled into the request text -- see `anchor_sentence`. It sits
        # ABOVE the picker because it answers the same question the picker
        # does ("what goes here"), and an author who cannot find the
        # command they want should not have to cross the window to ask.
        self.here_field = QLineEdit()
        self.here_field.setPlaceholderText(
            "…or say what should happen here, and let the AI write it")
        self.here_field.returnPressed.connect(self.ask_here)
        self.here_button = QPushButton("Ask here")
        self.here_button.setDefault(False)
        self.here_button.setAutoDefault(False)
        self.here_button.setToolTip(ASK_HERE)
        self.here_button.clicked.connect(self.ask_here)
        here_row = QHBoxLayout()
        here_row.setContentsMargins(0, 0, 0, 0)
        here_row.setSpacing(3)
        here_row.addWidget(self.here_field, 1)
        here_row.addWidget(self.here_button)
        middle_column.addLayout(here_row)

        self.picker = OpPicker()
        self.picker.chosen.connect(self.pick_op)
        middle_column.addWidget(self.picker, 1)
        # The form takes the picker's place while it is open. Both are
        # ordinary children shown and hidden with `setVisible`; neither is
        # ever re-parented to nothing (law 12) and neither is a dialog.
        self.form = ArgumentForm()
        self.form.accepted.connect(self.__on_form_accepted)
        self.form.cancelled.connect(self.close_form)
        self.form.hide()
        middle_column.addWidget(self.form, 1)
        #: What the open form will do when it is accepted, or None. One of
        #: ("add", do, into, arm, after), ("edit", node_id) or
        #: ("when", "page"|"node", target_id).
        self.form_intent: tuple | None = None

        # -- right: the selected command ---------------------------------
        self.node_view = InspectionView(show_header=False, show_sources=False)
        self.node_view.command_requested.connect(self.__on_command)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(middle)
        split.addWidget(self.node_view)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([260, 700, 320])
        self.splitter = split

        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(_WARN_STYLE)
        self.problem.hide()
        column.addWidget(self.problem)
        self.empty = QLabel(NO_SCRIPTS)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(_EMPTY_STYLE)
        column.addWidget(self.empty)
        column.addWidget(split, 1)

        # THE RELAY BOX, aimed at the SCRIPT. This is the author's stated
        # working mode -- stand on the thing, say one sentence about it,
        # send it now -- and the scope is what makes the bundle small: only
        # the fourteen verbs that can touch a script travel with it.
        self.strip = PromptStrip(session, self.scope)
        column.addWidget(self.strip)

        self.footer = QLabel("")
        self.footer.setWordWrap(True)
        self.footer.setStyleSheet(_FOOTER_STYLE)
        column.addWidget(self.footer)
        self.setCentralWidget(holder)

        # Qt shortcuts are per-window, so a promise that only works in the
        # OTHER window is worse than no promise. These forward; the stream
        # is still the parent's.
        for text, sequence, name in (("&Undo", QKeySequence.Undo, "undo"),
                                     ("&Redo", QKeySequence.Redo, "redo"),
                                     ("&Save", QKeySequence.Save, "save")):
            action = QAction(text, self)
            action.setShortcut(sequence)
            action.triggered.connect(
                lambda _checked=False, n=name: self.__forward(n))
            self.addAction(action)

        self.refresh()

    # -- small builders ----------------------------------------------------

    def __heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(_TITLE_STYLE)
        return label

    def __button_row(self, column, entries) -> dict[str, QPushButton]:
        holder = QHBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.setSpacing(3)
        made: dict[str, QPushButton] = {}
        for text, tip, slot in entries:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, s=slot: s())
            holder.addWidget(button)
            made[text] = button
        holder.addStretch(1)
        column.addLayout(holder)
        return made

    # -- what this window is aimed at --------------------------------------

    @property
    def script_id(self) -> str:
        return self._script_id

    @property
    def scope(self) -> Scope:
        """The script scope, or the project when none is open.

        Never an empty scope: `Scope` refuses one, and the prompt strip is
        built before a script is picked.
        """
        return Scope.of(("script", self._script_id)) if self._script_id \
            else Scope.of("project")

    def set_script(self, script_id: str) -> None:
        """Aim this window at another script. ONE window, re-aimed."""
        if script_id == self._script_id:
            self.refresh()
            return
        self.commit_in_flight()
        # An open form belongs to the document it was opened on: its
        # anchor is a node id in THAT document, and a node id is only
        # unique inside one.
        self.close_form()
        self._script_id = script_id
        self.refresh()

    # -- the library, which may refuse to load -----------------------------

    @property
    def library(self):
        """The project's script library, or None when it will not load.

        A document with an op the registry does not know is refused at
        LOAD, by the reader, for the whole library -- so this window has to
        survive that rather than take the editor down with it. `refresh`
        turns the exception into the empty state, with the reader's
        sentence in it, which is how a typo stays fixable.
        """
        try:
            return event_script.scripts_of(self.session.project)
        except Exception as exc:                                # noqa: BLE001
            self.report(str(exc))
            return None

    @property
    def registry(self):
        """The op table this window offers, NARROWED to the project's genre.

        One property, because every reader in this window already goes
        through it -- the picker, the loadout toggles, the node words, the
        refusals -- so narrowing here gives them all the same answer and
        none of them grows a second opinion about membership.

        A pack that does not declare `event_loadouts` is silent and gets the
        table back by identity, which is why wiring this in changed nothing
        for either shipped pack.
        """
        library = self.library
        table = getattr(library, "registry", None)
        base = op_registry.OP_REGISTRY if table is None else table
        return self.session.project.genre.granted_registry(base)

    @property
    def grants_nothing(self) -> bool:
        """The pack withholds every loadout, so this genre does not script.

        Said as one sentence by `__refresh` rather than left to surface as
        every op in every document reading as unknown. An empty grant is a
        STATEMENT a pack makes, and a window that renders it as ten broken
        ops is reporting the author's own decision back at them as damage.
        """
        return bool(op_registry.OP_REGISTRY) and not self.registry

    @property
    def document(self):
        library = self.library
        if library is None or not self._script_id \
                or not library.has(self._script_id):
            return None
        return library.document(self._script_id)

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the whole screen from the document.

        Never raises: a script can go away under this window on an undo,
        and the answer is a message in the frame rather than a traceback
        through the event loop.
        """
        self.report("")
        self.__last = None
        self.__rebuilding = True
        views = (self.document_view, self.page_view, self.node_view)
        retiring = [(view, view.widget()) for view in views]
        try:
            self.__refresh()
            for view, body in retiring:
                if body is not None and body is not view.widget():
                    self.__silence(body)
        except Exception as exc:                                # noqa: BLE001
            self.report("%s: %s" % (type(exc).__name__, exc))
        finally:
            self.__rebuilding = False
        self.setWindowTitle(self.__title())

    @staticmethod
    def __silence(body: QWidget) -> None:
        """A form that has been replaced does not speak again.

        `InspectionView` retires a body with `deleteLater`, which does not
        run until an event loop unwinds -- so the old form is alive, still
        connected, and still able to emit `editingFinished` the moment Qt
        takes the focus off it, landing a command a SECOND time against a
        snapshot of the value from before. Measured in
        `ObjectEditor.__silence`, which is where the whole story is.
        """
        body.blockSignals(True)
        for inner in body.findChildren(QWidget):
            inner.blockSignals(True)

    def __refresh(self) -> None:
        library = self.library
        names = library.names() if library is not None else []
        self.__fill_scripts(names)

        if self.grants_nothing:
            # The pack's own statement, in the window's words. Said BEFORE
            # the document is drawn, because the alternative is a tree full
            # of ops reported as unknown for a reason that is not a typo.
            self.report(
                "The '%s' genre grants no op loadouts, so scripting is off "
                "for this project. Add a loadout name to this pack's "
                "event_loadouts to turn it back on."
                % self.session.project.genre.id)

        document = self.document
        self.empty.setVisible(document is None)
        self.splitter.setVisible(document is not None)
        self.delete_button.setEnabled(document is not None)
        if document is None:
            self.empty.setText(
                NO_SCRIPTS if not names else
                "Pick a script on the left, or press New… to make another.")
            self.strip.set_scope(self.scope)
            self.footer.setText(self.__footer())
            return

        self.document_view.show_inspection(self.__describe_document(document))
        self.__fill_pages(document)
        page = self.current_page()
        self.page_view.show_inspection(self.__describe_page(document, page))
        self.__fill_tree(document, page)
        self.picker.rebuild(
            self.registry, declared=tuple(document.loadouts),
            refusal=lambda name: self.refusal_for_op(document, name))
        self.node_view.show_inspection(self.__describe_node(document))
        self.__sync_buttons(document, page)
        self.strip.set_scope(self.scope)
        self.footer.setText(self.__footer())

    def __title(self) -> str:
        document = self.document
        if document is None:
            return "Events — %s" % self.session.project.genre.title
        return "%s — script:%s" % (document.title or document.id, document.id)

    def __footer(self) -> str:
        library = self.library
        dirty = library.dirty_scripts() if library is not None else []
        head = ("Every change here is one undoable command: Ctrl+Z takes "
                "back exactly one, Ctrl+S writes the scripts to disk.")
        if dirty:
            head += "   Not on disk yet: %s." % ", ".join(dirty)
        return head

    def __fill_scripts(self, names) -> None:
        self.script_list.blockSignals(True)
        self.script_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.script_list.addItem(item)
            if name == self._script_id:
                self.script_list.setCurrentItem(item)
        self.script_list.blockSignals(False)

    def __fill_pages(self, document) -> None:
        wanted = self.__page_id
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for page in document.pages:
            label = "%s   %s   %s" % (page["id"], page.get("trigger", "use"),
                                      when_words(page.get("when")))
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, page["id"])
            self.page_list.addItem(item)
        if document.pages:
            ids = document.page_ids()
            index = ids.index(wanted) if wanted in ids else 0
            self.page_list.setCurrentRow(index)
            self.__page_id = ids[index]
        else:
            self.__page_id = ""
        self.page_list.blockSignals(False)

    def current_page(self) -> dict | None:
        document = self.document
        if document is None or not self.__page_id:
            return None
        try:
            return document.page(self.__page_id)
        except Exception:                                       # noqa: BLE001
            return None

    def current_node(self) -> dict | None:
        document = self.document
        if document is None or not self.__node_id:
            return None
        try:
            return document.node(self.__node_id)
        except Exception:                                       # noqa: BLE001
            return None

    # -- the command tree --------------------------------------------------

    def __fill_tree(self, document, page) -> None:
        self.tree.blockSignals(True)
        # `clear()` is right here and nowhere else in this file: a
        # QTreeWidgetItem is not a QWidget, so law 12's re-parenting trap
        # does not apply -- the items are owned and destroyed by the tree.
        self.tree.clear()
        if page is not None:
            self.__draw_body(self.tree.invisibleRootItem(), page["id"],
                             PAGE_BODY, page.get("body") or ())
        self.tree.expandAll()
        self.__select_node(self.__node_id)
        self.tree.blockSignals(False)

    def __draw_body(self, parent, into: str, arm: str, body) -> None:
        if not body:
            item = QTreeWidgetItem(parent, [NOTHING_YET])
            self.__stamp(item, "", into, arm, "empty")
            item.setForeground(0, self.palette().mid())
            return
        table = self.registry
        for node in body:
            item = QTreeWidgetItem(parent, [node_words(node, table)])
            self.__stamp(item, node["id"], into, arm, "node")
            if node.get("note"):
                item.setToolTip(0, node["note"])
            if "do" in node:
                continue
            kind = "if" if "if" in node else "while"
            self.__draw_body(item, node["id"], "then",
                             node.get("then") or ())
            if kind != "if":
                continue
            for index, entry in enumerate(node.get("elif") or ()):
                header = QTreeWidgetItem(
                    item, ["else if  —  %s" % when_words(entry.get("when"))])
                self.__stamp(header, "", node["id"], "elif:%d" % index, "arm")
                self.__draw_body(header, node["id"], "elif:%d" % index,
                                 entry.get("then") or ())
            # ALWAYS drawn, even when the canonical rendering has dropped an
            # empty one. Without the header the else arm has no address, and
            # "put something in the else" would be a thing the screen cannot
            # say; `script.node.add` materialises the key.
            header = QTreeWidgetItem(item, ["else"])
            self.__stamp(header, "", node["id"], "else", "arm")
            self.__draw_body(header, node["id"], "else",
                             node.get("else") or ())

    def __stamp(self, item, node_id: str, into: str, arm: str,
                kind: str) -> None:
        item.setData(0, self.NODE_ROLE, node_id)
        item.setData(0, self.INTO_ROLE, into)
        item.setData(0, self.ARM_ROLE, arm)
        item.setData(0, self.KIND_ROLE, kind)

    def __walk(self):
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            yield item
            stack = [item.child(i) for i in range(item.childCount())] + stack

    def tree_rows(self) -> list[dict]:
        """Every drawn row as data: depth, text, and the address it carries.

        Public because it is what a check reads, and because "what does the
        command list actually show" should not require walking Qt.
        """
        rows = []
        for item in self.__walk():
            depth = -1
            walker = item
            while walker is not None:
                walker = walker.parent()
                depth += 1
            rows.append({
                "depth": depth,
                "text": item.text(0),
                "node": item.data(0, self.NODE_ROLE) or "",
                "into": item.data(0, self.INTO_ROLE) or "",
                "arm": item.data(0, self.ARM_ROLE) or "",
                "kind": item.data(0, self.KIND_ROLE) or "",
            })
        return rows

    def __select_node(self, node_id: str) -> None:
        for item in self.__walk():
            if node_id and item.data(0, self.NODE_ROLE) == node_id:
                self.tree.setCurrentItem(item)
                return
        self.__node_id = ""

    def insertion_target(self) -> tuple[str, str, str]:
        """Where the next picked command goes: `(into, arm, after)`.

        An id and a SIDE, never an index -- the addressing the verbs take,
        for the reason `docs/PLAN_SCENES.md` 3.4 gives: an ordered batch of
        edits shifts every index it touches, silently.

        A selected command means "after this one". A selected arm header or
        the dim placeholder means "into that arm, at the end". Nothing
        selected means the end of the page.
        """
        page = self.current_page()
        item = self.tree.currentItem()
        if page is None:
            return ("", PAGE_BODY, event_script.NO_ANCHOR)
        if item is None:
            body = page.get("body") or ()
            return (page["id"], PAGE_BODY,
                    body[-1]["id"] if body else event_script.NO_ANCHOR)
        into = item.data(0, self.INTO_ROLE) or page["id"]
        arm = item.data(0, self.ARM_ROLE) or PAGE_BODY
        if item.data(0, self.KIND_ROLE) == "node":
            return (into, arm, item.data(0, self.NODE_ROLE))
        # An arm header or a placeholder: the address IS the row, and the
        # new command goes after whatever is already in that arm.
        last = event_script.NO_ANCHOR
        for index in range(item.childCount()):
            child = item.child(index)
            if child.data(0, self.KIND_ROLE) == "node":
                last = child.data(0, self.NODE_ROLE)
        if item.data(0, self.KIND_ROLE) == "empty":
            return (into, arm, event_script.NO_ANCHOR)
        return (item.data(0, self.INTO_ROLE), item.data(0, self.ARM_ROLE),
                last)

    # -- describing --------------------------------------------------------

    def __describe_document(self, document) -> Inspection:
        scope = self.scope
        title = Field(
            "title", "title", "str", document.title,
            doc="A human label. The id is what the file, the address and "
                "another script's `call` use, and it never changes.",
            emit=lambda value: Command("script.set", scope,
                                       {"key": "title", "value": str(value)}))
        rows = [title]
        declared = list(document.loadouts)
        for loadout in op_registry.loadouts(self.registry):
            rows.append(self.__loadout_field(scope, declared, loadout))
        note = ("A script that declares only `core` runs unchanged in every "
                "game mode. Every other loadout is a promise about where it "
                "can run.")
        return Inspection(scope, document.id, sections=[
            Section("Script", rows, note=note)])

    def __loadout_field(self, scope, declared, loadout: str) -> Field:
        def emit(value: Any):
            wanted = list(declared)
            if bool(value) and loadout not in wanted:
                wanted.append(loadout)
            elif not bool(value) and loadout in wanted:
                wanted.remove(loadout)
            else:
                return None
            return Command("script.set", scope,
                           {"key": "loadouts", "value": sorted(wanted)})

        return Field("loadout_%s" % loadout, "loadout %s" % loadout, "bool",
                     loadout in declared,
                     doc="Whether this script may use the ops the %r loadout "
                         "declares." % loadout,
                     emit=emit)

    def __describe_page(self, document, page) -> Inspection:
        scope = self.scope
        if page is None:
            return Inspection(scope, "", sections=[
                Section("Page", [], note=NO_PAGES if not document.pages
                        else NO_PAGE_SELECTED)])
        page_id = page["id"]

        def setter(key: str):
            def emit(value: Any):
                return Command("script.page.set", scope,
                               {"page": page_id, "key": key, "value": value})
            return emit

        rows = [
            Field("trigger", "trigger", "choice",
                  page.get("trigger", "use"),
                  choices=tuple(event_script.SCRIPT_TRIGGERS),
                  doc="What starts this page. `use` is the action button; "
                      "`enter` / `exit` / `stay` are region triggers; "
                      "`auto` fires from the scene's own entry.",
                  emit=setter("trigger")),
            Field("payload", "payload", "str", page.get("payload", ""),
                  doc="The opaque string the action carries, matched against "
                      "the object's `pyoneer_param_payload`. Never "
                      "interpreted.",
                  emit=setter("payload")),
            Field("once", "once", "bool", bool(page.get("once", False)),
                  doc="Run this page at most once.",
                  emit=setter("once")),
            Field("cooldown_ms", "cooldown ms", "int",
                  int(page.get("cooldown_ms", 0)),
                  doc="How long before it may fire again. Milliseconds, "
                      "matching every other `_ms` in the project.",
                  emit=setter("cooldown_ms")),
            Field("note", "note", "str", page.get("note", ""),
                  doc="A line for whoever reads this next. It never runs.",
                  emit=setter("note")),
        ]
        blocked = self.condition_note()
        conditions = list(page.get("when") or ())
        # SHOWN HERE, BUILT WITH THE BUTTONS. A condition is a record and
        # not a scalar, so there is nothing for a text row to hold; `+ when`
        # opens the three-row builder that makes one.
        if not conditions:
            rows.append(Field("when", "when", "str", NO_CONDITIONS,
                              blocked_reason=blocked))
        for index, condition in enumerate(conditions):
            rows.append(Field("when_%d" % index, "when", "str",
                              condition_words(condition),
                              blocked_reason=blocked))
        note = ("Conditions are ANDed. An empty list always passes and is "
                "the fallback page.   " + blocked)
        return Inspection(scope, page_id, sections=[
            Section("Page %s" % page_id, rows, note=note)])

    def __describe_node(self, document) -> Inspection:
        scope = self.scope
        node = self.current_node()
        if node is None:
            return Inspection(scope, "", sections=[
                Section("Command", [], note=NO_NODE_SELECTED)])
        table = self.registry
        node_id = node["id"]

        def setter(key: str):
            def emit(value: Any):
                return Command("script.node.set", scope,
                               {"node": node_id, "key": key, "value": value})
            return emit

        spec = table.get(node.get("do")) if "do" in node else None
        rows: list[Field] = []
        try:
            keys = event_script.settable_node_keys(node, table)
        except Exception as exc:                                # noqa: BLE001
            # An unknown op: the row still draws, and so does this pane,
            # with the compiler's message. Refusing to open is how a typo in
            # a hand-edited file becomes unfixable.
            return Inspection(scope, node.get("do", node_id), sections=[
                Section("Command %s" % node_id, [], note=str(exc))])

        for key in keys:
            value = event_script.node_value(node, key, table)
            rows.append(self.__node_field(spec, key, value, setter))

        if spec is None:
            heading = "if" if "if" in node else "while"
            note = ("A branch. Its arms are filled by picking commands with "
                    "one of them selected; its condition is read-only for "
                    "the same reason a page's is.   " + self.condition_note())
        else:
            heading = spec.name
            note = "%s   [%s]%s" % (
                spec.summary, spec.loadout,
                "" if spec.status == "live" else
                "   ⚠ status %s: authorable now, it does not run yet."
                % spec.status)
        return Inspection(scope, heading,
                          sections=[Section("Command %s" % node_id, rows,
                                            note=note)])

    def __node_field(self, spec, key: str, value: Any, setter) -> Field:
        """One editable argument, typed by the op's OWN declaration.

        A `BehaviorParam` carries a type, so the form gets a real editor. A
        dynamic `OpArg` deliberately carries none -- the moment it could
        coerce it would be a second `BehaviorParam` and the two would drift
        -- so it renders read-only with the SHAPE its declaration states,
        and the box below is how it gets changed. Guessing a type from the
        value that happens to be there today is the plausible default law 7
        forbids.
        """
        if key == "note":
            return Field(key, "note", "str", value,
                         doc="A line for whoever reads this next.",
                         emit=setter(key))
        param = spec.param(key) if spec is not None else None
        if param is not None:
            kind = "choice" if param.choices else param.type
            return Field(key, param.label, kind, value,
                         choices=tuple(param.choices), doc=param.doc,
                         emit=setter(key))
        if spec is not None:
            for arg in spec.dynamic:
                if arg.key == key:
                    return Field(key, arg.label, "str", value_words(value),
                                 doc=arg.doc,
                                 blocked_reason="it is %s, and this screen "
                                                "does not type one yet — ask "
                                                "for the change in the box "
                                                "below" % arg.shape)
        # A control node's own keys: the condition list, and the arm list.
        if key == "elif":
            return Field(key, "else-if arms", "str",
                         "%d arm(s)" % len(value or ()),
                         blocked_reason="arms are added and removed with the "
                                        "+ else-if / − else-if buttons; each "
                                        "arm's condition is a `when` list")
        return Field(key, key, "str", when_words(value),
                     blocked_reason=self.condition_note())

    def condition_note(self) -> str:
        """What the builder can do right now, in the READER's own words.

        Measured rather than declared: a one-condition page is put through
        `ScriptDocument.validate` and whatever it says is the answer. With
        no scene in the project that is *"this load was given no variable
        schema"*, which is the true reason and names the fix; the moment a
        scene declares its `vars` the same probe passes and this note says
        so, with nothing in this file edited.

        The probe names a DECLARED variable when there is one, so that a
        project which can author conditions is never told it cannot by a
        probe that failed on a name nobody wrote.
        """
        document = self.document
        if document is None:
            return CONDITIONS_ARE_BUILT
        library = self.library
        names = self.variable_names()
        probe, value = "a_variable", True
        if names:
            # Its own declared DEFAULT, which is the one value guaranteed
            # to be at its type -- `is True` against an int variable would
            # fail on the value rather than on the thing being asked.
            probe = names[0]
            try:
                value = library.variables.declaration(probe).default
            except Exception:                                   # noqa: BLE001
                value = True
        trial = event_script.ScriptDocument(
            id=document.id, loadouts=list(document.loadouts),
            pages=[{"id": PROBE_PAGE, "trigger": "use",
                    "when": [{"var": probe, "is": value}], "body": []}])
        try:
            trial.validate(variables=getattr(library, "variables", None),
                           registry=self.registry)
        except Exception as exc:                                # noqa: BLE001
            return "%s The reader says: %s" % (
                CONDITIONS_ARE_BUILT, one_line(exc))
        return (CONDITIONS_ARE_BUILT
                + " %d variable(s) are declared." % len(names))

    def refusal_for_op(self, document, name: str) -> str:
        """`""` if this op can be added to this document, else the reason."""
        table = self.registry
        spec = table.get(name)
        if spec is None:
            return "%r is not a registered op" % name
        library = self.library
        node = dict(seed_for(spec), id=PROBE_NODE, do=name)
        return refusal_for(document, node,
                           variables=getattr(library, "variables", None),
                           registry=table)

    # -- acting ------------------------------------------------------------

    def create_script(self) -> None:
        """Ask for an id, then `script.create`.

        The one decision this screen puts in a dialog, and it really is the
        author's: a script id is the file stem, the scope, and what another
        script's `call` names, so nothing may pick it for them. There is no
        rename verb -- the id IS the address -- which is exactly why it is
        asked once, up front.
        """
        library = self.library
        if library is None:
            return
        answer = self.ask(
            self, "New event script",
            [Field("id", "id", "str", "",
                   doc="letters, digits, '_' and '-'. It becomes the file "
                       "name and the address, and it never changes."),
             Field("title", "title", "str", "",
                   doc="a human label; optional")],
            ok_label="Create",
            note="A script is shared: several objects can name the same one, "
                 "and each keeps its own `local.` state.")
        if not answer:
            return
        wanted = str(answer.get("id", "")).strip()
        if not wanted:
            self.notify("a script needs an id — it is the file name and the "
                        "address")
            return
        if library.has(wanted):
            self.notify("there is already a script called %r" % wanted)
            return
        scope = Scope.of(("script", wanted))
        self.__send(Command("script.create", scope,
                            {"title": str(answer.get("title", "")).strip()}))
        self.set_script(wanted)

    def delete_script(self) -> None:
        document = self.document
        if document is None:
            return
        self.__send(Command("script.delete", self.scope, {"confirm": True}))
        library = self.library
        names = library.names() if library is not None else []
        self.set_script(names[0] if names else "")

    def add_page(self) -> None:
        document = self.document
        if document is None:
            return
        page_id = mint(document.ids(), "pg_")
        after = self.__page_id
        # Set BEFORE the send, because the send rebuilds: the new page is
        # what the author is now looking at, and a refresh that ran first
        # would land the selection back on the old one.
        self.__page_id = page_id
        self.__node_id = ""
        self.__send(Command("script.page.add", self.scope,
                            {"id": page_id, "after": after,
                             "trigger": "use", "when": []}))

    def remove_page(self) -> None:
        if self.current_page() is None:
            return
        page_id = self.__page_id
        self.__page_id = ""
        self.__node_id = ""
        self.__send(Command("script.page.remove", self.scope,
                            {"page": page_id}))

    def move_page(self, delta: int) -> None:
        document = self.document
        page = self.current_page()
        if document is None or page is None:
            return
        ids = document.page_ids()
        index = ids.index(page["id"]) + delta
        if index < 0 or index >= len(ids):
            self.notify("that page is already %s"
                        % ("first" if delta < 0 else "last"))
            return
        # An anchor id and a side, never an index: `after` is the sibling it
        # follows, and `""` is the FRONT.
        neighbours = [i for i in ids if i != page["id"]]
        after = neighbours[index - 1] if index else event_script.NO_ANCHOR
        self.__send(Command("script.page.move", self.scope,
                            {"page": page["id"], "after": after}))

    # -- picking, which is not inserting -----------------------------------

    def variable_names(self) -> tuple[str, ...]:
        """Every variable a scene has declared, or none when none has.

        `()` is not "there are no variables": with no schema in hand the
        reader refuses every condition, and `condition_fields` renders the
        variable row as free text so the author can still see what they
        were trying to say when the refusal arrives.
        """
        variables = getattr(self.library, "variables", None)
        names = getattr(variables, "names", None)
        return tuple(names()) if callable(names) else ()

    def argument_fields(self, do: str, node: dict | None = None) -> list[Field]:
        """The form for one op, DERIVED from what that op declares.

        One row per `BehaviorParam`, typed by the declaration; one row per
        `OpArg`, which declares no type on purpose and so takes what was
        typed (see `argument_value`); and `note`, which every node may
        carry. Nothing in this method knows the name of a single op, which
        is what makes registering one enough to make its form appear.

        `node` populates it. That is the whole of `Edit…`: the same rows,
        the same order, the values that are in the document.
        """
        spec = self.registry.get(do)
        rows: list[Field] = []
        if spec is not None:
            seed = seed_for(spec)
            for param in spec.params:
                if node is not None and param.key in node:
                    value = node[param.key]
                else:
                    value = seed.get(param.key, param.default)
                kind = "choice" if param.choices else param.type
                rows.append(Field(param.key, param.label, kind, value,
                                  choices=tuple(param.choices),
                                  doc=param.doc))
            for arg in spec.dynamic:
                if node is not None and arg.key in node:
                    value = node[arg.key]
                else:
                    value = seed.get(arg.key, arg.default)
                rows.append(Field(
                    arg.key, arg.label, "str",
                    "" if value is None else json.dumps(value),
                    doc="%s — %s. Written as it reads: `Pay half` is text, "
                        "`100` is a number, `[\"a\", \"b\"]` is a list."
                        % (arg.doc, arg.shape)))
        rows.append(Field("note", "note", "str",
                          (node or {}).get("note", ""),
                          doc="A line for whoever reads this next. It never "
                              "runs, and it shows on the row's tooltip."))
        return rows

    def condition_fields(self, current: dict | None = None) -> list[Field]:
        """The form for ONE condition: a variable, a comparator, a value.

        Three rows, and the middle one is a closed list of the six the
        format has. `docs/PLAN_SCENES.md` 3.4 made a condition a record
        rather than a string precisely so this form needs no parser.
        """
        names = self.variable_names()
        # Every comparator the record carries, in the format's own order --
        # not the first one found. A record with two is illegal and the
        # reader says so naming both; picking one here would draw a legal
        # row for a document that does not load.
        present = [key for key in COMPARATORS if key in (current or {})]
        operator = present[0] if present else COMPARATORS[0]
        value = (current or {}).get(operator, "")
        variable = str((current or {}).get("var", ""))
        return [
            Field("var", "variable", "choice" if names else "str",
                  variable, choices=names,
                  doc="Which variable to compare. A scene's `vars` block "
                      "declares it, with a type and a default."),
            Field("operator", "comparator", "choice", operator,
                  choices=tuple(COMPARATORS),
                  doc="`is` / `not` compare equality; `at_least` / "
                      "`at_most` are arithmetic and need a number; `in` "
                      "asks whether the value is one of a list; `contains` "
                      "asks whether it holds one."),
            Field("value", "value", "str",
                  "" if value == "" else json.dumps(value),
                  doc="What to compare against. `100` is a number, `true` "
                      "is a boolean, `[\"a\", \"b\"]` is a list."),
        ]

    def pick_op(self, do: str) -> None:
        """A picked command opens ITS OWN FORM. Nothing is inserted yet.

        The RPG Maker gesture, and the reason for it: a node dropped with
        empty arguments is a broken script the author now has to go and
        repair, and the repair is in a different pane from the picker.
        """
        document = self.document
        if document is None:
            return
        if self.current_page() is None:
            self.notify("add a page first — a command lives on a page")
            return
        into, arm, after = self.insertion_target()
        self.form_intent = ("add", do, into, arm, after)
        if do in event_script.CONTROL_KINDS:
            self.form.open(
                "%s — its first condition" % do,
                self.condition_fields(),
                note="A branch. Leave the variable empty to start it with no "
                     "condition at all, which always passes; its arms are "
                     "filled by picking commands with one of them selected."
                     "   " + self.condition_note(),
                ok_label="Insert")
        else:
            spec = self.registry.get(do)
            self.form.open(
                "%s — %s" % (do, spec.summary if spec is not None
                             else "an op the registry does not know"),
                self.argument_fields(do),
                note=self.__form_note(spec), ok_label="Insert")
        self.picker.setVisible(False)

    def __form_note(self, spec) -> str:
        if spec is None:
            return ""
        note = "%s   [%s]" % (spec.summary, spec.loadout)
        if spec.status != "live":
            note += ("   ⚠ status %s: it can be authored now, and it does "
                     "not run yet." % spec.status)
        return note

    def close_form(self) -> None:
        """Put the picker back. Called by Cancel and by every accept."""
        self.form_intent = None
        self.form.hide()
        self.picker.setVisible(True)

    def open_picker_here(self) -> str:
        """Show the picker for the row the author just activated.

        Enter or a double-click, including on the dim placeholder at the
        end of an empty body -- which is the whole reason that row is drawn
        with an address on it.
        """
        self.close_form()
        self.picker.search.setFocus()
        anchor = self.anchor_sentence()
        self.notify("pick a command — it goes %s" % anchor)
        return anchor

    def __on_form_accepted(self, values: dict) -> None:
        intent = self.form_intent
        if intent is None:
            return
        if intent[0] == "add":
            self.insert_node(intent[1], intent[2], intent[3], intent[4],
                             values)
        elif intent[0] == "edit":
            self.apply_node_edit(intent[1], values)
        else:
            self.apply_condition(intent[1], intent[2], values)

    def __arguments(self, do: str, values: dict) -> dict:
        """The form's answers as the `args` a verb takes.

        A dynamic `OpArg` is read with `argument_value`; a declared param is
        already the type its declaration asked the widget for. `note` is
        dropped when it is empty, because the canonical rendering drops it
        there and "absent" and "empty" are one state.
        """
        spec = self.registry.get(do)
        dynamic = {arg.key for arg in spec.dynamic} if spec is not None \
            else set()
        args: dict = {}
        for key, value in values.items():
            if key == "note":
                if str(value).strip():
                    args["note"] = str(value)
                continue
            args[key] = argument_value(value) if key in dynamic else value
        return args

    def insert_node(self, do: str, into: str, arm: str, after: str,
                    values: dict) -> None:
        """Accepting the form is what inserts the node. One command."""
        document = self.document
        if document is None:
            return
        if do in event_script.CONTROL_KINDS:
            args = {"when": self.__condition_list(values)}
            note = str(values.get("note", "")).strip()
            if note:
                args["note"] = note
            probe = {do: args["when"], "then": []}
        else:
            args = self.__arguments(do, values)
            probe = dict(args, do=do)
        refusal = refusal_for(document, probe,
                              variables=getattr(self.library, "variables",
                                                None),
                              registry=self.registry)
        if refusal:
            # THE READER REFUSES, IN THE FORM, WITH THE VALUES STILL IN IT.
            # Sending it and letting the window report the rejection would
            # cost the author everything they had typed.
            self.form.refuse(one_line(refusal, limit=600))
            return
        node_id = mint(document.ids(), "n")
        self.__node_id = node_id
        self.close_form()
        self.__send(Command("script.node.add", self.scope,
                            {"id": node_id, "do": do, "into": into,
                             "arm": arm, "after": after, "args": args}))

    def edit_node(self) -> None:
        """Reopen THE SAME form on the selected command, populated."""
        node = self.current_node()
        if node is None:
            self.notify("pick a command first")
            return
        if "do" not in node:
            kind = "if" if "if" in node else "while"
            self.notify("a `%s` is edited with + when / − when — its arms "
                        "are filled by picking commands inside them" % kind)
            return
        self.form_intent = ("edit", node["id"])
        spec = self.registry.get(node["do"])
        self.form.open("%s — %s" % (node["do"], node["id"]),
                       self.argument_fields(node["do"], node),
                       note=self.__form_note(spec), ok_label="Apply")
        self.picker.setVisible(False)

    def apply_node_edit(self, node_id: str, values: dict) -> None:
        """One `script.node.set` per key that actually changed.

        A list, so the whole edit is ONE transaction and one Ctrl+Z, and so
        a form that changed nothing sends nothing at all.
        """
        document = self.document
        if document is None:
            return
        try:
            node = document.node(node_id)
        except Exception as exc:                                # noqa: BLE001
            self.form.refuse(str(exc))
            return
        table = self.registry
        args = self.__arguments(node["do"], values)
        probe = dict({k: v for k, v in node.items() if k != "id"}, **args)
        if "note" not in args:
            probe.pop("note", None)
        refusal = refusal_for(document, probe,
                              variables=getattr(self.library, "variables",
                                                None),
                              registry=table)
        if refusal:
            self.form.refuse(one_line(refusal, limit=600))
            return
        commands = []
        for key in list(args) + (["note"] if "note" not in args else []):
            wanted = args.get(key, "")
            if event_script.node_value(node, key, table) == wanted:
                continue
            commands.append(Command("script.node.set", self.scope,
                                    {"node": node_id, "key": key,
                                     "value": wanted}))
        self.close_form()
        if not commands:
            self.notify("nothing changed")
            return
        self.__send(commands)

    # -- conditions --------------------------------------------------------

    def __condition_list(self, values: dict) -> list:
        """The one condition a filled form describes, as a list of records.

        An empty variable is not an empty condition: it is NO condition,
        which is a `when` list of zero and always passes. Writing
        `{"var": ""}` instead would be a record the reader refuses for a
        reason the author never asked for.
        """
        variable = str(values.get("var", "")).strip()
        if not variable:
            return []
        return [{"var": variable,
                 str(values.get("operator") or COMPARATORS[0]):
                     argument_value(values.get("value", ""))}]

    def __condition_owner(self, target: str):
        """`(kind, id, the current when list)` for "page" or "node"."""
        if target == "page":
            page = self.current_page()
            if page is None:
                return None
            return ("page", page["id"], list(page.get("when") or ()))
        node = self.current_node()
        if node is None or "do" in node:
            return None
        kind = "if" if "if" in node else "while"
        return (kind, node["id"], list(node.get(kind) or ()))

    def add_condition(self, target: str) -> None:
        """Open the condition builder for a page or for a control node."""
        owner = self.__condition_owner(target)
        if owner is None:
            self.notify("pick a page first" if target == "page" else
                        "pick an `if` or a `while` first — only those carry "
                        "conditions of their own")
            return
        kind, owner_id, _current = owner
        self.form_intent = ("when", target, owner_id)
        self.form.open("a condition on %s %s" % (kind, owner_id),
                       self.condition_fields(),
                       note="Every condition on the list has to hold — they "
                            "are ANDed, and an empty list always passes.   "
                            + self.condition_note(),
                       ok_label="Add")
        self.picker.setVisible(False)

    def apply_condition(self, target: str, owner_id: str,
                        values: dict) -> None:
        document = self.document
        owner = self.__condition_owner(target)
        if document is None or owner is None:
            return
        kind, current_id, current = owner
        if current_id != owner_id:
            self.form.refuse("the selection moved while this form was open")
            return
        made = self.__condition_list(values)
        if not made:
            self.form.refuse("a condition needs a variable to compare")
            return
        wanted = current + made
        refusal = refusal_for_when(
            document, wanted,
            variables=getattr(self.library, "variables", None),
            registry=self.registry)
        if refusal:
            self.form.refuse(one_line(refusal, limit=600))
            return
        self.close_form()
        if target == "page":
            self.__send(Command("script.page.set", self.scope,
                                {"page": owner_id, "key": "when",
                                 "value": wanted}))
        else:
            self.__send(Command("script.node.set", self.scope,
                                {"node": owner_id, "key": kind,
                                 "value": wanted}))

    def remove_condition(self, target: str) -> None:
        """Take the LAST condition off. Exactly invertible, like an arm."""
        owner = self.__condition_owner(target)
        if owner is None:
            self.notify("pick a page first" if target == "page" else
                        "pick an `if` or a `while` first")
            return
        kind, owner_id, current = owner
        if not current:
            self.notify("there is no condition to take off — an empty list "
                        "always passes")
            return
        if target == "page":
            self.__send(Command("script.page.set", self.scope,
                                {"page": owner_id, "key": "when",
                                 "value": current[:-1]}))
        else:
            self.__send(Command("script.node.set", self.scope,
                                {"node": owner_id, "key": kind,
                                 "value": current[:-1]}))

    # -- the relay, at a placement -----------------------------------------

    def anchor_sentence(self) -> str:
        """Where the next command would land, in the VERBS' own words.

        `Scope` cannot name a node -- a scope kind is a permanent file
        format string and not one module's to mint -- so the anchor travels
        in the request TEXT. It is spelled `into` / `arm` / `after` because
        that is what `script.node.add` takes: a responder transcribes it
        rather than interpreting it.
        """
        page = self.current_page()
        if page is None:
            return "nowhere yet — this script has no page"
        into, arm, after = self.insertion_target()
        return ("on page %r, into %r, arm %r, after %r (arm \"\" is the "
                "page's own body; after \"\" is the FRONT of that body)"
                % (page["id"], into, arm, after))

    def ask_here(self) -> str | None:
        """Send one request carrying THIS insertion point. Returns its path.

        The accelerator, never the dependency: everything the picker and
        the form do works with this switched off entirely.
        """
        text = self.here_field.text().strip()
        if not text:
            self.notify("say what should happen here first — the insertion "
                        "point comes from the row you are standing on")
            return None
        document = self.document
        if document is None:
            self.notify("open a script first")
            return None
        body = "%s\n\nInsert it %s." % (text, self.anchor_sentence())
        try:
            path = self.session.ask(self.scope, body)
        except Exception as exc:                                # noqa: BLE001
            # Broad on purpose: this is a Qt slot, and an exception thrown
            # out of one is swallowed by the event loop -- the author would
            # see the press do nothing at all.
            self.notify(str(exc).splitlines()[0], seconds=14.0)
            return None
        self.here_field.clear()
        self.notify("wrote %s — it carries the insertion point, not just "
                    "the script" % path, seconds=15.0)
        return path

    def remove_node(self) -> None:
        node = self.current_node()
        if node is None:
            self.notify("pick a command first")
            return
        self.__node_id = ""
        self.__send(Command("script.node.remove", self.scope,
                            {"node": node["id"]}))

    def move_node(self, delta: int) -> None:
        document = self.document
        node = self.current_node()
        if document is None or node is None:
            self.notify("pick a command first")
            return
        site = document.locate(node["id"])
        container = document.container(site.into, site.arm)
        index = site.index + delta
        if index < 0 or index >= len(container):
            self.notify("that command is already %s among its siblings"
                        % ("first" if delta < 0 else "last"))
            return
        siblings = [n["id"] for n in container if n["id"] != node["id"]]
        after = siblings[index - 1] if index else event_script.NO_ANCHOR
        self.__send(Command("script.node.move", self.scope,
                            {"node": node["id"], "into": site.into,
                             "arm": site.arm, "after": after}))

    def add_arm(self) -> None:
        """Give the selected `if` one more else-if arm.

        `script.node.set` on the whole `elif` list is how an arm is created,
        and it is exactly invertible because the inverse carries the list as
        it was. There is deliberately no arm verb: one node with arms means
        an added arm is one contiguous block in a diff.
        """
        node = self.current_node()
        if node is None or "if" not in node:
            self.notify("pick an `if` command first — only an `if` has "
                        "else-if arms")
            return
        arms = list(node.get("elif") or ()) + [{"when": [], "then": []}]
        self.__send(Command("script.node.set", self.scope,
                            {"node": node["id"], "key": "elif",
                             "value": arms}))

    def remove_arm(self) -> None:
        node = self.current_node()
        if node is None or "if" not in node:
            self.notify("pick an `if` command first")
            return
        arms = list(node.get("elif") or ())
        if not arms:
            self.notify("that `if` has no else-if arm")
            return
        self.__send(Command("script.node.set", self.scope,
                            {"node": node["id"], "key": "elif",
                             "value": arms[:-1]}))

    # -- state -------------------------------------------------------------

    def __sync_buttons(self, document, page) -> None:
        """Enable only what can act, and say why in the tooltip when not."""
        node = self.current_node()
        control = node is not None and "if" in node
        branch = node is not None and "do" not in node
        arms = len(node.get("elif") or ()) if control else 0
        for key, on, why in (
                ("− page", page is not None, "pick a page first"),
                ("▲", page is not None, "pick a page first"),
                ("▼", page is not None, "pick a page first"),
                ("+ when", page is not None, "pick a page first"),
                ("− when", bool(page is not None
                                and (page.get("when") or ())),
                 "this page has no condition to take off")):
            button = self.page_buttons[key]
            button.setEnabled(on)
            if not on:
                button.setToolTip(why)
        # `Edit…` is the op form; a branch is edited with the when buttons
        # and by filling its arms, so it says so rather than opening an
        # empty form.
        self.node_buttons["Edit…"].setEnabled(node is not None and not branch)
        self.node_buttons["+ when"].setEnabled(branch)
        self.node_buttons["− when"].setEnabled(
            branch and bool(node.get("if" if control else "while") or ()))
        if not branch:
            for key in ("+ when", "− when"):
                self.node_buttons[key].setToolTip(
                    "pick an `if` or a `while` — only those carry conditions "
                    "of their own. A page's conditions are above.")
        self.node_buttons["− command"].setEnabled(node is not None)
        self.node_buttons["▲"].setEnabled(node is not None)
        self.node_buttons["▼"].setEnabled(node is not None)
        self.node_buttons["+ else-if"].setEnabled(control)
        self.node_buttons["− else-if"].setEnabled(control and bool(arms))
        if not control:
            for key in ("+ else-if", "− else-if"):
                self.node_buttons[key].setToolTip(
                    "pick an `if` command — only an `if` has else-if arms")

    def report(self, message: str) -> None:
        self.problem.setText(message)
        self.problem.setVisible(bool(message))

    def notify(self, message: str, *, seconds: float = 8.0) -> None:
        """Say something without stopping the hand. Always remembered."""
        self.last_notice = message
        self.statusBar().showMessage(message, int(seconds * 1000))

    def commit_in_flight(self) -> bool:
        """Push the field the author is still inside into the document.

        The same hazard `ObjectEditor.commit_in_flight` names and for the
        same reason: `InspectionView` commits a text field on
        `editingFinished`, and a form that is DESTROYED rather than
        defocused -- re-aimed at another script, or taken down with the
        editor -- emits neither.
        """
        focus = self.focusWidget()
        if focus is None or not focus.isVisible():
            return False
        if isinstance(focus, QAbstractSpinBox):
            focus.interpretText()
        elif isinstance(focus, QLineEdit):
            focus.editingFinished.emit()
        else:
            return False
        return True

    def closeEvent(self, event) -> None:                        # noqa: N802
        self.commit_in_flight()
        super().closeEvent(event)

    # -- selection ---------------------------------------------------------

    def __on_pick_script(self, current, _previous) -> None:
        if self.__rebuilding or current is None:
            return
        self.set_script(current.data(Qt.UserRole) or "")

    def __on_pick_page(self, current, _previous) -> None:
        if self.__rebuilding:
            return
        self.__page_id = (current.data(Qt.UserRole) or "") if current else ""
        self.__node_id = ""
        self.refresh()

    def __on_pick_node(self, current, _previous) -> None:
        if self.__rebuilding:
            return
        self.__node_id = (current.data(0, self.NODE_ROLE) or "") \
            if current else ""
        document = self.document
        if document is None:
            return
        self.node_view.show_inspection(self.__describe_node(document))
        self.__sync_buttons(document, self.current_page())

    # -- emitting ----------------------------------------------------------

    def __send(self, command) -> None:
        """One command out, then a rebuild. Refusals are the window's."""
        self.command_requested.emit(command)
        self.refresh()

    def __on_command(self, command: Any) -> None:
        """One edit from a form, on its way to the one mutation point.

        The same two duplicate shapes `ObjectEditor.__on_command` measured:
        a command that arrives DURING a rebuild came from a widget being
        torn down, and an identical command arriving immediately after one
        is a second slot on the same emission rather than a second edit.
        """
        if self.__rebuilding:
            return
        signature = (command.verb, str(command.scope), repr(command.args))
        if signature == self.__last:
            return
        self.command_requested.emit(command)
        self.refresh()
        self.__last = signature

    def __forward(self, name: str) -> None:
        call = getattr(self.parent(), name, None)
        if callable(call):
            call()


__all__ = ["ASK_HERE", "CONDITIONS_ARE_BUILT", "NOTHING_YET", "NO_CONDITIONS",
           "NO_PAGES", "NO_SCRIPTS", "SCRIPT", "ArgumentForm", "OpPicker",
           "ScriptEditor", "argument_value", "condition_words", "mint",
           "node_words", "one_line", "refusal_for", "refusal_for_when",
           "seed_for", "value_words", "when_words"]
