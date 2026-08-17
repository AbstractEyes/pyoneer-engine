"""`patrol_input`: a scripted producer of MoveIntent, registered from a GAME.

WHAT THIS PROVES, AND WHY IT LIVES IN demos/ RATHER THAN scripts/
------------------------------------------------------------------
`scripts/game/behavior/input.py` makes a claim in its docstring:

    "That split is also what lets a movement behavior be driven by something
    that is not a keyboard -- a replay, a network peer, an AI -- by attaching
    a different producer at `order` 10 and changing nothing else."

Nothing in the tree exercised it, so it was a claim about the design rather
than a fact about the code. This module is the second producer. It writes the
same `MoveIntent`, at the same order, and `topdown_move` -- which is not
modified, not subclassed and not aware this exists -- turns it into exactly
the same displacement.

It is registered from OUTSIDE `scripts/`, which is the second thing it
proves: `scripts.game.behavior.register` is a real extension point, and a
game adds a behavior without editing the engine's table. `register` is called
at import time, and `demos/patrol.py` imports this module before it boots --
which it must, because the token is resolved while the MAP is being bound.

THE ONE THING THAT MADE THIS HARDER THAN IT LOOKS
--------------------------------------------------
`player_input` and this both declare `order=10` and both declare
`writes=("intent",)`. `EntityBehaviors.attach` refuses two behaviors that
share an order AND write the same attribute, so composing both onto one
object raises at load rather than letting one silently overwrite the other
every frame. `conflicts` says the same thing a second time and earlier, with
a message that names both tokens. Both are deliberate: the writes rule is
what catches a behavior somebody adds later and forgets to declare against.

WHAT IT IS NOT
--------------
Not an AI, and not a pathfinder. It walks a fixed route on a clock, because
what is under test is the SEAM and a clever body would make the measurement
about the cleverness. A real AI producer is the same shape with a different
`update`.
"""
from __future__ import annotations

from typing import Any

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior import (NO_INTENT, BehaviorParam, BehaviorSpec,
                                   EntityBehavior, MoveIntent, register)
from scripts.game.behavior.movement import MS_PER_DELTA, TOPDOWN_VERBS


class GamePatrolInputBehavior(EntityBehavior):
    """Hold one direction at a time, on a clock, forever.

    Reads no input manager and needs none: an entity carrying this is driven
    and is not a player. The route is a comma-separated list of the same four
    direction verbs `topdown_move` polls, which is not a coincidence -- they
    are `MoveIntent`'s slot names, and those slot names are the vocabulary
    that reaches `GameEntity.move_direction` and the `{}` in `walk_{}`.
    Spelling one of them wrong here would move the entity zero pixels with no
    warning at all, so the route is validated in `attach` against
    `TOPDOWN_VERBS` and raises there instead.
    """

    def __init__(self, route: str = "right,left", leg_ms: int = 600):
        self.route = tuple(part.strip() for part in str(route).split(",")
                           if part.strip())
        self.leg_ms = int(leg_ms)
        self._elapsed = 0.0
        self._leg = 0

    def attach(self, entity: Any) -> None:
        """Allocate the intent, and refuse a route this vocabulary cannot walk.

        The same job `player_input.attach` does for verbs, for the same
        reason and with the opposite failure mode in mind: an unbound INPUT
        verb raises `KeyError` inside a frame, while an unknown DIRECTION is
        silent -- `move_direction` has no `else` branch and displaces zero.
        A silent producer looks like a broken movement behavior, so it is
        caught here where the mistake is.
        """
        if not self.route:
            raise PyoneerConfigError(
                "behavior 'patrol_input' on %s has an empty route, so it "
                "would publish an empty intent forever and the entity would "
                "look like it was never composed at all. Give it a route, "
                "e.g. route=\"right,left\"." % (type(entity).__name__,))
        unknown = [step for step in self.route if step not in TOPDOWN_VERBS]
        if unknown:
            raise PyoneerConfigError(
                "behavior 'patrol_input' on %s declares route step(s) %s, "
                "which are not MoveIntent directions. GameEntity."
                "move_direction has no else branch and moves ZERO pixels for "
                "a direction it does not know, with no warning, so this is "
                "refused here instead. Known: %s."
                % (type(entity).__name__, ", ".join(repr(u) for u in unknown),
                   ", ".join(TOPDOWN_VERBS)))
        if self.leg_ms <= 0:
            raise PyoneerConfigError(
                "behavior 'patrol_input' on %s declares leg_ms=%d; a leg of "
                "zero or less would advance the route every frame and hold no "
                "direction long enough to move." % (type(entity).__name__,
                                                    self.leg_ms))
        entity.intent = MoveIntent()

    def detach(self, entity: Any) -> None:
        """Hand back a fresh, empty intent -- `player_input.detach`'s reason.

        A movement sibling left attached would otherwise keep reading the last
        intent published here and walk forever in the direction the route
        happened to be holding.
        """
        entity.intent = MoveIntent()

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        # event.data["delta"] is milliseconds / target_tick_rate, NOT seconds.
        # MS_PER_DELTA is imported from the movement module rather than typed
        # again: tools/check_movement.py asserts that constant against
        # config/game.json, and a second copy here would drift the day the
        # tick rate is retuned -- silently, because a patrol that walks for
        # the wrong duration still looks like a patrol.
        self._elapsed += event.data["delta"] * MS_PER_DELTA
        while self._elapsed >= self.leg_ms:
            self._elapsed -= self.leg_ms
            self._leg = (self._leg + 1) % len(self.route)
        intent = getattr(entity, "intent", None)
        if intent is None or intent is NO_INTENT:
            # attach() always allocates one. This is the hand-constructed
            # path, and writing to NO_INTENT would raise rather than give
            # every intent-less entity on the map this route.
            intent = entity.intent = MoveIntent()
        intent.clear()
        state = getattr(entity, "state", None)
        if state is not None and not state.can_move:
            # `can_move` is the cutscene freeze, and a scripted body honours
            # it: "nothing moves right now" is about the world, not about who
            # is steering.
            #
            # `enabled_inputs` is deliberately NOT read here, because it means
            # "this entity is wired to a human's input" and a scripted body has
            # none to disable. NOTE the reason is not the one first written
            # beside this line: that claimed `GamePlayer.__init__` clears
            # `enabled_inputs` for every entity built with `input_=None`, so
            # honouring it would freeze the patroller permanently. Measured on
            # the live demo, the patroller's `enabled_inputs` is TRUE --
            # `game_player.py` clears it only when `input_` is falsy, and
            # `main.py`'s `spawn_arguments` hands the manager to EVERY
            # map-spawned GamePlayer, which DemoGame inherits. Honouring it
            # would therefore freeze the patroller only on maps whose spawner
            # happens not to, which is the worse bug of the two and the real
            # argument for not reading it. `tools/check_demos.py` pins both
            # halves.
            return
        setattr(intent, self.route[self._leg], True)


PATROL_INPUT = BehaviorSpec(
    name="patrol_input",
    summary="Walks a fixed route on a clock, publishing the same MoveIntent a "
            "keyboard would. The second producer at order 10.",
    factory=GamePatrolInputBehavior,
    params=(
        BehaviorParam("route", "route", "str", "right,left",
                      "Comma-separated MoveIntent directions, held one at a "
                      "time in order and then repeated. Only up, down, left "
                      "and right exist.", source="object"),
        BehaviorParam("leg_ms", "leg duration", "int", 600,
                      "Milliseconds to hold each step of the route.",
                      source="object"),
    ),
    writes=("intent",),
    # Nothing. It allocates the intent it writes, so there is no attribute an
    # entity has to already have -- and `requires` is reported, never
    # enforced, so naming something it does not actually read would only make
    # `missing_requirements()` lie.
    requires=(),
    conflicts=("player_input",),
    order=10,
    example='<property name="pyoneer_behaviors" '
            'value="patrol_input,topdown_move,animation_drive"/>\n'
            '<property name="pyoneer_param_route" value="right,down,left,up"/>',
)

register(PATROL_INPUT)

__all__ = ["PATROL_INPUT", "GamePatrolInputBehavior"]
