"""Foundation layout: strips under bearing walls, pads under columns, and the
combined and strapped cases where those two collide with each other or with a
boundary.

Position in the pipeline
------------------------
Footings need loads, so this module runs AFTER the takedown, not with the rest
of placement (finding 18). `structural/api.py run_design` is the one caller that
sequences it:

    placement -> load model -> takedown -> layout_foundations -> ... -> report

One function serves both systems: the masonry pipeline hands it bearing walls
plus its tie columns, and the frame placer hands it its own columns. Because
there is a single overlap resolver, a mixed building cannot double-place a
footing under a column that already sits on a strip.

The load contract (documented deliberately, finding 18)
-------------------------------------------------------
`wall_loads` and `column_loads` are PLAIN DICTS, not a takedown object, so this
module never imports the analysis package:

    wall_loads   = {wall_id: n_service_kn_per_m}    service line load at the
                   base of that wall, cumulative over the storeys above it
    column_loads = {column_id or stack_id: p_service_kn}   service axial load at
                   the base of that column stack

The orchestrator adapts the takedown result into those two dicts in wave 5. A
wall or column with no entry is sized on its geometric minimum and says so, on
the ladder and in the report: nothing is quietly assumed to be zero.

Units are SI throughout: metres, kN, kPa. Section dimensions are named `*_mm`.
Output is sorted, so two runs on one model give byte-identical `to_dict()`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..data._loader import load_yaml
from ..model import (
    Disclosure,
    Footing,
    FootingKind,
    GEOM_TOL_M,
    StructuralModel,
    WallLine,
    WallRole,
    footing_id,
    make_disclosure,
    pos_token,
    strip_footing_id,
    wall_axis,
)

PLACED_BY = "placement.foundations"

SOIL_TABLE = "soil_defaults"

_ETA = 1e-9


class FoundationLoadError(ValueError):
    """A compression-only foundation received an unsupported load demand."""

    code = "E_GRAVITY_UPLIFT"

    def __init__(self, message: str, element_ids: Sequence[str] = ()) -> None:
        super(FoundationLoadError, self).__init__(message)
        self.element_ids = list(element_ids)


# ---------------------------------------------------------------------------
# soil (finding 30: one frozen shape, one mapping table, 1.5 m everywhere)
# ---------------------------------------------------------------------------


@dataclass
class Soil:
    """{type, sbc_kpa, soft, founding_depth_m} plus the water table, if known."""

    type: str = "II"
    sbc_kpa: float = 150.0
    soft: bool = False
    founding_depth_m: float = 1.5
    water_table_m: Optional[float] = None
    assumed: List[str] = field(default_factory=list)

    @staticmethod
    def defaults() -> Dict[str, Any]:
        """The `data/soil_defaults.yaml` default block."""
        return dict(load_yaml(SOIL_TABLE)["defaults"])

    @staticmethod
    def from_params(value: Optional[Dict[str, Any]] = None) -> "Soil":
        """Build a Soil from a request block, filling gaps from the catalogue.

        Every field that falls back is named in `assumed`, and
        `layout_foundations` turns those names into W_ASSUMED_SBC and
        W_ASSUMED_FOUNDING_DEPTH ladder entries. Nothing defaults in silence.
        """
        table = load_yaml(SOIL_TABLE)
        base = dict(table["defaults"])
        supplied = dict(value or {})
        incoming = supplied.get("assumed", [])
        if isinstance(incoming, (list, tuple, set, frozenset)):
            assumed = {str(name) for name in incoming if str(name)}
        elif incoming is None:
            assumed = set()
        else:
            assumed = {str(incoming)}
        soil_type = str(supplied.get("type", base["type"]))
        if "type" not in supplied:
            assumed.add("type")
        types = table.get("types", {})
        row = types.get(soil_type, {}) if isinstance(types, dict) else {}
        if "sbc_kpa" in supplied and supplied["sbc_kpa"] is not None:
            sbc = float(supplied["sbc_kpa"])
        elif row.get("typical_sbc_kpa") is not None:
            sbc = float(row["typical_sbc_kpa"])
            assumed.add("sbc_kpa")
        else:
            sbc = float(base["sbc_kpa"])
            assumed.add("sbc_kpa")
        if "founding_depth_m" in supplied and supplied["founding_depth_m"] is not None:
            depth = float(supplied["founding_depth_m"])
        else:
            depth = float(base["founding_depth_m"])
            assumed.add("founding_depth_m")
        if "soft" in supplied:
            soft = bool(supplied["soft"])
        else:
            soft = bool(row.get("soft", base["soft"]))
        water = supplied.get("water_table_m", base.get("water_table_depth_m"))
        return Soil(
            type=soil_type,
            sbc_kpa=sbc,
            soft=soft,
            founding_depth_m=depth,
            water_table_m=None if water is None else float(water),
            assumed=sorted(assumed),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "sbc_kpa": round(float(self.sbc_kpa), 6),
            "soft": bool(self.soft),
            "founding_depth_m": round(float(self.founding_depth_m), 6),
            "water_table_m": None if self.water_table_m is None else round(float(self.water_table_m), 6),
            "assumed": list(self.assumed),
        }


@dataclass
class FoundationParams:
    """Sizing knobs. Lengths are METRES unless the name ends in `_mm`."""

    strip_min_width_m: float = 0.45
    strip_width_t_factor: float = 2.0
    rc_strip_t_factor: float = 3.0
    strip_round_mm: float = 50.0
    pad_min_m: float = 1.0
    pad_snap_mm: float = 150.0
    combine_gap_m: float = 0.15
    centroid_tol: float = 0.05
    strap_search_m: float = 6.0
    column_on_strip_factor: float = 0.5
    taper_m: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strip_min_width_m": round(float(self.strip_min_width_m), 6),
            "strip_width_t_factor": round(float(self.strip_width_t_factor), 6),
            "rc_strip_t_factor": round(float(self.rc_strip_t_factor), 6),
            "strip_round_mm": round(float(self.strip_round_mm), 6),
            "pad_min_m": round(float(self.pad_min_m), 6),
            "pad_snap_mm": round(float(self.pad_snap_mm), 6),
            "combine_gap_m": round(float(self.combine_gap_m), 6),
            "centroid_tol": round(float(self.centroid_tol), 6),
            "strap_search_m": round(float(self.strap_search_m), 6),
            "column_on_strip_factor": round(float(self.column_on_strip_factor), 6),
            "taper_m": round(float(self.taper_m), 6),
        }


# ---------------------------------------------------------------------------
# footing records
# ---------------------------------------------------------------------------


@dataclass
class Widening:
    """A local strip widening under a column that landed on the strip axis."""

    column_id: str
    at_m: float
    width_m: float
    taper_m: float
    p_service_kn: float
    s0_m: float = 0.0
    s1_m: float = 0.0
    effective_length_m: float = 0.0
    line_load_kn_per_m: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_id": self.column_id,
            "at_m": round(float(self.at_m), 6),
            "width_m": round(float(self.width_m), 6),
            "taper_m": round(float(self.taper_m), 6),
            "p_service_kn": round(float(self.p_service_kn), 6),
            "s0_m": round(float(self.s0_m), 6),
            "s1_m": round(float(self.s1_m), 6),
            "effective_length_m": round(float(self.effective_length_m), 6),
            "line_load_kn_per_m": round(float(self.line_load_kn_per_m), 6),
        }


@dataclass
class StripFooting:
    """A continuous spread footing under one run of collinear bearing walls."""

    id: str
    wall_ids: List[str]
    orient: str
    pos_m: float
    s0_m: float
    s1_m: float
    width_m: float
    depth_m: float
    wall_t_m: float
    rc: bool
    eccentric: bool = False
    e_m: float = 0.0
    w_service_kn_per_m: float = 0.0
    load_source: str = "takedown"
    mitre_m: Tuple[float, float] = (0.0, 0.0)
    widenings: List[Widening] = field(default_factory=list)
    note: str = ""

    def polyline(self) -> List[Tuple[float, float]]:
        """Centreline of the strip in plan, mitred into its neighbours."""
        lo = self.s0_m - self.mitre_m[0]
        hi = self.s1_m + self.mitre_m[1]
        if self.orient == "h":
            return [(lo, self.pos_m), (hi, self.pos_m)]
        return [(self.pos_m, lo), (self.pos_m, hi)]

    def rect(self) -> Tuple[float, float, float, float]:
        """(x, y, w, h) of the strip rectangle in metres."""
        points = self.polyline()
        half = 0.5 * self.width_m
        if self.orient == "h":
            return (points[0][0], self.pos_m - half, points[1][0] - points[0][0], self.width_m)
        return (self.pos_m - half, points[0][1], self.width_m, points[1][1] - points[0][1])

    def length_m(self) -> float:
        return (self.s1_m - self.s0_m) + self.mitre_m[0] + self.mitre_m[1]

    def to_dict(self) -> Dict[str, Any]:
        x, y, w, h = self.rect()
        return {
            "id": self.id,
            "kind": FootingKind.STRIP.value,
            "wall_ids": list(self.wall_ids),
            "orient": self.orient,
            "pos_m": round(float(self.pos_m), 6),
            "s0_m": round(float(self.s0_m), 6),
            "s1_m": round(float(self.s1_m), 6),
            "width_m": round(float(self.width_m), 6),
            "length_m": round(float(self.length_m()), 6),
            "depth_m": round(float(self.depth_m), 6),
            "wall_t_m": round(float(self.wall_t_m), 6),
            "rc": bool(self.rc),
            "eccentric": bool(self.eccentric),
            "e_m": round(float(self.e_m), 6),
            "mitre_m": [round(float(self.mitre_m[0]), 6), round(float(self.mitre_m[1]), 6)],
            "rect_m": [round(x, 6), round(y, 6), round(w, 6), round(h, 6)],
            "polyline_m": [[round(px, 6), round(py, 6)] for px, py in self.polyline()],
            "widenings": [row.to_dict() for row in self.widenings],
            "demands": {
                "w_service_kn_per_m": round(float(self.w_service_kn_per_m), 6),
                "e_m": round(float(self.e_m), 6),
                "source": self.load_source,
            },
            "note": self.note,
        }


@dataclass
class PadFooting:
    """A square isolated footing under one column stack."""

    id: str
    column_ids: List[str]
    x_m: float
    y_m: float
    w_m: float
    h_m: float
    depth_m: float
    p_service_kn: float = 0.0
    load_source: str = "takedown"
    eccentric: bool = False
    e_m: float = 0.0
    load_x_m: float = 0.0
    load_y_m: float = 0.0
    note: str = ""

    def rect(self) -> Tuple[float, float, float, float]:
        return (self.x_m - 0.5 * self.w_m, self.y_m - 0.5 * self.h_m, self.w_m, self.h_m)

    def to_dict(self) -> Dict[str, Any]:
        x, y, w, h = self.rect()
        return {
            "id": self.id,
            "kind": FootingKind.ISOLATED.value,
            "column_ids": list(self.column_ids),
            "x_m": round(float(self.x_m), 6),
            "y_m": round(float(self.y_m), 6),
            "w_m": round(float(self.w_m), 6),
            "h_m": round(float(self.h_m), 6),
            "depth_m": round(float(self.depth_m), 6),
            "rect_m": [round(x, 6), round(y, 6), round(w, 6), round(h, 6)],
            "eccentric": bool(self.eccentric),
            "demands": {
                "p_service_kn": round(float(self.p_service_kn), 6),
                "e_m": round(float(self.e_m), 6),
                "load_x_m": round(float(self.load_x_m), 6),
                "load_y_m": round(float(self.load_y_m), 6),
                "source": self.load_source,
            },
            "note": self.note,
        }


@dataclass
class CombinedFooting:
    """One rectangle under two or more loads that could not stand apart."""

    id: str
    member_ids: List[str]
    column_ids: List[str]
    x_m: float
    y_m: float
    w_m: float
    h_m: float
    depth_m: float
    p_service_kn: float
    resultant_x_m: float
    resultant_y_m: float
    centroid_offset_ratio: float
    eccentric: bool = False
    e_m: float = 0.0
    note: str = ""

    def rect(self) -> Tuple[float, float, float, float]:
        return (self.x_m - 0.5 * self.w_m, self.y_m - 0.5 * self.h_m, self.w_m, self.h_m)

    def to_dict(self) -> Dict[str, Any]:
        x, y, w, h = self.rect()
        return {
            "id": self.id,
            "kind": FootingKind.COMBINED.value,
            "member_ids": list(self.member_ids),
            "column_ids": list(self.column_ids),
            "x_m": round(float(self.x_m), 6),
            "y_m": round(float(self.y_m), 6),
            "w_m": round(float(self.w_m), 6),
            "h_m": round(float(self.h_m), 6),
            "depth_m": round(float(self.depth_m), 6),
            "rect_m": [round(x, 6), round(y, 6), round(w, 6), round(h, 6)],
            "centroid_offset_ratio": round(float(self.centroid_offset_ratio), 6),
            "eccentric": bool(self.eccentric),
            "demands": {
                "p_service_kn": round(float(self.p_service_kn), 6),
                "resultant_x_m": round(float(self.resultant_x_m), 6),
                "resultant_y_m": round(float(self.resultant_y_m), 6),
                "e_m": round(float(self.e_m), 6),
                "source": "takedown",
            },
            "note": self.note,
        }


@dataclass
class StrapBeam:
    """The beam that ties an eccentric boundary footing back to an interior one."""

    id: str
    from_id: str
    to_id: str
    a: Tuple[float, float]
    b: Tuple[float, float]
    e_m: float
    note: str = ""

    def length_m(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": FootingKind.STRAP.value,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "a_m": [round(float(self.a[0]), 6), round(float(self.a[1]), 6)],
            "b_m": [round(float(self.b[0]), 6), round(float(self.b[1]), 6)],
            "length_m": round(float(self.length_m()), 6),
            "e_m": round(float(self.e_m), 6),
            "note": self.note,
        }


@dataclass
class FoundationPlan:
    """Everything `layout_foundations` decided, ready for design and the report."""

    strips: List[StripFooting] = field(default_factory=list)
    pads: List[PadFooting] = field(default_factory=list)
    combined: List[CombinedFooting] = field(default_factory=list)
    straps: List[StrapBeam] = field(default_factory=list)
    warnings: List[Disclosure] = field(default_factory=list)
    report: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strips": [row.to_dict() for row in self.strips],
            "pads": [row.to_dict() for row in self.pads],
            "combined": [row.to_dict() for row in self.combined],
            "straps": [row.to_dict() for row in self.straps],
            "warnings": [entry.to_dict() for entry in self.warnings],
            "report": _plain(self.report),
        }

    def footings(self) -> List[Footing]:
        """The plan as model `Footing` elements, in id order."""
        out = []  # type: List[Footing]
        for strip in self.strips:
            x, y, w, h = strip.rect()
            out.append(
                Footing(
                    id=strip.id,
                    kind=FootingKind.STRIP,
                    supports=list(strip.wall_ids),
                    x_m=x + 0.5 * w,
                    y_m=y + 0.5 * h,
                    w_m=w,
                    h_m=h,
                    depth_m=strip.depth_m,
                    placed_by=PLACED_BY,
                    eccentric=strip.eccentric,
                    e_m=strip.e_m,
                    w_service_kn_per_m=strip.w_service_kn_per_m,
                )
            )
        for pad in self.pads:
            out.append(
                Footing(
                    id=pad.id,
                    kind=FootingKind.ISOLATED,
                    supports=list(pad.column_ids),
                    x_m=pad.x_m,
                    y_m=pad.y_m,
                    w_m=pad.w_m,
                    h_m=pad.h_m,
                    depth_m=pad.depth_m,
                    placed_by=PLACED_BY,
                    eccentric=pad.eccentric,
                    e_m=pad.e_m,
                )
            )
        for comb in self.combined:
            out.append(
                Footing(
                    id=comb.id,
                    kind=FootingKind.COMBINED,
                    supports=list(comb.column_ids),
                    x_m=comb.x_m,
                    y_m=comb.y_m,
                    w_m=comb.w_m,
                    h_m=comb.h_m,
                    depth_m=comb.depth_m,
                    placed_by=PLACED_BY,
                    eccentric=comb.eccentric,
                    e_m=comb.e_m,
                )
            )
        for strap in self.straps:
            out.append(
                Footing(
                    id=strap.id,
                    kind=FootingKind.STRAP,
                    supports=[strap.from_id, strap.to_id],
                    x_m=0.5 * (strap.a[0] + strap.b[0]),
                    y_m=0.5 * (strap.a[1] + strap.b[1]),
                    w_m=abs(strap.b[0] - strap.a[0]),
                    h_m=abs(strap.b[1] - strap.a[1]),
                    depth_m=None,
                    placed_by=PLACED_BY,
                )
            )
        return sorted(out, key=lambda f: f.id)

    def write_back(self, model: StructuralModel) -> StructuralModel:
        """Replace this module's footings on the model. Idempotent."""
        model.footings = [f for f in model.footings if f.placed_by != PLACED_BY]
        model.footings.extend(self.footings())
        model.footings.sort(key=lambda f: f.id)
        model.meta["foundation_plan"] = self.to_dict()
        seen = {(entry.code, entry.message) for entry in model.warnings}
        for entry in self.warnings:
            if (entry.code, entry.message) in seen:
                continue  # a second write_back must leave the ladder as it was
            seen.add((entry.code, entry.message))
            model.add_warning(
                entry.code, entry.message, entry.element_ids, clause=entry.clause, stage=entry.stage
            )
        return model


def _plain(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {str(key): _plain(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    return str(value)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mm(value_m: float) -> int:
    return int(round(float(value_m) * 1000.0))


def _round_up(value: float, step_mm: float) -> float:
    """`value` metres rounded up to a whole number of `step_mm` millimetres."""
    step = float(step_mm) / 1000.0
    if step <= 0.0:
        return float(value)
    return math.ceil(float(value) / step - 1e-9) * step


def _merge_runs(items: Sequence[Tuple[float, float, str]]) -> List[Tuple[float, float, List[str]]]:
    """Merge touching or overlapping (lo, hi, id) spans into continuous runs."""
    ordered = sorted(items, key=lambda item: (item[0], item[1], item[2]))
    out = []  # type: List[Tuple[float, float, List[str]]]
    for lo, hi, name in ordered:
        if out and lo <= out[-1][1] + GEOM_TOL_M:
            out[-1] = (out[-1][0], max(out[-1][1], hi), out[-1][2] + [name])
        else:
            out.append((lo, hi, [name]))
    return out


def _rects_touch(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], gap: float) -> bool:
    """True when two rectangles overlap or their clear gap is below `gap`."""
    dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]))
    dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]))
    return dx < gap - _ETA and dy < gap - _ETA


def _plot_bounds(model: StructuralModel) -> Optional[Tuple[float, float, float, float]]:
    """(x0, y0, x1, y1) of the plot, taken from the ground storey wall network."""
    xs = []  # type: List[float]
    ys = []  # type: List[float]
    ground = min((w.storey for w in model.walls), default=None)
    if ground is None:
        return None
    for wall in model.walls:
        if wall.storey != ground:
            continue
        xs.extend([wall.a[0], wall.b[0]])
        ys.extend([wall.a[1], wall.b[1]])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _is_foundation_party_boundary(model: StructuralModel, wall: WallLine) -> bool:
    """Whether this party wall is an explicitly usable no-cross boundary.

    Legacy/direct structural models without metadata retain the historical
    interpretation that every `PARTY` wall is a boundary. Adapters that know
    their party label means only an internal demising wall provide an explicit
    (possibly empty) id roster instead of laundering adjacency into ownership.
    """
    if wall.role != WallRole.PARTY:
        return False
    explicit = model.meta.get("foundation_party_boundary_wall_ids")
    if isinstance(explicit, (list, tuple, set)):
        return str(wall.id) in {str(one) for one in explicit}
    return True


def _party_lines(model: StructuralModel) -> List[Tuple[str, float]]:
    """Explicit no-cross party wall centrelines (spec 10.5)."""
    out = set()
    for wall in model.walls:
        if not _is_foundation_party_boundary(model, wall):
            continue
        axis = wall_axis(wall)
        if axis is None:
            continue
        out.add((axis[0], round(axis[1], 6)))
    return sorted(out)


def _party_inward(
    model: StructuralModel, orient: str, pos: float, reference: Optional[float] = None
) -> float:
    """Side of a party line owned by this footing.

    Pads use their own load point, so an internal demising line never turns the
    opposite half of the building into forbidden ground. A load exactly on the
    line, including a wall strip, uses the model footprint centre as the stable
    tie breaker.
    """
    if reference is not None:
        if reference < pos - GEOM_TOL_M:
            return -1.0
        if reference > pos + GEOM_TOL_M:
            return 1.0
    bounds = _plot_bounds(model)
    plot = model.meta.get("plot_bounds_m")
    if isinstance(plot, (list, tuple)) and len(plot) == 4:
        bounds = tuple(float(value) for value in plot)
    if bounds is None:
        return 1.0
    centre = 0.5 * (bounds[0] + bounds[2]) if orient == "v" else 0.5 * (bounds[1] + bounds[3])
    return 1.0 if centre >= pos else -1.0


def _lookup_load(loads: Dict[str, float], keys: Sequence[str]) -> Tuple[float, bool]:
    """The largest load found under any of these ids, and whether one was found."""
    best = None  # type: Optional[float]
    for key in keys:
        if key in loads and loads[key] is not None:
            value = float(loads[key])
            best = value if best is None else max(best, value)
    if best is None or abs(best) <= _ETA:
        return (0.0, False)
    return (best, True)


def layout_foundations(
    model: StructuralModel,
    bearing_wall_ids: Sequence[str] = (),
    column_ids: Sequence[str] = (),
    wall_loads: Optional[Dict[str, float]] = None,
    column_loads: Optional[Dict[str, float]] = None,
    soil: Optional[Any] = None,
    params: Optional[FoundationParams] = None,
    write_back: bool = True,
) -> FoundationPlan:
    """Size and place every footing under a placed structure.

    Arguments
    ---------
    model
        The placed `StructuralModel`. Written to when `write_back` is true.
    bearing_wall_ids
        Wall ids the placement decided will bear. Only the ground storey members
        take a strip; the storeys above hand their load down through the stack,
        which is what the takedown already summed.
    column_ids
        Column ids needing a footing: masonry tie columns, frame columns, or
        both in a mixed building.
    wall_loads
        {wall_id: n_service_kn_per_m}. See the module docstring for the contract.
    column_loads
        {column_id or stack_id: p_service_kn}.
    soil
        A `Soil`, or the frozen request dict {type, sbc_kpa, soft,
        founding_depth_m}; `None` takes the catalogue defaults and discloses them.
    params
        `FoundationParams`; defaults are the spec 10 numbers.
    write_back
        Write the result into `model.footings` (replacing this module's earlier
        output) and push the ladder entries onto the model.

    Returns a `FoundationPlan`. Nothing raises on a missing load: the footing is
    sized on its geometric minimum and both the ladder and the report say so.
    """
    params = params or FoundationParams()
    if isinstance(soil, Soil):
        resolved = soil
    else:
        resolved = Soil.from_params(soil if isinstance(soil, dict) else None)
    wall_loads = dict(wall_loads or {})
    column_loads = dict(column_loads or {})
    non_positive_columns = sorted(
        str(key) for key, value in column_loads.items() if float(value) <= _ETA
    )
    non_positive_walls = sorted(
        str(key) for key, value in wall_loads.items() if float(value) <= _ETA
    )
    if non_positive_columns or non_positive_walls:
        ids = non_positive_columns + non_positive_walls
        raise FoundationLoadError(
            "compression-only strip/pad placement requires positive service reactions; "
            "non-positive demand was supplied for " + ", ".join(ids[:20]),
            ids,
        )
    plan = FoundationPlan()
    notes = []  # type: List[str]

    if "sbc_kpa" in resolved.assumed:
        plan.warnings.append(
            make_disclosure(
                "W_ASSUMED_SBC",
                "no safe bearing capacity was supplied; %.0f kPa taken for soil type %s from "
                "data/soil_defaults.yaml, which is a catalogue default and not a site investigation"
                % (resolved.sbc_kpa, resolved.type),
                (),
                clause="IS6403:1981",
                stage="placement.foundations",
            )
        )
    if "founding_depth_m" in resolved.assumed:
        plan.warnings.append(
            make_disclosure(
                "W_ASSUMED_FOUNDING_DEPTH",
                "no founding depth was supplied; %.2f m taken from data/soil_defaults.yaml"
                % resolved.founding_depth_m,
                (),
                clause="IS1904:1986 Cl 5",
                stage="placement.foundations",
            )
        )

    strips = _strips(model, bearing_wall_ids, wall_loads, resolved, params, plan, notes)
    pads = _pads(model, column_ids, column_loads, resolved, params, plan, notes)
    pads = _column_on_strip(strips, pads, resolved, params, plan, notes)
    pads, combined = _combine(pads, params, plan, notes)
    _straps(model, strips, pads, combined, params, plan, notes)
    _disclose_pad_strip_overlaps(strips, pads, combined, plan, notes)

    plan.strips = sorted(strips, key=lambda row: row.id)
    plan.pads = sorted(pads, key=lambda row: row.id)
    plan.combined = sorted(combined, key=lambda row: row.id)
    plan.straps = sorted(plan.straps, key=lambda row: row.id)
    plan.report = {
        "soil": resolved.to_dict(),
        "params": params.to_dict(),
        "counts": {
            "strips": len(plan.strips),
            "pads": len(plan.pads),
            "combined": len(plan.combined),
            "straps": len(plan.straps),
        },
        "notes": sorted(set(notes)),
        "load_contract": (
            "wall_loads[wall_id] = service line load in kN/m at the base of the wall; "
            "column_loads[column_id or stack_id] = service axial load in kN at the base of the stack"
        ),
    }
    if write_back:
        plan.write_back(model)
    return plan


# ---------------------------------------------------------------------------
# 1. strips under the bearing wall runs
# ---------------------------------------------------------------------------


def _strips(
    model: StructuralModel,
    bearing_wall_ids: Sequence[str],
    wall_loads: Dict[str, float],
    soil: Soil,
    params: FoundationParams,
    plan: FoundationPlan,
    notes: List[str],
) -> List[StripFooting]:
    """One mitred strip per run of collinear ground storey bearing walls."""
    chosen = set(bearing_wall_ids)
    walls = {wall.id: wall for wall in model.walls if wall.id in chosen}
    if not walls:
        return []
    ground = min(wall.storey for wall in walls.values())
    stacks = {}  # type: Dict[str, List[str]]
    for stack in model.build_wall_stacks():
        ids = [str(value) for value in stack["walls"].values()]
        for wall_id in ids:
            stacks[wall_id] = ids

    lines = {}  # type: Dict[Tuple[str, int], List[Tuple[float, float, str]]]
    for wall in sorted(walls.values(), key=lambda w: w.id):
        if wall.storey != ground:
            continue
        axis = wall_axis(wall)
        if axis is None:
            continue
        orient, pos, lo, hi = axis
        lines.setdefault((orient, _mm(pos)), []).append((lo, hi, wall.id))

    strips = []  # type: List[StripFooting]
    missing = []  # type: List[str]
    for key in sorted(lines):
        orient, pos_mm = key
        for lo, hi, ids in _merge_runs(lines[key]):
            members = sorted(ids)
            thickness = max(float(walls[wall_id].thickness_m) for wall_id in members)
            keys = list(members)
            for wall_id in members:
                keys.extend(stacks.get(wall_id, []))
            load, found = _lookup_load(wall_loads, sorted(set(keys)))
            if not found:
                missing.extend(members)
            width = max(
                load / float(soil.sbc_kpa),
                float(params.strip_width_t_factor) * thickness,
                float(params.strip_min_width_m),
            )
            width = _round_up(width, params.strip_round_mm)
            rc = width > float(params.rc_strip_t_factor) * thickness + _ETA
            note = (
                "projection past the wall face exceeds the footing thickness, so this is a reinforced "
                "concrete strip, not a plain spread footing"
                if rc
                else "projection is inside the plain spread footing rule; no bending steel required"
            )
            if not found:
                note += "; sized on the geometric minimum because no line load was supplied"
            party = any(_is_foundation_party_boundary(model, walls[wall_id]) for wall_id in members)
            strips.append(
                StripFooting(
                    id=strip_footing_id(members[0]),
                    wall_ids=members,
                    orient=orient,
                    pos_m=pos_mm / 1000.0,
                    s0_m=lo,
                    s1_m=hi,
                    width_m=width,
                    depth_m=float(soil.founding_depth_m),
                    wall_t_m=thickness,
                    rc=rc,
                    eccentric=party,
                    e_m=0.0,
                    w_service_kn_per_m=load,
                    load_source="takedown" if found else "geometric_minimum",
                    note=note + ("; party wall strip is flushed inside the boundary" if party else ""),
                )
            )
    _mitre(strips)
    for strip in strips:
        if not strip.eccentric:
            continue
        wall_pos = strip.pos_m
        inward = _party_inward(model, strip.orient, wall_pos)
        strip.e_m = 0.5 * strip.width_m
        strip.pos_m = wall_pos + inward * strip.e_m
    if missing:
        plan.warnings.append(
            make_disclosure(
                "W_RELEASED_CAP",
                "%d bearing wall(s) reached the foundation layout with no line load, so their strips "
                "are sized on the geometric minimum (2t and %.2f m) rather than on bearing pressure"
                % (len(set(missing)), float(params.strip_min_width_m)),
                sorted(set(missing)),
                clause="IS6403:1981",
                stage="placement.foundations",
            )
        )
        notes.append("some strips carry no takedown load; see the W_RELEASED_CAP entry")
    for strip in strips:
        if strip.eccentric:
            plan.warnings.append(
                make_disclosure(
                    "W_ECCENTRIC_COLUMN",
                    "strip %s runs under a party wall and was flushed inside the boundary; the wall "
                    "resultant is %.3f m off the emitted strip centre and that eccentricity is handed to design"
                    % (strip.id, strip.e_m),
                    [strip.id],
                    clause="IS6403:1981",
                    stage="placement.foundations",
                )
            )
    return strips


def _mitre(strips: Sequence[StripFooting]) -> None:
    """Extend each strip end by half the width of the strip it meets there."""
    for strip in strips:
        extents = [0.0, 0.0]
        for index, station in enumerate((strip.s0_m, strip.s1_m)):
            best = 0.0
            for other in strips:
                if other.id == strip.id or other.orient == strip.orient:
                    continue
                if abs(other.pos_m - station) > GEOM_TOL_M:
                    continue
                if other.s0_m - GEOM_TOL_M <= strip.pos_m <= other.s1_m + GEOM_TOL_M:
                    best = max(best, 0.5 * other.width_m)
            extents[index] = best
        strip.mitre_m = (extents[0], extents[1])


# ---------------------------------------------------------------------------
# 2. pads under the column stacks
# ---------------------------------------------------------------------------


def _pads(
    model: StructuralModel,
    column_ids: Sequence[str],
    column_loads: Dict[str, float],
    soil: Soil,
    params: FoundationParams,
    plan: FoundationPlan,
    notes: List[str],
) -> List[PadFooting]:
    """One square pad per column stack, sized on the service axial load."""
    wanted = set(column_ids)
    groups = {}  # type: Dict[Tuple[int, int], List[Any]]
    for column in model.columns:
        if column.id not in wanted:
            continue
        groups.setdefault((_mm(column.x_m), _mm(column.y_m)), []).append(column)
    pads = []  # type: List[PadFooting]
    missing = []  # type: List[str]
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda col: (col.storey, col.id))
        ids = [col.id for col in members]
        keys = list(ids) + [col.stack_id for col in members if col.stack_id]
        load, found = _lookup_load(column_loads, sorted(set(keys)))
        if not found:
            missing.extend(ids)
        side = max(math.sqrt(load / float(soil.sbc_kpa)) if load > 0.0 else 0.0, float(params.pad_min_m))
        side = _round_up(side, params.pad_snap_mm)
        base = members[0]
        stack = base.stack_id or ("stk-@" + pos_token(base.x_m) + "x" + pos_token(base.y_m))
        note = "square pad, side snapped up to %d mm" % int(round(params.pad_snap_mm))
        if not found:
            note += "; sized on the %.2f m minimum because no axial load was supplied" % float(params.pad_min_m)
        pads.append(
            PadFooting(
                id=footing_id(stack),
                column_ids=sorted(ids),
                x_m=float(base.x_m),
                y_m=float(base.y_m),
                w_m=side,
                h_m=side,
                depth_m=float(soil.founding_depth_m),
                p_service_kn=load,
                load_source="takedown" if found else "geometric_minimum",
                load_x_m=float(base.x_m),
                load_y_m=float(base.y_m),
                note=note,
            )
        )
    if missing:
        plan.warnings.append(
            make_disclosure(
                "W_RELEASED_CAP",
                "%d column(s) reached the foundation layout with no axial load, so their pads are sized "
                "on the %.2f m minimum rather than on bearing pressure"
                % (len(set(missing)), float(params.pad_min_m)),
                sorted(set(missing)),
                clause="IS6403:1981",
                stage="placement.foundations",
            )
        )
        notes.append("some pads carry no takedown load; see the W_RELEASED_CAP entry")
    return pads


# ---------------------------------------------------------------------------
# 3. a column that lands on a strip widens it instead of taking its own pad
# ---------------------------------------------------------------------------


def _column_on_strip(
    strips: Sequence[StripFooting],
    pads: Sequence[PadFooting],
    soil: Soil,
    params: FoundationParams,
    plan: FoundationPlan,
    notes: List[str],
) -> List[PadFooting]:
    """Absorb a pad into real widening geometry and the strip's design demand.

    The point load is conservatively spread over the inscribed pad width plus
    the two taper lengths. The resulting line-load increment is carried on the
    strip record and on the emitted model footing, so deleting the separate pad
    never deletes its axial load from design.
    """
    kept = []  # type: List[PadFooting]
    for pad in sorted(pads, key=lambda row: row.id):
        host = None
        for strip in sorted(strips, key=lambda row: row.id):
            if strip.orient == "h":
                offset = abs(pad.y_m - strip.pos_m)
                station = pad.x_m
            else:
                offset = abs(pad.x_m - strip.pos_m)
                station = pad.y_m
            if offset > float(params.column_on_strip_factor) * strip.width_m + GEOM_TOL_M:
                continue
            lo = strip.s0_m - strip.mitre_m[0]
            hi = strip.s1_m + strip.mitre_m[1]
            if station < lo - GEOM_TOL_M or station > hi + GEOM_TOL_M:
                continue
            host = (strip, station)
            break
        if host is None:
            kept.append(pad)
            continue
        strip, station = host
        lo = strip.s0_m - strip.mitre_m[0]
        hi = strip.s1_m + strip.mitre_m[1]
        half_zone = 0.5 * pad.w_m + float(params.taper_m)
        spread_lo = max(lo, station - half_zone)
        spread_hi = min(hi, station + half_zone)
        effective_length = max(spread_hi - spread_lo, min(pad.w_m, max(hi - lo, _ETA)), _ETA)
        line_load = float(pad.p_service_kn) / effective_length
        widening = Widening(
            column_id=pad.column_ids[0],
            at_m=station,
            width_m=max(strip.width_m, pad.w_m),
            taper_m=float(params.taper_m),
            p_service_kn=pad.p_service_kn,
            s0_m=spread_lo,
            s1_m=spread_hi,
            effective_length_m=effective_length,
            line_load_kn_per_m=line_load,
        )
        strip.widenings.append(widening)
        strip.widenings.sort(key=lambda row: (round(row.at_m, 6), row.column_id))
    for strip in sorted(strips, key=lambda row: row.id):
        if not strip.widenings:
            continue
        boundaries = sorted(
            {value for widening in strip.widenings for value in (widening.s0_m, widening.s1_m)}
        )
        probes = [widening.at_m for widening in strip.widenings]
        probes.extend(
            0.5 * (left + right)
            for left, right in zip(boundaries[:-1], boundaries[1:])
            if right > left + _ETA
        )
        peak = max(
            sum(
                widening.line_load_kn_per_m
                for widening in strip.widenings
                if widening.s0_m - _ETA <= probe <= widening.s1_m + _ETA
            )
            for probe in probes
        )
        strip.w_service_kn_per_m += peak
        pressure_width = _round_up(
            strip.w_service_kn_per_m / max(float(soil.sbc_kpa), _ETA), params.strip_round_mm
        )
        for widening in strip.widenings:
            widening.width_m = max(widening.width_m, pressure_width)
            if widening.width_m > strip.width_m + _ETA:
                strip.note += (
                    "; widened locally to %.3f m under %s, tapered over %.2f m each side"
                    % (widening.width_m, widening.column_id, widening.taper_m)
                )
            strip.note += (
                "; %.3f kN from %s is carried as %.3f kN/m over %.3f m in the strip demand"
                % (
                    widening.p_service_kn,
                    widening.column_id,
                    widening.line_load_kn_per_m,
                    widening.effective_length_m,
                )
            )
            notes.append(
                "column %s lands on strip %s and its %.3f kN service load is carried by a %.3f m "
                "local widening, not a separate pad"
                % (widening.column_id, strip.id, widening.p_service_kn, widening.width_m)
            )
    return kept


# ---------------------------------------------------------------------------
# 4. pads that cannot stand apart become one combined footing
# ---------------------------------------------------------------------------


def _combine(
    pads: Sequence[PadFooting],
    params: FoundationParams,
    plan: FoundationPlan,
    notes: List[str],
) -> Tuple[List[PadFooting], List[CombinedFooting]]:
    """Chain overlapping or near-touching pads left to right into one rectangle."""
    ordered = sorted(pads, key=lambda row: (round(row.x_m, 6), round(row.y_m, 6), row.id))
    parent = list(range(len(ordered)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            if _rects_touch(ordered[i].rect(), ordered[j].rect(), float(params.combine_gap_m)):
                a, b = find(i), find(j)
                if a != b:
                    parent[max(a, b)] = min(a, b)

    groups = {}  # type: Dict[int, List[int]]
    for index in range(len(ordered)):
        groups.setdefault(find(index), []).append(index)

    kept = []  # type: List[PadFooting]
    combined = []  # type: List[CombinedFooting]
    for root in sorted(groups):
        members = [ordered[index] for index in groups[root]]
        if len(members) == 1:
            kept.append(members[0])
            continue
        combined.append(_combine_group(members, params, plan, notes))
    return (kept, combined)


def _combine_group(
    members: Sequence[PadFooting],
    params: FoundationParams,
    plan: FoundationPlan,
    notes: List[str],
    dry_run: bool = False,
) -> CombinedFooting:
    """One rectangle covering the group, extended so its centre sits on the resultant.

    `dry_run` returns the same geometry without touching the ladder or the notes,
    so a caller can test the result against a boundary before committing to it.
    """
    bad = sorted(
        pad.id
        for pad in members
        if pad.load_source == "takedown" and float(pad.p_service_kn) <= _ETA
    )
    if bad:
        raise FoundationLoadError(
            "combined footing cannot include a non-positive compression reaction: "
            + ", ".join(bad),
            bad,
        )
    loaded = [pad for pad in members if float(pad.p_service_kn) > _ETA]
    total = sum(float(pad.p_service_kn) for pad in loaded)
    if total <= _ETA:
        rx = sum(float(pad.load_x_m) for pad in members) / float(len(members))
        ry = sum(float(pad.load_y_m) for pad in members) / float(len(members))
    else:
        rx = sum(float(pad.load_x_m) * float(pad.p_service_kn) for pad in loaded) / total
        ry = sum(float(pad.load_y_m) * float(pad.p_service_kn) for pad in loaded) / total
    rects = [pad.rect() for pad in members]
    x0 = min(rect[0] for rect in rects)
    y0 = min(rect[1] for rect in rects)
    x1 = max(rect[0] + rect[2] for rect in rects)
    y1 = max(rect[1] + rect[3] for rect in rects)
    # extend the far end so the plan centroid lands on the load resultant; the
    # covering rectangle only ever grows, so every member stays inside it
    cx = 0.5 * (x0 + x1)
    if rx > cx:
        x1 += 2.0 * (rx - cx)
    elif rx < cx:
        x0 -= 2.0 * (cx - rx)
    cy = 0.5 * (y0 + y1)
    if ry > cy:
        y1 += 2.0 * (ry - cy)
    elif ry < cy:
        y0 -= 2.0 * (cy - ry)
    width = x1 - x0
    height = y1 - y0
    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    span = max(width, height, _ETA)
    offset = math.hypot(cx - rx, cy - ry) / span
    column_ids = sorted({column_id for pad in members for column_id in pad.column_ids})
    footing = CombinedFooting(
        id="ftg-comb-@" + pos_token(cx) + "x" + pos_token(cy),
        member_ids=sorted(pad.id for pad in members),
        column_ids=column_ids,
        x_m=cx,
        y_m=cy,
        w_m=width,
        h_m=height,
        depth_m=float(members[0].depth_m),
        p_service_kn=total,
        resultant_x_m=rx,
        resultant_y_m=ry,
        centroid_offset_ratio=offset,
        note="%d pads within %d mm of each other were combined; the rectangle was extended so its plan "
        "centroid sits on the load resultant; this rectangle is a cover on the resultant and bearing area "
        "is set by the designer"
        % (len(members), int(round(params.combine_gap_m * 1000.0))),
    )
    if dry_run:
        return footing
    notes.append("combined footing %s carries %s" % (footing.id, ", ".join(footing.member_ids)))
    if offset > float(params.centroid_tol) + _ETA:
        plan.warnings.append(
            make_disclosure(
                "W_ECCENTRIC_COLUMN",
                "combined footing %s has its plan centroid %.1f%% of its length off the load resultant, "
                "past the %.0f%% target; the eccentricity is handed to design, never shrunk away"
                % (footing.id, 100.0 * offset, 100.0 * float(params.centroid_tol)),
                [footing.id],
                clause="IS6403:1981",
                stage="placement.foundations",
            )
        )
    return footing


# ---------------------------------------------------------------------------
# 5. footings that cross a boundary go eccentric and get a strap
# ---------------------------------------------------------------------------


def _disclose_pad_strip_overlaps(
    strips: Sequence[StripFooting],
    pads: Sequence[PadFooting],
    combined: Sequence[CombinedFooting],
    plan: FoundationPlan,
    notes: List[str],
) -> None:
    """Name every final pad/combined rectangle that still shares strip soil."""
    others = list(pads) + list(combined)
    for strip in sorted(strips, key=lambda row: row.id):
        sx, sy, sw, sh = strip.rect()
        for footing in sorted(others, key=lambda row: row.id):
            fx, fy, fw, fh = footing.rect()
            dx = min(sx + sw, fx + fw) - max(sx, fx)
            dy = min(sy + sh, fy + fh) - max(sy, fy)
            if dx <= GEOM_TOL_M or dy <= GEOM_TOL_M:
                continue
            area = dx * dy
            plan.warnings.append(
                make_disclosure(
                    "W_FOOTING_OVERLAP",
                    "footing %s and strip %s overlap by %.3f m2 and share bearing soil; both are "
                    "kept at full size for engineer resolution rather than silently double-crediting the area"
                    % (footing.id, strip.id, area),
                    [footing.id, strip.id],
                    clause="IS6403:1981",
                    stage="placement.foundations",
                )
            )
            notes.append(
                "footing %s overlaps strip %s by %.3f m2; see W_FOOTING_OVERLAP"
                % (footing.id, strip.id, area)
            )


def _crosses(rect: Tuple[float, float, float, float], lines: Sequence[Tuple[str, float, float]]) -> bool:
    """True when a rectangle crosses a one-sided plot or two-sided party line."""
    for orient, pos, inward in lines:
        low = rect[0] if orient == "v" else rect[1]
        high = low + (rect[2] if orient == "v" else rect[3])
        if inward == 0.0 and low < pos - GEOM_TOL_M and high > pos + GEOM_TOL_M:
            return True
        if inward > 0.0 and low < pos - GEOM_TOL_M:
            return True
        if inward < 0.0 and high > pos + GEOM_TOL_M:
            return True
    return False


def _boundary_lines(model: StructuralModel) -> List[Tuple[str, float, float]]:
    """(orientation, position, inward sign) of every line a footing may not cross.

    Party walls carry inward=0: they are two-sided internal lines and only a
    rectangle that straddles them crosses. The owning side is selected later
    from that footing's own load point. The plot line itself is only a boundary
    when the caller supplies it as `model.meta["plot_bounds_m"] = [x0, y0, x1,
    y1]`: the wall network draws the BUILDING outline, and a footing projecting
    into the setback beyond that outline is normal, not a violation.
    """
    lines = []  # type: List[Tuple[str, float, float]]
    plot = model.meta.get("plot_bounds_m")
    if isinstance(plot, (list, tuple)) and len(plot) == 4:
        x0, y0, x1, y1 = (float(value) for value in plot)
        lines.extend([("v", x0, 1.0), ("v", x1, -1.0), ("h", y0, 1.0), ("h", y1, -1.0)])
    for orient, pos in _party_lines(model):
        lines.append((orient, pos, 0.0))
    return sorted(set(lines))


def _flush_centre(
    model: StructuralModel,
    x_m: float,
    y_m: float,
    w_m: float,
    h_m: float,
    load_x_m: float,
    load_y_m: float,
    lines: Sequence[Tuple[str, float, float]],
) -> Tuple[float, float, bool]:
    """Flush one rectangle across each boundary it actually crosses."""
    x = float(x_m)
    y = float(y_m)
    moved = False
    for orient, pos, inward in lines:
        half = 0.5 * (w_m if orient == "v" else h_m)
        centre = x if orient == "v" else y
        low = centre - half
        high = centre + half
        if inward == 0.0:
            crosses = low < pos - GEOM_TOL_M and high > pos + GEOM_TOL_M
            reference = load_x_m if orient == "v" else load_y_m
            side = _party_inward(model, orient, pos, reference)
        else:
            crosses = (inward > 0.0 and low < pos - GEOM_TOL_M) or (
                inward < 0.0 and high > pos + GEOM_TOL_M
            )
            side = inward
        if not crosses:
            continue
        if orient == "v":
            x = pos + side * half
        else:
            y = pos + side * half
        moved = True
    return (x, y, moved)


def _straps(
    model: StructuralModel,
    strips: Sequence[StripFooting],
    pads: List[PadFooting],
    combined: List[CombinedFooting],
    params: FoundationParams,
    plan: FoundationPlan,
    notes: List[str],
) -> None:
    """Flush an offending pad to the boundary, then strap, combine, or warn."""
    lines = _boundary_lines(model)
    if not lines:
        notes.append(
            "no plot or party boundary was supplied, so no footing was treated as eccentric; "
            "set model.meta['plot_bounds_m'] to enable the strap ladder"
        )
        return
    offenders = []  # type: List[PadFooting]
    for pad in sorted(pads, key=lambda row: row.id):
        pad.x_m, pad.y_m, moved = _flush_centre(
            model,
            pad.x_m,
            pad.y_m,
            pad.w_m,
            pad.h_m,
            pad.load_x_m,
            pad.load_y_m,
            lines,
        )
        if not moved:
            continue
        pad.eccentric = True
        pad.e_m = math.hypot(pad.x_m - pad.load_x_m, pad.y_m - pad.load_y_m)
        pad.note += "; shifted flush to the boundary, so the load is %.3f m off the footing centre" % pad.e_m
        offenders.append(pad)

    combined_offenders = []  # type: List[CombinedFooting]
    for footing in sorted(combined, key=lambda row: row.id):
        footing.x_m, footing.y_m, moved = _flush_centre(
            model,
            footing.x_m,
            footing.y_m,
            footing.w_m,
            footing.h_m,
            footing.resultant_x_m,
            footing.resultant_y_m,
            lines,
        )
        if not moved:
            continue
        footing.eccentric = True
        footing.e_m = math.hypot(
            footing.x_m - footing.resultant_x_m, footing.y_m - footing.resultant_y_m
        )
        footing.note += (
            "; shifted flush to the boundary, so the load resultant is %.3f m off the footing centre"
            % footing.e_m
        )
        combined_offenders.append(footing)

    if not offenders and not combined_offenders:
        return

    interior = [pad for pad in pads if not pad.eccentric]
    interior_combined = [footing for footing in combined if not footing.eccentric]
    for pad in offenders:
        target = _nearest(pad, interior, interior_combined)
        if target is not None and target[1] <= float(params.strap_search_m) + _ETA:
            other = target[0]
            mid_x = 0.5 * (pad.x_m + other[1])
            mid_y = 0.5 * (pad.y_m + other[2])
            plan.straps.append(
                StrapBeam(
                    id="ftg-strap-@" + pos_token(mid_x) + "x" + pos_token(mid_y),
                    from_id=pad.id,
                    to_id=other[0],
                    a=(pad.x_m, pad.y_m),
                    b=(other[1], other[2]),
                    e_m=pad.e_m,
                    note="eccentric boundary footing tied back to the nearest interior footing within "
                    "%.1f m; the strap beam carries the couple" % float(params.strap_search_m),
                )
            )
            notes.append("strap beam from %s to %s" % (pad.id, other[0]))
            continue
        partner = _nearest_pad(pad, interior)
        if partner is not None:
            trial = _combine_group([pad, partner], params, plan, notes, dry_run=True)
            if not _crosses(trial.rect(), lines):
                combined.append(_combine_group([pad, partner], params, plan, notes))
                if pad in pads:
                    pads.remove(pad)
                if partner in pads:
                    pads.remove(partner)
                if partner in interior:
                    interior.remove(partner)
                notes.append(
                    "no interior footing within %.1f m of %s, so it was combined with %s instead"
                    % (float(params.strap_search_m), pad.id, partner.id)
                )
                continue
            notes.append(
                "combining %s with %s would push the rectangle back across the boundary, so the "
                "eccentricity is left for design instead" % (pad.id, partner.id)
            )
        plan.warnings.append(
            make_disclosure(
                "W_ECCENTRIC_COLUMN",
                "footing %s sits on a boundary with its load %.3f m off centre and there is no interior "
                "footing to strap or combine it with; the eccentricity is left for design to resolve and "
                "the footing is not shrunk to hide it" % (pad.id, pad.e_m),
                [pad.id],
                clause="IS6403:1981",
                stage="placement.foundations",
            )
        )
        notes.append("eccentric footing %s could not be strapped or combined" % pad.id)

    for footing in combined_offenders:
        target = _nearest_point(
            footing.id, footing.x_m, footing.y_m, interior, interior_combined
        )
        if target is not None and target[1] <= float(params.strap_search_m) + _ETA:
            other = target[0]
            mid_x = 0.5 * (footing.x_m + other[1])
            mid_y = 0.5 * (footing.y_m + other[2])
            plan.straps.append(
                StrapBeam(
                    id="ftg-strap-@" + pos_token(mid_x) + "x" + pos_token(mid_y),
                    from_id=footing.id,
                    to_id=other[0],
                    a=(footing.x_m, footing.y_m),
                    b=(other[1], other[2]),
                    e_m=footing.e_m,
                    note="eccentric boundary combined footing tied back to the nearest interior footing "
                    "within %.1f m; the strap beam carries the couple"
                    % float(params.strap_search_m),
                )
            )
            notes.append("strap beam from %s to %s" % (footing.id, other[0]))
            plan.warnings.append(
                make_disclosure(
                    "W_ECCENTRIC_COLUMN",
                    "combined footing %s was flushed inside the boundary and a strap was laid out to %s, "
                    "but the automatic combined-footing designer does not consume that strap; engineer "
                    "design of the %.3f m eccentricity and strap is required"
                    % (footing.id, other[0], footing.e_m),
                    [footing.id, other[0]],
                    clause="IS6403:1981",
                    stage="placement.foundations",
                )
            )
            continue
        plan.warnings.append(
            make_disclosure(
                "W_ECCENTRIC_COLUMN",
                "combined footing %s was flushed inside the boundary with its load resultant %.3f m "
                "off centre, but there is no separate interior footing within %.1f m to strap it to; "
                "automatic design does not resolve this eccentric condition, so engineer review is required"
                % (footing.id, footing.e_m, float(params.strap_search_m)),
                [footing.id],
                clause="IS6403:1981",
                stage="placement.foundations",
            )
        )
        notes.append("eccentric combined footing %s could not be strapped" % footing.id)


def _nearest(
    pad: PadFooting, interior: Sequence[PadFooting], combined: Sequence[CombinedFooting]
) -> Optional[Tuple[Tuple[str, float, float], float]]:
    """Nearest interior pad or combined footing to this one, by centre distance."""
    return _nearest_point(pad.id, pad.x_m, pad.y_m, interior, combined)


def _nearest_point(
    element_id: str,
    x_m: float,
    y_m: float,
    interior: Sequence[PadFooting],
    combined: Sequence[CombinedFooting],
) -> Optional[Tuple[Tuple[str, float, float], float]]:
    """Nearest interior pad or combined footing to an arbitrary centre."""
    best = None
    for other in sorted(interior, key=lambda row: row.id):
        if other.id == element_id:
            continue
        distance = math.hypot(other.x_m - x_m, other.y_m - y_m)
        if best is None or distance < best[1] - _ETA:
            best = ((other.id, other.x_m, other.y_m), distance)
    for other in sorted(combined, key=lambda row: row.id):
        if other.id == element_id:
            continue
        distance = math.hypot(other.x_m - x_m, other.y_m - y_m)
        if best is None or distance < best[1] - _ETA:
            best = ((other.id, other.x_m, other.y_m), distance)
    return best


def _nearest_pad(pad: PadFooting, interior: Sequence[PadFooting]) -> Optional[PadFooting]:
    best = None
    best_distance = None
    for other in sorted(interior, key=lambda row: row.id):
        if other.id == pad.id:
            continue
        distance = math.hypot(other.x_m - pad.x_m, other.y_m - pad.y_m)
        if best_distance is None or distance < best_distance - _ETA:
            best = other
            best_distance = distance
    return best
