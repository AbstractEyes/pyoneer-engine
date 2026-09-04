"""Verify the audio subsystem: the roots, the split, the pack, the ops.

    .venv/Scripts/python.exe tools/check_audio.py

RUNS ON A MACHINE WITH NO SOUND CARD, WHICH IS THE NORMAL CASE
--------------------------------------------------------------
`SDL_AUDIODRIVER=dummy` is set before pygame is initialised, so every
assertion below is made on a runner with no audio hardware at all. That is
not a concession: it is the environment the engine has to survive, and a
check that needed a real device could never make the one assertion that
matters most -- that an absent device is survivable.

WHAT IS COVERED, AND WHY EACH HALF IS HERE
------------------------------------------
  1. `resolve_audio` orders the two roots BOTH WAYS -- the declared path wins
     when it holds a file (the no-drift identity: the argument comes back
     character for character), the shipped twin answers when it does not, and
     when NEITHER holds one the argument comes back untouched so the caller
     raises naming what the author wrote. Plus the teeth on `declared_audio`:
     an absolute name and a `..` name are refused, because an authored `.json`
     may have arrived from anywhere.

  2. The two shipped assets are the files `data/audio/CREDITS.md` says they
     are. Their sizes and sha256 prefixes are PARSED OUT OF THE DOCUMENT and
     compared to the bytes on disk, AND compared to a copy pinned here. Both,
     deliberately: the doc-derived half catches an asset swapped under a
     stale document, and the pinned half catches a document edited to match a
     swapped asset. Either one alone can be defeated by one edit. This is the
     assertion that notices an unlicensed file arriving in a public repo.

  3. `read_settings` refuses every wrong shape of `config/audio.json` and
     accepts the real one -- and the real one is read from the file, so a
     config nobody can prepare from fails here.

  4. THE SPLIT, which is the load-bearing section. A missing FILE raises
     naming the name, WITH a device and WITHOUT one. A missing DEVICE warns
     exactly once, leaves the manager unavailable, and leaves every play a
     truthful no-op returning False -- proved by making `pygame.mixer.init`
     raise, never by asserting a happy path. A second `prepare` does not warn
     again, because "warns once" is the claim.

  5. The generated fallback pack is reproducible twice over, is written only
     under the shipped root, and reads back both through the stdlib `wave`
     module and through `pygame.mixer.Sound`. That is what makes it possible
     to test the audio path with no licensed asset present at all.

  6. `play_sound` and `play_music` are in the registry, run through a real
     `ScriptRun`, and RAISE through the op when the node names a sound
     neither root holds -- the negative that separates "the op works" from
     "the op silently does nothing", which is the defect it was once
     rejected for.

NO MAP CONTENT IS PINNED
------------------------
`data/maps/starter.tmx` is never opened, and no map is read at all.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  (must precede the engine and tools.audio imports)

import hashlib
import json
import os
import shutil
import sys
import tempfile
import wave
import warnings

# Before pygame.init(). SDL reads the driver name when the subsystem opens,
# and a check that needed real hardware could not assert the thing this
# module exists to assert.
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

pygame.init()

from scripts.core.audio import (AUDIO_ROOT, CONFIG_PATH, MIXER_SIZES,
                                REPO_ROOT, SETTING_KEYS, SOUND_ROOT,
                                AudioManager, MixerSettings, available_names,
                                declared_audio, read_settings, resolve_audio,
                                shipped_audio, shipped_audio_path)
from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 PyoneerConfigKeyError, PyoneerWarning)
from scripts.game.flow.interpreter import ScriptRun
from scripts.game.flow.ops import OP_REGISTRY, CORE, resolve, resolve_args
from scripts.loaders import script_file as sf
from tools.audio import (CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, render_cli,
                         write_sounds)
from tools.audio.__main__ import SOUNDS

failures: list[str] = []
asserted: list[int] = []


def expect(label, got, want):
    asserted.append(1)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<64} got={got} want={want}")
    if not ok:
        failures.append(label)


def expect_true(label, got):
    expect(label, bool(got), True)


def expect_raises(label, exception, call, *fragments):
    """The call must raise `exception`, and its message must name each fragment.

    The fragments are the teeth: asserting only the exception TYPE passes for
    any raise anywhere inside the call, including a typo three frames down.
    """
    asserted.append(1)
    try:
        call()
    except exception as exc:
        missing = [f for f in fragments if f not in str(exc)]
        if missing:
            print(f"  FAIL {label:<64} raised {type(exc).__name__} without "
                  f"{missing}: {str(exc).splitlines()[0][:90]}")
            failures.append(label)
            return
        print(f"  ok   {label:<64} raised {type(exc).__name__}")
        return
    except Exception as exc:  # noqa: BLE001 - reporting tool
        print(f"  FAIL {label:<64} raised {type(exc).__name__}, wanted "
              f"{exception.__name__}: {exc}")
        failures.append(label)
        return
    print(f"  FAIL {label:<64} did not raise")
    failures.append(label)


def digest(path: str) -> str:
    """sha256 of a file, or a readable stand-in when it is not there."""
    if not os.path.isfile(path):
        return "<missing>"
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def write_wave(path: str, value: int, count: int = 512) -> bytes:
    """A tiny valid mono wav holding one constant sample. Returns its bytes.

    A constant rather than silence so two probes are distinguishable by their
    bytes, which is what lets section 1 say WHICH root answered.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = int(value).to_bytes(2, "little", signed=True) * count
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(payload)
    with open(path, "rb") as handle:
        return handle.read()


GOOD = {"frequency": 44100, "size": -16, "channels": 2, "buffer": 512,
        "master_volume": 0.5}
"""A settings object every section can prepare from. NOT read from disk --
section 3 reads the real file, and a check that only ever used the real one
could not tell a good config from a lucky one."""


def fresh(config=None) -> AudioManager:
    """A brand-new AudioManager, prepared. The singleton is dropped first."""
    AudioManager.reset_singleton()
    return AudioManager().prepare(GOOD if config is None else config)


print("check_audio -- two roots, two failures, one mixer")
print(f"  driver: SDL_AUDIODRIVER={os.environ.get('SDL_AUDIODRIVER')!r}; "
      f"registry: {len(OP_REGISTRY)} op(s)")


# ===========================================================================
print("\n1. resolve_audio orders the two roots, in both directions")
# ===========================================================================
PROBE = "_check_audio_probe"
SOUND_DIR = os.path.join(REPO_ROOT, *SOUND_ROOT.split("/"))
AUDIO_DIR = os.path.join(REPO_ROOT, *AUDIO_ROOT.split("/"))
sound_root_was_absent = not os.path.isdir(SOUND_DIR)
override_probe = os.path.join(SOUND_DIR, PROBE, "probe.wav")
shipped_probe = os.path.join(AUDIO_DIR, PROBE, "probe.wav")
declared = "%s/%s/probe.wav" % (SOUND_ROOT, PROBE)
absent = "%s/%s/nowhere.wav" % (SOUND_ROOT, PROBE)

try:
    override_bytes = write_wave(override_probe, 1000)
    shipped_bytes = write_wave(shipped_probe, -2000)
    expect("the two probes really are different files",
           override_bytes == shipped_bytes, False)

    # THE NO-DRIFT HALF. The argument comes back unchanged, character for
    # character, so a machine holding the author's own audio is handed
    # exactly the string it declared and cannot start playing something else.
    expect("a declared path that holds a file comes back UNCHANGED",
           resolve_audio(declared), declared)
    absolute = os.path.join(REPO_ROOT, *declared.split("/"))
    expect("...and so does the absolute spelling of it",
           resolve_audio(absolute), absolute)

    # THE FALLBACK HALF, with the very same shipped twin already in place:
    # remove the declared file and the answer moves.
    os.remove(override_probe)
    expect("with nothing at the declared path, the shipped twin answers",
           resolve_audio(declared), shipped_probe)
    expect("...and it is really the shipped bytes, not the override's",
           (digest(resolve_audio(declared)),
            hashlib.sha256(override_bytes).hexdigest()[:8]),
           (hashlib.sha256(shipped_bytes).hexdigest(),
            hashlib.sha256(override_bytes).hexdigest()[:8]))

    # THE THIRD CASE, the one a fallback usually forgets: neither root has it.
    expect("with neither root holding it, the argument comes back untouched",
           resolve_audio(absent), absent)

    # A path outside the override root is not this module's business,
    # including one on another drive -- a scratch directory routinely is, and
    # answering that with os.path.relpath raises ValueError instead.
    foreign = os.path.join(tempfile.gettempdir(), "pyoneer_no_such_sound.wav")
    expect("a path outside the override root is returned untouched",
           resolve_audio(foreign), foreign)
    expect("a map file is not a sound either",
           resolve_audio("data/maps/nothing.tmx"), "data/maps/nothing.tmx")

    # -- the prefix swap, both ways -------------------------------------
    expect("shipped_audio swaps exactly one prefix",
           shipped_audio("data/sound/sfx/chime.wav"), "data/audio/sfx/chime.wav")
    expect_raises("...and refuses a path that is not under the override root",
                  ValueError,
                  lambda: shipped_audio("data/audio/sfx/chime.wav"),
                  "data/sound")
    expect("shipped_audio_path lands in THIS checkout",
           shipped_audio_path("data/sound/sfx/chime.wav"),
           os.path.join(REPO_ROOT, "data", "audio", "sfx", "chime.wav"))

    # -- declared_audio: the gate on an authored name --------------------
    expect("a root-free name becomes the override root's path",
           declared_audio("sfx/chime.wav"), "data/sound/sfx/chime.wav")
    expect("...and a backslash-spelled one lands in the same place",
           declared_audio("sfx\\chime.wav"), "data/sound/sfx/chime.wav")
    expect_raises("an absolute name is refused", PyoneerConfigError,
                  lambda: declared_audio("C:/windows/media/chimes.wav"),
                  "absolute path", "data/sound")
    expect_raises("...and so is a POSIX absolute one", PyoneerConfigError,
                  lambda: declared_audio("/etc/passwd"), "absolute path")
    expect_raises("a name walking out with '..' is refused",
                  PyoneerConfigError,
                  lambda: declared_audio("../../secrets/private.wav"), "'..'")
    expect_raises("an empty name is refused", PyoneerConfigError,
                  lambda: declared_audio("   "), "non-empty string")
    expect_raises("a name that is not a string is refused",
                  PyoneerConfigError, lambda: declared_audio(7), "int")

    # -- available_names sees both roots ---------------------------------
    names = available_names()
    expect_true("available_names finds the shipped chime",
                "sfx/chime.wav" in names)
    expect_true("...and the probe under the OTHER root while it is there",
                "%s/probe.wav" % PROBE in names)
finally:
    shutil.rmtree(os.path.join(SOUND_DIR, PROBE), ignore_errors=True)
    shutil.rmtree(os.path.join(AUDIO_DIR, PROBE), ignore_errors=True)
    # Leave the tree as it was found: the override root is the AUTHOR'S, and
    # a check that creates it makes `data/sound/` look authored. `rmdir`
    # refuses a directory with anything in it, so this can only ever remove
    # the empty one this check made -- and it is attempted even when the
    # directory was already there, because a previous run whose rmdir lost a
    # race with a file-sync client would otherwise leave it forever.
    try:
        os.rmdir(SOUND_DIR)
    except OSError:
        if sound_root_was_absent and os.path.isdir(SOUND_DIR):
            print(f"  note {SOUND_ROOT}/ was created by this check and could "
                  f"not be removed; it is empty and safe to delete")


# ===========================================================================
print("\n2. the shipped assets are what CREDITS.md says they are")
# ===========================================================================
CREDITS = os.path.join(AUDIO_DIR, "CREDITS.md")

# Pinned HERE as well as parsed from the document. One copy can be edited to
# match a swapped file; two cannot be edited by accident. If a shipped asset
# is deliberately replaced, both of these change in the same commit and the
# licence is re-read -- which is the entire point.
PINNED = {
    "sfx/chime.wav": (133754, "33681aac2a79780f", b"RIFF"),
    "music/pleasant_moments.ogg": (2854297, "329e6690ac681a17", b"OggS"),
}
MAGIC_FOR = {"RIFF/WAVE": b"RIFF", "Ogg Vorbis": b"OggS"}


def credits_facts(text: str) -> dict:
    """The two-column tables under each `## \\`name\\`` heading, as dicts."""
    sections: dict[str, dict] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## `") and line.count("`") >= 2:
            current = line.split("`")[1]
            sections[current] = {}
        elif line.startswith("## "):
            current = None
        elif current is not None and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 2 and cells[0] and set(cells[0]) != {"-"}:
                sections[current][cells[0]] = cells[1].strip("`")
    return sections


expect_true("CREDITS.md is there at all", os.path.isfile(CREDITS))
with open(CREDITS, encoding="utf-8") as handle:
    FACTS = credits_facts(handle.read())
expect("it documents exactly the two shipped assets", sorted(FACTS),
       sorted(PINNED))

for name, (pinned_size, pinned_sha, pinned_magic) in sorted(PINNED.items()):
    path = os.path.join(AUDIO_DIR, *name.split("/"))
    stated = FACTS.get(name, {})
    expect_true("%s is on disk" % name, os.path.isfile(path))
    size = os.path.getsize(path) if os.path.isfile(path) else -1
    sha = digest(path)
    with open(path, "rb") as handle:
        head = handle.read(4)

    # Half one: the file agrees with the document.
    expect("%s: the document's byte count is the file's" % name,
           str(size), stated.get("bytes", "").replace(",", ""))
    expect_true("%s: the document's sha256 prefix is the file's" % name,
                sha.startswith(stated.get("sha256", "?").rstrip("\u2026")))
    expect("%s: the document's format is the file's magic" % name,
           MAGIC_FOR.get(stated.get("format", ""), b"?"), head)

    # Half two: the file agrees with this check. A document edited to match a
    # swapped asset passes the three above and fails these.
    expect("%s: ...and the size this check pins" % name, size, pinned_size)
    expect_true("%s: ...and the sha256 this check pins" % name,
                sha.startswith(pinned_sha))
    expect("%s: ...and the magic this check pins" % name, head, pinned_magic)

    # Half three: the terms are written down. A file whose licence row is
    # blank is a file nobody may ship, whatever its bytes say.
    expect_true("%s: the licence is recorded" % name,
                bool(stated.get("licence") or stated.get("license")))

# And pygame can really decode both, by the route CREDITS.md argues for --
# a Sound for the effect, a stream for the track.
manager = fresh()
expect_true("the mixer opened on the dummy driver", manager.available)
expect_true("the wav decodes into a Sound",
            manager.sound("sfx/chime.wav").get_length() > 0)
pygame.mixer.music.load(os.path.join(AUDIO_DIR, "music",
                                     "pleasant_moments.ogg"))
pygame.mixer.music.play()
expect("the ogg really streams", pygame.mixer.music.get_busy(), True)
pygame.mixer.music.stop()
expect("...and stops when it is told to", pygame.mixer.music.get_busy(), False)


# ===========================================================================
print("\n3. config/audio.json is judged, key by key")
# ===========================================================================
with open(os.path.join(REPO_ROOT, *CONFIG_PATH.split("/")),
          encoding="utf-8") as handle:
    AUTHORED = json.load(handle)

settings = read_settings(AUTHORED)
expect("the authored config is accepted, and is these five numbers",
       (sorted(AUTHORED), isinstance(settings, MixerSettings)),
       (sorted(SETTING_KEYS), True))
expect_true("...and its master_volume is a float in range",
            0.0 <= settings.master_volume <= 1.0)
expect_true("...and its size is one pygame takes",
            settings.size in MIXER_SIZES)
expect("the shipped engine can prepare from the shipped file",
       fresh(AUTHORED).prepared, True)


def without(key):
    return {k: v for k, v in GOOD.items() if k != key}


def swapped(key, value):
    out = dict(GOOD)
    out[key] = value
    return out


expect("a good config gives back exactly what was authored",
       read_settings(GOOD),
       MixerSettings(44100, -16, 2, 512, 0.5))
for key in SETTING_KEYS:
    expect_raises("a config missing %r raises naming it" % key,
                  PyoneerConfigKeyError, lambda k=key: read_settings(without(k)),
                  key, CONFIG_PATH)
expect_raises("an UNKNOWN key raises rather than being ignored",
              PyoneerConfigError, lambda: read_settings(swapped("bufer", 512)),
              "'bufer'")
expect_raises("a config that is not an object raises",
              PyoneerConfigError, lambda: read_settings([44100]), "JSON object")
expect_raises("frequency as a string raises", PyoneerConfigError,
              lambda: read_settings(swapped("frequency", "44100")),
              "frequency", "whole number")
expect_raises("frequency of zero raises", PyoneerConfigError,
              lambda: read_settings(swapped("frequency", 0)), "above zero")
expect_raises("a size pygame does not take raises", PyoneerConfigError,
              lambda: read_settings(swapped("size", -24)), "size is -24")
expect_raises("channels of 3 raises", PyoneerConfigError,
              lambda: read_settings(swapped("channels", 3)), "OUTPUT channel")
expect_raises("channels as a bool raises -- True IS an int in Python",
              PyoneerConfigError,
              lambda: read_settings(swapped("channels", True)), "True is an int")
expect_raises("a buffer that is not a power of two raises",
              PyoneerConfigError, lambda: read_settings(swapped("buffer", 500)),
              "power of two")
expect_raises("master_volume above 1.0 raises", PyoneerConfigError,
              lambda: read_settings(swapped("master_volume", 1.5)),
              "0.0 (silent)")
expect_raises("master_volume as a string raises", PyoneerConfigError,
              lambda: read_settings(swapped("master_volume", "loud")),
              "master_volume")
expect("an int master_volume widens to float",
       read_settings(swapped("master_volume", 1)).master_volume, 1.0)


# ===========================================================================
print("\n4. a missing FILE and a missing DEVICE are not one failure")
# ===========================================================================
loud = fresh()
expect_true("with a device, the manager is available", loud.available)
expect("...and says nothing is wrong", loud.unavailable_reason, "")
expect_true("a real sound plays", loud.play_sound("sfx/chime.wav"))
expect_true("...and is cached, not re-decoded", len(loud.loaded) == 1)
expect_true("...and playing it again reuses that one Sound",
            (loud.play_sound("sfx/chime.wav"), len(loud.loaded))[1] == 1)
expect_raises("a MISSING file raises naming it, WITH a device",
              PyoneerAssetMissingError,
              lambda: loud.play_sound("sfx/nope.wav"),
              "sfx/nope.wav", "data/sound/sfx/nope.wav",
              "data/audio/sfx/nope.wav")
expect_raises("...and a missing TRACK does too", PyoneerAssetMissingError,
              lambda: loud.play_music("music/nope.ogg"), "music/nope.ogg")
expect_raises("a volume above 1.0 raises rather than clamping",
              PyoneerConfigError, lambda: loud.play_sound("sfx/chime.wav", 2.0),
              "0.0 to 1.0")
expect_raises("loops below -1 raises", PyoneerConfigError,
              lambda: loud.play_music("music/pleasant_moments.ogg", loops=-2),
              "loops=-2")

# The music flags, both halves. `music_finished` is False before anything is
# started -- "never started" and "finished" are different answers, and a
# property that collapsed them would report a finished track on frame one.
expect("nothing started: not playing", loud.music_playing, False)
expect("nothing started: NOT finished either", loud.music_finished, False)
expect("...and no track is named", loud.music_name, "")
expect_true("the track starts", loud.play_music("music/pleasant_moments.ogg"))
expect("...and is named", loud.music_name, "music/pleasant_moments.ogg")
expect("...and reads as playing", loud.music_playing, True)
expect("...and NOT as finished", loud.music_finished, False)
loud.stop_music()
expect("once stopped it reads as finished", loud.music_finished, True)
expect("...and no longer as playing", loud.music_playing, False)

# -- now take the device away ----------------------------------------------
# By making init RAISE, not by asserting a happy path: the claim is that an
# absent sound card is survivable, and the only way to assert that is to have
# one be absent.
real_init = pygame.mixer.init


def refuse_to_open(*args, **kwargs):
    raise pygame.error("dsp: No such audio device")


AudioManager.reset_singleton()
pygame.mixer.init = refuse_to_open
try:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        silent = AudioManager().prepare(GOOD)
        after_first = len(caught)
        silent.prepare(GOOD)
        after_second = len(caught)
        categories = [w.category for w in caught]
        texts = [str(w.message) for w in caught]

    expect("init raising leaves the engine RUNNING and audio unavailable",
           (silent.prepared, silent.available), (True, False))
    expect("...and it warned exactly once", after_first, 1)
    expect("...and preparing a second time does not warn again", after_second, 1)
    expect_true("the warning is a PyoneerWarning",
                categories and issubclass(categories[0], PyoneerWarning))
    expect_true("...and it names the device, not the author's content",
                texts and "sound card" in texts[0])
    expect_true("...and it says the game keeps running silently",
                texts and "no-op" in texts[0])
    expect("the reason is pygame's own words", silent.unavailable_reason,
           "dsp: No such audio device")
    expect("play_sound on a REAL file is a truthful no-op",
           silent.play_sound("sfx/chime.wav"), False)
    expect("play_music likewise", silent.play_music("music/pleasant_moments.ogg"),
           False)
    expect("...and nothing was cached, because nothing was decoded",
           silent.loaded, ())
    expect("no device means no track is playing", silent.music_playing, False)
    expect("...and none finished, because none started", silent.music_finished,
           False)
    # THE OTHER HALF OF THE SPLIT, and the reason the two branches are apart:
    # a filename is wrong on a silent machine too.
    expect_raises("a MISSING file still raises, WITHOUT a device",
                  PyoneerAssetMissingError,
                  lambda: silent.play_sound("sfx/nope.wav"), "sfx/nope.wav")
    expect_raises("...and a bad NAME is still refused", PyoneerConfigError,
                  lambda: silent.play_sound("../../etc/passwd"), "'..'")
finally:
    pygame.mixer.init = real_init

# -- and the third state: nobody wired it up at all -------------------------
AudioManager.reset_singleton()
unwired = AudioManager()
expect("an unprepared manager knows it is unprepared", unwired.prepared, False)
expect_raises("...and RAISES rather than looking like a silent machine",
              PyoneerConfigError, lambda: unwired.play_sound("sfx/chime.wav"),
              "nothing has prepared it", "load_config")
expect_raises("...for music too", PyoneerConfigError,
              lambda: unwired.play_music("music/pleasant_moments.ogg"),
              "nothing has prepared it")

expect("the singleton really is one object",
       AudioManager() is AudioManager(), True)
expect("...and reset_singleton really replaces it",
       (lambda a: (AudioManager.reset_singleton(), a is AudioManager())[1])(
           AudioManager()), False)


# ===========================================================================
print("\n5. the generated fallback pack is reproducible, and is real audio")
# ===========================================================================
manager = fresh()
first = tempfile.mkdtemp(prefix="pyoneer_audio_a_")
second = tempfile.mkdtemp(prefix="pyoneer_audio_b_")
try:
    for scratch in (first, second):
        expect("the pack writes into a bare tree",
               render_cli(SOUNDS, "check fixture", ["--out", scratch]), 0)

    # The property that keeps the author's licensed audio safe: the CLI
    # physically cannot reach the override root, because every key has
    # already been re-rooted before a path is joined.
    roots = set()
    for base, _dirs, names in os.walk(first):
        for name in names:
            relative = os.path.relpath(os.path.join(base, name), first)
            roots.add("/".join(relative.replace(os.sep, "/").split("/")[:2]))
    expect("the CLI writes only under the shipped root", sorted(roots),
           [AUDIO_ROOT])

    expect_true("the pack has something in it", len(SOUNDS) >= 3)
    for relative in sorted(SOUNDS):
        parts = shipped_audio(relative).split("/")
        built = os.path.join(first, *parts)
        twin = os.path.join(second, *parts)
        leaf = parts[-1]
        expect_true("%s was written" % leaf, os.path.isfile(built))
        expect("%s is byte-identical across two builds" % leaf,
               digest(built), digest(twin))

        with wave.open(built, "rb") as handle:
            shape = (handle.getnchannels(), handle.getsampwidth(),
                     handle.getframerate())
            count = handle.getnframes()
        expect("%s reads back as the declared wave shape" % leaf, shape,
               (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE))
        expect_true("%s has real frames in it" % leaf, count > 1000)
        sound = pygame.mixer.Sound(built)
        expect_true("%s decodes through pygame.mixer" % leaf,
                    sound.get_length() > 0.0)
        expect_true("...and plays", sound.play() is not None)

    # Create-only-if-absent, both halves. Same tree, second pass.
    written, skipped = write_sounds(
        {shipped_audio(k): v for k, v in SOUNDS.items()}, first)
    expect("a second pass writes nothing and says so",
           (written, sorted(skipped)),
           ([], sorted(shipped_audio(k) for k in SOUNDS)))
    written, skipped = write_sounds(
        {shipped_audio(k): v for k, v in SOUNDS.items()}, first, force=True)
    expect("...and --force writes them all", (sorted(written), skipped),
           (sorted(shipped_audio(k) for k in SOUNDS), []))

    # A builder that lies is refused rather than written as a broken file.
    expect_raises("a builder returning something that is not bytes raises",
                  TypeError,
                  lambda: write_sounds({"data/audio/bad.wav": lambda: "nope"},
                                       first, force=True), "non-empty bytes")
    expect_raises("...and one returning a half frame raises", ValueError,
                  lambda: write_sounds(
                      {"data/audio/odd.wav": lambda: b"\x01\x02\x03"},
                      first, force=True), "whole number")
finally:
    shutil.rmtree(first, ignore_errors=True)
    shutil.rmtree(second, ignore_errors=True)


# ===========================================================================
print("\n6. the ops are registered, run, and refuse a sound that is not there")
# ===========================================================================
VARS = sf.read_vars({"count": {"type": "int", "default": 0, "doc": "Any."}})
DELTA = 1.0


def script(body):
    document = {"format": sf.FORMAT, "version": sf.VERSION, "id": "audio_probe",
                "loadouts": [CORE],
                "pages": [{"id": "pg", "trigger": "use", "when": [],
                           "body": body}]}
    return sf.parse_script(document, "audio_probe.json", variables=VARS)


def run_body(body):
    run = ScriptRun(script(body), variables=sf.VarStore(VARS))
    run.begin()
    return run


for name in ("play_sound", "play_music"):
    spec = resolve(name)
    expect("%s is in the registry, in core, live" % name,
           (spec.loadout, spec.status, spec.yields), (CORE, "live", False))
expect("play_sound takes exactly the arguments it documents",
       resolve("play_sound").arg_keys, ("sound", "volume"))
expect("play_music takes exactly the arguments it documents",
       resolve("play_music").arg_keys, ("track", "loops", "volume"))
expect_raises("an unknown argument is refused at LOAD", PyoneerConfigError,
              lambda: resolve_args(resolve("play_sound"),
                                   {"sound": "sfx/chime.wav", "vol": 1},
                                   None, "fixture.json"), "'vol'")
expect_raises("...and a volume out of range too", PyoneerConfigError,
              lambda: resolve_args(resolve("play_sound"),
                                   {"sound": "sfx/chime.wav", "volume": 3.0},
                                   None, "fixture.json"), "volume=3.0")

manager = fresh()
run = run_body([{"id": "n1", "do": "play_sound", "sound": "sfx/chime.wav",
                 "volume": 0.5},
                {"id": "n2", "do": "set", "var": "count", "to": 1}])
run.update(DELTA)
expect("play_sound completes in the frame it is entered, and the next node "
       "runs", (run.done, run.variables.get("count")), (True, 1))
expect("...and it really played, through the manager's cache",
       manager.loaded and manager.loaded[0].endswith("chime.wav"), True)

manager = fresh()
run = run_body([{"id": "n1", "do": "play_music",
                 "track": "music/pleasant_moments.ogg", "loops": -1},
                {"id": "n2", "do": "set", "var": "count", "to": 2}])
run.update(DELTA)
expect("play_music completes immediately too -- it starts a stream",
       (run.done, run.variables.get("count")), (True, 2))
expect("...and the manager says which track", manager.music_name,
       "music/pleasant_moments.ogg")
expect("...and it is playing, not finished",
       (manager.music_playing, manager.music_finished), (True, False))
manager.stop_music()

# THE NEGATIVE. An op naming a sound neither root holds must RAISE, not
# quietly do nothing: "registered, documented, does nothing" is the defect
# these two were once rejected to avoid.
manager = fresh()
missing = run_body([{"id": "n1", "do": "play_sound", "sound": "sfx/ghost.wav"}])
expect_raises("an op naming a missing sound RAISES rather than doing nothing",
              PyoneerAssetMissingError, lambda: missing.update(DELTA),
              "sfx/ghost.wav")
missing = run_body([{"id": "n1", "do": "play_music", "track": "music/ghost.ogg"}])
expect_raises("...and so does one naming a missing track",
              PyoneerAssetMissingError, lambda: missing.update(DELTA),
              "music/ghost.ogg")

# And the same op on a machine with no device runs to completion in silence,
# because a silent machine is not a broken script.
AudioManager.reset_singleton()
pygame.mixer.init = refuse_to_open
try:
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        AudioManager().prepare(GOOD)
    quiet = run_body([{"id": "n1", "do": "play_sound", "sound": "sfx/chime.wav"},
                      {"id": "n2", "do": "set", "var": "count", "to": 3}])
    quiet.update(DELTA)
    expect("with no device the script still runs to the end",
           (quiet.done, quiet.variables.get("count")), (True, 3))
finally:
    pygame.mixer.init = real_init
    fresh()


print()
print(f"{sum(asserted)} assertions")
if failures:
    print(f"FAILED ({len(failures)}):")
    for label in failures:
        print(f"  - {label}")
    sys.exit(1)
print("PASS")
