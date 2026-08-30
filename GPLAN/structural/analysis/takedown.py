"""Gravity load takedown: the v1 analysis workhorse (spec section 12).

`run(model, loadmodel, opts)` walks the placed model top-down, per unfactored
case (DL / LL / LLR kept separate so combinations factor at consumption):

    1. slab panels split to their edges (two-way 45-degree triangles and
       trapezoids with peak w lx/2, one-way strips, cantilever full to the
       backing edge) and land on the supporting beams and walls as exact
       piecewise-linear loads;
    2. collinear beams form continuous runs; secondary runs are analyzed first
       and their reactions frame into the primaries as point loads (the
       dependency graph must be acyclic: a cycle is an E_FRAMING_DEPTH hard
       fail);
    3. every run is solved exactly by the three-moment (Clapeyron) equations
       with pattern live loading; where the IS 456 Cl 22.5.1 Table 12/13
       coefficient method is applicable it supplies the DESIGN stations
       (method "coeff") while support reactions always come from the exact
       all-spans-loaded solve, so the conservation invariant holds exactly
       (Table 13 shears deliberately over-cover reactions and would break it);
    4. reactions stack down columns (self weight added per storey, height
       floor to floor per the registered N_COLUMN_HEIGHT_CONVENTION) and walls
       (loads averaged over the bearing length, centrelines within t/2), with
       the IS 875-2 Cl 3.2.1 live reduction applied member-wise at the ledger,
       never to slab or beam design forces;
    5. masonry walls get WallStress{n_kn_m, e_m, e_over_t}: eccentricity by
       moment summation of the loads arriving at the wall top, slab edge
       reactions applied at t/6 from the centreline toward their panel
       (centre-third bearing model), so an exterior one-side bearing reads
       e = t/6 and an interior wall loaded both sides reads ~0;
    6. footing loads per column stack {p_dl_kn, p_ll_reduced_kn} and per
       bearing wall n per metre at plinth.

Conservation invariant (hard): per case, the base column + wall gravity total
equals the applied total within `opts["conservation_tol"]` (default 0.5%),
else E_ANA_CONSERVATION is disclosed on the model ladder and raised. Nothing
is ever silently dropped: loads addressed to unknown elements raise
E_BAD_ENVELOPE.

Storey conventions consumed here (documented for the placement wave):
    * a Beam / SlabPanel of storey i sits at FLOOR LEVEL i, the top of storey
      i's structure; a Column of storey i spans storey i and its top joint is
      at floor level i;
    * a WallLine of storey i stands on floor level i-1 (a PARAPET on level i);
      `loads.dead.find_wall_support` is the one owner of the bearing search;
    * plinth beams (BeamKind.PLINTH) of storey i sit at the BASE of storey i.

`TakedownResult.storey_ledger` feeds the seismic builder (parallel work). Its
exact shape is {storey: {"w_dl_kn": float, "w_ll_kn": float,
"ll_fraction_basis_kpa": float, "z_m": float}} where `storey` is the FLOOR
LEVEL index, w_dl tallies the full dead load at that level (slabs, beams,
finishes, and walls / columns half a storey up plus half down; the ground
halves go to the foundation, not to any level), w_ll tallies the floor imposed
load at the level (roof imposed, LLR, is excluded per IS 1893 Cl 7.3.2), and
ll_fraction_basis_kpa is the largest panel imposed pressure at the level (the
Table 10 fraction selector). z_m is the level height from Storey.bottom_z_m +
height_m (critic resolution 2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..codes.trace import TraceEntry, clause, trace_into
from ..data._loader import load_yaml

_STAGE = "analysis.takedown"

#: Gauss-Legendre 3-point rule on [-1, 1]; exact to polynomial degree 5, which
#: covers x * M0(x) with M0 cubic (linearly varying load) inside every piece.
_GAUSS_X = (-math.sqrt(3.0 / 5.0), 0.0, math.sqrt(3.0 / 5.0))
_GAUSS_W = (5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0)

_EPS = 1e-9


class AnalysisError(RuntimeError):
    """A registered hard-fail condition; `code` is a model.REGISTRY key."""

    def __init__(self, code: str, message: str, element_ids: Sequence[str] = ()):
        super(AnalysisError, self).__init__(code + ": " + message)
        self.code = code
        self.message = message
        self.element_ids = list(element_ids)


# ---------------------------------------------------------------------------
# clause callables: equivalent UDL conversions and the IS 456 tables
# ---------------------------------------------------------------------------


@clause(
    code="SP 24:1983",
    ref="IS 456 Cl 24.5 commentary",
    title="Equivalent UDL of a triangular slab share, bending",
    symbol="w_eq,b",
    units="kN/m",
)
def eq_udl_triangle_bending(w_kpa: float, lx_m: float) -> float:
    """w lx / 3: the UDL giving the same midspan moment as the triangle."""
    return float(w_kpa) * float(lx_m) / 3.0


@clause(
    code="SP 24:1983",
    ref="IS 456 Cl 24.5 commentary",
    title="Equivalent UDL of a triangular slab share, shear",
    symbol="w_eq,v",
    units="kN/m",
)
def eq_udl_triangle_shear(w_kpa: float, lx_m: float) -> float:
    """w lx / 4: the UDL giving the same end shear as the triangle."""
    return float(w_kpa) * float(lx_m) / 4.0


@clause(
    code="SP 24:1983",
    ref="IS 456 Cl 24.5 commentary",
    title="Equivalent UDL of a trapezoidal slab share, bending",
    symbol="w_eq,b",
    units="kN/m",
)
def eq_udl_trapezoid_bending(w_kpa: float, lx_m: float, r: float) -> float:
    """(w lx / 2)(1 - 1/(3 r^2)) with r = ly/lx >= 1."""
    ratio = max(float(r), 1.0)
    return 0.5 * float(w_kpa) * float(lx_m) * (1.0 - 1.0 / (3.0 * ratio * ratio))


@clause(
    code="SP 24:1983",
    ref="IS 456 Cl 24.5 commentary",
    title="Equivalent UDL of a trapezoidal slab share, shear",
    symbol="w_eq,v",
    units="kN/m",
)
def eq_udl_trapezoid_shear(w_kpa: float, lx_m: float, r: float) -> float:
    """(w lx / 2)(1 - 1/(2 r)) with r = ly/lx >= 1."""
    ratio = max(float(r), 1.0)
    return 0.5 * float(w_kpa) * float(lx_m) * (1.0 - 1.0 / (2.0 * ratio))


#: IS 456:2000 Table 13 shear coefficients on w l, transcribed from the spec
#: (the printed table; the moment coefficients live in data/is456_tables.yaml).
_TABLE13 = {
    "end_support": {"dead": 0.4, "imposed": 0.45},
    "penultimate_outer": {"dead": 0.6, "imposed": 0.6},
    "penultimate_inner": {"dead": 0.55, "imposed": 0.6},
    "interior": {"dead": 0.5, "imposed": 0.6},
}

_TABLE12_KEYS = {
    "span_end": "span_end",
    "span_interior": "span_interior",
    "support_near_end": "support_near_end",
    "support_interior": "support_interior",
}


@clause(code="IS 456:2000", ref="Table 12", title="Bending moment coefficients for continuous beams", symbol="alpha_m", units="")
def table12_alpha(position: str, case: str) -> float:
    """Moment coefficient on w l^2 (Cl 22.5.1); `case` is 'dead' or 'imposed'."""
    table = load_yaml("is456_tables")["table_12_moment_coefficients"]
    block = table["dead_and_imposed_fixed"] if str(case) == "dead" else table["imposed_not_fixed"]
    key = _TABLE12_KEYS.get(str(position))
    if key is None:
        raise KeyError("unknown Table 12 position: " + repr(str(position)))
    return float(block[key])


@clause(code="IS 456:2000", ref="Table 13", title="Shear force coefficients for continuous beams", symbol="alpha_v", units="")
def table13_alpha(position: str, case: str) -> float:
    """Shear coefficient on w l (Cl 22.5.1); `case` is 'dead' or 'imposed'."""
    block = _TABLE13.get(str(position))
    if block is None:
        raise KeyError("unknown Table 13 position: " + repr(str(position)))
    return float(block["dead" if str(case) == "dead" else "imposed"])


# ---------------------------------------------------------------------------
# exact continuous-run analysis (three-moment / Clapeyron)
# ---------------------------------------------------------------------------


@dataclass
class SpanLoading:
    """Loads on one span, span-local x from the LEFT support, metres and kN.

    `segs` are (a, b, w1, w2): linearly varying distributed load w1 at a to w2
    at b, kN/m; segments may overlap (they sum).  `points` are (x, P) kN.
    """

    length_m: float
    segs: List[Tuple[float, float, float, float]] = field(default_factory=list)
    points: List[Tuple[float, float]] = field(default_factory=list)

    def total_kn(self) -> float:
        total = sum(0.5 * (w1 + w2) * (b - a) for a, b, w1, w2 in self.segs)
        return total + sum(p for _, p in self.points)

    def point_total_kn(self) -> float:
        return sum(abs(p) for _, p in self.points)

    def breakpoints(self) -> List[float]:
        stations = set([0.0, self.length_m])
        for a, b, _, _ in self.segs:
            stations.add(min(max(a, 0.0), self.length_m))
            stations.add(min(max(b, 0.0), self.length_m))
        for x, _ in self.points:
            stations.add(min(max(x, 0.0), self.length_m))
        return sorted(stations)

    # -- closed-form simple-span statics -----------------------------------

    def _first_moment_kn_m(self) -> float:
        """Sum of load * distance-from-left-end."""
        total = 0.0
        for a, b, w1, w2 in self.segs:
            if b <= a:
                continue
            slope = (w2 - w1) / (b - a)
            total += w1 * (b * b - a * a) / 2.0 + slope * ((b ** 3 - a ** 3) / 3.0 - a * (b * b - a * a) / 2.0)
        for x, p in self.points:
            total += p * x
        return total

    def r_left_kn(self) -> float:
        """Simple-span left reaction (loads positive downward)."""
        if self.length_m <= 0.0:
            return 0.0
        return self.total_kn() - self._first_moment_kn_m() / self.length_m

    def load_upto(self, x: float, inclusive: bool = True) -> float:
        """Distributed + point load between 0 and x."""
        total = 0.0
        for a, b, w1, w2 in self.segs:
            u = min(x, b)
            if u <= a:
                continue
            slope = (w2 - w1) / (b - a)
            total += w1 * (u - a) + 0.5 * slope * (u - a) * (u - a)
        for t, p in self.points:
            if t < x - _EPS or (inclusive and abs(t - x) <= _EPS):
                total += p
        return total

    def moment_of_loads_about(self, x: float) -> float:
        """Moment about station x of every load left of x."""
        total = 0.0
        for a, b, w1, w2 in self.segs:
            u = min(x, b)
            if u <= a:
                continue
            slope = (w2 - w1) / (b - a)
            load = w1 * (u - a) + 0.5 * slope * (u - a) * (u - a)
            first = w1 * (u * u - a * a) / 2.0 + slope * ((u ** 3 - a ** 3) / 3.0 - a * (u * u - a * a) / 2.0)
            total += x * load - first
        for t, p in self.points:
            if t <= x + _EPS:
                total += p * (x - t)
        return total

    def m0_at(self, x: float) -> float:
        """Simple-span sagging moment at x."""
        return self.r_left_kn() * x - self.moment_of_loads_about(x)

    def v0_at(self, x: float, side: str = "+") -> float:
        """Simple-span shear at x; side '+' just right of x, '-' just left."""
        return self.r_left_kn() - self.load_upto(x, inclusive=(side == "+"))

    def w_at(self, x: float) -> float:
        """Total distributed intensity at x (sum of active segments)."""
        total = 0.0
        for a, b, w1, w2 in self.segs:
            if a - _EPS <= x <= b + _EPS and b > a:
                total += w1 + (w2 - w1) * (min(max(x, a), b) - a) / (b - a)
        return total

    def weighted_integrals(self) -> Tuple[float, float]:
        """(int M0 x/L dx, int M0 (1 - x/L) dx) via exact Gauss per piece."""
        length = self.length_m
        if length <= 0.0:
            return (0.0, 0.0)
        right = 0.0
        left = 0.0
        stations = self.breakpoints()
        for i in range(len(stations) - 1):
            a, b = stations[i], stations[i + 1]
            if b - a <= _EPS:
                continue
            half = 0.5 * (b - a)
            mid = 0.5 * (a + b)
            for gx, gw in zip(_GAUSS_X, _GAUSS_W):
                x = mid + half * gx
                m0 = self.m0_at(x)
                right += gw * half * m0 * (x / length)
                left += gw * half * m0 * (1.0 - x / length)
        return (right, left)


def _thomas(sub: List[float], diag: List[float], sup: List[float], rhs: List[float]) -> List[float]:
    """Tridiagonal solve (Thomas algorithm), plain deterministic floats."""
    n = len(diag)
    if n == 0:
        return []
    c = list(sup)
    d = list(rhs)
    b = list(diag)
    for i in range(1, n):
        if abs(b[i - 1]) <= _EPS:
            raise AnalysisError("E_FRAMING_DEPTH", "singular three-moment system")
        m = sub[i] / b[i - 1]
        b[i] = b[i] - m * c[i - 1]
        d[i] = d[i] - m * d[i - 1]
    x = [0.0] * n
    if abs(b[n - 1]) <= _EPS:
        raise AnalysisError("E_FRAMING_DEPTH", "singular three-moment system")
    x[n - 1] = d[n - 1] / b[n - 1]
    for i in range(n - 2, -1, -1):
        x[i] = (d[i] - c[i] * x[i + 1]) / b[i]
    return x


def solve_support_moments(spans: Sequence[SpanLoading], m_left: float = 0.0, m_right: float = 0.0) -> List[float]:
    """Support moments M_0..M_n for a continuous run, knife-edge ends.

    Three-moment equation at each interior support i (spans i and i+1,
    1-based): L_i M_{i-1} + 2 (L_i + L_{i+1}) M_i + L_{i+1} M_{i+1}
    = -6 (S_right(span i) + S_left(span i+1)) where S_right integrates
    M0 x/L over the left span and S_left integrates M0 (1 - x/L) over the
    right span.  `m_left` / `m_right` are known end moments (cantilever
    back-moments); sagging positive throughout.
    """
    n = len(spans)
    if n == 0:
        return []
    if n == 1:
        return [m_left, m_right]
    weighted = [span.weighted_integrals() for span in spans]
    sub = [0.0] * (n - 1)
    diag = [0.0] * (n - 1)
    sup = [0.0] * (n - 1)
    rhs = [0.0] * (n - 1)
    for i in range(1, n):
        l1 = spans[i - 1].length_m
        l2 = spans[i].length_m
        row = i - 1
        diag[row] = 2.0 * (l1 + l2)
        if row > 0:
            sub[row] = l1
        if row < n - 2:
            sup[row] = l2
        rhs[row] = -6.0 * (weighted[i - 1][0] + weighted[i][1])
        if i == 1:
            rhs[row] -= l1 * m_left
        if i == n - 1:
            rhs[row] -= l2 * m_right
    interior = _thomas(sub, diag, sup, rhs)
    return [m_left] + interior + [m_right]


@dataclass
class SpanResult:
    """Solved span: end moments, shears, extremes and evaluators."""

    loading: SpanLoading
    m_left: float
    m_right: float

    def _shear_shift(self) -> float:
        if self.loading.length_m <= 0.0:
            return 0.0
        return (self.m_right - self.m_left) / self.loading.length_m

    def m_at(self, x: float) -> float:
        length = self.loading.length_m
        if length <= 0.0:
            return self.m_left
        return self.loading.m0_at(x) + self.m_left * (1.0 - x / length) + self.m_right * (x / length)

    def v_at(self, x: float, side: str = "+") -> float:
        return self.loading.v0_at(x, side) + self._shear_shift()

    def reaction_left(self) -> float:
        return self.v_at(0.0, "+")

    def reaction_right(self) -> float:
        return -self.v_at(self.loading.length_m, "-")

    def extreme_moments(self) -> Tuple[float, float]:
        """(max, min) bending moment anywhere in the span, exact.

        Candidates: piece breakpoints plus the stationary points where the
        (quadratic within a piece) shear crosses zero.
        """
        stations = self.loading.breakpoints()
        candidates = list(stations)
        shift = self._shear_shift()
        for i in range(len(stations) - 1):
            a, b = stations[i], stations[i + 1]
            if b - a <= _EPS:
                continue
            v0 = self.loading.v0_at(a, "+") + shift
            wa = self.loading.w_at(a + _EPS)
            wb = self.loading.w_at(b - _EPS)
            slope = (wb - wa) / (b - a) if b > a else 0.0
            # V(a + t) = v0 - (wa t + slope t^2 / 2) = 0
            if abs(slope) <= _EPS:
                if abs(wa) > _EPS:
                    t = v0 / wa
                    if _EPS < t < (b - a) - _EPS:
                        candidates.append(a + t)
            else:
                disc = wa * wa + 2.0 * slope * v0
                if disc >= 0.0:
                    root = math.sqrt(disc)
                    for t in ((-wa + root) / slope, (-wa - root) / slope):
                        if _EPS < t < (b - a) - _EPS:
                            candidates.append(a + t)
        values = [self.m_at(x) for x in sorted(set(candidates))]
        return (max(values), min(values))


def solve_run_exact(spans: Sequence[SpanLoading], m_left: float = 0.0, m_right: float = 0.0) -> List[SpanResult]:
    """Solve a continuous run; returns one SpanResult per span."""
    moments = solve_support_moments(spans, m_left, m_right)
    return [SpanResult(loading=span, m_left=moments[i], m_right=moments[i + 1]) for i, span in enumerate(spans)]


def run_reactions(results: Sequence[SpanResult]) -> List[float]:
    """Support reactions R_0..R_n of a solved run (downward loads positive)."""
    n = len(results)
    if n == 0:
        return []
    reactions = [0.0] * (n + 1)
    for i, res in enumerate(results):
        reactions[i] += res.reaction_left()
        reactions[i + 1] += res.reaction_right()
    return reactions


def solve_continuous(spans_input: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Public exact-analysis entry for tests and callers outside the takedown.

    `spans_input` is [{"l": length_m, "segs": [(a, b, w1, w2)...],
    "points": [(x, P)...]}, ...].  Returns {"support_moments": [...],
    "reactions": [...], "spans": [{"m_mid", "m_max", "m_min", "m_sup_l",
    "m_sup_r", "v_l", "v_r"}, ...]}, sagging positive, kN / kNm.
    """
    spans = [
        SpanLoading(
            length_m=float(s["l"]),
            segs=[(float(a), float(b), float(w1), float(w2)) for a, b, w1, w2 in s.get("segs", [])],
            points=[(float(x), float(p)) for x, p in s.get("points", [])],
        )
        for s in spans_input
    ]
    results = solve_run_exact(spans)
    moments = [results[0].m_left] + [r.m_right for r in results] if results else []
    out_spans = []
    for res in results:
        m_max, m_min = res.extreme_moments()
        out_spans.append(
            {
                "m_mid": res.m_at(0.5 * res.loading.length_m),
                "m_max": m_max,
                "m_min": m_min,
                "m_sup_l": res.m_left,
                "m_sup_r": res.m_right,
                "v_l": res.v_at(0.0, "+"),
                "v_r": res.v_at(res.loading.length_m, "-"),
            }
        )
    return {"support_moments": moments, "reactions": run_reactions(results), "spans": out_spans}


# ---------------------------------------------------------------------------
# takedown data shapes
# ---------------------------------------------------------------------------

_DP = 6


def _r(value: float) -> float:
    return round(float(value), _DP) + 0.0


@dataclass
class WallStress:
    """Per-storey masonry wall resultant feeding IS 1905 (spec step 7).

    `n_kn_m` is the service axial at the wall BASE per metre (DL + LL + LLR,
    unreduced, self weight included); `e_m` is the resultant eccentricity of
    the loads arriving at the wall TOP (slab edge reactions at t/6 from the
    centreline toward their panel, wall-above transfers at their centreline
    offset, beam bearings centred), so an exterior wall carrying one slab
    reads e = t/6 and an interior wall loaded from both sides reads ~0.
    """

    wall_id: str
    storey: int
    n_kn_m: float
    e_m: float
    e_over_t: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "storey": int(self.storey),
            "n_kn_m": _r(self.n_kn_m),
            "e_m": _r(self.e_m),
            "e_over_t": _r(self.e_over_t),
        }


@dataclass
class TakedownResult:
    """Everything the gravity takedown produced; `to_dict()` rides on
    model.analysis (critic resolution 14) merged by the orchestrator."""

    storey_ledger: Dict[int, Dict[str, float]] = field(default_factory=dict)
    beam_runs: List[Dict[str, Any]] = field(default_factory=list)
    column_loads: List[Dict[str, Any]] = field(default_factory=list)
    wall_stresses: List[WallStress] = field(default_factory=list)
    footing_loads: Dict[str, Any] = field(default_factory=dict)
    conservation: Dict[str, Dict[str, float]] = field(default_factory=dict)
    envelopes: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    log: Any = None

    def to_dict(self) -> Dict[str, Any]:
        from ..model import DisclosureLog

        log = self.log if self.log is not None else DisclosureLog()
        return {
            "storey_ledger": {
                str(level): {key: _r(val) for key, val in sorted(row.items())}
                for level, row in sorted(self.storey_ledger.items())
            },
            "beam_runs": [dict(runrec) for runrec in self.beam_runs],
            "column_loads": [dict(entry) for entry in self.column_loads],
            "wall_stresses": [ws.to_dict() for ws in self.wall_stresses],
            "footing_loads": {
                "columns": {
                    key: {k: _r(v) for k, v in sorted(val.items())}
                    for key, val in sorted(self.footing_loads.get("columns", {}).items())
                },
                "walls": {
                    key: {k: _r(v) for k, v in sorted(val.items())}
                    for key, val in sorted(self.footing_loads.get("walls", {}).items())
                },
            },
            "conservation": {
                case: {k: _r(v) for k, v in sorted(row.items())}
                for case, row in sorted(self.conservation.items())
            },
            "envelopes": {eid: self.envelopes[eid].to_dict() for eid in sorted(self.envelopes)},
            "trace": [dict(entry) for entry in self.trace],
            "disclosures": log.to_dict(),
        }


def check_conservation(
    case_name: str,
    applied_kn: float,
    base_kn: float,
    tol: float,
) -> Dict[str, float]:
    """The hard invariant: base gravity equals applied gravity within `tol`.

    Returns the conservation record; raises AnalysisError("E_ANA_CONSERVATION")
    when the relative error exceeds the tolerance (never a silent wrong
    answer).  Exposed for tests.
    """
    scale = max(abs(applied_kn), 1e-6)
    rel = abs(base_kn - applied_kn) / scale
    if rel > tol:
        raise AnalysisError(
            "E_ANA_CONSERVATION",
            "case %s: applied %.3f kN but base receives %.3f kN (%.2f%% off, tolerance %.2f%%)"
            % (case_name, applied_kn, base_kn, 100.0 * rel, 100.0 * tol),
        )
    return {"applied_kn": applied_kn, "base_kn": base_kn, "rel_err": rel}


# ---------------------------------------------------------------------------
# model indexing: lines, runs, supports
# ---------------------------------------------------------------------------

from ..codes import is875
from ..loads import CASE_DL, CASE_LL, CASE_LLR, LoadModel
from ..loads.dead import beam_axis, find_wall_support
from ..model import (
    Beam,
    BeamKind,
    Column,
    DisclosureLog,
    StructuralModel,
    System,
    WallLine,
    WallRole,
    footing_id,
    polygon_rect,
    wall_axis,
)
from . import ForceEnvelope, StationForces

_GRAVITY_CASES = (CASE_DL, CASE_LL, CASE_LLR)
_IMPOSED_CASES = (CASE_LL, CASE_LLR)
_MASONRY_SYSTEMS = (System.LOAD_BEARING_MASONRY, System.CONFINED_MASONRY, System.MIXED)

_CHAIN_TOL_M = 0.002
_SUPPORT_TOL_M = 0.02
_FRAME_INSET_M = 0.05
_EDGE_ALIGN_M = 0.145  # half a one-brick wall plus a hair; edge-member window
_FULL_COVER = 0.99
_SPAN_MATCH = 0.02  # fraction of span for full-span shape matching


def _quant(value_m: float) -> int:
    return int(round(float(value_m) * 1000.0))


def _to_xy(orient: str, pos_m: float, s_m: float) -> Tuple[float, float]:
    """Plan point of line coordinate s on the line (orient, pos)."""
    return (s_m, pos_m) if orient == "h" else (pos_m, s_m)


def _along(orient: str, x_m: float, y_m: float) -> float:
    return x_m if orient == "h" else y_m


@dataclass
class _Support:
    x_m: float
    kind: str  # "column" | "wall" | "frame"
    target_id: str = ""


@dataclass
class _Run:
    run_id: str
    storey: int
    orient: str
    pos_m: float
    beams: List[Beam]
    lo_m: float
    hi_m: float
    plinth: bool = False
    supports: List[_Support] = field(default_factory=list)
    spans: List[Tuple[float, float]] = field(default_factory=list)
    overhang_left: Optional[Tuple[float, float]] = None
    overhang_right: Optional[Tuple[float, float]] = None
    segs: Dict[str, List[Tuple[float, float, float, float]]] = field(default_factory=dict)
    pts: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)
    items: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    method: str = "exact"
    method_reason: str = ""

    def add_seg(self, case: str, ga: float, gb: float, w1: float, w2: float, tag: Optional[Dict[str, Any]] = None) -> None:
        if gb <= ga + _EPS:
            return
        self.segs.setdefault(case, []).append((ga, gb, w1, w2))
        item = dict(tag) if tag else {"tag": "gen"}
        item["ga"] = ga
        item["gb"] = gb
        self.items.setdefault(case, []).append(item)

    def add_pt(self, case: str, gx: float, p_kn: float) -> None:
        if p_kn == 0.0:
            return
        self.pts.setdefault(case, []).append((gx, p_kn))
        self.items.setdefault(case, []).append({"tag": "pt", "ga": gx, "gb": gx, "p": p_kn})


def _wall_supports_beams(model: StructuralModel, wall: WallLine) -> bool:
    """A wall counts as a RUN support only when it is a bearing wall."""
    if wall.role in (WallRole.PARAPET, WallRole.RAILING):
        return False
    if wall.bearing is True:
        return True
    if wall.bearing is False:
        return False
    return model.system in _MASONRY_SYSTEMS


def _column_at(columns: Sequence[Column], x_m: float, y_m: float) -> Optional[Column]:
    for col in columns:
        tol = 0.5 * max(col.width_m, col.depth_m) + _SUPPORT_TOL_M
        if abs(col.x_m - x_m) <= tol and abs(col.y_m - y_m) <= tol:
            return col
    return None


def _bearing_wall_at(model: StructuralModel, walls: Sequence[WallLine], x_m: float, y_m: float) -> Optional[WallLine]:
    for wall in walls:
        if not _wall_supports_beams(model, wall):
            continue
        axis = wall_axis(wall)
        if axis is None:
            continue
        orient, pos, s0, s1 = axis
        across = y_m if orient == "h" else x_m
        along = x_m if orient == "h" else y_m
        if abs(across - pos) <= 0.5 * wall.thickness_m + _SUPPORT_TOL_M and s0 - _SUPPORT_TOL_M <= along <= s1 + _SUPPORT_TOL_M:
            return wall
    return None


def _framing_target(beams: Sequence[Beam], self_ids: Sequence[str], orient: str, pos_m: float, s_m: float) -> Optional[Beam]:
    """A perpendicular beam whose span strictly contains the point."""
    x_m, y_m = _to_xy(orient, pos_m, s_m)
    for beam in beams:
        if beam.id in self_ids:
            continue
        axis = beam_axis(beam)
        if axis is None or axis[0] == orient:
            continue
        b_orient, b_pos, b0, b1 = axis
        across = y_m if b_orient == "h" else x_m
        along = x_m if b_orient == "h" else y_m
        if abs(across - b_pos) > 0.5 * beam.width_m + _SUPPORT_TOL_M:
            continue
        if b0 + _FRAME_INSET_M < along < b1 - _FRAME_INSET_M:
            return beam
    return None


def _build_runs(model: StructuralModel, storey: int, log: DisclosureLog) -> List["_Run"]:
    """Collinear beams of one storey chained into continuous runs."""
    groups = {}  # type: Dict[Tuple[str, int, bool], List[Tuple[float, float, Beam]]]
    for beam in sorted(model.beams_on(storey), key=lambda b: b.id):
        axis = beam_axis(beam)
        if axis is None:
            raise AnalysisError("E_BAD_ENVELOPE", "beam %s is not axis aligned" % beam.id, [beam.id])
        orient, pos, s0, s1 = axis
        key = (orient, _quant(pos), beam.kind == BeamKind.PLINTH)
        groups.setdefault(key, []).append((s0, s1, beam))

    columns = sorted(model.columns_on(storey), key=lambda c: c.id)
    walls = sorted(model.walls_on(storey), key=lambda w: w.id)
    all_beams = sorted(model.beams_on(storey), key=lambda b: b.id)

    runs = []  # type: List[_Run]
    for key in sorted(groups):
        orient, pos_mm, plinth = key
        pos = pos_mm / 1000.0
        intervals = sorted(groups[key], key=lambda e: (e[0], e[1], e[2].id))
        chains = []  # type: List[List[Tuple[float, float, Beam]]]
        for entry in intervals:
            if chains and entry[0] <= max(e[1] for e in chains[-1]) + _CHAIN_TOL_M:
                chains[-1].append(entry)
            else:
                chains.append([entry])
        for index, chain in enumerate(chains):
            beams = [b for _, _, b in chain]
            lo = min(e[0] for e in chain)
            hi = max(e[1] for e in chain)
            run = _Run(
                run_id="run-s%d-%s%d-%02d" % (storey, orient, pos_mm, index),
                storey=storey,
                orient=orient,
                pos_m=pos,
                beams=beams,
                lo_m=lo,
                hi_m=hi,
                plinth=plinth,
            )
            # candidate support stations: every beam end
            stations = sorted(set([_quant(e[0]) for e in chain] + [_quant(e[1]) for e in chain]))
            self_ids = [b.id for b in beams]
            supports = []  # type: List[_Support]
            for st_mm in stations:
                s = st_mm / 1000.0
                x_m, y_m = _to_xy(orient, pos, s)
                col = _column_at(columns, x_m, y_m)
                if col is not None:
                    supports.append(_Support(x_m=s, kind="column", target_id=col.id))
                    continue
                wall = _bearing_wall_at(model, walls, x_m, y_m)
                if wall is not None:
                    supports.append(_Support(x_m=s, kind="wall", target_id=wall.id))
                    continue
                if st_mm in (_quant(lo), _quant(hi)):
                    target = _framing_target(all_beams, self_ids, orient, pos, s)
                    if target is not None:
                        supports.append(_Support(x_m=s, kind="frame", target_id=target.id))
                # otherwise an interior joint: continuity, the spans merge
            # dedupe supports by position
            seen = {}  # type: Dict[int, _Support]
            for support in supports:
                seen.setdefault(_quant(support.x_m), support)
            run.supports = [seen[k] for k in sorted(seen)]
            if not run.supports:
                raise AnalysisError(
                    "E_TRANSFER_REQUIRED",
                    "beam run %s has no support (no column, bearing wall or framing target)" % run.run_id,
                    self_ids,
                )
            xs = [s.x_m for s in run.supports]
            run.spans = [(xs[i], xs[i + 1]) for i in range(len(xs) - 1)]
            if xs[0] - lo > _SUPPORT_TOL_M:
                run.overhang_left = (lo, xs[0])
            if hi - xs[-1] > _SUPPORT_TOL_M:
                run.overhang_right = (xs[-1], hi)
            if run.overhang_left or run.overhang_right:
                log.add(
                    "W_CANTILEVER",
                    "run %s carries a cantilever overhang; edge torsion is not computed in v1" % run.run_id,
                    self_ids,
                    stage=_STAGE,
                )
            runs.append(run)
    return runs


def _topo_order(runs: Sequence["_Run"], beam_to_run: Dict[str, "_Run"]) -> List["_Run"]:
    """Secondaries before the primaries they frame into; cycles hard-fail."""
    order_key = {run.run_id: i for i, run in enumerate(sorted(runs, key=lambda r: r.run_id))}
    dependants = {run.run_id: [] for run in runs}  # type: Dict[str, List[str]]
    indegree = {run.run_id: 0 for run in runs}
    by_id = {run.run_id: run for run in runs}
    for run in sorted(runs, key=lambda r: r.run_id):
        for support in run.supports:
            if support.kind != "frame":
                continue
            target_run = beam_to_run.get(support.target_id)
            if target_run is None or target_run.run_id == run.run_id:
                continue
            dependants[run.run_id].append(target_run.run_id)
            indegree[target_run.run_id] += 1
    ready = sorted([rid for rid, deg in indegree.items() if deg == 0], key=lambda r: order_key[r])
    out = []  # type: List[_Run]
    while ready:
        rid = ready.pop(0)
        out.append(by_id[rid])
        for nxt in sorted(dependants[rid], key=lambda r: order_key[r]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda r: order_key[r])
    if len(out) != len(runs):
        cyclic = sorted(rid for rid, deg in indegree.items() if deg > 0)
        raise AnalysisError(
            "E_FRAMING_DEPTH",
            "secondary framing is cyclic; runs cannot be ordered: " + ", ".join(cyclic),
            cyclic,
        )
    return out


# ---------------------------------------------------------------------------
# panel -> edge split (spec step 1 and 2)
# ---------------------------------------------------------------------------


def _edge_support_members(
    model: StructuralModel, storey: int, orient: str, pos_m: float, lo_m: float, hi_m: float
) -> List[Tuple[Any, float, float, bool]]:
    """(element, overlap_lo, overlap_hi, is_beam) along a panel edge.

    Beams take precedence; walls (any role but parapet / railing) fill only the
    stretches no beam covers, so an RC slab edge never double-loads a wall
    under its beam.
    """
    members = []  # type: List[Tuple[Any, float, float, bool]]
    covered = []  # type: List[Tuple[float, float]]
    for beam in sorted(model.beams_on(storey), key=lambda b: b.id):
        if beam.kind == BeamKind.PLINTH:
            continue
        axis = beam_axis(beam)
        if axis is None or axis[0] != orient:
            continue
        if abs(axis[1] - pos_m) > max(_EDGE_ALIGN_M, 0.5 * beam.width_m + _SUPPORT_TOL_M):
            continue
        lo = max(lo_m, axis[2])
        hi = min(hi_m, axis[3])
        if hi - lo > _SUPPORT_TOL_M:
            members.append((beam, lo, hi, True))
            covered.append((lo, hi))
    for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
        if wall.role in (WallRole.PARAPET, WallRole.RAILING):
            continue
        axis = wall_axis(wall)
        if axis is None or axis[0] != orient:
            continue
        if abs(axis[1] - pos_m) > 0.5 * wall.thickness_m + _SUPPORT_TOL_M:
            continue
        lo = max(lo_m, axis[2])
        hi = min(hi_m, axis[3])
        if hi - lo <= _SUPPORT_TOL_M:
            continue
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
            if phi - plo > _SUPPORT_TOL_M:
                members.append((wall, plo, phi, False))
    return members


def _profile_ordinate(profile: str, length: float, ramp: float, t: float) -> float:
    """Unit-peak profile ordinate at station t in [0, length]."""
    if length <= 0.0:
        return 0.0
    t = min(max(t, 0.0), length)
    if profile == "uniform":
        return 1.0
    if profile == "triangle":
        half = 0.5 * length
        return 1.0 - abs(t - half) / half if half > 0.0 else 0.0
    if profile == "trapezoid":
        rr = min(ramp, 0.5 * length)
        if rr <= 0.0:
            return 1.0
        return min(1.0, t / rr, (length - t) / rr)
    raise ValueError("unknown profile " + repr(profile))


def _profile_area(profile: str, length: float, ramp: float) -> float:
    """Integral of the unit-peak profile over the edge."""
    if profile == "uniform":
        return length
    if profile == "triangle":
        return 0.5 * length
    if profile == "trapezoid":
        rr = min(ramp, 0.5 * length)
        return length - rr
    raise ValueError("unknown profile " + repr(profile))


def _profile_kink_stations(profile: str, length: float, ramp: float) -> List[float]:
    if profile == "triangle":
        return [0.5 * length]
    if profile == "trapezoid":
        rr = min(ramp, 0.5 * length)
        return sorted(set([rr, length - rr]))
    return []


@dataclass
class _EdgePlan:
    """One panel edge's assignment, computed once per panel geometry."""

    orient: str
    pos_m: float
    lo_m: float
    hi_m: float
    members: List[Tuple[Any, float, float, bool]]
    covered_m: float
    supported: bool
    profile: str = ""
    peak_unit: float = 0.0  # peak per unit q (kPa -> kN/m)
    ramp_m: float = 0.0
    factor: float = 1.0

    def length(self) -> float:
        return self.hi_m - self.lo_m


def _panel_edges(model: StructuralModel, slab: Any) -> List[_EdgePlan]:
    x, y, w, h = polygon_rect(slab.polygon)
    raw = [
        ("h", y, x, x + w),
        ("h", y + h, x, x + w),
        ("v", x, y, y + h),
        ("v", x + w, y, y + h),
    ]
    edges = []  # type: List[_EdgePlan]
    for orient, pos, lo, hi in raw:
        members = _edge_support_members(model, slab.storey, orient, pos, lo, hi)
        covered = sum(mhi - mlo for _, mlo, mhi, _ in members)
        supported = covered >= 0.5 * (hi - lo) - _EPS and (hi - lo) > _EPS
        edges.append(
            _EdgePlan(
                orient=orient,
                pos_m=pos,
                lo_m=lo,
                hi_m=hi,
                members=members,
                covered_m=covered,
                supported=supported,
            )
        )
    return edges


def _opposite(index: int) -> int:
    return {0: 1, 1: 0, 2: 3, 3: 2}[index]


def _assign_edge_profiles(edges: List[_EdgePlan], w_m: float, h_m: float, two_way: bool, log: DisclosureLog, panel_id: str) -> None:
    """Fill profile / peak_unit / ramp / factor per the supported-edge topology.

    Peaks are per unit q; edges 0/1 are the horizontal pair (length w), edges
    2/3 the vertical pair (length h).  lx = min(w, h).  Free edges hand their
    tributary to the opposite edge (a doubled factor), which keeps the split
    exactly load-conserving for every topology; a single supported edge is the
    cantilever backing edge and takes the whole panel one-way.
    """
    lx = min(w_m, h_m)
    supported = [i for i, e in enumerate(edges) if e.supported]
    n = len(supported)
    if n == 0:
        raise AnalysisError("E_TRANSFER_REQUIRED", "slab panel %s has no supported edge" % panel_id, [panel_id])

    horiz_short = w_m <= h_m  # horizontal edges are the short pair when w <= h

    def base_assign() -> None:
        for i, edge in enumerate(edges):
            is_short = (i in (0, 1)) == horiz_short
            if two_way:
                if is_short:
                    edge.profile = "triangle"
                    edge.peak_unit = lx / 2.0
                    edge.ramp_m = 0.0
                else:
                    edge.profile = "trapezoid"
                    edge.peak_unit = lx / 2.0
                    edge.ramp_m = lx / 2.0
            else:
                if is_short:
                    edge.profile = ""
                    edge.peak_unit = 0.0
                else:
                    edge.profile = "uniform"
                    edge.peak_unit = lx / 2.0
                    edge.ramp_m = 0.0
            edge.factor = 1.0

    if n == 4:
        base_assign()
        return
    if n == 3 or n == 2:
        free = [i for i in range(4) if i not in supported]
        if n == 2 and edges[supported[0]].orient == edges[supported[1]].orient:
            # two OPPOSITE supported edges: one-way between them
            span = h_m if edges[supported[0]].orient == "h" else w_m
            for i, edge in enumerate(edges):
                if i in supported:
                    edge.profile = "uniform"
                    edge.peak_unit = span / 2.0
                    edge.ramp_m = 0.0
                    edge.factor = 1.0
                else:
                    edge.profile = ""
                    edge.peak_unit = 0.0
            return
        # three supported, or two ADJACENT supported: reassign each free
        # edge's tributary to its opposite edge
        base_assign()
        for i in free:
            opp = _opposite(i)
            if edges[i].peak_unit > 0.0 and opp in supported:
                edges[opp].factor += edges[i].factor
            edges[i].profile = ""
            edges[i].peak_unit = 0.0
        return
    # n == 1: cantilever, full load one-way to the backing edge
    backing = supported[0]
    depth = h_m if edges[backing].orient == "h" else w_m
    for i, edge in enumerate(edges):
        if i == backing:
            edge.profile = "uniform"
            edge.peak_unit = depth
            edge.ramp_m = 0.0
            edge.factor = 1.0
        else:
            edge.profile = ""
            edge.peak_unit = 0.0
    log.add(
        "W_CANTILEVER",
        "panel %s bears on one edge; full load taken one-way to the backing edge, edge torsion not computed in v1" % panel_id,
        [panel_id],
        stage=_STAGE,
    )


def _emit_edge_case(
    edge: _EdgePlan,
    q_kpa: float,
    case: str,
    beam_to_run: Dict[str, "_Run"],
    wall_books: Dict[str, "_WallBook"],
    lx_m: float,
    r_ratio: float,
    panel_centre_perp: float,
) -> None:
    """Emit one edge's tributary for one case onto its members, exactly.

    Uncovered stretches of the edge are made up by scaling the covered
    ordinates so the edge total is conserved; a triangle or trapezoid landing
    on a single beam that covers the whole edge keeps its shape tag so the
    coefficient method can use the classic equivalent-UDL conversions.
    """
    if not edge.profile or edge.peak_unit <= 0.0 or q_kpa == 0.0:
        return
    length = edge.length()
    peak = q_kpa * edge.peak_unit * edge.factor
    total = peak * _profile_area(edge.profile, length, edge.ramp_m)
    if abs(total) <= _EPS:
        return
    covered_total = 0.0
    for _, mlo, mhi, _ in edge.members:
        stations = sorted(set([mlo, mhi] + [edge.lo_m + k for k in _profile_kink_stations(edge.profile, length, edge.ramp_m) if mlo < edge.lo_m + k < mhi]))
        for i in range(len(stations) - 1):
            a, b = stations[i], stations[i + 1]
            wa = peak * _profile_ordinate(edge.profile, length, edge.ramp_m, a - edge.lo_m)
            wb = peak * _profile_ordinate(edge.profile, length, edge.ramp_m, b - edge.lo_m)
            covered_total += 0.5 * (wa + wb) * (b - a)
    if covered_total <= _EPS:
        raise AnalysisError(
            "E_TRANSFER_REQUIRED",
            "edge at %s=%0.3f of a loaded panel has no covered support length" % (edge.orient, edge.pos_m),
        )
    scale = total / covered_total

    single_full = (
        len(edge.members) == 1
        and edge.members[0][3]
        and (edge.members[0][2] - edge.members[0][1]) >= _FULL_COVER * length
    )
    for element, mlo, mhi, is_beam in edge.members:
        kinks = [edge.lo_m + k for k in _profile_kink_stations(edge.profile, length, edge.ramp_m)]
        stations = sorted(set([mlo, mhi] + [k for k in kinks if mlo < k < mhi]))
        piece_total = 0.0
        pieces = []  # type: List[Tuple[float, float, float, float]]
        for i in range(len(stations) - 1):
            a, b = stations[i], stations[i + 1]
            if b - a <= _EPS:
                continue
            wa = scale * peak * _profile_ordinate(edge.profile, length, edge.ramp_m, a - edge.lo_m)
            wb = scale * peak * _profile_ordinate(edge.profile, length, edge.ramp_m, b - edge.lo_m)
            pieces.append((a, b, wa, wb))
            piece_total += 0.5 * (wa + wb) * (b - a)
        if is_beam:
            run = beam_to_run.get(element.id)
            if run is None:
                raise AnalysisError("E_BAD_ENVELOPE", "beam %s belongs to no run" % element.id, [element.id])
            if single_full and pieces:
                q_eff = q_kpa * edge.factor * scale
                if edge.profile == "uniform":
                    tag = {"tag": "udl", "w": peak * scale}
                elif edge.profile == "triangle":
                    tag = {"tag": "tri", "q": q_eff, "lx": lx_m}
                else:
                    tag = {"tag": "trap", "q": q_eff, "lx": lx_m, "r": r_ratio}
                for a, b, wa, wb in pieces:
                    run.segs.setdefault(case, []).append((a, b, wa, wb))
                tag["ga"] = pieces[0][0]
                tag["gb"] = pieces[-1][1]
                run.items.setdefault(case, []).append(tag)
            else:
                for a, b, wa, wb in pieces:
                    run.add_seg(case, a, b, wa, wb, tag={"tag": "udl", "w": wa} if abs(wa - wb) <= _EPS else {"tag": "gen"})
        else:
            book = wall_books[element.id]
            side = 1.0 if panel_centre_perp > edge.pos_m else -1.0
            lever = element.thickness_m / 6.0
            book.top[case] = book.top.get(case, 0.0) + piece_total
            book.moment[case] = book.moment.get(case, 0.0) + piece_total * lever * side
            book.loaded_top = True


# ---------------------------------------------------------------------------
# per-run solving
# ---------------------------------------------------------------------------


@dataclass
class _WallBook:
    """Per-wall gravity bookkeeping across the takedown."""

    top: Dict[str, float] = field(default_factory=dict)  # arrives at the top
    carried: Dict[str, float] = field(default_factory=dict)  # rides on the wall itself
    moment: Dict[str, float] = field(default_factory=dict)  # signed kNm about the centreline
    loaded_top: bool = False
    floors_in: int = 0
    basis_in: float = 0.0

    def total(self, case: str) -> float:
        return self.top.get(case, 0.0) + self.carried.get(case, 0.0)


def _clip_segs(
    segs: Sequence[Tuple[float, float, float, float]], lo: float, hi: float
) -> List[Tuple[float, float, float, float]]:
    """Segments clipped to [lo, hi], returned span-local."""
    out = []  # type: List[Tuple[float, float, float, float]]
    for ga, gb, w1, w2 in segs:
        a = max(ga, lo)
        b = min(gb, hi)
        if b - a <= _EPS:
            continue
        if gb - ga <= _EPS:
            continue
        wa = w1 + (w2 - w1) * (a - ga) / (gb - ga)
        wb = w1 + (w2 - w1) * (b - ga) / (gb - ga)
        out.append((a - lo, b - lo, wa, wb))
    return out


def _case_loading(
    run: "_Run", case: str, included_spans: Optional[Sequence[int]] = None
) -> Tuple[List[SpanLoading], float, float, List[float]]:
    """(span loadings, m_left, m_right, extra support reactions) for one case.

    `included_spans` filters the pattern for imposed cases; overhang loads and
    loads landing exactly on a support are applied on every pattern.  End
    moments carry the cantilever back-moments of the overhangs.
    """
    segs = run.segs.get(case, [])
    pts = run.pts.get(case, [])
    n = len(run.spans)
    extra = [0.0] * max(len(run.supports), 1)
    spans = []  # type: List[SpanLoading]
    included = set(range(n)) if included_spans is None else set(included_spans)
    support_xs = [s.x_m for s in run.supports]
    for idx, (lo, hi) in enumerate(run.spans):
        loading = SpanLoading(length_m=hi - lo)
        if idx in included:
            loading.segs = _clip_segs(segs, lo, hi)
        spans.append(loading)
    for gx, p in pts:
        placed = False
        for j, sx in enumerate(support_xs):
            if abs(gx - sx) <= _SUPPORT_TOL_M:
                extra[j] += p
                placed = True
                break
        if placed:
            continue
        for idx, (lo, hi) in enumerate(run.spans):
            if lo - _EPS <= gx <= hi + _EPS:
                if idx in included:
                    spans[idx].points.append((min(max(gx - lo, 0.0), hi - lo), p))
                placed = True
                break
        if not placed and run.overhang_left and run.overhang_left[0] - _SUPPORT_TOL_M <= gx <= run.overhang_left[1]:
            placed = True  # handled in the overhang pass below
        if not placed and run.overhang_right and run.overhang_right[0] <= gx <= run.overhang_right[1] + _SUPPORT_TOL_M:
            placed = True
        if not placed:
            raise AnalysisError("E_BAD_ENVELOPE", "point load at %.3f falls outside run %s" % (gx, run.run_id))
    m_left = 0.0
    m_right = 0.0
    if run.overhang_left:
        olo, ohi = run.overhang_left
        pseudo = SpanLoading(length_m=ohi - olo, segs=_clip_segs(segs, olo, ohi))
        for gx, p in pts:
            if olo - _SUPPORT_TOL_M <= gx < ohi - _SUPPORT_TOL_M:
                pseudo.points.append((min(max(gx - olo, 0.0), ohi - olo), p))
        m_left = -pseudo.moment_of_loads_about(pseudo.length_m)
        extra[0] += pseudo.total_kn()
    if run.overhang_right:
        olo, ohi = run.overhang_right
        pseudo = SpanLoading(length_m=ohi - olo, segs=_clip_segs(segs, olo, ohi))
        for gx, p in pts:
            if olo + _SUPPORT_TOL_M < gx <= ohi + _SUPPORT_TOL_M:
                pseudo.points.append((min(max(gx - olo, 0.0), ohi - olo), p))
        m_right = -pseudo._first_moment_kn_m()
        extra[-1] += pseudo.total_kn()
    for loading in spans:
        loading.segs.sort()
        loading.points.sort()
    return (spans, m_left, m_right, extra)


def _extremes_between(result: SpanResult, xa: float, xb: float) -> Tuple[float, float]:
    """(max, min) moment on [xa, xb] of a solved span (span-local coords)."""
    loading = result.loading
    xa = max(0.0, min(xa, loading.length_m))
    xb = max(0.0, min(xb, loading.length_m))
    if xb < xa:
        xa, xb = xb, xa
    stations = [x for x in loading.breakpoints() if xa - _EPS <= x <= xb + _EPS]
    candidates = [xa, xb] + stations
    shift = (result.m_right - result.m_left) / loading.length_m if loading.length_m > 0.0 else 0.0
    pieces = sorted(set([xa, xb] + stations))
    for i in range(len(pieces) - 1):
        a, b = pieces[i], pieces[i + 1]
        if b - a <= _EPS:
            continue
        v0 = loading.v0_at(a, "+") + shift
        wa = loading.w_at(a + _EPS)
        wb = loading.w_at(b - _EPS)
        slope = (wb - wa) / (b - a)
        if abs(slope) <= _EPS:
            if abs(wa) > _EPS:
                t = v0 / wa
                if _EPS < t < (b - a) - _EPS:
                    candidates.append(a + t)
        else:
            disc = wa * wa + 2.0 * slope * v0
            if disc >= 0.0:
                root = math.sqrt(disc)
                for t in ((-wa + root) / slope, (-wa - root) / slope):
                    if _EPS < t < (b - a) - _EPS:
                        candidates.append(a + t)
    values = [result.m_at(x) for x in sorted(set(candidates))]
    return (max(values), min(values))


def _patterns(n_spans: int) -> List[Tuple[str, Tuple[int, ...]]]:
    """Pattern roster: all spans, alternates, adjacent pairs (spec step 4)."""
    out = [("all", tuple(range(n_spans)))]
    if n_spans >= 2:
        out.append(("odd", tuple(range(0, n_spans, 2))))
        out.append(("even", tuple(range(1, n_spans, 2))))
        for k in range(1, n_spans):
            out.append(("adj%d" % k, (k - 1, k)))
    return out


def _span_eq_udl(run: "_Run", case: str, span_idx: int) -> Tuple[float, float]:
    """(bending, shear) equivalent UDL for one span, via the traced clauses."""
    lo, hi = run.spans[span_idx]
    length = hi - lo
    wb = 0.0
    ws = 0.0
    for item in run.items.get(case, []):
        a = max(item["ga"], lo)
        b = min(item["gb"], hi)
        tag = item["tag"]
        if tag == "pt":
            if lo - _SUPPORT_TOL_M < item["ga"] < hi + _SUPPORT_TOL_M and length > 0.0:
                wb += item["p"] / length
                ws += item["p"] / length
            continue
        if b - a <= _EPS:
            continue
        if tag == "udl":
            wb += item["w"]
            ws += item["w"]
        elif tag == "tri":
            wb += eq_udl_triangle_bending(item["q"], item["lx"])
            ws += eq_udl_triangle_shear(item["q"], item["lx"])
        elif tag == "trap":
            wb += eq_udl_trapezoid_bending(item["q"], item["lx"], item["r"])
            ws += eq_udl_trapezoid_shear(item["q"], item["lx"], item["r"])
    return (wb, ws)


def _coeff_applicable(run: "_Run", cases: Sequence[str]) -> Tuple[bool, str]:
    """The Cl 22.5.1 guard: >= 3 spans, spans within 15 percent, UDL-dominant,
    and every shaped item full-span so the classic equivalents apply."""
    n = len(run.spans)
    if n < 3:
        return (False, "%d span(s); the coefficient method needs at least 3" % n)
    lengths = [hi - lo for lo, hi in run.spans]
    longest = max(lengths)
    if min(lengths) < 0.85 * longest - _EPS:
        return (False, "span lengths differ by more than 15 percent")
    if run.overhang_left or run.overhang_right:
        return (False, "run carries a cantilever overhang")
    span_edges = set()
    for lo, hi in run.spans:
        span_edges.add(_quant(lo))
        span_edges.add(_quant(hi))
    for beam in run.beams:
        axis = beam_axis(beam)
        if axis is None:
            continue
        for end in (axis[2], axis[3]):
            if _quant(end) not in span_edges:
                return (False, "beam %s does not start and end on supports" % beam.id)
    for case in cases:
        items = run.items.get(case, [])
        for idx, (lo, hi) in enumerate(run.spans):
            length = hi - lo
            span_total = 0.0
            point_total = 0.0
            for item in items:
                a = max(item["ga"], lo)
                b = min(item["gb"], hi)
                if item["tag"] == "pt":
                    if lo - _SUPPORT_TOL_M < item["ga"] < hi + _SUPPORT_TOL_M:
                        point_total += abs(item["p"])
                        span_total += abs(item["p"])
                    continue
                if b - a <= _EPS:
                    continue
                if item["tag"] == "gen":
                    return (False, "span %d of %s carries an irregular load shape" % (idx, case))
                cover = (b - a) / length if length > 0.0 else 0.0
                if cover < _FULL_COVER:
                    return (False, "span %d of %s carries a partial-span load" % (idx, case))
                if abs(item["ga"] - lo) > _SPAN_MATCH * length or abs(item["gb"] - hi) > _SPAN_MATCH * length:
                    return (False, "span %d of %s carries a load not aligned with the span" % (idx, case))
                if item["tag"] == "udl":
                    span_total += item["w"] * length
                elif item["tag"] == "tri":
                    span_total += eq_udl_triangle_shear(item["q"], item["lx"]) * length
                else:
                    span_total += eq_udl_trapezoid_shear(item["q"], item["lx"], item["r"]) * length
            if span_total > _EPS and point_total > 0.2 * span_total:
                return (False, "span %d of %s is point-load dominant" % (idx, case))
    return (True, "")


def _shear_position(span_idx: int, side: str, n_spans: int) -> str:
    """Table 13 position for the shear at one end of one span."""
    k = span_idx if side == "L" else span_idx + 1
    if k == 0 or k == n_spans:
        return "end_support"
    if k == 1:
        return "penultimate_outer" if side == "R" else "penultimate_inner"
    if k == n_spans - 1:
        return "penultimate_outer" if side == "L" else "penultimate_inner"
    return "interior"


def _moment_support_position(k: int, n_spans: int) -> Optional[str]:
    if k == 0 or k == n_spans:
        return None  # outer end: no coefficient moment
    if k == 1 or k == n_spans - 1:
        return "support_near_end"
    return "support_interior"


# ---------------------------------------------------------------------------
# solving one run
# ---------------------------------------------------------------------------


def _reversed_loading(loading: SpanLoading) -> SpanLoading:
    length = loading.length_m
    return SpanLoading(
        length_m=length,
        segs=sorted((length - b, length - a, w2, w1) for a, b, w1, w2 in loading.segs),
        points=sorted((length - x, p) for x, p in loading.points),
    )


def _overhang_pseudo(run: "_Run", case: str, side: str) -> Optional[SpanLoading]:
    span = run.overhang_left if side == "L" else run.overhang_right
    if span is None:
        return None
    olo, ohi = span
    pseudo = SpanLoading(length_m=ohi - olo, segs=_clip_segs(run.segs.get(case, []), olo, ohi))
    for gx, p in run.pts.get(case, []):
        if olo - _SUPPORT_TOL_M <= gx <= ohi + _SUPPORT_TOL_M:
            inside = olo + _SUPPORT_TOL_M < gx < ohi - _SUPPORT_TOL_M
            at_free_end = (side == "L" and gx <= olo + _SUPPORT_TOL_M) or (side == "R" and gx >= ohi - _SUPPORT_TOL_M)
            if inside or at_free_end:
                pseudo.points.append((min(max(gx - olo, 0.0), ohi - olo), p))
    pseudo.segs.sort()
    pseudo.points.sort()
    return pseudo


class _RunSolution:
    """Solved state of one run for one case pattern set."""

    def __init__(self, run: "_Run", case: str):
        self.run = run
        self.case = case
        spans, m_l, m_r, extra = _case_loading(run, case)
        self.extra = extra
        self.m_left = m_l
        self.m_right = m_r
        self.results = solve_run_exact(spans, m_l, m_r) if run.spans else []
        self.left_pseudo = _overhang_pseudo(run, case, "L")
        self.right_pseudo = _overhang_pseudo(run, case, "R")

    def reactions(self) -> List[float]:
        base = run_reactions(self.results) if self.results else [0.0] * len(self.run.supports)
        if len(base) != len(self.run.supports):
            base = base + [0.0] * (len(self.run.supports) - len(base))
        return [base[i] + self.extra[i] for i in range(len(self.run.supports))]

    def support_moments(self) -> List[float]:
        if not self.results:
            return [self.m_left] if self.run.supports else []
        return [self.results[0].m_left] + [r.m_right for r in self.results]

    def m_at(self, x: float) -> float:
        run = self.run
        if run.overhang_left and x < run.overhang_left[1] - _EPS:
            pseudo = self.left_pseudo
            if pseudo is None:
                return 0.0
            return -pseudo.moment_of_loads_about(x - run.overhang_left[0])
        if run.overhang_right and x > run.overhang_right[0] + _EPS:
            pseudo = self.right_pseudo
            if pseudo is None:
                return 0.0
            rev = _reversed_loading(pseudo)
            return -rev.moment_of_loads_about(pseudo.length_m - (x - run.overhang_right[0]))
        for idx, (lo, hi) in enumerate(run.spans):
            if lo - _EPS <= x <= hi + _EPS:
                return self.results[idx].m_at(min(max(x - lo, 0.0), hi - lo))
        if run.supports:
            return self.m_left if abs(x - run.supports[0].x_m) < abs(x - run.supports[-1].x_m) else self.m_right
        return 0.0

    def v_abs_at(self, x: float) -> float:
        run = self.run
        values = []  # type: List[float]
        if run.overhang_left and x <= run.overhang_left[1] + _EPS:
            pseudo = self.left_pseudo
            if pseudo is not None:
                values.append(abs(pseudo.load_upto(x - run.overhang_left[0])))
        if run.overhang_right and x >= run.overhang_right[0] - _EPS:
            pseudo = self.right_pseudo
            if pseudo is not None:
                rev = _reversed_loading(pseudo)
                values.append(abs(rev.load_upto(pseudo.length_m - (x - run.overhang_right[0]))))
        for idx, (lo, hi) in enumerate(run.spans):
            if lo - _EPS <= x <= hi + _EPS:
                local = min(max(x - lo, 0.0), hi - lo)
                values.append(abs(self.results[idx].v_at(local, "+")))
                values.append(abs(self.results[idx].v_at(local, "-")))
        return max(values) if values else 0.0

    def sag_extremes_between(self, xa: float, xb: float) -> Tuple[float, float]:
        run = self.run
        m_max = None  # type: Optional[float]
        m_min = None  # type: Optional[float]
        for idx, (lo, hi) in enumerate(run.spans):
            a = max(xa, lo)
            b = min(xb, hi)
            if b - a <= _EPS:
                continue
            hi_v, lo_v = _extremes_between(self.results[idx], a - lo, b - lo)
            m_max = hi_v if m_max is None else max(m_max, hi_v)
            m_min = lo_v if m_min is None else min(m_min, lo_v)
        for x in (xa, xb):
            value = self.m_at(x)
            m_max = value if m_max is None else max(m_max, value)
            m_min = value if m_min is None else min(m_min, value)
        return (m_max or 0.0, m_min or 0.0)


def _pattern_solutions(run: "_Run", case: str) -> List["_RunSolution"]:
    """Solutions for the live-pattern roster (spec: all / alternate / adjacent).

    Pattern filtering rebuilds the span loadings with only the pattern's spans
    loaded; overhang and support-point loads ride on every pattern.
    """
    solutions = []  # type: List[_RunSolution]
    base = _RunSolution(run, case)
    solutions.append(base)
    n = len(run.spans)
    if n >= 2:
        for name, included in _patterns(n)[1:]:
            sol = _RunSolution.__new__(_RunSolution)
            sol.run = run
            sol.case = case
            spans, m_l, m_r, extra = _case_loading(run, case, included_spans=included)
            sol.extra = extra
            sol.m_left = m_l
            sol.m_right = m_r
            sol.results = solve_run_exact(spans, m_l, m_r) if run.spans else []
            sol.left_pseudo = base.left_pseudo
            sol.right_pseudo = base.right_pseudo
            solutions.append(sol)
    return solutions


def _solve_run(run: "_Run", cases: Sequence[str], force_exact: bool, log: DisclosureLog) -> Dict[str, Any]:
    """Solve one run for every case; returns reactions, summaries, stations."""
    if not force_exact:
        applicable, reason = _coeff_applicable(run, cases)
    else:
        applicable, reason = (False, "exact method forced by options")
    run.method = "coeff" if applicable else "exact"
    run.method_reason = reason

    single_monolithic = (
        len(run.spans) == 1
        and run.supports[0].kind == "column"
        and run.supports[-1].kind == "column"
    )
    if not applicable and reason and not force_exact:
        message = "run %s: %s; exact three-moment analysis used" % (run.run_id, reason)
        if single_monolithic:
            message += "; monolithic end allowance w l^2/24 applied at the column supports"
        log.add("W_ANA_COEFF_INAPPLICABLE", message, [b.id for b in run.beams], clause="IS 456:2000 Cl 22.5.1", stage=_STAGE)

    n = len(run.spans)
    reactions = {}  # type: Dict[str, List[float]]
    summary = {}  # type: Dict[str, Dict[str, Any]]
    beam_stations = {}  # type: Dict[str, Dict[str, List[Dict[str, float]]]]

    all_solutions = {}  # type: Dict[str, List[_RunSolution]]
    for case in cases:
        if case in _IMPOSED_CASES and run.method == "exact":
            all_solutions[case] = _pattern_solutions(run, case)
        else:
            all_solutions[case] = [_RunSolution(run, case)]
        base = all_solutions[case][0]
        reactions[case] = base.reactions()
        summary[case] = {
            "support_moments": [_r(m) for m in base.support_moments()],
            "reactions": [_r(v) for v in reactions[case]],
        }

    # per-beam stations
    coeff_values = {}  # type: Dict[str, Dict[int, Dict[str, float]]]
    if run.method == "coeff":
        lengths = [hi - lo for lo, hi in run.spans]
        for case in cases:
            kindkey = "dead" if case == CASE_DL else "imposed"
            per_span = {}  # type: Dict[int, Dict[str, float]]
            eq = [_span_eq_udl(run, case, j) for j in range(n)]
            for j in range(n):
                l_j = lengths[j]
                span_pos = "span_end" if j in (0, n - 1) else "span_interior"
                m_span = table12_alpha(span_pos, kindkey) * eq[j][0] * l_j * l_j
                v_l = table13_alpha(_shear_position(j, "L", n), kindkey) * eq[j][1] * l_j
                v_r = table13_alpha(_shear_position(j, "R", n), kindkey) * eq[j][1] * l_j
                per_span[j] = {"m_span": m_span, "v_l": v_l, "v_r": v_r}
            for k in range(n + 1):
                pos = _moment_support_position(k, n)
                if pos is None:
                    per_span.setdefault(-1, {})["m_sup_%d" % k] = 0.0
                    continue
                adjacent = [j for j in (k - 1, k) if 0 <= j < n]
                wb = sum(eq[j][0] for j in adjacent) / len(adjacent)
                lbar = sum(lengths[j] for j in adjacent) / len(adjacent)
                per_span.setdefault(-1, {})["m_sup_%d" % k] = table12_alpha(pos, kindkey) * wb * lbar * lbar
            coeff_values[case] = per_span

    support_xs = [s.x_m for s in run.supports]
    for beam in sorted(run.beams, key=lambda b: b.id):
        axis = beam_axis(beam)
        if axis is None:
            continue
        b0 = max(axis[2], run.lo_m)
        b1 = min(axis[3], run.hi_m)
        mid = 0.5 * (b0 + b1)
        stations_x = (b0, mid, b1)
        beam_stations[beam.id] = {}
        for case in cases:
            solutions = all_solutions[case]
            rows = []  # type: List[Dict[str, float]]
            for si, x in enumerate(stations_x):
                m_vals = []  # type: List[float]
                m_min_vals = []  # type: List[float]
                v_vals = []  # type: List[float]
                for sol in solutions:
                    if si == 1:
                        hi_v, lo_v = sol.sag_extremes_between(b0, b1)
                        m_vals.append(hi_v)
                        m_min_vals.append(lo_v)
                    else:
                        value = sol.m_at(x)
                        m_vals.append(value)
                        m_min_vals.append(value)
                    v_vals.append(sol.v_abs_at(x))
                rows.append(
                    {
                        "m_max": max(m_vals),
                        "m_min": min(m_min_vals),
                        "v_abs": max(v_vals),
                    }
                )
            if run.method == "coeff":
                span_idx = None
                for j, (lo, hi) in enumerate(run.spans):
                    if lo - _SUPPORT_TOL_M <= mid <= hi + _SUPPORT_TOL_M:
                        span_idx = j
                        break
                if span_idx is not None:
                    per_span = coeff_values[case]
                    imposed = case != CASE_DL
                    m_span = per_span[span_idx]["m_span"]
                    rows[1]["m_max"] = m_span
                    rows[1]["m_min"] = 0.0 if imposed else m_span
                    for si, side in ((0, "L"), (2, "R")):
                        x = stations_x[si]
                        k = None
                        for kk, sx in enumerate(support_xs):
                            if abs(x - sx) <= _SUPPORT_TOL_M:
                                k = kk
                                break
                        if k is None:
                            continue
                        m_sup = per_span[-1]["m_sup_%d" % k]
                        rows[si]["m_min"] = m_sup
                        rows[si]["m_max"] = 0.0 if imposed else m_sup
                        rows[si]["v_abs"] = per_span[span_idx]["v_l" if side == "L" else "v_r"]
            if single_monolithic and run.method == "exact":
                total = sum(0.5 * (w1 + w2) * (gb - ga) for ga, gb, w1, w2 in _clip_segs(run.segs.get(case, []), run.spans[0][0], run.spans[0][1]))
                total += sum(p for gx, p in run.pts.get(case, []) if run.spans[0][0] < gx < run.spans[0][1])
                span_l = run.spans[0][1] - run.spans[0][0]
                allowance = -(total * span_l) / 24.0
                for si in (0, 2):
                    rows[si]["m_min"] = min(rows[si]["m_min"], allowance)
            beam_stations[beam.id][case] = rows
    return {"reactions": reactions, "summary": summary, "beam_stations": beam_stations, "method": run.method}


# ---------------------------------------------------------------------------
# combination assembly (combine())
# ---------------------------------------------------------------------------


def _factored_stations(
    case_rows: Dict[str, List[Dict[str, float]]],
    combos: Sequence[Any],
    stations_x: Sequence[float],
) -> Tuple[Tuple[StationForces, ...], Dict[str, str]]:
    """Envelope per-station values over the given combinations."""
    governing = {}  # type: Dict[str, str]
    best = {"m_pos": None, "m_neg": None, "v": None}  # type: Dict[str, Optional[float]]
    rows = []  # type: List[Dict[str, float]]
    for si in range(len(stations_x)):
        rows.append({"m_pos": 0.0, "m_neg": 0.0, "v": 0.0})
    for combo in combos:
        factors = combo.factor_map()
        for si in range(len(stations_x)):
            m_hi = 0.0
            m_lo = 0.0
            v = 0.0
            for case, case_stations in case_rows.items():
                factor = factors.get(case, 0.0)
                if factor == 0.0:
                    continue
                row = case_stations[si]
                m_hi += factor * row["m_max"]
                m_lo += factor * row["m_min"]
                v += factor * row["v_abs"]
            row_out = rows[si]
            if m_hi > row_out["m_pos"]:
                row_out["m_pos"] = m_hi
                if best["m_pos"] is None or m_hi > best["m_pos"]:
                    best["m_pos"] = m_hi
                    governing["m_pos"] = combo.id
            if m_lo < row_out["m_neg"]:
                row_out["m_neg"] = m_lo
                if best["m_neg"] is None or m_lo < best["m_neg"]:
                    best["m_neg"] = m_lo
                    governing["m_neg"] = combo.id
            if v > row_out["v"]:
                row_out["v"] = v
                if best["v"] is None or v > best["v"]:
                    best["v"] = v
                    governing["v"] = combo.id
    stations = tuple(
        StationForces(
            station=stations_x[si],
            m_pos_max_knm=rows[si]["m_pos"],
            m_neg_min_knm=rows[si]["m_neg"],
            v_max_kn=rows[si]["v"],
        )
        for si in range(len(stations_x))
    )
    return (stations, governing)


# ---------------------------------------------------------------------------
# the takedown itself
# ---------------------------------------------------------------------------


def _line_load_total(load: Any, element: Any) -> float:
    length = element.span_m() if isinstance(element, Beam) else element.length_m()
    return 0.5 * (load.w1_kn_m + load.w2_kn_m) * (load.b - load.a) * length


def run(model: StructuralModel, loadmodel: LoadModel, opts: Optional[Dict[str, Any]] = None) -> TakedownResult:
    """Gravity takedown of a placed model; see the module docstring.

    `opts` (all optional): "conservation_tol" (default 0.005), "method"
    ("auto" default, or "exact" to skip the coefficient method).  Lateral
    cases in the load model are ignored here (the diaphragm distributes them);
    clause calls made inside are collected into `TakedownResult.trace`.
    """
    options = dict(opts or {})
    tol = float(options.get("conservation_tol", 0.005))
    force_exact = str(options.get("method", "auto")) == "exact"

    entries = []  # type: List[TraceEntry]
    with trace_into(entries):
        result = _run_inner(model, loadmodel, tol, force_exact)
    result.trace = [entry.to_dict() for entry in entries]
    return result


def _run_inner(model: StructuralModel, loadmodel: LoadModel, tol: float, force_exact: bool) -> TakedownResult:
    log = DisclosureLog()
    cases = [c for c in _GRAVITY_CASES if c in loadmodel.cases]
    if not cases:
        raise AnalysisError("E_BAD_ENVELOPE", "load model carries no gravity case (DL / LL / LLR)")

    panels = {s.id: s for s in model.slabs}
    beams = {b.id: b for b in model.beams}
    walls = {w.id: w for w in model.walls}
    columns = {c.id: c for c in model.columns}
    panel_area = {}  # type: Dict[str, float]
    for slab in model.slabs:
        rect = polygon_rect(slab.polygon)
        panel_area[slab.id] = rect[2] * rect[3]

    levels = sorted(set(s.index for s in model.storeys) | set(s.storey for s in model.slabs) | set(b.storey for b in model.beams) | set(w.storey for w in model.walls) | set(c.storey for c in model.columns))
    if not levels:
        raise AnalysisError("E_EMPTY_PLAN", "model carries no storeys or elements to take down")
    storey_height = {}  # type: Dict[int, float]
    storey_z_top = {}  # type: Dict[int, float]
    for storey in model.storeys:
        storey_height[storey.index] = storey.height_m
        storey_z_top[storey.index] = storey.bottom_z_m + storey.height_m

    # ---- applied totals, per-panel pressures, ledger ---------------------
    applied = {case: 0.0 for case in cases}
    area_q = {case: {} for case in cases}  # type: Dict[str, Dict[str, float]]
    beam_line = {case: {} for case in cases}  # type: Dict[str, Dict[str, List[Any]]]
    wall_books = {wid: _WallBook() for wid in walls}
    col_extra = {case: {} for case in cases}  # type: Dict[str, Dict[str, float]]
    ledger = {}  # type: Dict[int, Dict[str, float]]

    def ledger_row(level: int) -> Dict[str, float]:
        if level not in ledger:
            ledger[level] = {
                "w_dl_kn": 0.0,
                "w_ll_kn": 0.0,
                "ll_fraction_basis_kpa": 0.0,
                "z_m": storey_z_top.get(level, 0.0),
            }
        return ledger[level]

    def ledger_add(level: int, case: str, kn: float) -> None:
        if level < 0:
            return
        row = ledger_row(level)
        if case == CASE_DL:
            row["w_dl_kn"] += kn
        elif case == CASE_LL:
            row["w_ll_kn"] += kn
        # LLR is excluded from the seismic weight (IS 1893 Cl 7.3.2)

    for level in levels:
        ledger_row(level)

    for case in cases:
        load_case = loadmodel.cases[case]
        for area in load_case.area:
            slab = panels.get(area.panel_id)
            if slab is None:
                raise AnalysisError("E_BAD_ENVELOPE", "area load on unknown panel " + area.panel_id, [area.panel_id])
            area_q[case][area.panel_id] = area_q[case].get(area.panel_id, 0.0) + area.q_kpa
            total = area.q_kpa * panel_area[area.panel_id]
            applied[case] += total
            ledger_add(slab.storey, case, total)
            if case == CASE_LL:
                row = ledger_row(slab.storey)
                q_now = area_q[case][area.panel_id]
                if q_now > row["ll_fraction_basis_kpa"]:
                    row["ll_fraction_basis_kpa"] = q_now
        for line in load_case.line:
            if line.element_id in beams:
                beam = beams[line.element_id]
                beam_line[case].setdefault(line.element_id, []).append(line)
                total = _line_load_total(line, beam)
                applied[case] += total
                ledger_add(beam.storey, case, total)
            elif line.element_id in walls:
                wall = walls[line.element_id]
                total = _line_load_total(line, wall)
                book = wall_books[wall.id]
                book.carried[case] = book.carried.get(case, 0.0) + total
                applied[case] += total
                ledger_add(wall.storey, case, 0.5 * total)
                ledger_add(wall.storey - 1, case, 0.5 * total)
            else:
                raise AnalysisError("E_BAD_ENVELOPE", "line load on unknown element " + line.element_id, [line.element_id])
        for point in load_case.point:
            col = columns.get(point.node_id)
            if col is None:
                raise AnalysisError("E_BAD_ENVELOPE", "point load on unknown node " + point.node_id, [point.node_id])
            col_extra[case][col.id] = col_extra[case].get(col.id, 0.0) + point.p_kn
            applied[case] += point.p_kn
            ledger_add(col.storey, case, point.p_kn)

    level_basis = {level: ledger[level]["ll_fraction_basis_kpa"] for level in ledger}

    # ---- geometry: runs per storey ---------------------------------------
    runs_by_storey = {}  # type: Dict[int, List[_Run]]
    beam_to_run = {}  # type: Dict[str, _Run]
    for level in levels:
        runs_by_storey[level] = _build_runs(model, level, log)
        for one in runs_by_storey[level]:
            for beam in one.beams:
                beam_to_run[beam.id] = one

    # element line loads onto their runs
    for case in cases:
        for beam_id in sorted(beam_line[case]):
            beam = beams[beam_id]
            one = beam_to_run[beam_id]
            c_a = _along(one.orient, beam.a[0], beam.a[1])
            c_b = _along(one.orient, beam.b[0], beam.b[1])
            for line in beam_line[case][beam_id]:
                ga = c_a + line.a * (c_b - c_a)
                gb = c_a + line.b * (c_b - c_a)
                w1, w2 = line.w1_kn_m, line.w2_kn_m
                if gb < ga:
                    ga, gb = gb, ga
                    w1, w2 = w2, w1
                tag = {"tag": "udl", "w": w1} if abs(w1 - w2) <= _EPS else {"tag": "gen"}
                one.add_seg(case, ga, gb, w1, w2, tag=tag)

    # ---- column stacks ----------------------------------------------------
    columns_by_stack = {}  # type: Dict[str, Dict[int, Column]]
    for col in sorted(model.columns, key=lambda c: c.id):
        columns_by_stack.setdefault(col.stack_id, {})[col.storey] = col
    stack_incoming = {}  # type: Dict[str, Dict[str, float]]
    stack_floors = {}  # type: Dict[str, int]
    stack_basis = {}  # type: Dict[str, float]

    gamma_rcc = is875.part1_unit_weight("rcc")
    if model.columns:
        log.add(
            "N_COLUMN_HEIGHT_CONVENTION",
            "column self weight uses the floor to floor height; the slab depth is not deducted",
            (),
            stage=_STAGE,
        )

    footing_columns = {}  # type: Dict[str, Dict[str, float]]
    footing_col_meta = {}  # type: Dict[str, Dict[str, float]]
    footing_walls = {}  # type: Dict[str, Dict[str, float]]
    footing_wall_meta = {}  # type: Dict[str, Dict[str, float]]
    column_loads = []  # type: List[Dict[str, Any]]
    wall_stresses = []  # type: List[WallStress]
    beam_station_data = {}  # type: Dict[str, Dict[str, List[Dict[str, float]]]]
    beam_method = {}  # type: Dict[str, str]
    run_records = []  # type: List[Dict[str, Any]]
    column_entry_by_id = {}  # type: Dict[str, Dict[str, Any]]

    def footing_col_add(stack_id: str, case: str, kn: float) -> None:
        footing_columns.setdefault(stack_id, {}).setdefault(case, 0.0)
        footing_columns[stack_id][case] += kn

    def footing_wall_add(wall_id: str, case: str, kn: float) -> None:
        footing_walls.setdefault(wall_id, {}).setdefault(case, 0.0)
        footing_walls[wall_id][case] += kn

    def solve_and_distribute(runs: Sequence["_Run"]) -> None:
        ordered = _topo_order(list(runs), beam_to_run)
        for one in ordered:
            solved = _solve_run(one, cases, force_exact, log)
            for beam in one.beams:
                beam_method[beam.id] = solved["method"]
            for beam_id, rows in solved["beam_stations"].items():
                beam_station_data[beam_id] = rows
            run_records.append(
                {
                    "run_id": one.run_id,
                    "storey": one.storey,
                    "orient": one.orient,
                    "pos_m": _r(one.pos_m),
                    "plinth": one.plinth,
                    "method": solved["method"],
                    "method_reason": one.method_reason,
                    "beam_ids": [b.id for b in one.beams],
                    "spans": [[_r(lo), _r(hi)] for lo, hi in one.spans],
                    "supports": [
                        {"x_m": _r(s.x_m), "kind": s.kind, "target_id": s.target_id} for s in one.supports
                    ],
                    "cases": solved["summary"],
                }
            )
            for case in cases:
                reactions = solved["reactions"][case]
                for idx, support in enumerate(one.supports):
                    reaction = reactions[idx]
                    if abs(reaction) <= _EPS:
                        continue
                    if support.kind == "column":
                        col = columns[support.target_id]
                        if one.plinth:
                            footing_col_add(col.stack_id, case, reaction)
                        else:
                            col_extra[case][col.id] = col_extra[case].get(col.id, 0.0) + reaction
                    elif support.kind == "wall":
                        book = wall_books[support.target_id]
                        book.top[case] = book.top.get(case, 0.0) + reaction
                        book.loaded_top = True
                    else:  # frame
                        target_run = beam_to_run[support.target_id]
                        x_m, y_m = _to_xy(one.orient, one.pos_m, support.x_m)
                        target_x = _along(target_run.orient, x_m, y_m)
                        target_run.add_pt(case, target_x, reaction)

    # ---- the top-down loop ------------------------------------------------
    plinth_runs = []  # type: List[_Run]
    for level in levels:
        plinth_runs.extend([one for one in runs_by_storey[level] if one.plinth])

    for level in sorted(levels, reverse=True):
        # slab panels at this floor level
        for slab in sorted(model.slabs_on(level), key=lambda s: s.id):
            qs = {case: area_q[case].get(slab.id, 0.0) for case in cases}
            if not any(abs(q) > _EPS for q in qs.values()):
                continue
            rect = polygon_rect(slab.polygon)
            w_m, h_m = rect[2], rect[3]
            if w_m <= _EPS or h_m <= _EPS:
                continue
            lx = min(w_m, h_m)
            ly = max(w_m, h_m)
            ratio = ly / lx if lx > 0.0 else 99.0
            two_way = slab.two_way if slab.two_way is not None else (ratio <= 2.0)
            edges = _panel_edges(model, slab)
            _assign_edge_profiles(edges, w_m, h_m, bool(two_way), log, slab.id)
            for edge in edges:
                centre_perp = rect[1] + 0.5 * h_m if edge.orient == "h" else rect[0] + 0.5 * w_m
                for case in cases:
                    if abs(qs[case]) > _EPS:
                        _emit_edge_case(edge, qs[case], case, beam_to_run, wall_books, lx, ratio, centre_perp)

        # beam runs at this level (plinth runs wait for the ground walls)
        solve_and_distribute([one for one in runs_by_storey[level] if not one.plinth])

        # columns of this storey: accumulate and push down
        for col in sorted(model.columns_on(level), key=lambda c: c.id):
            stack = columns_by_stack[col.stack_id]
            incoming = stack_incoming.pop(col.stack_id, {})
            height = storey_height.get(level, 3.0)
            self_kn = gamma_rcc * col.width_m * col.depth_m * height
            applied[CASE_DL] += self_kn
            ledger_add(level, CASE_DL, 0.5 * self_kn)
            ledger_add(level - 1, CASE_DL, 0.5 * self_kn)
            totals = {}  # type: Dict[str, float]
            for case in cases:
                totals[case] = incoming.get(case, 0.0) + col_extra[case].get(col.id, 0.0)
            totals[CASE_DL] = totals.get(CASE_DL, 0.0) + self_kn
            floors = stack_floors.get(col.stack_id, 0) + 1
            basis = max(stack_basis.get(col.stack_id, 0.0), level_basis.get(level, 0.0))
            reduction = is875.part2_reduction_factor(floors, basis if basis > 0.0 else None)
            imposed_raw = totals.get(CASE_LL, 0.0) + totals.get(CASE_LLR, 0.0)
            entry = {
                "column_id": col.id,
                "stack_id": col.stack_id,
                "storey": level,
                "p_dl_kn": _r(totals.get(CASE_DL, 0.0)),
                "p_ll_kn": _r(totals.get(CASE_LL, 0.0)),
                "p_llr_kn": _r(totals.get(CASE_LLR, 0.0)),
                "p_ll_reduced_kn": _r(imposed_raw * reduction.factor),
                "floors_carried": floors,
                "reduction": _r(reduction.reduction),
                "reduction_applied": reduction.applied,
            }
            column_loads.append(entry)
            column_entry_by_id[col.id] = {
                "entry": entry,
                "totals": dict(totals),
                "factor": reduction.factor,
                "height": height,
            }
            below = stack.get(level - 1)
            if below is not None:
                stack_incoming[col.stack_id] = dict(totals)
                stack_floors[col.stack_id] = floors
                stack_basis[col.stack_id] = basis
            elif level == min(levels):
                for case in cases:
                    footing_col_add(col.stack_id, case, totals.get(case, 0.0))
                footing_col_meta[col.stack_id] = {"floors": floors, "basis": basis, "factor": reduction.factor}
            else:
                raise AnalysisError(
                    "E_TRANSFER_REQUIRED",
                    "column %s of storey %d has no column below to carry it" % (col.id, level),
                    [col.id],
                )

        # walls of this storey: stress record, then route the base load
        for wall in sorted(model.walls_on(level), key=lambda w: w.id):
            book = wall_books[wall.id]
            total_service = sum(book.total(case) for case in cases)
            if total_service <= _EPS:
                continue
            length = wall.length_m()
            top_service = sum(book.top.get(case, 0.0) for case in cases)
            moment_service = sum(book.moment.get(case, 0.0) for case in cases)
            ecc = abs(moment_service) / top_service if top_service > _EPS else 0.0
            if length > _EPS and wall.thickness_m > _EPS:
                wall_stresses.append(
                    WallStress(
                        wall_id=wall.id,
                        storey=level,
                        n_kn_m=total_service / length,
                        e_m=ecc,
                        e_over_t=ecc / wall.thickness_m,
                    )
                )
            floors = book.floors_in + (1 if book.loaded_top else 0)
            basis = max(book.basis_in, level_basis.get(level, 0.0) if book.loaded_top else 0.0)
            support = find_wall_support(model, wall)
            if support["kind"] == "beams":
                cover = sum(hi - lo for _, lo, hi in support["beams"])
                if cover <= _EPS:
                    raise AnalysisError("E_TRANSFER_REQUIRED", "wall %s bearing length is zero" % wall.id, [wall.id])
                for case in cases:
                    total = book.total(case)
                    if abs(total) <= _EPS:
                        continue
                    w_uni = total / cover
                    for beam_id, lo, hi in support["beams"]:
                        target = beam_to_run[beam_id]
                        target.add_seg(case, lo, hi, w_uni, w_uni, tag={"tag": "udl", "w": w_uni})
            elif support["kind"] == "wall":
                below = walls[support["wall_id"]]
                below_book = wall_books[below.id]
                axis_above = wall_axis(wall)
                axis_below = wall_axis(below)
                offset = 0.0
                if axis_above is not None and axis_below is not None:
                    offset = axis_above[1] - axis_below[1]
                for case in cases:
                    total = book.total(case)
                    if abs(total) <= _EPS:
                        continue
                    below_book.top[case] = below_book.top.get(case, 0.0) + total
                    below_book.moment[case] = below_book.moment.get(case, 0.0) + total * offset
                below_book.floors_in = max(below_book.floors_in, floors)
                below_book.basis_in = max(below_book.basis_in, basis)
            elif support["kind"] == "ground":
                for case in cases:
                    total = book.total(case)
                    if abs(total) > _EPS:
                        footing_wall_add(wall.id, case, total)
                footing_wall_meta[wall.id] = {"floors": float(max(floors, 1)), "basis": basis, "length": length}
            else:
                raise AnalysisError(
                    "E_TRANSFER_REQUIRED",
                    "wall %s of storey %d has no support below for its accumulated load" % (wall.id, level),
                    [wall.id],
                )

    # plinth runs last: ground walls have routed onto them by now
    solve_and_distribute(plinth_runs)

    # ---- conservation -----------------------------------------------------
    conservation = {}  # type: Dict[str, Dict[str, float]]
    for case in cases:
        base = sum(footing_columns.get(stack, {}).get(case, 0.0) for stack in footing_columns)
        base += sum(footing_walls.get(wid, {}).get(case, 0.0) for wid in footing_walls)
        try:
            conservation[case] = check_conservation(case, applied[case], base, tol)
        except AnalysisError as error:
            model.add_warning(error.code, error.message, error.element_ids, stage=_STAGE)
            raise

    # ---- footing loads with the member-wise live reduction ----------------
    footing_out_cols = {}  # type: Dict[str, Dict[str, float]]
    for stack in sorted(footing_columns):
        totals = footing_columns[stack]
        meta = footing_col_meta.get(stack, {"floors": 1, "basis": 0.0})
        reduction = is875.part2_reduction_factor(int(meta["floors"]), meta["basis"] if meta["basis"] > 0.0 else None)
        imposed_raw = totals.get(CASE_LL, 0.0) + totals.get(CASE_LLR, 0.0)
        footing_out_cols[stack] = {
            "p_dl_kn": totals.get(CASE_DL, 0.0),
            "p_ll_raw_kn": imposed_raw,
            "p_ll_reduced_kn": imposed_raw * reduction.factor,
            "floors_carried": float(int(meta["floors"])),
            "reduction": reduction.reduction,
        }
    footing_out_walls = {}  # type: Dict[str, Dict[str, float]]
    for wid in sorted(footing_walls):
        totals = footing_walls[wid]
        meta = footing_wall_meta.get(wid, {"floors": 1.0, "basis": 0.0, "length": walls[wid].length_m()})
        length = meta["length"] if meta["length"] > _EPS else 1.0
        reduction = is875.part2_reduction_factor(int(meta["floors"]), meta["basis"] if meta["basis"] > 0.0 else None)
        imposed_raw = totals.get(CASE_LL, 0.0) + totals.get(CASE_LLR, 0.0)
        footing_out_walls[wid] = {
            "n_dl_kn_m": totals.get(CASE_DL, 0.0) / length,
            "n_ll_raw_kn_m": imposed_raw / length,
            "n_ll_kn_m": imposed_raw * reduction.factor / length,
            "floors_carried": float(int(meta["floors"])),
            "reduction": reduction.reduction,
        }

    # ---- envelopes (combine) ---------------------------------------------
    envelopes = _combine_envelopes(
        model,
        loadmodel,
        cases,
        beam_station_data,
        beam_method,
        column_entry_by_id,
        wall_stresses,
        area_q,
        footing_out_cols,
    )

    result = TakedownResult(
        storey_ledger={level: dict(row) for level, row in sorted(ledger.items())},
        beam_runs=sorted(run_records, key=lambda r: r["run_id"]),
        column_loads=sorted(column_loads, key=lambda e: (e["storey"], e["column_id"])),
        wall_stresses=sorted(wall_stresses, key=lambda w: (w.storey, w.wall_id)),
        footing_loads={"columns": footing_out_cols, "walls": footing_out_walls},
        conservation=conservation,
        envelopes=envelopes,
        log=log,
    )
    return result


def _combine_envelopes(
    model: StructuralModel,
    loadmodel: LoadModel,
    cases: Sequence[str],
    beam_station_data: Dict[str, Dict[str, List[Dict[str, float]]]],
    beam_method: Dict[str, str],
    column_entry_by_id: Dict[str, Dict[str, Any]],
    wall_stresses: Sequence[WallStress],
    area_q: Dict[str, Dict[str, float]],
    footing_out_cols: Dict[str, Dict[str, float]],
) -> Dict[str, ForceEnvelope]:
    """Factored envelopes per element: THE contract design/ consumes."""
    combos = list(loadmodel.combos)
    uls = [c for c in combos if c.kind == "ULS"]
    sls = [c for c in combos if c.kind == "SLS"]
    fallback = None
    if not uls or not sls:
        from ..loads import Combo

        fallback = Combo(
            id="RAW",
            name="+".join(cases),
            kind="SLS",
            factors=tuple((case, 1.0) for case in cases),
            source="unit factors; no combinations were supplied",
        )
    uls_set = uls or [fallback]
    sls_set = sls or [fallback]
    envelopes = {}  # type: Dict[str, ForceEnvelope]

    stations_x = (0.0, 0.5, 1.0)
    for beam_id in sorted(beam_station_data):
        case_rows = beam_station_data[beam_id]
        stations, governing = _factored_stations(case_rows, uls_set, stations_x)
        envelopes[beam_id] = ForceEnvelope(
            element_id=beam_id,
            element_type="beam",
            stations=stations,
            method=beam_method.get(beam_id, "exact"),
            governing=governing,
        )

    for col_id in sorted(column_entry_by_id):
        data = column_entry_by_id[col_id]
        totals = data["totals"]
        factor = data["factor"]
        per_case = {
            CASE_DL: totals.get(CASE_DL, 0.0),
            CASE_LL: totals.get(CASE_LL, 0.0) * factor,
            CASE_LLR: totals.get(CASE_LLR, 0.0) * factor,
        }
        best = None
        best_combo = ""
        low = None
        for combo in uls_set:
            factors = combo.factor_map()
            value = sum(factors.get(case, 0.0) * per_case.get(case, 0.0) for case in cases)
            if best is None or value > best:
                best = value
                best_combo = combo.id
            if low is None or value < low:
                low = value
        stations = tuple(
            StationForces(station=x, n_max_kn=best or 0.0, n_min_kn=low or 0.0) for x in stations_x
        )
        entry = data["entry"]
        envelopes[col_id] = ForceEnvelope(
            element_id=col_id,
            element_type="column",
            stations=stations,
            method="takedown",
            governing={"n": best_combo},
            storey=int(entry["storey"]),
            length_m=data["height"],
        )

    for stress in wall_stresses:
        eid = stress.wall_id + "@s%d" % stress.storey
        envelopes[eid] = ForceEnvelope(
            element_id=eid,
            element_type="wall",
            stations=(StationForces(station=0.0, n_max_kn=stress.n_kn_m, n_min_kn=stress.n_kn_m),),
            method="takedown",
            governing={"n": sls_set[0].id},
            storey=stress.storey,
            units_note="axial per metre of wall, service (DL+LL+LLR unfactored)",
        )

    panel_ids = sorted(set().union(*[set(area_q[case]) for case in cases]) if cases else set())
    for panel_id in panel_ids:
        per_case = {case: area_q[case].get(panel_id, 0.0) for case in cases}
        w_u = None
        w_service = None
        gov_u = ""
        gov_s = ""
        for combo in uls_set:
            factors = combo.factor_map()
            value = sum(factors.get(case, 0.0) * per_case[case] for case in cases)
            if w_u is None or value > w_u:
                w_u = value
                gov_u = combo.id
        for combo in sls_set:
            factors = combo.factor_map()
            value = sum(factors.get(case, 0.0) * per_case[case] for case in cases)
            if w_service is None or value > w_service:
                w_service = value
                gov_s = combo.id
        slab = next(s for s in model.slabs if s.id == panel_id)
        envelopes[panel_id] = ForceEnvelope(
            element_id=panel_id,
            element_type="slab",
            stations=(),
            method="takedown",
            governing={"w_u": gov_u, "w_service": gov_s},
            w_u_kpa=w_u or 0.0,
            w_service_kpa=w_service or 0.0,
            storey=slab.storey,
        )

    for stack in sorted(footing_out_cols):
        record = footing_out_cols[stack]
        n_service = record["p_dl_kn"] + record["p_ll_reduced_kn"]
        eid = footing_id(stack)
        envelopes[eid] = ForceEnvelope(
            element_id=eid,
            element_type="footing",
            stations=(StationForces(station=0.0, n_max_kn=n_service, n_min_kn=record["p_dl_kn"]),),
            method="takedown",
            governing={"n": sls_set[0].id},
            units_note="service axial at the footing (dead + reduced imposed)",
        )
    return envelopes
