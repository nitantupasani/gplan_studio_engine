"""Canonical StructuralModel: the one data structure every structural submodule reads.

Unit and frame regime (normative):
  - internal storage is SI, metres, floats; forces kN, moments kNm, loads kPa,
    stresses MPa. Section dimensions are stored in metres and reported in mm.
  - the plan frame is y-DOWN, origin top-left, north = -y; storey 0 = ground,
    z is metres up from ground finished floor level.
  - to_dict() emits the wire shape: plan geometry in FEET with _ft suffixes,
    sections in mm, engineering SI. Every numeric wire key carries a unit suffix.

Enums subclass str, so `model.system == "rc_frame"` compares True without
unwrapping. Disclosure codes are API: every code lives in REGISTRY, once.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .schema import STRUCTURAL_SCHEMA_VERSION, units_block

FT = 0.3048
SQFT = FT * FT

XY = Tuple[float, float]

# Geometry comparison tolerance in metres (1 mm); the model is not a CAD kernel.
GEOM_TOL_M = 1e-3


def ft_to_m(value_ft: float) -> float:
    """Feet to metres."""
    return float(value_ft) * FT


def m_to_ft(value_m: float) -> float:
    """Metres to feet."""
    return float(value_m) / FT


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------


class System(str, Enum):
    """Structural system; frozen wire vocabulary (finding 26)."""

    RC_FRAME = "rc_frame"
    LOAD_BEARING_MASONRY = "load_bearing_masonry"
    CONFINED_MASONRY = "confined_masonry"
    MIXED = "mixed"


class Material(str, Enum):
    RC = "rc"
    BRICK_MASONRY = "brick_masonry"
    STEEL = "steel"
    TIMBER = "timber"


class Occupancy(str, Enum):
    HABITABLE = "habitable"
    KITCHEN = "kitchen"
    BATH = "bath"
    WC = "wc"
    BALCONY = "balcony"
    CORRIDOR = "corridor"
    STAIR = "stair"
    LIFT = "lift"
    UTILITY = "utility"
    PARKING = "parking"
    STORAGE = "storage"
    LOBBY = "lobby"
    GREEN = "green"
    VOID = "void"
    OTHER = "other"


class WallRole(str, Enum):
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    PARTY = "party"
    CORE = "core"
    PARAPET = "parapet"
    RAILING = "railing"


class Severity(str, Enum):
    """Disclosure ladder: error blocks, warning ships labeled, note informs."""

    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


SEVERITY_ORDER = MappingProxyType({Severity.ERROR: 0, Severity.WARNING: 1, Severity.NOTE: 2})


class ModelSource(str, Enum):
    PLAN_JSON = "plan_json"
    BUILDING = "building"
    HOUSING = "housing"


class StoreyKind(str, Enum):
    UNITS = "units"
    STILT = "stilt"
    ROOF = "roof"


class AxisDir(str, Enum):
    X = "x"
    Y = "y"


class AxisSource(str, Enum):
    """Grid axis provenance; `wall` replaced placement-frame's `unit` (finding 12)."""

    OUTLINE = "outline"
    CORRIDOR = "corridor"
    PARTY = "party"
    WALL = "wall"
    CORE = "core"
    INSERTED = "inserted"


class OpeningKind(str, Enum):
    DOOR = "door"
    WINDOW = "window"
    OPENING = "opening"
    ENTRY = "entry"


class Provenance(str, Enum):
    DRESSED = "dressed"
    ASSUMED_MID_WALL = "assumed_mid_wall"
    ENTRY_POINT = "entry_point"
    ADJACENCY_HINT = "adjacency_hint"


class CoreKind(str, Enum):
    STAIRS = "stairs"
    LIFT = "lift"
    UTILITY_SHAFT = "utility_shaft"
    FIRE_EXIT = "fire_exit"


class BeamKind(str, Enum):
    """Frozen superset (finding 11); bands stay Band elements, not beam roles."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    PLINTH = "plinth"
    TIE = "tie"
    TRIMMER = "trimmer"
    CANTILEVER = "cantilever"
    SPANDREL = "spandrel"
    LANDING = "landing"
    LINTEL = "lintel"


class SlabKind(str, Enum):
    FLOOR = "floor"
    ROOF = "roof"
    LANDING = "landing"


class BandKind(str, Enum):
    PLINTH = "plinth"
    LINTEL = "lintel"
    ROOF = "roof"
    GABLE = "gable"


class FootingKind(str, Enum):
    ISOLATED = "isolated"
    COMBINED = "combined"
    STRIP = "strip"
    STRAP = "strap"


# ---------------------------------------------------------------------------
# disclosure ladder
# ---------------------------------------------------------------------------

REGISTRY = MappingProxyType(
    {
        # errors: the condition blocks the element or the whole system
        "E_BAD_ENVELOPE": (Severity.ERROR, "input payload shape is unrecognized or self-inconsistent"),
        "E_EMPTY_PLAN": (Severity.ERROR, "no rooms or no geometry in the payload"),
        "E_NOT_RECTANGULAR": (Severity.ERROR, "room rectangle disagrees with its stated width or height"),
        "E_ROOM_OVERLAP": (Severity.ERROR, "two rooms overlap in plan"),
        "E_PLAN_NOT_GAPLESS": (Severity.ERROR, "plan contains voids; door_connectivity gapless plans only"),
        "E_BOUNDARY_NOT_RECTILINEAR": (Severity.ERROR, "boundary polygon has a non axis-aligned edge"),
        "E_BAD_ROTATION": (Severity.ERROR, "unit rotation is not 0, 90, 180 or 270"),
        "E_UNSUPPORTED_STOREYS": (Severity.ERROR, "storey count outside the supported range"),
        "E_CORE_MISMATCH": (Severity.ERROR, "core footprint differs between storeys"),
        "E_STACK_DISCONTINUOUS": (Severity.ERROR, "a built storey has no storey below it"),
        "E_TRANSFER_REQUIRED": (Severity.ERROR, "a floating column would be required; transfer structure not auto-placed"),
        "E_CANTILEVER_SPAN": (Severity.ERROR, "cantilever exceeds the refusal span"),
        "E_FRAMING_DEPTH": (Severity.ERROR, "required framing depth cannot be accommodated"),
        "E_GRID_COARSE": (Severity.ERROR, "no admissible grid found within the span caps"),
        "E_SPAN_OVER_MAX": (Severity.ERROR, "span exceeds the maximum and cannot be subdivided"),
        "E_MERGE_FLOOR": (Severity.ERROR, "footing merge would exceed the plan area available"),
        "E_ANA_CONSERVATION": (Severity.ERROR, "load takedown fails the conservation check"),
        "E_MASONRY_LIMIT": (Severity.ERROR, "masonry storeys or height exceed the code category cap"),
        "E_NO_BEARING_DIRECTION": (Severity.ERROR, "no bearing wall line exists in one direction"),
        # warnings: the result ships, labeled
        "W_DOOR_ASSUMED": (Severity.WARNING, "doors were synthesized mid-wall; the plan carried none"),
        "W_DOOR_UNMAPPED": (Severity.WARNING, "a dressed door could not be mapped to a wall line"),
        "W_ADJACENCY_SHORTFALL": (Severity.WARNING, "room pair shares too little wall for a door; none assumed"),
        "W_OCCUPANCY_UNKNOWN": (Severity.WARNING, "room name did not map to a known occupancy"),
        "W_UNIT_NO_PLAN": (Severity.WARNING, "unit has no interior plan; partition allowance used"),
        "W_TYPICAL_REPEATED": (Severity.WARNING, "a typical floor was repeated to fill the storey count"),
        "W_UNIT_OUTSIDE_BOUNDARY": (Severity.WARNING, "a unit protrudes past the building boundary"),
        "W_CORE_UNIT_OVERLAP": (Severity.WARNING, "a core footprint overlaps a unit footprint"),
        "W_STALE_GENERATED": (Severity.WARNING, "generated plan does not match its region; uniformly rescaled"),
        "W_REGION_CONTENT_UNMATCHED": (Severity.WARNING, "region content could not be matched to a derived face"),
        "W_NO_STAIR": (Severity.WARNING, "multi-storey stack has no stair core"),
        "W_CLIENT_GRID_DIFFERS": (Severity.WARNING, "client structural grid differs from the engine grid"),
        "W_SHORT_SPAN": (Severity.WARNING, "span below the minimum target band"),
        "W_SLID": (Severity.WARNING, "an axis was slid off its wall centreline to satisfy a cap"),
        "W_TERTIARY": (Severity.WARNING, "tertiary beams were inserted to break a long panel"),
        "W_CANTILEVER": (Severity.WARNING, "cantilever placed within the allowed span"),
        "W_BACKSPAN": (Severity.WARNING, "cantilever backspan is shorter than recommended"),
        "W_TALL": (Severity.WARNING, "storey count above the thumb-rule validity range; engineer review required"),
        "W_TORSION": (Severity.WARNING, "stiffness centroid offset from the area centroid beyond tolerance"),
        "W_IRREG": (Severity.WARNING, "plan or vertical irregularity detected"),
        "W_THICK_SLAB": (Severity.WARNING, "slab thickness above the thumb range for the panel"),
        "W_COARSE_ITER": (Severity.WARNING, "iteration stopped at the coarse limit before convergence"),
        "W_COLUMN_IN_DOOR": (Severity.WARNING, "a column lands inside a door opening"),
        "W_ASSUMED_OPENINGS": (Severity.WARNING, "openings were assumed for the code opening checks"),
        "W_ASSUMED_SBC": (Severity.WARNING, "default safe bearing capacity assumed"),
        "W_ASSUMED_FOUNDING_DEPTH": (Severity.WARNING, "default founding depth assumed"),
        "W_RELEASED_CAP": (Severity.WARNING, "a placement cap was relaxed to produce output"),
        "W_STEEL_DENSITY_BAND": (Severity.WARNING, "steel per built-up area outside the expected band"),
        "W_CONCRETE_DENSITY_BAND": (Severity.WARNING, "concrete per built-up area outside the expected band"),
        "W_PLACEHOLDER_RATES": (Severity.WARNING, "cost uses placeholder rates"),
        "W_ECCENTRIC_COLUMN": (Severity.WARNING, "column offset from the wall centreline beyond tolerance"),
        "W_FOOTING_OVERLAP": (Severity.WARNING, "two footings overlap in plan and share bearing soil"),
        "W_LOAD_OCCUPANCY_FALLBACK": (Severity.WARNING, "occupancy had no code live load; fallback used"),
        "W_LIVE_LOAD_OVERRIDDEN": (Severity.WARNING, "a request value replaced the code imposed load"),
        "W_ANA_COEFF_INAPPLICABLE": (Severity.WARNING, "coefficient method not applicable; alternative used"),
        "W_EQ_TORSION_IRREGULAR": (Severity.WARNING, "torsionally irregular; the governing design eccentricity applied"),
        "W_EQ_DRIFT": (Severity.WARNING, "storey drift exceeds the code limit"),
        "W_INFILL_EXCLUDED": (Severity.WARNING, "non-bearing walls not credited with lateral stiffness"),
        "W_WIND_STATIC_LIMIT": (Severity.WARNING, "static wind method at the edge of its validity"),
        "W_WIND_UPLIFT": (Severity.WARNING, "net wind uplift governs a roof or footing"),
        # notes: informational simplifications
        "N_INFILL_STRUT": (Severity.NOTE, "infill credited as equivalent diagonal struts by option"),
        "N_LAP_50D_FLAT": (Severity.NOTE, "laps taken flat at 50d where a bar carries no ld"),
        "N_BBS_SHAPE_CODES_DEFERRED": (Severity.NOTE, "bar shape codes are not emitted in this version"),
        "N_NO_BEND_DEDUCTION": (Severity.NOTE, "bend deductions are not applied to cut lengths"),
        "N_FORMWORK_EDGES_IGNORED": (Severity.NOTE, "formwork edge strips are not measured"),
        "N_WASTAGE_3PCT": (Severity.NOTE, "3 percent steel wastage included"),
        "N_SLOPE_ALLOWANCE_FLAT": (Severity.NOTE, "no slope allowance; roof measured flat"),
        "N_PARTITION_M3_CONVENTION": (Severity.NOTE, "partition volume measured by the stated convention"),
        "N_COLUMN_HEIGHT_CONVENTION": (Severity.NOTE, "column height measured floor to floor, slab not deducted"),
        "N_WINDOWS_NOT_ASSUMED": (Severity.NOTE, "no windows assumed; window lintels omitted"),
        "N_SHAFT_WALL_UNDESIGNED": (Severity.NOTE, "shaft walls carry a prescription, not a design"),
        "N_ELEMENT_UNDESIGNED": (Severity.NOTE, "placed and quantified, but no designer reached it"),
        "N_PLAIN_CONCRETE_FOOTING": (
            Severity.NOTE,
            "footing adequate as plain concrete; no reinforcement is required",
        ),
    }
)


@dataclass
class Disclosure:
    """One ladder entry. Codes are API: producer, report, response and frontend share them."""

    code: str
    severity: Severity
    message: str
    element_ids: List[str] = field(default_factory=list)
    clause: Optional[str] = None
    stage: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": _enum_value(self.severity),
            "message": self.message,
            "element_ids": list(self.element_ids),
            "clause": self.clause,
            "stage": self.stage,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Disclosure":
        return Disclosure(
            code=d["code"],
            severity=Severity(d.get("severity", "warning")),
            message=d.get("message", ""),
            element_ids=list(d.get("element_ids") or []),
            clause=d.get("clause"),
            stage=d.get("stage", ""),
        )


@dataclass
class DisclosureLog:
    """Shared sink. One (code, message) pair appears once, element_ids merged.

    The dedupe key is the code AND the message, not the code alone. One code
    covers a CONDITION, and several producers can hit the same condition on
    different elements: those merge, which is what the ladder is for. But two
    genuinely different conditions can also share a code (the registry is a
    fixed vocabulary, deliberately coarser than English), and merging those on
    the code alone silently dropped the later text. Keying on the message keeps
    both entries, in producer order.
    """

    entries: List[Disclosure] = field(default_factory=list)

    def append(self, entry: Disclosure) -> Disclosure:
        """Add an entry, merging only into an existing entry saying the same thing."""
        for existing in self.entries:
            if existing.code == entry.code and existing.message == entry.message:
                merged = sorted(set(existing.element_ids) | set(entry.element_ids))
                existing.element_ids = merged
                if not existing.clause and entry.clause:
                    existing.clause = entry.clause
                return existing
        self.entries.append(entry)
        return entry

    def extend(self, entries: Iterable[Disclosure]) -> None:
        for entry in entries:
            self.append(entry)

    def add(self, code: str, message: str, element_ids: Sequence[str] = (), clause: Optional[str] = None, stage: str = "") -> Disclosure:
        """Registry-checked convenience constructor."""
        return self.append(make_disclosure(code, message, element_ids, clause=clause, stage=stage))

    def counts(self) -> Dict[str, int]:
        out = {Severity.ERROR.value: 0, Severity.WARNING.value: 0, Severity.NOTE.value: 0}
        for entry in self.entries:
            out[_enum_value(entry.severity)] += 1
        return out

    def codes(self) -> List[str]:
        return sorted({entry.code for entry in self.entries})

    def sorted_entries(self) -> List[Disclosure]:
        """Severity first, then producer order (stable)."""
        indexed = list(enumerate(self.entries))
        indexed.sort(key=lambda pair: (SEVERITY_ORDER.get(Severity(pair[1].severity), 3), pair[0]))
        return [entry for _, entry in indexed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "disclosures": [entry.to_dict() for entry in self.sorted_entries()],
            "counts": self.counts(),
        }


def make_disclosure(code: str, message: str, element_ids: Sequence[str] = (), clause: Optional[str] = None, stage: str = "") -> Disclosure:
    """Build a Disclosure, taking its severity from REGISTRY. Unknown codes raise."""
    if code not in REGISTRY:
        raise ValueError("unregistered disclosure code: " + str(code))
    severity = REGISTRY[code][0]
    return Disclosure(
        code=code,
        severity=severity,
        message=message,
        element_ids=list(element_ids),
        clause=clause,
        stage=stage,
    )


def add_disclosure(model: "StructuralModel", code: str, message: str, element_ids: Sequence[str] = (), clause: Optional[str] = None, stage: str = "") -> Disclosure:
    """Append a registry-checked Disclosure to a model's ladder."""
    entry = make_disclosure(code, message, element_ids, clause=clause, stage=stage)
    model.warnings.append(entry)
    return entry


def registry_severity(code: str) -> Severity:
    """Severity of a registered code; raises on an unknown code."""
    if code not in REGISTRY:
        raise ValueError("unregistered disclosure code: " + str(code))
    return REGISTRY[code][0]


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


# ---------------------------------------------------------------------------
# element ids: derived from geometry, never from insertion order
# ---------------------------------------------------------------------------


def fmt(value_ft: float) -> str:
    """Position token: feet at 2 dp with trailing zeros trimmed. fmt(12.5) == '12.5'."""
    rounded = round(float(value_ft), 2) + 0.0
    text = "{0:.2f}".format(rounded)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    return text


def pos_token(value_m: float) -> str:
    """Position token from a metre value (ids speak feet)."""
    return fmt(m_to_ft(value_m))


def _id_token(value: Any) -> str:
    """Source ids enter ids verbatim, with whitespace collapsed to underscores."""
    return "_".join(str(value).split())


def axis_id(direction: Any, label: str) -> str:
    """gx-1 / gy-A."""
    return "g" + _enum_value(direction) + "-" + _id_token(label)


def stack_id(x_label: Optional[str] = None, y_label: Optional[str] = None, *, x_m: Optional[float] = None, y_m: Optional[float] = None) -> str:
    """stk-<xlabel>-<ylabel> on grid, stk-@<xft>x<yft> off grid."""
    if x_label is not None and y_label is not None:
        return "stk-" + _id_token(x_label) + "-" + _id_token(y_label)
    if x_m is None or y_m is None:
        raise ValueError("stack_id needs either grid labels or x_m and y_m")
    return "stk-@" + pos_token(x_m) + "x" + pos_token(y_m)


def column_id(storey: int, x_label: Optional[str] = None, y_label: Optional[str] = None, *, x_m: Optional[float] = None, y_m: Optional[float] = None) -> str:
    """col-<xlabel>-<ylabel>-s<n> on grid, col-@<xft>x<yft>-s<n> off grid."""
    if x_label is not None and y_label is not None:
        head = "col-" + _id_token(x_label) + "-" + _id_token(y_label)
    else:
        if x_m is None or y_m is None:
            raise ValueError("column_id needs either grid labels or x_m and y_m")
        head = "col-@" + pos_token(x_m) + "x" + pos_token(y_m)
    return head + "-s" + str(int(storey))


def beam_id(storey: int, axis: Any, line_label: str, index: int, plinth: bool = False) -> str:
    """beam-s<n>-<axis><lineLabel>-<i>; plinth beams sit on the storey 0 datum as pbeam-."""
    prefix = "pbeam-" if plinth else "beam-"
    return prefix + "s" + str(int(storey)) + "-" + _enum_value(axis) + _id_token(line_label) + "-" + str(int(index))


def wall_id(storey: int, orient: str, pos_m: float, start_m: float) -> str:
    """wall-s<n>-<h|v>-<posft>-<startft> (centreline position, then segment start)."""
    return "wall-s" + str(int(storey)) + "-" + orient + "-" + pos_token(pos_m) + "-" + pos_token(start_m)


def opening_id(wall_element_id: str, index: int) -> str:
    """<wallid>-op<i>, i ordered by increasing offset along the wall."""
    return wall_element_id + "-op" + str(int(index))


def room_id(storey: int, source_id: Any) -> str:
    """room-s<n>-<sourceid>."""
    return "room-s" + str(int(storey)) + "-" + _id_token(source_id)


def slab_id(storey: int, index: int) -> str:
    """slab-s<n>-<i>, i by sorted panel origin."""
    return "slab-s" + str(int(storey)) + "-" + str(int(index))


def band_id(kind: Any, storey: int) -> str:
    """band-<kind>-s<n>."""
    return "band-" + _enum_value(kind) + "-s" + str(int(storey))


def lintel_id(wall_element_id: str, index: int) -> str:
    """lin-<wallid>-op<i>."""
    return "lin-" + wall_element_id + "-op" + str(int(index))


def footing_id(stack_element_id: str) -> str:
    """ftg-<stackid>."""
    return "ftg-" + stack_element_id


def strip_footing_id(wall_element_id: str) -> str:
    """ftg-strip-<wallid>."""
    return "ftg-strip-" + wall_element_id


def core_id(source_id: Any) -> str:
    """core-<sourceid>; cores keep the id they arrived with."""
    return "core-" + _id_token(source_id)


def wall_stack_id(bottom_wall_id: str) -> str:
    """wstk-<lowest wall id in the stack>."""
    return "wstk-" + bottom_wall_id


# ---------------------------------------------------------------------------
# containers (SI metres; y-down plan frame)
# ---------------------------------------------------------------------------


@dataclass
class Storey:
    index: int
    name: str
    bottom_z_m: float
    height_m: float
    kind: StoreyKind = StoreyKind.UNITS
    source_id: Optional[str] = None


@dataclass
class GridAxis:
    id: str
    dir: AxisDir
    pos_m: float
    label: str
    source: AxisSource = AxisSource.INSERTED
    storeys: List[int] = field(default_factory=list)


@dataclass
class Opening:
    id: str
    kind: OpeningKind
    offset_m: float
    width_m: float
    sill_m: Optional[float] = None
    head_m: Optional[float] = None
    provenance: Provenance = Provenance.ASSUMED_MID_WALL


@dataclass
class WallLine:
    """Axis-aligned centreline; room_ids are (left, right) by the wall normal, None outside."""

    id: str
    storey: int
    a: XY
    b: XY
    thickness_m: float
    role: WallRole = WallRole.INTERIOR
    material: Material = Material.BRICK_MASONRY
    bearing: Optional[bool] = None
    openings: List[Opening] = field(default_factory=list)
    room_ids: Tuple[Optional[str], Optional[str]] = (None, None)
    source: Optional[str] = None

    def length_m(self) -> float:
        dx = self.b[0] - self.a[0]
        dy = self.b[1] - self.a[1]
        return (dx * dx + dy * dy) ** 0.5


@dataclass
class RoomPoly:
    """Rectilinear loop, no closing vertex, y-down positive shoelace."""

    id: str
    storey: int
    name: str
    occupancy: Occupancy
    polygon: List[XY]
    area_m2: float
    unit_id: Optional[str] = None
    interior_unknown: bool = False
    source: Optional[str] = None


@dataclass
class Core:
    id: str
    kind: CoreKind
    x_m: float
    y_m: float
    w_m: float
    h_m: float
    storeys: List[int] = field(default_factory=list)
    stair_landing_hint: Optional[str] = None


@dataclass
class Column:
    id: str
    stack_id: str
    storey: int
    x_m: float
    y_m: float
    width_m: float
    depth_m: float
    rot: int = 0
    on_grid: Optional[Tuple[str, str]] = None
    placed_by: str = ""
    code_refs: List[str] = field(default_factory=list)


@dataclass
class Beam:
    id: str
    storey: int
    a: XY
    b: XY
    width_m: float
    depth_m: Optional[float] = None
    kind: BeamKind = BeamKind.PRIMARY
    supports_wall_id: Optional[str] = None
    placed_by: str = ""
    code_refs: List[str] = field(default_factory=list)

    def span_m(self) -> float:
        dx = self.b[0] - self.a[0]
        dy = self.b[1] - self.a[1]
        return (dx * dx + dy * dy) ** 0.5


@dataclass
class SlabPanel:
    id: str
    storey: int
    polygon: List[XY]
    thickness_m: Optional[float] = None
    two_way: Optional[bool] = None
    lx_m: float = 0.0
    ly_m: float = 0.0
    edge_continuity: Dict[str, str] = field(default_factory=dict)
    kind: SlabKind = SlabKind.FLOOR
    support_ids: List[str] = field(default_factory=list)
    placed_by: str = ""


@dataclass
class Band:
    id: str
    kind: BandKind
    storey: int
    wall_ids: List[str] = field(default_factory=list)
    level_m: float = 0.0
    placed_by: str = ""


@dataclass
class Lintel:
    id: str
    wall_id: str
    opening_id: str
    span_m: float
    placed_by: str = ""


@dataclass
class Footing:
    id: str
    kind: FootingKind
    supports: List[str] = field(default_factory=list)
    x_m: float = 0.0
    y_m: float = 0.0
    w_m: Optional[float] = None
    h_m: Optional[float] = None
    depth_m: Optional[float] = None
    placed_by: str = ""
    # A boundary footing the placer flushed inside the line: the load acts
    # `e_m` off the footing centre and the designer must be told, so the flag
    # survives the model hand-off instead of dying inside the placement plan.
    eccentric: bool = False
    e_m: float = 0.0


# ---------------------------------------------------------------------------
# wire conversion helpers (SI metres <-> feet / mm on the wire)
# ---------------------------------------------------------------------------

_GEOM_DP = 4


def _ft(value_m: float) -> float:
    return round(m_to_ft(value_m), _GEOM_DP) + 0.0


def _ft_opt(value_m: Optional[float]) -> Optional[float]:
    return None if value_m is None else _ft(value_m)


def _mm(value_m: float) -> int:
    return int(round(float(value_m) * 1000.0))


def _mm_opt(value_m: Optional[float]) -> Optional[int]:
    return None if value_m is None else _mm(value_m)


def _sqft(area_m2: float) -> float:
    return round(float(area_m2) / SQFT, _GEOM_DP) + 0.0


def _pt_ft(point: Sequence[float]) -> List[float]:
    return [_ft(point[0]), _ft(point[1])]


def _poly_ft(polygon: Sequence[Sequence[float]]) -> List[List[float]]:
    return [_pt_ft(p) for p in polygon]


def _m_opt(value_ft: Optional[float]) -> Optional[float]:
    return None if value_ft is None else ft_to_m(value_ft)


def _from_mm(value_mm: float) -> float:
    return float(value_mm) / 1000.0


def _from_mm_opt(value_mm: Optional[float]) -> Optional[float]:
    return None if value_mm is None else _from_mm(value_mm)


def _pt_m(point: Sequence[float]) -> XY:
    return (ft_to_m(point[0]), ft_to_m(point[1]))


def _poly_m(polygon: Sequence[Sequence[float]]) -> List[XY]:
    return [_pt_m(p) for p in polygon]


def _pair(value: Any) -> Optional[Tuple[Any, Any]]:
    if value is None:
        return None
    return (value[0], value[1])


def _storey_to_wire(s: Storey) -> Dict[str, Any]:
    return {
        "index": int(s.index),
        "name": s.name,
        "bottom_z_ft": _ft(s.bottom_z_m),
        "height_ft": _ft(s.height_m),
        "kind": _enum_value(s.kind),
        "source_id": s.source_id,
    }


def _storey_from_wire(d: Dict[str, Any]) -> Storey:
    return Storey(
        index=int(d["index"]),
        name=d.get("name", ""),
        bottom_z_m=ft_to_m(d.get("bottom_z_ft", 0.0)),
        height_m=ft_to_m(d.get("height_ft", 0.0)),
        kind=StoreyKind(d.get("kind", "units")),
        source_id=d.get("source_id"),
    )


def _axis_to_wire(a: GridAxis) -> Dict[str, Any]:
    return {
        "id": a.id,
        "dir": _enum_value(a.dir),
        "pos_ft": _ft(a.pos_m),
        "label": a.label,
        "source": _enum_value(a.source),
        "storeys": [int(v) for v in a.storeys],
    }


def _axis_from_wire(d: Dict[str, Any], direction: str) -> GridAxis:
    return GridAxis(
        id=d["id"],
        dir=AxisDir(d.get("dir", direction)),
        pos_m=ft_to_m(d.get("pos_ft", 0.0)),
        label=d.get("label", ""),
        source=AxisSource(d.get("source", "inserted")),
        storeys=[int(v) for v in (d.get("storeys") or [])],
    )


def _opening_to_wire(o: Opening) -> Dict[str, Any]:
    return {
        "id": o.id,
        "kind": _enum_value(o.kind),
        "offset_ft": _ft(o.offset_m),
        "width_ft": _ft(o.width_m),
        "sill_ft": _ft_opt(o.sill_m),
        "head_ft": _ft_opt(o.head_m),
        "provenance": _enum_value(o.provenance),
    }


def _opening_from_wire(d: Dict[str, Any]) -> Opening:
    return Opening(
        id=d["id"],
        kind=OpeningKind(d.get("kind", "door")),
        offset_m=ft_to_m(d.get("offset_ft", 0.0)),
        width_m=ft_to_m(d.get("width_ft", 0.0)),
        sill_m=_m_opt(d.get("sill_ft")),
        head_m=_m_opt(d.get("head_ft")),
        provenance=Provenance(d.get("provenance", "assumed_mid_wall")),
    )


def _wall_to_wire(w: WallLine) -> Dict[str, Any]:
    return {
        "id": w.id,
        "storey": int(w.storey),
        "a_ft": _pt_ft(w.a),
        "b_ft": _pt_ft(w.b),
        "thickness_ft": _ft(w.thickness_m),
        "role": _enum_value(w.role),
        "material": _enum_value(w.material),
        "bearing": w.bearing,
        "openings": [_opening_to_wire(o) for o in w.openings],
        "room_ids": [w.room_ids[0], w.room_ids[1]],
        "source": w.source,
    }


def _wall_from_wire(d: Dict[str, Any]) -> WallLine:
    return WallLine(
        id=d["id"],
        storey=int(d.get("storey", 0)),
        a=_pt_m(d["a_ft"]),
        b=_pt_m(d["b_ft"]),
        thickness_m=ft_to_m(d.get("thickness_ft", 0.0)),
        role=WallRole(d.get("role", "interior")),
        material=Material(d.get("material", "brick_masonry")),
        bearing=d.get("bearing"),
        openings=[_opening_from_wire(o) for o in (d.get("openings") or [])],
        room_ids=_pair(d.get("room_ids")) or (None, None),
        source=d.get("source"),
    )


def _room_to_wire(r: RoomPoly) -> Dict[str, Any]:
    return {
        "id": r.id,
        "storey": int(r.storey),
        "name": r.name,
        "occupancy": _enum_value(r.occupancy),
        "polygon_ft": _poly_ft(r.polygon),
        "area_sqft": _sqft(r.area_m2),
        "unit_id": r.unit_id,
        "interior_unknown": bool(r.interior_unknown),
        "source": r.source,
    }


def _room_from_wire(d: Dict[str, Any]) -> RoomPoly:
    return RoomPoly(
        id=d["id"],
        storey=int(d.get("storey", 0)),
        name=d.get("name", ""),
        occupancy=Occupancy(d.get("occupancy", "other")),
        polygon=_poly_m(d.get("polygon_ft") or []),
        area_m2=float(d.get("area_sqft", 0.0)) * SQFT,
        unit_id=d.get("unit_id"),
        interior_unknown=bool(d.get("interior_unknown", False)),
        source=d.get("source"),
    )


def _core_to_wire(c: Core) -> Dict[str, Any]:
    return {
        "id": c.id,
        "kind": _enum_value(c.kind),
        "x_ft": _ft(c.x_m),
        "y_ft": _ft(c.y_m),
        "w_ft": _ft(c.w_m),
        "h_ft": _ft(c.h_m),
        "storeys": [int(v) for v in c.storeys],
        "stair_landing_hint": c.stair_landing_hint,
    }


def _core_from_wire(d: Dict[str, Any]) -> Core:
    return Core(
        id=d["id"],
        kind=CoreKind(d.get("kind", "stairs")),
        x_m=ft_to_m(d.get("x_ft", 0.0)),
        y_m=ft_to_m(d.get("y_ft", 0.0)),
        w_m=ft_to_m(d.get("w_ft", 0.0)),
        h_m=ft_to_m(d.get("h_ft", 0.0)),
        storeys=[int(v) for v in (d.get("storeys") or [])],
        stair_landing_hint=d.get("stair_landing_hint"),
    )


def _column_to_wire(c: Column) -> Dict[str, Any]:
    # a_ft/b_ft are plan positions; b_mm/d_mm are the section (finding 5).
    return {
        "id": c.id,
        "stack_id": c.stack_id,
        "storey": int(c.storey),
        "x_ft": _ft(c.x_m),
        "y_ft": _ft(c.y_m),
        "b_mm": _mm(c.width_m),
        "d_mm": _mm(c.depth_m),
        "rot": int(c.rot),
        "on_grid": None if c.on_grid is None else [c.on_grid[0], c.on_grid[1]],
        "placed_by": c.placed_by,
        "code_refs": list(c.code_refs),
    }


def _column_from_wire(d: Dict[str, Any]) -> Column:
    return Column(
        id=d["id"],
        stack_id=d.get("stack_id", ""),
        storey=int(d.get("storey", 0)),
        x_m=ft_to_m(d.get("x_ft", 0.0)),
        y_m=ft_to_m(d.get("y_ft", 0.0)),
        width_m=_from_mm(d.get("b_mm", 0)),
        depth_m=_from_mm(d.get("d_mm", 0)),
        rot=int(d.get("rot", 0)),
        on_grid=_pair(d.get("on_grid")),
        placed_by=d.get("placed_by", ""),
        code_refs=list(d.get("code_refs") or []),
    )


def _beam_to_wire(b: Beam) -> Dict[str, Any]:
    return {
        "id": b.id,
        "storey": int(b.storey),
        "a_ft": _pt_ft(b.a),
        "b_ft": _pt_ft(b.b),
        "b_mm": _mm(b.width_m),
        "d_mm": _mm_opt(b.depth_m),
        "kind": _enum_value(b.kind),
        "supports_wall_id": b.supports_wall_id,
        "placed_by": b.placed_by,
        "code_refs": list(b.code_refs),
    }


def _beam_from_wire(d: Dict[str, Any]) -> Beam:
    return Beam(
        id=d["id"],
        storey=int(d.get("storey", 0)),
        a=_pt_m(d["a_ft"]),
        b=_pt_m(d["b_ft"]),
        width_m=_from_mm(d.get("b_mm", 0)),
        depth_m=_from_mm_opt(d.get("d_mm")),
        kind=BeamKind(d.get("kind", "primary")),
        supports_wall_id=d.get("supports_wall_id"),
        placed_by=d.get("placed_by", ""),
        code_refs=list(d.get("code_refs") or []),
    )


def _slab_to_wire(s: SlabPanel) -> Dict[str, Any]:
    return {
        "id": s.id,
        "storey": int(s.storey),
        "polygon_ft": _poly_ft(s.polygon),
        "thickness_mm": _mm_opt(s.thickness_m),
        "two_way": s.two_way,
        "lx_ft": _ft(s.lx_m),
        "ly_ft": _ft(s.ly_m),
        "edge_continuity": dict(s.edge_continuity),
        "kind": _enum_value(s.kind),
        "support_ids": list(s.support_ids),
        "placed_by": s.placed_by,
    }


def _slab_from_wire(d: Dict[str, Any]) -> SlabPanel:
    return SlabPanel(
        id=d["id"],
        storey=int(d.get("storey", 0)),
        polygon=_poly_m(d.get("polygon_ft") or []),
        thickness_m=_from_mm_opt(d.get("thickness_mm")),
        two_way=d.get("two_way"),
        lx_m=ft_to_m(d.get("lx_ft", 0.0)),
        ly_m=ft_to_m(d.get("ly_ft", 0.0)),
        edge_continuity=dict(d.get("edge_continuity") or {}),
        kind=SlabKind(d.get("kind", "floor")),
        support_ids=list(d.get("support_ids") or []),
        placed_by=d.get("placed_by", ""),
    )


def _band_to_wire(b: Band) -> Dict[str, Any]:
    return {
        "id": b.id,
        "kind": _enum_value(b.kind),
        "storey": int(b.storey),
        "wall_ids": list(b.wall_ids),
        "level_ft": _ft(b.level_m),
        "placed_by": b.placed_by,
    }


def _band_from_wire(d: Dict[str, Any]) -> Band:
    return Band(
        id=d["id"],
        kind=BandKind(d.get("kind", "lintel")),
        storey=int(d.get("storey", 0)),
        wall_ids=list(d.get("wall_ids") or []),
        level_m=ft_to_m(d.get("level_ft", 0.0)),
        placed_by=d.get("placed_by", ""),
    )


def _lintel_to_wire(lin: Lintel) -> Dict[str, Any]:
    return {
        "id": lin.id,
        "wall_id": lin.wall_id,
        "opening_id": lin.opening_id,
        "span_ft": _ft(lin.span_m),
        "placed_by": lin.placed_by,
    }


def _lintel_from_wire(d: Dict[str, Any]) -> Lintel:
    return Lintel(
        id=d["id"],
        wall_id=d.get("wall_id", ""),
        opening_id=d.get("opening_id", ""),
        span_m=ft_to_m(d.get("span_ft", 0.0)),
        placed_by=d.get("placed_by", ""),
    )


def _footing_to_wire(f: Footing) -> Dict[str, Any]:
    return {
        "id": f.id,
        "kind": _enum_value(f.kind),
        "supports": list(f.supports),
        "x_ft": _ft(f.x_m),
        "y_ft": _ft(f.y_m),
        "w_ft": _ft_opt(f.w_m),
        "h_ft": _ft_opt(f.h_m),
        "depth_ft": _ft_opt(f.depth_m),
        "placed_by": f.placed_by,
        "eccentric": bool(f.eccentric),
        "e_ft": _ft(f.e_m),
    }


def _footing_from_wire(d: Dict[str, Any]) -> Footing:
    return Footing(
        id=d["id"],
        kind=FootingKind(d.get("kind", "isolated")),
        supports=list(d.get("supports") or []),
        x_m=ft_to_m(d.get("x_ft", 0.0)),
        y_m=ft_to_m(d.get("y_ft", 0.0)),
        w_m=_m_opt(d.get("w_ft")),
        h_m=_m_opt(d.get("h_ft")),
        depth_m=_m_opt(d.get("depth_ft")),
        placed_by=d.get("placed_by", ""),
        eccentric=bool(d.get("eccentric", False)),
        e_m=ft_to_m(d.get("e_ft", 0.0) or 0.0),
    )


# ---------------------------------------------------------------------------
# geometry helpers shared with placement (finding 9)
# ---------------------------------------------------------------------------


def wall_axis(wall: WallLine) -> Optional[Tuple[str, float, float, float]]:
    """('h'|'v', centreline position, span start, span end) in metres; None if skew."""
    ax, ay = wall.a
    bx, by = wall.b
    horizontal = abs(ay - by) <= GEOM_TOL_M
    vertical = abs(ax - bx) <= GEOM_TOL_M
    if horizontal and not vertical:
        return ("h", 0.5 * (ay + by), min(ax, bx), max(ax, bx))
    if vertical and not horizontal:
        return ("v", 0.5 * (ax + bx), min(ay, by), max(ay, by))
    return None


def opening_span(wall: WallLine, opening: Opening) -> Tuple[float, float]:
    """Arc-length span (s0_m, s1_m) of an opening measured from wall endpoint a."""
    half = 0.5 * float(opening.width_m)
    centre = float(opening.offset_m)
    return (centre - half, centre + half)


def opening_assumed(opening: Opening) -> bool:
    """True unless the opening came from a dressed plan."""
    return _enum_value(opening.provenance) != Provenance.DRESSED.value


def polygon_rect(polygon: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    """Bounding rect (x, y, w, h) in metres of a plan polygon."""
    xs = [float(p[0]) for p in polygon]
    ys = [float(p[1]) for p in polygon]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _is_rectilinear(polygon: Sequence[Sequence[float]]) -> bool:
    if len(polygon) < 4:
        return False
    count = len(polygon)
    for i in range(count):
        ax, ay = polygon[i][0], polygon[i][1]
        bx, by = polygon[(i + 1) % count][0], polygon[(i + 1) % count][1]
        flat_x = abs(bx - ax) <= GEOM_TOL_M
        flat_y = abs(by - ay) <= GEOM_TOL_M
        if flat_x == flat_y:
            return False
    return True


def _rects_overlap(a: Core, b: Core) -> bool:
    dx = min(a.x_m + a.w_m, b.x_m + b.w_m) - max(a.x_m, b.x_m)
    dy = min(a.y_m + a.h_m, b.y_m + b.h_m) - max(a.y_m, b.y_m)
    return dx > GEOM_TOL_M and dy > GEOM_TOL_M


def _same_rect(a: Core, b: Core) -> bool:
    return (
        abs(a.x_m - b.x_m) <= GEOM_TOL_M
        and abs(a.y_m - b.y_m) <= GEOM_TOL_M
        and abs(a.w_m - b.w_m) <= GEOM_TOL_M
        and abs(a.h_m - b.h_m) <= GEOM_TOL_M
    )


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

# id-bearing slots, in the order elements() walks them (storeys carry no id)
_ELEMENT_SLOTS = (
    "axes",
    "walls",
    "rooms",
    "cores",
    "columns",
    "beams",
    "slabs",
    "bands",
    "lintels",
    "footings",
)


@dataclass
class StructuralModel:
    """The single structure adapters write and every other submodule reads.

    `loads`, `seismic` and `analysis` carry the loads module's serialized output
    verbatim, `design` the design module's DesignResult dicts; this model owns
    their transport, never their shape (finding 14, finding 6).
    """

    schema_version: str = STRUCTURAL_SCHEMA_VERSION
    id: str = ""
    source: ModelSource = ModelSource.PLAN_JSON
    system: System = System.RC_FRAME
    fingerprint: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    storeys: List[Storey] = field(default_factory=list)
    axes: List[GridAxis] = field(default_factory=list)
    walls: List[WallLine] = field(default_factory=list)
    rooms: List[RoomPoly] = field(default_factory=list)
    cores: List[Core] = field(default_factory=list)
    columns: List[Column] = field(default_factory=list)
    beams: List[Beam] = field(default_factory=list)
    slabs: List[SlabPanel] = field(default_factory=list)
    bands: List[Band] = field(default_factory=list)
    lintels: List[Lintel] = field(default_factory=list)
    footings: List[Footing] = field(default_factory=list)
    loads: Dict[str, Any] = field(default_factory=dict)
    seismic: Optional[Dict[str, Any]] = None
    analysis: Dict[str, Any] = field(default_factory=dict)
    design: List[Dict[str, Any]] = field(default_factory=list)
    quantities: Optional[Dict[str, Any]] = None
    warnings: List[Disclosure] = field(default_factory=list)

    # -- disclosure ---------------------------------------------------------

    def add_warning(self, code: str, message: str, element_ids: Sequence[str] = (), severity: Optional[Severity] = None, clause: Optional[str] = None, stage: str = "") -> Disclosure:
        """Append a registry-checked Disclosure; severity always comes from REGISTRY."""
        registered = registry_severity(code)
        if severity is not None and Severity(severity) != registered:
            raise ValueError(
                "severity for " + code + " is " + registered.value + " in REGISTRY, not " + str(_enum_value(severity))
            )
        return add_disclosure(self, code, message, element_ids, clause=clause, stage=stage)

    def disclosure_log(self) -> DisclosureLog:
        """A deduped log view of this model's ladder."""
        log = DisclosureLog()
        log.extend(self.warnings)
        return log

    # -- lookup -------------------------------------------------------------

    def elements(self) -> List[Any]:
        """Every element carrying an id, in a fixed slot order (openings included)."""
        out = []  # type: List[Any]
        for slot in _ELEMENT_SLOTS:
            for element in getattr(self, slot):
                out.append(element)
                if slot == "walls":
                    out.extend(element.openings)
        return out

    def by_id(self, element_id: str) -> Optional[Any]:
        """The element with this id, or None."""
        for element in self.elements():
            if getattr(element, "id", None) == element_id:
                return element
        return None

    def storey(self, index: int) -> Optional[Storey]:
        for s in self.storeys:
            if s.index == index:
                return s
        return None

    def walls_on(self, storey: int) -> List[WallLine]:
        return [w for w in self.walls if w.storey == storey]

    def columns_on(self, storey: int) -> List[Column]:
        return [c for c in self.columns if c.storey == storey]

    def rooms_on(self, storey: int) -> List[RoomPoly]:
        return [r for r in self.rooms if r.storey == storey]

    def beams_on(self, storey: int) -> List[Beam]:
        return [b for b in self.beams if b.storey == storey]

    def slabs_on(self, storey: int) -> List[SlabPanel]:
        return [s for s in self.slabs if s.storey == storey]

    def cores_on(self, storey: int) -> List[Core]:
        return [c for c in self.cores if storey in c.storeys]

    # -- derived helpers (finding 9) ---------------------------------------

    def _occupancy_rects(self, occupancy: Occupancy, storey: Optional[int]) -> List[Tuple[float, float, float, float]]:
        rects = []
        for room in self.rooms:
            if storey is not None and room.storey != storey:
                continue
            if _enum_value(room.occupancy) != occupancy.value:
                continue
            rects.append(polygon_rect(room.polygon))
        return sorted(rects)

    def corridor_rects(self, storey: Optional[int] = None) -> List[Tuple[float, float, float, float]]:
        """Corridor RoomPolys as (x, y, w, h) metre rects, sorted."""
        return self._occupancy_rects(Occupancy.CORRIDOR, storey)

    def balcony_rects(self, storey: Optional[int] = None) -> List[Tuple[float, float, float, float]]:
        """Balcony RoomPolys as (x, y, w, h) metre rects, sorted."""
        return self._occupancy_rects(Occupancy.BALCONY, storey)

    def doors_known(self, storey: Optional[int] = None) -> bool:
        """True when any opening on the storey came from a dressed plan."""
        for wall in self.walls:
            if storey is not None and wall.storey != storey:
                continue
            for opening in wall.openings:
                if not opening_assumed(opening):
                    return True
        return False

    @staticmethod
    def opening_span(wall: WallLine, opening: Opening) -> Tuple[float, float]:
        """(s0_m, s1_m) along the wall from endpoint a."""
        return opening_span(wall, opening)

    @staticmethod
    def opening_assumed(opening: Opening) -> bool:
        """True unless provenance is 'dressed'."""
        return opening_assumed(opening)

    def build_wall_stacks(self) -> List[Dict[str, Any]]:
        """Group walls across storeys whose centrelines align within t/2 of the lower wall.

        Returns [{stack_id, walls: {storey: wall_id}, grounded, max_offset_m}], sorted
        by stack_id. Deterministic: storeys ascending, walls by id, nearest centreline wins.
        """
        open_stacks = []  # type: List[Dict[str, Any]]
        for storey in sorted({w.storey for w in self.walls}):
            for wall in sorted(self.walls_on(storey), key=lambda w: w.id):
                axis = wall_axis(wall)
                if axis is None:
                    continue
                orient, pos, s0, s1 = axis
                best = None
                best_offset = None
                for stack in open_stacks:
                    top = stack["_top"]
                    if top["storey"] != storey - 1 or top["orient"] != orient:
                        continue
                    overlap = min(s1, top["s1"]) - max(s0, top["s0"])
                    if overlap <= GEOM_TOL_M:
                        continue
                    offset = abs(pos - top["pos"])
                    if offset > 0.5 * top["thickness_m"] + GEOM_TOL_M:
                        continue
                    if best_offset is None or offset < best_offset - 1e-12 or (
                        abs(offset - best_offset) <= 1e-12 and stack["stack_id"] < best["stack_id"]
                    ):
                        best = stack
                        best_offset = offset
                top_record = {
                    "storey": storey,
                    "orient": orient,
                    "pos": pos,
                    "s0": s0,
                    "s1": s1,
                    "thickness_m": wall.thickness_m,
                }
                if best is None:
                    open_stacks.append(
                        {
                            "stack_id": wall_stack_id(wall.id),
                            "walls": {storey: wall.id},
                            "grounded": storey == 0,
                            "max_offset_m": 0.0,
                            "_top": top_record,
                        }
                    )
                else:
                    best["walls"][storey] = wall.id
                    best["max_offset_m"] = max(best["max_offset_m"], best_offset)
                    best["_top"] = top_record
        stacks = []
        for stack in sorted(open_stacks, key=lambda s: s["stack_id"]):
            stacks.append(
                {
                    "stack_id": stack["stack_id"],
                    "walls": dict(sorted(stack["walls"].items())),
                    "grounded": stack["grounded"],
                    "max_offset_m": round(stack["max_offset_m"], 6),
                }
            )
        return stacks

    # -- invariants ---------------------------------------------------------

    def validate(self) -> List[Disclosure]:
        """Model invariants as ERROR Disclosures. Never raises: api.py discloses these."""
        log = DisclosureLog()
        stage = "model.validate"

        indices = [s.index for s in self.storeys]
        if not indices:
            log.add("E_UNSUPPORTED_STOREYS", "model has no storeys", (), stage=stage)
        elif sorted(indices) != list(range(len(indices))):
            log.add(
                "E_STACK_DISCONTINUOUS",
                "storey indices must be contiguous from 0, got " + repr(sorted(indices)),
                (),
                stage=stage,
            )

        seen = set()
        duplicates = set()
        for element in self.elements():
            eid = getattr(element, "id", None)
            if eid in seen:
                duplicates.add(eid)
            seen.add(eid)
        if duplicates:
            log.add(
                "E_BAD_ENVELOPE",
                "duplicate element ids: " + ", ".join(sorted(duplicates)),
                sorted(duplicates),
                stage=stage,
            )

        skew = [w.id for w in self.walls if wall_axis(w) is None]
        if skew:
            log.add(
                "E_NOT_RECTANGULAR",
                "wall centrelines must be axis aligned: " + ", ".join(sorted(skew)),
                sorted(skew),
                stage=stage,
            )

        crooked = [r.id for r in self.rooms if not _is_rectilinear(r.polygon)]
        crooked += [s.id for s in self.slabs if not _is_rectilinear(s.polygon)]
        if crooked:
            log.add(
                "E_NOT_RECTANGULAR",
                "polygon is not a rectilinear loop: " + ", ".join(sorted(crooked)),
                sorted(crooked),
                stage=stage,
            )

        cores = sorted(self.cores, key=lambda c: c.id)
        mismatched = set()
        for i, first in enumerate(cores):
            for second in cores[i + 1:]:
                if _enum_value(first.kind) != _enum_value(second.kind):
                    continue
                if set(first.storeys) & set(second.storeys):
                    continue
                if not _rects_overlap(first, second):
                    continue
                if not _same_rect(first, second):
                    mismatched.add(first.id)
                    mismatched.add(second.id)
        if mismatched:
            log.add(
                "E_CORE_MISMATCH",
                "core footprint differs between storeys: " + ", ".join(sorted(mismatched)),
                sorted(mismatched),
                stage=stage,
            )

        declared = set(indices)
        off_storey = sorted(
            e.id
            for e in self.elements()
            if getattr(e, "storey", None) is not None and e.storey not in declared
        )
        if off_storey:
            log.add(
                "E_BAD_ENVELOPE",
                "elements sit on undeclared storeys: " + ", ".join(off_storey),
                off_storey,
                stage=stage,
            )

        known = {getattr(e, "id", None) for e in self.elements()}
        dangling = {}
        for wall in self.walls:
            for rid in wall.room_ids:
                if rid and rid not in known:
                    dangling.setdefault(rid, set()).add(wall.id)
        for beam in self.beams:
            if beam.supports_wall_id and beam.supports_wall_id not in known:
                dangling.setdefault(beam.supports_wall_id, set()).add(beam.id)
        for lin in self.lintels:
            for ref in (lin.wall_id, lin.opening_id):
                if ref and ref not in known:
                    dangling.setdefault(ref, set()).add(lin.id)
        for band in self.bands:
            for ref in band.wall_ids:
                if ref and ref not in known:
                    dangling.setdefault(ref, set()).add(band.id)
        for slab in self.slabs:
            for ref in slab.support_ids:
                if ref and ref not in known:
                    dangling.setdefault(ref, set()).add(slab.id)
        for footing in self.footings:
            for ref in footing.supports:
                if ref and ref not in known:
                    dangling.setdefault(ref, set()).add(footing.id)
        if dangling:
            holders = sorted({h for hs in dangling.values() for h in hs})
            log.add(
                "E_BAD_ENVELOPE",
                "unresolved references: " + ", ".join(sorted(dangling)),
                holders,
                stage=stage,
            )

        return log.sorted_entries()

    # -- wire ---------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """The wire shape: feet geometry, mm sections, SI engineering, unit-suffixed keys."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "source": _enum_value(self.source),
            "system": _enum_value(self.system),
            "fingerprint": self.fingerprint,
            "units": units_block(),
            "meta": copy.deepcopy(self.meta),
            "storeys": [_storey_to_wire(s) for s in self.storeys],
            "axes": {
                "x": [_axis_to_wire(a) for a in self.axes if _enum_value(a.dir) == "x"],
                "y": [_axis_to_wire(a) for a in self.axes if _enum_value(a.dir) == "y"],
            },
            "walls": [_wall_to_wire(w) for w in self.walls],
            "rooms": [_room_to_wire(r) for r in self.rooms],
            "cores": [_core_to_wire(c) for c in self.cores],
            "columns": [_column_to_wire(c) for c in self.columns],
            "beams": [_beam_to_wire(b) for b in self.beams],
            "slabs": [_slab_to_wire(s) for s in self.slabs],
            "bands": [_band_to_wire(b) for b in self.bands],
            "lintels": [_lintel_to_wire(lin) for lin in self.lintels],
            "footings": [_footing_to_wire(f) for f in self.footings],
            "loads": copy.deepcopy(self.loads),
            "seismic": copy.deepcopy(self.seismic),
            "analysis": copy.deepcopy(self.analysis),
            "design": copy.deepcopy(self.design),
            "quantities": copy.deepcopy(self.quantities),
            "warnings": [w.to_dict() for w in self.warnings],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StructuralModel":
        """Parse the wire shape back to SI. Unknown top-level keys land in meta['extra']."""
        axes_wire = d.get("axes") or {}
        axes = [_axis_from_wire(a, "x") for a in (axes_wire.get("x") or [])]
        axes += [_axis_from_wire(a, "y") for a in (axes_wire.get("y") or [])]

        meta = copy.deepcopy(d.get("meta") or {})
        extra = {k: copy.deepcopy(v) for k, v in sorted(d.items()) if k not in _WIRE_KEYS}
        if extra:
            merged = dict(meta.get("extra") or {})
            merged.update(extra)
            meta["extra"] = merged

        return StructuralModel(
            schema_version=d.get("schema_version", STRUCTURAL_SCHEMA_VERSION),
            id=d.get("id", ""),
            source=ModelSource(d.get("source", "plan_json")),
            system=System(d.get("system", "rc_frame")),
            fingerprint=d.get("fingerprint", ""),
            meta=meta,
            storeys=[_storey_from_wire(s) for s in (d.get("storeys") or [])],
            axes=axes,
            walls=[_wall_from_wire(w) for w in (d.get("walls") or [])],
            rooms=[_room_from_wire(r) for r in (d.get("rooms") or [])],
            cores=[_core_from_wire(c) for c in (d.get("cores") or [])],
            columns=[_column_from_wire(c) for c in (d.get("columns") or [])],
            beams=[_beam_from_wire(b) for b in (d.get("beams") or [])],
            slabs=[_slab_from_wire(s) for s in (d.get("slabs") or [])],
            bands=[_band_from_wire(b) for b in (d.get("bands") or [])],
            lintels=[_lintel_from_wire(lin) for lin in (d.get("lintels") or [])],
            footings=[_footing_from_wire(f) for f in (d.get("footings") or [])],
            loads=copy.deepcopy(d.get("loads") or {}),
            seismic=copy.deepcopy(d.get("seismic")),
            analysis=copy.deepcopy(d.get("analysis") or {}),
            design=copy.deepcopy(d.get("design") or []),
            quantities=copy.deepcopy(d.get("quantities")),
            warnings=[Disclosure.from_dict(w) for w in (d.get("warnings") or [])],
        )


_WIRE_KEYS = frozenset(
    [
        "schema_version",
        "id",
        "source",
        "system",
        "fingerprint",
        "units",
        "meta",
        "storeys",
        "axes",
        "walls",
        "rooms",
        "cores",
        "columns",
        "beams",
        "slabs",
        "bands",
        "lintels",
        "footings",
        "loads",
        "seismic",
        "analysis",
        "design",
        "quantities",
        "warnings",
    ]
)
