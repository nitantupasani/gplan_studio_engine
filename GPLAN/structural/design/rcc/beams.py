"""RC beam design to IS 456:2000, with the IS 13920 overlay where it applies.

Input is one `analysis.BeamForces` envelope (the only designer input critic
finding 20 allows), one `BeamGeometry` from placement, and one
`detailing.DesignContext`. Output is one `common.DesignResult`, always: a beam
that cannot be made to work comes back fully populated with status `fail` and
the check that stopped it, never as an exception and never as an empty result.

The sequence is the one the spec fixes, per trial section:

1. effective depth from the cover stack (Table 16, Table 16A, bar diameter);
2. torsion folded in as Cl 41 equivalent shear and equivalent moments, when the
   envelope carries a torsion;
3. flexure at three stations (top at each end, bottom at midspan) through the
   Annex G callables, under the resize ladder depth, then doubly, then width;
4. minimum and maximum steel, Table 15 crack spacing, side face steel;
5. bar selection through `common.pick_bars`, with the effective depth
   recomputed from the chosen layout and the flexure re-checked once;
6. development length per bar zone and the Cl 26.2.3.3 anchorage check at a
   simple support;
7. shear at both ends from the PROVIDED tension steel, with the Table 20 cap
   read as a section failure rather than a stirrup problem;
8. span over effective depth with the Fig 4, 5 and 6 modification factors;
9. the IS 13920 overlay, after the IS 456 design passes.

Units are N, mm, MPa, N.mm throughout; the kN and kNm envelope is converted
once on entry by `common.kn_to_n` and `common.knm_to_nmm`.

Two simplifications are deliberate, disclosed on every result, and named in the
spec: bottom bars run the full length of the span (the 50 percent that SP 34
would curtail at 0.1 l is an optimization not applied), and hogging bars run
0.3 of the clear span plus a development length plus the Cl 26.2.3.1 extension,
with nothing curtailed at 0.15 l.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ...analysis import BeamForces
from ...codes import is456
from ...codes.trace import TraceEntry, trace_into
from .. import common as C
from . import detailing as D

__all__ = [
    "BeamGeometry",
    "as_beam_geometry",
    "design_beam",
    "CANTILEVER_REFUSAL_SPAN_MM",
]

#: Placement refuses a cantilever longer than this (catalogue rule, disclosure
#: code E_CANTILEVER_SPAN). A longer one reaching design is a pipeline slip, so
#: it is designed and warned about rather than dropped.
CANTILEVER_REFUSAL_SPAN_MM = 2500.0

#: Diameter assumed for the first effective depth, before a layout exists.
_ASSUMED_MAIN_DIA_MM = 16.0
#: Smallest main bar a beam is detailed with.
_MIN_MAIN_DIA_MM = 12

#: Millimetres below which two covers are the same cover.
_COVER_TOL_MM = 1e-9
#: Stirrup diameter the shear ladder starts from.
_BASE_STIRRUP_DIA_MM = 8.0
#: Bars carried through the span to hold the stirrup cage where the hogging
#: steel is curtailed. Not a strength requirement of IS 456; IS 13920 Cl
#: 6.2.1(b) makes two of them mandatory in a ductile frame.
_HANGER_DIA_MM = 12

_TOL = 1e-9


# ---------------------------------------------------------------------------
# geometry and forces at the design boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeamGeometry:
    """One beam's geometry in design units, mm.

    `span_mm` is the effective span the analysis used (centre to centre in the
    v1 takedown); `clear_span_mm` defaults to the effective span less the
    support width, which is what IS 13920 Cl 6.1 and Cl 6.3.3 are written in.
    """

    b_mm: float
    D_mm: float
    span_mm: float
    support: str = D.SUPPORT_CONTINUOUS
    clear_span_mm: float = 0.0
    support_width_mm: float = 230.0
    bf_mm: Optional[float] = None
    element_id: str = "beam"
    storey: int = 0

    def __post_init__(self) -> None:
        if float(self.b_mm) <= 0.0 or float(self.D_mm) <= 0.0:
            raise ValueError("beam b_mm and D_mm must be positive")
        if float(self.span_mm) <= 0.0:
            raise ValueError("beam span_mm must be positive")
        object.__setattr__(self, "support", D.normalize_support(self.support))

    @property
    def clear_span(self) -> float:
        """Clear span, mm: as stated, else the effective span less one support."""
        stated = float(self.clear_span_mm)
        if stated > 0.0:
            return stated
        return max(float(self.span_mm) - float(self.support_width_mm), 0.5 * float(self.span_mm))

    @property
    def span_m(self) -> float:
        return C.mm_to_m(self.span_mm)


def as_beam_geometry(source: Any) -> BeamGeometry:
    """A BeamGeometry from one, from a mapping, or from any object with the names."""
    if isinstance(source, BeamGeometry):
        return source
    if source is None:
        raise ValueError("design_beam needs a beam geometry, got None")
    b = D.read_field(source, ("b_mm", "width_mm", "b"))
    depth = D.read_field(source, ("D_mm", "d_overall_mm", "overall_depth_mm", "depth_mm", "D"))
    span = D.read_field(source, ("span_mm", "length_mm", "span"))
    if b is None or depth is None or span is None:
        raise ValueError("beam geometry needs b_mm, D_mm and span_mm; got " + repr(source))
    return BeamGeometry(
        b_mm=float(b),
        D_mm=float(depth),
        span_mm=float(span),
        support=D.read_field(source, ("support", "support_condition", "end_condition"), D.SUPPORT_CONTINUOUS),
        clear_span_mm=float(D.read_field(source, ("clear_span_mm", "l_clear_mm"), 0.0)),
        support_width_mm=float(D.read_field(source, ("support_width_mm", "bearing_mm"), 230.0)),
        bf_mm=D.read_field(source, ("bf_mm", "flange_mm", "flange_width_mm")),
        element_id=str(D.read_field(source, ("element_id", "id", "beam_id"), "beam")),
        storey=int(D.read_field(source, ("storey", "level"), 0)),
    )


class _Forces(NamedTuple):
    """The envelope in design units: N and N.mm, magnitudes."""

    mu_hog_a_nmm: float
    mu_hog_b_nmm: float
    mu_sag_nmm: float
    vu_a_n: float
    vu_b_n: float
    tu_nmm: float
    combo_tags: Tuple[Tuple[str, str], ...]


def _as_forces(source: Any) -> _Forces:
    """BeamForces, a mapping or a duck, converted once across the SI boundary."""
    if source is None:
        raise ValueError("design_beam needs a BeamForces envelope, got None")
    if isinstance(source, BeamForces):
        tags = tuple(source.combo_tags)
        tu = source.tu_knm
    else:
        tags = tuple(D.read_field(source, ("combo_tags",), ()) or ())
        tu = D.read_field(source, ("tu_knm", "tu"))
    hog_a = D.read_field(source, ("mu_hog_end_a_knm", "mu_hog_a_knm"), 0.0)
    hog_b = D.read_field(source, ("mu_hog_end_b_knm", "mu_hog_b_knm"), 0.0)
    sag = D.read_field(source, ("mu_sag_mid_knm", "mu_sag_knm"), 0.0)
    vu_a = D.read_field(source, ("vu_a_kn",), 0.0)
    vu_b = D.read_field(source, ("vu_b_kn",), 0.0)
    return _Forces(
        mu_hog_a_nmm=abs(C.knm_to_nmm(hog_a or 0.0)),
        mu_hog_b_nmm=abs(C.knm_to_nmm(hog_b or 0.0)),
        mu_sag_nmm=abs(C.knm_to_nmm(sag or 0.0)),
        vu_a_n=abs(C.kn_to_n(vu_a or 0.0)),
        vu_b_n=abs(C.kn_to_n(vu_b or 0.0)),
        tu_nmm=abs(C.knm_to_nmm(tu or 0.0)),
        combo_tags=tuple((str(pair[0]), str(pair[1])) for pair in tags),
    )


# ---------------------------------------------------------------------------
# per-trial records
# ---------------------------------------------------------------------------


@dataclass
class _Station:
    """One flexural station: what it demands, what the steel chosen gives."""

    name: str
    face: str
    mu_nmm: float
    d_mm: float
    dprime_mm: float
    mu_lim_nmm: float
    ast_req_mm2: float
    asc_req_mm2: float
    ast_min_mm2: float
    ast_max_mm2: float
    layout: C.BarLayout
    comp_layout: Optional[C.BarLayout] = None
    asc_credit_mm2: float = 0.0
    doubly: bool = False
    nominal: bool = False
    mu_cap_nmm: float = 0.0
    ok: bool = True
    reason: str = ""

    @property
    def ast_prov_mm2(self) -> float:
        return float(self.layout.ast_prov_mm2)

    @property
    def asc_prov_mm2(self) -> float:
        extra = 0.0 if self.comp_layout is None else float(self.comp_layout.ast_prov_mm2)
        return float(self.asc_credit_mm2) + extra

    def to_dict(self, b_mm: float) -> Dict[str, Any]:
        return {
            "station": self.name,
            "face": self.face,
            "mu_nmm": float(self.mu_nmm),
            "mu_lim_nmm": float(self.mu_lim_nmm),
            "mu_cap_nmm": float(self.mu_cap_nmm),
            "d_mm": float(self.d_mm),
            "dprime_mm": float(self.dprime_mm),
            "ast_req_mm2": float(self.ast_req_mm2),
            "ast_prov_mm2": float(self.ast_prov_mm2),
            "asc_req_mm2": float(self.asc_req_mm2),
            "asc_prov_mm2": float(self.asc_prov_mm2),
            "pt_pct": 100.0 * self.ast_prov_mm2 / (float(b_mm) * self.d_mm) if self.d_mm > 0.0 else 0.0,
            "bars": self.layout.label,
            "doubly": bool(self.doubly),
            "nominal": bool(self.nominal),
        }


@dataclass
class _ShearEnd:
    """One end's shear design, from the tension steel actually provided there."""

    name: str
    vu_n: float
    ve_n: float
    d_mm: float
    pt_pct: float
    tau_v_mpa: float
    tau_c_mpa: float
    tau_c_max_mpa: float
    vus_n: float
    asv_per_mm_req: float
    choice: D.StirrupChoice
    tension_from: str
    ok: bool = True
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "end": self.name,
            "vu_n": float(self.vu_n),
            "ve_n": float(self.ve_n),
            "d_mm": float(self.d_mm),
            "pt_pct": float(self.pt_pct),
            "tension_steel_from": self.tension_from,
            "tau_v_mpa": float(self.tau_v_mpa),
            "tau_c_mpa": float(self.tau_c_mpa),
            "tau_c_max_mpa": float(self.tau_c_max_mpa),
            "vus_n": float(self.vus_n),
            "stirrups": self.choice.to_dict(),
        }


@dataclass
class _Deflection:
    """The Cl 23.2.1 span over effective depth check on the governing station."""

    span_over_d: float
    allowed: float
    basic: float
    mf_tension: float
    mf_compression: float
    mf_flanged: float
    long_span_factor: float
    fs_mpa: float
    pt_pct: float
    pc_pct: float
    ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_over_d": float(self.span_over_d),
            "allowed": float(self.allowed),
            "basic": float(self.basic),
            "mf_tension": float(self.mf_tension),
            "mf_compression": float(self.mf_compression),
            "mf_flanged": float(self.mf_flanged),
            "long_span_factor": float(self.long_span_factor),
            "fs_mpa": float(self.fs_mpa),
            "pt_pct": float(self.pt_pct),
            "pc_pct": float(self.pc_pct),
        }


@dataclass
class _Attempt:
    """Everything one trial section produced, passing or not."""

    b_mm: float
    D_mm: float
    cover_mm: float
    cover_note: str
    stirrup_dia_mm: float
    width_avail_mm: float
    max_clear_spacing_mm: float
    doubly_allowed: bool
    stations: List[_Station] = field(default_factory=list)
    shear: List[_ShearEnd] = field(default_factory=list)
    middle: Optional[D.StirrupChoice] = None
    deflection: Optional[_Deflection] = None
    side_face: Optional[Any] = None
    torsion: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    through_layout: Optional[C.BarLayout] = None
    ok: bool = True
    reason: str = ""
    detail: str = ""

    def station(self, name: str) -> Optional[_Station]:
        for item in self.stations:
            if item.name == name:
                return item
        return None


# ---------------------------------------------------------------------------
# flexure at one station
# ---------------------------------------------------------------------------


class _Flexure(NamedTuple):
    ast_req_mm2: float
    asc_req_mm2: float
    mu_lim_nmm: float
    doubly: bool
    over_limit: bool


def _flexure(
    mu_nmm: float,
    b_mm: float,
    d_mm: float,
    dprime_mm: float,
    ctx: D.DesignContext,
    doubly_allowed: bool,
) -> _Flexure:
    """Steel for one station at one effective depth, through the Annex G callables."""
    fck = ctx.fck_mpa
    fy = ctx.fy_mpa
    mu_lim = is456.annex_g__mu_lim(b_mm, d_mm, fck, fy)
    ast_min = is456.cl_26_5_1_1__min_tension_steel(b_mm, d_mm, fy)
    if mu_nmm <= 0.0:
        return _Flexure(ast_req_mm2=0.0, asc_req_mm2=0.0, mu_lim_nmm=mu_lim, doubly=False, over_limit=False)
    headroom = mu_lim * (1.0 - 1e-9)
    if mu_nmm <= headroom:
        ast = is456.annex_g__ast_singly(mu_nmm, b_mm, d_mm, fck, fy)
        return _Flexure(
            ast_req_mm2=max(ast, ast_min),
            asc_req_mm2=0.0,
            mu_lim_nmm=mu_lim,
            doubly=False,
            over_limit=False,
        )
    if doubly_allowed and dprime_mm < d_mm:
        doubly = is456.annex_g__doubly(mu_nmm, b_mm, d_mm, dprime_mm, fck, fy)
        return _Flexure(
            ast_req_mm2=max(doubly.ast1_mm2 + doubly.ast2_mm2, ast_min),
            asc_req_mm2=doubly.asc_mm2,
            mu_lim_nmm=mu_lim,
            doubly=True,
            over_limit=False,
        )
    # Singly reinforced and past the limit: the section cannot take this moment
    # at this depth. The balanced steel is reported so the emitted result shows
    # what the trial section actually holds, and the ladder deepens it.
    return _Flexure(
        ast_req_mm2=max(D.ast_balanced_mm2(b_mm, d_mm, fck, fy), ast_min),
        asc_req_mm2=0.0,
        mu_lim_nmm=mu_lim,
        doubly=False,
        over_limit=True,
    )


def _design_station(
    name: str,
    face: str,
    mu_nmm: float,
    b_mm: float,
    depth_mm: float,
    cover_mm: float,
    stirrup_dia_mm: float,
    width_avail_mm: float,
    prefs: C.BarPrefs,
    ctx: D.DesignContext,
    doubly_allowed: bool,
    asc_credit_mm2: float = 0.0,
    asc_credit_depth_mm: float = 0.0,
) -> _Station:
    """Steel at one station, with the effective depth re-derived from the layout.

    The first pass reads the depth an assumed 16 mm bar gives; picking bars
    settles the real depth (layering included), which changes the demand, which
    can change the bars. The loop below runs that exchange to a fixed point,
    bounded at three passes, and then evaluates the flexure once more at the
    depth it settled on, so the requirement, the limiting moment and the
    effective depth the result reports are all read at the same section rather
    than at an intermediate one.
    """
    nominal = mu_nmm <= 0.0
    dprime_one = cover_mm + stirrup_dia_mm + 0.5 * _ASSUMED_MAIN_DIA_MM
    d_final = C.effective_depth(
        depth_mm, cover_mm, stirrup_dia_mm, _ASSUMED_MAIN_DIA_MM, layers=1, agg_mm=prefs.agg_mm
    )
    layout = None  # type: Optional[C.BarLayout]
    for _ in range(3):
        trial = _flexure(mu_nmm, b_mm, d_final, dprime_one, ctx, doubly_allowed)
        if layout is None or trial.ast_req_mm2 > layout.ast_prov_mm2 + 1e-6:
            picked = C.pick_bars(trial.ast_req_mm2, width_avail_mm, prefs)
        else:
            picked = layout
        depth = (
            C.effective_depth(depth_mm, cover_mm, stirrup_dia_mm, picked.max_dia_mm, layers=1, agg_mm=prefs.agg_mm)
            - picked.d_adjust_mm
        )
        settled = picked is layout and abs(depth - d_final) <= 1e-9
        layout, d_final = picked, depth
        if settled:
            break
    second = _flexure(mu_nmm, b_mm, d_final, dprime_one, ctx, doubly_allowed)

    comp_layout = None  # type: Optional[C.BarLayout]
    dprime = dprime_one
    asc_extra_req = max(second.asc_req_mm2 - float(asc_credit_mm2), 0.0)
    if second.asc_req_mm2 > 0.0:
        if asc_extra_req > 1e-6:
            comp_layout = C.pick_bars(asc_extra_req, width_avail_mm, prefs)
            dprime = cover_mm + stirrup_dia_mm + 0.5 * comp_layout.max_dia_mm
        elif asc_credit_depth_mm > 0.0:
            dprime = float(asc_credit_depth_mm)

    asc_prov = float(asc_credit_mm2) + (0.0 if comp_layout is None else float(comp_layout.ast_prov_mm2))
    capacity = D.moment_capacity_nmm(
        b_mm,
        d_final,
        ctx.fck_mpa,
        ctx.fy_mpa,
        layout.ast_prov_mm2,
        asc_prov if second.asc_req_mm2 > 0.0 else 0.0,
        dprime if second.asc_req_mm2 > 0.0 else 0.0,
    )
    ast_min = is456.cl_26_5_1_1__min_tension_steel(b_mm, d_final, ctx.fy_mpa)
    ast_max = is456.cl_26_5_1_1b__max_steel(b_mm, depth_mm)

    ok = True
    reason = ""
    if second.over_limit:
        ok, reason = False, "flexure"
    elif capacity + 1e-6 < mu_nmm:
        ok, reason = False, "flexure"
    elif not layout.ok:
        ok, reason = False, "bar_fit"
    elif comp_layout is not None and not comp_layout.ok:
        ok, reason = False, "bar_fit"
    elif layout.ast_prov_mm2 > ast_max + 1e-6:
        ok, reason = False, "max_steel"
    elif comp_layout is not None and comp_layout.ast_prov_mm2 > ast_max + 1e-6:
        ok, reason = False, "max_steel"

    return _Station(
        name=name,
        face=face,
        mu_nmm=float(mu_nmm),
        d_mm=d_final,
        dprime_mm=dprime,
        mu_lim_nmm=second.mu_lim_nmm,
        ast_req_mm2=second.ast_req_mm2,
        asc_req_mm2=second.asc_req_mm2,
        ast_min_mm2=ast_min,
        ast_max_mm2=ast_max,
        layout=layout,
        comp_layout=comp_layout,
        asc_credit_mm2=float(asc_credit_mm2) if second.asc_req_mm2 > 0.0 else 0.0,
        doubly=second.doubly,
        nominal=nominal,
        mu_cap_nmm=capacity,
        ok=ok,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# shear at one end
# ---------------------------------------------------------------------------


def _design_shear_end(
    name: str,
    vu_n: float,
    ve_n: float,
    b_mm: float,
    d_mm: float,
    ast_tension_mm2: float,
    tension_from: str,
    ctx: D.DesignContext,
    torsion_per_mm: float = 0.0,
) -> _ShearEnd:
    """Stirrups at one end from the tension steel that is actually there."""
    fck = ctx.fck_mpa
    fy_stirrup = ctx.fy_stirrup_mpa
    shear = max(ve_n, 0.0)
    tau_v = is456.cl_40_1__tau_v(shear, b_mm, d_mm)
    tau_c_max = is456.table_20__tau_c_max(fck)
    pt = 100.0 * max(ast_tension_mm2, 0.0) / (b_mm * d_mm) if d_mm > 0.0 else 0.0
    tau_c = is456.table_19__tau_c(pt, fck)
    vus = max(shear - tau_c * b_mm * d_mm, 0.0)
    asv_per_mm = max(
        is456.cl_40_4__vertical_stirrups(vus, fy_stirrup, d_mm),
        is456.cl_26_5_1_6__min_stirrups(b_mm, fy_stirrup),
        float(torsion_per_mm),
    )
    choice = D.choose_stirrups(asv_per_mm, is456.cl_26_5_1_5__max_stirrup_spacing(d_mm))
    ok = True
    reason = ""
    if tau_v > tau_c_max + 1e-9:
        # Table 20 is a limit on the section, not on the stirrups: no amount of
        # shear steel is allowed to carry a beam past it.
        ok, reason = False, "shear_section"
    elif not choice.ok:
        ok, reason = False, "shear_stirrups"
    return _ShearEnd(
        name=name,
        vu_n=float(vu_n),
        ve_n=float(shear),
        d_mm=float(d_mm),
        pt_pct=pt,
        tau_v_mpa=tau_v,
        tau_c_mpa=tau_c,
        tau_c_max_mpa=tau_c_max,
        vus_n=vus,
        asv_per_mm_req=asv_per_mm,
        choice=choice,
        tension_from=tension_from,
        ok=ok,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# one trial section
# ---------------------------------------------------------------------------


def _attempt(
    forces: _Forces,
    geom: BeamGeometry,
    ctx: D.DesignContext,
    b_mm: float,
    depth_mm: float,
    doubly_allowed: bool,
    seed_dia_mm: float = 0.0,
) -> _Attempt:
    """Design one trial section end to end, reporting whatever it produced.

    `seed_dia_mm` is the largest main bar a previous pass over this section
    chose. IS 456 Cl 26.4.1 asks that the nominal cover be at least the bar
    diameter, and no bar exists before the flexure is designed, so the first
    pass resolves the cover with no diameter and the tail of this function
    re-resolves it against the bars that were actually chosen. Only when the
    cover moves does the section get designed again, at the larger cover; the
    sibling column designer resolves the same way once its cage is known.
    """
    cover = C.resolve_cover("beam", ctx.exposure, ctx.fire_rating_h, float(seed_dia_mm))
    stirrup_dia = _BASE_STIRRUP_DIA_MM
    width_avail = C.clear_width_mm(b_mm, cover.cover_mm, stirrup_dia)
    max_clear = is456.table_15__clear_spacing(ctx.fy_mpa, ctx.redistribution_pct)
    prefs = C.BarPrefs(
        dias_mm=tuple(dia for dia in C.MAIN_DIAS if dia >= _MIN_MAIN_DIA_MM),
        min_dia_mm=_MIN_MAIN_DIA_MM,
        min_bars_per_layer=2,
        max_bars_per_layer=6,
        max_layers=2,
        agg_mm=ctx.agg_mm,
        max_clear_spacing_mm=max_clear,
    )
    attempt = _Attempt(
        b_mm=float(b_mm),
        D_mm=float(depth_mm),
        cover_mm=float(cover.cover_mm),
        cover_note=cover.note,
        stirrup_dia_mm=stirrup_dia,
        width_avail_mm=width_avail,
        max_clear_spacing_mm=max_clear,
        doubly_allowed=bool(doubly_allowed),
    )

    cantilever = geom.support == D.SUPPORT_CANTILEVER
    mu_top_a = forces.mu_hog_a_nmm
    mu_top_b = forces.mu_hog_b_nmm
    mu_bottom = forces.mu_sag_nmm
    torsion_per_mm = 0.0

    # -- Cl 41 torsion folded into equivalent shear and moments ------------
    if forces.tu_nmm > 0.0:
        equiv_a = is456.cl_41_4_2__equiv_moment(forces.mu_hog_a_nmm, forces.tu_nmm, b_mm, depth_mm)
        equiv_b = is456.cl_41_4_2__equiv_moment(forces.mu_hog_b_nmm, forces.tu_nmm, b_mm, depth_mm)
        equiv_mid = is456.cl_41_4_2__equiv_moment(forces.mu_sag_nmm, forces.tu_nmm, b_mm, depth_mm)
        mu_top_a = max(equiv_a.me1_nmm, equiv_mid.me2_nmm)
        mu_top_b = max(equiv_b.me1_nmm, equiv_mid.me2_nmm)
        mu_bottom = max(equiv_mid.me1_nmm, equiv_a.me2_nmm, equiv_b.me2_nmm)
        ve_a = is456.cl_41_3_1__equiv_shear(forces.vu_a_n, forces.tu_nmm, b_mm)
        ve_b = is456.cl_41_3_1__equiv_shear(forces.vu_b_n, forces.tu_nmm, b_mm)
        attempt.torsion = {
            "tu_nmm": forces.tu_nmm,
            "mt_nmm": equiv_mid.mt_nmm,
            "me1_mid_nmm": equiv_mid.me1_nmm,
            "me2_mid_nmm": equiv_mid.me2_nmm,
            "ve_a_n": ve_a,
            "ve_b_n": ve_b,
        }
        attempt.notes.append(
            "IS 456 Cl 41: the envelope carries a torsion, so the equivalent shear Ve (Cl 41.3.1) and the "
            "equivalent moments Me1 and Me2 (Cl 41.4.2) replace Vu and Mu at every station"
        )
    else:
        ve_a = forces.vu_a_n
        ve_b = forces.vu_b_n

    if cantilever:
        mu_top = max(mu_top_a, mu_top_b)
        mu_top_a, mu_top_b = mu_top, mu_top

    # -- flexure: bottom first, so the ends can credit it in compression ---
    bottom = _design_station(
        "bottom_mid",
        "bottom",
        mu_bottom,
        b_mm,
        depth_mm,
        cover.cover_mm,
        stirrup_dia,
        width_avail,
        prefs,
        ctx,
        doubly_allowed,
    )
    bottom_depth_from_face = cover.cover_mm + stirrup_dia + 0.5 * bottom.layout.max_dia_mm
    stations = [bottom]
    top_names = ("top_left", "top_right")
    for name, moment in zip(top_names, (mu_top_a, mu_top_b)):
        stations.append(
            _design_station(
                name,
                "top",
                moment,
                b_mm,
                depth_mm,
                cover.cover_mm,
                stirrup_dia,
                width_avail,
                prefs,
                ctx,
                doubly_allowed,
                asc_credit_mm2=bottom.layout.ast_prov_mm2,
                asc_credit_depth_mm=bottom_depth_from_face,
            )
        )
    attempt.stations = stations

    # -- Cl 41.4.3 transverse steel for torsion, per mm of beam ------------
    if forces.tu_nmm > 0.0:
        dia_corner = max(bottom.layout.max_dia_mm, stations[1].layout.max_dia_mm, stations[2].layout.max_dia_mm)
        b1 = b_mm - 2.0 * (cover.cover_mm + stirrup_dia + 0.5 * dia_corner)
        d1 = depth_mm - 2.0 * (cover.cover_mm + stirrup_dia + 0.5 * dia_corner)
        if b1 > 0.0 and d1 > 0.0:
            worst_v = max(forces.vu_a_n, forces.vu_b_n)
            worst_d = min(station.d_mm for station in stations)
            tau_ve = is456.cl_40_1__tau_v(max(ve_a, ve_b), b_mm, worst_d)
            pt_worst = 100.0 * bottom.layout.ast_prov_mm2 / (b_mm * worst_d)
            transverse = is456.cl_41_4_3__transverse(
                forces.tu_nmm,
                worst_v,
                b1,
                d1,
                ctx.fy_stirrup_mpa,
                1.0,
                b_mm,
                tau_ve,
                is456.table_19__tau_c(pt_worst, ctx.fck_mpa),
            )
            torsion_per_mm = transverse.asv_req_mm2
            attempt.torsion["asv_per_mm_req"] = torsion_per_mm
            attempt.torsion["b1_mm"] = b1
            attempt.torsion["d1_mm"] = d1

    # -- shear at both ends, from the steel that is actually in tension ----
    ends = (
        ("a", forces.vu_a_n, ve_a, mu_top_a, attempt.station("top_left")),
        ("b", forces.vu_b_n, ve_b, mu_top_b, attempt.station("top_right")),
    )
    for name, vu, ve, moment, station in ends:
        if moment > 0.0 and station is not None and not station.nominal:
            ast_tension = station.layout.ast_prov_mm2
            d_end = station.d_mm
            tension_from = station.name
        else:
            # No hogging at this end: the bars in tension at the support are the
            # bottom bars, which run the full length in this version.
            ast_tension = bottom.layout.ast_prov_mm2
            d_end = bottom.d_mm
            tension_from = "bottom_mid"
        attempt.shear.append(
            _design_shear_end(
                name,
                vu,
                ve,
                b_mm,
                d_end,
                ast_tension,
                tension_from,
                ctx,
                torsion_per_mm=torsion_per_mm,
            )
        )
    middle_demand = max(
        is456.cl_26_5_1_6__min_stirrups(b_mm, ctx.fy_stirrup_mpa),
        torsion_per_mm,
    )
    attempt.middle = D.choose_stirrups(
        middle_demand,
        is456.cl_26_5_1_5__max_stirrup_spacing(min(station.d_mm for station in stations)),
    )

    # -- Cl 26.5.1.3 side face steel ---------------------------------------
    attempt.side_face = is456.cl_26_5_1_3__side_face(b_mm, depth_mm, torsion=forces.tu_nmm > 0.0)

    # -- Cl 23.2.1 span over effective depth -------------------------------
    governing = _governing_station(attempt, cantilever)
    attempt.deflection = _check_deflection(governing, attempt, geom, ctx)

    # -- verdict ------------------------------------------------------------
    for station in attempt.stations:
        if not station.ok:
            attempt.ok = False
            attempt.reason = station.reason
            attempt.detail = station.name
            break
    if attempt.ok:
        for end in attempt.shear:
            if not end.ok:
                attempt.ok = False
                attempt.reason = end.reason
                attempt.detail = "end " + end.name
                break
    if attempt.ok and attempt.deflection is not None and not attempt.deflection.ok:
        attempt.ok = False
        attempt.reason = "deflection"
        attempt.detail = "span/d " + ("%.2f" % attempt.deflection.span_over_d)

    # -- Cl 26.4.1 cover against the bars actually chosen -------------------
    # The cover above was resolved before any bar existed, so a 32 mm bar could
    # be detailed on a 30 mm Table 16 cover. Re-resolve against the largest main
    # bar and design the section again when the cover moved: the effective depth
    # and the bar choice both follow the cover, so nothing short of a re-run is
    # honest. The seed strictly increases and the diameters come from a finite
    # catalogue, so the walk is bounded by the number of bar sizes.
    dia = _largest_main_dia_mm(attempt)
    if dia > seed_dia_mm + _COVER_TOL_MM:
        recut = C.resolve_cover("beam", ctx.exposure, ctx.fire_rating_h, dia)
        if recut.cover_mm > attempt.cover_mm + _COVER_TOL_MM:
            return _attempt(forces, geom, ctx, b_mm, depth_mm, doubly_allowed, dia)
    return attempt


def _largest_main_dia_mm(attempt: _Attempt) -> float:
    """The biggest longitudinal bar this attempt chose, tension or compression."""
    largest = 0.0
    for station in attempt.stations:
        largest = max(largest, float(station.layout.max_dia_mm))
        if station.comp_layout is not None:
            largest = max(largest, float(station.comp_layout.max_dia_mm))
    return largest


def _governing_station(attempt: _Attempt, cantilever: bool) -> _Station:
    """The station the deflection rule reads: the cantilever root, else midspan."""
    if cantilever:
        top = attempt.station("top_left")
        if top is not None and not top.nominal:
            return top
    bottom = attempt.station("bottom_mid")
    return bottom if bottom is not None else attempt.stations[0]


def _check_deflection(
    station: _Station,
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
) -> _Deflection:
    """Cl 23.2.1 with the Fig 4, Fig 5 and Fig 6 modification factors."""
    b_mm = attempt.b_mm
    d_mm = station.d_mm
    basic = is456.cl_23_2_1__basic_ld(geom.support)
    pt = 100.0 * station.ast_prov_mm2 / (b_mm * d_mm) if d_mm > 0.0 else 0.0
    pc = 100.0 * station.asc_prov_mm2 / (b_mm * d_mm) if d_mm > 0.0 else 0.0
    ast_req = max(station.ast_req_mm2, 0.0)
    fs = (
        is456.cl_23_2_1__fs(ctx.fy_mpa, ast_req, station.ast_prov_mm2)
        if station.ast_prov_mm2 > 0.0 and ast_req > 0.0
        else 0.0
    )
    mf_t = is456.fig_4__mf_tension(fs, pt) if pt > 0.0 else 2.0
    mf_c = is456.fig_5__mf_compression(pc)
    mf_f = 1.0
    if geom.bf_mm is not None and float(geom.bf_mm) > b_mm:
        mf_f = is456.fig_6__mf_flanged(b_mm / float(geom.bf_mm))
    k_span = 1.0
    if geom.support != D.SUPPORT_CANTILEVER:
        k_span = is456.cl_23_2_1_c__long_span_factor(geom.span_m)
    allowed = basic * mf_t * mf_c * mf_f * k_span
    actual = geom.span_mm / d_mm if d_mm > 0.0 else float("inf")
    return _Deflection(
        span_over_d=actual,
        allowed=allowed,
        basic=basic,
        mf_tension=mf_t,
        mf_compression=mf_c,
        mf_flanged=mf_f,
        long_span_factor=k_span,
        fs_mpa=fs,
        pt_pct=pt,
        pc_pct=pc,
        ok=actual <= allowed + 1e-9,
    )


# ---------------------------------------------------------------------------
# the resize ladder
# ---------------------------------------------------------------------------

_LADDER_REASONS = {
    "flexure": "flexure demand above the section capacity",
    "bar_fit": "the tension steel does not fit the width available",
    "max_steel": "steel above the Cl 26.5.1.1(b) maximum of 0.04 bD",
    "shear_section": "nominal shear stress above the Table 20 cap, a section limit",
    "shear_stirrups": "the stirrup ladder cannot hold the shear at a buildable spacing",
    "deflection": "span over effective depth above the Cl 23.2.1 limit",
}


def _next_width(width_seq: Sequence[float], b_mm: float) -> Optional[float]:
    """The next width in the policy sequence above the current one."""
    for candidate in sorted(float(value) for value in width_seq):
        if candidate > b_mm + 1e-6:
            return candidate
    return None


def _run_ladder(
    forces: _Forces,
    geom: BeamGeometry,
    ctx: D.DesignContext,
    result: C.DesignResult,
) -> _Attempt:
    """Walk the disclosed resize ladder: depth, then doubly, then width."""
    policy = ctx.policy
    b_mm = float(geom.b_mm)
    depth_mm = float(geom.D_mm)
    depth_cap = float(policy.beam_depth_cap(geom.D_mm, geom.span_mm))
    doubly_allowed = False
    attempt = _attempt(forces, geom, ctx, b_mm, depth_mm, doubly_allowed)
    iterations = max(1, int(policy.max_iters))
    for _ in range(iterations):
        if attempt.ok:
            return attempt
        reason = attempt.reason
        why = _LADDER_REASONS.get(reason, reason) + " at " + attempt.detail
        step = float(policy.beam_depth_step_mm)
        if reason != "bar_fit" and depth_mm + step <= depth_cap + 1e-6:
            result.add_resize({"D_mm": depth_mm}, {"D_mm": depth_mm + step}, why)
            depth_mm += step
        elif reason == "flexure" and not doubly_allowed:
            doubly_allowed = True
            result.add_resize(
                {"doubly_reinforced": False},
                {"doubly_reinforced": True},
                why + "; depth at the cap of " + ("%.0f" % depth_cap) + " mm, so compression steel is added",
            )
        else:
            wider = _next_width(policy.beam_width_seq_mm, b_mm)
            if wider is None:
                return attempt
            result.add_resize({"b_mm": b_mm}, {"b_mm": wider}, why)
            b_mm = wider
        attempt = _attempt(forces, geom, ctx, b_mm, depth_mm, doubly_allowed)
    return attempt


# ---------------------------------------------------------------------------
# emitting the result
# ---------------------------------------------------------------------------


def _emit_bars(
    result: C.DesignResult,
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
) -> None:
    """Bars, zones and development lengths onto the result."""
    span = float(geom.span_mm)
    clear = float(geom.clear_span)
    cantilever = geom.support == D.SUPPORT_CANTILEVER
    bottom = attempt.station("bottom_mid")

    def emit_layout(role: str, layout: C.BarLayout, zone: Sequence[float], ast_req: float, compression: bool = False) -> None:
        layers = layout.layer_dias_mm or ((int(layout.max_dia_mm),) * layout.count,)
        for layer_index, layer in enumerate(layers):
            counts = {}  # type: Dict[int, int]
            for dia in layer:
                counts[int(dia)] = counts.get(int(dia), 0) + 1
            for dia in sorted(counts, reverse=True):
                result.add_bar(
                    role=role,
                    count=counts[dia],
                    dia_mm=float(dia),
                    ld_mm=D.development_length_mm(dia, ctx, compression=compression),
                    zone_mm=[float(zone[0]), float(zone[1])],
                    layer=layer_index + 1,
                    ast_req_mm2=float(ast_req),
                    ast_prov_mm2=float(layout.ast_prov_mm2),
                )

    # Bottom: full length in this version, both as the sagging steel and as the
    # compression steel of the hogging sections at the supports.
    if bottom is not None:
        emit_layout("bottom_mid", bottom.layout, [0.0, span], bottom.ast_req_mm2)

    # Top at each end, curtailed at the disclosed conservative reach. An end
    # with no hogging moment carries no top group of its own: the through bars
    # below are the whole top detail there.
    for name, end in (("top_left", "a"), ("top_right", "b")):
        station = attempt.station(name)
        if station is None or station.nominal:
            continue
        if cantilever and name == "top_right":
            # A cantilever has one root: both stations carry the same moment and
            # the same full length bars, so the group is detailed once.
            continue
        ld = D.development_length_mm(station.layout.max_dia_mm, ctx)
        cutoff = D.cutoff_extension_mm(station.d_mm, station.layout.max_dia_mm)
        if cantilever:
            zone = [0.0, span]
        else:
            bar_zone = D.hogging_zone_mm(end, span, clear, ld, cutoff)
            zone = bar_zone.pair()
        emit_layout(name, station.layout, zone, station.ast_req_mm2)

    # Compression steel that the bottom bars do not already provide.
    for name in ("bottom_mid", "top_left", "top_right"):
        station = attempt.station(name)
        if station is None or station.comp_layout is None:
            continue
        role = "top_mid" if name == "bottom_mid" else ("bottom_left" if name == "top_left" else "bottom_right")
        emit_layout(role, station.comp_layout, [0.0, span], max(station.asc_req_mm2 - station.asc_credit_mm2, 0.0), compression=True)

    # Hangers, where the top steel is curtailed and no compression bar runs through.
    mid = attempt.station("bottom_mid")
    has_through_top = mid is not None and mid.comp_layout is not None
    if not cantilever and not has_through_top:
        if attempt.through_layout is None:
            attempt.through_layout = C.BarLayout(
                bars=((2, int(_HANGER_DIA_MM)),),
                ast_prov_mm2=2.0 * C.bar_area_mm2(_HANGER_DIA_MM),
                layers=1,
                d_adjust_mm=0.0,
                layer_dias_mm=((int(_HANGER_DIA_MM), int(_HANGER_DIA_MM)),),
            )
        emit_layout("top_through", attempt.through_layout, [0.0, span], 0.0)
        result.add_note(
            "two "
            + str(_HANGER_DIA_MM)
            + " mm bars run the full length at the top to carry the stirrup cage where the hogging steel is "
            "curtailed; they are not counted in any flexural or shear capacity"
        )

    # Side face steel on a deep web, Cl 26.5.1.3.
    side = attempt.side_face
    if side is not None and side.required:
        per_face = side.area_per_face_mm2
        dia = 12
        count = max(2, int(-(-per_face // C.bar_area_mm2(dia))))
        result.add_bar(
            role="side_face",
            count=2 * count,
            dia_mm=float(dia),
            ld_mm=D.development_length_mm(dia, ctx),
            zone_mm=[0.0, span],
            layer=1,
            ast_req_mm2=float(side.area_mm2),
            ast_prov_mm2=float(2 * count * C.bar_area_mm2(dia)),
            max_spacing_mm=float(side.max_spacing_mm),
        )


def _emit_stirrups(result: C.DesignResult, attempt: _Attempt, geom: BeamGeometry) -> List[D.StirrupZone]:
    """End zones of 2d at the computed spacing, the middle at maximum spacing."""
    span = float(geom.span_mm)
    zones = []  # type: List[D.StirrupZone]
    for end in attempt.shear:
        zone_length = min(2.0 * end.d_mm, span)
        if end.name == "a":
            start, stop = 0.0, zone_length
        else:
            start, stop = max(span - zone_length, 0.0), span
        zones.append(
            D.StirrupZone(
                from_mm=start,
                to_mm=stop,
                legs=end.choice.legs,
                dia_mm=end.choice.dia_mm,
                spacing_mm=end.choice.spacing_mm,
                kind="shear",
            )
        )
    if attempt.middle is not None:
        zones.append(
            D.StirrupZone(
                from_mm=0.0,
                to_mm=span,
                legs=attempt.middle.legs,
                dia_mm=attempt.middle.dia_mm,
                spacing_mm=attempt.middle.spacing_mm,
                kind="shear",
            )
        )
    return D.emit_stirrups(result, zones, span)


def _emit_checks(
    result: C.DesignResult,
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
    forces: _Forces,
) -> None:
    """Every check row, each citing a clause that is in the clause registry."""
    b_mm = attempt.b_mm
    cantilever = geom.support == D.SUPPORT_CANTILEVER
    for station in attempt.stations:
        if station.nominal:
            continue
        if cantilever and station.name == "top_right":
            # One root, one set of bars, one row: the two top stations of a
            # cantilever carry the same moment by construction.
            continue
        clause = (
            D.clause_of(is456.annex_g__doubly) if station.doubly else D.clause_of(is456.annex_g__mu_lim)
        )
        result.add_check(
            "flexure_" + station.name,
            clause,
            demand=station.mu_nmm,
            capacity=station.mu_cap_nmm,
            units="N.mm",
        )
        result.add_check(
            "min_steel_" + station.name,
            D.clause_of(is456.cl_26_5_1_1__min_tension_steel),
            demand=station.ast_min_mm2,
            capacity=station.ast_prov_mm2,
            units="mm2",
        )
        # Cl 26.5.1.1(b) caps tension steel at 0.04 bD and Cl 26.5.1.2 caps
        # compression steel at the same figure: two limits, not one sum. Steel
        # credited from another station's bars is measured on that station's own
        # row, so it is not counted twice here.
        result.add_check(
            "max_steel_" + station.name,
            D.clause_of(is456.cl_26_5_1_1b__max_steel),
            demand=station.ast_prov_mm2,
            capacity=station.ast_max_mm2,
            units="mm2",
        )
        if station.comp_layout is not None:
            result.add_check(
                "max_comp_steel_" + station.name,
                D.clause_of(is456.cl_26_5_1_1b__max_steel),
                demand=float(station.comp_layout.ast_prov_mm2),
                capacity=station.ast_max_mm2,
                units="mm2",
            )
        outer = station.layout.layer_dias_mm[0] if station.layout.layer_dias_mm else ()
        if len(outer) > 1:
            clear_spacing = (attempt.width_avail_mm - float(sum(outer))) / (len(outer) - 1)
            result.add_check(
                "crack_spacing_" + station.name,
                D.clause_of(is456.table_15__clear_spacing),
                demand=clear_spacing,
                capacity=attempt.max_clear_spacing_mm,
                units="mm",
            )

    for end in attempt.shear:
        result.add_check(
            "shear_stress_" + end.name,
            D.clause_of(is456.table_20__tau_c_max),
            demand=end.tau_v_mpa,
            capacity=end.tau_c_max_mpa,
            units="MPa",
        )
        result.add_check(
            "stirrups_" + end.name,
            D.clause_of(is456.cl_40_4__vertical_stirrups),
            demand=end.asv_per_mm_req,
            capacity=end.choice.asv_per_mm_prov,
            units="mm2/mm",
        )
        # The Cl 26.5.1.5 maximum spacing is applied inside the stirrup ladder,
        # which cannot return a spacing above it. It is disclosed as a note
        # rather than as a check row that can only ever read 1.0 or less and
        # would otherwise sit at the top of every beam's utilization.
        result.add_note(
            "end "
            + end.name
            + " stirrups: "
            + str(end.choice.legs)
            + " legs of "
            + ("%.0f" % end.choice.dia_mm)
            + " mm at "
            + ("%.0f" % end.choice.spacing_mm)
            + " mm, against the IS 456 Cl 26.5.1.5 maximum of "
            + ("%.0f" % end.choice.max_spacing_mm)
            + " mm (the lesser of 0.75d and 300 mm)"
        )

    if attempt.deflection is not None:
        result.add_check(
            "span_over_depth",
            D.clause_of(is456.cl_23_2_1__basic_ld),
            demand=attempt.deflection.span_over_d,
            capacity=attempt.deflection.allowed,
            units="-",
        )

    side = attempt.side_face
    if side is not None and side.required:
        provided = 0.0
        for bar in result.bars:
            if bar.get("role") == "side_face":
                provided = float(bar.get("ast_prov_mm2", 0.0))
        result.add_check(
            "side_face_steel",
            D.clause_of(is456.cl_26_5_1_3__side_face),
            demand=side.area_mm2,
            capacity=provided,
            units="mm2",
        )

    if forces.tu_nmm > 0.0 and attempt.torsion is not None:
        worst = max(attempt.shear, key=lambda end: end.tau_v_mpa)
        result.add_check(
            "torsion_transverse_steel",
            D.clause_of(is456.cl_41_4_3__transverse),
            demand=float(attempt.torsion.get("asv_per_mm_req", 0.0)),
            capacity=worst.choice.asv_per_mm_prov,
            units="mm2/mm",
        )

    _emit_anchorage(result, attempt, geom, ctx)


def _emit_anchorage(
    result: C.DesignResult,
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
) -> None:
    """Cl 26.2.3.3 at a simple support, with a standard hook where it is short.

    A shortfall is a detailing problem, not a section problem: the row carries
    status `warn` (disclosed, ranked, not a member failure) and a warning names
    the remedy, which is what the spec asks for.
    """
    if geom.support != D.SUPPORT_SS:
        return
    bottom = attempt.station("bottom_mid")
    if bottom is None or bottom.layout.ast_prov_mm2 <= 0.0:
        return
    shear = max((end.ve_n for end in attempt.shear), default=0.0)
    if shear <= 0.0:
        return
    dia = bottom.layout.max_dia_mm
    ld = D.development_length_mm(dia, ctx)
    m1 = D.moment_capacity_nmm(attempt.b_mm, bottom.d_mm, ctx.fck_mpa, ctx.fy_mpa, bottom.layout.ast_prov_mm2)
    lo_straight = max(0.5 * float(geom.support_width_mm) - attempt.cover_mm, 0.0)
    check = is456.cl_26_2_3_3__simple_support_anchorage(m1, shear, lo_straight, ld)
    hooked = False
    if not check.ok:
        hook = C.hook_allowance_mm(dia, 90)
        check = is456.cl_26_2_3_3__simple_support_anchorage(m1, shear, lo_straight + hook, ld)
        hooked = True
        result.add_note(
            "a standard 90 degree hook is provided on the bottom bars at the simple support so the "
            "Cl 26.2.3.3 anchorage 1.3 M1/V + Lo reaches the development length"
        )
    status = C.CHECK_PASS if check.ok else D.CHECK_WARN
    result.add_check(
        "anchorage_simple_support",
        D.clause_of(is456.cl_26_2_3_3__simple_support_anchorage),
        demand=check.required_mm,
        capacity=check.available_mm,
        units="mm",
        status=status,
    )
    if not check.ok:
        result.add_warning(
            "IS 456 Cl 26.2.3.3: the anchorage available at the simple support is "
            + ("%.0f" % check.available_mm)
            + " mm against a development length of "
            + ("%.0f" % check.required_mm)
            + " mm even with a standard hook"
            + (" (hook already counted)" if hooked else "")
            + "; use smaller bottom bars at the support or a mechanical anchorage. Reported as a detailing "
            "warning rather than a member failure, because the anchorage available depends on the support "
            "detail this layer assumes"
        )


def _emit_notes(
    result: C.DesignResult,
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
    forces: _Forces,
) -> None:
    """The conventions and simplifications this beam was designed under."""
    result.add_note(attempt.cover_note)
    result.add_note(
        "curtailment, simplified per the spec: bottom bars run the full span (the 50 percent SP 34 would "
        "curtail at 0.1 l is an optimization not applied), hogging bars run 0.3 of the clear span plus Ld "
        "plus the Cl 26.2.3.1 extension of d or 12 bar diameters with nothing stopped at 0.15 l"
    )
    result.add_note(
        "the Table 19 concrete shear strength at each end is read from the tension steel actually provided "
        "there, not from the steel the moment asked for"
    )
    result.add_note(
        "the middle of the span carries the Cl 26.5.1.6 minimum stirrups at the Cl 26.5.1.5 maximum "
        "spacing: the envelope supplies shear at the two ends only"
    )
    for text in attempt.notes:
        result.add_note(text)
    for text in attempt.warnings:
        result.add_warning(text)

    grade_warning = C.check_exposure_grade(ctx.fck_mpa, ctx.exposure)
    if grade_warning:
        result.add_warning(grade_warning)

    for station in attempt.stations:
        if not station.layout.ok:
            result.add_warning(station.name + ": " + station.layout.note)
        if station.comp_layout is not None and not station.comp_layout.ok:
            result.add_warning(station.name + " compression steel: " + station.comp_layout.note)
        if station.asc_credit_mm2 > 0.0 and station.comp_layout is None:
            result.add_note(
                station.name
                + ": the compression steel the doubly reinforced section needs is already provided by the "
                "full length bottom bars at the support"
            )
    for end in attempt.shear:
        if not end.choice.ok:
            result.add_warning("shear at end " + end.name + ": " + end.choice.note)

    if geom.support == D.SUPPORT_CANTILEVER:
        result.add_note(
            "cantilever: the Cl 23.2.1 basic span to depth ratio is 7 and the hogging steel runs the full "
            "length into the support"
        )
        if geom.span_mm > CANTILEVER_REFUSAL_SPAN_MM + 1e-6:
            result.add_warning(
                "cantilever span "
                + ("%.0f" % geom.span_mm)
                + " mm is past the "
                + ("%.0f" % CANTILEVER_REFUSAL_SPAN_MM)
                + " mm placement refusal (disclosure E_CANTILEVER_SPAN); it should not have reached design, "
                "and it is designed here rather than dropped"
            )
        if geom.span_m > 10.0:
            result.add_warning(
                "cantilever span above 10 m: IS 456 Cl 23.2.1(c) asks for a calculated deflection there, "
                "and the long span factor is not applicable to a cantilever"
            )
    if forces.tu_nmm > 0.0 and attempt.side_face is not None and attempt.side_face.required:
        result.add_note(
            "side face steel is triggered at an overall depth over 450 mm because the section carries torsion "
            "(IS 456 Cl 26.5.1.3)"
        )


def _ductile_state(
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
    forces: _Forces,
    result: C.DesignResult,
) -> Dict[str, Any]:
    """The private record `detailing.apply_13920` needs. Never serialized."""
    bottom = attempt.station("bottom_mid")
    top_a = attempt.station("top_left")
    top_b = attempt.station("top_right")
    dias = [float(bar.get("dia_mm", 0.0)) for bar in result.bars if bar.get("role") != "side_face"]
    top_d = max((station.d_mm for station in attempt.stations if station.face == "top"), default=0.0)
    state = {
        "b_mm": attempt.b_mm,
        "D_mm": attempt.D_mm,
        "d_mm": min(station.d_mm for station in attempt.stations),
        "cover_mm": attempt.cover_mm,
        "span_mm": float(geom.span_mm),
        "clear_span_mm": float(geom.clear_span),
        "fck_mpa": ctx.fck_mpa,
        "fy_mpa": ctx.fy_mpa,
        "fy_stirrup_mpa": ctx.fy_stirrup_mpa,
        "vu_a_n": attempt.shear[0].ve_n if attempt.shear else forces.vu_a_n,
        "vu_b_n": attempt.shear[1].ve_n if len(attempt.shear) > 1 else forces.vu_b_n,
        "tau_c_a_mpa": attempt.shear[0].tau_c_mpa if attempt.shear else 0.0,
        "tau_c_b_mpa": attempt.shear[1].tau_c_mpa if len(attempt.shear) > 1 else 0.0,
        "dia_long_min_mm": min(dias) if dias else float(_HANGER_DIA_MM),
        "dia_long_max_mm": max(dias) if dias else float(_HANGER_DIA_MM),
        "mu_cap_hog_a_nmm": top_a.mu_cap_nmm if top_a is not None and not top_a.nominal else 0.0,
        "mu_cap_hog_b_nmm": top_b.mu_cap_nmm if top_b is not None and not top_b.nominal else 0.0,
        "mu_cap_sag_nmm": bottom.mu_cap_nmm if bottom is not None else 0.0,
        "ast_bot_mm2": bottom.ast_prov_mm2 if bottom is not None else 0.0,
    }
    # A face is offered to the ratio rules only where it carries bars of its
    # own: at an end with no hogging moment the top steel IS the through bars,
    # and offering both would ask for the minimum ratio twice over.
    if top_a is not None and not top_a.nominal:
        state["ast_top_a_mm2"] = top_a.ast_prov_mm2
    if top_b is not None and not top_b.nominal:
        state["ast_top_b_mm2"] = top_b.ast_prov_mm2
    if attempt.through_layout is not None and top_d > 0.0:
        state["ast_top_through_mm2"] = float(attempt.through_layout.ast_prov_mm2)
        state["mu_cap_top_through_nmm"] = D.moment_capacity_nmm(
            attempt.b_mm,
            top_d,
            ctx.fck_mpa,
            ctx.fy_mpa,
            attempt.through_layout.ast_prov_mm2,
        )
    return state


def _steel_setter(
    result: C.DesignResult,
    attempt: _Attempt,
    geom: BeamGeometry,
    ctx: D.DesignContext,
):
    """A callback the ductile overlay uses to add bars to one role."""

    def set_steel(role: str, ast_req_mm2: float) -> Dict[str, Any]:
        prefs = C.BarPrefs(
            dias_mm=tuple(dia for dia in C.MAIN_DIAS if dia >= _MIN_MAIN_DIA_MM),
            min_dia_mm=_MIN_MAIN_DIA_MM,
            min_bars_per_layer=2,
            max_bars_per_layer=6,
            max_layers=2,
            agg_mm=ctx.agg_mm,
            max_clear_spacing_mm=attempt.max_clear_spacing_mm,
        )
        if role == "top_through":
            current = attempt.through_layout
            if current is None:
                return {}
            layout = C.pick_bars(max(float(ast_req_mm2), current.ast_prov_mm2), attempt.width_avail_mm, prefs)
            if layout.ast_prov_mm2 <= current.ast_prov_mm2 + 1e-6:
                return {"ast_prov_mm2": current.ast_prov_mm2, "label": current.label, "changed": False}
            attempt.through_layout = layout
            _rewrite_bars(result, "top_through", layout, geom, ctx, 0.0)
            return {"ast_prov_mm2": layout.ast_prov_mm2, "label": layout.label, "changed": True}
        station = attempt.station(role)
        if station is None:
            return {}
        target = max(float(ast_req_mm2), station.layout.ast_prov_mm2)
        layout = C.pick_bars(target, attempt.width_avail_mm, prefs)
        if layout.ast_prov_mm2 <= station.layout.ast_prov_mm2 + 1e-6:
            return {
                "ast_prov_mm2": station.layout.ast_prov_mm2,
                "mu_cap_nmm": station.mu_cap_nmm,
                "label": station.layout.label,
                "changed": False,
            }
        station.layout = layout
        station.d_mm = (
            C.effective_depth(
                attempt.D_mm,
                attempt.cover_mm,
                attempt.stirrup_dia_mm,
                layout.max_dia_mm,
                layers=1,
                agg_mm=ctx.agg_mm,
            )
            - layout.d_adjust_mm
        )
        station.mu_cap_nmm = D.moment_capacity_nmm(
            attempt.b_mm,
            station.d_mm,
            ctx.fck_mpa,
            ctx.fy_mpa,
            layout.ast_prov_mm2,
            station.asc_prov_mm2 if station.asc_req_mm2 > 0.0 else 0.0,
            station.dprime_mm if station.asc_req_mm2 > 0.0 else 0.0,
        )
        _rewrite_bars(result, role, layout, geom, ctx, station.ast_req_mm2)
        return {
            "ast_prov_mm2": layout.ast_prov_mm2,
            "mu_cap_nmm": station.mu_cap_nmm,
            "label": layout.label,
            "changed": True,
        }

    return set_steel


def _rewrite_bars(
    result: C.DesignResult,
    role: str,
    layout: C.BarLayout,
    geom: BeamGeometry,
    ctx: D.DesignContext,
    ast_req_mm2: float,
) -> None:
    """Replace the bar entries of one role with a new layout, zone unchanged."""
    existing = [bar for bar in result.bars if bar.get("role") == role]
    if not existing:
        return
    zone = existing[0].get("zone_mm", [0.0, float(geom.span_mm)])
    ast_req = float(existing[0].get("ast_req_mm2", ast_req_mm2))
    result.bars = [bar for bar in result.bars if bar.get("role") != role]
    layers = layout.layer_dias_mm or ((int(layout.max_dia_mm),) * layout.count,)
    for layer_index, layer in enumerate(layers):
        counts = {}  # type: Dict[int, int]
        for dia in layer:
            counts[int(dia)] = counts.get(int(dia), 0) + 1
        for dia in sorted(counts, reverse=True):
            result.add_bar(
                role=role,
                count=counts[dia],
                dia_mm=float(dia),
                ld_mm=D.development_length_mm(dia, ctx),
                zone_mm=[float(zone[0]), float(zone[1])],
                layer=layer_index + 1,
                ast_req_mm2=ast_req,
                ast_prov_mm2=float(layout.ast_prov_mm2),
            )


# ---------------------------------------------------------------------------
# the public entry point
# ---------------------------------------------------------------------------


#: Effective depth below which a beam is not a beam: the cover stack has eaten
#: the section and no arithmetic downstream would mean anything.
_MIN_EFFECTIVE_DEPTH_MM = 50.0


def _refuse_impossible_section(
    result: C.DesignResult,
    geom: BeamGeometry,
    ctx: D.DesignContext,
) -> Optional[C.DesignResult]:
    """A fully populated refusal when the cover stack leaves no effective depth.

    Placement never produces one; a hand built or corrupted payload can. The
    refusal is a result like any other rather than an exception, so a batch
    carrying one bad member still comes back.
    """
    cover = C.resolve_cover("beam", ctx.exposure, ctx.fire_rating_h, 0.0)
    d_mm = C.effective_depth(
        geom.D_mm, cover.cover_mm, _BASE_STIRRUP_DIA_MM, float(_MIN_MAIN_DIA_MM), layers=1, agg_mm=ctx.agg_mm
    )
    if d_mm >= _MIN_EFFECTIVE_DEPTH_MM:
        return None
    needed = geom.D_mm - d_mm + _MIN_EFFECTIVE_DEPTH_MM
    result.section = {
        "b_mm": float(geom.b_mm),
        "D_mm": float(geom.D_mm),
        "d_mm": float(d_mm),
        "cover_mm": float(cover.cover_mm),
        "length_mm": float(geom.span_mm),
        "clear_span_mm": float(geom.clear_span),
        "support": geom.support,
        "stirrup_dia_mm": _BASE_STIRRUP_DIA_MM,
    }
    result.materials = C.materials_block(ctx.concrete, ctx.steel)
    result.add_note(cover.note)
    return result.fail_with(
        "section_depth",
        reason=(
            "an overall depth of "
            + ("%.0f" % geom.D_mm)
            + " mm leaves an effective depth of "
            + ("%.0f" % d_mm)
            + " mm after the cover stack; at least "
            + ("%.0f" % needed)
            + " mm is needed before any IS 456 arithmetic is meaningful, so nothing is detailed"
        ),
        clause=D.clause_of(is456.table_16__nominal_cover),
        demand=needed,
        capacity=float(geom.D_mm),
        units="mm",
    )


def design_beam(forces: Any, geom: Any, ctx: Any = None) -> C.DesignResult:
    """Design one RC beam. Always returns a fully populated DesignResult.

    `forces` is an `analysis.BeamForces` (or a mapping with its field names),
    `geom` a `BeamGeometry` (or a mapping with b_mm, D_mm and span_mm), `ctx` a
    `detailing.DesignContext` or the api options block.
    """
    context = D.as_context(ctx)
    geometry = as_beam_geometry(geom)
    envelope = _as_forces(forces)
    result = C.DesignResult(element_id=geometry.element_id, element_type="beam")
    entries = []  # type: List[TraceEntry]
    with trace_into(entries):
        refusal = _refuse_impossible_section(result, geometry, context)
        if refusal is not None:
            result.trace = entries
            return refusal
        attempt = _run_ladder(envelope, geometry, context, result)
        result.section = {
            "b_mm": attempt.b_mm,
            "D_mm": attempt.D_mm,
            "d_mm": min(station.d_mm for station in attempt.stations),
            "cover_mm": attempt.cover_mm,
            "length_mm": float(geometry.span_mm),
            "clear_span_mm": float(geometry.clear_span),
            "support": geometry.support,
            "stirrup_dia_mm": attempt.stirrup_dia_mm,
        }
        result.materials = C.materials_block(context.concrete, context.steel)
        _emit_bars(result, attempt, geometry, context)
        _emit_stirrups(result, attempt, geometry)
        _emit_checks(result, attempt, geometry, context, envelope)
        _emit_notes(result, attempt, geometry, context, envelope)
        result.extras["flexure"] = [station.to_dict(attempt.b_mm) for station in attempt.stations]
        result.extras["shear"] = [end.to_dict() for end in attempt.shear]
        if attempt.deflection is not None:
            result.extras["serviceability"] = attempt.deflection.to_dict()
        if attempt.torsion is not None:
            result.extras["torsion"] = dict(attempt.torsion)
        if envelope.combo_tags:
            result.add_note(
                "governing load combinations from the envelope: "
                + ", ".join(name + " by " + combo for name, combo in envelope.combo_tags)
            )

        if not attempt.ok:
            result.fail_with(
                _governing_name(attempt),
                reason=(
                    "the resize ladder is exhausted: "
                    + _LADDER_REASONS.get(attempt.reason, attempt.reason)
                    + " at "
                    + attempt.detail
                    + "; the last section tried is reported in full"
                ),
            )
            if D.ductile_required(context):
                result.add_note(
                    "the IS 13920 overlay did not run: it applies to a member that has passed IS 456, and "
                    "this one has not, so the ductile rules would be describing a section that is not built"
                )
        elif D.ductile_required(context):
            state = _ductile_state(attempt, geometry, context, envelope, result)
            state["set_steel"] = _steel_setter(result, attempt, geometry, context)
            D.apply_13920(result, "beam", context, state)
            result.extras["flexure"] = [station.to_dict(attempt.b_mm) for station in attempt.stations]
        elif context.is13920 == "off":
            result.add_note("IS 13920 ductile detailing was switched off in the options for this run")
        else:
            result.add_note(
                "IS 13920 ductile detailing does not apply here (seismic zone "
                + str(context.zone)
                + ", "
                + str(context.frame)
                + " frame); IS 456 detailing only"
            )
    result.trace = entries
    return result.finalize()


def _governing_name(attempt: _Attempt) -> str:
    """The check row name the failing reason belongs to."""
    reason = attempt.reason
    if reason in ("flexure", "bar_fit", "max_steel"):
        station = attempt.detail if attempt.detail else "bottom_mid"
        prefix = "max_steel_" if reason == "max_steel" else "flexure_"
        return prefix + station
    if reason == "shear_section":
        return "shear_stress_" + attempt.detail.replace("end ", "")
    if reason == "shear_stirrups":
        return "stirrups_" + attempt.detail.replace("end ", "")
    if reason == "deflection":
        return "span_over_depth"
    return reason or "flexure_bottom_mid"
