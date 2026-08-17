"""Declaring a body GONE: the one authorable writer of the lifecycle axis.

WHAT THIS IS, IN ONE SENTENCE
-----------------------------
`lifecycle_mark` writes `state.life = "gone"` when a named action fires or a
declared lifetime elapses, and does nothing else at all -- it does not unbind,
does not touch the renderer, does not free anything and does not know that a
scene exists.

WHY MARKING AND REMOVING ARE TWO DIFFERENT JOBS
-----------------------------------------------
This is the load-bearing decision in the file, and it is a measurement rather
than a preference. `GameScene.core_frame_update` iterates its buckets RAW:

    for game_object_type, game_object_list in self.__game_objects.items():
        for game_object in game_object_list:
            game_object.core_frame_update(...)

Driven on this engine with three objects `a, b, c` in one bucket, where `a`
unbinds itself from inside its own update, the frame ran `['a', 'c']` -- `b`
never updated at all, because `list.remove` shifted it into the index the loop
had already passed. Nothing raises and nothing warns; one entity silently
misses one frame, and which entity it is depends on bind order.

So a behavior must never remove its own entity. It declares, and
`SceneManager.reap()` removes -- once, after the whole fan-out has returned,
where a mutation cannot skip anything. The same argument in the other
direction is why the axis is not a `None` in the list: a null is a value every
consumer has to guard, and the guard is exactly the thing that gets forgotten.

WHY IT SITS AT ORDER 95
-----------------------
After `action_relay` (90), which is after `animation_drive` (80), which is
after the movement bodies (20). Concretely: on the frame a pickup is collected,
the relay has already handed the firing to the scene's `ActionRouter` -- so a
game can open a window, add to an inventory or start a cutscene from a body
that is about to stop existing. Marking first would still work today, because
the mark does not remove anything until the reap; running last is what keeps
that true if the reap ever moves earlier.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
  * **A despawn SINK.** The survey that specified this pass proposed a
    `entity.despawn_sink` callable, status `needs-host`, on the model of
    `action_sink`. That would have put a second unhosted seam on the board
    next to the one this pass is mounting. The engine ships a despawner --
    `SceneManager.despawn` / `.reap()` -- so a game that wants to be told
    routes `ActionRouter` and gets the firing BEFORE the mark, at order 90,
    with the entity still whole.
  * **A spawner.** `SceneManager.spawn` is the construct half and lives with
    `bind`, whose exact inverse it is. A behavior that spawned would need the
    scene, and an entity that knows about the scene is the coupling this
    package exists without.
  * **`hp`, damage, or death conditions.** There is no damage consumer in this
    engine and no engine-side reader for `data/project/tables/`. A health axis
    before a damage consumer is the docs/history/ORPHANS.md pattern verbatim.
  * **A death animation.** `alive` covers "playing its last sequence"; give
    the body a `lifetime_ms` and play whatever it likes during it. That is why
    `LIVES` has two values and not four.

THE PARAMETERS ARE THE TRIGGER VOCABULARY'S WORDS
--------------------------------------------------
`despawn_on` names an ACTION TOKEN (`interact_action`), not an input verb --
the same distinction `ActionFired` draws between `name` and `verb`, and for
the same reason: the verb is rebindable data and the token is the stable name
a consumer switches on. `lifetime_ms` ends `_ms` and is milliseconds, matching
`cooldown_ms` in both the behavior vocabulary and
`editor/core/map_events.py`'s trigger vocabulary. It is NOT delta units;
`event.data["delta"]` is milliseconds/60 and this module converts through
`MS_PER_DELTA`, exactly as the action cooldown does.
"""
from __future__ import annotations

from typing import Any

from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.action import actions_of
from scripts.game.behavior.base import (BehaviorParam, BehaviorSpec,
                                        EntityBehavior)
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import LIFE_GONE, ensure_state

ORDER: int = 95
"""Where a body is declared gone: after the relay, last of everything."""


class GameLifecycleMarkBehavior(EntityBehavior):
    """Write `state.life = gone` on a named action, or after a lifetime.

    Both triggers are optional and both may be declared together; the first
    one to fire wins and the second is then moot, because the mark is checked
    before either trigger is consulted and a body is never re-marked.

    Declaring the token with NEITHER parameter is legal and means "this body's
    life is written by game code". It is not a mistake and it is not inert
    machinery: the behavior still allocates the record in `attach`, so
    `state_of(entity).life = LIFE_GONE` from anywhere is a complete despawn
    request on an entity that carries this token. That is the seam. This class
    is one authorable writer of it, not the only way in.
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
        self.despawn_on = despawn_on
        self.lifetime_ms = lifetime_ms
        self._age_ms = 0.0

    # -- inspection --------------------------------------------------------

    @property
    def age_ms(self) -> float:
        """Milliseconds this behavior has been updated for. Stops at the mark.

        On the behavior instance rather than on the record, for the reason
        `GameActionInputBehavior._cooldown_left` is: it is one behavior's
        working variable, it has no second reader that is not simply asking
        this behavior, and a shared `entity.ages` would be an intersecting
        write at a shared order that `EntityBehaviors.attach` would refuse.
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

        The contract every writer in this package has, and the reason no
        entity class has to know which behaviors it might one day carry:
        whoever WRITES an axis allocates the record in `attach`. `GamePlayer`
        allocates one in `__init__` as well, and `ensure_state` is idempotent,
        so the two cannot fight.
        """
        ensure_state(entity)

    def update(self, entity: Any, event: Any) -> None:
        if event is None:
            return
        state = ensure_state(entity)
        if state.gone:
            # Already declared. Returning here rather than re-writing the axis
            # is what makes `age_ms` stop at the moment of death, and it is
            # what makes a second mark on the same body a no-op instead of a
            # second reap request -- `SceneManager.reap` is idempotent too, but
            # a body that kept ageing after it died would report a lifetime
            # that outlived it.
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
                      "and the token is the stable name. Empty means no "
                      "action ends this body.",
                      source="object"),
        BehaviorParam("lifetime_ms", "lifetime (ms)", "int", 0,
                      "Milliseconds this body exists for before it is declared "
                      "gone. 0 means no lifetime. Milliseconds, not delta "
                      "units -- delta is ms/60 and this converts.",
                      source="object"),
    ),
    writes=("state.life",),
    # Nothing is REQUIRED. `despawn_on` reads the action record, and an entity
    # with no action behavior reads the shared inert one, which reports that
    # nothing ever fired -- so a mis-declared token is a body that simply never
    # dies, not a crash. Declaring `action_intent` here would be a lie for the
    # lifetime-only configuration, which is the majority one.
    requires=(),
    order=ORDER,
    example='<property name="pyoneer_behaviors" '
            'value="player_input,interact_action,action_relay,lifecycle_mark"/>\n'
            '<property name="pyoneer_param_despawn_on" value="interact_action"/>',
)


__all__ = ["LIFECYCLE_MARK", "ORDER", "GameLifecycleMarkBehavior"]
