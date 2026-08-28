from __future__ import annotations

import pygame
import pytmx
from pygame import Rect
from pygame.surface import Surface

from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject
from typing import Optional

from scripts.core.event_types import GameEventType
from scripts.core.component import GameComponent
from scripts.game.entity.game_entity import GameEntity
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.core.depth import MAP_DEPTH, DEPTH, resolve_layer_depth
from scripts.core import layer_profile
from scripts.core.collision_runtime import CollisionField, field_from_map
from scripts.core.blitpool import BlitPool
from scripts.core.viewclip import clip_to_view, containment, Containment
from scripts.core.log import trace_lifecycle, trace_render
from scripts.core.errors import (PyoneerBindTargetError, PyoneerCameraMissingError,
                                 PyoneerLayerError, warn_content)
from scripts.game.behavior import build as build_behaviors
from scripts.loaders.map_loader import SpawnedEntity, spawn_objects
from scripts.loaders.table_file import ProjectTables


def drawable_tile_count(layer: pytmx.TiledTileLayer, tile_map: pytmx.TiledMap) -> int:
    """How many cells of this tile layer actually resolve to a surface.

    A Tiled file happily carries layers that are declared but empty, and
    rasterizing one costs a full-map SRCALPHA surface plus a blit token every
    frame. The gid test alone is not enough -- a gid can be non-zero and still
    resolve to None -- so this counts what the bake would actually draw.
    """
    count = 0
    for _x, _y, gid in layer:
        if gid and isinstance(tile_map.get_tile_image_by_gid(gid), pygame.Surface):
            count += 1
    return count


def opaque_mask(surface: Surface) -> pygame.mask.Mask:
    """Pixels with alpha exactly 255."""
    return pygame.mask.from_surface(surface, 254)


def partial_alpha_mask(surface: Surface) -> pygame.mask.Mask:
    """Pixels with alpha strictly between 0 and 255."""
    mask = pygame.mask.from_surface(surface, 0)
    mask.erase(opaque_mask(surface), (0, 0))
    return mask


class Layer(PyoneerGameObject):

    def __init__(self, layer_name: str, layer_depth: int, layer_surface: Surface):
        super().__init__()
        self.layer_name = layer_name
        self.layer_depth = layer_depth
        self._image = layer_surface

    def core_lifecycle_prepare(self) -> Surface:
        return self._image

    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_lifecycle_build(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_lifecycle_dispose(self, event: Optional[PyoneerEvent] = None) -> bool:
        return True

    def core_render_blits(self, event: Optional[PyoneerEvent] = None):
        BlitPool.blit_to_layer(depth=self.layer_depth, image=self._image, destination=(0, 0), sender=self)


    def core_input_receive(self, events: list[pygame.event.Event] | pygame.event.Event):
        pass


class EntityLayer(Layer):
    def __init__(self, layer_name: str, layer_depth: int, layer_surface: Surface):
        super().__init__(layer_name, layer_depth, layer_surface)
        self.entities: list[GameEntity] = []  # list of entities

    def bind(self, entity: GameEntity):
        self.entities.append(entity)

    def unbind(self, entity: GameEntity):
        self.entities.remove(entity)

    def core_lifecycle_prepare(self) -> Surface:
        return self._image


    def core_frame_update(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_render_blits(self, event: Optional[PyoneerEvent] = None):
        camera = event.data["camera"]
        view = camera.view_area
        for entity in self.entities:
            # One call: for an animated entity each access is a dict lookup
            # and a list index.
            image = entity.image
            if image is None:
                continue
            # Cull against the sprite's TRUE rect: the blit below draws at
            # position, so a rect anchored anywhere else disagrees with it by
            # that offset and sprites pop in and out early at the edges.
            rect = image.get_rect(topleft=(entity.transform.position.x,
                                           entity.transform.position.y))
            # clip_to_view culls and clips in one step, so a sprite straddling
            # the camera edge queues only the pixels that are actually inside
            # rather than relying on pygame's blits() to trim it afterwards.
            clipped = clip_to_view(rect, view)
            if clipped is None:
                BlitPool.count_culled()
                continue
            BlitPool.blit_to_layer(depth=entity.depth + self.layer_depth,
                                   priority=entity.priority,
                                   image=image,
                                   destination=(clipped.destination[0] - view.x,
                                                clipped.destination[1] - view.y),
                                   draw_area=clipped.source_area,
                                   sender=entity)


class GameComponentLayer(Layer):
    def __init__(self, layer_name: str, layer_depth: int, layer_surface: Surface):
        super().__init__(layer_name, layer_depth, layer_surface)
        self.components: list[GameComponent] = []

    def core_lifecycle_prepare(self) -> Surface:
        return self._image

    def core_frame_update(self, delta: float):
        pass

    def core_render_blits(self, event: Optional[PyoneerEvent]):
        for component in self.components:
            event.data["layer_depth"] = self.layer_depth
            component.core_render_blits(event)

    def bind(self, component: GameComponent):
        self.components.append(component)
        component.core_lifecycle_prepare(PyoneerEvent(GameEventType.PREPARE, sender=self))

    def unbind(self, component: GameComponent):
        self.components.remove(component)


class MapLayer(Layer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.layer: pytmx.TiledTileLayer | None = None
        self.tile_map: pytmx.TiledMap | None = None
        self.tile_width = 32
        self.tile_height = 32
        # What the tmx says this layer is. Read once at bind time; see
        # scripts/core/layer_profile.py for the vocabulary.
        self.profile = layer_profile.DEFAULT

    def set_layer(self, layer: pytmx.TiledTileLayer, tile_map: pytmx.TiledMap):
        self.layer: pytmx.TiledTileLayer = layer
        self.tile_map: pytmx.TiledMap = tile_map
        self.tile_width = tile_map.tilewidth
        self.tile_height = tile_map.tileheight
        self.profile = layer_profile.read(layer)

    @property
    def static(self) -> bool:
        """Whether this layer may be flattened into a composite."""
        return self.profile.static

    def rebake(self) -> MapLayer:
        """Re-rasterize this layer's tiles onto its own surface.

        Split out of core_lifecycle_prepare so runtime map editing has an
        entry point: change gids in the pytmx layer, call rebake(), then
        LayerRenderer.invalidate() so any composite holding this layer picks
        the new pixels up.
        """
        if self.tile_map is None or self.layer is None:
            return self
        self._image.fill((0, 0, 0, 0))
        for x, y, gid in self.layer:
            tile = self.tile_map.get_tile_image_by_gid(gid)
            if isinstance(tile, pygame.Surface):
                self._image.blit(tile, [x * self.tile_width + self.layer.offsetx,
                                        y * self.tile_height + self.layer.offsety])
        self._image = self._image.convert_alpha()
        return self

    def core_lifecycle_prepare(self) -> MapLayer:
        return self.rebake()

    def core_frame_update(self, delta: float):
        pass

    def core_render_blits(self, event: Optional[PyoneerEvent]):
        """Blit this layer's viewport, offset by its parallax factor."""
        camera = event.data["camera"]
        view = camera.view_area
        if self.profile.parallaxed:
            view = layer_profile.parallax_view(
                view, self.profile.parallax,
                self._image.get_width(), self._image.get_height())
        BlitPool.blit_to_layer(depth=self.layer_depth, image=self._image,
                               destination=(0, 0), draw_area=view, sender=self)


class MapComposite(Layer):
    """One baked surface standing in for a run of consecutive static tile layers.

    N full-map tile layers cost N viewport blits per frame redrawing pixels
    that never change; baking them into one surface turns that into one blit.

    It is NOT unconditional. pygame's RGBA->RGBA blit writes the blended
    colour WITHOUT re-dividing by the resulting alpha, so partial alpha
    landing on partial alpha has its alpha applied a second time at the final
    blit. A composite is therefore only built where it is PROVABLY
    pixel-identical -- see `composite_is_exact`. Groups that fail are left as
    separate layers, which is slower but correct.

    Baking happens in `rebake`, never in `__init__`, so runtime map editing
    has an entry point.
    """

    def __init__(self, sources: list[MapLayer], layer_depth: int):
        if not sources:
            raise PyoneerLayerError("MapComposite needs at least one source MapLayer")
        name = "+".join(str(source.layer_name) for source in sources)
        super().__init__(name, layer_depth, None)
        self.sources: list[MapLayer] = list(sources)
        self.depth_band: tuple[int, int] = (min(s.layer_depth for s in sources),
                                            max(s.layer_depth for s in sources))
        self.opaque: bool = False
        """True when the bake covers its whole surface at alpha 255.

        The surface can then drop its alpha channel entirely (`.convert()`),
        which is the cheaper blit.
        """

    def covers(self, depth_band: tuple[int, int]) -> bool:
        """Does this composite hold any layer inside the given depth band?"""
        return not (depth_band[1] < self.depth_band[0] or depth_band[0] > self.depth_band[1])

    def rebake(self) -> MapComposite:
        """Flatten the source layers, in depth order, into a single surface."""
        ordered = sorted(self.sources, key=lambda s: s.layer_depth)
        size = ordered[0].require_image().get_size()
        baked = pygame.Surface(size, pygame.SRCALPHA)
        for source in ordered:
            baked.blit(source.require_image(), (0, 0))
        self.opaque = opaque_mask(baked).count() == size[0] * size[1]
        # An opaque composite has nothing to blend, so drop the alpha channel:
        # .convert() is a straight copy where .convert_alpha() is a per-pixel
        # blend. The pixels are identical either way because every alpha is
        # already 255.
        self._image = baked.convert() if self.opaque else baked.convert_alpha()
        trace_render("baked composite %s depth=%s band=%s opaque=%s",
                     self.layer_name, self.layer_depth, self.depth_band, self.opaque)
        return self

    def core_lifecycle_prepare(self) -> MapComposite:
        return self.rebake()

    def core_frame_update(self, delta: float):
        pass

    def core_render_blits(self, event: Optional[PyoneerEvent]):
        camera = event.data["camera"]
        BlitPool.blit_to_layer(depth=self.layer_depth, image=self.require_image(),
                               destination=(0, 0), draw_area=camera.view_area,
                               sender=self)


MaskCache = dict


def _masks(surface: Surface, cache: MaskCache | None) -> tuple[pygame.mask.Mask, pygame.mask.Mask]:
    """Opaque and partial-alpha masks, optionally memoized within one pass.

    `pygame.mask.from_surface` over a full-map layer is expensive, and
    `__split_exact_groups` calls `composite_is_exact` with GROWING PREFIXES of
    the same run, so without a cache each surface is re-masked once per
    extension.

    The cache is passed IN and scoped to a single grouping pass, never module
    global: it is keyed on `id()`, and CPython reuses the id of a freed
    object, so only a caller holding every surface alive makes those keys
    safe.
    """
    if cache is None:
        opaque = opaque_mask(surface)
        partial = pygame.mask.from_surface(surface, 0)
        partial.erase(opaque, (0, 0))
        return opaque, partial
    key = id(surface)
    hit = cache.get(key)
    if hit is not None:
        return hit
    opaque = opaque_mask(surface)
    partial = pygame.mask.from_surface(surface, 0)
    partial.erase(opaque, (0, 0))
    cache[key] = (opaque, partial)
    return opaque, partial


def composite_is_exact(surfaces: list[Surface], cache: MaskCache | None = None) -> bool:
    """Can these surfaces be flattened without moving a single screen pixel?

    Flattening replaces `screen <- L0 <- L1 <- ...` with
    `empty <- L0 <- L1 <- ... ; screen <- composite`. Whether that is
    lossless depends on pygame's RGBA->RGBA blitter, measured on pygame
    2.6.0 / SDL 2.28.4:

        destination alpha 0    the source pixel is COPIED verbatim, colour
                               and alpha, so nothing is lost.
        destination alpha 255  a normal source-over blend onto a known
                               colour, and the result is still opaque.
        destination alpha in   the blended colour is written back WITHOUT
        between                being re-divided by the resulting alpha, so
                               the source's alpha is applied a second time
                               at the final blit to the screen.

    Only the last row is lossy, and only when the incoming pixel is itself
    partially transparent (alpha 255 overwrites, alpha 0 is a no-op), so the
    single disqualifying event is PARTIAL ALPHA LANDING ON PARTIAL ALPHA.

    A pixel is forgiven even then if a later layer is fully opaque there,
    because the bad value is overwritten before the composite is ever used.
    """
    if len(surfaces) < 2:
        return True
    computed = [_masks(s, cache) for s in surfaces]
    opaque = [m[0] for m in computed]
    partial = [m[1] for m in computed]
    size = surfaces[0].get_size()

    # later[i] = union of the opaque masks of everything drawn after i.
    later: list[pygame.mask.Mask] = [pygame.mask.Mask(size) for _ in surfaces]
    for index in range(len(surfaces) - 2, -1, -1):
        later[index] = later[index + 1].copy()
        later[index].draw(opaque[index + 1], (0, 0))

    # Per-pixel state of the buffer so far: FULL once some layer wrote alpha
    # 255 there (it can never go back), PARTIAL once a partial pixel landed on
    # an untouched spot, otherwise still untouched.
    full = pygame.mask.Mask(size)
    part = pygame.mask.Mask(size)
    for index in range(len(surfaces)):
        incoming = partial[index]
        if incoming.count():
            unsafe = incoming.overlap_mask(part, (0, 0))
            unsafe.erase(later[index], (0, 0))
            if unsafe.count():
                trace_render("composite rejected at index %s: %s partial-alpha "
                             "pixels land on partial alpha and survive", index,
                             unsafe.count())
                return False
            fresh = incoming.copy()
            fresh.erase(full, (0, 0))
            part.draw(fresh, (0, 0))
        part.erase(opaque[index], (0, 0))
        full.draw(opaque[index], (0, 0))
    return True



class LayerRenderer:

    def __init__(self, surface: Surface):
        """Load the Tiled map data and the surface to render to."""
        self.camera: GameCamera | None = None
        self._image: Surface = surface

        """Define the layer indexes and accessors"""

        self.layers: dict[int, list[Layer | MapLayer | EntityLayer]] = dict()

        self.map_sources: dict[int, list[MapLayer]] = dict()
        """Every rasterized tile layer, by depth. The authority.

        `self.layers` is DERIVED from this: a run of these may be replaced by
        one MapComposite. Keeping the sources means a rebake can always
        reconstruct the ungrouped state, so rebaking twice never composites a
        composite.
        """

        self._map_regroup: bool = False
        self._map_regroup_rebakes: bool = True
        """Whether the pending regroup should also re-rasterize sources."""
        """Grouping is stale: which layers can merge has to be recomputed."""

        self._map_invalid: set[tuple[int, int]] = set()
        """Depth bands whose pixels are stale but whose grouping still holds."""

        self.spawn_defaults: dict[str, dict] = {}
        """Per-type constructor keyword arguments for map-placed objects.

        A .tmx object carries a type, a position and custom properties, but it
        cannot carry an `InputActionManager` or a parsed animation category,
        and the renderer owns no asset managers to build them from. Whoever
        does hands them over before the map is bound. Empty means every
        registered class is constructible with no arguments.
        """

        self.tables: ProjectTables | None = None
        """The project's data tables, or None when nobody loaded any.

        Sits beside `spawn_defaults` because it is the same kind of thing: a
        value a .tmx object cannot carry, handed over before the map is bound.
        An object's `pyoneer_actor` names a row in here, and that row is the
        middle rung of behavior-parameter resolution -- under the object's own
        `pyoneer_param_*`, over each parameter's default.

        The renderer holds it for the reason it holds `collision_field`: it is
        the single funnel every entity passes through, so one slot serves the
        map spawn and `SceneManager.spawn` alike.

        None costs nothing -- `actor_row` returns None for an object that
        names no row. `main.py` assigns `load_tables()` at boot.
        """

        self.spawned_entities: list[SpawnedEntity] = []
        """What the last map bind spawned, in document order.

        Binding into an `EntityLayer` is only half of what a live entity
        needs: `EntityLayer.core_frame_update` is a no-op, so an entity that
        exists only here holds its first frame forever. `SceneManager` reads
        this list after `renderer.bind(GameMap)` and binds the same entities
        into the scene, which is what drives their frame updates. The renderer
        cannot do that itself -- `scene_manager` already imports `renderer`,
        so reaching back would be an import cycle.
        """

        self.collision_field: CollisionField | None = None
        """The bound map's baked passability, or None when it declares none.

        The renderer holds it because it is where the two halves meet: it is
        handed the parsed map, and it is the single funnel every entity passes
        through on its way into a frame -- `bind()` for hand-built ones,
        `__prepare_entity_layers` for map-placed ones. `__gate` is the only
        thing that hands it out, so the two cannot end up gated differently.

        None means UNGATED: a map that authors no passability costs nothing.
        """

    def __bind_map(self, tmx_data: pytmx.TiledMap):
        # BEFORE the layers, not after: __prepare_entity_layers spawns this
        # map's own objects and __gate_entities hands them this field, so
        # baking afterwards would gate them on the PREVIOUS map's field.
        self.collision_field = field_from_map(tmx_data)
        self.__prepare_map_layers(tmx_data)
        self.__prepare_entity_layers(tmx_data)
        # One sweep here plus one call in __bind_entity gates every entity
        # the renderer draws, whether the map placed it or a caller bound it,
        # and whether that happened before this map or after -- so a caller
        # has no ordering rule to get wrong.
        self.__gate_entities()

    def __gate(self, entity: GameEntity) -> None:
        """Hand `entity` the passability of the map it is being drawn on.

        The only assignment to `collision_field` in the engine: an entity that
        reached a frame ungated would not raise and not warn, it would just
        walk through walls.

        Assigns unconditionally, None included. "This map declares no
        passability" is a real answer and must overwrite a previous map's
        field. A caller wanting a hand-built field sets it AFTER the bind.
        """
        entity.collision_field = self.collision_field

    def __gate_entities(self) -> None:
        """Re-gate every entity the renderer currently draws."""
        for layers in self.layers.values():
            for layer in layers:
                if isinstance(layer, EntityLayer):
                    for entity in layer.entities:
                        self.__gate(entity)

    def __make_tile_layer(self, layer_name: str, layer_depth: int, layer_surface: Surface, tmx_data: pytmx.TiledMap,
                          layer: pytmx.TiledTileLayer) -> MapLayer:
        """Make a tile layer, and bind it to the layer list for rendering."""
        map_layer = MapLayer(layer_name, layer_depth, layer_surface)
        map_layer.set_layer(layer, tmx_data)
        return map_layer

    def __prepare_map_layers(self, tmx_data: pytmx.TiledMap):
        """Rasterize every tile layer the MAP declares.

        Driven from the MAP, not from `MAP_DEPTH`: iterating the code's list
        of layer names and looking each one up warns about names the map never
        had while silently dropping layers the map has and the code does not
        name. Driving from the map means authored content is never lost
        without a warning naming the exact layer.

        Two reasons a tile layer is skipped, and only one of them is a
        mistake. A layer with no depth is content the author expected to see
        and will not, so it WARNS. A layer declaring `pyoneer_renders=false`
        is doing exactly what it says, so it is silent.
        """
        for layer_data in tmx_data.layers:
            layer_name = getattr(layer_data, 'name', None)
            if not isinstance(layer_data, pytmx.TiledTileLayer):
                # Object groups and image layers are handled elsewhere; group
                # wrappers carry no tiles of their own.
                continue

            if not layer_profile.read(layer_data).renders:
                # DATA, NOT ART, and the declaration is what makes it   #TAG:renders_false_is_data
                # so. A passability companion's cells are mask numbers
                # read as gids, so drawing one paints the mask vocabulary
                # over the map -- which is why the depth is not even
                # looked up here: a name that happens to resolve is not
                # permission to draw over an explicit refusal, and a name
                # that does not resolve is not a mistake to advise about.
                continue

            layer_depth = resolve_layer_depth(layer_name)
            if layer_depth is None:
                warn_content(
                    f"map layer {layer_name!r} has no depth mapping in "
                    f"scripts/core/depth.py and will NOT be drawn. If it is "
                    f"ART, give that NAME a depth in MAP_DEPTH: renaming the "
                    f"layer to one that already has a depth is not the same "
                    f"move, because pyoneer_passability names a layer as a "
                    f"string and does not follow a rename, so a companion "
                    f"pointing here goes unread and collision on the layer "
                    f"that owns it turns off. If it is DATA -- a passability "
                    f"companion, a mask layer -- declare pyoneer_renders=false "
                    f"on it and it is skipped without this warning."
                )
                continue

            if drawable_tile_count(layer_data, tmx_data) == 0:
                # The .tmx says this layer exists, so say out loud that it
                # was dropped. An empty layer is cheap to skip but must not be
                # invisible to the author.
                warn_content(
                    f"map layer {layer_name!r} (depth {layer_depth}) has no "
                    f"drawable tiles and was skipped: no surface allocated and "
                    f"no blit queued. Delete it in Tiled, or put tiles in it."
                )
                continue

            self.layers.setdefault(layer_depth, [])
            layer_surface = pygame.Surface((tmx_data.width * tmx_data.tilewidth,
                                            tmx_data.height * tmx_data.tileheight),
                                           pygame.SRCALPHA)
            prepared = self.__make_tile_layer(layer_name, layer_depth, layer_surface,
                                              tmx_data, layer_data).core_lifecycle_prepare()
            self.layers[layer_depth].append(prepared)
            self.map_sources.setdefault(layer_depth, []).append(prepared)

        # Binding a map changes which depths hold tiles, so the grouping is
        # stale by definition. Deliberately NOT baked here: the bake runs from
        # render() once the layer set has settled, so binding entities
        # afterwards cannot leave a composite straddling them.
        self.invalidate(sources_dirty=False)

    def invalidate(self, depth_band: int | tuple[int, int] | None = None,
                   *, sources_dirty: bool = True) -> None:
        """Mark baked map composites stale; the next render() rebakes them.

        This is the runtime-map-editing entry point. Edit tiles, then:

            renderer.invalidate(50)          # one depth
            renderer.invalidate((10, 30))    # a band
            renderer.invalidate()            # everything, including regrouping

        Every one of those re-rasterizes the affected source layers before
        re-flattening, so a content change actually reaches the screen. Passing
        None additionally recomputes the GROUPING, which is what a layer
        being added or removed needs, since a new layer can split a
        previously contiguous run.

        sources_dirty=False says "the layer SET changed but no layer's CONTENT
        did" -- regroup without re-rasterizing. Only __bind_map uses it,
        because __prepare_map_layers has just baked every source itself.
        Getting it wrong is silent: skipping the rebake makes a tile edit
        followed by invalidate() render the old pixels with no error.
        """
        if depth_band is None:
            self._map_regroup = True
            self._map_regroup_rebakes = sources_dirty
            self._map_invalid.clear()
            return
        if isinstance(depth_band, int):
            depth_band = (depth_band, depth_band)
        low, high = int(depth_band[0]), int(depth_band[1])
        self._map_invalid.add((min(low, high), max(low, high)))

    def rebake_map(self) -> None:
        """Do the work invalidate() asked for. Idempotent."""
        if self._map_regroup:
            self._map_invalid.clear()
            self._map_regroup = False
            # Re-rasterize unless the caller said the content is unchanged.
            # __bind_map passes sources_dirty=False because the sources are
            # freshly baked; everyone else calling invalidate() means
            # "something changed" and must not get stale pixels.
            if self._map_regroup_rebakes:
                for layers in self.map_sources.values():
                    for source in layers:
                        source.rebake()
            self._map_regroup_rebakes = True
            self.__regroup_map_layers()
            return

        bands = self._map_invalid
        self._map_invalid = set()
        for depth, layers in self.map_sources.items():
            if any(band[0] <= depth <= band[1] for band in bands):
                for source in layers:
                    source.rebake()
        for layer_list in self.layers.values():
            for layer in layer_list:
                if isinstance(layer, MapComposite) and any(layer.covers(b) for b in bands):
                    layer.rebake()

    def __regroup_map_layers(self) -> None:
        """Replace runs of tile-only depths with one MapComposite each.

        Draw order is preserved by construction: a run is a MAXIMAL span of
        consecutive depths (in the renderer's own sort order) holding nothing
        but tile layers, so an entity or UI layer anywhere in the range ends
        the run there and the entities still interleave.
        """
        for depth in list(self.layers):
            self.layers[depth] = [layer for layer in self.layers[depth]
                                  if not isinstance(layer, (MapLayer, MapComposite))]
            if not self.layers[depth]:
                del self.layers[depth]

        # Whatever survived the strip is a non-tile layer, so its depth
        # breaks a run. A depth holding BOTH tiles and entities is such a
        # break: the tile layer is reinserted there on its own, at the front,
        # which is the order __prepare_map_layers established.
        #
        # A DECLARED-dynamic layer breaks a run the same way, and that is the
        # whole implementation of "dynamic": not a new draw path, just
        # exclusion from the bake. Parallaxed and semi-transparent layers are
        # excluded too, because both are modulated at blit time and a
        # composite cannot represent that.
        blocking = set(self.layers) | {
            depth for depth, sources in self.map_sources.items()
            if any(not getattr(source, "static", True) for source in sources)
        }
        runs: list[list[int]] = []
        current: list[int] = []
        for depth in sorted(set(self.map_sources) | blocking):
            if depth in self.map_sources and depth not in blocking:
                current.append(depth)
            else:
                if current:
                    runs.append(current)
                current = []
                if depth in self.map_sources:
                    # setdefault, not [depth]: a declared-dynamic tile layer
                    # blocks without anything else living at its depth, so the
                    # depth need not already be a key here.
                    self.layers.setdefault(depth, [])
                    for source in reversed(self.map_sources[depth]):
                        self.layers[depth].insert(0, source)
        if current:
            runs.append(current)

        for run in runs:
            sources = [source for depth in run for source in self.map_sources[depth]]
            for group in self.__split_exact_groups(sources):
                depth = group[0].layer_depth
                self.layers.setdefault(depth, [])
                if len(group) == 1:
                    self.layers[depth].append(group[0])
                else:
                    self.layers[depth].append(MapComposite(group, depth).rebake())

    @staticmethod
    def __split_exact_groups(sources: list[MapLayer]) -> list[list[MapLayer]]:
        """Greedily cut a run into the longest provably-exact merge groups.

        All-or-nothing would throw away a legal merge because of one bad layer
        further down the run, so a group extends while `composite_is_exact`
        still holds and a new one starts at the layer that breaks it.
        """
        groups: list[list[MapLayer]] = []
        current: list[MapLayer] = []
        # One cache for this pass only. `sources` holds every surface alive
        # for its lifetime, so id() keys cannot collide with a freed object.
        cache: MaskCache = {}
        for source in sources:
            candidate = current + [source]
            if len(candidate) > 1 and not composite_is_exact(
                    [layer.require_image() for layer in candidate], cache):
                groups.append(current)
                current = [source]
            else:
                current = candidate
        if current:
            groups.append(current)
        return groups

    def image(self, image_in: Surface | None = None) -> Surface:
        if image_in:
            self._image = image_in
        return self._image

    def __prepare_entity_layers(self, tmx_data: pytmx.TiledMap):
        """Spawn every typed object on the map's object layers and bind it.

        `scripts/loaders/map_loader.py` constructs and positions the entities,
        `scripts/core/spawn.py` says which class and which depth, and this is
        where they become part of a frame.

        It runs inside `__bind_map`, AFTER the tile layers are rasterized and
        BEFORE anything renders, so every `EntityLayer` created here is folded
        into the single regroup `__prepare_map_layers` already flagged. A
        spawn after the first render would leave a composite already baked
        across the depths the entities landed on, and they would draw under
        tiles meant to be behind them.

        It asks for that regroup ONCE for the whole batch rather than calling
        `__bind_entity` per entity: each of those would call `invalidate()`
        with `sources_dirty` defaulting to True, re-rasterizing every tile
        layer that was just rasterized.

        The properties are read through `MapDocument` rather than pytmx, which
        casts a custom property only when the file carries `type="int"` -- a
        depth would otherwise arrive as the string `'50'`, which is truthy,
        is not 50, and keys nothing in `self.layers`.

        It does NOT gate the entities it binds. `__bind_map` sweeps every
        bound entity immediately after this returns, and that one sweep also
        catches an entity bound BEFORE the map.
        """
        spawned = spawn_objects(tmx_data, defaults=self.spawn_defaults,
                                tables=self.tables)
        self.spawned_entities = spawned
        regroup = False
        for record in spawned:
            # Compose BEFORE bind, so an entity is never bound in a
            # half-composed state. attach_all raises on a duplicated token or
            # a declared conflict -- authoring errors that must surface at
            # load rather than as a physics bug later.
            if record.behaviors:
                record.entity.behaviors.attach_all(
                    build_behaviors(record.behaviors))
            layer, created = self.__entity_layer(record.depth, record.layer_name)
            layer.bind(record.entity)
            regroup = regroup or (created and self.__inside_map_span(record.depth))
        if regroup:
            # sources_dirty=False: the sources are freshly baked, only the
            # GROUPING is stale, and re-rasterizing cannot change a pixel.
            self.invalidate(sources_dirty=False)
        if spawned:
            trace_lifecycle("map spawn bound %d entities at depths %s",
                            len(spawned),
                            sorted({record.depth for record in spawned}))

    def bind_camera(self, camera: GameCamera):
        """Bind a camera to the renderer."""
        self.camera = camera

    def remove_camera(self):
        """Remove the camera from the renderer."""
        self.camera = None

    def __deploy_blits(self):
        """Get the render layers."""
        # Camera offset
        prepared_event = PyoneerEvent(
            GameEventType.BLITS,
            sender=self,
            data={
                "camera": self.camera,
                # UI lives in screen space and has no camera, but has the
                # same "is any of this visible" problem. The screen rect is
                # its clip region.
                "screen": self._image.get_rect(),
            },
        )
        for layer_depth in sorted(self.layers.keys()):
            layer_list = self.layers[layer_depth]
            for layer in layer_list:
                layer.core_render_blits(prepared_event)
        return BlitPool.get_blit_pool_pygame(True)

    def bind(self, layer: str | int, game_object: PyoneerGameObject):
        """Bind a game object to a specific layer."""
        if isinstance(game_object, GameEntity):
            self.__bind_entity(game_object, layer)
        elif isinstance(game_object, GameMap):
            self.__bind_map(game_object.tmx_data)
        elif isinstance(game_object, GameComponent):
            self.__bind_ui_component(game_object, layer)
        else:
            raise PyoneerBindTargetError(
                game_object,
                supported=("GameEntity", "GameMap", "GameComponent"),
            )

    def unbind(self, game_object: PyoneerGameObject) -> bool:
        """Stop drawing `game_object`. The inverse of `bind`.

        Without this an object taken out of the scene stays in the renderer
        and `EntityLayer.core_render_blits` goes on queueing a blit token for
        it every frame, forever.

        Returns whether anything was removed, so a caller can tell "taken out"
        from "was never in" -- `SceneManager.despawn` needs that to be
        idempotent. Silent on a miss rather than raising: removing something
        already absent is a request already satisfied.

        Identity, never equality. `list.remove` uses `==`, so an object
        defining `__eq__` would make this remove a DIFFERENT one that merely
        compares equal, and the symptom would be the wrong sprite vanishing.

        The layer itself is kept even when it empties. Recreating one calls
        `__invalidate_if_inside_map_span` and buys a full regroup; an empty
        layer costs one loop iteration that queues nothing.
        """
        for layers in self.layers.values():
            for layer in layers:
                if isinstance(layer, EntityLayer):
                    held = layer.entities
                elif isinstance(layer, GameComponentLayer):
                    held = layer.components
                else:
                    continue
                for index, candidate in enumerate(held):
                    if candidate is game_object:
                        del held[index]
                        trace_lifecycle("unbound %s from layer %s at depth %s",
                                        type(game_object).__name__,
                                        layer.layer_name, layer.layer_depth)
                        return True
        return False

    def __entity_layer(self, depth: int, layer_name: int | str) -> tuple[EntityLayer, bool]:
        """The EntityLayer at `depth`, creating one if that depth has none.

        Returns (layer, created). Creating one is the only case that can split
        a run of tile layers, and the two callers pay for the resulting
        regroup at different moments -- see `__prepare_entity_layers`.
        """
        layers = self.layers.setdefault(depth, [])
        for layer in layers:
            if isinstance(layer, EntityLayer):
                return layer, False
        created = EntityLayer(layer_name, depth, self.image())
        layers.append(created)
        return created, True

    def __bind_entity(self, entity: GameEntity, layer_name: int | str = "ENTITY_2"):
        """Bind an entity to a specific layer."""
        depth = self.__prepare_depth(layer_name)
        layer, created = self.__entity_layer(depth, layer_name)
        layer.bind(entity)
        # The hand-built half of the gate; a map-placed entity arrives
        # through __prepare_entity_layers. Both are gated by the same call
        # with the same field.
        self.__gate(entity)
        if created:
            # A new entity layer can land in the middle of a run of tile
            # layers, and a composite spanning it would draw the tiles above
            # the entities. Only regroup when that is possible.
            self.__invalidate_if_inside_map_span(depth)

    def __inside_map_span(self, depth: int) -> bool:
        """Could a new layer at `depth` land inside a run of tile layers?

        Strictly between the lowest and the highest tile depth: a layer at or
        outside either end has no run to cut in half. UI at depth 100+ never
        can, and neither can an object group that resolved above every tile.
        """
        if not self.map_sources:
            return False
        return min(self.map_sources) < depth < max(self.map_sources)

    def __invalidate_if_inside_map_span(self, depth: int) -> None:
        """Regroup ONLY if a new layer at `depth` could split a tile run.

        An unconditional `invalidate()` sets the regroup flag and buys a full
        restructure on the next `render()`, so the first window opened or
        entity spawned mid-game would eat a stall measured in tenths of a
        second.
        """
        if self.__inside_map_span(depth):
            self.invalidate()

    def __prepare_depth(self, depth: int | str):
        if isinstance(depth, int):
            return depth
        if depth in DEPTH:
            return DEPTH[depth]
        raise PyoneerLayerError(
            f"layer name {depth!r} is not in the core depth maps; "
            f"pass an int depth, or add it to scripts/core/depth.py. "
            f"known: {sorted(DEPTH)}"
        )

    def __bind_ui_component(self, widget: GameComponent, layer_name: str | int = "UI"):
        depth = self.__prepare_depth(layer_name)
        if depth not in self.layers:
            self.layers[depth] = []
        layer = GameComponentLayer(layer_name, depth + len(self.layers[depth]), Surface(widget.world_bounds.size))
        layer.bind(widget)
        self.layers[depth].append(layer)
        self.__invalidate_if_inside_map_span(depth)

    def update(self, delta: float):
        """update all available layers."""
        if self.camera:
            for layer_list in self.layers.values():
                for layer in layer_list:
                    layer.core_frame_update(delta)
        else:
            raise PyoneerCameraMissingError(
                "renderer was driven with no camera bound; "
                "call LayerRenderer.bind_camera() before update/render"
            )

    def render(self):
        """draw all available layers."""
        if self.camera:
            # Lazy, not eager: the bake runs once after the layer set
            # settles, and again only when something calls invalidate(). Doing
            # it here rather than in a constructor keeps runtime map editing
            # possible.
            if self._map_regroup or self._map_invalid:
                self.rebake_map()
            self.image().blits(self.__deploy_blits())
        else:
            raise PyoneerCameraMissingError(
                "renderer was driven with no camera bound; "
                "call LayerRenderer.bind_camera() before update/render"
            )

    def rotate_image(self, image, position, origin, angle) -> tuple[Surface, Rect]:
        if angle == 0:
            return image, image.get_rect(center=position)
        # offset from pivot to center
        image_rect = image.get_rect(topleft=(position[0] - origin[0], position[1] - origin[1]))
        offset_center_to_pivot = pygame.math.Vector2(position) - image_rect.center

        # rotated offset from pivot to center
        rotated_offset = offset_center_to_pivot.rotate(-angle)

        # rotated image center
        rotated_image_center = (position[0] - rotated_offset.x, position[1] - rotated_offset.y)

        # get a rotated image
        rotated_image = pygame.transform.rotate(image, angle)
        rotated_image_rect = rotated_image.get_rect(center=rotated_image_center)

        return rotated_image, rotated_image_rect
