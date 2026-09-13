"""Housing-only geometry assessment for one to three total storeys.

These are deterministic candidates, not a structural or cost optimum. A guide
line is not a wall: use finite architectural wall segments on every storey.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict

from ..model import Occupancy, StoreyKind, StructuralModel, WallRole

WALL_ALIGNMENT_M = 0.30
SEARCH_CANDIDATE_LIMIT = 48
WALL_STATION_LIMIT = 128
MIN_REPOSITION_MM = 400
_OPEN_OCCUPANCIES = {Occupancy.PARKING, Occupancy.GREEN, Occupancy.VOID, Occupancy.CORRIDOR, Occupancy.BALCONY, Occupancy.STAIR, Occupancy.LIFT}


def wall_station_pool(model, grid, cap_m, priority_points=()):
    """Canonical finite-wall pool, capped by count, never by elapsed time.

    Endpoints include wall junctions; axis intersections and even/legal span
    stations add positions along the actual finite segments. Millimetres are
    the placement precision. Failed bearing endpoints take priority, followed
    by wall endpoints, grid crossings and subdivisions, each lexicographically.
    """
    points = {tuple(point): 0 for point in priority_points}
    xs = [axis.pos_mm for axis in grid.x_axes]
    ys = [axis.pos_mm for axis in grid.y_axes]
    cap = max(1, int(round(cap_m * 1000)))
    wall_runs = []
    for wall in sorted(model.walls, key=lambda w: (w.storey, w.id)):
        if wall.role in (WallRole.RAILING, WallRole.PARAPET):
            continue
        a, b = [tuple(int(round(v * 1000)) for v in p) for p in (wall.a, wall.b)]
        for point in (a, b):
            points[point] = min(points.get(point, 1), 1)
        if a[0] != b[0] and a[1] != b[1]:
            continue
        horizontal = a[1] == b[1]
        lo, hi = sorted((a[0], b[0]) if horizontal else (a[1], b[1]))
        fixed = a[1] if horizontal else a[0]
        wall_runs.append((wall.storey, horizontal, fixed, lo, hi))
        stations = {value: 2 for value in (xs if horizontal else ys) if lo <= value <= hi}
        count = max(1, int(math.ceil((hi - lo) / cap)))
        for index in range(1, min(count, 16)):
            stations[int(round(lo + (hi - lo) * index / count))] = 3
        for value in ((lo + hi) // 2, lo + cap, hi - cap):
            if lo < value < hi:
                stations.setdefault(value, 3)
        for value, priority in stations.items():
            point = (value, fixed) if horizontal else (fixed, value)
            points[point] = min(points.get(point, priority), priority)
    # True internal wall crossings need not coincide with a merged grid axis.
    # Keep their actual finite intersection, not an extended guide crossing.
    for storey, horizontal, y, x0, x1 in wall_runs:
        if not horizontal:
            continue
        for other_storey, other_horizontal, x, y0, y1 in wall_runs:
            if other_storey == storey and not other_horizontal and x0 <= x <= x1 and y0 <= y <= y1:
                points[(x, y)] = min(points.get((x, y), 2), 2)
    ordered = sorted(points, key=lambda point: (points[point], point))
    return [point for point in ordered if any(
        near_wall(model, storey.index, point[0] / 1000, point[1] / 1000)
        for storey in model.storeys
    )][:WALL_STATION_LIMIT]


def near_wall(model: StructuralModel, storey: int, x_m: float, y_m: float) -> bool:
    for wall in model.walls:
        if wall.storey != storey or wall.role in (WallRole.RAILING, WallRole.PARAPET):
            continue
        dx, dy = wall.b[0] - wall.a[0], wall.b[1] - wall.a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x_m-wall.a[0])*dx + (y_m-wall.a[1])*dy) / length2))
        if math.hypot(x_m-wall.a[0]-t*dx, y_m-wall.a[1]-t*dy) <= WALL_ALIGNMENT_M + 1e-9:
            return True
    return False


def _strictly_inside(polygon, x_m: float, y_m: float) -> bool:
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        if abs((x_m-a[0])*dy - (y_m-a[1])*dx) < 1e-9 and min(a[0], b[0])-1e-9 <= x_m <= max(a[0], b[0])+1e-9 and min(a[1], b[1])-1e-9 <= y_m <= max(a[1], b[1])+1e-9:
            return False
        if (a[1] > y_m) != (b[1] > y_m) and x_m < a[0] + (y_m-a[1])*dx/dy:
            inside = not inside
    return inside


def point_assessment(model: StructuralModel, storey: int, x_m: float, y_m: float) -> str:
    """intrusion, clear or unassessed; an unrelated unknown room is irrelevant."""
    if near_wall(model, storey, x_m, y_m):
        return "clear"
    rooms = [r for r in model.rooms if r.storey == storey]
    containing = [r for r in rooms if _strictly_inside(r.polygon, x_m, y_m)]
    known = [r for r in containing if not r.interior_unknown]
    if any(r.occupancy not in _OPEN_OCCUPANCIES for r in known):
        return "intrusion"
    if known:
        return "clear"
    if containing:
        return "unassessed"
    level = model.storey(storey)
    if not rooms and (level is None or level.kind != StoreyKind.STILT):
        return "unassessed"
    return "clear"


def assess(model: StructuralModel, min_span_m: float = 2.5) -> Dict[str, Any]:
    assessed = {c.id: point_assessment(model, c.storey, c.x_m, c.y_m) for c in model.columns}
    off_wall_ids = sorted(c.id for c in model.columns if not near_wall(model, c.storey, c.x_m, c.y_m))
    intrusion_ids = sorted(c.id for c in model.columns if assessed[c.id] == "intrusion")
    unknown_ids = sorted(c.id for c in model.columns if assessed[c.id] == "unassessed")
    unknown_storeys = sorted({c.storey for c in model.columns if c.id in unknown_ids})
    geometry = sorted({(c.storey, round(c.x_m, 3), round(c.y_m, 3)) for c in model.columns})
    stacks = {c.stack_id or c.id for c in model.columns}
    pairs = {}
    nearest = None
    for storey in sorted(s.index for s in model.storeys):
        columns = sorted([c for c in model.columns if c.storey == storey], key=lambda c: (c.x_m, c.y_m, c.id))
        for i, a in enumerate(columns):
            for b in columns[i + 1:]:
                distance = math.hypot(a.x_m-b.x_m, a.y_m-b.y_m)
                if distance <= 1e-9:
                    continue
                nearest = distance if nearest is None else min(nearest, distance)
                if distance < min_span_m - 1e-9:
                    key = tuple(sorted((a.stack_id or a.id, b.stack_id or b.id)))
                    pairs[key] = min(pairs.get(key, distance), distance)
    return {
        "geometry_fingerprint": hashlib.sha256(json.dumps(geometry, separators=(",", ":")).encode()).hexdigest(),
        "column_stack_count": len(stacks),
        "off_wall_column_count": len(off_wall_ids),
        "off_wall_column_ids": off_wall_ids,
        "closest_column_centres_m": None if nearest is None else round(nearest, 3),
        "close_pair_count": len(pairs),
        "close_pair_deficit_m": round(sum(max(0.0, min_span_m-gap) for gap in pairs.values()), 3),
        "close_pair_basis": "unique final column-stack pairs on shared storeys; Euclidean centre distance below requested min_span; includes explained corridor/core exceptions",
        "room_intrusion_count": None if unknown_ids else len({c.stack_id or c.id for c in model.columns if c.id in intrusion_ids}),
        "confirmed_room_intrusion_count": len({c.stack_id or c.id for c in model.columns if c.id in intrusion_ids}),
        "room_intrusion_column_ids": intrusion_ids,
        "room_assessment": ("partial" if len(unknown_ids) < len(model.columns) else "unassessed") if unknown_ids else "assessed",
        "assessed_column_count": len(model.columns) - len(unknown_ids),
        "unassessed_column_ids": unknown_ids,
        "unassessed_storeys": sorted(unknown_storeys),
        "wall_alignment_tolerance_m": WALL_ALIGNMENT_M,
    }
