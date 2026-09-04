"""The composition of the selected object, as a grouped checklist and a sequence.

`pyoneer_behaviors` is the declaration site of the engine's central
abstraction -- an entity is one class carrying a list of tokens read off the
tmx object at spawn -- so this panel authors it as a checklist with types,
parameters and refusals. Rendered as free text, a list naming a token that
does not resolve, or two behaviors that declare they conflict, is authored
happily and fails at map load with the object id in the exception.

What to show lives in `editor/core/behavior_view.py`, which imports no Qt.
This file is the frame: build the view, hand it a description, send what it
emits to the window's single mutation point. That split is why
`tools/check_behavior_ui.py` can assert "ticking `platformer_move` on a body
that already carries `topdown_move` emits NOTHING and names both sides"
without opening a window.

HOW IT IS ARRANGED, AND WHY THAT IS HERE
----------------------------------------
`group_by_category` takes the description apart and puts it back together in
the shape an author reads: one section per family of behaviors, and above
them the sequence one frame will actually run. It is arrangement and nothing
else -- every `emit`, every `blocked_reason` and every value is carried
across untouched, so a refusal still greys its tick and still says why. It is
a module-level function on `Inspection` rather than a method, so a check
drives it with no window, exactly like the description it rearranges.

Two facts it exists to fix, both of them the author's own report:

  * **The order number read as an id.** `order` is a position in the frame;
    10, 15 and 20 are three moments, not three names. So every row now says
    which STEP of the frame it is (`step 1 of 6`), every row's tooltip
    carries `ORDER_RULE` -- the one sentence, written once, in
    `scripts/game/behavior/base.py` -- and the panel opens with the ticked
    behaviors numbered in the sequence the frame will call them.
  * **The families were invisible.** The checklist is grouped by
    `BehaviorSpec.category`, which is DERIVED from the module the behavior is
    declared in and mapped nowhere. A behavior registered tomorrow gets its
    heading for free; there is no table here to forget to edit, which is the
    single most repeated failure this repository records.

The grouping and the sequence are two different readings and the panel needs
both, because a category interleaves: `action` holds order 15 and order 90,
so reading the groups top to bottom does NOT give the run order. Neither
view is derivable from the other by eye, which is why one does not replace
the other.

The Parameters section is passed through exactly as it arrives, in position
and in order. It already sits under its behavior: `_parameters` walks the
ticked tokens in the order the object lists them, so a behavior's parameters
follow it. They are not nested INSIDE the checklist rows because one property
can feed several behaviors -- the three action behaviors declare the same
`verb`, `cooldown_ms` and `payload` keys, one tmx property answers all three,
and filing that row under one of them would be a lie the panel tells with a
straight face.

NO NEW VERB
-----------
Every edit here is `map.object.property.set` or `map.object.property.remove`
-- the pair that already writes any tmx custom property and returns an exact
inverse, so this panel inherits undo, one-step rollback, the History panel
and the generated `COMMANDS.md`. Validation cannot move into a verb: a
command that raises inside a transaction takes the rollback with it, so a
refused list must never reach the stream. The panel refuses first and emits
second.

THE TWO QT TRAPS
----------------
Both live on exactly the path this panel takes -- a checkbox emitting a
command that refreshes the form the checkbox is in:

  * `widget.setParent(None)` does not detach a widget, it PROMOTES it to a
    top-level window. Clearing a layout that way leaks about twenty
    miniature windows per Ctrl+Z (59 top-level widgets at rest, 85 after one
    undo, still 85 afterwards).
  * `QScrollArea.setWidget()` frees the widget it replaces SYNCHRONOUSLY, so
    the naive cure for the first frees a checkbox while its own `toggled`
    signal is still on the stack -- a hard STATUS_HEAP_CORRUPTION
    (0xC0000374) crash of the whole editor.

The one sequence that survives both is `takeWidget()` -> `setParent(self)` ->
`hide()` -> `deleteLater()` -> `setWidget(new)`, written once in
`InspectionView.show_inspection`. So this panel rebuilds NOTHING of its own:
the chrome below is built once in `build_content` and only ever has its text
set, and every field widget is `InspectionView`'s.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from editor.core.behavior_view import describe_behaviors, object_at, read_tokens
from editor.core.inspect import Field, Inspection, Section
from editor.ui.docks import ScopedDock
from editor.ui.fields import InspectionView

from scripts.game.behavior.registry import (BEHAVIOR_REGISTRY, ORDER_RULE,
                                            BehaviorSpec, categories,
                                            category_label, run_order,
                                            step_of)

#: Sits above the form, always. Not a caveat like the Actions panel's banner:
#: `LayerRenderer` really does read this property at spawn, and this is the
#: one fact an author needs before ticking anything.
IS_WIRED = (
    "The .tmx object is the whole truth. This list is read at spawn and the "
    "behaviors are attached before the entity binds, so a map plays the same "
    "way whether or not the editor has ever opened it."
)

_BANNER_STYLE = ("background: rgba(120, 180, 255, 30); "
                 "border-left: 3px solid rgb(120, 180, 255); "
                 "padding: 7px 9px; font-size: 11px;")

_PROBLEM_STYLE = ("background: rgba(255, 120, 120, 40); "
                  "border-left: 3px solid rgb(255, 120, 120); "
                  "padding: 6px 9px; font-size: 11px;")

#: The section `editor/core/behavior_view.py` builds and this file takes apart.
CHECKLIST = "Behaviors"

#: The sequence, above the groups. Not a checklist: nothing here is tickable,
#: because the run order is not something an author sets. It is what the
#: `order` numbers already on the rows ADD UP TO, which is the thing that was
#: unreadable when they were shown one at a time.
RUN_SECTION = "Runs in this order"

#: Where a token the registry does not know goes: its own group, last of the
#: groups, because it has no category to be derived from -- it is either a
#: typo or a behavior the game registers at import, and inventing a heading
#: for it would be the catch-all bucket `BehaviorSpec.category` refuses.
STRAY_SECTION = CHECKLIST + " · not in the registry"

_RUN_NOTE = (
    "What one frame does to this object, top to bottom. " + ORDER_RULE)

_CATEGORY_NOTE = (
    "Derived from where these behaviors are declared: %s. Nothing maps a "
    "token to a category, so a behavior registered tomorrow appears under "
    "its own module with no edit to the editor.")

_ORDINALS = ("0th", "1st", "2nd", "3rd")


def ordinal(number: int) -> str:
    """`1` -> `1st`. Used for the run sequence, so it reads as a position."""
    if number % 100 in (11, 12, 13) or number % 10 > 3:
        return "%dth" % number
    return "%d%s" % (number, _ORDINALS[number % 10][1:])


def category_title(name: str) -> str:
    """The section heading one category gets. Derived, never listed."""
    return "%s · %s" % (CHECKLIST, category_label(name))


def group_by_category(inspection: Inspection, tokens: Sequence[str],
                      registry: Mapping[str, BehaviorSpec] | None = None
                      ) -> Inspection:
    """Rearrange one description: the run sequence first, then the families.

    Arrangement ONLY. Every field crosses over with its `emit`, its
    `blocked_reason`, its value and its removability intact -- rebuilt with
    `dataclasses.replace` rather than mutated, so calling this twice on one
    description cannot double-prefix a label. Nothing is dropped: every row
    of the checklist lands in exactly one group, and every other section is
    passed through in its original position and order.

    `tokens` is the object's list AS AUTHORED, which the checklist itself
    cannot supply: its rows are sorted by `(order, name)`, and two behaviors
    at one order run in the sequence the OBJECT lists them. Reading the tie
    off the sorted rows would show a sequence the frame does not run.
    """
    table = BEHAVIOR_REGISTRY if registry is None else registry
    source = next((s for s in inspection.sections if s.title == CHECKLIST),
                  None)
    if source is None:
        # An error description has no sections at all, and a future one may
        # title its checklist differently. Returning it untouched is right for
        # both: this function decorates a description, it does not validate
        # one.
        return inspection

    known = [row for row in source.fields if row.key in table]
    stray = [row for row in source.fields if row.key not in table]
    ticked = tuple(name for name in dict.fromkeys(tokens) if name in table)

    grouped: dict[str, list[Field]] = {}
    for row in known:
        grouped.setdefault(table[row.key].category, []).append(
            _stepped(row, table[row.key], table))
    ranked = {name: index for index, (name, _) in enumerate(categories(table))}

    rebuilt: list[Section] = [_sequence(ticked, tokens, table)]
    for name in sorted(grouped, key=lambda n: (ranked.get(n, len(ranked)), n)):
        modules = sorted({table[row.key].declared_in for row in grouped[name]})
        rebuilt.append(Section(
            category_title(name), grouped[name],
            note=_CATEGORY_NOTE % ", ".join(modules)))
    if stray:
        rebuilt.append(Section(
            STRAY_SECTION, stray,
            note="These are on the object and the editor's registry does not "
                 "have them, so they have no category to be filed under. The "
                 "engine REFUSES the whole object at load until they are "
                 "gone, unless the game registers them itself at import."))

    sections = list(inspection.sections)
    at = sections.index(source)
    return replace(inspection, sections=sections[:at] + rebuilt
                   + sections[at + 1:])


def _stepped(row: Field, spec: BehaviorSpec,
             table: Mapping[str, BehaviorSpec]) -> Field:
    """One checklist row, told which step of the frame it runs in.

    The step is prefixed rather than substituted into the label: the label is
    built in `editor/core/behavior_view.py` and carries the status and the
    genre marker, and rewriting text another module composed is how two
    modules end up owning one string. `step_of` gives two behaviors at one
    order the SAME step, which is the honest reading -- the file, not the
    number, decides which of them goes first.
    """
    step, total = step_of(spec, table)
    return replace(
        row,
        label="step %d of %d   ·   %s" % (step, total, row.label),
        doc=("%s\n\n%s" % (row.doc, ORDER_RULE)) if row.doc else ORDER_RULE)


def _sequence(ticked: Sequence[str], authored: Sequence[str],
              table: Mapping[str, BehaviorSpec]) -> Section:
    """The ticked behaviors, numbered in the order the frame will call them.

    Read-only by construction (no `emit`), because there is nothing here to
    set: the sequence is `order` plus the object's own list, and both are
    edited elsewhere in this panel.

    A tie says so in its own row instead of pretending the number decided it.
    """
    section = Section(RUN_SECTION, note=_RUN_NOTE)
    unresolved = [name for name in dict.fromkeys(authored) if name not in table]
    if not ticked:
        section.note += ("\n\nNothing is ticked, so no behavior runs and this "
                         "object is inert. Tick one below.")
    for position, spec in enumerate(run_order(ticked, table), 1):
        tied = [other for other in ticked
                if other != spec.name and table[other].order == spec.order]
        section.fields.append(Field(
            "run:" + spec.name,
            "%s   ·   %s" % (ordinal(position), spec.name), "str",
            "order %d%s" % (spec.order,
                            (" — tied with %s, so the object's list decides"
                             % ", ".join(tied)) if tied else ""),
            doc="%s\n\n%s" % (spec.summary, ORDER_RULE)))
    if unresolved:
        section.note += (
            "\n\nNot shown, because the editor's registry cannot resolve "
            "them: " + ", ".join(unresolved) + ". The engine refuses the "
            "whole object at load while they are listed.")
    return section


class BehaviorDock(ScopedDock):
    """Which behaviors the selected object composes, and what they read."""

    follows_selection = True

    def build_content(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = QLabel(IS_WIRED)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(_BANNER_STYLE)
        layout.addWidget(self.banner)

        self.view = InspectionView(show_header=True, show_sources=False)
        self.view.command_requested.connect(self.__on_command)
        layout.addWidget(self.view, 1)

        # An emitter that refuses to build a command returns None, which the
        # view treats as a silent no-op -- right for "nothing changed", wrong
        # for "your value was rejected", which is what this label says. Its
        # text is set and it is never rebuilt, so neither Qt trap applies.
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(_PROBLEM_STYLE)
        self.problem.hide()
        layout.addWidget(self.problem)
        return holder

    # -- refreshing --------------------------------------------------------

    def refresh(self) -> None:
        # Cleared BEFORE describing, never after: describing installs the
        # emitters that call `report`, and one firing during this refresh
        # must not have its message wiped.
        self.report("")
        # The authored list is read here and not taken from the description,
        # because the description's rows are sorted by run order and the run
        # order needs the object's own sequence to break a tie. Same reader
        # `describe_behaviors` uses, one line apart, so the two cannot see
        # different files.
        tokens = read_tokens(object_at(self.session, self._scope)[1])
        self.view.show_inspection(group_by_category(
            describe_behaviors(self.session, self._scope,
                               on_error=self.report),
            tokens))

    def report(self, message: str) -> None:
        """Show why an edit produced no command, or clear it."""
        self.problem.setText(message)
        self.problem.setVisible(bool(message))

    # -- emitting ----------------------------------------------------------

    def __on_command(self, command: Any) -> None:
        # run() reports a rejection to the user and returns False; either way
        # the form is rebuilt from the document rather than left showing what
        # was ticked, so a refused edit cannot leave the panel lying.
        self.window().run(command)
        self.refresh()
