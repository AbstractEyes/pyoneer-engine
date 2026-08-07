# Pyoneer — Singleton & Global State Repair Plan (corrected)

## Verification preamble — the draft is substantially stale

I re-ran the engine at HEAD before critiquing. The in-flight worker landed fixes **between the draft being written and now**, and the draft's first three steps are already done. `config/managers/core_asset_manager.py` was rewritten *while I was reading it* (my first read returned the old 67-line version; the second returned the current 125-line version).

Commands re-run:

```
SDL_VIDEODRIVER=dummy .venv/Scripts/python.exe tools/smoke.py --frames 60 --baseline tools/baseline.json
  -> NO DRIFT     frame_hash bec3f3153713a6b2, 113 UI components, 69 blit tokens, 13 depths
```

**The engine boots. There is no blocker.** Every claim below was executed; throwaway probes were written to `tools/` and deleted.

### What the draft asserts vs. what the code says

| Draft claim | Reality at HEAD | Evidence |
|---|---|---|
| §0 "engine does not boot"; `prepare_inputs` calls `pygame.key.get_pressed()` | **FALSE.** `input.py:149-153` is a comment explaining it deliberately does *not* sample | smoke green |
| §0 `validate_bindings` rejects `gamepad:button_N` | **FALSE.** `input.py:45` `CONTROLLER.update({f"button_{i}": i for i in range(16)})` | smoke green |
| §1.a `__init__` re-entry BROKEN | **FIXED.** `core_asset_manager.py:73-76` guards on `self.is_initialized` | probe: 2nd/3rd call return immediately |
| §1.a sub-managers wiped on re-construction | **FIXED.** `maps mgr identity kept: True`, tmx id unchanged across a stray `CoreAssetManager()` | probe |
| §1.a "every config JSON parsed 3×" | **FALSE now.** `__init__` is *called* 3× but bodies run once | probe |
| §1.b `Singleton._instance` MRO trap blocks test doubles | **FIXED.** `core_asset_manager.py:33` `_instances: dict[type, Singleton]` keyed per class. `FakeAssets(CoreAssetManager)()` returns a `FakeAssets`, not the real one | probe |
| Step 2 `os.listdir('config')` CWD bug | **FIXED.** `config_data.py:27-29` `CONFIG_DIR` derived from `__file__`; `config_data.py:33` uses it | probe from parent dir: OK |
| §1.f `update()` default arg frozen at import | **TRUE, still live.** `event_manager.py:80`; `update.__defaults__ == (0.016,)` | probe |
| §1.f **`FRAME_DELTA` is write-only, delete it** | **FALSE AND DANGEROUS.** Read at `scripts/core/ui/widget/behavior/mouse.py:244` — `self.mouse_down_time += EventManager.FRAME_DELTA`. Draft Step 4 deletes it → `AttributeError` in every mouse-move | grep + read |
| §Step 8 "two `MainGame`s diverge on input" | **FALSE now.** `g1.assets is g2.assets: True`, `g1.input is g2.input: True` | probe |
| `AssetMapManager` has no reload path | **FIXED.** `map_data.py:63-68` `reload()`; `map_data.py:28` `load_assets(name, reload=False)`; `map_data.py:46` `is_loaded()` | read |
| §1.d `DepthAssetManager` dead | **TRUE.** zero call sites | grep |
| §1.g `__object_registry__` dead | **TRUE.** zero call sites, 0 entries after boot | grep + probe |
| §1.h `ComponentFactory` unreferenced | **TRUE.** only `main.py:23/53` commented out | grep |
| §1.e `ORGANIZED_BLITS` correct in operation | **TRUE** | read |
| §1.f `QUEUE` is rebound not mutated | **TRUE.** `event_manager.py:86` | probe: identity kept `False` |
| §1.f `pump_pyo` coalescing branch dead | **TRUE, and worse than stated** — see below | probe |

### Three defects the draft got wrong in ways that matter

**1. `FRAME_DELTA` deletion is a crash.** Already covered. Step 4 must not touch it.

**2. `pump_pyo` is *doubly* dead — fixing the comparison will not revive it.** The draft says `event_manager.py:126` compares a `PyoneerEvent` to `GameEventType.PYGAME` and is always `False`. True. But `PyoneerEvent.__translate` (`event_manager.py:65-74`) already rewrites `self.type` away from `PYGAME` during construction — probe shows a `MOUSEBUTTONDOWN` becomes `GameEventType.MOUSE_DOWN`. So `last_event.type == GameEventType.PYGAME` would *also* be `False`. Anyone "fixing" the operand will believe they restored coalescing and will not have. The `__PROBLEM_EVENTS` macOS guard (`event_manager.py:16`) stays dead either way.

**3. The proposed `engine.py` is a guaranteed import cycle.** Draft §2 Option B declares `scenes: SceneManager` on `PyoneerEngine`, and Step 5 makes `component.py` import `Pyoneer`. Measured:

```
importing scripts.core.scene.scene_manager pulls in scripts.core.component : True
```

`engine → scene_manager → renderer → component → engine`. The draft never notices. By contrast `config.managers.core_asset_manager` does **not** pull `component`, so an assets-only accessor is cycle-free. This is a real ordering defect, not a style note.

### The one place the draft's reasoning is right but its evidence is wrong

Draft §2 argues against flat from-imports because a rebind in the source module does not update consumers. That argument is sound, and the *live* proof is not the one the draft gives:

```
CoreAssetManager.reset_singleton(); new = CoreAssetManager()
  new is old                        : False
  component.Config still points to old : True   <- STALE MODULE ALIAS
```

`reset_singleton()` now exists and works, but `component.py:16` and `window.py:25` hold `Config` as a module global, so after a reset the entire UI tree reads a dead asset graph. **That** is the argument for removing the module-level `Config`, and it only became true *because* the worker added the reset seam.

### The one genuine architectural defect still open

```
`import scripts.core.component` took 423.0 ms
  config JSON parsed at import  : ['animations','depth','entity','game','inputs','maps','theme']
  maps indexed at import        : ['test']
  input actions built at import : 7
```

`component.py:16 Config = CoreAssetManager()` still performs 423 ms of disk IO as a side effect of importing a UI module. It is no longer *destructive*, but import order still decides when assets load, and it is what makes `component.py` untestable in isolation. This is the real remaining target — and the draft's Step 5 does not fix it, because `Config = Pyoneer.assets` at module scope is the *same* import-time evaluation under a new name.

**It is fixable trivially, which the draft missed.** All seven theme lookups are already inside method bodies:

`window.py:37` and `:87` (in `__init__`/method), `shape.py:35`, `text.py:30`, `button.py:26` and `:44`, `keyboard.py:54` — every one is `config = Config.config.get("theme")[...]` inside a function. **No module-level binding is needed by anything.** Delete the global, call the accessor at use time. No proxy, no lazy descriptor, no deprecation alias.

---

## 1. Corrected inventory of global / singleton state

### 1.a Already repaired — do not re-open

| Item | Location | State |
|---|---|---|
| `Singleton` per-class instance cache | `core_asset_manager.py:33-41` | correct; `_instances` keyed by `cls` |
| `__init__` re-entry guard | `core_asset_manager.py:73-76`, sealed at `:88` | correct |
| `reset_singleton()` test seam | `core_asset_manager.py:47-54` | correct |
| `CoreAssetManager.reload()` | `core_asset_manager.py:90-98` | correct; explicit only |
| tmx parse-once + explicit reload | `map_data.py:28-48`, `:63-68` | correct |
| CWD-independent config load | `config_data.py:27-39` | correct |
| Regression guard | `tools/check_singletons.py` | exists, passes |

### 1.b Still broken

| # | Defect | Location | Impact |
|---|---|---|---|
| B1 | `Config = CoreAssetManager()` at module scope, ×2 | `component.py:16`, `window.py:25` | 423 ms disk IO on import; stale alias after `reset_singleton()` |
| B2 | `QUEUE` rebound, not mutated | `event_manager.py:86` | any `from … import QUEUE` binds a dead list |
| B3 | Default arg evaluated at import | `event_manager.py:80` | one throwaway `Clock`, ~16 ms import block, value frozen at 0.016 |
| B4 | `pump_pyo` coalescing + macOS guard doubly dead | `event_manager.py:126`, `:16`, `:65-74` | dead code that looks alive |
| B5 | `queue()` never called, appends without clearing | `event_manager.py:91-97` | dead |
| B6 | `smoke.py` monkeypatches a `@staticmethod` onto a global class | `tools/smoke.py:47-59`, restored `:69` | no read-only seam exists |
| B7 | Probes carry a now-redundant `CONTROLLER` shim | `probe_singletons.py:25-32`, `probe_singleton_boot.py:19` | actively misleading; `input.py:45` supersedes it |

### 1.c Dead — delete

| Item | Location | Call sites |
|---|---|---|
| `DepthAssetManager`, `Depth` | `config/managers/depth_data.py` | 0 |
| `__object_registry__` + 3 functions | `__init__.py:3-25` | 0 |
| `ComponentFactory`, `COMPONENT_POOL`, `COMPONENT_POOL_READY`, `ComponentNode` | `scripts/core/ui/widget/factory/component_factory.py` | 0 live (`main.py:23/53` commented) |
| commented specimen block | `component_factory.py:70-85` | — |

Note: live depth data is the hardcoded dicts in `scripts/core/depth.py:2/16/24/33`. `config/depth.json` is parsed by `ConfigManager` and never read — leave the file, delete the manager.

### 1.d Correct as-is — leave alone

`ORGANIZED_BLITS` (`blitpool.py:60`) — every accessor declares `global` and mutates in place; no consumer holds an alias (`renderer.py:20` imports the class). `PYO_QUEUE` (`event_manager.py:13`) — mutated via `clear`/`append`, never rebound. Read-only tables: `depth.py:2/16/24/33`, `input.py:8/33`, `utils.py:26-27`.

Two class-level mutable containers used as constants: `MouseComponentAsync.EVENT_TYPES` (`mouse.py:16-30`) and `Movement.EVENT_TYPES` (`movement.py:10`). The mouse list is the gate that silently rejects `MOUSE_DRAG_BEGIN/END` — **that belongs to the event-system worker, not this plan.** Confirmed absent from `mouse.py:16-30`.

---

## 2. Naming schema — one accessor, assets only

The owner asked for singletons with "a useful relational name schema to understand the autocompletes." He also said cut the bloat. Those constrain each other: the schema must be a *naming* change, not a re-architecture.

**`scripts/core/engine.py`** — new, ~30 lines, imports only `config.managers.core_asset_manager` (proven cycle-free).

```python
from config.managers.core_asset_manager import CoreAssetManager

class PyoneerEngine:
    @property
    def assets(self) -> CoreAssetManager: return CoreAssetManager()
    @property
    def config(self):     return self.assets.config
    @property
    def input(self):      return self.assets.inputs
    @property
    def maps(self):       return self.assets.maps
    @property
    def animations(self): return self.assets.animations
    @property
    def entity(self):     return self.assets.entity
    def theme(self, section: str) -> dict:
        return self.assets.config.get("theme")[section]
    def reload(self):     return self.assets.reload()
    def reset(self):      CoreAssetManager.reset_singleton()

Pyoneer = PyoneerEngine()
```

Autocomplete tree:

| Types | Sees |
|---|---|
| `from scripts.core.engine import ` | `Pyoneer` |
| `Pyoneer.` | `animations · assets · config · entity · input · maps · theme() · reload() · reset()` |
| `Pyoneer.maps.` | `load_assets() · unload_assets() · is_loaded() · reload() · prepare() · maps` |

`Pyoneer.theme("widget")` replaces `Config.config.get("theme")["widget"]` — an object named `Config` whose `.config` is a different object. Every property resolves through `CoreAssetManager()`, which is now a guarded singleton, so **there is no stale alias and no reset seam problem** — the two things the draft needed a whole new architecture to achieve.

**Rules:**
1. Exactly one module-level engine name: `Pyoneer`.
2. Plural nouns for collections (`maps`, `animations`), singular for services (`input`, `config`).
3. Class keeps `*Manager` for grep; the accessor drops it.
4. Verbs uniform: `load_assets / unload_assets / is_loaded / reload / prepare`.
5. **No module may write `X = SomeManager()` at module scope.** Enforced in `tools/check_imports.py` (Step 5).

**Explicitly NOT in the schema:** `Pyoneer.scenes` (import cycle — `SceneManager` is per-`MainGame` state and belongs on `MainGame`), `Pyoneer.display` (one `set_mode`, at `main.py:165` — nothing to arbitrate), `Pyoneer.events` / `Pyoneer.blits` (see Removed).

---

## 3. Ordered migration

Baseline held constant throughout: `frame_hash bec3f3153713a6b2`, `ui_component_total 113`, `blit_tokens 69`, 13 depths, one `GameWindow` root.
Verification command for every step:

```
SDL_VIDEODRIVER=dummy .venv/Scripts/python.exe tools/smoke.py --frames 60 --baseline tools/baseline.json
```

There is **no Step 0**. The engine is green now.

---

**Step 1 — Delete dead code. Zero behavior change.**
Delete `config/managers/depth_data.py`; delete the body of `__init__.py` (leave the file empty — it is the package marker for the repo root); delete `scripts/core/ui/widget/factory/component_factory.py` and the `factory/` package if it empties; delete the commented `ComponentFactory` lines at `main.py:23` and `main.py:53-54`.
*Verify:* `.venv/Scripts/python.exe tools/check_imports.py` → PASS; smoke → **NO DRIFT**. Any drift here means something imported the dead code implicitly — bisect by restoring one file.
*Why first:* it is the only step with literally zero coupling to the in-flight worker, and it shrinks the surface every later step has to reason about.

**Step 2 — Fix the three `event_manager` globals, in place. No new classes.**
- `event_manager.py:80` — `def update(delta: float = 0.016)`. Removes the import-time `Clock` construction and the ~16 ms block.
- `event_manager.py:86` — `QUEUE[:] = pygame.event.get(pump=True)` instead of `QUEUE = …`. One character class of change; kills B2 permanently, and makes `from … import QUEUE` safe rather than merely unused.
- `event_manager.py:91-97` — delete `queue()` (B5).
- **Do not touch `FRAME_DELTA`.** It is read at `mouse.py:244`.
- Add a comment at `event_manager.py:126` recording that the branch is dead on *two* counts (operand type, and `__translate` at `:65-74` having already rewritten `.type`), so the event worker does not "fix" the operand and believe coalescing is restored. Do not change the logic — coalescing semantics belong to the event-contract segment.
*Verify:* smoke → **NO DRIFT** (frame_hash covers rendered output; `QUEUE` mutation-vs-rebind is behaviourally identical today, which is exactly why it is safe to change now and unsafe to leave). Also `.venv/Scripts/python.exe tools/probe_events.py` unchanged.

**Step 3 — Add `scripts/core/engine.py`, additively. Nothing is rewritten.**
Create the file from §2. It imports only `core_asset_manager`.
*Verify:* new `tools/check_engine.py` asserting `Pyoneer.assets is CoreAssetManager()`, `Pyoneer.input is Pyoneer.assets.inputs`, `Pyoneer.theme("widget") == Pyoneer.config.get("theme")["widget"]`, and — critically — that `import scripts.core.engine` does **not** put `scripts.core.component` or `scripts.core.scene.scene_manager` in `sys.modules` (the cycle guard). Then smoke → **NO DRIFT**.

**Step 4 — Retire the two module-level `Config` globals. Coordinate with the `component.py`/`window.py` worker; one commit.**
This is the only step that touches files another worker owns. Sequence it with them.
- `component.py:16` — delete `Config = CoreAssetManager()` and the now-unused `from config.managers.core_asset_manager import CoreAssetManager` at `:14`.
- `window.py:25` — delete `Config = CoreAssetManager()` and its import at `:23`.
- Replace all seven use sites with a call inside the existing method body (all seven already are in method bodies — no restructuring):
  - `window.py:37`, `window.py:87` → `config = Pyoneer.theme("widget")`
  - `shape.py:35` → `config = Pyoneer.theme("widget")`  (drop `from scripts.core.component import Config` at `shape.py:9`)
  - `text.py:30` → `theme = Pyoneer.theme("widget")`  (drop import at `text.py:10`)
  - `button.py:26`, `button.py:44` → `theme = Pyoneer.theme("widget")`  (`button.py:3` becomes `from scripts.core.component import GameComponent`)
  - `keyboard.py:54` → `config = Pyoneer.theme("input")`  (drop import at `keyboard.py:11`)
- `main.py:159` → `self.assets = Pyoneer.assets`; `main.py:160` → `self.input = Pyoneer.input`.
*Verify, in order:* (a) `import scripts.core.component` timing drops from ~423 ms to the low tens — assert `< 100 ms` in `tools/check_engine.py`; (b) `CoreAssetManager.__init__` body runs **once**, and the caller is `main.py`, not `component.py` — extend `tools/check_singletons.py` with the stack-attributing counter; (c) smoke → **NO DRIFT** on `frame_hash`, `ui_component_census`, `blit_tokens`. A `ui_component_census` drift means a theme lookup resolved differently — bisect one file at a time, which is why this is six small edits and not a rename.
*Note:* do this per-file with a smoke run between files if the worker's schedule allows; the seven sites are independent.

**Step 5 — Lock it in.**
Add to `tools/check_imports.py` (after the existing bare-name check at `:78-84`) an AST scan over `scripts/`, `config/`, `main.py` that fails on any module-scope `Assign` whose value is a `Call` to a name ending in `Manager` or `Factory`. This is the rule that stops B1 from regressing.
*Verify:* `tools/check_imports.py` → PASS on clean tree; temporarily re-add `Config = CoreAssetManager()` to `component.py` and confirm it **fails**, then revert. Smoke → NO DRIFT.

**Step 6 — Give `smoke.py` a real seam and delete the monkeypatch.**
Add one read-only classmethod to the existing `BlitPool` class (`blitpool.py:64`) — no instance conversion, no signature changes to the five existing staticmethods:
```python
@staticmethod
def snapshot_depths() -> dict[int, int]:
    return {int(d): sum(len(t) for t in ORGANIZED_BLITS[d].values())
            for d in sorted(ORGANIZED_BLITS)}
```
Then rewrite `tools/smoke.py:47-59` to call `BlitPool.snapshot_depths()` immediately before `renderer.render()` and delete the restore at `:69`.
*Verify:* the reported `blit_depths` histogram must be **byte-identical** to the monkeypatched version — `{10:1, 30:1, 40:5, 41:1, 50:1, 60:1, 100:1, 101:6, 102:2, 103:13, 104:13, 105:16, 106:8}`, `blit_tokens: 69`. Then smoke → NO DRIFT.

**Step 7 — Clean the probe shims and prove reset round-trips.**
- Delete the `TRANSIENT SHIM` at `probe_singletons.py:25-32` and `probe_singleton_boot.py:19`. `input.py:45` supersedes them; leaving them makes the probes lie about what `CONTROLLER` contains.
- Refresh both probes against the current `core_asset_manager.py` — their §1/§2 sections now assert defects that no longer exist and will read as false failures.
- New `tools/probe_reset.py`: boot `MainGame(autostart=False)`, `begin(max_frames=60)`, record `frame_hash`; `Pyoneer.reset()`; boot a second `MainGame`; assert the **same** `frame_hash`.
*Verify:* `probe_reset.py` prints matching hashes. This is now achievable because Step 4 removed the module aliases that go stale across a reset — before Step 4 it provably fails (`component.Config still points to old: True`).

---

## Removed from the draft

- **Step 0 (input.py blocker).** Stale — both cited defects are already fixed (`input.py:45`, `input.py:149-153`); smoke is green.
- **Step 1 (`_initialized` guard, split `__init__`/`load()`).** Already landed at `core_asset_manager.py:73-76`/`:88`; re-doing it would revert working code.
- **Step 2 (CWD fix).** Already landed at `config_data.py:27-29/33`.
- **New `scripts/core/singleton.py` with `__init_subclass__` + `cls.__dict__.get("_instance")`.** Rewrites a fix that already works by a different, simpler mechanism (`_instances` keyed by `cls`, `core_asset_manager.py:33`). Verified the MRO trap and the test-double case are both already closed. Pure churn in a file another worker owns.
- **Deleting `FRAME_DELTA`.** It is read at `mouse.py:244`; deletion is an `AttributeError` on every mouse move. The draft's "read nowhere" is false.
- **`EventBus(Singleton)` class.** A Python module *is* a singleton. Converting 26 importers and two `import … as EventManager` sites to buy what the module already provides is the exact abstraction-adding the owner called bloat. The one real bug (`QUEUE` rebinding) is a one-line fix — Step 2.
- **`BlitPool` instance conversion.** Same reasoning. `ORGANIZED_BLITS` is verified correct in operation; the only stated motive was a test seam, which one read-only classmethod supplies (Step 6) without touching `renderer.py:20`, `draw.py:7`, `game_entity.py:13`, `game_player.py:12`.
- **`Pyoneer.scenes: SceneManager`.** Import cycle, measured: `engine → scene_manager → renderer → component → engine`. `SceneManager` is per-`MainGame` state and does not belong on a process-global accessor.
- **`Pyoneer.display: DisplayContext`.** Speculative. One `set_mode` in the engine (`main.py:165`); nothing to arbitrate.
- **Option A (flat `PyoAssets`/`PyoConfig`/… prefix).** Correctly rejected by the draft; kept out. Property-based Option B has no stale-alias failure mode at all, so the draft's long testability argument is moot rather than merely won.
- **`Config = Pyoneer.assets` as a deprecated module alias (draft Step 5).** Does not fix the problem it claims to — module-scope evaluation is the defect, and renaming the right-hand side preserves it. All seven call sites are already inside method bodies, so the alias is unnecessary.
- **Draft Step 8's premise ("two `MainGame`s diverge on input").** Stale; measured `g1.input is g2.input: True`. The reset round-trip test survives as Step 7, rebuilt on the real remaining motive (stale module aliases), not the fictional one.