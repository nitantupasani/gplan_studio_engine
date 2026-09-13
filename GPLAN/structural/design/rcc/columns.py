"""RC column design to IS 456 Cl 25, 39 and 26.5.3 (spec section 4).

One entry point, `design_column(forces, geom, ctx)`, taking the `ColumnForces`
that `analysis/to_column_forces` hands over and the section `placement/frame.py`
already put in the model, and returning the one `DesignResult` shape
`design/common.py` owns. It never raises on a column that cannot be made to
work: the ladder is walked, the section is grown by the shared `ResizePolicy`,
and what comes back is a fully populated result with `status` fail and the
check that governed (finding 6, disclose never hide).

The sequence, and where each number comes from:

1. Slenderness, Cl 25.1.2, on the effective lengths (the analysis hands over the
   unsupported length; the effective length factor is a context knob defaulting
   to 1.0, the braced-and-restrained value of Table 28). Cl 25.3.1 caps the
   unsupported length at 60 times the least dimension and that IS a check.
2. Design moments per axis: max(frame moment, Pu x e_min per Cl 25.4) plus the
   Cl 39.7.1 additional moment where that plane is slender, reduced by the
   Cl 39.7.1.1 factor k. k needs Puz and the balanced load Pb, both of which
   depend on the steel, so it is recomputed for every rung of the ladder rather
   than frozen at an assumed percentage.
3. The ladder: symmetric perimeter layouts from the 0.8 percent floor of
   Cl 26.5.3.1 upwards, each one picked by the shared `common.pick_bars` and
   then arranged on the four faces, ordered by steel area. Each is checked
   biaxially through Cl 39.6 with Mux1 and Muy1 read off the interaction domain
   at the design Pu and alpha_n from Puz. The first layout that passes wins.
4. Exhausted at the 6 percent ceiling (or at the largest layout the section can
   actually hold, which is often the real stop and is disclosed as such): the
   section grows by `ResizePolicy.column_step_mm` on its smaller side, up to
   `column_cap_mm`, and every step lands in `resize_history`. Past the cap the
   result is a fail carrying the last attempt in full.
5. Ties to Cl 26.5.3.2, with the leg pattern derived from the arrangement: the
   perimeter tie supports the corners, and an interior bar more than 150 mm
   clear of a laterally supported bar gets a cross tie.
6. The IS 13920 ductile overlay is not written here. When it applies it is
   handed to `design/rcc/detailing.apply_13920`, imported late so a build
   without that sibling still designs the column and says in a note and a
   `joint_check_manual` referral what did not run. What the overlay is told
   about the member is `ColumnGeometry.role` (`COLUMN_ROLES`): a `tie` column is
   an IS 4326 confining column, whose section is the masonry wall it ties and
   not a frame section, so the overlay's Cl 7.1 frame geometry clause is not
   read against it. Steps 1 to 5 above are identical for both roles, and `frame`
   is the default, so the exemption can only ever be taken deliberately.

Interaction domain. Critic finding 31 removed `structuralcodes` from v1, so
`_interaction_fallback.py` IS the interaction engine: a strain-plane fiber
sweep with the IS 456 Cl 38.1 design curves. Every result says so in a note.
Swapping in an adapter later means changing the `_ENGINE` import, nothing else.

Units. kN and kNm come in, N and mm and MPa are used throughout, and the only
things that leave are the DesignResult fields, all suffixed. Determinism: the
ladder is a sorted list, the search is a first-match walk over it, and the
domains are cached, so the same column designed twice returns an equal dict.

Cost. Two caches carry the run: the ladder, which depends on the section and
the cover rules but never on the load, and the interaction domain, which
depends on the section and the cage. A hundred columns over five distinct
sections measure about 180 ms on the development machine; a hundred columns
that share no section at all, which no real building produces, about 2.7 s.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ...analysis import ColumnForces
from ...codes import is13920, is456
from ...codes.trace import trace_into
from ..common import (
    CHECK_FAIL,
    RATIO_CAP,
    STATUS_FAIL,
    BarPrefs,
    DesignResult,
    ResizePolicy,
    bar_area_mm2,
    clear_width_mm,
    kn_to_n,
    knm_to_nmm,
    m_to_mm,
    min_bar_gap_mm,
    pick_bars,
    resolve_cover,
    round_down_mm,
)
from . import _interaction_fallback as _ENGINE

__all__ = [
    "COLUMN_DIAS_MM",
    "TIE_DIAS_MM",
    "PERIPHERY_SPACING_MM",
    "LATERAL_SUPPORT_MM",
    "TIE_SPACING_MODULE_MM",
    "MAX_LONG_BARS",
    "ColumnContext",
    "ColumnGeometry",
    "BarArrangement",
    "column_context",
    "column_geometry",
    "arrange_bars",
    "tie_legs",
    "design_column",
]


# ---------------------------------------------------------------------------
# catalogue and clause constants
# ---------------------------------------------------------------------------

#: Longitudinal bar sizes offered to a column (spec section 4: 12/16/20/25),
#: extended by 32 because the 6 percent ceiling of a large column needs it.
COLUMN_DIAS_MM = (12, 16, 20, 25, 32)

#: Tie sizes; the Cl 26.5.3.2 minimum of max(6, dia/4) is rounded up into this.
TIE_DIAS_MM = (8, 10, 12)

#: IS 456 Cl 26.5.3.1: bars further apart than this along the periphery need an
#: intermediate bar. Read from the clause callable, kept here for the ladder
#: filter that runs before any clause is called.
PERIPHERY_SPACING_MM = 300.0

#: A longitudinal bar further than this, clear, from a laterally supported bar
#: needs its own tie leg (the detailing rule the spec states for the leg
#: pattern; Cl 26.5.3.2 itself is written as corner plus alternate bars).
LATERAL_SUPPORT_MM = 150.0

#: Tie pitch is rounded DOWN to this module, never up past the clause limit.
TIE_SPACING_MODULE_MM = 5.0

#: What the placed column IS, carried on `ColumnGeometry.role` by the caller.
#: `frame` is a moment frame column and the default: everything the IS 13920
#: overlay says about frame geometry applies to it. `tie` is an IS 4326
#: confining column cast against masonry, whose 230 x t section is set by the
#: wall it confines and not by IS 13920 Cl 7.1, which governs frame members
#: subjected to bending and axial load. The role changes the ductile overlay's
#: geometry clause and nothing else: the IS 456 axial, biaxial and detailing
#: design is identical, and so are the Cl 7.6 confining hoops.
COLUMN_ROLE_FRAME = "frame"
COLUMN_ROLE_TIE = "tie"
COLUMN_ROLES = (COLUMN_ROLE_FRAME, COLUMN_ROLE_TIE)

#: Bars in one column cage. The ladder is bounded, and no detailer puts more
#: than this in a house-scale column.
MAX_LONG_BARS = 20

#: Ladder rung, as a fraction of the gross area: 0.1 percent of Ag.
LADDER_STEP_FRACTION = 0.001

#: Sections whose ladders are kept. A storey of identical columns enumerates
#: once; the cache is bounded rather than grown.
_LADDER_CACHE_SIZE = 128

#: Slenderness at or above which Cl 39.7 additional moments apply. Cl 25.1.2
#: calls a column short when both ratios are LESS than 12, so 12.0 itself is
#: slender and `_additional_moment` compares against this strictly.
SLENDER_LIMIT = 12.0

#: Eccentricity below which Cl 39.3 lets a column be designed as axially
#: loaded, as a fraction of the dimension in that plane.
AXIAL_ONLY_ECCENTRICITY_FRACTION = 0.05

_TOL = 1e-9
_AREA_TOL_MM2 = 1e-6
_IS456 = is456.CODE


# ---------------------------------------------------------------------------
# context and geometry (same shape as the sibling designers: a frozen
# dataclass, and a normalizer that accepts it, an options mapping or an object)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnContext:
    """Materials, exposure and policy for one column design.

    `effective_length_factor` multiplies the unsupported length the analysis
    reports; 1.0 is the braced, restrained-both-ends value of Table 28 and the
    result says the assumption was made.

    `beam_bar_dia_mm` is the largest beam longitudinal bar framing into the
    joint, which only the IS 13920 Cl 7.1 geometry check needs. It defaults to
    the smallest bar a beam is detailed with, because Cl 7.1 asks for 20 times
    that diameter and a pessimistic default would invent a failure on every
    column the orchestrator has not told about its beams. The assumption is
    stated in a note whenever the overlay runs.

    `sum_mb_nmm` is the beam capacity framing into the joint, which one column
    cannot see; without it the Cl 7.2.1 strong-column check reports itself not
    applicable. `stilt` marks a ground storey whose full height the ductile
    overlay confines.
    """

    fck_mpa: float = 25.0
    fy_mpa: float = 500.0
    exposure: str = "moderate"
    fire_rating_h: float = 0.0
    aggregate_mm: float = 20.0
    zone: str = "III"
    frame: str = "OMRF"
    is13920: str = "auto"
    effective_length_factor: float = 1.0
    beam_bar_dia_mm: float = 12.0
    sum_mb_nmm: float = 0.0
    stilt: bool = False
    policy: ResizePolicy = field(default_factory=ResizePolicy)


@dataclass(frozen=True)
class ColumnGeometry:
    """The placed column: section, height and identity, all mm.

    `role` is one of `COLUMN_ROLES` and defaults to a frame column, so a caller
    that says nothing gets the full frame treatment: the exemption is opt in,
    never a default that could quietly let a real frame column off Cl 7.1.
    """

    b_mm: float
    depth_mm: float
    height_mm: float
    clear_height_mm: float
    element_id: str = ""
    storey: int = 0
    role: str = COLUMN_ROLE_FRAME


_CTX_ALIASES = {
    "fck_mpa": ("fck_mpa", "fck"),
    "fy_mpa": ("fy_mpa", "fy"),
    "exposure": ("exposure",),
    "fire_rating_h": ("fire_rating_h", "fire_rating", "fire"),
    "aggregate_mm": ("aggregate_mm", "agg_mm", "aggregate"),
    "effective_length_factor": ("effective_length_factor", "k_effective", "eff_length_factor"),
    "beam_bar_dia_mm": ("beam_bar_dia_mm", "dia_beam_bar_mm"),
    "sum_mb_nmm": ("sum_mb_nmm",),
    "stilt": ("stilt", "soft_storey"),
}

#: (name, names inside the seismic block, names at the top level). The two are
#: kept apart because `system` means the ductility class inside `seismic` and
#: the structural system (rc_frame, load_bearing_masonry) outside it; reading
#: the outer one as a frame class would feed the code an unknown word.
_SEISMIC_ALIASES = (
    ("zone", ("zone",), ("zone", "seismic_zone")),
    ("frame", ("frame", "system", "ductility"), ("frame", "frame_type")),
    ("is13920", ("is13920",), ("is13920", "ductile_detailing", "ductile")),
)


def _lookup(source: Any, names: Sequence[str], nested: Sequence[str] = ("materials", "seismic")) -> Any:
    """First of `names` present on a mapping or an object, else None.

    Mappings are also searched one level down through `nested`, so the options
    block the API spec writes ({"materials": {"fck": 25}, "seismic": {...}})
    reaches the same fields as a flat context object.
    """
    if source is None:
        return None
    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        for key in nested:
            inner = source.get(key)
            if isinstance(inner, Mapping):
                for name in names:
                    if name in inner and inner[name] is not None:
                        return inner[name]
        return None
    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def column_context(ctx: Any = None) -> ColumnContext:
    """A ColumnContext from a ColumnContext, an options mapping, an object or None."""
    if isinstance(ctx, ColumnContext):
        return ctx
    base = ColumnContext()
    values = {}  # type: Dict[str, Any]
    for name, aliases in sorted(_CTX_ALIASES.items()):
        found = _lookup(ctx, aliases)
        values[name] = getattr(base, name) if found is None else found
    block = _lookup(ctx, ("seismic",), nested=())
    for name, inner_names, outer_names in _SEISMIC_ALIASES:
        found = _lookup(block, inner_names, nested=())
        if found is None:
            found = _lookup(ctx, outer_names, nested=())
        values[name] = getattr(base, name) if found is None else found
    policy = _lookup(ctx, ("policy", "resize_policy"))
    if isinstance(policy, Mapping):
        policy = ResizePolicy.from_dict(policy)
    elif not isinstance(policy, ResizePolicy):
        policy = base.policy
    return ColumnContext(
        fck_mpa=float(values["fck_mpa"]),
        fy_mpa=float(values["fy_mpa"]),
        exposure=str(values["exposure"]),
        fire_rating_h=float(values["fire_rating_h"]),
        aggregate_mm=float(values["aggregate_mm"]),
        zone=str(values["zone"]),
        frame=str(values["frame"]),
        is13920=str(values["is13920"]).strip().lower(),
        effective_length_factor=float(values["effective_length_factor"]),
        beam_bar_dia_mm=float(values["beam_bar_dia_mm"]),
        sum_mb_nmm=float(values["sum_mb_nmm"]),
        stilt=bool(values["stilt"]),
        policy=policy,
    )


def column_geometry(geom: Any, forces: Optional[ColumnForces] = None) -> ColumnGeometry:
    """A ColumnGeometry from the placed column, a mapping or an object.

    Section dimensions are mm and must be given (`b_mm` and `D_mm`, or the
    model's metre fields `width_m` and `depth_m`). The height falls back to the
    unsupported length the force envelope carries, and the clear height to the
    height, so a caller that knows only the section still gets a design.
    """
    if isinstance(geom, ColumnGeometry):
        return geom
    b_mm = _first_length_mm(geom, ("b_mm", "width_mm"), ("b_m", "width_m"))
    depth_mm = _first_length_mm(geom, ("D_mm", "depth_mm", "d_mm"), ("D_m", "depth_m"))
    if b_mm is None or depth_mm is None:
        raise ValueError("column geometry needs b_mm and D_mm (or the model's width_m and depth_m)")
    if b_mm <= 0.0 or depth_mm <= 0.0:
        raise ValueError("column b_mm and D_mm must be positive")
    height_mm = _first_length_mm(geom, ("height_mm", "length_mm"), ("height_m", "length_m"))
    if height_mm is None and forces is not None:
        height_mm = m_to_mm(max(float(forces.lex_m), float(forces.ley_m)))
    if not height_mm or height_mm <= 0.0:
        raise ValueError("column geometry needs a height (height_mm, or lex_m on the forces)")
    clear_mm = _first_length_mm(geom, ("clear_height_mm",), ("clear_height_m",))
    element_id = _lookup(geom, ("element_id", "id"), nested=())
    storey = _lookup(geom, ("storey",), nested=())
    return ColumnGeometry(
        b_mm=float(b_mm),
        depth_mm=float(depth_mm),
        height_mm=float(height_mm),
        clear_height_mm=float(clear_mm) if clear_mm else float(height_mm),
        element_id="" if element_id is None else str(element_id),
        storey=0 if storey is None else int(storey),
        role=_column_role(geom),
    )


def _column_role(geom: Any) -> str:
    """`role` off the placed column, defaulting to a frame column.

    A word this module does not know is not silently taken for a frame column
    and not silently taken for an exemption either: it raises, so a caller that
    invents a role finds out at the boundary instead of getting an overlay it
    did not ask for.
    """
    role = _lookup(geom, ("role",), nested=())
    if role is None:
        return COLUMN_ROLE_FRAME
    word = str(role).strip().lower()
    if word not in COLUMN_ROLES:
        raise ValueError(
            "column role " + repr(role) + " is not one of " + ", ".join(COLUMN_ROLES)
        )
    return word


def _first_length_mm(source: Any, mm_names: Sequence[str], m_names: Sequence[str]) -> Optional[float]:
    """A length in mm from the mm fields, else converted from the metre fields."""
    value = _lookup(source, mm_names, nested=())
    if value is not None:
        return float(value)
    value = _lookup(source, m_names, nested=())
    return None if value is None else m_to_mm(float(value))


def _forces_view(forces: Any) -> ColumnForces:
    """A ColumnForces from a ColumnForces, a column ForceEnvelope or a mapping."""
    if isinstance(forces, ColumnForces):
        return forces
    if getattr(forces, "element_type", None) == "column":
        from ...analysis import to_column_forces

        return to_column_forces(forces)
    pu = _lookup(forces, ("pu_kn", "pu"), nested=())
    return ColumnForces(
        pu_kn=0.0 if pu is None else float(pu),
        mux_knm=float(_lookup(forces, ("mux_knm", "mux"), nested=()) or 0.0),
        muy_knm=float(_lookup(forces, ("muy_knm", "muy"), nested=()) or 0.0),
        lex_m=float(_lookup(forces, ("lex_m", "lex"), nested=()) or 0.0),
        ley_m=float(_lookup(forces, ("ley_m", "ley"), nested=()) or 0.0),
        storey=int(_lookup(forces, ("storey",), nested=()) or 0),
    )


# ---------------------------------------------------------------------------
# bar arrangement: a symmetric cage on the four faces
# ---------------------------------------------------------------------------


class BarArrangement(NamedTuple):
    """A symmetric perimeter cage: what is on each face and where every bar sits.

    `bars_b` counts the bars along ONE face of length b (corners included) and
    `bars_d` the same along a face of length D, so the cage holds
    2 bars_b + 2 bars_d - 4 bars. `positions_mm` are (x, y) from the centroid,
    x along b.
    """

    count: int
    dia_mm: int
    bars_b: int
    bars_d: int
    spacing_b_mm: float
    spacing_d_mm: float
    tie_dia_mm: float
    cover_mm: float
    asc_mm2: float
    positions_mm: Tuple[Tuple[float, float], ...]


def _tie_dia_for(dia_long_mm: float) -> float:
    """Smallest catalogue tie that meets Cl 26.5.3.2, mm."""
    required = max(6.0, float(dia_long_mm) / 4.0)
    for dia in TIE_DIAS_MM:
        if float(dia) >= required - _TOL:
            return float(dia)
    return float(TIE_DIAS_MM[-1])


def _face_split(count: int, b_mm: float, depth_mm: float) -> Tuple[int, int]:
    """Bars per b-face and per D-face for an even total, in face proportion."""
    sides = count // 2 + 2
    share = float(b_mm) / (float(b_mm) + float(depth_mm))
    bars_b = int(math.floor(sides * share + 0.5))
    bars_b = min(max(bars_b, 2), sides - 2)
    return bars_b, sides - bars_b


def arrange_bars(
    count: int,
    dia_mm: int,
    b_mm: float,
    depth_mm: float,
    cover_mm: float,
    agg_mm: float,
) -> Optional[BarArrangement]:
    """Lay `count` bars of `dia_mm` symmetrically on the four faces, or None.

    None means the cage does not fit: a face gap below IS 456 Cl 26.3.2, or a
    periphery spacing above the Cl 26.5.3.1 limit of 300 mm that another bar
    would have to fix. The caller walks on to the next rung of the ladder.

    The Cl 26.3.2 gap is applied to every face that carries two bars or more.
    Two corner bars on a 150 mm face still have one clear gap between them, so
    a face is never exempt for being narrow: `design_column` grows the section
    instead, and says so in `resize_history`.
    """
    total = int(count)
    if total < 4 or total % 2 or int(dia_mm) <= 0:
        return None
    dia = int(dia_mm)
    tie = _tie_dia_for(dia)
    cover = max(float(cover_mm), float(dia))
    inset = cover + tie + 0.5 * dia
    span_b = float(b_mm) - 2.0 * inset
    span_d = float(depth_mm) - 2.0 * inset
    if span_b <= 0.0 or span_d <= 0.0:
        return None

    bars_b, bars_d = _face_split(total, b_mm, depth_mm)
    if bars_b < 2 or bars_d < 2:
        return None
    spacing_b = span_b / (bars_b - 1) if bars_b > 1 else span_b
    spacing_d = span_d / (bars_d - 1) if bars_d > 1 else span_d
    gap = min_bar_gap_mm(dia, agg_mm)
    # Cl 26.3.2 governs every clear gap on the face, the single gap between two
    # corner bars included: a face carrying exactly two bars has one real gap,
    # and on a thin section that gap is the one that closes first. The ladder
    # loses a rung rather than shipping a cage that cannot be poured, and
    # `design_column` walks its resize ladder when the section runs out of rungs.
    if bars_b >= 2 and spacing_b - dia < gap - _TOL:
        return None
    if bars_d >= 2 and spacing_d - dia < gap - _TOL:
        return None
    if spacing_b > PERIPHERY_SPACING_MM + _TOL or spacing_d > PERIPHERY_SPACING_MM + _TOL:
        return None

    # Written about the centreline rather than accumulated from one edge, so
    # the two halves of the cage are exact mirrors and the section signature the
    # interaction cache keys on is the same however the column was reached.
    xs = [(index - 0.5 * (bars_b - 1)) * spacing_b for index in range(bars_b)]
    ys = [(index - 0.5 * (bars_d - 1)) * spacing_d for index in range(bars_d)]
    positions = []  # type: List[Tuple[float, float]]
    for x in xs:
        positions.append((x, ys[0]))
        positions.append((x, ys[-1]))
    for y in ys[1:-1]:
        positions.append((xs[0], y))
        positions.append((xs[-1], y))
    if len(positions) != total:
        return None
    return BarArrangement(
        count=total,
        dia_mm=dia,
        bars_b=bars_b,
        bars_d=bars_d,
        spacing_b_mm=spacing_b,
        spacing_d_mm=spacing_d,
        tie_dia_mm=tie,
        cover_mm=cover,
        asc_mm2=total * bar_area_mm2(dia),
        positions_mm=tuple(sorted(positions)),
    )


def _internal_legs(bars_on_face: int, clear_spacing_mm: float) -> int:
    """Cross ties one face needs so no bar is unsupported and out of reach.

    The perimeter tie holds the two corners. A bar within `LATERAL_SUPPORT_MM`
    clear of a supported bar is held by it; anything further needs its own leg.
    The scan is the standard left-to-right cover of a path and is bounded by the
    bar count.
    """
    count = int(bars_on_face)
    if count <= 2:
        return 0
    if clear_spacing_mm > LATERAL_SUPPORT_MM + _TOL:
        return count - 2
    covered = [False] * count
    for index in (0, 1, count - 2, count - 1):
        covered[index] = True
    ties = 0
    index = 1
    while index < count - 1:
        if covered[index]:
            index += 1
            continue
        place = min(index + 1, count - 2)
        ties += 1
        for near in (place - 1, place, place + 1):
            if 0 <= near < count:
                covered[near] = True
        index += 1
    return ties


def tie_legs(arrangement: BarArrangement) -> Tuple[int, int]:
    """(legs across b, legs across D) for the cage, perimeter tie included.

    The rule is the 150 mm reach of a laterally supported bar, so the aggregate
    size that governs the Cl 26.3.2 gaps plays no part here.
    """
    clear_b = arrangement.spacing_b_mm - arrangement.dia_mm
    clear_d = arrangement.spacing_d_mm - arrangement.dia_mm
    # A leg that crosses b engages one bar on each D-face, so it is the D-face
    # bars that decide how many of them there are.
    return (
        2 + _internal_legs(arrangement.bars_d, clear_d),
        2 + _internal_legs(arrangement.bars_b, clear_b),
    )


# ---------------------------------------------------------------------------
# one trial section and its ladder
# ---------------------------------------------------------------------------


class _Trial(NamedTuple):
    """Everything one attempt at a section needs, all mm and N.

    `role` rides along so the ductile overlay can tell a frame column from an
    IS 4326 confining column; `_grow` carries it through `_replace`, so it
    survives every rung of the resize ladder.
    """

    b_mm: float
    depth_mm: float
    height_mm: float
    clear_height_mm: float
    lex_mm: float
    ley_mm: float
    ctx: ColumnContext
    role: str = COLUMN_ROLE_FRAME


class _Demand(NamedTuple):
    """The factored actions, converted once at the boundary."""

    pu_n: float
    mux_nmm: float
    muy_nmm: float


class _Eval(NamedTuple):
    """The numbers one candidate produced; the check rows are written from it."""

    puz_n: float
    pb_x_n: float
    pb_y_n: float
    k_x: float
    k_y: float
    ma_x_nmm: float
    ma_y_nmm: float
    e_min_x_mm: float
    e_min_y_mm: float
    mux_design_nmm: float
    muy_design_nmm: float
    mux1_nmm: float
    muy1_nmm: float
    alpha_n: float
    ratio: float
    pu_axial_n: float
    axial_only: bool
    ok: bool


def _ladder(trial: _Trial) -> Tuple[Sequence[BarArrangement], str]:
    """Every symmetric cage this section can hold, ascending in steel area.

    Nothing in the ladder depends on the load, only on the section and the
    cover rules, so it is cached on exactly those five values: a storey of
    identical columns enumerates once. The cages are immutable NamedTuples, so
    handing the same tuple to every caller is safe.
    """
    ctx = trial.ctx
    return _ladder_for(
        trial.b_mm,
        trial.depth_mm,
        ctx.exposure,
        ctx.fire_rating_h,
        ctx.aggregate_mm,
    )


@functools.lru_cache(maxsize=_LADDER_CACHE_SIZE)
def _ladder_for(
    b_mm: float,
    depth_mm: float,
    exposure: str,
    fire_rating_h: float,
    aggregate_mm: float,
) -> Tuple[Tuple[BarArrangement, ...], str]:
    """The cached body of `_ladder`; see it for what the rungs are.

    Rungs are 0.1 percent of the gross area apart between the Cl 26.5.3.1 floor
    and ceiling. Each rung asks `common.pick_bars` for HALF the cage against
    half the clear perimeter: a cage symmetric about both axes is two identical
    halves, so picking the half guarantees the even count the arrangement needs
    without asking the shared picker to know anything about columns, and the
    area excess it scores is the same for the half as for the whole. What comes
    back is kept only if it actually arranges on the four faces. The note says
    where the ladder really stopped, which for a small section is the packing,
    not the 6 percent.

    The picker scores area excess and `_arrange_up` then adds pairs of bars for
    the Cl 26.5.3.1 periphery rule, so on a large section the cheapest rung it
    reaches can sit well above the floor: on 600 x 600 it starts at 1.005
    percent while 10-20 (0.873) and 16-16 (0.894) both arrange legally. So
    `_floor_rungs` scans the catalogue directly for the legal cages below that
    and the ladder really does start at the floor, not at whatever the picker
    happened to reach.
    """
    ag = float(b_mm) * float(depth_mm)
    limits = is456.cl_26_5_3_1__long_steel_limits(ag)
    base_cover = resolve_cover("column", exposure, fire_rating_h, 0.0).cover_mm
    prefs = _prefs(b_mm, depth_mm, base_cover, aggregate_mm)
    if prefs is None:
        return (), "section is too small to hold the four bars Cl 26.5.3.1 requires"
    width = _half_perimeter_mm(b_mm, depth_mm, base_cover)

    step = max(ag * LADDER_STEP_FRACTION, 1.0)
    rungs = int(math.floor((limits.asc_max_mm2 - limits.asc_min_mm2) / step)) + 1
    seen = set()  # type: set
    out = []  # type: List[BarArrangement]
    for index in range(max(rungs, 1)):
        target = min(limits.asc_min_mm2 + index * step, limits.asc_max_mm2)
        layout = pick_bars(0.5 * target, width, prefs)
        if not layout.ok:
            continue
        count = 2 * layout.count
        dia = layout.max_dia_mm
        if count > MAX_LONG_BARS:
            continue
        if (count, dia) in seen:
            continue
        seen.add((count, dia))
        arrangement = _arrange_up(count, dia, b_mm, depth_mm, base_cover, aggregate_mm, limits.asc_max_mm2)
        if arrangement is None:
            continue
        if (arrangement.count, dia) in seen and arrangement.count != count:
            continue
        seen.add((arrangement.count, dia))
        if arrangement.asc_mm2 < limits.asc_min_mm2 - _AREA_TOL_MM2:
            continue
        out.append(arrangement)
    out.extend(_floor_rungs(b_mm, depth_mm, base_cover, aggregate_mm, limits, out, seen))
    out.sort(key=lambda item: (item.asc_mm2, item.count, item.dia_mm))
    if not out:
        return (), "no symmetric cage between 0.8 and 6 percent fits this section"
    top = out[-1]
    note = (
        "longitudinal steel ladder ran "
        + _pct(out[0].asc_mm2 / ag)
        + " to "
        + _pct(top.asc_mm2 / ag)
        + " in "
        + str(len(out))
        + " layouts"
    )
    if top.asc_mm2 < limits.asc_max_mm2 - _AREA_TOL_MM2:
        if top.count >= MAX_LONG_BARS:
            note += (
                "; the 6 percent ceiling of Cl 26.5.3.1 was not reached because the policy cap of "
                + str(MAX_LONG_BARS)
                + " longitudinal bars stopped enumeration"
            )
        else:
            note += "; the 6 percent ceiling of Cl 26.5.3.1 was not reached because the cage stopped fitting first"
    return tuple(out), note


def _floor_rungs(
    b_mm: float,
    depth_mm: float,
    cover_mm: float,
    agg_mm: float,
    limits: Any,
    reached: Sequence[BarArrangement],
    seen: set,
) -> List[BarArrangement]:
    """Legal cages cheaper than the cheapest rung the picker reached.

    `pick_bars` optimises area excess against a target and `_arrange_up` then
    inflates the count for the Cl 26.5.3.1 periphery rule, so the lowest rung
    the search reaches is not necessarily the cheapest cage the section can
    legally hold. This is the direct answer: every catalogue diameter against
    every even count up to `MAX_LONG_BARS`, kept when the area is inside the
    Cl 26.5.3.1 band, the cage arranges on the four faces, and it is cheaper
    than anything already on the ladder. Bounded by 5 diameters x 9 counts, and
    the caller caches the whole ladder, so it costs one pass per section.

    Nothing is added when the picker found no rung at all: an empty ladder means
    the section cannot hold a cage and `design_column` grows it.
    """
    if not reached:
        return []
    cheapest = min(item.asc_mm2 for item in reached)
    found = []  # type: List[BarArrangement]
    for dia in COLUMN_DIAS_MM:
        area = bar_area_mm2(dia)
        for count in range(4, MAX_LONG_BARS + 1, 2):
            asc = count * area
            if asc < limits.asc_min_mm2 - _AREA_TOL_MM2:
                continue
            if asc >= cheapest - _AREA_TOL_MM2:
                break
            if asc > limits.asc_max_mm2 + _AREA_TOL_MM2:
                break
            if (count, int(dia)) in seen:
                continue
            arrangement = arrange_bars(count, dia, b_mm, depth_mm, cover_mm, agg_mm)
            if arrangement is None:
                continue
            seen.add((count, int(dia)))
            found.append(arrangement)
    return found


def _arrange_up(
    count: int,
    dia_mm: int,
    b_mm: float,
    depth_mm: float,
    cover_mm: float,
    agg_mm: float,
    asc_max_mm2: float,
) -> Optional[BarArrangement]:
    """Arrange this cage, adding pairs of bars until the periphery rule is met.

    `pick_bars` chooses the diameter and the area; it knows nothing about the
    Cl 26.5.3.1 rule that bars on the periphery may not stand more than 300 mm
    apart, which on a big section is what really sets the bar count. Adding two
    bars at a time is the detailer's answer and keeps the cage symmetric. The
    walk is bounded by the cage limit and stops as soon as the extra pair would
    break the Cl 26.3.2 gap or run past the 6 percent ceiling.
    """
    area = bar_area_mm2(dia_mm)
    total = int(count)
    while total <= MAX_LONG_BARS and total * area <= asc_max_mm2 + _AREA_TOL_MM2:
        arrangement = arrange_bars(total, dia_mm, b_mm, depth_mm, cover_mm, agg_mm)
        if arrangement is not None:
            return arrangement
        total += 2
    return None


def _prefs(b_mm: float, depth_mm: float, cover_mm: float, agg_mm: float) -> Optional[BarPrefs]:
    """Preferences for HALF a column cage, or None when four bars will not fit.

    Half, because `_ladder` asks the shared picker for half the steel in half
    the perimeter: `min_bars_per_layer` 2 is the half of the Cl 26.5.3.1
    four-bar minimum, and the maximum is half of what the four faces can hold
    at the smallest catalogue diameter.

    No `max_clear_spacing_mm` is set. The picker measures clear spacing across a
    straight row, and a half cage is an L round two faces, so on four bars the
    proxy reads the full half perimeter as one gap and rejects a cage that is
    perfectly legal. The Cl 26.5.3.1 periphery rule is applied exactly instead,
    on the real face spacings, by `arrange_bars`.
    """
    smallest = min(COLUMN_DIAS_MM)
    tie = _tie_dia_for(smallest)
    gap = min_bar_gap_mm(smallest, agg_mm)
    per_face = []
    for dimension in (b_mm, depth_mm):
        span = clear_width_mm(dimension, max(cover_mm, smallest), tie)
        if span < smallest:
            return None
        per_face.append(max(2, int(math.floor((span + gap) / (smallest + gap)))))
    total = min(MAX_LONG_BARS, 2 * per_face[0] + 2 * per_face[1] - 4)
    if total < 4:
        return None
    return BarPrefs(
        dias_mm=COLUMN_DIAS_MM,
        min_dia_mm=12,
        min_bars_per_layer=2,
        max_bars_per_layer=total // 2,
        max_layers=1,
        max_distinct_dias=1,
        agg_mm=agg_mm,
    )


def _half_perimeter_mm(b_mm: float, depth_mm: float, cover_mm: float) -> float:
    """Half the clear perimeter, the width `pick_bars` sizes half a cage in, mm.

    A column cage is not a row of bars, so this is a proxy: it lets the shared
    picker reject a group the perimeter could never hold at the Cl 26.3.2 gaps.
    The binding test is `arrange_bars`, which packs the actual four faces and
    applies the Cl 26.5.3.1 periphery rule to the real spacings.
    """
    tie = _tie_dia_for(min(COLUMN_DIAS_MM))
    return clear_width_mm(b_mm, cover_mm, tie) + clear_width_mm(depth_mm, cover_mm, tie)


def _section_of(trial: _Trial, arrangement: BarArrangement) -> _ENGINE.RectSection:
    """The interaction engine's view of this trial section with this cage."""
    area = bar_area_mm2(arrangement.dia_mm)
    return _ENGINE.rect_section(
        trial.b_mm,
        trial.depth_mm,
        trial.ctx.fck_mpa,
        trial.ctx.fy_mpa,
        [(x, y, area) for x, y in arrangement.positions_mm],
    )


def _evaluate(trial: _Trial, arrangement: BarArrangement, demand: _Demand) -> _Eval:
    """Check one cage against the demand. Traced when a sink is open, else silent.

    The design search runs this with no sink so the ladder does not fill the
    report with the layouts it rejected; the winning cage is run through it once
    more inside the sink, which is where the trace and the check rows come from.
    """
    ctx = trial.ctx
    section = _section_of(trial, arrangement)
    asc = section.asc_mm2
    ac = max(section.ac_mm2, _TOL)
    pu = demand.pu_n

    puz = is456.cl_39_6__puz(ctx.fck_mpa, ctx.fy_mpa, ac, asc)
    pu_axial = is456.cl_39_3__pu_axial(ctx.fck_mpa, ctx.fy_mpa, ac, asc)

    e_min_x = is456.cl_25_4__e_min(trial.height_mm, trial.depth_mm)
    e_min_y = is456.cl_25_4__e_min(trial.height_mm, trial.b_mm)

    pb_x = _ENGINE.balanced_point(section, _ENGINE.THETA_X).pu_n
    pb_y = _ENGINE.balanced_point(section, _ENGINE.THETA_Y).pu_n

    ma_x, k_x = _additional_moment(pu, trial.depth_mm, trial.lex_mm, puz, pb_x)
    ma_y, k_y = _additional_moment(pu, trial.b_mm, trial.ley_mm, puz, pb_y)

    mux = max(abs(demand.mux_nmm), abs(pu) * e_min_x) + ma_x
    muy = max(abs(demand.muy_nmm), abs(pu) * e_min_y) + ma_y

    # A cage that cannot carry the axial load alone has no moment capacity
    # either, so the domain is not swept for it: that is what makes the ladder
    # cheap on an overloaded column, where every rung fails this way.
    alpha_n = is456.cl_39_6__alpha_n(pu, puz)
    if pu >= puz:
        mux1 = 0.0
        muy1 = 0.0
    else:
        mux1 = _ENGINE.mu_capacity(section, pu, _ENGINE.THETA_X)
        muy1 = _ENGINE.mu_capacity(section, pu, _ENGINE.THETA_Y)
    if mux1 > 0.0 and muy1 > 0.0:
        ratio = is456.cl_39_6__biaxial_ratio(mux, muy, mux1, muy1, alpha_n)
    else:
        ratio = RATIO_CAP

    axial_only = (
        abs(demand.mux_nmm) <= _TOL
        and abs(demand.muy_nmm) <= _TOL
        and ma_x <= _TOL
        and ma_y <= _TOL
        and e_min_x <= AXIAL_ONLY_ECCENTRICITY_FRACTION * trial.depth_mm + _TOL
        and e_min_y <= AXIAL_ONLY_ECCENTRICITY_FRACTION * trial.b_mm + _TOL
    )
    ok = ratio <= 1.0 + _TOL and pu <= puz + _TOL and (not axial_only or pu <= pu_axial + _TOL)
    return _Eval(
        puz_n=puz,
        pb_x_n=pb_x,
        pb_y_n=pb_y,
        k_x=k_x,
        k_y=k_y,
        ma_x_nmm=ma_x,
        ma_y_nmm=ma_y,
        e_min_x_mm=e_min_x,
        e_min_y_mm=e_min_y,
        mux_design_nmm=mux,
        muy_design_nmm=muy,
        mux1_nmm=mux1,
        muy1_nmm=muy1,
        alpha_n=alpha_n,
        ratio=ratio,
        pu_axial_n=pu_axial,
        axial_only=axial_only,
        ok=ok,
    )


def _additional_moment(
    pu_n: float,
    dim_mm: float,
    le_mm: float,
    puz_n: float,
    pb_n: float,
) -> Tuple[float, float]:
    """(Ma, k) for one plane: zero when the plane is not slender, Cl 39.7.1.

    The boundary is the one `is456.cl_25_1_2__slenderness` draws: Cl 25.1.2 lets
    a column be treated as short when the ratio is LESS than 12, so a plane at
    exactly 12 is slender and carries the Cl 39.7.1 additional moment. The
    comparison is strict for that reason, and le/dim lands on 12.0 exactly for
    every round metric pair (2.4/200, 3.0/250, 3.6/300 and so on).

    k is the Cl 39.7.1.1 reduction, which needs Puz and the balanced load of
    THIS cage. Where the balanced load is not below Puz the clause has no valid
    k and the full additional moment is kept, which is the conservative side.
    """
    if dim_mm <= 0.0 or le_mm / dim_mm < SLENDER_LIMIT:
        return 0.0, 1.0
    ma = is456.cl_39_7_1__additional_moment(abs(pu_n), dim_mm, le_mm)
    if puz_n > pb_n + _TOL:
        k = is456.cl_39_7_1_1__k(abs(pu_n), puz_n, pb_n)
    else:
        k = 1.0
    return ma * k, k


# ---------------------------------------------------------------------------
# the designer
# ---------------------------------------------------------------------------


def design_column(forces: Any, geom: Any, ctx: Any = None) -> DesignResult:
    """Design one RC column lift and return the shared DesignResult.

    `forces` is a `ColumnForces` (or a column `ForceEnvelope`, or a mapping with
    the same names), `geom` the placed section, `ctx` the options block. The
    result always comes back populated: a column that cannot be made to work
    carries `status` fail, its governing check and the last section tried.
    """
    view = _forces_view(forces)
    geometry = column_geometry(geom, view)
    context = column_context(ctx)
    demand = _Demand(
        pu_n=kn_to_n(view.pu_kn),
        mux_nmm=knm_to_nmm(view.mux_knm),
        muy_nmm=knm_to_nmm(view.muy_knm),
    )
    result = DesignResult(
        element_id=geometry.element_id,
        element_type="column",
        materials={"fck_mpa": float(context.fck_mpa), "fy_mpa": float(context.fy_mpa)},
    )

    trial = _trial_for(geometry, context, view)
    history = []  # type: List[Dict[str, Any]]
    chosen = None  # type: Optional[Tuple[BarArrangement, _Eval]]
    fallback = None  # type: Optional[Tuple[BarArrangement, _Eval]]
    ladder_note = ""
    stop = ""
    iterations = max(1, int(context.policy.max_iters))
    attempts = 0
    pending = None  # type: Optional[Dict[str, Any]]

    while True:
        rungs, ladder_note = _ladder(trial)
        best = None  # type: Optional[Tuple[BarArrangement, _Eval]]
        for arrangement in rungs:
            evaluated = _evaluate(trial, arrangement, demand)
            best = (arrangement, evaluated)
            if evaluated.ok:
                chosen = best
                break
        # The step that produced THIS section is recorded only now, once the
        # section has actually been designed, so `resize_history` never claims a
        # size the result does not carry.
        if pending is not None:
            history.append(pending)
            pending = None
        if chosen is not None:
            break
        fallback = best
        attempts += 1
        if attempts >= iterations:
            stop = "the resize policy stopped at its " + str(iterations) + " iteration limit"
            break
        grown = _grow(trial, context)
        if grown is None:
            stop = "the resize policy reached its " + _num(context.policy.column_cap_mm, 0) + " mm cap"
            break
        pending = {
            "from": {"b_mm": trial.b_mm, "D_mm": trial.depth_mm},
            "to": {"b_mm": grown.b_mm, "D_mm": grown.depth_mm},
            "reason": _resize_reason(best),
        }
        trial = grown

    entries = []  # type: List[Any]
    with trace_into(entries):
        _emit(result, trial, demand, chosen, fallback, history, ladder_note, stop, context)
    result.trace = entries
    return result


def _trial_for(geometry: ColumnGeometry, context: ColumnContext, forces: ColumnForces) -> _Trial:
    """The first attempt: the placed section with the effective lengths applied."""
    factor = float(context.effective_length_factor)
    lex = m_to_mm(float(forces.lex_m)) * factor
    ley = m_to_mm(float(forces.ley_m)) * factor
    if lex <= 0.0:
        lex = geometry.height_mm * factor
    if ley <= 0.0:
        ley = geometry.height_mm * factor
    return _Trial(
        b_mm=geometry.b_mm,
        depth_mm=geometry.depth_mm,
        height_mm=geometry.height_mm,
        clear_height_mm=geometry.clear_height_mm,
        lex_mm=lex,
        ley_mm=ley,
        ctx=context,
        role=geometry.role,
    )


def _grow(trial: _Trial, context: ColumnContext) -> Optional[_Trial]:
    """The next section up the resize ladder, or None at the cap.

    The smaller side grows first, which alternates the axes on a square column
    and drives a rectangular one back towards the IS 13920 Cl 7.1.2 side ratio
    of 0.45 rather than away from it.
    """
    step = float(context.policy.column_step_mm)
    cap = float(context.policy.column_cap_mm)
    b, depth = trial.b_mm, trial.depth_mm
    if b <= depth + _TOL:
        if b + step > cap + _TOL:
            return None
        b = b + step
    else:
        if depth + step > cap + _TOL:
            return None
        depth = depth + step
    return trial._replace(b_mm=b, depth_mm=depth)


def _resize_reason(best: Optional[Tuple[BarArrangement, _Eval]]) -> str:
    """Why the ladder ran out on this section."""
    if best is None:
        return "no symmetric cage between 0.8 and 6 percent fits this section"
    arrangement, evaluated = best
    cage = str(arrangement.count) + "-" + str(arrangement.dia_mm)
    if arrangement.count >= MAX_LONG_BARS:
        limit = "the policy cap of " + str(MAX_LONG_BARS) + " longitudinal bars (" + cage + ")"
    else:
        limit = "the largest cage that fits (" + cage + ")"
    if evaluated.ratio >= RATIO_CAP:
        return "Pu is at or above Puz with " + limit
    return "Cl 39.6 interaction " + _num(evaluated.ratio, 3) + " with " + limit


# ---------------------------------------------------------------------------
# emitting the result (the one traced pass)
# ---------------------------------------------------------------------------


def _emit(
    result: DesignResult,
    trial: _Trial,
    demand: _Demand,
    chosen: Optional[Tuple[BarArrangement, _Eval]],
    fallback: Optional[Tuple[BarArrangement, _Eval]],
    history: Sequence[Mapping[str, Any]],
    ladder_note: str,
    stop: str,
    context: ColumnContext,
) -> DesignResult:
    """Write the section, bars, ties, checks and trace of the final attempt."""
    for step in history:
        result.add_resize(step["from"], step["to"], str(step["reason"]))

    result.add_note(_ENGINE.engine_note())
    if ladder_note:
        result.add_note(ladder_note)
    if abs(context.effective_length_factor - 1.0) <= _TOL:
        result.add_note(
            "effective length taken as the unsupported length (Table 28 factor 1.0, braced and restrained "
            "at both ends); pass effective_length_factor to change it"
        )

    picked = chosen if chosen is not None else fallback
    result.section = {
        "b_mm": trial.b_mm,
        "D_mm": trial.depth_mm,
        "length_mm": trial.height_mm,
        "clear_height_mm": trial.clear_height_mm,
        "cover_mm": 0.0,
        "d_mm": 0.0,
    }

    slenderness = is456.cl_25_1_2__slenderness(trial.lex_mm, trial.ley_mm, trial.depth_mm, trial.b_mm)
    max_unsupported = is456.cl_25_3__max_unsupported(min(trial.b_mm, trial.depth_mm))
    result.add_check(
        "unsupported_length",
        _IS456 + " 25.3.1",
        trial.height_mm,
        max_unsupported,
        units="mm",
    )
    result.add_note(
        "slenderness lex/D "
        + _num(slenderness.lambda_x, 2)
        + ", ley/b "
        + _num(slenderness.lambda_y, 2)
        + (
            "; short column, Cl 39.7 additional moments do not apply"
            if slenderness.short
            else "; slender, Cl 39.7.1 additional moments applied where the ratio reaches 12"
        )
    )

    if picked is None:
        # Finding 25: cover is read from the section, so a refusal carries it
        # too, resolved without a bar diameter because there is no bar.
        bare = resolve_cover("column", context.exposure, context.fire_rating_h, 0.0)
        result.section["cover_mm"] = bare.cover_mm
        result.add_note(bare.note)
        result.add_note(ladder_note or "no cage fits")
        return result.fail_with(
            "bar_arrangement",
            "no symmetric cage between the Cl 26.5.3.1 limits fits a "
            + _num(trial.b_mm, 0)
            + " x "
            + _num(trial.depth_mm, 0)
            + " mm column",
            clause=_IS456 + " 26.5.3.1",
            demand=4.0,
            capacity=0.0,
            units="bars",
        )

    arrangement = picked[0]
    cover = resolve_cover("column", context.exposure, context.fire_rating_h, float(arrangement.dia_mm))
    limits = is456.cl_26_5_3_1__long_steel_limits(trial.b_mm * trial.depth_mm)
    ties = is456.cl_26_5_3_2__ties(float(arrangement.dia_mm), min(trial.b_mm, trial.depth_mm))

    # The one traced evaluation. It repeats exactly what the search already did
    # for this cage, so the numbers are the search's numbers and the trace holds
    # the winning layout alone, not the rungs the ladder rejected.
    evaluated = _evaluate(trial, arrangement, demand)

    # Cl 26.2.1.1 raises the bond stress by 25 percent for a bar in COMPRESSION,
    # so a compression Ld is a fifth shorter than the tension one and a bar that
    # is in tension at the design strain plane would be under-developed by it.
    # The schedule reads this ld_mm straight into its laps, so the value is
    # taken as compression bond only where the module has proved the whole
    # section is in compression, which is the Cl 39.3 axially loaded case
    # `_evaluate` already reports; wherever a design moment acts it is the
    # tension value, and the note says which was used.
    compression_bond = bool(evaluated.axial_only)
    ld = is456.cl_26_2_1__ld(
        float(arrangement.dia_mm), context.fy_mpa, context.fck_mpa, True, compression_bond
    )
    d_mm = 0.5 * trial.depth_mm + max(y for _x, y in arrangement.positions_mm)
    result.section["cover_mm"] = cover.cover_mm
    result.section["d_mm"] = d_mm
    result.add_note(cover.note)
    diameters = ld / float(arrangement.dia_mm) if arrangement.dia_mm else 0.0
    if compression_bond:
        result.add_note(
            "development length "
            + _num(ld, 0)
            + " mm ("
            + _num(diameters, 1)
            + " diameters) on the Cl 26.2.1.1 COMPRESSION bond stress: the Cl 39.3 axially loaded case "
            + "applies to this column, so no bar is in tension at the design strain plane"
        )
    else:
        result.add_note(
            "development length "
            + _num(ld, 0)
            + " mm ("
            + _num(diameters, 1)
            + " diameters) on the Cl 26.2.1.1 TENSION bond stress: the Cl 39.3 axially loaded case does "
            + "not apply here, either because a design moment acts or because the Cl 25.4 minimum "
            + "eccentricity is beyond 0.05 of the section, so bars on one face can be in tension at ULS; "
            + "which bar that is at the design strain plane is not resolved in this version, so the longer "
            + "value is written on every bar and any lap read from it is a tension lap"
        )

    result.add_check("axial_capacity", _IS456 + " 39.6 Puz", demand.pu_n, evaluated.puz_n, units="N")
    if evaluated.axial_only:
        result.add_check("pure_axial", _IS456 + " 39.3", demand.pu_n, evaluated.pu_axial_n, units="N")
        result.add_note(
            "frame moments are zero and the Cl 25.4 minimum eccentricity is within 0.05 of the section both "
            "ways, so the Cl 39.3 axially loaded check applies as well as the interaction"
        )
    result.add_check("biaxial_interaction", _IS456 + " 39.6", evaluated.ratio, 1.0, units="")
    result.add_check(
        "longitudinal_steel_min",
        _IS456 + " 26.5.3.1",
        limits.asc_min_mm2,
        arrangement.asc_mm2,
        units="mm2",
    )
    result.add_check(
        "longitudinal_steel_max",
        _IS456 + " 26.5.3.1",
        arrangement.asc_mm2,
        limits.asc_max_mm2,
        units="mm2",
    )
    result.add_check(
        "bar_periphery_spacing",
        _IS456 + " 26.5.3.1",
        max(arrangement.spacing_b_mm, arrangement.spacing_d_mm),
        limits.max_periphery_spacing_mm,
        units="mm",
    )

    pitch = max(TIE_SPACING_MODULE_MM, round_down_mm(ties.pitch_mm, TIE_SPACING_MODULE_MM))
    result.add_check("tie_pitch", _IS456 + " 26.5.3.2", pitch, ties.pitch_mm, units="mm")
    legs_b, legs_d = tie_legs(arrangement)

    result.add_bar(
        "long",
        arrangement.count,
        float(arrangement.dia_mm),
        ld,
        [0.0, trial.height_mm],
        layer=1,
        bars_per_b_face=arrangement.bars_b,
        bars_per_d_face=arrangement.bars_d,
        spacing_b_mm=arrangement.spacing_b_mm,
        spacing_d_mm=arrangement.spacing_d_mm,
        asc_mm2=arrangement.asc_mm2,
    )
    result.add_stirrup(
        [0.0, trial.height_mm],
        max(legs_b, legs_d),
        max(ties.dia_mm, arrangement.tie_dia_mm),
        pitch,
        kind="tie",
        legs_across_b=legs_b,
        legs_across_d=legs_d,
    )

    # The shared contract picks the highest ratio on the sheet as
    # `governing_check`, and a detailing rule the designer deliberately sets AT
    # its clause limit (the tie pitch) sits near 1.0 on every column. The
    # strength number is therefore stated here as well, so a reader never has to
    # infer it from the rows.
    result.add_note(
        "Cl 39.6 interaction utilization "
        + _num(evaluated.ratio, 3)
        + " at "
        + _pct(arrangement.asc_mm2 / (trial.b_mm * trial.depth_mm))
        + " longitudinal steel ("
        + str(arrangement.count)
        + "-"
        + str(arrangement.dia_mm)
        + ")"
    )
    result.add_note(
        "design moments Mux "
        + _knm(evaluated.mux_design_nmm)
        + " and Muy "
        + _knm(evaluated.muy_design_nmm)
        + " against capacities Mux1 "
        + _knm(evaluated.mux1_nmm)
        + " and Muy1 "
        + _knm(evaluated.muy1_nmm)
        + " at alpha_n "
        + _num(evaluated.alpha_n, 3)
    )
    if evaluated.ma_x_nmm > _TOL or evaluated.ma_y_nmm > _TOL:
        result.add_note(
            "Cl 39.7.1 additional moments Max "
            + _knm(evaluated.ma_x_nmm)
            + " (k "
            + _num(evaluated.k_x, 3)
            + ") and May "
            + _knm(evaluated.ma_y_nmm)
            + " (k "
            + _num(evaluated.k_y, 3)
            + "), k from Puz "
            + _kn(evaluated.puz_n)
            + " and the balanced loads "
            + _kn(evaluated.pb_x_n)
            + " and "
            + _kn(evaluated.pb_y_n)
        )
    if abs(demand.mux_nmm) <= _TOL and abs(demand.muy_nmm) <= _TOL:
        result.add_note(
            "the envelope carries no frame moment, so the Cl 25.4 minimum eccentricity governs both planes "
            "at once, which is the conservative reading of the clause"
        )
    if arrangement.asc_mm2 > limits.asc_lap_warn_mm2:
        result.add_warning(
            "longitudinal steel "
            + _pct(arrangement.asc_mm2 / (trial.b_mm * trial.depth_mm))
            + " is above 4 percent: laps will congest the section (Cl 26.5.3.1)"
        )

    _overlay_13920(result, trial, arrangement, evaluated, context)

    result.finalize()
    if chosen is None:
        result.status = STATUS_FAIL
        # Every way the search can give up already writes a failing row: the
        # interaction sum, the Puz check or the Cl 39.3 one. This is the guard
        # for a fourth way nobody has thought of, so that a fail is never a
        # sheet of passing rows.
        if not any(row.status == CHECK_FAIL for row in result.checks):
            result.add_check(
                "column_capacity",
                _IS456 + " 39.6",
                max(evaluated.ratio, 1.0 + _TOL),
                1.0,
                status=CHECK_FAIL,
            )
        result.governing_check = result.governing_check or "biaxial_interaction"
        result.add_warning(
            (stop or "the resize policy stopped")
            + " without a passing layout; the last attempt is reported in full"
        )
        result.finalize()
        result.status = STATUS_FAIL
    return result


def _overlay_13920(
    result: DesignResult,
    trial: _Trial,
    arrangement: BarArrangement,
    evaluated: _Eval,
    context: ColumnContext,
) -> None:
    """Hand the ductile detailing overlay to detailing.apply_13920, or say why not.

    The overlay owns the Cl 7.1 geometry referral, the confining zones and the
    joint flag (spec section 7). This module only decides whether it applies and
    calls it; a build without the sibling still returns a designed column, with
    a note and the `joint_check_manual` referral saying the overlay did not run.
    """
    mode = context.is13920
    if mode == "off":
        result.add_note("IS 13920 ductile detailing switched off by the options block")
        return
    if mode == "on":
        applies = True
    else:
        try:
            applies = is13920.is13920_applies(context.zone, context.frame)
        except ValueError as error:
            # An unreadable zone or frame must not lose the column: take the
            # conservative branch and say why.
            applies = True
            result.add_warning(
                "seismic context not understood ("
                + str(error)
                + "); the IS 13920 overlay is applied, which is the conservative reading"
            )
    if not applies:
        result.add_note(
            "IS 13920 does not apply to an "
            + str(context.frame).upper()
            + " frame in zone "
            + str(context.zone).upper()
            + " (Cl 1.1.1)"
        )
        return

    legs_b, legs_d = tie_legs(arrangement)
    cover = arrangement.cover_mm
    state = {
        "b_mm": trial.b_mm,
        "D_mm": trial.depth_mm,
        "clear_height_mm": trial.clear_height_mm,
        "fck_mpa": context.fck_mpa,
        "fy_mpa": context.fy_mpa,
        "dia_long_min_mm": float(arrangement.dia_mm),
        "dia_beam_bar_mm": context.beam_bar_dia_mm,
        "cover_mm": cover,
        "tie_dia_mm": arrangement.tie_dia_mm,
        "ag_mm2": trial.b_mm * trial.depth_mm,
        "ak_mm2": max(trial.b_mm - 2.0 * cover, 1.0) * max(trial.depth_mm - 2.0 * cover, 1.0),
        "legs": max(legs_b, legs_d),
        "stilt_storey": context.stilt,
        # What this column IS. A confining column's 230 x t section is set by
        # the wall it ties, so the overlay reads the flag and leaves the Cl 7.1
        # frame geometry clause alone for it (see COLUMN_ROLE_TIE); everything
        # else in the overlay runs unchanged.
        "role": trial.role,
        "confinement_column": trial.role == COLUMN_ROLE_TIE,
        # Sum Mc for the joint, taken as this lift above and below: a per-element
        # designer sees one column and no beams, so sum Mb comes from the
        # orchestrator or the Cl 7.2.1 check reports itself not applicable.
        "sum_mc_nmm": 2.0 * evaluated.mux1_nmm,
        "sum_mb_nmm": float(context.sum_mb_nmm),
    }  # type: Dict[str, Any]

    apply_13920 = None
    stirrup_zone = None
    try:
        from . import detailing  # late: the sibling may not be in this build

        apply_13920 = getattr(detailing, "apply_13920", None)
        stirrup_zone = getattr(detailing, "StirrupZone", None)
    except ImportError:
        apply_13920 = None
    if apply_13920 is None:
        result.add_note(
            "IS 13920 applies here; the column overlay (Cl 7.1 geometry, Cl 7.6 confining hoops, Cl 9 joint) "
            "is referred to design/rcc/detailing.apply_13920, which this build does not carry"
        )
        result.add_referral("joint_check_manual", _referral_payload(state))
        return

    if stirrup_zone is not None and result.stirrups:
        # The overlay rewrites the stirrup schedule from `tie_zones`, so the
        # Cl 26.5.3.2 ties have to travel with the state or they are dropped.
        tie = result.stirrups[0]
        state["tie_zones"] = [
            stirrup_zone(
                from_mm=float(tie["zone_mm"][0]),
                to_mm=float(tie["zone_mm"][1]),
                legs=int(tie["legs"]),
                dia_mm=int(tie["dia_mm"]),
                spacing_mm=float(tie["spacing_mm"]),
                kind="tie",
            )
        ]
    if trial.role != COLUMN_ROLE_TIE:
        # A confining column is not checked against Cl 7.1 at all (the overlay
        # says so in its own note), so this caveat about the beam bar the clause
        # is read with would be describing a check that did not run.
        result.add_note(
            "IS 13920 Cl 7.1 is checked against a largest beam bar of "
            + _num(context.beam_bar_dia_mm, 0)
            + " mm; pass beam_bar_dia_mm from the beam design to check the real one"
        )
    try:
        try:
            apply_13920(result, "column", context, state)
        except TypeError:
            # Older signature: the overlay reads its state off the result.
            result.extras["ductile_state"] = state
            apply_13920(result, "column", context)
    except Exception as error:  # disclose, never crash a batch on the overlay
        result.add_warning(
            "the IS 13920 column overlay did not run: " + type(error).__name__ + ": " + str(error)
        )
        result.add_referral("joint_check_manual", _referral_payload(state))
    finally:
        result.extras.pop("ductile_state", None)


# ---------------------------------------------------------------------------
# formatting (messages only, never arithmetic)
# ---------------------------------------------------------------------------


def _referral_payload(state: Mapping[str, Any]) -> Dict[str, Any]:
    """The ductile state as a JSON-safe referral detail: no zone objects."""
    return {key: state[key] for key in sorted(state) if key != "tie_zones"}


def _num(value: float, places: int) -> str:
    return ("%." + str(int(places)) + "f") % float(value)


def _pct(fraction: float) -> str:
    return _num(100.0 * float(fraction), 2) + " percent"


def _kn(value_n: float) -> str:
    return _num(float(value_n) / 1.0e3, 1) + " kN"


def _knm(value_nmm: float) -> str:
    return _num(float(value_nmm) / 1.0e6, 2) + " kNm"
