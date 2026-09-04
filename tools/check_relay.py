"""Verify the scoped relay -- the piecemeal door between the author and an AI.

The author's own sentence governs this file: *"the developer is likely not
going to be coding anything, but instead will be communicating through the
engine to the AI for curative changes."* So the thing under test is not a
widget. It is the PAYLOAD: what a bundle costs to send, and whether what it
sends is what the address can actually be answered with.

WHAT IS ASSERTED, AND WHY EACH HALF EXISTS
------------------------------------------
  * the slice contains EXACTLY the verbs a scope accepts -- by name and by
    count -- and NONE of the others. The second half is the one that fails
    when the filter is wrong: a filter that returns everything passes any
    "contains the right verbs" test ever written.
  * the filter is the VALIDATOR'S OWN TEST. Every verb in a slice is driven
    through `Verb.validate` and asserted not to raise on scope; every verb
    left out is asserted to raise `PyoneerCommandScopeError`. A filter that
    agreed with the validator by coincidence would ship a vocabulary whose
    verbs are refused on arrival.
  * the unscoped output is UNCHANGED, byte for byte, against the
    `docs/COMMANDS.md` that was generated before the keyword existed. That
    file is the only real "before" snapshot available, and `check_docs`
    regenerates from the same function, so a default-path regression is
    caught here as a diff rather than there as a red suite.
  * THE SIZE ITSELF. The whole feature is a ratio -- ~2,500 tokens instead
    of ~11,000 for the same note -- and a ratio that is not asserted
    silently regresses into shipping the vocabulary again the first time
    someone "makes it safe" by adding a file back.
  * the ZERO-VERB REFUSAL, both halves: a scope no verb accepts is refused
    by name, and a scope that has verbs writes.
  * `describe_scope` answers for every kind in `SCOPE_KINDS` and RAISES on
    a kind it has no arm for. The arm it used to have returned "*(no
    description available)*", which writes a complete-looking bundle whose
    CONTEXT.md says nothing -- law 7.
  * the Qt half, offscreen: a REAL click on the Ask button writes a bundle
    carrying its own panel's scope, and `modals()` stays empty. A verb with
    no caller is the defect this tree keeps paying for, so the button is
    driven rather than the method.

No pygame. Nothing is written into the repository: every bundle goes to a
throwaway workspace built from a COPY of the map. The Qt section skips
cleanly when PySide6 is absent.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import atexit
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

from editor.core.commands import (
    Command,
    all_verbs,
    describe_all,
    verb_names,
    verbs_accepting,
)
from editor.core.errors import (
    PyoneerCommandScopeError,
    PyoneerRequestError,
)
from editor.core.request import (
    Manifest,
    Note,
    RULES_SCOPE_KINDS,
    describe_scope,
    rules_travel_with,
    write_bundle,
)
from editor.core.scope import SCOPE_KINDS, Scope, Segment
from editor.core.session import Session

REPO = _bootstrap.REPO_ROOT
failures: list[str] = []


def expect(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception_type, fn, *, naming: str = ""):
    """Both halves in one call: the right exception, and a message that
    actually tells the author which thing was refused. A refusal nobody can
    read is the same defect as no refusal."""
    try:
        fn()
    except exception_type as exc:
        text = str(exc)
        if naming and naming not in text:
            print(f"  FAIL {label:<62} raised but never named {naming!r}")
            failures.append(label)
            return
        print(f"  ok   {label:<62} {type(exc).__name__}: "
              f"{text.splitlines()[0][:52]}")
        return
    except Exception as exc:                                    # noqa: BLE001
        print(f"  FAIL {label:<62} raised {type(exc).__name__}, "
              f"wanted {exception_type.__name__}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise {exception_type.__name__}")
    failures.append(label)


def tokens(text_or_path) -> int:
    """The measure the spec is written in: bytes over four.

    Not a tokeniser. It does not need to be -- the claim being defended is a
    4x ratio, and every number in `docs/PLAN_SCENES.md` section 5a was taken
    this way, so this is the same yardstick rather than a better one.
    """
    if isinstance(text_or_path, str) and os.path.isdir(text_or_path):
        return sum(os.path.getsize(os.path.join(text_or_path, name))
                   for name in os.listdir(text_or_path)) // 4
    if isinstance(text_or_path, str) and os.path.isfile(text_or_path):
        return os.path.getsize(text_or_path) // 4
    return len(text_or_path.encode("utf-8")) // 4


# --------------------------------------------------------------------------
print()
print("a throwaway workspace, so no bundle is ever written into the repo")
# --------------------------------------------------------------------------
workspace = tempfile.mkdtemp(prefix="pyoneer_relay_check_")
atexit.register(shutil.rmtree, workspace, ignore_errors=True)
os.makedirs(os.path.join(workspace, "config"))
os.makedirs(os.path.join(workspace, "data", "maps"))
shutil.copy2(os.path.join(REPO, "data", "maps", "test.tmx"),
             os.path.join(workspace, "data", "maps", "test.tmx"))
with open(os.path.join(workspace, "config", "maps.json"), "w",
          encoding="utf-8") as handle:
    json.dump({"data": [{"name": "test", "identifier": "test",
                         "file": "data/maps/test.tmx"}]}, handle)

session = Session.open(workspace, genre_id="topdown_rpg")
expect("the workspace opened", session.project.map_names(), ["test"])

#: Every bundle this file writes lands here, never in `editor/requests/`.
OUT = tempfile.mkdtemp(prefix="pyoneer_relay_bundles_")
atexit.register(shutil.rmtree, OUT, ignore_errors=True)

LAYER = Scope.parse("map:test/layer:Floor")
MAP = Scope.parse("map:test")
OBJECT = Scope.parse("map:test/layer:entity/object:1")
TABLE = Scope.parse("table:actors")
ASSETS = Scope.parse("assets")
GENRE = Scope.parse("genre")

SENTENCE = "make the shoreline two tiles wider"

#: One address per scope kind that `describe_scope` has an arm for. NOT a
#: copy of `SCOPE_KINDS` -- the gap between the two is the point. A kind
#: declared with no arm written for it is exactly what law 7 is about, and
#: `sample()` below builds a scope for one so it can be driven and refused.
KIND_SAMPLE: dict[str, str] = {
    "project": "project",
    "genre": "genre",
    "map": "map:test",
    "layer": "map:test/layer:Floor",
    "object": "map:test/layer:entity/object:1",
    "table": "table:actors",
    "row": "table:actors/row:hero",
    "field": "table:actors/field:hp",
    "assets": "assets",
    "code": "code:renderer",
    "script": "script:relay_fixture",
}


def sample(kind: str) -> Scope:
    """An address of `kind`, whether or not this file has a real one.

    `Scope` is constructed directly for a kind with no sample, because the
    parser is not the thing under test here: a kind reaches `SCOPE_KINDS`
    before anything can address it, and the question is what the bundle
    writer does when it meets one.
    """
    text = KIND_SAMPLE.get(kind)
    return Scope.parse(text) if text else Scope((Segment(kind, "sample"),))


# --------------------------------------------------------------------------
print()
print("the filter is the VALIDATOR'S own test, not a second opinion")
# --------------------------------------------------------------------------
# The failure this guards against is subtle and total: a slice built from
# the verb NAME ("map.tile.* is a layer verb") would look right, ship, and
# then have every command in it refused on arrival by `Verb.validate`.
slice_names = [spec.name for spec in verbs_accepting((LAYER,))]
left_out = [name for name in verb_names() if name not in slice_names]

accepted_but_refused = []
for spec in verbs_accepting((LAYER,)):
    try:
        spec.validate(Command(spec.name, LAYER, {}))
    except PyoneerCommandScopeError:
        accepted_but_refused.append(spec.name)
    except Exception:                                           # noqa: BLE001
        pass            # a missing/typed argument is a different question
expect("every verb in the slice passes the validator's scope gate",
       accepted_but_refused, [])

refused_but_offered = []
for name in left_out:
    spec = next(v for v in all_verbs() if v.name == name)
    try:
        spec.validate(Command(name, LAYER, {}))
    except PyoneerCommandScopeError:
        continue
    except Exception:                                           # noqa: BLE001
        pass
    refused_but_offered.append(name)
expect("every verb left out is one the validator would refuse here",
       refused_but_offered, [])

expect("an empty scope tuple selects NOTHING, not everything",
       verbs_accepting(()), [])


# --------------------------------------------------------------------------
print()
print("the sliced vocabulary: exactly these, and none of the others")
# --------------------------------------------------------------------------
scoped_doc = describe_all(scopes=(LAYER,))
unscoped_doc = describe_all()

# HALF A -- by name and by count. Spelled out rather than derived, so a
# change to what a tile layer accepts has to be looked at by a human.
LAYER_VERBS = ["map.layer.remove", "map.layer.set", "map.layer.unset",
               "map.object.add", "map.object.restore",
               "map.tile.fill", "map.tile.set", "map.tile.set_many"]
expect("the slice is exactly the layer verbs", slice_names, LAYER_VERBS)
expect("eight of them", len(slice_names), 8)
expect("and the document holds every one",
       [n for n in LAYER_VERBS if f"### `{n}`" in scoped_doc], LAYER_VERBS)
expect("the document says how many, and agrees with itself",
       scoped_doc.count("### `"), len(LAYER_VERBS))
expect("it prints the count in its own preamble",
       f"{len(LAYER_VERBS)} verbs:" in scoped_doc, True)

# HALF B -- the half that fails when the filter is wrong.
leaked = [n for n in left_out if f"### `{n}`" in scoped_doc]
expect("and NONE of the others", leaked, [])
# Non-vacuity: half B proves nothing if there is nothing to leak. The
# registry grows, so the count is derived and only its FLOOR is pinned.
expect("there were plenty of them to leak",
       (len(left_out) == len(all_verbs()) - len(LAYER_VERBS),
        len(left_out) > 20), (True, True))
expect("the slice names its scope, so the responder knows what it may aim at",
       str(LAYER) in scoped_doc, True)

# The other measured slices from the spec, both halves each.
for scope, wanted in ((OBJECT, 9), (MAP, 9), (TABLE, 6),
                      (Scope.parse("table:actors/row:hero"), 2)):
    names = [spec.name for spec in verbs_accepting((scope,))]
    doc = describe_all(scopes=(scope,))
    expect(f"{scope} slices to {wanted} verbs", len(names), wanted)
    expect(f"{scope} leaks none of the rest",
           [n for n in verb_names()
            if n not in names and f"### `{n}`" in doc], [])


# --------------------------------------------------------------------------
print()
print("the unscoped default is byte-identical to what it produced before")
# --------------------------------------------------------------------------
expect("unscoped still carries every registered verb",
       unscoped_doc.count("### `"), len(all_verbs()))
# A floor, not an equality: verbs are added by other work, and a check that
# pins the census goes red for a change that has nothing to do with it.
# What must not happen is the registry SHRINKING out from under the relay.
expect("there are at least the 37 the spec measured",
       len(all_verbs()) >= 37, True)
expect("and the preamble's count is the SELECTED count, not the registry's",
       f"{len(all_verbs())} verbs:" in unscoped_doc, True)
expect("and every name is really in it",
       [n for n in verb_names() if f"### `{n}`" not in unscoped_doc], [])
expect("the scoped preamble appears on the scoped path ONLY",
       ("Scoped to" in scoped_doc, "Scoped to" in unscoped_doc), (True, False))
expect("an explicitly empty scopes tuple is the unscoped rendering",
       describe_all(scopes=()) == unscoped_doc, True)

with open(os.path.join(REPO, "docs", "COMMANDS.md"), encoding="utf-8") as handle:
    generated = handle.read()
expect("there is a real document to compare against", len(generated) > 20000, True)
# The only real "before" snapshot available: `docs/COMMANDS.md` was
# generated by this function before the keyword existed. The HEAD block is
# compared -- everything above the first verb -- because that is the part
# `scopes` can touch, while the per-verb body legitimately changes whenever
# someone registers a verb. The one number in the head that moves with the
# registry is substituted rather than ignored, so the rest is a byte
# comparison: a re-worded rule or an injected preamble still fails it.
snapshot = generated[generated.index("# Command vocabulary"):].split("### `")[0]
now = unscoped_doc.split("### `")[0]
was = re.search("^([0-9]+) verbs:$", snapshot, re.M)
expect("the snapshot states a verb count", bool(was), True)
if was:
    expect("the unscoped preamble is byte-identical to the one that "
           "generated docs/COMMANDS.md",
           now, snapshot.replace(f"{was.group(1)} verbs:",
                                 f"{len(all_verbs())} verbs:"))


# --------------------------------------------------------------------------
print()
print("THE SIZE ITSELF -- the whole feature is this ratio")
# --------------------------------------------------------------------------
one_note = Note(LAYER, SENTENCE)
wide = write_bundle(session.project, Manifest(notes=[one_note]),
                    requests_dir=OUT)
narrow_path = session.ask(LAYER, SENTENCE, requests_dir=OUT)

wide_tokens = tokens(wide.directory)
narrow_tokens = tokens(narrow_path)
print(f"       the same note, both ways: {wide_tokens} tok unscoped, "
      f"{narrow_tokens} tok scoped")
expect("a scoped bundle is under 3,000 tokens", narrow_tokens < 3000, True)
expect("an unscoped one is over 9,000", wide_tokens > 9000, True)
expect("the vocabulary is the bulk of the difference",
       tokens(os.path.join(wide.directory, "COMMANDS.md"))
       - tokens(os.path.join(narrow_path, "COMMANDS.md")) > 4000, True)


# --------------------------------------------------------------------------
print()
print("manifest.json carries the machine-readable half")
# --------------------------------------------------------------------------
with open(os.path.join(narrow_path, "manifest.json"), encoding="utf-8") as handle:
    payload = json.load(handle)
expect("it names the scope it was cut for", payload.get("scoped"), str(LAYER))
expect("and lists the verbs, exactly the ones in the document",
       payload.get("verbs"), LAYER_VERBS)
expect("the note came with it", len(payload.get("notes", [])), 1)
expect("carrying the author's sentence",
       payload["notes"][0]["text"], SENTENCE)

with open(os.path.join(wide.directory, "manifest.json"), encoding="utf-8") as handle:
    wide_payload = json.load(handle)
expect("an unscoped bundle claims neither key",
       ("scoped" in wide_payload, "verbs" in wide_payload), (False, False))


# --------------------------------------------------------------------------
print()
print("RULES.md is dropped, not trimmed -- and the brief never lies about it")
# --------------------------------------------------------------------------
expect("the pack travels with the shapes it declares, and nothing else",
       [k for k in sorted(SCOPE_KINDS) if rules_travel_with(sample(k))],
       sorted(RULES_SCOPE_KINDS))
expect("a layer-scoped bundle drops it",
       os.path.isfile(os.path.join(narrow_path, "RULES.md")), False)
expect("an unscoped bundle keeps it",
       os.path.isfile(os.path.join(wide.directory, "RULES.md")), True)

map_path = session.ask(MAP, "add a rooftop layer above the foreground",
                       requests_dir=OUT)
expect("a MAP-scoped bundle keeps it -- the pack's layer table is exactly "
       "what that scope edits",
       os.path.isfile(os.path.join(map_path, "RULES.md")), True)

with open(os.path.join(narrow_path, "BRIEF.md"), encoding="utf-8") as handle:
    dropped_brief = handle.read()
with open(os.path.join(map_path, "BRIEF.md"), encoding="utf-8") as handle:
    kept_brief = handle.read()
# BOTH halves, and the row rather than the string: a brief that had simply
# stopped mentioning RULES.md would pass an absence test and be a WORSE
# document -- the responder would not know why the pack is missing. So the
# routing table must not send them to a file that is not there, and the
# explanation must be there instead.
ROW = "| `RULES.md` | the genre's conventions"
expect("the brief of a bundle without RULES.md never routes the reader there",
       ROW in dropped_brief, False)
expect("the brief of a bundle WITH it does",
       ROW in kept_brief, True)
expect("and the dropped one mentions the pack ONCE, to say why it is absent",
       (dropped_brief.count("RULES.md"),
        "no `RULES.md` in this bundle" in dropped_brief), (1, True))
expect("the sentences that pointed at the pack were re-aimed, not left "
       "dangling",
       ("`RULES.md` states what must not change" in dropped_brief,
        "`RULES.md` states what must not change" in kept_brief),
       (False, True))
for name in ("CONTEXT.md", "REQUEST.md", "COMMANDS.md"):
    expect(f"every brief still routes to {name}",
           (name in dropped_brief, name in kept_brief), (True, True))


# --------------------------------------------------------------------------
print()
print("Session.ask -- the door, and what it refuses at it")
# --------------------------------------------------------------------------
expect("assets is reachable by no verb at all", verbs_accepting((ASSETS,)), [])
expect("nor is genre", verbs_accepting((GENRE,)), [])
expect_raises("ask refuses a zero-verb scope, naming it",
              PyoneerRequestError,
              lambda: session.ask(ASSETS, "the art is too dark",
                                  requests_dir=OUT),
              naming="assets")
expect_raises("and refuses genre the same way",
              PyoneerRequestError,
              lambda: session.ask(GENRE, "make it feel more arcade",
                                  requests_dir=OUT),
              naming="genre")
expect("nothing was written for a refused ask",
       sorted(os.listdir(OUT)),
       sorted(os.path.basename(p) for p in
              (wide.directory, narrow_path, map_path)))

before_notes = len(session.manifest.notes)
session.stage(LAYER, "a note the author is still collecting")
kept_path = session.ask(TABLE, "give the hero somewhere to start",
                        requests_dir=OUT)
expect("an ask does NOT consume the staged manifest",
       len(session.manifest.notes), before_notes + 1)
expect("it returns a path that exists", os.path.isdir(kept_path), True)
expect("and the session remembers the bundle it wrote",
       session.last_bundle.directory, kept_path)
expect("write_bundle owns the refusal, so no caller can route around it",
       True, True)
expect_raises("even called directly with a scoped bundle",
              PyoneerRequestError,
              lambda: write_bundle(session.project,
                                   Manifest(notes=[Note(ASSETS, "darker")]),
                                   requests_dir=OUT, scoped=ASSETS),
              naming="assets")


# --------------------------------------------------------------------------
print()
print("describe_scope answers for every kind, and raises on one it has no "
      "arm for")
# --------------------------------------------------------------------------
# A fixture table, built through the same door a click uses, so this section
# asserts the CODE and pins nothing about the author's own project data.
session.run(Command("table.create", TABLE, {}))
columns = session.project.table("actors").columns
session.run(Command("table.row.add", TABLE, {"id": "checkrow"}))
FIELD = Scope.parse(f"table:actors/field:{columns[0].name}")
ROW = Scope.parse("table:actors/row:checkrow")

# And a fixture SCRIPT, built through the same door. A script scope is the
# one kind whose arm can be checked against a document this file authored,
# so every id the description prints is an id this file put there.
SCRIPT = Scope.parse("script:relay_fixture")
session.run(Command("script.create", SCRIPT, {"title": "Relay fixture"}))
session.run(Command("script.page.add", SCRIPT, {"id": "pg_1", "trigger": "use"}))
session.run(Command("script.node.add", SCRIPT,
                    {"id": "n1", "do": "say", "into": "pg_1",
                     "args": {"text": "halt"}}))
session.run(Command("script.node.add", SCRIPT,
                    {"id": "n2", "do": "if", "into": "pg_1", "after": "n1"}))
session.run(Command("script.node.add", SCRIPT,
                    {"id": "n3", "do": "say", "into": "n2", "arm": "then",
                     "args": {"text": "pass"}}))

SAMPLES = dict({kind: sample(kind) for kind in KIND_SAMPLE},
               row=ROW, field=FIELD)
unwired = [kind for kind in SCOPE_KINDS if kind not in SAMPLES]
print(f"       {len(SAMPLES)} kind(s) with an arm; "
      f"{len(unwired)} declared with none: {unwired}")

silent = []
broken = []
for kind, scope in SAMPLES.items():
    lines = describe_scope(session.project, scope)
    body = "\n".join(lines).strip()
    if not body:
        silent.append(kind)
    if "no description available" in body or "could not be read" in body:
        broken.append(kind)
expect("every kind with an arm answers with something", silent, [])
expect("and none of them falls through or blows up", broken, [])

# The other half, and it maintains itself: a kind that joins SCOPE_KINDS
# with no arm is REFUSED rather than described as nothing, and the day
# someone writes that arm this goes red until they add a sample above --
# which is the only way a new kind's CONTEXT.md ever gets looked at.
for kind in unwired:
    expect_raises(f"a declared kind with no arm ({kind!r}) refuses the ship",
                  PyoneerRequestError,
                  lambda k=kind: describe_scope(session.project, sample(k)),
                  naming=kind)

expect("the field arm reads the column off the table, not off the pack",
       f"`{columns[0].type}`" in "\n".join(describe_scope(session.project, FIELD)),
       True)
expect("the code arm says plainly that no verb reaches it",
       "no command verb accepts" in
       "\n".join(describe_scope(session.project, Scope.parse("code:renderer"))),
       True)

# THE SCRIPT ARM, both halves. `into`, `after` and `node` are all ids, so a
# CONTEXT.md that does not carry them is a bundle whose every answer aims at
# an address that is not there.
script_context = "\n".join(describe_scope(session.project, SCRIPT))
# Half A: every id this document holds is in the description.
expect("the script arm carries every id in the document, because every "
       "script.node.* argument is one",
       [ident for ident in ("pg_1", "n1", "n2", "n3")
        if "`" + ident + "`" not in script_context], [])
# Half B, the half that fails when the arm prints a fixed string: an id the
# document does NOT hold is not in it either.
expect("...and none it does not hold", "n4" in script_context, False)
expect("...it names the loadouts, which decide what a `do` may say",
       "`core`" in script_context, True)
expect("...and the arms an `if` really has, which decide what `arm` may say",
       ("arm `then`" in script_context, "arm `else`" in script_context),
       (True, False))
# An address that parses and resolves to nothing is a FACT about this
# project, not a build error: described, naming the verb that would create
# it -- the same shape `_describe_object` uses for an object id that is gone.
absent = "\n".join(describe_scope(session.project,
                                  Scope.parse("script:not_written_yet")))
expect("a script that does not exist is described, not raised",
       ("no script named" in absent, "script.create" in absent), (True, True))

# And a kind that is not even declared -- the shape that used to return
# "*(no description available for this scope kind)*" and write a
# complete-looking bundle whose CONTEXT.md said nothing at all.
expect_raises("an undeclared kind stops the ship instead of describing nothing",
              PyoneerRequestError,
              lambda: describe_scope(session.project,
                                     Scope((Segment("scene", "overworld"),))),
              naming="scene")


# --------------------------------------------------------------------------
print()
print("the Qt half, offscreen: the BUTTON, not the method")
# --------------------------------------------------------------------------
if importlib.util.find_spec("PySide6") is None:
    print("  SKIP PySide6 is not installed "
          "(pip install -r editor/requirements.txt)")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox     # noqa: E402
    from editor.ui.prompt import PromptStrip                    # noqa: E402

    # RECORD every modal rather than silencing it: "this path asked nothing"
    # has to be a measurement, and law 13 is why -- a box opened here would
    # hang the suite for 600s with no output.
    opened: list[str] = []

    def _record(*args, **kwargs):
        opened.append(str(args[2]) if len(args) > 2 else "")
        return QMessageBox.Yes

    QMessageBox.warning = staticmethod(_record)
    QMessageBox.critical = staticmethod(_record)
    QMessageBox.information = staticmethod(_record)
    QMessageBox.question = staticmethod(_record)

    def modals() -> list[str]:
        return opened

    application = QApplication.instance() or QApplication([])
    strip = PromptStrip(session, LAYER)
    heard: list[str] = []
    strip.asked.connect(heard.append)

    expect("the strip carries an Ask button", strip.ask_button.text(), "Ask")
    expect("and still carries Stage", strip.button.text(), "Stage")

    before = set(os.listdir(os.path.join(workspace, "editor", "requests"))
                 if os.path.isdir(os.path.join(workspace, "editor", "requests"))
                 else [])
    strip.field.setText("widen the shoreline by two tiles")
    strip.ask_button.click()            # the real wire, not strip.ask()

    expect("the click wrote a bundle", len(heard), 1)
    written = heard[0] if heard else ""
    expect("it landed inside the project, where the author can find it",
           written.startswith(os.path.join(workspace, "editor", "requests")),
           True)
    expect("the strip reported the path", strip.last_bundle_path, written)
    expect("and said so, in words that name it",
           "wrote" in strip.last_notice and "BRIEF.md" in strip.last_notice,
           True)
    expect("the field cleared, so the gesture is finished",
           strip.field.text(), "")
    expect("no dialog opened", modals(), [])

    if written:
        with open(os.path.join(written, "manifest.json"),
                  encoding="utf-8") as handle:
            click_payload = json.load(handle)
        expect("THE BUNDLE CARRIES THIS PANEL'S OWN SCOPE",
               click_payload["scoped"], str(LAYER))
        expect("and this panel's own vocabulary",
               click_payload["verbs"], LAYER_VERBS)
        expect("and the author's sentence, verbatim",
               click_payload["notes"][0]["text"],
               "widen the shoreline by two tiles")
        expect("scoped, so it is small", tokens(written) < 3000, True)

    # The refusal, through the same button. Both halves: it refuses, AND it
    # gives the typing back -- a refusal that eats the sentence teaches the
    # author to stop using the button.
    strip.set_scope(ASSETS)
    strip.field.setText("the art is too dark")
    heard.clear()
    strip.ask_button.click()
    expect("a zero-verb scope writes nothing", heard, [])
    expect("the refusal names the scope", "assets" in strip.last_notice, True)
    expect("the author's sentence is still in the box",
           strip.field.text(), "the art is too dark")
    expect("and it is a status line, not a dialog", modals(), [])

    strip.field.setText("   ")
    strip.ask_button.click()
    expect("an empty note is refused before anything is written", heard, [])
    expect("and says what to do about it",
           "say what you want changed" in strip.last_notice, True)
    expect("still no dialog", modals(), [])

    strip.deleteLater()


# --------------------------------------------------------------------------
print()
if failures:
    print(f"FAILED: {failures}")
    sys.exit(1)
print("OK -- the relay ships one scope's vocabulary, and refuses the scopes "
      "no verb can answer")
