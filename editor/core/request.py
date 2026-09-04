"""Requests -- how a note typed under a panel becomes work an AI can do.

THE LOOP
--------
    1. You type into the prompt strip at the bottom of a panel.
       The panel knows its scope, so the note is addressed automatically.
    2. Notes accumulate in the Manifest panel. You review them, reorder
       them, delete the ones you changed your mind about.
    3. "Ship" writes a *bundle* -- a self-contained directory containing
       the notes, the genre rules, the current state of everything the
       notes touch, and the exact command vocabulary.
    4. Claude Code (or Codex, or anything) reads the bundle and writes
       `response.jsonl`.
    5. The editor validates every line, applies them as ONE transaction,
       and shows you what changed. Undo takes back the whole response.

WHY A BUNDLE AND NOT A PROMPT STRING
------------------------------------
  * **Location.** A note carries a scope, and the bundle turns that scope
    into concrete file paths. The responder does not have to guess where
    "the actors list" lives.
  * **Conditioning without bloat.** The genre pack is a page. It replaces
    the several thousand words of context that "make me a platformer"
    would otherwise need, and it is the same page every time, so it is
    reviewable.
  * **The vocabulary cannot drift.** COMMANDS.md is generated from the
    registry that executes the response. A verb the editor cannot run
    cannot appear in the docs the responder reads.

WHAT A RESPONSE MAY DO
----------------------
Emit commands. That is the paved road, and it is transactional, undoable,
and reviewable.

Code changes are the escape hatch, for genuinely new mechanics -- a jump
arc, a targeting rule. Those are ordinary edits to `scripts/`, reviewed as
ordinary diffs. The bundle names the files involved so the responder starts
in the right place, and RULES.md states what must not be touched.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from editor.core.commands import (
    Command,
    all_verbs,
    describe_all,
    verbs_accepting,
)
from editor.core.errors import (
    PyoneerRequestError,
    PyoneerResponseParseError,
)
from editor.core.scope import SCOPE_KINDS, Scope, code_locations
from editor.core import event_script

REQUESTS_DIR = os.path.join("editor", "requests")

NOTE_KINDS: tuple[str, ...] = ("change", "question", "constraint")

RESPONSE_FILE = "response.jsonl"
NOTES_FILE = "NOTES.md"

#: The scope kinds a genre pack's rules actually speak to.
#:
#: A pack declares two things and only two: WHICH LAYERS a map has (with the
#: class an object placed on one starts as) and WHICH TABLES exist, with what
#: columns. Both are statements about the project's SHAPE. So the pack has
#: something to say wherever the shape itself is editable -- a whole map,
#: whose layer set can gain and lose layers; a whole table, which can be
#: created, dropped or given a column; the project, whose genre can be
#: swapped; the pack itself.
#:
#: One segment deeper, the vocabulary only edits CONTENT -- this layer's
#: cells, this object's properties, this row's values, this column -- and a
#: pack says nothing about content. That is why RULES.md is DROPPED rather
#: than trimmed for those: shipping 1,900 tokens of layer and column tables
#: to condition "make the shoreline two tiles wider" is the habit the scoped
#: bundle exists to break.
#:
#: The one edge, stated rather than hidden: `map.layer.remove` reaches a
#: layer scope, and removing a layer the pack marks required IS a rule
#: violation -- the stream does not refuse it. The bundle is not blind to
#: that, because `_context` prints `project.problems()` live in CONTEXT.md,
#: in every bundle, scoped or not. Prescriptive prose is dropped; the
#: measured violations are not.
RULES_SCOPE_KINDS: frozenset[str] = frozenset({"project", "genre", "map", "table"})


def rules_travel_with(scope: Scope) -> bool:
    """Whether a bundle scoped to `scope` should carry the genre pack."""
    return scope.kind in RULES_SCOPE_KINDS


# --------------------------------------------------------------------------
# Notes and manifests
# --------------------------------------------------------------------------

@dataclass
class Note:
    """One comment left on one part of the project."""

    scope: Scope
    text: str
    kind: str = "change"
    created: str = ""

    def __post_init__(self) -> None:
        if self.kind not in NOTE_KINDS:
            raise PyoneerRequestError(
                f"note kind {self.kind!r} is not one of {list(NOTE_KINDS)}")
        if not self.text.strip():
            raise PyoneerRequestError("an empty note carries no request",
                                      scope=str(self.scope))
        if not self.created:
            self.created = datetime.now().isoformat(timespec="seconds")

    def to_json(self) -> dict[str, Any]:
        return {"scope": str(self.scope), "text": self.text,
                "kind": self.kind, "created": self.created}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Note":
        return cls(Scope.parse(raw["scope"]), raw["text"],
                   raw.get("kind", "change"), raw.get("created", ""))


@dataclass
class Manifest:
    """The staged notes, waiting to be shipped as one request."""

    title: str = ""
    notes: list[Note] = field(default_factory=list)

    def add(self, note: Note) -> Note:
        self.notes.append(note)
        return note

    def remove(self, index: int) -> Note:
        try:
            return self.notes.pop(index)
        except IndexError:
            raise PyoneerRequestError(
                f"no note at index {index}", count=len(self.notes)) from None

    def clear(self) -> None:
        self.notes.clear()
        self.title = ""

    @property
    def empty(self) -> bool:
        return not self.notes

    def scopes(self) -> list[Scope]:
        """Every distinct scope, in first-mentioned order."""
        seen: list[Scope] = []
        for note in self.notes:
            if note.scope not in seen:
                seen.append(note.scope)
        return seen

    def grouped(self) -> list[tuple[Scope, list[Note]]]:
        return [(scope, [n for n in self.notes if n.scope == scope])
                for scope in self.scopes()]

    def suggested_title(self) -> str:
        if self.title.strip():
            return self.title.strip()
        first = self.notes[0].text.strip() if self.notes else "request"
        words = re.split(r"\s+", first)[:8]
        return " ".join(words).rstrip(".,;:")

    def to_json(self) -> dict[str, Any]:
        return {"title": self.suggested_title(),
                "notes": [n.to_json() for n in self.notes]}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Manifest":
        return cls(raw.get("title", ""),
                   [Note.from_json(n) for n in raw.get("notes", [])])


# --------------------------------------------------------------------------
# Writing a bundle
# --------------------------------------------------------------------------

@dataclass
class Bundle:
    """A written request on disk."""

    directory: str
    identifier: str
    files: list[str]

    @property
    def response_path(self) -> str:
        return os.path.join(self.directory, RESPONSE_FILE)

    @property
    def has_response(self) -> bool:
        return os.path.isfile(self.response_path)


def write_bundle(project: Any, manifest: Manifest, *,
                 requests_dir: str | None = None,
                 scoped: Scope | None = None) -> Bundle:
    """Write a self-contained request directory. Returns where it went.

    `scoped` is the piecemeal grain. Pass one address and the bundle is cut
    for it: `COMMANDS.md` holds only the verbs that address it, `RULES.md`
    is dropped unless the genre pack speaks to it (`rules_travel_with`), and
    `manifest.json` gains `scoped` and `verbs` so the payload is checkable
    rather than merely smaller. Measured on this tree: 25,202 bytes of
    vocabulary become 5,582 for one tile layer.

    THE ZERO-VERB REFUSAL LIVES HERE, not in the caller. A bundle aimed at a
    scope no verb accepts ships a vocabulary the responder structurally
    cannot answer with -- an empty instruction set that reads like an
    instruction set -- and that is a property of the BUNDLE, so putting the
    refusal at the chokepoint means no future caller can route around it
    (law 7: decide it, do not default into it).
    """
    if manifest.empty:
        raise PyoneerRequestError(
            "nothing staged; type a note under a panel first")

    vocabulary = all_verbs() if scoped is None else verbs_accepting((scoped,))
    if scoped is not None and not vocabulary:
        raise PyoneerRequestError(
            f"no verb in this editor accepts {scoped}, so a request scoped "
            f"to it would ship an empty vocabulary and the responder could "
            f"not answer with a single command. Aim the note at something a "
            f"verb reaches -- a map, a layer, an object, a table, a row -- "
            f"or stage it and ship the whole manifest instead.",
            scope=str(scoped), kind=scoped.kind, verbs=0)
    carries_rules = scoped is None or rules_travel_with(scoped)

    base = requests_dir or os.path.join(project.root, REQUESTS_DIR)
    os.makedirs(base, exist_ok=True)
    identifier = _next_id(base, manifest.suggested_title())
    directory = os.path.join(base, identifier)
    os.makedirs(directory, exist_ok=False)

    written: list[str] = []

    def put(name: str, text: str) -> None:
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
        written.append(path)

    put("BRIEF.md", _brief(project, manifest, identifier,
                           scoped=scoped, carries_rules=carries_rules))
    put("REQUEST.md", _request(project, manifest))
    if carries_rules:
        put("RULES.md", _rules(project))
    put("CONTEXT.md", _context(project, manifest))
    put("COMMANDS.md", describe_all()
        if scoped is None else describe_all(scopes=(scoped,)))

    payload: dict[str, Any] = {
        "id": identifier,
        "genre": project.genre.id,
        "root": project.root,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    if scoped is not None:
        # The machine-readable half of the sliced COMMANDS.md. This is what
        # makes the payload checkable: a filter that drifted from
        # `Verb.validate` shows up here as a name, not as a size.
        payload["scoped"] = str(scoped)
        payload["verbs"] = [spec.name for spec in vocabulary]
    payload.update(manifest.to_json())
    put("manifest.json", json.dumps(payload, indent=2))

    return Bundle(directory, identifier, written)


def _next_id(base: str, title: str) -> str:
    existing = [d for d in os.listdir(base)
                if os.path.isdir(os.path.join(base, d)) and d[:4].isdigit()]
    number = max((int(d[:4]) for d in existing), default=0) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "request"
    return f"{number:04d}-{slug}"


def _brief(project: Any, manifest: Manifest, identifier: str, *,
           scoped: Scope | None = None,
           carries_rules: bool = True) -> str:
    """The protocol, and NOTHING ELSE.

    This is the one hand-written file in a bundle, so it is held to one
    rule: it may state how the exchange works and it may not state what the
    code does. A protocol claim is falsified the moment the protocol fails;
    a code claim is falsified in silence. `docs/BEHAVIORS.md`'s hand-written
    preamble carried two such lies for months while matching its generator
    byte for byte, which is the measured cost of the other habit.

    So the file list below is BUILT from what was actually written, not
    typed out once and trusted: a brief that names `RULES.md` in a bundle
    that dropped it is a protocol claim that is already false.
    """
    rows = []
    if carries_rules:
        rows.append("| `RULES.md` | the genre's conventions. Non-negotiable. |")
    rows += [
        "| `CONTEXT.md` | the current state of everything the notes touch. |",
        "| `REQUEST.md` | the notes themselves, grouped by what they are about. |",
        "| `COMMANDS.md` | the exact vocabulary for changing project data. |",
    ]
    reading = "\n".join(rows)
    # Two sentences below point at RULES.md by name. In a bundle that
    # dropped it they would send the responder to a file that is not there,
    # which is exactly the falsifiable-in-silence shape this docstring
    # refuses, so they are written from what was put on disk.
    limits = ("`RULES.md` states what must not change"
              if carries_rules else
              "`docs/PLAN_SCENES.md` and `CLAUDE.md` state what must not change")
    event_rule = ("`RULES.md` says what that means concretely"
                  if carries_rules else
                  "`CLAUDE.md` law 3 says what that means concretely")
    if scoped is None:
        aim = ""
    else:
        aim = (f"\n**Scope:** `{scoped}`. This request is about that address "
               f"and `COMMANDS.md` holds only the verbs that reach it -- a "
               f"command aimed anywhere else is refused and takes the whole "
               f"response down with it.\n")
        if not carries_rules:
            aim += ("\nThere is no `RULES.md` in this bundle. The genre pack "
                    "declares which layers and tables a project has, and this "
                    "request edits what is inside one of them, so the pack "
                    "has nothing to say about it. Any rule the project is "
                    "already violating is printed live in `CONTEXT.md`.\n")
    return f"""# Request {identifier}

You are extending a game built on the Pyoneer engine. The human author has
left notes on specific parts of the project; your job is to carry them out.

**Read in this order:**

| file | what it is |
|---|---|
{reading}

**Project:** `{project.root}`
**Genre:** `{project.genre.id}` -- {project.genre.title}
{aim}
## How to answer

Write `{RESPONSE_FILE}` in this directory: one JSON object per line, no
wrapping array, no trailing commas. Each line is a command from
`COMMANDS.md`.

```
{{"verb": "table.row.add", "scope": "table:actors", "args": {{"id": "hero", "values": {{"hp": 30}}}}}}
{{"verb": "map.object.add", "scope": "map:test/layer:entity", "args": {{"type": "PlayerStart", "x": 64, "y": 64}}}}
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
   likely to touch, and {limits}.
3. Write `{NOTES_FILE}` in this directory explaining what you changed and
   why. The author reads it as the review summary.

Run `.venv/Scripts/python.exe tools/check_all.py` before you finish. If a
smoke field moves, say which one and why in `{NOTES_FILE}`. Do not
re-baseline something you cannot explain.

## What not to do

- Do not invent verbs. If the vocabulary cannot express something, say so in
  `{NOTES_FILE}` and do that part as a code change instead.
- Do not edit `.tmx` files as text. They round-trip byte-exactly through
  `MapDocument`, and a hand-edit destroys that.
- Do not restructure the event system. It is the one thing the whole engine
  rests on; {event_rule}.
"""


def _request(project: Any, manifest: Manifest) -> str:
    out = [f"# {manifest.suggested_title()}", "",
           f"{len(manifest.notes)} note"
           f"{'' if len(manifest.notes) == 1 else 's'} across "
           f"{len(manifest.scopes())} scope"
           f"{'' if len(manifest.scopes()) == 1 else 's'}.", ""]
    for scope, notes in manifest.grouped():
        out.append(f"## `{scope}`")
        out.append("")
        paths = code_locations(scope)
        if paths:
            out.append("*Likely files:* "
                       + ", ".join(f"`{p}`" for p in paths))
            out.append("")
        for note in notes:
            marker = {"change": "", "question": "**Question.** ",
                      "constraint": "**Constraint.** "}[note.kind]
            out.append(f"- {marker}{note.text.strip()}")
        out.append("")
    return "\n".join(out)


def _rules(project: Any) -> str:
    pack = project.genre
    head = [f"# {pack.title}", "", pack.summary, ""]
    if pack.layers:
        head += ["## Layers this genre expects", "",
                 "| layer | kind | depth | required | meaning |",
                 "|---|---|---|---|---|"]
        for layer in pack.layers:
            head.append(f"| `{layer.name}` | {layer.kind} | {layer.depth} | "
                        f"{'yes' if layer.required else 'no'} | {layer.doc} |")
        head.append("")
    if pack.tables:
        head += ["## Data tables this genre expects", ""]
        for table in pack.tables:
            head.append(f"### `{table.name}` -- {table.title}")
            head.append("")
            if table.doc:
                head += [table.doc, ""]
            if table.fields:
                head += ["| column | type | required | meaning |",
                         "|---|---|---|---|"]
                for f in table.fields:
                    head.append(f"| `{f.name}` | {f.type} | "
                                f"{'yes' if f.required else 'no'} | {f.doc} |")
                head.append("")
    if pack.rules_markdown:
        head += ["---", "", pack.rules_markdown]
    return "\n".join(head)


def _context(project: Any, manifest: Manifest) -> str:
    out = ["# Current state", "",
           "Everything the notes touch, as it is right now.", ""]
    for scope in manifest.scopes():
        out.append(f"## `{scope}`")
        out.append("")
        out.extend(describe_scope(project, scope))
        out.append("")

    problems = project.problems()
    if problems:
        out += ["## Open rule violations", "",
                "Not necessarily yours to fix -- listed so you do not "
                "mistake one for something you broke.", ""]
        for violation in problems:
            out.append(f"- {violation}")
        out.append("")
    return "\n".join(out)


def describe_scope(project: Any, scope: Scope) -> list[str]:
    """A compact, factual rendering of one scope. Shared with the UI.

    ONE ARM PER KIND IN `SCOPE_KINDS`, AND A RAISE UNDERNEATH. The arm that
    used to sit at the bottom returned *"(no description available for this
    scope kind)"* -- a plausible default, and the worst possible one here:
    the bundle still writes, still looks complete, and the CONTEXT.md the
    responder conditions on says nothing at all about the thing it is being
    asked to change. A missing arm is a build error, not a footnote, so the
    kind that has no arm stops the ship (law 7).
    """
    kind = scope.kind
    try:
        if kind == "project":
            return _describe_project(project)
        if kind == "genre":
            return [f"Genre `{project.genre.id}` -- {project.genre.title}.",
                    "", project.genre.summary]
        if kind == "map":
            return _describe_map(project, scope)
        if kind == "layer":
            return _describe_layer(project, scope)
        if kind == "object":
            return _describe_object(project, scope)
        if kind == "table":
            return _describe_table(project, scope)
        if kind == "row":
            return _describe_row(project, scope)
        if kind == "field":
            return _describe_field(project, scope)
        if kind == "code":
            return _describe_code(project, scope)
        if kind == "script":
            return _describe_script(project, scope)
        if kind == "assets":
            return ["See `docs/ASSETS.md`. The art that ships is generated: "
                    "`data/art/` is tracked and `tools/art/` draws it. Your "
                    "own sheets go in `data/graphics/`, which wins over it."]
    except Exception as exc:                                    # noqa: BLE001
        return [f"*(could not be read: {type(exc).__name__}: {exc})*"]
    raise PyoneerRequestError(                          #TAG:describe_scope_has_no_default
        f"describe_scope has no arm for a {kind!r} scope, so a bundle about "
        f"{scope} would ship a CONTEXT.md that silently describes nothing. "
        f"Add the arm in the same change that adds the kind.",
        scope=str(scope), kind=kind, known=list(SCOPE_KINDS))


def _describe_project(project: Any) -> list[str]:
    return [
        f"- genre: `{project.genre.id}`",
        f"- maps: {', '.join('`' + m + '`' for m in project.map_names()) or 'none'}",
        f"- tables: {', '.join('`' + t + '`' for t in project.table_names()) or 'none'}",
        f"- root: `{project.root}`",
    ]


def _describe_map(project: Any, scope: Scope) -> list[str]:
    document = project.map(scope.require("map"))
    out = [f"{document.width} x {document.height} tiles, "
           f"{document.tile_width} x {document.tile_height} px each.", "",
           "| layer | kind |", "|---|---|"]
    tile_layers = set(document.tile_layer_names())
    for name in document.layer_names():
        out.append(f"| `{name}` | {'tile' if name in tile_layers else 'object'} |")
    return out


def _describe_layer(project: Any, scope: Scope) -> list[str]:
    document = project.map(scope.require("map"))
    name = scope.require("layer")
    if name in document.tile_layer_names():
        layer = document.tile_layer(name)
        gids = layer.gids()
        used = sorted({g for g in gids if g})
        occupied = sum(1 for g in gids if g)
        out = [f"Tile layer, {layer.width} x {layer.height}.",
               f"{occupied} of {len(gids)} cells occupied.",
               f"{len(used)} distinct gids."]
        if used:
            shown = ", ".join(str(g) for g in used[:24])
            more = "" if len(used) <= 24 else f", ... (+{len(used) - 24})"
            out.append(f"gids in use: {shown}{more}")
        return out
    if name in document.object_layer_names():
        layer = document.object_layer(name)
        objects = layer.objects()
        out = [f"Object layer with {len(objects)} object"
               f"{'' if len(objects) == 1 else 's'}."]
        if objects:
            out += ["", "| id | class | name | x | y | properties |",
                    "|---|---|---|---|---|---|"]
            for obj in objects[:50]:
                props = obj.properties.as_dict()
                rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(props.items()))
                out.append(f"| {obj.id} | `{obj.type or '-'}` | "
                           f"{obj.name or '-'} | {obj.x:g} | {obj.y:g} | "
                           f"{rendered or '-'} |")
            if len(objects) > 50:
                out.append(f"| ... | | | | | (+{len(objects) - 50} more) |")
        return out
    return [f"*(no layer named {name!r}; this map has "
            f"{document.layer_names()})*"]


def _describe_object(project: Any, scope: Scope) -> list[str]:
    document = project.map(scope.require("map"))
    layer = document.object_layer(scope.require("layer"))
    found = layer.find(int(scope.require("object")))
    if found is None:
        return [f"*(object {scope.require('object')} is not in this layer)*"]
    out = [f"- class: `{found.type or '-'}`",
           f"- name: `{found.name or '-'}`",
           f"- position: ({found.x:g}, {found.y:g})",
           f"- size: {found.width:g} x {found.height:g}"]
    props = found.properties.as_dict()
    if props:
        out.append("- properties:")
        for key, value in sorted(props.items()):
            out.append(f"  - `{key}` = `{value!r}` ({type(value).__name__})")
    return out


def _describe_field(project: Any, scope: Scope) -> list[str]:
    """One column of one table -- what it is, and what the rows put in it."""
    table_name = scope.require("table")
    name = scope.require("field")
    if not project.has_table(table_name):
        return [f"*(no table {table_name!r}, so nothing named {name!r} "
                f"in it either)*"]
    table = project.table(table_name)
    column = table.field(name)
    if column is None:
        return [f"*(table `{table_name}` has no column {name!r}; it has "
                f"{[c.name for c in table.columns]})*"]
    declared = project.genre.table(table_name)
    required = bool(declared and declared.field(name)
                    and declared.field(name).required)
    default = column.coerced_default()
    # Both halves of what an author actually wants to know before touching a
    # column: what it is declared as, and what is really sitting in it.
    values = [row[name] for row in table.rows.values() if name in row]
    non_default = sum(1 for v in values if v != default)
    out = [f"- table: `{table_name}`",
           f"- type: `{column.type}`",
           f"- default: `{default!r}`",
           f"- required by genre `{project.genre.id}`: "
           f"{'yes -- it cannot be removed' if required else 'no'}",
           f"- meaning: {column.doc or '*(undocumented)*'}",
           f"- {len(values)} of {len(table.rows)} row"
           f"{'' if len(table.rows) == 1 else 's'} carry a value, "
           f"{non_default} of them different from the default"]
    if values:
        shown = ", ".join(repr(v) for v in values[:12])
        more = "" if len(values) <= 12 else f", ... (+{len(values) - 12})"
        out.append(f"- values in use: {shown}{more}")
    return out


def _describe_script(project: Any, scope: Scope) -> list[str]:
    """One event script: its loadouts, its pages, and every id in it.

    THREE FACTS A VERB LIST CANNOT CARRY, which is the whole reason this arm
    exists rather than letting `script.*` verbs speak for themselves:

      1. THE IDS. `into`, `after` and `node` are all ids, and pages and nodes
         share ONE namespace. A responder that invents an id addresses
         nothing, and `script.node.add` refuses it -- correctly, and one
         round trip too late. Every id this document holds is printed.
      2. THE LOADOUTS, which decide which op names are legal in a `do`. An op
         outside them is refused by the reader at edit time, so shipping the
         declared list is shipping the vocabulary.
      3. THE ARMS. `arm` is refused for a container that does not have one,
         so the shape of each `if` -- how many `elif` arms, whether there is
         an `else` -- has to be visible before a node can be aimed into it.

    A script that is not there is NOT a raise: the same `*(...)*` shape every
    other arm uses for an address that parses and resolves to nothing, and it
    names the verb that would create it. The raise is reserved for a scope
    KIND with no arm at all, which is a build error rather than a fact about
    this project.
    """
    library = event_script.scripts_of(project)
    name = scope.require("script")
    if not library.has(name):
        known = ", ".join("`" + n + "`" for n in library.names())
        return [f"*(no script named `{name}` in this project; it has "
                f"{known or 'none'}. `script.create` on this scope makes "
                f"it.)*"]
    document = library.document(name)
    out = [f"- title: `{document.title or '-'}`",
           f"- loadouts: {', '.join('`' + l + '`' for l in document.loadouts)}",
           f"- pages: {len(document.pages)}",
           f"- every id in this document (ONE namespace, pages and nodes "
           f"together): {', '.join('`' + i + '`' for i in document.ids()) or 'none'}"]
    if library.variables is None:
        out.append("- no scene declares this script's variables yet, so a "
                   "`when` condition cannot be authored: the reader refuses "
                   "one until a `vars` schema exists.")
    for page in document.pages:
        out += [""] + _describe_script_page(page)
    return out


def _describe_script_page(page: dict) -> list[str]:
    """One page and its whole body, indented the way the arms nest."""
    head = f"### page `{page.get('id', '?')}`"
    facts = []
    for key in ("trigger", "once", "cooldown_ms", "payload", "note"):
        if key in page and page[key] != event_script.PAGE_DEFAULTS.get(key):
            facts.append(f"{key}=`{page[key]!r}`")
    if page.get("when"):
        facts.append(f"when=`{page['when']!r}`")
    out = [head + ("  -- " + ", ".join(facts) if facts else "")]
    out += _describe_script_body(page.get("body") or (), 0)
    return out


def _describe_script_body(body: Iterable[dict], depth: int) -> list[str]:
    """The nodes of one container, in the order the frame runs them."""
    pad = "  " * depth
    out: list[str] = []
    for node in body:
        node_id = node.get("id", "?")
        control = next((k for k in event_script.CONTROL_KINDS if k in node),
                       None)
        if control is None:
            out.append(f"{pad}- `{node_id}` do `{node.get('do', '?')}`")
            continue
        out.append(f"{pad}- `{node_id}` {control} `{node[control]!r}`")
        out.append(f"{pad}  - arm `then`:")
        out += _describe_script_body(node.get("then") or (), depth + 2)
        for index, arm in enumerate(node.get("elif") or ()):
            out.append(f"{pad}  - arm `elif:{index}` when `{arm.get('when')!r}`:")
            out += _describe_script_body(arm.get("then") or (), depth + 2)
        if "else" in node:
            out.append(f"{pad}  - arm `else`:")
            out += _describe_script_body(node.get("else") or (), depth + 2)
    return out or [pad + "- *(empty)*"]


def _describe_code(project: Any, scope: Scope) -> list[str]:
    """A source label. Deliberately says what it is NOT.

    A `code:` scope addresses the tree, not the document, so no verb accepts
    one -- measured, `verbs_accepting` returns nothing for it. A note left
    here is answered with an ordinary edit and an ordinary diff, and saying
    that plainly is the difference between a responder writing code and a
    responder inventing a verb to avoid writing code.
    """
    out = [f"Label `{scope.name}`. This addresses SOURCE, not project data: "
           f"no command verb accepts a `code:` scope, so this note is "
           f"answered by editing files and describing the change in "
           f"`{NOTES_FILE}` -- not by a line in `{RESPONSE_FILE}`."]
    paths = code_locations(scope)
    if paths:
        out += ["", "Files: " + ", ".join(f"`{p}`" for p in paths)]
    return out


def _describe_table(project: Any, scope: Scope) -> list[str]:
    name = scope.require("table")
    if not project.has_table(name):
        declared = project.genre.table(name)
        if declared is None:
            return [f"*(no table {name!r}, and the genre does not declare one)*"]
        return [f"*(the genre declares `{name}` but the project has not "
                f"created it. `table.create` with scope `table:{name}` takes "
                f"the declared shape.)*"]
    table = project.table(name)
    out = [f"{len(table)} row{'' if len(table) == 1 else 's'}, "
           f"{len(table.columns)} column"
           f"{'' if len(table.columns) == 1 else 's'}.", "",
           "| column | type | default | meaning |", "|---|---|---|---|"]
    for column in table.columns:
        out.append(f"| `{column.name}` | {column.type} | "
                   f"`{column.coerced_default()!r}` | {column.doc} |")
    if table.rows:
        out += ["", "| id | " + " | ".join(c.name for c in table.columns) + " |",
                "|---|" + "---|" * len(table.columns)]
        for row_id, row in list(table)[:40]:
            cells = " | ".join(repr(row.get(c.name)) for c in table.columns)
            out.append(f"| `{row_id}` | {cells} |")
        if len(table) > 40:
            out.append(f"| ... | (+{len(table) - 40} more rows) |")
    return out


def _describe_row(project: Any, scope: Scope) -> list[str]:
    table = project.table(scope.require("table"))
    row = table.require_row(scope.require("row"))
    return [f"- `{key}` = `{value!r}`" for key, value in sorted(row.items())]


# --------------------------------------------------------------------------
# Reading a response
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```")


def parse_response(text: str, *, source: str = "response.jsonl") -> list[Command]:
    """Turn a JSON Lines response into commands, loudly.

    Tolerates blank lines and a wrapping markdown fence, because a model
    that wraps its output in ```json has not made a semantic mistake. It
    tolerates nothing else -- a malformed line names its own line number
    rather than failing the file.
    """
    commands: list[Command] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or _FENCE.match(raw):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PyoneerResponseParseError(
                f"line {number} is not valid JSON: {exc.msg}",
                line=number, source=source,
                text=line[:120]) from exc
        if isinstance(payload, list):
            raise PyoneerResponseParseError(
                f"line {number} is a JSON array; the format is one command "
                f"object per line, not a wrapping array",
                line=number, source=source)
        try:
            commands.append(Command.from_json(payload))
        except Exception as exc:                                # noqa: BLE001
            raise PyoneerResponseParseError(
                f"line {number}: {exc}", line=number, source=source) from exc
    if not commands:
        raise PyoneerResponseParseError(
            "the response contains no commands", source=source)
    return commands


def read_response(path: str) -> list[Command]:
    if not os.path.isfile(path):
        raise PyoneerRequestError(f"no response at {path}", path=path)
    with open(path, "r", encoding="utf-8") as handle:
        return parse_response(handle.read(), source=path)


