"""Take-off, bar bending schedule and bill of quantities: the one quantity owner.

Critic finding 24 makes this module the SOLE owner of quantity: `DesignResult`
deliberately carries no `quantities` field, and every cubic metre, square metre
and kilogram in the response is measured here, once, under the IS 1200
conventions written down in `07-quantities-report.md` section 1. Finding 25
adds the two rules that keep the schedule honest: cover always comes from
`DesignResult.section` (there are no bar-schedule cover defaults), and
`data/rebar.yaml` is read, never duplicated, because the design layer owns it.

Steel comes from the bar schedule and from nowhere else. `build_bbs` walks each
designer's own bars and reads each bar's own `ld_mm` and `zone_mm`; the flat 50d
of the older draft survives only as the fallback for a bar that carries no
development length, and taking that fallback raises `N_LAP_50D_FLAT`. There is
no percentage guess anywhere in this file.

Units. Quantities are SI throughout, because a bill of quantities in India is
metric and Eurocode later will be too: volumes m3, areas m2, mass kg, lengths m.
Sections arrive in mm (the design layer's units) and are converted once, at the
point of use. Geometry converts to feet only at the response edge, which is
`api.py`, not here.

Determinism. Same model in, same numbers out: every walk is over a sorted list,
every mapping is emitted key-sorted, every float is rounded to a fixed number of
decimals on export, and nothing reads the clock. `price` takes its rates from a
table, never from the network.

Disclose, never hide. Every simplification below raises its registered NOTE the
first time it is actually used, and the registry codes are the ones in
`model.REGISTRY`; a row that could not be measured lands with zero quantity and
a `basis` sentence saying why, never as a silence and never as an exception.
Every quantity row carries a `basis`: one short sentence naming the measurement
rule applied, so the report can print the convention beside the number.

Calibration bands are per system. `price` judges three densities against
`data/density_bands.yaml` rather than against two hard-coded numbers: the pair
this module shipped with is a low-rise RC FRAME rule of thumb, and applying it to
a load-bearing masonry house called a correct design wrong on every run. The
rc_frame row is those same numbers to the digit; the masonry rows are the
module's own measured runs widened by ordinary practice, and they add the walling
volume, which is the density a reader should actually sanity check there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .data._loader import load_yaml
from .design.common import BEND_ALLOWANCES
from .model import (
    REGISTRY,
    BandKind,
    BeamKind,
    Disclosure,
    DisclosureLog,
    Material,
    StructuralModel,
    WallRole,
    opening_assumed,
)

__all__ = [
    # options and vocabulary
    "CONCRETE_CLASSES",
    "FORMWORK_CLASSES",
    "SHAPE_STRAIGHT",
    "SHAPE_L",
    "SHAPE_STIRRUP",
    "SHAPE_CODES",
    "STEEL_DENSITY_BAND_KG_M2",
    "CONCRETE_DENSITY_BAND_M3_M2",
    "DENSITY_BAND_CHECKS",
    "DENSITY_BANDS",
    "DENSITY_BAND_LABELS",
    "DEFAULT_BAND_SYSTEM",
    "band_provenance",
    "bands_for_system",
    "DETAIL_LEVELS",
    "DETAIL_COMPACT",
    "DETAIL_FULL",
    "QuantityOptions",
    # take-off
    "ElementVolume",
    "ElementQuantity",
    "FormworkQuantity",
    "MasonryQuantity",
    "FootingEarthwork",
    "EarthworkQuantity",
    "QuantityTakeoff",
    "take_off",
    # bar schedule
    "BBSItem",
    "BarBendingSchedule",
    "build_bbs",
    # pricing
    "RateSchedule",
    "BOQItem",
    "BOQ",
    "load_rates",
    "price",
]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

#: Concrete-bearing element classes, in report order. A class with nothing in
#: the model still gets a row (zero volume, a basis saying so): the spec forbids
#: raising on a missing class, and a silent gap is worse than an explicit zero.
CONCRETE_CLASSES = (
    "column",
    "beam",
    "plinth_beam",
    "slab",
    "stair",
    "band",
    "lintel",
    "footing",
)

#: Classes whose shuttering is measured. Same list: every concrete class here is
#: cast against formwork of some kind.
FORMWORK_CLASSES = CONCRETE_CLASSES

#: Shape codes v1 emits. Richer IS 2502 codes are deferred, which is why the
#: schedule header carries `shape_codes_deferred` and the NOTE is raised.
SHAPE_STRAIGHT = "STR"
SHAPE_L = "L"
SHAPE_STIRRUP = "STP"
SHAPE_CODES = (SHAPE_STRAIGHT, SHAPE_L, SHAPE_STIRRUP)

# ---------------------------------------------------------------------------
# density calibration bands: data/density_bands.yaml, one row per system
# ---------------------------------------------------------------------------
#
# Spec section 1.7 asked for two bands and the module shipped two numbers. They
# were low-rise RC FRAME numbers, and they fired on every masonry house: the
# measured masonry run came out at 1.02 kg/m2 and 0.020 m3/m2, which is what a
# load-bearing masonry house correctly measures and what these bands correctly
# called wrong. Correct arithmetic, wrong advice, and the reader it misled is
# the reader the warnings exist for. The bands are per system now and live in
# `data/density_bands.yaml` beside the other calibration data, provenance
# tagged, with the rc_frame pair unchanged to the digit.

_BAND_TABLE = load_yaml("density_bands")

#: The three checks, in report order. The table must carry exactly these.
DENSITY_BAND_CHECKS = ("steel", "concrete", "masonry")

#: Print formats, kept in code rather than in the table: a format string is not
#: calibration data, and a bad one in YAML would be a crash rather than a wrong
#: number. The measured value and the band ends are formatted separately because
#: 0.020 m3/m2 needs the third digit and "0.10 to 0.20" reads better without it.
_BAND_VALUE_FORMAT = {"steel": "%.2f", "concrete": "%.3f", "masonry": "%.3f"}
_BAND_LIMIT_FORMAT = {"steel": "%.2f", "concrete": "%.2f", "masonry": "%.2f"}
#: The unit the measured quantity is counted in, before "per m2".
_BAND_QUANTITY_UNIT = {"steel": "kg", "concrete": "m3", "masonry": "m3"}
#: Comparison slack, per check, carried over unchanged from the two-band version.
_BAND_TOL = {"steel": 1e-9, "concrete": 1e-12, "masonry": 1e-12}


def _band_pair(value: Any, where: str) -> Optional[Tuple[float, float]]:
    """A [low, high] pair from the table, or None where the check is off."""
    if value is None:
        return None
    pair = tuple(float(item) for item in value)
    if len(pair) != 2:
        raise ValueError(where + " must be a [low, high] pair or null, got " + repr(value))
    if pair[0] > pair[1]:
        raise ValueError(where + " has its low end above its high end: " + repr(value))
    return (pair[0], pair[1])


def _build_band_tables() -> Tuple[Any, Any, Any]:
    """(bands, labels, provenance) read once out of data/density_bands.yaml."""
    checks = _BAND_TABLE.get("checks") or {}
    missing = [name for name in DENSITY_BAND_CHECKS if name not in checks]
    if missing:
        raise ValueError("density_bands.yaml is missing checks: " + ", ".join(missing))
    # Registry codes only. A check that names a code `model.REGISTRY` does not
    # hold would raise the first time it fired, so it refuses to load instead --
    # unless the row declares the gap, which is a deliberate, documented and
    # loudly reported state, not a silent one. See the table's own comment.
    for name in DENSITY_BAND_CHECKS:
        code = str(checks[name].get("disclosure_code", ""))
        if code not in REGISTRY and not checks[name].get("pending_registration"):
            raise ValueError(
                "density_bands.yaml checks."
                + name
                + " names an unregistered disclosure code "
                + code
                + "; add it to model.REGISTRY or declare pending_registration: true"
            )
    bands = {}  # type: Dict[str, Any]
    labels = {}  # type: Dict[str, str]
    for system, row in sorted((_BAND_TABLE.get("systems") or {}).items(), key=lambda item: str(item[0])):
        name = str(system)
        labels[name] = str(row.get("label", name))
        bands[name] = MappingProxyType(
            {
                check: _band_pair(
                    row.get(str(checks[check]["band_key"])),
                    "density_bands.yaml systems." + name + "." + str(checks[check]["band_key"]),
                )
                for check in DENSITY_BAND_CHECKS
            }
        )
    return (
        MappingProxyType(bands),
        MappingProxyType(labels),
        MappingProxyType({check: MappingProxyType(dict(checks[check])) for check in DENSITY_BAND_CHECKS}),
    )


DENSITY_BANDS, DENSITY_BAND_LABELS, _BAND_CHECK_META = _build_band_tables()

#: The row a model whose system the table does not carry is judged against. The
#: substitution is named in the response rather than applied silently.
DEFAULT_BAND_SYSTEM = str(_BAND_TABLE.get("default_system") or "rc_frame")
if DEFAULT_BAND_SYSTEM not in DENSITY_BANDS:
    raise ValueError("density_bands.yaml default_system is not a tabulated system: " + DEFAULT_BAND_SYSTEM)

#: Calibration band for reinforcement per square metre of built-up area, the
#: rc_frame row of the table. It is a heuristic that catches take-off bugs and
#: absurd designs, not a code rule, so it is stated in the metric's `basis` and
#: both ends are option-overridable. Kept as a module constant because it is the
#: `QuantityOptions` default and the published name; the number itself is the
#: table's, so the two cannot drift.
STEEL_DENSITY_BAND_KG_M2 = DENSITY_BANDS[DEFAULT_BAND_SYSTEM]["steel"]

#: Calibration band for concrete per square metre of built-up area, same source
#: and same status.
CONCRETE_DENSITY_BAND_M3_M2 = DENSITY_BANDS[DEFAULT_BAND_SYSTEM]["concrete"]


def band_provenance() -> Dict[str, Any]:
    """The table's own source, edition and per-system basis, for the report."""
    return {
        "table": "data/density_bands.yaml",
        "schema_version": _BAND_TABLE.get("schema_version"),
        "source": str(_BAND_TABLE.get("source", "")),
        "edition": str(_BAND_TABLE.get("edition", "")),
        "default_system": DEFAULT_BAND_SYSTEM,
        "systems": {
            name: {
                "label": DENSITY_BAND_LABELS[name],
                "basis": str((_BAND_TABLE.get("systems") or {}).get(name, {}).get("basis", "")),
                "uncertainty": str((_BAND_TABLE.get("systems") or {}).get(name, {}).get("uncertainty", "")),
            }
            for name in sorted(DENSITY_BANDS)
        },
    }


def bands_for_system(system: Any) -> Dict[str, Optional[Tuple[float, float]]]:
    """The three bands one system is judged against; None where a check is off.

    An unknown system falls back to `DEFAULT_BAND_SYSTEM`, which is what `price`
    does too; there it also says so in `band_source`.
    """
    name = _word(system) or DEFAULT_BAND_SYSTEM
    row = DENSITY_BANDS.get(name) or DENSITY_BANDS[DEFAULT_BAND_SYSTEM]
    return {check: row[check] for check in DENSITY_BAND_CHECKS}

#: Serialization levels (spec 07 size discipline). `full` is this module's own
#: default; `api.py` asks for `compact` on the wire, where the per-element rows
#: are elided and every aggregate, total and basis string is kept. Eliding is
#: never silent: an elided list keeps its type and gains `_total`, `_elided` and
#: `_ref` siblings saying how many rows there were and what still holds them.
DETAIL_COMPACT = "compact"
DETAIL_FULL = "full"
DETAIL_LEVELS = (DETAIL_COMPACT, DETAIL_FULL)

#: Class letters that open a bar mark: "C3-L1" is column 3, longitudinal set 1.
_MARK_LETTERS = {
    "column": "C",
    "beam": "B",
    "plinth_beam": "P",
    "slab": "S",
    "stair": "T",
    "band": "N",
    "lintel": "L",
    "footing": "F",
}
_MARK_FALLBACK = "X"

#: Stirrup kinds: an entry with one of these kinds is a closed link, not a
#: main bar, whatever the designer called it.
_STIRRUP_KINDS = frozenset(("shear", "tie", "hoop", "link", "torsion", "confinement"))

#: Formwork rate keys the shipped schedule carries; anything else is priced on
#: the nearest relative below and the substitution is named in `rate_source`.
_FORMWORK_RATE_ALIAS = {
    "plinth_beam": "beam",
    "band": "beam",
    "lintel": "beam",
    "stair": "slab",
}

_GEOM_TOL_M = 1e-9
_STAGE = "quantities"


_ELIDED_FOR_DETAIL = (
    "elided at detail=" + DETAIL_COMPACT + "; ask for detail=" + DETAIL_FULL
)


def _elide_rows(block: Dict[str, Any], key: str, ref: str, reason: str) -> None:
    """Empty one per-element list and say, in three siblings, what it held.

    The key keeps its type so a client's parser does not change shape, and the
    aggregates the rows were summed into are never touched: eliding a row list
    moves no measured number.
    """
    rows = block.get(key)
    if not isinstance(rows, (list, tuple)):
        return
    block[key] = []
    block[key + "_total"] = len(rows)
    block[key + "_elided"] = True
    block[key + "_ref"] = ref
    block[key + "_elided_reason"] = reason + "; " + _ELIDED_FOR_DETAIL


def _r(value: float, dp: int) -> float:
    """A float rounded for export, with no negative zero to break equality."""
    return round(float(value), int(dp)) + 0.0


def _num(value: Any, default: float = 0.0) -> float:
    """A float from anything a wire dict might hold, `default` when it cannot."""
    if value is None:
        return float(default)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(out) or math.isinf(out):
        return float(default)
    return out


def _word(value: Any) -> str:
    """An enum value or a string, normalised to the lower-snake vocabulary."""
    text = getattr(value, "value", value)
    return str(text).strip().lower().replace("-", "_").replace(" ", "_")


def _m2_text(value: float) -> str:
    return ("%.3f" % float(value)).rstrip("0").rstrip(".") + " m2"


def _m_text(value: float) -> str:
    return ("%.3f" % float(value)).rstrip("0").rstrip(".") + " m"


def _mm_text(value: float) -> str:
    return str(int(round(float(value)))) + " mm"


# ---------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantityOptions:
    """Every knob the take-off, the schedule and the pricing take.

    Defaults are the spec's. Each one that changes a number also changes the
    `basis` string that number is reported with, so a caller who moves a knob
    cannot move it silently.
    """

    # bar schedule
    wastage_pct: float = 3.0
    lap_dia_multiple: float = 50.0
    stock_length_m: float = 12.0
    stirrup_hook_dia_multiple: float = 20.0
    bbs_max_items: int = 500

    # IS 1200 measurement
    opening_deduction_min_m2: float = 0.1
    default_opening_head_m: float = 2.1
    default_window_height_m: float = 1.2

    # earthwork
    working_space_m: float = 0.3
    slope_multiplier: float = 1.1
    slope_depth_m: float = 1.5
    pcc_thickness_m: float = 0.1
    pcc_offset_m: float = 0.1
    founding_depth_m: float = 1.5

    # element defaults used only where the model carries nothing
    lintel_depth_mm: float = 150.0
    lintel_bearing_m: float = 0.15
    band_depth_mm: float = 75.0
    roof_band_depth_mm: float = 150.0
    partition_thickness_mm: int = 115
    default_concrete_grade: str = "M25"
    default_steel_grade: str = "Fe500"

    # Calibration bands (spec 1.7), now per system: see `_resolve_bands`. A band
    # left at its shipped default defers to `data/density_bands.yaml` for the
    # system the take-off measured; a band a caller sets to anything else is the
    # caller's and is used verbatim, whatever the system. The steel and concrete
    # defaults are the rc_frame row, so an RC take-off is judged against the same
    # numbers whichever way it arrived. The masonry default is empty because
    # rc_frame does not check masonry at all: supplying a pair here turns the
    # check on for any system.
    steel_band_kg_m2: Tuple[float, ...] = STEEL_DENSITY_BAND_KG_M2
    concrete_band_m3_m2: Tuple[float, ...] = CONCRETE_DENSITY_BAND_M3_M2
    masonry_band_m3_m2: Tuple[float, ...] = ()

    # elements an ERROR blocked upstream: measured as zero, with the reason
    blocked_element_ids: Tuple[str, ...] = ()

    # how much of the working `to_dict` shows: "full" (the default, and what a
    # direct caller and the batteries get) or "compact", which elides the
    # per-element rows and keeps every aggregate, total and basis string. It
    # changes no measured number, only what is serialized.
    detail: str = DETAIL_FULL

    # export precision
    volume_dp: int = 2
    area_dp: int = 2
    mass_dp: int = 3
    money_dp: int = 2

    @property
    def compact(self) -> bool:
        """True when `to_dict` elides the per-element rows (never the aggregates)."""
        return str(self.detail).strip().lower() == DETAIL_COMPACT

    @staticmethod
    def coerce(options: Any) -> "QuantityOptions":
        """Options from None, a mapping or an existing instance. Unknown keys ignored."""
        if isinstance(options, QuantityOptions):
            return options
        if options is None:
            return QuantityOptions()
        if not isinstance(options, Mapping):
            raise ValueError("quantity options must be a mapping or QuantityOptions, got " + type(options).__name__)
        base = QuantityOptions()
        values = {}  # type: Dict[str, Any]
        for name in _OPTION_FIELDS:
            if name not in options:
                continue
            current = getattr(base, name)
            supplied = options[name]
            if name == "blocked_element_ids":
                values[name] = tuple(sorted(str(item) for item in (supplied or ())))
            elif isinstance(current, tuple):
                # Empty (or None) is not a malformed pair, it is the caller
                # saying "take this band from the system table" -- the same
                # thing the shipped default says.
                pair = () if supplied is None else tuple(float(item) for item in supplied)
                if pair and len(pair) != 2:
                    raise ValueError(name + " must be a (low, high) pair, got " + repr(supplied))
                values[name] = pair
            elif isinstance(current, bool):
                values[name] = bool(supplied)
            elif isinstance(current, int) and not isinstance(current, bool):
                values[name] = int(supplied)
            elif isinstance(current, float):
                values[name] = float(supplied)
            else:
                values[name] = str(supplied)
        return QuantityOptions(**values)

    def to_dict(self) -> Dict[str, Any]:
        """The resolved options, for the response `options_echo`."""
        out = {}  # type: Dict[str, Any]
        for name in _OPTION_FIELDS:
            value = getattr(self, name)
            out[name] = list(value) if isinstance(value, tuple) else value
        return out


_OPTION_FIELDS = (
    "wastage_pct",
    "lap_dia_multiple",
    "stock_length_m",
    "stirrup_hook_dia_multiple",
    "bbs_max_items",
    "opening_deduction_min_m2",
    "default_opening_head_m",
    "default_window_height_m",
    "working_space_m",
    "slope_multiplier",
    "slope_depth_m",
    "pcc_thickness_m",
    "pcc_offset_m",
    "founding_depth_m",
    "lintel_depth_mm",
    "lintel_bearing_m",
    "band_depth_mm",
    "roof_band_depth_mm",
    "partition_thickness_mm",
    "default_concrete_grade",
    "default_steel_grade",
    "steel_band_kg_m2",
    "concrete_band_m3_m2",
    "masonry_band_m3_m2",
    "blocked_element_ids",
    "detail",
    "volume_dp",
    "area_dp",
    "mass_dp",
    "money_dp",
)


# ---------------------------------------------------------------------------
# the design results, read the same way whether they are objects or dicts
# ---------------------------------------------------------------------------


class _Design(object):
    """One `DesignResult`, read uniformly from the object or from its dict.

    `run_design` hands over live `DesignResult`s; a cached response hands over
    the dicts `to_dict()` produced. Both must take off to the same numbers, so
    every read in this module goes through here.
    """

    __slots__ = ("element_id", "element_type", "section", "materials", "bars", "stirrups", "status", "extras")

    def __init__(self, source: Any) -> None:
        get = source.get if isinstance(source, Mapping) else (lambda key, default=None: getattr(source, key, default))
        self.element_id = str(get("element_id", "") or "")
        self.element_type = _word(get("element_type", "") or "")
        self.section = dict(get("section", None) or {})
        self.materials = dict(get("materials", None) or {})
        self.bars = [dict(bar) for bar in (get("bars", None) or [])]
        self.stirrups = [dict(item) for item in (get("stirrups", None) or [])]
        self.status = _word(get("status", "pass") or "pass")
        extras = get("extras", None)
        self.extras = dict(extras) if isinstance(extras, Mapping) else {}
        if not self.extras and isinstance(source, Mapping):
            # A serialized result flattens `extras` to the top level, so the
            # keys the schedule cares about are picked back up from there.
            self.extras = {key: value for key, value in source.items() if key not in _RESULT_WIRE_KEYS}

    # -- reads the take-off makes ------------------------------------------

    def mm(self, *names: str) -> Optional[float]:
        """The first section key present, as mm; None when none of them is."""
        for name in names:
            if name in self.section and self.section[name] is not None:
                return _num(self.section[name])
        return None

    def m(self, *names: str) -> Optional[float]:
        """The first section key present, converted from mm to metres."""
        value = self.mm(*names)
        return None if value is None else value / 1000.0

    @property
    def concrete_grade(self) -> str:
        grade = self.materials.get("concrete_grade")
        return str(grade) if grade else ""

    @property
    def steel_grade(self) -> str:
        grade = self.materials.get("steel_grade")
        return str(grade) if grade else ""

    @property
    def cover_mm(self) -> Optional[float]:
        """Cover, mm, from the section. Finding 25: never defaulted here."""
        return self.mm("cover_mm")

    @property
    def is_stair(self) -> bool:
        """A stair flight: the slab designer's stair mode stamps `waist_mm`."""
        return "waist_mm" in self.section


_RESULT_WIRE_KEYS = frozenset(
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


def _index_designs(design_results: Any) -> Dict[str, _Design]:
    """Design results keyed by element id, later entries winning on a repeat."""
    out = {}  # type: Dict[str, _Design]
    for source in design_results or []:
        design = _Design(source)
        if design.element_id:
            out[design.element_id] = design
    return out


# ---------------------------------------------------------------------------
# take-off rows
# ---------------------------------------------------------------------------


@dataclass
class ElementVolume:
    """One element's concrete, kept beside the aggregate so a line is traceable."""

    element_id: str
    element_class: str
    grade: str
    storey: int
    volume_m3: float
    basis: str

    def to_dict(self, dp: int = 2) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "class": self.element_class,
            "grade": self.grade,
            "storey": int(self.storey),
            "volume_m3": _r(self.volume_m3, dp),
            "volume_exact_m3": _r(self.volume_m3, 6),
            "basis": self.basis,
        }


@dataclass
class ElementQuantity:
    """Concrete for one (class, grade), aggregated from the per-element rows.

    `volume_m3` is the reported figure, rounded to 0.01 m3 as the spec asks;
    `volume_exact_m3` is the sum before rounding, so the totals a report adds up
    do not drift from the lines it prints. Both ship (spec 1.2, report both).
    """

    element_class: str
    grade: str
    volume_m3: float
    basis: str
    count: int = 0
    element_ids: List[str] = field(default_factory=list)

    def to_dict(self, dp: int = 2, compact: bool = False) -> Dict[str, Any]:
        """The class row. `compact` drops the id roll-call, never a number.

        `element_ids` is the list of members this line was summed from; it is one
        id per member, so on a 775-member building the eight class rows together
        carry the whole model's ids a second time. The count stays, the volumes
        stay, and `concrete_by_element` at `detail=full` is the per-member list.
        """
        out = {
            "class": self.element_class,
            "grade": self.grade,
            "volume_m3": _r(self.volume_m3, dp),
            "volume_exact_m3": _r(self.volume_m3, 6),
            "count": int(self.count),
            "element_ids": [] if compact else sorted(self.element_ids),
            "basis": self.basis,
        }  # type: Dict[str, Any]
        if compact:
            out["element_ids_total"] = len(self.element_ids)
            out["element_ids_elided"] = True
            out["element_ids_ref"] = "structural_model.columns / .beams / .slabs / .footings"
            out["element_ids_elided_reason"] = _ELIDED_FOR_DETAIL
        return out


@dataclass
class FormworkQuantity:
    """Shuttering for one class, m2 of surface in contact with concrete."""

    element_class: str
    area_m2: float
    basis: str
    count: int = 0

    def to_dict(self, dp: int = 2) -> Dict[str, Any]:
        return {
            "class": self.element_class,
            "area_m2": _r(self.area_m2, dp),
            "area_exact_m2": _r(self.area_m2, 6),
            "count": int(self.count),
            "basis": self.basis,
        }


@dataclass
class MasonryQuantity:
    """Walling of one thickness class, split bearing from non-bearing."""

    thickness_mm: int
    bearing: bool
    volume_m3: float
    deductions_m3: float
    basis: str
    count: int = 0
    wall_ids: List[str] = field(default_factory=list)

    @property
    def gross_m3(self) -> float:
        return self.volume_m3 + self.deductions_m3

    def to_dict(self, dp: int = 2) -> Dict[str, Any]:
        return {
            "thickness_mm": int(self.thickness_mm),
            "bearing": bool(self.bearing),
            "volume_m3": _r(self.volume_m3, dp),
            "volume_exact_m3": _r(self.volume_m3, 6),
            "gross_m3": _r(self.gross_m3, dp),
            "deductions_m3": _r(self.deductions_m3, dp),
            "count": int(self.count),
            "wall_ids": sorted(self.wall_ids),
            "basis": self.basis,
        }


@dataclass
class FootingEarthwork:
    """The pit under one footing, and what comes back into it."""

    footing_id: str
    depth_m: float
    plan_l_m: float
    plan_b_m: float
    excavation_m3: float
    pcc_m3: float
    footing_m3: float
    pedestal_m3: float
    backfill_m3: float
    disposal_m3: float
    slope_factor: float
    depth_assumed: bool
    basis: str

    def to_dict(self, dp: int = 2) -> Dict[str, Any]:
        return {
            "footing_id": self.footing_id,
            "depth_m": _r(self.depth_m, 3),
            "plan_l_m": _r(self.plan_l_m, 3),
            "plan_b_m": _r(self.plan_b_m, 3),
            "excavation_m3": _r(self.excavation_m3, dp),
            "pcc_m3": _r(self.pcc_m3, dp),
            "footing_m3": _r(self.footing_m3, dp),
            "pedestal_m3": _r(self.pedestal_m3, dp),
            "backfill_m3": _r(self.backfill_m3, dp),
            "disposal_m3": _r(self.disposal_m3, dp),
            "slope_factor": _r(self.slope_factor, 3),
            "depth_assumed": bool(self.depth_assumed),
            "basis": self.basis,
        }


@dataclass
class EarthworkQuantity:
    """The earthwork totals, and the pit-by-pit rows they were summed from."""

    excavation_m3: float = 0.0
    pcc_m3: float = 0.0
    backfill_m3: float = 0.0
    disposal_m3: float = 0.0
    basis: str = ""
    footings: List[FootingEarthwork] = field(default_factory=list)

    def to_dict(self, dp: int = 2) -> Dict[str, Any]:
        return {
            "excavation_m3": _r(self.excavation_m3, dp),
            "pcc_m3": _r(self.pcc_m3, dp),
            "backfill_m3": _r(self.backfill_m3, dp),
            "disposal_m3": _r(self.disposal_m3, dp),
            "excavation_exact_m3": _r(self.excavation_m3, 6),
            "basis": self.basis,
            "footings": [row.to_dict(dp) for row in self.footings],
        }


@dataclass
class QuantityTakeoff:
    """Everything measured off one designed model.

    The bar schedule rides here because reinforcement mass has exactly one
    source (finding 24) and the density metrics need it; `to_dict` carries only
    the schedule's aggregates, and `api.py` serializes `bbs` beside `takeoff`
    as the wire schema lays it out.
    """

    concrete: List[ElementQuantity] = field(default_factory=list)
    concrete_by_element: List[ElementVolume] = field(default_factory=list)
    formwork: List[FormworkQuantity] = field(default_factory=list)
    masonry: List[MasonryQuantity] = field(default_factory=list)
    earthwork: EarthworkQuantity = field(default_factory=EarthworkQuantity)
    bbs: Optional["BarBendingSchedule"] = None
    builtup_area_m2: float = 0.0
    builtup_basis: str = ""
    steel_grade: str = ""
    storeys: int = 0
    #: The structural system this take-off measured, straight off
    #: `StructuralModel.system`. It is carried because the density calibration
    #: bands are per system and `price` cannot see the model. Empty means the
    #: caller built the take-off by hand; `price` then judges it against
    #: `DEFAULT_BAND_SYSTEM` and says so.
    system: str = ""
    disclosures: DisclosureLog = field(default_factory=DisclosureLog)
    options: QuantityOptions = field(default_factory=QuantityOptions)

    # -- totals -------------------------------------------------------------

    @property
    def concrete_m3(self) -> float:
        """Concrete summed before rounding, per spec 1.2."""
        return sum(row.volume_m3 for row in self.concrete)

    @property
    def formwork_m2(self) -> float:
        return sum(row.area_m2 for row in self.formwork)

    @property
    def masonry_m3(self) -> float:
        return sum(row.volume_m3 for row in self.masonry)

    @property
    def steel_kg(self) -> float:
        """Reinforcement including wastage; zero when no schedule was built."""
        return 0.0 if self.bbs is None else self.bbs.total_with_wastage_kg

    def to_dict(self, detail: Optional[str] = None) -> Dict[str, Any]:
        """The take-off. `detail` overrides the level the options carry.

        Same rule as the schedule: a consumer with arithmetic to do over the
        per-element rows asks for `DETAIL_FULL` and elides afterwards.
        """
        dp = self.options.volume_dp
        area_dp = self.options.area_dp
        compact = (
            self.options.compact
            if detail is None
            else str(detail).strip().lower() == DETAIL_COMPACT
        )
        earthwork = self.earthwork.to_dict(dp)
        if compact:
            _elide_rows(
                earthwork,
                "footings",
                "structural_model.footings",
                "the pit totals above are the sum of these rows",
            )
        out = {
            "concrete": [row.to_dict(dp, compact) for row in self.concrete],
            "concrete_by_element": (
                [] if compact else [row.to_dict(dp) for row in self.concrete_by_element]
            ),
            "formwork": [row.to_dict(area_dp) for row in self.formwork],
            "masonry": [row.to_dict(dp) for row in self.masonry],
            "earthwork": earthwork,
            "steel": {
                "total_kg": _r(0.0 if self.bbs is None else self.bbs.total_kg, self.options.mass_dp),
                "total_with_wastage_kg": _r(self.steel_kg, self.options.mass_dp),
                "wastage_pct": _r(self.options.wastage_pct, 3),
                "basis": "reinforcement is taken from the bar bending schedule only, never from a percentage",
            },
            "totals": {
                "concrete_m3": _r(self.concrete_m3, dp),
                "formwork_m2": _r(self.formwork_m2, area_dp),
                "masonry_m3": _r(self.masonry_m3, dp),
                "steel_kg": _r(self.steel_kg, self.options.mass_dp),
                "excavation_m3": _r(self.earthwork.excavation_m3, dp),
            },
            # The same four totals flat, because a consumer that adds up the
            # rounded rows instead lands a cent short of the priced bill; these
            # are the figures summed before rounding, per spec 1.2.
            "concrete_m3": _r(self.concrete_m3, dp),
            "formwork_m2": _r(self.formwork_m2, area_dp),
            "masonry_m3": _r(self.masonry_m3, dp),
            "steel_kg": _r(self.steel_kg, self.options.mass_dp),
            "builtup_area_m2": _r(self.builtup_area_m2, area_dp),
            "builtup_basis": self.builtup_basis,
            "steel_grade": self.steel_grade,
            "storeys": int(self.storeys),
            "system": self.system,
            "disclosures": [entry.to_dict() for entry in self.disclosures.sorted_entries()],
            "options_echo": self.options.to_dict(),
        }
        if compact:
            out["concrete_by_element_total"] = len(self.concrete_by_element)
            out["concrete_by_element_elided"] = True
            out["concrete_by_element_ref"] = (
                "concrete (the same volumes, aggregated by class and grade)"
            )
            out["concrete_by_element_elided_reason"] = _ELIDED_FOR_DETAIL
        out["detail"] = DETAIL_COMPACT if compact else DETAIL_FULL
        return out


# ---------------------------------------------------------------------------
# measurement conventions, written once so the report and the tests share them
# ---------------------------------------------------------------------------

#: The `basis` sentence each concrete class is measured under.
CONCRETE_BASIS = {
    "column": (
        "b x D x clear height per storey, the storey height less the deepest beam framing into its head "
        "(IS 1200 Part 2 Cl 4.5); no deductions"
    ),
    "beam": (
        "b x full D x clear span between column faces, the column widths deducted at both ends; the "
        "beam-slab overlap is deducted from the slab, not from the beam"
    ),
    "plinth_beam": (
        "b x full D x clear span between column faces, measured at plinth level; no slab overlaps it"
    ),
    "slab": (
        "panel area less the beam plan footprints, less every opening over 0.1 m2 "
        "(IS 1200 Part 5 Cl 4.4), times the slab thickness"
    ),
    "stair": (
        "inclined waist, plan length / cos(incline) x width x waist, plus the step triangles "
        "0.5 x going x riser x width x risers; landings are measured under slab"
    ),
    "band": (
        "wall centreline length x wall thickness x band depth (IS 4326 Table 6); openings are not "
        "deducted, the band over an opening is the lintel"
    ),
    "lintel": "(clear opening width + 2 x bearing) x wall thickness x lintel depth",
    "footing": "L x B x uniform thickness; no deductions, and v1 pads are of uniform thickness only",
}

#: The `basis` sentence each formwork class is measured under, IS 1200 Part 5:
#: formwork is the surface actually in contact with concrete.
FORMWORK_BASIS = {
    "column": "perimeter x clear height, all four faces",
    "beam": "two sides over the depth below the slab, plus the soffit, over the clear span",
    "plinth_beam": "two sides over the full depth, plus the soffit, over the clear span",
    "slab": "soffit only, the panel less the beam footprints; edge strips are not measured",
    "stair": "inclined soffit only; riser boards and the side edges are not measured",
    "band": "two sides plus the soffit over the band run",
    "lintel": "two sides plus the soffit over the lintel run",
    "footing": "side shutters only, perimeter x thickness; a footing has no soffit",
}

_EMPTY_BASIS = "no elements of this class are in the model; the row ships at zero rather than as a gap"
_BLOCKED_BASIS = "an ERROR blocked this element upstream, so no quantity is taken for it"


# ---------------------------------------------------------------------------
# working rows
# ---------------------------------------------------------------------------


@dataclass
class _Segment:
    """One linear member reduced to what the take-off needs of it."""

    element_id: str
    element_class: str
    storey: int
    b_m: float
    depth_m: float
    clear_length_m: float
    grade: str
    x0: float
    y0: float
    x1: float
    y1: float
    note: str = ""

    def footprint(self) -> Tuple[float, float, float, float]:
        """Plan rectangle (x0, y0, x1, y1) the member covers over its clear span."""
        half = 0.5 * self.b_m
        if abs(self.y1 - self.y0) <= _GEOM_TOL_M:
            return (min(self.x0, self.x1), self.y0 - half, max(self.x0, self.x1), self.y0 + half)
        if abs(self.x1 - self.x0) <= _GEOM_TOL_M:
            return (self.x0 - half, min(self.y0, self.y1), self.x0 + half, max(self.y0, self.y1))
        # A skew member is boxed: v1 grids are orthogonal, so this is a guard,
        # not a case, and boxing is the safe side for a slab deduction.
        return (
            min(self.x0, self.x1) - half,
            min(self.y0, self.y1) - half,
            max(self.x0, self.x1) + half,
            max(self.y0, self.y1) + half,
        )


class _Acc(object):
    """Accumulates the two things every element contributes: volume and shutter."""

    __slots__ = ("volumes", "formwork")

    def __init__(self) -> None:
        self.volumes = []  # type: List[ElementVolume]
        self.formwork = {}  # type: Dict[str, List[float]]

    def volume(self, element_id: str, element_class: str, grade: str, storey: int, value_m3: float, basis: str) -> None:
        self.volumes.append(
            ElementVolume(
                element_id=str(element_id),
                element_class=str(element_class),
                grade=str(grade),
                storey=int(storey),
                volume_m3=max(0.0, float(value_m3)),
                basis=str(basis),
            )
        )

    def shutter(self, element_class: str, area_m2: float) -> None:
        row = self.formwork.setdefault(str(element_class), [0.0, 0.0])
        row[0] += max(0.0, float(area_m2))
        row[1] += 1.0


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------


def _polygon_area_m2(polygon: Sequence[Sequence[float]]) -> float:
    """Shoelace area of a plan loop, always positive."""
    points = [(float(p[0]), float(p[1])) for p in polygon or []]
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index in range(len(points)):
        ax, ay = points[index]
        bx, by = points[(index + 1) % len(points)]
        total += ax * by - bx * ay
    return abs(total) * 0.5


def _net_panel_area_m2(
    polygon: Sequence[Sequence[float]],
    footprints: Sequence[Tuple[float, float, float, float]],
    openings: Sequence[Sequence[Sequence[float]]],
    min_opening_m2: float,
) -> Tuple[float, float, float, List[float]]:
    """(net, beam footprint, openings deducted, opening areas) for one panel, m2.

    Beam footprints are unioned before they are cut out, so a crossing at a
    column is not deducted twice. An opening is deducted only where its own area
    inside the panel exceeds `min_opening_m2` (IS 1200 Part 5 Cl 4.4): exactly
    at the limit it stays, because the clause reads "exceeding".
    """
    gross = _polygon_area_m2(polygon)
    if gross <= 0.0:
        return (0.0, 0.0, 0.0, [])

    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    panel = Polygon([(float(p[0]), float(p[1])) for p in polygon])
    if not panel.is_valid:
        panel = panel.buffer(0.0)

    beams = [box(x0, y0, x1, y1) for x0, y0, x1, y1 in footprints if x1 > x0 and y1 > y0]
    beam_union = unary_union(beams) if beams else None
    beam_area = 0.0
    if beam_union is not None:
        beam_area = float(beam_union.intersection(panel).area)

    kept = []  # type: List[float]
    holes = []
    for loop in openings:
        shape = Polygon([(float(p[0]), float(p[1])) for p in loop])
        if not shape.is_valid:
            shape = shape.buffer(0.0)
        clipped = shape.intersection(panel)
        area = float(clipped.area)
        if area <= float(min_opening_m2) + 1e-12:
            continue
        kept.append(area)
        holes.append(clipped)
    opening_area = 0.0
    if holes:
        # Where an opening overlaps a beam footprint the panel has already lost
        # that area once; subtracting the beams keeps the deduction single.
        merged_holes = unary_union(holes)
        if beam_union is not None:
            merged_holes = merged_holes.difference(beam_union)
        opening_area = float(merged_holes.area)

    net = max(0.0, gross - beam_area - opening_area)
    return (net, beam_area, opening_area, sorted(kept))


def _rect_loop(x: float, y: float, w: float, h: float) -> List[Tuple[float, float]]:
    """A rectangle as a plan loop, y-down like every other polygon here."""
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _shrink(a: Tuple[float, float], b: Tuple[float, float], length_m: float) -> Tuple[float, float, float, float]:
    """The segment a-b shortened symmetrically about its midpoint to `length_m`."""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    full = math.hypot(bx - ax, by - ay)
    if full <= _GEOM_TOL_M:
        return (ax, ay, bx, by)
    keep = max(0.0, min(float(length_m), full))
    trim = 0.5 * (full - keep) / full
    return (ax + (bx - ax) * trim, ay + (by - ay) * trim, bx - (bx - ax) * trim, by - (by - ay) * trim)


# ---------------------------------------------------------------------------
# the model, read the way the take-off needs it
# ---------------------------------------------------------------------------


@dataclass
class _Ctx:
    """The one working state a take-off pass carries."""

    model: StructuralModel
    designs: Dict[str, "_Design"]
    options: QuantityOptions
    log: DisclosureLog
    acc: _Acc = field(default_factory=_Acc)
    slab_t_m: Dict[int, float] = field(default_factory=dict)
    beam_d_m: Dict[int, float] = field(default_factory=dict)

    def design(self, element_id: str) -> Optional["_Design"]:
        return self.designs.get(str(element_id))

    def blocked(self, element_id: str) -> bool:
        return str(element_id) in self.options.blocked_element_ids

    def note(self, code: str, message: str, element_ids: Sequence[str] = (), clause: Optional[str] = None) -> Disclosure:
        return self.log.add(code, message, element_ids=element_ids, clause=clause, stage=_STAGE)

    def grade(self, design: Optional["_Design"]) -> Tuple[str, bool]:
        """(concrete grade, assumed) for one element."""
        if design is not None and design.concrete_grade:
            return (design.concrete_grade, False)
        return (str(self.options.default_concrete_grade), True)


def _storey_height_m(model: StructuralModel, index: int) -> float:
    storey = model.storey(int(index))
    return 0.0 if storey is None else float(storey.height_m)


def _slab_thickness_m(ctx: _Ctx, storey: int) -> float:
    """The slab thickness a beam and a wall on this storey are measured against.

    The thickest floor plate on the storey: it is the one a beam's side shutter
    stops under and the one a wall stops below, and taking the thickest is the
    safe side for both.
    """
    key = int(storey)
    if key in ctx.slab_t_m:
        return ctx.slab_t_m[key]
    best = 0.0
    for panel in sorted(ctx.model.slabs_on(key), key=lambda s: s.id):
        design = ctx.design(panel.id)
        thickness = None if design is None else design.m("thickness_mm", "D_mm")
        if thickness is None:
            thickness = None if panel.thickness_m is None else float(panel.thickness_m)
        if thickness is not None:
            best = max(best, float(thickness))
    ctx.slab_t_m[key] = best
    return best


def _beam_depth_m(ctx: _Ctx, storey: int) -> float:
    """The deepest beam at the head of this storey, which the column stops under."""
    key = int(storey)
    if key in ctx.beam_d_m:
        return ctx.beam_d_m[key]
    best = 0.0
    for beam in sorted(ctx.model.beams_on(key), key=lambda b: b.id):
        if _word(beam.kind) == BeamKind.PLINTH.value:
            continue
        design = ctx.design(beam.id)
        depth = None if design is None else design.m("D_mm")
        if depth is None:
            depth = None if beam.depth_m is None else float(beam.depth_m)
        if depth is not None:
            best = max(best, float(depth))
    ctx.beam_d_m[key] = best
    return best


def _column_plan_mm(column: Any, design: Optional["_Design"]) -> Tuple[float, float]:
    """(size along x, size along y) of a column in metres, rotation applied."""
    b_m = None if design is None else design.m("b_mm")
    d_m = None if design is None else design.m("D_mm")
    if b_m is None:
        b_m = float(getattr(column, "width_m", 0.0) or 0.0)
    if d_m is None:
        d_m = float(getattr(column, "depth_m", 0.0) or 0.0)
    if int(getattr(column, "rot", 0) or 0) % 180 == 90:
        return (d_m, b_m)
    return (b_m, d_m)


def _support_deduction_m(ctx: _Ctx, storey: int, point: Sequence[float], along_x: bool) -> float:
    """Half the column at `point`, measured along the beam axis; 0 with no column."""
    best = 0.0
    px, py = float(point[0]), float(point[1])
    for column in sorted(ctx.model.columns_on(int(storey)), key=lambda c: c.id):
        if abs(float(column.x_m) - px) > 0.05 or abs(float(column.y_m) - py) > 0.05:
            continue
        size_x, size_y = _column_plan_mm(column, ctx.design(column.id))
        best = max(best, 0.5 * (size_x if along_x else size_y))
    return best


# ---------------------------------------------------------------------------
# concrete and formwork, class by class
# ---------------------------------------------------------------------------


def _measure_columns(ctx: _Ctx) -> None:
    """b x D x clear height per storey, and the four faces over that height."""
    columns = sorted(ctx.model.columns, key=lambda c: c.id)
    if not columns:
        return
    # No element_ids: the convention is the whole class's, and listing every
    # column of a 200-column building would be payload, not information.
    ctx.note(
        "N_COLUMN_HEIGHT_CONVENTION",
        "column concrete and shuttering are measured over the clear height, the storey height less the "
        "deepest beam framing into the column head; the slab thickness is not deducted a second time",
        clause="IS 1200 Part 2 Cl 4.5",
    )
    for column in columns:
        design = ctx.design(column.id)
        grade, assumed = ctx.grade(design)
        if ctx.blocked(column.id):
            ctx.acc.volume(column.id, "column", grade, column.storey, 0.0, _BLOCKED_BASIS)
            continue
        size_x, size_y = _column_plan_mm(column, design)
        height = _storey_height_m(ctx.model, column.storey)
        if height <= 0.0 and design is not None:
            height = design.m("length_mm") or 0.0
        clear = max(0.0, height - _beam_depth_m(ctx, column.storey))
        basis = CONCRETE_BASIS["column"]
        if assumed:
            basis += "; concrete grade assumed " + grade
        if clear <= 0.0:
            basis = "no clear height is available for this column, so it is measured as zero"
        ctx.acc.volume(column.id, "column", grade, column.storey, size_x * size_y * clear, basis)
        ctx.acc.shutter("column", 2.0 * (size_x + size_y) * clear)


def _beam_segments(ctx: _Ctx) -> List[_Segment]:
    """Every beam reduced to its clear span, in id order. Plinth beams included."""
    out = []  # type: List[_Segment]
    for beam in sorted(ctx.model.beams, key=lambda b: b.id):
        kind = _word(beam.kind)
        element_class = "plinth_beam" if kind == BeamKind.PLINTH.value else "beam"
        design = ctx.design(beam.id)
        b_m = None if design is None else design.m("b_mm")
        d_m = None if design is None else design.m("D_mm")
        if b_m is None:
            b_m = float(beam.width_m or 0.0)
        if d_m is None:
            d_m = float(beam.depth_m or 0.0)
        span = float(beam.span_m())
        along_x = abs(beam.b[1] - beam.a[1]) <= _GEOM_TOL_M
        stated = None if design is None else design.mm("clear_span_mm")
        if stated is not None and stated > 0.0:
            clear = stated / 1000.0
        else:
            clear = span - _support_deduction_m(ctx, beam.storey, beam.a, along_x) - _support_deduction_m(
                ctx, beam.storey, beam.b, along_x
            )
        clear = max(0.0, min(clear, span))
        x0, y0, x1, y1 = _shrink(beam.a, beam.b, clear)
        grade, assumed = ctx.grade(design)
        out.append(
            _Segment(
                element_id=beam.id,
                element_class=element_class,
                storey=int(beam.storey),
                b_m=b_m,
                depth_m=d_m,
                clear_length_m=clear,
                grade=grade,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                note=("; concrete grade assumed " + grade) if assumed else "",
            )
        )
    return out


def _measure_beams(ctx: _Ctx, segments: Sequence[_Segment]) -> None:
    """Full depth over the clear span; the slab keeps the overlap deduction."""
    for seg in segments:
        basis = CONCRETE_BASIS[seg.element_class] + seg.note
        if ctx.blocked(seg.element_id):
            ctx.acc.volume(seg.element_id, seg.element_class, seg.grade, seg.storey, 0.0, _BLOCKED_BASIS)
            continue
        if seg.depth_m <= 0.0:
            basis = "no beam depth was placed or designed, so this beam is measured as zero"
        ctx.acc.volume(
            seg.element_id,
            seg.element_class,
            seg.grade,
            seg.storey,
            seg.b_m * seg.depth_m * seg.clear_length_m,
            basis,
        )
        slab_t = 0.0 if seg.element_class == "plinth_beam" else _slab_thickness_m(ctx, seg.storey)
        below = max(0.0, seg.depth_m - slab_t)
        ctx.acc.shutter(seg.element_class, (2.0 * below + seg.b_m) * seg.clear_length_m)


def _slab_openings(ctx: _Ctx, storey: int) -> List[List[Tuple[float, float]]]:
    """Loops that punch the floor plate of this storey, in a deterministic order.

    Two sources, unioned by the caller: the cores (a stair or lift shaft is a
    hole through every plate it passes) and an explicit
    `model.meta["slab_openings"]` list, which is how a caller states a shaft the
    core plan does not carry.
    """
    loops = []  # type: List[List[Tuple[float, float]]]
    for core in sorted(ctx.model.cores_on(int(storey)), key=lambda c: c.id):
        loops.append(_rect_loop(float(core.x_m), float(core.y_m), float(core.w_m), float(core.h_m)))
    declared = ctx.model.meta.get("slab_openings")
    if isinstance(declared, (list, tuple)):
        rows = []
        for entry in declared:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("storey") is not None and int(entry["storey"]) != int(storey):
                continue
            rows.append(entry)
        for entry in sorted(rows, key=lambda row: str(row.get("id", ""))):
            polygon = entry.get("polygon_m")
            if polygon:
                loops.append([(float(p[0]), float(p[1])) for p in polygon])
                continue
            rect = entry.get("rect_m")
            if rect and len(rect) == 4:
                loops.append(_rect_loop(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])))
    return loops


def _measure_slabs(ctx: _Ctx, segments: Sequence[_Segment]) -> float:
    """Panel less beam footprints less openings; returns the gross plate area."""
    by_storey = {}  # type: Dict[int, List[Tuple[float, float, float, float]]]
    for seg in segments:
        if seg.element_class == "plinth_beam":
            continue
        by_storey.setdefault(seg.storey, []).append(seg.footprint())

    gross_total = 0.0
    for panel in sorted(ctx.model.slabs, key=lambda s: s.id):
        design = ctx.design(panel.id)
        grade, assumed = ctx.grade(design)
        thickness = None if design is None else design.m("thickness_mm", "D_mm")
        if thickness is None:
            thickness = None if panel.thickness_m is None else float(panel.thickness_m)
        gross_total += _polygon_area_m2(panel.polygon)
        if ctx.blocked(panel.id):
            ctx.acc.volume(panel.id, "slab", grade, panel.storey, 0.0, _BLOCKED_BASIS)
            continue
        net, beam_area, opening_area, kept = _net_panel_area_m2(
            panel.polygon,
            by_storey.get(int(panel.storey), []),
            _slab_openings(ctx, panel.storey),
            ctx.options.opening_deduction_min_m2,
        )
        basis = CONCRETE_BASIS["slab"]
        basis += "; beam footprints " + _m2_text(beam_area)
        basis += ", openings deducted " + _m2_text(opening_area)
        basis += " over " + str(len(kept)) + " opening(s) past the limit"
        if assumed:
            basis += "; concrete grade assumed " + grade
        if thickness is None or thickness <= 0.0:
            basis = "no slab thickness was placed or designed, so this panel is measured as zero"
            thickness = 0.0
        ctx.acc.volume(panel.id, "slab", grade, panel.storey, net * float(thickness), basis)
        ctx.acc.shutter("slab", net)

    if ctx.model.slabs:
        ctx.note(
            "N_FORMWORK_EDGES_IGNORED",
            "slab shuttering is the soffit only; edge strips deeper than 200 mm are not measured in v1, and "
            "nor are a stair flight's riser boards and side edges",
            clause="IS 1200 Part 5",
        )
    return gross_total


def _stair_records(ctx: _Ctx) -> List[Dict[str, Any]]:
    """Every stair flight the model knows about, placement first, design second."""
    rows = {}  # type: Dict[str, Dict[str, Any]]
    frame = ctx.model.meta.get("frame_placement")
    if isinstance(frame, Mapping):
        for entry in frame.get("stair_slabs") or []:
            if not isinstance(entry, Mapping):
                continue
            rows[str(entry.get("id", ""))] = dict(entry)
    for element_id in sorted(ctx.designs):
        design = ctx.designs[element_id]
        if design.is_stair:
            rows.setdefault(element_id, {"id": element_id, "storey": 0})
    return [rows[key] for key in sorted(rows) if key]


def _measure_stairs(ctx: _Ctx) -> float:
    """Inclined waist plus the step triangles; returns the plan area of the flights."""
    plan_area = 0.0
    for record in _stair_records(ctx):
        element_id = str(record.get("id", ""))
        design = ctx.design(element_id)
        grade, assumed = ctx.grade(design)
        storey = int(_num(record.get("storey"), 0.0))
        if ctx.blocked(element_id):
            ctx.acc.volume(element_id, "stair", grade, storey, 0.0, _BLOCKED_BASIS)
            continue
        span = (None if design is None else design.m("span_mm")) or _num(record.get("span_m"))
        width = (None if design is None else design.m("width_mm")) or _num(record.get("width_m"))
        rise = _num(record.get("rise_m"))
        waist = None if design is None else design.m("waist_mm")
        incline = _num(record.get("incline_deg"))
        if design is not None and design.section.get("incline_deg") is not None:
            incline = _num(design.section["incline_deg"])
        risers = 0
        if design is not None and design.section.get("risers") is not None:
            risers = int(_num(design.section["risers"], 0.0))
        riser_m = (None if design is None else design.m("riser_mm")) or (rise / risers if risers else 0.0)
        going_m = (None if design is None else design.m("going_mm")) or (span / risers if risers else 0.0)
        plan_area += span * width

        if waist is None or waist <= 0.0 or span <= 0.0 or width <= 0.0:
            ctx.acc.volume(
                element_id,
                "stair",
                grade,
                storey,
                0.0,
                "the flight carries no designed waist thickness, so it is measured as zero",
            )
            continue
        cos_theta = math.cos(math.radians(incline))
        if cos_theta <= 1e-6:
            cos_theta = 1.0
        inclined_area = span / cos_theta * width
        steps = 0.5 * going_m * riser_m * width * risers
        basis = (
            CONCRETE_BASIS["stair"]
            + "; incline "
            + ("%.1f" % incline)
            + " deg, "
            + str(risers)
            + " risers"
        )
        if assumed:
            basis += "; concrete grade assumed " + grade
        ctx.acc.volume(element_id, "stair", grade, storey, inclined_area * float(waist) + steps, basis)
        ctx.acc.shutter("stair", inclined_area)
    return plan_area


def _band_depths(ctx: _Ctx) -> Dict[str, float]:
    """band_id -> designed depth in metres, from the masonry designer's schedule."""
    out = {}  # type: Dict[str, float]
    for element_id in sorted(ctx.designs):
        prescription = ctx.designs[element_id].extras.get("prescription")
        if not isinstance(prescription, Mapping):
            continue
        block = prescription.get("bands")
        if not isinstance(block, Mapping):
            continue
        for entry in block.get("bands") or []:
            if not isinstance(entry, Mapping):
                continue
            spec = entry.get("spec")
            band_id = str(entry.get("band_id", ""))
            if band_id and isinstance(spec, Mapping) and spec.get("depth_mm"):
                out[band_id] = _num(spec["depth_mm"]) / 1000.0
    return out


def _measure_bands(ctx: _Ctx) -> None:
    """Wall run x wall thickness x band depth; the band over an opening IS the lintel."""
    depths = _band_depths(ctx)
    walls = {wall.id: wall for wall in ctx.model.walls}
    for band in sorted(ctx.model.bands, key=lambda b: b.id):
        design = ctx.design(band.id)
        grade, assumed = ctx.grade(design)
        if ctx.blocked(band.id):
            ctx.acc.volume(band.id, "band", grade, band.storey, 0.0, _BLOCKED_BASIS)
            continue
        kind = _word(band.kind)
        default = ctx.options.roof_band_depth_mm if kind == BandKind.ROOF.value else ctx.options.band_depth_mm
        depth = depths.get(band.id)
        source = "IS 4326 Table 6 as designed"
        if depth is None:
            depth = float(default) / 1000.0
            source = "default " + _mm_text(default) + " for a " + kind + " band; no designed depth was supplied"
        volume = 0.0
        shutter = 0.0
        for wall_id in sorted(set(str(item) for item in band.wall_ids)):
            wall = walls.get(wall_id)
            if wall is None:
                continue
            length = float(wall.length_m())
            thickness = float(wall.thickness_m)
            volume += length * thickness * depth
            shutter += (2.0 * depth + thickness) * length
        basis = CONCRETE_BASIS["band"] + "; depth " + _mm_text(depth * 1000.0) + ", " + source
        if assumed:
            basis += "; concrete grade assumed " + grade
        ctx.acc.volume(band.id, "band", grade, band.storey, volume, basis)
        ctx.acc.shutter("band", shutter)


def _lintel_schedule(ctx: _Ctx) -> Dict[str, Dict[str, Any]]:
    """lintel id -> the placer's row, when placement/masonry.py wrote one."""
    block = ctx.model.meta.get("masonry_placement")
    if not isinstance(block, Mapping):
        return {}
    out = {}  # type: Dict[str, Dict[str, Any]]
    for row in block.get("lintel_schedule") or []:
        if isinstance(row, Mapping) and row.get("id"):
            out[str(row["id"])] = dict(row)
    return out


def _measure_lintels(ctx: _Ctx) -> None:
    """Discrete lintels: the bearing length is already in `Lintel.span_m`."""
    schedule = _lintel_schedule(ctx)
    walls = {wall.id: wall for wall in ctx.model.walls}
    for lintel in sorted(ctx.model.lintels, key=lambda item: item.id):
        design = ctx.design(lintel.id)
        grade, assumed = ctx.grade(design)
        wall = walls.get(lintel.wall_id)
        storey = 0 if wall is None else int(wall.storey)
        if ctx.blocked(lintel.id):
            ctx.acc.volume(lintel.id, "lintel", grade, storey, 0.0, _BLOCKED_BASIS)
            continue
        row = schedule.get(lintel.id, {})
        depth_mm = None if design is None else design.mm("D_mm", "depth_mm")
        if depth_mm is None and row.get("depth_mm") is not None:
            depth_mm = _num(row["depth_mm"])
        source = "as placed"
        if depth_mm is None:
            depth_mm = float(ctx.options.lintel_depth_mm)
            source = "default depth, no lintel schedule was supplied"
        depth = float(depth_mm) / 1000.0
        thickness = 0.0 if wall is None else float(wall.thickness_m)
        length = float(lintel.span_m)
        basis = (
            CONCRETE_BASIS["lintel"]
            + "; run "
            + _m_text(length)
            + " including both bearings, depth "
            + _mm_text(depth_mm)
            + " ("
            + source
            + ")"
        )
        if wall is None:
            basis = "the lintel names a wall the model does not carry, so it is measured as zero"
        if assumed:
            basis += "; concrete grade assumed " + grade
        ctx.acc.volume(lintel.id, "lintel", grade, storey, length * thickness * depth, basis)
        ctx.acc.shutter("lintel", (2.0 * depth + thickness) * length)


def _footing_plan_m(ctx: _Ctx, footing: Any, design: Optional["_Design"]) -> Tuple[float, float, Optional[float]]:
    """(L, B, thickness) in metres: designed rectangle first, placed second."""
    length = None if design is None else design.m("bx_mm", "length_mm")
    breadth = None if design is None else design.m("ly_mm", "width_mm")
    thickness = None if design is None else design.m("D_mm")
    if length is None:
        length = float(footing.w_m or 0.0)
    if breadth is None:
        breadth = float(footing.h_m or 0.0)
    return (length, breadth, thickness)


def _measure_footings(ctx: _Ctx) -> None:
    """L x B x uniform thickness, side shutters only."""
    for footing in sorted(ctx.model.footings, key=lambda f: f.id):
        design = ctx.design(footing.id)
        grade, assumed = ctx.grade(design)
        if ctx.blocked(footing.id):
            ctx.acc.volume(footing.id, "footing", grade, 0, 0.0, _BLOCKED_BASIS)
            continue
        length, breadth, thickness = _footing_plan_m(ctx, footing, design)
        basis = CONCRETE_BASIS["footing"] + "; " + _word(footing.kind) + " " + _m_text(length) + " x " + _m_text(breadth)
        if assumed:
            basis += "; concrete grade assumed " + grade
        if thickness is None or thickness <= 0.0:
            ctx.acc.volume(
                footing.id,
                "footing",
                grade,
                0,
                0.0,
                "the footing carries no designed thickness, so it is measured as zero",
            )
            continue
        ctx.acc.volume(footing.id, "footing", grade, 0, length * breadth * float(thickness), basis)
        ctx.acc.shutter("footing", 2.0 * (length + breadth) * float(thickness))


# ---------------------------------------------------------------------------
# masonry (IS 1200 Part 3 Cl 4.6: deduct an opening only over 0.1 m2)
# ---------------------------------------------------------------------------


def _opening_height_m(ctx: _Ctx, opening: Any) -> Tuple[float, bool]:
    """(height, stated) of one opening: the head less the sill where both are known."""
    head = getattr(opening, "head_m", None)
    sill = getattr(opening, "sill_m", None)
    if head is not None:
        return (max(0.0, float(head) - float(sill or 0.0)), True)
    kind = _word(getattr(opening, "kind", "door"))
    if kind == "window":
        return (float(ctx.options.default_window_height_m), False)
    return (float(ctx.options.default_opening_head_m), False)


def _band_depth_on_wall(ctx: _Ctx, wall_id: str, storey: int, depths: Mapping[str, float]) -> float:
    """Total band depth crossing one wall, metres: the wall stops under a band."""
    total = 0.0
    for band in sorted(ctx.model.bands, key=lambda b: b.id):
        if int(band.storey) != int(storey) or wall_id not in set(str(item) for item in band.wall_ids):
            continue
        kind = _word(band.kind)
        default = ctx.options.roof_band_depth_mm if kind == BandKind.ROOF.value else ctx.options.band_depth_mm
        total += depths.get(band.id, float(default) / 1000.0)
    return total


def _measure_masonry(ctx: _Ctx) -> List[MasonryQuantity]:
    """Walling by thickness class, bearing split out, openings deducted."""
    depths = _band_depths(ctx)
    rows = {}  # type: Dict[Tuple[int, bool], MasonryQuantity]
    assumed_ids = []  # type: List[str]
    partition_ids = []  # type: List[str]

    for wall in sorted(ctx.model.walls, key=lambda w: w.id):
        role = _word(wall.role)
        if role == WallRole.RAILING.value or ctx.blocked(wall.id):
            continue
        if _word(wall.material) != Material.BRICK_MASONRY.value:
            continue
        length = float(wall.length_m())
        thickness = float(wall.thickness_m)
        if length <= 0.0 or thickness <= 0.0:
            continue
        thickness_mm = int(round(thickness * 1000.0))
        bearing = bool(wall.bearing)
        storey_h = _storey_height_m(ctx.model, wall.storey)
        clear = max(
            0.0,
            storey_h - _slab_thickness_m(ctx, wall.storey) - _band_depth_on_wall(ctx, wall.id, wall.storey, depths),
        )
        gross = length * thickness * clear
        deduction = 0.0
        for opening in sorted(wall.openings, key=lambda o: (float(o.offset_m), str(o.id))):
            width = float(opening.width_m)
            height, stated = _opening_height_m(ctx, opening)
            area = width * min(height, clear) if clear > 0.0 else width * height
            if area <= float(ctx.options.opening_deduction_min_m2) + 1e-12:
                continue
            deduction += area * thickness
            if opening_assumed(opening):
                assumed_ids.append(str(opening.id))
            if not stated:
                assumed_ids.append(str(opening.id))
        key = (thickness_mm, bearing)
        row = rows.get(key)
        if row is None:
            row = MasonryQuantity(
                thickness_mm=thickness_mm,
                bearing=bearing,
                volume_m3=0.0,
                deductions_m3=0.0,
                basis=(
                    "wall centreline length x thickness x clear height (storey height less the slab and any "
                    "band crossing the wall); an opening is deducted only where its own area exceeds "
                    + _m2_text(ctx.options.opening_deduction_min_m2)
                    + " (IS 1200 Part 3 Cl 4.6)"
                ),
            )
            rows[key] = row
        row.volume_m3 += max(0.0, gross - deduction)
        row.deductions_m3 += deduction
        row.count += 1
        row.wall_ids.append(wall.id)
        if thickness_mm <= int(ctx.options.partition_thickness_mm):
            partition_ids.append(wall.id)

    if partition_ids:
        ctx.note(
            "N_PARTITION_M3_CONVENTION",
            "partitions "
            + _mm_text(ctx.options.partition_thickness_mm)
            + " thick and under are measured in cubic metres like every other wall; the trade often prices "
            "them by area instead, so a partition line is not directly comparable with a square-metre rate",
            element_ids=sorted(set(partition_ids)),
            clause="IS 1200 Part 3",
        )
    if assumed_ids:
        ctx.note(
            "W_DOOR_ASSUMED",
            "masonry deductions used opening geometry that was assumed rather than dressed, so the deducted "
            "volume is only as good as the assumption",
            element_ids=sorted(set(assumed_ids)),
            clause="IS 1200 Part 3 Cl 4.6",
        )
    return [rows[key] for key in sorted(rows)]


# ---------------------------------------------------------------------------
# earthwork (spec 1.6)
# ---------------------------------------------------------------------------


def _pedestal_area_m2(ctx: _Ctx, footing: Any) -> float:
    """Plan area of whatever rises out of the footing: a column stub or a wall."""
    area = 0.0
    supports = sorted(str(item) for item in (footing.supports or []))
    for element_id in supports:
        column = ctx.model.by_id(element_id)
        if column is None:
            continue
        if hasattr(column, "width_m") and hasattr(column, "depth_m") and hasattr(column, "stack_id"):
            size_x, size_y = _column_plan_mm(column, ctx.design(element_id))
            area += size_x * size_y
        elif hasattr(column, "thickness_m") and hasattr(column, "a"):
            area += float(column.thickness_m) * float(column.length_m())
    return area


def _measure_earthwork(ctx: _Ctx) -> EarthworkQuantity:
    """One pit per footing: excavation, PCC bedding, backfill and disposal."""
    options = ctx.options
    out = EarthworkQuantity(
        basis=(
            "pit (L + 2 x working space) x (B + 2 x working space) x depth below natural ground, working "
            "space " + _m_text(options.working_space_m) + "; PCC bedding "
            + _mm_text(options.pcc_thickness_m * 1000.0)
            + " thick with a " + _mm_text(options.pcc_offset_m * 1000.0)
            + " offset all round; backfill is the pit less the footing, the pedestal and the PCC; disposal is "
            "the balance"
        )
    )
    assumed_ids = []  # type: List[str]
    sloped_ids = []  # type: List[str]
    for footing in sorted(ctx.model.footings, key=lambda f: f.id):
        design = ctx.design(footing.id)
        length, breadth, thickness = _footing_plan_m(ctx, footing, design)
        if length <= 0.0 or breadth <= 0.0 or ctx.blocked(footing.id):
            continue
        depth_assumed = footing.depth_m is None
        depth = float(options.founding_depth_m) if depth_assumed else float(footing.depth_m)
        if depth_assumed:
            assumed_ids.append(footing.id)
        working = float(options.working_space_m)
        slope = 1.0
        if depth > float(options.slope_depth_m) + 1e-12:
            slope = float(options.slope_multiplier)
            sloped_ids.append(footing.id)
        pit = (length + 2.0 * working) * (breadth + 2.0 * working) * depth * slope
        pcc = (length + 2.0 * options.pcc_offset_m) * (breadth + 2.0 * options.pcc_offset_m) * options.pcc_thickness_m
        pad = length * breadth * float(thickness or 0.0)
        stub_height = max(0.0, depth - float(options.pcc_thickness_m) - float(thickness or 0.0))
        pedestal = _pedestal_area_m2(ctx, footing) * stub_height
        backfill = max(0.0, pit - pad - pedestal - pcc)
        disposal = max(0.0, pit - backfill)
        basis = (
            "pit "
            + _m_text(length + 2.0 * working)
            + " x "
            + _m_text(breadth + 2.0 * working)
            + " x "
            + _m_text(depth)
            + (
                (" with the flat " + ("%.2f" % slope) + " slope allowance for a pit deeper than "
                 + _m_text(options.slope_depth_m))
                if slope != 1.0
                else " with no slope allowance"
            )
            + ("; founding depth assumed" if depth_assumed else "; founding depth as founded")
        )
        out.footings.append(
            FootingEarthwork(
                footing_id=footing.id,
                depth_m=depth,
                plan_l_m=length,
                plan_b_m=breadth,
                excavation_m3=pit,
                pcc_m3=pcc,
                footing_m3=pad,
                pedestal_m3=pedestal,
                backfill_m3=backfill,
                disposal_m3=disposal,
                slope_factor=slope,
                depth_assumed=depth_assumed,
                basis=basis,
            )
        )
        out.excavation_m3 += pit
        out.pcc_m3 += pcc
        out.backfill_m3 += backfill
        out.disposal_m3 += disposal

    if sloped_ids:
        ctx.note(
            "N_SLOPE_ALLOWANCE_FLAT",
            "battered pit sides are approximated by a flat "
            + ("%.2f" % options.slope_multiplier)
            + " multiplier on excavation for any pit deeper than "
            + _m_text(options.slope_depth_m)
            + "; the true batter is not set out",
            element_ids=sorted(set(sloped_ids)),
        )
    if assumed_ids:
        ctx.note(
            "W_ASSUMED_FOUNDING_DEPTH",
            "no founding depth reached the take-off for "
            + str(len(set(assumed_ids)))
            + " footing(s), so excavation is measured to the default "
            + _m_text(options.founding_depth_m)
            + "; a geotechnical investigation must settle it",
            element_ids=sorted(set(assumed_ids)),
            clause="IS 1904:1986 Cl 5",
        )
    return out


# ---------------------------------------------------------------------------
# take_off
# ---------------------------------------------------------------------------


def _aggregate(volumes: Sequence[ElementVolume]) -> List[ElementQuantity]:
    """Per-element rows folded into one row per (class, grade), in report order."""
    rows = {}  # type: Dict[Tuple[str, str], ElementQuantity]
    for item in volumes:
        key = (item.element_class, item.grade)
        row = rows.get(key)
        if row is None:
            row = ElementQuantity(
                element_class=item.element_class,
                grade=item.grade,
                volume_m3=0.0,
                basis=CONCRETE_BASIS.get(item.element_class, ""),
            )
            rows[key] = row
        row.volume_m3 += item.volume_m3
        row.count += 1
        row.element_ids.append(item.element_id)
    order = {name: index for index, name in enumerate(CONCRETE_CLASSES)}
    return sorted(rows.values(), key=lambda row: (order.get(row.element_class, len(order)), row.element_class, row.grade))


def _builtup(ctx: _Ctx, slab_gross_m2: float, stair_plan_m2: float) -> Tuple[float, str]:
    """Built-up area, and the sentence saying how it was arrived at."""
    if slab_gross_m2 > 0.0 or stair_plan_m2 > 0.0:
        return (
            slab_gross_m2 + stair_plan_m2,
            "gross slab panel area of every storey plus the plan area of the stair flights; "
            "beam footprints and openings are NOT deducted from built-up area",
        )
    rooms = sum(float(room.area_m2) for room in ctx.model.rooms)
    if rooms > 0.0:
        return (rooms, "no slabs are placed, so built-up area falls back to the sum of the room areas")
    return (0.0, "neither slabs nor rooms carry an area, so the density metrics cannot be formed")


def take_off(model: StructuralModel, design_results: Any = None, options: Any = None) -> QuantityTakeoff:
    """Measure one designed model. Deterministic and pure: no file IO, no clock.

    `design_results` is the design layer's output, live `DesignResult`s or the
    dicts `to_dict()` made of them; both take off to the same numbers. Where a
    result exists it is authoritative for the section (design may have resized
    what placement put down) and for the concrete grade; where it does not, the
    placed geometry is measured and the row says so in its `basis`.

    Nothing here raises on a class the model does not carry: that class ships as
    a zero row naming the gap. An element an ERROR blocked upstream (named in
    `options.blocked_element_ids`) ships at zero with the reason, per the ladder.
    """
    settings = QuantityOptions.coerce(options)
    ctx = _Ctx(model=model, designs=_index_designs(design_results), options=settings, log=DisclosureLog())

    segments = _beam_segments(ctx)
    _measure_columns(ctx)
    _measure_beams(ctx, segments)
    slab_gross = _measure_slabs(ctx, segments)
    stair_plan = _measure_stairs(ctx)
    _measure_bands(ctx)
    _measure_lintels(ctx)
    _measure_footings(ctx)
    masonry = _measure_masonry(ctx)
    earthwork = _measure_earthwork(ctx)

    concrete = _aggregate(ctx.acc.volumes)
    present = {row.element_class for row in concrete}
    for name in CONCRETE_CLASSES:
        if name not in present:
            concrete.append(ElementQuantity(element_class=name, grade="", volume_m3=0.0, basis=_EMPTY_BASIS))
    order = {name: index for index, name in enumerate(CONCRETE_CLASSES)}
    concrete.sort(key=lambda row: (order.get(row.element_class, len(order)), row.element_class, row.grade))

    formwork = []  # type: List[FormworkQuantity]
    for name in FORMWORK_CLASSES:
        area, count = ctx.acc.formwork.get(name, [0.0, 0.0])
        formwork.append(
            FormworkQuantity(
                element_class=name,
                area_m2=area,
                basis=FORMWORK_BASIS.get(name, "") if count else _EMPTY_BASIS,
                count=int(count),
            )
        )

    builtup, builtup_basis = _builtup(ctx, slab_gross, stair_plan)
    bbs = build_bbs(design_results, settings)
    ctx.log.extend(bbs.disclosures.entries)

    steel_grade = ""
    for element_id in sorted(ctx.designs):
        grade = ctx.designs[element_id].steel_grade
        if grade:
            steel_grade = grade
            break
    if not steel_grade:
        steel_grade = str(settings.default_steel_grade)

    return QuantityTakeoff(
        concrete=concrete,
        concrete_by_element=sorted(ctx.acc.volumes, key=lambda row: (row.element_class, row.element_id)),
        formwork=formwork,
        masonry=masonry,
        earthwork=earthwork,
        bbs=bbs,
        builtup_area_m2=builtup,
        builtup_basis=builtup_basis,
        steel_grade=steel_grade,
        storeys=len(model.storeys),
        system=_word(model.system),
        disclosures=ctx.log,
        options=settings,
    )


# ---------------------------------------------------------------------------
# bar bending schedule (spec 1.3)
# ---------------------------------------------------------------------------

_STEEL_MASS = load_yaml("steel_mass")

#: Trade mass per metre, d^2/162 rounded the way a bar bender and a rate
#: analysis quote it. data/rebar.yaml stays canonical for the catalogue
#: (finding 25) and is read through `design.common` for the bend allowances; a
#: diameter this table does not carry falls back to it.
UNIT_MASS_KG_M = MappingProxyType(
    {int(dia): float(value) for dia, value in (_STEEL_MASS.get("unit_mass_kg_m") or {}).items()}
)

#: Mill stock length, m. A cut length past this needs a lap, and that lap is a
#: quantities decision, which is why the number lives beside the mass table.
STOCK_LENGTH_M = float(_STEEL_MASS.get("stock_length_m", 12.0))

#: Flat cut-length allowance for the two 135 degree hooks of a closed link, in
#: bar diameters. IS 2502 / IS 13920 via data/rebar.yaml, never re-tabulated.
STIRRUP_HOOK_DIA = float(BEND_ALLOWANCES.get("stirrup_two_hook_dia", 20.0))

#: Extension beyond one 90 degree bend, in bar diameters: what an "L" bar adds.
BEND_90_DIA = float(BEND_ALLOWANCES.get("hook_90_deg_dia", 8.0))


def _unit_mass_kg_m(dia_mm: float) -> Tuple[float, str]:
    """(kg/m, source) for one diameter: the trade table, then the catalogue."""
    dia = int(round(float(dia_mm)))
    if dia in UNIT_MASS_KG_M:
        return (UNIT_MASS_KG_M[dia], "steel_mass.yaml")
    from .design.common import unit_mass_kg_m as catalogue_mass

    try:
        return (float(catalogue_mass(dia)), "rebar.yaml")
    except ValueError:
        return (float(dia) * float(dia) / 162.0, "d^2/162")


@dataclass
class BBSItem:
    """One bar set: what to cut, how many, and what it weighs."""

    bar_mark: str
    element_id: str
    element_class: str
    shape_code: str
    dia_mm: int
    count: int
    cut_length_m: float
    unit_mass_kg_m: float
    total_mass_kg: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self, dp: int = 3) -> Dict[str, Any]:
        return {
            "bar_mark": self.bar_mark,
            "element_id": self.element_id,
            "element_class": self.element_class,
            "shape_code": self.shape_code,
            "dia_mm": int(self.dia_mm),
            "count": int(self.count),
            "cut_length_m": _r(self.cut_length_m, dp),
            "unit_mass_kg_m": _r(self.unit_mass_kg_m, 6),
            "total_mass_kg": _r(self.total_mass_kg, dp),
            "notes": list(self.notes),
        }


@dataclass
class BarBendingSchedule:
    """Every bar in the building, and the only place reinforcement mass exists."""

    items: List[BBSItem] = field(default_factory=list)
    mass_by_dia: Dict[int, float] = field(default_factory=dict)
    mass_by_class: Dict[str, float] = field(default_factory=dict)
    total_kg: float = 0.0
    wastage_pct: float = 3.0
    total_with_wastage_kg: float = 0.0
    shape_codes_deferred: bool = True
    items_elided: bool = False
    items_total: int = 0
    disclosures: DisclosureLog = field(default_factory=DisclosureLog)
    options: QuantityOptions = field(default_factory=QuantityOptions)

    def to_dict(self, detail: Optional[str] = None) -> Dict[str, Any]:
        """The schedule. `detail` overrides the level the options carry.

        A consumer that has arithmetic to do over the rows -- `report.py`
        subtracts a blocked element's mass back out of the aggregates, which it
        can only do row by row -- asks for `DETAIL_FULL` explicitly and elides
        afterwards. Nothing else may: eliding before that subtraction would move
        `total_kg`, and a level is not allowed to move a number.
        """
        dp = self.options.mass_dp
        compact = (
            self.options.compact
            if detail is None
            else str(detail).strip().lower() == DETAIL_COMPACT
        )
        cap = 0 if compact else max(0, int(self.options.bbs_max_items))
        shown = self.items[:cap] if (self.items_elided or compact) else self.items
        out = {
            "shape_codes_deferred": bool(self.shape_codes_deferred),
            "shape_codes": list(SHAPE_CODES),
            "items": [item.to_dict(dp) for item in shown],
            "items_elided": bool(self.items_elided or (compact and self.items_total)),
            "items_total": int(self.items_total),
            "mass_by_dia": {str(dia): _r(self.mass_by_dia[dia], dp) for dia in sorted(self.mass_by_dia)},
            "mass_by_class": {name: _r(self.mass_by_class[name], dp) for name in sorted(self.mass_by_class)},
            "total_kg": _r(self.total_kg, dp),
            "wastage_pct": _r(self.wastage_pct, 3),
            "total_with_wastage_kg": _r(self.total_with_wastage_kg, dp),
            "disclosures": [entry.to_dict() for entry in self.disclosures.sorted_entries()],
        }
        if compact:
            # Every priced number stays: the mass by diameter, the mass by class
            # and both totals are aggregates of the rows, not the rows.
            out["items_shown"] = len(out["items"])
            out["items_elided_reason"] = _ELIDED_FOR_DETAIL
        out["detail"] = DETAIL_COMPACT if compact else DETAIL_FULL
        return out


def _bbs_class(design: "_Design") -> str:
    """The class a bar is booked under. `build_bbs` never sees the model, so the
    class is read off the design result: the stair mode is the slab designer's
    `waist_mm`, everything else is the designer's own element_type."""
    if design.is_stair:
        return "stair"
    return design.element_type or "other"


def _zone_length_m(entry: Mapping[str, Any]) -> float:
    """Length of the zone a bar runs over, metres, from its own `zone_mm` pair."""
    zone = entry.get("zone_mm")
    if not zone or len(zone) < 2:
        return 0.0
    return abs(_num(zone[1]) - _num(zone[0])) / 1000.0


def _lap_m(entry: Mapping[str, Any], dia_mm: float, options: QuantityOptions) -> Tuple[float, bool]:
    """(lap or anchorage in metres, whether the flat 50d fallback was taken).

    Finding 24: the designer's own `ld_mm` is used wherever the bar carries one.
    The flat multiple is the fallback for a bar that carries none, and taking it
    raises `N_LAP_50D_FLAT` once for the whole schedule.
    """
    stated = entry.get("ld_mm")
    if stated is not None:
        value = _num(stated, -1.0)
        if value >= 0.0:
            return (value / 1000.0, False)
    return (float(options.lap_dia_multiple) * float(dia_mm) / 1000.0, True)


def _stock_laps(base_m: float, options: QuantityOptions) -> int:
    """How many extra laps a run longer than the mill stock length needs."""
    stock = float(options.stock_length_m)
    if stock <= 0.0 or base_m <= stock + 1e-9:
        return 0
    return int(math.ceil(base_m / stock - 1e-9)) - 1


def _shape_of(element_class: str, entry: Mapping[str, Any]) -> str:
    """The v1 shape code. Richer IS 2502 codes are deferred, and said to be."""
    role = _word(entry.get("role", ""))
    if element_class == "footing":
        return SHAPE_L
    if element_class in ("beam", "plinth_beam") and role.startswith("top"):
        return SHAPE_L
    return SHAPE_STRAIGHT


def _mark(letters: Dict[str, Dict[str, int]], element_class: str, element_id: str, role_letter: str,
          seq: Dict[Tuple[str, str], int]) -> str:
    """A stable bar mark, "C3-L1": class letter, element number, role, set number."""
    letter = _MARK_LETTERS.get(element_class, _MARK_FALLBACK)
    index = letters.get(element_class, {}).get(element_id, 0)
    key = (element_id, role_letter)
    seq[key] = seq.get(key, 0) + 1
    return letter + str(index) + "-" + role_letter + str(seq[key])


def build_bbs(design_results: Any = None, options: Any = None) -> BarBendingSchedule:
    """The bar bending schedule, walked off each designer's own bars.

    Every length rule here is the spec's, and every simplification raises its
    NOTE once: a lap or anchorage is the bar's own `ld_mm` (flat 50d only where
    the bar carries none, `N_LAP_50D_FLAT`), a closed link is 2(a + b) plus a
    flat 20d hook allowance with no bend deductions (`N_NO_BEND_DEDUCTION`),
    shape codes are STR / L / STP only (`N_BBS_SHAPE_CODES_DEFERRED`), and the
    wastage percentage is disclosed whatever it is set to (`N_WASTAGE_3PCT`).

    Cover comes from `DesignResult.section` and from nowhere else (finding 25):
    a section that states none cannot have its links measured, and the item
    ships at zero mass saying exactly that rather than inventing a cover.
    """
    settings = QuantityOptions.coerce(options)
    log = DisclosureLog()
    designs = [_Design(source) for source in (design_results or [])]
    designs.sort(key=lambda item: (_bbs_class(item), item.element_id))

    by_class = {}  # type: Dict[str, Dict[str, int]]
    for design in designs:
        table = by_class.setdefault(_bbs_class(design), {})
        if design.element_id not in table:
            table[design.element_id] = len(table) + 1

    items = []  # type: List[BBSItem]
    seq = {}  # type: Dict[Tuple[str, str], int]
    flat_lap_ids = []  # type: List[str]
    no_cover_ids = []  # type: List[str]

    for design in designs:
        element_class = _bbs_class(design)
        cover_mm = design.cover_mm
        b_mm = design.mm("b_mm")
        d_mm = design.mm("D_mm", "thickness_mm", "waist_mm")
        # An ERROR blocked this element upstream: its rows still appear, so the
        # report can show the code beside them, but they carry no mass. The
        # take-off zeroes the same element's concrete, so the two agree.
        blocked = design.element_id in settings.blocked_element_ids

        for entry in design.bars:
            dia = int(round(_num(entry.get("dia_mm"))))
            count = int(_num(entry.get("count")))
            if dia <= 0 or count <= 0:
                continue
            length = _zone_length_m(entry)
            lap, flat = _lap_m(entry, dia, settings)
            if flat:
                flat_lap_ids.append(design.element_id)
            ends = 1 if element_class == "column" else 2
            note = (
                "one lap per storey"
                if ends == 1
                else "anchored " + _m_text(lap) + " at each end"
            )
            base = length + ends * lap
            extra = _stock_laps(base, settings)
            cut = base + extra * lap
            shape = _shape_of(element_class, entry)
            notes = [note]
            if shape == SHAPE_L:
                cut += BEND_90_DIA * dia / 1000.0
                notes.append("one 90 degree bend, extension " + _mm_text(BEND_90_DIA * dia))
            if extra:
                notes.append(str(extra) + " stock lap(s) at " + _m_text(settings.stock_length_m))
            if flat:
                notes.append(
                    "no ld_mm on this bar, so a flat "
                    + str(int(settings.lap_dia_multiple))
                    + "d was used"
                )
            if entry.get("spacing_mm") is not None:
                notes.append("mesh at " + _mm_text(_num(entry["spacing_mm"])) + " centres")
            mass, source = _unit_mass_kg_m(dia)
            if source != "steel_mass.yaml":
                notes.append("unit mass from " + source)
            role_letter = "M" if entry.get("spacing_mm") is not None else "L"
            if blocked:
                cut = 0.0
                notes.append(_BLOCKED_BASIS)
            items.append(
                BBSItem(
                    bar_mark=_mark(by_class, element_class, design.element_id, role_letter, seq),
                    element_id=design.element_id,
                    element_class=element_class,
                    shape_code=shape,
                    dia_mm=dia,
                    count=count,
                    cut_length_m=cut,
                    unit_mass_kg_m=mass,
                    total_mass_kg=count * cut * mass,
                    notes=notes,
                )
            )

        for entry in design.stirrups:
            dia = int(round(_num(entry.get("dia_mm"))))
            spacing = _num(entry.get("spacing_mm"))
            legs = max(2, int(_num(entry.get("legs"), 2.0)))
            run = _zone_length_m(entry) * 1000.0
            if dia <= 0 or spacing <= 0.0 or run <= 0.0:
                continue
            sets = max(1, legs // 2)
            positions = int(math.floor(run / spacing + 1e-9)) + 1
            count = positions * sets
            mass, source = _unit_mass_kg_m(dia)
            notes = [
                "closed link 2(a + b) plus a flat "
                + str(int(settings.stirrup_hook_dia_multiple))
                + "d hook allowance, no bend deduction",
                str(positions) + " at " + _mm_text(spacing) + " centres",
            ]
            if sets > 1:
                notes.append(str(legs) + " legs measured as " + str(sets) + " closed links")
            if source != "steel_mass.yaml":
                notes.append("unit mass from " + source)
            if cover_mm is None or b_mm is None or d_mm is None:
                no_cover_ids.append(design.element_id)
                cut = 0.0
                notes.append(
                    "the section states no cover, width or depth, so the link cannot be measured; "
                    "cover is never defaulted in a bar schedule (finding 25)"
                )
            else:
                a_side = max(0.0, float(b_mm) - 2.0 * float(cover_mm))
                b_side = max(0.0, float(d_mm) - 2.0 * float(cover_mm))
                cut = (2.0 * (a_side + b_side) + settings.stirrup_hook_dia_multiple * dia) / 1000.0
            if blocked:
                cut = 0.0
                notes.append(_BLOCKED_BASIS)
            items.append(
                BBSItem(
                    bar_mark=_mark(by_class, element_class, design.element_id, "T", seq),
                    element_id=design.element_id,
                    element_class=element_class,
                    shape_code=SHAPE_STIRRUP,
                    dia_mm=dia,
                    count=count,
                    cut_length_m=cut,
                    unit_mass_kg_m=mass,
                    total_mass_kg=count * cut * mass,
                    notes=notes,
                )
            )

    items.sort(key=lambda item: (item.element_class, item.element_id, item.bar_mark))
    mass_by_dia = {}  # type: Dict[int, float]
    mass_by_class = {}  # type: Dict[str, float]
    total = 0.0
    for item in items:
        mass_by_dia[item.dia_mm] = mass_by_dia.get(item.dia_mm, 0.0) + item.total_mass_kg
        mass_by_class[item.element_class] = mass_by_class.get(item.element_class, 0.0) + item.total_mass_kg
        total += item.total_mass_kg

    wastage = float(settings.wastage_pct)
    schedule = BarBendingSchedule(
        items=items,
        mass_by_dia=mass_by_dia,
        mass_by_class=mass_by_class,
        total_kg=total,
        wastage_pct=wastage,
        total_with_wastage_kg=total * (1.0 + wastage / 100.0),
        shape_codes_deferred=True,
        items_elided=len(items) > max(0, int(settings.bbs_max_items)),
        items_total=len(items),
        disclosures=log,
        options=settings,
    )

    if items:
        log.add(
            "N_BBS_SHAPE_CODES_DEFERRED",
            "shape codes are limited to " + ", ".join(SHAPE_CODES) + " in this version; the richer IS 2502 "
            "codes are deferred and the field is already a string, so adding them is not a breaking change",
            stage=_STAGE,
            clause="IS 2502:1963",
        )
        # One code, one message: both halves are statements about how a cut
        # length was arrived at, and the log merges by code, so a second add
        # under this code would silently drop its own sentence.
        cut_message = (
            "cut lengths are measured along the bar centreline with hook and bend extensions added and no "
            "bend deductions taken; the schedule is therefore on the safe side of the cut list"
        )
        if no_cover_ids:
            cut_message += (
                "; links on "
                + str(len(set(no_cover_ids)))
                + " element(s) could not be measured at all because the section states no cover, width or "
                "depth, and cover is read from the design result and never defaulted here (finding 25), so "
                "those rows ship at zero mass"
            )
        log.add(
            "N_NO_BEND_DEDUCTION",
            cut_message,
            element_ids=sorted(set(no_cover_ids)),
            stage=_STAGE,
            clause="IS 2502:1963 Cl 5",
        )
        log.add(
            "N_WASTAGE_3PCT",
            ("%.1f" % wastage) + " percent wastage is added to the scheduled mass before it is priced",
            stage=_STAGE,
        )
    if flat_lap_ids:
        log.add(
            "N_LAP_50D_FLAT",
            str(len(set(flat_lap_ids)))
            + " element(s) carry bars with no development length of their own, so their laps and anchorages "
            "were taken at a flat "
            + str(int(settings.lap_dia_multiple))
            + "d; every bar the design layer wrote carries its own ld_mm and is measured on it",
            element_ids=sorted(set(flat_lap_ids)),
            stage=_STAGE,
            clause="IS 456:2000 Cl 26.2.1",
        )
    return schedule


# ---------------------------------------------------------------------------
# rates (spec 1.7): data/rates.yaml is the only table, overrides merge over it
# ---------------------------------------------------------------------------


@dataclass
class RateSchedule:
    """One priced schedule, plus a record of which rates an override replaced."""

    name: str
    label: str = ""
    currency: str = "INR"
    basis_year: int = 0
    placeholder: bool = True
    items: Dict[str, Any] = field(default_factory=dict)
    overridden: Tuple[str, ...] = ()
    source: str = ""

    def source_of(self, path: str) -> str:
        """`override` where an override supplied this rate, else the schedule name."""
        return "override" if path in self.overridden else self.name

    def lookup(self, group: str, key: Optional[str] = None) -> Optional[float]:
        """The rate at `group` or `group.key`, or None when the table has none."""
        block = self.items.get(group)
        if key is None:
            return None if not isinstance(block, (int, float)) else float(block)
        if not isinstance(block, Mapping):
            return None
        value = block.get(key)
        return None if value is None else _num(value)

    def keys_of(self, group: str) -> List[str]:
        block = self.items.get(group)
        return sorted(str(name) for name in block) if isinstance(block, Mapping) else []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "currency": self.currency,
            "basis_year": int(self.basis_year),
            "placeholder": bool(self.placeholder),
            "items": _sorted_plain(self.items),
            "overridden": list(self.overridden),
            "source": self.source,
        }


def _sorted_plain(value: Any) -> Any:
    """A JSON-safe, key-sorted copy: the rate table goes on the wire verbatim."""
    if isinstance(value, Mapping):
        return {str(key): _sorted_plain(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_sorted_plain(item) for item in value]
    return value


def _merge_rates(base: Mapping[str, Any], overrides: Mapping[str, Any], prefix: str, seen: List[str]) -> Dict[str, Any]:
    """`overrides` deep-merged over `base`; every replaced leaf path is recorded."""
    out = {str(key): base[key] for key in base}
    for key in sorted(overrides, key=str):
        path = prefix + str(key)
        value = overrides[key]
        current = out.get(str(key))
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            out[str(key)] = _merge_rates(current, value, path + ".", seen)
        else:
            out[str(key)] = value
            seen.append(path)
    return out


def load_rates(name: str = "default_india", overrides: Any = None) -> RateSchedule:
    """A named schedule from data/rates.yaml, with `overrides` merged over it.

    A district or client schedule is either another named entry in the table or
    an `overrides` mapping shaped like the `items` block; a rate that came from
    an override reports `rate_source` "override" on its BOQ line, so a priced
    response always says which number came from where. An unknown schedule name
    raises, naming every schedule the table does carry: silently falling back to
    a placeholder would be the one failure this module must not have.
    """
    table = load_yaml("rates")
    schedules = table.get("schedules") or {}
    wanted = str(name or table.get("default_schedule") or "default_india")
    if wanted not in schedules:
        raise ValueError(
            "rate schedule not in data/rates.yaml: " + repr(wanted) + "; known: " + ", ".join(sorted(schedules))
        )
    entry = dict(schedules[wanted])
    items = dict(entry.get("items") or {})
    seen = []  # type: List[str]
    if overrides:
        if not isinstance(overrides, Mapping):
            raise ValueError("rate overrides must be a mapping, got " + type(overrides).__name__)
        block = overrides.get("items") if isinstance(overrides.get("items"), Mapping) else overrides
        items = _merge_rates(items, block, "", seen)
    return RateSchedule(
        name=wanted,
        label=str(entry.get("label", "")),
        currency=str(entry.get("currency", "INR")),
        basis_year=int(_num(entry.get("basis_year"), 0.0)),
        placeholder=bool(entry.get("placeholder", False)),
        items=items,
        overridden=tuple(sorted(set(seen))),
        source=str(table.get("source", "")),
    )


def _coerce_rates(rates: Any) -> RateSchedule:
    """A RateSchedule from an instance, a schedule name, a mapping or None."""
    if isinstance(rates, RateSchedule):
        return rates
    if rates is None:
        return load_rates()
    if isinstance(rates, str):
        return load_rates(rates)
    if isinstance(rates, Mapping):
        if "items" in rates and isinstance(rates["items"], Mapping):
            return RateSchedule(
                name=str(rates.get("name", "custom")),
                label=str(rates.get("label", "")),
                currency=str(rates.get("currency", "INR")),
                basis_year=int(_num(rates.get("basis_year"), 0.0)),
                placeholder=bool(rates.get("placeholder", False)),
                items=dict(rates["items"]),
                source=str(rates.get("source", "")),
            )
        overrides = rates.get("overrides")
        if overrides is None and "schedule" not in rates:
            # A bare mapping shaped like the `items` block is an override set,
            # not an empty request for the defaults: pricing it at the shipped
            # rates would silently ignore what the caller asked for.
            overrides = rates
        return load_rates(str(rates.get("schedule", "default_india")), overrides)
    raise ValueError("rates must be a RateSchedule, a schedule name or a mapping, got " + type(rates).__name__)


# ---------------------------------------------------------------------------
# bill of quantities
# ---------------------------------------------------------------------------


@dataclass
class BOQItem:
    """One priced line. `rate_source` names where the number came from."""

    sl: int
    item: str
    spec: str
    unit: str
    qty: float
    rate: float
    amount: float
    rate_source: str

    def to_dict(self, dp: int = 2) -> Dict[str, Any]:
        return {
            "sl": int(self.sl),
            "item": self.item,
            "spec": self.spec,
            "unit": self.unit,
            "qty": _r(self.qty, dp),
            "rate": _r(self.rate, dp),
            "amount": _r(self.amount, dp),
            "rate_source": self.rate_source,
        }


@dataclass
class BOQ:
    """The priced bill, its subtotals, and the density sanity metrics.

    `density_checks` is the verdict block: one entry per check in
    `DENSITY_BAND_CHECKS`, each naming the metric, the value, the band it was
    judged against, where that band came from, whether the value sits inside it
    and which registry code carried the finding. It is on the payload whether or
    not a ladder entry was raised, so a reader can always see what was checked
    and what was deliberately not.
    """

    schedule: str = ""
    currency: str = "INR"
    placeholder_rates: bool = True
    items: List[BOQItem] = field(default_factory=list)
    subtotals: Dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    builtup_area_m2: float = 0.0
    cost_per_m2: float = 0.0
    steel_kg_per_m2: float = 0.0
    concrete_m3_per_m2: float = 0.0
    masonry_m3_per_m2: float = 0.0
    system: str = ""
    system_label: str = ""
    density_basis: str = ""
    density_checks: Dict[str, Any] = field(default_factory=dict)
    disclosures: DisclosureLog = field(default_factory=DisclosureLog)
    options: QuantityOptions = field(default_factory=QuantityOptions)

    def to_dict(self) -> Dict[str, Any]:
        dp = self.options.money_dp
        return {
            "schedule": self.schedule,
            "currency": self.currency,
            "placeholder_rates": bool(self.placeholder_rates),
            "items": [item.to_dict(dp) for item in self.items],
            "subtotals": {name: _r(self.subtotals[name], dp) for name in sorted(self.subtotals)},
            "total": _r(self.total, dp),
            "builtup_area_m2": _r(self.builtup_area_m2, self.options.area_dp),
            "cost_per_m2": _r(self.cost_per_m2, dp),
            "steel_kg_per_m2": _r(self.steel_kg_per_m2, 3),
            "concrete_m3_per_m2": _r(self.concrete_m3_per_m2, 4),
            "masonry_m3_per_m2": _r(self.masonry_m3_per_m2, 4),
            "system": self.system,
            "system_label": self.system_label,
            "density_basis": self.density_basis,
            "density_checks": _sorted_plain(self.density_checks),
            "disclosures": [entry.to_dict() for entry in self.disclosures.sorted_entries()],
        }


def _concrete_rate(schedule: RateSchedule, grade: str) -> Tuple[float, str]:
    """The rate for a grade, the nearest grade priced when it is not tabulated."""
    path = "concrete_m3." + str(grade)
    exact = schedule.lookup("concrete_m3", str(grade))
    if exact is not None:
        return (exact, schedule.source_of(path))
    known = schedule.keys_of("concrete_m3")
    if not known:
        return (0.0, "unrated")
    target = _num(str(grade).lstrip("Mm"), 0.0)
    nearest = min(known, key=lambda name: (abs(_num(name.lstrip("Mm"), 0.0) - target), name))
    value = schedule.lookup("concrete_m3", nearest) or 0.0
    return (value, schedule.name + " (" + nearest + " substituted for " + str(grade) + ")")


def _masonry_rate(schedule: RateSchedule, thickness_mm: int) -> Tuple[float, str]:
    """The rate for a wall thickness, prorated off the nearest tabulated one."""
    known = schedule.keys_of("masonry_m3")
    if not known:
        return (0.0, "unrated")
    thicknesses = {}  # type: Dict[str, float]
    for name in known:
        digits = "".join(char for char in name if char.isdigit())
        thicknesses[name] = _num(digits, 0.0)
    for name in known:
        if abs(thicknesses[name] - float(thickness_mm)) <= 0.5:
            return (schedule.lookup("masonry_m3", name) or 0.0, schedule.source_of("masonry_m3." + name))
    nearest = min(known, key=lambda name: (abs(thicknesses[name] - float(thickness_mm)), name))
    base = schedule.lookup("masonry_m3", nearest) or 0.0
    return (base, schedule.name + " (" + nearest + " substituted for a " + str(int(thickness_mm)) + " mm wall)")


def _formwork_rate(schedule: RateSchedule, element_class: str) -> Tuple[float, str]:
    """The rate for a class, through the alias table where the class has none."""
    exact = schedule.lookup("formwork_m2", element_class)
    if exact is not None:
        return (exact, schedule.source_of("formwork_m2." + element_class))
    alias = _FORMWORK_RATE_ALIAS.get(element_class)
    if alias is not None:
        value = schedule.lookup("formwork_m2", alias)
        if value is not None:
            return (value, schedule.name + " (" + alias + " formwork rate applied to " + element_class + ")")
    known = schedule.keys_of("formwork_m2")
    if not known:
        return (0.0, "unrated")
    return (
        schedule.lookup("formwork_m2", known[0]) or 0.0,
        schedule.name + " (" + known[0] + " formwork rate applied to " + element_class + ")",
    )


def _flat_rate(schedule: RateSchedule, group: str) -> Tuple[float, str]:
    value = schedule.lookup(group)
    if value is None:
        return (0.0, "unrated")
    return (value, schedule.source_of(group))


# ---------------------------------------------------------------------------
# the density calibration bands, resolved for one take-off
# ---------------------------------------------------------------------------

#: The option field holding each check's caller override, and the module default
#: that field carries when the caller has not touched it.
_BAND_OPTION_FIELD = {
    "steel": "steel_band_kg_m2",
    "concrete": "concrete_band_m3_m2",
    "masonry": "masonry_band_m3_m2",
}

#: What `QuantityOptions` carries for each check when nobody has set it. Read
#: once off a default instance so the two cannot drift: a band still equal to
#: this is the shipped default, not a caller's decision.
_SHIPPED_BAND_DEFAULT = MappingProxyType(
    {check: tuple(getattr(QuantityOptions(), field)) for check, field in sorted(_BAND_OPTION_FIELD.items())}
)


@dataclass(frozen=True)
class _BandChoice:
    """One resolved check: the band, where it came from, what it is called."""

    check: str
    band: Optional[Tuple[float, float]]
    source: str


def _resolve_bands(system: Any, options: QuantityOptions) -> Tuple[str, str, Dict[str, _BandChoice]]:
    """(system word, system label, one `_BandChoice` per check).

    Two rules, in this order. A band the caller set to anything other than the
    shipped default is the caller's and is used verbatim for every system, which
    is what makes `price(takeoff, None, {"steel_band_kg_m2": (0.0, 100.0)})` mean
    what it says. Otherwise the band is the row `data/density_bands.yaml` holds
    for the system the take-off measured, and a null there means the check is
    deliberately off for that system rather than passing.

    A system the table does not carry falls back to `DEFAULT_BAND_SYSTEM` and the
    substitution is named in `source`, so a response never quietly judges an
    unknown system against a frame heuristic.
    """
    name = _word(system)
    resolved = name if name in DENSITY_BANDS else DEFAULT_BAND_SYSTEM
    row = DENSITY_BANDS[resolved]
    if not name:
        origin = (
            "data/density_bands.yaml, the " + resolved + " row (the take-off names no system)"
        )
    elif resolved != name:
        origin = (
            "data/density_bands.yaml, the "
            + resolved
            + " row (substituted: the table carries no row for system "
            + name
            + ")"
        )
    else:
        origin = "data/density_bands.yaml, the " + resolved + " row"

    choices = {}  # type: Dict[str, _BandChoice]
    for check in DENSITY_BAND_CHECKS:
        supplied = tuple(getattr(options, _BAND_OPTION_FIELD[check]))
        if len(supplied) == 2 and supplied != _SHIPPED_BAND_DEFAULT[check]:
            choices[check] = _BandChoice(check, (float(supplied[0]), float(supplied[1])), "caller override")
        else:
            choices[check] = _BandChoice(check, row[check], origin)
    return (name, DENSITY_BAND_LABELS.get(resolved, resolved), choices)


def _band_text(check: str, band: Tuple[float, float]) -> str:
    """"2.50 to 7.00 kg/m2 of reinforcement", the phrase both sentences share."""
    meta = _BAND_CHECK_META[check]
    fmt = _BAND_LIMIT_FORMAT[check]
    return (
        (fmt % band[0])
        + " to "
        + (fmt % band[1])
        + " "
        + str(meta["unit"])
        + " of "
        + str(meta["noun"])
    )


def _join_clauses(clauses: Sequence[str]) -> str:
    """"a", "a and b", "a, b and c": the bands read as a sentence, not a list."""
    items = list(clauses)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _band_message(check: str, value: float, band: Tuple[float, float], label: str) -> str:
    """The sentence a reader gets when a density falls outside its band."""
    meta = _BAND_CHECK_META[check]
    fmt = _BAND_LIMIT_FORMAT[check]
    return (
        str(meta["noun"])
        + " works out at "
        + (_BAND_VALUE_FORMAT[check] % value)
        + " "
        + _BAND_QUANTITY_UNIT[check]
        + " per m2 of built-up area, outside the "
        + (fmt % band[0])
        + " to "
        + (fmt % band[1])
        + " "
        + str(meta["unit"])
        + " calibration band for "
        + label
        + "; check the take-off and the design before trusting the cost"
    )


def price(takeoff: QuantityTakeoff, rates: Any = None, options: Any = None, bbs: Any = None) -> BOQ:
    """Price a take-off. Deterministic: same take-off and same table, same bill.

    `rates` is a `RateSchedule`, a schedule name, or a mapping carrying either a
    full `items` block or `{schedule, overrides}`. Reinforcement is priced off
    the bar schedule the take-off carries (or the one passed here), never off a
    percentage, and every line names its `rate_source`.

    The three density calibration bands are resolved per system from
    `data/density_bands.yaml`, against `takeoff.system`: an RC frame is judged on
    reinforcement and concrete, a masonry house on those two plus the walling
    volume, which is the number worth sanity checking there, and each against its
    own values. Every check lands in `boq.density_checks` whether it fired, sat
    inside its band or was deliberately not run, so the payload is the whole
    verdict and the ladder carries only the findings.
    """
    settings = QuantityOptions.coerce(options) if options is not None else takeoff.options
    schedule = _coerce_rates(rates)
    log = DisclosureLog()
    money = settings.money_dp
    volume_dp = settings.volume_dp
    area_dp = settings.area_dp

    lines = []  # type: List[BOQItem]
    subtotals = {"concrete": 0.0, "steel": 0.0, "masonry": 0.0, "formwork": 0.0, "earthwork": 0.0}

    def add(group: str, item: str, spec: str, unit: str, qty: float, rate: float, source: str) -> None:
        quantity = _r(qty, volume_dp if unit == "m3" else (area_dp if unit == "m2" else settings.mass_dp))
        if quantity <= 0.0:
            return
        amount = _r(quantity * float(rate), money)
        lines.append(
            BOQItem(
                sl=len(lines) + 1,
                item=item,
                spec=spec,
                unit=unit,
                qty=quantity,
                rate=_r(rate, money),
                amount=amount,
                rate_source=source,
            )
        )
        subtotals[group] = subtotals.get(group, 0.0) + amount

    for row in takeoff.concrete:
        if row.volume_m3 <= 0.0:
            continue
        rate, source = _concrete_rate(schedule, row.grade)
        add("concrete", "Concrete", row.grade + " in " + row.element_class, "m3", row.volume_m3, rate, source)

    schedule_bbs = takeoff.bbs if bbs is None else bbs
    steel_kg = 0.0 if schedule_bbs is None else float(schedule_bbs.total_with_wastage_kg)
    if steel_kg > 0.0:
        grade = takeoff.steel_grade or settings.default_steel_grade
        rate = schedule.lookup("steel_kg", grade)
        source = schedule.source_of("steel_kg." + grade)
        if rate is None:
            known = schedule.keys_of("steel_kg")
            if known:
                rate = schedule.lookup("steel_kg", known[0]) or 0.0
                source = schedule.name + " (" + known[0] + " substituted for " + grade + ")"
            else:
                rate, source = (0.0, "unrated")
        add(
            "steel",
            "Reinforcement",
            grade + " bars, cut and bent, including " + ("%.1f" % schedule_bbs.wastage_pct) + " percent wastage",
            "kg",
            steel_kg,
            rate,
            source,
        )

    for row in takeoff.masonry:
        if row.volume_m3 <= 0.0:
            continue
        rate, source = _masonry_rate(schedule, row.thickness_mm)
        add(
            "masonry",
            "Masonry",
            str(int(row.thickness_mm)) + " mm " + ("bearing" if row.bearing else "non-bearing") + " wall",
            "m3",
            row.volume_m3,
            rate,
            source,
        )

    for row in takeoff.formwork:
        if row.area_m2 <= 0.0:
            continue
        rate, source = _formwork_rate(schedule, row.element_class)
        add("formwork", "Formwork", "shuttering to " + row.element_class, "m2", row.area_m2, rate, source)

    earth = takeoff.earthwork
    for group, label, quantity in (
        ("excavation_m3", "Earthwork in excavation", earth.excavation_m3),
        ("pcc_m3", "Plain cement concrete bedding", earth.pcc_m3),
        ("backfill_m3", "Backfilling in layers", earth.backfill_m3),
        ("disposal_m3", "Disposal of surplus spoil", earth.disposal_m3),
    ):
        if quantity <= 0.0:
            continue
        rate, source = _flat_rate(schedule, group)
        if source == "unrated" and group == "disposal_m3":
            continue
        add("earthwork", label, "foundations", "m3", quantity, rate, source)

    total = _r(sum(line.amount for line in lines), money)
    area = float(takeoff.builtup_area_m2)
    densities = {
        "steel": steel_kg / area if area > 0.0 else 0.0,
        "concrete": takeoff.concrete_m3 / area if area > 0.0 else 0.0,
        "masonry": takeoff.masonry_m3 / area if area > 0.0 else 0.0,
    }
    system, label, choices = _resolve_bands(takeoff.system, settings)

    # The verdict block is built before anything is disclosed, so the payload
    # says what was checked even where no ladder entry could be raised.
    checks = {}  # type: Dict[str, Any]
    findings = []  # type: List[Tuple[str, str]]
    for check in DENSITY_BAND_CHECKS:
        choice = choices[check]
        meta = _BAND_CHECK_META[check]
        code = str(meta["disclosure_code"])
        registered = code in REGISTRY
        value = densities[check]
        if choice.band is None:
            status = "not_checked"
        elif area <= 0.0:
            status = "no_area"
        else:
            low, high = choice.band
            tol = _BAND_TOL[check]
            status = "inside" if (low - tol <= value <= high + tol) else "outside"
        message = (
            _band_message(check, value, choice.band, label)
            if (status == "outside" and choice.band is not None)
            else ""
        )
        if status == "outside" and registered:
            findings.append((code, message))
        checks[check] = {
            "metric": str(meta["metric"]),
            "value": _r(value, 3 if check == "steel" else 4),
            "band": None if choice.band is None else [_r(choice.band[0], 6), _r(choice.band[1], 6)],
            "band_source": choice.source,
            "status": status,
            "disclosure_code": code,
            "disclosure_code_registered": bool(registered),
            "disclosed": bool(status == "outside" and registered),
            "message": message,
        }

    stated = [_band_text(check, choices[check].band) for check in DENSITY_BAND_CHECKS if choices[check].band]
    density_basis = (
        (
            "densities are per square metre of built-up area; the calibration bands are "
            + _join_clauses(stated)
            + ", a heuristic for "
            + label
            + " that catches take-off bugs and absurd designs, not a code limit"
        )
        if stated
        else (
            "densities are per square metre of built-up area; no calibration band is tabulated for "
            + label
            + ", so no density is judged here"
        )
    )

    boq = BOQ(
        schedule=schedule.name,
        currency=schedule.currency,
        placeholder_rates=bool(schedule.placeholder),
        items=lines,
        subtotals=subtotals,
        total=total,
        builtup_area_m2=area,
        cost_per_m2=(total / area if area > 0.0 else 0.0),
        steel_kg_per_m2=densities["steel"],
        concrete_m3_per_m2=densities["concrete"],
        masonry_m3_per_m2=densities["masonry"],
        system=system,
        system_label=label,
        density_basis=density_basis,
        density_checks=checks,
        disclosures=log,
        options=settings,
    )

    if schedule.placeholder:
        log.add(
            "W_PLACEHOLDER_RATES",
            "schedule " + schedule.name + " is marked PLACEHOLDER in data/rates.yaml, so every amount here is "
            "indicative only and must not be used as a tender estimate",
            stage=_STAGE,
        )
    # Report order, not discovery order: the ladder is stable run to run.
    for code, message in findings:
        log.add(code, message, stage=_STAGE)
    return boq
