"""One engine floor plan to a repeated-storey StructuralModel.

Input is a door_connectivity plan in any of the engine envelopes (a bare room
list, `{floorPlans}`, `{Documents}` or the full `{response:{Documents}}`), in
FEET, y-down, origin top-left, zero thickness centrelines. Output is the
canonical SI model, converted once, here.

Refusals (AdapterError, never a silent repair): E_BAD_ENVELOPE, E_EMPTY_PLAN,
E_NOT_RECTANGULAR, E_ROOM_OVERLAP, E_PLAN_NOT_GAPLESS, E_UNSUPPORTED_STOREYS.
The gapless rule is what rejects relaxed multi_ptpg layouts; door_connectivity
plans pass by construction.

Disclosed, never hidden: W_OCCUPANCY_UNKNOWN, W_DOOR_ASSUMED, W_DOOR_UNMAPPED,
W_ADJACENCY_SHORTFALL, W_ASSUMED_OPENINGS, N_WINDOWS_NOT_ASSUMED.

Wall extraction. Every room edge lies on an axis parallel line; lines within
115 mm are one line (`_geom.LINE_TOL_M`). On each line the room edges cut
elementary intervals, each interval records the room on either side, and
adjacent intervals with the same signature (role, thickness, material, room
pair) merge into one WallLine. One room only means an exterior wall at
`exterior_wall_ft`; two rooms mean an interior wall at `interior_wall_ft`.
Segments keep one room pair each, so a wall is never a lie about what it
separates: nothing downstream has to re-derive the pair.

room_ids convention. `(left, right)` by the wall normal, the left normal of a
direction (dx, dy) being (dy, -dx) in the y-down plan frame. Walls are always
emitted a -> b in increasing coordinate, so a horizontal wall reads
(room above, room below) and a vertical wall reads (room right, room left).

Opening synthesis lives here and nowhere else (finding 10). Doors are 0.9 m at
the midpoint of the longest run a room pair shares, taken from the plan's ptpg
adjacency; a pair sharing less than 2.8 ft, or listed in adjacency_shortfalls,
gets no door at all, because a lintel must not be invented over a doorway that
cannot exist. A reachability pass then doors any room the adjacency graph left
unreachable. Windows are assumed only when `assume_windows` is set (the
orchestrator sets it for masonry, so IS 4326 Table 4 has data to check); with
it off the model carries the N_WINDOWS_NOT_ASSUMED note instead of invented
openings.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..model import (
    SEVERITY_ORDER,
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
    add_disclosure,
    ft_to_m,
    m_to_ft,
    opening_id,
    registry_severity,
    room_id,
    wall_id,
)
from ._geom import (
    EPS_M,
    LINE_TOL_M,
    POINT_TOL_M,
    AdapterError,
    cluster_values,
    fingerprint,
    interval_overlap,
    merge_intervals,
    polygon_area,
    rect_polygon,
    rects_overlap_area,
)

# ---------------------------------------------------------------------------
# tolerances and synthesis constants
# ---------------------------------------------------------------------------

# circular_coordinates must agree with the room's stated width/height (feet).
RECT_TOL_FT = 0.05

# sum(room areas) must equal the bbox area within this fraction, else voids.
GAPLESS_TOL_FRACTION = 0.005
# A residual above this absolute floor is a real void even in a large plan.
GAPLESS_ABSOLUTE_FLOOR_SQFT = 1.0

# Rooms sharing more than this on both axes overlap (feet, tiny by design).
OVERLAP_TOL_FT = 0.01

# Unified assumed door width (finding 10). Windows are 1.2 m, sill 0.9, head 2.1.
DOOR_WIDTH_M = 0.9
WINDOW_WIDTH_M = 1.2
WINDOW_SILL_M = 0.9
WINDOW_HEAD_M = 2.1

# A room pair sharing less than this cannot take a door (feet, engine convention).
MIN_SHARED_FT = 2.8

# Line tolerance when mapping a dressed door onto a wall (the openingsOnWallLoose precedent).
DRESSED_TOL_FT = 0.45

# Assumed windows go on exterior walls of these occupancies only.
WINDOW_OCCUPANCIES = (Occupancy.HABITABLE,)

RECT_TOL_M = ft_to_m(RECT_TOL_FT)
OVERLAP_TOL_M = ft_to_m(OVERLAP_TOL_FT)
MIN_SHARED_M = ft_to_m(MIN_SHARED_FT)
DRESSED_TOL_M = ft_to_m(DRESSED_TOL_FT)

# The refusal message the spec pins for relaxed multi_ptpg layouts.
NOT_GAPLESS_MESSAGE = (
    "this plan contains voids or is a relaxed multi_ptpg layout; "
    "the structural module accepts door_connectivity gapless plans only"
)


# ---------------------------------------------------------------------------
# occupancy: this adapter is the only room-name parser (finding 22)
# ---------------------------------------------------------------------------

NAME_KIND = MappingProxyType(
    {
        # habitable
        "bedroom": Occupancy.HABITABLE,
        "bed room": Occupancy.HABITABLE,
        "bed": Occupancy.HABITABLE,
        "master": Occupancy.HABITABLE,
        "living": Occupancy.HABITABLE,
        "drawing": Occupancy.HABITABLE,
        "dining": Occupancy.HABITABLE,
        "hall": Occupancy.HABITABLE,
        "family": Occupancy.HABITABLE,
        "guest": Occupancy.HABITABLE,
        "lounge": Occupancy.HABITABLE,
        "study": Occupancy.HABITABLE,
        "office": Occupancy.HABITABLE,
        "den": Occupancy.HABITABLE,
        "puja": Occupancy.HABITABLE,
        "pooja": Occupancy.HABITABLE,
        "prayer": Occupancy.HABITABLE,
        "room": Occupancy.HABITABLE,
        # kitchen
        "kitchen": Occupancy.KITCHEN,
        "kitchenette": Occupancy.KITCHEN,
        "pantry": Occupancy.KITCHEN,
        # bath
        "bath": Occupancy.BATH,
        "bathroom": Occupancy.BATH,
        "washroom": Occupancy.BATH,
        "shower": Occupancy.BATH,
        # water closet
        "toilet": Occupancy.WC,
        "wc": Occupancy.WC,
        "water closet": Occupancy.WC,
        "powder": Occupancy.WC,
        "lavatory": Occupancy.WC,
        "latrine": Occupancy.WC,
        "restroom": Occupancy.WC,
        # balcony and open sitting
        "balcony": Occupancy.BALCONY,
        "terrace": Occupancy.BALCONY,
        "verandah": Occupancy.BALCONY,
        "veranda": Occupancy.BALCONY,
        "sit out": Occupancy.BALCONY,
        "sitout": Occupancy.BALCONY,
        "deck": Occupancy.BALCONY,
        # circulation
        "corridor": Occupancy.CORRIDOR,
        "passage": Occupancy.CORRIDOR,
        "hallway": Occupancy.CORRIDOR,
        "circulation": Occupancy.CORRIDOR,
        "stair": Occupancy.STAIR,
        "staircase": Occupancy.STAIR,
        "lift": Occupancy.LIFT,
        "elevator": Occupancy.LIFT,
        "lobby": Occupancy.LOBBY,
        "foyer": Occupancy.LOBBY,
        "entrance": Occupancy.LOBBY,
        "entry": Occupancy.LOBBY,
        "porch": Occupancy.LOBBY,
        # service
        "utility": Occupancy.UTILITY,
        "laundry": Occupancy.UTILITY,
        "service": Occupancy.UTILITY,
        "wash": Occupancy.UTILITY,
        "store": Occupancy.STORAGE,
        "storage": Occupancy.STORAGE,
        "closet": Occupancy.STORAGE,
        "wardrobe": Occupancy.STORAGE,
        "parking": Occupancy.PARKING,
        "garage": Occupancy.PARKING,
        "carport": Occupancy.PARKING,
        "car parking": Occupancy.PARKING,
        # open and unbuilt
        "garden": Occupancy.GREEN,
        "lawn": Occupancy.GREEN,
        "green": Occupancy.GREEN,
        "courtyard": Occupancy.GREEN,
        "open space": Occupancy.GREEN,
        "void": Occupancy.VOID,
        "shaft": Occupancy.VOID,
        "duct": Occupancy.VOID,
    }
)

def normalize_name(name: Any) -> str:
    """Lowercase, whitespace collapsed room name; the key both lookups use."""
    return " ".join(str(name or "").strip().lower().split())


def occupancy_for_name(name: Any) -> Optional[Occupancy]:
    """Occupancy for a room name, matched on complete whitespace tokens."""
    normalized = normalize_name(name)
    if not normalized:
        return None
    if normalized in NAME_KIND:
        return NAME_KIND[normalized]
    tokens = normalized.split()
    matches = []  # type: List[Tuple[int, Occupancy]]
    for key, occupancy in NAME_KIND.items():
        key_tokens = key.split()
        width = len(key_tokens)
        if any(tokens[index:index + width] == key_tokens for index in range(len(tokens) - width + 1)):
            matches.append((width, occupancy))
    if not matches:
        return None
    wet = [match for match in matches if match[1] in (Occupancy.BATH, Occupancy.WC)]
    choices = wet or matches
    occupancies = {match[1] for match in choices}
    if len(occupancies) != 1:
        return None
    return max(choices, key=lambda match: match[0])[1]


def _coerce_occupancy(value: Any, where: str) -> Occupancy:
    """An Occupancy from an override value; an unknown literal is a refusal, not a guess."""
    if isinstance(value, Occupancy):
        return value
    try:
        return Occupancy(str(value))
    except ValueError:
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "occupancy_map[" + where + "] is not a known occupancy: " + repr(value),
            {"value": str(value)},
        )


# ---------------------------------------------------------------------------
# intermediate records (feet at ingestion, metres from _RoomRec onward)
# ---------------------------------------------------------------------------


@dataclass
class _RoomRec:
    """One normalized room rectangle in metres, plan frame."""

    index: int
    source_id: str
    name: str
    occupancy: Occupancy
    x_m: float
    y_m: float
    w_m: float
    h_m: float

    def rect(self) -> Tuple[float, float, float, float]:
        return (self.x_m, self.y_m, self.w_m, self.h_m)

    def span(self, orient: str) -> Tuple[float, float]:
        """Extent along the wall direction: x for a horizontal line, y for a vertical one."""
        if orient == "h":
            return (self.x_m, self.x_m + self.w_m)
        return (self.y_m, self.y_m + self.h_m)

    def across(self, orient: str) -> Tuple[float, float]:
        """Extent across the wall direction: y for a horizontal line, x for a vertical one."""
        if orient == "h":
            return (self.y_m, self.y_m + self.h_m)
        return (self.x_m, self.x_m + self.w_m)


@dataclass
class _OpenRec:
    kind: OpeningKind
    offset_m: float
    width_m: float
    sill_m: Optional[float]
    head_m: Optional[float]
    provenance: Provenance


@dataclass
class _SegRec:
    """One wall segment before it is instantiated per storey."""

    orient: str  # "h" or "v"
    pos_m: float
    s0_m: float
    s1_m: float
    role: WallRole
    thickness_m: float
    left: Optional[int]  # room index on the wall's left side, None outside
    right: Optional[int]
    openings: List[_OpenRec] = field(default_factory=list)

    def length_m(self) -> float:
        return self.s1_m - self.s0_m

    def points(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        if self.orient == "h":
            return ((self.s0_m, self.pos_m), (self.s1_m, self.pos_m))
        return ((self.pos_m, self.s0_m), (self.pos_m, self.s1_m))

    def pair(self) -> Optional[Tuple[int, int]]:
        """The room pair this wall separates, ordered, or None for an exterior wall."""
        if self.left is None or self.right is None:
            return None
        return (min(self.left, self.right), max(self.left, self.right))

    def interior_room(self) -> Optional[int]:
        """The single room an exterior wall bounds."""
        if self.left is None:
            return self.right
        if self.right is None:
            return self.left
        return None

    def has_door(self) -> bool:
        return any(o.kind == OpeningKind.DOOR for o in self.openings)


class _Pending:
    """Disclosure batches: one entry per code, element ids expanded over storeys."""

    def __init__(self) -> None:
        self.messages = {}  # type: Dict[str, List[str]]
        self.refs = {}  # type: Dict[str, List[Tuple[Any, ...]]]

    def add(self, code: str, message: str, refs: Sequence[Tuple[Any, ...]] = ()) -> None:
        registry_severity(code)  # unknown codes raise here, at the producer
        self.messages.setdefault(code, []).append(message)
        self.refs.setdefault(code, []).extend(refs)

    def codes(self) -> List[str]:
        """Codes in ladder order: errors, then warnings, then notes, each sorted."""
        return sorted(self.messages, key=lambda c: (SEVERITY_ORDER[registry_severity(c)], c))


# ---------------------------------------------------------------------------
# step 1: unwrap the envelope
# ---------------------------------------------------------------------------


def _documents(plan: Any) -> Optional[Dict[str, Any]]:
    """The Documents block of whichever envelope was handed in, or None for a bare list."""
    if isinstance(plan, dict):
        if isinstance(plan.get("response"), dict) and isinstance(
            plan["response"].get("Documents"), dict
        ):
            return plan["response"]["Documents"]
        if isinstance(plan.get("Documents"), dict):
            return plan["Documents"]
        if isinstance(plan.get("floorPlans"), list):
            return plan
    return None


def _unwrap(plan: Any, plan_index: int) -> Tuple[List[Any], Dict[str, Any]]:
    """(room dicts, Documents block) from any accepted envelope."""
    if plan is None:
        raise AdapterError("E_BAD_ENVELOPE", "plan payload is None")

    documents = _documents(plan)
    if documents is None:
        if not isinstance(plan, list):
            raise AdapterError(
                "E_BAD_ENVELOPE",
                "unrecognized plan payload: expected a room list, {floorPlans}, "
                "{Documents} or {response:{Documents}}, got " + type(plan).__name__,
            )
        # A bare list is either the rooms themselves or a list of plans.
        if plan and all(isinstance(item, list) for item in plan):
            documents = {"floorPlans": plan}
        else:
            return (list(plan), {})

    plans = documents.get("floorPlans")
    if not isinstance(plans, list):
        raise AdapterError(
            "E_BAD_ENVELOPE", "Documents.floorPlans is missing or is not a list"
        )
    if not plans:
        raise AdapterError("E_EMPTY_PLAN", "Documents.floorPlans is empty")
    if plan_index < 0 or plan_index >= len(plans):
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "plan_index " + str(plan_index) + " is outside floorPlans of length " + str(len(plans)),
        )
    selected = plans[plan_index]
    if not isinstance(selected, list):
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "floorPlans[" + str(plan_index) + "] must be a list of rooms, got "
            + type(selected).__name__,
        )
    return (list(selected), documents)


def _per_plan(value: Any, plan_index: int, plan_count: int) -> Any:
    """Unwrap a value the engine emits once per plan (plot_fit, adjacency_shortfalls).

    A parallel array has one entry per plan and every entry is itself a record
    (a dict, or a list of records). A ptpg adjacency matrix fails that test at
    its rows, which are lists of numbers, so an N x N matrix is never mistaken
    for N plans' worth of anything.
    """
    if not isinstance(value, list) or not value or len(value) != plan_count:
        return value
    for item in value:
        if isinstance(item, dict):
            continue
        if isinstance(item, list) and (not item or isinstance(item[0], (list, dict))):
            continue
        return value
    if 0 <= plan_index < len(value):
        return value[plan_index]
    return value


# ---------------------------------------------------------------------------
# step 1 continued: normalize rooms
# ---------------------------------------------------------------------------


def _points_of(room: Dict[str, Any]) -> List[Tuple[float, float]]:
    """The room outline in feet, from circular_coordinates or the wall endpoints."""
    coords = room.get("circular_coordinates")
    if isinstance(coords, list) and len(coords) >= 3:
        return [(float(p[0]), float(p[1])) for p in coords]
    walls = room.get("walls")
    if isinstance(walls, list) and walls:
        points = []
        for wall in walls:
            points.append((float(wall["x1"]), float(wall["y1"])))
            points.append((float(wall["x2"]), float(wall["y2"])))
        return points
    return []


def _source_ids(rooms: Sequence[Dict[str, Any]]) -> List[str]:
    """Source id per room: _id, id, name, else region-<i> ranked by sorted origin."""
    origins = []
    for i, room in enumerate(rooms):
        points = _points_of(room)
        xs = [p[0] for p in points] or [0.0]
        ys = [p[1] for p in points] or [0.0]
        origins.append((min(xs), min(ys), i))
    rank = {}
    for order, entry in enumerate(sorted(origins)):
        rank[entry[2]] = order

    out = []
    for i, room in enumerate(rooms):
        raw = room.get("_id") or room.get("id") or room.get("name")
        out.append(str(raw) if raw else "region-" + str(rank[i]))
    return out


def _room_records(rooms: Sequence[Any]) -> List[_RoomRec]:
    """Rooms as metre rectangles; every geometric lie is refused here."""
    if not rooms:
        raise AdapterError("E_EMPTY_PLAN", "the plan carries no rooms")

    for i, room in enumerate(rooms):
        if not isinstance(room, dict):
            raise AdapterError(
                "E_BAD_ENVELOPE",
                "room " + str(i) + " must be an object, got " + type(room).__name__,
            )

    ids = _source_ids(rooms)
    duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
    if duplicates:
        raise AdapterError(
            "E_BAD_ENVELOPE",
            "rooms do not carry unique ids: " + ", ".join(duplicates),
            {"element_ids": duplicates},
        )

    records = []  # type: List[_RoomRec]
    for i, room in enumerate(rooms):
        source_id = ids[i]
        points = _points_of(room)
        if len(points) < 3:
            raise AdapterError(
                "E_BAD_ENVELOPE",
                "room " + source_id + " carries neither circular_coordinates nor walls",
                {"element_ids": [source_id]},
            )
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0_ft, x1_ft = min(xs), max(xs)
        y0_ft, y1_ft = min(ys), max(ys)
        w_ft = x1_ft - x0_ft
        h_ft = y1_ft - y0_ft
        if w_ft <= RECT_TOL_FT or h_ft <= RECT_TOL_FT:
            raise AdapterError(
                "E_NOT_RECTANGULAR",
                "room " + source_id + " is degenerate: " + _ft2(w_ft) + " by " + _ft2(h_ft) + " ft",
                {"element_ids": [source_id]},
            )

        # The outline itself must be a rectangle: an L-shaped room is a refusal,
        # never a bounding box quietly substituted for the real geometry.
        outline_area = polygon_area(points) if len(points) >= 4 else 0.0
        if len(set((round(p[0], 4), round(p[1], 4)) for p in points)) != 4 or abs(
            outline_area - w_ft * h_ft
        ) > max(RECT_TOL_FT * max(w_ft, h_ft), RECT_TOL_FT):
            raise AdapterError(
                "E_NOT_RECTANGULAR",
                "room " + source_id + " outline is not a rectangle: "
                + str(len(points)) + " points enclosing " + _ft2(outline_area)
                + " sqft inside a " + _ft2(w_ft) + " by " + _ft2(h_ft) + " ft box",
                {"element_ids": [source_id]},
            )

        for key, measured in (("width", w_ft), ("height", h_ft)):
            stated = room.get(key)
            if stated is None:
                continue
            if abs(float(stated) - measured) > RECT_TOL_FT:
                raise AdapterError(
                    "E_NOT_RECTANGULAR",
                    "room " + source_id + " states " + key + " " + _ft2(float(stated))
                    + " ft but its outline measures " + _ft2(measured) + " ft",
                    {"element_ids": [source_id]},
                )

        records.append(
            _RoomRec(
                index=i,
                source_id=source_id,
                name=str(room.get("name") or source_id),
                occupancy=Occupancy.OTHER,
                x_m=ft_to_m(x0_ft),
                y_m=ft_to_m(y0_ft),
                w_m=ft_to_m(w_ft),
                h_m=ft_to_m(h_ft),
            )
        )
    return records


def _ft2(value: float) -> str:
    """Feet formatted for a refusal message."""
    return "{0:.2f}".format(float(value))


# ---------------------------------------------------------------------------
# step 2: gapless validation
# ---------------------------------------------------------------------------


def _check_gapless(
    records: Sequence[_RoomRec], pending: Optional[_Pending] = None
) -> Tuple[float, float, float, float]:
    """Refuse overlaps and voids; return the plan bbox in metres."""
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            ax0, ay0, ax1, ay1 = a.x_m, a.y_m, a.x_m + a.w_m, a.y_m + a.h_m
            bx0, by0, bx1, by1 = b.x_m, b.y_m, b.x_m + b.w_m, b.y_m + b.h_m
            dx = min(ax1, bx1) - max(ax0, bx0)
            dy = min(ay1, by1) - max(ay0, by0)
            if dx > OVERLAP_TOL_M and dy > OVERLAP_TOL_M:
                shared = rects_overlap_area(a.rect(), b.rect())
                raise AdapterError(
                    "E_ROOM_OVERLAP",
                    "rooms " + a.source_id + " and " + b.source_id + " overlap by "
                    + _ft2(m_to_ft(dx) * m_to_ft(dy)) + " sqft",
                    {"element_ids": [a.source_id, b.source_id], "overlap_m2": shared},
                )

    x0 = min(r.x_m for r in records)
    y0 = min(r.y_m for r in records)
    x1 = max(r.x_m + r.w_m for r in records)
    y1 = max(r.y_m + r.h_m for r in records)
    bbox_area = (x1 - x0) * (y1 - y0)
    if bbox_area <= EPS_M:
        raise AdapterError("E_EMPTY_PLAN", "the plan bounding box has no area")

    total = sum(r.w_m * r.h_m for r in records)
    residual = abs(bbox_area - total)
    if (
        residual > GAPLESS_TOL_FRACTION * bbox_area
        or _sqft(residual) > GAPLESS_ABSOLUTE_FLOOR_SQFT
    ):
        raise AdapterError(
            "E_PLAN_NOT_GAPLESS",
            NOT_GAPLESS_MESSAGE
            + " (rooms cover " + _ft2(_sqft(total))
            + " sqft of a " + _ft2(_sqft(bbox_area)) + " sqft envelope)",
            {"rooms_m2": total, "bbox_m2": bbox_area},
        )
    if residual > 0.0 and pending is not None:
        pending.add(
            "N_GAPLESS_RESIDUAL",
            "the room envelope retains a %.3f sqft residual below both the %.1f sqft absolute and %.1f pct relative void floors"
            % (_sqft(residual), GAPLESS_ABSOLUTE_FLOOR_SQFT, 100.0 * GAPLESS_TOL_FRACTION),
            [("room", record.index) for record in records],
        )
    return (x0, y0, x1 - x0, y1 - y0)


def _sqft(area_m2: float) -> float:
    """Square metres to square feet, for refusal messages only."""
    return float(area_m2) * m_to_ft(1.0) * m_to_ft(1.0)


# ---------------------------------------------------------------------------
# step 3: occupancy
# ---------------------------------------------------------------------------


def _apply_occupancy(
    records: Sequence[_RoomRec], occupancy_map: Optional[Dict[Any, Any]], pending: _Pending
) -> None:
    """Set every room's occupancy; unknown names become `other` and are disclosed."""
    overrides = {}  # type: Dict[str, Any]
    for key, value in (occupancy_map or {}).items():
        overrides[str(key)] = value
        overrides[normalize_name(key)] = value

    unknown = []  # type: List[Tuple[int, str]]
    for record in records:
        override = None
        for key in (record.source_id, record.name, normalize_name(record.name)):
            if key in overrides:
                override = overrides[key]
                break
        if override is not None:
            record.occupancy = _coerce_occupancy(override, record.source_id)
            continue
        guessed = occupancy_for_name(record.name)
        if guessed is None:
            record.occupancy = Occupancy.OTHER
            unknown.append((record.index, record.name))
        else:
            record.occupancy = guessed

    if unknown:
        names = ", ".join(sorted(set(name for _, name in unknown)))
        pending.add(
            "W_OCCUPANCY_UNKNOWN",
            str(len(unknown)) + " room name(s) did not map to a known occupancy and were "
            "taken as 'other': " + names,
            [("room", index) for index, _ in unknown],
        )


# ---------------------------------------------------------------------------
# step 4: wall extraction
# ---------------------------------------------------------------------------


def _extract_segments(
    records: Sequence[_RoomRec], exterior_m: float, interior_m: float
) -> List[_SegRec]:
    """Shared room edges and boundary edges as merged, room-tagged wall segments."""
    segments = []  # type: List[_SegRec]

    for orient in ("h", "v"):
        positions = []  # type: List[float]
        for record in records:
            lo, hi = record.across(orient)
            positions.append(lo)
            positions.append(hi)
        lines = cluster_values(positions, LINE_TOL_M)

        for pos in lines:
            low_side = []  # type: List[Tuple[Tuple[float, float], int]]
            high_side = []  # type: List[Tuple[Tuple[float, float], int]]
            for record in records:
                lo, hi = record.across(orient)
                span = record.span(orient)
                # A room sits on ONE side of a line. A room thinner than the
                # tolerance would otherwise land on both and become a wall
                # between itself and itself, so the nearer edge wins.
                to_lo = abs(lo - pos)
                to_hi = abs(hi - pos)
                if to_hi <= LINE_TOL_M and to_hi <= to_lo:
                    low_side.append((span, record.index))
                elif to_lo <= LINE_TOL_M:
                    high_side.append((span, record.index))
            if not low_side and not high_side:
                continue

            breaks = cluster_values(
                [value for span, _ in low_side + high_side for value in span], LINE_TOL_M
            )
            runs = {}  # type: Dict[Tuple[Any, ...], List[Tuple[float, float]]]
            for i in range(len(breaks) - 1):
                start, end = breaks[i], breaks[i + 1]
                if end - start <= POINT_TOL_M:
                    continue
                low = _covering(low_side, start, end)
                high = _covering(high_side, start, end)
                if low is None and high is None:
                    continue
                exterior = low is None or high is None
                role = WallRole.EXTERIOR if exterior else WallRole.INTERIOR
                thickness = exterior_m if exterior else interior_m
                # left normal (dy, -dx): a horizontal wall reads (above, below),
                # a vertical wall reads (right, left).
                left, right = (low, high) if orient == "h" else (high, low)
                key = (role.value, round(thickness, 9), left, right)
                runs.setdefault(key, []).append((start, end))

            for key in sorted(runs, key=lambda k: (k[0], k[1], _none_last(k[2]), _none_last(k[3]))):
                role_value, thickness, left, right = key
                for lo, hi in merge_intervals(runs[key], POINT_TOL_M):
                    segments.append(
                        _SegRec(
                            orient=orient,
                            pos_m=pos,
                            s0_m=lo,
                            s1_m=hi,
                            role=WallRole(role_value),
                            thickness_m=thickness,
                            left=left,
                            right=right,
                        )
                    )

    segments.sort(key=lambda s: (s.orient, s.pos_m, s.s0_m))
    return segments


def _covering(
    side: Sequence[Tuple[Tuple[float, float], int]], start: float, end: float
) -> Optional[int]:
    """The room index covering the majority of [start, end]; lowest index wins a tie."""
    span_len = end - start
    for (s0, s1), index in sorted(side, key=lambda item: item[1]):
        if interval_overlap(start, end, s0, s1) > 0.5 * span_len:
            return index
    return None


def _none_last(value: Optional[int]) -> Tuple[int, int]:
    return (1, 0) if value is None else (0, value)


# ---------------------------------------------------------------------------
# step 5: openings
# ---------------------------------------------------------------------------


def _pair_walls(segments: Sequence[_SegRec]) -> Dict[Tuple[int, int], List[int]]:
    """Room pair to the indices of the interior walls that separate it."""
    out = {}  # type: Dict[Tuple[int, int], List[int]]
    for index, segment in enumerate(segments):
        pair = segment.pair()
        if pair is not None:
            out.setdefault(pair, []).append(index)
    return out


def _longest(segments: Sequence[_SegRec], indices: Sequence[int]) -> int:
    """The longest of a set of segments; ties break on (position, start) for determinism."""
    return sorted(
        indices,
        key=lambda i: (-segments[i].length_m(), segments[i].orient, segments[i].pos_m, segments[i].s0_m),
    )[0]


def _place_door(segment: _SegRec, clamped: List[int]) -> _OpenRec:
    """A 0.9 m door at the midpoint of the segment, narrowed only if the wall is shorter."""
    length = segment.length_m()
    width = DOOR_WIDTH_M
    if width > length - EPS_M:
        width = length
        clamped.append(1)
    door = _OpenRec(
        kind=OpeningKind.DOOR,
        offset_m=0.5 * length,
        width_m=width,
        sill_m=None,
        head_m=None,
        provenance=Provenance.ASSUMED_MID_WALL,
    )
    segment.openings.append(door)
    return door


def _resolve_room(reference: Any, records: Sequence[_RoomRec]) -> Optional[int]:
    """A room index from an integer index, a source id or a name."""
    if isinstance(reference, bool):
        return None
    if isinstance(reference, int):
        return reference if 0 <= reference < len(records) else None
    key = str(reference)
    normalized = normalize_name(key)
    for record in records:
        if record.source_id == key:
            return record.index
    for record in records:
        if normalize_name(record.name) == normalized:
            return record.index
    return None


def _pairs_from(raw: Any, records: Sequence[_RoomRec]) -> List[Tuple[int, int]]:
    """Room index pairs from an adjacency matrix, an edge list or a shortfall list."""
    if not isinstance(raw, list) or not raw:
        return []

    if _is_matrix(raw):
        pairs = []
        for i in range(len(raw)):
            for j in range(i + 1, len(raw)):
                if raw[i][j]:
                    pairs.append((i, j))
        return _clean_pairs(pairs, records)

    pairs = []
    for entry in raw:
        items = _pair_items(entry)
        if items is None:
            continue
        a = _resolve_room(items[0], records)
        b = _resolve_room(items[1], records)
        if a is None or b is None or a == b:
            continue
        pairs.append((a, b))
    return _clean_pairs(pairs, records)


def _pair_items(entry: Any) -> Optional[Tuple[Any, Any]]:
    """The two room references carried by one edge or shortfall entry."""
    if isinstance(entry, dict):
        for key in ("pair", "rooms", "edge"):
            value = entry.get(key)
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return (value[0], value[1])
        for first, second in (("a", "b"), ("u", "v"), ("room1", "room2"), ("from", "to")):
            if first in entry and second in entry:
                return (entry[first], entry[second])
        return None
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return (entry[0], entry[1])
    return None


def _is_matrix(raw: Sequence[Any]) -> bool:
    """A square, symmetric, hollow 0/1 matrix; anything else is read as an edge list."""
    size = len(raw)
    for row in raw:
        if not isinstance(row, list) or len(row) != size:
            return False
        for value in row:
            if isinstance(value, bool):
                continue
            if not isinstance(value, (int, float)) or value not in (0, 1):
                return False
    for i in range(size):
        if raw[i][i]:
            return False
        for j in range(size):
            if bool(raw[i][j]) != bool(raw[j][i]):
                return False
    return True


def _clean_pairs(
    pairs: Sequence[Tuple[int, int]], records: Sequence[_RoomRec]
) -> List[Tuple[int, int]]:
    count = len(records)
    out = set()
    for a, b in pairs:
        if a == b or not (0 <= a < count) or not (0 <= b < count):
            continue
        out.add((min(a, b), max(a, b)))
    return sorted(out)


def _synthesize_doors(
    segments: List[_SegRec],
    records: Sequence[_RoomRec],
    edges: Sequence[Tuple[int, int]],
    shortfalls: Sequence[Tuple[int, int]],
    pending: _Pending,
) -> None:
    """Assume doors from the adjacency graph, then repair reachability (spec step 5b)."""
    pair_walls = _pair_walls(segments)
    shortfall_set = set(shortfalls)
    refused = []  # type: List[str]
    clamped = []  # type: List[int]
    doored = []  # type: List[Tuple[Any, ...]]

    for pair in edges:
        names = records[pair[0]].source_id + " and " + records[pair[1]].source_id
        if pair in shortfall_set:
            refused.append(names + " (listed as an adjacency shortfall)")
            continue
        indices = pair_walls.get(pair)
        if not indices:
            refused.append(names + " (share no wall)")
            continue
        index = _longest(segments, indices)
        if segments[index].length_m() < MIN_SHARED_M:
            refused.append(
                names + " (share only " + _ft2(m_to_ft(segments[index].length_m())) + " ft)"
            )
            continue
        if not segments[index].has_door():
            _place_door(segments[index], clamped)
            doored.append(("opening", index, len(segments[index].openings) - 1))

    stranded = _repair_reachability(
        segments, records, pair_walls, shortfall_set, clamped, doored
    )
    for index in stranded:
        refused.append(
            records[index].source_id + " (no wall long enough to reach the plan's door graph)"
        )

    if doored:
        message = str(len(doored)) + " door(s) were assumed at 0.9 m wide, mid wall, on the " \
            "longest run each adjacent room pair shares; the plan carried none"
        if clamped:
            message += "; " + str(len(clamped)) + " were narrowed to their wall run"
        pending.add("W_DOOR_ASSUMED", message, doored)
    if refused:
        pending.add(
            "W_ADJACENCY_SHORTFALL",
            "no door assumed between " + "; ".join(refused),
            [],
        )


def _repair_reachability(
    segments: List[_SegRec],
    records: Sequence[_RoomRec],
    pair_walls: Dict[Tuple[int, int], List[int]],
    shortfall_set: set,
    clamped: List[int],
    doored: List[Tuple[Any, ...]],
) -> List[int]:
    """Door any unreachable room onto the reachable set; return what stays stranded."""
    if not records:
        return []
    start = _start_room(records)
    reachable = _reachable(segments, records, start)

    progress = True
    while progress and len(reachable) < len(records):
        progress = False
        for record in records:
            if record.index in reachable:
                continue
            best = None  # type: Optional[int]
            for pair in sorted(pair_walls):
                if record.index not in pair or pair in shortfall_set:
                    continue
                other = pair[0] if pair[1] == record.index else pair[1]
                if other not in reachable:
                    continue
                for index in pair_walls[pair]:
                    if segments[index].has_door():
                        continue
                    # One rule for "can a doorway exist here", the same 2.8 ft
                    # the adjacency pass uses; the repair never invents a door
                    # the synthesis would have refused.
                    if segments[index].length_m() < MIN_SHARED_M:
                        continue
                    if best is None or segments[index].length_m() > segments[best].length_m():
                        best = index
            if best is None:
                continue
            _place_door(segments[best], clamped)
            doored.append(("opening", best, len(segments[best].openings) - 1))
            reachable = _reachable(segments, records, start)
            progress = True
            break

    return sorted(r.index for r in records if r.index not in reachable)


def _start_room(records: Sequence[_RoomRec]) -> int:
    """The living room if the plan names one, else the first room."""
    for record in records:
        if normalize_name(record.name).startswith("living"):
            return record.index
    return records[0].index


def _reachable(segments: Sequence[_SegRec], records: Sequence[_RoomRec], start: int) -> set:
    """Rooms reachable from `start` through walls that carry a door."""
    graph = {}  # type: Dict[int, List[int]]
    for segment in segments:
        pair = segment.pair()
        if pair is None or not segment.has_door():
            continue
        graph.setdefault(pair[0], []).append(pair[1])
        graph.setdefault(pair[1], []).append(pair[0])
    seen = set([start])
    queue = [start]
    while queue:
        node = queue.pop(0)
        for other in sorted(graph.get(node, ())):
            if other not in seen:
                seen.add(other)
                queue.append(other)
    return seen


def _map_dressed(
    segments: List[_SegRec],
    dressed: Sequence[Any],
    kind: OpeningKind,
    default_width_m: float,
    pending: _Pending,
) -> int:
    """Map dressed PlanDoor/PlanWindow dicts onto collinear walls; count what mapped."""
    mapped = 0
    unmapped = []  # type: List[str]
    for entry in dressed:
        if not isinstance(entry, dict):
            unmapped.append(repr(entry))
            continue
        try:
            x_ft = float(entry.get("x", entry.get("cx", 0.0)))
            y_ft = float(entry.get("y", entry.get("cy", 0.0)))
        except (TypeError, ValueError):
            unmapped.append(repr(entry))
            continue
        width_m = ft_to_m(float(entry.get("width", entry.get("w", m_to_ft(default_width_m)))))
        sill_m = _opt_ft(entry.get("sill"))
        head_m = _opt_ft(entry.get("head"))
        orientations = _orientations(entry)

        index = _nearest_wall(segments, ft_to_m(x_ft), ft_to_m(y_ft), orientations)
        if index is None:
            unmapped.append("(" + _ft2(x_ft) + ", " + _ft2(y_ft) + ") ft")
            continue
        segment = segments[index]
        along = ft_to_m(x_ft) if segment.orient == "h" else ft_to_m(y_ft)
        offset = min(max(along - segment.s0_m, 0.0), segment.length_m())
        segment.openings.append(
            _OpenRec(
                kind=kind,
                offset_m=offset,
                width_m=width_m,
                sill_m=sill_m,
                head_m=head_m,
                provenance=Provenance.DRESSED,
            )
        )
        mapped += 1

    if unmapped:
        pending.add(
            "W_DOOR_UNMAPPED",
            str(len(unmapped)) + " dressed " + kind.value + "(s) sat on no wall line within "
            + _ft2(DRESSED_TOL_FT) + " ft: " + ", ".join(unmapped),
            [],
        )
    return mapped


def _orientations(entry: Dict[str, Any]) -> Tuple[str, ...]:
    """The wall orientations a dressed opening may sit on; both when it does not say."""
    raw = entry.get("orientation", entry.get("orient", entry.get("dir")))
    text = normalize_name(raw)
    if text.startswith("h"):
        return ("h",)
    if text.startswith("v"):
        return ("v",)
    return ("h", "v")


def _nearest_wall(
    segments: Sequence[_SegRec], x_m: float, y_m: float, orientations: Sequence[str]
) -> Optional[int]:
    """The collinear wall nearest a dressed opening centre, within the line tolerance."""
    best = None  # type: Optional[int]
    best_gap = None  # type: Optional[float]
    for index, segment in enumerate(segments):
        if segment.orient not in orientations:
            continue
        across = y_m if segment.orient == "h" else x_m
        along = x_m if segment.orient == "h" else y_m
        gap = abs(across - segment.pos_m)
        if gap > DRESSED_TOL_M:
            continue
        if along < segment.s0_m - DRESSED_TOL_M or along > segment.s1_m + DRESSED_TOL_M:
            continue
        if best_gap is None or gap < best_gap - 1e-12:
            best = index
            best_gap = gap
    return best


def _opt_ft(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return ft_to_m(float(value))
    except (TypeError, ValueError):
        return None


def _assume_windows(
    segments: List[_SegRec], records: Sequence[_RoomRec], pending: _Pending
) -> None:
    """One 1.2 m window per habitable exterior wall, so IS 4326 Table 4 has data."""
    placed = []  # type: List[Tuple[Any, ...]]
    for index, segment in enumerate(segments):
        if segment.role != WallRole.EXTERIOR or segment.openings:
            continue
        room = segment.interior_room()
        if room is None or records[room].occupancy not in WINDOW_OCCUPANCIES:
            continue
        if segment.length_m() < WINDOW_WIDTH_M + POINT_TOL_M:
            continue
        segment.openings.append(
            _OpenRec(
                kind=OpeningKind.WINDOW,
                offset_m=0.5 * segment.length_m(),
                width_m=WINDOW_WIDTH_M,
                sill_m=WINDOW_SILL_M,
                head_m=WINDOW_HEAD_M,
                provenance=Provenance.ASSUMED_MID_WALL,
            )
        )
        placed.append(("opening", index, len(segment.openings) - 1))

    if placed:
        pending.add(
            "W_ASSUMED_OPENINGS",
            str(len(placed)) + " window(s) were assumed 1.2 m wide, sill 0.9 m, head 2.1 m, "
            "one per habitable exterior wall; the plan carried none",
            placed,
        )


# ---------------------------------------------------------------------------
# step 6: storey repetition and assembly
# ---------------------------------------------------------------------------


def _storey_name(index: int) -> str:
    return "Ground" if index == 0 else "Floor " + str(index)


def _instantiate(
    model: StructuralModel,
    records: Sequence[_RoomRec],
    segments: Sequence[_SegRec],
    storeys: int,
    height_m: float,
    plan_index: int,
) -> Dict[Tuple[Any, ...], List[str]]:
    """Write storeys, rooms and walls; return base-record to element id lists."""
    ids = {}  # type: Dict[Tuple[Any, ...], List[str]]

    for storey in range(storeys):
        model.storeys.append(
            Storey(
                index=storey,
                name=_storey_name(storey),
                bottom_z_m=storey * height_m,
                height_m=height_m,
                kind=StoreyKind.UNITS,
                source_id="floorPlans[" + str(plan_index) + "]",
            )
        )

        room_ids = {}
        for record in records:
            rid = room_id(storey, record.source_id)
            room_ids[record.index] = rid
            ids.setdefault(("room", record.index), []).append(rid)
            model.rooms.append(
                RoomPoly(
                    id=rid,
                    storey=storey,
                    name=record.name,
                    occupancy=record.occupancy,
                    polygon=rect_polygon(record.rect()),
                    area_m2=record.w_m * record.h_m,
                    unit_id=None,
                    interior_unknown=False,
                    source=record.source_id,
                )
            )

        for index, segment in enumerate(segments):
            wid = wall_id(storey, segment.orient, segment.pos_m, segment.s0_m)
            ids.setdefault(("wall", index), []).append(wid)
            a, b = segment.points()
            openings = []
            ordered = sorted(
                range(len(segment.openings)),
                key=lambda i: (segment.openings[i].offset_m, segment.openings[i].kind.value),
            )
            for slot, op_index in enumerate(ordered):
                record = segment.openings[op_index]
                oid = opening_id(wid, slot)
                ids.setdefault(("opening", index, op_index), []).append(oid)
                openings.append(
                    Opening(
                        id=oid,
                        kind=record.kind,
                        offset_m=record.offset_m,
                        width_m=record.width_m,
                        sill_m=record.sill_m,
                        head_m=record.head_m,
                        provenance=record.provenance,
                    )
                )
            model.walls.append(
                WallLine(
                    id=wid,
                    storey=storey,
                    a=a,
                    b=b,
                    thickness_m=segment.thickness_m,
                    role=segment.role,
                    material=Material.BRICK_MASONRY,
                    bearing=None,
                    openings=openings,
                    room_ids=(
                        room_ids.get(segment.left) if segment.left is not None else None,
                        room_ids.get(segment.right) if segment.right is not None else None,
                    ),
                    source="edge:"
                    + (records[segment.left].source_id if segment.left is not None else "outside")
                    + "|"
                    + (records[segment.right].source_id if segment.right is not None else "outside"),
                )
            )

    return ids


def _emit_disclosures(
    model: StructuralModel, pending: _Pending, ids: Dict[Tuple[Any, ...], List[str]]
) -> None:
    """One ladder entry per code, element ids expanded across every storey."""
    for code in pending.codes():
        element_ids = sorted(
            {eid for ref in pending.refs.get(code, ()) for eid in ids.get(ref, ())}
        )
        add_disclosure(
            model,
            code,
            " ".join(pending.messages[code]),
            element_ids,
            stage="adapters.plan_json",
        )


# ---------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------


def from_plan(
    plan,
    *,
    storeys=1,
    occupancy_map=None,
    doors=None,
    windows=None,
    adjacency_edges=None,
    adjacency_shortfalls=None,
    plot=None,
    storey_height_ft=10.0,
    exterior_wall_ft=0.75,
    interior_wall_ft=0.4,
    system_hint="rc_frame",
    plan_index=0,
    assume_windows=False
):
    """One engine floor plan to a StructuralModel repeated over `storeys` storeys.

    `plan` accepts a bare room list, `{floorPlans:[[Room...]]}`, `{Documents:{...}}`
    or the full `{response:{Documents:{...}}}` envelope; `plan_index` selects from
    floorPlans. When the envelope is present, `ptpg_graph` and
    `adjacency_shortfalls` are read from it; the matching keyword arguments
    override what the envelope says.

    Geometry is feet on the way in and SI metres from here on. Doors are assumed
    when the plan carries none; windows only when `assume_windows` is set, which
    the orchestrator does for masonry systems so the opening checks have data.
    """
    if int(storeys) < 1:
        raise AdapterError(
            "E_UNSUPPORTED_STOREYS", "storeys must be at least 1, got " + str(storeys)
        )
    storeys = int(storeys)

    try:
        system = System(system_hint) if not isinstance(system_hint, System) else system_hint
    except ValueError:
        raise AdapterError(
            "E_BAD_ENVELOPE", "system_hint is not a known system: " + repr(system_hint)
        )

    rooms, documents = _unwrap(plan, plan_index)
    records = _room_records(rooms)
    pending = _Pending()
    bbox = _check_gapless(records, pending)
    _apply_occupancy(records, occupancy_map, pending)

    segments = _extract_segments(
        records, ft_to_m(float(exterior_wall_ft)), ft_to_m(float(interior_wall_ft))
    )

    plan_count = len(documents.get("floorPlans") or [None])
    if adjacency_edges is not None:
        raw_edges = adjacency_edges
    else:
        raw_edges = _per_plan(documents.get("ptpg_graph"), plan_index, plan_count)
    if adjacency_shortfalls is not None:
        raw_shortfalls = adjacency_shortfalls
    else:
        raw_shortfalls = _per_plan(
            documents.get("adjacency_shortfalls"), plan_index, plan_count
        )
    edges = _pairs_from(raw_edges, records)
    shortfalls = _pairs_from(raw_shortfalls, records)

    doors_given = list(doors or ())
    windows_given = list(windows or ())
    _map_dressed(segments, doors_given, OpeningKind.DOOR, DOOR_WIDTH_M, pending)
    _map_dressed(segments, windows_given, OpeningKind.WINDOW, WINDOW_WIDTH_M, pending)

    # Priority: a dressed plan is believed; synthesis only fills a silent plan.
    if not doors_given:
        _synthesize_doors(segments, records, edges, shortfalls, pending)
    if not windows_given:
        if assume_windows:
            _assume_windows(segments, records, pending)
        else:
            pending.add(
                "N_WINDOWS_NOT_ASSUMED",
                "no windows were assumed, so window lintels are omitted; "
                "set assume_windows to give the opening checks data",
                [],
            )

    options = {
        "storeys": storeys,
        "storey_height_ft": float(storey_height_ft),
        "exterior_wall_ft": float(exterior_wall_ft),
        "interior_wall_ft": float(interior_wall_ft),
        "system_hint": system.value,
        "plan_index": int(plan_index),
        "assume_windows": bool(assume_windows),
        "occupancy_map_keys": sorted(str(k) for k in (occupancy_map or {})),
        "doors_given": len(doors_given),
        "windows_given": len(windows_given),
        "adjacency_edges_given": adjacency_edges is not None,
        "adjacency_shortfalls_given": adjacency_shortfalls is not None,
    }

    model = StructuralModel(
        id="plan-" + str(int(plan_index)),
        source=ModelSource.PLAN_JSON,
        system=system,
        fingerprint=fingerprint(
            {
                "source": "plan_json",
                "rooms": [
                    [
                        r.source_id,
                        r.name,
                        round(m_to_ft(r.x_m), 4),
                        round(m_to_ft(r.y_m), 4),
                        round(m_to_ft(r.w_m), 4),
                        round(m_to_ft(r.h_m), 4),
                    ]
                    for r in records
                ],
                "edges": [list(pair) for pair in edges],
                "shortfalls": [list(pair) for pair in shortfalls],
                "doors": doors_given,
                "windows": windows_given,
                "options": options,
            }
        ),
        meta={
            "north": "-y",
            "adapter": "plan_json",
            "plan_index": int(plan_index),
            "options": options,
            "bbox_ft": [round(m_to_ft(v), 4) for v in bbox],
            "roof_storey_index": storeys - 1,
            "source_room_ids": [r.source_id for r in records],
            "occupancy": {r.source_id: r.occupancy.value for r in records},
        },
    )
    # Copied, not referenced: the model must not change under a caller who
    # keeps editing the payload it handed in.
    if plot is not None:
        model.meta["plot"] = copy.deepcopy(plot)
    plot_fit = _per_plan(documents.get("plot_fit"), plan_index, plan_count)
    if plot_fit is not None:
        model.meta["plot_fit"] = copy.deepcopy(plot_fit)

    ids = _instantiate(
        model, records, segments, storeys, ft_to_m(float(storey_height_ft)), int(plan_index)
    )
    _emit_disclosures(model, pending, ids)
    return model
