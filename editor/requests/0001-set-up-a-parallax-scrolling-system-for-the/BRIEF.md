# Request 0001-set-up-a-parallax-scrolling-system-for-the

You are extending a game built on the Pyoneer engine. The human author has
left notes on specific parts of the project; your job is to carry them out.

**Read in this order:**

| file | what it is |
|---|---|
| `RULES.md` | the genre's conventions. Non-negotiable. |
| `CONTEXT.md` | the current state of everything the notes touch. |
| `REQUEST.md` | the notes themselves, grouped by what they are about. |
| `COMMANDS.md` | the exact vocabulary for changing project data. |

**Project:** `S:\Dropbox\Pyoneer`
**Genre:** `platformer` -- 2D side-scrolling platformer

## How to answer

Write `response.jsonl` in this directory: one JSON object per line, no
wrapping array, no trailing commas. Each line is a command from
`COMMANDS.md`.

```
{"verb": "table.row.add", "scope": "table:actors", "args": {"id": "hero", "values": {"hp": 30}}}
{"verb": "map.object.add", "scope": "map:test/layer:entity", "args": {"type": "PlayerStart", "x": 64, "y": 64}}
```

The editor validates every line before applying any of them. Unknown verb,
unknown argument, missing argument, or wrong argument type rejects the
**whole response** -- so nothing is ever half-applied, and a typo costs you
a retry rather than costing the author a corrupted project.

Types are checked and never coerced. `"30"` is not `30`.

## When data commands are not enough

Some requests need real engine code -- a new movement rule, a new component,
a new system. Then:

1. Do the data part with commands as above, and
2. edit the source directly. `REQUEST.md` lists the files each note is
   likely to touch, and `RULES.md` states what must not change.
3. Write `NOTES.md` in this directory explaining what you changed and
   why. The author reads it as the review summary.

Run `.venv/Scripts/python.exe tools/check_all.py` before you finish. If a
smoke field moves, say which one and why in `NOTES.md`. Do not
re-baseline something you cannot explain.

## What not to do

- Do not invent verbs. If the vocabulary cannot express something, say so in
  `NOTES.md` and do that part as a code change instead.
- Do not edit `.tmx` files as text. They round-trip byte-exactly through
  `MapDocument`, and a hand-edit destroys that.
- Do not restructure the event system. It is the one thing the whole engine
  rests on; `RULES.md` says what that means concretely.
