"""Unreinforced masonry wall design: the IS 1905 checks and the IS 4326 specs.

What this module does, and just as importantly what it does not:

* It CHECKS every bearing wall segment of every storey against IS 1905:1987,
  through the clause callables in `codes/is1905.py`. Not one table value is
  transcribed here.
* It PRESCRIBES, which is the output an architect can act on: for each wall it
  sweeps the unit-strength by mortar-grade grid cheapest first and returns the
  cheapest pair that passes, then rolls the walls up into one building-level
  specification so the bill of quantities prices a single spec.
* It SPECIFIES the IS 4326 bands and vertical bars through `codes/is4326.py`,
  keyed on the resolved seismic category and the storey count. The geometry of
  those bands was already placed by `placement/masonry.py` (finding 23); this
  module says what steel goes in them.
* It does NOT compute the demand. Finding 21 gives both numbers to the loads
  and analysis layer: `analysis/takedown.py` owns `WallStress` with its axial
  per metre, its eccentricity and its e/t, and `analysis/diaphragm.py` owns the
  share of storey shear each wall carries. Both are consumed as they arrive.

Units. Dimensions are millimetres inside this module and every public field
carries its suffix, so a wall is `thickness_mm`, `length_mm`, `height_mm`.
Stresses are MPa, which is N/mm2, so a per-metre service load in kN/m over a
thickness in mm is a stress in MPa with no conversion factor at all:
`fa_mpa = n_kn_per_m / thickness_mm`. The IS 1905 callables are native in
metres (they were shipped that way and they are the source of truth), so the
conversion to metres happens at that one call boundary, through `mm_to_m`.

Determinism. Segments are resolved in a sorted order, the candidate grid is a
sorted tuple walked in a fixed cost order, the escalation ladder is bounded at
three rungs, and every exported dict is rounded and key-sorted by the shared
`DesignResult.to_dict`. The same model twice gives the same dicts.

Disclose, never hide. A wall the grid cannot satisfy still returns a fully
populated `DesignResult` with `status="fail"`, its governing check, the whole
stress waterfall it did manage to compute, the ladder it climbed in
`prescription["steps"]`, and a referral asking placement to confine the line.
Nothing in the public surface raises: a genuine code input error inside the
chain is caught and reported as a failed design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..codes import is1905, is4326
from ..codes.is1905 import CodeInputError
from ..codes.trace import TraceEntry, trace_into
from ..model import (
    Material,
    StructuralModel,
    WallLine,
    WallRole,
    opening_span,
    wall_axis,
)
from .common import (
    CHECK_FAIL,
    STATUS_FAIL,
    STATUS_RESIZED,
    DesignResult,
    MasonryMaterial,
    mm_to_m,
    register_designer,
)

__all__ = [
    "MATERIAL",
    "ELEMENT_TYPE_WALL",
    "ELEMENT_TYPE_BUILDING",
    "STAGE",
    "DEFAULT_UNIT_STRENGTHS_MPA",
    "DEFAULT_MORTAR_GRADES",
    "THICKNESS_LADDER_MM",
    "CHECK_SLENDERNESS",
    "CHECK_COMPRESSION",
    "CHECK_SHEAR",
    "CHECK_TENSION",
    "STEP_ASSUMED",
    "STEP_GRID",
    "STEP_THICKNESS",
    "STEP_CONFINED",
    "STEP_RC_FRAME",
    "REFERRAL_CONFINED",
    "BAND_KINDS",
    "BUILDING_ELEMENT_ID",
    "MasonryOptions",
    "WallSegment",
    "SegmentCheck",
    "evaluate_segment",
    "resolve_segments",
    "cheapest_passing",
    "resolve_category",
    "design_masonry_walls",
    "band_specification",
    "vertical_bar_specification",
]


#: The material key `design/common.py` dispatches on.
MATERIAL = "masonry"

#: `DesignResult.element_type` for one wall segment at one storey.
ELEMENT_TYPE_WALL = "masonry_wall"

#: `DesignResult.element_type` for the single building-level rollup entry.
ELEMENT_TYPE_BUILDING = "masonry_building"

#: Disclosure stage tag.
STAGE = "design.masonry"

#: The unit crushing strengths offered by default, IS 1905 Table 8 columns.
DEFAULT_UNIT_STRENGTHS_MPA = (3.5, 5.0, 7.5, 10.0, 12.5)

#: Mortar grades offered by default, WEAKEST (cheapest) FIRST. This ordering is
#: the cost model: a weaker mortar is the cheaper mortar. Lime grades are not
#: offered by default because their Table 7 slenderness cap is 20, not 27.
DEFAULT_MORTAR_GRADES = ("M2", "M1", "H2", "H1")

#: Standard brick wall thicknesses the escalation ladder climbs, mm.
THICKNESS_LADDER_MM = (190.0, 230.0, 345.0)

#: Check names, stable across the report, the API and the frontend.
CHECK_SLENDERNESS = "slenderness"
CHECK_COMPRESSION = "compression"
CHECK_SHEAR = "shear"
CHECK_TENSION = "tension"

#: Prescription ladder rungs, in the order they are climbed.
STEP_ASSUMED = "assumed_pair"
STEP_GRID = "material_grid"
STEP_THICKNESS = "thickness_bump"
STEP_CONFINED = "confined_masonry_conversion"
STEP_RC_FRAME = "frame_in_rc"

#: Referral action the orchestrator executes in its one bounded re-place pass.
REFERRAL_CONFINED = "confined_masonry_conversion"

#: Plan tolerance for wall end junction detection, metres.
_TOL_M = 1.0e-3

_ETA = 1.0e-9

#: Decimals on every exported float, matching `design/common.py`.
_DP = 6


def _r(value: float) -> float:
    """A float at the export precision, with no negative zero."""
    return round(float(value), _DP) + 0.0


def _r_opt(value: Optional[float]) -> Optional[float]:
    return None if value is None else _r(value)


def _word(value: Any) -> str:
    """Vocabulary word normalised the way the code modules normalise one."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _two_sf(value: float) -> str:
    """A value printed to two significant figures, for a message."""
    return "%.2g" % float(value)


# ---------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MasonryOptions:
    """Every knob the masonry designer reads, with its default and its unit.

    The candidate grid, the assumed pair and the thickness ladder are the three
    that change the answer; everything else describes the building. Finding 42
    makes this the single source for the API's options enum: the mortar grades
    offered are `codes/is1905.MORTAR_GRADES`, never a second literal list.
    """

    assumed_unit_strength_mpa: float = 7.5
    assumed_mortar_grade: str = "M1"
    unit_strengths_mpa: Tuple[float, ...] = DEFAULT_UNIT_STRENGTHS_MPA
    mortar_grades: Tuple[str, ...] = DEFAULT_MORTAR_GRADES
    thickness_ladder_mm: Tuple[float, ...] = THICKNESS_LADDER_MM
    unit_h_over_w: float = 0.75
    tension_policy: str = "no_tension"
    bending_plane: str = "normal_to_bed"
    zone: str = "III"
    importance: float = 1.0
    category: Optional[str] = None
    storeys: Optional[int] = None
    roof_type: str = "flat"
    cast_in_situ_slab: bool = True
    soft_soil: bool = False
    top_restraint: str = "full"
    bottom_restraint: str = "full"
    slab_bearing_m: float = 0.0
    default_storey_height_m: float = 3.0
    band_span_m: Optional[float] = None
    dead_fraction: float = 0.7
    dead_axial_kn_m: Mapping[str, float] = field(default_factory=dict)
    allow_confined_referral: bool = True
    confined_relief_cap: float = 2.0
    use_pilasters: bool = True

    def __post_init__(self) -> None:
        grade = str(self.assumed_mortar_grade).strip().upper()
        if grade not in is1905.MORTAR_GRADES:
            raise ValueError(
                "assumed_mortar_grade " + repr(self.assumed_mortar_grade) + " is not an IS 1905 Table 1 grade; known: "
                + ", ".join(is1905.MORTAR_GRADES)
            )
        object.__setattr__(self, "assumed_mortar_grade", grade)

        grades = []  # type: List[str]
        for item in self.mortar_grades:
            token = str(item).strip().upper()
            if token not in is1905.MORTAR_GRADES:
                raise ValueError("mortar grade " + repr(item) + " is not an IS 1905 Table 1 grade")
            if token not in grades:
                grades.append(token)
        if not grades:
            raise ValueError("mortar_grades must offer at least one grade")
        object.__setattr__(self, "mortar_grades", tuple(grades))

        strengths = sorted({float(value) for value in self.unit_strengths_mpa})
        if not strengths:
            raise ValueError("unit_strengths_mpa must offer at least one unit strength")
        if min(strengths) <= 0.0:
            raise ValueError("unit strengths must be positive MPa values")
        object.__setattr__(self, "unit_strengths_mpa", tuple(strengths))

        ladder = sorted({float(value) for value in self.thickness_ladder_mm})
        object.__setattr__(self, "thickness_ladder_mm", tuple(ladder))

        policy = _word(self.tension_policy)
        if policy not in is1905.TENSION_POLICIES:
            raise ValueError("tension_policy must be one of " + ", ".join(is1905.TENSION_POLICIES))
        object.__setattr__(self, "tension_policy", policy)

        plane = _word(self.bending_plane)
        if plane not in is1905.BENDING_PLANES:
            raise ValueError("bending_plane must be one of " + ", ".join(is1905.BENDING_PLANES))
        object.__setattr__(self, "bending_plane", plane)

        for name in ("top_restraint", "bottom_restraint"):
            token = _word(getattr(self, name))
            if token not in is1905.RESTRAINTS:
                raise ValueError(name + " must be one of " + ", ".join(is1905.RESTRAINTS))
            object.__setattr__(self, name, token)

        if self.category is not None:
            token = str(self.category).strip().upper()
            if token not in is4326.CATEGORIES:
                raise ValueError("category " + repr(self.category) + " is not an IS 4326 category")
            object.__setattr__(self, "category", token)

        object.__setattr__(self, "roof_type", _word(self.roof_type))
        if not 0.0 < float(self.dead_fraction) <= 1.0:
            raise ValueError("dead_fraction must sit in (0, 1], got " + repr(self.dead_fraction))
        dead = {}  # type: Dict[str, float]
        for key in sorted(self.dead_axial_kn_m, key=_demand_key):
            dead[_demand_key(key)] = float(self.dead_axial_kn_m[key])
        object.__setattr__(self, "dead_axial_kn_m", dead)

    # -- derived ----------------------------------------------------------

    def assumed_material(self) -> MasonryMaterial:
        """The pair the forward check runs on before any prescription."""
        return MasonryMaterial(
            unit_strength_mpa=float(self.assumed_unit_strength_mpa),
            mortar_grade=self.assumed_mortar_grade,
        )

    def candidate_pairs(self) -> Tuple[MasonryMaterial, ...]:
        """The candidate grid in cost order, cheapest first.

        Cost order is a stated convention, not a price list: the weaker spec is
        the cheaper spec, unit strength first and mortar grade second, so the
        walk starts at the weakest unit in the weakest offered mortar and ends
        at the strongest unit in the strongest mortar. It is a total order, so
        the sweep is deterministic.
        """
        pairs = []  # type: List[MasonryMaterial]
        for strength in self.unit_strengths_mpa:
            for grade in self.mortar_grades:
                pairs.append(MasonryMaterial(unit_strength_mpa=strength, mortar_grade=grade))
        return tuple(pairs)

    def cost_rank(self, material: MasonryMaterial) -> Tuple[float, int]:
        """Position of a pair in the cost order; a pair off the grid sorts last."""
        try:
            grade_index = self.mortar_grades.index(material.mortar_grade)
        except ValueError:
            grade_index = len(self.mortar_grades)
        return (float(material.unit_strength_mpa), grade_index)

    def next_thickness_mm(self, thickness_mm: float) -> Optional[float]:
        """The next standard thickness above this one, or None at the top."""
        for value in self.thickness_ladder_mm:
            if value > float(thickness_mm) + _ETA:
                return value
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assumed_unit_strength_mpa": _r(self.assumed_unit_strength_mpa),
            "assumed_mortar_grade": self.assumed_mortar_grade,
            "unit_strengths_mpa": [_r(v) for v in self.unit_strengths_mpa],
            "mortar_grades": list(self.mortar_grades),
            "thickness_ladder_mm": [_r(v) for v in self.thickness_ladder_mm],
            "unit_h_over_w": _r(self.unit_h_over_w),
            "tension_policy": self.tension_policy,
            "bending_plane": self.bending_plane,
            "zone": str(self.zone),
            "importance": _r(self.importance),
            "category": self.category,
            "storeys": None if self.storeys is None else int(self.storeys),
            "roof_type": self.roof_type,
            "cast_in_situ_slab": bool(self.cast_in_situ_slab),
            "soft_soil": bool(self.soft_soil),
            "top_restraint": self.top_restraint,
            "bottom_restraint": self.bottom_restraint,
            "slab_bearing_m": _r(self.slab_bearing_m),
            "default_storey_height_m": _r(self.default_storey_height_m),
            "band_span_m": _r_opt(self.band_span_m),
            "dead_fraction": _r(self.dead_fraction),
            "allow_confined_referral": bool(self.allow_confined_referral),
            "confined_relief_cap": _r(self.confined_relief_cap),
            "use_pilasters": bool(self.use_pilasters),
        }

    @staticmethod
    def coerce(options: Any) -> "MasonryOptions":
        """`MasonryOptions` from None, from an instance, or from a mapping."""
        if options is None:
            return MasonryOptions()
        if isinstance(options, MasonryOptions):
            return options
        if isinstance(options, Mapping):
            known = {
                "assumed_unit_strength_mpa",
                "assumed_mortar_grade",
                "unit_strengths_mpa",
                "mortar_grades",
                "thickness_ladder_mm",
                "unit_h_over_w",
                "tension_policy",
                "bending_plane",
                "zone",
                "importance",
                "category",
                "storeys",
                "roof_type",
                "cast_in_situ_slab",
                "soft_soil",
                "top_restraint",
                "bottom_restraint",
                "slab_bearing_m",
                "default_storey_height_m",
                "band_span_m",
                "dead_fraction",
                "dead_axial_kn_m",
                "allow_confined_referral",
                "confined_relief_cap",
                "use_pilasters",
            }
            fields = {key: options[key] for key in sorted(options) if key in known}
            masonry = options.get("masonry")
            if isinstance(masonry, Mapping):
                for key in sorted(masonry):
                    if key in known:
                        fields[key] = masonry[key]
            return MasonryOptions(**fields)
        raise ValueError("options must be a MasonryOptions, a mapping or None, got " + repr(type(options)))


def _demand_key(key: Any) -> str:
    """The `<wall_id>@s<storey>` key both demand lookups are keyed on."""
    if isinstance(key, (tuple, list)) and len(key) == 2:
        return str(key[0]) + "@s" + str(int(key[1]))
    return str(key)


# ---------------------------------------------------------------------------
# the resolved wall segment: one wall, one storey, geometry plus demand
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WallSegment:
    """One bearing wall segment at one storey, resolved and ready to check.

    Everything the IS 1905 chain needs and nothing it does not. The demand
    fields arrive from the analysis layer verbatim (finding 21): `n_kn_per_m`
    and `e_over_t` are `WallStress`, `shear_kn` is the diaphragm share. Where a
    number had to be assumed rather than read, the matching `*_source` string
    says so and the designer turns it into a disclosed note.
    """

    wall_id: str
    storey: int
    storeys_total: int
    thickness_mm: float
    length_mm: float
    net_length_mm: float
    height_mm: float
    n_kn_per_m: float
    e_over_t: float
    dead_kn_per_m: float
    shear_kn: float
    top_restraint: str = "full"
    bottom_restraint: str = "full"
    end_conditions: Optional[Tuple[str, str]] = None
    role: str = "interior"
    openings_known: bool = True
    dead_source: str = ""
    shear_source: str = ""
    height_source: str = ""
    pier_spacing_mm: Optional[float] = None
    pier_width_mm: Optional[float] = None
    pier_depth_mm: Optional[float] = None

    @property
    def element_id(self) -> str:
        """The id a DesignResult and an analysis envelope share."""
        return self.wall_id + "@s" + str(int(self.storey))

    def loaded_area_m2(self, thickness_mm: Optional[float] = None) -> float:
        """Plan area of the loaded segment, m2, for the Cl 5.4.1.2 factor."""
        t = float(self.thickness_mm if thickness_mm is None else thickness_mm)
        return mm_to_m(t) * mm_to_m(self.net_length_mm)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "storey": int(self.storey),
            "storeys_total": int(self.storeys_total),
            "thickness_mm": _r(self.thickness_mm),
            "length_mm": _r(self.length_mm),
            "net_length_mm": _r(self.net_length_mm),
            "height_mm": _r(self.height_mm),
            "n_kn_per_m": _r(self.n_kn_per_m),
            "e_over_t": _r(self.e_over_t),
            "dead_kn_per_m": _r(self.dead_kn_per_m),
            "shear_kn": _r(self.shear_kn),
            "top_restraint": self.top_restraint,
            "bottom_restraint": self.bottom_restraint,
            "end_conditions": None if self.end_conditions is None else list(self.end_conditions),
            "role": self.role,
            "openings_known": bool(self.openings_known),
            "dead_source": self.dead_source,
            "shear_source": self.shear_source,
            "height_source": self.height_source,
            "pier_spacing_mm": _r_opt(self.pier_spacing_mm),
            "pier_width_mm": _r_opt(self.pier_width_mm),
            "pier_depth_mm": _r_opt(self.pier_depth_mm),
        }


# ---------------------------------------------------------------------------
# one evaluation of one segment on one material
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentCheck:
    """The whole IS 1905 waterfall for one segment on one candidate material.

    This is what the report renders: heff, leff and teff with their table
    citations, the slenderness ratio against its cap, then the
    fb -> ks -> ka -> kp -> fc chain, then the three utilizations. `ks` and
    `fc_mpa` are None exactly when IS 1905 Table 9 has no value for the pair,
    which `ks_reason` states in words; that is a failure, never a guess.
    """

    thickness_mm: float
    unit_strength_mpa: float
    mortar_grade: str
    heff_m: float
    leff_m: Optional[float]
    teff_m: float
    slenderness_ratio: float
    slenderness_limit: float
    slenderness_ok: bool
    fb_mpa: float
    ks: Optional[float]
    ks_reason: str
    ka: float
    kp: float
    fc_mpa: Optional[float]
    fa_mpa: float
    utilization_compression: float
    fd_mpa: float
    fs_mpa: float
    tau_mpa: float
    utilization_shear: float
    ft_mpa: float
    tension_demand_mpa: float
    utilization_tension: float
    ok: bool
    governing_check: str
    utilization_max: float

    @property
    def verdict(self) -> str:
        """`OK` or `FAIL`, the word the SP 20 style vectors are written in."""
        return "OK" if self.ok else "FAIL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thickness_mm": _r(self.thickness_mm),
            "unit_strength_mpa": _r(self.unit_strength_mpa),
            "mortar_grade": self.mortar_grade,
            "heff_m": _r(self.heff_m),
            "leff_m": _r_opt(self.leff_m),
            "teff_m": _r(self.teff_m),
            "slenderness_ratio": _r(self.slenderness_ratio),
            "slenderness_limit": _r(self.slenderness_limit),
            "slenderness_ok": bool(self.slenderness_ok),
            "fb_mpa": _r(self.fb_mpa),
            "ks": _r_opt(self.ks),
            "ks_reason": self.ks_reason,
            "ka": _r(self.ka),
            "kp": _r(self.kp),
            "fc_mpa": _r_opt(self.fc_mpa),
            "fa_mpa": _r(self.fa_mpa),
            "utilization_compression": _r(self.utilization_compression),
            "fd_mpa": _r(self.fd_mpa),
            "fs_mpa": _r(self.fs_mpa),
            "tau_mpa": _r(self.tau_mpa),
            "utilization_shear": _r(self.utilization_shear),
            "ft_mpa": _r(self.ft_mpa),
            "tension_demand_mpa": _r(self.tension_demand_mpa),
            "utilization_tension": _r(self.utilization_tension),
            "ok": bool(self.ok),
            "verdict": self.verdict,
            "governing_check": self.governing_check,
            "utilization_max": _r(self.utilization_max),
        }


#: Utilization reported where a capacity is zero; matches `common.RATIO_CAP`.
_RATIO_CAP = 999.0


def _ratio(demand: float, capacity: Optional[float]) -> float:
    """Utilization, finite: a zero or absent capacity is full utilization."""
    if capacity is None:
        return 0.0 if float(demand) <= 0.0 else _RATIO_CAP
    if float(capacity) > 0.0:
        return min(float(demand) / float(capacity), _RATIO_CAP)
    return 0.0 if float(demand) <= 0.0 else _RATIO_CAP


def evaluate_segment(
    segment: WallSegment,
    material: MasonryMaterial,
    options: MasonryOptions,
    thickness_mm: Optional[float] = None,
) -> SegmentCheck:
    """Run the whole IS 1905 chain for one segment on one candidate material.

    Pure: it reads nothing but its arguments and writes nothing but its return
    value, so the prescription sweep can call it eighty times without leaving a
    mark. Every number comes from a `codes/is1905.py` callable, so a call made
    inside a `trace_into` block lands the full waterfall in the sink.

    `thickness_mm` overrides the segment thickness for one evaluation, which is
    how the escalation ladder tries a thicker wall without rebuilding it.
    """
    t_mm = float(segment.thickness_mm if thickness_mm is None else thickness_mm)
    grade = material.mortar_grade

    heff_m = is1905.effective_height(
        mm_to_m(segment.height_mm), segment.top_restraint, segment.bottom_restraint
    )
    leff_m = None  # type: Optional[float]
    if segment.end_conditions is not None:
        leff_m = is1905.effective_length(mm_to_m(segment.length_mm), segment.end_conditions)
    if segment.pier_spacing_mm is not None and segment.pier_width_mm is not None and segment.pier_depth_mm is not None:
        teff_m = is1905.effective_thickness(
            mm_to_m(t_mm),
            pier_spacing_m=mm_to_m(segment.pier_spacing_mm),
            pier_width_m=mm_to_m(segment.pier_width_mm),
            pier_depth_m=mm_to_m(segment.pier_depth_mm),
        )
    else:
        teff_m = is1905.effective_thickness(mm_to_m(t_mm))

    slenderness = is1905.slenderness_ratio(heff_m, leff_m, teff_m)
    slenderness_ok = is1905.check_max_slenderness(slenderness, segment.storeys_total, grade)
    slenderness_limit = is1905.max_slenderness(grade)

    fb_mpa = is1905.basic_compressive_stress(material.unit_strength_mpa, grade)
    reduction = is1905.stress_reduction_factor(slenderness, segment.e_over_t)
    ka = is1905.area_reduction_factor(segment.loaded_area_m2(t_mm))
    kp = is1905.shape_modification_factor(options.unit_h_over_w, material.unit_strength_mpa)
    fc_mpa = None  # type: Optional[float]
    if reduction.ks is not None:
        fc_mpa = is1905.permissible_compressive_stress(fb_mpa, reduction.ks, ka, kp)

    # A per-metre service load in kN/m over a thickness in mm is already MPa.
    fa_mpa = float(segment.n_kn_per_m) / t_mm
    utilization_compression = _ratio(fa_mpa, fc_mpa)

    fd_mpa = float(segment.dead_kn_per_m) / t_mm
    fs_mpa = is1905.permissible_shear(fd_mpa)
    net_length_mm = max(float(segment.net_length_mm), _ETA)
    tau_mpa = abs(float(segment.shear_kn)) * 1.0e3 / (t_mm * net_length_mm)
    utilization_shear = _ratio(tau_mpa, fs_mpa)

    ft_mpa = is1905.permissible_tension(options.bending_plane, grade, options.tension_policy)
    # Elastic stress at the far face of an eccentrically loaded section: the
    # section is in full compression up to the kern, e/t = 1/6, and develops
    # fa (6 e/t - 1) of tension past it.
    tension_demand_mpa = 0.0
    if float(segment.e_over_t) > (1.0 / 6.0) + _ETA:
        tension_demand_mpa = fa_mpa * (6.0 * float(segment.e_over_t) - 1.0)
    utilization_tension = _ratio(tension_demand_mpa, ft_mpa)

    rows = (
        (CHECK_SLENDERNESS, _ratio(slenderness, slenderness_limit)),
        (CHECK_COMPRESSION, utilization_compression),
        (CHECK_SHEAR, utilization_shear),
        (CHECK_TENSION, utilization_tension),
    )
    governing = rows[0][0]
    worst = rows[0][1]
    for name, ratio in rows[1:]:
        if ratio > worst + 1.0e-9:
            governing = name
            worst = ratio
    if not slenderness_ok:
        governing = CHECK_SLENDERNESS
    ok = bool(slenderness_ok) and reduction.ks is not None and worst <= 1.0 + 1.0e-9

    return SegmentCheck(
        thickness_mm=t_mm,
        unit_strength_mpa=float(material.unit_strength_mpa),
        mortar_grade=grade,
        heff_m=heff_m,
        leff_m=leff_m,
        teff_m=teff_m,
        slenderness_ratio=slenderness,
        slenderness_limit=slenderness_limit,
        slenderness_ok=bool(slenderness_ok),
        fb_mpa=fb_mpa,
        ks=reduction.ks,
        ks_reason=reduction.reason,
        ka=ka,
        kp=kp,
        fc_mpa=fc_mpa,
        fa_mpa=fa_mpa,
        utilization_compression=utilization_compression,
        fd_mpa=fd_mpa,
        fs_mpa=fs_mpa,
        tau_mpa=tau_mpa,
        utilization_shear=utilization_shear,
        ft_mpa=ft_mpa,
        tension_demand_mpa=tension_demand_mpa,
        utilization_tension=utilization_tension,
        ok=ok,
        governing_check=governing,
        utilization_max=worst,
    )


# ---------------------------------------------------------------------------
# consuming what the analysis layer owns (finding 21)
# ---------------------------------------------------------------------------


def _get(record: Any, name: str, default: Any = None) -> Any:
    """Field of a dataclass record or of its serialized mapping."""
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _unpack_stresses(source: Any) -> Tuple[List[Any], Dict[str, Any]]:
    """`(wall stress records, footing wall loads)` from whatever was handed in.

    Three shapes are accepted, all of them things `analysis/takedown.py` emits:
    a `TakedownResult` (or its `to_dict()`), from which the wall stresses and
    the dead-only base loads are both read, or a bare sequence of `WallStress`
    records (or their dicts), which carries the stresses alone.
    """
    if source is None:
        return ([], {})
    stresses = _get(source, "wall_stresses")
    if stresses is not None:
        footing = _get(source, "footing_loads") or {}
        walls = footing.get("walls", {}) if isinstance(footing, Mapping) else {}
        return (list(stresses), dict(walls))
    if isinstance(source, Mapping):
        raise ValueError("a mapping handed to design_masonry_walls must carry a wall_stresses key")
    return (list(source), {})


def _shear_lookup(lateral: Any) -> Dict[str, Tuple[float, str]]:
    """`{wall@storey: (V_kN, source)}` from the diaphragm distribution.

    A wall participates in exactly one direction, so the entry it appears under
    is its own; the larger magnitude wins if a caller ever supplies both. The
    shear is the whole segment shear in kN, which the check divides by the net
    plan area of the wall.
    """
    out = {}  # type: Dict[str, Tuple[float, str]]
    if lateral is None:
        return out

    storeys = _get(lateral, "storeys")
    if storeys is not None:
        for block in storeys:
            direction = str(_get(block, "direction", ""))
            for share in _get(block, "elements", []) or []:
                if str(_get(share, "element_type", "")) != "wall":
                    continue
                element_id = str(_get(share, "element_id", ""))
                storey = int(_get(share, "storey", 0))
                value = abs(float(_get(share, "v_kn", 0.0) or 0.0))
                key = _demand_key((element_id, storey))
                previous = out.get(key)
                if previous is None or value > previous[0]:
                    out[key] = (
                        value,
                        "diaphragm share along " + direction + " at storey " + str(storey),
                    )
        return out

    if isinstance(lateral, Mapping):
        for key in sorted(lateral, key=_demand_key):
            out[_demand_key(key)] = (abs(float(lateral[key])), "in-plane shear supplied by the caller")
        return out

    raise ValueError("lateral must be a LateralResult, its dict, a mapping of shears, or None")


def _net_length_mm(wall: WallLine) -> float:
    """Bearing length in mm: the gross length less the union of its openings."""
    gross_m = float(wall.length_m())
    spans = []  # type: List[Tuple[float, float]]
    for opening in wall.openings:
        s0, s1 = opening_span(wall, opening)
        low = max(0.0, min(float(s0), float(s1)))
        high = min(gross_m, max(float(s0), float(s1)))
        if high > low + _ETA:
            spans.append((low, high))
    spans.sort()
    covered = 0.0
    reach = None  # type: Optional[float]
    for low, high in spans:
        if reach is None or low > reach:
            covered += high - low
            reach = high
        elif high > reach:
            covered += high - reach
            reach = high
    net_m = max(gross_m - covered, 0.0)
    return net_m * 1.0e3


def _end_condition(
    model: StructuralModel,
    wall: WallLine,
    orient: str,
    position_m: float,
    station_m: float,
    outward: float,
) -> str:
    """One end of a wall read against the walls around it, IS 1905 Table 5.

    Continuity is looked for first: where a masonry wall on the same centreline
    runs on past this end, the segment boundary is an artefact of how the plan
    was cut up and the wall is genuinely continuous there. Failing that, a
    perpendicular wall landing on the end is a cross wall. Failing both, the
    end is free.
    """
    continuous = False
    cross = False
    for other in sorted(model.walls_on(wall.storey), key=lambda item: item.id):
        if other.id == wall.id or not _is_masonry(other):
            continue
        axis = wall_axis(other)
        if axis is None:
            continue
        other_orient, other_pos, other_lo, other_hi = axis
        if other_orient == orient:
            if abs(other_pos - position_m) > _TOL_M:
                continue
            if other_hi < station_m - _TOL_M or other_lo > station_m + _TOL_M:
                continue
            beyond = (other_hi > station_m + _TOL_M) if outward > 0.0 else (other_lo < station_m - _TOL_M)
            if beyond:
                continuous = True
        else:
            if abs(other_pos - station_m) > _TOL_M:
                continue
            if other_lo - _TOL_M <= position_m <= other_hi + _TOL_M:
                cross = True
    if continuous:
        return "continuous"
    if cross:
        return "cross_wall"
    return "free"


def _end_conditions(model: StructuralModel, wall: WallLine) -> Optional[Tuple[str, str]]:
    """Both ends of a wall, or None where Table 5 offers no case at all.

    A wall free at both ends has no effective length: IS 1905 Table 5 has no
    row for it and the callable refuses one, so the height term governs the
    slenderness on its own and None is what says so.
    """
    axis = wall_axis(wall)
    if axis is None:
        return None
    orient, position_m, low_m, high_m = axis
    first = _end_condition(model, wall, orient, position_m, low_m, -1.0)
    second = _end_condition(model, wall, orient, position_m, high_m, 1.0)
    if first == "free" and second == "free":
        return None
    return (first, second)


def _is_masonry(wall: WallLine) -> bool:
    """A wall this module designs: masonry, and not a parapet or a railing."""
    material = wall.material.value if hasattr(wall.material, "value") else str(wall.material)
    role = wall.role.value if hasattr(wall.role, "value") else str(wall.role)
    if material != Material.BRICK_MASONRY.value:
        return False
    return role not in (WallRole.PARAPET.value, WallRole.RAILING.value)


def _pier_params(
    model: StructuralModel, wall: WallLine, thickness_mm: float
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Table 6 pier inputs from the pilasters `placement/masonry.py` injected.

    The stiffening spacing is the LONGEST bay between consecutive pilasters
    with the two wall ends counted as stiffened, which is the bay that governs.
    A wall with no pilaster returns three Nones and is checked solid.
    """
    placement = model.meta.get("masonry_placement")
    if not isinstance(placement, Mapping):
        return (None, None, None)
    rows = placement.get("pilasters") or []
    axis = wall_axis(wall)
    if axis is None:
        return (None, None, None)
    orient, _position_m, low_m, high_m = axis
    stations = []  # type: List[float]
    width_mm = None  # type: Optional[float]
    projection_mm = None  # type: Optional[float]
    for row in rows:
        if str(_get(row, "wall_id", "")) != wall.id:
            continue
        if int(_get(row, "storey", wall.storey)) != int(wall.storey):
            continue
        station = float(_get(row, "x_m", 0.0)) if orient == "h" else float(_get(row, "y_m", 0.0))
        stations.append(station)
        width_mm = float(_get(row, "t_mm", thickness_mm))
        projection_mm = float(_get(row, "projection_mm", 0.0))
    if not stations or width_mm is None or projection_mm is None:
        return (None, None, None)
    marks = sorted([low_m] + stations + [high_m])
    spacing_m = max(marks[index + 1] - marks[index] for index in range(len(marks) - 1))
    if spacing_m <= _ETA or width_mm <= _ETA:
        return (None, None, None)
    return (spacing_m * 1.0e3, width_mm, thickness_mm + projection_mm)


def resolve_segments(
    model: StructuralModel,
    wall_stresses: Any = None,
    lateral: Any = None,
    options: Optional[MasonryOptions] = None,
) -> List[WallSegment]:
    """Every masonry bearing wall segment the analysis layer reported, resolved.

    One segment per wall per storey, in `(storey, wall_id)` order. Geometry is
    read off the model, demand off the analysis records, and the two numbers
    the analysis layer does not carry, the dead-only axial for the shear check
    and the in-plane shear itself, are looked up in that order of preference:
    an explicit value from the caller, the takedown's dead base load, then a
    disclosed fraction of the service axial.
    """
    settings = MasonryOptions.coerce(options)
    records, footing_walls = _unpack_stresses(wall_stresses)
    shears = _shear_lookup(lateral)

    storeys_total = settings.storeys
    if storeys_total is None:
        storeys_total = len(model.storeys) if model.storeys else 1
    storeys_total = max(int(storeys_total), 1)

    ordered = []  # type: List[Tuple[int, str, Any]]
    for record in records:
        wall_id = str(_get(record, "wall_id", ""))
        ordered.append((int(_get(record, "storey", 0)), wall_id, record))
    ordered.sort(key=lambda item: (item[0], item[1]))

    segments = []  # type: List[WallSegment]
    for storey, wall_id, record in ordered:
        wall = model.by_id(wall_id)
        if not isinstance(wall, WallLine) or int(wall.storey) != storey:
            continue
        if not _is_masonry(wall) or wall.bearing is False:
            continue
        thickness_mm = float(wall.thickness_m) * 1.0e3
        length_mm = float(wall.length_m()) * 1.0e3
        if thickness_mm <= _ETA or length_mm <= _ETA:
            continue

        storey_record = model.storey(storey)
        if storey_record is not None:
            height_m = float(storey_record.height_m) - float(settings.slab_bearing_m)
            height_source = "storey height less the stated slab bearing"
        else:
            height_m = float(settings.default_storey_height_m) - float(settings.slab_bearing_m)
            height_source = "no storey record; the default storey height was assumed"
        height_m = max(height_m, _ETA)

        key = _demand_key((wall_id, storey))
        n_kn_per_m = float(_get(record, "n_kn_m", 0.0) or 0.0)
        e_over_t = float(_get(record, "e_over_t", 0.0) or 0.0)

        if key in settings.dead_axial_kn_m:
            dead_kn_per_m = float(settings.dead_axial_kn_m[key])
            dead_source = "dead-only axial supplied by the caller"
        elif wall_id in footing_walls and "n_dl_kn_m" in (footing_walls[wall_id] or {}):
            dead_kn_per_m = float(footing_walls[wall_id]["n_dl_kn_m"])
            dead_source = "dead-only base load from the takedown footing loads"
        else:
            dead_kn_per_m = float(settings.dead_fraction) * n_kn_per_m
            dead_source = (
                "no dead-only axial available; taken as "
                + repr(float(settings.dead_fraction))
                + " of the service axial, which lowers the permissible shear"
            )
        dead_kn_per_m = max(min(dead_kn_per_m, n_kn_per_m), 0.0)

        shear_kn, shear_source = shears.get(key, (0.0, "no lateral distribution supplied; in-plane shear taken as zero"))

        piers = (None, None, None)  # type: Tuple[Optional[float], Optional[float], Optional[float]]
        if settings.use_pilasters:
            piers = _pier_params(model, wall, thickness_mm)

        segments.append(
            WallSegment(
                wall_id=wall_id,
                storey=storey,
                storeys_total=storeys_total,
                thickness_mm=thickness_mm,
                length_mm=length_mm,
                net_length_mm=_net_length_mm(wall),
                height_mm=height_m * 1.0e3,
                n_kn_per_m=n_kn_per_m,
                e_over_t=e_over_t,
                dead_kn_per_m=dead_kn_per_m,
                shear_kn=float(shear_kn),
                top_restraint=settings.top_restraint,
                bottom_restraint=settings.bottom_restraint,
                end_conditions=_end_conditions(model, wall),
                role=wall.role.value if hasattr(wall.role, "value") else str(wall.role),
                openings_known=bool(model.doors_known(storey)),
                dead_source=dead_source,
                shear_source=shear_source,
                height_source=height_source,
                pier_spacing_mm=piers[0],
                pier_width_mm=piers[1],
                pier_depth_mm=piers[2],
            )
        )
    return segments


# ---------------------------------------------------------------------------
# the prescription inverse and its escalation ladder
# ---------------------------------------------------------------------------


def _sweep(
    segment: WallSegment, options: MasonryOptions, thickness_mm: Optional[float] = None
) -> Tuple[Optional[Tuple[MasonryMaterial, SegmentCheck]], Optional[Tuple[MasonryMaterial, SegmentCheck]]]:
    """`(first passing pair, best pair tried)` over the candidate grid.

    The grid is walked in cost order and stops at the first pair that passes,
    so the answer is the cheapest one. The best pair is kept whether or not
    anything passed: it is the strongest prescription available and it is what
    a failing wall reports rather than reporting nothing.
    """
    passing = None  # type: Optional[Tuple[MasonryMaterial, SegmentCheck]]
    best = None  # type: Optional[Tuple[MasonryMaterial, SegmentCheck]]
    for material in options.candidate_pairs():
        try:
            check = evaluate_segment(segment, material, options, thickness_mm=thickness_mm)
        except CodeInputError:
            continue
        if best is None or check.utilization_max < best[1].utilization_max - 1.0e-9:
            best = (material, check)
        if check.ok and passing is None:
            passing = (material, check)
            break
    return (passing, best)


def cheapest_passing(
    segment: WallSegment, options: Optional[MasonryOptions] = None, thickness_mm: Optional[float] = None
) -> Optional[Tuple[MasonryMaterial, SegmentCheck]]:
    """The cheapest unit-strength and mortar pair that passes, or None.

    This is the useful inverse: not "does the wall you assumed work", but "what
    is the least you can build and still pass every IS 1905 check".
    """
    settings = MasonryOptions.coerce(options)
    return _sweep(segment, settings, thickness_mm)[0]


@dataclass(frozen=True)
class _Adopted:
    """The specification a wall ended up with, and how it got there."""

    material: MasonryMaterial
    check: SegmentCheck
    thickness_mm: float
    passed: bool
    material_changed: bool
    thickness_changed: bool
    referral: bool
    steps: Tuple[Dict[str, Any], ...]

    def rank_key(self, options: MasonryOptions) -> Tuple[float, int, float]:
        """Sort key for the building rollup: the strongest specification last."""
        rank = options.cost_rank(self.material)
        return (rank[0], rank[1], float(self.thickness_mm))


def _step(name: str, outcome: str, detail: str, **extra: Any) -> Dict[str, Any]:
    """One rung of the prescription ladder, as it goes on the report."""
    entry = {"step": name, "outcome": outcome, "detail": detail}  # type: Dict[str, Any]
    for key in sorted(extra):
        entry[key] = extra[key]
    return entry


def _pair_text(material: MasonryMaterial, thickness_mm: float) -> str:
    return (
        _two_sf(material.unit_strength_mpa)
        + " MPa unit in "
        + material.mortar_grade
        + " mortar, "
        + str(int(round(thickness_mm)))
        + " mm wall"
    )


def _prescribe(segment: WallSegment, options: MasonryOptions) -> _Adopted:
    """Climb the ladder until the wall passes, or until it demonstrably cannot.

    Rung 0 is the pair the caller assumed. Rung 1 is the candidate grid at the
    placed thickness, cheapest first. Rung 2 bumps the thickness to the next
    standard and re-runs the whole grid, once per standard thickness above the
    current one. Rung 3 refers the line back to `placement/masonry.py` for
    confined framing, which the orchestrator applies in its one bounded
    re-place pass. Rung 4 is the plain refusal: frame this line in RC.
    """
    steps = []  # type: List[Dict[str, Any]]
    assumed = options.assumed_material()
    placed_mm = float(segment.thickness_mm)

    try:
        assumed_check = evaluate_segment(segment, assumed, options)
    except CodeInputError as error:
        assumed_check = None
        steps.append(
            _step(
                STEP_ASSUMED,
                "refused",
                "the assumed pair is outside the IS 1905 tables: " + str(error),
                unit_strength_mpa=_r(assumed.unit_strength_mpa),
                mortar_grade=assumed.mortar_grade,
            )
        )
    else:
        steps.append(
            _step(
                STEP_ASSUMED,
                "passed" if assumed_check.ok else "insufficient",
                _pair_text(assumed, placed_mm)
                + (" passes every check" if assumed_check.ok else " is beaten by " + assumed_check.governing_check),
                unit_strength_mpa=_r(assumed.unit_strength_mpa),
                mortar_grade=assumed.mortar_grade,
                thickness_mm=_r(placed_mm),
                utilization_max=_r(assumed_check.utilization_max),
            )
        )
        if assumed_check.ok:
            return _Adopted(
                material=assumed,
                check=assumed_check,
                thickness_mm=placed_mm,
                passed=True,
                material_changed=False,
                thickness_changed=False,
                referral=False,
                steps=tuple(steps),
            )

    passing, best = _sweep(segment, options, None)
    if passing is not None:
        steps.append(
            _step(
                STEP_GRID,
                "passed",
                "the cheapest passing pair on the placed wall is " + _pair_text(passing[0], placed_mm),
                unit_strength_mpa=_r(passing[0].unit_strength_mpa),
                mortar_grade=passing[0].mortar_grade,
                thickness_mm=_r(placed_mm),
                utilization_max=_r(passing[1].utilization_max),
            )
        )
        return _Adopted(
            material=passing[0],
            check=passing[1],
            thickness_mm=placed_mm,
            passed=True,
            material_changed=passing[0] != assumed,
            thickness_changed=False,
            referral=False,
            steps=tuple(steps),
        )

    steps.append(
        _step(
            STEP_GRID,
            "insufficient",
            "no pair in the "
            + str(len(options.candidate_pairs()))
            + " pair grid passes on the placed "
            + str(int(round(placed_mm)))
            + " mm wall",
            thickness_mm=_r(placed_mm),
            utilization_max=None if best is None else _r(best[1].utilization_max),
        )
    )

    thickness_mm = placed_mm
    while True:
        thicker = options.next_thickness_mm(thickness_mm)
        if thicker is None:
            break
        thickness_mm = thicker
        passing, thicker_best = _sweep(segment, options, thickness_mm)
        if thicker_best is not None and (best is None or thicker_best[1].utilization_max < best[1].utilization_max):
            best = thicker_best
        if passing is not None:
            steps.append(
                _step(
                    STEP_THICKNESS,
                    "passed",
                    "at "
                    + str(int(round(thickness_mm)))
                    + " mm the cheapest passing pair is "
                    + _pair_text(passing[0], thickness_mm),
                    thickness_mm=_r(thickness_mm),
                    unit_strength_mpa=_r(passing[0].unit_strength_mpa),
                    mortar_grade=passing[0].mortar_grade,
                    utilization_max=_r(passing[1].utilization_max),
                )
            )
            return _Adopted(
                material=passing[0],
                check=passing[1],
                thickness_mm=thickness_mm,
                passed=True,
                material_changed=passing[0] != options.assumed_material(),
                thickness_changed=True,
                referral=False,
                steps=tuple(steps),
            )
        steps.append(
            _step(
                STEP_THICKNESS,
                "insufficient",
                "no pair in the grid passes at " + str(int(round(thickness_mm))) + " mm either",
                thickness_mm=_r(thickness_mm),
                utilization_max=None if thicker_best is None else _r(thicker_best[1].utilization_max),
            )
        )

    # Nothing built. Report the strongest specification that was tried, and say
    # what has to change about the structure instead of about the brick.
    if best is None:
        strongest = options.candidate_pairs()[-1]
        best = (strongest, evaluate_segment(segment, strongest, options))
    best_thickness_mm = float(best[1].thickness_mm)

    referral = False
    if options.allow_confined_referral and best[1].utilization_max <= float(options.confined_relief_cap) + 1.0e-9:
        referral = True
        steps.append(
            _step(
                STEP_CONFINED,
                "referred",
                "referred back to placement for confined masonry: tie columns and bands shorten the panel and "
                "restore the slenderness and integrity this wall is short of",
                utilization_max=_r(best[1].utilization_max),
                governing_check=best[1].governing_check,
            )
        )
    else:
        steps.append(
            _step(
                STEP_CONFINED,
                "refused",
                "confinement is not offered: the shortfall of "
                + _two_sf(best[1].utilization_max)
                + " on "
                + best[1].governing_check
                + " is past what tie columns recover, which is panel slenderness and integrity, not permissible stress",
                utilization_max=_r(best[1].utilization_max),
            )
        )
    steps.append(
        _step(
            STEP_RC_FRAME,
            "refused",
            "unreinforced masonry cannot carry this line: frame it in reinforced concrete",
            governing_check=best[1].governing_check,
            utilization_max=_r(best[1].utilization_max),
        )
    )

    return _Adopted(
        material=best[0],
        check=best[1],
        thickness_mm=best_thickness_mm,
        passed=False,
        material_changed=best[0] != options.assumed_material(),
        thickness_changed=abs(best_thickness_mm - placed_mm) > _ETA,
        referral=referral,
        steps=tuple(steps),
    )


# ---------------------------------------------------------------------------
# IS 4326: the band and vertical bar SPECIFICATIONS (placement placed them)
# ---------------------------------------------------------------------------

#: Band kinds, in the order they are reported.
BAND_KINDS = ("plinth", "lintel", "roof", "gable")


def resolve_category(model: StructuralModel, options: Optional[MasonryOptions] = None) -> str:
    """The IS 4326 category, from the option if given, else from zone and importance."""
    settings = MasonryOptions.coerce(options)
    if settings.category is not None:
        return settings.category
    return is4326.seismic_category(settings.zone, settings.importance)


def _placement(model: StructuralModel) -> Dict[str, Any]:
    """`placement/masonry.py`'s serialized decisions, or an empty mapping."""
    block = model.meta.get("masonry_placement")
    return dict(block) if isinstance(block, Mapping) else {}


def _governing_span_m(model: StructuralModel, storey: int, options: MasonryOptions) -> Optional[float]:
    """The span the band is priced on where the placer did not state one.

    The longest masonry bearing wall on the storey, which is the longest run a
    band has to cross. It is a proxy for the clear span between cross walls and
    it is disclosed as one; `options.band_span_m` overrides it outright.
    """
    if options.band_span_m is not None:
        return float(options.band_span_m)
    lengths = [
        float(wall.length_m())
        for wall in model.walls_on(storey)
        if _is_masonry(wall) and wall.bearing is not False
    ]
    if not lengths:
        return None
    return max(lengths)


def _band_entry(
    kind: str,
    storey: int,
    category: str,
    span_m: Optional[float],
    options: MasonryOptions,
    band_id: str = "",
    wall_ids: Sequence[str] = (),
) -> Dict[str, Any]:
    """One band of one kind at one storey: what to build, or why nothing is."""
    entry = {
        "kind": kind,
        "storey": int(storey),
        "band_id": band_id,
        "wall_ids": [str(item) for item in wall_ids],
        "span_m": _r_opt(span_m),
        "category": category,
        "required": False,
        "spec": None,
        "reason": "",
    }  # type: Dict[str, Any]
    try:
        if kind == "lintel":
            spec = is4326.lintel_band(span_m, category)
        elif kind == "roof":
            spec = is4326.roof_band(span_m, category, options.roof_type, bool(options.cast_in_situ_slab))
        elif kind == "plinth":
            spec = is4326.plinth_band(category, bool(options.soft_soil), span_m)
        elif kind == "gable":
            spec = is4326.gable_band(category, options.roof_type, span_m)
        else:
            raise CodeInputError("unknown band kind " + repr(kind))
    except CodeInputError as error:
        entry["required"] = True
        entry["reason"] = "the band is required but IS 4326 Table 6 cannot size it: " + str(error)
        return entry

    if spec is None:
        entry["reason"] = _band_absent_reason(kind, category, options)
        return entry
    entry["required"] = True
    entry["spec"] = dict(spec._asdict())
    entry["reason"] = spec.note
    return entry


def _band_absent_reason(kind: str, category: str, options: MasonryOptions) -> str:
    """Why a band that was asked for came back as None, in words for the report."""
    if category == "A":
        return "not required, category A takes no reinforced concrete band"
    if kind == "roof":
        return (
            "not required, IS 4326 Cl 8.4.6: the cast-in-situ reinforced concrete roof slab is itself the roof band"
        )
    if kind == "plinth":
        return (
            "not required, IS 4326 Cl 8.4.7: a plinth band is mandatory only on soft or filled soil and for "
            "categories D and E; here it is recommended, not required"
        )
    if kind == "gable":
        return "not required, a " + options.roof_type + " roof has no raking end wall to band"
    return "not required for category " + category


def band_specification(
    model: StructuralModel,
    options: Optional[MasonryOptions] = None,
    storeys_total: Optional[int] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """The IS 4326 band bar schedule, one entry per band the building carries.

    Where `placement/masonry.py` has already placed the band geometry, every
    placed band is specified in place, span by span. Where it has not, one band
    per kind per storey is synthesized on the governing wall span so the report
    still says what the building needs.

    A category A or B band that needs nothing is reported as an explicit
    not-required entry with its reason, never as a silence; the callable is
    called either way, so the trace carries the clause line that said no.
    """
    settings = MasonryOptions.coerce(options)
    cat = category if category is not None else resolve_category(model, settings)
    count = int(storeys_total if storeys_total is not None else (len(model.storeys) or 1))
    count = max(count, 1)
    placement = _placement(model)
    rows = placement.get("band_schedule") or []

    entries = []  # type: List[Dict[str, Any]]
    if rows:
        source = "band geometry placed by placement/masonry.py, specified span by span"
        ordered = sorted(
            rows,
            key=lambda row: (
                int(_get(row, "storey", 0)),
                BAND_KINDS.index(str(_get(row, "kind", "lintel")))
                if str(_get(row, "kind", "lintel")) in BAND_KINDS
                else len(BAND_KINDS),
                str(_get(row, "band_id", "")),
            ),
        )
        for row in ordered:
            kind = str(_get(row, "kind", "lintel"))
            storey = int(_get(row, "storey", 0))
            span = float(_get(row, "span_m", 0.0) or 0.0)
            if span <= 0.0:
                fallback = _governing_span_m(model, storey, settings)
                span_m = fallback  # type: Optional[float]
            else:
                span_m = span
            entries.append(
                _band_entry(
                    kind,
                    storey,
                    cat,
                    span_m,
                    settings,
                    band_id=str(_get(row, "band_id", "")),
                    wall_ids=[str(item) for item in (_get(row, "wall_ids", []) or [])],
                )
            )
    else:
        source = "no placed band schedule; one band per kind per storey on the governing wall span"
        top = count - 1
        for storey in range(count):
            span_m = _governing_span_m(model, storey, settings)
            if storey == 0:
                entries.append(_band_entry("plinth", storey, cat, span_m, settings))
            entries.append(_band_entry("lintel", storey, cat, span_m, settings))
            if storey == top:
                entries.append(_band_entry("roof", storey, cat, span_m, settings))
                entries.append(_band_entry("gable", storey, cat, span_m, settings))

    required = [entry for entry in entries if entry["required"]]
    return {
        "code": is4326.CODE,
        "category": cat,
        "storeys": count,
        "roof_type": settings.roof_type,
        "cast_in_situ_slab": bool(settings.cast_in_situ_slab),
        "soft_soil": bool(settings.soft_soil),
        "source": source,
        "bands": entries,
        "bands_required": len(required),
        "width_source": "wall thickness: every band is cast the full width of the wall it runs on",
    }


def vertical_bar_specification(
    model: StructuralModel,
    options: Optional[MasonryOptions] = None,
    storeys_total: Optional[int] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """The IS 4326 Table 7 vertical steel, one entry per storey of the stack.

    The diameter is a function of the storey count, the position of the storey
    in the stack and the category, and nothing else; the LOCATIONS come from
    `placement/masonry.py`, which put the bars at the corners, junctions and
    jambs. Categories A and B take no vertical steel and say so.
    """
    settings = MasonryOptions.coerce(options)
    cat = category if category is not None else resolve_category(model, settings)
    count = int(storeys_total if storeys_total is not None else (len(model.storeys) or 1))
    count = max(count, 1)

    placed = {}  # type: Dict[int, List[Dict[str, Any]]]
    for row in _placement(model).get("vertical_bars") or []:
        low = int(_get(row, "from_storey", 0))
        high = int(_get(row, "to_storey", low))
        for storey in range(min(low, high), max(low, high) + 1):
            placed.setdefault(storey, []).append(dict(row) if isinstance(row, Mapping) else dict(row.to_dict()))

    entries = []  # type: List[Dict[str, Any]]
    for index in range(count):
        entry = {
            "storey": index,
            "required": False,
            "spec": None,
            "placed_bars": len(placed.get(index, [])),
            "reason": "",
        }  # type: Dict[str, Any]
        try:
            spec = is4326.vertical_bars(count, index, cat)
        except CodeInputError as error:
            entry["reason"] = "IS 4326 Table 7 cannot answer for this stack: " + str(error)
            entries.append(entry)
            continue
        if spec is None:
            entry["reason"] = (
                "not required, category "
                + cat
                + " takes no vertical steel from IS 4326 Table 7"
            )
        else:
            entry["required"] = True
            entry["spec"] = dict(spec._asdict())
            entry["reason"] = spec.note
        entries.append(entry)

    required = [entry for entry in entries if entry["required"]]
    return {
        "code": is4326.CODE,
        "category": cat,
        "storeys": count,
        "source": "IS 4326 Table 7 diameters; bar locations placed by placement/masonry.py",
        "storeys_detail": entries,
        "storeys_required": len(required),
        "placed_bars_total": sum(len(rows) for rows in placed.values()),
    }


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

#: The single building-level rollup entry the bill of quantities prices from.
BUILDING_ELEMENT_ID = "masonry-building"

_CLAUSE_SLENDERNESS = is1905.CODE + " Table 7"
_CLAUSE_COMPRESSION = is1905.CODE + " Cl 5.4.1"
_CLAUSE_SHEAR = is1905.CODE + " Cl 5.4.2"
_CLAUSE_TENSION = is1905.CODE + " Cl 5.4.3"


def _wall_result(segment: WallSegment, options: MasonryOptions, adopted: _Adopted) -> DesignResult:
    """One wall segment at one storey, as the shared design contract."""
    result = DesignResult(element_id=segment.element_id, element_type=ELEMENT_TYPE_WALL)

    entries = []  # type: List[TraceEntry]
    try:
        with trace_into(entries):
            check = evaluate_segment(segment, adopted.material, options, thickness_mm=adopted.thickness_mm)
    except CodeInputError as error:
        check = adopted.check
        entries = []
        result.add_warning("the adopted specification could not be re-traced: " + str(error))
    result.trace = entries

    result.section = {
        "wall_id": segment.wall_id,
        "storey": int(segment.storey),
        "thickness_mm": _r(adopted.thickness_mm),
        "placed_thickness_mm": _r(segment.thickness_mm),
        "length_mm": _r(segment.length_mm),
        "net_length_mm": _r(segment.net_length_mm),
        "height_mm": _r(segment.height_mm),
        "effective_height_mm": _r(check.heff_m * 1.0e3),
        "effective_length_mm": None if check.leff_m is None else _r(check.leff_m * 1.0e3),
        "effective_thickness_mm": _r(check.teff_m * 1.0e3),
        "role": segment.role,
    }
    result.materials = {
        "material": MATERIAL,
        "unit_strength_mpa": _r(adopted.material.unit_strength_mpa),
        "mortar_grade": adopted.material.mortar_grade,
        "fb_mpa": _r(check.fb_mpa),
        "fc_mpa": _r_opt(check.fc_mpa),
        "code": is1905.CODE,
    }

    result.add_check(
        CHECK_SLENDERNESS,
        _CLAUSE_SLENDERNESS,
        check.slenderness_ratio,
        check.slenderness_limit,
        status=None if check.slenderness_ok else CHECK_FAIL,
    )
    result.add_check(
        CHECK_COMPRESSION,
        _CLAUSE_COMPRESSION,
        check.fa_mpa,
        0.0 if check.fc_mpa is None else check.fc_mpa,
        units="MPa",
    )
    result.add_check(CHECK_SHEAR, _CLAUSE_SHEAR, check.tau_mpa, check.fs_mpa, units="MPa")
    result.add_check(CHECK_TENSION, _CLAUSE_TENSION, check.tension_demand_mpa, check.ft_mpa, units="MPa")

    if check.fc_mpa is None and check.ks_reason:
        result.add_warning(check.ks_reason)

    if adopted.material_changed:
        result.add_resize(
            options.assumed_material().to_dict(),
            adopted.material.to_dict(),
            "the assumed unit and mortar pair does not pass; this is the cheapest pair in the grid that does"
            if adopted.passed
            else "the assumed unit and mortar pair does not pass; this is the strongest pair the grid offers, "
            "and it does not pass either",
        )
    if adopted.thickness_changed:
        result.add_resize(
            _r(segment.thickness_mm),
            _r(adopted.thickness_mm),
            "no pair in the grid passes at the placed thickness; the wall is prescribed one standard thicker"
            if adopted.passed
            else "no pair in the grid passes at any standard thickness; this is the thickest one tried",
        )
    if adopted.referral:
        result.add_referral(
            REFERRAL_CONFINED,
            {
                "wall_id": segment.wall_id,
                "storey": int(segment.storey),
                "governing_check": check.governing_check,
                "utilization_max": _r(check.utilization_max),
                "reason": "unreinforced masonry cannot carry this line; confine it with tie columns and bands",
            },
        )

    for note in (segment.height_source, segment.dead_source, segment.shear_source):
        if note:
            result.add_note(note)
    if segment.pier_spacing_mm is not None:
        result.add_note(
            "stiffened by pilasters: the effective thickness follows IS 1905 Table 6 on the longest bay, "
            + str(int(round(segment.pier_spacing_mm)))
            + " mm"
        )
    if not segment.openings_known:
        result.add_warning(
            "no dressed openings on this storey: the bearing length is the gross wall length and the opening "
            "checks of IS 4326 Table 4 had assumed geometry to work on"
        )
    if options.tension_policy == "allow_flexural_tension":
        result.add_warning(
            "flexural tension is allowed by option: IS 1905 Cl 5.4.3 values are for a laterally loaded panel, "
            "never for a primary gravity wall"
        )

    result.extras["masonry"] = {
        "segment": segment.to_dict(),
        "check": check.to_dict(),
        "verdict": check.verdict,
    }
    result.extras["prescription"] = {
        "unit_strength_mpa": _r(adopted.material.unit_strength_mpa),
        "mortar_grade": adopted.material.mortar_grade,
        "thickness_mm": _r(adopted.thickness_mm),
        "passes": bool(adopted.passed),
        "assumed": options.assumed_material().to_dict(),
        "steps": [dict(step) for step in adopted.steps],
        "governing_check": check.governing_check,
        "utilization_max": _r(check.utilization_max),
    }

    if not check.slenderness_ok:
        result.governing_check = CHECK_SLENDERNESS
    if adopted.passed:
        result.finalize()
    else:
        result.fail_with(
            result.governing_check or check.governing_check,
            reason="unreinforced masonry cannot carry this line at any pair in the grid: frame it in reinforced concrete",
        )
    return result


def _building_result(
    model: StructuralModel,
    options: MasonryOptions,
    segments: Sequence[WallSegment],
    adopted: Sequence[_Adopted],
    results: Sequence[DesignResult],
    storeys_total: int,
) -> DesignResult:
    """The one entry the bill of quantities prices: the max spec over the walls."""
    result = DesignResult(element_id=BUILDING_ELEMENT_ID, element_type=ELEMENT_TYPE_BUILDING)

    # Strongest specification last, and where two walls want the same spec the
    # harder worked one is the governing wall, not whichever id sorts later.
    ranked = sorted(
        zip(segments, adopted),
        key=lambda pair: (
            pair[1].rank_key(options),
            min(float(pair[1].check.utilization_max), _RATIO_CAP),
            pair[0].element_id,
        ),
    )
    governing_segment, governing = ranked[-1]

    # The category lookup belongs inside the sink: the zone-to-category step is
    # a clause of IS 4326 like any other and the report cites it.
    entries = []  # type: List[TraceEntry]
    with trace_into(entries):
        category = resolve_category(model, options)
        bands = band_specification(model, options, storeys_total=storeys_total, category=category)
        bars = vertical_bar_specification(model, options, storeys_total=storeys_total, category=category)
    result.trace = entries

    thickest_mm = max(float(item.thickness_mm) for item in adopted)
    failed = [row for row in results if row.status == STATUS_FAIL]
    resized = [row for row in results if row.status == STATUS_RESIZED]
    worst = max((float(row.utilization_max) for row in results), default=0.0)

    result.section = {
        "thickness_mm": _r(thickest_mm),
        "storeys": int(storeys_total),
        "walls_designed": len(results),
        "walls_failed": len(failed),
        "walls_resized": len(resized),
    }
    result.materials = {
        "material": MATERIAL,
        "unit_strength_mpa": _r(governing.material.unit_strength_mpa),
        "mortar_grade": governing.material.mortar_grade,
        "code": is1905.CODE,
    }
    result.add_check("wall_utilization", _CLAUSE_COMPRESSION, worst, 1.0)

    result.extras["prescription"] = {
        "unit_strength_mpa": _r(governing.material.unit_strength_mpa),
        "mortar_grade": governing.material.mortar_grade,
        "thickness_mm": _r(thickest_mm),
        "governing_wall": governing_segment.element_id,
        "category": category,
        "storeys": int(storeys_total),
        "escalation": [dict(step) for step in governing.steps],
        "bands": bands,
        "vertical_bars": bars,
        "walls": [
            {
                "element_id": segment.element_id,
                "unit_strength_mpa": _r(item.material.unit_strength_mpa),
                "mortar_grade": item.material.mortar_grade,
                "thickness_mm": _r(item.thickness_mm),
                "passes": bool(item.passed),
            }
            for segment, item in ranked
        ],
        "cost_order": "unit strength ascending, then mortar grade weakest first; the weaker spec is the cheaper spec",
    }
    result.add_note(
        "one specification for the whole building: the strongest pair any wall needed, so the bill of quantities "
        "prices a single unit and a single mortar"
    )
    if bands["bands_required"] == 0:
        result.add_note("no reinforced concrete band is required at category " + category)
    if bars["storeys_required"] == 0:
        result.add_note("no vertical steel is required at category " + category)

    if failed:
        result.fail_with(
            "wall_utilization",
            reason=str(len(failed))
            + " masonry wall segment(s) cannot be built in unreinforced masonry; see their referrals",
        )
    else:
        if resized:
            result.add_resize(
                options.assumed_material().to_dict(),
                {
                    "unit_strength_mpa": _r(governing.material.unit_strength_mpa),
                    "mortar_grade": governing.material.mortar_grade,
                    "thickness_mm": _r(thickest_mm),
                },
                "the assumed pair does not carry every wall; the building specification is the strongest pair needed",
            )
        result.finalize()
    return result


# ---------------------------------------------------------------------------
# the public entry point
# ---------------------------------------------------------------------------


def design_masonry_walls(
    model: StructuralModel,
    wall_stresses: Any = None,
    lateral: Any = None,
    options: Any = None,
) -> List[DesignResult]:
    """Design every masonry bearing wall segment, then specify the building.

    `wall_stresses` is the takedown output: a `TakedownResult`, its dict, or a
    bare sequence of `WallStress` records. `lateral` is the diaphragm output: a
    `LateralResult`, its dict, or a mapping of `wall@storey` to a shear in kN.
    `options` is a `MasonryOptions` or a mapping of its fields.

    The return is one `DesignResult` per wall segment per storey in
    `(storey, wall_id)` order, followed by exactly one building-level entry
    (`element_type` `masonry_building`) carrying the rolled-up material
    specification, the IS 4326 band schedule and the vertical bar schedule.
    Every storey is checked and reported even though the bottom one usually
    governs, because "usually" is not a design basis.

    Nothing raises. A wall the grid cannot satisfy comes back with status
    `fail`, its governing check, the ladder it climbed and a referral asking
    placement to confine the line.
    """
    settings = MasonryOptions.coerce(options)
    segments = resolve_segments(model, wall_stresses, lateral, settings)
    if not segments:
        return []

    storeys_total = segments[0].storeys_total

    results = []  # type: List[DesignResult]
    adopted = []  # type: List[_Adopted]
    for segment in segments:
        try:
            plan = _prescribe(segment, settings)
        except CodeInputError as error:
            plan = _refused(segment, settings, str(error))
        adopted.append(plan)
        results.append(_wall_result(segment, settings, plan))

    results.append(_building_result(model, settings, segments, adopted, results, storeys_total))
    _disclose(model, settings, segments, adopted, storeys_total)
    return results


def _refused(segment: WallSegment, options: MasonryOptions, reason: str) -> _Adopted:
    """The adopted record for a segment the code tables refuse outright.

    It still carries a specification and a ladder, because a fully populated
    failing result is the contract; what it does not carry is a pretence that
    the wall was checked.
    """
    material = options.assumed_material()
    check = SegmentCheck(
        thickness_mm=float(segment.thickness_mm),
        unit_strength_mpa=float(material.unit_strength_mpa),
        mortar_grade=material.mortar_grade,
        heff_m=0.0,
        leff_m=None,
        teff_m=mm_to_m(segment.thickness_mm),
        slenderness_ratio=0.0,
        slenderness_limit=0.0,
        slenderness_ok=False,
        fb_mpa=0.0,
        ks=None,
        ks_reason=reason,
        ka=0.0,
        kp=0.0,
        fc_mpa=None,
        fa_mpa=float(segment.n_kn_per_m) / max(float(segment.thickness_mm), _ETA),
        utilization_compression=_RATIO_CAP,
        fd_mpa=0.0,
        fs_mpa=0.0,
        tau_mpa=0.0,
        utilization_shear=0.0,
        ft_mpa=0.0,
        tension_demand_mpa=0.0,
        utilization_tension=0.0,
        ok=False,
        governing_check=CHECK_COMPRESSION,
        utilization_max=_RATIO_CAP,
    )
    steps = (
        _step(STEP_ASSUMED, "refused", "the IS 1905 tables refuse this wall: " + reason),
        _step(STEP_RC_FRAME, "refused", "frame this line in reinforced concrete"),
    )
    return _Adopted(
        material=material,
        check=check,
        thickness_mm=float(segment.thickness_mm),
        passed=False,
        material_changed=False,
        thickness_changed=False,
        referral=False,
        steps=steps,
    )


def _disclose(
    model: StructuralModel,
    options: MasonryOptions,
    segments: Sequence[WallSegment],
    adopted: Sequence[_Adopted],
    storeys_total: int,
) -> None:
    """Put on the model's ladder what the model, not one wall, has to answer for.

    Only conditions with a registry code of their own land here. A wall that
    cannot be built is not one of them: that verdict lives on its own
    DesignResult, with its governing check and its referral, and the
    orchestrator raises it to the ladder in the vocabulary of its own stage.
    """
    if storeys_total > 3:
        model.add_warning(
            "E_MASONRY_LIMIT",
            "load bearing masonry is designed here for up to 3 storeys; this stack is "
            + str(int(storeys_total))
            + ", past the transcribed rows of IS 4326 Table 7",
            clause=is4326.CODE + " Table 7",
            stage=STAGE,
        )

    unknown = sorted({segment.wall_id for segment in segments if not segment.openings_known})
    if unknown:
        model.add_warning(
            "W_ASSUMED_OPENINGS",
            "no dressed openings on "
            + str(len(unknown))
            + " masonry wall segment(s): the bearing length was taken as the gross wall length",
            element_ids=unknown,
            clause=is1905.CODE + " Cl 5.4.1",
            stage=STAGE,
        )

    thicker = sorted(
        {segment.wall_id for segment, plan in zip(segments, adopted) if plan.thickness_changed}
    )
    if thicker:
        model.add_warning(
            "W_RELEASED_CAP",
            "the placed thickness of "
            + str(len(thicker))
            + " masonry wall segment(s) does not pass; the design prescribes the next standard thickness",
            element_ids=thicker,
            clause=is1905.CODE + " Cl 5.4.1",
            stage=STAGE,
        )

    if options.tension_policy == "allow_flexural_tension":
        model.add_warning(
            "W_RELEASED_CAP",
            "flexural tension was allowed by option; IS 1905 Cl 5.4.3 values apply to laterally loaded panels, "
            "not to primary gravity walls",
            clause=is1905.CODE + " Cl 5.4.3",
            stage=STAGE,
        )


register_designer(MATERIAL, design_masonry_walls)
