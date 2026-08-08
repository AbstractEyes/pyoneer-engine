from __future__ import annotations

from abc import ABC
from typing import Callable, Type, Optional

from pygame import Rect, Vector2, surface

from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject

from scripts.core.event_types import GameEventType
#from scripts.game.game_camera import GameCamera

from config.managers.core_asset_manager import CoreAssetManager
from scripts.core.errors import (PyoneerAlreadyBoundError, PyoneerAssetMissingError,
                                 PyoneerError, PyoneerEventDispatchError,
                                 PyoneerEventTypeError,
                                 PyoneerListenerContractError)

Config = CoreAssetManager()

INPUT_EVENT_TYPES: frozenset[GameEventType] = frozenset({
    GameEventType.INPUTS,
    GameEventType.MOUSE_MOTION, GameEventType.MOUSE_DOWN, GameEventType.MOUSE_UP,
    GameEventType.MOUSE_SCROLL, GameEventType.MOUSE_CLICK, GameEventType.MOUSE_DOUBLE_CLICK,
    GameEventType.MOUSE_DOWN_INSIDE, GameEventType.MOUSE_UP_INSIDE,
    GameEventType.MOUSE_DOWN_OUTSIDE, GameEventType.MOUSE_UP_OUTSIDE,
    GameEventType.MOUSE_DRAGGING, GameEventType.MOUSE_DRAG_BEGIN, GameEventType.MOUSE_DRAG_END,
    GameEventType.MOUSE_CLICK_INSIDE, GameEventType.MOUSE_DOUBLE_CLICK_INSIDE,
    GameEventType.MOUSE_ENTER, GameEventType.MOUSE_LEAVE,
    GameEventType.KEY_DOWN, GameEventType.KEY_UP, GameEventType.KEY_REPEAT,
    GameEventType.GAMEPAD_BUTTON_PRESSED, GameEventType.GAMEPAD_BUTTON_RELEASED,
    GameEventType.GAMEPAD_BUTTON_HELD, GameEventType.GAMEPAD_AXIS, GameEventType.GAMEPAD_HAT,
})
"""Event types gated by `GameComponent.active`.

Lifecycle events (PREPARE, UPDATE, BLITS, DISPOSE...) are deliberately NOT
in here: a disabled component must still lay out, draw and tear down.
"""


# The component components are the building blocks of the deprecated.
class GameComponent(PyoneerGameObject, ABC):
    """A simple component that can be used to build more complex components.
        \n
        Attributes:\n
        - bounds: The bounds of the component component.
        - __build: The build callback for the component component.
            This builds the component before initial use.
        - __events: This buffer accepts any custom event input and is used for data processing.
            This accepts any buffer argument required to make the component component work.
        - __prepare: The prepare callback for the component component.
            This prepares the component before rendering and after building.
        - __pre_update: The pre-update callback for the component component.
            This is pre-update, used for additional processing before updating.
        - __update: The update callback for the component component.
            This is update, standard updates go here.
        - __post_update: The post-update callback for the component component.
            This is post-update, used for additional processing after updating.
        - __dispose: The dispose callback for the component component.
            This is dispose, used for cleanup.
        - __rebuild: The rebuild callback for the component component.
            This is rebuild, used for rebuilding the component component.
        - __blits: The blits callback for the component.
            This is blits, returns a compounded list of blits for all the components.
        - __use: The use callback for the component.
            This is use, when the component is used by the user or another component directly.
    """

    def __init__(self,
                 parent: GameComponent | None = None,
                 bounds: Rect | None = None,
                 screen_area: Rect | None = None,
                 working_area: Rect | None = None,
                 visible: bool = True,
                 focused: bool = False,
                 active: bool = True,
                 clickable: bool = False,
                 draggable: bool = True,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__base_bounds: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """The base bounds of the component, used for default positioning."""
        self.__local_bounds: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """The bounds of the component, used for dynamic positioning."""
        self.__world_bounds: Rect = bounds.copy() if bounds is not None else Rect(0, 0, 0, 0)
        """The world bounds of the component, used for positioning in the world."""
        self.__offset: Vector2 = Vector2(0, 0)
        """The offset value that determines where the component is interacted with or drawn."""
        self.__scale: float = 1.0
        """The scale of the component, used for rendering size."""
        self.__rotation: float = 0.0
        """The rotation of the component, used for rendering rotation."""
        #self.__depth: int = 0
        #"""The depth of the component, used for rendering order."""
        # ---------------------------------------------------------------------------------------- #
        # behavior
        self.is_view: bool = False
        """The view state of the component, used for rendering positioning."""
        self.visible: bool = visible
        """Whether the component is DRAWN. Rendering only.

        Deliberately not consulted by the event path: a window can be hidden
        and still live, and hiding it must not silently disable it. Use
        `active` to disable a subtree.
        """
        self._focused: bool = focused
        """Backing field for `focused`; see the property below."""
        self.active: bool = active
        """Whether the component participates in input dispatch.

        Defaults True. Setting it False skips this component AND its subtree
        for input-class events, while leaving rendering untouched.
        """
        self.clickable: bool = clickable
        """A manually allocated clickable flag for the component."""
        self.focusable: bool = False
        """Whether this component can take keyboard focus when clicked.

        Text entry sets this; decorative components leave it False so a click
        on a label does not steal focus from the field next to it.
        """
        self.draggable: bool = draggable
        """A manually allocated draggable flag for the component."""
        # ---------------------------------------------------------------------------------------- #
        # parent/child hierarchy system
        self.__parent: GameComponent | None = None
        """The parent of the component, used for hierarchy."""
        self.bind_parent(parent, preserve_world_bounds=False)

        self.callbacks: dict[GameEventType, list[Callable]] = {}
        """The event callbacks for the component, used for event handling."""
        self.async_callbacks: dict[GameEventType, list[Callable]] = {}
        """The async event callbacks for the component, used for event handling."""

        self.components: dict[str, GameComponent] = {}
        """The components of the component, used for building complex components."""
        self.manager: PyoneerGameObject | None = None
        """A defined event manager, used for event handling.\n
            Managers and self can only send messages to each other.\n
            If none, accepts events from anything.
        """
        self.__screen_area: Rect = self.__local_bounds.copy() if screen_area is None else screen_area
        """The screen display zone of the component used for viewport clipping, default x=0, y=0, w=self.__bounds.width/height."""
        self.__working_area: Rect = Rect(0, 0, self.__local_bounds.width, self.__local_bounds.height) if working_area is None else working_area
        """The actual internal working area for more complex panels and the like, potentially any size."""
        self.__use_immediate_viewport: bool = True
        """Whether the component uses the immediate viewport or the next one up."""
        self.component_type = "component"
        """The type of the component used for logical separation, not always needed."""

    def core_lifecycle_prepare(self, event: PyoneerEvent | None = None):
        """Populate the events for the component."""
        super().core_lifecycle_prepare(event)
        if not self.flags.get("prepared_base", False):
            self.bind_sync_listener(GameEventType.PARENT_CHANGED, self.__on_parent_changed)
            self.bind_sync_listener(GameEventType.TRANSFORM, self.__transform_component)
            self.flags["prepared_base"] = True
        return self.send_event_advanced(event_type=GameEventType.PREPARE, event=event)

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        """Build the component."""
        if self.flags.get("built", False):
            return
        return self.send_event_advanced(event_type=GameEventType.BUILD, event=event)

    @property
    def offset(self) -> Vector2:
        return self.__offset

    @offset.setter
    def offset(self, value: Vector2):
        self.__offset = value

    @property
    def use_immediate_viewport(self) -> bool:
        return self.__use_immediate_viewport

    @use_immediate_viewport.setter
    def use_immediate_viewport(self, value: bool):
        for name, component in self.components.items():
            component.use_immediate_viewport = value
        self.__use_immediate_viewport = value

    @property
    def depth(self) -> int:
        """This component's depth, accumulated through the parent chain."""
        depth_ = super().depth
        if self.__parent is not None:
            depth_ += self.__parent.depth
        return depth_

    @depth.setter
    def depth(self, value: int) -> None:
        """Set this component's OWN depth contribution.

        Redefining `depth` as a property here replaced the whole property
        object inherited from PyoneerGameObject, taking its setter with it --
        so `component.depth = 5` raised
        `AttributeError: property 'depth' of 'X' object has no setter`.
        Every component was depth-immutable after construction, which made
        raising a window to the front impossible, while the identical
        assignment kept working on entities (they do not override it).
        """
        PyoneerGameObject.depth.fset(self, value)

    @property
    def parent(self) -> GameComponent | None:
        return self.__parent

    @parent.setter
    def parent(self, parent_in: GameComponent | None = None):
        self.__parent = parent_in

    def move(self, x: int | float, y: int | float, sender: GameComponent | None = None):
        # determine the difference between the current x/y and the new x/y
        local = self.local_bounds.copy()
        world = self.world_bounds.copy()
        if self.__parent is None:
            self.__local_bounds = Rect(x + self.offset.x, y + self.offset.y, local.width, local.height)
            self.__world_bounds = Rect(x + self.offset.x, y + self.offset.y, world.width, world.height)
        else:
            self.__world_bounds = Rect(x + self.offset.x, y + self.offset.y, world.width, world.height)

        if sender is None:
            sender = self

        self.send_event_to_children_advanced(GameEventType.TRANSFORM,
                                             PyoneerEvent(event_type=GameEventType.TRANSFORM,
                                                          sender=sender,
                                                          data={"parent_moved": True}))

    def scale(self, scale: Vector2 | None = Vector2(1, 1), sender: GameComponent | None = None):
        self.__scale = scale
        if sender is None:
            self.send_event_to_children_advanced(GameEventType.TRANSFORM, PyoneerEvent(GameEventType.TRANSFORM, sender=self, data={"parent_moved": True}))

    def rotate(self, rotation: float, sender: GameComponent | None = None):
        self.__rotation = rotation
        if sender is None:
            self.send_event_to_children_advanced(GameEventType.TRANSFORM, PyoneerEvent(GameEventType.TRANSFORM, sender=self, data={"parent_moved": True}))

    @property
    def world_bounds(self) -> Rect:
        """Returns a prepared bounds object based on the parent component hierarchy."""
        return self.__world_bounds

    def __transform_component(self, event: PyoneerEvent | None = None):
        """Handle the parent moved event."""
        # if data is not empty
        any_transformed = False
        if event is not None and event.data is not None:
            parent_moved = event.data.get("parent_moved", False)
            position = event.data.get("position", None)
            scale = event.data.get("scale", None)
            rotation = event.data.get("rotation", None)
            offset = event.data.get("offset", None)
            if parent_moved:
                #print("Transforming; Parent Moved: ", self, event.data)
                self.__update_world_bounds(event)
                any_transformed = True
            if isinstance(position, Vector2):
                self.move(position.x, position.y, self)
                any_transformed = True
            if isinstance(scale, Vector2):
                self.scale(scale, self)
                any_transformed = True
            elif isinstance(scale, tuple):
                self.scale(Vector2(scale[0], scale[1]), self)
                any_transformed = True
            elif isinstance(scale, float | int):
                self.scale(Vector2(scale, scale), self)
                any_transformed = True
            if isinstance(rotation, float):
                self.rotate(rotation, self)
                any_transformed = True
            elif isinstance(rotation, tuple):
                self.rotate(rotation[0], self)
                any_transformed = True
            elif isinstance(rotation, int):
                self.rotate(rotation / 360.0, self)
                any_transformed = True
            if isinstance(offset, Vector2):
                self.offset = offset
                any_transformed = True
        #self.__force_update_world_bounds(event)
        #if any_transformed:
        #    self.send_event_to_children_advanced(event_type=GameEventType.TRANSFORM,
        #                                         event=PyoneerEvent(GameEventType.TRANSFORM, sender=self, data={"parent_moved": True}))

    def force_update_transforms(self):
        self.send_event_to_children_advanced(event_type=GameEventType.TRANSFORM,
                                             event=PyoneerEvent(GameEventType.TRANSFORM, sender=self,
                                                       data={"parent_moved": True}))

    def __update_world_bounds(self, event: PyoneerEvent | None = None):
        """Update the world bounds of the component."""
        if self.parent is None:
            return
        base_bounds = self.__local_bounds.copy()
        base_bounds.x += self.__parent.world_bounds.x + self.offset.x
        base_bounds.y += self.__parent.world_bounds.y + self.offset.y
        self.__world_bounds = base_bounds

    @property
    def adjusted_bounds(self) -> Rect:
        """Returns the adjusted bounds of the component by using the adjusted position."""
        bounds = self.world_bounds.copy()
        bounds.topleft = self.adjusted_position(bounds.topleft)
        return self.world_bounds  # by default this does nothing, but can be overridden to adjust the bounds based on the scroll position

    @world_bounds.setter
    def world_bounds(self, bounds: Rect):
        """Accepts an unfiltered bounds object and sets the bounds of the component."""
        self.__world_bounds = bounds.copy()

    @property
    def viewport(self) -> Rect | None:
        """Returns a filtered bounds object based on the parent component hierarchy."""
        bounds = self.world_bounds.copy()
        if self.is_view:
            return bounds
        if self.__parent is not None and self.__parent.is_view:
            parent_view = self.__parent.world_bounds
            bounds.topleft = parent_view.topleft
            bounds.w, bounds.h = parent_view.w, parent_view.h
        if self.__parent is not None:
            if self.__parent.is_view:
                return self.__parent.world_bounds
        return bounds

    @property
    def screen_area(self) -> Rect:
        """Returns the direct screen display area of the component."""
        if self.is_view:
            return self.__screen_area
        viewport = self.get_viewport_component
        if viewport is not None:
            return viewport.screen_area
        return self.__screen_area # no viewport, lets grab the immediate working area instead.

    @screen_area.setter
    def screen_area(self, bounds: Rect):
        """Sets the screen area of the component, directly connected with viewport."""
        self.__screen_area = bounds

    @property
    def working_area(self) -> Rect:
        """Returns the working area of the component."""
        return self.__working_area

    @working_area.setter
    def working_area(self, bounds: Rect):
        """Sets the working area of the component."""
        self.__working_area = bounds

    @property
    def clipped_working_area(self) -> Rect:
        """Returns the CLIPPED working area of the component using the viewport."""
        viewport = self.get_viewport_component
        if viewport is not None:
            # we have a viewport, so we should clip the working area to the viewport
            return self.__screen_area.clip(viewport.screen_area)
        return self.__screen_area

    @property
    def get_viewport_component(self) -> GameComponent | None:
        """Finds the viewport defining the draw bounds of this component."""
        use_this_viewport = self.use_immediate_viewport
        if self.is_view:
            if use_this_viewport:
                return self
            else:
                use_this_viewport = True
        # okay this isn't the view, so we should check the parents until we find the view
        par = self.parent
        if par is None:
            return None
        if par is not None and isinstance(par, GameComponent) and par.is_view:
            if use_this_viewport:
                return par
            else:
                use_this_viewport = True
        # the immediate parent isn't a viewport, so lets iterate higher.
        while par is not None and use_this_viewport:
            par = par.parent
            if par is None:
                return None
            if isinstance(par, GameComponent) and par.is_view and use_this_viewport:
                return par
        # this and none of it's parents are viewports, we return None due to having no viewport
        # this identifies the screen itself as the sole viewport
        return None

    def __get_difference(self, bounds1: Rect, bounds2: Rect):
        """Return the difference between the current bounds and the new bounds."""
        return (bounds1.x - bounds2.x, bounds1.y - bounds2.y, bounds1.width - bounds2.width, bounds1.height - bounds2.height)

    @property
    def local_bounds(self) -> Rect:
        """Returns the raw bounds of the component."""
        return self.__local_bounds

    @local_bounds.setter
    def local_bounds(self, bounds: Rect | Vector2):
        """Assign local bounds and cascade the consequences.

        This used to be a bare assignment, which meant a post-construction
        bounds change reached nothing: not the component's own world bounds,
        not its children, not its surface. Measured on the scroll thumb --
        set `vertical_scroll.scrollable_bounds` and re-run the scroll update
        and `thumb.local_bounds` becomes h=6 while `thumb.world_bounds` and
        the surface of its "background" child both stay at h=118.
        """
        if isinstance(bounds, Vector2):
            new_bounds = Rect(bounds.x, bounds.y, self.__local_bounds.w, self.__local_bounds.h)
        else:
            new_bounds = bounds
        previous = self.__local_bounds
        unchanged = (previous.x == new_bounds.x and previous.y == new_bounds.y
                     and previous.w == new_bounds.w and previous.h == new_bounds.h)
        previous = previous.copy()
        self.__local_bounds = new_bounds
        if unchanged:
            return
        self._on_bounds_changed(previous, new_bounds.copy())

    # ---------------------------------------------------------------------------------------------
    # Bounds-changed cascade
    # ---------------------------------------------------------------------------------------------
    def _on_bounds_changed(self, previous: Rect, current: Rect):
        """React to a change of THIS component's local bounds.

        The order is the contract: world bounds, then CHILDREN, then this
        component's own SURFACE.

        - world bounds first, because everything below reads them;
        - children next, because a container's own appearance is a function
          of where its children ended up, and a child repaints from its own
          (now corrected) world bounds;
        - the surface last, because DrawComponent.resize() repaints from
          world_bounds and must see the settled values.
        """
        self.__resync_world_bounds(current)
        moved = previous.topleft != current.topleft
        resized = previous.size != current.size
        if not (moved or resized):
            return
        for child in tuple(self.components.values()):
            child.notify_parent_bounds_changed(self)
        if resized:
            self._on_size_changed(current.width, current.height)

    def notify_parent_bounds_changed(self, parent: GameComponent):
        """A parent moved or resized; rebase this subtree onto it.

        Only positions are rebased here. A child's SIZE is not a function of
        its parent's size in the general case -- containers that do want that
        relationship (Button, ScrollComponent) express it by assigning their
        children's `local_bounds`, which re-enters the cascade above.
        """
        self.__resync_world_bounds(self.__local_bounds)
        for child in tuple(self.components.values()):
            child.notify_parent_bounds_changed(self)

    def _on_size_changed(self, width: int | float, height: int | float):
        """This component's pixel size changed.

        Base implementation is a no-op: a plain GameComponent owns no pixels.
        DrawComponent overrides it to reallocate its surface.
        """

    def __resync_world_bounds(self, local: Rect):
        """Recompute world bounds from local bounds and the parent chain.

        `__update_world_bounds` returns early when there is no parent, which
        leaves a root's world bounds frozen at whatever the constructor or
        the last move() left there. For a root there is no parent transform,
        so world IS local plus offset -- the same relation the constructor
        and move() already assume.
        """
        if self.__parent is None:
            world = local.copy()
            world.x += self.__offset.x
            world.y += self.__offset.y
            self.__world_bounds = world
            return
        self.__update_world_bounds()

    def bind_parent(self, parent: GameComponent | None, preserve_world_bounds: bool = True, bind_manager: bool = False):
        """Bind a parent component component."""
        if parent is not self and parent is not self.__parent:
            self.__parent = parent
            if bind_manager:
                self.manager = parent
            if preserve_world_bounds:
                temp = self.world_bounds
                self.__local_bounds.x = temp.x
                self.__local_bounds.y = temp.y
                self.__local_bounds.width = temp.width
                self.__local_bounds.height = temp.height
            self.__update_world_bounds()

    def bind_component(self, name: str, component_in: GameComponent,
                       commands: list | None = ("pre_prepare", "prepare", "post_prepare", "build")):
        """Bind a component to the component container.

        Refuses to register the same instance under two names. Doing so makes
        the "tree" a DAG: the shared node and its whole subtree are visited
        twice per traversal, so every listener on them fires twice per
        dispatch and they queue duplicate blit tokens. ScrollComponent shipped
        with exactly that bug for its thumb.
        """
        for existing_name, existing in self.components.items():
            if existing is component_in and existing_name != name:
                raise PyoneerAlreadyBoundError(
                    f"{type(component_in).__name__} is already bound to "
                    f"{type(self).__name__} as {existing_name!r}; "
                    f"refusing to also bind it as {name!r}"
                )
        commands = commands if commands is not None else ()
        if "pre_prepare" in commands:
            component_in.core_lifecycle_prepare_pre(None)
        if "prepare" in commands:
            component_in.core_lifecycle_prepare(None)
        if "post_prepare" in commands:
            component_in.core_lifecycle_prepare_post(None)
        if "build" in commands:
            component_in.core_lifecycle_build(None)
        self.components[name] = component_in

    def unbind_component(self, identifier: str):
        """Unbind a component from the component container."""
        if identifier in self.components:
            del self.components[identifier]
        else:
            raise PyoneerAssetMissingError(
                "component", identifier, available=self.components.keys(),
                owner=type(self).__name__,
            )

    def adjusted_position(self, point: Vector2 | Rect | tuple[int | float, int | float]) -> Vector2:
        """Adjust the point based on the scroll position, default there is no scroll position so it simply type shifts."""
        if isinstance(point, Rect):
            return Vector2(point.topleft)
        elif isinstance(point, tuple):
            return Vector2(point[0], point[1])
        point.x += self.offset.x
        point.y += self.offset.y
        return point

    def get_component(self, identifier: str) -> GameComponent | None:
        """Get a specific component."""
        if identifier in self.components:
            return self.components[identifier]
        else:
            return None

    def get_components_at(self, bounds: Rect | Vector2 | tuple[int | float, int | float]) -> list[GameComponent]:
        """Get components at a specific location."""
        if isinstance(bounds, Vector2):
            bounds = Rect(bounds.x, bounds.y, 1, 1)
        elif isinstance(bounds, tuple):
            bounds = Rect(bounds[0], bounds[1], 1, 1)
        output = []
        for name, component in self.components.items():
            if component.world_bounds.colliderect(bounds):
                output.append(component)
                output.extend(component.get_components_at(bounds))
        return output

    def get_clickable_components_at(self, bounds: Rect | Vector2 | tuple[int | float, int | float]) -> list[GameComponent]:
        """Get components at a specific location."""
        if isinstance(bounds, Vector2):
            bounds = Rect(bounds.x, bounds.y, 1, 1)
        elif isinstance(bounds, tuple):
            bounds = Rect(bounds[0], bounds[1], 1, 1)
        output = []
        for name, component in self.components.items():
            if component.world_bounds.colliderect(bounds) and component.is_clickable():
                output.append(component)
                output.extend(component.get_clickable_components_at(bounds))
        return output

    def get_components(self, identifiers: list[str] = [], exceptions: list = [], ordered: bool = True) -> list[GameComponent]:
        """Get specific components."""
        output = []
        for name, component in self.components.items():
            if component in exceptions:
                continue
            if name in identifiers or len(identifiers) == 0:
                output.append(component)
        if ordered:
            output.sort(key=lambda x: x.depth)
        return output

    def get_component_by_type(self, component_type: Type | str) -> GameComponent | None:
        """Get a specific component by type."""
        for component_name, component in self.components.items():
            if str(type(component)) is str(component_type):
                return component
        return None

    def get_components_by_type(self, component_type: Type, ordered: bool = True) -> list[GameComponent]:
        """Get a specific component by type."""
        output: list[GameComponent] = []
        for name, component in self.components.items():
            if component is component_type:
                output.append(component)
        if ordered:
            output.sort(key=lambda x: x.depth)
        return output

    def bind_sync_listener(self, typ: GameEventType, callback: Callable):
        """Bind a callback to a component event."""
        if self.callbacks.keys().__contains__(typ):
            self.callbacks[typ].append(callback)
        else:
            self.callbacks[typ] = [callback]
        return True

    def has_event_type(self, typ: GameEventType) -> bool:
        return self.callbacks.keys().__contains__(typ)

    #async def bind_async_listener(self, typ: GameEventType, callback: Callable):
    #    """Bind a callback to a component event."""
    #    if self.async_callbacks.keys().__contains__(typ):
    #        self.async_callbacks[typ].append(callback)
    #    else:
    #        self.async_callbacks[typ] = [callback]
    #    return True

    # ---------------------------------------------------------------------------------------------
    @staticmethod
    def event_listener(typ: GameEventType) -> Callable:
        """Decorator for binding a callback to a component event type."""
        def decorator(func):
            def wrapper(self, *args, **kwargs):
                func(self, *args, **kwargs)
            return wrapper  # func
        return decorator  # wrapper

    #async def async_listener(self, typ: GameEventType) -> Callable:
    #    """Decorator for binding a callback to a component event type."""
    #    async def decorator(func):
    #        await self.bind_async_listener(typ, func)
    #        return func
    #    return decorator
    # ---------------------------------------------------------------------------------------------

    def unbind_event_listener(self, typ: GameEventType, callback: Callable):
        """Unbind a callback from a component event."""
        if self.callbacks.keys().__contains__(typ):
            self.callbacks[typ].remove(callback)
            if len(self.callbacks[typ]) == 0:
                del self.callbacks[typ]
                return True
        return False

    def __send_event(self, typ: GameEventType, event: Optional[PyoneerEvent], *args, **kwargs):
        # An already-consumed event stops here. Previously `handled` only
        # broke out of the local callback loop and the fan-out below ran
        # unconditionally, so mark_event_handled() could not actually consume
        # anything: a click on a window's close button was still delivered to
        # every sibling and every descendant.
        if event is not None and event.handled and not event.trickle:
            return

        # Input is gated on `active`, never on `visible`. A hidden but active
        # window still receives and can consume input; that is deliberate.
        # `active` is False only when a subtree has been explicitly disabled.
        if typ in INPUT_EVENT_TYPES and not self.accepts_input:
            return

        # Rendering is gated on `visible`, and it must gate the whole SUBTREE.
        # Each DrawComponent checks its own `visible`, but a container like
        # GameWindow is a plain GameComponent with no core_render_blits of its own --
        # it only fans BLITS out to children. So setting `window.visible =
        # False` hid nothing: every child still had visible=True and kept
        # drawing itself. Cutting the fan-out here makes visibility inherit.
        if typ is GameEventType.BLITS and not self.visible:
            return

        if self.__has_callback(typ):
            for callback in self.__get_callback(typ):
                self.__invoke_listener(typ, callback, event, *args, **kwargs)
                if event is not None and event.handled and not event.trickle:
                    return
        self.send_event_to_children_advanced(event_type=typ, event=event, *args, **kwargs)

    def __invoke_listener(self, typ: GameEventType, callback: Callable,
                          event: Optional[PyoneerEvent], *args, **kwargs):
        """Call one listener, attaching dispatch context to anything it raises.

        A failure several components deep in a fan-out is close to unreadable
        without the path that reached it. PyoneerErrors accumulate a frame per
        component they pass through; anything else is wrapped once, naming the
        component, the event type and the listener.
        """
        try:
            callback(event, *args, **kwargs)
        except PyoneerError as exc:
            exc.push_frame(component=type(self).__name__,
                           uuid=self.uuid[:8],
                           event=getattr(typ, "name", typ))
            raise
        except TypeError as exc:
            # A TypeError raised AT the call boundary (empty traceback beyond
            # this frame) means the signature does not match what the
            # dispatcher passes -- a contract error, not a bug inside the
            # listener. DrawComponent.dispose_drawable shipped exactly this:
            # bound to DISPOSE while taking no `event` parameter.
            if exc.__traceback__ is not None and exc.__traceback__.tb_next is None:
                raise PyoneerListenerContractError(
                    f"{type(self).__name__} listener "
                    f"{getattr(callback, '__qualname__', callback)} cannot accept the "
                    f"{getattr(typ, 'name', typ)} event; listeners must take "
                    f"(event, *args, **kwargs). Original: {exc}",
                    component=type(self).__name__,
                    uuid=self.uuid[:8],
                ) from exc
            raise PyoneerEventDispatchError(self, typ, callback, exc) from exc
        except Exception as exc:
            raise PyoneerEventDispatchError(self, typ, callback, exc) from exc

    @property
    def accepts_input(self) -> bool:
        """Whether input-class events reach this component and its children.

        Override to add conditions; do not fold `visible` in here.
        """
        return self.active

    @property
    def accepts_focus(self) -> bool:
        """Whether clicking this component should move keyboard focus to it."""
        return self.focusable and self.active

    @property
    def focused(self) -> bool:
        """Whether this component holds keyboard focus.

        This is the flag a click-to-focus widget sets. `active` used to be
        overloaded for it by GameWindow and TextBox, which conflicted with
        `active` meaning "enabled".
        """
        return self._focused

    @focused.setter
    def focused(self, value: bool):
        value = bool(value)
        if value == self._focused:
            return
        self._focused = value
        self._on_focus_changed(value)

    def _on_focus_changed(self, focused: bool):
        """Called when focus is gained or lost. Override in subclasses.

        Text-entry widgets use this to claim and release keyboard capture, so
        that gameplay input is suppressed while the user is typing.
        """

    def __get_callback(self, typ: GameEventType):
        # Snapshot: a handler that unbinds itself (or a sibling listener)
        # mutates self.callbacks[typ] mid-iteration, which silently skipped
        # the NEXT listener in the list.
        if self.__has_callback(typ):
            for callback in tuple(self.callbacks[typ]):
                yield callback

    def __create_event(self, event_type: GameEventType, data: PyoneerEvent | dict, sender: GameComponent | None = None) -> PyoneerEvent:
        return PyoneerEvent(event_type=event_type, sender=sender, data=data)

    #async def send_async_event(self, typ: GameEventType, event: Optional[PyoneerEvent], *args, **kwargs):
    #    """Send an async event to the component."""
    #    return self.send_event(typ, event, *args, **kwargs)

    def send_pygame_event(self, event: PyoneerEvent, *args, **kwargs):
        """Send a PyoneerEvent to the component."""
        return self.send_event_advanced(event.type, event, *args, **kwargs)

    def send_event(self, event_type: GameEventType, data: {}, *args, **kwargs):
        """Send an event to the component."""
        return self.send_event_advanced(event_type, data, *args, **kwargs)

    def send_event_to_children(self, event_type: GameEventType, data: {}, *args, **kwargs):
        """Send an event to all children of the component."""
        return self.send_event_to_children_advanced(event_type, data, *args, **kwargs)

    def send_event_advanced(self,
                            event_type: GameEventType = None,
                            event: Optional[PyoneerEvent] | dict = None,
                            *args, **kwargs):
        """Call a component directly from anywhere in the program.\n
            - typ: The event type to call\n
                - PyoneerEvent: If a PyoneerEvent is passed,\n
                    - The event will be used for type and event and assume data can be present.\n
                - GameEventType: If a GameEventType is passed,\n
                    - The type will be used and assume data can be present.\n
            - event: The event data to send\n
                - PyoneerEvent: If a dict is passed,\n
                    - the event will append the dictionary to the data of the PyoneerEvent using the append_data method.\n
                    - specific data should be manually allocated instead of concatenated if necessary.\n
                - dict: If a PyoneerEvent is passed, the event will use the PyoneerEvent if the typ isn't an event.\n
            - args: Additional arguments for the actual event callback.\n
            - kwargs: Additional keyword arguments for the actual event callback.\n
        """
        # if the parent or the manager is managing we want to send
        # if the manager is not set, we want to send as there is no manager
        # if the event sender is the current widget, we want to send as that is necessary functionality
        e_type = None
        event__ = None
        if isinstance(event_type, GameEventType):
            e_type = event_type
            if isinstance(event, dict):
                # create the event using the data, if sender is in data use that, otherwise use the current widget
                event__ = self.__create_event(event_type, event)
            elif isinstance(event, PyoneerEvent):
                event__ = event
        elif isinstance(event_type, PyoneerEvent):
            e_type = event_type.type
            event__ = event_type

        if e_type is None:
            # Nothing routable was supplied. Previously this returned silently.
            raise PyoneerEventTypeError(
                f"{type(self).__name__}.send_event_advanced needs a GameEventType or a "
                f"PyoneerEvent; got event_type={event_type!r}",
                uuid=self.uuid[:8],
            )

        if event__ is None:
            # Synthesize the missing event instead of dropping the dispatch.
            #
            # This guard used to read `event__ is not None`, so ANY call with
            # event=None returned having invoked nothing. Every lifecycle
            # wrapper funnels through here, and bind_component calls
            # core_lifecycle_prepare(None) / core_lifecycle_build(None)
            # directly -- so those methods ran, but the listener fan-out INSIDE
            # them was silently discarded. Widgets that register behaviour with
            # bind_sync_listener(PREPARE, ...) never received it unless the
            # scene happened to re-dispatch with a real event later.
            event__ = self.__create_event(e_type, {}, sender=self)

        # The `manager` gate: when a manager is set, only it may drive this
        # component. Reads event__ rather than the raw `event` argument, which
        # was an AttributeError waiting to happen -- `event` can be a dict or
        # None here, and neither has `.sender`.
        if self.manager is not None and event__.sender is not self.manager:
            return None

        return self.__send_event(e_type, event__, *args, **kwargs)

    def send_event_to_self(self, event_type: GameEventType, event: Optional[PyoneerEvent] = None,
                           *args, **kwargs):
        """Invoke THIS component's listeners for `event_type`; no fan-out.

        `send_event_advanced` always continues into the children, and
        `send_empty_event(to_children=False)` still funnels through it, so
        there was no way to say "repaint yourself" without repainting the
        whole subtree. DrawComponent.resize() needs exactly that.
        """
        if event is None:
            event = self.__create_event(event_type, {}, sender=self)

        # Same gates __send_event enforces. This is a public dispatch entry
        # point sitting next to send_event_advanced, and without these it
        # would deliver a mouse event to a disabled component or a BLITS to a
        # hidden one -- silently, and only for whoever called this method.
        # A dispatch path with different rules from the main one is a trap.
        #
        # The `manager` gate is deliberately NOT copied: resize() sends with
        # sender=self, so a managed component would refuse to repaint itself.
        if event.handled and not event.trickle:
            return event
        if event_type in INPUT_EVENT_TYPES and not self.accepts_input:
            return event
        if event_type is GameEventType.BLITS and not self.visible:
            return event

        for callback in self.__get_callback(event_type):
            self.__invoke_listener(event_type, callback, event, *args, **kwargs)
            if event.handled and not event.trickle:
                break
        return event

    def send_event_to_children_advanced(self, event_type: GameEventType = None, event: Optional[PyoneerEvent] = None, *args, **kwargs):
        """Send an event to all children of the component.

        Iterates a snapshot: a handler that binds or unbinds a component --
        closing a window, spawning a dialog, removing a list row -- mutates
        self.components mid-dispatch, which raised
        `RuntimeError: dictionary changed size during iteration`.
        """
        output = {}
        for name, component in tuple(self.components.items()):
            # Stop as soon as a child consumes the event.
            if event is not None and event.handled and not event.trickle:
                break
            try:
                call_return = component.send_event_advanced(event_type=event_type, event=event, *args, **kwargs)
            except PyoneerError as exc:
                # Record the child slot we descended through, so the final
                # message reads as a path from the root rather than a leaf.
                exc.push_frame(parent=type(self).__name__, child_slot=name)
                raise
            if call_return is not None:
                output[component.uuid] = call_return
        return output

    def send_empty_event(self, event_type: GameEventType, to_self: bool = True, to_children: bool = True):
        """Send an empty event to the component or the children of the component."""
        if to_children:
            return self.send_event_to_children_advanced(event_type=event_type)
        if to_self:
            return self.send_event_advanced(event_type=event_type)

    def mark_event_handled(self, event: PyoneerEvent | list[PyoneerEvent] | None = None):
        """Flags the event or list of events as handled."""
        if event is not None:
            if isinstance(event, list):
                for ev in event:
                    ev.handled = True
            else:
                event.handled = True

    # ---------------------------------------------------------------------------------------------
    # Convenience Pyoneer Game Object Calls
    # ---------------------------------------------------------------------------------------------
    # These are directly overridden from the pyoneer object for scene API convenience.
    # Each of these automatically trickles as necessary from the core scene to the internal components.
    def core_input_receive(self, event: Optional[PyoneerEvent] = None):
        """Buffer the component."""
        return self.send_event_advanced(event_type=GameEventType.INPUTS, event=event)

    def events(self, event: Optional[PyoneerEvent] = None):
        """Buffer the component."""
        return self.send_event_advanced(event_type=GameEventType.CUSTOM_EVENT, event=event)

    def rebuild(self, event: Optional[PyoneerEvent] = None):
        """
            Rebuild the component. \n
            Required only if the component needs to be rebuilt, and must be overridden for function.
        """
        return self.send_event_advanced(GameEventType.REBUILD, event)



    def core_frame_update_pre(self, event: Optional[PyoneerEvent] = None):
        """Pre-update the component."""
        return self.send_event_advanced(event_type=GameEventType.PRE_UPDATE, event=event)

    def core_frame_update_post(self, event: Optional[PyoneerEvent] = None):
        """Post-update the component."""
        return self.send_event_advanced(event_type=GameEventType.POST_UPDATE, event=event)

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        """Update the component."""
        return self.send_event_advanced(event_type=GameEventType.UPDATE, event=event)

    def core_lifecycle_dispose(self, event: Optional[PyoneerEvent] = None):
        """Dispose of the component."""
        return self.send_event_advanced(event_type=GameEventType.DISPOSE, event=event)

    def __has_callback(self, typ: GameEventType) -> bool:
        return self.callbacks.keys().__contains__(typ)

    def core_render_blits(self, event: Optional[PyoneerEvent] = None):
        """Blit the component."""
        return self.send_event_advanced(event_type=GameEventType.BLITS, event=event)

    # `image` is inherited from PyoneerGameObject. The override that lived
    # here returned self.__image, which mangled to _GameComponent__image and
    # was never assigned anywhere -- so it raised AttributeError for any
    # subclass that did not override it. Every live subclass happened to,
    # which is the only reason it never fired.

    def is_clickable(self) -> bool:
        return self.get_component("mouse") is not None or self.clickable

    def __str__(self):
        return f"GameComponent: {self.__class__.__name__} - {self.uuid}"

    # ---------------------------------------------------------------------------------------------
    # Event Listeners
    # ---------------------------------------------------------------------------------------------
    # Each of these is built for default behavioral control.
    # These are meant to either be overridden or replaced.
    def __on_parent_changed(self, event: Optional[PyoneerEvent] = None):
        """When the parent is changed, this is deployed to components."""
        # adjust the offset to fit the correct parent/child hierarchy
        #new_parent = event.data["parent"]
        #if new_parent is not None:
        #    new_parent_offset = new_parent.offset
        #    self.offset: Vector2 = Vector2(new_parent_offset.x + self.offset.x, new_parent_offset.y + self.offset.y)
        # adjust the bounds to fit the correct parent/child hierarchy
        if self.__parent is not None:
            self.__update_world_bounds()

    def __on_component_bound(self, event: Optional[PyoneerEvent] = None):
        """When a component is bound, this is deployed to components."""
        pass

