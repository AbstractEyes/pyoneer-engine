"""Verify entity control: a body declares itself gone, and is really removed.

The claims, each one a line the engine is otherwise free to break with no
symptom until an author noticed a sprite that would not go away, or a
neighbour that skipped a frame:

     1. `life` is a CLOSED two-value axis that raises on anything else, and
        it defaults to alive on a record nobody has touched
     2. `lifecycle_mark` declares what it writes, allocates the record in
        `attach`, and sits AFTER `action_relay` so a firing reaches the game
        before the body that fired it is declared gone
     3. `despawn_on` marks on the named action and does NOT mark on a
        different one, nor on a quiet frame
     4. `lifetime_ms` marks when it elapses and does NOT mark before, and 0
        means the body never dies of old age
     5. THE LOAD-BEARING HALF: after `SceneManager.despawn` the entity queues
        ZERO blit tokens on the next frame -- and after `scene.unbind` ALONE
        it still queues them, which is the negative control that proves this
        section can fail
     6. `reap()` removes every marked body in one pass, including adjacent
        ones -- a live-list walk would remove alternate ones and look fine
     7. `LayerRenderer.unbind` answers False for something it never held, and
        removes by IDENTITY rather than by `==`
     8. `SceneManager.spawn` constructs, PLACES, composes and binds through
        the same reader a map-spawned object goes through -- and asks for the
        scene FIRST, so a manager with none has built nothing when it raises
     9. despawn is idempotent, and a body marked, reaped and asked again says
        it is gone
    10. despawn is the THIRD removal too: a map-spawned body's row in
        `renderer.spawned_entities` goes with it, its neighbour's stays, and
        the resurrection that list could cause is measured to be unreachable

EVERY ASSERTION IS A PAIR
-------------------------
A gate proved to let something through and never proved to stop it is the
commonest toothless shape here, so each rule above is written as two
assertions with opposite expectations. The ones that matter most are marked
BOTH HALVES in the source, and the mutation table at the end records what
each one turned red for.

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
`data/maps/starter.tmx` is the shipped map and is never read here. The probe
entity, the probe spawn-registry entry, the whole scene and the two-object
map section 10 needs are built here -- the map into a tempdir; nothing in
this file asserts what any shipped map contains.

    .venv/Scripts/python.exe tools/check_lifecycle.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import inspect
import os
import sys
import tempfile

import pygame

pygame.init()
SCREEN = pygame.display.set_mode((128, 128))

import pytmx

from scripts.core import blitpool
from scripts.core.errors import PyoneerConfigError, PyoneerSceneError
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.renderer import EntityLayer, LayerRenderer
from scripts.core.scene.game_scene import GameScene
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.spawn import SPAWN_REGISTRY, register as register_spawn
from scripts.game.behavior import BEHAVIOR_REGISTRY, build, read_requests
from scripts.game.behavior.action import ACTION_RELAY, ActionFired, ActionIntent
from scripts.game.behavior.base import BEHAVIORS, PARAM_PREFIX
from scripts.game.behavior.lifecycle import (LIFECYCLE_MARK, ORDER,
                                             GameLifecycleMarkBehavior)
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.registry import describe_all
from scripts.game.behavior.state import (LIFE_ALIVE, LIFE_GONE, LIVES,
                                         BodyState, state_of)
from scripts.game.entity.game_entity import GameEntity
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
"""One frame's delta in ENGINE units. `MS_PER_DELTA` of these is one ms x 60.

Chosen as 1.0 and never as "a frame at 60fps", because the whole point of the
conversion is that delta is not seconds and not milliseconds. One delta unit
is `MS_PER_DELTA` = 60 milliseconds, so a 300ms lifetime is exactly five of
these -- derived below rather than typed, so retuning the tick rate moves the
expectation instead of turning this check red for the wrong reason.
"""


class Probe(GameEntity):
    """The smallest entity that is constructible, drawable and countable.

    Three gaps in `GameEntity`, each deliberate there and each in the way
    here. It is an ABC with two abstract methods, so it cannot be instantiated
    at all. It computes no `image` -- only `GameAnimatedEntity` does -- and the
    render path SKIPS an entity with no image, which is indistinguishable from
    an unbound one, so an 8x8 block is set. And `core_frame_update` drives
    behaviors and reports nothing, so the updates are counted: that count is
    the only externally visible difference between an entity the scene drives
    and one that merely draws.

    `GamePlayer` is the real registry entry and is not used, because it needs
    a spritesheet this repository deliberately does not ship.
    """

    def __init__(self, tint=(0, 200, 0), **kwargs):
        super().__init__(**kwargs)
        self.updates = 0
        block = pygame.Surface((8, 8))
        block.fill(tint)
        self._image = block

    @property
    def image(self):
        return self._image

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, event=None):
        pass

    def core_frame_update(self, event=None):
        self.updates += 1
        super().core_frame_update(event)


class Suicidal(Probe):
    """A probe that unbinds ITSELF from inside its own update.

    Not a thing any behavior in this engine is allowed to do -- it is the
    reason `lifecycle_mark` marks rather than removes -- and it is built here
    to MEASURE the cost rather than to assert it as correct. See section 6.
    """

    def __init__(self, scene, bucket, **kwargs):
        super().__init__(**kwargs)
        self.scene = scene
        self.bucket = bucket

    def core_frame_update(self, event=None):
        super().core_frame_update(event)
        self.scene.unbind(self.bucket, self)


class Widget:
    """A stand-in `GameComponent` for the renderer's other unbind path.

    A real `GameComponent` would work and would drag the theme config in; what
    is under test is that `LayerRenderer.unbind` finds a `GameComponentLayer`
    at all, and the layer holds whatever it was given.
    """

    def __init__(self, name):
        self.name = name


def frame(entity, delta=DELTA):
    """One `core_frame_update` with a real per-object event, as the scene builds it."""
    entity.core_frame_update(PyoneerEvent(GameEventType.UPDATE, sender=None,
                                          data={"delta": delta}))


def build_manager():
    """A real SceneManager with a real renderer, a camera and an empty scene."""
    renderer = LayerRenderer(SCREEN)
    renderer.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                    pygame.Rect(0, 0, 128, 128), scale=1))
    manager = SceneManager(game=None)
    manager.add_scene("probe", GameScene("probe"))
    manager.set_scene("probe")
    manager.bind(0, renderer)              # the LayerRenderer branch of bind
    return manager, renderer


def blit_senders(renderer):
    """Every blit token one `render()` queues, as (depth, sender object).

    The tokens are rebuilt from `EntityLayer.entities` every frame and dropped
    with the pool -- `BlitPool.get_blit_pool_pygame(clear=True)` empties
    `ORGANIZED_BLITS` -- so this is a measurement of what the layer PRODUCES
    now, not of what leaked from before.
    """
    captured = []
    original = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def spy(clear: bool = True):
        for depth in sorted(blitpool.ORGANIZED_BLITS):
            for priority in sorted(blitpool.ORGANIZED_BLITS[depth]):
                for token in blitpool.ORGANIZED_BLITS[depth][priority]:
                    captured.append((depth, token.sender))
        return original(clear)

    blitpool.BlitPool.get_blit_pool_pygame = spy
    try:
        renderer.render()
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return captured


def tokens_for(renderer, entity):
    return sum(1 for _depth, sender in blit_senders(renderer) if sender is entity)


register_spawn("LifecycleProbe", Probe)

BUILDS: list[int] = []


class Counted(Probe):
    """A probe that records the fact of its own construction.

    Section 8's scene guard is the only reason this exists. `spawn` and the
    `bind` at the bottom of it BOTH refuse a manager with no scene and both
    raise the same `PyoneerSceneError`, so "it raises" passes with the guard
    at either end. What tells them apart is whether the entity was built on
    the way to the raise, and only the object itself can report that.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        BUILDS.append(1)


register_spawn("CountedProbe", Counted)


# The fixture map for section 10, written to a tempdir. Two objects, because
# the claim under test is that despawning one forgets ONE record; with a
# single object "the list is empty afterwards" passes for a method that
# clears it. No tile layers: what is under test is the object path.
FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="8" height="8" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="3" nextobjectid="4">
 <objectgroup id="1" name="entity">
  <object id="1" name="first" type="LifecycleProbe" x="16" y="16" width="16" height="16"/>
  <object id="2" name="second" type="LifecycleProbe" x="48" y="48" width="16" height="16"/>
 </objectgroup>
</map>
"""

FIXTURE_PATH = os.path.join(tempfile.mkdtemp(prefix="pyoneer_lifecycle_"),
                            "lifecycle.tmx")
with open(FIXTURE_PATH, "w", encoding="utf-8", newline="\n") as _handle:
    _handle.write(FIXTURE)


def load_fixture_map():
    return GameMap(pytmx.load_pygame(FIXTURE_PATH))


# ===========================================================================
print("\n1. the `life` axis is closed, and defaults to alive")
# ===========================================================================
_fresh = BodyState()
expect("a record nobody has touched is alive", _fresh.life, LIFE_ALIVE)
expect("...and `gone` is the reaper's question, spelled once", _fresh.gone, False)
expect("the vocabulary is exactly two values", LIVES, (LIFE_ALIVE, LIFE_GONE))
expect("`life` is on the axes map, so it reaches the generated doc",
       "life" in BodyState().axes, True)

# BOTH HALVES of the closed set. The legal value assigns; anything else raises
# AT THE WRITE, which is the whole reason it is a property and not a slot --
# the reaper's test is `== LIFE_GONE`, so a typo'd value is a body that was
# declared dead and is then never removed.
expect_no_raise("assigning the legal 'gone' works",
                lambda: setattr(BodyState(), "life", LIFE_GONE))
expect_no_raise("assigning back to 'alive' works too",
                lambda: setattr(BodyState(), "life", LIFE_ALIVE))
expect_raises("assigning an unknown value raises, naming it and the set",
              PyoneerConfigError,
              lambda: setattr(BodyState(), "life", "dead"),
              "'dead'", "'alive'", "'gone'")
expect_raises("...and a plausible near-miss raises the same way",
              PyoneerConfigError,
              lambda: setattr(BodyState(), "life", "GONE"), "'GONE'")
expect_raises("...and so does a non-string", PyoneerConfigError,
              lambda: setattr(BodyState(), "life", None), "None")
_marked = BodyState()
_marked.life = LIFE_GONE
expect("a marked record reports gone through both spellings",
       (_marked.life, _marked.gone), (LIFE_GONE, True))
expect("`__slots__` refuses a misspelled axis, so a typo cannot create a field",
       "life" in BodyState.__slots__ or "_life" in BodyState.__slots__, True)
expect_raises("...proved: assigning a misspelled axis raises AttributeError",
              AttributeError, lambda: setattr(BodyState(), "lfie", "gone"),
              "lfie")

# The axis has to be DESCRIBED where the writes column is read, or the column
# names `state.life` to a reader with no way to learn what it means. The
# generator renders "**undocumented**" for an axis with no sentence, so both
# halves are visible in one string.
_doc = describe_all()
expect("the generated doc carries a row for `state.life`",
       "| `state.life` |" in _doc, True)
expect("...and that row is not the undocumented placeholder",
       "| `state.life` | **undocumented**" in _doc, False)


# ===========================================================================
print("\n2. `lifecycle_mark` declares what it writes, and runs last")
# ===========================================================================
expect("it is registered under its token",
       BEHAVIOR_REGISTRY.get("lifecycle_mark") is LIFECYCLE_MARK, True)
expect("...and declares the one axis it writes", LIFECYCLE_MARK.writes,
       ("state.life",))
expect("...and requires nothing, because a lifetime-only body has no actions",
       LIFECYCLE_MARK.requires, ())
expect("...and is live: SceneManager.reap() is the engine-side reader",
       LIFECYCLE_MARK.status, "live")
expect("...and implements attach and update, read off the class",
       LIFECYCLE_MARK.hooks, ("attach", "update"))
expect("...and reaches the event bus at zero declared points",
       LIFECYCLE_MARK.binds, ())

# The ORDER claim with teeth: it is not "95", it is "after the relay". A
# firing must reach the game's router while the entity is still whole, so a
# pickup can open a window on the frame it is collected.
expect("it runs AFTER action_relay, so a firing gets out before the mark",
       ORDER > ACTION_RELAY.order, True)
expect("...stated as the numbers, so a moved relay is visible here",
       (LIFECYCLE_MARK.order, ACTION_RELAY.order), (95, 90))

# BOTH HALVES of the allocate-in-attach contract: an entity that has never
# been attached to has no record, and attaching creates one.
_bare = Probe()
expect("a bare entity carries no BodyState", state_of(_bare) is None, True)
_bare.behaviors.attach_all(build(read_requests({BEHAVIORS: "lifecycle_mark"})))
expect("...and attaching lifecycle_mark allocates one, alive",
       (state_of(_bare) is not None, state_of(_bare).life), (True, LIFE_ALIVE))

# The constructor refuses the two lifetimes that would be lies.
expect_raises("a negative lifetime raises rather than killing on frame one",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(lifetime_ms=-1), "-1", "0")
expect_raises("...and a boolean raises, because in Python True is an int",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(lifetime_ms=True), "bool")
expect_raises("...and an untyped tmx property (a string) raises, naming str",
              PyoneerConfigError,
              lambda: GameLifecycleMarkBehavior(lifetime_ms="500"), "str")
expect_no_raise("...and 0 is legal: it means no lifetime",
                lambda: GameLifecycleMarkBehavior(lifetime_ms=0))


# ===========================================================================
print("\n3. `despawn_on`: the named action marks, and nothing else does")
# ===========================================================================
def marked_after(fired_names, despawn_on="interact_action", frames=1):
    """Drive a body carrying `lifecycle_mark` with a pre-filled action record."""
    body = Probe()
    body.action_intent = ActionIntent()
    behavior = GameLifecycleMarkBehavior(despawn_on=despawn_on)
    behavior.spec = LIFECYCLE_MARK
    body.behaviors.attach(behavior)
    for name in fired_names:
        body.action_intent.record(name, ActionFired(name=name, verb="probe"))
    for _ in range(frames):
        frame(body)
    return state_of(body).gone


# BOTH HALVES. The named action marks; a DIFFERENT action does not, and that
# second half is the one that fails if the behavior ever reads
# `len(actions_of(entity))` instead of the named slot.
expect("the named action marks the body gone",
       marked_after(["interact_action"]), True)
expect("...a different action does NOT mark it",
       marked_after(["attack_action"]), False)
expect("...and a quiet frame does not either", marked_after([]), False)
expect("...even after a hundred quiet frames",
       marked_after([], frames=100), False)
expect("a body with the token and NO despawn_on never dies of an action",
       marked_after(["interact_action"], despawn_on=""), False)

# The record an entity with no action behavior reads is the shared inert one,
# which reports that nothing ever fired -- so a mis-declared token is a body
# that simply never dies rather than a crash. That is why `requires` is empty.
_no_actions = Probe()
_no_actions.behaviors.attach_all(build(read_requests(
    {BEHAVIORS: "lifecycle_mark",
     PARAM_PREFIX + "despawn_on": "interact_action"})))
for _ in range(20):
    frame(_no_actions)
expect("a body with no action behavior at all is quiet, not broken",
       state_of(_no_actions).gone, False)


# ===========================================================================
print("\n4. `lifetime_ms`: elapsed marks, not-yet does not, 0 never does")
# ===========================================================================
LIFETIME = 300
FRAMES_TO_DIE = int(LIFETIME / MS_PER_DELTA)   # derived, never typed twice
expect("the fixture's lifetime is a whole number of frames at this tick rate",
       FRAMES_TO_DIE * MS_PER_DELTA, float(LIFETIME))


def aged(frames, lifetime_ms=LIFETIME):
    body = Probe()
    behavior = GameLifecycleMarkBehavior(lifetime_ms=lifetime_ms)
    behavior.spec = LIFECYCLE_MARK
    body.behaviors.attach(behavior)
    for _ in range(frames):
        frame(body)
    return state_of(body).gone, behavior


# BOTH HALVES of the clock: one frame short is still alive, and the exact
# frame it elapses is not. A `>` written as `>=` or a conversion left out
# breaks exactly one of these two.
expect("one frame before the lifetime elapses the body is alive",
       aged(FRAMES_TO_DIE - 1)[0], False)
expect("...and on the frame it elapses it is gone", aged(FRAMES_TO_DIE)[0], True)
expect("...and it stays gone", aged(FRAMES_TO_DIE + 10)[0], True)
expect("lifetime_ms=0 means no lifetime, over two hundred frames",
       aged(200, lifetime_ms=0)[0], False)

_gone, _behavior = aged(FRAMES_TO_DIE + 10)
expect("the age STOPS at the mark rather than running on",
       _behavior.age_ms, float(LIFETIME))
expect("...and `remaining_ms` reads zero there", _behavior.remaining_ms, 0.0)
_alive, _young = aged(1, lifetime_ms=0)
expect("with no lifetime, `remaining_ms` is infinite rather than zero",
       _young.remaining_ms, float("inf"))
expect("...and the age still ticks, in MILLISECONDS not delta units",
       _young.age_ms, MS_PER_DELTA)


# ===========================================================================
print("\n5. the load-bearing half: a despawned entity queues NO blit tokens")
# ===========================================================================
manager, renderer = build_manager()
victim = Probe(tint=(200, 0, 0))
bystander = Probe(tint=(0, 0, 200))
manager.bind(50, victim)
manager.bind(50, bystander)
victim.moveto((10.0, 10.0))
bystander.moveto((30.0, 30.0))

expect("both bound entities queue a token on the first frame",
       (tokens_for(renderer, victim), tokens_for(renderer, bystander)), (1, 1))

# THE NEGATIVE CONTROL, and it is the assertion that proves this whole section
# can fail. `scene.unbind` alone stops the object UPDATING and leaves it
# DRAWING, forever, because the tokens are rebuilt from EntityLayer.entities.
# It runs on its own manager, because `bind` does not de-duplicate: rebinding
# the same entity afterwards would put it in the EntityLayer a SECOND time and
# every count below would be off by one.
control_manager, control_renderer = build_manager()
leaker = Probe(tint=(200, 200, 0))
control_manager.bind(50, leaker)
expect("the control entity draws while bound", tokens_for(control_renderer, leaker), 1)
control_manager.current_scene.unbind(50, leaker)
expect("scene.unbind ALONE takes it out of the scene...",
       [obj for _b, obj in control_manager.current_scene.contents()], [])
expect("...and does NOT stop the blit tokens -- the leak this pass closes",
       tokens_for(control_renderer, leaker), 1)
expect("...on every subsequent frame, forever",
       tokens_for(control_renderer, leaker), 1)

# The real thing: both removals, one call.
expect("despawn reports that it removed something",
       manager.despawn(victim), True)
expect("...the entity queues ZERO tokens on the next frame",
       tokens_for(renderer, victim), 0)
expect("...and the bystander is untouched, so this was not a mass clear",
       tokens_for(renderer, bystander), 1)
expect("...and the scene no longer holds it either",
       [obj for _b, obj in manager.current_scene.contents() if obj is victim], [])
expect("...and its record says gone, whichever end the removal started from",
       state_of(victim).gone if state_of(victim) else "no record", "no record")

# A despawned entity is not driven any more. Both halves, because "it stopped
# drawing" and "it stopped updating" are two different leaks.
_before = bystander.updates
manager.update(DELTA)
expect("the bystander still updates after its neighbour was despawned",
       bystander.updates > _before, True)

# BOTH HALVES of idempotence.
expect("despawning it again reports that there was nothing to remove",
       manager.despawn(victim), False)
expect("...and despawning something never bound reports the same",
       manager.despawn(Probe()), False)


# ===========================================================================
print("\n6. reap() removes every marked body in ONE pass, adjacent included")
# ===========================================================================
manager, renderer = build_manager()
crowd = [Probe() for _ in range(6)]
for probe in crowd:
    manager.bind(50, probe)
    # `lifecycle_mark` is not needed to mark: writing the axis IS the despawn
    # request, and that is the seam. The behavior is one authorable writer of
    # it, checked in sections 3 and 4.
    from scripts.game.behavior.state import ensure_state
    ensure_state(probe).life = LIFE_GONE

# The negative control FIRST, on a throwaway scene: a reaper that walks the
# LIVE bucket instead of a snapshot removes alternate entries and looks like
# it worked. Six marked bodies, three removed.
naive_scene = GameScene("naive")
naive = [Probe() for _ in range(6)]
for probe in naive:
    naive_scene.bind(50, probe)
_bucket = naive_scene._GameScene__game_objects[50]
for held in _bucket:                       # the mistake, made on purpose
    _bucket.remove(held)
expect("a live-list walk removes only half of six, and reports success",
       len(_bucket), 3)

reaped = manager.reap()
expect("reap() returns every body it took", len(reaped), 6)
expect("...and the scene is empty afterwards, not half empty",
       len(manager.current_scene.contents()), 0)
expect("...and none of the six queues a blit token",
       sum(tokens_for(renderer, probe) for probe in crowd), 0)

# BOTH HALVES: an unmarked body survives a reap that removes its neighbours.
manager, renderer = build_manager()
from scripts.game.behavior.state import ensure_state
doomed, survivor = Probe(), Probe()
manager.bind(50, doomed)
manager.bind(50, survivor)
ensure_state(doomed).life = LIFE_GONE
ensure_state(survivor)                     # alive, and carrying a record
expect("reap takes the marked body", len(manager.reap()), 1)
expect("...and leaves the unmarked one bound",
       [obj for _b, obj in manager.current_scene.contents()], [survivor])
expect("...still drawing", tokens_for(renderer, survivor), 1)
expect("...and a second reap finds nothing to do", manager.reap(), ())

# An object with NO state record is never reaped. That is what keeps a map, a
# UI component and a bare crate bound. Bound straight onto the scene, because
# `SceneManager.bind` routes into the renderer too and `LayerRenderer.bind`
# correctly refuses a type it has no binder for.
manager.current_scene.bind(50, Widget("chrome"))
expect("an object carrying no BodyState is never reaped", manager.reap(), ())
expect("...and is still bound", len(manager.current_scene.contents()), 2)

# reap() is driven by the frame loop, after the fan-out. Read off the source
# rather than asserted as a comment: the ORDER is the reason a mark is safe.
_post = inspect.getsource(SceneManager.post_update)
expect("post_update calls reap()", "self.reap()" in _post, True)
expect("...after the scene's post-update fan-out has returned",
       _post.index("core_frame_update_post") < _post.index("self.reap()"), True)

# THE MEASUREMENT THAT JUSTIFIES MARKING RATHER THAN REMOVING. An object that
# unbinds itself from inside its own update makes the fan-out skip its
# neighbour. This is recorded as the cost of the alternative, on a fixture
# built for it -- no behavior in the engine does this.
skip_scene = GameScene("skip")
a = Suicidal(skip_scene, 50)
b, c = Probe(), Probe()
for obj in (a, b, c):
    skip_scene.bind(50, obj)
skip_scene.core_frame_update(DELTA)
expect("self-removal mid-fan-out SKIPS the next sibling (why marking exists)",
       (a.updates, b.updates, c.updates), (1, 0, 1))


# ===========================================================================
print("\n7. LayerRenderer.unbind: both directions, and by identity")
# ===========================================================================
manager, renderer = build_manager()
held, never = Probe(), Probe()
manager.bind(50, held)
expect("unbind removes something the renderer holds", renderer.unbind(held), True)
expect("...and answers False the second time", renderer.unbind(held), False)
expect("...and False for an entity it never held", renderer.unbind(never), False)
expect("...and False for an object of a type it cannot hold",
       renderer.unbind(Widget("stray")), False)


class Equal(Probe):
    """Two of these compare equal and are different objects.

    `list.remove` uses `==`. If `unbind` used it, removing one of these would
    take the OTHER out of the layer -- and the symptom is the wrong sprite
    vanishing, which nobody traces back to a comparison operator.
    """

    def __eq__(self, other):
        return isinstance(other, Equal)

    def __hash__(self):
        return 7


manager, renderer = build_manager()
twin_a, twin_b = Equal(), Equal()
manager.bind(50, twin_a)
manager.bind(50, twin_b)
expect("the two fixtures really do compare equal", twin_a == twin_b, True)
renderer.unbind(twin_b)
_layer = [l for layers in renderer.layers.values() for l in layers
          if isinstance(l, EntityLayer)][0]
expect("unbinding one leaves the OTHER, by identity",
       [e is twin_a for e in _layer.entities], [True])
expect("...and the removed one really is gone",
       any(e is twin_b for e in _layer.entities), False)

# The same identity rule on the scene side.
scene = GameScene("identity")
scene.bind(50, twin_a)
scene.bind(50, twin_b)
expect("scene.discard returns the bucket it found the object in",
       scene.discard(twin_b), 50)
expect("...and left the equal-but-different sibling",
       [obj is twin_a for _b, obj in scene.contents()], [True])
expect("...and answers None for something it does not hold",
       scene.discard(Probe()), None)
expect_no_raise("scene.unbind tolerates an object the bucket does not hold",
                lambda: scene.unbind(50, Probe()))
expect_no_raise("...and a bucket that does not exist",
                lambda: scene.unbind("nowhere", twin_a))
expect("...and still removes one it does hold",
       (scene.unbind(50, twin_a), len(scene.contents())), (None, 0))

# `contents()` is a SNAPSHOT: that is what makes despawning inside the reap
# loop safe by construction rather than by care.
scene = GameScene("snapshot")
for probe in (Probe(), Probe(), Probe()):
    scene.bind(50, probe)
snapshot = scene.contents()
scene.discard(snapshot[0][1])
expect("a snapshot taken before a removal still lists three", len(snapshot), 3)
expect("...while the scene itself now holds two", len(scene.contents()), 2)


# ===========================================================================
print("\n8. SceneManager.spawn: construct, PLACE, compose, bind")
# ===========================================================================
manager, renderer = build_manager()
spawned = manager.spawn("LifecycleProbe", (24.0, 40.0), properties={
    BEHAVIORS: "lifecycle_mark",
    PARAM_PREFIX + "lifetime_ms": 300,
})
expect("it built the registered class", type(spawned) is Probe, True)
# The PLACE half. `GameEntity.__init__` accepts a `transform` keyword and
# THROWS IT AWAY, so an entity that is not moved after construction sits at
# (0, 0) -- and (0, 0) is a plausible-looking position, which is why this is
# asserted rather than assumed.
expect("...at the position it was asked for, not at the origin",
       (spawned.transform.position.x, spawned.transform.position.y), (24.0, 40.0))
expect("...composed through the same reader a tmx object goes through",
       spawned.behaviors.names, ("lifecycle_mark",))
expect("...with the parameter resolved from the tmx-shaped property",
       spawned.behaviors.get("lifecycle_mark").lifetime_ms, 300)
expect("...bound into the scene", [obj is spawned for _b, obj
                                   in manager.current_scene.contents()], [True])
expect("...and into the renderer, drawing", tokens_for(renderer, spawned), 1)
expect("...and handed the scene's action router as its sink",
       spawned.action_sink is manager.actions, True)

# The depth ladder is resolved by `scripts.core.spawn.resolve_depth` and not
# by a second copy here. BOTH HALVES: the default, and an authored override.
placed = manager.spawn("LifecycleProbe", (0.0, 0.0),
                       properties={"pyoneer_depth": 77})
_depths = {depth for depth, layers in renderer.layers.items()
           for layer in layers if isinstance(layer, EntityLayer)
           and any(e is placed for e in layer.entities)}
expect("an authored pyoneer_depth is honoured", _depths, {77})
expect("...and the default is the object depth, not 77",
       [d for d, layers in renderer.layers.items() for layer in layers
        if isinstance(layer, EntityLayer)
        and any(e is spawned for e in layer.entities)], [50])
expect_raises("an unregistered type raises rather than spawning nothing",
              Exception, lambda: manager.spawn("NotAThing"), "NotAThing")

# THE SCENE IS ASKED FOR FIRST, AND THE COUNTER IS THE TEETH. `bind` carries
# the same guard and raises the same exception CLASS from the bottom of
# `spawn`, so asserting only that it raises passes wherever the guard sits.
# With it at the bottom the entity is constructed, moved and fully composed --
# every `attach` hook has run, which is where a behavior audits what it needs
# -- before the caller hears about the missing scene. The message is the
# second half of the teeth: from `bind` it reads `bind Counted into`, naming
# the class the registry built, where the author typed `CountedProbe`.
sceneless = SceneManager(game=None)
expect("no probe has been built through this registry entry yet", len(BUILDS), 0)
expect_raises("spawn with no scene raises, naming the TYPE and the fix",
              PyoneerSceneError,
              lambda: sceneless.spawn("CountedProbe", (3.0, 4.0), properties={
                  BEHAVIORS: "lifecycle_mark"}),
              "CountedProbe", "set_scene()")
expect("...and it constructed NOTHING on the way to that raise", len(BUILDS), 0)

# The other half, and it is what stops the guard being written as an
# unconditional raise: the identical call on a manager WITH a scene builds.
counted_manager, _counted_renderer = build_manager()
_counted = counted_manager.spawn("CountedProbe", (3.0, 4.0), properties={
    BEHAVIORS: "lifecycle_mark"})
expect("...while the same call on a manager WITH a scene builds exactly one",
       len(BUILDS), 1)
expect("...placed and composed as usual",
       (_counted.transform.position.x, _counted.behaviors.names),
       (3.0, ("lifecycle_mark",)))

# `bind`'s own guard is still the general one, and still refuses. BOTH HALVES:
# a bindable game object needs a scene, and the two objects that are bound
# INTO the manager rather than into a scene do not.
expect_raises("bind on a scene-less manager still raises, naming the object",
              PyoneerSceneError,
              lambda: SceneManager(game=None).bind(50, Probe()),
              "Probe", "set_scene()")
expect_no_raise("...while binding a renderer needs no scene at all",
                lambda: SceneManager(game=None).bind(0, LayerRenderer(SCREEN)))

# The whole round trip, which is what "dynamic creation/destruction" means:
# spawn a body with a lifetime, drive frames through the real frame path, and
# find it gone with no further code.
manager, renderer = build_manager()
short = manager.spawn("LifecycleProbe", (8.0, 8.0), properties={
    BEHAVIORS: "lifecycle_mark",
    PARAM_PREFIX + "lifetime_ms": 300,
})
expect("the spawned body draws before its lifetime elapses",
       tokens_for(renderer, short), 1)
for _ in range(FRAMES_TO_DIE - 1):
    manager.update(DELTA)
    manager.post_update(DELTA)
expect("...one frame short of its lifetime it is still bound and drawing",
       (len(manager.current_scene.contents()), tokens_for(renderer, short)),
       (1, 1))
manager.update(DELTA)
manager.post_update(DELTA)
expect("...and on the frame it elapses it is gone from the scene",
       len(manager.current_scene.contents()), 0)
expect("...and queues no blit token", tokens_for(renderer, short), 0)


# ===========================================================================
print("\n9. teardown: the behaviors let go, and the record agrees")
# ===========================================================================
manager, renderer = build_manager()
composed = manager.spawn("LifecycleProbe", (0.0, 0.0), properties={
    BEHAVIORS: "interact_action,action_relay,lifecycle_mark",
})
expect("it is composed of three behaviors, in declared order",
       composed.behaviors.names,
       ("interact_action", "action_relay", "lifecycle_mark"))
expect("...and the action slot is allocated",
       composed.action_intent.slots, ("interact_action",))
manager.despawn(composed)
expect("despawn detaches every behavior", composed.behaviors.names, ())
expect("...and the action behavior released its slot on the way out",
       composed.action_intent.slots, ())
expect("...and the record reports gone", state_of(composed).life, LIFE_GONE)
expect("...and `core_lifecycle_dispose` was NOT given a first caller here",
       inspect.getsource(GameEntity.core_lifecycle_dispose).strip().endswith("pass"),
       True)

# BOTH HALVES of the detach: a body that is NOT despawned keeps its behaviors.
kept = manager.spawn("LifecycleProbe", (0.0, 0.0),
                     properties={BEHAVIORS: "lifecycle_mark"})
manager.reap()
expect("a reap that does not touch a body leaves its behaviors attached",
       kept.behaviors.names, ("lifecycle_mark",))


# ===========================================================================
print("\n10. the THIRD removal: the map's own spawn record is forgotten")
# ===========================================================================
# `renderer.spawned_entities` is a list the map bind writes and
# `SceneManager.__bind_spawned_entities` reads. `LayerRenderer.unbind` empties
# the LAYER and never touches it, so without a third removal a reaped body
# stays reachable from the renderer for as long as the map is bound. Sections
# 5 and 6 cannot see that: they bind by hand, and a hand-bound entity has no
# record.
map_manager, map_renderer = build_manager()
map_manager.bind("MAP", load_fixture_map())
_records = map_renderer.spawned_entities
expect("the fixture map spawned two bodies, in document order", len(_records), 2)
first_body, second_body = _records[0].entity, _records[1].entity
expect("...and both draw", (tokens_for(map_renderer, first_body),
                            tokens_for(map_renderer, second_body)), (1, 1))

# BOTH HALVES, and the second is the shape this repo keeps finding missing: a
# removal proved to remove and never proved to leave the neighbours alone. A
# `spawned_entities.clear()` passes the first assertion and fails the second.
expect("despawn reports it removed the first", map_manager.despawn(first_body),
       True)
expect("...and the renderer no longer holds a RECORD for it",
       any(r.entity is first_body for r in map_renderer.spawned_entities), False)
expect("...while the neighbour's record is untouched",
       any(r.entity is second_body for r in map_renderer.spawned_entities), True)
expect("...so exactly one row went, and the list is not cleared",
       len(map_renderer.spawned_entities), 1)
expect("...and the neighbour is still bound and drawing",
       (len([obj for _b, obj in map_manager.current_scene.contents()
             if obj is second_body]), tokens_for(map_renderer, second_body)),
       (1, 1))
expect("...and despawning the first again reports nothing to remove",
       map_manager.despawn(first_body), False)

# The record is its own removal CHANNEL, which is why the forget runs before
# the early return rather than after it. A caller that unbound a body by hand
# has left a record with no call that would take it out; despawn is that call,
# and it reports True for the record alone.
map_renderer.unbind(second_body)
map_manager.current_scene.discard(second_body)
expect("a body unbound by hand still has its spawn record",
       any(r.entity is second_body for r in map_renderer.spawned_entities), True)
expect("...and despawn reports True for the record alone",
       map_manager.despawn(second_body), True)
expect("...leaving the list empty", map_renderer.spawned_entities, [])
expect("...and a manager with no renderer at all despawns without raising",
       SceneManager(game=None).despawn(Probe()), False)

# THE RESURRECTION IS NOT REACHABLE, and this is where that is measured rather
# than assumed. `__bind_spawned_entities` would re-bind anything in the list,
# but `LayerRenderer.__prepare_entity_layers` REBINDS `spawned_entities` to a
# freshly spawned list on every map bind and `SceneManager.bind` only reaches
# `__bind_spawned_entities` behind `renderer.bind(GameMap)`, which is what
# runs it. An `extend` written there instead of an assignment is what this
# pair catches -- and it would resurrect a reaped body on the next map load.
again_manager, again_renderer = build_manager()
again_manager.bind("MAP", load_fixture_map())
ghost = again_renderer.spawned_entities[0].entity
again_manager.despawn(ghost)
again_manager.bind("MAP", load_fixture_map())
expect("re-binding a map REPLACES the record list rather than growing it",
       len(again_renderer.spawned_entities), 2)
expect("...so the despawned body is not among the records",
       any(r.entity is ghost for r in again_renderer.spawned_entities), False)
expect("...and is not re-bound into the scene either",
       any(obj is ghost for _b, obj in again_manager.current_scene.contents()),
       False)
_fresh_bodies = [r.entity for r in again_renderer.spawned_entities]
_bound = [obj for _b, obj in again_manager.current_scene.contents()]
expect("...while both freshly spawned bodies ARE bound",
       [any(obj is body for obj in _bound) for body in _fresh_bodies],
       [True, True])


# ===========================================================================
print("\n" + "=" * 74)
if failures:
    print(f"FAILED {len(failures)}:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"assertions             : {len(asserted)}")
print(f"registry at HEAD       : {len(BEHAVIOR_REGISTRY)} behavior(s)")
print(f"spawn registry         : {len(SPAWN_REGISTRY)} type(s)\n")
print("""OK -- entity control: a body declares itself gone, and is really removed.

MUTATIONS RUN, AND WHAT EACH ONE TURNED RED
  * `BodyState.life` setter's membership test deleted
        -> section 1: three "raises" assertions turn green-to-FAIL
  * `lifecycle.ORDER` moved from 95 to 85 (before action_relay)
        -> section 2: the after-the-relay pair fails
  * `lifecycle_mark.update`'s `self.despawn_on ==` test replaced by
    `len(actions_of(entity))`
        -> section 3: "a different action does NOT mark it" fails, and the
           four positive assertions all still pass
  * `0 < self.lifetime_ms <= self._age_ms` relaxed to `<=`
        -> section 4: "lifetime_ms=0 means no lifetime" fails
  * `event.data["delta"] * MS_PER_DELTA` written without the conversion
        -> section 4: the frame-before/frame-of pair fails
  * `LayerRenderer.unbind` deleted (despawn removes from the scene only)
        -> section 5: "ZERO tokens on the next frame" fails, while the
           negative control above it still passes -- which is exactly the
           state the engine was in before this pass
  * `GameScene.discard` removed from `despawn` (renderer only)
        -> section 5: "the scene no longer holds it" fails
  * `SceneManager.reap` walking `__game_objects` live instead of `contents()`
        -> section 6: six-in-one-pass fails at three
  * `reap()` moved from `post_update` into `update`
        -> section 6: the source-order assertion fails
  * `LayerRenderer.unbind` switched from `is` to `list.remove`
        -> section 7: the equal-but-different twins fail
  * `GameScene.unbind` restored to `list.remove` (raising on a miss)
        -> section 7: the two tolerance assertions fail
  * the `moveto` dropped from `SceneManager.spawn`
        -> section 8: the position pair fails at (0.0, 0.0)
  * `SceneManager.spawn`'s `__require_scene` call deleted (the guard left
    only at the bottom, in `bind`, which is where it was)
        -> section 8, FAILED 3, and the third one was not predicted:
             - "it constructed NOTHING on the way to that raise" got=1
             - "the same call WITH a scene builds exactly one" got=2, because
               the sceneless call had already built one
             - "spawn with no scene raises, naming the TYPE and the fix"
               (message lacks ['CountedProbe']) -- the error from `bind`
               names the CLASS, `Counted`, and the author typed the tmx TYPE.
               `expect_raises` checking fragments and not just the exception
               class is what catches that
  * `__require_scene` made an unconditional raise (`if True:`)
        -> the check DIES at section 5's first `manager.bind(50, victim)`
           with the traceback, which is the coarse half of the same pair
  * `behaviors.detach_all()` dropped from `despawn`
        -> section 9: the slot-release pair fails
  * `__forget_spawn_record` dropped from `despawn` (HEAD before this pass)
        -> section 10, FAILED 4: "the renderer no longer holds a RECORD for
           it", "exactly one row went", "despawn reports True for the record
           alone", "leaving the list empty". Every drawing and updating
           assertion in sections 5 and 6 still passes, which is why the leak
           survived them: a hand-bound entity has no record at all
  * `__forget_spawn_record` written as an unconditional `spawned_entities = []`
        -> section 10, FAILED 4, led by "the neighbour's record is untouched"
           -- while "the renderer no longer holds a RECORD for it" directly
           above it PASSES. That pair is the whole reason both halves are
           written: a removal proved to remove and never proved to leave the
           neighbours alone
  * `__forget_spawn_record` matching on `==` instead of `is`
        -> nothing here, and deliberately so: no entity in the tree defines
           `__eq__`. Section 7's `Equal` twins are the standing proof for the
           renderer's half of the same rule
  * `__forget_spawn_record` moved AFTER `despawn`'s early return
        -> section 10, FAILED 2: "despawn reports True for the record alone"
           and "leaving the list empty"
  * `LayerRenderer.__prepare_entity_layers` EXTENDING `spawned_entities`
    instead of assigning -- run as an in-memory wrapper, so renderer.py on
    disk was never edited
        -> section 10: "re-binding a map REPLACES the record list" fails at
           3. The other two of that trio still pass, and that is worth
           knowing: with the forget in place the ghost is already out of the
           list, so an `extend` no longer resurrects anything -- the COUNT is
           what catches it, and it is what would go red before a version of
           this engine without the forget resurrected a reaped body""")
