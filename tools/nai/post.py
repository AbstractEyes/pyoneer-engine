"""Post-processing: a generated 1216x832 strip becomes real pixel art (brief 5).

OWNER: implementer C.

RESPONSIBILITY
--------------
`pixelize` runs P1-P10 over ONE strip: detect the pseudo-pixel grid once,
quantise to one shared palette, downscale by block mode, key the grey
background, cut and baseline-align the frames, validate, and emit an RGBA
strip, per-frame PNGs and a sidecar. It reads no file and writes no file:
bytes in, bytes out. The CLI decides where anything lands.

INVARIANTS
----------
* PER STRIP, NEVER PER FRAME. k, phase and palette are chosen once for the
  whole strip, so scale and colours cannot flicker between frames. The P5
  flood-fill fallback is also strip-wide.
* NO NEW COLOURS. Downscale is the MOST COMMON palette index per k x k block
  at the detected phase, ties to the lowest index. Never Image.reduce (box
  average), never a NEAREST downscale (a single sample, not a mode).
* ONE MAPPING PATH. Every strip -- the first one included -- is mapped with
  rgb.quantize(palette=<mode P image>, dither=Image.Dither.NONE) on an RGB
  image (RGBA raises in Pillow). The first strip of a character builds that
  mode-P palette image first and returns it; a later strip passes it back in
  and gets the same palette bytes returned. So pixelize(png) and
  pixelize(png, palette_png=<its own palette>) emit identical strips.
* THE PALETTE IS BUILT FROM DENOISED BLOCKS -- MEASURED, AND NOT THE
  BRIEF'S ONE-CALL MEDIANCUT. Measured on a synthetic 1216x832 strip (grey
  background, eight flat colours plus x0.7 shades, per-channel noise +-6, a
  0.6 px blur), Pillow 10.2:
    - rgb.quantize(colors=16, method=MEDIANCUT) spent 13 entries on shades
      of the background grey and merged the whole sprite into 2-3 entries:
      median cut splits the most POPULATED box, and the background is ~85%
      of the pixels.
    - rgb.quantize(colors=16, method=MAXCOVERAGE) kept the grey as one entry
      but spent 6 of 16 on blur blends (outline over grey, tunic over grey);
      boots, pants and hair drifted up to 26 levels per channel.
    - quantising the full image to 64 entries and keeping block winners
      split the noisy grey into representatives up to 20 apart (Euclidean),
      further apart than real colour pairs (hair/boots 17), so blocks
      alternated between two greys and keying broke.
  So the first strip's palette is: the per-channel MEDIAN of each block's
  core (CORE_INSET pixels in from every side), quantised to `colours` with
  PALETTE_METHOD (MAXCOVERAGE), then entries within MERGE_DISTANCE of a
  more populous entry merged into it. Nothing dithers, and the palette can
  hold fewer than `colours` entries. Near-duplicate entries are the thing
  to avoid: noisy pixels of one flat area split between them, and the block
  mode then alternates.
* REJECT, DO NOT REPAIR. P9 failures set validation["ok"] False with the
  failing entries; the strip is still returned so the author can look, and
  nothing is silently fixed. A P5 flood-fill fallback is a FLAG
  (validation["flags"]), not a pass.
* INPUT ERRORS RAISE: a PNG that is not layout.width x layout.height, a
  palette PNG that is not mode P, centers or ground of the wrong length.
* Pillow and pure Python only; numpy is not available.

STEPS (brief 5, thresholds are module constants)
------------------------------------------------
P1 load RGB, assert size. P2 `detect_grid`: luma L = (299R + 587G + 114B) //
1000; column energy Ex[j] = sum over rows |L[i][j] - L[i][j-1]| for j >= 1,
row energy Ey likewise; for k in K_RANGE and phase in [0, k): S(k, phase) =
mean(E[j] for j >= 1, j = phase mod k) / mean(E[j] for j >= 1); T(k) =
max_phase Sx + max_phase Sy; pick the k maximising T (ties to the smaller k,
phases tie to the smaller phase). Then two tie rules, in order: (a) if
T(PREFERRED_K) >= (1 - TIE_TOLERANCE) * T(best), answer PREFERRED_K; (b) if
best is even, best // 2 is in K_RANGE and T(best // 2) >= HARMONIC_RATIO *
T(best), answer best // 2. Rule (b) is not in the brief: every edge of a k
grid is also an edge of a 2k grid, so a true k=6 strip scores about as high
at 12 as at 6, while a true k=12 strip scores only about half at 6.
The grid: phase p means blocks start at columns p, p + k, ...; block u
covers canvas x in [ox + u*k, ox + (u+1)*k) clipped to the image, with ox =
p - k when p > 0 else 0 (a partial first block), and likewise in y.
P3 palette (above). P4 block mode over that grid, partial edge blocks
included.
P5 bg = most common index on the outer 1 px ring (ties to the lowest index);
alpha 0 for every pixel of that index. Sanity check, per frame: of the
figure's silhouette inside its bbox (non-bg pixels of the cell, plus the
bg-index pixels in the bbox that a 4-connected flood fill of bg pixels from
the border does NOT reach), the unreached bg-index share must be <=
BG_INSIDE_MAX; if any frame exceeds it, key ONLY the flood-reached pixels,
strip-wide, and flag "bg_flood_fill". The brief's literal "bg pixels inside
the bbox <= 10%" is not used: measured on the synthetic walk strip, 27-49%
of each figure's bbox is background between the legs and around the arms,
so that reading rejects every strip. Enclosed key-colour pixels are what a
figure drawn partly in the key colour produces.
P6 cut each cell: output block u belongs to cell rect [x0, x1) when its
centre ox + u*k + k//2 is in [x0, x1), same in y; opaque bbox per frame over
every opaque pixel of the cell; anchor x = the output column holding canvas
x = hip_x_src * layout.k + layout.k // 2, baseline row = the output row
holding canvas y = baseline_src * layout.k + layout.k // 2.
P7 ground frames (ground[i] and not hold_arc) shift vertically so their
lowest opaque row lands on the cell baseline; every other frame takes the
shift of the strip's first ground frame (0, flagged, when that frame is
empty); frame box = union of the aligned bboxes (relative to hip and
baseline) plus a 1 px transparent margin on every side, each dimension
rounded up to even by one more column on the right or one more row on top,
shared by all frames with the hip at the same x.
P8 (lever, `remove_orphans`, off by default): an opaque pixel with no
same-index 4-neighbour takes the most common value among its 4 neighbours
(transparent counts as a value and wins ties), all read from the grid
before any replacement.
P9 validate: frame_count -- connected figures (8-connected opaque pixels,
components of at least FIGURE_MIN_SHARE of the largest one) number exactly
layout.count and each cell holds exactly one figure centre; opaque_px --
opaque pixel count per frame within OPAQUE_TOLERANCE of the strip median;
ground_height -- ground-frame bbox height within GROUND_HEIGHT_TOLERANCE of
the ground median; used_colours -- distinct RGB values among opaque pixels
of the EMITTED strip PNG <= palette size; center_snap -- each figure's bbox
centre, mapped back to canvas pixels, snaps to centers[i].
P10 emit the RGBA strip (frames left to right, facing right), one PNG per
frame, and the sidecar. The sidecar `palette` lists the colours the strip
actually uses, in reference-palette index order (brief P8's "drop unused
entries"); the full reference palette is `palette_png`.

PUBLIC NAMES BEYOND THE CONTRACT
--------------------------------
`HARMONIC_RATIO`, `FIGURE_MIN_SHARE`, `PALETTE_METHOD`, `CORE_INSET`,
`MERGE_DISTANCE`, `used_colours_verdict`; `pixelize(...,
remove_orphans=False)` (P8); validation also carries "background":
{"index", "rgb", "enclosed_ratio" (per frame), "flood_fill"}.
"""
from __future__ import annotations

import io
import statistics
from dataclasses import dataclass
from typing import Sequence

from PIL import Image, ImageChops

from tools.nai.model import DEFAULT_COLOURS, INIT_K, Layout, snap

K_RANGE: tuple[int, ...] = tuple(range(6, 13))
PREFERRED_K = INIT_K
TIE_TOLERANCE = 0.05
HARMONIC_RATIO = 0.75
BG_INSIDE_MAX = 0.10
OPAQUE_TOLERANCE = 0.40
"""Brief P9 said 0.25 (DESIGN). Measured on mannequin.render_init's own walk
strip: contact frames hold 478 opaque pixels, pass frames 353 and the idle
334, so a contact frame sits 35% above the median and 0.25 rejects the ideal
init. A missing figure (100% below) or two figures in a cell (~100% above)
still fail at 0.40."""
GROUND_HEIGHT_TOLERANCE = 0.15
FIGURE_MIN_SHARE = 0.20
CORE_INSET = 1
MERGE_DISTANCE = 12.0
COLOURS_RANGE: tuple[int, int] = (8, 32)
PALETTE_METHOD = Image.Quantize.MAXCOVERAGE

SIDECAR_KEYS: tuple[str, ...] = (
    "frame_w", "frame_h", "count", "fps_hint", "anchor_x", "baseline_y",
    "k", "phase", "palette", "ledger_id", "strip_version",
)
"""P10 sidecar keys, in order. phase is [x, y]; palette is ["#rrggbb", ...]."""

VALIDATION_KEYS: tuple[str, ...] = (
    "frame_count", "opaque_px", "ground_height", "used_colours", "center_snap",
)
"""Each is {"ok": bool, "detail": ...}; validation also has "ok" (all five
ok), "flags" (a list of strings, e.g. "bg_flood_fill") and "background"."""

_TRANSPARENT = -1
_LUMA_R = tuple(299 * v for v in range(256))
_LUMA_G = tuple(587 * v for v in range(256))
_LUMA_B = tuple(114 * v for v in range(256))


@dataclass(frozen=True)
class GridFit:
    """P2's answer: pseudo-pixel size, phase, and the two peak scores."""
    k: int
    phase_x: int
    phase_y: int
    score_x: float
    score_y: float


@dataclass(frozen=True)
class Pixelized:
    """P10's output.

    strip_rgba_png: all frames left to right in one RGBA PNG, each
    frame_w x frame_h, facing right. frames: one RGBA PNG per frame.
    sidecar: SIDECAR_KEYS. k and phase (x, y) from P2. palette_png: the
    mode-P reference palette (the input one when given). validation: see
    VALIDATION_KEYS.
    """
    strip_rgba_png: bytes
    frames: tuple[bytes, ...]
    sidecar: dict
    k: int
    phase: tuple[int, int]
    palette_png: bytes
    validation: dict


# ---------------------------------------------------------------------------
# P1, P2
# ---------------------------------------------------------------------------


def _open_png(png_bytes: bytes, what: str) -> Image.Image:
    if not isinstance(png_bytes, (bytes, bytearray)):
        raise ValueError(f"{what}: expected PNG bytes, got "
                         f"{type(png_bytes).__name__}")
    try:
        im = Image.open(io.BytesIO(png_bytes))
        im.load()
    except Exception as exc:  # Pillow raises several unrelated classes
        raise ValueError(f"{what}: not a readable image ({exc})") from None
    if im.format != "PNG":
        raise ValueError(f"{what}: expected a PNG, got {im.format}")
    return im


def _png(im: Image.Image) -> bytes:
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _axis_scores(energy: Sequence[int], k: int) -> tuple[float, int]:
    """(max over phase of S(k, phase), the first phase reaching it).

    energy[0] is a placeholder; positions start at 1.
    """
    n = len(energy)
    total = sum(energy[1:])
    if total <= 0 or n < 2:
        return 0.0, 0
    overall = total / (n - 1)
    best, best_phase = -1.0, 0
    for phase in range(k):
        picked = energy[phase if phase else k::k]
        score = (sum(picked) / len(picked)) / overall if picked else 0.0
        if score > best:
            best, best_phase = score, phase
    return best, best_phase


def _grid_fit(rgb: Image.Image) -> GridFit:
    width, height = rgb.size
    floor = 2 * max(K_RANGE)
    if width < floor or height < floor:
        raise ValueError(f"detect_grid: {width}x{height} is smaller than "
                         f"{floor}x{floor}")
    data = rgb.tobytes()
    luma = bytes([(_LUMA_R[r] + _LUMA_G[g] + _LUMA_B[b]) // 1000
                  for r, g, b in zip(data[0::3], data[1::3], data[2::3])])
    lum = Image.frombytes("L", (width, height), luma)
    dx = ImageChops.difference(lum.crop((1, 0, width, height)),
                               lum.crop((0, 0, width - 1, height))).tobytes()
    ex = [0] + [sum(dx[c::width - 1]) for c in range(width - 1)]
    dy = ImageChops.difference(lum.crop((0, 1, width, height)),
                               lum.crop((0, 0, width, height - 1))).tobytes()
    ey = [0] + [sum(dy[r * width:(r + 1) * width]) for r in range(height - 1)]

    fits: dict[int, tuple[float, float, float, int, int]] = {}
    for k in K_RANGE:
        sx, px = _axis_scores(ex, k)
        sy, py = _axis_scores(ey, k)
        fits[k] = (sx + sy, sx, sy, px, py)
    best = K_RANGE[0]
    for k in K_RANGE:
        if fits[k][0] > fits[best][0]:
            best = k
    chosen = best
    if fits[PREFERRED_K][0] >= (1.0 - TIE_TOLERANCE) * fits[best][0]:
        chosen = PREFERRED_K
    elif best % 2 == 0 and best // 2 in fits \
            and fits[best // 2][0] >= HARMONIC_RATIO * fits[best][0]:
        chosen = best // 2
    _, sx, sy, px, py = fits[chosen]
    return GridFit(k=chosen, phase_x=px, phase_y=py, score_x=sx, score_y=sy)


def detect_grid(png_bytes: bytes) -> GridFit:
    """P2 over an RGB-convertible PNG. Deterministic; ValueError for an image
    narrower or shorter than 2 * max(K_RANGE)."""
    return _grid_fit(_open_png(png_bytes, "detect_grid").convert("RGB"))


# ---------------------------------------------------------------------------
# Grid geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Grid:
    k: int
    ox: int
    oy: int
    nx: int
    ny: int

    @classmethod
    def of(cls, fit: GridFit, width: int, height: int) -> "_Grid":
        k = fit.k
        ox = fit.phase_x - k if fit.phase_x else 0
        oy = fit.phase_y - k if fit.phase_y else 0
        return cls(k=k, ox=ox, oy=oy, nx=-(-(width - ox) // k),
                   ny=-(-(height - oy) // k))

    def span(self, e0: int, e1: int, offset: int, n: int) -> tuple[int, int]:
        """Blocks whose centre offset + u*k + k//2 lies in [e0, e1)."""
        half = self.k // 2
        u0 = -((offset + half - e0) // self.k)
        u1 = -((offset + half - e1) // self.k)
        return max(0, min(n, u0)), max(0, min(n, u1))

    def column(self, x: int) -> int:
        return min(self.nx - 1, max(0, (x - self.ox) // self.k))

    def row(self, y: int) -> int:
        return min(self.ny - 1, max(0, (y - self.oy) // self.k))


# ---------------------------------------------------------------------------
# P3, P4
# ---------------------------------------------------------------------------


def _block_medians(rgb: Image.Image, grid: "_Grid") -> Image.Image:
    """nx x ny RGB: per block, the per-channel median of the block's core.

    The core drops CORE_INSET pixels on every side where the block is big
    enough, so a blur or anti-alias ring does not vote; the median of the
    rest removes per-pixel noise without averaging two flat colours.
    """
    width, height = rgb.size
    k = grid.k
    out = []
    for v in range(grid.ny):
        y0, y1 = max(0, grid.oy + v * k), min(height, grid.oy + (v + 1) * k)
        if y1 - y0 > 2 * CORE_INSET:
            y0, y1 = y0 + CORE_INSET, y1 - CORE_INSET
        for u in range(grid.nx):
            x0 = max(0, grid.ox + u * k)
            x1 = min(width, grid.ox + (u + 1) * k)
            if x1 - x0 > 2 * CORE_INSET:
                x0, x1 = x0 + CORE_INSET, x1 - CORE_INSET
            data = rgb.crop((x0, y0, x1, y1)).tobytes()
            mid = (len(data) // 3) // 2
            out.append((sorted(data[0::3])[mid], sorted(data[1::3])[mid],
                        sorted(data[2::3])[mid]))
    mosaic = Image.new("RGB", (grid.nx, grid.ny))
    mosaic.putdata(out)
    return mosaic


def _palette_image(rgb: Image.Image, colours: int, grid: "_Grid") -> Image.Image:
    """The first strip's reference palette (see the module docstring).

    Block-core medians, quantised to `colours` with PALETTE_METHOD, then
    near-duplicates merged: entries in descending population order, each
    joining the first kept entry within MERGE_DISTANCE (Euclidean RGB) of
    it, a kept colour being the population-weighted mean of its members.
    """
    mosaic = _block_medians(rgb, grid)
    quantized = mosaic.quantize(colors=colours, method=PALETTE_METHOD)
    raw = (quantized.getpalette() or [])[:colours * 3]
    hist = quantized.histogram()
    order = sorted(range(len(raw) // 3), key=lambda i: (-hist[i], i))
    kept: list[list[int]] = []  # seed r, g, b, population, sum r, g, b
    for i in order:
        if hist[i] == 0:
            continue
        r, g, b = raw[i * 3:i * 3 + 3]
        for entry in kept:
            if ((entry[0] - r) ** 2 + (entry[1] - g) ** 2
                    + (entry[2] - b) ** 2) <= MERGE_DISTANCE ** 2:
                entry[3] += hist[i]
                entry[4] += r * hist[i]
                entry[5] += g * hist[i]
                entry[6] += b * hist[i]
                break
        else:
            kept.append([r, g, b, hist[i], r * hist[i], g * hist[i],
                         b * hist[i]])
    if not kept:
        raise ValueError("pixelize: quantize produced an empty palette")
    entries: list[int] = []
    for _, _, _, n, sr, sg, sb in kept:
        entries.extend(((sr + n // 2) // n, (sg + n // 2) // n,
                        (sb + n // 2) // n))
    pal = Image.new("P", (len(kept), 1))
    pal.putdata(list(range(len(kept))))
    pal.putpalette(entries)
    return pal


def _load_palette(palette_png: bytes) -> Image.Image:
    pal = _open_png(palette_png, "palette_png")
    if pal.mode != "P":
        raise ValueError(f"palette_png: mode {pal.mode}, expected P")
    return pal


def _block_modes(indexed: Image.Image, grid: _Grid) -> list[int]:
    width, height = indexed.size
    k = grid.k
    out: list[int] = []
    for v in range(grid.ny):
        y0, y1 = max(0, grid.oy + v * k), min(height, grid.oy + (v + 1) * k)
        for u in range(grid.nx):
            x0 = max(0, grid.ox + u * k)
            x1 = min(width, grid.ox + (u + 1) * k)
            hist = indexed.crop((x0, y0, x1, y1)).histogram()
            out.append(hist.index(max(hist)))
    return out


# ---------------------------------------------------------------------------
# P5, P8
# ---------------------------------------------------------------------------


def _ring_mode(cells: list[int], nx: int, ny: int) -> int:
    ring = set()
    for u in range(nx):
        ring.add((u, 0))
        ring.add((u, ny - 1))
    for v in range(ny):
        ring.add((0, v))
        ring.add((nx - 1, v))
    counts: dict[int, int] = {}
    for u, v in ring:
        idx = cells[v * nx + u]
        counts[idx] = counts.get(idx, 0) + 1
    top = max(counts.values())
    return min(i for i, c in counts.items() if c == top)


def _flood_from_border(cells: list[int], nx: int, ny: int,
                       value: int) -> bytearray:
    reached = bytearray(nx * ny)
    stack = []
    for u in range(nx):
        stack.append(u)
        stack.append((ny - 1) * nx + u)
    for v in range(ny):
        stack.append(v * nx)
        stack.append(v * nx + nx - 1)
    while stack:
        p = stack.pop()
        if reached[p] or cells[p] != value:
            continue
        reached[p] = 1
        u, v = p % nx, p // nx
        if u > 0:
            stack.append(p - 1)
        if u < nx - 1:
            stack.append(p + 1)
        if v > 0:
            stack.append(p - nx)
        if v < ny - 1:
            stack.append(p + nx)
    return reached


def _remove_orphans(cells: list[int], nx: int, ny: int) -> list[int]:
    out = list(cells)
    for v in range(ny):
        for u in range(nx):
            p = v * nx + u
            here = cells[p]
            if here == _TRANSPARENT:
                continue
            around = []
            if u > 0:
                around.append(cells[p - 1])
            if u < nx - 1:
                around.append(cells[p + 1])
            if v > 0:
                around.append(cells[p - nx])
            if v < ny - 1:
                around.append(cells[p + nx])
            if not around or here in around:
                continue
            counts: dict[int, int] = {}
            for value in around:
                counts[value] = counts.get(value, 0) + 1
            top = max(counts.values())
            out[p] = min(value for value, c in counts.items() if c == top)
    return out


def _components(cells: list[int], nx: int, ny: int) -> list[tuple[int, tuple[int, int, int, int]]]:
    """8-connected opaque components: (size, (u0, v0, u1, v1) inclusive)."""
    seen = bytearray(nx * ny)
    found = []
    for start in range(nx * ny):
        if seen[start] or cells[start] == _TRANSPARENT:
            continue
        seen[start] = 1
        stack = [start]
        size = 0
        u0 = v0 = 1 << 30
        u1 = v1 = -1
        while stack:
            p = stack.pop()
            size += 1
            u, v = p % nx, p // nx
            u0, u1, v0, v1 = min(u0, u), max(u1, u), min(v0, v), max(v1, v)
            for dv in (-1, 0, 1):
                vv = v + dv
                if vv < 0 or vv >= ny:
                    continue
                for du in (-1, 0, 1):
                    uu = u + du
                    if uu < 0 or uu >= nx:
                        continue
                    q = vv * nx + uu
                    if not seen[q] and cells[q] != _TRANSPARENT:
                        seen[q] = 1
                        stack.append(q)
        found.append((size, (u0, v0, u1, v1)))
    return found


# ---------------------------------------------------------------------------
# pixelize
# ---------------------------------------------------------------------------


def _bbox(pixels: Sequence[tuple[int, int, int]]) -> tuple[int, int, int, int] | None:
    if not pixels:
        return None
    us = [p[0] for p in pixels]
    vs = [p[1] for p in pixels]
    return min(us), min(vs), max(us), max(vs)


def _within(value: float, median: float, tolerance: float) -> bool:
    return median > 0 and abs(value - median) <= tolerance * median


def used_colours_verdict(strip_png: bytes, palette_size: int) -> dict:
    """P9 used_colours: {"ok": distinct RGB values among the opaque pixels
    of `strip_png` <= palette_size, "detail": {"used", "palette_size"}}.

    Inside `pixelize` this holds by construction -- measured on Pillow 10.2,
    quantize(palette=) maps only onto the palette's own entries, even for a
    2-entry palette and a colour equidistant from both -- so it is a
    tripwire for a future change to the mapping, and it is a separate
    function so a check can hand it a strip that breaks it.
    """
    emitted = Image.open(io.BytesIO(strip_png)).convert("RGBA").tobytes()
    used = {emitted[p:p + 3] for p in range(0, len(emitted), 4)
            if emitted[p + 3]}
    return {
        "ok": len(used) <= palette_size,
        "detail": {"used": len(used), "palette_size": palette_size},
    }


def pixelize(png_bytes: bytes, layout: Layout, *,
             centers: Sequence[tuple[float, float]],
             ground: Sequence[bool],
             hold_arc: bool = False,
             palette_png: bytes | None = None,
             colours: int = DEFAULT_COLOURS,
             fps_hint: int = 8,
             ledger_id: str | None = None,
             strip_version: int = 1,
             remove_orphans: bool = False) -> Pixelized:
    """P1-P10 over one strip; see the module docstring.

    `centers` are the snapped centers the request carried (from
    mannequin.render_init); `ground` is recipe.ground; `hold_arc` is
    recipe.hold_arc; `fps_hint`, `ledger_id` and `strip_version` go to the
    sidecar verbatim; `remove_orphans` turns on lever P8. ValueError when:
    the PNG is not layout-sized; len of centers or ground != layout.count;
    a center is not two numbers; no frame is ground; colours is outside
    COLOURS_RANGE; palette_png is given and is not a mode-P PNG.
    """
    # -- P1 and argument checks --------------------------------------------
    count = layout.count
    if len(centers) != count:
        raise ValueError(f"pixelize: {len(centers)} centers for a "
                         f"{count}-cell layout {layout.name}")
    if len(ground) != count:
        raise ValueError(f"pixelize: {len(ground)} ground flags for a "
                         f"{count}-cell layout {layout.name}")
    wanted_centers: list[tuple[float, float]] = []
    for i, center in enumerate(centers):
        if len(center) != 2 or any(isinstance(c, bool)
                                   or not isinstance(c, (int, float))
                                   for c in center):
            raise ValueError(f"pixelize: center {i} {center!r} is not two "
                             f"numbers")
        wanted_centers.append((float(center[0]), float(center[1])))
    if not any(ground):
        raise ValueError("pixelize: no frame is a ground frame")
    lo, hi = COLOURS_RANGE
    if isinstance(colours, bool) or not isinstance(colours, int) \
            or not lo <= colours <= hi:
        raise ValueError(f"pixelize: colours {colours!r} is outside "
                         f"{lo}..{hi}")
    source = _open_png(png_bytes, "pixelize")
    if source.size != (layout.width, layout.height):
        raise ValueError(f"pixelize: image is {source.size[0]}x"
                         f"{source.size[1]}, layout {layout.name} is "
                         f"{layout.width}x{layout.height}")
    rgb = source.convert("RGB")
    width, height = rgb.size

    # -- P2 ----------------------------------------------------------------
    fit = _grid_fit(rgb)
    grid = _Grid.of(fit, width, height)
    nx, ny = grid.nx, grid.ny

    # -- P3 ----------------------------------------------------------------
    if palette_png is None:
        pal_image = _palette_image(rgb, colours, grid)
        pal_bytes = _png(pal_image)
    else:
        pal_image = _load_palette(palette_png)
        pal_bytes = bytes(palette_png)
    pal_entries = pal_image.getpalette() or []
    palette_size = len(pal_entries) // 3
    indexed = rgb.quantize(palette=pal_image, dither=Image.Dither.NONE)

    # -- P4 ----------------------------------------------------------------
    cells = _block_modes(indexed, grid)

    # -- P5 ----------------------------------------------------------------
    flags: list[str] = []
    bg = _ring_mode(cells, nx, ny)
    reached = _flood_from_border(cells, nx, ny, bg)
    spans = []
    for cell in layout.cells:
        x0, y0, x1, y1 = cell.rect_canvas
        spans.append((grid.span(x0, x1, grid.ox, nx),
                      grid.span(y0, y1, grid.oy, ny)))
    enclosed_ratio: list[float] = []
    for (u0, u1), (v0, v1) in spans:
        figure = [(u, v, 0) for v in range(v0, v1) for u in range(u0, u1)
                  if cells[v * nx + u] != bg]
        box = _bbox(figure)
        if box is None:
            enclosed_ratio.append(0.0)
            continue
        bu0, bv0, bu1, bv1 = box
        enclosed = sum(1 for v in range(bv0, bv1 + 1)
                       for u in range(bu0, bu1 + 1)
                       if cells[v * nx + u] == bg and not reached[v * nx + u])
        enclosed_ratio.append(round(enclosed / (len(figure) + enclosed), 4))
    flood_fill = any(r > BG_INSIDE_MAX for r in enclosed_ratio)
    if flood_fill:
        flags.append("bg_flood_fill")
        keyed = [_TRANSPARENT if reached[p] else cells[p]
                 for p in range(nx * ny)]
    else:
        keyed = [_TRANSPARENT if c == bg else c for c in cells]

    # -- P8 ----------------------------------------------------------------
    if remove_orphans:
        keyed = _remove_orphans(keyed, nx, ny)
        flags.append("orphans_removed")

    # -- P6 ----------------------------------------------------------------
    frame_pixels: list[list[tuple[int, int, int]]] = []
    boxes: list[tuple[int, int, int, int] | None] = []
    anchors: list[tuple[int, int]] = []
    for i, ((u0, u1), (v0, v1)) in enumerate(spans):
        pixels = [(u, v, keyed[v * nx + u]) for v in range(v0, v1)
                  for u in range(u0, u1) if keyed[v * nx + u] != _TRANSPARENT]
        frame_pixels.append(pixels)
        boxes.append(_bbox(pixels))
        cell = layout.cells[i]
        anchors.append((
            grid.column(cell.hip_x_src * layout.k + layout.k // 2),
            grid.row(cell.baseline_src * layout.k + layout.k // 2)))
        if boxes[-1] is None:
            flags.append(f"empty_frame:{i}")

    # -- P7 ----------------------------------------------------------------
    first_ground = next(i for i in range(count) if ground[i])
    if boxes[first_ground] is None:
        reference_shift = 0
        flags.append(f"first_ground_frame_empty:{first_ground}")
    else:
        reference_shift = anchors[first_ground][1] - boxes[first_ground][3]
    shifts = []
    for i in range(count):
        if ground[i] and not hold_arc and boxes[i] is not None:
            shifts.append(anchors[i][1] - boxes[i][3])
        else:
            shifts.append(reference_shift)
    rel = []
    for i in range(count):
        box = boxes[i]
        if box is None:
            continue
        hip_u, base_v = anchors[i]
        rel.append((box[0] - hip_u, box[1] + shifts[i] - base_v,
                    box[2] - hip_u, box[3] + shifts[i] - base_v))
    if rel:
        min_x = min(r[0] for r in rel)
        min_y = min(r[1] for r in rel)
        max_x = max(r[2] for r in rel)
        max_y = max(r[3] for r in rel)
    else:
        min_x = min_y = max_x = max_y = 0
    frame_w = max_x - min_x + 1 + 2
    frame_h = max_y - min_y + 1 + 2
    top_pad = 1
    if frame_w % 2:
        frame_w += 1
    if frame_h % 2:
        frame_h += 1
        top_pad = 2
    anchor_x = 1 - min_x
    baseline_y = top_pad - min_y

    # -- P10 (images) ------------------------------------------------------
    rgb_of = [tuple(pal_entries[i * 3:i * 3 + 3]) for i in range(palette_size)]
    strip = Image.new("RGBA", (frame_w * count, frame_h), (0, 0, 0, 0))
    frames_png: list[bytes] = []
    for i in range(count):
        buf = bytearray(frame_w * frame_h * 4)
        hip_u, base_v = anchors[i]
        for u, v, idx in frame_pixels[i]:
            fx = u - hip_u + anchor_x
            fy = v + shifts[i] - base_v + baseline_y
            p = (fy * frame_w + fx) * 4
            r, g, b = rgb_of[idx]
            buf[p:p + 4] = bytes((r, g, b, 255))
        frame = Image.frombytes("RGBA", (frame_w, frame_h), bytes(buf))
        frames_png.append(_png(frame))
        strip.paste(frame, (i * frame_w, 0))
    strip_png = _png(strip)

    # -- P9 ----------------------------------------------------------------
    comps = _components(keyed, nx, ny)
    largest = max((size for size, _ in comps), default=0)
    figures = [box for size, box in comps
               if largest and size >= FIGURE_MIN_SHARE * largest]
    per_cell = [0] * count
    stray = 0
    for fu0, fv0, fu1, fv1 in figures:
        cu, cv = (fu0 + fu1 + 1) / 2, (fv0 + fv1 + 1) / 2
        for i, ((u0, u1), (v0, v1)) in enumerate(spans):
            if u0 <= cu < u1 and v0 <= cv < v1:
                per_cell[i] += 1
                break
        else:
            stray += 1
    frame_count = {
        "ok": len(figures) == count and all(n == 1 for n in per_cell),
        "detail": {"expected": count, "figures": len(figures),
                   "per_cell": per_cell, "outside_cells": stray},
    }

    opaque = [len(p) for p in frame_pixels]
    opaque_median = statistics.median(opaque)
    opaque_px = {
        "ok": all(_within(n, opaque_median, OPAQUE_TOLERANCE) for n in opaque),
        "detail": {"counts": opaque, "median": opaque_median},
    }

    heights = [(boxes[i][3] - boxes[i][1] + 1) if boxes[i] else 0
               for i in range(count) if ground[i]]
    height_median = statistics.median(heights)
    ground_height = {
        "ok": all(_within(h, height_median, GROUND_HEIGHT_TOLERANCE)
                  for h in heights),
        "detail": {"heights": heights, "median": height_median},
    }

    used_colours = used_colours_verdict(strip_png, palette_size)

    snapped: list[list[float] | None] = []
    snap_ok = True
    for i in range(count):
        box = boxes[i]
        if box is None:
            snapped.append(None)
            snap_ok = False
            continue
        cx = grid.ox + (box[0] + box[2] + 1) * grid.k / 2
        cy = grid.oy + (box[1] + box[3] + 1) * grid.k / 2
        got = [snap(min(1.0, max(0.0, cx / width))),
               snap(min(1.0, max(0.0, cy / height)))]
        snapped.append(got)
        if tuple(got) != wanted_centers[i]:
            snap_ok = False
    center_snap = {
        "ok": snap_ok,
        "detail": {"expected": [list(c) for c in wanted_centers],
                   "found": snapped},
    }

    validation: dict = {
        "frame_count": frame_count,
        "opaque_px": opaque_px,
        "ground_height": ground_height,
        "used_colours": used_colours,
        "center_snap": center_snap,
    }
    validation["ok"] = all(validation[key]["ok"] for key in VALIDATION_KEYS)
    validation["flags"] = flags
    validation["background"] = {
        "index": bg, "rgb": "#%02x%02x%02x" % rgb_of[bg],
        "enclosed_ratio": enclosed_ratio, "flood_fill": flood_fill,
    }

    # -- P10 (sidecar) -----------------------------------------------------
    used_indices = sorted({idx for pixels in frame_pixels
                           for _, _, idx in pixels})
    sidecar = {
        "frame_w": frame_w,
        "frame_h": frame_h,
        "count": count,
        "fps_hint": fps_hint,
        "anchor_x": anchor_x,
        "baseline_y": baseline_y,
        "k": fit.k,
        "phase": [fit.phase_x, fit.phase_y],
        "palette": ["#%02x%02x%02x" % rgb_of[i] for i in used_indices],
        "ledger_id": ledger_id,
        "strip_version": strip_version,
    }
    return Pixelized(strip_rgba_png=strip_png, frames=tuple(frames_png),
                     sidecar=sidecar, k=fit.k,
                     phase=(fit.phase_x, fit.phase_y),
                     palette_png=pal_bytes, validation=validation)
