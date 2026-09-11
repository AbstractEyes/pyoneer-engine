"""The event-script document -- the AUTHORING half of `data/project/scripts/`.

`scripts/loaders/script_file.py` is the READING half: it parses, judges and
hands back frozen records. This is the other end of the same file, and the
two are joined by the FILES and never by an import in that direction
(law 2). Everything here is mutable, addressed by id, and canonical on the
way out.

THE READER IS THE ONLY JUDGE
----------------------------
There is deliberately no second implementation of "is this document legal".
Every mutation runs the document through `script_file.parse_script` -- the
same function the engine calls at boot -- and a document that would not
load is REFUSED and rolled back before the verb returns. So the author
finds out at edit time, in the editor, with one thing changed, instead of
at run time with a whole project in flight. A second copy of those rules
would be the 425-duplicate-line shape law 2's corollary was paid for.

What this module adds on top of the reader is only what the reader cannot
see, because it judges a finished document and never a change to one:

    * where a node IS -- its container, its arm and its predecessor, so a
      removal can be inverted into a restore that lands in the same arm at
      the same place
    * whether an `after` anchor is a sibling of the thing being placed
    * whether a move would put a node inside its own subtree

A CANONICAL RENDERING, AND WHY THE INVERSES DEPEND ON IT
--------------------------------------------------------
`to_json` emits a key only when it carries information: `note`, `payload`,
`once` and `cooldown_ms` disappear at their format defaults, and so does an
op argument sitting at the default its `OpSpec` declares. Required keys are
always written.

That is not tidiness. It is what makes `script.page.set` and
`script.node.set` their own exact inverses: "the key is absent" and "the
key holds its default" are ONE state, so setting a key back to its default
restores the document byte for byte instead of leaving `"once": false`
behind where there was no key at all. The alternative -- a second `unset`
verb per level, as `map.layer.set` needs -- costs two permanent names to
buy the same property.

A hand-edited file is therefore normalised the first time the editor saves
it. That is a real change to the bytes and it is deliberate: one document,
one rendering, one diff.

VARIABLES
---------
A condition names a variable, and only a scene's `vars` block says whether
that variable exists or what type it is. `scripts_of` reads that block --
`script_file.load_vars` over `data/project/scenes/*.json` -- and hands it to
the library, which is the ONE wire: `script_editor`, `object_editor` twice,
`genre.py`'s script check, `request.py` and `verbs.py` all reach a library
through that single function, so the schema arrives at six surfaces from one
line.

It was `None` for a day, and the day was measured: the game ran
`data/project/scripts/starter_greeting.json` and the editor could not OPEN
it, because its one condition names `greeted` and the only schema in the
tree was a dict in `main.py` that `editor/` may never import (law 2). The
Events screen said *"No event script in this project yet"* about a file that
had just run, and `New...` was inert behind the same refusal.

`variables` stays an assignable slot -- a check points it at its own fixture,
and the day a scene manager picks ONE scene instead of every scene, that is
where it reaches.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence
from weakref import WeakKeyDictionary

from editor.core.errors import PyoneerProjectError
from editor.core.project import PROJECT_DIR
from scripts.core.errors import PyoneerAssetMissingError
from scripts.game.flow import ops as op_registry
from scripts.loaders import script_file
from scripts.loaders.script_file import (
    CONTROL_KEYS,
    FORMAT,
    PAGE_KEYS,
    SCRIPT_TRIGGERS,
    VERSION,
)

SCRIPTS_SUBDIR: str = "scripts"
"""The directory under `data/project/` that holds event scripts.

Composed here from the editor's own `PROJECT_DIR` rather than imported from
the engine's `script_file.SCRIPTS_DIR`, because the two halves are joined
by the files. Composed and then CHECKED, one line below: an agreement
nobody measures is an agreement that drifts.
"""

if os.path.join(PROJECT_DIR, SCRIPTS_SUBDIR) != script_file.SCRIPTS_DIR:
    raise PyoneerProjectError(
        "the editor writes event scripts to %r and the engine reads them "
        "from %r; the two halves of one format have to name one directory"
        % (os.path.join(PROJECT_DIR, SCRIPTS_SUBDIR), script_file.SCRIPTS_DIR),
        editor=os.path.join(PROJECT_DIR, SCRIPTS_SUBDIR),
        engine=script_file.SCRIPTS_DIR)

SCENES_SUBDIR: str = "scenes"
"""The directory under `data/project/` that holds scene documents.

Composed from the editor's own `PROJECT_DIR` and then CHECKED against the
engine's `SCENES_DIR`, one line below, for the same reason `SCRIPTS_SUBDIR`
is: the two halves are joined by the files, and an agreement nobody measures
is an agreement that drifts.

The editor does not WRITE this file yet -- nothing here authors a scene -- so
this is a read-only address today. It is composed the same way anyway,
because the day a scene screen lands it writes to whatever this says.
"""

if os.path.join(PROJECT_DIR, SCENES_SUBDIR) != script_file.SCENES_DIR:
    raise PyoneerProjectError(
        "the editor looks for scene documents in %r and the engine reads "
        "them from %r; the two halves of one format have to name one "
        "directory"
        % (os.path.join(PROJECT_DIR, SCENES_SUBDIR), script_file.SCENES_DIR),
        editor=os.path.join(PROJECT_DIR, SCENES_SUBDIR),
        engine=script_file.SCENES_DIR)

CONTROL_KINDS: tuple[str, ...] = ("if", "while")
"""The two control node shapes. FILE FORMAT strings, both of them.

`script.node.add` accepts either one where it accepts an op name, because a
node is EITHER executable or control and there is no third shape to
disambiguate against. The registry is asked first whether it has claimed
the word, so an op named `if` collides loudly there instead of quietly
making every `if` in every document mean something else.
"""

for _kind in CONTROL_KINDS:
    if _kind not in CONTROL_KEYS:
        raise PyoneerProjectError(
            "control kind %r is not a key the reader accepts on a control "
            "node; it accepts %s" % (_kind, ", ".join(CONTROL_KEYS)))

PAGE_DEFAULTS: dict[str, Any] = {
    "note": "",
    "trigger": "use",
    "payload": "",
    "once": False,
    "cooldown_ms": 0,
    "when": [],
}
"""What a page key means when it is not written down.

Taken from `script_file`'s own `raw.get(key, default)` calls, one for one.
A page key that is not in here is not settable: `id` is the address and
`body` is what the node verbs are for.
"""

ALWAYS_ON_A_PAGE: tuple[str, ...] = ("id", "trigger", "when", "body")
"""Written even at their defaults -- a page's identity and its whole point."""

SETTABLE_PAGE_KEYS: tuple[str, ...] = tuple(sorted(PAGE_DEFAULTS))
SETTABLE_SCRIPT_KEYS: tuple[str, ...] = ("loadouts", "title")

NO_ANCHOR: str = ""
"""What an empty `after` means: the FRONT of the container, index 0.

Not the back. A body's first node has to be expressible or removing it
cannot be inverted, and appending is expressible either way -- it names the
last sibling. This is the whole reason the anchor is a sibling id and a
side rather than a position (`docs/PLAN_SCENES.md` 3.4): an ordered batch
of edits shifts every index it touches, and it shifts them silently.
"""

for _key in PAGE_DEFAULTS:
    if _key not in PAGE_KEYS:
        raise PyoneerProjectError(
            "page key %r is not one the reader accepts; it accepts %s"
            % (_key, ", ".join(PAGE_KEYS)))


# --------------------------------------------------------------------------
# Canonical rendering
# --------------------------------------------------------------------------

def _declared_defaults(spec) -> dict[str, Any]:
    """Every argument key an op takes -> (required, declared default)."""
    out: dict[str, Any] = {}
    for param in spec.params:
        out[param.key] = (param.required, param.default)
    for arg in spec.dynamic:
        out[arg.key] = (arg.required, arg.default)
    return out


def _canonical_when(raw: Any) -> list[dict[str, Any]]:
    return [dict(copy.deepcopy(item)) for item in (raw or ())]


def _canonical_node(raw: Mapping[str, Any], registry, where: str) -> dict:
    out: dict[str, Any] = {"id": raw["id"]}
    note = raw.get("note", "")
    if note:
        out["note"] = note

    if "do" in raw:
        spec = op_registry.resolve(raw["do"], registry, where)
        out["do"] = raw["do"]
        for key, (required, default) in _declared_defaults(spec).items():
            if key not in raw:
                continue
            value = raw[key]
            if required or value != default:
                out[key] = copy.deepcopy(value)
        return out

    kind = "if" if "if" in raw else "while"
    out[kind] = _canonical_when(raw[kind])
    out["then"] = [_canonical_node(n, registry, where)
                   for n in raw.get("then") or ()]
    arms = raw.get("elif") or ()
    if arms:
        out["elif"] = [
            {"when": _canonical_when(arm.get("when")),
             "then": [_canonical_node(n, registry, where)
                      for n in arm.get("then") or ()]}
            for arm in arms]
    otherwise = raw.get("else") or ()
    if otherwise:
        out["else"] = [_canonical_node(n, registry, where) for n in otherwise]
    return out


def _canonical_page(raw: Mapping[str, Any], registry, where: str) -> dict:
    out: dict[str, Any] = {
        "id": raw["id"],
        "trigger": raw.get("trigger", PAGE_DEFAULTS["trigger"]),
        "when": _canonical_when(raw.get("when")),
        "body": [_canonical_node(n, registry, where)
                 for n in raw.get("body") or ()],
    }
    for key in ("note", "payload", "once", "cooldown_ms"):
        value = raw.get(key, PAGE_DEFAULTS[key])
        if value != PAGE_DEFAULTS[key]:
            out[key] = value
    return out


# --------------------------------------------------------------------------
# Where a node is
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NodeSite:
    """A node's address as the VERBS spell it: container, arm, predecessor.

    `into` is a page id or a control node id -- pages and nodes share one id
    namespace precisely so that one address form reaches both. `arm` is
    `""` for a page body and `then` / `elif:N` / `else` inside a control
    node. `after` is the id of the sibling above it, or `""` for the front.

    `index` is carried for the code that has to splice a list and is NEVER
    written into a command: an index is the thing this whole addressing
    scheme exists to keep out of a file.
    """

    into: str
    arm: str
    after: str
    index: int

    def as_args(self) -> dict[str, str]:
        return {"into": self.into, "arm": self.arm, "after": self.after}


def _arm_bodies(node: Mapping[str, Any]) -> Iterator[tuple[str, list]]:
    """Every (arm token, list) a control node holds, in document order."""
    then = node.get("then")
    if then is not None:
        yield "then", then
    for index, arm in enumerate(node.get("elif") or ()):
        body = arm.get("then")
        if body is not None:
            yield "elif:%d" % index, body
    otherwise = node.get("else")
    if otherwise is not None:
        yield "else", otherwise


def _walk_bodies(nodes: Sequence[Mapping[str, Any]]
                 ) -> Iterator[tuple[str, str, list]]:
    for node in nodes:
        if "do" in node:
            continue
        for arm, body in _arm_bodies(node):
            yield node["id"], arm, body
            for entry in _walk_bodies(body):
                yield entry


def _containers(pages: Sequence[Mapping[str, Any]]
                ) -> Iterator[tuple[str, str, list]]:
    """(into, arm, the list) for every place a node can sit, in order."""
    for page in pages:
        body = page.get("body")
        if body is None:
            continue
        yield page["id"], "", body
        for entry in _walk_bodies(body):
            yield entry


def _predecessor(container: Sequence[Mapping[str, Any]], index: int) -> str:
    return container[index - 1]["id"] if index else NO_ANCHOR


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------

@dataclass
class ScriptDocument:
    """One `data/project/scripts/<id>.json`, open for editing.

    Holds the raw JSON tree rather than the reader's frozen records, for the
    same reason `DataTable` holds dicts: the document IS the file, and a
    model that paraphrased it would need a second round trip to prove it
    still said the same thing.
    """

    id: str
    title: str = ""
    loadouts: list[str] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    dirty: bool = False

    # -- rendering ---------------------------------------------------------

    def to_raw(self) -> dict[str, Any]:
        """Exactly what is in memory, judged by nobody yet."""
        return {"format": FORMAT, "version": VERSION, "id": self.id,
                "title": self.title, "loadouts": list(self.loadouts),
                "pages": copy.deepcopy(self.pages)}

    def to_json(self, registry=None) -> dict[str, Any]:
        """The canonical document: no key that carries no information."""
        where = "%s.json" % self.id
        out: dict[str, Any] = {"format": FORMAT, "version": VERSION,
                               "id": self.id, "loadouts": list(self.loadouts),
                               "pages": [_canonical_page(p, registry, where)
                                         for p in self.pages]}
        if self.title:
            out["title"] = self.title
        return out

    def render(self, registry=None) -> str:
        """The file's exact text: sorted keys, two-space indent, one newline.

        `Project.save` renders a table with the same three arguments; a
        second spelling of "deterministic JSON" is a second diff shape.
        """
        return json.dumps(self.to_json(registry), indent=2,
                          sort_keys=True) + "\n"

    # -- judging -----------------------------------------------------------

    def validate(self, *, variables=None, registry=None):
        """Run the ENGINE's reader over what is in memory.

        Raises exactly what a boot would raise, or returns the judged
        `Script`.
        """
        return script_file.parse_script(self.to_raw(), "%s.json" % self.id,
                                        variables=variables,
                                        registry=registry)

    def snapshot(self) -> tuple[str, list, list]:
        return (self.title, copy.deepcopy(self.loadouts),
                copy.deepcopy(self.pages))

    def restore(self, snapshot: tuple[str, list, list]) -> None:
        self.title = snapshot[0]
        self.loadouts = copy.deepcopy(snapshot[1])
        self.pages = copy.deepcopy(snapshot[2])

    def commit(self, *, variables=None, registry=None):
        """Judge, then canonicalise, then mark dirty. Raises unchanged.

        Callers wrap a mutation in `edit()` so a refusal leaves the document
        exactly as it was -- a half-applied edit the reader refused is the
        one state neither undo nor save can describe.
        """
        judged = self.validate(variables=variables, registry=registry)
        canonical = self.to_json(registry)
        self.title = canonical.get("title", "")
        self.loadouts = list(canonical["loadouts"])
        self.pages = canonical["pages"]
        self.dirty = True
        return judged

    # -- addressing --------------------------------------------------------

    def _node_ids(self, nodes: Sequence[Mapping[str, Any]]) -> list[str]:
        out: list[str] = []
        for node in nodes:
            out.append(node["id"])
            if "do" in node:
                continue
            for _, body in _arm_bodies(node):
                out.extend(self._node_ids(body))
        return out

    def ids(self) -> list[str]:
        """Every page id and node id in document order. ONE namespace."""
        found: list[str] = []
        for page in self.pages:
            found.append(page["id"])
            found.extend(self._node_ids(page.get("body") or ()))
        return found

    def page_ids(self) -> list[str]:
        return [page["id"] for page in self.pages]

    def page(self, page_id: str) -> dict:
        for page in self.pages:
            if page["id"] == page_id:
                return page
        raise PyoneerAssetMissingError(
            "script page", page_id, available=self.page_ids(),
            asked_by=self.id,
            hint="a page is addressed by its own stable id, never by its "
                 "position")

    def page_index(self, page_id: str) -> int:
        for index, page in enumerate(self.pages):
            if page["id"] == page_id:
                return index
        raise PyoneerAssetMissingError(
            "script page", page_id, available=self.page_ids(),
            asked_by=self.id)

    def node(self, node_id: str) -> dict:
        for _, _, container in _containers(self.pages):
            for item in container:
                if item["id"] == node_id:
                    return item
        raise PyoneerAssetMissingError(
            "script node", node_id, available=self.ids(), asked_by=self.id,
            hint="every node carries a stable id; a wrong one is refused "
                 "here rather than landing on whatever sits at that "
                 "position")

    def locate(self, node_id: str) -> NodeSite:
        """Where a node sits: its container, its arm, and what precedes it."""
        for into, arm, container in _containers(self.pages):
            for index, item in enumerate(container):
                if item["id"] == node_id:
                    return NodeSite(into=into, arm=arm,
                                    after=_predecessor(container, index),
                                    index=index)
        raise PyoneerAssetMissingError(
            "script node", node_id, available=self.ids(), asked_by=self.id)

    def container(self, into: str, arm: str, *, create: bool = False) -> list:
        """The list of nodes at `into`/`arm`, or raise saying what is there.

        `create=True` materialises an empty `then` / `else` that the
        canonical rendering had dropped. Reading never creates: a lookup
        that leaves a key behind is a lookup that dirties a document nobody
        edited.
        """
        for page in self.pages:
            if page["id"] != into:
                continue
            if arm:
                raise PyoneerProjectError(
                    "%r is a page and a page has one body, so it takes no "
                    "arm (got %r)" % (into, arm), script=self.id)
            return page.setdefault("body", [])

        node = self.node(into)
        if "do" in node:
            raise PyoneerProjectError(
                "%r is a `do: %s` node and holds no body; only a page or an "
                "`if` / `while` can contain a node" % (into, node["do"]),
                script=self.id)
        kind = "if" if "if" in node else "while"
        arms = len(node.get("elif") or ())
        if kind == "while":
            legal = ("then",)
        else:
            legal = ("then",) + tuple("elif:%d" % i for i in range(arms)) \
                + ("else",)
        if arm not in legal:
            raise PyoneerProjectError(
                "%r is an `%s` node and has no %r arm; it takes %s"
                % (into, kind, arm, ", ".join(legal)),
                script=self.id, node=into, elif_arms=arms,
                hint=("`elif:N` is the Nth arm counted from 0, and arms are "
                      "created by `script.node.set` on the `elif` key"
                      if kind == "if" else
                      "a `while` has one arm, because a loop that fell "
                      "through to an else would run it on every exit"))
        if arm in ("then", "else"):
            if arm not in node and not create:
                return []
            return node.setdefault(arm, [])
        return node["elif"][int(arm.partition(":")[2])].setdefault("then", [])

    def index_after(self, container: Sequence[Mapping[str, Any]],
                    after: str, *, what: str) -> int:
        """Where `after` puts a new sibling. `""` is the FRONT, index 0."""
        if not after:
            return 0
        for index, item in enumerate(container):
            if item["id"] == after:
                return index + 1
        raise PyoneerProjectError(
            "`after` names %r, which is not a %s in this container; it holds "
            "%s. An anchor has to be a SIBLING -- that is what makes the "
            "address survive a batch that inserts above it."
            % (after, what,
               ", ".join(repr(item["id"]) for item in container) or "nothing"),
            script=self.id)

    def subtree_ids(self, node: Mapping[str, Any]) -> set[str]:
        """Every id inside a node, itself included."""
        return set(self._node_ids([node]))

    # -- persistence -------------------------------------------------------

    @classmethod
    def from_json(cls, raw: Mapping[str, Any], *,
                  path: str = "") -> "ScriptDocument":
        """Build from a decoded document. Judges NOTHING -- `commit` does.

        Tolerant of key ORDER and of a hand-written file's omissions, and
        deliberately tolerant of nothing else: the caller runs `commit`,
        which IS the reader, before the document counts as loaded.
        """
        if not isinstance(raw, Mapping):
            raise PyoneerProjectError(
                "a script file is a JSON object, not %s" % type(raw).__name__,
                path=path)
        return cls(id=str(raw.get("id", "")),
                   title=str(raw.get("title", "")),
                   loadouts=list(raw.get("loadouts") or ()),
                   pages=copy.deepcopy(list(raw.get("pages") or ())))


def settable_node_keys(node: Mapping[str, Any],
                       registry=None) -> tuple[str, ...]:
    """Which keys `script.node.set` may write on this node, sorted.

    An executable node takes `note` and exactly the arguments its `OpSpec`
    declares -- asked of the registry rather than listed here, so an op that
    grows an argument grows its editable surface in the same commit.

    A control node takes `note`, its own `if` / `while` key (which holds the
    condition list) and, for an `if`, `elif` -- the ARM list. `then` and
    `else` are bodies and are reached by `script.node.add` /
    `script.node.remove` with an `arm`, so they are deliberately not here:
    two ways to add a node would be two ways to claim an id.
    """
    if "do" in node:
        spec = op_registry.resolve(node["do"], registry,
                                   "node %r" % node.get("id"))
        return tuple(sorted(("note",) + spec.arg_keys))
    kind = "if" if "if" in node else "while"
    return tuple(sorted(("note", kind) + (("elif",) if kind == "if" else ())))


def node_value(node: Mapping[str, Any], key: str,
               registry=None) -> Any:
    """What `key` holds on this node, an absent key reading as its default.

    This is what makes `script.node.set` its own exact inverse: the value it
    hands back for a key nobody wrote is the value that, written, renders as
    nothing at all.
    """
    allowed = settable_node_keys(node, registry)
    if key not in allowed:
        raise PyoneerProjectError(
            "%r is not a settable key on node %r, which takes %s. `id` is "
            "the address and `do` is the node's whole identity -- remove it "
            "and add the node you want. `then` and `else` hold nodes, which "
            "is what `script.node.add` and `script.node.remove` are for."
            % (key, node.get("id"), ", ".join(allowed)),
            node=node.get("id"))
    if key in node:
        return copy.deepcopy(node[key])
    if key == "note":
        return ""
    if "do" in node:
        spec = op_registry.resolve(node["do"], registry,
                                   "node %r" % node.get("id"))
        return copy.deepcopy(_declared_defaults(spec)[key][1])
    return []


class edit:
    """Mutate a document, then let the READER decide whether it happened.

        with edit(document, library):
            document.pages.insert(0, page)

    On the way out the whole document goes through
    `script_file.parse_script`. If it refuses, the document is put back
    exactly as it was and the refusal is re-raised -- so a verb that writes
    something the engine would not load changes nothing at all, and the
    author is told at edit time rather than at boot.
    """

    def __init__(self, document: ScriptDocument, library: "ScriptLibrary"):
        self.document = document
        self.library = library
        self.before = document.snapshot()

    def __enter__(self) -> ScriptDocument:
        return self.document

    def __exit__(self, kind, value, trace) -> bool:
        if kind is not None:
            self.document.restore(self.before)
            return False
        try:
            self.document.commit(variables=self.library.variables,
                                 registry=self.library.registry)
        except Exception:
            self.document.restore(self.before)
            raise
        return False


# --------------------------------------------------------------------------
# The library
# --------------------------------------------------------------------------

class ScriptLibrary:
    """Every event script under one project, and the one place they save.

    Creation and deletion happen HERE, in memory, and reach the disk only at
    `save()`. That is `docs/PLAN_SCENES.md` 2.5's rule and it is the fix for
    a measured fault in the incumbent: `Project.drop_table` calls
    `os.remove` inside the command, so a drop that is rolled back has
    already deleted the file. A file's existence is the one thing a command
    cannot invert.
    """

    def __init__(self, directory: str, *, variables=None, registry=None):
        self.directory = os.path.abspath(directory)
        self.variables = variables
        """A scene's `vars` schema, or None. See this module's docstring.

        `scripts_of` never passes None -- it passes what the project's scene
        documents declare, possibly nothing. None survives as a value a
        CHECK can set, and as the state that produces the wiring-error
        message for anyone constructing a library by hand.
        """
        self.registry = registry
        self.documents: dict[str, ScriptDocument] = {}
        self.removed: set[str] = set()
        self.load()

    # -- reading -----------------------------------------------------------

    def load(self) -> None:
        """Read every `*.json` in the directory. A missing directory is empty.

        A project with no scripted events is not broken, exactly as a project
        with no `tables/` is not. A file that IS there and does not load is
        broken, and says so naming the file -- the same choice
        `Project.__load_tables` makes, and for the same reason: a script
        skipped at load is a keeper who silently does nothing.
        """
        if not os.path.isdir(self.directory):
            return
        for entry in sorted(os.listdir(self.directory)):
            if not entry.endswith(".json"):
                continue
            path = os.path.join(self.directory, entry)
            with open(path, "r", encoding="utf-8") as handle:
                try:
                    raw = json.load(handle)
                except json.JSONDecodeError as exc:
                    raise PyoneerProjectError(
                        "event script is not valid JSON: %s" % exc,
                        path=path) from exc
            document = ScriptDocument.from_json(raw, path=path)
            document.commit(variables=self.variables, registry=self.registry)
            document.dirty = False
            self.documents[document.id] = document

    def names(self) -> list[str]:
        return sorted(self.documents)

    def has(self, script_id: str) -> bool:
        return script_id in self.documents

    def document(self, script_id: str) -> ScriptDocument:
        if script_id not in self.documents:
            raise PyoneerAssetMissingError(
                "event script", script_id, available=self.names(),
                asked_by="the editor",
                hint="create it with `script.create`, or fix the scope")
        return self.documents[script_id]

    # -- changing ----------------------------------------------------------

    def create(self, document: ScriptDocument) -> ScriptDocument:
        if document.id in self.documents:
            raise PyoneerProjectError(
                "event script %r already exists" % document.id,
                script=document.id, available=self.names())
        document.commit(variables=self.variables, registry=self.registry)
        self.documents[document.id] = document
        self.removed.discard(document.id)
        return document

    def delete(self, script_id: str) -> ScriptDocument:
        document = self.document(script_id)
        del self.documents[script_id]
        self.removed.add(script_id)
        return document

    # -- persistence -------------------------------------------------------

    def path_for(self, script_id: str) -> str:
        return os.path.join(self.directory, "%s.json" % script_id)

    def dirty_scripts(self) -> list[str]:
        return sorted(n for n, d in self.documents.items() if d.dirty)

    @property
    def dirty(self) -> bool:
        return bool(self.dirty_scripts() or self.removed)

    def save(self) -> list[str]:
        """Write every dirty document and delete every removed one.

        Returns the paths written, the way `Project.save` does, so the one
        line that wires this into the project can extend the same list.
        """
        written: list[str] = []
        for script_id in sorted(self.removed):
            path = self.path_for(script_id)
            if os.path.isfile(path):
                os.remove(path)
        self.removed.clear()
        for script_id in sorted(self.documents):
            document = self.documents[script_id]
            if not document.dirty:
                continue
            os.makedirs(self.directory, exist_ok=True)
            path = self.path_for(script_id)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(document.render(self.registry))
            document.dirty = False
            written.append(path)
        return written


_LIBRARIES: "WeakKeyDictionary[Any, ScriptLibrary]" = WeakKeyDictionary()


def scripts_of(project) -> ScriptLibrary:
    """The `ScriptLibrary` for one open project, made on first use.

    THE ONE PLACE THE VARIABLE SCHEMA IS READ. Six editor surfaces reach a
    library and every one of them comes through here, so the scene's `vars`
    arrive at all six from the two lines below -- and a seventh surface
    written tomorrow gets them by asking for a library, which is the only
    thing it can do anyway. Fixing this in the callers instead would have
    been six homes for one fact.

    A project with no `data/project/scenes/` reads as a schema declaring
    nothing, which is not the same as no schema: a script naming a variable
    is then refused for the reason it should be -- nothing declares it --
    rather than for a wiring reason the author cannot act on.

    Held BESIDE the project rather than on it, and the reason is law 2's
    corollary rather than convenience: `editor/core/project.py` must not
    import this module at import time, because this module imports it. The
    project reaches a library the other way round -- `Project.save`,
    `Project.dirty` and `Project.dirty_scripts` call `opened_scripts` below
    through a deferred import -- so the wire is one direction and the
    lookup is the other.

    THIS IS THE ONLY DOOR THAT MAKES ONE. Anything that reaches a library
    comes through here, so "a project has a library" and "a project saves
    its scripts" cannot come apart: `Project.save` writes whatever library
    exists, and a project that never asked has none, nothing dirty and
    nothing to write, which is the same answer by a shorter road.
    """
    library = _LIBRARIES.get(project)
    if library is None:
        library = ScriptLibrary(
            os.path.join(project.project_dir, SCRIPTS_SUBDIR),
            variables=script_file.load_vars(
                os.path.join(project.project_dir, SCENES_SUBDIR)))
        _LIBRARIES[project] = library
    return library


def opened_scripts(project) -> "ScriptLibrary | None":
    """The library this project already has, or None if it never asked.

    `Project.save`, `Project.dirty` and `Project.dirty_scripts` call this
    and never `scripts_of`, and the difference is the whole reason it
    exists: `scripts_of` CONSTRUCTS, and constructing reads and parses every
    `data/project/scripts/*.json` and RAISES on a malformed one. `dirty` is
    asked on every window-title refresh and on the way out, so making it
    construct would turn one broken script file into an editor that cannot
    close -- and would do it at the exact moment the author is trying to
    leave with their work.

    A project with no library has nothing in memory that could be dirty and
    nothing to write, so None and "an empty library" are the same answer and
    the cheaper one is correct.
    """
    return _LIBRARIES.get(project)


__all__ = [
    "ALWAYS_ON_A_PAGE", "CONTROL_KINDS", "NO_ANCHOR", "PAGE_DEFAULTS",
    "SCRIPTS_SUBDIR", "SCRIPT_TRIGGERS", "SETTABLE_PAGE_KEYS",
    "SETTABLE_SCRIPT_KEYS", "NodeSite", "ScriptDocument", "ScriptLibrary",
    "edit", "node_value", "opened_scripts", "scripts_of",
    "settable_node_keys",
]
