"""NovelAI's own request form, in NovelAI's order, with our pipeline's values in it.

OWNER: this pane owns the LAYOUT and the ARGV. It builds no request body,
opens no socket and reads no credential: what it produces is a
`widgets.NaiCommand` -- an argv for `python -m tools.nai` -- and
`run_pane.RunPane` is the only thing that runs one.

WHY IT LOOKS LIKE NOVELAI
-------------------------
The author asked for a standard layout for NovelAI's inputs. Someone who
uses NovelAI's own image generator must be able to read this pane without
learning our vocabulary first, so the field ORDER and the field NAMES are
theirs and only the VALUES are ours. `NAI_FIELDS` is that mapping, one row
per control, and it records for every row whether the label was confirmed
against docs.novelai.net or is our own guess -- see CONFIRMED / NOT
CONFIRMED at the bottom of this docstring.

Three groups of controls are OURS and are not NovelAI's at all: the recipe
and action strip at the top, the ledger context (round, phase, lever) and
the post-processing fields. They are laid out under their own headings,
which say so in the heading text, so a NovelAI reader can see where their
form ends and ours begins.

FOUR KINDS OF CONTROL, AND NOTHING IS HIDDEN
--------------------------------------------
    editable    the author sets it, and it reaches the argv
    capped      the author sets it, but only up to a free-tier limit, and
                the limit is shown beside it -- Steps, at 28
    derived     our recipe computes it, so it is shown READ-ONLY and
                labelled derived -- the captions and the centres
    locked      the free-tier guard forbids it, so it is shown GREYED with
                the reason as visible text (`widgets.LockedField`)

A locked control is never removed from the form. A reader has to be able to
SEE WHERE THE FREE TIER ENDS -- that 28 steps is a ceiling and not a
default, that V5 exists and is refused, that Number of Images is 1 because
a batch is charged -- and a control that is simply absent teaches none of
that. Every reason string is a sentence from `NAI_FIELDS`, and
`tools/check_nai_ui.py` compares the numbers in them against
`tools.nai.model` so a limit cannot be restated wrongly here.

The Image-to-Image group is the ONE thing hidden rather than locked, and
only while the action is `generate`: it is not a limit, it is a field that
does not exist for that action (`recipes._ACTION_KEYS`).

NOTHING FIRES ON A VALUE CHANGE
-------------------------------
Editing a field re-emits `command_changed` with a new `NaiCommand`, and
that is ALL it does: the pane updates a line of text. No command runs until
a human presses a button in `run_pane`, and a sending command needs an arm
step on top. There is no queue, no batch, no sweep, no timer and no retry
anywhere in this package (docs/NAI_SPRITES.md, "The loop": every generation
is one command a human typed).

WHAT THE ARGV SPELLS, AND WHAT IT LEAVES OUT
--------------------------------------------
A flag is written only when its value differs from the CLI's own default,
so the line stays the line a human would type -- `run walk --action
generate --character scout --seed 1234567`, not a line with eight
restatements of a default in it. TWO FLAGS ARE ALWAYS SPELLED: `--action`,
because the CLI requires it, and `--character`, because its default is a
PERSON'S NAME. A pasted command line that does not name the character means
somebody else the day the default moves, and every row of this window's
output is filed under that name (CLAUDE.md law 8). Every example in
`COMMAND_EXAMPLES` spells it for the same reason.

`probe` IS NOT COMPOSED HERE. The probe flag is spelled nowhere in this
package and the check asserts it. The probe row is a `LockedField` reading
that only the author runs it, by hand, in a terminal.

THE PROOF ROW IS NOT GUESSED HERE. `img2img` and `infill` need a confirmed
proof row (guard condition 1) that only the author's own probe can write.
This pane does NOT read `data/nai/proofs.json` to find out whether one
exists -- the guard runs in the child, and the readable answer is the
numbered verdict list a `plan` prints, which `run_pane` shows. So the
Anlas line names the risk in words and the Dry run button measures it;
`command()` never blocks a command on a file it did not read.

CONFIRMED against docs.novelai.net, 2026-09-17, read-only browsing, no
login, no form, no account touched:
    /en/image/undesiredcontent  "Undesired Content" is a tab of the same
                                input field as the Prompt, on the left of
                                the screen; its presets ("Heavy", "Light",
                                "Human Focus", "Furry Focus", "No Default
                                UC") sit at the bottom of the Prompt box
    /en/image/stepsguidance     the labels "Steps", "Prompt Guidance" and
                                "Prompt Guidance Rescale" (and "Decrisper",
                                which we do not send); and the free rule,
                                quoted: images generated with 28 or less
                                Steps cost no Anlas on Opus as long as the
                                resolution stays under the normal range and
                                they are not generated in batches
    /en/image/multiplecharacters  "The V4 and V4.5 models are limited to a
                                5x5 grid for custom character positioning";
                                the setting is changed from "AI's Choice"
                                to "Custom"; a "Character Positions" button
                                opens the canvas; each character prompt has
                                its own "Undesired Content" field
    /en/image/strengthnoise,
    /en/image/uploadimage       the labels "Strength" and "Noise", and that
                                they appear only when an image is used to
                                generate with
    /en/image/models            the model names, including NovelAI
                                Diffusion V4.5 Full / Curated and V5 Full /
                                Curated; the model selector sits DIRECTLY
                                ABOVE THE PROMPT BOX, not in the settings
                                column
    /en/image/sampling          "the Sampler setting", and the sampler
                                names (DPM++ 2M, Euler Ancestral, Euler,
                                DPM2, DPM++ 2S Ancestral, DPM++ SDE, DPM
                                Fast, DDIM)
    /en/image/                  "Number of Images" is a section of the
                                interface, and it sits BELOW the resolution
                                setting -- which is the one piece of the
                                settings column's order the docs state

NOT CONFIRMED -- our own spelling, marked `confirmed=False` in NAI_FIELDS:
    the exact label text of "Image Size" (the docs' own heading is "Image
    Resolution", said in this row's own caption) and "Noise Schedule"; the
    rest of the top-to-bottom ORDER of the settings column; the resolution
    preset names; and the wording of the Anlas cost line. The docs explain
    these settings without cataloguing the interface, and the generator
    itself is behind a login this pass did not touch.

THE FIVE CONTROLS THAT ARE LOCKED AND NOT MISSING. `qualityToggle`,
`dynamic_thresholding`, `skip_cfg_above_sigma` and `autoSmea` are fixed in
`request.FIXED_PARAMETERS`, and any reference or vibe key is refused by
guard condition 5. Every one now has a row -- "Add Quality Tags" at the
foot of the prompt box where /en/image/qualitytags puts it, "Vibe Transfer"
under it, and "Variety+", "Decrisper" and "SMEA" beside Prompt Guidance
Rescale. They were absent rather than locked, which is exactly the thing
this pane's docstring forbids, and one of them -- a vibe, at 2 Anlas on
every tier including Opus -- is a COST boundary a reader could not see.
`tools/check_nai_ui.py` now asserts that every key of FIXED_PARAMETERS is
either named by exactly one row here or listed there as not a control
NovelAI shows, so a new fixed parameter cannot go unlisted again.

AND THE WINDOW IS NARROWER THAN THE FORM. NovelAI's two columns sit side
by side only while there is room for both at their own minimum;
`_Columns` stacks them into one column below that, in the same order, so
the settings column and its lock reasons can never go behind a horizontal
scrollbar. MEASURED: at 1366x768 the two-column form clipped 296 px,
taking the whole sentence "Opus tier: 28 steps max" off the screen.
"""
from __future__ import annotations

import os
import secrets
import sys
from typing import NamedTuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                               QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from tools.nai import characters, mannequin, model, recipes
from tools.nai_ui import theme, widgets

# ---------------------------------------------------------------------------
# The mapping table: one row per control NovelAI shows
# ---------------------------------------------------------------------------

EDITABLE = "editable"
CAPPED = "capped"
DERIVED = "derived"
LOCKED = "locked"

COLUMN_WIDTH = 430
"""The width at which ONE of NovelAI's columns reads, in pixels.

MEASURED, by looking: below this a locked control's reason -- the sentence
saying what a generation costs -- is drawn narrower than its own text and
clipped. `_Columns` stacks the two columns below twice this, and each
column carries it as its own `setMinimumWidth`, so the number is written
once and both halves of the rule read it."""

LEFT = "left"
RIGHT = "right"
COST = "cost"


class NaiField(NamedTuple):
    """One control of NovelAI's form, and what this window puts in it.

    `label` is the text the row wears -- NovelAI's own wherever `confirmed`
    is True. `column` is LEFT, RIGHT or COST, and the tuple order inside a
    column IS the top-to-bottom order the pane lays out. `ours` says what
    our pipeline's value is and where it comes from. `state` is EDITABLE,
    CAPPED, DERIVED or LOCKED. `reason` is why it is locked, what caps it,
    or what derives it; it is "" for EDITABLE and non-empty for every
    other state. `flag` is the CLI option this row writes into the argv,
    or "" when the row reaches no flag -- only an EDITABLE or CAPPED row
    may have one.
    """

    label: str
    column: str
    ours: str
    state: str
    reason: str
    flag: str
    confirmed: bool


NAI_FIELDS: tuple[NaiField, ...] = (
    # -- left column ------------------------------------------------------
    # The model selector FIRST, because docs.novelai.net/en/image/models
    # puts it directly above the prompt box rather than in the settings
    # column. It used to sit at the head of the right column, which is the
    # one deviation the previous author recorded and did not act on.
    NaiField(
        "Model", LEFT,
        "NovelAI Diffusion V4.5 Full or Curated "
        "(nai-diffusion-4-5-full / -curated; infill uses their -inpainting "
        "twins)",
        EDITABLE, "", "--variant", True),
    NaiField(
        "Model: V5 Full / Curated", LEFT, "not offered",
        LOCKED, "V5 draws on the usage battery", "", True),
    NaiField(
        "Prompt", LEFT,
        "the recipe's base caption: the subject's count tag, the views and "
        "style tags, the character file's tags, the recipe sentence, and "
        "model.QUALITY_TAIL closing on rating:general",
        DERIVED, "recipes.build_recipe writes it; the outfit half comes "
                 "from the character file", "", True),
    NaiField(
        "Add Quality Tags", LEFT, "off",
        LOCKED, "qualityToggle is False in request.FIXED_PARAMETERS. "
                "NovelAI has this ON by default and appends its own words; "
                "ours are model.QUALITY_TAIL, written into the caption the "
                "ledger records, so a row says what was actually sent",
        "", True),
    NaiField(
        "Character Prompts", LEFT,
        "one per layout cell (5 for walk and jump, 6 for run): "
        "recipes.character_caption -- the subject noun, the anchor tags, "
        "from side, facing right, then the pose words",
        DERIVED, "the pose words are the recipe's; the anchor is the "
                 "character file's", "", True),
    NaiField(
        "Character Positions", LEFT,
        "each frame's centre, snapped to model.GRID "
        "(0.1, 0.3, 0.5, 0.7, 0.9)",
        DERIVED, "mannequin.render_init computes every centre from the "
                 "drawn bounding box; none is ever typed", "", True),
    NaiField(
        "AI's Choice / Custom", LEFT, "always Custom (use_coords is True in "
                                      "request.FIXED_PARAMETERS)",
        LOCKED, "the strip layout IS the centres; AI's Choice would let "
                "the model place the figures and there would be no cells",
        "", True),
    NaiField(
        "Undesired Content", LEFT, "model.NEGATIVE, one shared string",
        DERIVED, "the recipe writes it; a character file may not repeat "
                 "one of its tags", "", True),
    NaiField(
        "Undesired Content presets", LEFT,
        "none: ucPreset = model.UC_PRESET_NONE[model]",
        LOCKED, "a preset would add tags the ledger never records, so the "
                "caption in a row would not be what was sent", "", True),
    NaiField(
        "Vibe Transfer", LEFT, "none: no reference image, ever",
        LOCKED, "guard condition 5 refuses any reference or vibe key, and "
                "encoding an image into a vibe costs 2 Anlas ON EVERY "
                "TIER, Opus included -- this is a COST boundary, not a "
                "taste one", "", True),

    # -- right column -----------------------------------------------------
    NaiField(
        "Image Size", RIGHT,
        "1216 x 832 = 1,011,712 px, fixed by the recipe's layout "
        "(L5 for walk and jump, G6 for run)",
        LOCKED, "within NovelAI's Normal range, landscape: <= 1,048,576 px, "
                "and the cells are the frames. The docs head this section "
                "'Image Resolution'", "", False),
    NaiField(
        "Number of Images", RIGHT, "1",
        LOCKED, "one sample: n_samples is 1 in request.FIXED_PARAMETERS, "
                "and a batch costs Anlas on every tier", "", True),
    NaiField(
        "Steps", RIGHT, "23 by default (model.DEFAULT_STEPS)",
        CAPPED, "Opus tier: 28 steps max; on any other plan every "
                "generation costs Anlas", "--steps", True),
    NaiField(
        "Prompt Guidance", RIGHT, "5.0 by default (model.DEFAULT_SCALE)",
        EDITABLE, "", "--scale", True),
    NaiField(
        "Prompt Guidance Rescale", RIGHT, "0",
        LOCKED, "cfg_rescale is fixed at 0 in request.FIXED_PARAMETERS; "
                "there is no flag for it", "", True),
    NaiField(
        "Variety+", RIGHT, "off",
        LOCKED, "skip_cfg_above_sigma is None in request.FIXED_PARAMETERS; "
                "it changes the body the guard judged and there is no flag",
        "", True),
    NaiField(
        "Decrisper", RIGHT, "off",
        LOCKED, "dynamic_thresholding is False in request.FIXED_PARAMETERS; "
                "the pipeline sends one sampler configuration so two strips "
                "a week apart are comparable", "", True),
    NaiField(
        "SMEA", RIGHT, "off",
        LOCKED, "autoSmea is False in request.FIXED_PARAMETERS; V4.5 does "
                "not take it and request.build_body would not send it",
        "", True),
    NaiField(
        "Sampler", RIGHT, "Euler Ancestral (k_euler_ancestral)",
        LOCKED, "no --sampler flag: the CLI sends model.DEFAULT_SAMPLER",
        "", True),
    NaiField(
        "Noise Schedule", RIGHT, "karras",
        LOCKED, "no flag, and request.build_body refuses 'native' on "
                "V4/V4.5", "", False),
    NaiField(
        "Seed", RIGHT,
        "an int in [2, 4294967287]. LEFT EMPTY, THE DRY RUN AND THE SEND "
        "PICK DIFFERENT SEEDS: the CLI draws one from `secrets` in each "
        "child and prints it before sending, so the line the guard cleared "
        "and the line that runs are the same text and not the same "
        "request. Press Randomise to fix one",
        EDITABLE, "", "--seed", True),
    NaiField(
        "Image to Image: base image", RIGHT,
        "a layout-sized RGB or opaque RGBA PNG -- the consistency re-pass "
        "of an accepted strip; the mannequin init when left empty",
        EDITABLE, "", "--from", False),
    NaiField(
        "Image to Image: Strength", RIGHT,
        "0.45 by default, inside the author's band 0.35-0.55",
        EDITABLE, "", "--strength", True),
    NaiField(
        "Image to Image: Noise", RIGHT,
        "0.05 for img2img, 0.0 for infill; range 0.0-0.99",
        EDITABLE, "", "--noise", True),

    # -- cost -------------------------------------------------------------
    NaiField(
        "Anlas", COST,
        "0 expected for generate (V4.5, <= 28 steps, <= 1,048,576 px, one "
        "sample, Opus). UNPROVEN for img2img and infill (risks R1 and R2): "
        "the guard refuses both until the author's own probe writes a "
        "proof row, and this window never runs that probe",
        DERIVED, "the child process reads the real balance; this line is "
                 "the class, not a measurement", "", False),
)
"""Every control NovelAI's generator shows, in NovelAI's order, mapped onto
this pipeline. The pane lays out LEFT, then RIGHT, then COST, each in this
tuple's order. `tools/check_nai_ui.py` asserts every number spelled in a
`reason` agrees with `tools.nai.model`."""


# ---------------------------------------------------------------------------
# The command table: button -> argv, after `python -m tools.nai`
# ---------------------------------------------------------------------------

SENDING_SUBCOMMANDS: frozenset[str] = frozenset({"account", "run", "infill",
                                                 "probe"})
"""The subcommands that open a socket. `run`, `infill` and `probe` can
spend; `account` only reads the balance. A `NaiCommand` whose subcommand is
in this set has `sends` True, and `RunPane` will not start it unarmed."""

OFFERED_SUBCOMMANDS: tuple[str, ...] = ("render", "plan", "run", "infill",
                                        "account", "pixelize", "ledger")
"""What this window offers a button for. `probe` is deliberately absent: it
is the author's own decision, typed by hand in a terminal with the flag
spelled in full, and nothing in this package composes it."""

COMMAND_EXAMPLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("render",
     ("render", "walk", "--character", "scout")),
    ("plan.generate",
     ("plan", "walk", "--action", "generate", "--character", "scout",
      "--seed", "1234567", "--variant", "full", "--steps", "23",
      "--scale", "5.0")),
    ("plan.img2img",
     ("plan", "walk", "--action", "img2img", "--character", "scout",
      "--seed", "1234567", "--strength", "0.45", "--noise", "0.05")),
    ("run.generate",
     ("run", "walk", "--action", "generate", "--character", "scout",
      "--seed", "1234567", "--round", "1", "--lever", "seed")),
    ("run.img2img",
     ("run", "walk", "--action", "img2img", "--character", "scout",
      "--seed", "1234567", "--strength", "0.45", "--noise", "0.05",
      "--from", "data/nai/blobs/EXAMPLE.png", "--color-correct",
      "--round", "2", "--phase", "consistency", "--lever", "strength")),
    ("infill",
     ("infill", "walk", "--cell", "2", "--from", "data/nai/blobs/EXAMPLE.png",
      "--character", "scout", "--strength", "0.45", "--keep-cell")),
    ("account", ("account",)),
    ("pixelize",
     ("pixelize", "data/nai/blobs/EXAMPLE.png", "--recipe", "walk",
      "--character", "scout", "--colours", "16", "--remove-orphans")),
    ("ledger", ("ledger", "--last", "10")),
)
"""One complete example argv per button this window offers, WITHOUT the
interpreter and `-m tools.nai`.

This is the contract between this window and `tools/nai/cli.py`, and it is
the check's load-bearing assertion: `tools/check_nai_ui.py` feeds every one
of these to the LIVE `cli.build_parser()` and fails when one no longer
parses. A flag renamed in the CLI turns the suite red here instead of
turning a button into a usage error at the author's desk. Every option a
button can write appears in at least one example, so no flag is unwatched.
"""

EXAMPLE_FLAGS: frozenset[str] = frozenset(
    argument for _name, argv in COMMAND_EXAMPLES for argument in argv
    if argument.startswith("--"))
"""Every option `COMMAND_EXAMPLES` exercises against the live CLI parser.

`command()` refuses to compose an argv carrying anything else. The check
makes that assertion for the flags `NAI_FIELDS` declares; this one covers
the rest -- `--round`, `--phase`, `--lever`, `--cell`, `--keep-cell`,
`--color-correct`, `--colours`, `--remove-orphans`, `--last` -- which are
this pipeline's own fields and have no NovelAI row to hang off. Without it
a control could write a flag that nothing ever parsed, which is the shape
CLAUDE.md's ACTIVE WARNINGS call the sibling route: the watched half of a
rule and the unwatched half.
"""


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
"""The checkout this window composes commands for; every `NaiCommand.cwd`."""

_NOT_A_FLAG = ("--out", "--palette", "--ledger-id", "--strip-version")
"""The CLI options this pane deliberately offers NO control for. `--out`
and `--ledger-id` would let the window choose where the child writes, which
is the child's decision; `--palette` and `--strip-version` belong to a
post-processing pass the author drives by hand. Listed so the omission is a
decision a reader can see rather than a gap."""

_ANLAS_FREE = ("0 expected: V4.5 full or curated, {steps} steps (<= {max}), "
               "{w}x{h} px (<= {area:,}), one sample, Opus tier")
"""The cost line for `generate` -- the CLASS of the request, not a
measurement. Only the child reads the real balance."""

_ANLAS_UNPROVEN = ("UNPROVEN for {action} (risk R1/R2): the guard refuses "
                   "it until a proof row exists, and only a probe the "
                   "author ran by hand can write one. Press Dry run to read "
                   "the guard's own verdict.")
"""The cost line for `img2img` and `infill`, which no measurement in this
repository has yet shown to be free."""


class _Columns(QWidget):
    """NovelAI's two columns side by side, or stacked when there is no room.

    A QHBoxLayout pinned the two columns beside each other at every width,
    so below the sum of their two minimums the form went behind a
    HORIZONTAL SCROLLBAR and the settings column -- with the sentence
    saying what a generation costs -- was simply off the right-hand edge.
    Measured: at 1366 px of window the request form clipped 296 px, and no
    splitter position could recover it, because the clipping was inside the
    form rather than between the panes.

    So the two children are placed in a QGridLayout and MOVED between one
    row of two columns and two rows of one, on `resizeEvent`. NovelAI's
    order is the same either way -- left column, then settings -- so the
    narrow form is the wide one read top to bottom.

    The threshold is `COLUMN_WIDTH` twice, plus the spacing -- a STATED
    width at which a column reads, not a measured "how small can this be
    squeezed". Every caption in this form is `QSizePolicy.Ignored` across
    (see `fix_wrapped_labels`), so a column's own `minimumSizeHint` is the
    width of its group-box title and nothing more: measured, 233 px for a
    column whose text needs 430. A threshold read off that is a threshold
    that never fires, and the form sat in two silently clipped columns.

    LAW 12: nothing here is ever `setParent(None)`. `QGridLayout.addWidget`
    re-parents in place, and neither child is ever removed from this
    widget, only from a cell.
    """

    def __init__(self, left, right, parent=None) -> None:
        """Hold `left` and `right`, side by side to begin with."""
        super().__init__(parent)
        self._left = left
        self._right = right
        self._side_by_side = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        margins = self._grid.contentsMargins()
        self._threshold = (2 * COLUMN_WIDTH + self._grid.horizontalSpacing()
                           + margins.left() + margins.right())
        self._place(True)

    def side_by_side(self) -> bool:
        """True while the two columns sit beside each other."""
        return bool(self._side_by_side)

    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt's own spelling)
        """Never wider than the STACKED arrangement needs.

        THE CHICKEN AND EGG THIS BREAKS. A `QScrollArea` with
        `widgetResizable` lays its body out at the larger of the viewport
        and the body's own minimum. While the columns sat side by side that
        minimum was the sum of both, so a narrow viewport got a HORIZONTAL
        SCROLLBAR instead of a narrower body -- and this widget, never
        being given a narrow width, never stacked. Measured: at 1366 px the
        form still sat in two clipped columns behind a scrollbar, which is
        the exact defect the stacking was written to remove.

        So the minimum width reported is always the one column's, whatever
        arrangement is current. The scroll area then really does narrow the
        body, `resizeEvent` sees the narrow width, and the columns stack.
        The height is left to the layout, because that is the arrangement
        the widget is actually in.
        """
        hint = super().minimumSizeHint()
        margins = self._grid.contentsMargins()
        narrow = COLUMN_WIDTH + margins.left() + margins.right()
        return QSize(min(hint.width(), narrow), hint.height())

    def threshold(self) -> int:
        """The width at or above which the columns sit side by side.

        `COLUMN_WIDTH` twice plus the spacing, fixed at construction. It
        does not move, so dragging the splitter across it cannot make the
        arrangement flap.
        """
        return self._threshold

    def _place(self, side_by_side: bool) -> None:
        """Move the two children into one row of two, or two rows of one."""
        if side_by_side == self._side_by_side:
            return
        self._side_by_side = side_by_side
        grid = self._grid
        grid.removeWidget(self._left)
        grid.removeWidget(self._right)
        if side_by_side:
            grid.addWidget(self._left, 0, 0)
            grid.addWidget(self._right, 0, 1)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
        else:
            grid.addWidget(self._left, 0, 0)
            grid.addWidget(self._right, 1, 0)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 0)
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        """Stack or unstack for the width just given. Runs no command."""
        super().resizeEvent(event)
        self._place(self.width() >= self._threshold)


def fix_wrapped_labels(root) -> None:
    """Let every word-wrapped QLabel under `root` claim the height it needs.

    A `QLabel` with `setWordWrap(True)` can compute `heightForWidth`, but
    its size policy does not ADVERTISE that, so `QFormLayout` and
    `QBoxLayout` lay the row out at one line's height and the second line
    draws over the row below. Measured here: the `Image Size`, `Sampler`
    and `Noise Schedule` rows overprinted their captions, which is exactly
    the reason text a locked control exists to show.

    So every caption this window builds -- `widgets.field_row`'s, a
    `widgets.LockedField`'s reason, the arm banner in `run_pane` -- is
    fixed in ONE pass, over the finished tree, rather than at each of the
    twenty places a label is made. It belongs in `widgets.py` beside
    `field_row`, whose captions it repairs; that file is another module's
    this pass, and contract_issues.md records the move.

    AND IT MAKES THE FORM NARROW-SAFE, in the same pass and for the same
    reason. A wrapped label still ADVERTISES the width of its longest line
    as a minimum, so a layout holding twenty captions asks for a window
    nobody has: measured, this pane's body demanded 973 px and the whole
    window 1367x838, which does not fit a 1366x768 laptop in either
    dimension. A wrapped label is given `QSizePolicy.Ignored` across --
    it can compute its height for ANY width, so its own width preference
    is noise -- and every `QFormLayout` is set to `WrapLongRows`, which
    puts a long caption above its control instead of beside it. Nothing is
    clipped and nothing is hidden; the form just gets taller, and the
    scroll area's always-on vertical bar was already paid for.
    """
    for label in root.findChildren(QLabel):
        if not label.wordWrap():
            continue
        policy = label.sizePolicy()
        policy.setHeightForWidth(True)
        # Everything EXCEPT a locked control's value: see
        # `widgets.VALUE_KEEPS_ITS_WIDTH`. A caption may give way; the
        # value the row exists to show may not.
        if not label.property(widgets.VALUE_KEEPS_ITS_WIDTH):
            policy.setHorizontalPolicy(QSizePolicy.Ignored)
        label.setSizePolicy(policy)
    for form in root.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)


class RequestPane(QWidget):
    """NovelAI's form, laid out from `NAI_FIELDS`.

    Signals:
        command_changed(object)     a `widgets.NaiCommand`, after any edit.
                                    It updates a line of text and NOTHING
                                    else: nothing runs, nothing is sent.
        plan_requested()            "show me what plan says": the window
                                    turns it into the `plan` command for
                                    the current form.
    """

    command_changed = Signal(object)
    plan_requested = Signal()

    def __init__(self, parent=None) -> None:
        """Build both columns and the cost line from `NAI_FIELDS`.

        Every row is built by `widgets.field_row`; a LOCKED row is a
        `widgets.LockedField` carrying its `reason`; a DERIVED row is
        read-only and captioned with `reason`. The pane starts on `walk`,
        `generate`, `characters.DEFAULT_CHARACTER`, with the defaults from
        `tools.nai.model`.

        RuntimeError when a `NAI_FIELDS` row is EDITABLE with a non-empty
        `reason`, or CAPPED, LOCKED or DERIVED with an empty one -- law 7:
        a table that cannot be laid out is not laid out approximately.
        """
        super().__init__(parent)
        for row in NAI_FIELDS:
            if row.state == EDITABLE and row.reason:
                raise RuntimeError(
                    f"NAI_FIELDS row {row.label!r} is editable and carries "
                    f"the reason {row.reason!r}: a control that looks "
                    f"locked and is not teaches the reader the wrong thing")
            if row.state != EDITABLE and not row.reason.strip():
                raise RuntimeError(
                    f"NAI_FIELDS row {row.label!r} is {row.state} with no "
                    f"reason; a reader must be able to see WHY, or a lock "
                    f"is indistinguishable from a bug")

        self._recipe = recipes.RECIPE_NAMES[0]
        self._action = model.ACTIONS[0]
        self._character = characters.DEFAULT_CHARACTER
        self._character_problem = ""
        self._derived_problem = ""
        self._layout_name = ""
        self._frame_count = 0
        self._quiet = True          # no signal while __init__ builds rows

        self._rows = {row.label: row for row in NAI_FIELDS}
        self._build()
        self._quiet = False
        self._refresh_derived()
        self._apply_action()
        self._emit()

    # -- construction ------------------------------------------------------

    def _row(self, label: str) -> NaiField:
        """The `NAI_FIELDS` row called `label`; KeyError naming it if absent.

        Every widget this pane builds asks for its row by NovelAI's own
        label, so a row deleted from the table takes its control with it
        instead of leaving a control with a hand-typed caption behind.
        """
        if label not in self._rows:
            raise KeyError(f"NAI_FIELDS has no row labelled {label!r}")
        return self._rows[label]

    def _locked(self, form, label: str, value: str):
        """Add row `label` as a `widgets.LockedField` showing `value`.

        The caption under the control is `row.ours` -- UNLESS that is the
        same sentence the chip above it already shows, in which case there
        is no caption at all. Nine rows read "1" beside "one sample" and
        then "1" again underneath, which looks like a rendering fault and
        costs a line of height on every one of them.
        """
        row = self._row(label)
        field = widgets.LockedField(row.label, value, row.reason)
        same = " ".join(row.ours.split()) == " ".join(str(value).split())
        return widgets.field_row(form, row.label, field,
                                 "" if same else row.ours)

    def _derived_box(self, form, label: str, height: int):
        """Add row `label` as a read-only text box `height` pixels tall."""
        row = self._row(label)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setFixedHeight(height)
        box.setStyleSheet(theme.MONO_STYLE)
        widgets.field_row(form, f"{row.label}  (derived)", box, row.reason)
        return box

    def _heading(self, text: str) -> QLabel:
        """A section heading in the editor's own idiom."""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(theme.HEADING_STYLE)
        return label

    def _caption(self, text: str) -> QLabel:
        """A muted caption line, wrapped, in the editor's own idiom."""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(theme.CAPTION_STYLE)
        return label

    def _build(self) -> None:
        """Lay the whole pane out: our strip, NovelAI's two columns, cost."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # ALWAYS ON, not as needed. A word-wrapped caption's height is
        # computed for the width it has; a vertical scrollbar that appears
        # afterwards takes that width away, the caption wraps to a second
        # line the row was never given room for, and it draws over the row
        # below -- which is where the free-tier reasons live. A scrollbar
        # that is always there cannot change the width it was measured at.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)

        stack = QVBoxLayout(body)
        stack.addWidget(self._build_ours())
        # A `_Columns` and NOT a QSplitter. A splitter hands its children
        # its own height and squeezes them past their minimum when it is
        # short, and what gets squeezed here is the caption under a locked
        # control -- the sentence saying what a generation costs. A layout
        # inside the scroll area grows the body instead and lets the
        # vertical scrollbar do the work; `_Columns` then STACKS the two
        # columns rather than letting them go behind a horizontal one.
        self._columns = _Columns(self._build_left(), self._build_right())
        stack.addWidget(self._columns)
        stack.addWidget(self._build_cost())
        fix_wrapped_labels(self)
        self._connect()

    def _connect(self) -> None:
        """Wire every control to `_edited`, once the whole form exists.

        Nothing is connected while the rows are being built. A combo box
        emits `currentTextChanged` from `addItems`, and a handler that ran
        then would read a widget the next line had not created yet -- the
        crash is at construction, where it is loud, but the fix is to have
        ONE place that says when this pane starts listening.

        Every connection here ends in `command_changed`: a new line of
        text. None of them runs anything, and none of them is a timer.
        """
        self._action_combo.currentTextChanged.connect(self._action_picked)
        self._recipe_combo.currentTextChanged.connect(self._recipe_picked)
        self._seed_button.clicked.connect(self._randomise_clicked)
        self._source_button.clicked.connect(self._browse_source)
        self._strip_button.clicked.connect(self._browse_strip)
        self._variant_combo.currentIndexChanged.connect(self._variant_picked)
        for spin in (self._steps_spin, self._scale_spin, self._strength_spin,
                     self._noise_spin, self._cell_spin, self._round_spin,
                     self._colours_spin, self._last_spin):
            spin.valueChanged.connect(self._edited)
        for edit in (self._seed_edit, self._source_edit, self._phase_edit,
                     self._lever_edit, self._strip_edit):
            edit.textChanged.connect(self._edited)
        for box in (self._full_repaint, self._colour_correct,
                    self._keep_cell, self._remove_orphans):
            box.toggled.connect(self._edited)

    def _build_ours(self) -> QWidget:
        """The strip NovelAI has no equivalent for: action, recipe, character."""
        box = QGroupBox("Ours, not NovelAI's")
        form = QFormLayout(box)

        self._action_combo = QComboBox()
        self._action_combo.addItems(list(model.ACTIONS))
        widgets.field_row(
            form, "Action", self._action_combo,
            "generate sends no image; img2img re-passes one; infill repaints "
            "ONE cell and is its own subcommand, with no dry run")

        self._recipe_combo = QComboBox()
        self._recipe_combo.addItems(list(recipes.RECIPE_NAMES))
        widgets.field_row(
            form, "Recipe", self._recipe_combo,
            "the strip: walk and jump are 5 cells (L5), run is 6 (G6). It "
            "is the positional argument of every command below")

        self._character_label = QLineEdit(self._character)
        self._character_label.setReadOnly(True)
        widgets.field_row(
            form, "Character", self._character_label,
            "chosen in the character pane; always spelled into --character, "
            "because the CLI's default is a person's name")

        self._character_problem_label = QLabel("")
        self._character_problem_label.setWordWrap(True)
        self._character_problem_label.setStyleSheet(theme.PROBLEM_STYLE)
        self._character_problem_label.hide()
        form.addRow(self._character_problem_label)
        return box

    def _build_left(self) -> QWidget:
        """NovelAI's left-hand side: Prompt, Character Prompts, Undesired."""
        box = QGroupBox("Prompt  (NovelAI's left column)")
        box.setMinimumWidth(COLUMN_WIDTH)
        column = QVBoxLayout(box)
        form = QFormLayout()
        column.addLayout(form)

        # docs.novelai.net/en/image/models puts the model selector DIRECTLY
        # ABOVE THE PROMPT BOX. It used to head the settings column, which
        # was the one deviation the docstring recorded and nobody acted on.
        variant = self._row("Model")
        self._variant_combo = QComboBox()
        self._variant_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._variant_combo.setMinimumContentsLength(10)
        for name in model.VARIANTS:
            self._variant_combo.addItem(
                f"NovelAI Diffusion V4.5 {name.capitalize()}", name)
        widgets.field_row(form, variant.label, self._variant_combo,
                          variant.ours)
        self._model_id_label = self._caption("")
        form.addRow("", self._model_id_label)
        self._locked(form, "Model: V5 Full / Curated", "not offered")

        self._prompt_box = self._derived_box(form, "Prompt", 120)
        # The foot of the prompt box: docs.novelai.net/en/image/qualitytags
        # says the toggle "is enabled by default, but you can find it on
        # the bottom of the Prompt box". Ours is the opposite of NovelAI's
        # default, which is the strongest reason of all to show it.
        self._locked(form, "Add Quality Tags", "off")

        prompts = self._row("Character Prompts")
        positions = self._row("Character Positions")
        column.addWidget(self._heading(
            f"{prompts.label}  (derived)"))
        column.addWidget(self._caption(
            f"{prompts.reason}. Each row carries NovelAI's 5x5 position "
            f"picker: {positions.reason}"))
        self._frame_rows = []
        for index in range(model.MAX_FRAMES):
            row_widget, caption_field, grid = self._build_frame_row(index)
            column.addWidget(row_widget)
            self._frame_rows.append((row_widget, caption_field, grid))

        tail = QFormLayout()
        column.addLayout(tail)
        self._positions_field = QLineEdit()
        self._positions_field.setReadOnly(True)
        widgets.field_row(tail, f"{positions.label}  (derived)",
                          self._positions_field, positions.ours)
        self._locked(tail, "AI's Choice / Custom", "Custom")
        self._negative_box = self._derived_box(tail, "Undesired Content", 90)
        self._locked(tail, "Undesired Content presets",
                     "none (ucPreset = UC_PRESET_NONE)")
        self._locked(tail, "Vibe Transfer", "none")
        return box

    def _build_frame_row(self, index: int):
        """One character prompt: its index, its caption, its 5x5 picker."""
        row_widget = QWidget()
        line = QHBoxLayout(row_widget)
        line.setContentsMargins(0, 0, 0, 0)
        number = QLabel(f"{index}")
        number.setFixedWidth(16)
        number.setStyleSheet(theme.CAPTION_STYLE)
        # A WRAPPING box, not a QLineEdit. This is the text that is
        # actually sent for this frame, and in a one-line field it was
        # clipped mid-word at every window width with no tooltip and no way
        # at all to read the rest of it -- the one derived value on the
        # form a reader could not check against the ledger. Its siblings
        # above and below (Prompt, Undesired Content) are already wrapping
        # boxes; this is the route the rule was not applied to.
        caption = QPlainTextEdit()
        caption.setReadOnly(True)
        caption.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        caption.setStyleSheet(theme.MONO_STYLE)
        caption.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        caption.setMinimumWidth(80)
        caption.setFixedHeight(58)
        caption.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        grid = widgets.PositionGrid(model.GRID[0], model.GRID[2])
        line.addWidget(number)
        line.addWidget(caption, 1)
        line.addWidget(grid)
        return row_widget, caption, grid

    def _build_right(self) -> QWidget:
        """NovelAI's settings column, in NovelAI's order, plus ours below it."""
        box = QGroupBox("Settings  (NovelAI's right column)")
        # COLUMN_WIDTH, not the 520 this used to pin. At 520 plus the left
        # column plus the run pane the window did not fit a 1366x768 laptop
        # in either dimension. The captions wrap, so the column reads at
        # 430; what it must never do is clip.
        box.setMinimumWidth(COLUMN_WIDTH)
        column = QVBoxLayout(box)
        form = QFormLayout()
        column.addLayout(form)

        self._size_field = self._locked(form, "Image Size", "")
        self._locked(form, "Number of Images", str(model.N_SAMPLES))

        steps = self._row("Steps")
        self._steps_spin = QSpinBox()
        self._steps_spin.setRange(1, model.MAX_STEPS)
        self._steps_spin.setValue(model.DEFAULT_STEPS)
        widgets.field_row(form, steps.label, self._steps_spin,
                          f"{steps.reason} -- the spinner stops there; "
                          f"{steps.ours}")

        scale = self._row("Prompt Guidance")
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.1, 10.0)
        self._scale_spin.setSingleStep(0.5)
        self._scale_spin.setDecimals(1)
        self._scale_spin.setValue(float(model.DEFAULT_SCALE))
        widgets.field_row(form, scale.label, self._scale_spin, scale.ours)

        self._locked(form, "Prompt Guidance Rescale", "0")
        self._locked(form, "Variety+", "off")
        self._locked(form, "Decrisper", "off")
        self._locked(form, "SMEA", "off")
        self._locked(form, "Sampler", "Euler Ancestral "
                                      f"({model.DEFAULT_SAMPLER})")
        self._locked(form, "Noise Schedule", model.DEFAULT_NOISE_SCHEDULE)

        seed = self._row("Seed")
        seed_widget = QWidget()
        seed_line = QHBoxLayout(seed_widget)
        seed_line.setContentsMargins(0, 0, 0, 0)
        self._seed_edit = QLineEdit()
        self._seed_edit.setPlaceholderText("empty: the CLI picks one")
        self._seed_button = QPushButton("Randomise")
        seed_line.addWidget(self._seed_edit, 1)
        seed_line.addWidget(self._seed_button)
        widgets.field_row(form, seed.label, seed_widget, seed.ours)

        column.addWidget(self._build_i2i())
        column.addWidget(self._build_ledger())
        column.addWidget(self._build_post())
        return box

    def _build_i2i(self) -> QWidget:
        """NovelAI's Image-to-Image group: base image, Strength, Noise."""
        box = QGroupBox("Image to Image")
        form = QFormLayout(box)

        source = self._row("Image to Image: base image")
        source_widget = QWidget()
        source_line = QHBoxLayout(source_widget)
        source_line.setContentsMargins(0, 0, 0, 0)
        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText(
            "empty: the mannequin init (img2img only)")
        self._source_button = QPushButton("Browse...")
        source_line.addWidget(self._source_edit, 1)
        source_line.addWidget(self._source_button)
        widgets.field_row(form, source.label, source_widget, source.ours)

        strength = self._row("Image to Image: Strength")
        self._strength_spin = QDoubleSpinBox()
        self._strength_spin.setRange(*model.STRENGTH_BAND)
        self._strength_spin.setSingleStep(0.01)
        self._strength_spin.setDecimals(2)
        self._strength_spin.setValue(model.DEFAULT_STRENGTH)
        widgets.field_row(form, strength.label, self._strength_spin,
                          f"{strength.ours} -- the spinner is the band: "
                          f"recipes.make_request refuses anything outside it")

        self._full_repaint = QCheckBox("full repaint")
        widgets.field_row(
            form, "", self._full_repaint,
            f"strength {model.INFILL_FULL_REPAINT} instead of the band")

        noise = self._row("Image to Image: Noise")
        self._noise_spin = QDoubleSpinBox()
        self._noise_spin.setRange(*model.NOISE_RANGE)
        self._noise_spin.setSingleStep(0.01)
        self._noise_spin.setDecimals(2)
        self._noise_spin.setValue(model.DEFAULT_IMG2IMG_NOISE)
        widgets.field_row(form, noise.label, self._noise_spin, noise.ours)

        self._colour_correct = QCheckBox("color_correct")
        widgets.field_row(form, "", self._colour_correct, "lever L11")

        self._cell_spin = QSpinBox()
        self._cell_spin.setRange(0, model.MAX_FRAMES - 1)
        self._cell_row = widgets.field_row(
            form, "Cell to repaint  (ours)", self._cell_spin,
            "infill only: the 0-based index of the ONE cell this repaints")

        self._keep_cell = QCheckBox("--keep-cell")
        widgets.field_row(form, "", self._keep_cell,
                          "do not paste the mannequin in first")

        self._i2i_group = box
        return box

    def _build_ledger(self) -> QWidget:
        """The ledger context: round, phase, lever. Ours, not NovelAI's."""
        box = QGroupBox("Ledger context  (ours)")
        column = QVBoxLayout(box)
        column.addWidget(self._caption(
            "Written into the ledger row, not into the request body: a dry "
            "run cleared with one round still clears the send that records "
            "another."))
        form = QFormLayout()
        column.addLayout(form)
        self._round_spin = QSpinBox()
        self._round_spin.setRange(0, 999)
        self._round_spin.setSpecialValueText("(not recorded)")
        widgets.field_row(form, "Round", self._round_spin,
                          "--round: which turn of the loop this is; 0 means "
                          "the flag is left out")
        self._phase_edit = QLineEdit()
        widgets.field_row(form, "Phase", self._phase_edit,
                          "--phase: the stage this belongs to, free text")
        self._lever_edit = QLineEdit()
        widgets.field_row(form, "Lever", self._lever_edit,
                          "--lever: the ONE thing this round changes. A "
                          "round that changes two levers measures neither")
        # The slack goes to the BOTTOM, not into the caption: a QVBoxLayout
        # with nothing expanding hands its spare height to the first thing
        # that will take it, and a caption drawn in the middle of 90 px of
        # nothing reads as a rendering fault.
        column.addStretch(1)
        return box

    def _build_post(self) -> QWidget:
        """Post-processing: the strip to pixelize, its colours, the tail."""
        box = QGroupBox("Post-processing  (ours)")
        column = QVBoxLayout(box)
        column.addWidget(self._caption(
            "Runs on a PNG that is already on disk. No network, no spend."))
        form = QFormLayout()
        column.addLayout(form)
        strip_widget = QWidget()
        strip_line = QHBoxLayout(strip_widget)
        strip_line.setContentsMargins(0, 0, 0, 0)
        self._strip_edit = QLineEdit()
        self._strip_edit.setPlaceholderText(
            "the PNG a run returned; pixelize's positional argument")
        self._strip_button = QPushButton("Browse...")
        strip_line.addWidget(self._strip_edit, 1)
        strip_line.addWidget(self._strip_button)
        widgets.field_row(form, "Strip PNG", strip_widget,
                          "pixelize reads this file. A run prints the path "
                          "it wrote on its `output` line; Browse... picks "
                          "it without retyping")
        self._colours_spin = QSpinBox()
        self._colours_spin.setRange(2, 256)
        self._colours_spin.setValue(model.DEFAULT_COLOURS)
        widgets.field_row(form, "Colours", self._colours_spin,
                          f"--colours, {model.DEFAULT_COLOURS} by default")
        self._remove_orphans = QCheckBox("--remove-orphans")
        widgets.field_row(form, "", self._remove_orphans, "lever P8")
        self._last_spin = QSpinBox()
        self._last_spin.setRange(1, 500)
        self._last_spin.setValue(10)
        widgets.field_row(form, "Ledger rows", self._last_spin,
                          "--last: how many rows the ledger button prints")
        column.addStretch(1)
        return box

    def _build_cost(self) -> QWidget:
        """NovelAI puts its Anlas figure at the bottom. So do we."""
        row = self._row("Anlas")
        box = QGroupBox(f"{row.label}  (derived)")
        column = QVBoxLayout(box)
        self._cost_label = QLabel("")
        self._cost_label.setWordWrap(True)
        self._cost_label.setStyleSheet(theme.BANNER_STYLE)
        column.addWidget(self._cost_label)
        column.addWidget(self._caption(row.reason))
        return box

    # -- the one thing the rest of the window asks for ---------------------

    def command(self, subcommand: str) -> object:
        """THE COMMAND LINE AS IT STANDS, as a `widgets.NaiCommand`.

        `subcommand` is one of `OFFERED_SUBCOMMANDS`. The argv is built
        from the form exactly as `COMMAND_EXAMPLES` shows for that button:
        the interpreter (`sys.executable`), `-m`, `tools.nai`, the
        subcommand, its positional, then one option per EDITABLE or
        CAPPED row whose
        value differs from the CLI's own default -- a default is never
        spelled out, so the line stays the line a human would type.
        `--action` and `--character` are the two exceptions, always
        spelled; the module docstring says why.

        `sends` is `subcommand in SENDING_SUBCOMMANDS`. `blocked` is the
        first reason this cannot run: the character file is refused, a
        `--from` path does not exist, `--cell` is outside the layout, or
        the subcommand cannot express the chosen action. It is a string
        to show, never a silent disable.

        ValueError for a subcommand outside `OFFERED_SUBCOMMANDS`. In
        particular `probe` raises: this window does not compose it.
        """
        if subcommand not in OFFERED_SUBCOMMANDS:
            raise ValueError(
                f"this window composes {list(OFFERED_SUBCOMMANDS)}, not "
                f"{subcommand!r}; the cost probe is the author's own "
                f"decision and is typed by hand in a terminal")
        argv = [sys.executable, "-m", "tools.nai"]
        argv.extend(self._tail(subcommand))
        for token in argv:
            if token.startswith("--") and token not in EXAMPLE_FLAGS:
                raise RuntimeError(
                    f"this pane composed {token}, which no row of "
                    f"COMMAND_EXAMPLES carries: add an example argv in the "
                    f"same change as the control that writes a flag, or "
                    f"nothing ever parses it against the live CLI")
            if token == "":
                raise RuntimeError(
                    f"the {subcommand} line carries an empty argument; a "
                    f"field left blank leaves its flag OUT, it does not "
                    f"pass nothing to it")
        return widgets.NaiCommand(argv=tuple(argv),
                                  sends=subcommand in SENDING_SUBCOMMANDS,
                                  blocked=self._blocked(subcommand),
                                  cwd=REPO_ROOT)

    def _tail(self, subcommand: str) -> list[str]:
        """The argv after `-m tools.nai`, for one subcommand.

        One branch per member of `OFFERED_SUBCOMMANDS` and a raise at the
        end, so a subcommand added to the tuple and not to this function
        cannot compose a half-built line (law 7).
        """
        character = ["--character", self._character]
        if subcommand == "render":
            return ["render", self._recipe] + character
        if subcommand in ("plan", "run"):
            tail = [subcommand, self._recipe, "--action", self._action]
            tail += character + self._generation_options()
            if subcommand == "run":
                tail += self._ledger_options()
            return tail
        if subcommand == "infill":
            tail = ["infill", self._recipe,
                    "--cell", str(self._cell_spin.value())]
            tail += character
            source = self._source_edit.text().strip()
            if source:
                tail += ["--from", source]
            tail += self._strength_option()
            tail += self._noise_option()
            tail += self._variant_option()
            tail += self._seed_option()
            if self._keep_cell.isChecked():
                tail.append("--keep-cell")
            return tail + self._ledger_options()
        if subcommand == "account":
            return ["account"]
        if subcommand == "pixelize":
            strip = self._strip_edit.text().strip()
            tail = (["pixelize"] + ([strip] if strip else [])
                    + ["--recipe", self._recipe] + character)
            if self._colours_spin.value() != model.DEFAULT_COLOURS:
                tail += ["--colours", str(self._colours_spin.value())]
            if self._remove_orphans.isChecked():
                tail.append("--remove-orphans")
            return tail
        if subcommand == "ledger":
            if self._last_spin.value() == 10:
                return ["ledger"]
            return ["ledger", "--last", str(self._last_spin.value())]
        raise RuntimeError(
            f"{subcommand!r} is offered and has no argv here; add its line "
            f"to _tail and its example to COMMAND_EXAMPLES in one change")

    def _generation_options(self) -> list[str]:
        """The options `plan` and `run` share, defaults left unspelled."""
        options = self._seed_option() + self._variant_option()
        if self._steps_spin.value() != model.DEFAULT_STEPS:
            options += ["--steps", str(self._steps_spin.value())]
        if self._scale_spin.value() != float(model.DEFAULT_SCALE):
            options += ["--scale", f"{self._scale_spin.value():g}"]
        if self._action == "img2img":
            options += self._strength_option() + self._noise_option()
            source = self._source_edit.text().strip()
            if source:
                options += ["--from", source]
            if self._colour_correct.isChecked():
                options.append("--color-correct")
        return options

    def _seed_option(self) -> list[str]:
        """`--seed N`, or nothing when the field is empty."""
        seed = self._seed_edit.text().strip()
        return ["--seed", seed] if seed else []

    def _variant_option(self) -> list[str]:
        """`--variant curated`, or nothing: `full` is the CLI's default."""
        variant = self._variant_combo.currentData()
        return [] if variant == model.VARIANTS[0] else ["--variant", variant]

    def _strength_option(self) -> list[str]:
        """`--strength`, or nothing when it equals this action's default.

        img2img and infill share this one function on purpose: they take
        the same flag with two different defaults and two different legal
        sets, and a second copy would be the sibling route that drifts.
        """
        if self._action == "infill" and self._full_repaint.isChecked():
            return ["--strength", f"{model.INFILL_FULL_REPAINT:g}"]
        default = (model.DEFAULT_INPAINT_STRENGTH if self._action == "infill"
                   else model.DEFAULT_STRENGTH)
        value = self._strength_spin.value()
        return [] if value == default else ["--strength", f"{value:g}"]

    def _noise_option(self) -> list[str]:
        """`--noise`, or nothing when it equals this action's default."""
        default = (model.DEFAULT_INFILL_NOISE if self._action == "infill"
                   else model.DEFAULT_IMG2IMG_NOISE)
        value = self._noise_spin.value()
        return [] if value == default else ["--noise", f"{value:g}"]

    def _ledger_options(self) -> list[str]:
        """`--round`, `--phase`, `--lever`, each only when it was filled in."""
        options: list[str] = []
        if self._round_spin.value() > 0:
            options += ["--round", str(self._round_spin.value())]
        phase = self._phase_edit.text().strip()
        if phase:
            options += ["--phase", phase]
        lever = self._lever_edit.text().strip()
        if lever:
            options += ["--lever", lever]
        return options

    def _blocked(self, subcommand: str) -> str:
        """The FIRST reason `subcommand` cannot run as the form stands, or "".

        Every offered subcommand gets a verdict here, in one function, so a
        rule added for one route cannot skip its siblings (CLAUDE.md,
        ACTIVE WARNINGS). What it does NOT judge is anything it would have
        to read `data/nai/` to know -- the proof row, the LOCK file, the
        balance chain. Those are the guard's, in the child, and `plan`
        prints them.
        """
        names_character = subcommand in ("render", "plan", "run", "infill",
                                         "pixelize")
        if names_character and self._character_problem:
            return self._character_problem
        if names_character and self._derived_problem:
            return self._derived_problem
        if subcommand in ("plan", "run") and self._action == "infill":
            return (f"`{subcommand}` takes --action generate or img2img: an "
                    f"infill is its own subcommand in tools/nai/cli.py, and "
                    f"there is no dry run for one")
        if subcommand == "infill" and self._action != "infill":
            return (f"the action is {self._action}: set it to infill before "
                    f"repainting one cell")
        if subcommand == "infill":
            if not self._source_edit.text().strip():
                return ("infill needs --from: the accepted strip it "
                        "repaints one cell of")
            if self._cell_spin.value() >= self._frame_count:
                return (f"cell {self._cell_spin.value()} is outside "
                        f"{self._recipe}: it has {self._frame_count} cells "
                        f"(0..{self._frame_count - 1})")
        # ONLY when this line actually carries --from. A path typed into the
        # base-image field and then left behind by a switch to `generate` is
        # not part of the command, and blocking on it would refuse a line
        # the flag is not even in.
        if "--from" in self._tail(subcommand):
            source = self._source_edit.text().strip()
            if source and not os.path.isfile(self._resolve(source)):
                return f"the base image {source} is not a file"
        if subcommand == "pixelize":
            strip = self._strip_edit.text().strip()
            if not strip:
                return ("pixelize needs the strip PNG to post-process: put "
                        "it in Post-processing / Strip PNG")
            if not os.path.isfile(self._resolve(strip)):
                return f"the strip {strip} is not a file"
        return ""

    def _resolve(self, path: str) -> str:
        """`path` as the child would see it: relative to the checkout."""
        return path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)

    # -- driving it --------------------------------------------------------

    def set_character(self, state: object) -> None:
        """Take a `character_pane.CharacterState`.

        Puts `state.name` into `--character`, redraws the derived Prompt,
        Character Prompts and Character Positions rows for the new outfit
        (`recipes.get_recipe(recipe, name)` and `mannequin.render_init`),
        and, when `state.ok()` is False, puts `state.problem` into every
        command's `blocked`. Emits `command_changed`.
        """
        self._character = state.name
        self._character_problem = "" if state.ok() else state.problem
        self._character_label.setText(self._character)
        self._character_problem_label.setText(self._character_problem)
        self._character_problem_label.setVisible(
            bool(self._character_problem))
        self._refresh_derived()
        self._emit()

    def set_recipe(self, name: str) -> None:
        """Choose walk, run or jump; redraw the derived rows; emit.

        ValueError listing `recipes.RECIPE_NAMES` for an unknown name.
        """
        if name not in recipes.RECIPE_NAMES:
            raise ValueError(f"unknown recipe {name!r}; legal: "
                             f"{', '.join(recipes.RECIPE_NAMES)}")
        self._recipe = name
        if self._recipe_combo.currentText() != name:
            self._recipe_combo.setCurrentText(name)
        self._refresh_derived()
        self._emit()

    def set_action(self, action: str) -> None:
        """Choose generate, img2img or infill.

        Shows the Image to Image group for img2img and infill and hides it
        for generate -- the one group that IS hidden rather than locked,
        because it is not a limit, it is a field that does not exist for
        that action (`recipes._ACTION_KEYS`). Emits `command_changed`.

        ValueError for an action outside `model.ACTIONS`.
        """
        if action not in model.ACTIONS:
            raise ValueError(f"unknown action {action!r}; legal: "
                             f"{', '.join(model.ACTIONS)}")
        self._action = action
        if self._action_combo.currentText() != action:
            self._action_combo.setCurrentText(action)
        self._apply_action()
        self._emit()

    def randomise_seed(self) -> int:
        """Put a fresh seed in the Seed field; return it; emit.

        `secrets` in [`model.SEED_MIN`, `model.SEED_MAX`], the same range
        the CLI draws from, so a seed typed here and a seed the CLI picked
        are the same kind of number.
        """
        seed = model.SEED_MIN + secrets.randbelow(
            model.SEED_MAX - model.SEED_MIN + 1)
        self._seed_edit.setText(str(seed))
        return seed

    def values(self) -> dict:
        """The EDITABLE and CAPPED rows as {flag: value}, for the window to
        remember.

        Only flags: nothing derived and nothing locked is in here, so a
        saved layout can never carry a value the guard forbids back in.
        Every settable control appears, NovelAI's rows and this pipeline's
        own, because a window that remembered half a form would reopen on a
        line the author did not leave.
        """
        return {
            "--variant": self._variant_combo.currentData(),
            "--steps": self._steps_spin.value(),
            "--scale": self._scale_spin.value(),
            "--seed": self._seed_edit.text().strip(),
            "--from": self._source_edit.text().strip(),
            "--strength": self._strength_spin.value(),
            "--noise": self._noise_spin.value(),
            "--color-correct": self._colour_correct.isChecked(),
            "--cell": self._cell_spin.value(),
            "--keep-cell": self._keep_cell.isChecked(),
            "--round": self._round_spin.value(),
            "--phase": self._phase_edit.text().strip(),
            "--lever": self._lever_edit.text().strip(),
            "--colours": self._colours_spin.value(),
            "--remove-orphans": self._remove_orphans.isChecked(),
            "--last": self._last_spin.value(),
        }

    # -- internals ---------------------------------------------------------

    def _emit(self) -> None:
        """Announce the command line as it now stands. Runs NOTHING."""
        if self._quiet:
            return
        self.command_changed.emit(self.command(self._default_subcommand()))

    def _default_subcommand(self) -> str:
        """The subcommand the box shows after an edit.

        `plan` for generate and img2img: the dry run is free, always safe,
        and its numbered verdicts are what a reader wants next. For infill
        there IS no dry run -- `tools/nai/cli.py`'s plan takes only
        generate and img2img -- so the box shows the `infill` line itself,
        because a composer that will not show you the line you are
        composing is not a composer. Showing it runs nothing: a sending
        line still needs an arm and a send, and `RunPane.set_command`
        disarms on every one of these.
        """
        return "infill" if self._action == "infill" else "plan"

    def _edited(self) -> None:
        """Any editable control moved: recompose the line, and nothing else."""
        self._refresh_cost()
        self._emit()

    def _variant_picked(self, _index: int) -> None:
        """The Model combo moved: restate the model id, recompose the line."""
        self._model_id_label.setText(
            f"sends model {model.model_for(self._action, self._variant())}")
        self._edited()

    def _action_picked(self, action: str) -> None:
        """The Action combo moved: apply it and re-emit."""
        self.set_action(action)

    def _recipe_picked(self, name: str) -> None:
        """The Recipe combo moved: apply it and re-emit."""
        self.set_recipe(name)

    def _randomise_clicked(self) -> None:
        """The Randomise button: a new seed, then the new line."""
        self.randomise_seed()

    def _browse_source(self) -> None:
        """Pick the base image with a file dialog. A USER ACTION ONLY.

        Law 13: no check ever reaches this, because no check presses a
        button; `_source_edit.setText` is the path every test uses.
        """
        from PySide6.QtWidgets import QFileDialog
        start = os.path.join(REPO_ROOT, "data", "nai")
        path, _filter = QFileDialog.getOpenFileName(
            self, "The strip to re-pass", start, "PNG images (*.png)")
        if path:
            self._source_edit.setText(os.path.relpath(path, REPO_ROOT))

    def _browse_strip(self) -> None:
        """Pick the strip to post-process. A USER ACTION ONLY (law 13)."""
        from PySide6.QtWidgets import QFileDialog
        start = os.path.join(REPO_ROOT, "data", "nai")
        path, _filter = QFileDialog.getOpenFileName(
            self, "The strip to pixelize", start, "PNG images (*.png)")
        if path:
            self._strip_edit.setText(os.path.relpath(path, REPO_ROOT))

    def _apply_action(self) -> None:
        """Show the groups this action has, hide the ones it does not have."""
        self._i2i_group.setVisible(self._action != "generate")
        self._cell_spin.setEnabled(self._action == "infill")
        self._keep_cell.setEnabled(self._action == "infill")
        self._full_repaint.setEnabled(self._action == "infill")
        self._colour_correct.setEnabled(self._action == "img2img")
        self._source_edit.setEnabled(self._action != "generate")
        self._source_edit.setPlaceholderText(
            "REQUIRED: the accepted strip this repaints one cell of"
            if self._action == "infill"
            else "empty: the mannequin init (img2img only)")
        self._noise_spin.setValue(
            model.DEFAULT_INFILL_NOISE if self._action == "infill"
            else model.DEFAULT_IMG2IMG_NOISE)
        self._model_id_label.setText(
            f"sends model {model.model_for(self._action, self._variant())}")
        self._refresh_cost()

    def _variant(self) -> str:
        """The chosen variant: `full` or `curated`."""
        return self._variant_combo.currentData()

    def _refresh_cost(self) -> None:
        """Rewrite the Anlas line for the action now chosen."""
        if self._action == "generate":
            self._cost_label.setStyleSheet(theme.BANNER_STYLE)
            self._cost_label.setText(_ANLAS_FREE.format(
                steps=self._steps_spin.value(), max=model.MAX_STEPS,
                w=model.DEFAULT_WIDTH, h=model.DEFAULT_HEIGHT,
                area=model.MAX_AREA))
        else:
            self._cost_label.setStyleSheet(theme.LOCKED_STYLE)
            self._cost_label.setText(
                _ANLAS_UNPROVEN.format(action=self._action))

    def _refresh_derived(self) -> None:
        """Rebuild every DERIVED row from the recipe and the character file.

        `recipes.get_recipe` and `mannequin.render_init` are the only
        sources: the captions and the centres are shown EXACTLY as the tool
        will send them. A character file the loader refuses is shown as its
        refusal, verbatim, in every derived row -- not as a stale caption
        for the previous character, which would be a line that lies.
        """
        try:
            recipe = recipes.get_recipe(self._recipe, self._character)
            _png, centers = mannequin.render_init(
                recipe.layout, recipe.poses, recipe.identity.as_dict(),
                garments=recipe.identity.garments)
            frames = recipes.frames_for(recipe, centers)
        except (ValueError, KeyError, OSError) as exc:
            self._derived_problem = str(exc)
            self._show_derived_problem()
            return
        self._derived_problem = ""
        self._layout_name = recipe.layout.name
        self._frame_count = recipe.layout.count
        self._prompt_box.setPlainText(recipe.base_caption)
        self._negative_box.setPlainText(recipe.negative)
        self._positions_field.setText(
            "  ".join(f"{i}:({f.center[0]}, {f.center[1]})"
                      for i, f in enumerate(frames)))
        # A marker's label is DRAWN INSIDE a 21-pixel cell, so it is the
        # frame's index and not its sentence; the row's own number and the
        # grid's tooltip carry the long form.
        markers = tuple((frame.center[0], frame.center[1], f"f{i}")
                        for i, frame in enumerate(frames))
        for index, (row_widget, caption, grid) in enumerate(self._frame_rows):
            live = index < len(frames)
            row_widget.setVisible(live)
            grid.set_markers((), distinct=False)
            if live:
                caption.setPlainText(frames[index].caption)
                # The whole sentence, on hover as well as wrapped in the
                # box, because this is the value a reader is most likely to
                # want to check against a ledger row.
                caption.setToolTip(frames[index].caption)
                grid.set_label(f"f{index}")
                grid.set_center(*frames[index].center)
        for index, (_row, _caption, grid) in enumerate(self._frame_rows):
            if index < len(frames):
                grid.set_markers(markers)
        self._size_field.set_value(
            f"{recipe.layout.width} x {recipe.layout.height}  "
            f"({recipe.layout.name}, {recipe.layout.count} cells)")
        self._cell_spin.setMaximum(max(0, recipe.layout.count - 1))
        self._refresh_cost()

    def _show_derived_problem(self) -> None:
        """Put the loader's refusal in the rows the recipe would have filled."""
        self._frame_count = 0
        self._prompt_box.setPlainText(self._derived_problem)
        self._negative_box.setPlainText("")
        self._positions_field.setText("")
        for row_widget, caption, _grid in self._frame_rows:
            caption.setPlainText("")
            caption.setToolTip("")
            row_widget.setVisible(False)
        self._size_field.set_value("no layout: the character file is refused")
