"""The three sounds the fallback pack is made of: a blip, a thud, a jingle.

    .venv/Scripts/python.exe -m tools.audio.tones --list

Three, because three is what it takes to cover the shapes the engine plays:
a short interface tick, a low-frequency impact with a noise component, and a
sequence with more than one note in it. A fourth would be decoration; a
second one of the same shape would prove nothing the first did not.

Every builder here is pure arithmetic over `math.sin` and `tools.audio.lcg`,
takes no argument, opens no file, and returns the same bytes every time --
which is what `tools/check_audio.py` builds twice into two scratch trees and
compares.
"""
from __future__ import annotations

import math

from tools.audio import (Builder, SAMPLE_RATE, envelope, frames, lcg,
                         render_cli, tone)


def blip() -> bytes:
    """A short high tick. What a menu cursor or a picked-up coin sounds like.

    880 Hz with a little of its octave, 90 ms, decaying fast. Short enough
    that two in quick succession do not smear into each other, which is the
    whole job of an interface sound.
    """
    return frames(tone(880.0, 0.09, decay=7.0, attack_ms=3.0, harmonic=0.25))


def thud() -> bytes:
    """A low impact: a landing, a door, a chest lid.

    A sine sliding from 150 Hz down to 60 Hz, with a decaying band of
    deterministic noise on top. The pitch DROP is what makes it read as an
    impact rather than a bass note -- a fixed low sine sounds like a hum, and
    the ear hears the slide as something losing energy.
    """
    seconds = 0.22
    count = int(SAMPLE_RATE * seconds)
    attack = int(SAMPLE_RATE * 0.002)
    noise = lcg(seed=20260904)
    out = []
    angle = 0.0
    for index in range(count):
        share = index / float(count)
        hertz = 150.0 - 90.0 * share
        # The phase is ACCUMULATED, not recomputed as `2*pi*f*t`: with a
        # sliding frequency the closed form jumps the phase every frame,
        # which is a burst of clicks rather than a slide.
        angle += 2.0 * math.pi * hertz / SAMPLE_RATE
        body = math.sin(angle)
        grit = next(noise) * 0.35 * math.exp(-9.0 * share)
        out.append((body * 0.85 + grit) * envelope(index, count, attack, 5.0))
    return frames(out)


def jingle() -> bytes:
    """Two notes, E5 then A5: the four-notes-shorter version of a fanfare.

    A rising fourth, which is the interval an ear reads as "good news" almost
    regardless of what came before it. The two notes are concatenated rather
    than crossfaded, and each carries its own envelope, so the join is at
    silence and cannot click.
    """
    first = tone(659.255, 0.18, decay=5.0, attack_ms=6.0, harmonic=0.2)
    second = tone(880.0, 0.34, decay=4.0, attack_ms=6.0, harmonic=0.3)
    return frames(first + second)


SOUNDS: dict[str, Builder] = {
    "data/sound/sfx/blip.wav": blip,
    "data/sound/sfx/thud.wav": thud,
    "data/sound/sfx/jingle.wav": jingle,
}
"""Engine path -> builder. Keys are the OVERRIDE root's spelling; the pack is
written to their shipped twins. See `#TAG:audio_write_once`."""


if __name__ == "__main__":
    raise SystemExit(render_cli(SOUNDS, "the generated tones"))
