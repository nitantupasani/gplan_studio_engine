"""IS 6403:1981 bearing capacity of shallow foundations, one clause per callable.

The chain a footing designer walks: bearing capacity factors from the friction
angle, then shape, depth, load inclination and water table corrections, then
the local shear reduction where the soil is loose or soft, then the net safe
bearing pressure at a factor of safety. Every step is a pure function traced by
the single sink in `codes/trace.py`; `net_safe_bearing` is the assembly and
emits the whole chain into the sink in one call.

Units are geotechnical SI as the rest of the engine uses them: lengths metres,
unit weights kN/m3, cohesion and pressures kPa, angles degrees. This module has
no millimetre surface, so nothing here carries an `_mm` name.

Two things this module does NOT decide. It never invents a soil: c, phi, gamma
and the water table depth come from the caller, and a caller with only a stated
safe bearing capacity skips this module entirely. And it never writes to the
disclosure ladder: the conditions it can raise (the local shear reduction, a
friction angle past the tabulated range, a water table above the founding
level) travel in the returned `notes` tuple, which the footing designer copies
into DesignResult.notes. The model.py registry has no code for a code mandated
strength reduction, and borrowing a neighbouring code would merge two unrelated
messages in the DisclosureLog, which dedupes by code.

Clause NUMBERS below are transcribed from the submodule specification and are
pending a read against the printed standard; the VALUES are the published
Vesic style expressions and are pinned by the cross-check test at phi 0 to 35.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Optional, Tuple

from .trace import clause

CODE = "IS6403:1981"

# Nc at phi = 0 is the printed table value; the analytical limit of
# (Nq - 1) cot(phi) as phi tends to zero is pi + 2 = 5.1416, 0.03 percent above it.
NC_PHI_ZERO = 5.14

# Below this friction angle the soil is taken to fail in local shear and the
# strength parameters are reduced by two thirds (tan phi and c alike).
LOCAL_SHEAR_PHI_DEG = 28.0
LOCAL_SHEAR_FACTOR = 2.0 / 3.0

# Water table correction: 0.5 with the table at or above the founding level,
# rising linearly to 1.0 once it lies a footing width below it.
WATER_FACTOR_AT_BASE = 0.5
WATER_FACTOR_DRY = 1.0

GAMMA_WATER_KNM3 = 9.81

FOS_DEFAULT = 2.5

# Friction angle beyond which the factors are an extrapolation of the range the
# standard tabulates. Not a refusal, a note on the result.
PHI_TABULATED_MAX_DEG = 45.0
PHI_SUPPORTED_MAX_DEG = 60.0

# Table 2 prints a separate square row, 1.3 / 1.2 / 0.8, which does not meet the
# rectangle expressions at B/L = 1 (they give 1.2 / 1.2 / 0.6). This module uses
# the rectangle expressions at every aspect ratio: continuous, and the lower of
# the two readings on both governing terms. The printed row is kept here for the
# record and is not applied.
TABLE_2_SQUARE_PRINTED = (1.3, 1.2, 0.8)

_TOL = 1e-12


class BearingFactors(NamedTuple):
    """Table 1 bearing capacity factors."""

    nc: float
    nq: float
    n_gamma: float


class ShapeFactors(NamedTuple):
    """Table 2 shape factors."""

    sc: float
    sq: float
    s_gamma: float


class DepthFactors(NamedTuple):
    """Table 3 depth factors."""

    dc: float
    dq: float
    d_gamma: float


class InclinationFactors(NamedTuple):
    """Table 4 load inclination factors."""

    ic: float
    iq: float
    i_gamma: float


class LocalShear(NamedTuple):
    """Strength parameters after the local shear check."""

    phi_deg: float
    c_kpa: float
    applied: bool
    phi_in_deg: float
    c_in_kpa: float
    notes: Tuple[str, ...]


class NetSafeBearing(NamedTuple):
    """Net and gross safe bearing pressure with every term that built it."""

    q_net_ult_kpa: float
    q_safe_net_kpa: float
    q_safe_gross_kpa: float
    fos: float
    nc: float
    nq: float
    n_gamma: float
    term_cohesion_kpa: float
    term_surcharge_kpa: float
    term_width_kpa: float
    surcharge_eff_kpa: float
    overburden_total_kpa: float
    water_factor: float
    local_shear_applied: bool
    phi_used_deg: float
    c_used_kpa: float
    notes: Tuple[str, ...]


# ---------------------------------------------------------------------------
# factors
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 1",
    title="Bearing capacity factors",
    symbol="Nc, Nq, Ngamma",
    units="-",
    latex=r"N_q=e^{\pi\tan\phi}\tan^2\left(45+\frac{\phi}{2}\right),\ N_c=(N_q-1)\cot\phi,\ N_\gamma=2(N_q+1)\tan\phi",
)
def bearing_capacity_factors(phi_deg: float) -> BearingFactors:
    """Nc, Nq and Ngamma for an angle of shearing resistance in degrees.

    Nq is the Prandtl expression, Nc follows from it, Ngamma is the Vesic form
    the standard adopts. At phi = 0 the cotangent is singular and Nc takes its
    printed value 5.14, which is the limit of the expression.
    """
    phi = float(phi_deg)
    if phi < 0.0:
        raise ValueError("phi_deg cannot be negative")
    if phi >= PHI_SUPPORTED_MAX_DEG:
        raise ValueError("phi_deg " + _r(phi, 1) + " is outside the range this module supports (below 60 degrees)")
    if phi <= _TOL:
        return BearingFactors(nc=NC_PHI_ZERO, nq=1.0, n_gamma=0.0)
    rad = math.radians(phi)
    tan_phi = math.tan(rad)
    nq = math.exp(math.pi * tan_phi) * math.tan(math.radians(45.0 + phi / 2.0)) ** 2
    nc = (nq - 1.0) / tan_phi
    n_gamma = 2.0 * (nq + 1.0) * tan_phi
    return BearingFactors(nc=nc, nq=nq, n_gamma=n_gamma)


@clause(
    code=CODE,
    ref="Table 2",
    title="Shape factors",
    symbol="sc, sq, sgamma",
    units="-",
    latex=r"s_c=s_q=1+0.2\frac{B}{L},\quad s_\gamma=1-0.4\frac{B}{L}",
)
def shape_factors(b_m: float, l_m: float) -> ShapeFactors:
    """Shape corrections for a rectangle of width B and length L, B the shorter side.

    B/L is clamped at 1.0, so a caller that hands the sides in the other order
    gets the square values rather than a factor outside the tabulated range.
    A long strip tends to 1.0 / 1.0 / 1.0, which is the strip row.
    """
    if b_m <= 0.0 or l_m <= 0.0:
        raise ValueError("footing b_m and l_m must be positive")
    ratio = min(float(b_m) / float(l_m), 1.0)
    return ShapeFactors(sc=1.0 + 0.2 * ratio, sq=1.0 + 0.2 * ratio, s_gamma=1.0 - 0.4 * ratio)


@clause(
    code=CODE,
    ref="Table 3",
    title="Depth factors",
    symbol="dc, dq, dgamma",
    units="-",
    latex=r"d_c=1+0.2\frac{D_f}{B}\tan\left(45+\frac{\phi}{2}\right),\quad d_q=d_\gamma=1+0.1\frac{D_f}{B}\tan\left(45+\frac{\phi}{2}\right)",
)
def depth_factors(phi_deg: float, df_m: float, b_m: float) -> DepthFactors:
    """Depth corrections for a founding depth Df and footing width B.

    The surcharge and width factors are unity below phi = 10 degrees, where the
    standard credits no depth effect to the frictional terms.
    """
    phi = float(phi_deg)
    if phi < 0.0:
        raise ValueError("phi_deg cannot be negative")
    if df_m < 0.0:
        raise ValueError("df_m cannot be negative")
    if b_m <= 0.0:
        raise ValueError("b_m must be positive")
    root_nphi = math.tan(math.radians(45.0 + phi / 2.0))
    depth_ratio = float(df_m) / float(b_m)
    dc = 1.0 + 0.2 * depth_ratio * root_nphi
    if phi < 10.0:
        return DepthFactors(dc=dc, dq=1.0, d_gamma=1.0)
    dq = 1.0 + 0.1 * depth_ratio * root_nphi
    return DepthFactors(dc=dc, dq=dq, d_gamma=dq)


@clause(
    code=CODE,
    ref="Table 4",
    title="Load inclination factors",
    symbol="ic, iq, igamma",
    units="-",
    latex=r"i_c=i_q=\left(1-\frac{\alpha}{90}\right)^2,\quad i_\gamma=\left(1-\frac{\alpha}{\phi}\right)^2",
)
def inclination_factors(alpha_deg: float, phi_deg: float) -> InclinationFactors:
    """Corrections for a resultant inclined alpha degrees from the vertical.

    A vertical load returns unity throughout. Beyond alpha = phi the width term
    is exhausted and igamma is zero rather than negative; on a cohesive soil
    with phi = 0 the width term does not exist and igamma is likewise zero.
    """
    alpha = float(alpha_deg)
    phi = float(phi_deg)
    if alpha < 0.0:
        raise ValueError("alpha_deg cannot be negative")
    if phi < 0.0:
        raise ValueError("phi_deg cannot be negative")
    if alpha <= _TOL:
        return InclinationFactors(ic=1.0, iq=1.0, i_gamma=1.0)
    alpha = min(alpha, 90.0)
    ic = (1.0 - alpha / 90.0) ** 2
    if phi <= _TOL:
        return InclinationFactors(ic=ic, iq=ic, i_gamma=0.0)
    i_gamma = max(1.0 - alpha / phi, 0.0) ** 2
    return InclinationFactors(ic=ic, iq=ic, i_gamma=i_gamma)


@clause(
    code=CODE,
    ref="5.1.1",
    title="Water table correction",
    symbol="W'",
    units="-",
    latex=r"W'=0.5+0.5\frac{z_w}{B}\ \ (0\le z_w\le B)",
)
def water_table_factor(zw_m: float, b_m: float) -> float:
    """Correction on the width term for a water table zw below the footing base.

    0.5 with the table at or above the founding level, rising linearly to 1.0
    once it lies a full footing width below it. The correction applies to the
    0.5 B gamma Ngamma term only; the surcharge term is corrected by using the
    effective overburden, which `net_safe_bearing` does for its caller.
    """
    if b_m <= 0.0:
        raise ValueError("b_m must be positive")
    depth_ratio = float(zw_m) / float(b_m)
    if depth_ratio <= 0.0:
        return WATER_FACTOR_AT_BASE
    if depth_ratio >= 1.0:
        return WATER_FACTOR_DRY
    return WATER_FACTOR_AT_BASE + (WATER_FACTOR_DRY - WATER_FACTOR_AT_BASE) * depth_ratio


@clause(
    code=CODE,
    ref="5.1.3",
    title="Local shear failure: reduced strength parameters",
    symbol="phi_m, c_m",
    units="deg, kPa",
    latex=r"\tan\phi_m=\frac{2}{3}\tan\phi,\quad c_m=\frac{2}{3}c",
)
def local_shear_guard(phi_deg: float, c_kpa: float) -> LocalShear:
    """Reduce c and tan phi by two thirds where the soil fails in local shear.

    Loose sands and soft clays punch rather than develop the full general shear
    wedge. Below phi = 28 degrees the reduction is applied and said so in
    `notes`; at or above it the inputs are returned untouched with applied
    False, so the caller can always read what went into the factors.
    """
    phi = float(phi_deg)
    cohesion = float(c_kpa)
    if phi < 0.0:
        raise ValueError("phi_deg cannot be negative")
    if cohesion < 0.0:
        raise ValueError("c_kpa cannot be negative")
    if phi >= LOCAL_SHEAR_PHI_DEG:
        return LocalShear(
            phi_deg=phi,
            c_kpa=cohesion,
            applied=False,
            phi_in_deg=phi,
            c_in_kpa=cohesion,
            notes=(),
        )
    phi_reduced = math.degrees(math.atan(LOCAL_SHEAR_FACTOR * math.tan(math.radians(phi))))
    c_reduced = LOCAL_SHEAR_FACTOR * cohesion
    note = (
        "local shear reduction applied below phi "
        + _r(LOCAL_SHEAR_PHI_DEG, 0)
        + " deg: phi "
        + _r(phi, 1)
        + " -> "
        + _r(phi_reduced, 1)
        + " deg, c "
        + _r(cohesion, 1)
        + " -> "
        + _r(c_reduced, 1)
        + " kPa"
    )
    return LocalShear(
        phi_deg=phi_reduced,
        c_kpa=c_reduced,
        applied=True,
        phi_in_deg=phi,
        c_in_kpa=cohesion,
        notes=(note,),
    )


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="6.1",
    title="Net safe bearing pressure",
    symbol="q_safe_net",
    units="kPa",
    latex=r"q_{ns}=\frac{cN_cs_cd_ci_c+q(N_q-1)s_qd_qi_q+0.5B\gamma N_\gamma s_\gamma d_\gamma i_\gamma W'}{F}",
)
def net_safe_bearing(
    c_kpa: float,
    phi_deg: float,
    gamma_knm3: float,
    b_m: float,
    l_m: float,
    df_m: float,
    gwt_depth_m: Optional[float] = None,
    alpha_deg: float = 0.0,
    fos: float = FOS_DEFAULT,
) -> NetSafeBearing:
    """Net ultimate and net safe bearing pressure for a rectangular footing.

    `gwt_depth_m` is the water table depth below GROUND level, the way the soil
    block states it; None means no water table within the influence depth, a
    caller assumption that is noted on the result. A table above the founding
    level both caps the width correction at 0.5 and puts the surcharge on the
    submerged unit weight, both done here.

    The safety factor divides the NET ultimate pressure, per the standard; the
    gross safe pressure adds the total overburden back at the founding level.
    """
    if b_m <= 0.0 or l_m <= 0.0:
        raise ValueError("footing b_m and l_m must be positive")
    if gamma_knm3 <= 0.0:
        raise ValueError("gamma_knm3 must be positive")
    if df_m < 0.0:
        raise ValueError("df_m cannot be negative")
    if fos < 1.0:
        raise ValueError("fos must be at least 1.0")

    width_m = min(float(b_m), float(l_m))
    length_m = max(float(b_m), float(l_m))
    notes = []

    strength = local_shear_guard(phi_deg, c_kpa)
    notes.extend(strength.notes)
    phi_used = strength.phi_deg
    c_used = strength.c_kpa
    if phi_used > PHI_TABULATED_MAX_DEG:
        notes.append(
            "phi " + _r(phi_used, 1) + " deg is past the tabulated range; bearing factors are extrapolated"
        )

    factors = bearing_capacity_factors(phi_used)
    shape = shape_factors(width_m, length_m)
    depth = depth_factors(phi_used, df_m, width_m)
    inclination = inclination_factors(alpha_deg, phi_used)

    gamma = float(gamma_knm3)
    overburden_total = gamma * float(df_m)
    if gwt_depth_m is None:
        water_factor = WATER_FACTOR_DRY
        surcharge_eff = overburden_total
        notes.append("no water table supplied; taken as below the influence depth")
    else:
        gwt = float(gwt_depth_m)
        if gwt < 0.0:
            raise ValueError("gwt_depth_m cannot be negative")
        water_factor = water_table_factor(gwt - float(df_m), width_m)
        if gwt < float(df_m):
            gamma_sub = max(gamma - GAMMA_WATER_KNM3, 0.0)
            surcharge_eff = gamma * gwt + gamma_sub * (float(df_m) - gwt)
            notes.append(
                "water table at "
                + _r(gwt, 2)
                + " m is above the founding level; surcharge on the submerged unit weight "
                + _r(gamma_sub, 2)
                + " kN/m3"
            )
        else:
            surcharge_eff = overburden_total

    term_cohesion = c_used * factors.nc * shape.sc * depth.dc * inclination.ic
    term_surcharge = surcharge_eff * (factors.nq - 1.0) * shape.sq * depth.dq * inclination.iq
    term_width = (
        0.5
        * width_m
        * gamma
        * factors.n_gamma
        * shape.s_gamma
        * depth.d_gamma
        * inclination.i_gamma
        * water_factor
    )
    q_net_ult = term_cohesion + term_surcharge + term_width
    q_safe_net = q_net_ult / float(fos)
    return NetSafeBearing(
        q_net_ult_kpa=q_net_ult,
        q_safe_net_kpa=q_safe_net,
        q_safe_gross_kpa=q_safe_net + overburden_total,
        fos=float(fos),
        nc=factors.nc,
        nq=factors.nq,
        n_gamma=factors.n_gamma,
        term_cohesion_kpa=term_cohesion,
        term_surcharge_kpa=term_surcharge,
        term_width_kpa=term_width,
        surcharge_eff_kpa=surcharge_eff,
        overburden_total_kpa=overburden_total,
        water_factor=water_factor,
        local_shear_applied=strength.applied,
        phi_used_deg=phi_used,
        c_used_kpa=c_used,
        notes=tuple(notes),
    )


def _r(value: float, places: int) -> str:
    """Message formatting only, never arithmetic."""
    return ("%." + str(places) + "f") % float(value)
