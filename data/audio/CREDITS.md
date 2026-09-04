<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every field below was read from the Wikimedia Commons API on 2026-09-04 and every byte count and hash was verified against the downloaded file on the same day by the command printed at the bottom. -->

# Shipped audio — where each file came from, and under what terms

Two files ship with this engine so that sound has something to play on a fresh
clone. **Neither is "fair use."** Fair use is a legal defence raised after the
fact, not a licence, and it is the wrong footing for a file committed to a
public repository. Both of these are unambiguously free to redistribute: one is
a CC0 dedication, the other is a public-domain recording of a public-domain
composition. Attribution is not legally required for either — it is recorded
here because knowing an asset's provenance is what lets the next person decide
whether they may ship it too.

## `sfx/chime.wav`

| | |
|---|---|
| source | https://commons.wikimedia.org/wiki/File:Chime_(1)_Sample.wav |
| original filename | `Chime (1) Sample.wav` |
| licence | **CC0 1.0 Universal** — Public Domain Dedication |
| licence text | https://creativecommons.org/publicdomain/zero/1.0/deed.en |
| credited author | "UnKnownrNone", own work |
| dated | 2024-08-24 |
| bytes | 133,754 |
| sha256 | `33681aac2a79780f…` |
| format | RIFF/WAVE |

WAV was chosen for the effect deliberately: `pygame.mixer.Sound` decodes it with
no external codec, so the sound path has one fewer thing that can be absent on a
strange machine.

## `music/pleasant_moments.ogg`

| | |
|---|---|
| source | https://commons.wikimedia.org/wiki/File:Pleasant_Moments_Piano_Roll.ogg |
| original filename | `Pleasant Moments Piano Roll.ogg` |
| licence | **Public domain** |
| composer | Scott Joplin — *Pleasant Moments* (ragtime waltz), first published 1909 |
| recording | piano roll, April 1916 |
| credit | http://www.pianola.co.nz/pleasant_moments.htm |
| bytes | 2,854,297 |
| sha256 | `329e6690ac681a17…` |
| format | Ogg Vorbis |

Public domain on both counts, which is why it is safe to ship: the composition's
copyright expired long ago (Joplin died in 1917), and the 1916 piano-roll
transfer is itself out of copyright. Ogg was chosen for music because
`pygame.mixer.music` streams it rather than decoding it whole into memory, which
is what a background track wants.

## Adding your own

Do not put a file here whose terms you have not read. This directory is the
**shipped** pack — it is committed, it is public, and it travels to anyone who
clones. Licensed audio you may play but not redistribute belongs in the
untracked override root instead, which wins over this one when it holds the same
name, exactly as `data/graphics/` wins over `data/art/` for images.

## Re-verify

    .venv/Scripts/python.exe -c "import hashlib,os;[print(os.path.getsize(p), hashlib.sha256(open(p,'rb').read()).hexdigest()[:16], p) for p in ('data/audio/sfx/chime.wav','data/audio/music/pleasant_moments.ogg')]"
