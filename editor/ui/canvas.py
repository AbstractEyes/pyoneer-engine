"""The map canvas and the tile palette.

MOUSE CONVENTIONS
-----------------
Taken from Tiled and Aseprite:

    left drag        paint with the current tool
    right drag       erase (a temporary eraser, whatever the tool)
    middle drag      pan
    space + drag     pan
    ctrl + wheel     zoom under the cursor
    alt + click      pick the tile under the cursor into the brush

ON AN OBJECT LAYER THE SAME BUTTONS MEAN SOMETHING ELSE
-------------------------------------------------------
There are no tiles to paint there, so the object gestures take over -- and
ONLY there. Every branch below is reached after the tile branch has already
declined, so a right-drag over a tile layer still erases exactly as it did.

    left drag        move the object under the cursor; one drag, one undo
    left click       select it (a drag that goes nowhere writes nothing);
                     on BARE GROUND it clears the selection and creates
                     nothing at all
    double click     open the object editor; on bare ground, place one first
    right click      a menu -- Edit / Delete over one object, a LIST to pick
                     from when several are stacked, nothing at all over bare
                     ground except a line saying so
    Delete           remove the SELECTED object

A SINGLE CLICK NEVER CREATES
----------------------------
It did, on bare ground, and the author's report is why this paragraph
exists: "left click is currently adding an entity to the map when it needs
to be double click". Double-click-to-place was ADDED and
single-click-to-place was never REMOVED, so merely navigating an object
layer littered it with entities nobody asked for -- an object placed by a
click that meant "look here" is one the author never looks at again.

QT'S EVENT ORDER IS WHY IT HAS TO STAY OUT. A double-click arrives as
press, release, DoubleClick, release: the single-click path runs FIRST, on
the way to every double-click there will ever be. So whatever a single
click does must be harmless to do immediately before a double-click --
which rules out creating, and rules out anything else expensive or
irreversible. Clearing the selection is the one answer that is both useful
and free to repeat: it is the standard gesture for "point at nothing", and
it is the only deliberate way back to the nothing-selected state.

Creation therefore lives in exactly one place -- `__place_object`, reached
only from `__open_object_editor`, reached only from a DoubleClick.
#TAG:single_click_never_creates

RIGHT-CLICK USED TO DELETE, WITH NO MENU AND NO QUESTION.
One press, on the button a hand uses to erase tiles, and the entity was
gone. It was undoable and it was still wrong: the gesture that means
"tell me about this" everywhere else in the editor was the destructive one
here, and the author asked for it to stop. Delete now costs a menu pick or
a selection plus a key.

SNAPPED BY DEFAULT, FREEFLOW ON PURPOSE
---------------------------------------
`snap_objects` is a plain attribute, set from outside exactly as
`grid_step` and `collision_subcell` are -- the persistent home of a view
preference is `editor.core.settings`, which this widget does not import.
Holding ALT during the drag inverts whatever it says, so the exception
costs no trip to a menu. The inversion is read at every MOVE and again at
RELEASE rather than at press, because alt+press is already the tile picker.

ONE STROKE, ONE TRANSACTION
---------------------------
Press-drag-release accumulates in an `editor.core.paint.Stroke` and commits
a single `map.tile.set_many` on release, so undo takes back the whole stroke
and the tmx csv payload is re-rendered once.

While the stroke is live the canvas draws a translucent GHOST of what it
would do. Nothing is committed until the button comes up, so dragging out a
rectangle and changing your mind costs nothing.

TWO MODES, ONE SET OF TOOLS
---------------------------
`EditMode.COLLISION` changes what a stroke WRITES, never what the tools ARE:
brush still brushes, R is still a rectangle, right-drag still erases. The
only differences are the layer that receives the write -- the active layer's
companion passability layer -- and the value, a mask instead of a tile.

That is why there is no second stroke machinery. A mask is stored as
`first_gid + mask` in an ordinary tile layer, so `paint.Stroke` over the
companion is already correct, down to the eraser: it writes gid 0, and gid 0
in a companion layer is `NO_DATA`, "nobody said anything here" -- which is
exactly what erasing collision should mean, and is NOT the same claim as
"open". Committing is the same `map.tile.set_many`, so a collision stroke
inherits one-transaction undo and an exact inverse for free.

The mode reaches the PALETTE by the same rule. Picking a tile in collision
mode writes that tile's own mask -- level one, so it applies everywhere the
tile is ever stamped -- rather than setting a brush the mode cannot paint
with. Same two-step as a cell: pick the mask, then pick what it applies to.
See `set_stamp` and `bake_tile_mask`.

The companion layer is created by the FIRST stroke that needs it, inside the
same transaction as the tiles. Three commands land together or none do, and
one undo takes the layer, its declaration and its tiles back out in reverse.

The mask TILESET, and the PNG it names, are provisioned by that same stroke
and never by a dialog -- see `CollisionTilesetOffer` and `write_mask_sheet`.

A TILESET'S HEADER IS A CONTROL, NOT A CAPTION
----------------------------------------------
Right-clicking the header strip above a sheet opens Rename / Grow / Remove,
which are `map.tileset.rename`, `map.tileset.grow` and `map.tileset.remove`
-- three verbs that existed, refused with teeth, inverted exactly, and had
no caller anywhere in the window. The palette asks the decision through the
`ask` seam and EMITS `tileset_requested`; the window turns it into one
`self.run(Command(...))`, so undo and the history list come free.

An entry that cannot act is disabled and says why in its own label, and an
entry that can act still names what it will cost -- how much headroom the
tileset has, how many placed tiles a removal would orphan. Both numbers come
from the MAP, which this widget cannot see, so `EditorWindow` installs
`tileset_facts` as a seam and it is asked when the menu opens rather than on
every repaint: two of its answers walk every cell of every tile layer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from scripts.core.errors import PyoneerError
from scripts.core.collision_runtime import (  # noqa: F401  (re-exported)
    COLLISION_TILESET,
    COMPANION_SUFFIX,
    collision_first_gid as engine_collision_first_gid,
    collision_layers,
    companion_name as engine_companion_name,
    depth_for_layer_name,
    tileset_defaults,
)
from scripts.game.behavior.base import BEHAVIORS
from scripts.loaders.map_document import tileset_geometry

from editor.core import autotile
from editor.core.collision import (
    NO_DATA,
    SUBCELL,
    CollisionLayer,
    companion_subcell,
    describe_opinion,
    field_subcell,
    gid_to_opinion,
    opinion_to_gid,
)
from editor.core.commands import Command
from editor.core.inspect import Field
from editor.core.layers import BLOCK_ALL, describe_mask, read_profile
from editor.core.paint import (
    Bounds,
    EditMode,
    Stamp,
    Stroke,
    Tool,
    edits_to_triples,
    footprint,
    grid_lines,
)
from editor.core.scope import Scope
from editor.ui.ask import ask_form
from editor.ui.collision_view import (
    LEVEL_NONE,
    MASK_DOMAIN,
    CollisionOverlay,
    glyph_pixmaps,
    masks_from_layer,
    resolve_cell,
)
from editor.ui.tileset import TilesetAtlas, gid_colour, render_layer

_OBJECT_PEN = QColor(255, 90, 90)
_OBJECT_SELECTED = QColor(120, 200, 255)
_GRID_PEN = QColor(255, 255, 255, 28)
_GHOST_Z = 2000
#: Under a mask ghost, so that painting "open" or clearing -- both of which
#: draw no glyph at all -- still shows you where the brush is.
_MASK_GHOST_FILL = QColor(120, 200, 255, 60)
_MASK_GHOST_PEN = QColor(120, 200, 255, 140)
#: The tile palette's marker for "this tile carries its own mask".
#:
#: A glyph alone cannot say it: `PASS_ALL`'s glyph is deliberately EMPTY, so a
#: tile baked OPEN would look exactly like a tile nobody has ever touched --
#: and "open" versus "nobody said anything" is the distinction level one
#: exists to make.
_BAKED_PEN = QColor(255, 206, 74)

# COLLISION_TILESET and COMPANION_SUFFIX are imported from
# `scripts/core/collision_runtime.py` above and re-exported here, because
# `from editor.ui.canvas import COLLISION_TILESET` is what the checks and the
# rest of the UI already write. A map is PAINTED against that tileset name
# here and READ back by it in the engine, so a second copy of the spelling
# would be collision the player cannot feel -- no error, no warning, just
# walls that are not there.
#
# A map without the tileset is GIVEN one by the stroke that needs it -- see
# `CollisionTilesetOffer` -- appended above every gid range the map already
# uses, so it changes the meaning of no gid that already exists.

#: Where the offer proposes the mask sheet. Written into the tmx and therefore
#: RELATIVE TO THE .tmx, which is what Tiled and the engine both resolve an
#: `<image source>` against, and spelled with forward slashes because a
#: backslash here is a path that only opens on Windows.
COLLISION_IMAGE = "../graphics/tilesets/System/Collision.png"


def write_mask_sheet(path: str, tile_width: int, tile_height: int) -> bool:
    """Put the mask sheet on disk. CREATE-ONLY-IF-ABSENT, never overwrite.

    Returns True when it wrote one and False when a file was already there.
    Being idempotent is what makes it safe inside an undoable gesture:
    undo/redo/undo can cycle without ever touching a sheet the author has
    since replaced with their own. Undo removes the `<tileset>` DECLARATION
    and leaves the file -- an unreferenced PNG is harmless, a map that raises
    `FileNotFoundError` at load is not.

    Raises OSError when it cannot write, because `QImage.save` returns False
    and raises nothing: an unchecked call reports success and leaves a
    tileset declared over an image that is not there.

    Tile N of the sheet IS mask N -- a mask is stored as `first_gid + mask`
    -- so the glyphs are laid out in `MASK_DOMAIN` order. Nothing reads these
    pixels; they are drawn so the sheet is legible to whoever opens it in
    Tiled.
    """
    if os.path.exists(path):
        return False
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    image = QImage(tile_width * len(MASK_DOMAIN), tile_height,
                   QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    glyphs = glyph_pixmaps(tile_width, tile_height)
    try:
        for index, mask in enumerate(MASK_DOMAIN):
            glyph = glyphs.get(mask)
            if glyph is not None:
                painter.drawPixmap(index * tile_width, 0, glyph)
    finally:
        # An open QPainter holds the QImage's buffer; save() while it is
        # live writes a half-flushed file on some platforms and warns on
        # all of them.
        painter.end()
    if not image.save(path, "PNG"):
        raise OSError(f"could not write the collision mask sheet to {path}")
    return True


INHERITED_OPACITY: float = 0.45
"""How solid the tile-mode mask overlay is drawn.

Dimmer than the collision-mode readout because it sits ON TOP of
the art an author is placing: it has to be legible without hiding
the tile it describes.
"""


@dataclass(frozen=True)
class CollisionTilesetOffer:
    """What declaring a `collision` tileset on one map would write.

    Plain data, Qt-free once built, and derived without a window, so the
    decision is checkable headlessly. `TilesetImport` is the same shape.

    The sheet's PIXELS are provisioned rather than asked for. pytmx opens
    every `<image source>` it parses and `pygame.image.load` raises
    FileNotFoundError, which stops the whole map loading, so the file has to
    EXIST at the declared size -- but nothing reads what is on it: the editor
    renders masks from `collision_view.glyph_pixmaps`, a companion layer
    declares `pyoneer_renders=false` so `rebuild()` skips it, and the engine
    reads numbers. Writing it costs the document nothing, because the tmx
    bytes `map.tileset.add` produces are identical either way and undo
    removes only the declaration.
    """

    name: str
    image: str                  # as written into the .tmx
    absolute: str               # where that resolves on this machine
    tile_width: int
    tile_height: int
    image_width: int
    image_height: int
    columns: int
    rows: int
    tile_count: int
    exists: bool                # on disk AND readable; see the reader below

    @property
    def sufficient(self) -> bool:
        """Can this grid hold every mask?

        A mask is stored as `first_gid + mask`, so tile N of this sheet IS
        mask N. A sheet with fewer than seventeen tiles leaves the high masks
        -- including STAR, "defer to the layer below" -- pointing past its
        end, where pytmx resolves them to whatever tileset comes next.
        """
        return self.tile_count >= len(MASK_DOMAIN)

    def command_args(self) -> dict[str, Any]:
        """Arguments for `map.tileset.add`.

        `image_width` and `image_height` are handed over EXPLICITLY:
        `MapDocument.add_tileset` reads the PNG header when they are absent
        and raises when the file is not there, and the file is usually not
        there yet when this offer is made.
        """
        return {
            "name": self.name,
            "image": self.image,
            "tile_width": self.tile_width,
            "tile_height": self.tile_height,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "columns": self.columns,
            "tile_count": self.tile_count,
        }

    def grid(self) -> str:
        """One line naming the cut, the way the import dialog does."""
        return (f"{self.image_width}x{self.image_height} -> {self.columns} "
                f"columns x {self.rows} rows = {self.tile_count} tiles")


def _EMPTY_READER(_x: int, _y: int) -> int:                       # noqa: N802
    """Every cell empty -- what a companion layer that does not exist yet
    holds. A `Stroke` needs a reader to drop no-op edits against, and the
    honest answer for a layer about to be created is gid 0 everywhere."""
    return 0


@dataclass
class ObjectDrag:
    """One press-drag-release that is moving an object.

    ADDRESSED BY ID, never by holding the `MapObject`. A press emits
    `selected`, the window answers it with `refresh_all`, and `rebuild`
    calls `scene.clear()` -- so anything this held onto across the drag
    would be a wrapper around an element the next transaction could have
    replaced. An id is re-resolved through the document at commit, and a
    drag whose object is gone by then simply finds nothing.

    `moved` is what separates a CLICK from a DRAG that returned home. Both
    end where they started and neither writes a command; only the second
    one has anything to say about it.
    """

    layer: str
    object_id: int
    #: Where the object was when the press landed. The commit compares
    #: against this rather than re-reading, so a drag is one before/after
    #: pair even if something else touched the map mid-gesture.
    start_x: float
    start_y: float
    #: Where inside the object the cursor grabbed it. Without this an
    #: object jumps its own top-left corner under the cursor on the first
    #: pixel of travel.
    grab_dx: float
    grab_dy: float
    width: float
    height: float
    moved: bool = False

    def what(self) -> str:
        return f"object {self.object_id}"


@dataclass
class SelectedObject:
    """WHICH object the selection named, taken at the moment it was made.

    AN ID IS NOT AN IDENTITY HERE, and that is a measured fact rather than
    a worry. `MapDocument._release_object_id` ROLLS `nextobjectid` back
    when the id being removed is the one just handed out -- deliberately,
    because that is what makes add-then-remove byte-exact -- so ids are
    REUSED, and a selection re-resolved by id alone lands on a DIFFERENT
    object. Measured, in five real gestures: place two objects, select the
    second, Ctrl+Z, place a third. The third is handed the second's id,
    the canvas drew it selected, and Delete removed an object the author
    had never clicked, silently. #TAG:an_id_is_not_an_identity

    SO THE ELEMENT IS THE IDENTITY. `MapObject` is a wrapper around a live
    `<object>` element, and the element survives every edit that keeps the
    object -- a move, a rename, a property write, and the undo of any of
    them -- while `add_object` and `restore_object` both build a NEW one.
    That is the exact line this record has to draw, and it is why the card
    beside it is not a second opinion:

      * comparing POSITION would drop the selection every time the author
        nudged the selected object, which forgets more than it must;
      * comparing TYPE and NAME would not catch the reproduction at all --
        place a GamePlayer, undo, place another, and the type matches and
        both names are empty. Only the position differs.

    The card is what the canvas SAYS when the answer is no, so a dropped
    selection names the thing it dropped instead of vanishing quietly. It
    is refreshed whenever the element confirms the object is still the
    same one, so the sentence describes the object as it is now.

    Note the deliberate contrast with `ObjectDrag` just above, which holds
    an id and never a wrapper: a drag wants whatever answers to that id at
    commit, and this wants to know when that is somebody else.
    """

    layer: str
    object_id: int
    #: The live `<object>` element. Held STRONGLY on purpose: a removed
    #: element that stayed reachable is what makes `is` a sound test --
    #: a freed one could have its address handed to the element that
    #: replaced it.
    element: Any
    x: float
    y: float
    type: str
    name: str

    def describe(self) -> str:
        """The object as the author last saw it, for a status line."""
        what = self.name or self.type or "object"
        return f"{what} {self.object_id} at ({self.x:.0f}, {self.y:.0f})"

    def still(self, found) -> bool:
        """Is `found` the very object this record was taken from?"""
        return found.element is self.element

    def refresh(self, found) -> None:
        """Follow a legitimate edit of the same object."""
        self.x, self.y = found.x, found.y
        self.type, self.name = found.type, found.name


@dataclass(frozen=True)
class PaintUnit:
    """What ONE addressable cell is, right now, and where the number came
    from.

    Resolved in one place -- `MapCanvas.paint_unit` -- so that the displayed
    grid, the cell a click snaps to, the ghost, the bounds a stroke clips to
    and the mask that gets written cannot be reading five different numbers.

    `refusal` is the one thing this cannot resolve: a companion whose
    declaration cannot be read at all. It is carried rather than raised
    because this is consulted on every mouse move and every grid line, and an
    exception on that path takes the editor down over a property an author
    can fix in Tiled. The stroke is refused instead -- see
    `MapCanvas.collision_stroke_refusal`: nothing is written, and the reason
    is said out loud.
    """

    #: How many addressable cells one map TILE divides into, per axis.
    subcell: int
    #: Pixels per addressable cell. `tile size // subcell`, both axes.
    width: int
    height: int
    #: The companion the number was read off. None in tile mode, where a
    #: companion's resolution is none of a tile stroke's business.
    layer: str | None = None
    #: Why the declaration could not be read, if it could not be.
    refusal: str | None = None


class MapCanvas(QGraphicsView):
    """A depth-ordered, paintable view of one map."""

    status = Signal(str)
    picked_gid = Signal(int)
    picked_mask = Signal(int)          # alt/picker in collision mode
    selected = Signal(object)          # a Scope
    #: OPEN THIS OBJECT FOR EDITING -- a double-click, or `Edit…` on the
    #: object menu. The canvas knows which object was pointed at and
    #: nothing else; the window owns what "edit" opens. Typed `Scope`
    #: rather than `object` because this wire is new and there is no
    #: back-compatible caller to be lenient for: a connect that hands back
    #: the wrong shape should fail at the emit, not three frames later.
    edit_object_requested = Signal(Scope)

    def __init__(self, session, map_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.map_name = map_name
        self.active_layer: str | None = None
        self.tool = Tool.BRUSH
        self.stamp = Stamp.single(1)
        self.mode = EditMode.TILES
        self.mask = BLOCK_ALL          # the collision brush; see set_mask
        self.all_layers = False
        self.object_class = "GameEntity"
        self.hidden_layers: set[str] = set()
        self.selected_scope: Scope | None = None
        #: WHAT THAT SCOPE NAMED WHEN IT ARRIVED, or None when it names no
        #: object this canvas is willing to vouch for. The scope is the
        #: window's business and follows it exactly; this is the canvas's
        #: own answer to "and is that still the same object", which an id
        #: cannot give because ids are recycled -- see `SelectedObject`.
        #: EVERYTHING that draws, deletes or reports the selected object
        #: reads THIS and never the scope's id.
        self.__selected: SelectedObject | None = None
        #: Does dragging an object land it on the tile grid? DEFAULT TRUE,
        #: because placing already snaps -- `__click_object` creates at
        #: `column * tile_width` -- and a move that did not would put an
        #: object one pixel off a grid every other object in the map sits
        #: on, which is invisible until something lines up against it.
        #:
        #: A plain attribute, set from outside exactly as `grid_step` and
        #: `collision_subcell` are: the persistent home of a view
        #: preference is `editor.core.settings`, and this widget does not
        #: import it. ALT during the drag inverts it live -- see
        #: `__snapping`, which is where the one reason it cannot be read at
        #: press is written down.
        self.snap_objects = True
        self.show_grid = True
        #: How many paint cells apart the grid lines are drawn. A view
        #: preference, so it comes from `editor.core.settings` -- the one
        #: store -- and it can only ever SKIP boundaries, never invent
        #: them. See `paint.grid_lines`.
        self.grid_step = 1
        #: How many sub-cells per map tile a companion layer CREATED by the
        #: next collision stroke is given. An authoring preference, so it
        #: comes from `editor.core.settings` -- the same one store
        #: `grid_step` comes from -- and it reaches `paint_unit`, so the
        #: cell a click addresses before the companion exists is the cell
        #: the companion is about to hold.
        #:
        #: 1 by DEFAULT: measured on a 100x100 map, a 4x companion is 8.6x
        #: the file bytes and +271ms per companion at load. The author opts
        #: in, and an existing companion keeps whatever it declares -- there
        #: is no verb to re-scale one.
        self.collision_subcell = 1
        #: The brush footprint, in paint cells, for the tools that have one.
        #: Transient like `tool` and `stamp`, and not persisted: it is a
        #: moment-to-moment choice rather than a view preference.
        self.brush_size = 1
        #: The tileset this stroke will declare in front of its tiles, or
        #: None. Set at press by `provision_collision_tileset`, consumed by
        #: `__commit_collision`, and cleared either way -- so a gesture that
        #: never commits cannot leave a declaration queued for the next one.
        self.__pending_tileset: CollisionTilesetOffer | None = None
        #: Did this session's provisioning actually write the PNG? Carried
        #: so the commit can disclose it ONCE, in the same status line as
        #: the stroke, rather than as a second message about plumbing.
        self.__wrote_sheet = False

        # This canvas holds NO `confirm` seam and imports no QMessageBox: a
        # modal on the paint path blocks a headless check forever, and
        # `tools/check_collision_mount.py` asserts both facts structurally.

        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(28, 28, 32)))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        #: THE MENU SEAM, and the only reason it is an attribute. A check
        #: must never block on a modal (law 13) and `QMenu.exec` is one --
        #: which is why `_exec_menu` calls `popup` instead, and why a check
        #: replaces this to READ the menu a real right-click built rather
        #: than watch it flash past. Shared verbatim with `TilePalette`,
        #: which needs it for the same reason.
        self.popup_menu = _exec_menu

        self.atlas: TilesetAtlas | None = None
        self.__stroke: Stroke | None = None
        #: The object being dragged, or None. Lives beside `__stroke` and
        #: is dropped on the same beats: the two are the same shape of
        #: gesture over different material, and neither may survive into a
        #: mode where its commit would mean something else.
        self.__object_drag: ObjectDrag | None = None
        self.__terrain: _TerrainStroke | None = None
        self.__erasing = False
        self.__ghost: QGraphicsItemGroup | None = None
        self.__panning = False
        self.__pan_from = None
        self.__space = False
        self.__overlay: CollisionOverlay | None = None
        self.__overlay_geometry: tuple[int, int, int, int] | None = None
        self.__collision_stale = True
        self.__own_commit = False
        #: Level one, memoised: `(defaults, refusal)` or None for "not read
        #: yet". The only part of the collision stack that is cached, because
        #: it is the only part that lives in a file -- see
        #: `__tileset_defaults` for the key and why the rest is not cached.
        self.__level_one: tuple[tuple, str | None] | None = None
        #: Why the last stack BUILD came back empty, or None. Recorded rather
        #: than recomputed: reproducing it on the mouse-move path would mean
        #: snapshotting every layer's gids to find out.
        self.__stack_build_refusal: str | None = None

        # The overlay is kept current cell by cell as strokes commit, so it
        # has to be told when the document moved some OTHER way -- an undo, a
        # redo, an applied response, a command from a panel. The stream
        # announces every one of those, and without this the readout would
        # disagree with the map after the first Ctrl+Z.
        self.session.stream.subscribe(self.__on_transaction)
        self.rebuild()

    def detach(self) -> None:
        """Stop hearing about transactions, before this canvas is dropped.

        `__init__` hands the command stream a BOUND METHOD of this object,
        and that is the one reference a Qt delete does not take back: the
        stream keeps the bound method, the bound method keeps this canvas,
        and every listener on that list is called for every command for the
        rest of the session. So a window that swaps canvases -- one per map
        switch -- keeps every canvas it ever built, re-announces each
        command to all of them, and marks the overlay of a map nobody is
        looking at stale, on a list that only ever grows.

        IDEMPOTENT, and deliberately: a caller that has to remember whether
        it already detached is a caller that will get it wrong on the path
        that matters. Removing what is not there is fine; leaving what IS
        there is the bug, which is why this loops rather than assuming one.
        """
        listeners = self.session.stream.listeners
        while self.__on_transaction in listeners:
            listeners.remove(self.__on_transaction)

    # -- document ----------------------------------------------------------

    @property
    def document(self):
        return self.session.project.map(self.map_name)

    @property
    def tile_width(self) -> int:
        return self.document.tile_width

    @property
    def tile_height(self) -> int:
        return self.document.tile_height

    # -- the paint unit ----------------------------------------------------
    #
    # TWO SIZES, NEVER ONE. Everything that means "an addressable CELL" reads
    # `paint_width` / `paint_height`, and everything that means "the size of a
    # tile's ART" -- the atlas, the tile ghost, the terrain ghost, an object's
    # default box -- reads `tile_width` / `tile_height`. They differ whenever
    # the layer being painted declares `pyoneer_subcell`: a companion at "4"
    # stores four masks per tile per axis, so a canvas that addressed whole
    # tiles there would drop each mask up to 1,188px from the cursor on a
    # 100x100 map.

    def paint_unit(self) -> PaintUnit:
        """One addressable cell, resolved from the LAYER BEING PAINTED.

        `mode.subdivides` picks WHICH layer that is -- in collision mode the
        companion this stroke would write into, in tile mode the active layer
        itself, which may well be a companion the author selected in the
        Layers panel and is painting masks onto directly.

        HOW FINELY is then the map's business: `pyoneer_subcell` on that
        layer, a FILE FORMAT string read through the engine's own
        `companion_subcell` rather than re-spelled here, so the cell the
        editor addresses is the cell the runtime bakes. A layer with no
        declaration answers 1, so an art layer is unaffected.

        A companion that does not exist yet resolves to the resolution this
        canvas would CREATE it at -- `collision_subcell`, the author's
        preference -- and not to 1, or the first stroke on a fresh map would
        address a whole tile while the layer created to hold it stored
        sixteen masks per tile.
        """
        document = self.document
        tile_w, tile_h = document.tile_width, document.tile_height
        name = (self.companion_name() if self.mode.subdivides
                else self.active_layer)
        subcell, refusal = self.__declared_subcell(name)
        return PaintUnit(subcell, tile_w // subcell, tile_h // subcell,
                         layer=name, refusal=refusal)

    def __declared_subcell(self, name: str | None) -> tuple[int, str | None]:
        """(resolution, why it could not be read) for one companion layer.

        The ONE read of `pyoneer_subcell` on this class. `paint_unit` and
        `overlay_subcell` both come through here, so the cell a click lands
        in and the cell the readout draws are the same cell by construction.

        An absent property means 1, the file format's default, decided at
        `SUBCELL` in `scripts/core/collision_runtime.py`.

        A layer that does not exist yet is two questions in one shape. If it
        is the COMPANION this canvas would create, the answer is
        `__pending_subcell` -- `map.layer.add` takes a resolution, so the
        click has to address the cell that layer is about to hold. Anything
        else (no active layer, an object layer, an unknown name) is 1.

        The error is RETURNED rather than raised because this is consulted on
        every mouse move and every grid line; see `PaintUnit.refusal`.
        """
        document = self.document
        if name is None or name not in document.tile_layer_names():
            if name is not None and name == self.companion_name():
                return self.__pending_subcell()
            return 1, None
        try:
            return companion_subcell(document, name), None
        except PyoneerError as exc:
            return 1, str(exc)

    def __pending_subcell(self) -> tuple[int, str | None]:
        """(resolution, why not) for the companion the next stroke CREATES.

        `collision_subcell` is a PREFERENCE and the map is a FACT; the two
        are reconciled here into the same `(value, refusal)` pair
        `__declared_subcell` returns for a companion that already exists, so
        `paint_unit` cannot tell the two cases apart.

        The refusal restates `companion_subcell`'s own rule, because that
        reader needs a LAYER and this runs before one exists;
        `tools/check_collision_mount.py` asserts both sides agree. A factor
        the map cannot hold draws at 1x and REFUSES to write rather than
        falling back, the same as an unreadable declaration one branch up.
        """
        document = self.document
        wanted = int(self.collision_subcell)
        if wanted < 1:
            return 1, (f"the collision resolution is set to {wanted} "
                       f"sub-cells per tile; it is 1 or more (1 means one "
                       f"mask per map tile)")
        if document.tile_width % wanted or document.tile_height % wanted:
            return 1, (f"the collision resolution is set to {wanted} "
                       f"sub-cells per tile, but this map's tiles are "
                       f"{document.tile_width}x{document.tile_height}px and "
                       f"{wanted} does not divide them evenly; a sub-cell "
                       f"has to land on whole pixels")
        return wanted, None

    @property
    def paint_subcell(self) -> int:
        """How many addressable cells one map tile divides into, per axis."""
        return self.paint_unit().subcell

    @property
    def paint_width(self) -> int:
        """Pixels per addressable cell, horizontally."""
        return self.paint_unit().width

    @property
    def paint_height(self) -> int:
        """Pixels per addressable cell, vertically."""
        return self.paint_unit().height

    def cell_at(self, scene_x: float, scene_y: float) -> tuple[int, int]:
        # Floor division, not int(): int(-0.5) is 0, which puts the cell one
        # to the right of where the cursor actually is on the left edge.
        unit = self.paint_unit()
        return (int(scene_x // unit.width), int(scene_y // unit.height))

    def __footprint(self, stamp: Stamp | None = None):
        """The stamp this press should place, and where it sits.

        The gate is `self.tool.uses_size` -- the SELECTED tool, not the
        effective one. A right-drag substitutes the eraser, which does take a
        footprint, but the toolbar's size control is lit for what is
        selected, and a greyed control must not still size a right-drag.
        """
        size = self.brush_size if self.tool.uses_size else 1
        return footprint(self.stamp if stamp is None else stamp, size)

    def __active_tile_layer(self):
        if self.active_layer is None:
            return None
        document = self.document
        if self.active_layer not in document.tile_layer_names():
            return None
        return document.tile_layer(self.active_layer)

    # -- collision addressing ----------------------------------------------

    @property
    def collision_first_gid(self) -> int | None:
        """The firstgid masks are stored relative to, or None if this map has
        no collision tileset. Everything collision-shaped checks this first,
        because without it a mask cannot be encoded OR decoded.

        The engine's own function, called rather than mirrored: this canvas
        WRITES the gids that function READS.
        """
        return engine_collision_first_gid(self.document)

    def collision_tileset_offer(self) -> CollisionTilesetOffer:
        """What declaring the mask tileset on THIS map would write.

        The geometry comes from `tileset_geometry`, the same function
        `MapDocument.add_tileset` uses to write `columns` and `tilecount`, so
        what the offer describes and what the file records cannot disagree
        once margins exist.

        A sheet already on disk is MEASURED rather than assumed, since the
        author may have supplied one of their own shape. One that is present
        but undecodable counts as absent.
        """
        document = self.document
        directory = os.path.dirname(document.path or "")
        absolute = (os.path.normpath(os.path.join(directory, COLLISION_IMAGE))
                    if directory else COLLISION_IMAGE)
        tile_width, tile_height = document.tile_width, document.tile_height

        image = QImage(absolute) if os.path.isfile(absolute) else QImage()
        exists = not image.isNull()
        width = image.width() if exists else tile_width * len(MASK_DOMAIN)
        height = image.height() if exists else tile_height

        columns, rows, count = tileset_geometry(
            width, height, tile_width, tile_height, 0, 0)
        return CollisionTilesetOffer(
            name=COLLISION_TILESET, image=COLLISION_IMAGE, absolute=absolute,
            tile_width=tile_width, tile_height=tile_height,
            image_width=width, image_height=height,
            columns=columns, rows=rows, tile_count=count, exists=exists)

    def collision_tileset_ref(self):
        """The `<tileset>` masks are stored in, as a ref, or None.

        Found BY THE FIRSTGID the engine answered with rather than by
        re-spelling "the tileset called collision, case-insensitively".
        That predicate lives in `scripts/core/collision_runtime.py` and
        nowhere else; a second spelling here is how the canvas and the
        engine come to disagree about which tileset a mask means, which the
        author only ever meets as a wall that is not there.
        """
        first_gid = self.collision_first_gid
        if first_gid is None:
            return None
        for ref in self.document.tilesets():
            if ref.first_gid == first_gid:
                return ref
        return None

    def provision_collision_tileset(self) -> CollisionTilesetOffer | None:
        """Get the mask sheet onto disk, and say what to declare for it.

        Returns the offer for `__commit_collision` to prepend, or None
        having emitted ONE status line saying why the stroke was refused.
        No dialog, no question, nothing to dismiss: every outcome here is
        either "carry on painting" or "refuse the gesture, say why in one
        line, change nothing".

        This does not touch the document: writing an asset is not a document
        change. The DECLARATION is, and stays in the command stream with an
        exact inverse, in the same transaction as the tiles it exists for.

        Two of the three refusals below are about a sheet the AUTHOR
        supplied; never overwrite one to make it fit.
        """
        offer = self.collision_tileset_offer()
        if not offer.sufficient:
            # Only reachable for a sheet already on disk: an absent one is
            # sized from MASK_DOMAIN and is sufficient by construction.
            self.status.emit(
                f"the collision sheet at {offer.absolute} is too small — "
                f"{offer.grid()}, and a mask sheet needs {len(MASK_DOMAIN)}. "
                f"Delete it and paint again to have one made")
            return None
        try:
            wrote = write_mask_sheet(offer.absolute, offer.tile_width,
                                     offer.tile_height)
        except OSError as exc:
            # The absolute path first and always: the cause varies, and a
            # refused `QImage.save` carries no path at all, so this is the
            # only place the author learns where the write was attempted.
            self.status.emit(
                f"could not write the collision sheet at {offer.absolute} "
                f"({exc}) — nothing was changed")
            return None
        self.__wrote_sheet = wrote
        return offer

    def companion_name(self, layer_name: str | None = None) -> str | None:
        """Which layer holds `layer_name`'s masks.

        The layer's own `pyoneer_passability` declaration if it has one --
        two art layers may legitimately point at one companion -- otherwise
        the name this canvas would create. Returning the would-be name rather
        than None is what lets one stroke both create the companion and paint
        into it.

        The answer comes from the engine's `companion_name`, so the layer
        this stroke paints into is the layer the game reads the masks out of.
        None means the question does not apply: no active layer, or a name
        this map does not have.
        """
        name = layer_name if layer_name is not None else self.active_layer
        if name is None or name not in self.document.tile_layer_names():
            return None
        return engine_companion_name(self.document, name)

    def companion_layer(self, layer_name: str | None = None):
        """The companion as a TileLayer, or None when it does not exist yet."""
        document = self.document
        name = self.companion_name(layer_name)
        if not name or name not in document.tile_layer_names():
            return None
        return document.tile_layer(name)

    def collision_stroke_refusal(self) -> str | None:
        """Why a collision stroke cannot be PLACED right now, or None.

        THE GUARD. A mask is only meaningful at the resolution its companion
        declares, and the cell a click resolved to came from `paint_unit`. If
        those two numbers disagree, every cell of the stroke is written at
        the right index into the wrong grid -- which reads as collision that
        is slightly off, found by walking into a wall that is not there.

        So this reads the declaration a SECOND time, straight off the
        document, and compares: a guard that consulted `paint_unit` would be
        asserting `x == x`. When the two agree it is unreachable, which is
        why it is a status line rather than an exception -- the next person
        to touch `paint_width` gets a refusal naming both numbers instead of
        a misplaced wall.

        Never write a mask you cannot place, and never ask about it in a
        dialog: this sits on the paint path, where `editor/ui/ask.py` is the
        only seam allowed to be modal.
        """
        unit = self.paint_unit()
        if unit.refusal is not None:
            return (f"{unit.refusal} — refusing the stroke rather than "
                    f"writing a mask at a resolution nobody agrees on")
        name = self.companion_name()
        document = self.document
        if name is None or name not in document.tile_layer_names():
            # There is nothing to disagree with yet: the companion this
            # stroke CREATES is created at `paint_unit`'s own resolution --
            # `__commit_collision` passes that very number to
            # `map.layer.add` -- so the two cannot diverge here by
            # construction. A resolution the map cannot hold at all is
            # already refused above, through `unit.refusal`.
            return None
        declared = companion_subcell(document, name)      # cannot raise: see above
        if declared == unit.subcell:
            return None
        # The worst cell on THIS map. Cell i is written at i x the companion's
        # cell size and was clicked at i x the paint unit, so the two diverge
        # by i x the difference, bounded by whichever grid runs out first.
        # Both cells are square -- `companion_subcell` refuses a subcell the
        # tile size does not divide -- so one axis tells the whole story.
        cell_px = document.tile_width // declared
        last = min(document.width * unit.subcell,
                   document.width * declared) - 1
        drift = last * abs(unit.width - cell_px)
        return (f"refusing this collision stroke: a click here addresses a "
                f"{unit.width}x{unit.height}px cell ({unit.subcell} per tile) "
                f"but {name!r} declares {SUBCELL}={declared}, which is "
                f"{cell_px}x{document.tile_height // declared}px — a mask "
                f"would land up to {drift}px from the cursor")

    def collision_stack(self, subcell: int | None = None) -> list[CollisionLayer]:
        """The map's collision stack, TOPMOST FIRST -- THE ENGINE'S OWN.

        `collision_layers`, called and not mirrored, so membership, order,
        resolution and the levels themselves are the same answer the player
        will walk into. Anything this canvas decided for itself would show
        the author one stack while the game ran another.

        `subcell` is the resolution the STACK is read at, defaulting to the
        finest any of its members declares -- `field_subcell`, the same
        function `field_from_map` calls, so a stack resolved here and a field
        baked there index the same cells. `collision_layers` scales every
        member into it, which is what keeps a 1x companion on a mixed map
        drawn over its own map tile.

        Rebuilt whenever it is consulted rather than cached: a member costs
        one flat snapshot of its layer's gids (`document_gid_reader`), 0.78 ms
        for a whole stack over a 400x400 companion, against the 6.9 ms rebuild
        every command already pays. Level one is the one memoised part, keyed
        on a document change -- see `__tileset_defaults`.
        """
        return self.__collision_stack(subcell)[0]

    def __collision_stack(self, subcell: int | None = None
                          ) -> tuple[list[CollisionLayer], str | None]:
        """(the stack, why it is empty) -- the raising call, made safe.

        `collision_layers` RAISES on a map it cannot read, which is right for
        the engine. A canvas cannot: this sits under `rebuild`, under a mouse
        move and under a stroke's own commit, and an exception on any of the
        three takes the editor down over a map the author opened to repair.

        So the refusal is CARRIED, never swallowed, and the resolved view
        goes DARK rather than degrading. The map is still drawn, the
        single-layer collision view still works and the brush still paints;
        it is only the all-layers view, whose whole claim is "this is what
        the player will feel", that goes empty -- on a map the engine refuses
        there is no field, so every cell it could draw would be invented.
        """
        if subcell is None:
            subcell = self.stack_subcell()
        defaults, refusal = self.__tileset_defaults()
        if refusal is not None:
            return [], refusal
        try:
            return collision_layers(self.document, subcell=subcell,
                                    defaults=defaults), None
        except PyoneerError as exc:
            self.__stack_build_refusal = (
                f"the resolved view is empty because this map's collision "
                f"stack cannot be built: {exc}")
            return [], self.__stack_build_refusal

    def __tileset_defaults(self):
        """(level one for this map, why it could not be read).

        MEMOISED, unlike everything else the stack is made of, because this
        is the one level that lives in a FILE: `stack_refusal` is consulted on
        every mouse move, and parsing a `.blitmask` per pixel of travel buys
        an answer that can only change when the document does. Cleared by
        `rebuild` and by every transaction, which between them cover every way
        a `<tileset>`'s `pyoneer_collision` can appear, change or go; a
        sidecar edited on disk behind the editor's back is stale until the
        next command, exactly as `TilesetAtlas`'s art is.

        MISSING IS NOT AN ERROR AND UNREADABLE IS. A tileset that declares no
        masks contributes none and says nothing. One that declares a
        `.blitmask` which is absent, mis-shaped or names another sheet makes
        `tileset_defaults` raise -- and the engine raises on the same map at
        load, so the refusal carries that fact to the author rather than
        letting the overlay imply the map is fine.
        """
        if self.__level_one is None:
            try:
                self.__level_one = (tuple(tileset_defaults(self.document)), None)
            except PyoneerError as exc:
                self.__level_one = ((), f"this map's tileset masks could not "
                                        f"be read: {exc}")
        return self.__level_one

    def stack_subcell(self) -> int:
        """The finest resolution any companion on this map declares.

        `field_subcell`, the engine's own function, so the overlay's
        all-layers view is drawn at exactly the resolution `field_from_map`
        bakes at. Named apart from it because the canvas has two resolutions:
        this one is about the whole STACK, `paint_unit` about the one
        companion a stroke writes into.

        `field_subcell` raises on a stack whose declarations do not nest.
        That raise is caught -- this is consulted from `rebuild` -- but not
        swallowed: `stack_refusal` is the other half, and the readout says it
        out loud.
        """
        return self.__field_subcell()[0]

    def stack_refusal(self) -> str | None:
        """Why the resolved view cannot be trusted on this map, or None.

        `stack_subcell` degrades to 1 on a map the ENGINE refuses to load, so
        that a broken map can still be drawn and fixed. This is the other
        half: the reason is carried out to where the author is looking -- the
        cell readout under the cursor, and the moment All layers is switched
        on -- rather than leaving a plausible 1x picture unexplained.
        Reported, never raised; this sits on the same mouse move
        `paint_unit` does.

        THREE WAYS TO BE UNREADABLE, in the order they are cheap to know:
        a `pyoneer_subcell` the map cannot honour, a `.blitmask` a tileset
        declares and this map cannot open, and anything else that made
        `collision_layers` refuse the stack. The first two are answered from
        state that is already computed or memoised, which is what lets this
        be called on every mouse move; the third is recorded by the build
        that hit it, because reproducing it here would mean snapshotting
        every layer's gids to find out.
        """
        return (self.__field_subcell()[1] or self.__tileset_defaults()[1]
                or self.__stack_build_refusal)

    def __field_subcell(self) -> tuple[int, str | None]:
        """(the stack's resolution, why it could not be read).

        The ONE read of `field_subcell` on this class, in the same
        `(value, refusal)` shape `__declared_subcell` uses for one companion,
        so `stack_subcell` and `stack_refusal` are two halves of one answer
        rather than two functions that have to agree about when to raise.
        """
        try:
            return field_subcell(self.document), None
        except PyoneerError as exc:
            return 1, f"the readout is drawn at 1x cells: {exc}"

    def overlay_subcell(self) -> int:
        """The resolution the READOUT is drawn at.

        Not always `paint_unit`'s: the all-layers view resolves every
        collision layer into the one answer the player will feel, and that
        answer only exists at the finest resolution in the stack. An author
        painting a 1x layer on a map that also carries a 4x one paints whole
        tiles and READS quarter-tiles, which is what the game does with the
        same two layers.

        Otherwise it is the active companion's own resolution, read through
        `__declared_subcell` rather than from `paint_unit` -- which answers 1
        in TILE mode, and re-sizing a scene-sized pixmap on a mode switch
        would bake for a change in what is painted, not in what is shown.
        """
        if self.all_layers:
            return self.stack_subcell()
        return self.__declared_subcell(self.companion_name())[0]

    # -- building ----------------------------------------------------------

    def __depth_of(self, name: str) -> int:
        """How high a layer DRAWS in this scene.

        The genre pack first, because that is the editor's authored contract
        with the author, then the ENGINE's table for anything the pack does
        not declare -- so a layer only the renderer ranks (`ENTITY_1`,
        `FOREGROUND_2`, `UI_LAYER_1`) sorts here where it sorts there.

        DRAWING ONLY. Collision order is the engine's, through
        `collision_layers`, which never reads a genre pack.
        `tools/check_collision_runtime.py` asserts the two tables agree
        wherever both rank a name, so the pixels and the walls stay in the
        same order.
        """
        declared = self.session.project.genre.layer(name)
        if declared is not None:
            return declared.depth
        return depth_for_layer_name(name)

    def rebuild(self) -> None:
        # Level one is re-read from here down, for `TilesetAtlas`'s reason
        # and on the same beat: a rebuild is what follows every document
        # change this canvas is told about, and a `<tileset>` declaration is
        # a document change. See `__tileset_defaults`.
        self.__refresh_level_one()
        scene = self.scene()
        # scene.clear() DELETES what it holds, C++ side and all, and the
        # overlay is meant to outlive a rebuild. removeItem hands ownership
        # back to us; clearing while it is attached would leave a live Python
        # wrapper around freed memory, which is a crash and not an exception.
        self.__detach_overlay()
        scene.clear()
        self.__ghost = None

        try:
            document = self.document
        except Exception as exc:                                # noqa: BLE001
            scene.addText(f"map unreadable: {exc}")
            return

        # BEFORE a single object is drawn from this document, and against
        # the document just read: is the selection still what it was? Said
        # out loud at the very END of this method, where the scene is
        # whole -- the sentence travels down instead of the emit travelling
        # up, because telling the window here would re-enter `rebuild`
        # halfway through building the scene it is standing in.
        lost = self.__revalidate_selection(document)

        self.atlas = TilesetAtlas(document,
                                  tile_width=document.tile_width,
                                  tile_height=document.tile_height)
        width = document.width * document.tile_width
        height = document.height * document.tile_height
        scene.setSceneRect(0, 0, width, height)

        depth_of = self.__depth_of
        for name in sorted(document.tile_layer_names(), key=depth_of):
            layer = document.tile_layer(name)
            # A data layer -- passability, region ids, spawn weights -- says
            # so with pyoneer_renders=false, and the engine already skips it.
            # Drawing its gids as art puts confetti over the map and hides
            # the thing the author is actually editing.
            if name in self.hidden_layers or not read_profile(layer).renders:
                continue
            item = QGraphicsPixmapItem(render_layer(layer, self.atlas))
            item.setZValue(depth_of(name))
            item.setTransformationMode(Qt.FastTransformation)
            # The layer being painted stays fully opaque; everything above it
            # fades, so you can see what you are doing without hiding context.
            if self.active_layer and depth_of(name) > depth_of(self.active_layer):
                item.setOpacity(0.35)
            scene.addItem(item)

        for name in document.object_layer_names():
            if name in self.hidden_layers:
                continue
            self.__draw_objects(scene, document.object_layer(name),
                                depth_of(name) + 0.5, name)

        self.__draw_grid(scene, document, width, height)
        self.__mount_overlay()

        if self.atlas.missing:
            self.status.emit(
                f"no tileset art for {', '.join(self.atlas.missing)} — "
                f"drawing colour swatches (docs/ASSETS.md)")

        if lost:
            # The window is told FIRST and the sentence said second, so the
            # sentence survives the rebuild that answering this emit runs.
            # Told at all because `Selection.select` de-duplicates: a window
            # left pointing at the dead id would swallow the author's next
            # click on the object that inherited it, and its inspector would
            # be filling in a form for an object nothing here is selecting.
            if self.selected_scope is not None:
                parent = self.selected_scope.parent()
                if parent is not None:
                    self.selected_scope = parent
                    self.selected.emit(parent)
            self.status.emit(lost)

    def __draw_objects(self, scene, layer, z: float, layer_name: str) -> None:
        # THE CARD, never the scope's id: an id that has been recycled
        # still resolves, and drawing the highlight from it is how an
        # author ends up looking at an object they never clicked.
        selected_id = None
        if self.__selected is not None and self.__selected.layer == layer_name:
            selected_id = self.__selected.object_id
        for obj in layer.objects():
            width = obj.width or self.tile_width
            height = obj.height or self.tile_height
            is_selected = obj.id == selected_id
            colour = _OBJECT_SELECTED if is_selected else _OBJECT_PEN
            rect = QGraphicsRectItem(QRectF(obj.x, obj.y, width, height))
            rect.setPen(QPen(colour, 2.5 if is_selected else 1.5))
            rect.setBrush(QBrush(QColor(colour.red(), colour.green(),
                                        colour.blue(), 60 if is_selected else 30)))
            rect.setZValue(z + (0.1 if is_selected else 0))
            scene.addItem(rect)
            label = QGraphicsSimpleTextItem(obj.name or obj.type or str(obj.id))
            label.setBrush(QBrush(QColor(240, 240, 240)))
            # Scale the label back so zoom does not turn it into a billboard.
            label.setFlag(QGraphicsSimpleTextItem.ItemIgnoresTransformations)
            label.setPos(obj.x, obj.y - 14)
            label.setZValue(z + 0.2)
            scene.addItem(label)

    def set_background(self, colour) -> None:
        if colour is not None:
            self.setBackgroundBrush(QBrush(colour))

    def __draw_grid(self, scene, document, width: int, height: int) -> None:
        """Cell boundaries, every `grid_step` of them.

        Drawn in PAINT cells rather than in tiles, and only on boundaries
        that exist -- `grid_lines` returns a subset of the real ones, so a
        coarser grid hides lines and can never invent them: every line the
        author sees is somewhere a click can land.

        The unit is read ONCE into a local, both because `paint_unit` reaches
        the document (a 100x100 map at 4x is 401 lines per axis) and because
        one number for the whole grid is what makes that promise hold.
        """
        if not self.show_grid:
            return
        pen = QPen(_GRID_PEN)
        pen.setCosmetic(True)
        # Not clamped here. `EditorSettings` validates the stored value
        # against its own choices and falls back if it is nonsense -- a
        # corrupt preference must not stop the editor booting -- so a bad
        # step arriving at the canvas means a CALLER set it, and
        # `grid_lines` raising is the right way to find that out.
        step = self.grid_step
        unit = self.paint_unit()
        columns = width // unit.width
        rows = height // unit.height
        for column in grid_lines(columns, step):
            x = column * unit.width
            scene.addLine(x, 0, x, height, pen).setZValue(1000)
        for row in grid_lines(rows, step):
            y = row * unit.height
            scene.addLine(0, y, width, y, pen).setZValue(1000)

    def set_layer_visible(self, name: str, visible: bool) -> None:
        if visible:
            self.hidden_layers.discard(name)
        else:
            self.hidden_layers.add(name)
        self.rebuild()

    def set_active_layer(self, name: str | None) -> None:
        self.active_layer = name
        # A different layer means a different companion, so the readout is
        # about to be about something else.
        self.__collision_stale = True
        self.rebuild()

    def set_selection(self, scope: Scope) -> None:
        """Point at what the window is pointing at, and note WHAT that is.

        The card is taken only when the scope CHANGES. A repeat of the
        same scope is what `refresh_all` sends after every single command,
        and re-identifying there is exactly the defect: the canvas would
        adopt whatever now answers to that id -- including the object a
        recycled id has just been handed to.
        """
        if scope != self.selected_scope:
            self.__selected = self.__identify(scope)
        self.selected_scope = scope
        self.rebuild()

    def focus_object(self, scope) -> bool:
        """Centre the view on one object and select it. THE HIERARCHY'S DOOR.

        `self.window().canvas.focus_object(scope)` is what a tree row calls
        when the author picks an object out of the hierarchy: the row knows
        an address and nothing else, and where that address sits on screen
        is the canvas's business.

        SELECTED THROUGH THE SAME PATH A CLICK USES -- the `selected`
        signal, carrying `object_scope`'s one spelling -- and never by
        writing the card here. Two ways of setting a selection is the
        defect this contract exists to avoid: the canvas would draw one
        object highlighted while the window's inspector filled in a form
        for another, and neither surface could tell which of them was
        wrong. Going out and coming back costs one rebuild and buys a card
        built by exactly the code a click builds it with.

        RETURNS FALSE, and does not raise, when the scope names nothing
        this canvas can show. A tree row is drawn from a document the
        author can undo out from under it, so a row naming an id that is
        gone is a normal race and not a contract violation -- and nothing
        is centred or selected in that case, because a view that scrolled
        somewhere for a missing object would be saying the object is
        there.
        """
        layer_name, found = self.__resolve_object(scope)
        if found is None:
            return False
        width = found.width or self.tile_width
        height = found.height or self.tile_height
        # The object's CENTRE, not its corner: centring the corner puts
        # half of a large object off the edge it was scrolled to.
        self.centerOn(found.x + width / 2.0, found.y + height / 2.0)
        self.selected.emit(self.object_scope(layer_name, found.id))
        return True

    def __identify(self, scope) -> SelectedObject | None:
        """The card for an object scope, or None when it names none HERE."""
        layer_name, found = self.__resolve_object(scope)
        if found is None:
            return None
        return SelectedObject(layer=layer_name, object_id=found.id,
                              element=found.element, x=found.x, y=found.y,
                              type=found.type, name=found.name)

    def __resolve_object(self, scope) -> tuple[str | None, Any]:
        """(layer, object) for a scope naming an object on THIS map.

        (None, None) for: no scope, a scope that is not an object, an
        object on another map, a layer this map does not have, an
        unreadable object segment, and an id the layer does not hold.

        THE ONE PLACE a scope becomes an object on this class. The card
        `set_selection` takes and the object `focus_object` scrolls to are
        resolved by this same rule, so a scope one of them refuses cannot
        be a scope the other quietly accepts.
        """
        if scope is None or scope.kind != "object":
            return None, None
        if scope.get("map") != self.map_name:
            return None, None
        layer_name = scope.get("layer")
        document = self.document
        if layer_name is None or layer_name not in document.object_layer_names():
            return None, None
        try:
            object_id = int(scope.require("object"))
        except (ValueError, TypeError):
            return None, None
        return layer_name, document.object_layer(layer_name).find(object_id)

    def __revalidate_selection(self, document) -> str:
        """Is the selected object still the one that was selected?

        CALLED FROM `rebuild`, which is what follows every document change
        this canvas is told about -- so an undo, a redo and a sibling
        panel's edit all arrive here, and none of them has to remember to.

        Returns the sentence to say when the answer is no, or "" when
        there is nothing to say. It DROPS the card rather than the scope's
        contents: the scope is the window's, and `rebuild` hands the
        window a new one afterwards, once the scene is whole again.

        Deliberately NOT "clear the selection whenever the document
        changes". Painting a tile must not cost the author the object they
        had selected; only the object ceasing to be that object may.
        """
        record = self.__selected
        if record is None:
            return ""
        found = None
        if record.layer in document.object_layer_names():
            found = document.object_layer(record.layer).find(record.object_id)
        if found is None:
            self.__selected = None
            return (f"{record.describe()} is gone — nothing is selected now")
        if not record.still(found):
            # THE DANGEROUS ONE. The id resolves, so every by-id path
            # would carry on happily; it just resolves to somebody else.
            self.__selected = None
            return (f"object {record.object_id} is not {record.describe()} "
                    f"any more — nothing is selected now")
        # The same object, wherever it has been moved or renamed to.
        record.refresh(found)
        return ""

    # -- the collision overlay ---------------------------------------------

    @property
    def overlay(self) -> CollisionOverlay | None:
        """The collision readout, once a rebuild has had a document to size
        it against. Exposed so a panel can read `mask_at`/`describe` rather
        than re-deriving what is already rendered."""
        return self.__overlay

    def set_mode(self, mode: EditMode) -> None:
        """Switch what a stroke acts on. Same tools, same keys, other layer."""
        if mode is self.mode:
            return
        self.mode = mode
        # A mode change mid-drag would commit a stroke into the layer the
        # other mode addresses. Dropping it is the honest outcome -- and the
        # queued declaration goes with it, or the NEXT stroke would carry a
        # `map.tileset.add` nobody asked for.
        self.__stroke = None
        self.__pending_tileset = None
        self.__wrote_sheet = False
        self.__terrain = None
        # Same reason, one layer over: collision mode has no object
        # gestures at all, so a drag begun in tile mode would commit a
        # `map.object.move` the author can no longer see the ghost of.
        self.__object_drag = None
        self.__clear_ghost()
        self.__collision_stale = True
        self.rebuild()
        self.status.emit(mode.tip)

    def set_all_layers(self, on: bool) -> None:
        """Resolve the whole stack instead of showing one layer's opinion.

        A re-bake is normally enough -- the same cells, a different answer in
        each. It is not enough when the two views are drawn at different
        RESOLUTIONS: a 1x active layer on a map that also carries a 4x one
        resolves at 4x, which is a different number of cells and a different
        pixmap, so the item is rebuilt rather than repainted.
        """
        if bool(on) == self.all_layers:
            return
        self.all_layers = bool(on)
        self.__collision_stale = True
        # Nothing else emits on this path, so a refusal said here survives to
        # be read. The cell readout repeats it on every move anyway, because
        # `set_mode` does emit its tip right after a rebuild.
        if self.all_layers:
            refusal = self.stack_refusal()
            if refusal is not None:
                self.status.emit(f"All layers cannot be trusted here: "
                                 f"{refusal}")
        if self.overlay_geometry() != self.__overlay_geometry:
            self.rebuild()
            return
        if self.mode is EditMode.COLLISION:
            self.__bake_overlay()

    def set_mask(self, mask: int) -> None:
        """The mask a collision stroke writes -- what `stamp` is to tiles."""
        self.mask = int(mask)

    # -- a mask on the TILE, not on the cell -------------------------------
    #
    # `EditMode.COLLISION` means "a click writes a mask instead of a tile",
    # in the PALETTE as well as on the map: picking a tile there gives that
    # TILE this mask, once, for everywhere it is ever stamped. The two-step
    # is the one the author already knows from cells -- pick the mask, then
    # pick what it applies to -- with the tileset standing in for the map.
    #
    # WHERE THE ANSWER SHOWS UP, AND WHERE IT DOES NOT.       #TAG:tile_mask_is_level_one
    # A tile's mask is LEVEL ONE. The single-layer readout draws one
    # companion's own gids -- level two -- so it cannot show a tile mask and
    # must not pretend to; the resolved All-layers view is where level one
    # lives, and `__on_transaction` marks the overlay stale for this
    # transaction like any other, so the next rebuild re-bakes it. The
    # single-layer case is not silently wrong -- it says in one line where to
    # look.

    def set_stamp(self, stamp: Stamp) -> None:
        """A tile picked in the palette. What it MEANS is the mode's answer.

        In TILES mode it is the brush. In COLLISION mode the brush is a MASK,
        so the tile is the TARGET and the pick writes that mask onto the tile
        itself.

        The stamp is remembered EITHER WAY, so a mode switch does not lose
        the author's tile or leave the palette's highlight behind.
        """
        self.stamp = stamp
        if self.mode is EditMode.COLLISION:
            self.bake_tile_mask(stamp)

    def bake_tile_mask(self, stamp: Stamp | None = None) -> bool:
        """Give every tile in `stamp` the collision brush's mask, for good.

        ONE TRANSACTION, one `map.tileset.mask.set` per distinct tile, each
        carrying the exact `map.tileset.mask.restore` the verb hands back --
        so a rectangle dragged out of the palette is still one Ctrl+Z, and it
        puts back both the cells and the `pyoneer_collision` declaration a
        first bake had to add.

        REFUSALS ARE SAID, NEVER GUESSED AROUND. An empty pick, an atlas that
        has not loaded, a gid belonging to no tileset this map declares: each
        ends the gesture with one status line and no command at all, so
        nothing is half-written. The verb's own refusals -- an external
        tileset whose extent lives in a .tsx, a tileset with no name to
        derive a sidecar from -- are left to the verb and reach the author
        through `run`'s rejection report. Nothing on this path opens a
        dialog.

        A TILESET THAT CARRIES NO MASKS STAYS FREE. The sidecar is written
        and declared by the first bake, in one transaction, exactly as the
        first collision stroke provisions `Collision.png`.
        """
        if self.atlas is None:
            self.status.emit("no tilesets are loaded yet, so there is no "
                             "tile to give a mask to")
            return False
        stamp = self.stamp if stamp is None else stamp
        mask = self.mask
        # Distinct, and in the order the palette laid them out: a 2x2 pick of
        # one repeated tile is ONE mask edit, not four commands writing the
        # same cell whose inverses would then undo each other in sequence.
        gids: list[int] = []
        for gid in stamp.gids:
            # -1 is `Stamp`'s "leave this cell alone" hole and 0 is the empty
            # cell. Neither is a tile, so neither can carry a mask.
            if gid > 0 and gid not in gids:
                gids.append(gid)
        if not gids:
            self.status.emit("pick a tile in the Tiles palette to give it "
                             "this mask")
            return False

        map_scope = Scope.of(("map", self.map_name))
        commands: list[Command] = []
        for gid in gids:
            entry = self.atlas.entry_for(gid)
            if entry is None:
                self.status.emit(
                    f"gid {gid} belongs to no tileset this map declares, so "
                    f"there is nowhere to store its mask — nothing changed")
                return False
            commands.append(Command("map.tileset.mask.set", map_scope, {
                # A name when there is one, the firstgid when there is not:
                # an external `<tileset source=...>` carries no name in this
                # file, and `_tileset_key` takes either.
                "name": entry.name,
                "first_gid": 0 if entry.name else entry.first_gid,
                "tile": gid - entry.first_gid,
                "mask": mask,
            }))

        what = f"tile {gids[0]}" if len(gids) == 1 else f"{len(gids)} tiles"
        # `describe_opinion`, never `describe_mask`: the chip's -1 has every
        # bit set, so `describe_mask` reads the one value that CLEARS a mask
        # as the one that blocks every direction.
        if not self.window().run(commands,
                                 label=f"{what} {describe_opinion(mask)}"):
            return False
        # AFTER run(), which writes its own line to the same status bar, so
        # the author is left looking at what the click did rather than at the
        # verb that did it. `__commit_collision` orders it the same way.
        note = ""
        if self.mode is EditMode.COLLISION and not self.all_layers:
            note = (" — turn All layers on to see it: this view draws one "
                    "companion's own cells, and a tile's mask is not one")
        self.status.emit(
            f"{what}: {describe_opinion(mask)}, everywhere "
            f"{'it is' if len(gids) == 1 else 'they are'} stamped{note}")
        return True

    def tile_masks(self) -> dict[int, int]:
        """gid -> the mask its TILESET carries, for every tile that has one.

        Level one, read through the SAME memo the resolved overlay resolves
        against -- `__tileset_defaults` -- so the badge the palette draws and
        the glyph the overlay draws cannot disagree.

        MISSING IS NOT AN ERROR: a tileset that declares no masks contributes
        none. A declaration that cannot be honoured answers an empty mapping
        here and leaves the reporting to `stack_refusal`.
        """
        found: dict[int, int] = {}
        defaults, _refusal = self.__tileset_defaults()
        for tileset in defaults:
            for local, opinion in enumerate(tileset.opinions):
                if opinion != NO_DATA:
                    found[tileset.first_gid + local] = opinion
        return found

    def inherited_cells(self) -> list[int]:
        """Row-major masks for the active layer: what each placed tile carries.

        Level one seen through the MAP rather than through the tileset sheet.
        `tile_masks()` answers "which gids are masked"; this answers "what is
        under this cell of the map", which is the question an author painting
        tiles is actually asking.

        NO_DATA for a cell whose gid carries no mask, and for every cell when
        no tile layer is selected -- an empty answer draws nothing rather than
        drawing a wall the map does not have.
        """
        layer = self.__active_tile_layer()
        if layer is None:
            return []
        by_gid = self.tile_masks()
        if not by_gid:
            return []
        return [by_gid.get(gid, NO_DATA) for gid in layer.gids()]

    def __detach_overlay(self) -> None:
        if self.__overlay is not None and self.__overlay.scene() is not None:
            self.__overlay.scene().removeItem(self.__overlay)

    def overlay_geometry(self) -> tuple[int, int, int, int]:
        """The readout's size, in cells and in pixels per cell.

        FROM THE COMPANION, NOT FROM THE MAP. The overlay draws what is in
        the file, so its cells have to BE the file's cells: a companion
        declaring `pyoneer_subcell="4"` holds sixteen masks per map tile, and
        one sized from the map would draw a single 16px glyph over them.

        Its OWN width and height, rather than `map * subcell`, because a
        companion smaller than the map is legal (`file_gid_reader` answers 0
        past its edge on purpose) and `bake` fits a flat row-major list by
        index -- so a narrower layer baked into a map-wide overlay would skew
        by one row per row.

        The all-layers view is the exception and sizes from the MAP: a
        resolved field is every layer at the finest resolution any of them
        declares, which is what the engine bakes.
        """
        document = self.document
        subcell = self.overlay_subcell()
        cell_w = max(1, document.tile_width // subcell)
        cell_h = max(1, document.tile_height // subcell)
        if not self.all_layers:
            companion = self.companion_layer()
            if companion is not None:
                return companion.width, companion.height, cell_w, cell_h
        return (document.width * subcell, document.height * subcell,
                cell_w, cell_h)

    def overlay_cell_at(self, scene_x: float, scene_y: float) -> tuple[int, int]:
        """Which READOUT cell a scene point is in.

        `cell_at`'s sibling, and separate from it because the two grids are
        allowed to differ: painting a 1x layer under the all-layers view is
        a 16px brush over a 4px readout, and the status line has to name the
        cell the cursor is actually over rather than the top-left corner of
        the cell the brush would fill.
        """
        _width, _height, cell_w, cell_h = self.overlay_geometry()
        return int(scene_x // cell_w), int(scene_y // cell_h)

    def __mount_overlay(self) -> None:
        """Put the readout back into the freshly cleared scene.

        Built once per map GEOMETRY and re-added, never rebuilt: the item
        owns a scene-sized pixmap, and both making one and filling it are
        expensive enough that doing either on every command -- and a command
        is every click -- would be felt.
        """
        geometry = self.overlay_geometry()
        if self.__overlay is None or self.__overlay_geometry != geometry:
            self.__overlay = CollisionOverlay(*geometry)
            self.__overlay_geometry = geometry
            self.__collision_stale = True
        self.scene().addItem(self.__overlay)
        self.__overlay.setVisible(True)
        self.__overlay.setOpacity(
            1.0 if self.mode is EditMode.COLLISION else INHERITED_OPACITY)
        if self.__collision_stale:
            self.__bake_overlay()

    def __on_transaction(self, _transaction, action: str) -> None:
        """Anything that changed the project other than our own stroke."""
        # BEFORE the early return: our own stroke can carry a
        # `map.tileset.add` in the same transaction as its cells, so "this
        # commit was ours" is a reason not to re-bake the whole overlay and
        # is not a reason to keep reading a tileset table from before it.
        self.__forget_level_one()
        if action == "apply" and self.__own_commit:
            return          # our cells are written by __sync_overlay instead
        self.__collision_stale = True

    def __forget_level_one(self) -> None:
        """Drop the memoised tileset defaults and the last build's refusal.

        Both are answers about a document that has just changed underneath
        them. Kept as one call because forgetting one without the other is a
        readout reporting last document's reason for this document's stack.
        """
        self.__level_one = None
        self.__stack_build_refusal = None

    def __refresh_level_one(self) -> None:
        """Re-read level one, and mark the READOUT stale if it moved.

        A `.blitmask` is the one input to this overlay that can change with
        no command behind it: the refusal names a file, the author goes and
        writes that file, and comes back. Nothing in the stream announces
        that, so a rebuild re-reads the sidecar and compares.

        MARKED STALE ONLY WHEN THE ANSWER REALLY CHANGED. Marking it on every
        rebuild would pay a full bake per command -- 6 ms on top of the
        26.9 ms of layer rendering, on every click. When a TRANSACTION
        cleared the memo a moment ago there is nothing to compare against,
        and nothing to decide: `__on_transaction` has already judged that
        change, knowing whether it was our own stroke.
        """
        previous = self.__level_one
        self.__forget_level_one()
        if previous is not None and self.__tileset_defaults() != previous:
            self.__collision_stale = True

    def __bake_overlay(self) -> None:
        """The whole field, from the document. The expensive path.

        THE RESOLVED VIEW IS ASKED FIRST, AND IS NOT GATED ON A COLLISION
        TILESET. A tileset default is stored in a `.blitmask` beside the .tmx
        and needs no firstgid, so a map where the author painted nothing and
        the tiles carry everything still resolves -- as it does in
        `field_from_map`, which has no such gate either.

        The single-layer view keeps the gate: it shows one companion's own
        gids, and without a firstgid there is no companion and nothing to
        decode.
        """
        overlay = self.__overlay
        if overlay is None:
            return
        self.__collision_stale = False
        if self.mode is not EditMode.COLLISION:
            # Tile mode shows what each PLACED tile brings with it, so an
            # author can see a wall tile's own passability while painting art
            # rather than having to switch modes to find out.
            overlay.bake(self.inherited_cells())
            return
        if self.all_layers:
            # At the overlay's OWN resolution, and every member scaled into
            # it -- see `collision_stack`. The overlay was sized from the
            # same number, so cell (x, y) here and cell (x, y) there are the
            # same square of the map.
            overlay.bake_resolved(self.collision_stack(self.overlay_subcell()))
            return
        first_gid = self.collision_first_gid
        if first_gid is None:
            overlay.bake([])                  # pads with NO_DATA: draws nothing
            return
        companion = self.companion_layer()
        overlay.bake(masks_from_layer(companion, first_gid)
                     if companion is not None else [])

    def __overlay_scale(self) -> int:
        """How many overlay cells one PAINT cell covers, per axis.

        1 whenever the readout and the brush are at the same resolution,
        which is every single-layer view and every unmixed map. It is not 1
        for an author painting a 1x layer while the all-layers view resolves
        the map at 4x: one click changes sixteen cells of that readout, and
        writing only the first of them leaves fifteen showing the answer from
        before the stroke.
        """
        return max(1, self.overlay_subcell() // max(1, self.paint_subcell))

    def __sync_overlay(self, cells) -> None:
        """Repaint only the cells a stroke just changed.

        This is the reason the item is held rather than re-made: a cell is
        10.4 us and a full bake is 6 ms, on top of the layer rendering a
        rebuild already pays. The resolved view re-resolves the same cells
        rather than falling back to a bake, because changing one cell of one
        layer can only change that cell's answer.

        `cells` are PAINT cells -- what the stroke wrote -- and the overlay is
        indexed in overlay cells, so each one expands by `__overlay_scale`.
        """
        overlay = self.__overlay
        if overlay is None or self.collision_first_gid is None:
            return
        scale = self.__overlay_scale()
        if self.all_layers:
            stack = self.collision_stack(self.overlay_subcell())
            for x, y in cells:
                for offset_y in range(scale):
                    for offset_x in range(scale):
                        cx, cy = x * scale + offset_x, y * scale + offset_y
                        # `resolve_cell`, which is what a full bake calls per
                        # cell too, so a stroke and the next bake cannot draw
                        # two different answers for one cell.
                        mask, owner, conflicted, level = resolve_cell(
                            stack, cx, cy, undecided=NO_DATA)
                        overlay.set_cell(cx, cy, mask, owner=owner,
                                         conflicted=conflicted, level=level)
            return
        companion = self.companion_layer()
        if companion is None:
            return
        first_gid = self.collision_first_gid
        for x, y in cells:
            overlay.set_cell(
                x, y, gid_to_opinion(companion.get_tile(x, y), first_gid))

    # -- ghost preview -----------------------------------------------------

    def __clear_ghost(self) -> None:
        if self.__ghost is not None:
            self.scene().removeItem(self.__ghost)
            self.__ghost = None

    def __draw_ghost(self) -> None:
        self.__clear_ghost()
        if self.__stroke is None:
            return
        if self.mode is EditMode.COLLISION:
            self.__draw_mask_ghost()
            return
        if self.atlas is None:
            return
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.55)
        for x, y, gid in self.__stroke.preview():
            px, py = x * self.tile_width, y * self.tile_height
            if gid <= 0:
                marker = QGraphicsRectItem(px, py, self.tile_width, self.tile_height)
                marker.setPen(QPen(QColor(255, 120, 120), 0))
                marker.setBrush(QBrush(QColor(255, 60, 60, 90)))
                group.addToGroup(marker)
                continue
            tile = self.atlas.pixmap(gid)
            if tile is not None:
                item = QGraphicsPixmapItem(tile)
                item.setPos(px, py)
                item.setTransformationMode(Qt.FastTransformation)
                group.addToGroup(item)
        self.scene().addItem(group)
        self.__ghost = group

    def __draw_mask_ghost(self) -> None:
        """The pending stroke in the overlay's own vocabulary.

        A tile ghost cannot say this: what is being placed is a mask, and its
        art is the glyph rather than anything in a tileset. The plate under
        each glyph is what makes "open" and "clear" aimable -- both of those
        draw no glyph at all, and a brush you cannot see is a brush you
        cannot place.
        """
        first_gid = self.collision_first_gid
        if first_gid is None:
            return
        # A mask ghost is drawn in PAINT cells, not in tiles: what is being
        # placed is an opinion about one addressable cell, and its art is
        # the glyph rather than anything in a tileset.
        glyphs = glyph_pixmaps(self.paint_width, self.paint_height)
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.75)
        for x, y, gid in self.__stroke.preview():
            px, py = x * self.paint_width, y * self.paint_height
            plate = QGraphicsRectItem(px, py, self.paint_width, self.paint_height)
            plate.setPen(QPen(_MASK_GHOST_PEN, 0))
            plate.setBrush(QBrush(_MASK_GHOST_FILL))
            group.addToGroup(plate)
            glyph = glyphs.get(gid_to_opinion(gid, first_gid))
            if glyph is not None:
                item = QGraphicsPixmapItem(glyph)
                item.setPos(px, py)
                item.setTransformationMode(Qt.FastTransformation)
                group.addToGroup(item)
        self.scene().addItem(group)
        self.__ghost = group

    # -- input -------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.__space = True
            self.setCursor(Qt.OpenHandCursor)
        if event.key() == Qt.Key_Delete:
            # Delete ONLY. Backspace is deliberately not bound: it is the
            # key a hand reaches for while typing, this view takes focus
            # from a click on the map, and a mis-aimed Backspace that
            # removes an entity is exactly the accident right-click has
            # just stopped causing.
            self.delete_selected_object()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.__space = False
            self.unsetCursor()
        super().keyReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        """Plain wheel zooms.

        Deliberately unlike Tiled, which needs ctrl+wheel: zooming is
        constant here and scrolling is rare, since panning is middle-drag.
        Shift+wheel still scrolls.
        """
        if event.modifiers() & Qt.ShiftModifier:
            super().wheelEvent(event)
            return
        steps = event.angleDelta().y()
        if not steps:
            super().wheelEvent(event)
            return
        factor = 1.15 if steps > 0 else 1 / 1.15
        # Keep zoom inside a range where the scene is still addressable; at
        # 0.02x a 1600px map is 32px and every click lands on the same tile.
        current = self.transform().m11()
        target = current * factor
        if not (0.05 <= target <= 20.0):
            event.accept()
            return
        self.scale(factor, factor)
        self.status.emit(f"zoom {target * 100:.0f}%")
        event.accept()

    def mousePressEvent(self, event) -> None:
        point = self.mapToScene(event.position().toPoint())
        column, row = self.cell_at(point.x(), point.y())

        if event.button() == Qt.MiddleButton or self.__space:
            self.__panning = True
            self.__pan_from = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.modifiers() & Qt.AltModifier and event.button() == Qt.LeftButton:
            if self.mode is EditMode.COLLISION:
                self.__pick_mask(column, row)
            else:
                self.__pick(column, row)
            event.accept()
            return

        if (event.modifiers() & Qt.ShiftModifier
                and event.button() == Qt.LeftButton):
            # MAP cells, not `cell_at`'s. What carries a mask is the TILE,
            # and in collision mode `cell_at` answers in sub-cells -- sixteen
            # of which sit on one tile at 4x.
            self.__mask_tile_at(int(point.x() // self.tile_width),
                                int(point.y() // self.tile_height))
            event.accept()
            return

        if self.mode is EditMode.COLLISION:
            if event.button() in (Qt.LeftButton, Qt.RightButton):
                self.__begin_collision(
                    column, row, erase=event.button() == Qt.RightButton)
                event.accept()
                return
            super().mousePressEvent(event)
            return

        layer = self.__active_tile_layer()
        if layer is not None and event.button() in (Qt.LeftButton, Qt.RightButton):
            if self.tool is Tool.PICKER:
                self.__pick(column, row)
                event.accept()
                return
            if self.tool is Tool.AUTOTILE:
                self.__begin_terrain(layer, column, row,
                                     erase=event.button() == Qt.RightButton)
                event.accept()
                return
            self.__erasing = event.button() == Qt.RightButton
            stamp, anchor = self.__footprint()
            self.__stroke = Stroke(
                Tool.ERASER if self.__erasing else self.tool,
                stamp, Bounds(layer.width, layer.height), layer.get_tile,
                anchor=anchor)
            self.__stroke.begin(column, row)
            self.__draw_ghost()
            event.accept()
            return

        # BELOW HERE THERE IS NO TILE LAYER TO PAINT, so the buttons mean
        # what they mean on an object layer. Everything above has already
        # declined, which is what keeps right-drag-erases intact.
        if event.button() == Qt.LeftButton:
            self.__click_object(point, column, row)
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self.__open_object_menu(
                point, self.mapToGlobal(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Open the object editor. Only ever on an object layer.

        A tile layer keeps every double-click it ever had: the second
        press of a fast double paint has to keep painting, so this defers
        to the base class the moment there is a tile layer or a mask under
        the cursor.
        """
        if event.button() != Qt.LeftButton or self.mode is EditMode.COLLISION \
                or self.__active_tile_layer() is not None:
            super().mouseDoubleClickEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        column, row = self.cell_at(point.x(), point.y())
        # A drag opened by the first press of this double-click is over
        # and must not commit on the release that follows.
        self.__object_drag = None
        self.__clear_ghost()
        self.__open_object_editor(point, column, row)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        point = self.mapToScene(position)
        column, row = self.cell_at(point.x(), point.y())

        if self.__panning and self.__pan_from is not None:
            delta = position - self.__pan_from
            self.__pan_from = position
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self.__object_drag is not None:
            self.__drag_object_to(point, snap=self.__snapping(event))
            event.accept()
            return

        if self.__terrain is not None:
            self.__terrain.extend(column, row)
            self.__draw_terrain_ghost()
            self.status.emit(f"cell ({column}, {row})   "
                             f"{len(self.__terrain.pending)} tiles")
            event.accept()
            return

        if self.__stroke is not None:
            self.__stroke.extend(column, row)
            self.__draw_ghost()
            unit = "cells" if self.mode is EditMode.COLLISION else "tiles"
            self.status.emit(f"cell ({column}, {row})   "
                             f"{len(self.__stroke.edits())} {unit}")
            event.accept()
            return

        if self.mode is EditMode.COLLISION and self.__overlay is not None:
            # A RESOLVED VIEW THE MAP CANNOT SUPPORT DESCRIBES NOTHING. When
            # `field_subcell` refuses this map the overlay is drawn at 1x so
            # the map stays editable, and describing a cell of it would state
            # what the player will feel on a map that raises before there is
            # a player. Said on every move, because this line is the only
            # status nothing else overwrites.
            refusal = self.stack_refusal() if self.all_layers else None
            if refusal is not None:
                self.status.emit(f"cell ({column}, {row})   All layers cannot "
                                 f"be trusted here: {refusal}")
                super().mouseMoveEvent(event)
                return
            # What the overlay shows, in words -- including which layer
            # decided and whether one below disagrees, neither of which
            # survives being reduced to a colour. Read at the OVERLAY's cell,
            # which is finer than the brush's under the all-layers view.
            self.status.emit(
                f"cell ({column}, {row})   "
                f"{self.__overlay.describe(*self.overlay_cell_at(point.x(), point.y()))}")
            super().mouseMoveEvent(event)
            return

        self.status.emit(f"cell ({column}, {row})   "
                         f"px ({point.x():.0f}, {point.y():.0f})")
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.__panning:
            self.__panning = False
            self.__pan_from = None
            self.setCursor(Qt.OpenHandCursor if self.__space else Qt.ArrowCursor)
            self.unsetCursor()
            event.accept()
            return

        if self.__object_drag is not None:
            self.__commit_object_drag(
                self.mapToScene(event.position().toPoint()),
                snap=self.__snapping(event))
            event.accept()
            return

        if self.__terrain is not None:
            self.__commit_terrain()
            event.accept()
            return

        if self.__stroke is not None:
            if self.mode is EditMode.COLLISION:
                self.__commit_collision()
            else:
                self.__commit_stroke()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def __commit_stroke(self) -> None:
        stroke, self.__stroke = self.__stroke, None
        self.__clear_ghost()
        if stroke is None:
            return
        edits = stroke.edits()
        if not edits:
            self.status.emit("nothing changed")
            return
        scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))
        verb = "map.tile.set_many"
        self.window().run(
            Command(verb, scope, {"tiles": edits_to_triples(edits)}),
            label=f"{stroke.tool.label} ({len(edits)} tiles)")

    # -- collision ---------------------------------------------------------

    def __begin_collision(self, column: int, row: int, *, erase: bool) -> None:
        """Start a stroke against the active layer's companion.

        The same `Stroke` the tile tools use, over the same kind of layer,
        writing the same kind of value -- `first_gid + mask` is a gid. What
        changes is only where it reads and what it stamps.

        THE ORDER OF THE GATES MATTERS. The LOCAL refusals -- no layer,
        wrong tool, nothing to pick -- run first, so that nothing is
        provisioned for a gesture that was going to be refused anyway.

        Then the mask tileset. When the map has none, the sheet is written if
        absent and the DECLARATION is queued for the commit, so the gesture
        that asked is the gesture that paints. When the map has one, it is
        checked that it can hold every mask -- a map declaring a five-tile
        `collision` tileset would otherwise paint gids past the end of its
        own sheet.
        """
        if self.__active_tile_layer() is None:
            self.status.emit("select a tile layer to give collision to")
            return
        # THE GUARD, above the picker on purpose: a resolution the canvas and
        # the file disagree about makes a PICK read the wrong cell as surely
        # as it makes a stroke write one. Cheap and local like the refusal
        # above it -- it reads the document and writes nothing.
        misplaced = self.collision_stroke_refusal()
        if misplaced is not None:
            self.status.emit(misplaced)
            return
        if self.tool is Tool.PICKER:
            self.__pick_mask(column, row)
            return
        if not self.mode.allows(self.tool):
            self.status.emit(f"{self.tool.label} has no meaning in collision "
                             f"mode — there is no mask sheet to index")
            return

        self.__pending_tileset = None
        self.__wrote_sheet = False
        first_gid = self.collision_first_gid
        # THE NO-OPINION CHIP CLEARS, so it is the eraser wearing a swatch:
        # `opinion_to_gid(NO_DATA, ...)` is 0 whatever the firstgid is, which
        # is the one value in the brush that needs no tileset to encode.
        clears = erase or self.mask == NO_DATA
        if first_gid is None:
            if clears:
                # Erasing writes gid 0, which needs no tileset, and there is
                # nothing here to erase -- so a right-drag over a map with no
                # collision must not declare a gid range to service it.
                self.status.emit("no collision on this map yet — "
                                 "nothing to erase")
                return
            try:
                # A pure query -- the document is byte-identical afterwards --
                # and the SAME function `add_tileset` uses at release, so the
                # gid this stroke stamps is the gid the tileset will claim.
                # It raises when a tileset's extent lives in a .tsx this
                # document cannot see, which makes a collision-free firstgid
                # unknowable; refusing at press is the answer
                # `map.tileset.add` would give at release, forty cells later.
                first_gid = self.document.next_tileset_firstgid()
            except PyoneerError as exc:
                self.status.emit(str(exc))
                return
            offer = self.provision_collision_tileset()
            if offer is None:
                return                      # it said why; changed nothing
            self.__pending_tileset = offer
        else:
            declared = self.collision_tileset_ref()
            if declared is not None and declared.tile_count < len(MASK_DOMAIN):
                self.status.emit(
                    f"this map's {declared.name!r} tileset declares "
                    f"{declared.tile_count} tiles (gids {declared.first_gid}–"
                    f"{declared.last_gid}) — too few to hold "
                    f"{len(MASK_DOMAIN)} masks, so a mask would be written as "
                    f"a gid it does not own. Re-add it at "
                    f"{len(MASK_DOMAIN)} tiles before painting collision")
                return

        companion = self.companion_layer()
        document = self.document
        # Before the companion exists there is nothing to read, and every
        # cell of it is empty -- which is exactly what a reader that answers 0
        # says.
        #
        # THE BOUNDS ARE THE LAYER'S, NOT THE MAP'S. When the companion is
        # there they are its own width and height, so a companion finer than
        # the map -- or smaller than it, which is legal -- clips to what
        # exists. When it is not, the commit creates it at the map's size in
        # PAINT cells and passes this same number as `subcell`, so that is
        # what the stroke may write into.
        subcell = self.paint_subcell
        read = companion.get_tile if companion is not None else _EMPTY_READER
        bounds = (Bounds(companion.width, companion.height)
                  if companion is not None
                  else Bounds(document.width * subcell,
                              document.height * subcell))
        stamp, anchor = self.__footprint(
            Stamp.single(opinion_to_gid(self.mask, first_gid)))
        self.__stroke = Stroke(
            Tool.ERASER if erase else self.tool,
            stamp, bounds, read, anchor=anchor)
        self.__stroke.begin(column, row)
        self.__draw_ghost()

    def __commit_collision(self) -> None:
        """One stroke, one transaction -- tileset and companion layer included.

        Up to four commands land in front of the tiles: declare the mask
        TILESET if this map had none, then create the companion LAYER, tell
        the art layer which layer holds its masks, and mark the companion as
        data rather than art. They land together or not at all, and one undo
        takes all five back out in reverse, each from its own recorded
        inverse.

        `map.tileset.add`'s inverse is `map.tileset.remove(force=False)`, and
        that guard holds here because the tiles pointing into the new range
        are zeroed EARLIER in the same unwind. So undo takes the declaration
        back out and leaves the PNG on disk.

        The undo entry reads as the stroke -- "Brush collision (3 cells)" --
        not as the plumbing: the tileset and the layer are implementation of
        that stroke rather than separate acts the author performed, and
        `Transaction.summary_lines()` exposes all five commands to anyone who
        wants them.
        """
        stroke, self.__stroke = self.__stroke, None
        # Consumed, not merely read: a spent offer left on the instance is a
        # `map.tileset.add` the NEXT stroke would carry without asking.
        # `__begin_collision` clears them again at the top of every press.
        pending, self.__pending_tileset = self.__pending_tileset, None
        wrote, self.__wrote_sheet = self.__wrote_sheet, False
        self.__clear_ghost()
        if stroke is None:
            return
        edits = stroke.edits()
        if not edits:
            self.status.emit("nothing changed")
            return

        name = self.companion_name()
        if name is None:
            return
        map_scope = Scope.of(("map", self.map_name))
        companion_scope = map_scope.child("layer", name)
        commands: list[Command] = []
        if pending is not None:
            commands.append(Command("map.tileset.add", map_scope,
                                    pending.command_args()))
        if self.companion_layer() is None:
            commands.append(Command("map.layer.add", map_scope,
                                    self.__companion_add_args(name)))
            commands.append(Command(
                "map.layer.set", map_scope.child("layer", self.active_layer),
                {"key": "passability", "value": name}))
            commands.append(Command("map.layer.set", companion_scope,
                                    {"key": "renders", "value": False}))
        commands.append(Command("map.tile.set_many", companion_scope,
                                {"tiles": edits_to_triples(edits)}))

        # The window refreshes -- and so rebuilds this canvas -- inside run(),
        # so the flag has to be up for the whole call: it is how the stream
        # listener tells our own write apart from everybody else's.
        self.__own_commit = True
        try:
            applied = self.window().run(
                commands, label=f"{stroke.tool.label} collision "
                                f"({len(edits)} cells)")
        finally:
            self.__own_commit = False
        if not applied:
            return
        self.__sync_overlay([(x, y) for x, y, _gid in edits])
        if pending is not None:
            # ONE line, after run() has written its own to the same status
            # bar, so this is what the author is left looking at: what was
            # provisioned, said as something that happened.
            written = (f" — wrote {pending.absolute}" if wrote else "")
            self.status.emit(
                f"{stroke.tool.label} collision ({len(edits)} cells): added "
                f"the {pending.name!r} tileset, {pending.tile_count} masks"
                f"{written}")

    def __companion_add_args(self, name: str) -> dict:
        """The `map.layer.add` that creates a companion for this stroke.

        THE RESOLUTION COMES FROM THE FUNNEL, not from `collision_subcell`
        directly: `paint_unit` decided which cell the click landed in, and a
        layer created at any other resolution would not hold the cells this
        stroke just addressed.

        `subcell` is OMITTED at 1 rather than passed as 1, so a 1x companion
        is written exactly as it always has been and the author opts in to
        anything else. It has to be right at creation: no verb re-scales a
        companion afterwards, and `map.layer.set` refuses to write
        `pyoneer_subcell`.

        `renders=False` is stated HERE, at creation, and not only by the
        `map.layer.set` that follows: a name with no depth is advised to get
        one as the layer is added, and a companion that arrives silently is
        the difference between painting collision and being told to draw the
        masks. The later set is left in place and is a no-op against the
        value this already wrote.
        """
        args: dict = {"name": name, "kind": "tile", "renders": False}
        subcell = self.paint_subcell
        if subcell > 1:
            args["subcell"] = subcell
        return args

    def __mask_tile_at(self, column: int, row: int) -> None:
        """Shift+Left on the MAP: give the tile under it the mask brush.

        The two-step is the one a palette click already uses -- pick the
        mask, then pick what it applies to -- with the MAP standing in for
        the tileset sheet. What it removes is the hunt: finding which of a
        768-tile sheet a wall was, when the wall is on screen in front of
        you.

        IT NEEDS NO MODE. The mask is whatever the mask palette holds, the
        target is the tile under the cursor, and in TILES mode the answer
        appears where the click landed -- `__bake_overlay` draws
        `inherited_cells()` there, which is level one, which is the level
        this writes. That is the whole of "apply collision and see it
        without switching modes".

        `bake_tile_mask` owns every command and every refusal past this
        point, so this is a BINDING and not a second way to author a mask.
        """
        layer = self.__active_tile_layer()
        if layer is None:
            self.status.emit("select a tile layer, then shift+click a tile on "
                             "it to give that tile this mask")
            return
        if not (0 <= column < layer.width and 0 <= row < layer.height):
            self.status.emit("that is outside the map")
            return
        gid = layer.get_tile(column, row)
        if gid <= 0:
            self.status.emit(
                f"cell ({column}, {row}) of {self.active_layer!r} is empty — "
                f"a mask lives on a tile, and there is no tile here")
            return
        self.bake_tile_mask(Stamp.single(gid))

    def __pick_mask(self, column: int, row: int) -> None:
        """Alt+click, or the picker tool, in collision mode."""
        first_gid = self.collision_first_gid
        companion = self.companion_layer()
        if first_gid is None or companion is None or not (
                0 <= column < companion.width and 0 <= row < companion.height):
            self.status.emit("no mask here to pick")
            return
        mask = gid_to_opinion(companion.get_tile(column, row), first_gid)
        if mask == NO_DATA:
            self.status.emit("no mask here to pick")
            return
        self.mask = mask
        self.picked_mask.emit(mask)
        self.status.emit(f"picked {describe_mask(mask)}")

    # -- terrain -----------------------------------------------------------

    def __terrain_for_brush(self):
        """The autotile group the currently-picked tile belongs to.

        Choosing a terrain is therefore "click any tile of it in the
        palette", rather than picking one of 32 origin gids out of a list.
        """
        if self.atlas is None:
            return None
        gid = self.stamp.primary
        entry = self.atlas.entry_for(gid)
        if entry is None or gid <= 0:
            return None
        try:
            origin = autotile.origin_for_gid(gid, entry.first_gid, entry.columns)
        except ValueError:
            return None
        return autotile.TerrainSet(origin=origin, columns=entry.columns,
                                   name=entry.name)

    def __begin_terrain(self, layer, column: int, row: int, *,
                        erase: bool) -> None:
        terrain = self.__terrain_for_brush()
        if terrain is None:
            self.status.emit("pick a tile from an autotile sheet first")
            return
        self.__terrain = _TerrainStroke(
            layer, terrain, erase=erase,
            size=self.brush_size if self.tool.uses_size else 1)
        self.__terrain.extend(column, row)
        self.__draw_terrain_ghost()

    def __draw_terrain_ghost(self) -> None:
        self.__clear_ghost()
        if self.__terrain is None or self.atlas is None:
            return
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.6)
        for (x, y), gid in self.__terrain.pending.items():
            tile = self.atlas.pixmap(gid)
            if tile is None:
                continue
            item = QGraphicsPixmapItem(tile)
            item.setPos(x * self.tile_width, y * self.tile_height)
            item.setTransformationMode(Qt.FastTransformation)
            group.addToGroup(item)
        self.scene().addItem(group)
        self.__ghost = group

    def __commit_terrain(self) -> None:
        stroke, self.__terrain = self.__terrain, None
        self.__clear_ghost()
        if stroke is None:
            return
        edits = stroke.edits()
        if not edits:
            self.status.emit("nothing changed")
            return
        scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))
        self.window().run(
            Command("map.tile.set_many", scope,
                    {"tiles": edits_to_triples(edits)}),
            label=f"Terrain ({len(edits)} tiles)")

    # -- picking and objects -----------------------------------------------

    def __pick(self, column: int, row: int) -> None:
        layer = self.__active_tile_layer()
        if layer is None or not (0 <= column < layer.width
                                 and 0 <= row < layer.height):
            # Said out loud, as `__pick_mask` does: an alt+click off the map
            # or with no layer selected must not look like a dead editor.
            self.status.emit("no tile here to pick")
            return
        gid = layer.get_tile(column, row)
        self.stamp = Stamp.single(gid)
        self.picked_gid.emit(gid)
        self.status.emit(f"picked gid {gid}")

    def objects_under(self, point) -> list[tuple[str, Any]]:
        """EVERY object the point lands in, TOPMOST FIRST.

        Topmost is a claim about the picture, so it is answered from the
        same two numbers the picture is drawn from. `__draw_objects` gives
        every object of a layer `depth_of(layer) + 0.5`, so the layer with
        the greatest depth is in front; within one layer every rectangle
        shares a z and Qt paints them in the order they were added, so the
        LAST object of a group is the one on top. Hence: sort the layers by
        depth, descending, over a list already reversed -- `sorted` is
        stable, so layers that tie on depth keep reversed document order,
        which is the same tiebreak Qt applies to equal z.

        The alternative -- nearest to the cursor, or smallest first -- was
        rejected because it answers a question nobody asked: a click picks
        what a hand sees, and what a hand sees is what is drawn last.

        Hidden layers are skipped. Picking an object the author has
        switched off is picking something that is not on the screen.

        `__object_under` is this function's first element, so the incumbent
        single-hit behaviour is by construction the head of this list.
        """
        document = self.document
        found: list[tuple[str, Any]] = []
        names = sorted(reversed(document.object_layer_names()),
                       key=self.__depth_of, reverse=True)
        for name in names:
            if name in self.hidden_layers:
                continue
            for obj in reversed(document.object_layer(name).objects()):
                width = obj.width or self.tile_width
                height = obj.height or self.tile_height
                if (obj.x <= point.x() < obj.x + width
                        and obj.y <= point.y() < obj.y + height):
                    found.append((name, obj))
        return found

    def __object_under(self, point):
        hits = self.objects_under(point)
        return hits[0] if hits else (None, None)

    def object_label(self, layer_name: str, obj) -> str:
        """How one object says which one it is, in a menu.

        Its tmx `name` when it has one, because that is the string the
        author typed and the only one they will recognise. When it has
        none there is nothing to shorten, so the id and the type are given
        WHOLE rather than invented into a friendly-looking label -- an
        object called "GamePlayer" that is one of four GamePlayers is a
        list you cannot pick from.
        """
        what = obj.type or "object"
        if obj.name:
            return f"{obj.name}  ·  {what} {obj.id}  ·  {layer_name}"
        return f"{what} {obj.id}  ·  {layer_name}"

    def object_scope(self, layer_name: str, object_id) -> Scope:
        """The address of one object on THIS map. The one spelling."""
        return Scope.of(("map", self.map_name), ("layer", layer_name),
                        ("object", str(object_id)))

    # -- the object menu ---------------------------------------------------

    def object_menu(self, hits: list[tuple[str, Any]]) -> QMenu:
        """The right-click menu for what is under the cursor.

        Built apart from being shown, for `TilePalette.tileset_menu`'s two
        reasons: a check can trigger an entry without touching a modal
        (law 13), and a menu that is only ever `exec`'d is a menu no
        assertion can read.

        TWO SHAPES, AND THE COUNT DECIDES WHICH. Over ONE object the menu
        acts on it -- Edit and Delete, the two things there are to do. Over
        SEVERAL it is a PICKER and nothing else: one entry per object, each
        selecting it, because "which of these did you mean" has to be
        answered before "what should I do with it" can be. Deleting the
        topmost of a stack from a menu that never said which one was
        topmost is the shape this is against.

        A picker entry emits `selected` and writes nothing at all. The
        author then has Delete on the keyboard and a double-click for the
        editor, both of which act on the selection they just made.
        """
        if not hits:
            # RAISED, not answered with an empty menu (law 7). "Nothing is
            # here" is a decision `__open_object_menu` makes before this is
            # called, and a menu with no entries in it is a control that
            # tells the author they missed without telling them what they
            # missed.
            raise PyoneerError("there is no object here to open a menu for")
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        if len(hits) > 1:
            for layer_name, obj in hits:
                entry = menu.addAction(self.object_label(layer_name, obj))
                entry.setToolTip(
                    "select this one. Delete removes what is selected, and "
                    "a double-click opens it")
                entry.triggered.connect(
                    lambda _checked=False, layer=layer_name, oid=obj.id:
                    self.selected.emit(self.object_scope(layer, oid)))
            return menu

        layer_name, obj = hits[0]
        edit = menu.addAction("Edit…")
        edit.setToolTip("open this object's editor")
        edit.triggered.connect(
            lambda _checked=False, layer=layer_name, oid=obj.id:
            self.request_object_edit(layer, oid))
        delete = menu.addAction("Delete")
        delete.setToolTip("remove it from the map. One Ctrl+Z puts it back, "
                          "with every property it carried")
        delete.triggered.connect(
            lambda _checked=False, layer=layer_name, oid=obj.id:
            self.remove_object(layer, oid))
        return menu

    def __open_object_menu(self, point, at) -> None:
        """A right-click on an object layer. THE GESTURE THAT USED TO DELETE.

        Over bare ground it opens NOTHING -- an empty menu is a control
        that says the author missed without saying what they missed --
        and puts what the button means on the status bar instead.
        """
        hits = self.objects_under(point)
        if not hits:
            self.status.emit(
                "no object here — right-click one for Edit and Delete, "
                "double-click bare ground to place one")
            return
        menu = self.object_menu(hits)
        # Parented to this view, so it was never a top-level orphan (law
        # 12) -- but it would outlive the click until the next collection,
        # and it must not be freed while it is still on screen: `popup`
        # returns immediately. See `_hold_menu`.
        _hold_menu(menu)
        self.popup_menu(menu, at)

    # -- selecting, editing, removing --------------------------------------

    def request_object_edit(self, layer_name: str, object_id) -> None:
        """Ask the window to open one object. Selects it on the way.

        Two signals and not one, because they are two different claims:
        `selected` is where the editor is LOOKING, which the canvas draws
        itself, and `edit_object_requested` is a door being opened, which
        it cannot. Emitting only the second would open an editor for an
        object the canvas is still drawing unselected.
        """
        scope = self.object_scope(layer_name, object_id)
        self.selected.emit(scope)
        self.edit_object_requested.emit(scope)

    def selected_object(self):
        """(layer, object) for the selection, when it still names the one
        that was selected.

        RE-RESOLVED THROUGH THE DOCUMENT every single time -- a cached
        `MapObject` would, after one undo of a removal, be a wrapper around
        an element the document has replaced -- but re-resolved BY CARD and
        never by the scope's id alone. An id that is gone is handed out
        again: `MapDocument._release_object_id` rolls `nextobjectid` back,
        so the next object placed can be handed the dead id, and answering
        with THAT is how Delete removed something the author had never
        clicked. `SelectedObject` is where the whole measurement lives.

        (None, None) for: no selection, a selection that is not an object,
        an object on another map, a layer this map does not have, an id
        that is gone, and -- the one this exists for -- an id that now
        names a different object.
        """
        record = self.__selected
        if record is None:
            return None, None
        document = self.document
        if record.layer not in document.object_layer_names():
            return None, None
        found = document.object_layer(record.layer).find(record.object_id)
        if found is None or not record.still(found):
            return None, None
        return record.layer, found

    def remove_object(self, layer_name: str, object_id) -> bool:
        """`map.object.remove`, and then move the selection to the parent.

        The selection has to climb: the scope it held names an object that
        is no longer in the file, and a window still pointed at it shows an
        inspector for nothing and an outline around empty ground. The
        layer is the honest place to land -- it is where the object was,
        and it is what the author will place the next one on.
        """
        scope = self.object_scope(layer_name, object_id)
        if not self.window().run(Command("map.object.remove", scope)):
            return False
        self.selected.emit(Scope.of(("map", self.map_name),
                                    ("layer", layer_name)))
        return True

    def delete_selected_object(self) -> bool:
        """What the Delete key does. Every refusal is said out loud.

        FOUR GUARDS, and each one exists because the alternative deletes
        something the author cannot see selected:

        * COLLISION mode paints masks and draws no object outlines at all,
          so a Delete there would remove an entity the author had no way
          of knowing was still selected.
        * an active TILE layer means the canvas is showing tiles and the
          hierarchy is pointed at a tile layer; the object outline the
          selection refers to is not what the author is working on.
        * nothing selected, or a selection whose id now names a different
          object, removes nothing -- and says so, rather than looking like
          a dead key.
        * a HIDDEN layer draws no outline either. `__draw_objects` skips it
          and `objects_under` skips it, so the author cannot see the
          object, cannot click it and cannot right-click it -- and this
          key was the one path left that could still remove it. Measured
          through the real Layers-panel switch: it deleted.
        """
        if self.mode is EditMode.COLLISION:
            self.status.emit("Delete removes an object, and collision mode "
                             "paints masks — switch to Tiles first")
            return False
        if self.__active_tile_layer() is not None:
            self.status.emit(f"Delete removes an object, and {self.active_layer!r} "
                             f"is a tile layer — select the object first")
            return False
        layer_name, obj = self.selected_object()
        if obj is None:
            self.status.emit("nothing is selected — click an object first, "
                             "then press Delete")
            return False
        if layer_name in self.hidden_layers:
            self.status.emit(f"Delete removes an object, and {layer_name!r} is "
                             f"hidden — switch the layer back on in Layers "
                             f"first")
            return False
        return self.remove_object(layer_name, obj.id)

    # -- dragging an object ------------------------------------------------

    def __snapping(self, event) -> bool:
        """Does THIS event's position land on the grid?

        `snap_objects` inverted by ALT. Read from the event rather than
        from press state on purpose: alt+press is already the tile picker,
        so alt can only ever be taken up mid-drag, and a modifier sampled
        once at press would make the override unusable by the hand it
        exists for.
        """
        alt = bool(event.modifiers() & Qt.AltModifier)
        return bool(self.snap_objects) != alt

    def __drag_target(self, drag: ObjectDrag, point, *,
                      snap: bool) -> tuple[float, float]:
        """Where the dragged object's top-left would land.

        Snapping FLOORS to the tile grid rather than rounding to the
        nearest boundary, so that it agrees with `__click_object`, which
        places at `column * tile_width` for the cell the cursor is in.
        Two ways to put an object on a map that disagreed about which
        cell a pixel belongs to would be a half-tile jump on the first
        drag of every object ever placed.
        """
        x = point.x() - drag.grab_dx
        y = point.y() - drag.grab_dy
        if not snap:
            return float(x), float(y)
        tile_w, tile_h = self.tile_width, self.tile_height
        return float(x // tile_w * tile_w), float(y // tile_h * tile_h)

    def __begin_object_drag(self, layer_name: str, obj, point) -> None:
        drag = ObjectDrag(
            layer=layer_name, object_id=obj.id,
            start_x=obj.x, start_y=obj.y,
            grab_dx=point.x() - obj.x, grab_dy=point.y() - obj.y,
            width=obj.width or self.tile_width,
            height=obj.height or self.tile_height)
        self.__object_drag = drag
        # A press selects, exactly as it did before there were drags: the
        # gesture that moves a thing and the gesture that points at it are
        # the same gesture until the mouse travels.
        self.selected.emit(self.object_scope(layer_name, obj.id))

    def __drag_object_to(self, point, *, snap: bool) -> None:
        drag = self.__object_drag
        if drag is None:
            return
        drag.moved = True
        x, y = self.__drag_target(drag, point, snap=snap)
        self.__draw_object_ghost(drag, x, y)
        self.status.emit(
            f"{drag.what()} → ({x:.0f}, {y:.0f})   "
            f"{'snapped to the tile grid' if snap else 'freeflow'}"
            f"   (hold Alt to "
            f"{'go free' if self.snap_objects else 'snap'})")

    def __draw_object_ghost(self, drag: ObjectDrag, x: float, y: float) -> None:
        """Where the object WOULD land, drawn and not written.

        The document is untouched until the button comes up -- the same
        rule a tile stroke follows, and the reason a drag is one undo step
        rather than one per mouse move.
        """
        self.__clear_ghost()
        group = QGraphicsItemGroup()
        group.setZValue(_GHOST_Z)
        group.setOpacity(0.7)
        rect = QGraphicsRectItem(QRectF(x, y, drag.width, drag.height))
        rect.setPen(QPen(_OBJECT_SELECTED, 2.0))
        rect.setBrush(QBrush(QColor(_OBJECT_SELECTED.red(),
                                    _OBJECT_SELECTED.green(),
                                    _OBJECT_SELECTED.blue(), 70)))
        group.addToGroup(rect)
        self.scene().addItem(group)
        self.__ghost = group

    def __commit_object_drag(self, point, *, snap: bool) -> None:
        """ONE `map.object.move`, or nothing at all.

        A drag that ends where it started emits NO command. An undo step
        that changes nothing is worse than no undo step: it makes Ctrl+Z
        look broken, because the first press appears to do nothing at all.
        `map.object.move` would itself return a None inverse for an
        unchanged position -- but `CommandStream.apply` still pushes that
        transaction onto the undo stack, so the guard has to be here,
        before the command exists.
        """
        drag, self.__object_drag = self.__object_drag, None
        self.__clear_ghost()
        if drag is None:
            return
        x, y = self.__drag_target(drag, point, snap=snap)
        if x == drag.start_x and y == drag.start_y:
            # Silent for a plain CLICK, which is this same code path with
            # no travel in it and has already said what it did by
            # selecting. A drag that went somewhere and came back is a
            # different event and gets told it changed nothing.
            if drag.moved:
                self.status.emit(f"{drag.what()} stayed at "
                                 f"({x:.0f}, {y:.0f}) — nothing changed")
            return
        self.window().run(
            Command("map.object.move",
                    self.object_scope(drag.layer, drag.object_id),
                    {"x": x, "y": y}),
            label=f"move {drag.what()} to ({x:.0f}, {y:.0f})")

    def __click_object(self, point, column: int, row: int) -> None:
        """A left press on an object layer: grab one, or point at nothing.

        IT DOES NOT CREATE, and the whole reason is written out under
        A SINGLE CLICK NEVER CREATES in this module's docstring: this runs
        FIRST on the way to every double-click Qt will ever deliver, so
        anything expensive or irreversible here happens once per
        double-click as well.

        On bare ground it CLEARS the selection instead, by pointing the
        window at the layer -- the same climb `remove_object` makes when
        the object it named stops existing. That is the standard meaning of
        a click on empty space, and it is the author's only deliberate way
        back to "nothing is selected", which the Delete key and the
        inspector both read.

        `column` and `row` are still taken, and deliberately unused: they
        are the cell a create WOULD have landed in, and the signature is
        shared with `__open_object_editor` so that the two branches of one
        gesture cannot drift apart about which cell a pixel belongs to.
        """
        layer_name, obj = self.__object_under(point)
        if obj is not None:
            self.__begin_object_drag(layer_name, obj, point)
            return
        document = self.document
        if self.active_layer in document.object_layer_names():
            # The LAYER, not None: a scope is how every panel in this
            # editor is aimed, and there is no "nowhere" to aim them at.
            # `Selection.select` de-duplicates, so clicking bare ground
            # twice costs one rebuild and not two.
            self.selected.emit(Scope.of(("map", self.map_name),
                                        ("layer", self.active_layer)))
            if self.active_layer in self.hidden_layers:
                # THE SAME TRUTH THE DOUBLE-CLICK WILL TELL. Everything on a
                # hidden layer is skipped by `objects_under`, so "nothing
                # here" is what this branch can see and not what is there --
                # and inviting the double-click that `__place_object` now
                # refuses would be the editor advertising a dead gesture.
                self.status.emit(f"{self.active_layer!r} is hidden, so nothing "
                                 f"on it can be clicked — switch the layer "
                                 f"back on in Layers first")
                return
            self.status.emit(
                f"nothing here — selection cleared. Double-click to "
                f"place a {self.object_class}, or click an object to "
                f"select it")
            return
        self.status.emit("select a layer to paint on, or an object to select")

    def __place_object(self, column: int, row: int) -> int | None:
        """Put one object on the active object layer. THE ONLY CREATE PATH.

        Returns the new object's id, or None having said why in one line --
        which is what `__open_object_editor` needs, because opening an
        editor for "the last object in the layer" after a REFUSED add opens
        somebody else's object, silently, and looks exactly like it worked.

        IT SAYS NOTHING ON SUCCESS. The caller does, once the editor is
        open, because a status line is only ever the LAST one emitted:
        `request_object_edit` selects, the window answers with
        `refresh_all`, and `rebuild` has its own line to say on a machine
        with no tileset art. Measured -- the placement sentence was landing
        under "no tileset art for ... drawing colour swatches", which is
        true, unasked for, and not what the author just did.

        Snapped to the cell: `column * tile_width`, which is where
        `__drag_target`'s floor comes from. Two ways of putting an object on
        a map that disagreed about which cell a pixel belongs to would be a
        half-tile jump on the first drag of every object ever placed.

        A HIDDEN LAYER IS REFUSED, in the same words `delete_selected_object`
        uses, and creation is where the refusal matters MOST -- because
        creation on a hidden object layer is the one direction that cannot
        be walked back by hand. `__draw_objects` skips a hidden layer and
        `objects_under` skips it, so the object that lands is not drawn,
        cannot be clicked, cannot be dragged and cannot be right-clicked;
        the Delete key already refuses on the same grounds; and the
        double-click therefore finds nothing under the cursor and places
        AGAIN. Measured: three double-clicks in ONE cell of a layer
        unticked in the Layers panel left objects 1, 2 and 3 stacked, none
        of them drawn and none of them removable.
        #TAG:hidden_layer_refuses_creation

        THE LAYER IS NOT SWITCHED BACK ON INSTEAD. Making it visible would
        be a second effect of a gesture that asked for one, and it is an
        effect undo cannot reach: `hidden_layers` is view state and never
        enters the command stream, so Ctrl+Z would take the object back and
        leave the layer switched on. Refusing is also what the other three
        guards on this canvas do, and the refusal names the fix, which is
        this editor's habit everywhere a control declines (law 7).
        """
        document = self.document
        if self.active_layer not in document.object_layer_names():
            self.status.emit("select an object layer to place an object on")
            return None
        if self.active_layer in self.hidden_layers:
            self.status.emit(f"a double-click places an object, and "
                             f"{self.active_layer!r} is hidden — switch the "
                             f"layer back on in Layers first")
            return None
        scope = Scope.of(("map", self.map_name), ("layer", self.active_layer))
        if not self.window().run(Command("map.object.add", scope, {
            "type": self.object_class,
            "x": float(column * self.tile_width),
            "y": float(row * self.tile_height),
        })):
            # `run` has already reported the rejection where it can be read.
            return None
        # `add_object` APPENDS, so the new object is the last one -- and the
        # document is re-read rather than reusing the one above, because a
        # command ran in between.
        placed = self.document.object_layer(self.active_layer).objects()
        if not placed:
            return None
        return placed[-1].id

    def __say_placed(self, object_id: int) -> None:
        """One line for one placement, said where it can still be read.

        A genre default materialised onto the new object is otherwise
        INVISIBLE: the property is on the object and the author is looking
        at a rectangle. So the list is said out loud, once -- and read back
        off the object rather than off the pack, because what the file got
        is the only thing worth reporting.
        """
        found = self.document.object_layer(self.active_layer).find(object_id)
        tokens = found.properties.as_dict().get(BEHAVIORS, "") if found else ""
        self.status.emit(f"placed {self.object_class}"
                         + (f" with {tokens}" if tokens else ""))

    def __open_object_editor(self, point, column: int, row: int) -> None:
        """A double-click: open the object here, placing one if there is none.

        THE ORDER IS THE WHOLE THING. Ask what is under the cursor FIRST,
        and only create when the answer is nothing -- reversed, a
        double-click on a crowded map places a duplicate on top of every
        object it opens, silently, one per gesture.

        Qt's real sequence for a double-click is press, release,
        DoubleClick, release, and the first press has already run
        `__click_object` -- which now selects or CLEARS and never creates,
        for the reason this module's docstring gives under A SINGLE CLICK
        NEVER CREATES. So this is the ONLY creating branch there is, it
        runs once per gesture, and the count is the whole assertion: one
        double-click on bare ground leaves exactly one new object, never
        two.
        """
        layer_name, obj = self.__object_under(point)
        if obj is not None:
            self.request_object_edit(layer_name, obj.id)
            return
        object_id = self.__place_object(column, row)
        if object_id is None:
            # Refused, and `__place_object` has already said why. No
            # editor: one opened over a placement that did not happen is
            # an editor aimed at somebody else's object.
            return
        self.request_object_edit(self.active_layer, object_id)
        # LAST, and that is the whole reason it is not inside
        # `__place_object`: the line above rebuilds this canvas, and a
        # rebuild has its own things to say.
        self.__say_placed(object_id)


class _TerrainStroke:
    """One press-drag-release of the terrain tool.

    Kept separate from `paint.Stroke` because the models genuinely differ:
    a stamp tool writes the cells the cursor covered, and terrain writes a
    corner lattice and then re-tiles every cell those corners touch --
    including cells the cursor never went near, which is how the seam
    against existing terrain updates.

    The corner field is recovered once, on press, and then carried through
    the drag. Rebuilding it per mouse move would rescan the whole layer.
    """

    def __init__(self, layer, terrain: autotile.TerrainSet, *,
                 erase: bool = False, size: int = 1):
        if size < 1:
            raise ValueError(f"a terrain footprint must be at least 1 cell, "
                             f"got {size}")
        self.layer = layer
        self.terrain = terrain
        self.erase = erase
        #: A footprint in CELLS, the same number the brush uses. Terrain has
        #: no stamp -- `Tool.uses_stamp` is False for it -- but it does have
        #: a size, which is why `Tool.uses_size` is a separate property.
        self.size = size
        self.bounds = autotile.Bounds(layer.width, layer.height)
        self.pending: dict[tuple[int, int], int] = {}
        self.__last: tuple[int, int] | None = None
        self.field = autotile.corner_field(self.read, self.bounds, terrain)

    def read(self, x: int, y: int) -> int:
        """Uncommitted edits win, so a drag builds on its own work."""
        if (x, y) in self.pending:
            return self.pending[(x, y)]
        return self.layer.get_tile(x, y)

    def extend(self, column: int, row: int) -> None:
        if (column, row) == self.__last:
            return
        self.__last = (column, row)
        # A size-N terrain brush is the UNION of the per-cell corner sets
        # over an NxN block, centred the same way a tile brush is. At size 1
        # that is one call for the cell the cursor is on.
        half = (self.size - 1) // 2
        corners: set[autotile.Corner] = set()
        for down in range(self.size):
            for across in range(self.size):
                corners.update(autotile.corners_for_cell_brush(
                    column - half + across, row - half + down))
        edits, self.field = autotile.paint(
            self.read, self.bounds, self.terrain, corners,
            erase=self.erase, field=self.field)
        for x, y, gid in edits:
            self.pending[(x, y)] = gid

    def edits(self) -> list[tuple[int, int, int]]:
        return [(x, y, gid) for (x, y), gid in sorted(self.pending.items())
                if self.layer.get_tile(x, y) != gid]


# --------------------------------------------------------------------------
# The tile palette
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PaletteSection:
    """One tileset's strip of the stacked palette.

    Its OWN column count and its OWN cell size, because a fixed grid across
    tilesets would produce nonsense stamps for any geometry but the first --
    a gid's row and column are read off the tileset that owns it.
    """

    entry: Any                  # a TilesetEntry
    cell: int
    top: int                    # y of the header strip
    grid_top: int               # y of the first row of tiles
    columns: int
    rows: int

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def width(self) -> int:
        return self.columns * self.cell

    @property
    def bottom(self) -> int:
        return self.grid_top + self.rows * self.cell

    def rect(self, column: int, row: int) -> QRectF:
        """Where one tile of this section sits on the palette surface."""
        return QRectF(column * self.cell, self.grid_top + row * self.cell,
                      self.cell, self.cell)


@dataclass(frozen=True)
class TilesetFacts:
    """What the MAP knows about one tileset. See `TilePalette.tileset_facts`.

    The palette reads the ATLAS, which is a snapshot of the attributes one
    `<tileset>` declares. Two things it cannot see decide whether an edit is
    offered at all: the gid space ABOVE the range, and the cells painted
    INTO it. `EditorWindow.tileset_facts` answers both from the document.

    `problem` carries the reason when it could not answer -- an unknown
    extent, a map that will not open -- and every entry that depends on the
    numbers is greyed with it. A zero standing in for an unknown reads as
    "no headroom, nothing placed", which is the shape of answer that gets an
    author's painted cells deleted.
    """

    #: Tiles this tileset could still claim before it collided with the range
    #: above it. `MapDocument.tileset_headroom` computes it.
    headroom: int = 0
    #: Cells and tile objects currently pointing into its range.
    placed: int = 0
    #: Where those are, as "Floor x12, Props x1" -- a count with no address
    #: cannot be acted on.
    where: str = ""
    #: What ends the headroom, as "Beta at gid 33", or "" at the top of the
    #: gid space.
    blocked_by: str = ""
    #: Why this SHAPE of tileset cannot grow at all (external, margin or
    #: spacing, a collection of images), or "" when it can.
    growth_refusal: str = ""
    #: Why none of it could be answered, or "".
    problem: str = ""


def _exec_menu(menu: QMenu, at) -> None:
    """Pop `menu` at a global point. THE SEAM, and the only reason it exists.

    `popup`, NEVER `exec`. `QMenu.exec` spins its own event loop and does
    not return until the menu closes, which is a modal by every definition
    law 13 cares about: a check that drove a real right-click through this
    would sit there with zero output until the 600s timeout, exactly as
    `check_collision_mount` once did for 40+ minutes. `popup` shows the
    same menu and returns immediately, so the gesture is drivable and the
    only thing lost is a return value neither caller reads -- both wire
    their entries up with `triggered`.

    Held as an instance attribute like `ask` -- on `TilePalette` for a
    tileset's header and on `MapCanvas` for an object -- so a check can
    ALSO replace it and read the menu a real right-click built. Both
    halves matter: the seam lets a check see the menu, and `popup` is
    what keeps the unreplaced, shipping path from blocking.

    ONE function for both, because there is one property being protected.
    A second spelling is a second menu nothing is watching, which is how
    the modal that hung this suite for 40+ minutes got in.
    """
    menu.popup(at)


def _hold_menu(menu: QMenu) -> None:
    """Free a popped-up menu when it closes, and not one moment sooner.

    `popup` returns with the menu still on screen, so the `deleteLater`
    that used to sit under an `exec` would now free a menu the author is
    reading. Deferring it to `aboutToHide` frees it on the same beat
    Qt stops showing it -- via `deleteLater`, never synchronously, since
    the signal that closed it is on the stack at that moment (law 12).

    A menu whose `popup_menu` seam was replaced by a check never shows and
    so never hides: it stays parented to the widget that built it, which
    is where it was already, and dies with it.
    """
    menu.aboutToHide.connect(menu.deleteLater)


class TilePalette(QWidget):
    """Every tileset the map declares, stacked in one scrolling column.

    ONE COLUMN, NOT A CHOOSER. A dropdown made "which sheet holds this tile"
    a question the author had to answer before they could look, and the
    atlas already answers it -- `TilesetAtlas.entry_for` walks the same
    ordered list this widget lays out. Stacking is also what makes a tileset
    a NAMED, visible thing: the header is where a sheet says what it is
    called and how many tiles it has.

    A DRAG PICKS A STAMP, and it is clamped to one section: a rectangle
    spanning two tilesets would produce perfectly legal gids and a nonsense
    picture.

    THE SELECTION IS AN ADDRESS -- a tileset NAME plus a rectangle in that
    tileset's own local ids. Every command rebuilds this widget, and a
    selection keyed on position would either vanish on the first stroke or,
    worse, slide onto a different sheet's tiles when a tileset above it is
    removed.

    THE HEADER IS WHERE A TILESET IS EDITED. Right-clicking it opens the
    three verbs that address a whole sheet -- rename, grow, remove -- and
    each one is asked for through `ask`, refused HERE when it cannot be
    afforded, and emitted as `tileset_requested` for the window to run. The
    hit test is deliberately not `locate`, which clamps a header point into
    the first row of tiles and would silently name the wrong tileset.
    """

    stamp_picked = Signal(object)      # a Stamp
    add_tiles_requested = Signal()
    #: (tileset name, verb, args) -- one whole-tileset edit, already decided
    #: and already argued, for `EditorWindow.tileset_command` to run. The
    #: palette never touches the session: a widget that ran its own commands
    #: would be a second mutation point, and undo has exactly one.
    tileset_requested = Signal(str, str, dict)

    #: The header strip's height, and the gap under each section.
    HEADER = 18
    GAP = 6
    #: Integer zoom only. A fractionally scaled pixel-art picker is a blurred
    #: picker, and the tile it shows is not the tile the map will draw.
    ZOOMS = (1, 2, 3, 4)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.atlas: TilesetAtlas | None = None
        self.sections: list[PaletteSection] = []
        self.zoom = 1
        #: gid -> the mask its TILESET bakes in, from `MapCanvas.tile_masks`.
        #: Drawn over the sheet so an author can SEE which tiles are already
        #: baked: level one lives in a file beside the .tmx, and the only
        #: other readout is the All-layers overlay, which answers about map
        #: cells rather than about the tile in hand.
        self.masks: dict[int, int] = {}
        #: (tileset name, left, top, width, height) in that tileset's local
        #: ids, or None. See the class docstring.
        self.selection: tuple[str, int, int, int, int] | None = None
        self.__anchor: tuple[str, int, int] | None = None
        #: The dialog seam and the popup seam, same shape and same reason as
        #: `EditorWindow.ask`: a check replaces them on the one widget it is
        #: driving and asserts, per gesture, both that the real question is
        #: asked and that the routine path asks nothing at all.
        self.ask = ask_form
        self.popup_menu = _exec_menu
        #: `(name) -> TilesetFacts`, installed by `EditorWindow`. None until
        #: it is -- a palette with no map behind it greys its header menu
        #: with that as the reason rather than inventing two numbers.
        self.tileset_facts = None

        self.add_button = QPushButton("+  Add tiles…")
        self.add_button.setToolTip(
            "select a region of any image and add it as a named tileset")
        self.add_button.clicked.connect(self.add_tiles_requested)

        self.surface = _PaletteSurface(self)
        self.surface.setToolTip(
            "drag to pick a multi-tile stamp · ctrl+wheel zooms · "
            "alt+click on the map picks the tile under the cursor · "
            "right-click a tileset's header to rename, grow or remove it")
        # ON THE SURFACE, because that is the widget the click lands on and
        # its coordinates are the ones the sections are laid out in.
        self.surface.setContextMenuPolicy(Qt.CustomContextMenu)
        self.surface.customContextMenuRequested.connect(self.open_tileset_menu)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.surface)
        self.scroll.setWidgetResizable(False)

        self.caption = QLabel("")
        self.caption.setStyleSheet("color: palette(mid); font-size: 11px;")
        # A refusal comes down this channel (see `request_remove`), and a
        # refusal is a sentence, not a gid. Clipped to one line it would say
        # the opposite of what it means half the time.
        self.caption.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        layout.addWidget(self.add_button)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.caption)

    # -- data --------------------------------------------------------------

    def set_atlas(self, atlas: TilesetAtlas) -> None:
        self.atlas = atlas
        self.__layout()
        self.__reseat_selection()
        self.surface.rebuild()

    def set_masks(self, masks: dict[int, int]) -> None:
        """Which gids their own tileset already masks. See `masks`.

        DOES NOT REBUILD. Its one caller is `EditorWindow.refresh_all`, which
        calls `set_atlas` on the very next line, and `set_atlas` rebuilds the
        sheet unconditionally -- so the sheet is drawn once, with its badges
        already on. A second caller using this alone has to rebuild itself.
        """
        self.masks = dict(masks)

    def set_zoom(self, zoom: int) -> None:
        """Draw the sheets at `zoom` screen pixels per source pixel."""
        wanted = max(self.ZOOMS[0], min(int(zoom), self.ZOOMS[-1]))
        if wanted == self.zoom:
            return
        self.zoom = wanted
        self.__layout()
        self.surface.rebuild()
        self.__show_selection()

    def __layout(self) -> None:
        """Stack the atlas's entries into sections, top to bottom.

        THE MASK SHEET IS NOT ART, so it gets no section. Its seventeen
        glyphs are an encoding -- tile N of that sheet IS mask N -- and
        offering them beside the scenery invites an author to paint a wall
        symbol onto a floor, which is legal TMX that draws a wall symbol.
        The ATLAS still carries it, because the overlay and every piece of
        gid arithmetic need it; only this picker looks away.
        """
        self.sections = []
        if self.atlas is None:
            return
        y = 0
        for entry in self.atlas.entries:
            # The engine's own predicate, one spelling. A second way to say
            # "this is the collision tileset" is a wall the player cannot
            # feel: no error, no warning, just a sheet in the wrong list.
            if entry.name.lower() == COLLISION_TILESET:
                continue
            section = PaletteSection(
                entry=entry, cell=max(entry.tile_width, 8) * self.zoom,
                top=y, grid_top=y + self.HEADER,
                columns=max(1, entry.columns), rows=max(1, entry.rows))
            self.sections.append(section)
            y = section.bottom + self.GAP

    @property
    def surface_size(self) -> tuple[int, int]:
        if not self.sections:
            return 1, 1
        return (max(section.width for section in self.sections),
                self.sections[-1].bottom + self.GAP)

    # -- addressing --------------------------------------------------------

    def section(self, name: str) -> PaletteSection | None:
        for section in self.sections:
            if section.name == name:
                return section
        return None

    def locate(self, x: float, y: float) -> tuple[PaletteSection, int, int] | None:
        """Surface point -> the section under it and a cell inside it.

        None only above the first section or below the last. A point in a
        header, or in the gutter beside a narrow sheet, is CLAMPED into that
        section rather than dropped, so a drag that strays never silently
        stops extending.
        """
        if not self.sections:
            return None
        found = None
        for section in self.sections:
            if y >= section.top:
                found = section
            else:
                break
        if found is None or y >= self.sections[-1].bottom + self.GAP:
            return None
        return (found, ) + self.clamp(found, x, y)

    @staticmethod
    def clamp(section: PaletteSection, x: float, y: float) -> tuple[int, int]:
        """A point, as a cell of `section`, never outside its grid."""
        column = max(0, min(int(x) // section.cell, section.columns - 1))
        row = max(0, min(int(y - section.grid_top) // section.cell,
                         section.rows - 1))
        return column, row

    def header_at(self, x: float, y: float) -> PaletteSection | None:
        """Surface point -> the section whose HEADER STRIP is under it.

        NOT `locate`, and that is the whole point of it existing. `locate`
        clamps: a point in a header comes back as row 0 of that section, and
        a point in the gap under a sheet comes back as the LAST row of the
        section above -- both correct for a drag that strays and both wrong
        for a menu, which would then rename a tileset the author was not
        pointing at.

        `x` is not read because the strip is drawn across the full width of
        the surface (`_PaletteSurface.__draw_header`), including the gutter
        beside a sheet narrower than the widest one.
        """
        for section in self.sections:
            if section.top <= y < section.top + self.HEADER:
                return section
        return None

    def gid_at(self, section: PaletteSection, column: int, row: int) -> int | None:
        index = row * section.columns + column
        if not (0 <= column < section.columns
                and 0 <= index < section.entry.tile_count):
            return None
        return section.entry.first_gid + index

    def tile_point(self, name: str, column: int, row: int) -> QPointF | None:
        """The centre of one tile, in surface coordinates.

        The one mapping a caller outside this widget needs -- a check
        driving a real mouse press, and `select_gid` scrolling to a pick.
        """
        section = self.section(name)
        if section is None:
            return None
        return section.rect(column, row).center()

    # -- the header menu ---------------------------------------------------

    def facts(self, name: str) -> TilesetFacts:
        """`TilesetFacts` for one tileset. Never raises.

        The seam is a call into the document and a document can refuse to
        answer -- an external tileset declares no extent in this file, a map
        may not open at all. That refusal is carried back as `problem` and
        shown on the entries that need the numbers, because this runs inside
        a Qt handler: an exception raised here reaches the event loop, takes
        the gesture with it, and tells the author nothing.
        """
        if self.tileset_facts is None:
            return TilesetFacts(problem="this palette is not attached to a map")
        try:
            return self.tileset_facts(name)
        except Exception as exc:                                # noqa: BLE001
            return TilesetFacts(problem=f"{type(exc).__name__}: {exc}")

    def open_tileset_menu(self, point) -> None:
        """A right-click on the surface: the header menu, or nothing at all.

        Nothing at all is the common case -- most of the surface is tiles,
        where a right-click means "erase" on the map and must not mean
        "rename this sheet" here.
        """
        section = self.header_at(point.x(), point.y())
        if section is None:
            return
        menu = self.tileset_menu(section)
        # Parented, so it was never a top-level orphan -- but it would
        # outlive the click until the next collection, and this tree counts
        # widgets to catch exactly that. Freed when it CLOSES, because
        # `popup` hands the menu back still open. See `_hold_menu`.
        _hold_menu(menu)
        self.popup_menu(menu, self.surface.mapToGlobal(point))

    def tileset_menu(self, section: PaletteSection) -> QMenu:
        """The header menu for one tileset, built and not yet shown.

        Built apart from being shown for two reasons: a check can trigger an
        entry without touching a modal (law 13), and every entry's
        ENABLEMENT is a fact about the map that has to be read before the
        menu appears. A control that is present and refusing has already
        spent the click by the time the refusal arrives, so an entry that
        cannot act is disabled and carries the reason in its own label --
        where it is read on the way to the click rather than after it.
        """
        facts = self.facts(section.name)
        columns = max(1, section.entry.columns)
        menu = QMenu(self.surface)
        menu.setToolTipsVisible(True)

        rename = menu.addAction("Rename…")
        rename.setToolTip(
            "the key every tileset verb addresses this sheet by, and the "
            "name its .blitmask carries in its own header")
        rename.triggered.connect(lambda: self.request_rename(section))

        grow = menu.addAction("Grow…")
        grow.triggered.connect(lambda: self.request_grow(section))
        stopped = facts.problem or facts.growth_refusal
        if stopped:
            grow.setEnabled(False)
            grow.setText(f"Grow…  ·  {stopped}")
            grow.setToolTip(stopped)
        else:
            rows = facts.headroom // columns
            if not facts.blocked_by:
                # Nothing above it, so the headroom is the rest of the gid
                # space -- eight figures of rows, which is not a number
                # anybody is deciding with. The real limit on this one is
                # the sheet it is pointed at, and the verb owns that.
                room = "room to the top of the gid space"
            elif rows:
                room = f"room for {rows} more row{'' if rows == 1 else 's'}"
            else:
                room = f"no room before {facts.blocked_by}"
            grow.setText(f"Grow…  ·  {room}")
            grow.setToolTip(
                f"{facts.headroom} more tiles fit before "
                f"{facts.blocked_by or 'the top of the gid space'}. Rows are "
                "the only safe axis: a wider sheet renumbers every tile "
                "after the first row and repaints the map with nothing "
                "raised.")

        remove = menu.addAction("Remove")
        remove.triggered.connect(lambda: self.request_remove(section))
        if facts.problem:
            remove.setEnabled(False)
            remove.setText(f"Remove  ·  {facts.problem}")
            remove.setToolTip(facts.problem)
        elif facts.placed:
            remove.setEnabled(False)
            remove.setText(
                f"Remove  ·  {facts.placed} placed tile"
                f"{' still points' if facts.placed == 1 else 's still point'}"
                " into it")
            remove.setToolTip(
                f"{facts.where}. Clear them first: an orphaned gid raises "
                "nowhere, it resolves to whatever tileset sits below and "
                "paints the wrong art.")
        else:
            remove.setToolTip(
                "nothing points into its range. Undo puts it back verbatim, "
                "every <tile> child with it.")
        return menu

    def request_rename(self, section: PaletteSection) -> None:
        """Ask for a new name and emit the rename. See `tileset_requested`."""
        answer = self.ask(
            self, f"Rename {section.name}",
            [Field("to", "Name", "str", section.name,
                   doc="Unique within the map. No gid moves -- a name is not "
                       "part of the numbering -- but every tileset verb "
                       "addresses this sheet by it, and its .blitmask names "
                       "it in a header the engine refuses to contradict.")],
            ok_label="Rename")
        if answer is None:
            return
        wanted = str(answer["to"]).strip()
        if not wanted or wanted == section.name:
            # Not a refusal: it is the author leaving the name alone. The
            # verb answers a no-op rename with no inverse, so running it
            # would put a step in the undo list that undoes nothing.
            return
        self.tileset_requested.emit(
            section.name, "map.tileset.rename",
            {"name": section.name, "to": wanted})

    def request_grow(self, section: PaletteSection) -> None:
        """Ask for a row count and emit the growth, or refuse it here.

        REFUSED HERE when it cannot be afforded. `map.tileset.grow` refuses
        the same case with a much better sentence, and by then the author
        has spent a dialog on it -- so the headroom is quoted in the form
        BEFORE they type, and an over-ask never becomes a command at all.
        """
        entry, name = section.entry, section.name
        facts = self.facts(name)
        stopped = facts.problem or facts.growth_refusal
        if stopped:
            self.caption.setText(f"{name}: {stopped}")
            return
        columns = max(1, entry.columns)
        free = facts.headroom // columns
        room = (f"There is room for {facts.headroom} more "
                f"({free} row{'' if free == 1 else 's'}) before "
                f"{facts.blocked_by}." if facts.blocked_by else
                "Nothing sits above its range, so the only limit is the "
                "sheet it is pointed at.")
        note = (
            f"{name} owns {entry.tile_count} tiles in {columns} columns. "
            f"{room}\n"
            "Rows are the only safe axis: a taller sheet at the same width "
            "adds ids after the last one and moves nothing, while a wider "
            "one renumbers every tile after the first row.")
        answer = self.ask(
            self, f"Grow {name}",
            [Field("rows", "Rows to add", "str", "1",
                   doc="How many rows of tiles to add. Negative truncates "
                       "from the end, which is refused while anything still "
                       "points into the rows it would drop."),
             Field("image", "Sheet", "str", entry.source,
                   doc="The re-cut sheet's path AS WRITTEN INTO THE .tmx, "
                       "relative to the map. Leave it alone to keep the "
                       "current image, which can only grow into rows it "
                       "already has.")],
            ok_label="Grow", note=note)
        if answer is None:
            return
        raw = str(answer["rows"]).strip()
        try:
            rows = int(raw)
        except ValueError:
            self.caption.setText(f"{raw!r} is not a number of rows")
            return
        if rows == 0:
            self.caption.setText("0 rows is not a change")
            return
        if rows * columns > facts.headroom:
            self.caption.setText(
                f"{name} has room for {free} more row"
                f"{'' if free == 1 else 's'} ({facts.headroom} tiles) before "
                f"{facts.blocked_by or 'the top of the gid space'}, not "
                f"{rows}. Growing past it would overlap a range pytmx "
                "resolves two contradictory ways.")
            return
        count = entry.tile_count + rows * columns
        if count <= 0:
            self.caption.setText(
                f"{name} owns {entry.tile_count} tiles, so {rows} rows would "
                "leave it none. Remove it instead, which checks first that "
                "nothing still points into its range.")
            return
        args = {"name": name, "tile_count": count}
        image = str(answer["image"]).strip()
        if image and image != entry.source:
            # Only when it CHANGED. The verb measures a new sheet from its
            # own PNG header; passing dimensions from here would be this
            # widget telling the file what size it is.
            args["image"] = image
        self.tileset_requested.emit(name, "map.tileset.grow", args)

    def request_remove(self, section: PaletteSection) -> None:
        """Emit the removal, or say what is still painted with it.

        NO CONFIRMATION. Undo here is exact and byte-for-byte -- the inverse
        restores the element verbatim, every `<tile>` child with it -- and
        `editor/ui/ask.py` reserves a yes/no for what undo cannot reach.
        What DOES have to be said first is the count: the verb refuses while
        gids still point into the range, and a refusal the author could have
        read before clicking is a click taken from them.
        """
        name = section.name
        facts = self.facts(name)
        if facts.problem:
            self.caption.setText(f"{name}: {facts.problem}")
            return
        if facts.placed:
            self.caption.setText(
                f"{name} still has {facts.placed} placed tile"
                f"{'' if facts.placed == 1 else 's'} ({facts.where}). Clear "
                "them first -- an orphaned gid raises nowhere, it just "
                "paints the wrong art.")
            return
        self.tileset_requested.emit(name, "map.tileset.remove",
                                    {"name": name, "force": False})

    # -- selection ---------------------------------------------------------

    def begin_at(self, x: float, y: float) -> None:
        located = self.locate(x, y)
        if located is None:
            return
        section, column, row = located
        self.__anchor = (section.name, column, row)
        self.selection = (section.name, column, row, 1, 1)
        self.surface.update()

    def extend_at(self, x: float, y: float) -> None:
        """Grow the selection, ALWAYS inside the anchor's own section."""
        if self.__anchor is None:
            return
        name, anchor_column, anchor_row = self.__anchor
        section = self.section(name)
        if section is None:
            return
        column, row = self.clamp(section, x, y)
        left, right = sorted((anchor_column, column))
        top, bottom = sorted((anchor_row, row))
        self.selection = (name, left, top, right - left + 1, bottom - top + 1)
        self.surface.update()

    def commit(self) -> None:
        self.__anchor = None
        stamp = self.stamp()
        if stamp is None:
            return
        if all(gid <= 0 for gid in stamp.gids):
            # A rectangle entirely inside a ragged sheet's short last row.
            # Emitting it would set a brush that paints nothing and, in
            # collision mode, aim a mask at no tile at all -- both of which
            # look exactly like a click that worked.
            self.caption.setText("that rectangle holds no tiles")
            return
        self.stamp_picked.emit(stamp)
        # CAPTIONED AFTER THE EMIT: in collision mode that signal is what
        # writes the mask, and `refresh_all` hands this widget the new
        # mapping on its way back. Captioning first would show the author the
        # mask their own click had just replaced.
        self.caption.setText(self.describe(stamp))

    def stamp(self) -> Stamp | None:
        """The current selection as a Stamp, or None when there is none."""
        if self.selection is None:
            return None
        name, left, top, width, height = self.selection
        section = self.section(name)
        if section is None:
            return None
        rows: list[list[int]] = []
        for row in range(top, top + height):
            # -1 means "leave this cell alone" -- a ragged selection at the
            # end of a tileset stays a rectangle with holes rather than
            # silently shrinking.
            rows.append([self.gid_at(section, column, row) or -1
                         for column in range(left, left + width)])
        if not rows or not rows[0]:
            return None
        return Stamp.from_rows(rows)

    def describe(self, stamp: Stamp) -> str:
        """The caption for a pick: what it is, and what it already carries.

        Names the tiles it REALLY holds, not the size of the rectangle. A
        drag off the end of a sheet is a legal pick made mostly of holes,
        and captioning that `11×3` says the opposite of what it does.
        """
        real = sum(1 for gid in stamp.gids if gid > 0)
        if stamp.is_single:
            head = f"gid {stamp.primary}"
        else:
            head = (f"{stamp.width}×{stamp.height}  ·  {real} tiles from gid "
                    f"{stamp.primary}")
            empty = stamp.width * stamp.height - real
            if empty:
                head += f"  ({empty} empty)"
        mask = self.masks.get(stamp.primary)
        return head if mask is None else f"{head}  ·  {describe_mask(mask)}"

    def selection_rect(self) -> tuple[int, int, int, int] | None:
        """The selection in its own tileset's local ids, without the name."""
        if self.selection is None:
            return None
        return self.selection[1:]

    def selection_section(self) -> PaletteSection | None:
        return None if self.selection is None else self.section(self.selection[0])

    def __reseat_selection(self) -> None:
        """Keep the highlight on the SAME tiles across a rebuild.

        Keyed on the tileset's name, so adding or removing another tileset
        moves nothing. A selection whose tileset is gone is dropped rather
        than clamped onto whatever now sits at that index.
        """
        if self.selection is None:
            return
        name, left, top, width, height = self.selection
        section = self.section(name)
        if section is None:
            self.selection = None
            return
        left = max(0, min(left, section.columns - 1))
        top = max(0, min(top, section.rows - 1))
        self.selection = (name, left, top,
                          max(1, min(width, section.columns - left)),
                          max(1, min(height, section.rows - top)))

    def select_gid(self, gid: int) -> None:
        """Move the highlight to a gid chosen elsewhere (the canvas picker)."""
        if self.atlas is None:
            return
        entry = self.atlas.entry_for(gid)
        section = self.section(entry.name) if entry is not None else None
        if section is None:
            return
        offset = gid - section.entry.first_gid
        self.selection = (section.name, offset % section.columns,
                          offset // section.columns, 1, 1)
        self.caption.setText(self.describe(Stamp.single(gid)))
        self.surface.update()
        self.__show_selection()

    def __show_selection(self) -> None:
        """Scroll the highlight into view.

        A picker that moved a highlight the author cannot see has, from
        where they are sitting, done nothing at all.
        """
        section = self.selection_section()
        if section is None:
            return
        _name, left, top, width, height = self.selection
        rect = section.rect(left, top).united(
            section.rect(left + width - 1, top + height - 1))
        self.scroll.ensureVisible(int(rect.center().x()),
                                  int(rect.center().y()),
                                  int(rect.width() / 2) + 8,
                                  int(rect.height() / 2) + 8)


class _PaletteSurface(QWidget):
    """The drawn stack. Split out so the palette can own scrolling."""

    #: The header strip and its text. Fixed rather than themed, like the
    #: sheet background: these sit against tile art, not against the window.
    HEADER_FILL = QColor(46, 46, 56)
    HEADER_TEXT = QColor(226, 226, 236)
    HEADER_DIM = QColor(150, 150, 165)
    SHEET_FILL = QColor(20, 20, 24)

    def __init__(self, palette: TilePalette):
        super().__init__()
        self.palette = palette
        self.__pixmap: QPixmap | None = None
        self.setMouseTracking(True)

    def rebuild(self) -> None:
        width, height = self.palette.surface_size
        pixmap = QPixmap(width, height)
        pixmap.fill(self.SHEET_FILL)
        painter = QPainter(pixmap)
        for section in self.palette.sections:
            self.__draw_header(painter, section, width)
            self.__draw_sheet(painter, section)
        painter.end()
        self.__pixmap = pixmap
        self.resize(pixmap.size())
        self.update()

    def __draw_header(self, painter: QPainter, section: PaletteSection,
                      width: int) -> None:
        strip = QRectF(0, section.top, width, TilePalette.HEADER)
        painter.fillRect(strip, self.HEADER_FILL)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.HEADER_TEXT)
        painter.drawText(strip.adjusted(5, 0, -5, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, section.name)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(self.HEADER_DIM)
        count = f"{section.entry.tile_count} tiles"
        if section.entry.image is None:
            count += "  ·  no art"
        painter.drawText(strip.adjusted(5, 0, -5, 0),
                         Qt.AlignVCenter | Qt.AlignRight, count)

    def __draw_sheet(self, painter: QPainter, section: PaletteSection) -> None:
        entry = section.entry
        masks = self.palette.masks
        # The overlay's OWN glyphs, at this section's cell size -- a second
        # drawing of "blocks left and right" would be two pictures of one
        # mask, drifting apart.
        glyphs = glyph_pixmaps(section.cell, section.cell) if masks else {}
        for index in range(entry.tile_count):
            gid = entry.first_gid + index
            x = (index % section.columns) * section.cell
            y = section.grid_top + (index // section.columns) * section.cell
            tile = self.palette.atlas.pixmap(gid)
            if tile is not None:
                painter.drawPixmap(x, y, section.cell, section.cell, tile)
            else:
                painter.fillRect(x, y, section.cell, section.cell,
                                 gid_colour(gid))
            mask = masks.get(gid)
            if mask is None:
                continue
            glyph = glyphs.get(mask)
            if glyph is not None:
                painter.drawPixmap(x, y, glyph)
            # And the frame, whatever the glyph drew -- see `_BAKED_PEN`.
            painter.setPen(QPen(_BAKED_PEN, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(x, y, section.cell - 1, section.cell - 1)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self.__pixmap is not None:
            painter.drawPixmap(0, 0, self.__pixmap)
        section = self.palette.selection_section()
        if section is not None:
            _name, left, top, width, height = self.palette.selection
            rect = section.rect(left, top).united(
                section.rect(left + width - 1, top + height - 1))
            painter.setPen(QPen(QColor(120, 200, 255), 2))
            painter.setBrush(QBrush(QColor(120, 200, 255, 50)))
            painter.drawRect(rect)
        painter.end()

    def wheelEvent(self, event) -> None:                          # noqa: N802
        """Ctrl+wheel zooms; a plain wheel scrolls the stack.

        The other way round on a column holding every tileset in the map
        would make the one gesture that reaches the bottom of the list also
        the one that changes its size.
        """
        if not (event.modifiers() & Qt.ControlModifier):
            event.ignore()
            return
        step = 1 if event.angleDelta().y() > 0 else -1
        self.palette.set_zoom(self.palette.zoom + step)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self.palette.begin_at(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.palette.extend_at(event.position().x(), event.position().y())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.palette.commit()
