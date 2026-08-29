## How this genre is built on Pyoneer

Read this before writing anything.

### What the engine already gives you, honestly

Re-derived against the tree, not inherited. Five rows of the previous
revision's table were false by the time it was read: gravity, a jump, air
control, tile collision and a spawn system all exist now.

| you get | you do not get |
|---|---|
| deferred depth-sorted rendering | a one-way platform (the mask vocabulary is symmetric) |
| tile map loading and compositing | a swept or box collider; the test is one anchor point |
| a spawn path that reads each object's `pyoneer_behaviors` and composes it | a genre pack's default list being applied for you -- the object carries its own |
| gravity, terminal velocity, air control and a jump with coyote time -- the `platformer_move` behavior | jump *buffering* (pressing early, before landing) |
| a passability gate baked at map load from a tileset's own tile masks AND from companion layers, handed to every entity bound | a body gated on a map that declares neither -- that bakes `None`, which is ungated |
| behavior composition: swap what an entity does by editing a list | a class-free way to mark which object the human drives; that is `player_input` in the list |
| input actions with real edge detection, `jump` among them | a behavior parameter that is not declared in its own spec -- the actors table fills declared keys, it does not invent them |

**Read `docs/BEHAVIORS.md` before this file.** It is generated from the
registry the engine binds from, so it cannot describe a behavior that does
not exist or omit one that does; this table can, and has. It also carries the
integration status, measured rather than asserted.

So a platformer request against this engine is now mostly a *data* change:
compose the right behavior list and fill in the actors row. Say in `NOTES.md`
which parts were data and which were code.

### A platformer player is not a class

This is the load-bearing paragraph of this file.

There is no platformer-specific subclass of `GamePlayer` and there must not
be one. The previous revision sent you to write a `game_platformer_body.py`
holding a component that owns velocity, and named two classes that exist
nowhere in the tree. A side-on player and a top-down player are **the same
`GamePlayer` class carrying a different behavior list**:

```xml
<!-- a top-down character -->
<property name="pyoneer_behaviors" value="player_input,topdown_move,animation_drive"/>

<!-- a side-on character: same class, same spawn entry, different list -->
<property name="pyoneer_behaviors" value="player_input,platformer_move,animation_drive"/>
<property name="pyoneer_param_jump_verb" value="jump"/>
<property name="pyoneer_param_initial_sequence" value="idle_right"/>
```

`platformer_move` and `topdown_move` declare that they **conflict**, so a
list naming both is refused at attach rather than producing two behaviors
that both write `transform.position` and one silently winning.

`player_input` is the entire marker for "this is the entity the human
drives". An entity without it never polls a key, so five inert decoys and one
player are one class and one spawn entry, distinguished by one token.

### Where the code goes

- **A behavior**, in `scripts/game/behavior/`, deriving `EntityBehavior` --
  `attach(entity)` / `update(entity, event)` / `detach(entity)`, no event-bus
  presence. Register it in `scripts/game/behavior/registry.py` with a
  `BehaviorSpec` declaring what it writes, what it requires, what it conflicts
  with, its run order, and the actors columns it consumes. Name it
  `Game<Thing>Behavior`, like `GamePlatformerMoveBehavior`. The step-by-step
  is in `docs/BEHAVIORS.md`; do not restate it here, because a second copy of
  a procedure drifts from the first.
- **Not** a `GameComponent`. That class is the widget machinery -- bounds,
  anchor, viewport, a callbacks dict -- and an entity wants none of it. A
  behavior is *called* from the entity's frame update, never dispatched to,
  which is what keeps it clear of the event system entirely.
- **Not** a new entity subclass. If you are about to add one to change how
  something moves, the thing you want is a behavior.
- Tunables belong in the `actors` table, never as Python literals.
  `platformer_move` already consumes `move_speed`, `jump_velocity`,
  `gravity`, `max_fall_speed`, `air_control` and `coyote_ms` -- a behavior
  claims a column by declaring a `BehaviorParam` whose key **is the column
  name**, not a private alias. Every one of those columns is declared by this
  pack, and `tools/check_behavior_docs.py` fails if a behavior ever consumes
  one that is not.

### Four things that will bite a platformer body

1. **A map that declares neither a tile mask nor a companion bakes `None`, and
   `None` means UNGATED.** The field IS assigned -- `LayerRenderer` bakes the
   map's passability at bind and hands it to every entity, both routes -- so a
   body falling forever is not a missing wire, it is a map with nothing
   authored on it. Give the ground tileset a `.blitmask` (one mask per tile, in
   the palette) or paint cells on the art layer; either alone produces a field.
   Check the integration table in `docs/BEHAVIORS.md`, which is measured.
2. **An authoring error in the list raises at LOAD, not at play.** An unknown
   token, a duplicate, or two behaviors that conflict all stop the map from
   spawning and name the `<object>` that carried them. That is deliberate: a
   token silently skipped would disarm every object carrying it and look
   exactly like the behavior working. Rename a token and you break maps, which
   is why a token is stable once referenced.
3. **`delta` is milliseconds ÷ 60, not seconds.** `main.py` divides elapsed
   milliseconds by the target tick rate. The columns above are documented in
   pixels per second, so a number used raw is about 16.7× wrong in a way that
   still looks like it works. `platformer_move` converts through
   `SECONDS_PER_DELTA`; anything new must too.
4. **Jump-through platforms are not expressible.** Blocking is per-cell and
   symmetric — one bit governs both crossings of an edge — so falling through
   a ledge and landing on it cannot both be authored. That is a vocabulary
   change in `scripts/core/collision_runtime.py`, not something to fake in a
   behavior.

### Solid is the tile's own mask, then the cell -- never the Floor gid

A non-zero gid on `Floor` is **not** solid. `Floor` is art. Passability is a
four-bit mask -- down 1, left 2, right 4, up 8, and a **set** bit means
**blocked** -- authored at two levels, strongest last:

1. **The tile's own mask**, in a `.blitmask` beside the map named by the
   tileset's `pyoneer_collision` property. Stamping the tile authors the
   collision. For a platformer this is the level you want: give the ground tile
   `BLOCK_UP` (8) once and every platform you paint supports a body.
2. **The cell**, in a **companion tile layer** -- `FloorCollision` by default,
   or whatever `Floor`'s `pyoneer_passability` property names. It says *"not
   THIS one"*. A painted cell **overrides** the tile default rather than
   merging with it, and `gid 0` -- an empty cell -- means *nobody said
   anything*, which falls back to the tile.

Two levels, one resolution order, still exactly one source of collision truth.
Do not add a third. A doorway and its frame come from the same tileset, which
is precisely why the tile's mask is a default and the cell can contradict it.

The companion has no row in the editor's hierarchy: it declares
`pyoneer_renders=false` and nothing draws it. Select the **art** layer, pick a
mask swatch, and paint; shift+click a map cell to give the TILE under it that
mask instead.

Hazards go on the `entity` object layer as objects, not as tiles, so they can
carry damage values and trigger regions.

### An object's Type must be spawnable

The `entity` layer declares `GamePlayer` and nothing else, because
`SPAWN_REGISTRY` in `scripts/core/spawn.py` contains `GamePlayer` and nothing
else — and an object whose Type is not registered makes the whole map **raise
at load**. The earlier list of six classes named four that exist nowhere in
the tree. To place a new kind of thing, register the class first; this list
mirrors the registry and is not a wish list.

What distinguishes two objects of that one class is their behavior list.

### Screen space is y-down

Up is negative y. `jump_velocity` is stored as a **positive** number in the
table and negated at the instant of use, so a designer reading the table is
not doing sign arithmetic in their head. `platformer_move` already does this;
match it.

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
`core_lifecycle_build` directly, so those do run at bind time. Note also that
`GameScene.begin` runs the prepare triple a **second** time on every bound
object — which is why a behavior allocates in `attach` and the behavior
contract has no `prepare` hook at all.

### Do not restructure the event system

Add event types, listeners and components freely. Do not change dispatch,
`mark_event_handled` consumption, or the listener registries. A behavior
never needs to: it is called from the entity's frame update and binds
nothing, so it can never call `handle()` and silence its siblings for the
rest of the frame.

`active` gates input. `visible` gates blits and cascades to the subtree.
A window with `visible=False` and `active=True` still eats input,
deliberately.

### Naming

- Classes: `<Paradigm><Usage><Actions><Behavior>` -- `GameAnimatedEntity`,
  `GameSceneMap`. A behavior class ends `Behavior`: `Game<Thing>Behavior`.
- Behavior tokens (what goes in the tmx): `snake_case`, stable once
  referenced, never renamed — the same rule as a table row id and for the
  same reason. A renamed token silently disarms every object carrying the old
  one, which is why the reader raises on an unknown token instead of skipping
  it.
- Engine errors: every one starts `Pyoneer` and ends `Error`, under a domain
  base. Never `raise Exception`.
- Table row ids: `snake_case`, stable once referenced (`plasma_rifle`).
- Columns: `snake_case`; durations end `_ms`, speeds are per second. A column
  name is also a behavior parameter key, so the two are one vocabulary.

### Fail loud

Contract violations raise. Unusable authored content warns. Never fall back
to a plausible default -- a wrong number that runs is the failure mode this
codebase keeps producing, and it costs more to find than a crash.

### Before you finish

```bash
.venv/Scripts/python.exe tools/check_all.py
```

If you changed a `BehaviorSpec` or a genre pack, regenerate the document
first, or the docs check fails on the drift:

```bash
.venv/Scripts/python.exe tools/check_behavior_docs.py --write
```

If a smoke field moves, name which one, from what to what, and why, in
`NOTES.md`.
