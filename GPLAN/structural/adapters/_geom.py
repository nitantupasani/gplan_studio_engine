"""Shared adapter primitives: the refusal type plus rectangle, polygon and
interval helpers.

Every adapter imports this module, so it stays small, stable and dependency
light: stdlib plus `model.py`, no shapely and no numpy. Lengths are metres
unless a name says otherwise, since adapters convert feet to metres once at
ingestion and never convert back.

The one tolerance that matters is `LINE_TOL_M`, 115 mm: the grid
regularization number (about 0.377 ft) that decides when two near parallel
edges are the same line. It is wide enough to absorb the known 0.25 ft column
overlaps and narrow enough to keep a 0.5 ft duct wall distinct.
"""

from __future__ import annotations

import hashlib
import json
from collections import namedtuple
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..model import FT, GEOM_TOL_M, REGISTRY, Disclosure, Severity, ft_to_m, make_disclosure, m_to_ft

XY = Tuple[float, float]

# Two coordinates closer than this are the same coordinate (1 mm, model.GEOM_TOL_M).
POINT_TOL_M = GEOM_TOL_M

# Centreline clustering tolerance (115 mm); see the module docstring.
LINE_TOL_M = 0.115

# Guard against dividing by a degenerate length.
EPS_M = 1e-9

__all__ = [
    "FT",
    "EPS_M",
    "LINE_TOL_M",
    "POINT_TOL_M",
    "XY",
    "AdapterError",
    "Rect",
    "almost_equal",
    "bbox_of_rects",
    "canonical_json",
    "cluster_index",
    "cluster_values",
    "fingerprint",
    "ft_to_m",
    "interval_breakpoints",
    "interval_overlap",
    "is_axis_aligned_rect",
    "is_rectilinear",
    "m_to_ft",
    "merge_intervals",
    "polygon_area",
    "polygon_bbox",
    "polygon_signed_area",
    "rect_area",
    "rect_bounds",
    "rect_from_polygon",
    "rect_polygon",
    "rects_overlap",
    "rects_overlap_area",
    "require_rectilinear",
]


# ---------------------------------------------------------------------------
# the refusal type
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """A refusal: the structure is underivable or the input geometry lies.

    `code` must be an ERROR code registered in `model.REGISTRY`; api.py maps the
    refusal to the engine error envelope with `message` verbatim. Anything that
    is merely an assumption belongs on the model's disclosure ladder instead:
    this exception is for inputs no honest model can be built from.
    """

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        if code not in REGISTRY:
            raise ValueError("unregistered disclosure code: " + str(code))
        registered = REGISTRY[code][0]
        if registered != Severity.ERROR:
            raise ValueError(
                "AdapterError needs an ERROR code; " + code + " is registered " + registered.value
            )
        super(AdapterError, self).__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def __str__(self) -> str:
        return self.code + ": " + self.message

    def to_disclosure(self, stage: str = "adapter") -> Disclosure:
        """The same refusal as a ladder entry, for responses that report rather than raise."""
        ids = self.details.get("element_ids") or ()
        return make_disclosure(self.code, self.message, list(ids), stage=stage)


# ---------------------------------------------------------------------------
# scalars
# ---------------------------------------------------------------------------


def almost_equal(a: float, b: float, tol: float = POINT_TOL_M) -> bool:
    """True when two coordinates are the same within `tol`."""
    return abs(float(a) - float(b)) <= tol


# ---------------------------------------------------------------------------
# rectangles (x, y are the top-left corner in the y-down plan frame)
# ---------------------------------------------------------------------------

Rect = namedtuple("Rect", ["x", "y", "w", "h"])


def rect_bounds(rect: Sequence[float]) -> Tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of a rect given as (x, y, w, h)."""
    x, y, w, h = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
    return (x, y, x + w, y + h)


def rect_area(rect: Sequence[float]) -> float:
    """Area of an (x, y, w, h) rect."""
    return float(rect[2]) * float(rect[3])


def rect_polygon(rect: Sequence[float]) -> List[XY]:
    """The rect as a 4 point loop, no closing vertex, y-down positive shoelace."""
    x0, y0, x1, y1 = rect_bounds(rect)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rect_from_polygon(points: Sequence[Sequence[float]]) -> Rect:
    """Bounding rect of a point loop, as a Rect."""
    return polygon_bbox(points)


def rects_overlap_area(a: Sequence[float], b: Sequence[float]) -> float:
    """Area two (x, y, w, h) rects share; 0.0 when they only touch."""
    ax0, ay0, ax1, ay1 = rect_bounds(a)
    bx0, by0, bx1, by1 = rect_bounds(b)
    dx = min(ax1, bx1) - max(ax0, bx0)
    dy = min(ay1, by1) - max(ay0, by0)
    if dx <= 0.0 or dy <= 0.0:
        return 0.0
    return dx * dy


def rects_overlap(a: Sequence[float], b: Sequence[float], tol: float = POINT_TOL_M) -> bool:
    """True when two rects overlap by more than `tol` on both axes (touching is not overlap)."""
    ax0, ay0, ax1, ay1 = rect_bounds(a)
    bx0, by0, bx1, by1 = rect_bounds(b)
    dx = min(ax1, bx1) - max(ax0, bx0)
    dy = min(ay1, by1) - max(ay0, by0)
    return dx > tol and dy > tol


def bbox_of_rects(rects: Iterable[Sequence[float]]) -> Rect:
    """Bounding rect of a set of rects; a zero Rect when the set is empty."""
    bounds = [rect_bounds(r) for r in rects]
    if not bounds:
        return Rect(0.0, 0.0, 0.0, 0.0)
    x0 = min(b[0] for b in bounds)
    y0 = min(b[1] for b in bounds)
    x1 = max(b[2] for b in bounds)
    y1 = max(b[3] for b in bounds)
    return Rect(x0, y0, x1 - x0, y1 - y0)


# ---------------------------------------------------------------------------
# polygons (rectilinear loops, no closing vertex)
# ---------------------------------------------------------------------------


def polygon_bbox(points: Sequence[Sequence[float]]) -> Rect:
    """Bounding rect of a point loop."""
    if not points:
        return Rect(0.0, 0.0, 0.0, 0.0)
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def polygon_signed_area(points: Sequence[Sequence[float]]) -> float:
    """Shoelace area, positive for the frontend y-down outline winding."""
    count = len(points)
    if count < 3:
        return 0.0
    total = 0.0
    for i in range(count):
        ax, ay = float(points[i][0]), float(points[i][1])
        bx, by = float(points[(i + 1) % count][0]), float(points[(i + 1) % count][1])
        total += ax * by - bx * ay
    return 0.5 * total


def polygon_area(points: Sequence[Sequence[float]]) -> float:
    """Unsigned polygon area."""
    return abs(polygon_signed_area(points))


def is_rectilinear(points: Sequence[Sequence[float]], tol: float = POINT_TOL_M) -> bool:
    """True when every edge is axis aligned and no edge is degenerate.

    Matches `model._is_rectilinear` so anything this returns True for survives
    `StructuralModel.validate()`.
    """
    if len(points) < 4:
        return False
    count = len(points)
    for i in range(count):
        ax, ay = float(points[i][0]), float(points[i][1])
        bx, by = float(points[(i + 1) % count][0]), float(points[(i + 1) % count][1])
        flat_x = abs(bx - ax) <= tol
        flat_y = abs(by - ay) <= tol
        if flat_x == flat_y:
            return False
    return True


def require_rectilinear(
    points: Sequence[Sequence[float]],
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    tol: float = POINT_TOL_M,
) -> None:
    """Raise AdapterError(`code`) unless the loop is a rectilinear loop."""
    if not is_rectilinear(points, tol):
        raise AdapterError(code, message, details)


def is_axis_aligned_rect(points: Sequence[Sequence[float]], tol: float = POINT_TOL_M) -> bool:
    """True when the loop is exactly a 4 corner axis aligned rectangle."""
    if len(points) != 4:
        return False
    if not is_rectilinear(points, tol):
        return False
    box = polygon_bbox(points)
    if box.w <= tol or box.h <= tol:
        return False
    return abs(polygon_area(points) - box.w * box.h) <= tol * max(box.w, box.h, 1.0)


# ---------------------------------------------------------------------------
# intervals and line clustering
# ---------------------------------------------------------------------------


def cluster_values(values: Iterable[float], tol: float = LINE_TOL_M) -> List[float]:
    """Representatives of near equal values, each cluster at most `tol` wide.

    Deterministic: values are sorted, a cluster starts at the smallest value not
    yet taken and absorbs everything within `tol` of that start; the
    representative is the cluster mean.
    """
    ordered = sorted(float(v) for v in values)
    reps = []  # type: List[float]
    i = 0
    while i < len(ordered):
        start = ordered[i]
        j = i
        while j < len(ordered) and ordered[j] - start <= tol:
            j += 1
        members = ordered[i:j]
        reps.append(sum(members) / float(len(members)))
        i = j
    return reps


def cluster_index(value: float, representatives: Sequence[float], tol: float = LINE_TOL_M) -> Optional[int]:
    """Index of the nearest representative within `tol`, or None. Ties take the lower index."""
    best = None  # type: Optional[int]
    best_gap = None  # type: Optional[float]
    for i, rep in enumerate(representatives):
        gap = abs(float(value) - float(rep))
        if gap > tol:
            continue
        if best_gap is None or gap < best_gap - 1e-12:
            best = i
            best_gap = gap
    return best


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """Length two closed intervals share; 0.0 when they only touch or are disjoint."""
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return hi - lo if hi > lo else 0.0


def merge_intervals(
    intervals: Iterable[Sequence[float]], tol: float = POINT_TOL_M
) -> List[Tuple[float, float]]:
    """Merge overlapping and abutting (lo, hi) intervals; sorted, gaps up to `tol` closed."""
    ordered = sorted((min(float(a), float(b)), max(float(a), float(b))) for a, b in intervals)
    merged = []  # type: List[List[float]]
    for lo, hi in ordered:
        if merged and lo <= merged[-1][1] + tol:
            if hi > merged[-1][1]:
                merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return [(run[0], run[1]) for run in merged]


def interval_breakpoints(
    intervals: Iterable[Sequence[float]], tol: float = LINE_TOL_M
) -> List[float]:
    """Sorted endpoints of a set of intervals, endpoints within `tol` clustered into one."""
    endpoints = []  # type: List[float]
    for a, b in intervals:
        endpoints.append(float(a))
        endpoints.append(float(b))
    return cluster_values(endpoints, tol)


# ---------------------------------------------------------------------------
# canonical serialization (fingerprints are the backend dedup key)
# ---------------------------------------------------------------------------


def canonical_json(payload: Any) -> str:
    """Key sorted, whitespace free JSON; the one text a fingerprint is taken over."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(payload: Any) -> str:
    """sha256 of the canonical JSON of `payload`, reusable as a cache key."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
