"""Verify the `script.*` verbs: what they write, what they refuse, what undo
puts back.

    .venv/Scripts/python.exe tools/check_script_verbs.py

`editor/core/event_script.py` is the AUTHORING half of
`data/project/scripts/*.json` and `editor/core/verbs.py` is its vocabulary.
Everything below except section 8 is proved here or not at all -- an inverse
that nothing exercises is not exercised by playing the game either:

  1. every verb's inverse restores the document BYTE FOR BYTE -- including
     the awkward ones: a node lifted out of a nested `elif` arm, a page
     pulled from the middle, a move that is a no-op, a subtree carried
     whole
  2. a node is addressed by its stable ID and placed by an ANCHOR id and a
     side, never by an index -- so an `after` that is not a sibling is
     refused rather than silently landing at the end
  3. a verb refuses at EDIT time everything the reader would refuse at LOAD
     time, because it runs the reader: a duplicate id, an unknown `do`, an
     op outside the declared loadouts, a condition carrying two comparators
  4. a refusal changes NOTHING -- the document is byte-identical afterwards,
     which is the property that makes a rolled-back batch safe
  5. creation and deletion reach the DISK only at `save()`, so a delete that
     is undone leaves the file where it was (`docs/PLAN_SCENES.md` 2.5, and
     the measured fault in `Project.drop_table` it exists to avoid)
  6. the canonical rendering: a key at its default is written as no key at
     all, which is what lets `set` be its own exact inverse without a second
     `unset` verb per level
  7. the VARIABLE SCHEMA seam (section 8): `scripts_of` -- the one function
     every editor surface reaches a library through -- hands the library
     what `data/project/scenes/*.json` declares, so a script naming a
     variable can be opened by the editor and not only run by the game
  8. the SAVE WIRE (section 9): authoring a script makes the SESSION dirty
     and the editor's own save puts the `.json` on disk, so a map that
     names a script and the script itself reach the disk together and the
     next boot of the game finds what the map references

EVERY ASSERTION IS A PAIR
-------------------------
A gate proved to let something through and never proved to stop it is the
dominant failure this repo has found in its own checks (law 5). Every
refusal below is followed by a POSITIVE CONTROL -- the same command with the
one wrong thing made right -- so a guard that refused everything would go
red here, and so would a guard that refused nothing.

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
A temporary workspace, built here, thrown away at the end. `data/maps/`,
`tools/baseline.json` and the author's own project are never WRITTEN.
Law 4.

Section 8 is the one place that READS the real project, in two rows, and it
is deliberate: every fixture in this tree passed while the seam it covers
was broken, which is what kept the defect invisible for a whole pass. Those
two rows name no script, no variable and no file -- they assert that the
wiring hands over a schema and that the library opens whatever is on disk --
so they survive a renamed script and die on a broken seam. Every tooth in
that section is on a fixture built here.

NEVER CALL THE WRITER YOU ARE TRYING TO PROVE IS CALLED
------------------------------------------------------
Section 6 calls `library.save()` on purpose: it is about what the writer
WRITES. Section 9 is about whether anything calls it, so it never touches
that method -- it drives `Session.save()` and `session.dirty`, the two
things `MainWindow.save()` and `MainWindow.closeEvent` call and nothing
else. The distinction is not pedantry: `ScriptLibrary.save()` had six
callers in this tree and all six were in `tools/`, four of them in section
6, while the editor called it nowhere and an authored script was lost on
every close.

No Qt. pygame arrives through `scripts.game.flow.ops`, which is what holds
the op registry the node verbs validate against.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import json
import os
import shutil
import sys
import tempfile
import warnings

from scripts.loaders import script_file as sf

from editor.core import event_script
from editor.core.commands import Command
from editor.core.errors import PyoneerCommandApplyError
from editor.core.project import Project
from editor.core.scope import SCOPE_KINDS, Scope
from editor.core.session import Session
from scripts.game.flow import ops as op_registry

failures: list[str] = []


def brief(value, limit: int = 34) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
          f"got={brief(got)} want={brief(want)}")
    if not ok:
        failures.append(label)
        if isinstance(got, str) and isinstance(want, str):
            low = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b),
                       min(len(want), len(got)))
            print(f"        first diff at character {low}")
            print(f"        want ...{want[max(0, low - 60):low + 60]!r}...")
            print(f"        got  ...{got[max(0, low - 60):low + 60]!r}...")


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


# --------------------------------------------------------------------------
# The workspace
# --------------------------------------------------------------------------

workspace = tempfile.mkdtemp(prefix="pyoneer_script_verbs_")
os.makedirs(os.path.join(workspace, "data", "project"), exist_ok=True)
os.makedirs(os.path.join(workspace, "config"), exist_ok=True)
with open(os.path.join(workspace, "config", "maps.json"), "w",
          encoding="utf-8") as handle:
    json.dump({"data": []}, handle)
with open(os.path.join(workspace, "data", "project", "project.json"), "w",
          encoding="utf-8") as handle:
    json.dump({"genre": "topdown_rpg"}, handle)

session = Session.open(workspace, genre_id="topdown_rpg")
library = event_script.scripts_of(session.project)

SCRIPT = "keeper_gate"
GATE = Scope.of(("script", SCRIPT))
OTHER = Scope.of(("script", "shop_intro"))

VARS = sf.read_vars({
    "gate_open": {"type": "bool", "default": False, "doc": "The gate."},
    "coins": {"type": "int", "default": 0, "doc": "Spendable."},
    "keeper_pick": {"type": "int", "default": -1, "doc": "An ask writes it."},
})


def text(script_id: str = SCRIPT) -> str:
    """The exact bytes the library would save for one document."""
    if not library.has(script_id):
        return "<no such document>"
    return library.document(script_id).render(library.registry)


def refusal(command: Command) -> str:
    """The message ONE command refused with, or "" if it did not refuse."""
    try:
        session.run(command)
    except PyoneerCommandApplyError as exc:
        return str(exc)
    return ""


def both_halves(label: str, *commands: Command, changes: bool = True) -> None:
    """Apply, prove it CHANGED something, undo, prove the bytes came back.

    The forward assertion is the half that is easy to leave out: an inverse
    that restores a document a verb never touched is a passing test of
    nothing at all.
    """
    before = text()
    session.run(list(commands))
    after = text()
    if changes:
        expect(f"{label}: changes the document", after != before, True)
    session.undo()
    expect(f"{label}: undo restores it byte for byte", text(), before)


# --------------------------------------------------------------------------
section("1. the vocabulary exists and is reachable")
# --------------------------------------------------------------------------
# The signature defect this repo records five times is a layer that is
# complete, checked and unreachable. A `script.*` verb whose scope cannot be
# PARSED is exactly that, so the scope kind is asserted before anything else.

from editor.core.commands import all_verbs  # noqa: E402  (after registration)

registered = sorted(v.name for v in all_verbs() if v.name.startswith("script."))
expect("`script` is a scope kind, so a script scope parses at all",
       "script" in SCOPE_KINDS, True)
expect("and a script scope really does parse",
       str(Scope.parse("script:keeper_gate")), "script:keeper_gate")
expect("the fourteen verbs of PLAN_SCENES 6.4 are registered", registered, [
    "script.create", "script.delete", "script.node.add", "script.node.move",
    "script.node.remove", "script.node.restore", "script.node.set",
    "script.page.add", "script.page.move", "script.page.remove",
    "script.page.restore", "script.page.set", "script.restore", "script.set",
])
expect("every one of them accepts a script scope and nothing else",
       sorted({tuple(v.scopes) for v in all_verbs()
               if v.name.startswith("script.")}), [("script:*",)])
expect("and the three that cannot be undone from the outside say so",
       sorted(v.name for v in all_verbs()
              if v.name.startswith("script.") and v.destructive),
       ["script.delete", "script.node.remove", "script.page.remove"])


# --------------------------------------------------------------------------
section("2. create, and the canonical rendering")
# --------------------------------------------------------------------------

session.run(Command("script.create", GATE,
                    {"title": "The keeper at the north gate"}))
expect("script.create makes a document the library knows", library.has(SCRIPT),
       True)
expect("with the core loadout when none was declared",
       library.document(SCRIPT).loadouts, ["core"])
expect("and renders as deterministic, sorted, one-newline JSON", text(),
       '{\n'
       '  "format": "pyoneer.script",\n'
       '  "id": "keeper_gate",\n'
       '  "loadouts": [\n'
       '    "core"\n'
       '  ],\n'
       '  "pages": [],\n'
       '  "title": "The keeper at the north gate",\n'
       '  "version": 1\n'
       '}\n')

expect("creating the same id twice is refused",
       "already exists" in refusal(Command("script.create", GATE, {})), True)
expect("...and the positive control: a DIFFERENT id is created",
       refusal(Command("script.create", OTHER, {})), "")
session.undo()
expect("and that refusal left the document byte-identical",
       library.has("shop_intro"), False)

# A hand-written document is normalised on the way in: "the key is absent"
# and "the key holds its default" are ONE state, which is what makes every
# `set` verb its own exact inverse without a second `unset` verb per level.
noisy = event_script.ScriptDocument.from_json({
    "format": sf.FORMAT, "version": 1, "id": "noisy", "title": "",
    "loadouts": ["core"],
    "pages": [{"id": "pg", "trigger": "use", "when": [], "note": "",
               "payload": "", "once": False, "cooldown_ms": 0,
               "body": [{"id": "n1", "do": "say", "text": "hi", "who": "",
                         "note": ""}]}]})
noisy.commit()
expect("a key written at its format default is dropped from the rendering",
       json.loads(noisy.render())["pages"][0],
       {"id": "pg", "trigger": "use", "when": [],
        "body": [{"id": "n1", "do": "say", "text": "hi"}]})
expect("...and the positive control: a key OFF its default survives",
       (lambda d: (d.pages[0].update({"once": True, "payload": "keeper"}),
                   d.commit(),
                   json.loads(d.render())["pages"][0]["once"],
                   json.loads(d.render())["pages"][0]["payload"])[2:])(noisy),
       (True, "keeper"))


# --------------------------------------------------------------------------
section("3. pages: add, set, move, remove -- and undo, byte for byte")
# --------------------------------------------------------------------------

session.run([
    Command("script.page.add", GATE,
            {"id": "pg_main", "trigger": "use", "when": []}),
    Command("script.page.set", GATE,
            {"page": "pg_main", "key": "payload", "value": "keeper"}),
])
expect("script.page.add put the page in the document",
       [p["id"] for p in library.document(SCRIPT).pages], ["pg_main"])

both_halves("script.page.add with after='' lands it FIRST",
            Command("script.page.add", GATE, {"id": "pg_open", "when": []}))
session.run(Command("script.page.add", GATE, {"id": "pg_open", "when": []}))
expect("an empty `after` really does mean the front, not the back",
       [p["id"] for p in library.document(SCRIPT).pages],
       ["pg_open", "pg_main"])

session.run(Command("script.page.add", GATE,
                    {"id": "pg_last", "after": "pg_main"}))
expect("...and naming the last sibling is how a page is appended",
       [p["id"] for p in library.document(SCRIPT).pages],
       ["pg_open", "pg_main", "pg_last"])

both_halves("script.page.remove from the MIDDLE",
            Command("script.page.remove", GATE, {"page": "pg_main"}))
both_halves("script.page.set trigger",
            Command("script.page.set", GATE,
                    {"page": "pg_main", "key": "trigger", "value": "enter"}))
both_halves("script.page.set once (absent -> present)",
            Command("script.page.set", GATE,
                    {"page": "pg_main", "key": "once", "value": True}))
both_halves("script.page.set cooldown_ms (absent -> present)",
            Command("script.page.set", GATE,
                    {"page": "pg_main", "key": "cooldown_ms", "value": 400}))
both_halves("script.page.set note (absent -> present)",
            Command("script.page.set", GATE,
                    {"page": "pg_main", "key": "note",
                     "value": "once the gate is open the keeper only nods"}))
both_halves("script.page.move to the front",
            Command("script.page.move", GATE, {"page": "pg_last", "after": ""}))
both_halves("script.page.move into the middle",
            Command("script.page.move", GATE,
                    {"page": "pg_open", "after": "pg_main"}))

unchanged = text()
transaction = session.run(Command("script.page.move", GATE,
                                  {"page": "pg_open", "after": ""}))
expect("a move that is a NO-OP writes nothing and records no inverse",
       (text() == unchanged, transaction.inverses[0].verb), (True, "noop"))
session.undo()
expect("...and the positive control: a move that is NOT a no-op does both",
       (lambda: (session.run(Command("script.page.move", GATE,
                                     {"page": "pg_open",
                                      "after": "pg_last"})).inverses[0].verb,
                 text() != unchanged))(),
       ("script.page.move", True))
session.undo()
expect("which undo put back exactly", text(), unchanged)


# --------------------------------------------------------------------------
section("4. nodes: the tree, the arms, and the id that addresses them")
# --------------------------------------------------------------------------

library.variables = VARS

session.run([
    Command("script.node.add", GATE,
            {"id": "n2", "do": "hold", "into": "pg_main",
             "args": {"steerable": False}}),
    Command("script.node.add", GATE,
            {"id": "n3", "do": "say", "into": "pg_main", "after": "n2",
             "args": {"who": "Keeper", "text": "The north gate is sealed."}}),
    Command("script.node.add", GATE,
            {"id": "n4", "do": "if", "into": "pg_main", "after": "n3",
             "args": {"when": [{"var": "coins", "at_least": 100}]}}),
    Command("script.node.add", GATE,
            {"id": "n5", "do": "say", "into": "n4", "arm": "then",
             "args": {"who": "Keeper", "text": "Unless you can pay."}}),
    Command("script.node.set", GATE,
            {"node": "n4", "key": "elif",
             "value": [{"when": [{"var": "coins", "at_least": 10}],
                        "then": []}]}),
    Command("script.node.add", GATE,
            {"id": "n8", "do": "say", "into": "n4", "arm": "elif:0",
             "args": {"text": "Half now?"}}),
    Command("script.node.add", GATE,
            {"id": "n9", "do": "if", "into": "n4", "arm": "elif:0",
             "after": "n8",
             "args": {"when": [{"var": "keeper_pick", "is": 0}]}}),
    Command("script.node.add", GATE,
            {"id": "n10", "do": "say", "into": "n9", "arm": "then",
             "args": {"text": "Half it is."}}),
    Command("script.node.add", GATE,
            {"id": "n11", "do": "say", "into": "n9", "arm": "else",
             "args": {"text": "Then wait."}}),
    Command("script.node.add", GATE,
            {"id": "n12", "do": "say", "into": "n4", "arm": "else",
             "args": {"text": "Come back with coin."}}),
    Command("script.node.add", GATE,
            {"id": "n13", "do": "stop", "into": "n4", "arm": "else",
             "after": "n12"}),
], label="build the keeper")

document = library.document(SCRIPT)
expect("the whole tree of PLAN_SCENES 3.4 is reachable through the verbs",
       document.ids(),
       ["pg_open", "pg_main", "n2", "n3", "n4", "n5", "n8", "n9",
        "n10", "n11", "n12", "n13", "pg_last"])
expect("and the engine's own reader loads it",
       [p.id for p in document.validate(variables=VARS).pages],
       ["pg_open", "pg_main", "pg_last"])

expect("a node knows which arm it sits in and what precedes it",
       (document.locate("n9").into, document.locate("n9").arm,
        document.locate("n9").after),
       ("n4", "elif:0", "n8"))
expect("...and one at the front of a page body reports NO predecessor",
       (document.locate("n2").into, document.locate("n2").arm,
        document.locate("n2").after),
       ("pg_main", "", ""))

# The hard one the ask names: out of the middle of a nested elif arm, and
# back into the same arm at the same place.
session.run(Command("script.node.add", GATE,
                    {"id": "n8b", "do": "say", "into": "n4", "arm": "elif:0",
                     "after": "n8", "args": {"text": "middle"}}))
both_halves("script.node.remove from the MIDDLE of a nested elif arm",
            Command("script.node.remove", GATE, {"node": "n8b"}))
both_halves("script.node.remove of a SUBTREE (an if with both arms filled)",
            Command("script.node.remove", GATE, {"node": "n9"}))
both_halves("script.node.remove of the FIRST node in a page body",
            Command("script.node.remove", GATE, {"node": "n2"}))
both_halves("script.node.add into an else arm that does not exist yet",
            Command("script.node.add", GATE,
                    {"id": "nx", "do": "stop", "into": "n9", "arm": "else",
                     "after": "n11"}))
both_halves("script.node.set on an op argument",
            Command("script.node.set", GATE,
                    {"node": "n3", "key": "text", "value": "Rewritten."}))
both_halves("script.node.set on an argument that was ABSENT (who -> set)",
            Command("script.node.set", GATE,
                    {"node": "n10", "key": "who", "value": "Keeper"}))
both_halves("script.node.set on a control node's conditions",
            Command("script.node.set", GATE,
                    {"node": "n4", "key": "if",
                     "value": [{"var": "gate_open", "is": True}]}))
both_halves("script.node.set adding a second elif arm",
            Command("script.node.set", GATE,
                    {"node": "n4", "key": "elif",
                     "value": [{"when": [{"var": "coins", "at_least": 10}],
                                "then": []},
                               {"when": [], "then": []}]}))
both_halves("script.node.move across arms (then -> else)",
            Command("script.node.move", GATE,
                    {"node": "n5", "into": "n4", "arm": "else",
                     "after": "n12"}))
both_halves("script.node.move to another page entirely",
            Command("script.node.move", GATE,
                    {"node": "n4", "into": "pg_open", "arm": "", "after": ""}))
both_halves("script.node.move within one container (reorder)",
            Command("script.node.move", GATE,
                    {"node": "n2", "into": "pg_main", "after": "n4"}))

steady = text()
transaction = session.run(Command("script.node.move", GATE,
                                  {"node": "n3", "into": "pg_main",
                                   "arm": "", "after": "n2"}))
expect("a node move that is a NO-OP writes nothing and records no inverse",
       (text() == steady, transaction.inverses[0].verb), (True, "noop"))
session.undo()
expect("...and the positive control: one place further along is NOT a no-op",
       (lambda: (session.run(Command("script.node.move", GATE,
                                     {"node": "n3", "into": "pg_main",
                                      "after": "n4"})).inverses[0].verb,
                 text() != steady))(),
       ("script.node.move", True))
session.undo()
expect("which undo put back exactly", text(), steady)

expect("a whole page carrying a subtree survives remove -> undo",
       (lambda: (session.run(Command("script.page.remove", GATE,
                                     {"page": "pg_main"})),
                 session.undo(), text())[2])(),
       steady)


# --------------------------------------------------------------------------
section("5. the refusals, each with a positive control")
# --------------------------------------------------------------------------

INTACT = text()


def refuses(label: str, needle: str, bad: Command, good: Command) -> None:
    """`bad` refuses NAMING `needle`, changes nothing; `good` goes through."""
    said = refusal(bad)
    expect(label, (needle in said, text() == INTACT), (True, True))
    allowed = refusal(good)
    expect(f"    ...positive control: the same command, made legal",
           allowed, "")
    if not allowed:
        session.undo()
    expect("    ...and the document is back where it started", text(), INTACT)


refuses("an `after` that is not a SIBLING is refused, naming the container",
        "has to be a SIBLING",
        Command("script.node.add", GATE,
                {"id": "z1", "do": "stop", "into": "pg_main", "after": "n10"}),
        Command("script.node.add", GATE,
                {"id": "z1", "do": "stop", "into": "pg_main", "after": "n3"}))

refuses("an arm the node does not have is refused, listing the ones it does",
        "has no 'elif:7' arm",
        Command("script.node.add", GATE,
                {"id": "z2", "do": "stop", "into": "n4", "arm": "elif:7"}),
        Command("script.node.add", GATE,
                {"id": "z2", "do": "stop", "into": "n4", "arm": "elif:0"}))

refuses("a `do` node holds no body and says so",
        "holds no body",
        Command("script.node.add", GATE,
                {"id": "z3", "do": "stop", "into": "n3", "arm": "then"}),
        Command("script.node.add", GATE,
                {"id": "z3", "do": "stop", "into": "n4", "arm": "then"}))

refuses("a page takes no arm",
        "takes no arm",
        Command("script.node.add", GATE,
                {"id": "z4", "do": "stop", "into": "pg_main", "arm": "then"}),
        Command("script.node.add", GATE,
                {"id": "z4", "do": "stop", "into": "pg_main", "arm": ""}))

refuses("moving a node INTO its own subtree is refused, naming the subtree",
        "would detach the subtree",
        Command("script.node.move", GATE,
                {"node": "n4", "into": "n9", "arm": "then"}),
        Command("script.node.move", GATE,
                {"node": "n4", "into": "pg_open", "arm": ""}))

refuses("a duplicate id is refused with the READER's own message",
        "is already used at",
        Command("script.node.add", GATE,
                {"id": "n3", "do": "stop", "into": "pg_main", "after": "n3"}),
        Command("script.node.add", GATE,
                {"id": "n99", "do": "stop", "into": "pg_main", "after": "n3"}))

refuses("a page id colliding with a NODE id is refused -- one namespace",
        "is already used at",
        Command("script.page.add", GATE, {"id": "n3"}),
        Command("script.page.add", GATE, {"id": "pg_fresh"}))

refuses("an unknown `do` is refused rather than skipped",
        "script op",
        Command("script.node.add", GATE,
                {"id": "z5", "do": "teleport", "into": "pg_main",
                 "after": "n3"}),
        Command("script.node.add", GATE,
                {"id": "z5", "do": "wait", "into": "pg_main", "after": "n3",
                 "args": {"ms": 250}}))

refuses("an op argument the op does not take is refused, naming what it does",
        "this format has no meaning for",
        Command("script.node.add", GATE,
                {"id": "z6", "do": "say", "into": "pg_main", "after": "n3",
                 "args": {"txt": "typo"}}),
        Command("script.node.add", GATE,
                {"id": "z6", "do": "say", "into": "pg_main", "after": "n3",
                 "args": {"text": "spelled right"}}))

refuses("a required op argument that is missing is refused",
        "and the node does not give it",
        Command("script.node.add", GATE,
                {"id": "z7", "do": "say", "into": "pg_main", "after": "n3"}),
        Command("script.node.add", GATE,
                {"id": "z7", "do": "say", "into": "pg_main", "after": "n3",
                 "args": {"text": "given"}}))

refuses("a condition carrying TWO comparators is refused, naming both",
        "carries two comparators",
        Command("script.page.set", GATE,
                {"page": "pg_main", "key": "when",
                 "value": [{"var": "coins", "is": 1, "at_least": 2}]}),
        Command("script.page.set", GATE,
                {"page": "pg_main", "key": "when",
                 "value": [{"var": "coins", "at_least": 2}]}))

refuses("a variable nothing declares is refused, naming the schema",
        "scene variable",
        Command("script.page.set", GATE,
                {"page": "pg_main", "key": "when",
                 "value": [{"var": "invented", "is": 1}]}),
        Command("script.page.set", GATE,
                {"page": "pg_main", "key": "when",
                 "value": [{"var": "gate_open", "is": True}]}))

refuses("a trigger outside the closed five is refused at the door",
        "is not one of",
        Command("script.page.set", GATE,
                {"page": "pg_main", "key": "trigger", "value": "shout"}),
        Command("script.page.set", GATE,
                {"page": "pg_main", "key": "trigger", "value": "enter"}))

refuses("`id` is the address and is not settable",
        "is not a settable key",
        Command("script.node.set", GATE,
                {"node": "n3", "key": "id", "value": "renamed"}),
        Command("script.node.set", GATE,
                {"node": "n3", "key": "note", "value": "a note"}))

refuses("`then` holds nodes, so it is not settable either",
        "is not a settable key",
        Command("script.node.set", GATE,
                {"node": "n4", "key": "then", "value": []}),
        Command("script.node.set", GATE,
                {"node": "n4", "key": "elif", "value": []}))

refuses("`args` may not smuggle structure past the node verbs",
        "which is structure rather than content",
        Command("script.node.add", GATE,
                {"id": "z8", "do": "if", "into": "pg_main", "after": "n3",
                 "args": {"then": [{"id": "z9", "do": "stop"}]}}),
        Command("script.node.add", GATE,
                {"id": "z8", "do": "if", "into": "pg_main", "after": "n3",
                 "args": {"when": []}}))

refuses("script.delete without confirm is refused",
        "needs confirm=true",
        Command("script.delete", GATE, {"confirm": False}),
        Command("script.delete", GATE, {"confirm": True}))

refuses("a page cannot be moved to follow itself",
        "cannot follow itself",
        Command("script.page.move", GATE,
                {"page": "pg_main", "after": "pg_main"}),
        Command("script.page.move", GATE,
                {"page": "pg_main", "after": "pg_open"}))

refuses("a restore payload with no id is refused before anything moves",
        "carries its own stable `id`",
        Command("script.node.restore", GATE,
                {"node": {"do": "stop"}, "into": "pg_main", "after": "n3"}),
        Command("script.node.restore", GATE,
                {"node": {"id": "zb", "do": "stop"}, "into": "pg_main",
                 "after": "n3"}))

refuses("script.restore refuses a payload whose id disagrees with the scope",
        "the scope says",
        Command("script.restore", OTHER,
                {"script": json.loads(text())}),
        Command("script.restore", OTHER,
                {"script": dict(json.loads(text()), id="shop_intro")}))

# A `while` really does refuse `else`, asked directly rather than through the
# arm-index message above.
session.run(Command("script.node.add", GATE,
                    {"id": "w1", "do": "while", "into": "pg_main",
                     "after": "n3", "args": {"when": []}}))
said = refusal(Command("script.node.add", GATE,
                       {"id": "w2", "do": "stop", "into": "w1",
                        "arm": "else"}))
expect("a `while` refuses an else arm, naming the reason",
       ("has no 'else' arm" in said, "run it on every exit" in said),
       (True, True))
expect("    ...positive control: the `then` arm of the same while is fine",
       refusal(Command("script.node.add", GATE,
                       {"id": "w2", "do": "stop", "into": "w1",
                        "arm": "then"})), "")
session.undo()
session.undo()
expect("and the document is back where it started", text(), INTACT)

# The `if` / op ambiguity guard. `script.node.add` accepts `if` where it
# accepts an op name, so an op that claimed the word would silently change
# what every `if` in every document means.
shadow = dict(op_registry.OP_REGISTRY)
shadow["if"] = op_registry.OpSpec(name="if", summary="a decoy",
                                  run=lambda run, args: True)
library.registry = shadow
expect("an op that claims the word `if` collides LOUDLY at the node verb",
       "cannot mean both" in refusal(
           Command("script.node.add", GATE,
                   {"id": "zc", "do": "if", "into": "pg_main",
                    "after": "n3", "args": {"when": []}})), True)
library.registry = None
expect("    ...positive control: with no such op, the same command lands",
       refusal(Command("script.node.add", GATE,
                       {"id": "zc", "do": "if", "into": "pg_main",
                        "after": "n3", "args": {"when": []}})), "")
session.undo()
expect("and the document is STILL byte-identical after every refusal above",
       text(), INTACT)

# The variable schema is a real slot, not decoration: with none set, a
# condition is refused with the message that names the fix.
library.variables = None
expect("with no variable schema a condition is refused, naming the fix",
       "was given no variable schema" in refusal(
           Command("script.page.set", GATE,
                   {"page": "pg_main", "key": "when",
                    "value": [{"var": "coins", "at_least": 5}]})), True)
library.variables = VARS
expect("    ...positive control: with the schema set, the same edit lands",
       refusal(Command("script.page.set", GATE,
                       {"page": "pg_main", "key": "when",
                        "value": [{"var": "coins", "at_least": 5}]})), "")
session.undo()
expect("and the document is unchanged", text(), INTACT)


# --------------------------------------------------------------------------
section("6. the disk: created and deleted in memory, written at save")
# --------------------------------------------------------------------------
# PLAN_SCENES 2.5. The measured fault it exists to avoid: `Project.drop_table`
# calls `os.remove` INSIDE the command, so a drop that is rolled back has
# already deleted the file.

path = library.path_for(SCRIPT)
expect("nothing is on disk before a save", os.path.isfile(path), False)
written = library.save()
expect("save() writes the dirty document and reports its path",
       (os.path.isfile(path), written), (True, [path]))
expect("and what it wrote is exactly what render() says", text(),
       open(path, "r", encoding="utf-8", newline="").read())
expect("a second save writes nothing, because nothing is dirty",
       library.save(), [])

session.run(Command("script.delete", GATE, {"confirm": True}))
expect("a delete removes it from the model and leaves the FILE alone",
       (library.has(SCRIPT), os.path.isfile(path)), (False, True))
session.undo()
library.save()
expect("...so undoing the delete leaves the file exactly where it was",
       (library.has(SCRIPT), os.path.isfile(path)), (True, True))

session.run(Command("script.delete", GATE, {"confirm": True}))
library.save()
expect("...and the positive control: a delete that is SAVED does remove it",
       os.path.isfile(path), False)
session.undo()
expect("undo brings the whole document back, byte for byte", text(), INTACT)
library.save()
expect("and saving writes it out again", os.path.isfile(path), True)

reloaded = event_script.ScriptLibrary(library.directory, variables=VARS)
expect("a fresh library reads back exactly what was written",
       reloaded.document(SCRIPT).render(), INTACT)
expect("and the engine's own reader loads that file from disk",
       sorted(sf.load_scripts(library.directory, variables=VARS)), [SCRIPT])


# --------------------------------------------------------------------------
section("7. reachability: the author can get at these without a screen")
# --------------------------------------------------------------------------
# The defect `CLAUDE.md` records five times is a layer that is complete,
# checked, and unreachable by the person who asked for it. There is no event
# SCREEN yet -- that is the next pass -- so the question is whether these
# verbs can be driven at all today. They can, through the route the author
# actually described: ask the AI, apply what it writes back. That path is
# generic (`Command.from_json` -> `Scope.parse` -> the registry), which is
# exactly why the scope kind had to exist before the verbs meant anything.

bundle_dir = os.path.join(workspace, "response")
os.makedirs(bundle_dir, exist_ok=True)
response = os.path.join(bundle_dir, "response.jsonl")
with open(response, "w", encoding="utf-8", newline="\n") as handle:
    for line in (
        {"verb": "script.node.add", "scope": "script:keeper_gate",
         "args": {"id": "relayed", "do": "say", "into": "pg_main",
                  "after": "n3", "args": {"text": "Written by the relay."}}},
        {"verb": "script.page.set", "scope": "script:keeper_gate",
         "args": {"page": "pg_main", "key": "note", "value": "relayed too"}},
    ):
        handle.write(json.dumps(line) + "\n")

before = text()
session.apply_response(response)
expect("a response.jsonl full of script.* verbs applies as one transaction",
       ("relayed" in library.document(SCRIPT).ids(), text() != before),
       (True, True))
session.undo()
expect("...and ONE undo takes the whole batch back, byte for byte",
       text(), before)

with open(response, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(json.dumps(
        {"verb": "script.node.add", "scope": "script:keeper_gate",
         "args": {"id": "relayed", "do": "say", "into": "nowhere",
                  "args": {"text": "misaddressed"}}}) + "\n")
try:
    session.apply_response(response)
    landed = ""
except PyoneerCommandApplyError as exc:
    landed = str(exc)
expect("...and the positive control: a batch naming a container that does "
       "not exist is refused whole, leaving nothing behind",
       ("script node" in landed, text()), (True, before))


# --------------------------------------------------------------------------
section("8. the variable schema: a file, a reader, and ONE wire")
# --------------------------------------------------------------------------
# The defect this closes was measured by playing the shipped game: it RAN
# `data/project/scripts/starter_greeting.json`, and the editor could not OPEN
# it, because the script's one condition names `greeted` and the only schema
# in the tree was a dict in `main.py` that `editor/` may never import
# (law 2). `scripts_of` passed `variables=None`, the reader refused every
# condition, and the Events screen reported "No event script in this project
# yet" about a file that had just run. Two complete layers that could not see
# each other, because the file that joins them belonged to nobody.
#
# WHY THE FIRST ROW READS THE REAL PROJECT AND THE REST DO NOT
# ------------------------------------------------------------
# Every fixture in this tree passed while the seam was broken -- that is what
# made the defect invisible for a pass. So one row asks the question no
# fixture can: does `scripts_of` open what the engine reads, HERE. It asserts
# what the CODE does -- the wiring hands the library a schema, and the
# library opens every document on disk -- and names no script, no variable
# and no file, so it survives a renamed script and dies on a broken seam
# (law 4). Every TOOTH below it is on a fixture built by this file.

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
made: list[str] = []


def scene_doc(scene_id: str, variables: dict) -> dict:
    return {"format": sf.SCENE_FORMAT, "version": sf.SCENE_VERSION,
            "id": scene_id, "title": scene_id, "vars": variables}


def script_doc(script_id: str, body=(), when=()) -> dict:
    return {"format": sf.FORMAT, "version": sf.VERSION, "id": script_id,
            "loadouts": ["core"],
            "pages": [{"id": "pg", "trigger": "use", "when": list(when),
                       "body": list(body)}]}


def project_at(*, scenes=None, scripts=None) -> str:
    """A throwaway project. `scenes=None` writes no `scenes/` AT ALL.

    Keyed by FILENAME stem, and a document carries its own `id`, so the two
    can be made to disagree on purpose.
    """
    root = tempfile.mkdtemp(prefix="pyoneer_schema_")
    made.append(root)
    os.makedirs(os.path.join(root, "config"))
    os.makedirs(os.path.join(root, "data", "project"))
    with open(os.path.join(root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": []}, handle)
    with open(os.path.join(root, "data", "project", "project.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"genre": "topdown_rpg"}, handle)
    for subdir, documents in (("scenes", scenes), ("scripts", scripts)):
        if documents is None:
            continue
        target = os.path.join(root, "data", "project", subdir)
        os.makedirs(target, exist_ok=True)
        for stem, document in documents.items():
            with open(os.path.join(target, "%s.json" % stem), "w",
                      encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(document, indent=2, sort_keys=True)
                             + "\n")
    return root


def opened(root: str, **kw):
    """`scripts_of` on a project -> (library, "") or (None, the refusal)."""
    try:
        return event_script.scripts_of(Session.open(root, **kw).project), ""
    except Exception as exc:                                    # noqa: BLE001
        return None, str(exc)


def declared(lib):
    """Every name a library's schema declares, or None when it has no schema.

    Never an attribute walk straight inside an `expect` tuple: a mutation
    that puts None back in that slot must produce a red ROW, not an
    AttributeError that stops the rest of the section from running.
    """
    schema = getattr(lib, "variables", None)
    return sorted(schema.names()) if isinstance(schema, sf.VarSchema) else None


# -- the seam itself, on the real repository -------------------------------

real_dir = os.path.join(REPO, sf.SCRIPTS_DIR)
on_disk = sorted(os.path.splitext(name)[0]
                 for name in (sorted(os.listdir(real_dir))
                              if os.path.isdir(real_dir) else [])
                 if name.endswith(".json"))
real, real_refusal = opened(REPO)
expect("the editor opens every script the engine reads, in THIS project",
       (real_refusal, sorted(real.names()) if real else None),
       ("", on_disk))
expect("...because scripts_of handed the library a schema and not None",
       isinstance(getattr(real, "variables", None), sf.VarSchema), True)

# -- the wire is at the entry point, not at six surfaces -------------------

WITH_SCENE = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "coins": {"type": "int", "default": 0, "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll", when=[{"var": "coins",
                                               "at_least": 10}])})
lib, refused = opened(WITH_SCENE, genre_id="topdown_rpg")
expect("a scene's `vars` reaches the library through scripts_of alone",
       (refused, declared(lib)),
       ("", ["scene.coins"]))
expect("...so a script naming a declared variable opens",
       sorted(lib.names()) if lib else None, ["toll"])

# -- an undeclared variable: the refusal, and its ADDRESS -------------------

WRONG_NAME = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "gate_open": {"type": "bool", "default": False, "doc": "The gate."}})},
    scripts={"toll": script_doc("toll", when=[{"var": "coins", "is": 1}])})
lib, refused = opened(WRONG_NAME, genre_id="topdown_rpg")
expect("a script naming an undeclared variable is REFUSED", lib is None, True)
expect("...naming the script, the variable and the file that must declare it",
       ("toll.json" in refused, "scene.coins" in refused,
        "overworld.json" in refused), (True, True, True))
expect("...and what is declared is offered, so a typo reads as one",
       "scene.gate_open" in refused, True)

# The SAME schema has to reach the op route. `ops._declared` is a sibling of
# `_read_condition` -- a different function, in a module `script_file` cannot
# import -- and a fix that reached only conditions would leave `set` and
# `ask` refusing everything on a project that authored a scene correctly.
OP_ROUTE = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "coins": {"type": "int", "default": 0, "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll", body=[
        {"id": "n1", "do": "set", "var": "coins", "to": 5}])})
lib, refused = opened(OP_ROUTE, genre_id="topdown_rpg")
expect("the schema reaches the OP route too, not only conditions",
       (refused, sorted(lib.names()) if lib else None), ("", ["toll"]))

BAD_OP_VAR = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "coins": {"type": "int", "default": 0, "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll", body=[
        {"id": "n1", "do": "set", "var": "purse", "to": 5}])})
lib, refused = opened(BAD_OP_VAR, genre_id="topdown_rpg")
expect("...and refuses an undeclared one there, with the same address",
       (lib is None, "scene.purse" in refused, "overworld.json" in refused),
       (True, True, True))

# -- a declared variable at the wrong TYPE ---------------------------------

WRONG_TYPE = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "coins": {"type": "int", "default": 0, "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll", body=[
        {"id": "n1", "do": "set", "var": "coins", "to": "lots"}])})
lib, refused = opened(WRONG_TYPE, genre_id="topdown_rpg")
expect("a declared variable written at the wrong type is refused",
       (lib is None, "coins" in refused), (True, True))

COMPARE_TYPE = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "greeted": {"type": "bool", "default": False, "doc": "Said hello."}})},
    scripts={"toll": script_doc("toll", when=[{"var": "greeted",
                                               "at_least": 2}])})
lib, refused = opened(COMPARE_TYPE, genre_id="topdown_rpg")
expect("...and an arithmetic comparator on a bool is refused naming the type",
       (lib is None, "at_least" in refused and "bool" in refused),
       (True, True))

BAD_DEFAULT = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "coins": {"type": "int", "default": "0", "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(BAD_DEFAULT, genre_id="topdown_rpg")
expect("a DECLARATION whose default is the wrong type is refused at load",
       (lib is None, "coins" in refused), (True, True))

BAD_TYPE_NAME = project_at(
    scenes={"overworld": scene_doc("overworld", {
        "coins": {"type": "colour", "default": 0, "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(BAD_TYPE_NAME, genre_id="topdown_rpg")
expect("...and so is a type no `BehaviorParam` knows, naming the known ones",
       (lib is None, "colour" in refused), (True, True))

# -- a missing schema file is SILENT ---------------------------------------
# The neighbours decide this one: a missing `tables/` is `table_file.EMPTY`
# and a missing `scripts/` is an empty dict. Consistency with them is worth
# more than any argument for strictness -- a project that declares no
# variables and names none is not broken.

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    absent = sf.load_vars(os.path.join(REPO, "no", "such", "scenes"))
expect("a missing scenes directory reads as a schema declaring nothing",
       (isinstance(absent, sf.VarSchema), len(absent), absent.names()),
       (True, 0, []))
expect("...silently: nothing is warned, nothing is raised",
       [str(w.message) for w in caught], [])

NO_SCENES = project_at(scripts={"quiet": script_doc("quiet", body=[
    {"id": "n1", "do": "say", "text": "No variable anywhere."}])})
lib, refused = opened(NO_SCENES, genre_id="topdown_rpg")
expect("...and a project with no scenes/ at all still opens its scripts",
       (refused, sorted(lib.names()) if lib else None), ("", ["quiet"]))
schema = getattr(lib, "variables", None)
expect("...with a real empty schema on the library, not None",
       # Measured while mutation-testing this section: reading `len()` of a
       # None straight in the tuple turned a red ROW into a traceback, and
       # every row after it stopped running. A check that dies is a check
       # that stops reporting.
       (isinstance(schema, sf.VarSchema),
        len(schema) if isinstance(schema, sf.VarSchema) else None), (True, 0))

SILENT_BUT_NAMED = project_at(scripts={"toll": script_doc(
    "toll", when=[{"var": "coins", "is": 1}])})
lib, refused = opened(SILENT_BUT_NAMED, genre_id="topdown_rpg")
expect("...but silence is not permission: an undeclared variable still "
       "refuses",
       (lib is None, "scene.coins" in refused), (True, True))
expect("...and the refusal says where a declaration would have been read",
       # `PyoneerError.__str__` reprs its context, which DOUBLES every
       # backslash on Windows, so a path is matched against the unescaped
       # text rather than against a substring that only holds on posix.
       os.path.join("data", "project", "scenes")
       in refused.replace("\\\\", "\\"), True)

# -- the scene document's own vocabulary -----------------------------------
# Law 7 at the top of the file: a key with no reader is refused, not kept.
# `docs/PLAN_SCENES.md` 3.2 mints eight more keys and NONE of them is read
# here, so accepting one would be `transform=` again -- an authored field
# that looks like it works until somebody measures it.

FUTURE_KEY = project_at(
    scenes={"overworld": dict(scene_doc("overworld", {}),
                              maps=[{"map": "starter", "entry": "start"}])},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(FUTURE_KEY, genre_id="topdown_rpg")
expect("a scene key nothing reads yet is refused, naming what is read",
       (lib is None, "maps" in refused, "vars" in refused),
       (True, True, True))

MISNAMED = project_at(
    scenes={"overworld": scene_doc("somewhere_else", {})},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(MISNAMED, genre_id="topdown_rpg")
expect("a scene whose id disagrees with its filename is refused, both named",
       (lib is None, "somewhere_else" in refused,
        "overworld.json" in refused), (True, True, True))

NEWER = project_at(
    scenes={"overworld": dict(scene_doc("overworld", {}), version=2)},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(NEWER, genre_id="topdown_rpg")
expect("a NEWER scene document is refused rather than read optimistically",
       (lib is None, "version 2" in refused), (True, True))

NOT_A_SCENE = project_at(
    scenes={"overworld": dict(scene_doc("overworld", {}),
                              format="pyoneer.script")},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(NOT_A_SCENE, genre_id="topdown_rpg")
expect("...and so is a file that is not a scene document at all",
       (lib is None, sf.SCENE_FORMAT in refused), (True, True))

CLEAN = project_at(
    scenes={"overworld": scene_doc("overworld", {})},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(CLEAN, genre_id="topdown_rpg")
expect("...and the positive control: the same document with nothing wrong "
       "opens", (refused, sorted(lib.names()) if lib else None),
       ("", ["toll"]))

# -- two scenes, one store -------------------------------------------------

AGREE = project_at(
    scenes={"one": scene_doc("one", {
                "coins": {"type": "int", "default": 0, "doc": "Spendable."}}),
            "two": scene_doc("two", {
                "coins": {"type": "int", "default": 0, "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll", when=[{"var": "coins", "is": 0}])})
lib, refused = opened(AGREE, genre_id="topdown_rpg")
expect("two scenes declaring one variable identically merge to one",
       (refused, declared(lib)),
       ("", ["scene.coins"]))

DISAGREE = project_at(
    scenes={"one": scene_doc("one", {
                "coins": {"type": "int", "default": 0, "doc": "Spendable."}}),
            "two": scene_doc("two", {
                "coins": {"type": "str", "default": "", "doc": "Spendable."}})},
    scripts={"toll": script_doc("toll")})
lib, refused = opened(DISAGREE, genre_id="topdown_rpg")
expect("...and two that CONTRADICT are refused, naming both files",
       (lib is None, "one.json" in refused, "two.json" in refused),
       (True, True, True))

# --------------------------------------------------------------------------
section("9. the wire: the editor's own save writes the scripts too")
# --------------------------------------------------------------------------
# THE DEFECT THIS CLOSES WAS MEASURED BY PLAYING THE EDITOR, in four gestures:
#
#   object screen -> Script row -> New... -> id 'signpost' -> Create
#   Ctrl+S        wrote ['starter.tmx', 'project.json']
#   close         session.dirty was False, so the window took its "not dirty"
#                 branch and closed with no prompt at all
#   run the game  PyoneerAssetMissingError: event script 'signpost' not found
#
# One gesture and a Ctrl+S, and the shipped game no longer booted: the MAP
# half of a two-document transaction reached the disk and the SCRIPT half did
# not. Work lost, silently, and the corruption landed in a file that DID get
# saved.
#
# WHY NOTHING IN THIS TREE SAW IT, AND WHY THESE ROWS LOOK LIKE THEY DO.
# `ScriptLibrary.save()` had six callers and ALL SIX WERE IN `tools/` --
# section 6 above is four of them. Calling the writer proves the WRITER
# works, which was never in doubt; no number of such rows can see that
# nothing ELSE calls it. So not one row below calls `library.save()`,
# `library.dirty` or `Project.save`: they drive `Session.save()` and
# `session.dirty`, which are exactly and only what `MainWindow.save()` and
# `MainWindow.closeEvent` call. They assert the WIRE and never its address,
# so they keep passing the day it moves into `Project` itself.

WIRE_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" \
renderorder="right-down" width="2" height="2" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="2">
 <layer id="1" name="Floor" width="2" height="2">
  <data encoding="csv">
0,0,
0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" class="GamePlayer" x="16" y="16" width="16" \
height="16"/>
 </objectgroup>
</map>
"""

SIGNPOST = "signpost"
SIGN_SCOPE = Scope.of(("script", SIGNPOST))
HERO = Scope.parse("map:yard/layer:entity/object:1")


def yard(**kw) -> str:
    """A throwaway project holding one map with one object on it.

    `project_at` builds the project; this adds the map and registers it, so
    every row below runs on a fixture this file wrote (law 4). No tileset:
    the object is what carries `pyoneer_script`, and a `<tileset>` would only
    add art nobody looks at.
    """
    root = project_at(**kw)
    os.makedirs(os.path.join(root, "data", "maps"))
    with open(os.path.join(root, "data", "maps", "yard.tmx"), "wb") as handle:
        handle.write(WIRE_MAP)
    with open(os.path.join(root, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "yard", "identifier": "yard",
                             "file": "data/maps/yard.tmx"}]}, handle)
    return root


def authored(root: str):
    """The two-document transaction the object screen's `New...` sends.

    One `session.run`, exactly as the window does it: the script is created
    and the object that will run it is pointed at it in the same undoable
    step. Returns the session.
    """
    editing = Session.open(root, genre_id="topdown_rpg")
    editing.run([Command("script.create", SIGN_SCOPE,
                         {"title": "The signpost"}),
                 Command("map.object.property.set", HERO,
                         {"key": sf.SCRIPT_PROPERTY, "value": SIGNPOST})])
    return editing


def boot(root: str):
    """What the GAME does with what is on disk: (id, "") or (None, why).

    `load_scripts` and `script_of` are the engine's own two -- the second is
    THE one reader of `pyoneer_script`, the function both spawn routes call --
    so this is the boot join and not a rehearsal of it. The map is re-read
    from disk through a fresh project, because a document still open in the
    editor is not evidence about a file.
    """
    project_dir = os.path.join(root, "data", "project")
    scripts = sf.load_scripts(
        os.path.join(project_dir, "scripts"),
        variables=sf.load_vars(os.path.join(project_dir, "scenes")))
    found = Session.open(root, genre_id="topdown_rpg").project
    obj = found.map("yard").object_layer("entity").objects()[0]
    try:
        return sf.script_of(scripts, obj.properties.as_dict(),
                            "tmx object id=%d on layer 'entity'" % obj.id), ""
    except Exception as exc:                                    # noqa: BLE001
        return None, str(exc)


def basenames(paths) -> list[str]:
    return sorted(os.path.basename(p) for p in paths)


# -- the dirty half, isolated from the map so it cannot borrow its answer --

WIRED = yard()
made.append(WIRED)
wired = Session.open(WIRED, genre_id="topdown_rpg")
expect("a project with nothing authored is not dirty", wired.dirty, False)
wired.run(Command("script.create", SIGN_SCOPE, {"title": "The signpost"}))
expect("authoring a script ALONE makes the session dirty, so the close "
       "prompt fires instead of the window closing silently",
       (wired.dirty, wired.project.dirty_maps(), wired.project.dirty_tables()),
       (True, [], []))
# Measured while writing this row, which first asserted that undo CLEANS the
# session. It does not, and the three document kinds do not agree about why:
# `MapDocument.changed` re-serialises and compares bytes, so undoing a map
# edit really does clean it, while a table's `dirty` and a script's are
# sticky flags set at the mutation. A script created and undone therefore
# leaves the session dirty until a save -- which then writes nothing for it
# and clears. That is the conservative answer and it matches the neighbour a
# script most resembles; the row pins which model is in force rather than
# asserting the one it would prefer, because an undocumented disagreement
# between two kinds is how the next pass loses an afternoon.
expect("...undo does not clean it: a script's dirtiness is a FLAG set at "
       "the mutation, like a table's, not the byte comparison a map's is",
       (wired.undo() is not None, wired.dirty), (True, True))

# -- the same transaction, undone, leaves the map byte-identical -----------
# Not a detour from the wire: `New...` writes `pyoneer_script` onto an object
# the file wrote SELF-CLOSING, and the inverse -- `map.object.property.remove`
# -- empties the `<properties>` container that write created. Measured before
# this row existed: the undo left `<object ...>\n   </object>` where the file
# said `<object .../>`, two lines of diff on a declare-then-undo that must
# leave none. The sibling verb one screenful away, `map.object.action.unset`,
# had carried the guard for that since the day it was written, with the
# reason in a comment; the property route grew without it. Sighting again.

EXACT = yard()
made.append(EXACT)
exact = Session.open(EXACT, genre_id="topdown_rpg")
with open(os.path.join(EXACT, "data", "maps", "yard.tmx"), "rb") as handle:
    on_disk = handle.read()
expect("the fixture's object is written self-closing, so the row has "
       "something to get wrong", b'height="16"/>' in on_disk, True)
exact.run([Command("script.create", SIGN_SCOPE, {"title": "The signpost"}),
           Command("map.object.property.set", HERO,
                   {"key": sf.SCRIPT_PROPERTY, "value": SIGNPOST})])
expect("...the transaction really does change the map",
       exact.project.map("yard").to_bytes() != on_disk, True)
exact.undo()
expect("...and one undo puts the map back BYTE for byte, self-closing "
       "`<object/>` and all",
       exact.project.map("yard").to_bytes(), on_disk)
expect("...so the map is not dirty any more either, which is the other half "
       "of the same fact: `MapDocument.changed` compares the bytes",
       exact.project.dirty_maps(), [])


# -- the save half, and no document kind left behind -----------------------

wired.run([Command("script.create", SIGN_SCOPE, {"title": "The signpost"}),
           Command("map.object.property.set", HERO,
                   {"key": sf.SCRIPT_PROPERTY, "value": SIGNPOST})])
script_path = os.path.join(WIRED, "data", "project", "scripts",
                           "%s.json" % SIGNPOST)
expect("nothing is on disk before the save", os.path.isfile(script_path),
       False)
written = wired.save()
expect("ONE save writes the map, the script and project.json -- both halves "
       "of the transaction reach the disk together",
       basenames(written), ["project.json", "signpost.json", "yard.tmx"])
expect("...and the session is clean afterwards, so the window closes "
       "without asking", (wired.dirty, os.path.isfile(script_path)),
       (False, True))
expect("a second save writes no script, because nothing is dirty",
       [p for p in wired.save() if os.path.basename(p).startswith(SIGNPOST)],
       [])

# -- the acceptance test: a fresh boot finds what the map names ------------

expect("and the whole point: a fresh boot of the game finds the script the "
       "map references", boot(WIRED), (SIGNPOST, ""))

# -- the negative half: the exact defect, reproduced ------------------------
# The map saved and the script not is not a hypothetical -- it is what the
# editor did for a whole pass, so it is arranged here by hand: the map
# document is written on its own, which is all `Project.save` did while
# nothing wrote the library.

LOST = yard()
made.append(LOST)
lost = authored(LOST)
lost.project.map("yard").save()
lost_id, lost_refusal = boot(LOST)
expect("with the map saved and the script NOT, the boot REFUSES, naming the "
       "script it cannot find",
       (lost_id, SIGNPOST in lost_refusal, "event script" in lost_refusal),
       (None, True, True))
lost.save()
expect("...and the positive control: the same project, saved through the "
       "editor, boots", boot(LOST), (SIGNPOST, ""))

# -- delete reaches the disk through the same save -------------------------

lost_path = os.path.join(LOST, "data", "project", "scripts",
                         "%s.json" % SIGNPOST)
lost.run(Command("script.delete", SIGN_SCOPE, {"confirm": True}))
expect("a delete leaves the file alone and makes the session dirty",
       (os.path.isfile(lost_path), lost.dirty), (True, True))
lost.save()
expect("...and the editor's own save is what removes it",
       (os.path.isfile(lost_path), lost.dirty), (False, False))
lost.undo()
lost.save()
expect("...and undo plus one save puts the document back on disk",
       (os.path.isfile(lost_path), lost.dirty), (True, False))

# -- the listing and the flag are ONE sentence -----------------------------
# The close prompt asks `session.dirty` and then lists what is unsaved, and
# for one pass those were two different facts: `dirty` had learned about
# event scripts and the listing had not, so a script-only session was told
# "0 documents have changes that are not on disk:" over an empty list. Work
# survived -- Yes saved the script too -- but the sentence the author reads
# before deciding was false, which is the worse half of the pair to lose.
#
# `Project.dirty` is composed from `dirty_maps() + dirty_tables() +
# dirty_scripts()` now, so the two cannot come apart. These rows drive the
# three listings and the flag and never name where the code lives -- the
# same rows passed while the wire was a `__class__` swap in
# `event_script.py`, which is how that move was proved safe on the way to
# its permanent home in `editor/core/project.py`.

LISTED = yard()
made.append(LISTED)
listed = Session.open(LISTED, genre_id="topdown_rpg")
expect("a project with nothing authored lists no script and is not dirty",
       (listed.project.dirty_scripts(), listed.dirty), ([], False))
listed.run(Command("script.create", SIGN_SCOPE, {"title": "The signpost"}))
expect("an authored script is NAMED in the listing the close prompt shows",
       (listed.project.dirty_scripts(), listed.dirty), ([SIGNPOST], True))
expect("...and `dirty` is exactly those three listings, so the prompt and "
       "the flag that raises it cannot disagree",
       (listed.dirty, bool(listed.project.dirty_maps()
                           + listed.project.dirty_tables()
                           + listed.project.dirty_scripts())), (True, True))
listed.save()
expect("...and one save empties both halves of that sentence",
       (listed.project.dirty_scripts(), listed.dirty), ([], False))
listed.run(Command("script.delete", SIGN_SCOPE, {"confirm": True}))
expect("A DELETION IS LISTED TOO, and it is the case the library's own "
       "`dirty_scripts()` cannot see: the document is gone from memory so "
       "nothing is dirty, the `.json` is still on disk, and the session is "
       "still not saved",
       (listed.project.dirty_scripts(), listed.dirty), ([SIGNPOST], True))

# -- the project is still a plain project ----------------------------------
# The anti-regression for the road not taken. The wire was a `Project`
# subclass swapped in at `scripts_of` while `editor/core/project.py` belonged
# to another track; both halves now live in `Project` itself, so an editor
# project is a plain `Project` whether it has scripts or not, and a project
# that never asks for a library is left exactly as it was found.

UNASKED = project_at()
made.append(UNASKED)
unasked = Session.open(UNASKED, genre_id="topdown_rpg")
expect("a project with scripts and a project without are both plain "
       "`Project`s -- no subclass, no `__class__` swap",
       (isinstance(wired.project, Project), type(wired.project) is Project,
        type(unasked.project) is Project), (True, True, True))
expect("...and a project that never asks for a library counts none and "
       "writes none, so the wire costs a scriptless project nothing",
       (unasked.project.dirty_scripts(),
        [os.path.basename(q) for q in unasked.save()
         if ("scripts" + os.sep) in q]), ([], []))


for root in made:
    shutil.rmtree(root, ignore_errors=True)

shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
