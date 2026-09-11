"""Allocate coordinated full-side shifts using actual post-shift room areas.

SLSQP is a bounded deterministic constrained allocation heuristic. A candidate
is independently rejected unless every hard constraint holds afterwards.
"""

import numpy as np
from scipy.optimize import minimize
from shapely.geometry import box

from .models import EPS, fail


def allocate(request, selected, groups, deadline=None):
    active = [groups[gid] for gid in sorted(selected)]
    room_index = {room.id: i for i, room in enumerate(request.rooms)}
    nrooms, nvars = len(request.rooms), len(active)
    # Axes: left, top, right, bottom. Each movement is positive inward.
    coefficients = np.zeros((nrooms, 4, nvars))
    constants = np.zeros((nrooms, 4))
    bounds = []
    provenance = {r.id: [] for r in request.rooms}
    for j, group in enumerate(active):
        negative_side, positive_side = (2, 0) if group.orientation == "v" else (3, 1)
        low, high = 0.0, request.width
        for room_id in group.negative:
            i = room_index[room_id]
            coefficients[i, negative_side, j] = 1.0
            provenance[room_id].append((group.id, ("left", "top", "right", "bottom")[negative_side]))
            if request.rooms[i].locked or request.rooms[i].protected:
                high = 0.0
        for room_id in group.positive:
            i = room_index[room_id]
            coefficients[i, positive_side, j] = -1.0
            constants[i, positive_side] = request.width
            provenance[room_id].append((group.id, ("left", "top", "right", "bottom")[positive_side]))
            if request.rooms[i].locked or request.rooms[i].protected:
                low = request.width
        if low > high:
            fail("infeasible_protection", "Both sides of a required wall are locked or protected; neither may contribute corridor area.", wall_group=group.id)
        bounds.append((low, high))
    widths = np.array([r.bounds[2] - r.bounds[0] for r in request.rooms])
    heights = np.array([r.bounds[3] - r.bounds[1] for r in request.rooms])
    areas = widths * heights
    min_width = np.array([r.min_width for r in request.rooms])
    min_height = np.array([r.min_height for r in request.rooms])
    min_area = np.array([r.min_area for r in request.rooms])
    aspects = np.array([r.max_aspect for r in request.rooms])
    changed_indices = np.array([i for i, r in enumerate(request.rooms) if provenance[r.id] and not (r.locked or r.protected)], dtype=int)
    area_scale = max(float(areas.sum()), 1)
    if request.policy == "equal":
        weights = np.ones(nrooms)
    elif request.policy == "surplus":
        weights = np.maximum(areas - np.maximum(min_area, min_width * min_height), EPS)
    else:
        weights = areas

    def dimensions(x):
        shifts = constants + np.einsum("ijk,k->ij", coefficients, x)
        return shifts, widths - shifts[:, 0] - shifts[:, 2], heights - shifts[:, 1] - shifts[:, 3]

    def hard_constraints(x):
        _, w, h = dimensions(x)
        return np.concatenate(((w - min_width), (h - min_height), (w * h - min_area) / np.maximum(widths, heights),
                               (aspects * h - w), (aspects * w - h)))

    def objective(x):
        if deadline is not None:
            deadline()
        _, w, h = dimensions(x)
        lost = areas - w * h
        affected_loss = lost[changed_indices]
        affected_weight = weights[changed_indices]
        target = affected_weight * affected_loss.sum() / max(float(affected_weight.sum()), EPS)
        return float(np.square((affected_loss - target) / area_scale).sum() + 1e-10 * lost.sum() / area_scale)

    initial = np.array([(low + high) / 2 for low, high in bounds])
    solutions = []
    if min(hard_constraints(initial), default=0) >= -EPS:
        solutions.append(initial)
    result = minimize(objective, initial, method="SLSQP", bounds=bounds,
                      constraints=[{"type": "ineq", "fun": hard_constraints}],
                      options={"maxiter": 160, "ftol": 1e-12, "disp": False})
    if np.isfinite(result.x).all() and min(hard_constraints(result.x), default=0) >= -EPS:
        solutions.append(result.x)
    if not solutions:
        fail("infeasible_dimensions", "The requested corridor width cannot be allocated while preserving room minimum dimensions, area, aspect ratio and protected geometry. Reduce width, select fewer rooms, or choose another entrance.", solver_message=str(result.message))
    chosen = min(solutions, key=objective)
    shifts, _, _ = dimensions(chosen)
    adjusted = {}
    for i, room in enumerate(request.rooms):
        x0, y0, x1, y1 = room.bounds
        left, top, right, bottom = shifts[i]
        adjusted[room.id] = box(x0 + left, y0 + top, x1 - right, y1 - bottom)
    offsets = {group.id: float(chosen[j]) for j, group in enumerate(active)}
    constrained = bool(not result.success or objective(chosen) > 1e-9 or any(abs(chosen[j] - low) < EPS or abs(chosen[j] - high) < EPS for j, (low, high) in enumerate(bounds)))
    return adjusted, offsets, provenance, constrained
