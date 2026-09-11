# Event script ops -- the vocabulary a script may spell

**This file is generated.** `scripts/game/flow/ops.py` holds the table. Edit the specs, not this file.

10 op(s) in 1 loadout(s): `core`.

## The protocol

A script is `data/project/scripts/<id>.json`. It declares which loadouts it uses; every op it spells must belong to one of them, and the check is at LOAD, never at execution.

```json
{"format": "pyoneer.script", "version": 1, "id": "keeper_gate",
 "loadouts": ["core"],
 "pages": [{"id": "pg", "trigger": "use", "when": [],
            "body": [{"id": "n1", "do": "say", "text": "Hello."}]}]}
```

A node is one of exactly two shapes: executable `{"id", "do", ...arguments}`, or control `{"id", "if"|"while", "then", "elif", "else"}`. Any node may carry a `note`. Nothing else parses, and an unknown key raises naming its path.

## The registry

| op | loadout | arguments | yields | status | summary |
| --- | --- | --- | --- | --- | --- |
| `ask` | `core` | `prompt`, `into`, `options` | yes | needs-host | Offer a choice and write the chosen index into a variable. |
| `call` | `core` | `script` | no | live | Run another script's first passing page here, then carry on. |
| `hold` | `core` | `steerable`, `enabled_inputs`, `simulated` | no | live | Take the bodies' agency, recording what to give back. |
| `play_music` | `core` | `track`, `loops`, `volume` | no | live | Start the background track. Starts a stream; never waits for it. |
| `play_sound` | `core` | `sound`, `volume` | no | live | Play one sound effect and carry on in the same frame. |
| `release` | `core` | -- | no | live | Give back exactly the agency `hold` recorded. Never `true`. |
| `say` | `core` | `text`, `who` | yes | live | Show a line and wait for the advance. |
| `set` | `core` | `var`, `by`, `to` | no | live | Write a declared variable, by assignment or by addition. |
| `stop` | `core` | -- | no | live | End the run from inside any arm, releasing anything held. |
| `wait` | `core` | `ms` | yes | live | Hold this node for a number of milliseconds. |

### `ask`

Offer a choice and write the chosen index into a variable.

> **Status: needs-host.** It is registered, authorable and documented, and something outside the engine has to exist before it can do its job.

- **loadout** `core`
- **yields** yes -- it can stop the frame and resume on the next

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `prompt` | str | `''` | yes | The question. |
| `into` | str | `''` | yes | The int variable the chosen INDEX is written to. |
| `options` | a list of at least two non-empty strings | -- | yes | What the player may pick. The INDEX of the pick is written to `into`, so inserting an option renumbers every branch after it. |

```json
{"id": "n8", "do": "ask", "prompt": "Half now?", "options": ["Pay half", "Walk away"], "into": "keeper_pick"}
```

### `call`

Run another script's first passing page here, then carry on.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `script` | str | `''` | yes | The id of the script to run, which is also its file stem. |

```json
{"id": "n5", "do": "call", "script": "shop_intro"}
```

### `hold`

Take the bodies' agency, recording what to give back.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `steerable` | bool | *(tri-state: absent or null means do not touch)* | no | false stops the body walking. The gate is on the producer, so a side-on body still falls. |
| `enabled_inputs` | bool | *(tri-state: absent or null means do not touch)* | no | false silences the action behaviors too -- clearing this AND steerable is how a dialogue locks itself out of its own continue button. |
| `simulated` | bool | *(tri-state: absent or null means do not touch)* | no | false stops a GamePlayer completely, animation clock included. Per entity; there is no world pause. |

```json
{"id": "n2", "do": "hold", "steerable": false}
```

### `play_music`

Start the background track. Starts a stream; never waits for it.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `track` | str | `''` | yes | The track's name, relative to the audio roots -- "music/pleasant_moments.ogg". Ogg streams rather than decoding whole into memory. |
| `loops` | int | `0` | no | -1 repeats forever, 0 plays it once, n repeats it n more times. |
| `volume` | float | `1.0` | no | 0.0 to 1.0, scaled by master_volume in config/audio.json. |

```json
{"id": "n1", "do": "play_music", "track": "music/pleasant_moments.ogg", "loops": -1}
```

### `play_sound`

Play one sound effect and carry on in the same frame.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `sound` | str | `''` | yes | The sound's name, relative to the audio roots -- "sfx/chime.wav". data/sound/ is looked at first, then the shipped data/audio/. |
| `volume` | float | `1.0` | no | 0.0 to 1.0, scaled by master_volume in config/audio.json. |

```json
{"id": "n7", "do": "play_sound", "sound": "sfx/chime.wav"}
```

### `release`

Give back exactly the agency `hold` recorded. Never `true`.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

Takes no arguments.

```json
{"id": "n15", "do": "release"}
```

### `say`

Show a line and wait for the advance.

- **loadout** `core`
- **yields** yes -- it can stop the frame and resume on the next

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `text` | str | `''` | yes | The line. |
| `who` | str | `''` | no | Who is speaking. Empty is narration. |

```json
{"id": "n3", "do": "say", "who": "Keeper", "text": "The north gate is sealed."}
```

### `set`

Write a declared variable, by assignment or by addition.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `var` | str | `''` | yes | The variable to write. Bare means the `scene.` namespace. |
| `by` | str | `'assign'` | no | assign replaces; add is arithmetic and needs a numeric variable. |
| `to` | whatever type the variable named by `var` was declared with | -- | yes | The value. With by="assign" it replaces; with by="add" it is added, so -100 is how a purchase is written. |

```json
{"id": "n6", "do": "set", "var": "coins", "to": -100, "by": "add"}
```

### `stop`

End the run from inside any arm, releasing anything held.

- **loadout** `core`
- **yields** no -- it completes in the frame it is entered

Takes no arguments.

```json
{"id": "n13", "do": "stop"}
```

### `wait`

Hold this node for a number of milliseconds.

- **loadout** `core`
- **yields** yes -- it can stop the frame and resume on the next

| argument | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `ms` | float | `0.0` | yes | Milliseconds, matching cooldown_ms and lifetime_ms everywhere else. Must be above zero. |

```json
{"id": "n14", "do": "wait", "ms": 250}
```

<!-- Everything above this line is `describe_all()` in scripts/game/flow/ops.py. Everything below is MEASURED by tools/check_event_docs.py -- every row is produced by running something, never by reading a flag. Regenerate the whole file with:  .venv/Scripts/python.exe tools/check_event_docs.py --write  -->

## Measured runtime

Every row below is produced by constructing a `ScriptRun` over a one-node script and stepping it, then observing the effect. A row that says *no* is an op that does not do its job at this commit -- not one that is merely undocumented.

9 of 10 op(s) run.

| op | loadout | status | runtime | what was observed |
| --- | --- | --- | --- | --- |
| `ask` | `core` | needs-host | no | raises: `ask` needs a host that reports a CHOICE, and this engine has none -- no widget reports  |
| `call` | `core` | live | **yes** | runs the called script's body |
| `hold` | `core` | live | **yes** | clears the axis on a real BodyState, and keeps holding it |
| `play_music` | `core` | live | **yes** | starts the stream and finishes in the same frame |
| `play_sound` | `core` | live | **yes** | finds the file and starts it, finishing in the same frame |
| `release` | `core` | live | **yes** | gives back the RECORDED value mid-run -- an already-held body stays held |
| `say` | `core` | live | **yes** | opens a duck-typed host's line, waits for the advance, closes it |
| `set` | `core` | live | **yes** | writes the variable store |
| `stop` | `core` | live | **yes** | ends the run; nothing after it runs |
| `wait` | `core` | live | **yes** | elapses on the frame it is due and not before |

## Reachability

Each row is measured from the parse tree of the tree above this layer, not from a flag. A capability that is registered, documented and checked while nothing above it can reach one is this repository's signature defect; this table is the instrument against it.

| the wire | at this commit | what it takes |
| --- | --- | --- |
| an op registry exists and is populated | **yes** | 10 op(s) in `core` |
| a genre pack GRANTS a loadout (`event_loadouts`) | **yes** | one array in a pack's `genre.json`, validated through `ops.validate_loadouts`. granted by platformer, topdown_rpg |
| an editor module reaches the op registry (the PICKER) | **yes** | reached by `editor/core/event_script.py`, `editor/core/genre.py`, `editor/core/verbs.py`, `editor/ui/script_editor.py` |
| a script document is read from disk in production | **yes** | read in `main.py` |
| a `ScriptRun` is constructed outside the checks | **yes** | constructed in `main.py` |
| a script document exists under `data/project/scripts` | **yes** | 1 file(s): starter_greeting.json |

## The loadouts

A loadout exists because an op declares it; there is no separate list. A document names the loadouts it uses at its head, every op it spells must belong to one of them, and both checks happen at LOAD.

| loadout | ops |
| --- | --- |
| `core` | `ask`, `call`, `hold`, `play_music`, `play_sound`, `release`, `say`, `set`, `stop`, `wait` |
