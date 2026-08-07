from __future__ import annotations
import enum

import pygame
import pytmx
from pygame import Rect
from pygame.sprite import AbstractGroup
from pygame.surface import Surface

from scripts.core.event_manager import PyoneerEvent
from scripts.core.game_object import PyoneerGameObject
from typing import Optional

from scripts.core.event_types import GameEventType
from scripts.core.component import GameComponent
from scripts.game.entity.game_entity import GameEntity
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.core.depth import MAP_DEPTH, DEPTH
from scripts.core.blitpool import BlitPool


class LayerType(str, enum.Enum):
    TILE = 'tile'
    ENTITY = 'entity'
    OBJECT = 'object'
    UI = 'ui'


class Layer(PyoneerGameObject):

    def __init__(self, layer_type: LayerType, layer_name: str, layer_depth: int, layer_surface: Surface):
        super().__init__()
        self.layer_type = layer_type
        self.layer_name = layer_name
        self.layer_depth = layer_depth
        self._image = layer_surface
        self.container: list[PyoneerGameObject] = []

    def core_prepare(self) -> Surface:
        return self._image

    def core_update(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_build(self, event: Optional[PyoneerEvent] = None):
        pass

    def core_dispose(self, event: Optional[PyoneerEvent] = None) -> bool:
        return True

    def core_image(self, image_in: Surface | None = None) -> Surface:
        return self._image

    def core_blits(self, event: Optional[PyoneerEvent] = None):
        BlitPool.blit_to_layer(depth=self.layer_depth, image=self._image, destination=(0, 0), sender=self)


    def core_inputs(self, events: list[pygame.event.Event] | pygame.event.Event):
        pass


class EntityLayer(Layer):
    def __init__(self, layer_type: LayerType, layer_name: str, layer_depth: int, layer_surface: Surface):
        super().__init__(layer_type, layer_name, layer_depth, layer_surface)
        self.entities: list[GameEntity] = []  # list of entities
        self.sprites: AbstractGroup = pygame.sprite.Group()

    def bind(self, entity: GameEntity):
        self.entities.append(entity)

    def unbind(self, entity: GameEntity):
        self.entities.remove(entity)

    def core_prepare(self) -> Surface:
        return self._image


    def core_update(self, event: Optional[PyoneerEvent] = None):
        pass
        # update all entity positions if they are within the camera's view
        #if self._camera:
        #    for entity in self.entities:
        #        #if self._camera.within_bounds(entity.world_transform.position):
        #        if self._camera.viewport.colliderect((entity.transform.position.x, entity.transform.position.y, entity.image().get_width(), entity.image().get_height())):
        #            x = entity.transform.position.x - self._camera.viewport.x
        #            y = entity.transform.position.y - self._camera.viewport.y
        #            #print(x, y, entity.transform.position.x, entity.transform.position.y, self._camera.viewport.topleft, self._camera.viewport.bottomright)
        #            if self._camera.viewport.collidepoint(entity.transform.position.x, entity.transform.position.y):
        #                self._image.blit(entity.image(), (x, y))
        #            #self._image.blit(entity.image(), (x, y))

    def core_blits(self, event: Optional[PyoneerEvent] = None):
        camera = event.data["camera"]
        view = camera.view_area
        for entity in self.entities:
            # One call. This used to invoke core_image() five times per entity
            # per frame, and for an animated entity that is a dict lookup and
            # a list index each time.
            image = entity.core_image()
            if image is None:
                continue
            # Cull against the sprite's true rect. The previous rect placed its
            # ORIGIN at position + size/2 while the blit below draws at
            # position, so the two disagreed by half a sprite: sprites popped
            # out 22px early on the right edge and 32px early on the bottom,
            # and off-screen sprites kept drawing for half a sprite past the
            # left and top.
            rect = image.get_rect(topleft=(entity.transform.position.x,
                                           entity.transform.position.y))
            if view.colliderect(rect):
                BlitPool.blit_to_layer(depth=entity.depth + self.layer_depth,
                                       priority=entity.priority,
                                       image=image,
                                       destination=(rect.x - view.x, rect.y - view.y),
                                       sender=entity)


class GameComponentLayer(Layer):
    def __init__(self, layer_type: LayerType, layer_name: str, layer_depth: int, layer_surface: Surface):
        super().__init__(layer_type, layer_name, layer_depth, layer_surface)
        self.components: list[GameComponent] = []

    def core_prepare(self) -> Surface:
        return self._image

    def core_update(self, delta: float):
        pass
        #for component in self.components:
        #    component.update(delta)

    def core_blits(self, event: Optional[PyoneerEvent]):
        for component in self.components:
            event.data["layer_depth"] = self.layer_depth
            component.core_blits(event)

    def bind(self, component: GameComponent):
        self.components.append(component)
        component.core_prepare(PyoneerEvent(GameEventType.PREPARE, sender=self))

    def unbind(self, component: GameComponent):
        self.components.remove(component)


class MapLayer(Layer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.layer: pytmx.TiledTileLayer | None = None
        self.tile_map: pytmx.TiledMap | None = None
        self.tile_width = 32
        self.tile_height = 32

    def set_layer(self, layer: pytmx.TiledTileLayer, tile_map: pytmx.TiledMap):
        self.layer: pytmx.TiledTileLayer = layer
        self.tile_map: pytmx.TiledMap = tile_map
        self.tile_width = tile_map.tilewidth
        self.tile_height = tile_map.tileheight

    def core_prepare(self) -> MapLayer:
        if self.tile_map is not None and self.layer is not None:
            # layer = self.tile_map.get_layer_by_name(self.layer_name)
            # if isinstance(layer, pytmx.TiledTileLayer):
            for x, y, gid in self.layer:
                tile = self.tile_map.get_tile_image_by_gid(gid)
                if isinstance(tile, pygame.Surface):
                    self._image.blit(tile,[x * self.tile_width + self.layer.offsetx, y * self.tile_height + self.layer.offsety])
            self._image = self._image.convert_alpha()
        return self

    def core_update(self, delta: float):
        pass

    def core_blits(self, event: Optional[PyoneerEvent]):
        """blit the map layer viewport based on the offset of the camera"""
        camera = event.data["camera"]
        BlitPool.blit_to_layer(depth=self.layer_depth, image=self._image, destination=(0, 0), draw_area=camera.view_area, sender=self)



class LayerRenderer:

    def __init__(self, surface: Surface):
        """Load the Tiled map data and the surface to render to."""
        self.tiled_maps: dict[str, pytmx.TiledMap] = {}
        self.camera: GameCamera | None = None
        self._image: Surface = surface

        """Define the layer indexes and accessors"""

        self.layers: dict[int, list[Layer | MapLayer | EntityLayer]] = dict()

    def __bind_map(self, tmx_data: pytmx.TiledMap):
        self.__prepare_map_layers(tmx_data)
        self.__prepare_entity_layers(tmx_data)

    #def prepare(self):
    #    self.prepare_map_layers()
    #    self.prepare_entity_layers()
    #    self.ready = True

    def __make_tile_layer(self, layer_name: str, layer_depth: int, layer_surface: Surface, tmx_data: pytmx.TiledMap,
                          layer: pytmx.TiledTileLayer) -> MapLayer:
        """Make a tile layer, and bind it to the layer list for rendering."""
        map_layer = MapLayer(LayerType.TILE, layer_name, layer_depth, layer_surface)
        map_layer.set_layer(layer, tmx_data)
        return map_layer

    def __get_map(self, name: str) -> pytmx.TiledMap:
        return self.tiled_maps[name]

    def __prepare_map_layers(self, tmx_data: pytmx.TiledMap):
        """Prepare the map layers"""
        for layer_name, layer_depth in MAP_DEPTH.items():
            # the map layers are taken from the map data and generated as a surface each layer
            if layer_name in tmx_data.layernames:
                layer_data = tmx_data.get_layer_by_name(layer_name)
                if layer_data and isinstance(layer_data, pytmx.TiledTileLayer):  # make the tile layers
                    self.layers[layer_depth] = [] if not self.layers.keys().__contains__(layer_depth) else self.layers[
                        layer_depth]
                    layer_surface = pygame.Surface((tmx_data.width * tmx_data.tilewidth,
                                                    tmx_data.height * tmx_data.tileheight),
                                                   pygame.SRCALPHA)
                    prepared = self.__make_tile_layer(layer_name, layer_depth, layer_surface, tmx_data, layer_data).core_prepare()
                    self.layers[layer_depth].append(prepared)
                elif layer_data and isinstance(layer_data, pytmx.TiledObjectGroup): # object group
                    pass
                elif layer_data and isinstance(layer_data, pytmx.TiledImageLayer): # image layer
                    pass
            else:
                print(f"Layer not found in map: {layer_name}")

    def image(self, image_in: Surface | None = None) -> Surface:
        if image_in:
            self._image = image_in
        return self._image

    def __prepare_entity_layers(self, tmx_data: pytmx.TiledMap):
        pass

    def bind_camera(self, camera: GameCamera):
        """Bind a camera to the renderer."""
        self.camera = camera

    def remove_camera(self):
        """Remove the camera from the renderer."""
        self.camera = None

    def __deploy_blits(self):
        """Get the render layers."""
        # Camera offset
        prepared_event = PyoneerEvent(GameEventType.BLITS, sender=self, data={"camera": self.camera})
        for layer_depth in sorted(self.layers.keys()):
            layer_list = self.layers[layer_depth]
            for layer in layer_list:
                layer.core_blits(prepared_event)
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
            raise Exception(f"Game object type {type(game_object)} not supported.")

    def __bind_entity(self, entity: GameEntity, layer_name: int | str = "ENTITY_2"):
        """Bind an entity to a specific layer."""
        depth = self.__prepare_depth(layer_name)
        if depth not in self.layers:
            self.layers[depth] = []
        layer_found = False
        for layer in self.layers[depth]:
            if isinstance(layer, EntityLayer):
                layer.bind(entity)
                layer_found = True
                break
        if not layer_found:
            layer = EntityLayer(LayerType.ENTITY, layer_name, depth, self.image())
            layer.bind(entity)
            self.layers[depth].append(layer)

    def __prepare_depth(self, depth: int | str):
        if isinstance(depth, int):
            return depth
        if depth in DEPTH:
            return DEPTH[depth]
        raise Exception(f"Layer name {depth} not found in core depth maps, did you mean to use an int?")

    def __bind_ui_component(self, widget: GameComponent, layer_name: str | int = "UI"):
        depth = self.__prepare_depth(layer_name)
        if depth not in self.layers:
            self.layers[depth] = []
        layer = GameComponentLayer(LayerType.UI, layer_name, depth + len(self.layers[depth]), Surface(widget.world_bounds.size))
        layer.bind(widget)
        self.layers[depth].append(layer)

    def update(self, delta: float):
        """update all available layers."""
        if self.camera:
            for layer_list in self.layers.values():
                for layer in layer_list:
                    layer.core_update(delta)
        else:
            raise Exception("No camera bound to renderer.")

    def render(self):
        """draw all available layers."""
        if self.camera:
            #try:
                self.image().blits(self.__deploy_blits())
            #except Exception as e:
            #    print(e)
        else:
            raise Exception("No camera bound to renderer.")

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
