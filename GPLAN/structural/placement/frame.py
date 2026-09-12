"""RC frame placement: columns, beams, slab panels, cores, metrics and score.

`run_frame_placement(model, params) -> FrameResult` is the pipeline (spec 02
section 5): extract_axes -> plan_cores -> place_columns -> vertical continuity
with slide repair -> beam framing and slab panelization inside the thickness
feedback loop (max 3 iterations) -> plinth and tie levels -> score_layout.

Contracts honoured (critic findings are NORMATIVE):
  - finding 1: the model is SI metres; this module quantizes to integer
    millimetres PRIVATELY for byte-reproducible arithmetic and re-emits metres.
    Only names suffixed `_mm` carry millimetres.
  - finding 8: every disclosure uses a code registered in model.REGISTRY
    (`W_COLUMN_IN_DOOR`, `W_SLID`, `E_TRANSFER_REQUIRED`, ...).
  - finding 9: corridor/balcony rects, door knowledge and opening spans come
    from the model's derived helpers, never re-derived here.
  - finding 11: Beam.kind is model.BeamKind; bands are not beams.
  - finding 13: element ids come from model helpers (stack_id / column_id /
    beam_id / slab_id), never from insertion order.
  - finding 18: NO footings are placed here.
  - finding 19: `insert_secondary_beams` is the bounded re-place entry
    run_design may call exactly once.
  - finding 33: the metrics block is canonical and carries `score_version`.
  - finding 40: shaft walls and stair flights ship as records;
    `place_lintels_for_infill` creates model.Lintel entries over openings in
    masonry infill walls (span + 2 x 150 mm bearing).

Level convention: beams and panels at level L belong to the slab OVER storey L
(storey 0 = ground); level "P" is the plinth and "T0" a tie level inside the
ground storey. Level-L beams follow the walls of storey L (the frontend's one
grid per building convention): the wall is the infill under the beam and the
beam carries the slab over it.

Cantilevers: balcony rooms mark their panels `cantilever`; true overhangs
(footprint area of storey s outside storey s-1) are framed as cantilever beams
off the backing line with a tip spandrel, on the 2.0 / 2.5 m ladder. Columns
whose stack cannot reach the ground are dropped when the overhang is within
the refusal span (the cantilever framing carries that area) and flagged
`E_TRANSFER_REQUIRED` when it is not; transfers are never auto-placed.

Determinism: every greedy pass states a total order, candidate scores are
exact `fractions.Fraction`, all geometry is integer millimetres internally and
`to_dict()` is stable under `json.dumps(..., sort_keys=True)`.

Engineering refinements over the spec letter (each disclosed where it acts):
corner and core anchors are position-pinned (snapping a plot corner onto a
nearby junction would abandon exact plot fill); the merge span-guard also
demands both resulting sub-gaps clear the 1.2 m floor, and a floor-rejected
subdivision station may slide along its own axis instead of dying; a line the
floor keeps column-free (a boundary 0.6 m off the unit walls, a corridor edge
0.3 m off the outline) is framed by segmented duty beams picked up by short
link stubs cantilevered from the parallel columns; and the W_TERTIARY repair
ladder is extend-to-a-stronger-line, then a link stub, then column promotion,
before E_FRAMING_DEPTH stands. Without these, the plain multi-unit building
fixture dead-ends in hard errors the catalogue never intended for it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..grid import (
    Axis,
    AxisGrid,
    DEFAULT_WALL_T_M,
    FrameParams,
    HARD_MAX_SPAN_M,
    _Footprint,
    _merge_intervals,
    _round_ratio,
    _subtract_intervals,
    extract_axes,
)
from ..model import (
    AxisDir,
    Beam,
    BeamKind,
    Column,
    CoreKind,
    DisclosureLog,
    Lintel,
    Material,
    Occupancy,
    RC_SLAB_MIN_THICKNESS_MM,
    SlabKind,
    SlabPanel,
    StructuralModel,
    WallRole,
    beam_id,
    column_id,
    lintel_id,
    opening_assumed,
    opening_span,
    pos_token,
    slab_id,
    stack_id,
    wall_axis,
)
from .cores import CoreBeam, CorePlan, ShaftWall, StairSlab, frame_core_openings, plan_cores
from .housing_variants import near_wall as _housing_near_wall
from ..design_reuse import EngineeringCache, _exact

SCORE_VERSION = "frame-1"
ECONOMY_SCORE_VERSION = "frame-economy-1"
_HOUSING_SEARCH_CACHE = EngineeringCache(limit=6)

# Catalogue constants (not user parameters).
REFUSE_CANTILEVER_M = 2.5
MIN_BEARING_WALL_T_MM = 115
MIN_BEARING_WALL_LEN_MM = 1500
MID_WALL_DOOR_RUN_MM = 3600
SLIDE_STEP_MM = 50
SLIDE_MAX_MM = 1000
MERGE_FLOOR_MM = 1200
#: Catalogue R6 upper band: a column whose two line neighbours both sit closer
#: than this merges away when the span they leave is under the cap.
SHORT_PAIR_MM = 2000
PANEL_SHORT_TRIGGER_MM = 4500
FEEDBACK_ITERATIONS = 3
SUPPORT_DEDUCT_MM = 230  # centreline span to clear span, one support width
_ON_LINE_TOL_MM = 100
_AXIS_MATCH_TOL_MM = 5
_ECC_SEARCH_MM = 300

_STAGE_COLS = "placement.columns"
_STAGE_CONT = "placement.continuity"
_STAGE_BEAMS = "placement.beams"
_STAGE_SLABS = "placement.slabs"
_STAGE_SCORE = "placement.score"

_HARD_CODES = (
    "E_TRANSFER_REQUIRED",
    "E_CANTILEVER_SPAN",
    "E_FRAMING_DEPTH",
    "E_GRID_COARSE",
    "E_SPAN_OVER_MAX",
    "E_MERGE_FLOOR",
)

# Column thumb ladder by storeys carried (spec 5.3); 8+ takes (300, 600).
_COLUMN_LADDER = {
    1: (230, 230),
    2: (230, 300),
    3: (300, 300),
    4: (300, 380),
    5: (300, 450),
    6: (380, 450),
    7: (380, 450),
}


# ---------------------------------------------------------------------------
# small integer helpers
# ---------------------------------------------------------------------------


def _mm(value_m: float) -> int:
    return int(round(float(value_m) * 1000.0))


def _m(value_mm: int) -> float:
    return int(value_mm) / 1000.0


def _ceil25(value: int) -> int:
    return -(-int(value) // 25) * 25


def _ceil5(value: int) -> int:
    return -(-int(value) // 5) * 5


def _slide_ladder(step_mm: int, max_mm: int) -> List[int]:
    """Displacements ordered by (|d|, d): -step, +step, -2*step, ..."""
    out = []  # type: List[int]
    d = step_mm
    while d <= max_mm:
        out.append(-d)
        out.append(d)
        d += step_mm
    return out


def _overlap(lo1: int, hi1: int, lo2: int, hi2: int) -> int:
    return max(0, min(hi1, hi2) - max(lo1, lo2))


def _rects_subtract(
    a_rects: Sequence[Tuple[int, int, int, int]],
    b_rects: Sequence[Tuple[int, int, int, int]],
) -> List[Tuple[int, int, int, int]]:
    """Region a minus region b, as sorted disjoint rects (guillotine cuts)."""
    pieces = []  # type: List[Tuple[int, int, int, int]]
    for x0, y0, x1, y1 in a_rects:
        cells = [(x0, y0, x1, y1)]
        for bx0, by0, bx1, by1 in b_rects:
            nxt = []  # type: List[Tuple[int, int, int, int]]
            for cx0, cy0, cx1, cy1 in cells:
                if bx1 <= cx0 or bx0 >= cx1 or by1 <= cy0 or by0 >= cy1:
                    nxt.append((cx0, cy0, cx1, cy1))
                    continue
                ix0, ix1 = max(cx0, bx0), min(cx1, bx1)
                iy0, iy1 = max(cy0, by0), min(cy1, by1)
                if cy0 < iy0:
                    nxt.append((cx0, cy0, cx1, iy0))
                if iy1 < cy1:
                    nxt.append((cx0, iy1, cx1, cy1))
                if cx0 < ix0:
                    nxt.append((cx0, iy0, ix0, iy1))
                if ix1 < cx1:
                    nxt.append((ix1, iy0, cx1, iy1))
            cells = nxt
        pieces.extend(c for c in cells if c[2] > c[0] and c[3] > c[1])
    return sorted(pieces)


# ---------------------------------------------------------------------------
# sparse candidate-grid regularization
# ---------------------------------------------------------------------------


def _economy_axis_path(
    axes: Sequence[Axis], cap_mm: int, min_span_mm: int
) -> List[Axis]:
    """Smallest feasible end-to-end axis path, then the best balanced one.

    ``extract_axes`` intentionally keeps every architectural candidate.  That
    is useful provenance but it is not a column-placement obligation.  This
    bounded dynamic program first fixes the minimum number of bays needed by
    the span cap, then chooses candidates that avoid short bays, balance the
    bay lengths, and finally prefer a real architectural line over an inserted
    line.  It is deterministic and exhaustive over the (normally tiny) axis
    candidate set; no stochastic "optimizer" claim is made.
    """
    ordered = sorted(axes, key=lambda one: (one.pos_mm, one.id))
    if len(ordered) <= 2:
        return list(ordered)
    extent = ordered[-1].pos_mm - ordered[0].pos_mm
    if extent <= 0 or cap_mm <= 0:
        return [ordered[0], ordered[-1]]

    minimum_segments = max(1, -(-extent // cap_mm))
    source_cost = {
        "outline": 0,
        "party": 1,
        "core": 1,
        "corridor": 2,
        "wall": 3,
        "inserted": 4,
    }

    for segments in range(minimum_segments, len(ordered)):
        target = _round_ratio(extent, segments)
        # (edges used, terminal axis index) -> (cost tuple, path indices)
        states = {(0, 0): ((0, 0, 0, 0), (0,))}
        for used in range(1, segments + 1):
            for i in range(1, len(ordered)):
                remaining = segments - used
                if len(ordered) - 1 - i < remaining:
                    continue
                if remaining == 0 and i != len(ordered) - 1:
                    continue
                if remaining > 0 and i == len(ordered) - 1:
                    continue
                best = None
                for j in range(0, i):
                    previous = states.get((used - 1, j))
                    if previous is None:
                        continue
                    gap = ordered[i].pos_mm - ordered[j].pos_mm
                    if gap <= 0 or gap > cap_mm:
                        continue
                    old_cost, old_path = previous
                    short = max(0, min_span_mm - gap)
                    added = (
                        1 if short else 0,
                        short,
                        (gap - target) * (gap - target),
                        0 if i == len(ordered) - 1 else source_cost.get(ordered[i].source.value, 5),
                    )
                    cost = tuple(old_cost[k] + added[k] for k in range(4))
                    path = old_path + (i,)
                    candidate = (cost, tuple(ordered[p].pos_mm for p in path), path)
                    if best is None or candidate < best:
                        best = candidate
                if best is not None:
                    states[(used, i)] = (best[0], best[2])
        final = states.get((segments, len(ordered) - 1))
        if final is not None:
            return [ordered[i] for i in final[1]]
    # Adjacent axes are already span-controlled by grid.extract_axes, so this
    # fallback is feasible even for an irregular footprint.
    return list(ordered)


def _economy_grid(grid: AxisGrid, params: FrameParams) -> AxisGrid:
    """Return the sparse admissible subset used by ``economy_grid`` placement."""
    cap_mm = _mm(min(float(params.max_primary_span), HARD_MAX_SPAN_M))
    min_span_mm = _mm(float(params.min_span))
    x_axes = _economy_axis_path(grid.x_axes, cap_mm, min_span_mm)
    y_axes = _economy_axis_path(grid.y_axes, cap_mm, min_span_mm)
    x_ids = {axis.id for axis in x_axes}
    y_ids = {axis.id for axis in y_axes}
    x_pos = {axis.pos_mm for axis in x_axes}
    y_pos = {axis.pos_mm for axis in y_axes}

    # Axis-specific warnings from discarded candidates must not survive as if
    # they described the selected grid.
    kept_log = DisclosureLog()
    for entry in grid.log.entries:
        if entry.code in ("W_SHORT_SPAN", "N_GRID_AXIS_OFFSET"):
            ids = set(entry.element_ids)
            if ids and not ids.issubset(x_ids | y_ids):
                continue
        kept_log.append(entry)

    for axes in (x_axes, y_axes):
        for low, high in zip(axes, axes[1:]):
            gap = high.pos_mm - low.pos_mm
            if gap < min_span_mm and not (set(low.corridor_keys) & set(high.corridor_keys)):
                kept_log.add(
                    "W_SHORT_SPAN",
                    "selected economy axes %s and %s are %d mm apart, below min_span %d mm"
                    % (low.id, high.id, gap, min_span_mm),
                    [low.id, high.id],
                    stage="placement.economy_grid",
                )

    kept_log.add(
        "N_ECONOMY_GRID",
        "economy_grid_v0 regularized %d x %d architectural candidate axes to %d x %d selected axes; "
        "all selected bay gaps are bounded by %d mm; this is one deterministic candidate, not a cost optimum, "
        "and final eligibility follows the full design/foundation/quantity pass"
        % (len(grid.x_axes), len(grid.y_axes), len(x_axes), len(y_axes), cap_mm),
        sorted(x_ids | y_ids),
        stage="placement.economy_grid",
    )
    junctions = {
        storey: [
            junction
            for junction in grid.junctions.get(storey, [])
            if junction.x_mm in x_pos and junction.y_mm in y_pos
        ]
        for storey in grid.storeys
    }
    return AxisGrid(
        x_axes=list(x_axes),
        y_axes=list(y_axes),
        junctions=junctions,
        params=params,
        log=kept_log,
        storeys=list(grid.storeys),
        footprints=dict(grid.footprints),
    )


# ---------------------------------------------------------------------------
# prepared model views (walls, doors, corridors) in integer mm
# ---------------------------------------------------------------------------


@dataclass
class _WallRec:
    id: str
    storey: int
    orient: str  # "h" | "v"
    pos_mm: int
    lo_mm: int
    hi_mm: int
    t_mm: int
    role: str
    material: str
    qualifying: bool  # masonry, t >= 115 mm, length > 1.5 m

    @property
    def length_mm(self) -> int:
        return self.hi_mm - self.lo_mm


@dataclass
class _DoorRec:
    wall: _WallRec
    lo_mm: int  # forbidden interval start (jamb clearance applied)
    hi_mm: int


@dataclass
class _CorridorRec:
    storey: int
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def runs_in_x(self) -> bool:
        return (self.x1 - self.x0) >= (self.y1 - self.y0)

    def long_edges(self) -> Tuple[str, int, int, int, int]:
        """(cross orient of edges, edge pos 1, edge pos 2, along lo, along hi)."""
        if self.runs_in_x:
            return ("h", self.y0, self.y1, self.x0, self.x1)
        return ("v", self.x0, self.x1, self.y0, self.y1)


class _View:
    """Deterministic mm view of the model the placement passes share."""

    def housing_wall_allowed(self, x_mm: int, y_mm: int, storeys: Sequence[int]) -> bool:
        return self.params.housing_column_variant is None or all(
            _housing_near_wall(self.model, s, _m(x_mm), _m(y_mm)) for s in storeys
        )

    def __init__(self, model: StructuralModel, grid: AxisGrid, params: FrameParams):
        self.model = model
        self.grid = grid
        self.params = params
        self.storeys = list(grid.storeys)
        self.default_t_mm = _mm(DEFAULT_WALL_T_M)
        self.walls = {}  # type: Dict[int, List[_WallRec]]
        self.doors = {}  # type: Dict[int, List[_DoorRec]]
        self.midthirds = {}  # type: Dict[int, List[Tuple[_WallRec, int, int]]]
        self.corridors = {}  # type: Dict[int, List[_CorridorRec]]
        self.doors_known = {}  # type: Dict[int, bool]
        jamb_mm = _mm(params.jamb_clearance)
        for storey in self.storeys:
            recs = []  # type: List[_WallRec]
            doors = []  # type: List[_DoorRec]
            mids = []  # type: List[Tuple[_WallRec, int, int]]
            known = model.doors_known(storey)
            self.doors_known[storey] = known
            for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
                if wall.role == WallRole.RAILING:
                    continue
                axis = wall_axis(wall)
                if axis is None:
                    continue
                orient, pos_m, s0_m, s1_m = axis
                t_mm = max(1, _mm(wall.thickness_m))
                rec = _WallRec(
                    id=wall.id,
                    storey=storey,
                    orient=orient,
                    pos_mm=_mm(pos_m),
                    lo_mm=_mm(s0_m),
                    hi_mm=_mm(s1_m),
                    t_mm=t_mm,
                    role=wall.role.value,
                    material=wall.material.value if hasattr(wall.material, "value") else str(wall.material),
                    qualifying=(
                        (wall.material == Material.BRICK_MASONRY or getattr(wall.material, "value", None) == Material.BRICK_MASONRY.value)
                        and _mm(wall.thickness_m) >= MIN_BEARING_WALL_T_MM
                        and (_mm(s1_m) - _mm(s0_m)) > MIN_BEARING_WALL_LEN_MM
                    ),
                )
                recs.append(rec)
                if known:
                    for opening in wall.openings:
                        if opening.kind.value not in ("door", "entry"):
                            continue
                        if opening_assumed(opening):
                            continue
                        s0, s1 = opening_span(wall, opening)
                        doors.append(
                            _DoorRec(
                                wall=rec,
                                lo_mm=rec.lo_mm + _mm(s0) - jamb_mm,
                                hi_mm=rec.lo_mm + _mm(s1) + jamb_mm,
                            )
                        )
                elif rec.role == WallRole.INTERIOR.value and rec.length_mm < MID_WALL_DOOR_RUN_MM:
                    third = rec.length_mm // 3
                    mids.append((rec, rec.lo_mm + third, rec.hi_mm - third))
            self.walls[storey] = recs
            self.doors[storey] = doors
            self.midthirds[storey] = mids
            rects = []  # type: List[_CorridorRec]
            for rx, ry, rw, rh in model.corridor_rects(storey):
                rects.append(
                    _CorridorRec(
                        storey=storey,
                        x0=_mm(rx),
                        y0=_mm(ry),
                        x1=_mm(rx + rw),
                        y1=_mm(ry + rh),
                    )
                )
            self.corridors[storey] = rects
        self.balconies = {}  # type: Dict[int, List[Tuple[int, int, int, int]]]
        for storey in self.storeys:
            self.balconies[storey] = [
                (_mm(rx), _mm(ry), _mm(rx + rw), _mm(ry + rh))
                for rx, ry, rw, rh in model.balcony_rects(storey)
            ]

    def covers(self, storey: int, x_mm: int, y_mm: int) -> bool:
        footprint = self.grid.footprints.get(storey)
        return footprint is not None and footprint.covers(x_mm, y_mm)

    def walls_through(self, storey: int, x_mm: int, y_mm: int) -> List[_WallRec]:
        """Walls whose centreline passes through the point (within t/2)."""
        found = []  # type: List[_WallRec]
        for rec in self.walls.get(storey, []):
            tol = max(rec.t_mm, self.default_t_mm) // 2
            if rec.orient == "h":
                if abs(y_mm - rec.pos_mm) <= tol and rec.lo_mm - tol <= x_mm <= rec.hi_mm + tol:
                    found.append(rec)
            else:
                if abs(x_mm - rec.pos_mm) <= tol and rec.lo_mm - tol <= y_mm <= rec.hi_mm + tol:
                    found.append(rec)
        return found

    def door_conflicts(self, x_mm: int, y_mm: int, storeys: Sequence[int]) -> List[_DoorRec]:
        """Dressed door intervals the point lands in, over the given storeys."""
        hits = []  # type: List[_DoorRec]
        for storey in storeys:
            for door in self.doors.get(storey, []):
                rec = door.wall
                tol = max(rec.t_mm, self.default_t_mm) // 2
                # open interval: standing exactly at jamb + clearance is allowed
                if rec.orient == "h":
                    if abs(y_mm - rec.pos_mm) <= tol and door.lo_mm < x_mm < door.hi_mm:
                        hits.append(door)
                else:
                    if abs(x_mm - rec.pos_mm) <= tol and door.lo_mm < y_mm < door.hi_mm:
                        hits.append(door)
        return hits

    def corridor_strictly_inside(self, x_mm: int, y_mm: int, storeys: Sequence[int], slack_mm: int) -> Optional[_CorridorRec]:
        """The corridor whose interior holds the point beyond `slack` of both long edges."""
        for storey in storeys:
            for rect in self.corridors.get(storey, []):
                if not (rect.x0 < x_mm < rect.x1 and rect.y0 < y_mm < rect.y1):
                    continue
                orient, p1, p2, lo, hi = rect.long_edges()
                cross = y_mm if orient == "h" else x_mm
                if abs(cross - p1) > slack_mm and abs(cross - p2) > slack_mm:
                    return rect
        return None


# ---------------------------------------------------------------------------
# column stacks
# ---------------------------------------------------------------------------


@dataclass
class _Cand:
    x_mm: int
    y_mm: int
    anchor: int = 0
    origin: str = "grid"
    no_snap: bool = False
    slide_axis: str = ""  # "x"|"y": coordinate a floor-rejected station may move


@dataclass
class _Stack:
    x_mm: int
    y_mm: int
    anchor: int
    origin: str
    exists: List[int]
    top: int
    base: int
    score: Fraction
    w_dir: Optional[str] = None  # orientation of the dominant supporting wall
    support: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    slid_mm: int = 0
    slide_dir: str = ""
    transfer: bool = False
    unsupported: List[int] = field(default_factory=list)
    w_mm: int = 230
    d_mm: int = 230
    sections_by_storey: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    rot: int = 0
    axis_x: Optional[Axis] = None
    axis_y: Optional[Axis] = None
    corridor_pair_keys: List[str] = field(default_factory=list)
    slide_axis: str = ""
    id: str = ""
    placed_by: str = ""
    #: junction class at the station: X 4, T 3, L 2, on a wall run 1, free 0
    jn: int = 0
    #: keys shared by a core corner and the column that ties it to the wall
    #: line past it when that line is closer than the merge floor (R9/R11):
    #: such a pair is waived from the floor the way a corridor edge pair is
    tie_keys: List[str] = field(default_factory=list)

    def chebyshev(self, other: "_Stack") -> int:
        return max(abs(self.x_mm - other.x_mm), abs(self.y_mm - other.y_mm))

    def to_dict(self) -> Dict[str, Any]:
        labels = None
        if self.axis_x is not None and self.axis_y is not None and self.on_grid():
            labels = [self.axis_x.label, self.axis_y.label]
        return {
            "id": self.id,
            "x_m": _m(self.x_mm),
            "y_m": _m(self.y_mm),
            "width_mm": int(self.w_mm),
            "depth_mm": int(self.d_mm),
            "sections_by_storey": [
                {
                    "storey": int(storey),
                    "width_mm": int(section[0]),
                    "depth_mm": int(section[1]),
                }
                for storey, section in sorted(self.sections_by_storey.items())
            ],
            "rot": int(self.rot),
            "base_storey": int(self.base),
            "top_storey": int(self.top),
            "storeys": sorted(self.exists),
            "axis_x": self.axis_x.id if self.axis_x is not None else None,
            "axis_y": self.axis_y.id if self.axis_y is not None else None,
            "on_grid": self.on_grid(),
            "labels": labels,
            "support": list(self.support),
            "notes": sorted(self.notes),
            "placed_by": self.placed_by,
        }

    def section_at(self, storey: int) -> Tuple[int, int]:
        """The monotone thumb section for one physical column lift."""
        return self.sections_by_storey.get(int(storey), (self.w_mm, self.d_mm))

    def on_grid(self) -> bool:
        return (
            self.axis_x is not None
            and self.axis_y is not None
            and abs(self.axis_x.pos_mm - self.x_mm) <= _AXIS_MATCH_TOL_MM
            and abs(self.axis_y.pos_mm - self.y_mm) <= _AXIS_MATCH_TOL_MM
        )


def _existing_storeys(view: _View, x_mm: int, y_mm: int) -> List[int]:
    return [s for s in view.storeys if view.covers(s, x_mm, y_mm)]


def _footprint_corners(grid: AxisGrid) -> List[Tuple[int, int]]:
    corners = set()  # type: Set[Tuple[int, int]]
    for storey in grid.storeys:
        footprint = grid.footprints.get(storey)
        if footprint is None:
            continue
        for pos_mm, lo_mm, hi_mm in footprint.boundary_lines("v"):
            corners.add((pos_mm, lo_mm))
            corners.add((pos_mm, hi_mm))
    return sorted(corners)


def _junctions_near(grid: AxisGrid, storeys: Sequence[int], x_mm: int, y_mm: int, window_mm: int):
    """Junctions within a Chebyshev window, best (J desc, x, y) first."""
    found = []
    for storey in storeys:
        for junction in grid.junctions.get(storey, []):
            if abs(junction.x_mm - x_mm) <= window_mm and abs(junction.y_mm - y_mm) <= window_mm:
                found.append(junction)
    found.sort(key=lambda j: (-j.j, j.x_mm, j.y_mm, j.storey))
    return found


def _axis_at(axes: Sequence[Axis], pos_mm: int, tol_mm: int) -> Optional[Axis]:
    best = None  # type: Optional[Axis]
    for axis in axes:
        d = abs(axis.pos_mm - pos_mm)
        if d <= tol_mm and (best is None or d < abs(best.pos_mm - pos_mm)):
            best = axis
    return best


def _span_balance(positions: Sequence[int], coord_mm: int) -> Fraction:
    """1 - |gapL - gapR| / (gapL + gapR); 1 when a side has no neighbour."""
    prev = None  # type: Optional[int]
    nxt = None  # type: Optional[int]
    for pos in positions:
        if pos < coord_mm - _AXIS_MATCH_TOL_MM:
            prev = pos if prev is None or pos > prev else prev
        elif pos > coord_mm + _AXIS_MATCH_TOL_MM:
            nxt = pos if nxt is None or pos < nxt else nxt
    if prev is None or nxt is None:
        return Fraction(1)
    left = coord_mm - prev
    right = nxt - coord_mm
    if left + right == 0:
        return Fraction(1)
    return Fraction(1) - Fraction(abs(left - right), left + right)


class _ColumnState:
    """Everything the column passes share; mutated deterministically."""

    def __init__(self, view: _View, core_plan: CorePlan, params: FrameParams):
        self.view = view
        self.core_plan = core_plan
        self.params = params
        self.accepted = []  # type: List[_Stack]
        self.short_pairs = []  # type: List[Tuple[_Stack, _Stack]]
        self.midwall_fired = set()  # type: Set[str]
        self.door_dropped = []  # type: List[str]
        self.snap_junction_mm = _mm(params.snap_junction)
        self.snap_wall_mm = _mm(params.snap_wall)
        self.merge_mm = _mm(params.column_merge_floored())
        self.cap_mm = _mm(min(float(params.max_primary_span), HARD_MAX_SPAN_M))
        if self.cap_mm <= 0:
            self.cap_mm = _mm(HARD_MAX_SPAN_M)
        self.min_span_mm = _mm(params.min_span)
        self.tol_wall_mm = view.default_t_mm // 2
        #: station -> (pair key, core corner) for closure columns that tie an
        #: isolated core corner to a wall line closer than the merge floor
        self.tie_points = {}  # type: Dict[Tuple[int, int], Tuple[str, _Stack]]

    # -- candidate processing -------------------------------------------------

    def _snap(self, cand: _Cand) -> Tuple[int, int]:
        if cand.no_snap:
            return (cand.x_mm, cand.y_mm)
        exists = _existing_storeys(self.view, cand.x_mm, cand.y_mm) or self.view.storeys
        near = _junctions_near(self.view.grid, exists, cand.x_mm, cand.y_mm, self.snap_junction_mm)
        if near:
            return (near[0].x_mm, near[0].y_mm)
        x, y = cand.x_mm, cand.y_mm
        best_v = None  # type: Optional[Tuple[int, int, str]]
        best_h = None  # type: Optional[Tuple[int, int, str]]
        for storey in exists:
            for rec in self.view.walls.get(storey, []):
                if rec.orient == "v" and rec.lo_mm <= y <= rec.hi_mm:
                    d = abs(rec.pos_mm - x)
                    if d <= self.snap_wall_mm and (best_v is None or (d, rec.pos_mm, rec.id) < best_v):
                        best_v = (d, rec.pos_mm, rec.id)
                if rec.orient == "h" and rec.lo_mm <= x <= rec.hi_mm:
                    d = abs(rec.pos_mm - y)
                    if d <= self.snap_wall_mm and (best_h is None or (d, rec.pos_mm, rec.id) < best_h):
                        best_h = (d, rec.pos_mm, rec.id)
        if best_v is not None:
            x = best_v[1]
        if best_h is not None:
            y = best_h[1]
        return (x, y)

    def _inside_shaft(self, x_mm: int, y_mm: int) -> bool:
        tol = self.tol_wall_mm
        for rect in self.core_plan.shaft_rects_mm():
            if rect[0] - tol <= x_mm <= rect[2] + tol and rect[1] - tol <= y_mm <= rect[3] + tol:
                return True
        return False

    def on_core_edge(self, x_mm: int, y_mm: int) -> bool:
        """Whether a station lies on the edge of a circulation core.

        A core edge is a loaded wall (flights and landings bear on it), and the
        crossing of another structural line with it is a station in its own
        right: it is how the core ties into the grid when its corners cannot
        (a core closer to the outline than the merge floor gets no column on
        the outline opposite its corners).
        """
        tol = self.tol_wall_mm
        for cid in sorted(self.core_plan.core_rects_mm):
            x0, y0, x1, y1 = self.core_plan.core_rects_mm[cid]
            on_vertical = (abs(x_mm - x0) <= tol or abs(x_mm - x1) <= tol) and y0 - tol <= y_mm <= y1 + tol
            on_horizontal = (abs(y_mm - y0) <= tol or abs(y_mm - y1) <= tol) and x0 - tol <= x_mm <= x1 + tol
            if on_vertical or on_horizontal:
                return True
        return False

    def _inside_core_opening(self, x_mm: int, y_mm: int) -> bool:
        tol = self.tol_wall_mm
        for cid in sorted(self.core_plan.core_rects_mm):
            x0, y0, x1, y1 = self.core_plan.core_rects_mm[cid]
            if x0 + tol < x_mm < x1 - tol and y0 + tol < y_mm < y1 - tol:
                return True
        return False

    def _door_slide(self, cand: _Cand, x_mm: int, y_mm: int, exists: Sequence[int]) -> Optional[Tuple[int, int]]:
        """Slide off a dressed door along the door's wall; None drops the candidate."""
        hits = self.view.door_conflicts(x_mm, y_mm, exists)
        if not hits:
            return (x_mm, y_mm)
        wall = hits[0].wall
        horizontal = wall.orient == "h"  # slide along x
        origin = x_mm if horizontal else y_mm
        for d in _slide_ladder(SLIDE_STEP_MM, SLIDE_MAX_MM):
            nx = x_mm + d if horizontal else x_mm
            ny = y_mm if horizontal else y_mm + d
            if self.view.door_conflicts(nx, ny, exists):
                continue
            if not all(self.view.covers(s, nx, ny) for s in exists):
                continue
            axes = self.view.grid.x_axes if horizontal else self.view.grid.y_axes
            coord = nx if horizontal else ny
            spans_ok = True
            # the candidate's own line moves with it, so its origin axis is
            # not a neighbour once it has slid off that station
            positions = [a.pos_mm for a in axes if abs(a.pos_mm - origin) > _AXIS_MATCH_TOL_MM]
            prev = max((p for p in positions if p < coord - _AXIS_MATCH_TOL_MM), default=None)
            nxt = min((p for p in positions if p > coord + _AXIS_MATCH_TOL_MM), default=None)
            for gap in ((coord - prev) if prev is not None else None, (nxt - coord) if nxt is not None else None):
                if gap is not None and not (self.min_span_mm <= gap <= self.cap_mm):
                    spans_ok = False
            if spans_ok:
                return (nx, ny)
        self.door_dropped.append(wall.id)
        return None

    def _score(self, cand: _Cand, x_mm: int, y_mm: int, exists: Sequence[int]) -> Tuple[Fraction, Optional[str], List[str], int]:
        view = self.view
        grid = view.grid
        # Jn: max junction class over storeys; on a wall run without a junction: 1
        jn = 0
        for junction in _junctions_near(grid, exists, x_mm, y_mm, self.tol_wall_mm):
            jn = max(jn, min(4, junction.j))
        wall_hits = 0
        w_dir = None  # type: Optional[str]
        best_len = -1
        support = []  # type: List[str]
        for storey in exists:
            through = view.walls_through(storey, x_mm, y_mm)
            if through:
                wall_hits += 1
                support.append("s%d:wall" % storey)
                for rec in through:
                    if rec.length_mm > best_len:
                        best_len = rec.length_mm
                        w_dir = rec.orient
            else:
                support.append("s%d:frame" % storey)
        if jn == 0 and wall_hits:
            jn = 1
        top = max(exists)
        cont = Fraction(len([s for s in exists if s <= top]), top + 1)
        w_frac = Fraction(wall_hits, len(exists)) if exists else Fraction(0)
        bal_x = _span_balance([a.pos_mm for a in grid.x_axes], x_mm)
        bal_y = _span_balance([a.pos_mm for a in grid.y_axes], y_mm)
        balance = (bal_x + bal_y) / 2
        penalty = 0
        if not all(view.doors_known.get(s, False) for s in exists):
            for storey in exists:
                if view.doors_known.get(storey, False):
                    continue
                for rec, mid_lo, mid_hi in view.midthirds.get(storey, []):
                    tol = max(rec.t_mm, view.default_t_mm) // 2
                    along = x_mm if rec.orient == "h" else y_mm
                    cross = y_mm if rec.orient == "h" else x_mm
                    if abs(cross - rec.pos_mm) <= tol and mid_lo <= along <= mid_hi:
                        penalty = 4
                        self.midwall_fired.add(rec.id)
        score = Fraction(10) * jn + Fraction(6) * w_frac + Fraction(8) * cont + Fraction(3) * balance + cand.anchor - penalty
        return (score, w_dir, support, jn)

    def process(self, cands: Sequence[_Cand]) -> List[_Stack]:
        """Snap, reject, slide and score one candidate batch (spec B1)."""
        queue = sorted(cands, key=lambda c: (c.x_mm, c.y_mm, -c.anchor, c.origin))
        prepared = {}  # type: Dict[Tuple[int, int], Tuple[_Cand, List[int]]]
        extra = []  # type: List[_Cand]
        for cand in queue:
            x, y = self._snap(cand)
            exists = _existing_storeys(self.view, x, y)
            if not exists:
                continue  # outside every footprint
            if self._inside_shaft(x, y) or self._inside_core_opening(x, y):
                continue
            rect = self.view.corridor_strictly_inside(x, y, exists, self.snap_wall_mm)
            if rect is not None:
                orient, p1, p2, lo, hi = rect.long_edges()
                for edge_pos in (p1, p2):
                    if orient == "h":
                        extra.append(_Cand(x, edge_pos, cand.anchor, "corridor_proj", no_snap=True))
                    else:
                        extra.append(_Cand(edge_pos, y, cand.anchor, "corridor_proj", no_snap=True))
                continue
            # snap onto a near corridor edge
            for storey in exists:
                for crect in self.view.corridors.get(storey, []):
                    if not (crect.x0 < x < crect.x1 and crect.y0 < y < crect.y1):
                        continue
                    orient, p1, p2, lo, hi = crect.long_edges()
                    cross = y if orient == "h" else x
                    target = p1 if abs(cross - p1) <= abs(cross - p2) else p2
                    if abs(cross - target) <= self.snap_wall_mm:
                        if orient == "h":
                            y = target
                        else:
                            x = target
            slid = self._door_slide(cand, x, y, exists)
            if slid is None:
                continue
            x, y = slid
            exists = _existing_storeys(self.view, x, y)
            if not exists:
                continue
            if not self.view.housing_wall_allowed(x, y, exists):
                continue
            key = (x, y)
            moved = _Cand(x, y, cand.anchor, cand.origin, slide_axis=cand.slide_axis)
            if key in prepared:
                old, _ = prepared[key]
                if cand.anchor > old.anchor:
                    prepared[key] = (moved, exists)
            else:
                prepared[key] = (moved, exists)
        scored = []  # type: List[_Stack]
        if extra:
            scored.extend(self.process(extra))
        for key in sorted(prepared):
            cand, exists = prepared[key]
            score, w_dir, support, jn = self._score(cand, cand.x_mm, cand.y_mm, exists)
            top = max(exists)
            scored.append(
                _Stack(
                    x_mm=cand.x_mm,
                    y_mm=cand.y_mm,
                    anchor=cand.anchor,
                    origin=cand.origin,
                    exists=exists,
                    top=top,
                    base=min(exists),
                    score=score,
                    w_dir=w_dir,
                    support=support,
                    slide_axis=cand.slide_axis,
                    placed_by="placement.frame." + cand.origin,
                    jn=jn,
                )
            )
        return scored

    # -- merge ---------------------------------------------------------------

    def _guard_subgaps(self, cand: _Stack) -> Optional[Tuple[int, int]]:
        """(left, right) sub-gaps where rejecting `cand` leaves a span over the cap.

        None when no line through the candidate has an over-cap gap that the
        candidate would split. When both directions qualify, the one whose
        smaller sub-gap is larger wins (the more useful split).
        """
        best = None  # type: Optional[Tuple[int, int]]
        for horizontal in (False, True):
            if horizontal:
                mates = [a for a in self.accepted if abs(a.y_mm - cand.y_mm) <= _ON_LINE_TOL_MM]
                coords = sorted(a.x_mm for a in mates)
                coord = cand.x_mm
            else:
                mates = [a for a in self.accepted if abs(a.x_mm - cand.x_mm) <= _ON_LINE_TOL_MM]
                coords = sorted(a.y_mm for a in mates)
                coord = cand.y_mm
            prev = max((p for p in coords if p < coord), default=None)
            nxt = min((p for p in coords if p > coord), default=None)
            if prev is not None and nxt is not None and (nxt - prev) > self.cap_mm:
                gaps = (coord - prev, nxt - coord)
                if best is None or min(gaps) > min(best):
                    best = gaps
        return best

    def _corridor_pair(self, a: _Stack, b: _Stack) -> bool:
        for storey in self.view.storeys:
            for rect in self.view.corridors.get(storey, []):
                orient, p1, p2, lo, hi = rect.long_edges()
                tol = self.tol_wall_mm
                if orient == "h":
                    cross_a, cross_b = a.y_mm, b.y_mm
                    along_a, along_b = a.x_mm, b.x_mm
                else:
                    cross_a, cross_b = a.x_mm, b.x_mm
                    along_a, along_b = a.y_mm, b.y_mm
                on_edges = (abs(cross_a - p1) <= tol and abs(cross_b - p2) <= tol) or (
                    abs(cross_a - p2) <= tol and abs(cross_b - p1) <= tol
                )
                if on_edges and lo - tol <= along_a <= hi + tol and lo - tol <= along_b <= hi + tol:
                    return True
        return False

    def _waived_pair(self, a: _Stack, b: _Stack) -> bool:
        """A pair the merge floor does not apply to: both corridor edges, or a
        core corner and the column tying it to the wall line past it."""
        if self._corridor_pair(a, b):
            return True
        return bool(set(a.tie_keys) & set(b.tie_keys))

    def merge(self, scored: Sequence[_Stack]) -> None:
        """Greedy accept by (-S, x, y); a conflicting candidate survives only when

        it fixes an over-cap span (the span-guard exception), never closer than
        the 1.2 m catalogue floor to what already stands, and never splitting a
        span into pieces under that floor. Corridor edge pairs and core tie
        pairs are exempt from the floor and the short-span warning.
        """
        for cand in sorted(scored, key=lambda s: (-s.score, s.x_mm, s.y_mm)):
            conflicts = [a for a in self.accepted if cand.chebyshev(a) < self.merge_mm]
            if not conflicts:
                self.accepted.append(cand)
                continue
            nearest = sorted(conflicts, key=lambda a: (cand.chebyshev(a), a.x_mm, a.y_mm))[0]
            cheb_min = cand.chebyshev(nearest)
            if cheb_min < MERGE_FLOOR_MM and not self._waived_pair(nearest, cand):
                # the floor is hard; a subdivision station may slide clear of it
                if cand.slide_axis and self._slide_station(cand):
                    self.accepted.append(cand)
                continue
            if self._waived_pair(nearest, cand):
                self.accepted.append(cand)  # both stand, waived
                continue
            gaps = self._guard_subgaps(cand)
            if gaps is None or min(gaps) < MERGE_FLOOR_MM:
                continue
            self.accepted.append(cand)
            if min(gaps) < self.min_span_mm:
                self.short_pairs.append((nearest, cand))
        self.accepted.sort(key=lambda s: (s.x_mm, s.y_mm))

    def _slide_station(self, cand: _Stack) -> bool:
        """Move a floor-rejected subdivision station along its axis until it
        clears every accepted column by the floor and still splits its gap
        into workable pieces. Returns True when the stack was moved in place."""
        horizontal = cand.slide_axis == "x"
        for d in _slide_ladder(SLIDE_STEP_MM, MERGE_FLOOR_MM + SLIDE_MAX_MM):
            nx = cand.x_mm + d if horizontal else cand.x_mm
            ny = cand.y_mm if horizontal else cand.y_mm + d
            probe = _Stack(
                x_mm=nx, y_mm=ny, anchor=0, origin=cand.origin,
                exists=cand.exists, top=cand.top, base=cand.base, score=cand.score,
            )
            if any(probe.chebyshev(a) < MERGE_FLOOR_MM for a in self.accepted):
                continue
            exists = _existing_storeys(self.view, nx, ny)
            if not exists:
                continue
            if self.view.door_conflicts(nx, ny, exists):
                continue
            if self.view.corridor_strictly_inside(nx, ny, exists, self.snap_wall_mm) is not None:
                continue
            if not self.view.housing_wall_allowed(nx, ny, exists):
                continue
            if horizontal:
                mates = sorted(a.x_mm for a in self.accepted if abs(a.y_mm - ny) <= _ON_LINE_TOL_MM)
                coord = nx
            else:
                mates = sorted(a.y_mm for a in self.accepted if abs(a.x_mm - nx) <= _ON_LINE_TOL_MM)
                coord = ny
            prev = max((p for p in mates if p < coord), default=None)
            nxt = min((p for p in mates if p > coord), default=None)
            gaps = []
            if prev is not None:
                gaps.append(coord - prev)
            if nxt is not None:
                gaps.append(nxt - coord)
            if gaps and (min(gaps) < MERGE_FLOOR_MM or max(gaps) > self.cap_mm):
                continue
            cand.x_mm, cand.y_mm = nx, ny
            cand.exists = exists
            cand.top = max(exists)
            cand.base = min(exists)
            return True
        return False

    def closure_candidates(self) -> List[_Cand]:
        """The extent ends of every axis that already carries a column.

        A beam lands on a column at BOTH ends (catalogue R11), so a line that
        got a column at a junction must also get one where its run ends: the
        outline crossing at the end of a stair-core edge, the far wall at the
        end of a partition. Extents already stop at crossing axes, so an end is
        an existing grid station the junction pass declined; it comes back
        here through the same snap, door and merge rules, and only when a wall
        actually passes there (a chord end on open floor stays empty).
        """
        out = []  # type: List[_Cand]
        seen = set()  # type: Set[Tuple[int, int]]
        for axis in self.view.grid.axes():
            vertical = axis.dir == AxisDir.X
            on_line = [
                a
                for a in self.accepted
                if abs((a.x_mm if vertical else a.y_mm) - axis.pos_mm) <= _ON_LINE_TOL_MM
            ]
            if not on_line:
                continue
            for storey in axis.storeys():
                for lo, hi in axis.extents_mm.get(storey, []):
                    inside = [
                        a
                        for a in on_line
                        if storey in a.exists
                        and lo - _ON_LINE_TOL_MM <= (a.y_mm if vertical else a.x_mm) <= hi + _ON_LINE_TOL_MM
                    ]
                    if not inside:
                        continue
                    for end in (lo, hi):
                        if any(abs((a.y_mm if vertical else a.x_mm) - end) <= _ON_LINE_TOL_MM for a in inside):
                            continue
                        point = (axis.pos_mm, end) if vertical else (end, axis.pos_mm)
                        if point in seen:
                            continue
                        seen.add(point)
                        out.append(_Cand(point[0], point[1], 0, "closure"))
        return sorted(out, key=lambda c: (c.x_mm, c.y_mm))

    # -- post-passes on the accepted set (wall_aligned) -----------------------

    def _line_members(self, vertical: bool, pos_mm: int) -> List[_Stack]:
        return sorted(
            (a for a in self.accepted if abs((a.x_mm if vertical else a.y_mm) - pos_mm) <= _ON_LINE_TOL_MM),
            key=lambda a: (a.y_mm if vertical else a.x_mm),
        )

    def _removal_leaves_overcap(self, cand: _Stack, vertical: bool) -> bool:
        """Whether dropping `cand` opens a span over the cap on the given line."""
        coord = cand.y_mm if vertical else cand.x_mm
        along = [
            (a.y_mm if vertical else a.x_mm)
            for a in self._line_members(vertical, cand.x_mm if vertical else cand.y_mm)
            if a is not cand
        ]
        prev = max((p for p in along if p < coord), default=None)
        nxt = min((p for p in along if p > coord), default=None)
        return prev is not None and nxt is not None and (nxt - prev) > self.cap_mm

    def collapse_short_pairs(self) -> List[_Stack]:
        """Catalogue R6, the upper band: three columns in a row on one line with
        both gaps under SHORT_PAIR_MM lose the middle one when the span that
        leaves is under the cap. The partition that met the line there bears on
        the main beam instead of on a column of its own; a rigid-support
        continuous-beam analysis lifts a support squeezed between two short
        spans, and the foundation pass refuses uplift. Anchors, corridor edge
        pairs and any column whose other line would open past the cap stay.
        """
        dropped = []  # type: List[_Stack]
        progress = True
        while progress:
            progress = False
            for vertical in (True, False):
                positions = sorted({(a.x_mm if vertical else a.y_mm) for a in self.accepted})
                for pos in positions:
                    members = self._line_members(vertical, pos)
                    for i in range(1, len(members) - 1):
                        prev, cur, nxt = members[i - 1], members[i], members[i + 1]
                        if cur.anchor > 0 or cur.origin == "corridor_proj":
                            continue
                        g1 = (cur.y_mm - prev.y_mm) if vertical else (cur.x_mm - prev.x_mm)
                        g2 = (nxt.y_mm - cur.y_mm) if vertical else (nxt.x_mm - cur.x_mm)
                        if g1 >= SHORT_PAIR_MM or g2 >= SHORT_PAIR_MM or g1 + g2 > self.cap_mm:
                            continue
                        if self._waived_pair(prev, cur) or self._waived_pair(cur, nxt):
                            continue
                        if self._removal_leaves_overcap(cur, not vertical):
                            continue
                        self.accepted.remove(cur)
                        dropped.append(cur)
                        progress = True
                        break
                    if progress:
                        break
                if progress:
                    break
        self.accepted.sort(key=lambda s: (s.x_mm, s.y_mm))
        return dropped

    def _nearest_supporting_mm(
        self, axes: Sequence[Axis], storey: int, pos_mm: int, from_mm: int, below: bool
    ) -> Optional[int]:
        """Nearest perpendicular axis past `from_mm` with a WALL member at `pos_mm`."""
        best = None  # type: Optional[int]
        for other in axes:
            p = other.pos_mm
            if below and p >= from_mm - _ON_LINE_TOL_MM:
                continue
            if not below and p <= from_mm + _ON_LINE_TOL_MM:
                continue
            spans = other.member_spans_mm.get(storey) or []
            if not any(lo - _ON_LINE_TOL_MM <= pos_mm <= hi + _ON_LINE_TOL_MM for lo, hi, _tag in spans):
                continue
            if best is None or (below and p > best) or (not below and p < best):
                best = p
        return best

    def _core_corner_tied(self, col: _Stack) -> bool:
        grid = self.view.grid
        for vertical in (True, False):
            axis = _axis_at(
                grid.x_axes if vertical else grid.y_axes,
                col.x_mm if vertical else col.y_mm,
                _AXIS_MATCH_TOL_MM,
            )
            if axis is None:
                continue
            coord = col.y_mm if vertical else col.x_mm
            members = self._line_members(vertical, axis.pos_mm)
            for storey in axis.storeys():
                for lo, hi in axis.extents_mm.get(storey, []):
                    if not (lo - _ON_LINE_TOL_MM <= coord <= hi + _ON_LINE_TOL_MM):
                        continue
                    for a in members:
                        along = a.y_mm if vertical else a.x_mm
                        if a is not col and a.origin != "core" and storey in a.exists and lo - _ON_LINE_TOL_MM <= along <= hi + _ON_LINE_TOL_MM:
                            return True
        return False

    def tie_isolated_core_corners(self) -> bool:
        """Catalogue R9/R11: a core corner that shares no run with a non-core
        column hangs on its trimmers alone. Its two core-edge lines are extended
        from that corner to the nearest perpendicular line that carries a WALL
        there (outline or partition), so the framer runs a beam from the corner
        to that line and the closure pass lands a column on it. Core edges stop
        at the core's own crossing edges in the grid, which is right for a core
        that walls already reach and leaves an island otherwise.

        When that wall line is closer than the merge floor (a stair 900 mm off
        the outer wall), the tie column and the corner form a waived pair, the
        way two corridor edges do: the corner keeps its column (its trimmers
        bear on it) and the outline gets one too. Returns whether any extent
        changed."""
        grid = self.view.grid
        changed = False
        for col in [a for a in self.accepted if a.origin == "core"]:
            if self._core_corner_tied(col):
                continue
            for vertical in (True, False):
                axes = grid.x_axes if vertical else grid.y_axes
                others = grid.y_axes if vertical else grid.x_axes
                axis = _axis_at(axes, col.x_mm if vertical else col.y_mm, _AXIS_MATCH_TOL_MM)
                if axis is None:
                    continue
                coord = col.y_mm if vertical else col.x_mm
                for storey in list(axis.storeys()):
                    if storey not in col.exists:
                        continue
                    spans = []  # type: List[Tuple[int, int]]
                    for lo, hi in axis.extents_mm.get(storey, []):
                        if lo - _ON_LINE_TOL_MM <= coord <= hi + _ON_LINE_TOL_MM:
                            for at_lo in (True, False):
                                end = lo if at_lo else hi
                                if abs(coord - end) > _ON_LINE_TOL_MM:
                                    continue
                                target = self._nearest_supporting_mm(others, storey, axis.pos_mm, end, at_lo)
                                if target is None:
                                    continue
                                if at_lo and target < lo:
                                    lo = target
                                    changed = True
                                elif not at_lo and target > hi:
                                    hi = target
                                    changed = True
                                if 0 < abs(target - coord) < MERGE_FLOOR_MM:
                                    point = (axis.pos_mm, target) if vertical else (target, axis.pos_mm)
                                    key = "core-tie:%d:%d:%d:%d" % (col.x_mm, col.y_mm, point[0], point[1])
                                    self.tie_points[point] = (key, col)
                        spans.append((lo, hi))
                    axis.extents_mm[storey] = _merge_intervals(spans)
        return changed

    def mark_tie_pairs(self, scored: Sequence[_Stack]) -> None:
        """Stamp the shared pair key on a closure column standing on a tie point
        and on the core corner it ties, so the merge floor waives the pair."""
        for stack in scored:
            for (px, py), (key, corner) in self.tie_points.items():
                if abs(stack.x_mm - px) <= _ON_LINE_TOL_MM and abs(stack.y_mm - py) <= _ON_LINE_TOL_MM:
                    if key not in stack.tie_keys:
                        stack.tie_keys.append(key)
                    if key not in corner.tie_keys:
                        corner.tie_keys.append(key)
                    stack.notes.append("ties core corner (%d, %d) mm to this wall line" % (corner.x_mm, corner.y_mm))

    def subdivision_candidates(self) -> List[_Cand]:
        """Even stations where accepted columns leave a gap over the cap (B1)."""
        out = []  # type: List[_Cand]
        seen = set()  # type: Set[Tuple[int, int]]
        for axis in self.view.grid.axes():
            vertical = axis.dir == AxisDir.X
            on_line = [
                a
                for a in self.accepted
                if abs((a.x_mm if vertical else a.y_mm) - axis.pos_mm) <= _ON_LINE_TOL_MM
            ]
            for storey in axis.storeys():
                spans = axis.extents_mm.get(storey, [])
                for lo, hi in spans:
                    coords = sorted(
                        (a.y_mm if vertical else a.x_mm)
                        for a in on_line
                        if storey in a.exists and lo - _ON_LINE_TOL_MM <= (a.y_mm if vertical else a.x_mm) <= hi + _ON_LINE_TOL_MM
                    )
                    for i in range(len(coords) - 1):
                        gap = coords[i + 1] - coords[i]
                        if gap <= self.cap_mm:
                            continue
                        count = -(-gap // self.cap_mm) - 1
                        for step in range(1, count + 1):
                            station = coords[i] + _round_ratio(step * gap, count + 1)
                            if self.view.params.housing_column_variant in ("toward_start", "toward_end"):
                                shift = -300 if self.view.params.housing_column_variant == "toward_start" else 300
                                # Shift the whole even sequence within its end
                                # bay slack. Never create an over-cap end bay or
                                # a sub-bay below the hard merge floor.
                                base_gap = gap // (count + 1)
                                slack = max(0, min(base_gap - MERGE_FLOOR_MM, self.cap_mm - base_gap - 1))
                                station += max(-slack, min(slack, shift))
                            station = self._snap_station(axis, storey, station)
                            point = (axis.pos_mm, station) if vertical else (station, axis.pos_mm)
                            if point not in seen:
                                seen.add(point)
                                # wall-snapped already; junction snapping would
                                # drag the station off its axis (spec B1)
                                out.append(
                                    _Cand(
                                        point[0],
                                        point[1],
                                        0,
                                        "subdiv",
                                        no_snap=True,
                                        slide_axis="y" if vertical else "x",
                                    )
                                )
        return sorted(out, key=lambda c: (c.x_mm, c.y_mm))

    def _snap_station(self, axis: Axis, storey: int, station_mm: int) -> int:
        """Snap a subdivision station to a crossing wall within snap_wall."""
        vertical = axis.dir == AxisDir.X
        best = None  # type: Optional[Tuple[int, int]]
        for rec in self.view.walls.get(storey, []):
            perpendicular = rec.orient == ("h" if vertical else "v")
            if not perpendicular:
                continue
            if not (rec.lo_mm - self.tol_wall_mm <= axis.pos_mm <= rec.hi_mm + self.tol_wall_mm):
                continue
            d = abs(rec.pos_mm - station_mm)
            if d <= self.snap_wall_mm and (best is None or (d, rec.pos_mm) < best):
                best = (d, rec.pos_mm)
        return best[1] if best is not None else station_mm


def place_columns(
    model: StructuralModel,
    grid: AxisGrid,
    core_plan: CorePlan,
    params: FrameParams,
    log: DisclosureLog,
    view: Optional[_View] = None,
) -> Tuple[List[_Stack], _ColumnState]:
    """B1: mandatory anchors, grid intersections, scoring, dedupe, subdivision."""
    view = view if view is not None else _View(model, grid, params)
    state = _ColumnState(view, core_plan, params)

    cands = []  # type: List[_Cand]
    # mandatory anchors are position-pinned: snapping a building corner onto a
    # nearby junction would abandon the corner itself (exact plot fill)
    for x_mm, y_mm in _footprint_corners(grid):
        cands.append(_Cand(x_mm, y_mm, 100, "corner", no_snap=True))
    if core_plan.mode == "columns":
        for x_mm, y_mm, _cid in core_plan.anchors_mm:
            cands.append(_Cand(x_mm, y_mm, 100, "core", no_snap=True))
    for ax in grid.x_axes:
        for ay in grid.y_axes:
            if not (ax.presence & ay.presence):
                continue
            common = [s for s in view.storeys if ax.present(s) and ay.present(s)]
            if any(view.covers(s, ax.pos_mm, ay.pos_mm) for s in common):
                cands.append(
                    _Cand(
                        ax.pos_mm,
                        ay.pos_mm,
                        0,
                        "grid",
                        # The selected economy axes are structural stations.
                        # Do not snap them back onto a discarded architectural
                        # line; door avoidance may still slide/drop them and the
                        # physical-span audit will then decide validity.
                        no_snap=params.column_strategy == "economy_grid",
                    )
                )

    scored = state.process(cands)
    if params.column_strategy == "economy_grid":
        # every intersection of the selected sparse axes is a station of the
        # regular grid by construction; the strategy's whole point
        state.merge(scored)
        subdivision_rounds = 1
    else:
        # PLACEMENT_RULES B1 step 3: candidates are the JUNCTIONS of the wall-line
        # graph (L/T/X) plus the pinned anchors and corridor edge projections. An
        # axis intersection on a wall run or in open floor is never a column in
        # its own right: step 5 adds intermediate columns only where a wall run
        # between two placed columns exceeds max_span, and those stations are
        # extent-aware and wall-snapped by `subdivision_candidates`. Accepting
        # every intersection here put a column 7 ft along a 14 ft wall (a
        # 4.27 m span under the 5 m cap) and a free column wherever two walls'
        # axes crossed in a room.
        state.merge(
            [
                s
                for s in scored
                if s.anchor > 0
                or s.origin == "corridor_proj"
                or s.jn >= 2
                or state.on_core_edge(s.x_mm, s.y_mm)
            ]
        )
        # then close every line that carries a column at the ends of its run,
        # where a wall passes (R11: beams land on columns at both ends); a core
        # corner otherwise hangs on its trimmers alone with no beam to the frame
        closure = state.process(state.closure_candidates())
        state.merge([s for s in closure if s.jn >= 1])
        # a core no wall reaches gets its edge lines run out to the nearest wall
        # line and closed there (R9/R11), then the R6 upper band collapses a
        # column squeezed between two short spans
        if state.tie_isolated_core_corners():
            closure = state.process(state.closure_candidates())
            state.mark_tie_pairs(closure)
            state.merge([s for s in closure if s.jn >= 1])
        state.collapse_short_pairs()
        # a room over the cap in both directions gets its mid-wall stations in
        # round 1 and, if the line through them is still over the cap, its
        # centre station in round 2; bounded, the panel feedback covers the rest
        subdivision_rounds = 2
    for _round in range(subdivision_rounds):
        subdiv = state.subdivision_candidates()
        if not subdiv:
            break
        state.merge(state.process(subdiv))

    for stack in state.accepted:
        stack.axis_x = _axis_at(grid.x_axes, stack.x_mm, _AXIS_MATCH_TOL_MM)
        stack.axis_y = _axis_at(grid.y_axes, stack.y_mm, _AXIS_MATCH_TOL_MM)
    if state.midwall_fired:
        # the closest registered code: doors were assumed mid-wall
        log.add(
            "W_DOOR_ASSUMED",
            "doors unknown: mid-third rule applied on %d interior walls" % len(state.midwall_fired),
            sorted(state.midwall_fired),
            stage=_STAGE_COLS,
        )
    for wall_id in sorted(set(state.door_dropped)):
        log.add(
            "W_COLUMN_IN_DOOR",
            "column candidate dropped: every slide station on wall %s lands in a door interval" % wall_id,
            [wall_id],
            stage=_STAGE_COLS,
        )
    return (state.accepted, state)


# ---------------------------------------------------------------------------
# continuity (spec 5.2)
# ---------------------------------------------------------------------------


def _distance_to_region(footprint: Optional[_Footprint], x_mm: int, y_mm: int) -> int:
    """Chebyshev distance from a point to the storey region (0 when inside)."""
    if footprint is None or footprint.is_empty():
        return 10 ** 9
    best = None  # type: Optional[int]
    for x0, y0, x1, y1 in footprint.rects:
        dx = max(x0 - x_mm, 0, x_mm - x1)
        dy = max(y0 - y_mm, 0, y_mm - y1)
        d = max(dx, dy)
        if best is None or d < best:
            best = d
    return best if best is not None else 10 ** 9


def enforce_continuity(
    view: _View,
    stacks: List[_Stack],
    state: _ColumnState,
    params: FrameParams,
    log: DisclosureLog,
) -> List[_Stack]:
    """Walk every stack to the ground; slide, drop to cantilever, or flag transfer."""
    refuse_mm = _mm(max(REFUSE_CANTILEVER_M, float(params.cantilever_cap)))
    kept = []  # type: List[_Stack]
    for stack in sorted(stacks, key=lambda s: (s.x_mm, s.y_mm)):
        failures = [s for s in range(0, stack.top + 1) if not view.covers(s, stack.x_mm, stack.y_mm)]
        if not failures:
            stack.base = 0
            kept.append(stack)
            continue
        horizontal = (stack.w_dir or "h") == "h"  # slide along the wall; free stacks slide in x
        repaired = False
        for d in _slide_ladder(SLIDE_STEP_MM, SLIDE_MAX_MM):
            nx = stack.x_mm + d if horizontal else stack.x_mm
            ny = stack.y_mm if horizontal else stack.y_mm + d
            if not all(view.covers(s, nx, ny) for s in range(0, stack.top + 1)):
                continue
            if view.door_conflicts(nx, ny, range(0, stack.top + 1)):
                continue
            if view.corridor_strictly_inside(nx, ny, range(0, stack.top + 1), state.snap_wall_mm) is not None:
                continue
            exists = _existing_storeys(view, nx, ny)
            if not view.housing_wall_allowed(nx, ny, exists):
                continue
            mates_ok = True
            for a in kept:
                cross = abs((a.y_mm - ny) if horizontal else (a.x_mm - nx))
                if cross > _ON_LINE_TOL_MM:
                    continue
                gap = abs((a.x_mm - nx) if horizontal else (a.y_mm - ny))
                if 0 < gap < state.min_span_mm:
                    mates_ok = False
                    break
            if not mates_ok:
                continue
            stack.slid_mm = d
            stack.slide_dir = "x" if horizontal else "y"
            stack.x_mm, stack.y_mm = nx, ny
            stack.exists = exists
            stack.base = 0
            stack.notes.append("slid %d mm along %s" % (d, stack.slide_dir))
            stack.axis_x = _axis_at(view.grid.x_axes, nx, _AXIS_MATCH_TOL_MM)
            stack.axis_y = _axis_at(view.grid.y_axes, ny, _AXIS_MATCH_TOL_MM)
            repaired = True
            break
        if repaired:
            kept.append(stack)
            continue
        dmax = max(
            _distance_to_region(view.grid.footprints.get(s), stack.x_mm, stack.y_mm)
            for s in failures
        )
        if dmax <= refuse_mm:
            # the overhang framing (cantilever pass) carries this area instead
            continue
        stack.transfer = True
        stack.unsupported = failures
        stack.base = min(stack.exists)
        stack.notes.append("unsupported below storey %d" % min(failures))
        kept.append(stack)
    return kept


def _assign_sizes(stacks: List[_Stack], view: _View, log: DisclosureLog) -> None:
    tall = []  # type: List[str]
    for stack in stacks:
        levels = sorted(set(int(storey) for storey in stack.exists))
        raw = {}  # type: Dict[int, Tuple[int, int]]
        for storey in levels:
            remaining = sum(1 for level in levels if level >= storey)
            raw[storey] = (
                (300, 600)
                if remaining >= 8
                else _COLUMN_LADDER.get(max(1, remaining), (230, 230))
            )

        # A dimension may reduce at a floor but may never increase above one.
        # Envelope from the roof down.  This is material at the 8 -> 7 rung:
        # raw 300 x 600 below raw 380 x 450 would otherwise widen upward.
        sections = {}  # type: Dict[int, Tuple[int, int]]
        upper_w = upper_d = 0
        for storey in reversed(levels):
            raw_w, raw_d = raw[storey]
            width = max(raw_w, upper_w)
            depth = max(raw_d, upper_d)
            sections[storey] = (width, depth)
            upper_w, upper_d = width, depth
        stack.sections_by_storey = dict(sorted(sections.items()))
        if levels:
            stack.w_mm, stack.d_mm = stack.section_at(levels[0])

        if len(levels) > 5:
            tall.append(stack.id or stack_id(x_m=_m(stack.x_mm), y_m=_m(stack.y_mm)))
        # orientation: long side lies in the longest supporting wall
        best = None  # type: Optional[Tuple[int, str, str]]
        for storey in stack.exists:
            for rec in view.walls_through(storey, stack.x_mm, stack.y_mm):
                key = (-rec.length_mm, rec.orient, rec.id)
                if best is None or key < best:
                    best = key
        if best is not None:
            stack.rot = 0 if best[1] == "h" else 90
        else:
            gx = _span_balance_gap(view.grid.x_axes, stack.x_mm)
            gy = _span_balance_gap(view.grid.y_axes, stack.y_mm)
            stack.rot = 0 if gx >= gy else 90
    if tall:
        log.add(
            "W_TALL",
            "%d column stacks carry more than 5 storeys; thumb sizes need design review" % len(tall),
            sorted(tall),
            stage=_STAGE_COLS,
        )


def _span_balance_gap(axes: Sequence[Axis], coord_mm: int) -> int:
    positions = sorted(a.pos_mm for a in axes)
    prev = max((p for p in positions if p < coord_mm), default=None)
    nxt = min((p for p in positions if p > coord_mm), default=None)
    left = coord_mm - prev if prev is not None else 0
    right = nxt - coord_mm if nxt is not None else 0
    return left + right


def _assign_stack_ids(stacks: List[_Stack]) -> None:
    seen = set()  # type: Set[str]
    for stack in sorted(stacks, key=lambda s: (s.x_mm, s.y_mm)):
        if stack.on_grid():
            base = stack_id(stack.axis_x.label, stack.axis_y.label)
        else:
            base = stack_id(x_m=_m(stack.x_mm), y_m=_m(stack.y_mm))
        candidate = base
        bump = 2
        while candidate in seen:
            candidate = base + "-" + str(bump)
            bump += 1
        seen.add(candidate)
        stack.id = candidate


# ---------------------------------------------------------------------------
# beams
# ---------------------------------------------------------------------------


@dataclass
class _PBeam:
    level_key: str  # "P", "T0", "0", "1", ...
    level_rank: int
    storey: int
    kind: BeamKind
    orient: str  # "h" runs in x, "v" runs in y
    pos_mm: int
    lo_mm: int
    hi_mm: int
    width_mm: int = 230
    depth_mm: int = 300
    under_wall: Optional[str] = None
    supports: Tuple[str, str] = ("", "")
    chain: int = 1
    core_id: Optional[str] = None
    note: str = ""
    key: str = ""
    line_label: Optional[str] = None
    axis_ref: Optional[str] = None
    id: str = ""

    @property
    def span_mm(self) -> int:
        return self.hi_mm - self.lo_mm

    def points_mm(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        if self.orient == "h":
            return ((self.lo_mm, self.pos_mm), (self.hi_mm, self.pos_mm))
        return ((self.pos_mm, self.lo_mm), (self.pos_mm, self.hi_mm))

    def to_dict(self) -> Dict[str, Any]:
        (x1, y1), (x2, y2) = self.points_mm()
        level = int(self.level_key) if self.level_key.isdigit() else self.level_key
        return {
            "id": self.id,
            "level": level,
            "storey": int(self.storey),
            "kind": self.kind.value,
            "x1_m": _m(x1),
            "y1_m": _m(y1),
            "x2_m": _m(x2),
            "y2_m": _m(y2),
            "span_m": _m(self.span_mm),
            "width_mm": int(self.width_mm),
            "depth_mm": int(self.depth_mm),
            "axis": self.axis_ref,
            "under_wall": self.under_wall,
            "supports": [self.supports[0], self.supports[1]],
            "chain": int(self.chain),
            "sized_by": "thumb",
            "note": self.note,
        }


def _level_key(storey: int) -> str:
    return str(int(storey))


def _level_rank(key: str) -> int:
    if key == "P":
        return 0
    if key.startswith("T"):
        return 1
    return 2 + int(key)


def _beam_covers(beams: Sequence[_PBeam], orient: str, pos_mm: int, lo_mm: int, hi_mm: int, lateral_mm: int, ratio: float = 0.8) -> bool:
    length = hi_mm - lo_mm
    if length <= 0:
        return True
    covered = []  # type: List[Tuple[int, int]]
    for beam in beams:
        if beam.orient != orient or abs(beam.pos_mm - pos_mm) > lateral_mm:
            continue
        piece = (max(lo_mm, beam.lo_mm), min(hi_mm, beam.hi_mm))
        if piece[1] > piece[0]:
            covered.append(piece)
    total = sum(hi - lo for lo, hi in _merge_intervals(covered))
    return total >= int(ratio * length)


class _Framer:
    """Per-level beam framing, shared across feedback iterations."""

    def __init__(
        self,
        view: _View,
        stacks: List[_Stack],
        core_beams: Sequence[CoreBeam],
        params: FrameParams,
        log: DisclosureLog,
        state: _ColumnState,
    ):
        self.view = view
        self.stacks = stacks
        self.params = params
        self.log = log
        self.state = state
        self.core_beams = list(core_beams)
        self.reinstated = set()  # type: Set[str]
        self.secondary_specs = {}  # type: Dict[int, List[Tuple[str, int, int, int, Optional[str], str]]]
        self.pruned = {}  # type: Dict[int, List[_PBeam]]
        self.cap_mm = state.cap_mm
        self.overhangs = self._compute_overhangs()
        self.cantilever_logged = set()  # type: Set[str]

    # -- overhangs -----------------------------------------------------------

    def _compute_overhangs(self) -> Dict[int, List[Tuple[int, int, int, int]]]:
        out = {}  # type: Dict[int, List[Tuple[int, int, int, int]]]
        for storey in self.view.storeys:
            if storey == 0:
                out[storey] = []
                continue
            here = self.view.grid.footprints.get(storey)
            below = self.view.grid.footprints.get(storey - 1)
            if here is None or below is None:
                out[storey] = []
                continue
            out[storey] = _rects_subtract(here.rects, below.rects)
        return out

    def _backing_edge(self, storey: int, rect: Tuple[int, int, int, int]) -> Optional[str]:
        below = self.view.grid.footprints.get(storey - 1)
        if below is None:
            return None
        x0, y0, x1, y1 = rect
        probes = {
            "n": ((x0 + x1) // 2, y0 - 10),
            "e": (x1 + 10, (y0 + y1) // 2),
            "s": ((x0 + x1) // 2, y1 + 10),
            "w": (x0 - 10, (y0 + y1) // 2),
        }
        lengths = {"n": x1 - x0, "e": y1 - y0, "s": x1 - x0, "w": y1 - y0}
        best = None  # type: Optional[Tuple[int, int, str]]
        for order, tag in enumerate(("n", "e", "s", "w")):
            px, py = probes[tag]
            if below.covers(px, py):
                key = (-lengths[tag], order, tag)
                if best is None or key < best:
                    best = key
        return best[2] if best is not None else None

    # -- one level -----------------------------------------------------------

    def frame_level(self, storey: int) -> List[_PBeam]:
        view = self.view
        footprint = view.grid.footprints.get(storey)
        beams = []  # type: List[_PBeam]
        pruned = []  # type: List[_PBeam]
        key = _level_key(storey)
        rank = _level_rank(key)

        # core trimmers / headers / landings: always kept
        for cb in self.core_beams:
            if cb.level != storey:
                continue
            beams.append(
                _PBeam(
                    level_key=key,
                    level_rank=rank,
                    storey=storey,
                    kind=cb.kind,
                    orient=cb.orient,
                    pos_mm=cb.pos_mm,
                    lo_mm=cb.lo_mm,
                    hi_mm=cb.hi_mm,
                    width_mm=cb.width_mm,
                    depth_mm=cb.depth_mm,
                    core_id=cb.core_id,
                    note=cb.note,
                    supports=("core", "core"),
                    chain=1,
                )
            )

        # 1. primary candidates on every axis between adjacent columns
        for axis in view.grid.axes():
            if not axis.present(storey):
                continue
            vertical = axis.dir == AxisDir.X
            orient = "v" if vertical else "h"
            on_line = [
                s
                for s in self.stacks
                if storey in s.exists
                and abs((s.x_mm if vertical else s.y_mm) - axis.pos_mm) <= _ON_LINE_TOL_MM
            ]
            coords = sorted((s.y_mm if vertical else s.x_mm) for s in on_line)
            chords = footprint.chords_mm(orient, axis.pos_mm) if footprint is not None else []
            for i in range(len(coords) - 1):
                lo, hi = coords[i], coords[i + 1]
                if hi - lo < 50:
                    continue
                if hi - lo > self.cap_mm:
                    # no admissible primary between columns this far apart:
                    # subdivision could not land a column (merge floor), so the
                    # line is framed by the segmented bearing/corridor duty
                    continue
                if not any(clo <= lo and hi <= chi for clo, chi in chords):
                    continue
                if self._crosses_core(orient, axis.pos_mm, lo, hi):
                    continue
                cand_key = "pri:%d:%s:%d:%d:%d" % (storey, orient, axis.pos_mm, lo, hi)
                beam = _PBeam(
                    level_key=key,
                    level_rank=rank,
                    storey=storey,
                    kind=BeamKind.PRIMARY,
                    orient=orient,
                    pos_mm=axis.pos_mm,
                    lo_mm=lo,
                    hi_mm=hi,
                    supports=("col", "col"),
                    chain=1,
                    key=cand_key,
                    axis_ref=axis.id,
                    line_label=axis.label,
                )
                if self._keep_primary(beam, axis, storey) or cand_key in self.reinstated:
                    if not _beam_covers(beams, orient, axis.pos_mm, lo, hi, 10, 0.98):
                        beams.append(beam)
                else:
                    pruned.append(beam)
        self.pruned[storey] = pruned

        # 4. cantilevers: true overhangs framed off the backing line
        beams.extend(self._cantilever_beams(storey, key, rank))

        # 2. wall-bearing duty, then the corridor edges (both must be framed)
        beams.extend(self._bearing_beams(storey, key, rank, beams))
        beams.extend(self._corridor_edge_beams(storey, key, rank, beams))

        # 3. secondaries recorded by the feedback loop
        for orient, pos, lo, hi, wall_id, skey in self.secondary_specs.get(storey, []):
            if _beam_covers(beams, orient, pos, lo, hi, 60, 0.98):
                continue
            secondary = _PBeam(
                level_key=key,
                level_rank=rank,
                storey=storey,
                kind=BeamKind.SECONDARY,
                orient=orient,
                pos_mm=pos,
                lo_mm=lo,
                hi_mm=hi,
                under_wall=wall_id,
                key=skey,
                note="slab_feedback",
            )
            tags = []
            for end in (lo, hi):
                tags.append(self._end_support_tag(secondary, end, beams))
            secondary.supports = (tags[0], tags[1])
            beams.append(secondary)

        self._resolve_chains(storey, beams)
        beams.sort(key=lambda b: (b.orient, b.pos_mm, b.lo_mm, b.hi_mm, b.kind.value))
        return beams

    def _crosses_core(self, orient: str, pos_mm: int, lo_mm: int, hi_mm: int) -> bool:
        """A slab beam may not fly across a stair or lift opening interior."""
        tol = self.state.tol_wall_mm
        for cid in sorted(self.state.core_plan.core_rects_mm):
            x0, y0, x1, y1 = self.state.core_plan.core_rects_mm[cid]
            if orient == "h":
                if y0 + tol < pos_mm < y1 - tol and _overlap(lo_mm, hi_mm, x0 + tol, x1 - tol) > 0:
                    return True
            else:
                if x0 + tol < pos_mm < x1 - tol and _overlap(lo_mm, hi_mm, y0 + tol, y1 - tol) > 0:
                    return True
        return False

    def _keep_primary(self, beam: _PBeam, axis: Axis, storey: int) -> bool:
        view = self.view
        # a wall along >= 30 pct of the beam
        wall_len = 0
        for rec in view.walls.get(storey, []):
            if rec.orient != beam.orient:
                continue
            tol = max(rec.t_mm, view.default_t_mm) // 2
            if abs(rec.pos_mm - beam.pos_mm) > tol:
                continue
            wall_len += _overlap(beam.lo_mm, beam.hi_mm, rec.lo_mm, rec.hi_mm)
        if wall_len * 10 >= beam.span_mm * 3:
            return True
        # a corridor long edge
        for rect in view.corridors.get(storey, []):
            orient, p1, p2, lo, hi = rect.long_edges()
            if orient == beam.orient and (abs(beam.pos_mm - p1) <= 60 or abs(beam.pos_mm - p2) <= 60):
                if _overlap(beam.lo_mm, beam.hi_mm, lo, hi) > 0:
                    return True
        # the footprint perimeter
        footprint = view.grid.footprints.get(storey)
        if footprint is not None:
            for pos, lo, hi in footprint.boundary_lines(beam.orient):
                if abs(pos - beam.pos_mm) <= 60 and _overlap(beam.lo_mm, beam.hi_mm, lo, hi) >= beam.span_mm - 20:
                    return True
        return False

    def _cantilever_beams(self, storey: int, key: str, rank: int) -> List[_PBeam]:
        out = []  # type: List[_PBeam]
        cap_mm = _mm(float(self.params.cantilever_cap))
        refuse_mm = _mm(max(REFUSE_CANTILEVER_M, float(self.params.cantilever_cap)))
        for rect in self.overhangs.get(storey, []):
            x0, y0, x1, y1 = rect
            tag = self._backing_edge(storey, rect)
            geom = "overhang s%d %d,%d..%d,%d" % (storey, x0, y0, x1, y1)
            if tag is None:
                if geom not in self.cantilever_logged:
                    self.log.add(
                        "E_CANTILEVER_SPAN",
                        "overhang at storey %d has no backing support line (%s)" % (storey, geom),
                        (),
                        stage=_STAGE_BEAMS,
                    )
                    self.cantilever_logged.add(geom)
                continue
            depth = (y1 - y0) if tag in ("n", "s") else (x1 - x0)
            if depth > refuse_mm:
                if geom not in self.cantilever_logged:
                    self.log.add(
                        "E_CANTILEVER_SPAN",
                        "cantilever %d mm at storey %d exceeds the %d mm refusal span (%s)"
                        % (depth, storey, refuse_mm, geom),
                        (),
                        stage=_STAGE_BEAMS,
                    )
                    self.cantilever_logged.add(geom)
                continue
            if depth > cap_mm and geom not in self.cantilever_logged:
                self.log.add(
                    "W_CANTILEVER",
                    "cantilever %d mm at storey %d is over the %d mm auto cap" % (depth, storey, cap_mm),
                    (),
                    stage=_STAGE_BEAMS,
                )
                self.cantilever_logged.add(geom)
            if tag in ("n", "s"):
                # backing "n" means the supported storey lies NORTH of the rect,
                # so the shared (backing) edge is y0 and the tip is y1
                back_pos = y0 if tag == "n" else y1
                tip_pos = y1 if tag == "n" else y0
                cross_lo, cross_hi = x0, x1
                orient, sp_orient = "v", "h"
            else:
                back_pos = x0 if tag == "w" else x1
                tip_pos = x1 if tag == "w" else x0
                cross_lo, cross_hi = y0, y1
                orient, sp_orient = "h", "v"
            stations = [cross_lo, cross_hi]
            for s in self.stacks:
                if storey not in s.exists:
                    continue
                back_coord = s.y_mm if orient == "v" else s.x_mm
                cross_coord = s.x_mm if orient == "v" else s.y_mm
                if abs(back_coord - back_pos) <= _ON_LINE_TOL_MM and cross_lo < cross_coord < cross_hi:
                    stations.append(cross_coord)
            for station in sorted(set(stations)):
                out.append(
                    _PBeam(
                        level_key=key,
                        level_rank=rank,
                        storey=storey,
                        kind=BeamKind.CANTILEVER,
                        orient=orient,
                        pos_mm=station,
                        lo_mm=min(back_pos, tip_pos),
                        hi_mm=max(back_pos, tip_pos),
                        supports=("col", "tip"),
                        chain=1,
                        note="cantilever_" + tag,
                    )
                )
            out.append(
                _PBeam(
                    level_key=key,
                    level_rank=rank,
                    storey=storey,
                    kind=BeamKind.SPANDREL,
                    orient=sp_orient,
                    pos_mm=tip_pos,
                    lo_mm=cross_lo,
                    hi_mm=cross_hi,
                    supports=("beam", "beam"),
                    chain=1,
                    note="cantilever_tip",
                )
            )
            backspan = self._nearest_backspan(storey, orient, back_pos, cross_lo, cross_hi, tag)
            if backspan is not None and backspan * 2 < depth * 3 and (geom + ":bs") not in self.cantilever_logged:
                self.log.add(
                    "W_BACKSPAN",
                    "cantilever backspan %d mm is under 1.5x the %d mm projection (%s)"
                    % (backspan, depth, geom),
                    (),
                    stage=_STAGE_BEAMS,
                )
                self.cantilever_logged.add(geom + ":bs")
        return out

    def _nearest_backspan(self, storey: int, orient: str, back_pos: int, cross_lo: int, cross_hi: int, tag: str) -> Optional[int]:
        # the supported region lies on the backing side: north or west means
        # the backspan columns sit at DECREASING coordinates
        inward = -1 if tag in ("n", "w") else 1
        best = None  # type: Optional[int]
        for s in self.stacks:
            if storey not in s.exists:
                continue
            back_coord = s.y_mm if orient == "v" else s.x_mm
            cross_coord = s.x_mm if orient == "v" else s.y_mm
            if not (cross_lo - _ON_LINE_TOL_MM <= cross_coord <= cross_hi + _ON_LINE_TOL_MM):
                continue
            d = (back_coord - back_pos) * inward
            if d > _ON_LINE_TOL_MM and (best is None or d < best):
                best = d
        return best

    def _bearing_beams(self, storey: int, key: str, rank: int, existing: List[_PBeam]) -> List[_PBeam]:
        view = self.view
        out = []  # type: List[_PBeam]
        for rec in view.walls.get(storey, []):
            if not rec.qualifying:
                continue
            lateral = max(60, rec.t_mm // 2)
            out.extend(
                self._duty_beams(
                    storey,
                    key,
                    rank,
                    rec.orient,
                    rec.pos_mm,
                    rec.lo_mm,
                    rec.hi_mm,
                    lateral,
                    existing + out,
                    under_wall=rec.id,
                    note="wall_bearing",
                )
            )
        return out

    def _corridor_edge_beams(self, storey: int, key: str, rank: int, existing: List[_PBeam]) -> List[_PBeam]:
        """Both corridor long edges carry beams even where no wall stands."""
        out = []  # type: List[_PBeam]
        for rect in self.view.corridors.get(storey, []):
            orient, p1, p2, lo, hi = rect.long_edges()
            for pos in (p1, p2):
                out.extend(
                    self._duty_beams(
                        storey,
                        key,
                        rank,
                        orient,
                        pos,
                        lo,
                        hi,
                        60,
                        existing + out,
                        under_wall=None,
                        note="corridor_edge",
                    )
                )
        return out

    def _duty_beams(
        self,
        storey: int,
        key: str,
        rank: int,
        orient: str,
        pos_mm: int,
        lo_mm: int,
        hi_mm: int,
        lateral_mm: int,
        others: Sequence[_PBeam],
        under_wall: Optional[str],
        note: str,
    ) -> List[_PBeam]:
        """Cover [lo, hi] on a line with beams between the nearest supports.

        Pieces are segmented at column stations always and, when a piece still
        exceeds the span cap, at perpendicular beam crossings (those segments
        become secondaries bearing on the crossing beams).
        """
        footprint = self.view.grid.footprints.get(storey)
        covered = []  # type: List[Tuple[int, int]]
        for beam in others:
            if beam.orient != orient or abs(beam.pos_mm - pos_mm) > lateral_mm:
                continue
            piece = (max(lo_mm, beam.lo_mm), min(hi_mm, beam.hi_mm))
            if piece[1] > piece[0]:
                covered.append(piece)
        uncovered = _subtract_intervals([(lo_mm, hi_mm)], _merge_intervals(covered))
        stations = self._line_stations(storey, orient, pos_mm, lateral_mm, others)
        out = []  # type: List[_PBeam]
        for ulo, uhi in uncovered:
            if uhi - ulo < 60:
                continue
            start, start_tag = self._nearest_station(stations, ulo, before=True)
            end, end_tag = self._nearest_station(stations, uhi, before=False)
            if footprint is not None:
                for clo, chi in footprint.chords_mm(orient, pos_mm):
                    if clo <= ulo and uhi <= chi:
                        start = max(start, clo)
                        end = min(end, chi)
                        break
            if end - start < 60:
                continue
            cuts = [(start, start_tag), (end, end_tag)]
            for spos, stag in stations:
                if start < spos < end and stag == "col":
                    cuts.append((spos, stag))
            cuts = sorted(set(cuts))
            pieces = []  # type: List[Tuple[int, str, int, str]]
            for i in range(len(cuts) - 1):
                pieces.append((cuts[i][0], cuts[i][1], cuts[i + 1][0], cuts[i + 1][1]))
            final = []  # type: List[Tuple[int, str, int, str]]
            for plo, tag_lo, phi, tag_hi in pieces:
                if phi - plo > self.cap_mm:
                    inner = sorted(
                        set(s for s, t in stations if plo < s < phi and t == "beam")
                    )
                    stubs = self._link_stubs(storey, key, rank, orient, pos_mm, plo, phi, inner)
                    out.extend(stubs)
                    inner = sorted(set(inner) | {s.pos_mm for s in stubs})
                    edges = [plo] + inner + [phi]
                    tags = [tag_lo] + ["beam"] * len(inner) + [tag_hi]
                    for i in range(len(edges) - 1):
                        final.append((edges[i], tags[i], edges[i + 1], tags[i + 1]))
                else:
                    final.append((plo, tag_lo, phi, tag_hi))
            for plo, tag_lo, phi, tag_hi in final:
                if phi - plo < 60:
                    continue
                kind = BeamKind.PRIMARY if tag_lo == "col" and tag_hi == "col" else BeamKind.SECONDARY
                out.append(
                    _PBeam(
                        level_key=key,
                        level_rank=rank,
                        storey=storey,
                        kind=kind,
                        orient=orient,
                        pos_mm=pos_mm,
                        lo_mm=plo,
                        hi_mm=phi,
                        under_wall=under_wall,
                        supports=(tag_lo, tag_hi),
                        note=note,
                    )
                )
        return out

    def _link_stubs(
        self,
        storey: int,
        key: str,
        rank: int,
        orient: str,
        pos_mm: int,
        lo_mm: int,
        hi_mm: int,
        existing_stations: Sequence[int],
    ) -> List[_PBeam]:
        """Short bracket beams from a parallel column line onto an over-span line.

        A line the merge floor kept column-free (a boundary 0.6 m off the unit
        walls, a corridor edge 0.3 m off the outline) is picked up by stubs
        cantilevering from the nearest parallel columns, and the long beam is
        then segmented at the stubs.
        """
        reach_mm = _mm(REFUSE_CANTILEVER_M)
        by_along = {}  # type: Dict[int, Tuple[int, int]]
        for s in self.stacks:
            if storey not in s.exists:
                continue
            cross = s.y_mm if orient == "h" else s.x_mm
            along = s.x_mm if orient == "h" else s.y_mm
            lateral = abs(cross - pos_mm)
            if lateral <= _ON_LINE_TOL_MM or lateral > reach_mm:
                continue
            if not (lo_mm + 60 < along < hi_mm - 60):
                continue
            if any(abs(along - st) <= _ON_LINE_TOL_MM for st in existing_stations):
                continue
            if along not in by_along or lateral < abs(by_along[along][0] - pos_mm):
                by_along[along] = (cross, lateral)
        stubs = []  # type: List[_PBeam]
        for along in sorted(by_along):
            cross = by_along[along][0]
            stubs.append(
                _PBeam(
                    level_key=key,
                    level_rank=rank,
                    storey=storey,
                    kind=BeamKind.CANTILEVER,
                    orient="v" if orient == "h" else "h",
                    pos_mm=along,
                    lo_mm=min(cross, pos_mm),
                    hi_mm=max(cross, pos_mm),
                    supports=("col", "tip"),
                    chain=1,
                    note="link_stub",
                )
            )
        return stubs

    def _line_stations(
        self, storey: int, orient: str, pos_mm: int, lateral_mm: int, beams: Sequence[_PBeam]
    ) -> List[Tuple[int, str]]:
        """Support stations along a line: columns first, then beam crossings."""
        stations = []  # type: List[Tuple[int, str]]
        for s in self.stacks:
            if storey not in s.exists:
                continue
            cross = s.y_mm if orient == "h" else s.x_mm
            along = s.x_mm if orient == "h" else s.y_mm
            if abs(cross - pos_mm) <= max(lateral_mm, _ON_LINE_TOL_MM):
                stations.append((along, "col"))
        perp = "v" if orient == "h" else "h"
        for beam in beams:
            if beam.orient != perp:
                continue
            if beam.lo_mm - 60 <= pos_mm <= beam.hi_mm + 60:
                stations.append((beam.pos_mm, "beam"))
        # a column at a station outranks a beam crossing at the same station
        best = {}  # type: Dict[int, str]
        for along, tag in sorted(stations):
            if along not in best or (tag == "col" and best[along] == "beam"):
                best[along] = tag
        return [(along, best[along]) for along in sorted(best)]

    @staticmethod
    def _nearest_station(stations: Sequence[Tuple[int, str]], at_mm: int, before: bool) -> Tuple[int, str]:
        best = None  # type: Optional[Tuple[int, str]]
        for pos, tag in stations:
            if before and pos <= at_mm + 60:
                if best is None or pos > best[0] or (pos == best[0] and tag == "col"):
                    best = (pos, tag)
            if not before and pos >= at_mm - 60:
                if best is None or pos < best[0] or (pos == best[0] and tag == "col"):
                    best = (pos, tag)
        return best if best is not None else (at_mm, "free")

    _FIXED_KINDS = (
        BeamKind.TRIMMER,
        BeamKind.LANDING,
        BeamKind.LINTEL,
        BeamKind.CANTILEVER,
        BeamKind.SPANDREL,
    )

    def _recompute_chains(self, beams: List[_PBeam]) -> None:
        for _round in range(6):
            changed = False
            for beam in beams:
                if beam.kind in self._FIXED_KINDS:
                    new = 1
                elif beam.supports == ("col", "col"):
                    new = 1
                elif beam.span_mm <= 600 and "col" in beam.supports:
                    new = 1  # a joint-zone closure piece, not a bearing level
                else:
                    depths = []
                    for end_i, tag in enumerate(beam.supports):
                        if tag in ("col", "core", "stub", "tip"):
                            depths.append(0)
                        elif tag == "beam":
                            end = beam.lo_mm if end_i == 0 else beam.hi_mm
                            depths.append(self._support_depth(beam, end, beams))
                        else:
                            depths.append(1)
                    new = 1 + max(depths) if depths else 1
                if new != beam.chain:
                    beam.chain = new
                    changed = True
            if not changed:
                break

    def _resolve_chains(self, storey: int, beams: List[_PBeam]) -> None:
        """Bearing-depth bookkeeping with the W_TERTIARY repair ladder.

        A chain-3 beam (a beam on a beam on a beam) is disclosed, then repaired
        in order: extend its deep end to the next column or chain-1 line,
        bracket the deep end with a link stub off a parallel column, promote
        the bearing point to a column stack (full B1 checks and the merge
        floor). Only when all three fail does E_FRAMING_DEPTH stand.
        """
        self._refresh_end_supports(beams)
        self._recompute_chains(beams)
        for _pass in range(4):
            offenders = sorted(
                (b for b in beams if b.chain >= 3 and b.kind not in self._FIXED_KINDS),
                key=lambda b: (b.orient, b.pos_mm, b.lo_mm),
            )
            if not offenders:
                return
            beam = offenders[0]
            self.log.add(
                "W_TERTIARY",
                "beam under %s bears on a beam that bears on a beam (chain %d)"
                % (beam.under_wall or "a panel", beam.chain),
                [beam.under_wall] if beam.under_wall else (),
                stage=_STAGE_BEAMS,
            )
            repaired = (
                self._extend_repair(storey, beam, beams)
                or self._stub_repair(storey, beam, beams)
                or self._promote_support(storey, beam, beams)
            )
            if not repaired:
                self.log.add(
                    "E_FRAMING_DEPTH",
                    "framing depth exceeds the slab-secondary-primary-column chain at level %d" % storey,
                    [beam.under_wall] if beam.under_wall else (),
                    stage=_STAGE_BEAMS,
                )
                beam.chain = 2  # stop re-reporting the same member
            self._refresh_end_supports(beams)
            self._recompute_chains(beams)
        # anything still deep after the pass budget is disclosed as an error
        for beam in beams:
            if beam.chain >= 3 and beam.kind not in self._FIXED_KINDS:
                self.log.add(
                    "E_FRAMING_DEPTH",
                    "framing depth exceeds the slab-secondary-primary-column chain at level %d" % storey,
                    [beam.under_wall] if beam.under_wall else (),
                    stage=_STAGE_BEAMS,
                )

    def _deep_ends(self, beam: _PBeam, beams: Sequence[_PBeam]) -> List[int]:
        ends = []  # type: List[int]
        for end_i, tag in enumerate(beam.supports):
            if tag != "beam":
                continue
            end = beam.lo_mm if end_i == 0 else beam.hi_mm
            if self._support_depth(beam, end, beams) >= 2:
                ends.append(end_i)
        return ends

    def _extend_repair(self, storey: int, beam: _PBeam, beams: List[_PBeam]) -> bool:
        """Run the deep end onward to the next column or chain-1 crossing."""
        reach_mm = _mm(REFUSE_CANTILEVER_M)
        footprint = self.view.grid.footprints.get(storey)
        chords = footprint.chords_mm(beam.orient, beam.pos_mm) if footprint is not None else []
        for end_i in self._deep_ends(beam, beams):
            outward = -1 if end_i == 0 else 1
            end = beam.lo_mm if end_i == 0 else beam.hi_mm
            stations = []  # type: List[Tuple[int, str]]
            for s in self.stacks:
                if storey not in s.exists:
                    continue
                cross = s.y_mm if beam.orient == "h" else s.x_mm
                along = s.x_mm if beam.orient == "h" else s.y_mm
                if abs(cross - beam.pos_mm) > _ON_LINE_TOL_MM:
                    continue
                d = (along - end) * outward
                if 0 < d <= reach_mm:
                    stations.append((d, "col"))
            perp = "v" if beam.orient == "h" else "h"
            for other in beams:
                if other is beam or other.orient != perp or other.chain > 1:
                    continue
                if not (other.lo_mm - 60 <= beam.pos_mm <= other.hi_mm + 60):
                    continue
                d = (other.pos_mm - end) * outward
                if 0 < d <= reach_mm:
                    stations.append((d, "beam"))
            for d, tag in sorted(stations, key=lambda t: (t[0], 0 if t[1] == "col" else 1)):
                new_end = end + d * outward
                lo = min(beam.lo_mm, new_end)
                hi = max(beam.hi_mm, new_end)
                if not any(clo <= lo and hi <= chi for clo, chi in chords):
                    continue
                if end_i == 0:
                    beam.lo_mm = new_end
                else:
                    beam.hi_mm = new_end
                supports = list(beam.supports)
                supports[end_i] = tag
                beam.supports = (supports[0], supports[1])
                beam.note = (beam.note + "+extended").lstrip("+")
                return True
        return False

    def _stub_repair(self, storey: int, beam: _PBeam, beams: List[_PBeam]) -> bool:
        """Bracket the deep end from a parallel column line within reach."""
        reach_mm = _mm(REFUSE_CANTILEVER_M)
        for end_i in self._deep_ends(beam, beams):
            end = beam.lo_mm if end_i == 0 else beam.hi_mm
            x = end if beam.orient == "h" else beam.pos_mm
            y = beam.pos_mm if beam.orient == "h" else end
            best = None  # type: Optional[Tuple[int, int, int]]
            for s in self.stacks:
                if storey not in s.exists:
                    continue
                if beam.orient == "h":
                    along_off = abs(s.x_mm - x)
                    lateral = abs(s.y_mm - y)
                    cross = s.y_mm
                else:
                    along_off = abs(s.y_mm - y)
                    lateral = abs(s.x_mm - x)
                    cross = s.x_mm
                if along_off <= _ON_LINE_TOL_MM and _ON_LINE_TOL_MM < lateral <= reach_mm:
                    if best is None or lateral < best[0]:
                        best = (lateral, cross, end)
            if best is None:
                continue
            _lateral, cross, along = best
            beams.append(
                _PBeam(
                    level_key=beam.level_key,
                    level_rank=beam.level_rank,
                    storey=storey,
                    kind=BeamKind.CANTILEVER,
                    orient="v" if beam.orient == "h" else "h",
                    pos_mm=along,
                    lo_mm=min(cross, beam.pos_mm),
                    hi_mm=max(cross, beam.pos_mm),
                    supports=("col", "tip"),
                    chain=1,
                    note="link_stub",
                )
            )
            supports = list(beam.supports)
            supports[end_i] = "stub"
            beam.supports = (supports[0], supports[1])
            return True
        return False

    def _refresh_end_supports(self, beams: Sequence[_PBeam]) -> None:
        """Resolve endpoints against the complete level, not insertion order.

        Slab feedback can append a receiving beam after its dependent beam.
        Keeping the dependent's earlier ``free`` tag hides its actual bearing
        depth from the repair ladder. Fill unassigned feedback ends after
        assembly and repairs; preserve bearings resolved by the separate
        wall/core placement routines (including offset/joint-zone stations).
        This is connectivity bookkeeping, not a successful analysis claim.
        """
        for beam in beams:
            if beam.kind in self._FIXED_KINDS or not beam.note.startswith("slab_feedback"):
                continue
            beam.supports = tuple(
                self._end_support_tag(beam, end, beams) if tag == "free" else tag
                for end, tag in zip((beam.lo_mm, beam.hi_mm), beam.supports)
            )

    def _end_support_tag(self, beam: _PBeam, end_mm: int, beams: Sequence[_PBeam]) -> str:
        """What a beam end lands on: a column, a crossing beam, or nothing."""
        x = end_mm if beam.orient == "h" else beam.pos_mm
        y = beam.pos_mm if beam.orient == "h" else end_mm
        for s in self.stacks:
            if beam.storey in s.exists and abs(s.x_mm - x) <= _ON_LINE_TOL_MM and abs(s.y_mm - y) <= _ON_LINE_TOL_MM:
                return "col"
        perp = "v" if beam.orient == "h" else "h"
        for other in beams:
            if other.orient != perp:
                continue
            cross = x if perp == "v" else y
            along = y if perp == "v" else x
            if abs(other.pos_mm - cross) <= 60 and other.lo_mm - 60 <= along <= other.hi_mm + 60:
                return "beam"
        return "free"

    def _support_depth(self, beam: _PBeam, end_mm: int, beams: Sequence[_PBeam]) -> int:
        """Depth of the shallowest member crossing under a beam end.

        A link stub counts as a column bracket (0); every other beam counts its
        own chain. No crossing at all reads as 1 (unknown, pessimistic).
        """
        perp = "v" if beam.orient == "h" else "h"
        point = (end_mm, beam.pos_mm) if beam.orient == "h" else (beam.pos_mm, end_mm)
        best = None  # type: Optional[int]
        for other in beams:
            if other is beam or other.orient != perp:
                continue
            along = point[0] if perp == "h" else point[1]
            cross = point[1] if perp == "h" else point[0]
            if abs(other.pos_mm - cross) <= 60 and other.lo_mm - 60 <= along <= other.hi_mm + 60:
                depth = 0 if other.note == "link_stub" else other.chain
                if best is None or depth < best:
                    best = depth
        return 1 if best is None else best

    def _promote_support(self, storey: int, beam: _PBeam, beams: List[_PBeam]) -> bool:
        """One repair: raise the deep bearing point to a column stack (full checks)."""
        view = self.view
        for end_i in (0, 1):
            if beam.supports[end_i] != "beam":
                continue
            end = beam.lo_mm if end_i == 0 else beam.hi_mm
            x = end if beam.orient == "h" else beam.pos_mm
            y = beam.pos_mm if beam.orient == "h" else end
            if not all(view.covers(s, x, y) for s in range(0, storey + 1)):
                continue
            if view.door_conflicts(x, y, range(0, storey + 1)):
                continue
            if view.corridor_strictly_inside(x, y, range(0, storey + 1), self.state.snap_wall_mm) is not None:
                continue
            if any(max(abs(s.x_mm - x), abs(s.y_mm - y)) < MERGE_FLOOR_MM for s in self.stacks):
                continue  # the 1.2 m floor binds promoted columns too
            exists = _existing_storeys(view, x, y)
            if not view.housing_wall_allowed(x, y, exists):
                continue
            stack = _Stack(
                x_mm=x,
                y_mm=y,
                anchor=0,
                origin="promoted",
                exists=exists,
                top=max(exists),
                base=0,
                score=Fraction(0),
                support=["s%d:promoted" % s for s in exists],
                placed_by="placement.frame.promoted",
            )
            stack.axis_x = _axis_at(view.grid.x_axes, x, _AXIS_MATCH_TOL_MM)
            stack.axis_y = _axis_at(view.grid.y_axes, y, _AXIS_MATCH_TOL_MM)
            self.stacks.append(stack)
            self.stacks.sort(key=lambda s: (s.x_mm, s.y_mm))
            supports = list(beam.supports)
            supports[end_i] = "col"
            beam.supports = (supports[0], supports[1])
            return True
        return False


# ---------------------------------------------------------------------------
# panelization (spec 5.5): planar face tracing on integer mm segments
# ---------------------------------------------------------------------------


@dataclass
class _Panel:
    level: int
    outline_mm: List[Tuple[int, int]]
    region: _Footprint
    kind: str = "slab"
    rect_mm: Tuple[int, int, int, int] = (0, 0, 0, 0)
    lx_mm: int = 0
    ly_mm: int = 0
    irregular: bool = False
    span_dir: str = "x"
    two_way: bool = True
    edge_support: List[str] = field(default_factory=list)
    edge_cont: List[bool] = field(default_factory=list)
    t_mm: Optional[int] = None
    marked: bool = False
    id: str = ""

    def area_mm2(self) -> int:
        return sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in self.region.rects)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "level": int(self.level),
            "kind": self.kind,
            "outline_m": [[_m(x), _m(y)] for x, y in self.outline_mm],
            "lx_m": _m(self.lx_mm),
            "ly_m": _m(self.ly_mm),
            "two_way": bool(self.two_way),
            "span_dir": self.span_dir,
            "t_mm": None if self.t_mm is None else int(self.t_mm),
            "edge_support": list(self.edge_support),
            "edge_continuity": [bool(v) for v in self.edge_cont],
            "irregular": bool(self.irregular),
        }


def _trace_faces(segments: Sequence[Tuple[int, int, int, int]]) -> List[List[Tuple[int, int]]]:
    """Positive-area faces of the axis-aligned planar subdivision.

    Half-edges sorted by (node, direction); the next half-edge maximizes the
    clockwise turn code, which makes bounded faces positive under the y-down
    shoelace; the outer face is negative and dropped (spec 5.5).
    """
    verticals = {}  # type: Dict[int, List[Tuple[int, int]]]
    horizontals = {}  # type: Dict[int, List[Tuple[int, int]]]
    for x1, y1, x2, y2 in segments:
        if x1 == x2 and y1 != y2:
            verticals.setdefault(x1, []).append((min(y1, y2), max(y1, y2)))
        elif y1 == y2 and x1 != x2:
            horizontals.setdefault(y1, []).append((min(x1, x2), max(x1, x2)))
    for x in verticals:
        verticals[x] = _merge_intervals(verticals[x])
    for y in horizontals:
        horizontals[y] = _merge_intervals(horizontals[y])

    adj = {}  # type: Dict[Tuple[int, int], Set[int]]

    def _connect(a: Tuple[int, int], b: Tuple[int, int], dir_code: int) -> None:
        adj.setdefault(a, set()).add(dir_code)
        adj.setdefault(b, set()).add((dir_code + 2) % 4)

    edge_map = {}  # type: Dict[Tuple[Tuple[int, int], int], Tuple[int, int]]
    for x in sorted(verticals):
        for lo, hi in verticals[x]:
            cuts = {lo, hi}
            for y in horizontals:
                if lo <= y <= hi:
                    for hlo, hhi in horizontals[y]:
                        if hlo <= x <= hhi:
                            cuts.add(y)
                            break
            points = sorted(cuts)
            for i in range(len(points) - 1):
                a, b = (x, points[i]), (x, points[i + 1])
                _connect(a, b, 1)  # S
                edge_map[(a, 1)] = b
                edge_map[(b, 3)] = a
    for y in sorted(horizontals):
        for lo, hi in horizontals[y]:
            cuts = {lo, hi}
            for x in verticals:
                if lo <= x <= hi:
                    for vlo, vhi in verticals[x]:
                        if vlo <= y <= vhi:
                            cuts.add(x)
                            break
            points = sorted(cuts)
            for i in range(len(points) - 1):
                a, b = (points[i], y), (points[i + 1], y)
                _connect(a, b, 0)  # E
                edge_map[(a, 0)] = b
                edge_map[(b, 2)] = a

    visited = set()  # type: Set[Tuple[Tuple[int, int], int]]
    faces = []  # type: List[List[Tuple[int, int]]]
    for start in sorted(edge_map):
        if start in visited:
            continue
        loop = []  # type: List[Tuple[int, int]]
        node, dir_code = start
        guard = 0
        while True:
            visited.add((node, dir_code))
            loop.append(node)
            node = edge_map[(node, dir_code)]
            rev = (dir_code + 2) % 4
            options = adj.get(node, set())
            best = None  # type: Optional[Tuple[int, int]]
            for cand in options:
                delta = (cand - rev) % 4
                if delta == 0:
                    continue
                if best is None or delta > best[0]:
                    best = (delta, cand)
            dir_code = best[1] if best is not None else rev
            guard += 1
            if (node, dir_code) == start or guard > 100000:
                break
        area2 = 0
        for i in range(len(loop)):
            x1, y1 = loop[i]
            x2, y2 = loop[(i + 1) % len(loop)]
            area2 += x1 * y2 - x2 * y1
        if area2 > 0:
            faces.append(loop)
    return faces


def _clean_loop(loop: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Remove spur traversals (p, q, p) then collapse collinear runs."""
    points = list(loop)
    changed = True
    while changed and len(points) > 3:
        changed = False
        for i in range(len(points)):
            prev = points[(i - 1) % len(points)]
            nxt = points[(i + 1) % len(points)]
            if prev == nxt:
                kill = sorted(((i, points[i]), ((i + 1) % len(points), nxt)))
                for index, _ in sorted(kill, key=lambda p: -p[0]):
                    points.pop(index)
                changed = True
                break
    out = []  # type: List[Tuple[int, int]]
    count = len(points)
    for i in range(count):
        prev = points[(i - 1) % count]
        here = points[i]
        nxt = points[(i + 1) % count]
        dx1, dy1 = here[0] - prev[0], here[1] - prev[1]
        dx2, dy2 = nxt[0] - here[0], nxt[1] - here[1]
        if dx1 * dy2 - dx2 * dy1 == 0 and (dx1 or dy1) and (dx2 or dy2):
            same_dir = (dx1 > 0) == (dx2 > 0) and (dy1 > 0) == (dy2 > 0) and (dx1 < 0) == (dx2 < 0) and (dy1 < 0) == (dy2 < 0)
            if same_dir:
                continue
        out.append(here)
    return out


def _region_rect_area(region: _Footprint, rect: Tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = rect
    total = 0
    for rx0, ry0, rx1, ry1 in region.rects:
        total += _overlap(x0, x1, rx0, rx1) * _overlap(y0, y1, ry0, ry1)
    return total


def _largest_inscribed_rect(region: _Footprint, outline: Sequence[Tuple[int, int]]) -> Tuple[int, int, int, int]:
    # grid coordinates come from the region decomposition, so hole boundaries
    # (a ring panel around a shaft) are candidate rect edges too
    xs = sorted({p[0] for p in outline} | {r[0] for r in region.rects} | {r[2] for r in region.rects})
    ys = sorted({p[1] for p in outline} | {r[1] for r in region.rects} | {r[3] for r in region.rects})
    best = None  # type: Optional[Tuple[int, Tuple[int, int, int, int]]]
    for i in range(len(xs) - 1):
        for j in range(i + 1, len(xs)):
            for k in range(len(ys) - 1):
                for l in range(k + 1, len(ys)):
                    rect = (xs[i], ys[k], xs[j], ys[l])
                    area = (rect[2] - rect[0]) * (rect[3] - rect[1])
                    if area <= 0:
                        continue
                    if best is not None and area <= best[0]:
                        continue
                    if _region_rect_area(region, rect) == area:
                        best = (area, rect)
    if best is None:
        x0 = min(p[0] for p in outline)
        y0 = min(p[1] for p in outline)
        return (x0, y0, x0, y0)
    return best[1]


class _Panelizer:
    def __init__(self, view: _View, state: _ColumnState, params: FrameParams, log: DisclosureLog, framer: _Framer):
        self.view = view
        self.state = state
        self.params = params
        self.log = log
        self.framer = framer
        self.irregular_logged = set()  # type: Set[str]
        self.slab_t_max = max(
            int(round(float(params.slab_t_max_mm))),
            int(round(RC_SLAB_MIN_THICKNESS_MM)),
        )

    def panelize(self, storey: int, beams: Sequence[_PBeam]) -> List[_Panel]:
        footprint = self.view.grid.footprints.get(storey)
        if footprint is None or footprint.is_empty():
            return []
        segments = []  # type: List[Tuple[int, int, int, int]]
        for orient in ("v", "h"):
            for pos, lo, hi in footprint.boundary_lines(orient):
                if orient == "v":
                    segments.append((pos, lo, pos, hi))
                else:
                    segments.append((lo, pos, hi, pos))
        for beam in beams:
            (x1, y1), (x2, y2) = beam.points_mm()
            segments.append((x1, y1, x2, y2))
        faces = _trace_faces(segments)
        panels = []  # type: List[_Panel]
        for loop in faces:
            outline = _clean_loop(loop)
            if len(outline) < 4:
                continue
            region = _Footprint.from_polygons([outline])
            if region.is_empty():
                continue
            panels.append(_Panel(level=storey, outline_mm=outline, region=region))
        # hole assignment: a face wholly inside another is a hole in it (a ring
        # of slab around a shaft traces as its outer loop only), so the inner
        # face's region is cut out of the outer one before any measurement
        by_area = sorted(panels, key=lambda p: (-p.area_mm2(), p.outline_mm[0]))
        for i, big in enumerate(by_area):
            for small in by_area[i + 1:]:
                inter = sum(
                    _region_rect_area(big.region, rect) for rect in small.region.rects
                )
                if inter == small.area_mm2() and small.area_mm2() < big.area_mm2():
                    big.region = _Footprint(_rects_subtract(big.region.rects, small.region.rects))
        for panel in panels:
            self._classify(panel, storey)
            self._measure(panel)
        panels.sort(key=lambda p: (min(x for x, _ in p.outline_mm), min(y for _, y in p.outline_mm), p.area_mm2()))
        for index, panel in enumerate(panels):
            panel.id = slab_id(storey, index)
        for panel in panels:
            self._edges(panel, panels, beams, storey)
            self._thickness(panel)
        return panels

    def _classify(self, panel: _Panel, storey: int) -> None:
        area = panel.area_mm2()
        if area <= 0:
            return
        for cid in sorted(self.state.core_plan.core_rects_mm):
            rect = self.state.core_plan.core_rects_mm[cid]
            if storey not in self.state.core_plan.core_storeys.get(cid, []):
                continue
            overlap = _region_rect_area(panel.region, rect)
            if overlap * 2 > area:
                core = next((c for c in self.view.model.cores if c.id == cid), None)
                panel.kind = "stair" if core is not None and core.kind == CoreKind.STAIRS else "opening"
                return
        for rect in self.view.balconies.get(storey, []):
            if _region_rect_area(panel.region, rect) * 2 > area:
                panel.kind = "cantilever"
                return
        for rect in self.framer.overhangs.get(storey, []):
            if _region_rect_area(panel.region, rect) * 2 > area:
                panel.kind = "cantilever"
                return
        panel.kind = "slab"

    def _measure(self, panel: _Panel) -> None:
        xs = [p[0] for p in panel.outline_mm]
        ys = [p[1] for p in panel.outline_mm]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        if panel.area_mm2() == bbox_area:
            panel.rect_mm = bbox
            panel.irregular = False
        else:
            panel.rect_mm = _largest_inscribed_rect(panel.region, panel.outline_mm)
            panel.irregular = True
            if panel.kind == "slab" and panel.id not in self.irregular_logged:
                self.irregular_logged.add(panel.id)
        w = panel.rect_mm[2] - panel.rect_mm[0]
        h = panel.rect_mm[3] - panel.rect_mm[1]
        panel.lx_mm, panel.ly_mm = (w, h) if w <= h else (h, w)
        short_is_x = w <= h
        forced = str(self.params.span_direction or "auto").lower()
        if forced in ("x", "y"):
            panel.two_way = False
            panel.span_dir = forced
        else:
            panel.span_dir = "x" if short_is_x else "y"
            panel.two_way = panel.lx_mm > 0 and panel.ly_mm * 1 <= 2 * panel.lx_mm

    def _edges(self, panel: _Panel, panels: Sequence[_Panel], beams: Sequence[_PBeam], storey: int) -> None:
        supports = []  # type: List[str]
        conts = []  # type: List[bool]
        count = len(panel.outline_mm)
        for i in range(count):
            a = panel.outline_mm[i]
            b = panel.outline_mm[(i + 1) % count]
            if a[0] == b[0]:
                orient, pos = "v", a[0]
                lo, hi = min(a[1], b[1]), max(a[1], b[1])
            else:
                orient, pos = "h", a[1]
                lo, hi = min(a[0], b[0]), max(a[0], b[0])
            if _beam_covers(beams, orient, pos, lo, hi, 60):
                supports.append("beam")
            else:
                wall_cover = []  # type: List[Tuple[int, int]]
                for rec in self.view.walls.get(storey, []):
                    if rec.orient != orient:
                        continue
                    tol = max(rec.t_mm, self.view.default_t_mm) // 2
                    if abs(rec.pos_mm - pos) > tol:
                        continue
                    piece = (max(lo, rec.lo_mm), min(hi, rec.hi_mm))
                    if piece[1] > piece[0]:
                        wall_cover.append(piece)
                total = sum(h2 - l2 for l2, h2 in _merge_intervals(wall_cover))
                supports.append("wall" if total >= int(0.8 * (hi - lo)) else "free")
            mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
            if orient == "v":
                p1, p2 = (mid[0] - 10, mid[1]), (mid[0] + 10, mid[1])
            else:
                p1, p2 = (mid[0], mid[1] - 10), (mid[0], mid[1] + 10)
            outside = p2 if panel.region.covers(*p1) else p1
            cont = False
            for other in panels:
                if other is panel:
                    continue
                if other.region.covers(*outside):
                    cont = True
                    break
            conts.append(cont)
        panel.edge_support = supports
        panel.edge_cont = conts

    def _side_continuous(self, panel: _Panel, orient: str, pos: int) -> bool:
        count = len(panel.outline_mm)
        total = 0
        cont = 0
        for i in range(count):
            a = panel.outline_mm[i]
            b = panel.outline_mm[(i + 1) % count]
            if orient == "v" and a[0] == b[0] and abs(a[0] - pos) <= 60:
                length = abs(b[1] - a[1])
            elif orient == "h" and a[1] == b[1] and abs(a[1] - pos) <= 60:
                length = abs(b[0] - a[0])
            else:
                continue
            total += length
            if panel.edge_cont[i]:
                cont += length
        return total > 0 and cont * 2 >= total

    def _thickness(self, panel: _Panel) -> None:
        if panel.kind in ("opening", "stair"):
            panel.t_mm = None
            return
        clear = max(300, panel.lx_mm - SUPPORT_DEDUCT_MM)
        if panel.kind == "cantilever":
            ratio = 7
        else:
            if panel.span_dir == "x":
                ends = (("v", panel.rect_mm[0]), ("v", panel.rect_mm[2]))
            else:
                ends = (("h", panel.rect_mm[1]), ("h", panel.rect_mm[3]))
            continuous = sum(1 for orient, pos in ends if self._side_continuous(panel, orient, pos))
            ratio = (20, 23, 26)[continuous]
        panel.t_mm = max(
            int(round(RC_SLAB_MIN_THICKNESS_MM)),
            _ceil5(-(-clear // ratio)),
        )
        if panel.kind == "slab":
            panel.marked = panel.t_mm > self.slab_t_max or panel.lx_mm > PANEL_SHORT_TRIGGER_MM
        if panel.irregular and panel.kind == "slab":
            pass  # W_IRREG raised once ids are final, in run_frame_placement


# ---------------------------------------------------------------------------
# plinth, ties, sizing and ids
# ---------------------------------------------------------------------------


def _cluster_lines(coords: Sequence[int]) -> List[List[int]]:
    groups = []  # type: List[List[int]]
    for coord in sorted(coords):
        if groups and coord - groups[-1][-1] <= _ON_LINE_TOL_MM:
            groups[-1].append(coord)
        else:
            groups.append([coord])
    return groups


def _connect_level(
    stacks: Sequence[_Stack],
    footprint: Optional[_Footprint],
    level_key: str,
    kind: BeamKind,
    note: str,
) -> List[_PBeam]:
    """Full connectivity beams (plinth / tie) between ground columns."""
    beams = []  # type: List[_PBeam]
    rank = _level_rank(level_key)
    ground = [s for s in stacks if 0 in s.exists and not s.transfer]
    for vertical in (True, False):
        coords = [s.x_mm if vertical else s.y_mm for s in ground]
        for group in _cluster_lines(coords):
            rep = group[0]
            on_line = sorted(
                (s.y_mm if vertical else s.x_mm)
                for s in ground
                if abs((s.x_mm if vertical else s.y_mm) - rep) <= _ON_LINE_TOL_MM
            )
            chords = footprint.chords_mm("v" if vertical else "h", rep) if footprint is not None else []
            for i in range(len(on_line) - 1):
                lo, hi = on_line[i], on_line[i + 1]
                if hi - lo < 50:
                    continue
                if chords and not any(clo <= lo and hi <= chi for clo, chi in chords):
                    continue
                beams.append(
                    _PBeam(
                        level_key=level_key,
                        level_rank=rank,
                        storey=0,
                        kind=kind,
                        orient="v" if vertical else "h",
                        pos_mm=rep,
                        lo_mm=lo,
                        hi_mm=hi,
                        width_mm=230,
                        depth_mm=300,
                        supports=("col", "col"),
                        chain=1,
                        note=note,
                    )
                )
    beams.sort(key=lambda b: (b.orient, b.pos_mm, b.lo_mm))
    return beams


def _size_beams(beams: List[_PBeam]) -> None:
    for beam in beams:
        if beam.kind in (BeamKind.PLINTH, BeamKind.TIE):
            beam.width_mm, beam.depth_mm = 230, 300
            continue
        if beam.core_id is not None:
            continue  # cores pre-sized their beams
        span = beam.span_mm
        if beam.kind == BeamKind.CANTILEVER:
            beam.depth_mm = max(300, _ceil25(-(-span // 6)))
            beam.width_mm = 230
        elif beam.kind == BeamKind.SPANDREL:
            beam.width_mm, beam.depth_mm = 230, 300
        else:
            depth = _ceil25(-(-span // 12))
            beam.depth_mm = min(750, max(300, depth))
            beam.width_mm = 300 if span > 6000 else 230
    # constructability: a contiguous primary run takes the max depth of its spans
    runs = {}  # type: Dict[Tuple[str, str, int], List[_PBeam]]
    for beam in beams:
        if beam.kind != BeamKind.PRIMARY:
            continue
        runs.setdefault((beam.level_key, beam.orient, beam.pos_mm), []).append(beam)
    for key in sorted(runs):
        chain = sorted(runs[key], key=lambda b: b.lo_mm)
        group = []  # type: List[_PBeam]
        prev_hi = None  # type: Optional[int]
        for beam in chain + [None]:  # type: ignore[list-item]
            if beam is not None and (prev_hi is None or abs(beam.lo_mm - prev_hi) <= 10):
                group.append(beam)
                prev_hi = beam.hi_mm
                continue
            if group:
                depth = max(b.depth_mm for b in group)
                width = max(b.width_mm for b in group)
                for member in group:
                    member.depth_mm = depth
                    member.width_mm = width
            if beam is not None:
                group = [beam]
                prev_hi = beam.hi_mm
            else:
                group = []


def _split_beams_at_columns(beams: Sequence[_PBeam], stacks: Sequence[_Stack]) -> List[_PBeam]:
    """Make every interior column station an explicit beam-fragment end.

    Architectural wall duty and slab-feedback repair can create one long
    drawing fragment across several already-selected grid columns.  The
    BeamRun analysis understands the intermediate supports, but a member row
    and its reinforcement schedule need a fragment boundary there so the
    internal support moment is not hidden inside one endpoint/midpoint row.
    """
    out = []  # type: List[_PBeam]
    for beam in beams:
        cuts = []  # type: List[int]
        for stack in stacks:
            if beam.storey not in stack.exists:
                continue
            across = stack.y_mm if beam.orient == "h" else stack.x_mm
            along = stack.x_mm if beam.orient == "h" else stack.y_mm
            if abs(across - beam.pos_mm) > _ON_LINE_TOL_MM:
                continue
            if beam.lo_mm + 10 < along < beam.hi_mm - 10:
                cuts.append(int(along))
        stations = [beam.lo_mm] + sorted(set(cuts)) + [beam.hi_mm]
        if len(stations) == 2:
            out.append(beam)
            continue
        for index, (lo, hi) in enumerate(zip(stations[:-1], stations[1:])):
            out.append(
                _PBeam(
                    level_key=beam.level_key,
                    level_rank=beam.level_rank,
                    storey=beam.storey,
                    kind=beam.kind,
                    orient=beam.orient,
                    pos_mm=beam.pos_mm,
                    lo_mm=lo,
                    hi_mm=hi,
                    width_mm=beam.width_mm,
                    depth_mm=beam.depth_mm,
                    under_wall=beam.under_wall,
                    supports=(
                        beam.supports[0] if index == 0 else "col",
                        beam.supports[1] if index == len(stations) - 2 else "col",
                    ),
                    chain=beam.chain,
                    core_id=beam.core_id,
                    note=beam.note,
                    key=(beam.key + ":colsplit:%d" % index) if beam.key else "colsplit:%d" % index,
                    line_label=beam.line_label,
                    axis_ref=beam.axis_ref,
                )
            )
    return sorted(out, key=lambda b: (b.storey, b.level_rank, b.orient, b.pos_mm, b.lo_mm, b.hi_mm, b.kind.value))


def _assign_beam_ids(beams: List[_PBeam], grid: AxisGrid) -> None:
    for beam in beams:
        axes = grid.y_axes if beam.orient == "h" else grid.x_axes
        axis = _axis_at(axes, beam.pos_mm, _AXIS_MATCH_TOL_MM)
        if axis is not None:
            beam.line_label = axis.label
            beam.axis_ref = axis.id
        else:
            beam.line_label = "@" + pos_token(_m(beam.pos_mm))
            beam.axis_ref = None
    groups = {}  # type: Dict[Tuple[int, bool, str, str], List[_PBeam]]
    for beam in beams:
        plinth = beam.level_key == "P"
        dir_char = "y" if beam.orient == "h" else "x"
        groups.setdefault((beam.storey, plinth, dir_char, beam.line_label or ""), []).append(beam)
    for key in sorted(groups):
        storey, plinth, dir_char, label = key
        ordered = sorted(groups[key], key=lambda b: (b.level_rank, b.lo_mm, b.hi_mm, b.kind.value))
        for index, beam in enumerate(ordered):
            beam.id = beam_id(storey, dir_char, label, index, plinth=plinth)


# ---------------------------------------------------------------------------
# metrics + score (spec section 7, canonical; finding 33)
# ---------------------------------------------------------------------------


_HIST_BINS = ("lt_2_5", "2_5_3", "3_4", "4_5", "5_6", "6_7_5", "gt_7_5")


def _span_bin(span_mm: int) -> str:
    if span_mm < 2500:
        return "lt_2_5"
    if span_mm < 3000:
        return "2_5_3"
    if span_mm < 4000:
        return "3_4"
    if span_mm <= 5000:
        return "4_5"
    if span_mm < 6000:
        return "5_6"
    if span_mm <= 7500:
        return "6_7_5"
    return "gt_7_5"


def score_layout(
    view: _View,
    grid: AxisGrid,
    stacks: Sequence[_Stack],
    beams: Sequence[_PBeam],
    panels: Sequence[_Panel],
    shaft_walls: Sequence[ShaftWall],
    log: DisclosureLog,
) -> Dict[str, Any]:
    """The canonical metrics block plus the 0..100 integer score."""
    counts = {code: 0 for code in _HARD_CODES}
    for entry in log.entries:
        if entry.code in counts:
            counts[entry.code] += max(1, len(entry.element_ids))

    primary_spans = [b.span_mm for b in beams if b.kind == BeamKind.PRIMARY]
    histogram = {name: 0 for name in _HIST_BINS}
    for span in primary_spans:
        histogram[_span_bin(span)] += 1
    in_band = sum(1 for s in primary_spans if 2500 <= s <= 5000)
    pct_band = round(100.0 * in_band / len(primary_spans), 1) if primary_spans else 100.0
    histogram_out = dict(histogram)
    histogram_out["pct_in_2_5_to_5"] = pct_band

    axis_count = {
        "x": len(grid.x_axes),
        "y": len(grid.y_axes),
        "x_inserted": sum(1 for a in grid.x_axes if a.source.value == "inserted"),
        "y_inserted": sum(1 for a in grid.y_axes if a.source.value == "inserted"),
    }

    ecc = []  # type: List[int]
    for stack in stacks:
        best = None  # type: Optional[int]
        for storey in stack.exists:
            for rec in view.walls.get(storey, []):
                tol = _ECC_SEARCH_MM
                if rec.orient == "h":
                    if rec.lo_mm - tol <= stack.x_mm <= rec.hi_mm + tol:
                        d = abs(stack.y_mm - rec.pos_mm)
                        if d <= tol and (best is None or d < best):
                            best = d
                else:
                    if rec.lo_mm - tol <= stack.y_mm <= rec.hi_mm + tol:
                        d = abs(stack.x_mm - rec.pos_mm)
                        if d <= tol and (best is None or d < best):
                            best = d
        if best is not None:
            ecc.append(best)
    ecc_mean = _round_ratio(sum(ecc), len(ecc)) if ecc else 0
    ecc_max = max(ecc) if ecc else 0

    torsion = _torsion_proxy(view, grid, stacks, shaft_walls)
    torsion_max = max(torsion["x"], torsion["y"])
    if torsion_max > 5.0:
        log.add(
            "W_TORSION",
            "stiffness centroid offset %.1f pct of the plan dimension (over 5 pct)" % torsion_max,
            (),
            stage=_STAGE_SCORE,
        )

    ground = grid.footprints.get(0)
    area_m2 = 0.0
    if ground is not None:
        area_m2 = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in ground.rects) / 1.0e6
    columns_per = round(100.0 * len(stacks) / area_m2, 2) if area_m2 > 0 else 0.0

    walls_total = 0
    walls_covered = 0
    for storey in view.storeys:
        level_beams = [b for b in beams if b.level_key == _level_key(storey)]
        for rec in view.walls.get(storey, []):
            if not rec.qualifying:
                continue
            walls_total += 1
            lateral = max(60, rec.t_mm // 2)
            if _beam_covers(level_beams, rec.orient, rec.pos_mm, rec.lo_mm, rec.hi_mm, lateral, 0.98):
                walls_covered += 1
    beams_under = _round_ratio(100 * walls_covered, walls_total) if walls_total else 100

    load_path = 1 + max((b.chain for b in beams), default=0)

    hv = sum(counts.values())
    outside = sum(1 for s in primary_spans if s < 2500 or s > 5000)
    dims = _plan_dims_mm(grid)
    cap_mm = _mm(min(float(view.params.max_primary_span), HARD_MAX_SPAN_M))
    extra_axes = 0
    for dim_mm, count in ((dims[0], axis_count["x"]), (dims[1], axis_count["y"])):
        ideal = (-(-dim_mm // cap_mm) + 1) if dim_mm > 0 and cap_mm > 0 else count
        extra_axes += max(0, count - ideal)
    minimum_regular_grid_columns = None  # type: Optional[int]
    column_count_excess_pct = None  # type: Optional[float]
    if view.params.column_strategy == "economy_grid":
        nx = (-(-dims[0] // cap_mm) + 1) if dims[0] > 0 and cap_mm > 0 else len(grid.x_axes)
        ny = (-(-dims[1] // cap_mm) + 1) if dims[1] > 0 and cap_mm > 0 else len(grid.y_axes)
        minimum_regular_grid_columns = max(1, int(nx) * int(ny))
        column_count_excess_pct = round(
            100.0 * max(0, len(stacks) - minimum_regular_grid_columns) / minimum_regular_grid_columns,
            1,
        )
        # Stair openings, re-entrant corners and door avoidance can legitimately
        # add supports. Penalize the excess, not the small-building boundary
        # effect that makes every viable 30 x 40 ft grid exceed 7 columns/100m2.
        cdist = column_count_excess_pct / 10.0
    elif columns_per < 4.0:
        cdist = 4.0 - columns_per
    elif columns_per > 7.0:
        cdist = columns_per - 7.0
    else:
        cdist = 0.0

    score = 100
    score -= 30 * hv
    score -= min(10, int(round(0.5 * outside)))
    score -= min(8, extra_axes)
    score -= min(10, ecc_mean // 25)
    score -= min(10, int(round(2 * max(0.0, torsion_max - 5.0))))
    score -= min(8, int(round(2 * cdist)))
    if beams_under < 90:
        score -= min(10, (90 - beams_under) // 2)
    score = max(0, score)

    result = {
        "score": int(score),
        "score_version": (
            ECONOMY_SCORE_VERSION
            if view.params.column_strategy == "economy_grid"
            else SCORE_VERSION
        ),
        "hard_violations": counts,
        "span_histogram": histogram_out,
        "axis_count": axis_count,
        "column_eccentricity_mm": {"mean": int(ecc_mean), "max": int(ecc_max)},
        "torsion_proxy_pct": torsion,
        "columns_per_100m2": columns_per,
        "beams_under_walls_pct": int(beams_under),
        "load_path_depth": int(load_path),
    }
    if minimum_regular_grid_columns is not None:
        result["minimum_regular_grid_columns"] = minimum_regular_grid_columns
        result["column_count_excess_pct"] = column_count_excess_pct
        result["column_strategy"] = "economy_grid"
        result["candidate_generator"] = "economy_grid_v0"
    return result


def _plan_dims_mm(grid: AxisGrid) -> Tuple[int, int]:
    x0 = y0 = None  # type: Optional[int]
    x1 = y1 = None  # type: Optional[int]
    for storey in grid.storeys:
        footprint = grid.footprints.get(storey)
        if footprint is None:
            continue
        box = footprint.bbox_mm()
        if box is None:
            continue
        x0 = box[0] if x0 is None else min(x0, box[0])
        y0 = box[1] if y0 is None else min(y0, box[1])
        x1 = box[2] if x1 is None else max(x1, box[2])
        y1 = box[3] if y1 is None else max(y1, box[3])
    if x0 is None or x1 is None or y0 is None or y1 is None:
        return (0, 0)
    return (x1 - x0, y1 - y0)


def _torsion_proxy(
    view: _View,
    grid: AxisGrid,
    stacks: Sequence[_Stack],
    shaft_walls: Sequence[ShaftWall],
) -> Dict[str, float]:
    """|stiffness centroid - area centroid| per direction over the plan dimension.

    Weights are second-moment proxies: a column contributes dim_along^3 x
    dim_across per direction, a shaft wall L^3 x t along its run (dominant) and
    t^3 x L across it. A pure proxy, deterministic and unitless.
    """
    ground = grid.footprints.get(0)
    dims = _plan_dims_mm(grid)
    if ground is None or ground.is_empty() or dims[0] <= 0 or dims[1] <= 0:
        return {"x": 0.0, "y": 0.0}
    area = 0
    ax_sum = 0
    ay_sum = 0
    for x0, y0, x1, y1 in ground.rects:
        a = (x1 - x0) * (y1 - y0)
        area += a
        ax_sum += a * (x0 + x1) // 2
        ay_sum += a * (y0 + y1) // 2
    if area == 0:
        return {"x": 0.0, "y": 0.0}
    area_cx = ax_sum / area
    area_cy = ay_sum / area

    wx_sum = wy_sum = 0.0
    wx_tot = wy_tot = 0.0
    for stack in sorted(stacks, key=lambda s: (s.x_mm, s.y_mm)):
        along_x = stack.d_mm if stack.rot == 0 else stack.w_mm
        along_y = stack.w_mm if stack.rot == 0 else stack.d_mm
        wx = float(along_x) ** 3 * float(along_y)
        wy = float(along_y) ** 3 * float(along_x)
        wx_tot += wx
        wx_sum += wx * stack.x_mm
        wy_tot += wy
        wy_sum += wy * stack.y_mm
    for wall in sorted(shaft_walls, key=lambda w: w.id):
        run_x = abs(wall.b_mm[0] - wall.a_mm[0])
        run_y = abs(wall.b_mm[1] - wall.a_mm[1])
        t = float(wall.t_mm)
        cx = (wall.a_mm[0] + wall.b_mm[0]) / 2.0
        cy = (wall.a_mm[1] + wall.b_mm[1]) / 2.0
        wx = float(max(run_x, wall.t_mm)) ** 3 * t if run_x else t ** 3 * float(run_y)
        wy = float(max(run_y, wall.t_mm)) ** 3 * t if run_y else t ** 3 * float(run_x)
        wx_tot += wx
        wx_sum += wx * cx
        wy_tot += wy
        wy_sum += wy * cy
    if wx_tot <= 0 or wy_tot <= 0:
        return {"x": 0.0, "y": 0.0}
    off_x = abs(wx_sum / wx_tot - area_cx)
    off_y = abs(wy_sum / wy_tot - area_cy)
    return {
        "x": round(100.0 * off_x / dims[0], 1),
        "y": round(100.0 * off_y / dims[1], 1),
    }


# ---------------------------------------------------------------------------
# cantilever panel handoff
# ---------------------------------------------------------------------------


def _panel_edge_line(panel: _Panel, index: int) -> Tuple[str, int, int, int]:
    """(orientation, station, low, high) for one panel outline edge."""
    a = panel.outline_mm[index]
    b = panel.outline_mm[(index + 1) % len(panel.outline_mm)]
    if a[0] == b[0]:
        return ("v", a[0], min(a[1], b[1]), max(a[1], b[1]))
    return ("h", a[1], min(a[0], b[0]), max(a[0], b[0]))


def _panel_edge_side(panel: _Panel, index: int) -> Optional[str]:
    """Canonical bounding-box side occupied by an outline edge, if any."""
    orient, pos, _lo, _hi = _panel_edge_line(panel, index)
    xs = [point[0] for point in panel.outline_mm]
    ys = [point[1] for point in panel.outline_mm]
    if orient == "v":
        if pos == min(xs):
            return "x_min"
        if pos == max(xs):
            return "x_max"
    else:
        if pos == min(ys):
            return "y_min"
        if pos == max(ys):
            return "y_max"
    return None


def _edge_outside_point(panel: _Panel, index: int) -> Tuple[int, int]:
    """Point ten millimetres across an edge, on the side outside panel."""
    a = panel.outline_mm[index]
    b = panel.outline_mm[(index + 1) % len(panel.outline_mm)]
    mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
    if a[0] == b[0]:
        first, second = (mid[0] - 10, mid[1]), (mid[0] + 10, mid[1])
    else:
        first, second = (mid[0], mid[1] - 10), (mid[0], mid[1] + 10)
    return second if panel.region.covers(*first) else first


def _edge_support_ids(
    panel: _Panel,
    index: int,
    beams: Sequence[_PBeam],
    walls: Sequence[Any],
) -> List[str]:
    """Resolved beam or wall ids covering at least 80 percent of an edge."""
    support = panel.edge_support[index] if index < len(panel.edge_support) else "free"
    if support == "free":
        return []
    orient, pos, lo, hi = _panel_edge_line(panel, index)
    if hi <= lo:
        return []
    pieces = []  # type: List[Tuple[int, int]]
    ids = []  # type: List[str]
    if support == "beam":
        for beam in beams:
            if (
                beam.storey != panel.level
                or beam.level_key != str(panel.level)
                or beam.kind == BeamKind.PLINTH
                or beam.orient != orient
                or abs(beam.pos_mm - pos) > 60
            ):
                continue
            piece = (max(lo, beam.lo_mm), min(hi, beam.hi_mm))
            if piece[1] <= piece[0]:
                continue
            pieces.append(piece)
            if beam.id:
                ids.append(str(beam.id))
    elif support == "wall":
        for wall in walls:
            if int(getattr(wall, "storey", -1)) != panel.level:
                continue
            role = getattr(wall, "role", "")
            if str(getattr(role, "value", role)) == WallRole.RAILING.value:
                continue
            a = getattr(wall, "a", (0.0, 0.0))
            b = getattr(wall, "b", (0.0, 0.0))
            ax, ay, bx, by = _mm(a[0]), _mm(a[1]), _mm(b[0]), _mm(b[1])
            wall_orient = "v" if ax == bx else "h" if ay == by else ""
            if wall_orient != orient:
                continue
            wall_pos = ax if orient == "v" else ay
            tolerance = max(60, _mm(float(getattr(wall, "thickness_m", 0.0))) // 2)
            if abs(wall_pos - pos) > tolerance:
                continue
            wall_lo, wall_hi = (min(ay, by), max(ay, by)) if orient == "v" else (min(ax, bx), max(ax, bx))
            piece = (max(lo, wall_lo), min(hi, wall_hi))
            if piece[1] <= piece[0]:
                continue
            pieces.append(piece)
            wall_id = str(getattr(wall, "id", ""))
            if wall_id:
                ids.append(wall_id)
    covered = sum(end - start for start, end in _merge_intervals(pieces))
    if covered * 5 < 4 * (hi - lo):
        return []
    return sorted(set(ids))


def _room_region_mm(room: Any) -> _Footprint:
    """A source room polygon in the placement module's integer geometry."""
    points = [(_mm(float(x)), _mm(float(y))) for x, y in getattr(room, "polygon", [])]
    return _Footprint.from_polygons([points]) if len(points) >= 3 else _Footprint([])


def _edge_region_coverage_mm(
    panel: _Panel,
    index: int,
    regions: Sequence[_Footprint],
) -> int:
    """Length of one edge backed by the supplied room regions."""
    orient, _pos, lo, hi = _panel_edge_line(panel, index)
    probe = _edge_outside_point(panel, index)
    pieces = []  # type: List[Tuple[int, int]]
    for region in regions:
        for x0, y0, x1, y1 in region.rects:
            if orient == "v":
                if x0 <= probe[0] <= x1:
                    piece = (max(lo, y0), min(hi, y1))
                else:
                    continue
            else:
                if y0 <= probe[1] <= y1:
                    piece = (max(lo, x0), min(hi, x1))
                else:
                    continue
            if piece[1] > piece[0]:
                pieces.append(piece)
    return sum(end - start for start, end in _merge_intervals(pieces))


def _balcony_root_side(panel: _Panel, rooms: Sequence[Any]) -> Optional[str]:
    """Root side implied by normalized balcony and occupied-room regions.

    The source occupancy describes intent. Generated perimeter beams describe
    framing, and may surround a partial-width balcony without turning its slab
    strip into an ordinary supported panel.
    """
    if panel.kind != "cantilever":
        return None
    balcony_regions = []  # type: List[_Footprint]
    backing_regions = []  # type: List[_Footprint]
    for room in rooms:
        if int(getattr(room, "storey", -1)) != panel.level:
            continue
        occupancy = getattr(room, "occupancy", "")
        value = str(getattr(occupancy, "value", occupancy))
        region = _room_region_mm(room)
        if region.is_empty():
            continue
        if value == Occupancy.BALCONY.value:
            balcony_regions.append(region)
        elif value not in (Occupancy.VOID.value, Occupancy.GREEN.value):
            backing_regions.append(region)
    overlap = sum(
        _region_rect_area(panel.region, rect)
        for region in balcony_regions
        for rect in region.rects
    )
    if overlap * 2 <= panel.area_mm2() or not backing_regions:
        return None
    totals = {}  # type: Dict[str, List[int]]
    for index in range(len(panel.outline_mm)):
        side = _panel_edge_side(panel, index)
        if side is None:
            continue
        _orient, _pos, lo, hi = _panel_edge_line(panel, index)
        row = totals.setdefault(side, [0, 0])
        row[0] += hi - lo
        row[1] += _edge_region_coverage_mm(panel, index, backing_regions)
    candidates = sorted(
        side
        for side, (length, covered) in totals.items()
        if length > 0 and covered * 5 >= length * 4
    )
    return candidates[0] if len(candidates) == 1 else None


def _vertical_support_ids_at_point(
    panel: _Panel,
    point: Tuple[int, int],
    stacks: Sequence[_Stack],
    walls: Sequence[Any],
) -> List[str]:
    """Actual column-stack or structural-wall ids supporting one beam end."""
    x_mm, y_mm = point
    ids = []  # type: List[str]
    for stack in stacks:
        if panel.level not in stack.exists:
            continue
        if abs(stack.x_mm - x_mm) <= _ON_LINE_TOL_MM and abs(stack.y_mm - y_mm) <= _ON_LINE_TOL_MM:
            if stack.id:
                ids.append(str(stack.id))
    for wall in walls:
        if int(getattr(wall, "storey", -1)) != panel.level:
            continue
        role = getattr(wall, "role", "")
        role_value = str(getattr(role, "value", role))
        if role_value != WallRole.CORE.value:
            continue
        axis = wall_axis(wall)
        if axis is None:
            continue
        orient, pos_m, lo_m, hi_m = axis
        pos, lo, hi = _mm(pos_m), _mm(lo_m), _mm(hi_m)
        tolerance = max(60, _mm(float(getattr(wall, "thickness_m", 0.0))) // 2)
        cross = x_mm if orient == "v" else y_mm
        along = y_mm if orient == "v" else x_mm
        if abs(cross - pos) <= tolerance and lo - tolerance <= along <= hi + tolerance:
            wall_id = str(getattr(wall, "id", ""))
            if wall_id:
                ids.append(wall_id)
    return sorted(set(ids))


def _edge_independent_vertical_support(
    panel: _Panel,
    side: str,
    beams: Sequence[_PBeam],
    stacks: Sequence[_Stack],
    walls: Sequence[Any],
) -> Tuple[bool, Dict[str, Tuple[List[str], List[str]]]]:
    """Whether a side is carried by members with real vertical supports.

    A beam kind or its cached support tags are insufficient evidence. Each
    contributing floor beam must resolve actual support ids at both endpoints.
    """
    edge_length = 0
    covered = []  # type: List[Tuple[int, int]]
    evidence = {}  # type: Dict[str, Tuple[List[str], List[str]]]
    for index in range(len(panel.outline_mm)):
        if _panel_edge_side(panel, index) != side:
            continue
        orient, pos, lo, hi = _panel_edge_line(panel, index)
        edge_length += hi - lo
        for beam in beams:
            if (
                beam.storey != panel.level
                or beam.level_key != str(panel.level)
                or beam.kind == BeamKind.PLINTH
                or beam.orient != orient
                or abs(beam.pos_mm - pos) > 60
            ):
                continue
            piece = (max(lo, beam.lo_mm), min(hi, beam.hi_mm))
            if piece[1] <= piece[0]:
                continue
            a, b = beam.points_mm()
            left = _vertical_support_ids_at_point(panel, a, stacks, walls)
            right = _vertical_support_ids_at_point(panel, b, stacks, walls)
            if not left or not right:
                continue
            covered.append(piece)
            if beam.id:
                evidence[str(beam.id)] = (left, right)
    coverage = sum(end - start for start, end in _merge_intervals(covered))
    return (edge_length > 0 and coverage * 5 >= edge_length * 4, evidence)


def _backspan_mm(panel: _Panel, backing: _Panel, side: str) -> int:
    """Available adjacent slab length normal to the cantilever root."""
    x0, y0, x1, y1 = panel.rect_mm
    bx0, by0, bx1, by1 = backing.rect_mm
    if side == "x_min":
        return max(0, x0 - bx0)
    if side == "x_max":
        return max(0, bx1 - x1)
    if side == "y_min":
        return max(0, y0 - by0)
    if side == "y_max":
        return max(0, by1 - y1)
    return 0


def _cantilever_handoff(
    panel: _Panel,
    panels: Sequence[_Panel],
    beams: Sequence[_PBeam],
    walls: Sequence[Any],
    root_side: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve the unique root support and adjacent regular backing panel.

    A root must be both supported and continuous into a regular slab.  Merely
    finding one supported perimeter edge does not establish the negative-
    moment load path or somewhere to develop the top bars.
    """
    empty = {
        "backing_edge": None,
        "backing_support_ids": [],
        "backing_panel_id": None,
        "backspan_m": None,
    }  # type: Dict[str, Any]
    if panel.kind != "cantilever":
        return empty

    roots = {}  # type: Dict[Tuple[str, str], Dict[str, Any]]
    for index in range(len(panel.outline_mm)):
        if index >= len(panel.edge_cont) or not panel.edge_cont[index]:
            continue
        side = _panel_edge_side(panel, index)
        if side is None:
            continue
        if root_side is not None and side != root_side:
            continue
        support_ids = _edge_support_ids(panel, index, beams, walls)
        if not support_ids:
            continue
        _orient, _pos, lo, hi = _panel_edge_line(panel, index)
        adjacent = [
            other
            for other in panels
            if other is not panel
            and other.level == panel.level
            and other.kind == "slab"
            and _edge_region_coverage_mm(panel, index, [other.region]) * 5
            >= (hi - lo) * 4
        ]
        if len(adjacent) != 1:
            continue
        backing = adjacent[0]
        available = _backspan_mm(panel, backing, side)
        if available <= 0:
            continue
        key = (side, backing.id)
        root = roots.setdefault(
            key,
            {
                "backing_edge": side,
                "backing_support_ids": [],
                "backing_panel_id": backing.id,
                "backspan_mm": available,
            },
        )
        root["backing_support_ids"] = sorted(
            set(root["backing_support_ids"]) | set(support_ids)
        )
        root["backspan_mm"] = min(int(root["backspan_mm"]), int(available))

    if len(roots) != 1:
        return empty
    root = roots[sorted(roots)[0]]
    return {
        "backing_edge": root["backing_edge"],
        "backing_support_ids": list(root["backing_support_ids"]),
        "backing_panel_id": root["backing_panel_id"],
        "backspan_m": _m(int(root["backspan_mm"])),
    }


# ---------------------------------------------------------------------------
# the result
# ---------------------------------------------------------------------------


@dataclass
class FrameResult:
    """Placement output; `write_back(model)` installs it on the StructuralModel."""

    grid: AxisGrid
    columns: List[_Stack] = field(default_factory=list)
    beams: List[_PBeam] = field(default_factory=list)
    panels: List[_Panel] = field(default_factory=list)
    shaft_walls: List[ShaftWall] = field(default_factory=list)
    stair_slabs: List[StairSlab] = field(default_factory=list)
    core_notes: List[Dict[str, Any]] = field(default_factory=list)
    params_echo: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    report: Dict[str, Any] = field(default_factory=dict)
    valid: bool = True
    log: DisclosureLog = field(default_factory=DisclosureLog)

    @property
    def axes(self) -> List[Axis]:
        return self.grid.axes()

    def beam_supports(self) -> List[Dict[str, Any]]:
        """Endpoint roles for the drawing; placement facts, not design verdicts."""
        return [
            {
                "id": beam.id,
                "storey": int(beam.storey),
                "level": beam.level_key,
                "ends": list(beam.supports),
                "chain": int(beam.chain),
            }
            for beam in sorted(self.beams, key=lambda member: member.id)
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axes": {
                "x": [a.to_dict() for a in self.grid.x_axes],
                "y": [a.to_dict() for a in self.grid.y_axes],
            },
            "columns": [s.to_dict() for s in self.columns],
            "beams": [b.to_dict() for b in self.beams],
            "panels": [p.to_dict() for p in self.panels],
            "shaft_walls": [w.to_dict() for w in self.shaft_walls],
            "stair_slabs": [s.to_dict() for s in self.stair_slabs],
            "core_notes": list(self.core_notes),
            "params": dict(self.params_echo),
            "metrics": self.metrics,
            "report": self.report,
            "valid": bool(self.valid),
        }

    def write_back(self, model: StructuralModel) -> StructuralModel:
        """Install axes, columns, beams and slabs on the model (placement owns them).

        Shaft walls, stair slabs, core notes, metrics and the report ride under
        `model.meta["frame_placement"]`; disclosures merge into model.warnings.
        """
        model.axes = self.grid.to_model_axes()
        columns = []  # type: List[Column]
        for stack in sorted(self.columns, key=lambda s: s.id):
            labels = None
            if stack.on_grid():
                labels = (stack.axis_x.label, stack.axis_y.label)
            for storey in sorted(stack.exists):
                if storey < stack.base or storey > stack.top:
                    continue
                if labels is not None:
                    cid = column_id(storey, labels[0], labels[1])
                else:
                    cid = column_id(storey, x_m=_m(stack.x_mm), y_m=_m(stack.y_mm))
                width_mm, depth_mm = stack.section_at(storey)
                columns.append(
                    Column(
                        id=cid,
                        stack_id=stack.id,
                        storey=storey,
                        x_m=_m(stack.x_mm),
                        y_m=_m(stack.y_mm),
                        width_m=_m(width_mm),
                        depth_m=_m(depth_mm),
                        rot=int(stack.rot),
                        on_grid=labels,
                        placed_by=stack.placed_by,
                    )
                )
        model.columns = columns
        beams = []  # type: List[Beam]
        for pb in sorted(self.beams, key=lambda b: b.id):
            (x1, y1), (x2, y2) = pb.points_mm()
            beams.append(
                Beam(
                    id=pb.id,
                    storey=int(pb.storey),
                    a=(_m(x1), _m(y1)),
                    b=(_m(x2), _m(y2)),
                    width_m=_m(pb.width_mm),
                    depth_m=_m(pb.depth_mm),
                    kind=pb.kind,
                    supports_wall_id=pb.under_wall,
                    placed_by="placement.frame." + (pb.note or pb.kind.value),
                )
            )
        model.beams = beams
        top_storey = max(self.grid.storeys) if self.grid.storeys else 0
        slabs = []  # type: List[SlabPanel]
        for panel in sorted(self.panels, key=lambda p: p.id):
            if panel.kind not in ("slab", "cantilever"):
                continue
            semantic_root = _balcony_root_side(panel, model.rooms)
            tip_supported = False
            if semantic_root is not None:
                tip_side = {
                    "x_min": "x_max",
                    "x_max": "x_min",
                    "y_min": "y_max",
                    "y_max": "y_min",
                }[semantic_root]
                tip_supported, _ = _edge_independent_vertical_support(
                    panel,
                    tip_side,
                    self.beams,
                    self.columns,
                    model.walls,
                )
            structural_cantilever = panel.kind == "cantilever" and not tip_supported
            cantilever = (
                _cantilever_handoff(
                    panel,
                    self.panels,
                    self.beams,
                    model.walls,
                    root_side=semantic_root,
                )
                if structural_cantilever
                else {
                    "backing_edge": None,
                    "backing_support_ids": [],
                    "backing_panel_id": None,
                    "backspan_m": None,
                }
            )
            edge_cont = {}
            for i, support in enumerate(panel.edge_support):
                cont = "cont" if (i < len(panel.edge_cont) and panel.edge_cont[i]) else "disc"
                edge_cont["e%d" % i] = support + ":" + cont
            slabs.append(
                SlabPanel(
                    id=panel.id,
                    storey=int(panel.level),
                    polygon=[(_m(x), _m(y)) for x, y in panel.outline_mm],
                    thickness_m=None if panel.t_mm is None else _m(panel.t_mm),
                    two_way=panel.two_way,
                    lx_m=_m(panel.lx_mm),
                    ly_m=_m(panel.ly_mm),
                    edge_continuity=edge_cont,
                    kind=SlabKind.ROOF if panel.level == top_storey else SlabKind.FLOOR,
                    support_ids=list(cantilever["backing_support_ids"]),
                    placed_by=(
                        "placement.frame.cantilever"
                        if structural_cantilever
                        else "placement.frame.balcony_supported"
                        if panel.kind == "cantilever"
                        else "placement.frame.slab"
                    ),
                    span_kind="cantilever" if structural_cantilever else "regular",
                    cantilever_backing_edge=cantilever["backing_edge"],
                    cantilever_backing_support_ids=list(cantilever["backing_support_ids"]),
                    cantilever_backing_panel_id=cantilever["backing_panel_id"],
                    cantilever_backspan_m=cantilever["backspan_m"],
                )
            )
        model.slabs = slabs
        model.meta["frame_placement"] = {
            "score_version": self.metrics.get("score_version", SCORE_VERSION),
            "valid": bool(self.valid),
            "metrics": self.metrics,
            "report": self.report,
            "shaft_walls": [w.to_dict() for w in self.shaft_walls],
            "stair_slabs": [s.to_dict() for s in self.stair_slabs],
            "core_notes": list(self.core_notes),
            # Retain this when analysis stops: the partial model still draws
            # these beams and must not lose the meaning of their endpoints.
            "beam_supports": self.beam_supports(),
        }
        merged = model.disclosure_log()
        merged.extend(self.log.entries)
        model.warnings = merged.entries
        return model


# ---------------------------------------------------------------------------
# the orchestrating pipeline
# ---------------------------------------------------------------------------


class _HousingEditRejected(Exception):
    """An optional search edit cannot pass the unchanged placement guards."""


def _housing_required(stack, state=None):
    return bool(
        stack.anchor or stack.origin in ("core", "corner", "corridor_proj")
        or stack.tie_keys or stack.corridor_pair_keys
        or any(axis is not None and axis.source.value in ("party", "corridor", "core")
               for axis in (stack.axis_x, stack.axis_y))
        or (state is not None and state.on_core_edge(stack.x_mm, stack.y_mm))
    )


def _housing_geometry(columns):
    return tuple(sorted((c.x_mm, c.y_mm, tuple(c.exists)) for c in columns))


def _housing_objective(columns, beams, min_span):
    """All same-storey Euclidean pairs, including corridor/core exceptions.

    Hard checks run separately first. Deficit, pair count, optional stacks,
    coordinate-line count (regularity), final beam length, canonical geometry
    give a total deterministic order. This is a bounded preliminary search.
    """
    ordered = sorted(columns, key=lambda c: (c.x_mm, c.y_mm))
    deficits = []
    for index, a in enumerate(ordered):
        for b in ordered[index + 1:]:
            if not set(a.exists).intersection(b.exists):
                continue
            distance = math.hypot(a.x_mm - b.x_mm, a.y_mm - b.y_mm) / 1000
            if 0 < distance < min_span - 1e-9:
                deficits.append(min_span - distance)
    return (
        round(sum(deficits), 6), len(deficits),
        # A support does not become a new mandatory anchor merely because a
        # trial puts it on a protected guide. Count the actual anchor/tie
        # provenance so repositioning cannot game the optional-stack count.
        sum(not (c.anchor or c.origin in ("core", "corner", "corridor_proj")
                 or c.tie_keys or c.corridor_pair_keys) for c in ordered),
        len({c.x_mm for c in ordered}) + len({c.y_mm for c in ordered}),
        sum(b.span_mm for b in beams), _housing_geometry(ordered),
    )


def _housing_preflight(model, result, params):
    """Use the production support topology before ranking a placed frame.

    This does not replace loads, member design or the final API audits.
    """
    from ..analysis.takedown import AnalysisError, _build_runs, _topo_order
    from .housing_variants import assess
    written = result.write_back(copy.deepcopy(model))
    audit = assess(written, params.min_span)
    okay = result.valid and not result.report["errors"] and bool(result.columns)
    okay = okay and not audit["off_wall_column_count"] and not audit["confirmed_room_intrusion_count"]
    okay = okay and audit["room_assessment"] == "assessed"
    maximum = 0.0
    try:
        for storey in written.storeys:
            runs = _build_runs(written, storey.index, DisclosureLog())
            beam_to_run = {beam.id: run for run in runs for beam in run.beams}
            # Production takedown solves floor runs and base plinth ties in
            # separate passes. They intentionally share coordinate run IDs.
            _topo_order([run for run in runs if not run.plinth], beam_to_run)
            _topo_order([run for run in runs if run.plinth], beam_to_run)
            for run in runs:
                if run.plinth:
                    continue
                maximum = max(maximum, max((hi - lo for lo, hi in run.spans), default=0.0))
                for overhang in (run.overhang_left, run.overhang_right):
                    if overhang and overhang[1] - overhang[0] > params.cantilever_cap + 1e-6:
                        okay = False
        okay = okay and maximum <= params.max_primary_span + 1e-6
    except AnalysisError:
        okay = False
    return bool(okay), maximum


def replay_housing_candidate(model, params, recipe, _force_secondary=(), search=None):
    """Replay a searched recipe for an API-owned bounded engineering retry.

    This is an internal seam, not a request parameter. The API retains its
    actual request envelope and must repeat all full-design eligibility gates.
    """
    result = _run_frame_placement_once(
        model, replace(params, housing_column_variant=recipe["seed"]), _force_secondary,
        (set(tuple(point) for point in recipe["removed"]), tuple(tuple(point) for point in recipe["added"])),
    )
    result.params_echo = params.to_dict()
    metadata = copy.deepcopy(search or {})
    metadata.update(
        selected_seed_variant=recipe["seed"], selected_removed=copy.deepcopy(recipe["removed"]),
        selected_added=copy.deepcopy(recipe["added"]), operation=recipe.get("operation", "design_fallback"),
        selected_rank=recipe.get("rank"),
        objective=list(_housing_objective(result.columns, result.beams, params.min_span)[:5]),
    )
    result.metrics["housing_search"] = metadata
    return result


def housing_search_cache_diagnostics():
    """Process-local operational evidence; never included in response metrics."""
    counts = _HOUSING_SEARCH_CACHE.diagnostics()
    out = {key: counts[key] for key in ("requests", "cache_hits", "cache_entries", "cache_limit", "in_flight")}
    out["pool_computation_count"] = counts["expensive_design_invocation_count"]
    return out


def clear_housing_search_cache():
    _HOUSING_SEARCH_CACHE.clear()


def _housing_search_signature(model, params, engine_fingerprint):
    state = {"version": "housing-placement-pool-1", "model": vars(model),
             "params": vars(replace(params, housing_column_variant=None)), "engine": engine_fingerprint}
    encoded = json.dumps(_exact(state), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def run_frame_placement(model, params=None, _force_secondary=()):
    params = params if params is not None else FrameParams()
    if (params.housing_column_variant in ("balanced", "toward_start", "toward_end")
            and 1 <= len(model.storeys) <= 3 and params.column_strategy == "wall_aligned"
            and params.system == "rc_frame" and not _force_secondary):
        # The source/data/rate fingerprint is owned by the API. Import lazily
        # so omitted-variant placement retains its existing import behavior.
        from ..api import structural_fingerprint
        key = _housing_search_signature(model, params, structural_fingerprint())
        pool = _HOUSING_SEARCH_CACHE.run(
            key, lambda: _run_housing_placement_uncached(model, params, _return_pool=True),
        )
        return pool[params.housing_column_variant]
    return _run_housing_placement_uncached(model, params, _force_secondary)


def _run_housing_placement_uncached(model, params=None, _force_secondary=(), _return_pool=False):
    """Preserve legacy placement, or search bounded low-rise Housing frames.

    Three guide seeds, at most 8 bearing repairs, 8 paired-support repairs,
    12 single-stack removals, 6 row/column subsets, 8 wall repositions, then remaining-budget greedy
    removals. At most 48 complete frame evaluations and 128 finite-wall
    stations. Every trial repeats all continuity/framing/panel repairs and
    final warnings. No elapsed-time cutoff chooses a partial winner.
    """
    from .housing_variants import MIN_REPOSITION_MM, SEARCH_CANDIDATE_LIMIT, WALL_STATION_LIMIT, wall_station_pool
    params = params if params is not None else FrameParams()
    variants = ("balanced", "toward_start", "toward_end")
    if (params.housing_column_variant not in variants or not 1 <= len(model.storeys) <= 3
            or params.column_strategy != "wall_aligned" or params.system != "rc_frame"):
        return _run_frame_placement_once(model, params, _force_secondary)

    prior = model.meta.get("frame_placement", {}).get("metrics", {}).get("housing_search", {})
    if _force_secondary and "selected_removed" in prior:
        # Referral panel IDs belong to this exact chosen frame. Replaying the
        # recipe repairs those panels; a fresh ranked search could choose a
        # different frame and silently leave their referrals outstanding.
        removed = tuple(tuple(point) for point in prior["selected_removed"])
        added = tuple(tuple(point) for point in prior["selected_added"])
        result = _run_frame_placement_once(
            model, replace(params, housing_column_variant=prior["selected_seed_variant"]),
            _force_secondary, (set(removed), added),
        )
        result.params_echo = params.to_dict()
        result.metrics["housing_search"] = dict(prior)
        result.metrics["housing_search"].update(
            referral_frame_evaluation_count=1,
            objective=list(_housing_objective(result.columns, result.beams, params.min_span)[:5]),
        )
        return result

    records, seen_recipes, all_geometry = [], set(), set()
    generated = 0

    def evaluate(seed, removed=(), added=(), operation="seed"):
        nonlocal generated
        recipe = (seed, tuple(sorted(removed)), tuple(sorted(added)))
        if recipe in seen_recipes or generated >= SEARCH_CANDIDATE_LIMIT:
            return None
        seen_recipes.add(recipe)
        generated += 1
        seed_params = replace(params, housing_column_variant=seed)
        try:
            result = _run_frame_placement_once(
                model, seed_params, _force_secondary,
                None if operation == "seed" else (set(removed), tuple(added)),
            )
        except _HousingEditRejected:
            return None
        safe, maximum = _housing_preflight(model, result, params)
        geometry = _housing_geometry(result.columns)
        all_geometry.add(geometry)
        record = dict(result=result, seed=seed, removed=tuple(removed), added=tuple(added),
                      operation=operation, safe=safe, maximum=maximum,
                      objective=_housing_objective(result.columns, result.beams, params.min_span))
        records.append(record)
        return record

    seeds = [evaluate(seed) for seed in variants]
    # Equal final seeds need only one set of support edits. The engineering
    # cache still uses full topology, not this column-layout identity.
    parents = {}
    for record in sorted(seeds, key=lambda row: (row["objective"], row["seed"])):
        parents.setdefault(_housing_geometry(record["result"].columns), record)
    buckets = {name: [] for name in ("bearing_repair", "bearing_pair", "remove", "subset", "reposition")}
    for record in parents.values():
        result = record["result"]
        optional = [c for c in result.columns if not _housing_required(c)]
        danger = set()
        for beam in result.beams:
            if beam.chain >= 3:
                danger.update(beam.points_mm())
        pool = wall_station_pool(model, result.grid, params.max_primary_span, danger)
        occupied = {(c.x_mm, c.y_mm) for c in result.columns}

        def propose(kind, removed, added=()):
            removed = tuple(sorted(set(removed)))
            added = tuple(sorted(set(added)))
            trial = [c for c in result.columns if (c.x_mm, c.y_mm) not in removed]
            for x, y in added:
                if any(max(abs(c.x_mm - x), abs(c.y_mm - y)) < MERGE_FLOOR_MM for c in trial):
                    return
                exists = [s.index for s in model.storeys if result.grid.contains(s.index, x / 1000, y / 1000)]
                if not exists or not all(_housing_near_wall(model, s, x / 1000, y / 1000) for s in exists):
                    return
                trial.append(_Stack(x, y, 0, "housing_search", exists, max(exists), min(exists), Fraction(0)))
            objective = _housing_objective(trial, (), params.min_span)
            buckets[kind].append((objective, record["seed"], removed, added))

        for c in optional:
            point = (c.x_mm, c.y_mm)
            propose("remove", (point,))
            for target in pool:
                repairs_bearing = any(max(abs(target[0] - end[0]), abs(target[1] - end[1])) <= 1500 for end in danger)
                if target in occupied or (not repairs_bearing and target[0] != c.x_mm and target[1] != c.y_mm):
                    continue
                distance = max(abs(target[0] - c.x_mm), abs(target[1] - c.y_mm))
                if MIN_REPOSITION_MM <= distance <= 2000:
                    propose("bearing_repair" if repairs_bearing else "reposition", (point,), (target,))
                    if repairs_bearing:
                        # Moving a near-end support onto a rear wall can leave
                        # the original side run with an excessive overhang.
                        # Keep an additional real-wall station on that run.
                        backups = [station for station in pool if station not in occupied and station != target
                                   and (station[0] == c.x_mm or station[1] == c.y_mm)
                                   and MIN_REPOSITION_MM <= max(abs(station[0] - c.x_mm), abs(station[1] - c.y_mm)) <= 2000]
                        for backup in sorted(backups)[:6]:
                            propose("bearing_pair", (point,), (target, backup))
        for target in sorted((danger & set(pool)) - occupied):
            propose("bearing_repair", (), (target,))
        for vertical in (True, False):
            lines = {}
            for c in optional:
                lines.setdefault(c.x_mm if vertical else c.y_mm, []).append((c.x_mm, c.y_mm))
            for points in lines.values():
                if len(points) > 1:
                    propose("subset", points)

    for kind, quota in (("bearing_repair", 8), ("bearing_pair", 8), ("remove", 12), ("subset", 6), ("reposition", 8)):
        unique = sorted(set(buckets[kind]))
        for _, seed, removed, added in unique[:quota]:
            evaluate(seed, removed, added, kind)
    # Reconsider deletions on the strongest repaired frame. Compound support
    # subsets can improve a layout even when the original merge pass retained
    # each member. Remaining work is explicitly bounded, too.
    survivors = [row for row in records if row["safe"]]
    if survivors:
        best = min(survivors, key=lambda row: (row["objective"], row["seed"]))
        for column in sorted(best["result"].columns, key=lambda c: (c.x_mm, c.y_mm)):
            if _housing_required(column) or best["added"]:
                continue
            removed = tuple(sorted(set(best["removed"]) | {(column.x_mm, column.y_mm)}))
            trial = evaluate(best["seed"], removed, (), "compound_subset")
            if trial is not None and trial["safe"] and trial["objective"] < best["objective"]:
                best = trial

    distinct = {}
    for record in sorted((row for row in records if row["safe"]), key=lambda row: (row["objective"], row["seed"])):
        distinct.setdefault(_housing_geometry(record["result"].columns), record)
    ranked = list(distinct.values())
    pool = {}
    for requested_rank, variant in enumerate(variants):
        selected_rank = requested_rank if requested_rank < len(ranked) else 0
        chosen = ranked[selected_rank] if ranked else seeds[requested_rank]
        result = copy.deepcopy(chosen["result"])
        result.params_echo = replace(params, housing_column_variant=variant).to_dict()
        result.metrics["housing_search"] = {
            "version": "housing-search-1", "generated_candidate_count": generated,
            "distinct_layout_count": len(ranked), "distinct_final_layout_count": len(all_geometry),
            "candidate_limit": SEARCH_CANDIDATE_LIMIT, "wall_station_limit": WALL_STATION_LIMIT,
            "minimum_reposition_mm": MIN_REPOSITION_MM, "selected_rank": selected_rank if ranked else None,
            "selected_seed_variant": chosen["seed"], "operation": chosen["operation"],
            "selected_removed": [list(point) for point in chosen["removed"]],
            "selected_added": [list(point) for point in chosen["added"]],
            "objective": list(chosen["objective"][:5]),
            "assessment": "placement preflight only; full design and final API audits required",
        }
        pool[variant] = result
    return pool if _return_pool else pool[params.housing_column_variant]


def _run_frame_placement_once(
    model: StructuralModel,
    params: Optional[FrameParams] = None,
    _force_secondary: Sequence[str] = (),
    _support_edit=None,
) -> FrameResult:
    """Axes -> cores -> columns -> continuity -> framing/panels loop -> score."""
    params = params if params is not None else FrameParams()
    log = DisclosureLog()
    grid = extract_axes(model, params)
    if params.column_strategy == "economy_grid":
        grid = _economy_grid(grid, params)
    log.extend(grid.log.entries)

    core_plan = plan_cores(model, grid, params)
    log.extend(core_plan.log.entries)
    core_beams, stair_slabs, core_notes = frame_core_openings(model, grid, core_plan, params)

    view = _View(model, grid, params)
    stacks, state = place_columns(model, grid, core_plan, params, log, view)
    if _support_edit is not None:
        removed, added = _support_edit
        stacks = [stack for stack in stacks if (stack.x_mm, stack.y_mm) not in removed or _housing_required(stack, state)]
        state.accepted = stacks
        for x, y in added:
            new = state.process([_Cand(x, y, 0, "housing_search", no_snap=True)])
            exact = [stack for stack in new if (stack.x_mm, stack.y_mm) == (x, y)]
            if not exact or any(stack.chebyshev(exact[0]) < MERGE_FLOOR_MM for stack in stacks):
                raise _HousingEditRejected()
            stacks.append(exact[0])
        for stack in stacks:
            stack.axis_x = _axis_at(grid.x_axes, stack.x_mm, _AXIS_MATCH_TOL_MM)
            stack.axis_y = _axis_at(grid.y_axes, stack.y_mm, _AXIS_MATCH_TOL_MM)
    stacks = enforce_continuity(view, stacks, state, params, log)
    state.accepted = stacks

    framer = _Framer(view, stacks, core_beams, params, log, state)
    panelizer = _Panelizer(view, state, params, log, framer)
    forced = set(_force_secondary)

    beams_by_level = {}  # type: Dict[int, List[_PBeam]]
    panels_by_level = {}  # type: Dict[int, List[_Panel]]
    still_marked = []  # type: List[_Panel]
    exhausted = False
    for iteration in range(1, FEEDBACK_ITERATIONS + 1):
        beams_by_level = {s: framer.frame_level(s) for s in view.storeys}
        panels_by_level = {
            s: panelizer.panelize(s, beams_by_level[s]) for s in view.storeys
        }
        marked = []  # type: List[_Panel]
        for storey in view.storeys:
            for panel in panels_by_level[storey]:
                if panel.marked or panel.id in forced:
                    marked.append(panel)
        if not marked:
            still_marked = []
            break
        still_marked = marked
        if iteration == FEEDBACK_ITERATIONS:
            exhausted = True
            break
        progressed = False
        for panel in sorted(marked, key=lambda p: p.id):
            if _reinstate_for_panel(framer, panel):
                progressed = True
            elif _insert_secondaries_for_panel(framer, panel, params, view):
                progressed = True
        if not progressed:
            break

    if still_marked:
        if exhausted:
            log.add(
                "W_COARSE_ITER",
                "slab feedback stopped at %d iterations before convergence" % FEEDBACK_ITERATIONS,
                sorted(p.id for p in still_marked),
                stage=_STAGE_SLABS,
            )
        cap_mm = state.cap_mm
        slab_target_mm = max(
            int(round(float(params.slab_t_max_mm))),
            int(round(RC_SLAB_MIN_THICKNESS_MM)),
        )
        for panel in sorted(still_marked, key=lambda p: p.id):
            if min(panel.lx_mm, panel.ly_mm) * 2 > 3 * cap_mm:
                log.add(
                    "E_GRID_COARSE",
                    "panel %s short side %d mm exceeds 1.5x the primary span cap" % (panel.id, panel.lx_mm),
                    [panel.id],
                    stage=_STAGE_SLABS,
                )
            elif panel.t_mm is not None and panel.t_mm > slab_target_mm:
                log.add(
                    "W_THICK_SLAB",
                    "panel %s keeps a %s mm thumb thickness above the %d mm target"
                    % (panel.id, panel.t_mm, slab_target_mm),
                    [panel.id],
                    stage=_STAGE_SLABS,
                )
            else:
                log.add(
                    "W_COARSE_ITER",
                    "panel %s remains above the secondary-beam span trigger after feedback; "
                    "its %s mm thumb thickness is within the %d mm target and the final slab "
                    "design, not this preliminary thumb rule, governs"
                    % (panel.id, panel.t_mm, slab_target_mm),
                    [panel.id],
                    stage=_STAGE_SLABS,
                )

    all_beams = []  # type: List[_PBeam]
    for storey in view.storeys:
        all_beams.extend(beams_by_level.get(storey, []))
    ground_fp = grid.footprints.get(0)
    all_beams.extend(_connect_level(stacks, ground_fp, "P", BeamKind.PLINTH, "plinth"))
    ground = model.storey(0)
    if ground is not None and ground.height_m > float(params.tie_trigger):
        all_beams.extend(_connect_level(stacks, ground_fp, "T0", BeamKind.TIE, "tie"))

    all_beams = _split_beams_at_columns(all_beams, stacks)
    _size_beams(all_beams)
    _assign_beam_ids(all_beams, grid)
    _assign_stack_ids(stacks)
    _assign_sizes(stacks, view, log)

    _warn_final_short_spans(state, log)
    _validate_merge_floor(state, log)
    for stack in stacks:
        if stack.transfer:
            log.add(
                "E_TRANSFER_REQUIRED",
                "column %s is unsupported at storey %s; a transfer structure is required and is never auto-placed"
                % (stack.id, ",".join(str(s) for s in stack.unsupported)),
                [stack.id],
                clause="IS 1893 Cl 7.1",
                stage=_STAGE_CONT,
            )
        if stack.slid_mm:
            log.add(
                "W_SLID",
                "column %s slid %d mm along %s to stay supported" % (stack.id, stack.slid_mm, stack.slide_dir),
                [stack.id],
                stage=_STAGE_CONT,
            )
    for beam in all_beams:
        if beam.kind in (BeamKind.PRIMARY, BeamKind.SECONDARY) and beam.span_mm > _mm(HARD_MAX_SPAN_M):
            log.add(
                "E_SPAN_OVER_MAX",
                "primary beam %s spans %d mm, over the %d mm hard cap"
                % (beam.id, beam.span_mm, _mm(HARD_MAX_SPAN_M)),
                [beam.id],
                stage=_STAGE_BEAMS,
            )
    irregular = sorted(
        p.id for panels in panels_by_level.values() for p in panels if p.irregular and p.kind == "slab"
    )
    if irregular:
        log.add(
            "W_IRREG",
            "%d panels are rectilinear non-rectangles; the largest inscribed rectangle sets their spans" % len(irregular),
            irregular,
            stage=_STAGE_SLABS,
        )

    all_panels = []  # type: List[_Panel]
    for storey in view.storeys:
        all_panels.extend(panels_by_level.get(storey, []))

    metrics = score_layout(view, grid, stacks, all_beams, all_panels, core_plan.shaft_walls, log)
    valid = sum(metrics["hard_violations"].values()) == 0

    assumptions = []  # type: List[str]
    if model.doors_known():
        assumptions.append("doors read from dressed plan")
    else:
        assumptions.append(
            "doors unknown: mid-third rule applied on %d interior walls" % len(state.midwall_fired)
        )
    for note in core_notes:
        if str(note.get("note", "")).startswith("door_edge_assumed"):
            assumptions.append("core %s: %s" % (note.get("core_id"), note.get("note")))
    if core_plan.mode == "shaft":
        assumptions.append("cores modelled as RC shafts (prescription, not design)")

    repairs = [
        {"column": s.id, "d_mm": int(s.slid_mm), "dir": s.slide_dir}
        for s in sorted(stacks, key=lambda s: s.id)
        if s.slid_mm
    ]
    entries = log.sorted_entries()
    report = {
        "summary": "%d x %d axes, %d column stacks, %d beams, %d panels over %d storeys"
        % (
            len(grid.x_axes),
            len(grid.y_axes),
            len(stacks),
            len(all_beams),
            len(all_panels),
            len(view.storeys),
        ),
        "errors": [e.to_dict() for e in entries if e.severity.value == "error"],
        "warnings": [e.to_dict() for e in entries if e.severity.value != "error"],
        "assumptions": assumptions,
        "repairs": repairs,
    }

    result = FrameResult(
        grid=grid,
        columns=sorted(stacks, key=lambda s: (s.x_mm, s.y_mm)),
        beams=sorted(all_beams, key=lambda b: (b.level_rank, b.orient, b.pos_mm, b.lo_mm, b.hi_mm, b.id)),
        panels=sorted(all_panels, key=lambda p: (p.level, p.id)),
        shaft_walls=list(core_plan.shaft_walls),
        stair_slabs=list(stair_slabs),
        core_notes=list(core_notes),
        params_echo=params.to_dict(),
        metrics=metrics,
        report=report,
        valid=valid,
        log=log,
    )
    return result


def _warn_final_short_spans(state: _ColumnState, log: DisclosureLog) -> None:
    """Disclose close final neighbours, including late beam-support promotions.

    Grid gaps are not column gaps. Only adjacent centres on the same exact row
    or column and an occupied shared storey qualify here. Report each pair once
    across the building; corridor-edge and core-tie exceptions remain exempt.
    Recomputing after feedback also avoids referring to a column later removed.
    """
    log.entries[:] = [entry for entry in log.entries
                      if not (entry.code == "W_SHORT_SPAN" and entry.stage == _STAGE_COLS)]
    pairs = {}  # type: Dict[Tuple[str, str], Tuple[_Stack, _Stack, int, List[int]]]
    for storey in state.view.storeys:
        active = [s for s in state.accepted if storey in s.exists and s.base <= storey <= s.top]
        for vertical in (True, False):
            lines = {}  # type: Dict[int, List[_Stack]]
            for stack in active:
                pos = stack.x_mm if vertical else stack.y_mm
                lines.setdefault(pos, []).append(stack)
            for pos in sorted(lines):
                line = sorted(lines[pos], key=lambda s: (s.y_mm if vertical else s.x_mm, s.id))
                for a, b in zip(line, line[1:]):
                    gap = (b.y_mm - a.y_mm) if vertical else (b.x_mm - a.x_mm)
                    if gap <= 0 or gap >= state.min_span_mm or state._waived_pair(a, b):
                        continue
                    key = tuple(sorted((a.id, b.id)))
                    if key not in pairs:
                        pairs[key] = (a, b, gap, [])
                    if storey not in pairs[key][3]:
                        pairs[key][3].append(storey)
    guarded = {tuple(sorted((a.id, b.id))) for a, b in state.short_pairs}
    for key in sorted(pairs):
        a, b, gap, storeys = pairs[key]
        reason = ""
        if key in guarded:
            reason = "; retained to keep a neighbouring span within the requested cap"
        elif a.origin == "promoted" or b.origin == "promoted":
            reason = "; retained after beam-support repair"
        log.add(
            "W_SHORT_SPAN",
            "columns %s and %s have retained centres %d mm apart on storey indices %s, "
            "below the preferred min_span %d mm%s"
            % (a.id, b.id, gap, ",".join(str(s) for s in storeys), state.min_span_mm, reason),
            list(key),
            stage=_STAGE_COLS,
        )


def _validate_merge_floor(state: _ColumnState, log: DisclosureLog) -> None:
    accepted = sorted(state.accepted, key=lambda s: (s.x_mm, s.y_mm))
    for i in range(len(accepted)):
        for j in range(i + 1, len(accepted)):
            a, b = accepted[i], accepted[j]
            if b.x_mm - a.x_mm >= MERGE_FLOOR_MM:
                break
            if a.chebyshev(b) < MERGE_FLOOR_MM and not state._waived_pair(a, b):
                log.add(
                    "E_MERGE_FLOOR",
                    "columns %s and %s are %d mm apart, under the 1.2 m merge floor"
                    % (a.id or "?", b.id or "?", a.chebyshev(b)),
                    [a.id, b.id],
                    stage=_STAGE_COLS,
                )


def _reinstate_for_panel(framer: _Framer, panel: _Panel) -> bool:
    """Keep-rule 2: pruned primaries that would bound a marked panel come back."""
    added = False
    for cand in framer.pruned.get(panel.level, []):
        if cand.key in framer.reinstated:
            continue
        chords = panel.region.chords_mm(cand.orient, cand.pos_mm)
        inside = sum(
            _overlap(cand.lo_mm, cand.hi_mm, lo, hi) for lo, hi in chords
        )
        if inside < 100:
            continue
        on_boundary = False
        count = len(panel.outline_mm)
        for i in range(count):
            a = panel.outline_mm[i]
            b = panel.outline_mm[(i + 1) % count]
            if cand.orient == "v" and a[0] == b[0] and abs(a[0] - cand.pos_mm) <= 60:
                on_boundary = True
            if cand.orient == "h" and a[1] == b[1] and abs(a[1] - cand.pos_mm) <= 60:
                on_boundary = True
        if on_boundary:
            continue
        framer.reinstated.add(cand.key)
        added = True
    return added


def _insert_secondaries_for_panel(
    framer: _Framer, panel: _Panel, params: FrameParams, view: _View
) -> bool:
    """Rule 3: secondaries parallel to the SHORT side subdividing the LONG side."""
    spacing_mm = _mm(params.secondary_spacing_clamped())
    long_mm = panel.ly_mm
    if long_mm <= 0 or spacing_mm <= 0:
        return False
    count = -(-long_mm // spacing_mm) - 1
    if count <= 0:
        return False
    x0, y0, x1, y1 = panel.rect_mm
    long_is_y = (y1 - y0) >= (x1 - x0)
    lo = y0 if long_is_y else x0
    hi = y1 if long_is_y else x1
    orient = "h" if long_is_y else "v"  # parallel to the short side
    added = False
    snap_mm = _mm(params.snap_wall)
    for step in range(1, count + 1):
        station = lo + _round_ratio(step * (hi - lo), count + 1)
        wall_id = None  # type: Optional[str]
        best = None  # type: Optional[Tuple[int, int, str]]
        for rec in view.walls.get(panel.level, []):
            if rec.orient != orient:
                continue
            d = abs(rec.pos_mm - station)
            if d <= snap_mm and lo < rec.pos_mm < hi and (best is None or (d, rec.pos_mm, rec.id) < best):
                best = (d, rec.pos_mm, rec.id)
        if best is not None:
            station = best[1]
            wall_id = best[2]
        chords = panel.region.chords_mm(orient, station)
        for clo, chi in chords:
            if chi - clo < 100:
                continue
            key = "sec:%d:%s:%d:%d:%d" % (panel.level, orient, station, clo, chi)
            specs = framer.secondary_specs.setdefault(panel.level, [])
            if any(s[5] == key for s in specs):
                continue
            specs.append((orient, station, clo, chi, wall_id, key))
            specs.sort(key=lambda s: (s[0], s[1], s[2], s[3]))
            added = True
    return added


def insert_secondary_beams(
    model: StructuralModel,
    params: Optional[FrameParams] = None,
    panel_ids: Sequence[str] = (),
) -> FrameResult:
    """The bounded re-place entry (finding 19): force secondaries into panels.

    run_design calls this at most once, passing the panel ids its load or
    design pass referred back; the whole placement re-runs deterministically
    with those panels marked in the feedback loop.
    """
    return run_frame_placement(model, params, _force_secondary=tuple(panel_ids))


# ---------------------------------------------------------------------------
# lintels over masonry infill openings (finding 40)
# ---------------------------------------------------------------------------

LINTEL_BEARING_M = 0.150


def place_lintels_for_infill(model: StructuralModel) -> List[Lintel]:
    """Create model.Lintel entries over openings in masonry-material walls.

    Simple geometry: lintel span = opening width + 2 x 150 mm bearing. Existing
    frame-placed lintels are replaced, other producers' lintels are kept.
    run_design invokes this after placement for rc_frame systems.
    """
    placed_by = "placement.frame.lintel_infill"
    kept = [lin for lin in model.lintels if lin.placed_by != placed_by]
    out = []  # type: List[Lintel]
    for wall in sorted(model.walls, key=lambda w: w.id):
        if wall.role == WallRole.RAILING:
            continue
        material = wall.material.value if hasattr(wall.material, "value") else str(wall.material)
        if material != Material.BRICK_MASONRY.value:
            continue
        openings = sorted(wall.openings, key=lambda o: (o.offset_m, o.id))
        for index, opening in enumerate(openings):
            out.append(
                Lintel(
                    id=lintel_id(wall.id, index),
                    wall_id=wall.id,
                    opening_id=opening.id,
                    span_m=float(opening.width_m) + 2.0 * LINTEL_BEARING_M,
                    placed_by=placed_by,
                )
            )
    model.lintels = kept + out
    return out
