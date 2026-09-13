"""Reinforced concrete design: beams, columns, slabs, footings, detailing.

The member designers take the shapes `analysis/__init__.py` hands out
(`BeamForces`, `ColumnForces`, `SlabLoad`, and the footing loads foundations
sizes from) plus a geometry and a `detailing.DesignContext`, and each returns
the one `design/common.py` `DesignResult`. `run_rcc_design` walks a model and
its analysis and returns one result per element, in element kind then id order.

**Two rosters, not one.** Beams and columns are force-driven: an element with no
force envelope has no demand and is designed off the envelope index. Slabs and
footings are GEOMETRY-driven: the slab designer's first argument is the panel
and the footing designer's is the pad, so both are walked off the MODEL and the
analysis is read for their loads only. That distinction is what lets a combined
footing be designed at all: `layout_foundations` merges two column stacks into
one rectangle that carries no envelope of its own, so a walk over envelopes
would silently skip it. Any element that appears on one roster and not the other
still comes back, disclosed.

**The designers are called by their shipped signatures**, which are not uniform
and are not made uniform here: `design_beam(forces, geom, ctx)`,
`design_column(forces, geom, ctx)`, `design_slab(panel, load, ctx)`,
`design_stair_flight(stair, load, ctx)`,
`design_footing(pad, loads, soil, ctx)`,
`design_strip_footing(strip, line_loads, soil, ctx)` and
`design_combined_footing(rect, [loads], soil, ctx)`. The soil comes from the
options block's `soil` key (spec 05 section 11), because a footing is sized
against the ground and nothing else in the options carries it.

A strip footing is the one footing whose demand is not a column reaction: it
carries a LINE load in kN per metre, which the takedown states per wall in
`footing_loads["walls"]`, so the strip route reads that ledger and the model's
walls rather than the column roster.

Every member module is imported lazily, inside the function that needs it. Two
reasons: the members land in separate changes, so a sibling that is not written
yet has to degrade into a disclosed failure rather than an ImportError at package
import; and a caller that wants only beams should not pay for the column
interaction sweep or the footing soil tables. The one eager import is
`design/common.py`, at the bottom, to register the RC designer for the material
dispatch: importing this package already means RC design is wanted.

Nothing here raises per element. A designer that is not present, that throws on a
member the pipeline should never have produced, or that cannot be fed at all
(a footing with no takedown load, a beam with no section) comes back as a
`DesignResult` with status `fail`, the reason in `warnings`, and the element
still on the list, because a batch that silently loses members is worse than a
batch that says which ones it could not design.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "design_beam",
    "design_column",
    "design_slab",
    "design_stair_flight",
    "design_footing",
    "design_strip_footing",
    "design_combined_footing",
    "run_rcc_design",
    "strip_geometry_from_model",
    "stair_design_inputs",
    "stair_flights_from_model",
    "beam_support_condition",
    "MEMBER_KINDS",
    "UNDESIGNED_FOOTING_KINDS",
]

#: The element types `run_rcc_design` dispatches on, in the order it reports
#: them: results are grouped by this order and then sorted by element id.
MEMBER_KINDS = ("beam", "column", "slab", "footing")

#: Footing kinds the v1 RC layer places but does not design, and why. A model
#: `strap` element is the strap BEAM tying two pads together, and the pad it
#: serves carries the `strap_required` referral with the moment balance. A
#: `strip` is NOT on this list any more: `footings.design_strip_footing` designs
#: it, plain or reinforced, off the takedown's wall line loads.
UNDESIGNED_FOOTING_KINDS = {
    "strap": (
        "the strap beam is not designed in this version: it is placed and sized by "
        "placement/foundations.py, and the eccentric pad it serves carries the "
        "strap_required referral with the moment balance"
    ),
}

_STAGE = "design.rcc"

#: Fallback storey height, m, for a column whose storey the model does not carry
#: and whose envelope states no unsupported length. Disclosed on the result.
_FALLBACK_STOREY_HEIGHT_M = 3.0

#: IS 875 gravity combination factor used for the flight's imposed pressure.
#: The stair designer adds the factored waist and step dead loads itself.
_STAIR_IMPOSED_ULS_FACTOR = 1.5


# ---------------------------------------------------------------------------
# the member designers, lazily imported, called by their own signatures
# ---------------------------------------------------------------------------


def design_beam(forces: Any, geom: Any, ctx: Any = None):
    """Design one RC beam (design/rcc/beams.py)."""
    from .beams import design_beam as _design_beam

    return _design_beam(forces, geom, ctx)


def design_column(forces: Any, geom: Any, ctx: Any = None):
    """Design one RC column (design/rcc/columns.py)."""
    from .columns import design_column as _design_column

    return _design_column(forces, geom, ctx)


def design_slab(panel: Any, load: Any, ctx: Any = None):
    """Design one RC slab panel (design/rcc/slabs.py). Panel first, then load."""
    from .slabs import design_slab as _design_slab

    return _design_slab(panel, load, ctx)


def design_stair_flight(stair: Any, load: Any, ctx: Any = None):
    """Design one inclined RC stair flight (design/rcc/slabs.py)."""
    from .slabs import design_stair_flight as _design_stair

    return _design_stair(stair, load, ctx)


def design_footing(footing: Any, loads: Any, soil: Any = None, ctx: Any = None):
    """Design one isolated or strap RC pad (design/rcc/footings.py)."""
    from .footings import design_footing as _design_footing

    return _design_footing(footing, loads, soil, ctx)


def design_strip_footing(footing: Any, loads: Any, soil: Any = None, ctx: Any = None):
    """Design one wall strip footing (design/rcc/footings.py)."""
    from .footings import design_strip_footing as _design_strip

    return _design_strip(footing, loads, soil, ctx)


def design_combined_footing(footing: Any, loads: Any, soil: Any = None, ctx: Any = None):
    """Design one two-column combined footing (design/rcc/footings.py)."""
    from .footings import design_combined_footing as _design_combined

    return _design_combined(footing, loads, soil, ctx)


# ---------------------------------------------------------------------------
# results that are not designs
# ---------------------------------------------------------------------------


def _failed_result(element_id: str, element_type: str, reason: str, check: str = "designer"):
    """A fully populated failure, so a batch never loses an element silently."""
    from ..common import DesignResult

    result = DesignResult(element_id=str(element_id), element_type=str(element_type))
    result.add_warning(reason)
    return result.fail_with(str(check), reason="")


def _skipped_result(element_id: str, element_type: str, reason: str, code: str = "N_ELEMENT_UNDESIGNED"):
    """A placed element the v1 RC layer does not design, said out loud.

    `N_ELEMENT_UNDESIGNED` names the real condition, "placed and quantified, but
    no designer reached it", which is the same code `api._disclose_undesigned`
    uses; neither borrows `N_SHAFT_WALL_UNDESIGNED` ("shaft walls carry a
    prescription, not a design") any more, because that means something else.
    The entry lands structured in `extras["disclosures"]` and its text is
    mirrored into `warnings`, which is where the report reads it.
    """
    from ...model import make_disclosure

    result = _failed_result(element_id, element_type, reason, check="not designed")
    entry = make_disclosure(code, reason, [str(element_id)], stage=_STAGE)
    result.extras.setdefault("disclosures", []).append(entry.to_dict())
    return result


# ---------------------------------------------------------------------------
# reading the model and the analysis
# ---------------------------------------------------------------------------


def _elements(model: Any, name: str) -> List[Any]:
    """`model.<name>` as a list; empty when the model does not carry the slot."""
    return list(getattr(model, name, None) or [])


def stair_flights_from_model(model: Any) -> List[Dict[str, Any]]:
    """Placed stair-flight records from frame placement, unique and id sorted.

    Flights are real placed elements, but they live under frame-placement meta
    rather than ``model.slabs`` because the latter contains horizontal panels.
    Keep this one reader shared by the package facade and the API orchestrator
    so design, coverage and quantities all see the same roster.
    """
    meta = getattr(model, "meta", None) or {}
    if not isinstance(meta, Mapping):
        return []
    frame = meta.get("frame_placement") or {}
    if not isinstance(frame, Mapping):
        return []
    flights = {}  # type: Dict[str, Dict[str, Any]]
    for raw in frame.get("stair_slabs") or []:
        if not isinstance(raw, Mapping):
            continue
        record = dict(raw)
        element_id = str(record.get("id", ""))
        if element_id:
            flights.setdefault(element_id, record)
    return [flights[element_id] for element_id in sorted(flights)]


def stair_design_inputs(ctx: Any = None) -> Tuple[Any, Any]:
    """The synthetic load and stair-specific context for one placed flight.

    Takedown loads the core floor occupancy but emits no flight envelope. The
    flight therefore receives the IS 875 corridor/stair imposed pressure here:
    3.0 kPa service and 1.5 x 3.0 = 4.5 kPa ultimate. Its waist and step dead
    loads are deliberately absent because ``design_stair_flight`` calculates
    and factors them after choosing the waist.
    """
    from dataclasses import replace

    from ...analysis import SlabLoad
    from ...codes import is875
    from .slabs import slab_context

    imposed_kpa = float(is875.part2_imposed("corridor_stair"))
    load = SlabLoad(
        w_u_kpa=_STAIR_IMPOSED_ULS_FACTOR * imposed_kpa,
        w_service_kpa=imposed_kpa,
    )
    context = replace(
        slab_context(ctx),
        imposed_kpa=imposed_kpa,
        dead_kpa=None,
        stair_self_weight_included=False,
    )
    return (load, context)


def _envelope_index(analysis: Any) -> Dict[Tuple[str, str], Any]:
    """{(element_type, element_id): envelope} from an AnalysisResult or a list.

    `analysis.envelopes` is the takedown's dict keyed by element id; a bare list
    or an iterable of envelopes is accepted too, so a caller with one element in
    hand does not have to build a result object around it.
    """
    envelopes = getattr(analysis, "envelopes", None)
    if envelopes is None:
        envelopes = analysis
    if isinstance(envelopes, Mapping):
        envelopes = [envelopes[key] for key in sorted(envelopes)]
    index = {}  # type: Dict[Tuple[str, str], Any]
    for envelope in list(envelopes or []):
        key = (str(getattr(envelope, "element_type", "")), str(getattr(envelope, "element_id", "")))
        index.setdefault(key, envelope)
    return index


def _stack_service_loads(analysis: Any) -> Dict[str, float]:
    """{column stack id: service axial kN} from the takedown's footing ledger.

    `layout_foundations` may merge two stacks into one rectangle, so the per
    stack ledger is the only reading that survives the merge; the takedown
    documents it as `footing_loads["columns"][stack] = {p_dl_kn,
    p_ll_reduced_kn}` and the service value a footing is sized on is their sum.
    """
    ledger = getattr(analysis, "footing_loads", None) or {}
    if not isinstance(ledger, Mapping):
        return {}
    columns = ledger.get("columns") or {}
    if not isinstance(columns, Mapping):
        return {}
    out = {}  # type: Dict[str, float]
    for key in sorted(columns, key=str):
        row = columns[key]
        if not isinstance(row, Mapping):
            continue
        out[str(key)] = float(row.get("p_dl_kn", 0.0) or 0.0) + float(
            row.get("p_ll_reduced_kn", 0.0) or 0.0
        )
    return out


def _wall_line_loads(analysis: Any) -> Dict[str, float]:
    """{wall id: service line load kN per metre} from the takedown's footing ledger.

    The takedown documents it as `footing_loads["walls"][wall_id] = {n_dl_kn_m,
    n_ll_raw_kn_m, n_ll_kn_m, ...}`, keyed by the GROUND wall of each stack and
    already carrying everything the storeys above put on it, divided by the wall
    length. The service value a strip is sized on is the dead plus the REDUCED
    imposed part, which is the same sum `api._foundation_loads` hands
    `layout_foundations`, so the placer and the designer read one number.
    """
    ledger = getattr(analysis, "footing_loads", None) or {}
    if not isinstance(ledger, Mapping):
        return {}
    walls = ledger.get("walls") or {}
    if not isinstance(walls, Mapping):
        return {}
    out = {}  # type: Dict[str, float]
    for key in sorted(walls, key=str):
        row = walls[key]
        if not isinstance(row, Mapping):
            continue
        out[str(key)] = float(row.get("n_dl_kn_m", 0.0) or 0.0) + float(row.get("n_ll_kn_m", 0.0) or 0.0)
    return out


def strip_geometry_from_model(footing: Any, walls: Mapping[str, Any]) -> Any:
    """The `footings.StripGeometry` for one placed strip, read off the model.

    A model `Footing` of kind `strip` carries the rectangle the placer laid
    (`w_m` x `h_m` about `x_m, y_m`) and, in `supports`, the ids of the bearing
    walls the run covers. Which of the two rectangle dimensions is the WIDTH is
    decided by the walls, not guessed from which is smaller: a wall running along
    x makes the strip's y dimension its width, and a short heavily loaded run can
    legitimately be wider than it is long.

    `Footing.depth_m` is deliberately NOT read: for a strip the placer stores the
    FOUNDING depth there, how far below ground the strip sits, not a footing
    thickness, and the designer computes the thickness itself.
    """
    from .footings import StripGeometry

    members = [walls[key] for key in sorted(str(one) for one in (getattr(footing, "supports", None) or [])) if key in walls]
    thickness = max([float(getattr(one, "thickness_m", 0.0) or 0.0) for one in members] or [0.0])
    along_x = 0.0
    along_y = 0.0
    for wall in members:
        a = getattr(wall, "a", (0.0, 0.0))
        b = getattr(wall, "b", (0.0, 0.0))
        along_x = max(along_x, abs(float(b[0]) - float(a[0])))
        along_y = max(along_y, abs(float(b[1]) - float(a[1])))
    orient = "h" if along_x >= along_y else "v"
    w_m = abs(float(getattr(footing, "w_m", 0.0) or 0.0))
    h_m = abs(float(getattr(footing, "h_m", 0.0) or 0.0))
    width_m, length_m = (h_m, w_m) if orient == "h" else (w_m, h_m)
    return StripGeometry(
        element_id=str(getattr(footing, "id", "")),
        wall_t_m=thickness,
        length_m=length_m,
        placed_width_m=width_m or None,
        wall_ids=tuple(str(one) for one in (getattr(footing, "supports", None) or [])),
        orient=orient,
        # A boundary strip arrives flushed inside the line: the placer stamps
        # the offset on the model footing and the designer must see it.
        eccentric=bool(getattr(footing, "eccentric", False)),
        e_m=float(getattr(footing, "e_m", 0.0) or 0.0),
    )


def _soil_of(options: Any) -> Any:
    """The options block's `soil`, which `SoilProfile.from_params` reads.

    Spec 05 section 11 puts it there as `{sbc_kpa}` or `{c, phi, gamma, Df,
    gwt}`; the api request's frozen `{type, sbc_kpa, soft, founding_depth_m}`
    (finding 30) is the same shape from the profile's point of view. None means
    the soil catalogue defaults, which the footing designer discloses itself.
    """
    if options is None:
        return None
    if isinstance(options, Mapping):
        return options.get("soil")
    return getattr(options, "soil", None)


def _storey_height_m(model: Any, index: Any) -> Optional[float]:
    """Floor to floor height of one storey, or None when the model has none."""
    try:
        level = int(index)
    except (TypeError, ValueError):
        return None
    lookup = getattr(model, "storey", None)
    storey = None
    if callable(lookup):
        try:
            storey = lookup(level)
        except Exception:  # a duck that does not answer is simply not asked twice
            storey = None
    if storey is None:
        for candidate in _elements(model, "storeys"):
            if int(getattr(candidate, "index", -1)) == level:
                storey = candidate
                break
    if storey is None:
        return None
    height = getattr(storey, "height_m", None)
    return float(height) if height else None


# ---------------------------------------------------------------------------
# geometry, in the design layer's millimetres
# ---------------------------------------------------------------------------


def beam_support_condition(beam: Any, forces: Any = None) -> str:
    """Beam design support from placement kind and analysed end continuity.

    A placed cantilever is fixed by its kind.  For every other run, zero
    hogging demand at both analysed ends is the simply supported route; any
    end continuity makes the run continuous.  With no force record the old
    continuous default is retained for backward compatibility.
    """
    kind = getattr(beam, "kind", "")
    kind = str(getattr(kind, "value", kind) or "").strip().lower()
    if kind == "cantilever":
        return "cantilever"
    if forces is None:
        return "continuous"
    if isinstance(forces, Mapping):
        hog_a = forces.get("mu_hog_end_a_knm", forces.get("mu_hog_a_knm", 0.0))
        hog_b = forces.get("mu_hog_end_b_knm", forces.get("mu_hog_b_knm", 0.0))
    else:
        hog_a = getattr(forces, "mu_hog_end_a_knm", getattr(forces, "mu_hog_a_knm", 0.0))
        hog_b = getattr(forces, "mu_hog_end_b_knm", getattr(forces, "mu_hog_b_knm", 0.0))
    if abs(float(hog_a or 0.0)) <= 1.0e-9 and abs(float(hog_b or 0.0)) <= 1.0e-9:
        return "ss"
    return "continuous"


def _beam_geometry(beam: Any, forces: Any = None) -> Optional[Dict[str, Any]]:
    """The mapping `beams.as_beam_geometry` documents, or None when unbuildable."""
    from ..common import m_to_mm

    width = getattr(beam, "width_m", None)
    depth = getattr(beam, "depth_m", None)
    span = beam.span_m() if hasattr(beam, "span_m") else None
    if not width or not depth or not span:
        return None
    return {
        "element_id": str(getattr(beam, "id", "")),
        "b_mm": m_to_mm(float(width)),
        "D_mm": m_to_mm(float(depth)),
        "span_mm": m_to_mm(float(span)),
        "storey": int(getattr(beam, "storey", 0) or 0),
        "support": beam_support_condition(beam, forces),
    }


def _column_geometry(column: Any, height_m: Optional[float]) -> Optional[Dict[str, Any]]:
    """The mapping `columns.column_geometry` documents, or None when unbuildable.

    The height is stated rather than left to the forces: `column_geometry` will
    fall back to the envelope's unsupported length, and a column whose envelope
    carries none would otherwise be refused for having no height at all.
    """
    from ..common import m_to_mm

    width = getattr(column, "width_m", None)
    depth = getattr(column, "depth_m", None)
    if not width or not depth or not height_m:
        return None
    return {
        "element_id": str(getattr(column, "id", "")),
        "b_mm": m_to_mm(float(width)),
        "depth_mm": m_to_mm(float(depth)),
        "height_mm": m_to_mm(float(height_m)),
        "clear_height_mm": m_to_mm(float(height_m)),
        "storey": int(getattr(column, "storey", 0) or 0),
    }


def _column_stub(column: Any):
    """The `footings.ColumnStub` for one placed column: section and plan position."""
    from ..common import m_to_mm
    from .footings import ColumnStub

    return ColumnStub(
        column_id=str(getattr(column, "id", "")),
        bx_mm=m_to_mm(float(getattr(column, "width_m", 0.0) or 0.0)),
        dy_mm=m_to_mm(float(getattr(column, "depth_m", 0.0) or 0.0)),
        x_m=float(getattr(column, "x_m", 0.0) or 0.0),
        y_m=float(getattr(column, "y_m", 0.0) or 0.0),
    )


def _footing_kind(footing: Any) -> str:
    """The footing kind as a plain word, whether it is an enum or a string."""
    kind = getattr(footing, "kind", "isolated")
    return str(getattr(kind, "value", kind) or "isolated").strip().lower()


def _placed_m(footing: Any, name: str) -> Optional[float]:
    """One placed dimension in metres, with zero read as nothing stated.

    `PadGeometry.from_pad_footing` takes the same reading: a placed size is the
    starting point of the depth ladder, and a zero is the placer saying it never
    sized this footing, not a footing with no width.
    """
    value = getattr(footing, name, None)
    return float(value) if value else None


def _lowest_by_stack(columns: Sequence[Any]) -> Dict[str, Any]:
    """{stack id: the lowest column of that stack}, the one that bears on a pad."""
    out = {}  # type: Dict[str, Any]
    for column in columns:
        key = str(getattr(column, "stack_id", "") or getattr(column, "id", ""))
        current = out.get(key)
        if current is None or _stack_order(column) < _stack_order(current):
            out[key] = column
    return out


def _stack_order(column: Any) -> Tuple[int, str]:
    return (int(getattr(column, "storey", 0) or 0), str(getattr(column, "id", "")))


def _bearing_columns(
    footing: Any, columns_by_id: Mapping[str, Any], columns_by_stack: Mapping[str, Any]
) -> List[Any]:
    """One column per stack the footing carries, lowest storey first.

    `Footing.supports` lists every column id the placer merged into the footing,
    which on a multi-storey stack is one id per storey. A footing carries a
    STACK, not a column per storey, so the roster is deduplicated on stack id and
    the lowest column of each stack (the one that actually bears on the pad) is
    the representative. A support named by its stack rather than by a column id
    resolves too, which is what a model rebuilt from the wire can carry. Order is
    by plan position, so the two columns of a combined rectangle always arrive in
    the same order.
    """
    by_stack = {}  # type: Dict[str, Any]
    for support in sorted(str(one) for one in (getattr(footing, "supports", None) or [])):
        column = columns_by_id.get(support) or columns_by_stack.get(support)
        if column is None:
            continue
        key = str(getattr(column, "stack_id", "") or getattr(column, "id", ""))
        current = by_stack.get(key)
        if current is None or _stack_order(column) < _stack_order(current):
            by_stack[key] = column
    return [
        by_stack[key]
        for key in sorted(
            by_stack,
            key=lambda k: (
                float(getattr(by_stack[k], "x_m", 0.0) or 0.0),
                float(getattr(by_stack[k], "y_m", 0.0) or 0.0),
                str(k),
            ),
        )
    ]


def _service_load_kn(
    footing: Any,
    column: Any,
    columns_on_footing: int,
    envelopes: Mapping[Tuple[str, str], Any],
    stack_loads: Mapping[str, float],
) -> Optional[float]:
    """Service axial at one column of a footing, kN, or None when unknown.

    A footing carrying exactly one stack has an envelope of its own, keyed by the
    footing id, and that envelope IS the takedown's reading. A merged rectangle
    has none, so the per stack ledger answers instead; the two carry the same
    number by construction, the ledger simply survives the merge.
    """
    if columns_on_footing == 1:
        envelope = envelopes.get(("footing", str(getattr(footing, "id", ""))))
        if envelope is not None:
            from .footings import FootingLoads

            return float(FootingLoads.from_envelope(envelope).p_service_kn)
    for key in (getattr(column, "stack_id", ""), getattr(column, "id", "")):
        if key and str(key) in stack_loads:
            return float(stack_loads[str(key)])
    return None


def _straps_by_footing(footings: Sequence[Any]) -> Dict[str, Tuple[str, float]]:
    """{pad id: (partner pad id, strap span m)} from the placed strap elements.

    A model footing of kind `strap` is the beam, and its `supports` are the two
    PAD ids it ties. The pad at each end is designed as a strap pad, which is
    what raises its reaction to P S / (S - e) and emits the `strap_required`
    referral; the beam itself has no v1 designer.
    """
    out = {}  # type: Dict[str, Tuple[str, float]]
    for footing in footings:
        if _footing_kind(footing) != "strap":
            continue
        ends = [str(one) for one in (getattr(footing, "supports", None) or [])]
        if len(ends) != 2:
            continue
        width = abs(float(getattr(footing, "w_m", 0.0) or 0.0))
        height = abs(float(getattr(footing, "h_m", 0.0) or 0.0))
        span = (width * width + height * height) ** 0.5
        out.setdefault(ends[0], (ends[1], span))
        out.setdefault(ends[1], (ends[0], span))
    return out


# ---------------------------------------------------------------------------
# per kind dispatch
# ---------------------------------------------------------------------------


def _design_one_beam(beam: Any, envelope: Any, ctx: Any):
    """One beam: the envelope through `to_beam_forces`, the placed section as geom."""
    from ...analysis import to_beam_forces

    element_id = str(getattr(beam, "id", ""))
    forces = to_beam_forces(envelope)
    geometry = _beam_geometry(beam, forces)
    if geometry is None:
        return _failed_result(
            element_id,
            "beam",
            "the placed beam carries no width, depth or span, so there is no section to design",
            check="geometry",
        )
    return design_beam(forces, geometry, ctx)


def _design_one_column(model: Any, column: Any, envelope: Any, ctx: Any):
    """One column: the envelope through `to_column_forces`, height off the storey."""
    from ...analysis import to_column_forces

    element_id = str(getattr(column, "id", ""))
    height_m = getattr(envelope, "length_m", None)
    note = ""
    if not height_m:
        height_m = _storey_height_m(model, getattr(column, "storey", 0))
    if not height_m:
        height_m = _FALLBACK_STOREY_HEIGHT_M
        note = (
            "neither the force envelope nor the model carried an unsupported length for this "
            "column; the slenderness checks were run on the "
            + ("%.2f" % _FALLBACK_STOREY_HEIGHT_M)
            + " m default storey height"
        )
    geometry = _column_geometry(column, height_m)
    if geometry is None:
        return _failed_result(
            element_id,
            "column",
            "the placed column carries no width or depth, so there is no section to design",
            check="geometry",
        )
    result = design_column(to_column_forces(envelope), geometry, ctx)
    if note:
        result.add_note(note)
    return result


def _design_one_slab(panel: Any, envelope: Any, ctx: Any):
    """One slab panel: the panel is the geometry, the envelope carries the load."""
    from ...analysis import to_slab_load

    element_id = str(getattr(panel, "id", ""))
    if envelope is None:
        return _failed_result(
            element_id,
            "slab",
            "no slab envelope reached the design layer for this panel, so there is no "
            "factored pressure to design it against",
            check="load",
        )
    return design_slab(panel, to_slab_load(envelope), ctx)


def _design_one_stair(stair: Any, ctx: Any):
    """One placed flight with its synthetic IS 875 stair occupancy load."""
    load, stair_ctx = stair_design_inputs(ctx)
    return design_stair_flight(stair, load, stair_ctx)


def _design_one_strip(
    footing: Any,
    walls_by_id: Mapping[str, Any],
    wall_loads: Mapping[str, float],
    soil: Any,
    ctx: Any,
):
    """One wall strip: the placed rectangle as geometry, the wall ledger as load.

    A run can cover several collinear walls, so the strip is designed for the
    WORST line load on it, which is the same reading `layout_foundations` takes
    when it sizes the run.
    """
    from .footings import StripLoads

    element_id = str(getattr(footing, "id", ""))
    supports = [str(one) for one in (getattr(footing, "supports", None) or [])]
    known = [key for key in supports if key in walls_by_id]
    if not known:
        return _failed_result(
            element_id,
            "footing",
            "none of the bearing walls this strip supports ("
            + ", ".join(supports)
            + ") is on the model, and a strip is sized by the wall it carries",
            check="wall section",
        )
    geometry = strip_geometry_from_model(footing, walls_by_id)
    carried = [(str(key), float(wall_loads[key])) for key in sorted(known) if key in wall_loads]
    if not carried:
        return _failed_result(
            element_id,
            "footing",
            "no service line load reached the design layer for wall(s) "
            + ", ".join(sorted(known))
            + "; the takedown footing ledger carries none of them, and a strip sized against an "
            "invented load is a wrong number wearing a design's clothes",
            check="service load",
        )
    worst = max(carried, key=lambda row: (row[1], row[0]))
    emitted = getattr(footing, "w_service_kn_per_m", None)
    design_load = worst[1]
    if emitted is not None:
        design_load = max(design_load, float(emitted))
    result = design_strip_footing(
        geometry, StripLoads(n_service_kn_per_m=design_load, wall_id=worst[0]), soil, ctx
    )
    if design_load > worst[1] + 1e-9:
        result.add_note(
            "the placer increased the governing strip service demand from "
            + str(round(worst[1], 3))
            + " to "
            + str(round(design_load, 3))
            + " kN/m to carry column point loads absorbed into local widenings"
        )
    if len(carried) > 1:
        result.add_note(
            "this strip runs under "
            + str(len(carried))
            + " collinear bearing walls and is designed for the worst line load on the run, "
            + worst[0]
        )
    return result


def _design_one_footing(
    footing: Any,
    columns_by_id: Mapping[str, Any],
    columns_by_stack: Mapping[str, Any],
    envelopes: Mapping[Tuple[str, str], Any],
    stack_loads: Mapping[str, float],
    straps: Mapping[str, Tuple[str, float]],
    soil: Any,
    ctx: Any,
    walls_by_id: Optional[Mapping[str, Any]] = None,
    wall_loads: Optional[Mapping[str, float]] = None,
):
    """One footing, routed on its kind to the designer that owns that shape."""
    from .footings import CombinedGeometry, FootingLoads, PadGeometry

    element_id = str(getattr(footing, "id", ""))
    kind = _footing_kind(footing)
    if kind in UNDESIGNED_FOOTING_KINDS:
        return _skipped_result(element_id, "footing", UNDESIGNED_FOOTING_KINDS[kind])
    if kind == "strip":
        return _design_one_strip(footing, walls_by_id or {}, wall_loads or {}, soil, ctx)

    columns = _bearing_columns(footing, columns_by_id, columns_by_stack)
    if not columns:
        return _failed_result(
            element_id,
            "footing",
            "none of the columns this footing supports ("
            + ", ".join(str(one) for one in (getattr(footing, "supports", None) or []))
            + ") is on the model, and a footing is sized by the column it carries",
            check="column section",
        )

    loads = []  # type: List[Any]
    unloaded = []  # type: List[str]
    for column in columns:
        value = _service_load_kn(footing, column, len(columns), envelopes, stack_loads)
        if value is None:
            unloaded.append(str(getattr(column, "id", "")))
            value = 0.0
        loads.append(
            FootingLoads(p_service_kn=float(value), column_id=str(getattr(column, "id", "")))
        )
    if unloaded:
        return _failed_result(
            element_id,
            "footing",
            "no service load reached the design layer for column(s) "
            + ", ".join(unloaded)
            + "; the takedown footing ledger carries neither their stack nor their element id, "
            "and a footing sized against an invented load is a wrong number wearing a design's "
            "clothes",
            check="service load",
        )

    if kind == "combined":
        geometry = CombinedGeometry(
            element_id=element_id,
            columns=tuple(_column_stub(one) for one in columns),
            placed_bx_m=_placed_m(footing, "w_m"),
            placed_ly_m=_placed_m(footing, "h_m"),
        )
        return design_combined_footing(geometry, loads, soil, ctx)

    column = columns[0]
    partner, span_m = straps.get(element_id, ("", 0.0))
    geometry = PadGeometry(
        element_id=element_id,
        column=_column_stub(column),
        col_offset_x_m=float(getattr(column, "x_m", 0.0) or 0.0)
        - float(getattr(footing, "x_m", 0.0) or 0.0),
        col_offset_y_m=float(getattr(column, "y_m", 0.0) or 0.0)
        - float(getattr(footing, "y_m", 0.0) or 0.0),
        placed_bx_m=_placed_m(footing, "w_m"),
        placed_ly_m=_placed_m(footing, "h_m"),
        kind="strap" if partner else kind,
        strap_partner_id=partner,
        strap_span_m=span_m,
    )
    result = design_footing(geometry, loads[0], soil, ctx)
    if len(columns) > 1:
        result.add_warning(
            "this "
            + kind
            + " footing carries "
            + str(len(columns))
            + " column stacks; v1 designs it as a pad under "
            + str(getattr(column, "id", ""))
            + " alone and the other stacks are not accounted for"
        )
    return result


# ---------------------------------------------------------------------------
# run_rcc_design
# ---------------------------------------------------------------------------


def run_rcc_design(model: Any, analysis: Any, options: Any = None) -> List[Any]:
    """Design every RC element the model carries and the analysis can feed.

    `analysis` is `analysis.takedown`'s result, or anything with `envelopes`, or
    a bare list of them. Beams and columns are taken from the envelope index,
    slabs and footings from the model with the analysis read for their loads, and
    an element that appears on only one of the two rosters still comes back with
    its own result. Every demand crosses into a designer through the converters
    finding 20 made the only designer inputs (`to_beam_forces`,
    `to_column_forces`, `to_slab_load`) or, for a footing, through the takedown's
    own footing ledger.

    Results come back grouped in `MEMBER_KINDS` order and then by element id. A
    designer that is missing, that raises, or that cannot be fed is disclosed on
    its own result rather than dropping the element or the batch.
    """
    from . import detailing

    ctx = detailing.as_context(options)
    soil = _soil_of(options)
    envelopes = _envelope_index(analysis)
    stack_loads = _stack_service_loads(analysis)
    wall_loads = _wall_line_loads(analysis)

    placed_columns = _elements(model, "columns")
    beams = dict((str(item.id), item) for item in _elements(model, "beams"))
    columns = dict((str(item.id), item) for item in placed_columns)
    by_stack = _lowest_by_stack(placed_columns)
    slabs = dict((str(item.id), item) for item in _elements(model, "slabs"))
    stairs = dict((str(item["id"]), item) for item in stair_flights_from_model(model))
    walls = dict((str(item.id), item) for item in _elements(model, "walls"))
    footings = _elements(model, "footings")
    straps = _straps_by_footing(footings)

    results = []  # type: List[Any]

    def run(element_id, element_type, call):
        """Call one designer, turning anything it throws into its own failure."""
        try:
            results.append(call())
        except Exception as error:  # noqa: BLE001 - disclose, never lose the element
            results.append(
                _failed_result(
                    element_id,
                    element_type,
                    "the "
                    + element_type
                    + " designer could not run: "
                    + type(error).__name__
                    + ": "
                    + str(error),
                )
            )

    # -- beams and columns: force driven, walked off the envelope index -----
    for kind, placed in (("beam", beams), ("column", columns)):
        for key in sorted(envelopes):
            if key[0] != kind:
                continue
            element_id = key[1]
            envelope = envelopes[key]
            element = placed.get(element_id)
            if element is None:
                results.append(
                    _failed_result(
                        element_id,
                        kind,
                        "no placed " + kind + " with id " + repr(element_id) + " to design",
                    )
                )
                continue
            if kind == "beam":
                run(element_id, kind, lambda e=element, v=envelope: _design_one_beam(e, v, ctx))
            else:
                run(
                    element_id,
                    kind,
                    lambda e=element, v=envelope: _design_one_column(model, e, v, ctx),
                )

    # -- slabs: geometry driven, the panel is the designer's first argument --
    for element_id in sorted(slabs):
        envelope = envelopes.get(("slab", element_id))
        run(
            element_id,
            "slab",
            lambda p=slabs[element_id], v=envelope: _design_one_slab(p, v, ctx),
        )

    # -- stair flights: geometry driven, with no takedown envelope ----------
    for element_id in sorted(stairs):
        run(
            element_id,
            "slab",
            lambda flight=stairs[element_id]: _design_one_stair(flight, ctx),
        )

    # -- footings: geometry driven, and the only place a merge is visible ---
    for footing in sorted(footings, key=lambda item: str(getattr(item, "id", ""))):
        element_id = str(getattr(footing, "id", ""))
        run(
            element_id,
            "footing",
            lambda f=footing: _design_one_footing(
                f, columns, by_stack, envelopes, stack_loads, straps, soil, ctx, walls, wall_loads
            ),
        )

    order = dict((kind, index) for index, kind in enumerate(MEMBER_KINDS))
    results.sort(
        key=lambda item: (
            order.get(str(getattr(item, "element_type", "")), len(order)),
            str(getattr(item, "element_type", "")),
            str(getattr(item, "element_id", "")),
        )
    )
    return results


def _register() -> None:
    """Register the RC designer for the material dispatch in design/common.py."""
    try:
        from ..common import register_designer
    except Exception:  # pragma: no cover - common is always importable in a built tree
        return
    register_designer("rcc", run_rcc_design)


_register()
