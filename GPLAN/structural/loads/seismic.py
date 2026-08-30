"""IS 1893 (Part 1) : 2016 equivalent static earthquake forces.

The whole method in one call: seismic weight per storey with the Table 10
imposed-load fraction applied here, the approximate period per direction, the
design horizontal coefficient with the Cl 7.2.2 floor, the base shear and the
Cl 7.6.3 vertical distribution, emitted as four lateral cases (EQX+, EQX-,
EQY+, EQY-) and one clause-traced report.

Wave-3 boundary. This module deliberately imports nothing from `loads` or
`analysis`, so the cases and forces it returns are PLAIN DICTS with documented
shapes; the wave-5 orchestrator adapts them to the loads package dataclasses
(`LoadCase`, `StoreyForce`) without any recomputation.

    storey force   {"storey": int, "fx_kn": float, "fy_kn": float,
                    "z_m": float, "source": str}
    lateral case   {"name": str, "storey_forces": [storey force, ...], ...}

Those keys are exactly `loads.StoreyForce.from_dict`, so the orchestrator adapts
a case with `StoreyForce.from_dict(force)` and nothing is recomputed.

Input shape (`storey_weights`), one row per storey, from the takedown storey
ledger:

    {"storey": 0,               # 0-based, ground storey is 0 (finding 2)
     "w_dl_kn": 1800.0,         # full dead tally lumped at this level
     "w_ll_kn": 400.0,          # raw imposed tally at this level, unfactored
     "ll_basis_kpa": 2.0,       # governing imposed load, picks the Table 10 row
     "z_top_m": 3.0,            # level elevation, bottom_z_m + height_m
     "roof": False}             # Cl 7.3.2: roof imposed load is excluded

`w_kn` is accepted as an alias for `w_dl_kn` for a caller that has already
tallied a single weight; `w_ll_kn` then defaults to zero and no Table 10
fraction is applied. hi is always `z_top_m - base_z_m`, never derived from the
storey index (finding 2).

Units are SI throughout: metres, kN, seconds. Nothing here rounds; the response
edge does that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..codes import is1893
from ..codes.trace import trace_into
from ..model import DisclosureLog

STAGE = "loads.seismic"
CODE = "IS 1893-1:2016"

# The design spectra of Cl 6.4.2 are printed for 5 percent damping and the
# equivalent static method carries no damping adjustment; another value is an
# input this module cannot honour, so it raises rather than quietly using 5.
DAMPING_TABULATED = 0.05
DAMPING_TOL = 1e-9

# Any imposed load above the Table 10 threshold selects the conservative 0.50
# row. 5.0 kPa is the heaviest residential row in IS 875 (Part 2) Table 1, used
# only when a storey arrives with an imposed tally but no basis to classify it.
UNKNOWN_LL_BASIS_KPA = 5.0

DIRECTIONS = ("x", "y")

# Emission order is fixed: EQX+, EQX-, EQY+, EQY-.
CASE_NAMES = {"x": ("EQX+", "EQX-"), "y": ("EQY+", "EQY-")}

_FORCE_SOURCE = CODE + " 7.6.3"

_TINY = 1e-12


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeismicContext:
    """The site and system inputs of the equivalent static method.

    `system` is REQUIRED (finding 41): no OMRF default is baked in anywhere in
    the stack. `structural/api.py` resolves the default the request omitted,
    records it in `defaults_used`, and hands the resolved system in here.

    `importance` takes either the factor itself (1.0) or an IS 1893 Table 8
    category name ("residential", "important", "essential"), in which case the
    lookup is traced like every other clause.
    """

    zone: str = "III"
    soil: str = "II"
    importance: Any = 1.0
    system: Optional[str] = None
    infilled: bool = True
    damping: float = DAMPING_TABULATED

    def __post_init__(self) -> None:
        if self.system is None or not str(self.system).strip():
            raise ValueError(
                "SeismicContext.system is required (finding 41): no structural system is "
                "defaulted in loads or codes; structural/api.py resolves it and records the "
                "choice in defaults_used"
            )
        if abs(float(self.damping) - DAMPING_TABULATED) > DAMPING_TOL:
            raise ValueError(
                "only 5 percent damping is tabulated for the IS 1893 design spectra; got "
                + repr(float(self.damping))
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone": str(self.zone),
            "soil": str(self.soil),
            "importance": self.importance,
            "system": str(self.system),
            "infilled": bool(self.infilled),
            "damping": float(self.damping),
        }


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


def _plan_dimension(plan_dims: Dict[str, Any], direction: str) -> float:
    """Base plan dimension along `direction`, in metres.

    Accepts `{"x_m", "y_m"}` (primary) or `{"width_m", "depth_m"}`, width being
    the X dimension and depth the Y dimension.
    """
    keys = {"x": ("x_m", "width_m", "x"), "y": ("y_m", "depth_m", "y")}[direction]
    for key in keys:
        if key in plan_dims:
            value = float(plan_dims[key])
            if value <= 0.0:
                raise ValueError("plan dimension " + key + " must be positive, got " + repr(value))
            return value
    raise KeyError(
        "plan_dims needs a "
        + direction
        + " dimension; give one of "
        + ", ".join(keys)
        + " in metres"
    )


def _rows(storey_weights: Sequence[Dict[str, Any]], base_z_m: float) -> List[Dict[str, Any]]:
    """Normalize the storey ledger rows, sorted by storey index then elevation."""
    out = []  # type: List[Dict[str, Any]]
    for raw in storey_weights:
        if "storey" not in raw:
            raise KeyError("every storey_weights row needs a 0-based 'storey' index")
        if "z_top_m" not in raw:
            raise KeyError("every storey_weights row needs 'z_top_m' (bottom_z_m + height_m)")
        w_dl = raw.get("w_dl_kn")
        if w_dl is None:
            w_dl = raw.get("w_kn", 0.0)
        z_top = float(raw["z_top_m"])
        basis = raw.get("ll_basis_kpa")
        out.append(
            {
                "storey": int(raw["storey"]),
                "w_dl_kn": float(w_dl),
                "w_ll_kn": float(raw.get("w_ll_kn", 0.0) or 0.0),
                "ll_basis_kpa": None if basis is None else float(basis),
                "roof": bool(raw.get("roof", False)),
                "z_top_m": z_top,
                "h_i_m": z_top - float(base_z_m),
            }
        )
    out.sort(key=lambda row: (row["storey"], row["z_top_m"]))
    return out


def _apply_ll_fraction(rows: List[Dict[str, Any]], log: DisclosureLog) -> None:
    """Table 10 imposed-load fraction, applied here and traced per storey.

    Cl 7.3.2 keeps the roof imposed load out of the seismic weight altogether,
    so a row flagged `roof` takes fraction 0.0 whatever its basis.
    """
    for row in rows:
        w_ll = row["w_ll_kn"]
        if w_ll <= _TINY:
            row["ll_fraction"] = 0.0
            row["ll_fraction_source"] = "no imposed tally at this level"
        elif row["roof"]:
            row["ll_fraction"] = 0.0
            row["ll_fraction_source"] = CODE + " 7.3.2 (roof imposed load excluded)"
        else:
            basis = row["ll_basis_kpa"]
            if basis is None:
                basis = UNKNOWN_LL_BASIS_KPA
                log.add(
                    "W_LOAD_OCCUPANCY_FALLBACK",
                    "storey "
                    + str(row["storey"])
                    + " carries an imposed tally with no ll_basis_kpa; the Table 10 row above "
                    + "the threshold (0.50) was taken, evaluated at "
                    + repr(UNKNOWN_LL_BASIS_KPA)
                    + " kPa",
                    clause=CODE + " Table 10",
                    stage=STAGE,
                )
                row["ll_basis_assumed"] = True
            row["ll_fraction"] = is1893.seismic_ll_fraction(basis)
            row["ll_fraction_source"] = CODE + " Table 10"
        row["w_ll_seismic_kn"] = row["w_ll_kn"] * row["ll_fraction"]
        row["w_kn"] = row["w_dl_kn"] + row["w_ll_seismic_kn"]


# ---------------------------------------------------------------------------
# the method
# ---------------------------------------------------------------------------


def _direction_block(
    rows: Sequence[Dict[str, Any]],
    height_m: float,
    d_m: float,
    ctx: SeismicContext,
    z_factor: float,
    i_factor: float,
    r_factor: float,
    weight_kn: float,
    log: DisclosureLog,
) -> Dict[str, Any]:
    """Ta, Sa/g, Ah, VB and the Qi table for one direction."""
    if ctx.infilled:
        ta_s = is1893.period_infilled(height_m, d_m)
        ta_ref = CODE + " 7.6.2(c)"
    else:
        ta_s = is1893.period_bare_rc(height_m)
        ta_ref = CODE + " 7.6.2(a)"

    ordinate = is1893.sa_over_g(ta_s, ctx.soil)
    if ordinate.clamped:
        log.add(
            "W_TALL",
            "approximate period "
            + repr(ta_s)
            + " s runs past the 4 s end of the IS 1893 spectrum; Sa/g was read at 4 s and a "
            + "dynamic analysis is required before this result is used",
            clause=CODE + " 6.4.2",
            stage=STAGE,
        )

    ah_computed = is1893.design_horizontal_coeff(z_factor, i_factor, r_factor, ordinate.sa_g)
    ah_min = is1893.min_base_shear_coeff(ctx.zone)
    floor_governs = ah_min > ah_computed
    ah = ah_min if floor_governs else ah_computed

    base_shear_kn = is1893.base_shear(ah, weight_kn)
    pairs = [(row["w_kn"], row["h_i_m"]) for row in rows]
    forces = is1893.vertical_distribution(pairs, base_shear_kn)

    denominator = sum(w * h * h for w, h in pairs)
    qi = []  # type: List[Dict[str, Any]]
    for row, force in zip(rows, forces):
        w_h2 = row["w_kn"] * row["h_i_m"] * row["h_i_m"]
        qi.append(
            {
                "storey": row["storey"],
                "w_kn": row["w_kn"],
                "h_i_m": row["h_i_m"],
                "z_m": row["z_top_m"],
                "w_h2": w_h2,
                "share": (w_h2 / denominator) if denominator > 0.0 else 0.0,
                "qi_kn": force,
            }
        )

    return {
        "d_m": d_m,
        "ta_s": ta_s,
        "ta_clause": ta_ref,
        "sa_g": ordinate.sa_g,
        "sa_branch": ordinate.branch,
        "sa_clamped": bool(ordinate.clamped),
        "ah": ah,
        "ah_computed": ah_computed,
        "ah_min": ah_min,
        "min_coefficient_governs": bool(floor_governs),
        "ah_clause": (CODE + " 7.2.2") if floor_governs else (CODE + " 6.4.2"),
        "base_shear_kn": base_shear_kn,
        "qi": qi,
        "cases": [],
    }


def build_seismic(
    storey_weights: Sequence[Dict[str, Any]],
    plan_dims: Dict[str, Any],
    ctx: SeismicContext,
    base_z_m: float = 0.0,
    log: Optional[DisclosureLog] = None,
    trace: Optional[List[Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Four lateral cases and one clause-traced seismic report.

    `storey_weights` is the takedown storey ledger in the shape documented at
    the top of this module; `plan_dims` gives the base plan dimensions
    (`{"x_m": ..., "y_m": ...}`); `ctx` carries zone, soil, importance, the
    REQUIRED structural system and the infill flag.

    Returns `(cases, report)`. `cases` is exactly `[EQX+, EQX-, EQY+, EQY-]`,
    each a plain dict `{"name", "kind", "direction", "sign", "base_shear_kn",
    "storey_forces"}`; the orchestrator turns them into `LoadCase` objects.

    Pass `trace` to collect the clause records this call makes. Pass `log` to
    have every disclosure merged into a shared ladder as well as into the
    report.
    """
    if trace is not None:
        with trace_into(trace):
            return _build(storey_weights, plan_dims, ctx, base_z_m, log)
    return _build(storey_weights, plan_dims, ctx, base_z_m, log)


def _build(
    storey_weights: Sequence[Dict[str, Any]],
    plan_dims: Dict[str, Any],
    ctx: SeismicContext,
    base_z_m: float,
    into: Optional[DisclosureLog],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    log = DisclosureLog()
    rows = _rows(storey_weights, base_z_m)
    if not rows:
        raise ValueError("storey_weights is empty; the seismic weight has nowhere to come from")
    _apply_ll_fraction(rows, log)

    above = [row for row in rows if row["h_i_m"] > _TINY]
    at_base = [row for row in rows if row["h_i_m"] <= _TINY]
    if not above:
        raise ValueError(
            "every storey_weights row sits at or below the base elevation "
            + repr(float(base_z_m))
            + "; nothing is above the base to shake"
        )

    weight_kn = sum(row["w_kn"] for row in above)
    if weight_kn <= 0.0:
        raise ValueError("the seismic weight above the base is not positive")
    height_m = max(row["h_i_m"] for row in above)

    z_factor = is1893.zone_factor(ctx.zone)
    if isinstance(ctx.importance, str):
        i_factor = is1893.importance_factor(ctx.importance)
        importance_source = CODE + " Table 8"
    else:
        i_factor = float(ctx.importance)
        importance_source = "given directly in the SeismicContext"
    r_factor = is1893.response_reduction(ctx.system)

    directions = {}  # type: Dict[str, Dict[str, Any]]
    cases = []  # type: List[Dict[str, Any]]
    for direction in DIRECTIONS:
        d_m = _plan_dimension(plan_dims, direction)
        block = _direction_block(
            above, height_m, d_m, ctx, z_factor, i_factor, r_factor, weight_kn, log
        )
        block["cases"] = list(CASE_NAMES[direction])
        directions[direction] = block
        for name in CASE_NAMES[direction]:
            sign = 1.0 if name.endswith("+") else -1.0
            forces = []  # type: List[Dict[str, Any]]
            for entry in block["qi"]:
                magnitude = sign * entry["qi_kn"]
                forces.append(
                    {
                        "storey": entry["storey"],
                        "fx_kn": magnitude if direction == "x" else 0.0,
                        "fy_kn": magnitude if direction == "y" else 0.0,
                        "z_m": entry["z_m"],
                        "source": _FORCE_SOURCE,
                    }
                )
            cases.append(
                {
                    "name": name,
                    "kind": "seismic",
                    "direction": direction,
                    "sign": int(sign),
                    "base_shear_kn": block["base_shear_kn"],
                    "storey_forces": forces,
                }
            )

    report = {
        "code": CODE,
        "method": "equivalent static (Cl 7.6)",
        "context": ctx.to_dict(),
        "zone": str(ctx.zone),
        "soil": str(ctx.soil),
        "system": str(ctx.system),
        "z": z_factor,
        "i": i_factor,
        "r": r_factor,
        "zone_factor": z_factor,
        "importance_factor": i_factor,
        "importance_source": importance_source,
        "response_reduction": r_factor,
        "base_z_m": float(base_z_m),
        "height_m": height_m,
        "plan_dims_m": {"x": _plan_dimension(plan_dims, "x"), "y": _plan_dimension(plan_dims, "y")},
        "seismic_weight_kn": weight_kn,
        "weight_excluded_at_base_kn": sum(row["w_kn"] for row in at_base),
        "ll_fraction": {str(row["storey"]): row["ll_fraction"] for row in rows},
        "storey_weights": [
            {
                "storey": row["storey"],
                "w_dl_kn": row["w_dl_kn"],
                "w_ll_kn": row["w_ll_kn"],
                "ll_basis_kpa": row["ll_basis_kpa"],
                "ll_basis_assumed": bool(row.get("ll_basis_assumed", False)),
                "ll_fraction": row["ll_fraction"],
                "ll_fraction_source": row["ll_fraction_source"],
                "w_ll_seismic_kn": row["w_ll_seismic_kn"],
                "w_kn": row["w_kn"],
                "z_top_m": row["z_top_m"],
                "h_i_m": row["h_i_m"],
                "above_base": row["h_i_m"] > _TINY,
            }
            for row in rows
        ],
        "directions": directions,
        "cases": [case["name"] for case in cases],
        "limits": {
            "vertical_earthquake": "not computed in v1 (Cl 6.4.6)",
            "dynamic_analysis": "not computed in v1 (Cl 7.7)",
            "torsion": "static eccentricity and the Cl 7.8.2 branches come from analysis/diaphragm.py",
        },
        "disclosures": log.to_dict(),
    }
    if into is not None:
        into.extend(log.entries)
    return cases, report
