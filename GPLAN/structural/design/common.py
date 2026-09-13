"""The one design contract every material designer writes to.

Critic finding 6 makes this module normative: `DesignResult` is the shape RC,
masonry, steel and timber all return, `model.design` carries its serialized
dicts, and no designer defines its own. Finding 24 removes `quantities` from
that shape (quantities.py is the sole take-off owner) and pays for it by making
every bar entry carry its own `ld_mm` and `zone_mm`, so a bar schedule needs no
defaults. Finding 25 keeps cover out of the schedule: it is read from
`DesignResult.section`, resolved here, once, per member.

Units. The design layer is N, mm, MPa: the SI model (m, kN, kNm) is converted
once on entry with `m_to_mm` / `kn_to_n` / `knm_to_nmm` and once on exit with
their inverses. Every public field carries its unit suffix.

Determinism. Same input, same dict: enumeration is over sorted catalogue
tuples, scoring is a total order with an explicit final tiebreak, exported
floats are rounded to a fixed number of decimals, and exported mappings are
key-sorted. Nothing here allocates unbounded work: `pick_bars` walks a few
thousand catalogue combinations and stops.

Disclose, never hide. Nothing in this module raises on a design that cannot
pass: `fail_with` returns a fully populated result carrying its governing
check, `pick_bars` returns its best effort with `ok=False` and a note when the
requirement or the width beat it. Only genuine input errors (an unknown
concrete grade, a bar entry with no development length) raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ..codes import is456
from ..codes.trace import TraceEntry
from ..data._loader import load_yaml

__all__ = [
    # unit boundary
    "KN_TO_N",
    "KNM_TO_NMM",
    "M_TO_MM",
    "kn_to_n",
    "knm_to_nmm",
    "m_to_mm",
    "n_to_kn",
    "nmm_to_knm",
    "mm_to_m",
    "round_down_mm",
    "round_up_mm",
    # materials
    "CONCRETE_GRADES_MPA",
    "REBAR_GRADES_MPA",
    "Concrete",
    "RebarSteel",
    "MasonryMaterial",
    "check_exposure_grade",
    "materials_block",
    # rebar catalogue
    "MAIN_DIAS",
    "STIRRUP_DIAS",
    "BEND_ALLOWANCES",
    "bar_area_mm2",
    "unit_mass_kg_m",
    "hook_allowance_mm",
    "stirrup_hook_allowance_mm",
    # cover and depth
    "DEFAULT_AGG_MM",
    "Cover",
    "resolve_cover",
    "min_bar_gap_mm",
    "min_vertical_gap_mm",
    "layer_pitch_mm",
    "effective_depth",
    "clear_width_mm",
    # result contract
    "STATUS_PASS",
    "STATUS_RESIZED",
    "STATUS_FAIL",
    "STATUSES",
    "CHECK_PASS",
    "CHECK_FAIL",
    "CHECK_TOL",
    "RATIO_CAP",
    "REFERRAL_ACTIONS",
    "CheckRow",
    "DesignResult",
    # resize policy
    "default_beam_depth_cap",
    "ResizePolicy",
    # bar selection
    "BarPrefs",
    "BarLayout",
    "pick_bars",
    "spacing_for_area",
    "area_for_spacing",
    # dispatch
    "MATERIALS",
    "MATERIAL_DESIGNERS",
    "register_designer",
    "get_designer",
]


# ---------------------------------------------------------------------------
# unit boundary (SI model in, code units out)
# ---------------------------------------------------------------------------

#: kN to N.
KN_TO_N = 1.0e3
#: kN.m to N.mm.
KNM_TO_NMM = 1.0e6
#: m to mm.
M_TO_MM = 1.0e3

#: Decimals kept on every exported float, so a dict compares equal to itself.
_DP = 6


def kn_to_n(value_kn: float) -> float:
    """Force from the SI model into the design layer."""
    return float(value_kn) * KN_TO_N


def knm_to_nmm(value_knm: float) -> float:
    """Moment from the SI model into the design layer."""
    return float(value_knm) * KNM_TO_NMM


def m_to_mm(value_m: float) -> float:
    """Length from the SI model into the design layer."""
    return float(value_m) * M_TO_MM


def n_to_kn(value_n: float) -> float:
    """Force from the design layer back to the SI model."""
    return float(value_n) / KN_TO_N


def nmm_to_knm(value_nmm: float) -> float:
    """Moment from the design layer back to the SI model."""
    return float(value_nmm) / KNM_TO_NMM


def mm_to_m(value_mm: float) -> float:
    """Length from the design layer back to the SI model."""
    return float(value_mm) / M_TO_MM


def round_down_mm(value_mm: float, module_mm: float) -> float:
    """`value_mm` rounded DOWN to a whole module (spacings, bar pitches)."""
    if module_mm <= 0.0:
        raise ValueError("module_mm must be positive, got " + repr(module_mm))
    return math.floor(float(value_mm) / float(module_mm) + 1e-9) * float(module_mm)


def round_up_mm(value_mm: float, module_mm: float) -> float:
    """`value_mm` rounded UP to a whole module (section depths, plan sizes)."""
    if module_mm <= 0.0:
        raise ValueError("module_mm must be positive, got " + repr(module_mm))
    return math.ceil(float(value_mm) / float(module_mm) - 1e-9) * float(module_mm)


def _r(value: float) -> float:
    """A float rounded to the export precision, with no negative zero."""
    return round(float(value), _DP) + 0.0


def _finite(value: float, cap: float) -> float:
    """A finite value: NaN and infinities are clamped so the dict stays JSON-safe."""
    number = float(value)
    if math.isnan(number):
        return cap
    if math.isinf(number):
        return cap if number > 0.0 else -cap
    if number > cap:
        return cap
    return number


def _word(value: Any) -> str:
    """Vocabulary word normalised the way codes/is456.py normalises one."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _jsonable(value: Any) -> Any:
    """A JSON-safe, key-sorted, fixed-precision view of a value."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return _r(RATIO_CAP)
        if math.isinf(value):
            return _r(RATIO_CAP if value > 0.0 else -RATIO_CAP)
        return _r(value)
    as_dict = getattr(value, "to_dict", None)
    if callable(as_dict):
        return _jsonable(as_dict())
    named = getattr(value, "_asdict", None)
    if callable(named):
        return {str(key): _jsonable(item) for key, item in sorted(named().items())}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else list(value)
        return [_jsonable(item) for item in items]
    return str(value)


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------

#: Concrete grades the design layer offers. api-backend's options enum is
#: generated from this tuple (finding 42), never transcribed beside it.
CONCRETE_GRADES_MPA = (20.0, 25.0, 30.0, 35.0, 40.0)

#: Reinforcement grades the design layer offers, IS 1786 Fe415/500/550.
REBAR_GRADES_MPA = (415.0, 500.0, 550.0)


def _grade_list(grades: Sequence[float], prefix: str) -> str:
    return ", ".join(prefix + str(int(value)) for value in grades)


@dataclass(frozen=True)
class Concrete:
    """A concrete grade and the constants IS 456 derives from it."""

    fck_mpa: float
    gamma_c: float = 1.5
    density_knm3: float = 25.0

    def __post_init__(self) -> None:
        if float(self.fck_mpa) not in CONCRETE_GRADES_MPA:
            raise ValueError(
                "fck_mpa " + repr(self.fck_mpa) + " is not a design grade; known: " + _grade_list(CONCRETE_GRADES_MPA, "M")
            )
        if self.gamma_c <= 0.0 or self.density_knm3 <= 0.0:
            raise ValueError("gamma_c and density_knm3 must be positive")

    @property
    def grade(self) -> str:
        """The grade name, "M25"."""
        return "M" + str(int(self.fck_mpa))

    @property
    def ec_mpa(self) -> float:
        """Short-term modulus, IS 456 Cl 6.2.3.1. Traced when a sink is open."""
        return is456.cl_6_2_3_1__ec(self.fck_mpa)

    @property
    def fcd_mpa(self) -> float:
        """Design compressive stress 0.67 fck / 1.5, IS 456 Cl 38.1."""
        return is456.CONCRETE_DESIGN_FACTOR * float(self.fck_mpa)

    @staticmethod
    def from_grade(grade: Any) -> "Concrete":
        """`Concrete.from_grade("M25")`, also accepting the bare number."""
        text = _word(grade).lstrip("m")
        try:
            fck = float(text)
        except (TypeError, ValueError):
            raise ValueError("concrete grade unknown: " + repr(grade) + "; known: " + _grade_list(CONCRETE_GRADES_MPA, "M"))
        return Concrete(fck_mpa=fck)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade": self.grade,
            "fck_mpa": _r(self.fck_mpa),
            "gamma_c": _r(self.gamma_c),
            "density_knm3": _r(self.density_knm3),
        }


@dataclass(frozen=True)
class RebarSteel:
    """A reinforcement grade and its partial safety factor."""

    fy_mpa: float
    gamma_s: float = 1.15
    es_mpa: float = is456.ES_MPA

    def __post_init__(self) -> None:
        if float(self.fy_mpa) not in REBAR_GRADES_MPA:
            raise ValueError(
                "fy_mpa " + repr(self.fy_mpa) + " is not a design grade; known: " + _grade_list(REBAR_GRADES_MPA, "Fe")
            )
        if self.gamma_s <= 0.0 or self.es_mpa <= 0.0:
            raise ValueError("gamma_s and es_mpa must be positive")

    @property
    def grade(self) -> str:
        """The grade name, "Fe500"."""
        return "Fe" + str(int(self.fy_mpa))

    @property
    def fyd_mpa(self) -> float:
        """Design yield stress 0.87 fy, IS 456 Cl 38.1."""
        return is456.GAMMA_S_FACTOR * float(self.fy_mpa)

    @staticmethod
    def from_grade(grade: Any) -> "RebarSteel":
        """`RebarSteel.from_grade("Fe500")`, also accepting the bare number."""
        text = _word(grade)
        if text.startswith("fe"):
            text = text[2:]
        try:
            fy = float(text)
        except (TypeError, ValueError):
            raise ValueError("steel grade unknown: " + repr(grade) + "; known: " + _grade_list(REBAR_GRADES_MPA, "Fe"))
        return RebarSteel(fy_mpa=fy)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grade": self.grade,
            "fy_mpa": _r(self.fy_mpa),
            "gamma_s": _r(self.gamma_s),
            "es_mpa": _r(self.es_mpa),
        }


def _mortar_grades() -> Tuple[str, ...]:
    """IS 1905 Table 1 mortar grades, imported lazily.

    codes/is1905.py reads its own YAML at import; an RC designer that only
    wanted `pick_bars` should not pay for the masonry tables, so the import
    happens when a MasonryMaterial is actually built.
    """
    from ..codes.is1905 import MORTAR_GRADES

    return tuple(MORTAR_GRADES)


@dataclass(frozen=True)
class MasonryMaterial:
    """A masonry unit and mortar pair; the masonry designer reuses this shape."""

    unit_strength_mpa: float
    mortar_grade: str

    def __post_init__(self) -> None:
        if float(self.unit_strength_mpa) <= 0.0:
            raise ValueError("unit_strength_mpa must be positive, got " + repr(self.unit_strength_mpa))
        grades = _mortar_grades()
        grade = str(self.mortar_grade).strip().upper()
        if grade not in grades:
            raise ValueError("mortar grade unknown: " + repr(self.mortar_grade) + "; known: " + ", ".join(grades))
        object.__setattr__(self, "mortar_grade", grade)

    def to_dict(self) -> Dict[str, Any]:
        return {"unit_strength_mpa": _r(self.unit_strength_mpa), "mortar_grade": self.mortar_grade}


def check_exposure_grade(fck_mpa: float, exposure: str) -> Optional[str]:
    """Warning text when the grade is below the IS 456 Table 5 minimum, else None.

    Warn, never fail: the engine designs with the grade it was given and says
    on the face of the report that durability wants a richer mix.
    """
    minimum = is456.table_5__min_grade(exposure)
    if float(fck_mpa) >= minimum:
        return None
    return (
        "M"
        + str(int(fck_mpa))
        + " is below the IS 456 Table 5 minimum M"
        + str(int(minimum))
        + " for "
        + _word(exposure)
        + " exposure; designed as specified"
    )


def materials_block(concrete: Concrete, steel: RebarSteel) -> Dict[str, Any]:
    """The `materials` dict of a DesignResult."""
    return {
        "fck_mpa": _r(concrete.fck_mpa),
        "fy_mpa": _r(steel.fy_mpa),
        "concrete_grade": concrete.grade,
        "steel_grade": steel.grade,
    }


# ---------------------------------------------------------------------------
# rebar catalogue (data/rebar.yaml is the only table)
# ---------------------------------------------------------------------------

_REBAR = load_yaml("rebar")

#: Diameters a main bar may take, ascending.
MAIN_DIAS = tuple(int(value) for value in _REBAR["main_dias_mm"])
#: Diameters a stirrup, tie or hoop may take, ascending.
STIRRUP_DIAS = tuple(int(value) for value in _REBAR["stirrup_dias_mm"])

_BAR_AREA = MappingProxyType({int(dia): float(row["area_mm2"]) for dia, row in _REBAR["bars"].items()})
_BAR_MASS = MappingProxyType({int(dia): float(row["unit_mass_kg_m"]) for dia, row in _REBAR["bars"].items()})

#: Bend and hook allowances in bar diameters, IS 2502 Cl 5 and IS 13920 Cl 7.3.2.
BEND_ALLOWANCES = MappingProxyType({str(key): value for key, value in _REBAR["bend_allowances"].items()})

_HOOK_135_DIA = float(BEND_ALLOWANCES["hook_135_deg_dia"])
_HOOK_90_DIA = float(BEND_ALLOWANCES["hook_90_deg_dia"])
_HOOK_MIN_MM = float(BEND_ALLOWANCES["min_hook_extension_mm"])


def _known_dias() -> str:
    return ", ".join(str(dia) for dia in sorted(_BAR_AREA))


def bar_area_mm2(dia_mm: float) -> float:
    """Nominal area of one bar, mm2, from data/rebar.yaml."""
    dia = int(round(float(dia_mm)))
    if dia not in _BAR_AREA:
        raise ValueError("bar diameter not in the catalogue: " + repr(dia_mm) + "; known: " + _known_dias())
    return _BAR_AREA[dia]


def unit_mass_kg_m(dia_mm: float) -> float:
    """Nominal mass of one bar per metre, kg/m, from data/rebar.yaml."""
    dia = int(round(float(dia_mm)))
    if dia not in _BAR_MASS:
        raise ValueError("bar diameter not in the catalogue: " + repr(dia_mm) + "; known: " + _known_dias())
    return _BAR_MASS[dia]


def hook_allowance_mm(dia_mm: float, angle_deg: int = 135) -> float:
    """Extension beyond one bend, mm: the catalogue multiple, floored at 75 mm."""
    dia = float(dia_mm)
    if int(angle_deg) == 135:
        multiple = _HOOK_135_DIA
    elif int(angle_deg) == 90:
        multiple = _HOOK_90_DIA
    else:
        raise ValueError("hook angle must be 90 or 135 degrees, got " + repr(angle_deg))
    return max(multiple * dia, _HOOK_MIN_MM)


def stirrup_hook_allowance_mm(dia_mm: float) -> float:
    """Cut-length allowance for a closed stirrup, mm: two 135 degree hooks."""
    return 2.0 * hook_allowance_mm(dia_mm, 135)


# ---------------------------------------------------------------------------
# cover, bar gaps, effective depth
# ---------------------------------------------------------------------------

#: Nominal maximum size of coarse aggregate, mm, where a caller states none.
DEFAULT_AGG_MM = 20.0

#: Member words that are cast against earth, IS 456 Cl 26.4.2.2.
_FOOTING_MEMBERS = frozenset(("footing", "combined_footing", "strip_footing", "pad", "raft", "pile_cap"))


class Cover(NamedTuple):
    """Nominal cover and the sentence that derived it."""

    cover_mm: float
    note: str


def resolve_cover(
    member: str,
    exposure: str,
    fire_rating_h: float = 0.0,
    bar_dia_mm: float = 0.0,
) -> Cover:
    """Nominal cover, mm: the worst of durability, fire and the bar itself.

    Table 16 for the exposure, Table 16A for the fire period (skipped when no
    period is asked for), the bar diameter per Cl 26.4.1, and a 50 mm floor for
    anything cast against earth (Cl 26.4.2.2). The note is the derivation the
    report prints, so it names every contributor, not only the winner.
    """
    word = _word(member)
    footing = word in _FOOTING_MEMBERS
    durability = float(is456.table_16__nominal_cover(exposure))
    parts = ["Table 16 " + _word(exposure) + " " + _mm_text(durability)]
    cover = durability

    rating = 0.0 if fire_rating_h is None else float(fire_rating_h)
    if rating > 0.0:
        fire = float(is456.table_16a__fire_cover("footing" if footing else word, rating))
        parts.append("Table 16A " + _hours_text(rating) + " " + _mm_text(fire))
        cover = max(cover, fire)

    dia = 0.0 if bar_dia_mm is None else float(bar_dia_mm)
    if dia > 0.0:
        parts.append("bar diameter " + _mm_text(dia))
        cover = max(cover, dia)

    if footing:
        floor = float(is456.cl_26_4_2_2__footing_cover())
        parts.append("Cl 26.4.2.2 cast against earth " + _mm_text(floor))
        cover = max(cover, floor)

    note = "cover " + _mm_text(cover) + " governed by the largest of: " + "; ".join(parts)
    return Cover(cover_mm=cover, note=note)


def _mm_text(value_mm: float) -> str:
    """A millimetre value printed without a trailing .0 when it is whole."""
    number = float(value_mm)
    return (str(int(round(number))) if abs(number - round(number)) < 1e-9 else ("%.1f" % number)) + " mm"


def _hours_text(hours: float) -> str:
    number = float(hours)
    return (str(int(round(number))) if abs(number - round(number)) < 1e-9 else ("%.1f" % number)) + " h"


def min_bar_gap_mm(dia_mm: float, agg_mm: float = DEFAULT_AGG_MM) -> float:
    """Minimum horizontal clear gap between parallel bars, IS 456 Cl 26.3.2(a)."""
    return float(is456.cl_26_3_2__min_bar_spacing(dia_mm, agg_mm))


def min_vertical_gap_mm(dia_mm: float, agg_mm: float = DEFAULT_AGG_MM) -> float:
    """Minimum vertical clear gap between bar layers, IS 456 Cl 26.3.2(b): 15 mm,
    two thirds of the aggregate size, or the larger bar, whichever governs.

    codes/is456.py carries the horizontal rule (Cl 26.3.2 a) as a clause
    callable but not this one; the layering arithmetic below is the only
    consumer, so the rule lives here rather than untraced in four designers.
    """
    return max(15.0, 2.0 * float(agg_mm) / 3.0, float(dia_mm))


def layer_pitch_mm(dia_mm: float, agg_mm: float = DEFAULT_AGG_MM) -> float:
    """Centre to centre distance between two bar layers, mm."""
    return float(dia_mm) + min_vertical_gap_mm(dia_mm, agg_mm)


def effective_depth(
    overall_depth_mm: float,
    cover_mm: float,
    stirrup_dia_mm: float = 0.0,
    main_dia_mm: float = 0.0,
    *,
    layers: int = 1,
    agg_mm: float = DEFAULT_AGG_MM
) -> float:
    """Effective depth to the tension steel centroid, mm.

    One layer: D minus cover, stirrup and half the bar. More layers: minus the
    centroid rise of equally loaded layers, (layers - 1) / 2 times the pitch.
    A layout with unequal layers carries the exact rise as
    `BarLayout.d_adjust_mm`; subtract that from the one-layer value instead.

    `layers` is keyword-only on purpose: the spec writes the argument order
    with layers before the diameter, and a positional call in that order would
    otherwise return a plausible wrong number instead of raising.
    """
    count = max(1, int(layers))
    depth = (
        float(overall_depth_mm)
        - float(cover_mm)
        - float(stirrup_dia_mm)
        - 0.5 * float(main_dia_mm)
        - 0.5 * (count - 1) * layer_pitch_mm(main_dia_mm, agg_mm)
    )
    return depth


def clear_width_mm(b_mm: float, cover_mm: float, stirrup_dia_mm: float = 0.0) -> float:
    """Width available to a bar layer between the stirrup legs, mm."""
    return float(b_mm) - 2.0 * (float(cover_mm) + float(stirrup_dia_mm))


# ---------------------------------------------------------------------------
# the design result contract (critic finding 6)
# ---------------------------------------------------------------------------

#: Every check passed on the section the placer handed over.
STATUS_PASS = "pass"
#: The section changed during design; `resize_history` holds every step.
STATUS_RESIZED = "resized"
#: The resize policy was exhausted; the last attempt is still reported in full.
STATUS_FAIL = "fail"

STATUSES = (STATUS_PASS, STATUS_RESIZED, STATUS_FAIL)

CHECK_PASS = "pass"
CHECK_FAIL = "fail"

#: Utilization is reported as a finite number: a zero capacity would otherwise
#: put an infinity on the wire, which is not JSON.
RATIO_CAP = 999.0

#: Tolerance on a utilization of exactly 1.0, so float noise is not a failure.
CHECK_TOL = 1e-9

#: A demand or capacity is a real engineering number; only a non-finite one is
#: clamped, and this is the value it lands on so the dict stays JSON.
_VALUE_CAP = 1e15

#: Referral actions run_design executes in its one bounded re-place pass.
#: Finding 19 removed `combine_footings` and `strap_required`: foundations own
#: those and design only sizes what it is handed.
REFERRAL_ACTIONS = (
    "add_secondary_beams",
    "confined_masonry_conversion",
    "joint_check_manual",
)


@dataclass
class CheckRow:
    """One code check: what was demanded, what the section gives, the verdict."""

    name: str
    clause: str
    demand: float
    capacity: float
    ratio: float
    status: str
    units: str = ""

    @staticmethod
    def evaluate(
        name: str,
        clause: str,
        demand: float,
        capacity: float,
        units: str = "",
        status: Optional[str] = None,
    ) -> "CheckRow":
        """Build a row, deriving the ratio and the verdict from demand/capacity.

        A check whose rule reads the other way round (a provided spacing against
        a maximum, say) is stated the same way: demand is what the section has,
        capacity is what the clause allows.
        """
        ratio = _ratio(demand, capacity)
        verdict = status if status is not None else (CHECK_PASS if ratio <= 1.0 + CHECK_TOL else CHECK_FAIL)
        return CheckRow(
            name=str(name),
            clause=str(clause),
            demand=float(demand),
            capacity=float(capacity),
            ratio=ratio,
            status=str(verdict),
            units=str(units),
        )

    @property
    def ok(self) -> bool:
        return self.status == CHECK_PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "clause": self.clause,
            "demand": _r(_finite(self.demand, _VALUE_CAP)),
            "capacity": _r(_finite(self.capacity, _VALUE_CAP)),
            "ratio": _r(_finite(self.ratio, RATIO_CAP)),
            "status": self.status,
            "units": self.units,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "CheckRow":
        return CheckRow(
            name=str(d.get("name", "")),
            clause=str(d.get("clause", "")),
            demand=float(d.get("demand", 0.0)),
            capacity=float(d.get("capacity", 0.0)),
            ratio=float(d.get("ratio", 0.0)),
            status=str(d.get("status", CHECK_PASS)),
            units=str(d.get("units", "")),
        )


def _ratio(demand: float, capacity: float) -> float:
    """Utilization, finite and non-negative: a zero capacity is full utilization."""
    d = float(demand)
    c = float(capacity)
    if c > 0.0:
        return _finite(d / c, RATIO_CAP)
    return 0.0 if d <= 0.0 else RATIO_CAP


@dataclass
class DesignResult:
    """What every designer returns, for every material, passing or not.

    `section` carries the dimensions in mm (b_mm, D_mm, d_mm, cover_mm and
    whatever else the member has: length_mm, thickness_mm, plan sizes).
    `materials` is `materials_block`. `bars` entries carry role, count, dia_mm,
    layer, zone_mm [from, to] or spacing_mm, and their own ld_mm, so the bar
    schedule needs no defaults (finding 24: there is deliberately no
    `quantities` field here, quantities.py owns the take-off). `stirrups`
    entries carry zone_mm, legs, dia_mm, spacing_mm and kind.

    `extras` is the material-specific extension slot finding 6 allows: masonry
    puts its `prescription` there and it lands at the top level of the wire
    dict, beside the shared keys, without any designer redefining this class.
    """

    element_id: str
    element_type: str
    section: Dict[str, Any] = field(default_factory=dict)
    materials: Dict[str, Any] = field(default_factory=dict)
    bars: List[Dict[str, Any]] = field(default_factory=list)
    stirrups: List[Dict[str, Any]] = field(default_factory=list)
    checks: List[CheckRow] = field(default_factory=list)
    status: str = STATUS_PASS
    resize_history: List[Dict[str, Any]] = field(default_factory=list)
    referrals: List[Dict[str, Any]] = field(default_factory=list)
    utilization_max: float = 0.0
    governing_check: str = ""
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    trace: List[TraceEntry] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)

    # -- assembly ---------------------------------------------------------

    def add_check(
        self,
        name: str,
        clause: str,
        demand: float,
        capacity: float,
        units: str = "",
        status: Optional[str] = None,
    ) -> CheckRow:
        """Append a check row and return it."""
        row = CheckRow.evaluate(name, clause, demand, capacity, units=units, status=status)
        self.checks.append(row)
        return row

    def add_bar(
        self,
        role: str,
        count: int,
        dia_mm: float,
        ld_mm: float,
        zone_mm: Sequence[float],
        layer: int = 1,
        spacing_mm: Optional[float] = None,
        **extra: Any
    ) -> Dict[str, Any]:
        """Append one bar entry. `ld_mm` and `zone_mm` are not optional.

        Finding 24: the bar schedule reads the development length and the zone
        the designer computed, and falls back to a flat 50d only where a bar
        carries none. A bar written through this method always carries both.
        """
        if ld_mm is None:
            raise ValueError("bar entry for " + str(role) + " needs its own ld_mm (finding 24)")
        pair = _zone_pair(zone_mm, role)
        entry = {
            "role": str(role),
            "count": int(count),
            "dia_mm": float(dia_mm),
            "layer": int(layer),
            "zone_mm": pair,
            "ld_mm": float(ld_mm),
        }  # type: Dict[str, Any]
        if spacing_mm is not None:
            entry["spacing_mm"] = float(spacing_mm)
        for key in sorted(extra):
            entry[str(key)] = extra[key]
        self.bars.append(entry)
        return entry

    def add_stirrup(
        self,
        zone_mm: Sequence[float],
        legs: int,
        dia_mm: float,
        spacing_mm: float,
        kind: str = "shear",
        **extra: Any
    ) -> Dict[str, Any]:
        """Append one stirrup, tie or hoop zone and return it."""
        entry = {
            "zone_mm": _zone_pair(zone_mm, kind),
            "legs": int(legs),
            "dia_mm": float(dia_mm),
            "spacing_mm": float(spacing_mm),
            "kind": str(kind),
        }  # type: Dict[str, Any]
        for key in sorted(extra):
            entry[str(key)] = extra[key]
        self.stirrups.append(entry)
        return entry

    def add_resize(self, from_value: Any, to_value: Any, reason: str) -> Dict[str, Any]:
        """Record one auto-resize step and mark the result `resized`."""
        entry = {"from": from_value, "to": to_value, "reason": str(reason)}
        self.resize_history.append(entry)
        if self.status == STATUS_PASS:
            self.status = STATUS_RESIZED
        return entry

    def add_referral(self, action: str, detail: Any = None) -> Dict[str, Any]:
        """Ask the orchestrator to change something design cannot change itself."""
        entry = {"action": str(action), "detail": detail}
        self.referrals.append(entry)
        return entry

    def add_warning(self, message: str) -> str:
        """Record a warning once; repeated text is not repeated on the report."""
        text = str(message)
        if text not in self.warnings:
            self.warnings.append(text)
        return text

    def add_note(self, message: str) -> str:
        """Record an informational simplification once."""
        text = str(message)
        if text not in self.notes:
            self.notes.append(text)
        return text

    # -- verdict ----------------------------------------------------------

    def worst_check(self) -> Optional[CheckRow]:
        """The check with the highest utilization; the earliest row wins a tie."""
        worst = None  # type: Optional[CheckRow]
        for row in self.checks:
            if worst is None or row.ratio > worst.ratio + CHECK_TOL:
                worst = row
        return worst

    def finalize(self) -> "DesignResult":
        """Compute utilization_max and governing_check, and honour a failed check.

        `governing_check` is filled from the worst row unless one was already
        pinned (`fail_with` pins the check that stopped the design, which is not
        always the highest ratio: a refused geometry has no ratio at all).
        A result carrying any failed row cannot claim `pass` or `resized`.
        """
        worst = self.worst_check()
        self.utilization_max = _r(worst.ratio) if worst is not None else 0.0
        if not self.governing_check and worst is not None:
            self.governing_check = worst.name
        if any(row.status == CHECK_FAIL for row in self.checks):
            self.status = STATUS_FAIL
        return self

    def fail_with(
        self,
        check: str,
        reason: str = "",
        clause: str = "",
        demand: Optional[float] = None,
        capacity: Optional[float] = None,
        units: str = "",
    ) -> "DesignResult":
        """Stop with status fail, fully populated, naming the governing check.

        With demand and capacity a row is added for it; without them the named
        check is assumed to be on the list already (or to be a refusal that has
        no numbers, such as a geometry the code will not allow at any size).
        """
        if demand is not None and capacity is not None:
            self.add_check(check, clause, demand, capacity, units=units, status=CHECK_FAIL)
        if reason:
            self.add_warning(reason)
        self.governing_check = str(check)
        self.finalize()
        self.status = STATUS_FAIL
        return self

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """The JSON-safe dict `model.design` carries. Deterministic and sorted."""
        out = {
            "element_id": self.element_id,
            "element_type": self.element_type,
            "section": _jsonable(self.section),
            "materials": _jsonable(self.materials),
            "bars": [_jsonable(bar) for bar in self.bars],
            "stirrups": [_jsonable(stirrup) for stirrup in self.stirrups],
            "checks": [row.to_dict() for row in self.checks],
            "status": self.status,
            "resize_history": [_jsonable(step) for step in self.resize_history],
            "referrals": [_jsonable(item) for item in self.referrals],
            "utilization_max": _r(_finite(self.utilization_max, RATIO_CAP)),
            "governing_check": self.governing_check,
            "warnings": [str(text) for text in self.warnings],
            "notes": [str(text) for text in self.notes],
            "trace": [entry.to_dict() for entry in self.trace],
        }  # type: Dict[str, Any]
        for key in sorted(self.extras):
            if str(key) not in out:
                out[str(key)] = _jsonable(self.extras[key])
        return out

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "DesignResult":
        """Rebuild a result from its dict; unknown keys land in `extras`."""
        result = DesignResult(
            element_id=str(d.get("element_id", "")),
            element_type=str(d.get("element_type", "")),
            section=dict(d.get("section") or {}),
            materials=dict(d.get("materials") or {}),
            bars=[dict(bar) for bar in (d.get("bars") or [])],
            stirrups=[dict(stirrup) for stirrup in (d.get("stirrups") or [])],
            checks=[CheckRow.from_dict(row) for row in (d.get("checks") or [])],
            status=str(d.get("status", STATUS_PASS)),
            resize_history=[dict(step) for step in (d.get("resize_history") or [])],
            referrals=[dict(item) for item in (d.get("referrals") or [])],
            utilization_max=float(d.get("utilization_max", 0.0)),
            governing_check=str(d.get("governing_check", "")),
            warnings=[str(text) for text in (d.get("warnings") or [])],
            notes=[str(text) for text in (d.get("notes") or [])],
            trace=[_trace_from_dict(entry) for entry in (d.get("trace") or [])],
        )
        for key in sorted(d):
            if key not in _RESULT_KEYS:
                result.extras[str(key)] = d[key]
        return result


_RESULT_KEYS = frozenset(
    (
        "element_id",
        "element_type",
        "section",
        "materials",
        "bars",
        "stirrups",
        "checks",
        "status",
        "resize_history",
        "referrals",
        "utilization_max",
        "governing_check",
        "warnings",
        "notes",
        "trace",
    )
)


def _zone_pair(zone_mm: Sequence[float], what: Any) -> List[float]:
    """A [from, to] pair in mm, or a ValueError naming what asked for it."""
    if zone_mm is None:
        raise ValueError("entry for " + str(what) + " needs a zone_mm [from, to] pair (finding 24)")
    try:
        values = [float(zone_mm[0]), float(zone_mm[1])]
    except (TypeError, IndexError, ValueError):
        raise ValueError("zone_mm for " + str(what) + " must be a [from, to] pair, got " + repr(zone_mm))
    return values


def _trace_from_dict(d: Mapping[str, Any]) -> TraceEntry:
    """A TraceEntry rebuilt from its dict (trace.py serializes, this reads back)."""
    return TraceEntry(
        code=str(d.get("code", "")),
        ref=str(d.get("ref", "")),
        title=str(d.get("title", "")),
        symbol=str(d.get("symbol", "")),
        inputs=dict(d.get("inputs") or {}),
        output=d.get("output"),
        units=str(d.get("units", "")),
        latex=d.get("latex"),
    )


# ---------------------------------------------------------------------------
# resize policy (spec section 8: uniform, bounded, disclosed)
# ---------------------------------------------------------------------------


def default_beam_depth_cap(overall_depth_mm: float, span_mm: float) -> float:
    """How deep a beam may grow: half again its placed depth, or span/8."""
    return max(1.5 * float(overall_depth_mm), float(span_mm) / 8.0)


@dataclass(frozen=True)
class ResizePolicy:
    """The one auto-resize ladder, shared by every designer and disclosed.

    Every step a designer takes under this policy is appended to
    `DesignResult.resize_history` with the check that forced it, and the walk
    is bounded by `max_iters` so a member can never loop.
    """

    beam_depth_step_mm: float = 25.0
    beam_depth_cap: Callable[[float, float], float] = default_beam_depth_cap
    beam_width_seq_mm: Tuple[float, ...] = (230.0, 300.0)
    column_step_mm: float = 50.0
    column_cap_mm: float = 600.0
    slab_step_mm: float = 10.0
    slab_cap_mm: float = 150.0
    footing_depth_step_mm: float = 50.0
    footing_plan_step_mm: float = 100.0
    max_iters: int = 12

    def to_dict(self) -> Dict[str, Any]:
        """The numeric fields. The depth cap is a callable and is not on the wire."""
        return {
            "beam_depth_step_mm": _r(self.beam_depth_step_mm),
            "beam_width_seq_mm": [_r(value) for value in self.beam_width_seq_mm],
            "column_step_mm": _r(self.column_step_mm),
            "column_cap_mm": _r(self.column_cap_mm),
            "slab_step_mm": _r(self.slab_step_mm),
            "slab_cap_mm": _r(self.slab_cap_mm),
            "footing_depth_step_mm": _r(self.footing_depth_step_mm),
            "footing_plan_step_mm": _r(self.footing_plan_step_mm),
            "max_iters": int(self.max_iters),
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "ResizePolicy":
        """A policy from an options block; absent keys keep their default."""
        base = ResizePolicy()
        seq = d.get("beam_width_seq_mm")
        return ResizePolicy(
            beam_depth_step_mm=float(d.get("beam_depth_step_mm", base.beam_depth_step_mm)),
            beam_depth_cap=base.beam_depth_cap,
            beam_width_seq_mm=tuple(float(value) for value in seq) if seq else base.beam_width_seq_mm,
            column_step_mm=float(d.get("column_step_mm", base.column_step_mm)),
            column_cap_mm=float(d.get("column_cap_mm", base.column_cap_mm)),
            slab_step_mm=float(d.get("slab_step_mm", base.slab_step_mm)),
            slab_cap_mm=float(d.get("slab_cap_mm", base.slab_cap_mm)),
            footing_depth_step_mm=float(d.get("footing_depth_step_mm", base.footing_depth_step_mm)),
            footing_plan_step_mm=float(d.get("footing_plan_step_mm", base.footing_plan_step_mm)),
            max_iters=int(d.get("max_iters", base.max_iters)),
        )


# ---------------------------------------------------------------------------
# bar selection: the one engine all four designers call
# ---------------------------------------------------------------------------

#: Area excess is scored in whole bands of this many percent, so the keys after
#: it (bar count, mixed diameters, layers) actually decide. Without a band a
#: layout saving one square millimetre would beat a plainer one every time.
EXCESS_BUCKET_PCT = 5.0

_AREA_TOL_MM2 = 1e-6


@dataclass(frozen=True)
class BarPrefs:
    """What a designer will accept from the catalogue for one bar group.

    `max_dia_ratio` is a detailing preference, not a code rule: mixing 25 mm
    corner bars with 8 mm fillers satisfies every clause and no detailer would
    build it, so combinations further apart than this ratio are not offered.
    """

    dias_mm: Tuple[int, ...] = MAIN_DIAS
    min_dia_mm: int = 0
    min_bars_per_layer: int = 2
    max_bars_per_layer: int = 8
    max_layers: int = 2
    max_distinct_dias: int = 2
    max_dia_ratio: float = 2.0
    agg_mm: float = DEFAULT_AGG_MM
    max_clear_spacing_mm: Optional[float] = None

    def key(self) -> Tuple[Any, ...]:
        """The hashable identity of the enumeration this prefs asks for."""
        return (
            tuple(int(dia) for dia in self.dias_mm),
            int(self.min_dia_mm),
            int(self.min_bars_per_layer),
            int(self.max_bars_per_layer),
            int(self.max_layers),
            int(self.max_distinct_dias),
            float(self.max_dia_ratio),
        )


@dataclass(frozen=True)
class BarLayout:
    """A chosen bar group: what to build, what it gives, what it costs in depth.

    `bars` is (count, dia_mm) groups, largest diameter first. `layer_dias_mm`
    is the same bars split into layers, the layer nearest the tension face
    first, which is where the larger diameters go. `d_adjust_mm` is how much
    the layering pulls the steel centroid away from that face: subtract it from
    a one-layer effective depth. `ok` is False when the requirement or the
    available width beat the catalogue; the layout is still the best available
    and `note` says what happened.
    """

    bars: Tuple[Tuple[int, int], ...]
    ast_prov_mm2: float
    layers: int
    d_adjust_mm: float
    ok: bool = True
    note: str = ""
    layer_dias_mm: Tuple[Tuple[int, ...], ...] = ()
    width_used_mm: float = 0.0

    @property
    def count(self) -> int:
        """Total number of bars."""
        return sum(int(group[0]) for group in self.bars)

    @property
    def max_dia_mm(self) -> int:
        return max(int(group[1]) for group in self.bars) if self.bars else 0

    @property
    def min_dia_mm(self) -> int:
        return min(int(group[1]) for group in self.bars) if self.bars else 0

    @property
    def label(self) -> str:
        """The detailer's shorthand, "2-20 + 2-16"."""
        return " + ".join(str(int(count)) + "-" + str(int(dia)) for count, dia in self.bars)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bars": [[int(count), int(dia)] for count, dia in self.bars],
            "label": self.label,
            "ast_prov_mm2": _r(self.ast_prov_mm2),
            "layers": int(self.layers),
            "d_adjust_mm": _r(self.d_adjust_mm),
            "ok": bool(self.ok),
            "note": self.note,
            "layer_dias_mm": [[int(dia) for dia in layer] for layer in self.layer_dias_mm],
            "width_used_mm": _r(self.width_used_mm),
        }


def _candidate_groups(key: Tuple[Any, ...]) -> Tuple[Tuple[Tuple[int, int], ...], ...]:
    """Every catalogue combination this prefs allows, sorted, cached per prefs."""
    cached = _CANDIDATE_CACHE.get(key)
    if cached is not None:
        return cached
    dias, min_dia, min_per_layer, max_per_layer, max_layers, max_distinct, max_ratio = key
    usable = tuple(sorted(int(dia) for dia in dias if int(dia) >= int(min_dia)))
    max_total = int(max_per_layer) * int(max_layers)
    min_total = max(1, int(min_per_layer))
    out = []  # type: List[Tuple[Tuple[int, int], ...]]
    for dia in usable:
        for count in range(min_total, max_total + 1):
            out.append(((count, dia),))
    if int(max_distinct) >= 2:
        for i in range(len(usable) - 1, 0, -1):
            big = usable[i]
            for j in range(i):
                small = usable[j]
                if float(big) / float(small) > float(max_ratio) + 1e-9:
                    continue
                for c_big in range(1, max_total):
                    for c_small in range(1, max_total - c_big + 1):
                        if c_big + c_small < min_total:
                            continue
                        # Symmetric about the section centreline: at most one
                        # group may have an odd count, and it sits centred.
                        if (c_big % 2) + (c_small % 2) > 1:
                            continue
                        out.append(((c_big, big), (c_small, small)))
    frozen = tuple(sorted(out))
    if len(_CANDIDATE_CACHE) >= _CANDIDATE_CACHE_MAX:
        _CANDIDATE_CACHE.clear()
    _CANDIDATE_CACHE[key] = frozen
    return frozen


_CANDIDATE_CACHE = {}  # type: Dict[Tuple[Any, ...], Tuple[Tuple[Tuple[int, int], ...], ...]]
#: The cache exists so a run of 100 elements enumerates once per prefs shape,
#: not once per element. It is cleared rather than grown without a bound.
_CANDIDATE_CACHE_MAX = 32


def _layer_split(bars_desc: Sequence[int], layers: int, max_per_layer: int, min_per_layer: int) -> Optional[List[List[int]]]:
    """Bars dealt into layers, largest first, outer layer taking any remainder."""
    total = len(bars_desc)
    if layers < 1 or total < layers * min_per_layer or total > layers * max_per_layer:
        return None
    base = total // layers
    extra = total % layers
    split = []  # type: List[List[int]]
    index = 0
    for i in range(layers):
        take = base + (1 if i < extra else 0)
        split.append(list(bars_desc[index : index + take]))
        index += take
    return split


def _layer_width_mm(layer: Sequence[int], gaps: Mapping[int, float]) -> float:
    """Width one layer needs: the bars plus a clear gap between each pair."""
    if not layer:
        return 0.0
    gap = gaps[max(layer)]
    return float(sum(layer)) + gap * (len(layer) - 1)


def _pack(
    bars_desc: Sequence[int],
    prefs: BarPrefs,
    width_avail_mm: float,
    gaps: Mapping[int, float],
) -> Optional[Tuple[int, List[List[int]], float]]:
    """The fewest layers this bar set fits in, or None when it never fits."""
    for layers in range(1, int(prefs.max_layers) + 1):
        split = _layer_split(bars_desc, layers, int(prefs.max_bars_per_layer), int(prefs.min_bars_per_layer))
        if split is None:
            continue
        widest = 0.0
        fits = True
        for layer in split:
            needed = _layer_width_mm(layer, gaps)
            if needed > float(width_avail_mm) + 1e-9:
                fits = False
                break
            if prefs.max_clear_spacing_mm is not None and len(layer) > 1:
                clear = (float(width_avail_mm) - float(sum(layer))) / (len(layer) - 1)
                if clear > float(prefs.max_clear_spacing_mm) + 1e-9:
                    fits = False
                    break
            widest = max(widest, needed)
        if fits:
            return layers, split, widest
    return None


def _d_adjust_mm(split: Sequence[Sequence[int]], agg_mm: float) -> float:
    """Distance from the outer layer to the steel centroid, mm."""
    if len(split) < 2:
        return 0.0
    max_dia = max(max(layer) for layer in split if layer)
    pitch = layer_pitch_mm(max_dia, agg_mm)
    total_area = 0.0
    moment = 0.0
    for index, layer in enumerate(split):
        area = sum(bar_area_mm2(dia) for dia in layer)
        total_area += area
        moment += area * index * pitch
    return moment / total_area if total_area > 0.0 else 0.0


def _score(groups: Sequence[Tuple[int, int]], ast_prov_mm2: float, ast_req_mm2: float, layers: int) -> Tuple[Any, ...]:
    """Lexicographic preference: area excess band, bar count, mixing, layers."""
    total_bars = sum(int(count) for count, _ in groups)
    mixed = 0 if len(groups) == 1 else 1
    if ast_req_mm2 > 0.0:
        excess_pct = max(0.0, (float(ast_prov_mm2) - float(ast_req_mm2)) / float(ast_req_mm2) * 100.0)
    else:
        excess_pct = 0.0
    bucket = int(math.ceil(round(excess_pct, 6) / EXCESS_BUCKET_PCT - 1e-9))
    return (bucket, total_bars, mixed, int(layers), tuple(groups))


def pick_bars(ast_req_mm2: float, width_avail_mm: float, prefs: Optional[BarPrefs] = None) -> BarLayout:
    """Choose the bar group for a required steel area in an available width.

    Enumerates the catalogue (2 to `max_bars_per_layer` bars a layer, at most
    two distinct diameters, symmetric), keeps the combinations that fit the
    width under the Cl 26.3.2 clear-spacing rule, layering when one layer will
    not hold them, and returns the best by area excess band, then bar count,
    then single diameter, then layer count.

    Never raises. When nothing in the catalogue reaches the requirement, or
    nothing fits the width at all, the best available layout comes back with
    `ok=False` and a note saying so, for the caller to disclose and resize.

    The clear-gap clause is evaluated once per catalogue diameter, so a trace
    sink records the rule, not the search.
    """
    prefs = prefs or BarPrefs()
    required = max(0.0, float(ast_req_mm2))
    width = float(width_avail_mm)
    gaps = {int(dia): min_bar_gap_mm(dia, prefs.agg_mm) for dia in sorted(set(int(d) for d in prefs.dias_mm))}

    best_ok = None  # type: Optional[Tuple[Tuple[Any, ...], BarLayout]]
    best_any = None  # type: Optional[Tuple[Tuple[Any, ...], BarLayout]]
    for groups in _candidate_groups(prefs.key()):
        bars_desc = []  # type: List[int]
        ast = 0.0
        for count, dia in groups:
            bars_desc.extend([int(dia)] * int(count))
            ast += count * bar_area_mm2(dia)
        packed = _pack(bars_desc, prefs, width, gaps)
        if packed is None:
            continue
        layers, split, used = packed
        layout = BarLayout(
            bars=tuple((int(count), int(dia)) for count, dia in groups),
            ast_prov_mm2=ast,
            layers=layers,
            d_adjust_mm=_d_adjust_mm(split, prefs.agg_mm),
            ok=True,
            note="",
            layer_dias_mm=tuple(tuple(layer) for layer in split),
            width_used_mm=used,
        )
        score = _score(groups, ast, required, layers)
        if ast + _AREA_TOL_MM2 >= required:
            if best_ok is None or score < best_ok[0]:
                best_ok = (score, layout)
        fallback_key = (-round(ast, 6),) + score
        if best_any is None or fallback_key < best_any[0]:
            best_any = (fallback_key, layout)

    if best_ok is not None:
        return best_ok[1]

    if best_any is not None:
        layout = best_any[1]
        return BarLayout(
            bars=layout.bars,
            ast_prov_mm2=layout.ast_prov_mm2,
            layers=layout.layers,
            d_adjust_mm=layout.d_adjust_mm,
            ok=False,
            note=(
                "required "
                + _mm2_text(required)
                + " exceeds the largest catalogue layout that fits "
                + _mm_text(width)
                + " ("
                + layout.label
                + " gives "
                + _mm2_text(layout.ast_prov_mm2)
                + "); widen the section"
            ),
            layer_dias_mm=layout.layer_dias_mm,
            width_used_mm=layout.width_used_mm,
        )

    # Nothing fits at all: report the smallest buildable group and say why.
    dia = min(int(d) for d in prefs.dias_mm if int(d) >= int(prefs.min_dia_mm)) if prefs.dias_mm else MAIN_DIAS[0]
    count = max(1, int(prefs.min_bars_per_layer))
    return BarLayout(
        bars=((count, dia),),
        ast_prov_mm2=count * bar_area_mm2(dia),
        layers=1,
        d_adjust_mm=0.0,
        ok=False,
        note=(
            "no catalogue layout fits the "
            + _mm_text(width)
            + " available between the stirrup legs under IS 456 Cl 26.3.2; "
            + str(count)
            + "-"
            + str(dia)
            + " shown, widen the section"
        ),
        layer_dias_mm=((dia,) * count,),
        width_used_mm=_layer_width_mm([dia] * count, gaps),
    )


def _mm2_text(value_mm2: float) -> str:
    return str(int(round(float(value_mm2)))) + " mm2"


def spacing_for_area(
    ast_req_mm2_per_m: float,
    dia_mm: float,
    max_spacing_mm: float = 300.0,
    module_mm: float = 10.0,
) -> float:
    """Mesh spacing, mm, for a required area per metre, rounded DOWN to a module.

    Down, never up: a spacing rounded up would provide less steel than asked
    for. The clause cap (3d or 300 main, 5d or 450 distribution, Cl 26.3.3) is
    applied before the rounding, and the result is never below one module.
    """
    area = bar_area_mm2(dia_mm)
    required = float(ast_req_mm2_per_m)
    spacing = float(max_spacing_mm) if required <= 0.0 else 1000.0 * area / required
    spacing = min(spacing, float(max_spacing_mm))
    return max(float(module_mm), round_down_mm(spacing, module_mm))


def area_for_spacing(dia_mm: float, spacing_mm: float) -> float:
    """Steel provided by a mesh, mm2 per metre width."""
    if float(spacing_mm) <= 0.0:
        raise ValueError("spacing_mm must be positive, got " + repr(spacing_mm))
    return 1000.0 * bar_area_mm2(dia_mm) / float(spacing_mm)


# ---------------------------------------------------------------------------
# material dispatch (populated by the designers, so dispatch never branches)
# ---------------------------------------------------------------------------

#: The material vocabulary. api-backend's options enum is generated from it.
MATERIALS = ("rcc", "masonry", "steel", "timber")

#: material -> the callable that designs one element of it. Filled in by
#: design/rcc, design/masonry and design/steel at import; a material with no
#: designer yet stays None, and the orchestrator discloses that rather than
#: growing a special case per material.
MATERIAL_DESIGNERS = {name: None for name in MATERIALS}  # type: Dict[str, Optional[Callable]]


def register_designer(material: str, designer: Callable) -> Callable:
    """Register the designer for a material. Unknown materials raise."""
    key = _word(material)
    if key not in MATERIAL_DESIGNERS:
        raise ValueError("unknown material: " + repr(material) + "; known: " + ", ".join(MATERIALS))
    if not callable(designer):
        raise ValueError("designer for " + key + " must be callable")
    MATERIAL_DESIGNERS[key] = designer
    return designer


def get_designer(material: str) -> Optional[Callable]:
    """The registered designer, or None when that material has none yet."""
    key = _word(material)
    if key not in MATERIAL_DESIGNERS:
        raise ValueError("unknown material: " + repr(material) + "; known: " + ", ".join(MATERIALS))
    return MATERIAL_DESIGNERS[key]
