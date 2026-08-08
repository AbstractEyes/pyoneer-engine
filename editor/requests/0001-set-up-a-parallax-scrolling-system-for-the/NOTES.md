# Response to 0001

No `response.jsonl`. Every note here needed engine or editor **code**, not
project data, so this is the code-change path the brief describes. Nothing
in the project was mutated.

`ALL 20 CHECKS PASS, NO DRIFT` after a deliberate re-baseline, explained
below.

---

## Done

### 1. Parallax scrolling, wired end to end

> *"Set up a parallax scrolling system for the background with a speed, make
> it so it only scrolls a little and then returns."*
> *"Parallax x is different but does not change the parallax background,
> there is also no parallax background pathway or systems installed."*

Correct diagnosis, and the cause was worse than "not wired": the capability
existed only in the **editor**. Nothing in the engine had ever heard of
`pyoneer_parallax_x`, so setting it wrote a property to the tmx and stopped
there. That is the "looks complete, behaves otherwise" failure, and it was
mine.

Now:

- `scripts/core/layer_profile.py` is the **shared vocabulary**, in the
  engine, imported by `editor/core/layers.py`. The dependency only runs one
  way, so the property names cannot drift apart — and a check asserts the
  editor writes exactly what the engine reads.
- `MapLayer` reads its profile at bind time and offsets its source rect by
  the parallax factor, **clamped to the surface**. Clamping is not optional:
  `destination` is a hard `(0, 0)`, so an unclamped rect near the map edge
  draws fewer pixels and leaves whatever was underneath on the rest of the
  screen.
- A declared-dynamic, parallaxed, or semi-transparent layer now **breaks a
  composite run**, exactly the way an entity layer does. That is the entire
  implementation of "dynamic": not a new draw path, just exclusion from the
  bake. A composite cannot represent something modulated at blit time.

"Only scrolls a little and then returns" is what a factor below 1.0 already
does — the layer travels *less* than the camera, so it drifts and settles
rather than sliding away, and clamping holds it at the edges. Your `Paralax`
layer is currently set to **1.4**, which is above 1.0 and therefore travels
*faster* than the world — a foreground effect. For a background, try
**0.3–0.6**.

**One thing to know before you look for it:** `Paralax` sits at depth 1 and
`Floor` at depth 10 is fully opaque across the whole map, so the parallax
layer is painted over every frame and you will see nothing. Either hole the
floor, or move the parallax content above it. This is a pre-existing content
issue recorded in `README.md`, not new.

### 2. Unstage button

> *"Add a button to unstage requests."*

**Unstage** and **Unstage all** in the Manifest panel. Unstaging was
double-click-only, which is not a feature anybody finds. Both disable
themselves when they cannot act, and "unstage all" confirms — notes are not
undoable, because they have not been applied to anything.

---

## Not done

### 3. Tilesets: add, remove, size, constraints

> *"Still cannot add or remove tilesets."*
> *"Tileset size and constraints still not set."*

Correct, and it is the biggest of the three. `MapDocument` has no public
tileset accessor at all — only a private `_find_named` — so there is nothing
for a verb or a dialog to call yet. It needs `add_tileset` / `remove_tileset`
with the same byte-exact treatment layers just got, then verbs, then an
import dialog carrying tile width/height, columns, margin and spacing.

### 4. Terrain tilesets not selectable

> *"Terrain tilesets not selectable."*

The terrain tool infers its autotile group from whichever tile is picked in
the palette, which is invisible and only works if you already know which
tiles are autotile blocks. It needs an explicit terrain picker listing the
32 groups in a sheet. It is blocked on (3), because the honest version lets
you say *"this tileset is an autotile sheet with 4×6 blocks"* — which is
tileset metadata.

Both are queued for the next pass rather than half-built.

---

## Deliberate baseline change

`renderer_layer_depths` `[1,40,41,50,60,100]` → `[1,10,40,41,50,60,100]`,
`blit_tokens` 42 → 43, `frame_hash` moved.

Because `Paralax` is declared dynamic, it left the depth-1 composite and now
draws standalone, leaving `Floor`+`GroundClutter` composited at depth 10.
That is one extra viewport blit — the measured cost of a dynamic layer, ~0.48
ms/frame — and the hash moved because the layer genuinely samples somewhere
else now. This is the feature working, not a regression.

## One bug found on the way

Making dynamic layers block composite runs crashed the renderer with
`KeyError: 1`. The old code assumed every blocking depth was already a key in
`self.layers` — true only because `blocking` was *derived* from it. A
declared-dynamic tile layer blocks without anything else living at its depth.
Fixed with `setdefault`; the suite caught it on the first run.

## Three checks were pinning map CONTENT

They failed on your painted tiles, not on any code defect: `check_maplayers`
named `Above1` as *the* empty layer and expected `Floor` to have exactly
10,000 tiles, and `check_editor_ui` painted terrain onto `Above1` assuming it
was empty. All three now discover the map rather than describing it, and the
terrain test creates its own layer.

That is the third time content-pinned assertions have cost a red suite. The
rule going in: **a check may assert what the code does, never what the map
happens to contain.**
