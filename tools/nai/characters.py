"""Characters as data: one JSON file per outfit, loaded into a model.Identity.

OWNER: the author writes the files; this module refuses a bad one.

    tools/nai/characters/<name>.json
    {
      "tags":    "brown hair, short hair, red scarf, blue tunic, ...",
      "anchor":  "brown hair, red scarf, blue tunic",
      "colours": {"skin": "#E8B48C", "hair": "#6B4226", ...},
      "subject": "girl",                       OPTIONAL, default "boy"
      "garments": {"hat": "wizard", "cape": true, "neck": "none",
                   "legwear": "dress", "footwear": "heels"}   OPTIONAL
    }

RESPONSIBILITY
--------------
Say which characters exist (`available`), turn one file into the
`model.Identity` a recipe is built for (`load`, `load_file`, `parse`), and
hold the ONE per-tag caption rule (`tag_problem`) that this loader,
`recipes.build_recipe` (an Identity built in code) and
`recipes.character_caption` all apply, so a count, rating, quality, view,
negative or contradicting-subject tag is refused by one function whichever
route it arrives on.

`tags` goes into the base caption, `anchor` into every character caption,
`subject` decides the count tag and every caption's first word, `garments`
decide what the mannequin draws, and `colours` paint it. Nothing else in
this package reads a character file.

RULES -- every refusal is a ValueError naming the file and the field
-----
* The file is UTF-8 (a BOM is allowed) holding ONE JSON object, with no key
  written twice at any depth, and no field outside `FIELDS`: an unknown
  field and a missing REQUIRED_FIELDS field are each refused by name, and
  `OPTIONAL_FIELDS` may be left out (every file written before they existed
  loads unchanged, as `model.DEFAULT_SUBJECT` in `model.DEFAULT_GARMENTS`).
* `subject` is one of model.SUBJECT_NAMES ("boy", "girl").
* `garments` is an object; every key is one of model.GARMENT_SLOTS by name
  and every value is one of that slot's `choices` AT ITS OWN TYPE, so `0`
  is not `false`. A key that is left out means that slot's `default`.
* `tags` and `anchor` are non-empty ASCII strings of comma-separated tags. No
  tag is empty (`a, , b`); each tag is stripped and the tags are re-joined
  with ", ", so spacing around commas is not significant and nothing else is
  rewritten.
* Every tag of either field has `tag_problem(tag, subject) is None`, JUDGING
  WHAT THE MODEL READS, NOT THE COMMA-SEPARATED SPELLING: the text is
  lower-cased, NovelAI's emphasis syntax (`{}`, `[]`, a `1.5::` weight and
  its closing `::`, `WEIGHT_RX`) is taken off and every UNDERSCORE becomes a
  space (`judged`) before a rule looks -- so a booru spelling is judged like
  the words it spells, `magical_girl` exactly as `magical girl` -- and a
  count or a refused word is found anywhere inside a tag, not only as the
  whole tag. Refused, each by its own name (`TAG_PROBLEMS`):
    - a character outside printable ASCII 0x20-0x7E (a NUL, a newline, a tab);
    - `rating:` however spaced (model.RATING_RX);
    - a count (`1boy`, `2 girls`, `10girls`, `6+others`, `multiple girls`,
      `no humans`, `brown hair 2girls`, `{2girls}`), COUNT_RX;
    - a tag of model.QUALITY_TAIL as a phrase (`{masterpiece}`);
    - a rating word (`nsfw`, `nude`, ...), RATING_WORDS;
    - a view that contradicts the recipe's side view (`facing left`,
      `from behind`, ...), VIEW_PHRASES;
    - a tag that IS one of model.NEGATIVE's tags (`blurry`) -- the whole tag
      only, so `cropped jacket` is not `cropped`;
    - a word naming a DIFFERENT subject than this file's (`male` or `man`
      in a girl file, `woman` in a boy file), SUBJECT words, as whole words
      so `boyish` names nobody.
  The count, the quality tail, the rating, the view and the subject are
  written once, by the recipe.
* Every tag of `anchor` is, verbatim, a tag of `tags`. So every anchor word
  appears in the tags, and an anchor cannot assemble `red hair` out of
  `brown hair, red scarf` either.
* `colours` maps EXACTLY the parts this file's garments draw
  (`model.garment_parts`, model.IDENTITY_PARTS for the default outfit) to
  `#RRGGBB` strings (either case). Three refusals with their own messages
  (`parts_problem`): an UNKNOWN part (not in model.PARTS at all), an UNUSED
  part (a real part these garments do not draw -- a `scarf` colour under
  `"neck": "none"` is paint nobody ever sees), and a MISSING part. The
  Identity lists them in model.PARTS order whatever the file's order.
* THE DISTANCE RULE: every colour's Euclidean RGB distance to
  model.BACKGROUND_RGB (the grey key) and to model.OUTLINE_RGB (the
  near-black outline) is AT LEAST `MIN_KEY_DISTANCE`; a colour strictly
  closer to either is refused. Integer arithmetic: refused when
  dr*dr + dg*dg + db*db < MIN_KEY_DISTANCE ** 2.
* THE SHADE RULE: the mannequin also DRAWS every colour at model.FAR_SHADE
  (far limbs) and model.INNER_SHADE (inner lines), by model.shade; each of
  those shades keeps a distance of AT LEAST `MIN_SHADE_KEY_DISTANCE` from
  model.BACKGROUND_RGB, or pixelize keys figure pixels out as background.
  Shades are not judged against the outline (a dark shade beside the
  outline is what an inner line is).
* The token budget is NOT judged here: it depends on the recipe's words, so
  `recipes.build_recipe` refuses an identity whose worst recipe exceeds it.

INVARIANTS
----------
* AN OUTFIT CHANGE IS A NEW FILE, NEVER A CODE EDIT. `scout.json` is the
  default (`DEFAULT_CHARACTER`) and reproduces recipes.IDENTITY exactly --
  tools/check_nai.py pins that, so the brief's caption pins stay valid. To
  change an outfit, copy it under a new name.
* THE NAME IS THE FILE STEM, and it is spelled into output paths (the render
  file name, the sprites directory), so a legal name matches `NAME_RX` and
  names a regular file. An unknown name is refused listing the files that
  exist; it is never mapped to the default.
* Standard library and `model` only; nothing is cached, so an edited file is
  read by the next command, and `CHARACTERS_DIR` is read at call time by
  every function whose `directory` is left None.
"""
from __future__ import annotations

import json
import os
import re
from typing import Iterable

from tools.nai.model import (BACKGROUND_RGB, DEFAULT_GARMENTS,
                             DEFAULT_SUBJECT, FAR_SHADE, GARMENT_SLOTS,
                             INNER_SHADE, NEGATIVE, OUTLINE_RGB, PARTS,
                             QUALITY_TAIL, RATING_RX, SUBJECTS,
                             SUBJECT_NAMES, Garments, Identity,
                             garment_parts, garment_problem, garments_text,
                             shade)
from tools.nai.model import subject as subject_named

CHARACTERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "characters")
"""Where the character files live: tools/nai/characters/. Read when a
function is called with `directory` None, never bound at import."""

DEFAULT_CHARACTER = "scout"
"""The character every command uses when none is named; recipes.IDENTITY."""

REQUIRED_FIELDS: tuple[str, ...] = ("tags", "anchor", "colours")
"""Every character file writes these three."""

OPTIONAL_FIELDS: tuple[str, ...] = ("subject", "garments")
"""A file may leave these out; it then means model.DEFAULT_SUBJECT in
model.DEFAULT_GARMENTS, which is what every file written before the fields
existed means. ADDING A FIELD HERE IS A FILE-FORMAT CHANGE (CLAUDE.md law
8): the name is spelled in every shipped character file."""

FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS
"""Every field a character file may hold, required ones first."""

NAME_RX = re.compile(r"[a-z][a-z0-9_]*")
"""A legal character name, which is also its file stem (fullmatch)."""

HEX_RX = re.compile(r"#[0-9A-Fa-f]{6}")
"""A legal colour (fullmatch)."""

MIN_KEY_DISTANCE = 48
"""DESIGN: the least Euclidean RGB distance an identity colour keeps from the
grey key and from the outline. pixelize measured noisy key-grey block medians
up to 20 apart and merges palette entries within 12 (post.MERGE_DISTANCE);
48 keeps more than twice that spread between a colour and either reserved
colour. The shipped scout's nearest pair, belt to outline, is 63.6."""

MIN_SHADE_KEY_DISTANCE = 40
"""DESIGN: the least Euclidean RGB distance each drawn shade of a colour
(x model.FAR_SHADE, x model.INNER_SHADE) keeps from the grey key: twice the
20 pixelize measured between noisy key-grey block medians. Smaller than
MIN_KEY_DISTANCE because the shipped scout's nearest shade, skin x0.7, is
45.4. `#B7B7B7` is 95.3 from the key and draws its far leg in the key
itself."""

SHADES: tuple[tuple[float, str], ...] = (
    (FAR_SHADE, "the far arm and leg"),
    (INNER_SHADE, "inner lines"),
)
"""Every factor the mannequin draws a colour at besides 1, with what it draws."""

WEIGHT_RX = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)::|::|[{}\[\]]")
"""NovelAI's emphasis syntax: a numeric weight opening (`1.5::`, `-1::`),
the `::` that closes it, and the `{` `}` `[` `]` brackets. Replaced by a
space before a tag is judged, so `{2girls}` is judged as `2girls`."""

COUNT_RX = re.compile(r"\d+\+?[\s_-]*(?:boy|girl|other)s?"
                      r"|multiple[\s_-]+(?:boy|girl|other)s"
                      r"|\bno[\s_-]+humans\b")
"""A count, SEARCHED anywhere in a judged tag: `1boy`, `2 girls`, `10girls`,
`6+others`, `multiple girls`, `no humans`, and `brown hair 2girls`."""

QUALITY_TAGS: frozenset[str] = frozenset(
    t.strip().lower() for t in QUALITY_TAIL.split(","))
"""The tags of model.QUALITY_TAIL, lower-cased."""

RATING_WORDS: tuple[str, ...] = (
    "nsfw", "explicit", "questionable", "sensitive", "nude", "nudity",
    "naked")
"""Words that ask for a rating other than the recipe's `rating:general`,
searched as whole words in a judged tag."""

VIEW_PHRASES: tuple[str, ...] = (
    "facing left", "facing viewer", "facing away", "from behind",
    "from front", "from above", "from below")
"""Views that contradict the recipe's `from side, facing right`, searched as
whole phrases in a judged tag."""

NEGATIVE_TAGS: frozenset[str] = frozenset(
    t.strip().lower() for t in NEGATIVE.split(","))
"""The tags of model.NEGATIVE, lower-cased: a tag EQUAL to one is refused."""

SUBJECT_WORDS: dict[str, tuple[str, ...]] = {
    s.name: tuple(word for other in SUBJECTS if other is not s
                  for word in other.words)
    for s in SUBJECTS}
"""Per subject, every word that names a DIFFERENT subject -- what a file of
that subject may not carry in a tag. Read off model.SUBJECTS, never typed
here, so a subject added there is refused here in the same change."""

TAG_PROBLEMS: dict[str, str] = {
    "control character": "every tag is printable ASCII, 0x20 to 0x7E",
    "rating tag": "the rating is written once, by the recipe, at the end of "
                  "the base caption",
    "count tag": "the count is written once, by the recipe, at the head of "
                 "the base caption",
    "quality tag": "the quality tail is written once, by the recipe, at the "
                   "end of the base caption",
    "rating word": "every caption is rated general, and the negative prompt "
                   "refuses nsfw",
    "view tag": "the recipe fixes the view: every frame is drawn from the "
                "side, facing right",
    "negative tag": "the negative prompt refuses it, so a caption may not "
                    "also ask for it",
    "subject word": "the subject is written once, by the recipe: this "
                    "file's 'subject' field becomes the "
                    "count at the head of the base caption and the first "
                    "word of every character caption, so a tag naming a "
                    "different one asks for two people",
}
"""Every answer `tag_problem` gives, with why the rule exists."""


def _phrase_rx(phrases) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(
        r"\s+".join(re.escape(word) for word in phrase.split())
        for phrase in sorted(phrases, key=len, reverse=True)) + r")\b")


_QUALITY_RX = _phrase_rx(t for t in QUALITY_TAGS if not RATING_RX.search(t))
_RATING_WORD_RX = _phrase_rx(RATING_WORDS)
_VIEW_RX = _phrase_rx(VIEW_PHRASES)
_SUBJECT_RX: dict[str, re.Pattern] = {
    name: _phrase_rx(words) for name, words in SUBJECT_WORDS.items()}


def judged(tag: str) -> str:
    """`tag` as `tag_problem` judges it: lower-cased, WEIGHT_RX replaced by
    spaces, UNDERSCORES replaced by spaces, runs of whitespace collapsed to
    one space, stripped.

    THE UNDERSCORE IS NORMALISED HERE, FOR EVERY RULE AT ONCE, and not in one
    rule's pattern. A booru tag is written `magical_girl` as often as
    `magical girl`, and the two ask the model for the same thing; the word
    rules are `\\b`-bounded phrases, so without this an underscore hides
    every one of them (MEASURED: `magical_girl` loaded into a boy file and
    `old_man` into a girl file, each producing a caption asking for two
    people -- the exact failure the subject rule exists to stop). COUNT_RX
    already spelled `[\\s_-]` itself; that is now belt and braces rather than
    the only rule that knew (CLAUDE.md, ACTIVE WARNINGS: the sibling route).
    """
    return " ".join(WEIGHT_RX.sub(" ", tag.lower()).replace("_", " ").split())


def tag_problem(tag: str, subject: str = DEFAULT_SUBJECT) -> str | None:
    """Why `tag` may not stand in a `subject` identity or character caption.

    A key of TAG_PROBLEMS, the first that applies, in its order: a character
    of `tag` outside 0x20-0x7E; model.RATING_RX in the lower-cased tag; and,
    on `judged(tag)`, COUNT_RX found anywhere, a QUALITY_TAIL tag as a whole
    phrase, a RATING_WORDS word, a VIEW_PHRASES phrase, a tag equal to one
    of NEGATIVE_TAGS, and a SUBJECT_WORDS word of ANOTHER subject as a whole
    word. None when the tag is fine. The ONE rule behind this loader,
    recipes.build_recipe and recipes.character_caption; ValueError for a
    `subject` that is not one of model.SUBJECT_NAMES, because a tag judged
    against a subject nobody declared is judged against nothing.
    """
    subject_named(subject)
    if any(not " " <= ch <= "~" for ch in tag):
        return "control character"
    if RATING_RX.search(tag.lower()):
        return "rating tag"
    core = judged(tag)
    if COUNT_RX.search(core):
        return "count tag"
    if _QUALITY_RX.search(core):
        return "quality tag"
    if _RATING_WORD_RX.search(core):
        return "rating word"
    if _VIEW_RX.search(core):
        return "view tag"
    if core in NEGATIVE_TAGS:
        return "negative tag"
    if _SUBJECT_RX[subject].search(core):
        return "subject word"
    return None


def tag_refusal(tag: str, problem: str,
                subject: str = DEFAULT_SUBJECT) -> str:
    """The ONE sentence every route writes for a tag `tag_problem` refused.

    `carries the <problem> '<tag>'; <why>`, and for a `subject word` the
    subject the tag was judged against -- which the static TAG_PROBLEMS text
    cannot say. A girl file refusing `male focus` used to end "this file's
    'subject' field (default 'boy')", a parenthetical about the FIELD's
    default that reads as a statement about THIS FILE and names the wrong
    subject.

    This loader, `recipes.build_recipe` and `recipes.character_caption` all
    call it, so the sentence cannot drift between the three routes into one
    caption (CLAUDE.md, ACTIVE WARNINGS: the sibling route).
    """
    text = f"carries the {problem} {tag.strip()!r}; {TAG_PROBLEMS[problem]}"
    if problem == "subject word":
        text += f" -- and the subject judged here is {subject!r}"
    return text


def distance_sq(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    """Squared Euclidean distance between two RGB triples, in integers."""
    return sum((x - y) * (x - y) for x, y in zip(a, b))


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


class _DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKey(key)
        out[key] = value
    return out


def _refused(source: str, field: str | None, message: str) -> ValueError:
    where = (f"character file {source}, field {field!r}" if field is not None
             else f"character file {source}")
    return ValueError(f"{where}: {message}")


def available(directory: str | None = None) -> tuple[str, ...]:
    """The character names under `directory` (CHARACTERS_DIR when None):
    every `<name>.json` whose stem matches NAME_RX and that is a regular
    file, sorted. ValueError naming the directory when it cannot be
    listed."""
    directory = CHARACTERS_DIR if directory is None else directory
    try:
        entries = os.listdir(directory)
    except OSError as exc:
        raise ValueError(f"the character directory {directory} cannot be "
                         f"listed: {exc}") from exc
    return tuple(sorted(
        entry[:-len(".json")] for entry in entries
        if entry.endswith(".json") and NAME_RX.fullmatch(entry[:-len(".json")])
        and os.path.isfile(os.path.join(directory, entry))))


def unknown_character(name: object, directory: str | None = None) -> str:
    """The refusal text for a character name that is not a file here."""
    directory = CHARACTERS_DIR if directory is None else directory
    names = available(directory)
    listed = ", ".join(f"{n} ({n}.json)" for n in names) or "none"
    return (f"unknown character {name!r}: a character is a file "
            f"<name>.json under {directory} with a name matching "
            f"{NAME_RX.pattern}; available: {listed}")


def file_for(name: str, directory: str | None = None) -> str:
    """The path `load(name, directory)` reads: `<directory>/<name>.json`,
    normalised. Judges nothing; `load` refuses a name first."""
    directory = CHARACTERS_DIR if directory is None else directory
    return os.path.normpath(os.path.join(directory, f"{name}.json"))


def load(name: str, directory: str | None = None) -> Identity:
    """The Identity in `file_for(name, directory)`.

    ValueError listing the available files when `name` is not one of
    `available(directory)` (an illegal name included, so no path can be
    smuggled in), and the file's own refusal (`parse`) otherwise.
    """
    directory = CHARACTERS_DIR if directory is None else directory
    if not isinstance(name, str) or name not in available(directory):
        raise ValueError(unknown_character(name, directory))
    return load_file(file_for(name, directory))


def load_file(path: str) -> Identity:
    """`parse` of the bytes at `path`; ValueError naming it when unreadable."""
    source = os.path.normpath(path)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise _refused(source, None, f"cannot be read: {exc}") from exc
    return parse(raw, source)


def parts_problem(parts: Iterable[str],
                  garments: Garments = DEFAULT_GARMENTS) -> str | None:
    """Why the colour parts `parts` do not match `garments`, or None.

    `parts` is any iterable of part names -- a colours dict is one.
    Three answers, each with its own message: an UNKNOWN part (not in
    model.PARTS), an UNUSED part (in model.PARTS, but not drawn by these
    garments), and a MISSING part. THE ONE RULE: the loader applies it to a
    character file and `recipes.build_recipe` to an Identity built in code,
    so a colour map that names paint nobody sees is refused on either route.
    """
    wanted = garment_parts(garments)
    outfit = garments_text(garments)
    unknown = sorted(set(parts) - set(PARTS))
    if unknown:
        return f"unknown part(s) {unknown}; the parts are {PARTS}"
    unused = sorted(set(parts) - set(wanted))
    if unused:
        return (f"unused part(s) {unused}; the garments ({outfit}) draw "
                f"{wanted}, and a colour for a part they do not draw is "
                f"paint nobody ever sees")
    missing = [part for part in wanted if part not in parts]
    if missing:
        return (f"missing part(s) {missing}; the garments ({outfit}) draw "
                f"{wanted}, and every one of those needs a colour")
    return None


def _tag_list(source: str, field: str, value: object,
              subject: str = DEFAULT_SUBJECT) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        raise _refused(source, field, f"must be a non-empty string of "
                                      f"comma-separated tags, got {value!r}")
    if not value.isascii():
        raise _refused(source, field, f"is not ASCII: {value!r}")
    pieces = value.split(",")
    if any(not piece.strip() for piece in pieces):
        raise _refused(source, field, f"has an empty tag (two commas, or a "
                                      f"comma at an end): {value!r}")
    for piece in pieces:
        problem = tag_problem(piece, subject)
        if problem is not None:
            raise _refused(source, field,
                           tag_refusal(piece, problem, subject))
    return [piece.strip() for piece in pieces]


def _subject(source: str, value: object) -> str:
    if not isinstance(value, str) or value not in SUBJECT_NAMES:
        raise _refused(source, "subject", f"{value!r} is not a subject; "
                       f"legal: {SUBJECT_NAMES} (a file that leaves the "
                       f"field out means {DEFAULT_SUBJECT!r})")
    return value


def _garments(source: str, value: object) -> Garments:
    slots = {slot.name: slot for slot in GARMENT_SLOTS}
    if not isinstance(value, dict):
        raise _refused(source, "garments", f"must be an object with the "
                       f"optional keys {tuple(slots)}, got "
                       f"{type(value).__name__}")
    unknown = sorted(set(value) - set(slots))
    if unknown:
        raise _refused(source, "garments", f"unknown garment(s) {unknown}; "
                       f"the garments are {tuple(slots)}")
    chosen = {}
    for name, slot in slots.items():
        if name not in value:
            chosen[name] = slot.default
            continue
        problem = garment_problem(slot, value[name])
        if problem is not None:
            raise _refused(source, f"garments.{name}", problem)
        chosen[name] = value[name]
    return Garments(**chosen)


def _colours(source: str, value: object,
             garments: Garments = DEFAULT_GARMENTS
             ) -> tuple[tuple[str, tuple[int, int, int]], ...]:
    wanted = garment_parts(garments)
    if not isinstance(value, dict):
        raise _refused(source, "colours", f"must be an object mapping every "
                       f"part of {wanted} to '#RRGGBB', got "
                       f"{type(value).__name__}")
    problem = parts_problem(value, garments)
    if problem is not None:
        raise _refused(source, "colours", problem)
    out: list[tuple[str, tuple[int, int, int]]] = []
    for part in wanted:
        field = f"colours.{part}"
        text = value[part]
        if not isinstance(text, str) or not HEX_RX.fullmatch(text):
            raise _refused(source, field, f"{text!r} is not a '#RRGGBB' hex "
                                          f"colour")
        rgb = (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
        for what, reserved in (("the grey key background", BACKGROUND_RGB),
                               ("the near-black outline", OUTLINE_RGB)):
            squared = distance_sq(rgb, reserved)
            if squared < MIN_KEY_DISTANCE ** 2:
                raise _refused(
                    source, field,
                    f"{text} is {squared ** 0.5:.1f} from {what} "
                    f"{_hex(reserved)}; every identity colour keeps a "
                    f"Euclidean RGB distance of at least {MIN_KEY_DISTANCE} "
                    f"from it")
        for factor, drawn in SHADES:
            shaded = shade(rgb, factor)
            squared = distance_sq(shaded, BACKGROUND_RGB)
            if squared < MIN_SHADE_KEY_DISTANCE ** 2:
                raise _refused(
                    source, field,
                    f"{text} is drawn at its x{factor:g} shade "
                    f"{_hex(shaded)} for {drawn}, {squared ** 0.5:.1f} from "
                    f"the background key {_hex(BACKGROUND_RGB)}; every "
                    f"shade the mannequin draws keeps a Euclidean RGB "
                    f"distance of at least {MIN_SHADE_KEY_DISTANCE} from it, "
                    f"or pixelize keys the figure's pixels out")
        out.append((part, rgb))
    return tuple(out)


def parse(raw: bytes, source: str) -> Identity:
    """The Identity a character file's bytes describe, by the module RULES;
    ValueError naming `source` and the field otherwise."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _refused(source, None, f"is not UTF-8 ({exc.reason} at byte "
                                     f"{exc.start})") from exc
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicates)
    except _DuplicateKey as exc:
        raise _refused(source, str(exc), "duplicate key: a key is written "
                                         "twice, and JSON keeps only the "
                                         "last") from exc
    except json.JSONDecodeError as exc:
        raise _refused(source, None, f"is not valid JSON: {exc.msg} at line "
                                     f"{exc.lineno} column {exc.colno}"
                       ) from exc
    if not isinstance(doc, dict):
        raise _refused(source, None, f"must be one JSON object with the "
                                     f"fields {REQUIRED_FIELDS}, got "
                                     f"{type(doc).__name__}")
    unknown = sorted(set(doc) - set(FIELDS))
    if unknown:
        raise _refused(source, unknown[0], f"unknown field(s) {unknown}; a "
                                           f"character file holds "
                                           f"{REQUIRED_FIELDS} and may hold "
                                           f"{OPTIONAL_FIELDS}")
    missing = [key for key in REQUIRED_FIELDS if key not in doc]
    if missing:
        raise _refused(source, missing[0], f"missing field(s) {missing}; a "
                                           f"character file holds "
                                           f"{REQUIRED_FIELDS} and may hold "
                                           f"{OPTIONAL_FIELDS}")
    subject = (DEFAULT_SUBJECT if "subject" not in doc
               else _subject(source, doc["subject"]))
    garments = (DEFAULT_GARMENTS if "garments" not in doc
                else _garments(source, doc["garments"]))
    tags = _tag_list(source, "tags", doc["tags"], subject)
    anchor = _tag_list(source, "anchor", doc["anchor"], subject)
    stray = [tag for tag in anchor if tag not in tags]
    if stray:
        raise _refused(source, "anchor", f"anchor tag(s) {stray} are not a "
                       f"tag of 'tags'; the anchor repeats tags verbatim and "
                       f"adds none")
    return Identity(tags=", ".join(tags), anchor=", ".join(anchor),
                    colours=_colours(source, doc["colours"], garments),
                    subject=subject, garments=garments)
