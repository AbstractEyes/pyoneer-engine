<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every claim below was measured against the WORKING TREE on 2026-09-03, during an active repair pass, with the command printed beside the claim. Where HEAD and the working tree disagree the document says which -- one such disagreement killed the Stage 1 that four independent designs proposed, and it is recorded in section 1 rather than hidden. Claims not executed this pass carry [UNVERIFIED]. -->

# Scenes, shared tilesets, scripted events, and the relay

This is the build spec. It answers one request: *scenes that group maps,
tilesets that are their own files and are editable tile by tile, an
RPG-Maker-shaped event system in JSON with real `if/elif/else`, a stratified
command vocabulary that starts with a portable handful, and communication
relay boxes the developer works through instead of loading the whole tree.*

Read [`../CLAUDE.md`](../CLAUDE.md) first. Everything below assumes its
vocabulary, its fourteen laws and its two ACTIVE WARNINGS.

---

## 0. VOCABULARY TRANSLATION — read this before anything else

The author says **"tilemap"**. This repository has two different things and
calls neither of them that. Getting this backwards inverts the whole design.

| the author's word | this repo's word | what it is | address |
|---|---|---|---|
| **"tilemap"** | **tileset** | the sheet you stamp **FROM** | `<tileset>` in the tmx, `#TAG:TilesetFile`, `#TAG:TilesetAtlas`, `#TAG:TilePalette`, the `map.tileset.*` verbs |
| **"map"** / **"tile layer"** | **tile layer** inside a **map** | the grid you stamp **ONTO** | `<layer>`, `#TAG:MapCanvas`, the `map.tile.*` verbs |
| **"scene"** | *(no authored noun exists)* | at runtime `#TAG:GameScene` is a dict of buckets plus a fan-out | `scripts/core/scene/` |

So the ask reads, in code vocabulary:

> *"tilemaps need a proper add/remove edit screen"* → **a screen that adds
> tiles to and removes tiles from a TILESET.** The map editor already exists
> and is the central widget.
>
> *"tilemaps ought to be savable as independent files, reusable
> scene-by-scene"* → **`TilesetFile` (`.tileset`) becomes a first-class
> authored asset that N maps reference.** That file exists, complete, with two
> round-trip theorems, and there are zero of them on disk.

**One genuine ambiguity, named and decided.** *"shared between multiple maps
and potentially multiple scenes"* could mean (a) shared across the map
documents listed in `config/maps.json`, or (b) shared across runtime
`GameScene`s inside one map. **We take (a)**, because `TilesetFile`'s own
docstring gives sharing-across-maps as its entire reason for existing, and (b)
has no authored artifact to attach to. Sharing across scenes then falls out
*derived*: a scene names maps, maps name tilesets, so "which scenes use this
sheet" is computed and never stored.

**A second ambiguity, also decided.** *"remove a tile"* could mean *erase a
placed tile* or *take a tile out of the sheet*. The eraser already ships
(`Tool.ERASER`, gid 0). So the ask means the sheet, and section 2 says what
that can and cannot mean.

---

## 1. WHAT ALREADY EXISTS — the honest inventory

**Read this section before writing a line.** Four independent designs preceded
this spec and all four proposed the same Stage 1. That Stage 1 is already
built. The inventory is the deliverable here, not the preamble.

### 1.1 The Stage 1 that four designs proposed, and why it is dead

Every design opened by making `map.tileset.grow` and `map.tileset.rename`
reachable, citing `docs/NEXT.md` entry 3 and the fourth sighting of the
ACTIVE WARNING. Measured this pass:

```
git show HEAD:editor/ui/canvas.py | grep -c "map.tileset.grow\|map.tileset.rename"   -> 0
grep -c "map.tileset.grow\|map.tileset.rename" editor/ui/canvas.py                    -> 4
```

**The gap is closed in the repair pass's working tree and not at HEAD.**
`TilePalette` now carries a right-click header menu with Rename / Grow /
Remove, asking through the `ask` seam and emitting `tileset_requested`, with
the headroom quoted in the form *before* the author types
(`#TAG:TilePalette.request_grow`, `#TAG:TilePalette.request_rename`,
`#TAG:TilePalette.request_remove`).

This is the ACTIVE WARNING landing on the people quoting it: *"A gap you did
not re-measure is a gap you are about to file twice."* It was filed five
times. **`docs/NEXT.md` entry 3 is stale the moment the repair pass lands and
must be struck in the same change.**

The consequence for this spec is concrete: **Stage 1 is not a tileset
button.** It is section 5a's scoped relay payload, which is the other thing the
author named, is one day, ships a gesture, and touches files the repair pass
is not holding.

### 1.2 Already built — do not build a second one

| thing | address | measured by | state |
|---|---|---|---|
| The `.tileset` format | `#TAG:scripts/loaders/tileset_file.py` | `find . -name "*.tileset"` → **0 files** | **complete, 949 lines, two round-trip theorems, zero files on disk and no editor caller** |
| Per-tile authored data | `#TAG:TileEntry` | `grep -n "properties:" scripts/loaders/tileset_file.py` | `TileEntry.properties: tuple[Property, ...]` **exists.** Retirement needs no grammar change |
| Property line grammar | `#TAG:Property.render` | read this pass | `prop <type> <name> <value>` — so it is `prop bool pyoneer_retired true`, **not** `prop pyoneer_retired true` |
| Tileset growth | `#TAG:MapDocument.grow_tileset`, `#TAG:MapDocument.tileset_headroom` | `grep -n "def grow_tileset" scripts/loaders/map_document.py` | complete, twelve named refusals, exact inverse, **now reachable** (1.1) |
| Cross-doc tile counting | `#TAG:MapDocument.tiles_using_tileset` | same | per-document only; **no cross-map index exists** |
| Region crop import | `#TAG:TilesetImportDialog`, `#TAG:GridPreview`, `#TAG:CROP_DIR` | `grep -n "def open_for" editor/ui/tileset_dialog.py` | non-modal, snapped rubber band, `#TAG:write_region` never overwrites different pixels |
| The one flow slot | `#TAG:SceneManager.post_update` | `grep -n "self.flow" scripts/core/scene/scene_manager.py` | `self.flow: Any = None`, ticked after the fan-out returns, **duck-typed on `update(delta)`** |
| Narrative sequencer | `#TAG:SceneFlow` | `tools/check_flow.py` (144 assertions) | ordered beats, exact agency borrow/restore, `MS_PER_DELTA` conversion, **no branching, no JSON, no trigger** |
| Action dispatch | `#TAG:ActionRouter`, `#TAG:GameActionRelayBehavior` | `grep -n "ADVANCE_ACTION" scripts/game/flow/scene_flow.py` | `(token, payload)` keyed, N handlers, **no handler can silence another** |
| Trigger vocabulary | `#TAG:TRIGGER_KINDS`, `#TAG:EVENT_NAMES` | `grep -rn "pyoneer_trigger" scripts/` → **0** | 796 lines of `enter/exit/stay/use`, filters, `once`, `cooldown_ms`, `payload` — **authored, and no runtime reader** |
| Behavior registry | `#TAG:BehaviorSpec`, `#TAG:BehaviorParam` | `grep -n "genres:\|status:" scripts/game/behavior/base.py` | **`BehaviorSpec` carries `genres: tuple[str,...]` as a FIELD, and `status` against `STATUSES`.** This decides section 5b's naming |
| Genre pack validation | `#TAG:GenrePack`, `_object_classes` | `grep -n "validate_list" editor/core/genre.py` | a pack declaring an unknown behavior token **raises `PyoneerGenreError` at pack load**, through *the engine's own judge, not a second copy of it* |
| The relay chain | `#TAG:PromptStrip` → `Session.stage` → `#TAG:Manifest` → `#TAG:write_bundle` → `response.jsonl` → `#TAG:parse_response` → `EditorWindow.run` | `wc -l editor/ui/prompt.py` → 104 | **complete end to end**, driven headlessly by `tools/check_editor_ui.py`. Eight strips, each already scoped |
| Atomic apply | `#TAG:CommandStream.apply` | `grep -n "rolled_back" editor/core/commands.py` | all-or-nothing with reverse-replay rollback. **Partial application is structurally impossible** |
| Non-mutating dry run | `#TAG:Verb.validate` | `grep -n "def validate" editor/core/commands.py` | checks scope and args, materialises defaults, **mutates nothing** |
| Verb vocabulary | `#TAG:commands.describe_all` | run this pass | **51 verbs, 32,268 bytes of `docs/COMMANDS.md`** |

### 1.3 Half built — the seam exists and one end is missing

| gap | measured |
|---|---|
| `Session.apply_response` has **zero callers**; `EditorWindow.apply_response` reimplements it | `grep -rn "apply_response" editor/ --include=*.py` |
| `Manifest.from_json` has **zero callers**, so staged notes die with the process | `grep -rn "Manifest.from_json" editor/ tools/ --include=*.py` → nothing |
| `NOTES.md` is instructed by `BRIEF.md` and **read by nothing** | `grep -rn "NOTES.md" editor/ --include=*.py` |
| `describe_scope` ends `return ["*(no description available for this scope kind)*"]` — **a silent plausible default inside a payload generator** (law 7) | read at `#TAG:describe_scope` |
| `ActionRouter.clear()` names *"a scene teardown"* as its caller and **has none** | `grep -rn "actions.clear()" scripts/` → nothing |
| `GameScene.flags["active"]` is set by `#TAG:GameScene.begin` and **no writer clears it** | `grep -rn "flags\[.active.\]" scripts/` |
| `GameScene.core_lifecycle_dispose*` has **never been driven** | `grep -rn "core_lifecycle_dispose" main.py demos/ scripts/core/scene/` |
| `SceneManager.set_scene` is a **one-line pointer swap** raising a bare `KeyError` | read at `#TAG:SceneManager.set_scene` |
| **No verb writes `config/maps.json`**, and it holds **one map** | `grep -n "config/" editor/core/verbs.py` → nothing; `cat config/maps.json` |
| `Project.drop_table` calls `os.remove` **at apply time**; `save()` never deletes → **drop, then undo, leaves no file on disk** | `grep -n "os.remove" editor/core/project.py` |
| `assets` and `genre` scopes match **zero verbs** | measured with `Scope.matches` over `all_verbs()` |
| `docs/BEHAVIORS.md`'s hand-written preamble advertises `tile_collision`, which is not registered | `docs/NEXT.md` entry 1 |

### 1.4 Genuinely new

A scene document and its reader. An event script document, its reader and its
interpreter. An op registry. A shared `.tileset` link. Retirement. The scoped
relay payload and the back channel. Four screens.

### 1.5 The measurement that governs section 2

```
.venv/Scripts/python.exe -c "<count gids in the shipped map by tileset>"
```

<!-- fact: historical -- measured against the retired private canvas, which
     was replaced by data/maps/starter.tmx on 2026-09-04. Kept because the
     RATIO is what governs section 2, and the ratio is a property of how a
     tile-based map uses one terrain sheet, not of that particular file. -->

- **10,897 painted cells** in the retired canvas (Floor 9,897 · PlayerDepth 314 ·
  Paralax 237 · Foreground 187 · GroundClutter 159 · FloorCollision 43 ·
  ParalaxCollision 40 · Above1 20).
- **10,210 of them belong to `TileA2`**, which owns 768 tiles in 32 columns
  at `firstgid` 1 with **headroom 0** (Clutter starts at 769).
- Only **75 distinct local ids** are used, from 2 to 547.

Deleting one local id from `TileA2` and closing the gap:

| delete local id | painted cells whose art silently changes |
|---|---|
| 0 | **10,210** |
| 2 (the lowest actually used) | **10,210** |
| 194 (the median used) | 466 |
| 547 (the highest used) | 1 |

Nothing raises anywhere — not Tiled, not pytmx, not this engine. And the
`collision` sheet is worse: its local id **is** the mask value, so a shift
there changes the *meaning* of every painted collision cell, not its art.

---

## 2. THE MODEL

### 2.1 The diagram — what OWNS, what merely REFERENCES

```
  data/project/scenes/<id>.json          AUTHORED. The scene.
        |
        |  OWNS      vars schema, controls, entry/exit scripts, loadouts,
        |            the ORDERED LIST of map slots
        |
        |  REFERENCES ------> config/maps.json entry ------> data/maps/<name>.tmx
        |                                                          |
        |  REFERENCES ------> data/project/scripts/<id>.json        |  OWNS
        |                            (event scripts)               |  layers, cells,
        |                                                          |  objects, firstgid
        v                                                          |
   scripts/loaders/scene_file.py  (read-only, engine side)         |  REFERENCES
        |                                                          v
        |  BECOMES, at load       data/project/tilesets/<Name>.tileset
        v                                     |
   GameScene  (runtime bucket + fan-out)      |  OWNS  image, imagesize, tilesize,
   -- unchanged, not replaced                 |        count, columns, per-tile
                                              |        properties (incl. retirement),
                                              |        the .blitmask reference
                                              |
                                              |  REFERENCES
                                              v
                                    data/graphics/.../<Name>.png
                                    data/graphics/.../<Name>.blitmask
```

**Read the ownership column, because it is the whole model:**

- **A scene OWNS an ordered list of map slots.** It is the only place map
  grouping lives.
- **A scene does NOT own tilesets.** A map declares its own; "the scene's
  tilesets" is derived. Storing it would be a second source of truth that
  drifts silently.
- **A map OWNS `firstgid` and nothing else about a shared sheet.** This is not
  invented: `#TAG:TilesetFile` deliberately has **no `first_gid` field** and
  `#TAG:TilesetLink` carries it. The format already made this decision.
- **The `.tileset` OWNS geometry and the tile roster.** The embedded
  `<tileset>` element is a *materialised link*: `firstgid` plus a cached copy
  of the geometry that Tiled and pytmx must be able to read.
- **A scene OWNS its variable schema.** Every var an event reads or writes is
  declared here with a type and a default, which is what lets a typo raise
  before a frame runs.
- **A script is OWNED by nobody.** It sits at project level and is referenced
  by scenes and by map objects, because the author asked for scripts *reusable
  scene-by-scene*, and that has to be structural.
- **`GameScene` is unchanged.** It is what a scene is *loaded into*, not what a
  scene is. That split is the table stack's split reproduced: authored JSON,
  an editor model, an engine reader, *joined by the FILES, never by an import*
  (law 2's corollary, stated in `#TAG:scripts/loaders/table_file.py`).

### 2.2 The load graph is a DAG; the runtime graph may cycle

`scene → map → tileset → image` and `scene → script → script`. A map never
names a scene. A tileset never names a map. A script names a scene only
through `enter_scene`, which is a **runtime transition**, so the target scene
is loaded lazily and `overworld → dungeon → overworld` costs nothing.

`call` can cycle. It is **caught, not prevented**: `MAX_CALL_DEPTH = 16`, and
exceeding it raises **naming the whole chain**. A silent stop is a script that
looks like it worked.

### 2.3 Scopes — three new kinds, and why not five

`SCOPE_KINDS` is a closed ten today
(`project genre map layer object table row field assets code`, measured). We
add **three**: `scene`, `tileset`, `script`.

**A scene is a peer ROOT, never a parent segment.** `scene:overworld`, never
`scene:overworld/map:test`. The reason is load-bearing and measured:
`#TAG:Verb.validate` tests `any(command.scope.matches(p) for p in self.scopes)`
and `Scope.matches` is segment-wise, so nesting maps under scenes would
**silently invalidate every one of the 26 `map:*` verbs**. `table:actors` and
`map:test` already coexist as flat roots with references between them.

**`page` and `node` are NOT scope kinds.** They are addressed by verb
*argument*, exactly as the whole `map.tileset.*` family already addresses a
sheet by a `name` argument rather than a `tileset:` segment. Five new
permanent kinds where three do the work is permanent surface bought for
nothing.

**`describe_scope` gains arms for all three, and its fallback becomes a
raise** — `#TAG:describe_scope` currently returns
`"*(no description available for this scope kind)*"`, which is a plausible
default inside a payload generator and therefore the 39-tiles shape (law 7).
`field` and `code` fall through it **today**, so both get arms in the same
change.

### 2.4 What "remove a tile" can mean — three legal forms and one refused

`gid = firstgid + local_id`, `local_id = row * columns + column`. The local id
is the only thing that crosses a file boundary. Therefore:

> **A local id is never renumbered and never reused. A tileset grows DOWNWARD
> at a fixed width. Column count is immutable for the life of a tileset.**

The column rule is separate and is *not* a consequence of the first: the
`.blitmask` is row-major over the sheet and `#TAG:tileset_defaults` **raises**
unless `mask.width == ref.columns`.

| form | verb | painted gids | invertible |
|---|---|---|---|
| **GROW** — append whole rows at the same width | `map.tileset.grow` *(exists)* | **unchanged**, zero cell rewrites | yes, returns the four replaced values |
| **RETIRE** — the palette stops offering it; the art keeps drawing | `tileset.tile.retire` | **unchanged, art unchanged** | yes, exactly |
| **TRIM** — drop trailing slots | `map.tileset.grow` with a smaller count *(exists)* | refused while anything points into the dropped range | yes |
| **~~COMPACT~~** — delete mid-sheet and close the gap | — | **10,210 of 10,210 cells repaint wrong** | **PERMANENTLY REFUSED** |

**RETIRE is almost certainly what the author means by "remove".** It takes the
tile out of the palette, costs zero cell rewrites, is one click to undo, and
is the only form that is safe on a sheet three maps share.

Removing a tile the author genuinely wants gone is therefore **two parts, both
in one transaction**: retire the id, and repaint the cells that use it. One
`run(...)`, one `Transaction`, **one Ctrl+Z** — and that already spans maps,
because `apply` validates each command's own scope and `Project.save()` writes
every dirty `MapDocument`.

### 2.5 A new file-backed document joins `Project.dirty_*`

Measured: `#TAG:Project.drop_table` calls `os.remove` **inside the command**,
while `create_table` only registers, and `save()` writes but never deletes. So
drop-then-undo leaves no file on disk, and a rolled-back batch leaves the disk
changed.

> **Every new document type in this spec — `.tileset`, `.scene.json`,
> `.script.json` — is created and deleted in the in-memory model only, and
> written at `Project.save()`. A file's existence is the one thing that
> genuinely cannot invert, and it already has its rule at
> `#TAG:written_file_has_no_inverse`.**

---

## 3. THE FILE FORMATS

**Every key named in this section is a FILE FORMAT string and permanent under
law 8.** Renaming one silently disarms every document carrying it.

### 3.1 The versioning rule, and unknown keys

Every JSON document opens with two keys, in this order:

```json
{ "format": "pyoneer.scene", "version": 1, ... }
```

| failure | reader |
|---|---|
| `format` absent or wrong | **raises**, naming the path, the expected string and what was found |
| `version` absent or not an int | **raises** |
| `version` > the reader's `VERSION` | **raises**: `"<path> is version 2; this build reads version 1."` |
| **any unknown key, at any depth** | **raises**, naming the key, its path within the document, and the accepted set |

The unknown-key rule is deliberately stricter than what is on disk today, and
the reason is a measured asymmetry: an off-schema row key survives the
editor's `DataTable.from_json` and then **raises in the engine's
`load_table` at boot**. A key the writer keeps and the reader refuses is the
39-tiles shape with a delay fuse. New formats raise on **both** sides.

Precedent for versioning at all: `#TAG:TilesetFile` carries `VERSION = 1` and
`blitmap.py` calls `read_magic(cursor, MAGIC, VERSION)`. Nothing under
`data/project/` is versioned today; that is the mistake not to repeat.

**Migration:** none until there is a version 2. Then the reader migrates *in
memory* and the next `Project.save()` writes v2 — one visible git diff, at a
moment the author chose.

**Determinism:** `json.dumps(obj, indent=2, sort_keys=True) + "\n"` with
`newline="\n"`, exactly as `Project.save()` already writes tables.

### 3.2 The scene — `data/project/scenes/overworld.json`

> **PARTLY BUILT, 2026-09-11, and knowing which part matters.** The directory,
> the five keys `format version id title vars`, and a reader for them ship:
> `#TAG:load_vars` merges every `data/project/scenes/*.json` into the
> `VarSchema` that `main.py` and the editor's `scripts_of` both read, which is
> what let the event screen open the script the game runs. The **eight further
> keys below** — `loadouts maps entry_map controls routes on_enter on_exit
> next` — have no reader and are **REFUSED** rather than accepted and
> discarded, so authoring one early raises naming the key instead of looking
> like it works. Each lands with the code that reads it; `check_scenes` in the
> planned-checks fence is still unwritten and still owns the rest.

```json
{
  "format": "pyoneer.scene",
  "version": 1,
  "id": "overworld",
  "title": "The Overworld",
  "doc": "Town, road and cave. One continuity of variables.",

  "loadouts": ["core", "topdown_rpg"],

  "maps": [
    {"map": "test", "entry": "start"},
    {"map": "cave", "entry": "mouth"}
  ],
  "entry_map": "test",

  "vars": {
    "gate_open":  {"type": "bool", "default": false, "doc": "Set by the keeper."},
    "coins":      {"type": "int",  "default": 0,     "doc": "Spendable."},
    "keeper_pick":{"type": "int",  "default": -1,    "doc": "Written by an ask."}
  },

  "controls": {"steerable": true, "enabled_inputs": true, "simulated": true},

  "routes": [
    {"token": "interact_action", "payload": "keeper", "script": "keeper_gate"}
  ],

  "on_enter": ["overworld_open"],
  "on_exit":  [],
  "next":     ["dungeon"]
}
```

**Why each key, and why it is worth being permanent:**

- **`id` must equal the filename stem.** The same rule `load_table` enforces
  (*"declares table 'actors' but is named 'wrongname.json'"*), for the same
  measured reason: the editor keys by the inner name, the engine keys by the
  file, and a disagreement is a boot crash the editor never sees.
- **`loadouts` is the engine-readable stratum declaration.** It is here, and
  **not a `genre` key**, because law 2 forbids the engine reading a pack — so a
  pack id in an engine-read file would be a second home for a fact only the
  editor owns. This one placement is what lets section 5b raise at scene load
  instead of only at authoring time.
- **`maps` is the hierarchy**, ordered, each slot naming a map from
  `config/maps.json` plus a named entry point. **No `at: [x, y]` position
  field**, deliberately: nothing reads it, and an authored field with no
  reader is exactly what `pyoneer_trigger` has been for months. It lands with
  the stage that consumes it.
- **No `tilesets` key.** Derived (§2.1).
- **`vars` is the schema for every variable the scene's scripts touch**, with
  a type and a default. This is `#TAG:BehaviorParam`'s shape and it is what
  makes §4.5's static gate possible. There is no untyped global.
- **`controls` is the three existing `BodyState` agency axes and nothing
  else.** `null` on an axis means *do not touch it*, the exact semantics
  `SceneFlow` already uses. A scene **cannot rebind or unbind an input verb**:
  `#TAG:InputActionManager.held` is an unguarded dict index, so an unbound
  verb raises `KeyError` *inside* `core_frame_update`, killing the frame for
  every sibling in that bucket (law 10).
- **`routes` is what makes controls scene-dependent** — a `(token, payload)`
  pair meaning a different script per scene, installed into the existing
  `ActionRouter` on entry. This finally gives `#TAG:ActionRouter.clear` the
  caller its own docstring names.
- **`next` is continuity, and it is enforced.** An `enter_scene "dungeon"` in a
  script belonging to a scene whose `next` omits `dungeon` **raises at script
  load**, naming both. That is what makes a flow graph worth drawing.

### 3.3 The tileset — `data/project/tilesets/TileA2.tileset`

**Not JSON.** The format exists, is complete, is checked by
`tools/check_blitmap.py` and `tools/check_blitmap_engine.py`, and carries two
proved theorems — `parse(render(m)) == m` and `render(parse(t)) == t`. Writing
a JSON sibling for it is precisely the shape the ACTIVE WARNING says has died
five times.

**It is extended by zero lines of new grammar**, because `#TAG:TileEntry`
already carries `properties: tuple[Property, ...]`:

```
tileset 1
name TileA2
image ../graphics/tilesets/System/TileA2.png
imagesize 512 384
tilesize 16 16
count 768
columns 32
collision TileA2.blitmask
tile 194
	prop bool pyoneer_retired true
```

The property line grammar is `prop <type> <name> <value>`
(`#TAG:Property.render`, read this pass) — so it is
`prop bool pyoneer_retired true`, three words after `prop`. The `pyoneer_`
prefix is law 1 and comes from `#TAG:layer_profile.PREFIX`, never retyped.

**Retirement is per-tile data in the SHARED file**, so three maps referencing
one sheet cannot disagree about which tiles are retired. Putting it on a tmx
`<tile>` element would make it per-map for a sheet whose whole point is
sharing — a permanent property name encoding the wrong thing.

**The link, and the only tmx change in this spec:**

```xml
<tileset firstgid="1" name="TileA2" tilewidth="16" tileheight="16"
         tilecount="768" columns="32">
 <properties>
  <property name="pyoneer_tileset"   value="../project/tilesets/TileA2.tileset"/>
  <property name="pyoneer_collision" value="../graphics/tilesets/System/TileA2.blitmask"/>
 </properties>
 <image source="../graphics/tilesets/System/TileA2.png" width="512" height="384"/>
</tileset>
```

**One new property, `pyoneer_tileset`, on a `<tileset>` element.** The shape is
not new: `pyoneer_collision` already lives on that exact element and already
names a sidecar, and `map.tileset.mask.set` already writes it there
byte-exactly.

**Drift is a HARD refusal, never a silent reconcile.** The embedded
`tilewidth`/`tileheight`/`tilecount`/`columns` and `<image>` must **equal** the
`.tileset`'s. A mismatch raises at load naming **both files and the field that
differs**. The geometry is stated twice, and stating it twice is fine exactly
when disagreeing about it is fatal.

**Path trap, already asserted in both directions by
`tools/check_blitmap_engine.py`:** `#TAG:from_tmx_tileset` copies
`<image source>` **verbatim and never rebases it**. The `.tileset`'s `image`
line is relative to the `.tileset` file itself and is computed at write time
— which the editor already knows how to do (`#TAG:relative_image_path`).

### 3.4 The event script — `data/project/scripts/keeper_gate.json`

```json
{
  "format": "pyoneer.script",
  "version": 1,
  "id": "keeper_gate",
  "title": "The keeper at the north gate",

  "loadouts": ["core"],

  "pages": [
    {
      "id": "pg_open",
      "note": "once the gate is open the keeper only nods",
      "trigger": "use",
      "payload": "keeper",
      "when": [{"var": "gate_open", "is": true}],
      "body": [
        {"id": "n1", "do": "say", "who": "Keeper", "text": "Go on through."}
      ]
    },
    {
      "id": "pg_main",
      "trigger": "use",
      "payload": "keeper",
      "once": false,
      "cooldown_ms": 400,
      "when": [],
      "body": [
        {"id": "n2", "do": "hold", "steerable": false},
        {"id": "n3", "do": "say", "who": "Keeper",
                     "text": "The north gate is sealed."},

        {"id": "n4", "if": [{"var": "coins", "at_least": 100}],
         "then": [
           {"id": "n5", "do": "say", "who": "Keeper", "text": "Unless you can pay."},
           {"id": "n6", "do": "set", "var": "coins", "to": -100, "by": "add"},
           {"id": "n7", "do": "set", "var": "gate_open", "to": true}
         ],
         "elif": [
           {"when": [{"var": "coins", "at_least": 10}],
            "then": [
              {"id": "n8", "do": "ask", "prompt": "Half now?",
                           "options": ["Pay half", "Walk away"],
                           "into": "keeper_pick"},
              {"id": "n9", "if": [{"var": "keeper_pick", "is": 0}],
               "then": [{"id": "n10", "do": "say", "text": "Half it is."}],
               "else": [{"id": "n11", "do": "say", "text": "Then wait."}]}
            ]}
         ],
         "else": [
           {"id": "n12", "do": "say", "text": "Come back with coin."},
           {"id": "n13", "do": "stop"}
         ]},

        {"id": "n14", "do": "wait", "ms": 250},
        {"id": "n15", "do": "release"}
      ]
    }
  ]
}
```

**Every decision, justified:**

- **`id` on the script, every page and every node. Required, stable, never
  reused, never minted.** A node with no `id` **raises at load naming its
  position**. This is the single most important addressing decision in the
  spec: **a relay response is an ordered batch**, so two path-addressed
  inserts mis-land the second the moment the first shifts an index —
  *silently*, with a valid-looking transaction and a clean undo. A wrong `id`
  is loud. A minted id changes when the file is re-saved.
- **`pages` are ordered and the FIRST page whose `when` all pass runs.** This
  is deliberately the opposite of RPG Maker, which evaluates bottom-up so the
  highest-numbered page shadows the rest — a famous source of confusion. Here
  the list you read top to bottom is the order it runs, so a diff that inserts
  a page inserts it where it will fire. `"when": []` always passes and is the
  fallback page. Zero passing pages is **not an error**; a blank page is a
  real idiom.
- **`when` is a list of comparison records, ANDed. Never a string.** An
  expression language needs a grammar, and a grammar in a game file is where
  silent truthiness lives (`"0"` is truthy, `""` is falsy, a typo'd name
  resolves to nothing). Six comparators, **closed forever**:
  `is not at_least at_most in contains`. A seventh needs a design pass. A
  condition object carrying two operator keys **raises**, naming both.
  A structured condition also renders as an `#TAG:Field` form with zero
  parsing, so the condition editor is free.
- **No `and`/`or` nesting in `when`.** A page *is* the or-arm; two pages with
  different `when` lists is the disjunction and reads better than nesting.
- **`if` / `then` / `elif` / `else` is ONE node, and `elif` is a LIST of
  arms.** A flat `elif` key holds one arm and the author will want three. And
  one node with arms means an added arm is **one contiguous block in the
  diff**; flattened it is an insertion plus a re-indent of everything after
  it, and the reviewer cannot see the shape changed.
- **Nesting is real JSON nesting.** RPG Maker renders a flat list with a
  `Branch End` row; that is a *view* concern. The file is a tree; §5.3 renders
  it flat with indentation.
- **Exactly two node shapes.** Executable `{"id", "do", ...args}` and control
  `{"id", "if"|"while", ...arms}`. Nothing else parses.
- **`do`, not `command` or `type`.** Short, and it does not collide with the
  editor's `Command` noun, which appears in the same relay payloads.
- **`trigger`, `payload`, `once`, `cooldown_ms`** are taken **verbatim** from
  `#TAG:TRIGGER_KINDS` and the action behavior params, which were themselves
  spelled to match. One language across action, trigger and script — a third
  user of one vocabulary, not a fourth spelling of it. `SCRIPT_TRIGGERS` adds
  `auto` and is asserted by a check to be a **superset of
  `map_events.TRIGGER_KINDS` word for word**, rather than importing across the
  boundary.
- **`note` is a key on any node.** There is no `comment` command — a node
  whose runtime is a no-op can never be *measured* as integrated, which breaks
  the one property §5b.6 depends on.

**Variable namespaces, three, closed:** `global.` (the process), `scene.`
(cleared on scene entry), `local.` (per `(map, object)` — RPG Maker's
self-switch, generalised to any value, and the thing that lets one
`keeper_gate` document sit on ten doors and each remember its own state). A
bare name means `scene.`.

---

## 4. THE RUNTIME

### 4.1 It lives on the CALLED side, and that is structural, not a promise

Law 3. The measured cost: `GameScene.core_input_receive` hands **one shared
`PyoneerEvent`** to every bound object including the whole UI tree, and
consumption is **not type-gated** — one `handle()` in a fan-out silences every
sibling for the rest of the frame. That is *why* a behavior is called and
never dispatched to.

Measured (`grep -n "self.flow" scripts/core/scene/scene_manager.py`):
`#TAG:SceneManager.post_update` ticks **one duck-typed `self.flow` slot** on
`update(delta)`, after the fan-out has returned, with `delta` passed through
unconverted because `SceneFlow.update` is what converts.

> **`ScriptRun` fits that slot with ZERO changes to `SceneManager`, ZERO to
> `GameScene`, ZERO new `GameEventType` members, and ZERO contact with the
> bus. Any design that needs a `SceneManager` edit to run a script has taken a
> wrong turn.**

`GameEventType.USE` is the standing proof of what a member with no listener
costs, and `#TAG:EVENT_NAMES` already *reserves* four strings for members that
do not exist. **Do not create them.**

The check asserts this from the **parse tree of the module**, with a **planted
decoy** proving the scan can find a `handle(` — `tools/check_action.py`'s and
`tools/check_flow.py`'s exact technique, because asserting `binds == ()`
passes trivially forever (law 5).

### 4.2 New modules, and why none is a sibling file

```
scripts/game/flow/ops.py         the op registry -- mirrors behavior/registry.py
scripts/game/flow/interpreter.py ScriptRun, the step machine
scripts/loaders/script_file.py   the JSON reader -- mirrors table_file.py
scripts/loaders/scene_file.py    the scene reader -- mirrors table_file.py
```

`scripts/game/flow/` already declares its job as *"Scene and GUI flow: where a
firing goes, and what step the story is on"* and holds `router.py` (dispatch)
and `scene_flow.py` (sequencing). An interpreter over a tree is a third job in
that family — **not** a new `scripts/game/events/` package beside a two-module
package already owning the sequencer and the dispatch it needs.

`scripts/loaders/` already holds four read-only authored-data readers. Two more
join a family.

**The one thing that would be a duplicate is prevented by an extraction.**
`SceneFlow._borrow`/`_restore` is exact — it records each body's value per
touched axis before writing, skips bodies with no `BodyState`, and restores
**the saved value, never `True`**. So:

> **`AgencyHold` is lifted OUT of `SceneFlow` into module scope in
> `scene_flow.py` — an edit INTO the incumbent file — and `SceneFlow` and
> `ScriptRun` both use it.** `SceneFlow` keeps working, `demos/story.py` is
> untouched, and `tools/check_flow.py`'s 144 assertions are the regression net
> on the extraction.

That is the 425-duplicate-lines lesson applied before the fact.

### 4.3 Agency, through the three existing axes

`tools/check_action.py` already asserts these diverge **in both directions**,
and `state.py` says the split *"must not be collapsed"*:

| axis | what clearing it does |
|---|---|
| `steerable` | the body cannot walk. The gate is on the **producer**, so physics keeps running — a side-on body still falls |
| `enabled_inputs` | read by `player_input` **and** every action behavior. Clearing `steerable` and leaving this is exactly *"cannot walk, can still press continue"* |
| `simulated` | per-entity whole-body switch. **There is no scene-level pause in this engine** and this spec does not add one |

`hold` takes them tri-state (`null` = do not touch); `release` puts back
**what `hold` recorded**. They are two names because shipping either alone is a
bug.

### 4.4 The step machine, and why it cannot hang a frame

`ScriptRun.update(delta)` is a step machine, not a generator. A node either
**completes** (`set`, `if`, `stop`) or **yields** (`say`, `ask`, `wait`). The
cursor is a **stack of (node list, index)**; entering an arm pushes, running
off its end pops, `stop` clears it.

- `delta` arrives as **milliseconds ÷ 60** and is converted **once**, through
  the `MS_PER_DELTA = 60.0` that `scene_flow.py` already imports from
  `scripts.game.behavior.movement` (law 9, handled at one point).
- **`MAX_STEPS_PER_FRAME = 512`, and exceeding it RAISES**, naming the script
  and the node path. It does not silently budget. RPG Maker's answer to a
  runaway loop is a silent per-frame cap, which is a hang you cannot diagnose
  — the same failure law 13 already paid 40 silent minutes for, one layer
  down.
- **`MAX_CALL_DEPTH = 16`**, raising with the whole chain.
- A `PyoneerError` from a node gets `.push_frame(script=…, page=…, node=…)`
  and is **re-raised, never swallowed** — `EntityBehaviors.update`'s idiom.

**Only one script runs at a time.** `SceneManager.flow` is one slot
deliberately: a narrative flow is modal, and two would each restore agency the
other changed. A `ScriptQueue` owns the queue and hands the manager **one run
at a time**, which is what that comment tells a caller to do.

### 4.5 Where it raises, and why there

| fault | raises at | why there |
|---|---|---|
| unknown `format` / `version` / **any unknown key** | script load | the document is unreadable |
| unknown `do` name | **script load** | a branch that only runs on Tuesday would otherwise ship broken. `#TAG:registry.resolve`'s precedent: raise on an unknown token rather than skip it, because a skipped token *looks like the feature working* |
| unknown comparator, undeclared `var`, wrong-typed `set`, missing/duplicate node `id` | **script load** | cheapest possible moment, whole file in hand, no frame, no display |
| a `do` outside the script's `loadouts` | **script load** | §5b.5 |
| the script's `loadouts` ⊄ the scene's | **scene load** | §5b.5 |
| `pyoneer_script` naming an absent document | **map load**, naming the object | `#TAG:actor_row`'s exact precedent for an absent `pyoneer_actor` row |
| runaway loop | frame, at `MAX_STEPS_PER_FRAME` | cannot be known earlier |
| anything vocabulary-shaped | **never at execution** | by load time every op is a resolved callable, so there is no dispatch-on-string at runtime and **no place left for a fallback to hide** |

**Reading a variable is TOTAL and cannot raise.** Because every var is
declared, the raise moves to load time. A raise mid-cutscene, after agency has
been taken, is strictly worse than a raise at load.

### 4.6 How a script reaches an entity — two routes, both already wired

**Route A — `use`, and it needs nothing new.** An object carrying
`pyoneer_behaviors="player_input,interact_action,action_relay"`,
`pyoneer_param_payload="keeper"` and `pyoneer_script="keeper_gate"`:

```
press 'action' -> interact_action records ActionFired(name, verb, payload="keeper")
               -> action_relay (order 90) CALLS entity.action_sink
               -> SceneManager.actions (ActionRouter) picks (interact_action, "keeper")
               -> ScriptQueue.start("keeper_gate")
               -> SceneManager.flow = that ScriptRun
```

`ActionRouter` is already `entity.action_sink` on **both** binding routes,
already `(token, payload)` keyed, already N handlers with no way for one to
silence another. This is exactly how `demos/narrative.py` starts a `SceneFlow`
today. **Zero new dispatch.**

**Route B — `enter`/`exit`/`stay`.** `editor/core/map_events.py` (796 lines) is
authored and has **zero runtime readers**
(`grep -rn "pyoneer_trigger" scripts/` → nothing). Its own docstring says its
home is `scripts/core/` beside `layer_profile.py`, that the move is
**mechanical**, and that it takes only `Capability` and `RESERVED` from
`editor/`. So:

> **`editor/core/map_events.py` → `scripts/core/map_events.py`, and
> `editor/core/map_events.py` becomes a re-export.** That is law 2's corollary
> as written — *shared logic lives in `scripts/` and the editor re-exports it*
> — and it is what prevents a second copy of the trigger vocabulary.

Then the six-step seam that file already specifies, using the **dict** shape
its own docstring measured (**2,621 µs/frame at 256 regions as
`GameComponent`s versus 1.7 µs for a dict lookup**): rasterize
`MapEvent.cells()` into `dict[cell_index, MapEvent]` **once at load**, then a
per-frame cell compare per gated body, filtered by `accepts()`.

Step 3 runs in **one new behavior token**, because a behavior is called from
the entity's own frame update:

```
script_trigger   order=85   after topdown_move (20) and animation_drive (80),
                            so it reads THIS frame's position;
                            before action_relay (90), so a firing routes the same frame
```

**Law 10 note, stated so nobody adds a binding by reflex: `script_trigger`
polls no input verb.** It reads `entity.transform.position`. No
`config/inputs.json` change accompanies it.

`auto` is not a region trigger; it fires from the scene's `on_enter`.

### 4.7 The scene switch — four fixes INTO `SceneManager`

Measured today: after `set_scene('B')`, scene A's objects **stop updating and
keep drawing**, because `bind` writes into both the scene bucket and the
shared renderer while `set_scene` is a one-line pointer swap.

| fix | into | what it repairs |
|---|---|---|
| raise `PyoneerSceneError` naming the available scenes | `#TAG:SceneManager.set_scene` | the one raise in that file with no teeth (bare `KeyError('nope')`) |
| unbind the outgoing scene's `contents()` from the renderer | `SceneManager` | the keep-drawing bug. `LayerRenderer.unbind` exists; `check_flow` claim 10 covers its `GameComponentLayer` half |
| `self.actions.clear()`, then install the incoming scene's `routes` | `SceneManager` | gives `#TAG:ActionRouter.clear` the caller **its own docstring names** and it has never had |
| `GameScene.end()`, clearing `flags["active"]` | `GameScene` | **nothing clears it today**, so a revisited scene never re-prepares |

`GameScene.end()` is the one genuinely risky edit here:
`core_lifecycle_prepare` already runs twice by design, and a third run
allocates a third time for any behavior allocating in `prepare` instead of
`attach`. It is gated behind its own check with a probe counting hook calls,
**both halves** — a re-entered scene prepares again, *and* a once-entered scene
does not double-prepare beyond the documented twice.

---

## 5. THE SCREENS

Two rules apply to every screen below and are not negotiable:

1. **Non-modal.** `tools/check_editor_ui.py` enumerates `editor/ui/*.py` with
   `os.listdir` — **no registration step** — and fails on any
   `QMessageBox.x(` or `.exec()`. `ask.py` is the only exempt module and its
   modal set is pinned to **exactly** `["question", "exec:dialog"]`, so adding
   a picker there turns that assertion red. `#TAG:TilesetImportDialog` is the
   working precedent for a complex non-modal window that passes the census.
2. **Law 12 sequence, inherited not re-solved.** Every rebuilt body goes
   through `#TAG:qt_takewidget_sequence`:
   `takeWidget()` → `setParent(self)` → `hide()` → `deleteLater()` →
   `setWidget(new)`. Never `setParent(None)`.

A control that cannot act is **greyed with its reason in the tooltip**, never
present-and-refusing — the `__sync_buttons` rule already followed everywhere.

### 5.1 The tileset editor — `editor/ui/tileset_window.py`

`TilesetWindow(QMainWindow)`, opened by `EditorWindow.open_tilesets()`
following the `#TAG:DatabaseWindow` recipe verbatim: lazily constructed,
`command_requested.connect(self.run)`, `reveal_requested.connect(self.reveal)`,
one line in `refresh_all` under `__safely`, and **its own Undo/Redo
`QAction`s forwarded to the parent** (Qt shortcuts are per-window;
`check_editor_ui` already asserts this for Database).

Reached two ways: `Tilesets ▸ Edit tilesets…` and the palette section
header's existing context menu, which gains one entry. **Both, because the
capability must be reachable from where the author's cursor already is.**

`QSplitter(Qt.Horizontal)`, sizes `[240, 620, 300]`, stretch `(0, 1, 0)` —
`#TAG:TablePage`'s proportion, so the data screens look like one product.

```
┌ Tilesets ─────┬─ TileA2 ─── zoom [1 2 4] ─────────────┬─ Tile 194 ──────────┐
│ TileA2   768  │  ▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦      │ local id  194       │
│  3 retired    │  ▦▦▦▦▦▦▦▦▦▦▦▦▦▦▩▩▦▦▦▦▦▦▦▦▦▦▦▦▦▦      │ gid       195 (test)│
│  test, cave   │  ▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦▦      │ class     floor     │
│  overworld    │   ▩ = retired    ▢ = free row         │ mask      ▨ down    │
│ Clutter 1024  │                                       │ status    live      │
│  test         │                                       │                     │
│ collision 17🔒│                                       │ USED BY             │
│               │                                       │  test/Floor    441  │
│ [+ New from   │                                       │  cave/Floor     22  │
│  image…]      │                                       │                     │
│ ─────────────  │                                       │ GROW HEADROOM: 0    │
│ [Grow…] [Link…]│                                       │ blocked by Clutter  │
│ [Rename…]      │                                       │  at firstgid 769    │
│ [Retire] [Trim]│                                       │ [Retire] [Clear]    │
└───────────────┴───────────────────────────────────────┴─────────────────────┘
│ note for the AI about tileset:TileA2…    [change ▾] [Stage] [Ask] 0 here/2  │
```

**Left pane** — every tileset in the **project**, not the open map, with its
maps and its scenes underneath (`Project.tileset_usage`). The
`collision` sheet is marked **🔒** and its Grow / Retire are greyed with the
real reason: *"this sheet's ids are the mask alphabet — `#TAG:MASK_DOMAIN`
cannot grow, it is the physical layout of Collision.png."*

**Centre pane** — the sheet, drawn by the incumbent `#TAG:TilesetAtlas` into a
hand-composited `QPixmap` in a `QScrollArea`, addressed by
`section(name).rect(column, row)`, **never by absolute pixel position** — the
`_PaletteSurface` idiom, so `check_editor_ui`'s existing
`pick_tile(window, tileset, column, row)` helper drives it unchanged.

**Right pane** — an `InspectionView(show_sources=False)` fed by a new
`"tileset"` arm in `#TAG:describe`'s `_BUILDERS`. **The properties panel is
free**; the same renderer already draws `BehaviorParam` and `Capability`.

The line that makes the screen safe is **`GROW HEADROOM: 0 — blocked by
Clutter at firstgid 769`**: `min(tileset_headroom)` across every referencing
map, **plus the name of the map or sheet that limits everyone**. A shared
asset's affordances are bounded by its worst referencing map, and naming which
one turns a refusal into a fixable situation.

**Adding a tile.** `+ New from image…` opens the incumbent
`#TAG:TilesetImportDialog` unchanged. `Grow…` opens **the same dialog**,
pre-loaded with the current image, crop pre-set to the existing region, and
**the rubber band's left and right snap zones disabled so the width cannot
change**. The dialog physically cannot express an illegal growth;
`#TAG:growth_is_rows_only`'s refusal stays as the second gate for the scripted
route. That is the only place in this spec where a law is enforced by
geometry instead of by a message after the fact.

**Removing a tile that is painted on three maps.** `Retire` opens a
**non-modal pane inside the window** (not a dialog — the census forbids it,
and the pane needs a table `QuickForm` cannot render):

```
  Retire TileA2 tile 194  (gid 195)

  Nothing is renumbered. Every other tile keeps its local id in every map,
  in every scene, and in TileA2.blitmask. The sheet's pixels are untouched.

  463 cells across 2 maps paint this tile:
      test / Floor   441        cave / Floor    22

  Those cells become:   ( ) empty   (•) tile 193   [ pick from the sheet ]

  This is ONE undo step:
      tileset.tile.retire   TileA2 194
      map.tile.set_many     map:test/layer:Floor   441 cells
      map.tile.set_many     map:cave/layer:Floor    22 cells

                                       [ Cancel ]  [ Retire ]
```

One click → one `run(...)` → one `Transaction` → **one Ctrl+Z**.

**Empty and broken states — four, because this is where the screen earns its
keep.** Each surfaces a refusal that today fires as an error or is completely
silent:

| state | what the centre pane shows |
|---|---|
| **no tilesets** | `This map has no tilesets. Import one to start painting.` and one enabled button |
| **art missing** | The atlas draws its deterministic golden-ratio swatches **plus a banner**: `Art not found: data/graphics/… — showing placeholder colours` and a `Reveal` link. **Today this is entirely silent** — `TilesetAtlas` does not even report it as missing. This is a bug fix delivered inside a feature |
| **external `<tileset source=…>`** | `External tileset — its extents live in x.tsx, which this editor does not open.` Grow and Retire greyed with that reason. `#TAG:MapDocument.require_known_extents` already refuses; the screen *shows* the refusal instead of firing it |
| **collection-of-images** | `This tileset stores one image per tile. The editor draws placeholders and cannot grow it.` — the measured editor/engine divergence, surfaced instead of hidden |

**Undo:** every control emits one `Command` with an exact inverse; the retire
pane emits a list in one `run`.

### 5.2 The scene screen — `editor/ui/scenes.py`, `SceneDock(ScopedDock)`

A dock, not a window: it is a list plus an inspector, which is what a dock is
for, and being in `EditorWindow.docks` is what gets it refreshed, re-aimed,
strip-refreshed **and a View-menu entry** — a dock missing from that roster is
a panel the author cannot get back once closed.

- **Top:** `QListWidget` of scenes. `+ New…`, `Duplicate`, `−`.
- **Middle:** the selected scene's map slots as a `QTreeWidget`, ordered, each
  row `map · entry`. `+ Map slot…`, `−`, `▲ ▼`. Order is the hierarchy.
- **Bottom:** an `InspectionView` over a new `"scene"` `_BUILDERS` arm —
  `title`, `entry_map` (closed combo over the slots), `loadouts`,
  `on_enter`/`on_exit` (closed combos over scripts), `next` (multi), and the
  three `controls` axes as **three-state** choices (*leave alone / true /
  false*), because collapsing `None` to a checkbox loses a real value.

**Empty/broken:** no `data/project/scenes/` → `No scenes yet. A scene groups
maps and owns the variables its scripts share.` with one `+ New…`. A slot
naming an absent map → a **hard `RuleViolation`** in Problems with
`fix="project.map.add"`.

**`project.map.add` is a hard prerequisite of this screen**, not an
enhancement: `config/maps.json` holds one map and **no verb writes it**
(`grep -n "config/" editor/core/verbs.py` → nothing). Without it the screen
ships an unfixable red row.

### 5.3 The event editor — `editor/ui/script_window.py`

`ScriptWindow(QMainWindow)`, `DatabaseWindow` recipe again, opened from
`Events ▸ Edit scripts…`. Four panes.

```
┌ Scripts ──┬ Page 1 ▸ Page 2 ▸ [+] ────────────────┬ ▸ say ───────────┐
│ keeper_   │ WHEN  gate_open is false              │ who  [Keeper   ] │
│  gate  ●  │ TRIGGER use  PAYLOAD keeper  ONCE ☐   │ text [The north  │
│ gate_open │ HOLD steerable=off                    │       gate is…]  │
│ chest  ◆  │ ──────────────────────────────────    │                  │
│           │ ▸ hold  steerable off                 │ CORE — portable  │
│ ● portable│ ▸ say   "The north gate is sealed."   │ Runs unchanged   │
│ ◆ topdown │ ▾ if    coins ≥ 100                   │ in every mode.   │
│           │     say "Unless you can pay."         │                  │
│ [+ New…]  │     set coins by add -100             │ [Insert after ▾] │
│           │   ▾ else if  coins ≥ 10               │                  │
│           │       ask "Half now?"                 │                  │
│           │   ▾ else                              │                  │
│           │       say "Come back with coin."      │                  │
│           │       stop                            │                  │
└───────────┴───────────────────────────────────────┴──────────────────┘
```

- **Pages are a `QListWidget`, not a tab bar.** RPG Maker's numbered tabs stop
  being readable past six. Each row shows its `when` summary and trigger.
  **List order IS evaluation order**, so reordering is a real semantic edit.
- **The body is a `QTreeWidget`**, `setHeaderHidden(True)`,
  `setUniformRowHeights(True)`, built the way `#TAG:HierarchyDock` builds the
  only other real tree here — and using its identity trick: **every row stores
  its node `id` as a STRING in `Qt.UserRole`**. A command rebuilds the widget
  wholesale, and an index-keyed selection slides onto the wrong row.
  `Else if` / `Else` are **drawn arm headers**, not stored nodes; there is no
  `Branch End` row because the tree has real containment.
- **Every row whose op is not core carries a loadout chip in `palette(mid)`.**
  A script with no chips ports unchanged — the portability question answered
  by *scanning*, not by opening a dialog.
- **The right pane is an `InspectionView`** over a `"script"` `_BUILDERS` arm.
  Each argument is an `#TAG:Field` whose `emit` closure returns
  `script.node.set`. Free, because `OpParam` is `BehaviorParam` (§5b.1).

**The picker — `editor/ui/op_picker.py`, non-modal, docked under the body.**

```
 [ search…                              ]   ☑ core only
 CORE      [say] [ask] [set] [wait] [hold] [release] [call] [stop]
 ─────────────────────────────────────────────────────────────────
 TOPDOWN_RPG (this project)  [actor_set] [party_add] [party_remove]
                             [give_item ⚠]
 PLATFORMER (not this project)  [launch] [set_gravity]      ← greyed
     "needs genre platformer; this project is topdown_rpg (Project ▸ Genre…)"

 give_item — put an item in the party's inventory.
 needs-host: table:items is declared by the pack and no project file
 has created it. Authoring works; nothing runs yet.
```

- Built as the `_PaletteSurface` idiom — a composited `QPixmap` grid in a
  `QScrollArea` with `rect(row, column)` — which is how a picker grid is built
  here and how `check_editor_ui` already drives one.
- **A search field**, which is the single biggest improvement over RPG Maker's
  three tabbed grids and costs one widget.
- **`☑ core only`** is the portability filter.
- **Core is always the first section and its buttons carry no badge — the
  absence IS the signal**, which is the right way round, because portability
  is the default.
- **A `needs-host` op is offered with a ⚠ and its measured reason**, never
  hidden. **A loadout the scene does not declare is greyed with its reason**,
  never absent — hiding it makes the author think it does not exist.

**Empty/broken:** no script attached → the window will not open; the dock says
`This object has no script.` with `New…`. An empty page body → one dim
placeholder row `(nothing yet — press Insert)` that is not a node and cannot
be deleted. **An unknown op in a hand-edited file → the row draws red with the
compiler's message in the tooltip, and the window still opens** — refusing to
open a broken script is how a typo becomes unfixable.

---

## 5a. THE COMMUNICATION RELAY

> *"the developer once using the engine will be encouraged to piecemeal the
> process through the communication relay boxes"*

The end state: **a developer opens a box, states a small thing, and gets a
scoped change back, without either side loading the whole tree.**

### 5a.1 What already exists — do not build a chat panel

| built | measured |
|---|---|
| `#TAG:PromptStrip` — 104 lines, **eight instances**, each already scoped by its panel, already staging a `Note`, already reaching `refresh_manifest` | `wc -l editor/ui/prompt.py` |
| `#TAG:write_bundle` → a dated directory of BRIEF / REQUEST / RULES / CONTEXT / COMMANDS / manifest.json | read at `#TAG:write_bundle` |
| `#TAG:parse_response` → `Command.from_json` → `EditorWindow.run` → **one `Transaction`** | `tools/check_editor.py` proves *"one undo took the whole response back"* |
| `#TAG:CommandStream.apply` atomic with reverse-replay rollback | `grep -n "rolled_back" editor/core/commands.py` |
| `#TAG:Verb.validate` — a **non-mutating** scope-and-argument check | read this pass |

**The chain is real and complete. The underbuilt part is not the widget — it
is the GRAIN.** One global manifest ships one bundle carrying mostly-constant
context. `PromptStrip` gains **one button**, and nothing is written beside
`prompt.py`.

| button | meaning |
|---|---|
| **Stage** | unchanged — contribute to the global manifest, ship later. The full-view grain, kept, because a cross-cutting change genuinely needs it |
| **Ask** | **ship a ONE-NOTE bundle scoped to this panel's scope, immediately.** No manifest, no title dialog. That is the piecemeal gesture |

```python
def ask(self, scope: Scope | str, text: str, kind: str = "change") -> Bundle:
    """One note, one bundle, scoped. The piecemeal door."""
    return write_bundle(self.project, Manifest(notes=[Note(scope, text, kind)]),
                        scoped=True)
```

Twelve lines beside `Session.ship`, **Qt-free**, so the request half is
drivable from `open_here()` with no display.

**Boxes, plural, one per scope**, because they already are. Eleven after this
spec lands (seven docks + Database + Scenes + Scripts + Tilesets), **zero new
widget classes**.

### 5a.2 The scoped context payload — the measured heart

Measured this pass, and RE-MEASURED on 2026-09-04 once the fourteen
`script.*` verbs of section 6.4 had landed — every number below is the second
reading, which is why they are larger than the ones this argument was first
made with:

```
.venv/Scripts/python.exe -c "import editor.core.verbs; from editor.core.commands import describe_all; print(len(describe_all()))"
```

| part | bytes | ≈tokens |
|---|---:|---:|
| `COMMANDS.md` — all **51** verbs | **32,122** | 8,030 |
| `RULES.md` — the whole genre pack | 16,395 | 4,099 |
| `BRIEF.md` | 2,373 | 593 |
| `manifest.json` + `REQUEST.md` + `CONTEXT.md` | ~898 | 226 |
| **a bundle written today** | **~51,788** | **~12,947** |

**Two files are 94% of it.** The lever is one keyword on one existing
generator: `describe_all(*, title=…)` gains
`scopes: tuple[Scope, ...] = ()`, filtering by `Verb.scopes` through the same
`Scope.matches` test `Verb.validate` already uses. **When `scopes` is empty the
output is byte-identical**, so `check_docs`'s regeneration of
`docs/COMMANDS.md` cannot regress.

Measured verb reach and the real scoped slice:

| scope | verbs | scoped `COMMANDS.md` |
|---|---:|---:|
| `map:test/layer:Floor` | **8** | 5,582 B ≈ **1,396 tok** |
| `map:test/layer:Objects/object:1` | 9 | 5,132 B ≈ 1,283 tok |
| `map:test` | 9 | 12,310 B ≈ 3,078 tok |
| `table:actors/row:hero` | **2** | 1,323 B ≈ **331 tok** |
| *(unscoped)* | 51 | 32,122 B ≈ 8,030 tok |

**A literal scoped bundle for `map:test/layer:Floor`:**

```
editor/requests/0007-widen-the-shoreline/
  BRIEF.md        2,829 B   ~707 tok   the PROTOCOL; unchanged, must stay complete
  REQUEST.md        230 B    ~58 tok   the one note
  CONTEXT.md        286 B    ~72 tok   describe_scope(map:test/layer:Floor), live
  COMMANDS.md     5,582 B ~1,396 tok   the 8 this scope accepts, of the whole vocabulary
  manifest.json     617 B   ~154 tok   + "scoped" and "verbs"
  ───────────────────────────────────
  TOTAL           9,544 B ~2,386 tok        (vs ~12,947 tok unscoped -- 5x)
```

**`RULES.md` is DROPPED, not trimmed**, for a scope a genre pack's layer and
table rules say nothing about. Shipping 4,099 tokens of irrelevance to be safe
is the habit this feature exists to break; if that turns out wrong the fix is a
rule that mentions the scope, not a bigger payload.

**How it stays true rather than drifting.** Every part is generated **at the
moment of the ask**, from live objects: `describe_all(scopes=(scope,))` from
the live `_REGISTRY`, `describe_scope(project, scope)` from the live
`Project`, each verb's argument table from `Param.doc` verbatim. A bundle is an
**immutable dated snapshot**, so there is no invalidation problem, and a stale
command hits a real refusal on apply and the whole batch rolls back — **no
optimistic-concurrency machinery is needed and none is added.**

> **The one hand-written part is `BRIEF.md`, and it may contain statements
> about the PROTOCOL only — never a claim about what the code does.**

That restriction is not aesthetic. `docs/BEHAVIORS.md`'s hand-written preamble
has carried **two** lies while matching its generator byte for byte
(`docs/NEXT.md` entry 1). A protocol claim is falsified the moment the protocol
fails; a code claim is falsified silently.

**The empty-vocabulary case, decided.** Measured: `assets` and `genre` scopes
match **zero verbs**, so a box aimed at one would ship a vocabulary the
responder structurally cannot answer with. **`Session.ask` refuses that ship,
naming the scope and the fact that no verb accepts it** (law 7 — decide it, do
not default into it).

### 5a.3 The request and the response, literally

`manifest.json` gains two keys:

```json
{
  "id": "0007-widen-the-shoreline",
  "genre": "topdown_rpg",
  "root": "S:/Dropbox/Pyoneer",
  "created": "2026-09-03T14:02:11",
  "scoped": "map:test/layer:Floor",
  "verbs": ["map.layer.remove", "map.layer.set", "map.layer.unset",
            "map.object.add", "map.object.restore",
            "map.tile.fill", "map.tile.set", "map.tile.set_many"],
  "title": "widen the shoreline",
  "notes": [{"scope": "map:test/layer:Floor", "kind": "change",
             "text": "make the shoreline two tiles wider",
             "created": "2026-09-03T14:01:48"}]
}
```

`"verbs"` is the machine-readable half of the sliced `COMMANDS.md`, and it is
what makes the payload **checkable**.

**`response.jsonl` is UNCHANGED.** `#TAG:parse_response` is green, tolerates
blank lines and a wrapping fence, and raises with a **line number** on bad
JSON, a JSON array, a bad command and zero commands.

```jsonl
{"verb":"map.tile.set_many","scope":"map:test/layer:Floor","args":{"tiles":[[12,4,65],[13,4,65]]}}
{"verb":"map.tile.set","scope":"map:test/layer:Floor","args":{"x":14,"y":4,"gid":65}}
```

**A REFUSAL is a SIDECAR, `reply.json`, with NO `response.jsonl` at all:**

```json
{
  "format": "pyoneer.relay.reply",
  "version": 1,
  "answer": "",
  "refused": "Floor is 100 cells wide and the shoreline runs to x=99. Widening it two tiles needs the map resized first, and no verb in this vocabulary resizes a map.",
  "unresolved": ["should the shoreline wrap, or should the map grow?"],
  "commands": 0
}
```

**A sidecar, not a new line shape, because `parse_response` must not learn a
second grammar.** It is the one green, heavily-checked parser in the chain.

A successful reply is the same file with `answer` set and `refused` empty.

**The BACK channel — `refusal.json`, written by the editor into the bundle on
apply failure:**

```json
{
  "format": "pyoneer.relay.refusal",
  "version": 1,
  "failed_line": 2,
  "message": "map.tile.set_many: argument 'tiles' wants list, got str",
  "rolled_back": true,
  "applied": 0
}
```

One file write in an existing `except` arm, and it turns the relay from a
one-way pipe into a loop. Today **nothing is written back**, so the responder
learns a rejection only if a human retypes it.

### 5a.4 What a PARTIAL application looks like — it does not exist

**Structurally.** `#TAG:CommandStream.apply` builds one `Transaction` and on
any failure replays the collected inverses in reverse and raises
`PyoneerCommandApplyError(rolled_back=…)`. `tools/check_editor.py` already
proves a mixed good/bad response leaves the good row un-landed.

So `"applied": 0` is not a policy, it is what the stream did. And if the
rollback itself fails, the existing message already appends
*" -- AND THE ROLLBACK FAILED; in-memory state is partially applied, reload
the project from disk"*.

**There are no per-command checkboxes in the review, deliberately.** A
checkbox is a partial apply, and a hand-picked subset is a different response
the AI did not write and cannot be held to. The way to say *"the third one is
wrong"* is a note on that scope, shipped back.

**The third failure case is real and invisible to the machine:** a response
that applies **fully** and does **less than asked**. Rollback cannot see it,
`validate` cannot see it, a diff cannot see it. `BRIEF.md` already instructs
the responder to write `NOTES.md` and **nothing reads it**. **The relay reads
it**: after a successful apply the box shows `NOTES.md` inline, one paragraph,
above the input line. That is the only place a human learns *"I did four of
your five things"*, and it retires a measured dead file.

### 5a.5 Review before it applies

The incumbent spine is right and is kept: a `QFileSystemWatcher` on
`editor/requests/`, `QTimer.singleShot(400, …)` as a half-written-jsonl guard,
and a **Problems row, never a modal**.

The review moves into `#TAG:ManifestDock` — already in `self.docks`, already
grouping notes by scope, already the editor's one `confirm` caller — as an
**Incoming** section above the staged one:

```
 INCOMING · relay 0007 · map:test/layer:Floor            [Open ⧉]
 "Widened the shoreline two cells east across rows 3-9."

 ▸ map.tile.set_many   map:test/layer:Floor   24 tiles
     (12,4): 0 → 65      (13,4): 0 → 65      (14,4): 0 → 65   …
 ▸ map.tile.set        map:test/layer:Floor   1 tile
     (14,4): 65 → 66

              [ Discard ]        [ Apply — 1 undo step ]
```

- **What is shown:** `reply.json`'s `answer` as prose, then every command as
  one row rendered through the verb's own `Param.doc` — not raw JSON, and
  **not truncated at 20** as today's `confirm()` string is.
- **What is diffed, and this is the best part because it costs nothing:**
  expanding a row shows **before → after, computed by asking the verb for its
  own inverse.** Every verb in this editor already computes its exact inverse,
  and the inverse **is** the before-state. `map.tile.set_many` expands to
  `(x,y): old gid → new gid`; `map.tileset.grow` shows the four before/after
  values. Pure data, cannot fail, mutates nothing, and it scales to every verb
  added later for free.
- **A green/red verdict per row** from `#TAG:Verb.validate`, which is
  non-mutating — a genuine free dry run for scope and argument errors, with
  the exact refusal message on the red ones.
- **A `refused` reply shows at the top in the Problems colour with Apply
  DISABLED** and the responder's sentence in the tooltip.
- **Non-modal**, so `check_editor_ui`'s pinned modal counts are untouched.

### 5a.6 The one-undo-step guarantee

`Apply` calls the incumbent:

```python
window.run(commands, label=f"relay {identifier}", source=f"response:{identifier}")
```

**One `run` → one `Transaction` → one entry on `CommandStream.done` → one
Ctrl+Z takes the whole response back.** That is not a new guarantee; it is
`apply`'s existing contract, already proven. **The relay inherits it by using
the door rather than building one.**

`Session.apply_response` gets its **first caller**, and
`EditorWindow.apply_response` is collapsed onto it — two implementations of
one path become one (law 2's corollary at method scale).

`Manifest.from_json` gets its **first caller** too: the manifest persists to
`editor/requests/manifest.json` on every stage and is read at `Session.open`.
A piecemeal workflow that spans sessions is impossible while staged notes die
with the process.

### 5a.7 How the relay meets the event system

**They are the same shape in two respects and must stay apart in the third.**

| | event script | relay response | editor verb |
|---|---|---|---|
| format | JSON | JSON Lines | JSON args |
| vocabulary | `OP_REGISTRY` | `_REGISTRY` | `_REGISTRY` |
| doc | `docs/EVENTS.md`, generated, measured column | `docs/COMMANDS.md`, generated | same |
| unknown name | **raises**, names the known set | **raises**, names the known set | same |
| addressing | page `id` + node `id` | `Scope` | `Scope` |

**Same — an event script is EDITED by relay commands.** `script.node.add` is a
`Command` like any other, so *"write me the shopkeeper's dialogue"* is a relay
whose response is a jsonl of `script.node.add` lines, previewed as a diff,
applied as **one undo step**, and rendered in the tree the author is looking
at. **That is the payoff of the whole spec: an AI authoring game logic and a
human dragging a row are literally the same transaction type** — CLAUDE.md's
third sentence made real.

**Apart — a `Command` mutates the PROJECT at authoring time and returns its
inverse; an op mutates the GAME at run time and does not.** They must never be
one vocabulary. An op that could edit the project would put the running game
in the editor's undo stack; a `Command` that could run at play time would need
an inverse for *"the player took damage."* **Two registries, two generated
documents, one discovery protocol, one relay carrying both.**

### 5a.8 The offline story

1. **Law 2.** Every op, the interpreter, both readers live in `scripts/`. The
   relay lives entirely in `editor/core/request.py`, `editor/core/session.py`,
   `editor/ui/prompt.py` and `#TAG:ManifestDock`. `tools/check_editor.py`
   already walks `scripts/` failing on any `import editor` — the existing gate
   covers the new modules with no change, and `python main.py` on a clone with
   `editor/` deleted loads scenes and runs scripts.
2. **Law 13.** No dialog anywhere in the path. The review is a dock section;
   all new `editor/ui/*.py` files are auto-enrolled by the `os.listdir` census
   and contain zero `QMessageBox.x(` and zero `.exec()`.
3. **Headless, and it is not optional** — an unchecked screen is how this
   repository ships unreachable layers. `Session.ask`, `write_bundle`,
   `parse_response` and `Session.apply_response` are all Qt-free and drivable
   from `open_here(genre_id)`. The Qt half runs offscreen with
   `modals() == []` asserted on the routine path.

---

## 5b. THE COMMAND VOCABULARY

> *"We should start with a small handful of universally useful events so we can
> port them between game mode types, and include other events for specific game
> mode loadouts as well."*

This is the section the author asked for by name, and it outranks the rest of
the spec.

### 5b.1 Where a definition lives

**In `scripts/`, in a registry that is the behavior registry's twin. Never in a
genre pack.** Law 2 forces it: a pack lives at `editor/genres/`, so a command
whose *body* lived there would be unrunnable on a clone with `editor/` deleted.

```python
@dataclass(frozen=True)
class OpSpec:                                     # scripts/game/flow/ops.py
    name: str                                     # "say" -- FILE FORMAT, never renamed
    summary: str
    run: Callable[["ScriptRun", Mapping], Any]
    params: tuple[BehaviorParam, ...] = ()        # THE SAME CLASS, IMPORTED
    loadout: str = "core"                         # "core", or a genre id
    yields: bool = False                          # does it stop this frame's run?
    status: str = "live"                          # STATUSES, IMPORTED
    example: str | None = None
```

**`params` is `tuple[BehaviorParam, ...]` — the frozen dataclass from
`#TAG:BehaviorParam`, imported, not re-declared.** Its contract is already
exactly right: it **raises** rather than falling back, it tests `bool`
**before** `int` (in Python `True` *is* an int), it widens `int`→`float`
because Tiled writes `900` for a float, and it checks `choices`. Taking the
class buys three things at once — an op param and a behavior param **cannot
drift**, `InspectionView` already renders it so §5.3's argument form is
**free**, and the generated doc's param table is the same generator. Writing a
new `EventParam` "shaped verbatim like `BehaviorParam.coerce`" is the move that
cost 425 duplicate lines.

`status` is **imported** from `#TAG:STATUSES`
(`("live", "authoring-only", "needs-host")`, measured) for the same reason.

`resolve(name)` **raises `PyoneerAssetMissingError`** and never falls back —
`#TAG:registry.resolve`'s precedent, and its reason: an unknown token that is
skipped *looks like the feature working*.

### 5b.2 How a pack selects — one key, one parser arm, zero new mechanism

**A genre pack declares which loadouts it GRANTS. It never defines a
command.** `editor/genres/topdown_rpg/genre.json` gains one array:

```json
"event_loadouts": ["core", "topdown_rpg"]
```

parsed by a new `_event_loadouts(raw, path)` in `editor/core/genre.py` and
validated through **`ops.validate_loadouts`** — *the engine's own judge, not a
second copy of it*, which is the comment already sitting above
`_object_classes`'s call to `behavior_registry.validate_list`. A pack naming an
unknown loadout **raises `PyoneerGenreError` at pack load**, identical timing
and identical failure mode to today's bad-behavior-token raise, *"rather than
poisoning every map made from it."*

**Granting a loadout NAME, not an op list**, deliberately: an op list in a pack
is a second place the membership of a loadout is written, and it can disagree
with the registry silently.

### 5b.3 Namespacing — FLAT, with the loadout as a FIELD. Decided once.

The four designs disagreed here more than anywhere else. **The decision is
flat**, and it is decided by the incumbent rather than by taste:

```
grep -n "genres:\|status:" scripts/game/behavior/base.py
```

**`#TAG:BehaviorSpec` already carries `genres: tuple[str, ...]` as a FIELD, not
a prefix on the name.** Behavior tokens are flat. That is this repository's
existing answer to exactly this question, and the ACTIVE WARNING says extend
the incumbent, not invent beside it.

The decisive argument on top of that: **a dotted name freezes the stratum into
the permanent string.** Promoting a command from a loadout into core — which
*will* happen the second time two genres need the same thing — becomes a
**rename**, which law 8 forbids. A design that makes its own most likely future
edit illegal has a bug in it.

**The cost, named and paid three ways.** Dotting would have made portability
visible in the raw JSON. Instead:

1. **`"loadouts": ["core"]` at the head of the script file.** A script that
   stops being portable is a **one-line diff at the top of the file**, where a
   reviewer looks — strictly more legible than a prefix change scattered
   across forty nodes.
2. **`docs/EVENTS.md` has a Loadout column** (§5b.6).
3. **The picker badges each button and the tree chips each row** (§5.3).

**And it is checkable, which a prefix convention is not:** a check asserts
every op in a script is in a loadout the script declares, and every loadout the
script declares is granted by the scene.

**Collision** — two packs both wanting `jump` — is refused at registration:
`register` raises on a duplicate name, naming both loadouts, and the second one
picks a different word. That is one refusal at registration against a permanent
rename hazard on every promotion.

### 5b.4 THE CORE SET — eight ops

The test each member had to pass: **does it mean the same thing in a top-down
RPG, a platformer, and a visual novel? A script written from core alone runs
unchanged when the game mode changes.**

Control flow (`if` / `elif` / `else`, `while`, `break`) is **schema, not
vocabulary** — a node shape, as in most languages — so it costs nothing
against the eight.

| # | name | arguments | top-down RPG | platformer | visual novel | why it is core |
|---|---|---|---|---|---|---|
| 1 | **`say`** | `text`, `who=""` · *yields* | NPC line in a box | sign / barker line | the entire medium | Every genre shows text and waits. The host exists: `GameWindow.open()/close()` is pure duck typing and `demos/narrative.py`'s `StoryBox` is a working instance |
| 2 | **`ask`** | `prompt`, `options: list[str]`, `into` · *yields* · **`status="needs-host"`** | dialogue choice | signpost choice | the core verb | A branch with nothing to branch *on* is not a branching system. Ships **declared and honestly measured as unwired** — `scene_flow.py` states the blocker: *"no widget in this engine reports a click to anything"* |
| 3 | **`set`** | `var`, `to`, `by="assign"\|"add"` | quest flag, gold | checkpoint, lives | route flag | State is universal. `by:"add"` is there so `coins − 100` is one invertible node rather than a read-modify-write pair, and because there is no expression language by design |
| 4 | **`wait`** | `ms` · *yields* | beat before a reveal | beat before a door | beat before a line | Pacing is what makes a script feel authored. `FlowStep.hold_ms` already exists, already converts through `MS_PER_DELTA`, already auto-advances on the frame it elapses **and not before** |
| 5 | **`hold`** | `steerable`, `enabled_inputs`, `simulated` — each `bool\|null` | freeze during dialogue | freeze mid-platform | freeze (already still) | Without it, `say` in a platformer means the player walks off a ledge mid-sentence. Writes through the shared `AgencyHold`; `null` = do not touch this axis |
| 6 | **`release`** | — | give control back | give control back | give control back | The other end of `hold`. **Two names because shipping either alone is a bug.** Restores **the recorded value, never `True`** |
| 7 | **`call`** | `script` | shared shop intro | shared checkpoint beat | shared chapter header | The author asked for scripts *"reusable scene-by-scene"*; without `call` that is a filesystem claim with no runtime meaning. Depth-capped at 16, raising with the chain |
| 8 | **`stop`** | — | end the conversation | end the beat | end the scene | Early exit from inside a nested arm. Not expressible any other way once `loop` is refused, and every early-out otherwise becomes an `else` swallowing the remainder |

**Eight.** A ninth would have to beat the weakest of these.

**`enter_scene {scene}` is declared core and has a SCHEDULED BIRTH DATE.** It
is portable — every mode changes screens — but scene switching is measurably
broken today (§1.3: four separate faults), so it **registers only in the stage
that fixes `set_scene`** (Stage 6). Shipping it earlier would be an op whose
`run` does nothing, which is the defect `play_sound` is rejected for below.
And it takes **no positional argument** — an `entry`/`at` spawn point is a
place-to-stand assumption a visual novel has nothing to put in; the scene file's
`entry_map`/`entry` owns that.

### 5b.5 REJECTED from core — with the reason for each

| rejected | reason |
|---|---|
| **`loop` / `break`** | **The strongest rejection here.** A script runs on the called side inside `post_update`. An unbounded loop is a frozen frame — the same failure law 13 paid 40 silent minutes for, one layer down. `wait` yields; `MAX_STEPS_PER_FRAME` raises. A bounded `repeat n` is a defensible **later** addition; an unbounded loop is not, at any stratum. *(`while` exists in the schema and is bounded by the same raise.)* |
| **`label` / `jump_to_label`** | `goto`. With `if`, `call` and `stop` there is no expression a label buys, and a jump makes execution **un-renderable as a tree**, which breaks §5.3's entire display model. Adding it later costs one op; removing it later costs every script |
| **`note` / `comment`** | A node whose runtime is a no-op **can never be measured as integrated**, which makes §5b.6's column vacuous — law 5 inside the safeguard. Every node already accepts a `"note"` key |
| **`set_switch` distinct from `set`** | RPG Maker separates boolean switches from numeric variables. One `vars` store with a **declared type per key** is strictly more expressive and one fewer concept |
| **`control_self_switch`** | A self-switch is `set` with a `local.` name. Two spellings of one fact is the shape law 8 punishes |
| **`control_timer`** | `wait` plus a var expresses it. A second clock is a second home for one fact and would need its own ms↔delta conversion (law 9) |
| **`input_number` / `select_key_item`** | The same missing host as `ask`, with none of `ask`'s necessity. A second `needs-host` with no branch to feed is a promise, not a command |
| **`show_scrolling_text`** | A presentation variant of `say` for a widget that does not exist. There is not even word wrap: `TextComponent.prepare_text` is one `font.render` of one string and `auto_fit` answers overflow by shrinking the font |
| **`move_to` / `set_move_route`** | RPG Maker's most-used feature, and **not core**: *"move to (x, y)"* means a grid step in top-down, a velocity in side-on, and nothing in a VN — so a script using it does **not** run unchanged when the mode changes, which is the definition of core membership. → loadout |
| **`change_party_member`** | Named in the ask as a probable non-member. It is one: a platformer has no party. → loadout |
| **`change_gold` / `change_items` / `change_weapons` / `change_armor`** | Inventory presumes `table:items` / `table:equipment`, which **only the `topdown_rpg` pack declares**. → loadout |
| **`change_hp` / `change_exp` / `change_level` / `recover_all`** | `hp` is an `actors` column **because that genre put it there**. And the two shipped packs **already disagree about a column name** (`speed` vs `move_speed`, stated in `topdown_rpg`'s own field doc) — **that is the mechanical test for core membership: if the two packs already spell it differently, it is not core** → loadout, as one general `actor_set` |
| **`set_graphic` / `walking_anim`** | The incumbent for this is `pyoneer_behaviors` + `animation_drive`; a script command would be a **second way to do what the behavior list does**, and law 8 makes both permanent. Also `#TAG:GameAnimationHandler.__init__` plays `idle_down` unconditionally at construction — a live KNOWN GAP a portrait-only sheet hits first |
| **~~`play_sound` / `music`~~ -- LANDED 2026-09-04** | The day arrived. `scripts/core/audio.py` is the subsystem; `play_sound` and `play_music` are core, live, and probed by `tools/check_event_docs.py`. What is still true is the sentence underneath: an op whose `run` does nothing is the defect these two were kept out for, and `enter_scene` is the one the rule still points at. What they are NOT yet is REACHABLE -- nothing in the shipped game loads a script, so the demo makes its noise through an action route instead |
| **`tint_screen` / `shake_screen`** | The renderer is a sorted blit queue with **no post-process stage**. Same reason |
| **`spawn` / `despawn`** | `#TAG:SPAWN_REGISTRY` has **exactly one usable entry (`GamePlayer`)** and four advertised-but-absent ones. A core op that can only spawn the player is not a core op |
| **`script` (raw code)** | Arbitrary code in a JSON document makes every check vacuous (law 5) and turns a relay response into remote code execution. **Refused permanently** |

### 5b.6 ONE WORKED LOADOUT — `topdown_rpg`

Registered in `scripts/game/flow/ops_topdown.py`, imported at the bottom of
`ops.py` — a registry populated by importing the modules that declare into it,
which is how `registry.py` already gets its specs. Granted by
`editor/genres/topdown_rpg/genre.json`'s `"event_loadouts"`. Built against the
tables that **actually exist on disk** (`data/project/tables/actors.json`) and
read through `#TAG:scripts/loaders/table_file.py`, so nothing here is a
promise.

| name | arguments | status | why it is NOT core |
|---|---|---|---|
| `actor_set` | `actor`, `column`, `to`, `by="assign"` | live | One op for the whole `change_hp`/`change_exp`/`change_level` family. **`column` is validated against the live `actors` table at SCRIPT LOAD**, so `"hpp"` raises before a frame — `#TAG:actor_row`'s refusal shape exactly. Not core: a platformer's `actors` table has different columns |
| `actor_has` | *(condition form)* `{"actor":"1","column":"hp","at_least":1}` | live | The loadout's one condition extension, reusing the six core comparators and adding no seventh |
| `party_add` | `actor` | live | Party is an RPG noun |
| `party_remove` | `actor` | live | Refuses on the last member, naming it |
| `party_has` | *(condition form)* `{"party_has":"1"}` | live | RPG Maker's "actor is in the party" page condition, which the reference images show |
| `walk_to` | `who`, `x`, `y`, `speed=0` · *yields* | live | The honest half of "autonomous movement": walks in **tile space with no gravity and no jump** — a top-down assumption in one line |
| `face` | `who`, `dir` (`up/down/left/right`) | live | Writes `state.facing`. A side-on body has **two** facings; this is exactly the shape that does not port |
| `give_item` | `item`, `count=1` | **`needs-host`** | Requires `table:items`, which the pack declares and **no project file has created**. Ships declared and honestly measured as unwired. `count` may be negative — that is "take" |

**The extension mechanism, concretely and in full:**

1. write the specs in `scripts/game/flow/ops_topdown.py` with `loadout=`;
2. add `"event_loadouts": ["core", "topdown_rpg"]` to that pack's
   `genre.json`;
3. `tools/check_event_docs.py --write` regenerates `docs/EVENTS.md`;
4. the roster entry is already there from §5b.7.

**No new registry. No new dispatch. No editor code.** The picker groups by
`OpSpec.loadout`; the inspector renders `OpSpec.params` because they are
`BehaviorParam`s and `InspectionView` already renders those.

### 5b.7 Where a wrong-loadout command raises

Two rules: every op in a script must be in the script's declared `loadouts`;
the script's `loadouts` must be a subset of the scene's.

| moment | what happens |
|---|---|
| **authoring — picker** | The op is **greyed with its reason**, never hidden. Not a raise: a button that cannot be clicked |
| **authoring — hand-edited or pasted** | A **soft `RuleViolation`** in Problems, and the row draws red. **Not a raise** — an author mid-edit must be able to save a half-finished file, and a refusal belongs in the Problems dock, never a dialog |
| **authoring — project load** | `GenrePack.validate` walks every script; an op outside the pack's granted loadouts is a **hard `RuleViolation`** with `fix="add \"topdown_rpg\" to this pack's event_loadouts, or use a core op"` |
| **SCRIPT LOAD (engine)** | **RAISES** `PyoneerConfigError` naming file, page, node `id` and op, for an unregistered op or one outside the script's own `loadouts` |
| **SCENE LOAD (engine)** | **RAISES** for a script whose `loadouts` ⊄ the scene's, naming the script, the op and both lists |
| **execution** | **never** for vocabulary reasons — by then it is proved twice |

> **Answering the ask directly: a script using a platformer command opened in a
> top-down map RAISES AT SCENE LOAD**, naming the scene, the script, the page,
> the node and both loadout lists. Not at authoring (the picker prevented it).
> **Not at execution** — the same choice `#TAG:registry.resolve` made, for the
> same reason: a bad op discovered mid-cutscene has already stolen the
> player's agency.

**This raise is legal only because `loadouts` lives in the scene FILE, which
the engine reads, and not in a genre pack, which law 2 forbids the engine
reading.** That one placement (§3.2) is what buys an engine-side gate.

### 5b.8 How an AI collaborator discovers the vocabulary

**`docs/EVENTS.md`, GENERATED by `tools/check_event_docs.py --write` from
`OP_REGISTRY`, byte-compared on every run** — `docs/BEHAVIORS.md`'s contract
with `check_behavior_docs.py`, reproduced. Roster entry
`("event_docs", "the event vocabulary and its measured integration")` goes into
`tools/check_all.py` **in the same change** (law 6).

Columns: **op · loadout · arguments · yields · status · runtime · in a pack ·
IN THE PICKER**.

- **`runtime`** — the op's `run` is executed against a headless `ScriptRun`
  fixture and the effect observed. `set` writes the store; `wait` elapses;
  `say` opens a duck-typed window; `ask` **does not**.
- **`in the picker`** — **the generator imports the picker module and asks
  which names it offers.** A row reading `picker: no` names a capability that
  is registered, packaged, documented, checked and **unreachable from the
  layer above** — printed in a byte-compared table on every run.

That last column is the direct instrument against this repository's signature
defect. It is precisely what `map.tileset.grow` and `map.tileset.rename`
needed for four passes and never had, and §1.1 is what it costs not to have
it.

> **The same column is added to `docs/COMMANDS.md` in the same change**, asking
> which verbs have a caller under `editor/ui/`. It would have caught
> `grow`/`rename` the day they landed, and it makes the fifth sighting the
> last one.

**`docs/EVENTS.md` has NO hand-written preamble at all.** Every line is
generated from the registry's own counts. `docs/BEHAVIORS.md`'s preamble lives
inside its generator and has carried two lies while matching it byte for byte
(`docs/NEXT.md` entry 1); a document with no hand-written prose cannot catch
that disease.

**`docs/COMMANDS.md` and `docs/EVENTS.md` stay two documents.** A `Command`
mutates the project at authoring time and returns its inverse; an op mutates
the game at run time and does not. Merging them would be the single most
confusing thing this spec could do.

---

## 6. THE VERBS

All new verbs follow the incumbent `map.*` / `table.*` shape: exact inverses,
`destructive=True` where undo cannot reach, and inverse-only members where a
verb cannot express its own inverse (10 of 51 today).

### 6.1 Tilesets

| verb | scope | arguments | inverse |
|---|---|---|---|
| `tileset.create` | `tileset:*` | `name`, `image`, `tile_width`, `tile_height`, `columns`, `count` | `tileset.delete {confirm: true}` |
| `tileset.delete` *(destructive)* | `tileset:*` | `confirm: bool` | `tileset.restore {text: <TilesetFile.render()>}` |
| `tileset.restore` | `tileset:*` | `text: str` | `tileset.delete {confirm: true}` |
| `tileset.grow` | `tileset:*` | `count`, `image=""`, `image_height=0` | itself, with the previous values |
| `tileset.rename` | `tileset:*` | `to` | itself, names swapped |
| `tileset.tile.retire` | `tileset:*` | `tiles: list[int]`, `force=false` | `tileset.tile.restore` with the same ids |
| `tileset.tile.restore` | `tileset:*` | `tiles: list[int]` | `tileset.tile.retire {force: true}` |
| `tileset.tile.set` | `tileset:*` | `tile: int`, `key`, `value` | itself, previous value |
| `map.tileset.link` | `map:*` | `name`, `first_gid`, `tileset` | `map.tileset.unlink` |
| `map.tileset.unlink` | `map:*` | `name`, `first_gid` | `map.tileset.link` with the removed value |
| `map.tileset.sync` | `map:*` | `name`, `first_gid` | itself, with the previous four geometry values |

`tileset.restore` carries the file's **rendered TEXT**, not a dict:
`TilesetFile.render`/`parse` is a proved byte-exact round trip, and a dict
would be a second spelling of the same data.

`tileset.grow` and `tileset.rename` **fan out** — they rewrite the `.tileset`
**and** emit the per-map `map.tileset.grow` / `map.tileset.rename` for every
reference, all in one `run(...)` → **one undo step**. `grow` pre-flights
headroom in **every** referencing map and refuses **all-or-nothing**, naming
which map is short and by how much. A grow that lands in three maps and is
refused by a fourth leaves the shared asset disagreeing with a map that
references it, which is the exact drift the format exists to prevent.

`map.tileset.rename` on a **linked** tileset is refused — geometry and name
belong to the shared file, and `#TAG:tileset_defaults` **raises** when
`mask.meta["name"] != ref.name`, so a per-map rename would break the mask in
every other map.

`tileset.tile.retire` **refuses by default while the tile is painted**, naming
every map, every layer and its count, and offering `force=true` to hide it
from the palette while leaving the painted cells alone. It refuses **outright**
on a sheet whose local id carries meaning (the `collision` sheet).

### 6.2 Project

| verb | scope | arguments | inverse |
|---|---|---|---|
| `project.map.add` | `project` | `name`, `identifier`, `file` | `project.map.remove` |
| `project.map.remove` *(destructive)* | `project` | `name` | `project.map.restore` carrying the entry and its index |
| `project.map.restore` | `project` | `entry: dict`, `at: int` | `project.map.remove` |

`project.map.remove` **refuses while any scene names the map**, naming the
scenes.

### 6.3 Scenes

| verb | scope | arguments | inverse |
|---|---|---|---|
| `scene.create` | `scene:*` | `id`, `title` | `scene.delete {confirm: true}` |
| `scene.delete` *(destructive)* | `scene:*` | `confirm: bool` | `scene.restore {scene: <whole to_json()>}` |
| `scene.restore` | `scene:*` | `scene: dict` | `scene.delete {confirm: true}` |
| `scene.set` | `scene:*` | `key`, `value` | itself, previous value; **returns `None` when unchanged** |
| `scene.unset` | `scene:*` | `key` | `scene.set` with the removed value |
| `scene.map.add` | `scene:*` | `map`, `entry=""`, `at: int = -1` | `scene.map.remove` |
| `scene.map.remove` | `scene:*` | `map` | `scene.map.add` with the recorded index |
| `scene.map.move` | `scene:*` | `map`, `to: int` | itself, indices swapped |
| `scene.var.set` | `scene:*` | `key`, `type`, `default`, `doc=""` | itself, previous record |
| `scene.var.remove` *(destructive)* | `scene:*` | `key` | `scene.var.set` with the removed record |
| `scene.route.set` | `scene:*` | `token`, `payload`, `script` | itself, previous value |
| `scene.route.remove` | `scene:*` | `token`, `payload` | `scene.route.set` with the removed value |

### 6.4 Scripts

| verb | scope | arguments | inverse |
|---|---|---|---|
| `script.create` | `script:*` | `id`, `title`, `loadouts: list[str]` | `script.delete {confirm: true}` |
| `script.delete` *(destructive)* | `script:*` | `confirm: bool` | `script.restore {script: <whole document>}` |
| `script.restore` | `script:*` | `script: dict` | `script.delete {confirm: true}` |
| `script.set` | `script:*` | `key`, `value` — `title`, `loadouts` | itself, previous value |
| `script.page.add` | `script:*` | `id`, `after=""`, `trigger`, `when: list` | `script.page.remove` |
| `script.page.remove` *(destructive)* | `script:*` | `page: str` | `script.page.restore` carrying the whole page **and its position** |
| `script.page.restore` | `script:*` | `page: dict`, `after: str` | `script.page.remove` |
| `script.page.move` | `script:*` | `page`, `after` | itself, previous position |
| `script.page.set` | `script:*` | `page`, `key`, `value` | itself, previous value |
| `script.node.add` | `script:*` | `id`, `do`, `into`, `arm=""`, `after=""`, `args: dict` | `script.node.remove` |
| `script.node.remove` *(destructive)* | `script:*` | `node: str` | `script.node.restore` carrying the node, **its whole subtree**, its parent, its arm and its predecessor |
| `script.node.restore` | `script:*` | `node: dict`, `into`, `arm`, `after` | `script.node.remove` |
| `script.node.set` | `script:*` | `node`, `key`, `value` | itself, previous value; **returns `None` when unchanged** |
| `script.node.move` | `script:*` | `node`, `into`, `arm`, `after` | itself, previous position |

**Every node and page is addressed by its stable `id`, never by a path**
(§3.4). `into` and `after` are node ids; `arm` is `""` / `"then"` / `"elif:N"`
/ `"else"`.

**Attaching a script to an object needs NO new verb**:
`map.object.property.set {name: "pyoneer_script", value: "keeper_gate"}` —
existing verb, existing exact inverse, and `_checked_property_name` already
refuses a reserved name before writing. One fewer permanent string.

**Fourteen `script.*` verbs, not one per op.** Nine core ops × four verbs would
be 36 new verbs and `docs/COMMANDS.md` would double again — which is the
parallel-registry shape the ask forbids. One node verb validated against the op
registry is the same trade `map.layer.set` already makes against
`#TAG:CAPABILITIES`.

**`tools/check_docs.py --write` regenerates `docs/COMMANDS.md` in the same
change that adds any of these**, or the ONE HOME assertion goes red.

---

## 7. THE BUILD ORDER

Four tracks. **Stages 1, 2, 4 and 6 are independent starting points.** Within a
track the order is strict. **The core op set and its runtime ship before any
loadout**, because the author asked to start with the portable handful.

Every cost is honest working days for one person.

**Repair-pass note:** that pass is holding `main_window.py`, `canvas.py`,
`hierarchy.py`, `database.py`, `session.py`, `verbs.py`,
`scripts/game/entity/`, `main.py` and `demos/`. **Stage 1 is chosen partly
because it touches almost none of them.** Re-measure §1.1's grep before
starting anything in the tileset track.

---

### STAGE 1 — the scoped relay payload and the Ask button · **1 day** · INDEPENDENT

**Ships.** `describe_all(*, scopes=())` in `editor/core/commands.py` (one
keyword; empty means byte-identical output, so `check_docs` cannot regress).
`write_bundle(..., scoped=...)` in `editor/core/request.py`. `Session.ask(scope,
text)` — twelve lines, Qt-free. The **`Ask`** button on `PromptStrip`. The
refusal for a zero-verb scope. And two one-line fixes in the same change:
`database.py`'s strip has **no `staged.connect`**, and `#TAG:describe_scope`'s
plausible-default return becomes a raise with arms for `field` and `code`.

**THE GESTURE.** Open the Inspector on `map:test/layer:Floor`, type *"make the
shoreline two tiles wider"* into the strip beneath it, press **`Ask`**. A
bundle appears in `editor/requests/` and the status bar names the path. It is
**~2,386 tokens instead of ~12,947**, and its `COMMANDS.md` holds **8 of the 51 verbs
instead of all 51**.

**THE CHECK** — `tools/check_relay.py`, roster entry in the same change,
driven with **no Qt at all** through `open_here()`:

- **half A:** `describe_all(scopes=(layer,))` contains **exactly** the 8 layer
  verbs, by name and by count.
- **half B:** it contains **none** of the other 43 — *the half that actually
  fails when the filter is wrong*.
- **half A:** `describe_all()` unscoped still contains **all 51**, so the
  default path cannot regress.
- **half B:** a scoped bundle is **under 3,000 tokens** and an unscoped one is
  **over 9,000**. The whole feature is the ratio, so **the size claim itself is
  asserted** and cannot silently regress into shipping the vocabulary again.
- **half A/B:** `Session.ask("assets", …)` **refuses naming the scope**;
  `Session.ask("map:test/layer:Floor", …)` **writes a bundle**.
- **half A/B:** `describe_scope` answers for all thirteen kinds and **raises**
  on a fourteenth.
- Qt half, offscreen: `strip.ask()` writes a bundle carrying **its own panel's
  scope**, and `modals() == []`.
- **Mutation to report:** make `describe_all` ignore `scopes` → the size
  assertion and half B both go red.

**Why first.** It is a day, it ends in a gesture, it is one of the two things
the author named after seeing the draft, it makes every later stage's AI
collaboration cheap, and it avoids every file the repair pass is holding
except one additive method.

---

### STAGE 2 — a second map · **1–2 days** · INDEPENDENT · **gates 3 and 5**

**Ships.** `project.map.add` / `.remove` / `.restore`; `Project.save()` writing
`config/maps.json` deterministically (`sort_keys`, trailing newline,
`newline="\n"`, matching the tables' contract); `EditorWindow.map_name`
becomes settable with a toolbar `QComboBox`; `MapCanvas` re-targets.

**THE GESTURE.** `File ▸ New map…`, pick it in the toolbar combo, paint a
tile, switch back, Ctrl+Z.

**THE CHECK** — `tools/check_project_maps.py`:
- **half A:** a second map appears in `known_scopes()` and its layers are
  paintable, and `to_bytes()` round-trips byte-exactly.
- **half B:** removing a map a scene names is **refused, naming the scene**;
  removing an unreferenced one succeeds.
- **half A/B:** the untouched map's `to_bytes()` is unchanged throughout.

**Why here, and why it gates.** `config/maps.json` holds **one** map and **no
verb writes it** (measured). Every "shared by 3 maps / 2 scenes" line, every
cross-map refusal and every blast-radius number is **untestable and untrue**
until a second map can exist. A shared-tileset feature built before this ships
a central pane displaying a constant.

---

### STAGE 3 — the tileset editor: retire, link, share · **4–5 days** · after 2

**Ships.** `SCOPE_KINDS += ("tileset",)` with its `describe_scope` and
`_BUILDERS` arms; `data/project/tilesets/*.tileset` as authored documents
joining `Project.dirty_*` (§2.5); the eleven verbs of §6.1; `pyoneer_tileset` read
by a new `declared_tileset` written **beside** `#TAG:declared_collision`;
`Project.tileset_usage`; the drift refusal at project load;
`editor/ui/tileset_window.py` with all four empty/broken states; the width-locked
`Grow…` dialog; the retire pane; `TilePalette` reading retirement so a retired
tile greys and **cannot be stamped**; and **`#TAG:plan_intern` /
`#TAG:apply_intern` get their first caller outside a check** — promoting an
embedded sheet to a shared document is the operation they were written for.

**THE GESTURE.** `Ctrl+T` → pick `TileA2` → `Promote to shared…` → open the
second map → `Link…` → click tile 194 → `Retire` → the pane names **463 cells
across 2 maps** → choose *tile 193* → one click → both maps repaint → **one
Ctrl+Z takes all of it back**.

**THE CHECK** — `tools/check_tileset_shared.py`:
- **half A:** a retired gid **cannot be stamped** from the palette;
  **half B:** a non-retired one can.
- **half A:** a cross-map grow with headroom in **every** map applies to all in
  **one** transaction; **half B:** a grow short in **one** map refuses
  **entirely**, naming that map, leaving every other map **byte-identical**.
- **half A:** a `.tileset` whose geometry disagrees with a map **raises naming
  the field**; **half B:** an identical one loads.
- **half A/B:** the two round-trip theorems hold with and without a retirement
  property.
- **half A/B:** retire then undo leaves `document.to_bytes() == ORIGINAL` and
  the `.tileset` byte-identical.
- **half A/B:** `tileset.delete` then `undo` leaves the file **on disk**
  (§2.5's rule; the mutation is to call `os.remove` at apply time, which turns
  it red).
- The `os.listdir` census passes for the new file; `modals() == []`.
- **Mutation to report:** make the grow pre-flight check only the first map →
  the all-or-nothing half goes red.

---

### STAGE 4 — the op registry, the core eight, and `docs/EVENTS.md` · **3 days** · INDEPENDENT · **strictly before 5, 7, 9**

**Ships.** `scripts/game/flow/ops.py` (`OpSpec` with `params:
tuple[BehaviorParam, ...]` **imported**, `OP_REGISTRY`, `register`, `resolve`,
`validate_loadouts`, `describe_all`) and the **eight core specs**;
`scripts/loaders/script_file.py` with every §4.5 load gate;
`scripts/game/flow/interpreter.py` (`ScriptRun`, the node stack,
`MAX_STEPS_PER_FRAME`, `MAX_CALL_DEPTH`, `push_frame` re-raise); **`AgencyHold`
extracted INTO `scene_flow.py`** with `SceneFlow` rewritten onto it;
`docs/EVENTS.md` + `tools/check_event_docs.py`; and the **`in the picker`**
column added to `docs/COMMANDS.md`'s generator.

**THE GESTURE.** `.venv/Scripts/python.exe -m demos.script` — walk to the
keeper in a demo map (written by `demos/mapgen.py`, **never** the shipped
map),
press the action key, and **a branching conversation runs from
`data/project/scripts/keeper_gate.json`**, with the player unable to walk and
still able to press continue. Route A only; `ActionRouter` starts it exactly as
`demos/narrative.py` starts a flow today.

**THE CHECK** — `tools/check_ops.py` and `tools/check_event_docs.py`:
- **half A/B:** `if` takes `then` at coins 100 **and** `else` at 99, and an
  `elif` arm on its own condition.
- **half A:** an unknown `do` raises **at load** naming file/page/node;
  **half B:** a known one does not.
- **half A:** an **undeclared** var raises at load; **half B:** a declared one
  reads its default.
- **half A:** `hold` clears `steerable`; **half B:** `release` restores **the
  recorded value, not `True`** — an already-unsteerable body is still
  unsteerable after.
- **half A:** a 600-node non-yielding script **raises** at
  `MAX_STEPS_PER_FRAME`; **half B:** a 500-node one completes.
- **half A:** `call` depth 17 raises **naming the chain**; **half B:** depth 15
  runs.
- **structural:** `interpreter.py` and `ops.py` reach the event bus at **zero**
  points, **proved from the parse tree with a planted decoy** so the scan is
  shown able to find a `handle(`; and they import nothing from `editor/`, with
  a misspelled-prefix control.
- `docs/EVENTS.md` regenerated and compared **byte for byte**.
- `tools/check_flow.py`'s 144 assertions **stay green** — the regression net on
  the `AgencyHold` extraction.
- **Mutation to report:** make `_restore` write `True` → the
  already-unsteerable half goes red.

---

### STAGE 5 — the event editor and its picker · **4 days** · after 3 (for `SCOPE_KINDS`) and 4

**Ships.** `SCOPE_KINDS += ("script",)`; the fourteen verbs of §6.4;
`editor/ui/script_window.py`; `editor/ui/op_picker.py` (non-modal, `core only`
filter, badges, greyed-with-reason); the `"script"` `_BUILDERS` arm.

**THE GESTURE.** `Ctrl+E` → `+ New…` → `+ Page` → press Insert → the picker
opens showing **eight core buttons** → pick `if` → the row nests and grows an
`Else` header → click `Else`, Insert, pick `say`, type a line → **`F5` and the
game runs it.**

**THE CHECK** — `tools/check_script_editor.py`:
- **half A:** inserting into a `then` arm produces the right parent/arm and the
  reloaded document round-trips; **half B:** undo removes **exactly that
  subtree** and the document is byte-identical.
- **half A:** `script.node.remove` then `restore` puts the node back **in its
  original arm and position**; **half B:** a `set` with an unchanged value
  returns `None` and puts nothing in the undo list.
- **half A:** the picker shows **only** ops in the script's loadouts;
  **half B:** it shows a loadout op **greyed with its reason**, not absent.
- `modals() == []`; the `os.listdir` census passes for **both** new files.
- **leak assertion:** `top_levels()` equal at rest / after an edit / after an
  undo, and `peak <= settled` sampled **mid-rebuild** across 12 undo/redo
  cycles (law 12).

---

### STAGE 6 — scenes · **4 days** · INDEPENDENT of 1 and 3 · needs 2 and 4

**Ships.** `scripts/loaders/scene_file.py` (the `table_file.py` shape,
including `EMPTY` and the no-`.get`-sibling rule); `SCOPE_KINDS += ("scene",)`;
the twelve verbs of §6.3; `SceneDock`; the **four `SceneManager` fixes** and
`GameScene.end()`; `SceneManager.vars` as the one variable store; `main.py`
reading `data/project/scenes/` with **today's path unchanged when the directory
is absent**; and **`enter_scene` joins core** — the scheduled birth date.

**THE GESTURE.** Scenes dock → `+ New…` → `+ Map slot` twice → set `on_enter`
→ press Play. Then from an event, `enter_scene dungeon` walks the player
through a door and **the first scene's tiles stop drawing**, with
`gate_open` surviving the round trip.

**THE CHECK** — `tools/check_scenes.py`:
- **half A:** after a switch the leaving scene's entities **stop updating AND
  stop drawing**; **half B:** the incoming scene's are all bound. *(Today they
  stop updating and keep drawing — mutate the fix to skip the renderer unbind
  and this goes red.)*
- **half A:** `set_scene("nope")` raises `PyoneerSceneError` **naming the
  available scenes**; **half B:** a known name does not raise.
- **half A:** `actions.routes` is empty of the old scene's; **half B:** it
  carries **exactly** the new scene's `routes`.
- **half A:** a revisited scene prepares again; **half B:** a once-entered
  scene does **not** double-prepare beyond the documented twice (probe object
  counting hook calls).
- **half A/B:** the load graph is a DAG — a scene naming itself as a map
  raises, and an honest chain walks.
- **half A/B:** with **no** `data/project/scenes/` directory the boot is
  unchanged and `tools/smoke.py --frames 60` reports **no drift** (laws 11
  and 12).
- **Mutation to report:** drop the `actions.clear()` → the empty-of-old half
  goes red.

---

### STAGE 7 — region triggers · **3 days** · after 4 and 6

**Ships.** `editor/core/map_events.py` → **`scripts/core/map_events.py`** with
the editor re-exporting it (law 2's corollary, and the move the file's own
docstring specifies as mechanical); the load-time rasterisation into
`dict[cell_index, MapEvent]`; the `script_trigger` behavior token at
`order=85`; `docs/BEHAVIORS.md` regenerated.

**THE GESTURE.** Paint a trigger region in the Actions panel, attach a script,
**walk into it** — the conversation starts with no keypress.

**THE CHECK** — `tools/check_script_trigger.py`:
- **half A:** entering fires **once**; **half B:** staying does not re-fire,
  while a `stay` trigger does.
- **half A:** a `filter_class` that excludes the body fires **zero** times;
  **half B:** an including one fires once.
- **half A/B:** `once` and `cooldown_ms` behave in both directions.
- Law 2 re-asserted on the moved module; `tools/check_map_events.py` stays
  green through the move.
- **`ActionsDock`'s visible `NOT_WIRED` label comes down in the same change** —
  `check_actions_panel.py` pins that exact string and it becomes a lie.
- **Law 10 note in the change:** `script_trigger` polls **no** input verb, so
  **no `config/inputs.json` edit accompanies it.**

---

### STAGE 8 — the relay's back channel and the review · **2 days** · after 1

**Ships.** `reply.json` and `refusal.json`; `Manifest` persistence
(`from_json` gets its first caller); the **Incoming** section on
`ManifestDock` with the **inverse-rendered diff** and the `Verb.validate`
green/red; the `NOTES.md` readback in the box; and
`EditorWindow.apply_response` collapsed onto `Session.apply_response`.

**THE GESTURE.** A `response.jsonl` lands → the box lights up → the Manifest
dock shows **24 tiles change** with `(12,4): 0 → 65` under an expanded row →
one click → **one undo step**.

**THE CHECK** — `tools/check_relay.py` extended:
- **half A:** a `reply.json` with `refused` set applies **nothing** and leaves
  the document byte-identical; **half B:** a clean response applies **all** of
  it as one transaction.
- **half A:** a mid-batch failure rolls back with `rolled_back is True` and
  writes `refusal.json`; **half B:** the good command **never landed**.
- **half A/B:** `undo()` after apply restores the original bytes; `history()`
  carries `source == "response:<id>"`.
- **half A/B:** `ReviewPanel.apply` and `Session.apply_response` produce **the
  same transaction**.
- **half A/B:** the rendered diff for `map.tile.set_many` names the old gid,
  and the review **mutates nothing** — `can_undo` is exactly as it was found.

---

### STAGE 9 — the `topdown_rpg` loadout · **2 days** · after 4 and 5 · **deliberately LAST**

**Ships.** `scripts/game/flow/ops_topdown.py` with the eight §5b.6 specs;
`"event_loadouts"` in both packs' `genre.json`; `ops.validate_loadouts` in
`genre._build`; the picker's second section; `docs/EVENTS.md` regenerated.

**THE GESTURE.** Open the picker in a `topdown_rpg` scene — Core shows eight,
Top-down RPG shows eight more. Switch the project genre to `platformer`; the
same script's `walk_to` row turns red with its reason and the picker greys
those eight.

**THE CHECK** — `tools/check_loadouts.py`:
- **half A:** a script declaring `topdown_rpg` loads under that pack;
  **half B:** it **raises at scene load** under `platformer`, naming the op and
  both lists.
- **half A:** a pack declaring an unregistered loadout **raises at pack load**;
  **half B:** a valid pack loads.
- **half A:** `actor_set` with an unknown `actors` column raises **at script
  load** naming the file; **half B:** a known column does not.
- **half A/B:** every `core` op is reachable from **both** shipped packs —
  that is the portability claim, and it must be an assertion, not a hope.

**Why last.** The author asked to start with the portable handful, and a build
order delivering a genre-specific command before the core set runs is
answering a question nobody asked.

---

### Dependency summary

```
 1 (relay payload)  ─────────────────────────────► 8 (back channel)
 2 (second map) ──► 3 (tilesets) ──┐
 4 (ops + runtime) ──┬──► 5 (editor) ──► 9 (loadout)
                     ├──► 6 (scenes) ──► 7 (triggers)
                     └──► 7
```

**Independent starting points: 1, 2, 4.** Stage 6 needs 2 and 4. Stage 5 needs
3 (for the scope-kind change it shares) and 4.

**Parallelisable:** {1, 8} · {2, 3} · {4, 5, 6, 7, 9} are three tracks that
touch disjoint files except two shared seams — `main_window.py`'s menu and
`editor/core/scope.py`'s `SCOPE_KINDS`. **Both must be coordinated**, because
`check_editor_ui.py` pins `main_window.py`'s exact modal count and asserts
shortcut uniqueness across the whole window.

**Total ≈ 26 working days**, with the first gesture on **day one** and the
first scripted event running on day **four to seven**.

---

## 8. WHAT WE ARE DELIBERATELY NOT BUILDING

Stated so it cannot drift back in.

### Refused permanently

| refused | the cost that justifies it |
|---|---|
| **Tileset compaction / mid-sheet delete with renumbering** | **10,210 of 10,210 painted cells repaint with the wrong art from one deletion, silently, with nothing raising anywhere** (§1.5). And the `collision` sheet's local id **is** its mask value, so it changes meaning, not art. If it is ever built it must be a project-wide migration rewriting every referencing map in one transaction. **This is the irreversible mistake in this whole ask.** |
| **An expression language in the script schema** (`"if": "hp < 10 and gate"`) | A second grammar with its own escaping and its own error surface, no way for the editor to render it as a form, and no way for a check to enumerate it. Six comparators, closed |
| **A raw-code / `eval` command** | Makes every check vacuous (law 5) and turns a relay response into remote code execution |
| **A new `GameEventType` member for triggers** | `USE` is the standing proof: defined, emitted once, bound by nobody. `EVENT_NAMES` already *reserves* four such strings. Triggers reach scripts by a **behavior**, on the called side |
| **A modal command picker** | `check_editor_ui.py` auto-enrols every new `editor/ui/*.py` by `os.listdir` and fails on any `.exec()`. `ask.py`'s modal set is pinned to **exactly** `["question", "exec:dialog"]`, so putting the picker there turns that assertion red |
| **A genre pack defining a command body** | Law 2: `python main.py` must run with `editor/` deleted |
| **A map overriding a shared `.tileset`'s geometry** | One document, two meanings — and the `.blitmask` cannot be both |
| **Per-command checkboxes in the relay review** | A checkbox is a partial apply, and a hand-picked subset is a response the AI did not write and cannot be held to |
| **A second registry, a chat panel, an `EventBus`, a `SceneController`, or `foo_v2.py` of anything** | Five refactors died as sibling files. Every refactor written INTO the incumbent landed |

### Deferred, each with the specific repair that unblocks it

| deferred | blocked on |
|---|---|
| **`loop` / `break`** | `MAX_STEPS_PER_FRAME`'s raise measured in **both** directions (Stage 4). Then a bounded `repeat n` is defensible; an unbounded loop never is |
| **`parallel` triggers** | A second, non-borrowing runner. `SceneManager.flow` is one slot because two flows *"would each restore agency the other changed"* — that is a second concept nobody in this ask named |
| **Per-verb scene control profiles** ("this scene has no jump") | `#TAG:InputActionManager.held` is an unguarded dict index; the naive version is a `KeyError` **inside `core_frame_update`** that kills the frame for every sibling (law 10). Needs a new `BodyState` axis and a guarded `held()` |
| **A scene's map positions (`at: [x, y]`)** | Nothing reads it. An authored field with no reader is exactly what `pyoneer_trigger` has been for months. It lands with the stage that consumes it |
| **screen effects** | A post-process stage in a renderer that is a sorted blit queue. (The audio half of this row is paid: `scripts/core/audio.py` landed 2026-09-04 and `play_sound` / `play_music` are core ops) |
| **A save system** | `SceneManager.vars` survives a scene change and dies with the process. A save file is a separate change with its own check, and this spec does not open it |
| **Runtime writes to `data/project/tables/`** | A running game writing its own authored source. `actor_set` writes a per-run overlay, discarded at exit |
| **Native `.blitmap` collision beyond level one** | `#TAG:field_from_map` returns `None` for any source serving its own `object_records`, and a `.blitmap` has no companion layers either |

---

## 9. OPEN QUESTIONS

Three. Each has a recommended default, so **work starts tomorrow without an
answer**.

**Q1 — Is "remove a tile" retirement, or did you mean erasing painted tiles?**
This spec reads it as the sheet, and answers it with **retire** because the
arithmetic says a real removal repaints 10,210 cells silently (§1.5). Retire
takes the tile out of the palette, changes no cell, and undoes in one click.
**Default if you say nothing: retire, as specified. It ships in Stage 3 and
nothing about it is hard to change later** — the encoding is one per-tile
property on a file with two round-trip theorems.

**Q2 — Should a second map arrive as a real feature, or as a fixture?**
Stage 2 makes `config/maps.json` writable so a scene can hold two maps and the
tileset screen's numbers can be true. It is 1–2 days of infrastructure you did
not ask for, inserted before a screen you asked for twice. **Default: build
it.** The alternative is a blast-radius pane displaying a constant and
refusals quoting counts that cannot be true. Note that Stage 1 already ships a
clickable gesture, so this is not a detour before your first result.

**Q3 — `ask` (in-game choices) needs the first widget in this engine that
reports a click.** `scene_flow.py` states the blocker: *"no widget in this
engine reports one to anything."* **Default: `ask` ships in Stage 4 as
`status="needs-host"`** — registered, in the picker with a ⚠, in
`docs/EVENTS.md` with a measured `runtime: no`, and authorable — and the
`ChoiceBox` that makes it run is a half-stage after Stage 5, resolved by the
`up`/`down`/`action` verbs already bound in `config/inputs.json`. If you would
rather not see an op you cannot run, say so and it is held back entirely; the
core set is seven until then.

---

## The checks this spec plans

Every stage above names the check that proves it. None of them exists yet, so
they are declared here rather than merely mentioned: `tools/check_docs.py`
refuses a `check_*` a live document names unless it is on the roster or is
declared below, and it **also refuses a name declared below that has since
reached the roster**. So this list cannot rot — the stage that lands a check
deletes its line here, or the suite goes red.

```planned-checks
check_project_maps
check_tileset_shared
check_scenes
check_script_trigger
check_loadouts
```

## Appendix — every permanent string this spec mints

Law 8 makes each of these stable the day it lands. This list is the review
surface; if a name is wrong, it is wrong here and nowhere else.

**Scope kinds (3):** `scene` `tileset` `script`
**Tmx properties (2):** `pyoneer_tileset` `pyoneer_script`
**Tileset property (1):** `pyoneer_retired` — as `prop bool pyoneer_retired true`
**Document formats:** `pyoneer.scene` `pyoneer.script` `pyoneer.relay.reply`
`pyoneer.relay.refusal`, each `"version": 1`
**Scene keys:** `format version id title doc loadouts maps entry_map vars
controls routes on_enter on_exit next`; a map slot's `map entry`; a var's
`type default doc`
**Script keys:** `format version id title loadouts pages body note trigger
payload once cooldown_ms when do if while then elif else`
**Comparators (6, closed):** `is not at_least at_most in contains`
**Variable namespaces (3, closed):** `global.` `scene.` `local.`
**Script triggers (5, closed, a superset of `TRIGGER_KINDS`):** `use enter exit
stay auto`
**Core ops (8, +1 scheduled):** `say ask set wait hold release call stop`, and
`enter_scene` from Stage 6
**`topdown_rpg` loadout (8):** `actor_set actor_has party_add party_remove
party_has walk_to face give_item`
**Genre pack key (1):** `event_loadouts`
**Behavior token (1):** `script_trigger`
**Relay keys:** `scoped verbs` on `manifest.json`; `answer refused unresolved
commands` on `reply.json`; `failed_line message rolled_back applied` on
`refusal.json`
**Verbs (40):** the eleven tileset, three project, twelve scene and fourteen
script verbs of section 6.

Every one of these lands in a **generated** document — `docs/COMMANDS.md`,
`docs/EVENTS.md`, `docs/PLACEABLE.md`, `docs/BEHAVIORS.md`, `docs/CHECKS.md` —
regenerated in the same change that adds it and byte-compared on every run, so
none of them can drift into a lie.