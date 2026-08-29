## How this genre is built on Pyoneer

Read this before writing anything. It is short on purpose, and every line
in it is a thing that has already gone wrong at least once in this
codebase.

### What an entity DOES is composed, not subclassed

The engine attaches small swappable objects to an entity and runs them once
per frame, in a declared order: `scripts/game/behavior/`. Each has three
methods -- `attach(entity)` / `update(entity, event)` / `detach(entity)` --
declares what it writes, what it requires and what it conflicts with, and is
named on the tmx object itself:

```xml
<property name="pyoneer_behaviors" value="player_input,topdown_move,animation_drive"/>
<property name="pyoneer_param_walk_format" value="walk_{}"/>
```

That list is this genre's controller, and it is what `GamePlayer.input_move`
used to be: `player_input` polls the verbs, `topdown_move` displaces the
entity through `GameEntity.move_direction` (so the collision gate and
`move_speed` are untouched arithmetic), and `animation_drive` names the
sequence on the frame the movement state changes.

**Read `docs/BEHAVIORS.md` before this file.** It is generated from the
registry the engine binds from, so it cannot list a behavior that does not
exist or omit one that does — and prose about which behaviors exist is
exactly what drifts. It also carries the integration status, measured rather
than asserted -- the table there is produced by constructing a real entity and
running frames, so a row saying *no* is a wire that does not exist rather than
one that is merely undocumented. Check it before assuming a capability.

The point of the design, in one sentence: a top-down character and a side-on
one are **the same `GamePlayer` class carrying different behavior lists**, so
"the player" stops being a genre-specific class. Do not add an entity
subclass to change how something moves; add a behavior and put its token on
the object. `topdown_move` and the platformer's body declare that they
conflict, so a list naming both is refused rather than letting two behaviors
write `transform.position` with one silently winning.

`player_input` is the entire marker for "this is the entity the human
drives". An entity without it never polls a key.

### Rendering is a sorted queue, not a surface stack

Nothing draws directly. Everything pushes a `BlitToken` into a global pool
keyed by `(depth, priority)` and the renderer flattens the frame into one
`surface.blits()`. So:

- **Draw order is an integer, not a tree position.** To put something in
  front of the player, give it a higher depth. Do not reorder anything.
- A new map layer name only renders if `scripts/core/depth.py` maps it to a
  depth. `MAP_DEPTH` is that table. Adding a layer to a `.tmx` without
  adding it there means the layer silently does not draw -- which is
  exactly how 39 authored tiles went missing for months.

### The lifecycle contract, and the trap in it

Engine objects implement `core_<domain>_<action>[_<phase>]` --
`core_lifecycle_build`, `core_frame_update`, `core_render_blits`,
`core_input_receive`.

**These are not a general extension point.** They are entry points for
objects driven from *outside* the component graph: scenes, layers,
entities, and the root component bound into a layer. A `GameComponent`
reached through a parent's `components` dict is driven by the event bus,
which never calls them. An override there is dead code that neither runs
nor errors.

In-tree components register behaviour instead:

```python
self.bind_sync_listener(GameEventType.UPDATE, self.__on_update)
```

The one exception: `bind_component()` calls `core_lifecycle_prepare*` and
`core_lifecycle_build` on the child directly, so those specific overrides
*do* run at bind time. `GameScene.begin` then runs the prepare triple a
**second** time on every bound object — which is why a behavior allocates in
`attach` and the behavior contract has no `prepare` hook at all.

### Do not restructure the event system

It is the load-bearing thing. You may add event types, add listeners, and
add components. Do not change how dispatch works, do not change
`mark_event_handled`'s consumption semantics, and do not collapse the
listener registries -- that is planned work with its own measured
migration.

A behavior never needs to. It is *called* from the entity's frame update and
binds nothing, so it can never call `handle()` and silence every sibling for
the rest of the frame. If a behavior you are designing seems to need the bus,
it needs a different design.

`active` gates input. `visible` gates blits and cascades to the subtree.
They are independent: a window with `visible=False` and `active=True`
still eats input, deliberately.

### Entities and the object layer

An object on the `entity` layer names its class in the tmx `type`
attribute. That class must be in `SPAWN_REGISTRY` (`scripts/core/spawn.py`)
-- a Type that is not registered makes the map **raise at load**, so this
pack declares exactly what the registry holds, which today is `GamePlayer`
alone. The earlier list of six named four classes that exist nowhere in the
tree.

The class resolves to a draw depth through `OBJECT_CONVERTER` in
`scripts/core/depth.py`. Custom properties on the object become per-instance
data, and `pyoneer_behaviors` is the one that decides what it does. Two
objects of the same class on one map may carry different lists; that is the
property no other declaration site has, and the reason the list lives on the
object rather than in a table or in the spawn registry.

Object coordinates are **world pixels**, not tiles. Tiled anchors a
rectangle object at its top-left and a tile object at its bottom-left;
mind the difference when placing things.

### Solid is the TILE first, then the cell

`Floor` is art. What blocks movement is a four-bit mask -- down 1, left 2,
right 4, up 8, and a **set** bit means **blocked** -- and it is authored at
two levels, in this order:

1. **The tile's own mask**, in a `.blitmask` beside the map named by the
   tileset's `pyoneer_collision` property. Stamping the tile authors the
   collision, which is the level that scales: give the wall tile `15` once and
   every wall you ever paint is solid.
2. **The cell**, in a **companion tile layer** -- `FloorCollision` by default,
   or whatever `Floor`'s `pyoneer_passability` property names. It exists to say
   *"not THIS one"*: a door left open in a wall, a hole in a fence. A painted
   cell **overrides** the tile default rather than merging with it, so `0`
   (open) over a solid tile is open, and `gid 0` -- an empty cell -- means
   *nobody said anything*, which falls back to the tile.

The companion has no row in the editor's hierarchy on purpose: it declares
`pyoneer_renders=false` and nothing draws it, so the art layer carries a mask
count badge instead. Select the **art** layer, pick a mask swatch, and paint.
Shift+click a map cell gives the TILE under it that mask. Do not author a
third source of truth.

`scripts/core/collision_runtime.py` reads both levels and clamps a move, and
`topdown_move` inherits that gate for free by going through
`GameEntity.move_direction`. Two limits worth knowing before designing
against it: the test is at one anchor point per entity rather than a box, and
blocking is symmetric, so a one-way tile is not expressible. `LayerRenderer`
feeds the gate at bind, from whatever the map declares — and a map that
declares **neither** a tile mask nor a companion feeds it `None`, which means
ungated rather than open. See the
integration table in `docs/BEHAVIORS.md`, which is measured rather than
asserted.

### Data lives in tables, not in code

Actor stats, item effects and equipment modifiers belong in the project
tables (`data/project/tables/*.json`), reached with `table.*` commands.
Do not hardcode a stat in Python. If a stat does not exist yet, add the
column -- `table.column.add` is there precisely so the data model can grow
without an editor change.

A column name is also a **behavior parameter key**: a behavior declaring a
`source="actors"` parameter names the column directly rather than aliasing
it, so the two vocabularies are one vocabulary, and
`tools/check_behavior_docs.py` fails if a behavior claiming this genre
consumes a column this pack does not declare.

**A known discrepancy, recorded so it is not rediscovered:** this pack's
movement column is `speed`, the platformer pack's is `move_speed`, and the
engine's own field and config key are both `move_speed`
(`config/entity.json`). `topdown_move` sidesteps it by taking no parameter at
all and reading `GameEntity.move_speed`, which comes from the config file —
but the first behavior here that *does* want a `source="actors"` speed will
hit it. Renaming this column also changes `tools/check_editor.py`, which pins
both the column count and this column's default, so do it as one change
across all three files.

Equipment modifiers are **additive** and applied while equipped. A weapon
with `attack_mod: 4` on an actor with `attack: 3` gives 7. If you need
multiplicative or conditional modifiers, add columns for them and say so
in `NOTES.md`; do not redefine what the existing columns mean.

### Naming

- Classes: `<Paradigm><Usage><Actions><Behavior>` -- `GameAnimatedEntity`,
  `MouseComponentAsync`, `AssetMapManager`. A behavior class ends `Behavior`:
  `Game<Thing>Behavior`, like `GameTopDownMoveBehavior`.
- Behavior tokens (what goes in the tmx): `snake_case`, stable once
  referenced, never renamed -- the same rule as a table row id, and for the
  same reason. A renamed token silently disarms every object carrying the old
  one, which is why the reader raises on an unknown token instead of skipping
  it.
- Engine errors: every one starts `Pyoneer` and ends `Error`, grouped under
  a domain base. Raise a specific one; never `raise Exception`.
- Table row ids: `snake_case`, stable, never renamed once referenced
  (`iron_sword`, not `Iron Sword`).
- Table columns: `snake_case`. A modifier column ends `_mod`.

### Fail loud

Contract violations raise. Unusable authored content warns via
`warnings`. Never fall back to a plausible default -- this repository has a
documented history of exactly that failure mode, and every instance of it
cost more to find than the crash would have.

### Before you finish

```bash
.venv/Scripts/python.exe tools/check_all.py
```

If you changed a `BehaviorSpec` or a genre pack, regenerate the generated
document first or the docs check fails on the drift:

```bash
.venv/Scripts/python.exe tools/check_behavior_docs.py --write
```

If a smoke field moves, name which one, from what to what, and why, in
`NOTES.md`. Do not re-baseline something you cannot explain.
