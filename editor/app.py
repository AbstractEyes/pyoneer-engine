"""Launch the Pyoneer editor.

    .venv/Scripts/python.exe editor/app.py
    .venv/Scripts/python.exe editor/app.py --genre platformer
    .venv/Scripts/python.exe editor/app.py --root path/to/project

Deliberately a separate process from the game. `File > Play` launches
`main.py` as a subprocess; the editor never hosts the runtime, so a crash
in one cannot take the other with it.
"""
from __future__ import annotations

import _bootstrap  # noqa: F401

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pyoneer editor")
    parser.add_argument("--root", default=_bootstrap.REPO_ROOT,
                        help="project root (defaults to this repository)")
    parser.add_argument("--genre", default=None,
                        help="override the genre pack for this session")
    parser.add_argument("--list-genres", action="store_true",
                        help="print the installed genre packs and exit")
    args = parser.parse_args(argv)

    from editor.core import genre as genre_module

    if args.list_genres:
        for genre_id in genre_module.available():
            pack = genre_module.load(genre_id)
            print(f"{genre_id:<16} {pack.title}")
            print(f"{'':<16} {pack.summary}")
        return 0

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("The editor needs PySide6:\n\n"
              "    .venv/Scripts/python.exe -m pip install -r "
              "editor/requirements.txt\n", file=sys.stderr)
        return 2

    from editor.core.session import Session
    from editor.ui.main_window import EditorWindow

    application = QApplication(sys.argv)
    application.setApplicationName("Pyoneer Editor")

    try:
        session = Session.open(args.root, genre_id=args.genre)
    except Exception as exc:                                    # noqa: BLE001
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Could not open the project",
                             f"{type(exc).__name__}: {exc}")
        return 1

    window = EditorWindow(session)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
