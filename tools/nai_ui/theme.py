"""The editor's palette and chrome, reused rather than copied.

WHY THIS DELEGATES INSTEAD OF DEFINING
--------------------------------------
This window sits beside the Pyoneer editor on the same desktop, so it must
not look foreign beside it. A second palette here would be exactly the
sibling route CLAUDE.md's ACTIVE WARNINGS name: two spellings of one look,
drifting apart silently. So the palette IS `editor.ui.theme`'s, and this
module only calls it and names six chrome strings: four are the editor's
own idiom, quoted from `editor/ui/fields.py` and
`editor/ui/behavior_panel.py`, and two -- `LOCKED_STYLE` and `MONO_STYLE`
-- are this window's, because the editor has no control that is forbidden
and explained, and no box whose whole promise is that it is character for
character what will run.

LAW 2 DOES NOT APPLY HERE. `scripts/` may never import `editor/`; `tools/`
may and does (`tools/check_editor.py`). The engine is untouched by this
import, and `python main.py` on a clone with `editor/` deleted never
reaches this package.

LAW 7: this module RAISES when `editor.ui.theme` is missing. It does not
fall back to a plausible default palette, because a window that silently
stops matching the editor is the drift this module exists to prevent.

THE STYLE STRINGS are the editor's own idiom -- `palette(mid)` for a muted
label, a tinted background with a 3 px left border for a banner -- so they
follow a theme change instead of pinning a colour. `LOCKED_STYLE` is this
window's one addition: the look of a control the free-tier guard forbids,
which must read as DISABLED AND EXPLAINED rather than as broken.
"""
from __future__ import annotations

#: A muted caption under a field. The editor's `editor/ui/fields.py` idiom.
CAPTION_STYLE = "color: palette(mid); font-size: 11px;"

#: A section heading inside a pane.
HEADING_STYLE = "font-size: 15px; font-weight: 600;"

#: A blue explanatory banner, exactly `editor/ui/behavior_panel.py`'s.
BANNER_STYLE = ("background: rgba(120, 180, 255, 30); "
                "border-left: 3px solid rgb(120, 180, 255); "
                "padding: 7px 9px; font-size: 11px;")

#: A red refusal banner, exactly `editor/ui/behavior_panel.py`'s.
PROBLEM_STYLE = ("background: rgba(255, 120, 120, 40); "
                 "border-left: 3px solid rgb(255, 120, 120); "
                 "padding: 6px 9px; font-size: 11px;")

#: A control the guard forbids: greyed, with its reason beside it. Amber
#: rather than red, because nothing is wrong -- this is where free ends.
LOCKED_STYLE = ("background: rgba(230, 180, 80, 28); "
                "border-left: 3px solid rgb(230, 180, 80); "
                "padding: 4px 8px; font-size: 11px; color: palette(mid);")

#: The command box and the output view: one monospaced face for both, so a
#: command line and the output it produced line up in the same column.
MONO_STYLE = "font-family: Consolas, 'DejaVu Sans Mono', monospace; "


def apply(application) -> object:
    """Put the editor's palette on `application`; return the resolved Theme.

    `editor.ui.theme.apply(application, Theme.parse(EditorSettings().get(
    "theme")))` -- the editor's own saved preference, so both windows are
    light or dark together and neither has its own setting to forget.

    Raises ImportError, naming `editor/requirements.txt`, when PySide6 or
    `editor/` is absent. It does not fall back to an unthemed window.
    """
    try:
        from editor.core.settings import EditorSettings
        from editor.ui import theme as editor_theme
    except ImportError as exc:
        raise ImportError(
            f"the composer window wears the editor's palette, and "
            f"{exc.name} is not importable: install the editor's toolkit "
            f"with "
            f"    .venv/Scripts/python.exe -m pip install -r "
            f"editor/requirements.txt") from exc
    return editor_theme.apply(
        application, editor_theme.Theme.parse(EditorSettings().get("theme")))
