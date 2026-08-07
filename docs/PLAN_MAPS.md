All probes run and deleted. Draft verified against live code; 23 defects found. Corrected plan below.

---

# Pyoneer — Map Object Layer Plan (corrected)

**Verification base:** `SDL_VIDEODRIVER=dummy .venv/Scripts/python.exe tools/smoke.py --frames 60` runs clean today. Current baseline: `frame_hash=bec3f3153713a6b2`, `blit_tokens=69`, `renderer_layer_depths=[10,30,40,41,50,60,100]`, `entity_layer_counts={"40":5,"41":1}`, `ui_component_total=113`. Every number below was measured, not estimated.

---

## PART 0 — ARCHAEOLOGY (corrected)

### 0.1 `data/maps/test.tmx` — structure

133,940 bytes, CRLF throughout, orthogonal 100×100 @ 16px, `nextlayerid="10" nextobjectid="1"`. Indentation is internally inconsistent: **tabs** on lines 2–13 (`<editorsettings>` … first `<data>`), **single spaces** from line 117 (`<layer id="1" name="Floor">`) onward. No canonical pretty-printer reproduces this; only whitespace-preserving parsing does.

| Name | class | line | contents |
|---|---|---|---|
| `Graphic` | `TiledGroupLayer` | 12 | `<group>` wrapper |
| `Entity` | `TiledGroupLayer` | 638 | `<group>` wrapper — **not** an object group |
| `entity` | `TiledObjectGroup` id=9 | 639 | `<objectgroup id="9" name="entity"/>` — **self-closing, 0 objects, `properties == {}`** |

The preliminary is the **seam, not data**. The owner authored the container and never filled it. Nothing was lost.

> **Correction to draft:** `pytmx.TiledGroupLayer` **does not exist**. Verified: `AttributeError: module 'pytmx' has no attribute 'TiledGroupLayer'`. The class lives at `pytmx.pytmx.TiledGroupLayer`. Any `isinstance(x, pytmx.TiledGroupLayer)` in this plan's code would crash at runtime. Import it explicitly as `from pytmx.pytmx import TiledGroupLayer`.

### 0.2 Tile-layer population — confirmed by execution

| Layer | nonzero gids | in `MAP_DEPTH`? | renders? |
|---|---|---|---|
| `Paralax` | **39** | ✗ (code spells it `Parallax`) | **NO — 39 tiles silently lost** |
| `Floor` | 10000 | ✓ (10) | yes |
| `GroundClutter` | 37 | ✓ (30) | yes |
| `PlayerDepth` | 203 | ✓ (50) | yes |
| `Above1` | **0** | ✗ | NO — and genuinely empty |
| `Foreground` | 57 | ✓ (60) | yes |

The loop at `scripts/core/renderer.py:213` iterates `MAP_DEPTH.items()` — the code's imagination — not `tmx_data.layers` — the author's file. Result: exactly **7** `Layer not found in map:` lines per boot (`renderer.py:230`) for `Parallax, ENTITY_1, ENTITY_2, ENTITY_3, FOREGROUND_1, FOREGROUND_2, UI_LAYER_1`, while the two real dropped layers produce silence. The loop is inside out.

> **Correction to draft:** all `renderer.py` line citations in the draft are stale by ~14 lines. Correct anchors: loop `renderer.py:213`; surface allocation `renderer.py:220`; `TiledObjectGroup`/`TiledImageLayer` `pass` branches `renderer.py:225-228`; `Layer not found` print `renderer.py:230`; `__prepare_entity_layers` (empty) `renderer.py:237`; `entity.depth + self.layer_depth` `renderer.py:112`.

### 0.3 Depth registries — three exist, one live

- **live:** `scripts/core/depth.py` — `MAP_DEPTH`, `OBJECT_DEPTH`, `OBJECT_CONVERTER`, `DEPTH = MAP_DEPTH | OBJECT_DEPTH | OBJECT_CONVERTER`.
- **dead #1:** `config/maps.json` → `layers` block. Read by nothing. **Not a verbatim duplicate** as the draft claimed — it holds `"Parallax": 0` where `depth.py` holds `1`. It is a *divergent* stale copy, which is worse.
- **dead #2:** `config/depth.json` + `config/managers/depth_data.py`. Never imported, never constructed, absent from `CoreAssetManager.__init__`. And broken if wired: `Depth.__init__(self, config: tuple[str,int])` does `config[0]`/`config[1]` while `load_depths` passes each *value* from the json, which is a **list of dicts** — for key `"ui"` (1-element list) `config[1]` raises `IndexError`; for `"entity"` (2-element list) `self.depth` silently becomes `{"name":"player","depth":40}`.

`OBJECT_CONVERTER` in `depth.py` already maps `"GamePlayer" → 50`, `"GameEntity" → 50`, `"GameFloorEntity" → 20`, etc. **That is the class→depth resolver the object layer needs. It already exists.**

### 0.4 Entity config — the spawn path is already broken

`CoreAssetManager.entity: EntityAssetManager` is constructed at `config/managers/core_asset_manager.py:80` and **read by nothing**. `grep` for `assets.entity` outside the manager returns only `load_assets`/`unload_assets`, both `pass`.

`main.py:110` and `main.py:116` bypass it with `self.assets.config.get('entity').get('default')` — the raw dict `{'animations': {...}, 'movement': {'move_speed': 20, 'sprint_mult': 2}}`. `GameEntity.__init__` (`scripts/game/entity/game_entity.py:53`) then tests `'move_speed' in movement_config.keys()`, which is **False** because `move_speed` is nested under `movement`. Measured live: `g.player.move_speed == 16`, not the configured `20`.

> **Correction to draft:** the draft claims fixing this changes `frame_hash`. It does not. `tools/smoke.py` injects no input; measured, the player's position after 60 frames is `(200.0, 200.0)` — identical to frame 0. All five decoy players carry `state.can_move = False`. `move_speed` is multiplied by nothing in a headless run. **Fixing `move_speed` produces zero `frame_hash` drift.** It must be verified by direct assertion.

### 0.5 `scripts/loaders/` is empty scaffolding

`scripts/loaders/__init__.py` and `scripts/loaders/map_loader.py` are both **0 bytes**. Map loading is split three ways with no owner: file I/O in `config/managers/map_data.py:43` (`pytmx.load_pygame`), rasterization in `renderer.py:213-230`, and `GameMap` (`scripts/game/game_map.py`) which builds a `depth_map` that nothing reads.

`AssetMapManager.load_assets(name, reload=False)` (`config/managers/map_data.py:28-43`) is **already** the correct cache-once/reload-on-request API, and `tools/check_singletons.py` proves it holds: *"50 cached load_assets calls took 0.03 ms"*, *"reload=True returns a NEW parse"*.

**New defect (blocks any CLI tool):** `MapData.file` is the raw relative string `"data/maps/test.tmx"` from `config/maps.json`. `ConfigManager.CONFIG_DIR` resolves from `__file__`, but the map path does not. Proven: loading `CoreAssetManager().maps.load_assets('test')` from any cwd other than the repo root raises `FileNotFoundError: 'data/maps/test.tmx'`.

### 0.6 `ComponentFactory` — right seam, four defects

`scripts/core/ui/widget/factory/component_factory.py` is a correct name→constructor registry backed by module-global `COMPONENT_POOL`. Wired to nothing (`main.py:23,53-54` commented out). Defects:
1. `from pyclbr import Class` (line 1) — dead import.
2. `callable` parameter shadows the builtin.
3. `get(name)` raises bare `KeyError`. **There is no `get_or_none`** — the draft's Phase 4.3 calls one that does not exist.
4. `scripts/core/ui/widget/factory/` has **no `__init__.py`**. It works today as an implicit namespace package (`tools/check_imports.py` PASSes, 48 modules, 0 duplicates), so this is cosmetic consistency, not a blocker.

### 0.7 The writer — proven, with two corrections

`pytmx` exports no `save`/`write`/`dump`/`serialize`. `TiledMap` has only `parse_xml`/`from_xml_string`.

**pytmx cannot be the writer's document model** — all three claims verified by execution:
- `TiledGroupLayer` public attrs are exactly `['allow_duplicate_names','from_xml_string','id','name','parent','parse_xml','properties','visible']`. **No `.layers`.** `tm.layers` is flat; every layer's `.parent` is `TiledMap`. `Graphic`/`Entity` group membership is unrecoverable — writing from pytmx flattens the map on first save.
- pytmx invents attributes: parsing `<objectgroup id="2" name="spawns" tintcolor="#ff8800" opacity="0.75" offsetx="8" offsety="-4">` yields `draworder='index'` and `color=None` that were never authored.
- pytmx mutates geometry: `<object id="2"><polygon points="0,0 16,0 16,16"/></object>` with no `width`/`height` returns `w=16.0 h=16.0` (computed bbox).

**`xml.etree` round-trips byte-exactly. Executed, `True`, 133940 == 133940:**

```python
def dump(root) -> bytes:
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    body = re.sub(r"\s+/>", "/>", body)
    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
    return out.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
```

Exactly three fixups: CRLF, `<x/>` self-closing spacing, XML declaration quote style. Attribute order survives (insertion-ordered dict since 3.8), verified against `<map>`'s 12 attributes.

> **Correction — the regex is safe, but for a reason the draft did not state.** I attacked `re.sub(r"\s+/>", "/>")` expecting it to corrupt attribute values containing `/>`. It cannot: `ET.tostring` escapes `>` as `&gt;` in **both** attribute values and text content (verified: `value="go up /&gt;then right"`). The fixup can only match a real element terminator. It is nonetheless fragile against Tiled builds that emit `<x />` *with* a space, so it must be **derived from `source_bytes` at load**, not hardcoded.

> **Known limitation to assert, not discover later:** `ET.parse` drops XML comments and processing instructions. Tiled 1.3.1 writes neither, but the round-trip test must fail loudly on a file that contains them rather than silently deleting them.

**A real edit round-trips through pytmx.** Executed: inserting an `<object>` into the empty `<objectgroup id="9" name="entity"/>` with explicit `.text`/`.tail` indentation produced Tiled-native 1-space-per-level output; `pytmx.TiledMap` reload returned `id=1 name='hero_start' type='GamePlayer' (320.0,320.0) 44.0×64.0 props={'entity':'player','depth':50}` with `depth` cast to a real `int`, and `len(tm.layers) == 9` unchanged. **Removing the object restored the source bytes exactly.** The add/remove identity holds.

**Anchor correction — critical, and the draft has it backwards.** The draft says the resolver must normalize Tiled's bottom-anchored tile-object `y`. Verified: an object authored `gid="1" y="48" height="16"` comes back from pytmx as `y=32.0`. **pytmx already normalizes bottom→top-left.** A resolver consuming pytmx objects that re-normalizes will double-shift every tile object by one tile. Normalization belongs in the **`MapDocument` (raw XML) path only**, never the pytmx path.

---

## PART 1 — SEQUENCED PLAN

Ordering principle: a headless programmatic edit + reload must work before any GUI exists. Phases 1–4 deliver that; Phase 5 makes it drivable. Each phase ships alone.

Supersedes `docs/IMPROVEMENT_PLAN.md` 11.a / 11.c / 11.d. Depends on nothing from Segments 5–8.

---

### Phase 1 — Make the depth table honest *(tiny, ships alone)*

**1.1 — `scripts/core/depth.py`.**
```python
MAP_LAYER_ALIAS = {"Paralax": "Parallax"}   # authored typo in data/maps/test.tmx
MAP_DEPTH["Above1"] = 55                    # between PlayerDepth(50) and Foreground(60)

def resolve_map_layer(name: str) -> str:      # alias -> canonical
def resolve_depth(name: str) -> int | None:   # returns None, never raises
```
Alias table, not a rename, on both sides: renaming the **map** forces a 134 KB rewrite *before* the writer that guarantees round-trip safety exists (wrong order); renaming the **code** enshrines a typo in the engine's public depth vocabulary. The alias table is also the exact mechanism the object layer needs for Tiled-class → engine-class, so it is not a one-off.

**1.2 — `renderer.py`: invert `__prepare_map_layers` (currently `renderer.py:213`).** Iterate `tmx_data.layers`, not `MAP_DEPTH.items()`. Per layer: `resolve_map_layer` → `resolve_depth` → if `None`, log once naming the *layer* and the nearest `MAP_DEPTH` keys. Turns 7 spurious lines into 0 and 2 silent drops into 2 loud ones.

**1.3 — Skip baking empty layers.** *(new step, not in the draft)* `MapLayer.core_prepare` counts blitted tiles; if zero, the layer is dropped and emits no token. Rationale: a bare `Above1` entry allocates a 1600×1600 SRCALPHA surface — **10.24 MB, measured** — and pays a full-viewport alpha blit every frame to deliver **zero** pixels. Without this skip, Phase 1 raises map-surface memory from 40.96 MB (4 layers) to 61.44 MB (6 layers) for 39 new pixels. That is exactly the bloat the owner asked to cut.

> **Correction to draft's memory figures:** per-layer is **10.24 MB**, not 40.96 MB. 40.96 MB is the *total* across the 4 currently-baked layers. `docs/IMPROVEMENT_PLAN.md:418` carries the same mislabel. The `163.8 MB` figure for 200×200@32px *is* correct per-layer.

**1.4 — Delete the two dead depth registries.** Remove the `layers` block from `config/maps.json`; delete `config/depth.json` and `config/managers/depth_data.py`. Deletion is safe: `ConfigManager.__load_configurations` globs every `*.json` in `config/`, and `config.get('depth')` has no callers. Do **not** repair `DepthAssetManager` — `scripts/core/depth.py` is live and a fourth parallel registry is the same disease as the four listener registries.

**Verify.**
```
.venv/Scripts/python.exe tools/smoke.py --frames 60
```
- `renderer_layer_depths`: `[10,30,40,41,50,60,100]` → **`[1,10,30,40,41,50,60,100]`** (adds `Parallax`@1; `Above1` is empty and correctly skipped by 1.3).
- `blit_tokens`: **69 → 70**. *(Measured: 69→71 without the 1.3 empty-skip, 70 with it.)*
- `frame_hash` **changes** — `Paralax`'s 39 tiles now draw. This is the **only** intentional hash change in this plan. Re-baseline with `--write-baseline` and cite it in the commit.
- `stdout` contains **zero** `Layer not found in map:` lines.
- New `tools/check_map_layers.py`: assert every `TiledTileLayer` in `test.tmx` resolves to a depth; assert `Above1` resolves to 55 *and* bakes no surface.

> **Corrections to the draft's Phase 1 verify:** the draft's before/after depth lists (`[10,30,50,60]` → `[1,10,30,50,55,60]`) omit the entity layers 40/41 and the UI layer 100 that `smoke.py` actually reports. A worker following them would see a false failure on their first run.

---

### Phase 2 — `MapDocument`: ET-backed, round-trip-safe

New file **`scripts/loaders/map_document.py`**. **Uses no pytmx** (§0.7).

```
MapDocument
  .path, .tree: ET.ElementTree, .root: ET.Element, .source_bytes: bytes
  .line_ending: bytes            # detected from source_bytes, not hardcoded
  .self_close_style: str         # '/>' or ' />', detected from source_bytes

  .layer_names() -> list[str]              # walks <group> recursively, document order
  .group_path(layer) -> tuple[str, ...]    # ('Graphic',) / ('Entity',) -- what pytmx loses
  .tile_layer(name)   -> TileLayerHandle
  .object_layer(name) -> ObjectLayerHandle
  .tilesets() -> list[TilesetRef]
  .allocate_object_id() -> int             # reads + bumps <map nextobjectid>
  .to_bytes() -> bytes

TileLayerHandle:   .get(x,y) -> int   .set(x,y,gid)
ObjectLayerHandle: .objects()  .add(cls,x,y,w=0,h=0,name=None,properties=None)
                   .remove(id) .move(id,x,y) .set_property(id,key,value)
```

**2.1 — Byte-exact serializer.** Exactly the verified `dump()` from §0.7, with line-ending and self-close style read from `source_bytes` at load so an LF-authored or space-self-closing map stays that way.

**2.2 — Indentation inference.** `_indent_for(parent) -> (open_text, child_tail, close_tail)`: read the parent's `.text` and last child's `.tail`; when the parent is empty (`<objectgroup id="9" name="entity"/>`), derive from the grandparent's unit × depth. Verified working — the inserted `<object>` landed at 3 spaces, `<properties>` at 4, `<property>` at 5, matching Tiled 1.3.1. Default `" "` when ambiguous.

**2.3 — Self-closing transitions.** Empty→populated and populated→empty are native ET behaviour with `short_empty_elements=True` plus the fixup. No special casing; needs a test.

**2.4 — Surgical CSV edit.** `TileLayerHandle.set` must not reflow the ~20 KB `<data>` text. Parse once into `rows: list[list[str]]`, cache on the handle, mutate one cell, re-join preserving the per-row trailing comma (present on all rows but the last) and the leading newline. Assert `set(x,y,get(x,y))` is a byte no-op.

**2.5 — Property type inference.** `bool`→`type="bool"` `value="true"|"false"`; `int`→`type="int"`; `float`→`type="float"`; `str`→ omit `type`. This is what makes pytmx return a real `int` on reload (verified: `{'depth': 50}`, not `'50'`).

**2.6 — `scripts/loaders/map_loader.py` gets content.**
```python
class MapLoader:
    @staticmethod
    def load(name_or_path) -> MapDocument       # resolves relative paths against REPO_ROOT
    @staticmethod
    def save(doc, path=None) -> None            # atomic: temp file + os.replace
    @staticmethod
    def render_map(name, reload=False) -> pytmx.TiledMap:
        return CoreAssetManager().maps.load_assets(name, reload=reload)
```

> **Correction to draft:** the draft's `load_render(doc)` called `pytmx.load_pygame(doc.path)` directly. That **bypasses `AssetMapManager`'s cache** and re-parses 134 KB plus every tileset surface on each call — a direct contradiction of the owner's *"TMX cache built once unless reload requested"*. Route through `CoreAssetManager().maps.load_assets(name, reload=...)`, which already implements exactly that contract and is covered by `tools/check_singletons.py`.

**2.7 — Fix cwd-relative map paths.** *(new step)* Resolve `MapData.file` against the repo root inside `AssetMapManager.prepare` (mirroring `ConfigManager.CONFIG_DIR`). Without this, every tool in Phase 5 fails from any directory but the repo root — **proven** `FileNotFoundError`.

pytmx keeps exactly one role: the **rasterizer's** reader, because it resolves GIDs to `pygame.Surface` and ET cannot. `MapDocument` is the **author's** model. Two readers, one writer, one file — and the writer is never pytmx.

**Verify.** New `tools/check_tmx_roundtrip.py`:
- `MapLoader.load(test.tmx).to_bytes() == open(test.tmx,'rb').read()` — **proven True, 133940 bytes.**
- `set_tile(x,y,get_tile(x,y))` → `to_bytes()` unchanged.
- `set_tile(50,50,1)` → save → reload → exactly one gid differs.
- add object → save → pytmx reload → object present, `len(tm.layers) == 9`, groups id 7/8 intact — **proven.**
- remove that object → `to_bytes() == source_bytes` — **proven.**
- a fixture containing an XML comment fails loudly (documents the ET limitation).
- runs correctly from a foreign cwd (guards 2.7).

`tools/smoke.py`: **zero drift.** Nothing in the render path changed. If Phase 2 moves `frame_hash`, the writer touched the render path and is wrong.

---

### Phase 3 — Entity config repair *(prereq for spawning anything)*

**3.1 — Route through `EntityAssetManager`.** Replace `main.py:110,116` `self.assets.config.get('entity').get('default')` with `self.assets.entity.get('default')` → `DataEntity`. `GameEntity.__init__` (`game_entity.py:53-54`) then takes a `DataEntityMovement` and reads `.move_speed`/`.sprint_mult` as attributes. Accept both shapes for one release (`getattr(cfg,'move_speed',None)` first, dict fallback) so `main.py` and any caller can migrate independently. `GameAnimatedEntity` takes `DataEntitySpriteInfo.body` as the animation-category key instead of `main.py` hand-passing `assets.animations.get('entity')`.

**3.2 — Extend `config/entity.json` with spawn data — but *not* depth.**
```json
"player": {
  "animations": {"body": "entity"},
  "movement":   {"move_speed": 20, "sprint_mult": 2},
  "spawn":      {"class": "GamePlayer", "priority": 0,
                 "initial_animation": "idle_down", "controllable": true}
}
```
`DataEntity` gains `.spawn: DataEntitySpawn`.

> **Correction to draft:** the draft put `"depth": "PlayerDepth"` in this block. That creates a **fifth** depth registry two steps after Phase 1.4 deletes two of them — self-contradictory. `scripts/core/depth.py:OBJECT_CONVERTER` **already** maps `"GamePlayer" → 50`, `"GameEntity" → 50`, `"GameFloorEntity" → 20`, `"GameBackgroundEntity" → 5`, `"GameForegroundEntity" → 80`, `"GameUIEntity" → 100`. Depth resolves from the **class name** through the one live table. The only depth override permitted is a per-object `depth` property in the `.tmx`, resolved by name through `resolve_depth`.

**Verify.** New `tools/check_entity_config.py`:
- `CoreAssetManager().entity.get('default').movement.move_speed == 20`
- `MainGame(autostart=False).player.move_speed == 20` — currently **16**, measured.
- `tools/smoke.py`: **`frame_hash` unchanged**, `entity_layer_counts` unchanged `{"40":5,"41":1}`.

> **Correction to draft:** the draft asserted `frame_hash` *changes* here "because the player moves at 20 instead of 16." Measured: `smoke.py` injects no input, the five decoy players have `can_move=False`, and the real player's position is `(200.0, 200.0)` at both frame 0 and frame 60. `move_speed` is multiplied by a delta that never fires. A worker following the draft would re-baseline a hash that never moved, or chase a phantom regression. Verify by assertion, not by hash.

---

### Phase 4 — Object layer → entity activation

**4.1 — Object schema (the contract with Tiled).**
```xml
<object id="1" name="hero_start" type="GamePlayer" x="320" y="320" width="44" height="64">
 <properties>
  <property name="entity" value="player"/>
  <property name="depth" value="PlayerDepth"/>
 </properties>
</object>
```
- `type=` (Tiled ≤1.8) **or** `class=` (Tiled ≥1.9) is the **factory key**. Verified: a `class="GamePlayer"` object returns `o.type is None` and `getattr(o,'class') == 'GamePlayer'` — `class` is a Python keyword, reachable only via `getattr`. Resolve as `getattr(obj,'class',None) or obj.type`.
- `entity` property is the **archetype key** into `config/entity.json`.
- `depth` property is an optional override, by name, resolved through `scripts/core/depth.py`. Absent → `OBJECT_CONVERTER[cls_name]`.
- **Do not re-normalize the anchor.** pytmx already converts Tiled's bottom-anchored tile-object `y` to top-left (verified: authored `y="48" height="16"` → `y=32.0`). Rectangle objects are already top-left. Add a regression test asserting a `gid`-bearing object lands one tile *up* from its authored `y`, so a future "fix" cannot reintroduce the double shift.

**4.2 — `scripts/core/factory/object_factory.py`.** Promote `ComponentFactory` out of the widget tree. Same class shape, namespaced keys, matching the owner's relational-autocomplete request:

```
COMPONENT_POOL: dict[str, ComponentNode]      # "namespace.Name"
  entity.GamePlayer   entity.GameEntity
  widget.GameWindow   widget.Panel     widget.Button      widget.Checkbox
  widget.TextBox      widget.ImageComponent  widget.TextComponent  widget.ShapeComponent
```
Tiled `type="GamePlayer"` → `factory.make("entity.GamePlayer", …)`; an unprefixed lookup falls back to a scan with an unambiguity check so hand-authored `.tmx` stays terse. **Add `get_or_none(name) -> ComponentNode | None`** — it does not exist today and Phase 4.3 requires it; `get` raises a bare `KeyError`. Rename `callable` → `constructor`; drop `from pyclbr import Class`; add `scripts/core/ui/widget/factory/__init__.py` (cosmetic — `tools/check_imports.py` currently PASSes without it).

**4.3 — `scripts/loaders/object_resolver.py`.**
```python
class ObjectResolver:
    def __init__(self, factory: ObjectFactory | None = None):
        self.assets = CoreAssetManager()          # singleton, per owner's preference
        self.factory = factory or ObjectFactory()
    def resolve(self, tiled_object) -> ResolvedSpawn | None
    def spawn_all(self, tmx) -> list[tuple[int, PyoneerGameObject]]
```
Per object, in order:
1. `cls_name = getattr(obj,'class',None) or obj.type` — skip with a warning if absent.
2. `node = factory.get_or_none(f"entity.{cls_name}")` — skip with a warning if unregistered. **Never raise**: one bad object in a 500-object map must not brick the boot.
3. `archetype = self.assets.entity.get(obj.properties.get('entity','default'))`.
4. `depth = resolve_depth(obj.properties.get('depth')) or OBJECT_CONVERTER.get(cls_name, OBJECT_DEPTH["ENTITY"])`.
5. `anim = self.assets.animations.get(archetype.sprite_info.body)`.
6. `inst = node.call(movement_config=archetype.movement, animation_config=anim, …)`.
7. `inst.moveto((obj.x, obj.y))` — **no anchor arithmetic** (§4.1). `inst.depth` stays `0`; `EntityLayer.core_blits` at `renderer.py:112` does `entity.depth + self.layer_depth`, so a nonzero entity depth double-counts.
8. **Return** `(depth, inst)` to the caller. **Do not call `renderer.bind`.**

> **Correction to draft — internal contradiction.** Draft §4.3 step 8 says `renderer.bind(depth, inst)`; draft §4.4 then says *"The resolver must return spawns to the caller … not call `renderer.bind` directly."* Both cannot hold. The §4.4 reasoning is right and the §4.3 code is wrong: `SceneManager.bind` (`scene_manager.py:36-42`) binds to **both** `current_scene` and `renderer`. Binding only to the renderer produces an object that draws but never receives `core_update` — the same defect class as "child `core_*` overrides are never called."

**4.4 — `GameSceneMap` earns its body.** `scripts/core/scene/game_scene_map.py:12-17` is a `pass` under a 4-line comment listing exactly this pipeline. Implement `core_build`:
```
tmx    = MapLoader.render_map("test")
game_map = GameMap(tmx)
self.bind("MAP", game_map)               # via SceneManager -> scene + renderer
for depth, obj in ObjectResolver().spawn_all(tmx):
    self.bind(depth, obj)
    obj.core_pre_prepare(...); obj.core_prepare(...); obj.core_post_prepare(...)
```
**The explicit lifecycle calls are mandatory, not defensive.** `MainGame.__init__` runs `prepare()` → `prepare_test_scene()` (which fires `core_pre_prepare`/`core_prepare`/`core_post_prepare` on everything bound so far) → `build()` → `core_build` → `begin()` → `GameScene.begin()`, which re-fires `core_prepare` only, because `flags["active"]` is still False. Objects created inside `core_build` therefore receive `core_prepare` **twice** by accident and `core_pre_prepare`/`core_post_prepare` **never**. Driving the lifecycle explicitly at bind time makes it deterministic instead of dependent on that accident. `main.py:83-96` (`prepare_test_scene`) then shrinks to scene selection.

**4.5 — Renderer object branch: log and skip, do not spawn.** In the inverted loop from 1.2, replace the `pass` at `renderer.py:225-228` with a one-line debug log naming the object group and its object count.

> **Correction to draft — step deleted.** Draft §4.4 proposed a `LayerRenderer.__prepare_object_layer` that delegates to `ObjectResolver`. `LayerRenderer.__init__(surface)` holds no `CoreAssetManager` and no factory, and the draft's own ordering note says the renderer must not spawn. Spawning is `GameSceneMap`'s job (4.4). The renderer's only correct behaviour on an object group is to not silently ignore it.

**Verify.** Seed 3 objects into `test.tmx`'s `entity` layer **using Phase 2's writer** (`tools/seed_test_objects.py`) — the first real proof the writer is trusted. Then:
- `git diff data/maps/test.tmx` shows **only** the new `<object>` elements and the `nextobjectid` bump. If one CSV byte moved, Phase 2 is not done.
- `tools/smoke.py --frames 60`: `entity_layer_counts` grows by exactly 3; `blit_tokens` grows by ≤3 (frustum culling at `renderer.py:105-116`); `renderer_layer_depths` gains the resolved band if new.
- `tools/check_object_spawn.py`: assert each instance's class, position (**equal to the authored `x`/`y` for rect objects; one tile above the authored `y` for `gid` objects**), depth band, `inst.depth == 0`, and that the config source was `assets.entity`, not the raw dict.

---

### Phase 5 — Headless command API *(minimum viable, no GUI)*

**5.1 — `scripts/loaders/map_commands.py`.** Invertible dataclasses with `apply(doc)` and `invert(doc) -> Command`. **Five commands, matching what Phases 1–4 actually exercise:**
```
SetTile(layer,x,y,gid)                     <-> SetTile(layer,x,y,old_gid)
AddObject(layer,cls,x,y,w,h,props)         <-> RemoveObject(layer,id)
RemoveObject(layer,id)                     <-> AddObject(... captured ...)
MoveObject(layer,id,x,y)                   <-> MoveObject(layer,id,old_x,old_y)
SetObjectProperty(layer,id,key,value)      <-> SetObjectProperty(... old ...)
```

**5.2 — `MapSession`.** Owns a `MapDocument`, an undo stack and a redo stack. `execute(cmd)` / `undo()` / `redo()` / `save()`. Undo comes free from invertibility; nothing else is needed for it.

**5.3 — `tools/mapctl.py`.** JSON in, JSON out:
```bash
.venv/Scripts/python.exe tools/mapctl.py describe data/maps/test.tmx
.venv/Scripts/python.exe tools/mapctl.py apply   data/maps/test.tmx --commands edits.json
.venv/Scripts/python.exe tools/mapctl.py diff    data/maps/test.tmx --commands edits.json
```
`describe` emits the layer tree **with `<group>` membership** (which pytmx structurally cannot provide), tileset firstgid ranges, object inventory, and each layer's resolved depth including alias hits and unmapped layers. `diff` applies to a copy and prints a unified diff without writing — the safety valve for agent-driven edits.

**5.4 — Reload as a method, not a new event type.** `MapSession.save()` calls `GameSceneMap.reload_map()`, which calls `MapLoader.render_map(name, reload=True)` and re-bakes.

> **Correction to draft:** the draft fired a new `GameEventType.MAP_RELOAD`. `GameEventType` is a tuple-`Enum` whose `PyoneerEvent.__translate` does a **linear scan per event** — a named, in-flight defect in another worker's scope. Adding a member makes every event in the engine marginally slower to serve one caller, and lands a new member into a file being rewritten. A direct method call has no such coupling and can be promoted to an event once Segments 5–8 land.

**Verify.** `tools/check_map_commands.py`: a random 200-command sequence, `execute×200 → undo×200 → to_bytes() == source_bytes` — byte-exact, the strongest available assertion. Then `mapctl apply` a 3-object edit and re-run `smoke.py`; `entity_layer_counts` moves, `frame_hash` changes only in proportion to the new entities.

---

### Phase 6 — Editor *(deferred, gated, not scoped here)*

Two facts settle this without designing anything now.

**The engine is not ready, but it is closer than the draft says.** I re-read `scripts/core/component.py` — the concurrent worker has already landed three of the five prerequisites:

| Prerequisite | State |
|---|---|
| `send_event_advanced` dispatches `None` events | **OPEN** — `component.py:657` still requires `event__ is not None`; `send_empty_event`'s `to_children` path is still a no-op |
| `MOUSE_DRAG_BEGIN`/`_END` in `mouse.py`'s `EVENT_TYPES` | **OPEN** — `scripts/core/ui/widget/behavior/mouse.py:16-30` still omits both, while `mouse.py:257` emits `MOUSE_DRAG_BEGIN` |
| `mark_event_handled` stops child fan-out | **LANDED** — `component.py:570, 582, 673` |
| dispatch iterates a snapshot | **LANDED** — `component.py:672` `tuple(self.components.items())` |
| input gates on `active`, not `visible` | **LANDED** — `component.py:574-577` plus the `accepts_input` property returning `self.active`, with the owner's decision written into the docstring |

Drag is the editor's primary verb and it does not exist yet. Until both open items land, an editor built on `GameComponent` produces ambiguous bugs.

**The chunked-bake prerequisite is real.** `renderer.py:220` bakes one full-map surface per layer — 10.24 MB each, 40.96 MB total for this map, 163.8 MB *per layer* at 200×200@32px. A pannable, zoomable editor canvas needs the chunked path (`docs/IMPROVEMENT_PLAN.md` 11.b) first.

**Therefore: no editor work is scheduled by this plan.** When the two open prerequisites and 11.b land, reopen with a single concrete deliverable — `tools/mapview.py`, a read-mostly raw-pygame viewer that renders the existing bakes, draws object rectangles with class labels, and answers *"did my programmatic edit land where I meant"* without launching Tiled. That is the only editor-shaped artifact Phases 1–5 actually need. `EditorShell`, tool modes, palettes, and retiring Tiled are downstream of a viewer nobody has used yet.

---

## PART 2 — Deliverables

| File | Phase | Action |
|---|---|---|
| `scripts/core/depth.py` — alias, `Above1`, `resolve_*` | 1 | edit |
| `scripts/core/renderer.py` — invert loop (`:213`), empty-layer skip, log object groups (`:225`) | 1, 4 | edit |
| `config/maps.json` — drop dead `layers` block | 1 | edit |
| `config/depth.json`, `config/managers/depth_data.py` | 1 | **delete** |
| `scripts/loaders/map_document.py` | 2 | **new** |
| `scripts/loaders/map_loader.py` (0 bytes today) | 2 | **new content** |
| `config/managers/map_data.py` — resolve paths against repo root | 2 | edit |
| `config/entity.json` + `config/managers/entity_data.py` — `spawn` block, no depth | 3 | edit |
| `main.py:110,116` — route via `assets.entity` | 3 | edit |
| `scripts/game/entity/game_entity.py:53-54` — accept `DataEntityMovement` | 3 | edit |
| `scripts/core/factory/object_factory.py` — promoted, namespaced, `get_or_none` | 4 | **new** |
| `scripts/core/ui/widget/factory/__init__.py` | 4 | **new** (cosmetic) |
| `scripts/loaders/object_resolver.py` | 4 | **new** |
| `scripts/core/scene/game_scene_map.py` — implement `core_build` + explicit lifecycle | 4 | edit |
| `scripts/loaders/map_commands.py`, `map_session.py` | 5 | **new** |
| `tools/mapctl.py` | 5 | **new** |

**Verification tools to create:** `tools/check_map_layers.py`, `tools/check_tmx_roundtrip.py`, `tools/check_entity_config.py`, `tools/check_object_spawn.py`, `tools/check_map_commands.py`, `tools/seed_test_objects.py`.

## PART 3 — `frame_hash` budget

`docs/IMPROVEMENT_PLAN.md:470` makes `frame_hash` the contract. This plan changes it **exactly once**:

1. **Phase 1** — `Paralax`'s 39 tiles begin rendering at depth 1. `blit_tokens` 69→70, `renderer_layer_depths` gains 1. Re-baseline at that commit.

Phases 2, 3 and 5 must show **zero drift**. Phase 4 changes it only in proportion to the objects seeded into the map. If Phase 2 moves the hash, the writer touched the render path and is wrong.

> **Correction to draft:** the draft budgeted **two** changes, the second being Phase 3's `move_speed`. Measured — that change moves nothing headless (§0.4).

## PART 4 — Blockers

**None.** `tools/smoke.py`, `tools/check_imports.py` (48 modules, 0 duplicates, PASS) and `tools/check_singletons.py` (PASS) all run clean at head.

> **Correction to draft:** the draft's PART 4 reported `tools/smoke.py` unable to boot on `UnknownBindingError: action 'action' binds unknown gamepad button 'button_0'` from `scripts/core/input.py`, and said every Verify step was contingent on that landing. It has landed. No workaround or `validate_bindings` stub is needed, and no verification step in this plan is contingent.

---

## Removed from the draft

- **Phase 4.4, `LayerRenderer.__prepare_object_layer`** — `LayerRenderer` holds no `CoreAssetManager` and no factory, and the draft's own ordering note forbids the renderer from spawning; replaced with a one-line log.
- **`"depth": "PlayerDepth"` in `config/entity.json`** — would create a fifth depth registry two steps after Phase 1.4 deletes two; `depth.py:OBJECT_CONVERTER` already maps class→depth.
- **Phase 6 "Singleton naming" repair** — factually stale. `config/managers/core_asset_manager.py:19-53` already keys `_instances` per class with an explanatory docstring and `reset_singleton()`; `tools/check_singletons.py` PASSes.
- **`GameEventType.MAP_RELOAD`** — adds a member to a tuple-`Enum` with a known linear-scan translate, in a file another worker is rewriting; a direct `reload_map()` call has no coupling.
- **`AddLayer` / `ReorderLayer` commands** — nothing in Phases 1–5 creates or reorders a layer; speculative.
- **`MapSession.to_json()` / `from_json()`** — justified only by "an AI could watch a human's session"; no such session exists.
- **`MapDocument.dirty`, `.allocate_layer_id()`, `TileLayerHandle.fill()`, `.to_array()`** — no caller in any phase.
- **Anchor normalization in `ObjectResolver`** — pytmx already does it (verified `y="48"` → `32.0`); doing it again double-shifts every tile object.
- **Phase 6a `tools/mapview.py`, 6b `EditorShell`, 6c "retire Tiled"** — deferred behind two still-open engine prerequisites and chunked baking; folded into a single gated note.
- **Phase 7 chunked baking** — already scoped as `docs/IMPROVEMENT_PLAN.md` 11.b; restating it here duplicates a plan rather than cutting one. Referenced, not respecified.