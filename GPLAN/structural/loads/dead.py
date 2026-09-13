"""Dead load case builder (IS 875 Part 1).

`build_dead(model, options)` walks the placed StructuralModel and returns the
unfactored "DL" LoadCase:

    slabs      AreaLoad per panel: 25 t + finish by role (floor / flat roof),
               plus the sunken fill on bathroom panels when the option is on.
    beams      LineLoad per beam: web self weight 25 b (D - t_slab); full D on
               plinth beams and wherever no slab adjoins.
    walls      LineLoad per wall ON THE WALL ITSELF: gamma t h_clear + plaster
               on two faces.  The takedown routes each wall's accumulated load
               to its support below through `find_wall_support`, the single
               owner of that search.  Column self weight is NOT built here: the
               takedown adds it per storey (spec section 7 item 3).
    partitions a wall with no support below is smeared over the panel it
               stands on as an AreaLoad of its exact weight (disclosed).
    parapets   optional line loads on the roof perimeter members (0.9 m x
               115 mm engine default, toggle).
    roofs      meta.roof "flat" is the slab path; "gable" / "hip" / "shed" use
               the projected-area v1 model: q_plan = q_surface / cos(theta)
               distributed one-way to the eaves (gable, shed) or by tributary
               trapezoids around the perimeter (hip), emitted as LineLoads on
               the top storey eave members.

Every quantity read from IS 875 goes through the `codes.is875` clause
callables, so a caller running under `codes.trace.trace_into` gets the clause
trail for free.  Disclosures land on the model ladder via `model.add_warning`.

Options (dict, every key optional):
    sunken_bath            bool, default False: add the sunken fill on panels
                           over BATH / WC rooms.
    sunken_depth_m         float, default the table's reference depth (0.25).
    deduct_openings        bool, default the data default (False): subtract
                           opening areas from wall dead loads.
    parapet                bool, default True on a flat roof, False on a
                           pitched one.
    partition_allowance_kpa  float, default the data default (1.0), applied to
                           interior_unknown room areas.
    roof_surface           "roof_sheet_light" (default) or "roof_tile" for
                           pitched roofs.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..codes import is875
from ..model import (
    Beam,
    BeamKind,
    GEOM_TOL_M,
    Material,
    Occupancy,
    RC_SLAB_MIN_THICKNESS_MM,
    SlabKind,
    SlabPanel,
    StructuralModel,
    WallLine,
    WallRole,
    effective_rc_slab_thickness_m,
    polygon_rect,
    wall_axis,
)
from . import CASE_DL, AreaLoad, CaseKind, LineLoad, LoadCase

_STAGE = "loads.dead"

# Alignment window beyond the half thickness rule, metres (matches grid.py's
# TOL_JOIN_EXTRA_MM spirit).
_ALIGN_EXTRA_M = 0.01

# Overlap below which a support does not count, metres.
_MIN_OVERLAP_M = 0.05

_SRC_SLAB = "IS 875-1:1987 Table 1 (RC self weight) + Table 2 (finish)"
_SRC_BEAM = "IS 875-1:1987 Table 1, RC web below slab"
_SRC_WALL = "IS 875-1:1987 Table 1, masonry + 12 mm plaster both faces"
_SRC_PARAPET = "IS 875-1:1987 Table 1; 0.9 m x 115 mm parapet, engine default"
_SRC_ROOF = "IS 875-1:1987 Table 2, pitched roof projected-area v1"
_SRC_PARTITION = "IS 875-1:1987 Cl 3.1.2, partition weight smeared over its panel"
_SRC_ALLOWANCE = "IS 875-1:1987 Cl 3.1.2, partition allowance on an unknown interior"


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------


def beam_axis(beam: Beam) -> Optional[Tuple[str, float, float, float]]:
    """('h'|'v', centreline position, span start, span end) metres; None if skew."""
    ax, ay = beam.a
    bx, by = beam.b
    horizontal = abs(ay - by) <= GEOM_TOL_M
    vertical = abs(ax - bx) <= GEOM_TOL_M
    if horizontal and not vertical:
        return ("h", 0.5 * (ay + by), min(ax, bx), max(ax, bx))
    if vertical and not horizontal:
        return ("v", 0.5 * (ax + bx), min(ay, by), max(ay, by))
    return None


def _rect_overlap_area(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    """Overlap area of two (x, y, w, h) rects."""
    dx = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    dy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    if dx <= 0.0 or dy <= 0.0:
        return 0.0
    return dx * dy


def roof_storey_index(model: StructuralModel) -> int:
    """The roof level index: meta['roof_storey_index'] else the top storey."""
    meta = model.meta or {}
    if "roof_storey_index" in meta:
        return int(meta["roof_storey_index"])
    if model.storeys:
        return max(s.index for s in model.storeys)
    indices = set(w.storey for w in model.walls) | set(r.storey for r in model.rooms)
    return max(indices) if indices else 0


def colinear_beams(
    model: StructuralModel,
    storey: int,
    orient: str,
    pos_m: float,
    s0_m: float,
    s1_m: float,
    align_tol_m: float,
) -> List[Tuple[Beam, float, float]]:
    """Beams on `storey` along (orient, pos) overlapping [s0, s1], sorted by id.

    Returns (beam, overlap_lo_m, overlap_hi_m) with the overlap in line
    coordinates.  Alignment window is `align_tol_m` across the line.
    """
    out = []  # type: List[Tuple[Beam, float, float]]
    for beam in sorted(model.beams_on(storey), key=lambda b: b.id):
        axis = beam_axis(beam)
        if axis is None or axis[0] != orient:
            continue
        if abs(axis[1] - pos_m) > align_tol_m:
            continue
        lo = max(s0_m, axis[2])
        hi = min(s1_m, axis[3])
        if hi - lo > _MIN_OVERLAP_M:
            out.append((beam, lo, hi))
    return out


def find_wall_support(model: StructuralModel, wall: WallLine) -> Dict[str, Any]:
    """Where a wall's base load goes; the ONE owner of the wall bearing search.

    A wall of storey i stands on floor level i-1 (top of storey i-1); a wall
    with role PARAPET stands on its own floor level i.  The search order is
    (1) plinth beams of the wall's own storey, (2) beams of the storey below
    (own storey for a parapet), (3) a wall below aligned within half the lower
    wall's thickness, (4) the ground for storey 0.  Returns:

        {"kind": "beams", "beams": [(beam_id, lo_m, hi_m), ...]}
        {"kind": "wall",  "wall_id": id}
        {"kind": "ground"}
        {"kind": "none"}

    with line coordinates in metres.  Both dead.py (to decide the partition
    smear) and analysis/takedown.py (to route the accumulated load) call this,
    so the two can never disagree about where a wall bears.
    """
    axis = wall_axis(wall)
    if axis is None:
        return {"kind": "none"}
    orient, pos, s0, s1 = axis
    align = 0.5 * max(wall.thickness_m, 0.0) + _ALIGN_EXTRA_M
    is_parapet = wall.role == WallRole.PARAPET
    bearing_storey = wall.storey if is_parapet else wall.storey - 1

    # plinth beams of the wall's own storey sit at its base level
    if not is_parapet:
        plinth = [
            (beam, lo, hi)
            for beam, lo, hi in colinear_beams(model, wall.storey, orient, pos, s0, s1, align)
            if beam.kind == BeamKind.PLINTH
        ]
        if plinth:
            return {"kind": "beams", "beams": [(b.id, lo, hi) for b, lo, hi in plinth]}

    if bearing_storey >= 0:
        beams = [
            (beam, lo, hi)
            for beam, lo, hi in colinear_beams(model, bearing_storey, orient, pos, s0, s1, align)
            if is_parapet or beam.kind != BeamKind.PLINTH
        ]
        if beams:
            return {"kind": "beams", "beams": [(b.id, lo, hi) for b, lo, hi in beams]}

        for below in sorted(model.walls_on(bearing_storey), key=lambda w: w.id):
            if below.id == wall.id:
                continue
            below_axis = wall_axis(below)
            if below_axis is None or below_axis[0] != orient:
                continue
            if abs(below_axis[1] - pos) > 0.5 * below.thickness_m + _ALIGN_EXTRA_M:
                continue
            overlap = min(s1, below_axis[3]) - max(s0, below_axis[2])
            if overlap > _MIN_OVERLAP_M:
                return {"kind": "wall", "wall_id": below.id}

    if wall.storey == 0:
        return {"kind": "ground"}
    return {"kind": "none"}


def panel_under_wall(model: StructuralModel, wall: WallLine) -> Optional[SlabPanel]:
    """The slab panel at the wall's base level containing its midpoint, or None."""
    level = wall.storey - 1
    if level < 0:
        return None
    mx = 0.5 * (wall.a[0] + wall.b[0])
    my = 0.5 * (wall.a[1] + wall.b[1])
    for slab in sorted(model.slabs_on(level), key=lambda s: s.id):
        x, y, w, h = polygon_rect(slab.polygon)
        if x - GEOM_TOL_M <= mx <= x + w + GEOM_TOL_M and y - GEOM_TOL_M <= my <= y + h + GEOM_TOL_M:
            return slab
    return None


# ---------------------------------------------------------------------------
# edge profiles (shared with the pitched roof and with live.py)
# ---------------------------------------------------------------------------


def profile_kinks(profile: str, length_m: float, ramp_m: float) -> List[float]:
    """Interior slope-change stations of an edge load profile, metres."""
    if profile == "triangle":
        return [0.5 * length_m]
    if profile == "trapezoid":
        ramp = min(ramp_m, 0.5 * length_m)
        return sorted(set([ramp, length_m - ramp]))
    return []


def profile_value(profile: str, peak: float, length_m: float, ramp_m: float, t_m: float) -> float:
    """Ordinate of an edge load profile at station t along the edge."""
    if length_m <= 0.0:
        return 0.0
    t = min(max(t_m, 0.0), length_m)
    if profile == "uniform":
        return peak
    if profile == "triangle":
        half = 0.5 * length_m
        return peak * (1.0 - abs(t - half) / half)
    if profile == "trapezoid":
        ramp = min(ramp_m, 0.5 * length_m)
        if ramp <= 0.0:
            return peak
        return peak * min(1.0, t / ramp, (length_m - t) / ramp)
    raise ValueError("unknown edge profile: " + repr(profile))


def line_loads_for_edge(
    members: Sequence[Tuple[Any, float, float]],
    edge_lo_m: float,
    edge_hi_m: float,
    profile: str,
    peak_kn_m: float,
    ramp_m: float,
    kind: CaseKind,
    source: str,
    note: str = "",
) -> List[LineLoad]:
    """Sample an edge profile onto member overlaps as exact piecewise loads.

    `members` are (element, overlap_lo_m, overlap_hi_m) along the edge line;
    each element needs `.a`, `.b` and an axis so its parametric fractions can
    be computed.  Pieces are split at profile kinks so every emitted LineLoad
    is exactly linear.
    """
    length = edge_hi_m - edge_lo_m
    if length <= 0.0 or peak_kn_m == 0.0:
        return []
    kinks = [edge_lo_m + k for k in profile_kinks(profile, length, ramp_m)]
    out = []  # type: List[LineLoad]
    for element, lo, hi in members:
        axis = beam_axis(element) if isinstance(element, Beam) else wall_axis(element)
        if axis is None:
            continue
        orient = axis[0]
        a_coord = element.a[0] if orient == "h" else element.a[1]
        b_coord = element.b[0] if orient == "h" else element.b[1]
        span = b_coord - a_coord
        if abs(span) <= GEOM_TOL_M:
            continue
        stations = sorted(set([lo, hi] + [k for k in kinks if lo < k < hi]))
        for i in range(len(stations) - 1):
            p0, p1 = stations[i], stations[i + 1]
            if p1 - p0 <= GEOM_TOL_M:
                continue
            w0 = profile_value(profile, peak_kn_m, length, ramp_m, p0 - edge_lo_m)
            w1 = profile_value(profile, peak_kn_m, length, ramp_m, p1 - edge_lo_m)
            f0 = (p0 - a_coord) / span
            f1 = (p1 - a_coord) / span
            if f0 > f1:
                f0, f1 = f1, f0
                w0, w1 = w1, w0
            out.append(
                LineLoad(
                    element_id=element.id,
                    w1_kn_m=w0,
                    w2_kn_m=w1,
                    a=f0,
                    b=f1,
                    kind=kind,
                    source=source,
                    note=note,
                )
            )
    return out


# ---------------------------------------------------------------------------
# pitched roof (projected-area v1), shared with live.py
# ---------------------------------------------------------------------------


def pitched_roof_context(model: StructuralModel) -> Optional[Dict[str, Any]]:
    """The pitched-roof geometry, or None when the roof is flat / slab-built.

    Returns {"type", "storey", "tan", "cos", "alpha_deg", "bbox"} with bbox as
    (x0, y0, x1, y1) of the top storey.  A pitched meta.roof with ROOF slab
    panels present keeps the slab path (the panels are real structure), so this
    returns None there too.
    """
    meta = model.meta or {}
    roof = meta.get("roof") or {}
    rtype = str(roof.get("type", "flat"))
    rise = float(roof.get("rise_ratio", 0.0) or 0.0)
    if rtype not in ("gable", "hip", "shed") or rise <= 0.0:
        return None
    top = roof_storey_index(model)
    if any(s.kind == SlabKind.ROOF for s in model.slabs_on(top)):
        return None
    xs = []  # type: List[float]
    ys = []  # type: List[float]
    for room in model.rooms_on(top):
        x, y, w, h = polygon_rect(room.polygon)
        xs.extend([x, x + w])
        ys.extend([y, y + h])
    for wall in model.walls_on(top):
        xs.extend([wall.a[0], wall.b[0]])
        ys.extend([wall.a[1], wall.b[1]])
    if not xs:
        return None
    tan = 2.0 * rise if rtype in ("gable", "hip") else rise
    cos = 1.0 / math.sqrt(1.0 + tan * tan)
    return {
        "type": rtype,
        "storey": top,
        "tan": tan,
        "cos": cos,
        "alpha_deg": math.degrees(math.atan(tan)),
        "bbox": (min(xs), min(ys), max(xs), max(ys)),
    }


def _edge_members(
    model: StructuralModel, storey: int, orient: str, pos_m: float, lo_m: float, hi_m: float
) -> List[Tuple[Any, float, float]]:
    """Supporting members along one eave edge: beams first, walls where bare."""
    align = 0.5 * 0.23 + _ALIGN_EXTRA_M
    members = [(b, lo, hi) for b, lo, hi in colinear_beams(model, storey, orient, pos_m, lo_m, hi_m, align)]
    covered = [(lo, hi) for _, lo, hi in members]
    for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
        if wall.role == WallRole.RAILING:
            continue
        axis = wall_axis(wall)
        if axis is None or axis[0] != orient:
            continue
        if abs(axis[1] - pos_m) > 0.5 * wall.thickness_m + _ALIGN_EXTRA_M:
            continue
        lo = max(lo_m, axis[2])
        hi = min(hi_m, axis[3])
        if hi - lo <= _MIN_OVERLAP_M:
            continue
        # only the stretch no beam already covers
        pieces = [(lo, hi)]
        for clo, chi in covered:
            next_pieces = []  # type: List[Tuple[float, float]]
            for plo, phi in pieces:
                if chi <= plo or clo >= phi:
                    next_pieces.append((plo, phi))
                    continue
                if clo > plo:
                    next_pieces.append((plo, clo))
                if chi < phi:
                    next_pieces.append((chi, phi))
            pieces = next_pieces
        for plo, phi in pieces:
            if phi - plo > _MIN_OVERLAP_M:
                members.append((wall, plo, phi))
    return members


def pitched_roof_line_loads(
    model: StructuralModel,
    ctx: Dict[str, Any],
    q_plan_kpa: float,
    kind: CaseKind,
    source: str,
    note: str = "",
) -> Tuple[List[LineLoad], List[str]]:
    """Distribute a plan-projected roof pressure to the top storey eave members.

    gable / shed span one-way across the short plan dimension to the two long
    eave edges (each takes q S/2 uniformly); hip splits the perimeter by 45
    degree tributaries: trapezoids on the long edges, triangles on the short
    ones, all with peak q S/2.  Returns (loads, bare_edges) where bare_edges
    names edges that found no supporting member (the caller discloses).
    """
    x0, y0, x1, y1 = ctx["bbox"]
    w = x1 - x0
    h = y1 - y0
    storey = int(ctx["storey"])
    if w <= 0.0 or h <= 0.0:
        return ([], [])
    long_axis_x = w >= h
    short = h if long_axis_x else w
    peak = q_plan_kpa * short / 2.0
    edges = []  # type: List[Tuple[str, str, float, float, float, str, float]]
    # (tag, orient, pos, lo, hi, profile, ramp)
    if long_axis_x:
        long_edges = [("eave-y%.3f" % y0, "h", y0, x0, x1), ("eave-y%.3f" % y1, "h", y1, x0, x1)]
        short_edges = [("hip-x%.3f" % x0, "v", x0, y0, y1), ("hip-x%.3f" % x1, "v", x1, y0, y1)]
    else:
        long_edges = [("eave-x%.3f" % x0, "v", x0, y0, y1), ("eave-x%.3f" % x1, "v", x1, y0, y1)]
        short_edges = [("hip-y%.3f" % y0, "h", y0, x0, x1), ("hip-y%.3f" % y1, "h", y1, x0, x1)]
    if ctx["type"] in ("gable", "shed"):
        for tag, orient, pos, lo, hi in long_edges:
            edges.append((tag, orient, pos, lo, hi, "uniform", 0.0))
    else:  # hip
        for tag, orient, pos, lo, hi in long_edges:
            edges.append((tag, orient, pos, lo, hi, "trapezoid", short / 2.0))
        for tag, orient, pos, lo, hi in short_edges:
            edges.append((tag, orient, pos, lo, hi, "triangle", 0.0))
    loads = []  # type: List[LineLoad]
    bare = []  # type: List[str]
    for tag, orient, pos, lo, hi, profile, ramp in edges:
        members = _edge_members(model, storey, orient, pos, lo, hi)
        if not members:
            bare.append(tag)
            continue
        loads.extend(
            line_loads_for_edge(members, lo, hi, profile, peak, ramp, kind, source, note=note or tag)
        )
    return (loads, bare)


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------


def _wall_material_gamma(model: StructuralModel, wall: WallLine) -> float:
    """Unit weight for a wall's material, disclosing an off-catalogue fallback."""
    material = wall.material
    if material == Material.RC:
        return is875.part1_unit_weight("rcc")
    if material == Material.BRICK_MASONRY:
        return is875.part1_unit_weight("brick_masonry")
    model.add_warning(
        "W_RELEASED_CAP",
        "wall material %r has no IS 875-1 unit weight; brick masonry assumed" % material.value,
        [wall.id],
        stage=_STAGE,
    )
    return is875.part1_unit_weight("brick_masonry")


def _clear_height_m(model: StructuralModel, wall: WallLine, axis: Tuple[str, float, float, float]) -> float:
    """Storey height less the deepest framing member over the wall."""
    storey = model.storey(wall.storey)
    height = storey.height_m if storey is not None else 3.0
    orient, pos, s0, s1 = axis
    align = 0.5 * max(wall.thickness_m, 0.23) + _ALIGN_EXTRA_M
    over = colinear_beams(model, wall.storey, orient, pos, s0, s1, align)
    depths = [b.depth_m for b, _, _ in over if b.depth_m is not None and b.kind != BeamKind.PLINTH]
    if depths:
        return max(height - max(depths), 0.0)
    slabs = model.slabs_on(wall.storey)
    ts = [effective_rc_slab_thickness_m(s.thickness_m) for s in slabs]
    if ts:
        return max(height - max(ts), 0.0)
    return height


def _opening_deduction_kn(model: StructuralModel, wall: WallLine, weight_kn_m2: float, h_clear: float) -> Tuple[float, bool]:
    """(deducted weight kN, any assumed opening deducted) for one wall."""
    total = 0.0
    assumed = False
    for opening in wall.openings:
        sill = opening.sill_m if opening.sill_m is not None else 0.0
        head = opening.head_m if opening.head_m is not None else h_clear
        depth = max(min(head, h_clear) - max(sill, 0.0), 0.0)
        area = max(opening.width_m, 0.0) * depth
        if area <= 0.0:
            continue
        total += area * weight_kn_m2
        if model.opening_assumed(opening):
            assumed = True
    return (total, assumed)


def build_dead(model: StructuralModel, options: Optional[Dict[str, Any]] = None) -> LoadCase:
    """The unfactored "DL" LoadCase for a placed model; see the module docstring."""
    opts = dict(options or {})
    case = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)

    gamma_rcc = is875.part1_unit_weight("rcc")
    gamma_plaster = is875.part1_unit_weight("cement_plaster")
    plaster_t = float(is875.dead_load_default("plaster_thickness_m"))
    plaster_two_faces = 2.0 * gamma_plaster * plaster_t  # kN per m2 of wall face

    roof_ctx = pitched_roof_context(model)
    top_storey = roof_storey_index(model)

    # -- slabs -------------------------------------------------------------
    sunken_on = bool(opts.get("sunken_bath", (model.meta or {}).get("options", {}).get("sunken_bath", False)))
    sunken_q = is875.part1_area_load("sunken_fill") if sunken_on else 0.0
    reference_depth = is875.area_load_reference_depth_m("sunken_fill") or 0.25
    sunken_depth = float(opts.get("sunken_depth_m", reference_depth))
    finish_floor = is875.part1_area_load("floor_finish")
    finish_roof = is875.part1_area_load("roof_finish_flat")

    for slab in sorted(model.slabs, key=lambda s: (s.storey, s.id)):
        thickness = effective_rc_slab_thickness_m(slab.thickness_m)
        if slab.thickness_m is None:
            model.add_warning(
                "W_RELEASED_CAP",
                "slab %s has no thickness; %.0f mm project minimum assumed for self weight"
                % (slab.id, RC_SLAB_MIN_THICKNESS_MM),
                [slab.id],
                stage=_STAGE,
            )
        finish = finish_roof if slab.kind == SlabKind.ROOF else finish_floor
        q = gamma_rcc * thickness + finish
        case.area.append(AreaLoad(panel_id=slab.id, q_kpa=q, kind=CaseKind.DEAD, source=_SRC_SLAB))
        if sunken_on and sunken_q > 0.0:
            rect = polygon_rect(slab.polygon)
            area = rect[2] * rect[3]
            if area > 0.0:
                wet = 0.0
                for room in model.rooms_on(slab.storey):
                    if room.occupancy in (Occupancy.BATH, Occupancy.WC):
                        wet += _rect_overlap_area(rect, polygon_rect(room.polygon))
                if wet > GEOM_TOL_M:
                    q_add = sunken_q * (sunken_depth / reference_depth) * min(wet / area, 1.0)
                    case.area.append(
                        AreaLoad(
                            panel_id=slab.id,
                            q_kpa=q_add,
                            kind=CaseKind.DEAD,
                            source="IS 875-1:1987 Table 1, sunken fill over bath / wc",
                            note="depth %.3f m over %.2f m2" % (sunken_depth, wet),
                        )
                    )

    # -- beam webs ---------------------------------------------------------
    slab_ts = {}  # type: Dict[int, List[Tuple[Tuple[float, float, float, float], float]]]
    for slab in model.slabs:
        slab_ts.setdefault(slab.storey, []).append(
            (polygon_rect(slab.polygon), effective_rc_slab_thickness_m(slab.thickness_m))
        )
    for beam in sorted(model.beams, key=lambda b: (b.storey, b.id)):
        if beam.depth_m is None:
            model.add_warning(
                "W_RELEASED_CAP",
                "beam %s has no depth; web self weight omitted" % beam.id,
                [beam.id],
                stage=_STAGE,
            )
            continue
        t_adj = 0.0
        if beam.kind != BeamKind.PLINTH:
            mx = 0.5 * (beam.a[0] + beam.b[0])
            my = 0.5 * (beam.a[1] + beam.b[1])
            for rect, t in slab_ts.get(beam.storey, []):
                margin = 0.5 * beam.width_m + _ALIGN_EXTRA_M
                if rect[0] - margin <= mx <= rect[0] + rect[2] + margin and rect[1] - margin <= my <= rect[1] + rect[3] + margin:
                    t_adj = max(t_adj, t)
        web = max(beam.depth_m - t_adj, 0.0)
        w = gamma_rcc * beam.width_m * web
        if w > 0.0:
            case.line.append(
                LineLoad(element_id=beam.id, w1_kn_m=w, w2_kn_m=w, a=0.0, b=1.0, kind=CaseKind.DEAD, source=_SRC_BEAM)
            )

    # -- walls -------------------------------------------------------------
    parapet_h = float(is875.dead_load_default("parapet_height_m"))
    deduct_default = bool(is875.dead_load_default("opening_deduction"))
    deduct = bool(opts.get("deduct_openings", deduct_default))
    smeared = []  # type: List[str]
    floating = []  # type: List[str]

    for wall in sorted(model.walls, key=lambda w: (w.storey, w.id)):
        axis = wall_axis(wall)
        if axis is None or wall.thickness_m <= 0.0:
            continue
        length = wall.length_m()
        if length <= GEOM_TOL_M:
            continue
        if wall.role in (WallRole.PARAPET, WallRole.RAILING):
            h = parapet_h
        else:
            h = _clear_height_m(model, wall, axis)
        gamma = _wall_material_gamma(model, wall)
        weight_kn_m2 = gamma * wall.thickness_m + plaster_two_faces
        w_line = weight_kn_m2 * h
        if deduct and wall.openings:
            deducted, any_assumed = _opening_deduction_kn(model, wall, weight_kn_m2, h)
            w_line = max(w_line - deducted / length, 0.0)
            if any_assumed:
                model.add_warning(
                    "W_ASSUMED_OPENINGS",
                    "assumed openings were deducted from wall dead load",
                    [wall.id],
                    stage=_STAGE,
                )
        if w_line <= 0.0:
            continue
        support = find_wall_support(model, wall)
        if support["kind"] != "none":
            case.line.append(
                LineLoad(
                    element_id=wall.id,
                    w1_kn_m=w_line,
                    w2_kn_m=w_line,
                    a=0.0,
                    b=1.0,
                    kind=CaseKind.DEAD,
                    source=_SRC_WALL,
                    note="openings deducted" if deduct and wall.openings else "",
                )
            )
            continue
        panel = panel_under_wall(model, wall)
        if panel is not None:
            rect = polygon_rect(panel.polygon)
            area = rect[2] * rect[3]
            if area > 0.0:
                case.area.append(
                    AreaLoad(
                        panel_id=panel.id,
                        q_kpa=w_line * length / area,
                        kind=CaseKind.DEAD,
                        source=_SRC_PARTITION,
                        note="wall %s smeared" % wall.id,
                    )
                )
                smeared.append(wall.id)
                continue
        floating.append(wall.id)
        # never hide the weight: it stays on the wall and the takedown's
        # routing will hard-fail it as a transfer condition
        case.line.append(
            LineLoad(element_id=wall.id, w1_kn_m=w_line, w2_kn_m=w_line, a=0.0, b=1.0, kind=CaseKind.DEAD, source=_SRC_WALL)
        )

    if smeared:
        # closest registered code: the registered W_UNIT_NO_PLAN text is the
        # partition-allowance condition; these walls became area allowances
        model.add_warning(
            "W_UNIT_NO_PLAN",
            "%d partition wall(s) have no support below; their exact weight was smeared over the panel they stand on" % len(smeared),
            smeared,
            stage=_STAGE,
        )
    if floating:
        model.add_warning(
            "E_TRANSFER_REQUIRED",
            "wall(s) with no support below and no panel to smear over; a transfer member would be required",
            floating,
            stage=_STAGE,
        )

    # -- partition allowance on unknown interiors (critic finding 39) ------
    allowance = float(opts.get("partition_allowance_kpa", is875.dead_load_default("partition_allowance_kpa")))
    unknown_ids = []  # type: List[str]
    if allowance > 0.0:
        unknown = [r for r in model.rooms if r.interior_unknown]
        for slab in sorted(model.slabs, key=lambda s: (s.storey, s.id)):
            rect = polygon_rect(slab.polygon)
            area = rect[2] * rect[3]
            if area <= 0.0:
                continue
            overlap = 0.0
            hit = []  # type: List[str]
            for room in unknown:
                if room.storey != slab.storey:
                    continue
                part = _rect_overlap_area(rect, polygon_rect(room.polygon))
                if part > GEOM_TOL_M:
                    overlap += part
                    hit.append(room.id)
            if overlap > GEOM_TOL_M:
                case.area.append(
                    AreaLoad(
                        panel_id=slab.id,
                        q_kpa=allowance * min(overlap / area, 1.0),
                        kind=CaseKind.DEAD,
                        source=_SRC_ALLOWANCE,
                        note="%.1f kPa over %.2f m2 unknown interior" % (allowance, overlap),
                    )
                )
                unknown_ids.extend(hit)
    if unknown_ids:
        model.add_warning(
            "W_UNIT_NO_PLAN",
            "interior unknown: %.1f kPa partition allowance applied" % allowance,
            sorted(set(unknown_ids)),
            stage=_STAGE,
        )

    # -- parapet on the roof perimeter (toggle) ----------------------------
    parapet_default = roof_ctx is None
    if bool(opts.get("parapet", parapet_default)):
        parapet_t = float(is875.dead_load_default("parapet_thickness_m"))
        gamma_brick = is875.part1_unit_weight("brick_masonry")
        w_par = (gamma_brick * parapet_t + plaster_two_faces) * parapet_h
        for wall in sorted(model.walls_on(top_storey), key=lambda w: w.id):
            if wall.role != WallRole.EXTERIOR:
                continue
            axis = wall_axis(wall)
            if axis is None:
                continue
            orient, pos, s0, s1 = axis
            align = 0.5 * max(wall.thickness_m, 0.23) + _ALIGN_EXTRA_M
            beams = colinear_beams(model, top_storey, orient, pos, s0, s1, align)
            members = [(b, lo, hi) for b, lo, hi in beams]  # type: List[Tuple[Any, float, float]]
            if not members:
                members = [(wall, s0, s1)]
            case.line.extend(
                line_loads_for_edge(members, s0, s1, "uniform", w_par, 0.0, CaseKind.DEAD, _SRC_PARAPET, note="parapet")
            )

    # -- pitched roof (projected-area v1) ----------------------------------
    if roof_ctx is not None:
        surface_key = str(opts.get("roof_surface", "roof_sheet_light"))
        q_surface = is875.part1_area_load(surface_key)
        q_plan = q_surface / roof_ctx["cos"]
        loads, bare = pitched_roof_line_loads(
            model, roof_ctx, q_plan, CaseKind.DEAD, _SRC_ROOF, note="roof %s" % roof_ctx["type"]
        )
        case.line.extend(loads)
        # closest registered code for the projected-area statement: the roof
        # is measured on plan, not on slope
        model.add_warning(
            "N_SLOPE_ALLOWANCE_FLAT",
            "roof_model: projected-area v1; %s roof as plan pressure %.3f kPa on the eave members"
            % (roof_ctx["type"], q_plan),
            (),
            stage=_STAGE,
        )
        if bare:
            model.add_warning(
                "E_TRANSFER_REQUIRED",
                "pitched roof eave edge(s) found no supporting member: " + ", ".join(sorted(bare)),
                (),
                stage=_STAGE,
            )

    return case
