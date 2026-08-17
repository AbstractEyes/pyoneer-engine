# Behaviors -- composing an entity out of data

**This file is generated.** `scripts/game/behavior/registry.py` holds the
table; `describe_all()` prints it. Edit the specs, not this file.

## What a behavior is

A small object attached to a `GameEntity` and updated once per frame, with
three methods and no event-bus presence:

    attach(entity)          once, when it joins the entity
    update(entity, event)   once per frame, in declared order
    detach(entity)          once, when it leaves

A behavior is CALLED, never dispatched to. `GameEntity` derives
`PyoneerGameObject`, is not a `GameComponent`, and is driven by a plain method
call from `GameScene.core_frame_update` -- so composing behavior onto one needs
no change to the event system at all. Do not make an entity a `GameComponent`
to get this; the machinery it drags in (bounds, anchor, viewport, a callbacks
dict) is machinery an entity does not want, and a behavior on the bus could
call `event.handle()` and silence every sibling for the rest of the frame.

## How an entity declares one

On the tmx OBJECT, not on the class and not in a table:

    <property name="pyoneer_behaviors" value="topdown_move,tile_collision"/>
    <property name="pyoneer_param_move_speed" type="int" value="20"/>
    <property name="pyoneer_actor" value="hero"/>

The `pyoneer_` prefix is load-bearing: pytmx RAISES and makes the whole map
unloadable if a custom property shadows one of its own attribute names.

The list is comma-separated, snake_case, order-insensitive -- the run order
comes from each behavior's declared `order`, not from the list. The map file
is the whole truth: a genre pack may supply a default list, but the editor
materialises it into the object when the object is added, so an object plays
the same way whether or not the editor has ever opened the map.

## Where the parameters come from

Most specific first, the same shape as `resolve_depth`:

    1. `pyoneer_param_<key>` on the object      this object, this map
    2. the `<key>` column of the actors row named by `pyoneer_actor`
    3. the parameter's declared default

Step 2 needs a row, and **nothing in `scripts/` reads `data/project/`** -- the
engine has no table reader yet. Until one exists, every parameter resolves
from step 1 or step 3, and a `required` parameter with neither raises.

## The per-frame call chain

    main.py frame loop
      -> SceneManager.update            camera.update() runs BEFORE this
        -> GameScene.core_frame_update  fan-out over every bound object
          -> GameEntity.core_frame_update
            -> EntityBehaviors.update(event)
              -> behavior.update(entity, event)   in `order` order, low first

Note the camera: `SceneManager` updates it *before* the scene's frame update,
so it sees the previous frame's position. Moving a position write to a
different point in the frame changes what the camera sees even when the
arithmetic is identical -- and `tools/smoke.py` will report the drift.

## Four traps that have each cost a session

1. **`event.data["delta"]` is milliseconds / 60, not seconds.** The genre
   tables document movement in pixels per second. A number used raw is about
   16.7x wrong in a way that still looks like it works.
2. **`InputActionManager.held()` is an unguarded dict index.** Polling a verb
   absent from `config/inputs.json` raises `KeyError` inside
   `core_frame_update` and kills the frame for every sibling in that bucket.
   Adding a behavior and adding its binding are ONE change.
3. **`move_direction` silently moves zero for a direction it does not know**
   -- there is no `else` branch -- while **`GameAnimationHandler.start` RAISES**
   for a sequence name it does not know. Opposite failures from one typo, so a
   behavior that swaps a direction vocabulary must swap the animation naming
   with it.
4. **`GameEntity.__init__` accepts a `transform` keyword and discards it.**
   Anything that builds an entity still has to `moveto()` afterwards.

## What the collision vocabulary cannot express

Taken from `scripts/core/collision_runtime.py`, not restated from memory: a
mask is per-CELL and tested at ONE anchor point rather than a box; blocking is
symmetric, so a one-way platform is not expressible; and an anchor outside the
field is ungated rather than blocked.

`GameEntity.collision_field` IS assigned in production: `LayerRenderer` bakes
the map's passability once at bind and hands it to every entity it binds, by
either route. A map that declares no passability layer bakes `None`, which
means ungated -- so a body on such a map still moves freely, and that is the
shipped demo's state rather than a missing wire. The measured integration
table below is the authority on this; this paragraph is prose and can rot.

## Adding a behavior

1. Write the class in `scripts/game/behavior/`, deriving `EntityBehavior`.
   Take the resolved parameters as constructor keywords named exactly for the
   keys the spec declares.
2. Register it at the bottom of `scripts/game/behavior/registry.py`:

       register(BehaviorSpec(
           name="topdown_move",
           summary="Four-way axis-aligned movement polled from input verbs.",
           factory=GameTopDownMoveBehavior,
           params=(BehaviorParam("move_speed", "move speed", "int", 16,
                                 "Pixels per delta unit.", source="actors"),),
           writes=("transform.position",),
           requires=("action_manager",),
           order=20,
           genres=("topdown_rpg",)))

3. Add a check, and add it to `tools/check_all.py`'s roster.
4. `describe_all()` picks the new entry up with no further edit.

Two invariants that are not negotiable: `scripts/` may never import
`editor/`, and the event system does not get restructured to accommodate a
behavior. A behavior that needs the bus is a behavior that needs a different
design.

## Reading the tables below

    order      lower runs first within a frame; a tie is legal only when the
               two behaviors write nothing in common
    writes     which entity attributes it mutates -- this is what makes a
               collision between two composed behaviors visible in advance
    requires   what must be present on the entity for it to do anything;
               reported by `EntityBehaviors.missing_requirements()`, never
               enforced, because `input_=None` is a legal configuration
    hooks      derived from the class, not declared, so it cannot be stale
    binds      `GameEventType` members it listens for. Normally empty; a
               non-empty value means this behavior reaches the event bus and
               should be read carefully
    status     whether anything in the engine runs it


## The state axes

`BodyState` (`scripts/game/behavior/state.py`) is what a body IS, beside `MoveIntent` (what it was ASKED to do) and `ActionIntent` (what it DID). A behavior declares the axes it writes as `state.<axis>`, and two behaviors at one `order` writing one axis are REFUSED at attach -- which is the whole reason the declaration is spelled per axis rather than as `state`.

| axis | meaning |
| --- | --- |
| `state.enabled_inputs` | Whether input is currently permitted. The authored gate. Read by `player_input` WITH `steerable` and by the action behaviors WITHOUT it -- a body frozen for a cutscene may not walk and must still press continue. |
| `state.facing` | Which way the body is pointed. OPEN -- any non-empty string, because isometric wants eight tokens and twin-stick wants an angle. Defaults to `down`. It is the `{}` in `walk_{}` and it is NOT the argument to `move_direction`. |
| `state.input_bound` | Whether the body is wired to a human's input at all. Set once from the wiring, so a narrative gate can tell restoring input from granting it. |
| `state.life` | Whether the body is still part of the world. CLOSED: `alive`, `gone`. Written by `lifecycle_mark` (and by any game code that wants a body gone); READ by `SceneManager.reap()`, which is what actually removes it from its scene bucket and its EntityLayer. Marking is a DECLARATION -- a behavior that unbound its own entity would make the scene fan-out skip the next sibling. |
| `state.phase` | What the body is doing. CLOSED: `idle`, `moving`. A branch reads it, so an unrecognised value would silently take the idle path. |
| `state.simulated` | Whether the entity is stepped at all. `GamePlayer` returns before `super()` when this is false, so the animation clock stops too. Per-entity; it is NOT a world pause. |
| `state.sprinting` | A mirror of `MoveIntent.sprint`. Not an axis and has no production reader; the real home is the intent. |
| `state.steerable` | Whether the body may be STEERED. Gates the input poll, not the simulation -- a side-on body still falls while the player is in a menu. |
| `state.support` | Whether something is holding the body up. CLOSED: `grounded`, `airborne`. Written by `platformer_move`; `entity.grounded` is an alias over it. |
| `state.support_grace` | Milliseconds a body that has left its support is still treated as supported -- the coyote clock. `entity.coyote_left` is an alias over it. |

## The registry

| token | order | status | writes | summary |
| --- | --- | --- | --- | --- |
| `player_input` | 10 | live | `intent`, `state.sprinting` | Polls the bound input manager and publishes a MoveIntent. The entity carrying this one is the entity the human drives. |
| `attack_action` | 15 | live | `action_intent.attack_action` | Fires on the rising edge of the 'attack' verb, with a cooldown. Records an ActionFired; reaches no event bus. |
| `interact_action` | 15 | live | `action_intent.interact_action` | Fires on the rising edge of the 'action' verb -- talk, use, open. The explicit interaction a `use` map trigger is waiting for. |
| `pause_action` | 15 | live | `action_intent.pause_action` | Fires on the rising edge of the 'pause' verb. The entity-side half of a pause; what it MEANS is the sink's business. |
| `platformer_move` | 20 | live | `transform.position`, `velocity`, `state.support`, `state.support_grace`, `state.phase`, `state.facing` | A side-on body: gravity, terminal velocity, air control and a jump with coyote time. Reads the actors table's own columns. |
| `topdown_move` | 20 | live | `transform.position`, `state.phase`, `state.facing` | Eight-direction axis-aligned movement, each held verb gated separately. The demo's controller. |
| `animation_drive` | 80 | live | `animation` | Names the animation from the movement state, on the frame it changes. The sequence naming is parameters, not code. |
| `action_relay` | 90 | live | -- | Calls entity.action_sink(entity, fired) for every action that fired this frame. The only behavior that reaches outward, and it calls rather than dispatches. SceneManager assigns the sink: it is the scene's ActionRouter (scripts/game/flow/router.py). |
| `lifecycle_mark` | 95 | live | `state.life` | Declares this body GONE -- when a named action fires, or after a declared lifetime. It marks and never removes; SceneManager.reap() is what takes a marked body out of the scene and the renderer. |

### `player_input`

Polls the bound input manager and publishes a MoveIntent. The entity carrying this one is the entity the human drives.

- **class** `GamePlayerInputBehavior`
- **order** 10
- **hooks** `attach`, `update`, `detach`
- **binds** nothing (not on the event bus)
- **writes** `intent`, `state.sprinting`
- **requires** `action_manager`
- **conflicts with** --
- **genres** any

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `up_verb` | str | `'up'` | object | no | Action name polled with held() for upward intent. Empty means this body has no upward input. |
| `down_verb` | str | `'down'` | object | no | Action name polled with held() for downward intent. |
| `left_verb` | str | `'left'` | object | no | Action name polled with held() for leftward intent. |
| `right_verb` | str | `'right'` | object | no | Action name polled with held() for rightward intent. |
| `sprint_verb` | str | `'sprint'` | object | no | Action name polled with held() for sprint. Empty disables sprinting for this entity. |
| `jump_verb` | str | `''` | object | no | Action name polled with pressed() -- a rising edge -- for jump. Empty by default because a top-down body has no jump; a platformer sets it to 'jump'. |

```
<property name="pyoneer_behaviors" value="player_input,topdown_move,animation_drive"/>
```

### `attack_action`

Fires on the rising edge of the 'attack' verb, with a cooldown. Records an ActionFired; reaches no event bus.

- **class** `GameActionInputBehavior`
- **order** 15
- **hooks** `attach`, `update`, `detach`
- **binds** nothing (not on the event bus)
- **writes** `action_intent.attack_action`
- **requires** `action_manager`
- **conflicts with** --
- **genres** any

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `verb` | str | `'attack'` | object | no | Action name polled with pressed() -- a rising edge. Must be bound in config/inputs.json; an unbound one raises at attach rather than as a KeyError mid-frame. Empty disables this action for this entity. |
| `cooldown_ms` | int | `0` | object | no | Minimum milliseconds between two firings. 0 means no limit. The clock ticks through the input gate, so a cooldown is wall time and not gameplay time. |
| `once` | bool | `False` | object | no | Disarm after the first firing, for the whole life of this behavior. Survives a detach/attach cycle. |
| `payload` | str | `''` | object | no | An opaque key carried on the firing -- a door id, a cutscene name, a quest step. Deliberately not interpreted: the engine should not need a schema for every game built on it. |

```
<property name="pyoneer_behaviors" value="player_input,topdown_move,attack_action"/>
<property name="pyoneer_param_cooldown_ms" type="int" value="400"/>
```

### `interact_action`

Fires on the rising edge of the 'action' verb -- talk, use, open. The explicit interaction a `use` map trigger is waiting for.

- **class** `GameActionInputBehavior`
- **order** 15
- **hooks** `attach`, `update`, `detach`
- **binds** nothing (not on the event bus)
- **writes** `action_intent.interact_action`
- **requires** `action_manager`
- **conflicts with** --
- **genres** any

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `verb` | str | `'action'` | object | no | Action name polled with pressed() -- a rising edge. Must be bound in config/inputs.json; an unbound one raises at attach rather than as a KeyError mid-frame. Empty disables this action for this entity. |
| `cooldown_ms` | int | `0` | object | no | Minimum milliseconds between two firings. 0 means no limit. The clock ticks through the input gate, so a cooldown is wall time and not gameplay time. |
| `once` | bool | `False` | object | no | Disarm after the first firing, for the whole life of this behavior. Survives a detach/attach cycle. |
| `payload` | str | `''` | object | no | An opaque key carried on the firing -- a door id, a cutscene name, a quest step. Deliberately not interpreted: the engine should not need a schema for every game built on it. |

```
<property name="pyoneer_behaviors" value="player_input,topdown_move,interact_action"/>
<property name="pyoneer_param_payload" value="door_north"/>
```

### `pause_action`

Fires on the rising edge of the 'pause' verb. The entity-side half of a pause; what it MEANS is the sink's business.

- **class** `GameActionInputBehavior`
- **order** 15
- **hooks** `attach`, `update`, `detach`
- **binds** nothing (not on the event bus)
- **writes** `action_intent.pause_action`
- **requires** `action_manager`
- **conflicts with** --
- **genres** any

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `verb` | str | `'pause'` | object | no | Action name polled with pressed() -- a rising edge. Must be bound in config/inputs.json; an unbound one raises at attach rather than as a KeyError mid-frame. Empty disables this action for this entity. |
| `cooldown_ms` | int | `0` | object | no | Minimum milliseconds between two firings. 0 means no limit. The clock ticks through the input gate, so a cooldown is wall time and not gameplay time. |
| `once` | bool | `False` | object | no | Disarm after the first firing, for the whole life of this behavior. Survives a detach/attach cycle. |
| `payload` | str | `''` | object | no | An opaque key carried on the firing -- a door id, a cutscene name, a quest step. Deliberately not interpreted: the engine should not need a schema for every game built on it. |

```
<property name="pyoneer_behaviors" value="player_input,topdown_move,pause_action"/>
```

### `platformer_move`

A side-on body: gravity, terminal velocity, air control and a jump with coyote time. Reads the actors table's own columns.

- **class** `GamePlatformerMoveBehavior`
- **order** 20
- **hooks** `attach`, `update`
- **binds** nothing (not on the event bus)
- **writes** `transform.position`, `velocity`, `state.support`, `state.support_grace`, `state.phase`, `state.facing`
- **requires** `allowed_move`, `transform`
- **conflicts with** `topdown_move`
- **genres** platformer

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `move_speed` | float | `120.0` | actors | no | Horizontal pixels per SECOND at full run. |
| `jump_velocity` | float | `320.0` | actors | no | Upward pixels per second at the instant of jump. Stored POSITIVE and negated at use; screen space is y-down. |
| `gravity` | float | `900.0` | actors | no | Downward pixels per second squared. Per-actor, so a floaty boss is data and not a special case. |
| `max_fall_speed` | float | `600.0` | actors | no | Terminal velocity, so nothing tunnels through a floor. |
| `air_control` | float | `0.6` | actors | no | Fraction of ground speed usable mid-air, 0 to 1. |
| `coyote_ms` | int | `90` | actors | no | Milliseconds after leaving a ledge during which a jump still counts. 0 for strict. |

```
<property name="pyoneer_behaviors" value="player_input,platformer_move,animation_drive"/>
<property name="pyoneer_param_jump_verb" value="jump"/>
<property name="pyoneer_param_gravity" type="float" value="900"/>
```

### `topdown_move`

Eight-direction axis-aligned movement, each held verb gated separately. The demo's controller.

- **class** `GameTopDownMoveBehavior`
- **order** 20
- **hooks** `attach`, `update`
- **binds** nothing (not on the event bus)
- **writes** `transform.position`, `state.phase`, `state.facing`
- **requires** `move_direction`, `transform`
- **conflicts with** `platformer_move`
- **genres** topdown_rpg

Takes no parameters.

```
<property name="pyoneer_behaviors" value="player_input,topdown_move,animation_drive"/>
```

### `animation_drive`

Names the animation from the movement state, on the frame it changes. The sequence naming is parameters, not code.

- **class** `GameAnimationDriveBehavior`
- **order** 80
- **hooks** `attach`, `update`
- **binds** nothing (not on the event bus)
- **writes** `animation`
- **requires** `animation`, `state.phase`, `state.facing`
- **conflicts with** --
- **genres** any

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `walk_format` | str | `'walk_{}'` | object | no | Format string for the moving sequence; {} is the direction. A platformer sheet may want 'run_{}'. |
| `idle_format` | str | `'idle_{}'` | object | no | Format string for the stopped sequence; {} is the direction the body is facing. |
| `initial_sequence` | str | `'idle_down'` | object | no | Played once at attach. A side-on body wants 'idle_right'; empty leaves whatever the handler started. |

```
<property name="pyoneer_param_walk_format" value="run_{}"/>
```

### `action_relay`

Calls entity.action_sink(entity, fired) for every action that fired this frame. The only behavior that reaches outward, and it calls rather than dispatches. SceneManager assigns the sink: it is the scene's ActionRouter (scripts/game/flow/router.py).

- **class** `GameActionRelayBehavior`
- **order** 90
- **hooks** `update`
- **binds** nothing (not on the event bus)
- **writes** --
- **requires** `action_sink`
- **conflicts with** --
- **genres** any

Takes no parameters.

```
<property name="pyoneer_behaviors" value="player_input,interact_action,action_relay"/>
```

### `lifecycle_mark`

Declares this body GONE -- when a named action fires, or after a declared lifetime. It marks and never removes; SceneManager.reap() is what takes a marked body out of the scene and the renderer.

- **class** `GameLifecycleMarkBehavior`
- **order** 95
- **hooks** `attach`, `update`
- **binds** nothing (not on the event bus)
- **writes** `state.life`
- **requires** --
- **conflicts with** --
- **genres** any

| parameter | type | default | source | required | meaning |
| --- | --- | --- | --- | --- | --- |
| `despawn_on` | str | `''` | object | no | The ACTION TOKEN whose firing declares this body gone -- 'interact_action' for a pickup, 'attack_action' for a one-shot. Not an input verb: the verb is rebindable and the token is the stable name. Must name a registered action; an unknown one raises at construction rather than leaving the body immortal. Empty means no action ends this body. |
| `lifetime_ms` | int | `0` | object | no | Milliseconds this body exists for before it is declared gone. 0 means no lifetime. Milliseconds, not delta units -- delta is ms/60 and this converts. |

```
<property name="pyoneer_behaviors" value="player_input,interact_action,action_relay,lifecycle_mark"/>
<property name="pyoneer_param_despawn_on" value="interact_action"/>
```

<!-- Everything above this line is `describe_all()` in scripts/game/behavior/registry.py. Everything below is derived from the engine and the genre packs by tools/check_behavior_docs.py. Regenerate the whole file with:  .venv/Scripts/python.exe tools/check_behavior_docs.py --write  -->

## Integration status

**Integration status: the per-frame drive is WIRED.**

Every row below is measured, not declared: the drive row is produced by constructing a real `GameEntity`, attaching a behavior and running two frames. A row that says *no* is a wire that does not exist, not a wire that is merely undocumented.

| the wire | at this commit | what it takes |
| --- | --- | --- |
| `GameEntity.behaviors` exists on a constructed entity | **yes** | one attribute in `GameEntity.__init__` |
| `GameEntity.core_frame_update` runs the drive | **yes** | one line replacing the `pass` in `game_entity.py` |
| a behavior is registered | **yes** | one `register(BehaviorSpec(...))` in `scripts/game/behavior/registry.py` |
| a declaration is turned into attached behaviors somewhere | **yes** | done in `scripts/core/scene/scene_manager.py`, `scripts/game/entity/game_player.py`, `scripts/loaders/map_loader.py` |
| a **tmx object's** `pyoneer_behaviors` property is read when it spawns | **yes** | read in `scripts/core/scene/scene_manager.py`, `scripts/loaders/map_loader.py` |
| `GameEntity.collision_field` is assigned in production | **yes** | assigned in `scripts/core/renderer.py` |
| a `jump` input action exists | **yes** | `config/inputs.json` binds `action`, `attack`, `down`, `jump`, `left`, `pause`, `right`, `sprint`, `up` |

## What each genre pack declares

Derived from `editor/genres/*/genre.json`, so a pack that gains a column gains it here. A behavior whose parameter declares `source="actors"` may name any column in its genre's table below -- and only those, which is what this check enforces.

### `platformer` -- 2D side-scrolling platformer

- **passability is authored against** `Floor` (companion `FloorCollision`)
- **object layer `entity` allows** `GamePlayer`
- **actors columns a parameter may name** `display_name` (str), `animation` (str), `hp` (int), `move_speed` (float), `jump_velocity` (float), `gravity` (float), `max_fall_speed` (float), `air_control` (float), `coyote_ms` (int), `contact_damage` (int), `playable` (bool)
- **default behavior lists** none declared. The pack may declare them as `layers[].object_classes[].behaviors`; the editor is meant to MATERIALISE such a default into the object when the object is added, so the `.tmx` stays the whole truth and the engine never has to read a pack -- `scripts/` may not import `editor/`.

### `topdown_rpg` -- Top-down RPG

- **passability is authored against** `Floor` (companion `FloorCollision`)
- **object layer `entity` allows** `GamePlayer`
- **actors columns a parameter may name** `display_name` (str), `animation` (str), `hp` (int), `attack` (int), `defence` (int), `speed` (int), `level` (int), `playable` (bool)
- **default behavior lists** none declared. The pack may declare them as `layers[].object_classes[].behaviors`; the editor is meant to MATERIALISE such a default into the object when the object is added, so the `.tmx` stays the whole truth and the engine never has to read a pack -- `scripts/` may not import `editor/`.

## Swapping one behavior list for another

This is the whole point of the design: the same class, the same spawn entry, a different list.

| genre | a complete, legal list |
| --- | --- |
| `platformer` | `player_input,attack_action,interact_action,pause_action,platformer_move,animation_drive,action_relay,lifecycle_mark` |
| `topdown_rpg` | `player_input,attack_action,interact_action,pause_action,topdown_move,animation_drive,action_relay,lifecycle_mark` |

Set the object's `pyoneer_behaviors` property to one of those values. Same `type`, same `SPAWN_REGISTRY` entry, same depth, same class -- only the list changes. `player_input`, `attack_action`, `interact_action`, `pause_action`, `animation_drive`, `action_relay`, `lifecycle_mark` declare no genre and so belong in any list.
