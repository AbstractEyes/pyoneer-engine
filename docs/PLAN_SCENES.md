<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; the status table was re-measured on 2026-09-16 by running the command printed in each row, and the design below was carried from docs/history/PLAN_SCENES_2026-09-03.md with every fact those commands contradicted corrected. -->

# Scenes, shared tilesets, region triggers, the relay back channel — the unbuilt remainder

The build spec for what is **not built yet** of one request: scenes that group
maps, tilesets that are their own files, an RPG-Maker-shaped event system in
JSON, a portable command vocabulary, and relay boxes the developer works
through instead of loading the whole tree.

The shipped half — the scoped Ask, the op registry and runtime, the event
editor — is not described here. Its rationale is frozen in
[`history/PLAN_SCENES_2026-09-03.md`](history/PLAN_SCENES_2026-09-03.md), and
**every section number below is that file's number**. A number missing here is
work that is done: read it there, never build it again.

Read [`../CLAUDE.md`](../CLAUDE.md) first — its fourteen laws and five ACTIVE
WARNINGS, above all *"You will reach for a sibling file"*: every row below
names the incumbent to extend.

---

## Status — re-measured 2026-09-16

| stage | status | measured by | build on — extend it, never beside it |
|---|---|---|---|
| **1** scoped relay payload + Ask | **BUILT** | `grep -c "def ask" editor/core/session.py` → 1 | `#TAG:Session.ask`, `#TAG:commands.describe_all` (`scopes=`), `#TAG:BundleContract`, `tools/check_relay.py`. Residue: `grep -c "staged.connect" editor/ui/database.py editor/ui/script_editor.py` → 0 and 0, so staging from either window does not refresh the Manifest dock |
| **2** a second map | **UNBUILT** | `grep -rnF "project.map." editor scripts --include=*.py` → nothing | `#TAG:Project`; `config/maps.json` holds one map, `starter`, and no verb writes it |
| **3** tileset editor | **UNBUILT** | `grep -rnF "pyoneer_tileset" scripts editor --include=*.py` → nothing | `#TAG:TilesetFile` (complete; zero `.tileset` files on disk), `#TAG:declared_collision`, `#TAG:TilePalette`'s header menu, `#TAG:TilesetImportDialog`, `#TAG:MapDocument.tileset_headroom` |
| **4** op registry + runtime | **BUILT** — ten core ops, not eight | `.venv/Scripts/python.exe -c "from scripts.game.flow.ops import OP_REGISTRY; print(len(OP_REGISTRY))"` → 10 | `#TAG:scripts/game/flow/ops.py`, `#TAG:ScriptRun`, `#TAG:AgencyHold`, `docs/EVENTS.md`; runs through `main.py` (no `demos/script.py` is needed). Residue: §5b.8's "has a caller under `editor/ui/`" column for `docs/COMMANDS.md` — `grep -ci "caller" docs/COMMANDS.md` → 0 |
| **5** event editor + picker | **BUILT** | `grep -c "^class ScriptEditor" editor/ui/script_editor.py` → 1 | `#TAG:ScriptEditor` and `#TAG:OpPicker` in ONE module (not `script_window.py` / `op_picker.py`); the fourteen `script.*` verbs; `#TAG:ScriptLibrary` |
| **6** scenes | **PARTLY, ~15%** | `grep -n "enter_scene" scripts/game/flow/ops.py` → a comment, no registration; `grep -A1 "def set_scene" scripts/core/scene/scene_manager.py` → a one-line swap | The scene reader is `scripts/loaders/script_file.py` — `#TAG:SCENE_KEYS`, `#TAG:parse_scene_vars`, `#TAG:load_vars` — reading `format version id title doc vars` only; `#TAG:VarStore`; `data/project/scenes/starter.json`. No `scene_file.py`, no `scene` scope kind, no `scene.*` verb |
| **7** region triggers | **UNBUILT** | `grep -rn "script_trigger" scripts editor --include=*.py` → nothing; `ls scripts/core/map_events.py` → absent | `#TAG:editor/core/map_events.py` (`#TAG:MapEvent`, `#TAG:TRIGGER_KINDS`) — MOVED, never copied; `#TAG:ActionsDock` and its `#TAG:NOT_WIRED` banner |
| **8** relay back channel + review | **UNBUILT** | `grep -rnF "refusal.json" editor --include=*.py` → nothing | `#TAG:read_response` (the gate both apply doors share), `#TAG:ManifestDock`, `#TAG:Manifest.from_json` (no caller), `NOTES_FILE` in `editor/core/request.py` (read by nothing) |
| **9** `topdown_rpg` loadout | **PARTLY** | `grep -h "event_loadouts" editor/genres/*/genre.json` → `["core"]` twice; `ls scripts/game/flow/ops_topdown.py` → absent | `#TAG:validate_loadouts` (already judges packs), `#TAG:GenrePack.grants` and its soft violation, `#TAG:OpPicker` (already sections and badges by loadout) |
| **Q3** a `ChoiceBox` so `ask` runs | **UNBUILT**, promised "after Stage 5" | `grep -rn "ChoiceBox" scripts editor main.py --include=*.py` → nothing | `#TAG:ask` (status `needs-host`; raises at runtime); the `say_open` / `say_close` host seam of `#TAG:ScriptRun` |

**Dependencies still binding.** 2 gates 3 and 6's multi-map slots. 7's region
half needs nothing unbuilt; its `auto` trigger needs 6. 9's ops need nothing;
its scene-load raise needs 6. 8 is independent. Shared seams:
`editor/ui/main_window.py`'s menus and `SCOPE_KINDS` in `editor/core/scope.py`
— `tools/check_editor_ui.py` pins the window's modals and shortcut uniqueness.

---

## Decisions already made — do not relitigate

Full arguments are in the snapshot under the section given.

- **"Tilemap" means TILESET** (§0): the sheet stamped FROM (`#TAG:TilesetFile`,
  `map.tileset.*`); a map's tile layers are stamped ONTO. "Remove a tile" means
  the sheet. Sharing is across `config/maps.json` maps; which scenes use a
  sheet is derived, never stored.
- **Ownership** (§2.1): a scene owns ordered map slots, vars, controls, routes,
  entry/exit scripts and loadouts — not tilesets. A map owns `firstgid` only
  (`#TAG:TilesetLink`); a script is owned by nobody; `#TAG:GameScene` is what a
  scene loads into, unchanged. The load graph is a DAG; `call` cycles raise at
  `MAX_CALL_DEPTH` naming the chain (§2.2).
- **Save-time writes** (§2.5): a file-backed document is created and deleted in
  memory and reaches disk only at `Project.save()`, because a file's existence
  cannot be inverted (`#TAG:written_file_has_no_inverse`). `#TAG:ScriptLibrary`
  is the precedent every new document kind follows.
- **Strict, versioned JSON** (§3.1): `format` then `version`; an unknown key at
  any depth or a newer version raises naming the path; output is
  `json.dumps(indent=2, sort_keys=True) + "\n"`.
- **Two node shapes, stable ids** (§3.4): `{"id", "do", ...}` and
  `{"id", "if"|"while", ...}`. Every script, page and node id is required,
  never reused, never minted at save — a relay batch addressed by path
  mis-lands silently.
- **Pages select; nodes branch** (§3.4): pages run top-down, first passing
  `when` wins (the reverse of RPG Maker's shadowing), zero passing is fine. A
  page is a trigger plus an ANDed guard — two pages are the disjunction — and
  logic is the body's real tree (`if` with a LIST of `elif` arms), never page
  proliferation or a `Branch End` row.
- **Six comparators, closed** (§3.4): `is not at_least at_most in contains`
  (`#TAG:COMPARATORS`). A condition is a record; no expression language, ever.
- **Three namespaces, closed** (§3.4): `global.`, `scene.` (the default),
  `local.` (per map object) — `#TAG:NAMESPACES`. Every variable is declared
  with a type, so a read is total and a typo raises at load.
- **Called side, one slot** (§4.1, §4.4): a run fits `SceneManager.flow` with no
  new `GameEventType` and no bus contact; one run at a time; a runaway raises
  at `MAX_STEPS_PER_FRAME`.
- **Vocabulary raises at load, never at execution** (§4.5, §5b.7).
- **Flat op names, loadout as a field** (§5b.3): a dotted name would turn
  promotion into core into a rename, which law 8 forbids. `OpSpec.params` are
  imported `#TAG:BehaviorParam`s (§5b.1). A pack GRANTS loadout names via
  `event_loadouts` and never defines an op body (§5b.2, law 2).
- **No parallel registry** (§6.4): one verb family per document kind, validated
  against the op registry — fourteen `script.*` verbs, not one per op.
  Attaching a script is the existing `map.object.property.set` of
  `pyoneer_script`.
- **Commands and ops never merge** (§5a.7): a `Command` mutates the project and
  returns an inverse; an op mutates the game and does not. Two registries, two
  generated documents.
- **Rejected ops** (§5b.5): unbounded `loop` (a frozen frame; `while` is bounded
  by the step cap), `label`/`jump` (not a tree), a `note` op (every node takes a
  `"note"` key), switch and self-switch ops (typed `set` plus namespaces),
  `control_timer` (a second clock), `input_number`, `select_key_item` and
  `show_scrolling_text` (no host), screen tint and shake (no post-process
  stage), `spawn` (`#TAG:SPAWN_REGISTRY` has one usable type), `set_graphic`
  (the behavior list does it); a raw-code op **permanently**. Movement, party,
  inventory and stat changes belong to a loadout. `play_sound`/`play_music`
  were refused until `scripts/core/audio.py` existed — the rule that now holds
  back `enter_scene`.

---

## The unbuilt design, by original section number

### 2.3 Scopes — two kinds to add

`SCOPE_KINDS` is a closed **eleven** (`project genre map layer object table row
field assets code script`). Stage 3 adds `tileset`; Stage 6 adds `scene`.

**A scene is a peer ROOT** — `scene:overworld`, never
`scene:overworld/map:starter` — because `#TAG:Verb.validate` matches scopes
segment-wise and nesting would silently invalidate every `map:*` verb. Pages,
nodes and tiles are verb ARGUMENTS, never scope kinds. `#TAG:describe_scope`
raises on a kind with no arm (`#TAG:describe_scope_has_no_default`), so each
kind lands with its arm.

### 2.4 What "remove a tile" can mean

`gid = firstgid + local_id`, and the local id crosses file boundaries, so **a
local id is never renumbered or reused, a tileset grows downward at a fixed
width, and its column count is immutable** (`#TAG:tileset_defaults` raises
unless the row-major `.blitmask` width equals `columns`).

| form | verb | painted gids |
|---|---|---|
| GROW — whole rows, same width | `map.tileset.grow` *(exists)* | unchanged |
| RETIRE — out of the palette; the art keeps drawing | `tileset.tile.retire` | unchanged |
| TRIM — drop trailing slots | `map.tileset.grow`, smaller *(exists)* | refused while referenced |
| ~~COMPACT~~ — delete mid-sheet, close the gap | — | **PERMANENTLY REFUSED** |

Measured (§1.5): deleting one low id from `TileA2` silently repaints **10,210 of
10,210** of its cells, and on the `collision` sheet the id **is** the mask
value. **Retire is what "remove" means**; a tile genuinely gone is retire plus
repaint, one `run(...)`, one Ctrl+Z, across every map.

### 3.2 The scene — `data/project/scenes/<id>.json`

**Partly built.** `#TAG:parse_scene_vars` reads `format version id title doc
vars` and enforces `id` equal to the filename stem. The **eight further keys**
are refused by `#TAG:SCENE_KEYS` rather than accepted and discarded. **Each
joins `SCENE_KEYS` in `scripts/loaders/script_file.py` in the change that reads
it**; a runtime module may import those records, never restate them.

```json
{
  "format": "pyoneer.scene",
  "version": 1,
  "id": "overworld",
  "title": "The Overworld",
  "loadouts": ["core", "topdown_rpg"],
  "maps": [{"map": "starter", "entry": "start"}, {"map": "cave", "entry": "mouth"}],
  "entry_map": "starter",
  "vars": {"gate_open": {"type": "bool", "default": false, "doc": "Set by the keeper."}},
  "controls": {"steerable": true, "enabled_inputs": true, "simulated": true},
  "routes": [{"token": "interact_action", "payload": "keeper", "script": "keeper_gate"}],
  "on_enter": ["overworld_open"],
  "on_exit": [],
  "next": ["dungeon"]
}
```

- **`loadouts`** lives here, not in a pack, because law 2 forbids the engine
  reading a pack — which is what lets §5b.7 raise at **scene load**.
- **`maps`** is the ordered hierarchy of `config/maps.json` entries plus entry
  points; no `at: [x, y]`, and no `tilesets` key (derived).
- **`controls`** is the three `BodyState` agency axes, `null` meaning *leave
  alone*. A scene cannot rebind an input verb:
  `#TAG:InputActionManager.held` is an unguarded index (law 10).
- **`routes`** maps a `(token, payload)` to a script per scene, installed into
  `#TAG:ActionRouter` on entry — giving `#TAG:ActionRouter.clear` the caller its
  docstring names. See Q4.
- **`next`** is enforced: `enter_scene "dungeon"` in a scene whose `next` omits
  it raises at script load, naming both.

### 3.3 The tileset — `data/project/tilesets/<Name>.tileset`

**Not JSON.** `#TAG:TilesetFile` is complete, checked by
`tools/check_blitmap.py` and `tools/check_blitmap_engine.py`, with two
round-trip theorems; a JSON sibling is the shape the sibling-file ACTIVE
WARNING counts. Retirement needs **no new grammar** — `#TAG:TileEntry` carries
properties and `#TAG:Property.render` is `prop <type> <name> <value>`:

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

Retirement lives in the **shared** file, so maps cannot disagree about it. The
**only tmx change** is one property, `pyoneer_tileset`, on the `<tileset>`
element that already carries `pyoneer_collision`, read by a new
`declared_tileset` beside `#TAG:declared_collision`. **Drift is a hard
refusal**: embedded `tilewidth`, `tileheight`, `tilecount`, `columns` and
`<image>` must equal the `.tileset`'s, or load raises naming both files and the
field. **Path trap:** `#TAG:from_tmx_tileset` copies `<image source>` verbatim;
the `.tileset`'s `image` is relative to itself, via `#TAG:relative_image_path`.

### 4.6 Route B — `enter` / `exit` / `stay` region triggers

Route A (`use`) shipped, joined per object by `#TAG:script_of` in
`#TAG:MainGame.run_object_script`. For Route B, `editor/core/map_events.py` is
authored and checked (`tools/check_map_events.py`) and has **no runtime
reader**; its docstring says its home is `scripts/core/` and the move is
mechanical (only `Capability` and `RESERVED` come from `editor/`).

> **Move it to `scripts/core/map_events.py` and leave the editor module as a
> re-export** — law 2's corollary as written.

Then the seam in its measured **dict** shape (2,621 µs per frame at 256 regions
as components, 1.7 µs as a lookup): rasterise `MapEvent.cells()` into
`dict[cell_index, MapEvent]` once at load, compare cells per gated body per
frame, filter with `accepts()` — in one behavior token:

```
script_trigger   order=85   after animation_drive (80): reads THIS frame's position
                            before action_relay (90): a firing routes the same frame
```

`script_trigger` polls **no** input verb, so no `config/inputs.json` change
accompanies it (law 10). `auto` is not a region trigger; it fires from a
scene's `on_enter`.

### 4.7 The scene switch — four fixes INTO `SceneManager`

Still true: `#TAG:SceneManager.set_scene` is a pointer swap, so the old scene's
objects stop updating **and keep drawing**.

| fix | repairs |
|---|---|
| raise `PyoneerSceneError` (exists) naming the available scenes | a bare `KeyError` |
| unbind the outgoing scene from the renderer (`LayerRenderer.unbind` exists) | the keep-drawing bug |
| `actions.clear()`, then install the incoming `routes` | `ActionRouter.clear` has no runtime caller |
| `GameScene.end()`, clearing `flags["active"]` | only `#TAG:GameScene.begin` writes it, so a revisited scene never re-prepares |

`GameScene.end()` is the risky one — `core_lifecycle_prepare` already runs twice
by design — so its check counts hook calls both ways. The same stage gives the
namespaces lifetimes: `#TAG:VarStore` is one flat store today, so `scene.` is
not cleared on entry and `local.` is not per object.

### 5.1 The tileset editor — `editor/ui/tileset_window.py`

Every new screen is **non-modal** (`tools/check_editor_ui.py` enrols every
`editor/ui/*.py` and fails on `.exec()`), follows
`#TAG:qt_takewidget_sequence` (law 12), and greys a control that cannot act
with its reason. Wireframes are in the snapshot.

- `TilesetWindow(QMainWindow)` on the `#TAG:DatabaseWindow` recipe, reached from
  a menu **and** the palette header's existing context menu.
- **Left:** every PROJECT tileset with its maps and scenes
  (`Project.tileset_usage`); `collision` locked, its ids being
  `#TAG:MASK_DOMAIN`. **Centre:** the sheet via `#TAG:TilesetAtlas`, addressed
  by `section(name).rect(column, row)`. **Right:** an `InspectionView` over a
  new `"tileset"` arm of `#TAG:describe`, headed **`GROW HEADROOM: n — blocked
  by <sheet> at firstgid <g>`**, the minimum across every referencing map.
- **Grow** reuses `#TAG:TilesetImportDialog` with the width locked;
  `#TAG:growth_is_rows_only` stays the scripted route's gate. **Retire** is a
  non-modal pane naming every painted cell by map and layer, offering *empty /
  another tile*, and listing the one-undo batch.
- **Broken states:** no tilesets; missing art (surface `TilesetAtlas.missing`,
  which the canvas already reports); an external `<tileset source=…>`
  (`#TAG:MapDocument.require_known_extents` refuses — show it); a
  collection-of-images sheet (CLAUDE.md's known gap).

### 5.2 The scene screen — `SceneDock(ScopedDock)`, `editor/ui/scenes.py`

A dock in `EditorWindow.docks`, so it refreshes and has a View entry: scenes
(`+ New…`, `Duplicate`, `−`), the ordered map slots (order is the hierarchy),
and an `InspectionView` over a `"scene"` arm whose `controls` axes are
**three-state**. A slot naming an absent map is a hard `RuleViolation` with
`fix="project.map.add"` — hence Stage 2 first.

### 5a.3 The reply and the refusal

`response.jsonl` is **unchanged** — `#TAG:parse_response` must not learn a second
grammar. A responder's reply is a sidecar; a refusal ships **no**
`response.jsonl`:

```json
{"format": "pyoneer.relay.reply", "version": 1, "answer": "",
 "refused": "Widening the shoreline needs the map resized, and no verb resizes a map.",
 "unresolved": ["should the shoreline wrap, or should the map grow?"], "commands": 0}
```

The **back channel**, written by the editor into the bundle from the existing
`except` arm when an apply fails:

```json
{"format": "pyoneer.relay.refusal", "version": 1, "failed_line": 2,
 "message": "map.tile.set_many: argument 'tiles' wants list, got str",
 "rolled_back": true, "applied": 0}
```

### 5a.4 No partial application; read NOTES.md back

`#TAG:CommandStream.apply` is all-or-nothing, so `"applied": 0` is fact, not
policy, and the review has **no per-command checkboxes** (a hand-picked subset is
a response nobody wrote). The failure no machine sees is a response that applies
fully and does **less than asked**: the bundle tells the responder to write
`NOTES.md` and nothing reads it. **The box shows it** after a successful apply.

### 5a.5 Review before it applies

Keep the `QFileSystemWatcher` on `editor/requests/`, the half-written guard,
and a Problems row, never a modal. Add an **Incoming** section to
`#TAG:ManifestDock`: `reply.json`'s `answer`, then a row per command rendered
through the verb's `Param.doc`; expanding a row shows **before → after by asking
the verb for its own inverse** (free, mutates nothing, scales to every verb); a
green/red verdict per row from the non-mutating `#TAG:Verb.validate`; a
`refused` reply with Apply disabled. Staged notes persist too:
`#TAG:Manifest.from_json` gets a caller at `Session.open`.

### 5a.6 One undo step — and the two doors, an OPEN question

Apply goes through the incumbent `window.run(commands, label=…,
source="response:<id>")`: one `run`, one `Transaction`, one Ctrl+Z.

**Do not act on the snapshot's "collapse `EditorWindow.apply_response` onto
`Session.apply_response`".** It did not happen, deliberately:
`#TAG:EditorWindow.apply_response` declares itself a **second door**, and
`#TAG:Session.apply_response` records why the scope gate therefore lives in
`#TAG:read_response`, which both doors call. Stage 8 must first decide where
the review sits — in front of the window's door only, or behind a Qt-free
method both doors call — and whichever it picks, the sibling-route ACTIVE
WARNING binds: a guard on one door goes on both, or becomes one function.

### 5b.4 `enter_scene` — the scheduled core op

Portable, so core; it **registers only in Stage 6**, which fixes `set_scene`,
because before that its `run` would do nothing. No position argument: the scene
file's `entry_map` and slot `entry` own where the player stands.

### 5b.6 The worked loadout — `topdown_rpg`

In `scripts/game/flow/ops_topdown.py`, imported at the bottom of `ops.py`;
granted by adding `"topdown_rpg"` to that pack's `event_loadouts`; built against
tables on disk via `#TAG:scripts/loaders/table_file.py`.

| name | arguments | status | why not core |
|---|---|---|---|
| `actor_set` | `actor`, `column`, `to`, `by="assign"` | live | the whole hp/exp/level family; `column` checked against `actors` **at script load** (`#TAG:actor_row`'s shape). The packs already spell columns differently |
| `actor_has` | condition `{"actor": "1", "column": "hp", "at_least": 1}` | live | reuses the six comparators |
| `party_add` / `party_remove` | `actor` | live | a party is an RPG noun; removing the last member refuses |
| `party_has` | condition `{"party_has": "1"}` | live | RPG Maker's page condition |
| `walk_to` | `who`, `x`, `y`, `speed=0` · yields | live | tile space, no gravity |
| `face` | `who`, `dir` | live | a side-on body has two facings |
| `give_item` | `item`, `count=1` | needs-host | no project has `table:items` |

No new registry, dispatch or editor code: `#TAG:OpPicker` already sections by
`OpSpec.loadout`. Stat writes go to a per-run overlay, never
`data/project/tables/`.

### 5b.7 Wrong-loadout raises — the missing half

Already true: the picker greys an ungranted op with its reason, `#TAG:GenrePack`
reports a soft `RuleViolation`, and the script reader raises for an op outside
the script's own `loadouts`. **Missing, and blocked on Stage 6:** the **scene
load** raise for a script whose `loadouts` are not a subset of the scene's,
naming scene, script, page, node and both lists.

### 6.1 Tileset verbs (Stage 3)

| verb | arguments | inverse |
|---|---|---|
| `tileset.create` | `name`, `image`, `tile_width`, `tile_height`, `columns`, `count` | `tileset.delete {confirm: true}` |
| `tileset.delete` *(destructive)* | `confirm: bool` | `tileset.restore {text: <render()>}` |
| `tileset.restore` | `text: str` | `tileset.delete {confirm: true}` |
| `tileset.grow` | `count`, `image=""`, `image_height=0` | itself, previous values |
| `tileset.rename` | `to` | itself, swapped |
| `tileset.tile.retire` | `tiles: list[int]`, `force=false` | `tileset.tile.restore` |
| `tileset.tile.restore` | `tiles: list[int]` | `tileset.tile.retire {force: true}` |
| `tileset.tile.set` | `tile: int`, `key`, `value` | itself, previous value |
| `map.tileset.link` | `name`, `first_gid`, `tileset` | `map.tileset.unlink` |
| `map.tileset.unlink` | `name`, `first_gid` | `map.tileset.link` |
| `map.tileset.sync` | `name`, `first_gid` | itself, previous geometry |

`tileset.*` verbs take `tileset:*`, `map.tileset.*` take `map:*`. `restore`
carries rendered TEXT (a proved round trip; a dict is a second spelling).
`grow` and `rename` **fan out** to the per-map verbs in one `run`; `grow`
pre-flights headroom in **every** map and refuses all-or-nothing, naming the
short one. A linked sheet refuses `map.tileset.rename`. `retire` refuses while
painted unless `force`, naming each map and layer, and always on `collision`.

### 6.2 Project verbs (Stage 2)

`project.map.add {name, identifier, file}` ↔ `project.map.remove {name}`
*(destructive)*, whose inverse `project.map.restore {entry: dict, at: int}`
carries the entry and its index. All at scope `project`. `remove` refuses while
a scene names the map, naming the scenes.

### 6.3 Scene verbs (Stage 6)

All at `scene:*`, each with an exact inverse:
`scene.create {id, title}` / `scene.delete {confirm}` *(destructive)* /
`scene.restore {scene: dict}`; `scene.set {key, value}` (returns `None` when
unchanged) / `scene.unset {key}`; `scene.map.add {map, entry="", at=-1}` /
`scene.map.remove {map}` / `scene.map.move {map, to}`;
`scene.var.set {key, type, default, doc=""}` / `scene.var.remove {key}`
*(destructive)*; `scene.route.set {token, payload, script}` /
`scene.route.remove {token, payload}`.

Every family regenerates `docs/COMMANDS.md` (`tools/check_docs.py --write`) in
the change that adds it.

---

## 7. The build order — unbuilt stages

Each ends in a **gesture** a human performs and a **check** proving both halves
of every invariant, with a reported mutation (laws 5 and 6).

### STAGE 2 — a second map · 1–2 days · gates 3 and 5.2

**Ships.** §6.2; `Project.save()` writing `config/maps.json` on the tables'
deterministic contract; a settable `EditorWindow.map_name` with a toolbar
combo; `MapCanvas` re-targeting. **Gesture:** `File ▸ New map…`, pick it,
paint, switch back, Ctrl+Z. **Check** — `tools/check_project_maps.py`: a second
map is in `known_scopes()`, paintable and byte-exact / removing a map a scene
names refuses naming it, an unreferenced one goes; the other map's bytes never
move. **Why it gates:** every cross-map number is untestable with one map.

### STAGE 3 — the tileset editor · 4–5 days · after 2

**Ships.** `tileset` scope with its `describe_scope` and `describe` arms;
`.tileset` documents under §2.5; §6.1; `declared_tileset`;
`Project.tileset_usage`; the drift refusal; §5.1's window; `#TAG:TilePalette`
refusing to stamp a retired tile; and a first non-check caller for
`#TAG:plan_intern` / `#TAG:apply_intern`, which promote an embedded sheet to a
shared document. **Gesture:** tileset window → `TileA2` → `Promote to shared…`
→ second map → `Link…` → tile 194 → `Retire` → the pane names every painted
cell in both maps → pick a replacement → **one Ctrl+Z takes all of it back.**
**Check** — `tools/check_tileset_shared.py`: a retired gid cannot be stamped / a
live one can; a grow with headroom everywhere is one transaction / short in one
map it refuses entirely, naming it, others byte-identical; a drifted
`.tileset` raises naming the field / a matching one loads; both theorems hold
with a retirement property; retire-undo and delete-undo leave bytes and file
as found; `modals() == []`. **Mutation:** pre-flight only the first map.

### STAGE 6 — scenes · ~3 days left · slots beyond one map need 2

**Ships.** §3.2's eight keys, each joining `SCENE_KEYS` with its reader; the
`scene` scope; §6.3 with scene documents under §2.5 on `#TAG:ScriptLibrary`'s
pattern; §5.2; §4.7's fixes and the namespace lifetimes; `main.py` reading
scenes with **today's boot unchanged for a scene declaring only `vars`**; and
`enter_scene` (§5b.4), making core eleven. **Gesture:** Scenes dock → `+ New…`
→ two map slots → `on_enter` → Play; `enter_scene dungeon` walks through a
door, the first scene stops drawing, `gate_open` survives the round trip.
**Check** — `tools/check_scenes.py`: the leaving scene stops updating AND
drawing / the incoming one is bound; `set_scene("nope")` raises naming the
scenes / a known one does not; the router holds none of the old routes /
exactly the new; a revisited scene prepares again / no over-preparing (probe
counting hooks); a self-naming scene raises / an honest chain walks;
`tools/smoke.py --frames 60` shows no drift (law 11). **Mutation:** drop
`actions.clear()`.

### STAGE 7 — region triggers · 3 days

**Ships.** §4.6: the move with its re-export, load-time rasterisation,
`script_trigger` at order 85, `docs/BEHAVIORS.md` regenerated. **Gesture:**
paint a region in the Actions panel, attach a script, **walk into it**.
**Check** — `tools/check_script_trigger.py`: entering fires once / staying does
not re-fire while `stay` does; an excluding `filter_class` fires zero times / an
including one once; `once` and `cooldown_ms` both ways; law 2 on the moved
module, `tools/check_map_events.py` green through the move. **The
`NOT_WIRED` banner comes down in the same change** —
`tools/check_actions_panel.py` pins it and it becomes a lie.

### STAGE 8 — back channel and review · 2 days · independent

**Ships.** §5a.3–§5a.5, after answering §5a.6. **Gesture:** a response lands →
the box lights → the Manifest dock shows `(12,4): 0 → 65` under an expanded row
→ one click → **one undo step**. **Check** — `tools/check_relay.py`, extended: a
`refused` reply applies nothing, bytes unchanged / a clean one applies all as
one transaction; a mid-batch failure rolls back and writes `refusal.json` / the
good command never landed; undo restores the bytes and `history()` carries
`source == "response:<id>"`; both doors produce the same transaction; the diff
names the old gid and the review mutates nothing.

### STAGE 9 — the `topdown_rpg` loadout · 2 days · deliberately last

**Ships.** §5b.6's specs; the pack grant; `docs/EVENTS.md` regenerated; §5b.7's
scene-load raise once Stage 6 has `loadouts`. **Gesture:** the picker shows a
Top-down RPG section; switch the genre to `platformer` and the script's
`walk_to` row turns red with its reason. **Check** — `tools/check_loadouts.py`: a
`topdown_rpg` script loads under that pack / raises at scene load under
`platformer`, naming op and lists; an unregistered loadout in a pack raises /
a valid pack loads; `actor_set` on an unknown column raises at script load / a
known one does not; every core op is reachable from both packs. **Why last:**
the author asked for the portable handful first.

### Q3 — the `ChoiceBox` that lets `ask` run · a half-stage · independent

`ask` is authorable and in the picker, and **raises at runtime** because no
widget reports a choice. **Ships:** a choice host beside the `say` host, driven
by the `up`, `down` and `action` verbs already bound in `config/inputs.json` (no
binding change, law 10), writing the chosen index into the declared `into`
variable; `ask`'s status moves to `live`. **Check:** extend `tools/check_ops.py`
and `tools/check_event_docs.py` — `ask`'s runtime column flips to yes / a run
with no choice made writes nothing and stays held.

---

## 8. Deferred, with what unblocks each

| deferred | blocked on |
|---|---|
| a bounded `repeat n` | a design pass; an unbounded loop never |
| `parallel` triggers | a second, non-borrowing runner — two flows would each restore agency the other changed |
| per-verb scene control profiles | a new `BodyState` axis and a guarded `held()` (law 10) |
| screen effects | a post-process stage in the blit queue |
| a save system | its own change; the variable store dies with the process |
| native `.blitmap` collision beyond level one | `#TAG:field_from_map` returns `None` for a source serving its own `object_records` |

Refused permanently, besides §5b.5: tileset compaction, an expression language,
a `GameEventType` for triggers, a modal picker, a pack defining an op body, a
map overriding a shared sheet's geometry, per-command review checkboxes, and a
second registry, `EventBus`, `SceneController` or `foo_v2.py` of anything.

## 9. Open questions — each with a default, so work starts without an answer

**Q1 — Is "remove a tile" retirement?** Default: yes, §2.4, in Stage 3.

**Q2 — A second map as a feature or a fixture?** Default: a feature (Stage 2);
otherwise the blast-radius pane shows a constant.

**Q3 — `ask` needs a choice host.** Default: the half-stage above; until then
`ask` stays honestly `needs-host`.

**Q4 — Does a scene still need `routes`?** The per-object join shipped first
(`pyoneer_script`, `#TAG:script_of`, one handler in `main.py`). `routes` only
earns its key when a `(token, payload)` must mean a different script per scene
with no script on the object. Default: build it in Stage 6; drop it from §3.2
first if no scene needs it — a minted key cannot be un-minted (law 8).

---

## The checks this spec plans

`tools/check_docs.py` refuses a `check_*` a live document names unless it is
on the roster or declared here, and refuses a declared name that has reached
the roster — so the stage that lands a check deletes its line.

```planned-checks
check_project_maps
check_tileset_shared
check_scenes
check_script_trigger
check_loadouts
```

## Appendix — permanent strings still to mint

Law 8 makes each stable the day it lands; this list is the review surface.
Scope kinds `scene` `tileset` · tmx property `pyoneer_tileset` · tileset
property `pyoneer_retired` · formats `pyoneer.relay.reply`
`pyoneer.relay.refusal` · scene keys `loadouts maps entry_map controls routes
on_enter on_exit next` and a slot's `map entry` · core op `enter_scene` ·
loadout ops `actor_set actor_has party_add party_remove party_has walk_to face
give_item` · behavior token `script_trigger` · `reply.json` keys `answer refused
unresolved commands` · `refusal.json` keys `failed_line message rolled_back
applied` · the §6.1–§6.3 verb names.
