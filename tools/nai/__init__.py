"""NovelAI V4.5 side-scroller sprite pipeline, on the Opus free tier only.

WHAT IT DOES
------------
Turns a recipe (walk, run, jump) for a character (a data file under
tools/nai/characters/, default scout) into sprite strips: it draws a
grey-keyed mannequin init at source scale, builds ONE NovelAI image request
from it
(generate, img2img or infill), sends that request only after a guard has
proved it belongs to the free class, records the balance before and after in
an append-only ledger, and post-processes the returned image into real pixel
art (one grid size, one palette, block-mode downscale, keyed background,
baseline-aligned frames, a sidecar JSON).

    .venv/Scripts/python.exe -m tools.nai account
    .venv/Scripts/python.exe -m tools.nai render <recipe> [--character NAME] [--out PNG]
    .venv/Scripts/python.exe -m tools.nai plan <recipe> --action generate|img2img [--character NAME] [--seed N] [--strength S] [--noise N]
    .venv/Scripts/python.exe -m tools.nai run <recipe> --action generate|img2img [--character NAME] [--seed N] [--strength S] [--noise N] [--from PNG]
    .venv/Scripts/python.exe -m tools.nai infill <recipe> --cell N --from PNG [--character NAME] [--strength S]
    .venv/Scripts/python.exe -m tools.nai probe img2img|infill --accept-max-2-anlas
    .venv/Scripts/python.exe -m tools.nai pixelize PNG --recipe R [--character NAME] [--palette PNG]
    .venv/Scripts/python.exe -m tools.nai ledger [--last N]

`plan`, `render`, `pixelize` and `ledger` never touch the network. `account`
reads the balance and sends nothing. `run`, `infill` and `probe` send exactly
one generation request each and print the ledger id, the balance before and
after, and the delta.

THE FREE-TIER PROMISE
---------------------
No request leaves this package unless `guard.assert_free` passes, and
`run.run_request` is the only function that calls a transport's `post_json`.
Only `nai-diffusion-4-5-*` models, at most 1,048,576 pixels, at most 28
steps, one sample, no references or vibes, on an active Opus (tier 3)
account. img2img and infill are refused until a probe -- run only when the
author types `--accept-max-2-anlas` himself, in full -- has returned an image
at a zero delta for that (action, model), AND the next balance read has
confirmed it; any later charged call of that pair refutes the proof for good.
Any balance decrease, and any request interrupted after it was sent, writes
`LOCK`, and the tool then refuses everything until the author deletes `LOCK`
by hand. An agent never passes the probe flag and never deletes `LOCK`.

ONE REQUEST PER HUMAN COMMAND
-----------------------------
Every generation is initiated by a human typing a command: one command, at
most one POST to `/ai/generate-image`. There are no loops, batches, sweeps,
schedules or retries -- not on 429, not on 5xx, not on timeout. A second
`run_request` in the same process is refused, and an `INFLIGHT` file refuses
a second process.

WHERE STATE LIVES
-----------------
Under `data/nai/` in the MAIN checkout of the repository, which is gitignored
and must stay so; every git worktree of it resolves the same directory
(`state.default_root`), so one LOCK guards the account:

    data/nai/ledger.jsonl    append-only, one row per attempt, plus a `drift`
                             row per SIGNED boundary -- one the author
                             acknowledged as external, or resolved by hand
                             (model.LEDGER_FIELDS, model.ROW_KINDS)
    data/nai/proofs.json     the (action, model) pairs measured free
    data/nai/LOCK            present = refuse everything (author deletes it)
    data/nai/INFLIGHT        present = a request is in flight (or crashed)
    data/nai/blobs/          <sha256>.png | .zip | .json, content-addressed
    data/nai/renders/        mannequin inits written by `render`, <character>_<recipe>_init.png
    data/nai/sprites/        pixelized strips, frames and sidecars, <character>/<recipe>/<sha12>/

Inside a checkout nothing is written outside `data/nai/` -- not `data/art/`
(tracked; promoting a sprite there is the author's decision), not
`data/maps/`, `data/reference/` or `tools/`. The key is read from the NAI_KEY user environment variable, inside
`transport.api_key`, at send time, and is never logged, stored, echoed or put
in a URL; no ledger row, blob or message may carry it or the Authorization
header.

The module map, owners and cross-module contract are in each module's
docstring; `model` is the shared vocabulary and imports nothing else here.
"""
