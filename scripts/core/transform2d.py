from __future__ import annotations

from pygame import Rect, Vector2


class Transform2D:
    """Where a component sits, and the arithmetic that puts it there.

    Lifted out of `GameComponent`, which carried this alongside eight other
    responsibilities. This is the placement one and nothing else: local
    bounds, world bounds, the shift between them, and the scale/rotation the
    TRANSFORM event writes.

    OFFSET IS A LOCAL->WORLD SHIFT
    ------------------------------
    The one rule this class exists to keep honest:

        world = local + parent.world + offset

    `offset` is the shift that crosses the local -> world boundary, and it is
    applied exactly ONCE, at that crossing. It is never folded into local.

    `GameComponent.move` used to write `local = Rect(x + offset.x, ...)`,
    which is a second, different meaning of the same word -- and because
    world is then derived FROM local, the offset was counted again on the
    next recompute. Measured on a component with offset (7, 3): `move(10,10)`
    left local at (17, 13), and every later re-resolve added (7, 3) again, so
    the component drifted by its own offset on each move-then-resolve. Panels
    set offsets on their children (`panel.py:155`, `:180`), so this was
    reachable rather than theoretical. Gathering every site that touches
    `offset` into one class is what keeps it counted once.

    NO PARENT REFERENCE, NO EVENTS
    ------------------------------
    This deliberately knows nothing about the component tree or the event
    bus: it takes the parent's world rect as an ARGUMENT rather than holding
    a reference to a component. Two reasons, both practical.

    First, it can be exercised without booting a widget tree -- the offset
    contract used to be checkable only by constructing a real ShapeComponent
    and firing real events.

    Second, the dependency points one way: `GameComponent` owns a
    `Transform2D`, and `Transform2D` has never heard of `GameComponent`. The
    five previous refactors that died in this repo all died as new sibling
    modules that imported the incumbent back (see docs/history/ORPHANS.md §1A); this
    one imports pygame and stops.
    """

    def __init__(self, bounds: Rect | None = None):
        self.local: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """Position and size in the PARENT's coordinate space."""
        self.world: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """Position and size in screen space, derived from `local`.

        Seeded as a second, independent copy of the constructor bounds rather
        than an alias of `local`: a component with no parent starts with
        world == local by value, and the two must be able to diverge the
        moment either is written.
        """
        self.offset: Vector2 = Vector2(0, 0)
        """The local -> world shift. See the class docstring."""
        self.scale: Vector2 | float = 1.0
        """Render scale. Written by the TRANSFORM event; read by nobody yet.

        Starts as a float and becomes a Vector2 the first time `scale` is
        dispatched -- preserved as-is, because changing it would change what
        a future reader sees on an untouched component.
        """
        self.rotation: float = 0.0
        """Render rotation. Written by the TRANSFORM event; read by nobody yet."""

    # ---------------------------------------------------------------------
    # Deriving world from local
    # ---------------------------------------------------------------------
    def resolve(self, parent_world: Rect | None) -> None:
        """Recompute world as `local + parent_world + offset`.

        A None `parent_world` means "this is a root" and is a NO-OP, not a
        reset -- a root's world bounds are owned by whoever last wrote them
        (the constructor, `move`, or the `world` setter), and recomputing
        here would silently discard that. `resync` is the entry point that
        does handle the rootless case, and it is deliberately separate: the
        two callers want different things from the same situation.
        """
        if parent_world is None:
            return
        derived = self.local.copy()
        derived.x += parent_world.x + self.offset.x
        derived.y += parent_world.y + self.offset.y
        self.world = derived

    def resync(self, local: Rect, parent_world: Rect | None) -> None:
        """Recompute world from a KNOWN local, root or not.

        `resolve` returns early with no parent, which leaves a root's world
        bounds frozen at whatever the constructor or the last `move` left
        there. For a root there is no parent transform, so world IS local
        plus offset -- the same relation the constructor and `move` assume.

        `local` is passed in rather than read off self because the caller may
        be part-way through a bounds change and holds the authoritative rect.

        Be aware it is honoured ONLY on the rootless branch -- the parented
        branch delegates to `resolve`, which reads `self.local`. Both callers
        in GameComponent pass a rect that is already `self.local` by value, so
        the two agree today; the parameter is not a general "resolve against
        this other rect" knob and must not be used as one.
        """
        if parent_world is None:
            world = local.copy()
            world.x += self.offset.x
            world.y += self.offset.y
            self.world = world
            return
        self.resolve(parent_world)

    # ---------------------------------------------------------------------
    # Writing position
    # ---------------------------------------------------------------------
    def move(self, x: int | float, y: int | float, parented: bool) -> None:
        """Move to local position (x, y).

        Local becomes exactly what the caller asked for; the offset lands on
        world and only on world. See the class docstring for the drift this
        replaced.

        The `parented` branch is asymmetric on purpose, and it is the one
        genuinely surprising thing in this file:

        - rootless, world gets `(x + offset, y + offset)` and keeps its OWN
          previous size, which can differ from local's;
        - parented, LOCAL IS NOT WRITTEN AT ALL, and world is still written
          without the parent's origin -- which disagrees with `resolve`.

        That disagreement is preserved deliberately. The window drag path
        depends on the current behaviour, and correcting it is a separate,
        testable change. See docs/history/ORPHANS.md.
        """
        local = self.local.copy()
        world = self.world.copy()
        if not parented:
            self.local = Rect(x, y, local.width, local.height)
        self.world = Rect(x + self.offset.x, y + self.offset.y,
                          world.width, world.height)

    def set_world(self, bounds: Rect) -> None:
        """Assign world bounds from an outside rect, defensively copied.

        The copy is the point. Rects are mutable and pygame hands the same
        object back from `.copy()`-less accessors all over the engine, so
        storing the caller's rect would alias this transform to whatever they
        mutate next.
        """
        self.world = bounds.copy()

    def adopt_world_as_local(self) -> None:
        """Rewrite local to match world, IN PLACE.

        Used when a component is re-parented while keeping its on-screen
        position: its world rect is the truth, and local has to be restated
        in the new parent's space.

        Mutating the existing Rect rather than replacing it is load-bearing.
        `GameComponent.local_bounds`'s setter fires the bounds-changed
        cascade -- children rebase, surfaces reallocate -- and re-parenting
        happens inside `__init__`, before the child dict or any surface
        exists. Writing the fields directly is how it stays quiet.
        """
        world = self.world
        self.local.x = world.x
        self.local.y = world.y
        self.local.width = world.width
        self.local.height = world.height

    # ---------------------------------------------------------------------
    # Points
    # ---------------------------------------------------------------------
    def shift_point(self, point: Vector2) -> Vector2:
        """Carry a point across the same local -> world boundary as `offset`.

        Mutates the caller's Vector2 and returns it. No current caller reads
        the argument afterwards -- Panel's two hit-test paths use the return
        value -- but the mutation is observable from outside, so it is part
        of the behaviour and is preserved rather than quietly copied away.
        """
        point.x += self.offset.x
        point.y += self.offset.y
        return point

    def __str__(self):
        return (f"Transform2D: local={tuple(self.local)} world={tuple(self.world)} "
                f"offset=({self.offset.x}, {self.offset.y})")
