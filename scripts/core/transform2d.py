from __future__ import annotations

from pygame import Rect, Vector2


class Transform2D:
    """Where a component sits, and the arithmetic that puts it there.

    Placement and nothing else: local bounds, world bounds, the shift between
    them, and the scale/rotation the TRANSFORM event writes.

    OFFSET IS A LOCAL->WORLD SHIFT, and it is the rule this class exists to
    keep honest:

        world = local + parent.world + offset

    `offset` crosses the local -> world boundary and is applied exactly ONCE,
    at that crossing. It is never folded into local -- world is derived FROM
    local, so an offset written into local is counted again on every
    recompute and the component drifts by its own offset on each
    move-then-resolve. Panels set offsets on their children, so that is
    reachable rather than theoretical.

    It knows nothing about the component tree or the event bus: the parent's
    world rect is an ARGUMENT, not a held reference. So the offset contract
    can be exercised without booting a widget tree, and the dependency points
    one way -- `GameComponent` owns a `Transform2D`, which has never heard of
    `GameComponent`.
    """

    def __init__(self, bounds: Rect | None = None):
        self.local: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """Position and size in the PARENT's coordinate space."""
        self.world: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """Position and size in screen space, derived from `local`.

        A second, independent copy of the constructor bounds rather than an
        alias of `local`: the two start equal by value and must be able to
        diverge the moment either is written.
        """
        self.offset: Vector2 = Vector2(0, 0)
        """The local -> world shift. See the class docstring."""
        self.scale: Vector2 | float = 1.0
        """Render scale. Written by the TRANSFORM event; read by nobody yet.

        Starts as a float and becomes a Vector2 the first time `scale` is
        dispatched, so a reader must accept either.
        """
        self.rotation: float = 0.0
        """Render rotation. Written by the TRANSFORM event; read by nobody yet."""

    # ---------------------------------------------------------------------
    # Deriving world from local
    # ---------------------------------------------------------------------
    def resolve(self, parent_world: Rect | None) -> None:
        """Recompute world as `local + parent_world + offset`.

        A None `parent_world` means "this is a root" and is a NO-OP, not a
        reset: a root's world bounds are owned by whoever last wrote them --
        the constructor, `move`, or the `world` setter -- and recomputing here
        would discard that. `resync` is the entry point for the rootless case.
        """
        if parent_world is None:
            return
        derived = self.local.copy()
        derived.x += parent_world.x + self.offset.x
        derived.y += parent_world.y + self.offset.y
        self.world = derived

    def resync(self, local: Rect, parent_world: Rect | None) -> None:
        """Recompute world from a KNOWN local, root or not.

        For a root there is no parent transform, so world IS local plus
        offset. `local` is passed in rather than read off self because the
        caller may be part-way through a bounds change and hold the
        authoritative rect.

        It is honoured ONLY on the rootless branch: the parented branch
        delegates to `resolve`, which reads `self.local`. This is not a
        general "resolve against some other rect" knob and must not be used
        as one.
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
        world and only on world.

        The `parented` branch is asymmetric, and it is the one genuinely
        surprising thing in this file:

        - rootless, world gets `(x + offset, y + offset)` and keeps its OWN
          previous size, which can differ from local's;
        - parented, LOCAL IS NOT WRITTEN AT ALL, and world is still written
          without the parent's origin -- which disagrees with `resolve`.

        The disagreement is preserved deliberately: the window drag path
        depends on it, and correcting it is a separate change.
        """
        local = self.local.copy()
        world = self.world.copy()
        if not parented:
            self.local = Rect(x, y, local.width, local.height)
        self.world = Rect(x + self.offset.x, y + self.offset.y,
                          world.width, world.height)

    def set_world(self, bounds: Rect) -> None:
        """Assign world bounds from an outside rect, defensively copied.

        The copy is the point: Rects are mutable, so storing the caller's rect
        would alias this transform to whatever they mutate next.
        """
        self.world = bounds.copy()

    def adopt_world_as_local(self) -> None:
        """Rewrite local to match world, IN PLACE.

        Used when a component is re-parented while keeping its on-screen
        position: world is the truth, and local has to be restated in the new
        parent's space.

        Mutating the existing Rect rather than replacing it is load-bearing.
        `GameComponent.local_bounds`'s setter fires the bounds-changed cascade
        -- children rebase, surfaces reallocate -- and re-parenting happens
        inside `__init__`, before the child dict or any surface exists.
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

        MUTATES the caller's Vector2 and returns it.
        """
        point.x += self.offset.x
        point.y += self.offset.y
        return point

    def __str__(self):
        return (f"Transform2D: local={tuple(self.local)} world={tuple(self.world)} "
                f"offset=({self.offset.x}, {self.offset.y})")
