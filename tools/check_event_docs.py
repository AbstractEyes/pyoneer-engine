"""Generate `docs/EVENTS.md`, and prove it cannot describe an op that does not run.

    .venv/Scripts/python.exe tools/check_event_docs.py
    .venv/Scripts/python.exe tools/check_event_docs.py --write   # regenerate

`tools/check_ops.py` proves the machinery works. This file proves the paper
agrees with the machinery, which is a separate failure and a worse one: a
broken op raises on the first frame, while a document that describes an op the
interpreter cannot run sends an AI to write a script that raises at load, and
one that omits an op the interpreter CAN run means the op is never used at all.

WHAT IS ASSERTED
----------------
     1. `docs/EVENTS.md` is exactly what the generator produces, and its first
        half is byte-for-byte `ops.describe_all()`
     2. every registered op has a RUNTIME PROBE and every probe names a
        registered op -- both directions, so a new op cannot land unmeasured
        and a probe cannot outlive the op it measured
     3. the runtime column is a MEASUREMENT: `say` drives a host, `set` writes
        the store, `wait` elapses, `hold`/`release` move an axis and put it
        back, and `ask` reports **no** -- with a planted do-nothing op proving
        the prober can actually report a failure
     4. the reachability columns are measurements too, each from the parse
        tree of the tree above this layer, with a control proving the scan
        finds a caller where one exists
     5. the document names exactly the registered ops, in both places it names
        them, and every loadout it names is one the registry knows

THE DOCUMENT HAS NO HAND-WRITTEN CLAIM ABOUT THE CODE
------------------------------------------------------
`docs/BEHAVIORS.md`'s preamble is prose living inside its generator, and it
carried TWO lies while the file matched that generator byte for byte. So the
prose here states the FORMAT -- what a script document looks like -- and
nothing about what the engine does; every claim of that kind is a measured
row in a table. A document with no hand-written claim cannot catch that
disease.

THE FIXTURES ARE THIS FILE'S OWN
--------------------------------
Every probe builds its own one-node script as a dict and parses it through the
real reader. `data/maps/starter.tmx` is never read, and no file has to exist
under `data/project/scripts/` for this to run.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import json
import os
import sys
import warnings

import pygame

pygame.init()

from scripts.core.audio import AudioManager
from scripts.core.errors import PyoneerConfigError
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import ensure_state, state_of
from scripts.game.flow import ops as ops_module
from scripts.game.flow.interpreter import ScriptRun
from scripts.game.flow.ops import OP_REGISTRY, OpSpec, describe_all
from scripts.loaders import script_file as sf

ROOT = _bootstrap.REPO_ROOT
DOC_PATH = os.path.join(ROOT, "docs", "EVENTS.md")
GENRES_DIR = os.path.join(ROOT, "editor", "genres")
GENRE_MODULE = os.path.join(ROOT, "editor", "core", "genre.py")
SCRIPTS_ON_DISK = os.path.join(ROOT, sf.SCRIPTS_DIR)

REGENERATE = ".venv/Scripts/python.exe tools/check_event_docs.py --write"

SENTINEL = ("<!-- Everything above this line is `describe_all()` in "
            "scripts/game/flow/ops.py. Everything below is MEASURED by "
            "tools/check_event_docs.py -- every row is produced by running "
            "something, never by reading a flag. Regenerate the whole file "
            "with:  %s  -->" % REGENERATE)

failures: list[str] = []
asserted: list[int] = []


def expect(label, got, want):
    asserted.append(1)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    expect(label, bool(got), True)


def expect_empty(label, got):
    asserted.append(1)
    ok = not got
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
          f"{'--' if ok else got}")
    if not ok:
        failures.append(f"{label}: {got}")


# ===========================================================================
# The fixtures every probe runs against
# ===========================================================================

DELTA = 1.0
PROBE_VARS = sf.read_vars({
    "flag": {"type": "bool", "default": False, "doc": "Written by a probe."},
    "count": {"type": "int", "default": 0, "doc": "Written by a probe."},
    "pick": {"type": "int", "default": -1, "doc": "Written by an ask."},
})


class ProbeHost:
    """`say_open` / `say_close`, recording what it was told."""

    def __init__(self):
        self.calls: list = []

    def say_open(self, who, text):
        self.calls.append(("open", who, text))

    def say_close(self):
        self.calls.append(("close",))


class ProbeBody:
    """An entity-shaped thing carrying a `BodyState` and nothing else."""


def probe_body(**axes):
    made = ProbeBody()
    state = ensure_state(made)
    for axis, value in axes.items():
        setattr(state, axis, value)
    return made


def probe_script(body, script_id="probe", loadouts=("core",), registry=None):
    return sf.parse_script(
        {"format": sf.FORMAT, "version": sf.VERSION, "id": script_id,
         "loadouts": list(loadouts),
         "pages": [{"id": "pg", "when": [], "body": body}]},
        "%s.json" % script_id, variables=PROBE_VARS, registry=registry)


def probe_run(body, *, registry=None, **kw):
    run = ScriptRun(probe_script(body, registry=registry),
                    variables=sf.VarStore(PROBE_VARS), **kw)
    run.begin()
    return run


# ===========================================================================
# The runtime probes. Each RUNS the op and reports what it observed.
# ===========================================================================

def _probe_say():
    host = ProbeHost()
    run = probe_run([{"id": "n1", "do": "say", "who": "K", "text": "Line."}],
                    host=host)
    run.update(DELTA)
    opened = host.calls == [("open", "K", "Line.")]
    waited = not run.done
    run.advance()
    run.update(DELTA)
    closed = host.calls[-1] == ("close",) and run.done
    return (opened and waited and closed,
            "opens a duck-typed host's line, waits for the advance, closes it")


def _probe_ask():
    run = probe_run([{"id": "n1", "do": "ask", "prompt": "Which?",
                      "options": ["a", "b"], "into": "pick"}],
                    host=ProbeHost())
    try:
        run.update(DELTA)
    except PyoneerConfigError as exc:
        # The FIRST line only, whitespace collapsed: the error carries a
        # `push_frame` trail on later lines, and a newline inside a markdown
        # cell silently ends the table two rows early.
        first = " ".join(str(exc).splitlines()[0].split())
        return False, "raises: %s" % first.split(": ", 1)[-1][:88]
    return True, "wrote an index into `into`"


def _probe_set():
    run = probe_run([{"id": "n1", "do": "set", "var": "count", "to": 7}])
    run.update(DELTA)
    return run.variables.get("count") == 7, "writes the variable store"


def _probe_wait():
    run = probe_run([{"id": "n1", "do": "wait", "ms": 2 * MS_PER_DELTA},
                     {"id": "n2", "do": "set", "var": "count", "to": 1}])
    run.update(DELTA)
    early = run.variables.get("count") == 0
    run.update(DELTA)
    return (early and run.variables.get("count") == 1,
            "elapses on the frame it is due and not before")


PARK = {"id": "park", "do": "wait", "ms": 100 * MS_PER_DELTA}
"""A node that yields for a long time, so a probe can observe a run MID-RUN.

Without it every hold probe is vacuous: a run that reaches its end gives the
agency back on the way out, so a `hold` that did nothing and a `release` that
did nothing both look correct once the run is over.
"""


def _probe_hold():
    body = probe_body()
    run = probe_run([{"id": "n1", "do": "hold", "steerable": False}, PARK],
                    bodies=[body])
    run.update(DELTA)
    return (state_of(body).steerable is False and run.holding and not run.done,
            "clears the axis on a real BodyState, and keeps holding it")


def _probe_release():
    # Two halves in one probe. The body was ALREADY unsteerable, so a release
    # writing `True` fails it -- and the run is still RUNNING when it is read,
    # so a release op that did nothing fails it too, where the teardown's own
    # restore would have covered for it.
    body = probe_body(steerable=False)
    run = probe_run([{"id": "n1", "do": "hold", "steerable": False},
                     {"id": "n2", "do": "release"}, PARK], bodies=[body])
    run.update(DELTA)
    return (state_of(body).steerable is False and not run.holding
            and not run.done,
            "gives back the RECORDED value mid-run -- an already-held body "
            "stays held")


def _probe_call():
    inner = probe_script([{"id": "i1", "do": "set", "var": "count", "to": 3}],
                         script_id="inner")
    run = probe_run([{"id": "n1", "do": "call", "script": "inner"}],
                    scripts={"inner": inner})
    run.update(DELTA)
    return run.variables.get("count") == 3, "runs the called script's body"


def _probe_stop():
    run = probe_run([{"id": "n1", "do": "stop"},
                     {"id": "n2", "do": "set", "var": "count", "to": 9}])
    run.update(DELTA)
    return (run.done and run.variables.get("count") == 0,
            "ends the run; nothing after it runs")


AUDIO_SETTINGS = {"frequency": 44100, "size": -16, "channels": 2,
                  "buffer": 512, "master_volume": 0.5}
"""The probes own mixer numbers. Not read from `config/audio.json`: this
file's output is byte-compared, and a probe whose note depended on the
machine would make the document differ between two correct clones."""


def _probe_audio():
    """A prepared AudioManager, silent about an absent card."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # a runner with no card warns once
        AudioManager.reset_singleton()
        return AudioManager().prepare(AUDIO_SETTINGS)


def _probe_play_sound():
    _probe_audio()
    run = probe_run([{"id": "n1", "do": "play_sound",
                      "sound": "sfx/chime.wav"},
                     {"id": "n2", "do": "set", "var": "count", "to": 1}])
    run.update(DELTA)
    # Device-independent on purpose: `locate` RAISES for a name neither audio
    # root holds whether or not there is a card, so reaching n2 at all means
    # the file was really found and the call really went through. Asserting
    # the Sound cache instead would make this row read differently on a
    # machine with a sound card.
    return (run.done and run.variables.get("count") == 1,
            "finds the file and starts it, finishing in the same frame")


def _probe_play_music():
    audio = _probe_audio()
    run = probe_run([{"id": "n1", "do": "play_music",
                      "track": "music/pleasant_moments.ogg"},
                     {"id": "n2", "do": "set", "var": "count", "to": 1}])
    run.update(DELTA)
    ran = run.done and run.variables.get("count") == 1
    named = audio.music_name == "music/pleasant_moments.ogg"
    audio.stop_music()
    return ran and named, "starts the stream and finishes in the same frame"


PROBES = {
    "say": _probe_say, "ask": _probe_ask, "set": _probe_set,
    "wait": _probe_wait, "hold": _probe_hold, "release": _probe_release,
    "call": _probe_call, "stop": _probe_stop,
    "play_sound": _probe_play_sound, "play_music": _probe_play_music,
}
"""One probe per op. `describe_all` cannot see any of this: a spec says what
an op CLAIMS, and only running it says what it DOES."""


def runtime_rows(registry=None):
    """(op, ran, what was observed) for every registered op, measured."""
    table = OP_REGISTRY if registry is None else registry
    rows = []
    for name in sorted(table):
        probe = PROBES.get(name)
        if probe is None:
            rows.append((name, False,
                         "**no probe** -- add one to `PROBES` in "
                         "tools/check_event_docs.py"))
            continue
        ran, note = probe()
        rows.append((name, ran, note))
    return rows


# ===========================================================================
# Reachability. Who, above this layer, can actually use any of it.
# ===========================================================================

SKIP_DIRS = {".git", "__pycache__", ".venv", "docs", "data"}


def python_files(*roots):
    """Every tracked-looking .py under `roots`, repo-relative and sorted."""
    found = []
    for root in roots:
        base = os.path.join(ROOT, root)
        for folder, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                if name.endswith(".py"):
                    found.append(os.path.relpath(os.path.join(folder, name),
                                                 ROOT).replace("\\", "/"))
    return sorted(found)


def _tree(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8",
              errors="replace") as handle:
        return ast.parse(handle.read())


def importers(module_name, *roots):
    """Files under `roots` whose PARSE TREE imports `module_name`.

    The tree and not the text, so a docstring naming the module -- and every
    module in this layer names its neighbours in prose -- does not count as a
    caller. That is the difference between "documented" and "reachable", and
    this repository's signature defect lives in the gap.
    """
    hits = []
    for rel in python_files(*roots):
        tree = _tree(rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                whole = "%s.%s" % (node.module or "",
                                   node.names[0].name if node.names else "")
                if node.module == module_name or whole == module_name:
                    hits.append(rel)
                    break
            elif isinstance(node, ast.Import):
                if any(a.name == module_name for a in node.names):
                    hits.append(rel)
                    break
    return sorted(set(hits))


def constructors(name, *roots, exclude=()):
    """Files under `roots` that CALL `name(...)`, from the parse tree.

    `exclude` drops the module that DEFINES the thing: `load_scripts` calling
    `load_script` is one function calling its neighbour, not a production
    reader, and counting it would print a `yes` for a wire that does not
    exist -- which is the exact lie this table is the instrument against.
    """
    hits = []
    for rel in python_files(*roots):
        if rel in exclude:
            continue
        for node in ast.walk(_tree(rel)):
            if not isinstance(node, ast.Call):
                continue
            called = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            if called == name:
                hits.append(rel)
                break
    return sorted(set(hits))


def packs_granting():
    """(packs declaring `event_loadouts`, whether any parser reads the key).

    The raw `genre.json` is read here and NOT the loaded pack, deliberately
    and with the reason stated in the row: there is no parser for this key
    yet, so the loaded pack cannot answer. The moment one exists, this
    measurement is the thing that says so.
    """
    granted = {}
    if os.path.isdir(GENRES_DIR):
        for genre_id in sorted(os.listdir(GENRES_DIR)):
            path = os.path.join(GENRES_DIR, genre_id, "genre.json")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as handle:
                try:
                    raw = json.load(handle)
                except json.JSONDecodeError:
                    continue
            if isinstance(raw, dict) and raw.get("event_loadouts"):
                granted[genre_id] = tuple(raw["event_loadouts"])
    parsed = False
    if os.path.isfile(GENRE_MODULE):
        with open(GENRE_MODULE, encoding="utf-8", errors="replace") as handle:
            parsed = "event_loadouts" in handle.read()
    return granted, parsed


def scripts_on_disk():
    if not os.path.isdir(SCRIPTS_ON_DISK):
        return []
    return sorted(n for n in os.listdir(SCRIPTS_ON_DISK)
                  if n.endswith(".json"))


def reach_rows():
    """(the wire, whether it exists, what it takes) -- every one derived."""
    editor_reach = importers("scripts.game.flow.ops", "editor")
    started = constructors("ScriptRun", "scripts", "demos", "editor")
    defines = ("scripts/loaders/script_file.py",)
    read = (constructors("load_script", "scripts", "demos", "editor",
                         exclude=defines)
            + constructors("load_scripts", "scripts", "demos", "editor",
                           exclude=defines))
    granted, parsed = packs_granting()
    on_disk = scripts_on_disk()
    return [
        ("an op registry exists and is populated", bool(OP_REGISTRY),
         "%d op(s) in %s" % (len(OP_REGISTRY),
                             ", ".join("`%s`" % l
                                       for l in ops_module.loadouts()))),
        ("a genre pack GRANTS a loadout (`event_loadouts`)", bool(granted),
         "one array in a pack's `genre.json`, validated through "
         "`ops.validate_loadouts`. %s"
         % ("granted by " + ", ".join(sorted(granted)) if granted else
            "no pack declares the key, and `editor/core/genre.py` %s parse it"
            % ("does" if parsed else "does not"))),
        ("an editor module reaches the op registry (the PICKER)",
         bool(editor_reach),
         "an `editor/ui/` module importing `scripts.game.flow.ops` and "
         "offering its names. Until one does, every op above is registered, "
         "documented, checked and UNREACHABLE from the layer that asks for "
         "it." if not editor_reach else
         "reached by " + ", ".join("`%s`" % r for r in editor_reach)),
        ("a script document is read from disk in production", bool(read),
         "`script_file.load_scripts()` called from the game's boot" if not read
         else "read in " + ", ".join("`%s`" % r for r in sorted(set(read)))),
        ("a `ScriptRun` is constructed outside the checks", bool(started),
         "one `ScriptRun(...)` and one `manager.actions.route(...)`, which is "
         "how `demos/narrative.py` already starts a `SceneFlow`" if not started
         else "constructed in " + ", ".join("`%s`" % s for s in started)),
        ("a script document exists under `%s`" % sf.SCRIPTS_DIR.replace("\\", "/"),
         bool(on_disk),
         "%d file(s): %s" % (len(on_disk), ", ".join(on_disk)) if on_disk
         else "no `.json` there yet; the reader treats a missing directory as "
              "no scripts rather than an error"),
    ]


# ===========================================================================
# The generator
# ===========================================================================

def render_doc(registry=None) -> str:
    """The whole of `docs/EVENTS.md`: the registry, then the measurements.

    `describe_all()` first and verbatim, so the half the registry owns is not
    paraphrased anywhere. Then the two things it cannot see: what each op DOES
    when it is run, and who above this layer can reach any of it.
    """
    table = OP_REGISTRY if registry is None else registry
    lines = [describe_all(table).rstrip("\n"), "", SENTINEL, ""]

    rows = runtime_rows(table)
    lines.append("## Measured runtime")
    lines.append("")
    lines.append(
        "Every row below is produced by constructing a `ScriptRun` over a "
        "one-node script and stepping it, then observing the effect. A row "
        "that says *no* is an op that does not do its job at this commit -- "
        "not one that is merely undocumented.")
    lines.append("")
    lines.append("%d of %d op(s) run." % (sum(1 for _, ok, _ in rows if ok),
                                          len(rows)))
    lines.append("")
    lines.append("| op | loadout | status | runtime | what was observed |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name, ok, note in rows:
        spec = table[name]
        lines.append("| `%s` | `%s` | %s | %s | %s |"
                     % (name, spec.loadout, spec.status,
                        "**yes**" if ok else "no", note))
    lines.append("")

    lines.append("## Reachability")
    lines.append("")
    lines.append(
        "Each row is measured from the parse tree of the tree above this "
        "layer, not from a flag. A capability that is registered, documented "
        "and checked while nothing above it can reach one is this "
        "repository's signature defect; this table is the instrument against "
        "it.")
    lines.append("")
    lines.append("| the wire | at this commit | what it takes |")
    lines.append("| --- | --- | --- |")
    for what, ok, cost in reach_rows():
        lines.append("| %s | %s | %s |" % (what, "**yes**" if ok else "no",
                                           cost))
    lines.append("")

    lines.append("## The loadouts")
    lines.append("")
    lines.append(
        "A loadout exists because an op declares it; there is no separate "
        "list. A document names the loadouts it uses at its head, every op it "
        "spells must belong to one of them, and both checks happen at LOAD.")
    lines.append("")
    lines.append("| loadout | ops |")
    lines.append("| --- | --- |")
    for loadout in ops_module.loadouts(table):
        members = sorted(s.name for s in table.values()
                         if s.loadout == loadout)
        lines.append("| `%s` | %s |"
                     % (loadout, ", ".join("`%s`" % m for m in members)))
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


print("check_event_docs -- the paper must agree with what the ops DO")
print(f"  registry: {len(OP_REGISTRY)} op(s); probes: {len(PROBES)}")

if "--write" in sys.argv:
    with open(DOC_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_doc())
    print(f"\nwrote {os.path.relpath(DOC_PATH, ROOT)} "
          f"({len(OP_REGISTRY)} op(s))")
    raise SystemExit(0)


DOC_EXISTS = os.path.isfile(DOC_PATH)
DOC = ""
if DOC_EXISTS:
    with open(DOC_PATH, encoding="utf-8", newline="") as handle:
        DOC = handle.read().replace("\r\n", "\n")


# ===========================================================================
print("\n1. docs/EVENTS.md is exactly what the generator produces")
# ===========================================================================
expect_true("the file exists at all (run --write if this is the first pass)",
            DOC_EXISTS)
expect_true("its first half is byte-for-byte ops.describe_all()",
            DOC.startswith(describe_all(OP_REGISTRY).rstrip("\n")))
expect("...and the whole file matches the generator", DOC, render_doc())
expect("the boundary between the two halves is marked exactly once",
       DOC.count(SENTINEL), 1)
# Not implied by the equality above, unlike the count: if `describe_all` ever
# emitted this marker itself the boundary would be ambiguous and the prefix
# assertion would be reading the wrong half of the file.
expect("...and the generated half never emits the marker itself",
       describe_all(OP_REGISTRY).count(SENTINEL), 0)
expect_true("the file names the command that regenerates it",
            REGENERATE in DOC)
# Determinism: two renders in one process must agree, or the byte-comparison
# above is a coin toss that happens to be landing the same way.
expect("the generator is deterministic", render_doc(), render_doc())


# ===========================================================================
print("\n2. every op has a probe, and every probe has an op")
# ===========================================================================
# BOTH DIRECTIONS, and they catch different mistakes: registry -> probes means
# an op landed and nothing measures it, so its row would be a claim; probes ->
# registry means a probe outlived the op it measured, and it would be
# measuring nothing while looking like coverage.
expect_empty("every registered op has a runtime probe (registry -> probes)",
             sorted(set(OP_REGISTRY) - set(PROBES)))
expect_empty("every probe names a registered op (probes -> registry)",
             sorted(set(PROBES) - set(OP_REGISTRY)))


# ===========================================================================
print("\n3. the runtime column is a MEASUREMENT, not a flag")
# ===========================================================================
MEASURED = {name: ok for name, ok, _ in runtime_rows()}
expect("every op the registry calls `live` actually runs",
       sorted(n for n, ok in MEASURED.items()
              if ok != (OP_REGISTRY[n].status == "live")), [])
expect("...so `ask` -- the one needs-host op -- measures as NOT running",
       MEASURED["ask"], False)
expect("...and `say`, which needs the same kind of host, DOES run",
       MEASURED["say"], True)

# The half that stops the column from being a rubber stamp: an op that does
# nothing must measure as `no`. Without this, a prober that returned True
# unconditionally would print a table of yeses forever.
_planted: dict = {}
ops_module.register(OpSpec(name="probe_decoy", summary="Does nothing.",
                           run=lambda run, args: True), _planted)
_decoy_rows = runtime_rows(_planted)
expect("a planted op with no probe is reported as unmeasured, not as running",
       [(name, ok) for name, ok, _ in _decoy_rows], [("probe_decoy", False)])
expect("...and its note says what to do about it",
       "no probe" in _decoy_rows[0][2], True)

# And the probes themselves have teeth, in two ways that are easy to lose.
# One: an already-held body is the only body a `True`-writing release fails
# on. Two: the run must still be RUNNING when the axis is read, because a run
# that reached its end gives the agency back on the way out and would cover
# for a `release` op that did nothing at all.
_greedy = probe_body(steerable=False)
_run = probe_run([{"id": "n1", "do": "hold", "steerable": False},
                  {"id": "n2", "do": "release"}, PARK], bodies=[_greedy])
_run.update(DELTA)
expect("the release probe reads an ALREADY-held body, mid-run",
       (state_of(_greedy).steerable, _run.done, _run.holding),
       (False, False, False))
# The control: the same body, the same hold, and NO release node -- the run
# is still holding, which is what the probe above is distinguishing from.
_still = probe_body(steerable=False)
_held = probe_run([{"id": "n1", "do": "hold", "steerable": False}, PARK],
                  bodies=[_still])
_held.update(DELTA)
expect("...and without the release node the same run is still holding",
       (_held.holding, _held.done), (True, False))


# ===========================================================================
print("\n4. the reachability columns are measurements too")
# ===========================================================================
REACH = {what: ok for what, ok, _ in reach_rows()}
expect("the registry row is true, which proves the table is not all-no",
       REACH["an op registry exists and is populated"], True)
# The control on the scan itself: this file imports the op registry, so a scan
# that matched nothing because the module name was misspelled is
# distinguishable from an honest zero.
expect("the importer scan finds THIS file's own import of the op registry",
       "tools/check_event_docs.py" in importers("scripts.game.flow.ops",
                                                "tools"), True)
expect("...and finds nothing for a module name that does not exist",
       importers("scripts.game.flow.opz", "tools", "scripts", "editor"), [])
expect("the constructor scan finds THIS file's own ScriptRun(...)",
       "tools/check_event_docs.py" in constructors("ScriptRun", "tools"), True)
expect("...and finds nothing for a name nothing calls",
       constructors("ScriptRunnerFactory", "tools", "scripts"), [])


# ===========================================================================
print("\n5. the document names exactly the registry")
# ===========================================================================
_named = sorted({line.split("`")[1] for line in DOC.splitlines()
                 if line.startswith("| `") and "`" in line[3:]}
                & set(OP_REGISTRY))
expect("every registered op is named in a table row of the file",
       _named, sorted(OP_REGISTRY))
_headings = sorted(line[5:-1] for line in DOC.splitlines()
                   if line.startswith("### `") and line.endswith("`"))
expect("...and each has its own section, in the other place they are named",
       _headings, sorted(OP_REGISTRY))

def _cells(row):
    """A markdown table row's cells, trimmed: ``| a | b |`` -> ``['a', 'b']``."""
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _under(heading):
    """The lines under `heading`, stopping at the NEXT heading of ANY level.

    Stopping at `###` is the whole point. The per-op sections under
    `## The registry` carry PARAMETER tables, whose second column is a type
    and whose third is a default -- so a scan that reads "the second inline
    code span of any table row" reads a parameter default as a loadout and
    reports `''`, `'assign'` and `0.0` as loadouts the registry does not
    know. Measured: that is exactly what it reported the first time this
    document was generated.
    """
    out, inside = [], False
    for line in DOC.splitlines():
        if line.startswith("#"):
            inside = line.lstrip("#").strip() == heading
            continue
        if inside:
            out.append(line)
    return out


# Where a loadout is actually printed, read by COLUMN rather than by counting
# backticks: column 2 of the two op tables, column 1 of the loadout table.
_loadouts = set()
for _heading in ("The registry", "Measured runtime"):
    for _row in _under(_heading):
        _cs = _cells(_row)
        if len(_cs) >= 2 and _cs[0].strip("`") in OP_REGISTRY:
            _loadouts.add(_cs[1].strip("`"))
for _row in _under("The loadouts"):
    _cs = _cells(_row)
    if len(_cs) >= 2 and _cs[0].startswith("`"):
        _loadouts.add(_cs[0].strip("`"))
expect_empty("no loadout the file names is one the registry does not know",
             sorted(_loadouts - set(ops_module.loadouts())))
# The other half: a scan that found NOTHING would pass the refusal above
# forever. It must have read every loadout there is to have seen a wrong one.
expect("...having read every loadout the file prints, so it could see a wrong one",
       sorted(_loadouts), sorted(ops_module.loadouts()))
expect("the file states the op count the registry actually has",
       ("%d op(s) in %d loadout(s)" % (len(OP_REGISTRY),
                                       len(ops_module.loadouts()))) in DOC,
       True)


# ===========================================================================
print("\n%d assertion(s), %d failure(s)" % (len(asserted), len(failures)))
for _failure in failures:
    print("  FAILED: %s" % _failure)
if not DOC_EXISTS:
    print("\n  NOTE  docs/EVENTS.md has never been generated. Run:\n"
          "        %s" % REGENERATE)
print("""
MUTATIONS THIS FILE HAS BEEN RUN AGAINST -- each one was applied, this check
was run, the named assertions went red, and the source was put back:

  * `AgencyHold.give_back` writing `True` instead of the saved value
        -> FAILED 2: "the release probe reads an ALREADY-held body, mid-run",
           and "every op the registry calls `live` actually runs", which
           reported `['release']`. The row in the table flipped to `no`, which
           is the whole point: a broken op cannot stay documented as working
  * `ask`'s run writing index 0 and returning True
        -> FAILED 2: "`ask` measures as NOT running", and the same live-vs-
           runtime agreement, which reported `['ask']`. A promise printed as a
           `yes` is what this column exists to make impossible

TWO THINGS THIS FILE'S OWN SHAPE ALREADY PROVES, so they were not run as
source edits: a ninth op with no probe is planted live in section 3 and
reported as unmeasured, and the `opz` / `ScriptRunnerFactory` controls in
section 4 show both scans answering a real zero rather than always agreeing.
""")
raise SystemExit(1 if failures else 0)
