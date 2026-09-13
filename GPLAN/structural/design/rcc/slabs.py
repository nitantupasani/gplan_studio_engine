"""Slab design: two-way panels, one-way strips, cantilevers and stair flights.

Spec 05 section 5 plus the stair mode critic finding 40 assigns here. Two public
entry points, both returning the one `design/common.py` DesignResult:

    design_slab(panel, load, ctx)          # a floor or roof panel
    design_stair_flight(stair, load, ctx)  # one inclined flight from cores.py

**Units.** The SI model (metres, kPa) is converted once on entry and once on
exit; inside, everything is N, mm, MPa. Every design is done on a ONE METRE
STRIP, which makes the entry conversion pleasantly exact: a pressure of w kPa
on a 1 m strip is a line load of w N/mm, because 1 kN/m2 x 1 m = 1 kN/m =
1000 N / 1000 mm = 1 N/mm. `_line_load_n_per_mm` writes that out rather than
asserting it.

**Direction vocabulary.** lx is the SHORTER span, ly the longer, exactly as
Annex D writes them. The two panel sides of length ly are the LONG EDGES: they
are the supports at the ends of the short span, so they carry the Table 26
alpha_x_neg moment. The two sides of length lx are the SHORT EDGES and carry
alpha_y_neg. Table 26 case 6 ("two long edges discontinuous", alpha_x_neg all
dashes) and case 5 ("two short edges discontinuous", alpha_y_neg a dash) are
the two entries that pin this reading, and `table26_case` is a total map from
(long edges discontinuous, short edges discontinuous) onto the nine cases.

**Layering.** The short-span bars sit outermost, where the lever arm is worth
most, so d_x is the full depth to the outer layer and d_y sits one bar in:
d_y = d_x - (dia_x + dia_y) / 2, which is d_x - dia when the two mesh sizes are
equal (the form the spec states).

**Bar roles.** `mesh_x_bottom` and `mesh_y_bottom` are the sagging meshes in the
Annex D directions; a support mesh names the panel side it sits over, as in
`mesh_x_top_y_min` (the short-span mesh over the y_min side). The side tags are
plan-frame, the direction letters are Annex D, and `extras["edges"]` says which
sides are the long pair and which the short, so a reader never has to guess.

**Where the clause callables come from.** Everything is read through the traced
callables in `codes/is456.py`, with one exception the data file itself names:
Table 12 has no callable there (`data/is456_tables.yaml` records "no clause
callable in is456.py reads it yet; slabs.py is its consumer"), and the traced
`table12_alpha` in `analysis/takedown.py` already reads exactly that block, so
this module calls it rather than transcribing the table a second time.

**Disclose, never hide.** Nothing here raises on a slab that cannot pass. The
Cl 22.5.1 applicability guard on the Table 12 coefficients does not refuse the
coefficients: it uses them and attaches W_ANA_COEFF_INAPPLICABLE. When the
deflection check is still unsatisfied at the 150 mm cap the panel is NOT
thickened further (finding 40): the design stops at 150, the failing span/d row
stays on the result so the number is visible, the status is `resized`, and a
`add_secondary_beams` referral carries the suggested spacing range so wave 5
can hand the panel back to placement for its one bounded re-place pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ...analysis import SlabLoad
from ...analysis.takedown import table12_alpha
from ...codes import is456
from ...codes.trace import TraceEntry, trace_into
from ...model import RC_SLAB_MIN_THICKNESS_MM, make_disclosure
from ..common import (
    CHECK_FAIL,
    STATUS_RESIZED,
    Concrete,
    DesignResult,
    RebarSteel,
    ResizePolicy,
    area_for_spacing,
    check_exposure_grade,
    materials_block,
    resolve_cover,
    round_up_mm,
    spacing_for_area,
)

__all__ = [
    "MESH_DIAS_MM",
    "MIN_MESH_SPACING_MM",
    "SPACING_MODULE_MM",
    "STRIP_MM",
    "SUPPORT_BAND_FRACTION",
    "SECONDARY_BEAM_SPACING_M",
    "STAIR_WAIST_SPAN_RATIO",
    "STAIR_WAIST_MIN_MM",
    "STAIR_WAIST_CAP_RATIO",
    "CONCRETE_DENSITY_KNM3",
    "DEAD_LOAD_FACTOR",
    "SlabContext",
    "slab_context",
    "PanelGeometry",
    "panel_geometry",
    "table26_case",
    "design_slab",
    "design_stair_flight",
]

_STAGE = "design.rcc.slabs"

#: Mesh diameters a slab may be detailed with, ascending. The catalogue in
#: data/rebar.yaml carries larger bars; a slab mesh never uses them.
MESH_DIAS_MM = (8, 10, 12, 16)

#: Practical placing floor on a mesh pitch, mm. Below it the diameter is bumped
#: instead of the spacing being squeezed (spec 05 section 5.3).
MIN_MESH_SPACING_MM = 100.0

#: Mesh pitches are detailed on a 10 mm module, rounded DOWN so the provided
#: area never falls below the required area.
SPACING_MODULE_MM = 10.0

#: Every slab is designed as a one metre strip.
STRIP_MM = 1000.0

#: Annex D-1.6: half the support steel runs 0.3 l from the support face; the
#: v1 detailing runs all of it that far, which is the conservative reading.
SUPPORT_BAND_FRACTION = 0.3

#: Spacing range the add_secondary_beams referral suggests to placement, m.
SECONDARY_BEAM_SPACING_M = (2.5, 3.5)

#: Waist of a stair flight, span over this (finding 40).
STAIR_WAIST_SPAN_RATIO = 20.0

#: Project minimum RC slab/waist thickness, mm. Stair flights use the same
#: floor as ordinary panels; their span-based rule may still require more.
STAIR_WAIST_MIN_MM = RC_SLAB_MIN_THICKNESS_MM

#: A flight may thicken to span over this before the design gives up. A stair
#: cannot be handed secondary beams, so it has its own cap rather than the
#: 150 mm panel cap. Design-layer constant, not a code value.
STAIR_WAIST_CAP_RATIO = 12.0

#: Density of reinforced concrete, kN/m3 (IS 875-1 Table 1).
CONCRETE_DENSITY_KNM3 = 25.0

#: Partial safety factor on the dead load the stair designer adds for the waist
#: it has just chosen, IS 456 Table 18 combination 1.
DEAD_LOAD_FACTOR = 1.5

_EPS = 1e-9

#: Table 26 case number keyed by (long edges discontinuous, short edges
#: discontinuous). Total over the nine cases: every (0..2, 0..2) pair is here.
_T26_CASE_BY_MASK = {
    (0, 0): 1,  # interior
    (0, 1): 2,  # one short edge discontinuous
    (1, 0): 3,  # one long edge discontinuous
    (1, 1): 4,  # two adjacent edges discontinuous
    (0, 2): 5,  # two short edges discontinuous
    (2, 0): 6,  # two long edges discontinuous
    (1, 2): 7,  # three edges discontinuous, one long edge continuous
    (2, 1): 8,  # three edges discontinuous, one short edge continuous
    (2, 2): 9,  # four edges discontinuous
}

#: The four sides of a panel's bounding rectangle, in the order every loop here
#: walks them, so a result dict is reproducible.
SIDE_TAGS = ("x_min", "x_max", "y_min", "y_max")

#: The four corners, each naming the two sides that meet there.
CORNER_SIDES = (
    ("x_min_y_min", ("x_min", "y_min")),
    ("x_min_y_max", ("x_min", "y_max")),
    ("x_max_y_min", ("x_max", "y_min")),
    ("x_max_y_max", ("x_max", "y_max")),
)


# ---------------------------------------------------------------------------
# context: whatever the orchestrator hands over, read the same way
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlabContext:
    """Materials and policy for one slab design.

    The designers are called with whatever the orchestrator carries, so
    `slab_context` accepts this dataclass, a plain options mapping, or any
    object with these attribute names, and fills the rest with the defaults the
    spec's options schema states. `imposed_kpa` and `dead_kpa` are optional: the
    SlabLoad contract carries only the combined pressures, and the two Cl 22.5.1
    and Cl 24.1 Note legs that need the split say so when they cannot see it.
    """

    fck_mpa: float = 25.0
    fy_mpa: float = 500.0
    exposure: str = "moderate"
    fire_rating_h: float = 0.0
    aggregate_mm: float = 20.0
    imposed_kpa: Optional[float] = None
    dead_kpa: Optional[float] = None
    continuous_spans: Optional[int] = None
    span_variation_pct: Optional[float] = None
    corners_held_down: bool = False
    stair_self_weight_included: bool = False
    riser_mm: Optional[float] = None
    policy: ResizePolicy = field(default_factory=ResizePolicy)

    def concrete(self) -> Concrete:
        return Concrete(fck_mpa=float(self.fck_mpa))

    def steel(self) -> RebarSteel:
        return RebarSteel(fy_mpa=float(self.fy_mpa))


_CTX_ALIASES = {
    "fck_mpa": ("fck_mpa", "fck"),
    "fy_mpa": ("fy_mpa", "fy"),
    "exposure": ("exposure",),
    "fire_rating_h": ("fire_rating_h", "fire_rating", "fire"),
    "aggregate_mm": ("aggregate_mm", "agg_mm", "aggregate"),
    "imposed_kpa": ("imposed_kpa", "ll_kpa", "live_kpa"),
    "dead_kpa": ("dead_kpa", "dl_kpa"),
    "continuous_spans": ("continuous_spans", "spans"),
    "span_variation_pct": ("span_variation_pct",),
    "corners_held_down": ("corners_held_down",),
    "stair_self_weight_included": ("stair_self_weight_included",),
    "riser_mm": ("riser_mm",),
}


def _lookup(source: Any, names: Sequence[str]) -> Any:
    """First of `names` present on a mapping or an object, else None."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        materials = source.get("materials")
        if isinstance(materials, Mapping):
            for name in names:
                if name in materials and materials[name] is not None:
                    return materials[name]
        return None
    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def slab_context(ctx: Any = None) -> SlabContext:
    """A SlabContext from a SlabContext, an options mapping, an object or None."""
    if isinstance(ctx, SlabContext):
        return ctx
    base = SlabContext()
    values = {}  # type: Dict[str, Any]
    for field_name, names in sorted(_CTX_ALIASES.items()):
        found = _lookup(ctx, names)
        values[field_name] = getattr(base, field_name) if found is None else found
    policy = _lookup(ctx, ("policy", "resize_policy"))
    if isinstance(policy, Mapping):
        policy = ResizePolicy.from_dict(policy)
    elif not isinstance(policy, ResizePolicy):
        policy = base.policy
    return SlabContext(
        fck_mpa=float(values["fck_mpa"]),
        fy_mpa=float(values["fy_mpa"]),
        exposure=str(values["exposure"]),
        fire_rating_h=float(values["fire_rating_h"]),
        aggregate_mm=float(values["aggregate_mm"]),
        imposed_kpa=None if values["imposed_kpa"] is None else float(values["imposed_kpa"]),
        dead_kpa=None if values["dead_kpa"] is None else float(values["dead_kpa"]),
        continuous_spans=None if values["continuous_spans"] is None else int(values["continuous_spans"]),
        span_variation_pct=(
            None if values["span_variation_pct"] is None else float(values["span_variation_pct"])
        ),
        corners_held_down=bool(values["corners_held_down"]),
        stair_self_weight_included=bool(values["stair_self_weight_included"]),
        riser_mm=None if values["riser_mm"] is None else float(values["riser_mm"]),
        policy=policy,
    )


def _load_view(load: Any) -> SlabLoad:
    """A SlabLoad from a SlabLoad, a slab ForceEnvelope or a mapping."""
    if isinstance(load, SlabLoad):
        return load
    w_u = _lookup(load, ("w_u_kpa",))
    w_service = _lookup(load, ("w_service_kpa",))
    return SlabLoad(
        w_u_kpa=0.0 if w_u is None else float(w_u),
        w_service_kpa=0.0 if w_service is None else float(w_service),
    )


def _line_load_n_per_mm(w_kpa: float) -> float:
    """Line load on a one metre strip, N/mm, from a pressure in kPa.

    1 kN/m2 x 1000 mm = 1 kN/m = 1000 N / 1000 mm = 1 N/mm, so the number does
    not change; the arithmetic is written out because the identity is the whole
    reason the strip is a metre wide.
    """
    return float(w_kpa) * 1.0e-3 * STRIP_MM


# ---------------------------------------------------------------------------
# panel geometry: sides, continuity, the Table 26 case
# ---------------------------------------------------------------------------


class SideState(NamedTuple):
    """One side of the panel's bounding rectangle."""

    tag: str
    continuous: bool
    supported: bool
    length_mm: float


class PanelGeometry(NamedTuple):
    """Everything the design needs to know about the panel's shape and edges."""

    lx_mm: float
    ly_mm: float
    ratio: float
    short_axis: str  # "x" or "y": the axis the SHORT span runs along
    sides: Dict[str, SideState]
    long_side_tags: Tuple[str, str]  # supports at the ends of the short span
    short_side_tags: Tuple[str, str]
    long_cont: Tuple[bool, bool]
    short_cont: Tuple[bool, bool]
    supported_sides: int
    case: int
    notes: Tuple[str, ...]


def table26_case(long_discontinuous: int, short_discontinuous: int) -> int:
    """Annex D Table 26 case number for a continuity mask, 1 to 9.

    `long_discontinuous` counts the discontinuous edges of length ly (the
    supports at the ends of the short span, which carry alpha_x_neg) and
    `short_discontinuous` the discontinuous edges of length lx. The map is
    total: every pair in (0..2) x (0..2) is one of the nine printed cases.
    """
    key = (int(long_discontinuous), int(short_discontinuous))
    if key not in _T26_CASE_BY_MASK:
        raise ValueError("discontinuous edge counts must each be 0, 1 or 2, got " + repr(key))
    return _T26_CASE_BY_MASK[key]


def _continuity_entries(panel: Any) -> List[Tuple[int, str, bool]]:
    """(index, support word, continuous) per edge, in the placer's outline order.

    placement/frame.py writes `edge_continuity` as {"e0": "beam:cont", ...}; a
    bare "cont"/"disc" string or a bare bool is accepted too, so a hand-built
    panel in a test does not have to spell the support word.
    """
    raw = _lookup(panel, ("edge_continuity",))
    if not isinstance(raw, Mapping):
        return []
    out = []  # type: List[Tuple[int, str, bool]]
    for key in sorted(raw, key=lambda k: (len(str(k)), str(k))):
        text = raw[key]
        support = "beam"
        if isinstance(text, bool):
            continuous = bool(text)
        else:
            word = str(text).strip().lower()
            if ":" in word:
                support, _, word = word.partition(":")
                support = support.strip()
                word = word.strip()
            continuous = word in ("cont", "continuous", "true", "yes", "1")
        index = 0
        digits = "".join(ch for ch in str(key) if ch.isdigit())
        if digits:
            index = int(digits)
        out.append((index, support, continuous))
    out.sort(key=lambda item: item[0])
    return out


def _polygon_mm(panel: Any) -> List[Tuple[float, float]]:
    """The panel outline in mm, or an empty list when it carries none."""
    raw = _lookup(panel, ("polygon",))
    if not raw:
        return []
    points = []  # type: List[Tuple[float, float]]
    for point in raw:
        try:
            points.append((float(point[0]) * 1000.0, float(point[1]) * 1000.0))
        except (TypeError, IndexError, ValueError):
            return []
    return points


def _side_of_edge(
    a: Tuple[float, float],
    b: Tuple[float, float],
    x_lo: float,
    x_hi: float,
    y_lo: float,
    y_hi: float,
    tol_mm: float,
) -> Optional[str]:
    """Which side of the bounding rectangle an outline edge lies on, if any."""
    if abs(a[0] - b[0]) <= tol_mm:
        x = 0.5 * (a[0] + b[0])
        if abs(x - x_lo) <= tol_mm:
            return "x_min"
        if abs(x - x_hi) <= tol_mm:
            return "x_max"
        return None
    if abs(a[1] - b[1]) <= tol_mm:
        y = 0.5 * (a[1] + b[1])
        if abs(y - y_lo) <= tol_mm:
            return "y_min"
        if abs(y - y_hi) <= tol_mm:
            return "y_max"
        return None
    return None


def panel_geometry(panel: Any) -> PanelGeometry:
    """Spans, per-side continuity and support, and the Table 26 case.

    Each outline edge is assigned to a side of the panel's bounding rectangle;
    a side is continuous (or supported) when the length-weighted majority of the
    edges on it are, which is the rule placement/frame.py already uses for its
    own span-direction decision. A panel whose outline is not a rectangle keeps
    a note saying which edges could not be placed on a side.
    """
    notes = []  # type: List[str]
    lx = float(_lookup(panel, ("lx_m",)) or 0.0) * 1000.0
    ly = float(_lookup(panel, ("ly_m",)) or 0.0) * 1000.0
    polygon = _polygon_mm(panel)
    entries = _continuity_entries(panel)

    if polygon:
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        x_lo, x_hi, y_lo, y_hi = min(xs), max(xs), min(ys), max(ys)
    else:
        x_lo, y_lo = 0.0, 0.0
        x_hi, y_hi = (lx, ly)
    x_extent = max(x_hi - x_lo, 0.0)
    y_extent = max(y_hi - y_lo, 0.0)

    if lx <= 0.0 or ly <= 0.0:
        lx = min(x_extent, y_extent)
        ly = max(x_extent, y_extent)
        notes.append("panel carried no lx/ly; the bounding rectangle was used")
    if ly < lx:
        lx, ly = ly, lx
    short_axis = "x" if x_extent <= y_extent + _EPS else "y"

    tol = max(1.0, 0.02 * min(x_extent, y_extent) if min(x_extent, y_extent) > 0.0 else 1.0)
    tally = {tag: [0.0, 0.0, 0.0] for tag in SIDE_TAGS}  # tag -> [total, cont, supported]
    unassigned = 0
    if polygon and entries and len(entries) == len(polygon):
        for index, support, continuous in entries:
            a = polygon[index]
            b = polygon[(index + 1) % len(polygon)]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            tag = _side_of_edge(a, b, x_lo, x_hi, y_lo, y_hi, tol)
            if tag is None:
                unassigned += 1
                continue
            tally[tag][0] += length
            if continuous:
                tally[tag][1] += length
            if support != "free":
                tally[tag][2] += length
    else:
        # No usable outline: fall back to the placer's edge order, which walks
        # the rectangle, so e0/e2 are one opposed pair and e1/e3 the other.
        order = ("y_min", "x_max", "y_max", "x_min")
        for index, support, continuous in entries:
            tag = order[index % 4]
            length = x_extent if tag in ("y_min", "y_max") else y_extent
            length = length if length > 0.0 else 1.0
            tally[tag][0] += length
            if continuous:
                tally[tag][1] += length
            if support != "free":
                tally[tag][2] += length
        if entries:
            notes.append(
                "edge continuity read in the placer's edge order (e0 = y_min, e1 = x_max, "
                "e2 = y_max, e3 = x_min): the outline and the continuity mask could not be paired "
                "one edge to one entry"
            )

    if unassigned:
        notes.append(
            "panel outline is not a rectangle; "
            + str(unassigned)
            + " edge(s) could not be placed on a side and are read as discontinuous and unsupported"
        )

    sides = {}  # type: Dict[str, SideState]
    for tag in SIDE_TAGS:
        total, cont, supported = tally[tag]
        sides[tag] = SideState(
            tag=tag,
            continuous=total > 0.0 and cont * 2.0 >= total - _EPS,
            supported=total > 0.0 and supported * 2.0 >= total - _EPS,
            length_mm=y_extent if tag in ("x_min", "x_max") else x_extent,
        )

    if short_axis == "x":
        long_tags = ("x_min", "x_max")
        short_tags = ("y_min", "y_max")
    else:
        long_tags = ("y_min", "y_max")
        short_tags = ("x_min", "x_max")

    long_cont = (sides[long_tags[0]].continuous, sides[long_tags[1]].continuous)
    short_cont = (sides[short_tags[0]].continuous, sides[short_tags[1]].continuous)
    supported_sides = sum(1 for tag in SIDE_TAGS if sides[tag].supported)
    case = table26_case(2 - sum(1 for v in long_cont if v), 2 - sum(1 for v in short_cont if v))
    ratio = (ly / lx) if lx > 0.0 else 1.0

    return PanelGeometry(
        lx_mm=lx,
        ly_mm=ly,
        ratio=ratio,
        short_axis=short_axis,
        sides=sides,
        long_side_tags=long_tags,
        short_side_tags=short_tags,
        long_cont=long_cont,
        short_cont=short_cont,
        supported_sides=supported_sides,
        case=case,
        notes=tuple(notes),
    )


class _SpanRoute(NamedTuple):
    """Physical one-way span selected from the opposed supported edge pair."""

    axis: str
    span_mm: float
    across_mm: float
    support_tags: Tuple[str, str]
    continuity: Tuple[bool, bool]


class _CantileverRoute(NamedTuple):
    """Resolved root, projection and backing slab supplied by placement."""

    axis: str
    projection_mm: float
    across_mm: float
    backing_edge: str
    backing_support_ids: Tuple[str, ...]
    backing_panel_id: str
    backspan_mm: float


def _physical_extents(geo: PanelGeometry) -> Tuple[float, float]:
    """(x extent, y extent) of the measured design rectangle."""
    if geo.short_axis == "x":
        return (geo.lx_mm, geo.ly_mm)
    return (geo.ly_mm, geo.lx_mm)


def _ordinary_span_route(geo: PanelGeometry) -> Optional[_SpanRoute]:
    """One-way route from an actual opposed supported pair, never bbox lx alone."""
    x_extent, y_extent = _physical_extents(geo)
    # For an irregular outline, the support tally belongs to the outer bbox
    # while lx/ly belong to the largest inscribed rectangle.  Mixing those two
    # frames produced fictitious 20 m spans.  Keep the placer's measured short
    # rectangle route until an irregular-panel analysis can map every edge.
    if any("outline is not a rectangle" in note for note in geo.notes):
        return _SpanRoute(
            axis=geo.short_axis,
            span_mm=geo.lx_mm,
            across_mm=geo.ly_mm,
            support_tags=geo.long_side_tags,
            continuity=geo.long_cont,
        )
    candidates = {}  # type: Dict[str, _SpanRoute]
    x_tags = ("x_min", "x_max")
    y_tags = ("y_min", "y_max")
    if all(geo.sides[tag].supported for tag in x_tags):
        candidates["x"] = _SpanRoute(
            axis="x",
            span_mm=x_extent,
            across_mm=y_extent,
            support_tags=x_tags,
            continuity=tuple(geo.sides[tag].continuous for tag in x_tags),
        )
    if all(geo.sides[tag].supported for tag in y_tags):
        candidates["y"] = _SpanRoute(
            axis="y",
            span_mm=y_extent,
            across_mm=x_extent,
            support_tags=y_tags,
            continuity=tuple(geo.sides[tag].continuous for tag in y_tags),
        )
    if geo.short_axis in candidates:
        return candidates[geo.short_axis]
    if len(candidates) == 1:
        return candidates[sorted(candidates)[0]]
    return None


def _is_cantilever_panel(panel: Any) -> bool:
    """Explicit structural mode, with old placement provenance as a safe fallback."""
    span_kind = str(_lookup(panel, ("span_kind",)) or "regular").strip().lower()
    kind = _lookup(panel, ("kind",))
    kind_word = str(getattr(kind, "value", kind) or "").strip().lower()
    placed_by = str(_lookup(panel, ("placed_by",)) or "").strip().lower()
    return (
        span_kind == "cantilever"
        or kind_word == "cantilever"
        or placed_by.endswith(".cantilever")
    )


def _cantilever_route(panel: Any, geo: PanelGeometry) -> Tuple[Optional[_CantileverRoute], str]:
    """Validate placement's explicit backing handoff and derive the projection."""
    edge = str(_lookup(panel, ("cantilever_backing_edge",)) or "")
    raw_supports = _lookup(panel, ("cantilever_backing_support_ids",))
    support_values = (raw_supports,) if isinstance(raw_supports, str) else (raw_supports or ())
    support_ids = tuple(sorted(str(item) for item in support_values if str(item)))
    backing_panel_id = str(_lookup(panel, ("cantilever_backing_panel_id",)) or "")
    backspan_m = _lookup(panel, ("cantilever_backspan_m",))
    try:
        backspan_value = 0.0 if backspan_m is None else float(backspan_m)
    except (TypeError, ValueError):
        backspan_value = 0.0

    missing = []  # type: List[str]
    if edge not in SIDE_TAGS:
        missing.append("a canonical backing edge")
    if not support_ids:
        missing.append("backing beam or wall ids")
    if not backing_panel_id:
        missing.append("an adjacent backing panel id")
    if backspan_value <= 0.0:
        missing.append("a positive backing span")
    if missing:
        return (
            None,
            "cantilever backing handoff is incomplete: " + ", ".join(missing),
        )

    side = geo.sides[edge]
    if not side.supported or not side.continuous:
        return (
            None,
            "cantilever backing edge "
            + edge
            + " is not both supported and continuous into the identified backing panel",
        )

    x_extent, y_extent = _physical_extents(geo)
    axis = "x" if edge in ("x_min", "x_max") else "y"
    projection = x_extent if axis == "x" else y_extent
    across = y_extent if axis == "x" else x_extent
    if projection <= 0.0 or across <= 0.0:
        return (None, "cantilever projection or root width is zero")
    return (
        _CantileverRoute(
            axis=axis,
            projection_mm=projection,
            across_mm=across,
            backing_edge=edge,
            backing_support_ids=support_ids,
            backing_panel_id=backing_panel_id,
            backspan_mm=backspan_value * 1000.0,
        ),
        "",
    )


# ---------------------------------------------------------------------------
# one strip of mesh: area from the moment, pitch from the area
# ---------------------------------------------------------------------------


class _Row(NamedTuple):
    """One check the attempt wants written onto the result."""

    name: str
    clause: str
    demand: float
    capacity: float
    units: str


class _Station(NamedTuple):
    """One design moment on the strip, before any steel is sized."""

    tag: str  # "mid" or the side tag the support moment belongs to
    axis: str  # "x" (short span) or "y"
    face: str  # "bottom" (sagging) or "top" (hogging over a support)
    mu_nmm: float


class _Mesh(NamedTuple):
    """A sized station: what the moment asked for and what the pitch gives."""

    tag: str
    axis: str
    face: str
    mu_nmm: float
    mu_lim_nmm: float
    ast_req_mm2: float
    ast_min_mm2: float
    ast_des_mm2: float
    spacing_mm: float
    max_spacing_mm: float
    ast_prov_mm2: float
    over_lim: bool


class _Direction(NamedTuple):
    """The mesh in one direction: its bar size, its depth, its stations.

    `cover_mm` is the cover the diameter search resolved for this bar size. Only
    the outer layer's cover reaches the section dict: the inner layer's depth is
    measured off the outer one, not off the face.
    """

    axis: str
    kind: str  # "slab_main" or "slab_distribution", the Cl 26.3.3 row
    dia_mm: int
    d_mm: float
    cover_mm: float
    meshes: Tuple[_Mesh, ...]
    spacing_floor_ok: bool

    def mesh(self, tag: str, face: str) -> Optional[_Mesh]:
        for item in self.meshes:
            if item.tag == tag and item.face == face:
                return item
        return None

    def worst_spacing_mm(self) -> float:
        return min([item.spacing_mm for item in self.meshes] or [0.0])

    def worst_ratio_spacing(self) -> Tuple[float, float]:
        """(provided pitch, allowed pitch) of the station closest to the cap."""
        worst = None  # type: Optional[_Mesh]
        for item in self.meshes:
            if worst is None or item.spacing_mm / item.max_spacing_mm > worst.spacing_mm / worst.max_spacing_mm:
                worst = item
        if worst is None:
            return (0.0, 1.0)
        return (worst.spacing_mm, worst.max_spacing_mm)


class _CornerPlan(NamedTuple):
    """The Annex D-1.8 torsion mesh at one corner."""

    tag: str
    discontinuous_edges: int
    ast_mm2: float
    band_mm: float
    layers: int
    dia_mm: int
    spacing_mm: float
    ast_prov_mm2: float


def _size_station(
    station: _Station,
    d_mm: float,
    overall_depth_mm: float,
    dia_mm: int,
    fck_mpa: float,
    fy_mpa: float,
    kind: str,
) -> _Mesh:
    """Steel and pitch for one station on the one metre strip.

    A moment beyond Mu,lim is NOT silently over-reinforced: the steel is sized
    at Mu,lim, `over_lim` is raised, and the caller turns that into a failing
    flexure row that drives the thickness ladder. A slab is never detailed
    doubly reinforced.
    """
    mu_lim = is456.annex_g__mu_lim(STRIP_MM, d_mm, fck_mpa, fy_mpa)
    mu = max(float(station.mu_nmm), 0.0)
    over = mu > mu_lim + _EPS
    ast_req = is456.annex_g__ast_singly(min(mu, mu_lim), STRIP_MM, d_mm, fck_mpa, fy_mpa)
    ast_min = is456.cl_26_5_2_1__min_slab_steel(overall_depth_mm, fy_mpa, STRIP_MM)
    ast_des = max(ast_req, ast_min)
    max_spacing = is456.cl_26_3_3__max_spacing_flexure(kind, d_mm, fy_mpa)
    spacing = spacing_for_area(ast_des, dia_mm, max_spacing, SPACING_MODULE_MM)
    return _Mesh(
        tag=station.tag,
        axis=station.axis,
        face=station.face,
        mu_nmm=mu,
        mu_lim_nmm=mu_lim,
        ast_req_mm2=ast_req,
        ast_min_mm2=ast_min,
        ast_des_mm2=ast_des,
        spacing_mm=spacing,
        max_spacing_mm=max_spacing,
        ast_prov_mm2=area_for_spacing(dia_mm, spacing),
        over_lim=over,
    )


def _size_direction(
    axis: str,
    stations: Sequence[_Station],
    overall_depth_mm: float,
    depth_for: Any,
    ctx: SlabContext,
    kind: str,
) -> _Direction:
    """Pick the mesh diameter for one direction and size every station on it.

    The catalogue is walked from the smallest bar upward and the first size
    whose worst pitch clears the 100 mm placing floor wins (spec 05 section 5.3:
    the floor bumps the diameter, it never squeezes the pitch). `depth_for` maps
    a trial diameter to the effective depth, so the x direction can say "outer
    layer" and the y direction can say "one bar in".
    """
    chosen = None  # type: Optional[_Direction]
    for dia in MESH_DIAS_MM:
        cover = resolve_cover("slab", ctx.exposure, ctx.fire_rating_h, dia)
        d_mm = depth_for(dia, cover.cover_mm)
        if d_mm <= 0.0:
            continue
        meshes = tuple(
            _size_station(station, d_mm, overall_depth_mm, dia, ctx.fck_mpa, ctx.fy_mpa, kind)
            for station in stations
        )
        candidate = _Direction(
            axis=axis,
            kind=kind,
            dia_mm=int(dia),
            d_mm=d_mm,
            cover_mm=cover.cover_mm,
            meshes=meshes,
            spacing_floor_ok=min([m.spacing_mm for m in meshes] or [0.0]) >= MIN_MESH_SPACING_MM - _EPS,
        )
        chosen = candidate
        if candidate.spacing_floor_ok:
            return candidate
    if chosen is None:
        # Every trial depth came out non-positive: the slab is thinner than its
        # own cover. Report the largest bar so the caller still has a section.
        dia = MESH_DIAS_MM[-1]
        cover = resolve_cover("slab", ctx.exposure, ctx.fire_rating_h, dia)
        d_mm = max(depth_for(dia, cover.cover_mm), 1.0)
        meshes = tuple(
            _size_station(station, d_mm, overall_depth_mm, dia, ctx.fck_mpa, ctx.fy_mpa, kind)
            for station in stations
        )
        chosen = _Direction(
            axis=axis,
            kind=kind,
            dia_mm=int(dia),
            d_mm=d_mm,
            cover_mm=cover.cover_mm,
            meshes=meshes,
            spacing_floor_ok=False,
        )
    return chosen


# ---------------------------------------------------------------------------
# moments: Annex D for two-way panels, Table 12 (guarded) for one-way strips
# ---------------------------------------------------------------------------


class _MomentPlan(NamedTuple):
    """Design moments on the strip plus how they were arrived at."""

    stations: Tuple[_Station, ...]
    method: str  # "table26" | "table27" | "table12" | "ss"
    clause: str
    notes: Tuple[str, ...]
    disclosures: Tuple[Tuple[str, str], ...]  # (registry code, message)


class _Guard(NamedTuple):
    """Clause 22.5.1 applicability, split into what failed and what was assumed."""

    ok: bool
    unmet: Tuple[str, ...]
    assumed: Tuple[str, ...]


def _pct(value: float) -> str:
    return ("%.1f" % float(value)).rstrip("0").rstrip(".") + " percent"


def _kpa(value: float) -> str:
    return ("%.2f" % float(value)).rstrip("0").rstrip(".") + " kPa"


def _mm_text(value: float) -> str:
    number = float(value)
    return (str(int(round(number))) if abs(number - round(number)) < 1e-9 else ("%.1f" % number)) + " mm"


def _coefficient_guard(ctx: SlabContext, continuous_supports: int) -> _Guard:
    """Clause 22.5.1: three or more near-equal spans, UDL, imposed under dead.

    The SlabLoad contract carries only the combined pressures, so the legs this
    designer cannot see are recorded as ASSUMED rather than silently passed or
    silently failed. A panel continuous at both supports is inside a run of at
    least three spans by construction, which is the one span-count leg the
    continuity mask does settle on its own.
    """
    unmet = []  # type: List[str]
    assumed = []  # type: List[str]

    spans = ctx.continuous_spans
    if spans is None:
        if continuous_supports >= 2:
            assumed.append(
                "three or more spans taken from continuity at both supports: an interior panel "
                "has a span either side of it"
            )
        else:
            unmet.append(
                "span count not stated and only "
                + str(continuous_supports)
                + " support is continuous, so a run of three or more spans is not established"
            )
    elif int(spans) < 3:
        unmet.append("the run has " + str(int(spans)) + " spans, fewer than the three the clause asks for")

    variation = ctx.span_variation_pct
    if variation is None:
        assumed.append("spans assumed within 15 percent of each other; the placer equalizes the grid")
    elif float(variation) > 15.0 + _EPS:
        unmet.append("spans vary by " + _pct(variation) + ", more than the 15 percent the clause allows")

    if ctx.imposed_kpa is None or ctx.dead_kpa is None:
        assumed.append(
            "imposed against dead not verified: the slab load contract carries the combined "
            "pressures only, not the split"
        )
    elif float(ctx.imposed_kpa) > float(ctx.dead_kpa) + _EPS:
        unmet.append(
            "imposed "
            + _kpa(ctx.imposed_kpa)
            + " exceeds dead "
            + _kpa(ctx.dead_kpa)
            + ", and the clause wants the imposed load no greater than the dead load"
        )

    return _Guard(ok=not unmet, unmet=tuple(unmet), assumed=tuple(assumed))


def _two_way_moments(geo: PanelGeometry, w_line_n_per_mm: float, ctx: SlabContext) -> _MomentPlan:
    """Annex D moments for a panel supported on four sides.

    Table 26 for a restrained panel, Table 27 where the panel is discontinuous
    on all four edges and the corners are not held down (case 9 with
    `corners_held_down` false, which is the default: an unrestrained corner is
    the heavier reading and the one Table 27 is printed for).
    """
    scale = w_line_n_per_mm * geo.lx_mm * geo.lx_mm
    notes = []  # type: List[str]
    stations = []  # type: List[_Station]

    if geo.case == 9 and not ctx.corners_held_down:
        free = is456.annex_d__table27(geo.ratio)
        stations.append(_Station(tag="mid", axis="x", face="bottom", mu_nmm=free.alpha_x * scale))
        stations.append(_Station(tag="mid", axis="y", face="bottom", mu_nmm=free.alpha_y * scale))
        notes.append(
            "all four edges discontinuous and the corners are not held down, so Table 27 applies "
            "and no D-1.8 corner torsion mesh is detailed"
        )
        return _MomentPlan(
            stations=tuple(stations),
            method="table27",
            clause="IS456:2000 Table 27",
            notes=tuple(notes),
            disclosures=(),
        )

    coeff = is456.annex_d__table26(geo.case, geo.ratio)
    stations.append(_Station(tag="mid", axis="x", face="bottom", mu_nmm=coeff.alpha_x_pos * scale))
    for index, tag in enumerate(geo.long_side_tags):
        if geo.long_cont[index]:
            stations.append(_Station(tag=tag, axis="x", face="top", mu_nmm=coeff.alpha_x_neg * scale))
    stations.append(_Station(tag="mid", axis="y", face="bottom", mu_nmm=coeff.alpha_y_pos * scale))
    for index, tag in enumerate(geo.short_side_tags):
        if geo.short_cont[index]:
            stations.append(_Station(tag=tag, axis="y", face="top", mu_nmm=coeff.alpha_y_neg * scale))
    notes.append(
        "Table 26 case "
        + str(geo.case)
        + " at ly/lx "
        + ("%.3f" % geo.ratio)
        + "; both directions take alpha w lx^2 with lx the shorter span"
    )
    return _MomentPlan(
        stations=tuple(stations),
        method="table26",
        clause="IS456:2000 Table 26",
        notes=tuple(notes),
        disclosures=(),
    )


def _one_way_moments(route: _SpanRoute, w_line_n_per_mm: float, ctx: SlabContext) -> _MomentPlan:
    """One-way moments across the supported span: w l^2 / 8 or Table 12.

    The Table 12 rows are printed for the dead case and the imposed case
    separately and the combined factored pressure cannot be split, so BOTH rows
    are read and the heavier coefficient is taken at every position. That is an
    envelope, never an under-read, and both reads land in the trace.
    """
    span = route.span_mm
    scale = w_line_n_per_mm * span * span
    continuous = [tag for index, tag in enumerate(route.support_tags) if route.continuity[index]]
    stations = []  # type: List[_Station]
    notes = []  # type: List[str]
    disclosures = []  # type: List[Tuple[str, str]]

    if not continuous:
        stations.append(_Station(tag="mid", axis="x", face="bottom", mu_nmm=scale / 8.0))
        notes.append("both supports discontinuous: simply supported, w l^2 / 8 at midspan")
        return _MomentPlan(
            stations=tuple(stations),
            method="ss",
            clause="IS456:2000 22.5",
            notes=tuple(notes),
            disclosures=(),
        )

    interior = len(continuous) == 2
    span_key = "span_interior" if interior else "span_end"
    support_key = "support_interior" if interior else "support_near_end"
    alpha_span = max(abs(table12_alpha(span_key, case)) for case in ("dead", "imposed"))
    alpha_support = max(abs(table12_alpha(support_key, case)) for case in ("dead", "imposed"))

    stations.append(_Station(tag="mid", axis="x", face="bottom", mu_nmm=alpha_span * scale))
    for tag in continuous:
        stations.append(_Station(tag=tag, axis="x", face="top", mu_nmm=alpha_support * scale))

    notes.append(
        "Table 12 "
        + ("interior span" if interior else "end span")
        + ": the combined factored pressure is taken on the heavier of the dead and the imposed "
        + "coefficient row at every position; the context split checks applicability but the "
        + "frozen factored slab envelope remains combined"
    )

    guard = _coefficient_guard(ctx, len(continuous))
    for sentence in guard.assumed:
        notes.append("Cl 22.5.1 assumed: " + sentence)
    if not guard.ok:
        disclosures.append(
            (
                "W_ANA_COEFF_INAPPLICABLE",
                "IS 456 Cl 22.5.1 is not established for this panel ("
                + "; ".join(guard.unmet)
                + "). The Table 12 coefficients are used anyway and the moments stand as reported, "
                + "per the disclose-never-refuse rule; verify against an analysis of the run.",
            )
        )

    return _MomentPlan(
        stations=tuple(stations),
        method="table12",
        clause="IS456:2000 Table 12",
        notes=tuple(notes),
        disclosures=tuple(disclosures),
    )


# ---------------------------------------------------------------------------
# one attempt at one thickness: steel, shear, deflection, corner mesh
# ---------------------------------------------------------------------------

#: Checks a thicker slab can fix. Anything else (a pitch under the placing
#: floor, say) is answered by the bar catalogue, not by the resize ladder.
THICKNESS_DRIVEN_CHECKS = (
    "flexure x",
    "flexure y",
    "flexure main",
    "flexure distribution",
    "shear",
    "shear cap",
    "deflection",
)


@dataclass
class _Attempt:
    """Everything one thickness produced, before any of it is written out."""

    depth_mm: float
    two_way: bool
    plan: _MomentPlan
    x: _Direction
    y: _Direction
    rows: List[_Row] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    disclosures: List[Tuple[str, str]] = field(default_factory=list)
    corners: List[_CornerPlan] = field(default_factory=list)
    deflection_route: str = ""

    def failing(self) -> List[_Row]:
        """Rows the section does not satisfy, worst first, ties in row order."""
        bad = [row for row in self.rows if _ratio_of(row) > 1.0 + 1e-9]
        return sorted(bad, key=lambda row: (-_ratio_of(row), self.rows.index(row)))

    def failing_thickness(self) -> List[_Row]:
        return [row for row in self.failing() if row.name in THICKNESS_DRIVEN_CHECKS]


def _ratio_of(row: _Row) -> float:
    if row.capacity > 0.0:
        return row.demand / row.capacity
    return 0.0 if row.demand <= 0.0 else float("inf")


def _worst_by_ratio(meshes: Sequence[_Mesh], numerator: Any, denominator: Any) -> Tuple[float, float]:
    """(demand, capacity) of the mesh whose numerator/denominator is worst."""
    best = None  # type: Optional[Tuple[float, float]]
    for mesh in meshes:
        pair = (float(numerator(mesh)), float(denominator(mesh)))
        if pair[1] <= 0.0:
            continue
        if best is None or pair[0] / pair[1] > best[0] / best[1] + 1e-12:
            best = pair
    return best if best is not None else (0.0, 1.0)


def _panel_attempt(
    geo: PanelGeometry,
    ctx: SlabContext,
    depth_mm: float,
    w_line_n_per_mm: float,
    ll_kpa: float,
    two_way: bool,
    route: _SpanRoute,
) -> _Attempt:
    """Design the strip at one thickness. Pure: the ladder calls it repeatedly."""
    plan = (
        _two_way_moments(geo, w_line_n_per_mm, ctx)
        if two_way
        else _one_way_moments(route, w_line_n_per_mm, ctx)
    )

    x_stations = [s for s in plan.stations if s.axis == "x"]
    y_stations = [s for s in plan.stations if s.axis == "y"]
    if not y_stations:
        # One-way: the transverse steel carries no moment and lands on the
        # Cl 26.5.2.1 minimum, which `_size_station` applies as the floor.
        y_stations = [_Station(tag="mid", axis="y", face="bottom", mu_nmm=0.0)]

    def depth_x(dia_mm: int, cover_mm: float) -> float:
        return depth_mm - cover_mm - 0.5 * float(dia_mm)

    main_axis = "x" if two_way else route.axis
    distribution_axis = "y" if two_way else ("y" if route.axis == "x" else "x")
    x_dir = _size_direction(main_axis, x_stations, depth_mm, depth_x, ctx, "slab_main")

    def depth_y(dia_mm: int, _cover_mm: float) -> float:
        # The short-span bars are outermost, so the long-span mesh sits one bar
        # in: d_y = d_x - (dia_x + dia_y) / 2, which is d_x - dia when the two
        # mesh sizes are equal (the form spec 05 section 5.3 states).
        return x_dir.d_mm - 0.5 * float(x_dir.dia_mm) - 0.5 * float(dia_mm)

    y_dir = _size_direction(
        distribution_axis,
        y_stations,
        depth_mm,
        depth_y,
        ctx,
        "slab_main" if two_way else "slab_distribution",
    )

    attempt = _Attempt(depth_mm=depth_mm, two_way=two_way, plan=plan, x=x_dir, y=y_dir)
    attempt.notes.extend(plan.notes)
    attempt.disclosures.extend(plan.disclosures)

    # -- flexure and steel ------------------------------------------------
    for direction in (x_dir, y_dir):
        label = " " + direction.axis
        mu_max = max([m.mu_nmm for m in direction.meshes] or [0.0])
        mu_lim = direction.meshes[0].mu_lim_nmm if direction.meshes else 0.0
        attempt.rows.append(_Row("flexure" + label, "IS456:2000 G-1.1(b)", mu_max, mu_lim, "N.mm"))
        demand, capacity = _worst_by_ratio(
            direction.meshes, lambda m: m.ast_des_mm2, lambda m: m.ast_prov_mm2
        )
        attempt.rows.append(_Row("steel" + label, "IS456:2000 G-1.1(a)", demand, capacity, "mm2/m"))
        pitch, allowed = direction.worst_ratio_spacing()
        attempt.rows.append(_Row("bar spacing" + label, "IS456:2000 26.3.3", pitch, allowed, "mm"))
        if not direction.spacing_floor_ok:
            attempt.notes.append(
                "the "
                + direction.axis
                + " mesh pitch is below the "
                + _mm_text(MIN_MESH_SPACING_MM)
                + " placing floor even on the largest mesh bar in the catalogue ("
                + _mm_text(MESH_DIAS_MM[-1])
                + "); detailed at the computed pitch and flagged"
            )

    ast_min = x_dir.meshes[0].ast_min_mm2 if x_dir.meshes else 0.0
    provided_min = min([m.ast_prov_mm2 for m in list(x_dir.meshes) + list(y_dir.meshes)] or [0.0])
    attempt.rows.append(_Row("min steel", "IS456:2000 26.5.2.1", ast_min, provided_min, "mm2/m"))

    # -- shear at d from the support face ---------------------------------
    mid_x = x_dir.mesh("mid", "bottom")
    ast_mid_x = mid_x.ast_prov_mm2 if mid_x is not None else 0.0
    design_span_mm = geo.lx_mm if two_way else route.span_mm
    vu_n = max(w_line_n_per_mm * (0.5 * design_span_mm - x_dir.d_mm), 0.0)
    tau_v = is456.cl_40_1__tau_v(vu_n, STRIP_MM, x_dir.d_mm)
    pt = 100.0 * ast_mid_x / (STRIP_MM * x_dir.d_mm)
    tau_c = is456.table_19__tau_c(pt, ctx.fck_mpa)
    k_depth = is456.cl_40_2_1_1__k_solid_slab(depth_mm)
    attempt.rows.append(_Row("shear", "IS456:2000 40.2.1.1", tau_v, k_depth * tau_c, "MPa"))
    tau_c_max = is456.table_20__tau_c_max(ctx.fck_mpa)
    attempt.rows.append(_Row("shear cap", "IS456:2000 40.2.3.1", tau_v, 0.5 * tau_c_max, "MPa"))
    attempt.notes.append(
        "shear taken at d from the support face on w (design span/2 - d); tau_c reads the midspan bottom "
        "steel, which v1 runs the full span so it is present at the support"
    )

    # -- deflection --------------------------------------------------------
    support_continuity = geo.long_cont if two_way else route.continuity
    support_word = "continuous" if all(support_continuity) else "simply_supported"
    design_span_m = design_span_mm / 1000.0
    allowed = 0.0
    clause = ""
    if two_way:
        two_way_ld = is456.cl_24_1__two_way_ld(support_word, ctx.fy_mpa, design_span_m, ll_kpa)
        if two_way_ld.applicable:
            allowed = two_way_ld.ratio
            clause = "IS456:2000 24.1"
            attempt.deflection_route = "cl_24_1"
        else:
            attempt.notes.append(
                "Cl 24.1 Note is limited to a shorter span up to 3.5 m and an imposed load up to "
                "3 kN/m2; this panel spans "
                + ("%.2f" % design_span_m)
                + " m under "
                + _kpa(ll_kpa)
                + ", so the Cl 23.2.1 modification factor route is used instead"
            )
    if not clause:
        basic = is456.cl_23_2_1__basic_ld(support_word)
        req = mid_x.ast_des_mm2 if mid_x is not None else 0.0
        prov = ast_mid_x if ast_mid_x > 0.0 else 1.0
        fs = is456.cl_23_2_1__fs(ctx.fy_mpa, req, prov)
        mf = is456.fig_4__mf_tension(fs, 100.0 * prov / (STRIP_MM * x_dir.d_mm))
        long_span = is456.cl_23_2_1_c__long_span_factor(design_span_m)
        allowed = basic * mf * long_span
        clause = "IS456:2000 23.2.1"
        attempt.deflection_route = "cl_23_2_1"
    attempt.rows.append(_Row("deflection", clause, design_span_mm / x_dir.d_mm, allowed, "span/d"))

    # -- Annex D-1.8 corner torsion mesh -----------------------------------
    if two_way and plan.method == "table26":
        mid_y = y_dir.mesh("mid", "bottom")
        ast_mid = max(
            mid_x.ast_des_mm2 if mid_x is not None else 0.0,
            mid_y.ast_des_mm2 if mid_y is not None else 0.0,
        )
        for tag, side_tags in CORNER_SIDES:
            discontinuous = sum(1 for side in side_tags if not geo.sides[side].continuous)
            if discontinuous == 0:
                continue
            torsion = is456.annex_d_1_8__corner_torsion(ast_mid, geo.lx_mm, discontinuous)
            cap_mm = x_dir.meshes[0].max_spacing_mm if x_dir.meshes else 300.0
            pitch = spacing_for_area(torsion.ast_mm2, x_dir.dia_mm, cap_mm, SPACING_MODULE_MM)
            attempt.corners.append(
                _CornerPlan(
                    tag=tag,
                    discontinuous_edges=discontinuous,
                    ast_mm2=torsion.ast_mm2,
                    band_mm=torsion.band_mm,
                    layers=torsion.layers,
                    dia_mm=x_dir.dia_mm,
                    spacing_mm=pitch,
                    ast_prov_mm2=area_for_spacing(x_dir.dia_mm, pitch),
                )
            )
        if attempt.corners:
            attempt.notes.append(
                "D-1.8 corner torsion mesh over a band of lx/5, four layers, at every corner with a "
                "discontinuous edge; three quarters of the maximum mid-span steel where both edges "
                "at the corner are discontinuous and half of that per D-1.9 where one is continuous"
            )
    return attempt


def _cantilever_attempt(
    route: _CantileverRoute,
    ctx: SlabContext,
    depth_mm: float,
    w_line_n_per_mm: float,
) -> _Attempt:
    """Design one thickness of the root-fixed one metre cantilever strip."""
    root_mu = w_line_n_per_mm * route.projection_mm * route.projection_mm / 2.0
    plan = _MomentPlan(
        stations=(_Station(tag="root", axis="main", face="top", mu_nmm=root_mu),),
        method="cantilever",
        clause="IS456:2000 22.2",
        notes=(
            "cantilever root hogging moment is w a^2 / 2 on the full projection normal to "
            + route.backing_edge,
        ),
        disclosures=(),
    )

    def depth_main(dia_mm: int, cover_mm: float) -> float:
        return depth_mm - cover_mm - 0.5 * float(dia_mm)

    main = _size_direction(
        "main",
        plan.stations,
        depth_mm,
        depth_main,
        ctx,
        "slab_main",
    )

    def depth_distribution(dia_mm: int, _cover_mm: float) -> float:
        return main.d_mm - 0.5 * float(main.dia_mm) - 0.5 * float(dia_mm)

    distribution = _size_direction(
        "distribution",
        (_Station(tag="full", axis="distribution", face="top", mu_nmm=0.0),),
        depth_mm,
        depth_distribution,
        ctx,
        "slab_distribution",
    )
    attempt = _Attempt(
        depth_mm=depth_mm,
        two_way=False,
        plan=plan,
        x=main,
        y=distribution,
    )
    attempt.notes.extend(plan.notes)

    for direction in (main, distribution):
        label = " " + direction.axis
        mu_max = max([mesh.mu_nmm for mesh in direction.meshes] or [0.0])
        mu_lim = direction.meshes[0].mu_lim_nmm if direction.meshes else 0.0
        attempt.rows.append(
            _Row("flexure" + label, "IS456:2000 G-1.1(b)", mu_max, mu_lim, "N.mm")
        )
        demand, capacity = _worst_by_ratio(
            direction.meshes,
            lambda mesh: mesh.ast_des_mm2,
            lambda mesh: mesh.ast_prov_mm2,
        )
        attempt.rows.append(
            _Row("steel" + label, "IS456:2000 G-1.1(a)", demand, capacity, "mm2/m")
        )
        pitch, allowed = direction.worst_ratio_spacing()
        attempt.rows.append(
            _Row("bar spacing" + label, "IS456:2000 26.3.3", pitch, allowed, "mm")
        )
        if not direction.spacing_floor_ok:
            attempt.notes.append(
                "the "
                + direction.axis
                + " cantilever mesh pitch is below the "
                + _mm_text(MIN_MESH_SPACING_MM)
                + " placing floor even on the largest catalogue bar"
            )

    root_mesh = main.mesh("root", "top")
    ast_min = root_mesh.ast_min_mm2 if root_mesh is not None else 0.0
    provided_min = min(
        [mesh.ast_prov_mm2 for mesh in list(main.meshes) + list(distribution.meshes)] or [0.0]
    )
    attempt.rows.append(
        _Row("min steel", "IS456:2000 26.5.2.1", ast_min, provided_min, "mm2/m")
    )

    ast_root = root_mesh.ast_prov_mm2 if root_mesh is not None else 0.0
    vu_n = max(w_line_n_per_mm * (route.projection_mm - main.d_mm), 0.0)
    tau_v = is456.cl_40_1__tau_v(vu_n, STRIP_MM, main.d_mm)
    pt = 100.0 * ast_root / (STRIP_MM * main.d_mm)
    tau_c = is456.table_19__tau_c(pt, ctx.fck_mpa)
    k_depth = is456.cl_40_2_1_1__k_solid_slab(depth_mm)
    attempt.rows.append(
        _Row("shear", "IS456:2000 40.2.1.1", tau_v, k_depth * tau_c, "MPa")
    )
    tau_c_max = is456.table_20__tau_c_max(ctx.fck_mpa)
    attempt.rows.append(
        _Row("shear cap", "IS456:2000 40.2.3.1", tau_v, 0.5 * tau_c_max, "MPa")
    )
    attempt.notes.append(
        "cantilever shear is checked at d from the root on w (a - d), using the provided "
        "top root steel for the Table 19 percentage"
    )

    required = root_mesh.ast_des_mm2 if root_mesh is not None else 0.0
    provided = ast_root if ast_root > 0.0 else 1.0
    fs = is456.cl_23_2_1__fs(ctx.fy_mpa, required, provided)
    mf = is456.fig_4__mf_tension(fs, 100.0 * provided / (STRIP_MM * main.d_mm))
    basic = is456.cl_23_2_1__basic_ld("cantilever")
    attempt.rows.append(
        _Row(
            "deflection",
            "IS456:2000 23.2.1",
            route.projection_mm / main.d_mm,
            basic * mf,
            "span/d",
        )
    )
    attempt.deflection_route = "cl_23_2_1_cantilever"
    attempt.notes.append(
        "Cl 23.2.1 cantilever basic span/effective-depth ratio 7 is modified by Fig 4; "
        "the two-way Cl 24.1 Note does not apply"
    )

    ld_mm = is456.cl_26_2_1__ld(main.dia_mm, ctx.fy_mpa, ctx.fck_mpa)
    attempt.rows.append(
        _Row(
            "cantilever development length",
            "IS456:2000 26.2.1",
            ld_mm,
            route.backspan_mm,
            "mm",
        )
    )
    return attempt


# ---------------------------------------------------------------------------
# writing an attempt onto the result
# ---------------------------------------------------------------------------


def _bar_count(extent_mm: float, spacing_mm: float) -> int:
    """Bars across an extent at a pitch, both ends included."""
    if spacing_mm <= 0.0:
        return 0
    return int(math.floor(max(extent_mm, 0.0) / spacing_mm + _EPS)) + 1


def _support_zone(tag: str, span_mm: float, band_mm: float) -> List[float]:
    """[from, to] of a support band along the span it reaches into."""
    if tag.endswith("_max"):
        return [span_mm - band_mm, span_mm]
    return [0.0, band_mm]


def _emit_mesh(
    result: DesignResult,
    direction: _Direction,
    span_mm: float,
    across_mm: float,
    ctx: SlabContext,
) -> None:
    """Mesh bar entries for one direction.

    `zone_mm` is the run of the bar along its own span, so a schedule reads the
    bar length straight off it, and `count` is how many of them the pitch puts
    across the panel. Bottom steel runs the full span (v1 curtails nothing);
    support steel runs 0.3 l from the support line, Annex D-1.6.
    """
    ld_mm = is456.cl_26_2_1__ld(direction.dia_mm, ctx.fy_mpa, ctx.fck_mpa)
    for mesh in direction.meshes:
        if mesh.face == "bottom":
            zone = [0.0, span_mm]
            role = "mesh_" + direction.axis + "_bottom"
        else:
            band = SUPPORT_BAND_FRACTION * span_mm
            zone = _support_zone(mesh.tag, span_mm, band)
            role = "mesh_" + direction.axis + "_top_" + mesh.tag
        result.add_bar(
            role=role,
            count=_bar_count(across_mm, mesh.spacing_mm),
            dia_mm=float(direction.dia_mm),
            ld_mm=ld_mm,
            zone_mm=zone,
            spacing_mm=mesh.spacing_mm,
            ast_prov_mm2_per_m=mesh.ast_prov_mm2,
            ast_req_mm2_per_m=mesh.ast_des_mm2,
            direction=direction.axis,
            face=mesh.face,
            station=mesh.tag,
        )


def _emit_cantilever_mesh(
    result: DesignResult,
    attempt: _Attempt,
    route: _CantileverRoute,
    ctx: SlabContext,
) -> None:
    """Full-projection top main bars with one Ld into the backing slab."""
    main_mesh = attempt.x.mesh("root", "top")
    distribution_mesh = attempt.y.mesh("full", "top")
    if main_mesh is None or distribution_mesh is None:
        return

    main_ld = is456.cl_26_2_1__ld(attempt.x.dia_mm, ctx.fy_mpa, ctx.fck_mpa)
    if route.backing_edge in ("x_min", "y_min"):
        root_mm = 0.0
        anchor_zone = [-main_ld, 0.0]
    else:
        root_mm = route.projection_mm
        anchor_zone = [route.projection_mm, route.projection_mm + main_ld]
    result.add_bar(
        role="mesh_cantilever_main_top",
        count=_bar_count(route.across_mm, main_mesh.spacing_mm),
        dia_mm=float(attempt.x.dia_mm),
        ld_mm=main_ld,
        zone_mm=[0.0, route.projection_mm],
        layer=1,
        spacing_mm=main_mesh.spacing_mm,
        ast_prov_mm2_per_m=main_mesh.ast_prov_mm2,
        ast_req_mm2_per_m=main_mesh.ast_des_mm2,
        direction=route.axis,
        face="top",
        station="root",
        backing_edge=route.backing_edge,
        backing_support_ids=list(route.backing_support_ids),
        backing_panel_id=route.backing_panel_id,
        root_mm=root_mm,
        anchor_zone_mm=anchor_zone,
        anchorage_ends=1,
    )

    distribution_axis = "y" if route.axis == "x" else "x"
    distribution_ld = is456.cl_26_2_1__ld(
        attempt.y.dia_mm, ctx.fy_mpa, ctx.fck_mpa
    )
    result.add_bar(
        role="mesh_cantilever_distribution_top",
        count=_bar_count(route.projection_mm, distribution_mesh.spacing_mm),
        dia_mm=float(attempt.y.dia_mm),
        ld_mm=distribution_ld,
        zone_mm=[0.0, route.across_mm],
        layer=2,
        spacing_mm=distribution_mesh.spacing_mm,
        ast_prov_mm2_per_m=distribution_mesh.ast_prov_mm2,
        ast_req_mm2_per_m=distribution_mesh.ast_des_mm2,
        direction=distribution_axis,
        face="top",
        station="full",
        anchorage_ends=0,
    )


def _emit_corners(result: DesignResult, corners: Sequence[_CornerPlan], ctx: SlabContext) -> None:
    """Four layers of torsion mesh at each corner that needs one, D-1.8/D-1.9."""
    for corner in corners:
        ld_mm = is456.cl_26_2_1__ld(corner.dia_mm, ctx.fy_mpa, ctx.fck_mpa)
        count = _bar_count(corner.band_mm, corner.spacing_mm)
        for axis in ("x", "y"):
            for face in ("bottom", "top"):
                result.add_bar(
                    role="mesh_corner_" + corner.tag + "_" + axis + "_" + face,
                    count=count,
                    dia_mm=float(corner.dia_mm),
                    ld_mm=ld_mm,
                    zone_mm=[0.0, corner.band_mm],
                    spacing_mm=corner.spacing_mm,
                    ast_prov_mm2_per_m=corner.ast_prov_mm2,
                    ast_req_mm2_per_m=corner.ast_mm2,
                    corner=corner.tag,
                    direction=axis,
                    discontinuous_edges=corner.discontinuous_edges,
                    face=face,
                )


def _disclose(result: DesignResult, code: str, message: str, clause: Optional[str] = None) -> None:
    """Attach a registry-checked disclosure to the result.

    `make_disclosure` validates the code against model.REGISTRY, so an
    unregistered code raises here rather than reaching the report. The entry
    lands structured in `extras["disclosures"]` and its text is mirrored into
    `warnings` with the code in front, which is where the report reads it.
    """
    entry = make_disclosure(code, message, [result.element_id], clause=clause, stage=_STAGE)
    result.extras.setdefault("disclosures", []).append(entry.to_dict())
    result.add_warning(code + ": " + message)


# ---------------------------------------------------------------------------
# design_slab
# ---------------------------------------------------------------------------


def _two_way_decision(panel: Any, geo: PanelGeometry) -> Tuple[bool, List[str], List[str]]:
    """(two_way, notes, warnings) from ly/lx and the support mask."""
    notes = []  # type: List[str]
    warnings = []  # type: List[str]
    by_ratio = geo.ratio <= 2.0 + _EPS
    unsupported = [tag for tag in SIDE_TAGS if not geo.sides[tag].supported]
    two_way = by_ratio and not unsupported

    if unsupported:
        warnings.append(
            "sides "
            + ", ".join(unsupported)
            + " carry no beam or wall over at least half their length; the panel can be one-way "
            + "only where an actual opposed supported pair establishes its design span"
        )
    elif not by_ratio:
        notes.append(
            "ly/lx is " + ("%.3f" % geo.ratio) + ", above 2.0, so the panel spans one way across lx"
        )

    stated = _lookup(panel, ("two_way",))
    if stated is not None and bool(stated) != two_way:
        notes.append(
            "placement recorded this panel as "
            + ("two-way" if stated else "one-way")
            + "; design reads ly/lx "
            + ("%.3f" % geo.ratio)
            + " with "
            + str(geo.supported_sides)
            + " of 4 sides supported and designs it "
            + ("two-way" if two_way else "one-way")
        )
    return two_way, notes, warnings


def _imposed_for_guard(ctx: SlabContext, pressures: SlabLoad) -> Tuple[float, Optional[str]]:
    """The imposed pressure the Cl 24.1 Note guard is entered with."""
    if ctx.imposed_kpa is not None:
        return float(ctx.imposed_kpa), None
    return (
        float(pressures.w_service_kpa),
        "the imposed pressure is not separated from the service combination, so the whole service "
        "pressure "
        + _kpa(pressures.w_service_kpa)
        + " enters the Cl 24.1 Note guard. This is a routing fallback, not a conservative claim: "
        "when it takes a panel outside the Note, Cl 23.2.1 can allow a larger span/depth ratio "
        "and a thinner slab; supply the imposed-load split to evaluate Cl 24.1 correctly",
    )


def _initial_thickness(
    panel: Any, design_span_mm: float, policy: ResizePolicy
) -> Tuple[float, Optional[str]]:
    """Thickness to start the ladder at, in mm, and a note when it was derived."""
    thickness_m = _lookup(panel, ("thickness_m",))
    if thickness_m is not None:
        placed = float(thickness_m) * 1000.0
        if placed < RC_SLAB_MIN_THICKNESS_MM - _EPS:
            return (
                RC_SLAB_MIN_THICKNESS_MM,
                "the placed panel depth "
                + _mm_text(placed)
                + " is below the project minimum and was raised to "
                + _mm_text(RC_SLAB_MIN_THICKNESS_MM),
            )
        return placed, None
    derived = round_up_mm(design_span_mm / 30.0, policy.slab_step_mm)
    cap_mm = max(policy.slab_cap_mm, RC_SLAB_MIN_THICKNESS_MM)
    derived = min(max(derived, RC_SLAB_MIN_THICKNESS_MM), cap_mm)
    return (
        derived,
        "the panel carried no thickness, so the ladder starts at design span/30 rounded up to the "
        + _mm_text(policy.slab_step_mm)
        + " module and clamped to the "
        + _mm_text(RC_SLAB_MIN_THICKNESS_MM)
        + " to "
        + _mm_text(cap_mm)
        + " band",
    )


def _initial_cantilever_thickness(
    panel: Any, projection_mm: float, policy: ResizePolicy
) -> Tuple[float, Optional[str]]:
    """Placed depth, or the Cl 23.2.1 basic a/7 start for a bare cantilever."""
    thickness_m = _lookup(panel, ("thickness_m",))
    if thickness_m is not None:
        placed = float(thickness_m) * 1000.0
        if placed < RC_SLAB_MIN_THICKNESS_MM - _EPS:
            return (
                RC_SLAB_MIN_THICKNESS_MM,
                "the placed cantilever depth "
                + _mm_text(placed)
                + " is below the project minimum and was raised to "
                + _mm_text(RC_SLAB_MIN_THICKNESS_MM),
            )
        return placed, None
    derived = max(
        RC_SLAB_MIN_THICKNESS_MM,
        round_up_mm(projection_mm / 7.0, policy.slab_step_mm),
    )
    return (
        derived,
        "the cantilever carried no thickness, so the ladder starts at projection/7 rounded "
        "up to the "
        + _mm_text(policy.slab_step_mm)
        + " module",
    )


def _record_project_minimum_resizes(
    result: DesignResult, placed_depth_mm: Optional[float], policy: ResizePolicy
) -> None:
    """Record the ordinary slab ladder up to the mandatory project floor."""
    if placed_depth_mm is None:
        return
    depth = float(placed_depth_mm)
    step = max(float(policy.slab_step_mm), 1.0)
    while depth < RC_SLAB_MIN_THICKNESS_MM - _EPS:
        next_depth = min(depth + step, RC_SLAB_MIN_THICKNESS_MM)
        result.add_resize(depth, next_depth, "project minimum RC slab thickness")
        depth = next_depth


def _design_cantilever(
    panel: Any,
    pressures: SlabLoad,
    context: SlabContext,
    geo: PanelGeometry,
    result: DesignResult,
    route: _CantileverRoute,
) -> DesignResult:
    """Run the dedicated root-hogging cantilever ladder and detailing."""
    policy = context.policy
    depth, depth_note = _initial_cantilever_thickness(
        panel, route.projection_mm, policy
    )
    placed_depth = _lookup(panel, ("thickness_m",))
    _record_project_minimum_resizes(
        result,
        None if placed_depth is None else float(placed_depth) * 1000.0,
        policy,
    )
    if depth_note:
        result.add_note(depth_note)
    cap_mm = max(policy.slab_cap_mm, RC_SLAB_MIN_THICKNESS_MM, depth)
    w_line = _line_load_n_per_mm(pressures.w_u_kpa)

    attempt = _cantilever_attempt(route, context, depth, w_line)
    steps = 0
    while steps < policy.max_iters:
        outstanding = attempt.failing_thickness()
        if not outstanding or depth >= cap_mm - _EPS:
            break
        nxt = min(depth + policy.slab_step_mm, cap_mm)
        if nxt <= depth + _EPS:
            break
        result.add_resize(depth, nxt, outstanding[0].name + " at D " + _mm_text(depth))
        depth = nxt
        attempt = _cantilever_attempt(route, context, depth, w_line)
        steps += 1

    entries = []  # type: List[TraceEntry]
    with trace_into(entries):
        attempt = _cantilever_attempt(route, context, depth, w_line)
    result.trace = entries

    d_x = attempt.x.d_mm if route.axis == "x" else attempt.y.d_mm
    d_y = attempt.x.d_mm if route.axis == "y" else attempt.y.d_mm
    result.section = {
        "b_mm": STRIP_MM,
        "D_mm": depth,
        "d_mm": attempt.x.d_mm,
        "d_main_mm": attempt.x.d_mm,
        "d_distribution_mm": attempt.y.d_mm,
        "d_x_mm": d_x,
        "d_y_mm": d_y,
        "cover_mm": attempt.x.cover_mm,
        "thickness_mm": depth,
        "lx_mm": geo.lx_mm,
        "ly_mm": geo.ly_mm,
        "ly_over_lx": geo.ratio,
        "short_axis": geo.short_axis,
        "two_way": False,
        "table_26_case": 0,
        "cantilever_axis": route.axis,
        "projection_mm": route.projection_mm,
        "root_width_mm": route.across_mm,
        "backspan_mm": route.backspan_mm,
    }
    root_moment = w_line * route.projection_mm * route.projection_mm / 2.0
    root_shear = w_line * route.projection_mm
    shear_at_d = max(w_line * (route.projection_mm - attempt.x.d_mm), 0.0)
    result.extras.update(
        {
            "method": "cantilever",
            "deflection_route": attempt.deflection_route,
            "deflection_basic_ld": is456.cl_23_2_1__basic_ld("cantilever"),
            "backing_edge": route.backing_edge,
            "backing_support_ids": list(route.backing_support_ids),
            "backing_panel_id": route.backing_panel_id,
            "backspan_mm": route.backspan_mm,
            "projection_mm": route.projection_mm,
            "cantilever_axis": route.axis,
            "root_moment_nmm": root_moment,
            "root_shear_n": root_shear,
            "shear_at_d_n": shear_at_d,
            "edges": {
                tag: {
                    "continuous": geo.sides[tag].continuous,
                    "supported": geo.sides[tag].supported,
                    "role": "backing" if tag == route.backing_edge else "free_or_edge",
                }
                for tag in SIDE_TAGS
            },
        }
    )

    for note in attempt.notes:
        result.add_note(note)
    for code, message in attempt.disclosures:
        _disclose(result, code, message, clause=attempt.plan.clause)
    for row in attempt.rows:
        result.add_check(row.name, row.clause, row.demand, row.capacity, units=row.units)

    development = next(
        row for row in result.checks if row.name == "cantilever development length"
    )
    if development.status == CHECK_FAIL:
        reason = (
            "cantilever top bars require "
            + _mm_text(development.demand)
            + " development beyond "
            + route.backing_edge
            + ", but identified backing panel "
            + route.backing_panel_id
            + " provides only "
            + _mm_text(development.capacity)
        )
        _disclose(
            result,
            "E_CANTILEVER_BACKING",
            reason,
            clause="IS456:2000 26.2.1",
        )
        return result.fail_with(
            "cantilever backing support",
            reason=reason,
            clause="IS456:2000 26.2.1",
        )

    _emit_cantilever_mesh(result, attempt, route, context)
    result.finalize()
    if any(row.status == CHECK_FAIL for row in result.checks):
        result.add_note(
            "a failed cantilever check is not referred to the ordinary secondary-beam re-place "
            "route; the root/projection framing requires engineering revision"
        )
    return result


def design_slab(panel: Any, load: Any, ctx: Any = None) -> DesignResult:
    """Design one slab panel and return its DesignResult, passing or not.

    `panel` is a `model.SlabPanel` (or anything carrying its fields: id, lx_m,
    ly_m, polygon, thickness_m, two_way, edge_continuity); `load` is the
    `analysis.SlabLoad` the takedown produced for it; `ctx` is a `SlabContext`,
    an options mapping or any object carrying the same names.

    The ladder is the spec's uniform one: 10 mm at a time to 150 mm. At the cap
    the panel is NOT thickened further (finding 40): the result comes back
    designed at 150 with the outstanding span/d row visible, status `resized`,
    and an `add_secondary_beams` referral carrying the suggested spacing range.
    """
    context = slab_context(ctx)
    pressures = _load_view(load)
    geo = panel_geometry(panel)
    element_id = str(_lookup(panel, ("id",)) or "slab")

    result = DesignResult(element_id=element_id, element_type="slab")
    result.materials = materials_block(context.concrete(), context.steel())
    result.extras["slab_mode"] = "panel"

    for note in geo.notes:
        result.add_note(note)
    grade_note = check_exposure_grade(context.fck_mpa, context.exposure)
    if grade_note:
        result.add_warning(grade_note)

    if geo.lx_mm <= 0.0 or geo.ly_mm <= 0.0:
        return result.fail_with(
            "geometry",
            reason="the panel carries no span in one direction, so there is nothing to design",
            clause="IS456:2000 22.2",
        )

    if _is_cantilever_panel(panel):
        result.extras["slab_mode"] = "cantilever"
        route, refusal = _cantilever_route(panel, geo)
        if route is None:
            result.extras["method"] = "refused_cantilever"
            _disclose(
                result,
                "E_CANTILEVER_BACKING",
                refusal,
                clause="IS456:2000 26.2.1",
            )
            return result.fail_with(
                "cantilever backing support",
                reason=refusal + "; the panel is not designed as an ordinary spanning slab",
                clause="IS456:2000 26.2.1",
            )
        return _design_cantilever(panel, pressures, context, geo, result, route)

    two_way, decision_notes, decision_warnings = _two_way_decision(panel, geo)
    for note in decision_notes:
        result.add_note(note)
    for text in decision_warnings:
        result.add_warning(text)

    route = _ordinary_span_route(geo)
    if route is None:
        reason = (
            "no pair of opposite supported edges establishes an ordinary slab span, and the "
            "panel carries no resolved cantilever backing handoff"
        )
        return result.fail_with(
            "slab support topology",
            reason=reason,
            clause="IS456:2000 22.2",
        )
    if not two_way and route.axis != geo.short_axis:
        result.add_note(
            "the geometric short-span support pair is incomplete; the opposed "
            + "/".join(route.support_tags)
            + " supports make the physical "
            + route.axis
            + " direction the one-way design span at "
            + _mm_text(route.span_mm)
            + ", rather than bbox lx "
            + _mm_text(geo.lx_mm)
        )

    ll_kpa, ll_note = _imposed_for_guard(context, pressures)
    if ll_note:
        result.add_note(ll_note)

    policy = context.policy
    design_span_mm = geo.lx_mm if two_way else route.span_mm
    depth, depth_note = _initial_thickness(panel, design_span_mm, policy)
    placed_depth = _lookup(panel, ("thickness_m",))
    _record_project_minimum_resizes(
        result,
        None if placed_depth is None else float(placed_depth) * 1000.0,
        policy,
    )
    if depth_note:
        result.add_note(depth_note)
    cap_mm = max(policy.slab_cap_mm, RC_SLAB_MIN_THICKNESS_MM, depth)
    w_line = _line_load_n_per_mm(pressures.w_u_kpa)

    attempt = _panel_attempt(geo, context, depth, w_line, ll_kpa, two_way, route)
    steps = 0
    while steps < policy.max_iters:
        outstanding = attempt.failing_thickness()
        if not outstanding or depth >= cap_mm - _EPS:
            break
        nxt = min(depth + policy.slab_step_mm, cap_mm)
        if nxt <= depth + _EPS:
            break
        result.add_resize(depth, nxt, outstanding[0].name + " at D " + _mm_text(depth))
        depth = nxt
        attempt = _panel_attempt(geo, context, depth, w_line, ll_kpa, two_way, route)
        steps += 1

    # The winning thickness is re-run inside a sink so the trace carries the
    # design that is reported, not every abandoned rung of the ladder.
    entries = []  # type: List[TraceEntry]
    with trace_into(entries):
        attempt = _panel_attempt(geo, context, depth, w_line, ll_kpa, two_way, route)
    result.trace = entries

    physical_d = {attempt.x.axis: attempt.x.d_mm, attempt.y.axis: attempt.y.d_mm}
    result.section = {
        "b_mm": STRIP_MM,
        "D_mm": depth,
        "d_mm": attempt.x.d_mm,
        "d_x_mm": physical_d["x"],
        "d_y_mm": physical_d["y"],
        "cover_mm": attempt.x.cover_mm,
        "thickness_mm": depth,
        "lx_mm": geo.lx_mm,
        "ly_mm": geo.ly_mm,
        "ly_over_lx": geo.ratio,
        "short_axis": geo.short_axis,
        "two_way": two_way,
        "table_26_case": geo.case if two_way else 0,
    }
    if not two_way:
        result.section["design_span_mm"] = design_span_mm
        result.section["one_way_axis"] = route.axis
    result.extras["method"] = attempt.plan.method
    result.extras["deflection_route"] = attempt.deflection_route
    result.extras["edges"] = {
        tag: {
            "continuous": geo.sides[tag].continuous,
            "supported": geo.sides[tag].supported,
            "role": "long" if tag in geo.long_side_tags else "short",
        }
        for tag in SIDE_TAGS
    }

    for note in attempt.notes:
        result.add_note(note)
    for code, message in attempt.disclosures:
        _disclose(result, code, message, clause=attempt.plan.clause)

    main_span_mm = geo.lx_mm if two_way else route.span_mm
    main_across_mm = geo.ly_mm if two_way else route.across_mm
    _emit_mesh(result, attempt.x, main_span_mm, main_across_mm, context)
    _emit_mesh(result, attempt.y, main_across_mm, main_span_mm, context)
    _emit_corners(result, attempt.corners, context)

    for row in attempt.rows:
        result.add_check(row.name, row.clause, row.demand, row.capacity, units=row.units)
    result.finalize()

    _settle_status(result, geo, depth, cap_mm)
    return result


def _settle_status(result: DesignResult, geo: PanelGeometry, depth_mm: float, cap_mm: float) -> None:
    """Referral and final status once the ladder has stopped.

    Finding 40: a panel whose only outstanding check at the cap is span/d is
    NOT thickened past 150 mm. It comes back `resized` with the failing row
    still on the result, so the number is visible, and with the referral that
    hands it to placement for one bounded re-place pass. A panel that also
    fails a strength check keeps status `fail` and carries the same referral.
    """
    failed = [row for row in result.checks if row.status == CHECK_FAIL]
    if not failed:
        return
    thickness_driven = [row for row in failed if row.name in THICKNESS_DRIVEN_CHECKS]
    if not thickness_driven:
        return

    deflection_only = all(row.name == "deflection" for row in failed)
    result.add_referral(
        "add_secondary_beams",
        {
            "reason": "span/d" if deflection_only else thickness_driven[0].name,
            "governing_check": result.governing_check,
            "suggested_spacing_m": [SECONDARY_BEAM_SPACING_M[0], SECONDARY_BEAM_SPACING_M[1]],
            "panel_lx_m": geo.lx_mm / 1000.0,
            "panel_ly_m": geo.ly_mm / 1000.0,
            "thickness_mm": depth_mm,
        },
    )
    _disclose(
        result,
        "W_THICK_SLAB",
        "the ladder stopped at "
        + _mm_text(depth_mm)
        + " (cap "
        + _mm_text(cap_mm)
        + ") with "
        + result.governing_check
        + " still outstanding, so the panel is not thickened further; secondary beams at "
        + ("%.1f" % SECONDARY_BEAM_SPACING_M[0])
        + " to "
        + ("%.1f" % SECONDARY_BEAM_SPACING_M[1])
        + " m are referred to placement instead",
        clause="IS456:2000 24.1",
    )
    if deflection_only:
        result.status = STATUS_RESIZED
        result.add_warning(
            "status is resized, not fail, while the span/d row still reads over 1.0: the deflection "
            "shortfall is answered by the add_secondary_beams referral, not by more thickness "
            "(spec 05 section 5.5, critic finding 40). The row is left on the result so the "
            "shortfall is visible rather than hidden by the referral."
        )


# ---------------------------------------------------------------------------
# stair mode (critic finding 40): the flight as an inclined one-way slab
# ---------------------------------------------------------------------------

#: Riser the step geometry is derived with when the caller states none, m. The
#: flight's total rise is divided into whole steps as close to this as it goes,
#: so the step triangles weigh what the real flight's steps weigh.
STAIR_TARGET_RISER_M = 0.15


class _StairGeometry(NamedTuple):
    """The flight as the designer reads it, all in mm except the angles."""

    span_mm: float
    width_mm: float
    rise_mm: float
    incline_deg: float
    steps: int
    riser_mm: float
    going_mm: float


def _stair_geometry(stair: Any, ctx: SlabContext) -> _StairGeometry:
    """Span, width and step geometry from a `placement/cores.py` StairSlab."""
    span_mm = float(_lookup(stair, ("span_m",)) or 0.0) * 1000.0
    width_mm = float(_lookup(stair, ("width_m",)) or 0.0) * 1000.0
    rise_mm = float(_lookup(stair, ("rise_m",)) or 0.0) * 1000.0
    incline = _lookup(stair, ("incline_deg",))
    if incline is None:
        incline = math.degrees(math.atan2(rise_mm, span_mm)) if span_mm > 0.0 else 0.0
    riser_hint = _lookup(ctx, ("riser_mm",))
    if riser_hint:
        steps = max(1, int(round(rise_mm / float(riser_hint)))) if rise_mm > 0.0 else 1
    else:
        steps = max(1, int(round(rise_mm / (STAIR_TARGET_RISER_M * 1000.0)))) if rise_mm > 0.0 else 1
    riser = rise_mm / steps if steps else 0.0
    going = span_mm / steps if steps else 0.0
    return _StairGeometry(
        span_mm=span_mm,
        width_mm=width_mm,
        rise_mm=rise_mm,
        incline_deg=float(incline),
        steps=steps,
        riser_mm=riser,
        going_mm=going,
    )


class _StairLoad(NamedTuple):
    """The design pressure on the plan projection of the flight, kPa."""

    applied_u_kpa: float
    waist_u_kpa: float
    steps_u_kpa: float
    total_u_kpa: float


def _stair_load(
    geo: _StairGeometry,
    waist_mm: float,
    pressures: SlabLoad,
    ctx: SlabContext,
) -> _StairLoad:
    """Factored plan pressure: what the takedown handed over plus the waist.

    A waist chosen here did not exist when the takedown ran, so its weight and
    the weight of the step triangles are added to the pressure the load record
    carries, both projected onto plan: the waist is measured along the incline
    (t / cos theta) and the triangles average a thickness of half a riser over
    the going. The imposed load is already a plan pressure and passes straight
    through. `stair_self_weight_included` turns the addition off for a caller
    whose takedown already carried the designed waist.
    """
    cos_theta = math.cos(math.radians(geo.incline_deg))
    cos_theta = cos_theta if cos_theta > 0.05 else 0.05
    waist_kpa = CONCRETE_DENSITY_KNM3 * (waist_mm / 1000.0) / cos_theta
    steps_kpa = CONCRETE_DENSITY_KNM3 * (0.5 * geo.riser_mm / 1000.0)
    if ctx.stair_self_weight_included:
        waist_kpa = 0.0
        steps_kpa = 0.0
    waist_u = DEAD_LOAD_FACTOR * waist_kpa
    steps_u = DEAD_LOAD_FACTOR * steps_kpa
    applied = float(pressures.w_u_kpa)
    return _StairLoad(
        applied_u_kpa=applied,
        waist_u_kpa=waist_u,
        steps_u_kpa=steps_u,
        total_u_kpa=applied + waist_u + steps_u,
    )


def _stair_attempt(geo: _StairGeometry, ctx: SlabContext, waist_mm: float, pressures: SlabLoad) -> _Attempt:
    """Design the flight at one waist. Pure, so the ladder can call it again."""
    loads = _stair_load(geo, waist_mm, pressures, ctx)
    w_line = _line_load_n_per_mm(loads.total_u_kpa)
    span = geo.span_mm
    mu = w_line * span * span / 8.0

    plan = _MomentPlan(
        stations=(_Station(tag="mid", axis="main", face="bottom", mu_nmm=mu),),
        method="ss",
        clause="IS456:2000 22.2",
        notes=(
            "the flight is designed as a simply supported inclined one-way slab spanning between "
            "the landing beams, w L^2 / 8 on the plan projection of the span",
        ),
        disclosures=(),
    )

    def depth_main(dia_mm: int, cover_mm: float) -> float:
        return waist_mm - cover_mm - 0.5 * float(dia_mm)

    main = _size_direction("main", plan.stations, waist_mm, depth_main, ctx, "slab_main")

    def depth_dist(dia_mm: int, _cover_mm: float) -> float:
        return main.d_mm - 0.5 * float(main.dia_mm) - 0.5 * float(dia_mm)

    dist = _size_direction(
        "distribution",
        (_Station(tag="mid", axis="distribution", face="bottom", mu_nmm=0.0),),
        waist_mm,
        depth_dist,
        ctx,
        "slab_distribution",
    )

    attempt = _Attempt(depth_mm=waist_mm, two_way=False, plan=plan, x=main, y=dist)
    attempt.notes.extend(plan.notes)
    attempt.notes.append(
        "step geometry: "
        + str(geo.steps)
        + " risers of "
        + _mm_text(geo.riser_mm)
        + " over a going of "
        + _mm_text(geo.going_mm)
        + " at "
        + ("%.1f" % geo.incline_deg)
        + " degrees"
    )
    if ctx.stair_self_weight_included:
        attempt.notes.append(
            "the caller states the load record already carries the flight's own weight, so no "
            "waist or step weight is added here"
        )
    else:
        attempt.notes.append(
            "self weight added to the "
            + _kpa(loads.applied_u_kpa)
            + " the load record carries: waist along the incline "
            + _kpa(loads.waist_u_kpa)
            + " and step triangles "
            + _kpa(loads.steps_u_kpa)
            + " (factored), because the waist is chosen here and did not exist when the takedown ran"
        )

    for direction in (main, dist):
        label = " " + direction.axis
        mu_max = max([m.mu_nmm for m in direction.meshes] or [0.0])
        mu_lim = direction.meshes[0].mu_lim_nmm if direction.meshes else 0.0
        attempt.rows.append(_Row("flexure" + label, "IS456:2000 G-1.1(b)", mu_max, mu_lim, "N.mm"))
        demand, capacity = _worst_by_ratio(
            direction.meshes, lambda m: m.ast_des_mm2, lambda m: m.ast_prov_mm2
        )
        attempt.rows.append(_Row("steel" + label, "IS456:2000 G-1.1(a)", demand, capacity, "mm2/m"))
        pitch, allowed = direction.worst_ratio_spacing()
        attempt.rows.append(_Row("bar spacing" + label, "IS456:2000 26.3.3", pitch, allowed, "mm"))

    ast_min = main.meshes[0].ast_min_mm2 if main.meshes else 0.0
    provided_min = min([m.ast_prov_mm2 for m in list(main.meshes) + list(dist.meshes)] or [0.0])
    attempt.rows.append(_Row("min steel", "IS456:2000 26.5.2.1", ast_min, provided_min, "mm2/m"))

    mid = main.mesh("mid", "bottom")
    ast_mid = mid.ast_prov_mm2 if mid is not None else 0.0
    vu_n = max(w_line * (0.5 * span - main.d_mm), 0.0)
    tau_v = is456.cl_40_1__tau_v(vu_n, STRIP_MM, main.d_mm)
    pt = 100.0 * ast_mid / (STRIP_MM * main.d_mm)
    tau_c = is456.table_19__tau_c(pt, ctx.fck_mpa)
    k_depth = is456.cl_40_2_1_1__k_solid_slab(waist_mm)
    attempt.rows.append(_Row("shear", "IS456:2000 40.2.1.1", tau_v, k_depth * tau_c, "MPa"))
    tau_c_max = is456.table_20__tau_c_max(ctx.fck_mpa)
    attempt.rows.append(_Row("shear cap", "IS456:2000 40.2.3.1", tau_v, 0.5 * tau_c_max, "MPa"))

    basic = is456.cl_23_2_1__basic_ld("simply_supported")
    req = mid.ast_des_mm2 if mid is not None else 0.0
    prov = ast_mid if ast_mid > 0.0 else 1.0
    fs = is456.cl_23_2_1__fs(ctx.fy_mpa, req, prov)
    mf = is456.fig_4__mf_tension(fs, 100.0 * prov / (STRIP_MM * main.d_mm))
    long_span = is456.cl_23_2_1_c__long_span_factor(span / 1000.0)
    attempt.rows.append(
        _Row("deflection", "IS456:2000 23.2.1", span / main.d_mm, basic * mf * long_span, "span/d")
    )
    attempt.deflection_route = "cl_23_2_1"
    return attempt


def design_stair_flight(stair: Any, load: Any, ctx: Any = None) -> DesignResult:
    """Design one stair flight as an inclined one-way slab (critic finding 40).

    `stair` is a `placement/cores.py` StairSlab (or anything carrying span_m,
    width_m, rise_m and incline_deg). The waist starts at the greater of
    span/20 and the 150 mm project minimum, then walks the slab ladder; a
    flight cannot be handed secondary beams, so its cap is span/12 (but never
    below that minimum) and it fails rather than referring.
    """
    context = slab_context(ctx)
    pressures = _load_view(load)
    geo = _stair_geometry(stair, context)
    element_id = str(_lookup(stair, ("id",)) or "stair")

    result = DesignResult(element_id=element_id, element_type="slab")
    result.materials = materials_block(context.concrete(), context.steel())
    result.extras["slab_mode"] = "stair_flight"

    grade_note = check_exposure_grade(context.fck_mpa, context.exposure)
    if grade_note:
        result.add_warning(grade_note)

    if geo.span_mm <= 0.0:
        return result.fail_with(
            "geometry",
            reason="the flight carries no span, so there is nothing to design",
            clause="IS456:2000 33.1",
        )

    policy = context.policy
    waist = max(
        round_up_mm(geo.span_mm / STAIR_WAIST_SPAN_RATIO, policy.slab_step_mm), STAIR_WAIST_MIN_MM
    )
    cap_mm = max(geo.span_mm / STAIR_WAIST_CAP_RATIO, waist)
    result.add_note(
        "waist starts at span/"
        + str(int(STAIR_WAIST_SPAN_RATIO))
        + " ("
        + _mm_text(waist)
        + ") and may walk the "
        + _mm_text(policy.slab_step_mm)
        + " ladder to span/"
        + str(int(STAIR_WAIST_CAP_RATIO))
        + " ("
        + _mm_text(cap_mm)
        + "); a flight cannot be split by secondary beams, so it has its own cap"
    )

    attempt = _stair_attempt(geo, context, waist, pressures)
    steps = 0
    while steps < policy.max_iters:
        outstanding = attempt.failing_thickness()
        if not outstanding or waist >= cap_mm - _EPS:
            break
        nxt = min(waist + policy.slab_step_mm, cap_mm)
        if nxt <= waist + _EPS:
            break
        result.add_resize(waist, nxt, outstanding[0].name + " at waist " + _mm_text(waist))
        waist = nxt
        attempt = _stair_attempt(geo, context, waist, pressures)
        steps += 1

    entries = []  # type: List[TraceEntry]
    with trace_into(entries):
        attempt = _stair_attempt(geo, context, waist, pressures)
    result.trace = entries

    loads = _stair_load(geo, waist, pressures, context)
    result.section = {
        "b_mm": STRIP_MM,
        "D_mm": waist,
        "d_mm": attempt.x.d_mm,
        "d_main_mm": attempt.x.d_mm,
        "d_distribution_mm": attempt.y.d_mm,
        "cover_mm": attempt.x.cover_mm,
        "waist_mm": waist,
        "span_mm": geo.span_mm,
        "width_mm": geo.width_mm,
        "rise_mm": geo.rise_mm,
        "incline_deg": geo.incline_deg,
        "risers": geo.steps,
        "riser_mm": geo.riser_mm,
        "going_mm": geo.going_mm,
    }
    result.extras["method"] = attempt.plan.method
    result.extras["deflection_route"] = attempt.deflection_route
    result.extras["design_pressure_kpa"] = {
        "applied_u_kpa": loads.applied_u_kpa,
        "waist_u_kpa": loads.waist_u_kpa,
        "steps_u_kpa": loads.steps_u_kpa,
        "total_u_kpa": loads.total_u_kpa,
    }

    for note in attempt.notes:
        result.add_note(note)
    result.add_note(
        "landing check: the landings at each end and the landing beams under them are separate "
        "elements. This result covers the inclined flight only; the landing slab must be designed "
        "for the flight end reaction of "
        + ("%.2f" % (0.5 * loads.total_u_kpa * geo.span_mm / 1000.0))
        + " kN per metre of flight width applied at its edge, per IS 456 Cl 33.1 and 33.2"
    )

    _emit_mesh(result, attempt.x, geo.span_mm, geo.width_mm, context)
    _emit_mesh(result, attempt.y, geo.width_mm, geo.span_mm, context)

    for row in attempt.rows:
        result.add_check(row.name, row.clause, row.demand, row.capacity, units=row.units)
    result.finalize()

    outstanding = attempt.failing_thickness()
    if outstanding and waist >= cap_mm - _EPS:
        result.add_warning(
            "the waist reached its span/"
            + str(int(STAIR_WAIST_CAP_RATIO))
            + " cap of "
            + _mm_text(cap_mm)
            + " with "
            + outstanding[0].name
            + " still outstanding; a flight cannot be handed secondary beams, so this is reported "
            + "as a failure for an engineer to answer with a deeper landing beam layout or a "
            + "stringer"
        )
    return result
