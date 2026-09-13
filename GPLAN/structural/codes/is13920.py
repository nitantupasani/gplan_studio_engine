"""IS 13920:2016 ductile detailing clauses, one clause per traced callable.

Scope of this module: the geometry, reinforcement ratio, capacity shear, hoop
and confinement rules the RC designer overlays on an IS 456 design when
`is13920_applies(zone, frame)` is true. Nothing here sizes a section or picks a
bar; every callable is a pure function of floats returning a float, a bool or a
NamedTuple, traced by the single sink in `codes/trace.py`.

Units are the design layer's: N, mm, MPa. Reinforcement ratios are on the
b x d (effective depth) area, as IS 13920 defines them. Moments are N.mm and
shears N, so the capacity shear formula needs no conversion factor.

Conservative reading, deliberate and disclosed: where the 1993 and 2016
editions differ on a hoop spacing bound this module takes the union of the two
(the tighter cap with the higher floor) and says so in the returned `notes`,
which the designer copies into DesignResult.notes. Two conditions carried in
`notes` rather than in the model.py disclosure ladder, because no registry code
covers them: the edition union just described, and the Cl 9 joint verdict,
which travels as the DesignResult referral `joint_check_manual`.

Edition constants live in `structural/data/is13920.yaml`; they are read once at
import into the module constants below.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple, Optional, Tuple

from ..data._loader import load_yaml, require_keys
from .trace import clause

CODE = "IS13920:2016"

# ---------------------------------------------------------------------------
# edition constants (data/is13920.yaml, read once, frozen into module scalars)
# ---------------------------------------------------------------------------

_TABLE = load_yaml("is13920")
require_keys(
    _TABLE,
    ("schema_version", "source", "edition", "beam", "column", "applicability"),
    "is13920.yaml",
)


def _get(path: str) -> Any:
    """Dotted lookup into the loaded table; a missing key raises, never defaults."""
    node = _TABLE  # type: Any
    walked = []
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise ValueError("is13920.yaml is missing " + path + " (resolved " + ".".join(walked) + ")")
        walked.append(key)
        node = node[key]
    return node


def _num(path: str) -> float:
    return float(_get(path))


EDITION = str(_get("edition"))
SOURCE = str(_get("source"))

BEAM_MIN_WIDTH_MM = _num("beam.min_width_mm")
BEAM_MIN_WIDTH_OVER_DEPTH = _num("beam.min_width_over_depth")
BEAM_MAX_DEPTH_OVER_CLEAR_SPAN = _num("beam.max_depth_over_clear_span")
BEAM_RHO_MIN_COEFF = _num("beam.rho_min_coeff")
BEAM_RHO_MAX = _num("beam.rho_max")
BEAM_MIN_BARS_EACH_FACE = int(_get("beam.min_bars_each_face"))
BEAM_SAGGING_RATIO_AT_FACE = _num("beam.sagging_ratio_at_face")
BEAM_HOGGING_RATIO_ALONG_SPAN = _num("beam.hogging_ratio_along_span")
CAPACITY_SHEAR_FACTOR = _num("beam.capacity_shear_factor")

HOOP_END_ZONE_DEPTH_FACTOR = _num("beam.hoop.end_zone_depth_factor")
HOOP_FIRST_FROM_FACE_MM = _num("beam.hoop.first_hoop_from_face_mm")
HOOP_MIN_DIA_MM = _num("beam.hoop.min_dia_mm")
HOOP_MIN_DIA_LONG_SPAN_MM = _num("beam.hoop.min_dia_long_span_mm")
HOOP_LONG_SPAN_THRESHOLD_MM = _num("beam.hoop.long_span_threshold_mm")
HOOP_SPACING_DEPTH_DIVISOR = _num("beam.hoop.spacing_depth_divisor")
HOOP_SPACING_BAR_MULTIPLE = _num("beam.hoop.spacing_bar_multiple")
HOOP_SPACING_FLOOR_MM = _num("beam.hoop.spacing_floor_mm")
HOOP_MID_SPACING_DEPTH_DIVISOR = _num("beam.hoop.mid_span_spacing_depth_divisor")

COLUMN_MIN_DIMENSION_MM = _num("column.min_dimension_mm")
COLUMN_BEAM_BAR_DIA_MULTIPLE = _num("column.beam_bar_dia_multiple")
COLUMN_MIN_WIDTH_OVER_DEPTH = _num("column.min_width_over_depth")
STRONG_COLUMN_RATIO = _num("column.strong_column_ratio")

ASH_AREA_RATIO_COEFF = _num("column.confining.ash_area_ratio_coeff")
ASH_FLOOR_COEFF = _num("column.confining.ash_floor_coeff")
CONFINING_MAX_HOOP_LEG_MM = _num("column.confining.max_hoop_leg_mm")
CONFINING_LO_MIN_MM = _num("column.confining.lo_min_mm")
CONFINING_LO_HEIGHT_DIVISOR = _num("column.confining.lo_clear_height_divisor")
CONFINING_SPACING_MIN_DIM_DIVISOR = _num("column.confining.spacing_min_dim_divisor")
CONFINING_SPACING_BAR_MULTIPLE = _num("column.confining.spacing_bar_multiple")
CONFINING_SPACING_CAP_MM = _num("column.confining.spacing_cap_mm")
CONFINING_SPACING_FLOOR_MM = _num("column.confining.spacing_floor_mm")

DUCTILE_ZONES = tuple(str(z).upper() for z in _get("applicability.zones"))
SMRF_ANY_ZONE = bool(_get("applicability.smrf_any_zone"))

VERIFY_IN_PRINT = tuple(sorted(str(k) for k in (_TABLE.get("verify") or {})))

# Float comparison slack: geometry arrives rounded to whole millimetres, so a
# ratio landing 1e-12 under a bound is a rounding artefact, not a failure.
_TOL = 1e-9

_ZONE_ALIASES = {
    "1": "I",
    "2": "II",
    "3": "III",
    "4": "IV",
    "5": "V",
    "I": "I",
    "II": "II",
    "III": "III",
    "IV": "IV",
    "V": "V",
}

_FRAMES = ("OMRF", "SMRF")


# ---------------------------------------------------------------------------
# return shapes
# ---------------------------------------------------------------------------


class BeamGeometry(NamedTuple):
    """Cl 6.1 verdict on a trial beam section."""

    ok: bool
    width_ok: bool
    aspect_ok: bool
    depth_ok: bool
    width_over_depth: float
    min_width_mm: float
    max_depth_mm: float
    notes: Tuple[str, ...]


class CapacityShear(NamedTuple):
    """Cl 6.3.3 design shear at one beam end, both sway directions."""

    v_sway_right_n: float
    v_sway_left_n: float
    v_design_n: float
    sway_term_n: float
    governs: str


class HoopZones(NamedTuple):
    """Cl 6.3.5 hoop geometry for one beam."""

    end_zone_mm: float
    spacing_end_mm: float
    spacing_mid_mm: float
    first_hoop_mm: float
    min_dia_mm: float
    limit_depth_mm: float
    limit_bar_mm: float
    floor_applied: bool
    notes: Tuple[str, ...]


class ColumnGeometry(NamedTuple):
    """Cl 7.1 verdict on a trial column section."""

    ok: bool
    min_dim_ok: bool
    aspect_ok: bool
    min_dim_mm: float
    required_min_dim_mm: float
    aspect_ratio: float
    notes: Tuple[str, ...]


class StrongColumn(NamedTuple):
    """Cl 7.2.1 strong column weak beam ratio. Reported, never auto resized."""

    ratio: float
    required: float
    ok: bool
    applicable: bool
    flag_only: bool
    notes: Tuple[str, ...]


class ConfiningSteel(NamedTuple):
    """Cl 7.6.3 area of one leg of a rectangular confining hoop."""

    ash_mm2: float
    ash_area_ratio_mm2: float
    ash_floor_mm2: float
    governs: str
    crossties_required: bool
    notes: Tuple[str, ...]


class ConfiningSpacing(NamedTuple):
    """Cl 7.6.2 pitch of special confining hoops."""

    spacing_mm: float
    limit_min_dim_mm: float
    limit_bar_mm: float
    cap_mm: float
    floor_applied: bool
    governs: str
    notes: Tuple[str, ...]


class JointCheck(NamedTuple):
    """Cl 9 verdict: joints are flagged for a hand check, never designed here."""

    designed: bool
    marker: str
    referral: str
    notes: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Cl 6: flexural members
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="6.1",
    title="Flexural member geometry",
    symbol="b, D",
    units="mm",
    latex=r"b\ge 200,\quad \frac{b}{D}\ge 0.3,\quad D\le \frac{L_{clear}}{4}",
)
def cl_6_1__beam_geometry(b_mm: float, depth_mm: float, clear_span_mm: float) -> BeamGeometry:
    """Width floor, width to depth ratio and depth to clear span cap (Cl 6.1.1 to 6.1.3).

    `depth_mm` is the overall depth D, not the effective depth.
    """
    if b_mm <= 0.0 or depth_mm <= 0.0:
        raise ValueError("beam b_mm and depth_mm must be positive")
    if clear_span_mm <= 0.0:
        raise ValueError("clear_span_mm must be positive")
    ratio = float(b_mm) / float(depth_mm)
    max_depth = BEAM_MAX_DEPTH_OVER_CLEAR_SPAN * float(clear_span_mm)
    width_ok = float(b_mm) >= BEAM_MIN_WIDTH_MM - _TOL
    aspect_ok = ratio >= BEAM_MIN_WIDTH_OVER_DEPTH - _TOL
    depth_ok = float(depth_mm) <= max_depth + _TOL
    notes = []
    if not width_ok:
        notes.append("beam width " + _mm(b_mm) + " below the Cl 6.1.1 floor of " + _mm(BEAM_MIN_WIDTH_MM))
    if not aspect_ok:
        notes.append("b/D " + _r(ratio, 3) + " below the Cl 6.1.2 limit of " + _r(BEAM_MIN_WIDTH_OVER_DEPTH, 2))
    if not depth_ok:
        notes.append("depth " + _mm(depth_mm) + " above the Cl 6.1.3 cap of " + _mm(max_depth) + " (clear span / 4)")
    return BeamGeometry(
        ok=width_ok and aspect_ok and depth_ok,
        width_ok=width_ok,
        aspect_ok=aspect_ok,
        depth_ok=depth_ok,
        width_over_depth=ratio,
        min_width_mm=BEAM_MIN_WIDTH_MM,
        max_depth_mm=max_depth,
        notes=tuple(notes),
    )


@clause(
    code=CODE,
    ref="6.2.1",
    title="Minimum tension reinforcement ratio",
    symbol="rho_min",
    units="-",
    latex=r"\rho_{min}=0.24\frac{\sqrt{f_{ck}}}{f_y}",
)
def cl_6_2_1__rho_min(fck_mpa: float, fy_mpa: float) -> float:
    """Minimum flexural steel ratio on b x d, at any section, top and bottom."""
    if fck_mpa <= 0.0 or fy_mpa <= 0.0:
        raise ValueError("fck_mpa and fy_mpa must be positive")
    return BEAM_RHO_MIN_COEFF * math.sqrt(float(fck_mpa)) / float(fy_mpa)


@clause(
    code=CODE,
    ref="6.2.1(b)",
    title="Minimum bars continuous through the span",
    symbol="n_min",
    units="bars",
)
def cl_6_2_1__min_bars_each_face() -> int:
    """Bars that must run the full length of the beam on each face."""
    return BEAM_MIN_BARS_EACH_FACE


@clause(
    code=CODE,
    ref="6.2.2",
    title="Maximum tension reinforcement ratio",
    symbol="rho_max",
    units="-",
)
def cl_6_2_2__rho_max() -> float:
    """Cap on flexural steel ratio on b x d, each face."""
    return BEAM_RHO_MAX


@clause(
    code=CODE,
    ref="6.2.3",
    title="Sagging capacity at a joint face",
    symbol="Mu_sag,req",
    units="N.mm",
    latex=r"M_{u}^{sag}\ge 0.5\,M_{u}^{hog}",
)
def cl_6_2_3__joint_sagging(mu_hog_face_nmm: float) -> float:
    """Sagging capacity required at a joint face, from the hogging capacity there."""
    if mu_hog_face_nmm < 0.0:
        raise ValueError("mu_hog_face_nmm is a capacity magnitude and cannot be negative")
    return BEAM_SAGGING_RATIO_AT_FACE * float(mu_hog_face_nmm)


@clause(
    code=CODE,
    ref="6.2.4",
    title="Capacity retained along the span",
    symbol="Mu_min,span",
    units="N.mm",
)
def cl_6_2_4__span_capacity_floor(mu_face_max_nmm: float) -> float:
    """Hogging or sagging capacity to be retained at any section along the span."""
    if mu_face_max_nmm < 0.0:
        raise ValueError("mu_face_max_nmm is a capacity magnitude and cannot be negative")
    return BEAM_HOGGING_RATIO_ALONG_SPAN * float(mu_face_max_nmm)


@clause(
    code=CODE,
    ref="6.3.3",
    title="Design shear from plastic hinge capacity",
    symbol="Vu",
    units="N",
    latex=r"V_u=V_{g}\pm 1.4\frac{M_{u,A}+M_{u,B}}{L_{clear}}",
)
def cl_6_3_3__capacity_shear(
    v_gravity_n: float,
    mu_hog_nmm: float,
    mu_sag_nmm: float,
    l_clear_mm: float,
) -> CapacityShear:
    """Design shear at one beam end for both sway directions, Cl 6.3.3.

    The moment pair is the two end capacities that yield together in one sway
    direction: hogging at the end that hogs plus sagging at the far end. Both
    capacities are those of the PROVIDED steel, not the demand. For a beam whose
    two ends carry different steel, call once per pairing:
    sway right = (sagging at A, hogging at B), sway left = (hogging at A,
    sagging at B); with a symmetric section the two sums are equal and one call
    covers both. `v_gravity_n` is the factored gravity shear at the end being
    designed, signed by the caller's convention; the returned design shear is
    the larger magnitude of the two sway directions.
    """
    if l_clear_mm <= 0.0:
        raise ValueError("l_clear_mm must be positive")
    if mu_hog_nmm < 0.0 or mu_sag_nmm < 0.0:
        raise ValueError("capacities are magnitudes and cannot be negative")
    term = CAPACITY_SHEAR_FACTOR * (float(mu_hog_nmm) + float(mu_sag_nmm)) / float(l_clear_mm)
    right = float(v_gravity_n) + term
    left = float(v_gravity_n) - term
    if abs(right) >= abs(left):
        design, governs = abs(right), "sway_right"
    else:
        design, governs = abs(left), "sway_left"
    return CapacityShear(
        v_sway_right_n=right,
        v_sway_left_n=left,
        v_design_n=design,
        sway_term_n=term,
        governs=governs,
    )


@clause(
    code=CODE,
    ref="6.3.5",
    title="Hoop zones and spacing in flexural members",
    symbol="s",
    units="mm",
    latex=r"s_{end}\le\min\left(\frac{d}{4},8d_{b}\right),\ s_{end}\ge 100,\ s_{mid}\le\frac{d}{2}",
)
def cl_6_3_5__hoop_zones(
    d_eff_mm: float,
    dia_long_min_mm: float,
    clear_span_mm: Optional[float] = None,
) -> HoopZones:
    """End hoop zone length, hoop pitch inside and outside it, and hoop diameter.

    End zones run 2d from each joint face, the first hoop sits 50 mm from the
    face. Inside the zone the pitch is the lesser of d/4 and 8 times the
    smallest longitudinal bar, but need not be taken below 100 mm; outside it
    the pitch is d/2. Hoop diameter is 8 mm, raised to 10 mm on clear spans
    above 5 m when `clear_span_mm` is supplied.
    """
    if d_eff_mm <= 0.0:
        raise ValueError("d_eff_mm must be positive")
    if dia_long_min_mm <= 0.0:
        raise ValueError("dia_long_min_mm must be positive")
    limit_depth = float(d_eff_mm) / HOOP_SPACING_DEPTH_DIVISOR
    limit_bar = HOOP_SPACING_BAR_MULTIPLE * float(dia_long_min_mm)
    computed = min(limit_depth, limit_bar)
    floor_applied = computed < HOOP_SPACING_FLOOR_MM
    spacing_end = HOOP_SPACING_FLOOR_MM if floor_applied else computed
    notes = []
    if floor_applied:
        notes.append(
            "end hoop pitch raised from " + _mm(computed) + " to the Cl 6.3.5.2 floor of " + _mm(HOOP_SPACING_FLOOR_MM)
        )
    min_dia = HOOP_MIN_DIA_MM
    if clear_span_mm is not None and float(clear_span_mm) > HOOP_LONG_SPAN_THRESHOLD_MM:
        min_dia = HOOP_MIN_DIA_LONG_SPAN_MM
        notes.append("hoop diameter raised to " + _mm(min_dia) + " on a clear span above " + _mm(HOOP_LONG_SPAN_THRESHOLD_MM))
    return HoopZones(
        end_zone_mm=HOOP_END_ZONE_DEPTH_FACTOR * float(d_eff_mm),
        spacing_end_mm=spacing_end,
        spacing_mid_mm=float(d_eff_mm) / HOOP_MID_SPACING_DEPTH_DIVISOR,
        first_hoop_mm=HOOP_FIRST_FROM_FACE_MM,
        min_dia_mm=min_dia,
        limit_depth_mm=limit_depth,
        limit_bar_mm=limit_bar,
        floor_applied=floor_applied,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Cl 7: columns
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="7.1",
    title="Column geometry",
    symbol="b, D",
    units="mm",
    latex=r"\min(b,D)\ge\max(300,\,20d_{b,beam}),\quad \frac{b}{D}\ge 0.45",
)
def cl_7_1__column_geometry(b_mm: float, depth_mm: float, dia_beam_bar_mm: float) -> ColumnGeometry:
    """Minimum column dimension and side ratio (Cl 7.1.1, Cl 7.1.2).

    `dia_beam_bar_mm` is the largest longitudinal bar of any beam passing
    through or anchoring into the joint. The aspect ratio is the shorter side
    over the longer side, so the check is orientation free.
    """
    if b_mm <= 0.0 or depth_mm <= 0.0:
        raise ValueError("column b_mm and depth_mm must be positive")
    if dia_beam_bar_mm <= 0.0:
        raise ValueError("dia_beam_bar_mm must be positive")
    smaller = min(float(b_mm), float(depth_mm))
    larger = max(float(b_mm), float(depth_mm))
    required = max(COLUMN_MIN_DIMENSION_MM, COLUMN_BEAM_BAR_DIA_MULTIPLE * float(dia_beam_bar_mm))
    ratio = smaller / larger
    min_dim_ok = smaller >= required - _TOL
    aspect_ok = ratio >= COLUMN_MIN_WIDTH_OVER_DEPTH - _TOL
    notes = []
    if not min_dim_ok:
        notes.append(
            "column least dimension " + _mm(smaller) + " below the Cl 7.1.1 requirement of " + _mm(required)
        )
    if not aspect_ok:
        notes.append("side ratio " + _r(ratio, 3) + " below the Cl 7.1.2 limit of " + _r(COLUMN_MIN_WIDTH_OVER_DEPTH, 2))
    return ColumnGeometry(
        ok=min_dim_ok and aspect_ok,
        min_dim_ok=min_dim_ok,
        aspect_ok=aspect_ok,
        min_dim_mm=smaller,
        required_min_dim_mm=required,
        aspect_ratio=ratio,
        notes=tuple(notes),
    )


@clause(
    code=CODE,
    ref="7.2.1",
    title="Strong column weak beam ratio",
    symbol="sum Mc / sum Mb",
    units="-",
    latex=r"\sum M_{c}\ge 1.4\sum M_{b}",
)
def cl_7_2_1__strong_column_ratio(sum_mc_nmm: float, sum_mb_nmm: float) -> StrongColumn:
    """Joint moment capacity ratio, REPORTED ONLY.

    A shortfall never resizes a column in this version: it is surfaced as a
    check row and the DesignResult referral `joint_check_manual`. With no beam
    capacity framing in (a roof joint with the beams above absent, or a caller
    that has not designed the beams yet) the check is not applicable and is
    reported so, rather than passing silently.
    """
    if sum_mc_nmm < 0.0 or sum_mb_nmm < 0.0:
        raise ValueError("capacities are magnitudes and cannot be negative")
    applicable = float(sum_mb_nmm) > 0.0
    if not applicable:
        return StrongColumn(
            ratio=0.0,
            required=STRONG_COLUMN_RATIO,
            ok=True,
            applicable=False,
            flag_only=True,
            notes=("no beam capacity framing into the joint; Cl 7.2.1 not applicable here",),
        )
    ratio = float(sum_mc_nmm) / float(sum_mb_nmm)
    ok = ratio >= STRONG_COLUMN_RATIO - _TOL
    notes = []
    if not ok:
        notes.append(
            "sum Mc / sum Mb "
            + _r(ratio, 3)
            + " below the Cl 7.2.1 requirement of "
            + _r(STRONG_COLUMN_RATIO, 2)
            + "; flagged for a hand joint check, section not resized"
        )
    return StrongColumn(
        ratio=ratio,
        required=STRONG_COLUMN_RATIO,
        ok=ok,
        applicable=True,
        flag_only=True,
        notes=tuple(notes),
    )


@clause(
    code=CODE,
    ref="7.6.1",
    title="Length of the special confining zone",
    symbol="lo",
    units="mm",
    latex=r"l_o=\max\left(D_{larger},\ \frac{h_{c}}{6},\ 450\right)",
)
def cl_7_6_1__confining_length(depth_larger_mm: float, clear_height_mm: float) -> float:
    """Confining length measured from each joint face, Cl 7.6.1.

    `depth_larger_mm` is the larger lateral dimension of the column at the
    section where flexural yielding occurs, `clear_height_mm` its clear height.
    """
    if depth_larger_mm <= 0.0:
        raise ValueError("depth_larger_mm must be positive")
    if clear_height_mm <= 0.0:
        raise ValueError("clear_height_mm must be positive")
    return max(
        float(depth_larger_mm),
        float(clear_height_mm) / CONFINING_LO_HEIGHT_DIVISOR,
        CONFINING_LO_MIN_MM,
    )


@clause(
    code=CODE,
    ref="7.6.2",
    title="Pitch of special confining hoops",
    symbol="s",
    units="mm",
    latex=r"s\le\min\left(\frac{b_{min}}{4},\ 6d_{b},\ 100\right),\quad s\ge 75",
)
def cl_7_6_2__confining_spacing(min_dim_mm: float, dia_long_min_mm: float) -> ConfiningSpacing:
    """Confining hoop pitch, Cl 7.6.2.

    The union of the 1993 and 2016 editions is taken deliberately: the 6 bar
    diameter bound and the 100 mm cap together, with the 75 mm floor below
    which the pitch need not go. That is the tighter of the two editions at
    every point and is disclosed in `notes`.
    """
    if min_dim_mm <= 0.0:
        raise ValueError("min_dim_mm must be positive")
    if dia_long_min_mm <= 0.0:
        raise ValueError("dia_long_min_mm must be positive")
    limit_min_dim = float(min_dim_mm) / CONFINING_SPACING_MIN_DIM_DIVISOR
    limit_bar = CONFINING_SPACING_BAR_MULTIPLE * float(dia_long_min_mm)
    candidates = (
        (limit_min_dim, "least_dimension"),
        (limit_bar, "bar_diameter"),
        (CONFINING_SPACING_CAP_MM, "cap_100"),
    )
    computed, governs = min(candidates, key=lambda pair: (pair[0], pair[1]))
    floor_applied = computed < CONFINING_SPACING_FLOOR_MM
    spacing = CONFINING_SPACING_FLOOR_MM if floor_applied else computed
    notes = [
        "pitch bounds read as the union of the 1993 and 2016 editions"
        " (least dimension / 4, 6 bar diameters, 100 mm cap, 75 mm floor), the conservative reading"
    ]
    if floor_applied:
        notes.append("pitch raised from " + _mm(computed) + " to the " + _mm(CONFINING_SPACING_FLOOR_MM) + " floor")
        governs = "floor_75"
    return ConfiningSpacing(
        spacing_mm=spacing,
        limit_min_dim_mm=limit_min_dim,
        limit_bar_mm=limit_bar,
        cap_mm=CONFINING_SPACING_CAP_MM,
        floor_applied=floor_applied,
        governs=governs,
        notes=tuple(notes),
    )


@clause(
    code=CODE,
    ref="7.6.3",
    title="Area of a rectangular confining hoop leg",
    symbol="Ash",
    units="mm2",
    latex=r"A_{sh}=\max\left(0.18\,s\,h\frac{f_{ck}}{f_y}\left(\frac{A_g}{A_k}-1\right),\ 0.05\,s\,h\frac{f_{ck}}{f_y}\right)",
)
def cl_7_6_3__ash_rectangular(
    s_mm: float,
    h_core_mm: float,
    fck_mpa: float,
    fy_mpa: float,
    ag_mm2: float,
    ak_mm2: float,
) -> ConfiningSteel:
    """Confining steel area per hoop leg, Cl 7.6.3, both terms.

    `h_core_mm` is the longer dimension of the hoop leg measured to its outer
    face, `ag_mm2` the gross column area and `ak_mm2` the confined core area to
    the outside of the hoop. The area ratio term governs slender cores; on
    large sections it falls away and the 0.05 floor term takes over, which is
    why both are always evaluated and reported. A leg longer than 300 mm needs
    a crosstie, flagged here and detailed by the caller.
    """
    if s_mm <= 0.0 or h_core_mm <= 0.0:
        raise ValueError("s_mm and h_core_mm must be positive")
    if fck_mpa <= 0.0 or fy_mpa <= 0.0:
        raise ValueError("fck_mpa and fy_mpa must be positive")
    if ak_mm2 <= 0.0:
        raise ValueError("ak_mm2 must be positive")
    if ag_mm2 <= 0.0:
        raise ValueError("ag_mm2 must be positive")
    base = float(s_mm) * float(h_core_mm) * float(fck_mpa) / float(fy_mpa)
    gross_over_core = float(ag_mm2) / float(ak_mm2)
    notes = []
    if gross_over_core < 1.0:
        notes.append(
            "core area exceeds the gross area (Ag/Ak " + _r(gross_over_core, 3) + "); area ratio term taken as zero"
        )
        gross_over_core = 1.0
    area_ratio_term = ASH_AREA_RATIO_COEFF * base * (gross_over_core - 1.0)
    floor_term = ASH_FLOOR_COEFF * base
    if area_ratio_term >= floor_term:
        ash, governs = area_ratio_term, "area_ratio"
    else:
        ash, governs = floor_term, "floor"
        notes.append("0.05 floor term governs; the area ratio term gives " + _r(area_ratio_term, 1) + " mm2")
    crossties = float(h_core_mm) > CONFINING_MAX_HOOP_LEG_MM + _TOL
    if crossties:
        notes.append(
            "hoop leg " + _mm(h_core_mm) + " exceeds " + _mm(CONFINING_MAX_HOOP_LEG_MM) + "; crossties required"
        )
    return ConfiningSteel(
        ash_mm2=ash,
        ash_area_ratio_mm2=area_ratio_term,
        ash_floor_mm2=floor_term,
        governs=governs,
        crossties_required=crossties,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Cl 9: beam column joints
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="9",
    title="Beam column joint",
    symbol="joint",
    units="-",
)
def cl_9__joint_check() -> JointCheck:
    """Joint shear and confinement are not designed in this version.

    Cl 9 needs the joint shear demand from the beam bar forces on both faces
    plus the confinement supplied by the framing members. Rather than emit a
    silent pass, the joint is returned flagged: the designer attaches the
    referral `joint_check_manual` to the DesignResult and the report shows it.
    """
    return JointCheck(
        designed=False,
        marker="FLAGGED_NOT_DESIGNED",
        referral="joint_check_manual",
        notes=("IS 13920 Cl 9 joint shear and confinement are flagged for a hand check, not designed here",),
    )


# ---------------------------------------------------------------------------
# applicability
# ---------------------------------------------------------------------------


def normalize_zone(zone: Any) -> str:
    """Seismic zone as a roman numeral string; accepts 'iii', 'III', 3 or '3'."""
    key = str(zone).strip().upper()
    if key not in _ZONE_ALIASES:
        raise ValueError("unknown seismic zone: " + repr(zone) + " (expected I, II, III, IV or V)")
    return _ZONE_ALIASES[key]


def normalize_frame(frame: Any) -> str:
    """Frame ductility class as 'OMRF' or 'SMRF'."""
    key = str(frame).strip().upper()
    if key not in _FRAMES:
        raise ValueError("unknown frame class: " + repr(frame) + " (expected OMRF or SMRF)")
    return key


@clause(
    code=CODE,
    ref="1.1.1",
    title="Applicability of ductile detailing",
    symbol="is13920",
    units="-",
)
def is13920_applies(zone: Any, frame: Any) -> bool:
    """True when the ductile detailing overlay is required.

    A special moment resisting frame is detailed to IS 13920 in every zone,
    because the response reduction factor claimed for it in IS 1893 is earned
    by that detailing. Otherwise the overlay applies in zones III, IV and V.
    An ordinary frame in zone III is therefore covered as well, which is the
    conservative reading recorded in the spec critic pass (finding 41).
    """
    zone_key = normalize_zone(zone)
    frame_key = normalize_frame(frame)
    if SMRF_ANY_ZONE and frame_key == "SMRF":
        return True
    return zone_key in DUCTILE_ZONES


# ---------------------------------------------------------------------------
# spec aliases: the names the submodule specification uses, bound to the
# clause numbered callables above so a caller written against either spells
# reaches the same function object (and the same single registry entry).
# ---------------------------------------------------------------------------

cl_7_6__confining = cl_7_6_3__ash_rectangular
cl_7_6__lo = cl_7_6_1__confining_length
cl_7_6__spacing = cl_7_6_2__confining_spacing


# ---------------------------------------------------------------------------
# formatting helpers (messages only, never arithmetic)
# ---------------------------------------------------------------------------


def _r(value: float, places: int) -> str:
    return ("%." + str(places) + "f") % float(value)


def _mm(value: float) -> str:
    return _r(value, 1) + " mm"
