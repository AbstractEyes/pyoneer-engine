"""Verify the documentation SPINE, and generate the parts that can be generated.

    .venv/Scripts/python.exe tools/check_docs.py
    .venv/Scripts/python.exe tools/check_docs.py --write   # regenerate L1 docs

`tools/check_behavior_docs.py` proves one generated document agrees with one
subsystem. This file proves the whole tree of documents agrees with the tree of
code, and that a reader arriving cold can be routed by it.

WHY A DOCS CHECK IS NOT CEREMONY
--------------------------------
A document that lies costs more than one that is missing: a missing document
sends a reader to the source, a lying one sends them to write a `.tmx` that
raises. Generation alone does not save a document either -- a generated file
is guaranteed to match its GENERATOR, never to match the code, which is how
`docs/BEHAVIORS.md`'s hand-written preamble can name a behavior token that
does not exist.

WHAT IS ASSERTED
----------------
     1. every document declares its LAYER, and every layer's obligations are met
     2. NAVIGATION, both halves: every path CLAUDE.md names exists, AND every
        document under docs/ is named by CLAUDE.md (no unreachable document)
     3. the ROSTER, both halves: every roster entry has a file on disk, AND
        every check file on disk is in the roster -- plus every `check_*` a live
        document names is a real roster entry
     4. every `path.py:LINE` a live document quotes points at a file that is
        still that long, and the set of documents still quoting one at all is
        the pinned inventory below and nothing else
     5. the ANCHOR table in CLAUDE.md: every anchor addresses a `#TAG:`, that
        tag resolves to exactly one place in the tree, and the quoted text is
        still there  <- the strongest single assertion here
     6. FACT AGREEMENT: every fact a live document states that the CODE also
        knows is compared against the code -- token lists, roster counts, verb
        counts, spawnable types, input verbs, the property vocabulary
     7. the L1 documents are byte-for-byte what this file's generators produce
     8. ONE HOME: a roster blurb appears only in docs/CHECKS.md
     9. known-stale text in a FOREIGN generated document is pinned, and the pin
        fails when the defect is fixed as loudly as when a new one appears
    10. the CODE MAP: `docs/MAP.md` and `docs/map/*.md` are byte-for-byte what
        `tools/gen_map.py` produces, cover the mapped roots in both directions,
        and really do read signatures rather than merely list names
    11. the TAG SCHEME: every tag the tree emits resolves to exactly one place,
        every tag a document cites resolves at all, and a hand-placed `#TAG:`
        comment sits inside the thing it claims to name

WHY AN ANCHOR IS A #TAG AND NOT A LINE NUMBER
---------------------------------------------
A line number is an address invalidated by every edit above it, so a correct
anchor on a current document goes red when a docstring five rows up grows a
line. A `#TAG:` survives that, because the checker re-derives the line from
the AST on every run. Rule 5 keeps the proving and changes the address; rule 4
keeps the old form alive only as a pinned, shrinking debt.

THE ANTI-DRIFT POSITION THIS FILE TAKES
---------------------------------------
"No two documents may state the same fact" is unenforceable and also wrong --
routing requires some repetition. What is enforceable is stronger: **every
restatement of a fact the code knows is checked against the code**. So
CLAUDE.md may list the behavior tokens, and docs/PLACEABLE.md may list the
spawnable types, and neither can drift, because rule 6 recomputes both from the
registries on every run. Repetition is legal exactly where it is measured.

NO MAP CONTENT IS PINNED
------------------------
`data/maps/test.tmx` is never read. Every fact below comes from a registry, a
config file, the check roster, or a source line the docs themselves nominate.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import argparse
import ast
import json
import os
import re
import sys

import gen_map                      # the code-map generator; NOT a second copy

ROOT = _bootstrap.REPO_ROOT
DOCS = os.path.join(ROOT, "docs")

failures: list[str] = []
checked = 0


def expect(label: str, got, want) -> None:
    global checked
    checked += 1
    if got == want:
        print(f"    ok    {label}")
    else:
        print(f"    FAIL  {label}\n            got : {got!r}\n            want: {want!r}")
        failures.append(label)


def expect_empty(label: str, offenders) -> None:
    offenders = list(offenders)
    expect(label, offenders[:12], [])


_READ_CACHE: dict[str, str] = {}


def read(relpath: str) -> str:
    # Cached because rule 4 now walks several hundred references across the
    # generated map, and re-reading the same handful of source files once per
    # reference turned a fast check into a slow one.
    if relpath not in _READ_CACHE:
        with open(os.path.join(ROOT, relpath.replace("/", os.sep)),
                  encoding="utf-8", newline="") as handle:
            _READ_CACHE[relpath] = handle.read().replace("\r\n", "\n")
    return _READ_CACHE[relpath]


def lines_of(relpath: str) -> list[str]:
    return read(relpath).split("\n")


# ---------------------------------------------------------------------------
# The document layers
# ---------------------------------------------------------------------------
# L0  the boot document. Exactly one.
# L1  generated by THIS file. Must equal the generator byte for byte.
# L2  hand-written, live, question-scoped. Fact-checked; needs a stamp.
# L3  dated archive. EXEMPT from fact checks, and must say so in a banner --
#     the exemption is opt-in and visible, which is the only kind that keeps a
#     stale number from quietly becoming a live claim.

MARKER = re.compile(r"<!--\s*pyoneer-doc:\s*(L[0-3])\s*-->")
STAMP = re.compile(r"<!--\s*pyoneer-stamp:\s*(.+?)\s*-->", re.S)
ARCHIVE_BANNER = "pyoneer-archive"

BOOT = "CLAUDE.md"

# Generated somewhere ELSE. This file does not regenerate them and must not
# assert they equal ITS generators -- but they are live, so they are still
# fact-checked and still routed.
FOREIGN_GENERATED = {
    "docs/BEHAVIORS.md": "tools/check_behavior_docs.py --write",
    "docs/EVENTS.md": "tools/check_event_docs.py --write",
    "docs/MAP.md": "tools/gen_map.py --write",
}

# Documents that still address code by BARE LINE NUMBER, and how many times.
# The whole point of the tag scheme is that this table shrinks to nothing, so
# it fails in BOTH directions exactly as PINNED_STALE does: a new bare line
# reference anywhere is red, and fixing one without lowering the number here is
# also red. Lower the number in the same change that removes the reference.
#
# `docs/MAP.md` and `docs/map/*.md` are exempt by construction, not by
# indulgence: they are regenerated from the AST on every `--write`, so their
# line numbers cannot rot -- an address is only fragile when a human has to
# maintain it.
#
# The empty dict is the strongest form this rule can take: every bare
# `file.py:LINE` in a live document is a failure, with no exception left to
# argue about. A converted anchor reads as an address instead:
# `#TAG:GameEntity.allowed_move`, `#TAG:GameEntitySimple.__init__`,
# `#TAG:LAYER_NAME_ALIASES`, `#TAG:GameAnimationHandler.__init__`.
LINE_ANCHOR_DEBT: dict[str, int] = {}

# Text that is KNOWN WRONG in a document this file does not generate, pinned
# so it cannot get worse and cannot be forgotten. Each entry fails in BOTH
# directions: if the text disappears the pin is stale and must be deleted in
# the same change that fixed the defect; if new bad text appears it is not
# pinned and rule 6 catches it.
PINNED_STALE = [
    ("docs/BEHAVIORS.md", "topdown_move,tile_collision",
     "`tile_collision` is not a registered token and makes a map raise at "
     "load. TWO prose sites, both addressed by tag: the `_PREAMBLE` literal "
     "in #TAG:scripts/game/behavior/registry.py, and the `BEHAVIORS` "
     "docstring at #TAG:BEHAVIORS. Confirm with `grep -rn tile_collision "
     "scripts/game/behavior/ --include=*.py` -- drop the --include and a "
     "stale __pycache__ hit makes it look like three. This line is printed "
     "on every GREEN run, so it is read more often than any other sentence "
     "here; the three line numbers it used to carry named three places that "
     "did not contain the string, which is precisely what law 14 says a "
     "line number does."),
]


ARCHIVE_DIR = "docs/history/"
"""Where an L3 archive lives, and the rule is enforced in BOTH directions.

A banner at the top of a file is a sentence a reader can skip; a directory
named `history` is one they cannot. The measured cost of getting this wrong is
in the tree: five refactors were attempted as new sibling files and all five
died, while every refactor written into the incumbent class landed -- and a
finished plan sitting beside a live one is how a reader picks the sibling.
"""

GENERATED_DIRS = {"map"}
"""Subdirectories of docs/ that another generator owns whole.

`docs/map/` is 135 tier-2 files emitted by `tools/gen_map.py`; classifying
them would demand a layer marker in each and route each from CLAUDE.md, which
is a hundred navigation rows for one generated tree. Rule 10 checks that
directory byte-for-byte instead, which is stronger than a marker.
"""


def doc_files() -> list[str]:
    """Every markdown file under docs/, recursively, generated dirs aside."""
    found: list[str] = []
    for dirpath, dirs, files in os.walk(DOCS):
        dirs[:] = sorted(d for d in dirs
                         if os.path.relpath(os.path.join(dirpath, d),
                                            DOCS).replace(os.sep, "/")
                         not in GENERATED_DIRS)
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def classify() -> dict[str, str]:
    """relpath -> layer, for CLAUDE.md and every markdown file under docs/."""
    out = {BOOT: "L0"}
    for rel in doc_files():
        if rel in FOREIGN_GENERATED:
            out[rel] = "L1"
            continue
        found = MARKER.search(read(rel))
        out[rel] = found.group(1) if found else "?"
    return out


# ---------------------------------------------------------------------------
# The facts, read from the code -- never from a document
# ---------------------------------------------------------------------------

def roster() -> list[tuple[str, str]]:
    """The CHECKS list out of tools/check_all.py, parsed, not imported.

    Parsed rather than imported because importing it RUNS the whole suite.
    """
    tree = ast.parse(read("tools/check_all.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CHECKS":
            return [tuple(pair) for pair in ast.literal_eval(node.value)]
    raise AssertionError("tools/check_all.py has no CHECKS list")


ROSTER = roster()
ROSTER_NAMES = [name for name, _ in ROSTER]
ROSTER_BLURBS = {blurb: name for name, blurb in ROSTER}

from scripts.core.depth import (  # noqa: E402
    LAYER_NAME_ALIASES, MAP_DEPTH, OBJECT_CONVERTER, OBJECT_DEPTH)
from scripts.core.layer_profile import PREFIX  # noqa: E402
from scripts.core.spawn import SPAWN_REGISTRY  # noqa: E402
from scripts.game.behavior.base import ACTOR, BEHAVIORS, PARAM_PREFIX  # noqa: E402
from scripts.game.behavior.registry import BEHAVIOR_REGISTRY  # noqa: E402

with open(os.path.join(ROOT, "config", "inputs.json"), encoding="utf-8") as _h:
    INPUT_VERBS: dict = json.load(_h)

TOKENS = sorted(BEHAVIOR_REGISTRY)

try:
    import editor.core.verbs  # noqa: F401,E402  (populates the registry)
    from editor.core.commands import describe_all, verb_names  # noqa: E402
    EDITOR_VERBS = verb_names()
except Exception as _exc:                                   # pragma: no cover
    describe_all = None
    EDITOR_VERBS = None
    print(f"    note  editor verbs unavailable ({type(_exc).__name__}); "
          f"docs/COMMANDS.md will not be verified this run")


# ---------------------------------------------------------------------------
# The generators
# ---------------------------------------------------------------------------

GEN_BANNER = (
    "<!-- pyoneer-doc: L1 -->\n"
    "<!-- GENERATED by tools/check_docs.py. Do not edit. "
    "Regenerate: .venv/Scripts/python.exe tools/check_docs.py --write -->\n"
)


def _class_exists(name: str) -> bool:
    """Is `class <name>` defined anywhere under scripts/?"""
    needle = "class " + name
    for base, _dirs, files in os.walk(os.path.join(ROOT, "scripts")):
        for file in files:
            if not file.endswith(".py"):
                continue
            with open(os.path.join(base, file), encoding="utf-8",
                      errors="replace") as handle:
                for line in handle:
                    if line.startswith(needle) and line[len(needle)] in "(:":
                        return True
    return False


def render_placeable() -> str:
    from scripts.core.spawn import resolve_depth

    out = [GEN_BANNER, "# Placeable — what a map may legally contain", "",
           "Generated from `SPAWN_REGISTRY`, `scripts/core/depth.py` and",
           "`config/inputs.json`. This document answers *authoring* questions;",
           "for what a behavior DOES see [`BEHAVIORS.md`](BEHAVIORS.md), and for",
           "why something is inert see [`DIAGNOSE.md`](DIAGNOSE.md).", ""]

    out += ["## Object `type` values that spawn", "",
            "The `Type` field on a tmx object. An object whose type is not in",
            "this table makes the **whole map raise at load** — deliberately,",
            "because a skipped object looks like a working one.", "",
            "| `type` | default depth | spawned as |", "|---|---|---|"]
    for name in sorted(SPAWN_REGISTRY):
        factory = SPAWN_REGISTRY[name]
        try:
            depth = resolve_depth(name)
        except Exception:                                    # pragma: no cover
            depth = "—"
        out.append(f"| `{name}` | {depth} | `{getattr(factory, '__name__', factory)}` |")
    out.append("")

    phantom = [n for n in sorted(OBJECT_CONVERTER) if n not in SPAWN_REGISTRY]
    out += ["## Names that look placeable and are not", "",
            "`scripts/core/depth.py`'s `OBJECT_CONVERTER` maps these to a depth,",
            "which reads as a list of placeable classes. It is not one — a depth",
            "mapping is not a registration. Measured against the tree:", "",
            "| name in `OBJECT_CONVERTER` | `class` exists in `scripts/`? | spawnable? |",
            "|---|---|---|"]
    for name in phantom:
        out.append(f"| `{name}` | {'yes' if _class_exists(name) else '**no**'} | no |")
    out += ["", f"{len(phantom)} of {len(OBJECT_CONVERTER)} entries are not "
                "spawnable. Put one in a `Type` field and the map raises.", ""]

    out += ["## Tile layer names that resolve to a depth", "",
            "A tile layer whose name is not here is **silently not drawn** —",
            "`resolve_layer_depth` returns `None` and nothing warns.", "",
            "| layer name | depth |", "|---|---|"]
    for name, depth in sorted(MAP_DEPTH.items(), key=lambda kv: (kv[1], kv[0])):
        out.append(f"| `{name}` | {depth} |")
    out.append("")
    if LAYER_NAME_ALIASES:
        out += ["Aliases, which resolve to the canonical name above:", "",
                "| authored spelling | resolves to |", "|---|---|"]
        for bad, good in sorted(LAYER_NAME_ALIASES.items()):
            out.append(f"| `{bad}` | `{good}` |")
        out.append("")

    out += ["## Object group depth names", "",
            "| name | depth |", "|---|---|"]
    for name, depth in sorted(OBJECT_DEPTH.items(), key=lambda kv: (kv[1], kv[0])):
        out.append(f"| `{name}` | {depth} |")
    out.append("")

    out += ["## The tmx property vocabulary", "",
            "| property | meaning |", "|---|---|",
            f"| `{BEHAVIORS}` | comma-separated behavior tokens, on the OBJECT |",
            f"| `{PARAM_PREFIX}<key>` | one behavior parameter |",
            f"| `{ACTOR}` | actors-table row id, read from "
            f"`data/project/tables/actors.json` |",
            "",
            f"Every custom property starts `{PREFIX}`. The prefix is not style:",
            "pytmx raises and makes the whole map unloadable if a property",
            "shadows one of its own attribute names.", "",
            "Registered behavior tokens (see [`BEHAVIORS.md`](BEHAVIORS.md) for",
            "what each one does and whether it is wired):", "",
            "    " + " ".join(TOKENS), ""]

    out += ["## Input verbs", "",
            "Bound in `config/inputs.json`. A behavior polling a verb that is",
            "not here raises at attach — add the binding in the same change.", "",
            "| verb | bindings |", "|---|---|"]
    for verb in sorted(INPUT_VERBS):
        out.append(f"| `{verb}` | " + ", ".join(f"`{b}`" for b in INPUT_VERBS[verb]) + " |")
    out.append("")
    return "\n".join(out)


def render_checks() -> str:
    out = [GEN_BANNER, "# Checks — the roster, generated from it", "",
           "Generated from `tools/check_all.py`'s `CHECKS` list and each",
           "module's own first docstring line. Run the suite:", "",
           "    .venv/Scripts/python.exe tools/check_all.py", "",
           "One check on its own:", "",
           "    .venv/Scripts/python.exe tools/check_<name>.py", "",
           "A new check goes into the roster **in the same change** — three",
           "have been written, passed, and never run by the suite. A check that",
           "did not run has proved nothing, which is why an absent optional",
           "dependency reports `SKIP` and never `PASS`.", "",
           f"{len(ROSTER)} checks:", "",
           "| check | roster line | module says |", "|---|---|---|"]
    for name, blurb in ROSTER:
        rel = f"tools/check_{name}.py"
        first = ""
        try:
            first = lines_of(rel)[0].lstrip('"').strip()
        except OSError:                                      # pragma: no cover
            first = "**FILE MISSING**"
        out.append(f"| `{name}` | {blurb} | {first} |")
    out += ["", "`tools/smoke.py` runs after the roster and is not a check: it",
            "reports a frame hash, the component census, the blit-token",
            "histogram by depth, culled draws and listener invocations. It",
            "injects **no input**, so a clean smoke never means nothing",
            "changed.", ""]
    return "\n".join(out)


def render_commands() -> str:
    assert describe_all is not None
    body = describe_all(title="Command vocabulary")
    return GEN_BANNER + body if body.startswith("# ") else GEN_BANNER + body


GENERATED = {
    "docs/PLACEABLE.md": render_placeable,
    "docs/CHECKS.md": render_checks,
}
if describe_all is not None:
    GENERATED["docs/COMMANDS.md"] = render_commands


def write_all() -> None:
    for rel, render in GENERATED.items():
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render())
        print(f"  wrote {rel}")


parser = argparse.ArgumentParser()
parser.add_argument("--write", action="store_true",
                    help="regenerate the L1 documents and exit")
args = parser.parse_args()
if args.write:
    write_all()
    raise SystemExit(0)


print("Verifying the documentation spine\n")

LAYERS = classify()
BOOT_TEXT = read(BOOT)
LIVE = [rel for rel, layer in LAYERS.items() if layer in ("L0", "L1", "L2")]
ARCHIVE = [rel for rel, layer in LAYERS.items() if layer == "L3"]


# ---------------------------------------------------------------------------
print("1. every document declares its layer, and meets that layer's obligations")
# ---------------------------------------------------------------------------
expect_empty("every docs/*.md carries a `pyoneer-doc: L0..L3` marker",
             [rel for rel, layer in LAYERS.items() if layer == "?"])
expect("exactly one L0 boot document",
       sorted(r for r, v in LAYERS.items() if v == "L0"), [BOOT])
expect_empty("every L2 document carries a `pyoneer-stamp:`",
             [rel for rel, layer in LAYERS.items()
              if layer == "L2" and not STAMP.search(read(rel))])
expect_empty("every L3 archive says it is exempt (carries the archive banner)",
             [rel for rel in ARCHIVE if ARCHIVE_BANNER not in read(rel)])
expect_empty("no L1 document is hand-editable without a named generator",
             [rel for rel, layer in LAYERS.items()
              if layer == "L1" and rel not in GENERATED and rel not in FOREIGN_GENERATED])
# The archive rule, both halves. Half one alone permits a live plan quietly
# filed under history/; half two alone permits a superseded plan sitting in
# docs/ beside the document that replaced it, which is the shape that gets a
# finished piece of work built a second time.
expect_empty("every document under docs/history/ is an L3 archive",
             [rel for rel, layer in LAYERS.items()
              if rel.startswith(ARCHIVE_DIR) and layer != "L3"])
expect_empty("every L3 archive lives under docs/history/",
             [rel for rel in ARCHIVE if not rel.startswith(ARCHIVE_DIR)])
# ...and the walk really descends into it. Both rules above are satisfied
# VACUOUSLY by a classifier that never looks inside `docs/history/` -- a
# non-recursive listing -- which would make filing a document there a way to
# exempt it from every rule in this file rather than a way to date it.
# Enumerated by glob rather than by
# `doc_files()` on purpose: an assertion that asks the walker whether it walked
# proves nothing.
import glob as _glob                                                # noqa: E402
expect("every markdown file on disk under docs/history/ is classified",
       sorted("%s%s" % (ARCHIVE_DIR, os.path.basename(p))
              for p in _glob.glob(os.path.join(DOCS, "history", "*.md"))),
       sorted(ARCHIVE))


# ---------------------------------------------------------------------------
print("\n2. navigation, both halves")
# ---------------------------------------------------------------------------
# Half one: every repo path the boot document names resolves.
PATH_RX = re.compile(r"[`(]((?:docs|tools|scripts|editor|config|demos|data)"
                     r"/[A-Za-z0-9_<>./-]*?\.(?:md|py|json|tmx))[`)]")
named = sorted({m.group(1) for m in PATH_RX.finditer(BOOT_TEXT)})


def resolves(rel: str) -> bool:
    if "<" in rel:                       # editor/genres/<id>/RULES.md
        import glob
        pattern = re.sub(r"<[^>]+>", "*", rel)
        return bool(glob.glob(os.path.join(ROOT, pattern.replace("/", os.sep))))
    return os.path.exists(os.path.join(ROOT, rel.replace("/", os.sep)))


expect_empty("every repo path CLAUDE.md names exists",
             [rel for rel in named if not resolves(rel)])
expect("CLAUDE.md names a non-trivial number of paths", len(named) >= 12, True)

# Half two: no document under docs/ is unreachable. "Mentioned somewhere in
# CLAUDE.md" is too weak -- a doc named only in a KNOWN GAPS bullet is not
# routed. The assertion is against the NAVIGATION TABLE itself.
nav = re.search(r"## The query playbook\n(.*?)\n## ", BOOT_TEXT, re.S)
expect("CLAUDE.md has a query playbook section", nav is not None, True)
NAV = "\n".join(l for l in (nav.group(1) if nav else "").split("\n")
                if l.startswith("|"))
expect_empty("every docs/*.md is routed by the navigation table",
             [rel for rel in LAYERS if rel != BOOT and rel not in NAV])
expect("the navigation table routes by question shape, not by file name "
       "(every row asks something in quotes)",
       all('"' in row for row in NAV.split("\n")[2:] if row.strip()), True)


# ---------------------------------------------------------------------------
print("\n3. the check roster, both halves")
# ---------------------------------------------------------------------------
on_disk = sorted(f[len("check_"):-len(".py")]
                 for f in os.listdir(os.path.join(ROOT, "tools"))
                 if f.startswith("check_") and f.endswith(".py") and f != "check_all.py")


def tracked_checks() -> list[str] | None:
    """Check modules git knows about, or None when git cannot answer.

    The roster law is "a new check joins the roster IN THE SAME CHANGE", and a
    change is a commit -- so the set this rule judges is the TRACKED one. An
    untracked `tools/check_*.py` is another agent's work in flight, not a
    violation, and failing on it would make this check report someone else's
    half-finished tree as this one's. It is reported below instead, so nothing
    hides. The moment such a file is committed without a roster line, this
    goes red.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files", "tools/check_*.py"],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    except Exception:                                        # pragma: no cover
        return None
    if out.returncode != 0:                                  # pragma: no cover
        return None
    return sorted(os.path.basename(p)[len("check_"):-len(".py")]
                  for p in out.stdout.split("\n")
                  if p.strip() and not p.endswith("check_all.py"))


TRACKED = tracked_checks()
judged = on_disk if TRACKED is None else TRACKED
expect_empty("every roster entry has a file on disk",
             [n for n in ROSTER_NAMES if n not in on_disk])
expect_empty("every TRACKED check file is in the roster",
             [n for n in judged if n not in ROSTER_NAMES])
in_flight = [n for n in on_disk if n not in ROSTER_NAMES and n not in judged]
if in_flight:
    print(f"    note  untracked and unrostered (in flight, not judged): "
          f"{', '.join('check_' + n for n in in_flight)}")
expect("no duplicate roster entries", len(set(ROSTER_NAMES)), len(ROSTER_NAMES))

CHECK_RX = re.compile(r"\bcheck_([a-z0-9_]+)\b")
# A `check_*` that the code map lists is a FUNCTION, not a check module --
# `check_property_name` is one, and the map is generated so it will name every
# future one too. Resolving the name against the tag index rather than
# exempting the map by filename keeps the rule general: a hand-written document
# may also cite `check_property_name` and be right.
TAGS = gen_map.tag_index()
# A PLAN may name a check its own build order creates. That is not the same as
# naming one that does not exist: the plan has to DECLARE it, in a
# ```planned-checks fence, so the exemption is enumerated rather than inferred
# from tone. The second assertion below is what keeps the list from rotting --
# a declared name that has since reached the roster is red, so the stage that
# lands a check must delete its line.
PLANNED_RX = re.compile(r"```planned-checks\n(.*?)```", re.S)


def planned_checks(text):                                 # #TAG:planned_checks
    """The check names a document declares its own stages will create."""
    found = set()
    for body in PLANNED_RX.findall(text):
        for line in body.splitlines():
            name = line.strip()
            if name.startswith("check_"):
                found.add(name[len("check_"):])
    return found


unknown_named, planned_but_shipped = [], []
for rel in LIVE:
    text = read(rel)
    planned = planned_checks(text)
    for name in sorted(planned & set(ROSTER_NAMES)):
        planned_but_shipped.append(f"{rel} still plans check_{name}, "
                                   f"which is now on the roster")
    for name in sorted(set(CHECK_RX.findall(text))):
        if name in ROSTER_NAMES or name in ("all", "docs"):
            continue
        if any(tag.rsplit(".", 1)[-1] == "check_" + name for tag in TAGS):
            continue
        if name in planned:
            continue
        unknown_named.append(f"{rel}: check_{name}")
expect_empty("every check a LIVE document names is in the roster "
             "(or is a function the code map knows, or the document declares "
             "it as planned)", unknown_named)
expect_empty("no document plans a check that already shipped",
             planned_but_shipped)


# ---------------------------------------------------------------------------
print("\n4. every file:line a live document quotes still reaches that far")
# ---------------------------------------------------------------------------
REF_RX = re.compile(r"\b([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.(?:py|json|tmx|md)):(\d+)")
stale_refs = []
ref_count = 0
for rel in LIVE:
    for match in REF_RX.finditer(read(rel)):
        target, number = match.group(1), int(match.group(2))
        ref_count += 1
        path = os.path.join(ROOT, target.replace("/", os.sep))
        if not os.path.isfile(path):
            stale_refs.append(f"{rel} -> {target}:{number} (no such file)")
            continue
        if number > len(lines_of(target)):
            stale_refs.append(f"{rel} -> {target}:{number} "
                              f"(only {len(lines_of(target))} lines)")
expect_empty("no live document quotes a line past the end of its file", stale_refs)

# The inventory, both directions -- but nothing here DEMANDS a minimum number
# of line references: source-line quoting is the thing being removed, so an
# assertion insisting some survive would be an assertion against the point.
observed_debt = {}
for rel in LIVE:
    if rel in FOREIGN_GENERATED or rel in GENERATED:
        continue                     # regenerated; its numbers cannot rot
    count = len(REF_RX.findall(read(rel)))
    if count:
        observed_debt[rel] = count
expect("the bare-line-number inventory is exactly what is pinned "
       "(a new one is red; fixing one means lowering the pin)",
       observed_debt, LINE_ANCHOR_DEBT)
if observed_debt != LINE_ANCHOR_DEBT:
    for rel in sorted(set(observed_debt) | set(LINE_ANCHOR_DEBT)):
        was, now = LINE_ANCHOR_DEBT.get(rel, 0), observed_debt.get(rel, 0)
        if was == now:
            continue
        advice = ("address it by #TAG: instead" if now > was
                  else "lower or delete the pin in tools/check_docs.py")
        print(f"          {rel}: pinned {was}, found {now} -- {advice}")
expect("CLAUDE.md addresses no source by bare line number at all",
       observed_debt.get(BOOT, 0), 0)


# ---------------------------------------------------------------------------
print("\n5. the anchor table: every #TAG still says what it says")
# ---------------------------------------------------------------------------
# `#TAG:GameEntity.allowed_move :: if field is None or bit is None`
#
# The tag is resolved to a file and a LINE RANGE on every run -- from the AST
# for a generated tag, from the comment's own line for a hand-placed one -- and
# the quoted text must appear inside that range exactly once. So the anchor
# survives any edit ABOVE it (the failure that made the old form untenable) and
# still fails when the fact moves to a different symbol, is duplicated, or goes
# away.
SOURCE_TAGS: dict[str, tuple[str, int, str]] = {}
DUPLICATE_SOURCE_TAGS: list[str] = []
for _tag, _rel, _no, _line in gen_map.source_tags():
    if _tag in SOURCE_TAGS:
        DUPLICATE_SOURCE_TAGS.append(f"{_tag} at {_rel}:{_no} and "
                                     f"{SOURCE_TAGS[_tag][0]}:{SOURCE_TAGS[_tag][1]}")
    else:
        SOURCE_TAGS[_tag] = (_rel, _no, _line)


def tag_extent(tag: str) -> tuple[str, int, int] | None:
    """(relpath, first line, last line) a tag speaks for, or None.

    A hand-placed `#TAG:` comment wins over the generated one and speaks for
    its own single line -- that is the whole reason to place one: it narrows an
    anchor from "somewhere in this function" to "this line".
    """
    if tag in SOURCE_TAGS:
        rel, number, _ = SOURCE_TAGS[tag]
        return rel, number, number
    site = TAGS.get(tag)
    if site is None:
        return None
    return site.relpath, site.lineno, site.end_lineno


block = re.search(r"```anchors\n(.*?)```", BOOT_TEXT, re.S)
expect("CLAUDE.md carries an ```anchors``` block", block is not None, True)
anchors: list[tuple[str, str]] = []
malformed: list[str] = []
for raw in (block.group(1) if block else "").strip().split("\n"):
    if not raw.strip():
        continue
    head, sep, needle = raw.partition(" :: ")
    if not sep or not head.startswith(gen_map.TAG):
        malformed.append(raw.strip()[:70])
        continue
    anchors.append((head[len(gen_map.TAG):].strip(), needle))
expect_empty("every anchor is `#TAG:<tag> :: quoted text` -- no line numbers, "
             "which is the whole reason this table changed shape", malformed)
expect("the anchor table is not empty enough to be decorative",
       len(anchors) >= 8, True)

broken = []
for tag, needle in anchors:
    extent = tag_extent(tag)
    if extent is None:
        broken.append(f"#TAG:{tag} resolves nowhere -- the symbol was renamed "
                      f"or removed, or the map needs regenerating")
        continue
    target, first, last = extent
    body = lines_of(target)[first - 1:last]
    hits = [first + i for i, line in enumerate(body) if needle in line]
    if not hits:
        elsewhere = [i + 1 for i, line in enumerate(lines_of(target))
                     if needle in line]
        broken.append(
            f"#TAG:{tag} ({target}:{first}-{last}) no longer contains {needle!r}"
            + (f" -- it moved OUT of that symbol, to line {elsewhere[0]}"
               if elsewhere else " -- and it is gone from the file entirely"))
    elif len(hits) > 1:
        broken.append(f"#TAG:{tag} contains {needle!r} on {len(hits)} lines "
                      f"({hits[:4]}) -- the anchor no longer names one place")
expect_empty("every anchored tag still contains its quoted text, exactly once",
             broken)


# ---------------------------------------------------------------------------
print("\n6. fact agreement: what a live document claims vs what the code holds")
# ---------------------------------------------------------------------------
ESCAPE = "<!-- fact: historical"          # opt-in, must carry a reason

COUNT_RX = re.compile(r"(\d+)[^\S\n]*\**[^\S\n]*(checks?|verbs)\b")
wrong_counts = []
for rel in LIVE:
    for lineno, line in enumerate(lines_of(rel), 1):
        if ESCAPE in line:
            continue
        for match in COUNT_RX.finditer(line):
            value, kind = int(match.group(1)), match.group(2)
            if kind.startswith("check"):
                want = len(ROSTER)
            elif EDITOR_VERBS is None:
                continue
            else:
                want = len(EDITOR_VERBS)
            if value != want:
                wrong_counts.append(f"{rel}:{lineno} says {value} {kind}, "
                                    f"the tree holds {want}")
expect_empty("no live document states a stale roster or verb count", wrong_counts)

# Behavior tokens quoted in a `pyoneer_behaviors` value must all resolve. This
# is the token-VALUE twin of check_behavior_docs' property-NAME rule, which is
# blind to values -- and it is the rule that catches `tile_collision`.
# Matches both the tmx form  <property name="pyoneer_behaviors" value="a,b"/>
# and the prose form         pyoneer_behaviors="a,b"
VALUE_RX = re.compile(re.escape(BEHAVIORS) + r'"?\s*(?:value)?=\s*"([^"]*)"')
bad_tokens = []
for rel in LIVE:
    text = read(rel)
    for match in VALUE_RX.finditer(text):
        lineno = text.count("\n", 0, match.start()) + 1
        for token in [t.strip() for t in match.group(1).split(",") if t.strip()]:
            if token not in BEHAVIOR_REGISTRY:
                bad_tokens.append((rel, lineno, token))
pinned_hits = []
unpinned = []
for rel, lineno, token in bad_tokens:
    if any(rel == prel and token in pin for prel, pin, _ in PINNED_STALE):
        pinned_hits.append((rel, token))
    else:
        unpinned.append(f"{rel}:{lineno} declares behavior token {token!r}, "
                        f"which is not registered -- a map carrying it raises at load")
expect_empty("every behavior token a live document declares is registered "
             "(unpinned)", unpinned)

# THE SOWN TAGS, BOTH DIRECTIONS.
#
# A `#TAG:` comment in a source file is an ADDRESS, and an address nothing
# validates is the line-number problem wearing a new hat. A tag naming a
# behavior that has since been renamed fails silently: the grep the docs teach
# returns zero hits and the reader concludes the thing does not exist.
#
# So the sown behavior tags and the registry must agree as SETS. Both
# directions matter and they catch different mistakes:
#   registry -> tags : a behavior landed and nobody tagged it, so it is
#                      invisible to the lookup the docs promise.
#   tags -> registry : a behavior was renamed or deleted and its tag was left
#                      behind, so the lookup answers with a corpse.
SOWN_RX = re.compile(r"#TAG:([a-z][a-z0-9_]*)\b")
sown: set[str] = set()
for root, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs
               if d not in {".git", "__pycache__", ".venv", "docs", "tools"}]
    for name in files:
        if not name.endswith(".py"):
            continue
        with open(os.path.join(root, name), encoding="utf-8",
                  errors="replace") as handle:
            for match in SOWN_RX.finditer(handle.read()):
                sown.add(match.group(1))
sown_tokens = sown & set(TOKENS)
expect_empty("every registered behavior carries a sown #TAG (registry -> tags)",
             sorted(set(TOKENS) - sown_tokens))
# The reverse direction needs the snake_case tags that LOOK like tokens but
# are not -- `delta_is_ms_over_60` and friends are deliberate topic tags, so
# the offender set is tags that were once tokens and no longer are. A tag
# whose name matches nothing and was never a token is a topic tag and legal;
# what is illegal is a tag citing a token spelling the registry has dropped.
CITED_TOKEN_RX = re.compile(r"#TAG:(" + "|".join(re.escape(t) for t in TOKENS)
                            + r")\b")
orphan_token_tags = []
for rel in LIVE:
    for match in re.finditer(r"#TAG:([a-z][a-z0-9_]*)\b", read(rel)):
        tag = match.group(1)
        if tag.endswith("_action") or tag.endswith("_move") or tag.endswith("_input"):
            if tag not in BEHAVIOR_REGISTRY:
                orphan_token_tags.append(f"{rel} cites #TAG:{tag}, which is "
                                         f"not a registered behavior")
expect_empty("no document cites a behavior-shaped #TAG that is not registered "
             "(tags -> registry)", orphan_token_tags)

# L0 may NAME a token, and may not ENUMERATE the registry: a table that is
# generated elsewhere must not be copied into the boot document, or the boot
# document becomes the thing that rots. Both halves -- every token it names
# must resolve, and it must name strictly fewer than all of them.
boot_tokens = sorted(t for t in TOKENS
                     if re.search(rf"(?<![a-z_]){re.escape(t)}(?![a-z_])", BOOT_TEXT))
expect("CLAUDE.md does not enumerate the registry (that is BEHAVIORS.md's job)",
       len(boot_tokens) < len(TOKENS) and len(boot_tokens) >= 1, True)
expect("CLAUDE.md lists exactly the bound input verbs",
       sorted(v for v in INPUT_VERBS
              if re.search(rf"(?<![a-z_]){re.escape(v)}(?![a-z_])", BOOT_TEXT)),
       sorted(INPUT_VERBS))
expect("CLAUDE.md names the spawnable types and no others",
       sorted(n for n in set(SPAWN_REGISTRY) | set(OBJECT_CONVERTER)
              if f"**`{n}`**" in BOOT_TEXT),
       sorted(SPAWN_REGISTRY))
expect_empty("CLAUDE.md spells the property vocabulary the way the code does",
             [name for name in (PREFIX, BEHAVIORS, PARAM_PREFIX, ACTOR)
              if name not in BOOT_TEXT])
# The ACCESS ESCALATION ladder states a cost per level, and a ladder whose
# costs are wrong routes a reader to the wrong rung -- which is the one thing it
# exists to prevent. Each claim is bound to a real measurement here. The
# tolerance is a FACTOR, not a percentage: the claim is an order of magnitude
# ("a page" vs "a book"), so demanding two significant figures would make this
# rule fire on every commit that adds a class.
COST_RX = re.compile(r"~([\d.]+)k tokens")
TOKENS_PER_KB = 4000.0


def size_of(*rels: str) -> float:
    return sum(os.path.getsize(os.path.join(ROOT, r.replace("/", os.sep)))
               for r in rels) / TOKENS_PER_KB


def median_size(rels: list[str]) -> float:
    """Median BY SIZE, not by name -- the ladder's claim is about volume."""
    return size_of(sorted(rels, key=size_of)[len(rels) // 2]) if rels else 0.0


_tier2 = sorted(gen_map.on_disk_tier2())
_sources = sorted(gen_map.source_files())
COST_CLAIMS = [
    ("| 0 | this file |", "the boot document itself", size_of(BOOT)),
    ("— tier 1 |", "docs/MAP.md", size_of(gen_map.INDEX_REL)),
    ("— tier 2 |", "the median tier-2 file", median_size(_tier2)),
    ("the source file", "the median mapped module", median_size(_sources)),
    ("the set is ~", "every tier-2 file at once", size_of(*_tier2)),
]
cost_lies = []
for marker, what, real in COST_CLAIMS:
    row = next((l for l in lines_of(BOOT) if marker in l), None)
    found = COST_RX.search(row) if row else None
    if found is None:
        cost_lies.append(f"CLAUDE.md states no `~Nk tokens` cost for {what}")
        continue
    stated = float(found.group(1))
    if not (real / 1.6 <= stated <= real * 1.6):
        cost_lies.append(f"CLAUDE.md says {what} costs ~{stated}k tokens; "
                         f"measured ~{real:.1f}k -- write ~{round(real, 1)}k")
expect_empty("the access-escalation ladder's costs are the measured ones",
             cost_lies)

# Catches `GameFoo`, `GameFoo.method`, `GameFoo(` -- the phantom-class trap in
# scripts/core/depth.py is four names that read as placeable and exist nowhere.
CLASS_RX = re.compile(r"`(Game[A-Za-z]+)(?=[.`(\s])")
expect_empty("CLAUDE.md and DIAGNOSE.md name no absent Game* class",
             [f"{rel}: {name}" for rel in (BOOT, "docs/DIAGNOSE.md")
              for name in sorted(set(CLASS_RX.findall(read(rel))))
              if not _class_exists(name)])


# ---------------------------------------------------------------------------
print("\n7. the generated documents are exactly what the generators produce")
# ---------------------------------------------------------------------------
for rel, render in GENERATED.items():
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    on_file = read(rel) if os.path.isfile(path) else "<<absent>>"
    want = render()
    expect(f"{rel} is byte-identical to its generator", on_file == want, True)
    if on_file != want:
        # Say WHICH line and say the command. A generated doc going stale is
        # the normal consequence of adding a check or a verb, and the fix is
        # one command -- an unexplained boolean here would read as a bug in
        # the doc rather than as "you changed the thing it is generated from".
        a, b = on_file.split("\n"), want.split("\n")
        for i in range(max(len(a), len(b))):
            if a[i:i + 1] != b[i:i + 1]:
                print(f"          first difference at line {i + 1}:")
                print(f"            on disk : {(a[i:i+1] or ['<eof>'])[0][:90]!r}")
                print(f"            should  : {(b[i:i+1] or ['<eof>'])[0][:90]!r}")
                break
        print("          fix: .venv/Scripts/python.exe tools/check_docs.py --write")
if describe_all is None:                                     # pragma: no cover
    print("    note  docs/COMMANDS.md not verified (editor not importable)")


# ---------------------------------------------------------------------------
print("\n8. one home: a roster blurb lives in docs/CHECKS.md and nowhere else")
# ---------------------------------------------------------------------------
copies = []
for rel in LIVE + ARCHIVE:
    if rel == "docs/CHECKS.md":
        continue
    text = read(rel)
    copies += [f"{rel}: {blurb!r}" for blurb in ROSTER_BLURBS if blurb in text]
expect_empty("no document restates a roster blurb", copies)


# ---------------------------------------------------------------------------
print("\n9. pinned known-stale text: still there, and nothing worse")
# ---------------------------------------------------------------------------
for rel, needle, why in PINNED_STALE:
    present = needle in read(rel)
    expect(f"pin still applies: {rel} contains {needle!r}", present, True)
    if present:
        print(f"          reason: {why}")
    else:
        failures.append(f"stale pin for {rel}")
        print(f"          the defect appears FIXED -- delete this pin in the "
              f"same change ({rel})")
expect("every pinned defect was actually observed",
       len(pinned_hits) >= 1 or not PINNED_STALE, True)


# ---------------------------------------------------------------------------
print("\n10. the code map is generated, complete, and really reads signatures")
# ---------------------------------------------------------------------------
MODULES = gen_map.load()

expect_empty("docs/MAP.md and docs/map/*.md are byte-identical to their "
             "generator", gen_map.drift())

# Both halves of coverage. Half one alone passes for a map that has grown a
# file for every module and never deletes one; half two alone passes for a map
# of three modules that happen to still exist.
mapped = {m.relpath for m in MODULES}
on_disk_py = set(gen_map.source_files())
expect("every .py under the mapped roots is in the map", mapped, on_disk_py)
expect("every tier-2 file corresponds to a module that exists",
       sorted(gen_map.on_disk_tier2()),
       sorted(gen_map.tier2_rel(m) for m in MODULES))
expect("the map is not trivially small", len(MODULES) >= 100, True)

# TEETH. Everything above compares the tree against itself: a generator that
# emitted only names, dropped every default and never printed a return
# annotation would satisfy all of it. So drive the same renderers over a
# fixture this file owns, and mutate the fixture in the four ways a signature
# can silently stop being reported.
FIXTURE = '''"""Fixture module, first line.

A second paragraph that must never reach either tier.
"""
LOUD = 1
quiet = 2


def helper(a, b: int = 3, *rest, key: str = "x") -> str:
    """Helper gist."""
    return key


def _private_helper():
    pass


class Thing:
    """Thing gist."""

    def method(self, x=1):
        pass

    def _hidden(self):
        pass

    @property
    def value(self):
        return 0

    @value.setter
    def value(self, v):
        pass
'''


def fixture_module(source: str) -> "gen_map.Module":
    module = gen_map.parse_text("scripts/fixture/thing.py", source)
    gen_map.assign_tags([module])
    return module


def render_fixture(source: str) -> str:
    return gen_map.render_module(fixture_module(source))


FIX_DOC = render_fixture(FIXTURE)
expect("fixture: a default value is rendered, not just the parameter name",
       "b: int=3" in FIX_DOC, True)
expect("fixture: ...and mutating that default moves the document",
       "b: int=4" in render_fixture(FIXTURE.replace("b: int = 3", "b: int = 4")),
       True)
expect("fixture: a declared return annotation is rendered",
       "-> str" in FIX_DOC, True)
expect("fixture: ...and mutating it moves the document",
       "-> bytes" in render_fixture(FIXTURE.replace("-> str", "-> bytes")), True)
expect("fixture: star-args and keyword-only defaults survive",
       "*rest, key: str='x'" in FIX_DOC, True)
expect("fixture: the docstring's FIRST line is taken",
       "Fixture module, first line." in FIX_DOC, True)
expect("fixture: ...and the rest of the docstring is not",
       "must never reach" in FIX_DOC, False)
expect("fixture: an UPPER module constant is listed", "`LOUD`" in FIX_DOC, True)
expect("fixture: a lower-case module assignment is not called a constant",
       "`quiet`" in FIX_DOC, False)
expect("fixture: a private METHOD is still listed -- tier 2 is the whole file",
       "#TAG:Thing._hidden" in FIX_DOC, True)
expect("fixture: a property and its setter are both listed",
       ("#TAG:Thing.value" in FIX_DOC and "#TAG:Thing.value.setter" in FIX_DOC),
       True)

# Tier 1 is a second renderer over the same facts, and it has its own ways to
# be wrong: printing a signature (which makes it tier 2 under another name),
# forgetting the address, or listing a private symbol it promised to omit.
FIX_INDEX = gen_map.render_index([fixture_module(FIXTURE)])
expect("fixture: tier 1 gives a class its tag, its kind and its address",
       "#TAG:Thing class thing.py:18" in FIX_INDEX, True)
expect("fixture: tier 1 gives a public function the same",
       "#TAG:helper def thing.py:9  · Helper gist." in FIX_INDEX, True)
expect("fixture: tier 1 carries no signature -- that is tier 2's whole job",
       "b: int=3" in FIX_INDEX, False)
expect("fixture: tier 1 omits a private module-level function",
       "_private_helper" in FIX_INDEX, False)
expect("fixture: tier 1 omits methods entirely",
       "Thing.value" in FIX_INDEX, False)
LONG = FIXTURE.replace("Fixture module, first line.",
                       "Fixture module, " + "very " * 40 + "long first line.")
LONG_INDEX = gen_map.render_index([fixture_module(LONG)])
expect("fixture: a long gist is cut, not carried -- tier 1 stays a gist",
       ("very very very" in LONG_INDEX and "…" in LONG_INDEX
        and "long first line." not in LONG_INDEX), True)
expect("fixture: ...and a short one is carried whole",
       "Helper gist." in LONG_INDEX, True)


# ---------------------------------------------------------------------------
print("\n11. the tag scheme: unique to grep, and every cited tag resolves")
# ---------------------------------------------------------------------------
# Unique BY CONSTRUCTION is a claim, and this is the measurement of it: the
# index is a dict, so a collision would silently drop an entry, and the count
# of tags must therefore equal the count of tagged things.
tagged_things = len(MODULES) + sum(len(m.entries) for m in MODULES)
expect("every module, class, method, function and constant has its own tag",
       len(TAGS), tagged_things)
expect("the tag index is worth having", len(TAGS) >= 500, True)

# TEETH for the collision rule. The live tree happens to be almost free of
# duplicate names, so asserting over it proves nothing about the rule that
# separates them. Two fixture modules that both define `Thing` and both define
# `Thing.method` must come out with four distinct tags.
_a = gen_map.parse_text("scripts/fixture/one.py",
                        "class Thing:\n    def method(self): pass\n")
_b = gen_map.parse_text("scripts/fixture/two.py",
                        "class Thing:\n    def method(self): pass\n")
gen_map.assign_tags([_a, _b])
expect("fixture: a name defined in two modules gets two distinct tags",
       sorted(e.tag for m in (_a, _b) for e in m.entries),
       ["one.Thing", "one.Thing.method", "two.Thing", "two.Thing.method"])
_c = gen_map.parse_text("scripts/fixture/three.py",
                        "class Thing:\n"
                        "    @property\n    def v(self): pass\n"
                        "    @v.setter\n    def v(self, x): pass\n")
gen_map.assign_tags([_c])
expect("fixture: a property and its setter do not share a tag",
       sorted(e.tag for e in _c.entries if e.kind == "method"),
       ["Thing.v", "Thing.v.setter"])
_d = gen_map.parse_text("scripts/fixture/four.py",
                        "class Thing: pass\n\n\nclass Thing: pass\n")
gen_map.assign_tags([_d])
expect("fixture: a name redefined in ONE scope is still separated",
       len({e.tag for e in _d.entries}), 2)

# Every tag a document cites must resolve. Both halves again: the count is
# asserted too, because a rule that iterates nothing passes forever.
cited: list[tuple[str, str]] = []
for rel in sorted(LIVE):
    if rel == gen_map.INDEX_REL:
        continue                     # the index citing itself proves nothing
    for match in gen_map.TAG_REF.finditer(read(rel)):
        cited.append((rel, match.group(1)))
unresolved = [f"{rel} cites {gen_map.TAG}{tag}, which resolves nowhere"
              for rel, tag in cited
              if tag not in TAGS and tag not in SOURCE_TAGS]
expect_empty("every #TAG a document cites resolves in the tree", unresolved)
expect("documents actually use the scheme", len(cited) >= 10, True)

# A hand-placed `#TAG:` comment is the escape hatch for a line that is not a
# definition. It must be unique, and it must sit INSIDE the thing it names --
# otherwise `#TAG:GameEntity` could be dropped on an unrelated line and an
# anchor would follow it there.
expect_empty("no hand-placed #TAG: comment is duplicated in the tree",
             DUPLICATE_SOURCE_TAGS)
misplaced = []
for _tag, (_rel, _no, _line) in sorted(SOURCE_TAGS.items()):
    site = TAGS.get(_tag)
    if site is None:
        continue                     # a topic tag: it names no symbol, by design
    if site.relpath != _rel or not (site.lineno <= _no <= site.end_lineno):
        misplaced.append(f"{_rel}:{_no} places {gen_map.TAG}{_tag}, but that "
                         f"tag names {site.kind} at {site.address}")
expect_empty("a hand-placed #TAG: sits inside the symbol it names", misplaced)
if SOURCE_TAGS:
    print(f"    note  {len(SOURCE_TAGS)} hand-placed #TAG: comment(s) in the tree")
else:
    print("    note  no hand-placed #TAG: comment in the tree yet; every anchor "
          "resolves through the generated map")


# ---------------------------------------------------------------------------
print()
print(f"documents        : {len(LAYERS)}  "
      f"(L0 1, L1 {sum(1 for v in LAYERS.values() if v == 'L1')}, "
      f"L2 {sum(1 for v in LAYERS.values() if v == 'L2')}, "
      f"L3 {len(ARCHIVE)})")
print(f"roster           : {len(ROSTER)} checks")
print(f"behavior tokens  : {len(TOKENS)}")
print(f"anchors verified : {len(anchors)} (all by #TAG)")
print(f"tags cited       : {len(cited)} across {len(set(r for r, _ in cited))} document(s)")
print(f"mapped modules   : {len(MODULES)}, {len(TAGS)} tags")
print(f"bare line refs   : {ref_count} left in live documents "
      f"({', '.join(f'{k} {v}' for k, v in sorted(LINE_ANCHOR_DEBT.items())) or 'none'})")
print(f"assertions       : {checked}")
if failures:
    print(f"\nFAIL ({len(failures)}): " + "; ".join(failures[:8]))
    sys.exit(1)
print("\nALL DOC ASSERTIONS PASS")
