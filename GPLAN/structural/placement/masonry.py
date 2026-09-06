"""Masonry placement: system choice, bearing set, bands, lintels, vertical steel.

What this module is
-------------------
Pure geometry over a `StructuralModel`. `choose_system()` picks between an RC
frame and the two masonry systems; `MasonryPlacer.place()` then decides which
walls bear, closes the slab cover, runs the IS 4326 Table 4 opening checks,
resolves what fails by demoting or strengthening, and places the band, lintel,
vertical bar and tie column geometry. No loads are read here: the takedown runs
after placement, and `placement/foundations.py` (called by the orchestrator with
that takedown) is what turns loads into footings.

What this module is NOT
-----------------------
- It never synthesizes an opening. The adapters own that (finding 10); this
  module reads `model` openings and only labels a check ASSUMED-OPENINGS when
  the geometry it measured did not come from a dressed plan.
- It never carries a copy of a code table. IS 4326 Table 4, Table 6 and Table 7
  and the IS 1905 slenderness rules are read through `codes/is4326.py` and
  `codes/is1905.py` (finding 23); the band geometry is placed here, the band
  bars are specified by those callables.
- It never mutates the user's plan geometry. A wall that needs to be thicker is
  reported as a `GeometryChangeRequest`, an advisory the caller may apply.
- It has no HTTP surface (finding 17): `place` is a library function that
  `structural/api.py run_design` calls.

Units are SI: metres, kN, kPa, MPa. Section dimensions are named `*_mm`. The
plan frame is y-down with storey 0 on the ground, as everywhere in this engine.
Every list this module emits is sorted, so two runs on one model produce
byte-identical `to_dict()` output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..codes import is1905, is4326
from ..model import (
    Band,
    BandKind,
    Beam,
    BeamKind,
    Column,
    Disclosure,
    GEOM_TOL_M,
    Lintel,
    Material,
    Opening,
    Provenance,
    StructuralModel,
    System,
    WallLine,
    WallRole,
    band_id,
    beam_id,
    column_id,
    ft_to_m,
    lintel_id,
    make_disclosure,
    pos_token,
    stack_id,
    wall_axis,
)

PLACED_BY = "placement.masonry"

#: Systems a request may name (finding 26). `mixed` is an internal outcome only.
REQUESTABLE_SYSTEMS = (
    System.RC_FRAME.value,
    System.LOAD_BEARING_MASONRY.value,
    System.CONFINED_MASONRY.value,
)

#: Escalation ladder walked when the cover cannot be closed (spec 7.6).
ESCALATION = (
    System.LOAD_BEARING_MASONRY.value,
    System.CONFINED_MASONRY.value,
    System.RC_FRAME.value,
)

#: IS 4326 storey caps per seismic category, plus the absolute height cap.
MAX_STOREYS_BY_CATEGORY = {"A": 4, "B": 4, "C": 4, "D": 4, "E": 3}

MAX_MASONRY_HEIGHT_M = 15.0

#: Housing level constants (spec 9); metres above the storey's own floor level.
EAVES_HEIGHT_M = ft_to_m(9.5)

PLINTH_DEPTH_M = ft_to_m(0.5)

#: Reusable threshold for the point-load helper. The shipped masonry path
#: already supplies the stronger outcome with unconditional ties at injected
#: beam-line ends and core corners; `tie_columns_for_point_loads()` is not wired
#: into that path.
POINT_LOAD_LIMIT_KN = 25.0

#: Tie column and jamb column plan width along the wall (spec 8), mm.
TIE_COLUMN_WIDTH_MM = 230.0

#: The `Column.code_refs` entry every confining (tie) column this module writes
#: back carries. Together with `placed_by == PLACED_BY` it is the identity that
#: survives into the design layer: `write_back` creates Columns for tie columns
#: and for nothing else, so `is_tie_column` below is exact.
#:
#: It has to survive, because a tie column is NOT a moment frame column. Its
#: section is 230 x t, set by the wall it confines (spec 3 section 8), and IS
#: 4326 does not put it under the IS 13920 Cl 7.1.1 frame minimum of 300 mm.
#: `api._design_members` reads this and the ductile overlay skips that clause.
TIE_COLUMN_CODE_REF = "IS4326:1993 Cl 8.4.8"

_ETA = 1e-9


def is_tie_column(column: Any) -> bool:
    """True for a confining (tie) column placed by this module.

    Keyed on `placed_by` plus the IS 4326 code ref, both of which the model
    serializes, so the identity survives a wire round trip and a re-check of a
    returned model, not just the one process that placed it.
    """
    if str(getattr(column, "placed_by", "")) != PLACED_BY:
        return False
    return TIE_COLUMN_CODE_REF in (getattr(column, "code_refs", None) or ())


# ---------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------


@dataclass
class MasonryParams:
    """Placement knobs. Lengths are METRES unless the name ends in `_mm`.

    `system` follows the frozen request vocabulary auto|rc_frame|
    load_bearing_masonry|confined_masonry; "auto" delegates the whole decision
    to `choose_system` (finding 27). `soil` follows the frozen shape from
    finding 30: {type, sbc_kpa, soft, founding_depth_m}.
    """

    system: str = "auto"
    category: Optional[str] = None
    zone: str = "III"
    importance: float = 1.0
    min_bearing_t_mm: float = 190.0
    confined_min_t_mm: float = 150.0
    never_bearing_t_mm: float = 115.0
    preferred_t_mm: float = 230.0
    max_panel_short_span_m: float = 4.5
    cross_wall_max_m: float = 8.0
    lintel_unify_tol_mm: float = 600.0
    confined_panel_len_factor: float = 1.5
    confined_panel_len_cap_m: float = 4.5
    point_load_limit_kn: float = POINT_LOAD_LIMIT_KN
    assume_default_openings: bool = True
    allow_promote: bool = True
    max_height_m: float = MAX_MASONRY_HEIGHT_M
    mortar_grade: str = "M1"
    roof_type: str = ""
    cast_in_situ_slab: bool = True
    lintel_level_m: float = 2.1
    lintel_bearing_mm: float = 230.0
    lintel_min_bearing_mm: float = 115.0
    lintel_small_opening_m: float = 0.9
    lintel_min_depth_mm: float = 150.0
    lintel_depth_step_mm: float = 75.0
    eaves_height_m: float = EAVES_HEIGHT_M
    plinth_depth_m: float = PLINTH_DEPTH_M
    resolve_passes: int = 3
    soil: Dict[str, Any] = field(default_factory=dict)

    def max_storeys(self, category: str) -> int:
        """The IS 4326 storey cap for this category."""
        return int(MAX_STOREYS_BY_CATEGORY.get(str(category), 3))

    def confined_panel_cap(self, storey_height_m: float) -> float:
        """Longest unconfined masonry panel: min(1.5 h, 4.5 m) by default."""
        return min(
            float(self.confined_panel_len_factor) * float(storey_height_m),
            float(self.confined_panel_len_cap_m),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system": str(self.system),
            "category": self.category,
            "zone": str(self.zone),
            "importance": round(float(self.importance), 6),
            "min_bearing_t_mm": round(float(self.min_bearing_t_mm), 6),
            "confined_min_t_mm": round(float(self.confined_min_t_mm), 6),
            "never_bearing_t_mm": round(float(self.never_bearing_t_mm), 6),
            "max_panel_short_span_m": round(float(self.max_panel_short_span_m), 6),
            "cross_wall_max_m": round(float(self.cross_wall_max_m), 6),
            "lintel_unify_tol_mm": round(float(self.lintel_unify_tol_mm), 6),
            "confined_panel_len_factor": round(float(self.confined_panel_len_factor), 6),
            "confined_panel_len_cap_m": round(float(self.confined_panel_len_cap_m), 6),
            "point_load_limit_kn": round(float(self.point_load_limit_kn), 6),
            "assume_default_openings": bool(self.assume_default_openings),
            "allow_promote": bool(self.allow_promote),
            "max_height_m": round(float(self.max_height_m), 6),
            "mortar_grade": str(self.mortar_grade),
            "roof_type": str(self.roof_type),
            "cast_in_situ_slab": bool(self.cast_in_situ_slab),
            "lintel_level_m": round(float(self.lintel_level_m), 6),
            "lintel_bearing_mm": round(float(self.lintel_bearing_mm), 6),
            "lintel_min_depth_mm": round(float(self.lintel_min_depth_mm), 6),
            "eaves_height_m": round(float(self.eaves_height_m), 6),
            "plinth_depth_m": round(float(self.plinth_depth_m), 6),
            "resolve_passes": int(self.resolve_passes),
            "soil": {str(key): _plain(self.soil[key]) for key in sorted(self.soil)},
        }


def _plain(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    return str(value)


# ---------------------------------------------------------------------------
# result records
# ---------------------------------------------------------------------------


@dataclass
class Refusal:
    """A system the caller asked for and this module would not produce."""

    clause: str
    reason: str
    code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"clause": self.clause, "reason": self.reason, "code": self.code}


@dataclass
class SystemDecision:
    """What `choose_system` decided, and the row-by-row reasoning that got there."""

    system: str
    requested: str
    category: str
    refused: Optional[Refusal] = None
    labeled: bool = False
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system": self.system,
            "system_requested": self.requested,
            "system_used": self.system,
            "category": self.category,
            "refused": None if self.refused is None else self.refused.to_dict(),
            "labeled": bool(self.labeled),
            "trace": list(self.trace),
        }


@dataclass
class GeometryChangeRequest:
    """Advisory only: the plan is never edited here (spec 14, hard rule)."""

    wall_id: str
    storey: int
    field: str
    current_mm: float
    requested_mm: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "storey": int(self.storey),
            "field": self.field,
            "current_mm": round(float(self.current_mm), 3),
            "requested_mm": round(float(self.requested_mm), 3),
            "reason": self.reason,
        }


@dataclass
class Pilaster:
    """A t x 3t stiffening projection injected where cross walls are too far apart."""

    id: str
    wall_id: str
    storey: int
    x_m: float
    y_m: float
    t_mm: float
    projection_mm: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "wall_id": self.wall_id,
            "storey": int(self.storey),
            "x_m": round(float(self.x_m), 6),
            "y_m": round(float(self.y_m), 6),
            "t_mm": round(float(self.t_mm), 3),
            "projection_mm": round(float(self.projection_mm), 3),
            "reason": self.reason,
        }


@dataclass
class TieColumn:
    """A confining column cast against toothed masonry; 230 x t in plan."""

    id: str
    x_m: float
    y_m: float
    w_mm: float
    d_mm: float
    storeys: List[int]
    reason: str
    wall_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x_m": round(float(self.x_m), 6),
            "y_m": round(float(self.y_m), 6),
            "w_mm": round(float(self.w_mm), 3),
            "d_mm": round(float(self.d_mm), 3),
            "storeys": [int(s) for s in self.storeys],
            "reason": self.reason,
            "wall_id": self.wall_id,
        }


@dataclass
class VerticalBar:
    """One run of vertical steel through the bands, IS 4326 Table 7."""

    id: str
    x_m: float
    y_m: float
    dia_mm: int
    from_storey: int
    to_storey: int
    position: str
    clause: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x_m": round(float(self.x_m), 6),
            "y_m": round(float(self.y_m), 6),
            "dia_mm": int(self.dia_mm),
            "from_storey": int(self.from_storey),
            "to_storey": int(self.to_storey),
            "position": self.position,
            "clause": self.clause,
        }


@dataclass
class Panel:
    """One slab region bounded by the current support lines."""

    id: str
    storey: int
    x_m: float
    y_m: float
    w_m: float
    h_m: float
    area_m2: float
    unsupported_m: float = 0.0
    unsupported_long_m: float = 0.0
    edge_ids: List[str] = field(default_factory=list)

    @property
    def short_span_m(self) -> float:
        return min(self.w_m, self.h_m)

    @property
    def long_span_m(self) -> float:
        return max(self.w_m, self.h_m)

    @property
    def two_way(self) -> bool:
        short = self.short_span_m
        if short <= _ETA:
            return False
        return (self.long_span_m / short) <= 2.0 + _ETA

    def needs(self, cap_m: float) -> List[str]:
        """Every reason this panel is not covered yet, in a stable order."""
        out = []  # type: List[str]
        if self.short_span_m > cap_m + _ETA:
            out.append("short_span")
        if self.two_way:
            if self.unsupported_m > GEOM_TOL_M:
                out.append("edge")
        elif self.unsupported_long_m > GEOM_TOL_M:
            out.append("edge")
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "storey": int(self.storey),
            "x_m": round(float(self.x_m), 6),
            "y_m": round(float(self.y_m), 6),
            "w_m": round(float(self.w_m), 6),
            "h_m": round(float(self.h_m), 6),
            "area_m2": round(float(self.area_m2), 6),
            "short_span_m": round(float(self.short_span_m), 6),
            "long_span_m": round(float(self.long_span_m), 6),
            "two_way": bool(self.two_way),
            "unsupported_m": round(float(self.unsupported_m), 6),
            "unsupported_long_m": round(float(self.unsupported_long_m), 6),
        }


@dataclass
class CoverGap:
    """A panel the greedy cover could not close with the walls it was given."""

    panel_id: str
    storey: int
    need: str
    value_m: float
    limit_m: float
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "storey": int(self.storey),
            "need": self.need,
            "value_m": round(float(self.value_m), 6),
            "limit_m": round(float(self.limit_m), 6),
            "message": self.message,
        }


@dataclass
class WallReport:
    """One row of the per-wall report (spec 12)."""

    wall_id: str
    storey: int
    t_mm: float
    role: str
    action: str = "NON-BEARING"
    eligibility: List[str] = field(default_factory=list)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    assumed_openings: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "storey": int(self.storey),
            "t_mm": round(float(self.t_mm), 3),
            "role": self.role,
            "action": self.action,
            "eligibility": list(self.eligibility),
            "checks": [dict(check) for check in self.checks],
            "detail": self.detail,
            "assumed_openings": bool(self.assumed_openings),
        }


@dataclass
class BandRow:
    """One band in the schedule: where it runs and what steel it carries."""

    band_id: str
    kind: str
    storey: int
    level_m: float
    wall_ids: List[str]
    span_m: float
    spec: Optional[Dict[str, Any]]
    closed_loop: bool
    open_ends: List[str]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "band_id": self.band_id,
            "kind": self.kind,
            "storey": int(self.storey),
            "level_m": round(float(self.level_m), 6),
            "wall_ids": list(self.wall_ids),
            "span_m": round(float(self.span_m), 6),
            "spec": None if self.spec is None else dict(self.spec),
            "closed_loop": bool(self.closed_loop),
            "open_ends": list(self.open_ends),
            "note": self.note,
        }


@dataclass
class LintelRun:
    """One lintel or merged lintel run over openings in a bearing wall."""

    id: str
    wall_id: str
    storey: int
    opening_ids: List[str]
    clear_span_m: float
    bearing_mm: float
    depth_mm: float
    level_m: float
    merged: bool
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "wall_id": self.wall_id,
            "storey": int(self.storey),
            "opening_ids": list(self.opening_ids),
            "clear_span_m": round(float(self.clear_span_m), 6),
            "bearing_mm": round(float(self.bearing_mm), 3),
            "depth_mm": round(float(self.depth_mm), 3),
            "level_m": round(float(self.level_m), 6),
            "merged": bool(self.merged),
            "note": self.note,
        }


@dataclass
class MasonryPlacement:
    """Everything `place()` decided, ready for the report and the model."""

    system: SystemDecision
    params: MasonryParams
    bearing_walls: List[str] = field(default_factory=list)
    demoted: List[Dict[str, Any]] = field(default_factory=list)
    promoted: List[GeometryChangeRequest] = field(default_factory=list)
    bands: List[Band] = field(default_factory=list)
    band_schedule: List[BandRow] = field(default_factory=list)
    lintels: List[Lintel] = field(default_factory=list)
    lintel_schedule: List[LintelRun] = field(default_factory=list)
    vertical_bars: List[VerticalBar] = field(default_factory=list)
    tie_columns: List[TieColumn] = field(default_factory=list)
    pilasters: List[Pilaster] = field(default_factory=list)
    hybrid_beams: List[Beam] = field(default_factory=list)
    panels: List[Panel] = field(default_factory=list)
    cover_gaps: List[CoverGap] = field(default_factory=list)
    violations_resolved: List[Dict[str, Any]] = field(default_factory=list)
    per_wall_reports: List[WallReport] = field(default_factory=list)
    warnings: List[Disclosure] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system": self.system.to_dict(),
            "params": self.params.to_dict(),
            "bearing_walls": list(self.bearing_walls),
            "demoted": [dict(row) for row in self.demoted],
            "promoted": [row.to_dict() for row in self.promoted],
            "bands": [
                {
                    "id": band.id,
                    "kind": band.kind.value if hasattr(band.kind, "value") else str(band.kind),
                    "storey": int(band.storey),
                    "level_m": round(float(band.level_m), 6),
                    "wall_ids": list(band.wall_ids),
                }
                for band in self.bands
            ],
            "band_schedule": [row.to_dict() for row in self.band_schedule],
            "lintels": [
                {
                    "id": lin.id,
                    "wall_id": lin.wall_id,
                    "opening_id": lin.opening_id,
                    "span_m": round(float(lin.span_m), 6),
                }
                for lin in self.lintels
            ],
            "lintel_schedule": [row.to_dict() for row in self.lintel_schedule],
            "vertical_bars": [bar.to_dict() for bar in self.vertical_bars],
            "tie_columns": [col.to_dict() for col in self.tie_columns],
            "pilasters": [row.to_dict() for row in self.pilasters],
            "hybrid_beams": [
                {
                    "id": beam.id,
                    "storey": int(beam.storey),
                    "a_m": [round(float(beam.a[0]), 6), round(float(beam.a[1]), 6)],
                    "b_m": [round(float(beam.b[0]), 6), round(float(beam.b[1]), 6)],
                    "width_m": round(float(beam.width_m), 6),
                    "supports_wall_id": beam.supports_wall_id,
                }
                for beam in self.hybrid_beams
            ],
            "panels": [panel.to_dict() for panel in self.panels],
            "cover_gaps": [gap.to_dict() for gap in self.cover_gaps],
            "violations_resolved": [dict(row) for row in self.violations_resolved],
            "per_wall_reports": [row.to_dict() for row in self.per_wall_reports],
            "warnings": [entry.to_dict() for entry in self.warnings],
            "trace": list(self.trace),
        }

    # -- model writes -------------------------------------------------------

    def write_back(self, model: StructuralModel) -> StructuralModel:
        """Write bands, lintels, tie columns, hybrid beams and bearing flags in.

        Idempotent: anything this module placed before is dropped first, so a
        second call on the same model produces the same model, not a duplicate.
        """
        model.bands = [band for band in model.bands if band.placed_by != PLACED_BY]
        model.lintels = [lin for lin in model.lintels if lin.placed_by != PLACED_BY]
        model.columns = [col for col in model.columns if col.placed_by != PLACED_BY]
        model.beams = [beam for beam in model.beams if beam.placed_by != PLACED_BY]

        bearing = set(self.bearing_walls)
        for wall in model.walls:
            wall.bearing = wall.id in bearing

        model.bands.extend(self.bands)
        model.lintels.extend(self.lintels)
        model.beams.extend(self.hybrid_beams)
        for tie in self.tie_columns:
            for storey in tie.storeys:
                model.columns.append(
                    Column(
                        id=column_id(storey, x_m=tie.x_m, y_m=tie.y_m),
                        stack_id=stack_id(x_m=tie.x_m, y_m=tie.y_m),
                        storey=int(storey),
                        x_m=float(tie.x_m),
                        y_m=float(tie.y_m),
                        width_m=float(tie.w_mm) / 1000.0,
                        depth_m=float(tie.d_mm) / 1000.0,
                        placed_by=PLACED_BY,
                        code_refs=[TIE_COLUMN_CODE_REF],
                    )
                )
        model.columns.sort(key=lambda col: (col.storey, col.id))
        model.system = System(self.system.system)
        model.meta["masonry_placement"] = self.to_dict()
        seen = {(entry.code, entry.message) for entry in model.warnings}
        for entry in self.warnings:
            if (entry.code, entry.message) in seen:
                continue  # a second write_back must leave the ladder as it was
            seen.add((entry.code, entry.message))
            model.add_warning(
                entry.code,
                entry.message,
                entry.element_ids,
                clause=entry.clause,
                stage=entry.stage,
            )
        return model


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------


def _mm(value_m: float) -> int:
    """Metres to integer millimetres."""
    return int(round(float(value_m) * 1000.0))


def _t_mm(wall: WallLine) -> float:
    """Wall thickness in millimetres."""
    return float(wall.thickness_m) * 1000.0


def _axis_of(wall: WallLine) -> Optional[Tuple[str, float, float, float]]:
    """('h'|'v', centreline position, low, high) in metres, or None if skew."""
    return wall_axis(wall)


def _line_key(orient: str, pos_m: float) -> Tuple[str, int]:
    return (orient, _mm(pos_m))


def _point_of(orient: str, pos_m: float, station_m: float) -> Tuple[float, float]:
    """The plan point at `station_m` along a line of this orientation."""
    if orient == "h":
        return (float(station_m), float(pos_m))
    return (float(pos_m), float(station_m))


def _opening_interval(wall: WallLine, opening: Opening) -> Tuple[float, float]:
    """Absolute (low, high) station of an opening on its wall's axis, metres.

    Reported as drawn, never clipped to the wall: an opening that pokes past its
    wall end is an input the code checks are meant to catch, not one to hide.
    """
    axis = _axis_of(wall)
    if axis is None:
        return (0.0, 0.0)
    orient, _pos, _lo, _hi = axis
    start = wall.a[0] if orient == "h" else wall.a[1]
    end = wall.b[0] if orient == "h" else wall.b[1]
    sign = 1.0 if end >= start else -1.0
    centre = start + sign * float(opening.offset_m)
    half = 0.5 * float(opening.width_m)
    return (min(centre - half, centre + half), max(centre - half, centre + half))


def _merge_intervals(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Union of closed intervals, sorted, touching intervals merged."""
    ordered = sorted((float(lo), float(hi)) for lo, hi in intervals if float(hi) - float(lo) > _ETA)
    out = []  # type: List[Tuple[float, float]]
    for lo, hi in ordered:
        if out and lo <= out[-1][1] + GEOM_TOL_M:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _covers(intervals: Sequence[Tuple[float, float]], lo: float, hi: float) -> bool:
    """True when the merged intervals contain [lo, hi] whole."""
    for a, b in intervals:
        if a <= lo + GEOM_TOL_M and b >= hi - GEOM_TOL_M:
            return True
    return False


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """Length shared by two intervals, zero when they only touch."""
    return max(0.0, min(a1, b1) - max(a0, b0))


def _round_up(value: float, step: float) -> float:
    """`value` rounded up to a whole number of `step`."""
    if step <= 0.0:
        return float(value)
    return math.ceil(float(value) / float(step) - 1e-9) * float(step)


def _storey_height(model: StructuralModel, storey: int) -> float:
    record = model.storey(storey)
    if record is None:
        return ft_to_m(10.4)
    return float(record.height_m)


def _storey_base(model: StructuralModel, storey: int) -> float:
    record = model.storey(storey)
    if record is None:
        return 0.0
    return float(record.bottom_z_m)


def _roof_type(model: StructuralModel, params: MasonryParams) -> str:
    """Roof type from params, else the model's roof meta, else flat."""
    if params.roof_type:
        return str(params.roof_type)
    roof = model.meta.get("roof")
    if isinstance(roof, dict) and roof.get("type"):
        return str(roof["type"])
    return "flat"


def _soft_soil(params: MasonryParams) -> bool:
    soil = params.soil if isinstance(params.soil, dict) else {}
    return bool(soil.get("soft", False)) or bool(soil.get("fill", False))


def _masonry_walls(model: StructuralModel, storey: Optional[int] = None) -> List[WallLine]:
    """Axis-aligned masonry walls, sorted by id; parapets and railings excluded."""
    out = []
    for wall in model.walls:
        if storey is not None and wall.storey != storey:
            continue
        if _axis_of(wall) is None:
            continue
        if wall.role in (WallRole.PARAPET, WallRole.RAILING):
            continue
        if wall.material not in (Material.BRICK_MASONRY,):
            continue
        out.append(wall)
    return sorted(out, key=lambda w: w.id)


def _storeys_of(model: StructuralModel) -> List[int]:
    return sorted({int(s.index) for s in model.storeys}) or sorted({w.storey for w in model.walls})


def _tie_break(wall: WallLine) -> Tuple[float, float, float, str]:
    """Spec 1: length desc, then min x, then min y, then id."""
    xs = min(wall.a[0], wall.b[0])
    ys = min(wall.a[1], wall.b[1])
    return (-wall.length_m(), xs, ys, wall.id)


# ---------------------------------------------------------------------------
# eligibility (spec 4)
# ---------------------------------------------------------------------------


@dataclass
class _Eligibility:
    """Why one wall may or may not bear, on one storey."""

    wall_id: str
    storey: int
    t_mm: float
    never_bearing: bool
    thickness_ok: bool
    confined_only: bool
    stacked: bool
    grounded: bool
    sr: float
    sr_ok: bool
    party: bool
    reasons: List[str] = field(default_factory=list)

    def eligible(self, system: str) -> bool:
        """True when this wall may carry slab load under `system`."""
        if self.never_bearing:
            return False
        if not self.thickness_ok:
            return False
        if self.confined_only and system != System.CONFINED_MASONRY.value:
            return False
        return self.stacked and self.grounded and self.sr_ok


def _stack_index(model: StructuralModel) -> Dict[str, Dict[str, Any]]:
    """wall id -> its `build_wall_stacks()` record (finding 9's shared helper)."""
    out = {}  # type: Dict[str, Dict[str, Any]]
    for stack in model.build_wall_stacks():
        for wall_id in stack["walls"].values():
            out[str(wall_id)] = stack
    return out


def _eligibility(
    model: StructuralModel,
    params: MasonryParams,
    walls: Sequence[WallLine],
    stacks: Dict[str, Dict[str, Any]],
) -> Dict[str, _Eligibility]:
    """The per-wall bearing screen of spec 4, for every masonry wall in `walls`."""
    storeys = _storeys_of(model)
    total = max(1, len(storeys))
    out = {}  # type: Dict[str, _Eligibility]
    for wall in sorted(walls, key=lambda w: w.id):
        t_mm = _t_mm(wall)
        reasons = []  # type: List[str]
        never_bearing = t_mm <= float(params.never_bearing_t_mm) + _ETA
        thickness_ok = t_mm >= float(params.confined_min_t_mm) - _ETA
        confined_only = thickness_ok and t_mm < float(params.min_bearing_t_mm) - _ETA
        if never_bearing:
            reasons.append(
                "t %d mm is at or below the %d mm never-bearing floor; no override"
                % (int(round(t_mm)), int(round(params.never_bearing_t_mm)))
            )
        elif not thickness_ok:
            reasons.append(
                "t %d mm is below the %d mm confined minimum"
                % (int(round(t_mm)), int(round(params.confined_min_t_mm)))
            )
        elif confined_only:
            reasons.append(
                "t %d mm bears only under confined_masonry (%d mm is the load bearing minimum)"
                % (int(round(t_mm)), int(round(params.min_bearing_t_mm)))
            )
        elif t_mm < float(params.preferred_t_mm) - _ETA:
            reasons.append(
                "t %d mm admitted, %d mm preferred" % (int(round(t_mm)), int(round(params.preferred_t_mm)))
            )

        stack = stacks.get(wall.id)
        grounded = bool(stack and stack.get("grounded"))
        stacked = True
        if stack is None:
            stacked = False
            reasons.append("wall is in no stack")
        else:
            present = set(int(s) for s in stack["walls"].keys())
            below = set(range(0, int(wall.storey) + 1))
            if not below.issubset(present):
                stacked = False
                missing = sorted(below - present)
                reasons.append(
                    "no wall below on storey(s) "
                    + ", ".join(str(s) for s in missing)
                    + "; masonry never transfers"
                )
            offset_mm = float(stack.get("max_offset_m", 0.0)) * 1000.0
            if offset_mm > 0.5 * t_mm + 1.0:
                stacked = False
                reasons.append(
                    "centreline offset %d mm exceeds t/2 = %d mm"
                    % (int(round(offset_mm)), int(round(0.5 * t_mm)))
                )
        if not grounded:
            reasons.append("stack does not reach the ground")

        height = _storey_height(model, int(wall.storey))
        heff = is1905.effective_height(height, "full", "full")
        teff = is1905.effective_thickness(float(wall.thickness_m))
        sr = is1905.slenderness_ratio(heff, None, teff)
        sr_ok = is1905.check_max_slenderness(sr, total, params.mortar_grade)
        if not sr_ok:
            reasons.append(
                "slenderness %.1f is past the IS 1905 Cl 4.6.1 cap of %.0f"
                % (sr, is1905.max_slenderness(params.mortar_grade))
            )
        party = wall.role == WallRole.PARTY
        if party:
            reasons.append("party wall: its strip footing is eccentric, see foundations")
        out[wall.id] = _Eligibility(
            wall_id=wall.id,
            storey=int(wall.storey),
            t_mm=t_mm,
            never_bearing=never_bearing,
            thickness_ok=thickness_ok,
            confined_only=confined_only,
            stacked=stacked,
            grounded=grounded,
            sr=sr,
            sr_ok=sr_ok,
            party=party,
            reasons=reasons,
        )
    return out


# ---------------------------------------------------------------------------
# panels: a cell decomposition bounded by the current support lines (spec 5)
# ---------------------------------------------------------------------------


def _footprint(model: StructuralModel, storey: int, walls: Sequence[WallLine]):
    """The built plan area of one storey, as a shapely geometry.

    Room polygons tile a housing plot exactly, so their union is the footprint
    whenever the rooms cover most of the wall bounding box. Otherwise the wall
    bounding box is the footprint, which is exact for a rectangular plot and
    conservative for any other.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    xs = []  # type: List[float]
    ys = []  # type: List[float]
    for wall in walls:
        xs.extend([wall.a[0], wall.b[0]])
        ys.extend([wall.a[1], wall.b[1]])
    if not xs:
        return None
    box = Polygon([(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))])
    if box.area <= _ETA:
        return None
    polys = []
    for room in sorted(model.rooms_on(storey), key=lambda r: r.id):
        if len(room.polygon) >= 3:
            poly = Polygon([(float(p[0]), float(p[1])) for p in room.polygon])
            if poly.is_valid and poly.area > _ETA:
                polys.append(poly)
    if polys:
        union = unary_union(polys)
        if union.area >= 0.5 * box.area:
            return union
    return box


class _StoreyGrid:
    """The fixed cell decomposition of one storey, cut on every wall line.

    Cells never change; only the support lines drawn through them do, so one
    grid serves the greedy cover, every candidate dry run and the final panels.
    """

    def __init__(self, model: StructuralModel, storey: int, walls: Sequence[WallLine]) -> None:
        from shapely.geometry import Point

        self.storey = int(storey)
        self.model = model
        self.walls = list(walls)
        xs = set()
        ys = set()
        for wall in walls:
            axis = _axis_of(wall)
            if axis is None:
                continue
            orient, pos, lo, hi = axis
            if orient == "v":
                xs.add(_mm(pos))
                ys.add(_mm(lo))
                ys.add(_mm(hi))
            else:
                ys.add(_mm(pos))
                xs.add(_mm(lo))
                xs.add(_mm(hi))
        self.footprint = _footprint(model, storey, walls)
        if self.footprint is not None:
            minx, miny, maxx, maxy = self.footprint.bounds
            xs.update([_mm(minx), _mm(maxx)])
            ys.update([_mm(miny), _mm(maxy)])
        self.xs = [value / 1000.0 for value in sorted(xs)]
        self.ys = [value / 1000.0 for value in sorted(ys)]
        self.nx = max(0, len(self.xs) - 1)
        self.ny = max(0, len(self.ys) - 1)
        self.inside = [[False] * self.ny for _ in range(self.nx)]
        if self.footprint is None:
            return
        for i in range(self.nx):
            cx = 0.5 * (self.xs[i] + self.xs[i + 1])
            for j in range(self.ny):
                cy = 0.5 * (self.ys[j] + self.ys[j + 1])
                self.inside[i][j] = bool(self.footprint.contains(Point(cx, cy)))

    def has_cells(self) -> bool:
        """True when the storey has any built area to cover."""
        return self.nx > 0 and self.ny > 0 and any(any(column) for column in self.inside)

    def bbox(self) -> Tuple[float, float, float, float]:
        """(x, y, w, h) of the storey footprint in metres."""
        if self.footprint is None:
            return (0.0, 0.0, 0.0, 0.0)
        minx, miny, maxx, maxy = self.footprint.bounds
        return (minx, miny, maxx - minx, maxy - miny)

    # -- panel tracing ------------------------------------------------------

    def panels(self, support: Dict[Tuple[str, int], List[Tuple[float, float]]]) -> List[Panel]:
        """Trace the regions the current support lines leave, as `Panel` records."""
        label = {}  # type: Dict[Tuple[int, int], int]
        parent = {}  # type: Dict[int, int]

        def find(node):
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def join(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        index = 0
        for i in range(self.nx):
            for j in range(self.ny):
                if self.inside[i][j]:
                    label[(i, j)] = index
                    parent[index] = index
                    index += 1
        for i in range(self.nx):
            for j in range(self.ny):
                if not self.inside[i][j]:
                    continue
                if i + 1 < self.nx and self.inside[i + 1][j]:
                    if not self._blocked("v", self.xs[i + 1], self.ys[j], self.ys[j + 1], support):
                        join(label[(i, j)], label[(i + 1, j)])
                if j + 1 < self.ny and self.inside[i][j + 1]:
                    if not self._blocked("h", self.ys[j + 1], self.xs[i], self.xs[i + 1], support):
                        join(label[(i, j)], label[(i, j + 1)])

        groups = {}  # type: Dict[int, List[Tuple[int, int]]]
        for cell, idx in sorted(label.items()):
            groups.setdefault(find(idx), []).append(cell)

        panels = []  # type: List[Panel]
        for key in sorted(groups):
            cells = groups[key]
            xs = [self.xs[i] for i, _ in cells] + [self.xs[i + 1] for i, _ in cells]
            ys = [self.ys[j] for _, j in cells] + [self.ys[j + 1] for _, j in cells]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            area = sum((self.xs[i + 1] - self.xs[i]) * (self.ys[j + 1] - self.ys[j]) for i, j in cells)
            panel = Panel(id="", storey=self.storey, x_m=x0, y_m=y0, w_m=x1 - x0, h_m=y1 - y0, area_m2=area)
            member = set(cells)
            long_is_x = panel.w_m >= panel.h_m
            for i, j in sorted(cells):
                for orient, pos, lo, hi, neighbour in (
                    ("v", self.xs[i], self.ys[j], self.ys[j + 1], (i - 1, j)),
                    ("v", self.xs[i + 1], self.ys[j], self.ys[j + 1], (i + 1, j)),
                    ("h", self.ys[j], self.xs[i], self.xs[i + 1], (i, j - 1)),
                    ("h", self.ys[j + 1], self.xs[i], self.xs[i + 1], (i, j + 1)),
                ):
                    if neighbour in member:
                        continue
                    ni, nj = neighbour
                    if 0 <= ni < self.nx and 0 <= nj < self.ny and self.inside[ni][nj]:
                        continue  # a support line already separates two panels here
                    if self._blocked(orient, pos, lo, hi, support):
                        continue
                    length = hi - lo
                    panel.unsupported_m += length
                    if (orient == "h") == long_is_x:
                        panel.unsupported_long_m += length
            panels.append(panel)

        panels.sort(key=lambda p: (round(p.x_m, 6), round(p.y_m, 6), round(p.w_m, 6), round(p.h_m, 6)))
        for order, panel in enumerate(panels):
            panel.id = "pnl-s%d-%d" % (self.storey, order)
        return panels

    def boundary_on_line(self, orient: str, pos: float, lo: float, hi: float) -> float:
        """Length of panel edge this line would create, used to score candidates."""
        total = 0.0
        if orient == "v":
            if _mm(pos) not in [_mm(x) for x in self.xs]:
                return 0.0
            i = [_mm(x) for x in self.xs].index(_mm(pos))
            for j in range(self.ny):
                left = self.inside[i - 1][j] if i - 1 >= 0 else False
                right = self.inside[i][j] if i < self.nx else False
                if not (left or right):
                    continue
                seg_lo, seg_hi = self.ys[j], self.ys[j + 1]
                total += _overlap(seg_lo, seg_hi, lo, hi)
        else:
            if _mm(pos) not in [_mm(y) for y in self.ys]:
                return 0.0
            j = [_mm(y) for y in self.ys].index(_mm(pos))
            for i in range(self.nx):
                up = self.inside[i][j - 1] if j - 1 >= 0 else False
                down = self.inside[i][j] if j < self.ny else False
                if not (up or down):
                    continue
                seg_lo, seg_hi = self.xs[i], self.xs[i + 1]
                total += _overlap(seg_lo, seg_hi, lo, hi)
        return total

    def _blocked(
        self,
        orient: str,
        pos: float,
        lo: float,
        hi: float,
        support: Dict[Tuple[str, int], List[Tuple[float, float]]],
    ) -> bool:
        """True when a support line of this orientation covers [lo, hi] at `pos`."""
        return _covers(support.get(_line_key(orient, pos), []), lo, hi)


def _support_lines(
    walls: Sequence[WallLine],
    bearing: Sequence[str],
    extra: Sequence[Tuple[str, float, float, float]] = (),
) -> Dict[Tuple[str, int], List[Tuple[float, float]]]:
    """Merged support intervals per line, from bearing walls plus injected beams."""
    raw = {}  # type: Dict[Tuple[str, int], List[Tuple[float, float]]]
    chosen = set(bearing)
    for wall in walls:
        if wall.id not in chosen:
            continue
        axis = _axis_of(wall)
        if axis is None:
            continue
        orient, pos, lo, hi = axis
        raw.setdefault(_line_key(orient, pos), []).append((lo, hi))
    for orient, pos, lo, hi in extra:
        raw.setdefault(_line_key(orient, pos), []).append((lo, hi))
    return {key: _merge_intervals(value) for key, value in sorted(raw.items())}


#: A cover with nothing left to fix.
CLEAN = (0, 0.0, 0.0)


def _badness(panels: Sequence[Panel], cap_m: float) -> Tuple[int, float, float]:
    """How far the cover still is from done, worst first.

    (unsupported required edges, worst single span excess, total excess area).
    The worst-span term leads because spec 5.3 scores candidates on worst-span
    reduction; the area term breaks the tie so a wall that halves an oversized
    panel still counts as progress even when the worst span does not move.
    """
    edges = 0
    worst = 0.0
    area = 0.0
    for panel in panels:
        needs = panel.needs(cap_m)
        if "edge" in needs:
            edges += 1
        if "short_span" in needs:
            excess = panel.short_span_m - cap_m
            worst = max(worst, excess)
            area += excess * panel.long_span_m
    return (edges, round(worst, 9), round(area, 9))


# ---------------------------------------------------------------------------
# greedy cover (spec 5)
# ---------------------------------------------------------------------------


def _is_perimeter(wall: WallLine, grid: _StoreyGrid) -> bool:
    """Exterior and party walls bear by definition, as does anything on the outline."""
    if wall.role in (WallRole.EXTERIOR, WallRole.PARTY):
        return True
    axis = _axis_of(wall)
    if axis is None or grid.footprint is None:
        return False
    orient, pos, _lo, _hi = axis
    x0, y0, w, h = grid.bbox()
    if orient == "v":
        return _mm(pos) in (_mm(x0), _mm(x0 + w))
    return _mm(pos) in (_mm(y0), _mm(y0 + h))


@dataclass
class _CoverResult:
    """One storey after the greedy cover has run."""

    storey: int
    bearing: List[str]
    panels: List[Panel]
    gaps: List[CoverGap]
    trace: List[str]
    seeded: List[str]


def _low_rise_housing(model: StructuralModel) -> bool:
    return getattr(model.source, "value", model.source) == "housing" and 1 <= len(model.storeys) <= 3


def _housing_role_split_groups(model: StructuralModel, candidates: Sequence[WallLine]) -> List[List[WallLine]]:
    """Contiguous real-wall pieces whose architectural roles differ.

    Housing preserves the true extent of a core wall instead of leaking that
    role onto the adjacent interior run. A greedy single-ID promotion can then
    miss a continuous bearing line. Only already-eligible candidate walls are
    grouped, with their original IDs, roles, sections and openings intact.
    """
    if not _low_rise_housing(model):
        return []
    lines = {}
    for wall in candidates:
        axis = _axis_of(wall)
        if axis is not None:
            orient, pos, lo, hi = axis
            # Exact centrelines, not merely nearby parallel wall guides.
            lines.setdefault((wall.storey, orient, pos), []).append((lo, hi, wall))
    groups = []
    for key in sorted(lines):
        chain, end = [], None
        for lo, hi, wall in sorted(lines[key], key=lambda row: (row[0], row[1], row[2].id)):
            if chain and lo > end + _ETA:
                if len(chain) > 1 and len({item.role for item in chain}) > 1:
                    groups.append(chain)
                chain = []
            chain.append(wall)
            end = hi if len(chain) == 1 else max(end, hi)
        if len(chain) > 1 and len({item.role for item in chain}) > 1:
            groups.append(chain)
    return groups


def _cover_storey(
    grid: _StoreyGrid,
    walls: Sequence[WallLine],
    elig: Dict[str, _Eligibility],
    system: str,
    params: MasonryParams,
    extra: Sequence[Tuple[str, float, float, float]] = (),
    banned: Sequence[str] = (),
    promoted: Sequence[str] = (),
) -> _CoverResult:
    """Seed the perimeter, then add interior walls until the cover closes.

    `extra` carries injected RC beam lines (spec 7.4) as support, `banned` the
    walls a demote decision took out of play, and `promoted` the walls whose
    thickness change request is being taken as granted for this dry run.
    """
    cap = float(params.max_panel_short_span_m)
    blocked = set(banned)
    lifted = set(promoted)
    trace = []  # type: List[str]

    def usable(wall: WallLine) -> bool:
        if wall.id in blocked:
            return False
        record = elig.get(wall.id)
        if record is None:
            return False
        if wall.id in lifted:
            return (
                not record.never_bearing
                and record.stacked
                and record.grounded
                and record.sr_ok
            )
        return record.eligible(system)

    seed = sorted(wall.id for wall in walls if _is_perimeter(wall, grid) and usable(wall))
    skipped = sorted(
        wall.id for wall in walls if _is_perimeter(wall, grid) and not usable(wall)
    )
    if seed:
        trace.append(
            "storey %d: seeded %d perimeter wall(s) as bearing (masonry perimeters always bear)"
            % (grid.storey, len(seed))
        )
    for wall_id in skipped:
        record = elig.get(wall_id)
        trace.append(
            "storey %d: perimeter wall %s cannot bear: %s"
            % (grid.storey, wall_id, "; ".join(record.reasons) if record else "not a masonry wall")
        )

    bearing = list(seed)
    if not grid.has_cells():
        return _CoverResult(grid.storey, bearing, [], [], trace, list(seed))

    panels = grid.panels(_support_lines(walls, bearing, extra))
    bad = _badness(panels, cap)
    candidates = [wall for wall in walls if wall.id not in set(bearing) and usable(wall)]
    guard = 0
    while bad != CLEAN and candidates and guard < 200:
        guard += 1
        best = None  # type: Optional[Tuple[Tuple[float, ...], WallLine, List[Panel], Tuple[int, float, float]]]
        for candidate in sorted(candidates, key=_tie_break):
            trial = bearing + [candidate.id]
            trial_panels = grid.panels(_support_lines(walls, trial, extra))
            trial_bad = _badness(trial_panels, cap)
            if trial_bad >= bad:
                continue
            axis = _axis_of(candidate)
            cover_len = 0.0
            if axis is not None:
                orient, pos, lo, hi = axis
                cover_len = grid.boundary_on_line(orient, pos, lo, hi)
            score = (
                float(bad[0] - trial_bad[0]),
                float(bad[1] - trial_bad[1]),
                float(bad[2] - trial_bad[2]),
                round(cover_len, 6),
                round(candidate.length_m(), 6),
            )
            if best is None or score > best[0]:
                best = (score, candidate, trial_panels, trial_bad)
        if best is None and _low_rise_housing(grid.model):
            grouped = None
            for group in _housing_role_split_groups(grid.model, candidates):
                trial = bearing + [wall.id for wall in group]
                trial_panels = grid.panels(_support_lines(walls, trial, extra))
                trial_bad = _badness(trial_panels, cap)
                if trial_bad >= bad:
                    continue
                score = (float(bad[0] - trial_bad[0]), float(bad[1] - trial_bad[1]),
                         float(bad[2] - trial_bad[2]), sum(wall.length_m() for wall in group))
                if grouped is None or score > grouped[0]:
                    grouped = (score, group, trial_panels, trial_bad)
            if grouped is not None:
                promoted_ids = sorted(wall.id for wall in grouped[1])
                bearing.extend(promoted_ids)
                panels, bad = grouped[2], grouped[3]
                candidates = [wall for wall in candidates if wall.id not in set(promoted_ids)]
                trace.append("storey %d: promoted contiguous eligible Housing wall pieces %s together"
                             % (grid.storey, ", ".join(promoted_ids)))
                continue
        if best is None:
            break
        bearing.append(best[1].id)
        panels = best[2]
        bad = best[3]
        candidates = [wall for wall in candidates if wall.id != best[1].id]
        trace.append(
            "storey %d: promoted %s to bearing (worst short span now %.2f m)"
            % (grid.storey, best[1].id, max([p.short_span_m for p in panels] or [0.0]))
        )

    gaps = []  # type: List[CoverGap]
    for panel in panels:
        for need in panel.needs(cap):
            if need == "short_span":
                gaps.append(
                    CoverGap(
                        panel_id=panel.id,
                        storey=grid.storey,
                        need="short_span",
                        value_m=panel.short_span_m,
                        limit_m=cap,
                        message=(
                            "panel %s spans %.2f m the short way, past the %.2f m cap, and no "
                            "eligible wall closes it" % (panel.id, panel.short_span_m, cap)
                        ),
                    )
                )
            else:
                gaps.append(
                    CoverGap(
                        panel_id=panel.id,
                        storey=grid.storey,
                        need="edge",
                        value_m=panel.unsupported_m,
                        limit_m=0.0,
                        message=(
                            "panel %s has %.2f m of unsupported edge; a %s panel needs %s"
                            % (
                                panel.id,
                                panel.unsupported_m,
                                "two-way" if panel.two_way else "one-way",
                                "all four edges supported" if panel.two_way else "both long edges supported",
                            )
                        ),
                    )
                )
    bearing.sort()
    return _CoverResult(grid.storey, bearing, panels, gaps, trace, list(seed))


def _perpendicular_returns(
    walls: Sequence[WallLine], bearing: Sequence[str], wall: WallLine
) -> List[float]:
    """Stations along `wall` where a bearing wall of the other direction meets it."""
    axis = _axis_of(wall)
    if axis is None:
        return []
    orient, pos, lo, hi = axis
    other = "v" if orient == "h" else "h"
    chosen = set(bearing)
    stations = set()
    for candidate in walls:
        if candidate.id == wall.id or candidate.id not in chosen:
            continue
        if candidate.storey != wall.storey:
            continue
        caxis = _axis_of(candidate)
        if caxis is None or caxis[0] != other:
            continue
        _c_orient, c_pos, c_lo, c_hi = caxis
        if c_pos < lo - GEOM_TOL_M or c_pos > hi + GEOM_TOL_M:
            continue
        if pos < c_lo - GEOM_TOL_M or pos > c_hi + GEOM_TOL_M:
            continue
        stations.add(round(c_pos, 6))
    return sorted(stations)


def _cross_wall_gaps(
    walls: Sequence[WallLine], bearing: Sequence[str], params: MasonryParams
) -> List[Tuple[WallLine, float, float]]:
    """(wall, midpoint station, gap length) wherever cross walls sit further than the cap."""
    out = []
    limit = float(params.cross_wall_max_m)
    chosen = set(bearing)
    for wall in sorted(walls, key=lambda w: w.id):
        if wall.id not in chosen:
            continue
        axis = _axis_of(wall)
        if axis is None:
            continue
        _orient, _pos, lo, hi = axis
        stations = _perpendicular_returns(walls, bearing, wall)
        marks = sorted(set([lo, hi] + [s for s in stations if lo - GEOM_TOL_M <= s <= hi + GEOM_TOL_M]))
        for index in range(len(marks) - 1):
            gap = marks[index + 1] - marks[index]
            if gap > limit + GEOM_TOL_M:
                out.append((wall, 0.5 * (marks[index] + marks[index + 1]), gap))
    return out


def _both_directions(
    walls: Sequence[WallLine], bearing: Sequence[str], storey: int
) -> Tuple[bool, str]:
    """Spec 5.6: two bearing lines in each direction and a return on every wall."""
    chosen = set(bearing)
    lines = {"h": set(), "v": set()}  # type: Dict[str, set]
    on_storey = [w for w in walls if w.storey == storey and w.id in chosen]
    for wall in on_storey:
        axis = _axis_of(wall)
        if axis is None:
            continue
        lines[axis[0]].add(_mm(axis[1]))
    if len(lines["h"]) < 2:
        return (False, "storey %d has %d bearing line(s) running in x; two is the minimum" % (storey, len(lines["h"])))
    if len(lines["v"]) < 2:
        return (False, "storey %d has %d bearing line(s) running in y; two is the minimum" % (storey, len(lines["v"])))
    for wall in sorted(on_storey, key=lambda w: w.id):
        if not _perpendicular_returns(walls, bearing, wall):
            return (False, "bearing wall %s has no perpendicular return" % wall.id)
    return (True, "")


# ---------------------------------------------------------------------------
# choose_system (spec 3)
# ---------------------------------------------------------------------------


def _category(model: StructuralModel, params: MasonryParams, trace: List[str]) -> str:
    """Seismic category: an explicit override, else IS 4326 Table 1 on the zone."""
    if params.category:
        cat = str(params.category).strip().upper()
        if cat not in is4326.CATEGORIES:
            raise ValueError("seismic category override must be one of " + ", ".join(is4326.CATEGORIES))
        trace.append("category %s taken from the request override" % cat)
        return cat
    seismic = model.meta.get("seismic")
    zone = params.zone
    source = "params.zone"
    if isinstance(seismic, dict) and seismic.get("zone"):
        zone = seismic["zone"]
        source = "model.meta.seismic.zone"
    importance = float(params.importance)
    cat = is4326.seismic_category(zone, importance)
    trace.append(
        "category %s from IS 4326 Table 1 on zone %s (from %s) at importance %.2f"
        % (cat, str(zone), source, importance)
    )
    return cat


def _wall_census(walls: Sequence[WallLine], params: MasonryParams) -> Dict[str, float]:
    """Centreline length in each thickness class, ground storey only."""
    census = {"thin": 0.0, "confined": 0.0, "bearing": 0.0}
    for wall in walls:
        if wall.storey != 0:
            continue
        t_mm = _t_mm(wall)
        length = wall.length_m()
        if t_mm >= float(params.min_bearing_t_mm) - _ETA:
            census["bearing"] += length
        elif t_mm >= float(params.confined_min_t_mm) - _ETA:
            census["confined"] += length
        else:
            census["thin"] += length
    return census


def choose_system(model: StructuralModel, params: Optional[MasonryParams] = None) -> SystemDecision:
    """Pick the structural system, top-down through the spec 3 decision table.

    Every row that is evaluated appends a line to the trace, so the response can
    show why the answer is what it is. A masonry request this module will not
    honour comes back as a `Refusal` carrying the clause id, with the rc_frame
    fallback produced in the same call and `labeled` set: an engine never
    returns an empty batch, and never refuses silently.
    """
    params = params or MasonryParams()
    trace = []  # type: List[str]
    category = _category(model, params, trace)

    storeys = _storeys_of(model)
    count = max(1, len(storeys))
    height = sum(_storey_height(model, s) for s in storeys)
    cap = params.max_storeys(category)
    requested = str(params.system or "auto")
    masonry_ok = count <= cap and height <= float(params.max_height_m) + _ETA
    trace.append(
        "%d storey(s), %.2f m tall; category %s admits %d storey(s) up to %.1f m"
        % (count, height, category, cap, float(params.max_height_m))
    )

    if requested != "auto" and requested not in REQUESTABLE_SYSTEMS:
        trace.append(
            "row 1: requested system '%s' is not in the frozen vocabulary %s; treated as auto"
            % (requested, ", ".join(REQUESTABLE_SYSTEMS))
        )
        requested = "auto"

    # row 1: a legal override wins outright
    if requested != "auto":
        if requested == System.RC_FRAME.value or masonry_ok:
            trace.append("row 1: request '%s' is legal and is honoured" % requested)
            return SystemDecision(system=requested, requested=requested, category=category, trace=trace)
        trace.append("row 1: request '%s' is not legal at this height, falling through" % requested)

    # row 2: masonry over the storey or height cap is refused with its clause
    if requested in (System.LOAD_BEARING_MASONRY.value, System.CONFINED_MASONRY.value) and not masonry_ok:
        reason = (
            "%s refused: %d storeys and %.2f m against the category %s limit of %d storeys and %.1f m"
            % (requested, count, height, category, cap, float(params.max_height_m))
        )
        trace.append("row 2: " + reason)
        return SystemDecision(
            system=System.RC_FRAME.value,
            requested=requested,
            category=category,
            refused=Refusal(clause="IS4326:1993 Cl 8.1 Table 3", reason=reason, code="E_MASONRY_LIMIT"),
            labeled=True,
            trace=trace,
        )

    walls = _masonry_walls(model)
    stacks = _stack_index(model)
    elig = _eligibility(model, params, walls, stacks)
    grids = {storey: _StoreyGrid(model, storey, [w for w in walls if w.storey == storey]) for storey in storeys}

    if not masonry_ok:
        trace.append(
            "rows 4 to 6 skipped: %d storeys is past the category %s cap of %d, so no masonry system is admissible"
            % (count, category, cap)
        )
        trace.append("row 7: rc_frame")
        return SystemDecision(system=System.RC_FRAME.value, requested=requested, category=category, trace=trace)

    # row 3: a storey with no grounded bearing-eligible line in one direction
    missing = []  # type: List[str]
    for storey in storeys:
        found = {"h": False, "v": False}
        for wall in walls:
            if wall.storey != storey:
                continue
            record = elig.get(wall.id)
            if record is None or not record.eligible(System.LOAD_BEARING_MASONRY.value):
                continue
            axis = _axis_of(wall)
            if axis is not None:
                found[axis[0]] = True
        for orient in ("h", "v"):
            if not found[orient]:
                missing.append("storey %d has no grounded bearing-eligible wall running in %s" % (storey, orient))
    if missing and not params.allow_promote:
        trace.append("row 3: " + "; ".join(missing) + "; promotion is disallowed, so the both-directions rule is unsatisfiable")
        return SystemDecision(system=System.RC_FRAME.value, requested=requested, category=category, trace=trace)
    if missing:
        trace.append("row 3: " + "; ".join(missing) + "; promotion is allowed, so the row does not fire")

    # row 4: does the 190 mm and thicker set close the cover in both directions
    feasible = True
    reasons = []  # type: List[str]
    for storey in storeys:
        grid = grids[storey]
        if not grid.has_cells():
            continue
        on_storey = [w for w in walls if w.storey == storey]
        result = _cover_storey(grid, on_storey, elig, System.LOAD_BEARING_MASONRY.value, params)
        if result.gaps:
            feasible = False
            reasons.append(result.gaps[0].message)
            break
        ok, why = _both_directions(on_storey, result.bearing, storey)
        if not ok:
            feasible = False
            reasons.append(why)
            break
    if feasible:
        trace.append("row 4: the bearing-eligible set closes the cover in both directions; load_bearing_masonry")
        return SystemDecision(
            system=System.LOAD_BEARING_MASONRY.value, requested=requested, category=category, trace=trace
        )
    trace.append("row 4: load bearing masonry does not close the cover: " + "; ".join(reasons))

    census = _wall_census(walls, params)
    total = sum(census.values())

    # row 5: a wall census the 150 to 189 mm class dominates
    if total > _ETA and census["confined"] > 0.5 * total and count <= 3:
        trace.append(
            "row 5: %.0f%% of the ground storey wall length is in the 150 to 189 mm class; confined_masonry"
            % (100.0 * census["confined"] / total)
        )
        return SystemDecision(
            system=System.CONFINED_MASONRY.value, requested=requested, category=category, trace=trace
        )

    # row 6: thick perimeter, thin interior, interior support needed
    perimeter_ok = True
    interior_thin = total > _ETA and census["confined"] <= _ETA
    for wall in walls:
        if wall.storey != 0:
            continue
        grid = grids.get(0)
        if grid is None:
            continue
        if _is_perimeter(wall, grid):
            if _t_mm(wall) < float(params.min_bearing_t_mm) - _ETA:
                perimeter_ok = False
        elif _t_mm(wall) > float(params.never_bearing_t_mm) + _ETA:
            interior_thin = False
    if perimeter_ok and interior_thin:
        if count <= 2 and category <= "D":
            trace.append(
                "row 6: the perimeter bears and every interior wall is at or below %d mm, so interior "
                "support has to be injected; confined_masonry with tie columns and beam lines"
                % int(round(params.never_bearing_t_mm))
            )
            return SystemDecision(
                system=System.CONFINED_MASONRY.value, requested=requested, category=category, trace=trace
            )
        trace.append(
            "row 6: thick perimeter with thin interiors, but %d storeys in category %s is past the "
            "2 storey and category D limit for the injected-support route" % (count, category)
        )
        return SystemDecision(system=System.RC_FRAME.value, requested=requested, category=category, trace=trace)

    # row 6b: the census rows leave a hole (a confined-class share in the
    # 0 to 50 percent band fires neither row 5 nor row 6), so before falling to
    # rc_frame the same cover dry run is asked under confined masonry. The
    # census caps travel with the answer: row 5 admits confined up to 3
    # storeys, so this row admits no more.
    if count <= 3:
        confined_ok = True
        confined_reasons = []  # type: List[str]
        for storey in storeys:
            grid = grids[storey]
            if not grid.has_cells():
                continue
            on_storey = [w for w in walls if w.storey == storey]
            result = _cover_storey(grid, on_storey, elig, System.CONFINED_MASONRY.value, params)
            if result.gaps:
                confined_ok = False
                confined_reasons.append(result.gaps[0].message)
                break
            ok, why = _both_directions(on_storey, result.bearing, storey)
            if not ok:
                confined_ok = False
                confined_reasons.append(why)
                break
        if confined_ok:
            share = 100.0 * census["confined"] / total if total > _ETA else 0.0
            trace.append(
                "row 6b: %.0f%% of the ground storey wall length is in the 150 to 189 mm class and the "
                "confined-masonry set closes the cover in both directions; confined_masonry" % share
            )
            return SystemDecision(
                system=System.CONFINED_MASONRY.value, requested=requested, category=category, trace=trace
            )
        trace.append("row 6b: confined masonry does not close the cover either: " + "; ".join(confined_reasons))
    else:
        trace.append(
            "row 6b: %d storey(s) is past the 3 storey cap the census rows put on confined masonry, "
            "so the confined dry run is not attempted" % count
        )

    trace.append("row 7: no masonry row fits; rc_frame")
    return SystemDecision(system=System.RC_FRAME.value, requested=requested, category=category, trace=trace)


# ---------------------------------------------------------------------------
# the placer (spec 4 to 9)
# ---------------------------------------------------------------------------


class MasonryPlacer:
    """Runs the whole masonry placement over one `StructuralModel`.

    Stateless between calls: `place()` builds its own working state, so one
    placer instance may be reused and two calls on one model return equal
    results. Nothing here reads a load; the takedown runs afterwards.
    """

    def __init__(self, params: Optional[MasonryParams] = None) -> None:
        self.params = params or MasonryParams()

    # -- entry point --------------------------------------------------------

    def place(self, model: StructuralModel, params: Optional[MasonryParams] = None) -> MasonryPlacement:
        """Decide the system, close the cover, check the openings, place the steel."""
        self._model = model
        self._params = params or self.params
        self._decision = choose_system(model, self._params)
        self._category = self._decision.category
        self._walls = _masonry_walls(model)
        self._storeys = _storeys_of(model)
        self._count = max(1, len(self._storeys))
        self._stacks = _stack_index(model)
        self._elig = _eligibility(model, self._params, self._walls, self._stacks)
        self._grids = {
            storey: _StoreyGrid(model, storey, [w for w in self._walls if w.storey == storey])
            for storey in self._storeys
        }
        self._trace = list(self._decision.trace)
        self._warnings = []  # type: List[Disclosure]
        self._reset_attempt()

        system = self._decision.system
        while True:
            if system == System.RC_FRAME.value:
                return self._finish_rc_frame(system)
            covers, gaps = self._fixpoint(system)
            blocker = self._blocker(system, covers, gaps)
            if blocker is None:
                return self._finish_masonry(system, covers)
            nxt = self._escalate(system)
            reason = "masonry infeasible: %s; escalated to %s" % (blocker[1], nxt)
            self._trace.append(reason)
            self._decision.refused = Refusal(clause=blocker[0], reason=reason, code=blocker[2])
            self._decision.labeled = True
            system = nxt
            # the abandoned attempt's ladder entries describe geometry that is no
            # longer in the output; the trace keeps the record of what was tried
            self._reset_attempt()
            self._warn(blocker[2], reason, blocker[3], clause=blocker[0])

    # -- working state ------------------------------------------------------

    def _reset_attempt(self) -> None:
        """Clear the working state, including the ladder, for one system attempt."""
        self._warnings = []  # type: List[Disclosure]
        self._banned = set()  # type: set
        self._lifted = set()  # type: set
        self._extra = {}  # type: Dict[int, List[Tuple[str, float, float, float]]]
        self._hybrid = []  # type: List[Beam]
        self._demoted = []  # type: List[Dict[str, Any]]
        self._promoted = []  # type: List[GeometryChangeRequest]
        self._resolved = []  # type: List[Dict[str, Any]]
        self._strengthened = set()  # type: set
        self._jamb_points = []  # type: List[Tuple[float, float, str, int, str]]
        self._ties = {}  # type: Dict[Tuple[int, int], TieColumn]
        self._pilasters = []  # type: List[Pilaster]
        self._assumed_openings = []  # type: List[str]

    def _warn(self, code: str, message: str, element_ids: Sequence[str] = (), clause: Optional[str] = None) -> None:
        self._warnings.append(
            make_disclosure(code, message, sorted(set(element_ids)), clause=clause, stage="placement.masonry")
        )

    def _escalate(self, system: str) -> str:
        if system in ESCALATION:
            index = ESCALATION.index(system)
            if index + 1 < len(ESCALATION):
                return ESCALATION[index + 1]
        return System.RC_FRAME.value

    # -- the demote / strengthen fixpoint (spec 7) --------------------------

    def _cover_all(self, system: str) -> Dict[int, _CoverResult]:
        out = {}  # type: Dict[int, _CoverResult]
        for storey in self._storeys:
            grid = self._grids[storey]
            on_storey = [w for w in self._walls if w.storey == storey]
            out[storey] = _cover_storey(
                grid,
                on_storey,
                self._elig,
                system,
                self._params,
                extra=self._extra.get(storey, ()),
                banned=sorted(self._banned),
                promoted=sorted(self._lifted),
            )
        return out

    def _fixpoint(self, system: str) -> Tuple[Dict[int, _CoverResult], List[CoverGap]]:
        """At most `resolve_passes` passes of demote, strengthen, promote, inject."""
        covers = self._cover_all(system)
        gaps = [gap for storey in self._storeys for gap in covers[storey].gaps]
        for pass_no in range(1, int(self._params.resolve_passes) + 1):
            violations = self._table4_violations(covers)
            if not gaps and not violations:
                break
            progress = False
            if violations:
                progress = self._resolve_table4(system, covers, violations) or progress
            if gaps:
                progress = self._resolve_gaps(system, covers, gaps) or progress
            if not progress:
                self._trace.append("resolve pass %d: nothing further to try, stopping the fixpoint" % pass_no)
                break
            covers = self._cover_all(system)
            gaps = [gap for storey in self._storeys for gap in covers[storey].gaps]
            self._trace.append(
                "resolve pass %d complete: %d cover gap(s) left" % (pass_no, len(gaps))
            )
        for storey in self._storeys:
            self._trace.extend(covers[storey].trace)
        return (covers, gaps)

    def _blocker(
        self, system: str, covers: Dict[int, _CoverResult], gaps: Sequence[CoverGap]
    ) -> Optional[Tuple[str, str, str, List[str]]]:
        """(clause, reason, disclosure code, element ids) when masonry cannot stand."""
        if gaps:
            gap = gaps[0]
            # the governing reason is that no wall of an admissible load bearing
            # thickness exists on the line the panel needs supported
            code = "E_UNSUPPORTED_PANEL_EDGE" if gap.need == "edge" else "E_SPAN_OVER_MAX"
            return (
                "IS1905:1987 Cl 4.1",
                gap.message,
                code,
                [gap.panel_id],
            )
        for storey in self._storeys:
            grid = self._grids[storey]
            if not grid.has_cells():
                continue
            on_storey = [w for w in self._walls if w.storey == storey]
            ok, why = _both_directions(on_storey, covers[storey].bearing, storey)
            if not ok:
                return ("IS4326:1993 Cl 8.4", why, "E_NO_BEARING_DIRECTION", covers[storey].bearing[:1])
        return None

    # -- IS 4326 Table 4 (spec 6) -------------------------------------------

    def _segments(self, wall: WallLine, bearing: Sequence[str]) -> List[Dict[str, Any]]:
        """Split a bearing wall at its cross walls; one Table 4 check per segment."""
        axis = _axis_of(wall)
        if axis is None:
            return []
        orient, pos, lo, hi = axis
        inner = [s for s in _perpendicular_returns(self._walls, bearing, wall) if lo + GEOM_TOL_M < s < hi - GEOM_TOL_M]
        marks = [lo] + sorted(inner) + [hi]
        chosen = set(bearing)
        segments = []
        for index in range(len(marks) - 1):
            s0, s1 = marks[index], marks[index + 1]
            if s1 - s0 <= GEOM_TOL_M:
                continue
            ends = []
            for station, at_end in ((s0, index == 0), (s1, index == len(marks) - 2)):
                ends.append(at_end and self._is_corner(wall, station, chosen))
            openings = []
            for opening in sorted(wall.openings, key=lambda o: (float(o.offset_m), str(o.id))):
                o_lo, o_hi = _opening_interval(wall, opening)
                centre = 0.5 * (o_lo + o_hi)
                # an opening belongs to the segment its centre falls in, so one that
                # overruns a segment end is still measured rather than dropped, and
                # one sitting exactly on a cross wall lands in one segment, not two
                if centre < s0 - GEOM_TOL_M or centre > s1 + GEOM_TOL_M:
                    continue
                if index < len(marks) - 2 and centre >= s1 - GEOM_TOL_M:
                    continue
                openings.append(
                    Opening(
                        id=opening.id,
                        kind=opening.kind,
                        offset_m=0.5 * (o_lo + o_hi) - s0,
                        width_m=float(opening.width_m),
                        sill_m=opening.sill_m,
                        head_m=opening.head_m,
                        provenance=opening.provenance,
                    )
                )
            segments.append(
                {
                    "id": wall.id + "-seg" + str(index),
                    "wall": WallLine(
                        id=wall.id + "-seg" + str(index),
                        storey=wall.storey,
                        a=_point_of(orient, pos, s0),
                        b=_point_of(orient, pos, s1),
                        thickness_m=wall.thickness_m,
                        role=wall.role,
                        material=wall.material,
                        openings=openings,
                    ),
                    "corner_ends": (bool(ends[0]), bool(ends[1])),
                }
            )
        return segments

    def _is_corner(self, wall: WallLine, station: float, bearing: set) -> bool:
        """True when this wall end is an L corner rather than a T or X junction."""
        axis = _axis_of(wall)
        if axis is None:
            return False
        orient, pos, _lo, _hi = axis
        other = "v" if orient == "h" else "h"
        for candidate in self._walls:
            if candidate.id == wall.id or candidate.storey != wall.storey or candidate.id not in bearing:
                continue
            caxis = _axis_of(candidate)
            if caxis is None:
                continue
            c_orient, c_pos, c_lo, c_hi = caxis
            if c_orient == orient:
                if abs(c_pos - pos) <= GEOM_TOL_M and c_lo - GEOM_TOL_M <= station <= c_hi + GEOM_TOL_M:
                    if c_hi > station + GEOM_TOL_M or c_lo < station - GEOM_TOL_M:
                        return False  # the wall line runs on past this station
                continue
            if c_orient != other or abs(c_pos - station) > GEOM_TOL_M:
                continue
            if c_lo < pos - GEOM_TOL_M and c_hi > pos + GEOM_TOL_M:
                return False  # the cross wall passes through: a T junction, not a corner
        return True

    def _table4_violations(self, covers: Dict[int, _CoverResult]) -> List[Dict[str, Any]]:
        """Every open Table 4 breach on a wall that is still bearing."""
        if self._category == "A":
            return []
        rules = is4326.opening_limits(self._count, self._category)
        out = []  # type: List[Dict[str, Any]]
        for storey in self._storeys:
            bearing = covers[storey].bearing
            for wall in sorted((w for w in self._walls if w.storey == storey), key=lambda w: w.id):
                if wall.id not in bearing or wall.id in self._strengthened:
                    continue
                for segment in self._segments(wall, bearing):
                    for violation in is4326.check_openings(segment["wall"], rules, segment["corner_ends"]):
                        out.append(
                            {
                                "wall_id": wall.id,
                                "storey": storey,
                                "segment_id": segment["id"],
                                "check": violation.check,
                                "clause_id": violation.clause_id,
                                "opening_ids": list(violation.opening_ids),
                                "value": round(float(violation.value), 6),
                                "limit": round(float(violation.limit), 6),
                                "units": violation.units,
                                "message": violation.message,
                            }
                        )
        return out

    def _resolve_table4(
        self,
        system: str,
        covers: Dict[int, _CoverResult],
        violations: Sequence[Dict[str, Any]],
        late: bool = False,
    ) -> bool:
        """Spec 7.1 then 7.2: demote a redundant wall, otherwise strengthen it.

        `late` skips the demote branch. It is used for the walls the cross wall
        spacing pass promoted after the fixpoint closed: demoting one of those
        would reopen the spacing gap it was promoted to close, so the strengthen
        remedy is the only one on the table for them.
        """
        progress = False
        by_wall = {}  # type: Dict[str, List[Dict[str, Any]]]
        for violation in violations:
            by_wall.setdefault(violation["wall_id"], []).append(violation)
        for wall_id in sorted(by_wall):
            wall = self._wall(wall_id)
            if wall is None:
                continue
            storey = int(wall.storey)
            grid = self._grids[storey]
            if not late and not _is_perimeter(wall, grid) and self._redundant(system, wall, covers[storey]):
                self._banned.add(wall_id)
                self._demoted.append(
                    {
                        "wall_id": wall_id,
                        "storey": storey,
                        "rule": "7.1 redundant",
                        "reason": "the cover holds without it, so the cheapest answer to its Table 4 breach is to stop it bearing",
                    }
                )
                self._resolved.append(
                    {
                        "wall_id": wall_id,
                        "action": "DEMOTED",
                        "rule": "7.1",
                        "clause_id": by_wall[wall_id][0]["clause_id"],
                        "checks": sorted({v["check"] for v in by_wall[wall_id]}),
                    }
                )
                progress = True
                continue
            if self._category in ("B", "C", "D", "E"):
                self._strengthened.add(wall_id)
                jambs = self._jamb_stations(wall, by_wall[wall_id])
                for x, y in jambs:
                    self._add_tie(
                        x,
                        y,
                        _t_mm(wall),
                        [storey],
                        "IS 4326 Table 4 strengthen: jamb column at an offending opening",
                        wall_id,
                    )
                    self._jamb_points.append((x, y, "jamb_strengthen", storey, wall_id))
                self._resolved.append(
                    {
                        "wall_id": wall_id,
                        "action": "STRENGTHENED",
                        "rule": "7.2",
                        "clause_id": by_wall[wall_id][0]["clause_id"],
                        "checks": sorted({v["check"] for v in by_wall[wall_id]}),
                        "tie_columns": len(jambs),
                        "detail": "RC tie columns at both jambs of every offending opening, "
                        "a lintel band continuous through the pier and jamb vertical bars; the wall stays bearing",
                    }
                )
                progress = True
        return progress

    def _jamb_stations(self, wall: WallLine, violations: Sequence[Dict[str, Any]]) -> List[Tuple[float, float]]:
        """Plan points of both jambs of every opening named in a violation."""
        axis = _axis_of(wall)
        if axis is None:
            return []
        orient, pos, _lo, _hi = axis
        wanted = set()
        for violation in violations:
            wanted.update(violation["opening_ids"])
        points = set()
        for opening in wall.openings:
            if opening.id not in wanted:
                continue
            o_lo, o_hi = _opening_interval(wall, opening)
            points.add(_point_of(orient, pos, o_lo))
            points.add(_point_of(orient, pos, o_hi))
        return sorted(points)

    def _redundant(self, system: str, wall: WallLine, cover: _CoverResult) -> bool:
        """True when the cover still closes with this wall taken out of the set."""
        grid = self._grids[int(wall.storey)]
        on_storey = [w for w in self._walls if w.storey == wall.storey]
        remaining = [wall_id for wall_id in cover.bearing if wall_id != wall.id]
        panels = grid.panels(_support_lines(on_storey, remaining, self._extra.get(int(wall.storey), ())))
        return _badness(panels, float(self._params.max_panel_short_span_m)) == CLEAN

    # -- cover gaps: promote, inject, demote (spec 7.3 to 7.5) --------------

    def _resolve_gaps(self, system: str, covers: Dict[int, _CoverResult], gaps: Sequence[CoverGap]) -> bool:
        """One pass of rules 7.3 to 7.5, applied until nothing more improves."""
        progress = False
        for storey in self._storeys:
            if not [gap for gap in gaps if gap.storey == storey]:
                continue
            for _round in range(12):
                step = self._resolve_one_gap(system, covers[storey])
                progress = progress or step
                if not step:
                    break
                # a lift lives in placer state, not in the cover snapshot, so
                # the next round must read a FRESH cover: against the stale one
                # a round-1 lift is invisible and the resolver keeps spending
                # fixes on a gap it has already closed
                covers[storey] = self._cover_all(system)[storey]
                if not covers[storey].gaps:
                    break
        return progress

    def _resolve_one_gap(self, system: str, cover: _CoverResult) -> bool:
        """Apply the single best remaining fix on one storey, or report no move."""
        storey = cover.storey
        candidate = self._best_ineligible(system, cover)
        if candidate is None:
            return False
        wall, record = candidate
        t_mm = record.t_mm

        # rule 7.3: a 150 to 189 mm wall the cover needs, under load bearing
        # masonry. Rule 7.5's stacked/grounded screen (and the slenderness
        # screen) applies FIRST: a lifted wall still has to satisfy those to be
        # usable, so lifting one that does not would be a no-op that removes it
        # from gap resolution for good. Such a wall falls through to the beam
        # line rules below, which is spec 7's ordering.
        if (
            not record.never_bearing
            and record.thickness_ok
            and record.confined_only
            and record.stacked
            and record.grounded
            and record.sr_ok
            and system == System.LOAD_BEARING_MASONRY.value
        ):
            if self._params.allow_promote:
                self._lifted.add(wall.id)
                self._promoted.append(
                    GeometryChangeRequest(
                        wall_id=wall.id,
                        storey=storey,
                        field="thickness_mm",
                        current_mm=t_mm,
                        requested_mm=float(self._params.preferred_t_mm),
                        reason="rule 7.3: the cover needs this wall to bear and load bearing masonry "
                        "starts at %d mm; the centreline is unchanged and the plan is not edited"
                        % int(round(self._params.min_bearing_t_mm)),
                    )
                )
                self._resolved.append(
                    {"wall_id": wall.id, "action": "PROMOTED-REQUEST", "rule": "7.3", "clause_id": "IS1905:1987 Cl 4.1"}
                )
                self._warn(
                    "W_RELEASED_CAP",
                    "wall %s is kept bearing at %d mm on the condition that it is built at %d mm; "
                    "the thickness change is a request, the plan geometry is untouched"
                    % (wall.id, int(round(t_mm)), int(round(self._params.preferred_t_mm))),
                    [wall.id],
                    clause="IS1905:1987 Cl 4.1",
                )
                self._trace.append("rule 7.3: thickness promotion requested on %s" % wall.id)
                return True
            self._banned.add(wall.id)
            self._demoted.append(
                {
                    "wall_id": wall.id,
                    "storey": storey,
                    "rule": "7.3 thin wall, promotion disallowed",
                    "reason": "t %d mm is below the load bearing minimum and allow_promote is off" % int(round(t_mm)),
                }
            )
            self._trace.append("rule 7.3: %s demoted, promotion is disallowed" % wall.id)
            return True

        # rule 7.5: thick enough for this system, but it does not stack to the ground
        if record.thickness_ok and not (record.stacked and record.grounded):
            return self._inject_beam_line(wall, storey, "7.5")

        # rule 7.4: at or below the never-bearing floor, so an RC beam line takes over
        return self._inject_beam_line(wall, storey, "7.4")

    def _best_ineligible(self, system: str, cover: _CoverResult) -> Optional[Tuple[WallLine, _Eligibility]]:
        """The ineligible wall whose support line would close the most cover."""
        storey = cover.storey
        grid = self._grids[storey]
        on_storey = [w for w in self._walls if w.storey == storey]
        extra = list(self._extra.get(storey, ()))
        cap = float(self._params.max_panel_short_span_m)
        base = _badness(grid.panels(_support_lines(on_storey, cover.bearing, extra)), cap)
        best = None
        best_score = None
        for wall in sorted(on_storey, key=_tie_break):
            record = self._elig.get(wall.id)
            if record is None or wall.id in cover.bearing or wall.id in self._banned or wall.id in self._lifted:
                continue
            if record.eligible(system):
                continue
            axis = _axis_of(wall)
            if axis is None:
                continue
            orient, pos, lo, hi = axis
            trial = grid.panels(_support_lines(on_storey, cover.bearing, extra + [(orient, pos, lo, hi)]))
            score = _badness(trial, cap)
            if score >= base:
                continue
            key = (
                base[0] - score[0],
                base[1] - score[1],
                base[2] - score[2],
                round(wall.length_m(), 6),
            )
            if best_score is None or key > best_score:
                best_score = key
                best = (wall, record)
        return best

    def _inject_beam_line(self, wall: WallLine, storey: int, rule: str) -> bool:
        """Spec 7.4: an RC beam line on a wall axis that masonry cannot support."""
        axis = _axis_of(wall)
        if axis is None:
            return False
        orient, pos, lo, hi = axis
        lines = self._extra.setdefault(storey, [])
        if any(
            key[0] == orient and _mm(key[1]) == _mm(pos) and _mm(key[2]) == _mm(lo) and _mm(key[3]) == _mm(hi)
            for key in lines
        ):
            return False
        lines.append((orient, pos, lo, hi))
        a = _point_of(orient, pos, lo)
        b = _point_of(orient, pos, hi)
        reason = (
            "rule %s: %s is %d mm thick and can never bear, so an RC beam line takes over its support "
            "function; hybrid construction, labeled" % (rule, wall.id, int(round(_t_mm(wall))))
        )
        if rule == "7.5":
            reason = (
                "rule 7.5: %s does not stack to the ground, so an RC beam line takes over its support "
                "function on the same axis; masonry never transfers" % wall.id
            )
        beam = Beam(
            id=beam_id(storey, "x" if orient == "h" else "y", pos_token(pos), len(lines) - 1),
            storey=storey,
            a=a,
            b=b,
            width_m=max(float(wall.thickness_m), float(self._params.preferred_t_mm) / 1000.0),
            kind=BeamKind.PRIMARY,
            supports_wall_id=wall.id,
            placed_by=PLACED_BY,
            code_refs=["IS456:2000 Cl 22", "IS4326:1993 Cl 8.4"],
        )
        self._hybrid.append(beam)
        span = hi - lo
        cap = self._params.confined_panel_cap(_storey_height(self._model, storey))
        stations = [lo, hi]
        parts = int(math.ceil(span / cap - 1e-9)) if cap > 0 else 1
        for index in range(1, max(1, parts)):
            stations.append(lo + span * index / float(max(1, parts)))
        for station in sorted(set(round(value, 6) for value in stations)):
            x, y = _point_of(orient, pos, station)
            self._add_tie(x, y, max(_t_mm(wall), TIE_COLUMN_WIDTH_MM), [storey], reason, wall.id)
        self._resolved.append({"wall_id": wall.id, "action": "HYBRID-BEAM-LINE", "rule": rule, "clause_id": "IS456:2000 Cl 22"})
        self._trace.append(reason)
        self._warn("W_TERTIARY", reason, [wall.id], clause="IS4326:1993 Cl 8.4")
        return True

    def _wall(self, wall_id: str) -> Optional[WallLine]:
        for wall in self._walls:
            if wall.id == wall_id:
                return wall
        return None

    # -- tie columns (spec 8) ----------------------------------------------

    def _add_tie(
        self, x: float, y: float, t_mm: float, storeys: Sequence[int], reason: str, wall_id: Optional[str]
    ) -> None:
        key = (_mm(x), _mm(y))
        existing = self._ties.get(key)
        if existing is None:
            self._ties[key] = TieColumn(
                id="tie-@" + pos_token(x) + "x" + pos_token(y),
                x_m=float(x),
                y_m=float(y),
                w_mm=TIE_COLUMN_WIDTH_MM,
                d_mm=max(float(t_mm), 1.0),
                storeys=sorted(set(int(s) for s in storeys)),
                reason=reason,
                wall_id=wall_id,
            )
            return
        existing.storeys = sorted(set(existing.storeys) | set(int(s) for s in storeys))
        existing.d_mm = max(existing.d_mm, float(t_mm))

    # -- cross wall spacing and pilasters (spec 5.5) ------------------------

    def _close_cross_wall_gaps(self, system: str, bearing_by_storey: Dict[int, List[str]]) -> None:
        """Promote a perpendicular wall where one is eligible, else inject a pilaster."""
        for storey in self._storeys:
            on_storey = [w for w in self._walls if w.storey == storey]
            handled = set()  # type: set
            guard = 0
            while guard < 50:
                guard += 1
                gaps = [
                    item
                    for item in _cross_wall_gaps(on_storey, bearing_by_storey[storey], self._params)
                    if (item[0].id, _mm(item[1])) not in handled
                ]
                if not gaps:
                    break
                wall, station, gap = gaps[0]
                axis = _axis_of(wall)
                if axis is None:
                    break
                orient, pos, lo, hi = axis
                other = "v" if orient == "h" else "h"
                promoted = None
                for candidate in sorted(on_storey, key=_tie_break):
                    if candidate.id in bearing_by_storey[storey] or candidate.id in self._banned:
                        continue
                    record = self._elig.get(candidate.id)
                    if record is None or not (record.eligible(system) or candidate.id in self._lifted):
                        continue
                    caxis = _axis_of(candidate)
                    if caxis is None or caxis[0] != other:
                        continue
                    if not (lo - GEOM_TOL_M <= caxis[1] <= hi + GEOM_TOL_M):
                        continue
                    if not (caxis[2] - GEOM_TOL_M <= pos <= caxis[3] + GEOM_TOL_M):
                        continue
                    promoted = candidate
                    break
                if promoted is not None:
                    bearing_by_storey[storey] = sorted(set(bearing_by_storey[storey]) | {promoted.id})
                    self._trace.append(
                        "cross wall spacing: %s promoted to bearing to break a %.2f m gap on %s"
                        % (promoted.id, gap, wall.id)
                    )
                    continue
                x, y = _point_of(orient, pos, station)
                reason = (
                    "cross wall spacing on %s reaches %.2f m against the %.1f m cap and no perpendicular "
                    "wall is eligible, so a pilaster stiffens the line at midspan"
                    % (wall.id, gap, float(self._params.cross_wall_max_m))
                )
                self._pilasters.append(
                    Pilaster(
                        id="pil-@" + pos_token(x) + "x" + pos_token(y),
                        wall_id=wall.id,
                        storey=storey,
                        x_m=x,
                        y_m=y,
                        t_mm=_t_mm(wall),
                        projection_mm=3.0 * _t_mm(wall),
                        reason=reason,
                    )
                )
                self._trace.append(reason)
                self._warn("W_RELEASED_CAP", reason, [wall.id], clause="IS1905:1987 Cl 4.2.2")
                # the pilaster stands in for the missing cross wall on this stretch
                handled.add((wall.id, _mm(station)))

    # -- bands (spec 9) -----------------------------------------------------

    def _band_walls(self, storey: int, bearing: Sequence[str]) -> List[str]:
        """Bearing walls plus the masonry partitions the band runs through."""
        chosen = set(bearing)
        out = set(chosen)
        for wall in self._walls:
            if wall.storey != storey or wall.id in chosen:
                continue
            if _t_mm(wall) < 75.0:
                continue
            if _perpendicular_returns(self._walls, sorted(chosen), wall):
                out.add(wall.id)
        return sorted(out)

    def _band_span(self, storey: int, bearing: Sequence[str]) -> Tuple[float, bool]:
        """Longest clear band span between cross walls, and whether it was clamped."""
        on_storey = [w for w in self._walls if w.storey == storey and w.id in set(bearing)]
        longest = 0.0
        for wall in on_storey:
            axis = _axis_of(wall)
            if axis is None:
                continue
            _orient, _pos, lo, hi = axis
            stations = [s for s in _perpendicular_returns(self._walls, bearing, wall) if lo <= s <= hi]
            marks = sorted(set([lo, hi] + stations))
            for index in range(len(marks) - 1):
                longest = max(longest, marks[index + 1] - marks[index])
        limit = 8.0
        if longest > limit + _ETA:
            return (limit, True)
        return (max(longest, 1.0), False)

    def _loop_closure(self, wall_ids: Sequence[str]) -> Tuple[bool, List[str]]:
        """Is the band a closed loop, and where are its open ends?"""
        walls = [self._wall(wall_id) for wall_id in wall_ids]
        walls = [wall for wall in walls if wall is not None]
        open_ends = []
        for wall in walls:
            axis = _axis_of(wall)
            if axis is None:
                continue
            orient, pos, lo, hi = axis
            for station in (lo, hi):
                point = _point_of(orient, pos, station)
                touched = False
                for other in walls:
                    if other.id == wall.id:
                        continue
                    oaxis = _axis_of(other)
                    if oaxis is None:
                        continue
                    o_orient, o_pos, o_lo, o_hi = oaxis
                    ox, oy = point
                    on_line = abs((o_pos - oy) if o_orient == "h" else (o_pos - ox)) <= GEOM_TOL_M
                    station_on = (ox if o_orient == "h" else oy)
                    if on_line and o_lo - GEOM_TOL_M <= station_on <= o_hi + GEOM_TOL_M:
                        touched = True
                        break
                if not touched:
                    open_ends.append(pos_token(point[0]) + "," + pos_token(point[1]))
        open_ends = sorted(set(open_ends))
        return (not open_ends, open_ends)

    def _lintel_level(self, storey: int, bearing: Sequence[str]) -> float:
        """Modal opening head on the storey, or the configured lintel level."""
        heads = {}  # type: Dict[int, int]
        chosen = set(bearing)
        for wall in self._walls:
            if wall.storey != storey or wall.id not in chosen:
                continue
            for opening in wall.openings:
                if opening.head_m is None:
                    continue
                key = _mm(float(opening.head_m))
                heads[key] = heads.get(key, 0) + 1
        if not heads:
            return float(self._params.lintel_level_m)
        best = sorted(heads.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return best / 1000.0

    def _gable_walls(self, storey: int, bearing: Sequence[str], roof: str) -> Tuple[List[str], float]:
        """The raking gable or high-end walls, and the ridge rise above the eaves."""
        grid = self._grids[storey]
        x0, y0, w, h = grid.bbox()
        if w <= _ETA or h <= _ETA:
            return ([], 0.0)
        short = min(w, h)
        meta = self._model.meta.get("roof")
        ratio = 0.3 if roof != "shed" else 0.25
        if isinstance(meta, dict) and meta.get("rise_ratio"):
            ratio = float(meta["rise_ratio"])
        rise = ratio * short
        long_is_x = w >= h
        chosen = set(bearing)
        picks = []
        for wall in sorted((w2 for w2 in self._walls if w2.storey == storey and w2.id in chosen), key=lambda w2: w2.id):
            axis = _axis_of(wall)
            if axis is None:
                continue
            orient, pos, _lo, _hi = axis
            if roof == "shed":
                # the slope runs across the short span; the high end is taken at the
                # minimum coordinate of that axis, a stated convention, not a guess
                if long_is_x and orient == "v" and _mm(pos) == _mm(x0):
                    picks.append(wall.id)
                if (not long_is_x) and orient == "h" and _mm(pos) == _mm(y0):
                    picks.append(wall.id)
            else:
                if long_is_x and orient == "v" and _mm(pos) in (_mm(x0), _mm(x0 + w)):
                    picks.append(wall.id)
                if (not long_is_x) and orient == "h" and _mm(pos) in (_mm(y0), _mm(y0 + h)):
                    picks.append(wall.id)
        return (sorted(set(picks)), rise)

    def _bands(self, system: str, bearing_by_storey: Dict[int, List[str]]) -> Tuple[List[Band], List[BandRow]]:
        bands = []  # type: List[Band]
        rows = []  # type: List[BandRow]
        roof = _roof_type(self._model, self._params)
        top = max(self._storeys) if self._storeys else 0
        soft = _soft_soil(self._params)

        for storey in self._storeys:
            bearing = bearing_by_storey.get(storey, [])
            if not bearing:
                continue
            wall_ids = self._band_walls(storey, bearing)
            span, clamped = self._band_span(storey, bearing)
            closed, open_ends = self._loop_closure(wall_ids)
            level = _storey_base(self._model, storey) + self._lintel_level(storey, bearing)
            spec = is4326.lintel_band(span, self._category)
            note = "continuous closed loop at lintel level over every bearing wall"
            if spec is None:
                note = "category A takes no reinforced concrete band (IS 4326 Table 6)"
            if clamped:
                note += "; band span clamped to the last IS 4326 Table 6 row at 8 m"
            if not closed:
                note += "; the loop is open at " + ", ".join(open_ends)
            rows.append(
                BandRow(
                    band_id=band_id(BandKind.LINTEL, storey),
                    kind=BandKind.LINTEL.value,
                    storey=storey,
                    level_m=level,
                    wall_ids=wall_ids,
                    span_m=span,
                    spec=None if spec is None else dict(spec._asdict()),
                    closed_loop=closed,
                    open_ends=open_ends,
                    note=note,
                )
            )
            if spec is not None:
                bands.append(
                    Band(
                        id=band_id(BandKind.LINTEL, storey),
                        kind=BandKind.LINTEL,
                        storey=storey,
                        wall_ids=wall_ids,
                        level_m=level,
                        placed_by=PLACED_BY,
                    )
                )

        bearing_top = bearing_by_storey.get(top, [])
        if bearing_top:
            wall_ids = self._band_walls(top, bearing_top)
            span, clamped = self._band_span(top, bearing_top)
            closed, open_ends = self._loop_closure(wall_ids)
            level = _storey_base(self._model, top) + min(
                float(self._params.eaves_height_m), _storey_height(self._model, top)
            )
            spec = is4326.roof_band(span, self._category, roof, bool(self._params.cast_in_situ_slab))
            if spec is None:
                note = (
                    "roof band omitted: the %s roof is a cast-in-situ RC slab monolithic with the walls "
                    "and is itself the band (IS 4326 Cl 8.4.6 exception)" % roof
                ) if roof == "flat" and self._params.cast_in_situ_slab else (
                    "category A takes no reinforced concrete band (IS 4326 Table 6)"
                )
                self._trace.append("roof band: " + note)
            else:
                note = spec.note
            rows.append(
                BandRow(
                    band_id=band_id(BandKind.ROOF, top),
                    kind=BandKind.ROOF.value,
                    storey=top,
                    level_m=level,
                    wall_ids=wall_ids if spec is not None else [],
                    span_m=span,
                    spec=None if spec is None else dict(spec._asdict()),
                    closed_loop=closed,
                    open_ends=open_ends,
                    note=note,
                )
            )
            if spec is not None:
                bands.append(
                    Band(
                        id=band_id(BandKind.ROOF, top),
                        kind=BandKind.ROOF,
                        storey=top,
                        wall_ids=wall_ids,
                        level_m=level,
                        placed_by=PLACED_BY,
                    )
                )

            gable_ids, rise = self._gable_walls(top, bearing_top, roof)
            gspec = is4326.gable_band(self._category, roof, span)
            if gspec is not None and gable_ids:
                rows.append(
                    BandRow(
                        band_id=band_id(BandKind.GABLE, top),
                        kind=BandKind.GABLE.value,
                        storey=top,
                        level_m=level + rise,
                        wall_ids=gable_ids,
                        span_m=span,
                        spec=dict(gspec._asdict()),
                        closed_loop=False,
                        open_ends=[],
                        note=gspec.note,
                    )
                )
                bands.append(
                    Band(
                        id=band_id(BandKind.GABLE, top),
                        kind=BandKind.GABLE,
                        storey=top,
                        wall_ids=gable_ids,
                        level_m=level + rise,
                        placed_by=PLACED_BY,
                    )
                )
            else:
                self._trace.append(
                    "gable band: none, a %s roof has no raking end wall to band (IS 4326 Cl 8.4.5)" % roof
                )

        bearing_ground = bearing_by_storey.get(0, [])
        if bearing_ground:
            wall_ids = self._band_walls(0, bearing_ground)
            span, _clamped = self._band_span(0, bearing_ground)
            closed, open_ends = self._loop_closure(wall_ids)
            level = _storey_base(self._model, 0) - float(self._params.plinth_depth_m)
            spec = is4326.plinth_band(self._category, soft, span)
            note = (
                "plinth band recommended, not required: the soil is neither soft nor filled and the "
                "category is not D or E (IS 4326 Cl 8.4.7)"
                if spec is None
                else spec.note
            )
            rows.append(
                BandRow(
                    band_id=band_id(BandKind.PLINTH, 0),
                    kind=BandKind.PLINTH.value,
                    storey=0,
                    level_m=level,
                    wall_ids=wall_ids if spec is not None else [],
                    span_m=span,
                    spec=None if spec is None else dict(spec._asdict()),
                    closed_loop=closed,
                    open_ends=open_ends,
                    note=note,
                )
            )
            if spec is not None:
                bands.append(
                    Band(
                        id=band_id(BandKind.PLINTH, 0),
                        kind=BandKind.PLINTH,
                        storey=0,
                        wall_ids=wall_ids,
                        level_m=level,
                        placed_by=PLACED_BY,
                    )
                )
        rows.sort(key=lambda row: (row.storey, row.kind))
        bands.sort(key=lambda band: band.id)
        return (bands, rows)

    # -- lintels (spec 9) ---------------------------------------------------

    def _lintels(
        self, wall_ids_by_storey: Dict[int, List[str]], band_level: Optional[Dict[int, float]]
    ) -> Tuple[List[Lintel], List[LintelRun], List[str]]:
        """Discrete lintels over every opening the band does not absorb."""
        elements = []  # type: List[Lintel]
        rows = []  # type: List[LintelRun]
        absorbed = []  # type: List[str]
        tol = float(self._params.lintel_unify_tol_mm) / 1000.0
        bearing_mm = float(self._params.lintel_bearing_mm)
        for storey in sorted(wall_ids_by_storey):
            wanted = set(wall_ids_by_storey[storey])
            level = None if band_level is None else band_level.get(storey)
            for wall in sorted((w for w in self._walls if w.storey == storey and w.id in wanted), key=lambda w: w.id):
                axis = _axis_of(wall)
                if axis is None or not wall.openings:
                    continue
                indexed = sorted(
                    enumerate(wall.openings), key=lambda pair: (_opening_interval(wall, pair[1])[0], str(pair[1].id))
                )
                raw = []
                for index, opening in indexed:
                    head = float(opening.head_m) if opening.head_m is not None else float(self._params.lintel_level_m)
                    if level is not None and abs(head - level) <= tol + _ETA:
                        absorbed.append(str(opening.id))
                        continue
                    o_lo, o_hi = _opening_interval(wall, opening)
                    raw.append({"index": index, "ids": [str(opening.id)], "lo": o_lo, "hi": o_hi, "head": head,
                                "width": float(opening.width_m)})
                runs = []
                for item in raw:
                    if runs:
                        last = runs[-1]
                        overlap = (item["lo"] - bearing_mm / 1000.0) <= (last["hi"] + bearing_mm / 1000.0) + _ETA
                        if overlap and abs(item["head"] - last["head"]) <= tol + _ETA:
                            last["ids"].extend(item["ids"])
                            last["hi"] = max(last["hi"], item["hi"])
                            last["head"] = max(last["head"], item["head"])
                            last["width"] = max(last["width"], item["width"])
                            last["merged"] = True
                            continue
                    item = dict(item)
                    item["merged"] = False
                    runs.append(item)
                for run in runs:
                    clear = run["hi"] - run["lo"]
                    small = run["width"] < float(self._params.lintel_small_opening_m) - _ETA and not run["merged"]
                    seat = float(self._params.lintel_min_bearing_mm) if small else bearing_mm
                    depth = max(
                        float(self._params.lintel_min_depth_mm),
                        _round_up(clear * 1000.0 / 12.0, float(self._params.lintel_depth_step_mm)),
                    )
                    note = "bearing %d mm each side, depth clear span / 12 rounded up to %d mm and never below %d mm" % (
                        int(round(seat)),
                        int(round(self._params.lintel_depth_step_mm)),
                        int(round(self._params.lintel_min_depth_mm)),
                    )
                    if small:
                        note += "; %d mm seating admitted for an opening under %.1f m" % (
                            int(round(seat)),
                            float(self._params.lintel_small_opening_m),
                        )
                    if run["merged"]:
                        note += "; merged with a neighbour whose level is within %d mm" % int(
                            round(self._params.lintel_unify_tol_mm)
                        )
                    element_id = lintel_id(wall.id, int(run["index"]))
                    elements.append(
                        Lintel(
                            id=element_id,
                            wall_id=wall.id,
                            opening_id=run["ids"][0],
                            span_m=clear + 2.0 * seat / 1000.0,
                            placed_by=PLACED_BY,
                        )
                    )
                    rows.append(
                        LintelRun(
                            id=element_id,
                            wall_id=wall.id,
                            storey=storey,
                            opening_ids=sorted(run["ids"]),
                            clear_span_m=clear,
                            bearing_mm=seat,
                            depth_mm=depth,
                            level_m=_storey_base(self._model, storey) + run["head"],
                            merged=bool(run["merged"]),
                            note=note,
                        )
                    )
        elements.sort(key=lambda lin: lin.id)
        rows.sort(key=lambda row: row.id)
        return (elements, rows, sorted(set(absorbed)))

    # -- vertical steel (spec 9) -------------------------------------------

    def _junction_points(self, storey: int, bearing: Sequence[str]) -> Dict[Tuple[int, int], str]:
        """Corner and T/X junction points of the bearing network on one storey."""
        chosen = set(bearing)
        on_storey = [w for w in self._walls if w.storey == storey and w.id in chosen]
        out = {}  # type: Dict[Tuple[int, int], str]
        for wall in on_storey:
            axis = _axis_of(wall)
            if axis is None or axis[0] != "h":
                continue
            _o, y, x_lo, x_hi = axis
            for other in on_storey:
                oaxis = _axis_of(other)
                if oaxis is None or oaxis[0] != "v":
                    continue
                _o2, x, y_lo, y_hi = oaxis
                if not (x_lo - GEOM_TOL_M <= x <= x_hi + GEOM_TOL_M):
                    continue
                if not (y_lo - GEOM_TOL_M <= y <= y_hi + GEOM_TOL_M):
                    continue
                ends_h = abs(x - x_lo) <= GEOM_TOL_M or abs(x - x_hi) <= GEOM_TOL_M
                ends_v = abs(y - y_lo) <= GEOM_TOL_M or abs(y - y_hi) <= GEOM_TOL_M
                kind = "corner" if (ends_h and ends_v) else "junction"
                key = (_mm(x), _mm(y))
                if out.get(key) != "junction":
                    out[key] = kind
        return out

    def _free_ends(self, storey: int, bearing: Sequence[str]) -> List[Tuple[float, float, str]]:
        """Wall ends with no other bearing wall meeting them."""
        chosen = set(bearing)
        on_storey = [w for w in self._walls if w.storey == storey and w.id in chosen]
        junctions = self._junction_points(storey, bearing)
        out = []
        for wall in on_storey:
            axis = _axis_of(wall)
            if axis is None:
                continue
            orient, pos, lo, hi = axis
            for station in (lo, hi):
                x, y = _point_of(orient, pos, station)
                if (_mm(x), _mm(y)) in junctions:
                    continue
                out.append((x, y, wall.id))
        return sorted(out)

    def _vertical_bars(self, bearing_by_storey: Dict[int, List[str]]) -> List[VerticalBar]:
        """IS 4326 Table 7 bars at corners, junctions and (D and E) opening jambs.

        Table 7 is transcribed to 3 storeys. Categories A to D admit a 4 storey
        masonry building, so a 4 storey stack has no row: this issues no bar and
        says so on the ladder rather than reading a row that is not there or
        pretending none is needed.
        """
        try:
            first = is4326.vertical_bars(self._count, 0, self._category)
        except is1905.CodeInputError as exc:
            message = (
                "vertical steel not scheduled: %s. The bars are still required; an engineer has to "
                "size them from the printed IS 4326 Table 7 row" % str(exc)
            )
            self._trace.append(message)
            self._warn("W_TALL", message, [], clause="IS4326:1993 Table 7")
            return []
        if first is None:
            self._trace.append(
                "vertical steel: category %s takes none from IS 4326 Table 7" % self._category
            )
            return []
        locations = set(first.locations)
        points = {}  # type: Dict[Tuple[int, int], str]
        for storey in self._storeys:
            bearing = bearing_by_storey.get(storey, [])
            for key, kind in self._junction_points(storey, bearing).items():
                if kind in locations and points.get(key) != "junction":
                    points[key] = kind
            if "jamb" in locations:
                chosen = set(bearing)
                for wall in sorted((w for w in self._walls if w.storey == storey and w.id in chosen), key=lambda w: w.id):
                    axis = _axis_of(wall)
                    if axis is None:
                        continue
                    orient, pos, _lo, _hi = axis
                    for opening in wall.openings:
                        o_lo, o_hi = _opening_interval(wall, opening)
                        for station in (o_lo, o_hi):
                            x, y = _point_of(orient, pos, station)
                            points.setdefault((_mm(x), _mm(y)), "jamb")
        for x, y, kind, _storey, _wall_id in self._jamb_points:
            points.setdefault((_mm(x), _mm(y)), kind)

        bars = []  # type: List[VerticalBar]
        for key in sorted(points):
            x = key[0] / 1000.0
            y = key[1] / 1000.0
            position = points[key]
            runs = []  # type: List[List[Any]]
            for storey in self._storeys:
                spec = is4326.vertical_bars(self._count, storey, self._category)
                dia = None if spec is None else int(spec.dia_mm)
                if dia is None:
                    continue
                if runs and runs[-1][1] == dia and runs[-1][0][-1] == storey - 1:
                    runs[-1][0].append(storey)
                else:
                    runs.append([[storey], dia])
            for storeys, dia in runs:
                bars.append(
                    VerticalBar(
                        id="vbar-@" + pos_token(x) + "x" + pos_token(y) + "-s" + str(storeys[0]),
                        x_m=x,
                        y_m=y,
                        dia_mm=int(dia),
                        from_storey=int(storeys[0]),
                        to_storey=int(storeys[-1]),
                        position=position,
                        clause="IS4326:1993 Table 7",
                    )
                )
        bars.sort(key=lambda bar: bar.id)
        return bars

    # -- confining columns (spec 8) ----------------------------------------

    def _confine(self, system: str, bearing_by_storey: Dict[int, List[str]]) -> None:
        """Tie columns at corners, junctions, free ends and along long panels."""
        if system == System.CONFINED_MASONRY.value:
            for storey in self._storeys:
                bearing = bearing_by_storey.get(storey, [])
                height = _storey_height(self._model, storey)
                cap = self._params.confined_panel_cap(height)
                for key, kind in sorted(self._junction_points(storey, bearing).items()):
                    self._add_tie(
                        key[0] / 1000.0,
                        key[1] / 1000.0,
                        self._thickness_at(storey, bearing, key),
                        [storey],
                        "confined masonry baseline: tie column at a wall " + kind,
                        None,
                    )
                for x, y, wall_id in self._free_ends(storey, bearing):
                    self._add_tie(
                        x, y, self._thickness_at(storey, bearing, (_mm(x), _mm(y))), [storey],
                        "confined masonry baseline: tie column at a free wall end", wall_id,
                    )
                chosen = set(bearing)
                for wall in sorted((w for w in self._walls if w.storey == storey and w.id in chosen), key=lambda w: w.id):
                    axis = _axis_of(wall)
                    if axis is None:
                        continue
                    orient, pos, lo, hi = axis
                    marks = sorted(
                        set([lo, hi] + [s for s in _perpendicular_returns(self._walls, bearing, wall) if lo <= s <= hi])
                    )
                    for index in range(len(marks) - 1):
                        span = marks[index + 1] - marks[index]
                        if span <= cap + GEOM_TOL_M:
                            continue
                        parts = int(math.ceil(span / cap - 1e-9))
                        for step in range(1, parts):
                            station = marks[index] + span * step / float(parts)
                            x, y = _point_of(orient, pos, station)
                            self._add_tie(
                                x, y, _t_mm(wall), [storey],
                                "confined masonry: unconfined panel length capped at %.2f m = min(%.1f h, %.1f m)"
                                % (cap, float(self._params.confined_panel_len_factor), float(self._params.confined_panel_len_cap_m)),
                                wall.id,
                            )
        for core in sorted(self._model.cores, key=lambda c: c.id):
            storeys = sorted(int(s) for s in core.storeys) or list(self._storeys)
            for x in (float(core.x_m), float(core.x_m) + float(core.w_m)):
                for y in (float(core.y_m), float(core.y_m) + float(core.h_m)):
                    self._add_tie(
                        x, y, float(self._params.preferred_t_mm), storeys,
                        "core corner: an RC core inside a masonry building is always framed", core.id,
                    )

    def _thickness_at(self, storey: int, bearing: Sequence[str], key: Tuple[int, int]) -> float:
        """Thickest bearing wall passing through a plan point, for the tie depth."""
        chosen = set(bearing)
        best = float(self._params.preferred_t_mm)
        x = key[0] / 1000.0
        y = key[1] / 1000.0
        for wall in self._walls:
            if wall.storey != storey or wall.id not in chosen:
                continue
            axis = _axis_of(wall)
            if axis is None:
                continue
            orient, pos, lo, hi = axis
            on_line = abs(pos - (y if orient == "h" else x)) <= GEOM_TOL_M
            station = x if orient == "h" else y
            if on_line and lo - GEOM_TOL_M <= station <= hi + GEOM_TOL_M:
                best = max(best, _t_mm(wall))
        return best

    # -- reporting and assembly --------------------------------------------

    def _wall_checks(self, wall: WallLine, bearing: Sequence[str]) -> Tuple[List[Dict[str, Any]], bool]:
        """The clause rows for one wall's report, and whether its data was assumed."""
        record = self._elig.get(wall.id)
        checks = []  # type: List[Dict[str, Any]]
        if record is not None:
            checks.append(
                {
                    "clause_id": "IS1905:1987 Cl 4.6.1",
                    "check": "SR",
                    "ok": bool(record.sr_ok),
                    "value": round(float(record.sr), 4),
                    "limit": round(float(is1905.max_slenderness(self._params.mortar_grade)), 4),
                    "units": "",
                }
            )
        assumed = any(opening.provenance != Provenance.DRESSED for opening in wall.openings)
        if wall.id not in set(bearing):
            return (checks, assumed)
        if self._category == "A":
            checks.append(
                {
                    "clause_id": "IS4326:1993 Table 4",
                    "check": "table_4",
                    "ok": None,
                    "status": "EXEMPT",
                    "note": "category A is exempt from Table 4; the IS 1905 pier rules still apply",
                }
            )
            return (checks, assumed)
        if not wall.openings:
            checks.append(
                {
                    "clause_id": "IS4326:1993 Table 4",
                    "check": "table_4",
                    "ok": None,
                    "status": "NOT-RUN",
                    "note": "the wall carries no opening geometry, so the check is reported not run "
                    "rather than silently passed",
                }
            )
            return (checks, assumed)
        rules = is4326.opening_limits(self._count, self._category)
        for segment in self._segments(wall, bearing):
            violations = is4326.check_openings(segment["wall"], rules, segment["corner_ends"])
            if not violations:
                checks.append(
                    {
                        "clause_id": "IS4326:1993 Table 4",
                        "check": "table_4",
                        "segment_id": segment["id"],
                        "ok": True,
                        "status": "ASSUMED-OPENINGS" if assumed else "OK",
                    }
                )
                continue
            for violation in violations:
                checks.append(
                    {
                        "clause_id": violation.clause_id,
                        "check": violation.check,
                        "segment_id": segment["id"],
                        "ok": False,
                        "value": round(float(violation.value), 6),
                        "limit": round(float(violation.limit), 6),
                        "units": violation.units,
                        "message": violation.message,
                        "status": "ASSUMED-OPENINGS" if assumed else "MEASURED",
                        "resolved_by": "STRENGTHENED" if wall.id in self._strengthened else "OPEN",
                        "remedies": [
                            "shrink or move the opening (a user action, the geometry is never edited here)",
                            "jamb tie columns with a lintel band continuous through the pier",
                            "demote the wall where the cover holds without it",
                        ],
                    }
                )
        return (checks, assumed)

    def _wall_reports(self, system: str, bearing_by_storey: Dict[int, List[str]]) -> List[WallReport]:
        demoted = {row["wall_id"]: row for row in self._demoted}
        promoted = {row.wall_id: row for row in self._promoted}
        rows = []  # type: List[WallReport]
        for wall in sorted(self._walls, key=lambda w: (w.storey, w.id)):
            bearing = bearing_by_storey.get(int(wall.storey), [])
            record = self._elig.get(wall.id)
            checks, assumed = self._wall_checks(wall, bearing)
            if wall.id in set(bearing):
                action = "STRENGTHENED" if wall.id in self._strengthened else "BEARING"
                detail = ""
                if wall.id in promoted:
                    action = "PROMOTED-REQUEST"
                    detail = promoted[wall.id].reason
                elif wall.id in self._strengthened:
                    detail = "jamb tie columns and a lintel band through the pier; the wall stays bearing"
            elif wall.id in demoted:
                action = "DEMOTED"
                detail = demoted[wall.id]["reason"]
            else:
                action = "NON-BEARING"
                detail = "; ".join(record.reasons) if record else ""
            if assumed:
                self._assumed_openings.append(wall.id)
            rows.append(
                WallReport(
                    wall_id=wall.id,
                    storey=int(wall.storey),
                    t_mm=_t_mm(wall),
                    role=wall.role.value if hasattr(wall.role, "value") else str(wall.role),
                    action=action,
                    eligibility=list(record.reasons) if record else [],
                    checks=checks,
                    detail=detail,
                    assumed_openings=assumed,
                )
            )
        return rows

    def _reconcile_promotions(self, bearing_by_storey: Dict[int, List[str]]) -> None:
        """Drop every thickness promotion the final bearing set did not use.

        A `GeometryChangeRequest` is only honest while the cover needs the wall
        (spec 3, the promotion contract): a request whose wall the report rows
        call NON-BEARING would ask the user to thicken a wall that does nothing.
        The drop is traced per wall, never silent, and the matching
        `W_RELEASED_CAP` ladder entry goes with it.
        """
        bearing = {}  # type: Dict[int, set]
        for storey, ids in bearing_by_storey.items():
            bearing[int(storey)] = set(ids)
        orphans = sorted(
            request.wall_id
            for request in self._promoted
            if request.wall_id not in bearing.get(int(request.storey), set())
        )
        if not orphans:
            return
        dropped = set(orphans)
        self._promoted = [request for request in self._promoted if request.wall_id not in dropped]
        self._lifted -= dropped
        self._resolved = [
            row
            for row in self._resolved
            if not (str(row.get("action")) == "PROMOTED-REQUEST" and str(row.get("wall_id")) in dropped)
        ]
        self._warnings = [
            entry
            for entry in self._warnings
            if not (
                entry.code == "W_RELEASED_CAP"
                and "kept bearing" in entry.message
                and set(entry.element_ids) <= dropped
            )
        ]
        for wall_id in orphans:
            self._trace.append(
                "promotion request on %s dropped: the final cover does not need the wall to bear, "
                "so its report row stays NON-BEARING and no thickness change is asked for" % wall_id
            )

    def _finish_masonry(self, system: str, covers: Dict[int, _CoverResult]) -> MasonryPlacement:
        bearing_by_storey = {storey: list(covers[storey].bearing) for storey in self._storeys}
        self._close_cross_wall_gaps(system, bearing_by_storey)
        # a wall the cross wall pass promoted has not met Table 4 yet, so give it
        # one strengthen pass rather than leaving an open breach in the report
        late_covers = {
            storey: _CoverResult(storey, bearing_by_storey.get(storey, []), [], [], [], [])
            for storey in self._storeys
        }
        late = self._table4_violations(late_covers)
        if late:
            self._resolve_table4(system, late_covers, late, late=True)
        self._reconcile_promotions(bearing_by_storey)
        self._confine(system, bearing_by_storey)
        bands, band_rows = self._bands(system, bearing_by_storey)
        band_level = {}  # type: Dict[int, float]
        for row in band_rows:
            if row.kind == BandKind.LINTEL.value and row.spec is not None:
                band_level[row.storey] = row.level_m - _storey_base(self._model, row.storey)
        lintels, lintel_rows, absorbed = self._lintels(bearing_by_storey, band_level)
        bars = self._vertical_bars(bearing_by_storey)
        reports = self._wall_reports(system, bearing_by_storey)
        if absorbed:
            self._trace.append(
                "lintel band: %d opening(s) absorbed into the band, their heads sit within %d mm of it"
                % (len(absorbed), int(round(self._params.lintel_unify_tol_mm)))
            )
        if self._assumed_openings:
            self._warn(
                "W_ASSUMED_OPENINGS",
                "the IS 4326 Table 4 checks on %d wall(s) were measured on openings that did not come "
                "from a dressed plan; every affected row is labeled ASSUMED-OPENINGS"
                % len(set(self._assumed_openings)),
                sorted(set(self._assumed_openings)),
                clause="IS4326:1993 Table 4",
            )
        elif not self._model.doors_known():
            self._warn(
                "N_WINDOWS_NOT_ASSUMED",
                "no opening geometry reached this placement, so the Table 4 rows read NOT-RUN and no "
                "window lintels are scheduled",
                [],
                clause="IS4326:1993 Table 4",
            )
        self._decision.system = system
        # the cross wall pass may have promoted more walls, so the panels the report
        # carries are retraced from the final bearing set, never the pre-pass ones
        panels = []  # type: List[Panel]
        for storey in self._storeys:
            grid = self._grids[storey]
            if not grid.has_cells():
                continue
            on_storey = [w for w in self._walls if w.storey == storey]
            panels.extend(
                grid.panels(
                    _support_lines(on_storey, bearing_by_storey.get(storey, []), self._extra.get(storey, ()))
                )
            )
        bearing_all = sorted({wall_id for ids in bearing_by_storey.values() for wall_id in ids})
        self._trace.append(
            "final: %s with %d bearing wall(s), %d band(s), %d lintel(s), %d tie column(s), %d vertical bar run(s)"
            % (system, len(bearing_all), len(bands), len(lintels), len(self._ties), len(bars))
        )
        return MasonryPlacement(
            system=self._decision,
            params=self._params,
            bearing_walls=bearing_all,
            demoted=sorted(self._demoted, key=lambda row: str(row["wall_id"])),
            promoted=sorted(self._promoted, key=lambda row: row.wall_id),
            bands=bands,
            band_schedule=band_rows,
            lintels=lintels,
            lintel_schedule=lintel_rows,
            vertical_bars=bars,
            tie_columns=sorted(self._ties.values(), key=lambda tie: tie.id),
            pilasters=sorted(self._pilasters, key=lambda pil: pil.id),
            hybrid_beams=sorted(self._hybrid, key=lambda beam: beam.id),
            panels=panels,
            cover_gaps=[gap for storey in self._storeys for gap in covers[storey].gaps],
            violations_resolved=sorted(self._resolved, key=lambda row: (str(row["wall_id"]), str(row["action"]))),
            per_wall_reports=reports,
            warnings=list(self._warnings),
            trace=list(self._trace),
        )

    def _finish_rc_frame(self, system: str) -> MasonryPlacement:
        """No masonry bears, but infill openings still need lintels (finding 40)."""
        self._decision.system = System.RC_FRAME.value
        wall_ids = {}  # type: Dict[int, List[str]]
        for wall in self._walls:
            if wall.openings:
                wall_ids.setdefault(int(wall.storey), []).append(wall.id)
        lintels, lintel_rows, _absorbed = self._lintels(
            {storey: sorted(ids) for storey, ids in wall_ids.items()}, None
        )
        self._trace.append(
            "rc_frame: no masonry wall bears, so no band and no vertical steel are placed; "
            "lintels are still scheduled over %d opening(s) in the masonry infill" % len(lintel_rows)
        )
        reports = self._wall_reports(System.RC_FRAME.value, {storey: [] for storey in self._storeys})
        return MasonryPlacement(
            system=self._decision,
            params=self._params,
            bearing_walls=[],
            lintels=lintels,
            lintel_schedule=lintel_rows,
            per_wall_reports=reports,
            warnings=list(self._warnings),
            trace=list(self._trace),
        )


# ---------------------------------------------------------------------------
# module level surface
# ---------------------------------------------------------------------------


def place(model: StructuralModel, params: Optional[MasonryParams] = None) -> MasonryPlacement:
    """Run the masonry placement. Internal function; `api.py run_design` calls it."""
    return MasonryPlacer(params).place(model, params)


def lintels_for_infill(
    model: StructuralModel,
    params: Optional[MasonryParams] = None,
    wall_ids: Optional[Sequence[str]] = None,
) -> Tuple[List[Lintel], List[LintelRun]]:
    """Lintels over the openings in masonry infill walls, for the RC frame path.

    Finding 40: the frame path calls this module's lintel routine rather than
    growing a second one. There is no band in a frame, so nothing is absorbed and
    every opening takes its own lintel, merged with a neighbour whose head is
    within `lintel_unify_tol_mm`. Pass `wall_ids` to restrict the walls; the
    default covers every masonry wall in the model that carries an opening.
    Returns (model `Lintel` elements, schedule rows).
    """
    placer = MasonryPlacer(params)
    placer._model = model
    placer._params = params or placer.params
    placer._walls = _masonry_walls(model)
    placer._storeys = _storeys_of(model)
    wanted = None if wall_ids is None else set(wall_ids)
    by_storey = {}  # type: Dict[int, List[str]]
    for wall in placer._walls:
        if not wall.openings:
            continue
        if wanted is not None and wall.id not in wanted:
            continue
        by_storey.setdefault(int(wall.storey), []).append(wall.id)
    elements, rows, _absorbed = placer._lintels(
        {storey: sorted(ids) for storey, ids in by_storey.items()}, None
    )
    return (elements, rows)


def tie_columns_for_point_loads(
    placement: MasonryPlacement,
    point_loads: Sequence[Dict[str, Any]],
    params: Optional[MasonryParams] = None,
) -> List[TieColumn]:
    """Optional point-load helper, currently unreached by the design pipeline.

    Placement never reads a load, so this helper cannot run inside `place()`.
    The shipped masonry path instead places unconditional ties at injected
    beam-line ends and core corners, which already covers its beam reactions.
    If a future caller supplies post-takedown reactions, it must pass

        point_loads = [{"x_m": .., "y_m": .., "p_kn": .., "wall_id": .., "t_mm": ..}, ...]

    Any reaction above `params.point_load_limit_kn` (25 kN by default) gets a
    tie column under it. The returned columns are merged into
    `placement.tie_columns` in place and also handed back, sorted by id.
    """
    params = params or placement.params
    limit = float(params.point_load_limit_kn)
    existing = {(_mm(tie.x_m), _mm(tie.y_m)): tie for tie in placement.tie_columns}
    added = []  # type: List[TieColumn]
    for load in sorted(point_loads, key=lambda item: (float(item.get("x_m", 0.0)), float(item.get("y_m", 0.0)))):
        p_kn = float(load.get("p_kn", 0.0))
        if p_kn <= limit + _ETA:
            continue
        x = float(load.get("x_m", 0.0))
        y = float(load.get("y_m", 0.0))
        thickness = float(load.get("t_mm", params.preferred_t_mm))
        storeys = [int(s) for s in load.get("storeys", [0])]
        key = (_mm(x), _mm(y))
        reason = (
            "point load %.1f kN on masonry is above the %.1f kN limit, so a tie column carries it "
            "(IS 4326 Cl 8.4.8)" % (p_kn, limit)
        )
        if key in existing:
            tie = existing[key]
            tie.storeys = sorted(set(tie.storeys) | set(storeys))
            tie.d_mm = max(tie.d_mm, thickness)
            continue
        tie = TieColumn(
            id="tie-@" + pos_token(x) + "x" + pos_token(y),
            x_m=x,
            y_m=y,
            w_mm=TIE_COLUMN_WIDTH_MM,
            d_mm=max(thickness, 1.0),
            storeys=sorted(set(storeys)),
            reason=reason,
            wall_id=load.get("wall_id"),
        )
        existing[key] = tie
        added.append(tie)
    placement.tie_columns = sorted(existing.values(), key=lambda tie: tie.id)
    return sorted(added, key=lambda tie: tie.id)
