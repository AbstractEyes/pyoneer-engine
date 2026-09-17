<!-- pyoneer-doc: L2 -->
<!-- pyoneer-stamp: hand-written; every licence line was re-read from the live OpenGameArt page on 2026-09-17, and every byte count, sha256, sheet size and frame count was measured on the downloaded files that day by the commands printed at the bottom. -->

# Reference sprites — where each sheet came from, and under what terms

**What these are for.** Pose and proportion reference for the NovelAI sprite
pipeline's mannequin (`docs/NAI_SPRITES.md`), and a pixel-scale baseline to hold
a generated strip up against: how tall a readable side-view hero is, how many
frames a walk needs, where the feet sit. **They are not shipped in the game.**
Nothing under `scripts/` or `data/art/` loads this directory, no map points at
it, and it is not an art root.

All three are **CC0 1.0** (https://creativecommons.org/publicdomain/zero/1.0/),
which permits redistribution, so they are committed. Credit is not legally
required for any of them; it is recorded here because provenance is what lets
the next person decide whether they may use a sheet too. Only `.png` files were
taken from each download: layered sources (`.ase`, `.xcf`) and the preview
`.gif` were listed and left in the zip, and nothing in a download was run.
Filenames are the author's, with the zip's top folder dropped.

## `pixivan_knight_hero/`

| | |
|---|---|
| title | Knight Hero Platformer Animation Pack |
| creator | PixiVan |
| page | https://opengameart.org/content/knight-hero-platformer-animation-pack |
| licence field | **CC0** |
| page terms, quoted | "This asset pack can be used in free and commercial projects. You can modify the assets as you need. Credit is not necessary, but always appreciated." |
| file | https://opengameart.org/sites/default/files/knight_hero_platfomer.zip |
| zip bytes | 59,576 |
| zip sha256 | `44be2d4388e8655635a6f854304a40981bd89c9132691935a1d2e8f5ab76c24e` |
| zip members | 17: the 16 PNGs below and `Royal Knight Platformer.ase` (not taken) |
| taken | all 16 PNGs, 29,446 bytes |

Horizontal strips, one row each, facing right, RGBA. Frame count is the strip
width divided by the frame width, and matches the page's own animation list.

| strip | frame | frames |
|---|---|---|
| `Combat Ready Idle.png` | 22×24 | 5 |
| `Walk.png` · `Run.png` | 22×24 | 6 · 6 |
| `Jump.png` · `Fall.png` | 22×24 | 4 · 4 (loops, not one arc) |
| `Roll.png` | 22×24 | 11 |
| `Hit Back.png` · `Hit Front.png` | 22×24 | 6 · 6 |
| `Shield Raise.png` · `Shield Raise Walk.png` | 22×24 | 5 · 6 |
| `Sword Raise.png` · `Sword Channel.png` | 22×24 | 10 · 5 |
| `Attack 1.png` · `Attack 2.png` · `Attack 3.png` · `Attack 2 Recover.png` | 40×30 | 10 · 12 · 8 · 5 |

No land pose. Chibi proportions, so use it for frame counts and timing, not for
limb lengths. Its armour is grey and near-white, the pipeline's key and
highlight colours, so it is a poor img2img init.

**Caveats.** A moderator flagged the page on 2022-02-04 for extra terms against
repackaging, redistributing or reselling the assets, which contradict CC0; the author replied the same day that it was
fixed, and the page description read on 2026-09-17 carries only the CC0 text
quoted above. The design brief also records that the author's itch.io copy adds
a no-resale line; that copy was not re-read here. This directory holds the OGA
copy.

## `moikmellah_mv_platformer_male/`

| | |
|---|---|
| title | MV Platformer Male (32x64) |
| creator | MoikMellah |
| page | https://opengameart.org/content/mv-platformer-male-32x64 |
| licence field | **CC0** |
| page terms, quoted | "License is CC0 - do as you wish." The author, in a 2016-11-25 comment: "it is absolutely free to use for any purpose, no strings attached." |
| file | https://opengameart.org/sites/default/files/maleBase_0.zip (the page labels it `maleBase.zip`) |
| zip bytes | 349,555 |
| zip sha256 | `d97257856c82f3af1f65eac8ce77b9db26a4fc425f01eba6b5633c990c9f77f6` |
| zip members | 26: 5 directories, `maleBase.xcf` and `frameTestAnim.gif` (not taken), and the 19 PNGs below |
| taken | all 19 PNGs, 134,568 bytes |

`frameGuide.png` (labelled), `maleBasePreview.png` (100×100), and layer sheets
that stack on one grid: `base/` (3 skin tones), `head/` (8), `outfit/` (4) and
`full/` (2 composites). Every sheet but the preview is 320×640 RGBA: a 10×10
grid of **32×64** frames, facing right, rows 6–9 empty.

| row | columns → animation (from `frameGuide.png`) |
|---|---|
| 0 | 0 idle · 1–6 walk · 7–9 crouch |
| 1 | 0 stand · 1–2 damage high · 3–4 damage low · 5–6 damage crouch · 7–9 jump |
| 2–4 | vertical strike, horizontal strike, jab, guard: standing, crouching, air |
| 5 | 1–2 air damage / falling · 4 KO |

No run and no land. Human proportions, so this is the **primary reference for
the mannequin's limb lengths**.

## `grafxkid_classic_hero/`

| | |
|---|---|
| title | Classic Hero |
| creator | GrafxKid |
| page | https://opengameart.org/content/classic-hero |
| licence field | **CC0** |
| page terms, quoted | The author, in a 2019-02-09 comment: "Mr. Man is public domain, so crediting is optional" |
| file | https://opengameart.org/sites/default/files/Old%20hero.png (a bare PNG, no zip) |
| bytes | 2,361 |
| sha256 | `4805f1708a691879e152f6f58699b6bfd9069d72c15ebaa65dbd855cc1426a28` |
| taken | `Old hero.png`, as downloaded |

128×112 RGB on an opaque background of RGB(157,142,135): an 8×7 grid of
**16×16** cells with an empty one-cell border, 26 cells used. There is no frame
guide, so the rows below are a visual reading only: row 1 front-facing idle (4,
one blinking), a front-facing hurt pose and a parachute canopy; row 2 side-view
stand, run and air frames; row 3 side-view jump, **land** (a squat) and kicks;
row 4 swim (6); row 5 punch (3). Side views face right.

The only sheet here with a land pose. **Caveat:** CC0 waives copyright, not
trademark, so do not brand anything with the name "Mr. Man".

## Adding a sheet

Read the licence on the page itself before adding one, and add it here in the
same change. This directory is committed and public, so it takes CC0 or
public-domain work only. A sheet whose terms forbid redistribution may still be
looked at locally, from the untracked `data/graphics/`, but it never lands here
and never becomes an img2img init for output that might be committed.

## Re-verify

Offline: one digest per directory, over every PNG's path (relative to that
directory) and sha256. Expected output:

    3e3d990f82e5c031 grafxkid_classic_hero
    c62653d702d4378b moikmellah_mv_platformer_male
    be8400c40a52f084 pixivan_knight_hero

The command:

    .venv/Scripts/python.exe -c "import hashlib,pathlib as P;[print(hashlib.sha256(''.join(f'{p.relative_to(d).as_posix()} {hashlib.sha256(p.read_bytes()).hexdigest()}\n' for p in sorted(d.rglob('*.png'),key=lambda p:p.relative_to(d).as_posix())).encode()).hexdigest()[:16], d.name) for d in sorted(P.Path('data/reference/sprites').iterdir()) if d.is_dir()]"

Online (fetches from opengameart.org only): the three downloads still hash as
recorded above.

    .venv/Scripts/python.exe -c "import hashlib,urllib.request as u;[print(hashlib.sha256(u.urlopen(u.Request(x,headers={'User-Agent':'Mozilla/5.0'}),timeout=60).read()).hexdigest()[:16], x) for x in ('https://opengameart.org/sites/default/files/knight_hero_platfomer.zip','https://opengameart.org/sites/default/files/maleBase_0.zip','https://opengameart.org/sites/default/files/Old%20hero.png')]"
