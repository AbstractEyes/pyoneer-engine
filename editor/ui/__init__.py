"""Qt views over `editor.core`.

No module in here holds authority. A panel reads the session and emits
Commands; it never mutates the project directly. If you find yourself
reaching for `session.project.<something> = ...` inside a widget, the verb
you need is missing from `editor/core/verbs.py` -- add it there.
"""
