"""The editor's behavior surface: the checklist, the refusals, the undo.

`pyoneer_behaviors` is the declaration site of the composition model and the
editor rendered it as an untyped text box. This file covers the panel that
replaced it, and it is written against the two ways that panel could be wrong
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

Every gate is asserted in both directions, because testing one half of an
invariant is the dominant failure this repo has found in its own checks: a
conflict is refused AND a compatible token is accepted; an out-of-genre token
is named AND still offered; the parameters of a ticked behavior are offered
AND withdrawn when it is unticked.

Against its OWN fixture, never `data/maps/test.tmx`: the author repaints that
file and five red suites have come from a check that pinned its contents.

Skips cleanly when PySide6 is absent; the engine does not depend on it and a
bare clone should not fail here.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

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
from editor.ui.behavior_panel import IS_WIRED, BehaviorDock             # noqa: E402
from editor.ui.fields import InspectionView                             # noqa: E402
from editor.ui.inspector import InspectorDock                           # noqa: E402

from scripts.game.behavior.base import (BEHAVIORS, PARAM_PREFIX,        # noqa: E402
                                        BehaviorSpec, EntityBehavior)
from scripts.game.behavior.registry import (BEHAVIOR_REGISTRY,          # noqa: E402
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
    # `widget.setParent(None)` PROMOTES a widget to a top-level window (about
    # twenty flashing on every Ctrl+Z; 59 top-levels at rest -> 85 after one
    # undo), and `QScrollArea.setWidget()` frees the old body SYNCHRONOUSLY,
    # which freed a check box while its own `toggled` signal was on the stack
    # -- STATUS_HEAP_CORRUPTION, 0xC0000374. The cure for either is the cause
    # of the other. This panel refreshes from a check box's own signal, so it
    # is exactly that path and both have to be asserted here too.
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
    print("15. the tmx-exactness limit of the property verbs, named")
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
