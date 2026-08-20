"""Which tmx object type becomes which class, and at what depth.

THE TABLE IS HAND-WRITTEN, not scanned, for the same reason
`ComponentFactory`'s is. A scan would register `GameEntity`,
`GameAnimatedEntity` and `GameEntitySimple`, which are `ABC` subclasses with
unimplemented abstract methods, so constructing one raises `TypeError:
Can't instantiate abstract class` -- at spawn time, on the author's map,
rather than here in a file a human reads. `tools/check_spawn.py` falsifies
the written entries instead.

`scripts/core/depth.py`'s `OBJECT_CONVERTER` names six classes and only
`GamePlayer` can be built: `GameEntity` is abstract and the other four exist
nowhere in the tree. It is therefore a DEPTH table that happens to be keyed
by class name, useful for depth resolution and useless as a source of
constructors.

An unknown type RAISES, listing the registry, and never falls back to a
default class: a spawn that silently becomes the wrong entity looks like it
worked.

DEPTH IS THE LAYER TO BIND INTO, NOT `entity.depth`.
`EntityLayer.core_render_blits` queues at `entity.depth + self.layer_depth`,
so `entity.depth` is an offset WITHIN a layer and nothing here assigns it. A
resolved depth of 50 means "bind this into depth 50"; writing it onto
`entity.depth` as well would draw the entity at 100.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from scripts.core import layer_profile
from scripts.core.depth import DEPTH, OBJECT_CONVERTER, OBJECT_DEPTH
from scripts.core.errors import PyoneerAssetMissingError, PyoneerConfigError
from scripts.core.log import trace_lifecycle
from scripts.game.entity.game_player import GamePlayer

SPAWN_REGISTRY: dict[str, Callable[..., Any]] = {}
"""tmx object type -> the callable that builds one. Populated below."""

DEFAULT_OBJECT_DEPTH: int = OBJECT_DEPTH["ENTITY"]
"""Where an object lands when nothing else says.

`OBJECT_DEPTH["ENTITY"]` (50) rather than 0 or -1: 0 is under the floor and
a depth the renderer has never heard of draws nothing. An entity with no
depth signal should still be visible and still sort against the player.
"""

# The house-safe spelling, shared with the layer vocabulary rather than
# re-typed: pytmx RAISES on a custom property that shadows one of its own
# attribute names, which is why everything the editor writes is prefixed.
DEPTH_PROPERTY: str = layer_profile.DEPTH          # "pyoneer_depth"

DEPTH_PROPERTY_PLAIN: str = "depth"
"""The unprefixed spelling, accepted second.

`depth` is not one of `TiledObject`'s reserved attribute names in pytmx
3.32, so an object carrying it loads fine where `visible` or `gid` would
make the whole map raise. Safe ON OBJECTS specifically -- not a licence to
drop the prefix elsewhere; a layer's depth is still `pyoneer_depth`.
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(name: str, factory: Callable[..., Any],
             registry: dict[str, Callable[..., Any]] | None = None) -> Callable[..., Any]:
    """Bind one tmx type name to the callable that builds it.

    Re-registering a name replaces it, deliberately: swapping a class in and
    putting the original back is how a check drives the spawn path without
    art.
    """
    target = SPAWN_REGISTRY if registry is None else registry
    target[name] = factory
    return factory


def register_all(entries, registry: dict[str, Callable[..., Any]] | None = None) -> None:
    """Register a sequence of (name, factory) pairs. Mirrors ComponentFactory."""
    for name, factory in entries:
        register(name, factory, registry)


def resolve_factory(type_name: str,
                    registry: Mapping[str, Callable[..., Any]] | None = None) -> Callable[..., Any]:
    """The callable for `type_name`, or raise naming it and the whole registry.

    The error carries the registry because a bare "not a spawn type" leaves
    the author reading source to find the spelling.
    """
    table = SPAWN_REGISTRY if registry is None else registry
    factory = table.get(type_name)
    if factory is None:
        raise PyoneerAssetMissingError(
            "spawn type", type_name, available=table.keys(),
            hint="register it in scripts/core/spawn.py, or fix the object's "
                 "Type field in Tiled",
        )
    return factory


# ---------------------------------------------------------------------------
# Depth
# ---------------------------------------------------------------------------

def _declared_depth(properties: Mapping[str, Any] | None, where: str) -> int | None:
    """The depth an object declares in its own custom properties, if any.

    Checked, never coerced. `MapProperties` returns a real `int` only when
    the property carries `type="int"`; without it the value arrives as the
    string `'50'`. A wrongly-typed depth raises, naming the object and the
    fix, rather than being coerced until someone types `5o`.
    """
    if properties is None:
        return None
    for key in (DEPTH_PROPERTY, DEPTH_PROPERTY_PLAIN):
        value = properties.get(key)
        if value is None:
            continue
        # bool before int: in Python `True` IS an int, and a depth property
        # typed bool would otherwise resolve to depth 1 without complaint.
        if isinstance(value, bool) or not isinstance(value, int):
            raise PyoneerConfigError(
                "%s declares %s=%r (%s); a depth must be an integer. In "
                "Tiled, set the property's type to int."
                % (where, key, value, type(value).__name__),
            )
        return value
    return None


def resolve_depth(type_name: str,
                  properties: Mapping[str, Any] | None = None,
                  layer_name: str | None = None,
                  class_name: str | None = None,
                  where: str = "object") -> int:
    """Which render depth an object belongs at.

    Four sources, most specific first, and the order is the whole point --
    every step down is a broader statement about the object:

        1. the object's own `pyoneer_depth` / `depth` property
           the author said so about THIS object
        2. OBJECT_CONVERTER[type]    a per-CLASS convention
        3. DEPTH[layer name]         a per-LAYER convention
        4. DEFAULT_OBJECT_DEPTH      nobody said anything

    Step 2 tries the tmx type name first and the constructed class's own
    `__name__` second, because a registry entry may be an alias ("Hero" ->
    GamePlayer) or a factory function, and the depth table is keyed by class.

    Step 3 reads `DEPTH`, which is `MAP_DEPTH | OBJECT_DEPTH |
    OBJECT_CONVERTER`, so object groups named "PlayerDepth", "ENTITY" or
    "UI_ENTITY" all resolve. One named for nothing in that table falls
    through to step 4 rather than raising: an unmapped LAYER drops authored
    tiles and must warn, but an unmapped object group is simply one the
    author never gave a depth to.
    """
    declared = _declared_depth(properties, where)
    if declared is not None:
        return declared
    for candidate in (type_name, class_name):
        if candidate and candidate in OBJECT_CONVERTER:
            return OBJECT_CONVERTER[candidate]
    if layer_name and layer_name in DEPTH:
        return DEPTH[layer_name]
    return DEFAULT_OBJECT_DEPTH


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def spawn(type_name: str,
          registry: Mapping[str, Callable[..., Any]] | None = None,
          **kwargs: Any) -> Any:
    """Build one entity of `type_name`. Raises if the type is unknown.

    No position is applied here. `GameEntity.__init__` takes a `transform`
    keyword and THROWS IT AWAY -- `GameEntitySimple.__init__` builds a fresh
    `Transform` from its own arguments and never looks at the one it was
    handed -- so placing an entity is a `moveto()` call after construction.
    """
    factory = resolve_factory(type_name, registry)
    entity = factory(**kwargs)
    trace_lifecycle("spawned %s as %s", type_name, type(entity).__name__)
    return entity


# ---------------------------------------------------------------------------
# The table
#
# One line per concrete class, written by hand. No scan, no importlib.
# tools/check_spawn.py asserts the module docstring's reasoning still holds,
# so the day GameFloorEntity is written that check fails and points here.
# ---------------------------------------------------------------------------

register("GamePlayer", GamePlayer)
