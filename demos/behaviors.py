"""`patrol_input`: a scripted producer of MoveIntent, registered from a GAME.

A movement behavior reads a `MoveIntent` and does not care what wrote it, so
a second producer at `order` 10 drives the same body without touching
`topdown_move`. This is that producer: it walks a fixed route on a clock. A
replay, a network peer or a real AI is the same shape with a different
`update`.

Registration happens at import time and from outside `scripts/`, which is
what makes `scripts.game.behavior.register` an extension point a game can use
without editing the engine's table. Import this module before a map carrying
the token is bound, or `resolve()` raises on an unknown token.

`patrol_input` and `player_input` share `order=10` and both declare
`writes=("intent",)`, so composing both onto one object raises at load
instead of letting one overwrite the other every frame. `conflicts` catches
the same pair earlier, with a message naming both tokens.
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
    and is not a player. The route is a comma-separated list of `MoveIntent`
    slot names -- the same vocabulary that reaches `GameEntity.move_direction`
    and the `{}` in `walk_{}`. A misspelled direction moves the entity zero
    pixels silently, so `attach` validates the route against `TOPDOWN_VERBS`
    and raises there instead.
    """

    def __init__(self, route: str = "right,left", leg_ms: int = 600):
        self.route = tuple(part.strip() for part in str(route).split(",")
                           if part.strip())
        self.leg_ms = int(leg_ms)
        self._elapsed = 0.0
        self._leg = 0

    def attach(self, entity: Any) -> None:
        """Allocate the intent, and refuse a route this vocabulary cannot walk.

        Refused at attach because the runtime failure is silent:
        `move_direction` has no `else` branch and displaces zero for a
        direction it does not know, which reads as a broken movement
        behavior rather than as a bad route.
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
        """Hand back a fresh, empty intent.

        A movement sibling left attached would otherwise keep reading the last
        intent published here and walk forever in that direction.
        """
        entity.intent = MoveIntent()

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        # event.data["delta"] is milliseconds / target_tick_rate, NOT seconds.
        # MS_PER_DELTA is imported rather than retyped so this cannot drift
        # from the tick rate the movement module is measured against.
        self._elapsed += event.data["delta"] * MS_PER_DELTA
        while self._elapsed >= self.leg_ms:
            self._elapsed -= self.leg_ms
            self._leg = (self._leg + 1) % len(self.route)
        intent = getattr(entity, "intent", None)
        if intent is None or intent is NO_INTENT:
            # The hand-constructed path: attach() always allocates one, and
            # NO_INTENT is the shared read-only sentinel, never written to.
            intent = entity.intent = MoveIntent()
        intent.clear()
        state = getattr(entity, "state", None)
        if state is not None and not state.can_move:
            # `can_move` is the cutscene freeze and a scripted body honours it:
            # "nothing moves right now" is about the world, not about who is
            # steering. `enabled_inputs` is NOT read here -- it means "wired to
            # a human's input", which a scripted body never is, so reading it
            # would freeze the patroller on some spawners and not others.
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
    # Nothing: it allocates the intent it writes. `requires` is reported and
    # never enforced, so naming an attribute it does not read would only make
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
