"""IS 1893 (Part 1) : 2016 clause callables: the equivalent static method.

One clause is one pure callable reading `data/is1893.yaml`, registered in
CLAUSE_REGISTRY by the `@clause` decorator and traced whenever a sink is open.
Nothing here prints, logs, defaults a design choice or holds state.

Units are SI: metres, kN, seconds. Coefficients are dimensionless fractions,
never percentages: the Cl 7.2.2 floor for zone IV comes back as 0.016.

Finding 41: no structural system is assumed here. `response_reduction` is a
pure lookup and an unknown system raises; the resolved default (OMRF up to zone
III, SMRF above) is settled in `structural/api.py` and arrives inside the
SeismicContext.

Finding 2: storeys are 0-based everywhere and `vertical_distribution` is
index-free: it takes (Wi, hi) pairs, with hi measured from the base, so the
caller derives hi from `bottom_z_m` and never from a storey number.

Disclosure is the caller's job: `sa_over_g(...).clamped` is True when a period
past the printed 4 s end of the spectrum was clamped, and the seismic module
puts that on the ladder.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Sequence, Tuple

from ..data._loader import load_yaml, require_keys
from .trace import clause

CODE = "IS 1893-1:2016"

_TABLE_NAME = "is1893"
_REQUIRED = (
    "source",
    "edition",
    "zone_factor",
    "importance_factor",
    "response_reduction",
    "spectra",
    "period",
    "min_base_shear_coeff",
    "live_load_fraction",
    "eccentricity",
    "drift_limit",
)

# Callers hand a zone through from JSON, where it is as likely to be 4 as "IV".
_ZONE_ALIASES = {"2": "II", "3": "III", "4": "IV", "5": "V"}

_VALIDATED = []  # type: List[str]


def _table() -> Dict[str, Any]:
    """The seismic table, validated on first use."""
    table = load_yaml(_TABLE_NAME)
    if not _VALIDATED:
        require_keys(table, _REQUIRED, _TABLE_NAME + ".yaml")
        _VALIDATED.append(_TABLE_NAME)
    return table


def _zone_key(zone: Any) -> str:
    """`IV`, `iv`, `4` and 4 all resolve to the same table key."""
    key = str(zone).strip().upper()
    return _ZONE_ALIASES.get(key, key)


def _pick(mapping: Dict[str, Any], key: str, what: str, original: Any) -> Any:
    if key in mapping:
        return mapping[key]
    known = ", ".join(sorted(str(k) for k in mapping))
    raise KeyError("unknown " + what + ": " + repr(str(original)) + "; known keys: " + known)


# ---------------------------------------------------------------------------
# returned shapes
# ---------------------------------------------------------------------------


class SpectralOrdinate(NamedTuple):
    """Cl 6.4.2 design acceleration coefficient and which branch produced it."""

    sa_g: float
    branch: str  # rising | plateau | decay
    clamped: bool  # True when T ran past the printed 4 s end of the spectrum


class DesignEccentricity(NamedTuple):
    """Cl 7.8.2, both branches; the more severe effect governs the element."""

    amplified: float  # 1.5 esi + 0.05 bi
    reduced: float  # esi - 0.05 bi


# ---------------------------------------------------------------------------
# seismic inputs
# ---------------------------------------------------------------------------


@clause(code=CODE, ref="Table 3", title="Seismic zone factor", symbol="Z", units="")
def zone_factor(zone: str) -> float:
    """Z for a seismic zone: II 0.10, III 0.16, IV 0.24, V 0.36.

    Z is the maximum considered earthquake value; the Ah expression halves it
    for the design basis earthquake.
    """
    values = _table()["zone_factor"]["values"]
    return float(_pick(values, _zone_key(zone), "seismic zone", zone))


@clause(code=CODE, ref="Table 8", title="Importance factor", symbol="I", units="")
def importance_factor(cat: str = "residential") -> float:
    """I by building category: residential 1.0, important 1.2, essential 1.5."""
    values = _table()["importance_factor"]["values"]
    key = str(cat).strip().lower()
    return float(_pick(values, key, "importance category", cat))


@clause(code=CODE, ref="Table 9", title="Response reduction factor", symbol="R", units="")
def response_reduction(system: str) -> float:
    """R for a structural system. Pure lookup: an unknown system raises.

    Finding 41: no system is defaulted here. The resolved default reaches this
    function inside the SeismicContext that `structural/api.py` builds.
    """
    values = _table()["response_reduction"]["values"]
    key = str(system).strip().lower()
    return float(_pick(values, key, "structural system", system))


@clause(code=CODE, ref="6.4.2(b)", title="Design acceleration coefficient", symbol="Sa/g", units="")
def sa_over_g(T: float, soil: str = "II") -> SpectralOrdinate:
    """Sa/g at period T on soil type I, II or III, 5 percent damping.

    Three branches, exactly as printed: 1 + 15 T below 0.10 s, the 2.5 plateau
    to the soil corner period (0.40 / 0.55 / 0.67 s), then 1.00 / 1.36 / 1.67
    over T. The step at the corner period (1.36 / 0.55 = 2.473 against the 2.5
    plateau) is the code as printed and is not smoothed.

    The spectrum is tabulated to 4 s; a longer period is evaluated at 4 s and
    comes back with `clamped` True for the caller to disclose.
    """
    block = _table()["spectra"]
    key = str(soil).strip().upper()
    params = _pick(block["soils"], key, "soil type", soil)
    period = float(T)
    if period < 0.0:
        raise ValueError("period must not be negative, got " + repr(period))
    clamped = False
    limit = float(block["max_period_s"])
    if period > limit:
        period = limit
        clamped = True
    plateau_start = float(block["plateau_start_s"])
    plateau = float(block["plateau"])
    if period <= plateau_start:
        rising = float(block["rising_intercept"]) + float(block["rising_slope"]) * period
        return SpectralOrdinate(sa_g=rising, branch="rising", clamped=clamped)
    if period <= float(params["corner_period_s"]):
        return SpectralOrdinate(sa_g=plateau, branch="plateau", clamped=clamped)
    return SpectralOrdinate(sa_g=float(params["decay_numerator"]) / period, branch="decay", clamped=clamped)


@clause(code=CODE, ref="7.6.2(c)", title="Approximate period, infilled frame or masonry", symbol="Ta", units="s")
def period_infilled(h_m: float, d_m: float) -> float:
    """Ta = 0.09 h / sqrt(d), d being the base plan dimension along the direction shaken."""
    block = _table()["period"]["infilled"]
    depth = float(d_m)
    if depth <= 0.0:
        raise ValueError("base plan dimension must be positive, got " + repr(depth))
    return float(block["coefficient"]) * float(h_m) / (depth ** 0.5)


@clause(code=CODE, ref="7.6.2(a)", title="Approximate period, bare RC frame", symbol="Ta", units="s")
def period_bare_rc(h_m: float) -> float:
    """Ta = 0.075 h^0.75 for a bare moment resisting reinforced concrete frame."""
    block = _table()["period"]["bare_rc"]
    return float(block["coefficient"]) * (float(h_m) ** float(block["exponent"]))


@clause(code=CODE, ref="6.4.2", title="Design horizontal seismic coefficient", symbol="Ah", units="")
def design_horizontal_coeff(Z: float, I: float, R: float, SaG: float) -> float:
    """Ah = (Z / 2) (Sa/g) / (R / I).

    Zone III, I 1.0, R 5, Sa/g 2.5 gives 0.04.
    """
    ratio = float(R) / float(I)
    if ratio <= 0.0:
        raise ValueError("R / I must be positive, got " + repr(ratio))
    return (float(Z) / 2.0) * float(SaG) / ratio


@clause(code=CODE, ref="7.2.2", title="Minimum base shear coefficient", symbol="rho", units="")
def min_base_shear_coeff(zone: str) -> float:
    """Floor on VB / W by zone, as a fraction: II 0.007, III 0.011, IV 0.016, V 0.024."""
    values = _table()["min_base_shear_coeff"]["values"]
    return float(_pick(values, _zone_key(zone), "seismic zone", zone))


@clause(code=CODE, ref="7.6.1", title="Design seismic base shear", symbol="VB", units="kN")
def base_shear(Ah: float, W_kN: float) -> float:
    """VB = Ah W, with W the seismic weight of the building."""
    return float(Ah) * float(W_kN)


@clause(code=CODE, ref="Table 10", title="Imposed load fraction in the seismic weight", symbol="f_LL", units="")
def seismic_ll_fraction(q_kPa: float) -> float:
    """0.25 for an imposed load up to 3 kPa, 0.50 above it.

    Roof imposed load is excluded from the seismic weight altogether (Cl 7.3.2);
    that exclusion is the seismic module's, not this lookup's.
    """
    block = _table()["live_load_fraction"]
    if float(q_kPa) <= float(block["threshold_kpa"]):
        return float(block["at_or_below"])
    return float(block["above"])


@clause(code=CODE, ref="7.6.3", title="Vertical distribution of base shear", symbol="Qi", units="kN")
def vertical_distribution(pairs: Sequence[Tuple[float, float]], base_shear_kN: float) -> List[float]:
    """Qi = VB Wi hi^2 / sum(Wj hj^2), returned in the order the pairs arrive.

    `pairs` are (Wi in kN, hi in metres measured from the base). Index-free by
    design (finding 2): the caller derives hi from `bottom_z_m`, never from a
    storey number. Four equal masses at h, 2h, 3h, 4h split VB as
    1 : 4 : 9 : 16, so VB = 300 kN gives 10, 40, 90, 160.
    """
    weighted = []  # type: List[float]
    for pair in pairs:
        if len(pair) != 2:
            raise ValueError("vertical_distribution takes (Wi_kN, hi_m) pairs, got " + repr(pair))
        w_i = float(pair[0])
        h_i = float(pair[1])
        weighted.append(w_i * h_i * h_i)
    total = sum(weighted)
    if total <= 0.0:
        raise ValueError("sum of Wi hi^2 is not positive; the storey ledger carries no weight above the base")
    shear = float(base_shear_kN)
    return [shear * value / total for value in weighted]


@clause(code=CODE, ref="7.8.2", title="Design eccentricity", symbol="edi", units="m")
def design_eccentricity(esi: float, bi: float) -> DesignEccentricity:
    """Both Cl 7.8.2 branches: 1.5 esi + 0.05 bi and esi - 0.05 bi.

    Cl 7.8.2 defines `esi` as the DISTANCE between the centre of mass and the
    centre of rigidity, so a signed offset is folded to its magnitude here.
    Fed the signed value, the accidental 0.05 bi term would act in only one of
    its two accidental directions and the governing design eccentricity would
    come out up to 28.6 percent low on the mirrored half of all plans (the
    torque uses the magnitude, so only magnitudes matter downstream). With the
    distance in, the amplified branch always governs by magnitude and the
    envelope is 1.5 |esi| + 0.05 bi.

    `bi` is the plan dimension perpendicular to the direction shaken. The more
    severe effect on the element governs; the diaphragm module chooses, and
    takes no torsional relief on the flexible side (spec section 13).
    """
    block = _table()["eccentricity"]
    amplification = float(block["amplification"])
    accidental = float(block["accidental"])
    distance = abs(float(esi))
    return DesignEccentricity(
        amplified=amplification * distance + accidental * float(bi),
        reduced=distance - accidental * float(bi),
    )


@clause(code=CODE, ref="7.11.1.1", title="Storey drift limit", symbol="delta_limit", units="m")
def storey_drift_limit(h_m: float) -> float:
    """0.004 h, the drift limit under the design lateral force with a load factor of 1.0."""
    return float(_table()["drift_limit"]["value"]) * float(h_m)


def drift_limit_ratio() -> float:
    """The bare 0.004 ratio, for a report line that quotes the limit itself.

    Not a clause: reading the constant is not applying it.
    """
    return float(_table()["drift_limit"]["value"])
