"""Pyoneer's exception hierarchy.

WHY THIS EXISTS
---------------
The engine was built to fail quietly, which is the right trade while
prototyping: a missing config key falls back to a default, an unroutable
event returns None, a layer with no depth mapping is skipped. Nothing stops.

That trade stops paying the moment someone other than the author is reading
the code, because "it ran" carries no information. Silent fallbacks found in
review included: dispatches with `event=None` returning None, `bind_component`'s
whole command list no-opping, 39 authored map tiles being discarded because a
layer name was misspelled, and `move_speed` falling back to 16 while 20 sat
in the config file.

So: contract violations raise, recoverable oddities warn.

  raise  - the caller asked for something impossible or incoherent, and any
           value returned would be a lie (unknown asset, unroutable event,
           listener with the wrong signature).
  warn   - the engine can carry on truthfully, but a human should know
           (a map layer with no depth mapping, an empty animation).

Warnings go through the stdlib `warnings` module, so the prototype-speed
quiet mode is still one flag away (`python -W ignore::UserWarning main.py`)
without the engine needing a mode switch of its own.

NAMING
------
Every class starts with `Pyoneer`, so typing that prefix enumerates the whole
error surface. Domain bases (`PyoneerEventError`, `PyoneerRenderError`, ...)
are catchable as groups; leaves are specific enough to act on.

    PyoneerError
    +-- PyoneerConfigError        configuration and assets
    |   +-- PyoneerAssetMissingError
    |   +-- PyoneerConfigKeyError
    |   +-- PyoneerBindingInvalidError
    +-- PyoneerLifecycleError     build / prepare / dispose ordering
    |   +-- PyoneerNotPreparedError
    |   +-- PyoneerDisposedError
    |   +-- PyoneerAlreadyBoundError
    +-- PyoneerEventError         dispatch and listeners
    |   +-- PyoneerEventDispatchError
    |   +-- PyoneerListenerContractError
    |   +-- PyoneerEventTypeError
    +-- PyoneerRenderError        blits, images, layers, cameras
    |   +-- PyoneerImageMissingError
    |   +-- PyoneerLayerError
    |   +-- PyoneerCameraMissingError
    +-- PyoneerSceneError         scene graph and binding
        +-- PyoneerSceneMissingError
        +-- PyoneerBindTargetError

CONTEXT CHAINS
--------------
A failure five components deep in a BLITS fan-out is useless without knowing
which component, on which event, under which parent. `PyoneerError` carries a
frame trail; `push_frame` is called as the exception travels back up the
dispatch chain, so the final message reads as a path rather than a leaf.
"""
from __future__ import annotations

import warnings
from typing import Any


class PyoneerError(Exception):
    """Base for every engine error.

    Carries an ordered trail of context frames appended as the exception
    propagates outward, so the message names the whole path, not just the
    innermost failure.
    """

    def __init__(self, message: str, **context: Any):
        self.message = message
        self.frames: list[dict[str, Any]] = []
        if context:
            self.frames.append(context)
        super().__init__(message)

    def push_frame(self, **context: Any) -> "PyoneerError":
        """Record where this error passed through on its way up."""
        self.frames.append(context)
        return self

    def __str__(self) -> str:
        if not self.frames:
            return self.message
        trail = "\n".join(
            "    via " + ", ".join(f"{k}={v!r}" for k, v in frame.items())
            for frame in self.frames
        )
        return f"{self.message}\n{trail}"


# --------------------------------------------------------------------------
# Configuration and assets
# --------------------------------------------------------------------------

class PyoneerConfigError(PyoneerError):
    """Configuration or asset data is missing, malformed, or contradictory."""


class PyoneerAssetMissingError(PyoneerConfigError, KeyError):
    """A named asset was requested and does not exist.

    Also a KeyError: this genuinely is a failed lookup, and callers that
    already wrote `except KeyError` around an asset fetch should keep
    working. PyoneerError.__str__ wins on the MRO, so the message stays
    readable rather than KeyError's bare repr.
    """

    def __init__(self, kind: str, name: str, available=(), **context):
        options = ", ".join(sorted(str(a) for a in available)) or "<none loaded>"
        super().__init__(
            f"{kind} {name!r} not found; available: {options}",
            **context,
        )
        self.kind = kind
        self.name = name


class PyoneerConfigKeyError(PyoneerConfigError, KeyError):
    """A required configuration key is absent."""

    def __init__(self, key: str, source: str, available=(), **context):
        options = ", ".join(sorted(str(a) for a in available)) or "<empty>"
        super().__init__(
            f"config key {key!r} missing from {source}; present: {options}",
            **context,
        )
        self.key = key


class PyoneerBindingInvalidError(PyoneerConfigError, KeyError):
    """An input binding names a key or button the engine does not know."""


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

class PyoneerLifecycleError(PyoneerError):
    """An object was used out of lifecycle order."""


class PyoneerNotPreparedError(PyoneerLifecycleError):
    """Used before core_lifecycle_prepare ran."""

    def __init__(self, obj: Any, action: str, **context):
        super().__init__(
            f"{type(obj).__name__} was asked to {action} before it was prepared; "
            f"call core_lifecycle_prepare() first",
            **context,
        )


class PyoneerDisposedError(PyoneerLifecycleError):
    """Used after disposal."""

    def __init__(self, obj: Any, action: str, **context):
        super().__init__(
            f"{type(obj).__name__} was asked to {action} after disposal",
            **context,
        )


class PyoneerLayoutError(PyoneerError):
    """A layout container was asked for something geometrically impossible.

    Raised rather than silently dropping the item: a widget that is simply
    absent is the hardest kind of UI bug to trace back to its cause.
    """


class PyoneerAlreadyBoundError(PyoneerLifecycleError):
    """An object was bound twice, making the component tree a DAG.

    Shipped for real: ScrollComponent bound its thumb as both "thumb" and
    "scroll_bar", so that subtree received every event twice and queued
    duplicate blit tokens.
    """


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

class PyoneerEventError(PyoneerError):
    """Something went wrong routing or handling an event."""


class PyoneerEventDispatchError(PyoneerEventError):
    """A listener raised. Wraps the original with the dispatch path."""

    def __init__(self, component: Any, event_type: Any, listener: Any, cause: BaseException, **context):
        name = getattr(listener, "__qualname__", repr(listener))
        super().__init__(
            f"{type(component).__name__} listener {name} raised while handling "
            f"{getattr(event_type, 'name', event_type)}: "
            f"{type(cause).__name__}: {cause}",
            **context,
        )
        self.component = component
        self.event_type = event_type
        self.listener = listener


class PyoneerListenerContractError(PyoneerEventError):
    """A listener does not accept the event argument the dispatcher passes.

    Shipped for real: DrawComponent.dispose_drawable took no `event`
    parameter while being bound to DISPOSE, so the first teardown raised
    TypeError from inside the dispatcher with no indication of the culprit.
    """


class PyoneerEventTypeError(PyoneerEventError):
    """An unknown or unroutable event type."""


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

class PyoneerRenderError(PyoneerError):
    """A failure on the render path."""


class PyoneerImageMissingError(PyoneerRenderError):
    """Something needed a surface and did not have one."""

    def __init__(self, obj: Any, **context):
        super().__init__(
            f"{type(obj).__name__} has no image; assign .image or override it "
            f"before it reaches the blit pool",
            **context,
        )


class PyoneerLayerError(PyoneerRenderError):
    """A layer could not be resolved, or its depth is incoherent."""


class PyoneerCameraMissingError(PyoneerRenderError):
    """The renderer was driven with no camera bound."""


# --------------------------------------------------------------------------
# Scene graph
# --------------------------------------------------------------------------

class PyoneerSceneError(PyoneerError):
    """A failure in the scene graph or its binding API."""


class PyoneerSceneMissingError(PyoneerSceneError):
    """A scene was requested by a name that is not registered."""


class PyoneerBindTargetError(PyoneerSceneError):
    """An object was bound that no binder knows how to place."""

    def __init__(self, game_object: Any, supported=(), **context):
        options = ", ".join(sorted(supported)) or "<none registered>"
        super().__init__(
            f"cannot bind {type(game_object).__name__}: no binder handles it; "
            f"supported: {options}",
            **context,
        )


# --------------------------------------------------------------------------
# Warnings - recoverable, but a human should know
# --------------------------------------------------------------------------

class PyoneerWarning(UserWarning):
    """The engine carried on truthfully, but something is probably wrong."""


class PyoneerContentWarning(PyoneerWarning):
    """Authored content could not be used (an unmapped map layer, say)."""


class PyoneerPerformanceWarning(PyoneerWarning):
    """A configuration that works but will not scale."""


def warn_content(message: str, stacklevel: int = 3):
    """Report unusable authored content without stopping the engine."""
    warnings.warn(message, PyoneerContentWarning, stacklevel=stacklevel)


def warn_performance(message: str, stacklevel: int = 3):
    warnings.warn(message, PyoneerPerformanceWarning, stacklevel=stacklevel)
