<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written 2026-09-17 from the tools/nai contract docstrings and the NovelAI research brief; no command here has been run against NovelAI yet, so every cost claim says in place whether it is proven, and the baseline sprites were measured by the commands in their CREDITS.md. -->

# NovelAI sprites — side-scroller strips on the Opus free tier

Questions that land here:

- *"how do I generate sprites with NovelAI"*
- *"how do I run img2img or inpainting"*
- *"is this generation free"*
- *"how do I ask an agent for a new character"*
- *"is this outfit a data file or mannequin code"*
- *"where do the reference sprites come from"*

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
- a balance below the last ledger row's (a refill above it is recorded), or
  any UNSIGNED drop between two ledger rows (see *The books*), and any
  `LOCK` or `INFLIGHT` file
- an empty ledger beside `blobs/` or `proofs.json`: the ledger was lost, and
  the balance chain cannot safely start over

A balance **decrease** writes `LOCK`, and from then on the tool refuses
everything until the author deletes `LOCK` by hand. So does a request
**interrupted** after it was sent (Ctrl-C): the balance is still read and the
row still written, but whether it was charged is unknown. Nothing is retried
automatically: not a 429, not a 5xx, not a timeout.

## The books

**A shared account drifts.** If anyone else generates on the same NovelAI
login, the balance falls while this tool is doing nothing, and the tool WILL
see it. It is never guessed at and never quietly absorbed, because a balance
can fall in two places and they are not the same measurement:

| where the fall is | what it means | what happens |
|---|---|---|
| **inside one of our rows** — that row's own `account_after` below its own `account_before` | our request is the only thing between those two reads, so **the charge is ours** | `LOCK`, everything refused until the author deletes it by hand, and that action's proof refuted **for good**. No signature can absorb, clear or excuse it. |
| **between two rows** — one row's `account_after`, then the next row's `account_before`, lower | no row of ours lies between those two reads. That is **not** the same as "nothing of ours was charged": see the boundary table below | refused the first time it is seen (condition 9, `LOCK`), printing both balances, the delta, the window, and the command that signs it. It stays refused until the author signs it. |

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

Two things a signature never does. It **never deletes `LOCK`**: one that could
would be able to clear the `LOCK` a real charge wrote. And it **never restores
a proof** — `guard.proof_standing` reads no signature at all, so signing the
boundary that refuted img2img frees the chain so the generate track can go on
and leaves img2img refused. The one way back is to remove the proof from
`proofs.json` by hand and probe again, paying that probe knowingly.

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
- The proof counts only once the **next** balance read still shows the
  probe's balance. A read **above** it (a refill, which can hide a charge)
  refutes it for good: re-measuring then means the author removes that proof
  from `proofs.json` by hand and probes again.
- A read **below** it refutes it **for good** as well. The probe's own
  request went out, so a debit the server applied after the probe's
  after-read (R4) lands exactly there and is byte-identical to somebody
  else's spend; the unsafe reading is the one that counts. Signing that
  boundary re-baselines the chain and leaves the proof refuted.
- A **later** img2img or infill call of that model charged **inside its own
  row**, or one whose after-read failed, refutes the proof for good in the
  same way, so deleting that `LOCK` does not send another charged call. So
  does a fall in the read that **follows** such a call, for the R4 reason
  above.
- If it is charged, the client formula puts the worst case at 2 Anlas, and the
  tool writes `LOCK`.

Run the generate track first. Then probe img2img and infill separately, one
decision each. **Only the author types `--accept-max-2-anlas`, spelled out in
full: no abbreviation of any option is accepted. An agent never passes it and
never deletes `LOCK`.**

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
ok, 1 error, 2 refused, 3 strip rejected. Only `run`, `infill` and `probe` send,
at most once each, printing the ledger id, both balances and the delta. With no
`--seed`, the chosen seed is printed before sending.

| command | network | example |
|---|---|---|
| `account` | reads the balance only; writes nothing | `account` |
| `render` | none | `render walk` writes `data/nai/renders/scout_walk_init.png` |
| `plan` | none: a dry run that prints the request and every offline guard verdict | `plan walk --action img2img --seed 1234567` |
| `run` | one generate or img2img | `run walk --action generate --seed 1234567 --round 1 --lever seed` |
| `infill` | one infill of one cell | `infill walk --cell 2 --from data/nai/blobs/<sha256>.png` |
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
  tag and no quality-tail tag (`very aesthetic`, `masterpiece`, `no text`),
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

Two optional fields say **who** is drawn and **what she wears**. A file that
writes neither is a boy in scout's outfit, which is why every file written
before them still loads:

- `"subject"`: `"boy"` (the default) or `"girl"`. It writes the one count tag
  at the head of the base caption (`1boy`, `1girl`), the first word of every
  frame caption, and each recipe sentence's *the same boy* / *the same girl*.
  A tag naming the other subject is then refused — `male` or `man` in a girl
  file, `woman` or `female` in a boy one — as whole words, so `boyish` names
  nobody.
- `"garments"`: `"hat"` `none`|`wizard`, `"cape"` `false`|`true`, `"neck"`
  `scarf`|`none`, `"legwear"` `pants`|`dress`, `"footwear"` `boots`|`heels`.
  Each key may be left out and then means the choice named first. The
  mannequin draws them at source scale, and `colours` must name **exactly**
  the parts they draw: `skin`, `hair` and `belt` always, `scarf` for a scarf
  neck, `tunic` and `pants` for pants, `dress` for a dress, `boots` or
  `heels` for the footwear, `cape` for a cape, `hat` for a wizard hat. A
  colour for a part these garments never draw is refused as an unused part,
  exactly as a missing one is refused as missing.

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
| any outfit the five garment slots above can spell, in any legal colours, for either subject — 32 outfits × 2 subjects, drawing 5 to 9 colour parts | **one JSON file.** `scout_aqua_scarf.json` landed as a commit of 13 added lines and no code at all |
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
| **garments** | scout's: no hat, no cape, a scarf, pants, boots. Whatever you pick, `skin`, `hair` and `belt` are drawn, so even a dress file carries a belt colour the agent chose |
| **colours** | it picks a hex from your colour word — "blue" is `#46A5E6` in `scout_blue_scarf` and `#3CC8C8` in `scout_aqua_scarf` — and **nothing compares one of your colours to another**. Every colour is judged only against the grey key and the outline, so a red dress under a red cape passes every rule and then merges into one shape in the init, where no check can see it. Say so when two garments must read apart |
| a hex, for **grey or silver** | the trap. A neutral `#VVVVVV` loads only at `#000000`–`#040404`, `#3C3C3C`–`#646464` and `#FDFDFD`–`#FFFFFF`; `#C0C0C0` is refused because its ×0.7 shade `#868686` is 10.4 from the grey key, so the agent goes dark, near-white or off neutral (`#8C8CB4` loads) without asking |
| **tags** | it writes them from the garments and the colours |
| **anchor** | it picks from the tags, the only legal source: an anchor tag is a tag of `tags`, verbatim |
| **how far to go** | it writes the file, runs `render` and `plan`, and stops. Sending is a command a human types |

### The request

```text
Write tools/nai/characters/<name>.json.

who:      boy | girl
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
`walk` and `jump`) against one for a word in `tags` alone. Measured: scout 217,
`wizard_girl` 242, `scout_aqua_scarf` 246. Add six two-word tags to scout's
anchor and `run` counts 301 — refused by name, for `walk` too, before a
mannequin is drawn.

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
| `LOCK`, `INFLIGHT` | refusal markers |
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
