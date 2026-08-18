<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every item below was re-measured against d8c303f on 2026-08-16 by the command printed beside it. The genre-pack default behavior list shipped afterwards and left this list; see CLAUDE.md's Known gaps. -->

# Next — what is open, ranked, and the command that measured it

## Why this file is one screen long

The previous version of this file was a ranked list written against `ce66ce5`.
By the time it was next read, four of its items had shipped — and it still sat
at the address a reader is routed to for *"what should I do next"*. It is now
[`history/NEXT_ce66ce5.md`](history/NEXT_ce66ce5.md), and it is the local proof
of the failure this format exists to prevent: **a plan that describes finished
work reads as an instruction, and the work gets done a second time.** Five
refactors in this repository were attempted as new sibling files and all five
died; every refactor written into the incumbent class landed. A stale plan is
how a reader chooses the sibling.

So, two rules, and they are what make this file cheap enough to keep true:

1. **An entry carries the command that produced it, and the commit.** If you
   are acting on an entry, run the command first. An entry whose command you
   have not run is a claim, not a fact.
2. **The inventory is not here.** [`../CLAUDE.md`](../CLAUDE.md)'s *Known gaps*
   says what each hole *is*; this file says only what order to fill them in and
   what each one costs. Copying the descriptions down here would create the
   second home that goes stale first.

## Before you read the list: three commands that answer it without prose

    .venv/Scripts/python.exe tools/check_all.py          what is broken now
    .venv/Scripts/python.exe tools/smoke.py --frames 60  whether the frame moved
    grep -n "| \`" docs/BEHAVIORS.md                     what is actually wired

The third one is the one people skip. [`BEHAVIORS.md`](BEHAVIORS.md)'s
integration column is *measured* — it builds a real entity and runs frames — so
it outranks every sentence of prose in this tree, including this one. Measured
at `d8c303f`: every registered token reports `live`, so "the behavior is not
wired" is no longer a true answer to anything.

## The list

Ranked by *cost of being wrong × cheapness of the fix*, not by size.

**1. `README.md`'s "Known rough edges" states three shipped subsystems as
missing.** It is the front door, and it is the only document here that a person
reads before they have any reason to distrust it.
Cost: a reader concludes the engine cannot do things it does, and writes them
again. Measured: `grep -n "cannot read a collision mask" README.md` and the two
bullets after it name the object-spawn path and the `.blitmap` reader, all
three of which exist — `#TAG:scripts/core/spawn.py`,
`#TAG:scripts/loaders/blitmap.py`.

**2. `docs/BEHAVIORS.md`'s preamble declares an unregistered behavior token.**
The document is generated, so it matches its generator; the token is in the
generator's *hand-written* preamble, which is the one part generation does not
protect. Cost: a `.tmx` written from the example raises at load.
Measured: `grep -rn "tile_collision" scripts/game/behavior/` — three sites, all
prose. `tools/check_docs.py` pins the string so it cannot get worse, and the
pin must be deleted in the same change that fixes it.

**3. Ten behavior parameters declare `source="actors"` and nothing reads the
table.** Step 2 of the parameter chain — the actors row — can never fire, so a
`hp` or `move_speed` column in `data/project/tables/actors.json` reaches no
entity. Cost: a parameter that looks authored and is silently the default.
Measured: `grep -rn 'source="actors"' scripts/ | wc -l` → 10, against
`grep -rn "tables/" scripts/ --include=*.py` → one comment and no reader.

**4. Four `GameEventType` members are not named anywhere in `scripts/` outside
their own definition.** `POST_DISPOSE`, `PARENT_RESIZED`, `QUIT` and
`WINDOW_FOCUS_GAINED`. Cost: an event member with no listener is an API promise
the engine does not keep, and `USE` is the standing proof of what that costs.
Do not add a member before a listener exists; delete or wire these.
Anchor: `#TAG:post_dispose_unwired`. Measured by walking `scripts/` for each
member name and counting references outside `scripts/core/event_types.py`.

**5. The two silent-failure sites, in the order they will bite.**
Both are described in `CLAUDE.md`'s *Known gaps*; the ranking is the addition:
`#TAG:GameAnimationHandler.__init__` starts a sequence before any behavior
attaches, so a side-on-only or portrait-only sprite sheet raises inside the
entity constructor — that is the *first* wall a new art set hits, and it hits
before anything else in this list matters. `#TAG:GameEntity.allowed_move`
returns an unrecognised direction's vector unclamped, which is harmless only
while `move_direction` is its sole caller — so it becomes urgent the moment a
second caller exists, and not before.

## What is NOT on this list, and why

- **Anything the suite already covers.** `tools/check_all.py` is the work list
  for defects; this file is for holes, which are different — a hole has no
  failing assertion because nothing asserts it yet.
- **Anything in [`history/`](history/).** Those documents were true when
  written. If one of them names work you think is open, re-measure it before
  believing it; that is what filing them there means.
