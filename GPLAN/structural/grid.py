"""Axis extraction: walls, outlines, corridors and cores to a regularized building grid.

`extract_axes(model, params) -> AxisGrid` is the first step of RC frame placement.
It harvests candidate lines per storey, clusters them with priority anchoring,
unions them across floors with presence bitmasks, inserts span-control lines and
builds the per-storey junction graph.

Units. The StructuralModel is SI metres (finding 1). This module quantizes to
integer millimetres PRIVATELY, so that merging, weighted means and inserted
stations are exact and byte-reproducible; every value that leaves the module is
metres again. Only names ending in `_mm` carry millimetres.

`FrameParams` lives here rather than in `placement/frame.py` so that grid and
frame share one parameter object without a circular import: `placement/frame.py`
imports FrameParams from this module.

Determinism. No sets are iterated, no dict order is relied on, every greedy pass
states its total order key, and ids come from positions (through labels), never
from insertion order. The same model, with its walls in any order, produces an
identical `AxisGrid.to_dict()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .model import (
    AxisDir,
    AxisSource,
    DisclosureLog,
    GridAxis,
    RC_SLAB_MIN_THICKNESS_MM,
    StructuralModel,
    System,
    WallRole,
    axis_id,
    wall_axis,
)

# ---------------------------------------------------------------------------
# constants and parameters
# ---------------------------------------------------------------------------

# Structural caps from the placement catalogue; not user parameters.
HARD_MAX_SPAN_M = 7.5
COLUMN_MERGE_FLOOR_M = 1.2
HOUSING_COLUMN_VARIANTS = ("balanced", "toward_start", "toward_end")
SECONDARY_SPACING_BAND_M = (2.5, 3.5)

# An inserted axis prefers a partition within this window over fresh air.
INSERT_SNAP_M = 0.6

# Candidates that are not walls (footprint edges, corridor edges, core faces)
# borrow a one-brick wall for the non-parametric tolerance max(t1, t2) / 2.
DEFAULT_WALL_T_M = 0.23

# Junction coincidence window, per spec 4.5: tol_wall + 10 mm.
TOL_JOIN_EXTRA_MM = 10

# Lower wins: an outline member anchors a cluster against a party member, and so on.
AXIS_PRIORITY = {
    AxisSource.OUTLINE.value: 0,
    AxisSource.CORRIDOR.value: 1,
    AxisSource.PARTY.value: 2,
    AxisSource.CORE.value: 3,
    AxisSource.WALL.value: 4,
    AxisSource.INSERTED.value: 5,
}

# WallRole is architectural, AxisSource is structural provenance (finding 12).
# Adapters lay exterior centrelines on the boundary itself, so exterior walls and
# footprint edges are the same `outline` tier and agree on position.
_ROLE_SOURCE = {
    WallRole.EXTERIOR.value: AxisSource.OUTLINE,
    WallRole.PARTY.value: AxisSource.PARTY,
    WallRole.CORE.value: AxisSource.CORE,
    WallRole.INTERIOR.value: AxisSource.WALL,
    WallRole.PARAPET.value: AxisSource.WALL,
}

_JUNCTION_KIND = {1: "end", 2: "L", 3: "T", 4: "X"}


@dataclass
class FrameParams:
    """Placement knobs. Every length is METRES; `slab_t_max_mm` is millimetres.

    Field names follow the spec table so that frame.py, cores.py and the API
    layer name one knob one way; `to_dict()` adds the wire unit suffixes.
    """

    system: str = System.RC_FRAME.value
    # ``wall_aligned`` preserves the original exhaustive architectural-axis
    # candidate grid. ``economy_grid`` selects the smallest admissible subset
    # of those axes before columns and primary beams are placed; every selected
    # gap still respects ``max_primary_span`` and the full design/quantity pass
    # decides whether the resulting option is actually economical.
    column_strategy: str = "wall_aligned"
    max_primary_span: float = 5.0
    min_span: float = 2.5
    span_direction: str = "auto"
    secondary_spacing: float = 3.0
    merge_tol: float = 0.30
    jamb_clearance: float = 0.15
    cantilever_cap: float = 2.0
    column_merge: float = 1.5
    snap_junction: float = 0.45
    snap_wall: float = 0.30
    tie_trigger: float = 3.6
    shaft_min_storeys: int = 4
    slab_t_max_mm: float = 150.0
    # Appended to preserve positional construction of existing FrameParams.
    # Opt-in, low-rise Housing variants; None preserves the existing placer.
    housing_column_variant: Optional[str] = None

    def secondary_spacing_clamped(self) -> float:
        """Secondary centres inside the catalogue band [2.5, 3.5] m."""
        low, high = SECONDARY_SPACING_BAND_M
        return min(max(float(self.secondary_spacing), low), high)

    def column_merge_floored(self) -> float:
        """Column dedupe window, never below the 1.2 m catalogue floor."""
        return max(float(self.column_merge), COLUMN_MERGE_FLOOR_M)

    def slab_t_max_floored_mm(self) -> float:
        """The slab target cannot sit below the project's RC slab minimum."""
        return max(float(self.slab_t_max_mm), RC_SLAB_MIN_THICKNESS_MM)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "system": self.system,
            "column_strategy": str(self.column_strategy),
            "span_direction": self.span_direction,
            "max_primary_span_m": round(float(self.max_primary_span), 6),
            "min_span_m": round(float(self.min_span), 6),
            "secondary_spacing_m": round(float(self.secondary_spacing), 6),
            "merge_tol_m": round(float(self.merge_tol), 6),
            "jamb_clearance_m": round(float(self.jamb_clearance), 6),
            "cantilever_cap_m": round(float(self.cantilever_cap), 6),
            "column_merge_m": round(float(self.column_merge), 6),
            "snap_junction_m": round(float(self.snap_junction), 6),
            "snap_wall_m": round(float(self.snap_wall), 6),
            "tie_trigger_m": round(float(self.tie_trigger), 6),
            "shaft_min_storeys": int(self.shaft_min_storeys),
            "slab_t_max_mm": round(self.slab_t_max_floored_mm(), 6),
        }
        if self.housing_column_variant is not None:
            result["housing_column_variant"] = self.housing_column_variant
        return result


# ---------------------------------------------------------------------------
# integer millimetre helpers (private quantization, finding 1)
# ---------------------------------------------------------------------------


def _mm(value_m: float) -> int:
    """Metres to integer millimetres (Python round: ties to even)."""
    return int(round(float(value_m) * 1000.0))


def _m(value_mm: int) -> float:
    """Integer millimetres back to metres."""
    return int(value_mm) / 1000.0


def _round_ratio(num: int, den: int) -> int:
    """num / den to the nearest integer, an exact half resolving to the LOWER value.

    Spec 4.2 rule 3 resolves weight ties by the lower position, so a mean sitting
    exactly between two equally weighted members lands on the lower one.
    """
    if den == 0:
        raise ValueError("zero denominator")
    if den < 0:
        num, den = -num, -den
    quotient, remainder = divmod(num, den)  # floor division, remainder >= 0
    if 2 * remainder > den:
        quotient += 1
    return quotient


def _merge_intervals(intervals: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Sorted union of closed intervals; touching intervals merge."""
    ordered = sorted((int(lo), int(hi)) for lo, hi in intervals if hi >= lo)
    out = []  # type: List[Tuple[int, int]]
    for lo, hi in ordered:
        if out and lo <= out[-1][1]:
            if hi > out[-1][1]:
                out[-1] = (out[-1][0], hi)
        else:
            out.append((lo, hi))
    return out


def _subtract_intervals(
    intervals: Sequence[Tuple[int, int]], cut: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """`intervals` minus `cut`, both already sorted and merged."""
    out = []  # type: List[Tuple[int, int]]
    for lo, hi in intervals:
        pieces = [(lo, hi)]
        for clo, chi in cut:
            next_pieces = []  # type: List[Tuple[int, int]]
            for plo, phi in pieces:
                if chi <= plo or clo >= phi:
                    next_pieces.append((plo, phi))
                    continue
                if clo > plo:
                    next_pieces.append((plo, clo))
                if chi < phi:
                    next_pieces.append((chi, phi))
            pieces = next_pieces
        for piece in pieces:
            if piece[1] > piece[0]:
                out.append(piece)
    return _merge_intervals(out)


def _clip_intervals(
    intervals: Sequence[Tuple[int, int]], window: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Intersection of two interval unions, both already sorted and merged."""
    out = []  # type: List[Tuple[int, int]]
    for lo, hi in intervals:
        for wlo, whi in window:
            start = max(lo, wlo)
            end = min(hi, whi)
            if end > start:
                out.append((start, end))
    return _merge_intervals(out)


def letter_label(index: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA', 27 -> 'AB' (spreadsheet style)."""
    if index < 0:
        raise ValueError("label index must be non negative")
    text = ""
    value = int(index)
    while True:
        text = chr(ord("A") + (value % 26)) + text
        value = value // 26 - 1
        if value < 0:
            break
    return text


# ---------------------------------------------------------------------------
# storey footprint: a rectilinear region in integer millimetres
# ---------------------------------------------------------------------------


def _decompose(
    groups: Sequence[Sequence[Tuple[int, int, int]]],
    xs: Sequence[int],
    strict: bool,
) -> Optional[List[Tuple[int, int, int, int]]]:
    """Union of closed rectilinear groups as disjoint rects, by vertical slabs.

    Each group is a list of horizontal edges (y, xa, xb) belonging to one closed
    curve set; a vertical line through a slab midpoint crosses them an even
    number of times, and consecutive crossings bound the interior. With
    `strict`, an odd crossing count means the group is not closed and the whole
    decomposition is refused (None) rather than guessed.
    """
    bounds = sorted(set(int(v) for v in xs))
    slabs = []  # type: List[Tuple[int, int, Tuple[Tuple[int, int], ...]]]
    for i in range(len(bounds) - 1):
        x0 = bounds[i]
        x1 = bounds[i + 1]
        if x1 <= x0:
            continue
        mid_doubled = x0 + x1  # twice the slab midpoint, so no fractions
        spans = []  # type: List[Tuple[int, int]]
        for edges in groups:
            crossings = sorted(
                y for (y, xa, xb) in edges if 2 * xa < mid_doubled < 2 * xb
            )
            if strict and len(crossings) % 2:
                return None
            for j in range(0, len(crossings) - 1, 2):
                spans.append((crossings[j], crossings[j + 1]))
        merged = _merge_intervals(spans)
        if merged:
            slabs.append((x0, x1, tuple(merged)))

    rects = []  # type: List[Tuple[int, int, int, int]]
    open_slab = None  # type: Optional[Tuple[int, int, Tuple[Tuple[int, int], ...]]]
    for x0, x1, spans in slabs:
        if open_slab is not None and open_slab[1] == x0 and open_slab[2] == spans:
            open_slab = (open_slab[0], x1, spans)
            continue
        if open_slab is not None:
            for lo, hi in open_slab[2]:
                rects.append((open_slab[0], lo, open_slab[1], hi))
        open_slab = (x0, x1, spans)
    if open_slab is not None:
        for lo, hi in open_slab[2]:
            rects.append((open_slab[0], lo, open_slab[1], hi))
    return rects


class _Footprint:
    """The storey's built area as disjoint axis-aligned rects (mm).

    It is the union of the room polygons and the area enclosed by the exterior
    wall envelope: units are inset from a building boundary, so rooms alone
    would leave the boundary line outside the storey. The region answers the
    three questions the grid asks: does this line cross the storey, over which
    intervals, and is this crossing point inside.
    """

    def __init__(self, rects: Sequence[Tuple[int, int, int, int]]):
        self.rects = sorted(tuple(int(v) for v in r) for r in rects)

    @staticmethod
    def from_polygons(polygons: Sequence[Sequence[Tuple[int, int]]]) -> "_Footprint":
        """Union of rectilinear loops, each loop paired on its own."""
        groups = []  # type: List[List[Tuple[int, int, int]]]
        xs = []  # type: List[int]
        for polygon in polygons:
            points = [(int(p[0]), int(p[1])) for p in polygon]
            if len(points) < 4:
                continue
            horizontals = []  # type: List[Tuple[int, int, int]]
            count = len(points)
            for i in range(count):
                x1, y1 = points[i]
                x2, y2 = points[(i + 1) % count]
                xs.append(x1)
                xs.append(x2)
                if y1 == y2 and x1 != x2:
                    horizontals.append((y1, min(x1, x2), max(x1, x2)))
            if horizontals:
                groups.append(sorted(horizontals))
        if not groups:
            return _Footprint([])
        rects = _decompose(groups, xs, strict=False)
        return _Footprint(rects or [])

    @staticmethod
    def from_edges(
        edges: Sequence[Tuple[int, int, int, int]]
    ) -> Optional["_Footprint"]:
        """Area enclosed by axis-aligned segments (x0, y0, x1, y1), or None.

        None means the segments do not close, so nothing is assumed about what
        they enclose.
        """
        horizontals = []  # type: List[Tuple[int, int, int]]
        xs = []  # type: List[int]
        for x0, y0, x1, y1 in edges:
            xs.append(int(x0))
            xs.append(int(x1))
            if y0 == y1 and x0 != x1:
                horizontals.append((int(y0), min(int(x0), int(x1)), max(int(x0), int(x1))))
        if not horizontals:
            return None
        rects = _decompose([sorted(horizontals)], xs, strict=True)
        if rects is None:
            return None
        return _Footprint(rects)

    @staticmethod
    def from_rects(rects: Sequence[Tuple[int, int, int, int]]) -> "_Footprint":
        """Region from (x0, y0, x1, y1) rects, re-decomposed so they stay disjoint."""
        polygons = [
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for x0, y0, x1, y1 in rects
        ]
        return _Footprint.from_polygons(polygons)

    def is_empty(self) -> bool:
        return not self.rects

    def chords_mm(self, orient: str, pos_mm: int) -> List[Tuple[int, int]]:
        """Intervals the region covers along the line; orient 'v' is x = pos."""
        spans = []  # type: List[Tuple[int, int]]
        for x0, y0, x1, y1 in self.rects:
            if orient == "v":
                if x0 <= pos_mm <= x1:
                    spans.append((y0, y1))
            else:
                if y0 <= pos_mm <= y1:
                    spans.append((x0, x1))
        return _merge_intervals(spans)

    def boundary_lines(self, orient: str) -> List[Tuple[int, int, int]]:
        """Boundary edges as (pos_mm, lo_mm, hi_mm); 'v' is x = pos, spanning y.

        A boundary edge is where the region covers exactly one side of the line,
        so the slab seams of the decomposition drop out and interior holes stay in.
        """
        if not self.rects:
            return []
        if orient == "v":
            positions = sorted({r[0] for r in self.rects} | {r[2] for r in self.rects})
        else:
            positions = sorted({r[1] for r in self.rects} | {r[3] for r in self.rects})
        out = []  # type: List[Tuple[int, int, int]]
        for pos_mm in positions:
            before = self.chords_mm(orient, pos_mm - 1)
            after = self.chords_mm(orient, pos_mm + 1)
            spans = _merge_intervals(
                _subtract_intervals(before, after) + _subtract_intervals(after, before)
            )
            for lo, hi in spans:
                out.append((pos_mm, lo, hi))
        return sorted(out)

    def covers(self, x_mm: int, y_mm: int) -> bool:
        for x0, y0, x1, y1 in self.rects:
            if x0 <= x_mm <= x1 and y0 <= y_mm <= y1:
                return True
        return False

    def bbox_mm(self) -> Optional[Tuple[int, int, int, int]]:
        if not self.rects:
            return None
        x0 = min(r[0] for r in self.rects)
        y0 = min(r[1] for r in self.rects)
        x1 = max(r[2] for r in self.rects)
        y1 = max(r[3] for r in self.rects)
        return (x0, y0, x1, y1)

    def rects_m(self) -> List[Tuple[float, float, float, float]]:
        return [(_m(r[0]), _m(r[1]), _m(r[2]), _m(r[3])) for r in self.rects]


# ---------------------------------------------------------------------------
# harvest: one candidate line per contributing element (spec 4.1)
# ---------------------------------------------------------------------------


@dataclass
class _Cand:
    """One harvested line: where it sits, how much line it brings, and from what."""

    pos_mm: int
    source: AxisSource
    weight_mm: int
    lo_mm: int
    hi_mm: int
    t_mm: int
    storey: int
    key: str
    wall_id: Optional[str] = None
    corridor_key: Optional[str] = None

    @property
    def priority(self) -> int:
        return AXIS_PRIORITY[self.source.value]


def _anchor(members: Sequence[_Cand]) -> _Cand:
    """The member a cluster is anchored on: best priority, longest, lowest, then id."""
    return sorted(
        members, key=lambda c: (c.priority, -c.weight_mm, c.pos_mm, c.key)
    )[0]


def _resolve_pos_mm(members: Sequence[_Cand]) -> int:
    """Cluster position, spec 4.2 rules 1 to 3.

    1. an outline member fixes the position exactly (exact plot fill must survive)
    2. else a corridor edge fixes it exactly (columns frame the clear width)
    3. else the length-weighted mean, weight ties resolving to the lower position
    """
    for tier in (AxisSource.OUTLINE, AxisSource.CORRIDOR):
        tier_members = [c for c in members if c.source == tier]
        if tier_members:
            best = sorted(
                tier_members, key=lambda c: (-c.weight_mm, c.pos_mm, c.key)
            )[0]
            return best.pos_mm
    total = sum(c.weight_mm for c in members)
    if total <= 0:
        return min(c.pos_mm for c in members)
    return _round_ratio(sum(c.weight_mm * c.pos_mm for c in members), total)


class _Unit:
    """A clustering unit: a single candidate, or an already merged cluster."""

    def __init__(self, members: Sequence[_Cand], pos_mm: Optional[int] = None):
        self.members = list(members)
        self.anchor = _anchor(self.members)
        self.pos_mm = _resolve_pos_mm(self.members) if pos_mm is None else int(pos_mm)
        self.priority = self.anchor.priority
        self.source = self.anchor.source
        self.key = min(c.key for c in self.members)
        self.t_mm = self.anchor.t_mm


def _cluster(units: Sequence[_Unit], fixed_tol_mm: Optional[int] = None) -> List[_Unit]:
    """Greedy left to right clustering, ordered by (pos, priority, key).

    A unit joins the open cluster when it lies within the window of that
    cluster's anchor. The window is `max(t1, t2) // 2` (non parametric, per the
    catalogue) unless a fixed tolerance is given for the merge_tol passes.
    """
    ordered = sorted(units, key=lambda u: (u.pos_mm, u.priority, u.key))
    out = []  # type: List[_Unit]
    open_members = []  # type: List[_Cand]
    # The opening member owns this window for the whole cluster. Re-resolving
    # the anchor after each join lets a chain of close lines drift arbitrarily
    # past the documented tolerance.
    open_anchor = None  # type: Optional[_Cand]
    for unit in ordered:
        if open_anchor is None:
            open_members = list(unit.members)
            open_anchor = _anchor(open_members)
            continue
        if fixed_tol_mm is None:
            tol_mm = max(unit.t_mm, open_anchor.t_mm) // 2
        else:
            tol_mm = fixed_tol_mm
        if abs(unit.pos_mm - open_anchor.pos_mm) <= tol_mm:
            open_members.extend(unit.members)
        else:
            out.append(_Unit(open_members))
            open_members = list(unit.members)
            open_anchor = _anchor(open_members)
    if open_anchor is not None:
        out.append(_Unit(open_members))
    return sorted(out, key=lambda u: (u.pos_mm, u.priority, u.key))


def _dedupe_positions(units: Sequence[_Unit]) -> List[_Unit]:
    """Two clusters resolving to the same millimetre are one axis, not two ids."""
    by_pos = {}  # type: Dict[int, List[_Cand]]
    for unit in units:
        by_pos.setdefault(unit.pos_mm, []).extend(unit.members)
    return [_Unit(by_pos[pos], pos_mm=pos) for pos in sorted(by_pos)]


def _corridor_key(storey: int, rect_mm: Tuple[int, int, int, int]) -> str:
    return "cor-s%d-%d-%d-%d-%d" % (storey, rect_mm[0], rect_mm[1], rect_mm[2], rect_mm[3])


def _harvest(
    model: StructuralModel,
    storey: int,
    footprint: _Footprint,
) -> Tuple[List[_Cand], List[_Cand]]:
    """Candidates for (X axes, Y axes) on one storey.

    An X axis is the line x = pos and spans in y, so it is fed by walls whose
    centreline is perpendicular to x (the vertical runs). Railing walls never
    generate axes.
    """
    x_cands = []  # type: List[_Cand]
    y_cands = []  # type: List[_Cand]
    default_t_mm = _mm(DEFAULT_WALL_T_M)

    # footprint boundary: each edge contributes its coordinate, so every corner
    # contributes both of its coordinates, weighted by the edge length
    for orient, bucket, tag in (("v", x_cands, "x"), ("h", y_cands, "y")):
        for pos_mm, lo_mm, hi_mm in footprint.boundary_lines(orient):
            bucket.append(
                _Cand(
                    pos_mm=pos_mm,
                    source=AxisSource.OUTLINE,
                    weight_mm=hi_mm - lo_mm,
                    lo_mm=lo_mm,
                    hi_mm=hi_mm,
                    t_mm=default_t_mm,
                    storey=storey,
                    key="out-s%d-%s-%d-%d" % (storey, tag, pos_mm, lo_mm),
                )
            )

    # walls, ordered by id so the harvest itself does not depend on input order
    for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
        if wall.role == WallRole.RAILING:
            continue
        source = _ROLE_SOURCE.get(wall.role)
        if source is None:
            continue
        axis = wall_axis(wall)
        if axis is None:
            continue
        orient, pos_m, s0_m, s1_m = axis
        lo_mm = _mm(s0_m)
        hi_mm = _mm(s1_m)
        cand = _Cand(
            pos_mm=_mm(pos_m),
            source=source,
            weight_mm=max(0, hi_mm - lo_mm),
            lo_mm=lo_mm,
            hi_mm=hi_mm,
            t_mm=max(1, _mm(wall.thickness_m)),
            storey=storey,
            key=wall.id,
            wall_id=wall.id,
        )
        if orient == "v":
            x_cands.append(cand)
        else:
            y_cands.append(cand)

    # corridors: LONG edges only, the short ends stop against whatever the
    # corridor runs into (frontend rule kept verbatim)
    for rect in model.corridor_rects(storey):
        x0 = _mm(rect[0])
        y0 = _mm(rect[1])
        x1 = _mm(rect[0] + rect[2])
        y1 = _mm(rect[1] + rect[3])
        key = _corridor_key(storey, (x0, y0, x1, y1))
        runs_in_x = (x1 - x0) >= (y1 - y0)
        if runs_in_x:
            for pos_mm in (y0, y1):
                y_cands.append(
                    _Cand(
                        pos_mm=pos_mm,
                        source=AxisSource.CORRIDOR,
                        weight_mm=x1 - x0,
                        lo_mm=x0,
                        hi_mm=x1,
                        t_mm=default_t_mm,
                        storey=storey,
                        key="%s-y%d" % (key, pos_mm),
                        corridor_key=key,
                    )
                )
        else:
            for pos_mm in (x0, x1):
                x_cands.append(
                    _Cand(
                        pos_mm=pos_mm,
                        source=AxisSource.CORRIDOR,
                        weight_mm=y1 - y0,
                        lo_mm=y0,
                        hi_mm=y1,
                        t_mm=default_t_mm,
                        storey=storey,
                        key="%s-x%d" % (key, pos_mm),
                        corridor_key=key,
                    )
                )

    # cores: all four faces, so shaft walls and core columns land on the grid
    for core in sorted(model.cores_on(storey), key=lambda c: c.id):
        x0 = _mm(core.x_m)
        y0 = _mm(core.y_m)
        x1 = _mm(core.x_m + core.w_m)
        y1 = _mm(core.y_m + core.h_m)
        for pos_mm in (x0, x1):
            x_cands.append(
                _Cand(
                    pos_mm=pos_mm,
                    source=AxisSource.CORE,
                    weight_mm=y1 - y0,
                    lo_mm=y0,
                    hi_mm=y1,
                    t_mm=default_t_mm,
                    storey=storey,
                    key="core-%s-x%d" % (core.id, pos_mm),
                )
            )
        for pos_mm in (y0, y1):
            y_cands.append(
                _Cand(
                    pos_mm=pos_mm,
                    source=AxisSource.CORE,
                    weight_mm=x1 - x0,
                    lo_mm=x0,
                    hi_mm=x1,
                    t_mm=default_t_mm,
                    storey=storey,
                    key="core-%s-y%d" % (core.id, pos_mm),
                )
            )

    return (x_cands, y_cands)


# ---------------------------------------------------------------------------
# the grid objects (internal to placement; the wire carries model.GridAxis)
# ---------------------------------------------------------------------------


@dataclass
class Axis:
    """One structural grid line, unioned across storeys.

    `presence` is a bitmask, bit i meaning storey i either contributed a member
    or is spanned through (the line crosses that storey's footprint with no wall
    on it, and columns on it are still framed there).
    """

    dir: AxisDir
    pos_mm: int
    source: AxisSource
    presence: int = 0
    extents_mm: Dict[int, List[Tuple[int, int]]] = field(default_factory=dict)
    member_spans_mm: Dict[int, List[Tuple[int, int, str]]] = field(default_factory=dict)
    members: List[Tuple[int, str]] = field(default_factory=list)
    corridor_keys: Tuple[str, ...] = ()
    candidates: List[_Cand] = field(default_factory=list)
    label: str = ""
    id: str = ""

    @property
    def pos_m(self) -> float:
        return _m(self.pos_mm)

    @property
    def extents(self) -> Dict[int, List[Tuple[float, float]]]:
        """Per storey extents in METRES, the module's outward unit."""
        return {
            storey: [(_m(lo), _m(hi)) for lo, hi in spans]
            for storey, spans in sorted(self.extents_mm.items())
        }

    def present(self, storey: int) -> bool:
        return bool(self.presence & (1 << int(storey)))

    def storeys(self) -> List[int]:
        return sorted(storey for storey in self.extents_mm if self.present(storey))

    def orient(self) -> str:
        """'v' for an X axis (the line x = pos), 'h' for a Y axis."""
        return "v" if self.dir == AxisDir.X else "h"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "dir": self.dir.value,
            "label": self.label,
            "pos_m": round(self.pos_m, 6),
            "source": self.source.value,
            "presence": int(self.presence),
            "storeys": self.storeys(),
            "extents_m": {
                str(storey): [[round(lo, 6), round(hi, 6)] for lo, hi in spans]
                for storey, spans in sorted(self.extents.items())
            },
            "members": [[int(storey), wall] for storey, wall in self.members],
            "corridor_keys": list(self.corridor_keys),
        }


@dataclass
class Junction:
    """A meeting of centrelines on one storey. J: end 1, L 2, T 3, X 4."""

    storey: int
    x_mm: int
    y_mm: int
    j: int
    axis_ids: Tuple[str, str] = ("", "")
    wall_ids: List[str] = field(default_factory=list)

    @property
    def x_m(self) -> float:
        return _m(self.x_mm)

    @property
    def y_m(self) -> float:
        return _m(self.y_mm)

    @property
    def kind(self) -> str:
        return _JUNCTION_KIND.get(int(self.j), "end")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storey": int(self.storey),
            "x_m": round(self.x_m, 6),
            "y_m": round(self.y_m, 6),
            "j": int(self.j),
            "kind": self.kind,
            "axis_ids": [self.axis_ids[0], self.axis_ids[1]],
            "wall_ids": list(self.wall_ids),
        }


@dataclass
class AxisGrid:
    """Axes in both directions, the per-storey junction graph and the ladder."""

    x_axes: List[Axis] = field(default_factory=list)
    y_axes: List[Axis] = field(default_factory=list)
    junctions: Dict[int, List[Junction]] = field(default_factory=dict)
    params: FrameParams = field(default_factory=FrameParams)
    log: DisclosureLog = field(default_factory=DisclosureLog)
    storeys: List[int] = field(default_factory=list)
    footprints: Dict[int, _Footprint] = field(default_factory=dict)

    def axes(self) -> List[Axis]:
        """X axes then Y axes, each ascending in position."""
        return list(self.x_axes) + list(self.y_axes)

    def by_id(self, axis_id_value: str) -> Optional[Axis]:
        for axis in self.axes():
            if axis.id == axis_id_value:
                return axis
        return None

    def axes_in(self, direction: AxisDir) -> List[Axis]:
        return list(self.x_axes if direction == AxisDir.X else self.y_axes)

    def positions_m(self, direction: AxisDir) -> List[float]:
        return [axis.pos_m for axis in self.axes_in(direction)]

    def footprint_rects_m(self, storey: int) -> List[Tuple[float, float, float, float]]:
        """The storey footprint as (x0, y0, x1, y1) metre rects; placement uses it."""
        footprint = self.footprints.get(int(storey))
        return [] if footprint is None else footprint.rects_m()

    def contains(self, storey: int, x_m: float, y_m: float) -> bool:
        """Is this plan point inside or on the storey footprint."""
        footprint = self.footprints.get(int(storey))
        if footprint is None:
            return False
        return footprint.covers(_mm(x_m), _mm(y_m))

    def chord_m(self, storey: int, direction: AxisDir, pos_m: float) -> List[Tuple[float, float]]:
        """Footprint coverage of a line, in metres."""
        footprint = self.footprints.get(int(storey))
        if footprint is None:
            return []
        orient = "v" if direction == AxisDir.X else "h"
        return [(_m(lo), _m(hi)) for lo, hi in footprint.chords_mm(orient, _mm(pos_m))]

    def to_model_axes(self) -> List[GridAxis]:
        """The wire-facing GridAxis list for StructuralModel.axes."""
        return [
            GridAxis(
                id=axis.id,
                dir=axis.dir,
                pos_m=axis.pos_m,
                label=axis.label,
                source=axis.source,
                storeys=axis.storeys(),
            )
            for axis in self.axes()
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Debug view; deterministic under json.dumps(..., sort_keys=True)."""
        return {
            "params": self.params.to_dict(),
            "storeys": list(self.storeys),
            "x_axes": [axis.to_dict() for axis in self.x_axes],
            "y_axes": [axis.to_dict() for axis in self.y_axes],
            "junctions": {
                str(storey): [j.to_dict() for j in self.junctions.get(storey, [])]
                for storey in sorted(self.junctions)
            },
            "footprints_m": {
                str(storey): [
                    [round(v, 6) for v in rect]
                    for rect in self.footprints[storey].rects_m()
                ]
                for storey in sorted(self.footprints)
            },
            "disclosures": self.log.to_dict(),
        }


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

_STAGE = "grid.extract_axes"
_MAX_INSERT_DEPTH = 3


def _storey_footprint(model: StructuralModel, storey: int, log: DisclosureLog) -> _Footprint:
    """Rooms plus the exterior envelope; the wall bounding box as a last resort."""
    polygons = []  # type: List[List[Tuple[int, int]]]
    for room in sorted(model.rooms_on(storey), key=lambda r: r.id):
        if len(room.polygon) < 4:
            continue
        polygons.append([(_mm(p[0]), _mm(p[1])) for p in room.polygon])

    envelope_edges = []  # type: List[Tuple[int, int, int, int]]
    for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
        if wall.role != WallRole.EXTERIOR:
            continue
        envelope_edges.append(
            (_mm(wall.a[0]), _mm(wall.a[1]), _mm(wall.b[0]), _mm(wall.b[1]))
        )
    envelope = _Footprint.from_edges(envelope_edges) if envelope_edges else None

    if polygons or envelope is not None:
        rooms_region = _Footprint.from_polygons(polygons) if polygons else _Footprint([])
        rects = list(rooms_region.rects)
        if envelope is not None:
            rects.extend(envelope.rects)
        footprint = _Footprint.from_rects(rects)
        if not footprint.is_empty():
            return footprint

    walls = [w for w in model.walls_on(storey) if w.role != WallRole.RAILING]
    corners = []  # type: List[Tuple[int, int]]
    for wall in walls:
        corners.append((_mm(wall.a[0]), _mm(wall.a[1])))
        corners.append((_mm(wall.b[0]), _mm(wall.b[1])))
    if corners:
        x0 = min(c[0] for c in corners)
        y0 = min(c[1] for c in corners)
        x1 = max(c[0] for c in corners)
        y1 = max(c[1] for c in corners)
        if x1 > x0 and y1 > y0:
            # Closest registered code: the storey carries no interior plan, so the
            # outline is taken from the wall extents instead of room polygons.
            log.add(
                "W_UNIT_NO_PLAN",
                "storey %d has no rooms and no closed envelope; footprint taken from "
                "the wall bounding box" % storey,
                (),
                stage=_STAGE,
            )
            return _Footprint.from_rects([(x0, y0, x1, y1)])
    return _Footprint([])


def _axis_from_unit(unit: _Unit, direction: AxisDir) -> Axis:
    """Build the union Axis carried by one cross-floor cluster."""
    member_spans_mm = {}  # type: Dict[int, List[Tuple[int, int, str]]]
    members = []  # type: List[Tuple[int, str]]
    corridor_keys = []  # type: List[str]
    for cand in sorted(unit.members, key=lambda c: (c.storey, c.pos_mm, c.key)):
        # third slot is the WALL id, empty for outline, corridor and core faces
        member_spans_mm.setdefault(cand.storey, []).append(
            (cand.lo_mm, cand.hi_mm, cand.wall_id or "")
        )
        if cand.wall_id is not None:
            members.append((cand.storey, cand.wall_id))
        if cand.corridor_key is not None:
            corridor_keys.append(cand.corridor_key)
    return Axis(
        dir=direction,
        pos_mm=unit.pos_mm,
        source=unit.source,
        member_spans_mm={s: sorted(v) for s, v in sorted(member_spans_mm.items())},
        members=sorted(set(members)),
        corridor_keys=tuple(sorted(set(corridor_keys))),
        candidates=sorted(unit.members, key=lambda c: (c.storey, c.pos_mm, c.key)),
    )


def _assign_extents(
    axes: Sequence[Axis],
    other_positions_mm: Sequence[int],
    footprints: Dict[int, _Footprint],
    storeys: Sequence[int],
) -> None:
    """Presence masks and per-storey extents (spec 4.3).

    Member intervals are extended to the nearest crossing perpendicular axis and
    clipped to the footprint; a storey with no member but a footprint chord is a
    span-through storey and takes the chord.
    """
    ordered_other = sorted(set(int(p) for p in other_positions_mm))
    for axis in axes:
        orient = axis.orient()
        for storey in storeys:
            footprint = footprints.get(storey)
            if footprint is None or footprint.is_empty():
                continue
            chords = footprint.chords_mm(orient, axis.pos_mm)
            spans = axis.member_spans_mm.get(storey)
            if spans:
                merged = _merge_intervals([(lo, hi) for lo, hi, _ in spans])
                extended = []  # type: List[Tuple[int, int]]
                for lo, hi in merged:
                    extended.append(
                        _extend_to_perpendicular(
                            axis.pos_mm, lo, hi, orient, ordered_other, footprint
                        )
                    )
                clipped = _clip_intervals(_merge_intervals(extended), chords)
                axis.extents_mm[storey] = clipped if clipped else merged
                axis.presence |= 1 << int(storey)
            elif chords:
                axis.extents_mm[storey] = chords
                axis.presence |= 1 << int(storey)


def _extend_to_perpendicular(
    pos_mm: int,
    lo_mm: int,
    hi_mm: int,
    orient: str,
    other_positions_mm: Sequence[int],
    footprint: _Footprint,
) -> Tuple[int, int]:
    """Extend to a crossing, snapping a near overshoot back to that crossing."""
    tol_join_mm = _mm(DEFAULT_WALL_T_M) // 2 + TOL_JOIN_EXTRA_MM
    below = [
        p for p in other_positions_mm if p <= lo_mm and _crosses(p, pos_mm, orient, footprint)
    ]
    above = [
        p for p in other_positions_mm if p >= hi_mm and _crosses(p, pos_mm, orient, footprint)
    ]
    near_low = [
        p for p in other_positions_mm
        if abs(p - lo_mm) <= tol_join_mm and _crosses(p, pos_mm, orient, footprint)
    ]
    near_high = [
        p for p in other_positions_mm
        if abs(p - hi_mm) <= tol_join_mm and _crosses(p, pos_mm, orient, footprint)
    ]
    low = min(near_low, key=lambda p: (abs(p - lo_mm), p)) if near_low else (max(below) if below else lo_mm)
    high = min(near_high, key=lambda p: (abs(p - hi_mm), p)) if near_high else (min(above) if above else hi_mm)
    return (low, high)


def _warn_axis_offsets(axes: Sequence[Axis], log: DisclosureLog) -> None:
    """Disclose a merge that leaves a wall beyond its non-parametric window."""
    for axis in axes:
        far = [
            cand for cand in axis.candidates
            if cand.wall_id is not None and abs(cand.pos_mm - axis.pos_mm) > cand.t_mm // 2
        ]
        if not far:
            continue
        max_offset = max(abs(cand.pos_mm - axis.pos_mm) for cand in far)
        wall_ids = sorted({str(cand.wall_id) for cand in far if cand.wall_id is not None})
        log.add(
            "N_GRID_AXIS_OFFSET",
            "axis %s is up to %d mm from %d merged wall centreline(s), beyond their tol_wall; "
            "the bounded merge is retained" % (axis.id, max_offset, len(wall_ids)),
            [axis.id] + wall_ids,
            stage=_STAGE,
        )


def _crosses(other_pos_mm: int, pos_mm: int, orient: str, footprint: _Footprint) -> bool:
    if orient == "v":
        return footprint.covers(pos_mm, other_pos_mm)
    return footprint.covers(other_pos_mm, pos_mm)


def _gap_stations_mm(
    lo_mm: int,
    hi_mm: int,
    max_span_mm: int,
    snap_pool_mm: Sequence[int],
    depth: int,
) -> List[int]:
    """Even-fraction stations that bring every sub-gap under the span cap.

    The ideal station first tries to snap to an interior wall cluster within
    0.6 m (a partition is a better bearing line than fresh air); the pool holds
    the per-storey wall clusters, which is normally empty inside a long gap
    because every harvested wall cluster is already a grid axis.
    """
    gap = hi_mm - lo_mm
    if max_span_mm <= 0 or gap <= max_span_mm:
        return []
    count = -(-gap // max_span_mm) - 1  # ceil(gap / max) - 1
    if count <= 0:
        return []
    stations = []  # type: List[int]
    for step in range(1, count + 1):
        ideal = lo_mm + _round_ratio(step * gap, count + 1)
        station = ideal
        if depth == 0 and snap_pool_mm:
            near = [
                p
                for p in snap_pool_mm
                if lo_mm < p < hi_mm and abs(p - ideal) <= _mm(INSERT_SNAP_M)
            ]
            if near:
                station = sorted(near, key=lambda p: (abs(p - ideal), p))[0]
        if lo_mm < station < hi_mm and station not in stations:
            stations.append(station)
    stations.sort()

    if depth + 1 <= _MAX_INSERT_DEPTH:
        extra = []  # type: List[int]
        edges = [lo_mm] + stations + [hi_mm]
        for i in range(len(edges) - 1):
            extra.extend(
                _gap_stations_mm(edges[i], edges[i + 1], max_span_mm, (), depth + 1)
            )
        stations = sorted(set(stations + extra))
    return stations


def _insert_span_control(
    axes: List[Axis],
    direction: AxisDir,
    params: FrameParams,
    footprints: Dict[int, _Footprint],
    snap_pool_mm: Sequence[int],
    log: DisclosureLog,
) -> List[Axis]:
    """Insert axes until no adjacent pair is further apart than the span cap."""
    max_span_m = float(params.max_primary_span)
    if max_span_m > HARD_MAX_SPAN_M:
        log.add(
            "W_RELEASED_CAP",
            "max_primary_span %.3f m is above the %.1f m structural cap; insertion used the cap"
            % (max_span_m, HARD_MAX_SPAN_M),
            (),
            stage=_STAGE,
        )
        max_span_m = HARD_MAX_SPAN_M
    if max_span_m <= 0.0:
        log.add(
            "W_RELEASED_CAP",
            "max_primary_span is not positive; span control insertion was skipped",
            (),
            stage=_STAGE,
        )
        return list(axes)

    max_span_mm = _mm(max_span_m)
    ordered = sorted(axes, key=lambda a: a.pos_mm)
    pool = sorted(set(int(p) for p in snap_pool_mm))
    orient = "v" if direction == AxisDir.X else "h"
    inserted = []  # type: List[Axis]
    for i in range(len(ordered) - 1):
        low_axis = ordered[i]
        high_axis = ordered[i + 1]
        mask = low_axis.presence & high_axis.presence
        for station in _gap_stations_mm(
            low_axis.pos_mm, high_axis.pos_mm, max_span_mm, pool, 0
        ):
            axis = Axis(dir=direction, pos_mm=station, source=AxisSource.INSERTED)
            for storey in sorted(footprints):
                if not mask & (1 << int(storey)):
                    continue
                chords = footprints[storey].chords_mm(orient, station)
                if chords:
                    axis.extents_mm[storey] = chords
                    axis.presence |= 1 << int(storey)
            if axis.presence:
                inserted.append(axis)
    return sorted(ordered + inserted, key=lambda a: a.pos_mm)


def _label_axes(x_axes: Sequence[Axis], y_axes: Sequence[Axis]) -> None:
    """X axes number from 1, Y axes letter from A, both by ascending position."""
    for index, axis in enumerate(sorted(x_axes, key=lambda a: a.pos_mm)):
        axis.label = str(index + 1)
        axis.id = axis_id(AxisDir.X, axis.label)
    for index, axis in enumerate(sorted(y_axes, key=lambda a: a.pos_mm)):
        axis.label = letter_label(index)
        axis.id = axis_id(AxisDir.Y, axis.label)


def _arm_count(spans: Sequence[Tuple[int, int]], point_mm: int, tol_mm: int) -> int:
    """How many ways the extent runs away from the point (0, 1 or 2)."""
    below = 0
    above = 0
    for lo, hi in spans:
        if lo - tol_mm <= point_mm <= hi + tol_mm:
            below = max(below, point_mm - lo)
            above = max(above, hi - point_mm)
    return (1 if below > tol_mm else 0) + (1 if above > tol_mm else 0)


def _covers_point(spans: Sequence[Tuple[int, int]], point_mm: int, tol_mm: int) -> bool:
    for lo, hi in spans:
        if lo - tol_mm <= point_mm <= hi + tol_mm:
            return True
    return False


def _junction_walls(axis: Axis, storey: int, point_mm: int, tol_mm: int) -> List[str]:
    walls = []  # type: List[str]
    for lo, hi, wall in axis.member_spans_mm.get(storey, []):
        if wall and lo - tol_mm <= point_mm <= hi + tol_mm:
            walls.append(wall)
    return walls


def _build_junctions(
    model: StructuralModel,
    x_axes: Sequence[Axis],
    y_axes: Sequence[Axis],
    storeys: Sequence[int],
) -> Dict[int, List[Junction]]:
    """Crossings of perpendicular centrelines, plus free wall ends (spec 4.5)."""
    default_t_mm = _mm(DEFAULT_WALL_T_M)
    junctions = {}  # type: Dict[int, List[Junction]]
    for storey in storeys:
        found = []  # type: List[Junction]
        seen = {}  # type: Dict[Tuple[int, int], Junction]
        live_x = [a for a in x_axes if a.extents_mm.get(storey)]
        live_y = [a for a in y_axes if a.extents_mm.get(storey)]
        for ax in live_x:
            x_spans = ax.extents_mm[storey]
            for ay in live_y:
                y_spans = ay.extents_mm[storey]
                tol_mm = default_t_mm // 2 + TOL_JOIN_EXTRA_MM
                if not _covers_point(x_spans, ay.pos_mm, tol_mm):
                    continue
                if not _covers_point(y_spans, ax.pos_mm, tol_mm):
                    continue
                arms = _arm_count(x_spans, ay.pos_mm, tol_mm) + _arm_count(
                    y_spans, ax.pos_mm, tol_mm
                )
                if arms < 2:
                    continue
                walls = sorted(
                    set(
                        _junction_walls(ax, storey, ay.pos_mm, tol_mm)
                        + _junction_walls(ay, storey, ax.pos_mm, tol_mm)
                    )
                )
                junction = Junction(
                    storey=storey,
                    x_mm=ax.pos_mm,
                    y_mm=ay.pos_mm,
                    j=arms,
                    axis_ids=(ax.id, ay.id),
                    wall_ids=walls,
                )
                found.append(junction)
                seen[(ax.pos_mm, ay.pos_mm)] = junction

        for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
            if wall.role == WallRole.RAILING or _ROLE_SOURCE.get(wall.role) is None:
                continue
            axis = wall_axis(wall)
            if axis is None:
                continue
            orient, pos_m, s0_m, s1_m = axis
            tol_mm = max(default_t_mm, _mm(wall.thickness_m)) // 2 + TOL_JOIN_EXTRA_MM
            for end_m in (s0_m, s1_m):
                if orient == "v":
                    point = (_mm(pos_m), _mm(end_m))
                else:
                    point = (_mm(end_m), _mm(pos_m))
                near = [
                    key
                    for key in sorted(seen)
                    if abs(key[0] - point[0]) <= tol_mm and abs(key[1] - point[1]) <= tol_mm
                ]
                if near:
                    continue
                found.append(
                    Junction(
                        storey=storey,
                        x_mm=point[0],
                        y_mm=point[1],
                        j=1,
                        axis_ids=("", ""),
                        wall_ids=[wall.id],
                    )
                )
                seen[point] = found[-1]
        junctions[storey] = sorted(
            found, key=lambda j: (j.x_mm, j.y_mm, -j.j, j.axis_ids[0], j.axis_ids[1])
        )
    return junctions


def _warn_short_spans(
    axes: Sequence[Axis], params: FrameParams, log: DisclosureLog
) -> None:
    """W_SHORT_SPAN on adjacent pairs under min_span; corridor edge pairs exempt."""
    min_span_mm = _mm(params.min_span)
    ordered = sorted(axes, key=lambda a: a.pos_mm)
    for i in range(len(ordered) - 1):
        low = ordered[i]
        high = ordered[i + 1]
        gap = high.pos_mm - low.pos_mm
        if gap >= min_span_mm:
            continue
        if set(low.corridor_keys) & set(high.corridor_keys):
            continue  # both edges of one corridor: framing the clear width is the point
        log.add(
            "W_SHORT_SPAN",
            "axes %s and %s are %d mm apart, below min_span %d mm"
            % (low.id, high.id, gap, min_span_mm),
            [low.id, high.id],
            stage=_STAGE,
        )


def extract_axes(model: StructuralModel, params: Optional[FrameParams] = None) -> AxisGrid:
    """Harvest, cluster, union, insert and connect the structural axes of a model."""
    params = params if params is not None else FrameParams()
    log = DisclosureLog()
    merge_tol_mm = max(0, _mm(params.merge_tol))

    storeys = sorted(s.index for s in model.storeys)
    if not storeys:
        storeys = sorted(
            set(w.storey for w in model.walls) | set(r.storey for r in model.rooms)
        )

    footprints = {}  # type: Dict[int, _Footprint]
    blank = []  # type: List[int]
    for storey in storeys:
        footprint = _storey_footprint(model, storey, log)
        footprints[storey] = footprint
        if footprint.is_empty():
            blank.append(storey)
    if blank and len(blank) == len(storeys):
        log.add(
            "E_EMPTY_PLAN",
            "no room or wall geometry on any storey; no axes could be extracted",
            (),
            stage=_STAGE,
        )
        return AxisGrid(
            junctions={storey: [] for storey in storeys},
            params=params,
            log=log,
            storeys=storeys,
            footprints=footprints,
        )
    # A stilt or podium level carries no rooms and no walls but still carries the
    # columns of what stands on it, so it inherits the nearest built footprint
    # (above first). Without this every axis above it would read as floating.
    built = [storey for storey in storeys if storey not in blank]
    for storey in blank:
        donors = [s for s in built if s > storey] or [s for s in reversed(built) if s < storey]
        if not donors:
            continue
        footprints[storey] = footprints[donors[0]]
        log.add(
            "W_UNIT_NO_PLAN",
            "storey %d carries no rooms or walls; footprint inherited from storey %d"
            % (storey, donors[0]),
            (),
            stage=_STAGE,
        )

    x_units = []  # type: List[_Unit]
    y_units = []  # type: List[_Unit]
    snap_pool = {"x": [], "y": []}  # type: Dict[str, List[int]]
    for storey in storeys:
        x_cands, y_cands = _harvest(model, storey, footprints[storey])
        for cands, bucket, tag in ((x_cands, x_units, "x"), (y_cands, y_units, "y")):
            clusters = _cluster([_Unit([c]) for c in cands])
            clusters = _cluster(clusters, fixed_tol_mm=merge_tol_mm)
            bucket.extend(clusters)
            for cluster in clusters:
                if cluster.source == AxisSource.WALL:
                    snap_pool[tag].append(cluster.pos_mm)

    x_axes = [
        _axis_from_unit(unit, AxisDir.X)
        for unit in _dedupe_positions(_cluster(x_units, fixed_tol_mm=merge_tol_mm))
    ]
    y_axes = [
        _axis_from_unit(unit, AxisDir.Y)
        for unit in _dedupe_positions(_cluster(y_units, fixed_tol_mm=merge_tol_mm))
    ]

    if params.housing_column_variant in ("toward_start", "toward_end"):
        # Only alternative positions already present in a merged ordinary-wall
        # cluster are eligible. Outline, corridor, party and core anchors stay
        # fixed. The span-control pass below validates the resulting gaps.
        for axes in (x_axes, y_axes):
            ordered = sorted(axes, key=lambda a: a.pos_mm)
            originals = [a.pos_mm for a in ordered]
            for index, axis in enumerate(ordered):
                if axis.source != AxisSource.WALL:
                    continue
                choices = [
                    c.pos_mm for c in axis.candidates
                    if c.wall_id and abs(c.pos_mm - axis.pos_mm) <= merge_tol_mm
                    and (index == 0 or c.pos_mm > originals[index - 1])
                    and (index == len(ordered) - 1 or c.pos_mm < originals[index + 1])
                ]
                if choices:
                    axis.pos_mm = min(choices) if params.housing_column_variant == "toward_start" else max(choices)
        # Discard pre-variant weighted means. Inserted axes may prefer only
        # real ordinary-wall positions still represented by this candidate set.
        snap_pool = {
            tag: sorted({c.pos_mm for axis in axes for c in axis.candidates if c.wall_id and c.source == AxisSource.WALL})
            for tag, axes in (("x", x_axes), ("y", y_axes))
        }

    _assign_extents(x_axes, [a.pos_mm for a in y_axes], footprints, storeys)
    _assign_extents(y_axes, [a.pos_mm for a in x_axes], footprints, storeys)

    x_axes = _insert_span_control(
        x_axes, AxisDir.X, params, footprints, snap_pool["x"], log
    )
    y_axes = _insert_span_control(
        y_axes, AxisDir.Y, params, footprints, snap_pool["y"], log
    )

    _label_axes(x_axes, y_axes)
    _warn_axis_offsets(x_axes, log)
    _warn_axis_offsets(y_axes, log)
    _warn_short_spans(x_axes, params, log)
    _warn_short_spans(y_axes, params, log)
    junctions = _build_junctions(model, x_axes, y_axes, storeys)

    return AxisGrid(
        x_axes=sorted(x_axes, key=lambda a: a.pos_mm),
        y_axes=sorted(y_axes, key=lambda a: a.pos_mm),
        junctions=junctions,
        params=params,
        log=log,
        storeys=storeys,
        footprints=footprints,
    )
