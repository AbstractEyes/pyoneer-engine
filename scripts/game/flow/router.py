"""The engine's one host for `entity.action_sink`, and it CALLS.

WHAT THIS MOUNTS
----------------
`action_relay` reads an entity's action record and calls
`entity.action_sink(entity, fired)`. That behavior has shipped complete,
checked and documented, and `git grep action_sink` across `scripts/`,
`main.py`, `demos/`, `config/` and `editor/` returned eight hits, every one of
them inside `action.py` itself -- prose, or the `getattr` that reads it.
Nothing has ever assigned one, which is why its registry status was
`needs-host`. `SceneManager` assigns THIS, on both binding routes, and that is
the whole change: the runtime end of the `use` trigger kind, of GUI window
flow, and of scene-driven action flow, all at once.

WHY THIS IS NOT AN EVENT TYPE, AND CANNOT BECOME ONE BY ACCIDENT
----------------------------------------------------------------
It is a plain callable. It constructs no `PyoneerEvent`, calls no `handle()`,
binds no listener and imports no event module -- `tools/check_flow.py` proves
all four from this module's PARSE TREE, and proves the scan can find a bus
call when one is there, because a scan with a wrong name list looks exactly
like a clean pass.

The reason is the asymmetry in `GameScene` that `action.py` already documents:
`core_frame_update` builds a fresh event per bound object, while
`core_input_receive` hands every bound object -- including the entire UI tree,
since `bind()` accepts a `GameComponent` -- THE SAME event. Consumption in
this engine is not type-gated, so one `handle()` reached from an entity on the
input path silences every sibling for the rest of that pyo-event. A router
that can never reach the bus can never do that, and this one is reached from
`action_relay.update` at order 90, on the frame path, where the event object
is already per-object.

What that buys is the property the bus cannot give here: N handlers may read
one firing and none of them can stop the others. A dialogue box, a quest log
and an achievement counter all want the same `interact_action`, and on a bus
the first one to consume it wins.

THE ROUTING KEY IS THE AUTHORED VOCABULARY, NOT A NEW ONE
----------------------------------------------------------
A route is keyed by `(token, payload)`:

    token     `ActionFired.name` -- the BEHAVIOR TOKEN (`interact_action`),
              which is what a tmx object's `pyoneer_behaviors` list spells
    payload   `ActionFired.payload` -- the opaque key from
              `pyoneer_param_payload`, which is the same word, the same
              meaning and the same "deliberately not interpreted" contract as
              `pyoneer_payload` on a map trigger
              (`editor/core/map_events.py`)

Most specific first, the same shape as `resolve_depth` and as behavior
parameter resolution:

    1. a route registered for exactly this (token, payload)
    2. a route registered for the token with payload ""  -- "any payload"
    3. nothing, and the firing is dropped in silence

Silence is correct for step 3 and is not a swallow: `action_relay` hands over
every firing the entity produced, and a game that routes `interact_action` has
not thereby promised to care about `attack_action`. What is NOT silent is a
malformed ROUTE -- an empty token or a non-callable handler raises at
`route()`, at wiring time, where the caller is.

WHAT THIS DELIBERATELY DOES NOT DO
-----------------------------------
  * **No `args`.** `editor/core/map_events.py` declares `pyoneer_args` with a
    round-trip-checked `parse_args`/`format_args` pair, and `scripts/` may
    never import `editor/`. Re-spelling those two functions here would be the
    second implementation of one vocabulary across the fence a previous pass
    already broke. When that module moves to
    `scripts/core/trigger_profile.py`, this file gains argument routing by
    calling its parser and by nothing else.
  * **No filtering by class or tags.** `MapEvent.accepts` is the trigger side's
    job and needs `entity.tags` / `entity.type_name`, neither of which exists
    yet. A handler that cares reads the entity it was handed.
  * **No clock and no fired-set.** `cooldown_ms` and `once` are already owned
    by the action behavior, per action, and a second copy here would be two
    clocks disagreeing about the same authored number.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from scripts.core.errors import PyoneerConfigError

ANY_PAYLOAD: str = ""
"""The payload value that means "this route takes any payload for its token".

Empty, and not a sentinel object, because it is also the DEFAULT payload an
action carries: `BehaviorParam("payload", ..., "")`. A firing with no payload
and a route that does not care about payloads therefore meet at the same key,
which is the common case and costs no branch.
"""


class ActionRouter:
    """Token -> handler, and the `entity.action_sink` callable itself.

    One object plays both parts on purpose. A separate "sink adapter" would be
    a second thing to wire and a second place for a game to get the wiring
    wrong, and there is nothing for it to do that `__call__` does not.

    Handlers take `(entity, fired)` -- the same two arguments `action_relay`
    passes -- so a method on a scene, a flow, a quest log or a bound function
    is a handler with no adapter. `SceneFlow.on_action` is exactly that shape
    and exists for exactly this reason.
    """

    __slots__ = ("_routes",)

    def __init__(self) -> None:
        self._routes: Dict[Tuple[str, str], List[Callable[[Any, Any], Any]]] = {}

    # -- wiring ------------------------------------------------------------

    def route(self, token: str, handler: Callable[[Any, Any], Any],
              payload: str = ANY_PAYLOAD) -> Callable[[Any, Any], Any]:
        """Call `handler(entity, fired)` when `token` fires with `payload`.

        Returns the handler, so a decorator-ish or fluent wiring line reads in
        one direction.

        Registering the same (token, payload) twice ADDS a second handler
        rather than replacing the first: the property this router exists for
        is that N consumers may read one firing. A caller that wants
        replacement calls `clear` first, which is one visible line rather than
        a silent overwrite.
        """
        if not isinstance(token, str) or not token:
            raise PyoneerConfigError(
                "an action route needs a non-empty token and got %r. The token "
                "is `ActionFired.name` -- the BEHAVIOR token, e.g. "
                "'interact_action', which is what a tmx object's "
                "pyoneer_behaviors list spells -- and not the input verb."
                % (token,))
        if not callable(handler):
            raise PyoneerConfigError(
                "the route for %r was given %r, which is not callable. A "
                "handler takes (entity, fired), the same two arguments "
                "action_relay passes." % (token, handler))
        if not isinstance(payload, str):
            raise PyoneerConfigError(
                "the route for %r declares payload %r (%s); a payload is an "
                "opaque STRING key -- a door id, a cutscene name, a quest step "
                "-- exactly as pyoneer_payload is on a map trigger."
                % (token, payload, type(payload).__name__))
        self._routes.setdefault((token, payload), []).append(handler)
        return handler

    def clear(self, token: str | None = None,
              payload: str = ANY_PAYLOAD) -> int:
        """Forget routes. Returns how many handlers were dropped.

        `clear()` with no arguments forgets everything -- which is what a
        scene teardown wants, and is the only reason this takes an optional
        token rather than requiring one.
        """
        if token is None:
            dropped = sum(len(v) for v in self._routes.values())
            self._routes.clear()
            return dropped
        return len(self._routes.pop((token, payload), ()))

    @property
    def routes(self) -> Tuple[Tuple[str, str, int], ...]:
        """(token, payload, handler count) for every route. SORTED.

        Sorted rather than in registration order, for the reason
        `ActionIntent.fired_names` is: two scenes wired the same way must
        report themselves the same way regardless of the sequence the wiring
        happened to run in.
        """
        return tuple(sorted((token, payload, len(handlers))
                            for (token, payload), handlers
                            in self._routes.items()))

    def __len__(self) -> int:
        return sum(len(handlers) for handlers in self._routes.values())

    def __contains__(self, item: Any) -> bool:
        """`"interact_action" in router`, or `("interact_action", "door") in router`."""
        if isinstance(item, tuple):
            return bool(self._routes.get(item))
        return any(token == item for token, _ in self._routes)

    # -- the sink ----------------------------------------------------------

    def handlers_for(self, token: str,
                     payload: str = ANY_PAYLOAD) -> Tuple[Callable[[Any, Any], Any], ...]:
        """Which handlers a firing of (token, payload) would reach.

        The resolution rule in one place, so `__call__` and any caller asking
        "would this be routed?" cannot answer differently. A SNAPSHOT: a
        handler that routes or clears from inside its own call must not mutate
        the list the dispatch loop is walking, which is the same hazard
        `EntityBehaviors.update` snapshots against and the same one that makes
        an entity unbinding itself skip its neighbour.
        """
        if payload:
            exact = self._routes.get((token, payload))
            if exact:
                return tuple(exact)
        return tuple(self._routes.get((token, ANY_PAYLOAD), ()))

    def __call__(self, entity: Any, fired: Any) -> int:
        """The `action_sink` itself. Returns how many handlers ran.

        Duck-typed on `fired`, deliberately: `ActionFired` is a frozen
        dataclass in `scripts.game.behavior.action`, and importing it here
        would drag the behavior package into `scripts/core/scene/`'s import of
        this module for a type annotation that adds nothing. `getattr` with a
        default also means a game that hands its own record-shaped object to a
        route is not refused by the transport.
        """
        token = getattr(fired, "name", "")
        if not token:
            return 0
        handlers = self.handlers_for(token, getattr(fired, "payload", ANY_PAYLOAD))
        for handler in handlers:
            handler(entity, fired)
        return len(handlers)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<ActionRouter %s>" % (
            ", ".join("%s%s x%d" % (t, "/" + p if p else "", n)
                      for t, p, n in self.routes) or "unrouted")


__all__ = ["ANY_PAYLOAD", "ActionRouter"]
