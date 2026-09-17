<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written 2026-09-17 from the tools/nai contract docstrings and the NovelAI research brief; no command here has been run against NovelAI yet, so every cost claim says in place whether it is proven, and the baseline sprites were measured by the commands in their CREDITS.md. -->

# NovelAI sprites — side-scroller strips on the Opus free tier

Questions that land here:

- *"how do I generate sprites with NovelAI"*
- *"how do I run img2img or inpainting"*
- *"is this generation free"*

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
- a balance below the last ledger row's (a refill above it is recorded), and
  any `LOCK` or `INFLIGHT` file
- an empty ledger beside `blobs/` or `proofs.json`: the ledger was lost, and
  the balance chain cannot safely start over

A balance **decrease** writes `LOCK`, and from then on the tool refuses
everything until the author deletes `LOCK` by hand. So does a request
**interrupted** after it was sent (Ctrl-C): the balance is still read and the
row still written, but whether it was charged is unknown. Nothing is retried
automatically: not a 429, not a 5xx, not a timeout.

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
  probe's balance. A debit that lands late refutes it for good: the next
  command writes `LOCK` and names the probe, and img2img or infill stays
  refused after `LOCK` is deleted. Re-measuring means the author removes that
  proof from `proofs.json` by hand and probes again.
- A **later** img2img or infill call of that model that is charged -- across
  the call, or by a debit that lands before the next read -- refutes the
  proof for good in the same way, so deleting that `LOCK` does not send
  another charged call.
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
| `render` | none | `render walk` writes `data/nai/renders/walk_init.png` |
| `plan` | none: a dry run that prints the request and every offline guard verdict | `plan walk --action img2img --seed 1234567` |
| `run` | one generate or img2img | `run walk --action generate --seed 1234567 --round 1 --lever seed` |
| `infill` | one infill of one cell | `infill walk --cell 2 --from data/nai/blobs/<sha256>.png` |
| `probe` | none without the flag, which prints the worst case | `probe img2img` |
| `pixelize` | none | `pixelize data/nai/blobs/<sha256>.png --recipe walk` |
| `ledger` | none | `ledger --last 5` |

`infill --from` takes the full 1216×832 image that `run` returned, not the
pixelized strip; RGB or opaque RGBA is accepted, real transparency is refused.
`plan` and `run` take the same `--from` for **img2img** only: a consistency
re-pass on an accepted strip instead of the mannequin init. The ledger's
`init_png_sha256` names what was sent, so a chain of passes is visible; stop
after 2 chained passes and go back to the mannequin. For later strips, give
`pixelize` the walk's reference palette with `--palette`. `render` and
`pixelize` never overwrite a file whose bytes differ.

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
| `renders/` | mannequin renders |
| `sprites/<recipe>/` | strips, frames, sidecars and palettes |

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
| R4 | the debit arrives late | the chain check across the first five calls |
| R7, R8 | positions are only a nudge, or the figure count is wrong | the figures land in their cells, at N figures for at least 3 of 5 seeds |
| R10 | the same request gives a different image | send it twice and compare the output hashes |
| R13, R14 | no clean 8 px grid, or the grey does not key | `pixelize` validation |
| R19, R20 | the site changes its rules, or withdraws V4.5 | a new 400 or an unexpected delta: stop and re-read. Never fall back to V5 |
| R22 | long captions get cut silently | late frames lose their pose words |
| R23 | NovelAI's terms for committing generated sprites | an author decision before anything leaves `data/nai/` |

Balances compare the **sum** of subscription and paid Anlas, so NovelAI's
planned conversion of one into the other reads as no change.
