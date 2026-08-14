"""Which tmx object type becomes which class, and at what depth.

WHY THIS IS A HAND-WRITTEN TABLE
--------------------------------
A tmx `<object type="GamePlayer">` names a class in a string. Turning that
string into a constructor is a lookup, and there are exactly two ways to
build the table: scan the package and register whatever looks like an
entity, or write the entries down. This module writes them down, for the
same reason `ComponentFactory` does.

Scanning would have shipped a registry containing `GameEntity`,
`GameAnimatedEntity` and `GameEntitySimple` -- all three are `ABC`
subclasses with unimplemented abstract methods, so constructing any of them
raises `TypeError: Can't instantiate abstract class`. A scan cannot tell
that apart from a class it simply has not seen yet, so the failure would
land at spawn time on the author's map rather than here, in a file a human
reads. An explicit table is a list of claims that are true when written and
falsifiable by `tools/check_spawn.py` afterwards.

WHAT IS ACTUALLY CONCRETE, MEASURED
-----------------------------------
`scripts/core/depth.py`'s `OBJECT_CONVERTER` names six classes. Only one of
them can be built:

    GamePlayer               concrete                       registered
    GameEntity               abstract (core_lifecycle_build,
                             core_input_receive)            NOT registered
    GameFloorEntity          does not exist                 NOT registered
    GameBackgroundEntity     does not exist                 NOT registered
    GameForegroundEntity     does not exist                 NOT registered
    GameUIEntity             does not exist                 NOT registered

`OBJECT_CONVERTER` is therefore a DEPTH table that happens to be keyed by
class name, not a class list -- four of its six keys have no class anywhere
in the tree. It stays useful for depth resolution and is useless as a
source of constructors. Registering from it would have produced five
entries out of six that raise or `NameError` the moment a map used them.

An unknown type RAISES, listing the registry. It never falls back to a
default class: a spawn that silently becomes the wrong entity is the
"plausible wrong value" failure this codebase is built to refuse, and unlike
a missing entity it looks like it worked.

DEPTH IS THE LAYER TO BIND INTO, NOT `entity.depth`
---------------------------------------------------
`EntityLayer.core_render_blits` queues at `entity.depth + self.layer_depth`,
so `entity.depth` is an offset WITHIN a layer. Nothing here assigns it.
A resolved depth of 50 means "bind this into depth 50", and writing it onto
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

`OBJECT_DEPTH["ENTITY"]` (50) rather than 0 or -1, because 0 is under the
floor and a depth the renderer has never heard of draws nothing. An entity
whose author gave no depth signal at all should still be visible and should
still sort against the player, and 50 is the depth that means exactly that.
"""

# The house-safe spelling, shared with the layer vocabulary rather than
# re-typed: pytmx RAISES on a custom property that shadows one of its own
# attribute names, which is why everything the editor writes is prefixed.
DEPTH_PROPERTY: str = layer_profile.DEPTH          # "pyoneer_depth"

DEPTH_PROPERTY_PLAIN: str = "depth"
"""The unprefixed spelling, accepted second.

Measured on the pytmx installed here (3.32): `depth` is NOT one of
`TiledObject`'s reserved attribute names, so an object carrying it loads
fine, while `visible` or `gid` make the whole map raise. So this one is safe
ON OBJECTS specifically -- it is not a licence to drop the prefix elsewhere,
and a layer's depth is still `pyoneer_depth`.
"""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(name: str, factory: Callable[..., Any],
             registry: dict[str, Callable[..., Any]] | None = None) -> Callable[..., Any]:
    """Bind one tmx type name to the callable that builds it.

    Re-registering a name replaces it, deliberately: a test that swaps a
    class in and puts the original back is the only sanctioned way to drive
    the spawn path without art, and refusing the second call would make that
    impossible rather than safe.
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

    The error carries the registry because "GamePlayr is not a spawn type"
    without the list is a message the author has to go read source to act
    on, and the list is three entries long at most.
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
    the property carries `type="int"`; without it Tiled writes a bare string
    and the value arrives as `'50'`. Coercing would work right up until
    someone typed `5o`, so a wrongly-typed depth raises and says which
    object and what to fix.
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
    OBJECT_CONVERTER`, so an object group named "PlayerDepth", "ENTITY" or
    "UI_ENTITY" all resolve. An object group named for nothing in that table
    (the shipped map's is called "entity", lowercase, and is in none of
    them) falls through to step 4 rather than raising: an unmapped LAYER
    drops authored tiles and must warn, but an unmapped object group is just
    a group the author never gave a depth to, and 50 is a truthful answer.
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
    `Transform` from its own `position`/`rotation`/`scale` arguments and
    never looks at the one it was handed -- so placing an entity is a
    `moveto()` call after construction, exactly as `main.py` does it. Doing
    that here would make this function silently position-aware; the caller
    that knows the map does it instead. See `scripts/loaders/map_loader.py`.
    """
    factory = resolve_factory(type_name, registry)
    entity = factory(**kwargs)
    trace_lifecycle("spawned %s as %s", type_name, type(entity).__name__)
    return entity


# ---------------------------------------------------------------------------
# The table
#
# One line per concrete class, written by hand. No scan, no importlib. The
# module docstring records why the other five OBJECT_CONVERTER names are not
# here, and tools/check_spawn.py asserts that reasoning still holds -- so
# the day GameFloorEntity is written, that check fails and points at this
# line rather than at a map that mysteriously will not load.
# ---------------------------------------------------------------------------

register("GamePlayer", GamePlayer)
