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
     4. the reachability columns are measurements of CODE, each from the
        parse tree of the tree above this layer or from loading the thing
        itself -- and every one of them is DRIVEN TO `no` here by a NEGATIVE
        CORPUS that names the mutation, against a planted world where the
        code is broken and the data left intact, and to `yes` by a planted
        world where it is whole
     5. the document names exactly the registered ops, in both places it names
        them, and every loadout it names is one the registry knows

A REACHABILITY ROW MUST BE ABLE TO GO RED
-----------------------------------------
A row that cannot report `no` is the vacuous assertion, one level up: it
prints a green word forever and the reader believes a wire exists. Two rows
here were exactly that, and both were caught by a person driving the code
rather than reading it:

  * the pack row asserted DATA. It read the two raw `genre.json` files and
    never the parser, so bypassing `editor/core/genre.py` entirely left the
    row reading `yes`, while deleting one JSON line left it reading `no`.
    It now LOADS each pack through `editor.core.genre.load()` and narrows
    the live op table through `GenrePack.granted_registry`, so the row
    reports the code path it names.
  * the picker row measured the WHOLE `editor` package while its own text
    demanded an `editor/ui/` module, and an `editor/core/` importer had
    already been counted as evidence. It now measures `editor/ui/` only,
    and requires the module to NAME the table as well as import it.
  * the picker row AGAIN, one pass later and for a third name: its
    vocabulary of op-table names carried `granted_registry`, which is a
    `GenrePack` method and no attribute of the op module at all. So the
    picker could drop both of its real table reads, keep
    `genre.granted_registry(base)`, and the row still printed `yes` with the
    whole check green over it. The same scan also counted a module's OWN
    `OP_REGISTRY = {}` local, because it matched a bare spelling anywhere in
    the parse tree. Both halves are closed: `OP_TABLE_NAMES` holds only
    attributes of the op module (asserted in section 4), and
    `reading_table` resolves a name THROUGH the import that brought it in.

THE NEGATIVE CORPUS
-------------------
Three passes, three rows found lying, three repairs of one name each. So the
repair this time is structural: section 6 carries `CORPUS`, and for EVERY row
it writes down the specific mutations that must drive that row to `no` -- the
ones a person has been performing by hand on the real tree -- plus at least
one planted world that drives it to `yes`. A coverage gate refuses a row
whose corpus is one-sided, so a seventh row cannot land with a detector
nobody has seen give both answers. The broken world is a decoy source tree in
memory, a loader whose parser drops the key, an empty registry, a directory
this check makes and throws away; no tracked file is edited to build any of
it. Two entries expect `yes` for a wire that does not run -- a call under
`if False:`, a `return` above the construction -- because rows 4 and 5 say
*read* and *constructed* and are call scans: that blindness is asserted here
so it stays declared rather than being rediscovered a fourth time.

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
import tempfile
import warnings
from dataclasses import replace

import pygame

pygame.init()

from scripts.core.audio import AudioManager
from scripts.core.errors import PyoneerConfigError, PyoneerError
from scripts.game.behavior.movement import MS_PER_DELTA
from scripts.game.behavior.state import ensure_state, state_of
from scripts.game.flow import ops as ops_module
from scripts.game.flow.interpreter import ScriptRun
from scripts.game.flow.ops import OP_REGISTRY, OpSpec, describe_all
from scripts.loaders import script_file as sf

try:
    from editor.core import genre as genre_packs
except ImportError:  # pragma: no cover -- a clone with `editor/` deleted
    # NOT a fallback to a plausible default: the pack row reports this state
    # in its own `what it takes` cell, because "the editor package is not
    # here" and "no pack grants a loadout" are different facts and a reader
    # of the table has to be able to tell them apart. A tool may import the
    # editor (law 2 binds `scripts/`); the engine still boots without it.
    genre_packs = None

ROOT = _bootstrap.REPO_ROOT
DOC_PATH = os.path.join(ROOT, "docs", "EVENTS.md")
GENRES_DIR = os.path.join(ROOT, "editor", "genres")
SCRIPTS_ON_DISK = os.path.join(ROOT, sf.SCRIPTS_DIR)

OPS_MODULE = "scripts.game.flow.ops"
UI_DIR = "editor/ui"
"""The picker row's own words. The row is titled *(the PICKER)* and its `no`
text demands an `editor/ui/` module, so this -- and not the whole `editor`
package -- is what it may scan. A core module reaching the registry is a
real fact and a different one."""

EVENT_LOADOUTS_KEY = (genre_packs.EVENT_LOADOUTS if genre_packs is not None
                      else "event_loadouts")
"""The `genre.json` key, taken from the parser that owns it.

Law 8 makes this a FILE FORMAT string and `editor/core/genre.py` spells it
once. This tool asks that module for it rather than retyping it, and carries
a literal only for the clone where `editor/` is deleted -- where nothing can
be asked and the row reads `no` anyway."""

OP_TABLE_NAMES = ("OP_REGISTRY", "ops_in", "describe_all")
"""Reading the op table means naming one of these, THROUGH an import of it.

An import alone is not a picker: a module may import `ops` for a type
annotation, an error message or a docstring reference and offer a person
nothing. These three are every way a reader gets a TABLE of ops out of that
module -- the registry itself, the loadout filter, and the describer -- so
naming one is the cheapest honest evidence that the names reach a widget.

EVERY ONE IS AN ATTRIBUTE OF `scripts.game.flow.ops`, and section 4 asserts
exactly that, because the fourth name this tuple carried until 2026-09-11 was
not. `granted_registry` is a `GenrePack` METHOD -- a pack's narrowing of the
table, spelled on a pack. So a picker could stop reading the op table
ENTIRELY (`op_registry.ops_in` and `OP_REGISTRY` both deleted from
`editor/ui/script_editor.py`, `genre.granted_registry(base)` left standing)
and row 3 still printed **yes**, with its own cell still claiming that module
"names one of its table readers". The whole check stayed green over it. A
name that is not an attribute of the module the row is about turns the row
into a test of some other module.

The second half of the same lesson is in `reading_table`: the name has to be
reached THROUGH the import, or a module's own `OP_REGISTRY = {}` local reads
as the registry."""

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


def python_files(*roots, sources=None):
    """Every tracked-looking .py under `roots`, repo-relative and sorted.

    A root may be a DIRECTORY or a single .py FILE. The file form exists
    because `main.py` is the game's boot and sits under no package: while
    this walker took directories only, the two rows below that describe what
    the boot does could not see the one file that does it, and both printed
    `no` for months after the wire landed. A reachability table blind to the
    file that closes the gap is worse than no table.

    `sources` replaces the tree with a `{repo/relative/path.py: source}`
    mapping, so section 6 can hand every scan a PLANTED world -- one where
    the wire is broken, or lives in the wrong package -- without editing a
    tracked file. Roots still apply to it, which is the whole point: a decoy
    under `editor/core/` must not answer a scan of `editor/ui/`.
    """
    if sources is not None:
        return sorted(rel for rel in sources
                      if any(rel == root
                             or rel.startswith(root.rstrip("/") + "/")
                             for root in roots))
    if roots in _FILES:
        return _FILES[roots]
    found = []
    for root in roots:
        base = os.path.join(ROOT, root)
        if os.path.isfile(base) and base.endswith(".py"):
            found.append(os.path.relpath(base, ROOT).replace("\\", "/"))
            continue
        for folder, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                if name.endswith(".py"):
                    found.append(os.path.relpath(os.path.join(folder, name),
                                                 ROOT).replace("\\", "/"))
    _FILES[roots] = sorted(found)
    return _FILES[roots]


_TREES: dict = {}
_FILES: dict = {}
_SCANS: dict = {}
"""Parse and scan caches for the REAL tree only -- never for a planted `sources` world.

The negative corpus drives `reach_rows` a few dozen times, and every call
that does not plant a world re-parses `scripts/`, `demos/`, `editor/` and
`main.py`: measured at 1.9s each, which would have made the corpus cost more
than the rest of this check put together. Nothing here writes a `.py` file,
so a tree parsed once in this process is the tree for the whole run, and a
scan of it answers the same thing every time it is asked."""


def _cached(key, hits, sources):
    """One scan's answer, remembered when it was taken from the REAL tree."""
    out = sorted(set(hits))
    if sources is None:
        _SCANS[key] = out
    return out


def _tree(rel, sources=None):
    if sources is not None:
        return ast.parse(sources[rel])
    if rel not in _TREES:
        with open(os.path.join(ROOT, rel), encoding="utf-8",
                  errors="replace") as handle:
            _TREES[rel] = ast.parse(handle.read())
    return _TREES[rel]


def importers(module_name, *roots, sources=None):
    """Files under `roots` whose PARSE TREE imports `module_name`.

    The tree and not the text, so a docstring naming the module -- and every
    module in this layer names its neighbours in prose -- does not count as a
    caller. That is the difference between "documented" and "reachable", and
    this repository's signature defect lives in the gap.
    """
    key = ("importers", module_name, roots)
    if sources is None and key in _SCANS:
        return _SCANS[key]
    hits = []
    for rel in python_files(*roots, sources=sources):
        tree = _tree(rel, sources=sources)
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
    return _cached(key, hits, sources)


def constructors(name, *roots, exclude=(), sources=None, through=None):
    """Files under `roots` that CALL `name(...)`, from the parse tree.

    `exclude` drops the module that DEFINES the thing: `load_scripts` calling
    `load_script` is one function calling its neighbour, not a production
    reader, and counting it would print a `yes` for a wire that does not
    exist -- which is the exact lie this table is the instrument against.

    `through` is the picker row's lesson applied to its two siblings BEFORE
    anyone exploits them. Given a module name, the call must be spelled with
    a name that module's import brought in -- `ScriptRun(...)` under a
    `from ...interpreter import ScriptRun`, `script_file.load_scripts(...)`
    under a `from scripts.loaders import script_file`. Without it this scan
    matches a spelling and not a wire: a boot that defines its own
    `class ScriptRun` and constructs that, or calls `self.load_scripts()` on
    something it wrote itself, reads **yes** for a wire that does not exist.
    Measured against the shipped tree: both rows name exactly the files they
    named before, because `main.py` really does import both names.
    """
    key = ("constructors", name, roots, tuple(exclude), through)
    if sources is None and key in _SCANS:
        return _SCANS[key]
    hits = []
    for rel in python_files(*roots, sources=sources):
        if rel in exclude:
            continue
        tree = _tree(rel, sources=sources)
        spellings = (None if through is None
                     else _spellings(tree, through, (name,)))
        if spellings is not None and not spellings:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if spellings is not None:
                if _dotted(node.func) in spellings:
                    hits.append(rel)
                    break
                continue
            called = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            if called == name:
                hits.append(rel)
                break
    return _cached(key, hits, sources)


def _dotted(node):
    """`a.b.c` written out, or None for anything that is not a plain name."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _spellings(tree, module_name, wanted):
    """Every way THIS file could spell one of `wanted` and mean that module's.

    Three import shapes, three bindings: `import a.b.c` binds the dotted path
    (`a.b.c.NAME`), `from a.b import c` binds the module under one name
    (`c.NAME`, or the `as` alias), and `from a.b.c import NAME` binds the
    attribute itself (a bare `NAME`, or its alias). Nothing else counts.

    This is the half `naming` -- what stood here until 2026-09-11 -- could not
    see. It matched a BARE spelling anywhere in the parse tree, so a module
    that imported the op module for a type hint and kept its own
    `OP_REGISTRY = {}` local read as a picker. Measured as a false positive on
    exactly that decoy, alongside the `granted_registry` one.

    A star import binds nothing this can name, so a picker written that way
    would read `no`. That is the direction to fail in and the reason to
    narrow rather than widen: a row that says `no` for a wire that exists
    sends somebody to look, while a row that says `yes` for a wire that does
    not is the defect this whole table is the instrument against.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    out |= {"%s.%s" % (alias.asname or alias.name, w)
                            for w in wanted}
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == module_name:
                    if alias.name in wanted:
                        out.add(alias.asname or alias.name)
                elif "%s.%s" % (node.module or "", alias.name) == module_name:
                    out |= {"%s.%s" % (alias.asname or alias.name, w)
                            for w in wanted}
    return out


def reading_table(wanted, module_name, *roots, sources=None):
    """Files under `roots` that read one of `wanted` THROUGH `module_name`.

    An attribute or a bare name, called or not: `op_registry.OP_REGISTRY` is
    a table a widget can iterate whether or not it is called. This is the
    half `importers` cannot see -- reaching for the module versus reaching
    for the names in it -- and it is only evidence when the name arrives
    through the import, which is what `_spellings` resolves.
    """
    key = ("reading_table", tuple(wanted), module_name, roots)
    if sources is None and key in _SCANS:
        return _SCANS[key]
    hits = []
    for rel in python_files(*roots, sources=sources):
        tree = _tree(rel, sources=sources)
        spellings = _spellings(tree, module_name, wanted)
        if not spellings:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Attribute, ast.Name))
                    and _dotted(node) in spellings):
                hits.append(rel)
                break
    return _cached(key, hits, sources)


def pickers(sources=None):
    """`editor/ui/` modules that import the op module AND read its table.

    BOTH halves, because either alone is a lie in a different direction. An
    import with no use is the "documented but unreachable" shape this table
    exists to catch; naming `OP_REGISTRY` without importing the module is
    some other module's attribute with a familiar spelling -- or its own,
    which is why the reading half resolves the name through the import
    rather than matching the spelling anywhere in the file.

    `editor/core/` is deliberately out of scope. The row is titled *(the
    PICKER)*, and a previous pass listed `editor/core/genre.py` as its
    evidence -- a core module that offers a person nothing -- which would
    have let the row read `yes` with no picker in existence.
    """
    return sorted(set(importers(OPS_MODULE, UI_DIR, sources=sources))
                  & set(reading_table(OP_TABLE_NAMES, OPS_MODULE, UI_DIR,
                                      sources=sources)))


def packs_granting(registry=None, *, loader=None, genres_dir=None):
    """(packs that really grant a loadout, why none does) -- by LOADING them.

    THE PACK IS LOADED, not read. This row asserted DATA until 2026-09-11: it
    parsed the two raw `genre.json` files itself, so `editor/core/genre.py`
    could be bypassed entirely -- parser gone, nothing narrowed, no pack
    granting anything -- and the row still printed `yes`, while removing one
    JSON line printed `no` with the code perfectly intact. Both directions
    were measured. A reachability row that reports the presence of two JSON
    lines is not reporting a wire.

    So a pack counts when the CODE delivers all three steps:

      1. `genre.load()` parses the key into `GenrePack.event_loadouts`
         (which is where `ops.validate_loadouts` judges it, and a name no op
         claims raises right here rather than reaching a script)
      2. the pack grants something -- `None` is silence and `()` is a
         deliberate "this genre does not script"; neither is a grant
      3. `GenrePack.granted_registry` narrows the LIVE op table to a
         non-empty one, so the grant reaches an op that exists

    The raw file is still opened, for one reason only: to tell "no pack
    declares the key" apart from "a pack declares it and the loaded pack
    carries none", which is the signature of the parser being broken. That
    difference is the whole diagnostic value of the `no` cell.
    """
    table = OP_REGISTRY if registry is None else registry
    where = GENRES_DIR if genres_dir is None else genres_dir
    load = loader
    if load is None:
        if genre_packs is None:
            return {}, ("`editor.core.genre` is not importable from here, so "
                        "no pack can be loaded to ask")
        load = genre_packs.load

    granted, declared, dropped, empty, barren, broken = {}, [], [], [], [], []
    found = sorted(os.listdir(where)) if os.path.isdir(where) else []
    for genre_id in found:
        path = os.path.join(where, genre_id, "genre.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            try:
                raw = json.load(handle)
            except json.JSONDecodeError:
                continue
        if isinstance(raw, dict) and EVENT_LOADOUTS_KEY in raw:
            declared.append(genre_id)
        try:
            pack = load(genre_id, where)
        except PyoneerError as exc:
            # Reported, not swallowed: a pack that will not load is a fact
            # about the wire, and a generator that dies on it takes the
            # whole document with it.
            broken.append("%s (%s)" % (genre_id, str(exc).splitlines()[0]))
            continue
        names = pack.event_loadouts
        if names is None:
            if genre_id in declared:
                dropped.append(genre_id)
            continue
        if not names:
            empty.append(genre_id)
            continue
        if not pack.granted_registry(table):
            barren.append(genre_id)
            continue
        granted[genre_id] = tuple(names)

    why = []
    if not found:
        why.append("there is no genre pack on disk to ask")
    elif not declared and not broken:
        why.append("no pack declares the key")
    if dropped:
        why.append("%s declare(s) it and the LOADED pack carries none, so "
                   "`editor/core/genre.py` is not parsing it"
                   % ", ".join(sorted(dropped)))
    if empty:
        why.append("%s grant(s) nothing, deliberately"
                   % ", ".join(sorted(empty)))
    if barren:
        why.append("%s grant(s) a loadout no registered op claims"
                   % ", ".join(sorted(barren)))
    if broken:
        why.append("%s will not load" % ", ".join(sorted(broken)))
    return granted, "; ".join(why)


def scripts_on_disk(where=None):
    base = SCRIPTS_ON_DISK if where is None else where
    if not os.path.isdir(base):
        return []
    return sorted(n for n in os.listdir(base) if n.endswith(".json"))


def reach_rows(registry=None, *, sources=None, loader=None, genres_dir=None,
               scripts_dir=None):
    """(the wire, whether it exists, what it takes) -- every one derived.

    Every seam this reads is an argument, and section 6 drives each one with
    the code broken: an empty `registry`, a `loader` whose parser drops the
    key, a planted `sources` tree, a `scripts_dir` with nothing in it. A row
    nobody has seen report `no` is a green word, not a measurement.
    """
    table = OP_REGISTRY if registry is None else registry
    picker = pickers(sources=sources)
    # `main.py` is named alongside the packages because it IS the game's boot
    # and belongs to no package. Two rows below describe something only that
    # file can do; scanning directories alone made them structurally unable
    # to report it.
    production = ("scripts", "demos", "editor", "main.py")
    # The module each name belongs to, ASKED of the thing rather than
    # retyped -- so a move renames the requirement with it, and neither scan
    # can be satisfied by a production module's own same-named symbol.
    started = constructors("ScriptRun", *production, sources=sources,
                           through=ScriptRun.__module__)
    defines = ("scripts/loaders/script_file.py",)
    read = (constructors("load_script", *production, exclude=defines,
                         sources=sources, through=sf.__name__)
            + constructors("load_scripts", *production, exclude=defines,
                           sources=sources, through=sf.__name__))
    granted, why_not = packs_granting(table, loader=loader,
                                      genres_dir=genres_dir)
    on_disk = scripts_on_disk(scripts_dir)
    return [
        ("an op registry exists and is populated", bool(table),
         "%d op(s) in %s" % (len(table),
                             ", ".join("`%s`" % l
                                       for l in ops_module.loadouts(table)))),
        ("a genre pack GRANTS a loadout (`event_loadouts`)", bool(granted),
         "one array in a pack's `genre.json`, validated through "
         "`ops.validate_loadouts`. %s"
         % ("granted by " + ", ".join(sorted(granted)) if granted
            else why_not)),
        ("an editor module reaches the op registry (the PICKER)",
         bool(picker),
         "an `editor/ui/` module importing `scripts.game.flow.ops` and "
         "offering its names. Until one does, every op above is registered, "
         "documented, checked and UNREACHABLE from the layer that asks for "
         "it." if not picker else
         "offered by %s, which both imports `scripts.game.flow.ops` and "
         "names one of its table readers (`OP_TABLE_NAMES` in "
         "tools/check_event_docs.py). An `editor/core/` importer reaches "
         "the registry too; it is not a picker and is not counted here."
         % ", ".join("`%s`" % r for r in picker)),
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
    reach = reach_rows(table)

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
    for what, ok, cost in reach:
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
# Two renders, taken once and reused: every render runs all ten probes and
# loads both genre packs, so calling it per assertion is the difference
# between a check that costs seconds and one that costs a minute. Two,
# because determinism below has to compare independent runs.
RENDERED = render_doc()
RENDERED_AGAIN = render_doc()
expect("...and the whole file matches the generator", DOC, RENDERED)
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
expect("the generator is deterministic", RENDERED, RENDERED_AGAIN)


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
# A root may be a single FILE, and it had to become one: `main.py` is the
# game's boot, belongs to no package, and is the ONLY file that can satisfy
# the two production rows. While the walker took directories only, those rows
# were structurally unable to report a wire that already existed. Both halves:
# the file form finds the file, and it does not quietly widen to its folder.
expect("a single .py file is a valid scan root, so the boot is visible",
       python_files("main.py"), ["main.py"])
expect("...and naming that file does NOT drag in its whole directory",
       [p for p in python_files("main.py") if p != "main.py"], [])
expect("the boot really is what the production scan sees it as",
       ("main.py" in constructors("load_scripts", "main.py"),
        "main.py" in constructors("ScriptRun", "main.py")), (True, True))
# The picker row's scope, asserted rather than left to a reader's care: the
# row says `editor/ui/`, and a previous pass listed `editor/core/genre.py` as
# its evidence. Anything outside `editor/ui/` in this list is that regression
# coming back.
# The literal, NOT `UI_DIR`: measured -- widening the constant back to
# "editor" made this assertion tautological and it stayed green through the
# exact regression it is here to catch.
expect("every module the picker row names lives under editor/ui/",
       [p for p in pickers() if not p.startswith("editor/ui/")], [])
# ...and the other half of it, because a filter over an empty list is green
# forever. This one pins CODE, not data: the shipped tree really does have a
# module offering the ops, and if it stops having one the assertion above
# goes back to proving nothing.
expect_true("...and the shipped tree really has one, so that filter read "
            "something", pickers())
# The vocabulary the picker row is measured with, measured itself. Every name
# in it must be an ATTRIBUTE OF THE OP MODULE -- the fourth name it carried
# until 2026-09-11 was a `GenrePack` method, so a module reading the pack and
# never the op table satisfied a test about the op table. Both halves in one:
# every name resolves, and there is at least one name to resolve.
expect("every name in `OP_TABLE_NAMES` is an attribute of the op module, "
       "and there is at least one",
       ([n for n in OP_TABLE_NAMES if hasattr(ops_module, n)],
        bool(OP_TABLE_NAMES)), (list(OP_TABLE_NAMES), True))


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
print("\n6. every reachability row goes NO when the CODE is broken")
# ===========================================================================
# The assertion a person had to write by hand, once, for one row -- and the
# reason this section exists is that when he wrote it, the row did not move.
# Nothing below edits a tracked file: the broken world is a decoy source tree
# in memory, a loader whose parser drops the key, an empty registry, and a
# directory this check makes and throws away.

def _row(rows, starts):
    """One row's verdict, addressed by the words the table prints."""
    for what, ok, _ in rows:
        if what.startswith(starts):
            return ok
    raise KeyError("no reachability row starts %r -- a row was renamed, and "
                   "both the corpus and its coverage gate address rows by "
                   "the words they print" % starts)


_TMP = tempfile.TemporaryDirectory(prefix="pyoneer_event_docs_")


def _fixture_genres(label, **extra):
    """A one-pack genres directory, built here and deleted with the run.

    LAW 4: this asserts what `editor/core/genre.py` DOES with a pack, never
    what the two packs in `editor/genres/` happen to contain. Point the row
    at the shipped packs and it measures somebody's JSON; point it at this
    and it measures the parser.
    """
    root = os.path.join(_TMP.name, label, "fixture")
    os.makedirs(root, exist_ok=True)
    raw = {"id": "fixture", "title": "Fixture pack"}
    raw.update(extra)
    with open(os.path.join(root, "genre.json"), "w", encoding="utf-8") as out:
        json.dump(raw, out)
    return os.path.dirname(root)


def _fixture_dir(label, files=()):
    """A directory holding exactly `files`, made here and deleted with the run."""
    made = os.path.join(_TMP.name, label)
    os.makedirs(made, exist_ok=True)
    for name in files:
        with open(os.path.join(made, name), "w", encoding="utf-8") as out:
            out.write("{}")
    return made


# ---------------------------------------------------------------------------
# THE BROKEN WORLDS. Each one is a mutation a person performed BY HAND on the
# real tree, written down here so nobody has to perform it again.
# ---------------------------------------------------------------------------

PICKER_FILE = "editor/ui/script_editor.py"
"""The real picker's own path, so a planted world under it IS the mutation
the prover ran on the tracked file. Nothing here opens it."""

# -- row 3: eight shapes of `editor/ui/` module -----------------------------
_PICKER_SOURCE = ("from scripts.game.flow import ops\n"
                  "def fill(menu):\n"
                  "    for name in sorted(ops.OP_REGISTRY):\n"
                  "        menu.addAction(name)\n")
_PICKER_FROM_IMPORT = ("from scripts.game.flow.ops import ops_in\n"
                       "def fill(menu, loadouts, table):\n"
                       "    for spec in ops_in(loadouts, table):\n"
                       "        menu.addAction(spec.name)\n")
_IMPORT_ONLY = ("from scripts.game.flow import ops  # for a type hint only\n"
                "def fill(menu: 'ops.OpSpec'):\n"
                "    menu.addAction('hard coded')\n")
_NAMES_ONLY = ("def fill(menu, table):\n"
               "    for name in sorted(table.OP_REGISTRY):\n"
               "        menu.addAction(name)\n")
_GRANTED_ONLY = ("from scripts.game.flow import ops as op_registry\n"
                 "CORE_OPS = ('say', 'wait')\n"
                 "def fill(menu, genre, base):\n"
                 "    for name in sorted(genre.granted_registry(base)):\n"
                 "        menu.addAction(name)\n")
_OWN_TABLE = ("from scripts.game.flow import ops as op_registry\n"
              "OP_REGISTRY = {}\n"
              "def fill(menu: 'op_registry.OpSpec'):\n"
              "    for name in sorted(OP_REGISTRY):\n"
              "        menu.addAction(name)\n")
_IN_COMMENT = ("from scripts.game.flow import ops as op_registry\n"
               "def fill(menu):\n"
               "    # one day, iterate op_registry.OP_REGISTRY here\n"
               "    menu.addAction('hard coded')\n")
_IN_DOCSTRING = ('from scripts.game.flow import ops as op_registry\n'
                 'def fill(menu):\n'
                 '    """Offers what op_registry.describe_all() describes."""\n'
                 '    menu.addAction("hard coded")\n')

# -- rows 4 and 5: four shapes of boot --------------------------------------
_BOOT_SOURCE = ("from scripts.loaders import script_file\n"
                "from scripts.game.flow.interpreter import ScriptRun\n"
                "def boot(store):\n"
                "    found = script_file.load_scripts('data/project')\n"
                "    return ScriptRun(found['greeting'])\n")
_INERT_SOURCE = ("from scripts.loaders import script_file\n"
                 "from scripts.game.flow.interpreter import ScriptRun\n"
                 "def boot(store):\n"
                 "    return None\n")
_DEAD_CALL = ("from scripts.loaders import script_file\n"
              "from scripts.game.flow.interpreter import ScriptRun\n"
              "def boot(store):\n"
              "    scripts = {}\n"
              "    if False:\n"
              "        scripts = script_file.load_scripts('data/project')\n"
              "    return None\n")
_UNREACHED_RUN = ("from scripts.loaders import script_file\n"
                  "from scripts.game.flow.interpreter import ScriptRun\n"
                  "def boot(store):\n"
                  "    return None\n"
                  "    return ScriptRun({}['greeting'])\n")
# The OTHER import shape, which is the one `main.py` actually uses for the
# reader: the name imported bare, the module imported under its own name.
# Both must count, or narrowing the scan would have traded a false positive
# for a false negative.
_OTHER_IMPORTS = ("from scripts.loaders.script_file import load_scripts\n"
                  "from scripts.game.flow import interpreter\n"
                  "def boot(store):\n"
                  "    found = load_scripts('data/project')\n"
                  "    return interpreter.ScriptRun(found['greeting'])\n")
# The picker's defect, transplanted onto rows 4 and 5: a familiar spelling
# that no import brought in. A boot with its own `ScriptRun` class and its
# own `load_scripts` method reads as the whole wire under a scan that
# matches names.
_OWN_NAMES = ("class ScriptRun:\n"
              "    def __init__(self, script):\n"
              "        self.script = script\n"
              "class Boot:\n"
              "    def load_scripts(self, where):\n"
              "        return {}\n"
              "    def boot(self):\n"
              "        found = self.load_scripts('data/project')\n"
              "        return ScriptRun(found)\n")

# -- rows 1, 2 and 6: the worlds that are not source ------------------------
_ONE_OP: dict = {}
ops_module.register(OpSpec(name="probe_only", run=lambda run, args: True,
                           summary="Planted: one op, so the registry row has "
                                   "a populated table to read."), _ONE_OP)
_GRANTS = _fixture_genres("grants", event_loadouts=["core"])
_SILENT = _fixture_genres("silent")
_NOTHING = _fixture_genres("nothing", event_loadouts=[])
_UNKNOWN = _fixture_genres("unknown", event_loadouts=["telepathy"])
_NO_PACKS = _fixture_dir("no_packs")
_NO_SCRIPTS = _fixture_dir("no_scripts")
_ONE_SCRIPT = _fixture_dir("one_script", ["planted.json"])
_NOT_JSON = _fixture_dir("not_json", ["README.txt"])
_MISSING = os.path.join(_TMP.name, "never_made")


def _parserless(genre_id, directory):
    """The mutation the prover ran by hand, as a seam instead of an edit.

    `_build` bypassing `_event_loadouts` -- every loaded pack silent, every
    `genre.json` on disk untouched. The row read **yes** through this,
    because it was reading the JSON.
    """
    return replace(genre_packs.load(genre_id, directory),
                   event_loadouts=None)


def _barren(genre_id, directory):
    """A pack granting a loadout no registered op claims, validation bypassed.

    `ops.validate_loadouts` refuses this AT PACK LOAD, so the only way to ask
    what the row does with a grant that reaches nothing is to hand it a pack
    the loader would never have built. The row must say no: a grant that
    narrows the live table to nothing has reached no op, whatever it says.
    """
    return replace(genre_packs.load(genre_id, directory),
                   event_loadouts=("telepathy",))


# -- the detectors themselves, which name the FILE and not just a verdict ----
expect("a planted editor/ui module that imports AND reads the table is one",
       pickers({"editor/ui/palette.py": _PICKER_SOURCE}),
       ["editor/ui/palette.py"])
expect("...so is one that imports the NAME itself and spells it bare",
       pickers({"editor/ui/palette.py": _PICKER_FROM_IMPORT}),
       ["editor/ui/palette.py"])
expect("...an import that never reads the table is NOT a picker",
       pickers({"editor/ui/palette.py": _IMPORT_ONLY}), [])
expect("...naming `OP_REGISTRY` without importing the module is NOT either",
       pickers({"editor/ui/palette.py": _NAMES_ONLY}), [])
expect("...nor is a module whose only table name is `granted_registry`, a "
       "GenrePack method and no attribute of the op module at all",
       pickers({"editor/ui/palette.py": _GRANTED_ONLY}), [])
expect("...nor one whose `OP_REGISTRY` is its OWN local, a familiar "
       "spelling reached through no import",
       pickers({"editor/ui/palette.py": _OWN_TABLE}), [])
expect("...nor a table name that lives in a COMMENT",
       pickers({"editor/ui/palette.py": _IN_COMMENT}), [])
expect("...nor one that lives in a DOCSTRING",
       pickers({"editor/ui/palette.py": _IN_DOCSTRING}), [])
expect("...and the SAME picker under editor/core/ is NOT -- the regression",
       pickers({"editor/core/palette.py": _PICKER_SOURCE}), [])

expect_true("the editor package is importable, so the pack row is measurable",
            genre_packs is not None)
if genre_packs is not None:
    expect("a planted pack granting `core` is seen as a grant, by LOADING it",
           packs_granting(genres_dir=_GRANTS)[0], {"fixture": ("core",)})
    expect("...a pack that never spells the key is silence, not a grant",
           packs_granting(genres_dir=_SILENT)[0], {})
    expect("...and `[]` -- this genre does not script -- is not one either",
           packs_granting(genres_dir=_NOTHING)[0], {})
    _none, _why_none = packs_granting(genres_dir=_NO_PACKS)
    expect("...and with no pack on disk at all the row says so, not 'no key'",
           (_none, "no genre pack" in _why_none), ({}, True))

    # The row's own cell claims the array is "validated through
    # `ops.validate_loadouts`". That claim is measured, and it is measured
    # where it happens: at pack load, before any script exists.
    try:
        genre_packs.load("fixture", _UNKNOWN)
        _refusal = "no raise"
    except PyoneerError as exc:
        _refusal = type(exc).__name__
    expect("a loadout no registered op claims is refused AT PACK LOAD",
           _refusal, "PyoneerGenreError")
    _refused, _why_refused = packs_granting(genres_dir=_UNKNOWN)
    expect("...and such a pack grants nothing, with the row saying why",
           (_refused, "will not load" in _why_refused), ({}, True))
    _dead, _why_dead = packs_granting(genres_dir=_GRANTS, loader=_parserless)
    expect("row 2 goes no when the PARSER is bypassed and the JSON left whole",
           (_dead, "not parsing it" in _why_dead), ({}, True))


# ---------------------------------------------------------------------------
# THE NEGATIVE CORPUS -- every row, and the mutations that must move it.
# ---------------------------------------------------------------------------
# Three passes running, a reachability row was found lying and the repair was
# one name: the pack row read JSON instead of the parser, the picker row
# scanned the whole `editor` package, and the picker row again counted a
# `GenrePack` method as an op-table read. Every one was found by a PERSON
# breaking the code by hand and watching the row not move. This table is that
# work written down: for each row, the mutations that MUST drive it to `no`,
# and at least one planted world that drives it to `yes`. A row whose corpus
# is one-sided fails the gate below, so a seventh row cannot land with a
# detector nobody has seen give both answers.
#
# Two entries expect `yes` for a wire that does not run. They are neither
# defects nor oversights: rows 4 and 5 say *read* and *constructed*, they are
# CALL scans, and a call the interpreter never reaches is still a call.
# Asserting the blindness is how it stays declared instead of being
# discovered a fourth time.

ROW_KEYS = ("an op registry", "a genre pack", "an editor module",
            "a script document is read", "a `ScriptRun`",
            "a script document exists")

CORPUS = [
    # -- row 1: the op registry ---------------------------------------------
    ("an op registry", True, {"registry": _ONE_OP},
     "one op registered is a populated table"),
    ("an op registry", False, {"registry": {}},
     "`register` never writes the table -- `target[spec.name] = spec` gone"),

    # -- row 3: the picker --------------------------------------------------
    ("an editor module", True,
     {"sources": {"editor/ui/palette.py": _PICKER_SOURCE}},
     "a real picker under editor/ui/"),
    ("an editor module", False, {"sources": {PICKER_FILE: _GRANTED_ONLY}},
     "R3c -- the picker's two real op-table reads deleted (ops_in -> "
     "specs_in, OP_REGISTRY -> CORE_OPS), granted_registry left standing"),
    ("an editor module", False, {"sources": {PICKER_FILE: _OWN_TABLE}},
     "...and the same file reading its OWN `OP_REGISTRY = {}` local"),
    ("an editor module", False, {"sources": {PICKER_FILE: _IMPORT_ONLY}},
     "R3b -- the import kept, every use of it deleted"),
    ("an editor module", False, {"sources": {PICKER_FILE: _NAMES_ONLY}},
     "R3a -- the import deleted, the table names left"),
    ("an editor module", False,
     {"sources": {"editor/core/palette.py": _PICKER_SOURCE}},
     "the whole picker moved to editor/core/, where it offers nobody "
     "anything"),

    # -- row 4: a script document read in production ------------------------
    ("a script document is read", True, {"sources": {"main.py": _BOOT_SOURCE}},
     "a boot that calls `load_scripts`"),
    ("a script document is read", False,
     {"sources": {"main.py": _INERT_SOURCE}},
     "R4 -- `self.scripts = load_scripts(...)` becomes `{}`"),
    ("a script document is read", False,
     {"sources": {"scripts/loaders/script_file.py": _BOOT_SOURCE}},
     "the only call is inside the module that DEFINES it"),
    ("a script document is read", False,
     {"sources": {"main.py": _INERT_SOURCE,
                  "tools/check_planted.py": _BOOT_SOURCE}},
     "the only call is in a CHECK, which is not production"),
    ("a script document is read", True, {"sources": {"main.py": _DEAD_CALL}},
     "DECLARED BLINDNESS: a call under `if False:` still reads yes -- the "
     "cell says read, not runs"),
    ("a script document is read", True, {"sources": {"main.py": _OTHER_IMPORTS}},
     "...and the other import shape counts too: `load_scripts` imported "
     "bare, which is what main.py really writes"),
    ("a script document is read", False, {"sources": {"main.py": _OWN_NAMES}},
     "the boot calls its OWN `load_scripts` method, imported from nowhere "
     "-- row 3's defect, on row 3's sibling scan"),

    # -- row 5: a ScriptRun constructed outside the checks ------------------
    ("a `ScriptRun`", True, {"sources": {"main.py": _BOOT_SOURCE}},
     "a boot that constructs one"),
    ("a `ScriptRun`", False, {"sources": {"main.py": _INERT_SOURCE}},
     "R5 -- `ScriptRun(` becomes `_NoRun(`"),
    ("a `ScriptRun`", False,
     {"sources": {"main.py": _INERT_SOURCE,
                  "tools/check_planted.py": _BOOT_SOURCE}},
     "the only construction is in a CHECK, which is what `outside the "
     "checks` means"),
    ("a `ScriptRun`", True, {"sources": {"main.py": _UNREACHED_RUN}},
     "DECLARED BLINDNESS: a `return` above the call still reads yes"),
    ("a `ScriptRun`", True, {"sources": {"main.py": _OTHER_IMPORTS}},
     "...and the other import shape counts too: the module imported, the "
     "class reached as an attribute of it"),
    ("a `ScriptRun`", False, {"sources": {"main.py": _OWN_NAMES}},
     "the boot constructs its OWN `class ScriptRun`, imported from nowhere "
     "-- row 3's defect, on row 3's other sibling scan"),

    # -- row 6: a script document on disk -----------------------------------
    ("a script document exists", True, {"scripts_dir": _ONE_SCRIPT},
     "one `.json` document in the directory"),
    ("a script document exists", False, {"scripts_dir": _NO_SCRIPTS},
     "the directory emptied -- every document moved out of the tree"),
    ("a script document exists", False, {"scripts_dir": _MISSING},
     "no such directory: missing is no scripts, never an error"),
    ("a script document exists", False, {"scripts_dir": _NOT_JSON},
     "a directory holding a file that is not a `.json` document"),
]

if genre_packs is not None:
    CORPUS += [
        # -- row 2: a genre pack grants a loadout ---------------------------
        ("a genre pack", True, {"genres_dir": _GRANTS},
         "a planted pack granting `core`, LOADED through editor/core/genre.py"),
        ("a genre pack", False, {"genres_dir": _GRANTS, "loader": _parserless},
         "R2 -- `_build` bypasses `_event_loadouts`; the JSON untouched"),
        ("a genre pack", False, {"loader": _parserless},
         "...the same bypass against the packs this repository ships"),
        ("a genre pack", False, {"genres_dir": _SILENT},
         "a pack that never spells `event_loadouts`"),
        ("a genre pack", False, {"genres_dir": _NOTHING},
         "a pack granting `[]` -- this genre does not script"),
        ("a genre pack", False, {"genres_dir": _NO_PACKS},
         "no genre pack on disk to ask"),
        ("a genre pack", False, {"genres_dir": _UNKNOWN},
         "a pack the loader refuses: it grants a loadout no op claims"),
        ("a genre pack", False, {"genres_dir": _GRANTS, "loader": _barren},
         "...and with that refusal bypassed too, a grant narrowing the live "
         "table to nothing"),
        ("a genre pack", False, {"registry": {}},
         "an empty op registry: the grant then reaches no op at all"),
    ]

# The gate that makes the corpus a rule rather than a habit. Both halves: the
# keys claim every row exactly once -- a renamed or an added row shows up here
# as UNCLAIMED rather than as a silent hole -- and each key carries a case
# that drives its row both ways.
_LIVE = [what for what, _, _ in reach_rows()]
expect("every reachability row is claimed by exactly one corpus key",
       sorted(next((k for k in ROW_KEYS if w.startswith(k)),
                   "UNCLAIMED: " + w) for w in _LIVE),
       sorted(ROW_KEYS))
for _n, _key in enumerate(ROW_KEYS, 1):
    expect("row %d has a corpus case driving it BOTH ways" % _n,
           sorted({want for key, want, _, _ in CORPUS if key == _key}),
           [False, True])

for _key, _want, _kw, _label in CORPUS:
    expect("row %d %s <- %s" % (ROW_KEYS.index(_key) + 1,
                               "yes" if _want else "NO ", _label),
           _row(reach_rows(**_kw), _key), _want)

_TMP.cleanup()


# ===========================================================================
print("\n%d assertion(s), %d failure(s)" % (len(asserted), len(failures)))
for _failure in failures:
    print("  FAILED: %s" % _failure)
if not DOC_EXISTS:
    print("\n  NOTE  docs/EVENTS.md has never been generated. Run:\n"
          "        %s" % REGENERATE)
elif DOC != RENDERED:
    # The file is the generator's output, so a mismatch is never fixed by
    # editing the document: either the code moved and the paper must be
    # reprinted, or a row really did change and the reprint is the news.
    print("\n  NOTE  docs/EVENTS.md no longer matches the generator. Reprint\n"
          "        it -- do not edit it -- with:\n"
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

AND TEN AGAINST THIS FILE ITSELF, because a detector is code too and these
rows shipped unable to report a `no`:

  * `UI_DIR` widened back to `"editor"` -- the picker row's old scan
        -> FAILED 3: "every module the picker row names lives under
           editor/ui/", which reported `['editor/core/genre.py',
           'editor/core/verbs.py']`; "...and the SAME picker under
           editor/core/ is NOT"; and "row 3 goes no in a world whose only
           op-reading module is core". Note the first of those was written
           as `UI_DIR + "/"` and stayed GREEN through this mutation, being
           a tautology in terms of the thing being mutated. It is the
           literal now, and that is why
  * `packs_granting` taking its names from `raw.get(key)` -- the old DATA
    assertion, reading the JSON instead of the loaded pack
        -> FAILED 2: "row 2 goes no when the PARSER is bypassed and the
           JSON left whole", which reported `({'fixture': ('core',)},
           False)`, and "...including against the packs this repository
           actually ships". This is the defect exactly: the parser gone and
           the row still green
  * the `granted_registry` gate in `packs_granting` removed
        -> FAILED 1: "...and row 2 with it, because the grant then reaches
           no op at all" -- a pack granting a name the live table cannot
           serve was being counted as a reached wire

AND SEVEN MORE on 2026-09-11, the pass that gave every row a corpus. The
first three are the defect that pass was sent to fix, taken apart into the
two independent halves it was made of and then put back together:

  * `granted_registry` returned to `OP_TABLE_NAMES`
        -> FAILED 1: "every name in `OP_TABLE_NAMES` is an attribute of the
           op module, and there is at least one", which reported the tuple
           with a `GenrePack` method in it
  * `reading_table` reverted to matching a bare spelling anywhere in the
    parse tree -- what `naming` did
        -> FAILED 2: "...nor one whose `OP_REGISTRY` is its OWN local" and
           its corpus row, both reporting the decoy as a picker
  * BOTH AT ONCE -- the defect exactly as a person found it by hand
        -> FAILED 5, the two above plus "...nor is a module whose only table
           name is `granted_registry`" and, the one that matters, "row 3 NO
           <- R3c -- the picker's two real op-table reads deleted ...
           granted_registry left standing", which reported `got=True`. That
           is the bypass: the picker reads no op table and the row says yes
  * a seventh row planted in `reach_rows` with no corpus behind it
        -> FAILED 2: "every reachability row is claimed by exactly one
           corpus key", which printed `UNCLAIMED: a planted seventh row
           nobody wrote a corpus for`, and the document comparison
  * row 6's three negative entries deleted, leaving the row one-sided
        -> FAILED 1: "row 6 has a corpus case driving it BOTH ways", which
           reported `[True]`. A row can no longer be added, or quietly
           reduced, to a detector nobody has seen say no
  * `UI_DIR` pointed at `editor/uix`, a directory that does not exist
        -> FAILED 5, and the one worth naming is "...and the shipped tree
           really has one, so that filter read something": the scope filter
           beside it passes over an empty list forever, which is the vacuous
           half this assertion exists to hold down
  * `through=` removed from both call scans in `reach_rows`
        -> FAILED 2: "row 4 NO <- the boot calls its OWN `load_scripts`
           method" and "row 5 NO <- the boot constructs its OWN `class
           ScriptRun`", both reporting `got=True`. Row 3's defect lives in
           its two sibling scans as well; it was closed there in the same
           change, and the shipped tree's rows did not move

TWO THINGS THIS FILE'S OWN SHAPE ALREADY PROVES, so they were not run as
source edits: a ninth op with no probe is planted live in section 3 and
reported as unmeasured, and the `opz` / `ScriptRunnerFactory` controls in
section 4 show both scans answering a real zero rather than always agreeing.
""")
raise SystemExit(1 if failures else 0)
