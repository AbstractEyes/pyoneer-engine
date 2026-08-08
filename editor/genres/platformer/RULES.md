## How this genre is built on Pyoneer

Read this before writing anything.

### What the engine already gives you, honestly

| you get | you do not get |
|---|---|
| deferred depth-sorted rendering | gravity |
| tile map loading and compositing | tile collision |
| an object layer that can hold spawn data | a spawn system reading it |
| `GameBoundingBox.collide(other)`, a pairwise AABB test | a broadphase, or swept resolution |
| input actions with real edge detection (`pressed` / `held` / `released`) | jump buffering or coyote time |
| an 8-direction top-down player controller | a side-on one |

So a platformer request against this engine is **not** a data-only change.
The tables and the map are data; movement is code you have to write. Say
which of the two you did in `NOTES.md`.

### Where the code goes

- Movement and gravity: a new `scripts/game/entity/game_platformer_body.py`
  holding a component that owns velocity and integrates it. It must not
  live on `GameComponent` -- that class is already a god class and there is
  a live plan to split it.
- Tile collision: read solids from the `Floor` layer. Resolve **axis by
  axis**, horizontal first then vertical, using the tile grid directly.
  Do not build a general physics engine; a tile platformer does not need
  one and a general one will get the corner cases wrong.
- Tunables belong in the `actors` table, never as Python literals. The
  columns already exist: `gravity`, `jump_velocity`, `max_fall_speed`,
  `air_control`, `coyote_ms`.

### Solid means the Floor layer

A non-zero gid on `Floor` is solid. Nothing else is. That is a rule, not a
default -- resist adding a second solid layer, because two sources of
collision truth is how a platformer starts feeling inconsistent.

Hazards go on the `entity` object layer as objects, not as tiles, so they
can carry damage values and trigger regions.

### Screen space is y-down

Up is negative y. Store `jump_velocity` as a positive number in the table
and negate it at the moment of use, so a designer reading the table is not
doing sign arithmetic in their head.

### Rendering is a sorted queue, not a surface stack

Nothing draws directly. Everything pushes a `BlitToken` into a global pool
keyed by `(depth, priority)` and the renderer flattens the frame into one
`surface.blits()`.

- **Draw order is an integer, not a tree position.**
- A new map layer name only renders if `scripts/core/depth.py` maps it to a
  depth. Adding a layer to a `.tmx` without adding it to `MAP_DEPTH` means
  the layer silently does not draw.

### The lifecycle contract, and the trap in it

`core_<domain>_<action>[_<phase>]` methods are entry points for objects
driven from *outside* the component graph -- scenes, layers, entities, the
root component bound into a layer. A `GameComponent` reached through a
parent's `components` dict is driven by the event bus, which never calls
them; an override there is dead code that neither runs nor errors.

In-tree components register behaviour instead:

```python
self.bind_sync_listener(GameEventType.UPDATE, self.__on_update)
```

The exception: `bind_component()` calls `core_lifecycle_prepare*` and
`core_lifecycle_build` directly, so those do run at bind time.

### Do not restructure the event system

Add event types, listeners and components freely. Do not change dispatch,
`mark_event_handled` consumption, or the listener registries.

`active` gates input. `visible` gates blits and cascades to the subtree.
A window with `visible=False` and `active=True` still eats input,
deliberately.

### Naming

- Classes: `<Paradigm><Usage><Actions><Behavior>` -- `GamePlatformerBody`,
  `GameProjectileEmitter`.
- Engine errors: every one starts `Pyoneer` and ends `Error`, under a
  domain base. Never `raise Exception`.
- Table row ids: `snake_case`, stable once referenced (`plasma_rifle`).
- Columns: `snake_case`; durations end `_ms`, speeds are per second.

### Fail loud

Contract violations raise. Unusable authored content warns. Never fall back
to a plausible default -- a wrong number that runs is the failure mode this
codebase keeps producing, and it costs more to find than a crash.

### Before you finish

```bash
.venv/Scripts/python.exe tools/check_all.py
```

If a smoke field moves, name which one, from what to what, and why, in
`NOTES.md`.
