<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every wall-clock and token figure below was measured on this machine at the commit that added docs/DESIGN_TEMPLATE.md, and tools/check_prototype.py re-runs the loop's third step on every suite run -->

# Prototype — the loop, written down

Three steps, in one direction, each with a file you can point at:

    DESIGN   fill docs/DESIGN_TEMPLATE.md          no code is written
    BUILD    a map source, plus demos/<name>.py    the game runs
    PROVE    a check that boots it and presses     the game stays running

This paradigm is not proposed. It **already produced four demos**, and this
file is the version most likely to survive: a description of what happened,
not a plan for what should. What is new here is the form in step one — the
older demos were designed in a paragraph, and a paragraph does not resolve.

## Why the loop is three steps and not two

BUILD without DESIGN produces a game whose behavior list is invented at the
keyboard, and the failure mode is specific and quiet: a mistyped behavior token
**raises at load** (good), but a mistyped *direction*, a *tile layer* the depth
table does not know, and an *unbound verb polled by a behavior* fail three
different ways — zero pixels of movement, a layer that is silently not drawn,
and a `KeyError` inside the frame loop that kills every sibling in the scene
bucket. The form resolves all three before a file is written.

BUILD without PROVE produces the orphan this repository already has a document
about. A prototype looks fine right up until somebody runs it, and nobody runs
it.

## Step 1 — DESIGN

Fill [`DESIGN_TEMPLATE.md`](DESIGN_TEMPLATE.md)'s blank form. Fourteen rows,
each resolving to something that already exists.

**Cost, measured.** The form itself is ~1.8k tokens to read. If you already
know the vocabulary you need nothing else; if you do not, the two lookups are
[`BEHAVIORS.md`](BEHAVIORS.md) (~6.5k, the registry and what each token writes)
and [`PLACEABLE.md`](PLACEABLE.md) (~0.8k, the spawnable types, the tile layer
names that resolve to a depth, and the bound input verbs). Both are generated,
so neither can be wrong about the tree.

**Wall clock.** Minutes, and the budget is five. A row that takes longer than
that is a row describing something the engine cannot do yet — write that down
and stop, because a form that cannot be filled is a finding worth more than a
demo built around the gap.

**What you have at the end.** A block of text with no code in it, which
`tools/check_prototype.py` can resolve field by field. That is the property
worth the ceremony: the design is *checkable* before it is *built*.

## Step 2 — BUILD

Two files, and usually only one of them is new.

**A map source in [`demos/mapgen.py`](../demos/mapgen.py).** Copy the nearest
`_*_source` function and put every position, object id and geometry number in a
named module constant beside the others. This is not neatness: the check
DERIVES what it expects from those constants, so a number typed twice is a
check that pins map content instead of code — which is forbidden, because the
author repaints maps.

**A class in `demos/<name>.py`.** A `MAP_NAME` and, for a narrative game, a
`SCRIPT`. Measured: the four demo modules are 7, 9, 8 and 14 code lines, and
none of them defines a method. If yours needs one, the method wanted a hook —
on the shared demo runtime, on a narrative kit beside it, or on `MainGame` —
and putting it on the demo class is how a prototype becomes boilerplate.

**A kit beside them, only if the genre needs one.** The story demo needed a
dialogue box and a step adapter, so `demos/narrative.py` exists: 73 code lines,
shared by every narrative demo after it, and outside `scripts/` on purpose —
proving an extension point is only proof when the extension lives outside the
thing it extends.

**Cost, measured.** Reading `demos/mapgen.py` whole is ~5.5k tokens; its tier-2
map entry is ~1.3k and is usually enough to find the function to copy. Writing
the two files is the only genuinely new text in the loop.

**Wall clock.** `.venv/Scripts/python.exe -m demos.story --frames 60` returns
in **1.6s**, and a single-frame boot in **1.2s** — nearly all of it import and
the composite bake, so the second run costs the same as the first. That is the
number that matters: the edit-to-see-it loop is under two seconds, which is why
these demos get run instead of reasoned about.

**Then regenerate the map**, in the same change:

    .venv/Scripts/python.exe tools/gen_map.py --write

**1.1s.** A new module, class or module constant that is not in
[`MAP.md`](MAP.md) is a symbol `grep -rn "#TAG:..."` cannot find, and the doc
check compares the generated map byte for byte.

## Step 3 — PROVE

A section in a check that boots the demo headless, drives it with **injected
input**, and asserts both halves of every gate.

Injected input is the whole reason this step is not smoke. `tools/smoke.py`
presses nothing, so a clean smoke never means nothing changed — it cannot see
anything that only happens while walking, and a real animation-phase change
once moved ~16% of frames while walking with no drift reported at all.

**Both halves is the whole discipline.** The dominant defect shape here is a
gate proved to let something through and never proved to stop it. The form
makes you write the pair down in step one, as `prove` rows, and the check
refuses a `prove` row without an `AND` in it. Then each row becomes at least
two assertions and usually a negative-control boot:

| the claim | the half that kills the false pass |
|---|---|
| injected input walks the driven body | ...and leaves every other body on the pixel it spawned on |
| the cutscene refuses movement | ...and the action verb still advances it, on the same frames |
| a timed beat advances itself | ...and an untimed one does not, over more frames |
| steering comes back when the flow ends | ...and comes back to the value each body **had**, never to `True` |
| a side-on body lands on the mask | ...and with the field cleared, the same map falls forever |

**Cost, measured.** `tools/check_prototype.py` is 616 code lines and runs **87
assertions in 3.9s**, over three headless boots. Most of that line count is the
mutation fixtures, and they are the point: a resolver asserted only against a
correct form passes for a resolver whose every rule is `pass`, so the worked
example is mutated in memory twenty ways and each mutation must be reported by
name.

**Then put it in the roster, in the same change.** A check that is not in
`tools/check_all.py`'s list has proved nothing — checks have been written,
passed, and never run by the suite. [`CHECKS.md`](CHECKS.md) is generated from
that list:

    .venv/Scripts/python.exe tools/check_docs.py --write

## The whole loop, as commands

    # DESIGN   -- fill the blank form in docs/DESIGN_TEMPLATE.md

    # BUILD
    .venv/Scripts/python.exe -m demos.<name> --frames 60      1.6s
    .venv/Scripts/python.exe tools/gen_map.py --write         1.1s

    # PROVE
    .venv/Scripts/python.exe tools/check_<name>.py            ~4s
    .venv/Scripts/python.exe tools/check_docs.py --write

Total machine time for one turn of the loop, measured: **under ten seconds.**
Everything else is thinking, which is where it belongs.

## Where the editor joins this

Nowhere yet, and that is the honest answer. The loop above writes `.tmx` from
Python because there is no path from a filled form to an authored map — the
editor's genre packs declare a slot for default behavior lists
(`layers[].object_classes[].behaviors`) and the editor is meant to
MATERIALISE it into an object when the object is added, so the `.tmx` stays the
whole truth and the engine never has to read a pack. Until it does, a demo's
map source spells the behavior strings out.

What the loop already gives the editor is the vocabulary: the form's rows are
the editor's own nouns — a genre pack id, a layer, an object type, a behavior
checklist, a table column — so a form filled today is the same form a panel
would fill tomorrow. Nothing in the loop needs to change for that to land; one
column in a genre pack needs to be read.

## What this loop refuses to do

- **It does not add a framework.** A demo is a subclass of the game `main.py`
  runs, and the check asserts by *identity* that the shared runtime inherits
  that whole spine. The day a demo is 300 lines of boilerplate, that assertion
  goes red.
- **It does not fork the engine.** `demos/` imports `scripts/`; nothing under
  `scripts/`, `editor/` or `main.py` imports `demos/`, and that is asserted in
  both directions.
- **It does not pin map content.** Every check in this loop generates its own
  maps into a temp directory. `demos/maps/*.tmx` is yours to repaint, exactly
  as the shipped map is.
- **It does not bless a frame change.** A demo that moves the rendered frame of
  `main.py` is a demo that touched the engine, and smoke will say so.

## Reading order for the four demos

[`DEMOS.md`](DEMOS.md) is the index, and each demo proves one thing:

    topdown    the map is enough; `player_input` is the whole marker
    sidestep   genre lives in map data, and the collision gate is real
    patrol     the intent seam is real, and the registry is open to a game
    story      a scene flow is mounted: a window sequence takes the player's
               steering, advances on their own action verb, and gives the
               steering back exactly
