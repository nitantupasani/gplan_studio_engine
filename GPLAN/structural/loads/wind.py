"""IS 875 (Part 3) : 2015 static wind forces for a low-rise rectangular block.

The v1 method in one call: a bbox facade, k2 by height, pz = 0.6 Vz^2, the
Table 5 net frame coefficient, and one storey force per level per direction,
emitted as four lateral cases (WX+, WX-, WY+, WY-) with a clause-traced report.

Wave-3 boundary. Nothing here imports from `loads` or `analysis`, so cases and
forces are PLAIN DICTS with the documented shapes below; the wave-5
orchestrator adapts them to the loads package dataclasses (`LoadCase`,
`StoreyForce`) without recomputing anything.

    storey force   {"storey": int, "fx_kn": float, "fy_kn": float,
                    "z_m": float, "source": str}
    lateral case   {"name": str, "storey_forces": [storey force, ...], ...}

Those keys are exactly `loads.StoreyForce.from_dict`, so the orchestrator adapts
a case with `StoreyForce.from_dict(force)` and nothing is recomputed.

Input shape (`model_like`), the bbox envelope of the ground boundary:

    {"width_m": 12.0,             # plan dimension along X
     "depth_m": 8.0,              # plan dimension along Y
     "storey_z_tops": [3.0, 6.0], # level elevations, bottom_z_m + height_m
     "base_z_m": 0.0,             # optional, defaults to 0.0
     "roof": {"alpha_deg": 22.0, "dead_kpa": 0.6}}   # optional, uplift check

Table 5 geometry, stated once because the printed table names its dimensions
and this module maps them: `w` is the width of the windward and leeward faces,
that is the plan dimension PERPENDICULAR to the wind, and `l` is the along-wind
plan dimension. So wind along X reads w = depth_m and l = width_m, and the
storey force spreads over B_perp = w. The transcribed Table 5 rows in
`data/is875_3_wind.yaml` carry verify: "print" and are not vetted numbers.

Simplifications, all restated in the report block: bbox facade, no Ka area
averaging unless asked for, Cpi excluded from the frame shears (it cancels on
the diaphragm total) and exposed through `wall_panel_pressures()` for cladding
and out-of-plane masonry checks later, no frictional drag, no member design
from roof wind.

Units are SI: metres, m/s, kPa, kN.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..codes import is875
from ..codes.trace import trace_into
from ..model import DisclosureLog

STAGE = "loads.wind"
CODE = "IS 875-3:2015"

DIRECTIONS = ("x", "y")

# Emission order is fixed: WX+, WX-, WY+, WY-.
CASE_NAMES = {"x": ("WX+", "WX-"), "y": ("WY+", "WY-")}

_FORCE_SOURCE = CODE + " 6.3"

# Cl 7.4.1 anchorage rule of thumb carried by the spec: uplift matters once it
# passes 0.9 of the roof dead load.
UPLIFT_DEAD_FRACTION = 0.9

_TINY = 1e-12


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindContext:
    """Site wind inputs.

    Give `Vb_ms` directly or a `zone` ("1".."6", or an Annex A city name) for
    the lookup; one of the two is required. `use_kd_ka_kc` is False in v1, so
    pd = pz with Kd = Ka = Kc = 1.0, the conservative reading; turning it on
    applies the stored Kd 0.9, the Table 4 Ka by tributary area and Kc 0.9,
    every one of them traced.
    """

    Vb_ms: Optional[float] = None
    zone: Optional[str] = None
    terrain_category: int = 2
    k1: float = 1.0
    k3: float = 1.0
    k4: float = 1.0
    permeability: str = "normal"
    use_kd_ka_kc: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Vb_ms": None if self.Vb_ms is None else float(self.Vb_ms),
            "zone": None if self.zone is None else str(self.zone),
            "terrain_category": int(self.terrain_category),
            "k1": float(self.k1),
            "k3": float(self.k3),
            "k4": float(self.k4),
            "permeability": str(self.permeability),
            "use_kd_ka_kc": bool(self.use_kd_ka_kc),
        }


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Envelope:
    """The bbox facade the static method is applied to."""

    width_m: float  # X
    depth_m: float  # Y
    base_z_m: float
    levels: Tuple[Tuple[int, float, float, float], ...]  # storey, z, h_below, h_above

    @property
    def height_m(self) -> float:
        return self.levels[-1][1] - self.base_z_m

    @property
    def least_width_m(self) -> float:
        return min(self.width_m, self.depth_m)

    @property
    def plan_aspect(self) -> float:
        return max(self.width_m, self.depth_m) / min(self.width_m, self.depth_m)

    def across_wind_m(self, direction: str) -> float:
        """`w`: the width of the windward and leeward faces."""
        return self.depth_m if direction == "x" else self.width_m

    def along_wind_m(self, direction: str) -> float:
        """`l`: the along-wind plan dimension."""
        return self.width_m if direction == "x" else self.depth_m


def _envelope(model_like: Dict[str, Any]) -> _Envelope:
    for key in ("width_m", "depth_m", "storey_z_tops"):
        if key not in model_like:
            raise KeyError("wind needs '" + key + "' in the envelope description")
    width = float(model_like["width_m"])
    depth = float(model_like["depth_m"])
    if width <= 0.0 or depth <= 0.0:
        raise ValueError("plan dimensions must be positive, got " + repr((width, depth)))
    base_z = float(model_like.get("base_z_m", 0.0))
    tops = sorted(float(z) for z in model_like["storey_z_tops"])
    tops = [z for z in tops if z > base_z + _TINY]
    if not tops:
        raise ValueError(
            "storey_z_tops carries no level above the base elevation " + repr(base_z)
        )
    levels = []  # type: List[Tuple[int, float, float, float]]
    for index, z in enumerate(tops):
        below = z - (tops[index - 1] if index > 0 else base_z)
        above = (tops[index + 1] - z) if index + 1 < len(tops) else 0.0
        levels.append((index, z, below, above))
    return _Envelope(width_m=width, depth_m=depth, base_z_m=base_z, levels=tuple(levels))


# ---------------------------------------------------------------------------
# speeds and pressures
# ---------------------------------------------------------------------------


def _basic_speed(ctx: WindContext) -> Tuple[float, str]:
    if ctx.Vb_ms is not None:
        speed = float(ctx.Vb_ms)
        if speed <= 0.0:
            raise ValueError("Vb_ms must be positive, got " + repr(speed))
        return speed, "given directly in the WindContext"
    if ctx.zone is None:
        raise ValueError(
            "WindContext needs either Vb_ms or a zone; neither was given and no basic wind "
            "speed is defaulted here"
        )
    return is875.part3_basic_wind_speed(ctx.zone), CODE + " Cl 5.2 / Fig. 1"


def _levels(envelope: _Envelope, ctx: WindContext, vb_ms: float) -> List[Dict[str, Any]]:
    """Per level: k2, Vz and pz, all direction independent."""
    rows = []  # type: List[Dict[str, Any]]
    for storey, z, below, above in envelope.levels:
        k2 = is875.part3_k2(ctx.terrain_category, z)
        vz = is875.part3_design_wind_speed(vb_ms, ctx.k1, k2, ctx.k3, ctx.k4)
        pz = is875.part3_wind_pressure(vz)
        rows.append(
            {
                "storey": storey,
                "z_m": z,
                "k2": k2,
                "k2_range": is875.part3_k2_range(z),
                "vz_ms": vz,
                "pz_kpa": pz,
                "h_below_m": below,
                "h_above_m": above,
                "tributary_h_m": 0.5 * below + 0.5 * above,
            }
        )
    return rows


def _design_pressure(
    pz_kpa: float, area_m2: float, ctx: WindContext
) -> Tuple[float, float, float, float]:
    """(pd, Kd, Ka, Kc) for one panel; all three factors are 1.0 by default."""
    if not ctx.use_kd_ka_kc:
        return is875.part3_design_pressure(pz_kpa, 1.0, 1.0, 1.0), 1.0, 1.0, 1.0
    kd = is875.part3_stored_factor("kd")
    kc = is875.part3_stored_factor("kc")
    ka = is875.part3_ka(area_m2)
    return is875.part3_design_pressure(pz_kpa, kd, ka, kc), kd, ka, kc


# ---------------------------------------------------------------------------
# validity gates
# ---------------------------------------------------------------------------


def _static_limits(
    envelope: _Envelope, levels: Sequence[Dict[str, Any]], log: DisclosureLog
) -> Dict[str, Any]:
    """Cl 10.1 and Cl 7.4.1 gates; the engine warns, it does not refuse."""
    limits = is875.part3_static_limits()
    height = envelope.height_m
    slenderness = height / envelope.least_width_m
    aspect = envelope.plan_aspect
    above_table = sorted({row["storey"] for row in levels if row["k2_range"] == "above_table"})
    below_table = sorted({row["storey"] for row in levels if row["k2_range"] == "below_table"})

    checks = {
        "height_m": height,
        "max_height_m": limits["max_height_m"],
        "height_ok": height <= limits["max_height_m"],
        "height_over_least_width": slenderness,
        "max_height_over_least_width": limits["max_height_over_least_width"],
        "slenderness_ok": slenderness <= limits["max_height_over_least_width"],
        "plan_aspect": aspect,
        "max_plan_aspect_for_no_friction": limits["max_plan_aspect_for_no_friction"],
        "friction_negligible": aspect <= limits["max_plan_aspect_for_no_friction"],
        "k2_above_table_levels": above_table,
        # Heights under 10 m read the 10 m row of Table 2. The table itself
        # calls that the conservative standard reading, so it is reported here
        # rather than put on the ladder: it is the normal low-rise case.
        "k2_below_table_levels": below_table,
        "k2_below_table_note": "levels under 10 m take the 10 m row of Table 2, the conservative standard reading",
    }

    reasons = []  # type: List[str]
    if not checks["height_ok"]:
        reasons.append(
            "height " + repr(height) + " m is above the " + repr(limits["max_height_m"]) + " m static-method gate"
        )
    if not checks["slenderness_ok"]:
        reasons.append(
            "height over least width "
            + repr(slenderness)
            + " is above "
            + repr(limits["max_height_over_least_width"])
        )
    if not checks["friction_negligible"]:
        reasons.append(
            "plan aspect "
            + repr(aspect)
            + " is above "
            + repr(limits["max_plan_aspect_for_no_friction"])
            + "; frictional drag is not computed in v1"
        )
    if above_table:
        reasons.append("k2 was clamped at the top of Table 2 for levels " + repr(above_table))
    checks["reasons"] = reasons
    checks["within_static_method"] = not reasons
    if reasons:
        log.add(
            "W_WIND_STATIC_LIMIT",
            "static wind method outside its comfort zone: " + "; ".join(reasons),
            clause=CODE + " 10.1",
            stage=STAGE,
        )
    return checks


# ---------------------------------------------------------------------------
# the method
# ---------------------------------------------------------------------------


def build_wind(
    model_like: Dict[str, Any],
    ctx: WindContext,
    log: Optional[DisclosureLog] = None,
    trace: Optional[List[Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Four lateral cases and one clause-traced wind report.

    Returns `(cases, report)`. `cases` is exactly `[WX+, WX-, WY+, WY-]`, each
    a plain dict `{"name", "kind", "direction", "sign", "base_shear_kn",
    "storey_forces"}`; the orchestrator turns them into `LoadCase` objects.

    Pass `trace` to collect the clause records this call makes; pass `log` to
    merge the disclosures into a shared ladder as well as into the report.
    """
    if trace is not None:
        with trace_into(trace):
            return _build(model_like, ctx, log)
    return _build(model_like, ctx, log)


def _build(
    model_like: Dict[str, Any], ctx: WindContext, into: Optional[DisclosureLog]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    log = DisclosureLog()
    envelope = _envelope(model_like)
    vb_ms, vb_source = _basic_speed(ctx)
    levels = _levels(envelope, ctx, vb_ms)
    limits = _static_limits(envelope, levels, log)

    directions = {}  # type: Dict[str, Dict[str, Any]]
    cases = []  # type: List[Dict[str, Any]]
    out_of_table = []  # type: List[str]

    for direction in DIRECTIONS:
        w_m = envelope.across_wind_m(direction)
        l_m = envelope.along_wind_m(direction)
        h_over_w = envelope.height_m / w_m
        l_over_w = l_m / w_m
        cpe = is875.part3_cpe_walls(h_over_w, l_over_w)
        if cpe.out_of_table:
            out_of_table.append(direction)

        rows = []  # type: List[Dict[str, Any]]
        total_kn = 0.0
        for level in levels:
            area = w_m * level["tributary_h_m"]
            pd, kd, ka, kc = _design_pressure(level["pz_kpa"], area, ctx)
            force = pd * cpe.net * w_m * level["tributary_h_m"]
            total_kn += force
            rows.append(
                {
                    "storey": level["storey"],
                    "z_m": level["z_m"],
                    "tributary_h_m": level["tributary_h_m"],
                    "tributary_area_m2": area,
                    "pz_kpa": level["pz_kpa"],
                    "kd": kd,
                    "ka": ka,
                    "kc": kc,
                    "pd_kpa": pd,
                    "f_kn": force,
                }
            )

        directions[direction] = {
            "w_m": w_m,
            "l_m": l_m,
            "b_perp_m": w_m,
            "h_over_w": h_over_w,
            "l_over_w": l_over_w,
            "cpe_windward": cpe.windward,
            "cpe_leeward": cpe.leeward,
            "cpe_side": cpe.side,
            "cnet": cpe.net,
            "cpe_out_of_table": bool(cpe.out_of_table),
            "base_shear_kn": total_kn,
            "levels": rows,
            "cases": list(CASE_NAMES[direction]),
        }

        for name in CASE_NAMES[direction]:
            sign = 1.0 if name.endswith("+") else -1.0
            forces = [
                {
                    "storey": row["storey"],
                    "fx_kn": sign * row["f_kn"] if direction == "x" else 0.0,
                    "fy_kn": sign * row["f_kn"] if direction == "y" else 0.0,
                    "z_m": row["z_m"],
                    "source": _FORCE_SOURCE,
                }
                for row in rows
            ]
            cases.append(
                {
                    "name": name,
                    "kind": "wind",
                    "direction": direction,
                    "sign": int(sign),
                    "base_shear_kn": total_kn,
                    "storey_forces": forces,
                }
            )

    if out_of_table:
        log.add(
            "W_WIND_STATIC_LIMIT",
            "Table 5 was read outside its printed h/w or l/w bands for direction "
            + ", ".join(out_of_table)
            + "; the widest band was used",
            clause=CODE + " Table 5",
            stage=STAGE,
        )

    roof = _roof_block(model_like, envelope, levels, directions, ctx, log)

    report = {
        "code": CODE,
        "method": "static (Cl 6), rectangular clad building",
        "context": ctx.to_dict(),
        "vb_ms": vb_ms,
        "vb_source": vb_source,
        "terrain_category": int(ctx.terrain_category),
        "base_z_m": envelope.base_z_m,
        "height_m": envelope.height_m,
        "plan_dims_m": {"x": envelope.width_m, "y": envelope.depth_m},
        "levels": levels,
        "directions": directions,
        "static_limits": limits,
        "roof": roof,
        "cases": [case["name"] for case in cases],
        "simplifications": [
            "facade taken as the bbox of the ground boundary",
            "Ka area averaging off by default (Kd = Ka = Kc = 1.0, pd = pz)",
            "Cpi excluded from the storey shears; it cancels on the diaphragm total "
            "and is exposed through wall_panel_pressures() for cladding and out-of-plane checks",
            "no frictional drag term",
            "no member design from roof wind in v1",
        ],
        "disclosures": log.to_dict(),
    }
    if into is not None:
        into.extend(log.entries)
    return cases, report


# ---------------------------------------------------------------------------
# hooks kept for the cladding, masonry and anchorage checks
# ---------------------------------------------------------------------------


def wall_panel_pressures(
    model_like: Dict[str, Any],
    ctx: WindContext,
    log: Optional[DisclosureLog] = None,
    trace: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Per level, per face panel pressures INCLUDING Cpi, both signs.

    The frame shears in `build_wind` use Cnet only, because the internal
    pressure is equal and opposite on the two internal surfaces and cancels on
    the diaphragm total. A single wall panel feels it, so this hook hands the
    out-of-plane checks p = pd (Cpe - Cpi) on the windward, leeward and side
    faces with Cpi taken both ways round. Nothing consumes it in v1; it exists
    so that the masonry and cladding checks read the same pressures the frame
    did.
    """
    if trace is not None:
        with trace_into(trace):
            return _panels(model_like, ctx, log)
    return _panels(model_like, ctx, log)


def _panels(
    model_like: Dict[str, Any], ctx: WindContext, into: Optional[DisclosureLog]
) -> Dict[str, Any]:
    log = DisclosureLog()
    envelope = _envelope(model_like)
    vb_ms, vb_source = _basic_speed(ctx)
    levels = _levels(envelope, ctx, vb_ms)
    cpi = is875.part3_cpi(ctx.permeability)

    out_levels = []  # type: List[Dict[str, Any]]
    for level in levels:
        block = {
            "storey": level["storey"],
            "z_m": level["z_m"],
            "pz_kpa": level["pz_kpa"],
            "directions": {},
        }  # type: Dict[str, Any]
        for direction in DIRECTIONS:
            w_m = envelope.across_wind_m(direction)
            cpe = is875.part3_cpe_walls(
                envelope.height_m / w_m, envelope.along_wind_m(direction) / w_m
            )
            pd, kd, ka, kc = _design_pressure(
                level["pz_kpa"], w_m * level["tributary_h_m"], ctx
            )
            faces = {}  # type: Dict[str, Any]
            for face, coefficient in (
                ("windward", cpe.windward),
                ("leeward", cpe.leeward),
                ("side", cpe.side),
            ):
                with_plus = pd * (coefficient - cpi.plus)
                with_minus = pd * (coefficient - cpi.minus)
                governing = with_plus if abs(with_plus) >= abs(with_minus) else with_minus
                faces[face] = {
                    "cpe": coefficient,
                    "p_external_kpa": pd * coefficient,
                    "p_net_cpi_plus_kpa": with_plus,
                    "p_net_cpi_minus_kpa": with_minus,
                    "p_net_governing_kpa": governing,
                }
            block["directions"][direction] = {"pd_kpa": pd, "kd": kd, "ka": ka, "kc": kc, "faces": faces}
        out_levels.append(block)

    result = {
        "code": CODE,
        "clause": CODE + " 7.3.2",
        "context": ctx.to_dict(),
        "vb_ms": vb_ms,
        "vb_source": vb_source,
        "cpi": {"magnitude": cpi.magnitude, "plus": cpi.plus, "minus": cpi.minus},
        "convention": "p = pd (Cpe - Cpi); positive acts inward on the panel, negative outward",
        "levels": out_levels,
        "disclosures": log.to_dict(),
    }
    if into is not None:
        into.extend(log.entries)
    return result


def roof_uplift_check(
    alpha_deg: float,
    h_over_w: float,
    pd_kpa: float,
    roof_dead_kpa: float,
    ctx: WindContext,
    log: Optional[DisclosureLog] = None,
) -> Dict[str, Any]:
    """Net uplift on a pitched roof against 0.9 of the roof dead load.

    Uplift is the outward net pressure, pd (Cpi - Cpe) on the slope whose Cpe
    is the most negative. Above `UPLIFT_DEAD_FRACTION` of the roof dead load the
    holding-down anchorage governs and `W_WIND_UPLIFT` goes on the ladder; no
    member is designed from roof wind in v1.
    """
    cpe = is875.part3_cpe_pitched_roof(alpha_deg, h_over_w)
    cpi = is875.part3_cpi(ctx.permeability)
    worst_cpe = min(cpe.windward, cpe.leeward)
    uplift = float(pd_kpa) * (cpi.plus - worst_cpe)
    resistance = UPLIFT_DEAD_FRACTION * float(roof_dead_kpa)
    governs = uplift > resistance
    if governs and log is not None:
        log.add(
            "W_WIND_UPLIFT",
            "net wind uplift "
            + repr(uplift)
            + " kPa exceeds "
            + repr(UPLIFT_DEAD_FRACTION)
            + " of the roof dead load ("
            + repr(resistance)
            + " kPa); holding-down anchorage is required",
            clause=CODE + " Table 6",
            stage=STAGE,
        )
    return {
        "alpha_deg": float(alpha_deg),
        "h_over_w": float(h_over_w),
        "cpe_windward": cpe.windward,
        "cpe_leeward": cpe.leeward,
        "cpe_out_of_table": bool(cpe.out_of_table),
        "cpi_plus": cpi.plus,
        "pd_kpa": float(pd_kpa),
        "uplift_kpa": uplift,
        "roof_dead_kpa": float(roof_dead_kpa),
        "resistance_kpa": resistance,
        "uplift_governs": bool(governs),
    }


def _roof_block(
    model_like: Dict[str, Any],
    envelope: _Envelope,
    levels: Sequence[Dict[str, Any]],
    directions: Dict[str, Dict[str, Any]],
    ctx: WindContext,
    log: DisclosureLog,
) -> Optional[Dict[str, Any]]:
    """Run the uplift check when the envelope described a pitched roof."""
    roof = model_like.get("roof")
    if not roof:
        return None
    alpha = float(roof.get("alpha_deg", 0.0))
    dead = float(roof.get("dead_kpa", 0.0))
    top = levels[-1]
    worst = None  # type: Optional[Dict[str, Any]]
    for direction in DIRECTIONS:
        block = directions[direction]
        pd = block["levels"][-1]["pd_kpa"]
        checked = roof_uplift_check(alpha, block["h_over_w"], pd, dead, ctx, log)
        checked["direction"] = direction
        checked["z_m"] = top["z_m"]
        if worst is None or checked["uplift_kpa"] > worst["uplift_kpa"]:
            worst = checked
    return worst
