"""Check the engine is loadable BEFORE the editor imports any of it.

WHY
---
The editor is a tool for changing a codebase that is, by design, being
changed underneath it, so the question that matters is what happens to the
editor while the engine is broken. Without this, a syntax error in any of
the three engine modules the editor imports kills it with a bare traceback
at `editor/app.py` -- above argparse, above the PySide6 check, above
`QApplication`, and above the QMessageBox fallback. Launched from a
shortcut, that is a window that simply never appears.

WHAT THIS DOES
--------------
Reads the three files and `ast.parse`s them -- **parses, never imports**, so
nothing executes and nothing can have a side effect -- then confirms each
still declares the handful of names the editor binds. On failure the editor
reports the file, the line, and the message, and exits with its own code
instead of a traceback.

This module imports `os`, `ast` and `sys` and nothing else, deliberately.
It cannot be broken by the code it is checking.

WHAT AST CANNOT TELL YOU
------------------------
  * nothing about inheritance across files -- it cannot know that
    `PyoneerGameObject`'s abstract methods make `GameEntity` uninstantiable
  * nothing about decorators -- `editor/core/verbs.py`'s verbs exist only
    because `@command(...)` mutates a registry at import time
  * nothing about dynamic registration, or whether a signature matches its
    call sites
  * a file can parse cleanly and still explode on import from module-level
    side effects

It catches the failure that actually stops the editor from starting, which
is a syntax error or a deleted name. That is the whole claim.
"""
from __future__ import annotations

import ast
import os
import sys

# The complete set of engine modules the editor reaches, and the names it
# binds from each. Hardcoded rather than discovered: the closure is three
# modules, and a list you can read is worth more than a scan you have to
# trust. `tools/check_editor.py` asserts this stays true, so a rename in
# scripts/ becomes a failing check rather than a startup crash.
ENGINE_CONTRACT: dict[str, tuple[str, ...]] = {
    "scripts/core/errors.py": (
        "PyoneerError", "PyoneerConfigError", "PyoneerAssetMissingError",
        "warn_content",
    ),
    "scripts/core/log.py": (
        "trace_assets",
    ),
    "scripts/loaders/map_document.py": (
        "MapDocument", "MapObject", "ObjectLayer", "MapProperties",
    ),
}

EXIT_ENGINE_BROKEN = 3


class Problem:
    """One reason the editor cannot start."""

    def __init__(self, path: str, message: str, line: int | None = None,
                 detail: str = ""):
        self.path = path
        self.message = message
        self.line = line
        self.detail = detail

    def __str__(self) -> str:
        where = f"{self.path} line {self.line}" if self.line else self.path
        text = f"{where}: {self.message}"
        return f"{text}\n    {self.detail.strip()}" if self.detail else text


def top_level_names(tree: ast.Module) -> set[str]:
    """Every name a module binds at module scope.

    Top level only, on purpose: a name that moved inside a conditional or a
    class body is no longer importable the way the editor imports it, and
    reporting it as present would be a false pass.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def check(root: str, contract: dict[str, tuple[str, ...]] | None = None
          ) -> list[Problem]:
    """Everything wrong with the engine, without importing any of it."""
    problems: list[Problem] = []
    for relative, required in (contract or ENGINE_CONTRACT).items():
        path = os.path.join(root, relative.replace("/", os.sep))
        if not os.path.isfile(path):
            problems.append(Problem(relative, "missing — the editor needs it"))
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as exc:
            problems.append(Problem(relative, f"could not be read: {exc}"))
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            problems.append(Problem(relative, exc.msg or "invalid syntax",
                                    exc.lineno, (exc.text or "")))
            continue
        except ValueError as exc:                     # NUL bytes, bad encoding
            problems.append(Problem(relative, f"could not be parsed: {exc}"))
            continue
        missing = [name for name in required if name not in top_level_names(tree)]
        if missing:
            problems.append(Problem(
                relative,
                f"no longer defines {', '.join(missing)} at module level, "
                f"which the editor imports"))
    return problems


def report(problems: list[Problem]) -> str:
    lines = [
        "The Pyoneer editor cannot start because the engine it reads is "
        "not loadable.",
        "",
    ]
    lines += [f"  • {problem}" for problem in problems]
    lines += [
        "",
        "Your project files have NOT been touched — the editor stopped "
        "before opening anything.",
        "Fix the file above and start the editor again.",
        "",
        "To start anyway (the editor will probably crash): "
        "editor/app.py --skip-preflight",
    ]
    return "\n".join(lines)


def enforce(root: str, *, skip: bool = False) -> None:
    """Stop the process with a readable message if the engine is broken.

    Tries a Qt dialog because the editor is usually launched from a
    shortcut, where stderr goes nowhere. Falls back to stderr, and never
    lets the reporting path itself raise.
    """
    if skip or os.environ.get("PYONEER_NO_PREFLIGHT"):
        return
    problems = check(root)
    if not problems:
        return

    text = report(problems)
    # stderr FIRST and unconditionally. A modal dialog nobody is there to
    # dismiss hangs forever instead of exiting, which is the one behaviour a
    # crash gate must never have.
    print(text, file=sys.stderr)
    if _can_show_a_dialog():
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            application = QApplication.instance() or QApplication([])
            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("Pyoneer Editor — engine not loadable")
            box.setText("The engine the editor reads is not loadable.")
            box.setDetailedText(text)
            box.exec()
            del application
        except Exception:                                       # noqa: BLE001
            pass
    raise SystemExit(EXIT_ENGINE_BROKEN)


# Platforms that exist precisely because nobody is watching the screen.
_HEADLESS_PLATFORMS = {"offscreen", "minimal", "vnc", "webgl"}


def _can_show_a_dialog() -> bool:
    """Is there a human to dismiss a modal dialog?

    The editor is usually launched from a shortcut, where stderr goes
    nowhere and a dialog is the only way to say anything -- so the default
    is yes. It is no only when the environment says outright that this is an
    automated run.
    """
    if os.environ.get("PYONEER_NO_DIALOGS"):
        return False
    return os.environ.get("QT_QPA_PLATFORM", "").lower() not in _HEADLESS_PLATFORMS
