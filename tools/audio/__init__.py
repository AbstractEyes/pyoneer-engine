"""Generated audio: a fallback pack the suite can make out of arithmetic.

The same idea as `tools/art/`, one domain over. Every frame this package
writes comes from a function in here: nothing is sampled, resampled,
transcoded or trimmed from anybody's recording, so the generator IS the
asset and the `.wav` is its output.

    .venv/Scripts/python.exe -m tools.audio             write the whole pack
    .venv/Scripts/python.exe -m tools.audio --list      say what it would write
    .venv/Scripts/python.exe -m tools.audio --force     redraw it after an edit
    .venv/Scripts/python.exe -m tools.audio --out DIR   write it somewhere else
    .venv/Scripts/python.exe -m tools.audio.tones       one module's sounds only

WHY THIS EXISTS AT ALL                             #TAG:audio_pack_exists_why
------------------------------------------------------------------------
`data/audio/` ships two real files -- a CC0 chime and a public-domain piano
roll, both accounted for in `data/audio/CREDITS.md`. They are the pack a
player hears. This package is for the OTHER case: proving that the audio path
works on a machine where no licensed asset is present at all. A check that can
only test the sound system by opening somebody's `.ogg` is a check that stops
being able to test it the day that file is replaced, and `tools/art/` was
built for that exact reason one domain over.

Consequently the pack is DELIBERATELY not committed. `data/art/` is tracked
because the engine has to render on a fresh clone with no art; nothing has to
make a NOISE on a fresh clone, because `data/audio/` already answers, so a
binary in git here would buy nothing and would have to be kept in step with
its generator forever.

A KEY IS AN ENGINE PATH; THE PACK LANDS SOMEWHERE ELSE  #TAG:audio_write_once
------------------------------------------------------------------------
A `SOUNDS` key is the path the ENGINE would look for -- the override root's
spelling, `data/sound/sfx/blip.wav` -- so `render_cli` sends every key through
`scripts.core.audio.shipped_audio` and writes the TWIN, under `data/audio/`.
The consequence worth knowing: this package physically cannot write into
`data/sound/`, whatever `--force` says, so running it can never overwrite
audio the author is licensed to play and not to redistribute.

Within the shipped root the write is still create-only-if-absent --
`write_sounds` skips a path that already has bytes and reports the skip, and
`--force` is the explicit way past it. Same contract as `tools/art/`'s
`write_sheets`, so "provision, never clobber" has one spelling in this tree.

A BUILDER TAKES NOTHING, READS NOTHING, AND NEEDS NO PYGAME
-----------------------------------------------------------
`Builder` is a zero-argument callable returning `bytes`: signed 16-bit
little-endian MONO frames at `SAMPLE_RATE`, which `write_sounds` wraps with
the stdlib `wave` module. Not a `pygame.mixer.Sound`, deliberately -- a
`Sound` cannot be constructed without an open mixer, and the whole point of
this pack is to be buildable on a machine that has no audio device to open.

It must be DETERMINISTIC: called twice it returns the same bytes. Anything
noise-shaped uses `lcg` below rather than `random`, because a pack that
differs per run cannot be compared, cached, or blamed.
"""
from __future__ import annotations

import argparse
import math
import os
import wave
from typing import Callable, Iterator, Mapping, Sequence

from scripts.core.audio import AUDIO_ROOT, shipped_audio

Builder = Callable[[], bytes]
"""Zero-argument, file-free, deterministic. See the module docstring."""

SAMPLE_RATE = 22050
"""Frames per second, for every sound this package writes.

Half of CD rate: these are a blip and a thud, the top octave carries nothing,
and halving it halves the bytes a check has to compare. `pygame.mixer`
resamples to whatever `config/audio.json` opened the device at.
"""

SAMPLE_WIDTH = 2
"""Bytes per frame. 2 is signed 16-bit, which is `size: -16`'s sample."""

CHANNELS = 1
"""Mono. A generated blip has nothing to say about where it is standing."""

PEAK = 32767
"""The largest magnitude a signed 16-bit frame can carry."""

# Three levels up from tools/audio/__init__.py: audio -> tools -> the repo.
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def lcg(seed: int = 1) -> Iterator[float]:
    """A deterministic -1.0..1.0 noise source, forever.

    Numerical Recipes' linear congruential generator, spelled out rather than
    taken from `random`: the stdlib's Mersenne state is global and a caller
    that seeded it elsewhere would silently change these bytes. A generator
    whose output depends on what else ran first is not reproducible.
    """
    state = seed & 0xFFFFFFFF
    while True:
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        yield (state / 0x80000000) - 1.0


def frames(samples: Sequence[float]) -> bytes:
    """-1.0..1.0 floats -> signed 16-bit little-endian bytes, clipped.

    Clipped rather than normalised: a builder that overshot should sound
    wrong, so the fix lands in the builder. Normalising here would quietly
    rescale every other sound in the same file to hide it.
    """
    out = bytearray()
    for value in samples:
        scaled = int(round(max(-1.0, min(1.0, value)) * PEAK))
        out += int(scaled).to_bytes(2, "little", signed=True)
    return bytes(out)


def envelope(index: int, count: int, attack: int, decay: float) -> float:
    """A click-free amplitude for frame `index` of `count`.

    A raw sine that starts and stops at a non-zero value is a step change in
    the speaker cone, which is audible as a tick at both ends and is the
    single most common defect in a synthesised effect. `attack` frames ramp
    in linearly; the rest decays exponentially at `decay`.
    """
    if index < attack:
        return index / float(attack) if attack else 1.0
    remaining = (index - attack) / float(max(1, count - attack))
    return math.exp(-decay * remaining)


def tone(hertz: float, seconds: float, decay: float = 6.0,
         attack_ms: float = 4.0, harmonic: float = 0.0) -> list[float]:
    """One decaying sine, optionally with its octave mixed in.

    `harmonic` is how much of `2 * hertz` to add. A pure sine reads as a test
    tone; a touch of the octave is what makes a blip sound like an interface
    rather than an oscilloscope.
    """
    count = int(SAMPLE_RATE * seconds)
    attack = int(SAMPLE_RATE * attack_ms / 1000.0)
    step = 2.0 * math.pi * hertz / SAMPLE_RATE
    out = []
    for index in range(count):
        angle = step * index
        value = math.sin(angle) + harmonic * math.sin(2.0 * angle)
        out.append(value / (1.0 + harmonic) * envelope(index, count, attack,
                                                       decay))
    return out


def write_sounds(sounds: Mapping[str, Builder], root: str,
                 force: bool = False) -> tuple[list[str], list[str]]:
    """Write every sound under `root`. Returns (written, skipped) paths.

    Keys are repo-relative and spelled with forward slashes, because that is
    how an authored name is written; `os.path.join` on the split parts is
    what makes them open on Windows.

    Raises OSError from `wave` if a write fails, rather than reporting a
    success it did not have.
    """
    written: list[str] = []
    skipped: list[str] = []
    for relative, builder in sounds.items():
        path = os.path.join(root, *relative.split("/"))
        if os.path.exists(path) and not force:
            skipped.append(relative)
            continue
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = builder()
        if not isinstance(payload, bytes) or not payload:
            raise TypeError(
                "the builder for %r returned %r; a Builder returns non-empty "
                "bytes of signed 16-bit little-endian mono frames"
                % (relative, type(payload).__name__))
        if len(payload) % SAMPLE_WIDTH:
            raise ValueError(
                "the builder for %r returned %d bytes, which is not a whole "
                "number of %d-byte frames" % (relative, len(payload),
                                              SAMPLE_WIDTH))
        with wave.open(path, "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(payload)
        written.append(relative)
    return written, skipped


def render_cli(sounds: Mapping[str, Builder], description: str,
               argv: list[str] | None = None) -> int:
    """The `--out/--force/--list` front end every module in this package uses.

    One implementation, so `-m tools.audio` and `-m tools.audio.tones` cannot
    come to disagree about what `--force` means.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--out", default=REPO_ROOT, metavar="DIR",
                        help="write under DIR instead of the repository root")
    parser.add_argument("--force", action="store_true",
                        help="overwrite files that are already there "
                             "(default: leave them alone)")
    parser.add_argument("--list", action="store_true",
                        help="print each sound's path and length, write nothing")
    args = parser.parse_args(argv)

    # Engine path in, shipped path out. See `#TAG:audio_write_once`: the keys
    # name where the ENGINE looks, and the pack is written to the tracked
    # twin of each one, which is the only root this package may write to.
    shipped = {shipped_audio(relative): builder
               for relative, builder in sounds.items()}

    if args.list:
        for relative, builder in shipped.items():
            count = len(builder()) // SAMPLE_WIDTH
            print("  %s  %d frames, %.3fs @ %d Hz"
                  % (relative, count, count / float(SAMPLE_RATE), SAMPLE_RATE))
        return 0

    written, skipped = write_sounds(shipped, args.out, force=args.force)
    for relative in written:
        print(f"  write  {relative}")
    for relative in skipped:
        print(f"  skip   {relative}  (exists; --force to overwrite)")
    print()
    print(f"{len(written)} written, {len(skipped)} left alone, "
          f"under {AUDIO_ROOT}/")
    return 0
