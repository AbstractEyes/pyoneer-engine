"""Prove the map's passability actually reaches the bodies that move on it.

`tools/check_collision_runtime.py` proves the mask vocabulary, the boundary
walk and `allowed_distance`. `tools/check_movement.py` proves the two movement
behaviors call the gate. Neither proves anything is CONNECTED: with
`GameEntity.collision_field` assigned by nothing, `move_direction` walks
through painted walls and a `platformer_move` body accelerates downward
forever and never lands. That wire is what this file tests, and it has exactly
three claims:

    a body on a map WITH a mask is stopped by it
    the same body on a map WITHOUT a passability layer is stopped by nothing
    a platformer body on a floor LANDS, at the pixel the floor puts it at

WHY EVERY GATE CLAIM IS MADE TWICE
----------------------------------
The failure this file is most likely to have is testing one half of an
invariant: proving the gate lets something through and never proving it stops
anything, or the reverse. So each of the three claims above is measured on two
fixtures that differ in exactly one thing -- the presence of the companion
layer -- with the same entity class, the same start position and the same
number of frames. A gate that always stopped, or never did, fails one half.

THE `grounded is True` TRAP, MEASURED RATHER THAN ASSERTED AWAY
---------------------------------------------------------------
"The body landed" written the obvious way has NO teeth. `CollisionField.outside`
is BLOCK_ALL, so a body falling through a map with NO FLOOR PAINTED AT ALL
still stops -- at the world edge -- and still reports `grounded is True`. This
file therefore ships a fourth fixture whose companion layer is painted
explicitly OPEN everywhere, drives the identical body through it, and asserts
that it lands at a DIFFERENT pixel. That is what makes the resting-position
assertion an instrument rather than a coincidence: the calibration case is in
the file, next to the claim, and both are printed.

THE FIXTURES ARE THIS FILE'S OWN, ART INCLUDED
-----------------------------------------------
`data/maps/starter.tmx` is repainted whenever the demo changes and is never read here. It also
declares no collision at all, so it cannot exercise the gate in either
direction. Five maps are written into a temp directory together with the two
PNGs pytmx opens eagerly during the parse.

    .venv/Scripts/python.exe tools/check_collision_field.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import os
import shutil
import sys
import tempfile
import warnings

import pygame

pygame.init()
SCREEN = pygame.display.set_mode((128, 128))

import pytmx

from scripts.core import renderer as renderer_module
from scripts.core.collision_runtime import (BLOCK_ALL, EDGE_INSET, PASS_ALL,
                                            CollisionField, field_from_map)
from scripts.core.errors import PyoneerConfigError
from scripts.core.event_manager import PyoneerEvent
from scripts.core.event_types import GameEventType
from scripts.core.renderer import EntityLayer, LayerRenderer
from scripts.core.scene.game_scene import GameScene
from scripts.core.scene.scene_manager import SceneManager
from scripts.core.spawn import register
from scripts.game.entity.game_entity import GameEntity
from scripts.game.game_camera import GameCamera
from scripts.game.game_map import GameMap
from scripts.loaders.map_loader import as_document, has_tmx_document

failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


def expect_not(label, got, unwanted):
    """Assert a value is NOT something. The other half of an identity claim."""
    ok = got != unwanted
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got!r} "
          f"not={unwanted!r}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise, and the message must name each fragment.

    Asserting the TYPE alone passes for any raise anywhere inside the call,
    including a typo three frames down.
    """
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:50]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<62} raised {type(exc).__name__} "
              f"not {exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# The probes
# ---------------------------------------------------------------------------

class Probe(GameEntity):
    """A constructible, drawable GameEntity with an authored collision anchor.

    `GameEntity` leaves `core_lifecycle_build` and `core_input_receive`
    abstract, so it cannot be instantiated; and it has no image of its own, and
    the render path SKIPS an entity with no image, which would make a bound
    entity indistinguishable from an unbound one.

    `collision_offset` is a constructor keyword rather than the class default
    (0, 0) because (0, 0) is the sprite's TOP-LEFT -- a character's head -- and
    a body resting with its head on the floor line lands at a pixel that is
    also what several BROKEN configurations produce. Anchoring at the feet is
    what makes the resting position discriminating.
    """

    def __init__(self, collision_offset=(0.0, 0.0), **kwargs):
        super().__init__(**kwargs)
        self.collision_offset = tuple(float(v) for v in collision_offset)
        block = pygame.Surface((16, 16))
        block.fill((0, 200, 0))
        self._image = block

    def core_lifecycle_build(self, event=None):
        pass

    def core_input_receive(self, events=None):
        pass


def frame(delta: float) -> PyoneerEvent:
    return PyoneerEvent(GameEventType.UPDATE, data={"delta": delta})


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------
# 8x8 cells of 16px, so the world is 128x128 and every boundary in the file is
# an exact multiple of 16 that a resting position can be compared against
# without a tolerance.

W = H = 8
TILE = 16
ART_FIRST = 1
COLLISION_FIRST = 5            # the art tileset holds gids 1..4
BLOCKED = COLLISION_FIRST + BLOCK_ALL
OPEN = COLLISION_FIRST + PASS_ALL

#: The column and the row the WALLED fixture paints solid. Chosen at 3 so a
#: body starting in cell 1 crosses one open boundary before meeting a refusal
#: -- a gate that only ever tested the first boundary would still pass a test
#: that started adjacent to the wall.
WALL_COLUMN = 3
WALL_ROW = 3
WALL_EDGE = WALL_COLUMN * TILE          # 48: the pixel a walk must stop short of

#: The PLATFORM fixture's floor: every cell from this row down is solid.
FLOOR_ROW = 5
FLOOR_TOP = FLOOR_ROW * TILE            # 80
WORLD_BOTTOM = H * TILE                 # 128, where `outside` stops a fall

#: Feet, not head. See Probe.
FEET = (8.0, 15.0)

REST_ON_FLOOR = FLOOR_TOP - FEET[1] - EDGE_INSET        # 64.9990234375
REST_AT_WORLD_EDGE = WORLD_BOTTOM - FEET[1] - EDGE_INSET  # 112.9990234375

ART_TILESET = (' <tileset firstgid="%d" name="probe" tilewidth="16" '
               'tileheight="16" tilecount="4" columns="2">\n'
               '  <image source="probe.png" width="32" height="32"/>\n'
               ' </tileset>\n' % ART_FIRST)

COLLISION_TILESET = (' <tileset firstgid="%d" name="collision" tilewidth="16" '
                     'tileheight="16" tilecount="17" columns="17">\n'
                     '  <image source="collision.png" width="272" height="16"/>'
                     '\n </tileset>\n' % COLLISION_FIRST)

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" '
        'renderorder="right-down" width="%d" height="%d" tilewidth="%d" '
        'tileheight="%d" infinite="0" nextlayerid="9" nextobjectid="9">\n'
        % (W, H, TILE, TILE))


def csv(cell_gid) -> str:
    return ",\n".join(",".join(str(cell_gid(x, y)) for x in range(W))
                      for y in range(H))


def layer(identifier: int, name: str, cell_gid) -> str:
    return (' <layer id="%d" name="%s" width="%d" height="%d">\n'
            '  <data encoding="csv">\n%s\n</data>\n </layer>\n'
            % (identifier, name, W, H, csv(cell_gid)))


def walk_objects() -> str:
    """Two identical bodies, so one may be walked right and one walked down.

    Two rather than one repositioned between measurements: a check that moves
    its own probe back to the start is a check whose second measurement depends
    on `moveto` being correct.
    """
    return (' <objectgroup id="7" name="entity">\n'
            '  <object id="1" name="rightward" type="Probe" x="16" y="8" '
            'width="16" height="16"/>\n'
            '  <object id="2" name="downward" type="Probe" x="16" y="8" '
            'width="16" height="16"/>\n'
            ' </objectgroup>\n')


def body_objects() -> str:
    """One platformer body, composed entirely from the tmx object.

    Every number the fall depends on is authored here rather than inherited
    from the behavior's declared defaults, so retuning gravity in the registry
    cannot silently retune this check. The horizontal numbers are zeroed
    because the body carries no `player_input` and therefore has no intent to
    move sideways -- stating it makes the fall one-dimensional on purpose
    rather than by accident.
    """
    return (' <objectgroup id="7" name="entity">\n'
            '  <object id="1" name="body" type="Body" x="16" y="0" '
            'width="16" height="16">\n'
            '   <properties>\n'
            '    <property name="pyoneer_behaviors" value="platformer_move"/>\n'
            '    <property name="pyoneer_param_gravity" type="float" '
            'value="900"/>\n'
            '    <property name="pyoneer_param_max_fall_speed" type="float" '
            'value="600"/>\n'
            '    <property name="pyoneer_param_move_speed" type="float" '
            'value="0"/>\n'
            '    <property name="pyoneer_param_jump_velocity" type="float" '
            'value="0"/>\n'
            '    <property name="pyoneer_param_air_control" type="float" '
            'value="0"/>\n'
            '    <property name="pyoneer_param_coyote_ms" type="int" '
            'value="0"/>\n'
            '   </properties>\n'
            '  </object>\n'
            ' </objectgroup>\n')


def art_only(x, y):
    return ART_FIRST


def wall_mask(x, y):
    return BLOCKED if (x == WALL_COLUMN or y == WALL_ROW) else 0


def floor_mask(x, y):
    return BLOCKED if y >= FLOOR_ROW else 0


def all_open(x, y):
    return OPEN


#: name -> (declares collision?, companion painter, objects)
FIXTURES = {
    # A wall down column 3 and across row 3. Passability authored, movement
    # gated.
    "walled.tmx": (wall_mask, walk_objects()),
    # THE SAME MAP with the companion layer and the collision tileset deleted.
    # Nothing else differs, which is what makes the pair a measurement of the
    # gate rather than of two unrelated maps.
    "open.tmx": (None, walk_objects()),
    # A side-on world with a floor at row 5.
    "platform.tmx": (floor_mask, body_objects()),
    # The calibration case: a companion that says OPEN everywhere. There IS a
    # field and there is NO floor, so the body falls to the world edge and
    # still reports grounded.
    "nofloor.tmx": (all_open, body_objects()),
    # No companion at all: the ungated body.
    "ungated.tmx": (None, body_objects()),
}

workspace = tempfile.mkdtemp(prefix="pyoneer_collision_field_")


def write_fixture(name: str) -> str:
    painter, objects = FIXTURES[name]
    text = HEAD + ART_TILESET
    if painter is not None:
        text += COLLISION_TILESET
    text += layer(1, "Floor", art_only)
    if painter is not None:
        text += layer(2, "FloorCollision", painter)
    text += objects + "</map>\n"
    path = os.path.join(workspace, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def write_art() -> None:
    """The two PNGs pytmx opens during the parse.

    `collision.png` never draws anything -- a companion layer is not in
    MAP_DEPTH -- but the tileset that names the masks has to resolve or the
    parse fails, so the file has to exist and has to be the declared size.
    """
    sheet = pygame.Surface((32, 32))
    for index, color in enumerate(((180, 40, 40), (40, 180, 40),
                                   (40, 40, 180), (180, 180, 40))):
        sheet.fill(color, pygame.Rect((index % 2) * 16, (index // 2) * 16,
                                      16, 16))
    pygame.image.save(sheet, os.path.join(workspace, "probe.png"))
    masks = pygame.Surface((272, 16), pygame.SRCALPHA)
    pygame.image.save(masks, os.path.join(workspace, "collision.png"))


DEFAULTS = {
    "Probe": {"movement_config": {"move_speed": 100},
              "collision_offset": (0.0, 0.0)},
    "Body": {"movement_config": {"move_speed": 0},
             "collision_offset": FEET},
}


def build_renderer(path: str, *, pre_bound: GameEntity | None = None):
    """A fresh renderer with `path` bound. Returns (renderer, warnings).

    `pre_bound` is bound BEFORE the map, which is the ordering main.py does not
    use and a caller easily could: it is what proves the gate is not an
    accident of binding the map first.
    """
    renderer = LayerRenderer(SCREEN)
    renderer.bind_camera(GameCamera(pygame.Vector2(128, 128),
                                    pygame.Rect(0, 0, 128, 128), scale=1))
    renderer.spawn_defaults = DEFAULTS
    if pre_bound is not None:
        renderer.bind(41, pre_bound)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        renderer.bind("MAP", GameMap(pytmx.load_pygame(path)))
        return renderer, [str(item.message) for item in caught]


def value(thunk):
    """Call it; an exception becomes the value rather than the whole run.

    A wire that raises where it should answer is ONE broken claim, and the
    report is worth more than the traceback: without this, the first mutation
    that makes `field_from_map` raise takes every later assertion with it and
    the check reports one crash instead of the one thing that broke.
    """
    try:
        return thunk()
    except Exception as exc:  # noqa: BLE001 - reporting tool
        return "<raised %s: %s>" % (type(exc).__name__, exc)


class _MissingField:
    """Stands in for a field that was never baked. Nothing on it can match."""
    width = height = tile_width = tile_height = -1

    def mask_at(self, x, y):
        return "<no field>"


def field_of(renderer: LayerRenderer):
    field = renderer.collision_field
    return field if isinstance(field, CollisionField) else _MissingField()


class _MissingEntity:
    """Stands in for a body that never spawned.

    Every value is impossible to match, so a break in the spawn pass reports
    as the several false claims it is rather than hiding them behind the first
    AttributeError.
    """
    collision_field = "<did not spawn>"
    grounded = "<did not spawn>"
    behaviors = ()

    class transform:
        class position:
            x = y = -1.0

    @staticmethod
    def move_direction(*args, **kwargs):
        pass

    @staticmethod
    def core_frame_update(*args, **kwargs):
        pass


def spawned(renderer: LayerRenderer, object_id: int):
    for record in renderer.spawned_entities:
        if record.object_id == object_id:
            return record.entity
    return _MissingEntity


def run_frames(entity, count: int, delta: float = 0.2777):
    """Drive `count` frames; return (y, grounded) after each one.

    `grounded` is recorded per frame rather than read once at the end, because
    "it landed" is a claim about a TRANSITION: a body that was grounded on
    frame one never fell, and a body that is still not grounded on the last
    frame never landed. Reading only the final value proves neither.

    Calls `core_frame_update` directly rather than through a scene: the scene's
    fan-out is `tools/check_spawn_runtime.py`'s claim, and standing one up here
    would make a collision measurement depend on a camera and a display.
    """
    trail = []
    for _ in range(count):
        entity.core_frame_update(frame(delta))
        trail.append((entity.transform.position.y,
                      getattr(entity, "grounded", "<no such flag>")))
    return trail


try:
    write_art()
    register("Probe", Probe)
    register("Body", Probe)
    paths = {name: write_fixture(name) for name in FIXTURES}

    # ---------------------------------------------------------------- the bake
    print("binding a map bakes its passability, and only when it authors some")
    walled, _ = build_renderer(paths["walled.tmx"])
    open_map, open_warnings = build_renderer(paths["open.tmx"])

    expect("a map with a companion layer bakes a field",
           isinstance(walled.collision_field, CollisionField), True)
    expect("...sized in cells, from the map",
           (field_of(walled).width, field_of(walled).height), (W, H))
    expect("...and in pixels, from the map's tile size",
           (field_of(walled).tile_width, field_of(walled).tile_height),
           (TILE, TILE))
    expect("the painted wall is in it",
           field_of(walled).mask_at(WALL_COLUMN, 0), BLOCK_ALL)
    expect("and the cell beside it is not",
           field_of(walled).mask_at(WALL_COLUMN - 1, 0), PASS_ALL)
    # The other half. Without it, "bakes a field" would pass for a renderer
    # that baked an all-open field for every map ever bound, which is exactly
    # the outcome field_from_map returns None to avoid.
    expect("a map with NO companion layer bakes nothing at all",
           open_map.collision_field, None)
    # It must cost nothing AND say nothing. A wire that warned on every map
    # that authors no passability would be noise on every map in the repo,
    # and the two halves of "costs nothing" are the None above and this.
    expect("...and binding it warns about nothing whatsoever",
           open_warnings, [])

    # ------------------------------------------------------------- the hand-out
    print()
    print("every entity the renderer draws is handed that field, by one route")
    expect("a map-spawned body is gated by the map it spawned on",
           spawned(walled, 1).collision_field is walled.collision_field, True)
    expect("...and it is the field, not merely a field",
           spawned(walled, 1).collision_field is None, False)
    expect("a map-spawned body on an unauthored map is left ungated",
           spawned(open_map, 1).collision_field, None)

    # main.py's ordering: the map first, then the hand-built player.
    after = Probe(movement_config={"move_speed": 100})
    walled.bind(41, after)
    expect("a hand-bound body gets the SAME field object, not a copy",
           after.collision_field is walled.collision_field, True)
    expect("so hand-built and map-spawned are one path, not two",
           after.collision_field is spawned(walled, 1).collision_field, True)

    # The ordering main.py does not use. Without the sweep in __bind_map this
    # body stays ungated forever with no warning.
    before = Probe(movement_config={"move_speed": 100})
    expect("a body bound before any map starts ungated",
           before.collision_field, None)
    early, _ = build_renderer(paths["walled.tmx"], pre_bound=before)
    expect("...and binding the map gates it too",
           before.collision_field is early.collision_field, True)

    # A map that declares none must OVERWRITE, not be skipped: an entity
    # carrying a previous world's walls into a world with none is the failure
    # a "only assign when we have a field" gate would produce.
    open_map.bind(41, after)
    expect("re-binding into a map with no passability un-gates it again",
           after.collision_field, None)

    # One bake per map bind, not one per entity.
    calls = {"n": 0}
    real_field_from_map = renderer_module.field_from_map

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_field_from_map(*args, **kwargs)

    renderer_module.field_from_map = counting
    try:
        counted, _ = build_renderer(paths["walled.tmx"])
    finally:
        renderer_module.field_from_map = real_field_from_map
    expect("the map is read for masks exactly once per bind",
           calls["n"], 1)
    expect("...and both of its bodies were gated by that one read",
           [spawned(counted, i).collision_field is counted.collision_field
            for i in (1, 2)], [True, True])

    # --------------------------------------------------- main.py's actual route
    print()
    print("and through the call chain main.py really uses, not just the renderer")
    # prepare_test_scene(), in its own order: renderer, camera, map, then the
    # player it builds by hand. Everything above reaches LayerRenderer.bind
    # directly; this reaches it the way the game does, through SceneManager,
    # which is the only way to claim the shipped player is on the same path as
    # a map-placed one rather than merely on a path that looks like it.
    booted = LayerRenderer(SCREEN)
    booted.spawn_defaults = DEFAULTS
    manager = SceneManager(None)
    manager.add_scene("test", GameScene("test"))
    manager.set_scene("test")
    manager.bind("renderer", booted)
    manager.bind("camera", GameCamera(pygame.Vector2(128, 128),
                                      pygame.Rect(0, 0, 128, 128), scale=1))
    manager.bind("MAP", GameMap(pytmx.load_pygame(paths["walled.tmx"])))
    by_hand = Probe(movement_config={"move_speed": 100})
    manager.bind(41, by_hand)

    expect("the map's own bodies are gated when bound through SceneManager",
           spawned(booted, 1).collision_field is booted.collision_field, True)
    expect("...and so is the player main.py builds and binds by hand",
           by_hand.collision_field is booted.collision_field, True)
    expect("...and it is a real field, so both claims mean something",
           isinstance(by_hand.collision_field, CollisionField), True)
    expect("the hand-built body is gated identically to the map-placed one",
           by_hand.collision_field is spawned(booted, 1).collision_field, True)

    # ------------------------------------------------------- the gate, walking
    print()
    print("a body on a mask is stopped by it; the same body without one is not")
    # move_direction is what topdown_move calls, verbatim, with
    # move_speed * delta as the distance. 100 * 1.0 = 100 pixels asked
    # for, which crosses the wall and would leave the map if nothing refused.
    for label, renderer, want_right, want_down in (
            ("walled", walled, WALL_EDGE - EDGE_INSET, WALL_EDGE - EDGE_INSET),
            ("open", open_map, 16.0 + 100.0, 8.0 + 100.0)):
        rightward, downward = spawned(renderer, 1), spawned(renderer, 2)
        rightward.move_direction(1.0, "right")
        downward.move_direction(1.0, "down")
        expect(f"[{label}] walking right ends at",
               rightward.transform.position.x, want_right)
        expect(f"[{label}] walking down ends at",
               downward.transform.position.y, want_down)
        expect(f"[{label}] and the other axis never moved",
               (rightward.transform.position.y,
                downward.transform.position.x), (8.0, 16.0))

    # The refusal is a stop, not a freeze: the body that was just refused
    # rightward still travels its full distance back the way it came. Without
    # this, a gate that clamped every move on a gated entity to zero would
    # pass every assertion above.
    blocked = spawned(walled, 1)
    blocked.move_direction(0.1, "left")
    expect("the refused body still moves freely the other way",
           blocked.transform.position.x, WALL_EDGE - EDGE_INSET - 10.0)

    # --------------------------------------------------------- the falling body
    print()
    print("a platformer body on a floor lands, at the pixel the floor puts it")
    landed, _ = build_renderer(paths["platform.tmx"])
    body = spawned(landed, 1)
    expect("the body composed its behavior from the tmx object",
           [type(b).__name__ for b in body.behaviors],
           ["GamePlatformerMoveBehavior"])
    expect("and it is gated",
           body.collision_field is landed.collision_field, True)

    expect("the floor is where the fixture painted it",
           (field_of(landed).mask_at(1, FLOOR_ROW),
            field_of(landed).mask_at(1, FLOOR_ROW - 1)), (BLOCK_ALL, PASS_ALL))

    trail = run_frames(body, 300)
    # FOUR claims, because no one of them alone means "it landed". Falling
    # then resting kills gravity=0; not-grounded-then-grounded kills a body
    # that started on the floor; the exact resting pixel kills the ungated
    # fall, the head anchor and the empty companion -- see the calibration
    # section below, where three broken states report grounded is True.
    expect("it moved downward on the frames after it spawned",
           trail[0][0] > 0.0 and trail[3][0] > trail[0][0], True)
    expect("it was NOT grounded while it was falling", trail[1][1], False)
    expect("it comes to rest exactly on the floor line",
           body.transform.position.y, REST_ON_FLOOR)
    expect("and it IS grounded once it gets there", trail[-1][1], True)
    expect("and it stays there", run_frames(body, 60)[-1], (REST_ON_FLOOR, True))

    # Half one of the invariant: without a field it never lands.
    falling, _ = build_renderer(paths["ungated.tmx"])
    forever = spawned(falling, 1)
    expect("the ungated body was handed no field", forever.collision_field, None)
    run_frames(forever, 300)
    expect("it is still falling after 300 frames",
           getattr(forever, "grounded", "<no such flag>"), False)
    expect("...and is far below the world it was spawned in",
           forever.transform.position.y > WORLD_BOTTOM * 10, True)

    # ------------------------------------------------ calibrating the instrument
    print()
    print("`grounded` alone has no teeth -- here is the case that proves it")
    empty, _ = build_renderer(paths["nofloor.tmx"])
    nofloor = spawned(empty, 1)
    run_frames(nofloor, 300)
    expect("a map with NO FLOOR PAINTED still bakes a field",
           isinstance(empty.collision_field, CollisionField), True)
    expect("...whose cells are all open",
           field_of(empty).mask_at(1, FLOOR_ROW), PASS_ALL)
    expect("a body falling through it STILL reports grounded",
           getattr(nofloor, "grounded", "<no such flag>"), True)
    expect("because CollisionField.outside stopped it at the world edge",
           nofloor.transform.position.y, REST_AT_WORLD_EDGE)
    expect_not("which is NOT where the floor puts a body",
               REST_AT_WORLD_EDGE, REST_ON_FLOOR)

    # ---------------------------------------------------- a source with no .tmx
    print()
    print("a native map answers 'no passability' instead of a parse error")

    class NativeShaped:
        """The duck shape `config/managers/map_data.py` gives a .blitmap map.

        It carries a `filename` -- deliberately, so the rest of the engine can
        read it the way it reads pytmx -- and that filename names a binary file
        `MapDocument` cannot parse. Binding one must not raise from a wire that
        is looking for optional passability.
        """
        layers = ()
        filename = os.path.join(workspace, "native.blitmap")

        def object_records(self, layers=None):
            return []

    native = NativeShaped()
    expect("has_tmx_document says a native map has none",
           has_tmx_document(native), False)
    expect("...and says a parsed .tmx does",
           has_tmx_document(pytmx.load_pygame(paths["walled.tmx"])), True)
    expect("field_from_map answers None for it, and does not raise",
           value(lambda: field_from_map(native)), None)

    # The other half: the SAME object without the duck method takes the normal
    # path and fails loudly. Without this, the None above would also be
    # produced by a field_from_map that had stopped reading maps at all.
    class NotNative(NativeShaped):
        object_records = None

    expect_raises("a source with a filename it cannot parse still raises",
                  Exception, lambda: field_from_map(NotNative()),
                  "native.blitmap")
    expect_raises("and a source with no filename at all still raises",
                  PyoneerConfigError, lambda: as_document(object()),
                  "no .filename")

    # ------------------------------------------------------------ one hand-out
    print()
    print("the field is handed out from exactly one place in the renderer")
    source = open(renderer_module.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_function(node):
        while node is not None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
            node = parents.get(node)
        return "<module>"

    to_self: list[str] = []
    to_other: list[str] = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if (isinstance(target, ast.Attribute)
                    and target.attr == "collision_field"):
                where = enclosing_function(node)
                owner = getattr(target.value, "id", None)
                (to_self if owner == "self" else to_other).append(where)

    expect("only __gate assigns the field ONTO an entity",
           sorted(set(to_other)), ["__gate"])
    expect("...and it does it once, not once per branch", len(to_other), 1)
    expect("the renderer's own field is set where the map is read",
           sorted(set(to_self)), ["__bind_map", "__init__"])
    # No second reader: the renderer must not re-derive what field_from_map
    # already answers. Asserting the call site alone would pass for a renderer
    # that called it AND baked its own field beside it.
    for banned in ("CollisionField.bake", "collision_layers(",
                   "companion_pairs(", "gid_to_opinion("):
        expect(f"the renderer does not re-implement {banned}",
               banned in source, False)

    # And EVERY entity actually in a layer got one, so the sweep cannot be
    # passing only because the probes happen to be the ones asked. `early` is
    # used because nothing rebinds its entities afterwards: it holds the body
    # bound BEFORE the map as well as the two the map placed.
    in_layers = [entity
                 for layers in early.layers.values()
                 for layer_ in layers if isinstance(layer_, EntityLayer)
                 for entity in layer_.entities]
    expect("it reaches every entity in the renderer, not only the probed ones",
           (len(in_layers),
            all(e.collision_field is early.collision_field
                for e in in_layers)), (3, True))

finally:
    pygame.quit()
    shutil.rmtree(workspace, ignore_errors=True)

print()
if failures:
    print(f"FAILED {len(failures)}:")
    for item in failures:
        print("  -", item)
    sys.exit(1)
print("collision field OK")
