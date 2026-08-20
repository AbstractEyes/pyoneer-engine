"""Declaring a body GONE: the one authorable writer of the lifecycle axis.

`lifecycle_mark` writes `state.life = "gone"` when a named action fires or a
declared lifetime elapses, and does nothing else -- it does not unbind, does
not touch the renderer, frees nothing and does not know a scene exists.

MARKING AND REMOVING ARE TWO DIFFERENT JOBS
-------------------------------------------
`GameScene.core_frame_update` iterates its buckets raw, so a behavior that
removed its own entity would make the loop skip the next sibling: measured
with three objects `a, b, c` in one bucket where `a` unbinds itself, the frame
ran `['a', 'c']` and `b` never updated. Nothing raises and nothing warns.

So a behavior declares and `SceneManager.reap()` removes, once, after the
whole fan-out has returned. For the same reason the axis is not a `None` left
in the list: a null is a value every consumer has to guard.

ORDER 95
--------
After `action_relay` (90), so on the frame a pickup is collected the relay has
already handed the firing to the scene's `ActionRouter` -- a game can open a
window or add to an inventory from a body that is about to stop existing.

THE PARAMETERS ARE THE TRIGGER VOCABULARY'S WORDS
--------------------------------------------------
`despawn_on` names an ACTION TOKEN (`interact_action`), not an input verb --
the same distinction `ActionFired` draws between `name` and `verb`.
`lifetime_ms` is milliseconds, matching `cooldown_ms` here and in
`editor/core/map_events.py`. It is NOT delta units: `event.data["delta"]` is
milliseconds/60, and this module converts through `MS_PER_DELTA`.

WHY THE TOKEN IS AUDITED AT CONSTRUCTION AND NOT AT ATTACH
-----------------------------------------------------------
`update` reads `actions_of(entity).fired(self.despawn_on)`, and
`ActionIntent.fired` never raises on an unknown name -- so an unaudited
`despawn_on="interakt_action"` answers None forever and the body is silently
immortal, indistinguishable from the action never firing.

The audit runs in `__init__` against the REGISTRY, because the entity's
composed siblings are not available in time: `EntityBehaviors.attach_all`
attaches in the authored token order, so
`pyoneer_behaviors="lifecycle_mark,interact_action"` attaches this behavior
FIRST despite the orders 95 and 15, and a sibling check would refuse a legal
map over where the author put a comma.

What the registry answers is order-independent: does ANY registered behavior
write the slot this token names. It cannot answer whether THIS body carries
that action, so a body declaring `despawn_on` for an action it does not
compose is still immortal -- `ActionIntent.slots` reports that to anyone
holding the entity.
"""
from __future__ import annotations

from typing import Any

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.action import SLOT_PREFIX, actions_of
from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                        EntityBehavior)
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import LIFE_GONE, ensure_state

ORDER: int = 95
"""Where a body is declared gone: after the relay, last of everything."""


def _declared_action_tokens() -> tuple[str, ...]:
    """Every action slot the live registry has a declared writer for, sorted.

    Read off `BehaviorSpec.writes` rather than off token names, because the
    slot is what `actions_of(entity).fired()` is keyed by. A behavior that
    records no firing -- `action_relay` READS every one and writes none -- is
    not an answer to "which action ends this body", so it does not appear.
    Reading the declaration also audits against a game's own action specs.

    The registry is imported HERE and not at module scope: `registry` imports
    this module at the bottom of its own body, so a top-level import back is a
    cycle that resolves for `import registry` and raises ImportError for
    `import lifecycle`. Nothing constructs a behavior during import, so the
    table is whole by the time any caller reaches this.
    """
    from scripts.game.behavior.registry import BEHAVIOR_REGISTRY
    return tuple(sorted(
        write[len(SLOT_PREFIX):]
        for spec in BEHAVIOR_REGISTRY.values()
        for write in spec.writes
        if write.startswith(SLOT_PREFIX)))


class GameLifecycleMarkBehavior(EntityBehavior):
    """Write `state.life = gone` on a named action, or after a lifetime.

    Both triggers are optional and both may be declared together; the first
    one to fire wins and the second is then moot, because the mark is checked
    before either trigger is consulted and a body is never re-marked.

    Declaring the token with NEITHER parameter is legal and means "this body's
    life is written by game code": the behavior still allocates the record in
    `attach`, so `state_of(entity).life = LIFE_GONE` from anywhere is a
    complete despawn request. This class is one authorable writer, not the
    only way in.

    A NON-EMPTY `despawn_on` naming no registered action RAISES here, because
    an unaudited token is a silently immortal body. Empty stays legal.
    """

    def __init__(self, despawn_on: str = "", lifetime_ms: int = 0):
        if isinstance(lifetime_ms, bool) or not isinstance(lifetime_ms, int):
            raise PyoneerConfigError(
                "lifecycle_mark's lifetime_ms must be a whole number of "
                "milliseconds and got %r (%s); in Tiled, set the property's "
                "type -- an untyped property arrives as a string and would "
                "compare greater than every elapsed time"
                % (lifetime_ms, type(lifetime_ms).__name__))
        if lifetime_ms < 0:
            raise PyoneerConfigError(
                "lifecycle_mark declares lifetime_ms=%d. A negative lifetime "
                "reads as 'already elapsed' and would remove the body on its "
                "first frame, which is indistinguishable from the body never "
                "having spawned. Set it to 0 for no lifetime."
                % (lifetime_ms,))
        if despawn_on:
            declared = _declared_action_tokens()
            if despawn_on not in declared:
                raise PyoneerConfigError(
                    "lifecycle_mark declares despawn_on=%r, and no registered "
                    "behavior writes that action slot. update() reads "
                    "actions_of(entity).fired(%r), which answers None for a "
                    "name nothing records -- so this body would never die, and "
                    "a typo would be indistinguishable from the action simply "
                    "never firing. It is an ACTION TOKEN, not an input verb: "
                    "'action' is a verb and 'interact_action' is the token "
                    "that polls it. Declared actions: %s."
                    % (despawn_on, despawn_on,
                       ", ".join(declared) or "<none>"))
        self.despawn_on = despawn_on
        self.lifetime_ms = lifetime_ms
        self._age_ms = 0.0

    # -- inspection --------------------------------------------------------

    @property
    def age_ms(self) -> float:
        """Milliseconds this behavior has been updated for. Stops at the mark.

        On the behavior instance rather than on the record: it is one
        behavior's working variable, and a shared `entity.ages` would be an
        intersecting write at a shared order that `EntityBehaviors.attach`
        would refuse.
        """
        return self._age_ms

    @property
    def remaining_ms(self) -> float:
        """Milliseconds until the lifetime elapses. `inf` when none is declared."""
        if self.lifetime_ms <= 0:
            return float("inf")
        return max(0.0, float(self.lifetime_ms) - self._age_ms)

    # -- lifecycle ---------------------------------------------------------

    def attach(self, entity: Any) -> None:
        """Allocate the record, because this behavior writes an axis of it.

        Whoever WRITES an axis allocates the record, so no entity class has to
        know which behaviors it might one day carry. `ensure_state` is
        idempotent, so `GamePlayer` allocating one in `__init__` cannot fight
        with this.
        """
        ensure_state(entity)

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        state = ensure_state(entity)
        if state.gone:
            # Already declared. Returning rather than re-writing the axis is
            # what stops `age_ms` at the moment of death, so a dead body does
            # not go on reporting a lifetime that outlived it.
            return
        self._age_ms += event.data["delta"] * MS_PER_DELTA
        if 0 < self.lifetime_ms <= self._age_ms:
            state.life = LIFE_GONE
            return
        if self.despawn_on and actions_of(entity).fired(self.despawn_on) is not None:
            state.life = LIFE_GONE


LIFECYCLE_MARK = BehaviorSpec(
    name="lifecycle_mark",  # #TAG:lifecycle_mark
    summary="Declares this body GONE -- when a named action fires, or after a "
            "declared lifetime. It marks and never removes; SceneManager.reap() "
            "is what takes a marked body out of the scene and the renderer.",
    factory=GameLifecycleMarkBehavior,
    params=(
        BehaviorParam("despawn_on", "despawn on action", "str", "",
                      "The ACTION TOKEN whose firing declares this body gone "
                      "-- 'interact_action' for a pickup, 'attack_action' for "
                      "a one-shot. Not an input verb: the verb is rebindable "
                      "and the token is the stable name. Must name a "
                      "registered action; an unknown one raises at "
                      "construction rather than leaving the body immortal. "
                      "Empty means no action ends this body.",
                      source="object"),
        BehaviorParam("lifetime_ms", "lifetime (ms)", "int", 0,
                      "Milliseconds this body exists for before it is declared "
                      "gone. 0 means no lifetime. Milliseconds, not delta "
                      "units -- delta is ms/60 and this converts.",
                      source="object"),
    ),
    writes=("state.life",),
    # Nothing is REQUIRED, and the two failures it would guard are different.
    # A `despawn_on` naming a token no registered behavior WRITES is a typo,
    # and the constructor refuses it. A token that is real but that THIS body
    # does not compose stays quiet -- `actions_of` hands back the shared inert
    # record -- because attach order is the authored token order and no site
    # here can tell "not composed yet" from "not composed". Declaring
    # `action_intent` in `requires` would not catch it, and would be a lie for
    # the lifetime-only configuration.
    requires=(),
    order=ORDER,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,interact_action,action_relay,lifecycle_mark"/>\n'
            '<property name="pyoneer_param_despawn_on" value="interact_action"/>',
)


__all__ = ["LIFECYCLE_MARK", "ORDER", "GameLifecycleMarkBehavior"]
