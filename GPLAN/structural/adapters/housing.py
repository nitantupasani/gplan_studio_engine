"""adapters/housing.py: a HousingDesign payload -> one StructuralModel PER PLOT STACK.

Decision of record (spec section 7): structures on disjoint plots share no load
path, so each plot gets its own model. The primary boundary is stack "primary";
every `HousingPlot.id` is its own stack, and a plot id is shared across floors,
which is exactly what stacks its storeys.

Frame and units. The payload is FEET, y-down, origin top-left; north is -y. Every
coordinate is converted to metres ONCE here (`_m`, `_pt_m`), so nothing below the
adapter sees feet again. Storey 0 is ground, storey height 10.4 ft (frontend iso
precedent: 9.5 ft wall + 0.9 ft slab), plinth 0.5 ft recorded as meta only.

Regions are DERIVED, never stored: the payload keys `regionContent` by an opaque
`regionKey(points)` string. Two paths, both supported and both disclosed:
  (a) preferred: the caller passes `resolved_regions` (what the frontend's
      `detectFloorRegions` produced), and content rides along with each region;
  (b) fallback: this module planarizes the wall arrangement (plot boundary +
      segments + shape edges) with `shapely.ops.polygonize` and matches each
      content key, where the key parses as "x,y;x,y;...", by loop EQUALITY, and
      only where the arrangement has partitioned the key and nothing equals it,
      by containment of a single face's interior point. Unmatched content is
      dropped with W_REGION_CONTENT_UNMATCHED naming it, never guessed.

Content reaches this adapter through FOUR carriers, not one: `regionContent`,
the plot boundary (`boundaryContent`), an additional plot (`plot.content`) and a
drawn shape (`shape.content`). All four hold the same `HousingContent`, all four
become rooms here, and the boundary is the only slot the client can store a plan
dropped on the whole plot in, because its own face tracer drops the boundary
cycle. A region key is the more specific address and is matched first; a carrier
then takes the face that IS its polygon.

Walls come only from drawn geometry: the plot boundary (exterior, 0.75 ft),
`segments` and shape edges (interior, `wallDisplay.interiorWallFt`), plus the
interior walls of a placed unit plan. A region-to-region border that carries no
drawn wall is NOT a wall (open plan is a real answer here). Collinear runs are
merged once at a 115 mm centreline tolerance, so a span drawn twice becomes one
wall; a placed plan's own boundary is therefore carried by the enclosing region
walls rather than doubled beside them.

Nothing is placed anonymously and no fallback is silent: every assumption lands
on the model's disclosure ladder with a registry code.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from ..model import (
    Core,
    CoreKind,
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

# --------------------------------------------------------------------------
# constants (feet at the payload edge, metres everywhere below)
# --------------------------------------------------------------------------

#: Floor to floor height of a housing storey, feet (spec section 1).
HOUSING_STOREY_HEIGHT_FT = 10.4
#: Plinth height, feet. Recorded on meta; the model's z datum stays the ground FFL.
HOUSING_PLINTH_FT = 0.5
#: The product caps a housing design at three floors (frontend MAX_HOUSING_FLOORS).
MAX_HOUSING_FLOORS = 3
#: Exterior (plot boundary) wall thickness, feet.
EXTERIOR_WALL_FT = 0.75
#: `wallDisplay.interiorWallFt` default, feet (4 inches).
DEFAULT_INTERIOR_WALL_FT = 4.0 / 12.0
#: Entry opening width, feet (the large plot entrance the 3D render hangs here).
ENTRY_WIDTH_FT = 3.5

#: Unified assumed door width, metres (critic finding 10: one synthesizer, 0.9 m).
ASSUMED_DOOR_WIDTH_M = 0.9
#: Assumed window width, metres, only when `assume_windows` is on.
ASSUMED_WINDOW_WIDTH_M = 1.2
ASSUMED_WINDOW_SILL_M = 0.9
ASSUMED_WINDOW_HEAD_M = 2.1

#: Shared wall a door needs, metres (2.8 ft, the engine's DOORABLE_WALL_FT).
MIN_DOOR_SHARE_M = ft_to_m(2.8)
#: Centreline merge tolerance, metres (the grid-regularization catalogue number).
MERGE_TOL_M = 0.115
#: Gap below which two collinear runs are one wall, metres.
JOIN_TOL_M = 1e-3
#: Generated-plan staleness epsilon, metres (the client's PLOT_FIT_EPS, 0.15 ft).
STALE_EPS_M = ft_to_m(0.15)

#: Roof rise as a ratio of the shorter bbox span, by roof type.
ROOF_RISE_RATIO = {"flat": 0.0, "gable": 0.3, "hip": 0.3, "shed": 0.25}
#: Eaves overhang, feet.
ROOF_OVERHANG_FT = 1.0

#: The frontend's HousingSpaceKind -> Occupancy.
SPACE_OCCUPANCY = {
    "corridor": Occupancy.CORRIDOR,
    "staircase": Occupancy.STAIR,
    "lift": Occupancy.LIFT,
    "lobby": Occupancy.LOBBY,
    "parking": Occupancy.PARKING,
    "green": Occupancy.GREEN,
    "other": Occupancy.OTHER,
}

#: Space kinds that are not a building: a stack carrying only these is unbuilt.
UNBUILT_SPACE_KINDS = ("parking", "green")

#: Room-name prefixes -> Occupancy. plan_json.py owns the canonical NAME_KIND
#: table; this is the same mapping, kept private so a housing model can be built
#: without importing a sibling adapter. Longest prefix wins, case-insensitive.
NAME_OCCUPANCY = (
    ("living", Occupancy.HABITABLE),
    ("dining", Occupancy.HABITABLE),
    ("drawing", Occupancy.HABITABLE),
    ("bedroom", Occupancy.HABITABLE),
    ("master", Occupancy.HABITABLE),
    ("guest room", Occupancy.HABITABLE),
    ("study", Occupancy.HABITABLE),
    ("hall", Occupancy.HABITABLE),
    ("kitchen", Occupancy.KITCHEN),
    ("bath", Occupancy.BATH),
    ("toilet", Occupancy.WC),
    ("wc", Occupancy.WC),
    ("powder", Occupancy.WC),
    ("balcony", Occupancy.BALCONY),
    ("verandah", Occupancy.BALCONY),
    ("corridor", Occupancy.CORRIDOR),
    ("passage", Occupancy.CORRIDOR),
    ("lobby", Occupancy.LOBBY),
    ("staircase", Occupancy.STAIR),
    ("stair", Occupancy.STAIR),
    ("lift", Occupancy.LIFT),
    ("utility", Occupancy.UTILITY),
    ("wash", Occupancy.UTILITY),
    ("store", Occupancy.STORAGE),
    ("storage", Occupancy.STORAGE),
    ("parking", Occupancy.PARKING),
    ("garage", Occupancy.PARKING),
    ("garden", Occupancy.GREEN),
    ("green", Occupancy.GREEN),
    ("void", Occupancy.VOID),
    ("shaft", Occupancy.VOID),
)

#: The primary boundary's stack id.
PRIMARY_STACK = "primary"


# --------------------------------------------------------------------------
# refusal
# --------------------------------------------------------------------------


class _LocalAdapterError(Exception):
    """Raised only when the structure is underivable or the geometry lies.

    `code` is a model.REGISTRY error code; api.py maps it to the engine error
    envelope with `message` verbatim. Everything softer is disclosed on the
    model's ladder instead, never raised.
    """

    def __init__(self, code, message, details=None):
        # type: (str, str, Optional[Dict[str, Any]]) -> None
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _resolve_adapter_error():
    # type: () -> Any
    """One refusal class for the whole adapters package, when a sibling ships it.

    `_geom.py` (else `plan_json.py`) owns the shared `AdapterError`; both are
    written in parallel with this file, so the import is guarded AND probed for
    the (code, message, details) signature. Absent or differently shaped, this
    module keeps its own class with the same three fields, so `except
    housing.AdapterError` is correct either way.
    """
    for module_name in ("_geom", "plan_json"):
        try:
            module = __import__(module_name, globals(), locals(), ["AdapterError"], 1)
            shared = getattr(module, "AdapterError")
            probe = shared("E_BAD_ENVELOPE", "probe", {})
            if getattr(probe, "code", None) == "E_BAD_ENVELOPE":
                return shared
        except Exception:  # sibling adapter absent or incompatible
            continue
    return _LocalAdapterError


AdapterError = _resolve_adapter_error()


# --------------------------------------------------------------------------
# small helpers (feet in, metres out)
# --------------------------------------------------------------------------


def _num(value, default=0.0):
    # type: (Any, float) -> float
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _m(value_ft):
    # type: (Any) -> float
    return ft_to_m(_num(value_ft))


def _pt_m(point):
    # type: (Sequence[Any]) -> Tuple[float, float]
    return (_m(point[0]), _m(point[1]))


def _loop_m(points):
    # type: (Sequence[Sequence[Any]]) -> List[Tuple[float, float]]
    """Payload loop -> metre loop, closing vertex dropped."""
    loop = [_pt_m(p) for p in points or []]
    while len(loop) > 1 and abs(loop[0][0] - loop[-1][0]) <= JOIN_TOL_M and abs(loop[0][1] - loop[-1][1]) <= JOIN_TOL_M:
        loop.pop()
    return loop


def _signed_area(points):
    # type: (Sequence[Sequence[float]]) -> float
    total = 0.0
    count = len(points)
    for i in range(count):
        ax, ay = points[i][0], points[i][1]
        bx, by = points[(i + 1) % count][0], points[(i + 1) % count][1]
        total += ax * by - bx * ay
    return total * 0.5


def _normalize_loop(points):
    # type: (Sequence[Sequence[float]]) -> List[Tuple[float, float]]
    """The frontend's `normalizeLoop`, in metres: one canonical form per polygon.

    Duplicate and same-direction collinear vertices are dropped (planarizing
    splits an edge at every T junction, which is a vertex the polygon does not
    have), the winding is fixed to a positive y-down shoelace (the model's outline
    convention) and the loop is rotated so its lexicographically smallest vertex
    leads. Both windings of one polygon therefore normalize to the same list.
    """
    loop = []  # type: List[Tuple[float, float]]
    for point in points:
        candidate = (float(point[0]), float(point[1]))
        if loop and abs(loop[-1][0] - candidate[0]) <= JOIN_TOL_M and abs(loop[-1][1] - candidate[1]) <= JOIN_TOL_M:
            continue
        loop.append(candidate)
    while len(loop) > 1 and abs(loop[0][0] - loop[-1][0]) <= JOIN_TOL_M and abs(loop[0][1] - loop[-1][1]) <= JOIN_TOL_M:
        loop.pop()

    changed = True
    while changed and len(loop) > 3:
        changed = False
        for i in range(len(loop)):
            count = len(loop)
            a = loop[(i - 1) % count]
            b = loop[i]
            c = loop[(i + 1) % count]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            dot = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
            if abs(cross) <= 1e-9 and dot > 0.0:
                loop.pop(i)
                changed = True
                break
    if len(loop) < 3:
        return loop
    if _signed_area(loop) < 0.0:
        loop.reverse()
    start = min(range(len(loop)), key=lambda i: (loop[i][0], loop[i][1]))
    return loop[start:] + loop[:start]


def _bbox(points):
    # type: (Sequence[Sequence[float]]) -> Tuple[float, float, float, float]
    """(x, y, w, h) of a point set."""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _shoelace_area(points):
    # type: (Sequence[Sequence[float]]) -> float
    total = 0.0
    count = len(points)
    for i in range(count):
        ax, ay = points[i][0], points[i][1]
        bx, by = points[(i + 1) % count][0], points[(i + 1) % count][1]
        total += ax * by - bx * ay
    return abs(total) * 0.5


def _shapely_polygon(loop):
    # type: (Sequence[Sequence[float]]) -> Optional[Polygon]
    if len(loop) < 3:
        return None
    poly = Polygon([(float(p[0]), float(p[1])) for p in loop])
    if not poly.is_valid:
        poly = poly.buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon":
            return None
    return poly


def _contains(loop, point):
    # type: (Sequence[Sequence[float]], Sequence[float]) -> bool
    poly = _shapely_polygon(loop)
    if poly is None:
        return False
    return poly.contains(Point(float(point[0]), float(point[1])))


def _interior_point(loop):
    # type: (Sequence[Sequence[float]]) -> Tuple[float, float]
    poly = _shapely_polygon(loop)
    if poly is None:
        x, y, w, h = _bbox(loop)
        return (x + 0.5 * w, y + 0.5 * h)
    rep = poly.representative_point()
    return (rep.x, rep.y)


def _parse_region_key(key):
    # type: (Any) -> Optional[List[Tuple[float, float]]]
    """Parse the frontend's regionKey ("x,y;x,y;..."), feet, into a metre loop.

    Returns None when the key is opaque; the caller then discloses rather than
    guessing which face the content belonged to.
    """
    if not isinstance(key, str) or ";" not in key:
        return None
    loop = []  # type: List[Tuple[float, float]]
    for part in key.split(";"):
        chunk = part.strip()
        if not chunk or "," not in chunk:
            return None
        head, _, tail = chunk.partition(",")
        try:
            loop.append((ft_to_m(float(head)), ft_to_m(float(tail))))
        except ValueError:
            return None
    if len(loop) < 3:
        return None
    return loop


def _occupancy_for_name(name):
    # type: (Any) -> Tuple[Occupancy, bool]
    """(occupancy, recognized). Prefix-tolerant: 'Bathroom 2' -> bath."""
    text = str(name or "").strip().lower()
    if not text:
        return (Occupancy.OTHER, False)
    best = None  # type: Optional[Tuple[int, Occupancy]]
    for prefix, occupancy in NAME_OCCUPANCY:
        if text.startswith(prefix):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), occupancy)
    if best is None:
        return (Occupancy.OTHER, False)
    return (best[1], True)


def _content_of(holder):
    # type: (Any) -> Dict[str, Any]
    if not isinstance(holder, dict):
        return {}
    content = holder.get("content")
    return content if isinstance(content, dict) else {}


def _space_kind(content):
    # type: (Any) -> Optional[str]
    if not isinstance(content, dict):
        return None
    space = content.get("space")
    if not isinstance(space, dict):
        return None
    kind = space.get("kind")
    return str(kind) if kind else None


def _generated_of(content):
    # type: (Any) -> Optional[Dict[str, Any]]
    if not isinstance(content, dict):
        return None
    generated = content.get("generated")
    return generated if isinstance(generated, dict) else None


def _is_built_content(content):
    # type: (Any) -> bool
    """True when this content means a structure, not open ground."""
    if _generated_of(content) is not None:
        return True
    kind = _space_kind(content)
    if kind is None:
        return False
    return kind not in UNBUILT_SPACE_KINDS


def _floor_level(floor, index):
    # type: (Dict[str, Any], int) -> int
    level = floor.get("level")
    if level is None:
        return int(index)
    try:
        return int(level)
    except (TypeError, ValueError):
        return int(index)


def _segment_points(segment):
    # type: (Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float]]
    return (
        (_m(segment.get("x1")), _m(segment.get("y1"))),
        (_m(segment.get("x2")), _m(segment.get("y2"))),
    )


# --------------------------------------------------------------------------
# stack split
# --------------------------------------------------------------------------


def split_plot_stacks(design):
    # type: (Dict[str, Any]) -> List[Dict[str, Any]]
    """Split a HousingDesign into one record per plot stack, built flag included.

    Returns `[{"plot_id", "built", "floors": [...]}]` sorted with the primary
    boundary first and the additional plots by id. Each floor record is the
    slice of that floor belonging to the plot:

        {"level", "floor_id", "label", "boundary" (metres), "content",
         "segments", "shapes", "region_content", "orphan_content"}

    `built` is False for a stack that draws no wall beyond its own boundary and
    carries nothing but parking or green labels: open ground has no structure to
    derive, so `from_housing` produces no model for it.
    """
    if not isinstance(design, dict):
        raise AdapterError("E_BAD_ENVELOPE", "housing design payload is not an object")

    floors = design.get("floors")
    if not isinstance(floors, list) or not floors:
        raise AdapterError("E_UNSUPPORTED_STOREYS", "housing design carries no floors")
    if len(floors) > MAX_HOUSING_FLOORS:
        raise AdapterError(
            "E_UNSUPPORTED_STOREYS",
            "housing supports at most %d floors, this design has %d" % (MAX_HOUSING_FLOORS, len(floors)),
            {"floors": len(floors)},
        )

    ordered = sorted(
        [(_floor_level(f, i), i, f) for i, f in enumerate(floors) if isinstance(f, dict)]
    )
    if not ordered:
        raise AdapterError("E_BAD_ENVELOPE", "housing floors are not objects")

    # plot ids, primary first then additional plots by id (a plot id is shared
    # across floors by the frontend copy-up rule).
    plot_ids = []  # type: List[str]
    for _level, _index, floor in ordered:
        for plot in floor.get("plots") or []:
            if not isinstance(plot, dict):
                continue
            pid = str(plot.get("id") or "")
            if pid and pid not in plot_ids:
                plot_ids.append(pid)
    stack_ids = [PRIMARY_STACK] + sorted(plot_ids)

    stacks = []  # type: List[Dict[str, Any]]
    for stack_id in stack_ids:
        records = []  # type: List[Dict[str, Any]]
        for level, _index, floor in ordered:
            record = _floor_slice(floor, level, stack_id)
            if record is not None:
                records.append(record)
        if not records:
            continue
        built = False
        for record in records:
            if record["segments"] or record["shapes"]:
                built = True
            if _is_built_content(record["content"]):
                built = True
            for content in record["region_content"].values():
                if _is_built_content(content):
                    built = True
        stacks.append({"plot_id": stack_id, "built": built, "floors": records})
    return stacks


def _floor_slice(floor, level, stack_id):
    # type: (Dict[str, Any], int, str) -> Optional[Dict[str, Any]]
    """The part of one floor that belongs to one plot stack, in metres."""
    if stack_id == PRIMARY_STACK:
        loop = _loop_m(floor.get("boundary") or [])
        content = floor.get("boundaryContent")
        content = content if isinstance(content, dict) else {}
    else:
        loop = []
        content = {}
        for plot in floor.get("plots") or []:
            if isinstance(plot, dict) and str(plot.get("id") or "") == stack_id:
                loop = _loop_m(plot.get("boundary") or [])
                content = _content_of(plot)
                break
        if not loop:
            return None
    if len(loop) < 3:
        return None

    other_loops = _other_plot_loops(floor, stack_id)

    segments = []
    for segment in sorted(
        [s for s in (floor.get("segments") or []) if isinstance(s, dict)],
        key=lambda s: str(s.get("id") or ""),
    ):
        a, b = _segment_points(segment)
        mid = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
        if _owns(loop, other_loops, mid):
            segments.append({"id": str(segment.get("id") or ""), "a": a, "b": b})

    shapes = []
    for shape in sorted(
        [s for s in (floor.get("shapes") or []) if isinstance(s, dict)],
        key=lambda s: str(s.get("id") or ""),
    ):
        points = _loop_m(shape.get("points") or [])
        if len(points) < 3:
            continue
        if not _owns(loop, other_loops, _interior_point(points)):
            continue
        core = shape.get("core") if isinstance(shape.get("core"), dict) else None
        shapes.append(
            {
                "id": str(shape.get("id") or ""),
                "points": points,
                "content": _content_of(shape),
                "core": core,
            }
        )

    region_content = {}  # type: Dict[str, Dict[str, Any]]
    orphan = []  # type: List[str]
    raw = floor.get("regionContent")
    raw = raw if isinstance(raw, dict) else {}
    single_plot = not other_loops
    for key in sorted(raw):
        content_entry = raw[key]
        if not isinstance(content_entry, dict):
            continue
        parsed = _parse_region_key(key)
        if parsed is None:
            # An opaque key cannot be attributed on a multi-plot floor; on a
            # single-plot floor it can only belong here.
            if single_plot:
                region_content[key] = content_entry
            else:
                orphan.append(key)
            continue
        if _owns(loop, other_loops, _interior_point(parsed)):
            region_content[key] = content_entry

    return {
        "level": int(level),
        "floor_id": str(floor.get("id") or ""),
        "label": str(floor.get("label") or ""),
        "boundary": loop,
        "content": content,
        "segments": segments,
        "shapes": shapes,
        "region_content": region_content,
        "orphan_content": orphan,
    }


def _other_plot_loops(floor, stack_id):
    # type: (Dict[str, Any], str) -> List[List[Tuple[float, float]]]
    """Every plot loop on this floor except the stack's own."""
    loops = []
    if stack_id != PRIMARY_STACK:
        primary = _loop_m(floor.get("boundary") or [])
        if len(primary) >= 3:
            loops.append(primary)
    for plot in floor.get("plots") or []:
        if not isinstance(plot, dict):
            continue
        if str(plot.get("id") or "") == stack_id:
            continue
        loop = _loop_m(plot.get("boundary") or [])
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _owns(loop, other_loops, point):
    # type: (Sequence[Sequence[float]], Sequence[Sequence[Sequence[float]]], Sequence[float]) -> bool
    """True when this stack's loop holds `point` and no other plot's interior does.

    Plots are disjoint by the frontend's own rule, so the second test only
    protects against a payload that broke it. Containment falls back to the
    CLOSED loop, so a wall drawn along a plot edge belongs to that plot (and to
    both plots when it is drawn on a shared edge) rather than being dropped.
    """
    for other in other_loops:
        if _contains(other, point):
            return False
    if _contains(loop, point):
        return True
    polygon = _shapely_polygon(loop)
    if polygon is None:
        return False
    return polygon.intersects(Point(float(point[0]), float(point[1])))


# --------------------------------------------------------------------------
# regions: resolved by the caller, or re-derived here
# --------------------------------------------------------------------------


def _resolved_for_floor(resolved_regions, record, order_index):
    # type: (Any, Dict[str, Any], int) -> Optional[List[Dict[str, Any]]]
    """The caller's regions for one floor, or None when it supplied none.

    Accepted shapes: a dict keyed by floor id or by level (int or str), a flat
    list parallel to the design's floors, or a list of
    `{"floor_id"|"level", "regions": [...]}` envelopes. A stack's storeys are
    contiguous from 0 (a discontinuous one is refused), so a flat list is indexed
    by the floor's own level.
    """
    if resolved_regions is None:
        return None
    entry = None  # type: Any
    if isinstance(resolved_regions, dict):
        for key in (record["floor_id"], record["level"], str(record["level"])):
            if key in resolved_regions:
                entry = resolved_regions[key]
                break
    elif isinstance(resolved_regions, list):
        envelopes = [e for e in resolved_regions if isinstance(e, dict) and ("regions" in e)]
        if envelopes:
            for envelope in envelopes:
                same_id = str(envelope.get("floor_id") or "") == record["floor_id"]
                same_level = envelope.get("level") is not None and int(envelope["level"]) == record["level"]
                if same_id or same_level:
                    entry = envelope.get("regions")
                    break
        else:
            index = record["level"] if 0 <= record["level"] < len(resolved_regions) else order_index
            if 0 <= index < len(resolved_regions):
                entry = resolved_regions[index]
    if entry is None:
        return None
    if not isinstance(entry, list):
        return None
    out = []
    for region in entry:
        if not isinstance(region, dict):
            continue
        loop = _loop_m(region.get("points") or [])
        if len(loop) < 3:
            continue
        content = region.get("content")
        out.append({"loop": loop, "content": content if isinstance(content, dict) else None})
    return out


def _derive_faces(record):
    # type: (Dict[str, Any]) -> List[Tuple[List[Tuple[float, float]], float]]
    """Planarize the drawn arrangement; return each face as (exterior loop, area).

    The line set is the plot boundary, the open `segments` and every shape edge;
    `unary_union` nodes them (a crossing pair is split at the crossing), then
    `polygonize` builds the faces. A face nested inside another (a core island)
    comes back as its own face and as a HOLE in its host, which is exactly the
    accounting this module wants, so the host's `polygon.area` is already net of
    it. The loop is the hole-free exterior, so that net area travels WITH the
    loop; re-shoelacing the loop downstream would count every nested face twice,
    once as itself and once inside its host.
    """
    lines = []  # type: List[LineString]
    loop = record["boundary"]
    for i in range(len(loop)):
        a = loop[i]
        b = loop[(i + 1) % len(loop)]
        if a != b:
            lines.append(LineString([a, b]))
    for segment in record["segments"]:
        if segment["a"] != segment["b"]:
            lines.append(LineString([segment["a"], segment["b"]]))
    for shape in record["shapes"]:
        points = shape["points"]
        for i in range(len(points)):
            a = points[i]
            b = points[(i + 1) % len(points)]
            if a != b:
                lines.append(LineString([a, b]))
    if not lines:
        return []
    faces = []  # type: List[Tuple[Tuple[float, float], List[Tuple[float, float]], float]]
    for polygon in polygonize(unary_union(lines)):
        loop_m = _normalize_loop(list(polygon.exterior.coords)[:-1])
        if len(loop_m) < 3:
            continue
        rep = polygon.representative_point()
        faces.append(((rep.x, rep.y), loop_m, float(polygon.area)))
    kept = []
    for rep, loop_m, area in faces:
        if _contains(record["boundary"], rep):
            kept.append((loop_m, area))
    kept.sort(key=lambda item: (_bbox(item[0])[0], _bbox(item[0])[1]))
    return kept


def _same_loop(a, b, tol=JOIN_TOL_M):
    # type: (Sequence[Sequence[float]], Sequence[Sequence[float]], float) -> bool
    """True when two NORMALIZED loops are the same polygon.

    `_normalize_loop` drops duplicate and collinear vertices, fixes the winding
    and rotates the lexicographically smallest vertex to the front, so one
    polygon has exactly one form and a vertex-by-vertex compare is exact up to
    the payload's own round-2-in-feet quantization.
    """
    if len(a) != len(b) or not a:
        return False
    for index in range(len(a)):
        if abs(a[index][0] - b[index][0]) > tol or abs(a[index][1] - b[index][1]) > tol:
            return False
    return True


def _same_rect(a, b, tol=JOIN_TOL_M):
    # type: (Tuple[float, float, float, float], Tuple[float, float, float, float], float) -> bool
    return all(abs(a[i] - b[i]) <= tol for i in range(4))


def _core_of_face(loop, record):
    # type: (Sequence[Sequence[float]], Dict[str, Any]) -> Optional[Dict[str, Any]]
    """The core shape this face IS, if any: a core's label is locked, never content."""
    box = _bbox(loop)
    for shape in record["shapes"]:
        if shape["core"] is None:
            continue
        if _same_rect(_bbox(shape["points"]), box):
            return shape
    return None


def _eligible(face):
    # type: (Dict[str, Any]) -> bool
    """A face that can still take content: it has none, and it is not a core."""
    return face["content"] is None and face["core"] is None


def _match_region_content(faces, region_content):
    # type: (List[Dict[str, Any]], Dict[str, Dict[str, Any]]) -> List[str]
    """Attach payload content to faces: loop EQUALITY first, containment second.

    Only keys that parse as "x,y;x,y;..." can be matched. A key that IS a face
    takes that face, so a face nested inside the key can never steal its host's
    content: this module planarizes shape edges that the frontend's own
    `detectRegions` does not trace, and a nested island at the host's bbox origin
    is otherwise the first face the host's key contains.

    Containment is the fallback for the partitioning case, where the arrangement
    split the key and no face equals it. It fires only when exactly ONE eligible
    face lies inside, because two candidates is derivation drift and the spec
    says drift is disclosed, never guessed. Everything unattached comes back for
    disclosure. A core face never takes content: the frontend locks a core's
    label.
    """
    unmatched = []
    for key in sorted(region_content):
        content = region_content[key]
        parsed = _parse_region_key(key)
        if parsed is None:
            unmatched.append(key)
            continue
        loop = _normalize_loop(parsed)
        exact = [face for face in faces if _same_loop(face["loop"], loop)]
        if exact:
            hit = exact[0] if len(exact) == 1 and _eligible(exact[0]) else None
        else:
            inside = [face for face in faces if _eligible(face) and _contains(loop, face["interior"])]
            hit = inside[0] if len(inside) == 1 else None
        if hit is None:
            unmatched.append(key)
            continue
        hit["content"] = content
    return unmatched


def _carriers(record):
    # type: (Dict[str, Any]) -> List[Tuple[str, List[Tuple[float, float]], Dict[str, Any]]]
    """The content slots that are NOT keyed by region: (label, loop, content).

    The frontend hangs a space label or a generated unit plan on FOUR targets and
    `regionContent` is only one of them: the plot boundary (`boundaryContent`),
    an additional plot (`plot.content`) and a drawn shape (`shape.content`) carry
    the same `HousingContent`. A plan dropped on the whole plot can only be
    stored on the first of those, because the frontend's face tracer drops the
    boundary cycle and a segment-free floor has no region key at all, so reading
    `regionContent` alone loses the default single-house flow entirely.

    A circulation core is skipped: its content is the locked core label, which
    `_core_room` already reads, and the frontend never lets a plan land on one.
    """
    out = []  # type: List[Tuple[str, List[Tuple[float, float]], Dict[str, Any]]]
    content = record["content"]
    if _space_kind(content) is not None or _generated_of(content) is not None:
        out.append(("boundary", _normalize_loop(record["boundary"]), content))
    for shape in record["shapes"]:
        if shape["core"] is not None:
            continue
        content = shape["content"]
        if _space_kind(content) is None and _generated_of(content) is None:
            continue
        out.append(("shape:%s" % shape["id"], _normalize_loop(shape["points"]), content))
    return out


def _match_carrier_content(faces, carriers):
    # type: (List[Dict[str, Any]], List[Tuple[str, List[Tuple[float, float]], Dict[str, Any]]]) -> List[str]
    """Attach boundary, plot and shape content to the face that IS that polygon.

    Equality only: a carrier names its own polygon, so containment would be a
    guess, and a carrier the arrangement has since partitioned comes back for
    disclosure instead. Region content is matched FIRST, so a key addressing one
    of these faces still wins the face it names.
    """
    unmatched = []
    for label, loop, content in carriers:
        hits = [face for face in faces if _same_loop(face["loop"], loop)]
        if len(hits) != 1 or not _eligible(hits[0]):
            unmatched.append(label)
            continue
        hits[0]["content"] = content
    return unmatched


def _really_dropped(keys, region_content, carried):
    # type: (List[str], Dict[str, Dict[str, Any]], List[Any]) -> List[str]
    """Of `keys`, the ones whose content no region already carries.

    On the caller-supplied region path the regions arrive WITH their content and
    the payload still carries the same `regionContent`, so every key reads as
    unmatched although every one of them was already applied. Nothing was
    dropped there and saying so would be false. One region excuses one key, so a
    genuine drop standing beside an identical twin still discloses.
    """
    pool = [_blob(content) for content in carried]
    out = []
    for key in keys:
        blob = _blob(region_content.get(key))
        if blob in pool:
            pool.remove(blob)
            continue
        out.append(key)
    return out


def _floor_regions(record, resolved):
    # type: (Dict[str, Any], Optional[List[Dict[str, Any]]]) -> Tuple[List[Dict[str, Any]], List[str], bool]
    """(regions, unmatched content labels, derived_here) for one floor.

    A region is `{"id", "loop", "area_m2", "interior", "content"}` with `id`
    `region-<i>` by sorted origin, the spec's stable rule.

    Content reaches a region from `regionContent` first (the most specific
    address), then from the boundary, plot and shape carriers. What no face
    accepts is reported for disclosure, minus anything a region already carries:
    on the caller-supplied path the same content arrives twice and nothing is
    dropped.
    """
    derived_here = resolved is None
    if resolved is not None:
        candidates = []
        for region in resolved:
            loop = _normalize_loop(region["loop"])
            if len(loop) < 3:
                continue
            interior = _interior_point(loop)
            if not _contains(record["boundary"], interior):
                continue
            candidates.append((loop, _shoelace_area(loop), region["content"], interior))
        candidates.sort(key=lambda item: (_bbox(item[0])[0], _bbox(item[0])[1]))
    else:
        candidates = [
            (loop, area, None, _interior_point(loop)) for loop, area in _derive_faces(record)
        ]

    regions = []
    for index, (loop, area, content, interior) in enumerate(candidates):
        regions.append(
            {
                "id": "region-%d" % index,
                "loop": loop,
                "area_m2": area,
                "interior": interior,
                "content": content,
                "core": _core_of_face(loop, record),
            }
        )
    carried = [region["content"] for region in regions if region["content"] is not None]
    unmatched = _really_dropped(
        _match_region_content(regions, record["region_content"]), record["region_content"], carried
    )
    unmatched += _match_carrier_content(regions, _carriers(record))
    unmatched += list(record["orphan_content"])
    return (regions, sorted(unmatched), derived_here)


# --------------------------------------------------------------------------
# walls: drawn geometry only, merged once
# --------------------------------------------------------------------------

_ROLE_PRIORITY = {
    WallRole.EXTERIOR: 3,
    WallRole.CORE: 2,
    WallRole.PARTY: 1,
    WallRole.INTERIOR: 0,
    WallRole.PARAPET: 0,
    WallRole.RAILING: -1,
}


def _candidate(a, b, thickness_m, role, source):
    # type: (Sequence[float], Sequence[float], float, WallRole, str) -> Optional[Dict[str, Any]]
    """One axis-aligned wall run, or None when the edge is skew or degenerate."""
    horizontal = abs(a[1] - b[1]) <= JOIN_TOL_M
    vertical = abs(a[0] - b[0]) <= JOIN_TOL_M
    if horizontal == vertical:
        return None
    if horizontal:
        orient, pos = "h", 0.5 * (a[1] + b[1])
        s0, s1 = min(a[0], b[0]), max(a[0], b[0])
    else:
        orient, pos = "v", 0.5 * (a[0] + b[0])
        s0, s1 = min(a[1], b[1]), max(a[1], b[1])
    if s1 - s0 <= JOIN_TOL_M:
        return None
    return {
        "orient": orient,
        "pos": pos,
        "s0": s0,
        "s1": s1,
        "t": float(thickness_m),
        "role": role,
        "source": str(source),
    }


def _merge_candidates(candidates, storey):
    # type: (List[Dict[str, Any]], int) -> List[WallLine]
    """Collinear runs within 115 mm of one centreline become one WallLine.

    Merging is what stops a span drawn twice (a placed plan's edge over the
    region wall that already carries it) from becoming two walls. The merged run
    keeps the strongest role present (exterior beats core beats party beats
    interior) and the thickest section, so absorbing an interior duplicate can
    never demote a boundary wall.
    """
    walls = []  # type: List[WallLine]
    for orient in ("h", "v"):
        group = sorted(
            [c for c in candidates if c["orient"] == orient],
            key=lambda c: (c["pos"], c["s0"], c["s1"], c["source"]),
        )
        clusters = []  # type: List[List[Dict[str, Any]]]
        for cand in group:
            if clusters and cand["pos"] - clusters[-1][0]["pos"] <= MERGE_TOL_M:
                clusters[-1].append(cand)
            else:
                clusters.append([cand])
        for cluster in clusters:
            lead = sorted(
                cluster,
                key=lambda c: (-_ROLE_PRIORITY.get(c["role"], 0), -(c["s1"] - c["s0"]), c["pos"]),
            )[0]
            pos = lead["pos"]
            runs = []  # type: List[Dict[str, Any]]
            for cand in sorted(cluster, key=lambda c: (c["s0"], c["s1"])):
                if runs and cand["s0"] <= runs[-1]["s1"] + JOIN_TOL_M:
                    run = runs[-1]
                    run["s1"] = max(run["s1"], cand["s1"])
                    run["t"] = max(run["t"], cand["t"])
                    run["sources"].add(cand["source"])
                    if _ROLE_PRIORITY.get(cand["role"], 0) > _ROLE_PRIORITY.get(run["role"], 0):
                        run["role"] = cand["role"]
                else:
                    runs.append(
                        {
                            "s0": cand["s0"],
                            "s1": cand["s1"],
                            "t": cand["t"],
                            "role": cand["role"],
                            "sources": set([cand["source"]]),
                        }
                    )
            for run in runs:
                if orient == "h":
                    a = (run["s0"], pos)
                    b = (run["s1"], pos)
                else:
                    a = (pos, run["s0"])
                    b = (pos, run["s1"])
                walls.append(
                    WallLine(
                        id=wall_id(storey, orient, pos, run["s0"]),
                        storey=storey,
                        a=a,
                        b=b,
                        thickness_m=run["t"],
                        role=run["role"],
                        source="+".join(sorted(s for s in run["sources"] if s)) or None,
                    )
                )
    walls.sort(key=lambda w: w.id)
    return walls


def _wall_axis_of(wall):
    # type: (WallLine) -> Tuple[str, float, float, float]
    if abs(wall.a[1] - wall.b[1]) <= JOIN_TOL_M:
        return ("h", 0.5 * (wall.a[1] + wall.b[1]), min(wall.a[0], wall.b[0]), max(wall.a[0], wall.b[0]))
    return ("v", 0.5 * (wall.a[0] + wall.b[0]), min(wall.a[1], wall.b[1]), max(wall.a[1], wall.b[1]))


def _assign_room_sides(walls, rooms):
    # type: (List[WallLine], List[RoomPoly]) -> None
    """Fill `room_ids` = (left, right) by the wall normal; None outside.

    Left is the side a walker travelling a -> b has on their left in the y-DOWN
    plan frame: smaller y for a wall running +x, larger x for one running +y.
    The probe sits half a thickness plus 50 mm off the centreline, so it clears
    the wall it belongs to and lands in the room it points at.
    """
    shapes = []
    for room in sorted(rooms, key=lambda r: r.id):
        poly = _shapely_polygon(room.polygon)
        if poly is not None:
            shapes.append((room.id, poly))
    # smallest first: a core nested in a region is the more specific answer for a
    # probe inside it, and the region still answers on the far side of its wall.
    shapes.sort(key=lambda pair: (pair[1].area, pair[0]))
    for wall in walls:
        orient, pos, s0, s1 = _wall_axis_of(wall)
        mid = 0.5 * (s0 + s1)
        offset = 0.5 * wall.thickness_m + 0.05
        if orient == "h":
            left = (mid, pos - offset)
            right = (mid, pos + offset)
        else:
            left = (pos + offset, mid)
            right = (pos - offset, mid)
        wall.room_ids = (_room_at(shapes, left), _room_at(shapes, right))


def _room_at(shapes, point):
    # type: (List[Tuple[str, Polygon]], Sequence[float]) -> Optional[str]
    probe = Point(float(point[0]), float(point[1]))
    for room_ref, poly in shapes:
        if poly.contains(probe):
            return room_ref
    return None


def _attach_openings(walls, pending):
    # type: (List[WallLine], List[Dict[str, Any]]) -> Tuple[int, List[Dict[str, Any]]]
    """Place pending openings on the merged walls; returns (placed, dropped).

    An opening is anchored by (orientation, centreline, centre along the run);
    the wall carrying that run gets it, with the centre nudged inside the run and
    the width narrowed to it, so the opening cannot hang off a wall end. One that
    finds no wall, or that would sit on top of an opening already placed, is
    returned in `dropped` for the caller to disclose, never silently retargeted.
    """
    placed = 0
    dropped = []  # type: List[Dict[str, Any]]
    for spec in pending:
        best = None  # type: Optional[Tuple[float, WallLine, float, float]]
        for wall in walls:
            orient, pos, s0, s1 = _wall_axis_of(wall)
            if orient != spec["orient"]:
                continue
            if abs(pos - spec["pos"]) > MERGE_TOL_M:
                continue
            if spec["centre"] < s0 - JOIN_TOL_M or spec["centre"] > s1 + JOIN_TOL_M:
                continue
            width = min(spec["width"], max(s1 - s0 - 2.0 * JOIN_TOL_M, 0.0))
            if width <= 0.0:
                continue
            half = 0.5 * width
            centre = min(max(spec["centre"], s0 + half), s1 - half)
            if _overlaps_existing(wall, centre - s0, width):
                continue
            distance = abs(pos - spec["pos"])
            if best is None or distance < best[0]:
                best = (distance, wall, centre - s0, width)
        if best is None:
            dropped.append(spec)
            continue
        _distance, wall, offset, width = best
        wall.openings.append(
            Opening(
                id="",
                kind=spec["kind"],
                offset_m=offset,
                width_m=width,
                sill_m=spec.get("sill"),
                head_m=spec.get("head"),
                provenance=spec["provenance"],
            )
        )
        placed += 1
    for wall in walls:
        wall.openings.sort(key=lambda o: o.offset_m)
        for index, opening in enumerate(wall.openings):
            opening.id = opening_id(wall.id, index)
    return (placed, dropped)


def _overlaps_existing(wall, offset, width):
    # type: (WallLine, float, float) -> bool
    lo = offset - 0.5 * width
    hi = offset + 0.5 * width
    for opening in wall.openings:
        other_lo = opening.offset_m - 0.5 * opening.width_m
        other_hi = opening.offset_m + 0.5 * opening.width_m
        if min(hi, other_hi) - max(lo, other_lo) > JOIN_TOL_M:
            return True
    return False


# --------------------------------------------------------------------------
# a generated unit plan placed into its region
# --------------------------------------------------------------------------


def _select_plan(generated):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    plans = [p for p in (generated.get("plans") or []) if isinstance(p, dict)]
    if not plans:
        return None
    selected = generated.get("selectedPlanId")
    for plan in plans:
        if selected is not None and plan.get("id") == selected:
            return plan
    return plans[0]


def _place_generated(region, generated, storey, interior_t):
    # type: (Dict[str, Any], Dict[str, Any], int, float) -> Dict[str, Any]
    """Translate a selected UnitFloorplan into floor coordinates.

    The plan is authored in its OWN `floorWidth` x `floorHeight` frame (feet,
    y-down, undressed), which the client's `housingUnitForApi` FLOORS from the
    polygon it was asked for, so that frame is not (genW, genH) whenever the
    region is fractional. The frame is what the plan's placements are measured
    in, so it is the frame this scales and centres against, exactly as both
    client renderers do; `genW`/`genH` are the size the plan was ASKED for and
    serve only the staleness verdict.

    A single UNIFORM factor `min(bw/plan_w, bh/plan_h)` (never anisotropic, the
    standing client rule) fits the frame to the region and the residual is
    centred. Drift past 0.15 ft from (genW, genH) additionally means the region
    itself moved under a plan generated for another size: that is disclosed as
    stale.
    """
    plan = _select_plan(generated)
    out = {"rooms": [], "candidates": [], "doors": [], "stale": False, "plan_id": None, "unknown_names": []}
    if plan is None:
        return out
    out["plan_id"] = str(plan.get("id") or "")

    gen_w = _m(generated.get("genW") if generated.get("genW") is not None else plan.get("floorWidth"))
    gen_h = _m(generated.get("genH") if generated.get("genH") is not None else plan.get("floorHeight"))
    plan_w = _m(plan.get("floorWidth") if plan.get("floorWidth") is not None else generated.get("genW"))
    plan_h = _m(plan.get("floorHeight") if plan.get("floorHeight") is not None else generated.get("genH"))
    bx, by, bw, bh = _bbox(region["loop"])
    if plan_w <= 0.0 or plan_h <= 0.0:
        return out

    stale = gen_w > 0.0 and gen_h > 0.0 and (
        abs(bw - gen_w) > STALE_EPS_M or abs(bh - gen_h) > STALE_EPS_M
    )
    scale = min(bw / plan_w, bh / plan_h)
    off_x = bx + 0.5 * (bw - plan_w * scale)
    off_y = by + 0.5 * (bh - plan_h * scale)
    out["stale"] = stale

    rects = []  # type: List[Tuple[str, float, float, float, float]]
    for index, placement in enumerate(
        [p for p in (plan.get("placements") or []) if isinstance(p, dict)]
    ):
        width = _m(placement.get("width")) * scale
        height = _m(placement.get("height")) * scale
        if width <= JOIN_TOL_M or height <= JOIN_TOL_M:
            continue
        x = off_x + _m(placement.get("x")) * scale
        y = off_y + _m(placement.get("y")) * scale
        name = str(placement.get("name") or "Room %d" % (index + 1))
        occupancy, known = _occupancy_for_name(name)
        source = "%s-r%d" % (region["id"], index)
        element = room_id(storey, source)
        if not known:
            out["unknown_names"].append(element)
        out["rooms"].append(
            RoomPoly(
                id=element,
                storey=storey,
                name=name,
                occupancy=occupancy,
                polygon=[(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
                area_m2=width * height,
                unit_id=region["id"],
                interior_unknown=False,
                source=source,
            )
        )
        rects.append((element, x, y, width, height))

    shared = _shared_edges(rects)
    for edge in shared:
        a = (edge["s0"], edge["pos"]) if edge["orient"] == "h" else (edge["pos"], edge["s0"])
        b = (edge["s1"], edge["pos"]) if edge["orient"] == "h" else (edge["pos"], edge["s1"])
        candidate = _candidate(a, b, interior_t, WallRole.INTERIOR, region["id"])
        if candidate is not None:
            out["candidates"].append(candidate)
    names = dict((room.id, room.name) for room in out["rooms"])
    out["doors"] = _assume_doors(rects, shared, names)
    return out


def _shared_edges(rects):
    # type: (List[Tuple[str, float, float, float, float]]) -> List[Dict[str, Any]]
    """Every wall segment two placed rooms genuinely share, sorted."""
    edges = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            # vertical interface: right edge of one on the left edge of the other
            for left, right in ((rects[i], rects[j]), (rects[j], rects[i])):
                lx = left[1] + left[3]
                if abs(lx - right[1]) > JOIN_TOL_M:
                    continue
                s0 = max(left[2], right[2])
                s1 = min(left[2] + left[4], right[2] + right[4])
                if s1 - s0 > JOIN_TOL_M:
                    edges.append(
                        {"orient": "v", "pos": lx, "s0": s0, "s1": s1, "a": left[0], "b": right[0]}
                    )
            # horizontal interface
            for top, bottom in ((rects[i], rects[j]), (rects[j], rects[i])):
                ty = top[2] + top[4]
                if abs(ty - bottom[2]) > JOIN_TOL_M:
                    continue
                s0 = max(top[1], bottom[1])
                s1 = min(top[1] + top[3], bottom[1] + bottom[3])
                if s1 - s0 > JOIN_TOL_M:
                    edges.append(
                        {"orient": "h", "pos": ty, "s0": s0, "s1": s1, "a": top[0], "b": bottom[0]}
                    )
    edges.sort(key=lambda e: (e["orient"], e["pos"], e["s0"], e["a"], e["b"]))
    return edges


def _assume_doors(rects, shared, names):
    # type: (List[Tuple[str, float, float, float, float]], List[Dict[str, Any]], Dict[str, str]) -> List[Dict[str, Any]]
    """One 0.9 m door per edge of a spanning tree over the placed rooms.

    Housing plans are stored UNDRESSED, so no door survives the payload. The
    fallback is plan_json's: rooms sharing at least 2.8 ft of wall may carry a
    door, and a breadth-first tree from the living room (else the first room by
    id) doors exactly enough interfaces to make every room reachable. A pair
    sharing less than a door width gets nothing: a lintel must never be invented
    over a doorway that cannot exist.
    """
    if len(rects) < 2:
        return []
    passable = [e for e in shared if e["s1"] - e["s0"] >= MIN_DOOR_SHARE_M]
    neighbours = {}  # type: Dict[str, List[Tuple[str, Dict[str, Any]]]]
    for edge in passable:
        neighbours.setdefault(edge["a"], []).append((edge["b"], edge))
        neighbours.setdefault(edge["b"], []).append((edge["a"], edge))
    for key in neighbours:
        neighbours[key].sort(key=lambda pair: (pair[0], pair[1]["orient"], pair[1]["pos"]))

    ids = sorted(r[0] for r in rects)
    start = ids[0]
    for prefix in ("living", "hall", "dining"):
        hit = [e for e in ids if str(names.get(e, "")).strip().lower().startswith(prefix)]
        if hit:
            start = hit[0]
            break
    seen = set([start])
    queue = [start]
    doors = []
    while queue:
        current = queue.pop(0)
        for other, edge in neighbours.get(current, []):
            if other in seen:
                continue
            seen.add(other)
            queue.append(other)
            doors.append(
                {
                    "orient": edge["orient"],
                    "pos": edge["pos"],
                    "centre": 0.5 * (edge["s0"] + edge["s1"]),
                    "width": ASSUMED_DOOR_WIDTH_M,
                    "kind": OpeningKind.DOOR,
                    "provenance": Provenance.ASSUMED_MID_WALL,
                }
            )
    return doors


def _assume_windows(walls, rooms):
    # type: (List[WallLine], List[RoomPoly]) -> List[Dict[str, Any]]
    """One 1.2 m window mid-run on every exterior wall of a lit room.

    Off by default (finding 10): the orchestrator turns it on when the target
    system is masonry, so IS 4326 Table 4's opening checks have data to read
    instead of an empty wall. Requires `room_ids`, so it runs after the sides
    are assigned.
    """
    lit = set()
    for room in rooms:
        if room.occupancy in (Occupancy.HABITABLE, Occupancy.KITCHEN):
            lit.add(room.id)
    specs = []
    for wall in sorted(walls, key=lambda w: w.id):
        if wall.role != WallRole.EXTERIOR:
            continue
        if not any(rid in lit for rid in wall.room_ids if rid):
            continue
        orient, pos, s0, s1 = _wall_axis_of(wall)
        if s1 - s0 < ASSUMED_WINDOW_WIDTH_M + 0.6:
            continue
        specs.append(
            {
                "orient": orient,
                "pos": pos,
                "centre": 0.5 * (s0 + s1),
                "width": ASSUMED_WINDOW_WIDTH_M,
                "kind": OpeningKind.WINDOW,
                "provenance": Provenance.ASSUMED_MID_WALL,
                "sill": ASSUMED_WINDOW_SILL_M,
                "head": ASSUMED_WINDOW_HEAD_M,
            }
        )
    return specs


# --------------------------------------------------------------------------
# cores, roof, entry
# --------------------------------------------------------------------------


def _core_entries(records):
    # type: (List[Dict[str, Any]]) -> Tuple[List[Core], List[str]]
    """Shapes carrying `core` -> Core elements, one per identity across storeys.

    The reducers keep every copy's points identical, so a copy that differs is
    corrupted input and refused (E_CORE_MISMATCH). Geometry comes from the shape
    points; CORE_SIZES_FT is a sanity reference, never a substitute.
    """
    seen = {}  # type: Dict[str, Dict[str, Any]]
    unknown = []  # type: List[str]
    for record in sorted(records, key=lambda r: r["level"]):
        for shape in record["shapes"]:
            core = shape["core"]
            if core is None:
                continue
            source = str(core.get("id") or shape["id"])
            raw_kind = str(core.get("kind") or "")
            rect = _bbox(shape["points"])
            entry = seen.get(source)
            if entry is None:
                seen[source] = {
                    "source": source,
                    "kind": raw_kind,
                    "rect": rect,
                    "storeys": [record["level"]],
                }
                continue
            if entry["kind"] != raw_kind or not _same_rect(entry["rect"], rect):
                raise AdapterError(
                    "E_CORE_MISMATCH",
                    "core '%s' is %s at %s on storey %d and %s at %s on storey %d; "
                    "copies of one core must be identical on every floor"
                    % (
                        source,
                        entry["kind"] or "unset",
                        _rect_ft(entry["rect"]),
                        entry["storeys"][0],
                        raw_kind or "unset",
                        _rect_ft(rect),
                        record["level"],
                    ),
                    {"core_id": source},
                )
            entry["storeys"].append(record["level"])

    cores = []
    for source in sorted(seen):
        entry = seen[source]
        element = core_id(source)
        try:
            kind = CoreKind(entry["kind"])
        except ValueError:
            kind = CoreKind.UTILITY_SHAFT
            unknown.append(element)
        x, y, w, h = entry["rect"]
        cores.append(
            Core(
                id=element,
                kind=kind,
                x_m=x,
                y_m=y,
                w_m=w,
                h_m=h,
                storeys=sorted(set(entry["storeys"])),
                stair_landing_hint=None,
            )
        )
    return (cores, unknown)


def _rect_ft(rect):
    # type: (Tuple[float, float, float, float]) -> str
    return "(%.2f, %.2f, %.2f x %.2f) ft" % (
        m_to_ft(rect[0]),
        m_to_ft(rect[1]),
        m_to_ft(rect[2]),
        m_to_ft(rect[3]),
    )


def _roof_meta(design):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """meta.roof: what loads/dead.py turns into roof load and masonry.py into a band.

    An absent roof is flat (RC slab default). An unrecognized type keeps its name
    on the wire but takes a flat rise, so nothing downstream invents a slope.
    """
    raw = design.get("roof")
    kind = str(raw) if raw else "flat"
    return {
        "type": kind,
        "rise_ratio": ROOF_RISE_RATIO.get(kind, 0.0),
        "overhang_ft": ROOF_OVERHANG_FT,
        "on": "bbox",
    }


def _default_entry(loop):
    # type: (Sequence[Sequence[float]]) -> Optional[Tuple[float, float]]
    """Midpoint of the southernmost run (north is -y, so south is max y)."""
    best = None  # type: Optional[Tuple[float, float, float, float]]
    count = len(loop)
    for i in range(count):
        a = loop[i]
        b = loop[(i + 1) % count]
        if abs(a[1] - b[1]) > JOIN_TOL_M:
            continue
        lo, hi = min(a[0], b[0]), max(a[0], b[0])
        if hi - lo <= JOIN_TOL_M:
            continue
        if best is None or a[1] > best[0] + JOIN_TOL_M or (
            abs(a[1] - best[0]) <= JOIN_TOL_M and hi - lo > best[3]
        ):
            best = (a[1], lo, hi, hi - lo)
    if best is None:
        return None
    return (0.5 * (best[1] + best[2]), best[0])


def _entry_spec(walls, point, width_m):
    # type: (List[WallLine], Sequence[float], float) -> Optional[Dict[str, Any]]
    """A 3.5 ft entry opening on the exterior wall nearest the entry point."""
    best = None  # type: Optional[Tuple[float, str, str, float, float]]
    for wall in sorted(walls, key=lambda w: w.id):
        if wall.role != WallRole.EXTERIOR:
            continue
        orient, pos, s0, s1 = _wall_axis_of(wall)
        if orient == "h":
            along, across = float(point[0]), float(point[1])
        else:
            along, across = float(point[1]), float(point[0])
        clamped = min(max(along, s0), s1)
        distance = ((clamped - along) ** 2 + (across - pos) ** 2) ** 0.5
        if best is None or distance < best[0] - 1e-9:
            best = (distance, wall.id, orient, pos, clamped)
    if best is None:
        return None
    _distance, _wid, orient, pos, centre = best
    return {
        "orient": orient,
        "pos": pos,
        "centre": centre,
        "width": width_m,
        "kind": OpeningKind.ENTRY,
        "provenance": Provenance.ENTRY_POINT,
    }


def _storey_kind(record, regions):
    # type: (Dict[str, Any], List[Dict[str, Any]]) -> StoreyKind
    """`stilt` is the soft-storey hook: open ground under a built stack.

    A drawn segment or a drawn non-core shape is built area, so the storey is
    units. A CIRCULATION CORE is not: the frontend auto-places a mandatory stair
    core on every floor the moment a second floor exists, so short-circuiting on
    any shape put stilt out of reach of every multi-storey house there is.

    What remains must be labeled and every label must be parking or green. The
    label can sit on a region or, for a segment-free floor, on the boundary or
    plot carrier, which is the only slot the frontend can store it in.
    """
    if record["segments"]:
        return StoreyKind.UNITS
    for shape in record["shapes"]:
        if shape["core"] is None:
            return StoreyKind.UNITS
    labeled = False
    for content in [record["content"]] + [region["content"] for region in regions]:
        if _generated_of(content) is not None:
            return StoreyKind.UNITS
        kind = _space_kind(content)
        if kind is None:
            continue
        if kind not in UNBUILT_SPACE_KINDS:
            return StoreyKind.UNITS
        labeled = True
    return StoreyKind.STILT if labeled else StoreyKind.UNITS


def _canonical(value):
    # type: (Any) -> Any
    if isinstance(value, bool) or value is None or isinstance(value, int) or isinstance(value, str):
        return value
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return dict((str(k), _canonical(v)) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        items = sorted(value) if isinstance(value, set) else list(value)
        return [_canonical(v) for v in items]
    return str(value)


def _blob(value):
    # type: (Any) -> str
    """One canonical string per value, for hashing and for equality of content."""
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))


def _fingerprint(design, stack, options, resolved_regions):
    # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any], Any) -> str
    """sha256 of this stack's canonical input; a Redis dedup key that is stable.

    Everything that can change the model is in: the stack's own geometry, the
    design fields that reach the model beside it (`name`, `roof` and `entry`
    each move meta, and `entry` moves a placed lintel), the adapter options and
    the caller's regions. The `plot_id` REQUEST FILTER is deliberately out, so
    asking for one stack and asking for all of them hand back the same
    fingerprint for the same structure; `meta.stacks` is built from the
    unfiltered split for the same reason, and `meta.options` records the request
    as sent.
    """
    payload = {
        "design_id": str(design.get("id") or ""),
        "design_name": str(design.get("name") or ""),
        "roof": design.get("roof"),
        # the design entry point is read for the primary boundary only; an
        # additional plot falls back to its own southernmost run either way.
        "entry": design.get("entry") if stack["plot_id"] == PRIMARY_STACK else None,
        "plot_id": stack["plot_id"],
        "options": dict((k, v) for k, v in options.items() if k != "plot_id"),
        "floors": stack["floors"],
        "resolved_regions": resolved_regions,
    }
    return hashlib.sha256(_blob(payload).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the adapter
# --------------------------------------------------------------------------


def from_housing(
    design,
    plot_id=None,
    resolved_regions=None,
    storey_height_ft=HOUSING_STOREY_HEIGHT_FT,
    plinth_height_ft=HOUSING_PLINTH_FT,
    exterior_wall_ft=EXTERIOR_WALL_FT,
    interior_wall_ft=None,
    system_hint="rc_frame",
    assume_windows=False,
):
    # type: (Dict[str, Any], Optional[str], Any, float, float, float, Optional[float], str, bool) -> List[StructuralModel]
    """A HousingDesign -> one StructuralModel per BUILT plot stack.

    `plot_id` filters to a single stack. `resolved_regions` is the frontend's own
    `detectFloorRegions` output per floor and is preferred over re-deriving the
    faces here; see the module docstring for both paths. Refusals are raised as
    `AdapterError`; everything softer lands on each model's ladder.
    """
    all_stacks = split_plot_stacks(design)
    stacks = list(all_stacks)
    known = [stack["plot_id"] for stack in stacks]
    if plot_id is not None:
        if plot_id not in known:
            raise AdapterError(
                "E_BAD_ENVELOPE",
                "no plot stack '%s' in this design; it carries %s" % (plot_id, ", ".join(known)),
                {"plot_id": plot_id, "stacks": known},
            )
        stacks = [stack for stack in stacks if stack["plot_id"] == plot_id]
        if not stacks[0]["built"]:
            raise AdapterError(
                "E_EMPTY_PLAN",
                "plot stack '%s' draws no wall beyond its boundary and carries only "
                "open ground, so there is no structure to derive" % plot_id,
                {"plot_id": plot_id},
            )

    built = [stack for stack in stacks if stack["built"]]
    if not built:
        raise AdapterError(
            "E_EMPTY_PLAN",
            "this design has no built plot: every stack draws no wall beyond its "
            "boundary and carries only parking or green labels",
            {"stacks": known},
        )

    if interior_wall_ft is None:
        display = design.get("wallDisplay")
        display = display if isinstance(display, dict) else {}
        interior_wall_ft = _num(display.get("interiorWallFt"), DEFAULT_INTERIOR_WALL_FT)
        if interior_wall_ft <= 0.0:
            interior_wall_ft = DEFAULT_INTERIOR_WALL_FT

    options = {
        "storey_height_ft": float(storey_height_ft),
        "plinth_height_ft": float(plinth_height_ft),
        "exterior_wall_ft": float(exterior_wall_ft),
        "interior_wall_ft": float(interior_wall_ft),
        "system_hint": str(system_hint),
        "assume_windows": bool(assume_windows),
        "plot_id": plot_id,
        "resolved_regions": resolved_regions is not None,
    }

    models = []
    for stack in built:
        # `all_stacks`, never the filtered list: `meta.stacks` describes the
        # design, so a one-plot request must not shrink it away from what the
        # same stack reports unfiltered (its fingerprint does not move either).
        models.append(_build_stack_model(design, stack, options, resolved_regions, all_stacks))
    return models


def _build_stack_model(design, stack, options, resolved_regions, all_stacks):
    # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any], Any, List[Dict[str, Any]]) -> StructuralModel
    records = sorted(stack["floors"], key=lambda r: r["level"])
    levels = [record["level"] for record in records]
    if not levels:
        raise AdapterError(
            "E_UNSUPPORTED_STOREYS",
            "plot stack '%s' has no storeys" % stack["plot_id"],
            {"plot_id": stack["plot_id"]},
        )
    if len(levels) > MAX_HOUSING_FLOORS:
        raise AdapterError(
            "E_UNSUPPORTED_STOREYS",
            "housing supports at most %d storeys, plot stack '%s' has %d"
            % (MAX_HOUSING_FLOORS, stack["plot_id"], len(levels)),
            {"plot_id": stack["plot_id"], "storeys": len(levels)},
        )
    if levels != list(range(len(levels))):
        raise AdapterError(
            "E_STACK_DISCONTINUOUS",
            "plot stack '%s' is drawn on storeys %s; a built storey cannot sit over "
            "a storey the plot does not reach" % (stack["plot_id"], levels),
            {"plot_id": stack["plot_id"], "levels": levels},
        )

    height_m = ft_to_m(options["storey_height_ft"])
    exterior_t = ft_to_m(options["exterior_wall_ft"])
    interior_t = ft_to_m(options["interior_wall_ft"])
    if height_m <= 0.0 or exterior_t <= 0.0 or interior_t <= 0.0:
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "storey height and wall thicknesses must be positive, got %s ft, %s ft, %s ft"
            % (options["storey_height_ft"], options["exterior_wall_ft"], options["interior_wall_ft"]),
        )
    try:
        system = System(options["system_hint"])
    except ValueError:
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "unknown structural system '%s'; expected one of %s"
            % (options["system_hint"], ", ".join(sorted(s.value for s in System))),
        )

    design_id = str(design.get("id") or "housing")
    model = StructuralModel(
        id="%s-%s" % (design_id, stack["plot_id"]),
        source=ModelSource.HOUSING,
        system=system,
        fingerprint=_fingerprint(design, stack, options, resolved_regions),
    )

    entry_point = None  # type: Optional[Tuple[float, float]]
    ground = records[0]
    if stack["plot_id"] == PRIMARY_STACK and isinstance(design.get("entry"), (list, tuple)):
        entry_point = _pt_m(design["entry"])
    if entry_point is None:
        entry_point = _default_entry(ground["boundary"])

    stale = []  # type: List[str]
    unmatched = []  # type: List[str]
    unknown_rooms = []  # type: List[str]
    unknown_regions = []  # type: List[str]
    core_overlaps = []  # type: List[str]
    assumed_doors = 0
    dropped_doors = 0
    assumed_windows = 0
    derived_here = False

    for order, record in enumerate(records):
        storey = record["level"]
        resolved = _resolved_for_floor(resolved_regions, record, order)
        regions, floor_unmatched, floor_derived = _floor_regions(record, resolved)
        unmatched += ["s%d:%s" % (storey, key) for key in floor_unmatched]
        derived_here = derived_here or floor_derived

        model.storeys.append(
            Storey(
                index=storey,
                name=record["label"] or ("Level %d" % storey),
                bottom_z_m=storey * height_m,
                height_m=height_m,
                kind=_storey_kind(record, regions),
                source_id=record["floor_id"] or None,
            )
        )

        candidates = []  # type: List[Dict[str, Any]]
        loop = record["boundary"]
        for i in range(len(loop)):
            candidate = _candidate(
                loop[i], loop[(i + 1) % len(loop)], exterior_t, WallRole.EXTERIOR, stack["plot_id"]
            )
            if candidate is not None:
                candidates.append(candidate)
        for segment in record["segments"]:
            candidate = _candidate(segment["a"], segment["b"], interior_t, WallRole.INTERIOR, segment["id"])
            if candidate is not None:
                candidates.append(candidate)
        for shape in record["shapes"]:
            role = WallRole.CORE if shape["core"] is not None else WallRole.INTERIOR
            points = shape["points"]
            for i in range(len(points)):
                candidate = _candidate(
                    points[i], points[(i + 1) % len(points)], interior_t, role, shape["id"]
                )
                if candidate is not None:
                    candidates.append(candidate)

        rooms = []  # type: List[RoomPoly]
        pending = []  # type: List[Dict[str, Any]]
        for region in regions:
            if region["core"] is not None:
                rooms.append(_core_room(region, storey))
                continue
            content = region["content"]
            generated = _generated_of(content)
            placed = None
            if generated is not None:
                placed = _place_generated(region, generated, storey, interior_t)
            if placed is not None and placed["rooms"]:
                rooms += placed["rooms"]
                candidates += placed["candidates"]
                pending += placed["doors"]
                assumed_doors += len(placed["doors"])
                unknown_rooms += placed["unknown_names"]
                core_overlaps += _core_overlaps(region, regions, placed["rooms"])
                if placed["stale"]:
                    stale.append("%s/%s" % (region["id"], placed["plan_id"] or "plan"))
                continue
            rooms.append(_region_room(region, storey))
            if _space_kind(content) is None:
                unknown_regions.append(rooms[-1].id)
            elif rooms[-1].occupancy == Occupancy.OTHER and _space_kind(content) == "other":
                unknown_rooms.append(rooms[-1].id)

        walls = _merge_candidates(candidates, storey)
        _assign_room_sides(walls, rooms)
        if storey == 0 and entry_point is not None:
            spec = _entry_spec(walls, entry_point, ft_to_m(ENTRY_WIDTH_FT))
            if spec is not None:
                pending.append(spec)
        window_specs = _assume_windows(walls, rooms) if options["assume_windows"] else []
        _placed, dropped = _attach_openings(walls, pending + window_specs)
        assumed_windows += len(window_specs) - len(
            [spec for spec in dropped if spec["kind"] == OpeningKind.WINDOW]
        )
        dropped_doors += len([spec for spec in dropped if spec["kind"] != OpeningKind.WINDOW])

        model.walls += walls
        model.rooms += rooms

    cores, unknown_cores = _core_entries(records)
    model.cores = cores

    model.meta = {
        "north": "-y",
        "design_id": design_id,
        "design_name": str(design.get("name") or ""),
        "plot_id": stack["plot_id"],
        "storey_height_ft": options["storey_height_ft"],
        "plinth_height_ft": options["plinth_height_ft"],
        "exterior_wall_ft": options["exterior_wall_ft"],
        "interior_wall_ft": options["interior_wall_ft"],
        "roof": _roof_meta(design),
        "entry_ft": [m_to_ft(entry_point[0]), m_to_ft(entry_point[1])] if entry_point else None,
        "regions": "polygonize" if derived_here else "caller",
        "floor_ids": [record["floor_id"] for record in records],
        "stacks": [{"plot_id": s["plot_id"], "built": s["built"]} for s in all_stacks],
        "options": dict(options),
    }

    _disclose(
        model,
        stale=stale,
        unmatched=unmatched,
        unknown_rooms=unknown_rooms,
        unknown_regions=unknown_regions,
        unknown_cores=unknown_cores,
        core_overlaps=core_overlaps,
        assumed_doors=assumed_doors,
        dropped_doors=dropped_doors,
        assumed_windows=assumed_windows,
        assume_windows=options["assume_windows"],
    )
    return model


def _core_overlaps(region, regions, rooms):
    # type: (Dict[str, Any], List[Dict[str, Any]], List[RoomPoly]) -> List[str]
    """Ids of placed unit rooms lying across a core nested in their own region.

    A unit plan tiles its region entire, and a circulation core drawn inside that
    region is a face of its own carrying its own room, so the two describe the
    same floor area twice. The plan ships as generated (clipping a placement
    would invent a room shape the generator never produced) and the double count
    is disclosed rather than hidden.
    """
    boxes = []
    for other in regions:
        if other is region or other["core"] is None:
            continue
        if _contains(region["loop"], other["interior"]):
            boxes.append(_bbox(other["loop"]))
    if not boxes:
        return []
    hits = []
    for room in rooms:
        rx, ry, rw, rh = _bbox(room.polygon)
        for bx, by, bw, bh in boxes:
            wide = min(rx + rw, bx + bw) - max(rx, bx)
            tall = min(ry + rh, by + bh) - max(ry, by)
            if wide > JOIN_TOL_M and tall > JOIN_TOL_M:
                hits.append(room.id)
                break
    return hits


#: A core's own footprint reads as this occupancy (its live load is not a bedroom's).
CORE_OCCUPANCY = {
    CoreKind.STAIRS: Occupancy.STAIR,
    CoreKind.FIRE_EXIT: Occupancy.STAIR,
    CoreKind.LIFT: Occupancy.LIFT,
    CoreKind.UTILITY_SHAFT: Occupancy.VOID,
}


def _core_room(region, storey):
    # type: (Dict[str, Any], int) -> RoomPoly
    """The floor area a core occupies, so takedown sees a stair, not a hole."""
    shape = region["core"]
    core = shape["core"] or {}
    raw_kind = str(core.get("kind") or "")
    try:
        kind = CoreKind(raw_kind)
    except ValueError:
        kind = CoreKind.UTILITY_SHAFT
    source = str(core.get("id") or shape["id"])
    return RoomPoly(
        id=room_id(storey, region["id"]),
        storey=storey,
        name=raw_kind or kind.value,
        occupancy=CORE_OCCUPANCY.get(kind, Occupancy.OTHER),
        polygon=list(region["loop"]),
        area_m2=region["area_m2"],
        unit_id=None,
        interior_unknown=False,
        source=source,
    )


def _region_room(region, storey):
    # type: (Dict[str, Any], int) -> RoomPoly
    """A region with no unit plan: its space label, or an unknown interior."""
    content = region["content"]
    kind = _space_kind(content)
    element = room_id(storey, region["id"])
    if kind is None:
        return RoomPoly(
            id=element,
            storey=storey,
            name="region",
            occupancy=Occupancy.OTHER,
            polygon=list(region["loop"]),
            area_m2=region["area_m2"],
            unit_id=None,
            interior_unknown=True,
            source=region["id"],
        )
    space = content.get("space") if isinstance(content, dict) else {}
    custom = str((space or {}).get("customName") or "").strip()
    occupancy = SPACE_OCCUPANCY.get(kind, Occupancy.OTHER)
    name = custom or kind
    if kind == "other" and custom:
        named, known = _occupancy_for_name(custom)
        if known:
            occupancy = named
    return RoomPoly(
        id=element,
        storey=storey,
        name=name,
        occupancy=occupancy,
        polygon=list(region["loop"]),
        area_m2=region["area_m2"],
        unit_id=None,
        interior_unknown=False,
        source=region["id"],
    )


def _disclose(model, stale, unmatched, unknown_rooms, unknown_regions, unknown_cores,
              core_overlaps, assumed_doors, dropped_doors, assumed_windows, assume_windows):
    # type: (StructuralModel, List[str], List[str], List[str], List[str], List[str], List[str], int, int, int, bool) -> None
    """Every fallback this adapter took, on the ladder, in a fixed order."""
    stage = "adapters.housing"
    if stale:
        model.add_warning(
            "W_STALE_GENERATED",
            "%d generated plan(s) no longer match their region and were uniformly "
            "rescaled and centred: %s" % (len(stale), ", ".join(sorted(stale))),
            (),
            stage=stage,
        )
    if unmatched:
        model.add_warning(
            "W_REGION_CONTENT_UNMATCHED",
            "%d content entr(ies) could not be matched to a derived face and were "
            "dropped: %s" % (len(unmatched), ", ".join(sorted(unmatched))),
            (),
            stage=stage,
        )
    if core_overlaps:
        model.add_warning(
            "W_CORE_UNIT_OVERLAP",
            "%d placed unit room(s) lie across a circulation core drawn inside their "
            "region; the floor area is described twice and placement decides whether "
            "to carve" % len(core_overlaps),
            sorted(set(core_overlaps)),
            stage=stage,
        )
    if assumed_doors:
        model.add_warning(
            "W_DOOR_ASSUMED",
            "%d door(s) were assumed mid-wall at %.2f m; housing unit plans are stored "
            "undressed and carry none" % (assumed_doors, ASSUMED_DOOR_WIDTH_M),
            (),
            stage=stage,
        )
    if dropped_doors:
        model.add_warning(
            "W_DOOR_UNMAPPED",
            "%d assumed opening(s) found no wall line to sit on and were dropped" % dropped_doors,
            (),
            stage=stage,
        )
    if unknown_regions:
        model.add_warning(
            "W_UNIT_NO_PLAN",
            "%d region(s) carry no label and no unit plan; their interiors are unknown "
            "and take a partition allowance" % len(unknown_regions),
            sorted(unknown_regions),
            stage=stage,
        )
    unknown = sorted(set(unknown_rooms) | set(unknown_cores))
    if unknown:
        model.add_warning(
            "W_OCCUPANCY_UNKNOWN",
            "%d element(s) carry a name or kind outside the known vocabulary and were "
            "mapped to a neutral occupancy" % len(unknown),
            unknown,
            stage=stage,
        )
    storeys = len(model.storeys)
    if storeys >= 2 and not [c for c in model.cores if c.kind == CoreKind.STAIRS]:
        model.add_warning(
            "W_NO_STAIR",
            "this %d storey stack draws no stair core" % storeys,
            (),
            stage=stage,
        )
    if assume_windows:
        if assumed_windows:
            model.add_warning(
                "W_ASSUMED_OPENINGS",
                "%d window(s) were assumed at %.2f m on exterior walls of habitable "
                "rooms for the code opening checks" % (assumed_windows, ASSUMED_WINDOW_WIDTH_M),
                (),
                stage=stage,
            )
    else:
        model.add_warning(
            "N_WINDOWS_NOT_ASSUMED",
            "no windows were assumed; window lintels are omitted",
            (),
            stage=stage,
        )
