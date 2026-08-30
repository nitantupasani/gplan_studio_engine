"""IS 456:2000 clause callables: one clause, one pure function, one trace record.

Units are the code's own, never the model's: forces N, moments N.mm, lengths mm,
areas mm2, stresses MPa (N/mm2), spans m only where the clause itself is written
in metres. Every argument carries its unit suffix. The SI boundary (metres, kN,
kNm) is crossed once by the design layer, never in here.

Every public callable is `@clause`-decorated, so it is listed in
`trace.CLAUSE_REGISTRY` for the report bibliography and appends a TraceEntry
whenever a designer has opened a sink with `trace_into(entries)`.

Table data lives in `data/is456_tables.yaml` and `data/is456_figs.yaml`, read
once at import and frozen into module dicts. Digitized figures and print
transcriptions carry `verify: "print"` in the YAML: they are vetted defaults,
not verified reads, and the report says so.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Dict, NamedTuple, Optional, Sequence, Tuple

from ..data._loader import load_yaml, require_keys
from .trace import clause

CODE = "IS456:2000"

#: Modulus of elasticity of reinforcement, IS 456 Clause 5.6.3.
ES_MPA = 200000.0

#: Design yield stress factor, IS 456 Clause 38.1 (partial safety factor 1.15).
GAMMA_S_FACTOR = 0.87

#: Design concrete stress factor 0.67/1.5, IS 456 Clause 38.1.
CONCRETE_DESIGN_FACTOR = 0.446


# ---------------------------------------------------------------------------
# table loading (once, frozen)
# ---------------------------------------------------------------------------

_TABLES = load_yaml("is456_tables")
_FIGS = load_yaml("is456_figs")

require_keys(
    _TABLES,
    (
        "annex_d_table_26",
        "annex_d_table_27",
        "basic_span_depth",
        "k_solid_slab",
        "sp16_table_f_fsc",
        "table_5_min_grade",
        "table_12_moment_coefficients",
        "table_15_clear_spacing",
        "table_16_nominal_cover",
        "table_16a_fire_cover",
        "table_19_tau_c",
        "table_20_tau_c_max",
        "tau_bd",
        "two_way_span_depth",
    ),
    "is456_tables.yaml",
)
require_keys(_FIGS, ("fig_4_mf_tension", "fig_5_mf_compression", "fig_6_mf_flanged"), "is456_figs.yaml")


def _floats(values: Sequence[Any]) -> Tuple[float, ...]:
    """A YAML sequence as a tuple of floats."""
    return tuple(float(v) for v in values)


def _opt_floats(values: Sequence[Any]) -> Tuple[Optional[float], ...]:
    """A YAML sequence as floats, keeping YAML null as None."""
    return tuple(None if v is None else float(v) for v in values)


def _num_keyed(raw: Dict[Any, Any]) -> Dict[float, Tuple[float, ...]]:
    """A YAML mapping keyed by a number (grade, fy, fs) with float keys."""
    return {float(key): _floats(row) for key, row in raw.items()}


def _word(value: Any) -> str:
    """Vocabulary words normalised: lower case, spaces and hyphens to underscore."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


_T5 = _TABLES["table_5_min_grade"]
_MIN_GRADE = MappingProxyType({_word(k): float(v) for k, v in _T5["values"].items()})

_T16 = _TABLES["table_16_nominal_cover"]
_NOMINAL_COVER = MappingProxyType({_word(k): float(v) for k, v in _T16["values"].items()})

_T16A = _TABLES["table_16a_fire_cover"]
_FIRE_RATINGS = _floats(_T16A["ratings_h"])
_FIRE_COVER = MappingProxyType({_word(k): _floats(v) for k, v in _T16A["members"].items()})
_FIRE_ALIASES = MappingProxyType({_word(k): _word(v) for k, v in _T16A.get("aliases", {}).items()})

_T15 = _TABLES["table_15_clear_spacing"]
_T15_PCT = _floats(_T15["redistribution_pct"])
_T15_ROWS = _num_keyed(_T15["values"])
_T15_FY = tuple(sorted(_T15_ROWS))

_T19 = _TABLES["table_19_tau_c"]
_T19_PT_MIN = float(_T19["pt_min"])
_T19_PT_MAX = float(_T19["pt_max"])
_T19_FCK_MIN = float(_T19["fck_min"])
_T19_FCK_MAX = float(_T19["fck_max"])
_T19_PT = _floats(_T19["pt"])
_T19_GRADES = MappingProxyType(_num_keyed(_T19["grades"]))

_T20 = _TABLES["table_20_tau_c_max"]
_T20_GRADES = _floats(_T20["grades"])
_T20_VALUES = _floats(_T20["values"])

_TAU_BD = _TABLES["tau_bd"]
_TAU_BD_GRADES = _floats(_TAU_BD["grades"])
_TAU_BD_VALUES = _floats(_TAU_BD["values"])
_TAU_BD_DEFORMED = float(_TAU_BD["deformed_factor"])
_TAU_BD_COMPRESSION = float(_TAU_BD["compression_factor"])

_KSLAB = _TABLES["k_solid_slab"]
_KSLAB_D = _floats(_KSLAB["overall_depth_mm"])
_KSLAB_V = _floats(_KSLAB["values"])

_TF = _TABLES["sp16_table_f_fsc"]
_TF_DPRIME = _floats(_TF["dprime_over_d"])
_TF_ROWS = _num_keyed(_TF["values"])
_TF_FY = tuple(sorted(_TF_ROWS))

_T26 = _TABLES["annex_d_table_26"]
_T26_RATIOS = _floats(_T26["ratios"])
_T26_CASES = MappingProxyType(
    {
        int(key): MappingProxyType(
            {
                "name": _word(block["name"]),
                "alpha_x_neg": _opt_floats(block["alpha_x_neg"]),
                "alpha_x_pos": _opt_floats(block["alpha_x_pos"]),
                "alpha_y_neg": None if block["alpha_y_neg"] is None else float(block["alpha_y_neg"]),
                "alpha_y_pos": None if block["alpha_y_pos"] is None else float(block["alpha_y_pos"]),
            }
        )
        for key, block in _T26["cases"].items()
    }
)
_T26_NAMES = MappingProxyType({str(block["name"]): key for key, block in _T26_CASES.items()})

_T27 = _TABLES["annex_d_table_27"]
_T27_RATIOS = _floats(_T27["ratios"])
_T27_AX = _floats(_T27["alpha_x"])
_T27_AY = _floats(_T27["alpha_y"])

_BASIC = _TABLES["basic_span_depth"]
_BASIC_LD = MappingProxyType({_word(k): float(v) for k, v in _BASIC["values"].items()})
_BASIC_ALIASES = MappingProxyType({_word(k): _word(v) for k, v in _BASIC.get("aliases", {}).items()})

_TWO_WAY = _TABLES["two_way_span_depth"]
_TWO_WAY_LD = MappingProxyType({_word(k): float(v) for k, v in _TWO_WAY["values"].items()})
_TWO_WAY_ALIASES = MappingProxyType({_word(k): _word(v) for k, v in _TWO_WAY.get("aliases", {}).items()})
_TWO_WAY_HYSD = float(_TWO_WAY["hysd_factor"])
_TWO_WAY_MAX_SPAN_M = float(_TWO_WAY["max_short_span_m"])
_TWO_WAY_MAX_LL_KPA = float(_TWO_WAY["max_imposed_kpa"])

_F4 = _FIGS["fig_4_mf_tension"]
_F4_PT = _floats(_F4["pt"])
_F4_FS = _floats(_F4["fs_mpa"])
_F4_ROWS = tuple(_floats(_F4["mf"][int(fs)]) for fs in _F4_FS)

_F5 = _FIGS["fig_5_mf_compression"]
_F5_PC = _floats(_F5["pc"])
_F5_MF = _floats(_F5["mf"])

_F6 = _FIGS["fig_6_mf_flanged"]
_F6_X = _floats(_F6["bw_over_bf"])
_F6_MF = _floats(_F6["mf"])


# ---------------------------------------------------------------------------
# interpolation helpers (plain, untraced: they are arithmetic, not clauses)
# ---------------------------------------------------------------------------


def _bracket(axis: Sequence[float], value: float) -> Tuple[int, int, float]:
    """Indices either side of `value` on a sorted axis plus the fraction between.

    Flat outside the axis: the printed curves stop at their axis limits and the
    callables that use this say so in their docstring.
    """
    last = len(axis) - 1
    if value <= axis[0]:
        return 0, 0, 0.0
    if value >= axis[last]:
        return last, last, 0.0
    for i in range(1, last + 1):
        if value <= axis[i]:
            span = axis[i] - axis[i - 1]
            frac = 0.0 if span == 0.0 else (value - axis[i - 1]) / span
            return i - 1, i, frac
    return last, last, 0.0


def _interp(axis: Sequence[float], values: Sequence[float], value: float) -> float:
    """Linear interpolation on a sorted axis, flat outside it."""
    lower, upper, frac = _bracket(axis, value)
    low = float(values[lower])
    return low + (float(values[upper]) - low) * frac


def _bilinear(
    x_axis: Sequence[float],
    y_axis: Sequence[float],
    rows: Sequence[Sequence[float]],
    x_value: float,
    y_value: float,
) -> float:
    """Bilinear interpolation; `rows[i]` is the curve for `y_axis[i]` over `x_axis`."""
    lower, upper, frac = _bracket(y_axis, y_value)
    low = _interp(x_axis, rows[lower], x_value)
    return low + (_interp(x_axis, rows[upper], x_value) - low) * frac


def _step_down(axis: Sequence[float], values: Sequence[float], value: float) -> float:
    """Value of the highest tabulated step at or below `value` (first step below it)."""
    out = float(values[0])
    for i in range(len(axis)):
        if value >= axis[i]:
            out = float(values[i])
    return out


def _step_up_index(axis: Sequence[float], value: float) -> int:
    """Index of the lowest tabulated step at or above `value` (last step above it)."""
    for i in range(len(axis)):
        if value <= axis[i]:
            return i
    return len(axis) - 1


def _resolve(word: Any, table: Any, aliases: Any, what: str) -> str:
    """A vocabulary word resolved through its alias map, or a listing ValueError."""
    key = _word(word)
    key = aliases.get(key, key)
    if key not in table:
        raise ValueError(what + " unknown: " + repr(word) + "; known: " + ", ".join(sorted(table)))
    return key


def _fy_row(rows: Dict[float, Tuple[float, ...]], keys: Sequence[float], fy_mpa: float) -> Tuple[float, ...]:
    """Row for `fy_mpa`, interpolated between tabulated grades, flat outside."""
    fy = float(fy_mpa)
    if fy in rows:
        return rows[fy]
    lower, upper, frac = _bracket(keys, fy)
    low = rows[keys[lower]]
    high = rows[keys[upper]]
    return tuple(low[i] + (high[i] - low[i]) * frac for i in range(len(low)))


# ---------------------------------------------------------------------------
# materials and general
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="6.2.3.1",
    title="Modulus of elasticity of concrete",
    symbol="Ec",
    units="MPa",
    latex=r"E_c = 5000\sqrt{f_{ck}}",
)
def cl_6_2_3_1__ec(fck_mpa: float) -> float:
    """Short-term static modulus of elasticity of concrete, MPa."""
    if fck_mpa <= 0.0:
        raise ValueError("fck_mpa must be positive, got " + repr(fck_mpa))
    return 5000.0 * math.sqrt(float(fck_mpa))


@clause(code=CODE, ref="Table 5", title="Minimum grade of concrete for exposure", symbol="fck,min", units="MPa")
def table_5__min_grade(exposure: str) -> float:
    """Minimum characteristic strength for reinforced concrete at an exposure."""
    return _MIN_GRADE[_resolve(exposure, _MIN_GRADE, {}, "exposure")]


@clause(code=CODE, ref="Table 16", title="Nominal cover for durability", symbol="c_nom", units="mm")
def table_16__nominal_cover(exposure: str) -> float:
    """Nominal cover to all reinforcement to meet durability, mm."""
    return _NOMINAL_COVER[_resolve(exposure, _NOMINAL_COVER, {}, "exposure")]


@clause(code=CODE, ref="Table 16A", title="Nominal cover for fire resistance", symbol="c_fire", units="mm")
def table_16a__fire_cover(member: str, rating_h: float) -> float:
    """Nominal cover for a period of fire resistance, mm.

    A rating between tabulated periods steps UP to the next tabulated period
    (more cover), and a bare member word resolves to the simply supported row.
    """
    key = _resolve(member, _FIRE_COVER, _FIRE_ALIASES, "member")
    return float(_FIRE_COVER[key][_step_up_index(_FIRE_RATINGS, float(rating_h))])


@clause(code=CODE, ref="26.4.2.2", title="Cover for concrete cast against earth", symbol="c_footing", units="mm")
def cl_26_4_2_2__footing_cover() -> float:
    """Minimum cover for footings, 50 mm."""
    return 50.0


# ---------------------------------------------------------------------------
# flexure, Annex G
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="G-1.1",
    title="Limiting neutral axis depth",
    symbol="xu,max/d",
    units="",
    latex=r"\frac{x_{u,max}}{d}=\frac{0.0035}{0.0055+\frac{0.87f_y}{E_s}}",
)
def annex_g__xu_max_over_d(fy_mpa: float) -> float:
    """Limiting xu/d from strain compatibility: 0.53 Fe250, 0.48 Fe415, 0.46 Fe500."""
    if fy_mpa <= 0.0:
        raise ValueError("fy_mpa must be positive, got " + repr(fy_mpa))
    return 0.0035 / (0.0055 + GAMMA_S_FACTOR * float(fy_mpa) / ES_MPA)


@clause(
    code=CODE,
    ref="G-1.1(b)",
    title="Limiting moment of resistance, singly reinforced rectangular section",
    symbol="Mu,lim",
    units="N.mm",
    latex=r"M_{u,lim}=0.36\frac{x_{u,max}}{d}\left(1-0.42\frac{x_{u,max}}{d}\right)bd^2f_{ck}",
)
def annex_g__mu_lim(b_mm: float, d_mm: float, fck_mpa: float, fy_mpa: float) -> float:
    """Limiting moment of resistance of a rectangular section, N.mm."""
    ratio = annex_g__xu_max_over_d(fy_mpa)
    return 0.36 * ratio * (1.0 - 0.42 * ratio) * float(b_mm) * float(d_mm) * float(d_mm) * float(fck_mpa)


@clause(
    code=CODE,
    ref="G-1.1(a)",
    title="Tension steel for a singly reinforced section",
    symbol="Ast",
    units="mm2",
    latex=r"A_{st}=0.5\frac{f_{ck}}{f_y}\left(1-\sqrt{1-\frac{4.6M_u}{f_{ck}bd^2}}\right)bd",
)
def annex_g__ast_singly(mu_nmm: float, b_mm: float, d_mm: float, fck_mpa: float, fy_mpa: float) -> float:
    """Tension steel from the closed-form quadratic root, mm2.

    Raises ValueError when the demand is beyond the singly reinforced range, so
    a caller never gets a silently complex root: check `annex_g__mu_lim` first.
    """
    b = float(b_mm)
    d = float(d_mm)
    fck = float(fck_mpa)
    if b <= 0.0 or d <= 0.0 or fck <= 0.0 or fy_mpa <= 0.0:
        raise ValueError("section and material values must be positive")
    disc = 1.0 - 4.6 * float(mu_nmm) / (fck * b * d * d)
    if disc < 0.0:
        raise ValueError("mu_nmm beyond the singly reinforced range for this section; use annex_g__doubly")
    return 0.5 * (fck / float(fy_mpa)) * (1.0 - math.sqrt(disc)) * b * d


@clause(
    code=CODE,
    ref="SP 16 Table F",
    title="Stress in compression reinforcement (SP 16 design aid to IS 456)",
    symbol="fsc",
    units="MPa",
)
def sp16_table_f__fsc(fy_mpa: float, dprime_over_d: float) -> float:
    """Compression steel stress at the limiting neutral axis, MPa.

    Piecewise linear on d'/d over the tabulated {0.05, 0.10, 0.15, 0.20} and flat
    outside it; between tabulated fy grades the rows are interpolated.
    """
    row = _fy_row(_TF_ROWS, _TF_FY, fy_mpa)
    return _interp(_TF_DPRIME, row, float(dprime_over_d))


class DoublyResult(NamedTuple):
    """Split of a doubly reinforced section into its balanced and excess parts."""

    ast1_mm2: float
    ast2_mm2: float
    asc_mm2: float
    fsc_mpa: float
    mu_lim_nmm: float


@clause(
    code=CODE,
    ref="G-1.2",
    title="Doubly reinforced rectangular section",
    symbol="Ast,Asc",
    units="mm2",
    latex=r"A_{sc}=\frac{M_u-M_{u,lim}}{(f_{sc}-0.446f_{ck})(d-d')}",
)
def annex_g__doubly(
    mu_nmm: float,
    b_mm: float,
    d_mm: float,
    dprime_mm: float,
    fck_mpa: float,
    fy_mpa: float,
) -> DoublyResult:
    """Balanced part Ast1, excess part Ast2 and compression steel Asc, mm2.

    Total tension steel is ast1_mm2 + ast2_mm2. When the demand is at or below
    Mu,lim the excess parts come back zero and Ast1 carries the whole moment.
    """
    d = float(d_mm)
    dprime = float(dprime_mm)
    fck = float(fck_mpa)
    fy = float(fy_mpa)
    if d <= dprime:
        raise ValueError("dprime_mm must be less than d_mm")
    mu = float(mu_nmm)
    mu_lim = annex_g__mu_lim(b_mm, d, fck, fy)
    ratio = annex_g__xu_max_over_d(fy)
    lever = d - 0.42 * ratio * d
    if mu <= mu_lim:
        return DoublyResult(
            ast1_mm2=mu / (GAMMA_S_FACTOR * fy * lever),
            ast2_mm2=0.0,
            asc_mm2=0.0,
            fsc_mpa=sp16_table_f__fsc(fy, dprime / d),
            mu_lim_nmm=mu_lim,
        )
    fsc = sp16_table_f__fsc(fy, dprime / d)
    net = fsc - CONCRETE_DESIGN_FACTOR * fck
    if net <= 0.0:
        raise ValueError("compression steel stress does not exceed the displaced concrete stress")
    mu2 = mu - mu_lim
    asc = mu2 / (net * (d - dprime))
    return DoublyResult(
        ast1_mm2=mu_lim / (GAMMA_S_FACTOR * fy * lever),
        ast2_mm2=asc * net / (GAMMA_S_FACTOR * fy),
        asc_mm2=asc,
        fsc_mpa=fsc,
        mu_lim_nmm=mu_lim,
    )


# ---------------------------------------------------------------------------
# shear, Clause 40
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="40.1",
    title="Nominal shear stress",
    symbol="tau_v",
    units="MPa",
    latex=r"\tau_v=\frac{V_u}{bd}",
)
def cl_40_1__tau_v(vu_n: float, b_mm: float, d_mm: float) -> float:
    """Nominal shear stress on a rectangular section, MPa."""
    if b_mm <= 0.0 or d_mm <= 0.0:
        raise ValueError("b_mm and d_mm must be positive")
    return float(vu_n) / (float(b_mm) * float(d_mm))


@clause(
    code=CODE,
    ref="Table 19",
    title="Design shear strength of concrete",
    symbol="tau_c",
    units="MPa",
    latex=r"\tau_c=\frac{0.85\sqrt{0.8f_{ck}}(\sqrt{1+5\beta}-1)}{6\beta},\ \beta=\max\left(\frac{0.8f_{ck}}{6.89p_t},1\right)",
)
def table_19__tau_c(pt: float, fck_mpa: float) -> float:
    """Design shear strength for a tension steel percentage, MPa.

    The SP 24 closed form that generates Table 19. pt is clamped to the tabulated
    [0.15, 3.0] and fck to [15, 40] ("M40 and above" is the last column), which is
    what the printed table does at its own edges.
    """
    pt_used = min(max(float(pt), _T19_PT_MIN), _T19_PT_MAX)
    fck_used = min(max(float(fck_mpa), _T19_FCK_MIN), _T19_FCK_MAX)
    beta = max(0.8 * fck_used / (6.89 * pt_used), 1.0)
    return 0.85 * math.sqrt(0.8 * fck_used) * (math.sqrt(1.0 + 5.0 * beta) - 1.0) / (6.0 * beta)


@clause(code=CODE, ref="Table 20", title="Maximum shear stress", symbol="tau_c,max", units="MPa")
def table_20__tau_c_max(fck_mpa: float) -> float:
    """Cap on nominal shear stress with shear reinforcement, MPa.

    Steps down to the tabulated grade at or below fck; M40 and above take 4.0.
    """
    return _step_down(_T20_GRADES, _T20_VALUES, float(fck_mpa))


@clause(code=CODE, ref="40.2.1.1", title="Shear strength enhancement for solid slabs", symbol="k", units="")
def cl_40_2_1_1__k_solid_slab(overall_depth_mm: float) -> float:
    """Factor k on tau_c for solid slabs: 1.30 at 150 mm or less, 1.00 at 300 mm or more."""
    return _interp(_KSLAB_D, _KSLAB_V, float(overall_depth_mm))


@clause(
    code=CODE,
    ref="40.4",
    title="Vertical stirrups for shear",
    symbol="Asv/sv",
    units="mm2/mm",
    latex=r"\frac{A_{sv}}{s_v}=\frac{V_{us}}{0.87f_yd}",
)
def cl_40_4__vertical_stirrups(vus_n: float, fy_mpa: float, d_mm: float) -> float:
    """Required stirrup area per unit length for the shear carried by steel, mm2/mm."""
    if fy_mpa <= 0.0 or d_mm <= 0.0:
        raise ValueError("fy_mpa and d_mm must be positive")
    return max(float(vus_n), 0.0) / (GAMMA_S_FACTOR * float(fy_mpa) * float(d_mm))


@clause(
    code=CODE,
    ref="26.5.1.6",
    title="Minimum shear reinforcement",
    symbol="Asv/sv,min",
    units="mm2/mm",
    latex=r"\frac{A_{sv}}{s_v}\ge\frac{0.4b}{0.87f_y}",
)
def cl_26_5_1_6__min_stirrups(b_mm: float, fy_mpa: float) -> float:
    """Minimum stirrup area per unit length, mm2/mm; fy is capped at 415 MPa."""
    fy = min(float(fy_mpa), 415.0)
    return 0.4 * float(b_mm) / (GAMMA_S_FACTOR * fy)


@clause(code=CODE, ref="26.5.1.5", title="Maximum spacing of shear reinforcement", symbol="sv,max", units="mm")
def cl_26_5_1_5__max_stirrup_spacing(d_mm: float) -> float:
    """Maximum stirrup spacing along a beam, the lesser of 0.75d and 300 mm."""
    return min(0.75 * float(d_mm), 300.0)


# ---------------------------------------------------------------------------
# torsion, Clause 41
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="41.3.1",
    title="Equivalent shear for torsion",
    symbol="Ve",
    units="N",
    latex=r"V_e=V_u+1.6\frac{T_u}{b}",
)
def cl_41_3_1__equiv_shear(vu_n: float, tu_nmm: float, b_mm: float) -> float:
    """Equivalent shear combining shear and torsion, N."""
    if b_mm <= 0.0:
        raise ValueError("b_mm must be positive")
    return float(vu_n) + 1.6 * float(tu_nmm) / float(b_mm)


class EquivalentMoment(NamedTuple):
    """Torsional moment folded into an equivalent bending pair."""

    mt_nmm: float
    me1_nmm: float
    me2_nmm: float


@clause(
    code=CODE,
    ref="41.4.2",
    title="Equivalent bending moment for torsion",
    symbol="Me1,Me2",
    units="N.mm",
    latex=r"M_t=T_u\frac{1+D/b}{1.7},\ M_{e1}=M_u+M_t,\ M_{e2}=M_t-M_u",
)
def cl_41_4_2__equiv_moment(mu_nmm: float, tu_nmm: float, b_mm: float, overall_depth_mm: float) -> EquivalentMoment:
    """Equivalent moments Me1 (tension face) and Me2 (opposite face, only when Mt > Mu)."""
    if b_mm <= 0.0:
        raise ValueError("b_mm must be positive")
    mt = float(tu_nmm) * (1.0 + float(overall_depth_mm) / float(b_mm)) / 1.7
    mu = float(mu_nmm)
    return EquivalentMoment(mt_nmm=mt, me1_nmm=mu + mt, me2_nmm=max(mt - mu, 0.0))


class TorsionStirrups(NamedTuple):
    """Transverse steel for combined shear and torsion, with its Clause 41.4.3 floor."""

    asv_mm2: float
    asv_floor_mm2: float
    asv_req_mm2: float


@clause(
    code=CODE,
    ref="41.4.3",
    title="Transverse reinforcement for torsion",
    symbol="Asv",
    units="mm2",
    latex=r"A_{sv}=\frac{T_us_v}{b_1d_10.87f_y}+\frac{V_us_v}{2.5d_10.87f_y}",
)
def cl_41_4_3__transverse(
    tu_nmm: float,
    vu_n: float,
    b1_mm: float,
    d1_mm: float,
    fy_mpa: float,
    sv_mm: float,
    b_mm: float = 0.0,
    tau_ve_mpa: float = 0.0,
    tau_c_mpa: float = 0.0,
) -> TorsionStirrups:
    """Two-legged stirrup area at spacing sv, mm2, and the (tau_ve - tau_c) floor.

    b1 and d1 are the centre-to-centre dimensions of the corner bars. The floor
    is inert when the caller leaves b_mm and the two stresses at zero.
    """
    if b1_mm <= 0.0 or d1_mm <= 0.0 or fy_mpa <= 0.0:
        raise ValueError("b1_mm, d1_mm and fy_mpa must be positive")
    fyd = GAMMA_S_FACTOR * float(fy_mpa)
    sv = float(sv_mm)
    asv = float(tu_nmm) * sv / (float(b1_mm) * float(d1_mm) * fyd) + float(vu_n) * sv / (2.5 * float(d1_mm) * fyd)
    floor = max(float(tau_ve_mpa) - float(tau_c_mpa), 0.0) * float(b_mm) * sv / fyd
    return TorsionStirrups(asv_mm2=asv, asv_floor_mm2=floor, asv_req_mm2=max(asv, floor))


# ---------------------------------------------------------------------------
# serviceability, Clause 23.2.1
# ---------------------------------------------------------------------------


@clause(code=CODE, ref="23.2.1(a)", title="Basic span to effective depth ratio", symbol="(l/d)basic", units="")
def cl_23_2_1__basic_ld(support: str) -> float:
    """Basic l/d for spans up to 10 m: cantilever 7, simply supported 20, continuous 26."""
    return _BASIC_LD[_resolve(support, _BASIC_LD, _BASIC_ALIASES, "support")]


@clause(
    code=CODE,
    ref="23.2.1 Fig 4 note",
    title="Service stress in tension reinforcement",
    symbol="fs",
    units="MPa",
    latex=r"f_s=0.58f_y\frac{A_{st,req}}{A_{st,prov}}",
)
def cl_23_2_1__fs(fy_mpa: float, ast_req_mm2: float, ast_prov_mm2: float) -> float:
    """Service stress used to enter Fig 4, MPa."""
    if ast_prov_mm2 <= 0.0:
        raise ValueError("ast_prov_mm2 must be positive")
    return 0.58 * float(fy_mpa) * float(ast_req_mm2) / float(ast_prov_mm2)


@clause(code=CODE, ref="Fig 4", title="Modification factor for tension reinforcement", symbol="MF_t", units="")
def fig_4__mf_tension(fs_mpa: float, pt: float) -> float:
    """Fig 4 modification factor, bilinear on the digitized grid.

    Flat outside the plotted axes: fs below 120 or above 290 MPa and pt above
    3.0 percent read their edge curve, which is what the printed figure shows.
    """
    return _bilinear(_F4_PT, _F4_FS, _F4_ROWS, float(pt), float(fs_mpa))


@clause(code=CODE, ref="Fig 5", title="Modification factor for compression reinforcement", symbol="MF_c", units="")
def fig_5__mf_compression(pc: float) -> float:
    """Fig 5 modification factor for compression steel, linear on the digitized grid."""
    return _interp(_F5_PC, _F5_MF, float(pc))


@clause(code=CODE, ref="Fig 6", title="Reduction factor for flanged beams", symbol="MF_f", units="")
def fig_6__mf_flanged(bw_over_bf: float) -> float:
    """Fig 6 reduction factor on web to flange width, linear on the digitized grid."""
    return _interp(_F6_X, _F6_MF, float(bw_over_bf))


@clause(code=CODE, ref="23.2.1(c)", title="Long span factor", symbol="k_span", units="")
def cl_23_2_1_c__long_span_factor(span_m: float) -> float:
    """Factor 10/span for spans over 10 m, 1.0 otherwise.

    Not applicable to cantilevers: over 10 m the code asks for a deflection
    calculation, which the caller must disclose rather than take this factor.
    """
    span = float(span_m)
    if span <= 10.0:
        return 1.0
    return 10.0 / span


# ---------------------------------------------------------------------------
# detailing, Clause 26
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="26.5.1.1(a)",
    title="Minimum tension reinforcement in a beam",
    symbol="As,min",
    units="mm2",
    latex=r"\frac{A_s}{bd}=\frac{0.85}{f_y}",
)
def cl_26_5_1_1__min_tension_steel(b_mm: float, d_mm: float, fy_mpa: float) -> float:
    """Minimum tension steel in a beam, mm2."""
    if fy_mpa <= 0.0:
        raise ValueError("fy_mpa must be positive")
    return 0.85 * float(b_mm) * float(d_mm) / float(fy_mpa)


@clause(code=CODE, ref="26.5.1.1(b)", title="Maximum tension reinforcement in a beam", symbol="As,max", units="mm2")
def cl_26_5_1_1b__max_steel(b_mm: float, overall_depth_mm: float) -> float:
    """Maximum tension (or compression) steel in a beam, 0.04 bD, mm2."""
    return 0.04 * float(b_mm) * float(overall_depth_mm)


class SideFaceSteel(NamedTuple):
    """Side face reinforcement requirement for a deep web."""

    required: bool
    area_mm2: float
    area_per_face_mm2: float
    max_spacing_mm: float


@clause(code=CODE, ref="26.5.1.3", title="Side face reinforcement", symbol="As,side", units="mm2")
def cl_26_5_1_3__side_face(bw_mm: float, overall_depth_mm: float, torsion: bool = False) -> SideFaceSteel:
    """0.1 percent of the web area split over two faces, at most 300 mm or bw apart.

    Required when the web depth exceeds 750 mm. The caller raises `torsion` when
    the section is designed for torsion, where the trigger drops to D over 450 mm.
    """
    bw = float(bw_mm)
    depth = float(overall_depth_mm)
    required = depth > 750.0 or (bool(torsion) and depth > 450.0)
    area = 0.001 * bw * depth
    return SideFaceSteel(
        required=required,
        area_mm2=area,
        area_per_face_mm2=0.5 * area,
        max_spacing_mm=min(300.0, bw),
    )


@clause(code=CODE, ref="26.3.2", title="Minimum distance between main bars", symbol="s_min", units="mm")
def cl_26_3_2__min_bar_spacing(dia_mm: float, agg_mm: float = 20.0) -> float:
    """Minimum clear horizontal distance between parallel main bars, mm."""
    return max(float(dia_mm), float(agg_mm) + 5.0)


@clause(code=CODE, ref="Table 15", title="Clear distance between bars for crack control", symbol="s_clear", units="mm")
def table_15__clear_spacing(fy_mpa: float, redistribution_pct: float = 0.0) -> float:
    """Maximum clear distance between tension bars in a beam, mm.

    Interpolated between the tabulated fy rows and along the redistribution axis,
    flat outside the tabulated range.
    """
    row = _fy_row(_T15_ROWS, _T15_FY, fy_mpa)
    return _interp(_T15_PCT, row, float(redistribution_pct))


@clause(code=CODE, ref="26.3.3", title="Maximum distance between tension bars", symbol="s_max", units="mm")
def cl_26_3_3__max_spacing_flexure(member: str, d_mm: float, fy_mpa: float = 415.0) -> float:
    """Maximum bar spacing, mm: slab main 3d or 300, distribution 5d or 450, beam Table 15."""
    key = _word(member)
    if key in ("slab", "slab_main", "main"):
        return min(3.0 * float(d_mm), 300.0)
    if key in ("slab_distribution", "distribution", "secondary"):
        return min(5.0 * float(d_mm), 450.0)
    if key == "beam":
        return table_15__clear_spacing(fy_mpa)
    raise ValueError("member unknown: " + repr(member) + "; known: beam, slab_main, slab_distribution")


@clause(code=CODE, ref="26.2.1.1", title="Design bond stress", symbol="tau_bd", units="MPa")
def cl_26_2_1_1__tau_bd(fck_mpa: float, deformed: bool = True, compression: bool = False) -> float:
    """Design bond stress, MPa: table value times 1.6 for deformed bars and 1.25 in compression."""
    value = _step_down(_TAU_BD_GRADES, _TAU_BD_VALUES, float(fck_mpa))
    if deformed:
        value *= _TAU_BD_DEFORMED
    if compression:
        value *= _TAU_BD_COMPRESSION
    return value


@clause(
    code=CODE,
    ref="26.2.1",
    title="Development length of a bar",
    symbol="Ld",
    units="mm",
    latex=r"L_d=\frac{\phi\,0.87f_y}{4\tau_{bd}}",
)
def cl_26_2_1__ld(dia_mm: float, fy_mpa: float, fck_mpa: float, deformed: bool = True, compression: bool = False) -> float:
    """Development length, mm. M20 with Fe415 deformed bars in tension gives 47 diameters."""
    tau_bd = cl_26_2_1_1__tau_bd(fck_mpa, deformed=deformed, compression=compression)
    return float(dia_mm) * GAMMA_S_FACTOR * float(fy_mpa) / (4.0 * tau_bd)


class AnchorageCheck(NamedTuple):
    """Clause 26.2.3.3 anchorage available at a simple support against Ld."""

    available_mm: float
    required_mm: float
    ratio: float
    ok: bool


@clause(
    code=CODE,
    ref="26.2.3.3",
    title="Anchorage of positive steel at a simple support",
    symbol="1.3M1/V+Lo",
    units="mm",
    latex=r"L_d\le\frac{1.3M_1}{V}+L_o",
)
def cl_26_2_3_3__simple_support_anchorage(m1_nmm: float, v_n: float, lo_mm: float, ld_mm: float) -> AnchorageCheck:
    """Available anchorage 1.3 M1/V + Lo against the development length, mm.

    M1 is the moment of resistance of the steel actually continued past the
    support; V is the shear at the support; Lo is the anchorage beyond the
    centre of the support.
    """
    if v_n <= 0.0:
        raise ValueError("v_n must be positive")
    available = 1.3 * float(m1_nmm) / float(v_n) + float(lo_mm)
    required = float(ld_mm)
    ratio = available / required if required > 0.0 else float("inf")
    return AnchorageCheck(available_mm=available, required_mm=required, ratio=ratio, ok=available >= required)


# ---------------------------------------------------------------------------
# columns, Clauses 25, 39 and 26.5.3
# ---------------------------------------------------------------------------


class Slenderness(NamedTuple):
    """Slenderness ratios about both axes and the short-column verdict."""

    lambda_x: float
    lambda_y: float
    short: bool


@clause(code=CODE, ref="25.1.2", title="Slenderness of a compression member", symbol="lex/D, ley/b", units="")
def cl_25_1_2__slenderness(lex_mm: float, ley_mm: float, overall_depth_mm: float, b_mm: float) -> Slenderness:
    """Slenderness ratios; a column is short when both are below 12."""
    if overall_depth_mm <= 0.0 or b_mm <= 0.0:
        raise ValueError("overall_depth_mm and b_mm must be positive")
    lam_x = float(lex_mm) / float(overall_depth_mm)
    lam_y = float(ley_mm) / float(b_mm)
    return Slenderness(lambda_x=lam_x, lambda_y=lam_y, short=lam_x < 12.0 and lam_y < 12.0)


@clause(code=CODE, ref="25.3.1", title="Maximum unsupported length of a column", symbol="l_max", units="mm")
def cl_25_3__max_unsupported(b_mm: float) -> float:
    """Unsupported length limit, 60 times the least lateral dimension, mm."""
    return 60.0 * float(b_mm)


@clause(
    code=CODE,
    ref="25.4",
    title="Minimum eccentricity",
    symbol="e_min",
    units="mm",
    latex=r"e_{min}=\max\left(\frac{l}{500}+\frac{D}{30},\,20\right)",
)
def cl_25_4__e_min(l_mm: float, dim_mm: float) -> float:
    """Minimum eccentricity in one plane, mm; never less than 20 mm."""
    return max(float(l_mm) / 500.0 + float(dim_mm) / 30.0, 20.0)


@clause(
    code=CODE,
    ref="39.3",
    title="Axial load capacity of a short column with helical or lateral ties",
    symbol="Pu",
    units="N",
    latex=r"P_u=0.4f_{ck}A_c+0.67f_yA_{sc}",
)
def cl_39_3__pu_axial(fck_mpa: float, fy_mpa: float, ac_mm2: float, asc_mm2: float) -> float:
    """Design axial capacity for members with minimum eccentricity only, N."""
    return 0.4 * float(fck_mpa) * float(ac_mm2) + 0.67 * float(fy_mpa) * float(asc_mm2)


@clause(
    code=CODE,
    ref="39.6 Puz",
    title="Pure axial capacity Puz",
    symbol="Puz",
    units="N",
    latex=r"P_{uz}=0.45f_{ck}A_c+0.75f_yA_{sc}",
)
def cl_39_6__puz(fck_mpa: float, fy_mpa: float, ac_mm2: float, asc_mm2: float) -> float:
    """Squash load used in the biaxial interaction, N."""
    return 0.45 * float(fck_mpa) * float(ac_mm2) + 0.75 * float(fy_mpa) * float(asc_mm2)


@clause(code=CODE, ref="39.6 alpha_n", title="Biaxial interaction exponent", symbol="alpha_n", units="")
def cl_39_6__alpha_n(pu_n: float, puz_n: float) -> float:
    """Exponent alpha_n, 1.0 at Pu/Puz of 0.2 rising linearly to 2.0 at 0.8."""
    if puz_n <= 0.0:
        raise ValueError("puz_n must be positive")
    ratio = float(pu_n) / float(puz_n)
    if ratio <= 0.2:
        return 1.0
    if ratio >= 0.8:
        return 2.0
    return 1.0 + (ratio - 0.2) / 0.6


@clause(
    code=CODE,
    ref="39.6",
    title="Biaxial bending interaction",
    symbol="sum(Mu/Mu1)^alpha_n",
    units="",
    latex=r"\left(\frac{M_{ux}}{M_{ux1}}\right)^{\alpha_n}+\left(\frac{M_{uy}}{M_{uy1}}\right)^{\alpha_n}\le1.0",
)
def cl_39_6__biaxial_ratio(
    mux_nmm: float,
    muy_nmm: float,
    mux1_nmm: float,
    muy1_nmm: float,
    alpha_n: float,
) -> float:
    """Interaction sum; the section passes when it does not exceed 1.0."""
    if mux1_nmm <= 0.0 or muy1_nmm <= 0.0:
        raise ValueError("uniaxial capacities mux1_nmm and muy1_nmm must be positive")
    x = abs(float(mux_nmm)) / float(mux1_nmm)
    y = abs(float(muy_nmm)) / float(muy1_nmm)
    return x ** float(alpha_n) + y ** float(alpha_n)


@clause(
    code=CODE,
    ref="39.7.1",
    title="Additional moment for a slender column",
    symbol="Ma",
    units="N.mm",
    latex=r"M_a=\frac{P_uD}{2000}\left(\frac{l_e}{D}\right)^2",
)
def cl_39_7_1__additional_moment(pu_n: float, dim_mm: float, le_mm: float) -> float:
    """Additional moment from slenderness in one plane, N.mm.

    `dim_mm` is the section depth in the plane of bending and `le_mm` the
    effective length in that plane.
    """
    dim = float(dim_mm)
    if dim <= 0.0:
        raise ValueError("dim_mm must be positive")
    return float(pu_n) * dim * (float(le_mm) / dim) ** 2 / 2000.0


@clause(
    code=CODE,
    ref="39.7.1.1",
    title="Reduction factor on the additional moment",
    symbol="k",
    units="",
    latex=r"k=\frac{P_{uz}-P_u}{P_{uz}-P_b}\le1.0",
)
def cl_39_7_1_1__k(pu_n: float, puz_n: float, pb_n: float) -> float:
    """Reduction factor k, clamped to [0, 1]."""
    denominator = float(puz_n) - float(pb_n)
    if denominator <= 0.0:
        raise ValueError("puz_n must exceed pb_n")
    return min(max((float(puz_n) - float(pu_n)) / denominator, 0.0), 1.0)


class LongSteelLimits(NamedTuple):
    """Clause 26.5.3.1 longitudinal steel envelope for a column."""

    asc_min_mm2: float
    asc_max_mm2: float
    asc_lap_warn_mm2: float
    min_bars: int
    min_dia_mm: float
    max_periphery_spacing_mm: float


@clause(code=CODE, ref="26.5.3.1", title="Longitudinal reinforcement limits in a column", symbol="Asc", units="mm2")
def cl_26_5_3_1__long_steel_limits(ag_mm2: float) -> LongSteelLimits:
    """0.8 to 6 percent of the gross area, with the 4 percent lap-congestion warning level."""
    ag = float(ag_mm2)
    if ag <= 0.0:
        raise ValueError("ag_mm2 must be positive")
    return LongSteelLimits(
        asc_min_mm2=0.008 * ag,
        asc_max_mm2=0.06 * ag,
        asc_lap_warn_mm2=0.04 * ag,
        min_bars=4,
        min_dia_mm=12.0,
        max_periphery_spacing_mm=300.0,
    )


class TieSpec(NamedTuple):
    """Lateral tie diameter and pitch."""

    dia_mm: float
    pitch_mm: float


@clause(code=CODE, ref="26.5.3.2", title="Lateral ties in a column", symbol="tie", units="mm")
def cl_26_5_3_2__ties(dia_long_mm: float, least_dim_mm: float, dia_long_min_mm: Optional[float] = None) -> TieSpec:
    """Tie diameter (at least a quarter of the largest bar, never below 6 mm) and pitch.

    Pitch is the least of the least lateral dimension, 16 times the SMALLEST
    longitudinal bar and 300 mm; `dia_long_min_mm` defaults to `dia_long_mm`
    when every longitudinal bar is the same size.
    """
    largest = float(dia_long_mm)
    smallest = largest if dia_long_min_mm is None else float(dia_long_min_mm)
    return TieSpec(
        dia_mm=max(6.0, largest / 4.0),
        pitch_mm=min(float(least_dim_mm), 16.0 * smallest, 300.0),
    )


# ---------------------------------------------------------------------------
# slabs, Annex D and Clauses 24 and 26.5.2
# ---------------------------------------------------------------------------


class PanelCoefficients(NamedTuple):
    """Annex D Table 26 coefficients for one panel; 0.0 where no edge is continuous."""

    alpha_x_neg: float
    alpha_x_pos: float
    alpha_y_neg: float
    alpha_y_pos: float


def _t26_case(case: Any) -> int:
    """Case number from an int, a numeric string or the case name slug."""
    if isinstance(case, bool):
        raise ValueError("case must be 1 to 9 or a case name, got " + repr(case))
    if isinstance(case, int):
        number = case
    else:
        word = _word(case)
        if word in _T26_NAMES:
            return int(_T26_NAMES[word])
        if not word.isdigit():
            raise ValueError("case unknown: " + repr(case) + "; known: " + ", ".join(sorted(_T26_NAMES)))
        number = int(word)
    if number not in _T26_CASES:
        raise ValueError("case must be 1 to 9, got " + repr(case))
    return number


@clause(
    code=CODE,
    ref="Table 26",
    title="Moment coefficients for a restrained two-way panel",
    symbol="alpha",
    units="",
    latex=r"M=\alpha w l_x^2",
)
def annex_d__table26(case: Any, ly_over_lx: float) -> PanelCoefficients:
    """Table 26 coefficients, interpolated linearly on ly/lx and flat outside [1.0, 2.0].

    A tabulated dash (a discontinuous edge, so no negative moment in that
    direction) comes back as 0.0, which multiplies out to no support moment.
    """
    block = _T26_CASES[_t26_case(case)]
    ratio = float(ly_over_lx)
    if ratio < 1.0:
        raise ValueError("ly_over_lx must be at least 1.0 (ly is the longer span), got " + repr(ly_over_lx))
    x_neg = block["alpha_x_neg"]
    x_pos = block["alpha_x_pos"]
    neg = 0.0 if x_neg[0] is None else _interp(_T26_RATIOS, [v or 0.0 for v in x_neg], ratio)
    pos = 0.0 if x_pos[0] is None else _interp(_T26_RATIOS, [v or 0.0 for v in x_pos], ratio)
    return PanelCoefficients(
        alpha_x_neg=neg,
        alpha_x_pos=pos,
        alpha_y_neg=float(block["alpha_y_neg"] or 0.0),
        alpha_y_pos=float(block["alpha_y_pos"] or 0.0),
    )


class SimplePanelCoefficients(NamedTuple):
    """Annex D Table 27 coefficients for a simply supported panel, corners free."""

    alpha_x: float
    alpha_y: float


@clause(
    code=CODE,
    ref="Table 27",
    title="Moment coefficients for a simply supported two-way panel",
    symbol="alpha",
    units="",
    latex=r"M=\alpha w l_x^2",
)
def annex_d__table27(ly_over_lx: float) -> SimplePanelCoefficients:
    """Table 27 coefficients (corners not held down), linear on ly/lx, flat outside [1.0, 3.0]."""
    ratio = float(ly_over_lx)
    if ratio < 1.0:
        raise ValueError("ly_over_lx must be at least 1.0 (ly is the longer span), got " + repr(ly_over_lx))
    return SimplePanelCoefficients(
        alpha_x=_interp(_T27_RATIOS, _T27_AX, ratio),
        alpha_y=_interp(_T27_RATIOS, _T27_AY, ratio),
    )


class CornerTorsion(NamedTuple):
    """Corner torsion mesh: area in each of four layers over a band each way."""

    ast_mm2: float
    band_mm: float
    layers: int


@clause(code=CODE, ref="D-1.8", title="Torsion reinforcement at slab corners", symbol="Ast,corner", units="mm2")
def annex_d_1_8__corner_torsion(ast_mid_mm2: float, lx_mm: float, discontinuous_edges: int = 2) -> CornerTorsion:
    """Corner mesh area per layer, mm2, over a band of one fifth of the short span.

    Three quarters of the midspan steel where both edges at the corner are
    discontinuous, half of that per D-1.9 where one edge is continuous, none
    where both are continuous.
    """
    edges = int(discontinuous_edges)
    if edges not in (0, 1, 2):
        raise ValueError("discontinuous_edges must be 0, 1 or 2, got " + repr(discontinuous_edges))
    factor = {0: 0.0, 1: 0.375, 2: 0.75}[edges]
    return CornerTorsion(ast_mm2=factor * float(ast_mid_mm2), band_mm=float(lx_mm) / 5.0, layers=4)


class TwoWaySpanDepth(NamedTuple):
    """Clause 24.1 span to depth limit for a two-way slab and its applicability."""

    ratio: float
    applicable: bool


@clause(code=CODE, ref="24.1", title="Span to effective depth for a two-way slab", symbol="(l/d)", units="")
def cl_24_1__two_way_ld(support: str, fy_mpa: float, short_span_m: float, ll_kpa: float) -> TwoWaySpanDepth:
    """Limit on short span over effective depth: 35 simply supported, 40 continuous.

    Multiplied by 0.8 for high strength deformed bars. The Note limits the rule
    to a shorter span up to 3.5 m and an imposed load up to 3 kN/m2; outside
    that the caller must fall back to the Clause 23.2.1 beam rule, and
    `applicable` says which case it is.
    """
    base = _TWO_WAY_LD[_resolve(support, _TWO_WAY_LD, _TWO_WAY_ALIASES, "support")]
    if float(fy_mpa) > 250.0:
        base *= _TWO_WAY_HYSD
    ok = float(short_span_m) <= _TWO_WAY_MAX_SPAN_M and float(ll_kpa) <= _TWO_WAY_MAX_LL_KPA
    return TwoWaySpanDepth(ratio=base, applicable=ok)


@clause(code=CODE, ref="26.5.2.1", title="Minimum reinforcement in a slab", symbol="As,min", units="mm2")
def cl_26_5_2_1__min_slab_steel(overall_depth_mm: float, fy_mpa: float, width_mm: float = 1000.0) -> float:
    """Minimum slab steel over a strip width, mm2: 0.15 percent mild, 0.12 percent deformed."""
    fraction = 0.0015 if float(fy_mpa) <= 250.0 else 0.0012
    return fraction * float(width_mm) * float(overall_depth_mm)


# ---------------------------------------------------------------------------
# footings, Clauses 31 and 34
# ---------------------------------------------------------------------------


class PunchingCheck(NamedTuple):
    """Two-way shear capacity at the critical perimeter."""

    ks: float
    tau_c_mpa: float
    capacity_mpa: float
    ratio: float


@clause(
    code=CODE,
    ref="31.6.3",
    title="Two-way shear capacity",
    symbol="ks tau_c",
    units="MPa",
    latex=r"k_s=\min(0.5+\beta_c,1.0),\ \tau_c=0.25\sqrt{f_{ck}}",
)
def cl_31_6_3__punching(tau_v_mpa: float, fck_mpa: float, beta_c: float) -> PunchingCheck:
    """Punching capacity ks x 0.25 sqrt(fck) and the demand ratio.

    `beta_c` is the ratio of the short side to the long side of the loaded area.
    """
    ks = min(0.5 + float(beta_c), 1.0)
    tau_c = 0.25 * math.sqrt(float(fck_mpa))
    capacity = ks * tau_c
    return PunchingCheck(
        ks=ks,
        tau_c_mpa=tau_c,
        capacity_mpa=capacity,
        ratio=float(tau_v_mpa) / capacity if capacity > 0.0 else float("inf"),
    )


@clause(code=CODE, ref="34.2.3.2", title="Critical section for bending in a footing", symbol="projection", units="mm")
def cl_34_2_3_2__bending_section(footing_dim_mm: float, column_dim_mm: float) -> float:
    """Cantilever projection from the column face, mm, where the bending moment is taken."""
    return max(0.5 * (float(footing_dim_mm) - float(column_dim_mm)), 0.0)


@clause(
    code=CODE,
    ref="34.3.1.2",
    title="Reinforcement in the central band of a rectangular footing",
    symbol="2/(beta+1)",
    units="",
    latex=r"\frac{A_{s,band}}{A_{s,short}}=\frac{2}{\beta+1}",
)
def cl_34_3_1_2__band_distribution(beta: float) -> float:
    """Fraction of the short-direction steel that goes in the central band.

    `beta` is the ratio of the long side to the short side of the footing.
    """
    if beta < 1.0:
        raise ValueError("beta is the long side over the short side, so it is at least 1.0")
    return 2.0 / (float(beta) + 1.0)


class BearingStress(NamedTuple):
    """Permissible bearing stress at a column to footing interface."""

    area_ratio: float
    stress_mpa: float


@clause(
    code=CODE,
    ref="34.4",
    title="Permissible bearing stress at the column face",
    symbol="sigma_br",
    units="MPa",
    latex=r"\sigma_{br}=0.45f_{ck}\sqrt{A_1/A_2}\le0.9f_{ck}",
)
def cl_34_4__bearing(fck_mpa: float, a1_mm2: float, a2_mm2: float) -> BearingStress:
    """0.45 fck times sqrt(A1/A2), the ratio capped at 2 so the stress caps at 0.9 fck.

    A1 is the supporting (spread) area and A2 the loaded area.
    """
    if a2_mm2 <= 0.0 or a1_mm2 <= 0.0:
        raise ValueError("a1_mm2 and a2_mm2 must be positive")
    ratio = min(math.sqrt(float(a1_mm2) / float(a2_mm2)), 2.0)
    return BearingStress(area_ratio=ratio, stress_mpa=0.45 * float(fck_mpa) * ratio)


class DowelSpec(NamedTuple):
    """Minimum dowel steel across the column to footing joint."""

    area_mm2: float
    min_bars: int


@clause(code=CODE, ref="34.4.3", title="Minimum dowels at a column base", symbol="As,dowel", units="mm2")
def cl_34_4_3__min_dowels(ac_mm2: float) -> DowelSpec:
    """Half a percent of the supported column area, in at least four bars."""
    if ac_mm2 <= 0.0:
        raise ValueError("ac_mm2 must be positive")
    return DowelSpec(area_mm2=0.005 * float(ac_mm2), min_bars=4)


@clause(code=CODE, ref="34.1.2", title="Minimum thickness at the edge of a footing", symbol="D_edge", units="mm")
def cl_34_1_2__min_edge_thickness() -> float:
    """Minimum edge thickness of a footing on soil, 150 mm."""
    return 150.0
