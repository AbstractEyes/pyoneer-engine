"""Boot a game whose MAP names an event script, and press the action key.

WHY THIS EXISTS
---------------
`docs/EVENTS.md` carries a REACHABILITY table measured from the parse tree on
every run, and before this change four of its six rows read `no`. The op
registry, the interpreter, the reader, fourteen script verbs, the event editor
with its builder and its picker and both audio ops were all complete, checked,
and UNREACHABLE FROM A RUNNING GAME -- the sixth sighting of the shape
`CLAUDE.md`'s ACTIVE WARNINGS record.

`tools/check_ops.py` already proves every op does its job when a `ScriptRun` is
handed one. This check covers the other half, and it is the half that was
missing: that a HUMAN PRESSING A KEY reaches one. So nothing below calls the
starter directly. Every run in this file begins because a fake keyboard held
the `action` verb for a frame and the engine's own chain carried it:

    press `action` -> `interact_action` records ActionFired
                   -> `action_relay` (order 90) CALLS entity.action_sink
                   -> SceneManager.actions (ActionRouter) picks the handler
                   -> MainGame.run_object_script -> ScriptRun -> flow slot

Calling `run_object_script` by hand would prove the function works. It would
not prove the WIRE does, and the wire is the entire deliverable.

WHAT IS ASSERTED, AND THE PAIR THAT GIVES EACH ONE TEETH
--------------------------------------------------------
One half of an invariant is the commonest toothless shape in this tree, so
every gate below is asserted in both directions:

    a scripts directory is read at boot
                    AND an ABSENT one loads none, silently, and still boots
    pressing action starts a run and parks it in the flow slot
                    AND the same press with the map property REMOVED starts
                        nothing -- which is the defect this change closes,
                        written as an assertion
    the run walks to completion and its `set` landed
                    AND the frames in between really were the script's: the
                        lines arrived in authored order
    `release` gives back the RECORDED value
                    AND on a body that was ALREADY unsteerable it gives back
                        False, not True, so "restored" cannot be a constant
    `play_sound` reached the audio subsystem with the authored name
                    AND the name really resolves to a file on disk
    a second trigger mid-run is refused as a START
                    AND is not dropped: it is spent as the ADVANCE
    a `pyoneer_script` naming an absent document RAISES, naming both
                    AND one naming a present document does not
    a scripted body with no `action_relay` WARNS, naming the token
                    AND a body carrying both warns not at all

WHAT THIS CHECK MAY PIN, AND WHAT IT MAY NOT
--------------------------------------------
Law 4: a check asserts what the CODE does, never what a MAP contains. Commit
`333a77a` exists solely to undo two checks that pinned the shipped map, and
the law was paid a second time by two checks that turned out to be measuring
one person's punctuation. So NOTHING here reads `data/maps/starter.tmx` or
`data/project/scripts/`. Every map, every script document and every variable
schema below is written into a temporary directory by this file, and
`main.SCENE_VARS` and `script_file.default_scripts_dir` are pointed at it --
so repainting the shipped map, renaming its script or rewriting its lines
cannot make this red, and deleting the WIRE can.

The subclass overrides `load_map` and nothing else, the same hook
`demos/runtime.py` overrides and for the same reason: `prepare_test_scene`,
`load_test_objects`, the boot-time load, the join and the route handler are
all the shipped ones, inherited by identity, so this measures `main.py` rather
than a copy of it.

    .venv/Scripts/python.exe tools/check_script_runtime.py
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede engine imports)

import json
import os
import shutil
import tempfile
import warnings

import pygame

pygame.init()

# ---------------------------------------------------------------------------
# The fake keyboard, installed BEFORE anything boots.
#
# `InputActionManager.update()` calls `pygame.key.get_pressed()` once per
# frame and indexes the result by keycode, so replacing that function drives
# the real manager through its real edge derivation. Nothing here
# re-implements an edge; `tools/check_input.py` owns that claim.
# ---------------------------------------------------------------------------

HELD: set[int] = set()


class _FakeKeys:
    def __getitem__(self, code: int) -> bool:
        return code in HELD


pygame.key.get_pressed = lambda: _FakeKeys()   # noqa: E731

from config.managers.map_data import MapData                      # noqa: E402
from scripts.core.audio import AudioManager                       # noqa: E402
from scripts.core.errors import (PyoneerAssetMissingError,        # noqa: E402
                                 PyoneerContentWarning)
from scripts.core.input import KEYBOARD                           # noqa: E402
from scripts.game.behavior import BEHAVIORS                       # noqa: E402
from scripts.game.behavior.state import state_of                  # noqa: E402
from scripts.game.flow import ops as op_module                    # noqa: E402
from scripts.game.game_camera import GameCamera                   # noqa: E402
from scripts.game.game_map import GameMap                         # noqa: E402
from scripts.loaders import script_file                           # noqa: E402

import main as main_module                                        # noqa: E402
from main import MainGame                                         # noqa: E402

failures: list[str] = []
asserted = 0


def expect(label, got, want):
    global asserted
    asserted += 1
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth: asserting only the exception TYPE passes for
    any raise anywhere inside the call, including a typo three frames down.
    """
    global asserted
    asserted += 1
    try:
        call()
    except exception as exc:
        text = str(exc)
        missing = [f for f in fragments if f not in text]
        ok = not missing
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<62} "
              f"raised {type(exc).__name__}: {text.splitlines()[0][:44]}")
        if not ok:
            failures.append(f"{label} (message lacks {missing})")
        return
    except Exception as exc:                      # noqa: BLE001 - reporting
        print(f"  FAIL {label:<62} raised {type(exc).__name__} not "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<62} did not raise")
    failures.append(label)


# ---------------------------------------------------------------------------
# The workspace: a map, a scripts directory, and a variable schema, all ours
# ---------------------------------------------------------------------------

WORKSPACE = tempfile.mkdtemp(prefix="pyoneer_script_runtime_")
SCRIPTS_DIR = os.path.join(WORKSPACE, "scripts")
ABSENT_DIR = os.path.join(WORKSPACE, "no_scripts_here")
os.makedirs(SCRIPTS_DIR)

SCRIPT_PROPERTY = main_module.SCRIPT_PROPERTY
"""Read off main.py rather than typed, so a rename moves this check with it."""

FIXTURE_LAYER = "entity"
TALK_SCRIPT = "fix_talk"
CHIME = "sfx/chime.wav"
"""A sound the shipped pack really holds -- `data/audio/CREDITS.md` names it.

Spelled here rather than read off the map, because the claim is that the
`play_sound` OP carries an authored name to the subsystem; which name is the
fixture's business.
"""

FIXTURE_VARS = {
    "talked": {"type": "bool", "default": False,
               "doc": "Whether the fixture script has already spoken once."},
}
"""This check's OWN variable schema. `main.SCENE_VARS` is pointed at it.

Law 4 again: the shipped schema is content, and a check that read it would go
red the day an author declares a second variable.
"""

SCRIPTED_LIST = "%s,interact_action,action_relay,topdown_move" % (
    main_module.PLAYER_TOKEN,)
"""What a body needs to reach route A. The token spellings come from main.py."""

NO_RELAY_LIST = "%s,interact_action,topdown_move" % (main_module.PLAYER_TOKEN,)
"""The same body with the CALLING half missing: it records and reaches nobody."""


def write_script(script_id: str, body: list) -> str:
    """One `data/project/scripts/<id>.json`-shaped document in the workspace."""
    path = os.path.join(SCRIPTS_DIR, script_id + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({
            "format": script_file.FORMAT,
            "version": script_file.VERSION,
            "id": script_id,
            "loadouts": ["core"],
            "pages": [{"id": script_id + "_pg", "trigger": "use",
                       "when": [], "body": body}],
        }, handle, indent=1)
    return path


write_script(TALK_SCRIPT, [
    {"id": "t_hold", "do": "hold", "steerable": False},
    {"id": "t_chime", "do": "play_sound", "sound": CHIME},
    {"id": "t_branch", "if": [{"var": "talked", "is": False}],
     "then": [
         {"id": "t_one", "do": "say", "who": "Fixture", "text": "line one"},
         {"id": "t_two", "do": "say", "who": "Fixture", "text": "line two"},
         {"id": "t_mark", "do": "set", "var": "talked", "to": True},
     ],
     "else": [
         {"id": "t_again", "do": "say", "who": "Fixture", "text": "line again"},
     ]},
    {"id": "t_release", "do": "release"},
])

FIXTURE_ROW = ",".join(["1"] * 8)
FIXTURE_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" \
renderorder="right-down" width="8" height="8" tilewidth="16" tileheight="16" \
infinite="0" nextlayerid="9" nextobjectid="9">
 <tileset firstgid="1" name="probe" tilewidth="16" tileheight="16" tilecount="4" columns="2">
  <image source="probe.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="Floor" width="8" height="8">
  <data encoding="csv">
%s
</data>
 </layer>
""" % (",\n".join([FIXTURE_ROW] * 8),)


def write_fixture(key: str, tokens: str, script_id: str | None) -> str:
    """A one-body map. `script_id=None` writes the object WITHOUT the property.

    That absence is the whole negative case: the same map, the same behaviors,
    the same key press, and one property fewer.
    """
    script_line = ("" if script_id is None else
                   '    <property name="%s" value="%s"/>\n'
                   % (SCRIPT_PROPERTY, script_id))
    text = (FIXTURE_HEAD
            + ' <objectgroup id="4" name="%s">\n' % FIXTURE_LAYER
            + ('  <object id="1" name="body" type="GamePlayer" x="16" y="32" '
               'width="16" height="16">\n'
               '   <properties>\n'
               '    <property name="%s" value="%s"/>\n' % (BEHAVIORS, tokens))
            + script_line
            + '   </properties>\n  </object>\n'
            + ' </objectgroup>\n</map>\n')
    path = os.path.join(WORKSPACE, key + ".tmx")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


# A real 2x2 sheet beside them, because pytmx loads the tileset image for real
# and a missing one raises before any of this is reached.
_sheet = pygame.Surface((32, 32))
for _index, _colour in enumerate(((180, 40, 40), (40, 180, 40),
                                  (40, 40, 180), (180, 180, 40))):
    _sheet.fill(_colour, pygame.Rect((_index % 2) * 16, (_index // 2) * 16,
                                     16, 16))
pygame.image.save(_sheet, os.path.join(WORKSPACE, "probe.png"))


# ---------------------------------------------------------------------------
# The audio spy: records AND delegates, so a wrong name still raises
# ---------------------------------------------------------------------------

PLAYED: list[tuple] = []
_REAL_AUDIO = AudioManager()


class _AudioSpy:
    """Counts `play_sound` and then does the real thing.

    Delegating rather than stubbing is the difference between "the op was
    reached" and "the op worked": a stub would pass for a name neither audio
    root holds, and `AudioManager.locate` RAISES for exactly that, on a silent
    machine too. Counting rather than reading the Sound cache, because a
    runner with no sound card is truthfully unavailable and a row that read
    differently there would make this check machine-dependent.
    """

    def play_sound(self, name, volume=1.0, where=""):
        PLAYED.append((name, volume, where))
        return _REAL_AUDIO.play_sound(name, volume=volume, where=where)

    def __getattr__(self, item):
        return getattr(_REAL_AUDIO, item)


op_module.AudioManager = lambda: _AudioSpy()      # noqa: E731


# ---------------------------------------------------------------------------
# Booting the SHIPPED game class on this check's own map and scripts
# ---------------------------------------------------------------------------

class FixtureGame(MainGame):
    """The shipped game, booted on a map this check wrote.

    `MAP_KEY` and `MAP_FILE` are set per subclass so the asset manager's parse
    cache cannot hand one fixture's parsed map to another.
    """

    MAP_KEY: str = ""
    MAP_FILE: str = ""

    def load_map(self):
        self.assets.maps.maps[self.MAP_KEY] = MapData({
            "name": self.MAP_KEY,
            "identifier": self.MAP_KEY,
            "file": self.MAP_FILE,
        })
        map_data = self.assets.maps.load_assets(self.MAP_KEY)
        camera = GameCamera(
            pygame.Vector2(self.screen.get_width(), self.screen.get_height()),
            pygame.Rect(0, 0,
                        map_data.tilewidth * map_data.width,
                        map_data.tileheight * map_data.height),
            scale=1)
        return camera, GameMap(map_data)


def boot(key: str, tokens: str, script_id: str | None, *,
         scripts_dir: str = SCRIPTS_DIR):
    """Boot one fixture. Returns (game, content warnings).

    Points `main.SCENE_VARS` at this check's schema and
    `script_file.default_scripts_dir` at this check's directory, so the
    SHIPPED `load_scripts()` call in `main.py` -- which takes no argument -- is
    the thing being measured, over content that belongs to this file.
    """
    path = write_fixture(key, tokens, script_id)
    cls = type("FixtureGame_" + key, (FixtureGame,),
               {"MAP_KEY": key, "MAP_FILE": path})
    previous_vars = main_module.SCENE_VARS
    previous_dir = script_file.default_scripts_dir
    main_module.SCENE_VARS = FIXTURE_VARS
    script_file.default_scripts_dir = lambda: scripts_dir
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            booted = cls(autostart=False)
            booted.begin(max_frames=1)
        return booted, [str(entry.message) for entry in caught
                        if issubclass(entry.category, PyoneerContentWarning)]
    finally:
        main_module.SCENE_VARS = previous_vars
        script_file.default_scripts_dir = previous_dir


def key_for(game, verb: str) -> int:
    """The keycode a verb is bound to, read off the RUNNING manager.

    Not from a literal: the manager was built from `config/inputs.json`, so
    rebinding `action` from `e` to `f` changes what this presses and changes
    nothing else.
    """
    for kind, name in game.input.actions[verb].inputs:
        if kind in ("keyboard", "key"):
            return KEYBOARD[name]
    raise KeyError("verb %r has no keyboard binding" % verb)


def hold(game, *verbs: str) -> None:
    """Replace what is held. Empty releases everything."""
    HELD.clear()
    for verb in verbs:
        HELD.add(key_for(game, verb))


def press(game) -> None:
    """One rising edge of `action`, then a released frame.

    Two frames, because `interact_action` fires on the RISING edge: holding
    the key for a second frame fires nothing, which is the property
    `tools/check_demo_map.py` asserts and this file relies on.
    """
    hold(game, "action")
    game.tick()
    hold(game)
    game.tick()


def spoken(game):
    """The line currently on the dialogue box, or None if there is no box."""
    box = game.dialogue.box if game.dialogue is not None else None
    return None if box is None else box.line


def of(run, attribute):
    """One attribute of a run, or None when there is no run.

    Same reason as `showing`: a mutation that stops the run STARTING must
    report as the row that failed, not as an AttributeError three rows later.
    A check that crashes proves something is wrong; a check that reports names
    which half of which invariant broke.
    """
    return None if run is None else getattr(run, attribute)


def showing(game):
    """Whether a line is on screen. None when no box was ever built.

    A function rather than `game.dialogue.box.visible` at the call sites,
    because a mutation that stops the run starting leaves no box at all, and
    an AttributeError there would report as a crash instead of as the row that
    failed -- which is the difference between a check that names the defect
    and one that only proves something went wrong.
    """
    box = game.dialogue.box if game.dialogue is not None else None
    return None if box is None else box.visible


print("check_script_runtime: a key press reaches a script")

# ---------------------------------------------------------------------------
print()
print("1. the boot reads the scripts directory -- and an absent one is free")
# ---------------------------------------------------------------------------
game, boot_warnings = boot("talker", SCRIPTED_LIST, TALK_SCRIPT)

expect("booting loads every document in the scripts directory",
       sorted(game.scripts), [TALK_SCRIPT])
expect("...and the variable store is seeded from the declared defaults",
       game.script_vars.snapshot(), {"scene.talked": False})
expect("...and the map's scripted body was joined to its document",
       [script_id for _entity, script_id in game.object_scripts],
       [TALK_SCRIPT])
expect("...to the entity the map spawned, by identity",
       game.object_scripts[0][0] is game.player if game.object_scripts
       else None, True)
expect("...and main.py registered exactly one handler for the token",
       [entry for entry in game.scene.actions.routes
        if entry[0] == main_module.INTERACT_TOKEN],
       [(main_module.INTERACT_TOKEN, "", 1)])
expect("...and a body carrying both halves of route A warns not at all",
       boot_warnings, [])

# The other half. `data/project/scripts/` is optional exactly as
# `data/project/tables/` is, so a clone with no scripted events boots
# identically rather than raising.
expect("the directory is really absent", os.path.isdir(ABSENT_DIR), False)
silent, silent_warnings = boot("silent", SCRIPTED_LIST, None,
                               scripts_dir=ABSENT_DIR)
expect("an ABSENT scripts directory loads none", silent.scripts, {})
expect("...and says nothing about it", silent_warnings, [])
expect("...and the game still boots and runs a frame",
       (silent.player is not None, silent.frame), (True, 1))

# ---------------------------------------------------------------------------
print()
print("2. pressing the action key starts a run -- through the whole chain")
# ---------------------------------------------------------------------------
# NOT by calling `run_object_script`. The keyboard is held, the frame is
# ticked, and the engine's own relay carries it.
body = game.player
state = state_of(body)
expect("before any press the body is steerable and nothing is running",
       (state.steerable, game.script_run, game.scene.flow),
       (True, None, None))

press(game)
run = game.script_run
expect("one press of `action` constructed a run", run is not None, True)
expect("...and parked it in SceneManager's duck-typed flow slot",
       game.scene.flow is run, True)
expect("...over the document the MAP named",
       run.script.id if run is not None else None, TALK_SCRIPT)
expect("...and it is running, not merely built",
       of(run, "running"), True)

# The ops before the first `say` all completed in that same frame.
expect("the `hold` took the body's steering", state.steerable, False)
expect("the `play_sound` reached the audio subsystem with the authored name",
       [name for name, _volume, _where in PLAYED], [CHIME])
expect("...and that name really resolves to a file on disk",
       os.path.isfile(game.audio.locate(CHIME)), True)
# The teeth on the row above: without this, `locate` could be answering for
# anything at all, and "the file was found" would mean nothing.
expect_raises("...while a name neither root holds RAISES, naming it",
              PyoneerAssetMissingError,
              lambda: game.audio.locate("sfx/no_such_sound.wav"),
              "sfx/no_such_sound.wav")

expect("the first authored line is on screen", spoken(game), "line one")
expect("...in a box that is open", showing(game), True)
expect("...and the box was built ON FIRST USE, not at boot",
       # It is bound into the scene now; before the press there was none, which
       # is what keeps `tools/smoke.py`'s census at 124 components.
       silent.dialogue.box is None, True)

# ---------------------------------------------------------------------------
print()
print("3. a second trigger mid-run is refused as a START and spent as ADVANCE")
# ---------------------------------------------------------------------------
# The decision, stated in `MainGame.run_object_script`: REFUSED, not queued
# and not dropped. `SceneManager.flow` is one slot because a narrative flow is
# modal, and two runs would each restore the agency the other changed.
press(game)
expect("no second run was constructed", game.script_run is run, True)
expect("...and the flow slot still holds the first", game.scene.flow is run,
       True)
expect("...and the press was NOT dropped: the line advanced",
       spoken(game), "line two")
expect("...and only one sound has been played, so the run did not restart",
       len(PLAYED), 1)

# ---------------------------------------------------------------------------
print()
print("4. the run walks to the end and its effects landed")
# ---------------------------------------------------------------------------
press(game)
expect("the last press finished the run", of(run, "running"), False)
expect("...and it ended by running off the end, not by being stopped",
       of(run, "done"), True)
expect("the `set` wrote the variable store",
       game.script_vars.snapshot(), {"scene.talked": True})
expect("the `release` gave the steering back", state.steerable, True)
expect("...and the run is holding nothing", of(run, "holding"), False)
expect("the dialogue box closed behind the last line",
       showing(game), False)

# --- the RECORDED value, not `true` ----------------------------------------
# The teeth on the row above, and the reason `release` is documented as
# "never True": a body that was ALREADY unsteerable must still be unsteerable
# afterwards. Asserting only the restore above passes for a `release` that
# assigns a constant.
state.steerable = False
press(game)                                   # starts a second run: else arm
second = game.script_run
expect("a finished run does not block the next press", second is not run, True)
expect("...and the second run took the OTHER arm of the `if`",
       spoken(game), "line again")
expect("...over the same variable store, which is why that arm was reached",
       game.script_vars.snapshot(), {"scene.talked": True})
expect("...and the sound op ran again, once", len(PLAYED), 2)
expect("mid-run the already-unsteerable body is still unsteerable",
       state.steerable, False)
press(game)
expect("the second run finished", of(second, "done"), True)
expect("...and `release` gave back the RECORDED value, which was False",
       state.steerable, False)
state.steerable = True

# ---------------------------------------------------------------------------
print()
print("5. THE NEGATIVE: no `pyoneer_script`, no run -- the defect this closes")
# ---------------------------------------------------------------------------
# The same map, the same behaviors, the same key press, one property fewer.
# Before this change every map on earth was this case.
bare, bare_warnings = boot("bare", SCRIPTED_LIST, None)
expect("the bare map's body joined no script", bare.object_scripts, [])
expect("...and it still boots without complaint", bare_warnings, [])
bare_state = state_of(bare.player)
press(bare)
expect("pressing action on it starts NO run", bare.script_run, None)
expect("...and leaves the flow slot empty", bare.scene.flow, None)
expect("...and builds no dialogue box", bare.dialogue.box, None)
expect("...and nobody's steering was taken", bare_state.steerable, True)
expect("...though the firing DID reach the router, so the press was real",
       # Without this the row above passes for a map whose body cannot fire at
       # all, which would be the wrong reason for the right answer.
       [entry for entry in bare.scene.actions.routes
        if entry[0] == main_module.INTERACT_TOKEN],
       [(main_module.INTERACT_TOKEN, "", 1)])
fired: list = []
bare.scene.actions.route(main_module.INTERACT_TOKEN,
                         lambda entity, event: fired.append(event))
press(bare)
expect("...measured: the token really fires on this map", len(fired), 1)
expect("...and STILL no run started", bare.script_run, None)

# ---------------------------------------------------------------------------
print()
print("6. a script the project does not hold RAISES, naming both")
# ---------------------------------------------------------------------------
# Law 8's reason, one layer up: an object that looks scripted and is silently
# inert is the failure a missing token already costs. `actor_row` raises for a
# `pyoneer_actor` naming an absent row; this is the same rung.
expect_raises("a `pyoneer_script` naming no document raises at boot",
              PyoneerAssetMissingError,
              lambda: boot("ghost", SCRIPTED_LIST, "no_such_script"),
              "no_such_script", "id=1", FIXTURE_LAYER, SCRIPT_PROPERTY)

# ---------------------------------------------------------------------------
print()
print("7. a scripted body that can never fire says so, and still loads")
# ---------------------------------------------------------------------------
# WARNS rather than raises, on the engine's own split: a contract violation
# raises, unusable AUTHORED CONTENT warns. A map edited halfway -- the script
# named, the relay not typed yet -- is a normal state, and an engine that
# refused to load it would take the editor down with the author still in it.
mute, mute_warnings = boot("mute", NO_RELAY_LIST, TALK_SCRIPT)
expect("a scripted body with no `action_relay` warns exactly ONCE",
       len(mute_warnings), 1)
said = mute_warnings[0] if mute_warnings else ""
expect("...naming the <object> it is about", "<object id=1>" in said, True)
expect("...and the object layer it sits on", FIXTURE_LAYER in said, True)
expect("...and the script it names", TALK_SCRIPT in said, True)
expect("...and the token that is missing",
       main_module.RELAY_TOKEN in said, True)
expect("...and the property list an author has to add it to",
       BEHAVIORS in said, True)
expect("...and it is a WARNING: the map still loaded and still spawned",
       len(mute.renderer.spawned_entities), 1)
expect("...and the join still happened, so adding the token is the only fix",
       [script_id for _entity, script_id in mute.object_scripts],
       [TALK_SCRIPT])
# What the warning is ABOUT, measured rather than asserted: this is the
# silence the diagnostic exists to break.
press(mute)
expect("...and pressing action on that body really starts nothing",
       mute.script_run, None)

# ---------------------------------------------------------------------------
print()
shutil.rmtree(WORKSPACE, ignore_errors=True)
print("%d assertion(s), %d failure(s)" % (asserted, len(failures)))
for failure in failures:
    print("  FAILED: %s" % failure)
raise SystemExit(1 if failures else 0)
