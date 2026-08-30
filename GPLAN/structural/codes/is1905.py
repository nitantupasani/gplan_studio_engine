"""IS 1905:1987 clause callables for unreinforced masonry.

One clause is one pure function decorated with `@clause`, so a call lands in the
trace sink whenever `codes.trace.trace_into` is open and costs one ContextVar
read otherwise. Every callable returns a plain float, a plain bool, or a small
NamedTuple; none of them returns a (value, ref) tuple and none of them writes to
a model. The numbers all come from `data/is1905_tables.yaml`, which is loaded
once and validated for shape and monotonicity at import.

The compressive chain reads, in order:

    fb  = basic_compressive_stress(unit_strength_mpa, mortar_grade)   Table 8
    heff = effective_height(H, top, bottom)                           Table 4
    leff = effective_length(L, ends)                                  Table 5
    teff = effective_thickness(t, ...)                                Table 6
    SR  = slenderness_ratio(heff, leff, teff)                         Cl 5.2
          check_max_slenderness(SR, storeys, mortar_grade)            Table 7
    ks  = stress_reduction_factor(SR, e_over_t).ks                    Table 9
    ka  = area_reduction_factor(A_m2)                                 Cl 5.4.1.2
    kp  = shape_modification_factor(h_over_w, unit_strength_mpa)      Table 10
    fc  = permissible_compressive_stress(fb, ks, ka, kp)              Cl 5.4.1

Units are SI throughout: lengths and areas in metres, stresses in MPa (which is
N/mm2, so a per-metre wall load w in kN/m over a thickness t in m gives a stress
of w / (1000 t) MPa).
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ..data._loader import load_yaml, require_keys
from .trace import clause

CODE = "IS1905:1987"

TABLE_NAME = "is1905_tables"

MORTAR_GRADES = ("H1", "H2", "M1", "M2", "M3", "L1", "L2")

#: The leanest mortar the printed permissible-shear clause covers. The print
#: reads "in case of walls built in mortar not leaner than Grade M1 ... the
#: permissible shear stress ... shall not exceed fs = 0.1 + fd/6"; a grade
#: leaner than this floor gets no shear value from the clause at all. The
#: sibling tension clause carries the same restriction as `permitted_mortars`
#: in the YAML block.
SHEAR_MORTAR_FLOOR = "M1"


def shear_mortar_permitted(mortar_grade: str) -> bool:
    """True where the printed shear clause covers this mortar grade.

    `MORTAR_GRADES` is ordered strongest first, so "leaner than the floor"
    is a larger index than the floor's.
    """
    grade = _normalize_grade(mortar_grade)
    return MORTAR_GRADES.index(grade) <= MORTAR_GRADES.index(SHEAR_MORTAR_FLOOR)

RESTRAINTS = ("full", "lateral", "free")

END_CONDITIONS = ("continuous", "cross_wall", "free")

BENDING_PLANES = ("normal_to_bed", "parallel_to_bed")

TENSION_POLICIES = ("no_tension", "allow_flexural_tension")

_ETA = 1e-9


class CodeInputError(ValueError):
    """An input a code table cannot answer: outside the grid, or not a listed key.

    Raised rather than extrapolated. A caller that meets one converts it into a
    disclosure on the model, it is never swallowed.
    """


class StressReduction(NamedTuple):
    """Table 9 result. `ks` is None when the table has no value for the pair."""

    ks: Optional[float]
    ok: bool
    slenderness_ratio: float
    e_over_t: float
    reason: str


# ---------------------------------------------------------------------------
# table access and validation
# ---------------------------------------------------------------------------


def tables() -> Dict[str, Any]:
    """The parsed IS 1905 table file. Shared cache entry, treat as read-only."""
    return load_yaml(TABLE_NAME)


def _table(key: str) -> Dict[str, Any]:
    block = tables().get(key)
    if not isinstance(block, dict):
        raise ValueError(TABLE_NAME + " is missing the table block: " + key)
    return block


def _floats(values: Sequence[Any]) -> List[float]:
    return [float(v) for v in values]


def _is_strictly_increasing(values: Sequence[float]) -> bool:
    return all(values[i] < values[i + 1] for i in range(len(values) - 1))


def _is_non_increasing(values: Sequence[Optional[float]]) -> bool:
    present = [v for v in values if v is not None]
    return all(present[i] >= present[i + 1] - _ETA for i in range(len(present) - 1))


def _is_non_decreasing(values: Sequence[Optional[float]]) -> bool:
    present = [v for v in values if v is not None]
    return all(present[i] <= present[i + 1] + _ETA for i in range(len(present) - 1))


def _validate_tables() -> None:
    """Shape and monotonicity asserts, run once at import so a bad edit is loud."""
    require_keys(
        tables(),
        [
            "source",
            "edition",
            "mortar_grades",
            "table_4_effective_height",
            "table_5_effective_length",
            "table_6_effective_thickness",
            "table_7_max_slenderness",
            "table_8_basic_compressive_stress",
            "table_9_stress_reduction_factor",
            "table_10_shape_modification_factor",
            "cl_5_4_1_2_area_reduction",
            "cl_5_4_2_shear",
            "cl_5_4_3_tension",
        ],
        TABLE_NAME,
    )

    grades = _table("mortar_grades")
    if tuple(grades["order"]) != MORTAR_GRADES:
        raise ValueError(TABLE_NAME + " mortar_grades.order must be " + ", ".join(MORTAR_GRADES))

    t8 = _table("table_8_basic_compressive_stress")
    strengths = _floats(t8["unit_strength_mpa"])
    if not _is_strictly_increasing(strengths):
        raise ValueError(TABLE_NAME + " table 8 unit strengths must strictly increase")
    if tuple(t8["mortar_order"]) != MORTAR_GRADES:
        raise ValueError(TABLE_NAME + " table 8 mortar_order must be " + ", ".join(MORTAR_GRADES))
    columns = []  # type: List[List[float]]
    for grade in MORTAR_GRADES:
        row = _floats(t8["values"][grade])
        if len(row) != len(strengths):
            raise ValueError(TABLE_NAME + " table 8 row " + grade + " has the wrong width")
        if not _is_non_decreasing(row):
            raise ValueError(TABLE_NAME + " table 8 row " + grade + " must not fall as the unit gets stronger")
        columns.append(row)
    for index in range(len(strengths)):
        down_the_column = [columns[g][index] for g in range(len(MORTAR_GRADES))]
        if not _is_non_increasing(down_the_column):
            raise ValueError(TABLE_NAME + " table 8 column " + str(strengths[index]) + " must not rise as the mortar gets weaker")

    t9 = _table("table_9_stress_reduction_factor")
    ratios = _floats(t9["slenderness_ratio"])
    if not _is_strictly_increasing(ratios):
        raise ValueError(TABLE_NAME + " table 9 slenderness ratios must strictly increase")
    denominators = [int(d) for d in t9["e_over_t_denominator"]]
    if denominators[0] != 0 or not _is_strictly_increasing([-float(d) for d in denominators[1:]]):
        raise ValueError(TABLE_NAME + " table 9 e/t denominators must start at 0 and then fall")
    rows = t9["values"]
    if len(rows) != len(ratios):
        raise ValueError(TABLE_NAME + " table 9 has the wrong number of rows")
    for r, row in enumerate(rows):
        if len(row) != len(denominators):
            raise ValueError(TABLE_NAME + " table 9 row " + str(ratios[r]) + " has the wrong width")
        if not _is_non_increasing([None if v is None else float(v) for v in row]):
            raise ValueError(TABLE_NAME + " table 9 row " + str(ratios[r]) + " must not rise with eccentricity")
    for c in range(len(denominators)):
        column = [None if rows[r][c] is None else float(rows[r][c]) for r in range(len(ratios))]
        if not _is_non_increasing(column):
            raise ValueError(TABLE_NAME + " table 9 column " + str(denominators[c]) + " must not rise with slenderness")

    t6 = _table("table_6_effective_thickness")
    spacings = _floats(t6["spacing_over_width"])
    thickness_ratios = _floats(t6["thickness_ratio"])
    if not _is_strictly_increasing(spacings) or not _is_strictly_increasing(thickness_ratios):
        raise ValueError(TABLE_NAME + " table 6 axes must strictly increase")
    if len(t6["values"]) != len(thickness_ratios):
        raise ValueError(TABLE_NAME + " table 6 has the wrong number of rows")
    for row in t6["values"]:
        if len(row) != len(spacings):
            raise ValueError(TABLE_NAME + " table 6 row has the wrong width")
        if not _is_non_increasing(_floats(row)):
            raise ValueError(TABLE_NAME + " table 6 stiffening must not rise with pier spacing")

    t10 = _table("table_10_shape_modification_factor")
    shapes = _floats(t10["height_over_width"])
    kps = _floats(t10["values"])
    if not _is_strictly_increasing(shapes) or len(shapes) != len(kps):
        raise ValueError(TABLE_NAME + " table 10 axis and values disagree")
    if not _is_non_decreasing(kps):
        raise ValueError(TABLE_NAME + " table 10 factors must not fall as the unit gets taller")

    t7 = _table("table_7_max_slenderness")
    families = t7["mortar_family"]
    listed = sorted([str(g) for family in sorted(families) for g in families[family]])
    if listed != sorted(MORTAR_GRADES):
        raise ValueError(TABLE_NAME + " table 7 must place every mortar grade in exactly one family")


_validate_tables()


# ---------------------------------------------------------------------------
# interpolation helpers
# ---------------------------------------------------------------------------


def _bracket(axis: Sequence[float], value: float) -> Tuple[int, int, float]:
    """(lower index, upper index, fraction) for `value` on a rising axis, clamped."""
    if value <= axis[0]:
        return (0, 0, 0.0)
    if value >= axis[-1]:
        last = len(axis) - 1
        return (last, last, 0.0)
    hi = 0
    for index in range(1, len(axis)):
        if value <= axis[index]:
            hi = index
            break
    lo = hi - 1
    width = axis[hi] - axis[lo]
    return (lo, hi, 0.0 if width <= 0 else (value - axis[lo]) / width)


def _lerp(low: float, high: float, fraction: float) -> float:
    return low + (high - low) * fraction


def _normalize_grade(mortar_grade: Any) -> str:
    grade = str(mortar_grade).strip().upper()
    if grade not in MORTAR_GRADES:
        raise CodeInputError(
            "unknown mortar grade " + repr(mortar_grade) + "; IS 1905 Table 1 lists " + ", ".join(MORTAR_GRADES)
        )
    return grade


def _normalize_choice(value: Any, allowed: Sequence[str], what: str) -> str:
    token = str(value).strip().lower()
    if token not in allowed:
        raise CodeInputError("unknown " + what + " " + repr(value) + "; expected one of " + ", ".join(allowed))
    return token


# ---------------------------------------------------------------------------
# Table 8: basic compressive stress
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 8",
    title="Basic compressive stress for masonry",
    symbol="fb",
    units="MPa",
    latex=r"f_b = \mathrm{Table\ 8}(f_u, \text{mortar})",
)
def basic_compressive_stress(unit_strength_mpa: float, mortar_grade: str) -> float:
    """Basic compressive stress fb in MPa for a unit strength and mortar grade.

    Linear interpolation on unit strength only, as the note under Table 8 allows;
    mortar grade is categorical. A unit weaker than the first column (3.5 MPa) or
    a grade outside Table 1 raises CodeInputError. A unit stronger than the last
    column is clamped to it, never extrapolated.
    """
    grade = _normalize_grade(mortar_grade)
    table = _table("table_8_basic_compressive_stress")
    strengths = _floats(table["unit_strength_mpa"])
    strength = float(unit_strength_mpa)
    if strength < strengths[0] - _ETA:
        raise CodeInputError(
            "unit strength "
            + repr(unit_strength_mpa)
            + " MPa is below the first column of IS 1905 Table 8 ("
            + str(strengths[0])
            + " MPa); the table cannot be extrapolated downwards"
        )
    row = _floats(table["values"][grade])
    lo, hi, fraction = _bracket(strengths, strength)
    return _lerp(row[lo], row[hi], fraction)


# ---------------------------------------------------------------------------
# Tables 4, 5, 6 and Cl 5.2: slenderness inputs
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 4",
    title="Effective height of a wall",
    symbol="h_eff",
    units="m",
    latex=r"h_{eff} = k_h H",
)
def effective_height(height_m: float, top_restraint: str, bottom_restraint: str) -> float:
    """Effective height in metres from the clear storey height and its restraints.

    Restraint vocabulary: "full" (lateral and rotational, an RC slab bearing on
    the wall), "lateral" (lateral only), "free" (a parapet top). A wall free at
    the bottom is not a Table 4 case and raises CodeInputError.
    """
    top = _normalize_choice(top_restraint, RESTRAINTS, "top restraint")
    bottom = _normalize_choice(bottom_restraint, RESTRAINTS, "bottom restraint")
    if bottom == "free":
        raise CodeInputError("IS 1905 Table 4 has no case for a wall free at the bottom")
    key = "+".join(sorted([top, bottom]))
    factors = _table("table_4_effective_height")["values"]
    if key not in factors:
        raise CodeInputError("IS 1905 Table 4 has no case for restraints " + top + " over " + bottom)
    return float(factors[key]) * float(height_m)


@clause(
    code=CODE,
    ref="Table 5",
    title="Effective length of a wall",
    symbol="l_eff",
    units="m",
    latex=r"l_{eff} = k_l L",
)
def effective_length(length_m: float, end_conditions: Sequence[str]) -> float:
    """Effective length in metres from the wall length and its two end conditions.

    End vocabulary: "continuous" (the wall runs on past the support), "cross_wall"
    (supported by a cross wall and stopping there), "free". A wall free at both
    ends has no length restraint at all and raises CodeInputError; the caller
    then passes leff = None to `slenderness_ratio` and the height term governs.
    """
    if len(end_conditions) != 2:
        raise CodeInputError("end_conditions must name both ends of the wall")
    ends = sorted(_normalize_choice(end, END_CONDITIONS, "end condition") for end in end_conditions)
    key = "+".join(ends)
    factors = _table("table_5_effective_length")["values"]
    if key not in factors:
        raise CodeInputError(
            "IS 1905 Table 5 has no case for ends " + " and ".join(ends) + "; a wall free at both ends has no effective length"
        )
    return float(factors[key]) * float(length_m)


@clause(
    code=CODE,
    ref="Table 6",
    title="Effective thickness of a wall",
    symbol="t_eff",
    units="m",
    latex=r"t_{eff} = k_t\,t",
)
def effective_thickness(
    thickness_m: float,
    pier_spacing_m: Optional[float] = None,
    pier_width_m: Optional[float] = None,
    pier_depth_m: Optional[float] = None,
    cavity_leaves_m: Optional[Sequence[float]] = None,
) -> float:
    """Effective thickness in metres: solid, stiffened by piers, or cavity.

    A solid wall is its own thickness. A wall stiffened by piers or cross walls
    is the thickness times the Table 6 stiffening coefficient, bilinear over
    (pier spacing / pier width) and (pier thickness / wall thickness), clamped
    at both ends of both axes. A cavity wall takes the greater of 2/3 of the sum
    of the leaves and the thicker leaf alone; each leaf is still checked alone
    by the design layer.
    """
    thickness = float(thickness_m)
    if thickness <= 0.0:
        raise CodeInputError("wall thickness must be positive, got " + repr(thickness_m))

    if cavity_leaves_m is not None:
        leaves = _floats(cavity_leaves_m)
        if len(leaves) != 2 or min(leaves) <= 0.0:
            raise CodeInputError("cavity_leaves_m must be two positive leaf thicknesses in metres")
        return max((2.0 / 3.0) * (leaves[0] + leaves[1]), max(leaves))

    pier_args = (pier_spacing_m, pier_width_m, pier_depth_m)
    if all(arg is None for arg in pier_args):
        return thickness
    if any(arg is None for arg in pier_args):
        raise CodeInputError("stiffening needs pier_spacing_m, pier_width_m and pier_depth_m together")
    spacing = float(pier_spacing_m)
    width = float(pier_width_m)
    depth = float(pier_depth_m)
    if spacing <= 0.0 or width <= 0.0 or depth <= 0.0:
        raise CodeInputError("pier spacing, width and depth must all be positive metres")

    table = _table("table_6_effective_thickness")
    spacing_axis = _floats(table["spacing_over_width"])
    ratio_axis = _floats(table["thickness_ratio"])
    grid = [_floats(row) for row in table["values"]]
    col_lo, col_hi, col_f = _bracket(spacing_axis, spacing / width)
    row_lo, row_hi, row_f = _bracket(ratio_axis, depth / thickness)
    low = _lerp(grid[row_lo][col_lo], grid[row_lo][col_hi], col_f)
    high = _lerp(grid[row_hi][col_lo], grid[row_hi][col_hi], col_f)
    return thickness * _lerp(low, high, row_f)


@clause(
    code=CODE,
    ref="Cl 5.2",
    title="Slenderness ratio of a wall",
    symbol="SR",
    units="",
    latex=r"SR = \min\left(\frac{h_{eff}}{t_{eff}}, \frac{l_{eff}}{t_{eff}}\right)",
)
def slenderness_ratio(heff_m: float, leff_m: Optional[float], teff_m: float) -> float:
    """Lesser of the height and length terms. Pass leff_m=None for the height alone."""
    teff = float(teff_m)
    if teff <= 0.0:
        raise CodeInputError("effective thickness must be positive, got " + repr(teff_m))
    ratio = float(heff_m) / teff
    if leff_m is not None:
        ratio = min(ratio, float(leff_m) / teff)
    return ratio


@clause(
    code=CODE,
    ref="Table 7",
    title="Maximum slenderness ratio for a load bearing wall",
    symbol="SR_max",
    units="",
)
def check_max_slenderness(slenderness: float, storeys: int, mortar_grade: str) -> bool:
    """True while the wall is inside the Cl 5.2 cap: 27 on cement, 20 on lime mortars.

    The storey count is carried into the trace. This transcription of Table 7
    does not reduce the cap with storey count and no such reduction is invented
    here; see the storey_note in the YAML.
    """
    grade = _normalize_grade(mortar_grade)
    table = _table("table_7_max_slenderness")
    family = None
    for name in sorted(table["mortar_family"]):
        if grade in table["mortar_family"][name]:
            family = name
            break
    if family is None:
        raise CodeInputError("mortar grade " + grade + " is in no IS 1905 Table 7 family")
    if int(storeys) < 1:
        raise CodeInputError("storeys must be at least 1, got " + repr(storeys))
    return float(slenderness) <= float(table["values"][family]) + _ETA


@clause(
    code=CODE,
    ref="Table 7 limit",
    title="Maximum slenderness ratio permitted by mortar family",
    symbol="SR_lim",
    units="",
)
def max_slenderness(mortar_grade: str) -> float:
    """The cap itself, for a report line or a prescription that has to hit it."""
    grade = _normalize_grade(mortar_grade)
    table = _table("table_7_max_slenderness")
    for name in sorted(table["mortar_family"]):
        if grade in table["mortar_family"][name]:
            return float(table["values"][name])
    raise CodeInputError("mortar grade " + grade + " is in no IS 1905 Table 7 family")


# ---------------------------------------------------------------------------
# Table 9 and Cl 5.4: permissible stresses
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 9",
    title="Stress reduction factor for slenderness ratio and eccentricity",
    symbol="ks",
    units="",
    latex=r"k_s = \mathrm{Table\ 9}(SR, e/t)",
)
def stress_reduction_factor(slenderness: float, e_over_t: float) -> StressReduction:
    """Bilinear Table 9 lookup, returning ks with the reason when there is none.

    A slenderness below the first row (6) reads the first row. An eccentricity
    ratio above the last column (1/3) is outside the table: ks is None with
    ok=False, which the design layer turns into a FAIL, never into a guess. The
    printed table also leaves the tall-and-eccentric corner blank; a lookup that
    would have to read one of those blanks returns ks=None the same way.
    """
    table = _table("table_9_stress_reduction_factor")
    ratios = _floats(table["slenderness_ratio"])
    denominators = [int(d) for d in table["e_over_t_denominator"]]
    columns = [0.0 if d == 0 else 1.0 / float(d) for d in denominators]
    grid = table["values"]

    ratio = float(slenderness)
    eccentricity = float(e_over_t)
    if eccentricity < -_ETA:
        raise CodeInputError("e/t must not be negative, got " + repr(e_over_t))
    if eccentricity > columns[-1] + 1e-6:
        return StressReduction(
            ks=None,
            ok=False,
            slenderness_ratio=ratio,
            e_over_t=eccentricity,
            reason=(
                "e/t = "
                + ("%.4f" % eccentricity)
                + " exceeds the last column of IS 1905 Table 9 (1/3); the wall is outside the table"
            ),
        )
    if ratio > ratios[-1] + _ETA:
        return StressReduction(
            ks=None,
            ok=False,
            slenderness_ratio=ratio,
            e_over_t=eccentricity,
            reason=(
                "slenderness ratio "
                + ("%.3f" % ratio)
                + " exceeds the last row of IS 1905 Table 9 ("
                + str(ratios[-1])
                + "); the wall is outside the table"
            ),
        )

    row_lo, row_hi, row_f = _bracket(ratios, ratio)
    col_lo, col_hi, col_f = _bracket(columns, min(eccentricity, columns[-1]))
    corners = [
        grid[row_lo][col_lo],
        grid[row_lo][col_hi],
        grid[row_hi][col_lo],
        grid[row_hi][col_hi],
    ]
    if any(corner is None for corner in corners):
        return StressReduction(
            ks=None,
            ok=False,
            slenderness_ratio=ratio,
            e_over_t=eccentricity,
            reason=(
                "IS 1905 Table 9 leaves slenderness "
                + ("%.3f" % ratio)
                + " with e/t "
                + ("%.4f" % eccentricity)
                + " blank; that combination is not a permitted one"
            ),
        )
    low = _lerp(float(corners[0]), float(corners[1]), col_f)
    high = _lerp(float(corners[2]), float(corners[3]), col_f)
    return StressReduction(
        ks=_lerp(low, high, row_f),
        ok=True,
        slenderness_ratio=ratio,
        e_over_t=eccentricity,
        reason="",
    )


@clause(
    code=CODE,
    ref="Cl 5.4.1.2",
    title="Area reduction factor for a small loaded area",
    symbol="ka",
    units="",
    latex=r"k_a = 0.7 + 1.5A",
)
def area_reduction_factor(area_m2: float) -> float:
    """ka = 0.7 + 1.5A below 0.2 m2 of loaded plan area, 1.0 at or above it."""
    table = _table("cl_5_4_1_2_area_reduction")
    area = float(area_m2)
    if area < 0.0:
        raise CodeInputError("loaded area must not be negative, got " + repr(area_m2))
    if area >= float(table["threshold_m2"]) - _ETA:
        return 1.0
    return float(table["intercept"]) + float(table["slope_per_m2"]) * area


@clause(
    code=CODE,
    ref="Table 10",
    title="Shape modification factor for masonry units",
    symbol="kp",
    units="",
)
def shape_modification_factor(unit_h_over_w: float = 0.75, unit_strength_mpa: Optional[float] = None) -> float:
    """kp from the height to width ratio of the unit, interpolated and clamped.

    A ratio of 0.75 or less is the Table 8 reference unit, so kp = 1.0, which is
    the default and covers the standard modular brick this engine assumes. The
    unit strength is accepted and carried into the trace; this transcription of
    Table 10 has no strength axis, see the strength_axis note in the YAML.
    """
    table = _table("table_10_shape_modification_factor")
    shapes = _floats(table["height_over_width"])
    values = _floats(table["values"])
    ratio = float(unit_h_over_w)
    if ratio <= 0.0:
        raise CodeInputError("unit height to width ratio must be positive, got " + repr(unit_h_over_w))
    lo, hi, fraction = _bracket(shapes, ratio)
    return _lerp(values[lo], values[hi], fraction)


@clause(
    code=CODE,
    ref="Cl 5.4.1",
    title="Permissible compressive stress in masonry",
    symbol="fc",
    units="MPa",
    latex=r"f_c = f_b\,k_s\,k_a\,k_p",
)
def permissible_compressive_stress(fb_mpa: float, ks: float, ka: float, kp: float) -> float:
    """fc = fb * ks * ka * kp, in MPa. Every factor must already be a number.

    `stress_reduction_factor` can return ks=None when the wall is off Table 9;
    that is a failure the design layer reports, not something to be papered over
    with a default here, so a None ks raises.
    """
    if ks is None:
        raise CodeInputError("ks is None: the wall is outside IS 1905 Table 9 and has no permissible stress")
    for name, value in (("fb_mpa", fb_mpa), ("ks", ks), ("ka", ka), ("kp", kp)):
        if float(value) < 0.0:
            raise CodeInputError(name + " must not be negative, got " + repr(value))
    return float(fb_mpa) * float(ks) * float(ka) * float(kp)


@clause(
    code=CODE,
    ref="Cl 5.4.2",
    title="Permissible shear stress in masonry",
    symbol="fs",
    units="MPa",
    latex=r"f_s = \min\left(0.1 + \frac{f_d}{6},\ 0.5\right)",
)
def permissible_shear(fd_mpa: float, mortar_grade: str) -> float:
    """fs = 0.1 + fd/6 MPa, capped at 0.5 MPa, for mortar not leaner than M1.

    fd is the compressive stress from DEAD load only at the level considered, so
    the caller must not hand it a combined dead plus live stress.

    The printed clause restricts the formula to "walls built in mortar not
    leaner than Grade M1", the same restriction the sibling tension clause
    carries in `permitted_mortars`, so a grade leaner than
    `SHEAR_MORTAR_FLOOR` returns 0.0: the clause offers such a wall no
    permissible shear, and the design layer discloses that rather than
    letting the formula pass it.
    """
    table = _table("cl_5_4_2_shear")
    fd = float(fd_mpa)
    if fd < 0.0:
        raise CodeInputError("fd must not be negative, got " + repr(fd_mpa))
    if not shear_mortar_permitted(mortar_grade):
        return 0.0
    return min(float(table["intercept_mpa"]) + fd / float(table["fd_divisor"]), float(table["cap_mpa"]))


@clause(
    code=CODE,
    ref="Cl 5.4.3",
    title="Permissible tensile stress in masonry",
    symbol="ft",
    units="MPa",
)
def permissible_tension(bending_plane: str, mortar_grade: str, policy: str = "no_tension") -> float:
    """Permissible flexural tension in MPa under the stated policy.

    The engine default is `no_tension`: ft = 0.0, and any net tension is a
    failure carrying a prescription (add vertical reinforcement, or raise the
    dead load). `allow_flexural_tension` returns the Cl 5.4.3 values, 0.07 MPa
    normal to the bed joints and 0.14 MPa parallel to them, and only for the
    stronger mortars; a weaker mortar still returns 0.0. That policy is for a
    laterally loaded panel, never for a primary gravity wall, and the design
    layer discloses it whenever it is switched on.
    """
    table = _table("cl_5_4_3_tension")
    plane = _normalize_choice(bending_plane, BENDING_PLANES, "bending plane")
    grade = _normalize_grade(mortar_grade)
    chosen = _normalize_choice(policy, TENSION_POLICIES, "tension policy")
    if chosen == "no_tension":
        return 0.0
    if grade not in [str(g) for g in table["permitted_mortars"]]:
        return 0.0
    return float(table["flexural_values_mpa"][plane])
