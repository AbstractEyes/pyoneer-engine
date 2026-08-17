<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; error strings below were produced by running the code at 5dd012d on 2026-08-16, and every source address was converted from file:line to #TAG: at d8c303f -->

# Diagnose — "why doesn't my entity do the thing"

**This file is hand-written**, because a symptom is not derivable from a
registry. Every error string quoted below was produced by executing the code,
not copied from a docstring. Read [`../CLAUDE.md`](../CLAUDE.md) first for the
vocabulary; read [`BEHAVIORS.md`](BEHAVIORS.md)'s measured integration table
for what is actually wired.

The single most useful fact: **failures here split into two opposite families.**
Some things raise loudly at load or at attach; others move zero pixels and say
nothing. Knowing which family your symptom is in halves the search.

| | raises | silent |
|---|---|---|
| unknown behavior token | ✔ at spawn | |
| unknown tmx object `type` | ✔ at map load | |
| behavior polls an unbound verb | ✔ at attach | |
| unknown animation sequence | ✔ at `start()` | |
| unknown movement **direction** | | ✔ moves zero |
| unmapped tile layer name | | ✔ never draws |
| no `player_input` token | | ✔ never moves |
| collision field says BLOCK_ALL | | ✔ never moves |

---

## "It raises at load and I never see a window"

**`PyoneerAssetMissingError: entity behavior 'X' not found; available: …`**
Your `pyoneer_behaviors` list names a token the registry does not hold. The
message prints the whole legal vocabulary. `resolve()` raises rather than
skipping the token deliberately — a skipped token silently disarms the object
*and looks like the behavior working* (CLAUDE.md law 8).

**`PyoneerAssetMissingError: spawn type 'X' not found; available: GamePlayer`**
An object on an object layer carries a `Type` that is not in `SPAWN_REGISTRY`.
One type is spawnable today. See [`PLACEABLE.md`](PLACEABLE.md) — and note that
`scripts/core/depth.py`'s `OBJECT_CONVERTER` names five more, four of which
exist nowhere in the tree, so reading that table instead will send you here.

**`PyoneerConfigError: behaviors 'topdown_move' and 'platformer_move' declare
that they conflict, and pyoneer_behaviors lists both`**
Exactly what it says. One body model per entity.

**`PyoneerConfigError: behavior token 'X' appears twice in pyoneer_behaviors`**
The list is order-insensitive — run order comes from each spec's `order`, not
from your list — so a repeat is always a mistake, never an emphasis.

**`PyoneerConfigError` naming a verb at attach time.** A behavior polls a verb
that `config/inputs.json` does not bind. It raises at **attach**, on purpose:
the alternative is `KeyError` from an unguarded dict index *inside*
`core_frame_update`, which kills the frame for every sibling in that scene
bucket. Add the binding in the same change as the behavior (CLAUDE.md law 10).

**`PyoneerAssetMissingError: tileset image … not found`** — you have no art.
See [`ASSETS.md`](ASSETS.md); `tools/make_placeholder_art.py` fixes it.

---

## "Nothing happens when I press a key"

Walk this in order. It is the order the frame actually runs.

1. **Is `player_input` in the list?** It is the entire marker for "a human
   drives this". Without it nothing writes a `MoveIntent` and every downstream
   behavior reads an empty one. A body with `topdown_move` and no
   `player_input` is a correct, inert body.
2. **Is a key bound to the verb?** `config/inputs.json` is the whole binding
   surface and nothing in `demos/` names a keycode. Rebinding there changes the
   game and changes nothing else.
3. **Is an input manager attached?** `player_input` needs
   `entity.action_manager`. A `None` manager is a legal configuration — the
   entity simply produces no intent — which is exactly how a scripted body
   coexists with a driven one.
4. **Is the body steerable?** The agency fields on the shared body state gate
   the *producer*, not the world. See the next section, because this one has a
   measured surprise in it.
5. **Is a window eating the keys?** `begin_text_capture(owner)` makes
   `pressed`, `released` **and** `held` return False for **every** verb. It is
   all-or-nothing: there is no "movement off, confirm on". A cutscene that wants
   the player to be able to press *continue* must clear the body's steerable
   flag, **not** call `begin_text_capture` — reaching for text capture is the
   obvious wrong move and it locks the player out of their own dialogue box.

---

## "It moves, but not the way I asked"

- **An unrecognised direction moves zero and says nothing.**
  `GameEntity.move_direction` has four branches and no `else`, so a typo
  produces a body that runs its animation and never translates. This is the
  exact opposite of `GameAnimationHandler.start`, which **raises** for an
  unknown sequence — one typo, two opposite failure modes, in the same frame.
- **Worse: an unrecognised direction is also unclamped.**
  `allowed_move` looks the direction up in `DIRECTION_BITS` and returns the
  wanted vector untouched when the lookup misses
  (`#TAG:GameEntity.allowed_move`). Measured on a field of
  all-`BLOCK_ALL` cells: `allowed_move(Vector2(10,10), 'down_right')` returns
  `[10, 10]` — straight through walls — while `('down')` clamps to `7.999`. It
  is harmless only while `move_direction` is the sole caller, and it is the
  reason the facing token must never be handed to the collision gate.
- **Speed is ~16.7× off.** `event.data["delta"]` is milliseconds ÷ 60, not
  seconds. A genre table's pixels-per-second figure used raw still *looks* like
  it works, which is what makes it expensive.
- **`transform=` was ignored.** `GameEntity.__init__` accepts a `transform`
  keyword and hands it down to `GameEntitySimple.__init__`, which builds a
  fresh one from `position`/`rotation`/`scale` and never looks at the one it
  was given (`#TAG:GameEntitySimple.__init__`). Use `moveto()`.

---

## "It falls forever" / "it will not land"

A side-on body's `support` axis comes from the collision field, so all three of
these produce the same symptom:

1. **The map has no companion collision layer.** The bake produces `None`,
   which means **ungated** — every step is allowed and nothing is ever ground.
   The shipped demo map is ungated and correct; a body falling forever means an
   *unpainted* map far more often than a missing wire.
2. **The mask says open where you painted.** Erasing writes gid 0, which in a
   companion layer means `NO_DATA` — "nobody said anything here" — deliberately
   **not** the same claim as "open". Check you painted the bit you meant.
3. **You are outside the field.** `CollisionField.outside` defaults to
   `BLOCK_ALL`, which stops a body walking out of the world — but a body that
   *spawned* outside is frozen forever, reporting blocked in all four
   directions. A body that cannot move in any direction at the map edge is this,
   not gravity.

---

## "My layer does not draw" / "my tiles vanished"

`resolve_layer_depth` returns `None` for a name it does not know, and an
unmapped tile layer is silently not drawn. Measured: `resolve_layer_depth
("Trees")` is `None`; `resolve_layer_depth("Paralax")` is `1`, because the
author's map spells it with one L and `LAYER_NAME_ALIASES` carries the typo
rather than rewriting the `.tmx` (`#TAG:LAYER_NAME_ALIASES`). That alias exists
because 39 authored tiles were silently dropped for months. Legal layer names
are generated into [`PLACEABLE.md`](PLACEABLE.md).

---

## "The animation is wrong / it raises `idle_none`"

- `GameAnimationHandler` starts `idle_down` **at construction**, before any
  behavior attaches (`#TAG:GameAnimationHandler.__init__`). A sheet with
  no `idle_down` row therefore raises inside the entity constructor, before any
  composition can say what the body faces. This is the first wall a side-on-only
  or portrait-only sheet hits.
- `start()` raises `PyoneerAssetMissingError` for an unknown sequence and prints
  every sequence it does have. The sequence name is built from a format string
  and the facing token, so `idle_{facing}` with an illegal facing is the usual
  cause.
- Sequence naming is **parameters, not code** — `walk_format` / `idle_format` /
  `initial_sequence` are declared, so a two-row sheet is a parameter change and
  not a new behavior.

---

## "I changed something and the suite went red"

- **`DRIFT smoke`** means the rendered frame moved. Name the field, the old
  value and the new one, and say why, before re-baselining. Do not re-baseline
  something you cannot explain.
- **`PASS smoke` proves less than it looks.** Smoke injects **no input**, so it
  cannot see anything that only happens while walking. "No drift" never means
  "nothing changed" — a real animation-phase change once moved ~16% of frames
  while walking and smoke could not see it. Use `demos.patrol`: it is the only
  instrument that walks a body deterministically with no key injection.
- **`HANG`** means a check blocked, almost always on a modal dialog.
- **A check that asserts what `data/maps/test.tmx` contains is wrong**, even if
  it is green today. The author repaints that map.

---

## When the answer is not here

Check [`BEHAVIORS.md`](BEHAVIORS.md)'s integration table before believing any
prose anywhere, including this file's: that table is produced by constructing a
real entity and running frames, and a row reading `needs-host` means the
behavior runs and reaches nothing. If the thing you want appears finished but
inert, [`history/ORPHANS.md`](history/ORPHANS.md) is the dated archive of
finished-and-unattached code and is likely to name it — re-measure anything it
says before acting, because most of its findings are spent.

Every address in this file is a `#TAG:`. `grep -rn "#TAG:GameEntity.allowed_move"`
returns the definition line, this document's citation of it, and the code map's
entry, in one command — which is the point, and why no line number appears
above.
