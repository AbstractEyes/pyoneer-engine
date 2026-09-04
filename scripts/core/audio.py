"""Where the engine looks for a sound, and what it does when there is no card.

TWO ROOTS, ONE TREE                                      #TAG:audio_two_roots
------------------------------------------------------------------------
The same shape as `scripts/core/art.py`, for the same reason, and it is that
module's shape deliberately rather than a second invention.

`data/sound/` is the author's own audio. It is not tracked. Music and effects
a person is licensed to PLAY are very often not licensed to REDISTRIBUTE, and
a public repository redistributes everything in it, so the override root is
the place that never travels.

`data/audio/` is the pack this repository ships, and `data/audio/CREDITS.md`
records where every byte of it came from and under what terms. It mirrors the
same relative subtree: `data/sound/sfx/chime.wav` has its shipped twin at
`data/audio/sfx/chime.wav`. One prefix swap, spelled once, in
`shipped_audio` below.

`resolve_audio` puts them in order, and gives the same three answers
`resolve_art` gives: whatever is at the declared path wins, the shipped twin
answers only when nothing is there, and when NEITHER holds a file the
argument comes back untouched so the caller raises naming what the author
wrote. A machine holding the author's own audio is handed the very string it
declared, so swapping this module in cannot change what that machine plays.

THE AUTHORED NAME IS ROOT-FREE                     #TAG:audio_name_is_rootless
------------------------------------------------------------------------
An art path is spelled `data/graphics/...` by the author because that string
is already written into `config/animations.json` and into a `.tmx`
`<image source>` by a foreign tool -- `resolve_art` inherited a vocabulary it
does not get to choose. Nothing in this tree spells an audio path yet, so
this one does choose: a script writes `"sfx/chime.wav"` and the ROOT ORDER is
the engine's business. `declared_audio` turns that name into the path the
override root would hold, and `resolve_audio` takes it from there.

The gate that makes it safe is in `declared_audio`: a name is relative and
contains no `..`, so an authored string cannot address a file outside the two
roots. A `.json` a player downloaded is authored content too.

A MISSING CARD AND A MISSING FILE ARE NOT ONE FAILURE #TAG:audio_two_failures
------------------------------------------------------------------------
They land in different branches because they have different fixes, and
collapsing them is how a game either dies on a machine that is merely silent
or goes quiet on a machine whose author misspelled a filename.

  no device   An absent OPTIONAL capability, exactly the shape
              `tools/check_all.py` already answers with SKIP when PySide6 is
              not installed. `pygame.mixer.init` raising leaves this manager
              explicitly UNAVAILABLE, warns ONCE through the stdlib warnings
              module, and every later call is a truthful no-op returning
              False. The game keeps running. A CI box has no sound card and
              must still play the whole map.

  no file     Authored content that is WRONG, and no different from a
              behavior token nobody registered. It RAISES naming the name the
              author wrote and listing what both roots do hold -- and it
              raises whether or not there is a card, because a filename is
              wrong on a silent machine too. That is the assertion a check on
              a headless runner can actually make.

`pygame.error` is caught and nothing else is. A `TypeError` out of
`pygame.mixer.init` means the numbers in `config/audio.json` are the wrong
shape, which is a contract violation this module has already refused in
`read_settings` -- catching it here would turn a bug into a shrug.

THERE IS NO MUSIC-END EVENT, ON PURPOSE                #TAG:audio_no_end_event
------------------------------------------------------------------------
`pygame.mixer.music.set_endevent` posts a real event into the same pygame
queue `scripts/core/event_manager.py` drains every frame, and NOTHING in this
tree would consume it. That is `GameEventType.USE` one layer lower: a member
emitted by somebody and bound by nobody, which this repository already pays
for. So no end event is set and no `GameEventType` member is added.

`music_playing` and `music_finished` answer the same question by asking
`pygame.mixer.music.get_busy()` at the moment somebody cares. They are two
properties rather than one because "never started" and "finished" are
different answers, which is the same distinction `ScriptRun.done` draws
against `running`. The day a listener exists, the event member is a small
change on top of this and not instead of it.

WHAT THIS COSTS                                        #TAG:audio_import_cost
------------------------------------------------------------------------
`Singleton` is imported from `config/managers/core_asset_manager.py` rather
than restated here: one instance per concrete subclass with an `__init__`
that returns early is subtle enough that two copies would drift, and a second
copy of a shared class is what cost this tree 425 duplicate lines. Measured,
that import adds 30 modules and 43 ms to the import of anything that reaches
this module -- and it CONSTRUCTS nothing, so no config file is read and no
tmx is parsed by importing it.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

import pygame

from config.managers.core_asset_manager import Singleton
from scripts.core.errors import (PyoneerAssetMissingError, PyoneerConfigError,
                                 PyoneerConfigKeyError, PyoneerWarning)

# scripts/core/audio.py -> core -> scripts -> the repo.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SOUND_ROOT = "data/sound"
"""The author's own audio. Untracked; see this module's docstring."""

AUDIO_ROOT = "data/audio"
"""The shipped pack. Tracked, and its provenance is in its own CREDITS.md."""

_SOUND_PARTS = tuple(SOUND_ROOT.split("/"))
_AUDIO_PARTS = tuple(AUDIO_ROOT.split("/"))

# `str.startswith` on a normcased prefix, not `os.path.relpath`, which RAISES
# ValueError for a path on another drive letter -- and a check's tempdir
# routinely is one. normcase preserves length, so the prefix can be cut off
# the original string. Same reasoning, same spelling, as scripts/core/art.py.
_SOUND_PREFIX = os.path.normcase(
    os.path.join(REPO_ROOT, *_SOUND_PARTS) + os.sep)

AUDIO_SUFFIXES: Tuple[str, ...] = (".wav", ".ogg", ".mp3", ".flac", ".opus")
"""What `available_names` will list. Only a listing; nothing is refused by it.

`pygame.mixer` decides what it can decode, and it is the honest authority --
a whitelist here would refuse a format a newer SDL_mixer had learned.
"""


def _parts(path: str) -> Tuple[str, ...]:
    """Split a path on either separator, dropping empties.

    Authored strings use forward slashes because they are written in `.json`
    documents; the same strings come back from `os.path` on Windows with
    backslashes in them.
    """
    return tuple(part for part in path.replace("\\", "/").split("/") if part)


def shipped_audio(relative: str) -> str:
    """`data/sound/X` -> `data/audio/X`, still repo-relative.

    RAISES for a path that is not under `data/sound/`. `tools/audio/` keys its
    generators by the path the ENGINE would look for, so a key outside that
    subtree names a file nothing would ever open, and answering with a
    plausible destination would write the pack somewhere nothing reads.
    """
    parts = _parts(relative)
    if parts[:len(_SOUND_PARTS)] != _SOUND_PARTS:
        raise ValueError(
            "%r is not under %s/, so it has no shipped twin; the pack mirrors "
            "that subtree and nothing else" % (relative, SOUND_ROOT))
    return "/".join(_AUDIO_PARTS + parts[len(_SOUND_PARTS):])


def shipped_audio_path(relative: str) -> str:
    """Where `shipped_audio(relative)` lands in THIS checkout, absolutely."""
    return os.path.join(REPO_ROOT, *_parts(shipped_audio(relative)))


def _under_repo(path: str) -> str:
    """`path` absolute, resolving a relative one against the REPO, not the cwd.

    Authored names are repo-relative, and resolving them against wherever a
    tool happened to be started is how one config names a file that exists
    and a file that does not.
    """
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(REPO_ROOT, path))


def declared_audio(name: str, where: str = "") -> str:
    """A root-free authored name -> the path the OVERRIDE root would hold.

    `"sfx/chime.wav"` -> `"data/sound/sfx/chime.wav"`. Feeding that to
    `resolve_audio` is the whole ordering: the author's file wins if it is
    there, the shipped twin answers when it is not.

    RAISES for an absolute name and for one containing `..`. A script is
    authored content that may have arrived from anywhere, and a name is a
    name -- the two roots are the only places a sound may live.
    """
    blame = ("%s: " % where) if where else ""
    if not isinstance(name, str) or not name.strip():
        raise PyoneerConfigError(
            "%sa sound is named by a non-empty string, and this is %r (%s)"
            % (blame, name, type(name).__name__))
    if os.path.isabs(name) or (len(name) > 1 and name[1] == ":"):
        raise PyoneerConfigError(
            "%ssound name %r is an absolute path. A name is relative to the "
            "audio roots (%s/ then %s/), because those two are the only "
            "places a sound may live." % (blame, name, SOUND_ROOT, AUDIO_ROOT))
    parts = _parts(name)
    if any(part == ".." for part in parts):
        raise PyoneerConfigError(
            "%ssound name %r walks out of the audio roots with '..'. A name "
            "addresses %s/ or %s/ and nothing above them."
            % (blame, name, SOUND_ROOT, AUDIO_ROOT))
    return "/".join(_SOUND_PARTS + parts)


def resolve_audio(path: str) -> str:
    """The declared path if anything is there, else its shipped twin.

    Returns the ARGUMENT UNCHANGED when a file is already at it -- the same
    no-drift identity `resolve_art` gives: on a machine holding the author's
    own audio this is an `os.path.isfile` and an identity, and the loader is
    handed the string it was handed before.

    Returns the argument unchanged when NEITHER root holds it, too, so the
    caller raises naming what the author wrote rather than a rewritten guess.
    """
    if os.path.isfile(path):
        return path
    absolute = _under_repo(path)
    if os.path.isfile(absolute):
        return absolute
    if not os.path.normcase(absolute).startswith(_SOUND_PREFIX):
        return path
    rest = _parts(absolute[len(_SOUND_PREFIX):])
    shipped = os.path.join(REPO_ROOT, *(_AUDIO_PARTS + rest))
    if os.path.isfile(shipped):
        return shipped
    return path


def available_names() -> Tuple[str, ...]:
    """Every root-free name either root actually holds, sorted and unique.

    For an error message, and for nothing else. A caller that walked this to
    decide what to play would be reading the author's private override root
    on one machine and the shipped pack on another.
    """
    found: set[str] = set()
    for root in (SOUND_ROOT, AUDIO_ROOT):
        base = os.path.join(REPO_ROOT, *_parts(root))
        for folder, _dirs, names in os.walk(base):
            for name in names:
                if not name.lower().endswith(AUDIO_SUFFIXES):
                    continue
                whole = os.path.join(folder, name)
                found.add("/".join(_parts(os.path.relpath(whole, base))))
    return tuple(sorted(found))


# ---------------------------------------------------------------------------
# The numbers in config/audio.json
# ---------------------------------------------------------------------------

MIXER_SIZES: Tuple[int, ...] = (8, -8, 16, -16, 32, -32)
"""What `pygame.mixer.init` accepts for `size`. Negative means signed."""

MIXER_CHANNELS: Tuple[int, ...] = (1, 2)
"""Mono or stereo. This is the OUTPUT channel count, not the mixing slots."""

CONFIG_PATH = "config/audio.json"
"""Where the settings are authored. Named in every message this module raises."""

SETTING_KEYS: Tuple[str, ...] = ("frequency", "size", "channels", "buffer",
                                 "master_volume")
"""The keys `config/audio.json` carries. Closed: an unknown one raises."""


@dataclass(frozen=True)
class MixerSettings:
    """The five numbers `pygame.mixer.init` is opened with, already judged.

    A frozen record rather than a dict so `prepare` can compare what it is
    being asked for against what the mixer is already open on, and do nothing
    when they agree -- re-opening a mixer stops whatever is playing.
    """

    frequency: int
    size: int
    channels: int
    buffer: int
    master_volume: float


def _whole(config: Mapping[str, Any], key: str, where: str) -> int:
    """One integer setting, refusing a bool and refusing a float.

    `bool` before `int` because in Python `True` IS an int, which is the same
    trap `BehaviorParam.coerce` documents -- `"channels": true` would
    otherwise open a mono mixer and look deliberate.
    """
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise PyoneerConfigError(
            "%s: %s is %r (%s); it is a whole number. An untyped JSON string "
            "arrives as a string, and in Python True is an int."
            % (where, key, value, type(value).__name__))
    return value


def read_settings(config: Any, where: str = CONFIG_PATH) -> MixerSettings:
    """Judge an authored audio config, or raise naming the key and the file.

    Every key is required and every value is range-checked. Nothing falls
    back to a plausible default (law 7): a `frequency` of `"44100"` that
    quietly became 22050 is a game that sounds wrong on one machine, and the
    author would have no line to read.

    An UNKNOWN key raises too, the same gate `resolve_args` puts on a script
    node: a key the writer keeps and the reader drops is a setting that looks
    applied and is not, and `bufer` is one keystroke from `buffer`.
    """
    if not isinstance(config, Mapping):
        raise PyoneerConfigError(
            "%s: audio settings are a JSON object with the keys %s, and this "
            "is %r (%s)"
            % (where, ", ".join(SETTING_KEYS), config, type(config).__name__))
    stray = sorted(k for k in config if k not in SETTING_KEYS)
    if stray:
        raise PyoneerConfigError(
            "%s: holds %s, which the mixer does not take. It takes %s."
            % (where, ", ".join(repr(k) for k in stray),
               ", ".join(SETTING_KEYS)))
    for key in SETTING_KEYS:
        if key not in config:
            raise PyoneerConfigKeyError(key, where, available=config.keys())

    frequency = _whole(config, "frequency", where)
    if frequency <= 0:
        raise PyoneerConfigError(
            "%s: frequency is %r; it is a sample rate in hertz and is above "
            "zero (44100 is the usual answer)." % (where, frequency))
    size = _whole(config, "size", where)
    if size not in MIXER_SIZES:
        raise PyoneerConfigError(
            "%s: size is %r; pygame.mixer.init takes one of %s, where a "
            "negative width means signed samples."
            % (where, size, ", ".join(str(s) for s in MIXER_SIZES)))
    channels = _whole(config, "channels", where)
    if channels not in MIXER_CHANNELS:
        raise PyoneerConfigError(
            "%s: channels is %r; it is the OUTPUT channel count -- 1 for mono "
            "or 2 for stereo -- not the number of sounds that may overlap."
            % (where, channels))
    buffer = _whole(config, "buffer", where)
    if buffer <= 0 or buffer & (buffer - 1):
        raise PyoneerConfigError(
            "%s: buffer is %r; SDL wants a power of two (256, 512, 1024). A "
            "smaller buffer is a shorter delay and more chance of a crackle."
            % (where, buffer))
    volume = config["master_volume"]
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        raise PyoneerConfigError(
            "%s: master_volume is %r (%s); it is a number from 0.0 to 1.0"
            % (where, volume, type(volume).__name__))
    volume = float(volume)
    if not 0.0 <= volume <= 1.0:
        raise PyoneerConfigError(
            "%s: master_volume is %r; it scales every other volume in the "
            "game and runs from 0.0 (silent) to 1.0 (as authored)."
            % (where, volume))
    return MixerSettings(frequency=frequency, size=size, channels=channels,
                         buffer=buffer, master_volume=volume)


def _judged_volume(volume: Any, where: str, op: str) -> float:
    """A per-call volume in 0.0..1.0, or raise. Clamping would hide a typo."""
    blame = ("%s: " % where) if where else ""
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        raise PyoneerConfigError(
            "%s%s was given volume=%r (%s); it is a number from 0.0 to 1.0"
            % (blame, op, volume, type(volume).__name__))
    level = float(volume)
    if not 0.0 <= level <= 1.0:
        raise PyoneerConfigError(
            "%s%s was given volume=%r; it runs from 0.0 to 1.0 and scales "
            "against master_volume in %s. Clamping it here would make 11 and "
            "1.1 both sound like 1.0 and neither look wrong."
            % (blame, op, volume, CONFIG_PATH))
    return level


# ---------------------------------------------------------------------------
# The subsystem
# ---------------------------------------------------------------------------

class AudioManager(Singleton):
    """One mixer, one cache of loaded Sounds, one answer about the device.

    A `Singleton` in this tree's sense: constructed once per process, later
    `AudioManager()` calls hand back the same object without re-opening
    anything, so `audio = AudioManager()` is safe at module scope and a check
    calls `AudioManager.reset_singleton()` to get a fresh one.

    It is prepared exactly once, from `main.py`, with the object
    `config/audio.json` parsed to:

        self.audio = AudioManager().prepare(self.assets.config.get('audio'))

    Being unprepared is a WIRING state and says so. `play_sound` on a manager
    nobody prepared RAISES naming that line, rather than returning False --
    False is what an absent sound CARD means here, and a game that cannot
    tell "this machine is silent" from "nobody wired the audio" has no way to
    find the missing line.
    """

    def __init__(self) -> None:
        if self.is_initialized:
            # Already built. Re-running would drop the loaded Sound cache and
            # orphan every reference already handed out.
            return
        self.name = "AudioManager"
        self.settings: Optional[MixerSettings] = None
        self._available: bool = False
        self._reason: str = "nothing has called AudioManager().prepare(...)"
        self._warned: bool = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._music_name: str = ""
        self.initialized()

    # -- lifecycle ---------------------------------------------------------

    def prepare(self, config: Any) -> "AudioManager":
        """Judge the config, open the mixer on it, and say what happened.

        Returns self either way. An absent device is not an error here --
        this module's "A MISSING CARD AND A MISSING FILE ARE NOT ONE FAILURE"
        section says why it is not, and what is.
        """
        settings = read_settings(config)
        if self._available and settings == self.settings:
            # The very same numbers, and the mixer is already up on them.
            # Re-opening would stop whatever is playing for no gain.
            return self
        self.settings = settings
        self._sounds.clear()
        self._music_name = ""
        if pygame.mixer.get_init() is not None:
            pygame.mixer.quit()
        try:
            pygame.mixer.init(frequency=settings.frequency,
                              size=settings.size,
                              channels=settings.channels,
                              buffer=settings.buffer)
        except pygame.error as exc:
            # ONLY pygame.error. A TypeError here would mean the numbers are
            # the wrong shape, which `read_settings` has already refused, and
            # swallowing it would turn a bug into a shrug.
            self._available = False
            self._reason = str(exc) or "pygame.mixer.init failed"
            if not self._warned:  # #TAG:audio_warns_once
                self._warned = True
                # Neither PyoneerContentWarning (nothing the author wrote is
                # wrong) nor PyoneerPerformanceWarning (this will not scale
                # into working). The base class is the honest one: the engine
                # carried on truthfully and a human should know.
                warnings.warn(
                    "audio is unavailable and the game will run silently: "
                    "pygame.mixer.init(frequency=%d, size=%d, channels=%d, "
                    "buffer=%d) said %r. A machine with no sound card is the "
                    "usual reason and nothing is wrong with it; every "
                    "play_sound and play_music from here on is a no-op "
                    "returning False. A missing FILE still raises."
                    % (settings.frequency, settings.size, settings.channels,
                       settings.buffer, self._reason),
                    PyoneerWarning, stacklevel=2)
            return self
        self._available = True
        self._reason = ""
        return self

    def shutdown(self) -> None:
        """Close the mixer and forget every loaded Sound.

        For a check and for a clean exit. Leaves the manager prepared but
        unavailable, which is exactly what it is.
        """
        self._sounds.clear()
        self._music_name = ""
        if pygame.mixer.get_init() is not None:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        self._available = False
        self._reason = "AudioManager.shutdown() closed the mixer"

    # -- inspection --------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when the mixer is open. False is a silent machine, not a bug."""
        return self._available

    @property
    def unavailable_reason(self) -> str:
        """Why `available` is False, in words. Empty while it is True."""
        return self._reason

    @property
    def prepared(self) -> bool:
        """True once `prepare` has judged a config, whatever the device said."""
        return self.settings is not None

    @property
    def master_volume(self) -> float:
        """The authored master scale, or 1.0 while nothing is prepared."""
        return 1.0 if self.settings is None else self.settings.master_volume

    @property
    def loaded(self) -> Tuple[str, ...]:
        """Every resolved path in the Sound cache, sorted. For a check."""
        return tuple(sorted(self._sounds))

    # -- finding a file ----------------------------------------------------

    def locate(self, name: str, where: str = "") -> str:
        """The path a root-free name resolves to, or RAISE naming the name.

        Device-independent on purpose: a filename is just as wrong on a
        machine with no sound card, and a check on a headless runner is
        exactly where that mistake should be caught.
        """
        declared = declared_audio(name, where)
        resolved = resolve_audio(declared)
        if os.path.isfile(_under_repo(resolved)):
            return resolved
        raise PyoneerAssetMissingError(  # #TAG:audio_missing_file_raises
            "sound", name, available=available_names(),
            asked_by=where or "<unknown>",
            hint="looked at %s then %s; put the file in one of them, or fix "
                 "the name" % (declared, shipped_audio(declared)))

    def sound(self, name: str, where: str = "") -> Optional[pygame.mixer.Sound]:
        """The cached `Sound` for a name, or None when there is no device.

        Raises for a name neither root holds -- before the device is
        consulted, so the two failures cannot be confused for one another.
        """
        path = self.locate(name, where)
        if not self._available:
            return None
        cached = self._sounds.get(path)
        if cached is None:
            cached = pygame.mixer.Sound(_under_repo(path))
            self._sounds[path] = cached
        return cached

    # -- playing -----------------------------------------------------------

    def play_sound(self, name: str, volume: float = 1.0,
                   where: str = "") -> bool:
        """Start one effect. True when a channel took it.

        Returns immediately either way: an effect is fired and forgotten, and
        nothing in this engine waits for one to finish.
        """
        self._require_prepared("play the sound %r" % (name,))
        level = _judged_volume(volume, where, "play_sound")
        sound = self.sound(name, where)
        if sound is None:
            return False
        sound.set_volume(level * self.master_volume)
        return sound.play() is not None

    def play_music(self, name: str, loops: int = 0, volume: float = 1.0,
                   where: str = "") -> bool:
        """Start the streamed track. True when the stream started.

        `loops` follows pygame: 0 plays it once, -1 repeats forever, n repeats
        it n more times. Returns as soon as the stream is started -- it does
        NOT wait for the track, and there is deliberately no op that does.
        """
        self._require_prepared("play the music %r" % (name,))
        level = _judged_volume(volume, where, "play_music")
        if not isinstance(loops, int) or isinstance(loops, bool) or loops < -1:
            raise PyoneerConfigError(
                "%splay_music was given loops=%r; it is a whole number, -1 to "
                "repeat forever and 0 to play once."
                % (("%s: " % where) if where else "", loops))
        path = self.locate(name, where)
        if not self._available:
            return False
        pygame.mixer.music.load(_under_repo(path))
        pygame.mixer.music.set_volume(level * self.master_volume)
        pygame.mixer.music.play(loops=loops)
        self._music_name = name
        return True

    def stop_music(self) -> None:
        """Stop the stream. Safe with no device and with nothing playing."""
        if self._available:
            pygame.mixer.music.stop()

    # -- what the music is doing -------------------------------------------

    @property
    def music_name(self) -> str:
        """The last track `play_music` started, or "" if there was none."""
        return self._music_name

    @property
    def music_playing(self) -> bool:
        """True while a track this manager started is still streaming."""
        return bool(self._available and self._music_name
                    and pygame.mixer.music.get_busy())

    @property
    def music_finished(self) -> bool:
        """True once a track this manager started has stopped.

        NOT `not music_playing`: "no track was ever started" and "the track
        ended" are different answers, and a caller deciding whether to start
        the next one needs both -- the same distinction `ScriptRun.done`
        draws against `running`. This is the queryable form of an end event;
        this module's "THERE IS NO MUSIC-END EVENT" section says why there is
        no event.
        """
        if not self._music_name:  # #TAG:audio_never_started_is_not_finished
            return False
        return not (self._available and pygame.mixer.music.get_busy())

    # -- internals ---------------------------------------------------------

    def _require_prepared(self, action: str) -> None:
        """Refuse to pretend when nobody wired this up.

        A WIRING state, told apart from a silent machine deliberately: see
        the class docstring.
        """
        if self.settings is None:
            raise PyoneerConfigError(
                "AudioManager was asked to %s and nothing has prepared it. "
                "One line, in main.py's load_config, beside the input "
                "manager:\n"
                "    self.audio = AudioManager().prepare("
                "self.assets.config.get('audio'))\n"
                "Returning False here would be indistinguishable from a "
                "machine with no sound card, and that machine's owner has "
                "nothing to fix." % (action,))


__all__ = [
    "AUDIO_ROOT", "AUDIO_SUFFIXES", "CONFIG_PATH", "MIXER_CHANNELS",
    "MIXER_SIZES", "REPO_ROOT", "SETTING_KEYS", "SOUND_ROOT", "AudioManager",
    "MixerSettings", "available_names", "declared_audio", "read_settings",
    "resolve_audio", "shipped_audio", "shipped_audio_path",
]
