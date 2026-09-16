<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every open item was re-measured on 2026-09-16 by the command beside it. -->

# Next — what is open, and the command that measured it

1. **Item numbers are permanent ids.** Code cites items by number: item 16 is
   cited from `scripts/core/event_manager.py` and `tools/check_event_queue.py`,
   and item 29 from `tools/check_editor.py`. So a number is never changed and
   never reused. A new item takes the next unused number (**46**), and a
   closed item moves to *Closed* at the bottom and keeps its number.
2. **Rank is the section, not the number.** Sections run from most to least
   expensive; within a section, earlier means more urgent.
3. **Run the item's command before you act.** If the output has moved,
   re-measure the item and rewrite it or close it.
4. **One home.** An engine trap is described in `CLAUDE.md`'s *Known gaps*;
   the item here is the work that removes it and points there.

Before the list: `tools/check_all.py` says what is broken now,
`tools/smoke.py --frames 60` says whether the frame moved, and
`grep -n "| \`" docs/BEHAVIORS.md` says what is actually wired.

## Breaks a map or loses work

### 38. A control character in a relay string makes the saved map unloadable

`#TAG:_escape_attribute` escapes only `& < > " \r \n \t`, and
`#TAG:text_reads_back` returns True for any `str` attribute, so
`#TAG:_checked_attribute_text` lets a C0 control character through. Eleven
relay parameters accept one: `map.layer.add` name; `map.object.add` name and
type; `map.object.set` value; `map.object.property.set` key and value;
`map.object.action.restore` value; `map.tileset.add` name and image;
`map.tileset.grow` image; `map.tileset.rename` to. A lone surrogate is worse:
`MapDocument.to_bytes` raises when it encodes, so `Project.dirty` raises too.

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'tools'); import _bootstrap
from scripts.loaders.map_document import _escape_attribute as esc
from scripts.core.layer_profile import text_reads_back as ok
import xml.etree.ElementTree as ET
v = 'a\x01b'; print('guard passes:', ok(str, v))
ET.fromstring('<map name=\"%s\"/>' % esc(v))"
```

Expected: `guard passes: True`, then `ParseError: not well-formed`. Fix:
`text_reads_back`, which both guards already call, should refuse whatever XML
1.0 cannot carry. Add a fixture for each parameter.

### 37. Removing an object can make a saved map reuse its id

`#TAG:MapDocument._release_object_id` (and `_release_layer_id`) lowers the
counter whenever the removed id is one below it, which is not the same as
asking whether this session handed the id out. Take a map Tiled wrote
(`nextobjectid="9"`, highest id 8): remove 8, save, reload, add one, and the
ids are `[7, 8]`. A relay scope ending `object:8` now points at a different
object. A remove followed by undo also leaves the map dirty.

    grep -n "_release_object_id\|_release_layer_id" scripts/loaders/map_document.py   -> 4: two defs, two unconditional calls

Fix: record the ids this session claimed, and release only those.

### 30. Two things the editor cannot write at all

- **No way to remove a stray `pyoneer_`-named XML attribute.** An older map
  can still carry one, and the map becomes unloadable as soon as the real
  property is added. `map.object.unset` has to keep
  `choices=_OBJECT_ATTRIBUTES`, because its inverse is `map.object.set`, so
  this needs a new verb whose inverse is a restore.
- **No writer for `data/project/scenes/*.json`,** only a reader
  (`scripts_of` → `load_vars`). Declaring a scene variable takes a text editor
  and a restart (item 36).

      grep -c "_OBJECT_ATTRIBUTES" editor/core/verbs.py   -> 4
      grep -c '"scene\.' editor/core/verbs.py             -> 0

### 35. `Project.save` writes the map before the script

`#TAG:Project.save` writes maps, then tables, then `project.json`, then
scripts. If a script write fails, the map on disk names a document that does
not exist, and the next boot raises `PyoneerAssetMissingError`. The failure is
announced and the window stays dirty. Fix: write scripts first, or stage all
the documents and commit once.

    grep -n "def save" -A 57 editor/core/project.py | grep "__open_maps\|meta_path =\|library.save"   -> maps first, library.save() last

### 36. A scene variable needs a restart, and a hand edit can be overwritten

`#TAG:scripts_of` caches one `ScriptLibrary` per `Project` and reads the
scene's `vars` once, so a hand-edited scene file only shows up after a
relaunch. The editor never notices a file changing on disk underneath it, so
one in-editor edit plus Ctrl+S overwrites a hand-edited
`data/project/scripts/` document. Fix: invalidate the cache, and check the
file on disk before saving.

    grep -c "def reload\|def invalidate" editor/core/event_script.py   -> 0

## What a player or author hits first

### 44. Two of three prompt strips never refresh the Manifest dock

`PromptStrip` is built in three windows and only the dock's connects `staged`
to `refresh_manifest`. A note staged from the Database window or the Script
editor is in the session but not in the Manifest dock until something else
refreshes it. The fifth ACTIVE WARNING's shape; one shared construction
closes all three.

    grep -rn "PromptStrip(\|staged.connect" editor/ui --include=*.py   -> 3 strips, 1 connect

### 23. The demo window's text box grabs the keyboard at launch

`main.py` builds a `DemoWindow` at boot, and its text box says "Type here".
One click makes the game ignore movement and the action verb, and only F1
brings input back. Every demo already closes this window, in
`#TAG:DemoGame.load_test_objects`, for this reason. Fix: close it in the game
too, or release input capture on a click on empty ground.

    grep -n "DemoWindow(bounds" main.py   -> built at boot

### 22. The dialogue box's inherited close button freezes the player

`ScriptBox` derives `GameWindow` and keeps its red X. Clicking the X hides the
box, but the `ScriptRun` keeps going with `steerable` False, so the hero
cannot move (0 px over 40 frames of held `right`). The only way out is to
press the action verb without seeing anything. Fix: hide the X, or route it
into `#TAG:ScriptDialogue.say_close`.

    grep -c "close_button" main.py   -> 0: the X is never hidden or rerouted

### 21. The dialogue box covers the speaker, and the demo window covers the box

`#TAG:DIALOGUE_BOUNDS` hides 75% of the hero's height. The boot `DemoWindow`
overlaps 57% of the box on the same UI layer. **Deferred**, because moving the
box changes the frame (law 11). The measured candidate is
`Rect(120, 540, 784, 170)`.

    grep -n "DIALOGUE_BOUNDS: Rect\|DemoWindow(bounds" main.py   -> Rect(120, 400, 560, 120), Rect(100, 100, 400, 400)

### 24. Two loose ends of the script wire (the first of three closed)

- `interact_action` has no range or facing test, so the hero can trigger
  itself from anywhere. It needs the region-trigger wire in item 39.
- No cooldown: twelve presses in 24 frames played the chime 5 times. The
  `cooldown_ms` parameter already exists, so the fix is one map property
  (`pyoneer_param_cooldown_ms`), set through the editor.

      grep -c "cooldown_ms" data/maps/starter.tmx   -> 0

### 26. A body with `pyoneer_param_payload` never reaches its event script

`main.py` routes the interact token with `ANY_PAYLOAD`, and `ActionRouter`
prefers handlers that match the exact payload. So a body with a payload and a
`pyoneer_script` never starts the script, and nothing warns. The shipped
`StoryDemo` is the setup that hits this first. Fix: a second route, or a
starter that knows about payloads, in `demos/story.py` or
`scripts/game/flow/router.py`.

    grep -n "ADVANCE_PAYLOAD =" demos/story.py; grep -c "ANY_PAYLOAD" main.py   -> "keeper"; 1

### 25. `ScriptEditor`'s `New...` stays enabled when the grant offers no ops

This is latent, because both packs grant `["core"]`. With a grant of `[]`, the
window says scripting is off and still creates a document. Fix: gate
`#TAG:ScriptEditor.create_script` on `grants_nothing`.

    grep -n "def create_script" -A 12 editor/ui/script_editor.py | grep -c grants_nothing   -> 0

## Wrong but survivable

### 31. `pyoneer_param_<key>` is the one per-object link the editor does not check

`#TAG:GenrePack.validate` resolves the other three links (script, actor,
behaviors) through the engine's own readers. A bad parameter still only raises
at spawn, in `resolve_params`, because the reader that judges parameters,
`read_requests`, also emits warnings as it runs. Fix: a judging path that does
not warn, with the actors row passed in.

    grep -c "OBJECT_LINKS" editor/core/genre.py; grep -c "PARAM_PREFIX" editor/core/genre.py   -> 3; 0

### 6. The editor and the engine disagree about a tileset's pixels in two ways

The first is the collection-of-images tileset in *Known gaps*. The second is a
margined sheet: pytmx's tile count ignores `margin`, so it counts rows that
`tileset_geometry` and Tiled both say do not exist. `tileset_geometry` is
correct (it reduces to Tiled's `columnCountForWidth`). Fix pytmx's side in a
reader of our own, or not at all.

```bash
.venv/Scripts/python.exe -c "from itertools import product
import sys; sys.path.insert(0, 'tools'); import _bootstrap
from scripts.loaders.map_document import tileset_geometry as geo
tiled = lambda W,t,m,s: (W-m+s)//(t+s) if W-m>=t else 0
ptmx  = lambda W,t,m,s: len(range(m, W+m-t+1, t+s))
cases = list(product(range(8,129),(8,16,24),range(0,9),range(0,5)))
cols  = lambda c: geo(c[0],c[0],c[1],c[1],c[2],c[3])[0]
print(sum(cols(c) != tiled(*c) for c in cases), sum(cols(c) != ptmx(*c) for c in cases),
      sum(c[2] == 0 and cols(c) != ptmx(*c) for c in cases), 'of', len(cases))"
```

Expected: `0 4230 0 of 16335`.

### 4. A native `.blitmap` gets no collision (see *Known gaps*)

A map converted away from `.tmx` walks differently from the map it came from,
and nothing says so. Build level one only: a converted `.tileset` already
carries `collision <ref>`, and a `.blitmap` has no companion layers.

    grep -rn "\.collision\b" scripts/loaders/   -> 4 lines, all in tileset_file.py, none a reader

### 2. Collision is still a mode

Both palettes are on screen together, but switching still retitles a dock and
swaps the tool set, so the author has to track which mode they are in. Fix:
one selection across both palettes, with `EditMode` derived from it. That also
removes the apology at `#TAG:tile_mask_is_level_one`.

    grep -c "EditMode.COLLISION" editor/ui/main_window.py   -> 4, the branches that go away

### 12. Two headless readers look up an object by id and act on whatever they find

`#TAG:object_at` and `#TAG:inspect._describe_object` look an object up by id
and write back to that scope, where the canvas and tree hold a
`SelectedObject` card. This is safe only because `EditorWindow.refresh_all`
rebuilds both panels after every command, and `editor/core/` cannot import the
card from `editor/ui/` (law 2). Fix: move `SelectedObject` (already Qt-free)
to `editor/core/identity.py`, add an `identify()`, and have all four readers
import it.

    grep -n "layer.find(" editor/core/behavior_view.py editor/core/inspect.py   -> 2

### 7. Four `GameEventType` members have no reference outside their definition

A member nothing listens for is a promise the engine does not keep (*Known
gaps*). Delete these four or wire them. The one `QUIT` hit is prose.

```bash
for m in POST_DISPOSE PARENT_RESIZED QUIT WINDOW_FOCUS_GAINED; do
  echo "$m $(grep -rn "$m" scripts/ --include=*.py | grep -vc event_types.py)"; done
```

Expected: `0`, `0`, `1`, `0`.

### 8. The two silent traps, in the order they will bite

Both are in *Known gaps*. `#TAG:GameAnimationHandler.__init__` raises for a
sheet that only has side-on or portrait frames, which is the first wall a new
art set hits. `#TAG:GameEntity.allowed_move` only becomes urgent once it has a
second caller. `tools/check_docs.py` section 5 verifies both anchors.

### 19. `get_pyo`'s two filtering arms can never be true

`event is int` and `event is pygame.event.Event` compare the argument to a
type object, so `get_pyo(pygame.KEYDOWN)` quietly returns `[]` (law 7). The
only caller passes no argument. Decide: use `isinstance` and add a caller, or
delete both arms and the parameter.

    grep -n "event is int\|event is pygame.event.Event" scripts/core/event_manager.py   -> 2

### 20. Two dead functions in `scripts/core/event_manager.py`, one of them wrong

`#TAG:PyoneerEvent.update_data` has no caller, and it calls
`.core_frame_update(value)` on a dict entry (left over from a global rename),
so it would raise on first use. `#TAG:queue` has no caller outside
`tools/check_event_queue.py`, so deleting it means editing that check too.

    grep -rn "update_data" --include=*.py .   -> 1, its own def

### 32. Two check modules still match calls by bare name

`tools/check_demo_map.py` and `tools/check_log.py` match `func.id`/`func.attr`
without following the import, so a method with the same name gets past them.
The repair already exists next door: `calls_through` in
`tools/check_behavior_docs.py`.

    grep -rln "func.id if isinstance" tools/*.py   -> those 2 files

### 33. `check_event_docs`' picker-row gate checks the name, not what it is

Section 4 only asks `hasattr(ops_module, n)`, and the op module re-exports its
own imports. One tuple entry can reopen a reachability row while the check
stays green: on 2026-09-11, appending `"CORE"` still exited 0. Fix: check that
the name really is a registry mapping.

    grep -n "hasattr(ops_module" tools/check_event_docs.py   -> 1

### 34. The event screen's footer never learns that a save happened

After Ctrl+S the star in the title clears, but the footer still says "Not on
disk yet". Separately, the footer reads `ScriptLibrary.dirty_scripts()`,
which leaves out removed documents, and the close prompt reads
`Project.dirty_scripts()`, which includes them.

    grep -n "def save" -A 12 editor/ui/main_window.py | grep -c script   -> 0

### 9. Two small, real and cheap

- A per-tile `<objectgroup>` adds a nameless phantom layer, because
  `#TAG:MapDocument._layer_elements` walks `root.iter()` where
  `_tileset_elements` uses `findall`. Tiled writes that shape.
- Palette zoom is lost between sessions. It belongs in
  `editor/core/settings.py`, beside `grid_step`.

      grep -c "self.root.iter() if element.tag in _LAYER_TAGS" scripts/loaders/map_document.py   -> 1
      grep -c "zoom" editor/core/settings.py                                                    -> 0

### 41. The genre packs spell the parallax layer `Paralax`

Both `editor/genres/*/genre.json` files declare the layer as `Paralax`, the
spelling `#TAG:LAYER_NAME_ALIASES` keeps only so old maps still load, while
`data/maps/starter.tmx` uses `Parallax`. So the packs write new content with a
spelling that once silently dropped 39 tiles (law 7). Fix: spell it
`Parallax` in the packs and keep the alias for old files.

    grep -c '"name": "Paralax"' editor/genres/*/genre.json   -> 1 in each

### 43. Nothing stops a credential before the commit exists

`tools/check_secrets.py` (closed item 10) only refuses at check time, after
the commit is made. A pre-commit hook is the missing half, and installing one
is repository configuration, so it is the author's decision.

    grep -rln "check_secrets" .git/hooks/ 2>/dev/null | wc -l   -> 0

## Unbuilt, decided or deferred

### 39. The unbuilt part of `docs/PLAN_SCENES.md` has no items of its own

This item points there. Still unbuilt: a second map with a tileset shared
between maps; the tileset editor screen; scenes and `enter_scene`; region
triggers (`script_trigger`, the `enter`/`exit` wire item 24 needs); the relay
back channel; genre loadouts; and a `ChoiceBox` host so the `ask` op runs.

    grep -c 'status="needs-host"' scripts/game/flow/ops.py   -> 1, the ask op

### 40. The design form has no row for an event script or a sound

`tools/check_prototype.py` knows 12 row kinds for `docs/DESIGN_TEMPLATE.md`'s
form, and none of them is a script or audio, so the newest features cannot be
designed on the form. Add the row kinds to the check and the template in the
same change.

    grep -n "^KINDS = " -A 1 tools/check_prototype.py   -> no script, no audio

### 42. Tier-2 map files give a line number for every symbol — decide whether to keep them

Every `docs/map/*.md` entry gives a line number, so any edit re-renders every
entry below it. At `99a1888`, 229 of 246 removed lines in `docs/map/` differ
from an added line only in that number, and the `#TAG:` is already the address
(law 14). Decide: drop the numbers (one change across `tools/gen_map.py` and
its tier-1 fixture in `tools/check_docs.py`), or accept the churn.

    for c in $(git log -10 --format=%h); do git show --stat --format= $c -- docs/map | grep -q docs/map && echo $c; done | wc -l   -> 9

### 45. Three editor decisions nobody has made

Evicted from `docs/PLAN_EDITOR.md` when its plan half was deleted; each is the
author's call, not a defect.

1. **Send from the window.** A response is written by hand or by an outside
   agent; a button that shells out to `claude -p` does not exist.
2. **"Do not restructure the event system" is prose.** Both genre packs'
   `RULES.md` say it and no check enforces it.
3. **A pack's `template/` folder is declared and unused.** `GenrePack.template_dir`
   has no caller and no pack ships one.

    grep -rn "claude -p" editor --include=*.py | wc -l                     -> 0
    grep -rln "restructure" tools/ | wc -l                                  -> 0
    grep -rn "template_dir" --include=*.py editor scripts tools | wc -l     -> 1, the definition

### 13. `Session.ask(..., also=...)` has no control in the window

Attaching an event script involves two addresses, and the widening that lets
one request carry both can only be used from code. The seam is
`#TAG:ScriptEditor.ask_here`. This is the fourth ACTIVE WARNING's shape.

    grep -rn "also=" editor/ui/ --include=*.py   -> 0

### 5. A tileset has a name and no internal structure

A 768-tile sheet is one undivided wall in the palette, and `TerrainSet`'s
`name` is empty for every autotile origin. A per-tile `pyoneer_group` property
already round-trips and reaches pytmx. Missing: a verb that writes one, and a
palette that draws labelled sections.

    grep -rn "pyoneer_group\|pyoneer_terrain" --include=*.py .   -> nothing

### 3. Nobody has measured whether Tiled keeps a reserved `firstgid` gap

This is not corruption (`#TAG:MapDocument.tileset_headroom` recomputes every
time), but a headroom refusal may promise something a Tiled round trip takes
away. To measure: save a map with a gap in Tiled, then run
`git diff --word-diff data/maps/<that>.tmx | grep firstgid`.

### 11. The collision palette has a minimum size (recorded, not a task)

`#TAG:_MaskSurface.__init__` sets a minimum size on a grid with no scroll
area, so the mask dock cannot shrink below 168x238, while the tile palette
beside it shrinks to 178x133. The author re-tabbed the dock by hand and said
to leave it. If anyone fixes it, add a scroll area. Do NOT delete the
`#TAG:mask_palette_is_never_tabbed` guard.

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'tools'); import _bootstrap; from PySide6.QtWidgets import QApplication; from editor.ui.collision_view import MaskPalette; a = QApplication([]); p = MaskPalette(); print(p.minimumSizeHint(), p.surface.minimumSize())"
    -> QSize(168, 222) QSize(160, 200)

### 14. Painting a tile on a hidden layer is allowed on purpose

Creating an object on a hidden layer is refused
(`#TAG:hidden_layer_refuses_creation`), because a hidden object cannot be
reached. A tile can be: it is addressed by coordinate, and it shows up again
when the layer is ticked. If the author asks for a guard, copy the object
refusal's shape.

    grep -c "hidden_layers" editor/ui/canvas.py   -> 10, none in the __commit_* methods

### 18. `prepare_test_scene` and `load_test_objects` are named for a retired map (deferred)

These are the boot hooks every demo extends, named for the retired
`data/maps/test.tmx`. Three checks assert the names as data, and
`demos/narrative.py` calls `super()`, so a partial rename leaves the suite
red. Do it in one pass that owns `main.py`, `demos/` and `tools/`, and run
`tools/gen_map.py --write` in the same change.

    grep -rln "load_test_objects\|prepare_test_scene" --include=*.py . | wc -l   -> 9 files, 6 under tools/

## Not on this list

Defects the suite already catches (`tools/check_all.py` lists those); a verb
that remaps gids across the whole map (headroom means nobody needs it yet);
and anything in [`history/`](history/), which you should re-measure before
believing.

## Closed

The ids stay here so citations keep resolving. Read the "what closed it"
column before re-filing anything.

| id | title | what closed it |
|---|---|---|
| 1 | `docs/BEHAVIORS.md`'s preamble declared the unregistered token `tile_collision` | the markdown cleanup, 2026-09-16: `grep -rn "tile_collision" docs/BEHAVIORS.md scripts/ --include=*.py --include=*.md` returns 0 |
| 10 | Nothing refused a committed plaintext credential | `tools/check_secrets.py`, `0b6227c` (2026-09-10). The pre-commit half is item 43 |
| 15 | The audio ops could not be reached from a running game | `0b6227c` (2026-09-10): scripts load at boot and the `action` verb starts a `ScriptRun`. The shortcut route was deleted |
| 16 | `pump_pyo`'s event-coalescing branch had never executed | deleted in `0b6227c` (2026-09-10). The repair this item proposed is WRONG; `#TAG:no_event_pooling` explains why |
| 17 | `driven_record` was copied into `demos/runtime.py` | `0b6227c` (2026-09-10): one definition in `scripts/loaders/map_loader.py` |
| 24 (first bullet) | A finished `ScriptRun` was never cleared from `SceneManager.flow` | `6ea1d61` (2026-09-11): `post_update` evicts a stopped occupant |
| 27 | `docs/BEHAVIORS.md`'s integration column was measured by detectors never seen to say `no` | `5be433e` (2026-09-11): `calls_through`, `assigns_field`, and row 4 also requires the attach |
| 28 | Adding a child re-indented its first sibling | `5be433e` (2026-09-11): `#TAG:MapDocument._separator_of` |
| 29 | `map.object.unset` plus undo restored the value but not the attribute order | `99a1888` (2026-09-11): `#TAG:attribute_order_read_off_the_file` |
