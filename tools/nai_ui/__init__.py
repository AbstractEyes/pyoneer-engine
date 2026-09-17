"""A window that composes `python -m tools.nai` commands. It never sends one itself.

WHAT THIS IS
------------
A COMMAND COMPOSER, not a second NovelAI client. Every action this window
can take is an existing `tools.nai` subcommand. The window shows that exact
command line in a read-only, selectable box BEFORE it runs, runs it as a
subprocess that inherits this process's environment, and streams its stdout
and stderr into an output view.

    .venv/Scripts/python.exe -m tools.nai_ui

WHY IT IS BUILT THIS WAY
------------------------
Because the composer builds no request body and holds no credential, it
cannot get around the spend guard:

* THE KEY NEVER REACHES THIS PACKAGE. `NAI_KEY` is read by
  `tools.nai.transport.api_key`, inside the child process, at send time.
  This window learns only whether the name is PRESENT in `os.environ` (a
  bool -- `run_pane.key_present`) and shows only that word. No widget, log
  line, tooltip, window title, settings file or screenshot may carry the
  value, and nothing here reads `os.environ["NAI_KEY"]`.
* THE GUARD IS NOT REIMPLEMENTED HERE. `tools.nai.guard` runs in the child.
  What this window does with the Opus-tier limits is SHOW them: a control
  the guard would refuse is rendered greyed and non-editable, carrying the
  reason as visible text (`widgets.LockedField`). A reader must be able to
  see where the free allowance ends -- there is no free tier; the 28-step
  allowance is an Opus benefit -- so a forbidden control is never hidden.
* ONE GENERATION IS ONE COMMAND A HUMAN TYPED (docs/NAI_SPRITES.md, "The
  loop"). There is no queue, no batch, no sweep, no loop, no auto-retry,
  and nothing fires on a timer or on a value change. A command that opens a
  socket is armed by an explicit confirm step and runs exactly once per arm
  (`run_pane.RunPane`).
* THE PROBE FLAG IS TYPED BY HAND. `--accept-max-2-anlas` is spelled
  nowhere in this package; `tools/check_nai_ui.py` asserts that. The probe
  row is shown locked, with that sentence as its reason.

THE ONE FILE THIS WINDOW WRITES
-------------------------------
A character JSON under `tools/nai/characters/`, because that is data, not a
request (`character_pane.CharacterPane`). Every other byte on disk is
written by the child process, under `data/nai/`.

MODULES
-------
    theme.py           the editor's palette, so this window is not foreign
                       beside it
    widgets.py         the shared parts: NaiCommand, ColourSwatch,
                       PositionGrid, LockedField, CommandBox, ImageView,
                       field_row
    character_pane.py  pick, read, edit and save one character file;
                       emits CharacterState
    request_pane.py    NovelAI's own request form, in NovelAI's order, with
                       our values in it; exposes `command()`
    run_pane.py        show one NaiCommand, arm it if it sends, run it once,
                       stream its output
    app.py             the window that wires the three panes together

DEPENDENCIES
------------
PySide6 (the editor's toolkit; NOT in requirements.txt -- it is installed
from `editor/requirements.txt`) and `editor.ui.theme`. This package imports
`tools.nai` for its vocabularies (`model`, `characters`, `recipes`, `cli`)
and NEVER for its network: `run`, `transport` and `guard` are not imported
here, and nothing in this package calls `post_json`.
"""
from __future__ import annotations

import sys

MISSING_TOOLKIT = (
    "The NovelAI composer window needs PySide6, the editor's toolkit:" + chr(10)
    + chr(10) +
    "    .venv/Scripts/python.exe -m pip install -r editor/requirements.txt"
    + chr(10))
"""What a machine without the toolkit is told. A sentence naming the file
that installs it, not a traceback: `python -m tools.nai_ui` on a fresh
clone is the first thing anybody types, and an ImportError there reads as
a broken repository rather than as a missing optional dependency."""

EXIT_CANNOT_START = 2
"""The code `launch` returns when it never got as far as a window. Same
number `editor/app.py` returns for the same reason, so a script driving
either reads one convention."""


def launch(argv: list[str] | None = None) -> int:
    """Run the composer window; return the process exit code.

    Builds a `QApplication`, applies `theme.apply`, shows one
    `app.NaiWindow`, and enters the event loop. `argv` is
    `sys.argv[1:]` when None.

    Returns 0 on a clean close, 2 when PySide6 or `editor/` is not
    installed (printing the `editor/requirements.txt` line, as
    `editor/app.py` does) and when an argument is passed -- this window
    takes none, because every value it would accept is a field the author
    reads on screen before it is composed into a line. Raises nothing for
    a missing credential: the window opens and says so, because every
    non-sending command still works without one.

    The toolkit is imported INSIDE this function, and `tools.nai_ui.app`
    with it, so `import tools.nai_ui` on a machine with no PySide6 still
    works and this function is still callable to print the sentence.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv:
        print("`python -m tools.nai_ui` takes no arguments; it got "
              + " ".join(repr(a) for a in argv) + "." + chr(10) +
              "Every value this window sends is a field on screen, read "
              "before it is composed into a command line.")
        return EXIT_CANNOT_START

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(MISSING_TOOLKIT, file=sys.stderr)
        return EXIT_CANNOT_START

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Pyoneer NovelAI composer")

    from tools.nai_ui import theme
    try:
        # The palette before the window exists, so nothing flashes in the
        # old one -- `editor/app.py`'s own order.
        theme.apply(application)
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CANNOT_START

    from tools.nai_ui.app import NaiWindow
    window = NaiWindow()
    window.show()
    return application.exec()
