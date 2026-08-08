"""The editor's headless core: document, commands, genre rules, requests.

Every module in this package is importable and testable without Qt and
without pygame. The GUI in `editor/ui/` is a view onto this and holds no
authority of its own -- a click produces a Command, exactly as an AI
response does.
"""
