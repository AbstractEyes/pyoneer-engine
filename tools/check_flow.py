"""Verify scene and GUI flow: where a firing goes, and what step we are on.

The claims, each one a line the engine is otherwise free to break with no
symptom until a dialogue silently stopped advancing, or a player was left
permanently unable to walk:

     1. `ActionRouter` reaches a routed token's handler and reaches NOTHING
        for an unrouted one; a payload-specific route wins over the
        token-wide one and the token-wide one still serves other payloads
     2. the flow package reaches the event bus at ZERO points, proved from
        the parse tree of BOTH modules, with a decoy that proves the scan
        can find one -- and imports nothing from `editor/`; and what the
        package COSTS to import is measured in a subprocess rather than
        argued in prose
     3. `SceneManager` assigns `entity.action_sink` on BOTH binding routes,
        so `missing_requirements()` reports it before the bind and nothing
        after -- for a hand-built entity AND for one a map spawned
     4. END TO END on a real map: a tmx `pyoneer_behaviors` string, a real
        keypress, a real `GameWindow` opening -- and a quiet frame reaching
        the handler zero times
     5. `SceneFlow` opens each step's window on entry and closes it on exit,
        runs off the end exactly once, and can be replayed
     6. it BORROWS agency and gives back exactly what it took -- a body that
        was already unsteerable is still unsteerable afterwards
     7. the default hold clears `steerable` and LEAVES `enabled_inputs`, so
        the body cannot walk and CAN still press continue -- measured
        through the real behaviors, not asserted from the flags
     8. `hold_ms` auto-advances on the frame it elapses and NOT before, and
        `hold_ms=0` never auto-advances
     9. the runtime vocabulary AGREES with `editor/core/map_events.py`'s
        authoring vocabulary, word for word, rather than forking it
    10. `LayerRenderer.unbind` handles the component half too, so a window
        that is genuinely finished with can be destroyed rather than hidden

EVERY ASSERTION IS A PAIR
-------------------------
A gate proved to let something through and never proved to stop it is the
dominant failure this repo has found in its own checks. Each rule above is
two assertions with opposite expectations; the mutation table at the end
records what each one turned red for.

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
`data/maps/test.tmx` is the author's canvas and is never read; the one map
this file needs is written into a tempdir. `editor/core/map_events.py` IS
imported -- a check under `tools/` may import both sides, and that is the only
way an agreement between two files that may not import each other can be
MEASURED rather than assumed. `scripts/` importing it would break the one-way
rule, which section 2 also asserts.

    .venv/Scripts/python.exe tools/check_flow.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import inspect
import os
import subprocess
import sys
import tempfile

import pygame

pygame.init()
SCREEN = pygame.display.set_mode((160, 160))

import pytmx
from pygame import Rect

from editor.core import map_events
from scripts.core.errors import PyoneerConfigError
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core import renderer as renderer_module
from scripts.core.renderer import GameComponentLayer, LayerRenderer
from scripts.core.scene import scene_manager as scene_manager_module
from scripts.core.scene.game_scene import GameScene
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.spawn import register as register_spawn
from scripts.core.ui.widget.containers.window import GameWindow
from scripts.game.behavior import build, read_requests
from scripts.game.behavior.action import (INTERACT_ACTION, ActionFired,
                                          actions_of)
from scripts.game.behavior.base import BEHAVIORS, PARAM_PREFIX
from scripts.game.behavior.input import intent_of
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import ensure_state, state_of
from scripts.game.entity.game_entity import GameEntity
from scripts.game.flow import (ADVANCE_ACTION, ADVANCE_TRIGGER_KIND,
                               ANY_PAYLOAD, ActionRouter, FlowStep, SceneFlow)
from scripts.game.flow import router as router_module
from scripts.game.flow import scene_flow as scene_flow_module
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap

failures: list[str] = []
asserted: list[int] = []


def expect(label, got, want):
    asserted.append(1)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth: asserting only the exception TYPE passes for
    any raise anywhere inside the call, including a typo three frames down.
    """
    asserted.append(1)
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:44]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


def expect_no_raise(label, call):
    asserted.append(1)
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return
    print(f"  ok   {label:<62} did not raise")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DELTA = 1.0
"""One frame in ENGINE delta units. `MS_PER_DELTA` milliseconds each."""


class Pane:
    """The smallest thing a `FlowStep` can drive: `open()` and `close()`.

    The flow duck-types its window so it does not have to import `GameWindow`
    -- which would put `CoreAssetManager`'s theme load on the import path of
    every module that touches a flow. A REAL `GameWindow` is driven in section
    4; this one exists to record the ORDER of the calls, which a real window
    cannot report.
    """

    def __init__(self, name):
        self.name = name
        self.calls: list[str] = []
        self.shown = False

    def open(self):
        self.calls.append("open")
        self.shown = True

    def close(self):
        self.calls.append("close")
        self.shown = False


class Slot:
    __slots__ = ("held", "pressed", "released")

    def __init__(self):
        self.held = self.pressed = self.released = False


class Keys:
    """A stand-in InputActionManager whose `pressed`/`held` are UNGUARDED.

    Faithful on the one property that matters: the real manager indexes
    `self.actions[name]` with no guard, which is why an action behavior audits
    its verb at attach. A fixture that answered False for an unknown verb
    could not tell a working audit from a deleted one.
    """

    def __init__(self, *verbs):
        self.actions = {verb: Slot() for verb in verbs}

    def tap(self, *verbs):
        for name, slot in self.actions.items():
            slot.pressed = name in verbs
        return self

    def hold(self, *verbs):
        for name, slot in self.actions.items():
            slot.held = name in verbs
        return self

    def pressed(self, name):
        return self.actions[name].pressed

    def held(self, name):
        return self.actions[name].held


class Actor(GameEntity):
    """A drawable, spawnable entity that behaviors compose onto.

    `GamePlayer` is the real registry entry and is not used: it needs a
    spritesheet this repository deliberately does not ship, and every gate
    under test here lives on `BodyState` and in the behaviors, not on that
    class.
    """

    def __init__(self, **kwargs):
        kwargs.pop("input_", None)
        super().__init__(**kwargs)
        block = pygame.Surface((8, 8))
        block.fill((0, 180, 0))
        self._image = block
        self.action_manager = Keys("up", "down", "left", "right", "sprint",
                                   "action", "attack", "pause")
        ensure_state(self)

    @property
    def image(self):
        return self._image

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, event=None):
        pass


register_spawn("FlowActor", Actor)


def frame(entity, delta=DELTA):
    entity.core_frame_update(PyoneerEvent(GameEventType.UPDATE, sender=None,
                                          data={"delta": delta}))


def build_manager():
    renderer = LayerRenderer(SCREEN)
    renderer.bind_camera(GameCamera(pygame.Vector2(160, 160),
                                    pygame.Rect(0, 0, 160, 160), scale=1))
    manager = SceneManager(game=None)
    manager.add_scene("flow", GameScene("flow"))
    manager.set_scene("flow")
    manager.bind(0, renderer)
    return manager, renderer


def make_window(title="dialogue"):
    window = GameWindow(header_text=title, bounds=Rect(8, 8, 120, 60))
    window.core_lifecycle_prepare(PyoneerEvent(GameEventType.PREPARE,
                                               sender=None))
    window.close()                 # a dialogue starts shut
    return window


# The fixture map. No tile layers at all: what is under test is the OBJECT
# path -- spawn, compose, bind, and the sink assignment on that route -- and a
# tileset would only add art this check has no claim about.
FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="8" height="8" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="1" name="entity">
  <object id="1" name="npc" type="FlowActor" x="32" y="32" width="16" height="16">
   <properties>
    <property name="{behaviors}" value="interact_action,action_relay"/>
    <property name="{param}payload" value="door_north"/>
   </properties>
  </object>
 </objectgroup>
</map>
""".format(behaviors=BEHAVIORS, param=PARAM_PREFIX)

workspace = tempfile.mkdtemp(prefix="pyoneer_flow_")
FIXTURE_PATH = os.path.join(workspace, "flow.tmx")
with open(FIXTURE_PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(FIXTURE)


# ===========================================================================
print("\n1. ActionRouter: routed reaches, unrouted does not, payload wins")
# ===========================================================================
router = ActionRouter()
seen: list[tuple[str, str]] = []
router.route("interact_action", lambda e, f: seen.append(("wide", f.payload)))
router.route("interact_action", lambda e, f: seen.append(("door", f.payload)),
             payload="door_north")

# BOTH HALVES of the routing gate. A routed token reaches its handler; an
# unrouted one reaches NOTHING -- and silence there is correct, because
# `action_relay` hands over every firing an entity produced and routing
# `interact_action` is not a promise to care about `attack_action`.
expect("a routed token reaches exactly one handler",
       router(None, ActionFired("interact_action", "action")), 1)
expect("...and it is the token-wide one, for a firing with no payload",
       seen, [("wide", "")])
seen.clear()
expect("an UNROUTED token reaches nothing",
       router(None, ActionFired("attack_action", "attack")), 0)
expect("...and no handler ran", seen, [])

# Most specific first: the same shape `resolve_depth` and behavior parameter
# resolution both use. BOTH HALVES -- the specific route wins for its payload,
# and the wide route still serves every other payload.
seen.clear()
expect("a payload-specific route wins over the token-wide one",
       router(None, ActionFired("interact_action", "action", "door_north")), 1)
expect("...and it is the specific handler, not both", seen, [("door", "door_north")])
seen.clear()
expect("...while an unlisted payload still reaches the token-wide route",
       router(None, ActionFired("interact_action", "action", "chest")), 1)
expect("...and it is the wide handler", seen, [("wide", "chest")])

# N handlers on one firing -- the property a consumed bus event cannot give.
tally = ActionRouter()
hits: list[int] = []
for index in range(3):
    tally.route("interact_action", lambda e, f, n=index: hits.append(n))
expect("three handlers on one token all run, and none can stop the others",
       (tally(None, ActionFired("interact_action", "action")), hits), (3, [0, 1, 2]))

# A payload-specific route with NO token-wide fallback: the other half of the
# resolution rule, and the one that fails if the fallback is unconditional.
narrow = ActionRouter()
narrow_hits: list[str] = []
narrow.route("interact_action", lambda e, f: narrow_hits.append(f.payload),
             payload="door_north")
expect("the specific payload fires", narrow(None, ActionFired(
    "interact_action", "action", "door_north")), 1)
expect("...and a different payload reaches nothing, with no wide route",
       narrow(None, ActionFired("interact_action", "action", "chest")), 0)
expect("...and a firing with NO payload reaches nothing either",
       narrow(None, ActionFired("interact_action", "action")), 0)
expect("only the one payload ever ran", narrow_hits, ["door_north"])

# Reporting, and the refusals at wiring time.
expect("routes report sorted, so two scenes wired alike report alike",
       router.routes,
       (("interact_action", "", 1), ("interact_action", "door_north", 1)))
expect("membership by token alone", "interact_action" in router, True)
expect("...and by the full key", ("interact_action", "door_north") in router, True)
expect("...and False for a key with no handlers",
       ("interact_action", "chest") in router, False)
expect("clear() drops just that key and reports how many went",
       (router.clear("interact_action", "door_north"), len(router)), (1, 1))
expect("...and clear() with no argument drops the rest", router.clear(), 1)
expect_raises("an empty token is refused AT WIRING TIME, not at fire time",
              PyoneerConfigError, lambda: router.route("", lambda e, f: None),
              "non-empty token", "interact_action")
expect_raises("...and a non-callable handler is refused, naming the token",
              PyoneerConfigError, lambda: router.route("interact_action", 7),
              "interact_action", "not callable")
expect_raises("...and a non-string payload is refused",
              PyoneerConfigError,
              lambda: router.route("interact_action", lambda e, f: None,
                                   payload=3),
              "opaque STRING key")

# A handler that rewires from inside its own call must not mutate the list the
# dispatch loop is walking. Same hazard `EntityBehaviors.update` snapshots
# against, and the same one that makes a self-unbinding object skip a sibling.
mutating = ActionRouter()
ran: list[str] = []


def rewire(entity, fired):
    ran.append("first")
    mutating.clear("interact_action")
    mutating.route("interact_action", lambda e, f: ran.append("late"))


mutating.route("interact_action", rewire)
mutating.route("interact_action", lambda e, f: ran.append("second"))
expect_no_raise("a handler may rewire the router from inside its own call",
                lambda: mutating(None, ActionFired("interact_action", "action")))
expect("...and this frame still ran the set as it was", ran, ["first", "second"])
ran.clear()
expect("...and the rewire takes effect on the next firing",
       (mutating(None, ActionFired("interact_action", "action")), ran),
       (1, ["late"]))

# THE OTHER HALF, and the one with the teeth. `clear()` POPS the dict entry
# and never touches the list the dispatch loop is holding, so the pair above
# passes with or without the snapshot -- measured: mutating `handlers_for` to
# return the live list left every assertion above green. `route()` on a key
# that is mid-dispatch APPENDS to that exact list, and without the snapshot
# the new handler runs in the same pass and the returned count is wrong too.
appending = ActionRouter()
order: list[str] = []


def add_more(entity, fired):
    order.append("first")
    appending.route("interact_action", lambda e, f: order.append("added"))


appending.route("interact_action", add_more)
appending.route("interact_action", lambda e, f: order.append("second"))
_count = appending(None, ActionFired("interact_action", "action"))
expect("a handler that ROUTES mid-dispatch does not run this frame",
       order, ["first", "second"])
expect("...and the count reports the set as it was, not as it became",
       _count, 2)
order.clear()
expect("...and the added handler runs on the NEXT firing",
       (appending(None, ActionFired("interact_action", "action")), order),
       (3, ["first", "second", "added"]))

expect("a firing with no name reaches nothing rather than raising",
       ActionRouter()(None, ActionFired("", "action")), 0)


# ===========================================================================
print("\n2. the flow package reaches the event bus at zero points")
# ===========================================================================
BUS_CALLS = {"handle", "mark_event_handled", "send_event", "send_event_advanced",
             "send_event_to_self", "bind_listener", "bind_sync_listener",
             "bind_async_listener", "bind_mouse_listener"}


def scan(module):
    """(bus calls, imported module names) from a module's PARSE TREE.

    The tree and not the text, so the docstrings that explain WHY this never
    dispatches -- which contain the words `handle()` and `mark_event_handled`
    -- do not trip the scan. `binds == ()` on a spec is the assertion that
    passes trivially forever; this is the one with teeth.
    """
    with open(inspect.getsourcefile(module), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    called = sorted({
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
        and (node.func.attr if isinstance(node.func, ast.Attribute)
             else node.func.id) in BUS_CALLS})
    imported = sorted({node.module or "" for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom)}
                      | {alias.name for node in ast.walk(tree)
                         if isinstance(node, ast.Import) for alias in node.names})
    return called, imported


for _module, _name in ((router_module, "router.py"),
                       (scene_flow_module, "scene_flow.py")):
    _called, _imported = scan(_module)
    expect("%s makes no bus call anywhere" % _name, _called, [])
    expect("...and imports no event or component module" % (),
           [m for m in _imported if "event" in m or "component" in m], [])
    expect("...and imports nothing from editor/ (the one-way rule)",
           [m for m in _imported if m.startswith("editor")], [])

# The other half: the scan is CAPABLE of finding one. A scan whose name list
# was wrong would look exactly like a clean pass.
DECOY = ast.parse("class X:\n    def go(self, e):\n        e.handle()\n")
expect("...and the same scan DOES find a bus call when one is planted",
       sorted({n.func.attr for n in ast.walk(DECOY)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in BUS_CALLS}), ["handle"])

# The router is reached from the FRAME path, where every object already has
# its own event -- never from `core_input_receive`, which hands one shared
# event to every bound object including the whole UI tree.
_relay = inspect.getsource(
    __import__("scripts.game.behavior.action", fromlist=["x"])
    .GameActionRelayBehavior)
expect("the relay that calls the sink is an `update`, i.e. the frame path",
       "def update(self, entity: Any, event: Any)" in _relay, True)

# ---------------------------------------------------------------------------
# WHAT THE FLOW PACKAGE ACTUALLY COSTS TO IMPORT, MEASURED IN A SUBPROCESS
# ---------------------------------------------------------------------------
# `sys.modules` in THIS process answers nothing: the file above imports
# `GameWindow`, both flow modules and the whole engine. Each claim below is a
# fresh interpreter that imports exactly one name.


def loads(statement: str, module: str) -> bool:
    """Is `module` in `sys.modules` after `statement`, in a FRESH interpreter?

    The last line of stdout, because pygame prints a banner on import and
    parsing the first line would read the SDL version as a boolean.
    """
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys\nsys.path.insert(0, %r)\n%s\nprint(%r in sys.modules)"
         % (_bootstrap.REPO_ROOT, statement, module)],
        capture_output=True, text=True, cwd=_bootstrap.REPO_ROOT)
    lines = proc.stdout.strip().splitlines()
    return bool(lines) and lines[-1] == "True"


# BOTH HALVES, and the first one retires an argument `SceneManager` used to
# make. Its `flow` slot is annotated `Any`, and the stated reason WAS that
# importing `SceneFlow` "would put the whole flow package on the import path
# of every scene" -- while the line above it imports `ActionRouter`, which
# executes `scripts/game/flow/__init__.py`, which imports `scene_flow`. The
# package is one import unit, so the annotation would have added nothing.
expect("importing the ROUTER alone already loads scene_flow: the flow package "
       "is ONE import unit",
       loads("import scripts.game.flow.router",
             "scripts.game.flow.scene_flow"), True)
# The other half: the same probe answers False, and for a claim that IS load
# bearing -- `scene_flow` duck-types its window rather than importing
# `GameWindow`, which would drag `CoreAssetManager`'s theme load onto the
# import path of every module that touches a flow.
expect("...while the same probe says False for GameWindow, which the flow "
       "duck-types rather than imports",
       loads("import scripts.game.flow",
             "scripts.core.ui.widget.containers.window"), False)

# The altitude question the same slot raises: is `scripts/core/` importing
# `scripts/game/` a new coupling? Measured, no -- `scripts/core/renderer.py`
# does it too, and `scene_manager` imports `renderer`, so those modules are on
# its path whether or not it spells them. The one-way rule is law 2, below.
expect("scripts/core/renderer.py imports scripts.game at module level too",
       bool([m for m in scan(renderer_module)[1]
             if m.startswith("scripts.game")]), True)
expect("...so does scripts/core/scene/scene_manager.py",
       bool([m for m in scan(scene_manager_module)[1]
             if m.startswith("scripts.game")]), True)
expect("...and NEITHER imports editor/ -- that is the rule that is real",
       sorted([m for m in scan(renderer_module)[1]
               if m.startswith("editor")]
              + [m for m in scan(scene_manager_module)[1]
                 if m.startswith("editor")]), [])
# ...and the same scan DOES find an `editor` import where there is one. This
# check file imports `editor.core.map_events` itself, so a prefix scan that
# matched nothing because the spelling was wrong is distinguishable from a
# clean pass -- the same argument the decoy above makes for the bus scan.
expect("...proved: the same scan finds the editor import in THIS file",
       [m for m in scan(sys.modules[__name__])[1] if m.startswith("editor")],
       ["editor.core"])


# ===========================================================================
print("\n3. SceneManager assigns the sink, on BOTH binding routes")
# ===========================================================================
# BOTH HALVES, and this is what moved `action_relay` off `needs-host`: an
# unbound entity reports the requirement missing, a bound one does not.
loose = Actor()
loose.behaviors.attach_all(build(read_requests(
    {BEHAVIORS: "interact_action,action_relay"})))
expect("an entity nobody bound reports action_sink missing",
       loose.behaviors.missing_requirements(), (("action_relay", "action_sink"),))

manager, renderer = build_manager()
manager.bind(50, loose)
expect("...and binding it into a scene satisfies the requirement",
       loose.behaviors.missing_requirements(), ())
expect("...because the sink IS the scene's router, by identity",
       loose.action_sink is manager.actions, True)

# The map route. Same assertion, different code path -- the whole reason
# `__sink` is one private method called from two places, exactly as
# `LayerRenderer.__gate` is.
map_manager, map_renderer = build_manager()
map_manager.bind("MAP", GameMap(pytmx.load_pygame(FIXTURE_PATH)))
spawned = [obj for _b, obj in map_manager.current_scene.contents()
           if isinstance(obj, Actor)]
expect("the fixture map spawned exactly one actor", len(spawned), 1)
npc = spawned[0]
expect("...composed from the tmx property, in declared order",
       npc.behaviors.names, ("interact_action", "action_relay"))
expect("...and it too was handed the scene's router",
       npc.action_sink is map_manager.actions, True)
expect("...so it reports nothing missing", npc.behaviors.missing_requirements(), ())

# The half that proves `__sink` is selective rather than a blanket setattr.
window = make_window()
map_manager.bind(100, window)
expect("a UI component is NOT given an action_sink it has no relay to use",
       hasattr(window, "action_sink"), False)


# ===========================================================================
print("\n4. end to end: a tmx property, a real keypress, a real GameWindow")
# ===========================================================================
dialogue = make_window("door_north")
flow = SceneFlow([FlowStep("greeting", window=dialogue)], bodies=[npc],
                 name="door")
opened: list[str] = []
map_manager.actions.route(ADVANCE_ACTION,
                          lambda e, f: (opened.append(f.payload), flow.begin()))
map_manager.flow = flow

expect("the window starts shut", (dialogue.visible, dialogue.active), (False, False))
expect("...and the flow has not begun", (flow.running, flow.done), (False, False))

# A quiet frame: the relay runs, the record is empty, nothing is routed. This
# is the half that fails if the relay ever fires on an allocated-but-empty slot.
npc.action_manager.tap()
frame(npc)
expect("a quiet frame routes nothing", opened, [])
expect("...and the window is still shut", dialogue.visible, False)

# The press. Nothing between the key and the window is written in this check:
# interact_action records, action_relay calls the sink SceneManager assigned,
# the router picks the handler, the handler begins the flow, the flow opens
# the window.
npc.action_manager.tap("action")
frame(npc)
expect("the firing carried the AUTHORED payload all the way out",
       opened, ["door_north"])
expect("...the flow is running on its first step",
       (flow.running, flow.current.name), (True, "greeting"))
expect("...and a real GameWindow is open, active and visible",
       (dialogue.visible, dialogue.active), (True, True))
expect("...and the body that opened it may no longer be steered",
       state_of(npc).steerable, False)
expect("...but may still act, which is what advances the dialogue",
       state_of(npc).enabled_inputs, True)

# The advance, through the same wire. The handler begins an already-running
# flow (refused, correctly) and the router's second route advances it.
map_manager.actions.clear()
map_manager.actions.route(ADVANCE_ACTION, flow.on_action)
npc.action_manager.tap()
frame(npc)                                   # release, so the next tap is an edge
npc.action_manager.tap("action")
frame(npc)
expect("the same verb advances the flow off the end", flow.running, False)
expect("...the window is shut again", dialogue.visible, False)
expect("...the flow reports done rather than merely not-running",
       (flow.done, flow.index), (True, -1))
expect("...and the body's steering came back", state_of(npc).steerable, True)


# ===========================================================================
print("\n5. SceneFlow: the step machine, and the windows it drives")
# ===========================================================================
one, two, three = Pane("one"), Pane("two"), Pane("three")
march = SceneFlow([FlowStep("a", window=one), FlowStep("b", window=two),
                   FlowStep("c", window=three)], name="march")
expect("before begin: no current step, not running, not done",
       (march.current, march.running, march.done, march.index),
       (None, False, False, -1))
expect("begin() enters step 0 and reports it started", (march.begin(),
       march.current.name, march.index), (True, "a", 0))
expect("...opening only the first window",
       (one.calls, two.calls, three.calls), (["open"], [], []))
expect("...and beginning again is refused rather than re-taking agency",
       march.begin(), False)
expect("advance() closes the old window and opens the next",
       (march.advance(), one.calls, two.calls),
       (True, ["open", "close"], ["open"]))
expect("...and reports the step it moved to", march.current.name, "b")
march.advance()
expect("the last step is entered", (march.current.name, three.shown), ("c", True))
expect("advancing off the end reports False, not True", march.advance(), False)
expect("...closes the last window", three.calls, ["open", "close"])
expect("...and every window is shut, none opened twice",
       [p.calls for p in (one, two, three)],
       [["open", "close"], ["open", "close"], ["open", "close"]])
expect("...and it is done and not running", (march.done, march.running),
       (True, False))
expect("advancing a finished flow does nothing", march.advance(), False)
expect("...and opened no window again",
       [len(p.calls) for p in (one, two, three)], [2, 2, 2])

# Replayable: a shopkeeper's dialogue plays more than once.
expect("begin() on a finished flow rewinds it",
       (march.begin(), march.current.name, march.done), (True, "a", False))
expect("...and reopened the first window", one.calls,
       ["open", "close", "open"])
march.end()
expect("end() stops it wherever it is and closes the window",
       (march.running, march.done, one.shown), (False, True, False))
expect("...and ending a stopped flow reports False", march.end(), False)

# A step with no window is a real step: a beat that only holds input away.
quiet = SceneFlow([FlowStep("beat"), FlowStep("talk", window=one)], name="quiet")
expect_no_raise("a windowless step is entered without raising", quiet.begin)
expect("...and advancing from it opens the next step's window",
       (quiet.advance(), one.shown), (True, True))
quiet.end()

# The refusals.
expect_raises("an empty flow is refused: it would freeze with no beat",
              PyoneerConfigError, lambda: SceneFlow([], name="hollow"),
              "no steps", "hollow")
expect_raises("...and a non-FlowStep step is refused, naming the flow",
              PyoneerConfigError, lambda: SceneFlow(["a"], name="stringly"),
              "stringly", "FlowStep")
expect_raises("an unnamed step is refused", PyoneerConfigError,
              lambda: FlowStep(""), "non-empty name")
expect_raises("...and a negative hold is refused rather than skipped",
              PyoneerConfigError, lambda: FlowStep("x", hold_ms=-1),
              "'x'", "already elapsed")
expect_raises("...and a boolean hold is refused", PyoneerConfigError,
              lambda: FlowStep("x", hold_ms=True), "bool")
expect_no_raise("hold_ms=0 is legal: it means wait for an advance",
                lambda: FlowStep("x", hold_ms=0))


# ===========================================================================
print("\n6. agency is BORROWED, and given back exactly")
# ===========================================================================
free, already_held, scenery = Actor(), Actor(), object()
state_of(already_held).steerable = False       # inert before the flow existed
borrow = SceneFlow([FlowStep("beat")], bodies=[free, already_held, scenery],
                   name="borrow")
borrow.begin()
expect("the flow holds the two bodies that carry a record",
       [b is free or b is already_held for b in borrow.held_bodies], [True, True])
expect("...and silently ignores the one that does not", len(borrow.held_bodies), 2)
# The stateless object is FIRST in the tuple above by accident of writing.
# Put it first deliberately: a `held_bodies` that filtered by index rather
# than by "carries a record" would pass the length assertion either way.
_lead = SceneFlow([FlowStep("beat")], bodies=[object(), free, already_held],
                  name="lead")
_lead.begin()
expect("a stateless object FIRST in the list is still skipped, not held",
       ([b is free for b in _lead.held_bodies],
        [b is already_held for b in _lead.held_bodies]),
       ([True, False], [False, True]))
_lead.end()
expect("both bodies are unsteerable while it runs",
       (state_of(free).steerable, state_of(already_held).steerable), (False, False))
borrow.end()

# THE HALF THAT GETS FORGOTTEN. `end()` restores the value each body HAD, and
# never `True`. Five of the six demo players are inert precisely because their
# `can_move` is False, and a flow that ended by enabling everything it touched
# would silently animate the scenery.
expect("the body that was steerable gets its steering back",
       state_of(free).steerable, True)
expect("...and the body that was ALREADY unsteerable stays unsteerable",
       state_of(already_held).steerable, False)

# An axis left at None is neither saved nor written. BOTH HALVES: the default
# leaves `enabled_inputs` and `simulated` alone; asking clears them.
untouched = Actor()
default_flow = SceneFlow([FlowStep("beat")], bodies=[untouched])
default_flow.begin()
expect("the default hold leaves enabled_inputs alone",
       state_of(untouched).enabled_inputs, True)
expect("...and leaves simulated alone", state_of(untouched).simulated, True)
default_flow.end()

hard = Actor()
state_of(hard).enabled_inputs = True
freeze = SceneFlow([FlowStep("beat")], bodies=[hard],
                   enabled_inputs=False, simulated=False)
freeze.begin()
expect("a flow that asks for it clears enabled_inputs",
       state_of(hard).enabled_inputs, False)
expect("...and clears simulated", state_of(hard).simulated, False)
freeze.end()
expect("...and both come back", (state_of(hard).enabled_inputs,
                                 state_of(hard).simulated), (True, True))

# A flow that touches NO axis is legal and takes nothing.
observer = Actor()
watch = SceneFlow([FlowStep("beat")], bodies=[observer], steerable=None)
watch.begin()
expect("a flow with every axis None borrows nothing",
       state_of(observer).steerable, True)
watch.end()

# `simulated` is honest about its reach: `GamePlayer.core_frame_update` is the
# only reader in the engine. Asserted from source, so the day a second reader
# appears this line is where the claim is updated.
_player_source = inspect.getsource(
    __import__("scripts.game.entity.game_player", fromlist=["x"]).GamePlayer
    .core_frame_update)
expect("GamePlayer.core_frame_update is what reads `simulated`",
       "self.state.simulated" in _player_source, True)


# ===========================================================================
print("\n7. the default hold: cannot walk, CAN press continue")
# ===========================================================================
# Measured through the REAL behaviors rather than asserted from the flags.
# `player_input` gates on `steerable`; the action behaviors deliberately do
# NOT, and that divergence is what makes a visual novel able to advance itself.
walker = Actor()
walker.behaviors.attach_all(build(read_requests(
    {BEHAVIORS: "player_input,topdown_move,interact_action"})))
walker.moveto((50.0, 50.0))
walker.action_manager.hold("right").tap("action")
frame(walker)
_free_x = walker.transform.position.x
expect("before the flow: holding right MOVES the body", _free_x > 50.0, True)
expect("...and the action fires", actions_of(walker).fired("interact_action")
       is not None, True)

hold = SceneFlow([FlowStep("beat")], bodies=[walker], name="cutscene")
hold.begin()
walker.action_manager.hold("right").tap()
frame(walker)
walker.action_manager.hold("right").tap("action")
frame(walker)
expect("during the flow: holding right moves it ZERO pixels",
       walker.transform.position.x, _free_x)
expect("...the movement intent is empty, so the gate is on the PRODUCER",
       intent_of(walker).right, False)
expect("...and the SAME frame's action still fires -- press continue works",
       actions_of(walker).fired("interact_action") is not None, True)

hold.end()
walker.action_manager.hold("right").tap()
frame(walker)
expect("after the flow: the body walks again",
       walker.transform.position.x > _free_x, True)

# The measured limit, written down so it is not discovered mid-cutscene:
# clearing `steerable` does NOT pause the world. A side-on body keeps falling.
faller = Actor()
faller.behaviors.attach_all(build(read_requests(
    {BEHAVIORS: "player_input,platformer_move"})))
faller.moveto((0.0, 0.0))
fall_flow = SceneFlow([FlowStep("beat")], bodies=[faller])
fall_flow.begin()
for _ in range(10):
    frame(faller)
expect("a side-on body with steering taken away STILL FALLS -- not a pause",
       faller.transform.position.y > 0.0, True)
fall_flow.end()


# ===========================================================================
print("\n8. hold_ms auto-advances on the frame it elapses, and not before")
# ===========================================================================
HOLD = 300.0
FRAMES = int(HOLD / MS_PER_DELTA)          # derived, never typed twice
expect("the fixture hold is a whole number of frames at this tick rate",
       FRAMES * MS_PER_DELTA, HOLD)

timed = SceneFlow([FlowStep("first", hold_ms=HOLD), FlowStep("second")],
                  name="timed")
timed.begin()
for _ in range(FRAMES - 1):
    timed.update(DELTA)
expect("one frame short, it is still on the first step", timed.current.name,
       "first")
expect("...with the elapsed clock in MILLISECONDS, not delta units",
       timed.elapsed_ms, (FRAMES - 1) * MS_PER_DELTA)
timed.update(DELTA)
expect("...and on the frame it elapses it has moved on", timed.current.name,
       "second")
expect("...and the new step's clock was reset", timed.elapsed_ms, 0.0)

# BOTH HALVES: a hold_ms=0 step never auto-advances, however long it is ticked.
for _ in range(FRAMES * 5):
    timed.update(DELTA)
expect("a hold_ms=0 step waits forever rather than timing out",
       (timed.running, timed.current.name), (True, "second"))
expect("...and an advance still moves it", timed.advance(), False)
expect("...off the end", timed.done, True)

expect("updating a flow that is not running does nothing",
       (timed.update(DELTA), timed.running, timed.elapsed_ms),
       (None, False, 0.0))

# The whole clock, driven by the real frame loop rather than by hand.
tick_manager, _tick_renderer = build_manager()
auto = SceneFlow([FlowStep("first", hold_ms=HOLD), FlowStep("second")],
                 name="auto")
auto.begin()
tick_manager.flow = auto
for _ in range(FRAMES - 1):
    tick_manager.post_update(DELTA)
expect("SceneManager.post_update drives the flow: one frame short",
       auto.current.name, "first")
tick_manager.post_update(DELTA)
expect("...and it advances on the frame it elapses", auto.current.name, "second")
_no_flow_manager, _ = build_manager()
expect_no_raise("...and a manager with no flow post-updates fine",
                lambda: _no_flow_manager.post_update(DELTA))


# ===========================================================================
print("\n9. the runtime vocabulary AGREES with the editor's, word for word")
# ===========================================================================
# `scripts/` may never import `editor/`, so the agreement cannot be an import.
# It is a spelling, and this is where it is MEASURED -- a check under `tools/`
# may import both sides. Without this, two files agreeing is a coincidence.
expect("the flow's advance kind IS the editor's `use` trigger kind",
       ADVANCE_TRIGGER_KIND, map_events.USE)
expect("...which is one of the four kinds the editor declares",
       ADVANCE_TRIGGER_KIND in map_events.TRIGGER_KINDS, True)
expect("...and the runtime half of it is `interact_action`",
       ADVANCE_ACTION, INTERACT_ACTION.name)
expect("...whose registered summary names that trigger kind, in the doc a "
       "blind reader gets", "`use` map trigger" in INTERACT_ACTION.summary, True)

# BOTH HALVES of the agreement: the words that ARE shared are spelled the same,
# and the flow does not invent a second copy of the ones that are not.
_editor_keys = set(map_events.BY_KEY)
_action_keys = set(INTERACT_ACTION.param_keys)
expect("payload, once and cooldown_ms are shared, verbatim",
       sorted(_editor_keys & _action_keys), ["cooldown_ms", "once", "payload"])
expect("...and `payload` means the same opaque key on both sides",
       (map_events.BY_KEY["payload"].type,
        INTERACT_ACTION.param("payload").type), ("str", "str"))
expect("...spelled `pyoneer_payload` on a trigger and `pyoneer_param_payload` "
       "on a behavior", (map_events.PAYLOAD,
                         INTERACT_ACTION.param("payload").property_name),
       ("pyoneer_payload", "pyoneer_param_payload"))
expect("the route-any key IS an action's default payload, so they meet at one "
       "key", (ANY_PAYLOAD, INTERACT_ACTION.param("payload").default), ("", ""))
expect("...both prefixed, because pytmx raises on an unprefixed collision",
       (map_events.PAYLOAD.startswith("pyoneer_"),
        INTERACT_ACTION.param("payload").property_name.startswith("pyoneer_")),
       (True, True))

# The fork that is deliberately NOT made. `args` has a round-trip-checked
# parse/format pair on the editor side, and re-spelling it in `scripts/` would
# be the second implementation of one vocabulary.
expect("the editor owns `args` and its parser", ("args" in _editor_keys,
       hasattr(map_events, "parse_args")), (True, True))
expect("...and the action vocabulary deliberately declares none",
       "args" in _action_keys, False)

_flow_source = ""
for _module in (router_module, scene_flow_module):
    with open(inspect.getsourcefile(_module), encoding="utf-8") as _handle:
        _flow_source += _handle.read()
for _forked in ("def parse_args", "def format_args", "TRIGGER_KINDS =",
                "def parse_names", "def accepts"):
    expect("the flow package re-implements no `%s`" % _forked.rstrip(" ="),
           _forked in _flow_source, False)
# The other half: the same scan DOES see a thing that IS there, so a scan that
# matched nothing because the strings were wrong is distinguishable.
expect("...and the same scan finds what the flow DOES declare",
       "ADVANCE_TRIGGER_KIND" in _flow_source, True)


# ===========================================================================
print("\n10. the component half of despawn: a window can be destroyed")
# ===========================================================================
ui_manager, ui_renderer = build_manager()
doomed_window = make_window("temporary")
ui_manager.bind(100, doomed_window)
_layers = [layer for layers in ui_renderer.layers.values() for layer in layers
           if isinstance(layer, GameComponentLayer)]
expect("binding a window puts it in a GameComponentLayer",
       [any(c is doomed_window for c in layer.components) for layer in _layers],
       [True])

# BOTH HALVES: `close()` HIDES and keeps the component bound -- which is what
# a reopenable dialogue needs -- while `despawn` removes it outright.
doomed_window.close()
expect("close() hides it and leaves it bound",
       (doomed_window.visible,
        any(c is doomed_window for layer in _layers
            for c in layer.components)), (False, True))
expect("despawn takes it out of the layer", ui_manager.despawn(doomed_window),
       True)
expect("...and the layer no longer holds it",
       any(c is doomed_window for layer in _layers for c in layer.components),
       False)
expect("...and despawning it again reports nothing to remove",
       ui_manager.despawn(doomed_window), False)
expect("...and the renderer answers False for a window it never held",
       ui_renderer.unbind(make_window("stranger")), False)


# ===========================================================================
print("\n" + "=" * 74)
if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"assertions             : {len(asserted)}")
print(f"editor vocabulary      : {len(map_events.BY_KEY)} trigger field(s), "
      f"{len(map_events.TRIGGER_KINDS)} kind(s)")
print(f"headless boots         : 1 map, {2} GameWindow(s)\n")
print("""OK -- scene and GUI flow: a firing reaches a window, and the body waits.

MUTATIONS RUN, AND WHAT EACH ONE TURNED RED
  * `ActionRouter.handlers_for` falling back to the wide route even when an
    exact one matched (`return exact + wide`)
        -> section 1: "the specific handler, not both" fails
  * ...and the reverse: the fallback removed entirely
        -> section 1: "an unlisted payload still reaches the token-wide route"
           fails, while every positive assertion above it still passes
  * `handlers_for` returning the live list instead of a tuple
        -> section 1: the ROUTE-mid-dispatch triple fails.
           NOTE: this mutation ran GREEN the first time and that is why the
           triple exists. The check originally proved the snapshot with a
           handler that called `clear()` -- which POPS the dict entry and
           never touches the list the loop is holding, so it passed with or
           without the snapshot. One half of the hazard, exactly the shape
           this repo keeps finding. `route()` appends to that same live list
           and is the half with teeth.
  * `route()`'s empty-token and callable guards deleted
        -> section 1: the two wiring-time refusals fail
  * `e.handle()` planted in `ActionRouter.__call__`
        -> section 2: the parse-tree scan fails for router.py
  * the subprocess probe pointed at a module nothing loads
    (`loads("import scripts.core.depth", "scripts.game.flow.scene_flow")`)
        -> answered False, measured. That is how the True half above is known
           to be a measurement rather than a probe that always agrees. The
           negative half that SHIPS is the GameWindow one, because that claim
           is load bearing on its own: `scene_flow` duck-types its window
  * `scripts/game/flow/__init__.py` no longer re-exporting `scene_flow`
        -> section 2: "the flow package is ONE import unit" fails. NOT RUN as
           a file edit -- `flow/__init__.py` was not this pass's to edit, and
           the control above already shows the probe answers either way. If
           it ever does fail, the paragraph to revisit is the one on
           `SceneManager.flow`, which cites this measurement by name
  * the `editor` prefix in the import scan misspelled (`edtor`)
        -> section 2, FAILED 1: "the same scan finds the editor import in
           THIS file". That is what stops the three `[]` assertions above it
           from being vacuous
  * `SceneManager.__sink` deleted
        -> section 3: both `missing_requirements` halves fail, and section 4
           routes nothing at all
  * `__sink` called from `bind` only, not from `__bind_spawned_entities`
        -> section 3: the map-route assertion fails and the hand-built one
           passes -- which is the exact asymmetry `LayerRenderer.__gate`
           exists to prevent
  * `__sink` assigning to every bound object rather than to GameEntity
        -> section 3: "a UI component is NOT given an action_sink" fails
  * `SceneFlow._leave` not calling `close()`
        -> section 5: the window-call-order assertions fail
  * `SceneFlow._restore` writing `True` instead of the saved value
        -> section 6: "the body that was ALREADY unsteerable" fails, and
           every other assertion in that section still passes
  * `_borrow` saving an axis whose keyword is None
        -> section 6: "the default hold leaves enabled_inputs alone" fails
  * `SceneFlow` clearing `enabled_inputs` by default
        -> section 7: "the SAME frame's action still fires" fails
  * `SceneFlow.update` omitting `* MS_PER_DELTA`
        -> section 8: the frame-before/frame-of pair fails
  * `hold_ms > 0` relaxed to `>= 0`
        -> section 8: "a hold_ms=0 step waits forever" fails
  * `ADVANCE_TRIGGER_KIND` changed to "interact"
        -> section 9: the agreement with map_events.USE fails
  * `LayerRenderer.unbind` handling EntityLayer only
        -> section 10: "despawn takes it out of the layer" fails""")
