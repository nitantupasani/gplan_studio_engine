"""Shared load-model contract for the loads and analysis submodules.

This package owns the serialized shapes that ride on `StructuralModel.loads`
(finding 14): the unfactored load cases (`LoadCase` of `AreaLoad` / `LineLoad` /
`PointLoad` / `StoreyForce`), the factored combinations (`Combo`) and the
container (`LoadModel`).  Everything here is a plain dataclass with a
`to_dict`/`from_dict` pair so the whole model is JSON-serializable (Celery
rule: no live objects on the wire).

Units are SI throughout: kPa (kN/m2) for area loads, kN/m for line loads, kN
for point and storey forces, metres for positions.  Line loads are parametric:
`a` and `b` are fractions 0..1 along the target element measured from the
element's own `a` endpoint, and the intensity ramps linearly `w1 -> w2` over
that stretch, which represents every triangle, trapezoid and uniform strip the
takedown produces exactly.

Case names are the roster the combination generator expands: "DL", "LL",
"LLR", then the lateral names "EQX+", "EQX-", "EQY+", "EQY-", "WX+", "WX-",
"WY+", "WY-" contributed by the seismic and wind builders.  This module only
defines the shapes and the name vocabulary; `dead.py` / `live.py` build the
gravity cases and `combos.py` expands whatever roster is present.

Storey convention (critic resolution 2): storey 0 is the ground storey, floor
level i is the top of storey i, and every height derives from
`Storey.bottom_z_m`, never from a storey index.

`storey_weight_rows(model, loadmodel)` tallies the seismic storey weights
straight off the model and the built gravity cases, in exactly the shape
`loads/seismic.build_seismic` documents.  It is the intended input to
`build_seismic`: weighing the storeys does NOT require a gravity takedown pass,
and a caller that ran one anyway can keep using
`analysis.takedown.TakedownResult.storey_ledger`, which this reproduces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..model import Beam, Disclosure, DisclosureLog, StructuralModel, polygon_rect

__all__ = [
    "CaseKind",
    "AreaLoad",
    "LineLoad",
    "PointLoad",
    "StoreyForce",
    "LoadCase",
    "Combo",
    "LoadModel",
    "CASE_DL",
    "CASE_LL",
    "CASE_LLR",
    "LATERAL_CASE_ROSTER",
    "case_kind_for_name",
    "storey_weight_rows",
]

# Canonical case names.
CASE_DL = "DL"
CASE_LL = "LL"
CASE_LLR = "LLR"

#: Deterministic expansion order for lateral cases (combos.py iterates this).
LATERAL_CASE_ROSTER = ("EQX+", "EQX-", "EQY+", "EQY-", "WX+", "WX-", "WY+", "WY-")

_DP = 6  # serialization rounding; api.py applies the coarser response-edge rounding


def _r(value: float) -> float:
    """Round for the wire and normalize -0.0 so serialization is byte-stable."""
    return round(float(value), _DP) + 0.0


class CaseKind(str, Enum):
    DEAD = "dead"
    LIVE = "live"
    ROOF_LIVE = "roof_live"
    WIND = "wind"
    SEISMIC = "seismic"


def case_kind_for_name(name: str) -> CaseKind:
    """CaseKind for a canonical case name; raises on an unknown name."""
    text = str(name)
    if text == CASE_DL:
        return CaseKind.DEAD
    if text == CASE_LL:
        return CaseKind.LIVE
    if text == CASE_LLR:
        return CaseKind.ROOF_LIVE
    if text.startswith("EQ"):
        return CaseKind.SEISMIC
    if text.startswith("W") and text != CASE_LL:
        return CaseKind.WIND
    raise ValueError("unknown load case name: " + repr(text))


@dataclass(frozen=True)
class AreaLoad:
    """A uniform pressure on one slab panel, kPa positive downward."""

    panel_id: str
    q_kpa: float
    kind: CaseKind
    source: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "q_kpa": _r(self.q_kpa),
            "kind": self.kind.value,
            "source": self.source,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AreaLoad":
        return AreaLoad(
            panel_id=d["panel_id"],
            q_kpa=float(d["q_kpa"]),
            kind=CaseKind(d["kind"]),
            source=d.get("source", ""),
            note=d.get("note", ""),
        )


@dataclass(frozen=True)
class LineLoad:
    """A linearly varying line load on one element, kN/m positive downward.

    `a` and `b` are parametric fractions 0..1 along the element from its own
    `a` endpoint; intensity is `w1_kn_m` at `a` ramping linearly to `w2_kn_m`
    at `b`.  A uniform load has `w1 == w2`; a triangle over a full span is two
    of these back to back.
    """

    element_id: str
    w1_kn_m: float
    w2_kn_m: float
    a: float
    b: float
    kind: CaseKind
    source: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "w1_kn_m": _r(self.w1_kn_m),
            "w2_kn_m": _r(self.w2_kn_m),
            "a": _r(self.a),
            "b": _r(self.b),
            "kind": self.kind.value,
            "source": self.source,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LineLoad":
        return LineLoad(
            element_id=d["element_id"],
            w1_kn_m=float(d["w1_kn_m"]),
            w2_kn_m=float(d["w2_kn_m"]),
            a=float(d["a"]),
            b=float(d["b"]),
            kind=CaseKind(d["kind"]),
            source=d.get("source", ""),
            note=d.get("note", ""),
        )


@dataclass(frozen=True)
class PointLoad:
    """A concentrated load on one node-bearing element (a column id in v1)."""

    node_id: str
    p_kn: float
    kind: CaseKind
    source: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "p_kn": _r(self.p_kn),
            "kind": self.kind.value,
            "source": self.source,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PointLoad":
        return PointLoad(
            node_id=d["node_id"],
            p_kn=float(d["p_kn"]),
            kind=CaseKind(d["kind"]),
            source=d.get("source", ""),
            note=d.get("note", ""),
        )


@dataclass(frozen=True)
class StoreyForce:
    """A lateral force applied at one floor level (seismic / wind cases).

    `storey` is the floor level index (top of that storey's structure) and
    `z_m` its height above the model base, from `Storey.bottom_z_m`.
    """

    storey: int
    fx_kn: float
    fy_kn: float
    z_m: float
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storey": int(self.storey),
            "fx_kn": _r(self.fx_kn),
            "fy_kn": _r(self.fy_kn),
            "z_m": _r(self.z_m),
            "source": self.source,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StoreyForce":
        return StoreyForce(
            storey=int(d["storey"]),
            fx_kn=float(d["fx_kn"]),
            fy_kn=float(d["fy_kn"]),
            z_m=float(d["z_m"]),
            source=d.get("source", ""),
        )


@dataclass
class LoadCase:
    """One unfactored load case; cases stay unfactored until combine()."""

    name: str
    kind: CaseKind
    area: List[AreaLoad] = field(default_factory=list)
    line: List[LineLoad] = field(default_factory=list)
    point: List[PointLoad] = field(default_factory=list)
    storey: List[StoreyForce] = field(default_factory=list)

    def sorted_area(self) -> List[AreaLoad]:
        return sorted(self.area, key=lambda x: (x.panel_id, x.source, x.q_kpa))

    def sorted_line(self) -> List[LineLoad]:
        return sorted(self.line, key=lambda x: (x.element_id, x.a, x.b, x.source, x.w1_kn_m))

    def sorted_point(self) -> List[PointLoad]:
        return sorted(self.point, key=lambda x: (x.node_id, x.source, x.p_kn))

    def sorted_storey(self) -> List[StoreyForce]:
        return sorted(self.storey, key=lambda x: (x.storey, x.source))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "area": [x.to_dict() for x in self.sorted_area()],
            "line": [x.to_dict() for x in self.sorted_line()],
            "point": [x.to_dict() for x in self.sorted_point()],
            "storey": [x.to_dict() for x in self.sorted_storey()],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LoadCase":
        return LoadCase(
            name=d["name"],
            kind=CaseKind(d["kind"]),
            area=[AreaLoad.from_dict(x) for x in d.get("area", [])],
            line=[LineLoad.from_dict(x) for x in d.get("line", [])],
            point=[PointLoad.from_dict(x) for x in d.get("point", [])],
            storey=[StoreyForce.from_dict(x) for x in d.get("storey", [])],
        )


@dataclass(frozen=True)
class Combo:
    """One factored combination; `factors` maps case name -> factor.

    `allowable_stress_factor` is the permissible-stress overstress multiplier
    the masonry design applies on WS combinations that include a lateral case
    (1.25 per IS 1905 practice); it stays 1.0 on every other combination.
    """

    id: str
    name: str
    kind: str  # "ULS" | "SLS" | "WS"
    factors: Tuple[Tuple[str, float], ...]
    source: str
    allowable_stress_factor: float = 1.0

    def factor_map(self) -> Dict[str, float]:
        return dict(self.factors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "factors": {case: _r(factor) for case, factor in sorted(self.factors)},
            "source": self.source,
            "allowable_stress_factor": _r(self.allowable_stress_factor),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Combo":
        return Combo(
            id=d["id"],
            name=d["name"],
            kind=d["kind"],
            factors=tuple(sorted((str(k), float(v)) for k, v in d.get("factors", {}).items())),
            source=d.get("source", ""),
            allowable_stress_factor=float(d.get("allowable_stress_factor", 1.0)),
        )


@dataclass
class LoadModel:
    """Cases + combos + trace + disclosures; `to_dict()` rides on model.loads.

    `trace` holds `codes.trace.TraceEntry.to_dict()` records collected by the
    orchestrator while the builders ran; `log` holds the disclosures raised by
    the builders (they also land on the StructuralModel ladder at build time,
    this copy keeps the serialized LoadModel self-contained).
    """

    cases: Dict[str, LoadCase] = field(default_factory=dict)
    combos: List[Combo] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    log: DisclosureLog = field(default_factory=DisclosureLog)

    def case_names(self) -> List[str]:
        return sorted(self.cases)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cases": {name: self.cases[name].to_dict() for name in sorted(self.cases)},
            "combos": [combo.to_dict() for combo in self.combos],
            "trace": [dict(entry) for entry in self.trace],
            "disclosures": self.log.to_dict(),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LoadModel":
        log = DisclosureLog()
        for entry in (d.get("disclosures") or {}).get("disclosures", []):
            log.append(Disclosure.from_dict(entry))
        return LoadModel(
            cases={name: LoadCase.from_dict(case) for name, case in (d.get("cases") or {}).items()},
            combos=[Combo.from_dict(c) for c in d.get("combos", [])],
            trace=[dict(entry) for entry in d.get("trace", [])],
            log=log,
        )


# ---------------------------------------------------------------------------
# seismic storey weights, without a takedown pass
# ---------------------------------------------------------------------------

#: The gravity cases a storey weight is tallied from. LLR is walked for the
#: same element checks but contributes nothing: IS 1893 Cl 7.3.2 keeps the roof
#: imposed load out of the seismic weight.
_WEIGHED_CASES = (CASE_DL, CASE_LL, CASE_LLR)


def _line_total_kn(load: "LineLoad", element: Any) -> float:
    """Total load under one parametric line load, kN."""
    length = element.span_m() if isinstance(element, Beam) else element.length_m()
    return 0.5 * (load.w1_kn_m + load.w2_kn_m) * (load.b - load.a) * length


def storey_weight_rows(model: StructuralModel, loadmodel: "LoadModel") -> List[Dict[str, Any]]:
    """Seismic storey weights per floor level, the input `build_seismic` documents.

    Rows are `{"storey", "w_dl_kn", "w_ll_kn", "ll_basis_kpa", "z_top_m",
    "roof"}`, sorted by level; `roof` marks the top level so Cl 7.3.2 can drop
    its imposed load, and `ll_basis_kpa` is the largest panel imposed pressure
    at the level (the Table 10 fraction selector), None when the level carries
    no imposed load at all.

    The tally is the seismic-weight convention of the load takedown, computed
    here directly so that WEIGHING the building costs nothing beyond the gravity
    cases already built (before this existed, `build_seismic` could only be fed
    from `TakedownResult.storey_ledger`, so an orchestrator had to run the whole
    takedown once to weigh and once again over the full combination roster):

      * slab area loads land wholly at the panel's floor level;
      * beam line loads land wholly at the beam's floor level;
      * wall line loads split half to the level the wall stands under and half
        to the level it stands on, the ground half going to the foundation and
        not to any level;
      * column point loads land at the column's floor level;
      * column self weight, `25 b D h` over the floor to floor height, splits
        half up and half down the same way (it is not in the DL case: nothing
        but this and the takedown build it).

    Raises ValueError when a load names an element the model does not carry:
    the two must describe the same building or the weight is wrong, and a
    silently skipped load would under-weigh the storey.
    """
    slabs = {s.id: s for s in model.slabs}
    beams = {b.id: b for b in model.beams}
    walls = {w.id: w for w in model.walls}
    columns = {c.id: c for c in model.columns}

    panel_area = {}  # type: Dict[str, float]
    for slab in model.slabs:
        rect = polygon_rect(slab.polygon)
        panel_area[slab.id] = rect[2] * rect[3]

    levels = sorted(
        set(s.index for s in model.storeys)
        | set(s.storey for s in model.slabs)
        | set(b.storey for b in model.beams)
        | set(w.storey for w in model.walls)
        | set(c.storey for c in model.columns)
    )
    z_top = {}  # type: Dict[int, float]
    height = {}  # type: Dict[int, float]
    for storey in model.storeys:
        z_top[storey.index] = storey.bottom_z_m + storey.height_m
        height[storey.index] = storey.height_m

    tally = {}  # type: Dict[int, Dict[str, float]]

    def row_for(level: int) -> Dict[str, float]:
        if level not in tally:
            tally[level] = {"w_dl_kn": 0.0, "w_ll_kn": 0.0, "ll_basis_kpa": 0.0}
        return tally[level]

    def add(level: int, case: str, kn: float) -> None:
        if level < 0:
            return
        row = row_for(level)
        if case == CASE_DL:
            row["w_dl_kn"] += kn
        elif case == CASE_LL:
            row["w_ll_kn"] += kn

    for level in levels:
        row_for(level)

    panel_q = {}  # type: Dict[str, float]
    for case in _WEIGHED_CASES:
        load_case = loadmodel.cases.get(case)
        if load_case is None:
            continue
        for area in load_case.area:
            slab = slabs.get(area.panel_id)
            if slab is None:
                raise ValueError("area load on unknown panel " + str(area.panel_id))
            add(slab.storey, case, area.q_kpa * panel_area[area.panel_id])
            if case == CASE_LL:
                panel_q[area.panel_id] = panel_q.get(area.panel_id, 0.0) + area.q_kpa
                row = row_for(slab.storey)
                if panel_q[area.panel_id] > row["ll_basis_kpa"]:
                    row["ll_basis_kpa"] = panel_q[area.panel_id]
        for line in load_case.line:
            if line.element_id in beams:
                beam = beams[line.element_id]
                add(beam.storey, case, _line_total_kn(line, beam))
            elif line.element_id in walls:
                wall = walls[line.element_id]
                total = _line_total_kn(line, wall)
                add(wall.storey, case, 0.5 * total)
                add(wall.storey - 1, case, 0.5 * total)
            else:
                raise ValueError("line load on unknown element " + str(line.element_id))
        for point in load_case.point:
            column = columns.get(point.node_id)
            if column is None:
                raise ValueError("point load on unknown node " + str(point.node_id))
            add(column.storey, case, point.p_kn)

    from ..codes import is875  # local: keeps the shared shapes import-light

    gamma_rcc = is875.part1_unit_weight("rcc")
    for level in sorted(levels, reverse=True):
        for column in sorted(model.columns_on(level), key=lambda c: c.id):
            self_kn = gamma_rcc * column.width_m * column.depth_m * height.get(level, 3.0)
            add(level, CASE_DL, 0.5 * self_kn)
            add(level - 1, CASE_DL, 0.5 * self_kn)

    if not tally:
        return []
    top = max(tally)
    rows = []  # type: List[Dict[str, Any]]
    for level in sorted(tally):
        row = tally[level]
        basis = row["ll_basis_kpa"]  # type: Optional[float]
        rows.append(
            {
                "storey": int(level),
                "w_dl_kn": _r(row["w_dl_kn"]),
                "w_ll_kn": _r(row["w_ll_kn"]),
                "ll_basis_kpa": None if not basis else _r(basis),
                "z_top_m": _r(z_top.get(level, 0.0)),
                "roof": int(level) == int(top),
            }
        )
    return rows
