"""Scene and GUI flow: where a firing goes, and what step the story is on.

WHAT IS HERE
------------
    router.py       `ActionRouter` -- the engine's one host for
                    `entity.action_sink`. A firing recorded by an action
                    behavior and handed outward by `action_relay` at order 90
                    arrives here and is CALLED to whoever routed the token.
    scene_flow.py   `FlowStep` / `SceneFlow` -- an ordered run of beats that
                    drives windows that already exist, and borrows the bodies'
                    agency while it runs, giving back exactly what it took.

THE WHOLE WIRE, END TO END, IN ONE SCREEN
------------------------------------------
This is the breadcrumb trail. Every line of it is exercised by
`tools/check_flow.py` against a real map, a real `SceneManager` and a real
`GameWindow`:

    # 1. AUTHORED, in Tiled, on the object -- the map is the whole truth
    <property name="pyoneer_behaviors"
              value="player_input,interact_action,action_relay"/>
    <property name="pyoneer_param_payload" value="door_north"/>

    # 2. WIRED, in the game, once
    flow = SceneFlow([FlowStep("greeting", window=dialogue)], bodies=[player])
    manager.actions.route(ADVANCE_ACTION, flow.on_action)   # interact_action
    manager.actions.route("interact_action", open_door, payload="door_north")

    # 3. RUNS, with no further code
    #    press the 'action' verb
    #      -> interact_action records ActionFired(name, verb, payload)
    #      -> action_relay calls entity.action_sink, which SceneManager
    #         assigned to manager.actions when the entity was bound
    #      -> ActionRouter picks the handlers for (token, payload)
    #      -> the flow advances; the window opens; the player stops walking
    #         and can still press continue

WHY IT LIVES UNDER scripts/ AND NOT UNDER editor/
--------------------------------------------------
Because the engine runs it. The editor MAY import this -- `editor/` may import
`scripts/` and does so in eight places -- and an authoring panel for flows
would read `FlowStep`'s fields the way `editor/core/inspect.py` reads a
`Capability`. The reverse is the invariant: nothing here imports `editor/`,
which is why `ADVANCE_TRIGGER_KIND` is the string `"use"` spelled out and
asserted equal to `editor.core.map_events.USE` by a check under `tools/`
rather than imported from it.

THE EVENT SYSTEM IS NOT TOUCHED, BY CONSTRUCTION
-------------------------------------------------
Neither module constructs a `PyoneerEvent`, calls `handle()` or
`mark_event_handled`, binds a listener, or imports an event module.
`tools/check_flow.py` proves that from the parse tree of both files, and
proves the same scan finds a bus call when one is planted -- because a scan
with the wrong name list looks exactly like a clean pass. The router is
reached from `action_relay.update`, on the FRAME path where
`GameScene.core_frame_update` builds a fresh event per object, and never from
`core_input_receive`, which hands one shared event to every bound object
including the whole UI tree.
"""
from __future__ import annotations

from scripts.game.flow.router import ANY_PAYLOAD, ActionRouter
from scripts.game.flow.scene_flow import (ADVANCE_ACTION, ADVANCE_TRIGGER_KIND,
                                          FlowStep, SceneFlow)

__all__ = ["ADVANCE_ACTION", "ADVANCE_TRIGGER_KIND", "ANY_PAYLOAD",
           "ActionRouter", "FlowStep", "SceneFlow"]
