"""Footing design: isolated pads, the wall strip, N-support combined
rectangle, and the strap case that v1 refers out rather than pretends to design.

What this module is handed and what it refuses to invent
--------------------------------------------------------
Critic finding 19 draws the line: `placement/foundations.py` decides WHICH
footings exist, merges the pads that overlap and creates the strap beams. This
module designs what it is handed and never creates, merges or deletes a footing.
A pad that arrives with a strap partner is designed as a pad, with the strap
moment balance emitted as a `strap_required` referral so the orchestrator and
the report both carry it.

The walk, per pad (spec section 6)
----------------------------------
1. Allowable pressure. A stated SBC is used as given and traced as such. With no
   SBC the IS 6403 chain runs: bearing factors, shape, depth, water table, the
   local shear guard, and the net ultimate divided by the factor of safety 2.5.
   The chain is width dependent, so plan sizing re-enters it as the plan grows.
2. Plan, on SERVICE loads with a 10 percent self weight allowance, the aspect
   matched to the column, rounded up to `ResizePolicy.footing_plan_step_mm`.
   Eccentricity is kept inside the kern (e <= dim/6 both axes and the combined
   corner rule) by enlarging, and the pressure GRADIENT that survives is what
   the shear and flexure integrals then use: nothing is averaged away.
3. Depth, from the governing of punching at d/2 (Cl 31.6.3, ks and
   0.25 sqrt(fck)), one-way shear at d on both axes against Table 19 evaluated
   at the steel that direction actually gets, and flexure at the column face on
   1 m strips (Cl 34.2.3.2 with Annex G). Each requirement is solved for its own
   d over the same swept window and the deepest wins. `governing_check` is then
   pinned to whichever of those checks runs closest to its limit on the adopted
   section: a footing is sized by its thickness, so naming the shear or flexure
   check that the thickness answers to is more use to a reader than naming the
   highest ratio in the whole list, which is often a rounded-up bar count. A
   result that fails hands the name back to the check that failed. D = d + cover
   + 1.5 bar diameters, never below the 150 mm edge minimum.
4. Steel both ways, minimum 0.12 percent, spacing capped at 3d or 300, and for a
   rectangular footing the Cl 34.3.1.2 central band 2/(beta + 1) in the short
   direction with the remainder shared by the two outer strips. Bar diameters are
   capped by what the projection can develop, so a mat worked to its moment is
   detailed in bars that reach their stress rather than in bars that need a
   disclosure afterwards.
5. Dowels and the Cl 34.4 bearing check on the frustum area ratio, the dowel
   compression development length made to fit inside D or the depth bumped for
   it and the bump disclosed.

The walk, per wall strip (`design_strip_footing`)
-------------------------------------------------
A strip under a load bearing masonry wall is a different member from a pad and
is designed as one, per metre run of wall.

1. The demand is a LINE load, kN per metre, as `analysis/takedown.py` states it
   in `footing_loads["walls"]`; the allowable pressure comes from the same
   IS 6403 chain or the same stated SBC the pad uses.
2. Width, on the service line load with the same self weight allowance:
   `B = n_service (1 + allowance) / q_allow`, never narrower than the wall plus
   a projection each side, never narrower than the width the placer already
   laid, and rounded up to the policy plan step. The bearing chain is re-read as
   the width grows, exactly as the pad's is.
3. The projection past the wall face, `a = (B - t) / 2`, decides the member.
   A PLAIN concrete strip carries that projection in unreinforced concrete, so
   its thickness is set by the load spread: IS 456 Cl 34.1.3 wants
   `D >= a x 0.9 sqrt(100 q / fck + 1)`, and never less than the projection
   itself. While that thickness stays inside `plain_strip_max_thickness_mm` the
   strip IS a plain concrete spread footing and that verdict is the answer: a
   bearing check and a projection check, no steel, no invented reinforcement.
4. Past that thickness the strip is reinforced, and the RC case is IS 456 Cl 34
   on a 1 m strip of wall: one-way shear at d from the wall FACE (Cl 34.2.4.1),
   flexure at the section Cl 34.2.3.2(b) puts halfway between the wall
   centreline and the wall face for a footing under a MASONRY wall (not at the
   face, which is the concrete-wall rule), transverse steel from Annex G with
   the 0.12 percent floor, and nominal longitudinal distribution steel at the
   Cl 26.3.3 secondary spacing cap. There are no dowels: nothing is dowelled
   into a masonry wall.

Combined footings take the same pressure and depth machinery over a rectangle
carrying every support placement emitted.  The rectangle is centred on the
factored resultant, its service eccentricity is checked against the biaxial
kern, and the longitudinal beam-on-line diagram takes all N point loads.  That
diagram gives top steel between the outside columns and bottom steel under
them; punching is checked per column on a perimeter clipped to the footing,
each column gets a clipped transverse cantilever band, and a full-length
transverse minimum mat covers the regions between those bands.

One piece of code arithmetic lives here rather than in `codes/is456.py`: the
Cl 34.1.3 plain concrete load spread. That module ships no callable for the
clause and this change may not add one, so `plain_spread_factor` carries the
expression with the clause written out, and the check row cites it by number.

Units. N, mm, MPa inside, exactly as the IS equations are written. The SI model
(m, kN, kNm) is converted once on entry through `design/common.py` and the
geotechnical chain in `codes/is6403.py` is called in its own metre and kPa
units, converted at that one boundary. Every public field carries its unit.

Disclose, never hide. Nothing here raises: a footing that cannot be made to work
comes back fully populated with status fail, its governing check, every check
row it did evaluate and a warning saying what beat it.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterator, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ...codes import is456, is6403
from ...codes.trace import TraceEntry, trace_into
from ...data._loader import load_yaml
from .. import common as C

__all__ = [
    # constants
    "DEFAULT_LOAD_FACTOR",
    "SELF_WEIGHT_ALLOWANCE",
    "MIN_PROJECTION_MM",
    "FOOTING_BAR_DIAS_MM",
    "DOWEL_DIAS_MM",
    "MAX_DOWEL_BARS",
    "DOWEL_STRESS_FACTOR",
    "MIN_MESH_SPACING_MM",
    "DEPTH_DRIVEN_CHECKS",
    "MIN_STRIP_PROJECTION_MM",
    "PLAIN_STRIP_MAX_THICKNESS_MM",
    "STRIP_DEPTH_DRIVEN_CHECKS",
    "STRIP_LENGTH_FALLBACK_FACTOR",
    "STRIP_VERDICT_PLAIN",
    "STRIP_VERDICT_RC",
    # inputs
    "SoilProfile",
    "FootingLoads",
    "StripLoads",
    "ColumnStub",
    "PadGeometry",
    "StripGeometry",
    "CombinedGeometry",
    "FootingContext",
    # intermediate results, exposed so a test or a report can read one step
    "AllowablePressure",
    "PlanSize",
    "StripPlan",
    "MeshSteel",
    "BandSteel",
    "Dowels",
    "DepthDemand",
    "Critical",
    "allowable_pressure",
    "punching_critical",
    "anchorage_dia_cap_mm",
    "size_plan",
    "size_strip",
    "plain_spread_factor",
    "mesh_steel",
    "band_steel",
    "dowels",
    "bar_count",
    # designers
    "design_footing",
    "design_strip_footing",
    "design_combined_footing",
]

#: Partial safety factor on the service load where the caller states no factored
#: value. IS 456 Table 18, the 1.5 (DL + LL) combination.
DEFAULT_LOAD_FACTOR = 1.5

#: Allowance for the footing self weight and the backfill over it, as a fraction
#: of the service column load, used for PLAN SIZING only. The structural design
#: runs on the net upward pressure Pu/A: the weight of the footing is carried by
#: the soil directly under it and bends nothing.
SELF_WEIGHT_ALLOWANCE = 0.10

#: Smallest projection of the footing past the column face, mm. Not a code rule:
#: a pad that does not project cannot spread anything, and the placer never
#: produces one this small.
MIN_PROJECTION_MM = 150.0

#: Diameters offered to a footing mesh, ascending. 8 mm is deliberately absent:
#: a bottom mat cast against earth is walked on before the pour.
FOOTING_BAR_DIAS_MM = (10, 12, 16, 20, 25)

#: Diameters offered to dowels, ascending.
DOWEL_DIAS_MM = (12, 16, 20, 25)

#: Dowels preferred per column before the next diameter up is taken. Small bars
#: develop in less depth (Ld is proportional to the diameter), so a group of
#: twelve 16 mm dowels costs less footing thickness than six 20 mm ones.
MAX_DOWEL_BARS = 12

#: Design compressive stress in a dowel, as a multiple of fy: the same
#: 0.67 fy IS 456 Cl 39.3 credits to column longitudinal steel.
DOWEL_STRESS_FACTOR = 0.67

#: Floor on mesh bar spacing, mm, before the diameter is stepped up instead. The
#: code minimum (Cl 26.3.2, the larger of the bar and the aggregate plus 5) is
#: far smaller; this is a placing preference for a mat that gets walked on, and
#: it is what stops a footing being detailed at 60 mm centres of 10 mm bars.
MIN_MESH_SPACING_MM = 75.0

#: Checks a thicker footing fixes: only these drive the depth ladder. A bar
#: spacing or an anchorage shortfall wants a wider plan or a different bar, and
#: growing the depth for them would trade a disclosed note for wasted concrete.
DEPTH_DRIVEN_CHECKS = (
    "two-way shear",
    "one-way shear x",
    "one-way shear y",
    "flexure x",
    "flexure y",
    "dowel anchorage",
)

#: Smallest projection of a wall strip past its wall face, mm. Not a code rule:
#: a strip that does not project past the wall it carries spreads nothing. It is
#: deliberately smaller than `MIN_PROJECTION_MM`, which is a pad number: a 230 mm
#: wall on a 450 mm strip is ordinary practice and must not be grown into a pad.
MIN_STRIP_PROJECTION_MM = 75.0

#: Largest thickness a PLAIN concrete strip is given before the design switches
#: to a reinforced section. This is NOT a code number: IS 456 caps no thickness.
#: A plain strip carries its projection in unreinforced concrete, so its
#: thickness grows with the projection (see `plain_spread_factor`); past this it
#: is mass concrete doing a job that 250 to 300 mm of reinforced concrete does in
#: steel, so the design reinforces rather than pours it. Stated here, disclosed on
#: the result, and overridable per run through `FootingContext`.
PLAIN_STRIP_MAX_THICKNESS_MM = 600.0

#: Verdicts a strip can come back with. The plain verdict is an ANSWER, not an
#: absence: it means the bearing and projection checks are satisfied by an
#: unreinforced section and no reinforcement is required.
STRIP_VERDICT_PLAIN = "plain_concrete"
STRIP_VERDICT_RC = "reinforced_concrete"

#: Checks a thicker STRIP fixes. A bar spacing or an anchorage shortfall wants a
#: different bar, not more concrete, exactly as on the pad.
STRIP_DEPTH_DRIVEN_CHECKS = ("one-way shear", "flexure")

#: Length to read the IS 6403 shape factors at when the caller states no run
#: length, as a multiple of the strip width. A strip is not a square and reading
#: it as one would apply the square shape factors; ten widths is unambiguously in
#: the strip regime. Disclosed as a note whenever it is used.
STRIP_LENGTH_FALLBACK_FACTOR = 10.0

#: Bisection window and iteration count for the depth solvers. The residuals are
#: monotone in d, and the adopted depth is verified by a full check pass anyway.
_D_SEARCH_MIN_MM = 50.0
_D_SEARCH_MAX_MM = 3000.0
_D_SEARCH_SAMPLES = 59
_BISECT_ITERS = 30

_EPS = 1e-9

#: Anchorage value of a standard 90 degree bend, in bar diameters (IS 2502
#: bending allowance, carried in data/rebar.yaml).
_BEND_ANCHORAGE_DIA = float(C.BEND_ALLOWANCES["hook_90_deg_dia"])

_SOIL_DEFAULTS = dict(load_yaml("soil_defaults")["defaults"])


def _mm_to_m_opt(value_mm: Optional[float]) -> Optional[float]:
    """Millimetres to metres, keeping None as None and zero as nothing stated."""
    if value_mm is None or float(value_mm) <= 0.0:
        return None
    return C.mm_to_m(float(value_mm))


@contextmanager
def _quiet() -> Iterator[None]:
    """Swallow clause traces for the duration of a search.

    The depth solvers evaluate the same clauses dozens of times; a report that
    printed every bisection step would bury the design. `trace_into` isolates
    nested sinks, so the search runs into a throwaway list and only the final
    verification pass reaches the element's real trace.
    """
    with trace_into([]):
        yield


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoilProfile:
    """The ground under one footing, in the geotechnical SI the soil block uses.

    `sbc_kpa` set means the caller states a safe bearing capacity and the IS 6403
    chain is not walked; the trace and the notes both say so. `sbc_kpa` None
    means c, phi, gamma, the founding depth and the water table drive
    `codes/is6403.py`, which is the only place bearing capacity is computed.
    """

    sbc_kpa: Optional[float] = None
    c_kpa: float = float(_SOIL_DEFAULTS.get("c_kpa", 0.0))
    phi_deg: float = float(_SOIL_DEFAULTS.get("phi_deg", 30.0))
    gamma_knm3: float = float(_SOIL_DEFAULTS.get("gamma_knm3", 18.0))
    df_m: float = float(_SOIL_DEFAULTS.get("founding_depth_m", 1.5))
    gwt_depth_m: Optional[float] = None
    fos: float = is6403.FOS_DEFAULT

    @staticmethod
    def from_params(value: Any = None) -> "SoilProfile":
        """A profile from an options block, a placement `Soil`, or nothing.

        Accepts the request vocabulary (`founding_depth_m`, `water_table_m`) and
        this module's own (`df_m`, `gwt_depth_m`); missing values fall back to
        `data/soil_defaults.yaml`. A placement `Soil` always carries an SBC, so
        a caller handing one over gets the stated-SBC path, which is what the
        placer already sized against.
        """
        if isinstance(value, SoilProfile):
            return value
        if value is None:
            return SoilProfile()
        if isinstance(value, Mapping):
            get = lambda key, default=None: value.get(key, default)  # noqa: E731
        else:
            get = lambda key, default=None: getattr(value, key, default)  # noqa: E731
        sbc = get("sbc_kpa")
        depth = get("df_m")
        if depth is None:
            depth = get("founding_depth_m")
        water = get("gwt_depth_m")
        if water is None:
            water = get("water_table_m")
        base = SoilProfile()
        return SoilProfile(
            sbc_kpa=None if sbc is None else float(sbc),
            c_kpa=base.c_kpa if get("c_kpa") is None else float(get("c_kpa")),
            phi_deg=base.phi_deg if get("phi_deg") is None else float(get("phi_deg")),
            gamma_knm3=base.gamma_knm3 if get("gamma_knm3") is None else float(get("gamma_knm3")),
            df_m=base.df_m if depth is None else float(depth),
            gwt_depth_m=None if water is None else float(water),
            fos=base.fos if get("fos") is None else float(get("fos")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sbc_kpa": None if self.sbc_kpa is None else float(self.sbc_kpa),
            "c_kpa": float(self.c_kpa),
            "phi_deg": float(self.phi_deg),
            "gamma_knm3": float(self.gamma_knm3),
            "df_m": float(self.df_m),
            "gwt_depth_m": None if self.gwt_depth_m is None else float(self.gwt_depth_m),
            "fos": float(self.fos),
        }


@dataclass(frozen=True)
class FootingLoads:
    """Column actions at the top of one footing, SI as the model states them.

    `p_service_kn` is the unfactored axial load the takedown accumulated down the
    stack; `pu_kn` is the factored one and defaults to 1.5 times service.
    `mx_*_knm` is the moment that pushes the resultant along X (so ex = Mx / P),
    `my_*_knm` the same along Y; the factored pair defaults to the same factor,
    which leaves the eccentricity unchanged between the two states.
    """

    p_service_kn: float
    pu_kn: Optional[float] = None
    mx_service_knm: float = 0.0
    my_service_knm: float = 0.0
    mx_u_knm: Optional[float] = None
    my_u_knm: Optional[float] = None
    column_id: str = ""

    def factored_p_kn(self, load_factor: float = DEFAULT_LOAD_FACTOR) -> float:
        return float(self.pu_kn) if self.pu_kn is not None else float(load_factor) * float(self.p_service_kn)

    def factored_mx_knm(self, load_factor: float = DEFAULT_LOAD_FACTOR) -> float:
        return float(self.mx_u_knm) if self.mx_u_knm is not None else float(load_factor) * float(self.mx_service_knm)

    def factored_my_knm(self, load_factor: float = DEFAULT_LOAD_FACTOR) -> float:
        return float(self.my_u_knm) if self.my_u_knm is not None else float(load_factor) * float(self.my_service_knm)

    @staticmethod
    def from_envelope(envelope: Any, load_factor: float = DEFAULT_LOAD_FACTOR) -> "FootingLoads":
        """The service axial a `ForceEnvelope` of element_type "footing" carries.

        The takedown parks the service load (dead plus reduced imposed) on the
        single station's `n_max_kn`; moments arrive with the frame phase and are
        zero here, which is what the gravity path actually produces.
        """
        kind = getattr(envelope, "element_type", "")
        if kind != "footing":
            raise ValueError("from_envelope expects a footing envelope, got " + repr(kind))
        stations = getattr(envelope, "stations", ()) or ()
        p_service = max([float(getattr(s, "n_max_kn", 0.0)) for s in stations] or [0.0])
        return FootingLoads(p_service_kn=p_service, pu_kn=load_factor * p_service)


@dataclass(frozen=True)
class StripLoads:
    """Line load at the base of one bearing wall run, SI as the takedown states it.

    `n_service_kn_per_m` is the unfactored line load per metre run of wall that
    `analysis/takedown.py` accumulated down the stack and divided by the wall
    length; `nu_kn_per_m` is the factored one and defaults to 1.5 times service.
    A strip carries no moment in v1: the gravity takedown produces none. A party
    wall strip is FLUSHED inside the boundary by `placement/foundations.py`, which
    owns that geometry and hands the offset over as `StripGeometry.eccentric` /
    `e_m`; this designer checks bearing on the uniform pressure basis and warns
    that no eccentricity moment is taken, so neither module hides the offset.
    """

    n_service_kn_per_m: float
    nu_kn_per_m: Optional[float] = None
    wall_id: str = ""

    def factored_kn_per_m(self, load_factor: float = DEFAULT_LOAD_FACTOR) -> float:
        if self.nu_kn_per_m is not None:
            return float(self.nu_kn_per_m)
        return float(load_factor) * float(self.n_service_kn_per_m)

    @staticmethod
    def from_wall_ledger(row: Any, wall_id: str = "", load_factor: float = DEFAULT_LOAD_FACTOR) -> "StripLoads":
        """Loads from one row of `TakedownResult.footing_loads["walls"]`.

        That row is `{n_dl_kn_m, n_ll_raw_kn_m, n_ll_kn_m, floors_carried,
        reduction}` and the service line load a footing is sized on is the dead
        plus the REDUCED imposed part, which is the same sum `api._foundation_loads`
        hands `layout_foundations`. A plain number is accepted too, so a caller
        that already summed it does not have to build a dict back around it.
        """
        if isinstance(row, StripLoads):
            return row
        if isinstance(row, Mapping):
            service = float(row.get("n_dl_kn_m", 0.0) or 0.0) + float(row.get("n_ll_kn_m", 0.0) or 0.0)
        else:
            service = float(row or 0.0)
        return StripLoads(
            n_service_kn_per_m=service,
            nu_kn_per_m=float(load_factor) * service,
            wall_id=str(wall_id or ""),
        )


@dataclass(frozen=True)
class StripGeometry:
    """One continuous strip footing under a run of load bearing wall.

    `wall_t_m` is the wall the strip carries, `length_m` the run it covers and
    `placed_width_m` the width `placement/foundations.py` already laid, which is
    the starting point of the design and not a result. The placer states no
    footing THICKNESS for a strip: its `depth_m` is the FOUNDING depth, how far
    below ground the strip sits, so this designer computes the thickness itself
    and never reads that field as one.
    """

    element_id: str
    wall_t_m: float = 0.0
    length_m: float = 0.0
    placed_width_m: Optional[float] = None
    wall_ids: Tuple[str, ...] = ()
    orient: str = ""
    kind: str = "strip"
    eccentric: bool = False
    e_m: float = 0.0

    @staticmethod
    def from_mapping(data: Mapping) -> "StripGeometry":
        """A strip geometry from the plain dict a router builds off the model.

        This module's own names are read first and the placer's next. The wall
        thickness has no default: a strip designed against an invented wall is a
        wrong number wearing a design's clothes, so a mapping that carries none
        comes back as a disclosed failure naming the keys it wanted.
        """
        def pick(*names, **kwargs):
            for name in names:
                if data.get(name) is not None:
                    return float(data[name])
            return kwargs.get("default")

        thickness = pick("wall_t_m", "wall_thickness_m", default=None)
        if thickness is None:
            thickness = _mm_to_m_opt(pick("wall_t_mm", "wall_thickness_mm", default=None)) or 0.0
        length = pick("length_m", default=None)
        if length is None:
            length = _mm_to_m_opt(pick("length_mm", default=None)) or 0.0
        width = pick("placed_width_m", "width_m", default=None)
        if width is None:
            width = _mm_to_m_opt(pick("placed_width_mm", default=None))
        return StripGeometry(
            element_id=str(data.get("element_id", "") or ""),
            wall_t_m=float(thickness),
            length_m=float(length),
            placed_width_m=width,
            wall_ids=tuple(str(one) for one in (data.get("wall_ids") or ())),
            orient=str(data.get("orient", "") or ""),
            kind=str(data.get("kind", "strip") or "strip"),
            eccentric=bool(data.get("eccentric", False)),
            e_m=float(data.get("e_m", 0.0) or 0.0),
        )

    @staticmethod
    def from_strip_footing(strip: Any) -> "StripGeometry":
        """Build from a `placement.foundations.StripFooting`.

        Duck typed on purpose, exactly as `PadGeometry.from_pad_footing` is: the
        design layer reads the placer's shape but never imports it, so neither
        package depends on the other.
        """
        return StripGeometry(
            element_id=str(getattr(strip, "id", "")),
            wall_t_m=float(getattr(strip, "wall_t_m", 0.0) or 0.0),
            length_m=float(strip.length_m() if hasattr(strip, "length_m") else 0.0),
            placed_width_m=float(getattr(strip, "width_m", 0.0) or 0.0) or None,
            wall_ids=tuple(str(one) for one in (getattr(strip, "wall_ids", None) or ())),
            orient=str(getattr(strip, "orient", "") or ""),
            eccentric=bool(getattr(strip, "eccentric", False)),
            e_m=float(getattr(strip, "e_m", 0.0) or 0.0),
        )


@dataclass(frozen=True)
class ColumnStub:
    """The column the footing carries: its section and where it stands in plan."""

    column_id: str = ""
    bx_mm: float = 300.0
    dy_mm: float = 300.0
    x_m: float = 0.0
    y_m: float = 0.0

    @property
    def area_mm2(self) -> float:
        return float(self.bx_mm) * float(self.dy_mm)

    @property
    def beta_c(self) -> float:
        """Short side over long side of the loaded area, IS 456 Cl 31.6.3.1."""
        short = min(float(self.bx_mm), float(self.dy_mm))
        long_side = max(float(self.bx_mm), float(self.dy_mm))
        return short / long_side if long_side > 0.0 else 1.0


@dataclass(frozen=True)
class PadGeometry:
    """One isolated pad as placement handed it over.

    `col_offset_*_m` is the column centre measured from the footing centre: zero
    for the ordinary concentric pad, non-zero for the boundary pad a strap beam
    ties back. The placed plan size is the starting point, not a result: design
    grows it when a check asks and discloses every step. A placed foundation's
    ``depth_m`` is its *founding level*, never an RC thickness. Only the
    explicitly named thickness fields below may seed the RC depth ladder.
    """

    element_id: str
    column: ColumnStub = ColumnStub()
    col_offset_x_m: float = 0.0
    col_offset_y_m: float = 0.0
    placed_bx_m: Optional[float] = None
    placed_ly_m: Optional[float] = None
    # Canonical explicit physical-thickness input for a direct RCC caller.
    placed_thickness_m: Optional[float] = None
    # Backwards-compatible explicit-thickness spelling. Do not map a placed
    # Footing.depth_m into this field: that value is the founding level.
    placed_depth_m: Optional[float] = None
    kind: str = "isolated"
    strap_partner_id: str = ""
    strap_span_m: float = 0.0

    @property
    def specified_thickness_m(self) -> Optional[float]:
        """The optional physical pad thickness stated by a direct design input.

        ``placed_depth_m`` remains readable for callers of the earlier RCC-only
        API. It has never been a safe alias for the placement model's generic
        ``depth_m`` field, which records the founding level.
        """
        return self.placed_thickness_m if self.placed_thickness_m is not None else self.placed_depth_m

    @staticmethod
    def from_mapping(data: Mapping) -> "PadGeometry":
        """A pad geometry from the plain dict an orchestrator builds off the model.

        This module's own names are read first and the model-side names next: a
        model `Footing` crosses its PLAN sizes as `b_mm` / `D_mm`. A generic
        model ``depth_m``/``depth_mm`` is intentionally not accepted as an RC
        thickness because placement uses it for founding level. Direct callers
        must use ``placed_thickness_*`` (or the legacy explicit
        ``placed_depth_*`` spelling).

        The column section has no default. A footing designed against an invented
        column is a wrong number wearing a design's clothes, so a mapping that
        carries none comes back as a disclosed failure naming the keys it wanted.
        """
        def pick(*names, **kwargs):
            for name in names:
                if data.get(name) is not None:
                    return float(data[name])
            return kwargs.get("default")

        column = ColumnStub(
            column_id=str(data.get("column_id", "") or ""),
            bx_mm=pick("col_bx_mm", "column_bx_mm", default=0.0),
            dy_mm=pick("col_dy_mm", "column_dy_mm", default=0.0),
        )
        return PadGeometry(
            element_id=str(data.get("element_id", "") or ""),
            column=column,
            col_offset_x_m=pick("col_offset_x_m", default=0.0),
            col_offset_y_m=pick("col_offset_y_m", default=0.0),
            placed_bx_m=pick("placed_bx_m", "bx_m") or _mm_to_m_opt(pick("placed_bx_mm", "b_mm")),
            placed_ly_m=pick("placed_ly_m", "ly_m") or _mm_to_m_opt(pick("placed_ly_mm", "D_mm")),
            placed_thickness_m=pick("placed_thickness_m") or _mm_to_m_opt(pick("placed_thickness_mm")),
            placed_depth_m=pick("placed_depth_m") or _mm_to_m_opt(pick("placed_depth_mm")),
            kind=str(data.get("kind", "isolated") or "isolated"),
            strap_partner_id=str(data.get("strap_partner_id", "") or ""),
            strap_span_m=pick("strap_span_m", default=0.0),
        )

    @staticmethod
    def from_pad_footing(pad: Any, column: ColumnStub, strap: Any = None) -> "PadGeometry":
        """Build from a `placement.foundations.PadFooting` and its column.

        Duck typed on purpose: the design layer reads the placer's shape but
        never imports it, so neither package depends on the other.
        """
        centre_x = float(getattr(pad, "x_m", 0.0))
        centre_y = float(getattr(pad, "y_m", 0.0))
        offset_x = float(getattr(column, "x_m", centre_x)) - centre_x
        offset_y = float(getattr(column, "y_m", centre_y)) - centre_y
        partner = "" if strap is None else str(getattr(strap, "to_id", "") or "")
        span = 0.0
        if strap is not None:
            a = getattr(strap, "a", (0.0, 0.0))
            b = getattr(strap, "b", (0.0, 0.0))
            span = math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
        return PadGeometry(
            element_id=str(getattr(pad, "id", "")),
            column=column,
            col_offset_x_m=offset_x,
            col_offset_y_m=offset_y,
            placed_bx_m=float(getattr(pad, "w_m", 0.0)) or None,
            placed_ly_m=float(getattr(pad, "h_m", 0.0)) or None,
            kind="strap" if partner else str(getattr(pad, "kind", "isolated") or "isolated"),
            strap_partner_id=partner,
            strap_span_m=span,
        )


@dataclass(frozen=True)
class CombinedGeometry:
    """One combined rectangle carrying two or more columns.

    Column positions are plan metres in the model's own frame; the designer
    works along the axis that separates them and calls it longitudinal.
    """

    element_id: str
    columns: Tuple[ColumnStub, ...] = ()
    placed_bx_m: Optional[float] = None
    placed_ly_m: Optional[float] = None
    # See PadGeometry: this is a physical section input, not founding level.
    placed_thickness_m: Optional[float] = None
    # Legacy explicit physical-thickness spelling retained for RCC callers.
    placed_depth_m: Optional[float] = None
    kind: str = "combined"

    @property
    def specified_thickness_m(self) -> Optional[float]:
        return self.placed_thickness_m if self.placed_thickness_m is not None else self.placed_depth_m

    @staticmethod
    def from_combined_footing(combined: Any, columns: Sequence[ColumnStub]) -> "CombinedGeometry":
        return CombinedGeometry(
            element_id=str(getattr(combined, "id", "")),
            columns=tuple(columns),
            placed_bx_m=float(getattr(combined, "w_m", 0.0)) or None,
            placed_ly_m=float(getattr(combined, "h_m", 0.0)) or None,
        )


@dataclass(frozen=True)
class FootingContext:
    """Materials, exposure and the resize ladder, for one design run."""

    fck_mpa: float = 25.0
    fy_mpa: float = 500.0
    exposure: str = "moderate"
    fire_rating_h: float = 0.0
    agg_mm: float = C.DEFAULT_AGG_MM
    load_factor: float = DEFAULT_LOAD_FACTOR
    self_weight_allowance: float = SELF_WEIGHT_ALLOWANCE
    bar_dias_mm: Tuple[int, ...] = FOOTING_BAR_DIAS_MM
    policy: C.ResizePolicy = C.ResizePolicy()
    plain_strip_max_thickness_mm: float = PLAIN_STRIP_MAX_THICKNESS_MM

    @staticmethod
    def coerce(value: Any = None) -> "FootingContext":
        """A context from the options block, another context, or nothing.

        The orchestrator's options dict (`{materials: {fck, fy}, exposure,
        fire_rating_h, aggregate_mm, resize_policy}`) is accepted as-is so the
        designer can be called straight from `run_rcc_design` without a shim, and
        so is the sibling `detailing.DesignContext` the beam, column and slab
        designers share: anything carrying `fck_mpa` and `fy_mpa` is read for the
        fields a footing needs and defaulted for the rest.
        """
        if isinstance(value, FootingContext):
            return value
        if value is None:
            return FootingContext()
        if not isinstance(value, Mapping):
            if hasattr(value, "fck_mpa") and hasattr(value, "fy_mpa"):
                base = FootingContext()
                policy = getattr(value, "policy", None)
                return FootingContext(
                    fck_mpa=float(value.fck_mpa),
                    fy_mpa=float(value.fy_mpa),
                    exposure=str(getattr(value, "exposure", base.exposure)),
                    fire_rating_h=float(getattr(value, "fire_rating_h", base.fire_rating_h) or 0.0),
                    agg_mm=float(getattr(value, "agg_mm", base.agg_mm)),
                    policy=policy if isinstance(policy, C.ResizePolicy) else base.policy,
                    plain_strip_max_thickness_mm=float(
                        getattr(value, "plain_strip_max_thickness_mm", base.plain_strip_max_thickness_mm)
                        or base.plain_strip_max_thickness_mm
                    ),
                )
            raise ValueError("ctx must be a FootingContext, a mapping or None, got " + repr(type(value)))
        base = FootingContext()
        materials = value.get("materials") or {}
        fck = value.get("fck_mpa", materials.get("fck", materials.get("fck_mpa", base.fck_mpa)))
        fy = value.get("fy_mpa", materials.get("fy", materials.get("fy_mpa", base.fy_mpa)))
        policy = value.get("resize_policy") or value.get("policy")
        dias = value.get("bar_dias_mm")
        return FootingContext(
            fck_mpa=float(fck),
            fy_mpa=float(fy),
            exposure=str(value.get("exposure", base.exposure)),
            fire_rating_h=float(value.get("fire_rating_h", base.fire_rating_h) or 0.0),
            agg_mm=float(value.get("aggregate_mm", value.get("agg_mm", base.agg_mm))),
            load_factor=float(value.get("load_factor", base.load_factor)),
            self_weight_allowance=float(value.get("self_weight_allowance", base.self_weight_allowance)),
            bar_dias_mm=tuple(int(d) for d in dias) if dias else base.bar_dias_mm,
            policy=C.ResizePolicy.from_dict(policy) if isinstance(policy, Mapping) else (policy or base.policy),
            plain_strip_max_thickness_mm=float(
                value.get("plain_strip_max_thickness_mm") or base.plain_strip_max_thickness_mm
            ),
        )

    @property
    def concrete(self) -> C.Concrete:
        return C.Concrete(fck_mpa=float(self.fck_mpa))

    @property
    def steel(self) -> C.RebarSteel:
        return C.RebarSteel(fy_mpa=float(self.fy_mpa))


# ---------------------------------------------------------------------------
# bearing pressure and the pressure field
# ---------------------------------------------------------------------------


class AllowablePressure(NamedTuple):
    """The safe bearing pressure a plan size may be checked against."""

    q_allow_kpa: float
    source: str
    notes: Tuple[str, ...]


class PlanSize(NamedTuple):
    """A settled plan: dimensions, the pressures on it and what drove it."""

    bx_mm: float
    ly_mm: float
    q_allow_kpa: float
    q_max_kpa: float
    q_min_kpa: float
    ex_mm: float
    ey_mm: float
    kern_ok: bool
    driver: str
    iterations: int
    notes: Tuple[str, ...]
    contact_ratio: float = 1.0
    elastic_q_min_kpa: float = 0.0

    @property
    def area_mm2(self) -> float:
        return float(self.bx_mm) * float(self.ly_mm)


def allowable_pressure(soil: SoilProfile, bx_mm: float, ly_mm: float) -> AllowablePressure:
    """Net safe bearing pressure for a plan size, kPa.

    A stated SBC wins and is traced as the user's number. Otherwise the IS 6403
    chain runs at this plan size, in the metres and kPa that module speaks; the
    conversion from the design layer's millimetres happens here and nowhere else.
    """
    if soil.sbc_kpa is not None:
        return AllowablePressure(
            q_allow_kpa=float(soil.sbc_kpa),
            source="user SBC",
            notes=("user SBC " + _n(soil.sbc_kpa, 1) + " kPa taken as given; the IS 6403 chain was not walked",),
        )
    width_m = C.mm_to_m(min(float(bx_mm), float(ly_mm)))
    length_m = C.mm_to_m(max(float(bx_mm), float(ly_mm)))
    chain = is6403.net_safe_bearing(
        c_kpa=float(soil.c_kpa),
        phi_deg=float(soil.phi_deg),
        gamma_knm3=float(soil.gamma_knm3),
        b_m=width_m,
        l_m=length_m,
        df_m=float(soil.df_m),
        gwt_depth_m=soil.gwt_depth_m,
        fos=float(soil.fos),
    )
    return AllowablePressure(
        q_allow_kpa=float(chain.q_safe_net_kpa),
        source="IS 6403 net safe bearing at FOS " + _n(chain.fos, 1),
        notes=tuple(chain.notes),
    )


def _pressure_gradient(p_n: float, dim_mm: float, e_mm: float) -> float:
    """The linear coefficient c in q(x) = q0 (1 + c x), x from the plan centre.

    From the section modulus of the contact area: c = 12 e / dim^2, so the edge
    pressure is q0 (1 +- 6 e / dim), which is the kern statement itself.
    """
    if dim_mm <= 0.0:
        return 0.0
    return 12.0 * float(e_mm) / (float(dim_mm) * float(dim_mm))


class _ContactPressure(NamedTuple):
    """A no-tension linear soil-pressure plane over one rectangle.

    The plane is expressed on normalized coordinates X and Y in [-1, 1]:
    `q = max(0, a + bx X + by Y)`.  `elastic_q_min_mpa` is the unclipped
    corner pressure, which is the biaxial kern test.  The other pressure values
    describe the physical compression-only contact patch.
    """

    a_mpa: float
    bx_mpa: float
    by_mpa: float
    q_max_mpa: float
    q_min_mpa: float
    elastic_q_min_mpa: float
    contact_ratio: float


def _clip_pressure_polygon(
    polygon: Sequence[Tuple[float, float]], a_mpa: float, bx_mpa: float, by_mpa: float
) -> List[Tuple[float, float]]:
    """Clip a convex polygon to the compression side of one pressure plane."""
    out = list(polygon)
    if not out:
        return []
    clipped = []  # type: List[Tuple[float, float]]
    previous = out[-1]
    q_previous = a_mpa + bx_mpa * previous[0] + by_mpa * previous[1]
    for current in out:
        q_current = a_mpa + bx_mpa * current[0] + by_mpa * current[1]
        previous_in = q_previous >= -_EPS
        current_in = q_current >= -_EPS
        if previous_in != current_in:
            denominator = q_previous - q_current
            fraction = q_previous / denominator if abs(denominator) > _EPS else 0.0
            clipped.append(
                (
                    previous[0] + fraction * (current[0] - previous[0]),
                    previous[1] + fraction * (current[1] - previous[1]),
                )
            )
        if current_in:
            clipped.append(current)
        previous = current
        q_previous = q_current
    return clipped


def _polygon_moments(polygon: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float, float, float]:
    """Area and first/second monomial integrals of a counter-clockwise polygon."""
    if len(polygon) < 3:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    area2 = sx6 = sy6 = sxx12 = syy12 = sxy24 = 0.0
    previous = polygon[-1]
    for current in polygon:
        x0, y0 = previous
        x1, y1 = current
        cross = x0 * y1 - x1 * y0
        area2 += cross
        sx6 += (x0 + x1) * cross
        sy6 += (y0 + y1) * cross
        sxx12 += (x0 * x0 + x0 * x1 + x1 * x1) * cross
        syy12 += (y0 * y0 + y0 * y1 + y1 * y1) * cross
        sxy24 += (2.0 * x0 * y0 + x0 * y1 + x1 * y0 + 2.0 * x1 * y1) * cross
        previous = current
    sign = 1.0 if area2 >= 0.0 else -1.0
    return (
        sign * area2 / 2.0,
        sign * sx6 / 6.0,
        sign * sy6 / 6.0,
        sign * sxx12 / 12.0,
        sign * sxy24 / 24.0,
        sign * syy12 / 12.0,
    )


def _solve_three(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> Tuple[float, float, float]:
    """A pivoted 3 by 3 solve, kept local so the designer needs no numeric stack."""
    rows = [list(matrix[index]) + [float(vector[index])] for index in range(3)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda index: abs(rows[index][column]))
        if abs(rows[pivot][column]) <= 1e-14:
            raise ValueError("partial-contact pressure solve has a singular contact patch")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        scale = rows[column][column]
        rows[column] = [value / scale for value in rows[column]]
        for index in range(3):
            if index == column:
                continue
            factor = rows[index][column]
            rows[index] = [
                rows[index][slot] - factor * rows[column][slot]
                for slot in range(4)
            ]
    return (rows[0][3], rows[1][3], rows[2][3])


@lru_cache(maxsize=512)
def _contact_pressure(
    bx_mm: float, ly_mm: float, p_n: float, ex_mm: float, ey_mm: float
) -> _ContactPressure:
    """Compression-only pressure matching P, P ex and P ey on a rectangle.

    IS 456 Cl 34.1 requires the footing to sustain the applied moments and the
    induced reaction without exceeding the soil capacity.  Soil is not credited
    in tension.  Inside the biaxial kern the ordinary elastic plane is exact;
    outside it, Newton equilibrium is solved over the clipped contact polygon.
    """
    bx = float(bx_mm)
    ly = float(ly_mm)
    load = max(float(p_n), 0.0)
    if bx <= 0.0 or ly <= 0.0 or load <= 0.0:
        return _ContactPressure(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    q0 = load / (bx * ly)
    bx_plane = q0 * 6.0 * float(ex_mm) / bx
    by_plane = q0 * 6.0 * float(ey_mm) / ly
    elastic_min = q0 - abs(bx_plane) - abs(by_plane)
    elastic_max = q0 + abs(bx_plane) + abs(by_plane)
    if elastic_min >= -_EPS:
        return _ContactPressure(
            q0,
            bx_plane,
            by_plane,
            elastic_max,
            max(elastic_min, 0.0),
            elastic_min,
            1.0,
        )

    target_force = load / (0.25 * bx * ly)
    target_x = target_force * 2.0 * float(ex_mm) / bx
    target_y = target_force * 2.0 * float(ey_mm) / ly
    a_mpa = q0
    square = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    for _iteration in range(30):
        contact = _clip_pressure_polygon(square, a_mpa, bx_plane, by_plane)
        area, sx, sy, sxx, sxy, syy = _polygon_moments(contact)
        force = a_mpa * area + bx_plane * sx + by_plane * sy
        moment_x = a_mpa * sx + bx_plane * sxx + by_plane * sxy
        moment_y = a_mpa * sy + bx_plane * sxy + by_plane * syy
        residual = (
            target_force - force,
            target_x - moment_x,
            target_y - moment_y,
        )
        if max(abs(value) for value in residual) <= 1e-11 * max(abs(target_force), 1.0):
            break
        da, dbx, dby = _solve_three(
            ((area, sx, sy), (sx, sxx, sxy), (sy, sxy, syy)),
            residual,
        )
        a_mpa += da
        bx_plane += dbx
        by_plane += dby
    else:
        raise ValueError("partial-contact pressure solve did not converge")

    contact = _clip_pressure_polygon(square, a_mpa, bx_plane, by_plane)
    area = _polygon_moments(contact)[0]
    corners = [a_mpa + bx_plane * x + by_plane * y for x, y in square]
    return _ContactPressure(
        a_mpa,
        bx_plane,
        by_plane,
        max(max(corners), 0.0),
        0.0,
        elastic_min,
        min(max(area / 4.0, 0.0), 1.0),
    )


def _pressure_integrals(
    pressure: _ContactPressure,
    bx_mm: float,
    ly_mm: float,
    x_lo_mm: float,
    x_hi_mm: float,
    y_lo_mm: float,
    y_hi_mm: float,
) -> Tuple[float, float, float]:
    """(force, moment about plan x=0, moment about plan y=0) on a rectangle."""
    bx = float(bx_mm)
    ly = float(ly_mm)
    if bx <= 0.0 or ly <= 0.0 or x_hi_mm <= x_lo_mm or y_hi_mm <= y_lo_mm:
        return (0.0, 0.0, 0.0)
    x_lo = max(-1.0, min(1.0, 2.0 * float(x_lo_mm) / bx))
    x_hi = max(-1.0, min(1.0, 2.0 * float(x_hi_mm) / bx))
    y_lo = max(-1.0, min(1.0, 2.0 * float(y_lo_mm) / ly))
    y_hi = max(-1.0, min(1.0, 2.0 * float(y_hi_mm) / ly))
    polygon = [(x_lo, y_lo), (x_hi, y_lo), (x_hi, y_hi), (x_lo, y_hi)]
    contact = _clip_pressure_polygon(polygon, pressure.a_mpa, pressure.bx_mpa, pressure.by_mpa)
    area, sx, sy, sxx, sxy, syy = _polygon_moments(contact)
    force_norm = pressure.a_mpa * area + pressure.bx_mpa * sx + pressure.by_mpa * sy
    moment_x_norm = pressure.a_mpa * sx + pressure.bx_mpa * sxx + pressure.by_mpa * sxy
    moment_y_norm = pressure.a_mpa * sy + pressure.bx_mpa * sxy + pressure.by_mpa * syy
    scale = 0.25 * bx * ly
    return (
        scale * force_norm,
        scale * 0.5 * bx * moment_x_norm,
        scale * 0.5 * ly * moment_y_norm,
    )


def _strip_resultant(
    q0_mpa: float,
    grad_per_mm: float,
    width_mm: float,
    x_face_mm: float,
    length_mm: float,
    sign: float,
) -> Tuple[float, float]:
    """Force and moment on one cantilever strip of the pressure field.

    The strip starts at `x_face_mm` (measured from the plan centre) and runs
    `length_mm` towards the edge in direction `sign` (+1 or -1), across the full
    `width_mm` of the other axis, over which the other axis' linear term
    integrates to zero. Returns (force N, moment about the strip start N.mm).

    With q(u) = q0 (1 + c x_face + sign c u) along the arm u:
        F = w q0 [(1 + c x_face) a + sign c a^2 / 2]
        M = w q0 [(1 + c x_face) a^2 / 2 + sign c a^3 / 3]
    """
    a = max(float(length_mm), 0.0)
    if a <= 0.0:
        return (0.0, 0.0)
    base = 1.0 + float(grad_per_mm) * float(x_face_mm)
    slope = float(sign) * float(grad_per_mm)
    scale = float(width_mm) * float(q0_mpa)
    force = scale * (base * a + slope * a * a / 2.0)
    moment = scale * (base * a * a / 2.0 + slope * a * a * a / 3.0)
    return (force, moment)


class Critical(NamedTuple):
    """The punching critical section at d/2, clipped to the footing outline."""

    perimeter_mm: float
    area_mm2: float
    x_lo_mm: float
    x_hi_mm: float
    y_lo_mm: float
    y_hi_mm: float
    sides: int


def punching_critical(
    col_bx_mm: float,
    col_dy_mm: float,
    off_x_mm: float,
    off_y_mm: float,
    bx_mm: float,
    ly_mm: float,
    d_mm: float,
) -> Critical:
    """Critical perimeter at d/2 and the plan area inside it, clipped to the pad.

    Sides of the critical rectangle that fall outside the footing carry no shear
    and are dropped, which is how an edge or corner column is checked; a
    concentric column keeps all four sides and the full (c + d) x (c + d) area.
    """
    half = 0.5 * float(d_mm)
    x_lo = float(off_x_mm) - 0.5 * float(col_bx_mm) - half
    x_hi = float(off_x_mm) + 0.5 * float(col_bx_mm) + half
    y_lo = float(off_y_mm) - 0.5 * float(col_dy_mm) - half
    y_hi = float(off_y_mm) + 0.5 * float(col_dy_mm) + half
    edge_x = 0.5 * float(bx_mm)
    edge_y = 0.5 * float(ly_mm)
    cx_lo = max(x_lo, -edge_x)
    cx_hi = min(x_hi, edge_x)
    cy_lo = max(y_lo, -edge_y)
    cy_hi = min(y_hi, edge_y)
    span_x = max(cx_hi - cx_lo, 0.0)
    span_y = max(cy_hi - cy_lo, 0.0)
    perimeter = 0.0
    sides = 0
    if x_lo >= -edge_x - _EPS:
        perimeter += span_y
        sides += 1
    if x_hi <= edge_x + _EPS:
        perimeter += span_y
        sides += 1
    if y_lo >= -edge_y - _EPS:
        perimeter += span_x
        sides += 1
    if y_hi <= edge_y + _EPS:
        perimeter += span_x
        sides += 1
    return Critical(
        perimeter_mm=perimeter,
        area_mm2=span_x * span_y,
        x_lo_mm=cx_lo,
        x_hi_mm=cx_hi,
        y_lo_mm=cy_lo,
        y_hi_mm=cy_hi,
        sides=sides,
    )


def _n(value: float, places: int) -> str:
    """Message formatting only, never arithmetic."""
    return ("%." + str(int(places)) + "f") % float(value)


def _mm_text(value_mm: float) -> str:
    number = float(value_mm)
    return (str(int(round(number))) if abs(number - round(number)) < 1e-6 else _n(number, 1)) + " mm"


def _bisect_min_d(residual: Any, lo_mm: float = _D_SEARCH_MIN_MM, hi_mm: float = _D_SEARCH_MAX_MM) -> Optional[float]:
    """The shallowest d above which `residual(d) <= 0` everywhere, or None.

    The residuals are demand minus capacity and mostly fall with depth, but not
    smoothly: when a punching perimeter reaches the edge of the footing that
    side stops resisting and the stress jumps UP. A plain bisection would settle
    into the first crossing it happened to bracket and report a depth that the
    next millimetre of clipping undoes. So the window is swept coarsely, the
    LAST failing sample is taken, and only that one interval is refined: the
    answer is then a depth the criterion is satisfied at and stays satisfied
    above, which is the only useful reading of a design requirement.
    """
    lo = float(lo_mm)
    hi = float(hi_mm)
    if hi <= lo:
        return lo if residual(lo) <= 0.0 else None
    if residual(lo) <= 0.0:
        return lo
    if residual(hi) > 0.0:
        return None
    step = (hi - lo) / _D_SEARCH_SAMPLES
    last_fail = lo
    for index in range(1, _D_SEARCH_SAMPLES):
        probe = lo + index * step
        if residual(probe) > 0.0:
            last_fail = probe
    low, high = last_fail, min(last_fail + step, hi)
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (low + high)
        if residual(mid) <= 0.0:
            high = mid
        else:
            low = mid
    return high


@dataclass(frozen=True)
class _Field:
    """The factored soil pressure under one footing and the column that made it.

    Coordinates are millimetres from the plan centre and the plan edges sit at
    +- dim / 2.  Inside the biaxial kern the pressure is the ordinary linear
    plane.  Outside it, soil tension is discarded and the compression plane is
    solved back to the same P, P ex and P ey resultants.  The column may stand
    off centre (a strap pad); that offset and the pressure eccentricity are
    independent.
    """

    bx_mm: float
    ly_mm: float
    col_bx_mm: float
    col_dy_mm: float
    off_x_mm: float
    off_y_mm: float
    pu_n: float
    ex_mm: float
    ey_mm: float

    @property
    def area_mm2(self) -> float:
        return float(self.bx_mm) * float(self.ly_mm)

    @property
    def q0_mpa(self) -> float:
        area = self.area_mm2
        return float(self.pu_n) / area if area > 0.0 else 0.0

    @property
    def pressure(self) -> _ContactPressure:
        return _contact_pressure(self.bx_mm, self.ly_mm, self.pu_n, self.ex_mm, self.ey_mm)

    @property
    def grad_x(self) -> float:
        return _pressure_gradient(self.pu_n, self.bx_mm, self.ex_mm)

    @property
    def grad_y(self) -> float:
        return _pressure_gradient(self.pu_n, self.ly_mm, self.ey_mm)

    def axis(self, axis: str) -> Tuple[float, float, float, float, float]:
        """(dim, other dim, column dim, column offset, gradient) for one axis."""
        if axis == "x":
            return (float(self.bx_mm), float(self.ly_mm), float(self.col_bx_mm), float(self.off_x_mm), self.grad_x)
        return (float(self.ly_mm), float(self.bx_mm), float(self.col_dy_mm), float(self.off_y_mm), self.grad_y)

    def arm_mm(self, axis: str, side: float) -> float:
        """Cantilever projection from the column face to the edge on one side."""
        dim, _other, col, off, _grad = self.axis(axis)
        return max(0.5 * dim - side * off - 0.5 * col, 0.0)

    def face_mm(self, axis: str, side: float) -> float:
        """Position of that column face, measured from the plan centre."""
        _dim, _other, col, off, _grad = self.axis(axis)
        return off + side * 0.5 * col

    def cantilever(self, axis: str, side: float, back_off_mm: float = 0.0) -> Tuple[float, float]:
        """(force N, moment N.mm) on the strip from a section to the edge.

        `back_off_mm` moves the section away from the column face towards the
        edge: zero gives the bending section at the face (Cl 34.2.3.2), d gives
        the one-way shear section (Cl 34.2.4.1). The moment is taken about that
        same section.
        """
        dim, other, _col, _off, _grad = self.axis(axis)
        arm = self.arm_mm(axis, side)
        start = self.face_mm(axis, side) + side * float(back_off_mm)
        edge = side * 0.5 * dim
        if side > 0.0:
            lo, hi = start, edge
        else:
            lo, hi = edge, start
        if axis == "x":
            force, moment_axis, _other_moment = _pressure_integrals(
                self.pressure,
                self.bx_mm,
                self.ly_mm,
                lo,
                hi,
                -0.5 * other,
                0.5 * other,
            )
        else:
            force, _other_moment, moment_axis = _pressure_integrals(
                self.pressure,
                self.bx_mm,
                self.ly_mm,
                -0.5 * other,
                0.5 * other,
                lo,
                hi,
            )
        moment = float(side) * (moment_axis - start * force)
        return (max(force, 0.0), max(moment, 0.0))

    def load_in(self, x_lo: float, x_hi: float, y_lo: float, y_hi: float) -> float:
        """Exact resultant of the pressure field over a plan rectangle, N."""
        return _pressure_integrals(
            self.pressure,
            self.bx_mm,
            self.ly_mm,
            float(x_lo),
            float(x_hi),
            float(y_lo),
            float(y_hi),
        )[0]

    def critical(self, d_mm: float) -> Critical:
        return punching_critical(
            self.col_bx_mm, self.col_dy_mm, self.off_x_mm, self.off_y_mm, self.bx_mm, self.ly_mm, d_mm
        )


# ---------------------------------------------------------------------------
# plan sizing on service loads
# ---------------------------------------------------------------------------


def size_plan(
    p_service_kn: float,
    column: ColumnStub,
    soil: SoilProfile,
    ctx: FootingContext,
    ex_mm: float = 0.0,
    ey_mm: float = 0.0,
    off_x_mm: float = 0.0,
    off_y_mm: float = 0.0,
    placed_bx_mm: Optional[float] = None,
    placed_ly_mm: Optional[float] = None,
) -> PlanSize:
    """Plan dimensions for one pad, on SERVICE load with the self weight allowance.

    The area is P (1 + allowance) / q_allow, split to the column's own aspect
    ratio so a 230 x 450 column gets a rectangle the same way round, and rounded
    UP to the policy plan step. Three things can enlarge it beyond that: the
    minimum projection past the column face, the biaxial kern
    `6 |ex| / B + 6 |ey| / L <= 1`, and the corner pressure once the gradient is
    applied. The walk only ever grows, so it terminates, and the physical
    compression-only pressures on the settled size come back with it.
    """
    step = float(ctx.policy.footing_plan_step_mm)
    ratio = float(column.bx_mm) / float(column.dy_mm) if column.dy_mm > 0.0 else 1.0
    p_eff_n = C.kn_to_n(float(p_service_kn)) * (1.0 + float(ctx.self_weight_allowance))
    p_n = C.kn_to_n(float(p_service_kn))

    bx_floor = float(column.bx_mm) + 2.0 * (MIN_PROJECTION_MM + abs(float(off_x_mm)))
    ly_floor = float(column.dy_mm) + 2.0 * (MIN_PROJECTION_MM + abs(float(off_y_mm)))
    kern_bx = 6.0 * abs(float(ex_mm))
    kern_ly = 6.0 * abs(float(ey_mm))

    bx = C.round_up_mm(max(bx_floor, kern_bx, float(placed_bx_mm or 0.0)), step)
    ly = C.round_up_mm(max(ly_floor, kern_ly, float(placed_ly_mm or 0.0)), step)

    # The width the bearing capacity is read at is the width being solved for, so
    # the walk re-enters IS 6403 as the plan grows. Only the last reading is
    # traced: a report wants the chain that sized the footing, not the search.
    iterations = 0
    kern_grew = False
    with _quiet():
        for iterations in range(1, int(ctx.policy.max_iters) + 1):
            allow = allowable_pressure(soil, bx, ly)
            q_allow_mpa = max(float(allow.q_allow_kpa), _EPS) / 1000.0
            gradient = 1.0 + 6.0 * abs(float(ex_mm)) / bx + 6.0 * abs(float(ey_mm)) / ly
            area_req = p_eff_n * gradient / q_allow_mpa
            ly_target = math.sqrt(area_req / ratio) if ratio > 0.0 else math.sqrt(area_req)
            bx_target = ratio * ly_target
            bx_new = C.round_up_mm(max(bx_target, bx_floor, kern_bx, bx), step)
            ly_new = C.round_up_mm(max(ly_target, ly_floor, kern_ly, ly), step)
            kern_ratio = 6.0 * abs(float(ex_mm)) / bx_new + 6.0 * abs(float(ey_mm)) / ly_new
            if kern_ratio > 1.0 + _EPS:
                bx_new = C.round_up_mm(max(bx_new * kern_ratio, bx_floor, kern_bx), step)
                ly_new = C.round_up_mm(max(ly_new * kern_ratio, ly_floor, kern_ly), step)
                kern_grew = True
            if abs(bx_new - bx) < _EPS and abs(ly_new - ly) < _EPS:
                break
            bx, ly = bx_new, ly_new
    allow = allowable_pressure(soil, bx, ly)

    pressure = _contact_pressure(bx, ly, p_n, float(ex_mm), float(ey_mm))
    q_max = pressure.q_max_mpa * 1000.0
    q_min = pressure.q_min_mpa * 1000.0
    kern_ok = pressure.elastic_q_min_mpa >= -_EPS

    if kern_grew or kern_bx >= bx - _EPS or kern_ly >= ly - _EPS:
        driver = "kern eccentricity"
    elif bx_floor >= bx - _EPS and ly_floor >= ly - _EPS:
        driver = "minimum projection"
    else:
        driver = "bearing pressure"
    return PlanSize(
        bx_mm=bx,
        ly_mm=ly,
        q_allow_kpa=float(allow.q_allow_kpa),
        q_max_kpa=q_max,
        q_min_kpa=q_min,
        ex_mm=float(ex_mm),
        ey_mm=float(ey_mm),
        kern_ok=kern_ok,
        driver=driver,
        iterations=iterations,
        notes=(allow.source,) + tuple(allow.notes),
        contact_ratio=pressure.contact_ratio,
        elastic_q_min_kpa=pressure.elastic_q_min_mpa * 1000.0,
    )


# ---------------------------------------------------------------------------
# steel for one 1 m strip
# ---------------------------------------------------------------------------


class MeshSteel(NamedTuple):
    """The bars for one direction of a footing mat, per metre of width."""

    ast_req_mm2_m: float
    ast_flexure_mm2_m: float
    ast_min_mm2_m: float
    ast_prov_mm2_m: float
    dia_mm: int
    spacing_mm: float
    max_spacing_mm: float
    ld_mm: float
    note: str


def _ast_required(mu_nmm_per_m: float, d_mm: float, overall_d_mm: float, ctx: FootingContext) -> Tuple[float, float, float]:
    """(required, flexure, minimum) steel for a 1 m strip, mm2 per metre.

    The depth solvers call this thousands of times and need only the area, not a
    bar layout, so the diameter search in `mesh_steel` is not on this path.
    """
    fck = float(ctx.fck_mpa)
    fy = float(ctx.fy_mpa)
    mu_lim = is456.annex_g__mu_lim(1000.0, float(d_mm), fck, fy)
    demand = min(max(float(mu_nmm_per_m), 0.0), mu_lim)
    ast_flex = is456.annex_g__ast_singly(demand, 1000.0, float(d_mm), fck, fy)
    ast_min = is456.cl_26_5_2_1__min_slab_steel(float(overall_d_mm), fy, 1000.0)
    return (max(ast_flex, ast_min), ast_flex, ast_min)


def anchorage_dia_cap_mm(straight_mm: float, ctx: FootingContext, stress_ratio: float = 1.0) -> float:
    """Largest bar that develops in `straight_mm` plus its own 90 degree bend.

    Ld is proportional to the diameter and so is the bend allowance, so the rule
    solves in closed form: dia x (Ld per mm) x stress_ratio <= straight + 8 dia.
    `stress_ratio` is how hard the mat is actually worked, Ast_flexure over
    Ast_required: a mat sitting on the 0.12 percent minimum barely stresses its
    bars and is not diameter-limited, one designed to its moment is. A mat
    detailed past this cap carries bars that cannot reach the stress the section
    needs, and the honest fix is a smaller bar closer together, not a note.
    """
    per_mm = is456.cl_26_2_1__ld(1.0, float(ctx.fy_mpa), float(ctx.fck_mpa))
    slope = per_mm * max(min(float(stress_ratio), 1.0), 0.0) - _BEND_ANCHORAGE_DIA
    if slope <= 0.0:
        return float(max(ctx.bar_dias_mm))
    return max(float(straight_mm), 0.0) / slope


def _stress_ratio(mu_nmm_per_m: float, d_mm: float, overall_d_mm: float, ctx: FootingContext) -> float:
    """How much of the mat's steel the moment actually calls for, 0 to 1."""
    ast_req, ast_flex, _minimum = _ast_required(mu_nmm_per_m, d_mm, overall_d_mm, ctx)
    return min(1.0, ast_flex / ast_req) if ast_req > 0.0 else 0.0


def _usable_dias(ctx: FootingContext, max_dia_mm: Optional[float]) -> Tuple[int, ...]:
    """The catalogue under a diameter cap, never emptied of its smallest bar."""
    dias = tuple(sorted(int(dia) for dia in ctx.bar_dias_mm))
    if max_dia_mm is None:
        return dias
    kept = tuple(dia for dia in dias if dia <= float(max_dia_mm) + _EPS)
    return kept or dias[:1]


def mesh_steel(
    mu_nmm_per_m: float,
    d_mm: float,
    overall_d_mm: float,
    ctx: FootingContext,
    dia_mm: Optional[int] = None,
    max_dia_mm: Optional[float] = None,
) -> MeshSteel:
    """Bars for a 1 m strip: Annex G area, the 0.12 percent floor, then a spacing.

    The diameter is the smallest in the catalogue whose spacing lands at or above
    the placing floor and at or below the Cl 26.3.3 cap; when even the largest is
    too tight the largest is used and the note says the mat is congested, which
    the caller turns into a warning rather than a refusal.
    """
    fy = float(ctx.fy_mpa)
    demand = max(float(mu_nmm_per_m), 0.0)
    mu_lim = is456.annex_g__mu_lim(1000.0, float(d_mm), float(ctx.fck_mpa), fy)
    note = ""
    if demand > mu_lim:
        note = "moment " + _n(demand / 1e6, 1) + " kNm/m is past the singly reinforced limit for this depth"
    ast_req, ast_flex, _ast_min = _ast_required(demand, d_mm, overall_d_mm, ctx)
    max_spacing = is456.cl_26_3_3__max_spacing_flexure("slab", float(d_mm), fy)

    dias = _usable_dias(ctx, max_dia_mm)
    if dia_mm is not None:
        chosen = int(dia_mm)
        spacing = C.spacing_for_area(ast_req, chosen, max_spacing, 10.0)
    else:
        chosen = dias[-1]
        spacing = C.spacing_for_area(ast_req, chosen, max_spacing, 10.0)
        for dia in dias:
            trial = C.spacing_for_area(ast_req, dia, max_spacing, 10.0)
            if trial >= MIN_MESH_SPACING_MM - _EPS:
                chosen, spacing = dia, trial
                break
    if spacing < MIN_MESH_SPACING_MM - _EPS:
        note = (note + "; " if note else "") + (
            "even " + str(chosen) + " mm bars need " + _mm_text(spacing) + " centres, below the "
            + _mm_text(MIN_MESH_SPACING_MM) + " placing floor"
        )
    return MeshSteel(
        ast_req_mm2_m=ast_req,
        ast_flexure_mm2_m=ast_flex,
        ast_min_mm2_m=_ast_min,
        ast_prov_mm2_m=C.area_for_spacing(chosen, spacing),
        dia_mm=int(chosen),
        spacing_mm=spacing,
        max_spacing_mm=max_spacing,
        ld_mm=is456.cl_26_2_1__ld(chosen, fy, float(ctx.fck_mpa)),
        note=note,
    )


# ---------------------------------------------------------------------------
# depth: the three requirements, each solved for its own d
# ---------------------------------------------------------------------------


class DepthDemand(NamedTuple):
    """What one criterion asks of the effective depth."""

    name: str
    clause: str
    d_req_mm: Optional[float]
    detail: str


def _overall_from_effective(d_mm: float, cover_mm: float, dia_mm: float) -> float:
    """D = d + cover + 1.5 bar diameters: two mats, the upper one half a bar higher."""
    return float(d_mm) + float(cover_mm) + 1.5 * float(dia_mm)


def _required_d_punching(field: _Field, ctx: FootingContext, beta_c: float) -> DepthDemand:
    """Effective depth the two-way shear at d/2 asks for, Cl 31.6.3.

    The search stops where the critical rectangle reaches the plan edge: past
    that there is no perimeter to punch through and the mode does not exist, so
    extending the window would read a clipped perimeter as a refusal.
    """

    def residual(d_mm: float) -> float:
        crit = field.critical(d_mm)
        if crit.perimeter_mm <= 0.0:
            return -1.0
        inside = field.load_in(crit.x_lo_mm, crit.x_hi_mm, crit.y_lo_mm, crit.y_hi_mm)
        shear = max(float(field.pu_n) - inside, 0.0)
        tau_v = shear / (crit.perimeter_mm * d_mm)
        check = is456.cl_31_6_3__punching(tau_v, float(ctx.fck_mpa), beta_c)
        return tau_v - check.capacity_mpa

    with _quiet():
        d_req = _bisect_min_d(residual)
    return DepthDemand(
        name="two-way shear",
        clause="IS 456 Cl 31.6.3",
        d_req_mm=d_req,
        detail="punching on the perimeter at d/2",
    )


def _required_d_one_way(field: _Field, ctx: FootingContext, axis: str, side: float, cover_mm: float) -> DepthDemand:
    """Effective depth the one-way shear at d from the face asks for, Cl 40.

    tau_c is read at the steel THIS direction gets at the trial depth, so the
    check iterates against the provided pt instead of a guessed one.
    """
    dia_seed = int(sorted(ctx.bar_dias_mm)[0])

    def residual(d_mm: float) -> float:
        _dim, other, _col, _off, _grad = field.axis(axis)
        shear, _moment = field.cantilever(axis, side, back_off_mm=d_mm)
        if shear <= 0.0:
            return -1.0
        tau_v = is456.cl_40_1__tau_v(shear, other, d_mm)
        _force, moment = field.cantilever(axis, side)
        mu_per_m = 1000.0 * moment / other if other > 0.0 else 0.0
        overall = _overall_from_effective(d_mm, cover_mm, dia_seed)
        ast_req, _flex, _minimum = _ast_required(mu_per_m, d_mm, overall, ctx)
        pt = 100.0 * ast_req / (1000.0 * d_mm)
        return tau_v - is456.table_19__tau_c(pt, float(ctx.fck_mpa))

    with _quiet():
        d_req = _bisect_min_d(residual)
    return DepthDemand(
        name="one-way shear " + axis,
        clause="IS 456 Cl 40.1, Table 19",
        d_req_mm=d_req,
        detail="shear at d from the column face on the " + ("positive" if side > 0 else "negative") + " " + axis + " side",
    )


def _required_d_flexure(field: _Field, ctx: FootingContext, axis: str, side: float) -> DepthDemand:
    """Effective depth that keeps the face moment singly reinforced, Cl 34.2.3.2."""
    _dim, other, _col, _off, _grad = field.axis(axis)
    _force, moment = field.cantilever(axis, side)
    mu_per_m = 1000.0 * moment / other if other > 0.0 else 0.0

    def residual(d_mm: float) -> float:
        return mu_per_m - is456.annex_g__mu_lim(1000.0, d_mm, float(ctx.fck_mpa), float(ctx.fy_mpa))

    with _quiet():
        d_req = _bisect_min_d(residual)
    return DepthDemand(
        name="flexure " + axis,
        clause="IS 456 Cl 34.2.3.2, G-1.1(b)",
        d_req_mm=d_req,
        detail="cantilever moment " + _n(mu_per_m / 1e6, 2) + " kNm per metre at the column face",
    )


# ---------------------------------------------------------------------------
# the Cl 34.3.1.2 central band and the Cl 34.4 dowels
# ---------------------------------------------------------------------------


class BandSteel(NamedTuple):
    """Short-direction steel split into the central band and the outer strips."""

    steel: MeshSteel
    beta: float
    band_fraction: float
    band_width_mm: float
    spacing_band_mm: float
    spacing_outer_mm: float
    note: str


def band_steel(
    mu_nmm_per_m: float,
    d_mm: float,
    overall_d_mm: float,
    ctx: FootingContext,
    beta: float,
    short_dim_mm: float,
    max_dia_mm: Optional[float] = None,
) -> BandSteel:
    """Cl 34.3.1.2: 2 / (beta + 1) of the short-direction steel in the central band.

    The band is as wide as the short side of the footing, centred on the column.
    Working in spacings rather than areas keeps the arithmetic exact: uniform
    spacing s over the long side L becomes s / (f beta) inside the band and
    s (beta + 1) / beta outside it, and the outer strips are then clamped back to
    the 0.12 percent minimum and the Cl 26.3.3 spacing cap, which the bare
    redistribution can otherwise walk past on a long footing.
    """
    ratio = max(float(beta), 1.0)
    fraction = is456.cl_34_3_1_2__band_distribution(ratio)
    dias = _usable_dias(ctx, max_dia_mm)
    steel = mesh_steel(mu_nmm_per_m, d_mm, overall_d_mm, ctx, max_dia_mm=max_dia_mm)
    spacing_band = C.round_down_mm(steel.spacing_mm / (fraction * ratio), 10.0)
    note = ""
    for dia in dias:
        if dia < steel.dia_mm:
            continue
        trial = mesh_steel(mu_nmm_per_m, d_mm, overall_d_mm, ctx, dia_mm=dia)
        trial_band = C.round_down_mm(trial.spacing_mm / (fraction * ratio), 10.0)
        steel, spacing_band = trial, trial_band
        if trial_band >= MIN_MESH_SPACING_MM - _EPS:
            break
    if spacing_band < MIN_MESH_SPACING_MM - _EPS:
        note = (
            "central band needs " + _mm_text(spacing_band) + " centres at " + str(steel.dia_mm)
            + " mm, below the " + _mm_text(MIN_MESH_SPACING_MM) + " placing floor"
        )
    spacing_band = max(spacing_band, 10.0)
    outer_raw = steel.spacing_mm * (ratio + 1.0) / ratio
    min_steel_spacing = C.spacing_for_area(steel.ast_min_mm2_m, steel.dia_mm, steel.max_spacing_mm, 10.0)
    spacing_outer = C.round_down_mm(min(outer_raw, min_steel_spacing, steel.max_spacing_mm), 10.0)
    return BandSteel(
        steel=steel,
        beta=ratio,
        band_fraction=fraction,
        band_width_mm=float(short_dim_mm),
        spacing_band_mm=spacing_band,
        spacing_outer_mm=max(spacing_outer, 10.0),
        note=note,
    )


class Dowels(NamedTuple):
    """Dowel group across the column to footing joint, Cl 34.4."""

    count: int
    dia_mm: int
    area_req_mm2: float
    area_prov_mm2: float
    ld_mm: float
    available_mm: float
    d_needed_mm: float
    bearing_demand_mpa: float
    bearing_capacity_mpa: float
    frustum_ratio: float
    excess_n: float
    note: str


def dowels(
    pu_n: float,
    column: ColumnStub,
    bx_mm: float,
    ly_mm: float,
    off_x_mm: float,
    off_y_mm: float,
    overall_d_mm: float,
    cover_mm: float,
    mesh_dia_mm: float,
    ctx: FootingContext,
) -> Dowels:
    """Bearing at the column face and the dowels that carry what it cannot.

    A1 is the largest frustum area geometrically similar to and concentric with
    the column, so its side ratio is the column's: the limit on the scale factor
    is the 2:1 spread through the footing depth on each axis and the plan edge
    nearest the column. sqrt(A1/A2) is then that scale factor, which Cl 34.4 caps
    at 2. Any force the permissible stress cannot take is carried by dowels at
    0.67 fy, the same compressive stress Cl 39.3 credits to column steel, and the
    group is never smaller than the Cl 34.4.3 half a percent in four bars.

    Compression bars develop no anchorage from a bend (Cl 26.2.2.1), so the
    compression Ld has to fit inside the depth: `d_needed_mm` is the overall
    depth that would let it, and the caller bumps to it and discloses the bump.
    """
    a2 = column.area_mm2
    col_bx = float(column.bx_mm)
    col_dy = float(column.dy_mm)
    edge_x = min(0.5 * float(bx_mm) - float(off_x_mm), 0.5 * float(bx_mm) + float(off_x_mm))
    edge_y = min(0.5 * float(ly_mm) - float(off_y_mm), 0.5 * float(ly_mm) + float(off_y_mm))
    scale = min(
        1.0 + 4.0 * float(overall_d_mm) / col_bx,
        1.0 + 4.0 * float(overall_d_mm) / col_dy,
        2.0 * max(edge_x, 0.0) / col_bx,
        2.0 * max(edge_y, 0.0) / col_dy,
    )
    scale = max(scale, 1.0)
    bearing = is456.cl_34_4__bearing(float(ctx.fck_mpa), scale * scale * a2, a2)
    demand = float(pu_n) / a2 if a2 > 0.0 else 0.0
    excess = max((demand - bearing.stress_mpa) * a2, 0.0)
    spec = is456.cl_34_4_3__min_dowels(a2)
    area_req = max(spec.area_mm2, excess / (DOWEL_STRESS_FACTOR * float(ctx.fy_mpa)))

    dias = tuple(sorted(int(dia) for dia in DOWEL_DIAS_MM))
    dia = dias[-1]
    count = int(spec.min_bars)
    for candidate in dias:
        need = int(math.ceil(area_req / C.bar_area_mm2(candidate) - _EPS))
        need = max(need, int(spec.min_bars))
        if need % 2 == 1:
            need += 1
        dia, count = candidate, need
        if need <= MAX_DOWEL_BARS:
            break
    ld = is456.cl_26_2_1__ld(dia, float(ctx.fy_mpa), float(ctx.fck_mpa), compression=True)
    available = float(overall_d_mm) - float(cover_mm) - 2.0 * float(mesh_dia_mm)
    note = ""
    if available < ld - _EPS:
        note = (
            "dowel compression Ld " + _mm_text(ld) + " does not fit in the " + _mm_text(available)
            + " available below the column; a bend adds no anchorage in compression (Cl 26.2.2.1)"
        )
    return Dowels(
        count=int(count),
        dia_mm=int(dia),
        area_req_mm2=area_req,
        area_prov_mm2=count * C.bar_area_mm2(dia),
        ld_mm=ld,
        available_mm=available,
        d_needed_mm=ld + float(cover_mm) + 2.0 * float(mesh_dia_mm),
        bearing_demand_mpa=demand,
        bearing_capacity_mpa=bearing.stress_mpa,
        frustum_ratio=bearing.area_ratio,
        excess_n=excess,
        note=note,
    )


def bar_count(width_mm: float, cover_mm: float, spacing_mm: float) -> int:
    """Bars a mesh puts across a strip: the ends sit one cover in from the edge."""
    usable = max(float(width_mm) - 2.0 * float(cover_mm), 0.0)
    if spacing_mm <= 0.0:
        return 2
    return max(2, int(math.floor(usable / float(spacing_mm) + _EPS)) + 1)


def _anchorage(
    ld_mm: float, ast_flexure: float, ast_prov: float, straight_mm: float, dia_mm: float
) -> Tuple[float, float, bool, bool]:
    """(required, available, bend used, relaxed) for a bar run out to the edge.

    A bar is developed from the critical section to its end: the straight run is
    the projection past the face less the end cover, and a standard 90 degree
    bend adds its anchorage value (IS 2502 allowance, 8 diameters). Where the
    straight plus bend still falls short, the requirement is taken at the stress
    the bar actually carries, Ld x Ast_flexure / Ast_provided, and the caller
    discloses that as a note rather than applying it in silence. The FLEXURAL
    area is the right numerator: a mat governed by the 0.12 percent minimum is
    barely stressed at the column face, and asking it to develop a full Ld would
    condemn every small pad in the catalogue for a stress it never carries.
    """
    available = float(straight_mm)
    bend = False
    if available < float(ld_mm) - _EPS:
        available += _BEND_ANCHORAGE_DIA * float(dia_mm)
        bend = True
    required = float(ld_mm)
    relaxed = False
    if available < required - _EPS and ast_prov > 0.0:
        required = float(ld_mm) * min(1.0, max(float(ast_flexure), 0.0) / float(ast_prov))
        relaxed = True
    return (required, available, bend, relaxed)


class _PadEval(NamedTuple):
    """One trial depth, fully checked."""

    d_mm: float
    overall_d_mm: float
    dia_mm: int
    steel_x: MeshSteel
    steel_y: MeshSteel
    arm_x_mm: float
    arm_y_mm: float
    band: Optional[BandSteel]
    dowel: Dowels
    rows: Tuple[Tuple[Any, ...], ...]
    depth_ratios: Tuple[Tuple[str, float], ...]
    ok: bool
    reason: str


def _pad_evaluate(
    field: _Field,
    plan: PlanSize,
    column: ColumnStub,
    ctx: FootingContext,
    overall_d_mm: float,
    cover_mm: float,
) -> _PadEval:
    """Every check on one trial thickness, with the steel that goes with it.

    The mesh diameter and the effective depth chase each other (a fatter bar
    lowers d, a lower d asks for more steel), so the pair is settled by a short
    fixed-point walk over the catalogue before anything is checked.
    """
    fck = float(ctx.fck_mpa)
    fy = float(ctx.fy_mpa)
    dia = int(sorted(ctx.bar_dias_mm)[0])
    d_mm = float(overall_d_mm) - float(cover_mm) - 1.5 * dia
    moments = {}  # type: Dict[str, float]
    arms = {}  # type: Dict[str, float]
    steels = {}  # type: Dict[str, MeshSteel]

    def both_axes(depth_mm: float) -> None:
        """Face moment, its cantilever and the mat, for each direction at one d."""
        for axis in ("x", "y"):
            _dim, other, _col, _off, _grad = field.axis(axis)
            worst = 0.0
            arm = 0.0
            for side in (1.0, -1.0):
                _force, moment = field.cantilever(axis, side)
                value = 1000.0 * moment / other if other > 0.0 else 0.0
                if value >= worst:
                    worst, arm = value, field.arm_mm(axis, side)
            moments[axis] = worst
            arms[axis] = arm
            steels[axis] = mesh_steel(
                worst,
                depth_mm,
                float(overall_d_mm),
                ctx,
                max_dia_mm=anchorage_dia_cap_mm(
                    arm - float(cover_mm), ctx, _stress_ratio(worst, depth_mm, float(overall_d_mm), ctx)
                ),
            )

    for _pass in range(4):
        d_mm = float(overall_d_mm) - float(cover_mm) - 1.5 * dia
        if d_mm <= 0.0:
            break
        both_axes(d_mm)
        wanted = max(steels["x"].dia_mm, steels["y"].dia_mm)
        if wanted == dia:
            break
        dia = wanted
    d_mm = max(d_mm, 1.0)
    if not steels:
        both_axes(d_mm)

    short_axis = "x" if field.bx_mm <= field.ly_mm else "y"
    long_axis = "y" if short_axis == "x" else "x"
    beta = max(field.bx_mm, field.ly_mm) / min(field.bx_mm, field.ly_mm)
    short_dim = min(field.bx_mm, field.ly_mm)
    band = None  # type: Optional[BandSteel]
    if beta > 1.0 + 1e-6:
        band = band_steel(
            moments[short_axis],
            d_mm,
            float(overall_d_mm),
            ctx,
            beta,
            short_dim,
            max_dia_mm=anchorage_dia_cap_mm(
                arms[short_axis] - float(cover_mm),
                ctx,
                _stress_ratio(moments[short_axis], d_mm, float(overall_d_mm), ctx),
            ),
        )
        steels[short_axis] = band.steel

    rows = []  # type: List[Tuple[Any, ...]]
    ratios = []  # type: List[Tuple[str, float]]

    rows.append(("bearing pressure", plan.notes[0], plan.q_max_kpa, plan.q_allow_kpa, "kPa"))
    if abs(plan.ex_mm) > _EPS or abs(plan.ey_mm) > _EPS:
        rows.append(
            (
                "biaxial kern",
                "IS 456 Cl 34.1, full base contact",
                6.0 * abs(plan.ex_mm) / plan.bx_mm + 6.0 * abs(plan.ey_mm) / plan.ly_mm,
                1.0,
                "ratio",
            )
        )

    crit = field.critical(d_mm)
    inside = field.load_in(crit.x_lo_mm, crit.x_hi_mm, crit.y_lo_mm, crit.y_hi_mm)
    punch_shear = max(field.pu_n - inside, 0.0)
    # A critical section that has swallowed the whole footing has no perimeter to
    # punch through: the mode does not exist, it is not an infinite stress.
    tau_punch = punch_shear / (crit.perimeter_mm * d_mm) if crit.perimeter_mm > 0.0 else 0.0
    punch = is456.cl_31_6_3__punching(tau_punch, fck, column.beta_c)
    rows.append(("two-way shear", "IS 456 Cl 31.6.3", tau_punch, punch.capacity_mpa, "MPa"))
    ratios.append(("two-way shear", tau_punch / punch.capacity_mpa if punch.capacity_mpa > 0.0 else C.RATIO_CAP))

    for axis in ("x", "y"):
        _dim, other, _col, _off, _grad = field.axis(axis)
        tau_v = 0.0
        for side in (1.0, -1.0):
            shear, _moment = field.cantilever(axis, side, back_off_mm=d_mm)
            if shear > 0.0:
                tau_v = max(tau_v, is456.cl_40_1__tau_v(shear, other, d_mm))
        pt = 100.0 * steels[axis].ast_prov_mm2_m / (1000.0 * d_mm)
        tau_c = is456.table_19__tau_c(pt, fck)
        rows.append(("one-way shear " + axis, "IS 456 Cl 40.1, Table 19", tau_v, tau_c, "MPa"))
        ratios.append(("one-way shear " + axis, tau_v / tau_c if tau_c > 0.0 else C.RATIO_CAP))

        mu_lim = is456.annex_g__mu_lim(1000.0, d_mm, fck, fy)
        rows.append(("flexure " + axis, "IS 456 Cl 34.2.3.2, G-1.1(b)", moments[axis], mu_lim, "N.mm per m"))
        ratios.append(("flexure " + axis, moments[axis] / mu_lim if mu_lim > 0.0 else C.RATIO_CAP))

        rows.append(
            ("steel " + axis, "IS 456 Cl 26.5.2.1", steels[axis].ast_req_mm2_m, steels[axis].ast_prov_mm2_m, "mm2 per m")
        )
        rows.append(
            ("bar spacing " + axis, "IS 456 Cl 26.3.3", steels[axis].spacing_mm, steels[axis].max_spacing_mm, "mm")
        )

    rows.append(("edge thickness", "IS 456 Cl 34.1.2", is456.cl_34_1_2__min_edge_thickness(), float(overall_d_mm), "mm"))

    dowel = dowels(
        field.pu_n,
        column,
        field.bx_mm,
        field.ly_mm,
        field.off_x_mm,
        field.off_y_mm,
        float(overall_d_mm),
        float(cover_mm),
        dia,
        ctx,
    )
    joint_capacity = dowel.bearing_capacity_mpa * column.area_mm2 + DOWEL_STRESS_FACTOR * fy * dowel.area_prov_mm2
    limits = is456.cl_26_5_3_1__long_steel_limits(column.area_mm2)
    rows.append(("bearing at column face", "IS 456 Cl 34.4", field.pu_n, joint_capacity, "N"))
    rows.append(("dowel steel", "IS 456 Cl 34.4.3", dowel.area_req_mm2, dowel.area_prov_mm2, "mm2"))
    rows.append(("dowel steel ratio", "IS 456 Cl 26.5.3.1", dowel.area_prov_mm2, limits.asc_max_mm2, "mm2"))
    rows.append(("dowel anchorage", "IS 456 Cl 26.2.1", dowel.ld_mm, dowel.available_mm, "mm"))

    for axis in ("x", "y"):
        steel = steels[axis]
        required, available, _bend, _relaxed = _anchorage(
            steel.ld_mm, steel.ast_flexure_mm2_m, steel.ast_prov_mm2_m, arms[axis] - float(cover_mm), steel.dia_mm
        )
        rows.append(("bar anchorage " + axis, "IS 456 Cl 26.2.1", required, available, "mm"))

    depth_names = DEPTH_DRIVEN_CHECKS
    reason = ""
    for row in rows:
        if row[0] in depth_names and row[3] > 0.0 and row[2] > row[3] * (1.0 + C.CHECK_TOL):
            reason = str(row[0])
            break
        if row[0] in depth_names and row[3] <= 0.0 and row[2] > 0.0:
            reason = str(row[0])
            break
    return _PadEval(
        d_mm=d_mm,
        overall_d_mm=float(overall_d_mm),
        dia_mm=int(dia),
        steel_x=steels["x"],
        steel_y=steels["y"],
        arm_x_mm=arms.get("x", 0.0),
        arm_y_mm=arms.get("y", 0.0),
        band=band,
        dowel=dowel,
        rows=tuple(rows),
        depth_ratios=tuple(ratios),
        ok=not reason,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# the isolated pad
# ---------------------------------------------------------------------------


def _as_pad_inputs(
    footing: Any, loads: Any, soil: Any, ctx: Any
) -> Tuple[Any, Any, Any, Any]:
    """Accept the demands-first call the sibling package makes, and plain dicts.

    `run_rcc_design` dispatches every member designer as
    `designer(demands, geometry, ctx)`, which is the opposite order to this
    module's own (geometry, loads, soil, ctx) and leaves no room for the soil.
    Demands in the first slot can only mean that call, so the arguments are put
    back in order rather than designed nonsense; a geometry that arrives as a
    mapping or a load set that arrives as a footing force envelope are read
    through their own converters.
    """
    if isinstance(footing, (FootingLoads,)) or _is_footing_envelope(footing):
        footing, loads, soil, ctx = loads, footing, None, (ctx if ctx is not None else soil)
    if isinstance(footing, Mapping):
        footing = PadGeometry.from_mapping(footing)
    if _is_footing_envelope(loads):
        loads = FootingLoads.from_envelope(loads)
    return (footing, loads, soil, ctx)


def _is_footing_envelope(value: Any) -> bool:
    """True for an `analysis.ForceEnvelope` of element_type "footing"."""
    return getattr(value, "element_type", None) == "footing" and hasattr(value, "stations")


def design_footing(footing: PadGeometry, loads: FootingLoads, soil: Any = None, ctx: Any = None) -> C.DesignResult:
    """Design one isolated pad and return a fully populated DesignResult.

    Never raises. A pad that cannot be made to work at any depth in the search
    window comes back with status fail, the check that beat it as
    `governing_check`, and every row that was evaluated on the way.

    `governing_check` on a pad that DOES work names the depth-driving check
    (punching, one-way shear or flexure) running closest to its limit on the
    adopted section, because a footing is sized by its thickness;
    `utilization_max` still reports the highest ratio anywhere in the list, which
    is often a rounded-up bar count rather than a structural check.
    """
    entries = []  # type: List[TraceEntry]
    result = C.DesignResult(element_id="footing", element_type="footing")
    try:
        with trace_into(entries):
            footing, loads, soil, ctx = _as_pad_inputs(footing, loads, soil, ctx)
            result.element_id = str(getattr(footing, "element_id", "") or "footing")
            context = FootingContext.coerce(ctx)
            profile = SoilProfile.from_params(soil)
            result.materials = C.materials_block(context.concrete, context.steel)
            _pad_body(result, footing, loads, profile, context)
    except Exception as error:  # noqa: BLE001 - disclose, never hide
        result.add_warning("footing design stopped on an internal error: " + repr(error))
        result.fail_with("internal error")
    result.trace = entries
    return result


def _pad_body(
    result: C.DesignResult,
    geom: PadGeometry,
    loads: FootingLoads,
    soil: SoilProfile,
    ctx: FootingContext,
) -> C.DesignResult:
    """The pad walk: pressure, plan, depth, steel, dowels. Fills `result`."""
    column = geom.column
    result.section["kind"] = str(geom.kind)
    result.section["column_bx_mm"] = float(column.bx_mm)
    result.section["column_dy_mm"] = float(column.dy_mm)

    if column.bx_mm <= 0.0 or column.dy_mm <= 0.0:
        return result.fail_with(
            "column section",
            "column section " + _mm_text(column.bx_mm) + " x " + _mm_text(column.dy_mm)
            + " is not a section: a footing is sized by the column it carries, so pass a ColumnStub or the "
            "col_bx_mm and col_dy_mm keys rather than have one invented",
            clause="IS 456 Cl 34.4",
            demand=1.0,
            capacity=0.0,
            units="mm",
        )
    if float(loads.p_service_kn) <= 0.0:
        return result.fail_with(
            "service load",
            "service load " + _n(loads.p_service_kn, 2) + " kN: a footing needs a load to be sized against",
            clause="IS 6403",
            demand=1.0,
            capacity=0.0,
            units="kN",
        )

    grade = C.check_exposure_grade(float(ctx.fck_mpa), ctx.exposure)
    if grade:
        result.add_warning(grade)

    seed_dia = int(sorted(ctx.bar_dias_mm)[0])
    cover = C.resolve_cover("footing", ctx.exposure, ctx.fire_rating_h, seed_dia)
    result.add_note(cover.note)
    result.add_note(
        "both mats are designed at the mean effective depth D - cover - 1.5 bar diameters, "
        "which sits between the lower and the upper layer"
    )

    off_x = C.m_to_mm(geom.col_offset_x_m)
    off_y = C.m_to_mm(geom.col_offset_y_m)
    p_service_kn = float(loads.p_service_kn)
    pu_kn = loads.factored_p_kn(ctx.load_factor)
    ex_mm = C.m_to_mm(float(loads.mx_service_knm) / p_service_kn) if p_service_kn > 0.0 else 0.0
    ey_mm = C.m_to_mm(float(loads.my_service_knm) / p_service_kn) if p_service_kn > 0.0 else 0.0
    ex_u_mm = C.m_to_mm(loads.factored_mx_knm(ctx.load_factor) / pu_kn) if pu_kn > 0.0 else 0.0
    ey_u_mm = C.m_to_mm(loads.factored_my_knm(ctx.load_factor) / pu_kn) if pu_kn > 0.0 else 0.0

    if geom.strap_partner_id or str(geom.kind).lower() == "strap":
        p_service_kn, pu_kn, ex_mm, ey_mm, ex_u_mm, ey_u_mm = _strap_referral(
            result, geom, loads, ctx, p_service_kn, pu_kn
        )

    plan = size_plan(
        p_service_kn,
        column,
        soil,
        ctx,
        ex_mm=ex_mm,
        ey_mm=ey_mm,
        off_x_mm=off_x,
        off_y_mm=off_y,
        placed_bx_mm=None if geom.placed_bx_m is None else C.m_to_mm(geom.placed_bx_m),
        placed_ly_mm=None if geom.placed_ly_m is None else C.m_to_mm(geom.placed_ly_m),
    )
    for note in plan.notes[1:]:
        result.add_note(note)
    result.add_note(
        "plan sized on the service load with a " + _n(100.0 * ctx.self_weight_allowance, 0)
        + " percent self weight allowance"
    )
    if geom.placed_bx_m is not None and geom.placed_ly_m is not None:
        placed = (C.m_to_mm(geom.placed_bx_m), C.m_to_mm(geom.placed_ly_m))
        if abs(placed[0] - plan.bx_mm) > _EPS or abs(placed[1] - plan.ly_mm) > _EPS:
            result.add_resize(
                _mm_text(placed[0]) + " x " + _mm_text(placed[1]),
                _mm_text(plan.bx_mm) + " x " + _mm_text(plan.ly_mm),
                "plan enlarged: " + plan.driver,
            )
    if not plan.kern_ok:
        result.add_warning(
            "eccentricity is outside the kern even at " + _mm_text(plan.bx_mm) + " x " + _mm_text(plan.ly_mm)
            + "; part of the base would lift"
        )

    field = _Field(
        bx_mm=plan.bx_mm,
        ly_mm=plan.ly_mm,
        col_bx_mm=float(column.bx_mm),
        col_dy_mm=float(column.dy_mm),
        off_x_mm=off_x,
        off_y_mm=off_y,
        pu_n=C.kn_to_n(pu_kn),
        ex_mm=ex_u_mm,
        ey_mm=ey_u_mm,
    )

    demands = [_required_d_punching(field, ctx, column.beta_c)]
    for axis in ("x", "y"):
        _dim, _other, _col, off, grad = field.axis(axis)
        # A concentric column under a uniform pressure has two identical sides:
        # checking the mirror image would double the search for nothing.
        sides = (1.0,) if abs(off) <= _EPS and abs(grad) <= _EPS else (1.0, -1.0)
        for maker in (_required_d_one_way, _required_d_flexure):
            best = None  # type: Optional[DepthDemand]
            for side in sides:
                if maker is _required_d_one_way:
                    trial = _required_d_one_way(field, ctx, axis, side, cover.cover_mm)
                else:
                    trial = _required_d_flexure(field, ctx, axis, side)
                if best is None or _worse(trial, best):
                    best = trial
            demands.append(best)

    refused = [demand for demand in demands if demand.d_req_mm is None]
    d_req = max([demand.d_req_mm for demand in demands if demand.d_req_mm is not None] or [_D_SEARCH_MIN_MM])
    step = float(ctx.policy.footing_depth_step_mm)
    overall = max(
        is456.cl_34_1_2__min_edge_thickness(),
        C.round_up_mm(d_req + cover.cover_mm + 1.5 * seed_dia, step),
        0.0 if geom.specified_thickness_m is None else C.m_to_mm(geom.specified_thickness_m),
    )
    if geom.specified_thickness_m is not None and abs(C.m_to_mm(geom.specified_thickness_m) - overall) > _EPS:
        result.add_resize(
            _mm_text(C.m_to_mm(geom.specified_thickness_m)),
            _mm_text(overall),
            "depth set by " + _deepest(demands),
        )

    evaluation = None  # type: Optional[_PadEval]
    for _attempt in range(int(ctx.policy.max_iters)):
        with _quiet():
            evaluation = _pad_evaluate(field, plan, column, ctx, overall, cover.cover_mm)
        if evaluation.ok:
            break
        bumped = overall + step
        if evaluation.reason == "dowel anchorage":
            bumped = max(bumped, C.round_up_mm(evaluation.dowel.d_needed_mm, step))
        result.add_resize(_mm_text(overall), _mm_text(bumped), "depth increased for " + evaluation.reason)
        overall = bumped
    evaluation = _pad_evaluate(field, plan, column, ctx, overall, cover.cover_mm)

    _emit_pad(result, geom, plan, field, column, ctx, cover.cover_mm, evaluation)
    for demand in refused:
        result.add_warning(
            demand.name + " (" + demand.clause + ") cannot be satisfied at any depth up to "
            + _mm_text(_D_SEARCH_MAX_MM) + ": " + demand.detail
        )
    _settle(result, evaluation)
    if refused:
        result.governing_check = refused[0].name
        result.status = C.STATUS_FAIL
    return result


def _emit_pad(
    result: C.DesignResult,
    geom: PadGeometry,
    plan: PlanSize,
    field: _Field,
    column: ColumnStub,
    ctx: FootingContext,
    cover_mm: float,
    ev: _PadEval,
) -> None:
    """Write the settled pad into the result: section, checks, bars, dowels."""
    result.section.update(
        {
            "bx_mm": plan.bx_mm,
            "ly_mm": plan.ly_mm,
            "D_mm": ev.overall_d_mm,
            "d_mm": ev.d_mm,
            "cover_mm": float(cover_mm),
            "column_offset_x_mm": field.off_x_mm,
            "column_offset_y_mm": field.off_y_mm,
            "q_allow_kpa": plan.q_allow_kpa,
            "q_max_kpa": plan.q_max_kpa,
            "q_min_kpa": plan.q_min_kpa,
            "elastic_q_min_kpa": plan.elastic_q_min_kpa,
            "contact_ratio": plan.contact_ratio,
            "qu_mpa": field.q0_mpa,
        }
    )
    result.extras["si"] = {
        "bx_m": C.mm_to_m(plan.bx_mm),
        "ly_m": C.mm_to_m(plan.ly_mm),
        "depth_m": C.mm_to_m(ev.overall_d_mm),
    }
    for name, clause, demand, capacity, units in ev.rows:
        result.add_check(name, clause, demand, capacity, units=units)

    short_axis = "x" if field.bx_mm <= field.ly_mm else "y"
    long_axis = "y" if short_axis == "x" else "x"
    short_dim = min(field.bx_mm, field.ly_mm)
    long_dim = max(field.bx_mm, field.ly_mm)
    steels = {"x": ev.steel_x, "y": ev.steel_y}

    uniform = steels[long_axis]
    result.add_bar(
        role="mesh_" + long_axis + "_bottom",
        count=bar_count(short_dim, cover_mm, uniform.spacing_mm),
        dia_mm=uniform.dia_mm,
        ld_mm=uniform.ld_mm,
        zone_mm=[cover_mm, long_dim - cover_mm],
        layer=1,
        spacing_mm=uniform.spacing_mm,
        direction=long_axis,
        face="bottom",
        strip="full width",
    )

    banded = steels[short_axis]
    if ev.band is None:
        result.add_bar(
            role="mesh_" + short_axis + "_bottom",
            count=bar_count(long_dim, cover_mm, banded.spacing_mm),
            dia_mm=banded.dia_mm,
            ld_mm=banded.ld_mm,
            zone_mm=[cover_mm, short_dim - cover_mm],
            layer=2,
            spacing_mm=banded.spacing_mm,
            direction=short_axis,
            face="bottom",
            strip="full width",
        )
    else:
        band = ev.band
        result.add_note(
            "Cl 34.3.1.2 central band: " + _n(100.0 * band.band_fraction, 1) + " percent of the short direction "
            "steel sits in the " + _mm_text(band.band_width_mm) + " band centred on the column (beta "
            + _n(band.beta, 2) + ")"
        )
        result.add_bar(
            role="mesh_" + short_axis + "_bottom_band",
            count=bar_count(band.band_width_mm, 0.0, band.spacing_band_mm),
            dia_mm=banded.dia_mm,
            ld_mm=banded.ld_mm,
            zone_mm=[cover_mm, short_dim - cover_mm],
            layer=2,
            spacing_mm=band.spacing_band_mm,
            direction=short_axis,
            face="bottom",
            strip="central band",
        )
        strip_mm = 0.5 * (long_dim - band.band_width_mm)
        per_strip = max(1, int(math.floor(max(strip_mm - cover_mm, 0.0) / band.spacing_outer_mm + _EPS)))
        result.add_bar(
            role="mesh_" + short_axis + "_bottom_outer",
            count=2 * per_strip,
            dia_mm=banded.dia_mm,
            ld_mm=banded.ld_mm,
            zone_mm=[cover_mm, short_dim - cover_mm],
            layer=2,
            spacing_mm=band.spacing_outer_mm,
            direction=short_axis,
            face="bottom",
            strip="outer bands, " + _mm_text(strip_mm) + " each",
        )
        if band.note:
            result.add_warning(band.note)

    arms = {"x": ev.arm_x_mm, "y": ev.arm_y_mm}
    for axis in ("x", "y"):
        steel = steels[axis]
        straight = arms[axis] - cover_mm
        required, _available, bend, relaxed = _anchorage(
            steel.ld_mm, steel.ast_flexure_mm2_m, steel.ast_prov_mm2_m, straight, steel.dia_mm
        )
        if bend:
            result.add_note(
                "mesh " + axis + ": the straight run past the bending section is " + _mm_text(max(straight, 0.0))
                + " against Ld " + _mm_text(steel.ld_mm) + ", so the bars end in a standard 90 degree bend"
            )
        if relaxed:
            result.add_note(
                "mesh " + axis + ": development length taken at the stress the bar carries, "
                "Ld x Ast_flexure/Ast_provided = " + _mm_text(required)
            )
        if steel.note:
            result.add_warning("mesh " + axis + ": " + steel.note)

    dowel = ev.dowel
    result.add_bar(
        role="dowel",
        count=dowel.count,
        dia_mm=dowel.dia_mm,
        ld_mm=dowel.ld_mm,
        zone_mm=[0.0, max(dowel.available_mm, 0.0) + dowel.ld_mm],
        layer=1,
        direction="vertical",
        face="column",
        note="embedded " + _mm_text(max(dowel.available_mm, 0.0)) + " plus a compression lap of "
        + _mm_text(dowel.ld_mm) + " above the footing",
    )
    if dowel.excess_n > 0.0:
        result.add_note(
            "bearing at the column face is " + _n(dowel.bearing_demand_mpa, 2) + " MPa against "
            + _n(dowel.bearing_capacity_mpa, 2) + " MPa permissible (frustum ratio " + _n(dowel.frustum_ratio, 2)
            + "); the dowels carry the " + _n(dowel.excess_n / 1000.0, 1) + " kN excess at 0.67 fy"
        )
    if dowel.note:
        result.add_warning(dowel.note)
    if ev.d_mm <= 0.0:
        result.add_warning("the cover and bar stack leaves no effective depth at " + _mm_text(ev.overall_d_mm))


def _deepest(demands: Sequence[DepthDemand]) -> str:
    """The name of the criterion that asked for the most depth, for the record."""
    best = ""
    depth = -1.0
    for demand in demands:
        if demand.d_req_mm is not None and demand.d_req_mm > depth:
            best, depth = demand.name, demand.d_req_mm
    return best or "the minimum edge thickness"


def _worse(candidate: DepthDemand, incumbent: DepthDemand) -> bool:
    """True when `candidate` asks for the deeper section (None asks for more than any depth)."""
    if candidate.d_req_mm is None:
        return True
    if incumbent.d_req_mm is None:
        return False
    return candidate.d_req_mm > incumbent.d_req_mm


def _governing_name(evaluation: Any) -> str:
    """The depth-driving check with the highest utilization; ties keep list order."""
    if evaluation is None:
        return ""
    best_name = ""
    best_ratio = -1.0
    for name, ratio in evaluation.depth_ratios:
        if ratio > best_ratio + C.CHECK_TOL:
            best_name, best_ratio = name, ratio
    return best_name


def _settle(result: C.DesignResult, evaluation: Any) -> C.DesignResult:
    """Name the governing check and close the result.

    On a section that works, the check worth naming is the one that set the
    thickness. On a section that does not, it is the check that beat it: a
    failed row always takes the name, so a reader is never told a footing was
    governed by punching when what actually stopped it was the joint.
    """
    result.governing_check = _governing_name(evaluation)
    result.finalize()
    failed = [row for row in result.checks if row.status == C.CHECK_FAIL]
    if failed:
        result.governing_check = max(failed, key=lambda row: row.ratio).name
        result.status = C.STATUS_FAIL
    return result


# ---------------------------------------------------------------------------
# the N-support combined rectangle
# ---------------------------------------------------------------------------


class _Beam(NamedTuple):
    """The longitudinal beam-on-line: uniform upward load and N reactions."""

    w_n_per_mm: float
    length_mm: float
    stations_mm: Tuple[float, ...]
    loads_n: Tuple[float, ...]

    def shear_n(self, u_mm: float, side: str = "+") -> float:
        """Shear at u, taking the section just past (+) or just before (-) a load."""
        value = self.w_n_per_mm * float(u_mm)
        for station, load in zip(self.stations_mm, self.loads_n):
            if station < float(u_mm) - _EPS or (side == "+" and abs(station - float(u_mm)) <= _EPS):
                value -= load
        return value

    def moment_nmm(self, u_mm: float) -> float:
        """Bending moment at u: positive puts the bottom face in tension."""
        value = 0.5 * self.w_n_per_mm * float(u_mm) * float(u_mm)
        for station, load in zip(self.stations_mm, self.loads_n):
            if station < float(u_mm) - _EPS:
                value -= load * (float(u_mm) - station)
        return value

    def extremes(self) -> Tuple[float, float]:
        """(largest sagging-at-the-columns, largest hogging-between) as signed N.mm."""
        candidates = [0.0, self.length_mm]
        candidates.extend(self.stations_mm)
        running = 0.0
        for index, load in enumerate(self.loads_n):
            running += load
            if self.w_n_per_mm > 0.0:
                zero = running / self.w_n_per_mm
                upper = self.stations_mm[index + 1] if index + 1 < len(self.stations_mm) else self.length_mm
                if self.stations_mm[index] - _EPS <= zero <= upper + _EPS:
                    candidates.append(zero)
        values = [self.moment_nmm(u) for u in sorted(set(round(c, 6) for c in candidates))]
        return (max(values + [0.0]), min(values + [0.0]))


@dataclass(frozen=True)
class _Combined:
    """The settled combined rectangle in its own longitudinal (u) frame.

    `places` and `columns` run left to right along u, matching the beam's own
    station order, so an index means the same column everywhere.
    """

    longitudinal: str
    length_mm: float
    width_mm: float
    centre_u_mm: float
    centre_v_mm: float
    service_resultant_u_mm: float
    service_resultant_v_mm: float
    factored_resultant_u_mm: float
    factored_resultant_v_mm: float
    q_u_mpa: float
    q_service_kpa: float
    q_service_min_kpa: float
    q_service_average_kpa: float
    q_allow_kpa: float
    q_source: str
    service_contact_ratio: float
    service_kern_ratio: float
    beam: _Beam
    m_sag_nmm: float
    m_hog_nmm: float
    places: Tuple[Tuple[float, float, float, float], ...]
    pu_n: Tuple[float, ...]
    columns: Tuple[ColumnStub, ...]

    def local_u(self, index: int) -> float:
        """Column position measured from the left edge of the rectangle."""
        return self.places[index][0] - (self.centre_u_mm - 0.5 * self.length_mm)

    def offset_u(self, index: int) -> float:
        return self.places[index][0] - self.centre_u_mm

    def offset_v(self, index: int) -> float:
        return self.places[index][1] - self.centre_v_mm

    def band_width_mm(self, index: int, d_mm: float) -> float:
        """Symmetric transverse column band clipped at both footing ends."""
        local_u = self.local_u(index)
        return max(
            min(
                self.places[index][2] + 2.0 * float(d_mm),
                2.0 * local_u,
                2.0 * (self.length_mm - local_u),
                self.length_mm,
            ),
            0.0,
        )

    def band_arm_mm(self, index: int) -> float:
        """Longer cantilever from that column face to a transverse edge.

        A column on the transverse centreline has two equal arms.  A skew
        support does not: its far-edge arm grows by the absolute offset from
        the footing centreline, and that longer strip governs the band.
        """
        return max(
            0.5 * (self.width_mm - self.places[index][3]) + abs(self.offset_v(index)),
            0.0,
        )


class _CombinedEval(NamedTuple):
    """One trial thickness of the combined rectangle, fully checked."""

    d_mm: float
    overall_d_mm: float
    dia_mm: int
    steel_bottom: MeshSteel
    steel_top: MeshSteel
    steel_transverse_minimum: MeshSteel
    bands: Tuple[Tuple[int, float, float, MeshSteel], ...]
    dowel_list: Tuple[Dowels, ...]
    dowel_depth_mm: float
    rows: Tuple[Tuple[Any, ...], ...]
    depth_ratios: Tuple[Tuple[str, float], ...]
    ok: bool
    reason: str


def _combined_punching(combined: _Combined, index: int, d_mm: float, ctx: FootingContext) -> Tuple[float, float, Critical]:
    """(tau_v, capacity, critical section) for one column of a combined footing."""
    crit = punching_critical(
        combined.places[index][2],
        combined.places[index][3],
        combined.offset_u(index),
        combined.offset_v(index),
        combined.length_mm,
        combined.width_mm,
        d_mm,
    )
    column = combined.columns[index]
    if crit.perimeter_mm <= 0.0 or d_mm <= 0.0:
        return (0.0, is456.cl_31_6_3__punching(0.0, float(ctx.fck_mpa), column.beta_c).capacity_mpa, crit)
    shear = max(combined.pu_n[index] - combined.q_u_mpa * crit.area_mm2, 0.0)
    tau_v = shear / (crit.perimeter_mm * d_mm)
    return (tau_v, is456.cl_31_6_3__punching(tau_v, float(ctx.fck_mpa), column.beta_c).capacity_mpa, crit)


def _combined_steel(
    combined: _Combined, d_mm: float, overall_d_mm: float, ctx: FootingContext
) -> Tuple[MeshSteel, MeshSteel, MeshSteel, Tuple[Tuple[int, float, float, MeshSteel], ...]]:
    """Longitudinal mats, a full transverse minimum mat and column bands.

    The longitudinal steel is designed as a 1 m strip of the full width: Annex G
    is linear in b, so a strip and the whole width give the same answer, and the
    spacing that comes back is the one the detailer marks across the width.
    """
    width = combined.width_mm
    bottom = mesh_steel(1000.0 * combined.m_sag_nmm / width, d_mm, overall_d_mm, ctx)
    top = mesh_steel(1000.0 * abs(combined.m_hog_nmm) / width, d_mm, overall_d_mm, ctx)
    transverse_minimum = mesh_steel(0.0, d_mm, overall_d_mm, ctx)
    bands = []  # type: List[Tuple[int, float, float, MeshSteel]]
    for index in range(len(combined.columns)):
        band_width = combined.band_width_mm(index, d_mm)
        arm = combined.band_arm_mm(index)
        q_band = combined.pu_n[index] / (width * band_width) if width * band_width > 0.0 else 0.0
        mu_per_m = 1000.0 * q_band * arm * arm / 2.0
        cap = anchorage_dia_cap_mm(
            arm - is456.cl_26_4_2_2__footing_cover(), ctx, _stress_ratio(mu_per_m, d_mm, overall_d_mm, ctx)
        )
        bands.append((index, band_width, arm, mesh_steel(mu_per_m, d_mm, overall_d_mm, ctx, max_dia_mm=cap)))
    return (bottom, top, transverse_minimum, tuple(bands))


def _combined_long_shear_at(
    combined: _Combined, d_mm: float, ctx: FootingContext, bottom_ast: float, top_ast: float
) -> Tuple[float, float]:
    """Worst longitudinal shear at d from a column face: (tau_v, tau_c).

    The tension face changes along the beam: a section between the columns hangs
    off the top steel, one in an overhang off the bottom steel, so tau_c is read
    at the steel that is actually in tension there.
    """
    count = len(combined.columns)
    if d_mm <= 0.0 or count == 0:
        return (0.0, 1.0)
    stations = []  # type: List[Tuple[float, bool]]
    # Overhangs: the section sits d inside from the column face, if there is room.
    first_face = combined.local_u(0) - 0.5 * combined.places[0][2]
    if first_face - d_mm >= -_EPS:
        stations.append((first_face - d_mm, False))
    last_face = combined.local_u(count - 1) + 0.5 * combined.places[count - 1][2]
    if last_face + d_mm <= combined.length_mm + _EPS:
        stations.append((last_face + d_mm, False))
    # Between two columns a shear crack needs room to run: sections closer than d
    # to either face shed their load straight into it, so the window is the clear
    # span inset by d at both ends, and a clear span under 2d has no window left.
    for index in range(count - 1):
        left = combined.local_u(index) + 0.5 * combined.places[index][2]
        right = combined.local_u(index + 1) - 0.5 * combined.places[index + 1][2]
        if left + d_mm <= right - d_mm + _EPS:
            stations.append((left + d_mm, True))
            stations.append((right - d_mm, True))

    worst = (0.0, 1.0)
    margin = -1e30
    for station, between in stations:
        shear = abs(combined.beam.shear_n(station))
        tau_v = is456.cl_40_1__tau_v(shear, combined.width_mm, d_mm)
        pt = 100.0 * (top_ast if between else bottom_ast) / (1000.0 * d_mm)
        tau_c = is456.table_19__tau_c(pt, float(ctx.fck_mpa))
        if tau_v - tau_c > margin:
            margin = tau_v - tau_c
            worst = (tau_v, tau_c)
    return worst


def _combined_depth_demands(combined: _Combined, ctx: FootingContext, cover_mm: float) -> List[DepthDemand]:
    """What each criterion asks of the effective depth of the combined rectangle."""
    seed_dia = int(sorted(ctx.bar_dias_mm)[0])
    demands = []  # type: List[DepthDemand]

    for index in range(len(combined.columns)):
        def punch_residual(d_mm, index=index):
            tau_v, capacity, _crit = _combined_punching(combined, index, d_mm, ctx)
            return tau_v - capacity

        with _quiet():
            d_req = _bisect_min_d(punch_residual)
        demands.append(
            DepthDemand(
                name="two-way shear",
                clause="IS 456 Cl 31.6.3",
                d_req_mm=d_req,
                detail="punching around " + (combined.columns[index].column_id or ("column " + str(index + 1))),
            )
        )

    def long_shear_residual(d_mm):
        overall = _overall_from_effective(d_mm, cover_mm, seed_dia)
        width = combined.width_mm
        bottom_ast = _ast_required(1000.0 * combined.m_sag_nmm / width, d_mm, overall, ctx)[0]
        top_ast = _ast_required(1000.0 * abs(combined.m_hog_nmm) / width, d_mm, overall, ctx)[0]
        tau_v, tau_c = _combined_long_shear_at(combined, d_mm, ctx, bottom_ast, top_ast)
        return tau_v - tau_c

    with _quiet():
        d_shear = _bisect_min_d(long_shear_residual)
    demands.append(
        DepthDemand(
            name="longitudinal shear",
            clause="IS 456 Cl 40.1, Table 19",
            d_req_mm=d_shear,
            detail="beam shear at d from a column face along the footing",
        )
    )

    mu_long_per_m = 1000.0 * max(combined.m_sag_nmm, abs(combined.m_hog_nmm)) / combined.width_mm

    def long_flexure_residual(d_mm):
        return mu_long_per_m - is456.annex_g__mu_lim(1000.0, d_mm, float(ctx.fck_mpa), float(ctx.fy_mpa))

    with _quiet():
        d_flex = _bisect_min_d(long_flexure_residual)
    demands.append(
        DepthDemand(
            name="longitudinal flexure",
            clause="IS 456 G-1.1(b)",
            d_req_mm=d_flex,
            detail="sagging " + _n(combined.m_sag_nmm / 1e6, 1) + " kNm, hogging "
            + _n(combined.m_hog_nmm / 1e6, 1) + " kNm over the full width",
        )
    )

    for index in range(len(combined.columns)):
        def band_residual(d_mm, index=index):
            overall = _overall_from_effective(d_mm, cover_mm, seed_dia)
            band_width = combined.band_width_mm(index, d_mm)
            arm = combined.band_arm_mm(index)
            q_band = combined.pu_n[index] / (combined.width_mm * band_width)
            mu_per_m = 1000.0 * q_band * arm * arm / 2.0
            flexure = mu_per_m - is456.annex_g__mu_lim(1000.0, d_mm, float(ctx.fck_mpa), float(ctx.fy_mpa))
            tau_v = q_band * max(arm - d_mm, 0.0) / d_mm if d_mm > 0.0 else 0.0
            ast_req, _flex, _minimum = _ast_required(mu_per_m, d_mm, overall, ctx)
            pt = 100.0 * ast_req / (1000.0 * d_mm)
            shear = tau_v - is456.table_19__tau_c(pt, float(ctx.fck_mpa))
            return max(flexure / 1e6, shear)

        with _quiet():
            d_band = _bisect_min_d(band_residual)
        demands.append(
            DepthDemand(
                name="transverse band",
                clause="IS 456 Cl 34.2.3.2, Cl 40.1",
                d_req_mm=d_band,
                detail="cantilever strip under "
                + (combined.columns[index].column_id or ("column " + str(index + 1))),
            )
        )
    return demands


def design_combined_footing(
    footing: CombinedGeometry,
    loads: Sequence[FootingLoads],
    soil: Any = None,
    ctx: Any = None,
) -> C.DesignResult:
    """Design one combined rectangle carrying two or more columns. Never raises.

    The rectangle is centred on the factored resultant, which makes its design
    pressure uniform; the service resultant is retained as a biaxial pressure
    field for the SBC and contact checks.  The length follows from the outer
    support faces plus a projection and the width from the area the allowable
    pressure asks for. The longitudinal direction is then a beam on a
    uniform upward line load carrying every point reaction: its moment diagram
    hogs between the columns (top steel) and sags at them (bottom steel), and
    its shear is checked at d from each column face. Punching is checked per
    column on a perimeter clipped to the rectangle.  The transverse strip under
    each column is designed as a cantilever spanning out to the edges, and the
    full length also carries the Cl 34.5.1 minimum mat.
    """
    result = C.DesignResult(
        element_id=str(getattr(footing, "element_id", "") or "combined_footing"),
        element_type="footing",
    )
    entries = []  # type: List[TraceEntry]
    try:
        with trace_into(entries):
            context = FootingContext.coerce(ctx)
            profile = SoilProfile.from_params(soil)
            result.materials = C.materials_block(context.concrete, context.steel)
            _combined_body(result, footing, list(loads), profile, context)
    except Exception as error:  # noqa: BLE001 - disclose, never hide
        result.add_warning("combined footing design stopped on an internal error: " + repr(error))
        result.fail_with("internal error")
    result.trace = entries
    return result


def _combined_body(
    result: C.DesignResult,
    geom: CombinedGeometry,
    loads: List[FootingLoads],
    soil: SoilProfile,
    ctx: FootingContext,
) -> C.DesignResult:
    """The combined walk: resultant, rectangle, beam line, punching, bands."""
    columns = list(geom.columns)
    result.section["kind"] = "combined"
    if len(columns) < 2 or len(columns) != len(loads):
        return result.fail_with(
            "combined footing inputs",
            "a combined footing needs at least two columns and one load set per column; got "
            + str(len(columns)) + " columns and " + str(len(loads)) + " load sets",
            clause="IS 456 Cl 34",
            demand=float(max(2, len(columns), len(loads))),
            capacity=float(len(columns)) if len(columns) == len(loads) and len(columns) >= 2 else 0.0,
            units="columns",
        )
    if min(float(item.p_service_kn) for item in loads) <= 0.0:
        return result.fail_with(
            "service load",
            "every column on a combined footing needs a positive service load",
            clause="IS 6403",
            demand=1.0,
            capacity=0.0,
            units="kN",
        )
    if min(item.factored_p_kn(ctx.load_factor) for item in loads) <= 0.0:
        return result.fail_with(
            "factored load",
            "every column on a combined footing needs a positive factored load",
            clause="IS 456 Table 18",
            demand=1.0,
            capacity=0.0,
            units="kN",
        )

    grade = C.check_exposure_grade(float(ctx.fck_mpa), ctx.exposure)
    if grade:
        result.add_warning(grade)
    seed_dia = int(sorted(ctx.bar_dias_mm)[0])
    cover = C.resolve_cover("footing", ctx.exposure, ctx.fire_rating_h, seed_dia)
    result.add_note(cover.note)

    xs = [C.m_to_mm(column.x_m) for column in columns]
    ys = [C.m_to_mm(column.y_m) for column in columns]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    longitudinal = "x" if span_x >= span_y else "y"
    result.add_note(
        "longitudinal axis taken along " + longitudinal + ", the larger envelope of all "
        + str(len(columns)) + " supports"
    )
    if min(span_x, span_y) > _EPS:
        result.add_warning(
            "the columns are offset on both axes across " + _mm_text(span_x) + " and " + _mm_text(span_y)
            + "; the larger envelope is longitudinal and every transverse offset is retained in the rectangle, "
            "punching and dowel checks"
        )

    def local(column: ColumnStub) -> Tuple[float, float, float, float]:
        """(u position, v position, column dim along u, column dim along v), mm."""
        if longitudinal == "x":
            return (C.m_to_mm(column.x_m), C.m_to_mm(column.y_m), float(column.bx_mm), float(column.dy_mm))
        return (C.m_to_mm(column.y_m), C.m_to_mm(column.x_m), float(column.dy_mm), float(column.bx_mm))

    places = [local(column) for column in columns]
    p_service = [float(item.p_service_kn) for item in loads]
    pu_kn = [item.factored_p_kn(ctx.load_factor) for item in loads]
    p_total = sum(p_service)
    pu_total = sum(pu_kn)
    service_resultant_u = sum(place[0] * load for place, load in zip(places, p_service)) / p_total
    service_resultant_v = sum(place[1] * load for place, load in zip(places, p_service)) / p_total
    factored_resultant_u = sum(place[0] * load for place, load in zip(places, pu_kn)) / pu_total
    factored_resultant_v = sum(place[1] * load for place, load in zip(places, pu_kn)) / pu_total
    centre_u = factored_resultant_u
    centre_v = factored_resultant_v

    half_length = max(
        abs(place[0] - centre_u) + 0.5 * place[2] + MIN_PROJECTION_MM
        for place in places
    )
    half_width = max(
        abs(place[1] - centre_v) + 0.5 * place[3] + MIN_PROJECTION_MM
        for place in places
    )
    step = float(ctx.policy.footing_plan_step_mm)
    length_floor = 2.0 * half_length
    width_floor = 2.0 * half_width
    length = C.round_up_mm(length_floor, step)
    width = C.round_up_mm(width_floor, step)

    service_ex_u = service_resultant_u - centre_u
    service_ex_v = service_resultant_v - centre_v

    p_eff_n = C.kn_to_n(p_total) * (1.0 + float(ctx.self_weight_allowance))
    with _quiet():
        for _iteration in range(int(ctx.policy.max_iters)):
            allow = allowable_pressure(soil, width, length)
            gradient = (
                1.0
                + 6.0 * abs(service_ex_u) / length
                + 6.0 * abs(service_ex_v) / width
            )
            area_needed = p_eff_n * gradient / (max(allow.q_allow_kpa, _EPS) / 1000.0)
            next_length = length
            next_width = C.round_up_mm(max(area_needed / length, width_floor, width), step)
            kern_ratio = (
                6.0 * abs(service_ex_u) / next_length
                + 6.0 * abs(service_ex_v) / next_width
            )
            if kern_ratio > 1.0 + _EPS:
                next_length = C.round_up_mm(max(next_length * kern_ratio, length_floor), step)
                next_width = C.round_up_mm(max(next_width * kern_ratio, width_floor), step)
            if abs(next_length - length) < _EPS and abs(next_width - width) < _EPS:
                break
            length, width = next_length, next_width
    allow = allowable_pressure(soil, width, length)
    for note in allow.notes:
        result.add_note(note)

    service_pressure = _contact_pressure(
        length,
        width,
        C.kn_to_n(p_total),
        service_ex_u,
        service_ex_v,
    )
    q_service_average_kpa = 1000.0 * C.kn_to_n(p_total) / (width * length)
    q_service_kpa = 1000.0 * service_pressure.q_max_mpa
    q_service_min_kpa = 1000.0 * service_pressure.q_min_mpa
    q_u_mpa = C.kn_to_n(pu_total) / (width * length)
    service_kern_ratio = 6.0 * abs(service_ex_u) / length + 6.0 * abs(service_ex_v) / width
    result.add_note(
        "rectangle " + _mm_text(length) + " x " + _mm_text(width)
        + " centred on the factored load resultant; service pressure ranges "
        + _n(q_service_min_kpa, 1) + " to " + _n(q_service_kpa, 1) + " kPa"
    )
    if service_pressure.contact_ratio < 1.0 - 1e-9:
        result.add_warning(
            "the service resultant remains outside the biaxial kern after the bounded plan-sizing walk; "
            + _n(100.0 * service_pressure.contact_ratio, 1)
            + " percent of the base is in compression and the no-tension pressure field is used"
        )
    if geom.placed_bx_m is not None and geom.placed_ly_m is not None:
        placed_u = C.m_to_mm(geom.placed_bx_m if longitudinal == "x" else geom.placed_ly_m)
        placed_v = C.m_to_mm(geom.placed_ly_m if longitudinal == "x" else geom.placed_bx_m)
        if abs(placed_u - length) > _EPS or abs(placed_v - width) > _EPS:
            result.add_resize(
                _mm_text(placed_u) + " x " + _mm_text(placed_v),
                _mm_text(length) + " x " + _mm_text(width),
                "rectangle re-sized onto the factored resultant at the allowable service pressure",
            )

    order = sorted(range(len(columns)), key=lambda index: (places[index][0], columns[index].column_id))
    left_edge = centre_u - 0.5 * length
    beam = _Beam(
        w_n_per_mm=C.kn_to_n(pu_total) / length,
        length_mm=length,
        stations_mm=tuple(places[index][0] - left_edge for index in order),
        loads_n=tuple(C.kn_to_n(pu_kn[index]) for index in order),
    )
    m_sag, m_hog = beam.extremes()
    combined = _Combined(
        longitudinal=longitudinal,
        length_mm=length,
        width_mm=width,
        centre_u_mm=centre_u,
        centre_v_mm=centre_v,
        service_resultant_u_mm=service_resultant_u,
        service_resultant_v_mm=service_resultant_v,
        factored_resultant_u_mm=factored_resultant_u,
        factored_resultant_v_mm=factored_resultant_v,
        q_u_mpa=q_u_mpa,
        q_service_kpa=q_service_kpa,
        q_service_min_kpa=q_service_min_kpa,
        q_service_average_kpa=q_service_average_kpa,
        q_allow_kpa=allow.q_allow_kpa,
        q_source=allow.source,
        service_contact_ratio=service_pressure.contact_ratio,
        service_kern_ratio=service_kern_ratio,
        beam=beam,
        m_sag_nmm=m_sag,
        m_hog_nmm=m_hog,
        places=tuple(places[index] for index in order),
        pu_n=tuple(C.kn_to_n(pu_kn[index]) for index in order),
        columns=tuple(columns[index] for index in order),
    )

    demands = _combined_depth_demands(combined, ctx, cover.cover_mm)
    refused = [demand for demand in demands if demand.d_req_mm is None]
    d_req = max([demand.d_req_mm for demand in demands if demand.d_req_mm is not None] or [_D_SEARCH_MIN_MM])
    depth_step = float(ctx.policy.footing_depth_step_mm)
    overall = max(
        is456.cl_34_1_2__min_edge_thickness(),
        C.round_up_mm(d_req + cover.cover_mm + 1.5 * seed_dia, depth_step),
        0.0 if geom.specified_thickness_m is None else C.m_to_mm(geom.specified_thickness_m),
    )
    if geom.specified_thickness_m is not None and abs(C.m_to_mm(geom.specified_thickness_m) - overall) > _EPS:
        result.add_resize(
            _mm_text(C.m_to_mm(geom.specified_thickness_m)), _mm_text(overall), "depth set by " + _deepest(demands)
        )

    evaluation = None  # type: Optional[_CombinedEval]
    for _attempt in range(int(ctx.policy.max_iters)):
        with _quiet():
            evaluation = _combined_evaluate(combined, ctx, overall, cover.cover_mm)
        if evaluation.ok:
            break
        bumped = overall + depth_step
        if evaluation.reason == "dowel anchorage":
            bumped = max(bumped, C.round_up_mm(evaluation.dowel_depth_mm, depth_step))
        result.add_resize(_mm_text(overall), _mm_text(bumped), "depth increased for " + evaluation.reason)
        overall = bumped
    evaluation = _combined_evaluate(combined, ctx, overall, cover.cover_mm)

    _emit_combined(result, combined, ctx, cover.cover_mm, evaluation)
    for demand in refused:
        result.add_warning(
            demand.name + " (" + demand.clause + ") cannot be satisfied at any depth up to "
            + _mm_text(_D_SEARCH_MAX_MM) + ": " + demand.detail
        )
    _settle(result, evaluation)
    if refused:
        result.governing_check = refused[0].name
        result.status = C.STATUS_FAIL
    return result


def _column_label(combined: _Combined, index: int) -> str:
    return combined.columns[index].column_id or ("column " + str(index + 1))


def _local_stub(combined: _Combined, index: int) -> ColumnStub:
    """The column restated in the longitudinal frame, so u pairs with u."""
    column = combined.columns[index]
    return ColumnStub(
        column_id=column.column_id,
        bx_mm=combined.places[index][2],
        dy_mm=combined.places[index][3],
    )


def _combined_evaluate(
    combined: _Combined, ctx: FootingContext, overall_d_mm: float, cover_mm: float
) -> _CombinedEval:
    """Every check on one trial thickness of the combined rectangle."""
    fck = float(ctx.fck_mpa)
    fy = float(ctx.fy_mpa)
    dia = int(sorted(ctx.bar_dias_mm)[0])
    d_mm = float(overall_d_mm) - float(cover_mm) - 1.5 * dia
    bottom = top = transverse_minimum = None  # type: Optional[MeshSteel]
    bands = ()  # type: Tuple[Tuple[int, float, float, MeshSteel], ...]
    for _pass in range(4):
        d_mm = float(overall_d_mm) - float(cover_mm) - 1.5 * dia
        if d_mm <= 0.0:
            break
        bottom, top, transverse_minimum, bands = _combined_steel(combined, d_mm, float(overall_d_mm), ctx)
        wanted = max(
            [bottom.dia_mm, top.dia_mm, transverse_minimum.dia_mm]
            + [band[3].dia_mm for band in bands]
        )
        if wanted == dia:
            break
        dia = wanted
    d_mm = max(d_mm, 1.0)
    if bottom is None or top is None or transverse_minimum is None:
        bottom, top, transverse_minimum, bands = _combined_steel(
            combined, d_mm, float(overall_d_mm), ctx
        )

    rows = []  # type: List[Tuple[Any, ...]]
    ratios = []  # type: List[Tuple[str, float]]
    driven = set()  # type: set

    def add(name, clause, demand, capacity, units, structural=False, fixable=False):
        rows.append((name, clause, demand, capacity, units))
        if structural:
            ratios.append((name, demand / capacity if capacity > 0.0 else C.RATIO_CAP))
        if structural or fixable:
            driven.add(name)

    add("bearing pressure", combined.q_source, combined.q_service_kpa, combined.q_allow_kpa, "kPa")
    add(
        "service biaxial kern",
        "IS 456 Cl 34.1, full base contact",
        combined.service_kern_ratio,
        1.0,
        "ratio",
    )
    add(
        "longitudinal equilibrium",
        "factored pressure and column loads close at the free edge",
        abs(combined.beam.moment_nmm(combined.length_mm)),
        max(1.0, sum(combined.pu_n) * combined.length_mm * 1e-9),
        "N.mm",
    )

    for index in range(len(combined.columns)):
        tau_v, capacity, _crit = _combined_punching(combined, index, d_mm, ctx)
        add("two-way shear " + _column_label(combined, index), "IS 456 Cl 31.6.3", tau_v, capacity, "MPa", structural=True)

    tau_v, tau_c = _combined_long_shear_at(combined, d_mm, ctx, bottom.ast_prov_mm2_m, top.ast_prov_mm2_m)
    add("longitudinal shear", "IS 456 Cl 40.1, Table 19", tau_v, tau_c, "MPa", structural=True)

    mu_lim_per_m = is456.annex_g__mu_lim(1000.0, d_mm, fck, fy)
    add(
        "longitudinal flexure sagging",
        "IS 456 G-1.1(b)",
        1000.0 * combined.m_sag_nmm / combined.width_mm,
        mu_lim_per_m,
        "N.mm per m",
        structural=True,
    )
    add(
        "longitudinal flexure hogging",
        "IS 456 G-1.1(b)",
        1000.0 * abs(combined.m_hog_nmm) / combined.width_mm,
        mu_lim_per_m,
        "N.mm per m",
        structural=True,
    )
    for name, steel in (("bottom", bottom), ("top", top)):
        add("steel " + name, "IS 456 Cl 26.5.2.1", steel.ast_req_mm2_m, steel.ast_prov_mm2_m, "mm2 per m")
        add("bar spacing " + name, "IS 456 Cl 26.3.3", steel.spacing_mm, steel.max_spacing_mm, "mm")

    add(
        "steel transverse minimum",
        "IS 456 Cl 34.5.1, Cl 26.5.2.1",
        transverse_minimum.ast_req_mm2_m,
        transverse_minimum.ast_prov_mm2_m,
        "mm2 per m",
    )
    add(
        "bar spacing transverse minimum",
        "IS 456 Cl 34.5.1, Cl 26.3.3",
        transverse_minimum.spacing_mm,
        transverse_minimum.max_spacing_mm,
        "mm",
    )

    for index, band_width, arm, steel in bands:
        label = _column_label(combined, index)
        q_band = combined.pu_n[index] / (combined.width_mm * band_width) if band_width > 0.0 else 0.0
        add(
            "transverse band " + label,
            "IS 456 Cl 34.2.3.2, G-1.1(b)",
            1000.0 * q_band * arm * arm / 2.0,
            mu_lim_per_m,
            "N.mm per m",
            structural=True,
        )
        pt = 100.0 * steel.ast_prov_mm2_m / (1000.0 * d_mm)
        add(
            "transverse shear " + label,
            "IS 456 Cl 40.1, Table 19",
            q_band * max(arm - d_mm, 0.0) / d_mm,
            is456.table_19__tau_c(pt, fck),
            "MPa",
            structural=True,
        )
        add("steel band " + label, "IS 456 Cl 26.5.2.1", steel.ast_req_mm2_m, steel.ast_prov_mm2_m, "mm2 per m")

    add("edge thickness", "IS 456 Cl 34.1.2", is456.cl_34_1_2__min_edge_thickness(), float(overall_d_mm), "mm")

    dowel_list = []  # type: List[Dowels]
    dowel_depth = 0.0
    for index in range(len(combined.columns)):
        stub = _local_stub(combined, index)
        spec = dowels(
            combined.pu_n[index],
            stub,
            combined.length_mm,
            combined.width_mm,
            combined.offset_u(index),
            combined.offset_v(index),
            float(overall_d_mm),
            float(cover_mm),
            dia,
            ctx,
        )
        dowel_list.append(spec)
        dowel_depth = max(dowel_depth, spec.d_needed_mm)
        label = _column_label(combined, index)
        limits = is456.cl_26_5_3_1__long_steel_limits(stub.area_mm2)
        add(
            "bearing at column face " + label,
            "IS 456 Cl 34.4",
            combined.pu_n[index],
            spec.bearing_capacity_mpa * stub.area_mm2 + DOWEL_STRESS_FACTOR * fy * spec.area_prov_mm2,
            "N",
        )
        add("dowel steel " + label, "IS 456 Cl 34.4.3", spec.area_req_mm2, spec.area_prov_mm2, "mm2")
        add("dowel steel ratio " + label, "IS 456 Cl 26.5.3.1", spec.area_prov_mm2, limits.asc_max_mm2, "mm2")
        add("dowel anchorage " + label, "IS 456 Cl 26.2.1", spec.ld_mm, spec.available_mm, "mm", fixable=True)

    reason = ""
    for row in rows:
        if row[0] not in driven:
            continue
        if row[3] <= 0.0 or row[2] > row[3] * (1.0 + C.CHECK_TOL):
            reason = "dowel anchorage" if str(row[0]).startswith("dowel anchorage") else str(row[0])
            break
    return _CombinedEval(
        d_mm=d_mm,
        overall_d_mm=float(overall_d_mm),
        dia_mm=int(dia),
        steel_bottom=bottom,
        steel_top=top,
        steel_transverse_minimum=transverse_minimum,
        bands=bands,
        dowel_list=tuple(dowel_list),
        dowel_depth_mm=dowel_depth,
        rows=tuple(rows),
        depth_ratios=tuple(ratios),
        ok=not reason,
        reason=reason,
    )


def _emit_combined(
    result: C.DesignResult,
    combined: _Combined,
    ctx: FootingContext,
    cover_mm: float,
    ev: _CombinedEval,
) -> None:
    """Write the settled combined footing into the result."""
    if combined.longitudinal == "x":
        bx_mm, ly_mm = combined.length_mm, combined.width_mm
    else:
        bx_mm, ly_mm = combined.width_mm, combined.length_mm
    result.section.update(
        {
            "bx_mm": bx_mm,
            "ly_mm": ly_mm,
            "length_mm": combined.length_mm,
            "width_mm": combined.width_mm,
            "longitudinal_axis": combined.longitudinal,
            "D_mm": ev.overall_d_mm,
            "d_mm": ev.d_mm,
            "cover_mm": float(cover_mm),
            "support_count": len(combined.columns),
            "q_allow_kpa": combined.q_allow_kpa,
            "q_service_kpa": combined.q_service_kpa,
            "q_service_min_kpa": combined.q_service_min_kpa,
            "q_service_average_kpa": combined.q_service_average_kpa,
            "service_contact_ratio": combined.service_contact_ratio,
            "service_kern_ratio": combined.service_kern_ratio,
            "service_resultant_u_mm": combined.service_resultant_u_mm,
            "service_resultant_v_mm": combined.service_resultant_v_mm,
            "factored_resultant_u_mm": combined.factored_resultant_u_mm,
            "factored_resultant_v_mm": combined.factored_resultant_v_mm,
            "beam_end_moment_knm": combined.beam.moment_nmm(combined.length_mm) / 1e6,
            "qu_mpa": combined.q_u_mpa,
            "m_sag_knm": combined.m_sag_nmm / 1e6,
            "m_hog_knm": combined.m_hog_nmm / 1e6,
        }
    )
    result.extras["si"] = {
        "bx_m": C.mm_to_m(bx_mm),
        "ly_m": C.mm_to_m(ly_mm),
        "depth_m": C.mm_to_m(ev.overall_d_mm),
    }
    result.extras["combined_line"] = {
        "station_u_mm": list(combined.beam.stations_mm),
        "factored_load_kn": [load / 1000.0 for load in combined.beam.loads_n],
    }
    for name, clause, demand, capacity, units in ev.rows:
        result.add_check(name, clause, demand, capacity, units=units)

    result.add_bar(
        role="long_bottom",
        count=bar_count(combined.width_mm, cover_mm, ev.steel_bottom.spacing_mm),
        dia_mm=ev.steel_bottom.dia_mm,
        ld_mm=ev.steel_bottom.ld_mm,
        zone_mm=[cover_mm, combined.length_mm - cover_mm],
        layer=1,
        spacing_mm=ev.steel_bottom.spacing_mm,
        direction=combined.longitudinal,
        face="bottom",
        strip="full width, sagging under the columns",
    )
    first = combined.local_u(0)
    last = combined.local_u(len(combined.columns) - 1)
    top_from = max(cover_mm, first - ev.steel_top.ld_mm)
    top_to = min(combined.length_mm - cover_mm, last + ev.steel_top.ld_mm)
    result.add_bar(
        role="long_top",
        count=bar_count(combined.width_mm, cover_mm, ev.steel_top.spacing_mm),
        dia_mm=ev.steel_top.dia_mm,
        ld_mm=ev.steel_top.ld_mm,
        zone_mm=[top_from, top_to],
        layer=1,
        spacing_mm=ev.steel_top.spacing_mm,
        direction=combined.longitudinal,
        face="top",
        strip="between the columns, hogging",
    )
    if abs(combined.m_hog_nmm) <= _EPS:
        result.add_note(
            "the moment diagram never hogs between the columns (the overhangs balance it), so the top mat "
            "is the nominal 0.12 percent minimum"
        )
    else:
        result.add_note(
            "hogging between the columns is " + _n(abs(combined.m_hog_nmm) / 1e6, 1)
            + " kNm; the top mat runs a development length past each column"
        )

    transverse = "y" if combined.longitudinal == "x" else "x"
    result.add_bar(
        role="transverse_minimum",
        count=bar_count(combined.length_mm, cover_mm, ev.steel_transverse_minimum.spacing_mm),
        dia_mm=ev.steel_transverse_minimum.dia_mm,
        ld_mm=ev.steel_transverse_minimum.ld_mm,
        zone_mm=[cover_mm, combined.width_mm - cover_mm],
        layer=2,
        spacing_mm=ev.steel_transverse_minimum.spacing_mm,
        direction=transverse,
        face="bottom",
        strip="full length minimum mat, including between the column bands",
    )
    for index, band_width, arm, steel in ev.bands:
        label = _column_label(combined, index)
        result.add_bar(
            role="band_transverse",
            count=bar_count(band_width, 0.0, steel.spacing_mm),
            dia_mm=steel.dia_mm,
            ld_mm=steel.ld_mm,
            zone_mm=[cover_mm, combined.width_mm - cover_mm],
            layer=2,
            spacing_mm=steel.spacing_mm,
            direction=transverse,
            face="bottom",
            strip="band " + _mm_text(band_width) + " under " + label + ", cantilever " + _mm_text(arm),
            column_id=label,
        )
        if steel.note:
            result.add_warning("band under " + label + ": " + steel.note)

    for index, spec in enumerate(ev.dowel_list):
        label = _column_label(combined, index)
        result.add_bar(
            role="dowel",
            count=spec.count,
            dia_mm=spec.dia_mm,
            ld_mm=spec.ld_mm,
            zone_mm=[0.0, max(spec.available_mm, 0.0) + spec.ld_mm],
            layer=1,
            direction="vertical",
            face="column",
            column_id=label,
        )
        if spec.note:
            result.add_warning("dowels under " + label + ": " + spec.note)
    for name, steel in (("bottom", ev.steel_bottom), ("top", ev.steel_top)):
        if steel.note:
            result.add_warning("longitudinal " + name + " steel: " + steel.note)
    if ev.steel_transverse_minimum.note:
        result.add_warning("transverse minimum steel: " + ev.steel_transverse_minimum.note)


def _strap_referral(
    result: C.DesignResult,
    geom: PadGeometry,
    loads: FootingLoads,
    ctx: FootingContext,
    p_service_kn: float,
    pu_kn: float,
) -> Tuple[float, float, float, float, float, float]:
    """Refer the strap beam out and return the reaction the pad is designed for.

    A strap turns an eccentric boundary column into a concentric pad: the beam
    carries the couple back to the interior footing, the base pressure comes out
    uniform, and the pad reaction rises to R1 = P e / (S - e) above P. v1 sizes
    the pad for that R1 and refers the BEAM out with the moment balance that
    produced it, rather than designing a member it has no section for.
    """
    e_m = math.hypot(float(geom.col_offset_x_m), float(geom.col_offset_y_m))
    span_m = float(geom.strap_span_m)
    detail = {
        "footing_id": str(geom.element_id),
        "partner_footing_id": str(geom.strap_partner_id),
        "column_id": str(geom.column.column_id or loads.column_id),
        "e_m": e_m,
        "strap_span_m": span_m,
        "p_service_kn": float(p_service_kn),
        "pu_kn": float(pu_kn),
    }  # type: Dict[str, Any]
    factor = 1.0
    if span_m > e_m + _EPS and e_m > _EPS:
        factor = span_m / (span_m - e_m)
        detail["r1_service_kn"] = p_service_kn * factor
        detail["partner_relief_kn"] = p_service_kn * e_m / (span_m - e_m)
        detail["strap_moment_knm"] = p_service_kn * e_m
        result.add_note(
            "strap action: pad reaction raised from " + _n(p_service_kn, 1) + " kN to "
            + _n(p_service_kn * factor, 1) + " kN by the moment balance P S / (S - e), and the base pressure "
            "taken uniform because the strap beam carries the couple"
        )
    else:
        detail["r1_service_kn"] = float(p_service_kn)
        result.add_warning(
            "strap geometry is unusable (span " + _n(span_m, 2) + " m against eccentricity " + _n(e_m, 2)
            + " m): the pad is designed for the load as handed over, with no strap relief"
        )
    result.add_referral("strap_required", detail)
    result.add_warning(
        "strap footing: the strap beam is NOT designed in this version; the pad alone is designed and the "
        "moment balance travels on the strap_required referral"
    )
    return (p_service_kn * factor, pu_kn * factor, 0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# the wall strip
# ---------------------------------------------------------------------------


class StripPlan(NamedTuple):
    """A settled strip width, the pressures on it and what drove it."""

    width_mm: float
    q_allow_kpa: float
    q_service_kpa: float
    projection_mm: float
    driver: str
    iterations: int
    notes: Tuple[str, ...]


def _strip_bearing_length_mm(width_mm: float, length_mm: float) -> Tuple[float, bool]:
    """(length to read the IS 6403 shape factors at, whether it was assumed).

    A strip is long and narrow and its shape factors are the strip ones. A caller
    that states no run length would otherwise be read as a square, so the
    fallback is `STRIP_LENGTH_FALLBACK_FACTOR` widths, and the caller is told.
    """
    stated = float(length_mm)
    if stated > float(width_mm) + _EPS:
        return (stated, False)
    return (STRIP_LENGTH_FALLBACK_FACTOR * float(width_mm), True)


def size_strip(
    n_service_kn_per_m: float,
    wall_t_mm: float,
    soil: SoilProfile,
    ctx: FootingContext,
    length_mm: float = 0.0,
    placed_width_mm: Optional[float] = None,
) -> StripPlan:
    """Strip width for one metre run of wall, on SERVICE load with the allowance.

    `B = n (1 + allowance) / q_allow`, floored by the wall plus
    `MIN_STRIP_PROJECTION_MM` each side and by the width the placer already laid,
    and rounded UP to the policy plan step. The bearing chain is width dependent,
    so the walk re-enters it as the strip grows; it only ever grows, so it
    terminates. A placed width that already covers the demand is kept EXACTLY, so
    a strip the placer sized on a 50 mm module is not re-rounded onto a 100 mm one
    and reported as a resize it never needed.
    """
    step = float(ctx.policy.footing_plan_step_mm)
    n_eff = float(n_service_kn_per_m) * (1.0 + float(ctx.self_weight_allowance))
    floor_mm = C.round_up_mm(float(wall_t_mm) + 2.0 * MIN_STRIP_PROJECTION_MM, step)
    placed = max(float(placed_width_mm or 0.0), 0.0)

    width = max(floor_mm, placed)
    need = 0.0
    iterations = 0
    assumed_length = False
    with _quiet():
        for iterations in range(1, int(ctx.policy.max_iters) + 1):
            span_mm, assumed_length = _strip_bearing_length_mm(width, length_mm)
            allow = allowable_pressure(soil, width, span_mm)
            need = C.round_up_mm(1000.0 * n_eff / max(float(allow.q_allow_kpa), _EPS), step)
            candidate = max(need, floor_mm, placed, width)
            if abs(candidate - width) < _EPS:
                break
            width = candidate
    span_mm, assumed_length = _strip_bearing_length_mm(width, length_mm)
    allow = allowable_pressure(soil, width, span_mm)

    if need >= width - _EPS and need >= floor_mm - _EPS and need >= placed - _EPS:
        driver = "bearing pressure"
    elif placed >= floor_mm - _EPS and placed >= need - _EPS:
        driver = "the placed width"
    else:
        driver = "minimum projection"

    notes = [allow.source]
    notes.extend(allow.notes)
    if assumed_length:
        notes.append(
            "no run length was stated, so the bearing chain was read at "
            + _n(STRIP_LENGTH_FALLBACK_FACTOR, 0)
            + " widths, which is the strip shape rather than a square"
        )
    return StripPlan(
        width_mm=width,
        q_allow_kpa=float(allow.q_allow_kpa),
        q_service_kpa=1000.0 * float(n_service_kn_per_m) / width if width > 0.0 else 0.0,
        projection_mm=max(0.5 * (width - float(wall_t_mm)), 0.0),
        driver=driver,
        iterations=iterations,
        notes=tuple(notes),
    )


def plain_spread_factor(q_kpa: float, fck_mpa: float) -> float:
    """IS 456 Cl 34.1.3: thickness a plain concrete spread needs per unit projection.

    The clause reads tan(alpha) >= 0.9 sqrt(100 q_a / f_ck + 1) with alpha the
    angle from the bottom edge of the plain section up to the loaded face, so
    tan(alpha) = D / a and the requirement is D >= a x 0.9 sqrt(...), with q_a in
    MPa. The returned factor is never below 1.0: a plain footing whose projection
    runs past its own thickness is the case that needs reinforcement, which is
    the rule this designer gates on, and the code expression only falls under 1.0
    at bearing pressures too low to relax it usefully.

    This lives here rather than in `codes/is456.py` because that module ships no
    Cl 34.1.3 callable; the check row cites the clause by number.
    """
    q_mpa = max(float(q_kpa), 0.0) / 1000.0
    grade = max(float(fck_mpa), _EPS)
    return max(1.0, 0.9 * math.sqrt(100.0 * q_mpa / grade + 1.0))


def _distribution_steel(overall_d_mm: float, d_mm: float, ctx: FootingContext) -> MeshSteel:
    """Nominal longitudinal steel for a strip: the 0.12 percent floor, Cl 26.3.3 secondary cap.

    A strip spans nothing along its run, so the longitudinal bars are
    distribution steel: the Cl 26.5.2.1 minimum on the gross section, spaced at
    the Cl 26.3.3 secondary cap (5d or 450) rather than the main cap.
    """
    fy = float(ctx.fy_mpa)
    ast_min = is456.cl_26_5_2_1__min_slab_steel(float(overall_d_mm), fy, 1000.0)
    max_spacing = is456.cl_26_3_3__max_spacing_flexure("distribution", float(d_mm), fy)
    dias = tuple(sorted(int(dia) for dia in ctx.bar_dias_mm))
    chosen = dias[-1]
    spacing = C.spacing_for_area(ast_min, chosen, max_spacing, 10.0)
    for dia in dias:
        trial = C.spacing_for_area(ast_min, dia, max_spacing, 10.0)
        if trial >= MIN_MESH_SPACING_MM - _EPS:
            chosen, spacing = dia, trial
            break
    return MeshSteel(
        ast_req_mm2_m=ast_min,
        ast_flexure_mm2_m=0.0,
        ast_min_mm2_m=ast_min,
        ast_prov_mm2_m=C.area_for_spacing(chosen, spacing),
        dia_mm=int(chosen),
        spacing_mm=spacing,
        max_spacing_mm=max_spacing,
        ld_mm=is456.cl_26_2_1__ld(chosen, fy, float(ctx.fck_mpa)),
        note="",
    )


class _StripEval(NamedTuple):
    """One trial thickness of a strip, fully checked."""

    verdict: str
    d_mm: float
    overall_d_mm: float
    dia_mm: int
    steel_main: Optional[MeshSteel]
    steel_dist: Optional[MeshSteel]
    arm_flex_mm: float
    arm_shear_mm: float
    mu_nmm_per_m: float
    qu_mpa: float
    rows: Tuple[Tuple[Any, ...], ...]
    depth_ratios: Tuple[Tuple[str, float], ...]
    ok: bool
    reason: str


def _strip_flexure_arm_mm(width_mm: float, wall_t_mm: float) -> float:
    """Cantilever arm to the Cl 34.2.3.2(b) bending section of a MASONRY wall strip.

    The critical section for bending under a masonry wall is halfway between the
    wall centreline and the wall face, not at the face: masonry spreads its load
    into the footing less completely than concrete does, so the code moves the
    section inboard and the arm out to the edge grows by a quarter of the wall
    thickness. `cl_34_2_3_2__bending_section` is the concrete-wall form of the
    same clause and is deliberately not reused here.
    """
    return max(0.5 * float(width_mm) - 0.25 * float(wall_t_mm), 0.0)


def _strip_face_arm_mm(width_mm: float, wall_t_mm: float) -> float:
    """Projection from the wall FACE to the edge: the Cl 34.2.4.1 shear arm."""
    return max(0.5 * (float(width_mm) - float(wall_t_mm)), 0.0)


def _required_d_strip_shear(
    qu_mpa: float, arm_mm: float, mu_nmm_per_m: float, ctx: FootingContext, cover_mm: float
) -> DepthDemand:
    """Effective depth the one-way shear at d from the wall face asks for.

    IS 456 Cl 34.2.4.1 puts the section at d from the face of the wall for a
    footing on soil, and tau_c is read at the steel the strip actually gets at
    the trial depth, so the check iterates against the provided pt.
    """
    seed_dia = int(sorted(ctx.bar_dias_mm)[0])

    def residual(d_mm: float) -> float:
        if d_mm <= 0.0:
            return 1.0
        shear = float(qu_mpa) * max(float(arm_mm) - d_mm, 0.0) * 1000.0
        if shear <= 0.0:
            return -1.0
        tau_v = is456.cl_40_1__tau_v(shear, 1000.0, d_mm)
        overall = d_mm + float(cover_mm) + 0.5 * seed_dia
        ast_req, _flex, _minimum = _ast_required(float(mu_nmm_per_m), d_mm, overall, ctx)
        pt = 100.0 * ast_req / (1000.0 * d_mm)
        return tau_v - is456.table_19__tau_c(pt, float(ctx.fck_mpa))

    with _quiet():
        d_req = _bisect_min_d(residual)
    return DepthDemand(
        name="one-way shear",
        clause="IS 456 Cl 34.2.4.1, Cl 40.1, Table 19",
        d_req_mm=d_req,
        detail="shear at d from the wall face on a 1 m strip",
    )


def _required_d_strip_flexure(mu_nmm_per_m: float, ctx: FootingContext) -> DepthDemand:
    """Effective depth that keeps the Cl 34.2.3.2(b) moment singly reinforced."""

    def residual(d_mm: float) -> float:
        return float(mu_nmm_per_m) - is456.annex_g__mu_lim(
            1000.0, d_mm, float(ctx.fck_mpa), float(ctx.fy_mpa)
        )

    with _quiet():
        d_req = _bisect_min_d(residual)
    return DepthDemand(
        name="flexure",
        clause="IS 456 Cl 34.2.3.2, G-1.1(b)",
        d_req_mm=d_req,
        detail="cantilever moment "
        + _n(float(mu_nmm_per_m) / 1e6, 2)
        + " kNm per metre at the section halfway between the wall centreline and its face",
    )


def _strip_evaluate_plain(
    plan: StripPlan, geom: StripGeometry, ctx: FootingContext, overall_d_mm: float
) -> _StripEval:
    """Every check on one trial thickness of a PLAIN concrete strip.

    A plain strip is a bearing check and a projection check. There is no steel
    calculation here on purpose: reinforcement that no section needs is not a
    conservative extra, it is a wrong answer about what the member is.
    """
    projection = plan.projection_mm
    factor = plain_spread_factor(plan.q_service_kpa, ctx.fck_mpa)
    rows = [
        ("bearing pressure", plan.notes[0], plan.q_service_kpa, plan.q_allow_kpa, "kPa"),
        ("plain concrete spread", "IS 456 Cl 34.1.3", projection * factor, float(overall_d_mm), "mm"),
        ("projection", "IS 456 Cl 34.1.3", projection, float(overall_d_mm), "mm"),
        (
            "edge thickness",
            "IS 456 Cl 34.1.2",
            is456.cl_34_1_2__min_edge_thickness(),
            float(overall_d_mm),
            "mm",
        ),
    ]  # type: List[Tuple[Any, ...]]
    ratios = [
        (
            "bearing pressure",
            plan.q_service_kpa / plan.q_allow_kpa if plan.q_allow_kpa > 0.0 else C.RATIO_CAP,
        ),
        (
            "plain concrete spread",
            projection * factor / float(overall_d_mm) if overall_d_mm > 0.0 else C.RATIO_CAP,
        ),
    ]
    reason = ""
    for row in rows:
        if row[3] > 0.0 and row[2] > row[3] * (1.0 + C.CHECK_TOL):
            reason = str(row[0])
            break
    return _StripEval(
        verdict=STRIP_VERDICT_PLAIN,
        d_mm=0.0,
        overall_d_mm=float(overall_d_mm),
        dia_mm=0,
        steel_main=None,
        steel_dist=None,
        arm_flex_mm=_strip_flexure_arm_mm(plan.width_mm, float(geom.wall_t_m) * 1000.0),
        arm_shear_mm=projection,
        mu_nmm_per_m=0.0,
        qu_mpa=0.0,
        rows=tuple(rows),
        depth_ratios=tuple(ratios),
        ok=not reason,
        reason=reason,
    )


def _strip_evaluate_rc(
    plan: StripPlan,
    geom: StripGeometry,
    loads: StripLoads,
    ctx: FootingContext,
    overall_d_mm: float,
    cover_mm: float,
) -> _StripEval:
    """Every check on one trial thickness of a REINFORCED strip, with its steel.

    The bar diameter and the effective depth chase each other exactly as they do
    on a pad, so the pair is settled by a short fixed-point walk over the
    catalogue before anything is checked. A strip carries ONE mat, so the
    effective depth is D - cover - half a bar, not the pad's D - cover - 1.5.
    """
    fck = float(ctx.fck_mpa)
    fy = float(ctx.fy_mpa)
    wall_t_mm = float(geom.wall_t_m) * 1000.0
    arm_flex = _strip_flexure_arm_mm(plan.width_mm, wall_t_mm)
    arm_shear = _strip_face_arm_mm(plan.width_mm, wall_t_mm)
    qu_mpa = loads.factored_kn_per_m(ctx.load_factor) / plan.width_mm if plan.width_mm > 0.0 else 0.0
    mu_per_m = 1000.0 * qu_mpa * arm_flex * arm_flex / 2.0

    dia = int(sorted(ctx.bar_dias_mm)[0])
    d_mm = float(overall_d_mm) - float(cover_mm) - 0.5 * dia
    steel = None  # type: Optional[MeshSteel]
    for _pass in range(4):
        d_mm = float(overall_d_mm) - float(cover_mm) - 0.5 * dia
        if d_mm <= 0.0:
            break
        steel = mesh_steel(
            mu_per_m,
            d_mm,
            float(overall_d_mm),
            ctx,
            max_dia_mm=anchorage_dia_cap_mm(
                arm_flex - float(cover_mm),
                ctx,
                _stress_ratio(mu_per_m, d_mm, float(overall_d_mm), ctx),
            ),
        )
        if steel.dia_mm == dia:
            break
        dia = steel.dia_mm
    d_mm = max(d_mm, 1.0)
    if steel is None:
        steel = mesh_steel(mu_per_m, d_mm, float(overall_d_mm), ctx)
    d_dist = max(float(overall_d_mm) - float(cover_mm) - 1.5 * float(dia), 1.0)
    dist = _distribution_steel(float(overall_d_mm), d_dist, ctx)

    shear_n = qu_mpa * max(arm_shear - d_mm, 0.0) * 1000.0
    tau_v = is456.cl_40_1__tau_v(shear_n, 1000.0, d_mm) if shear_n > 0.0 else 0.0
    pt = 100.0 * steel.ast_prov_mm2_m / (1000.0 * d_mm)
    tau_c = is456.table_19__tau_c(pt, fck)
    mu_lim = is456.annex_g__mu_lim(1000.0, d_mm, fck, fy)
    required, available, _bend, _relaxed = _anchorage(
        steel.ld_mm, steel.ast_flexure_mm2_m, steel.ast_prov_mm2_m, arm_flex - float(cover_mm), steel.dia_mm
    )

    rows = [
        ("bearing pressure", plan.notes[0], plan.q_service_kpa, plan.q_allow_kpa, "kPa"),
        ("one-way shear", "IS 456 Cl 34.2.4.1, Cl 40.1, Table 19", tau_v, tau_c, "MPa"),
        ("flexure", "IS 456 Cl 34.2.3.2, G-1.1(b)", mu_per_m, mu_lim, "N.mm per m"),
        ("steel transverse", "IS 456 Cl 26.5.2.1", steel.ast_req_mm2_m, steel.ast_prov_mm2_m, "mm2 per m"),
        ("bar spacing transverse", "IS 456 Cl 26.3.3", steel.spacing_mm, steel.max_spacing_mm, "mm"),
        ("steel longitudinal", "IS 456 Cl 26.5.2.1", dist.ast_req_mm2_m, dist.ast_prov_mm2_m, "mm2 per m"),
        ("bar spacing longitudinal", "IS 456 Cl 26.3.3", dist.spacing_mm, dist.max_spacing_mm, "mm"),
        (
            "edge thickness",
            "IS 456 Cl 34.1.2",
            is456.cl_34_1_2__min_edge_thickness(),
            float(overall_d_mm),
            "mm",
        ),
        ("bar anchorage", "IS 456 Cl 26.2.1", required, available, "mm"),
    ]  # type: List[Tuple[Any, ...]]
    ratios = [
        ("one-way shear", tau_v / tau_c if tau_c > 0.0 else C.RATIO_CAP),
        ("flexure", mu_per_m / mu_lim if mu_lim > 0.0 else C.RATIO_CAP),
    ]
    reason = ""
    for row in rows:
        if row[0] not in STRIP_DEPTH_DRIVEN_CHECKS:
            continue
        if row[3] <= 0.0 or row[2] > row[3] * (1.0 + C.CHECK_TOL):
            reason = str(row[0])
            break
    return _StripEval(
        verdict=STRIP_VERDICT_RC,
        d_mm=d_mm,
        overall_d_mm=float(overall_d_mm),
        dia_mm=int(dia),
        steel_main=steel,
        steel_dist=dist,
        arm_flex_mm=arm_flex,
        arm_shear_mm=arm_shear,
        mu_nmm_per_m=mu_per_m,
        qu_mpa=qu_mpa,
        rows=tuple(rows),
        depth_ratios=tuple(ratios),
        ok=not reason,
        reason=reason,
    )


def _as_strip_inputs(footing: Any, loads: Any, soil: Any, ctx: Any) -> Tuple[Any, Any, Any, Any]:
    """Accept the demands-first call and plain dicts, exactly as the pad does."""
    if isinstance(loads, StripGeometry) or isinstance(footing, StripLoads):
        footing, loads, soil, ctx = loads, footing, None, (ctx if ctx is not None else soil)
    if isinstance(footing, Mapping):
        footing = StripGeometry.from_mapping(footing)
    if isinstance(loads, Mapping):
        loads = StripLoads.from_wall_ledger(loads)
    elif isinstance(loads, (int, float)):
        loads = StripLoads(n_service_kn_per_m=float(loads))
    return (footing, loads, soil, ctx)


def design_strip_footing(
    footing: StripGeometry, loads: StripLoads, soil: Any = None, ctx: Any = None
) -> C.DesignResult:
    """Design one wall strip footing and return a fully populated DesignResult.

    Never raises. The verdict is on `section["verdict"]`: a plain concrete spread
    footing is an ANSWER, with its bearing and projection checks and no
    reinforcement, and a reinforced strip is designed to IS 456 Cl 34 on a 1 m
    run with transverse steel, nominal longitudinal distribution steel and the
    shear and flexure checks that sized it.

    `governing_check` names the check that decided the section: the bearing
    pressure or the plain spread on a plain strip, the shear or the flexure on a
    reinforced one. A result that fails hands the name to the check that failed.
    """
    entries = []  # type: List[TraceEntry]
    result = C.DesignResult(element_id="footing", element_type="footing")
    try:
        with trace_into(entries):
            footing, loads, soil, ctx = _as_strip_inputs(footing, loads, soil, ctx)
            result.element_id = str(getattr(footing, "element_id", "") or "footing")
            context = FootingContext.coerce(ctx)
            profile = SoilProfile.from_params(soil)
            result.materials = C.materials_block(context.concrete, context.steel)
            _strip_body(result, footing, loads, profile, context)
    except Exception as error:  # noqa: BLE001 - disclose, never hide
        result.add_warning("strip footing design stopped on an internal error: " + repr(error))
        result.fail_with("internal error")
    result.trace = entries
    return result


def _strip_body(
    result: C.DesignResult,
    geom: StripGeometry,
    loads: StripLoads,
    soil: SoilProfile,
    ctx: FootingContext,
) -> C.DesignResult:
    """The strip walk: pressure, width, the plain or reinforced verdict, steel."""
    wall_t_mm = float(geom.wall_t_m) * 1000.0
    result.section["kind"] = str(geom.kind or "strip")
    result.section["wall_t_mm"] = wall_t_mm
    result.section["length_mm"] = C.m_to_mm(float(geom.length_m))
    if geom.wall_ids:
        result.section["wall_ids"] = list(geom.wall_ids)

    if wall_t_mm <= 0.0:
        return result.fail_with(
            "wall section",
            "wall thickness "
            + _mm_text(wall_t_mm)
            + " is not a wall: a strip is sized by the wall it carries, so pass a StripGeometry or the "
            "wall_t_m key rather than have one invented",
            clause="IS 456 Cl 34.1",
            demand=1.0,
            capacity=0.0,
            units="mm",
        )
    if float(loads.n_service_kn_per_m) <= 0.0:
        return result.fail_with(
            "service load",
            "service line load "
            + _n(loads.n_service_kn_per_m, 2)
            + " kN/m: a strip needs a load to be sized against",
            clause="IS 6403",
            demand=1.0,
            capacity=0.0,
            units="kN/m",
        )

    grade = C.check_exposure_grade(float(ctx.fck_mpa), ctx.exposure)
    if grade:
        result.add_warning(grade)

    seed_dia = int(sorted(ctx.bar_dias_mm)[0])
    cover = C.resolve_cover("footing", ctx.exposure, ctx.fire_rating_h, seed_dia)

    plan = size_strip(
        float(loads.n_service_kn_per_m),
        wall_t_mm,
        soil,
        ctx,
        length_mm=C.m_to_mm(float(geom.length_m)),
        placed_width_mm=None if geom.placed_width_m is None else C.m_to_mm(geom.placed_width_m),
    )
    for note in plan.notes[1:]:
        result.add_note(note)
    result.add_note(
        "width sized per metre run on the service line load with a "
        + _n(100.0 * ctx.self_weight_allowance, 0)
        + " percent self weight allowance; the width was set by "
        + plan.driver
    )
    if geom.placed_width_m is not None:
        placed = C.m_to_mm(geom.placed_width_m)
        if abs(placed - plan.width_mm) > _EPS:
            result.add_resize(_mm_text(placed), _mm_text(plan.width_mm), "width enlarged: " + plan.driver)
    if geom.eccentric:
        result.add_warning(
            "this strip is flushed inside a boundary and its wall line bears "
            + _n(geom.e_m, 3)
            + " m off the strip centre; v1 checks bearing as uniform pressure and takes no "
            "eccentricity moment, so the eccentric bearing peak is disclosed here, not designed for"
        )

    # -- the projection past the wall face decides which member this is -----
    step = float(ctx.policy.footing_depth_step_mm)
    factor = plain_spread_factor(plan.q_service_kpa, ctx.fck_mpa)
    plain_required = plan.projection_mm * factor
    plain_overall = max(is456.cl_34_1_2__min_edge_thickness(), C.round_up_mm(plain_required, step))
    result.section["projection_mm"] = plan.projection_mm
    result.section["plain_spread_factor"] = factor
    result.section["plain_thickness_required_mm"] = plain_overall
    result.section["plain_thickness_cap_mm"] = float(ctx.plain_strip_max_thickness_mm)

    if plain_overall <= float(ctx.plain_strip_max_thickness_mm) + _EPS:
        evaluation = _strip_evaluate_plain(plan, geom, ctx, plain_overall)
        result.add_note(
            "the "
            + _mm_text(plan.projection_mm)
            + " projection past the wall face is carried by "
            + _mm_text(plain_overall)
            + " of PLAIN concrete (IS 456 Cl 34.1.3 asks for "
            + _mm_text(plain_required)
            + "), so this is a plain concrete spread footing: no bending steel is required and none "
            "is detailed"
        )
        _emit_strip(result, geom, plan, ctx, cover.cover_mm, evaluation)
        _settle(result, evaluation)
        return result

    # -- reinforced: IS 456 Cl 34 on a 1 m run of wall ----------------------
    result.add_note(cover.note)
    result.add_note(
        "the "
        + _mm_text(plan.projection_mm)
        + " projection past the wall face would need "
        + _mm_text(plain_overall)
        + " of plain concrete, past the "
        + _mm_text(ctx.plain_strip_max_thickness_mm)
        + " this design pours unreinforced, so the strip is reinforced and a bending check applies"
    )
    result.add_note(
        "the bending section is halfway between the wall centreline and the wall face, which is what "
        "IS 456 Cl 34.2.3.2(b) puts under a MASONRY wall; the shear section is at d from the wall "
        "face per Cl 34.2.4.1"
    )
    result.add_note("one mat of transverse steel, so the effective depth is D - cover - half a bar diameter")

    arm_flex = _strip_flexure_arm_mm(plan.width_mm, wall_t_mm)
    arm_shear = _strip_face_arm_mm(plan.width_mm, wall_t_mm)
    qu_mpa = loads.factored_kn_per_m(ctx.load_factor) / plan.width_mm if plan.width_mm > 0.0 else 0.0
    mu_per_m = 1000.0 * qu_mpa * arm_flex * arm_flex / 2.0

    demands = [
        _required_d_strip_shear(qu_mpa, arm_shear, mu_per_m, ctx, cover.cover_mm),
        _required_d_strip_flexure(mu_per_m, ctx),
    ]
    refused = [demand for demand in demands if demand.d_req_mm is None]
    d_req = max([demand.d_req_mm for demand in demands if demand.d_req_mm is not None] or [_D_SEARCH_MIN_MM])
    overall = max(
        is456.cl_34_1_2__min_edge_thickness(),
        C.round_up_mm(d_req + cover.cover_mm + 0.5 * seed_dia, step),
    )

    evaluation = None  # type: Optional[_StripEval]
    for _attempt in range(int(ctx.policy.max_iters)):
        with _quiet():
            evaluation = _strip_evaluate_rc(plan, geom, loads, ctx, overall, cover.cover_mm)
        if evaluation.ok:
            break
        bumped = overall + step
        result.add_resize(_mm_text(overall), _mm_text(bumped), "thickness increased for " + evaluation.reason)
        overall = bumped
    evaluation = _strip_evaluate_rc(plan, geom, loads, ctx, overall, cover.cover_mm)

    _emit_strip(result, geom, plan, ctx, cover.cover_mm, evaluation)
    for demand in refused:
        result.add_warning(
            demand.name
            + " ("
            + demand.clause
            + ") cannot be satisfied at any thickness up to "
            + _mm_text(_D_SEARCH_MAX_MM)
            + ": "
            + demand.detail
        )
    _settle(result, evaluation)
    if refused:
        result.governing_check = refused[0].name
        result.status = C.STATUS_FAIL
    return result


def _emit_strip(
    result: C.DesignResult,
    geom: StripGeometry,
    plan: StripPlan,
    ctx: FootingContext,
    cover_mm: float,
    ev: _StripEval,
) -> None:
    """Write the settled strip into the result: section, checks and any bars.

    `bx_mm` and `ly_mm` carry the same plan rectangle as `length_mm` and
    `width_mm`, in the run-then-width order `quantities._footing_plan_m` reads a
    footing in, so the take-off measures the DESIGNED strip and the report card
    renders it as a rectangle rather than as a bare thickness. `orient` says
    which way the run points, since a strip's own frame is not the model's x
    and y.
    """
    length_mm = C.m_to_mm(float(geom.length_m))
    result.section.update(
        {
            "verdict": ev.verdict,
            "reinforced": ev.verdict == STRIP_VERDICT_RC,
            "width_mm": plan.width_mm,
            "bx_mm": length_mm,
            "ly_mm": plan.width_mm,
            "D_mm": ev.overall_d_mm,
            "q_allow_kpa": plan.q_allow_kpa,
            "q_service_kpa": plan.q_service_kpa,
            "width_driver": plan.driver,
        }
    )
    if geom.orient:
        result.section["orient"] = str(geom.orient)
    if ev.verdict == STRIP_VERDICT_RC:
        result.section["d_mm"] = ev.d_mm
        result.section["cover_mm"] = float(cover_mm)
        result.section["qu_mpa"] = ev.qu_mpa
    result.extras["si"] = {
        "width_m": C.mm_to_m(plan.width_mm),
        "thickness_m": C.mm_to_m(ev.overall_d_mm),
        "length_m": float(geom.length_m),
    }
    for name, clause, demand, capacity, units in ev.rows:
        result.add_check(name, clause, demand, capacity, units=units)

    if ev.verdict == STRIP_VERDICT_PLAIN:
        return

    steel = ev.steel_main
    result.add_bar(
        role="strip_transverse_bottom",
        count=bar_count(length_mm, cover_mm, steel.spacing_mm),
        dia_mm=steel.dia_mm,
        ld_mm=steel.ld_mm,
        zone_mm=[cover_mm, max(plan.width_mm - cover_mm, cover_mm)],
        layer=1,
        spacing_mm=steel.spacing_mm,
        direction="transverse",
        face="bottom",
        strip="across the strip, main steel",
    )
    dist = ev.steel_dist
    result.add_bar(
        role="strip_longitudinal_bottom",
        count=bar_count(plan.width_mm, cover_mm, dist.spacing_mm),
        dia_mm=dist.dia_mm,
        ld_mm=dist.ld_mm,
        zone_mm=[cover_mm, max(length_mm - cover_mm, cover_mm)],
        layer=2,
        spacing_mm=dist.spacing_mm,
        direction="longitudinal",
        face="bottom",
        strip="along the run, nominal distribution steel",
    )
    if length_mm <= 0.0:
        result.add_warning(
            "the strip states no run length, so the bar COUNTS are the two-bar floor; the spacings and "
            "the areas per metre are the design and are unaffected"
        )
    required, available, bend, relaxed = _anchorage(
        steel.ld_mm, steel.ast_flexure_mm2_m, steel.ast_prov_mm2_m, ev.arm_flex_mm - cover_mm, steel.dia_mm
    )
    if bend:
        result.add_note(
            "the straight run past the bending section is "
            + _mm_text(max(ev.arm_flex_mm - cover_mm, 0.0))
            + " against Ld "
            + _mm_text(steel.ld_mm)
            + ", so the transverse bars end in a standard 90 degree bend"
        )
    if relaxed:
        result.add_note(
            "development length taken at the stress the bar carries, "
            "Ld x Ast_flexure/Ast_provided = " + _mm_text(required)
        )
    if steel.note:
        result.add_warning("transverse mat: " + steel.note)
    if dist.note:
        result.add_warning("longitudinal mat: " + dist.note)
    if ev.d_mm <= 0.0:
        result.add_warning("the cover and bar stack leaves no effective depth at " + _mm_text(ev.overall_d_mm))
