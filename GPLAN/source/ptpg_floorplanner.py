"""Exact-dimension PTPG floorplan placer (the "PDF algorithm").

Headless port of ``ptpgfloorplanner.py`` from the GPLAN-team/GPLAN branch
``ptpg_floorplanner``. The original file was a self-contained Tkinter desktop
app that mocked out ``tkinter``/``turtle`` at import time; everything below is
the algorithmic core only, rewritten against this repository's packaged
``GPLAN.source.*`` layout so it can run inside a Celery worker.

ALGORITHM (unchanged from the source branch):

  INPUT: planar graph G, room dims rw[v] x rh[v], feasible boundary B=[N,E,S,W].

  STEP 1  Get 4 corner vertices {BL,BR,TR,TL} from B.
          Shortcuts = graph edges between two boundary nodes not consecutive on
          the boundary cycle.

  STEP 2  Build height_table H and width_table Wt from the boundary arcs.
            H[v]  = row index of v's TOP edge   (row 1 = bottom of plot)
            Wt[v] = col index of v's RIGHT edge (col 1 = left of plot)

  STEP 3  Build G' - the edge-labelled graph from G and B.
            green (shared vertical wall):   H[u]-rh[u] == H[v]-rh[v]
            red   (shared horizontal wall): otherwise

  STEP 4  Repeat until all rooms placed, starting at corner n = BL:
          a. Find current BL corner in G' (first unplaced corner going CW).
          b. Check if BL is adjacent to a shortcut endpoint p.
          c. If yes: m = common unplaced neighbour of BL and p. If no: m = BL.
          d. Place m in the encoded matrix M.
          e. Propagate H/Wt to unplaced neighbours, labelling edges green/red.
          f. Remove m from G', update the boundary cycle, find the new BL.

  STEP 5  Pixel coords: px = Wt[v]-rw[v], py = H[v]-rh[v] (y=0 at the bottom).

Differences from the branch version, all additive:

* ``get_boundaries(..., already_ptpg=True)`` skips biconnectivity augmentation
  and triangulation. PTPG variants coming out of :mod:`GPLAN.source.multiple_ptpg`
  are already internally triangulated, and re-triangulating them would add back
  the very edges a boundary-edge-removal variant deliberately dropped.
* ``max_boundaries`` bounds the brute-force 4-split enumeration, which is
  O(k^4) in the outer-cycle length and would otherwise dominate runtime on
  graphs with a long boundary.
* ``deadline`` (a ``time.monotonic()`` stamp) lets a caller cap wall-clock cost
  so a worker cannot blow through its soft time limit.
* ``FloorplanResult.to_dict()`` for JSON serialization.
"""

import copy
import time

import numpy as np
import networkx as nx

from GPLAN.source.graphoperations import operations as opr
from GPLAN.source.graphoperations import biconnectivity as bcn
from GPLAN.source.graphoperations import triangularity as trng
from GPLAN.source.graphoperations import graph_crossings1 as gc
from GPLAN.source.irregular import shortcutresolver as sr
from GPLAN.source.boundary import cip as cip_mod
from GPLAN.source.boundary import news as news_mod


DEFAULT_MAX_BOUNDARIES = 48

# Cardinal directions as boundary-arc indices, matching GPLAN.api's
# CARDINAL_DIR_INDEX and FloorplanResult.boundary's [[N],[E],[S],[W]] order.
CARDINAL_N, CARDINAL_E, CARDINAL_S, CARDINAL_W = 0, 1, 2, 3


class DeadlineExceeded(Exception):
    """Raised when the caller-supplied wall-clock budget runs out."""


def _check_deadline(deadline):
    if deadline is not None and time.monotonic() > deadline:
        raise DeadlineExceeded()


# =============================================================================
# DATA STRUCTURE
# =============================================================================

class FloorplanResult:
    """One dimensioned layout for one boundary of one graph."""

    def __init__(self, boundary, encoded_matrix, room_rects, node_ids,
                 edge_labels, is_relaxed=False):
        self.boundary = boundary              # [[N],[E],[S],[W]] of user IDs
        self.encoded_matrix = encoded_matrix   # 2-D numpy, row 0 = screen top
        self.room_rects = room_rects           # {nid: (x, y, w, h)}, y=0 bottom
        self.node_ids = node_ids
        self.edge_labels = edge_labels         # {frozenset({u,v}): 'green'|'red'}
        self.is_relaxed = is_relaxed           # layout may contain empty space

    def total_size(self):
        if not self.room_rects:
            return 1, 1
        tw = max(x + w for x, y, w, h in self.room_rects.values())
        th = max(y + h for x, y, w, h in self.room_rects.values())
        return tw, th

    def adjacency_report(self, edges):
        """Which required adjacencies the layout realises, and which it invents.

        Returned counts are what the API exposes as ``satisfied`` /
        ``missing`` / ``extra``; a non-relaxed plan always scores 0 missing and
        0 extra because :func:`_pdf_place` rejects anything else.
        """
        actual = _matrix_adjacencies(self.encoded_matrix, self.node_ids)
        required = {tuple(sorted((str(u), str(v)))) for u, v in edges}
        return {
            "satisfied": sorted(required & actual),
            "missing": sorted(required - actual),
            "extra": sorted(actual - required),
        }

    def to_dict(self, edges=None, room_names=None):
        tw, th = self.total_size()
        rooms = []
        for nid in self.node_ids:
            x, y, w, h = self.room_rects[nid]
            room = {
                "id": nid,
                "x": float(x),
                "y": float(y),
                "width": float(w),
                "height": float(h),
                "area": float(w) * float(h),
            }
            if room_names is not None and nid < len(room_names):
                room["name"] = room_names[nid]
            rooms.append(room)

        payload = {
            "rooms": rooms,
            "width": float(tw),
            "height": float(th),
            "area": float(tw) * float(th),
            "is_relaxed": bool(self.is_relaxed),
            "boundary": {
                "N": list(self.boundary[0]),
                "E": list(self.boundary[1]),
                "S": list(self.boundary[2]),
                "W": list(self.boundary[3]),
            },
            "edge_labels": [
                {"source": min(pair), "target": max(pair), "wall": label}
                for pair, label in (
                    (tuple(sorted(k)), v) for k, v in self.edge_labels.items()
                )
                if label is not None and len(pair) == 2
            ],
            "encoded_matrix": self.encoded_matrix.tolist(),
        }
        if edges is not None:
            payload["adjacency"] = self.adjacency_report(edges)
        return payload


def _matrix_adjacencies(matrix, node_ids):
    """Adjacencies actually realised by an encoded matrix (shared wall segments)."""
    actual = set()
    th, tw = matrix.shape
    for r in range(th):
        for c in range(tw):
            v1 = matrix[r][c]
            if v1 == -1:
                continue
            if c + 1 < tw:
                v2 = matrix[r][c + 1]
                if v2 != -1 and v1 != v2:
                    actual.add(tuple(sorted((str(node_ids[v1]), str(node_ids[v2])))))
            if r + 1 < th:
                v2 = matrix[r + 1][c]
                if v2 != -1 and v1 != v2:
                    actual.add(tuple(sorted((str(node_ids[v1]), str(node_ids[v2])))))
    return actual


# =============================================================================
# CARDINAL (N/E/S/W) CONSTRAINTS
# =============================================================================

def plan_satisfies_cardinal(room_rects, cardinal_pairs):
    """True when every ``(node_id, dir_idx)`` pin faces that side of the layout.

    Same idea as :func:`GPLAN.api.plan_satisfies_cardinal`, with two differences
    that both matter:

    * **y grows upward here.** ``FloorplanResult.room_rects`` puts y=0 at the
      bottom, so N is the high-y side and S the low-y one - the opposite of the
      y-down frame api.py reads. Getting that flip wrong silently swaps north and
      south, which is worse than not filtering at all.
    * **A void is not a recess.** The strip test alone ("no other room sits
      between this wall and the layout bounds") is exactly right for a gapless
      tiling, which is what door_connectivity returns. This endpoint's
      ``relaxed``/``best_effort`` layouts may contain real empty space, and
      across a void the strip test passes for a room nowhere near that side: a
      4x6 toilet ended up 11 ft short of the north edge, with nothing above it,
      and counted as north-facing. So the gap to the bounds must also be small
      enough to be a recess.

    The recess allowance is the smallest room dimension in the layout: a gap that
    could hold a room is a void, and a room across a void is not on that side of
    the plan. That is a threshold derived from the brief rather than a tuned
    constant, and it keeps the "exterior-facing, not flush" rule the graph path
    relies on, since min-dim recesses are far shallower than any room.
    """
    if not cardinal_pairs:
        return True
    if not room_rects:
        return False
    rects = {nid: (x, x + w, y, y + h) for nid, (x, y, w, h) in room_rects.items()}
    bx0 = min(r[0] for r in rects.values())
    bx1 = max(r[1] for r in rects.values())
    by0 = min(r[2] for r in rects.values())
    by1 = max(r[3] for r in rects.values())
    # Relative tolerance: a shared wall intersects the strip with ~zero depth
    # and must not read as a blocker at any unit scale.
    eps = max(bx1 - bx0, by1 - by0, 1e-6) * 1e-4
    recess_limit = min(min(w, h) for _, _, w, h in room_rects.values())

    for node, dir_idx in cardinal_pairs:
        if node not in rects:
            return False
        rx0, rx1, ry0, ry1 = rects[node]
        if dir_idx == CARDINAL_N:
            gap = by1 - ry1
            sx0, sx1, sy0, sy1 = rx0, rx1, ry1, by1
        elif dir_idx == CARDINAL_E:
            gap = bx1 - rx1
            sx0, sx1, sy0, sy1 = rx1, bx1, ry0, ry1
        elif dir_idx == CARDINAL_S:
            gap = ry0 - by0
            sx0, sx1, sy0, sy1 = rx0, rx1, by0, ry0
        else:
            gap = rx0 - bx0
            sx0, sx1, sy0, sy1 = bx0, rx0, ry0, ry1
        if gap > eps and gap >= recess_limit:
            return False
        for other, (ox0, ox1, oy0, oy1) in rects.items():
            if other == node:
                continue
            if (min(ox1, sx1) - max(ox0, sx0) > eps and
                    min(oy1, sy1) - max(oy0, sy0) > eps):
                return False
    return True


def _cardinal_boundary_score(boundary, cardinal_pairs):
    """How many pins a boundary's own N/E/S/W arcs already place correctly.

    Used to ORDER candidate boundaries, never to drop them. The arcs are what
    drives placement, so aiming the search at boundaries that put a pinned room
    on the right side finds satisfying layouts far sooner; but the arcs are a
    topological assignment and the geometry is the truth, so a boundary that
    scores 0 can still solve and must stay in the list.
    """
    if not cardinal_pairs:
        return 0
    return sum(1 for node, dir_idx in cardinal_pairs
               if 0 <= dir_idx < len(boundary) and node in boundary[dir_idx])


def order_boundaries_by_cardinal(boundaries, cardinal_pairs):
    """Boundaries best-aimed at the pins first; stable, and never truncated."""
    if not cardinal_pairs:
        return boundaries
    return sorted(boundaries,
                  key=lambda b: -_cardinal_boundary_score(b, cardinal_pairs))


# =============================================================================
# STEP 1: BOUNDARY GENERATION
# =============================================================================

def get_boundaries(node_ids, edges, node_positions=None, already_ptpg=False,
                   max_boundaries=DEFAULT_MAX_BOUNDARIES, deadline=None,
                   cardinal_pairs=None, stats=None):
    """Enumerate feasible N/E/S/W boundary splits for the graph.

    ``already_ptpg=True`` promises the caller's graph is internally
    triangulated with a simple-cycle outer face - the biconnectivity and
    triangulation passes are then skipped so variant topology survives intact.

    ``max_boundaries`` counts RAW boundaries (distinct 4-splits before symmetry),
    and every kept raw boundary is emitted with its complete 8-element dihedral
    orbit (4 rotations x 2 orientations). It used to slice the flat list AFTER
    all orbits were appended behind all raw entries, which cut orbit-first: on a
    10-node outer cycle the default kept 0 of 371 orbit members, so whole
    symmetry families (including every reflection) vanished and an 8-room ring
    returned 5 plans where the uncapped run returns 13 - with a reason string
    blaming the room sizes. The cap exists to bound the O(k^4) 4-split blowup,
    which lives entirely in the raw list, so that is what it counts now.

    ``cardinal_pairs`` aims the cap: raw boundaries are ordered by the best pin
    score across their orbit BEFORE truncation, so the kept slice is the
    pin-relevant one. Ordering only - no boundary is dropped for scoring 0.

    ``stats`` (optional dict) reports ``raw_total``, ``raw_kept`` and
    ``truncated`` so a caller can say when the cap bound instead of blaming
    the room sizes.
    """
    n = len(node_ids)
    idx = {nid: i for i, nid in enumerate(node_ids)}
    mat = np.zeros((n, n), int)
    ec = 0
    for u, v in edges:
        if u in idx and v in idx and mat[idx[u]][idx[v]] == 0:
            mat[idx[u]][idx[v]] = mat[idx[v]][idx[u]] = 1
            ec += 1

    # Coordinates used by the triangulation pass and by the crossing check.
    if node_positions and all(nid in node_positions for nid in node_ids):
        raw = [node_positions[nid] for nid in node_ids]
        xs, ys = [p[0] for p in raw], [p[1] for p in raw]
        rx = (max(xs) - min(xs)) or 1.0
        ry = (max(ys) - min(ys)) or 1.0
        coords = [((p[0] - min(xs)) / rx, 1.0 - (p[1] - min(ys)) / ry) for p in raw]
        try:
            if gc.check_intersection([c[0] for c in coords], [c[1] for c in coords], mat):
                coords = list(nx.planar_layout(nx.from_numpy_array(mat)).values())
        except Exception:
            coords = list(nx.planar_layout(nx.from_numpy_array(mat)).values())
    else:
        coords = list(nx.planar_layout(nx.from_numpy_array(mat)).values())

    if not already_ptpg:
        if not bcn.is_biconnected(mat):
            for e in bcn.biconnect(mat):
                mat[e[0]][e[1]] = mat[e[1]][e[0]] = 1
                ec += 1
        try:
            te, _, __ = trng.triangulate(copy.deepcopy(mat), False, coords)
        except Exception:
            te = []
        for e in te:
            mat[e[0]][e[1]] = mat[e[1]][e[0]] = 1
            ec += 1

    _check_deadline(deadline)

    # CIP enumeration -> boundary list
    trngls = opr.get_trngls(mat)
    dg = opr.get_directed(mat)
    bn, be = opr.get_bdy(trngls, dg)
    sc = sr.get_shortcut(mat, bn, be)

    if ec == 3 and n == 3:
        raw_list = [[[0], [0, 1], [1, 2], [2, 0]],
                    [[0, 1], [1], [1, 2], [2, 0]],
                    [[0, 1], [1, 2], [2], [2, 0]]]
    else:
        bo = opr.ordered_bdy(bn, be)
        cips = cip_mod.find_cip(bo, sc)
        paths = [p for p in news_mod.find_bdy(cips) if len(p) > 0]

        raw_list = []
        if paths:
            corners = news_mod.multiple_corners(paths)
            all_b = news_mod.all_boundaries(corners, bo)
            raw_list = news_mod.find_multiple_boundary(all_b, bo)

        # The CIP machinery returns nothing when the outer boundary carries no
        # shortcuts; fall back to enumerating consecutive 4-splits of the cycle.
        if not raw_list:
            k = len(bo)
            if k < 3:
                return []
            if k == 3:
                raw_list = [
                    [[bo[0]], [bo[0], bo[1]], [bo[1], bo[2]], [bo[2], bo[0]]],
                    [[bo[0], bo[1]], [bo[1]], [bo[1], bo[2]], [bo[2], bo[0]]],
                    [[bo[0], bo[1]], [bo[1], bo[2]], [bo[2]], [bo[2], bo[0]]],
                    [[bo[0], bo[1]], [bo[1], bo[2]], [bo[2], bo[0]], [bo[0]]],
                ]
            else:
                for i in range(k):
                    for j in range(i + 1, k):
                        for l in range(j + 1, k):
                            for m in range(l + 1, k):
                                raw_list.append([bo[i:j + 1], bo[j:l + 1],
                                                 bo[l:m + 1], bo[m:] + bo[:i + 1]])
                    _check_deadline(deadline)
            if not raw_list:
                return []

    # Convert internal 0-indexed vertices back to user IDs.
    def to_ids(arc):
        out = []
        for v in arc:
            if 0 <= v < n:
                nid = node_ids[v]
                if nid not in out:
                    out.append(nid)
        return out

    raw_bdys = []
    seen_raw = set()
    for b in (
        [[to_ids(arc) for arc in bb] for bb in raw_list]
    ):
        key = str(b)
        if key not in seen_raw:
            seen_raw.add(key)
            raw_bdys.append(b)

    def orbit(b):
        """Full dihedral orbit: 4 rotations of b and 4 of its reflection."""
        out = [b]
        cur = b
        for _ in range(3):
            cur = [cur[1], cur[2], cur[3], cur[0]]
            out.append(cur)
        for rot in range(4):
            rb = b
            for _ in range(rot):
                rb = [rb[1], rb[2], rb[3], rb[0]]
            out.append([list(reversed(rb[3])), list(reversed(rb[2])),
                        list(reversed(rb[1])), list(reversed(rb[0]))])
        return out

    pins = list(cardinal_pairs or [])
    if pins:
        # Best pin score anywhere in the orbit decides which raw boundaries
        # survive the cap; stable sort keeps the enumeration order among ties.
        raw_bdys.sort(key=lambda b: -max(
            _cardinal_boundary_score(m, pins) for m in orbit(b)))

    raw_total = len(raw_bdys)
    truncated = max_boundaries is not None and 0 < max_boundaries < raw_total
    if truncated:
        raw_bdys = raw_bdys[:max_boundaries]

    bdys = []
    seen = set()
    for b in raw_bdys:
        for m in orbit(b):
            key = str(m)
            if key not in seen:
                seen.add(key)
                bdys.append(m)

    if stats is not None:
        stats["raw_total"] = raw_total
        stats["raw_kept"] = len(raw_bdys)
        stats["truncated"] = bool(truncated)
    return bdys


# =============================================================================
# STEPS 2-5: THE PDF ALGORITHM
# =============================================================================

def _corners(N, E, S, W):
    """STEP 1: extract the 4 corners from the boundary arcs (CW order N-E-S-W)."""
    BL = S[-1] if S else (W[0] if W else None)
    BR = E[-1] if E else (S[0] if S else None)
    TR = N[-1] if N else (E[0] if E else None)
    TL = W[-1] if W else (N[0] if N else None)
    return BL, BR, TR, TL


def _boundary_cycle(N, E, S, W):
    """Ordered outer boundary cycle, no duplicates."""
    cycle = []
    seen = set()
    for arc in [N, E, S, W]:
        for v in arc:
            if v not in seen:
                cycle.append(v)
                seen.add(v)
    return cycle


def _shortcut_edges(adj, cycle):
    """STEP 1 (shortcuts): boundary-to-boundary edges that skip the cycle."""
    m = len(cycle)
    bdy_edges = {frozenset((cycle[i], cycle[(i + 1) % m])) for i in range(m)}
    bdy_set = set(cycle)
    cuts = []
    seen = set()
    for u in cycle:
        for v in adj.get(u, set()):
            key = frozenset((u, v))
            if v in bdy_set and key not in bdy_edges and key not in seen:
                cuts.append((u, v))
                seen.add(key)
    return cuts


def _init_tables(N, E, S, W, rw, rh, nid_set):
    """STEP 2: initialise the height table H and width table Wt from the arcs."""
    H = {}
    Wt = {}

    # 1. West wall (bottom to top)
    cur_y = 0
    for r in W:
        if r in nid_set and r not in H:
            cur_y += rh.get(r, 0)
            H[r] = cur_y
            Wt[r] = rw.get(r, 0)

    # 2. North wall (left to right)
    cur_x = Wt.get(W[-1], 0) if W and W[-1] in Wt else 0
    top_y = H.get(W[-1], 0) if W and W[-1] in H else 0
    for r in N:
        if r in nid_set and r not in H:
            cur_x += rw.get(r, 0)
            Wt[r] = cur_x
            H[r] = top_y

    # 3. East wall (top to bottom)
    cur_x = Wt.get(N[-1], 0) if N and N[-1] in Wt else 0
    tr_room = N[-1] if N else None
    cur_y = (H.get(tr_room, 0) - rh.get(tr_room, 0)) if tr_room in H else 0
    for r in E:
        if r in nid_set and r not in H:
            Wt[r] = cur_x
            H[r] = cur_y
            cur_y -= rh.get(r, 0)

    # 4. South wall (right to left)
    br_room = E[-1] if E else None
    cur_x = (Wt.get(br_room, 0) - rw.get(br_room, 0)) if br_room in Wt else 0
    bot_y = (H.get(br_room, 0) - rh.get(br_room, 0)) if br_room in H else 0
    if bot_y < 0:
        bot_y = 0
    for r in S:
        if r in nid_set and r not in H:
            H[r] = bot_y + rh.get(r, 0)
            Wt[r] = cur_x
            cur_x -= rw.get(r, 0)

    total_W = max(Wt.values()) if Wt else 1
    total_H = max(H.values()) if H else 1
    return H, Wt, total_W, total_H


def _init_interior(node_ids, adj, H, Wt, rw, rh):
    """Propagate H/Wt into interior rooms until the constraint system converges."""
    for _ in range(len(node_ids) + 2):
        changed = False
        for v in node_ids:
            nbs_H = [nb for nb in adj.get(v, set()) if H.get(nb, 0) > 0]
            if nbs_H:
                cand = min(H[nb] + rh.get(v, 0) for nb in nbs_H)
                if H.get(v, 0) == 0 or cand < H.get(v, 0):
                    H[v] = cand
                    changed = True
            nbs_W = [nb for nb in adj.get(v, set()) if Wt.get(nb, 0) > 0]
            if nbs_W:
                cand = min(Wt[nb] + rw.get(v, 0) for nb in nbs_W)
                if Wt.get(v, 0) == 0 or cand < Wt.get(v, 0):
                    Wt[v] = cand
                    changed = True
        if not changed:
            break


def _build_gprime(node_ids, edges, H, rh):
    """STEP 3: green/red labels for edges whose endpoints already sit on the boundary."""
    labels = {}
    for u, v in edges:
        key = frozenset((u, v))
        hu = H.get(u, 0)
        hv = H.get(v, 0)
        if hu == 0 or hv == 0:
            labels[key] = None      # interior room - labelled during placement
        elif hu - rh.get(u, 0) == hv - rh.get(v, 0):
            labels[key] = 'green'
        else:
            labels[key] = 'red'
    return labels


def _find_new_BL(cycle, placed, prev_BL, orig_corners):
    """STEP 4f: first unplaced node clockwise from the previous BL."""
    if not cycle:
        return None
    unplaced_cycle = [v for v in cycle if v not in placed]
    if not unplaced_cycle:
        return None
    try:
        idx = cycle.index(prev_BL)
        for i in range(1, len(cycle) + 1):
            v = cycle[(idx + i) % len(cycle)]
            if v not in placed:
                return v
    except ValueError:
        pass
    return unplaced_cycle[0]


def compact_and_resolve_overlaps(room_rects, edges, plot_w=-1, plot_h=-1,
                                 relaxed=False):
    """Push rooms apart, then pull adjacent rooms together to close gaps."""
    rects = {nid: list(rect) for nid, rect in room_rects.items()}

    def check_overlap(id1, id2):
        x1, y1, w1, h1 = rects[id1]
        x2, y2, w2, h2 = rects[id2]
        return not (x1 + w1 <= x2 or x1 >= x2 + w2 or y1 + h1 <= y2 or y1 >= y2 + h2)

    def push_chain(mover_id, dx, dy, visited):
        rects[mover_id][0] += dx
        rects[mover_id][1] += dy
        x, y, w, h = rects[mover_id]
        if x < 0 or y < 0:
            return False
        for oid in rects:
            if oid != mover_id and oid not in visited and check_overlap(mover_id, oid):
                visited.add(oid)
                if not push_chain(oid, dx, dy, visited):
                    return False
        return True

    def get_system_energy():
        e = 0
        for u, v in edges:
            if u in rects and v in rects:
                x1, y1, w1, h1 = rects[u]
                x2, y2, w2, h2 = rects[v]
                gap_x = max(0, max(x2 - (x1 + w1), x1 - (x2 + w2)))
                gap_y = max(0, max(y2 - (y1 + h1), y1 - (y2 + h2)))
                e += (gap_x ** 2 + gap_y ** 2) * 1000
                if gap_x == 0:
                    e += abs(y1 - y2) + abs((y1 + h1) - (y2 + h2))
                if gap_y == 0:
                    e += abs(x1 - x2) + abs((x1 + w1) - (x2 + w2))
        for nid, (x, y, w, h) in rects.items():
            e += (x + y) * 0.01
        return e

    # PHASE 1: cascade push - separate every overlapping pair.
    for _ in range(500):
        overlaps = False
        for id1 in rects:
            for id2 in rects:
                if id1 < id2 and check_overlap(id1, id2):
                    overlaps = True
                    x1, y1, w1, h1 = rects[id1]
                    x2, y2, w2, h2 = rects[id2]
                    sx = (x1 + w1) - x2 if x1 < x2 else (x2 + w2) - x1
                    sy = (y1 + h1) - y2 if y1 < y2 else (y2 + h2) - y1
                    if sx < sy:
                        if x1 < x2:
                            rects[id2][0] += sx
                        else:
                            rects[id1][0] += sx
                    else:
                        if y1 < y2:
                            rects[id2][1] += sy
                        else:
                            rects[id1][1] += sy
        if not overlaps:
            break

    # PHASE 2: chain gravity - hill-climb toward zero gap between adjacent rooms.
    magnet_changed = True
    iters = 0
    current_e = get_system_energy()
    while magnet_changed and iters < 1000:
        magnet_changed = False
        iters += 1
        if current_e == 0:
            break
        for nid in rects:
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                state_backup = {k: list(v) for k, v in rects.items()}
                if push_chain(nid, dx, dy, {nid}):
                    new_e = get_system_energy()
                    if new_e < current_e:
                        current_e = new_e
                        magnet_changed = True
                        break
                rects.clear()
                rects.update(state_backup)

    # PHASE 3: bounded relaxation - clamp into the plot, split residual overlaps.
    if relaxed:
        for _ in range(300):
            moved = False
            if plot_w > 0 or plot_h > 0:
                for nid in rects:
                    x, y, w, h = rects[nid]
                    new_x = max(0.0, min(x, float(plot_w) - w)) if plot_w > 0 else x
                    new_y = max(0.0, min(y, float(plot_h) - h)) if plot_h > 0 else y
                    if new_x != x or new_y != y:
                        rects[nid][0] = new_x
                        rects[nid][1] = new_y
                        moved = True
            for id1 in rects:
                for id2 in rects:
                    if id1 < id2 and check_overlap(id1, id2):
                        moved = True
                        x1, y1, w1, h1 = rects[id1]
                        x2, y2, w2, h2 = rects[id2]
                        sx = (x1 + w1) - x2 if x1 < x2 else (x2 + w2) - x1
                        sy = (y1 + h1) - y2 if y1 < y2 else (y2 + h2) - y1
                        if sx < sy:
                            if x1 < x2:
                                rects[id1][0] -= sx / 2
                                rects[id2][0] += sx / 2
                            else:
                                rects[id2][0] -= sx / 2
                                rects[id1][0] += sx / 2
                        else:
                            if y1 < y2:
                                rects[id1][1] -= sy / 2
                                rects[id2][1] += sy / 2
                            else:
                                rects[id2][1] -= sy / 2
                                rects[id1][1] += sy / 2
            if not moved:
                break

    for nid in rects:
        room_rects[nid] = (float(rects[nid][0]), float(rects[nid][1]),
                           float(rects[nid][2]), float(rects[nid][3]))
    return room_rects


def _place_block(M, h_m, w_m, mh, mw):
    """STEP 4d: claim the cells for one room, shifting right past collisions."""
    offset_c = 0
    while True:
        collision = False
        for r in range(h_m - mh + 1, h_m + 1):
            for c in range(w_m - mw + 1 + offset_c, w_m + 1 + offset_c):
                if r > 0 and c > 0 and M.get((r, c)) is not None:
                    collision = True
                    break
            if collision:
                break
        if not collision:
            break
        offset_c += 1
    return offset_c


def _pdf_place(node_ids, edges, rw, rh, boundary, plot_w=-1, plot_h=-1,
               relaxed=False, require_all_adjacencies=True):
    """Core PDF algorithm for one boundary. Returns (rects, matrix, labels) or None.

    ``relaxed`` lets the compactor leave gaps and tolerates walls the graph does
    not ask for. ``require_all_adjacencies=False`` additionally keeps layouts
    that drop some requested adjacency - only useful in best-effort mode, where
    the caller ranks what comes back by adjacency score.
    """
    nid_set = set(node_ids)
    N, E, S, W = ([v for v in arc if v in nid_set] for arc in boundary)

    adj = {v: set() for v in node_ids}
    for u, v in edges:
        if u in adj and v in adj:
            adj[u].add(v)
            adj[v].add(u)

    # STEP 1: corners and shortcuts
    BL, BR, TR, TL = _corners(N, E, S, W)
    if BL is None:
        return None
    cycle = _boundary_cycle(N, E, S, W)
    shortcuts = _shortcut_edges(adj, cycle)
    orig_corners = (BL, BR, TR, TL)

    # STEP 2: init tables from the boundary arcs
    try:
        H, Wt, total_W, total_H = _init_tables(N, E, S, W, rw, rh, nid_set)
    except Exception:
        return None
    if total_W <= 0 or total_H <= 0:
        return None

    _init_interior(node_ids, adj, H, Wt, rw, rh)

    # STEP 3: build G' with initial edge labels
    edge_labels = _build_gprime(node_ids, edges, H, rh)

    M = {}
    placed = set()
    cur_BL = BL
    # Rooms whose H/Wt came from _init_interior are already correct; step 4e
    # must label their edges rather than overwrite their tables.
    initialised = set(H.keys()) | set(Wt.keys())
    corners_order = [c for c in [BL, BR, TR, TL] if c is not None]

    def commit(m, h_m, w_m):
        """Place m, then propagate tables and labels to its unplaced neighbours."""
        mh = rh.get(m, 0)
        mw = rw.get(m, 0)
        offset_c = _place_block(M, h_m, w_m, mh, mw)
        for r in range(h_m - mh + 1, h_m + 1):
            for c in range(w_m - mw + 1 + offset_c, w_m + 1 + offset_c):
                if r > 0 and c > 0:
                    M[(r, c)] = m

        for u in adj.get(m, set()):
            if u in placed or u not in nid_set:
                continue
            key = frozenset((m, u))
            if u not in initialised:
                if H.get(u, 0) < h_m:
                    H[u] = h_m
                    edge_labels[key] = 'green'
                else:
                    edge_labels[key] = 'red'
                if Wt.get(u, 0) < w_m:
                    Wt[u] = w_m
            else:
                h_u = H.get(u, 0)
                if h_u == 0 or h_m - rh.get(m, 0) == h_u - rh.get(u, 0):
                    edge_labels[key] = 'green'
                else:
                    edge_labels[key] = 'red'
        placed.add(m)

    # STEP 4: placement loop
    for _ in range(len(node_ids) * (len(node_ids) + 4)):
        if len(placed) == len(node_ids):
            break

        placed_one = False

        # 4a: try each corner, BL first
        for corner in corners_order:
            if corner is None or corner in placed:
                continue
            if H.get(corner, 0) == 0 or Wt.get(corner, 0) == 0:
                continue

            m = None
            # 4b/4c: corner adjacent to a shortcut endpoint -> place the triplet's
            # third room instead of the corner itself
            for (su, sv) in shortcuts:
                partner = None
                if su in adj.get(corner, set()):
                    partner = su
                elif sv in adj.get(corner, set()):
                    partner = sv
                elif corner == su:
                    partner = sv
                elif corner == sv:
                    partner = su
                if partner is None:
                    continue
                common = sorted((adj.get(corner, set()) & adj.get(partner, set())) - placed)
                common = [v for v in common if v in nid_set]
                if common:
                    m = common[0]
                    break

            if m is None:
                m = corner

            commit(m, H[m], Wt[m])

            # 4f: shrink the cycle, recompute shortcuts, rotate the corner order
            cycle = [v for v in cycle if v != m]
            shortcuts = _shortcut_edges(adj, cycle)
            cur_BL = _find_new_BL(cycle, placed, corner, orig_corners)
            remaining = [v for v in [BL, BR, TR, TL] if v is not None and v not in placed]
            if cur_BL and cur_BL in remaining:
                idx = remaining.index(cur_BL)
                corners_order = remaining[idx:] + remaining[:idx]
            else:
                corners_order = remaining

            placed_one = True
            break

        if placed_one:
            continue

        # Fallback: no usable corner - place the lowest-left routable room.
        candidates = [(H.get(v, 0), Wt.get(v, 0), rw.get(v, 0), v)
                      for v in node_ids
                      if v not in placed and H.get(v, 0) > 0 and Wt.get(v, 0) > 0]
        if not candidates:
            return None     # boundary is infeasible
        candidates.sort()
        _, _, _, m = candidates[0]

        commit(m, H[m], Wt[m])

        cycle = [v for v in cycle if v != m]
        shortcuts = _shortcut_edges(adj, cycle)
        cur_BL = _find_new_BL(cycle, placed, m, orig_corners)
        remaining = [v for v in [BL, BR, TR, TL] if v is not None and v not in placed]
        if cur_BL and cur_BL in remaining:
            idx = remaining.index(cur_BL)
            corners_order = remaining[idx:] + remaining[:idx]
        else:
            corners_order = remaining

    if len(placed) < len(node_ids):
        return None

    # STEP 5: pixel coordinates
    raw_rects = {}
    for v in node_ids:
        if H.get(v, 0) == 0 or Wt.get(v, 0) == 0:
            return None     # room never got routed
        raw_rects[v] = (Wt[v] - rw.get(v, 0), H[v] - rh.get(v, 0), rw[v], rh[v])

    min_x_raw = min(r[0] for r in raw_rects.values())
    min_y_raw = min(r[1] for r in raw_rects.values())
    room_rects = {v: (float(x - min_x_raw), float(y - min_y_raw), float(w), float(h))
                  for v, (x, y, w, h) in raw_rects.items()}

    room_rects = compact_and_resolve_overlaps(room_rects, edges, plot_w, plot_h,
                                              relaxed=relaxed)

    min_x = min(x for x, y, w, h in room_rects.values())
    min_y = min(y for x, y, w, h in room_rects.values())
    max_x = max(x + w for x, y, w, h in room_rects.values())
    max_y = max(y + h for x, y, w, h in room_rects.values())
    actual_tw = int(max_x - min_x)
    actual_th = int(max_y - min_y)

    if (plot_w > 0 and actual_tw > plot_w) or (plot_h > 0 and actual_th > plot_h):
        return None
    if actual_tw <= 0 or actual_th <= 0:
        return None

    for v, (x, y, w, h) in room_rects.items():
        room_rects[v] = (x - min_x, y - min_y, w, h)

    Mnp = np.full((actual_th, actual_tw), -1, dtype=int)
    for j, v in enumerate(node_ids):
        x0, y0 = int(room_rects[v][0]), int(room_rects[v][1])
        w_val, h_val = int(room_rects[v][2]), int(room_rects[v][3])
        for r in range(h_val):
            for c in range(w_val):
                if 0 <= y0 + r < actual_th and 0 <= x0 + c < actual_tw:
                    Mnp[y0 + r][x0 + c] = j

    # Adjacency firewall: a compact plan must realise the graph exactly; a
    # relaxed plan may leave gaps but still may not drop a required adjacency.
    actual_edges = _matrix_adjacencies(Mnp, node_ids)
    required_edges = {tuple(sorted((str(u), str(v)))) for u, v in edges}
    if require_all_adjacencies and not required_edges.issubset(actual_edges):
        return None
    if not relaxed and not actual_edges.issubset(required_edges):
        return None

    return room_rects, np.flipud(Mnp), edge_labels


# =============================================================================
# ENTRY POINT
# =============================================================================

STRICTNESS_LEVELS = ("exact", "relaxed", "best_effort")


def generate_floorplans(node_ids, edges, room_widths, room_heights,
                        node_positions=None, plot_w=-1, plot_h=-1, limit=100,
                        already_ptpg=False, max_boundaries=DEFAULT_MAX_BOUNDARIES,
                        deadline=None, strictness="relaxed", cardinal_pairs=None,
                        stats=None):
    """Dimensioned floorplans for one graph and one set of exact room sizes.

    Passes are tried in order and the first one that produces anything wins:

    * ``exact``       - compact only: no gaps, every requested adjacency
                        realised, no wall the graph did not ask for.
    * ``relaxed``     - adds a pass that tolerates gaps and extra walls but
                        still realises every requested adjacency. This is what
                        the ``ptpg_floorplanner`` branch does.
    * ``best_effort`` - adds a final pass that also accepts layouts missing some
                        adjacencies, keeping only the best-scoring ones. Use it
                        when exact room sizes admit no true rectangular dual.

    Room sizes are exact, never minimums; that is the premise of this algorithm.

    ``cardinal_pairs`` is an optional list of ``(node_id, dir_idx)`` N/E/S/W
    pins (``dir_idx`` 0..3, as :func:`GPLAN.api.normalize_cardinal_constraints`
    produces). Every returned layout satisfies all of them; the gate runs
    INSIDE the candidate loop so ``limit`` counts satisfying layouts rather than
    filling up with violating ones that a caller-side filter would then throw
    away. An empty result therefore means "this graph cannot honour these pins",
    which is the caller's cue to relax, not a silent drop.
    """
    if not node_ids:
        return []
    if strictness not in STRICTNESS_LEVELS:
        raise ValueError(f"strictness must be one of {STRICTNESS_LEVELS}")
    plain = [(e[0], e[1]) for e in edges]
    rw = {nid: int(room_widths[nid]) for nid in node_ids}
    rh = {nid: int(room_heights[nid]) for nid in node_ids}
    nid_set = set(node_ids)
    pins = [(n, d) for n, d in (cardinal_pairs or []) if n in nid_set]

    try:
        boundaries = get_boundaries(node_ids, plain, node_positions,
                                    already_ptpg=already_ptpg,
                                    max_boundaries=max_boundaries,
                                    deadline=deadline,
                                    cardinal_pairs=pins, stats=stats)
    except DeadlineExceeded:
        raise
    except Exception:
        return []

    boundaries = order_boundaries_by_cardinal(boundaries, pins)

    def run_pass(is_relaxed, require_all=True):
        res_list = []
        seen_keys = set()
        for boundary in boundaries:
            if len(res_list) >= limit:
                break
            _check_deadline(deadline)
            try:
                result = _pdf_place(node_ids, plain, rw, rh, boundary,
                                    plot_w, plot_h, relaxed=is_relaxed,
                                    require_all_adjacencies=require_all)
                if result is None:
                    continue
                room_rects, M, el = result
                if pins and not plan_satisfies_cardinal(room_rects, pins):
                    continue
                key = str(M.tolist())
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                res_list.append(FloorplanResult(
                    boundary=[list(arc) for arc in boundary],
                    encoded_matrix=M,
                    room_rects=room_rects,
                    node_ids=node_ids,
                    edge_labels=el,
                    is_relaxed=is_relaxed,
                ))
            except DeadlineExceeded:
                raise
            except Exception:
                continue

        # Topological failsafe for hub graphs (W_7 and friends): seed rooms from
        # the drawing positions and let the compactor sort them out.
        if not res_list and is_relaxed and node_positions and (plot_w > 0 or plot_h > 0):
            try:
                xs = [p[0] for p in node_positions.values()]
                ys = [p[1] for p in node_positions.values()]
                min_pos_x, min_pos_y = min(xs), min(ys)
                room_rects = {}
                for nid in node_ids:
                    px, py = node_positions[nid]
                    room_rects[nid] = (float((px - min_pos_x) * 0.5),
                                       float((py - min_pos_y) * 0.5),
                                       float(rw[nid]), float(rh[nid]))
                room_rects = compact_and_resolve_overlaps(room_rects, plain,
                                                          plot_w, plot_h, relaxed=True)
                min_x = min(x for x, y, w, h in room_rects.values())
                min_y = min(y for x, y, w, h in room_rects.values())
                max_x = max(x + w for x, y, w, h in room_rects.values())
                max_y = max(y + h for x, y, w, h in room_rects.values())
                actual_tw = max(1, int(max_x - min_x))
                actual_th = max(1, int(max_y - min_y))
                # The failsafe only runs when a plot was given, so it has to
                # honour it: the compactor packs rooms without any notion of the
                # plot, and dropping this check let impossible plots come back
                # with a layout that overflows them.
                if (plot_w > 0 and actual_tw > plot_w) or (plot_h > 0 and actual_th > plot_h):
                    return res_list
                for v, (x, y, w, h) in room_rects.items():
                    room_rects[v] = (x - min_x, y - min_y, w, h)
                # The failsafe ignores boundary arcs entirely, so it is exactly
                # the path most likely to violate a pin. Gate it like the rest.
                if pins and not plan_satisfies_cardinal(room_rects, pins):
                    return res_list

                Mnp = np.full((actual_th, actual_tw), -1, dtype=int)
                for j, v in enumerate(node_ids):
                    x0, y0 = int(room_rects[v][0]), int(room_rects[v][1])
                    w_val, h_val = int(room_rects[v][2]), int(room_rects[v][3])
                    for r in range(h_val):
                        for c in range(w_val):
                            if 0 <= y0 + r < actual_th and 0 <= x0 + c < actual_tw:
                                Mnp[y0 + r][x0 + c] = j

                bdy_fallback = boundaries[0] if boundaries else [[node_ids[0]], [], [], []]
                res_list.append(FloorplanResult(
                    boundary=[list(arc) for arc in bdy_fallback],
                    encoded_matrix=np.flipud(Mnp),
                    room_rects=room_rects,
                    node_ids=node_ids,
                    edge_labels={frozenset((u, v)): 'red' for u, v in plain},
                    is_relaxed=True,
                ))
            except DeadlineExceeded:
                raise
            except Exception:
                pass

        return res_list

    required = {tuple(sorted((str(u), str(v)))) for u, v in plain}

    def adj_score(r):
        actual = _matrix_adjacencies(r.encoded_matrix, r.node_ids)
        return -(len(required - actual) + len(actual - required))

    def keep_best(res_list):
        if not res_list:
            return res_list
        best = max(adj_score(r) for r in res_list)
        return [r for r in res_list if adj_score(r) == best]

    results = run_pass(is_relaxed=False)

    if not results and strictness in ("relaxed", "best_effort"):
        results = keep_best(run_pass(is_relaxed=True))

    if not results and strictness == "best_effort":
        results = keep_best(run_pass(is_relaxed=True, require_all=False))

    results.sort(key=lambda r: r.total_size()[0] * r.total_size()[1])
    return results
