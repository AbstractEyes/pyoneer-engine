"""The engine's one host for `entity.action_sink`, and it CALLS.

`action_relay` reads an entity's action record and calls
`entity.action_sink(entity, fired)`. `SceneManager` assigns one of these on
both binding routes, so an entity carrying that token reaches a real sink with
no game code -- which is the runtime end of the `use` trigger kind, of GUI
window flow, and of scene-driven action flow.

NOT AN EVENT TYPE, AND IT CANNOT BECOME ONE BY ACCIDENT
-------------------------------------------------------
A plain callable: it constructs no `PyoneerEvent`, calls no `handle()`, binds
no listener and imports no event module. `tools/check_flow.py` proves all four
from this module's PARSE TREE.

`GameScene.core_input_receive` hands every bound object -- including the whole
UI tree, since `bind()` accepts a `GameComponent` -- THE SAME event, and
consumption is not type-gated, so one `handle()` reached from an entity there
silences every sibling for the rest of that pyo-event. This router is reached
instead from `action_relay.update` at order 90, on the frame path, where the
event object is already per-object. The payoff: N handlers may read one firing
and none can stop the others, so a dialogue box, a quest log and an
achievement counter can all want the same `interact_action`.

THE ROUTING KEY IS THE AUTHORED VOCABULARY
------------------------------------------
A route is keyed by `(token, payload)`:

    token     `ActionFired.name` -- the BEHAVIOR TOKEN (`interact_action`),
              which is what a tmx object's `pyoneer_behaviors` list spells
    payload   `ActionFired.payload` -- the opaque key from
              `pyoneer_param_payload`, carrying the same "not interpreted"
              contract as `pyoneer_payload` on a map trigger

Most specific first, the same shape as `resolve_depth`:

    1. a route registered for exactly this (token, payload)
    2. a route registered for the token with payload ""  -- "any payload"
    3. nothing, and the firing is dropped in silence

Step 3 is not a swallow: `action_relay` hands over every firing an entity
produced, and routing `interact_action` is no promise to care about
`attack_action`. A malformed ROUTE is not silent -- an empty token or a
non-callable handler raises at `route()`, at wiring time.

There is no `args` routing (`parse_args` lives in
`editor/core/map_events.py`, which `scripts/` may never import), no filtering
by class or tag (a handler reads the entity it was handed), and no clock:
`cooldown_ms` and `once` belong to the action behavior, and a second copy
would be two clocks disagreeing about one authored number.
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

    One object plays both parts: `__call__` IS the sink, so there is nothing
    extra to wire.

    Handlers take `(entity, fired)` -- the same two arguments `action_relay`
    passes -- so a method on a scene, a flow or a quest log is a handler with
    no adapter. `SceneFlow.on_action` is that shape.
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
        rather than replacing the first, because N consumers may read one
        firing. A caller that wants replacement calls `clear` first.
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

        `clear()` with no arguments forgets everything, which is what a scene
        teardown wants.
        """
        if token is None:
            dropped = sum(len(v) for v in self._routes.values())
            self._routes.clear()
            return dropped
        return len(self._routes.pop((token, payload), ()))

    @property
    def routes(self) -> Tuple[Tuple[str, str, int], ...]:
        """(token, payload, handler count) for every route. SORTED.

        Sorted rather than in registration order, so two scenes wired the same
        way report themselves the same way.
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

        The resolution rule in one place, so `__call__` and a caller asking
        "would this be routed?" cannot answer differently. Returns a SNAPSHOT,
        so a handler that routes or clears from inside its own call does not
        mutate the list the dispatch loop is walking.
        """
        if payload:
            exact = self._routes.get((token, payload))
            if exact:
                return tuple(exact)
        return tuple(self._routes.get((token, ANY_PAYLOAD), ()))

    def __call__(self, entity: Any, fired: Any) -> int:
        """The `action_sink` itself. Returns how many handlers ran.

        Duck-typed on `fired`: importing `ActionFired` would drag the behavior
        package into `scripts/core/scene/`'s import of this module, and the
        `getattr` reads also let a game route its own record-shaped object.
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
