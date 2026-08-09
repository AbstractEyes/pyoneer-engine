"""Per-layer capabilities, as declared data rather than inferred behaviour.

WHY
---
A tile layer in this engine currently carries exactly one piece of authored
state: its NAME, which `scripts/core/depth.py` maps to a draw depth. Everything
else about how it behaves is inferred:

  * "static" is inferred from Python type plus depth adjacency plus a
    measured alpha proof, none of which the author controls
  * opacity, visibility and offsets are parsed by pytmx and read by nobody
  * passability does not exist

So a layer cannot be TOLD anything. This module is the vocabulary for
telling it, stored as tmx layer custom properties -- which means Tiled shows
them, a human edits them in the same dialog they already use, `MapDocument`
writes them with a byte-minimal diff, and pytmx hands them back typed.

The point is not these six properties. It is that adding a seventh is a
one-line entry here plus whatever reads it -- no editor code, no UI code,
because the inspector renders whatever this declares.

NAMING
------
Every key is prefixed `pyoneer_`. That is not decoration: pytmx RAISES
ValueError and makes the whole map unloadable if a custom property collides
with one of its own attribute names (`data`, `name`, `width`, `height`,
`visible`, `opacity`, `offsetx`, `offsety`, `parent`, `properties`, `id`) --
measured, and it does not warn or skip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.core.layer_profile import KNOWN as ENGINE_KNOWN, PREFIX  # noqa: F401

# pytmx attribute names a custom property may never shadow. Documented here
# because the failure is total -- the map stops loading -- and silent until
# it happens.
RESERVED = frozenset({
    "data", "name", "width", "height", "visible", "opacity",
    "offsetx", "offsety", "parent", "properties", "id",
})


@dataclass(frozen=True)
class Capability:
    """One thing a layer can declare about itself."""

    key: str                       # stored as PREFIX + key
    label: str
    type: str                      # int | float | str | bool
    default: Any
    doc: str
    choices: tuple[Any, ...] = ()

    @property
    def property_name(self) -> str:
        return PREFIX + self.key

    def coerce(self, value: Any) -> Any:
        """Bring a tmx value to the declared type, or fall back to default.

        tmx properties are typed on read, but a hand-edited file can carry
        anything, and a layer with a nonsense capability should behave like
        an undeclared one rather than crash the renderer.
        """
        want = {"int": int, "float": float, "str": str, "bool": bool}[self.type]
        if isinstance(value, bool) and want is not bool:
            return self.default
        if want is float and isinstance(value, int):
            return float(value)
        if not isinstance(value, want):
            return self.default
        if self.choices and value not in self.choices:
            return self.default
        return value


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "depth", "draw depth", "int", -1,
        "Overrides the name lookup in scripts/core/depth.py. -1 means "
        "'use the name'. This is what lets a layer called anything at all "
        "render, instead of silently not drawing."),
    Capability(
        "motion", "motion", "str", "static",
        "static: baked into the map plane and flattened with its neighbours "
        "into one blit. dynamic: kept separate so its tiles can change at "
        "runtime or it can scroll at its own rate. A dynamic layer costs one "
        "extra viewport blit -- measured ~0.48 ms/frame -- and splits the "
        "composite run it sits in.",
        choices=("static", "dynamic")),
    Capability(
        "parallax_x", "parallax x", "float", 1.0,
        "Horizontal scroll rate relative to the camera. 1.0 moves with the "
        "world, 0.5 is a distant background, 0 is pinned. Anything but 1.0 "
        "forces the layer dynamic."),
    Capability(
        "parallax_y", "parallax y", "float", 1.0,
        "Vertical scroll rate. Same rules as parallax_x."),
    Capability(
        "opacity", "opacity", "float", 1.0,
        "0.0 to 1.0. Below 1.0 forces the layer dynamic, because a per-layer "
        "alpha applied at blit time is exactly the partial-on-partial case "
        "composite_is_exact() refuses to flatten."),
    Capability(
        "occludes", "occludes below", "bool", False,
        "This layer's alpha becomes a mask applied to dynamic things drawn "
        "beneath it, so a sprite under a canopy is modulated rather than "
        "merely drawn-over. Note that plain occlusion ALREADY works by draw "
        "order; this is for soft or partial masking."),
    Capability(
        "passability", "passability layer", "str", "",
        "Name of a companion tile layer whose gids encode movement blocking "
        "for this one. Empty means no restrictions."),
    Capability(
        "renders", "renders", "bool", True,
        "Untick for a data layer -- passability, region ids, spawn weights -- "
        "so the engine skips it instead of warning every boot that it has no "
        "depth."),
)

BY_KEY: dict[str, Capability] = {c.key: c for c in CAPABILITIES}
BY_PROPERTY: dict[str, Capability] = {c.property_name: c for c in CAPABILITIES}


# --------------------------------------------------------------------------
# Passability
# --------------------------------------------------------------------------
# RPG Maker's bit order, copied deliberately rather than invented: a set bit
# means BLOCKED, and the order is down, left, right, up. Star is NOT a
# direction -- it means "abstain, ask the layer below" -- so it gets its own
# value rather than being squeezed into the four bits.

BLOCK_DOWN = 0x1
BLOCK_LEFT = 0x2
BLOCK_RIGHT = 0x4
BLOCK_UP = 0x8
PASS_ALL = 0x0
BLOCK_ALL = BLOCK_DOWN | BLOCK_LEFT | BLOCK_RIGHT | BLOCK_UP
STAR = 0x10                    # defer to the layer below

DIRECTION_NAMES = {
    BLOCK_DOWN: "down", BLOCK_LEFT: "left",
    BLOCK_RIGHT: "right", BLOCK_UP: "up",
}


def describe_mask(mask: int) -> str:
    """Human-readable passability, for tooltips and generated docs."""
    if mask == STAR:
        return "star (defer to the layer below)"
    if mask == PASS_ALL:
        return "open"
    if mask == BLOCK_ALL:
        return "blocked"
    blocked = [name for bit, name in sorted(DIRECTION_NAMES.items())
               if mask & bit]
    return "blocks " + ", ".join(blocked)


def mask_to_gid(mask: int, first_gid: int) -> int:
    """A passability mask as a gid in its companion layer."""
    if not 0 <= mask <= STAR:
        raise ValueError(f"passability mask {mask} is outside 0..{STAR}")
    return first_gid + mask


def gid_to_mask(gid: int, first_gid: int) -> int:
    """The inverse. gid 0 (an empty cell) reads as fully open."""
    if gid <= 0:
        return PASS_ALL
    mask = gid - first_gid
    return mask if 0 <= mask <= STAR else PASS_ALL


# --------------------------------------------------------------------------
# Reading a layer's profile
# --------------------------------------------------------------------------

@dataclass
class LayerProfile:
    """Everything a layer declares about itself, with defaults filled in."""

    name: str
    values: dict[str, Any]

    def __getattr__(self, key: str) -> Any:
        if key in BY_KEY:
            return self.values.get(key, BY_KEY[key].default)
        raise AttributeError(key)

    @property
    def is_static(self) -> bool:
        """Static means "may be flattened into the map plane with its
        neighbours". Declared motion is only one of the ways to lose it:
        anything that has to be modulated at blit time cannot be baked."""
        return (self.values.get("motion", "static") == "static"
                and self.values.get("parallax_x", 1.0) == 1.0
                and self.values.get("parallax_y", 1.0) == 1.0
                and self.values.get("opacity", 1.0) >= 1.0)

    @property
    def declared(self) -> list[str]:
        return sorted(self.values)

    def as_properties(self) -> dict[str, Any]:
        """The tmx property names and values this profile would write."""
        return {PREFIX + key: value for key, value in sorted(self.values.items())}


def read_profile(layer) -> LayerProfile:
    """Read a MapDocument TileLayer or ObjectLayer's declared capabilities."""
    raw = layer.properties.as_dict()
    values: dict[str, Any] = {}
    for property_name, value in raw.items():
        capability = BY_PROPERTY.get(property_name)
        if capability is not None:
            values[capability.key] = capability.coerce(value)
    return LayerProfile(getattr(layer, "name", ""), values)


def validate_property(key: str, value: Any) -> Any:
    """Check one capability by key. Raises ValueError with a usable message."""
    capability = BY_KEY.get(key)
    if capability is None:
        raise ValueError(
            f"unknown layer capability {key!r}; known: {sorted(BY_KEY)}")
    coerced = capability.coerce(value)
    if coerced != value and not (
            capability.type == "float" and float(value) == coerced):
        raise ValueError(
            f"{key!r} wants {capability.type}"
            + (f" from {list(capability.choices)}" if capability.choices else "")
            + f", got {value!r}")
    return coerced


def describe_all() -> str:
    """Markdown for the generated request bundle."""
    lines = ["| capability | type | default | meaning |", "|---|---|---|---|"]
    for capability in CAPABILITIES:
        doc = capability.doc
        if capability.choices:
            doc += f" One of {list(capability.choices)}."
        lines.append(f"| `{capability.property_name}` | {capability.type} | "
                     f"`{capability.default!r}` | {doc} |")
    return "\n".join(lines)
