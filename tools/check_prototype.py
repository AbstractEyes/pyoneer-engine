"""Resolve every field the design template names, then boot its worked example.

    .venv/Scripts/python.exe tools/check_prototype.py

WHY THIS EXISTS
---------------
`docs/DESIGN_TEMPLATE.md` claims something specific: that every field in it
resolves to something that ALREADY EXISTS -- a genre pack id, a registered
behavior token, a declared parameter key, a table column, a bound input verb, a
step field on the sequencer -- so a filled form is an instruction and not a wish
list. That claim is exactly the kind that rots: a token gets renamed, a pack
gains a column, a sequencer keyword moves, and the form goes on looking
plausible while producing a `.tmx` that raises at load.

So the form is PARSED here and every field is resolved against the live
registries. And the worked example is not merely resolved, it is BOOTED: the
story demo is run headless, driven with injected input, and compared field by
field against the block in the document. A field changed in the document
without changing the game turns this red, and so does the reverse.

THE TWO WAYS THIS COULD HAVE BEEN TOOTHLESS, AND WHAT IS DONE ABOUT EACH
-------------------------------------------------------------------------
1. **A validator that reports nothing.** Asserting "the worked example produces
   no complaints" passes for a validator whose every rule is `pass`. So the
   fixture section below MUTATES the worked example one rule at a time -- a bad
   genre, an unregistered token, a duplicate token, a conflicting pair, a
   parameter key no token declares, a column the pack does not have, an unbound
   verb, an axis the sequencer does not take, a step field that does not exist,
   a route token that fires no action, a handler the code map does not know, a
   `prove` row with one half -- and each mutation must be REPORTED BY NAME. The
   fixtures are this file's own strings; nothing in the tree is touched.
2. **A boot that proves the harness rather than the game.** Every gate below is
   asserted in both directions:

       the cutscene holds     movement keys move the hero ZERO pixels
                          AND the action verb still advances the flow
       a timed step           advances itself with nothing pressed at all
                          AND an untimed one does not, over more frames
       the agency comes back  the hero walks again once the flow ends
                          AND a second boot with no SCRIPT walks from frame 1,
                              which is what kills "the harness pressed nothing"
       exact restore          a body already unsteerable before a replay is
                              still unsteerable after it, so `end()` restores
                              the value each body HAD and never `True`
       the payload key        the routed payload reaches the flow
                          AND the same token with any other payload reaches
                              nothing
       the box is real        the dialogue text queues a blit token while open
                          AND queues none once the flow has closed it

THE MAPS THIS CHECK READS ARE ITS OWN
--------------------------------------
`demos.mapgen.MAPS_DIR` is redirected to a temp directory, exactly as
`tools/check_demos.py` does it and for the same reason: `demos/maps/*.tmx` is
the author's canvas and a check that pinned its content would go red the first
time somebody repainted one.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import ast
import inspect
import json
import os
import re
import shutil
import sys
import tempfile

import pygame

pygame.init()

# ---------------------------------------------------------------------------
# The fake keyboard, installed BEFORE anything boots -- `InputActionManager`
# calls pygame.key.get_pressed() once per frame, so replacing that function
# drives the engine's own edge derivation rather than re-implementing one.
# ---------------------------------------------------------------------------

HELD: set[int] = set()


class _FakeKeys:
    def __getitem__(self, code: int) -> bool:
        return code in HELD


pygame.key.get_pressed = lambda: _FakeKeys()   # noqa: E731

import gen_map                                                   # noqa: E402

from scripts.core import blitpool                                # noqa: E402
from scripts.core.depth import resolve_layer_depth               # noqa: E402
from scripts.core.input import KEYBOARD                          # noqa: E402
from scripts.core.spawn import SPAWN_REGISTRY                    # noqa: E402
from scripts.game.behavior import BEHAVIOR_REGISTRY              # noqa: E402
from scripts.game.behavior.base import ACTOR as ACTOR_PROPERTY   # noqa: E402
from scripts.loaders.table_file import actor_row, load_tables    # noqa: E402
from scripts.game.flow.router import ANY_PAYLOAD                 # noqa: E402
from scripts.game.flow.scene_flow import (ADVANCE_ACTION,        # noqa: E402
                                          FlowStep, SceneFlow)

from demos import mapgen                                         # noqa: E402
from demos.narrative import StoryBox, StoryGame, StoryLine       # noqa: E402
from demos.story import StoryDemo                                # noqa: E402

ROOT = _bootstrap.REPO_ROOT
TEMPLATE_REL = "docs/DESIGN_TEMPLATE.md"

failures: list[str] = []
asserted = 0


def expect(label, got, want):
    global asserted
    asserted += 1
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<66} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_reports(label: str, rows, needle: str):
    """Validating `rows` must complain, and the complaint must NAME `needle`.

    Naming is the teeth. "the validator returned something" passes for a
    validator that reports the same unrelated grumble about every form, and a
    complaint that does not quote the offending value is one a reader cannot
    act on.
    """
    global asserted
    asserted += 1
    complaints = validate(rows)
    hit = [c for c in complaints if needle in c]
    ok = bool(hit)
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<66} "
          f"{(hit[0][:56] if hit else 'NOT REPORTED: ' + str(complaints[:1]))}")
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------------------
# What the tree actually holds. Read here, never restated.
# ---------------------------------------------------------------------------

GENRES_DIR = os.path.join(ROOT, "editor", "genres")


def genre_packs() -> dict[str, dict]:
    """id -> the parsed `genre.json`. Read as DATA, not imported.

    Read rather than imported because `editor/` needs PySide6 and this check
    does not: a narrative prototype is engine-side, and a check that reported
    SKIP on a machine with no Qt would prove nothing about the form.
    """
    packs = {}
    for name in sorted(os.listdir(GENRES_DIR)):
        path = os.path.join(GENRES_DIR, name, "genre.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                packs[name] = json.load(handle)
    return packs


PACKS = genre_packs()

with open(os.path.join(ROOT, "config", "inputs.json"), encoding="utf-8") as _h:
    INPUT_VERBS: dict = json.load(_h)

FLOW_AXES = tuple(name for name, param
                  in inspect.signature(SceneFlow.__init__).parameters.items()
                  if param.kind is inspect.Parameter.KEYWORD_ONLY
                  and name != "name")
STEP_FIELDS = tuple(FlowStep.__dataclass_fields__)
TAGS = gen_map.tag_index()

# A token that FIRES an action, derived rather than listed: an action behavior
# is one that writes an `action_intent.<token>` slot. Naming the three by hand
# here would be a second copy of the registry that goes stale the day a fourth
# is added.
ACTION_TOKENS = tuple(sorted(
    token for token, spec in BEHAVIOR_REGISTRY.items()
    if any(str(w).startswith("action_intent.") for w in spec.writes)))


# ---------------------------------------------------------------------------
# The form: parse, then resolve
# ---------------------------------------------------------------------------

BLOCK_RX = re.compile(r"```design\n(.*?)```", re.S)


class Row:
    __slots__ = ("kind", "fields", "text", "lineno")

    def __init__(self, kind, fields, text, lineno):
        self.kind, self.fields, self.text, self.lineno = kind, fields, text, lineno

    def __repr__(self):                     # pragma: no cover - diagnostic only
        return "<Row %s %r>" % (self.kind, self.fields)


def parse_design(text: str) -> list[Row]:
    """One row per non-empty, non-comment line. First word is the kind.

    Whitespace-separated and nothing else -- no YAML, no TOML, no parser to
    install. A design form a human fills in five minutes has to survive being
    aligned by eye, which is why every rule below reads FIELDS and never
    columns.
    """
    rows = []
    for lineno, raw in enumerate(text.split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        rows.append(Row(parts[0], parts[1:], line, lineno))
    return rows


KINDS = ("name", "genre", "map", "layer", "object", "param", "actor", "verb",
         "flow", "step", "route", "prove")


def _pairs(fields) -> list[tuple[str, str]]:
    """`a=1 b = 2` -> [('a','1'), ('b','2')]. Alignment-tolerant on purpose."""
    joined = " ".join(fields).replace(" = ", "=")
    out = []
    for chunk in joined.split():
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            out.append((key.strip(), value.strip()))
    return out


def validate(rows: list[Row]) -> list[str]:
    """Every complaint about `rows`, as sentences that quote the bad value.

    Returns rather than raises: a form with four mistakes should report four,
    not the first one. That is also what lets the fixture section below mutate
    one rule at a time and demand that exactly that rule fires.
    """
    out: list[str] = []
    pack: dict = {}
    objects: dict[str, list[str]] = {}

    for row in rows:
        if row.kind not in KINDS:
            out.append("row kind %r is not one of the template's rows: %s"
                       % (row.kind, ", ".join(KINDS)))

    # genre first: the layer and actor rules resolve against the pack.
    for row in rows:
        if row.kind == "genre" and row.fields:
            if row.fields[0] not in PACKS:
                out.append("genre %r is not a pack under editor/genres/; known: %s"
                           % (row.fields[0], ", ".join(sorted(PACKS))))
            else:
                pack = PACKS[row.fields[0]]

    pack_layers = {layer["name"]: layer.get("kind", "tile")
                   for layer in pack.get("layers", ())}
    pack_columns = {table["name"]: {field["name"] for field in table["fields"]}
                    for table in pack.get("tables", ())}

    for row in rows:
        if row.kind == "name":
            if not row.fields or row.fields[0] not in mapgen.SOURCES:
                out.append("name %r is not a map source in demos.mapgen; known: %s"
                           % (row.fields[0] if row.fields else "",
                              ", ".join(sorted(mapgen.SOURCES))))

        elif row.kind == "map":
            numbers = [f for f in row.fields if f.isdigit()]
            if len(numbers) != 3:
                out.append("map row %r needs three integers -- width, height "
                           "and pixels per tile" % row.text)

        elif row.kind == "layer":
            if len(row.fields) < 2:
                out.append("layer row %r needs a name and `tile` or `object`"
                           % row.text)
                continue
            name, kind = row.fields[0], row.fields[1]
            if kind not in ("tile", "object"):
                out.append("layer %r declares kind %r; a layer is `tile` or "
                           "`object`" % (name, kind))
            if pack_layers and name not in pack_layers:
                out.append("layer %r is not declared by the genre pack; it "
                           "declares: %s" % (name, ", ".join(sorted(pack_layers))))
            elif pack_layers and pack_layers[name] != kind:
                out.append("layer %r is a %s layer in the genre pack, not a %s "
                           "one" % (name, pack_layers[name], kind))
            if kind == "tile" and resolve_layer_depth(name) is None:
                out.append("tile layer %r resolves to no depth, so it would be "
                           "SILENTLY not drawn" % name)

        elif row.kind == "object":
            if len(row.fields) < 3:
                out.append("object row %r needs an id, a spawn type and a "
                           "behavior list" % row.text)
                continue
            ident, type_name, tokens = row.fields[0], row.fields[1], row.fields[2]
            if type_name not in SPAWN_REGISTRY:
                out.append("object %r declares type %r, which is not in "
                           "SPAWN_REGISTRY; spawnable: %s"
                           % (ident, type_name, ", ".join(sorted(SPAWN_REGISTRY))))
            listed = [t for t in tokens.split(",") if t]
            objects[ident] = listed
            for token in listed:
                if token not in BEHAVIOR_REGISTRY:
                    out.append("object %r names behavior token %r, which is not "
                               "registered -- a map carrying it RAISES at load"
                               % (ident, token))
            if len(set(listed)) != len(listed):
                repeated = sorted({t for t in listed if listed.count(t) > 1})
                out.append("object %r lists %s twice; the list is "
                           "order-insensitive, so a repeat is always a mistake"
                           % (ident, ", ".join(repr(t) for t in repeated)))
            for token in listed:
                spec = BEHAVIOR_REGISTRY.get(token)
                if spec is None:
                    continue
                clashing = sorted(set(spec.conflicts) & set(listed))
                if clashing:
                    out.append("object %r composes %r with %s, which declare "
                               "that they conflict -- one body model per entity"
                               % (ident, token, ", ".join(repr(c) for c in clashing)))

        elif row.kind == "verb":
            if not row.fields or row.fields[0] not in INPUT_VERBS:
                out.append("verb %r is not bound in config/inputs.json; bound: %s"
                           % (row.fields[0] if row.fields else "",
                              ", ".join(sorted(INPUT_VERBS))))

        elif row.kind == "flow":
            for axis, value in _pairs(row.fields[1:]):
                if axis not in FLOW_AXES:
                    out.append("flow axis %r is not a SceneFlow keyword; it "
                               "takes: %s" % (axis, ", ".join(FLOW_AXES)))
                if value.lower() not in ("true", "false"):
                    out.append("flow axis %r is set to %r; an agency axis is "
                               "true or false" % (axis, value))

        elif row.kind == "step":
            for key, _value in _pairs(row.fields[1:]):
                if key not in STEP_FIELDS:
                    out.append("step field %r is not on the step record; it "
                               "carries: %s" % (key, ", ".join(STEP_FIELDS)))

        elif row.kind == "route":
            if "->" not in row.fields:
                out.append("route row %r needs `-> Handler.method`" % row.text)
                continue
            cut = row.fields.index("->")
            left, right = row.fields[:cut], row.fields[cut + 1:]
            if not left or not right:
                out.append("route row %r needs a token on the left and a "
                           "handler on the right" % row.text)
                continue
            token = left[0]
            if token not in BEHAVIOR_REGISTRY:
                out.append("route names behavior token %r, which is not "
                           "registered" % token)
            elif token not in ACTION_TOKENS:
                out.append("route names %r, which fires no action -- a route "
                           "key is an ActionFired name, so only these can be "
                           "routed: %s" % (token, ", ".join(ACTION_TOKENS)))
            if right[0] not in TAGS:
                out.append("route handler %r is not a symbol the code map "
                           "knows; grep it with #TAG:%s" % (right[0], right[0]))

        elif row.kind == "prove":
            if " AND " not in row.text:
                out.append("prove row %r names one half of an invariant. A gate "
                           "proved to let something through and never proved to "
                           "stop it is the commonest toothless shape here -- "
                           "write the other half after an AND." % row.text)

    # These two need every `object` row read first, so they run in a second
    # pass rather than being folded into the loop above. A form is allowed to
    # put its `param` rows before its `object` rows; a human filling one in
    # five minutes should not have to know the order.
    for row in rows:
        if row.kind == "param":
            if len(row.fields) < 2:
                out.append("param row %r needs an object id and `key = value`"
                           % row.text)
                continue
            ident = row.fields[0]
            if ident not in objects:
                out.append("param row names object %r, which no object row "
                           "declares" % ident)
                continue
            declared = {p.key for token in objects[ident]
                        for p in getattr(BEHAVIOR_REGISTRY.get(token), "params", ())}
            for key, _value in _pairs(row.fields[1:]):
                if key not in declared:
                    out.append("param %r is declared by none of object %r's "
                               "behaviors; they declare: %s"
                               % (key, ident, ", ".join(sorted(declared)) or "nothing"))

        elif row.kind == "actor":
            if not row.fields:
                out.append("actor row %r needs an object id" % row.text)
                continue
            ident = row.fields[0]
            if ident not in objects:
                out.append("actor row names object %r, which no object row "
                           "declares" % ident)
            columns = pack_columns.get("actors", set())
            for key, _value in _pairs(row.fields[1:]):
                if columns and key not in columns:
                    out.append("actor column %r is not declared by the genre "
                               "pack's actors table; it declares: %s"
                               % (key, ", ".join(sorted(columns))))
    return out


def rows_of(kind: str, rows: list[Row]) -> list[Row]:
    return [r for r in rows if r.kind == kind]


def mutate(rows: list[Row], old: str, new: str) -> list[Row]:
    """The worked example with one substring replaced. The fixture engine.

    Re-parsed from TEXT rather than edited in place, so a mutation exercises
    the parser as well as the rule -- which is the difference between testing
    the validator and testing a hand-built object graph the validator never
    sees in production.
    """
    text = "\n".join(r.text for r in rows)
    assert old in text, "fixture mutation %r matches nothing" % old
    return parse_design(text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Boot harness
# ---------------------------------------------------------------------------

def key_for(game, verb: str) -> int:
    """The keycode a verb is bound to, read off the RUNNING manager.

    Not from a literal: the manager was built from `config/inputs.json` and
    holds the parsed bindings, so rebinding `action` from `e` to `f` changes
    what this presses and changes nothing else.
    """
    action = game.input.actions[verb]
    for kind, name in action.inputs:
        if kind in ("keyboard", "key"):
            return KEYBOARD[name]
    raise KeyError("verb %r has no keyboard binding" % verb)


def hold(game, *verbs: str) -> None:
    HELD.clear()
    for verb in verbs:
        HELD.add(key_for(game, verb))


def advance(game, frames: int) -> None:
    for _ in range(frames):
        game.tick()


def tap(game, verb: str, *also: str) -> None:
    """One rising edge of `verb`, with `also` held across both frames.

    Two ticks, because `pressed()` is an EDGE: a verb held on consecutive
    frames fires once. Holding the movement keys across the tap is the whole
    point of this helper -- it is what makes "cannot walk" and "can still press
    continue" a measurement of the same frames rather than of two experiments.
    """
    hold(game, verb, *also)
    game.tick()
    hold(game, *also)
    game.tick()


def queued_senders(game) -> list:
    """Every object that queued a blit token on ONE frame, by identity.

    Deliberately not `tools/check_demos.py`'s depth histogram: the question
    here is whether ONE named widget reached the frame, and identity is the
    only answer that survives a second `TextComponent` being added to the box.
    """
    seen: list = []
    original = blitpool.BlitPool.get_blit_pool_pygame

    @staticmethod
    def spy(clear: bool = True):
        for depth in sorted(blitpool.ORGANIZED_BLITS):
            for priority in sorted(blitpool.ORGANIZED_BLITS[depth]):
                for token in blitpool.ORGANIZED_BLITS[depth][priority]:
                    seen.append(token.sender)
        return original(clear)

    blitpool.BlitPool.get_blit_pool_pygame = spy
    try:
        game.tick()
    finally:
        blitpool.BlitPool.get_blit_pool_pygame = original
    return seen


class SilentStory(StoryGame):
    """The same map and the same objects, with NO script and so no flow.

    The negative control for every "the cutscene held it" assertion. Without
    this, "the hero did not move" is equally well explained by a harness that
    never pressed anything, by a map with no player token in it, and by an
    engine that stopped stepping.
    """

    MAP_NAME = StoryDemo.MAP_NAME
    SCRIPT = ()


WORKSPACE = tempfile.mkdtemp(prefix="pyoneer_prototype_")
SHIPPED_MAPS_DIR = mapgen.MAPS_DIR

try:
    mapgen.MAPS_DIR = WORKSPACE

    # =====================================================================
    print("1. the design template parses, and its two blocks agree")
    # =====================================================================
    with open(os.path.join(ROOT, TEMPLATE_REL.replace("/", os.sep)),
              encoding="utf-8") as handle:
        TEMPLATE_TEXT = handle.read()

    blocks = BLOCK_RX.findall(TEMPLATE_TEXT)
    expect("the template carries exactly two ```design blocks -- a blank form "
           "and a worked example", len(blocks), 2)
    BLANK = parse_design(blocks[0])
    EXAMPLE = parse_design(blocks[1])

    expect("every row in the blank form is a known row kind",
           sorted({r.kind for r in BLANK if r.kind not in KINDS}), [])
    expect("every row in the blank form carries a <placeholder> to fill",
           [r.text for r in BLANK if "<" not in r.text], [])
    expect("the worked example has no placeholder left in it",
           [r.text for r in EXAMPLE if "<" in r.text], [])
    expect("the blank form and the worked example use the SAME row kinds -- a "
           "row the form never shows is a row nobody fills",
           sorted({r.kind for r in BLANK}), sorted({r.kind for r in EXAMPLE}))
    expect("the form is short enough to fill in five minutes (rows)",
           len(BLANK) <= 20, True)
    expect("...and the documented row kinds are all reachable from it",
           sorted({r.kind for r in BLANK}), sorted(KINDS))

    # =====================================================================
    print()
    print("2. every field the worked example names resolves in the live tree")
    # =====================================================================
    complaints = validate(EXAMPLE)
    expect("the worked example resolves with no complaint at all",
           complaints, [])
    # Named individually as well, so a failure says WHICH field moved rather
    # than handing back a list.
    expect("its genre is a pack on disk",
           rows_of("genre", EXAMPLE)[0].fields[0] in PACKS, True)
    expect("its spawn types are all registered",
           sorted({r.fields[1] for r in rows_of("object", EXAMPLE)}
                  - set(SPAWN_REGISTRY)), [])
    expect("its behavior tokens are all registered",
           sorted({t for r in rows_of("object", EXAMPLE)
                   for t in r.fields[2].split(",")} - set(BEHAVIOR_REGISTRY)), [])
    expect("its input verbs are all bound",
           sorted({r.fields[0] for r in rows_of("verb", EXAMPLE)}
                  - set(INPUT_VERBS)), [])
    expect("its routed handler is a symbol the code map knows",
           rows_of("route", EXAMPLE)[0].fields[-1] in TAGS, True)
    expect("every prove row names both halves of its invariant",
           [r.text for r in rows_of("prove", EXAMPLE) if " AND " not in r.text],
           [])
    expect("the template resolves a non-trivial number of fields",
           len(EXAMPLE) >= 15, True)

    # =====================================================================
    print()
    print("3. TEETH: the resolver reports each mistake, by name, on its own")
    # =====================================================================
    # Own fixtures: every mutation below is a string edit to a copy of the
    # worked example, made in memory. Nothing in the tree is touched, and each
    # one must be reported NAMING the bad value -- a validator that grumbles
    # about the wrong field is a validator a reader cannot act on.
    expect_reports("a genre that is not a pack",
                   mutate(EXAMPLE, "topdown_rpg", "topdown_rpgg"), "topdown_rpgg")
    expect_reports("a tile layer the pack does not declare",
                   mutate(EXAMPLE, "layer   Floor", "layer   Flooor"), "Flooor")
    expect_reports("an object layer the pack does not declare",
                   mutate(EXAMPLE, "layer   entity", "layer   chatter"), "chatter")
    expect_reports("a tile layer declared as an object layer",
                   mutate(EXAMPLE, "layer   Floor      tile",
                          "layer   Floor      object"), "Floor")
    expect_reports("a spawn type that is not registered",
                   mutate(EXAMPLE, "GamePlayer  topdown_move",
                          "GameKeeper  topdown_move"), "GameKeeper")
    expect_reports("a behavior token that is not registered",
                   mutate(EXAMPLE, "topdown_move,animation_drive",
                          "topdown_move,tile_collision"), "tile_collision")
    expect_reports("the same token listed twice",
                   mutate(EXAMPLE, "topdown_move,animation_drive",
                          "topdown_move,animation_drive,topdown_move"),
                   "twice")
    expect_reports("two body models that declare they conflict",
                   mutate(EXAMPLE, "topdown_move,animation_drive",
                          "topdown_move,platformer_move,animation_drive"),
                   "conflict")
    expect_reports("a parameter key no listed behavior declares",
                   mutate(EXAMPLE, "payload = keeper", "payloads = keeper"),
                   "payloads")
    expect_reports("a param row naming an object that does not exist",
                   mutate(EXAMPLE, "param   hero", "param   nobody"), "nobody")
    expect_reports("an actors column the genre pack does not declare",
                   mutate(EXAMPLE, "hp=10", "hpp=10"), "hpp")
    expect_reports("an input verb that is not bound",
                   mutate(EXAMPLE, "verb    action", "verb    actionn"), "actionn")
    expect_reports("an agency axis the sequencer does not take",
                   mutate(EXAMPLE, "steerable=false", "steerible=false"),
                   "steerible")
    expect_reports("an agency axis set to something that is not a boolean",
                   mutate(EXAMPLE, "steerable=false", "steerable=sometimes"),
                   "sometimes")
    expect_reports("a step field that is not on the step record",
                   mutate(EXAMPLE, "hold_ms=900", "hold_msec=900"), "hold_msec")
    expect_reports("a routed token that fires no action at all",
                   mutate(EXAMPLE, "route   interact_action",
                          "route   topdown_move"), "topdown_move")
    expect_reports("a routed handler the code map does not know",
                   mutate(EXAMPLE, "SceneFlow.on_action", "SceneFlow.on_actions"),
                   "on_actions")
    expect_reports("a demo name with no map source behind it",
                   mutate(EXAMPLE, "name    demo_story", "name    demo_stories"),
                   "demo_stories")
    expect_reports("a prove row that names one half of its invariant",
                   mutate(EXAMPLE, "refuses movement AND still advances",
                          "refuses movement, also advances"), "one half")
    expect_reports("a row kind the template does not define",
                   mutate(EXAMPLE, "prove   the cutscene",
                          "assert  the cutscene"), "assert")
    # The other half of every line above: the unmutated form is silent. Without
    # this, a validator that reported "something is wrong" about every input
    # would pass all twenty.
    expect("...and the unmutated form still reports nothing",
           validate(EXAMPLE), [])

    # =====================================================================
    print()
    print("4. the worked example IS the demo: boot it and compare, field by field")
    # =====================================================================
    story = StoryDemo(autostart=False)
    story.begin(max_frames=1)

    flow = story.story_flow
    box = story.story_box
    hero = story.entity_of(mapgen.STORY_HERO_ID)
    keeper = story.entity_of(mapgen.STORY_KEEPER_ID)

    expect("the demo booted the map the form names",
           rows_of("name", EXAMPLE)[0].fields[0], StoryDemo.MAP_NAME)
    map_numbers = [int(f) for f in rows_of("map", EXAMPLE)[0].fields if f.isdigit()]
    expect("...at the size the form declares",
           tuple(map_numbers), (mapgen.STORY_SIZE[0], mapgen.STORY_SIZE[1],
                                mapgen.TILE))

    # Object ids: the form's are human names and a `.tmx` object's handle is
    # its id, so the two are joined through mapgen's own named constants --
    # never through a number typed twice.
    FORM_IDS = {"hero": mapgen.STORY_HERO_ID, "keeper": mapgen.STORY_KEEPER_ID}
    form_objects = {r.fields[0]: (r.fields[1], sorted(r.fields[2].split(",")))
                    for r in rows_of("object", EXAMPLE)}
    expect("the form names exactly the objects the map spawns",
           sorted(FORM_IDS), sorted(form_objects))
    live_objects = {}
    for ident, object_id in FORM_IDS.items():
        record = next(r for r in story.spawned if r.object_id == object_id)
        live_objects[ident] = (record.type_name,
                               sorted(q.spec.name for q in record.behaviors))
    expect("...and every spawn type and resolved token list matches the form",
           live_objects, form_objects)

    param_row = rows_of("param", EXAMPLE)[0]
    param_key, param_value = _pairs(param_row.fields[1:])[0]
    hero_record = next(r for r in story.spawned
                       if r.object_id == mapgen.STORY_HERO_ID)
    resolved = {q.spec.name: dict(q.values) for q in hero_record.behaviors}
    expect("the form's param row is the value the map resolved onto the "
           "behavior that declares it",
           resolved["interact_action"][param_key], param_value)

    form_steps = [(r.fields[0], _pairs(r.fields[1:])[0][1])
                  for r in rows_of("step", EXAMPLE)]
    expect("the form's steps are the demo's script, in order and with the "
           "same holds",
           form_steps,
           [(name, str(int(hold_ms))) for name, _line, hold_ms in StoryDemo.SCRIPT])
    expect("...and the flow the demo mounted carries exactly those steps",
           [step.name for step in flow.steps], [name for name, _ in form_steps])

    route_row = rows_of("route", EXAMPLE)[0]
    cut = route_row.fields.index("->")
    form_token, form_payload = route_row.fields[0], route_row.fields[1]
    # THE FORM'S ROW, LOOKED UP -- not the whole table compared. Every demo
    # inherits main.py's `(interact_action, ANY_PAYLOAD)` script starter now,
    # so the table carries a second row that has nothing to do with this form.
    # This assertion used to compare the tuple whole, which made it a count of
    # HANDLERS standing in for a claim about EFFECT: it went red the day the
    # demo path stopped re-spelling main.py's boot, while the effect it was
    # about did not change at all.
    expect("the form's route is the route the game registered",
           [row for row in story.scene.actions.routes
            if row[:2] == (form_token, form_payload)],
           [(form_token, form_payload, 1)])
    expect("...and the OTHER row is main.py's inherited script starter, bound "
           "to this game",
           [(getattr(h, "__func__", None) is type(story).run_object_script,
             getattr(h, "__self__", None) is story)
            for h in story.scene.actions.handlers_for(form_token,
                                                      ANY_PAYLOAD)],
           [(True, True)])
    handlers = story.scene.actions.handlers_for(form_token, form_payload)
    expect("...and its handler is the sequencer method the form names",
           [h.__func__ for h in handlers],
           [getattr(SceneFlow, route_row.fields[cut + 1].split(".")[-1])])
    expect("the routed token is the one the sequencer declares as its default "
           "advance", form_token, ADVANCE_ACTION)

    axis, value = _pairs(rows_of("flow", EXAMPLE)[0].fields[1:])[0]
    signature = inspect.signature(SceneFlow.__init__).parameters
    expect("the form's agency axis is the sequencer's own default hold",
           (axis in FLOW_AXES, signature[axis].default), (True, value == "true"))

    # =====================================================================
    print()
    print("5. the prove rows, measured on the running game")
    # =====================================================================
    expect("the flow is mounted in the manager's one slot", story.scene.flow is flow,
           True)
    expect("every spawned body's action sink is the scene's router",
           sorted({r.entity.action_sink is story.scene.actions
                   for r in story.spawned}), [True])
    expect("the flow holds both bodies", len(flow.held_bodies), 2)
    expect("the box opened on the first beat, showing that beat's line",
           box.line, StoryDemo.SCRIPT[0][1])

    # -- prove 1: the cutscene refuses movement AND still advances ----------
    walked_from = tuple(hero.transform.position)
    hold(story, "right")
    advance(story, 20)
    expect("PROVE holding a movement verb during the cutscene moves the hero "
           "zero pixels", tuple(hero.transform.position), walked_from)
    expect("...and the flow is still on the beat it was on", flow.index, 0)

    # -- prove 2: a timed step advances itself AND an untimed one waits -----
    HELD.clear()
    timed_frame = None
    for frame in range(400):
        story.tick()
        if flow.index != 0:
            timed_frame = frame
            break
    expect("PROVE the timed first beat advanced itself with NOTHING pressed",
           timed_frame is not None, True)
    expect("...onto the second beat, whose line the box now shows",
           box.line, StoryDemo.SCRIPT[1][1])
    advance(story, 90)
    expect("PROVE an untimed beat does NOT advance itself over more frames "
           "than the timed one needed", flow.index, 1)

    # -- prove 1, other half: the action verb still gets through ------------
    tap(story, "action", "right")
    expect("PROVE the action verb advances the flow while movement is refused",
           flow.index, 2)
    expect("...and the hero STILL has not moved a pixel",
           tuple(hero.transform.position), walked_from)
    expect("...and the box shows the third beat", box.line, StoryDemo.SCRIPT[2][1])

    # -- the box is a real widget in a real frame --------------------------
    senders = queued_senders(story)
    expect("PROVE the dialogue text queues a blit token while the box is open",
           any(sender is box.line_text for sender in senders), True)

    # -- prove 3: the agency comes back ------------------------------------
    tap(story, "action", "right")
    expect("the flow ran off its last beat and ended", (flow.running, flow.done),
           (False, True))
    expect("...and closed the box behind it", box.visible, False)
    expect("...so the dialogue text queues nothing at all now",
           any(sender is box.line_text for sender in queued_senders(story)), False)
    expect("PROVE steering came back to both bodies",
           sorted({hero.state.steerable, keeper.state.steerable}), [True])
    hold(story, "right")
    resumed_from = tuple(hero.transform.position)
    advance(story, 20)
    expect("...and the same held verb now walks the hero",
           tuple(hero.transform.position) != resumed_from, True)

    # -- prove 3, the sharp half: restore is EXACT, never True --------------
    # A replayed flow is legal and rewinds -- a shopkeeper's dialogue is played
    # more than once -- so this measures the restore on the live demo rather
    # than on a fixture. The keeper is made unsteerable FIRST; a flow that
    # ended by enabling everything it touched would silently animate it.
    HELD.clear()
    keeper.state.steerable = False
    expect("a finished flow can be replayed", flow.begin(), True)
    expect("...and it took the steering again", hero.state.steerable, False)
    flow.end()
    expect("PROVE the hero got back the value it HAD", hero.state.steerable, True)
    expect("...AND the keeper got back the value IT had, which was False",
           keeper.state.steerable, False)
    keeper.state.steerable = True

    # -- prove 4: the payload is the second half of the routing key --------
    expect("PROVE the routed payload reaches the flow",
           len(story.scene.actions.handlers_for(form_token, form_payload)), 1)
    # THE EFFECT, not the handler count. The exact-payload route is what
    # reaches the FLOW; any other payload reaches only the inherited starter,
    # and that starter starts nothing here because no body on this map names a
    # `pyoneer_script`. Counting handlers instead measured the wiring of a
    # sibling module and called it this form's claim.
    def _functions(handlers):
        return [getattr(handler, "__func__", handler) for handler in handlers]

    flow_handler = getattr(SceneFlow, route_row.fields[cut + 1].split(".")[-1])
    expect("...AND the same token with any other payload does not reach the "
           "flow",
           (flow_handler in _functions(
                story.scene.actions.handlers_for(form_token, "somewhere_else")),
            flow_handler in _functions(
                story.scene.actions.handlers_for(form_token, ANY_PAYLOAD))),
           (False, False))
    expect("...and the starter it DOES reach has nothing to start, because no "
           "body on this map names a script",
           (story.object_scripts, story.script_run), ([], None))
    expect("the keeper carries no action token at all, so pressing the verb "
           "beside it can fire nothing",
           sorted(q.spec.name for q in
                  next(r for r in story.spawned
                       if r.object_id == mapgen.STORY_KEEPER_ID).behaviors),
           sorted(mapgen.STORY_KEEPER_BEHAVIORS.split(",")))

    # =====================================================================
    print()
    print("6. the negative control: the same map with no script is not held")
    # =====================================================================
    # Without this boot, every "it did not move" above is equally well
    # explained by a harness that pressed nothing.
    HELD.clear()
    control = SilentStory(autostart=False)
    control.begin(max_frames=1)
    control_hero = control.entity_of(mapgen.STORY_HERO_ID)
    expect("a story game with no script mounts no flow", control.scene.flow, None)
    expect("...and registers no route OF ITS OWN -- the single row present is "
           "main.py's inherited script starter, which this map gives nothing "
           "to start",
           (control.scene.actions.routes, control.object_scripts),
           (((ADVANCE_ACTION, ANY_PAYLOAD, 1),), []))
    expect("...and builds no dialogue box", hasattr(control, "story_box"), False)
    expect("...and its hero is steerable from the first frame",
           control_hero.state.steerable, True)
    control_from = tuple(control_hero.transform.position)
    hold(control, "right")
    advance(control, 20)
    expect("PROVE the SAME map and the SAME held verb walks the hero when no "
           "flow is holding it",
           tuple(control_hero.transform.position) != control_from, True)
    expect("...along x only, so it is movement and not a camera artefact",
           control_hero.transform.position.y, control_from[1])

    # =====================================================================
    print()
    print("7. the loop's parts are where PROTOTYPE.md says they are")
    # =====================================================================
    expect("the design template is a document on disk",
           os.path.isfile(os.path.join(ROOT, TEMPLATE_REL.replace("/", os.sep))),
           True)
    expect("the prototype loop is written down beside it",
           os.path.isfile(os.path.join(ROOT, "docs", "PROTOTYPE.md")), True)
    expect("this check is in the roster, so the loop's PROVE step is itself run",
           "(\"prototype\"," in
           open(os.path.join(ROOT, "tools", "check_all.py"),
                encoding="utf-8").read(), True)
    expect("the story demo is a class and a script, with no method of its own",
           sorted(name for name, value in vars(StoryDemo).items()
                  if callable(value) and not name.startswith("__")), [])
    expect("...and the narrative kit it derives adds exactly one hook",
           sorted(name for name in vars(StoryGame)
                  if callable(vars(StoryGame)[name])
                  and not name.startswith("__")), ["load_test_objects"])
    expect("the step adapter is what makes one box say different things -- it "
           "is a pair of verbs and not a widget",
           (hasattr(StoryLine, "open") and hasattr(StoryLine, "close")
            and not issubclass(StoryLine, StoryBox)), True)

    # The template's `actor` row, asserted in both directions so the claim
    # cannot quietly become false OR quietly become a lie about a mechanism
    # that does not exist. Not a grep for the words "project" and "tables" --
    # prose says those, and a rule that fires on a docstring is a rule that
    # gets deleted rather than fixed.
    #
    # Measured as a CALL and a VALUE, never as a string in a file:
    # `scripts/loaders/table_file.py` supplies the row through `actor_row`,
    # so a scan for the spelling `actors_row` would pass unchanged while
    # asserting the opposite of the truth.
    #
    # Half one: step 2 of parameter resolution is BUILT. `read_requests` takes
    # an actors row and applies it over the declared default.
    from scripts.game.behavior.base import BEHAVIORS as BEHAVIORS_PROPERTY
    from scripts.game.behavior.registry import read_requests
    supplied = read_requests({BEHAVIORS_PROPERTY: "platformer_move"},
                             {"move_speed": 999.0})
    declared = read_requests({BEHAVIORS_PROPERTY: "platformer_move"})
    expect("an actors row IS applied when one is handed to the reader",
           supplied[0].values["move_speed"], 999.0)
    expect("...and the declared default is what arrives when one is not",
           declared[0].values["move_speed"],
           next(p.default for p in BEHAVIOR_REGISTRY["platformer_move"].params
                if p.key == "move_speed"))
    # Half two: a caller DOES hand one over now, on both spawn routes, so the
    # `actor` row a filled-in form writes reaches a running behavior. Measured
    # as the call in the AST rather than as a substring anywhere in the file:
    # deleting either `actor_row(...)` argument leaves both modules importing
    # the name and mentioning it in prose, and only the call site matters.
    def _passes_actor_row(rel: str) -> bool:
        tree = ast.parse(open(os.path.join(ROOT, rel.replace("/", os.sep)),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "read_requests"):
                continue
            for argument in node.args[1:]:
                called = (argument.func if isinstance(argument, ast.Call)
                          else None)
                if (getattr(called, "id", None) == "actor_row"
                        or getattr(called, "attr", "").endswith("actor_row")):
                    return True
        return False

    expect("the map spawn hands read_requests an actors row",
           _passes_actor_row("scripts/loaders/map_loader.py"), True)
    expect("...and so does the runtime spawn, so an authored object and a "
           "Python-built one read the same rung",
           _passes_actor_row("scripts/core/scene/scene_manager.py"), True)

    # And the value really arrives, through the reader, from a file. A fixture
    # table written here -- data/project/tables/actors.json is the author's and
    # a check that pinned it would go red the next time they edit a number.
    table_dir = os.path.join(WORKSPACE, "tables")
    os.makedirs(table_dir, exist_ok=True)
    with open(os.path.join(table_dir, "actors.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"table": "actors",
                   "columns": [{"name": "move_speed", "type": "float"}],
                   "rows": {"hero": {"move_speed": 777.0}}}, handle)
    loaded = load_tables(table_dir)
    from_file = read_requests(
        {BEHAVIORS_PROPERTY: "platformer_move"},
        actor_row(loaded, {ACTOR_PROPERTY: "hero"}, "the template's example"))
    expect("...and a row read off disk by pyoneer_actor is what the behavior "
           "is built with", from_file[0].values["move_speed"], 777.0)

finally:
    mapgen.MAPS_DIR = SHIPPED_MAPS_DIR
    HELD.clear()
    shutil.rmtree(WORKSPACE, ignore_errors=True)

print()
if failures:
    print(f"FAILED ({len(failures)} of {asserted}):", failures[:8])
    sys.exit(1)
print(f"PASS -- {asserted} assertions, the template resolved and mutated "
      f"{20} ways, the worked example booted and driven")
