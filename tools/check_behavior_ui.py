"""The editor's behavior surface: the checklist, the refusals, the undo.

`pyoneer_behaviors` is the declaration site of the composition model, so the
editor offers a typed checklist for it rather than a text box. This file
covers that panel, and is written against the two ways it could be wrong
without anyone noticing:

  * IT COULD KEEP ITS OWN LIST. A hand-kept checklist agrees with the engine
    on the day it is typed and silently disagrees afterwards -- the exact
    reason `docs/BEHAVIORS.md` is generated. So the assertions here drive
    `describe_behaviors` against a SUBSTITUTED registry as well as the real
    one: a token that exists only in the fixture must appear, and one the
    fixture drops must vanish.
  * IT COULD BLESS A LIST THE ENGINE REJECTS. The four refusal rules are
    split across two files -- `validate_list` knows unknown, duplicate and
    declared-conflict; `EntityBehaviors.attach` knows those three PLUS "same
    order and intersecting writes", which needs the spec pair and exists
    nowhere else. A panel calling only the first would authorise a list that
    raises at map load. The fixture pair in section 3 is ACCEPTED by
    `validate_list` and REFUSED by `attach`, and both halves of that are
    asserted.

  * IT COULD KEEP ITS OWN CATEGORIES. Section 15 covers the grouping and the
    run sequence, and it is written against the same failure one level up: a
    token-to-category mapping agrees with the tree on the day it is typed. So
    the category assertions register a behavior whose class claims a module
    that does not exist and require it to get its own heading in the panel
    AND in `BEHAVIORS.md` with nothing edited to let it. A check that listed
    today's four categories would pass just as happily for a hand-kept table.

Every gate is asserted in both directions, because testing one half of an
invariant is the dominant failure this repo has found in its own checks: a
conflict is refused AND a compatible token is accepted; an out-of-genre token
is named AND still offered; the parameters of a ticked behavior are offered
AND withdrawn when it is unticked; a tie in the run order is NAMED as a tie
AND an untied sequence says nothing about one.

Against its OWN fixture, never `data/maps/starter.tmx` (law 4).

Skips cleanly when PySide6 is absent.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import functools
import importlib.util
import json
import os
import shutil
import sys
import tempfile

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                           # noqa: E402
from PySide6.QtWidgets import (                                         # noqa: E402
    QApplication,
    QCheckBox,
    QLabel,
    QMainWindow,
)

from editor.core.behavior_view import (                                 # noqa: E402
    describe_behaviors,
    is_vocabulary,
    read_tokens,
    refusals,
    strip_vocabulary,
    unknown_axes,
)
from editor.core.commands import Command                                # noqa: E402
from editor.core.inspect import describe                                # noqa: E402
from editor.core.scope import Scope                                     # noqa: E402
from editor.core.session import Session                                 # noqa: E402
from editor.ui.behavior_panel import (CHECKLIST, IS_WIRED,              # noqa: E402
                                      RUN_SECTION, STRAY_SECTION,
                                      BehaviorDock, category_title,
                                      group_by_category, ordinal)
from editor.ui.fields import InspectionView                             # noqa: E402
from editor.ui.inspector import InspectorDock                           # noqa: E402

from scripts.core.errors import PyoneerConfigError                      # noqa: E402
from scripts.game.behavior.base import (BEHAVIORS, ORDER_RULE,          # noqa: E402
                                        PARAM_PREFIX, BehaviorSpec,
                                        EntityBehavior, EntityBehaviors,
                                        category_label)
from scripts.game.behavior.registry import (BEHAVIOR_REGISTRY,          # noqa: E402
                                            categories, describe_all,
                                            order_steps, run_order, step_of,
                                            validate_list)
from scripts.game.behavior.state import BodyState                       # noqa: E402

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<58} got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------
# The fixture
#
# Six objects, each one a shape the panel has to survive:
#
#   1 hero    a clean, legal list, a consumed parameter, an ORPHAN parameter
#             and an ordinary non-vocabulary property
#   2 bare    NO <properties> element, so the first-ever-property path runs
#   3 dup     a duplicated token: refused by validate_list
#   4 typo    a token that does not resolve
#   5 sideon  a behavior declared for the other genre, carrying a parameter
#             whose authored value the engine REFUSES to coerce
#   6 acts    two behaviors declaring the SAME parameter keys, which is one
#             tmx property feeding both and is said nowhere else
# --------------------------------------------------------------------------

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.2" tiledversion="1.3.1" orientation="orthogonal" \
renderorder="right-down" compressionlevel="-1" width="4" height="4" \
tilewidth="16" tileheight="16" infinite="0" nextlayerid="4" nextobjectid="7">
 <tileset firstgid="1" name="Art" tilewidth="16" tileheight="16" \
tilecount="256" columns="16">
  <image source="art.png" width="256" height="256"/>
 </tileset>
 <layer id="1" name="Floor" width="4" height="4">
  <data encoding="csv">
0,0,0,0,
0,0,0,0,
0,0,0,0,
0,0,0,0
</data>
 </layer>
 <objectgroup id="2" name="entity">
  <object id="1" name="hero" type="GamePlayer" x="0" y="0" width="16" \
height="16">
   <properties>
    <property name="hp" type="int" value="5"/>
    <property name="pyoneer_behaviors" value="player_input,topdown_move"/>
    <property name="pyoneer_param_nonsense" value="x"/>
    <property name="pyoneer_param_walk_format" value="run_{}"/>
   </properties>
  </object>
  <object id="2" name="bare" type="GamePlayer" x="32" y="0" width="16" \
height="16"/>
  <object id="3" name="dup" type="GamePlayer" x="48" y="0" width="16" \
height="16">
   <properties>
    <property name="pyoneer_behaviors" \
value="topdown_move,topdown_move,animation_drive"/>
   </properties>
  </object>
  <object id="4" name="typo" type="GamePlayer" x="0" y="32" width="16" \
height="16">
   <properties>
    <property name="pyoneer_behaviors" value="topdown_mvoe,animation_drive"/>
   </properties>
  </object>
  <object id="5" name="sideon" type="GamePlayer" x="32" y="32" width="16" \
height="16">
   <properties>
    <property name="pyoneer_behaviors" value="player_input,platformer_move"/>
    <property name="pyoneer_param_gravity" value="9o"/>
   </properties>
  </object>
  <object id="6" name="acts" type="GamePlayer" x="48" y="32" width="16" \
height="16">
   <properties>
    <property name="pyoneer_behaviors" value="attack_action,interact_action"/>
   </properties>
  </object>
 </objectgroup>
</map>
"""


class Harness(QMainWindow):
    """The one thing a `ScopedDock` asks of its window: `run`.

    Deliberately not `EditorWindow` -- a failure here has to be a failure in
    this panel rather than in whatever the toolbar looks like today, and
    `check_editor_ui.py` already drives the real window, which now mounts
    this dock.
    """

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.rejected: list[str] = []

    def run(self, commands, *, label=None, source="editor") -> bool:
        try:
            self.session.run(commands, label=label, source=source)
        except Exception as exc:                                # noqa: BLE001
            self.rejected.append(str(exc))
            return False
        return True

    def refresh_manifest(self) -> None:
        """`ScopedDock` wires its prompt strip to this."""


class Stub(EntityBehavior):
    """A factory for fixture specs. Nothing here ever constructs one."""

    def update(self, entity, event) -> None:                    # pragma: no cover
        """Never called."""


def fields_of(inspection) -> dict:
    return {f.key: f for section in inspection.sections for f in section.fields}


def section_of(inspection, title):
    for section in inspection.sections:
        if section.title == title:
            return section
    return None


def declared_axes(*tokens) -> list[str]:
    """The axes those tokens declare, read off the registry rather than typed."""
    return sorted({w[len("state."):] for token in tokens
                   for w in BEHAVIOR_REGISTRY[token].writes
                   if w.startswith("state.")})


class Inert(EntityBehavior):
    """A stand-in carrying a REAL spec, so attaching it runs the engine's rules."""

    def update(self, entity, event) -> None:                    # pragma: no cover
        """Never called: nothing here drives a frame."""


class StealthStub(EntityBehavior):
    """A factory pretending to be declared in a module this repo has not got.

    `__module__` is the whole experiment. `BehaviorSpec.category` derives
    from it and from nothing else, and no file anywhere maps a token to a
    category -- so a heading that appears for this class appeared by
    derivation, which is the one thing a hand-kept mapping could never do.
    """

    __module__ = "scripts.game.behavior.stealth"

    def update(self, entity, event) -> None:                    # pragma: no cover
        """Never called."""


class MovementStub(EntityBehavior):
    """The other half: declared in a module that already has a category."""

    __module__ = "scripts.game.behavior.movement"

    def update(self, entity, event) -> None:                    # pragma: no cover
        """Never called."""


class NamelessStub(EntityBehavior):
    """Declared in a module whose name shows nothing, so it has NO category."""

    __module__ = "_"

    def update(self, entity, event) -> None:                    # pragma: no cover
        """Never called."""


class Anonymous:
    """A callable object whose class hides its module entirely.

    The other branch of the same refusal: `functools.partial` and every
    ordinary instance still answer `__module__` through their type, so this
    is what an actually module-less factory has to look like.
    """

    __module__ = ""

    def __call__(self, *a, **k):                                # pragma: no cover
        """Never called."""


def engine_order(tokens, table=None) -> tuple:
    """What `EntityBehaviors` REALLY runs, obtained by attaching behaviors.

    The panel draws its sequence from `run_order`, which applies the engine's
    sort key to a list of TOKENS rather than to attached instances. That is a
    restatement, and a restatement is a second home for a rule, so the
    assertions compare it against this -- the real class, really attached.
    """
    composed = EntityBehaviors(type("entity", (object,), {})())
    for token in tokens:
        behavior = Inert()
        behavior.spec = (BEHAVIOR_REGISTRY if table is None else table)[token]
        composed.attach(behavior)
    return composed.names


def refusal_of(call) -> str:
    """The message `call` raises, or "" when it raises nothing.

    Both are useful: a refusal check needs the text, and the other half of
    every refusal needs the empty string.
    """
    try:
        call()
    except PyoneerConfigError as error:
        return str(error)
    return ""


workspace = tempfile.mkdtemp(prefix="pyoneer_behavior_ui_")
application = QApplication.instance() or QApplication([])

try:
    os.makedirs(os.path.join(workspace, "config"))
    os.makedirs(os.path.join(workspace, "data", "maps"))
    with open(os.path.join(workspace, "data", "maps", "fixture.tmx"), "w",
              encoding="utf-8", newline="") as handle:
        handle.write(FIXTURE)
    with open(os.path.join(workspace, "config", "maps.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"data": [{"name": "fixture", "identifier": "fixture",
                             "file": "data/maps/fixture.tmx"}]}, handle)

    session = Session.open(workspace, genre_id="topdown_rpg")
    document = session.project.map("fixture")
    ORIGINAL = document.to_bytes()

    def scope_for(object_id: int) -> Scope:
        return Scope.of(("map", "fixture"), ("layer", "entity"),
                        ("object", str(object_id)))

    HERO, BARE, DUP, TYPO, SIDEON, ACTS = (scope_for(i) for i in range(1, 7))

    def props(object_id: int) -> dict:
        return (document.object_layer("entity").find(object_id)
                .properties.as_dict())

    def look(scope, **kwargs):
        return describe_behaviors(session, scope, **kwargs)

    # ------------------------------------------------------------------
    print("1. the checklist IS the registry, not a list kept in the editor")
    # ------------------------------------------------------------------
    # First, before anything indexes a section: `describe_behaviors` is
    # contractually incapable of raising, so an internal failure arrives as an
    # `error` on the Inspection. Asserting that here means a regression names
    # itself instead of surfacing as an AttributeError four assertions later.
    expect("every fixture object describes without an internal error",
           [look(s).error for s in (HERO, BARE, DUP, TYPO, SIDEON, ACTS)],
           [""] * 6)

    hero = look(HERO)
    checklist = section_of(hero, "Behaviors")
    offered = [f.key for f in checklist.fields if f.key in BEHAVIOR_REGISTRY]
    expect("every registered token is offered",
           sorted(offered), sorted(BEHAVIOR_REGISTRY))
    expect("in the order they run, low order first",
           offered, [s.name for s in sorted(BEHAVIOR_REGISTRY.values(),
                                            key=lambda s: (s.order, s.name))])
    expect("each row is a tick box",
           {f.kind for f in checklist.fields}, {"bool"})
    expect("ticked exactly for what the object declares",
           sorted(f.key for f in checklist.fields if f.value),
           ["player_input", "topdown_move"])
    expect("the label carries the declared order",
           "order 20" in fields_of(hero)["topdown_move"].label, True)
    expect("and the tooltip carries what it writes",
           "writes transform.position" in fields_of(hero)["topdown_move"].doc,
           True)

    # The half that proves it is READ rather than listed: a registry this file
    # invents must change what the panel offers, in both directions.
    substituted = dict(BEHAVIOR_REGISTRY)
    substituted["invented_thing"] = BehaviorSpec(
        name="invented_thing", summary="fixture only", factory=Stub, order=42)
    del substituted["action_relay"]
    swapped = [f.key for f in
               section_of(look(HERO, registry=substituted), "Behaviors").fields]
    expect("a token only the substituted registry has is offered",
           "invented_thing" in swapped, True)
    expect("and one it drops is not", "action_relay" in swapped, False)
    expect("its declared ORDER places it, not its name",
           swapped.index("invented_thing"),
           sorted((s.order, s.name) for s in substituted.values())
           .index((42, "invented_thing")))

    # ------------------------------------------------------------------
    print()
    print("2. a refusal is the ENGINE's refusal, and it is at authoring time")
    # ------------------------------------------------------------------
    platformer = fields_of(hero)["platformer_move"]
    expect("ticking a conflicting behavior is refused",
           bool(platformer.blocked_reason), True)
    expect("the refusal names BOTH sides",
           all(word in platformer.blocked_reason
               for word in ("topdown_move", "platformer_move", "conflict")),
           True)
    expect("so the row cannot emit anything", platformer.editable, False)

    # The other half. Without it, "every row is blocked" would pass above.
    animation = fields_of(hero)["animation_drive"]
    expect("a compatible behavior is NOT refused",
           (animation.blocked_reason, animation.editable), ("", True))
    expect("and ticking it emits exactly one command",
           animation.emit(True),
           Command("map.object.property.set", HERO,
                   {"key": BEHAVIORS,
                    "value": "player_input,topdown_move,animation_drive"}))
    # `attack_action` sorts BEFORE both existing tokens alphabetically and
    # runs BETWEEN them by order, so an appended list proves the panel neither
    # sorts nor re-orders -- run order is `spec.order`'s business, and a panel
    # that rewrote the authored order would make every tick a whole-line diff.
    expect("a new token is appended, not sorted in",
           fields_of(hero)["attack_action"].emit(True).args["value"],
           "player_input,topdown_move,attack_action")
    expect("unticking one drops just that token",
           fields_of(hero)["topdown_move"].emit(False),
           Command("map.object.property.set", HERO,
                   {"key": BEHAVIORS, "value": "player_input"}))
    expect("re-ticking what is already ticked emits nothing",
           fields_of(hero)["topdown_move"].emit(True), None)

    # ------------------------------------------------------------------
    print()
    print("3. the refusal validate_list CANNOT see, and the ones it can")
    # ------------------------------------------------------------------
    # Two specs at one order whose writes intersect and which declare NO
    # conflict. `validate_list` accepts the pair; `EntityBehaviors.attach`
    # refuses it. If `refusals()` ever stops driving the second, this is the
    # assertion that dies -- and the whole "call the engine, never re-state
    # it" argument rests on it.
    clash = dict(BEHAVIOR_REGISTRY)
    clash["a_move"] = BehaviorSpec(name="a_move", summary="", factory=Stub,
                                   order=20, writes=("transform.position",))
    clash["b_move"] = BehaviorSpec(name="b_move", summary="", factory=Stub,
                                   order=20, writes=("transform.position",
                                                     "state.phase"))
    clash["c_move"] = BehaviorSpec(name="c_move", summary="", factory=Stub,
                                   order=21, writes=("transform.position",))
    clash["d_side"] = BehaviorSpec(name="d_side", summary="", factory=Stub,
                                   order=20, writes=("state.facing",))

    expect("validate_list ACCEPTS the same-order intersecting pair",
           validate_list(("a_move", "b_move"), clash), ("a_move", "b_move"))
    refused = refusals(("a_move", "b_move"), clash)
    expect("and the panel refuses it anyway", len(refused), 1)
    expect("naming both behaviors, the order and the shared write",
           all(word in "".join(refused) for word in
               ("a_move", "b_move", "order=20", "transform.position")), True)
    expect("the same pair at DIFFERENT orders is accepted",
           refusals(("a_move", "c_move"), clash), ())
    expect("and one order with DISJOINT writes is accepted",
           refusals(("a_move", "d_side"), clash), ())
    expect("a duplicate is refused, naming the token",
           "appears twice" in refusals(("topdown_move", "topdown_move"))[0],
           True)
    unknown = refusals(("topdown_mvoe",))
    expect("an unknown token is refused", len(unknown), 1)
    expect("and the message lists what the registry does have",
           all(name in unknown[0] for name in BEHAVIOR_REGISTRY), True)
    expect("a legal list is refused for nothing",
           refusals(("player_input", "topdown_move", "animation_drive")), ())
    expect("three behaviors at one order with disjoint writes compose",
           refusals(("attack_action", "interact_action", "pause_action")), ())

    # ------------------------------------------------------------------
    print()
    print("4. an already-refused list stays repairable")
    # ------------------------------------------------------------------
    for name, scope, phrase in (("a duplicate", DUP, "appears twice"),
                                ("an unknown token", TYPO, "not found")):
        found = look(scope)
        problems = section_of(found, "Refused at load")
        expect(f"{name} is reported before anything else",
               (found.sections[0].title if found.sections else "<none>",
                problems is not None and phrase in problems.note),
               ("Refused at load", True))
        # Computed from the candidate alone, every row here would be blocked
        # and the object could not be repaired from the panel at all --
        # unticking any one token leaves the other problem standing.
        expect(f"and while it stands every row stays editable ({name})",
               [f.key for f in section_of(found, "Behaviors").fields
                if f.blocked_reason], [])

    expect("unticking a doubled token removes both copies",
           fields_of(look(DUP))["topdown_move"].emit(False),
           Command("map.object.property.set", DUP,
                   {"key": BEHAVIORS, "value": "animation_drive"}))
    typo_fields = fields_of(look(TYPO))
    expect("the unresolvable token is shown ticked, never dropped",
           ("topdown_mvoe" in typo_fields, typo_fields["topdown_mvoe"].value),
           (True, True))
    expect("and unticking it is what repairs the object",
           typo_fields["topdown_mvoe"].emit(False),
           Command("map.object.property.set", TYPO,
                   {"key": BEHAVIORS, "value": "animation_drive"}))
    expect("a clean object has no refusals section",
           section_of(hero, "Refused at load"), None)

    # ------------------------------------------------------------------
    print()
    print("5. genre is advice and is named; only the engine refuses")
    # ------------------------------------------------------------------
    # Nothing in scripts/ reads `spec.genres` -- `describe_all` prints it and
    # no loader gates on it. Blocking on it would be the editor inventing a
    # refusal the engine does not have.
    bare_fields = fields_of(look(BARE))
    off_genre = bare_fields["platformer_move"]
    expect("an out-of-genre behavior is offered on an empty list",
           (off_genre.blocked_reason, off_genre.editable), ("", True))
    expect("the label says which genre declared it",
           "genre platformer" in off_genre.label, True)
    expect("the tooltip says why that is not a refusal",
           "NOTHING IN THE ENGINE READS IT" in off_genre.doc, True)
    expect("while a real refusal DOES block it (the contrast)",
           bool(fields_of(hero)["platformer_move"].blocked_reason), True)
    expect("a token this project's genre declares carries no such marker",
           "genre" in bare_fields["topdown_move"].label, False)
    # Derived, never pinned. A behavior's status is another pass's business,
    # and a check naming today's answer would have to be edited by whoever
    # changed it -- which is how a check starts being read as an obstacle. The
    # RULE is that a non-live status is on the row and a live one is not.
    not_live = sorted(s.name for s in BEHAVIOR_REGISTRY.values()
                      if s.status != "live")
    expect("every non-live behavior carries its status on the row",
           [bare_fields[name].label.endswith(BEHAVIOR_REGISTRY[name].status)
            for name in not_live], [True] * len(not_live))
    expect("and a live one carries no status marker",
           any(word in bare_fields["topdown_move"].label
               for word in ("live", "needs-host", "authoring-only")), False)

    # ------------------------------------------------------------------
    print()
    print("6. parameters follow the ticked list, typed and provenanced")
    # ------------------------------------------------------------------
    def offered_params(scope, **kwargs):
        return sorted(f.key for f in section_of(look(scope, **kwargs),
                                                "Parameters").fields
                      if not f.key.startswith(PARAM_PREFIX))

    expect("exactly the union over the ticked behaviors",
           offered_params(HERO),
           sorted(BEHAVIOR_REGISTRY["player_input"].param_keys))
    expect("topdown_move declares none, so it contributes none",
           BEHAVIOR_REGISTRY["topdown_move"].param_keys, ())

    session.run(fields_of(look(HERO))["animation_drive"].emit(True))
    expect("ticking a behavior offers its parameters",
           sorted(set(offered_params(HERO))
                  - set(BEHAVIOR_REGISTRY["player_input"].param_keys)),
           sorted(BEHAVIOR_REGISTRY["animation_drive"].param_keys))
    session.undo()
    expect("and unticking it withdraws them again",
           offered_params(HERO),
           sorted(BEHAVIOR_REGISTRY["player_input"].param_keys))

    platformer_spec = BEHAVIOR_REGISTRY["platformer_move"]
    gravity = platformer_spec.param("gravity")
    jump = platformer_spec.param("jump_velocity")
    sideon = look(SIDEON)
    sideon_fields = fields_of(sideon)
    expect("a parameter's editor comes from its declared type",
           sideon_fields["gravity"].kind, gravity.type)
    expect("its provenance is on the row",
           all(word in sideon_fields["gravity"].doc
               for word in ("source actors", "platformer_move",
                            gravity.property_name)), True)
    expect("the actors rung is stated where it bites, and stated as LIVE",
           ("the engine reads that row" in sideon_fields["gravity"].doc
            and "nothing in scripts/ reads data/project/"
            not in sideon_fields["gravity"].doc), True)
    expect("an undeclared parameter is marked as showing the default",
           "(default)" in sideon_fields["jump_velocity"].label, True)
    expect("and offers exactly that default",
           sideon_fields["jump_velocity"].value, jump.default)
    expect("a declared one is not marked",
           "(default)" in sideon_fields["gravity"].label, False)
    expect("only a declared one can be removed",
           (sideon_fields["gravity"].removable,
            sideon_fields["jump_velocity"].removable), (True, False))

    acts = look(ACTS)
    shared_note = section_of(acts, "Parameters").note
    expect("one property shared by two ticked behaviors is named",
           "Shared by more than one ticked behavior" in shared_note, True)
    expect("listing the keys that collide",
           all(key in shared_note.split("feeds them all:")[-1]
               for key in ("verb", "cooldown_ms", "payload")), True)
    expect("and the row says which behaviors read it",
           all(name in fields_of(acts)["verb"].doc
               for name in ("attack_action", "interact_action")), True)
    expect("while a list with no collision says nothing about sharing",
           "Shared by more than one ticked behavior"
           in section_of(hero, "Parameters").note, False)

    # ------------------------------------------------------------------
    print()
    print("7. a value the engine refuses is repairable, not merely red")
    # ------------------------------------------------------------------
    # `BehaviorParam.coerce` RAISES where `Capability.coerce` falls back, so
    # the panel cannot show "what the reader will make of it" the way the
    # layer inspector does -- there is nothing it will make of it.
    expect("the file's bad value is named on the row",
           "THE FILE SAYS SOMETHING THE ENGINE REFUSES"
           in sideon_fields["gravity"].doc, True)
    expect("and repeated in the refusals section",
           "9o" in getattr(section_of(sideon, "Refused at load"), "note", ""),
           True)
    expect("the editor still offers a legal value to type over it",
           sideon_fields["gravity"].value, gravity.default)
    expect("and the row can be emptied",
           sideon_fields["gravity"].remove(None),
           Command("map.object.property.remove", SIDEON,
                   {"key": gravity.property_name}))

    reported: list[str] = []
    checked = fields_of(look(SIDEON, on_error=reported.append))
    good = checked["gravity"].emit(400)
    expect("a legal edit emits a set with the COERCED value",
           good, Command("map.object.property.set", SIDEON,
                         {"key": gravity.property_name, "value": 400.0}))
    expect("an int widens to the declared float",
           type(good.args["value"]), float)
    expect("and nothing was reported", reported, [])
    expect("a wrong type emits nothing", checked["gravity"].emit("9o"), None)
    expect("and says why", len(reported), 1)
    expect("naming the property and the type it wanted",
           all(word in "".join(reported)
               for word in (gravity.property_name, "float")), True)
    # In Python True IS an int, so without `coerce`'s guard a boolean handed
    # to an int parameter would resolve to 1 and nothing would complain.
    reported.clear()
    cooldown = fields_of(look(ACTS, on_error=reported.append))["cooldown_ms"]
    expect("a boolean handed to an int parameter emits nothing",
           cooldown.emit(True), None)
    expect("and says that True is an int",
           "True is an int" in "".join(reported), True)
    expect("while a real int is accepted",
           cooldown.emit(400).args["value"], 400)

    # ------------------------------------------------------------------
    print()
    print("8. a parameter nothing consumes is visible, not swallowed")
    # ------------------------------------------------------------------
    orphan = PARAM_PREFIX + "nonsense"
    hero_param_keys = [f.key for f in section_of(hero, "Parameters").fields]
    expect("an orphan pyoneer_param_ property is shown",
           orphan in hero_param_keys, True)
    expect("named as consumed by nothing",
           "consumed by nothing" in fields_of(hero)[orphan].label, True)
    expect("and removable",
           fields_of(hero)[orphan].remove(None),
           Command("map.object.property.remove", HERO, {"key": orphan}))
    expect("the section says the engine warns and ignores them",
           "authored content that did nothing"
           in section_of(hero, "Parameters").note, True)
    # The other half, and the one with teeth: `pyoneer_param_walk_format` is
    # an orphan here ONLY because `animation_drive` is unticked. Ticking the
    # behavior that declares it must turn the same property into a typed,
    # consumed row, and unticking must turn it back.
    walk = PARAM_PREFIX + "walk_format"
    expect("an unticked behavior's parameter is an orphan too",
           walk in hero_param_keys, True)
    session.run(fields_of(look(HERO))["animation_drive"].emit(True))
    ticked_keys = [f.key for f in section_of(look(HERO), "Parameters").fields]
    expect("ticking its behavior stops it being one",
           (walk in ticked_keys, "walk_format" in ticked_keys), (False, True))
    expect("and it is typed, valued and removable now",
           (fields_of(look(HERO))["walk_format"].kind,
            fields_of(look(HERO))["walk_format"].value,
            fields_of(look(HERO))["walk_format"].removable),
           ("str", "run_{}", True))
    session.undo()
    expect("unticking makes it an orphan again",
           walk in [f.key for f in
                    section_of(look(HERO), "Parameters").fields], True)
    expect("an object with no stray parameters is not warned",
           "authored content that did nothing"
           in section_of(sideon, "Parameters").note, False)

    # ------------------------------------------------------------------
    print()
    print("9. the state axes the list writes, and who writes them")
    # ------------------------------------------------------------------
    axes = section_of(hero, "State axes")
    written = [f.key for f in axes.fields]
    expect("the rows are exactly the axes the ticked specs declare",
           sorted(written), declared_axes("player_input", "topdown_move"))
    expect("each names its writer and that writer's order",
           fields_of(hero)["phase"].value, "topdown_move (order 20)")
    expect("an axis nothing in the list writes is not a row",
           "support" in written, False)
    # Derived from `BodyState` itself, so the day an axis is added or dropped
    # this keeps meaning the same thing: everything not written is NAMED, so
    # the panel never silently omits part of the vocabulary.
    silent = [a for a in BodyState().axes if a not in written]
    unwritten = axes.note.split("Nothing in this list writes:")[-1]
    expect("and every unwritten axis is named in the note",
           [a for a in silent if a in unwritten], silent)
    expect("a side-on list DOES write support",
           "support" in [f.key for f in
                         section_of(sideon, "State axes").fields], True)
    expect("an object composing nothing writes no axis",
           [f.key for f in section_of(look(BARE), "State axes").fields], [])
    expect("the note explains what a same-order collision means",
           "SAME order" in axes.note, True)

    # Both halves of "the editor and BodyState agree on the axis vocabulary".
    expect("every state.<axis> the real registry declares is a real axis",
           unknown_axes(), ())
    strayed = dict(BEHAVIOR_REGISTRY)
    strayed["typo_writer"] = BehaviorSpec(name="typo_writer", summary="",
                                          factory=Stub, order=60,
                                          writes=("state.movnig",))
    expect("a misspelled one is reported",
           unknown_axes(strayed), (("typo_writer", "state.movnig"),))
    session.run(Command("map.object.property.set", DUP,
                        {"key": BEHAVIORS, "value": "typo_writer"}))
    strayed_axes = section_of(look(DUP, registry=strayed), "State axes")
    expect("and it never becomes an axis row",
           [f.key for f in strayed_axes.fields], [])
    expect("it is called out in the note instead",
           "DECLARED AND NOT AN AXIS: movnig" in strayed_axes.note, True)
    session.undo()

    # ------------------------------------------------------------------
    print()
    print("10. every edit is a command with an exact inverse")
    # ------------------------------------------------------------------
    before = props(1)[BEHAVIORS]
    session.run(fields_of(look(HERO))["animation_drive"].emit(True))
    expect("ticking landed in the file",
           props(1)[BEHAVIORS], "player_input,topdown_move,animation_drive")
    expect("and the bytes really moved", document.to_bytes() != ORIGINAL, True)
    session.undo()
    expect("undo restores the value", props(1)[BEHAVIORS], before)
    expect("and the map byte-identically",
           document.to_bytes() == ORIGINAL, True)

    session.run(fields_of(look(SIDEON))["gravity"].emit(400.0))
    expect("a parameter edit lands typed",
           props(5)[PARAM_PREFIX + "gravity"], 400.0)
    session.undo()
    expect("its undo restores the hand-authored text verbatim",
           props(5)[PARAM_PREFIX + "gravity"], "9o")
    expect("byte-identically", document.to_bytes() == ORIGINAL, True)

    session.run(fields_of(look(SIDEON))["gravity"].remove(None))
    expect("removing a parameter takes the property out",
           PARAM_PREFIX + "gravity" in props(5), False)
    session.undo()
    expect("and its undo puts it back byte-identically",
           document.to_bytes() == ORIGINAL, True)

    # ------------------------------------------------------------------
    print()
    print("11. the Inspector no longer offers a second, unvalidated door")
    # ------------------------------------------------------------------
    raw_keys = [f.key for f in
                section_of(describe(session, HERO), "Properties").fields]
    expect("describe() alone still renders the vocabulary as free text",
           (BEHAVIORS in raw_keys, PARAM_PREFIX + "walk_format" in raw_keys),
           (True, True))
    stripped = strip_vocabulary(describe(session, HERO))
    kept = [f.key for f in section_of(stripped, "Properties").fields]
    expect("the strip removes the behavior list", BEHAVIORS in kept, False)
    expect("and every parameter property",
           any(k.startswith(PARAM_PREFIX) for k in kept), False)
    expect("while leaving ordinary properties alone", kept, ["hp"])
    expect("and saying where they went",
           "Behaviors panel" in section_of(stripped, "Properties").note, True)
    expect("nothing is stripped from a layer",
           strip_vocabulary(describe(
               session, Scope.of(("map", "fixture"), ("layer", "Floor")))
           ).scope.kind, "layer")
    expect("is_vocabulary covers the list and the parameters, not the actor",
           (is_vocabulary(BEHAVIORS), is_vocabulary(PARAM_PREFIX + "x"),
            is_vocabulary("pyoneer_actor"), is_vocabulary("hp")),
           (True, True, False, False))
    expect("read_tokens says what the file says, duplicates included",
           read_tokens(document.object_layer("entity").find(3)),
           ("topdown_move", "topdown_move", "animation_drive"))

    window = Harness(session)
    inspector = InspectorDock("Inspector", session, HERO, window)
    window.addDockWidget(Qt.RightDockWidgetArea, inspector)
    inspector.refresh()
    application.processEvents()
    shown = [f.key for f in section_of(inspector.view.inspection,
                                       "Properties").fields]
    expect("the mounted Inspector shows hp and not the behavior list",
           (shown, BEHAVIORS in shown), (["hp"], False))

    # ------------------------------------------------------------------
    print()
    print("12. the panel builds, renders and emits through the window")
    # ------------------------------------------------------------------
    dock = BehaviorDock("Behaviors", session, HERO, window)
    window.addDockWidget(Qt.RightDockWidgetArea, dock)
    dock.refresh()
    application.processEvents()

    labels = [label.text() for label in dock.findChildren(QLabel)]
    expect("the panel states the file is the truth, in a visible label",
           IS_WIRED in labels, True)
    expect("and names the three facts an author needs before ticking",
           all(phrase in IS_WIRED for phrase in
               ("whole truth", "read at spawn", "before the entity binds")),
           True)
    expect("the refusal text is on screen, not only in a tooltip",
           any("declare that they conflict" in text for text in labels), False)

    def tick_rows():
        return [f.key for section in dock.view.inspection.sections
                for f in section.fields if f.kind == "bool" and f.editable]

    boxes = dock.findChildren(QCheckBox)
    expect("one check box per editable tick row",
           len(boxes), len(tick_rows()))
    expect("and the refused row is not one of them",
           "platformer_move" in tick_rows(), False)

    history = len(session.history())
    boxes[tick_rows().index("animation_drive")].setChecked(True)
    application.processEvents()
    expect("ticking a box ran exactly one command",
           [c.verb for c in session.history()[-1].commands],
           ["map.object.property.set"])
    expect("which landed on the object",
           props(1)[BEHAVIORS], "player_input,topdown_move,animation_drive")
    expect("and the panel re-read the document",
           fields_of(dock.view.inspection)["animation_drive"].value, True)
    session.undo()
    dock.refresh()
    application.processEvents()
    expect("undo returns the panel to what the file says",
           (fields_of(dock.view.inspection)["animation_drive"].value,
            len(session.history())), (False, history))
    expect("and the map to its bytes", document.to_bytes() == ORIGINAL, True)

    dock.report("")
    expect("the problem strip is hidden with nothing to say",
           dock.problem.isHidden(), True)
    dock.report("a message")
    expect("and shown with something",
           (dock.problem.isHidden(), dock.problem.text()),
           (False, "a message"))
    dock.refresh()
    application.processEvents()
    expect("a refresh clears it", dock.problem.isHidden(), True)

    # ------------------------------------------------------------------
    print()
    print("13. the two Qt traps this repo has already paid for")
    # ------------------------------------------------------------------
    # `widget.setParent(None)` PROMOTES a widget to a top-level window, and
    # `QScrollArea.setWidget()` frees the old body SYNCHRONOUSLY -- freeing a
    # check box while its own `toggled` signal is on the stack, which is
    # STATUS_HEAP_CORRUPTION (law 12). The cure for either is the cause of the
    # other. This panel refreshes from a check box's own signal, so it is
    # exactly that path and both have to be asserted here too.
    def top_levels() -> int:
        return len([w for w in QApplication.topLevelWidgets()
                    if w is not window and w.parent() is None])

    settled = top_levels()
    peak = settled
    original_show = InspectionView.show_inspection

    def watched(self, inspection):
        global peak
        original_show(self, inspection)
        peak = max(peak, top_levels())

    InspectionView.show_inspection = watched
    try:
        for _ in range(8):
            dock.refresh()
            application.processEvents()
    finally:
        InspectionView.show_inspection = original_show
    expect("no orphan window appears mid-rebuild", peak <= settled, True)
    expect("and none accumulate over eight rebuilds",
           top_levels() <= settled, True)

    boxes = dock.findChildren(QCheckBox)
    box = boxes[tick_rows().index("action_relay")]
    destroyed_synchronously: list[int] = []
    box.destroyed.connect(lambda *_a: destroyed_synchronously.append(1))
    box.setChecked(True)
    alive = True
    try:
        box.isChecked()
    except RuntimeError:
        alive = False
    expect("a tick box survives emitting its own command", alive, True)
    expect("its destruction was deferred, not synchronous",
           destroyed_synchronously, [])
    application.processEvents()
    expect("and the command still landed",
           "action_relay" in props(1)[BEHAVIORS], True)
    session.undo()
    dock.refresh()
    application.processEvents()
    expect("undoing it leaves the map byte-identical",
           document.to_bytes() == ORIGINAL, True)

    # ------------------------------------------------------------------
    print()
    print("14. a stale or wrong scope is a message, never a traceback")
    # ------------------------------------------------------------------
    for label, scope in (("a layer", Scope.of(("map", "fixture"),
                                              ("layer", "Floor"))),
                         ("the project", Scope.of("project"))):
        found = look(scope)
        expect(f"{label} scope reports why rather than raising",
               (bool(found.error), found.sections), (True, []))
    expect("an object that is not there says so",
           "no longer" in look(scope_for(99)).error, True)
    dock.set_scope(scope_for(99))
    dock.refresh()
    application.processEvents()
    expect("and the panel renders that without a crash",
           dock.view.inspection.error != "", True)

    # ------------------------------------------------------------------
    print()
    print("15. the run order reads as a SEQUENCE, and categories are DERIVED")
    # ------------------------------------------------------------------
    # Two complaints in one sentence from the author: the bare `order`
    # integer reads as an id, and the flags need categories. The category
    # half is asserted the only way that means anything -- by inventing a
    # behavior declared in a module that does not exist and requiring it to
    # appear under its own heading with NOTHING edited to let it. A check
    # that only listed today's four categories would pass just as happily for
    # a hand-kept table, which is the failure this whole design refuses.

    def arranged(object_id, **kwargs):
        scope = scope_for(object_id)
        return group_by_category(
            look(scope, **kwargs),
            read_tokens(document.object_layer("entity").find(object_id)),
            kwargs.get("registry"))

    def titles(inspection):
        return [section.title for section in inspection.sections]

    def rows_under(inspection, title):
        return [f.key for s in inspection.sections if s.title == title
                for f in s.fields]

    hero_raw = look(HERO)
    hero_view = arranged(1)

    placed = [spec.name for _, specs in categories() for spec in specs]
    expect("every registered behavior lands in a category",
           sorted(placed), sorted(BEHAVIOR_REGISTRY))
    expect("in exactly one -- none is filed twice",
           len(placed), len(set(placed)))
    expect("and no category is empty",
           [name for name, specs in categories() if not specs], [])
    group_orders = [min(s.order for s in specs) for _, specs in categories()]
    expect("the groups themselves come in run order, lowest first",
           group_orders, sorted(group_orders))

    # THE ONE THE DERIVATION RESTS ON. `StealthStub` differs from every other
    # fixture class in this file in exactly one attribute -- the module it
    # says it is declared in.
    invented = dict(BEHAVIOR_REGISTRY)
    invented["sneak"] = BehaviorSpec(name="sneak", summary="Fixture only.",
                                     factory=StealthStub, order=30)
    invented["glide"] = BehaviorSpec(name="glide", summary="Fixture only.",
                                     factory=MovementStub, order=31)
    grouped = dict(categories(invented))
    expect("a behavior declared in an unheard-of module makes its own category",
           [s.name for s in grouped.get("stealth", ())], ["sneak"])
    expect("while one declared in an existing module joins that category",
           "glide" in [s.name for s in grouped["movement"]], True)
    expect("so exactly one category appeared, not two",
           sorted(grouped), sorted(set(dict(categories())) | {"stealth"}))

    shared_class = sorted(t for t, s in BEHAVIOR_REGISTRY.items()
                          if s.factory is
                          BEHAVIOR_REGISTRY["attack_action"].factory)
    expect("every token sharing one factory class shares one category",
           len({BEHAVIOR_REGISTRY[t].category for t in shared_class}), 1)
    expect("and that is more than one token, so it is not vacuous",
           len(shared_class) > 1, True)

    # Law 7's half: no catch-all bucket, so a factory that cannot be filed is
    # refused where it is DECLARED rather than swept into one at display time.
    unfileable = refusal_of(lambda: BehaviorSpec(
        name="unfileable", summary="", factory=NamelessStub))
    expect("a factory whose module shows no name is refused at declaration",
           "no category to be filed under" in unfileable, True)
    expect("naming the behavior that could not be filed",
           "unfileable" in unfileable, True)
    expect("and saying there is no catch-all bucket for it",
           "no catch-all bucket" in unfileable, True)
    expect("a factory with no module at all is refused the same way",
           "no category to be filed under" in refusal_of(
               lambda: BehaviorSpec(name="anonymous", summary="",
                                    factory=Anonymous())), True)
    # A `functools.partial` is NOT that case and must not be refused: it
    # answers `__module__` through its type, so it has a category like
    # anything else. Asserting it separates "cannot be filed" from "I guessed
    # wrong about which callables carry a module", which the first draft did.
    expect("while a partial, which does answer __module__, is accepted",
           refusal_of(lambda: BehaviorSpec(
               name="partial_ok", summary="",
               factory=functools.partial(Stub))), "")
    expect("and so is an ordinary class factory",
           refusal_of(lambda: BehaviorSpec(name="fileable", summary="",
                                           factory=Stub)), "")
    expect("a category with no name to show is refused, not left blank",
           "no readable name" in refusal_of(lambda: category_label("_")), True)
    expect("and an ordinary one is titled, underscores and all",
           (category_label("movement"), category_label("scene_flow")),
           ("Movement", "Scene Flow"))

    # -- the sequence is the ENGINE's sequence -------------------------
    for label, listed in (
            ("listed out of order",
             ("animation_drive", "player_input", "topdown_move")),
            ("a tie as listed",
             ("attack_action", "interact_action", "pause_action")),
            ("the same tie reversed",
             ("pause_action", "interact_action", "attack_action"))):
        expect(f"run_order is what the engine really runs ({label})",
               [s.name for s in run_order(listed)], list(engine_order(listed)))
    expect("and the two tie orders differ, so that was not one case twice",
           engine_order(("attack_action", "interact_action"))
           != engine_order(("interact_action", "attack_action")), True)
    expect("a low order runs first however the object lists it",
           [s.name for s in run_order(("animation_drive", "player_input"))],
           ["player_input", "animation_drive"])

    steps = order_steps()
    expect("the frame's steps are the distinct orders, low first",
           list(steps), sorted({s.order for s in BEHAVIOR_REGISTRY.values()}))
    expect("two behaviors at one order share a step",
           step_of(BEHAVIOR_REGISTRY["attack_action"]),
           step_of(BEHAVIOR_REGISTRY["interact_action"]))
    expect("two at different orders do not",
           step_of(BEHAVIOR_REGISTRY["player_input"])
           == step_of(BEHAVIOR_REGISTRY["topdown_move"]), False)
    expect("a spec outside the sequence gets no step, and says so",
           "not in the sequence" in refusal_of(lambda: step_of(BehaviorSpec(
               name="outsider", summary="", factory=Stub, order=1234))), True)

    # -- the panel: grouped, lossless, and still refusing --------------
    raw_rows = [f.key for f in section_of(hero_raw, CHECKLIST).fields]
    view_rows = [f.key for s in hero_view.sections
                 if s.title.startswith(CHECKLIST) for f in s.fields]
    expect("grouping loses no checklist row",
           sorted(view_rows), sorted(raw_rows))
    expect("and duplicates none into two groups",
           len(view_rows), len(set(view_rows)))
    expect("one heading per category, in the order the registry groups them",
           [t for t in titles(hero_view) if t.startswith(CHECKLIST + " ·")],
           [category_title(name) for name, _ in categories()])
    expect("and the flat 'Behaviors' heading is gone",
           CHECKLIST in titles(hero_view), False)
    expect("every other section crosses over unchanged, in order",
           [t for t in titles(hero_view)
            if not t.startswith(CHECKLIST) and t != RUN_SECTION],
           [t for t in titles(hero_raw) if t != CHECKLIST])

    mover = BEHAVIOR_REGISTRY["topdown_move"]
    expect("a row sits under the heading its own module derives",
           "topdown_move" in rows_under(hero_view,
                                        category_title(mover.category)), True)
    expect("and under no other heading",
           [t for t in titles(hero_view)
            if t.startswith(CHECKLIST + " ·")
            and t != category_title(mover.category)
            and "topdown_move" in rows_under(hero_view, t)], [])

    invented_view = arranged(1, registry=invented)
    expect("the panel gives the unheard-of module its own heading",
           category_title("stealth") in titles(invented_view), True)
    expect("carrying exactly that behavior",
           rows_under(invented_view, category_title("stealth")), ["sneak"])
    expect("and naming the module it was derived from, in the heading's note",
           "scripts.game.behavior.stealth" in [
               s.note for s in invented_view.sections
               if s.title == category_title("stealth")][0], True)
    expect("while the real registry grows no such heading (the other half)",
           category_title("stealth") in titles(hero_view), False)

    # -- the order number now reads as a position ----------------------
    category_titles = [category_title(name) for name, _ in categories()]
    checklist_rows = [f for s in hero_view.sections
                      if s.title in category_titles for f in s.fields]

    def step_text(token):
        return fields_of(hero_view)[token].label.split("   ·   ")[0]

    expect("every row says which step of the frame it runs in",
           [f.label.startswith("step %d of %d   ·   "
                               % step_of(BEHAVIOR_REGISTRY[f.key]))
            for f in checklist_rows], [True] * len(BEHAVIOR_REGISTRY))
    expect("two behaviors at one order show the SAME step, never 2 and 3",
           step_text("attack_action"), step_text("interact_action"))
    expect("two at different orders show different ones",
           step_text("player_input") == step_text("topdown_move"), False)
    expect("every row's tooltip carries the run-order rule",
           [ORDER_RULE in f.doc for f in checklist_rows],
           [True] * len(BEHAVIOR_REGISTRY))
    expect("which the ungrouped description did not, so the panel added it",
           ORDER_RULE in fields_of(hero_raw)["topdown_move"].doc, False)
    expect("and the rule says order is a position and a tie is the list's",
           all(phrase in ORDER_RULE for phrase in
               ("RUN POSITION", "not an id", "share a STEP", "REFUSES")), True)

    run = section_of(hero_view, RUN_SECTION)
    expect("the sequence is the first thing on a clean object",
           titles(hero_view)[0], RUN_SECTION)
    expect("numbering the ticked behaviors in the order the frame calls them",
           [f.label for f in run.fields],
           ["1st   ·   player_input", "2nd   ·   topdown_move"])
    expect("each carrying its declared order beside it",
           [f.value for f in run.fields], ["order 10", "order 20"])
    expect("read-only, because a sequence is not something to tick",
           [f.editable for f in run.fields], [False, False])

    session.run(fields_of(look(HERO))["animation_drive"].emit(True))
    expect("so player_input before topdown_move before animation_drive reads "
           "off the panel at a glance",
           [f.label for f in section_of(arranged(1), RUN_SECTION).fields],
           ["1st   ·   player_input", "2nd   ·   topdown_move",
            "3rd   ·   animation_drive"])
    session.undo()

    acts_run = section_of(arranged(6), RUN_SECTION)
    expect("a tie says the object's list decided it, not the number",
           [("tied with" in f.value) for f in acts_run.fields], [True, True])
    expect("while an untied sequence says no such thing",
           any("tied with" in f.value for f in run.fields), False)
    expect("the tie runs in the order the object lists it",
           [f.key for f in acts_run.fields],
           ["run:attack_action", "run:interact_action"])
    session.run(Command("map.object.property.set", ACTS,
                        {"key": BEHAVIORS,
                         "value": "interact_action,attack_action"}))
    expect("and reversing the object's list reverses the sequence",
           [f.key for f in section_of(arranged(6), RUN_SECTION).fields],
           ["run:interact_action", "run:attack_action"])
    session.undo()
    expect("undo puts it back",
           [f.key for f in section_of(arranged(6), RUN_SECTION).fields],
           ["run:attack_action", "run:interact_action"])

    bare_run = section_of(arranged(2), RUN_SECTION)
    expect("an object composing nothing is called inert and gets no rows",
           ("inert" in bare_run.note, [f.key for f in bare_run.fields]),
           (True, []))
    typo_view = arranged(4)
    expect("a token the registry lacks gets its own group, not an invented one",
           rows_under(typo_view, STRAY_SECTION), ["topdown_mvoe"])
    expect("and stays editable, so the object is still repairable here",
           fields_of(typo_view)["topdown_mvoe"].editable, True)
    expect("the sequence names it rather than numbering it as if it ran",
           ("topdown_mvoe" in section_of(typo_view, RUN_SECTION).note,
            [f.key for f in section_of(typo_view, RUN_SECTION).fields]),
           (True, ["run:animation_drive"]))

    blocked = fields_of(hero_view)["platformer_move"]
    expect("a refused tick is still refused, and still greyed, after grouping",
           (blocked.blocked_reason, blocked.editable),
           (fields_of(hero_raw)["platformer_move"].blocked_reason, False))
    expect("still naming both sides",
           all(word in blocked.blocked_reason
               for word in ("topdown_move", "platformer_move", "conflict")),
           True)
    allowed = fields_of(hero_view)["animation_drive"]
    expect("while a legal tick still emits the command it did ungrouped",
           allowed.emit(True),
           fields_of(hero_raw)["animation_drive"].emit(True))
    expect("and is still editable", allowed.editable, True)

    # -- the parameters still sit under the behavior that reads them ---
    session.run(fields_of(look(HERO))["animation_drive"].emit(True))
    params_view = arranged(1)
    offered = [f.key for f in section_of(params_view, "Parameters").fields
               if not f.key.startswith(PARAM_PREFIX)]
    owned: list[str] = []
    for token in read_tokens(document.object_layer("entity").find(1)):
        for key in BEHAVIOR_REGISTRY[token].param_keys:
            if key not in owned:
                owned.append(key)
    expect("a parameter still follows the behavior that reads it, in the "
           "object's own order", offered, owned)
    expect("which is not merely alphabetical, so that means something",
           owned == sorted(owned), False)
    expect("and the section still sits below every behavior group",
           titles(params_view).index("Parameters")
           > max(index for index, title in enumerate(titles(params_view))
                 if title.startswith(CHECKLIST)), True)
    session.undo()

    # -- and all of it is on screen, not merely in the description ------
    dock.set_scope(HERO)
    dock.refresh()
    application.processEvents()
    shown = [label.text() for label in dock.findChildren(QLabel)]
    expect("every category heading is on screen",
           [category_title(name).upper() in shown for name, _ in categories()],
           [True] * len(categories()))
    expect("the sequence heading too", RUN_SECTION.upper() in shown, True)
    # `in`, not a slice: `deleteLater()` is deferred by design (law 12), so a
    # retired body's labels are still children for a while and an exact list
    # would be asserting how promptly Qt frees them.
    expect("with the ticked behaviors numbered in it",
           ["%s   ·   player_input" % ordinal(1) in shown,
            "%s   ·   topdown_move" % ordinal(2) in shown], [True, True])
    expect("and the flat heading is gone from the window too",
           CHECKLIST.upper() in shown, False)

    # The generated document groups by the same derivation, from the same
    # helpers, so the panel and BEHAVIORS.md cannot file one behavior two
    # different ways.
    doc = describe_all()
    expect("the generated document explains order from the same sentence",
           ORDER_RULE in doc, True)
    expect("and names every category it groups by",
           [category_label(name) in doc for name, _ in categories()],
           [True] * len(categories()))
    expect("a behavior in a new module is documented under a new category "
           "with no edit there either",
           (category_label("stealth") in describe_all(invented),
            category_label("stealth") in doc), (True, False))

    expect("the map is still byte-identical after all of that",
           document.to_bytes() == ORIGINAL, True)

    # ------------------------------------------------------------------
    print()
    print("16. the tmx-exactness limit of the property verbs, named")
    # ------------------------------------------------------------------
    # Last, because these are the two paths that do NOT come back
    # byte-identical, and every assertion above compares against ORIGINAL.
    #
    # Both are the same stated limit of `map.object.property.*`:
    # `MapProperties` can delete a `<property>` and append one but cannot
    # insert at an index. So restoring a property that was not LAST re-appends
    # it at the end, and dropping the only property of a self-closing
    # `<object/>` hands the container's whitespace back to the owner. Every
    # VALUE survives exactly, which is what these assert; the element ORDER
    # does not, which they print. `editor/core/verbs.py` states the limit
    # beside `map.object.action.unset`, which carries a local guard for the
    # second half, and names `scripts/loaders/map_document.py` as the real
    # home -- where `map.object.property.remove` would get it too.
    original_hero = dict(props(1))
    session.run([fields_of(look(HERO))["player_input"].emit(False)])
    session.run([fields_of(look(HERO))["topdown_move"].emit(False)])
    expect("unticking the last behavior removes the property, not blanks it",
           BEHAVIORS in props(1), False)
    session.undo()
    session.undo()
    expect("two undos restore every value exactly", props(1), original_hero)
    print(f"       note: values exact, byte-exact="
          f"{document.to_bytes() == ORIGINAL}; the residue is that a middle "
          f"<property> comes back appended last.")

    dock.set_scope(BARE)
    dock.refresh()
    session.run(fields_of(look(BARE))["topdown_move"].emit(True))
    expect("a first-ever property lands on a childless object",
           props(2), {BEHAVIORS: "topdown_move"})
    session.undo()
    expect("undo restores the properties exactly", props(2), {})
    expect("leaving no empty <properties> element behind",
           list(document.object_layer("entity").find(2).element), [])
    print("       note: values exact; the residue is that an <object/> the "
          "file wrote self-closing returns as <object></object>.")

finally:
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("behavior authoring surface OK")
