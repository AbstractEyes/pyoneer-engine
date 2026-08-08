## How this genre is built on Pyoneer

Read this before writing anything. It is short on purpose, and every line
in it is a thing that has already gone wrong at least once in this
codebase.

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
*do* run at bind time.

### Do not restructure the event system

It is the load-bearing thing. You may add event types, add listeners, and
add components. Do not change how dispatch works, do not change
`mark_event_handled`'s consumption semantics, and do not collapse the
listener registries -- that is planned work with its own measured
migration.

`active` gates input. `visible` gates blits and cascades to the subtree.
They are independent: a window with `visible=False` and `active=True`
still eats input, deliberately.

### Entities and the object layer

An object on the `entity` layer names its class in the tmx `type`
attribute. That class resolves to a draw depth through `OBJECT_CONVERTER`
in `scripts/core/depth.py`. Custom properties on the object become
per-instance data.

Object coordinates are **world pixels**, not tiles. Tiled anchors a
rectangle object at its top-left and a tile object at its bottom-left;
mind the difference when placing things.

### Data lives in tables, not in code

Actor stats, item effects and equipment modifiers belong in the project
tables (`data/project/tables/*.json`), reached with `table.*` commands.
Do not hardcode a stat in Python. If a stat does not exist yet, add the
column -- `table.column.add` is there precisely so the data model can grow
without an editor change.

Equipment modifiers are **additive** and applied while equipped. A weapon
with `attack_mod: 4` on an actor with `attack: 3` gives 7. If you need
multiplicative or conditional modifiers, add columns for them and say so
in `NOTES.md`; do not redefine what the existing columns mean.

### Naming

- Classes: `<Paradigm><Usage><Actions><Behavior>` -- `GameFloorEntity`,
  `MouseComponentAsync`, `AssetMapManager`.
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

If a smoke field moves, name which one, from what to what, and why, in
`NOTES.md`. Do not re-baseline something you cannot explain.
