"""Rigid-diaphragm distribution of storey shears: the v1 lateral analysis.

Finding 21 makes this module the single source of masonry pier stiffness and of
the lateral shear distribution; nothing else in the package models either.

The idealization, stated once: each floor is a rigid diaphragm in its own
plane, every vertical element is a fixed-fixed shear element between floors,
only elements parallel to the direction shaken participate, and the torsional
share is ADDITIVE ONLY, so no element is ever relieved by torsion. That last
one is deliberately conservative: the sum of the element shears exceeds the
storey shear.

    column k = 12 Ec Ic / h^3                  Ec = 5000 sqrt(fck), IS 456 6.2.3.1
    pier   k = Em t / ((h/L)^3 + 3 (h/L))      Em = 550 fm, IS 1893 7.10.2
           k = Em t / (4 (h/L)^3 + 3 (h/L))    cantilever variant, ctx flag
    strut  k = Em t w_ds cos^2(theta) / L_ds   w_ds = 0.175 alpha_h^-0.4 L_ds,
                                               IS 1893 7.9.2, option flag only

Which walls are credited, stated once: a wall enters the lateral system only
when it is declared bearing (`wall.bearing is True`) or is RC. Everything else
is URM infill or an undeclared partition and is EXCLUDED from the lateral
stiffness by default, with `W_INFILL_EXCLUDED` on the ladder naming the walls.
The reason for the default: crediting infill panels as full shear piers
overstates the storey stiffness by an order of magnitude, which understates
the period and the drift (so the drift check cannot fire), and it places the
centre of rigidity by the partition layout instead of the frame, so the
torsion verdicts come out of the wrong geometry. The bare-frame default errs
soft instead, which is the conservative side for drift, and every credited
element is a declared structural element. The IS 1893 Cl 7.9.2 equivalent
diagonal strut idealization is available as
`LateralContext(infill_stiffness="strut")` and is disclosed as
`N_INFILL_STRUT` when used; `W_INFILL_EXCLUDED` is an engineer-review trigger
(report.REVIEW_TRIGGER_CODES), so the excluded-infill idealization always
reaches a human.

Wave-3 boundary. This module imports nothing from `loads` or `analysis`; the
storey shears arrive as a plain documented dict and the seismic or wind report
that produced them stays with its own producer.

    storey_shears  {"x": {0: 320.0, 1: 309.3}, "y": {...}}   magnitudes in kN

`storey_shears_from_forces` turns the plain storey-force dicts that
`loads/seismic.py` and `loads/wind.py` emit into exactly that shape, so the
wave-5 orchestrator has no arithmetic of its own to do.

Units are SI: metres, kN, kN/m for stiffness, kN m for moment and for J.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..codes import is456, is1893
from ..codes.trace import trace_into
from ..model import (
    DisclosureLog,
    Material,
    StructuralModel,
    WallRole,
    opening_assumed,
    opening_span,
    polygon_rect,
)

STAGE = "analysis.diaphragm"
EQ_CODE = "IS 1893-1:2016"

# IS 1893 (Part 1) : 2016 Cl 7.10.2: modulus of elasticity of masonry.
EM_OVER_FM = 550.0

# 1 MPa = 1000 kN/m2.
MPA_TO_KN_M2 = 1000.0

# Cl 6.4.3 cracked-section properties, available as a context flag for drift
# realism. Ratios are unaffected when the modifier is uniform.
CRACKED_COLUMN_FACTOR = 0.7
CRACKED_BEAM_FACTOR = 0.35

# A solid segment shorter than this is not a pier; it is a nib.
MIN_PIER_LENGTH_M = 0.15

# Cl 7.8.2 torsional-irregularity proxy carried by the layout scoring.
TORSION_GATE_FRACTION = 0.05

_TINY = 1e-12
_DIRECTIONS = ("x", "y")


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


#: The two supported idealizations for walls that are not declared bearing and
#: are not RC (URM infill and undeclared partitions). "exclude" is the default
#: and drops them from the lateral stiffness, disclosed; "strut" credits them
#: as IS 1893 Cl 7.9.2 equivalent diagonal struts, disclosed. There is no
#: option to credit infill as a full shear pier: that was the defect.
INFILL_MODES = ("exclude", "strut")


@dataclass(frozen=True)
class LateralContext:
    """Material and modelling flags for the distribution.

    `plan_dims_m` overrides the per-storey plan bbox that supplies `bi` in the
    Cl 7.8.2 design eccentricity and the 5 percent torsion gate.

    `infill_stiffness` picks the idealization for non-bearing, non-RC walls:
    "exclude" (default, see the module docstring for why) or "strut" (the
    Cl 7.9.2 equivalent diagonal strut).
    """

    fck_mpa: float = 25.0
    fm_mpa: float = 5.0
    cracked_sections: bool = False
    cantilever_piers: bool = False
    min_wall_thickness_m: float = 0.100
    opening_knockdown: float = 0.8
    plan_dims_m: Optional[Tuple[float, float]] = None
    infill_stiffness: str = "exclude"

    def __post_init__(self) -> None:
        if self.infill_stiffness not in INFILL_MODES:
            raise ValueError(
                "infill_stiffness must be one of "
                + repr(INFILL_MODES)
                + ", got "
                + repr(self.infill_stiffness)
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fck_mpa": float(self.fck_mpa),
            "fm_mpa": float(self.fm_mpa),
            "cracked_sections": bool(self.cracked_sections),
            "cantilever_piers": bool(self.cantilever_piers),
            "min_wall_thickness_m": float(self.min_wall_thickness_m),
            "opening_knockdown": float(self.opening_knockdown),
            "plan_dims_m": None if self.plan_dims_m is None else [float(v) for v in self.plan_dims_m],
            "infill_stiffness": str(self.infill_stiffness),
        }


# ---------------------------------------------------------------------------
# stiffness primitives (finding 21: defined once, here)
# ---------------------------------------------------------------------------


def column_stiffness(e_mpa: float, i_m4: float, h_m: float, modifier: float = 1.0) -> float:
    """k = 12 E I / h^3 in kN/m, the fixed-fixed portal column.

    `e_mpa` is the modulus in MPa, `i_m4` the gross second moment about the
    axis that bends for this direction, `modifier` the cracked-section factor.
    """
    if h_m <= 0.0:
        raise ValueError("column height must be positive, got " + repr(h_m))
    return 12.0 * (float(e_mpa) * MPA_TO_KN_M2) * float(i_m4) * float(modifier) / (float(h_m) ** 3)


def pier_stiffness(e_mpa: float, t_m: float, h_m: float, l_m: float, cantilever: bool = False) -> float:
    """k = E t / ((h/L)^3 + 3 (h/L)) in kN/m, the fixed-fixed masonry pier.

    The cantilever variant, for a pier free to rotate at its top, replaces the
    cubic term with 4 (h/L)^3. Both are the classic shear-plus-flexure pier
    expressions with Poisson effects folded into the 3 (h/L) shear term.

    Spot value: h/L = 1, t = 0.23 m, fm = 5 MPa gives Em = 2750 MPa and
    k = 2750 * 1000 * 0.23 / (1 + 3) = 158125 kN/m.
    """
    if l_m <= 0.0:
        raise ValueError("pier length must be positive, got " + repr(l_m))
    if h_m <= 0.0:
        raise ValueError("pier height must be positive, got " + repr(h_m))
    ratio = float(h_m) / float(l_m)
    cubic = 4.0 * ratio ** 3 if cantilever else ratio ** 3
    return (float(e_mpa) * MPA_TO_KN_M2) * float(t_m) / (cubic + 3.0 * ratio)


def masonry_modulus(fm_mpa: float) -> float:
    """Em = 550 fm in MPa (IS 1893 Cl 7.10.2)."""
    return EM_OVER_FM * float(fm_mpa)


# IS 1893 (Part 1) : 2016 Cl 7.9.2.2: equivalent diagonal strut width,
# w_ds = 0.175 alpha_h^-0.4 L_ds. Printed formula constants, not tabulated.
STRUT_WIDTH_COEFF = 0.175
STRUT_WIDTH_EXPONENT = -0.4


def strut_stiffness(
    em_mpa: float, t_m: float, h_m: float, l_m: float, ef_mpa: float, ic_m4: float
) -> Dict[str, float]:
    """The Cl 7.9.2 equivalent diagonal strut of a URM infill panel, as a record.

    The panel is replaced by a pin-ended diagonal strut of width
    w_ds = 0.175 alpha_h^-0.4 L_ds (IS 1893 Cl 7.9.2.2), where

        alpha_h = h ((Em t sin 2 theta) / (4 Ef Ic h))^(1/4)

    with theta the angle of the diagonal, L_ds its length, Ef and Ic the
    modulus and sway-axis second moment of the ADJOINING columns. The lateral
    stiffness is the horizontal component of the strut's axial stiffness:

        k = (Em t w_ds / L_ds) cos^2 theta        in kN/m

    Returns the full record, not just k, because the wire discloses the strut
    geometry: {"k_kn_m", "w_ds_m", "l_ds_m", "theta_rad", "alpha_h"}.

    Spot value: Em = 2750 MPa, t = 0.23 m, h = 3 m, L = 4 m, Ef = 25000 MPa,
    Ic = 0.3^4 / 12. The 3-4-5 diagonal gives sin 2 theta = 0.96 and
    cos^2 theta = 0.64 exactly; alpha_h = 3.9477, w_ds = 0.5053 m and
    k = 40904 kN/m, several times softer than the same panel as a shear pier,
    which is the point of the idealization.
    """
    if l_m <= 0.0:
        raise ValueError("infill panel length must be positive, got " + repr(l_m))
    if h_m <= 0.0:
        raise ValueError("infill panel height must be positive, got " + repr(h_m))
    if ic_m4 <= 0.0:
        raise ValueError("adjoining column Ic must be positive, got " + repr(ic_m4))
    if ef_mpa <= 0.0 or em_mpa <= 0.0:
        raise ValueError("moduli must be positive, got Em " + repr(em_mpa) + ", Ef " + repr(ef_mpa))
    em = float(em_mpa) * MPA_TO_KN_M2
    ef = float(ef_mpa) * MPA_TO_KN_M2
    height = float(h_m)
    length = float(l_m)
    theta = math.atan2(height, length)
    l_ds = math.hypot(height, length)
    alpha_h = height * (
        (em * float(t_m) * math.sin(2.0 * theta)) / (4.0 * ef * float(ic_m4) * height)
    ) ** 0.25
    w_ds = STRUT_WIDTH_COEFF * alpha_h ** STRUT_WIDTH_EXPONENT * l_ds
    k = (em * float(t_m) * w_ds / l_ds) * math.cos(theta) ** 2
    return {
        "k_kn_m": k,
        "w_ds_m": w_ds,
        "l_ds_m": l_ds,
        "theta_rad": theta,
        "alpha_h": alpha_h,
    }


# ---------------------------------------------------------------------------
# storey shears from the plain storey-force dicts
# ---------------------------------------------------------------------------


def storey_shears_from_forces(storey_forces: Sequence[Dict[str, Any]]) -> Dict[str, Dict[int, float]]:
    """Accumulate level forces top-down into storey shear magnitudes.

    Level i is the top of storey i (0-based), so the shear carried by storey i
    is the sum of the forces at every level i and above. Signs are dropped: the
    plus and minus cases of a direction give the same distribution and the sign
    lives in the case name.

    A direction the case does not load comes back empty rather than as a column
    of zeros, so a storey is never asked to distribute a shear it does not have.
    """
    fx = {}  # type: Dict[int, float]
    fy = {}  # type: Dict[int, float]
    for force in storey_forces:
        storey = int(force["storey"])
        fx[storey] = fx.get(storey, 0.0) + float(force.get("fx_kn", 0.0) or 0.0)
        fy[storey] = fy.get(storey, 0.0) + float(force.get("fy_kn", 0.0) or 0.0)
    out = {"x": {}, "y": {}}  # type: Dict[str, Dict[int, float]]
    for direction, table in (("x", fx), ("y", fy)):
        running = 0.0
        for storey in sorted(table, reverse=True):
            running += table[storey]
            if abs(running) > _TINY:
                out[direction][storey] = abs(running)
    return out


def storey_shears_from_case(case: Dict[str, Any]) -> Dict[str, Dict[int, float]]:
    """`storey_shears_from_forces` on one lateral case dict."""
    return storey_shears_from_forces(case.get("storey_forces", []))


# ---------------------------------------------------------------------------
# result shapes
# ---------------------------------------------------------------------------


@dataclass
class ElementShare:
    """One vertical element's share of one storey shear in one direction."""

    element_id: str
    element_type: str  # column | wall
    storey: int
    direction: str
    k_kn_m: float
    x_m: float
    y_m: float
    d_m: float  # signed offset from the centre of rigidity, perpendicular to the force
    v_direct_kn: float
    v_torsion_kn: float
    v_kn: float
    m_top_knm: float = 0.0
    m_bot_knm: float = 0.0
    length_m: Optional[float] = None
    v_per_m_kn_m: Optional[float] = None
    m_base_knm: Optional[float] = None
    stack_id: Optional[str] = None
    stiffness_source: str = ""
    piers: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type,
            "storey": int(self.storey),
            "direction": self.direction,
            "k_kn_m": self.k_kn_m,
            "x_m": self.x_m,
            "y_m": self.y_m,
            "d_m": self.d_m,
            "v_direct_kn": self.v_direct_kn,
            "v_torsion_kn": self.v_torsion_kn,
            "v_kn": self.v_kn,
            "m_top_knm": self.m_top_knm,
            "m_bot_knm": self.m_bot_knm,
            "length_m": self.length_m,
            "v_per_m_kn_m": self.v_per_m_kn_m,
            "m_base_knm": self.m_base_knm,
            "stack_id": self.stack_id,
            "stiffness_source": self.stiffness_source,
            "piers": [dict(pier) for pier in self.piers],
        }


@dataclass
class StoreyLateral:
    """One storey, one direction: rigidity centre, eccentricity, drift, shares."""

    storey: int
    direction: str
    height_m: float
    shear_kn: float
    sum_k_kn_m: float
    cr_x_m: float
    cr_y_m: float
    cm_x_m: float
    cm_y_m: float
    esi_m: float
    bi_m: float
    ed_amplified_m: float
    ed_reduced_m: float
    ed_governing_m: float
    j_knm: float
    drift_m: float
    drift_limit_m: float
    drift_ratio: float
    drift_exceeded: bool
    torsion_irregular: bool
    overturning_moment_knm: float
    elements: List[ElementShare] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storey": int(self.storey),
            "direction": self.direction,
            "height_m": self.height_m,
            "shear_kn": self.shear_kn,
            "sum_k_kn_m": self.sum_k_kn_m,
            "cr_m": [self.cr_x_m, self.cr_y_m],
            "cm_m": [self.cm_x_m, self.cm_y_m],
            "esi_m": self.esi_m,
            "bi_m": self.bi_m,
            "ed_amplified_m": self.ed_amplified_m,
            "ed_reduced_m": self.ed_reduced_m,
            "ed_governing_m": self.ed_governing_m,
            "j_knm": self.j_knm,
            "drift_m": self.drift_m,
            "drift_limit_m": self.drift_limit_m,
            "drift_ratio": self.drift_ratio,
            "drift_exceeded": bool(self.drift_exceeded),
            "torsion_irregular": bool(self.torsion_irregular),
            "overturning_moment_knm": self.overturning_moment_knm,
            "elements": [element.to_dict() for element in self.elements],
        }


@dataclass
class LateralResult:
    """Everything the lateral distribution produced, JSON-serializable."""

    storeys: List[StoreyLateral] = field(default_factory=list)
    materials: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    cm_source: str = ""
    assumptions: List[str] = field(default_factory=list)
    overturning: Dict[str, Any] = field(default_factory=dict)
    base_forces: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    log: DisclosureLog = field(default_factory=DisclosureLog)

    def storey(self, storey: int, direction: str) -> Optional[StoreyLateral]:
        for entry in self.storeys:
            if entry.storey == storey and entry.direction == direction:
                return entry
        return None

    def element(self, storey: int, direction: str, element_id: str) -> Optional[ElementShare]:
        block = self.storey(storey, direction)
        if block is None:
            return None
        for share in block.elements:
            if share.element_id == element_id:
                return share
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": "rigid diaphragm, additive-only torsion",
            "code": EQ_CODE,
            "context": dict(self.context),
            "materials": dict(self.materials),
            "cm_source": self.cm_source,
            "assumptions": list(self.assumptions),
            "storeys": [entry.to_dict() for entry in self.storeys],
            "overturning": {
                direction: dict(values) for direction, values in sorted(self.overturning.items())
            },
            "base_forces": {
                direction: {
                    element_id: dict(values)
                    for element_id, values in sorted(elements.items())
                }
                for direction, elements in sorted(self.base_forces.items())
            },
            "disclosures": self.log.to_dict(),
        }


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------


def _wall_direction(wall: Any) -> Optional[str]:
    """`x` for a wall running along X, `y` along Y, None for a degenerate line."""
    dx = abs(wall.b[0] - wall.a[0])
    dy = abs(wall.b[1] - wall.a[1])
    if dx <= _TINY and dy <= _TINY:
        return None
    return "x" if dx >= dy else "y"


def _wall_centre(wall: Any) -> Tuple[float, float]:
    return (0.5 * (wall.a[0] + wall.b[0]), 0.5 * (wall.a[1] + wall.b[1]))


def _storey_bbox(model: StructuralModel, storey: int) -> Optional[Tuple[float, float, float, float]]:
    """(x0, y0, x1, y1) over everything the storey carries, or None."""
    xs = []  # type: List[float]
    ys = []  # type: List[float]
    for room in model.rooms_on(storey):
        x, y, w, h = polygon_rect(room.polygon)
        xs.extend([x, x + w])
        ys.extend([y, y + h])
    for slab in model.slabs_on(storey):
        x, y, w, h = polygon_rect(slab.polygon)
        xs.extend([x, x + w])
        ys.extend([y, y + h])
    for wall in model.walls_on(storey):
        xs.extend([wall.a[0], wall.b[0]])
        ys.extend([wall.a[1], wall.b[1]])
    for column in model.columns_on(storey):
        xs.append(column.x_m)
        ys.append(column.y_m)
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _plan_dims(model: StructuralModel, storey: int, ctx: LateralContext) -> Tuple[float, float]:
    if ctx.plan_dims_m is not None:
        return (float(ctx.plan_dims_m[0]), float(ctx.plan_dims_m[1]))
    box = _storey_bbox(model, storey)
    if box is None:
        raise ValueError(
            "storey " + str(storey) + " carries no geometry, so no plan dimension can be measured; "
            "give LateralContext.plan_dims_m"
        )
    return (box[2] - box[0], box[3] - box[1])


def _area_centroid(model: StructuralModel, storey: int) -> Tuple[Tuple[float, float], str]:
    """Plan area centroid of the storey, and where it came from."""
    weighted_x = 0.0
    weighted_y = 0.0
    total = 0.0
    for room in sorted(model.rooms_on(storey), key=lambda r: r.id):
        x, y, w, h = polygon_rect(room.polygon)
        area = w * h
        if area <= _TINY:
            continue
        weighted_x += area * (x + 0.5 * w)
        weighted_y += area * (y + 0.5 * h)
        total += area
    if total > _TINY:
        return ((weighted_x / total, weighted_y / total), "plan area centroid of the storey rooms")
    weighted_x = 0.0
    weighted_y = 0.0
    total = 0.0
    for slab in sorted(model.slabs_on(storey), key=lambda s: s.id):
        x, y, w, h = polygon_rect(slab.polygon)
        area = w * h
        if area <= _TINY:
            continue
        weighted_x += area * (x + 0.5 * w)
        weighted_y += area * (y + 0.5 * h)
        total += area
    if total > _TINY:
        return ((weighted_x / total, weighted_y / total), "plan area centroid of the storey slabs")
    box = _storey_bbox(model, storey)
    if box is None:
        raise ValueError("storey " + str(storey) + " carries no geometry to place a centre of mass")
    return (
        (0.5 * (box[0] + box[2]), 0.5 * (box[1] + box[3])),
        "centre of the storey bounding box",
    )


# ---------------------------------------------------------------------------
# element stiffness
# ---------------------------------------------------------------------------


def _column_plan_dims(column: Any) -> Tuple[float, float]:
    """(bx, by): the section dimensions along X and along Y, honouring `rot`."""
    rot = int(getattr(column, "rot", 0) or 0) % 180
    if rot == 90:
        return (float(column.depth_m), float(column.width_m))
    return (float(column.width_m), float(column.depth_m))


def _column_entry(column: Any, height_m: float, ec_mpa: float, ctx: LateralContext) -> Dict[str, Any]:
    bx, by = _column_plan_dims(column)
    modifier = CRACKED_COLUMN_FACTOR if ctx.cracked_sections else 1.0
    i_x = by * bx ** 3 / 12.0
    i_y = bx * by ** 3 / 12.0
    return {
        "id": column.id,
        "type": "column",
        "x_m": float(column.x_m),
        "y_m": float(column.y_m),
        "length_m": None,
        "stack_id": getattr(column, "stack_id", None),
        "kx": column_stiffness(ec_mpa, i_x, height_m, modifier),
        "ky": column_stiffness(ec_mpa, i_y, height_m, modifier),
        "source": "12 Ec Ic / h^3, IS 456 6.2.3.1 modulus"
        + (", 0.7 Ig cracked" if ctx.cracked_sections else ", gross section"),
        "piers": [],
    }


def _opening_height(opening: Any, storey_height_m: float) -> float:
    sill = getattr(opening, "sill_m", None)
    head = getattr(opening, "head_m", None)
    if sill is None or head is None:
        return storey_height_m
    height = float(head) - float(sill)
    if height <= 0.0:
        return storey_height_m
    return min(height, storey_height_m)


def _wall_openings_state(wall: Any, dressed_storey: bool) -> str:
    """`dressed`, `assumed` or `solid`, deciding pier splitting vs knockdown."""
    if wall.openings:
        if any(not opening_assumed(opening) for opening in wall.openings):
            return "dressed"
        return "assumed"
    return "solid" if dressed_storey else "assumed"


def _wall_piers(
    wall: Any, length_m: float, storey_height_m: float
) -> List[Tuple[float, float, float]]:
    """Solid segments between dressed openings as (start, length, height).

    A pier takes the height of the tallest opening it flanks, which is the
    classic pier idealization and the flexible reading of the two; overlapping
    openings merge into one hole carrying the taller of them.
    """
    holes = []  # type: List[Tuple[float, float, float]]
    for opening in wall.openings:
        start, end = opening_span(wall, opening)
        low = max(0.0, min(start, end))
        high = min(length_m, max(start, end))
        if high - low <= _TINY:
            continue
        holes.append((low, high, _opening_height(opening, storey_height_m)))
    holes.sort()

    merged = []  # type: List[Tuple[float, float, float]]
    for low, high, opening_h in holes:
        if merged and low <= merged[-1][1] + _TINY:
            previous = merged[-1]
            merged[-1] = (previous[0], max(previous[1], high), max(previous[2], opening_h))
        else:
            merged.append((low, high, opening_h))

    piers = []  # type: List[Tuple[float, float, float]]
    cursor = 0.0
    for index, (low, high, opening_h) in enumerate(merged):
        if low - cursor > MIN_PIER_LENGTH_M:
            neighbours = [opening_h]
            if index > 0:
                neighbours.append(merged[index - 1][2])
            piers.append((cursor, low - cursor, max(neighbours)))
        cursor = max(cursor, high)
    if length_m - cursor > MIN_PIER_LENGTH_M:
        piers.append(
            (cursor, length_m - cursor, merged[-1][2] if merged else storey_height_m)
        )
    return piers


def _wall_entry(
    wall: Any,
    height_m: float,
    ec_mpa: float,
    em_mpa: float,
    ctx: LateralContext,
    dressed_storey: bool,
    stack_id: Optional[str],
    log: DisclosureLog,
    frame_ic_m4: Dict[str, Optional[float]],
) -> Optional[Dict[str, Any]]:
    direction = _wall_direction(wall)
    if direction is None:
        return None
    if wall.role in (WallRole.PARAPET, WallRole.RAILING):
        return None
    thickness = float(wall.thickness_m)
    if thickness < ctx.min_wall_thickness_m:
        return None
    length = wall.length_m()
    if length <= MIN_PIER_LENGTH_M:
        return None

    # The infill screen (module docstring, "which walls are credited"): only a
    # declared bearing wall or an RC wall is a shear pier. Anything else is
    # URM infill or an undeclared partition; by default it is excluded from
    # the lateral stiffness, disclosed, or credited as the Cl 7.9.2 strut when
    # the option asks for that.
    if not (wall.bearing is True or wall.material == Material.RC):
        if ctx.infill_stiffness == "strut":
            return _strut_entry(
                wall, direction, length, thickness, height_m, ec_mpa, em_mpa, stack_id, log,
                frame_ic_m4.get(direction),
            )
        log.add(
            "W_INFILL_EXCLUDED",
            "walls not declared bearing and not rc are not credited with lateral "
            "stiffness; the storey shear goes to the declared bearing walls and "
            "columns (URM infill idealization; crediting infill as shear piers "
            "would overstate the stiffness and misplace the centre of rigidity)",
            element_ids=[wall.id],
            clause=EQ_CODE + " 7.9",
            stage=STAGE,
        )
        return None

    e_mpa = ec_mpa if wall.material == Material.RC else em_mpa
    material = "rc" if wall.material == Material.RC else "masonry"
    state = _wall_openings_state(wall, dressed_storey)
    piers = []  # type: List[Dict[str, Any]]

    if state == "dressed":
        segments = _wall_piers(wall, length, height_m)
        if not segments:
            return None
        total_k = 0.0
        for start, pier_length, pier_height in segments:
            k = pier_stiffness(e_mpa, thickness, pier_height, pier_length, ctx.cantilever_piers)
            total_k += k
            piers.append(
                {
                    "start_m": start,
                    "length_m": pier_length,
                    "height_m": pier_height,
                    "k_kn_m": k,
                }
            )
        source = "sum of " + str(len(segments)) + " piers between dressed openings"
    else:
        gross = pier_stiffness(e_mpa, thickness, height_m, length, ctx.cantilever_piers)
        if state == "assumed":
            total_k = gross * ctx.opening_knockdown
            source = (
                "gross wall with the "
                + repr(ctx.opening_knockdown)
                + " opening knockdown (opening positions not known)"
            )
            log.add(
                "W_ASSUMED_OPENINGS",
                "wall "
                + wall.id
                + " has no dressed openings; its in-plane stiffness was taken as the gross pier "
                + "times "
                + repr(ctx.opening_knockdown)
                + " instead of summing piers between openings",
                element_ids=[wall.id],
                clause=EQ_CODE + " 7.10.2",
                stage=STAGE,
            )
        else:
            total_k = gross
            source = "gross solid wall, no openings on a dressed plan"
        piers.append({"start_m": 0.0, "length_m": length, "height_m": height_m, "k_kn_m": total_k})

    centre = _wall_centre(wall)
    if material == "masonry":
        modulus_note = "masonry pier, Em = 550 fm, "
    else:
        modulus_note = "rc wall, Ec = 5000 sqrt(fck), "
    return {
        "id": wall.id,
        "type": "wall",
        "x_m": centre[0],
        "y_m": centre[1],
        "length_m": length,
        "stack_id": stack_id,
        "kx": total_k if direction == "x" else 0.0,
        "ky": total_k if direction == "y" else 0.0,
        "source": modulus_note + source,
        "piers": piers,
    }


def _strut_entry(
    wall: Any,
    direction: str,
    length: float,
    thickness: float,
    height_m: float,
    ec_mpa: float,
    em_mpa: float,
    stack_id: Optional[str],
    log: DisclosureLog,
    ic_m4: Optional[float],
) -> Optional[Dict[str, Any]]:
    """One infill panel as the Cl 7.9.2 diagonal strut, or None with a reason.

    The strut needs an adjoining frame: `ic_m4` is the mean sway-axis Ic of
    the storey's columns for this direction. Without columns there is no
    frame to strut against, so the panel is excluded and the ladder says why.
    Openings are not reduced for in v1; the disclosure states that.
    """
    if ic_m4 is None:
        log.add(
            "W_INFILL_EXCLUDED",
            "the Cl 7.9.2 strut idealization needs adjoining columns and the "
            "storey has none, so non-bearing walls are excluded from the "
            "lateral stiffness",
            element_ids=[wall.id],
            clause=EQ_CODE + " 7.9.2",
            stage=STAGE,
        )
        return None
    record = strut_stiffness(em_mpa, thickness, height_m, length, ec_mpa, ic_m4)
    log.add(
        "N_INFILL_STRUT",
        "non-bearing masonry walls are credited as equivalent diagonal struts, "
        "w_ds = 0.175 alpha_h^-0.4 L_ds, with the mean sway-axis Ic of the "
        "storey columns as the adjoining-column Ic; opening reductions are not "
        "modelled",
        element_ids=[wall.id],
        clause=EQ_CODE + " 7.9.2",
        stage=STAGE,
    )
    centre = _wall_centre(wall)
    k = record["k_kn_m"]
    return {
        "id": wall.id,
        "type": "wall",
        "x_m": centre[0],
        "y_m": centre[1],
        "length_m": length,
        "stack_id": stack_id,
        "kx": k if direction == "x" else 0.0,
        "ky": k if direction == "y" else 0.0,
        "source": "urm infill as an equivalent diagonal strut, w_ds = 0.175 alpha_h^-0.4 L_ds ("
        + EQ_CODE
        + " 7.9.2), mean storey column Ic",
        "piers": [
            {
                "kind": "strut",
                "w_ds_m": record["w_ds_m"],
                "l_ds_m": record["l_ds_m"],
                "theta_rad": record["theta_rad"],
                "alpha_h": record["alpha_h"],
                "k_kn_m": k,
            }
        ],
    }


# ---------------------------------------------------------------------------
# the distribution
# ---------------------------------------------------------------------------


def run(
    model: StructuralModel,
    storey_shears: Dict[str, Dict[int, float]],
    ctx: Optional[LateralContext] = None,
    centres_of_mass: Optional[Dict[int, Tuple[float, float]]] = None,
    log: Optional[DisclosureLog] = None,
    trace: Optional[List[Any]] = None,
) -> LateralResult:
    """Distribute storey shears onto the vertical elements of each storey.

    `storey_shears` is `{"x": {storey: V_kN}, "y": {storey: V_kN}}` with
    magnitudes; `storey_shears_from_forces` builds it from the plain storey
    force dicts the loads modules emit.

    `centres_of_mass` is `{storey: (x_m, y_m)}` from the takedown storey
    ledger. Without it the mass centre falls back to the plan area centroid of
    the storey, which is recorded in `cm_source`, in `assumptions` and on the
    ladder.

    Pass `trace` to collect the clause records; pass `log` to merge the
    disclosures into a shared ladder as well as into the result.
    """
    if trace is not None:
        with trace_into(trace):
            return _run(model, storey_shears, ctx, centres_of_mass, log)
    return _run(model, storey_shears, ctx, centres_of_mass, log)


def _run(
    model: StructuralModel,
    storey_shears: Dict[str, Dict[int, float]],
    ctx: Optional[LateralContext],
    centres_of_mass: Optional[Dict[int, Tuple[float, float]]],
    into: Optional[DisclosureLog],
) -> LateralResult:
    context = ctx or LateralContext()
    log = DisclosureLog()
    ec_mpa = is456.cl_6_2_3_1__ec(context.fck_mpa)
    em_mpa = masonry_modulus(context.fm_mpa)

    shears = {
        direction: {int(k): abs(float(v)) for k, v in (storey_shears.get(direction) or {}).items()}
        for direction in _DIRECTIONS
    }
    storeys = sorted({storey for direction in _DIRECTIONS for storey in shears[direction]})
    if not storeys:
        raise ValueError("storey_shears carries no storey in either direction")

    stack_of = {}  # type: Dict[str, str]
    for stack in model.build_wall_stacks():
        for wall_id in stack["walls"].values():
            stack_of[wall_id] = stack["stack_id"]

    cm_sources = []  # type: List[str]
    result = LateralResult(
        materials={
            "fck_mpa": float(context.fck_mpa),
            "ec_mpa": ec_mpa,
            "ec_clause": "IS 456:2000 6.2.3.1",
            "fm_mpa": float(context.fm_mpa),
            "em_mpa": em_mpa,
            "em_clause": EQ_CODE + " 7.10.2",
        },
        context=context.to_dict(),
        log=log,
    )

    # Walk the storeys top-down so the wall cantilever moment accumulates.
    carried = {}  # type: Dict[Tuple[str, str], float]
    blocks = []  # type: List[StoreyLateral]
    for storey in sorted(storeys, reverse=True):
        record = model.storey(storey)
        if record is None:
            raise ValueError("storey " + str(storey) + " is not in the model")
        height_m = float(record.height_m)
        if height_m <= 0.0:
            raise ValueError("storey " + str(storey) + " has a non-positive height")

        entries = _storey_entries(model, storey, height_m, ec_mpa, em_mpa, context, stack_of, log)
        plan_x, plan_y = _plan_dims(model, storey, context)
        cr_x, cr_y = _centre_of_rigidity(entries)
        if centres_of_mass is not None and storey in centres_of_mass:
            cm_x, cm_y = (float(centres_of_mass[storey][0]), float(centres_of_mass[storey][1]))
            cm_source = "storey ledger mass centroid"
        else:
            (cm_x, cm_y), cm_source = _area_centroid(model, storey)
        cm_sources.append(cm_source)

        j_knm = sum(
            entry["kx"] * (entry["y_m"] - cr_y) ** 2 + entry["ky"] * (entry["x_m"] - cr_x) ** 2
            for entry in entries
        )

        for direction in _DIRECTIONS:
            if storey not in shears[direction]:
                continue
            block = _distribute(
                storey=storey,
                direction=direction,
                shear_kn=shears[direction][storey],
                height_m=height_m,
                entries=entries,
                cr=(cr_x, cr_y),
                cm=(cm_x, cm_y),
                plan=(plan_x, plan_y),
                j_knm=j_knm,
                carried=carried,
                log=log,
            )
            if block is not None:
                blocks.append(block)

    blocks.sort(key=lambda entry: (entry.storey, entry.direction))
    result.storeys = blocks
    result.cm_source = cm_sources[0] if len(set(cm_sources)) == 1 else "mixed, see each storey"
    if centres_of_mass is None:
        log.add(
            "W_TORSION",
            "no storey mass ledger was supplied; the centre of mass was taken at the plan area "
            "centroid of each storey, so the static eccentricity is a geometric estimate",
            clause=EQ_CODE + " 7.8.2",
            stage=STAGE,
        )
    result.assumptions = _assumptions(context, centres_of_mass is None)
    result.overturning = _overturning(shears, model, storeys)
    result.base_forces = _base_forces(blocks, min(storeys))
    if into is not None:
        into.extend(log.entries)
    return result


def _storey_entries(
    model: StructuralModel,
    storey: int,
    height_m: float,
    ec_mpa: float,
    em_mpa: float,
    ctx: LateralContext,
    stack_of: Dict[str, str],
    log: DisclosureLog,
) -> List[Dict[str, Any]]:
    """Every participating vertical element on the storey, sorted by id."""
    entries = []  # type: List[Dict[str, Any]]
    sway_ic = {"x": [], "y": []}  # type: Dict[str, List[float]]
    for column in sorted(model.columns_on(storey), key=lambda c: c.id):
        entries.append(_column_entry(column, height_m, ec_mpa, ctx))
        bx, by = _column_plan_dims(column)
        sway_ic["x"].append(by * bx ** 3 / 12.0)
        sway_ic["y"].append(bx * by ** 3 / 12.0)
    # Mean sway-axis Ic per direction: the adjoining-column Ic the Cl 7.9.2
    # strut option needs. None when the storey has no columns.
    frame_ic_m4 = {
        direction: (sum(values) / len(values) if values else None)
        for direction, values in sway_ic.items()
    }  # type: Dict[str, Optional[float]]
    dressed = model.doors_known(storey)
    for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
        entry = _wall_entry(
            wall, height_m, ec_mpa, em_mpa, ctx, dressed, stack_of.get(wall.id), log,
            frame_ic_m4,
        )
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: entry["id"])
    return entries


def _centre_of_rigidity(entries: Sequence[Dict[str, Any]]) -> Tuple[float, float]:
    """(x_cr, y_cr): x from the Y-direction stiffnesses, y from the X-direction ones."""
    sum_kx = sum(entry["kx"] for entry in entries)
    sum_ky = sum(entry["ky"] for entry in entries)
    x_cr = (
        sum(entry["ky"] * entry["x_m"] for entry in entries) / sum_ky if sum_ky > _TINY else 0.0
    )
    y_cr = (
        sum(entry["kx"] * entry["y_m"] for entry in entries) / sum_kx if sum_kx > _TINY else 0.0
    )
    return (x_cr, y_cr)


def _distribute(
    storey: int,
    direction: str,
    shear_kn: float,
    height_m: float,
    entries: Sequence[Dict[str, Any]],
    cr: Tuple[float, float],
    cm: Tuple[float, float],
    plan: Tuple[float, float],
    j_knm: float,
    carried: Dict[Tuple[str, str], float],
    log: DisclosureLog,
) -> Optional[StoreyLateral]:
    key = "kx" if direction == "x" else "ky"
    participating = [entry for entry in entries if entry[key] > _TINY]
    sum_k = sum(entry[key] for entry in participating)
    if sum_k <= _TINY:
        log.add(
            "E_NO_BEARING_DIRECTION",
            "storey "
            + str(storey)
            + " has no vertical element resisting shear along "
            + direction
            + "; the storey shear cannot be distributed",
            clause=EQ_CODE + " 7.8",
            stage=STAGE,
        )
        return None

    # esi is measured perpendicular to the direction shaken, bi likewise.
    if direction == "x":
        esi = cm[1] - cr[1]
        bi = plan[1]
    else:
        esi = cm[0] - cr[0]
        bi = plan[0]

    # Cl 7.8.2 defines esi as the DISTANCE between the mass and rigidity
    # centres, so the magnitude goes in; the signed value stays on the wire as
    # `esi_m` for the mirror disclosure. With the distance in, the amplified
    # branch always governs by magnitude (1.5 |esi| + 0.05 bi covers both
    # accidental directions); the pick below stays for reporting.
    eccentricity = is1893.design_eccentricity(abs(esi), bi)
    amplified_governs = abs(eccentricity.amplified) >= abs(eccentricity.reduced)
    ed_governing = eccentricity.amplified if amplified_governs else eccentricity.reduced
    torque = shear_kn * abs(ed_governing)

    shares = []  # type: List[ElementShare]
    for entry in participating:
        k = entry[key]
        offset = (entry["y_m"] - cr[1]) if direction == "x" else (entry["x_m"] - cr[0])
        direct = shear_kn * k / sum_k
        # Additive only: no element is relieved on the flexible side.
        torsion = abs(torque * k * offset / j_knm) if j_knm > _TINY else 0.0
        total = direct + torsion
        share = ElementShare(
            element_id=entry["id"],
            element_type=entry["type"],
            storey=storey,
            direction=direction,
            k_kn_m=k,
            x_m=entry["x_m"],
            y_m=entry["y_m"],
            d_m=offset,
            v_direct_kn=direct,
            v_torsion_kn=torsion,
            v_kn=total,
            stack_id=entry["stack_id"],
            stiffness_source=entry["source"],
            piers=list(entry["piers"]),
        )
        if entry["type"] == "column":
            share.m_top_knm = total * height_m / 2.0
            share.m_bot_knm = total * height_m / 2.0
        else:
            length = float(entry["length_m"])
            share.length_m = length
            share.v_per_m_kn_m = total / length if length > _TINY else 0.0
            stack_key = (entry["stack_id"] or entry["id"], direction)
            above = carried.get(stack_key, 0.0)
            share.m_base_knm = above + total * height_m
            share.m_top_knm = above
            share.m_bot_knm = share.m_base_knm
            carried[stack_key] = share.m_base_knm
        shares.append(share)

    shares.sort(key=lambda share: share.element_id)
    drift = shear_kn / sum_k
    drift_limit = is1893.storey_drift_limit(height_m)
    drift_exceeded = drift > drift_limit
    if drift_exceeded:
        log.add(
            "W_EQ_DRIFT",
            "storey "
            + str(storey)
            + " drift along "
            + direction
            + " is "
            + repr(drift)
            + " m against the "
            + repr(drift_limit)
            + " m limit",
            clause=EQ_CODE + " 7.11.1.1",
            stage=STAGE,
        )
    torsion_irregular = abs(esi) > TORSION_GATE_FRACTION * bi
    if torsion_irregular:
        log.add(
            "W_EQ_TORSION_IRREGULAR",
            "storey "
            + str(storey)
            + " static eccentricity along "
            + direction
            + " is "
            + repr(esi)
            + " m, past "
            + repr(TORSION_GATE_FRACTION)
            + " of the "
            + repr(bi)
            + " m plan dimension; the governing Cl 7.8.2 design eccentricity is the "
            + ("amplified" if amplified_governs else "reduced")
            + " branch, "
            + repr(ed_governing)
            + " m; torsionally irregular, an FE phase is recommended",
            clause=EQ_CODE + " 7.8.2",
            stage=STAGE,
        )

    return StoreyLateral(
        storey=storey,
        direction=direction,
        height_m=height_m,
        shear_kn=shear_kn,
        sum_k_kn_m=sum_k,
        cr_x_m=cr[0],
        cr_y_m=cr[1],
        cm_x_m=cm[0],
        cm_y_m=cm[1],
        esi_m=esi,
        bi_m=bi,
        ed_amplified_m=eccentricity.amplified,
        ed_reduced_m=eccentricity.reduced,
        ed_governing_m=ed_governing,
        j_knm=j_knm,
        drift_m=drift,
        drift_limit_m=drift_limit,
        drift_ratio=drift / height_m,
        drift_exceeded=drift_exceeded,
        torsion_irregular=torsion_irregular,
        overturning_moment_knm=shear_kn * height_m,
        elements=shares,
    )


def _overturning(
    shears: Dict[str, Dict[int, float]], model: StructuralModel, storeys: Sequence[int]
) -> Dict[str, Any]:
    """Base overturning demand, from the storey shears differenced into forces."""
    out = {}  # type: Dict[str, Any]
    base_storey = min(storeys)
    base_record = model.storey(base_storey)
    base_z = float(base_record.bottom_z_m) if base_record is not None else 0.0
    for direction in _DIRECTIONS:
        table = shears[direction]
        if not table:
            continue
        ordered = sorted(table)
        moment = 0.0
        rows = []  # type: List[Dict[str, Any]]
        for index, storey in enumerate(ordered):
            above = table[ordered[index + 1]] if index + 1 < len(ordered) else 0.0
            force = table[storey] - above
            record = model.storey(storey)
            h_i = (
                float(record.bottom_z_m) + float(record.height_m) - base_z
                if record is not None
                else 0.0
            )
            moment += force * h_i
            rows.append({"storey": storey, "f_kn": force, "h_i_m": h_i, "v_kn": table[storey]})
        out[direction] = {
            "base_shear_kn": table[ordered[0]],
            "overturning_moment_knm": moment,
            "levels": rows,
            "note": "demand only; the stabilizing moment is checked with the gravity takedown",
        }
    return out


def _base_forces(blocks: Sequence[StoreyLateral], base_storey: int) -> Dict[str, Dict[str, Any]]:
    """Shear and moment at the base of the lowest storey, for the footing loads."""
    out = {}  # type: Dict[str, Dict[str, Any]]
    for block in blocks:
        if block.storey != base_storey:
            continue
        table = out.setdefault(block.direction, {})
        for share in block.elements:
            moment = share.m_base_knm if share.m_base_knm is not None else share.m_bot_knm
            table[share.element_id] = {
                "element_type": share.element_type,
                "v_kn": share.v_kn,
                "m_knm": moment,
            }
    return out


def _assumptions(ctx: LateralContext, cm_fallback: bool) -> List[str]:
    if ctx.infill_stiffness == "strut":
        infill_line = (
            "only declared bearing walls and rc walls are credited as shear piers; "
            "non-bearing masonry infill is credited as IS 1893 Cl 7.9.2 equivalent "
            "diagonal struts (w_ds = 0.175 alpha_h^-0.4 L_ds, mean storey column Ic, "
            "opening reductions not modelled)"
        )
    else:
        infill_line = (
            "only declared bearing walls and rc walls are credited with lateral "
            "stiffness; non-bearing masonry infill is excluded, because crediting "
            "infill as shear piers overstates the stiffness, understates the period "
            "and the drift, and misplaces the centre of rigidity"
        )
    lines = [
        "rigid diaphragm per floor; no in-plane flexibility is modelled",
        "fixed-fixed shear elements between floors; column inflection at mid height",
        infill_line,
        "only elements parallel to the direction shaken participate",
        "torsional share is additive only, so no element is relieved on the flexible side "
        "and the element shears sum to more than the storey shear",
        "beam flexibility is not modelled (shear-building idealization), so the Cl 6.4.3 "
        "beam modifier has no effect here and uniform modifiers do not change the ratios",
        "cantilever wall moment accumulates down a wall stack; no coupling beams are modelled",
    ]
    if ctx.cracked_sections:
        lines.append(
            "cracked-section column stiffness "
            + repr(CRACKED_COLUMN_FACTOR)
            + " Ig applied (beam factor "
            + repr(CRACKED_BEAM_FACTOR)
            + " recorded but unused here)"
        )
    if ctx.cantilever_piers:
        lines.append("masonry piers taken as cantilevers, 4 (h/L)^3 + 3 (h/L)")
    if cm_fallback:
        lines.append(
            "centre of mass taken at the plan area centroid; no storey mass ledger was supplied"
        )
    return lines
