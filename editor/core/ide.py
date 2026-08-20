"""Open a file, at a line, in whichever IDE the developer actually uses.

WHY THIS IS A CORE MODULE AND NOT A BUTTON
------------------------------------------
"Show me the code behind this" is the seam between authoring and
programming, and it has to work without ceremony or nobody uses it. It also
has to be **incapable of breaking anything**: revealing code is a read-only
act, so nothing here may raise into the editor's event loop, block it, or
depend on the game's code being valid.

So the whole module is built around two rules:

  * **Construction is pure.** `command_for()` builds an argv from a spec and
    a path and a line, and touches nothing. It is fully testable without
    launching a process, which is why the flag syntax for four different
    IDEs can be asserted rather than hoped at.
  * **Launching never blocks and never raises.** `open_at()` returns a
    reason string on failure instead of throwing. A missing IDE is a status
    bar message, not a traceback.

DETECTION
---------
Three strategies, cheapest first: the PATH, then JetBrains Toolbox shims,
then well-known install directories. Nothing is launched to find out whether
it exists. The result is cached for the process, because scanning Program
Files on every right-click would be felt.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Sequence

# --------------------------------------------------------------------------
# Specs
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class IdeSpec:
    """How to invoke one IDE.

    Two explicit argv templates rather than one clever one. The first
    version filtered out any token containing `{line}` when no line was
    wanted, which silently left PyCharm's `--line` FLAG behind and produced
    `pycharm --line <path>`. Two templates cannot do that.
    """

    id: str
    name: str
    executables: tuple[str, ...]         # names to look for on PATH
    goto: tuple[str, ...]                # argv when a line is known
    plain: tuple[str, ...] = ("{file}",)  # argv when it is not
    windows_globs: tuple[str, ...] = ()  # absolute patterns to probe
    toolbox: bool = False                # JetBrains Toolbox ships a shim


# `code -g file:line` is the documented goto form and is what the shim in
# %LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd forwards.
VSCODE = IdeSpec(
    id="vscode",
    name="Visual Studio Code",
    executables=("code", "code.cmd", "Code.exe"),
    goto=("-g", "{file}:{line}"),
    # User-scope install FIRST: where two VS Codes exist, the per-user one is
    # the one that is actually running, and the system-wide shim cold-starts
    # a second, older instance instead of jumping into it.
    windows_globs=(
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
        r"%PROGRAMFILES(X86)%\Microsoft VS Code\Code.exe",
    ),
)

VSCODE_INSIDERS = IdeSpec(
    id="vscode-insiders",
    name="VS Code Insiders",
    executables=("code-insiders", "code-insiders.cmd"),
    goto=("-g", "{file}:{line}"),
    windows_globs=(
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code Insiders\bin\code-insiders.cmd",
    ),
)

# JetBrains launchers take `--line N <file>`, in that order, and the line
# flag must come BEFORE the path.
PYCHARM = IdeSpec(
    id="pycharm",
    name="PyCharm",
    executables=("pycharm64.exe", "pycharm.exe", "pycharm.bat", "pycharm.cmd",
                 "pycharm"),
    goto=("--line", "{line}", "{file}"),
    windows_globs=(
        r"%LOCALAPPDATA%\Programs\PyCharm Professional\bin\pycharm64.exe",
        r"%LOCALAPPDATA%\Programs\PyCharm*\bin\pycharm64.exe",
        r"%PROGRAMFILES%\JetBrains\PyCharm*\bin\pycharm64.exe",
        r"%LOCALAPPDATA%\JetBrains\Toolbox\apps\PyCharm*\ch-0\*\bin\pycharm64.exe",
    ),
    toolbox=True,
)

IDEA = IdeSpec(
    id="idea",
    name="IntelliJ IDEA",
    executables=("idea64.exe", "idea.bat", "idea"),
    goto=("--line", "{line}", "{file}"),
    windows_globs=(
        r"%LOCALAPPDATA%\Programs\IntelliJ IDEA*\bin\idea64.exe",
        r"%PROGRAMFILES%\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
    ),
    toolbox=True,
)

SUBLIME = IdeSpec(
    id="sublime",
    name="Sublime Text",
    executables=("subl", "subl.exe", "sublime_text.exe"),
    goto=("{file}:{line}",),
    windows_globs=(r"%PROGRAMFILES%\Sublime Text*\subl.exe",),
)

NOTEPADPP = IdeSpec(
    id="notepad++",
    name="Notepad++",
    executables=("notepad++.exe", "notepad++"),
    goto=("-n{line}", "{file}"),
    windows_globs=(r"%PROGRAMFILES%\Notepad++\notepad++.exe",
                   r"%PROGRAMFILES(X86)%\Notepad++\notepad++.exe"),
)

# Order is preference order when nothing is configured. PyCharm first
# because this project is a PyCharm project -- .idea/ is in the repo.
KNOWN: tuple[IdeSpec, ...] = (PYCHARM, VSCODE, IDEA, VSCODE_INSIDERS,
                              SUBLIME, NOTEPADPP)


def spec(ide_id: str) -> IdeSpec | None:
    for candidate in KNOWN:
        if candidate.id == ide_id:
            return candidate
    return None


# --------------------------------------------------------------------------
# Command construction -- pure
# --------------------------------------------------------------------------

def command_for(found: "FoundIde", path: str, line: int | None = None
                ) -> list[str]:
    """The exact argv to run. No side effects, fully testable.

    When `line` is None the line token is dropped rather than passed as 0 --
    JetBrains treats `--line 0` as line 1 and VS Code appends a bare colon,
    both of which are wrong in a way nobody would notice.
    """
    absolute = os.path.abspath(path)
    template = found.spec.goto if line is not None else found.spec.plain
    return [found.executable] + [
        token.format(file=absolute, line=line) for token in template
    ]


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FoundIde:
    spec: IdeSpec
    executable: str
    how: str                       # "PATH" | "Toolbox" | "installed"
    version: str = ""
    display: str = ""              # e.g. "PyCharm Professional 2026.1.4"

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def name(self) -> str:
        return self.display or self.spec.name

    def __str__(self) -> str:
        return f"{self.name} ({self.how})"


_cache: list[FoundIde] | None = None


def _expand(pattern: str) -> list[str]:
    expanded = os.path.expandvars(pattern)
    if "%" in expanded:
        # An undefined variable such as %PROGRAMFILES(X86)% on a 32-bit
        # machine expands to itself; treat that as "not present".
        return []
    return sorted(glob.glob(expanded))


def _version_key(text: str) -> tuple:
    parts = []
    for chunk in str(text).replace("-", ".").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts) or (0,)


def detect(*, refresh: bool = False) -> list[FoundIde]:
    """Every IDE we can find, best first. Nothing is launched.

    PATH IS THE LAST RESORT, NOT THE FIRST. On a machine with JetBrains
    Toolbox, `shutil.which("pycharm")` resolves by shim NAME, and the numeric
    suffix on those shims is assignment order rather than version order -- so
    `pycharm` can be an old Community install while the IDE actually running
    this project is a newer Professional one under `pycharm1`. A stale VS
    Code shim is worse: it cold-starts an older second instance instead of
    jumping into the window you are looking at, which looks like it worked.

    So: read Toolbox's own manifest, then well-known install locations
    (user-scope before system-scope), and only then fall back to PATH.
    Executables, never `.cmd` shims -- a shim flashes a console window out of
    a GUI app, and Python 3.11.4 predates the 3.11.9 fix for argument
    quoting into `.bat`/`.cmd` (CVE-2024-3566) on paths that are user data.
    """
    global _cache
    if _cache is not None and not refresh:
        return list(_cache)

    found: list[FoundIde] = []
    seen: set[str] = set()

    def offer(candidate: FoundIde | None) -> None:
        if candidate is None:
            return
        key = os.path.normcase(candidate.executable)
        if key not in seen:
            seen.add(key)
            found.append(candidate)

    for candidate in _toolbox_candidates():
        offer(candidate)

    for spec_ in KNOWN:
        if spec_.toolbox and any(f.id == spec_.id for f in found):
            continue
        offer(_locate_installed(spec_))

    for spec_ in KNOWN:
        if any(f.id == spec_.id for f in found):
            continue
        offer(_locate_on_path(spec_))

    order = {candidate.id: index for index, candidate in enumerate(KNOWN)}
    found.sort(key=lambda f: (order.get(f.id, 99), -_version_key(f.version)[0]))
    _cache = found
    return list(found)


def _toolbox_candidates() -> list[FoundIde]:
    """JetBrains Toolbox records exactly what we need, so read it.

    `state.json` carries toolId, displayName, displayVersion and an absolute
    `launchCommand` pointing at the real .exe. Newest version of each product
    family wins.
    """
    if sys.platform != "win32":
        return []
    path = os.path.expandvars(
        r"%LOCALAPPDATA%\JetBrains\Toolbox\state.json")
    if "%" in path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return []

    best: dict[str, FoundIde] = {}
    for tool in state.get("tools", []):
        launch = tool.get("launchCommand") or ""
        tool_id = str(tool.get("toolId") or "")
        if not launch or not os.path.isfile(launch):
            continue
        if tool_id.startswith("PyCharm"):
            base = PYCHARM
        elif tool_id.startswith("IDEA") or tool_id.startswith("IntelliJ"):
            base = IDEA
        else:
            continue
        version = str(tool.get("displayVersion") or "")
        name = str(tool.get("displayName") or base.name)
        entry = FoundIde(base, launch, "Toolbox", version=version,
                         display=f"{name} {version}".strip())
        previous = best.get(base.id)
        if previous is None or _version_key(version) > _version_key(previous.version):
            best[base.id] = entry
    return list(best.values())


def _locate_installed(candidate: IdeSpec) -> FoundIde | None:
    if sys.platform != "win32":
        return None
    for pattern in candidate.windows_globs:
        for match in _expand(pattern):
            if os.path.isfile(match):
                return FoundIde(candidate, match, "installed")
    return None


def _locate_on_path(candidate: IdeSpec) -> FoundIde | None:
    for name in candidate.executables:
        on_path = shutil.which(name)
        if on_path:
            return FoundIde(candidate, on_path, "PATH")
    return None


def preferred(configured: str | None = None) -> FoundIde | None:
    """The IDE to use: the configured one if it is present, else the best
    thing found. Returns None when nothing is installed."""
    available = detect()
    if configured:
        for found in available:
            if found.id == configured:
                return found
    return available[0] if available else None


# --------------------------------------------------------------------------
# Launching -- never blocks, never raises
# --------------------------------------------------------------------------

@dataclass
class LaunchResult:
    ok: bool
    message: str
    argv: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def open_at(path: str, line: int | None = None, *,
            configured: str | None = None,
            found: FoundIde | None = None) -> LaunchResult:
    """Reveal `path` (optionally at `line`) in the developer's IDE.

    Returns a result rather than raising. Revealing code must never be able
    to take the editor down -- the whole point of the feature is that it is
    the safe half of "let me look at the code".
    """
    absolute = os.path.abspath(path)
    if not os.path.exists(absolute):
        return LaunchResult(False, f"{absolute} does not exist")

    target = found or preferred(configured)
    if target is None:
        return LaunchResult(
            False,
            "no supported IDE found — looked for "
            + ", ".join(candidate.name for candidate in KNOWN))

    argv = command_for(target, absolute, line)
    try:
        # Detached: the editor must not wait on, or be killed with, the IDE.
        creation = 0
        if sys.platform == "win32":
            creation = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                       getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(argv, creationflags=creation,
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         close_fds=True)
    except OSError as exc:
        return LaunchResult(False, f"could not launch {target.name}: {exc}", argv)
    where = f"{os.path.basename(absolute)}:{line}" if line else os.path.basename(absolute)
    return LaunchResult(True, f"opened {where} in {target.name}", argv)


# --------------------------------------------------------------------------
# Finding the line to open at
# --------------------------------------------------------------------------

def find_symbol_line(path: str, symbol: str) -> int | None:
    """The line a class or function is defined on, WITHOUT importing.

    Parsing rather than importing is the crash-proofing: the editor can
    point at code that does not run, code with a broken dependency, or code
    that is mid-edit, and learn nothing worse than "I could not parse it".
    """
    import ast

    try:
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == symbol:
            return node.lineno
    return None
