"""Per-layer capabilities, as declared data rather than inferred behaviour.

WHY
---
Without this, the only authored state a tile layer carries is its NAME,
which `scripts/core/depth.py` maps to a draw depth; everything else about
how it behaves is inferred -- "static" from Python type plus depth adjacency
plus a measured alpha proof, none of which the author controls, and opacity,
visibility and offsets parsed by pytmx and read by nobody.

This module is the vocabulary for TELLING a layer things, stored as tmx
layer custom properties -- so Tiled shows them, a human edits them in the
dialog they already use, `MapDocument` writes them with a byte-minimal diff,
and pytmx hands them back typed.

The point is not these six properties. It is that adding a seventh is a
one-line entry here plus whatever reads it -- no editor code, no UI code,
because the inspector renders whatever this declares.

NAMING
------
Every key is prefixed `pyoneer_`. That is not decoration: pytmx RAISES
ValueError and makes the whole map unloadable if a custom property collides
with one of its own attribute names (`data`, `name`, `width`, `height`,
`visible`, `opacity`, `rotation`, `append`, ...) -- measured, and it does not
warn or skip. `RESERVED`, re-exported below, is the whole set.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts.core.layer_profile import (  # noqa: F401
    KNOWN as ENGINE_KNOWN,
    PREFIX,
    RESERVED,
)

# The passability vocabulary. Defined ONCE, on the engine side, and re-exported
# here because everything in `editor/` already imports these names from this
# module. The bit layout is RPG Maker's -- a set bit means BLOCKED, in the
# order down, left, right, up, and STAR is an authored abstention rather than a
# fifth direction -- and it is stated in
# `scripts/core/collision_runtime.py`, for the reason `layer_profile` above is:
# the editor WRITES these gids and the engine READS them, `editor/` may import
# `scripts/` and never the reverse, and two hand-kept copies of "a set bit
# means blocked" drift into a map that walks differently in the overlay than
# in the game.
from scripts.core.collision_runtime import (  # noqa: F401
    BLOCK_ALL,
    BLOCK_DOWN,
    BLOCK_LEFT,
    BLOCK_RIGHT,
    BLOCK_UP,
    DIRECTION_NAMES,
    PASS_ALL,
    STAR,
    describe_mask,
    gid_to_mask,
    mask_to_gid,
)

# `RESERVED` -- every pytmx attribute name a custom property may never shadow
# -- is RE-EXPORTED from `scripts/core/layer_profile.py` in the import above,
# not declared here. It was declared here, as eleven remembered names, while
# the one module that could enforce it at the document door --
# `scripts/loaders/map_document.py` -- was forbidden to read it (law 2), so
# the fact sat on the wrong side of the boundary from the code that needed
# it. It is also longer than eleven: pytmx gives an object a default
# `rotation` and a layer a default `opacity` whether the file writes them or
# not, and its layer classes subclass `list`, so `rotation`, `opacity` and
# `append` are all fatal too. The set is measured off pytmx by
# `tools/check_tmx_roundtrip.py` rather than remembered.


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
