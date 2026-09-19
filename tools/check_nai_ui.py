"""The NovelAI composer window's contract: its argv table, its limits, its silence.

    .venv/Scripts/python.exe tools/check_nai_ui.py

WHAT THIS MEASURES, AND WHY EACH ASSERTION CAN GO RED
-----------------------------------------------------
`tools/nai_ui` is a COMMAND COMPOSER: every action it offers is an existing
`python -m tools.nai` subcommand, shown as an exact argv before it runs.
That design gives three things worth pinning, and this file pins all three.

1. THE ARGV TABLE AGAINST THE LIVE CLI. `request_pane.COMMAND_EXAMPLES` is
   one complete example argv per button. Every one is fed to the LIVE
   `tools.nai.cli.build_parser()`. A flag renamed, retyped or removed in
   the CLI turns this red instead of turning a button into a usage error at
   the author's desk. The reverse direction is checked too: every `flag` a
   `NAI_FIELDS` row declares must appear in some example, so a control the
   window offers cannot be a control nothing watches. And the subcommands
   that open a socket are READ OFF `tools/nai/cli.py`'s own source and must
   be exactly `SENDING_SUBCOMMANDS`, so a sending command added to the CLI
   cannot reach this window classified as free.

2. THE LIMITS AGAINST `tools.nai.model`. A locked control carries its
   reason as text -- "free tier: 28 steps max", "one sample",
   "<= 1,048,576 px". Those numbers are a SECOND SPELLING of rules that
   live in `model`, which is the sibling route CLAUDE.md's ACTIVE WARNINGS
   name. So every number is matched back: change `MAX_STEPS` and the
   sentence that still says 28 is named here.

3. THE SILENCE. `tools/nai_ui` must never read `NAI_KEY`'s value, never
   spell `--accept-max-2-anlas`, never `setParent(None)` (law 12), never
   import the network modules of `tools.nai`, and never start a process
   anywhere but `run_pane`. Each is a source-text assertion over the whole
   package, and each names the file and line it found.

4. THE WINDOW, DRIVEN. Sections 7 to 19 build a real `app.NaiWindow`
   off-screen and put it through the session a person has: pick a
   character, change an outfit, meet a file the loader refuses, compose
   each command, arm a send and watch an edit drop the arm. Each rule is
   asserted in BOTH DIRECTIONS (law 5), because half an invariant -- a
   gate proved to let something through and never proved to stop it -- is
   the dominant failure shape in this repository:

     * the garment combos ARE `model.GARMENT_SLOTS`: a sixth slot added to
       a copy of the vocabulary grows a sixth combo, and removing it takes
       it away;
     * the colour rows ARE `model.garment_parts(garments)`: a dress ADDS
       its row and REMOVES the tunic's and the pants';
     * a file the loader refuses shows the LOADER'S OWN sentence and
       blocks every command that names a character -- and a legal one
       blocks nothing;
     * the argv the window SHOWS parses under the live CLI into the values
       the form holds, and a default is not spelled;
     * a locked row holds no input at all, and the capped one clamps at
       `model.MAX_STEPS` while still accepting a legal value;
     * and the money rules: the send arms only behind a green dry run of
       its own request, drops on ANY change, a sending button never starts
       anything while a free one starts exactly one thing, and a decoy
       credential put into this process's own environment reaches no
       widget, no tooltip, no title, no argv and no saved file.

   SECTION 13 SETS `_cleared` BY HAND, and that is exactly how the defect
   section 14 exists for survived: an assertion that STANDS IN for the
   code it covers cannot fail the way that code does. `_finished` is the
   only thing that ever sets the clearance in production, and it read the
   line in the BOX -- which follows the form while a child runs -- so one
   nudge of a spinner during a `render` recorded a plan clearance for a
   request no dry run had judged, and SEND went live over an empty verdict
   list. Section 14 drives `_finished` for real, against a FAKE CHILD this
   file opens and closes by hand: `run_pane.subprocess.Popen` is replaced
   for the whole section, no process is created, and the gate is what
   makes "edit the form while it runs" a state rather than a race.

5. AND WHAT A READER CAN SEE. Sections 15 to 19: a line that cannot run
   shuts its button and its menu item and says why in the status bar
   instead of raising out of a Qt slot; the line in the box re-splits into
   the argv that runs, measured against the platform's own quoting rule;
   every key of `request.FIXED_PARAMETERS` is named by exactly one row of
   the form or classified there as something NovelAI shows no control for;
   nothing clips sideways at 1920, 1680, 1440 or 1366 px and the window
   fits a 1366x768 screen; and the name the save dialog suggests is one
   `save_as` accepts.

WHAT IT DOES NOT MEASURE
------------------------
It never enters an event loop and never opens a dialog (law 13:
`QT_QPA_PLATFORM=offscreen` is set before any Qt import, nothing here
calls `exec()`, and the window opens no modal by design). It never runs a
`tools.nai` subcommand: this file builds argvs and hands them to a PARSER,
and `RunPane.start` is replaced by a counter before any button is pressed.
No socket, no spend, no `data/nai/` byte -- the character directory is a
copy under a `mkdtemp` and `QSettings.setPath` puts the window's ini there
too.

THE CREDENTIAL. This file never READS it. Section 7 WRITES a decoy over
the name in this process's own environment -- which is why section 13 can
measure "nothing this window shows or saves carries the value" instead of
merely asserting, as section 5 does over the source text, that the value
is never read. Nothing is restored afterwards, because restoring would
mean having read it first.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import ast
import dataclasses
import importlib
import importlib.util
import inspect
import io
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import tokenize

if importlib.util.find_spec("PySide6") is None:
    print("SKIP  PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.nai import guard, model, recipes, spec              # noqa: E402
from tools.nai import request as nai_request                   # noqa: E402
from tools.nai.cli import build_parser                         # noqa: E402
from tools.nai import mannequin                                # noqa: E402
from tools.nai.mannequin import LAYOUTS                        # noqa: E402
from tools.nai_ui import app, character_pane, request_pane     # noqa: E402
from tools.nai_ui import run_pane, theme, widgets              # noqa: E402
import tools.nai_ui as nai_ui                                  # noqa: E402

PACKAGE_DIR = os.path.join(_bootstrap.REPO_ROOT, "tools", "nai_ui")
MODULES = {
    "__init__": nai_ui,
    "theme": theme,
    "widgets": widgets,
    "character_pane": character_pane,
    "request_pane": request_pane,
    "run_pane": run_pane,
    "app": app,
}

NEWLINE = chr(10)
"""Spelled this way so `code_only`'s own source carries no escape that a
reader could mistake for the thing it is blanking."""

failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def report(title: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {title}{' -- ' + detail if detail else ''}")


# ---------------------------------------------------------------------------
# 0. Every module and every public name carries a docstring
# ---------------------------------------------------------------------------

print("docstrings")
for name, module in MODULES.items():
    if not (module.__doc__ or "").strip():
        fail(f"tools/nai_ui/{name}.py has no module docstring")
    for attr, value in vars(module).items():
        if attr.startswith("_"):
            continue
        if not (inspect.isclass(value) or inspect.isfunction(value)):
            continue
        if getattr(value, "__module__", None) != module.__name__:
            continue
        if not (value.__doc__ or "").strip():
            fail(f"{module.__name__}.{attr} has no docstring")
        if inspect.isclass(value):
            generated = dataclasses.is_dataclass(value) or issubclass(
                value, tuple)
            for mname, member in vars(value).items():
                if mname.startswith("__") and mname != "__init__":
                    continue
                if mname == "__init__" and generated:
                    # A dataclass's and a NamedTuple's __init__ is written by
                    # the stdlib, not by us; the CLASS docstring documents it.
                    continue
                if not inspect.isfunction(member):
                    continue
                if not (member.__doc__ or "").strip():
                    fail(f"{module.__name__}.{attr}.{mname} has no docstring")
report("every module and public name is documented", not failures)


# ---------------------------------------------------------------------------
# 1. The signature table: the contract the builders implement against
# ---------------------------------------------------------------------------

SIGNATURES: tuple[tuple[str, str, str], ...] = (
    ("__init__", "launch", "(argv: 'list[str] | None' = None) -> 'int'"),
    ("theme", "apply", "(application) -> 'object'"),
    ("widgets", "quote_argv", "(parts) -> 'str'"),
    ("widgets", "NaiCommand.text", "(self) -> 'str'"),
    ("widgets", "NaiCommand.runnable", "(self) -> 'bool'"),
    ("widgets", "ColourSwatch.__init__",
     "(self, part: 'str', hex_colour: 'str', parent=None) -> 'None'"),
    ("widgets", "ColourSwatch.set_colour", "(self, hex_colour: 'str') -> 'None'"),
    ("widgets", "ColourSwatch.colour", "(self) -> 'str'"),
    ("widgets", "PositionGrid.__init__",
     "(self, x: 'float', y: 'float', *, editable: 'bool' = False, parent=None) -> 'None'"),
    ("widgets", "PositionGrid.set_center", "(self, x: 'float', y: 'float') -> 'None'"),
    ("widgets", "PositionGrid.center", "(self) -> 'tuple[float, float]'"),
    ("widgets", "LockedField.__init__",
     "(self, label: 'str', value: 'str', reason: 'str', parent=None) -> 'None'"),
    ("widgets", "LockedField.set_value", "(self, value: 'str') -> 'None'"),
    ("widgets", "CommandBox.__init__", "(self, parent=None) -> 'None'"),
    ("widgets", "CommandBox.set_command", "(self, command: 'NaiCommand') -> 'None'"),
    ("widgets", "CommandBox.command", "(self) -> 'NaiCommand | None'"),
    ("widgets", "ImageView.__init__", "(self, parent=None) -> 'None'"),
    ("widgets", "ImageView.show_png", "(self, path: 'str') -> 'None'"),
    ("widgets", "ImageView.clear", "(self) -> 'None'"),
    ("widgets", "ImageView.path", "(self) -> 'str'"),
    ("widgets", "field_row",
     "(form, label: 'str', widget, caption: 'str' = '') -> 'object'"),
    ("character_pane", "CharacterState.ok", "(self) -> 'bool'"),
    ("character_pane", "CharacterPane.__init__", "(self, parent=None) -> 'None'"),
    ("character_pane", "CharacterPane.state", "(self) -> 'CharacterState'"),
    ("character_pane", "CharacterPane.select", "(self, name: 'str') -> 'None'"),
    ("character_pane", "CharacterPane.reload", "(self) -> 'None'"),
    ("character_pane", "CharacterPane.build", "(self) -> 'str'"),
    ("character_pane", "CharacterPane.set_build", "(self, name: 'str') -> 'None'"),
    ("character_pane", "CharacterPane.edited_json", "(self) -> 'bytes'"),
    ("character_pane", "CharacterPane.problem", "(self) -> 'str'"),
    ("character_pane", "CharacterPane.save_as", "(self, name: 'str') -> 'str'"),
    ("character_pane", "CharacterPane.free_name", "(self) -> 'str'"),
    ("character_pane", "CharacterPane.drop_preview", "(self) -> 'str'"),
    ("character_pane", "CharacterPane.confirm_discard", "(self) -> 'bool'"),
    ("request_pane", "RequestPane.__init__", "(self, parent=None) -> 'None'"),
    ("request_pane", "RequestPane.command", "(self, subcommand: 'str') -> 'object'"),
    ("request_pane", "RequestPane.set_character", "(self, state: 'object') -> 'None'"),
    ("request_pane", "RequestPane.set_recipe", "(self, name: 'str') -> 'None'"),
    ("request_pane", "RequestPane.set_action", "(self, action: 'str') -> 'None'"),
    ("request_pane", "RequestPane.randomise_seed", "(self) -> 'int'"),
    ("request_pane", "RequestPane.values", "(self) -> 'dict'"),
    ("run_pane", "key_present", "() -> 'bool'"),
    ("run_pane", "RunPane.__init__", "(self, parent=None) -> 'None'"),
    ("run_pane", "RunPane.set_command", "(self, command: 'object') -> 'None'"),
    ("run_pane", "RunPane.command", "(self) -> 'object | None'"),
    ("run_pane", "RunPane.launched", "(self) -> 'object | None'"),
    ("run_pane", "RunPane.set_free_blocked", "(self, reasons: 'dict') -> 'None'"),
    ("run_pane", "RunPane.arm", "(self) -> 'None'"),
    ("run_pane", "RunPane.armed", "(self) -> 'bool'"),
    ("run_pane", "RunPane.disarm", "(self) -> 'None'"),
    ("run_pane", "RunPane.start", "(self) -> 'None'"),
    ("run_pane", "RunPane.running", "(self) -> 'bool'"),
    ("run_pane", "RunPane.interrupt", "(self) -> 'None'"),
    ("run_pane", "RunPane.text", "(self) -> 'str'"),
    ("run_pane", "RunPane.clear", "(self) -> 'None'"),
    ("run_pane", "RunPane.output_png", "(self) -> 'str'"),
    ("app", "NaiWindow.__init__", "(self, parent=None) -> 'None'"),
    ("app", "NaiWindow.compose", "(self, subcommand: 'str') -> 'object'"),
    ("app", "NaiWindow.state_root", "(self) -> 'str'"),
    ("app", "NaiWindow.locked", "(self) -> 'bool'"),
    ("app", "NaiWindow.closeEvent", "(self, event) -> 'None'"),
)

print("signatures")
before = len(failures)
for module_name, dotted, wanted in SIGNATURES:
    target = MODULES[module_name]
    try:
        for part in dotted.split("."):
            target = getattr(target, part)
    except AttributeError:
        fail(f"tools/nai_ui/{module_name}.py has no {dotted}")
        continue
    got = str(inspect.signature(target))
    if got != wanted:
        fail(f"{module_name}.{dotted} signature is {got}, the contract says "
             f"{wanted}")
report(f"{len(SIGNATURES)} signatures match the contract",
       len(failures) == before)


# ---------------------------------------------------------------------------
# 2. NAI_FIELDS is well formed
# ---------------------------------------------------------------------------

print("the NovelAI layout table")
before = len(failures)
COLUMNS = (request_pane.LEFT, request_pane.RIGHT, request_pane.COST)
STATES = (request_pane.EDITABLE, request_pane.CAPPED, request_pane.DERIVED,
          request_pane.LOCKED)
SETTABLE = (request_pane.EDITABLE, request_pane.CAPPED)
seen_labels: set[str] = set()
for row in request_pane.NAI_FIELDS:
    if not row.label.strip():
        fail("a NAI_FIELDS row has an empty label")
    if row.label in seen_labels:
        fail(f"NAI_FIELDS names {row.label!r} twice")
    seen_labels.add(row.label)
    if row.column not in COLUMNS:
        fail(f"{row.label}: column {row.column!r} is not one of {COLUMNS}")
    if row.state not in STATES:
        fail(f"{row.label}: state {row.state!r} is not one of {STATES}")
    # The rule the pane's __init__ refuses on: a locked or derived control
    # without a reason is indistinguishable from a bug, and an editable one
    # with a reason is a control that looks locked and is not.
    if row.state == request_pane.EDITABLE and row.reason:
        fail(f"{row.label} is editable but carries the reason {row.reason!r}")
    if row.state != request_pane.EDITABLE and not row.reason.strip():
        fail(f"{row.label} is {row.state} with no reason; a locked control "
             f"must say why, or a reader cannot see where free ends")
    if row.flag and row.state not in SETTABLE:
        fail(f"{row.label} is {row.state} yet writes the flag {row.flag}")
    if not row.ours.strip():
        fail(f"{row.label}: no value is stated for our pipeline")
for column in COLUMNS:
    if not any(r.column == column for r in request_pane.NAI_FIELDS):
        fail(f"NAI_FIELDS has no {column} column at all")
report(f"{len(request_pane.NAI_FIELDS)} rows, each with a column, a state "
       f"and a reason", len(failures) == before)


# ---------------------------------------------------------------------------
# 3. Every number a reason spells is `model`'s number
# ---------------------------------------------------------------------------

print("the limits, against tools.nai.model")
before = len(failures)
WALK = LAYOUTS["L5"]
def flat(text: str) -> str:
    """One space between words, so a reason that wrapped still matches."""
    return " ".join(str(text).split())


TEXT = flat(" || ".join(f"{r.label} :: {r.ours} :: {r.reason}"
                        for r in request_pane.NAI_FIELDS))

# (what the table must spell, where the number really lives). Each pair is a
# second spelling that a change to `model` would leave behind.
LIMIT_PINS: tuple[tuple[str, str], ...] = (
    (f"{model.MAX_STEPS} steps max", "model.MAX_STEPS"),
    (f"{model.DEFAULT_STEPS} by default", "model.DEFAULT_STEPS"),
    (f"{model.MAX_AREA:,} px", "model.MAX_AREA"),
    (f"{WALK.width} x {WALK.height} = {WALK.width * WALK.height:,} px",
     "mannequin.LAYOUTS['L5']"),
    (f"[{model.SEED_MIN}, {model.SEED_MAX}]", "model.SEED_MIN/SEED_MAX"),
    (f"{model.DEFAULT_STRENGTH} by default", "model.DEFAULT_STRENGTH"),
    (f"band {model.STRENGTH_BAND[0]}-{model.STRENGTH_BAND[1]}",
     "model.STRENGTH_BAND"),
    (f"{model.DEFAULT_IMG2IMG_NOISE} for img2img", "model.DEFAULT_IMG2IMG_NOISE"),
    (f"{model.DEFAULT_INFILL_NOISE} for infill", "model.DEFAULT_INFILL_NOISE"),
    (f"range {model.NOISE_RANGE[0]}-{model.NOISE_RANGE[1]}", "model.NOISE_RANGE"),
    (f"({', '.join(str(v) for v in model.GRID)})", "model.GRID"),
    (model.DEFAULT_SAMPLER, "model.DEFAULT_SAMPLER"),
    (model.DEFAULT_NOISE_SCHEDULE, "model.DEFAULT_NOISE_SCHEDULE"),
    (model.MODEL_FULL, "model.MODEL_FULL"),
    (f"{model.DEFAULT_SCALE}.0 by default", "model.DEFAULT_SCALE"),
)
for spelling, home in LIMIT_PINS:
    if flat(spelling) not in TEXT:
        fail(f"NAI_FIELDS never spells {spelling!r}, which is {home}: the "
             f"window's visible reason and the real limit have parted")
# `n_samples` is a count, not a number a sentence carries naturally, so it
# is pinned as the sentence the window shows.
if model.N_SAMPLES != 1:
    fail(f"model.N_SAMPLES is {model.N_SAMPLES}; the Number of Images row "
         f"says 'one sample'")
if "one sample" not in TEXT:
    fail("no row says 'one sample'; Number of Images must show its lock")
report(f"{len(LIMIT_PINS) + 1} limits spelled in the window match model",
       len(failures) == before)


# ---------------------------------------------------------------------------
# 4. THE LOAD-BEARING ONE: every example argv parses under the live CLI
# ---------------------------------------------------------------------------

print("the argv table, against the live tools/nai/cli.py parser")
before = len(failures)
parser = build_parser()
cli_subcommands = set()
for action in parser._subparsers._group_actions:          # noqa: SLF001
    cli_subcommands.update(action.choices)

for button, argv in request_pane.COMMAND_EXAMPLES:
    stderr = sys.stderr
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        parser.parse_args(list(argv))
    except SystemExit:
        fail(f"the {button} button's argv no longer parses: "
             f"python -m tools.nai {' '.join(argv)}")
    finally:
        sys.stderr.close()
        sys.stderr = stderr

offered = set(request_pane.OFFERED_SUBCOMMANDS)
unknown = sorted(offered - cli_subcommands)
if unknown:
    fail(f"the window offers {unknown}, which tools/nai/cli.py does not have")
sending = set(request_pane.SENDING_SUBCOMMANDS)
if not sending <= cli_subcommands:
    fail(f"SENDING_SUBCOMMANDS names {sorted(sending - cli_subcommands)}, "
         f"which the CLI does not have")
if "probe" in offered:
    fail("the window offers `probe`: only the author runs it, by hand")
if "probe" not in sending:
    fail("SENDING_SUBCOMMANDS must still NAME probe as a sender, so nothing "
         "can quietly reclassify it as free")

# THE OTHER DIRECTION, READ OFF THE CLI ITSELF. `sending <= cli_subcommands`
# proves the table names nothing the CLI lacks; it never proved the CLI has
# no sender the table lacks, and that half is the one that costs money: a
# new sending command the table misses composes with `sends` False and
# starts unarmed. So the senders are DERIVED from tools/nai/cli.py's source:
# a module-level function sends when it calls one of SOCKET_CALLS, or calls
# a module-level function that sends, and `_COMMANDS` maps each subcommand
# to its function.
SOCKET_CALLS = frozenset({"UrllibTransport", "run_request", "read_account"})


def cli_senders(source: str) -> set[str]:
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}

    def called(node) -> set[str]:
        names = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                target = sub.func
                if isinstance(target, ast.Attribute):
                    names.add(target.attr)
                elif isinstance(target, ast.Name):
                    names.add(target.id)
        return names

    calls = {name: called(node) for name, node in functions.items()}
    sends = {name for name, names in calls.items() if names & SOCKET_CALLS}
    grew = True
    while grew:
        grew = False
        for name, names in calls.items():
            if name not in sends and names & sends:
                sends.add(name)
                grew = True
    table = next(node.value for node in tree.body
                 if isinstance(node, ast.AnnAssign)
                 and isinstance(node.target, ast.Name)
                 and node.target.id == "_COMMANDS")
    return {key.value for key, value in zip(table.keys, table.values)
            if isinstance(value, ast.Name) and value.id in sends}


CLI_PATH = os.path.join(_bootstrap.REPO_ROOT, "tools", "nai", "cli.py")
with open(CLI_PATH, encoding="utf-8") as handle:
    CLI_SOURCE = handle.read()
derived = cli_senders(CLI_SOURCE)
if derived != sending:
    fail(f"tools/nai/cli.py's own sending commands are {sorted(derived)} and "
         f"SENDING_SUBCOMMANDS says {sorted(sending)}: a sender the table "
         f"misses would be composed as free and started unarmed")
# Both halves, measured on every run (law 5): a copy of the CLI with one
# more sending command, and a copy whose run-request no longer sends, must
# each disagree with the table.
GREW = CLI_SOURCE.replace(
    '_COMMANDS: dict[str, Callable[..., int]] = {',
    '_COMMANDS: dict[str, Callable[..., int]] = {\n    "decoy": _cmd_decoy,',
    1) + ("\n\ndef _cmd_decoy(args, transport, state):\n"
          "    return _send(None, transport, state, probe=False, "
          "context=None)\n")
SHRANK = CLI_SOURCE.replace(
    "    row = _send(loaded.request, transport, state, probe=False,\n"
    "                context=loaded.context)",
    "    row = {}", 1)
if GREW == CLI_SOURCE or SHRANK == CLI_SOURCE:
    fail("the sender mutations no longer match tools/nai/cli.py's text, so "
         "the derivation above is proved by nothing")
elif (cli_senders(GREW) != sending | {"decoy"}
      or cli_senders(SHRANK) != sending - {"run-request"}):
    fail(f"the sender derivation is blind: a copy of the CLI with a new "
         f"sender gives {sorted(cli_senders(GREW))}, and one whose "
         f"run-request no longer sends gives {sorted(cli_senders(SHRANK))}")

# THE TWO FORMS ARE ONE FORM. NAI_FIELDS is NovelAI's form as the recipe
# route fills it; tools.nai.spec.FORM is the same form as the request-file
# route fills it, and the Pioneer Pixel Editor draws its window from that
# one. A row here whose label or column FORM does not share is a control one
# route shows and the other forgot, or a rename that reached one table only.


def unshared(fields, form) -> list[tuple[str, str]]:
    columns = {row.label: row.column for row in form}
    return [(row.label, row.column) for row in fields
            if columns.get(row.label) != row.column]


if unshared(request_pane.NAI_FIELDS, spec.FORM):
    fail(f"NAI_FIELDS rows {unshared(request_pane.NAI_FIELDS, spec.FORM)} "
         f"have no row of the same label and column in tools.nai.spec.FORM")
RENAMED = [row._replace(label=row.label + " (renamed)") if row.label == "Seed"
           else row for row in request_pane.NAI_FIELDS]
MOVED = [row._replace(column="left") if row.label == "Steps" else row
         for row in request_pane.NAI_FIELDS]
if (unshared(RENAMED, spec.FORM) != [("Seed (renamed)", "right")]
        or unshared(MOVED, spec.FORM) != [("Steps", "left")]):
    fail("the two-form comparison is blind: a renamed Seed row or a Steps "
         "row moved to the left column went unnoticed")
example_buttons = {name.split(".")[0] for name, _ in
                   request_pane.COMMAND_EXAMPLES}
missing = sorted(offered - example_buttons)
if missing:
    fail(f"{missing} are offered with no example argv, so nothing watches "
         f"their flags")

# Every flag an editable row declares must be exercised by some example.
all_flags = {arg for _name, argv in request_pane.COMMAND_EXAMPLES
             for arg in argv if arg.startswith("--")}
for row in request_pane.NAI_FIELDS:
    if row.flag and row.flag not in all_flags:
        fail(f"{row.label} writes {row.flag}, which no example argv carries: "
             f"a renamed flag would not be caught")
report(f"{len(request_pane.COMMAND_EXAMPLES)} example argvs parse; "
       f"{len(all_flags)} flags exercised; the {len(derived)} senders read "
       f"off tools/nai/cli.py are SENDING_SUBCOMMANDS; every NovelAI row "
       f"here is a row of tools.nai.spec.FORM", len(failures) == before)


# ---------------------------------------------------------------------------
# 5. The silence: what no file in this package may contain
# ---------------------------------------------------------------------------

print("the silence")
before = len(failures)
SOURCES = {name: os.path.join(PACKAGE_DIR, f"{name}.py") for name in MODULES}
SOURCES["__main__"] = os.path.join(PACKAGE_DIR, "__main__.py")
TEXTS = {name: open(path, encoding="utf-8").read()
         for name, path in SOURCES.items()}


def code_only(text: str, path: str) -> str:
    """`text` with every comment and every DOCSTRING blanked, line numbers kept.

    The rules below are about what this package DOES, not about what it
    explains. `run_pane`'s docstring must be free to say the words "the key
    is never read here" without that sentence tripping the rule it states,
    and `app`'s must be free to name the probe flag while refusing to
    compose it. So prose is blanked to spaces -- same length, same line
    breaks, so a hit still reports its real line -- and what is left is
    code and the string literals code actually evaluates.
    """
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line))
    chars = list(text)

    def blank(start_row: int, start_col: int, end_row: int, end_col: int
              ) -> None:
        begin = starts[start_row - 1] + start_col
        stop = starts[end_row - 1] + end_col
        for i in range(begin, stop):
            if chars[i] != NEWLINE:
                chars[i] = " "

    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            blank(token.start[0], token.start[1], token.end[0], token.end[1])
    tree = ast.parse(text, path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            blank(value.lineno, value.col_offset,
                  value.end_lineno, value.end_col_offset)
    return "".join(chars)


CODE = {name: code_only(text, SOURCES[name]) for name, text in TEXTS.items()}

# The probe flag, assembled here so a grep of THIS file for the literal does
# not find it either.
PROBE_FLAG = "--accept-max-2-" + "anlas"
# A NovelAI persistent token's prefix, likewise assembled.
TOKEN_PREFIX = "pst" + "-"

BANNED: tuple[tuple[str, str, str], ...] = (
    (PROBE_FLAG, "",
     "the probe flag is typed by hand by the author; nothing composes it"),
    ("setParent(None)", "",
     "law 12: setParent(None) promotes a widget to a top-level window"),
    ('environ["NAI_KEY"]', "", "the key's VALUE is never read here"),
    ("environ.get(\"NAI_KEY\"", "", "the key's VALUE is never read here"),
    ("getenv(\"NAI_KEY\"", "", "the key's VALUE is never read here"),
    ("subprocess", "run_pane", "only run_pane starts a process"),
    ("QProcess", "run_pane", "only run_pane starts a process"),
    ("os.system", "run_pane", "only run_pane starts a process"),
    ("Popen", "run_pane", "only run_pane starts a process"),
    ("tools.nai.run", "", "the composer never imports the sending module"),
    ("tools.nai.transport", "", "the composer never imports the transport"),
    ("tools.nai.guard", "", "the guard runs in the CHILD, never here"),
    ("NAI_KEY", "run_pane",
     "only run_pane may name the key, and only to ask whether it is set"),
)
for needle, allowed, why in BANNED:
    for name, text in CODE.items():
        if allowed and name == allowed:
            continue
        if needle in text:
            line = text[:text.index(needle)].count(NEWLINE) + 1
            fail(f"tools/nai_ui/{name}.py:{line} contains {needle!r} in CODE "
                 f"-- {why}")

# The token prefix is banned in prose as well: a plausible-looking token in a
# docstring is exactly what tools/check_secrets.py exists to catch.
for name, text in TEXTS.items():
    if TOKEN_PREFIX in text:
        fail(f"tools/nai_ui/{name}.py carries a NovelAI token prefix")

# The rule has to be WRITTEN DOWN as well as obeyed, or the next author
# re-derives it: run_pane's docstring says what it does with the key.
if "NAI_KEY" not in (run_pane.__doc__ or ""):
    fail("run_pane's module docstring no longer explains what it does with "
         "NAI_KEY; the rule must be readable where it is obeyed")
if "key_present" not in (run_pane.__doc__ or ""):
    fail("run_pane's module docstring no longer names key_present as the one "
         "place the key is asked about")

# Nothing acts at import time, so every module can be imported offscreen and
# read. A bare call statement at module level is the shape that would.
for name, text in TEXTS.items():
    if name == "__main__":
        continue                       # `raise SystemExit(launch())` is its job
    for node in ast.parse(text, SOURCES[name]).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fail(f"tools/nai_ui/{name}.py:{node.lineno} calls something at "
                 f"import time; a module that acts on import cannot be "
                 f"checked offscreen (law 13)")
report(f"{len(BANNED)} forbidden spellings absent from the code of "
       f"{len(CODE)} files", len(failures) == before)


# ---------------------------------------------------------------------------
# 6. The position grid is model.GRID, not a copy of it
# ---------------------------------------------------------------------------

print("the position grid")
before = len(failures)
grid_doc = flat(widgets.PositionGrid.__doc__ or "")
if f"({', '.join(str(v) for v in model.GRID)})" not in grid_doc:
    fail("PositionGrid's docstring no longer spells model.GRID's five values")
if f"{len(model.GRID)}x{len(model.GRID)}" not in grid_doc:
    fail(f"PositionGrid's docstring no longer says "
         f"{len(model.GRID)}x{len(model.GRID)}")
for recipe_layout in LAYOUTS.values():
    for cell in recipe_layout.cells:
        if not (0 <= cell.rect_canvas[0] < recipe_layout.width):
            fail(f"{recipe_layout.name} has a cell outside its canvas; the "
                 f"grid would draw a centre that cannot exist")
report("the 5x5 grid the window draws is model.GRID", len(failures) == before)




# ---------------------------------------------------------------------------
# 7. THE WINDOW, BUILT. Everything below drives real widgets.
# ---------------------------------------------------------------------------
#
# Three things make that safe, and each is asserted rather than promised:
#
# * NOTHING IS SPAWNED. `RunPane.start` is replaced by a counter for the
#   whole of section 13, and `section_13` asserts the counter is the only
#   thing a button ever reached. No `subprocess`, no socket, no spend.
# * NOTHING OF THE AUTHOR'S IS WRITTEN. The character directory is a COPY
#   under a `mkdtemp`, and `QSettings.setPath` moves the window's ini there
#   too -- which works only because `app.settings_store` asks for an ini
#   explicitly; the platform default on Windows is the registry, where a
#   check would be writing into the author's own machine.
# * NO DIALOG IS OPENED (law 13). The window opens none at all by design,
#   and the two in `CharacterPane` are reached only from a click.

import json                                                    # noqa: E402
import shutil                                                  # noqa: E402
import tempfile                                                # noqa: E402

from PySide6.QtCore import QEvent, QSettings, Qt                # noqa: E402
from PySide6.QtCore import QThreadPool                          # noqa: E402
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication,  # noqa: E402
                               QCheckBox, QComboBox, QLabel,
                               QLineEdit,
                               QFormLayout, QPlainTextEdit, QPushButton,
                               QRadioButton, QScrollArea, QWidget)

from tools.nai import characters                               # noqa: E402

# A value shaped like nothing in particular, put into the environment under
# the credential's name BEFORE `run_pane` is asked anything. The check never
# READS the real value -- it overwrites the name in ITS OWN process, which
# is a write, not a read -- and then proves this string reaches no widget,
# no tooltip, no title, no argv and no saved file. Without a known value
# there is no way to assert the window does not leak one: "we never read it"
# is a source-text claim, and section 5 already makes that one. This is the
# behavioural half. Nothing is restored afterwards, because restoring would
# mean having read it.
KEY_NAME = "NAI" + "_KEY"
"""The credential's NAME, assembled so a grep of this file for it
finds the rule rather than a use."""

DECOY = "decoy-credential-" + "not-a-real-token-4d5e6f"
os.environ[KEY_NAME] = DECOY

SCRATCH = tempfile.mkdtemp(prefix="check_nai_ui_")
CHARACTER_DIR = os.path.join(SCRATCH, "characters")
shutil.copytree(characters.CHARACTERS_DIR, CHARACTER_DIR)
characters.CHARACTERS_DIR = CHARACTER_DIR
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                  os.path.join(SCRATCH, "settings"))

application = QApplication.instance() or QApplication(sys.argv[:1])


def build_window():
    """One window, shown off-screen, with `start` replaced by a counter."""
    window = app.NaiWindow()
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.resize(1500, 900)
    window.show()
    application.processEvents()
    return window


def settle() -> None:
    """Process pending events AND the deferred deletions.

    `processEvents` alone does not run `deleteLater`, so a pane that has
    correctly replaced its swatch rows still answers `findChildren` with
    the old ones until the event loop returns -- which, in a check, it
    never does. Without this, "the swatches follow the garments" measures
    every swatch the pane has ever built.
    """
    application.processEvents()
    application.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()


def every_widget(root):
    """`root` and every widget under it."""
    return [root] + list(root.findChildren(QWidget))


def visible_text(widget) -> str:
    """Everything `widget` could put in front of a reader or a screenshot."""
    parts = []
    for getter in ("text", "toolTip", "windowTitle", "placeholderText",
                   "statusTip", "whatsThis", "title", "styleSheet",
                   "toPlainText", "currentText"):
        method = getattr(widget, getter, None)
        if method is None:
            continue
        try:
            value = method()
        except (TypeError, RuntimeError):
            continue
        if isinstance(value, str):
            parts.append(value)
    return NEWLINE.join(parts)


print("the window builds")
before = len(failures)
window = build_window()
if window.character is None or window.request is None or window.run is None:
    fail("NaiWindow did not build all three panes")
if window.run.command() is None:
    fail("the command box is empty when the window opens; the form is "
         "supposed to have composed a line before anything is pressed")
if window.run.armed():
    fail("a send is ARMED the moment the window opens")
if window.run.running():
    fail("a child is running the moment the window opens")
# Both halves of the button table: nothing offered without a row, no row
# for anything unoffered.
if {row.subcommand for row in app.WINDOW_ACTIONS} != set(
        request_pane.OFFERED_SUBCOMMANDS):
    fail("app.WINDOW_ACTIONS and request_pane.OFFERED_SUBCOMMANDS have "
         "parted; a subcommand with no row is unreachable and a row with "
         "no subcommand raises ValueError on its first press")
for row in app.WINDOW_ACTIONS:
    if row.subcommand not in window._buttons:                  # noqa: SLF001
        fail(f"{row.subcommand} has a WINDOW_ACTIONS row and no button")
    if not row.tooltip.strip():
        fail(f"{row.subcommand}'s button carries no sentence saying what "
             f"pressing it costs")
report(f"the window and {len(app.WINDOW_ACTIONS)} command buttons build, "
       f"idle and unarmed", len(failures) == before)


# ---------------------------------------------------------------------------
# 8. The garment and subject controls ARE the live vocabulary
# ---------------------------------------------------------------------------

print("the outfit vocabulary reaches the controls")
before = len(failures)
boxes = window.character.findChildren(QComboBox)
by_choices = {}
for box in boxes:
    by_choices[tuple(box.itemText(i).split("  (")[0]
                     for i in range(box.count()))] = box


def spelled(choice) -> str:
    """How `character_pane` writes one choice into a combo."""
    return ("true" if choice is True else
            "false" if choice is False else str(choice))


for slot in model.GARMENT_SLOTS:
    wanted = tuple(spelled(c) for c in slot.choices)
    if wanted not in by_choices:
        fail(f"no control offers the {slot.name} choices {wanted}: the "
             f"garment combos are not model.GARMENT_SLOTS")
radios = [r.text() for r in window.character.findChildren(QRadioButton)]
for subject in model.SUBJECTS:
    if not any(subject.name in text for text in radios):
        fail(f"no subject control offers {subject.name!r}; model.SUBJECTS "
             f"and the radios have parted")
if len(radios) != len(model.SUBJECTS):
    fail(f"{len(radios)} subject radios for {len(model.SUBJECTS)} subjects")

# THE OTHER HALF: a slot this repository does not have must produce a
# control this window does not have -- so add one to a COPY of the
# vocabulary and watch the pane grow it. Five names have to move together,
# because `characters.py` imported `Garments` and `DEFAULT_GARMENTS` by
# name: that is the sibling route CLAUDE.md's ACTIVE WARNINGS describe, and
# a check that patched only `model` would prove nothing.
FAKE = "gloves"
real = (model.GARMENT_SLOTS, model.Garments, model.DEFAULT_GARMENTS,
        characters.Garments, characters.DEFAULT_GARMENTS)
fake_class = None
try:
    import typing
    fields = [(f, type(getattr(model.DEFAULT_GARMENTS, f)),
               getattr(model.DEFAULT_GARMENTS, f))
              for f in model.Garments._fields]
    fake_class = typing.NamedTuple(
        "Garments", [(name, kind) for name, kind, _default in fields]
        + [(FAKE, str)])
    fake_class.__new__.__defaults__ = tuple(
        [default for _n, _k, default in fields] + ["none"])
    fake_slot = model.GarmentSlot(
        FAKE, ("none", "long"), "none",
        (("none", ()), ("long", ("hair",))))
    model.GARMENT_SLOTS = real[0] + (fake_slot,)
    model.Garments = fake_class
    model.DEFAULT_GARMENTS = fake_class()
    characters.Garments = fake_class
    characters.DEFAULT_GARMENTS = fake_class()
    grown = character_pane.CharacterPane()
    grown_boxes = [tuple(b.itemText(i).split("  (")[0]
                         for i in range(b.count()))
                   for b in grown.findChildren(QComboBox)]
    if ("none", "long") not in grown_boxes:
        fail(f"a {FAKE!r} slot added to model.GARMENT_SLOTS produced no "
             f"control: the pane is not reading the live vocabulary, it is "
             f"carrying its own copy")
    grown.deleteLater()
except Exception as exc:                                       # noqa: BLE001
    fail(f"the fake-slot probe could not run: {type(exc).__name__}: {exc}")
finally:
    (model.GARMENT_SLOTS, model.Garments, model.DEFAULT_GARMENTS,
     characters.Garments, characters.DEFAULT_GARMENTS) = real
application.processEvents()
report(f"{len(model.GARMENT_SLOTS)} garment combos and "
       f"{len(model.SUBJECTS)} subject radios come from the live tables, "
       f"and a sixth slot grows a sixth combo", len(failures) == before)


# ---------------------------------------------------------------------------
# 9. The colour swatches follow the chosen garments, both ways
# ---------------------------------------------------------------------------

print("the swatches follow the garments")
before = len(failures)


def colour_rows(pane):
    """Every row of the colour form: (part, the widget beside it).

    Read off the layout rather than off `findChildren(ColourSwatch)`,
    because a part these garments DRAW and this file has never coloured
    gets the `character_pane.MISSING` note instead of a swatch -- nothing
    is invented for it (law 7). Counting swatches alone would call that
    row missing, and a window that silently dropped it would pass.
    """
    form = pane._CharacterPane__colour_layout                  # noqa: SLF001
    rows = []
    for index in range(form.rowCount()):
        label = form.itemAt(index, QFormLayout.LabelRole)
        field = form.itemAt(index, QFormLayout.FieldRole)
        if label is None or field is None:
            continue
        rows.append((label.widget().text(), field.widget()))
    return rows


def swatch_parts(pane) -> tuple[str, ...]:
    """The parts the pane is showing a colour ROW for, swatch or note."""
    return tuple(part for part, _widget in colour_rows(pane))


pane = window.character
for slot_name, choice in (("legwear", "dress"), ("legwear", "pants"),
                          ("hat", "wizard"), ("hat", "none"),
                          ("cape", True), ("cape", False)):
    pane.set_garment(slot_name, choice)
    settle()
    wanted = model.garment_parts(pane.garments())
    if pane.parts() != wanted:
        fail(f"{slot_name}={choice!r}: the pane says its parts are "
             f"{pane.parts()}, model.garment_parts says {wanted}")
    if swatch_parts(pane) != wanted:
        fail(f"{slot_name}={choice!r}: the swatches are "
             f"{swatch_parts(pane)}, the garments draw {wanted}")
# Both halves in one pair: `dress` must ADD a dress swatch and REMOVE the
# tunic and pants ones, so a pane that only ever adds is red here.
pane.set_garment("legwear", "dress")
settle()
rows = dict(colour_rows(pane))
if "dress" not in rows:
    fail("choosing a dress added no dress row")
elif not isinstance(rows["dress"], (widgets.ColourSwatch, QLabel)):
    fail(f"the dress row is a {type(rows['dress']).__name__}")
elif isinstance(rows["dress"], QLabel):
    # scout has never coloured a dress, so this is the MISSING note -- and
    # it must SAY so rather than show an invented colour.
    if character_pane.MISSING not in rows["dress"].text():
        fail(f"the uncoloured dress row says {rows['dress'].text()!r}, not "
             f"{character_pane.MISSING!r}: a colour was invented for a part "
             f"the file has never carried")
if "pants" in rows or "tunic" in rows:
    fail("choosing a dress left the tunic or pants row on screen; a colour "
         "for a part no garment draws is a file the loader refuses")
pane.set_garment("legwear", "pants")
settle()
if "dress" in dict(colour_rows(pane)):
    fail("going back to pants left the dress row behind")
report("the swatches are exactly model.garment_parts(garments), through "
       "six garment changes", len(failures) == before)


# ---------------------------------------------------------------------------
# 9b. EVERY FIELD OF THE FILE FORMAT HAS A CONTROL, and survives a round trip
# ---------------------------------------------------------------------------
# `edited_json` RAISES for a `characters.FIELDS` field this pane has no
# control for, which is law 7 working -- and it is a CONSTRUCTOR crash, so
# the window would not open at all. That is how `build` was caught, after it
# shipped. This is the same rule asserted from the other side, as a value
# the form carries in and writes back out, so a field can be added with the
# pane's own answer to it measured rather than only its absence punished.

print("every field of the file format has a control")
before = len(failures)
pane = window.character

for field in characters.FIELDS:
    if not hasattr(pane, field if field != "colours" else "colours"):
        fail(f"characters.FIELDS names {field!r} and CharacterPane has no "
             f"accessor for it")

pane.select("garet")
settle()
if pane.build() != "long":
    fail(f"garet.json says build 'long' and the form shows "
         f"{pane.build()!r}")
written = json.loads(pane.edited_json().decode("utf-8"))
if written.get("build") != "long":
    fail(f"the form would write build {written.get('build')!r} for garet, "
         f"not 'long': a field read and dropped is worse than one refused")
# The OTHER HALF: the default build writes no key at all, the way the
# default subject and the default garments do not -- so every file written
# before the field existed round-trips byte for byte.
for name in model.BUILD_NAMES:
    pane.set_build(name)
    settle()
    if pane.build() != name:
        fail(f"set_build({name!r}) left the form on {pane.build()!r}")
    doc = json.loads(pane.edited_json().decode("utf-8"))
    if name == model.DEFAULT_BUILD and "build" in doc:
        fail(f"the DEFAULT build wrote a {doc['build']!r} key; a file that "
             f"never had one would grow one")
    if name != model.DEFAULT_BUILD and doc.get("build") != name:
        fail(f"build {name!r} wrote {doc.get('build')!r}")
try:
    pane.set_build("gigantic")
    fail("set_build accepted a build that is not in model.BUILD_NAMES")
except ValueError as exc:
    if "gigantic" not in str(exc):
        fail(f"set_build's refusal does not name the value: {exc!r}")
pane.reload()
pane.select(characters.DEFAULT_CHARACTER)
settle()
if pane.build() != model.DEFAULT_BUILD:
    fail(f"the default character shows build {pane.build()!r}")
report("every characters.FIELDS field has a control; garet's build survives "
       "the form, the default build writes no key, and an unknown one is "
       "refused by name", len(failures) == before)


# ---------------------------------------------------------------------------
# 9c. THE WINDOW DRAWS THE CHARACTER'S OWN BUILD, on every recipe
# ---------------------------------------------------------------------------
# `mannequin.render_init` takes a build and both calls in this package left
# it at the default, so the composer drew a DIFFERENT FIGURE from the one
# `nai render` would send -- and on `jump` it did not draw at all: the
# placement raised, `_refresh_derived` swallowed it, and the pane reported
# the CHARACTER FILE as refused, which it is not. cli.py, recipes.make_request
# and recipes.context_for all got the build; the two calls one directory up
# did not. That is CLAUDE.md's sibling-route ACTIVE WARNING exactly, so the
# assertion is over EVERY recipe rather than the one that was noticed.

print("the window draws the character's own build")
before = len(failures)

drawn_on = []
real_render_init = mannequin.render_init


def watched_render_init(*args, **kwargs):
    """Record the build every call in this package asks for."""
    drawn_on.append(kwargs.get("build_name", model.DEFAULT_BUILD))
    return real_render_init(*args, **kwargs)


GARET = characters.load("garet")
if GARET.build == model.DEFAULT_BUILD:
    fail("garet.json no longer names a non-default build, so this section "
         "measures nothing; point it at a character that does")
mannequin.render_init = watched_render_init
try:
    # The request pane's own path, on the GUI thread: selecting a character
    # and a recipe rebuilds its derived rows through `render_init`.
    window.character.select("garet")
    settle()
    for recipe_name in recipes.RECIPE_NAMES:
        window.request.set_recipe(recipe_name)
        settle()
        composed = window.compose("plan")
        if not composed.runnable():
            fail(f"garet on {recipe_name} is blocked in the composer: "
                 f"{composed.blocked!r} -- his file loads, so this is the "
                 f"window failing to draw him")
    if not drawn_on:
        fail("selecting a character and three recipes drew no init at all; "
             "this section is watching a call nothing makes")
    # The character pane's own path, run straight rather than through the
    # thread pool, so the check never waits on a worker.
    signals = character_pane._PreviewSignals(window.character)
    for recipe_name in recipes.RECIPE_NAMES:
        out = os.path.join(SCRATCH, f"preview_{recipe_name}.png")
        character_pane._PreviewTask(signals, 1, GARET, recipe_name,
                                    out).run()
        if not os.path.isfile(out):
            fail(f"the pane's own preview task drew nothing for "
                 f"{recipe_name}")
        else:
            sent = recipes.make_request(recipe_name, "img2img", 1234567890,
                                        character="garet").image_png
            with open(out, "rb") as handle:
                if handle.read() != sent:
                    fail(f"the composer's {recipe_name} preview is NOT the "
                         f"image `nai render` would send: the window is "
                         f"showing a different figure from the one it is "
                         f"about to pay for")
            os.remove(out)
finally:
    mannequin.render_init = real_render_init
window.request.set_recipe("walk")
window.character.select(characters.DEFAULT_CHARACTER)
settle()
wrong = sorted({name for name in drawn_on if name != GARET.build})
if wrong:
    fail(f"this package drew garet on {wrong}; his file says "
         f"{GARET.build!r}. `mannequin.render_init` takes a build and every "
         f"call that leaves it out draws a different man -- on `jump` it "
         f"used not to draw at all, and the pane reported his FILE as "
         f"refused, which it is not")
report(f"every one of the {len(drawn_on)} inits this window draws for garet "
       f"is drawn on the build his file names, and the composer's preview "
       f"is byte for byte the image the tool would send",
       len(failures) == before)


# ---------------------------------------------------------------------------
# 10. An illegal character file shows the LOADER'S OWN message, and cannot
#     be saved
# ---------------------------------------------------------------------------

print("an illegal character file")
before = len(failures)
BAD = "check_illegal_outfit"
bad_path = os.path.join(CHARACTER_DIR, f"{BAD}.json")
# Legal JSON, illegal character: a colour for a part these garments do not
# draw. The loader names the field; the window must not invent a sentence
# of its own, and must not let a command run against it.
good = json.loads(open(os.path.join(CHARACTER_DIR, "scout.json"),
                       encoding="utf-8").read())
good["colours"]["dress"] = "#C83232"
open(bad_path, "w", encoding="utf-8").write(json.dumps(good, indent=2))

loader_said = ""
try:
    characters.load(BAD)
    fail(f"{BAD}.json was built to be refused and the loader accepted it; "
         f"this whole section is then vacuous")
except ValueError as exc:
    loader_said = str(exc)

window.character.reload()
window.character.select(BAD)
settle()
state = window.character.state()
if state.ok():
    fail("the pane says an illegal character file is fine")
if state.problem != loader_said:
    fail(f"the pane shows its own sentence, not the loader's."
         f"{NEWLINE}    loader: {loader_said}"
         f"{NEWLINE}    pane:   {state.problem}")
if not any(loader_said in visible_text(w) for w in every_widget(window)):
    fail("the loader's own message is nowhere on screen; a reader is told "
         "something is wrong and not what")

# Every command that NAMES a character is blocked by it, with that same
# sentence. `account` and `ledger` name none, so they are not -- and the
# two lists are read off `request_pane` rather than spelled again here.
for subcommand in request_pane.OFFERED_SUBCOMMANDS:
    command = window.compose(subcommand)
    names_character = "--character" in command.argv
    if names_character and command.runnable():
        fail(f"`{subcommand}` names --character and is runnable with a "
             f"character file the loader refuses")
    if names_character and loader_said not in command.blocked:
        fail(f"`{subcommand}`'s blocked reason is {command.blocked!r}, not "
             f"the loader's own message")
    if not names_character and loader_said in command.blocked:
        fail(f"`{subcommand}` carries no --character and is blocked by a "
             f"character refusal anyway")

# THE OTHER HALF: a legal file blocks nothing, or the rule above would pass
# on a window that blocks everything always.
window.character.select(characters.DEFAULT_CHARACTER)
settle()
legal = window.compose("plan")
if not legal.runnable():
    fail(f"a legal character file is blocked too: {legal.blocked!r}")

# AND IT CANNOT BE SAVED. The fixture above is one the pane REPAIRS on the
# way out -- `edited_json` writes a colour for each part the garments
# actually draw -- so saving it is right, and measuring "cannot be saved"
# with it would measure nothing. An edit the pane cannot repair does it:
# an anchor tag that is not verbatim a tag of Tags.
window.character.set_anchor("a tag that is not in tags")
settle()
edit_refusal = window.character.problem()
if not edit_refusal:
    fail("an anchor tag that is not in Tags was not refused; the loader "
         "and this pane disagree, or the fixture has stopped being illegal")
try:
    window.character.save_as(BAD + "_copy")
    fail("a character the loader refuses was saved under a new name")
except ValueError as exc:
    if edit_refusal not in str(exc):
        fail(f"the save refusal is {exc!r}, not the loader's sentence "
             f"{edit_refusal!r}")
if os.path.exists(os.path.join(CHARACTER_DIR, f"{BAD}_copy.json")):
    fail("the refused save wrote the file anyway")
# The other half again: repair the edit and the same save succeeds.
window.character.reload()
settle()
if window.character.problem():
    fail(f"a re-read of the shipped character is refused: "
         f"{window.character.problem()!r}")
saved_path = window.character.save_as(BAD + "_copy")
if not os.path.isfile(saved_path):
    fail(f"a legal save wrote nothing to {saved_path}")
characters.load(BAD + "_copy")          # ValueError here fails the check
os.remove(bad_path)
os.remove(saved_path)
window.character.reload()
window.character.select(characters.DEFAULT_CHARACTER)
settle()
report("a refused file shows the loader's sentence and blocks every "
       "command that names a character; a refused EDIT cannot be saved; a "
       "legal one is neither", len(failures) == before)


# ---------------------------------------------------------------------------
# 11. The composed argv is what the LIVE CLI parses, value for value
# ---------------------------------------------------------------------------

print("the composed argv, against the live parser")
before = len(failures)
window.request.set_recipe("run")
window.request.set_action("img2img")
seed = window.request.randomise_seed()
window.request._steps_spin.setValue(17)                        # noqa: SLF001
window.request._scale_spin.setValue(6.5)                       # noqa: SLF001
settle()

WANTED = {"recipe": "run", "action": "img2img", "steps": 17,
          "scale": 6.5, "seed": seed,
          "character": characters.DEFAULT_CHARACTER}
composed = window.compose("plan")
stderr = sys.stderr
sys.stderr = open(os.devnull, "w", encoding="utf-8")
try:
    parsed = parser.parse_args(list(composed.argv[3:]))
except SystemExit:
    parsed = None
    fail(f"the line this window is SHOWING does not parse: "
         f"{' '.join(composed.argv[3:])}")
finally:
    sys.stderr.close()
    sys.stderr = stderr
if parsed is not None:
    for name, value in WANTED.items():
        got = getattr(parsed, name, None)
        if got != value:
            fail(f"the form says {name}={value!r} and the CLI parses "
                 f"{name}={got!r} out of the line the window shows: the "
                 f"window and the tool have drifted")
    # The other half: a value the form does NOT hold must not appear. A
    # default is never spelled, so --steps back at its default leaves the
    # flag out entirely.
    window.request._steps_spin.setValue(model.DEFAULT_STEPS)   # noqa: SLF001
    application.processEvents()
    plain = window.compose("plan")
    if "--steps" in plain.argv:
        fail("--steps is spelled out at its own default; the line stops "
             "being the line a human would type")
window.request.set_action("generate")
window.request.set_recipe("walk")
application.processEvents()
report(f"{len(WANTED)} values survive the round trip through the live "
       f"parser, and a default is not spelled", len(failures) == before)


# ---------------------------------------------------------------------------
# 12. A locked control cannot be edited into an illegal value
# ---------------------------------------------------------------------------

print("the locked controls")
before = len(failures)
INPUTS = (QLineEdit, QAbstractSpinBox, QComboBox, QCheckBox)
locked_fields = window.request.findChildren(widgets.LockedField)
if not locked_fields:
    fail("no LockedField in the request pane at all; the rows the guard "
         "forbids are supposed to be SHOWN and locked, never hidden")
for field in locked_fields:
    editable = [kid for kind in INPUTS for kid in field.findChildren(kind)]
    if editable:
        fail(f"the locked row {field.value()!r} contains "
             f"{[type(k).__name__ for k in editable]}: a lock a user can "
             f"type into is not a lock")
    if not field.reason().strip():
        fail(f"the locked row {field.value()!r} carries no reason; a reader "
             f"cannot see where free ends")
# CAPPED is the other shape: a control that IS editable, up to the cap.
steps = window.request._steps_spin                             # noqa: SLF001
if steps.maximum() != model.MAX_STEPS:
    fail(f"the Steps spinner stops at {steps.maximum()}, and the free tier "
         f"stops at model.MAX_STEPS = {model.MAX_STEPS}")
steps.setValue(model.MAX_STEPS + 7)
if steps.value() != model.MAX_STEPS:
    fail(f"Steps accepted {steps.value()}, past the free tier's "
         f"{model.MAX_STEPS}")
steps.setValue(model.MAX_STEPS - 1)
if steps.value() != model.MAX_STEPS - 1:
    fail("Steps refuses a value inside the free tier; the cap has become a "
         "constant and the control is useless")
steps.setValue(model.DEFAULT_STEPS)
application.processEvents()
report(f"{len(locked_fields)} locked rows hold no input, and the capped "
       f"one clamps at model.MAX_STEPS", len(failures) == before)


# ---------------------------------------------------------------------------
# 13. THE MONEY ONES
# ---------------------------------------------------------------------------

print("the money rules")
before = len(failures)

# -- the credential reaches nothing --------------------------------------
window.compose("run")
application.processEvents()
for widget in every_widget(window):
    if DECOY in visible_text(widget):
        fail(f"{type(widget).__name__} is showing the credential's VALUE")
for subcommand in request_pane.OFFERED_SUBCOMMANDS:
    if any(DECOY in str(token) for token in window.compose(subcommand).argv):
        fail(f"the {subcommand} argv carries the credential's value")
window.run.set_command(window.compose("plan"))
if DECOY in window.run.text():
    fail("the output view carries the credential's value")


class _Event:
    """Stands in for a QCloseEvent, so closeEvent can be driven."""

    def __init__(self) -> None:
        self.accepted = None

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


window.closeEvent(_Event())            # writes the store
ini = app.settings_store().fileName()
saved = open(ini, encoding="utf-8", errors="replace").read() if (
    os.path.exists(ini)) else ""
if not saved:
    fail(f"the window saved nothing to {ini}; the 'no credential in the "
         f"saved file' rule would then be vacuous")
if DECOY in saved:
    fail(f"{ini} carries the credential's value")
for key in QSettings(QSettings.IniFormat, QSettings.UserScope,
                     app.SETTINGS_ORGANISATION,
                     app.SETTINGS_APPLICATION).allKeys():
    if key not in app.SAVED_KEYS:
        fail(f"the store holds {key!r}, which is not in app.SAVED_KEYS")
try:
    window._remember("api_key", DECOY)                         # noqa: SLF001
    fail("_remember wrote a key outside SAVED_KEYS")
except ValueError:
    pass

# The OTHER half of "the window knows only whether it is set".
if not run_pane.key_present():
    fail("key_present() is False with the name set in this process")
del os.environ[KEY_NAME]
if run_pane.key_present():
    fail("key_present() is True with the name removed")
os.environ[KEY_NAME] = DECOY

# -- the send control ------------------------------------------------------
starts: list[object] = []
window.run.start = lambda: starts.append(window.run.command())

sending = window.compose("run")
if not sending.sends:
    fail("`run` composed a command that says it opens no socket")
try:
    window.run.arm()
    fail("a send ARMED with no dry run behind it at all")
except RuntimeError:
    pass

# A green dry run of THIS request is what opens the arm. `_cleared` is the
# private the child's exit code sets; setting it here is the check standing
# in for a `plan` it is not allowed to run.
window.run._cleared = run_pane.request_key(sending.argv)       # noqa: SLF001
try:
    window.run.arm()
except RuntimeError as exc:
    fail(f"a send with a green dry run of its own request refused to arm: "
         f"{exc}")
if not window.run.armed():
    fail("arm() returned and the pane is not armed")

# ANY change drops it. Each of these is a different route to set_command.
for label, change in (
        ("a seed", lambda: window.request.randomise_seed()),
        ("a recipe", lambda: window.request.set_recipe("jump")),
        ("an action", lambda: window.request.set_action("img2img")),
        ("a character", lambda: window.character.select(
            characters.available()[-1])),
        ("a steps value", lambda: window.request._steps_spin.setValue(  # noqa: SLF001
            model.DEFAULT_STEPS - 1))):
    window.run.set_command(window.compose("run"))
    window.run._cleared = run_pane.request_key(                # noqa: SLF001
        window.run.command().argv)
    window.run.arm()
    if not window.run.armed():
        fail(f"could not re-arm before testing {label}")
    change()
    application.processEvents()
    if window.run.armed():
        fail(f"{label} changed and the send was STILL armed; an edited "
             f"line is a different request")

# A blocked or non-sending command is never armed, and `start` refuses an
# unarmed sender. `start` is the real method again for these three.
window.run.start = RunPane_start = run_pane.RunPane.start.__get__(window.run)
window.run.set_command(window.compose("run"))
try:
    window.run.start()
    fail("start() ran an unarmed sending command")
except RuntimeError:
    pass
window.run.start = lambda: starts.append(window.run.command())

# -- one press is never one request ---------------------------------------
#
# Pointed at a state root with NO LOCK first. MEASURED, by mutation: this
# checkout HAS a data/nai/LOCK, and with one present `_press` returns at
# the LOCK branch before it ever reaches the send guard -- so "a sending
# press started nothing" passed on a window whose send guard had been
# deleted. An assertion that cannot fail is not an assertion (law 5).
UNLOCKED_ROOT = os.path.join(SCRATCH, "state")
os.makedirs(UNLOCKED_ROOT, exist_ok=True)
LOCK_FIXTURE = os.path.join(UNLOCKED_ROOT, app.nai_state.LOCK_NAME)
real_default_root = app.nai_state.default_root
app.nai_state.default_root = lambda: UNLOCKED_ROOT
window._refresh_chrome()                                       # noqa: SLF001
if window.locked():
    fail(f"{UNLOCKED_ROOT} was meant to have no LOCK and this window says "
         f"it does; every press assertion below would be vacuous")
starts.clear()
for row in app.WINDOW_ACTIONS:
    if row.subcommand not in request_pane.SENDING_SUBCOMMANDS:
        continue
    window._press(row.subcommand)                              # noqa: SLF001
    application.processEvents()
    if starts:
        fail(f"pressing {row.subcommand!r} started "
             f"{[' '.join(c.argv[3:]) for c in starts]}: one press must "
             f"never reach a socket")
        starts.clear()
    if window.run.armed():
        fail(f"pressing {row.subcommand!r} armed the send by itself")

# THE OTHER HALF: a free press must actually run, exactly once, or the rule
# above is satisfied by a window whose buttons do nothing. `pixelize` is
# blocked with no strip named -- that is section 14's subject -- so it is
# given one here, or this assertion would measure a refusal and call it a
# button that works.
STRIP_FIXTURE = os.path.join(SCRATCH, "strip.png")
open(STRIP_FIXTURE, "wb").write(b"not a png, only a file that exists")
window.request._strip_edit.setText(STRIP_FIXTURE)             # noqa: SLF001
application.processEvents()
for row in app.WINDOW_ACTIONS:
    if row.subcommand in request_pane.SENDING_SUBCOMMANDS:
        continue
    starts.clear()
    window._press(row.subcommand)                              # noqa: SLF001
    application.processEvents()
    if len(starts) != 1:
        fail(f"pressing {row.subcommand!r} started {len(starts)} commands; "
             f"a free button runs its line once")
    elif run_pane.subcommand_of(starts[0].argv) != row.subcommand:
        fail(f"pressing {row.subcommand!r} started "
             f"{run_pane.subcommand_of(starts[0].argv)!r}")

# And nothing starts a second child. `running()` is what the window asks.
window.run.running = lambda: True
starts.clear()
window._press("plan")                                          # noqa: SLF001
if starts:
    fail("a second command was started while a child was still running")
window.run.running = run_pane.RunPane.running.__get__(window.run)

# THE OTHER HALF OF THE LOCK BRANCH: with a LOCK in that root, every
# sending control is shut and composes nothing, and every free one is
# untouched.
open(LOCK_FIXTURE, "w", encoding="utf-8").write("a check fixture")
window._refresh_chrome()                                       # noqa: SLF001
if not window.locked():
    fail(f"a LOCK file in {UNLOCKED_ROOT} and the window says nothing is "
         f"locked")
for row in app.WINDOW_ACTIONS:
    button = window._buttons[row.subcommand]                   # noqa: SLF001
    sending = row.subcommand in request_pane.SENDING_SUBCOMMANDS
    if sending and button.isEnabled():
        fail(f"LOCK is present and the {row.subcommand!r} button is still "
             f"live; the guard in the child would refuse it anyway, and a "
             f"button that looks live and is not teaches the wrong thing")
    if not sending and not button.isEnabled():
        fail(f"LOCK is present and the free {row.subcommand!r} button was "
             f"disabled too; LOCK stops sending, not working")
    if sending and app.LOCK_REASON not in button.toolTip():
        fail(f"the shut {row.subcommand!r} button does not say why")
starts.clear()
shown_before = window.run.command()
for row in app.WINDOW_ACTIONS:
    if row.subcommand not in request_pane.SENDING_SUBCOMMANDS:
        continue
    window._press(row.subcommand)                              # noqa: SLF001
if starts:
    fail("a sending press started something while LOCK was present")
if window.run.command() is not shown_before:
    fail("a sending press under LOCK composed a line anyway")
os.remove(LOCK_FIXTURE)
app.nai_state.default_root = real_default_root
window._refresh_chrome()                                       # noqa: SLF001

# A pane's own button may only ask for something that opens no socket.
for subcommand in request_pane.SENDING_SUBCOMMANDS:
    try:
        window.run._ask(subcommand)                            # noqa: SLF001
        fail(f"RunPane's own buttons were able to ask for {subcommand!r}")
    except RuntimeError:
        pass
report("the send arms only behind a green dry run of its own request, "
       "drops on any change, and no press of any button reached a socket",
       len(failures) == before)


# ---------------------------------------------------------------------------
# 14. THE CLEARANCE DESCRIBES THE CHILD, NOT THE BOX
# ---------------------------------------------------------------------------
#
# Section 13 sets `_cleared` BY HAND, because it may not run a `plan`. That
# stands in for the only code that ever sets it in production -- `_finished`
# -- and an assertion that stands in for the code it covers cannot fail the
# way the code does. It did not: `_finished` read `self._command`, the line
# in the BOX, which follows the form while a child runs. So one nudge of the
# Steps spinner during a `render` made the render's exit 0 record a plan
# clearance for a request no dry run had ever judged, and SEND went live
# over an EMPTY verdict list.
#
# This section drives `_finished` for real, with a fake child that this
# check controls -- no `tools.nai` subcommand runs, and `Popen` is replaced
# for the whole section.

print("the clearance is the child's, not the box's")
before = len(failures)


class _FakeChild:
    """A child process this check opens and closes by hand.

    Serves as its own `stdout`: `RunPane._pump` iterates it, closes it and
    calls `wait()`. The iterator BLOCKS on `gate` after its last line, so
    the window is genuinely mid-run while the form is edited, which is the
    state the defect needed. Nothing is executed; this replaces
    `run_pane.subprocess.Popen` and no process is created at all.
    """

    def __init__(self, lines, code):
        """Say `lines`, then wait for `release()`, then exit with `code`."""
        self.__lines = list(lines)
        self.__code = int(code)
        self.gate = threading.Event()
        self.stdout = self

    def __iter__(self):
        """Every line, then block until the check lets the child exit."""
        for line in self.__lines:
            yield line
        self.gate.wait(20)

    def close(self):
        """`_pump` closes the stream; there is nothing to close."""

    def wait(self):
        """The exit code this child was built with."""
        return self.__code

    def terminate(self):
        """`interrupt` calls this; releasing the gate is the whole of it."""
        self.gate.set()

    def release(self):
        """Let the child exit."""
        self.gate.set()


spawned: list[tuple] = []
child_box: list[_FakeChild] = []


def fake_popen(argv, **_kwargs):
    """Stand in for `subprocess.Popen`: record the argv, start nothing."""
    spawned.append(tuple(argv))
    child = _FakeChild(FAKE_LINES[0], FAKE_CODE[0])
    child_box.append(child)
    return child


FAKE_LINES = [()]
FAKE_CODE = [0]
real_popen = run_pane.subprocess.Popen
run_pane.subprocess.Popen = fake_popen
window.run.start = RunPane_start
window.run.clear()
window.request.set_action("generate")
window.request.randomise_seed()
application.processEvents()


def finish_child(gate_wait=8.0):
    """Let the running child exit and pump Qt until the pane says idle."""
    child_box[-1].release()
    deadline = time.time() + gate_wait
    while window.run.running() and time.time() < deadline:
        application.processEvents()
        time.sleep(0.005)
    application.processEvents()


# THE POSITIVE HALF FIRST, or the negative one below is satisfied by a pane
# that never clears anything: a `plan` that exits 0 DOES clear its own line.
PLAN_OK = ("  1 [ ok ] action is generate\n", "verdict       would send\n")
FAKE_LINES[0], FAKE_CODE[0] = PLAN_OK, 0
planned = window.compose("plan")
window.run.start()
finish_child()
if window.run._cleared != run_pane.request_key(planned.argv):   # noqa: SLF001
    fail(f"a green `plan` of this very line did not clear it: "
         f"_cleared is {window.run._cleared!r}")                # noqa: SLF001
sending = window.compose("run")
try:
    window.run.arm()
except RuntimeError as exc:
    fail(f"the send refused to arm behind its own green dry run: {exc}")
window.run.disarm()

# AND THE DEFECT. Run something FREE, edit the form while it runs so the
# box holds a `plan` line, and let the free child exit 0. Nothing about
# that exit code judged the plan line, so nothing may be cleared by it.
window.run.clear()
FAKE_LINES[0], FAKE_CODE[0] = ("render        out.png\n",), 0
rendered = window.compose("render")
window.run.start()
if not window.run.running():
    fail("the fake child exited before the form could be edited; the "
         "swap-mid-run assertion below would be vacuous")
if window.run.launched() is not rendered:
    fail("RunPane.launched() is not the command that was started")
window.request._steps_spin.setValue(model.DEFAULT_STEPS - 2)   # noqa: SLF001
application.processEvents()
if run_pane.subcommand_of(window.run.command().argv) != "plan":
    fail("the edit did not swap the box onto a `plan` line; the "
         "swap-mid-run assertion below would be vacuous")
finish_child()
if window.run._cleared is not None:                            # noqa: SLF001
    fail(f"a `render` that exited 0 recorded the clearance "
         f"{window.run._cleared!r} for a `plan` line that never ran -- "    # noqa: SLF001
         f"children actually spawned: "
         f"{[run_pane.subcommand_of(a) for a in spawned]}")
if window.run.launched() is not None:
    fail("the launched command outlived the child that parsed it")
window.run.set_command(window.compose("run"))
if window.run._arm_button.isEnabled():                         # noqa: SLF001
    fail("the Arm button is live over an uncleared `run`: `arm()` would "
         "refuse it, and a button the guard would refuse must not be live")
try:
    window.run.arm()
    fail("a send armed on a clearance no dry run had granted")
except RuntimeError:
    pass
# And the checklist the arm would have been granted on is what a reader
# reads: it must be empty here, not merely refused.
if window.run._conditions.count():                             # noqa: SLF001
    fail("the guard-condition checklist is not empty after a `render`")

# A SENDING command that finishes drops the clearance, both directions.
window.run.clear()
FAKE_LINES[0], FAKE_CODE[0] = PLAN_OK, 0
planned = window.compose("plan")
window.run.start()
finish_child()
if window.run._cleared is None:                                # noqa: SLF001
    fail("the second green plan cleared nothing")
FAKE_LINES[0], FAKE_CODE[0] = ("output        strip.png\n",), 0
window.run.set_command(window.compose("run"))
window.run._cleared = run_pane.request_key(                    # noqa: SLF001
    window.run.command().argv)
window.run.arm()
window.run.start()
finish_child()
if window.run._cleared is not None:                            # noqa: SLF001
    fail("a finished SEND left its clearance behind; one dry run would pay "
         "for two requests")
if not spawned:
    fail("this section started no child at all and measured nothing")

run_pane.subprocess.Popen = real_popen
window.run.clear()
window.run.start = lambda: starts.append(window.run.command())
report(f"the clearance is set by the argv the CHILD parsed, through "
       f"{len(spawned)} driven children, and an edit mid-run clears "
       f"nothing", len(failures) == before)


# ---------------------------------------------------------------------------
# 15. A BLOCKED LINE IS SHUT AND EXPLAINED, NEVER THROWN
# ---------------------------------------------------------------------------
#
# `RunPane.start` raises `RuntimeError(command.blocked)` -- that is its
# contract. A Qt SLOT that lets that out prints a traceback to a terminal a
# window launched from a shortcut does not have, and the press looks like a
# button that does nothing. The rule was applied to `run` and to the three
# senders and NOT to the four free routes, which is the sibling shape
# CLAUDE.md's ACTIVE WARNINGS name.

print("a blocked line")
before = len(failures)
# Pointed at the root with NO LOCK, so a sending button that is shut is
# shut for the reason THIS section is about. This checkout has a real
# data/nai/LOCK, and under it every sender is shut whatever its line says
# -- which is section 13's subject, and would make the loop below read
# "shut" for three buttons it never tested.
app.nai_state.default_root = lambda: UNLOCKED_ROOT
window.request._strip_edit.setText("")                         # noqa: SLF001
application.processEvents()
window._refresh_chrome()                                       # noqa: SLF001
blocked_now = window._blocked_reasons()                        # noqa: SLF001
if not blocked_now.get("pixelize"):
    fail("with no strip named, `pixelize` composed a runnable line; every "
         "assertion below would be vacuous")
for name, why in blocked_now.items():
    button = window._buttons.get(name)                         # noqa: SLF001
    action = window._actions.get(name)                         # noqa: SLF001
    if button is None:
        continue
    if why and button.isEnabled():
        fail(f"the {name!r} button is live over a line that cannot run: "
             f"{why}")
    if why and why not in button.toolTip():
        fail(f"the shut {name!r} button does not carry its reason")
    if why and action is not None and action.isEnabled():
        fail(f"the {name!r} MENU ITEM is live over a line that cannot run; "
             f"the button was shut and its sibling was not")
    if not why and not button.isEnabled():
        fail(f"the {name!r} button is shut and its line can run")
# The run pane's own three buttons are the OTHER route to the same lines.
for name in run_pane.NO_NETWORK_BUTTONS:
    button = {"plan": window.run._plan_button,                 # noqa: SLF001
              "pixelize": window.run._pixelize_button,         # noqa: SLF001
              "ledger": window.run._ledger_button}[name]       # noqa: SLF001
    if blocked_now.get(name) and button.isEnabled():
        fail(f"the run pane's own {name!r} button is live over a line that "
             f"cannot run")
    if not blocked_now.get(name) and not button.isEnabled():
        fail(f"the run pane's own {name!r} button is shut and its line runs")
try:
    window.run.set_free_blocked({"run": "nonsense"})
    fail("set_free_blocked accepted a subcommand this pane has no button "
         "for; the reason would shut nothing")
except KeyError:
    pass

# AND THE PRESS ITSELF: a refusal reaches the status bar, and nothing runs.
starts.clear()
window.statusBar().clearMessage()
try:
    window._press("pixelize")                                  # noqa: SLF001
except RuntimeError as exc:
    fail(f"a blocked press raised out of the slot instead of reporting: "
         f"{exc}")
application.processEvents()
if starts:
    fail("a blocked press started a command anyway")
if blocked_now["pixelize"] not in window.statusBar().currentMessage():
    fail(f"a blocked press said {window.statusBar().currentMessage()!r} "
         f"instead of the reason {blocked_now['pixelize']!r}")
# THE OTHER HALF: name a strip and the same press runs, once.
window.request._strip_edit.setText(STRIP_FIXTURE)              # noqa: SLF001
application.processEvents()
window._refresh_chrome()                                       # noqa: SLF001
if not window._buttons["pixelize"].isEnabled():                # noqa: SLF001
    fail("a runnable `pixelize` line and the button is still shut")
starts.clear()
window._press("pixelize")                                      # noqa: SLF001
application.processEvents()
if len(starts) != 1:
    fail(f"a runnable `pixelize` press started {len(starts)} commands")
# AND THE SHUT STATE FOLLOWS THE FORM, not the last press. No
# `_refresh_chrome` here on purpose: switching the action is an edit, and
# the edit alone must re-ask which lines can run, or every button carries
# the verdict the form had when something was last pressed.
window.request.set_action("infill")
application.processEvents()
if window._buttons["plan"].isEnabled():                        # noqa: SLF001
    fail("the action is infill -- `plan` takes only generate and img2img "
         "-- and the Dry run button is still live; the shut state did not "
         "follow the edit")
if not window._buttons["infill"].isEnabled():                  # noqa: SLF001
    infill_why = window._blocked_reasons()["infill"]           # noqa: SLF001
    if not infill_why:
        fail("the action is infill and the Infill button is shut with no "
             "reason at all")
window.request.set_action("generate")
application.processEvents()
if not window._buttons["plan"].isEnabled():                    # noqa: SLF001
    fail("back on generate and `plan` is still shut; the gate latched")
app.nai_state.default_root = real_default_root
window._refresh_chrome()                                       # noqa: SLF001
report("a line that cannot run shuts its button and its menu item, says "
       "why in the status bar, and starts nothing -- and a line that can "
       "still runs once", len(failures) == before)


# ---------------------------------------------------------------------------
# 16. THE LINE SHOWN RE-SPLITS INTO THE ARGV THAT RUNS
# ---------------------------------------------------------------------------
#
# `--phase`, `--lever`, `--from` and the strip path are free text. The box
# used to wrap an argument holding a space in a bare pair of double quotes
# and escape nothing, so `x" --steps 99 "y` rendered as a line carrying a
# `--steps 99` that NO argv element contained. The box is the promise this
# window rests on, and the Copy button hands that text to a shell.
#
# The oracle is `subprocess.list2cmdline`, which is what Windows itself
# uses to build the command line `CommandLineToArgvW` parses -- two
# independent spellings of one rule, so a mutation to either is named.

print("the command line re-splits into the argv")
before = len(failures)
CRAFTED: tuple[tuple[str, ...], ...] = (
    ("py", "--phase", 'x" --steps 99 "y', "--lever", "a b"),
    ("py", "--lever", 'he said "hi"', "--phase", ""),
    ("py", "--from", r"C:\a b\c\\", "--phase", r"trailing\\"),
    ("py", "--phase", "tab\there", "--lever", 'quote"and space'),
    ("py", "plain", "--phase", "simple"),
)
for parts in CRAFTED:
    rendered = widgets.quote_argv(parts)
    if os.name == "nt":
        if rendered != subprocess.list2cmdline(parts):
            fail(f"quote_argv({parts!r}) rendered {rendered!r}; Windows's "
                 f"own rule is {subprocess.list2cmdline(parts)!r}")
    else:
        if shlex.split(rendered) != list(parts):
            fail(f"quote_argv({parts!r}) rendered {rendered!r}, which "
                 f"re-splits to {shlex.split(rendered)!r}")

# And through the real window: the composed line must be that rendering,
# and the naive one -- a bare pair of quotes round anything with a space --
# must be a DIFFERENT string, or this assertion has no teeth.
window.request._phase_edit.setText('x" --steps 99 "y')         # noqa: SLF001
window.request._lever_edit.setText("a b")                      # noqa: SLF001
application.processEvents()
# `run` is the subcommand that carries `--phase` and `--lever` (they are
# `LEDGER_FLAGS`, and `plan` writes none of them). Composing it starts
# nothing: `compose` builds an argv and shows it.
crafted = window.compose("run")
if crafted.text() != widgets.quote_argv(
        (os.path.relpath(crafted.argv[0], crafted.cwd).replace(os.sep, "/"),)
        + tuple(crafted.argv[1:])):
    fail(f"the command box is not quote_argv's rendering: "
         f"{crafted.text()!r}")
# The rendering this replaced: a bare pair of double quotes round any
# argument holding a space, and no escaping at all. If the crafted value
# renders the same either way, this section has no teeth.
naive = " ".join(f'"{p}"' if " " in p else p for p in crafted.argv)
if naive == widgets.quote_argv(crafted.argv):
    fail("the crafted value renders identically under the old naive "
         "quoting; this section would pass over the defect it is for")
if "--steps 99" in crafted.text() and "--steps" not in crafted.argv:
    fail(f"the line shown carries a --steps 99 that no argv element does: "
         f"{crafted.text()!r}")
window.request._phase_edit.setText("")                         # noqa: SLF001
window.request._lever_edit.setText("")                         # noqa: SLF001
application.processEvents()
report(f"{len(CRAFTED)} crafted argvs render to a line that re-splits into "
       f"themselves, through the platform's own rule", len(failures) == before)


# ---------------------------------------------------------------------------
# 17. EVERY FIXED PARAMETER IS SHOWN AND LOCKED, NOT MISSING
# ---------------------------------------------------------------------------
#
# `request.FIXED_PARAMETERS` is where this pipeline's answer to a NovelAI
# control lives. `cfg_rescale` had a locked row saying so; `qualityToggle`,
# `dynamic_thresholding`, `skip_cfg_above_sigma` and `autoSmea` had no row
# at all, and neither did the vibe keys guard condition 5 refuses -- which
# is a COST boundary, at 2 Anlas on every tier. The pane's own docstring
# says a locked control is never removed from the form.
#
# So: every key of FIXED_PARAMETERS is either named by EXACTLY ONE row here
# or listed below as something NovelAI shows no control for. A new fixed
# parameter cannot be silently dropped, and it cannot be named twice.

print("the fixed parameters, against the form")
before = len(failures)
NOT_A_CONTROL: frozenset[str] = frozenset({
    "params_version", "deliberate_euler_ancestral_bug", "prefer_brownian",
    "controlnet_strength", "legacy", "legacy_v3_extend", "legacy_uc",
    "normalize_reference_strength_multiple",
})
"""Fixed parameters NovelAI's generator offers no control for, so no row
here can name one. Every OTHER key must have exactly one row. This list is
the place a new parameter is classified; law 7 says the check refuses
rather than guesses."""

for key in nai_request.FIXED_PARAMETERS:
    if key in NOT_A_CONTROL:
        continue
    naming = [r.label for r in request_pane.NAI_FIELDS
              if key in f"{r.ours} {r.reason}"]
    if len(naming) != 1:
        fail(f"request.FIXED_PARAMETERS[{key!r}] is named by {naming}: "
             f"exactly one NAI_FIELDS row must show it, or a reader cannot "
             f"see the control this pipeline has taken away")
unknown = [k for k in NOT_A_CONTROL if k not in nai_request.FIXED_PARAMETERS]
if unknown:
    fail(f"{unknown} is listed as 'not a control' and is not a fixed "
         f"parameter at all; the list has outlived its table")
# The vibe row names the condition that refuses it, in the GUARD'S words.
vibe = [r for r in request_pane.NAI_FIELDS if r.label == "Vibe Transfer"]
if len(vibe) != 1:
    fail("there is no Vibe Transfer row; guard condition 5 refuses a vibe "
         "key and encoding one costs 2 Anlas on every tier")
elif "vibe" not in guard.CONDITION_TITLES[5]:
    fail(f"guard condition 5 is now {guard.CONDITION_TITLES[5]!r} and the "
         f"Vibe Transfer row still cites it")
# Each new row is really in the built form, not only in the table.
locked_tips = [f.toolTip() for f in window.request.findChildren(
    widgets.LockedField)]
for label in ("Add Quality Tags", "Vibe Transfer", "Variety+", "Decrisper",
              "SMEA", "Prompt Guidance Rescale"):
    if not any(tip.startswith(label + ":") for tip in locked_tips):
        fail(f"{label!r} is a NAI_FIELDS row and no LockedField in the "
             f"window carries it: a row that is in the table and not on the "
             f"screen is the same as missing")

# THERE IS NO FREE TIER. The 28-step allowance is an Opus benefit; a window
# that says "free tier" tells a reader on any other plan that a generation
# costs nothing when every one of theirs costs Anlas.
for row in request_pane.NAI_FIELDS:
    if "free tier" in f"{row.ours} {row.reason}".lower():
        fail(f"the {row.label!r} row says 'free tier'; NovelAI's own page "
             f"makes the 28-step allowance an Opus-subscription benefit")
if "Opus tier" not in TEXT:
    fail("no row names the Opus tier; the Steps cap's condition is the "
         "subscription, and the window must say which one")
report(f"{len(nai_request.FIXED_PARAMETERS)} fixed parameters are each "
       f"shown-and-locked or classified, and no row claims a free tier",
       len(failures) == before)


# ---------------------------------------------------------------------------
# 18. THE FORM FITS THE SCREEN, AND NEVER CLIPS SIDEWAYS
# ---------------------------------------------------------------------------
#
# A lock the reader cannot see is the same as a lock that is not there.
# MEASURED before this: at 1366 px of window the request form was clipped
# by 296 px and the sentence "28 steps max" was off the right-hand edge --
# and the window's own minimumSizeHint was 1367x838, so a 1366x768 laptop
# could not open it in EITHER dimension. Both halves are asserted: the
# columns STACK when there is no room (nothing clips), and they sit SIDE BY
# SIDE when there is (the NovelAI layout is not thrown away to be safe).

print("the form at four widths")
before = len(failures)
LAPTOP = (1366, 768)
hint = window.minimumSizeHint()
if hint.width() > LAPTOP[0] or hint.height() > LAPTOP[1]:
    fail(f"the window's own minimum is {hint.width()}x{hint.height()} and "
         f"does not fit a {LAPTOP[0]}x{LAPTOP[1]} screen")
window._tabs.setCurrentIndex(1)                                # noqa: SLF001
scroll = window.request.findChild(QScrollArea)
form_body = scroll.widget()
columns = window.request._columns                              # noqa: SLF001
seen_stacked = False
seen_wide = False
for width in (1920, 1680, 1440, LAPTOP[0]):
    window.resize(width, 900)
    for _ in range(8):
        application.processEvents()
    clip = form_body.minimumSizeHint().width() - scroll.viewport().width()
    if clip > 0:
        fail(f"at {width} px the form asks for {clip} px more than it has, "
             f"so a lock reason is behind a horizontal scrollbar")
    if scroll.horizontalScrollBar().isVisible():
        fail(f"at {width} px the form grew a horizontal scrollbar")
    # A lock is its VALUE beside its reason. Every wrapped label in this
    # form is QSizePolicy.Ignored across, and a label that asks for nothing
    # beside one that asks for everything is drawn at zero width -- so the
    # value carries `widgets.VALUE_KEEPS_ITS_WIDTH` and is exempt. Measured
    # here, because "shown and locked, never hidden" is the pane's rule and
    # a value drawn 0 px wide is hidden.
    for field in window.request.findChildren(widgets.LockedField):
        shown = [kid for kid in field.findChildren(QLabel)
                 if kid.text() == field.value()]
        if not shown:
            fail(f"the locked row {field.value()!r} draws no value label")
        elif shown[0].width() < 24:
            fail(f"at {width} px the locked row {field.value()!r} draws its "
                 f"value {shown[0].width()} px wide: the reason took the "
                 f"whole row and the value is invisible")
    seen_stacked = seen_stacked or not columns.side_by_side()
    seen_wide = seen_wide or columns.side_by_side()
if not seen_stacked:
    fail("the columns never stacked at any width down to the laptop one; "
         "either the threshold is wrong or this assertion is vacuous")
if not seen_wide:
    fail("the columns never sat side by side, so NovelAI's own layout is "
         "gone rather than adapted")
if columns.threshold() <= 0:
    fail("_Columns never measured a threshold")
window.resize(*app.FIRST_RUN_SIZE)
for _ in range(8):
    application.processEvents()
report(f"nothing clips at 1920, 1680, 1440 or {LAPTOP[0]}, the columns "
       f"stack below {columns.threshold()} px, and the window fits a "
       f"{LAPTOP[0]}x{LAPTOP[1]} screen", len(failures) == before)


# ---------------------------------------------------------------------------
# 19. THE NAME THE SAVE DIALOG SUGGESTS IS ONE `save_as` ACCEPTS
# ---------------------------------------------------------------------------
#
# The button pre-filled the name of the file already open, which `save_as`
# refuses by rule -- a save here never overwrites -- so the most natural
# edit-and-save gesture in the window failed every time. Both halves: the
# suggestion is free, and `save_as` still refuses a taken one.

print("the suggested character name")
before = len(failures)
pane = window.character
for name in characters.available():
    pane.select(name)
    application.processEvents()
    suggested = pane.free_name()
    if not characters.NAME_RX.fullmatch(suggested):
        fail(f"free_name() suggested {suggested!r}, which is not a name")
    if suggested == characters.DEFAULT_CHARACTER:
        fail("free_name() suggested the default character, which save_as "
             "refuses by name")
    if os.path.exists(characters.file_for(suggested)):
        fail(f"free_name() suggested {suggested!r} and that file exists; "
             f"save_as refuses a name it would overwrite")
    if pane._CharacterPane__save_button.text() != "Copy As...":   # noqa: SLF001
        fail(f"the save button on {name!r} reads "
             f"{pane._CharacterPane__save_button.text()!r}; a save that "  # noqa: SLF001
             f"never overwrites is a copy and should say so")
    # isHidden(), not isVisible(): this check never shows the window, so
    # every widget in it reads invisible. What is asserted is that the
    # banner was not explicitly hidden for this character.
    if pane._CharacterPane__readonly.isHidden():                  # noqa: SLF001
        fail(f"the 'an outfit change is a new file' banner is hidden on "
             f"{name!r}; the rule must be on screen BEFORE the refusal")
# THE OTHER HALF: the rule the suggestion is dodging is still enforced.
taken = characters.available()[-1]
pane.select(taken)
application.processEvents()
try:
    pane.save_as(taken)
    fail(f"save_as overwrote {taken!r}")
except ValueError:
    pass
report(f"the suggested name is free for each of "
       f"{len(characters.available())} characters, and save_as still "
       f"refuses a taken one", len(failures) == before)


# ---------------------------------------------------------------------------
# 20. THE SMALL HONESTIES
# ---------------------------------------------------------------------------
#
# Four things a reader was promised and did not get: a locked row printed
# its value twice and looked like a rendering fault; the caption that is
# actually SENT per frame was clipped mid-word with no tooltip; seven of
# the run pane's eight buttons explained themselves nowhere; and the output
# box said "nothing has run in this window yet" for the whole of a silent
# child's run. Each is cheap, and each is the kind of thing that is fixed
# once and drifts back.

print("the small honesties")
before = len(failures)

# (a) A locked row shows its value ONCE. Measured on the BUILT FORM and not
# on NAI_FIELDS: the table is allowed to say that our value is "1" while the
# chip also shows "1" -- what must not happen is the pane drawing both, which
# is `_locked`'s decision and therefore what this has to read.
locked_seen = 0
for form in window.request.findChildren(QFormLayout):
    for index in range(form.rowCount()):
        item = form.itemAt(index, QFormLayout.FieldRole)
        field = item.widget() if item is not None else None
        if not isinstance(field, widgets.LockedField):
            continue
        locked_seen += 1
        below = (form.itemAt(index + 1, QFormLayout.FieldRole)
                 if index + 1 < form.rowCount() else None)
        caption = below.widget() if below is not None else None
        if not isinstance(caption, QLabel):
            continue
        if flat(caption.text()) == flat(field.value()):
            fail(f"the locked row showing {field.value()!r} prints it again "
                 f"in the caption underneath; nine rows read like a "
                 f"rendering fault and cost a line of height each")
if locked_seen < 10:
    fail(f"(a) walked only {locked_seen} locked rows; it is not looking at "
         f"the form it thinks it is")

# (b) A frame caption carries the whole sentence on hover.
window.request.set_recipe("walk")
application.processEvents()
frames_shown = 0
for row_widget, caption, _grid in window.request._frame_rows:  # noqa: SLF001
    if row_widget.isHidden():
        continue
    frames_shown += 1
    text = caption.toPlainText()
    if not text.strip():
        fail("a visible character-prompt row carries no caption at all")
    elif caption.toolTip() != text:
        fail(f"a character-prompt caption's tooltip is "
             f"{caption.toolTip()[:40]!r} and its text is {text[:40]!r}; "
             f"this is the one derived value a reader cannot widen")
    if caption.lineWrapMode() == QPlainTextEdit.NoWrap:
        fail("a character-prompt caption does not wrap; it was clipped "
             "mid-word at every window width")
if not frames_shown:
    fail("no character-prompt row was visible; (b) measured nothing")

# (c) EVERY button in the run pane says what it does. The window's top bar
# already did; this is the sibling route it was not applied to.
run_buttons = [b for b in window.run.findChildren(QPushButton)]
if len(run_buttons) < 8:
    fail(f"only {len(run_buttons)} buttons found in the run pane; (c) is "
         f"not measuring the pane it thinks it is")
for button in run_buttons:
    if not button.toolTip().strip():
        fail(f"the run pane's {button.text()!r} button explains itself "
             f"nowhere: a control that is shut and silent reads as broken")
for name, sentence in run_pane.BUTTON_TIPS.items():
    if not sentence.strip():
        fail(f"BUTTON_TIPS[{name!r}] is empty")

# (d) The output view names the line that is running, from the first
# instant. Driven with the fake child again, and restored after.
run_pane.subprocess.Popen = fake_popen
window.run.start = RunPane_start
window.run.clear()
FAKE_LINES[0], FAKE_CODE[0] = (), 0
started = window.compose("plan")
window.run.start()
first = window.run._view.toPlainText()                         # noqa: SLF001
if not first.startswith("$ "):
    fail(f"the output view opens with {first[:40]!r}; a silent child left "
         f"its placeholder on screen for the whole of its run")
if started.text() not in first:
    fail("the output view's first line is not the command that started")
if window.run.text().startswith("$ "):
    fail("RunPane.text() includes the echoed argv; it is what the CHILD "
         "said, and output_png and the guard verdicts are read from it")
finish_child()
run_pane.subprocess.Popen = real_popen
window.run.clear()
window.run.start = lambda: starts.append(window.run.command())

# (e) A refusal from the run pane's OWN buttons reaches the status bar
# instead of the console. `arm()` still raises -- that is the API contract
# -- and the SLOT is what must not let it out.
window.run.set_command(window.compose("run"))
window.run._cleared = None                                     # noqa: SLF001
window.statusBar().clearMessage()
try:
    window.run._arm_clicked()                                  # noqa: SLF001
except RuntimeError as exc:
    fail(f"the run pane's Arm slot let a RuntimeError out into the Qt "
         f"event loop: {exc}")
application.processEvents()
if window.run.armed():
    fail("the Arm slot armed a send with no clearance behind it")
if "dry run" not in window.statusBar().currentMessage():
    fail(f"the Arm slot refused and said {window.statusBar().currentMessage()!r} "
         f"in the status bar; the refusal has to reach the human")
try:
    window.run.arm()
    fail("arm() stopped raising; the slot may swallow, the API may not")
except RuntimeError:
    pass

# (f) The preview scratch directory is really made, and really removed.
window.character._CharacterPane__draw_preview()                # noqa: SLF001
QThreadPool.globalInstance().waitForDone(30000)
application.processEvents()
preview = window.character.preview_dir()
if not preview or not os.path.isdir(preview):
    fail(f"the character pane drew a preview and names {preview!r} as its "
         f"directory; (f) would measure nothing")
gone = window.character.drop_preview()
if gone != preview:
    fail(f"drop_preview() returned {gone!r}, not the directory {preview!r}")
if gone and os.path.isdir(gone):
    fail(f"drop_preview() returned {gone!r} and the directory is still "
         f"there; every window session used to leave one behind for good")
if window.character.drop_preview() != "":
    fail("drop_preview() is not idempotent")
report(f"a locked row shows its value once, {frames_shown} frame captions "
       f"wrap and carry a tooltip, {len(run_buttons)} run-pane buttons "
       f"explain themselves, the output view names its own command, and "
       f"the preview directory is removed", len(failures) == before)

QApplication.processEvents()
shutil.rmtree(SCRATCH, ignore_errors=True)


# ---------------------------------------------------------------------------

print()
if failures:
    print("FAILED")
    for message in failures:
        print(f"  - {message}")
    sys.exit(1)
print(f"PASS  {len(SIGNATURES)} signatures, "
      f"{len(request_pane.NAI_FIELDS)} NovelAI rows, "
      f"{len(request_pane.COMMAND_EXAMPLES)} argvs parsed by the live CLI, "
      f"{len(BANNED)} spellings proved absent from the code, "
      f"and one window driven through {len(app.WINDOW_ACTIONS)} buttons "
      f"with nothing sent")
