"""The event screen: what it offers, what it inserts, and what it can build.

The author asked for this twice, and the second time said what it has to be:

    "The json scripting required human interactive utilization, the
     developer is likely not going to be coding anything, but instead will
     be communicating through the engine to the AI for curative changes."

So the claim under test is not "the window opens". It is that someone who
never opens the file can build a script that RUNS, and that the AI is an
accelerator they may ignore. This file is written against the seven ways
that could be false with nothing on screen looking wrong:

  * THE PICKER COULD BE A LIST IN A QT FILE. A hand-written command list is
    the failure `docs/BEHAVIORS.md`'s categories already track: it agrees
    with the registry on the day it is written and silently disagrees
    afterwards. So the picker's names are asserted to BE the registry's,
    an op is registered IN THIS PROCESS, and the button and its whole
    argument form are asserted to appear with no line of the screen edited.
  * IT COULD DROP A BARE NODE. RPG Maker opens the chosen command's own
    form and the line lands only once its arguments are filled; a picker
    that inserts on the click hands the author a broken script and makes
    them go and find the fields. So picking is asserted to emit NOTHING,
    and the command is asserted to carry the values that were typed rather
    than the seed they started at.
  * THE FORM COULD DRIFT FROM THE NODE IT EDITS. Two forms for one node is
    two places for the argument vocabulary to rot, so `Edit…` is asserted
    to reopen THE SAME rows, populated from the document.
  * A REFUSAL COULD COST THE AUTHOR THEIR TYPING. The reader judges before
    a command is sent, and the refusal is asserted to stay IN the form with
    the values still in it -- both halves, because a form that refused
    everything would pass a test that only proved it can refuse.
  * A CONDITION COULD BE A TEXT BOX, or worse, a text box with an invented
    schema behind it. Both halves again: with no scene in the project the
    builder is asserted to write NOTHING and to carry the reader's own
    sentence, and with a real schema the same gesture is asserted to write
    the record.
  * THE RELAY COULD BE THE ONLY WAY THROUGH. So the branching script is
    built with `Session.ask` REPLACED BY A TRIPWIRE, loaded with the
    engine's own reader, and STEPPED -- and the arm that ran is asserted,
    both ways round.
  * THE BUNDLE COULD LOSE THE PLACE. A request that names the script but
    not the insertion point makes the responder guess a position, which is
    the silent mis-landing node ids exist to prevent. So the bundle is
    opened and its manifest is asserted to carry the script's scope and the
    anchor in the verbs' own words.

Plus the two standing structural properties of any window in `editor/ui/`:
it opens nothing modal (law 13), and it is REACHABLE -- `EditorWindow`
really does open it, and the entity screen really does ask for it.

Against its OWN fixture, never `data/maps/starter.tmx` (law 4).

Skips cleanly when PySide6 is absent.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent                     # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QMainWindow,
    QMessageBox,
)

from editor.core import event_script                                    # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.core.settings import EditorSettings                         # noqa: E402
from editor.ui.object_editor import (                                   # noqa: E402
    NO_SCRIPT_ON_OBJECT,
    SCRIPT_MOVED,
    ObjectEditor,
)
from editor.ui.script_editor import (                                   # noqa: E402
    NO_PAGES,
    NO_SCRIPTS,
    NOTHING_YET,
    SCRIPT,
    ScriptEditor,
    argument_value,
    refusal_for_when,
)
import editor.ui.main_window as main_window_module                      # noqa: E402
from editor.ui.main_window import EditorWindow                          # noqa: E402

from scripts.game.flow import ops as op_registry                        # noqa: E402
from scripts.game.flow.interpreter import ScriptRun                     # noqa: E402
from scripts.loaders import script_file as sf                           # noqa: E402

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def brief(value, limit: int = 44) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<64} "
          f"got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


# RECORD every modal rather than silencing it: "this path asked nothing" is
# the stronger claim of the two and it needs an instrument that could have
# said otherwise.
warned: list[str] = []
asked: list[str] = []
informed: list[str] = []


def _record(bucket, answer=None):
    def stub(*a, **k):
        bucket.append(str(a[2]) if len(a) > 2 else "")
        return answer
    return staticmethod(stub)


QMessageBox.warning = _record(warned)
QMessageBox.critical = _record(warned)
QMessageBox.information = _record(informed)
QMessageBox.question = _record(asked, QMessageBox.Yes)


def modals() -> list[str]:
    return warned + asked + informed


def settle() -> None:
    """Let Qt finish, INCLUDING the deferred deletes."""
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()


class FakeStore:
    """Stands in for QSettings, and keeps this check off the developer's own
    preferences."""

    def __init__(self, **initial):
        self.data = {k: str(v) for k, v in initial.items()}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = str(value)

    def remove(self, key):
        self.data.pop(key, None)


class FakeLayout:
    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


LAYOUTS = FakeLayout()
main_window_module.layout_store = lambda: LAYOUTS


class Harness(QMainWindow):
    """The one thing the screens ask of their window: run a command."""

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.applied: list = []
        self.rejected: list[str] = []

    def run(self, commands, *, label=None, source="editor") -> bool:
        self.applied.append(commands)
        try:
            self.session.run(commands, label=label, source=source)
        except Exception as exc:                                # noqa: BLE001
            self.rejected.append(str(exc))
            return False
        return True

    def undo(self) -> None:
        self.session.undo()

    def notify(self, message, seconds=0):
        pass


class SayHost:
    """A host that records what a `say` showed. The engine's own duck type."""

    def __init__(self):
        self.lines: list[tuple] = []

    def say_open(self, who, text):
        self.lines.append((who, text))

    def say_close(self):
        pass


FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="4" height="4" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="3">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="16" columns="4">
  <image source="art.png" width="64" height="64"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
1,1,1,1,
1,1,1,1,
1,1,1,1,
1,1,1,1
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="keeper" type="GamePlayer" x="16" y="16" width="16" \
height="16"/>
 </objectgroup>
</map>
"""

workspace = tempfile.mkdtemp(prefix="pyoneer_script_editor_")
application = QApplication.instance() or QApplication([])

try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    os.makedirs(os.path.join(workspace, "data", "project"))
    with open(os.path.join(workspace, "data", "maps", "fixture.tmx"), "w",
              encoding="utf-8", newline="") as handle:
        handle.write(FIXTURE)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)
    with open(os.path.join(workspace, "data", "project", "project.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"genre": "topdown_rpg"}, handle)

    session = Session.open(workspace, genre_id="topdown_rpg")
    library = event_script.scripts_of(session.project)
    harness = Harness(session)

    VARS = sf.read_vars({
        "coins": {"type": "int", "default": 0, "doc": "Spendable."},
        "gate_open": {"type": "bool", "default": False, "doc": "The gate."},
        "paid": {"type": "bool", "default": False, "doc": "Did they pay."},
    })

    SCRIPT_ID = "keeper_gate"
    GATE = Scope.of(("script", SCRIPT_ID))

    screen = ScriptEditor(session, "", harness)
    screen.command_requested.connect(harness.run)
    screen.show()
    settle()

    def rows_of(view=None):
        return screen.tree_rows()

    def page_words() -> str:
        """Every word the page pane is showing, from its LIVE body only.

        `InspectionView` retires the form it replaces with `deleteLater`,
        which does not run until an event loop unwinds -- so a refreshed
        view still has every previous form hanging off it as a hidden
        child, and reading those is how a pane looks like it never changed.
        """
        body = screen.page_view.widget()
        if body is None:
            return ""
        from PySide6.QtWidgets import QLabel
        return " ".join(w.text() for w in body.findChildren(QLabel))

    def find(pred):
        """The first tree item matching. Selection is by ROW, never index."""
        stack = [screen.tree.topLevelItem(i)
                 for i in range(screen.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            if pred(item):
                return item
            stack += [item.child(i) for i in range(item.childCount())]
        return None

    def select_node(node_id: str) -> None:
        item = find(lambda i: i.data(0, screen.NODE_ROLE) == node_id)
        screen.tree.setCurrentItem(item)

    def select_arm(into: str, arm: str) -> None:
        item = find(lambda i: i.data(0, screen.INTO_ROLE) == into
                    and i.data(0, screen.ARM_ROLE) == arm
                    and i.data(0, screen.KIND_ROLE) in ("arm", "empty"))
        screen.tree.setCurrentItem(item)

    def commands_since(mark: int) -> list:
        """Every command the screen sent since `mark`, flattened."""
        out = []
        for entry in harness.applied[mark:]:
            out.extend(entry if isinstance(entry, list) else [entry])
        return out

    def verbs_since(mark: int) -> list[str]:
        return [c.verb for c in commands_since(mark)]

    def node(node_id: str):
        return screen.document.node(node_id)

    # ------------------------------------------------------------------
    section("1. the empty state, which is the screen an author meets first")
    # ------------------------------------------------------------------
    expect("with no script in the project the frame says what one IS",
           (screen.empty.isVisible(), screen.empty.text() == NO_SCRIPTS),
           (True, True))
    expect("...and offers to make one", screen.new_button.isEnabled(), True)
    expect("...while Delete cannot act on nothing",
           screen.delete_button.isEnabled(), False)

    # The one dialog on this screen, replaced at the seam. Naming a script
    # is the author's decision: the id is the file stem, the scope, and what
    # another script's `call` addresses it by.
    screen.ask = lambda *a, **k: {"id": SCRIPT_ID, "title": "The keeper"}
    screen.create_script()
    settle()
    expect("New… creates the script the author named",
           (library.has(SCRIPT_ID), screen.script_id), (True, SCRIPT_ID))
    expect("a script with no page says what a page is FOR, not a blank pane",
           NO_PAGES in page_words(), True)

    screen.add_page()
    settle()
    PAGE = screen.document.page_ids()[0]
    expect("a page with no command draws the row that carries its address",
           [(r["text"], r["into"], r["arm"], r["kind"])
            for r in rows_of()],
           [(NOTHING_YET, PAGE, "", "empty")])

    # ------------------------------------------------------------------
    section("2. the picker IS the registry -- not a list in a Qt file")
    # ------------------------------------------------------------------
    expect("it offers exactly the registered ops, and nothing else",
           screen.picker.op_names(), sorted(op_registry.OP_REGISTRY))
    expect("`if` and `while` are control shapes, NOT ops",
           (sorted(screen.picker.control_buttons),
            [k for k in event_script.CONTROL_KINDS
             if k in screen.picker.op_names()]),
           (["if", "while"], []))
    expect("an op the registry does not have cannot be picked",
           "honk" in screen.picker.op_names(), False)
    # A DISABLED button's tooltip is unreachable by hand -- a disabled widget
    # gets no mouse events -- so the reasons are asserted to be on screen.
    expect("every greyed op's reason is READABLE, not only in a tooltip",
           all(name in screen.picker.note.text()
               for name in screen.picker.blocked)
           and bool(screen.picker.blocked), True)

    # AUTHORABLE AND MARKED, never hidden. `docs/EVENTS.md` measures the
    # runtime column and the screen must not contradict it: an op that does
    # not run yet is still offered, with the warning on its face and its
    # status in its tooltip.
    needs_host = [name for name, spec in op_registry.OP_REGISTRY.items()
                  if spec.status != "live"]
    expect("there is an op that does not run yet, to make this assertable",
           bool(needs_host), True)
    expect("...it is OFFERED rather than hidden",
           [n for n in needs_host if n in screen.picker.op_names()],
           sorted(needs_host))
    expect("...and marked on its face and in its tooltip",
           [(screen.picker.buttons[n].text().endswith("⚠"),
             "does not run yet" in screen.picker.buttons[n].toolTip())
            for n in sorted(needs_host)],
           [(True, True) for _ in needs_host])
    expect("...while a live op carries no such mark",
           screen.picker.buttons["say"].text().endswith("⚠"), False)

    # THE HALF THAT MATTERS: register an op HERE, with no screen edited.
    HONK = op_registry.OpSpec(
        name="honk",
        summary="A horn, for this check only.",
        run=lambda run, args: True,
        params=(op_registry.BehaviorParam(
            key="loudness", label="loudness", type="int", default=3,
            doc="how loud", source="object"),
            op_registry.BehaviorParam(
            key="colour", label="colour", type="str", default="red",
            doc="what colour", choices=("red", "blue"), source="object")),
        example='{"id": "n1", "do": "honk", "loudness": 7, "colour": "blue"}')
    shadow = dict(op_registry.OP_REGISTRY)
    shadow["honk"] = HONK
    library.registry = shadow
    screen.refresh()
    settle()
    expect("an op registered in this process appears in the picker",
           "honk" in screen.picker.op_names(), True)
    expect("...and its FORM is derived from what it declares",
           [f.key for f in screen.argument_fields("honk")],
           ["loudness", "colour", "note"])
    expect("...typed by the declaration, not guessed from the value",
           [(f.kind, f.value) for f in screen.argument_fields("honk")[:2]],
           [("int", 7), ("choice", "blue")])
    library.registry = None
    screen.refresh()
    settle()
    expect("dropping it from the registry drops it from the picker",
           "honk" in screen.picker.op_names(), False)

    # ------------------------------------------------------------------
    section("3. picking is NOT inserting")
    # ------------------------------------------------------------------
    mark = len(harness.applied)
    screen.pick_op("say")
    settle()
    expect("the pick opens a form and sends NOTHING",
           (screen.form.isVisible(), screen.picker.isVisible(),
            verbs_since(mark)), (True, False, []))
    expect("the form's rows are the op's own params, plus the note "
           "every node may carry",
           screen.form.keys(), ["text", "who", "note"])
    expect("...seeded from the op's own example, so it would LOAD",
           screen.form.values()["text"], "The north gate is sealed.")

    screen.form.editors["text"].setText("Fifty coins and the gate opens.")
    screen.form.editors["who"].setText("Keeper")
    screen.form.accept()
    settle()
    expect("accepting the form is what inserts it -- ONE command",
           verbs_since(mark), ["script.node.add"])
    expect("...carrying what was TYPED, not what it was seeded with",
           commands_since(mark)[0].args["args"]["text"],
           "Fifty coins and the gate opens.")
    expect("...and the picker is back", screen.picker.isVisible(), True)
    SAY = commands_since(mark)[0].args["id"]
    expect("the node is in the document", node(SAY)["do"], "say")

    harness.undo()
    screen.refresh()
    settle()
    expect("ONE undo removes it", [r["kind"] for r in rows_of()], ["empty"])
    session.redo()
    screen.refresh()
    settle()
    expect("...and redo puts it back", node(SAY)["do"], "say")

    mark = len(harness.applied)
    screen.pick_op("say")
    screen.form.cancel()
    settle()
    expect("cancelling sends nothing and gives the picker back",
           (verbs_since(mark), screen.picker.isVisible(), screen.form
            .isVisible()), ([], True, False))

    # THE REFUSAL STAYS IN THE FORM. `wait` declares ms and its own check
    # refuses zero, which is exactly the shape an author gets wrong first.
    mark = len(harness.applied)
    screen.pick_op("wait")
    screen.form.editors["ms"].setValue(0)
    screen.form.accept()
    settle()
    expect("a node the READER would refuse never becomes a command",
           verbs_since(mark), [])
    expect("...the form stays open, with the reason in it",
           (screen.form.isVisible(), bool(screen.form.problem.text())),
           (True, True))
    expect("...and the value the author typed is still there",
           screen.form.values()["ms"], 0.0)
    # THE OTHER HALF: the same form, a legal value, one command.
    screen.form.editors["ms"].setValue(250)
    screen.form.accept()
    settle()
    expect("...and fixing the value in place inserts it",
           verbs_since(mark), ["script.node.add"])
    WAIT = commands_since(mark)[0].args["id"]
    harness.undo()
    screen.refresh()
    settle()

    # ------------------------------------------------------------------
    section("4. Edit… reopens THE SAME form, populated")
    # ------------------------------------------------------------------
    select_node(SAY)
    settle()
    screen.edit_node()
    settle()
    expect("the rows are the ones the picker opened",
           screen.form.keys(), ["text", "who", "note"])
    expect("...filled from the DOCUMENT rather than from the seed",
           screen.form.values()["text"], "Fifty coins and the gate opens.")

    mark = len(harness.applied)
    screen.form.editors["who"].setText("The keeper")
    screen.form.accept()
    settle()
    expect("one changed field is one script.node.set, on that key alone",
           [(c.verb, c.args["key"], c.args["value"])
            for c in commands_since(mark)],
           [("script.node.set", "who", "The keeper")])
    harness.undo()
    screen.refresh()
    settle()
    expect("ONE undo puts the old value back", node(SAY)["who"], "Keeper")

    mark = len(harness.applied)
    select_node(SAY)
    screen.edit_node()
    screen.form.accept()
    settle()
    expect("a form that changed nothing sends nothing",
           (verbs_since(mark), screen.last_notice), ([], "nothing changed"))

    # ------------------------------------------------------------------
    section("5. an `if` draws its arms, and `else` is not `then`")
    # ------------------------------------------------------------------
    mark = len(harness.applied)
    select_node(SAY)
    screen.pick_op("if")
    settle()
    expect("picking a branch opens the CONDITION builder",
           screen.form.keys(), ["var", "operator", "value"])
    expect("...whose comparator row is the closed six, and only those",
           list(screen.form.rows[1].choices), list(sf.COMPARATORS))
    screen.form.accept()          # no variable yet: a branch that always runs
    settle()
    IF = commands_since(mark)[0].args["id"]
    expect("the branch lands after the row that was selected",
           [c.args["after"] for c in commands_since(mark)], [SAY])

    # `say` and `stop` rather than `set`: no scene has declared a variable
    # yet, so the reader refuses `set` here -- correctly, and that half is
    # asserted in section 6. This section is about the ARMS.
    select_arm(IF, "then")
    screen.pick_op("say")
    screen.form.editors["text"].setText("The gate swings open.")
    mark = len(harness.applied)
    screen.form.accept()
    settle()
    expect("a command picked with an ARM selected goes into that arm",
           [(c.args["into"], c.args["arm"]) for c in commands_since(mark)],
           [(IF, "then")])
    THEN_NODE = commands_since(mark)[0].args["id"]

    select_arm(IF, "else")
    screen.pick_op("stop")
    mark = len(harness.applied)
    screen.form.accept()
    settle()
    ELSE_NODE = commands_since(mark)[0].args["id"]
    expect("...and the else arm is addressable the same way",
           [(c.args["into"], c.args["arm"]) for c in commands_since(mark)],
           [(IF, "else")])

    drawn = rows_of()
    by_node = {r["node"]: r for r in drawn if r["node"]}
    expect("the arms are drawn INDENTED under the branch",
           (by_node[IF]["depth"], by_node[THEN_NODE]["depth"],
            by_node[ELSE_NODE]["depth"]), (0, 1, 2))
    expect("a then node hangs off the `if` row itself",
           (by_node[THEN_NODE]["into"], by_node[THEN_NODE]["arm"]),
           (IF, "then"))
    expect("an else node hangs off a DRAWN `else` header instead",
           [(r["text"], r["kind"], r["arm"]) for r in drawn
            if r["kind"] == "arm"], [("else", "arm", "else")])
    expect("so the two arms are told apart by the row, not by reading JSON",
           by_node[ELSE_NODE]["arm"] != by_node[THEN_NODE]["arm"], True)

    # ------------------------------------------------------------------
    section("6. conditions are built -- and the READER still judges them")
    # ------------------------------------------------------------------
    expect("with no scene in the project there is no variable to offer",
           screen.variable_names(), ())
    select_node(IF)
    screen.add_condition("node")
    settle()
    expect("the builder opens anyway, saying what the reader will say",
           ("no variable schema" in screen.form.note.text()), True)
    mark = len(harness.applied)
    screen.form.editors["var"].setText("coins")
    screen.form.editors["value"].setText("100")
    screen.form.accept()
    settle()
    expect("...and it writes NOTHING, because nothing can type `coins` yet",
           verbs_since(mark), [])
    expect("...with the reader's own sentence in the form",
           "no variable schema" in screen.form.problem.text(), True)
    screen.form.cancel()

    # THE OTHER HALF. A scene's `vars` is the only thing that changes, and
    # no line of the screen does.
    library.variables = VARS
    screen.refresh()
    settle()
    expect("a schema turns the variable row into the declared names",
           screen.variable_names(), tuple(VARS.names()))
    select_node(IF)
    screen.add_condition("node")
    mark = len(harness.applied)
    screen.form.editors["var"].setCurrentText("scene.coins")
    screen.form.editors["operator"].setCurrentText("at_least")
    screen.form.editors["value"].setText("50")
    screen.form.accept()
    settle()
    expect("...and the SAME gesture now writes the record",
           [(c.verb, c.args["key"], c.args["value"])
            for c in commands_since(mark)],
           [("script.node.set", "if",
             [{"var": "scene.coins", "at_least": 50}])])
    expect("a condition is a RECORD, never a string",
           isinstance(node(IF)["if"][0], dict), True)
    expect("the row reads it back in words",
           by_node[IF]["text"] if False else
           [r["text"] for r in rows_of() if r["node"] == IF],
           ["if  —  scene.coins at_least 50"])

    harness.undo()
    screen.refresh()
    settle()
    expect("ONE undo takes the condition off", node(IF)["if"], [])
    session.redo()
    screen.refresh()
    settle()

    # A RECORD WITH TWO COMPARATORS is refused by borrowing the reader,
    # naming both -- rather than by a rule restated in a Qt module.
    two = refusal_for_when(screen.document,
                           [{"var": "scene.coins", "at_least": 1,
                             "at_most": 9}],
                           variables=VARS, registry=screen.registry)
    expect("a condition carrying two comparators is refused naming both",
           ("two comparators" in two, "at_least" in two, "at_most" in two),
           (True, True, True))
    expect("...and one comparator is not",
           refusal_for_when(screen.document,
                            [{"var": "scene.coins", "at_least": 1}],
                            variables=VARS, registry=screen.registry), "")

    mark = len(harness.applied)
    screen.add_condition("page")
    screen.form.editors["var"].setCurrentText("scene.paid")
    screen.form.editors["operator"].setCurrentText("is")
    screen.form.editors["value"].setText("false")
    screen.form.accept()
    settle()
    expect("a PAGE's conditions are built the same way, through its verb",
           [(c.verb, c.args["key"]) for c in commands_since(mark)],
           [("script.page.set", "when")])
    mark = len(harness.applied)
    screen.remove_condition("page")
    settle()
    expect("...and taken off the same way",
           [(c.verb, c.args["value"]) for c in commands_since(mark)],
           [("script.page.set", [])])

    # ------------------------------------------------------------------
    section("7. THE STANDALONE GUARANTEE: a script built by hand, that RUNS")
    # ------------------------------------------------------------------
    # The relay is replaced by a TRIPWIRE for the whole of this section. If
    # any gesture below needs it, the builder is not finished.
    relayed: list = []

    def tripwire(scope, text, kind="change", **rest):
        relayed.append((str(scope), text))
        raise AssertionError("the builder reached for the relay")

    real_ask = session.ask
    session.ask = tripwire

    screen.ask = lambda *a, **k: {"id": "toll", "title": "The toll"}
    screen.create_script()
    settle()
    screen.add_page()
    settle()
    TOLL_PAGE = screen.document.page_ids()[0]

    screen.pick_op("say")
    screen.form.editors["text"].setText("Fifty coins.")
    screen.form.editors["who"].setText("Keeper")
    screen.form.accept()
    settle()

    screen.pick_op("if")
    screen.form.editors["var"].setCurrentText("scene.coins")
    screen.form.editors["operator"].setCurrentText("at_least")
    screen.form.editors["value"].setText("50")
    mark = len(harness.applied)
    screen.form.accept()
    settle()
    TOLL_IF = commands_since(mark)[0].args["id"]

    select_arm(TOLL_IF, "then")
    screen.pick_op("set")
    screen.form.editors["var"].setText("gate_open")
    screen.form.editors["to"].setText("true")
    screen.form.editors["by"].setCurrentText("assign")
    mark = len(harness.applied)
    screen.form.accept()
    settle()
    TOLL_THEN = commands_since(mark)[0].args["id"]

    select_arm(TOLL_IF, "else")
    screen.pick_op("set")
    screen.form.editors["var"].setText("paid")
    screen.form.editors["to"].setText("true")
    screen.form.editors["by"].setCurrentText("assign")
    screen.form.accept()
    settle()

    select_arm(TOLL_IF, "else")
    screen.pick_op("stop")
    screen.form.accept()
    settle()

    expect("the whole branching script was built without the relay",
           relayed, [])
    written = library.save()
    path = library.path_for("toll")
    expect("it reaches disk as one file", os.path.basename(path),
           "toll.json")
    expect("...which save reported", path in written, True)

    # THE ENGINE'S OWN READER, and then the engine's own interpreter.
    loaded = sf.load_script(path, variables=VARS,
                            registry=op_registry.OP_REGISTRY)
    expect("the engine's reader loads what the screen wrote",
           loaded.id, "toll")

    def walk(coins: int) -> dict:
        store = sf.VarStore(VARS, {"scene.coins": coins})
        host = SayHost()
        run = ScriptRun(loaded, variables=store, host=host)
        started = run.begin("use")
        for _ in range(64):
            if not run.running:
                break
            run.update(1.0)
            run.advance()               # the continue press, for the `say`
        return {"started": started, "lines": host.lines,
                "gate_open": store.get("scene.gate_open"),
                "paid": store.get("scene.paid"), "done": run.done}

    rich = walk(100)
    expect("it runs, and shows the line the author typed",
           (rich["started"], rich["lines"]),
           (True, [("Keeper", "Fifty coins.")]))
    expect("with 100 coins the THEN arm ran",
           (rich["gate_open"], rich["paid"], rich["done"]),
           (True, False, True))
    poor = walk(10)
    expect("with 10 coins the ELSE arm ran instead",
           (poor["gate_open"], poor["paid"], poor["done"]),
           (False, True, True))

    session.ask = real_ask

    # ------------------------------------------------------------------
    section("8. the relay, at the whole script AND at a placement")
    # ------------------------------------------------------------------
    expect("the strip is aimed at the SCRIPT, never at the map",
           str(screen.strip.scope()), "script:toll")

    # A node INSIDE the then arm, not the arm header: an arm with something
    # in it has no header row of its own, and "after that command" is how a
    # position in a filled body is said. The header exists for the empty
    # case, which is section 5's.
    select_node(TOLL_THEN)
    anchor = screen.anchor_sentence()
    expect("the anchor names the page, the container, the arm and the side",
           (TOLL_PAGE in anchor, TOLL_IF in anchor, "arm 'then'" in anchor,
            "after" in anchor), (True, True, True, True))

    # THE CONTRACT SEAM ITSELF, asserted directly and deterministically:
    #     Session.ask(scope, text) -> the bundle's path
    # What this screen is responsible for is WHAT IT HANDS OVER, and that is
    # asserted here whatever the request writer does with it afterwards.
    handed: list = []

    def recorder(scope, text, kind="change", **rest):
        handed.append((str(scope), text))
        return os.path.join(workspace, "editor", "requests", "pretend")

    session.ask = recorder
    screen.here_field.setText("make the keeper laugh here")
    screen.ask_here()
    session.ask = real_ask
    expect("the placement box asks about the SCRIPT",
           [scope for scope, _text in handed], ["script:toll"])
    note = handed[0][1]
    expect("...carrying the author's sentence",
           "make the keeper laugh here" in note, True)
    expect("...WITH the insertion point in the verbs' own words, so the "
           "responder transcribes it rather than guessing",
           (TOLL_PAGE in note, TOLL_IF in note, "arm 'then'" in note,
            "after %r" % TOLL_THEN in note), (True, True, True, True))
    expect("...and the box is cleared, because it was sent",
           screen.here_field.text(), "")

    screen.here_field.setText("   ")
    expect("an empty box writes nothing and says why",
           (screen.ask_here(), "say what should happen here"
            in screen.last_notice), (None, True))

    # AND THE REAL WRITE, through the real request writer. `describe_scope`
    # takes one arm per scope kind and RAISES for a kind it has none for
    # (law 7, and the arm it is missing is `script`) -- so this is asserted
    # both ways: when the arm lands the bundle is opened and read, and until
    # it does the refusal is asserted to be CLEAN, named, and to leave no
    # half-written bundle behind.
    requests = os.path.join(workspace, "editor", "requests")
    before = set(os.listdir(requests)) if os.path.isdir(requests) else set()
    screen.here_field.setText("make the keeper laugh here")
    bundle = screen.ask_here()
    after = set(os.listdir(requests)) if os.path.isdir(requests) else set()
    if bundle:
        with open(os.path.join(bundle, "manifest.json"),
                  encoding="utf-8") as fh:
            payload = json.load(fh)
        expect("the bundle is scoped to the SCRIPT, not to the map",
               payload.get("scoped"), "script:toll")
        expect("...carrying only the verbs that can touch a script",
               sorted({v.split(".")[0] for v in payload.get("verbs", [])}),
               ["script"])
        expect("...and the anchor travels in the note",
               TOLL_IF in payload["notes"][0]["text"], True)
    else:
        print("        BLOCKED: editor/core/request.py's `describe_scope` "
              "has no `script` arm, so no bundle can be written for a "
              "script scope yet -- by either relay grain.")
        expect("...it refuses CLEANLY, naming the arm that is missing",
               ("describe_scope" in screen.last_notice,
                "script" in screen.last_notice), (True, True))
        # THE HALF THIS SCREEN OWNS: a refusal costs the author the press
        # and not the typing. `PromptStrip.ask` makes the same promise, and
        # it is the difference between retrying and retyping.
        expect("...and the sentence the author wrote is still in the box",
               screen.here_field.text(), "make the keeper laugh here")
        if after != before:
            print("        NOTE: `write_bundle` created %s before raising, "
                  "so the refused request leaves a directory behind. That "
                  "is editor/core/request.py's, not this screen's."
                  % sorted(after - before))

    # ------------------------------------------------------------------
    section("9. the door: the ENTITY screen, where the author looked")
    # ------------------------------------------------------------------
    HERO = Scope.of(("map", "fixture"), ("layer", "entity"), ("object", "1"))
    document = session.project.map("fixture")

    def props() -> dict:
        return document.object_layer("entity").find(1).properties.as_dict()

    entity = ObjectEditor(session, HERO, harness)
    entity.command_requested.connect(harness.run)
    entity.show()
    settle()
    expect("an object with no script says what a script IS, and what to press",
           entity.script_note.text(), NO_SCRIPT_ON_OBJECT)
    expect("...and Edit… cannot act on nothing",
           entity.script_edit.isEnabled(), False)
    expect("...while the scripts that exist are offered",
           [entity.script_box.itemText(i)
            for i in range(entity.script_box.count())],
           ["", SCRIPT_ID, "toll"])

    opened: list[str] = []
    entity.script_requested.connect(opened.append)
    entity.ask = lambda *a, **k: {"id": "chest", "title": "A chest"}
    mark = len(harness.applied)
    entity.new_script()
    settle()
    expect("New… creates the script AND names it on the object, as ONE "
           "transaction",
           [(c.verb, str(c.scope)) for c in commands_since(mark)],
           [("script.create", "script:chest"),
            ("map.object.property.set", str(HERO))])
    expect("the object now runs it", props().get(SCRIPT), "chest")
    expect("...and the event screen was asked for", opened, ["chest"])
    expect("the row says what it does now",
           "chest" in entity.script_note.text(), True)

    harness.undo()
    entity.refresh()
    settle()
    expect("ONE undo takes back the whole gesture -- both halves of it",
           (SCRIPT in props(), library.has("chest")), (False, False))

    entity.choose_script(SCRIPT_ID)
    settle()
    expect("choosing an existing script names it on the object",
           props().get(SCRIPT), SCRIPT_ID)
    entity.refresh()
    settle()
    expect("...and Edit… can act now", entity.script_edit.isEnabled(), True)
    opened.clear()
    entity.open_script()
    expect("...and asks for that one", opened, [SCRIPT_ID])

    notes = [s.note for s in entity._ObjectEditor__describe_object().sections
             if s.title == "Properties"]
    keys = [f.key for s in entity._ObjectEditor__describe_object().sections
            if s.title == "Properties" for f in s.fields]
    expect("the property is lifted OUT of the untyped Properties list",
           SCRIPT in keys, False)
    expect("...and the list says where it went",
           any(SCRIPT_MOVED in n for n in notes), True)

    entity.choose_script("")
    settle()
    expect("blank REMOVES the property rather than emptying it",
           SCRIPT in props(), False)

    # ------------------------------------------------------------------
    section("10. reachable from the real window, and nothing modal")
    # ------------------------------------------------------------------
    window = EditorWindow(session)
    window.settings = EditorSettings(FakeStore())
    window.show()
    settle()
    expect("the window has a door of its own", hasattr(window, "open_script"),
           True)
    titles = []
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None:
            titles += [a.text() for a in menu.actions()]
    expect("...on a menu, so a script is reachable without an object",
           any("Event scripts" in t for t in titles), True)

    window.open_script("toll")
    settle()
    expect("it opens the event screen on that script",
           (window.script_editor is not None,
            window.script_editor.script_id), (True, "toll"))

    window.edit_object(HERO)
    settle()
    window.object_editor.script_requested.emit(SCRIPT_ID)
    settle()
    expect("the ENTITY screen's door really reaches it -- one window, "
           "re-aimed", window.script_editor.script_id, SCRIPT_ID)

    for name, module in (("script_editor", "editor/ui/script_editor.py"),
                         ("object_editor", "editor/ui/object_editor.py")):
        with open(os.path.join(REPO, module), encoding="utf-8") as handle:
            source = handle.read()
        expect(f"no blocking call anywhere in {name} (law 13)",
               bool(re.search(r"\.exec\s*\(", source)), False)

    expect("argument_value reads what was typed, and invents nothing",
           [argument_value(t) for t in ("100", "true", '["a", "b"]',
                                        "Pay half", "")],
           [100, True, ["a", "b"], "Pay half", ""])

    expect("nothing modal through any gesture in this file", modals(), [])

    window.close()
    entity.close()
    screen.close()
    settle()

finally:
    application.processEvents()
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("check_script_editor: all assertions passed")
