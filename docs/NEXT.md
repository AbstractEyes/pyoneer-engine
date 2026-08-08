# What to do next — one ranked list

Base state verified this session: `tools/check_all.py` → **ALL 18 CHECKS PASS,
NO DRIFT**. Working tree clean, `main` pushed. The editor (`editor/`) is new
and its two checks are in the suite.

Everything the previous version of this document ranked has been done: the
remote exists, `dispatch_counts` landed, the latent-bug batch landed, empty
layers are no longer baked, the map composite ships, `MapDocument` exists with
a byte-exactness check, and `resize()` plus the bounds cascade drive the
window, grid, anchors and scrollbars.

---

## The ranked list

### 1. Object layer → entity spawn — **M**

**What:** make an object placed on the `entity` layer become a live entity in
the running game.

**Why it is first:** the authoring half is now finished and the runtime half
is missing, which is the worst possible split. `MapDocument` writes objects
byte-exactly, the editor can place them with a click, `OBJECT_CONVERTER`
(`scripts/core/depth.py:25`) already maps class names to depths, and
`ComponentFactory` is a complete name→constructor registry. `renderer.py`'s
layer loop does `if not isinstance(layer_data, pytmx.TiledTileLayer):
continue`, so object groups are skipped with no seam at all. Every
prerequisite exists and nothing is connected.

**Design decisions already taken** (see `docs/PLAN_EDITOR.md` and the genre
packs): an object names its class in the tmx `type` attribute, custom
properties carry per-instance data, and the spawn registry is separate from
the widget `ComponentFactory` because they are different namespaces.

**Verify:** a new check asserting that an object authored into `test.tmx`
becomes a bound entity at the depth `OBJECT_CONVERTER` gives its class.
Expect deliberate `blit_tokens` drift when the entity starts drawing; inspect
it, do not bless it blind.

### 2. `MapDocument.add_layer` / `remove_layer` — **S**

**What:** create and delete `<layer>` and `<objectgroup>` elements.

**Why here:** it is the only reason the editor has no `map.layer.add` command,
and "include or remove layers" is a stated requirement. Adding is additive
and safe; removing must restore surrounding whitespace exactly, the same
problem `remove_object` already solved (it puts a self-closing element back to
self-closing). Follow that pattern.

**Constraint the packs already state:** a new layer name renders only if
`scripts/core/depth.py`'s `MAP_DEPTH` maps it. Adding a layer without adding
the depth is the silent-drop failure that cost 39 authored tiles once already,
so `add_layer` should warn when the name is unmapped.

**Verify:** extend `check_tmx_roundtrip` — add-then-remove a layer returns the
original bytes, exactly as add-then-remove an object already does.

### 3. Live reload from the editor — **S**

**What:** after `Project.save()`, tell a running game to re-read.

**Why here:** cheap, and it changes what the editor feels like. Both halves
exist — `AssetMapManager.load_assets(name, reload=True)` and
`renderer.invalidate(band)` / `rebake_map()`. What is missing is a channel.
A file mtime poll in the game loop is enough for v1; do not build a socket
protocol before something needs one.

**Verify:** edit a tile, save, and watch it change in a running `main.py`
without a restart.

### 4. `GameComponent` decomposition — **L**

Still the author's named priority and still the right destination. ~9
responsibilities in one file. `docs/IMPROVEMENT_PLAN.md` segment 8.

**Why not higher:** it is a multi-session change and the three items above are
each one session that leaves a green tree. Do the dead-code purge
(`IMPROVEMENT_PLAN` segment 2, ~1,100 lines) in the session immediately
before starting it — it buys honest greps exactly when a large refactor needs
them.

### 5. Boot cost, 230 ms → 640 ms — **M**

Map compositing proves its merges are lossless with `pygame.mask` work at
startup. One-time cost buying 2.6 ms per frame; pays back in ~150 frames, so
nothing is blocked. Worth fixing before anything else is measured against it.

**Do not** solve it by caching the proof — that was tried, and it broke live
map editing, which item 3 depends on.

### 6. Listbox, then drag-and-drop — **M**

`ListBoxComponent` has never run. The grid it needed now exists; what is
missing is row selection, keyboard navigation and a row template on
`GridComponent(max_columns=1)`.

Drag-and-drop is next and small: `GridComponent.snap()` places by pixel
position and `MOUSE_DRAG_BEGIN`/`END` are bindable. Nothing joins them.

### 7. The scroll bar's construction formula — **S**

`__scroll_bar_bounds` and `__scroll_bar_with_offsets` disagree, and the bar
shifts 14 px on its first scroll event. Cosmetic, isolated, well understood.

### 8. Replace the art — **M**

`data/graphics/` is not in the repository or its history and cannot come
back; see `docs/ASSETS.md`. `tools/make_placeholder_art.py` unblocks the
checks. Each genre pack ships an `ART.md` written to be pasted straight into
an image model, and the editor has **AI → Copy the art brief**.

---

## Not yet, and why

- **A socket protocol between editor and game.** Item 3 does not need one and
  building it first would fix a shape before anything has pushed on it.
- **More genre packs.** Two is enough to prove the abstraction. A third
  before the platformer one has produced a real game is speculation.
- **Mechanising "do not restructure the event system".** It is prose in every
  `RULES.md` today. Mechanise it the first time it is violated, not before.
- **`scripts/core/engine.py` singleton facade.** Additive, zero behaviour
  change, unblocks nothing, and its headline justification is dead: import
  cost measures 51 ms, not the documented 423 ms.
- **V8 renames.** Rename once, at the end, not twice. Checks and docs bind
  the current names.

## Standing corrections

Carried forward because each one has already cost a session:

1. **`bind_component`'s command list is NOT a no-op.** `component.py:441-449`
   calls `core_lifecycle_prepare_pre/prepare/prepare_post/build` on the child
   **directly**. Deleting `Panel.core_lifecycle_build` or
   `ScrollComponent.core_lifecycle_build` on the theory that they never run
   destroys the window. They run, and they build most of the UI.
2. **`flags["built"]` guards the fan-out, not subtree construction.** Both
   overrides above call `super()` first and then run their body
   unconditionally. Harmless today; a trap the moment anything rebuilds.
3. **`COMPONENT_TODO.txt:136-139` misstates the scroll thumb symptom.**
   Construction-time sizing is correct (measured 118 vs 6). The defect is
   post-construction only. The recorded remedy is right; the symptom is not.
4. **The layer is spelled `Paralax`, with one L**, in `test.tmx` and in both
   genre packs. `scripts/core/depth.py` aliases it rather than renaming, to
   keep the file byte-identical for Tiled.
