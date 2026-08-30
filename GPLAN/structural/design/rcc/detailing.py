"""The shared RC detailing engine: context, zones, schedules, ductile overlay.

Three jobs, none of which invents code arithmetic of its own:

1. **Context.** `DesignContext` is the one options block every RC designer reads
   (materials, exposure, fire, aggregate, seismic zone and frame, resize
   policy). `as_context` accepts the api options mapping verbatim, another
   agent's context object, or nothing at all, so a designer never parses
   options twice.
2. **Assembly.** Development lengths, curtailment zones, the stirrup ladder and
   `merge_stirrup_zones`: the arithmetic is IS 456's, pulled from
   `codes/is456.py`; what lives here is the bookkeeping that turns per-station
   answers into one schedule a detailer can build.
3. **The IS 13920 overlay.** `apply_13920(result, kind, ctx, state)` runs AFTER
   a member has passed IS 456 and may re-enter stirrup or hoop design only: it
   never changes a section size, because that belongs to the designer's own
   resize ladder. Section geometry that IS 13920 refuses is disclosed as a check
   row and a warning, and the strong column ratio is computed and FLAGGED as
   the referral `joint_check_manual`, never auto-resized. One exemption, stated
   because it is the only place the overlay is not applied whole: a column whose
   state carries `confinement_column` is an IS 4326 confining (tie) column, not
   a frame member, and Cl 7.1 column geometry is not read against it. The
   skipped clause is disclosed on the result as a NOTE with its reason; nothing
   else about the overlay changes, and a frame column is never exempt.

Units are the design layer's: N, mm, MPa, N.mm. Every public field carries its
unit suffix.

Check row statuses. `pass` and `fail` carry their usual meaning and a failing
row fails the member. One further word is used deliberately: `warn`, for a row
whose remedy is a detailing action the design layer is not empowered to take
(the anchorage available at a simple support depends on the real support
detail; the strong column ratio is a joint the engineer must check). A `warn`
row is fully disclosed, is ranked in `utilization_max` like any other, and does
not fail the member. Both cases are named in the spec as warnings rather than
failures, and `DesignResult.finalize` only fails on `fail`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ...codes import is13920, is456
from .. import common as C

__all__ = [
    # context
    "SUPPORTS",
    "SUPPORT_SS",
    "SUPPORT_CONTINUOUS",
    "SUPPORT_CANTILEVER",
    "normalize_support",
    "DesignContext",
    "as_context",
    "ductile_required",
    # clause plumbing
    "CHECK_WARN",
    "clause_of",
    "read_field",
    "drop_checks",
    # flexural capacity of a provided section
    "ast_balanced_mm2",
    "moment_capacity_nmm",
    # zones and development lengths
    "development_length_mm",
    "cutoff_extension_mm",
    "hogging_zone_mm",
    "BarZone",
    # stirrup and tie schedules
    "DEFAULT_STIRRUP_LADDER",
    "SPACING_MODULE_MM",
    "SPACING_FLOOR_MM",
    "StirrupChoice",
    "StirrupZone",
    "choose_stirrups",
    "merge_stirrup_zones",
    "emit_stirrups",
    # ductile overlay
    "apply_13920",
]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

SUPPORT_SS = "ss"
SUPPORT_CONTINUOUS = "continuous"
SUPPORT_CANTILEVER = "cantilever"

#: The support words a beam geometry may carry. IS 456 Cl 23.2.1 knows the same
#: three, and `is456.cl_23_2_1__basic_ld` resolves the aliases below itself.
SUPPORTS = (SUPPORT_SS, SUPPORT_CONTINUOUS, SUPPORT_CANTILEVER)

_SUPPORT_ALIASES = {
    "ss": SUPPORT_SS,
    "simply_supported": SUPPORT_SS,
    "simple": SUPPORT_SS,
    "simple_support": SUPPORT_SS,
    "pinned": SUPPORT_SS,
    "continuous": SUPPORT_CONTINUOUS,
    "cont": SUPPORT_CONTINUOUS,
    "fixed": SUPPORT_CONTINUOUS,
    "cantilever": SUPPORT_CANTILEVER,
    "cant": SUPPORT_CANTILEVER,
}

#: A check whose remedy is a detailing action, not a section change. Disclosed,
#: ranked, and deliberately not a failure (see the module docstring).
CHECK_WARN = "warn"

#: IS 13920 modes an options block may ask for.
IS13920_MODES = ("auto", "on", "off")

_TOL = 1e-9


def _word(value: Any) -> str:
    """Vocabulary word normalised the way codes/is456.py normalises one."""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def normalize_support(support: Any) -> str:
    """One of ss, continuous or cantilever, or a ValueError listing the three."""
    key = _word(support)
    if key not in _SUPPORT_ALIASES:
        raise ValueError("support unknown: " + repr(support) + "; known: " + ", ".join(SUPPORTS))
    return _SUPPORT_ALIASES[key]


def clause_of(func: Callable) -> str:
    """The registry id of a decorated clause callable, "IS456:2000 40.1".

    Every check row cites its clause through this helper, so a row can only
    carry a string that `codes/trace.CLAUSE_REGISTRY` actually holds.
    """
    meta = getattr(func, "clause_meta", None)
    if meta is None:
        raise ValueError("not a @clause callable: " + repr(getattr(func, "__name__", func)))
    return meta.clause_id


# ---------------------------------------------------------------------------
# design context (the api options block, read once)
# ---------------------------------------------------------------------------


def read_field(source: Any, names: Sequence[str], default: Any = None) -> Any:
    """First present value among `names`, from a mapping or an object."""
    if source is None:
        return default
    if isinstance(source, Mapping):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        return default
    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value
    return default


@dataclass(frozen=True)
class DesignContext:
    """Materials and code options shared by every RC member of one run."""

    concrete: C.Concrete = C.Concrete(fck_mpa=25.0)
    steel: C.RebarSteel = C.RebarSteel(fy_mpa=500.0)
    stirrup_steel: Optional[C.RebarSteel] = None
    exposure: str = "moderate"
    fire_rating_h: float = 0.0
    agg_mm: float = C.DEFAULT_AGG_MM
    zone: str = "III"
    frame: str = "OMRF"
    is13920: str = "auto"
    redistribution_pct: float = 0.0
    policy: C.ResizePolicy = C.ResizePolicy()

    @property
    def fck_mpa(self) -> float:
        return float(self.concrete.fck_mpa)

    @property
    def fy_mpa(self) -> float:
        return float(self.steel.fy_mpa)

    @property
    def fy_stirrup_mpa(self) -> float:
        """Shear reinforcement grade; the main grade unless one was stated."""
        return float(self.steel.fy_mpa if self.stirrup_steel is None else self.stirrup_steel.fy_mpa)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fck_mpa": float(self.concrete.fck_mpa),
            "fy_mpa": float(self.steel.fy_mpa),
            "fy_stirrup_mpa": self.fy_stirrup_mpa,
            "exposure": self.exposure,
            "fire_rating_h": float(self.fire_rating_h),
            "aggregate_mm": float(self.agg_mm),
            "zone": self.zone,
            "frame": self.frame,
            "is13920": self.is13920,
            "redistribution_pct": float(self.redistribution_pct),
        }


def as_context(source: Any = None) -> DesignContext:
    """A DesignContext from nothing, from one, from the api options, or a duck.

    The api options block (spec section 11) is accepted verbatim:
    `{materials:{fck, fy}, exposure, fire_rating_h, aggregate_mm,
    seismic:{zone, frame}, is13920, resize_policy}`. Anything else that carries
    the same attribute names works too, so a sibling designer's own context
    object does not have to be converted first.
    """
    if source is None:
        return DesignContext()
    if isinstance(source, DesignContext):
        return source

    materials = read_field(source, ("materials",), None)
    seismic = read_field(source, ("seismic",), None)
    base = DesignContext()

    concrete = read_field(source, ("concrete",), None)
    if not isinstance(concrete, C.Concrete):
        fck = read_field(materials, ("fck", "fck_mpa"), None)
        if fck is None:
            fck = read_field(source, ("fck_mpa", "fck"), base.concrete.fck_mpa)
        concrete = C.Concrete.from_grade(fck)

    steel = read_field(source, ("steel",), None)
    if not isinstance(steel, C.RebarSteel):
        fy = read_field(materials, ("fy", "fy_mpa"), None)
        if fy is None:
            fy = read_field(source, ("fy_mpa", "fy"), base.steel.fy_mpa)
        steel = C.RebarSteel.from_grade(fy)

    stirrup_steel = read_field(source, ("stirrup_steel",), None)
    if stirrup_steel is None:
        fy_stirrup = read_field(materials, ("fy_stirrup", "fy_stirrup_mpa"), None)
        if fy_stirrup is None:
            fy_stirrup = read_field(source, ("fy_stirrup_mpa", "fy_stirrup"), None)
        if fy_stirrup is not None:
            stirrup_steel = C.RebarSteel.from_grade(fy_stirrup)
    elif not isinstance(stirrup_steel, C.RebarSteel):
        stirrup_steel = C.RebarSteel.from_grade(stirrup_steel)

    policy = read_field(source, ("resize_policy", "policy"), None)
    if isinstance(policy, Mapping):
        policy = C.ResizePolicy.from_dict(policy)
    elif not isinstance(policy, C.ResizePolicy):
        policy = base.policy

    mode = _word(read_field(source, ("is13920", "ductile"), base.is13920))
    if mode in ("true", "yes"):
        mode = "on"
    elif mode in ("false", "no", "none"):
        mode = "off"
    if mode not in IS13920_MODES:
        raise ValueError("is13920 must be one of " + ", ".join(IS13920_MODES) + ", got " + repr(mode))

    zone = read_field(seismic, ("zone",), None)
    if zone is None:
        zone = read_field(source, ("zone", "seismic_zone"), base.zone)
    frame = read_field(seismic, ("frame", "system"), None)
    if frame is None:
        frame = read_field(source, ("frame", "frame_type"), base.frame)

    return DesignContext(
        concrete=concrete,
        steel=steel,
        stirrup_steel=stirrup_steel,
        exposure=_word(read_field(source, ("exposure",), base.exposure)),
        fire_rating_h=float(read_field(source, ("fire_rating_h", "fire_rating", "fire"), base.fire_rating_h)),
        agg_mm=float(read_field(source, ("aggregate_mm", "agg_mm"), base.agg_mm)),
        zone=is13920.normalize_zone(zone),
        frame=is13920.normalize_frame(frame),
        is13920=mode,
        redistribution_pct=float(read_field(source, ("redistribution_pct",), base.redistribution_pct)),
        policy=policy,
    )


def ductile_required(ctx: DesignContext) -> bool:
    """Whether the IS 13920 overlay runs: the mode, else the code's predicate."""
    mode = _word(ctx.is13920)
    if mode == "on":
        return True
    if mode == "off":
        return False
    return bool(is13920.is13920_applies(ctx.zone, ctx.frame))


# ---------------------------------------------------------------------------
# flexural capacity of a section that already carries its steel
# ---------------------------------------------------------------------------


def ast_balanced_mm2(b_mm: float, d_mm: float, fck_mpa: float, fy_mpa: float) -> float:
    """Tension steel that puts the neutral axis exactly at xu,max, mm2.

    From the Annex G limiting neutral axis depth and horizontal equilibrium
    0.36 fck b xu = 0.87 fy Ast: no new rule, just the balance written out.
    """
    ratio = is456.annex_g__xu_max_over_d(fy_mpa)
    return 0.36 * float(fck_mpa) * float(b_mm) * ratio * float(d_mm) / (is456.GAMMA_S_FACTOR * float(fy_mpa))


def moment_capacity_nmm(
    b_mm: float,
    d_mm: float,
    fck_mpa: float,
    fy_mpa: float,
    ast_mm2: float,
    asc_mm2: float = 0.0,
    dprime_mm: float = 0.0,
) -> float:
    """Moment of resistance of a rectangular section with the steel it has, N.mm.

    Under-reinforced, IS 456 Annex G-1.1(b) as printed:
    Mu = 0.87 fy Ast d (1 - Ast fy / (b d fck)), which is exactly the relation
    `annex_g__ast_singly` inverts. Reading the capacity off the same equation the
    steel was sized from is what keeps a section that provides the area the
    quadratic asked for from reading a fraction of a percent short and buying
    itself a resize it does not need. It is capped at Annex G's Mu,lim.

    At or beyond the balanced steel the singly reinforced part is Mu,lim and any
    compression steel adds the second couple Asc (fsc - 0.446 fck)(d - d'),
    limited by the excess tension steel that balances it, which is what makes
    the pair a couple at all.
    """
    b = float(b_mm)
    d = float(d_mm)
    fck = float(fck_mpa)
    fy = float(fy_mpa)
    ast = max(float(ast_mm2), 0.0)
    asc = max(float(asc_mm2), 0.0)
    if b <= 0.0 or d <= 0.0 or ast <= 0.0:
        return 0.0
    balanced = ast_balanced_mm2(b, d, fck, fy)
    capacity = is456.annex_g__mu_lim(b, d, fck, fy)
    if ast <= balanced + _TOL:
        return min(is456.GAMMA_S_FACTOR * fy * ast * d * (1.0 - ast * fy / (b * d * fck)), capacity)
    if asc <= 0.0 or dprime_mm <= 0.0 or dprime_mm >= d:
        return capacity
    fsc = is456.sp16_table_f__fsc(fy, float(dprime_mm) / d)
    net = fsc - is456.CONCRETE_DESIGN_FACTOR * fck
    if net <= 0.0:
        return capacity
    force_comp = asc * net
    force_excess_tension = (ast - balanced) * is456.GAMMA_S_FACTOR * fy
    return capacity + min(force_comp, force_excess_tension) * (d - float(dprime_mm))


# ---------------------------------------------------------------------------
# development lengths, cutoffs and bar zones
# ---------------------------------------------------------------------------


class BarZone(NamedTuple):
    """One bar group's run along the member, mm from the member's a end."""

    role: str
    from_mm: float
    to_mm: float

    @property
    def length_mm(self) -> float:
        return max(self.to_mm - self.from_mm, 0.0)

    def pair(self) -> List[float]:
        return [float(self.from_mm), float(self.to_mm)]


def development_length_mm(dia_mm: float, ctx: DesignContext, compression: bool = False) -> float:
    """IS 456 Cl 26.2.1 development length of one bar, mm."""
    return float(
        is456.cl_26_2_1__ld(
            float(dia_mm),
            ctx.fy_mpa,
            ctx.fck_mpa,
            deformed=True,
            compression=bool(compression),
        )
    )


def cutoff_extension_mm(d_mm: float, dia_mm: float) -> float:
    """IS 456 Cl 26.2.3.1 extension past a theoretical cutoff: d or 12 bar diameters.

    No clause callable owns this one in `codes/is456.py`; it is a length rule,
    not a stress rule, and it is baked into the zone lengths below.
    """
    return max(float(d_mm), 12.0 * float(dia_mm))


def hogging_zone_mm(
    end: str,
    span_mm: float,
    clear_span_mm: float,
    ld_mm: float,
    cutoff_mm: float,
    curtail_fraction: float = 0.3,
) -> BarZone:
    """Run of the top steel at one end, mm from the member's a end.

    SP 34 curtails half the hogging steel at 0.15 l and the rest at 0.25 l plus
    a development length. This version curtails nothing: every top bar runs the
    conservative 0.3 l plus Ld plus the Cl 26.2.3.1 extension, which is the
    simplification the spec names and the designer discloses as a note.
    """
    reach = min(
        float(span_mm),
        float(curtail_fraction) * float(clear_span_mm) + float(ld_mm) + float(cutoff_mm),
    )
    if _word(end) in ("a", "left", "start", "0"):
        return BarZone(role="top_left", from_mm=0.0, to_mm=reach)
    return BarZone(role="top_right", from_mm=max(float(span_mm) - reach, 0.0), to_mm=float(span_mm))


# ---------------------------------------------------------------------------
# stirrup and tie schedules
# ---------------------------------------------------------------------------

#: (legs, diameter) in ascending area, the order a detailer would try them in.
DEFAULT_STIRRUP_LADDER = ((2, 8), (2, 10), (2, 12), (3, 10), (3, 12), (4, 12))

#: Stirrup spacings are rounded DOWN to this module, so a rounded spacing never
#: provides less steel than the calculation asked for.
SPACING_MODULE_MM = 5.0

#: Below this a two legged stirrup cage cannot be built cleanly; the ladder
#: moves to a bigger diameter or more legs instead of packing them tighter.
SPACING_FLOOR_MM = 75.0


class StirrupChoice(NamedTuple):
    """A stirrup, tie or hoop set: what to build and what it provides."""

    legs: int
    dia_mm: int
    spacing_mm: float
    asv_mm2: float
    asv_per_mm_prov: float
    asv_per_mm_req: float
    max_spacing_mm: float
    ok: bool
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "legs": int(self.legs),
            "dia_mm": float(self.dia_mm),
            "spacing_mm": float(self.spacing_mm),
            "asv_mm2": float(self.asv_mm2),
            "asv_per_mm_prov": float(self.asv_per_mm_prov),
            "asv_per_mm_req": float(self.asv_per_mm_req),
            "max_spacing_mm": float(self.max_spacing_mm),
            "ok": bool(self.ok),
            "note": self.note,
        }


def choose_stirrups(
    asv_per_mm_req: float,
    max_spacing_mm: float,
    ladder: Sequence[Tuple[int, int]] = DEFAULT_STIRRUP_LADDER,
    min_dia_mm: float = 0.0,
    spacing_floor_mm: float = SPACING_FLOOR_MM,
    module_mm: float = SPACING_MODULE_MM,
    spacing_cap_mm: Optional[float] = None,
) -> StirrupChoice:
    """The lightest ladder entry whose spacing clears the constructability floor.

    `asv_per_mm_req` is the required Asv/sv (IS 456 Cl 40.4 against the minimum
    of Cl 26.5.1.6, plus the Cl 41.4.3 torsion demand where there is one).
    `max_spacing_mm` is the Cl 26.5.1.5 cap; `spacing_cap_mm` tightens it
    further when a ductile hoop rule applies. Never raises: when even the
    heaviest cage cannot hold the demand at the floor spacing, the heaviest is
    returned with `ok=False` and a note.
    """
    required = max(float(asv_per_mm_req), 0.0)
    cap = float(max_spacing_mm)
    if spacing_cap_mm is not None:
        cap = min(cap, float(spacing_cap_mm))
    cap = max(cap, module_mm)
    # A shallow member can have a code cap below the constructability floor; the
    # code cap wins, and the floor relaxes to it rather than failing the member.
    floor = min(float(spacing_floor_mm), cap)

    usable = [pair for pair in ladder if float(pair[1]) >= float(min_dia_mm) - _TOL]
    if not usable:
        usable = [max(ladder, key=lambda pair: pair[1] * pair[0])]

    last = None  # type: Optional[StirrupChoice]
    for legs, dia in usable:
        asv = legs * C.bar_area_mm2(dia)
        spacing_raw = cap if required <= 0.0 else asv / required
        spacing = C.round_down_mm(min(spacing_raw, cap), module_mm)
        spacing = max(spacing, module_mm)
        choice = StirrupChoice(
            legs=int(legs),
            dia_mm=int(dia),
            spacing_mm=spacing,
            asv_mm2=asv,
            asv_per_mm_prov=asv / spacing,
            asv_per_mm_req=required,
            max_spacing_mm=cap,
            ok=True,
            note="",
        )
        if spacing >= floor - _TOL:
            return choice
        last = choice

    heaviest = last if last is not None else None
    if heaviest is None:  # pragma: no cover - usable is never empty
        legs, dia = usable[-1]
        asv = legs * C.bar_area_mm2(dia)
        heaviest = StirrupChoice(
            legs=int(legs),
            dia_mm=int(dia),
            spacing_mm=floor,
            asv_mm2=asv,
            asv_per_mm_prov=asv / floor,
            asv_per_mm_req=required,
            max_spacing_mm=cap,
            ok=False,
            note="",
        )
    return StirrupChoice(
        legs=heaviest.legs,
        dia_mm=heaviest.dia_mm,
        spacing_mm=heaviest.spacing_mm,
        asv_mm2=heaviest.asv_mm2,
        asv_per_mm_prov=heaviest.asv_mm2 / heaviest.spacing_mm,
        asv_per_mm_req=required,
        max_spacing_mm=cap,
        ok=False,
        note=(
            "shear demand needs "
            + ("%.3f" % required)
            + " mm2/mm; the heaviest cage in the ladder gives "
            + str(heaviest.legs)
            + " legs of "
            + str(heaviest.dia_mm)
            + " mm at "
            + ("%.0f" % heaviest.spacing_mm)
            + " mm, below the "
            + ("%.0f" % floor)
            + " mm floor"
        ),
    )


class StirrupZone(NamedTuple):
    """One run of stirrups, ties or hoops along a member, mm from the a end."""

    from_mm: float
    to_mm: float
    legs: int
    dia_mm: int
    spacing_mm: float
    kind: str = "shear"
    first_mm: float = 0.0

    @property
    def length_mm(self) -> float:
        return max(self.to_mm - self.from_mm, 0.0)

    def same_set(self, other: "StirrupZone") -> bool:
        return (
            int(self.legs) == int(other.legs)
            and int(self.dia_mm) == int(other.dia_mm)
            and abs(float(self.spacing_mm) - float(other.spacing_mm)) <= 1e-6
            and str(self.kind) == str(other.kind)
        )


#: Where two zones cover the same millimetre the tighter set wins; this ranks
#: the tie break so the merge is a total order and therefore deterministic.
_KIND_RANK = {"confining": 0, "hoop": 0, "shear": 1, "tie": 2, "torsion": 1}


def _zone_rank(zone: StirrupZone, index: int) -> Tuple[Any, ...]:
    return (
        float(zone.spacing_mm),
        -int(zone.dia_mm),
        -int(zone.legs),
        _KIND_RANK.get(str(zone.kind), 9),
        index,
    )


def merge_stirrup_zones(
    zones: Sequence[StirrupZone],
    length_mm: Optional[float] = None,
    tol: float = 1e-6,
) -> List[StirrupZone]:
    """Overlapping zones resolved into one schedule, tightest spacing winning.

    End zones, ductile hoop zones and the maximum spacing middle are written
    independently by the rules that own them and then handed here. The sweep
    is over the union of every boundary, so the result is a partition of the
    member with no gaps, no overlaps and no accidental dependence on the order
    the zones were appended in.
    """
    clipped = []  # type: List[StirrupZone]
    for zone in zones:
        start = float(zone.from_mm)
        end = float(zone.to_mm)
        if length_mm is not None:
            start = min(max(start, 0.0), float(length_mm))
            end = min(max(end, 0.0), float(length_mm))
        if end - start <= tol:
            continue
        clipped.append(zone._replace(from_mm=start, to_mm=end))
    if not clipped:
        return []

    edges = sorted({round(value, 6) for zone in clipped for value in (zone.from_mm, zone.to_mm)})
    out = []  # type: List[StirrupZone]
    for index in range(len(edges) - 1):
        low = edges[index]
        high = edges[index + 1]
        if high - low <= tol:
            continue
        covering = [
            (position, zone)
            for position, zone in enumerate(clipped)
            if zone.from_mm <= low + tol and zone.to_mm >= high - tol
        ]
        if not covering:
            continue
        position, winner = min(covering, key=lambda pair: _zone_rank(pair[1], pair[0]))
        first = winner.first_mm if abs(winner.from_mm - low) <= tol else 0.0
        piece = winner._replace(from_mm=low, to_mm=high, first_mm=first)
        if out and out[-1].same_set(piece) and abs(out[-1].to_mm - low) <= tol:
            out[-1] = out[-1]._replace(to_mm=high)
            continue
        out.append(piece)
    return out


def emit_stirrups(result: "C.DesignResult", zones: Sequence[StirrupZone], length_mm: Optional[float] = None) -> List[StirrupZone]:
    """Merge `zones` and write them onto the result, replacing what was there."""
    merged = merge_stirrup_zones(zones, length_mm)
    del result.stirrups[:]
    for zone in merged:
        extra = {}  # type: Dict[str, Any]
        if zone.first_mm > 0.0:
            extra["first_mm"] = float(zone.first_mm)
        result.add_stirrup(
            zone_mm=[zone.from_mm, zone.to_mm],
            legs=zone.legs,
            dia_mm=zone.dia_mm,
            spacing_mm=zone.spacing_mm,
            kind=zone.kind,
            **extra
        )
    return merged


# ---------------------------------------------------------------------------
# IS 13920 overlay
# ---------------------------------------------------------------------------


def apply_13920(
    result: "C.DesignResult",
    kind: str,
    ctx: Any = None,
    state: Optional[Mapping[str, Any]] = None,
) -> "C.DesignResult":
    """Overlay the IS 13920 ductile rules on a member that already passes IS 456.

    `kind` is "beam" or "column". `state` is the designer's private working
    record (never serialized): section, materials, provided steel, provided
    capacities and, optionally, `set_steel(role, ast_req_mm2)` so the overlay
    can add bars where a ratio rule asks for them. With no `state` the overlay
    falls back to `result.extras["ductile_state"]`, and with neither it
    discloses that it could not run rather than silently passing.

    The overlay never changes a section dimension: sizing belongs to the
    designer's resize ladder, which runs before this. It may re-enter stirrup
    and hoop design, add bars, add check rows, notes, warnings and the
    `joint_check_manual` referral.
    """
    context = as_context(ctx)
    record = state if state is not None else result.extras.get("ductile_state")
    member = _word(kind)
    if record is None:
        result.add_warning(
            "IS 13920 applies to this member but the designer passed no ductile state; "
            "the overlay did not run and the member carries IS 456 detailing only"
        )
        return result
    if member == "beam":
        return _apply_13920_beam(result, context, record)
    if member == "column":
        return _apply_13920_column(result, context, record)
    result.add_warning("IS 13920 overlay has no rules for member kind " + repr(kind) + "; IS 456 detailing only")
    return result


def drop_checks(result: "C.DesignResult", names: Sequence[str]) -> int:
    """Remove check rows the overlay has superseded. Returns how many went.

    Used where the ductile rules replace a design outright: leaving the IS 456
    stirrup rows beside a hoop schedule that no longer matches them would put a
    spacing on the report that is not in the schedule.
    """
    wanted = set(str(name) for name in names)
    before = len(result.checks)
    result.checks = [row for row in result.checks if row.name not in wanted]
    return before - len(result.checks)


def _num(record: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = record.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _snap_stirrup_dia(dia_mm: float) -> float:
    """The smallest catalogue stirrup diameter at or above `dia_mm`."""
    for candidate in sorted(C.STIRRUP_DIAS):
        if float(candidate) >= float(dia_mm) - _TOL:
            return float(candidate)
    return float(max(C.STIRRUP_DIAS))


def _mm_text(value: float) -> str:
    return ("%.0f" % float(value)) + " mm"


def _mm2_text(value: float) -> str:
    return ("%.0f" % float(value)) + " mm2"


def _apply_13920_beam(result: "C.DesignResult", ctx: DesignContext, st: Mapping[str, Any]) -> "C.DesignResult":
    """Cl 6: geometry, steel ratios, joint sagging, capacity shear, hoops."""
    b = _num(st, "b_mm")
    depth = _num(st, "D_mm")
    d = _num(st, "d_mm")
    span = _num(st, "span_mm")
    clear_span = _num(st, "clear_span_mm", span)
    fck = _num(st, "fck_mpa", ctx.fck_mpa)
    fy = _num(st, "fy_mpa", ctx.fy_mpa)
    fy_stirrup = _num(st, "fy_stirrup_mpa", ctx.fy_stirrup_mpa)
    if b <= 0.0 or depth <= 0.0 or d <= 0.0 or clear_span <= 0.0:
        result.add_warning("ductile state for this beam is incomplete; the IS 13920 overlay did not run")
        return result

    result.add_note(
        "IS 13920:2016 ductile detailing applied ("
        + is13920.EDITION
        + "): seismic zone "
        + str(ctx.zone)
        + ", "
        + str(ctx.frame)
        + " frame"
    )

    # -- Cl 6.1 geometry ---------------------------------------------------
    geometry = is13920.cl_6_1__beam_geometry(b, depth, clear_span)
    result.add_check(
        "ductile_beam_width",
        clause_of(is13920.cl_6_1__beam_geometry),
        demand=geometry.min_width_mm,
        capacity=b,
        units="mm",
    )
    result.add_check(
        "ductile_beam_aspect",
        clause_of(is13920.cl_6_1__beam_geometry),
        demand=is13920.BEAM_MIN_WIDTH_OVER_DEPTH,
        capacity=geometry.width_over_depth,
        units="-",
    )
    result.add_check(
        "ductile_beam_depth",
        clause_of(is13920.cl_6_1__beam_geometry),
        demand=depth,
        capacity=geometry.max_depth_mm,
        units="mm",
    )
    for text in geometry.notes:
        result.add_warning("IS 13920 Cl 6.1: " + text + "; the ductile overlay does not resize a section")

    # -- Cl 6.2 steel ratios ----------------------------------------------
    rho_min = is13920.cl_6_2_1__rho_min(fck, fy)
    rho_max = is13920.cl_6_2_2__rho_max()
    ast_floor = rho_min * b * d
    ast_ceiling = rho_max * b * d
    setter = st.get("set_steel")
    faces = (
        ("top_left", "ast_top_a_mm2"),
        ("top_right", "ast_top_b_mm2"),
        ("top_through", "ast_top_through_mm2"),
        ("bottom_mid", "ast_bot_mm2"),
    )
    # Bars added below raise the capacities the capacity design shear is built
    # from, so they are tracked here rather than read again from the state,
    # which still holds the pre-overlay values.
    capacity = {
        "top_left": _num(st, "mu_cap_hog_a_nmm"),
        "top_right": _num(st, "mu_cap_hog_b_nmm"),
        "bottom_mid": _num(st, "mu_cap_sag_nmm"),
    }
    provided = {}  # type: Dict[str, float]
    for role, key in faces:
        if key not in st:
            continue
        area = _num(st, key)
        if area <= 0.0:
            continue
        if area + 1e-6 < ast_floor and callable(setter):
            updated = setter(role, ast_floor)
            if updated:
                new_area = float(updated.get("ast_prov_mm2", area))
                if new_area > area:
                    result.add_note(
                        "IS 13920 Cl 6.2.1 raised the "
                        + role.replace("_", " ")
                        + " steel from "
                        + _mm2_text(area)
                        + " to "
                        + _mm2_text(new_area)
                        + " ("
                        + str(updated.get("label", ""))
                        + ") to reach rho_min "
                        + ("%.4f" % rho_min)
                    )
                    area = new_area
                if role in capacity:
                    capacity[role] = max(capacity[role], float(updated.get("mu_cap_nmm", capacity[role])))
        provided[role] = area
        result.add_check(
            "ductile_rho_min_" + role,
            clause_of(is13920.cl_6_2_1__rho_min),
            demand=ast_floor,
            capacity=area,
            units="mm2",
        )
        result.add_check(
            "ductile_rho_max_" + role,
            clause_of(is13920.cl_6_2_2__rho_max),
            demand=area,
            capacity=ast_ceiling,
            units="mm2",
        )
    if not callable(setter):
        result.add_note(
            "the ductile overlay could not add bars (no set_steel hook was supplied); "
            "any rho_min shortfall above is reported, not corrected"
        )
    result.add_note(
        "IS 13920 Cl 6.2.1(b): at least "
        + str(is13920.cl_6_2_1__min_bars_each_face())
        + " bars run the full length of the beam on each face"
    )

    # -- Cl 6.2.3 sagging capacity at the joint faces ----------------------
    mu_hog_a = capacity["top_left"]
    mu_hog_b = capacity["top_right"]
    mu_sag = capacity["bottom_mid"]
    hog_face = max(mu_hog_a, mu_hog_b)
    if hog_face > 0.0:
        required_sag = is13920.cl_6_2_3__joint_sagging(hog_face)
        if mu_sag + 1e-6 < required_sag and callable(setter) and mu_sag > 0.0:
            ast_bot = provided.get("bottom_mid", _num(st, "ast_bot_mm2"))
            target = ast_bot * required_sag / mu_sag if mu_sag > 0.0 else ast_bot
            updated = setter("bottom_mid", target)
            if updated:
                new_sag = float(updated.get("mu_cap_nmm", mu_sag))
                if new_sag > mu_sag:
                    result.add_note(
                        "IS 13920 Cl 6.2.3 raised the bottom steel to "
                        + _mm2_text(float(updated.get("ast_prov_mm2", ast_bot)))
                        + " ("
                        + str(updated.get("label", ""))
                        + ") so the sagging capacity at the joint face reaches half the hogging capacity"
                    )
                    mu_sag = new_sag
                    provided["bottom_mid"] = float(updated.get("ast_prov_mm2", ast_bot))
        result.add_check(
            "ductile_joint_sagging",
            clause_of(is13920.cl_6_2_3__joint_sagging),
            demand=required_sag,
            capacity=mu_sag,
            units="N.mm",
        )
        # Cl 6.2.4 binds the WEAKER of the two capacities available at midspan:
        # the full length bottom bars in sagging and whatever top steel runs
        # through in hogging. A caller that reports no through capacity is
        # measured on its sagging capacity alone rather than against a zero.
        through = _num(st, "mu_cap_top_through_nmm")
        along_span = min(mu_sag, through) if through > 0.0 else mu_sag
        result.add_check(
            "ductile_span_capacity_floor",
            clause_of(is13920.cl_6_2_4__span_capacity_floor),
            demand=is13920.cl_6_2_4__span_capacity_floor(hog_face),
            capacity=along_span,
            units="N.mm",
        )

    # -- Cl 6.3.3 capacity design shear ------------------------------------
    tau_c_max = is456.table_20__tau_c_max(fck)
    dia_long_min = _num(st, "dia_long_min_mm", 12.0)
    hoops = is13920.cl_6_3_5__hoop_zones(d, dia_long_min, clear_span)
    for text in hoops.notes:
        result.add_note("IS 13920 Cl 6.3.5: " + text)

    zones = []  # type: List[StirrupZone]
    ends = (("a", "vu_a_n", "tau_c_a_mpa", 0.0), ("b", "vu_b_n", "tau_c_b_mpa", span))
    governed = False
    superseded = drop_checks(
        result,
        ("stirrups_a", "stirrups_b", "stirrup_spacing_a", "stirrup_spacing_b"),
    )
    if superseded:
        result.add_note(
            "the IS 456 stirrup rows are superseded here: the hoops below replace them, so the schedule and "
            "the check rows describe the same steel"
        )
    for name, shear_key, tau_key, origin in ends:
        v_gravity = _num(st, shear_key)
        sway_a = is13920.cl_6_3_3__capacity_shear(v_gravity, mu_hog_a, mu_sag, clear_span)
        sway_b = is13920.cl_6_3_3__capacity_shear(v_gravity, mu_hog_b, mu_sag, clear_span)
        v_design = max(sway_a.v_design_n, sway_b.v_design_n)
        if v_design > v_gravity + 1e-6:
            governed = True
        tau_v = is456.cl_40_1__tau_v(v_design, b, d)
        result.add_check(
            "ductile_shear_stress_" + name,
            clause_of(is456.table_20__tau_c_max),
            demand=tau_v,
            capacity=tau_c_max,
            units="MPa",
        )
        if tau_v > tau_c_max + 1e-9:
            result.add_warning(
                "IS 13920 Cl 6.3.3 capacity shear at end "
                + name
                + " puts tau_v at "
                + ("%.2f" % tau_v)
                + " MPa, above the IS 456 Table 20 cap of "
                + ("%.2f" % tau_c_max)
                + " MPa; the section must be enlarged, which the ductile overlay is not permitted to do"
            )
        tau_c = _num(st, tau_key)
        vus = max(v_design - tau_c * b * d, 0.0)
        asv_per_mm = max(
            is456.cl_40_4__vertical_stirrups(vus, fy_stirrup, d),
            is456.cl_26_5_1_6__min_stirrups(b, fy_stirrup),
        )
        choice = choose_stirrups(
            asv_per_mm,
            is456.cl_26_5_1_5__max_stirrup_spacing(d),
            min_dia_mm=hoops.min_dia_mm,
            spacing_cap_mm=hoops.spacing_end_mm,
        )
        result.add_check(
            "ductile_hoops_" + name,
            clause_of(is13920.cl_6_3_5__hoop_zones),
            demand=choice.asv_per_mm_req,
            capacity=choice.asv_per_mm_prov,
            units="mm2/mm",
        )
        if not choice.ok:
            result.add_warning("IS 13920 hoops at end " + name + ": " + choice.note)
        if origin <= 0.0:
            start, end_mm = 0.0, min(hoops.end_zone_mm, span)
        else:
            start, end_mm = max(span - hoops.end_zone_mm, 0.0), span
        zones.append(
            StirrupZone(
                from_mm=start,
                to_mm=end_mm,
                legs=choice.legs,
                dia_mm=choice.dia_mm,
                spacing_mm=choice.spacing_mm,
                kind="confining",
                first_mm=hoops.first_hoop_mm,
            )
        )
        result.extras.setdefault("ductile", {})["shear_" + name] = {
            "v_gravity_n": v_gravity,
            "v_design_n": v_design,
            "sway_term_n": sway_a.sway_term_n,
            "governs": sway_a.governs if sway_a.v_design_n >= sway_b.v_design_n else sway_b.governs,
            "tau_v_mpa": tau_v,
            "tau_c_mpa": tau_c,
            "spacing_mm": choice.spacing_mm,
            "legs": choice.legs,
            "dia_mm": choice.dia_mm,
        }

    # Middle of the span: the Cl 6.3.5 d/2 pitch over the Cl 26.5.1.6 minimum.
    asv_min = is456.cl_26_5_1_6__min_stirrups(b, fy_stirrup)
    middle = choose_stirrups(
        asv_min,
        is456.cl_26_5_1_5__max_stirrup_spacing(d),
        min_dia_mm=hoops.min_dia_mm,
        spacing_cap_mm=hoops.spacing_mid_mm,
    )
    zones.append(
        StirrupZone(
            from_mm=0.0,
            to_mm=span,
            legs=middle.legs,
            dia_mm=middle.dia_mm,
            spacing_mm=middle.spacing_mm,
            kind="shear",
        )
    )
    emit_stirrups(result, zones, span)

    result.add_note(
        "IS 13920 Cl 6.3.5: hoops over "
        + _mm_text(hoops.end_zone_mm)
        + " (2d) from each face, first hoop "
        + _mm_text(hoops.first_hoop_mm)
        + " from the face, pitch "
        + _mm_text(hoops.spacing_end_mm)
        + " inside the zone and "
        + _mm_text(hoops.spacing_mid_mm)
        + " (d/2) outside it"
    )
    if governed:
        result.add_note(
            "IS 13920 Cl 6.3.3: the design shear is the plastic hinge capacity shear from the PROVIDED steel, "
            "which governs over the analysis shear at one or both ends"
        )
    result.add_note(
        "IS 13920 Cl 6.3.3 gravity term: the factored envelope shear is used as Vg, "
        "which is at or above the 1.2(DL+LL) gravity shear the clause names"
    )
    result.add_note(
        "IS 13920 Cl 6.3.4 (concrete shear strength taken as zero where the earthquake share of the "
        "design shear is more than half) is not evaluated in this version: the envelope does not carry "
        "the earthquake share separately, so the Table 19 concrete contribution is retained"
    )
    result.add_note(
        "IS 13920 Cl 6.2.6 laps: lap splices only in the middle half of the span, hoops at 150 mm or less "
        "over the lap length, and not more than half the bars lapped at one section"
    )
    result.extras.setdefault("ductile", {})["applied"] = True
    result.extras["ductile"]["edition"] = is13920.EDITION
    result.extras["ductile"]["end_zone_mm"] = float(hoops.end_zone_mm)
    result.extras["ductile"]["hoop_spacing_end_mm"] = float(hoops.spacing_end_mm)
    result.extras["ductile"]["hoop_spacing_mid_mm"] = float(hoops.spacing_mid_mm)
    result.extras["ductile"]["first_hoop_mm"] = float(hoops.first_hoop_mm)
    result.extras.pop("ductile_state", None)
    return result


def _apply_13920_column(result: "C.DesignResult", ctx: DesignContext, st: Mapping[str, Any]) -> "C.DesignResult":
    """Cl 7: geometry, confining zones, hoop pitch and Ash, strong column flag.

    The Cl 7.1 geometry clause is the one part of this that is conditional. A
    state flagged `confinement_column` is an IS 4326 tie column, not a frame
    member, so the clause is replaced by a NOTE saying it was not applied and
    why; every other clause here applies to it exactly as to a frame column.
    """
    b = _num(st, "b_mm")
    depth = _num(st, "D_mm")
    height = _num(st, "clear_height_mm")
    fck = _num(st, "fck_mpa", ctx.fck_mpa)
    fy = _num(st, "fy_mpa", ctx.fy_mpa)
    dia_long_min = _num(st, "dia_long_min_mm", 12.0)
    dia_beam_bar = _num(st, "dia_beam_bar_mm", dia_long_min)
    if b <= 0.0 or depth <= 0.0 or height <= 0.0:
        result.add_warning("ductile state for this column is incomplete; the IS 13920 overlay did not run")
        return result

    result.add_note(
        "IS 13920:2016 ductile detailing applied ("
        + is13920.EDITION
        + "): seismic zone "
        + str(ctx.zone)
        + ", "
        + str(ctx.frame)
        + " frame"
    )

    if bool(st.get("confinement_column")):
        # IS 13920 Cl 7 is headed "columns and frame members subjected to
        # bending and axial load": it sizes a member of the lateral load
        # resisting FRAME. An IS 4326 confining column is not one. It is cast
        # against toothed masonry to tie a wall together, its plan section is
        # the wall it confines (230 x t, placement/masonry.TIE_COLUMN_WIDTH_MM),
        # and IS 4326 nowhere imposes the Cl 7.1.1 least dimension of 300 mm on
        # it. Judging one by that clause fails every tie column in a zone III
        # masonry house on a rule that does not apply to it, so the clause is
        # skipped HERE and only here. Everything IS 4326 does want of a
        # confining column still runs: the IS 456 axial and biaxial design that
        # produced this section, its longitudinal cage and ties, and the Cl 7.6
        # confining hoops, laps and joint referral below.
        result.add_note(
            "IS 13920 Cl 7.1 (least dimension "
            + _mm_text(is13920.COLUMN_MIN_DIMENSION_MM)
            + ", side ratio "
            + ("%.2f" % float(is13920.COLUMN_MIN_WIDTH_OVER_DEPTH))
            + ") is NOT applied to this member: it is an IS 4326 confining (tie) column, "
            "not a frame column, and its "
            + _mm_text(min(b, depth))
            + " x "
            + _mm_text(max(b, depth))
            + " section is set by the masonry wall it ties. The rest of the IS 13920 "
            "overlay, and the full IS 456 design, are applied to it unchanged"
        )
    else:
        geometry = is13920.cl_7_1__column_geometry(b, depth, dia_beam_bar)
        result.add_check(
            "ductile_column_min_dim",
            clause_of(is13920.cl_7_1__column_geometry),
            demand=geometry.required_min_dim_mm,
            capacity=geometry.min_dim_mm,
            units="mm",
        )
        result.add_check(
            "ductile_column_aspect",
            clause_of(is13920.cl_7_1__column_geometry),
            demand=is13920.COLUMN_MIN_WIDTH_OVER_DEPTH,
            capacity=geometry.aspect_ratio,
            units="-",
        )
        for text in geometry.notes:
            result.add_warning(
                "IS 13920 Cl 7.1: " + text + "; the ductile overlay does not resize a section"
            )

    lo = is13920.cl_7_6_1__confining_length(max(b, depth), height)
    spacing = is13920.cl_7_6_2__confining_spacing(min(b, depth), dia_long_min)
    for text in spacing.notes:
        result.add_note("IS 13920 Cl 7.6.2: " + text)

    cover = _num(st, "cover_mm", 40.0)
    # IS 13920 Cl 7.4.1 floors the hoop at 8 mm; the diameter is then snapped up
    # to a catalogue size, because a tie the catalogue does not carry cannot be
    # priced or bent.
    hoop_dia = _snap_stirrup_dia(max(_num(st, "tie_dia_mm", 8.0), is13920.HOOP_MIN_DIA_MM))
    core_b = max(b - 2.0 * cover, 1.0)
    core_d = max(depth - 2.0 * cover, 1.0)
    ag = _num(st, "ag_mm2", b * depth)
    ak = _num(st, "ak_mm2", core_b * core_d)
    h_core = max(core_b, core_d)
    ash = is13920.cl_7_6_3__ash_rectangular(spacing.spacing_mm, h_core, fck, fy, ag, ak)
    for text in ash.notes:
        result.add_note("IS 13920 Cl 7.6.3: " + text)
    leg_area = C.bar_area_mm2(hoop_dia)
    if leg_area + 1e-6 < ash.ash_mm2:
        for candidate in C.STIRRUP_DIAS:
            if C.bar_area_mm2(candidate) + 1e-6 >= ash.ash_mm2:
                hoop_dia = float(candidate)
                leg_area = C.bar_area_mm2(candidate)
                break
    result.add_check(
        "ductile_confining_ash",
        clause_of(is13920.cl_7_6_3__ash_rectangular),
        demand=ash.ash_mm2,
        capacity=leg_area,
        units="mm2",
    )
    if ash.crossties_required:
        result.add_note(
            "IS 13920 Cl 7.6.3: hoop leg "
            + _mm_text(h_core)
            + " needs crossties so no leg spans more than "
            + _mm_text(is13920.CONFINING_MAX_HOOP_LEG_MM)
        )

    zones = list(st.get("tie_zones") or ())  # type: List[StirrupZone]
    stilt = bool(st.get("stilt_storey"))
    if stilt:
        zones.append(
            StirrupZone(
                from_mm=0.0,
                to_mm=height,
                legs=int(_num(st, "legs", 2)),
                dia_mm=int(hoop_dia),
                spacing_mm=spacing.spacing_mm,
                kind="confining",
            )
        )
        result.add_note(
            "IS 13920 Cl 7.6.1: special confining hoops run the full clear height of this storey "
            "because it carries a stilt or an abrupt stiffness change"
        )
    else:
        zones.append(
            StirrupZone(
                from_mm=0.0,
                to_mm=min(lo, height),
                legs=int(_num(st, "legs", 2)),
                dia_mm=int(hoop_dia),
                spacing_mm=spacing.spacing_mm,
                kind="confining",
            )
        )
        zones.append(
            StirrupZone(
                from_mm=max(height - lo, 0.0),
                to_mm=height,
                legs=int(_num(st, "legs", 2)),
                dia_mm=int(hoop_dia),
                spacing_mm=spacing.spacing_mm,
                kind="confining",
            )
        )
    if zones:
        emit_stirrups(result, zones, height)
    result.add_note(
        "IS 13920 Cl 7.6: special confining hoops over "
        + _mm_text(lo)
        + " from each joint face at a pitch of "
        + _mm_text(spacing.spacing_mm)
    )
    result.add_note(
        "IS 13920 Cl 7.5 laps: splices only in the middle half of the clear height, "
        "hoops at 150 mm or less over the lap, and not more than half the bars spliced at one section"
    )

    strong = is13920.cl_7_2_1__strong_column_ratio(_num(st, "sum_mc_nmm"), _num(st, "sum_mb_nmm"))
    if strong.applicable:
        # Flag only, never a resize (Cl 7.2.1 is a joint verdict, and the joint
        # is referred below): a shortfall is disclosed as a warn row.
        result.add_check(
            "ductile_strong_column",
            clause_of(is13920.cl_7_2_1__strong_column_ratio),
            demand=strong.required,
            capacity=strong.ratio,
            units="-",
            status=C.CHECK_PASS if strong.ok else CHECK_WARN,
        )
    for text in strong.notes:
        result.add_note("IS 13920 Cl 7.2.1: " + text)
    joint = is13920.cl_9__joint_check()
    result.add_referral(
        joint.referral,
        {
            "element_id": result.element_id,
            "marker": joint.marker,
            "strong_column_ratio": float(strong.ratio),
            "strong_column_required": float(strong.required),
            "applicable": bool(strong.applicable),
        },
    )
    for text in joint.notes:
        result.add_note(text)
    result.extras.setdefault("ductile", {})["applied"] = True
    result.extras["ductile"]["edition"] = is13920.EDITION
    result.extras["ductile"]["confining_length_mm"] = float(lo)
    result.extras["ductile"]["confining_spacing_mm"] = float(spacing.spacing_mm)
    result.extras["ductile"]["ash_mm2"] = float(ash.ash_mm2)
    result.extras.pop("ductile_state", None)
    return result
