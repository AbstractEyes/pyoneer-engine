# What to do next — one ranked list

Base state verified this session: `tools/check_all.py` → **ALL 10 CHECKS PASS, NO DRIFT**. `git fsck` clean, 13 commits, 640 tracked files, working tree clean. No probes left behind; nothing outside `tools/` was read-modified.

---

## The ranked list

### 1. Push the repo to a remote, then Dropbox-ignore `.git` — **S**

**What:** create a private remote, push `master`, then re-run the repo's own script with the flag it is waiting for.

**Why it is first:** this is not bookkeeping, it is an active corruption risk that the repo itself documents. `tools/dropbox_ignore.ps1:8-11` says Dropbox forks files it catches mid-write and *"this repo already has one, from a MacBook, dated 2025-12-05."* I confirmed that conflicted copy still on disk (`.idea/workspace (Philips-MBP.attlocal.net's conflicted copy 2025-12-05).xml`) and confirmed `.git` currently has **no** `com.dropbox.ignored` stream — so 13 commits of history are protected only by the mechanism most likely to destroy them. `dropbox_ignore.ps1:19-21` states the resolution explicitly: *".git is deliberately NOT included… correct only once a git remote exists. Pass -IncludeGit once you have pushed."* The engine is currently one bad sync from a rebuild.

**Unblocks:** every other item on this list becomes revertible. Also the stated open-source goal, and any second machine.

**Verify:** `git fsck && git log --oneline origin/master | wc -l` → 13.

### 2. `smoke.py dispatch_counts` + close the `event=None` hole — **S**

**What:** add a `dispatch_counts` field to `tools/smoke.py` first (so the change shows as a reviewed number), then synthesize the missing event in `GameComponent.send_event_advanced` and make `core_lifecycle_build` actually write `flags["built"] = True`.

**Why it is next:** it is the cheapest structural unlock in any of the four documents, and it was measured **twice, independently, as producing a bit-identical `frame_hash`** (`bec3f3153713a6b2`, tokens 59, culled 4, census 113). Its no-drift property depends on `ShapeComponent.prepare_background` / `TextComponent.prepare_text` being idempotent — that is true today and every future surface-preparation change is a chance for it to quietly stop being true. The measurement has a shelf life; spend it.

**Unblocks:** V5 (migrating in-tree `core_*` to event binds) → V6 (registry collapse) → V7; `bind_component`'s `commands` list; every hand-written `core_lifecycle_build`; the popup-dismiss and drag-to-scroll guards that need real consumption. The back half of `PLAN_EVENT_SYSTEM` is entirely behind this.

**Verify:** `tools/check_all.py` — expect **no drift**, `blit_tokens` 59. If the hash moves, idempotence broke; that is a new bug, do **not** re-baseline over it.

### 3. Zero-drift latent-bug batch — **S**

Four unrelated fixes that provably cannot move a pixel, batched into one session:

- `mouse.py:17-31` — add `MOUSE_DRAG_BEGIN` / `MOUSE_DRAG_END` to `EVENT_TYPES`. Verified absent; both are emitted (`:238`, `:259`) and both are already in `component.py`'s `INPUT_EVENT_TYPES`. Zero call sites try to bind them today, so no listener can exist and the hash cannot move.
- Rename `DrawComponent.scale(width, height, destination)` (`draw.py:65`) — it shadows `GameComponent.scale(scale, sender)` (`component.py:232`), which `component.py:265-271` calls as `self.scale(scale, self)`. Latent only because nothing writes `"scale"` into `TRANSFORM` data. Item 7 will start writing exactly that.
- Delete the two pure-`super()` overrides: `Panel.core_lifecycle_prepare` (`panel.py:35`), `ScrollComponent.core_lifecycle_prepare` (`scroll.py:52`).
- `config/depth.json` + `config/managers/depth_data.py` + the `layers` block in `config/maps.json`: three dead depth registries, zero Python readers, and `maps.json` still disagrees with `depth.py` (`Parallax: 0` vs `1`).

**Unblocks:** drag work (panel drag-to-scroll, window resize) and item 7's rename prerequisite. Removing the divergent registries makes item 5's depth reasoning trustworthy.

**Verify:** `tools/check_all.py` — no drift.

### 4. Skip baking empty tile layers — **S**

`renderer.py:250-256` allocates a `1600×1600` `SRCALPHA` surface for every `TiledTileLayer` with no tile-count test. `Above1` has zero nonzero gids and still holds 10.24 MB and emits a blit token every frame (`baseline.json` `blit_depths["55"] = 1`). ~15 lines.

**Why here:** it is the cheapest memory-and-frame win in the tree and it is the natural warm-up for item 5 — it forces you into `__make_tile_layer` with a small, reversible change first.

**Verify:** `tools/smoke.py --frames 60` → `blit_tokens` 59 → **58**, `blit_depths["55"]` gone. Deliberate: `tools/smoke.py --frames 60 --write-baseline`, then `check_all.py`.

### 5. Two-surface map composite — **M**

`renderer.py:170-185` still blits six full-map layers per frame. Bake `{1: Paralax, 10: Floor, 30: GroundClutter}` into one `.convert()` surface and `{50: PlayerDepth, 55: Above1, 60: Foreground}` into one `.convert_alpha()`; entities at 40/41 still interleave between them. Measured **6.51 ms → 0.96 ms** on an 8.9 ms frame, plus `screen.fill` becomes dead work (Floor is 100% opaque in view).

**Why here and not first:** it is the largest single perf number available, but 8.9 ms is ~112 fps — nothing is blocked by it. It is worth doing before the decomposition so that work isn't measured against a noisy frame. **One design constraint the plans do not state:** bake behind an `invalidate(depth)` / rebake entry point, not in a constructor. Phase 5's headless map editing exists to mutate layers at runtime, and a composite with no rebake path is a wall built across the long-term goal.

**Verify:** `smoke.py --frames 60` → `blit_tokens` 58 → **54**, `frame_ms` ≈ 3.3. Deliberate drift: eyeball one frame against a pre-change capture, then `--write-baseline`.

### 6. `scripts/loaders/map_document.py` + `tools/check_tmx_roundtrip.py` — **M**

Byte-exact TMX load/serialize with object add/remove, plus a check that asserts it. ~200 lines. The round-trip is already **proven by execution** (133,940 bytes in, 133,940 out; add-then-remove returns the identical byte string) but proven **nowhere in the repo**.

**Why here:** this is the single load-bearing assumption under the entire "he edits in Tiled, an AI edits programmatically" goal, and it is currently unguarded. The day something reflows that 134 KB file, the goal dies to a merge diff. Three fixups do it, all measured: hardcode the declaration, one `re.sub(r"\s+/>", "/>")`, one `\n`→`\r\n`. Include property **type inference** — without `type="int"`, pytmx returns `depth` as the string `'50'`; that is load-bearing, not a nicety.

**Unblocks:** Phase 4 (object-layer spawn, ~80 lines once this exists) and Phase 5 (`tools/mapctl.py`). Also fixes `config/managers/map_data.py:12` cwd-relative paths, which currently `FileNotFoundError` from any directory but the repo root.

**Verify:** new `check_tmx_roundtrip` in `check_all.py`; `check_all.py` → 11 checks pass, no drift.

### 7. `DrawComponent.resize()` + the bounds-changed cascade — **M**

`grep "def resize" scripts/` returns nothing, confirmed. Add `resize()` that **allocates** (never `pygame.transform.scale` — `shape.py` and `text.py` both redraw from `world_bounds`, so stretching applies the size change twice), re-fires `PREPARE` on itself (PREPARE-with-a-real-event fires exactly once per process, at `renderer.py:147`), and matches `draw.py:29`'s construction exactly. Then the cascade: `local_bounds` setter (`component.py:403-408`, currently a bare assignment) → `_on_bounds_changed` → child relayout → surface, in that order.

**Why here:** it is the first visible-quality fix and the first genuine slice of the decomposition — it forces the construct-once / lay-out-every-time split on `Button.__make`, `Panel.core_lifecycle_build`, and `GameWindow.core_lifecycle_prepare` that 8.1 and 9 both need anyway.

**Unblocks:** window resize, grid layout, listbox, panel drag-to-scroll.

**Verify:** deliberate `frame_hash` drift and re-bless. Prove the fix directly: build a `Panel(300×200, working_area 300×210)`, set `vertical_scroll.scrollable_bounds` to `Rect(0,0,300,4000)`, assert the thumb's `ShapeComponent` **surface** goes `(14,118)` → `(14,6)` — today the logical bounds move and the surface does not.

### 8. V5 — migrate in-tree `core_*` to event binds, then enforce the rule — **M**

`Panel.core_lifecycle_build` → `event_bind(BUILD, …)`, same for `ScrollComponent`; fold `MouseComponentAsync`'s four binds into `__init__` and delete its override; bind `Panel.core_frame_update` to UPDATE (it has run **zero** times, boot or steady — `__clamp_scroll` and `__hide_unhide_scroll` have never executed). Then add the assertion to `check_events.py`: no class with a parent may define `core_*`.

**Hard prerequisite: item 2.** And read the correction in the next section before touching the migration table.

**Verify:** `check_all.py` + `dispatch_counts`; expect deliberate drift when `Panel.core_frame_update` starts running, and inspect it rather than blessing it blind.

---

## Top item, in enough detail to start now

**Goal:** history survives a Dropbox sync fork.

1. Create a **private** GitHub repo (do this yourself — I can't create accounts, and it's your call whether it goes public now or after the API stabilizes; private now, flip later, is the right sequencing given the naming schema is still in motion). `gh repo create Pyoneer --private --source=. --remote=origin` from `S:/Dropbox/Pyoneer` does it in one step if `gh` is authenticated.
2. `git push -u origin master`.
3. Confirm: `git log --oneline origin/master | wc -l` → `13`; `git status` → clean, nothing ahead.
4. `powershell -ExecutionPolicy Bypass -File tools\dropbox_ignore.ps1 -IncludeGit`. That is the flag `tools/dropbox_ignore.ps1:21` is explicitly waiting on. Expect it to print the ignored-path count without the `.git left syncing` trailer.
5. Prove step 4 took: `Get-Item -Path .git -Stream com.dropbox.ignored` must now return a stream. I checked today and it does not exist.
6. Optional cleanup while you're there: delete `.idea/workspace (Philips-MBP.attlocal.net's conflicted copy 2025-12-05).xml`. It is the physical evidence that this failure mode has already fired once on this repo.

**Files changed: none.** Nothing in `scripts/`, `config/`, `main.py`, or `tools/` is touched, so `check_all.py` cannot move. Run it once after anyway — it takes seconds and establishes that the pushed commit is the green one.

**Time: under fifteen minutes**, and it is the only item on this list whose absence can cost you all the others.

---

## Not yet, and why

- **GameComponent decomposition (8.1 `Transform2D`, 8.2 `EventBus`, 8.3 `ComponentRegistry`).** Your named priority, and still the right destination — but 8.2 is a four-registry collapse (`callbacks` 113, `async_callbacks` 113, `mouse_listeners` 26, `key_callbacks` 4) across 21 bind call sites, and it is behind items 2 and 8. 8.4 is behind item 7. Starting it now means a multi-session change with a broken engine in the middle, which violates your own working constraint. Items 2, 7 and 8 *are* the decomposition, arriving in pieces that each leave a green tree.
- **Segment 2 dead-code purge (~1,100 lines).** Genuinely safe, genuinely low-value right now. It buys honest greps, which matters most *before* a large refactor — so do it as the session immediately before you start 8.2, not now. Two corrections when you do: `EventManager.get_pyo` is **live** (`scene_manager.py:69` calls it every frame — it is the entire input path), and `listbox.py` / `behavior/grid.py` are imported at module scope by `window.py:14`.
- **V3 `event_types` reshape.** Real 11.6 µs-per-event cost, but `event_types.py:150/151` both carry `window_focus` and are currently distinguished only by the tuple's second element. A naive flatten silently merges two members. Medium risk for a micro win; do it as part of V6, not standalone.
- **V8 renames and `PLAN_SINGLETONS` Step 4.** Pure churn that now costs more than the docs assume — `check_errors.py:143/158`, `check_events.py`, and `docs/` all bind the current names. Rename once, at the end, not twice.
- **`draw.py:29` opaque-black default surface** (the black rectangles under 2 Panels + 1 TextBox). Tempting because it is one flag. It is a deliberate visual change requiring a re-bless, and item 7 rewrites surface allocation anyway. Fold it into item 7.
- **`scripts/core/engine.py` (`PLAN_SINGLETONS` Step 3).** ~50 lines, additive, zero behavior change, cycle-freedom re-verified. Fine as ballast at the end of a short session, but it does not unblock anything, and its headline justification is dead: import cost measures **51 ms**, not the documented 423 ms. Also decide the exported name deliberately — `Pyoneer` now collides in autocomplete with ~10 `PyoneerXxxError` classes plus `PyoneerGameObject` and `PyoneerEvent`.
- **Phase 6 map editor.** Its two named gates are items 2 and 3 on this list. It becomes schedulable after them, not before.

---

## Where the reconciliations disagreed — flagged

1. **`bind_component`'s `commands` list is NOT a no-op — and this is the dangerous one.** The task brief and `PLAN_EVENT_SYSTEM` both imply these dispatches vanish. I read the source: `component.py:441-449` calls `component_in.core_lifecycle_prepare_pre(None)`, `core_lifecycle_prepare(None)`, `core_lifecycle_prepare_post(None)`, `core_lifecycle_build(None)` **directly**. The methods run. What the `event=None` hole swallows is the *listener fan-out inside* them (`send_event_advanced` at `component.py:744` requires `event__ is not None`). Consequence: `PLAN_EVENT_SYSTEM`'s V5 table says `Panel.core_lifecycle_build` and `ScrollComponent.core_lifecycle_build` run "0 times" and should be deleted. They run 2× and 4×, and they build most of the UI. **Deleting them on that basis destroys the window.** The event-plan reconciliation caught this; treat its version as authoritative.
2. **`flags["built"]` does not mean what it looks like.** The guard sits in `GameComponent.core_lifecycle_build` (`component.py:162`, verified — read there, written nowhere in the tree). But `Panel.core_lifecycle_build` and `ScrollComponent.core_lifecycle_build` call `super()` **first** and then run their real body unconditionally. After item 2 lands, the flag guards the fan-out and not the subtree construction. Harmless today (measured exactly one call per instance); a trap the moment anything re-builds.
3. **Which item is "next" — the four documents nominate four different winners:** map composite (improvement), V4 (event), `map_document.py` (maps), DRAG types (component). My call: the *engine* winner is V4/item 2, because three of the four documents' back halves are behind it and its safety measurement decays. None of them nominated the git remote, because none of them were asked to weigh loss-of-everything against progress. That is why it is #1.
4. **A disagreement that isn't one.** improvement-plan reports 10.24 MB per map layer and 61.4 MB total; maps-plan reports 9.77 MB and 65.20 MB. `1600×1600×4 = 10,240,000 bytes` = 10.24 MB = 9.77 MiB — same measurement, different units. The totals differ only because maps-plan includes the two entity layers and the UI layer. Nobody is wrong; don't spend a session reconciling it.
5. **Segment 2 wants `clear_organized_blits` deleted; Segment 6.e wants it called.** Unresolved in the source documents. Decide when you reach it — my read is 6.e is right and the deletion list is stale.
6. **`COMPONENT_TODO.txt:136-139` misstates the scroll thumb symptom.** It claims a 4000px and a 210px document produce an identical thumb. Construction-time sizing is correct (measured 118 vs 6). The defect is post-construction only, and currently latent because nothing mutates `scrollable_bounds` at runtime. The recorded *remedy* is right; the recorded *symptom* is not — do not use it as your acceptance test. Use the assertion in item 7 instead.
7. **`COMPONENT_TODO.txt:140-142` has the listbox dependency backwards.** Listbox is blocked by **grid**, not scroll. Scroll already provides everything listbox needs; `GridComponent` has no layout engine at all (`add_item` never calls `bind_component`, so nodes never enter the tree; `row_height`/`max_rows` are stored and never read). Grid is "not started", not "in progress".