"""
HPWL-aware dimensioning for a fixed rectangular dual (opt-in, flag-gated).

Adds a half-perimeter wirelength objective to the existing per-axis flow LPs
(convert_adj_equ_sym): under a fixed dissection, room positions are prefix
sums of the solved dimensions, hence affine in the flow variables, so exact
bounding-box HPWL enters as two auxiliary variables and two rows per net pin.
The x-part rides the width (VER) LP, the y-part the height (HOR) LP, so the
engine's sequential two-LP structure and its aspect-ratio coupling survive.

Activation: a caller (the API layer / local bridge) installs the net list for
the CURRENT request with set_nets() and clears it afterwards. When no nets
are installed, floorplan_to_st takes its historical path bit for bit; this
module is then never imported into the solve.

Net format: [{"weight": w, "pins": [room_index, ...],
              "pads_x": [x, ...], "pads_y": [y, ...]}, ...]
Room indices are the caller's node indices (the encoded matrix's room ids);
pads are fixed die-edge coordinates in plot units, per axis. Rooms the
dissection added (merged/extra nodes) simply never appear in pins.

Prototype and measurements: GPLAN_Studio/vlsi_plan/prototype/ and
vlsi_plan/appendix/a1_affine_verification.md / a2_prototype_results.md.
"""

import numpy as np
import scipy.optimize

_NETS = None


def set_nets(nets):
    """Install the net list for the current request (None to clear)."""
    global _NETS
    _NETS = nets if nets else None


def active():
    return _NETS is not None


def _prefix_chains(E0, axis):
    """chains[r] = room ids whose dims sum to room r's x (axis 0) / y (axis 1).

    Along room r's first row (or column) in the encoded matrix, the distinct
    rooms before r's first cell; path independence across rows is exactly the
    flow-conservation equality the LP already enforces.
    """
    E = np.array(E0)
    n = int(E.max()) + 1
    chains = {}
    for r in range(n):
        rows, cols = np.where(E == r)
        if rows.shape[0] == 0:
            chains[r] = []
            continue
        if axis == 0:
            r0 = rows.min()
            line = E[r0, :]
            first = cols[rows == r0].min()
        else:
            c0 = cols.min()
            line = E[:, c0]
            first = rows[cols == c0].min()
        seen = set()
        out = []
        for v in line[:first]:
            v = int(v)
            if v != r and v not in seen:
                seen.add(v)
                out.append(v)
        chains[r] = out
    return chains


def _solve_axis(A, Aeq, Beq, dmin, dmax, chains, nets_axis, plot):
    """Augmented LP for one axis. Returns dims array or None on failure."""
    nrooms = len(dmin)
    nflow = A.shape[1]
    A_max_rows = A[nrooms:, :]  # dim_i = A_max_rows[i] . X
    nnet = len(nets_axis)
    nvar = nflow + 2 * nnet

    def centre_row(i):
        row = 0.5 * A_max_rows[i].astype(float)
        for j in chains.get(i, []):
            row = row + A_max_rows[j]
        return row

    rows_ub = []
    b_ub = []
    b_dim = np.hstack([-np.array(dmin, float), np.array(dmax, float)])
    for r, b in zip(A, b_dim):
        rows_ub.append(np.hstack([r, np.zeros(2 * nnet)]))
        b_ub.append(b)
    for e, (wgt, pins, pads) in enumerate(nets_axis):
        for i in pins:
            c = centre_row(i)
            ru = np.hstack([c, np.zeros(2 * nnet)])
            ru[nflow + 2 * e] = -1
            rows_ub.append(ru)
            b_ub.append(0.0)  # c_i - U_e <= 0
            rl = np.hstack([-c, np.zeros(2 * nnet)])
            rl[nflow + 2 * e + 1] = 1
            rows_ub.append(rl)
            b_ub.append(0.0)  # L_e - c_i <= 0
        for v in pads:
            ru = np.zeros(nvar)
            ru[nflow + 2 * e] = -1
            rows_ub.append(ru)
            b_ub.append(-float(v))
            rl = np.zeros(nvar)
            rl[nflow + 2 * e + 1] = 1
            rows_ub.append(rl)
            b_ub.append(float(v))

    A_ub = np.array(rows_ub)
    A_eq = np.hstack([Aeq, np.zeros((Aeq.shape[0], 2 * nnet))])
    b_eq = np.array(Beq).flatten()

    c = np.zeros(nvar)
    for e, (wgt, pins, pads) in enumerate(nets_axis):
        c[nflow + 2 * e] = wgt
        c[nflow + 2 * e + 1] = -wgt

    bounds = [(1, None)] * nflow + [(0, None)] * (2 * nnet)
    res = scipy.optimize.linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                                 bounds=bounds, method="highs")
    if not res.success:
        return None
    return A_max_rows @ res.x[:nflow]


def _nets_axis(axis, nrooms):
    out = []
    for net in _NETS:
        pins = [int(p) for p in net.get("pins", []) if 0 <= int(p) < nrooms]
        pads = net.get("pads_x" if axis == 0 else "pads_y", []) or []
        if len(pins) + len(pads) >= 2:
            out.append((float(net.get("weight", 1)), pins, pads))
    return out


def solve_linear_hpwl(E0, f_VER, A_VER, Aeq_VER, Beq_VER, f_HOR, A_HOR, Aeq_HOR, Beq_HOR,
                      min_width, max_width, min_height, max_height, min_ar, max_ar):
    """Drop-in for solve_linear when nets are installed. Same returns
    [W, H, status]; W/H in solve_linear's stacked (-A . X) layout so
    floorplan_to_st's callers are untouched. Falls back to None on any LP
    failure so the caller can run the historical path."""
    p = len(min_height)
    chains_x = _prefix_chains(E0, 0)
    chains_y = _prefix_chains(E0, 1)

    width = _solve_axis(A_VER, Aeq_VER, Beq_VER, min_width, max_width,
                        chains_x, _nets_axis(0, p), None)
    if width is None:
        return None
    a = list(width[:p])

    # sequential aspect-ratio coupling, mirroring solve_linear lines 90-129
    min_h_mod = []
    max_h_mod = []
    for i in range(p):
        min_h_mod.append(max(min_ar[i] * a[i], min_height[i]))
        max_h_mod.append(min(max_ar[i] * a[i], max_height[i]))
    if any(min_h_mod[i] > max_h_mod[i] for i in range(p)):
        min_h_mod = list(min_height)
        max_h_mod = list(max_height)

    height = _solve_axis(A_HOR, Aeq_HOR, Beq_HOR, min_h_mod, max_h_mod,
                         chains_y, _nets_axis(1, p), None)
    if height is None:
        return None

    # solve_linear returns column vectors W = -A_min.X stacked (min rows then
    # max rows); its caller keeps W[0:l/2]. Reproduce that shape.
    W = np.vstack([width.reshape(-1, 1), -width.reshape(-1, 1)])
    H = np.vstack([height.reshape(-1, 1), -height.reshape(-1, 1)])
    return [np.round(W, 3), np.round(H, 3), True]


# ---------------------------------------------------------------------------
# Geometry-level refinement: re-dimension finished floorplans (any caller).
# The door_connectivity path dimensions through minimum_dimensioning, not
# floorplan_to_st, so the bridge applies this pass to the serialized response
# when the request carries nets. Works on the plan geometry alone: rebuild
# the dissection's st-digraphs from the rectangles, solve the augmented LPs
# at the plan's own outline with the plan's dims as feasibility witness, then
# map every coordinate in each room dict through its room-local affine.

_EPS = 5e-3


def _rects_of_plan(plan):
    rects = {}
    for k, room in enumerate(plan):
        cc = room.get("circular_coordinates")
        if not cc or len(cc) != 4:
            return None
        xs = [pt[0] for pt in cc]
        ys = [pt[1] for pt in cc]
        rects[k] = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
    x0 = min(r[0] for r in rects.values())
    y0 = min(r[1] for r in rects.values())
    for r in rects.values():
        r[0] -= x0
        r[1] -= y0
    return rects


def _seam_digraphs(rects):
    n = len(rects)
    ver = np.zeros((n + 1, n + 1), int)
    hor = np.zeros((n + 1, n + 1), int)
    for a, (ax, ay, aw, ah) in rects.items():
        if ay < _EPS:
            ver[0][a + 1] = 1
        if ax < _EPS:
            hor[0][a + 1] = 1
        for b, (bx, by, bw, bh) in rects.items():
            if a == b:
                continue
            if abs(ax + aw - bx) < _EPS and min(ay + ah, by + bh) - max(ay, by) > _EPS:
                hor[a + 1][b + 1] = 1
            if abs(ay + ah - by) < _EPS and min(ax + aw, bx + bw) - max(ax, bx) > _EPS:
                ver[a + 1][b + 1] = 1
    return ver, hor


def _chains_from_seams(rects, axis):
    n = len(rects)
    into = {i: [] for i in range(n)}
    for a, (ax, ay, aw, ah) in rects.items():
        for b, (bx, by, bw, bh) in rects.items():
            if a == b:
                continue
            if axis == 0 and abs(ax + aw - bx) < _EPS and min(ay + ah, by + bh) - max(ay, by) > _EPS:
                into[b].append(a)
            if axis == 1 and abs(ay + ah - by) < _EPS and min(ax + aw, bx + bw) - max(ax, bx) > _EPS:
                into[b].append(a)
    memo = {}

    def chain(b):
        if b in memo:
            return memo[b]
        pos = rects[b][0] if axis == 0 else rects[b][1]
        if pos < _EPS or not into[b]:
            memo[b] = []
        else:
            p = into[b][0]
            memo[b] = chain(p) + [p]
        return memo[b]

    return {i: chain(i) for i in range(n)}


def _map_point(pt, old, new):
    ox, oy, ow, oh = old
    nx, ny, nw, nh = new
    return [nx + (pt[0] - ox) * (nw / ow if ow else 1),
            ny + (pt[1] - oy) * (nh / oh if oh else 1)]


def refine_response(response, nets, bounds_by_name=None):
    """Re-dimension every rectangular floorplan in a serialized response for
    minimum HPWL at its own outline. Mutates the response; returns how many
    plans were refined. Never raises: a plan that fails any step is left as
    the engine produced it."""
    if not nets:
        return 0
    global _NETS
    keep = _NETS
    _NETS = nets
    refined = 0
    try:
        from .convert_adj_equ_sym import convert_adj_equ_sym
        plans = response.get("Documents", {}).get("floorPlans", [])
        for plan in plans:
            try:
                rects = _rects_of_plan(plan)
                if rects is None:
                    continue
                n = len(rects)
                W_out = max(r[0] + r[2] for r in rects.values())
                H_out = max(r[1] + r[3] for r in rects.values())
                ver, hor = _seam_digraphs(rects)
                fV, AV, AeqV, BeqV = convert_adj_equ_sym(ver, [], round(W_out, 3))
                fH, AH, AeqH, BeqH = convert_adj_equ_sym(hor, [], round(H_out, 3))
                chains_x = _chains_from_seams(rects, 0)
                chains_y = _chains_from_seams(rects, 1)
                # request bounds, relaxed to admit the engine's own dims
                wmin, wmax, hmin, hmax = [], [], [], []
                for i in range(n):
                    name = plan[i].get("name")
                    bb = (bounds_by_name or {}).get(name)
                    if bb:
                        wmin.append(min(bb[0], rects[i][2]))
                        wmax.append(max(bb[1], rects[i][2]))
                        hmin.append(min(bb[2], rects[i][3]))
                        hmax.append(max(bb[3], rects[i][3]))
                    else:
                        wmin.append(min(1.0, rects[i][2]))
                        wmax.append(rects[i][2] * 3)
                        hmin.append(min(1.0, rects[i][3]))
                        hmax.append(rects[i][3] * 3)
                width = _solve_axis(AV, AeqV, BeqV, wmin, wmax, chains_x, _nets_axis(0, n), None)
                if width is None:
                    continue
                height = _solve_axis(AH, AeqH, BeqH, hmin, hmax, chains_y, _nets_axis(1, n), None)
                if height is None:
                    continue
                new_rects = {}
                for i in range(n):
                    x = sum(width[j] for j in chains_x[i])
                    y = sum(height[j] for j in chains_y[i])
                    new_rects[i] = [float(x), float(y), float(width[i]), float(height[i])]
                for i, room in enumerate(plan):
                    old, new = rects[i], new_rects[i]
                    room["circular_coordinates"] = [
                        _map_point(pt, old, new) for pt in room["circular_coordinates"]]
                    if room.get("label_coord"):
                        room["label_coord"] = _map_point(room["label_coord"], old, new)
                    room["width"] = round(new[2], 3)
                    room["height"] = round(new[3], 3)
                    room["area"] = round(new[2] * new[3], 6)
                    for wall in room.get("walls", []) or []:
                        p1 = _map_point([wall["x1"], wall["y1"]], old, new)
                        p2 = _map_point([wall["x2"], wall["y2"]], old, new)
                        wall["x1"], wall["y1"] = round(p1[0], 3), round(p1[1], 3)
                        wall["x2"], wall["y2"] = round(p2[0], 3), round(p2[1], 3)
                refined += 1
            except Exception:
                continue
    finally:
        _NETS = keep
    return refined
