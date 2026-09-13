"""The v1 column interaction engine: a strain-plane fiber sweep.

Critic finding 31 is normative: v1 ships NO `structuralcodes` dependency, so the
spec's "fallback" sweep is the primary and only interaction engine. Everything
here is stdlib plus numpy, and the constitutive laws are the IS 456 Cl 38.1
DESIGN curves, so a point on the domain is a design capacity, not a mean one:

  concrete  parabola-rectangle, plateau 0.446 fck (= 0.67/1.5), eps_c2 0.002,
            eps_cu 0.0035, zero in tension
  steel     bilinear elastic-plastic, Es 200000, yield at 0.87 fy both ways

The section is a rectangle of `CONCRETE_STRIPS` strips perpendicular to the
bending plane plus point rebars, and the concrete a compressed bar displaces is
netted out of the bar force, so the squash end of the sweep reproduces the IS
net-area formulas (Cl 39.3, Cl 39.6) instead of double counting the steel holes.

Strain plane. One parameter, the neutral axis depth `xu_mm` measured from the
extreme compression fibre, drives both IS pivots:

  xu <= h   curvature 0.0035 / xu          (eps_cu at the compressed face)
  xu >  h   curvature 0.002 / (xu - 3h/7)  (eps_c2 at the 3h/7 pivot)

The two agree at xu = h, so P(xu) is continuous and non-decreasing over the
whole range, from pure tension (xu -> 0, every bar yielded in tension) to the
squash load (xu -> infinity, uniform 0.002). That monotonicity is what lets the
sweep place its points by bisection on the axial load rather than on an
arbitrary xu ladder, which is why the returned domain is evenly covered in Pu.

Bilinear steel, disclosed. The IS design stress-strain curve for cold worked
bars is not bilinear: above 0.8 fyd it curves, so at the squash strain of 0.002
it reads about 0.91 fyd for Fe 415 where this bilinear law reads 1.00 fyd. The
sweep therefore sits ABOVE the code closed forms at the squash end, by about 2
percent at the 0.8 percent minimum steel and growing with the steel ratio
(roughly 5 percent at 2 percent steel, Fe 415; less for Fe 500, whose bilinear
law is still elastic at 0.002). Flexure-governed points, where the compression
steel strain is far from 0.002, agree closely. `tests/test_design_columns.py`
pins the anchors; the piecewise HYSD curve is the documented later refinement.

Determinism and cost. Sorted bar tuples, fixed strip and bisection counts, no
randomness: the same `RectSection` returns an identical domain every time. One
21 point domain measures about 4 ms on the development machine and is cached
per (b, D, layout, fck, fy, theta) by `functools.lru_cache`, so a hundred
identical columns pay for one sweep. The bisection is vectorized across the
domain's points, which is what keeps a sweep in milliseconds rather than
tens of them.

Angle convention. `theta` is the direction in which the strain varies, measured
from +y towards +x, so:

  theta = 0     (THETA_X) strain varies with y, the section depth D lies in the
                plane of bending, and the moment returned is Mux
  theta = pi/2  (THETA_Y) strain varies with x, the width b lies in the plane of
                bending, and the moment returned is Muy

Compression is positive for both Pu and the moment sense (the compressed face is
the +p face). A layout symmetric about both axes, which is all `columns.py`
builds, has an identical domain for theta and theta + pi.

The adapter seam. `columns.py` reaches the domain through exactly three calls,
`interaction_points`, `mu_capacity` and `balanced_point`, plus the descriptive
`engine_note`. A later `_sc_adapter.py` wrapping structuralcodes has only to
export those four names with these signatures and units (N, mm, MPa) and the
designer needs no edit beyond choosing the module.
"""

from __future__ import annotations

import bisect
import functools
import math
from typing import Any, List, NamedTuple, Sequence, Tuple

import numpy as np

from ...codes import is456

__all__ = [
    "ENGINE_NAME",
    "EPS_CU",
    "EPS_C2",
    "CONCRETE_STRIPS",
    "DEFAULT_POINTS",
    "THETA_X",
    "THETA_Y",
    "Bar",
    "RectSection",
    "InteractionPoint",
    "rect_section",
    "interaction_points",
    "mu_capacity",
    "balanced_point",
    "balanced_xu_mm",
    "section_forces",
    "bar_strains",
    "squash_load_n",
    "pure_tension_n",
    "engine_note",
    "cache_info",
    "clear_caches",
]

#: What the DesignResult note calls this engine.
ENGINE_NAME = "fallback-sweep"

#: Ultimate concrete strain at the extreme compression fibre, IS 456 Cl 38.1.
EPS_CU = 0.0035
#: Strain at which the design parabola meets its plateau, IS 456 Cl 38.1.
EPS_C2 = 0.002
#: Depth of the IS 456 Cl 39.1(b) pivot below the highly compressed face, as a
#: fraction of the section depth, used when the neutral axis leaves the section.
PIVOT_FRACTION = 3.0 / 7.0

#: Concrete strips across the bending plane. 200 is the spec's number; the
#: parabolic block is integrated by the midpoint rule, exact to about 1e-6.
CONCRETE_STRIPS = 200
#: Points on one domain, from pure tension to the squash load (spec section 4).
DEFAULT_POINTS = 21

THETA_X = 0.0
THETA_Y = math.pi / 2.0

#: Bisection steps per domain point. 64 halvings take the bracket below float
#: resolution, so the point is exact rather than tolerance dependent.
_BISECT_ITERS = 64
#: Bisection runs on t in (0, 1) with xu = h t / (1 - t), which reaches both
#: limits without an unbounded search.
_T_MIN = 1e-12
_T_MAX = 1.0 - 1e-12

_CACHE_SIZE = 256
_TINY = 1e-12
_TINY_MM = 1e-9
#: Decimals kept when a section is normalized, so two callers that computed the
#: same geometry by different arithmetic land on one cache entry.
_DP = 6


def engine_note() -> str:
    """The sentence a DesignResult carries about where its domain came from."""
    return (
        "column interaction domain from the in-house strain-plane fiber sweep ("
        + ENGINE_NAME
        + ", IS 456 Cl 38.1 design constitutive laws, "
        + str(CONCRETE_STRIPS)
        + " concrete strips, displaced concrete netted); structuralcodes is not a v1 dependency"
    )


# ---------------------------------------------------------------------------
# the section
# ---------------------------------------------------------------------------


class Bar(NamedTuple):
    """One point rebar at (x, y) from the section centroid, mm and mm2."""

    x_mm: float
    y_mm: float
    area_mm2: float


class RectSection(NamedTuple):
    """A rectangular RC section: the cache key AND the model, in one value.

    `bars` is sorted, and every float is rounded by `rect_section`, so the
    tuple hashes identically for two callers that built the same column. x runs
    along `b_mm`, y along `depth_mm`, both measured from the centroid.
    """

    b_mm: float
    depth_mm: float
    fck_mpa: float
    fy_mpa: float
    bars: Tuple[Bar, ...]
    net_displaced_concrete: bool = True

    @property
    def ag_mm2(self) -> float:
        """Gross concrete area."""
        return float(self.b_mm) * float(self.depth_mm)

    @property
    def asc_mm2(self) -> float:
        """Total longitudinal steel area."""
        return float(sum(bar.area_mm2 for bar in self.bars))

    @property
    def ac_mm2(self) -> float:
        """Net concrete area, gross less the steel."""
        return self.ag_mm2 - self.asc_mm2

    @property
    def fcd_mpa(self) -> float:
        """Design concrete stress at the plateau, 0.446 fck."""
        return is456.CONCRETE_DESIGN_FACTOR * float(self.fck_mpa)

    @property
    def fyd_mpa(self) -> float:
        """Design steel stress, 0.87 fy."""
        return is456.GAMMA_S_FACTOR * float(self.fy_mpa)


class InteractionPoint(NamedTuple):
    """One point on the domain; unpacks as the (Pu, Mu) pair the spec asks for."""

    pu_n: float
    mu_nmm: float


def rect_section(
    b_mm: float,
    depth_mm: float,
    fck_mpa: float,
    fy_mpa: float,
    bars: Sequence[Any],
    net_displaced_concrete: bool = True,
) -> RectSection:
    """A normalized, hashable RectSection: rounded floats, sorted bars.

    `bars` items are Bar values or any (x_mm, y_mm, area_mm2) triple. Rounding
    and sorting are what make the lru_cache hit for two columns that are the
    same section reached by different arithmetic.
    """
    if b_mm <= 0.0 or depth_mm <= 0.0:
        raise ValueError("b_mm and depth_mm must be positive")
    if fck_mpa <= 0.0 or fy_mpa <= 0.0:
        raise ValueError("fck_mpa and fy_mpa must be positive")
    rows = []  # type: List[Bar]
    for bar in bars:
        x_mm, y_mm, area_mm2 = float(bar[0]), float(bar[1]), float(bar[2])
        if area_mm2 <= 0.0:
            raise ValueError("bar area_mm2 must be positive")
        rows.append(Bar(round(x_mm, _DP) + 0.0, round(y_mm, _DP) + 0.0, round(area_mm2, _DP) + 0.0))
    return RectSection(
        b_mm=round(float(b_mm), _DP) + 0.0,
        depth_mm=round(float(depth_mm), _DP) + 0.0,
        fck_mpa=round(float(fck_mpa), _DP) + 0.0,
        fy_mpa=round(float(fy_mpa), _DP) + 0.0,
        bars=tuple(sorted(rows)),
        net_displaced_concrete=bool(net_displaced_concrete),
    )


# ---------------------------------------------------------------------------
# geometry: strips across the bending plane, bar ordinates in it
# ---------------------------------------------------------------------------


def _sin_cos(theta: float) -> Tuple[float, float]:
    """(sin, cos) with anything under the tolerance snapped to a clean zero."""
    s = math.sin(float(theta))
    c = math.cos(float(theta))
    return (0.0 if abs(s) < _TINY else s), (0.0 if abs(c) < _TINY else c)


def _extent_mm(b_mm: float, depth_mm: float, s: float, c: float) -> float:
    """Depth of the section in the bending plane, mm: |b sin| + |D cos|."""
    return abs(float(b_mm) * s) + abs(float(depth_mm) * c)


def _chord_mm(b_mm: float, depth_mm: float, s: float, c: float, p: np.ndarray) -> np.ndarray:
    """Width of the rectangle on the line (x, y) . u = p, mm, vectorized over p.

    The chord runs along v = (cos, -sin); a point on it is p u + t v, so each
    face of the rectangle becomes one interval on t and the chord is the length
    of their intersection. A face perpendicular to the chord bounds nothing and
    instead switches the chord on or off, which is the mask branch.
    """
    half_b = 0.5 * float(b_mm)
    half_d = 0.5 * float(depth_mm)
    lo = np.full(p.shape, -np.inf)
    hi = np.full(p.shape, np.inf)
    live = np.ones(p.shape, dtype=bool)

    if abs(c) > _TINY:
        t1 = (-half_b - p * s) / c
        t2 = (half_b - p * s) / c
        lo = np.maximum(lo, np.minimum(t1, t2))
        hi = np.minimum(hi, np.maximum(t1, t2))
    else:
        live &= np.abs(p * s) <= half_b + _TINY

    if abs(s) > _TINY:
        t1 = (p * c - half_d) / s
        t2 = (p * c + half_d) / s
        lo = np.maximum(lo, np.minimum(t1, t2))
        hi = np.minimum(hi, np.maximum(t1, t2))
    else:
        live &= np.abs(p * c) <= half_d + _TINY

    length = np.maximum(hi - lo, 0.0)
    return np.where(live, length, 0.0)


class _Fibers(NamedTuple):
    """Frozen strip and bar arrays for one (section, theta)."""

    p_strip_mm: np.ndarray
    area_strip_mm2: np.ndarray
    p_bar_mm: np.ndarray
    area_bar_mm2: np.ndarray
    extent_mm: float


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _fibers(section: RectSection, theta: float, strips: int) -> _Fibers:
    """The discretization of one section in one bending plane, cached."""
    s, c = _sin_cos(theta)
    h = _extent_mm(section.b_mm, section.depth_mm, s, c)
    step = h / float(strips)
    p = (np.arange(strips, dtype=float) + 0.5) * step - 0.5 * h
    area = _chord_mm(section.b_mm, section.depth_mm, s, c, p) * step
    if section.bars:
        p_bar = np.array([bar.x_mm * s + bar.y_mm * c for bar in section.bars], dtype=float)
        area_bar = np.array([bar.area_mm2 for bar in section.bars], dtype=float)
    else:
        p_bar = np.zeros(0, dtype=float)
        area_bar = np.zeros(0, dtype=float)
    for array in (p, area, p_bar, area_bar):
        array.flags.writeable = False
    return _Fibers(p_strip_mm=p, area_strip_mm2=area, p_bar_mm=p_bar, area_bar_mm2=area_bar, extent_mm=h)


# ---------------------------------------------------------------------------
# constitutive laws (IS 456 Cl 38.1 design curves, plain numpy: the fiber loop
# is the hot path and must never emit trace entries, finding 7)
# ---------------------------------------------------------------------------


def _curvature(xu_mm: np.ndarray, h_mm: float) -> np.ndarray:
    """Strain gradient per mm for a neutral axis at `xu_mm`, both IS pivots."""
    inside = EPS_CU / np.maximum(xu_mm, _TINY_MM)
    outside = EPS_C2 / np.maximum(xu_mm - PIVOT_FRACTION * h_mm, _TINY_MM)
    return np.where(xu_mm <= h_mm, inside, outside)


def _strain(xu_mm: np.ndarray, h_mm: float, depth_mm: np.ndarray) -> np.ndarray:
    """Strain at fibres `depth_mm` below the extreme compression fibre."""
    return _curvature(xu_mm, h_mm) * (xu_mm - depth_mm)


def _concrete_stress(eps: np.ndarray, fcd_mpa: float) -> np.ndarray:
    """Parabola-rectangle design stress, MPa; zero in tension, flat past eps_c2."""
    r = np.clip(eps / EPS_C2, 0.0, 1.0)
    return fcd_mpa * (2.0 * r - r * r)


def _steel_stress(eps: np.ndarray, fyd_mpa: float) -> np.ndarray:
    """Bilinear elastic-plastic design stress, MPa, yielding at +-0.87 fy."""
    return np.clip(is456.ES_MPA * eps, -fyd_mpa, fyd_mpa)


def _resultants(
    section: RectSection,
    fibers: _Fibers,
    xu_mm: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """(Pu, Mu) for one or many neutral axis depths; N and N.mm.

    `xu_mm` broadcasts against the fibre axis: a scalar returns scalars, a
    column vector of shape (m, 1) returns two vectors of shape (m,).
    """
    h = fibers.extent_mm
    fcd = section.fcd_mpa
    depth_strip = 0.5 * h - fibers.p_strip_mm
    stress = _concrete_stress(_strain(xu_mm, h, depth_strip), fcd)
    force = stress * fibers.area_strip_mm2
    n = force.sum(axis=-1)
    m = (force * fibers.p_strip_mm).sum(axis=-1)

    if fibers.p_bar_mm.size:
        depth_bar = 0.5 * h - fibers.p_bar_mm
        eps_bar = _strain(xu_mm, h, depth_bar)
        stress_bar = _steel_stress(eps_bar, section.fyd_mpa)
        if section.net_displaced_concrete:
            stress_bar = stress_bar - _concrete_stress(eps_bar, fcd)
        force_bar = stress_bar * fibers.area_bar_mm2
        n = n + force_bar.sum(axis=-1)
        m = m + (force_bar * fibers.p_bar_mm).sum(axis=-1)
    return n, m


# ---------------------------------------------------------------------------
# the two closed anchors of every domain
# ---------------------------------------------------------------------------


def pure_tension_n(section: RectSection) -> float:
    """Pure axial tension capacity, N, negative: every bar yielded, no concrete."""
    return -section.fyd_mpa * section.asc_mm2


def squash_load_n(section: RectSection) -> float:
    """Squash load of the sweep, N: uniform eps_c2, displaced concrete netted.

    This is the engine's own Puz. It is the number IS 456 Cl 39.6 approximates
    as 0.45 fck Ac + 0.75 fy Asc; the two agree to a few percent and the test
    module pins the band.
    """
    fcd = section.fcd_mpa
    fs = float(_steel_stress(np.array(EPS_C2), section.fyd_mpa))
    net = fs - fcd if section.net_displaced_concrete else fs
    return fcd * section.ag_mm2 + net * section.asc_mm2


def _tension_point(section: RectSection, fibers: _Fibers) -> InteractionPoint:
    """The pure tension end of the domain, moment included for asymmetric steel."""
    if not fibers.p_bar_mm.size:
        return InteractionPoint(0.0, 0.0)
    force = -section.fyd_mpa * fibers.area_bar_mm2
    return InteractionPoint(float(force.sum()), float((force * fibers.p_bar_mm).sum()))


def _squash_point(section: RectSection, fibers: _Fibers) -> InteractionPoint:
    """The squash end of the domain, moment included for asymmetric steel."""
    n = squash_load_n(section)
    if not fibers.p_bar_mm.size:
        return InteractionPoint(n, 0.0)
    fcd = section.fcd_mpa
    fs = float(_steel_stress(np.array(EPS_C2), section.fyd_mpa))
    net = fs - fcd if section.net_displaced_concrete else fs
    force = net * fibers.area_bar_mm2
    return InteractionPoint(n, float((force * fibers.p_bar_mm).sum()))


# ---------------------------------------------------------------------------
# the sweep
# ---------------------------------------------------------------------------


def _xu_from_t(t: np.ndarray, h_mm: float) -> np.ndarray:
    """xu = h t / (1 - t): t in (0, 1) covers pure tension to uniform compression."""
    return h_mm * t / (1.0 - t)


def _solve_xu(section: RectSection, fibers: _Fibers, targets: np.ndarray) -> np.ndarray:
    """Neutral axis depths giving the target axial loads, by vectorized bisection.

    Pu is non-decreasing in xu because every fibre strain is, and both design
    stress laws are non-decreasing in strain, so one bracket serves every
    target and the halving needs no convergence test.
    """
    lo = np.full(targets.shape, _T_MIN)
    hi = np.full(targets.shape, _T_MAX)
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        n, _unused = _resultants(section, fibers, _xu_from_t(mid, fibers.extent_mm)[:, None])
        below = n < targets
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return _xu_from_t(0.5 * (lo + hi), fibers.extent_mm)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _domain(section: RectSection, n_points: int, theta: float, strips: int) -> Tuple[InteractionPoint, ...]:
    """The cached interaction domain, ascending in Pu."""
    fibers = _fibers(section, theta, strips)
    tension = _tension_point(section, fibers)
    squash = _squash_point(section, fibers)
    targets = np.linspace(tension.pu_n, squash.pu_n, n_points)
    interior = targets[1:-1]
    points = [tension]
    if interior.size:
        xu = _solve_xu(section, fibers, interior)
        n, m = _resultants(section, fibers, xu[:, None])
        for index in range(interior.size):
            points.append(InteractionPoint(float(n[index]), float(m[index])))
    points.append(squash)
    return tuple(points)


def interaction_points(
    section: RectSection,
    n_points: int = DEFAULT_POINTS,
    theta: float = THETA_X,
    strips: int = CONCRETE_STRIPS,
) -> Tuple[InteractionPoint, ...]:
    """The (Pu, Mu) domain of `section` in the plane `theta`, pure tension first.

    Points are evenly spaced in Pu between the two closed anchors, which are the
    first and last entries, so a caller may interpolate on the axial load
    without searching. Cached per (section, n_points, theta, strips).
    """
    count = int(n_points)
    if count < 3:
        raise ValueError("n_points must be at least 3 (both anchors and one interior point)")
    return _domain(section, count, _theta_key(theta), int(strips))


def _theta_key(theta: float) -> float:
    """Theta rounded to a stable cache key; 0 and pi/2 keep their exact values."""
    return round(float(theta), 12) + 0.0


def mu_capacity(
    section: RectSection,
    pu_n: float,
    theta: float = THETA_X,
    n_points: int = DEFAULT_POINTS,
) -> float:
    """Uniaxial moment capacity at the axial load `pu_n`, N.mm, never negative.

    Linear interpolation on the domain. The domain is concave over the working
    range, so interpolating between two points understates the capacity: the
    error is on the safe side, which is why 21 points is enough for design.
    Outside the domain (net tension beyond the steel, or above the squash load)
    the section has no moment capacity and the answer is zero.
    """
    points = interaction_points(section, n_points, theta)
    pu = float(pu_n)
    axis = [point.pu_n for point in points]
    if pu <= axis[0] or pu >= axis[-1]:
        return 0.0
    index = bisect.bisect_left(axis, pu)
    lower = points[index - 1]
    upper = points[index]
    span = upper.pu_n - lower.pu_n
    if span <= 0.0:
        return max(0.0, abs(upper.mu_nmm))
    fraction = (pu - lower.pu_n) / span
    return max(0.0, abs(lower.mu_nmm + fraction * (upper.mu_nmm - lower.mu_nmm)))


def balanced_xu_mm(section: RectSection, theta: float = THETA_X) -> float:
    """Neutral axis depth at the IS 456 Cl 39.7.1.1 balanced condition, mm.

    The clause defines Pb by 0.0035 at the extreme concrete fibre together with
    0.002 tension in the OUTERMOST layer of tension steel, which fixes
    xu / d = 0.0035 / 0.0055 with d measured to that layer. With no steel the
    section has no such layer and the whole depth is taken.
    """
    fibers = _fibers(section, _theta_key(theta), CONCRETE_STRIPS)
    h = fibers.extent_mm
    if not fibers.p_bar_mm.size:
        return h
    d_eff = 0.5 * h - float(fibers.p_bar_mm.min())
    return EPS_CU / (EPS_CU + EPS_C2) * d_eff


def balanced_point(section: RectSection, theta: float = THETA_X) -> InteractionPoint:
    """(Pb, Mb) at the balanced condition, the peak moment of the domain."""
    return section_forces(section, balanced_xu_mm(section, theta), theta)


def section_forces(section: RectSection, xu_mm: float, theta: float = THETA_X) -> InteractionPoint:
    """(Pu, Mu) for one explicit neutral axis depth, N and N.mm."""
    fibers = _fibers(section, _theta_key(theta), CONCRETE_STRIPS)
    n, m = _resultants(section, fibers, np.array(float(xu_mm)))
    return InteractionPoint(float(n), float(m))


def bar_strains(section: RectSection, xu_mm: float, theta: float = THETA_X) -> Tuple[float, ...]:
    """Strain at every bar for one neutral axis depth, in `section.bars` order.

    Compression positive, so a tension bar reads negative. Used by the tests to
    show WHERE the balanced point sits, and available to a caller that wants to
    report which bars have yielded.
    """
    fibers = _fibers(section, _theta_key(theta), CONCRETE_STRIPS)
    if not fibers.p_bar_mm.size:
        return ()
    depth = 0.5 * fibers.extent_mm - fibers.p_bar_mm
    return tuple(float(value) for value in _strain(np.array(float(xu_mm)), fibers.extent_mm, depth))


# ---------------------------------------------------------------------------
# cache control (the designer discloses hits, the tests pin them)
# ---------------------------------------------------------------------------


def cache_info() -> Any:
    """`functools.CacheInfo` for the domain cache."""
    return _domain.cache_info()


def clear_caches() -> None:
    """Drop both caches; only tests and a long lived worker need this."""
    _domain.cache_clear()
    _fibers.cache_clear()
