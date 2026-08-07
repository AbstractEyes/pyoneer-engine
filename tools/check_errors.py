"""Verify the exception hierarchy, the naming schema, and the image contract.

Three things this guards:
  1. Failures that used to be silent now raise something typed and specific.
  2. The core_<domain>_<action>[_<phase>] schema is complete and consistent,
     with no stragglers from the old naming.
  3. There is exactly ONE image slot in the hierarchy.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import inspect
import sys
import warnings

import pygame

pygame.init()
pygame.display.set_mode((256, 256))

from pygame import Rect

from scripts.core import errors as E
from scripts.core.component import GameComponent
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.game_object import PyoneerGameObject
from scripts.core.renderer import LayerRenderer
from scripts.core.ui.widget.shape import ShapeComponent

failures = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<54} got={got} want={want}")
    if not ok:
        failures.append(label)


def raises(label, exc_type, fn):
    try:
        fn()
    except exc_type as exc:
        print(f"  ok   {label:<54} {type(exc).__name__}")
        return exc
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL {label:<54} raised {type(exc).__name__}: {exc}")
        failures.append(label)
        return None
    print(f"  FAIL {label:<54} did not raise")
    failures.append(label)
    return None


# --------------------------------------------------------------------------
print("hierarchy shape")
# --------------------------------------------------------------------------
for name in ("PyoneerAssetMissingError", "PyoneerEventDispatchError",
             "PyoneerImageMissingError", "PyoneerBindTargetError",
             "PyoneerCameraMissingError", "PyoneerAlreadyBoundError",
             "PyoneerListenerContractError", "PyoneerLayerError"):
    cls = getattr(E, name)
    expect(f"{name} is a PyoneerError", issubclass(cls, E.PyoneerError), True)

expect("every public error starts with 'Pyoneer'",
       [n for n in dir(E)
        if n.endswith("Error") and not n.startswith(("Pyoneer", "_"))],
       [])
expect("asset errors stay catchable as KeyError",
       issubclass(E.PyoneerAssetMissingError, KeyError), True)

print()
print("context chains accumulate outward")
bare = E.PyoneerAssetMissingError("map", "x", available=["a"])
expect("no context at construction means no frames", len(bare.frames), 0)
expect("bare message has no trailer", "\n" in str(bare), False)

err = E.PyoneerAssetMissingError("map", "x", available=["a"], source="config/maps.json")
expect("constructor context becomes the first frame", len(err.frames), 1)
err.push_frame(component="Panel", child_slot="body")
err.push_frame(parent="GameWindow", child_slot="panel")
expect("frames accumulate outward", len(err.frames), 3)
expect("message names the innermost source", "source='config/maps.json'" in str(err), True)
expect("message names the outermost path", "child_slot='panel'" in str(err), True)

# --------------------------------------------------------------------------
print()
print("failures that used to be silent now raise")
# --------------------------------------------------------------------------
renderer = LayerRenderer(pygame.display.get_surface())


class _NotBindable:
    pass


raises("binding an unsupported type", E.PyoneerBindTargetError,
       lambda: renderer.bind("UI_LAYER_1", _NotBindable()))
raises("rendering with no camera bound", E.PyoneerCameraMissingError,
       lambda: renderer.render())
raises("unknown layer name", E.PyoneerLayerError,
       lambda: renderer.bind("NO_SUCH_LAYER", ShapeComponent(bounds=Rect(0, 0, 4, 4))))


class Probe(GameComponent):
    def core_lifecycle_build(self, event=None):
        pass

    def core_lifecycle_dispose(self, event=None):
        return True


root = Probe(bounds=Rect(0, 0, 40, 40))
child = Probe(parent=root, bounds=Rect(0, 0, 10, 10))
root.bind_component("child", child)

raises("binding one instance under two names", E.PyoneerAlreadyBoundError,
       lambda: root.bind_component("child_again", child))
raises("unbinding a component that is not there", E.PyoneerAssetMissingError,
       lambda: root.unbind_component("nope"))

print()
print("a listener that raises reports WHERE, not just what")


def explode(event, *a, **k):
    raise ZeroDivisionError("boom")


child.bind_sync_listener(GameEventType.UPDATE, explode)
exc = raises("listener exception is wrapped", E.PyoneerEventDispatchError,
             lambda: root.send_event_advanced(
                 GameEventType.UPDATE,
                 PyoneerEvent(GameEventType.UPDATE, sender=None, data={})))
if exc is not None:
    text = str(exc)
    expect("names the listener", "explode" in text, True)
    expect("names the event", "UPDATE" in text, True)
    expect("names the child slot it descended through", "child_slot='child'" in text, True)
    expect("chains the original cause", isinstance(exc.__cause__, ZeroDivisionError), True)
child.unbind_event_listener(GameEventType.UPDATE, explode)

print()
print("a listener with the wrong signature is a contract error, not a TypeError")


def no_event_param():  # deliberately wrong: dispatcher always passes event
    pass


child.bind_sync_listener(GameEventType.UPDATE, no_event_param)
raises("wrong-arity listener", E.PyoneerListenerContractError,
       lambda: root.send_event_advanced(
           GameEventType.UPDATE,
           PyoneerEvent(GameEventType.UPDATE, sender=None, data={})))
child.unbind_event_listener(GameEventType.UPDATE, no_event_param)

print()
print("unusable authored content warns rather than dying")
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    E.warn_content("test layer has no depth mapping")
    expect("emits PyoneerContentWarning",
           any(issubclass(w.category, E.PyoneerContentWarning) for w in caught), True)

# --------------------------------------------------------------------------
print()
print("naming schema is complete and consistent")
# --------------------------------------------------------------------------
DOMAINS = ("lifecycle", "frame", "render", "input")
core_methods = sorted(n for n in dir(PyoneerGameObject) if n.startswith("core_"))
print(f"       {len(core_methods)} core_* methods on PyoneerGameObject")

bad_domain = [n for n in core_methods if n.split("_")[1] not in DOMAINS]
expect("every core_* uses a known domain", bad_domain, [])

legacy = ("core_build", "core_prepare", "core_update", "core_dispose",
          "core_blits", "core_inputs", "core_image",
          "core_pre_update", "core_post_update", "core_pre_prepare",
          "core_post_prepare", "core_pre_dispose", "core_post_dispose")
expect("no legacy names survive on the base class",
       [n for n in legacy if hasattr(PyoneerGameObject, n)], [])

for family in ("core_lifecycle_prepare", "core_frame_update", "core_lifecycle_dispose"):
    trio = [family, f"{family}_pre", f"{family}_post"]
    expect(f"{family} has all three phases",
           [n for n in trio if not hasattr(PyoneerGameObject, n)], [])

expect("phase suffix keeps the family adjacent when sorted",
       sorted(["core_frame_update", "core_frame_update_pre", "core_frame_update_post"])[0],
       "core_frame_update")

# --------------------------------------------------------------------------
print()
print("exactly one image slot in the hierarchy")
# --------------------------------------------------------------------------
mangled = []
for klass in (PyoneerGameObject, GameComponent, ShapeComponent):
    for base in klass.__mro__:
        mangled += [a for a in vars(base) if a.endswith("__image")]
expect("no name-mangled image slots remain", sorted(set(mangled)), [])

shape = ShapeComponent(bounds=Rect(0, 0, 8, 8))
expect("image is a property, not a method", callable(getattr(shape, "image", None)), False)
expect("image returns a Surface", isinstance(shape.image, pygame.Surface), True)
shape.image = None
expect("image is assignable", shape.image, None)
raises("require_image() names the object", E.PyoneerImageMissingError, shape.require_image)

prop = inspect.getattr_static(PyoneerGameObject, "image")
expect("declared as a property on the base", isinstance(prop, property), True)

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("PASS")
