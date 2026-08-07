# archive/

Superseded component systems. **Nothing here is importable or on the engine's
import path.** Kept for design reference, not for use.

Pyoneer's component layer went through three generations:

### `gen1_widget_deprecated/` — `Widget` + `WidgetState*`

The original UI layer. A `Widget` ABC paired with a parallel hierarchy of
state objects (`WidgetState`, `WidgetStateInteractive`, `WidgetStateWindow`, …)
holding the bounds/colour/visibility that the widget itself did not.
Superseded by generation 2, which folded state back onto the component.

Until Segment 0 this tree was still pinned into the boot path by a single
import in `main.py` (`WidgetDrawableGroup`, used only in a type annotation),
which is why it could never be removed.

### generation 2 — `scripts/core/component.py` — `GameComponent` — **LIVE**

The system the engine currently runs on. Everything under
`scripts/core/ui/widget/` derives from it, and it is what `main.py` binds.
Not archived; this is the real one.

### `gen3_behavior_rewrite/` — `SimpleComponent` + `Behavior`

An unfinished rewrite of generation 2. **It never executed a single line**:
it lived at `scripts/core/component/`, a package permanently shadowed by the
`scripts/core/component.py` module of the same name, so `import component`
always resolved to generation 2 and never to this package.

It is preserved because it records the intended direction, and that direction
is broadly the right one:

- `SimpleComponent` is thin — identity, a behavior bag, and a per-frame
  `handled_events` list. It is not a god object.
- `Behavior` owns its own `listeners` dict, so event wiring lives with the
  behavior that needs it instead of on a shared base class.
- `bind_listener` takes an `EventPriority`, making dispatch order explicit
  rather than dependent on dict insertion order.
- Lifecycle is `create(component)` / `destroy()` — real symmetry, which
  generation 2 lacks (it has no working unbind path at all).

Generation 2 accumulated nine responsibilities on one class. The planned
decomposition (see `docs/IMPROVEMENT_PLAN.md`, Segment 8) splits it into
composed objects, which lands close to what this tree was reaching for —
so read it before designing that split.

The one thing not to carry forward: `Behavior.call()` indexes
`self.listeners[event]` directly and raises `KeyError` for any event type
with no registered listener.
