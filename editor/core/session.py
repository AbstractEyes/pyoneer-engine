"""An editing session: a project, its command stream, and its staged notes.

The single object the GUI holds. Everything the GUI does goes through one
of three methods -- `run`, `stage`, `ship` -- so a panel never touches the
project directly and there is exactly one place to look when asking "what
can change this?".

Importing this module registers the command vocabulary as a side effect
(`editor.core.verbs`). That import is load-bearing and deliberate.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Iterable

from editor.core import verbs as _verbs             # noqa: F401  (registers verbs)
from editor.core.collision import (
    NO_DATA,
    collision_first_gid,
    companion_pairs,
    gid_to_opinion,
    world_coordinate_fault,
)
from editor.core.commands import Command, CommandStream, Transaction
from editor.core.genre import RuleViolation
from editor.core.project import Project
from editor.core.request import (
    Bundle,
    Manifest,
    Note,
    read_response,
    write_bundle,
)
from editor.core.scope import ASSETS, GENRE, PROJECT, Scope
from scripts.core.layer_profile import MOTION, PARALLAX_X, PARALLAX_Y


class Session:
    """One open project, with undo history and a staged manifest."""

    def __init__(self, project: Project):
        self.project = project
        self.stream = CommandStream(project)
        self.manifest = Manifest()
        self.last_bundle: Bundle | None = None

    # -- opening -----------------------------------------------------------

    @classmethod
    def open(cls, root: str, *, genre_id: str | None = None) -> "Session":
        return cls(Project.load(root, genre_id=genre_id))

    # -- changing ----------------------------------------------------------

    def run(self, commands: Command | Iterable[Command], *,
            label: str | None = None, source: str = "editor") -> Transaction:
        """The only way anything changes. Atomic; raises on any failure."""
        return self.stream.apply(commands, label=label, source=source)

    def undo(self) -> Transaction | None:
        return self.stream.undo()

    def redo(self) -> Transaction | None:
        return self.stream.redo()

    def save(self) -> list[str]:
        return self.project.save()

    @property
    def dirty(self) -> bool:
        return self.project.dirty

    # -- notes -------------------------------------------------------------

    def stage(self, scope: Scope | str, text: str, kind: str = "change") -> Note:
        """Attach a note to a scope. This is the prompt strip's whole job."""
        resolved = scope if isinstance(scope, Scope) else Scope.parse(scope)
        return self.manifest.add(Note(resolved, text, kind))

    def ship(self, *, title: str = "") -> Bundle:
        """Write the staged notes as a request bundle and clear them."""
        if title:
            self.manifest.title = title
        bundle = write_bundle(self.project, self.manifest)
        self.last_bundle = bundle
        self.manifest = Manifest()
        return bundle

    def ask(self, scope: Scope | str, text: str, kind: str = "change", *,
            also: Iterable[Scope | str] = (),
            requests_dir: str | None = None) -> str:
        """One note, one bundle, cut to one address. Returns its path.

        THE PIECEMEAL DOOR, and the other grain from `ship`. `ship` is for a
        change that crosses the project: it collects notes until they add up
        and sends everything the responder might need. `ask` is for the
        gesture the author actually makes most -- stand on one thing, say
        one sentence about it, send it now -- and it sends only what that
        address can be answered with. Measured on this tree, that is ~2,300
        tokens instead of ~9,300, and it is the ratio that makes asking
        cheap enough to do ten times in an afternoon.

        The staged manifest is NOT touched. An ask is not a ship: notes the
        author is still collecting stay collected, and asking about a tile
        layer mid-review does not silently post the review.

        Qt-free on purpose, so the whole request half is drivable from
        `open_here()` with no display -- which is how `tools/check_relay.py`
        measures the payload without opening a window.

        Refuses a scope no verb accepts; `write_bundle` owns that refusal so
        no caller can route around it.

        `also` names the other addresses this one request may touch, and the
        bundle then ships their verbs too and ACCEPTS a response aimed at
        them -- `BundleContract` refuses anything else. It exists because
        one real flow crosses addresses: attaching an event script needs
        `script.create` at `script:<id>` and `map.object.property.set` at
        the object that runs it, which is two scopes and no new verb
        (`docs/PLAN_SCENES.md` section 6). Widening is therefore a
        declaration the author makes, checked like everything else, rather
        than a hole in the gate for everybody.
        """
        resolved = scope if isinstance(scope, Scope) else Scope.parse(scope)
        bundle = write_bundle(self.project,
                              Manifest(notes=[Note(resolved, text, kind)]),
                              requests_dir=requests_dir, scoped=resolved,
                              also=also)
        self.last_bundle = bundle
        return bundle.directory

    # -- responses ---------------------------------------------------------

    def apply_response(self, path: str) -> Transaction:
        """Apply a `response.jsonl` as one undoable transaction.

        THE SCOPE GATE IS NOT HERE, DELIBERATELY. A response answering a
        SCOPED bundle may only use the verbs that bundle shipped, aimed at
        the addresses it declared -- and that check lives inside
        `read_response`, one call down, because this method is not the only
        door: the editor window's Apply-a-response does its own
        `read_response` and its own `run`, so a gate written here would
        guard the tool path and leave the path the author actually clicks
        wide open. That is the shape `CLAUDE.md`'s fourth ACTIVE WARNING
        counts sightings of. `read_response` is the chokepoint both doors
        share; see `BundleContract`.
        """
        commands = read_response(path)
        identifier = os.path.basename(os.path.dirname(os.path.abspath(path)))
        return self.run(commands,
                        label=f"response {identifier}",
                        source=f"response:{identifier}")

    # -- reading -----------------------------------------------------------

    def problems(self) -> list[RuleViolation]:
        """Everything wrong with the project: the genre's rules, plus the one
        fault only the collision model can see."""
        found: list[RuleViolation] = list(self.project.problems())
        found.extend(self.__dead_masks())
        return found

    def __dead_masks(self) -> Iterable[RuleViolation]:
        """Masks that are painted, look painted, and gate nothing.

        `world_coordinate_fault` is the engine's own refusal: a parallaxed or
        `motion`-driven layer is drawn at an offset that moves with the
        camera, so cell (3, 4) of that layer is not over cell (3, 4) of the
        map and `collision_layers` leaves it out of the stack entirely. Its
        companion's masks survive every save, read back correctly, and block
        nothing -- the single most expensive shape in this repository,
        because broken authored content looks exactly like working content.

        The hierarchy already tints that row and says so in a tooltip, which
        requires knowing which row to hover. This says it out loud, once per
        art layer, on the surface the author reads when asking "what is wrong
        with my map".

        BOTH halves, and the second one is the reason this is not one line: a
        faulted layer whose companion is EMPTY is reported as NOTHING. A
        parallax layer with no masks is not a problem, and a Problems dock
        that fires on every parallax layer in the project is worse than one
        that never fires at all -- it teaches the author to stop reading it.

        `painted` counts cells that DECODE, the same count the hierarchy
        badge shows and for the same reason: a companion gid outside the
        collision tileset's range reads as NO_DATA in the engine, so counting
        it would claim walls the field never had. A map with no collision
        tileset decodes nothing and reports nothing.
        """
        for map_name in self.project.map_names():
            try:
                document = self.project.map(map_name)
            except Exception:                                   # noqa: BLE001
                # Not swallowed: `GenrePack.validate` already yields a "hard"
                # violation naming the exception for this same map, and it is
                # in the list this one is being appended to.
                continue
            scope = Scope.of(("map", map_name))
            try:
                pairs = companion_pairs(document)
                first_gid = collision_first_gid(document)
            except Exception as exc:                            # noqa: BLE001
                yield RuleViolation(
                    "hard", scope,
                    f"this map's collision declarations could not be read, so "
                    f"no dead-mask fault can be reported for it: {exc}")
                continue
            for art, companion in pairs:
                fault = world_coordinate_fault(document, art)
                if fault is None:
                    continue
                painted = 0
                if first_gid is not None:
                    for gid in document.tile_layer(companion).gids():
                        if gid and gid_to_opinion(gid, first_gid) != NO_DATA:
                            painted += 1
                if not painted:
                    continue
                yield RuleViolation(
                    "soft", scope.child("layer", art),
                    f"{painted} mask{'' if painted == 1 else 's'} painted in "
                    f"{companion!r} "
                    f"{'reaches' if painted == 1 else 'reach'} no collision "
                    f"field: {art!r} is {fault}, so its cells are not the "
                    f"map's cells and nothing on it blocks movement",
                    fix=f"drop {PARALLAX_X}/{PARALLAX_Y} and {MOTION} from "
                        f"{art!r}, or move those {painted} masks onto a "
                        f"layer that stays put")

    def history(self) -> list[Transaction]:
        return self.stream.history()

    def subscribe(self, fn: Callable[[Transaction, str], None]) -> None:
        self.stream.subscribe(fn)

    # -- scopes the UI can offer -------------------------------------------

    def known_scopes(self) -> list[Scope]:
        """Every scope currently worth naming, for pickers and validation."""
        found: list[Scope] = [PROJECT, GENRE, ASSETS]
        for map_name in self.project.map_names():
            map_scope = Scope.of(("map", map_name))
            found.append(map_scope)
            try:
                document = self.project.map(map_name)
            except Exception:                                   # noqa: BLE001
                continue
            for layer in document.layer_names():
                found.append(map_scope.child("layer", layer))
        for table_name in self.project.table_names():
            found.append(Scope.of(("table", table_name)))
        for declared in self.project.genre.tables:
            scope = Scope.of(("table", declared.name))
            if scope not in found:
                found.append(scope)
        return found


def open_here(genre_id: str | None = None) -> Session:
    """Open the repository this file lives in. Convenience for tools."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return Session.open(root, genre_id=genre_id)
