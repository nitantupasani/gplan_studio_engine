"""Frontend Building payload -> multi-storey StructuralModel (spec section 6).

This adapter is the one place camelCase is read. Everything it writes is SI
metres in the model's y-down plan frame, storey 0 = ground.

What it derives, in the order the spec fixes:

1. storeys from `totalFloors`, storey i taking `floors[i]` POSITIONALLY,
   a missing upper floor repeating the last `kind:"units"` floor
   (W_TYPICAL_REPEATED); `kind:"stilt"` becomes StoreyKind.STILT.
   `floorNumber` is the frontend's 1-based HUMAN label (buildingSlice writes
   `i + 1`), never the 0-based storey index: it orders the list, nothing more.
2. the `boundary` (rect or rectilinear polygon) as an exterior wall loop.
3. unit envelopes from the DECLARED unit rect, merged with each other and with
   corridor edges at max(t1,t2)/2 into single party/interior walls.
4. unit interiors: a dressed `detailedPlan` when present (rooms + real doors
   and windows, provenance `dressed`), else the pinned UnitFloorplan's room
   placements with mid-wall doors assumed at 0.9 m, else one interior_unknown
   RoomPoly per unit (W_UNIT_NO_PLAN). A plan whose extent disagrees with the
   unit rect is scaled by one uniform factor and centred in that rect, the rule
   the frontend draws it by, and the rescale is disclosed (W_STALE_GENERATED).
5. the normative rotation transform for 0/90/180/270. No frontend view applies
   `unit.rotation`, so a non-zero one is disclosed as well: the convention
   across that boundary is an open product decision, not settled here.
6. corridors as corridor-occupancy RoomPolys plus their edge walls.
7. `fixedElements` as Cores present on every storey.

Grid axes are NOT derived here: grid.py owns them. The client `structuralGrid`
is stored verbatim under `meta.client_grid` and never imported as geometry.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..model import (
    GEOM_TOL_M,
    Core,
    CoreKind,
    Material,
    ModelSource,
    Occupancy,
    Opening,
    OpeningKind,
    Provenance,
    RoomPoly,
    Storey,
    StoreyKind,
    StructuralModel,
    System,
    WallLine,
    WallRole,
    core_id,
    ft_to_m,
    m_to_ft,
    opening_id,
    room_id,
    wall_id,
)

from ._geom import AdapterError, fingerprint
from .plan_json import occupancy_for_name

XY = Tuple[float, float]

# --------------------------------------------------------------------------
# defaults (feet at the wire edge, converted once)
# --------------------------------------------------------------------------

DEFAULT_STOREY_HEIGHT_FT = 10.0
DEFAULT_EXTERIOR_WALL_FT = 0.75
DEFAULT_INTERIOR_WALL_FT = 0.4
DEFAULT_RAILING_WALL_FT = 0.35

# Finding 10: one door width for every adapter, 0.9 m, mid-wall.
ASSUMED_DOOR_WIDTH_M = 0.9
ASSUMED_WINDOW_WIDTH_M = 1.2
# A shared run shorter than the assumed 0.9 m door cannot receive that door.
# Such runs remain adjacency shortfalls instead of producing an opening that
# overhangs both ends of its wall.
MIN_DOOR_SHARE_FT = m_to_ft(ASSUMED_DOOR_WIDTH_M)
# openingsOnWallLoose precedent: a dressed door maps to a wall within this.
DOOR_LINE_TOL_FT = 0.45
# PLOT_FIT_EPS class (housing.py STALE_EPS_M): below this the declared unit
# rect and the plan extent are the same rect and no rescale is applied.
PLAN_FIT_EPS_FT = 0.15

_ROTATIONS = (0, 90, 180, 270)

# A room's only access is never routed through one of these when another
# reached room shares a doorable wall with it.
_POOR_PARENTS = frozenset(
    [
        Occupancy.BALCONY,
        Occupancy.BATH,
        Occupancy.WC,
        Occupancy.UTILITY,
        Occupancy.STORAGE,
        Occupancy.PARKING,
        Occupancy.GREEN,
        Occupancy.VOID,
    ]
)

_CORE_KINDS = {
    "staircase": CoreKind.STAIRS,
    "stairs": CoreKind.STAIRS,
    "stair": CoreKind.STAIRS,
    "lift": CoreKind.LIFT,
    "elevator": CoreKind.LIFT,
    "utility_shaft": CoreKind.UTILITY_SHAFT,
    "shaft": CoreKind.UTILITY_SHAFT,
    "fire_exit": CoreKind.FIRE_EXIT,
}

# DetailedFloorplan RoomKind -> Occupancy: the dressed payload states the kind,
# so it is read before any name. Names go to plan_json.occupancy_for_name, the
# adapter layer's single synonym table (finding 22).
_ROOM_KINDS = {
    "living": Occupancy.HABITABLE,
    "bedroom": Occupancy.HABITABLE,
    "dining": Occupancy.HABITABLE,
    "study": Occupancy.HABITABLE,
    "kitchen": Occupancy.KITCHEN,
    "bath": Occupancy.BATH,
    "balcony": Occupancy.BALCONY,
    "utility": Occupancy.UTILITY,
}

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _dim(value: float) -> str:
    """One dimension in a disclosure message, 2 dp, no trailing noise."""
    return "%.2f" % round(float(value), 2)


def _slug(text: str) -> str:
    out = []
    for ch in str(text).strip().lower():
        out.append(ch if (ch.isalnum() or ch in "-_") else "_")
    slug = "".join(out).strip("_")
    return slug or "x"


def _rect_polygon(x: float, y: float, w: float, h: float) -> List[XY]:
    """Rect corners as a y-down positive-shoelace loop, no closing vertex."""
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _shoelace(points: Sequence[Sequence[float]]) -> float:
    total = 0.0
    count = len(points)
    for i in range(count):
        ax, ay = points[i][0], points[i][1]
        bx, by = points[(i + 1) % count][0], points[(i + 1) % count][1]
        total += ax * by - bx * ay
    return 0.5 * total


def _as_positive_loop(points: Sequence[XY]) -> List[XY]:
    loop = [(float(p[0]), float(p[1])) for p in points]
    if _shoelace(loop) < 0.0:
        loop.reverse()
    return loop


def _polygon_area(points: Sequence[XY]) -> float:
    return abs(_shoelace(points))


def _bbox(points: Sequence[XY]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _occupancy_for(name: str, kind: Optional[str] = None) -> Tuple[Occupancy, bool]:
    """(occupancy, recognized). `kind` is the dressed plan's RoomKind when given."""
    if kind:
        mapped = _ROOM_KINDS.get(str(kind).strip().lower())
        if mapped is not None:
            return (mapped, True)
    parsed = occupancy_for_name(name)
    if parsed is not None:
        return (parsed, True)
    return (Occupancy.OTHER, False)


def _point_mapper(rotation: int, ox: float, oy: float, w: float, h: float) -> Callable[[XY], XY]:
    """Normative local-plan -> floor-frame point map (spec section 6 step 5).

    (W, H) is the LOCAL plan size, (ox, oy) the unit origin, both y-down feet.
    The rect maps of the spec table follow from this point map exactly:
      rot 0   (X+x,          Y+y,          w, h)
      rot 90  (X+H-y-h,      Y+x,          h, w)
      rot 180 (X+W-x-w,      Y+H-y-h,      w, h)
      rot 270 (X+y,          Y+W-x-w,      h, w)
    """
    if rotation == 0:
        return lambda p: (ox + p[0], oy + p[1])
    if rotation == 90:
        return lambda p: (ox + h - p[1], oy + p[0])
    if rotation == 180:
        return lambda p: (ox + w - p[0], oy + h - p[1])
    return lambda p: (ox + p[1], oy + w - p[0])


def _scaled_mapper(
    rotation: int, ox: float, oy: float, w: float, h: float, scale: float
) -> Callable[[XY], XY]:
    """`_point_mapper` on a plan first scaled uniformly about its own origin.

    (w, h) is the UNSCALED local plan size; the caller has already moved
    (ox, oy) to the scaled plan's top-left corner in the floor frame.
    """
    inner = _point_mapper(rotation, ox, oy, w * scale, h * scale)
    if scale == 1.0:
        return inner

    def mapped(point: XY) -> XY:
        return inner((point[0] * scale, point[1] * scale))

    return mapped


def _flip_orientation(orientation: str, rotation: int) -> str:
    """Door/window axis under the rotation: h<->v on 90 and 270."""
    axis = "v" if str(orientation).lower().startswith("v") else "h"
    if rotation in (90, 270):
        return "h" if axis == "v" else "v"
    return axis


# --------------------------------------------------------------------------
# wall segments and the merge
# --------------------------------------------------------------------------

_OWNER_RANK = {"boundary": 0, "unit": 1, "corridor": 2, "room": 3}


@dataclass
class _Seg:
    """One candidate wall run in the floor frame, metres."""

    orient: str  # "h" (constant y) or "v" (constant x)
    pos: float
    s0: float
    s1: float
    thickness: float
    owner_kind: str
    owner: str
    room_lo: Optional[str] = None
    room_hi: Optional[str] = None
    source: Optional[str] = None

    def sort_key(self) -> Tuple[int, float, float, str]:
        return (_OWNER_RANK.get(self.owner_kind, 9), self.pos, self.s0, self.owner)


@dataclass
class _PendingOpening:
    """An opening in the floor frame, waiting for the wall it belongs to."""

    orient: str
    line: float
    centre: float
    width: float
    kind: OpeningKind
    provenance: Provenance
    sill: Optional[float] = None
    head: Optional[float] = None
    label: str = ""


@dataclass
class _UnitBuild:
    """Everything one unit contributes to its storey."""

    key: str
    unit_id: str
    rooms: List[RoomPoly] = field(default_factory=list)
    segments: List[_Seg] = field(default_factory=list)
    openings: List[_PendingOpening] = field(default_factory=list)
    dressed: bool = False
    has_plan: bool = False
    footprint: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # non-empty only when the adapter's geometry is not what the client draws
    rescale_note: str = ""
    rotation_note: str = ""


def _rect_segments(
    x: float,
    y: float,
    w: float,
    h: float,
    thickness: float,
    owner_kind: str,
    owner: str,
    source: Optional[str],
) -> List[_Seg]:
    """The four edges of a rect as ownership segments (no room sides)."""
    return [
        _Seg("h", y, x, x + w, thickness, owner_kind, owner, source=source),
        _Seg("h", y + h, x, x + w, thickness, owner_kind, owner, source=source),
        _Seg("v", x, y, y + h, thickness, owner_kind, owner, source=source),
        _Seg("v", x + w, y, y + h, thickness, owner_kind, owner, source=source),
    ]


def _room_segments(polygon: Sequence[XY], rid: str, thickness: float, source: Optional[str]) -> List[_Seg]:
    """Edges of a positive-shoelace rectilinear room loop, room on its own side.

    In this y-down frame a positive loop runs clockwise as drawn, so the room
    lies on the higher-coordinate side of a +x horizontal edge and of a -y
    vertical edge, and on the lower side of the other two.
    """
    segs = []  # type: List[_Seg]
    count = len(polygon)
    for i in range(count):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % count]
        if abs(ay - by) <= GEOM_TOL_M and abs(ax - bx) > GEOM_TOL_M:
            lo, hi = (rid, None) if bx < ax else (None, rid)
            segs.append(_Seg("h", 0.5 * (ay + by), min(ax, bx), max(ax, bx), thickness, "room", rid, lo, hi, source))
        elif abs(ax - bx) <= GEOM_TOL_M and abs(ay - by) > GEOM_TOL_M:
            lo, hi = (rid, None) if by > ay else (None, rid)
            segs.append(_Seg("v", 0.5 * (ax + bx), min(ay, by), max(ay, by), thickness, "room", rid, lo, hi, source))
    return segs


def _cluster(segments: List[_Seg]) -> List[List[_Seg]]:
    """Group collinear segments whose centrelines sit within max(t1,t2)/2."""
    clusters = []  # type: List[List[_Seg]]
    current = []  # type: List[_Seg]
    last_pos = 0.0
    last_thickness = 0.0
    for seg in sorted(segments, key=lambda s: (s.pos, s.s0, s.s1, s.owner)):
        if current:
            tolerance = 0.5 * max(last_thickness, seg.thickness)
            if seg.pos - last_pos > tolerance + GEOM_TOL_M:
                clusters.append(current)
                current = []
        current.append(seg)
        last_pos = seg.pos
        last_thickness = seg.thickness
    if current:
        clusters.append(current)
    return clusters


def _role_for(covering: Sequence[_Seg]) -> WallRole:
    units = {s.owner for s in covering if s.owner_kind == "unit"}
    corridors = {s.owner for s in covering if s.owner_kind == "corridor"}
    if any(s.owner_kind == "boundary" for s in covering):
        return WallRole.EXTERIOR
    if len(units) >= 2:
        return WallRole.PARTY
    if units and corridors:
        return WallRole.INTERIOR
    if units:
        return WallRole.EXTERIOR
    return WallRole.INTERIOR


def _merge_walls(segments: List[_Seg], storey: int) -> List[WallLine]:
    """Split every cluster at its breakpoints, then re-join identical runs.

    `room_lo` / `room_hi` are the rooms on the low and high side of the
    centreline. `WallLine.room_ids` is (left, right) by the wall normal, the
    left normal of (dx, dy) being (dy, -dx) in this y-down frame, so a
    horizontal wall reads (above, below) = (lo, hi) while a VERTICAL wall reads
    (right, left) = (hi, lo). Emitting (lo, hi) for both mirrored every
    vertical wall against model.py, plan_json.py, housing.py and spec 01.
    """
    walls = []  # type: List[WallLine]
    for orient in ("h", "v"):
        for cluster in _cluster([s for s in segments if s.orient == orient]):
            edges = sorted({round(v, 9) for s in cluster for v in (s.s0, s.s1)})
            runs = []  # type: List[Dict[str, Any]]
            for i in range(len(edges) - 1):
                lo, hi = edges[i], edges[i + 1]
                if hi - lo <= GEOM_TOL_M:
                    continue
                covering = [s for s in cluster if s.s0 <= lo + GEOM_TOL_M and s.s1 >= hi - GEOM_TOL_M]
                if not covering:
                    continue
                strongest = sorted(covering, key=lambda s: s.sort_key())[0]
                room_lo = next((s.room_lo for s in sorted(covering, key=lambda s: s.sort_key()) if s.room_lo), None)
                room_hi = next((s.room_hi for s in sorted(covering, key=lambda s: s.sort_key()) if s.room_hi), None)
                attrs = {
                    "pos": strongest.pos,
                    "thickness": max(s.thickness for s in covering),
                    "role": _role_for(covering),
                    "room_lo": room_lo,
                    "room_hi": room_hi,
                    "source": strongest.source,
                }
                if runs and runs[-1]["attrs"] == attrs and abs(runs[-1]["s1"] - lo) <= GEOM_TOL_M:
                    runs[-1]["s1"] = hi
                else:
                    runs.append({"s0": lo, "s1": hi, "attrs": attrs})
            for run in runs:
                attrs = run["attrs"]
                pos, s0, s1 = attrs["pos"], run["s0"], run["s1"]
                a, b = ((s0, pos), (s1, pos)) if orient == "h" else ((pos, s0), (pos, s1))
                sides = (attrs["room_lo"], attrs["room_hi"])
                if orient == "v":
                    sides = (attrs["room_hi"], attrs["room_lo"])
                walls.append(
                    WallLine(
                        id=wall_id(storey, orient, pos, s0),
                        storey=storey,
                        a=a,
                        b=b,
                        thickness_m=attrs["thickness"],
                        role=attrs["role"],
                        material=Material.BRICK_MASONRY,
                        bearing=None,
                        room_ids=sides,
                        source=attrs["source"],
                    )
                )
    return _uniquify(walls)


def _uniquify(walls: List[WallLine]) -> List[WallLine]:
    """Ids are geometry-derived at 2 dp of a foot; keep them unique regardless."""
    seen = {}  # type: Dict[str, int]
    for wall in sorted(walls, key=lambda w: (w.id, w.a, w.b)):
        if wall.id in seen:
            seen[wall.id] += 1
            wall.id = wall.id + "-" + str(seen[wall.id])
        else:
            seen[wall.id] = 0
    return sorted(walls, key=lambda w: w.id)


def _wall_axis(wall: WallLine) -> Tuple[str, float, float, float]:
    ax, ay = wall.a
    bx, by = wall.b
    if abs(ay - by) <= GEOM_TOL_M:
        return ("h", 0.5 * (ay + by), min(ax, bx), max(ax, bx))
    return ("v", 0.5 * (ax + bx), min(ay, by), max(ay, by))


def _wall_length(wall: WallLine) -> float:
    axis = _wall_axis(wall)
    return axis[3] - axis[2]


# --------------------------------------------------------------------------
# payload readers (camelCase stops here)
# --------------------------------------------------------------------------


def _unwrap(building: Any) -> Dict[str, Any]:
    if isinstance(building, dict) and isinstance(building.get("building"), dict):
        building = building["building"]
    if not isinstance(building, dict):
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "building payload must be an object, got " + type(building).__name__,
            {},
        )
    if "boundary" not in building:
        raise AdapterError("E_BAD_ENVELOPE", "building payload carries no boundary", {})
    return building


def _boundary_polygon_ft(boundary: Any) -> List[XY]:
    """Boundary as a rectilinear loop in FEET; refuses anything else."""
    if not isinstance(boundary, dict):
        raise AdapterError("E_BAD_ENVELOPE", "boundary must be an object", {})
    points = boundary.get("points")
    if boundary.get("kind") == "polygon" or points:
        raw = [(_num(p[0]), _num(p[1])) for p in (points or []) if len(p) >= 2]
        loop = []  # type: List[XY]
        for point in raw:
            if loop and abs(point[0] - loop[-1][0]) <= 1e-6 and abs(point[1] - loop[-1][1]) <= 1e-6:
                continue
            loop.append(point)
        if len(loop) > 1 and abs(loop[0][0] - loop[-1][0]) <= 1e-6 and abs(loop[0][1] - loop[-1][1]) <= 1e-6:
            loop.pop()
        if len(loop) < 4:
            raise AdapterError("E_EMPTY_PLAN", "polygon boundary needs at least four corners", {})
        count = len(loop)
        for i in range(count):
            ax, ay = loop[i]
            bx, by = loop[(i + 1) % count]
            flat_x = abs(bx - ax) <= 1e-6
            flat_y = abs(by - ay) <= 1e-6
            if flat_x == flat_y:
                raise AdapterError(
                    "E_BOUNDARY_NOT_RECTILINEAR",
                    "boundary edge " + str(i) + " from " + repr(loop[i]) + " to " + repr(loop[(i + 1) % count]) + " is not axis aligned",
                    {"edge": i},
                )
        return _as_positive_loop(loop)
    width = _num(boundary.get("width"))
    height = _num(boundary.get("height"))
    if width <= 0.0 or height <= 0.0:
        raise AdapterError("E_EMPTY_PLAN", "rect boundary has no area", {"width": width, "height": height})
    return _rect_polygon(0.0, 0.0, width, height)


def _rotation_of(unit: Dict[str, Any], unit_label: str) -> int:
    raw = unit.get("rotation", 0) or 0
    try:
        rotation = int(round(float(raw))) % 360
    except (TypeError, ValueError):
        rotation = -1
    if rotation not in _ROTATIONS:
        raise AdapterError(
            "E_BAD_ROTATION",
            "unit " + unit_label + " carries rotation " + repr(raw) + "; only 0, 90, 180 and 270 are supported",
            {"unit": unit_label, "rotation": raw},
        )
    return rotation


def _resolve_plan(unit: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(dressed detailedPlan or None, pinned UnitFloorplan or None)."""
    plans = [p for p in (unit.get("floorplans") or []) if isinstance(p, dict)]
    pinned = None  # type: Optional[Dict[str, Any]]
    saved_id = unit.get("savedFloorplanId")
    if saved_id:
        pinned = next((p for p in plans if p.get("id") == saved_id), None)
    if pinned is None and plans:
        index = int(_num(unit.get("activeFloorplanIndex"), 0.0))
        pinned = plans[index] if 0 <= index < len(plans) else plans[0]

    detailed = unit.get("detailedPlan")
    if isinstance(detailed, dict) and detailed.get("rooms"):
        return (detailed, pinned)
    if pinned is not None:
        nested = pinned.get("detailedPlan")
        if isinstance(nested, dict) and nested.get("rooms"):
            return (nested, pinned)
    return (None, pinned)


def _local_rooms(source: Sequence[Dict[str, Any]], unit_key: str, dressed: bool) -> List[Dict[str, Any]]:
    """Normalize PlanRoom / FloorplanPlacement dicts to local-feet room records."""
    records = []  # type: List[Dict[str, Any]]
    ordered = sorted(
        [r for r in source if isinstance(r, dict)],
        key=lambda r: (_num(r.get("x")), _num(r.get("y")), _text(r.get("name")), _text(r.get("id"))),
    )
    for index, raw in enumerate(ordered):
        x, y = _num(raw.get("x")), _num(raw.get("y"))
        w, h = _num(raw.get("width")), _num(raw.get("height"))
        if w <= 0.0 or h <= 0.0:
            continue
        outline = raw.get("outline")
        if isinstance(outline, (list, tuple)) and len(outline) >= 4:
            polygon = [(_num(p[0]), _num(p[1])) for p in outline if len(p) >= 2]
        else:
            polygon = _rect_polygon(x, y, w, h)
        name = _text(raw.get("name"), "Room")
        if dressed and raw.get("id"):
            token = _slug(_text(raw.get("id")))
        else:
            token = _slug(name) + "-" + str(index)
        records.append(
            {
                "source_id": unit_key + "-" + token,
                "name": name,
                "kind": raw.get("kind"),
                "polygon": polygon,
                "raw_id": _text(raw.get("id"), ""),
            }
        )
    return records


def _local_openings(plan: Dict[str, Any], unit_label: str) -> List[Dict[str, Any]]:
    """Dressed doors and windows as local-feet records, sorted for determinism."""
    records = []  # type: List[Dict[str, Any]]
    for door in sorted(
        [d for d in (plan.get("doors") or []) if isinstance(d, dict)],
        key=lambda d: (_num(d.get("x")), _num(d.get("y")), _text(d.get("id"))),
    ):
        if door.get("entrance"):
            kind = OpeningKind.ENTRY
        elif door.get("opening"):
            kind = OpeningKind.OPENING
        else:
            kind = OpeningKind.DOOR
        records.append(
            {
                "orientation": _text(door.get("orientation"), "h"),
                "x": _num(door.get("x")),
                "y": _num(door.get("y")),
                "width": _num(door.get("width"), m_to_ft(ASSUMED_DOOR_WIDTH_M)),
                "kind": kind,
                "sill": None,
                "head": None,
                "label": unit_label + " door " + _text(door.get("id"), "?"),
            }
        )
    for window in sorted(
        [w for w in (plan.get("windows") or []) if isinstance(w, dict)],
        key=lambda w: (_num(w.get("x")), _num(w.get("y")), _text(w.get("id"))),
    ):
        records.append(
            {
                "orientation": _text(window.get("orientation"), "h"),
                "x": _num(window.get("x")),
                "y": _num(window.get("y")),
                "width": _num(window.get("width"), m_to_ft(ASSUMED_WINDOW_WIDTH_M)),
                "kind": OpeningKind.WINDOW,
                "sill": window.get("sillFt"),
                "head": window.get("headFt"),
                "label": unit_label + " window " + _text(window.get("id"), "?"),
            }
        )
    return records


# --------------------------------------------------------------------------
# storey content
# --------------------------------------------------------------------------


@dataclass
class _Options:
    exterior_m: float
    interior_m: float
    railing_m: float
    assume_windows: bool
    occupancy_map: Dict[str, str]


def _to_m(points: Sequence[XY]) -> List[XY]:
    return [(ft_to_m(p[0]), ft_to_m(p[1])) for p in points]


def _occupancy_of(record: Dict[str, Any], options: _Options, unknown: List[str]) -> Occupancy:
    override = options.occupancy_map.get(record["raw_id"]) or options.occupancy_map.get(record["name"])
    if override:
        try:
            return Occupancy(override)
        except ValueError:
            unknown.append(record["name"] + " (override " + str(override) + ")")
            return Occupancy.OTHER
    occupancy, known = _occupancy_for(record["name"], record.get("kind"))
    if not known:
        unknown.append(record["name"])
    return occupancy


def _build_unit(
    unit: Dict[str, Any],
    storey: int,
    index: int,
    options: _Options,
    unknown: List[str],
) -> _UnitBuild:
    """One unit's rooms, wall segments and dressed openings, in metres."""
    unit_id = _text(unit.get("id")) or ("u" + str(index))
    label = _text(unit.get("name")) or unit_id
    key = "unit-s" + str(storey) + "-" + unit_id
    build = _UnitBuild(key=key, unit_id=unit_id)

    rotation = _rotation_of(unit, label)
    detailed, pinned = _resolve_plan(unit)
    unit_w, unit_h = _num(unit.get("width")), _num(unit.get("height"))

    exterior_ft = m_to_ft(options.exterior_m)
    interior_ft = m_to_ft(options.interior_m)
    records = []  # type: List[Dict[str, Any]]
    openings = []  # type: List[Dict[str, Any]]

    if detailed is not None:
        plan_w = _num(detailed.get("width")) or _num((pinned or {}).get("floorWidth")) or unit_w
        plan_h = _num(detailed.get("height")) or _num((pinned or {}).get("floorHeight")) or unit_h
        records = _local_rooms(detailed.get("rooms") or [], unit_id, True)
        openings = _local_openings(detailed, label)
        exterior_ft = _num(detailed.get("exteriorWall")) or exterior_ft
        interior_ft = _num(detailed.get("interiorWall")) or interior_ft
        build.dressed = True
    elif pinned is not None and pinned.get("placements"):
        plan_w = _num(pinned.get("floorWidth")) or unit_w
        plan_h = _num(pinned.get("floorHeight")) or unit_h
        records = _local_rooms(pinned.get("placements") or [], unit_id, False)
    else:
        plan_w, plan_h = unit_w, unit_h

    build.has_plan = bool(records)
    origin_x, origin_y = _num(unit.get("x")), _num(unit.get("y"))
    scale = 1.0
    if build.has_plan:
        mapped_w, mapped_h = (plan_h, plan_w) if rotation in (90, 270) else (plan_w, plan_h)
        if mapped_w <= 0.0 or mapped_h <= 0.0 or unit_w <= 0.0 or unit_h <= 0.0:
            return build
        scale = min(unit_w / mapped_w, unit_h / mapped_h)
        placed_w, placed_h = mapped_w * scale, mapped_h * scale
        placed_x = origin_x + 0.5 * (unit_w - placed_w)
        placed_y = origin_y + 0.5 * (unit_h - placed_h)
        mapper = _scaled_mapper(rotation, placed_x, placed_y, plan_w, plan_h, scale)
        # The unit rect is the declared envelope even when its interior plan
        # was authored for another extent. This is the same fit-and-centre rule
        # the frontend uses to draw the plan inside its unit.
        ex, ey, ew, eh = origin_x, origin_y, unit_w, unit_h
        if abs(mapped_w - unit_w) > PLAN_FIT_EPS_FT or abs(mapped_h - unit_h) > PLAN_FIT_EPS_FT:
            build.rescale_note = (
                label
                + " plan "
                + _dim(plan_w)
                + " x "
                + _dim(plan_h)
                + " ft was fitted to "
                + _dim(unit_w)
                + " x "
                + _dim(unit_h)
                + " ft unit rect at scale "
                + format(scale, ".3f")
            )
        if rotation:
            build.rotation_note = label + " rotated " + str(rotation) + " deg"
    else:
        mapper = _point_mapper(rotation, origin_x, origin_y, plan_w, plan_h)
        extent = _rect_polygon(origin_x, origin_y, unit_w, unit_h)
        ex, ey, ew, eh = _bbox(extent)
    build.footprint = (ex, ey, ew, eh)

    if ew <= 0.0 or eh <= 0.0:
        return build

    build.segments.extend(
        _rect_segments(
            ft_to_m(ex),
            ft_to_m(ey),
            ft_to_m(ew),
            ft_to_m(eh),
            ft_to_m(exterior_ft),
            "unit",
            unit_id,
            unit_id,
        )
    )

    if not build.has_plan:
        # No interior plan: one interior_unknown RoomPoly, loads apply a
        # partition allowance instead of wall line loads (finding 39).
        polygon = _to_m(_rect_polygon(ex, ey, ew, eh))
        rid = room_id(storey, unit_id)
        build.rooms.append(
            RoomPoly(
                id=rid,
                storey=storey,
                name="unit:" + _text(unit.get("type"), "unknown"),
                occupancy=Occupancy.OTHER,
                polygon=polygon,
                area_m2=_polygon_area(polygon),
                unit_id=key,
                interior_unknown=True,
                source=unit_id,
            )
        )
        build.segments.extend(_room_segments(polygon, rid, ft_to_m(exterior_ft), unit_id))
        return build

    for record in records:
        polygon = _as_positive_loop(_to_m([mapper(p) for p in record["polygon"]]))
        rid = room_id(storey, record["source_id"])
        build.rooms.append(
            RoomPoly(
                id=rid,
                storey=storey,
                name=record["name"],
                occupancy=_occupancy_of(record, options, unknown),
                polygon=polygon,
                area_m2=_polygon_area(polygon),
                unit_id=key,
                interior_unknown=False,
                source=record["raw_id"] or record["source_id"],
            )
        )
        build.segments.extend(_room_segments(polygon, rid, ft_to_m(interior_ft), record["source_id"]))

    for record in openings:
        orient = _flip_orientation(record["orientation"], rotation)
        gx, gy = mapper((record["x"], record["y"]))
        line, centre = (gx, gy) if orient == "v" else (gy, gx)
        build.openings.append(
            _PendingOpening(
                orient=orient,
                line=ft_to_m(line),
                centre=ft_to_m(centre),
                # the leaf is drawn at the plan's scale, like the wall it is in
                width=ft_to_m(record["width"] * scale),
                kind=record["kind"],
                provenance=Provenance.DRESSED,
                sill=None if record["sill"] is None else ft_to_m(_num(record["sill"])),
                head=None if record["head"] is None else ft_to_m(_num(record["head"])),
                label=record["label"],
            )
        )
    return build


def _build_corridor(
    corridor: Dict[str, Any],
    storey: int,
    index: int,
    options: _Options,
) -> Tuple[Optional[RoomPoly], List[_Seg]]:
    cid = _text(corridor.get("id")) or ("corridor-" + str(index))
    x, y = _num(corridor.get("x")), _num(corridor.get("y"))
    w, h = _num(corridor.get("width")), _num(corridor.get("height"))
    if w <= 0.0 or h <= 0.0:
        return (None, [])
    polygon = _to_m(_rect_polygon(x, y, w, h))
    rid = room_id(storey, cid)
    room = RoomPoly(
        id=rid,
        storey=storey,
        name=_text(corridor.get("role"), "corridor").capitalize() + " corridor",
        occupancy=Occupancy.CORRIDOR,
        polygon=polygon,
        area_m2=_polygon_area(polygon),
        unit_id=None,
        interior_unknown=False,
        source=cid,
    )
    segments = _rect_segments(
        ft_to_m(x), ft_to_m(y), ft_to_m(w), ft_to_m(h), options.interior_m, "corridor", cid, cid
    )
    segments.extend(_room_segments(polygon, rid, options.interior_m, cid))
    return (room, segments)


def _place_opening(walls: Sequence[WallLine], pending: _PendingOpening, tolerance: float) -> Optional[WallLine]:
    """Nearest collinear wall whose run contains the opening centre."""
    best = None  # type: Optional[WallLine]
    best_gap = None  # type: Optional[float]
    for wall in walls:
        orient, pos, s0, s1 = _wall_axis(wall)
        if orient != pending.orient:
            continue
        gap = abs(pos - pending.line)
        if gap > tolerance:
            continue
        if pending.centre < s0 - GEOM_TOL_M or pending.centre > s1 + GEOM_TOL_M:
            continue
        if best_gap is None or gap < best_gap - 1e-12 or (abs(gap - best_gap) <= 1e-12 and wall.id < best.id):
            best = wall
            best_gap = gap
    return best


def _bucket_opening(
    buckets: Dict[str, List[Dict[str, Any]]],
    wall: WallLine,
    offset: float,
    width: float,
    kind: OpeningKind,
    provenance: Provenance,
    sill: Optional[float] = None,
    head: Optional[float] = None,
) -> None:
    buckets.setdefault(wall.id, []).append(
        {
            "offset": offset,
            "width": width,
            "kind": kind,
            "provenance": provenance,
            "sill": sill,
            "head": head,
        }
    )


def _finalize_openings(walls: Sequence[WallLine], buckets: Dict[str, List[Dict[str, Any]]]) -> None:
    """Ids are `<wallid>-op<i>` with i ordered by increasing offset."""
    for wall in walls:
        items = buckets.get(wall.id) or []
        items.sort(key=lambda o: (round(o["offset"], 9), round(o["width"], 9), o["kind"].value))
        wall.openings = [
            Opening(
                id=opening_id(wall.id, index),
                kind=item["kind"],
                offset_m=item["offset"],
                width_m=item["width"],
                sill_m=item["sill"],
                head_m=item["head"],
                provenance=item["provenance"],
            )
            for index, item in enumerate(items)
        ]


def _assume_doors(
    walls: Sequence[WallLine],
    rooms: Sequence[RoomPoly],
    unit_key: str,
    min_share_m: float,
) -> Tuple[List[Tuple[WallLine, float]], List[str]]:
    """Mid-wall doors on a spanning tree of shared runs (plan_json step 5b).

    Only runs of at least MIN_DOOR_SHARE_FT carry a door: a lintel must never
    be invented over a doorway that cannot exist. Rooms left unreachable are
    returned so the caller can disclose them.
    """
    unit_rooms = sorted([r for r in rooms if r.unit_id == unit_key], key=lambda r: r.id)
    if len(unit_rooms) < 2:
        return ([], [])
    ids = {r.id for r in unit_rooms}
    best = {}  # type: Dict[Tuple[str, str], WallLine]
    for wall in sorted(walls, key=lambda w: w.id):
        lo, hi = wall.room_ids
        if not lo or not hi or lo not in ids or hi not in ids:
            continue
        if _wall_length(wall) < min_share_m - GEOM_TOL_M:
            continue
        pair = (lo, hi) if lo < hi else (hi, lo)
        held = best.get(pair)
        if held is None or _wall_length(wall) > _wall_length(held) + GEOM_TOL_M:
            best[pair] = wall

    def start_key(room: RoomPoly) -> Tuple[int, int, str]:
        lowered = room.name.lower()
        return (0 if "living" in lowered else 1, 0 if room.occupancy == Occupancy.HABITABLE else 1, room.id)

    by_id = {r.id: r for r in unit_rooms}
    reached = {sorted(unit_rooms, key=start_key)[0].id}
    doors = []  # type: List[Tuple[WallLine, float]]
    while True:
        frontier = []
        for pair in sorted(best):
            wall = best[pair]
            lo, hi = pair
            if (lo in reached) == (hi in reached):
                continue
            parent = by_id.get(lo if lo in reached else hi)
            rank = 1 if (parent is not None and parent.occupancy in _POOR_PARENTS) else 0
            frontier.append((rank, -_wall_length(wall), wall.id, pair))
        if not frontier:
            break
        frontier.sort()
        pair = frontier[0][3]
        wall = best[pair]
        doors.append((wall, 0.5 * _wall_length(wall)))
        reached.add(pair[0])
        reached.add(pair[1])
    unreached = sorted(r.id for r in unit_rooms if r.id not in reached)
    return (doors, unreached)


def _apply_railings(walls: Sequence[WallLine], rooms_by_id: Dict[str, RoomPoly], railing_m: float) -> None:
    """A balcony's own exterior edge is a railing, never a bearing wall."""
    for wall in walls:
        if wall.role != WallRole.EXTERIOR:
            continue
        sides = [rid for rid in wall.room_ids if rid]
        if len(sides) != 1:
            continue
        room = rooms_by_id.get(sides[0])
        if room is None or room.occupancy != Occupancy.BALCONY:
            continue
        wall.role = WallRole.RAILING
        wall.thickness_m = railing_m
        wall.bearing = False


def _assumed_window_walls(
    walls: Sequence[WallLine],
    rooms_by_id: Dict[str, RoomPoly],
    unit_key: str,
) -> List[Tuple[WallLine, float]]:
    """One mid-wall window per exterior wall of a habitable or kitchen room."""
    out = []  # type: List[Tuple[WallLine, float]]
    for wall in sorted(walls, key=lambda w: w.id):
        if wall.role != WallRole.EXTERIOR:
            continue
        sides = [rid for rid in wall.room_ids if rid]
        if len(sides) != 1:
            continue
        room = rooms_by_id.get(sides[0])
        if room is None or room.unit_id != unit_key:
            continue
        if room.occupancy not in (Occupancy.HABITABLE, Occupancy.KITCHEN):
            continue
        length = _wall_length(wall)
        if length < ASSUMED_WINDOW_WIDTH_M + 0.3:
            continue
        out.append((wall, 0.5 * length))
    return out


def _inside_boundary(rect_ft: Tuple[float, float, float, float], boundary_ft: Sequence[XY]) -> bool:
    x, y, w, h = rect_ft
    bx, by, bw, bh = _bbox(boundary_ft)
    eps = 0.01
    if x < bx - eps or y < by - eps or x + w > bx + bw + eps or y + h > by + bh + eps:
        return False
    if len(boundary_ft) == 4:
        return True
    try:
        from shapely.geometry import Polygon as _ShapelyPolygon
        from shapely.geometry import box as _shapely_box

        plate = _ShapelyPolygon([(float(p[0]), float(p[1])) for p in boundary_ft]).buffer(eps)
        return bool(plate.contains(_shapely_box(x, y, x + w, y + h)))
    except Exception:  # shapely absent: corner containment is the fallback
        return _corners_inside(rect_ft, boundary_ft)


def _corners_inside(rect_ft: Tuple[float, float, float, float], boundary_ft: Sequence[XY]) -> bool:
    x, y, w, h = rect_ft
    # inset so a unit flush with the boundary is not read as protruding
    x, y, w, h = x + 0.01, y + 0.01, max(w - 0.02, 0.0), max(h - 0.02, 0.0)
    for point in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
        if not _point_in_polygon(point, boundary_ft):
            return False
    return True


def _point_in_polygon(point: XY, polygon: Sequence[XY]) -> bool:
    px, py = point
    inside = False
    count = len(polygon)
    for i in range(count):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % count]
        if (ay > py) != (by > py):
            cross = ax + (py - ay) / (by - ay) * (bx - ax)
            if px < cross:
                inside = not inside
    return inside


def _build_parking(bay: Dict[str, Any], storey: int, index: int) -> Optional[RoomPoly]:
    bid = _text(bay.get("id")) or ("bay-" + str(index))
    x, y = _num(bay.get("x")), _num(bay.get("y"))
    w, h = _num(bay.get("width")), _num(bay.get("height"))
    if w <= 0.0 or h <= 0.0:
        return None
    polygon = _to_m(_rect_polygon(x, y, w, h))
    return RoomPoly(
        id=room_id(storey, bid),
        storey=storey,
        name="Parking bay",
        occupancy=Occupancy.PARKING,
        polygon=polygon,
        area_m2=_polygon_area(polygon),
        unit_id=None,
        interior_unknown=False,
        source=bid,
    )


# --------------------------------------------------------------------------
# the adapter
# --------------------------------------------------------------------------


def _ordered_floors(floors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Payload order, unless every entry states a `floorNumber` to sort by.

    `floorNumber` is a 1-based HUMAN label the frontend writes as `i + 1`
    (buildingSlice `addBuilding` and `addFloor`); it is never the 0-based
    storey index. It orders the list and nothing else. A payload that omits it
    anywhere keeps its own order, which is the frontend's order too.
    """
    numbers = []  # type: List[int]
    for floor in floors:
        try:
            numbers.append(int(floor.get("floorNumber")))
        except (TypeError, ValueError):
            return list(floors)
    indexed = list(zip(numbers, range(len(floors)), floors))
    indexed.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in indexed]


def _pick_floors(payload: Dict[str, Any], count: int) -> List[Tuple[Optional[Dict[str, Any]], bool]]:
    """Storey i -> (floor payload, repeated), POSITIONALLY per spec 6 step 1.

    Storey i takes `floors[i]`. Resolving it by `floorNumber == i` read a
    1-based label as a 0-based index: the ground floor was used for storeys 0
    AND 1, every other floor shifted down one, the top floor was dropped
    without a word and W_TYPICAL_REPEATED could not fire. Storeys past the end
    of the list repeat the last `kind:"units"` floor, disclosed; a floor that a
    lower storey already consumed is flagged repeated too, so no storey can
    duplicate another in silence.
    """
    floors = _ordered_floors([f for f in (payload.get("floors") or []) if isinstance(f, dict)])
    typical = next(
        (floor for floor in reversed(floors) if _text(floor.get("kind"), "units") != "stilt"),
        None,
    )  # type: Optional[Dict[str, Any]]
    picked = []  # type: List[Tuple[Optional[Dict[str, Any]], bool]]
    used_objects = set()  # type: set
    used_ids = set()  # type: set
    for index in range(count):
        if index < len(floors):
            floor = floors[index]
            source_id = _text(floor.get("id"))
            repeated = id(floor) in used_objects or (bool(source_id) and source_id in used_ids)
            picked.append((floor, repeated))
            used_objects.add(id(floor))
            if source_id:
                used_ids.add(source_id)
        elif typical is not None:
            picked.append((typical, True))
        else:
            picked.append((None, False))
    return picked


def _boundary_segments(boundary_m: Sequence[XY], thickness_m: float) -> List[_Seg]:
    """The boundary loop's own edges as exterior ownership segments."""
    segments = []  # type: List[_Seg]
    count = len(boundary_m)
    for i in range(count):
        ax, ay = boundary_m[i]
        bx, by = boundary_m[(i + 1) % count]
        if abs(ay - by) <= GEOM_TOL_M and abs(ax - bx) > GEOM_TOL_M:
            segments.append(
                _Seg("h", 0.5 * (ay + by), min(ax, bx), max(ax, bx), thickness_m, "boundary", "boundary", source="boundary")
            )
        elif abs(ax - bx) <= GEOM_TOL_M and abs(ay - by) > GEOM_TOL_M:
            segments.append(
                _Seg("v", 0.5 * (ax + bx), min(ay, by), max(ay, by), thickness_m, "boundary", "boundary", source="boundary")
            )
    return segments


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _add_cores(model: StructuralModel, payload: Dict[str, Any], count: int) -> None:
    """fixedElements become Cores present on every storey (spec step 7)."""
    storeys = list(range(count))
    unit_rects = []  # type: List[Tuple[float, float, float, float, str]]
    for floor in payload.get("floors") or []:
        if not isinstance(floor, dict):
            continue
        for unit in floor.get("units") or []:
            if not isinstance(unit, dict):
                continue
            unit_rects.append(
                (
                    _num(unit.get("x")),
                    _num(unit.get("y")),
                    _num(unit.get("width")),
                    _num(unit.get("height")),
                    _text(unit.get("id")),
                )
            )

    overlaps = []  # type: List[str]
    unknown = []  # type: List[str]
    elements = sorted(
        [e for e in (payload.get("fixedElements") or []) if isinstance(e, dict)],
        key=lambda e: (_num(e.get("x")), _num(e.get("y")), _text(e.get("id"))),
    )
    for index, element in enumerate(elements):
        eid = _text(element.get("id")) or ("fe-" + str(index))
        x, y = _num(element.get("x")), _num(element.get("y"))
        w, h = _num(element.get("width")), _num(element.get("height"))
        if w <= 0.0 or h <= 0.0:
            continue
        kind = _CORE_KINDS.get(_text(element.get("type")).strip().lower())
        if kind is None:
            kind = CoreKind.UTILITY_SHAFT
            unknown.append(_text(element.get("label"), eid) + " (" + _text(element.get("type"), "?") + ")")
        core = Core(
            id=core_id(eid),
            kind=kind,
            x_m=ft_to_m(x),
            y_m=ft_to_m(y),
            w_m=ft_to_m(w),
            h_m=ft_to_m(h),
            storeys=list(storeys),
            stair_landing_hint=None,
        )
        model.cores.append(core)
        for ux, uy, uw, uh, _uid in unit_rects:
            if min(x + w, ux + uw) - max(x, ux) > 0.01 and min(y + h, uy + uh) - max(y, uy) > 0.01:
                overlaps.append(core.id)
                break
    model.cores.sort(key=lambda c: c.id)
    if overlaps:
        model.add_warning(
            "W_CORE_UNIT_OVERLAP",
            "core footprint overlaps a unit footprint; placement decides whether to carve",
            sorted(set(overlaps)),
            stage="adapters.building",
        )
    if unknown:
        # Closest registered code for an unmapped payload label; the core ships
        # as a utility shaft rather than being dropped.
        model.add_warning(
            "W_OCCUPANCY_UNKNOWN",
            "fixed element types did not map to a known core kind: " + ", ".join(sorted(set(unknown))),
            (),
            stage="adapters.building",
        )


def from_building(
    building: Dict[str, Any],
    *,
    storey_height_ft: float = DEFAULT_STOREY_HEIGHT_FT,
    exterior_wall_ft: float = DEFAULT_EXTERIOR_WALL_FT,
    interior_wall_ft: float = DEFAULT_INTERIOR_WALL_FT,
    railing_wall_ft: float = DEFAULT_RAILING_WALL_FT,
    occupancy_map: Optional[Dict[str, str]] = None,
    assume_windows: bool = False,
    system_hint: str = "rc_frame",
) -> StructuralModel:
    """Frontend Building JSON -> one multi-storey StructuralModel.

    `assume_windows` is off by default and turned on by the orchestrator when
    the target system is masonry, so IS 4326 Table 4 has openings to check
    (finding 10). A stilt storey carries no envelope loop: pilotis are open by
    definition, and that absence is what makes StoreyKind.STILT the soft-storey
    hook the seismic checks read.
    """
    payload = _unwrap(building)
    boundary_ft = _boundary_polygon_ft(payload.get("boundary"))
    try:
        system = System(system_hint)
    except ValueError:
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "unknown system hint " + repr(system_hint),
            {"system": system_hint},
        )
    try:
        count = int(payload.get("totalFloors"))
    except (TypeError, ValueError):
        count = 0
    if count < 1:
        raise AdapterError(
            "E_UNSUPPORTED_STOREYS",
            "totalFloors must be at least 1, got " + repr(payload.get("totalFloors")),
            {"total_floors": payload.get("totalFloors")},
        )

    options = _Options(
        exterior_m=ft_to_m(exterior_wall_ft),
        interior_m=ft_to_m(interior_wall_ft),
        railing_m=ft_to_m(railing_wall_ft),
        assume_windows=bool(assume_windows),
        occupancy_map={str(k): str(v) for k, v in sorted((occupancy_map or {}).items())},
    )

    model = StructuralModel(
        id=_text(payload.get("id"), "building"),
        source=ModelSource.BUILDING,
        system=system,
        fingerprint=fingerprint(payload),
        meta={
            "adapter": "building",
            "north": "-y",
            "source_id": _text(payload.get("id"), ""),
            "source_name": _text(payload.get("name"), ""),
            "building_type": _text(payload.get("type"), ""),
            "boundary_ft": [[p[0], p[1]] for p in boundary_ft],
            "options": {
                "storey_height_ft": float(storey_height_ft),
                "exterior_wall_ft": float(exterior_wall_ft),
                "interior_wall_ft": float(interior_wall_ft),
                "railing_wall_ft": float(railing_wall_ft),
                "assume_windows": bool(assume_windows),
                "system_hint": _enum_text(system),
            },
        },
    )
    if isinstance(payload.get("structuralGrid"), dict):
        # Stored, never imported as geometry: the engine grid supersedes it.
        model.meta["client_grid"] = copy.deepcopy(payload["structuralGrid"])

    height_m = ft_to_m(storey_height_ft)
    boundary_m = _to_m(boundary_ft)
    min_share_m = ft_to_m(MIN_DOOR_SHARE_FT)
    door_tol_m = ft_to_m(DOOR_LINE_TOL_FT)

    repeated = []  # type: List[str]
    no_plan = []  # type: List[str]
    outside = []  # type: List[str]
    rescaled = []  # type: List[str]
    rescaled_rooms = []  # type: List[str]
    rotated = []  # type: List[str]
    rotated_rooms = []  # type: List[str]
    unknown_names = []  # type: List[str]
    unmapped = []  # type: List[str]
    shortfalls = []  # type: List[str]
    assumed_doors = 0
    assumed_windows = 0
    undressed_units = 0

    for index, (floor, is_repeat) in enumerate(_pick_floors(payload, count)):
        floor = floor or {}
        kind_text = _text(floor.get("kind"), "units")
        kind = StoreyKind.STILT if kind_text == "stilt" else StoreyKind.UNITS
        label = _text(floor.get("label")) if not is_repeat else ""
        if not label:
            label = "Ground" if index == 0 else "Floor " + str(index)
        model.storeys.append(
            Storey(
                index=index,
                name=label,
                bottom_z_m=index * height_m,
                height_m=height_m,
                kind=kind,
                source_id=_text(floor.get("id")) or None,
            )
        )
        if is_repeat:
            repeated.append(str(index))

        segments = []  # type: List[_Seg]
        rooms = []  # type: List[RoomPoly]
        pendings = []  # type: List[_PendingOpening]
        unit_keys = []  # type: List[Tuple[str, bool, bool]]

        if kind != StoreyKind.STILT:
            segments.extend(_boundary_segments(boundary_m, options.exterior_m))

        units = sorted(
            [u for u in (floor.get("units") or []) if isinstance(u, dict)],
            key=lambda u: (_num(u.get("x")), _num(u.get("y")), _text(u.get("id"))),
        )
        for unit_index, unit in enumerate(units):
            build = _build_unit(unit, index, unit_index, options, unknown_names)
            rooms.extend(build.rooms)
            segments.extend(build.segments)
            pendings.extend(build.openings)
            unit_keys.append((build.key, build.dressed, build.has_plan))
            if not build.has_plan:
                no_plan.extend(sorted(r.id for r in build.rooms))
            if build.rescale_note:
                rescaled.append(build.rescale_note)
                rescaled_rooms.extend(sorted(r.id for r in build.rooms))
            if build.rotation_note:
                rotated.append(build.rotation_note)
                rotated_rooms.extend(sorted(r.id for r in build.rooms))
            if not _inside_boundary(build.footprint, boundary_ft):
                outside.extend(sorted(r.id for r in build.rooms))

        corridors = sorted(
            [c for c in (floor.get("corridors") or []) if isinstance(c, dict)],
            key=lambda c: (_num(c.get("x")), _num(c.get("y")), _text(c.get("id"))),
        )
        for corridor_index, corridor in enumerate(corridors):
            room, corridor_segments = _build_corridor(corridor, index, corridor_index, options)
            if room is None:
                continue
            rooms.append(room)
            segments.extend(corridor_segments)

        bays = sorted(
            [b for b in (floor.get("parking") or []) if isinstance(b, dict)],
            key=lambda b: (_num(b.get("x")), _num(b.get("y")), _text(b.get("id"))),
        )
        for bay_index, bay in enumerate(bays):
            bay_room = _build_parking(bay, index, bay_index)
            if bay_room is not None:
                rooms.append(bay_room)

        walls = _merge_walls(segments, index)
        rooms_by_id = {room.id: room for room in rooms}
        _apply_railings(walls, rooms_by_id, options.railing_m)

        buckets = {}  # type: Dict[str, List[Dict[str, Any]]]
        for pending in pendings:
            wall = _place_opening(walls, pending, door_tol_m)
            if wall is None:
                unmapped.append(pending.label)
                continue
            axis = _wall_axis(wall)
            _bucket_opening(
                buckets,
                wall,
                pending.centre - axis[2],
                pending.width,
                pending.kind,
                pending.provenance,
                pending.sill,
                pending.head,
            )

        for unit_key, dressed, has_plan in unit_keys:
            if dressed or not has_plan:
                continue
            undressed_units += 1
            doors, unreached = _assume_doors(walls, rooms, unit_key, min_share_m)
            for wall, offset in doors:
                assumed_doors += 1
                _bucket_opening(
                    buckets, wall, offset, ASSUMED_DOOR_WIDTH_M, OpeningKind.DOOR, Provenance.ASSUMED_MID_WALL
                )
            shortfalls.extend(unreached)
            if options.assume_windows:
                for wall, offset in _assumed_window_walls(walls, rooms_by_id, unit_key):
                    assumed_windows += 1
                    _bucket_opening(
                        buckets,
                        wall,
                        offset,
                        ASSUMED_WINDOW_WIDTH_M,
                        OpeningKind.WINDOW,
                        Provenance.ASSUMED_MID_WALL,
                    )

        _finalize_openings(walls, buckets)
        model.walls.extend(walls)
        model.rooms.extend(sorted(rooms, key=lambda r: r.id))

    _add_cores(model, payload, count)

    if repeated:
        model.add_warning(
            "W_TYPICAL_REPEATED",
            "storeys "
            + ", ".join(repeated)
            + " repeat the last units floor; the payload carries "
            + str(len([f for f in (payload.get("floors") or []) if isinstance(f, dict)]))
            + " floor(s) for totalFloors "
            + str(count),
            (),
            stage="adapters.building",
        )
    if no_plan:
        model.add_warning(
            "W_UNIT_NO_PLAN",
            str(len(no_plan)) + " unit(s) carry no interior plan; each is one interior_unknown room",
            sorted(set(no_plan)),
            stage="adapters.building",
        )
    if rescaled:
        # The registry is deliberately coarser than English and this is the
        # code for "the placed plan is not the plan as drawn"; housing.py
        # raises it for the same rescale-and-centre rule.
        model.add_warning(
            "W_STALE_GENERATED",
            str(len(set(rescaled)))
            + " unit plan(s) did not match the declared unit rect and were uniformly rescaled and "
            "centred in it, the rule the frontend draws them by: "
            + ", ".join(sorted(set(rescaled))),
            sorted(set(rescaled_rooms)),
            stage="adapters.building",
        )
    if rotated:
        model.add_warning(
            "W_STALE_GENERATED",
            str(len(set(rotated)))
            + " unit(s) carry a non-zero rotation, applied here by the spec 6.5 transform: "
            + ", ".join(sorted(set(rotated)))
            + ". No frontend view (2D canvas, 3D, DXF, walkthrough) applies unit rotation, so this "
            "geometry differs from the drawn and exported plan; which side owns the rotation is an "
            "open product decision, not settled by this adapter.",
            sorted(set(rotated_rooms)),
            stage="adapters.building",
        )
    if outside:
        model.add_warning(
            "W_UNIT_OUTSIDE_BOUNDARY",
            "unit footprint protrudes past the building boundary; geometry kept",
            sorted(set(outside)),
            stage="adapters.building",
        )
    if unknown_names:
        model.add_warning(
            "W_OCCUPANCY_UNKNOWN",
            "room names did not map to a known occupancy: " + ", ".join(sorted(set(unknown_names))),
            (),
            stage="adapters.building",
        )
    if assumed_doors:
        model.add_warning(
            "W_DOOR_ASSUMED",
            str(assumed_doors) + " door(s) assumed mid-wall at " + str(ASSUMED_DOOR_WIDTH_M) + " m; the plans carried none",
            (),
            stage="adapters.building",
        )
    if unmapped:
        model.add_warning(
            "W_DOOR_UNMAPPED",
            str(len(unmapped)) + " dressed opening(s) mapped to no wall line: " + ", ".join(sorted(unmapped)),
            (),
            stage="adapters.building",
        )
    if shortfalls:
        model.add_warning(
            "W_ADJACENCY_SHORTFALL",
            "rooms share less than "
            + _dim(MIN_DOOR_SHARE_FT)
            + " ft of wall with the rest of their unit (the assumed door width); no door assumed",
            sorted(set(shortfalls)),
            stage="adapters.building",
        )
    if assumed_windows:
        model.add_warning(
            "W_ASSUMED_OPENINGS",
            str(assumed_windows) + " window(s) assumed mid-wall at " + str(ASSUMED_WINDOW_WIDTH_M) + " m for the opening checks",
            (),
            stage="adapters.building",
        )
    elif undressed_units:
        model.add_warning(
            "N_WINDOWS_NOT_ASSUMED",
            "no windows assumed on " + str(undressed_units) + " undressed unit(s); window lintels are omitted there",
            (),
            stage="adapters.building",
        )
    return model
