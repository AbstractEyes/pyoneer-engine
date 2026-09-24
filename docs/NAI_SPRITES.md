<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written 2026-09-17 from the tools/nai contract docstrings and the NovelAI research brief; no command here has been run against NovelAI yet, so every cost claim says in place whether it is proven, and the baseline sprites were measured by the commands in their CREDITS.md. The build axis, the gunslinger garments and the garet example were added 2026-09-17; every number in them was measured off data/graphics/tilesets/Characters/~Garet.png or off a render, and tools/check_nai.py asserts the ones that are invariants. Request files (plan-request, run-request, request-catalog) were added 2026-09-19 and were run offline only, against a recording transport, by tools/check_nai.py section 8c. On 2026-09-24, at the author's instruction, every balance event became a warning that never stops a send; "Is it free?", "The books" and the probe rules below say so, and tools/check_nai.py sections 2, 3, 8 and 8b assert it, each half proved red by a mutant. Also on 2026-09-24, at the author's word that curated is billed as full is, one proof came to stand for its action on both V4.5 variants (model.Proof.covers); tools/check_nai.py section 2 asserts both halves, each proved red by a mutant. -->

# NovelAI sprites — side-scroller strips on the Opus free tier

Questions that land here:

- *"how do I generate sprites with NovelAI"*
- *"how do I run img2img or inpainting"*
- *"is this generation free"*
- *"how do I ask an agent for a new character"*
- *"is this outfit a data file or mannequin code"*
- *"how do I change a character's proportions"* / *"his legs are too short"*
- *"where do the reference sprites come from"*
- *"how do I send part of an image to NovelAI"* / *"what is a request file"*

## What it is for

`tools/nai` turns a strip recipe (`walk`, `run` or `jump`) into a pixel-art
strip facing right. It draws a mannequin on a grey `#808080` key (a 40 px
figure, ×8 onto a 1216×832 canvas) and sends **one** NovelAI V4.5 request built
from it. It records the Anlas balance before and after, then turns the image
into real pixel art: one grid, one palette, a block-mode downscale, a keyed
background, baseline-aligned frames and a sidecar JSON. The game never imports
it or loads what it writes.

## Is it free?

The tool sends only what the Opus plan generates for free, and every base
caption ends in `rating:general`. One guard runs before any socket opens and
refuses:

- any model except `nai-diffusion-4-5-full` or `-curated` (infill uses their
  `-inpainting` twins). V5 draws on the usage battery, so it is never allowed.
- more than 1,048,576 pixels, more than 28 steps, or more than one sample
- Precise Reference, Vibe Transfer and streaming
- a body whose image fields do not belong to its action (a generate carrying
  an image or a strength, an img2img carrying a mask)
- an account that is not an active Opus (tier 3) plan, or that is in grace
- a `LOCK` file (only ever placed by hand: the author's emergency stop) or
  an `INFLIGHT` file (a send whose row may be missing)
- an empty ledger beside `blobs/` or `proofs.json`: the ledger was lost, and
  the balance chain cannot safely start over

**A balance event warns; it never stops anything.** The author's decision,
2026-09-24: *"Don't worry about the costs, it's a shared account. Downgrade
the LOCK to a warning, and don't stop the process via a warning."* So a fall
inside one of our rows (our own charge), a fall between two rows (somebody
else's spend, or a late charge of ours), a proof the balance has refuted, and
a request **interrupted** after it was sent (Ctrl-C, outcome unknown) are
each printed as `WARNING`, written into that row's `warning` column and kept
in the books, and the send goes ahead. Nothing in the tool writes `LOCK` any
more. What still refuses is what decides what is SENT -- the model, the
size, the steps, the samples, the references, the captions, the tier -- and
never what the balance did. Nothing is retried automatically: not a 429, not
a 5xx, not a timeout.

## The books

**A shared account drifts.** If anyone else generates on the same NovelAI
login, the balance falls while this tool is doing nothing, and the tool WILL
see it. It is never guessed at and never quietly absorbed, because a balance
can fall in two places and they are not the same measurement:

| where the fall is | what it means | what happens |
|---|---|---|
| **inside one of our rows** — that row's own `account_after` below its own `account_before` | our request is the only thing between those two reads, so **the charge is ours** | a `WARNING` in that row and in `ours spent`, and that action's proof refuted **for good** -- itself a warning: the action is still sent. No signature can absorb, clear or excuse it. |
| **between two rows** — one row's `account_after`, then the next row's `account_before`, lower | no row of ours lies between those two reads. That is **not** the same as "nothing of ours was charged": see the boundary table below | a `WARNING` every time it is seen (condition 9), printing both balances, the delta, the window, and the command that signs it. It stays on the books as `UNSIGNED` until the author signs it. |

**A fall between two rows is classified, never assumed.** The only thing the
ledger knows about that window is whether the earlier row put anything on the
wire:

| the earlier row | the boundary | who signs it |
|---|---|---|
| a `refused` row — the guard refused it after reading the balance and before any byte left | **EXTERNAL**: no request of ours was outstanding, so the drop cannot be a late charge of ours | `acknowledge-drift`. Calling it somebody else's is still the author's judgement, and `--checked` records what he looked at |
| a `generation` row — a request of ours went out, or may have (an interrupted POST is recorded the same way) | **AMBIGUOUS**: a debit the server applied after that row's own after-read (risk R4) is byte-identical to a friend's spend. Nothing here can tell them apart | `resolve-boundary`, the louder verb: it needs `--attribute theirs|ours` as well, and records the hand check that decided it |

```
.venv/Scripts/python.exe -m tools.nai acknowledge-drift --previous <id> --observed <id>     --anlas 1746 --by phil --checked "the provider usage page; my friend generated today"
.venv/Scripts/python.exe -m tools.nai resolve-boundary --previous <id> --observed <id>     --anlas 165 --attribute theirs --by phil --checked "the usage page shows their four images"
```

`--anlas` must be **exactly** the figure the ledger measured, so the author
types the number he is signing for; anything else is refused and nothing is
written. Each appends one `drift` row — both balances, the delta, the two
ledger rows the boundary sits between, who signed it, as whose, and what he
checked — and that row re-baselines **that one boundary** for the chain. A
later drop, or a larger one at the same boundary, is a different boundary and
needs its own signature.

Two things a signature never does. It **never deletes `LOCK`**: a `LOCK` is
the author's own emergency stop, and only the author lifts it. And it **never restores
a proof** — `guard.proof_standing` reads no signature at all, so signing the
boundary that refuted img2img silences the chain's warning and leaves
img2img's own warning in place. The one way to stand a refuted proof again is
to remove it from `proofs.json` by hand and probe again, paying that probe
knowingly.

`ledger` and `account` print **every figure separately, and never add any two
of them**:

```
ours spent    +0 Anlas across 17 rows this tool wrote -- each row's OWN
              after-read minus its own before-read, so a charge shows negative.
              THIS is what the tool has been measured to cost.
ours refilled +0 Anlas that arrived INSIDE one of our own rows.
theirs        +0 Anlas across 0 signature(s) ...
UNSIGNED      -1911 Anlas across 2 boundary(ies) NOT in any figure above:
              ...2495->...ac4d (-1746, AMBIGUOUS), ...b9cd->...ec39 (-165, AMBIGUOUS).
              This money HAS left the account.
```

`ours spent` is the only number that MEASURES what this pipeline costs, and at
the time of writing it is **0**. `UNSIGNED` is the figure that must never be
missing: money the ledger watched leave while nobody has typed anything. The
two boundaries above are real — 1911 Anlas left this account on 2026-09-17,
both at boundaries whose earlier row had sent a request of ours, so neither is
something this tool may call somebody else's by itself.

| request | status |
|---|---|
| generate: V4.5, ≤ 1 MP, ≤ 28 steps, 1 sample | **Free by every source**: NovelAI's docs, the website's cost code, and a third-party measurement on Opus. **Not yet measured on this account** (R3). The first `run --action generate` is that measurement. |
| img2img, same limits | **Unproven** (R1). The website code and five clients say it is free. The subscription docs say it is free only "without any other image used as a base". Refused until a probe proves it. |
| infill, same limits | **Unproven, likely free** (R2). The inpaint docs call Opus focused inpainting zero cost. Refused until a probe proves it. |
| 2+ samples, > 28 steps, > 1 MP, references, vibes, Director Tools, upscale, any V5 | Charged. The tool will not send these. |

**Probes.** A probe is how img2img and infill get unlocked: one 1216×832
request at 4 steps and strength 0.3. The output is junk; only the balance
matters.
- If it returns 2xx carrying the image, at the requested size, with an
  unchanged balance, the tool writes a proof row to `data/nai/proofs.json`
  for that action and model. A 2xx with no image in it (an HTML page, an
  empty body, a 204, JSON) proves nothing and writes no proof.
- **One proof stands for both variants.** NovelAI bills the curated model
  exactly as it bills the full one. The author, 2026-09-24: *"The curated
  model is in the same system, the same costs apply. So in our case no
  costs."* So a proof answers for its action on full AND curated
  (`model.Proof.covers`):
  - a curated call rides the full model's proof, and the reverse;
  - a probe of a pair whose twin is proven is refused, as having nothing
    left to measure;
  - a charged call on EITHER variant refutes the one proof they share.

  A proof never crosses actions: an img2img proof says nothing about
  infill.
- The proof stands only once the **next** balance read still shows the
  probe's balance. A read **above** it (a refill, which can hide a charge)
  refutes it for good: re-measuring then means the author removes that proof
  from `proofs.json` by hand and probes again. A REFUTED proof is a warning
  on every later call of its action, never a refusal; a proof that names no
  probe row, or a probe row that measured nothing, is still refused.
- A read **below** it refutes it **for good** as well. The probe's own
  request went out, so a debit the server applied after the probe's
  after-read (R4) lands exactly there and is byte-identical to somebody
  else's spend; the unsafe reading is the one that counts. Signing that
  boundary re-baselines the chain and leaves the proof refuted.
- A **later** img2img or infill call the proof covers, on either variant,
  charged **inside its own
  row**, or one whose after-read failed, refutes the proof for good in the
  same way, and its own row's warning says the action is charged. So does a
  fall in the read that **follows** such a call, for the R4 reason above.
- If it is charged, the client formula puts the worst case at 2 Anlas, and the
  probe's row warns and writes no proof.

Run the generate track first. Then probe img2img and infill separately, one
decision each. **Only the author types `--accept-max-2-anlas`, spelled out in
full: no abbreviation of any option is accepted. An agent never passes it and
never deletes a `LOCK` the author placed.**

## The key

`NAI_KEY`, a Windows **user** environment variable, read at send time and
never logged, stored, echoed or put in a URL. `tools/check_secrets.py` flags a
NovelAI token in any tracked file. Set it outside shell history:
`rundll32 sysdm.cpl,EditEnvironmentVariables`, under *User variables*.

The value must be the bare token: a space, a line break or a curly quote
inside it is refused before any request is built, with a message that names
`NAI_KEY` and never the value. A terminal, editor or agent session started
**before** it was set does not see it. In that PowerShell window, copy it in without printing it:

```powershell
$env:NAI_KEY = [Environment]::GetEnvironmentVariable('NAI_KEY', 'User')
if ($env:NAI_KEY) { 'NAI_KEY loaded' } else { 'NAI_KEY is not set for this user' }
```

The value lasts for that window and whatever it starts. `echo $env:NAI_KEY`,
`Get-ChildItem env:` and `cmd /c set` all print it.

## Commands

From the repo root: `.venv/Scripts/python.exe -m tools.nai <command>`. Exit 0
ok, 1 error, 2 refused, 3 strip rejected. Only `run`, `infill`, `run-request`
and `probe` send, at most once each, printing the ledger id, both balances and
the delta. With no `--seed`, the chosen seed is printed before sending.

| command | network | example |
|---|---|---|
| `account` | reads the balance only; writes nothing | `account` |
| `render` | none | `render walk` writes `data/nai/renders/scout_walk_init.png` |
| `plan` | none: a dry run that prints the request and every offline guard verdict | `plan walk --action img2img --seed 1234567` |
| `run` | one generate or img2img | `run walk --action generate --seed 1234567 --round 1 --lever seed` |
| `infill` | one infill of one cell | `infill walk --cell 2 --from data/nai/blobs/<sha256>.png` |
| `plan-request` | none: `plan` for a request file, any action | `plan-request editor/requests/0012-nai-garet-head/request.json` |
| `run-request` | the one request a request file describes | `run-request editor/requests/0012-nai-garet-head/request.json` |
| `request-catalog` | none: the request-file format, limits, defaults and form, as JSON | `request-catalog` |
| `probe` | none without the flag, which prints the worst case | `probe img2img` |
| `pixelize` | none | `pixelize data/nai/blobs/<sha256>.png --recipe walk` |
| `ledger` | none: the rows, then the two accounting figures | `ledger --last 5` |
| `acknowledge-drift` | none | `acknowledge-drift --anlas 1746 --by phil --checked "the usage page"` |
| `resolve-boundary` | none | `resolve-boundary --anlas 165 --attribute theirs --by phil --checked "the usage page"` |

`infill --from` takes the full 1216×832 image that `run` returned, not the
pixelized strip; RGB or opaque RGBA is accepted, real transparency is refused.
`plan` and `run` take the same `--from` for **img2img** only: a consistency
re-pass on an accepted strip instead of the mannequin init. The ledger's
`init_png_sha256` names what was sent, so a chain of passes is visible; stop
after 2 chained passes and go back to the mannequin. For later strips, give
`pixelize` the walk's reference palette with `--palette`. `render` and
`pixelize` never overwrite a file whose bytes differ.

## Request files: a slice from another tool

A recipe draws a whole strip. To send **part of an image**, such as the head a
selection covers in the Pioneer Pixel Editor, a tool writes the request as a
file and a human runs it. The tool never sends anything itself. A second
client on the same login would spend where [the books](#the-books) see only an
unexplained fall, so there is still one client: this one.

```
editor/requests/0012-nai-garet-head/     gitignored, numbered like relay bundles
    request.json      format "pyoneer.nai.request", version 1
    init.png          the canvas img2img or infill starts from
    mask.png          infill only: one white rectangle on black
    source.png        the slice at 1x, for a person; never read
    README.md         the two command lines
```

- **The same builder, guard and send.** `plan-request` prints exactly what
  `plan` prints for the same request, and `run-request` sends through
  `run.run_request`, so the file route has no rules of its own about money.
  29 steps, an area over 1,048,576 px or a width off the 64 px grid all load
  from a file and are refused by the guard's own condition number.
- **The same proofs.** img2img and infill from a file stay refused, by
  condition 1, until your own `probe` has written a proof row. A file does not
  skip the probe.
- **What a file may say** is decided in
  [`tools/nai/spec.py`](../tools/nai/spec.py), and its refusals name the file
  and the key:
  - Keys follow the action. Each one is written out and nothing is defaulted.
  - `prompt` is written without the quality tail. The tool appends it, so
    `rating:general` still closes every base caption, and a prompt that
    already carries a rating tag is refused however it is cased or spaced
    (`Rating:General`, `rating :explicit`). `model.rating_tag_in` is that one
    rule; the recipes, the character files, this loader and the guard all
    call it.
  - Every value passes the rule the recipes use: the strength band, the noise
    range, the one source-image rule (a transparent pixel is refused, never
    flattened) and the one mask shape.
  - A file has no key for the sampler, the schedule or any fixed parameter.
    The route sends what every recipe sends.
- **The ledger row.** `strip` is empty. `round`, `phase` and `lever` come from
  the file when it writes them. For infill, the mask's rectangle is recorded
  as `target_rect`, so the row says whether NovelAI changed anything outside
  it, and `run-request` writes the local composite as `infill` does.
- **`request-catalog`** prints NovelAI's form as this route fills it:
  - every control, in NovelAI's order;
  - whether it is editable, capped, derived or locked, and why;
  - every limit and default.

  The Pioneer Pixel Editor generates its `design/novelai.json` from this
  output, so its window cannot drift from the guard.

## Changing the outfit

An outfit is a data file, never a code edit: one JSON object in
`tools/nai/characters/<name>.json`, picked with `--character <name>`. The
default, `scout.json`, is held equal to the brief's identity by
`tools/check_nai.py`, so copy it to a new name instead of editing it.
`scout_blue_scarf.json` is the first copy:

```json
{
  "tags": "brown hair, short hair, blue scarf, blue tunic, brown belt, tan pants, brown boots",
  "anchor": "brown hair, blue scarf, blue tunic",
  "colours": {
    "skin": "#E8B48C", "hair": "#6B4226", "scarf": "#46A5E6", "tunic": "#3C64C8",
    "belt": "#5A3A1E", "pants": "#C8A064", "boots": "#7A4A24"
  }
}
```

`tags` goes into the base caption, `anchor` into every frame's caption, and
`colours` paints the mannequin init. A file that breaks a rule is refused
before anything is built, with a message naming the file and the field:

- the fields `tags`, `anchor` and `colours`, optionally `subject` and
  `garments` (below), nothing else, and no key written twice
- `colours` names exactly the parts this file's garments draw, each as
  `#RRGGBB` — `skin`, `hair`, `scarf`, `tunic`, `belt`, `pants` and `boots`
  for the default outfit
- tags are printable ASCII (no tab, newline or NUL) and comma-separated,
  with no empty tag; spacing around the commas does not matter
- no count (`1boy`, `2 girls`, `multiple girls`, `no humans`), no `rating:`
  tag however cased or spaced, and no quality-tail tag (`very aesthetic`, `masterpiece`, `no text`),
  in either field: the recipe writes those once, into the base caption
- no rating word (`nsfw`, `explicit`, `nude`, ...) and no view that fights
  the recipe's side view (`facing left`, `from behind`, `facing viewer`,
  ...); and no tag that is exactly one of the negative prompt's tags
  (`blurry`, `watermark`), though `cropped jacket` is fine
- these tag rules judge what the model reads: NovelAI's `{}`, `[]` and
  `1.5::...::` wrappers are looked through, **an underscore is read as a
  space** so a booru spelling is judged like the words it spells
  (`magical_girl` exactly as `magical girl`), and a count or a refused word
  is found inside a longer tag too (`brown hair 2girls`, `{nsfw}`)
- every anchor tag is also a tag in `tags`, word for word and in the same
  case
- every colour sits at least 48 away (straight-line RGB distance) from the
  grey key `#808080` and from the outline `#202020`, and the darker copies
  the mannequin draws of it (x0.7 for the far arm and leg, x0.6 for inner
  lines) each sit at least 40 away from the grey key, so a light grey such as
  `#B7B7B7` is refused: its far leg would be drawn in the key colour and
  keyed out. Nothing checks one outfit colour against another, so keep a
  scarf clearly apart from the tunic yourself: the init only separates
  colours it can see. Two garments sharing one RGB are ONE garment to the
  model however far apart they sit — `wizard_girl`'s hat and cape were both
  `#8C3CC8` and read as a purple hood — so give every garment its own value,
  not only every part a distance from the key.

Three optional fields say **who** is drawn, **what he wears** and **how he
is built**. A file that writes none of them is a boy in scout's outfit on
scout's proportions, which is why every file written before them still
loads:

- `"subject"`: `"boy"` (the default) or `"girl"`. It writes the one count tag
  at the head of the base caption (`1boy`, `1girl`), the first word of every
  frame caption, and each recipe sentence's *the same boy* / *the same girl*.
  A tag naming the other subject is then refused — `male` or `man` in a girl
  file, `woman` or `female` in a boy one — as whole words, so `boyish` names
  nobody.
- `"garments"`: `"hat"` `none`|`wizard`|`brim`, `"cape"` `false`|`true`,
  `"neck"` `scarf`|`none`, `"legwear"` `pants`|`dress`, `"footwear"`
  `boots`|`heels`, `"coat"` `false`|`true`, `"face"` `none`|`mask`.
  Each key may be left out and then means the choice named first. The
  mannequin draws them at source scale, and `colours` must name **exactly**
  the parts they draw: `skin`, `hair` and `belt` always, `scarf` for a scarf
  neck, `tunic` and `pants` for pants, `dress` for a dress, `boots` or
  `heels` for the footwear, `cape` for a cape, `hat` for a wizard hat,
  `brim` for a wide-brimmed one, `coat` for a trenchcoat and `mask` for a
  face mask. A
  colour for a part these garments never draw is refused as an unused part,
  exactly as a missing one is refused as missing. `parts_problem` answers
  with the FIRST kind of mismatch it finds, so a file that both carries a
  spare colour and lacks a needed one is refused for the spare, and meets
  the missing one on the next attempt.
- `"build"`: `"standard"` (the default), `"original"` or `"long"`. **It is
  not a garment and not a caption** — it names no colour part, writes no
  tag, and the only thing it changes is WHERE THE HIP SITS. A build adds
  source px to the thigh and the shin and takes exactly their sum off the
  torso, so `standard` 9/9/12 becomes `original` 7/8/15 and `long` 11/10/9.
  On the WALK strip the figure's TOTAL HEIGHT, its ground line, the top of
  its head above that ground line and its SHOULDER above it are identical
  on all three — measured, frame by frame, in `tools/check_nai.py` — so the
  arms hang where they hung and the ground line does not shift. What moves
  is the hip, and with it everything that hangs off the hip: the belt, an
  A-line skirt's waist, and the trenchcoat's hem.

  **That exact invariance is a property of GROUNDED, STRAIGHT-LEG POSES,
  not of the axis**, and this document used to claim it absolutely. A bent
  leg's vertical projection is shorter than its bone, so in a crouch the
  3 px moved out of the torso subtract 3 px of height and add less than 3
  back: `long` is SHORTER than `standard` on jump frame 0 and `original` is
  taller, and the shoulder moves 6 px between them. What holds on every
  shipped strip is a BOUND — no build moves any of the three by more than
  `BUILD_MAX_DRIFT` px — and `tools/check_nai.py` now measures it on all
  three recipes rather than passing `walk` four times.

  A build cannot push a figure out of its cell, but that is the PLACEMENT's
  doing and not the axis's. Three shipped combinations used to raise —
  garet on `standard` and on `original` could not draw `jump`, and neither
  could the default outfit on `original` — because a leaning pose carries
  the torso forward off the hip column the figure was pinned to, while nine
  columns of the cell went unused behind him. `mannequin._placed` now
  shifts by the LEAST that brings the drawn box inside its cell, and only
  when it is outside, so nothing that already fitted moved by a pixel. All
  3 builds x 3 recipes are rendered for the default outfit and for garet's
  on every check run.

  That is the whole point. A garment length is a CUT, in source px, and a
  cut does not stretch with the wearer — so raising the hip under a coat of
  unchanged length hands the difference to the leg. Measured on the walk
  strip: `long` shows 10–11 px of leg below the hem, `standard` 7–8,
  `original` 4–5. The author's own `~Garet.png` shows **3 px of a 45 px
  figure**, and `original` is the name of that.

The three newest garments are the gunslinger's, and each takes its own
colour part rather than borrowing one:

| choice | what is drawn at source scale | its part |
|---|---|---|
| `"hat": "brim"` | a **broad brim**, one row `BRIM_W` across on head row 1, overhanging the 8 px head by 3 at the back and 4 at the face, whose OVERHANG then droops `BRIM_DROOP_ROWS` further — the columns resting on the crown cannot fall and the columns past the head can — with a **low crown** of `CROWN_H` rows over it that never narrows past `CROWN_TAPER`. Explicitly not the wizard cone, which is twice as tall above the brim and narrows to 2 px | `brim` |
| `"coat": true` | a **trenchcoat**: a collar `COAT_COLLAR_W` across — **drawn in the MASK's colour when the wearer has one** (`COAT_COLLAR_IS_MASK`), so the dark is one unbroken mass from under the eye out over both shoulders, and in the coat's own colour when he has not — a bodice over the torso set `COAT_BODICE_BACK` px back so the coat reads OPEN and a strip of the shirt shows down the chest, and a skirt flared from `COAT_WAIST_W` at the hip to `COAT_HEM_W` at the hem, carried `COAT_SWING` px toward the leading thigh. It also takes both SLEEVES — a trenchcoat has its own. Drawn AFTER the near leg, so it covers the thigh it is meant to cover | `coat` |
| `"face": "mask"` | a **mask over the mouth and jaw**: head rows `MASK_TOP_ROW` to `MASK_TOP_ROW + MASK_ROWS`, the whole width of the head, starting on the row UNDER the eye. Take a row off the top and it covers the eye; add one at the bottom and the jaw shows | `mask` |

**Do not try to widen the brim.** Measured on the idle frame, `BRIM_W` 15
plus its outline is 17 px — the WIDEST ROW ON THE WHOLE FIGURE, out-spanning
the 14 px coat hem 1.21 to 1, where the author's own reference out-spans
its body 1.20 to 1; relative to the head this brim overhangs MORE than his
does. It was short of DEPTH, not width, and depth costs no cell at all:
that is what `BRIM_DROOP_ROWS` buys.

Two things about the coat are worth knowing before you tune it. Its skirt
hangs from the **hip** and its bodice from the **shoulder**, and that split
is what makes `build` reach the hem at all: a coat hung from the shoulder
would keep its hem at the same height above the ground on every build and
the proportion axis would do nothing. And `COAT_BODICE_BACK` must exceed
`(COAT_BODICE_W - TORSO_W) / 2` or the coat is simply closed — at 1.0 it
drew zero shirt pixels in every frame of every strip, silently.

`wizard_girl.json` is the second example, and the one that needed the fields:
a girl in a wizard hat and purple cape, a red dress and blue heels. Her hat
is a deeper violet than her cape on purpose (see the colour rule above), and
her dress stops both sleeves at the elbow, so the bare forearm carries a
one-pixel dark wrist before the hand — without it a forearm and a hand in one
skin value draw a blunt plank in the same colour as the bare far leg.

One more rule is judged when the recipe is built rather than when the file
is read: the tags and anchor must fit the token budget in every recipe, not
only the one you ask for. The anchor is repeated in every frame, six times
for `run`, so a long anchor is refused for `walk` too, with a message naming
the file, before anything is drawn or sent.

Look at the init, then send one request with it:

```powershell
.venv/Scripts/python.exe -m tools.nai render walk --character scout_blue_scarf
.venv/Scripts/python.exe -m tools.nai run walk --action generate --character scout_blue_scarf
```

`render` writes `data/nai/renders/scout_blue_scarf_walk_init.png`, beside
scout's `scout_walk_init.png` rather than over it. `plan`, `infill` and
`pixelize` take the same option, and `pixelize` writes under
`sprites/<character>/`; `probe` always uses scout. The ledger has no character
column: a row's `base_caption` names the outfit it was made for.

## Asking an agent for a character

The section above is what a character file may say. This one is what to type
at an agent so it writes one, and it turns on a single question: **can the
mannequin already draw the outfit?**

| the request | what it is |
|---|---|
| any outfit the seven garment slots above can spell, in any legal colours, for either subject, on any of the three builds | **one JSON file.** `scout_aqua_scarf.json` landed as a commit of 13 added lines and no code at all |
| a shape the mannequin does not draw — a hood, a ponytail, gloves, a sword, wings, gold trim on the dress | **an afternoon across seven files.** A choice in `model.GARMENT_SLOTS` and the parts it draws, a shape drawn at source scale in `mannequin.py` with its constants hashed beside the others, both halves of `tools/check_nai.py`, and a row here. The garment vocabulary itself arrived that way, moving `model`, `mannequin`, `characters`, `recipes`, the CLI, the check and this document |

Nothing refuses the confusion between the two. `tags` is free text, judged one
tag at a time and never against the garments, so *"give her a hood"* can come
back as a file whose caption asks for a hood the init does not draw, and no
command will say so. Make the agent tell you which side your request is on
before it writes anything. The loader is loud only about its own vocabulary:
`{"hood": true}` is *unknown garment(s) ['hood']*, a `ponytail` colour is
*unknown part(s) ['ponytail']*, and `"subject": "cat"` is *'cat' is not a
subject; legal: ('boy', 'girl')* — while `cat ears` is a perfectly legal
**tag** that draws no ears and leaves it to the diffusion model.

### What the agent assumes when you do not say

| you leave out | it assumes |
|---|---|
| the **name** | it invents one. The name is the file stem, matches `[a-z][a-z0-9_]*`, and is spelled into `renders/<name>_<recipe>_init.png` and `sprites/<name>/`, so *Aria-Nightshade* becomes `aria_nightshade` |
| **subject** | `boy`, which is scout's. There are two and no third |
| **garments** | scout's: no hat, no cape, a scarf, pants, boots, no coat, no mask. Whatever you pick, `skin`, `hair` and `belt` are drawn, so even a dress file carries a belt colour the agent chose |
| **build** | `standard`, which is scout's. Say *long legs* or *short legs* and you get `long` or `original`; nothing else in the file changes, and no caption mentions it |
| **colours** | it picks a hex from your colour word — "blue" is `#46A5E6` in `scout_blue_scarf` and `#3CC8C8` in `scout_aqua_scarf` — and **nothing compares one of your colours to another**. Every colour is judged only against the grey key and the outline, so a red dress under a red cape passes every rule and then merges into one shape in the init, where no check can see it. Say so when two garments must read apart |
| a hex, for **grey or silver** | the trap. A neutral `#VVVVVV` loads only at `#000000`–`#040404`, `#3C3C3C`–`#646464` and `#FDFDFD`–`#FFFFFF`; `#C0C0C0` is refused because its ×0.7 shade `#868686` is 10.4 from the grey key, so the agent goes dark, near-white or off neutral (`#8C8CB4` loads) without asking |
| **tags** | it writes them from the garments and the colours |
| **anchor** | it picks from the tags, the only legal source: an anchor tag is a tag of `tags`, verbatim |
| **how far to go** | it writes the file, runs `render` and `plan`, and stops. Sending is a command a human types |

### The request

```text
Write tools/nai/characters/<name>.json.

who:      boy | girl
build:    standard | original | long  <or leave it out for standard>
outfit:   <in the garment slots above; "scout's" keeps the default>
colours:  <part> #RRGGBB, or colour words and I will look at what you pick
tags:     <the look, or "write them from the outfit">
anchor:   <what must survive every frame, or "pick from the tags">

Use only garments the mannequin already draws; if my description needs one it
does not, stop and tell me what that would cost instead of faking it with a
tag. Then render the walk init and plan walk, show me the init and the worst
recipe's word count, and stop. Do not run, infill or probe.
```

### Worked: the request behind `wizard_girl.json`

*"a girl in a wizard hat and a purple cape, a red dress and blue heels, blonde
hair."* Three things that sentence does not settle, and what was decided for
it — one of them against what was asked, for a reason worth reading:

- **the neck, and the parts.** A file that omits `neck` means a scarf and is
  refused for a missing `scarf` colour, so `"neck": "none"` had to be written
  out — a dress does not imply a bare neck, and a dress with a scarf loads
  fine. Those garments draw seven parts, so keeping scout's is refused too:
  *unused part(s) ['pants', 'tunic'] ... paint nobody ever sees*.
- **the hexes, and the hat's in particular.** Four colour words became
  `#E8C85A`, `#C83232`, `#1E5AF0` and `#8C3CC8`; `skin` and `belt` kept
  scout's. No hat colour was given, so it took the cape's purple — and then
  had to stop: sharing one purple made the check's *the cape is drawn*
  assertion vacuous, because the brim alone satisfied it and deleting the
  cape entirely left the check green. The hat is `#5A28A0`. Two shades that
  read as one purple to a human are still two colours to an assertion, and
  that is the only reason they differ.
- **the tags and the anchor.** Eight tags, three garments named **twice**
  (`wizard hat` / `purple headwear`, `purple cape` / `cape`, `high heels` /
  `blue footwear`), and an anchor of five — one per garment, the doubles
  dropped, which is what the budget below leaves room for.
  `scout_aqua_scarf.json` spells its scarf four ways for the same reason, and
  its commit records the clearest scarf yet on that seed: one observation on
  one seed, not a proven technique.

### Worked: `garet.json`, and the flaw it exists to fix

`garet` is the author's own character, drawn years ago in
`~Garet.png` and never quite liked: *"essentially the gunslinger archetype
with a trenchcoat and big hat, mouth covered by a mask sort of character"*,
and *"I never did like how short his legs were."* He is the example that
earns its space because he needed BOTH sides of this document — a data
file, and an afternoon across seven files — and because the complaint is
measurable.

**What the reference measures.** Side pose, 44x68 cell: the figure is 45 px
tall, hat crown to sole. The hat is 13 of those px and the brim alone is 30
px across — two thirds of the figure's height, overhanging a 17 px head by
6 at the back and 7 at the face. The coat hem falls 41 px down, at 93% of
the figure, and below it there are **3 px of boot: 6.7%**. That is the
whole complaint, in one number. The legs may or may not be short; the
silhouette has no way to say, because the coat covers everything a leg
could be.

**What was changed, and why it is two changes.** A hem raised to show leg
and nothing else is a tunic, so the coat and the hip both had to move:
`COAT_LEN` puts the hem 13 px below the hip, and `"build": "long"` puts the
hip 3 px higher. Together they draw 10–11 px of leg on the walk strip
against the reference's 3, while collar-to-hem still covers 52–67% of the
figure in every frame of every strip. `original` is in the vocabulary
because it reproduces the reference — 4–5 px — so the fix has something to
be a fix OF.

**The palette is read off the file and then moved — and the rule is a BAND,
not a floor.** Every identity colour keeps 48 from the near-black outline
`#202020`, which forbids a ring roughly 34 to 48 wide around it. A colour
may be lifted OUT of that ring or pushed THROUGH it, and which way you go
is a design decision, not the rule's. The reference's coat `#3F1508` sits
40.7 away and its mask `#0D0401` sits 45.9, so neither loads.

The coat went UP, to `#5A2814`: there is no dark brown on the far side, only
black, and a black coat is a different character. The mask went DOWN, to
`#0A0000` (50.3 away, and `#000000` at 55.4 loads too). **That direction is
the whole character.** In the reference the mask is the DARKEST thing on the
sprite by a wide margin — a black void under one blue eye — and the first
attempt here lifted it to `#4E4038`, luminance 67 against a coat at 53, so
the mask was LIGHTER than the coat it sat above. A warm mid-grey band three
rows deep, under a blonde fringe, on an 8 px head, is a BEARD; it read as
one at every zoom, in every frame of all three strips, and a model at
strength 0.55 would have read it the same way whatever the caption said.
The collar wears the same value for the same reason (see the garment table),
and together they are the reference's real signature after the hat.

The hat kept the reference's own brown family and was lifted to `#8C5A28`
so the brim reads lighter than the coat in silhouette. His shirt shows in
the strip the open coat leaves down the chest: it is `#4A3A2A`, a coat
lining in shadow, because the reference has **no green, no blue and no
saturated colour anywhere** — every one of the twenty commonest values in
its 4x4 art block is a brown, a black or a near-black, and the open front
of his coat is the same near-black as his mask. An earlier olive `#7A8C4B`
put the only saturated pixels on the figure and the words *olive shirt* in
the caption that drives img2img, which is the most likely place for a model
to grow a garment the author never drew.

**What is still open, and it is a question for the author.** The reference
carries a round blue disc, and the first description of it here — *"about
22 px across, behind his shoulder, in every frame"* — was wrong in both
halves. Measured, blue-pixel census over the whole 4x4 art block:

- it is **21 x 22 source px** — as wide as his entire body (23 px with its
  outline), centred on the TORSO, not on a shoulder;
- it is **a side-view element**. Drawn full in both side rows (LEFT col 0
  x 11..31 y 25..46; RIGHT col 0 x 11..31 y 21..42) and occluded to a
  sliver from the front and the back — the 8 blue px in the DOWN row's
  first cell are his EYES (`#ACD6FC`, `#144ABC`), not a disc at all;
- it is **shaded**: `#0054A6` on his left and the darker `#004A80` on his
  right. That is a lit object, not a flat marker.

So the question is which of three things it is: something round slung on his
back that he only ever bothered to draw in profile, an effect, or an
authoring guide — a body-volume or pivot marker left in the template. Those
three answers produce three completely different garment slots, so nothing
here draws it and nothing here guesses.

### The sequence, and what you are handed

Every refusal names the file and the field, so the agent's first few attempts
are a conversation with the loader, not with you. Then two commands, neither
of which opens a socket.

**Render, and LOOK at the init.**

```powershell
.venv/Scripts/python.exe -m tools.nai render walk --character wizard_girl
```

It writes `data/nai/renders/wizard_girl_walk_init.png` and prints the layout,
every frame's snapped center, a params sha256 and the PNG's sha256. Looking is
not optional: the init is a 40 px figure drawn at source scale before the ×8,
and a garment you cannot identify there, two colours that have merged, or a
figure straddling a cell are invisible to every rule in this file. An existing
render whose bytes differ is never overwritten (exit 1), and `render` has no
`--strip-version`, so after editing the JSON delete the old init or `--out`.

**Plan, for the captions and the budget.**

```powershell
.venv/Scripts/python.exe -m tools.nai plan walk --action generate --character wizard_girl --seed 1234567
```

It prints the base caption, every frame caption with its center, the request
sha256, and eleven guard conditions — 8 and 9 marked *needs the live account
read*, the rest judged; exit 0 means every offline condition passes. Condition
7 is the one a new character trips: 450 tokens at 1.5 per word, so **300
words** over the base caption plus every frame caption. The anchor is repeated
in all six `run` frames, so one anchor word costs **seven** words there (six in
`walk` and `jump`) against one for a word in `tags` alone. Measured, on `run`: scout 217,
`wizard_girl` 242, `scout_aqua_scarf` 246, `garet` 260. Add six two-word
tags to scout's anchor and `run` counts 301 — refused by name, for `walk`
too, before a mannequin is drawn.

`garet` is in that list, and so are `scout`, `scout_blue_scarf` and
`wizard_girl`.

**What comes back:** one tracked file, `tools/nai/characters/<name>.json`; an
untracked init under `data/nai/renders/`; the worst recipe's word count; and
every refusal the agent hit — not an argument that the file is right.

Treat those two commands as the only proof your file is legal, and do not
assume the suite is behind you: `tools/check_nai.py` names the characters it
tests by hand. Measure it before you rely on it —

```powershell
.venv/Scripts/python.exe -c "import re;print(sorted(set(re.findall(r'load\(\"([a-z0-9_]+)\"', open('tools/check_nai.py',encoding='utf-8').read()))))"
```

— and if your file's name is not in that list, nothing in the suite has ever
opened it. Stop the agent there: sending is *The loop*, below, one human
command at a time.

## The loop

Every generation is one command a human typed. Never script a sweep.

0. **`account`.** Continue only on tier 3, active, not in grace.
1. **Generate track.** Run `run walk --action generate` at 3–5 seeds, one
   command each. This proves the free class for the account. `pixelize` the
   best result.
2. **Probes.** Optional, and the author decides.
3. **img2img track**, only if a proof row exists.
   - Sweep the seed at the default strength **0.45** (noise 0.05) and keep the
     best seed.
   - Then A/B the strength inside **0.35–0.55**.
   - Then noise 0, 0.05 and 0.10.
   - Then prompt levers.
   - A consistency re-pass on an accepted strip uses `--from`, at most 2
     chained passes.

   The author's rule: *low for continuity, but not too low*. The tool
   refuses a strength outside the band.
4. **Repair.** If infill is proven, infill the one bad cell. Use 0.45 to stay
   close; use 1.0 only when the pose itself is wrong. Otherwise regenerate the
   whole strip at a new seed. Never mix seeds in one strip.
5. **Freeze and extend.** Keep the identity text, palette and grid from the
   accepted walk. Then make `run` and `jump` with `--palette`.
6. **Accept** only when `pixelize` validates **and** the author confirms all
   of these:
   - right figure count
   - every figure faces right
   - identity colours in every frame
   - poses read correctly
   - flat background
   - no text

Between rounds:
- Change **one** lever and name it with `--lever`.
- Hold the seed fixed unless the round is a seed round.
- A winning lever becomes the new baseline.
- Stop a strip after 12 rounds without acceptance and fix the mannequin
  instead of prompting harder.

## Where files go

Everything lives under `data/nai/` in the **main** checkout, which is
gitignored. A git worktree of this repository (such as one under
`.claude/worktrees/`) resolves the same directory through git's metadata, so
every worktree sees the one `LOCK`, `INFLIGHT` and ledger. A separate clone
cannot be found that way and keeps its own: send from one checkout only.

| path | holds |
|---|---|
| `ledger.jsonl` | append-only, one row per attempt |
| `proofs.json` | the proof rows |
| `LOCK`, `INFLIGHT` | refusal markers: `LOCK` only when the author places it by hand; `INFLIGHT` while a send is in the air, or after one lost its row |
| `blobs/` | requests and responses by sha256 |
| `renders/` | mannequin renders, `<character>_<recipe>_init.png` |
| `sprites/<character>/<recipe>/` | strips, frames, sidecars and palettes |

Inside a checkout, the CLI writes only under `data/nai/`: `data/art/`,
`data/maps/`, `data/reference/` and `tools/` are all refused, so no command
can overwrite or stage a tracked file. A path outside the repository is the
author's own. Promoting a sprite to `data/art/` is the author's call, made by
hand after reading NovelAI's terms (R23).

## Baseline sprites

`data/reference/sprites/` holds three CC0 OpenGameArt sheets: pose and
proportion reference and a pixel-scale baseline, committed but never loaded by
the game. Creators, licences, hashes and frame tables:
[`data/reference/sprites/CREDITS.md`](../data/reference/sprites/CREDITS.md).

- **MV Platformer Male**, MoikMellah: 32×64, human proportions. Use it for the
  mannequin's limb lengths.
- **Knight Hero**, PixiVan: 22×24 chibi. Use it for frame counts: walk 6,
  run 6, jump 4, fall 4. Its grey armour makes it a poor init.
- **Classic Hero**, GrafxKid: 16×16. It is the only sheet here with a land pose.

## Open risks an author will meet

| id | risk | what settles it |
|---|---|---|
| R1, R2 | img2img or infill is charged | their probes |
| R3 | generate is charged on this account | the first generate: delta 0, and the next call's chain check matches |
| R4 | the debit arrives late | a fall in the read that FOLLOWS one of our own sent rows refutes that pair's proof FOR GOOD, and no signature restores it; the boundary itself is reported AMBIGUOUS, never as somebody else's |
| R7, R8 | positions are only a nudge, or the figure count is wrong | the figures land in their cells, at N figures for at least 3 of 5 seeds |
| R10 | the same request gives a different image | send it twice and compare the output hashes |
| R13, R14 | no clean 8 px grid, or the grey does not key | `pixelize` validation |
| R19, R20 | the site changes its rules, or withdraws V4.5 | a new 400 or an unexpected delta: stop and re-read. Never fall back to V5 |
| R22 | long captions get cut silently | late frames lose their pose words |
| R23 | NovelAI's terms for committing generated sprites | an author decision before anything leaves `data/nai/` |

Balances compare the **sum** of subscription and paid Anlas, so NovelAI's
planned conversion of one into the other reads as no change.
