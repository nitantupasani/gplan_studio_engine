"""API

Generates floorplamns for given graph data as input.
Current support only for rectangular floorplans.
A running example is available.

"""
from GPLAN.source.inputgraph import InputGraph
import GPLAN.pythongui.gui as gui
import math
import uuid

from GPLAN.handlers import *
from GPLAN.pythongui.GuiParameters import GuiParameters, DimParameters
import builtins

# Import boundary utilities from Space_Optimization folder
import sys
import os
space_opt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Space_Optimization')
if space_opt_path not in sys.path:
    sys.path.insert(0, space_opt_path)
from boundary_utils import boundary_to_regions as convert_boundary_to_regions


def boundary_to_regions(boundary, fixed_rooms=None):
    """
    Convert a polygonal boundary to a list of rectangular regions.
    
    Uses the same algorithm as the UI's CAD tool (decompose_into_rectangles).
    Creates a grid-based decomposition with cell merging for optimal region count.
    
    Args:
        boundary: List of [x, y] coordinate pairs defining the polygon vertices
        fixed_rooms: Optional list of fixed room polygons to exclude during decomposition
        
    Returns:
        List of region dictionaries with x, y, width, height
        
    Example:
        boundary = [[0, 0], [10, 0], [10, 5], [5, 5], [5, 10], [0, 10]]
        regions = boundary_to_regions(boundary)
        # Returns L-shape as merged rectangles
    """
    if not boundary or len(boundary) < 3:
        raise ValueError("Boundary must have at least 3 points")
    
    # Use the shared utility function (same as UI)
    return convert_boundary_to_regions(boundary, fixed_rooms=fixed_rooms)


class Asset:
    def __init__(self, _id, properties, asset_type):
        self._id = _id
        self.properties = properties
        self.type = asset_type

    def to_dict(self):
        return {
            "_id": self._id,
            "properties": self.properties,
            "type": self.type
        }


class Wall:
    def __init__(self, _id, x1, y1, x2, y2, assets=None):
        self._id = _id
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.assets = []
        if assets is not None:
            self.assets = [asset.to_dict() for asset in assets]

    def to_dict(self):
        return {
            "_id": self._id,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "assets": self.assets
        }


class Room:
    def __init__(self, _id, name, color, walls=None, assets=None, circular_coordinates=None,name_coord=None,area = None,width = None,height = None):
        self._id = _id
        self.name = name
        self.name_coord = name_coord
        self.area = area
        self.width = width
        self.height = height
        self.assets = []
        if assets is not None:
            self.assets = [asset.to_dict() for asset in assets]
        self.color = color
        if walls is not None:
            self.walls = [wall.to_dict() for wall in walls]
        self.circular_coordinates = circular_coordinates

    def to_dict(self):
        return {
            "_id": self._id,
            "name": self.name,
            "label_coord": self.name_coord,
            "area" : self.area,
            "width" : self.width,
            "height" : self.height,
            "assets": self.assets,
            "color": self.color,
            "walls": self.walls,
            "circular_coordinates": self.circular_coordinates
        }


FLOORPLAN_LIMIT = 30

# Cardinal directions map to boundary-path indices in the 4-completion
# (news.add_news order): N -> paths[0], E -> paths[1], S -> paths[2], W -> paths[3].
CARDINAL_DIR_INDEX = {"N": 0, "E": 1, "S": 2, "W": 3}


def normalize_cardinal_constraints(cardinal_constraints, nodecnt):
    """Normalizes user cardinal constraints into engine (node, dir_idx) pairs.

    Accepts entries either as {"room": <node id>, "direction": "N"|"E"|"S"|"W"}
    or as [node, "N"] pairs. Invalid rooms/directions are dropped.
    """
    pairs = []
    for entry in cardinal_constraints or []:
        if isinstance(entry, dict):
            room = entry.get("room")
            direction = entry.get("direction")
        else:
            try:
                room, direction = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
        if not isinstance(room, int) or room < 0 or room >= nodecnt:
            continue
        dir_idx = CARDINAL_DIR_INDEX.get(str(direction).upper()[:1])
        if dir_idx is None:
            continue
        pair = (room, dir_idx)
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def _ring_order_satisfies(order, pins):
    """True when the cyclic node order admits a 4-arc split (N,E,S,W, up to
    rotation and reflection) with every pinned node inside its direction's arc
    and every two-direction (corner) pin exactly at its two arcs' interface.

    This mirrors what filter_boundaries_by_cardinal can accept downstream:
    boundary paths are contiguous arcs of the outer cycle in N,E,S,W order
    (any rotation, either orientation), sharing only corner nodes.
    """
    if not pins:
        return True
    for seq in (order, list(reversed(order))):
        dirsets = [pins[n] for n in seq if n in pins]
        cnt = len(dirsets)
        for r in range(cnt):
            base = None
            prog = 0
            ok = True
            for ds in (dirsets[r:] + dirsets[:r]):
                if len(ds) == 1:
                    d = next(iter(ds))
                    if base is None:
                        base = d
                        continue
                    delta = (d - base) % 4
                    if delta < prog:
                        ok = False
                        break
                    prog = delta
                else:
                    d1, d2 = tuple(ds)
                    if (d2 - d1) % 4 != 1:
                        d1, d2 = d2, d1
                    if base is None:
                        base = d1
                        prog = 1
                        continue
                    delta1 = (d1 - base) % 4
                    delta2 = (d2 - base) % 4
                    if delta1 < prog or delta2 != delta1 + 1:
                        ok = False
                        break
                    prog = delta2
            if ok:
                return True
    return False


def build_cardinal_ring(nodecnt, edges_list, cardinal_pairs):
    """Planar outer-ring augmentation making every cardinal pin boundary-capable.

    A generated floorplan's boundary is the outer face of the planar embedding
    chosen during augmentation. For sparse inputs (the designer's normal case)
    that embedding otherwise comes from nx.planar_layout, which knows nothing
    about the pins - a pinned room can end up interior in EVERY enumerated
    boundary, starving the cardinal filter and forcing the relaxation ladder
    to "ignored" no matter what.

    Builds a Hamiltonian cycle through all rooms - components and subtrees
    ordered so pinned rooms sit contiguously per direction in N,E,S,W cyclic
    order - plus circle coordinates realizing it as a planar straight-line
    drawing (tree edges become non-crossing chords when the cycle follows DFS
    preorder). With the cycle added the graph is biconnected, so the engine
    skips its own augmentation and keeps this embedding: the outer boundary IS
    the ring and the boundary filter can always aim it.

    Returns (ring_edges, coordinates) or None when no valid ring exists
    (opposite-direction pins, ordering conflict, or crossing chords).
    """
    if nodecnt < 3:
        return None
    pins = {}
    for node, dir_idx in cardinal_pairs:
        pins.setdefault(node, set()).add(dir_idx)
    for dirs in pins.values():
        if len(dirs) > 2:
            return None
        if len(dirs) == 2:
            d1, d2 = tuple(dirs)
            if (d2 - d1) % 4 == 2:  # opposite sides can never share a corner
                return None
    adjset = {i: set() for i in range(nodecnt)}
    for edge in edges_list:
        a, b = edge[0], edge[1]
        if a != b:
            adjset[a].add(b)
            adjset[b].add(a)

    # Components, each ordered by DFS preorder (subtrees stay contiguous, so
    # tree edges never cross the circle chords). Children are visited in
    # ascending order of the smallest pin direction in their subtree, which
    # groups same-direction pins together in N,E,S,W order.
    def preorder_from(root, comp_nodes):
        children = {n: [] for n in comp_nodes}
        parent = {root: None}
        stack = [root]
        seen_local = {root}
        dfs_order = []
        while stack:
            cur = stack.pop()
            dfs_order.append(cur)
            for nbr in sorted(adjset[cur]):
                if nbr in comp_nodes and nbr not in seen_local:
                    seen_local.add(nbr)
                    parent[nbr] = cur
                    children[cur].append(nbr)
                    stack.append(nbr)
        subkey = {n: min(pins[n]) if n in pins else 4 for n in comp_nodes}
        for n in reversed(dfs_order):
            for ch in children[n]:
                subkey[n] = min(subkey[n], subkey[ch])
        out = []
        stack = [root]
        while stack:
            cur = stack.pop()
            out.append(cur)
            for ch in sorted(children[cur], key=lambda c: (subkey[c], c),
                             reverse=True):
                stack.append(ch)
        return out

    seen = set()
    comps = []
    for start in range(nodecnt):
        if start in seen:
            continue
        comp = set()
        stack = [start]
        seen.add(start)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for nbr in adjset[cur]:
                if nbr not in seen:
                    seen.add(nbr)
                    stack.append(nbr)
        comps.append(comp)

    def comp_key(comp):
        keys = [min(pins[n]) for n in comp if n in pins]
        return (min(keys) if keys else 4, min(comp))

    comps.sort(key=comp_key)
    # Per component try every root (components are small); take the first
    # combination whose full cyclic order verifies.
    comp_orders = []
    for comp in comps:
        roots = sorted(comp, key=lambda n: (min(pins[n]) if n in pins else 4, n))
        comp_orders.append([preorder_from(r, comp) for r in roots])

    def crossing_free(order):
        posidx = {n: i for i, n in enumerate(order)}
        chords = []
        for edge in edges_list:
            a, b = posidx[edge[0]], posidx[edge[1]]
            lo, hi = min(a, b), max(a, b)
            if hi - lo > 1 and not (lo == 0 and hi == len(order) - 1):
                chords.append((lo, hi))
        for i in range(len(chords)):
            for j in range(i + 1, len(chords)):
                a, b = chords[i]
                c, d = chords[j]
                if len({a, b, c, d}) == 4 and (a < c < b < d or c < a < d < b):
                    return False
        return True

    def combos(idx, prefix, budget):
        if budget[0] <= 0:
            return None
        if idx == len(comp_orders):
            budget[0] -= 1
            if _ring_order_satisfies(prefix, pins) and crossing_free(prefix):
                return list(prefix)
            return None
        for cand in comp_orders[idx]:
            found = combos(idx + 1, prefix + cand, budget)
            if found is not None:
                return found
        return None

    order = combos(0, [], [500])
    if order is None:
        return None
    ring_edges = []
    total = len(order)
    for i in range(total):
        a, b = order[i], order[(i + 1) % total]
        if b not in adjset[a]:
            ring_edges.append((a, b))
    coords = [None] * nodecnt
    for i, node in enumerate(order):
        ang = 2 * math.pi * i / total
        coords[node] = [0.5 + 0.4 * math.cos(ang), 0.5 + 0.4 * math.sin(ang)]
    return ring_edges, coords


def apply_cardinal_ring(graph, nodecnt, edges_list, cardinal_pairs,
                        non_adj_edge_list=None):
    """Adds the cardinal outer ring to graph (matrix + coordinates) in place.

    Ring edges are engine augmentation, not user adjacencies - they are added
    to the matrix only, so no doors are placed on them (ui edges stay the user
    list). Skipped (returns False) when pins are absent, non-adjacency
    constraints exist (a ring edge could force a forbidden adjacency), or no
    valid ring order was found.
    """
    if not cardinal_pairs or non_adj_edge_list:
        return False
    ring = build_cardinal_ring(nodecnt, edges_list, cardinal_pairs)
    if ring is None:
        return False
    ring_edges, coords = ring
    for a, b in ring_edges:
        if graph.matrix[a][b] != 1:
            graph.matrix[a][b] = 1
            graph.matrix[b][a] = 1
            graph.edgecnt += 1
    graph.coordinates = coords
    return True


def plan_satisfies_cardinal(plan_graph, cardinal_pairs):
    """True when every (node, dir_idx) pin is exterior-facing in the solved plan.

    Checks the geometry that is actually serialized to clients
    (final_traversal, rooms in node order): no other room's bounding box may
    intersect the strip between the pinned room's box and the plan bounds on
    the pinned side. Frame is y-down, dir_idx 0..3 = N,E,S,W (N = smaller y).
    """
    rooms = getattr(plan_graph, "final_traversal", None) or []
    if not rooms:
        return False
    rects = []
    for poly in rooms:
        xs = [pt[0] for pt in poly]
        ys = [pt[1] for pt in poly]
        if not xs:
            return False
        rects.append((min(xs), max(xs), min(ys), max(ys)))
    bx0 = min(r[0] for r in rects)
    bx1 = max(r[1] for r in rects)
    by0 = min(r[2] for r in rects)
    by1 = max(r[3] for r in rects)
    eps = max(bx1 - bx0, by1 - by0, 1e-6) * 1e-4
    for node, dir_idx in cardinal_pairs:
        if node >= len(rects):
            return False
        rx0, rx1, ry0, ry1 = rects[node]
        if dir_idx == 0:
            sx0, sx1, sy0, sy1 = rx0, rx1, by0, ry0
        elif dir_idx == 1:
            sx0, sx1, sy0, sy1 = rx1, bx1, ry0, ry1
        elif dir_idx == 2:
            sx0, sx1, sy0, sy1 = rx0, rx1, ry1, by1
        else:
            sx0, sx1, sy0, sy1 = bx0, rx0, ry0, ry1
        for j, (ox0, ox1, oy0, oy1) in enumerate(rects):
            if j == node:
                continue
            if (min(ox1, sx1) - max(ox0, sx0) > eps and
                    min(oy1, sy1) - max(oy0, sy0) > eps):
                return False
    return True


def filter_output_by_cardinal(ui, cardinal_pairs):
    """Keeps only geometrically satisfying plans in ui's output data.

    Returns the surviving list. The boundary pre-filter aims candidates at the
    right sides, but later stages (dimension-fit selection, optimal-resize
    fallback) can still emit violating plans - this is the hard gate.
    """
    satisfying = [plan for plan in ui.get_output_data()
                  if plan_satisfies_cardinal(plan, cardinal_pairs)]
    ui._set_output_data(satisfying)
    return satisfying


def _polyline_rect(poly, eps):
    """(x0, y0, x1, y1) if the room polyline is an axis-aligned rectangle
    (shoelace area == bbox area), else None."""
    xs = [pt[0] for pt in poly]
    ys = [pt[1] for pt in poly]
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    area2 = 0.0
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i][0], poly[i][1]
        bx, by = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        area2 += ax * by - bx * ay
    if abs(abs(area2) / 2 - (x1 - x0) * (y1 - y0)) > eps:
        return None
    return (x0, y0, x1, y1)


def _fill_gaps(rects, eps):
    """Greedy wall extension: push each room's sides outward to the nearest
    obstruction (another room overlapping that side's span, else the plan
    bounds) until nothing moves. Rooms stay rectangles and never overlap;
    empty notches next to a full side get absorbed. Mutates and returns rects."""
    bx0 = min(r[0] for r in rects)
    by0 = min(r[1] for r in rects)
    bx1 = max(r[2] for r in rects)
    by1 = max(r[3] for r in rects)
    changed = True
    guard = 0
    while changed and guard < 200:
        changed = False
        guard += 1
        for i, (x0, y0, x1, y1) in enumerate(rects):
            # East
            obst = bx1
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if j != i and min(y1, b1) - max(y0, b0) > eps and a0 >= x1 - eps:
                    obst = min(obst, a0)
            if obst - x1 > eps:
                rects[i] = (x0, y0, obst, y1)
                changed = True
                x1 = obst
            # West
            obst = bx0
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if j != i and min(y1, b1) - max(y0, b0) > eps and a1 <= x0 + eps:
                    obst = max(obst, a1)
            if x0 - obst > eps:
                rects[i] = (obst, y0, x1, y1)
                changed = True
                x0 = obst
            # South (larger y)
            obst = by1
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if j != i and min(x1, a1) - max(x0, a0) > eps and b0 >= y1 - eps:
                    obst = min(obst, b0)
            if obst - y1 > eps:
                rects[i] = (x0, y0, x1, obst)
                changed = True
                y1 = obst
            # North (smaller y)
            obst = by0
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if j != i and min(x1, a1) - max(x0, a0) > eps and b1 <= y0 + eps:
                    obst = max(obst, b1)
            if y0 - obst > eps:
                rects[i] = (x0, obst, x1, y1)
                changed = True
                y0 = obst
    return rects


def _is_gapless(rects, eps):
    """Full-coverage test for non-overlapping axis-aligned rects: the union
    fills the bounding rectangle iff the areas sum to the bounds area."""
    bx0 = min(r[0] for r in rects)
    by0 = min(r[1] for r in rects)
    bx1 = max(r[2] for r in rects)
    by1 = max(r[3] for r in rects)
    bounds_area = (bx1 - bx0) * (by1 - by0)
    if bounds_area <= 0:
        return False
    total = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
    return abs(total - bounds_area) <= bounds_area * 1e-3


def rectangularize_output(ui):
    """Keeps only plans that are (or can be made) gapless rectangles.

    For each generated plan whose rooms are all rectangles: fill boundary
    notches/holes by greedy wall extension, then require full coverage of the
    bounding rectangle. Plans with merged (non-rectangular) rooms, overlapping
    rooms, or residual holes are dropped. Surviving plans get their geometry
    rewritten to the filled rectangles. Returns the surviving list.
    """
    kept = []
    for plan in ui.get_output_data():
        rooms = getattr(plan, "final_traversal", None) or []
        if not rooms:
            continue
        all_xs = [pt[0] for poly in rooms for pt in poly]
        all_ys = [pt[1] for poly in rooms for pt in poly]
        span = max(max(all_xs) - min(all_xs), max(all_ys) - min(all_ys), 1e-6)
        eps = span * 1e-4
        rects = []
        for poly in rooms:
            rect = _polyline_rect(poly, span * 1e-3)
            if rect is None:
                rects = None
                break
            rects.append(rect)
        if rects is None or _rects_overlap(rects, eps):
            continue
        _fill_gaps(rects, eps)
        if _rects_overlap(rects, eps) or not _is_gapless(rects, eps):
            continue
        plan.final_traversal = [
            [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            for (x0, y0, x1, y1) in rects
        ]
        plan.room_width = [r[2] - r[0] for r in rects]
        plan.room_height = [r[3] - r[1] for r in rects]
        plan.area = [(r[2] - r[0]) * (r[3] - r[1]) for r in rects]
        if hasattr(plan, "name_coords") and plan.name_coords:
            for k, (x0, y0, x1, y1) in enumerate(rects):
                if k < len(plan.name_coords):
                    plan.name_coords[k] = [(x0 + x1) / 2, (y0 + y1) / 2]
        kept.append(plan)
    ui._set_output_data(kept)
    return kept


def _stacked_room_dict(name, color, x0, y0, x1, y1):
    """Serialized Room dict for one axis-aligned rectangle."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    walls = []
    for i in range(4):
        ax, ay = corners[i]
        bx, by = corners[(i + 1) % 4]
        walls.append(Wall(str(uuid.uuid4()), ax, ay, bx, by))
    room = Room(str(uuid.uuid4()), name, color, walls,
                circular_coordinates=[list(c) for c in corners] + [[x0, y0]],
                name_coord=[(x0 + x1) / 2, (y0 + y1) / 2],
                area=(x1 - x0) * (y1 - y0), width=x1 - x0, height=y1 - y0)
    return room.to_dict()


def _plan_rects(plan):
    """name -> (x0, y0, x1, y1) bounding box for each room of a serialized plan."""
    rects = {}
    for room in plan:
        xs, ys = [], []
        for wall in room["walls"]:
            xs += [wall["x1"], wall["x2"]]
            ys += [wall["y1"], wall["y2"]]
        if xs:
            rects[room["name"]] = (min(xs), min(ys), max(xs), max(ys))
    return rects


def _rects_overlap(rect_list, eps):
    for i in range(len(rect_list)):
        x0, y0, x1, y1 = rect_list[i]
        for j in range(i + 1, len(rect_list)):
            a0, b0, a1, b1 = rect_list[j]
            if min(x1, a1) - max(x0, a0) > eps and min(y1, b1) - max(y0, b0) > eps:
                return True
    return False


def _rect_exterior(rect_list, target, dir_idx, eps):
    """Strip test on (x0,y0,x1,y1) rects; dir_idx 0..3 = N,E,S,W (y-down)."""
    bx0 = min(r[0] for r in rect_list)
    by0 = min(r[1] for r in rect_list)
    bx1 = max(r[2] for r in rect_list)
    by1 = max(r[3] for r in rect_list)
    x0, y0, x1, y1 = target
    if dir_idx == 0:
        sx0, sy0, sx1, sy1 = x0, by0, x1, y0
    elif dir_idx == 1:
        sx0, sy0, sx1, sy1 = x1, y0, bx1, y1
    elif dir_idx == 2:
        sx0, sy0, sx1, sy1 = x0, y1, x1, by1
    else:
        sx0, sy0, sx1, sy1 = bx0, y0, x0, y1
    for r in rect_list:
        if r == target:
            continue
        if min(r[2], sx1) - max(r[0], sx0) > eps and min(r[3], sy1) - max(r[1], sy0) > eps:
            return False
    return True


def stacked_oneconnected_floorplans(nodes_list, edges_list, count, dim_inputs,
                                    cardinal_pairs, corridor_thickness, limit):
    """Floorplans for a 1-connected graph, composed as stacked component duals.

    Applies when the graph is exactly two biconnected components sharing one
    cut vertex (e.g. two wings joined by a hall). Each component's floorplans
    are generated through the full pipeline with the cut-vertex room pinned to
    the seam side (E|W for a horizontal stack, S|N for vertical); the second
    component is scaled so its cut-room span matches the first and the two are
    fused into a single plan whose cut room spans the seam. Composites are
    kept only when no rooms overlap and every user cardinal pin holds
    geometrically. Returns (plans, note) or (None, None) when the topology
    doesn't fit or nothing valid could be composed.
    """
    if not dim_inputs:
        return None, None
    try:
        import networkx as nx
        g = nx.Graph()
        g.add_nodes_from(range(len(nodes_list)))
        g.add_edges_from((int(e[0]), int(e[1])) for e in edges_list)
        if len(nodes_list) < 4 or g.number_of_edges() == 0 or not nx.is_connected(g):
            return None, None
        arts = list(nx.articulation_points(g))
        if len(arts) != 1:
            return None, None
        cut = arts[0]
        comps = [sorted(c) for c in nx.biconnected_components(g)]
        if len(comps) != 2:
            return None, None
    except Exception:
        return None, None
    labels = [node["label"] for node in nodes_list]
    if len(set(labels)) != len(labels):
        return None, None  # name-keyed stitching needs unique room labels
    cut_name = labels[cut]

    def component_plans(comp, seam_dir):
        mapping = {old: new for new, old in enumerate(comp)}
        sub_nodes = []
        for old in comp:
            node = dict(nodes_list[old])
            node["id"] = mapping[old]
            sub_nodes.append(node)
        sub_edges = [[mapping[e[0]], mapping[e[1]], "black"] for e in edges_list
                     if e[0] in mapping and e[1] in mapping]

        def slice_arr(key, default):
            arr = dim_inputs.get(key) or []
            return [arr[i] if i < len(arr) else default for i in comp]

        sub_dims = {
            "min_width": slice_arr("min_width", 3), "max_width": slice_arr("max_width", 99999),
            "min_height": slice_arr("min_height", 3), "max_height": slice_arr("max_height", 99999),
            "min_ratio": slice_arr("min_ratio", 3), "max_ratio": slice_arr("max_ratio", 99999),
            "plot_width": 0, "plot_height": 0,
            "symmetric": False, "optimal_floorplan": 0, "rotation_enabled": 0,
        }
        # User pins for rooms in this component; the cut room belongs to the
        # seam (its user pin, if any, is enforced on the composite instead).
        sub_cardinal = [{"room": mapping[n], "direction": "NESW"[d]}
                        for n, d in cardinal_pairs if n in mapping and n != cut]
        sub_cardinal.append({"room": mapping[cut], "direction": "NESW"[seam_dir]})
        coords = [[node.get("x", 0), node.get("y", 0)] for node in sub_nodes]
        sub_graph = InputGraph(len(sub_nodes), len(sub_edges), sub_edges, coords)
        per = max(6, min(count, 10))
        try:
            fps, msg = Documents.get_floorplans(
                starting_from=0, count=per, caller="door_connectivity",
                nodes_list=sub_nodes, graph=sub_graph, rectangular=True,
                minDimEnabled=True, nonAdj=False, limit=per,
                corridor_thickness=corridor_thickness, dim_inputs=sub_dims,
                edges_list=sub_edges, non_adj_edge_list=[],
                cardinal_constraints=sub_cardinal)
        except Exception:
            return [], ""
        return fps.to_dict()["Documents"]["floorPlans"], msg

    memo = {}

    def plans_for(comp_idx, seam_dir):
        key = (comp_idx, seam_dir)
        if key not in memo:
            memo[key] = component_plans(comps[comp_idx], seam_dir)
        return memo[key]

    def color_of(plan, name):
        for room in plan:
            if room["name"] == name:
                return room.get("color", "#1C4C82")
        return "#1C4C82"

    composed = []
    relaxed = False
    name_by_node = {i: labels[i] for i in range(len(labels))}
    # (left/top component, right/bottom component) x (horizontal, vertical)
    for first, second in ((0, 1), (1, 0)):
        for axis in ("h", "v"):
            if len(composed) >= count:
                break
            l_dir, r_dir = (1, 3) if axis == "h" else (2, 0)
            left_plans, left_msg = plans_for(first, l_dir)
            right_plans, right_msg = plans_for(second, r_dir)
            if "relaxed" in (left_msg or "") or "relaxed" in (right_msg or ""):
                relaxed = True
            for lp in left_plans:
                if len(composed) >= count:
                    break
                lrects = _plan_rects(lp)
                if cut_name not in lrects:
                    continue
                lall = list(lrects.values())
                lw = max(r[2] for r in lall) - min(r[0] for r in lall)
                lh = max(r[3] for r in lall) - min(r[1] for r in lall)
                leps = max(lw, lh, 1e-6) * 1e-4
                lcut = lrects[cut_name]
                if not _rect_exterior(lall, lcut, l_dir, leps):
                    continue
                # Gapless composite: the cut room must span the FULL seam side
                # of its component, so the two rectangles fuse into one
                # rectangle with no empty corners at the seam.
                if axis == "h":
                    if (lcut[1] > min(r[1] for r in lall) + leps or
                            lcut[3] < max(r[3] for r in lall) - leps):
                        continue
                else:
                    if (lcut[0] > min(r[0] for r in lall) + leps or
                            lcut[2] < max(r[2] for r in lall) - leps):
                        continue
                for rp in right_plans:
                    rrects = _plan_rects(rp)
                    if cut_name not in rrects:
                        continue
                    rall = list(rrects.values())
                    rw = max(r[2] for r in rall) - min(r[0] for r in rall)
                    rh = max(r[3] for r in rall) - min(r[1] for r in rall)
                    reps = max(rw, rh, 1e-6) * 1e-4
                    rcut = rrects[cut_name]
                    if not _rect_exterior(rall, rcut, r_dir, reps):
                        continue
                    if axis == "h":
                        if (rcut[1] > min(r[1] for r in rall) + reps or
                                rcut[3] < max(r[3] for r in rall) - reps):
                            continue
                    else:
                        if (rcut[0] > min(r[0] for r in rall) + reps or
                                rcut[2] < max(r[2] for r in rall) - reps):
                            continue
                    if axis == "h":
                        span_l = lcut[3] - lcut[1]
                        span_r = rcut[3] - rcut[1]
                    else:
                        span_l = lcut[2] - lcut[0]
                        span_r = rcut[2] - rcut[0]
                    if span_l <= 0 or span_r <= 0:
                        continue
                    s = span_l / span_r
                    if axis == "h":
                        dx = lcut[2] - rcut[0] * s
                        dy = lcut[1] - rcut[1] * s
                    else:
                        dx = lcut[0] - rcut[0] * s
                        dy = lcut[3] - rcut[1] * s
                    rooms = []
                    for nm, (x0, y0, x1, y1) in lrects.items():
                        if nm == cut_name:
                            continue
                        rooms.append((nm, x0, y0, x1, y1, color_of(lp, nm)))
                    for nm, (x0, y0, x1, y1) in rrects.items():
                        if nm == cut_name:
                            continue
                        rooms.append((nm, x0 * s + dx, y0 * s + dy,
                                      x1 * s + dx, y1 * s + dy, color_of(rp, nm)))
                    tcut = (rcut[0] * s + dx, rcut[1] * s + dy,
                            rcut[2] * s + dx, rcut[3] * s + dy)
                    if axis == "h":
                        fused = (lcut[0], lcut[1], tcut[2], lcut[3])
                    else:
                        fused = (lcut[0], lcut[1], lcut[2], tcut[3])
                    rooms.append((cut_name, fused[0], fused[1], fused[2], fused[3],
                                  color_of(lp, cut_name)))
                    rect_list = [(r[1], r[2], r[3], r[4]) for r in rooms]
                    w = max(r[2] for r in rect_list) - min(r[0] for r in rect_list)
                    h = max(r[3] for r in rect_list) - min(r[1] for r in rect_list)
                    eps = max(w, h, 1e-6) * 1e-4
                    if _rects_overlap(rect_list, eps) or not _is_gapless(rect_list, eps):
                        continue
                    rect_by_name = {r[0]: (r[1], r[2], r[3], r[4]) for r in rooms}
                    ok = True
                    for n, d in cardinal_pairs:
                        target = rect_by_name.get(name_by_node[n])
                        if target is None or not _rect_exterior(rect_list, target, d, eps):
                            ok = False
                            break
                    if not ok:
                        continue
                    composed.append([_stacked_room_dict(nm, col, x0, y0, x1, y1)
                                     for nm, x0, y0, x1, y1, col in rooms])
                    if len(composed) >= count:
                        break
    if not composed:
        return None, None
    note = (" One-connected graph composed as two stacked component duals"
            " joined at '" + cut_name + "'.")
    if relaxed:
        note += " Adjacency constraints were relaxed to satisfy cardinal directions."
    return composed, note


def spanning_tree_edges(edges_list, nodecnt):
    """BFS spanning-tree subset of the given edges (adjacency relaxation).

    Keeps only existing user edges; roots at the highest-degree node so hub
    adjacencies survive. Returns edges in the same [src, dst, color] shape.
    """
    adj = {i: [] for i in range(nodecnt)}
    edge_by_pair = {}
    for edge in edges_list:
        a, b = edge[0], edge[1]
        adj[a].append(b)
        adj[b].append(a)
        edge_by_pair[(min(a, b), max(a, b))] = edge
    if not edge_by_pair:
        return list(edges_list)
    roots = sorted(adj, key=lambda n: len(adj[n]), reverse=True)
    visited = set()
    tree = []
    for root in roots:
        if root in visited:
            continue
        visited.add(root)
        queue = [root]
        while queue:
            cur = queue.pop(0)
            for nbr in adj[cur]:
                if nbr not in visited:
                    visited.add(nbr)
                    queue.append(nbr)
                    tree.append(edge_by_pair[(min(cur, nbr), max(cur, nbr))])
    return tree


class Documents:
    def __init__(self, hasMore, offset, documentID, name, count):
        self.hasMore = hasMore
        self.offset = offset
        self.documentID = documentID
        self.name = name
        self.count = count
        self.floorplans = []
        self.ptpg_graph = None

    def append_floorplan(self,floorplan):
        if floorplan:
            self.floorplans.append([room.to_dict() for room in floorplan])
    
    def set_ptpg_graph(self, ptpg_graph):
        self.ptpg_graph = ptpg_graph

    def to_dict(self):
        doc_dict = {
            "documentID": self.documentID,
            "name": self.name,
            "count":self.count,
            # "hasMore": self.hasMore,
            # "offset": self.offset,
            "floorPlans": self.floorplans
        }
        if self.ptpg_graph is not None:
            doc_dict["ptpg_graph"] = self.ptpg_graph
            
        return {
            "Documents": doc_dict
        }

    @staticmethod
    def get_floorplans(starting_from: int, count: int, caller, nodes_list: list, graph: InputGraph, rectangular: bool, corridor=False,
                         dimensioned = False, dimensionedCirculation = False, minDimEnabled = False, removeAddCirculation = False, publicEnabled = False, nonAdj = False, normalize_const=40, limit=FLOORPLAN_LIMIT, corridor_thickness=None,documentID=None, name=None,circulationEnabled = 0, dim_inputs={},edges_list=[], non_adj_edge_list=[], cardinal_constraints=[]):
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        message = ""
        dim_parameters: DimParameters = None
        if minDimEnabled:
            dim_parameters = DimParameters(min_width=dim_inputs['min_width'], min_height=dim_inputs['min_height'],max_width=dim_inputs['max_width'], max_height=dim_inputs['max_height'], plot_width=dim_inputs['plot_width'], plot_height=dim_inputs['plot_height'], isOptimalEnabled=dim_inputs['optimal_floorplan'],isRotationAllowed = dim_inputs['rotation_enabled'])
        elif dimensioned:
            dim_parameters = DimParameters(min_width=dim_inputs['min_width'], min_height=dim_inputs['min_height'], max_width=dim_inputs['max_width'], max_height=dim_inputs['max_height'], min_ratio=dim_inputs['min_ratio'], max_ratio=dim_inputs['max_ratio'], plot_width=dim_inputs['plot_width'], plot_height=dim_inputs['plot_height'], symmetric=dim_inputs['symmetric'], isOptimalEnabled=dim_inputs['optimal_floorplan'])
        ui = GuiParameters(graph=graph).set_isDimensioned(dimensioned).set_isDimensionedCirculation(
            dimensionedCirculation).set_isMinDimensioned(minDimEnabled).set_isRemoveAddCirculation(
            removeAddCirculation).set_isPublic(publicEnabled).set_min_dim_inputs(dim_parameters).set_isCirculation(circulationEnabled)
        original_print(ui)
        documentID = str(uuid.uuid4()) if documentID is None else documentID
        name = "Untitled Document" if name is None else name
        ui.set_message("")
        ui.set_fptype(caller)
        ui.set_edges(edges_list)
        roomColors = []
        roomNames = []
        for node in nodes_list:
            roomColors.append(node["color"])
            roomNames.append(node["label"])
        ui.set_roomNames(roomNames)
        ui.set_roomColors(roomColors)
        if corridor_thickness is not None:
            ui.set_corridor_thickness(corridor_thickness)
        if corridor:
            ui.set_command('circulation')
        if starting_from is None:
            starting_from = 0
        if count is None:
            count = 1
        nodes_data = []
        response = []
        if count == 1:
            if caller == 'lshape':
                ui.set_letter("L Shape")
                for node in nodes_list:
                    node_obj = gui.gui_class.Nodes(node['id'], node['x'], node['y'])
                    nodes_data.append(node_obj)
                handle_letter_shape(ui, graph, nodes_data=nodes_data)
                message = 'Generated L shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'ushape':
                ui.set_letter("U Shape")
                handle_letter_shape(ui, graph)
                message = 'Generated U shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'tshape':
                ui.set_letter("T Shape")
                handle_letter_shape(ui, graph)
                message = 'Generated T shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'zshape':
                ui.set_letter("Z Shape")
                handle_letter_shape(ui, graph)
                message = 'Generated Z shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'staircaseshape':
                handle_staircase_shaped(ui, graph)
                message = 'Generated Staircase shaped floorplan.'
                message += ui.get_message()
                print(message)
            # elif caller == 'pentagonal': #Support Not added yet
            #     Pentagonal.PentagonalFloorplan(ui, graph, nodes_list)
            # elif caller == 'hexagonal': #Support Not added yet
            #     Hexagonal.HexagonalFloorplan(ui, graph, nodes_list)
            # elif caller == 'custom': #Support Not added yet
            # Customplot.CustomplotFloorplan(graph, nodes_list)
            elif caller == 'rectangular' or caller == 'irregular':
                if rectangular:
                    handle_single_oc(ui, graph)
                else:
                    handle_single(ui, graph)

            elif caller == "door_connectivity":
                ui.set_isNonAdj(nonAdj)
                ui.set_non_adj_list(non_adj_edge_list)
                ui.set_is_multiple_door(False)
                graph.cardinal_constraints = normalize_cardinal_constraints(
                    cardinal_constraints, len(nodes_list))
                apply_cardinal_ring(graph, len(nodes_list), edges_list,
                                    graph.cardinal_constraints, non_adj_edge_list)
                handle_door_connectivity(ui, graph)
            else:
                message = f"Support for {caller} Not yet Handled from Backend for Single Floorplan"
                print(message)
        else:
            if caller == 'lshape':
                print("Generating Multiple L shape")
                ui.set_letter("L Shape")
                for node in nodes_list:
                    node_obj = gui.gui_class.Nodes(node['id'], node['x'], node['y'])
                    nodes_data.append(node_obj)
                handle_multiple_l(ui, graph, nodes_data=nodes_data)
                message = 'Generated L shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'rectangular':
                handle_multiple_oc(ui, graph)
            elif caller == 'irregular':
                handle_multiple(ui, graph)
            elif caller == "door_connectivity":
                ui.set_isNonAdj(nonAdj)
                ui.set_non_adj_list(non_adj_edge_list)
                ui.set_is_multiple_door(True)
                cardinal_pairs = normalize_cardinal_constraints(
                    cardinal_constraints, len(nodes_list))
                graph.cardinal_constraints = cardinal_pairs
                if not non_adj_edge_list:
                    # One-connected graphs (two wings joined by one cut-vertex
                    # room) compose better as stacked component duals than
                    # through biconnectivity augmentation, which invents a
                    # fake adjacency and merges dummy rooms.
                    stacked_plans, stacked_note = stacked_oneconnected_floorplans(
                        nodes_list, edges_list, count, dim_inputs,
                        cardinal_pairs, corridor_thickness, limit)
                    if stacked_plans:
                        message = ('Generated Multiple Door connectivity floorplan.'
                                   + stacked_note)
                        response = Documents(False, 0, documentID, name,
                                             min(len(stacked_plans), limit, count))
                        response.floorplans = stacked_plans[:min(limit, count)]
                        builtins.print = original_print
                        return response, message
                apply_cardinal_ring(graph, len(nodes_list), edges_list,
                                    cardinal_pairs, non_adj_edge_list)
                handle_door_connectivity(ui, graph)
                message = 'Generated Multiple Door connectivity floorplan.'+ ui.get_message()
                original_plans = list(ui.get_output_data())
                if not rectangularize_output(ui) and original_plans and not cardinal_pairs:
                    # The gapless gate emptied the batch - return the ungated
                    # plans with an honest note rather than nothing.
                    ui._set_output_data(original_plans)
                    message += ' Some floorplans have a non-rectangular outline.'
                if cardinal_pairs and len(filter_output_by_cardinal(ui, cardinal_pairs)) == 0:
                    # Cardinal constraints take priority over adjacency wishes:
                    # retry with the adjacency set relaxed to a spanning tree
                    # (drops the fewest edges that still keep every room reachable),
                    # then as a last resort drop the cardinal filter so the caller
                    # always receives floorplans. Every constrained attempt is
                    # verified geometrically - only plans that satisfy all pins
                    # count as output, so callers can populate their full batch
                    # from satisfying plans alone.
                    node_coordinates = [[node.get("x", 0), node.get("y", 0)]
                                        for node in nodes_list]
                    tree_edges = spanning_tree_edges(edges_list, len(nodes_list))
                    attempts = []
                    if len(tree_edges) < len(edges_list):
                        attempts.append((tree_edges, cardinal_pairs,
                                         " Adjacency constraints were relaxed to satisfy cardinal directions."))
                    attempts.append((edges_list, [],
                                     " Cardinal constraints could not be satisfied and were ignored."))
                    for attempt_edges, attempt_cardinal, note in attempts:
                        retry_graph = InputGraph(len(nodes_list), len(attempt_edges),
                                                 attempt_edges, node_coordinates)
                        retry_graph.cardinal_constraints = attempt_cardinal
                        apply_cardinal_ring(retry_graph, len(nodes_list),
                                            attempt_edges, attempt_cardinal,
                                            non_adj_edge_list)
                        handle_door_connectivity(ui, retry_graph)
                        retry_original = list(ui.get_output_data())
                        rectangularize_output(ui)
                        if attempt_cardinal:
                            filter_output_by_cardinal(ui, attempt_cardinal)
                        elif not ui.get_output_data() and retry_original:
                            ui._set_output_data(retry_original)
                            note += ' Some floorplans have a non-rectangular outline.'
                        if len(ui.get_output_data()) > 0:
                            graph = retry_graph
                            message += note
                            break
            elif caller == "multiple_l":
                handle_multiple_l(ui, graph)
            else:
                message = f"Support for {caller} Not yet Handled from Backend for Multiple Floorplan"
                print(message)
        if count == 1:
            outputData = ui.get_output_data()
        elif count > 1:
            outputData = ui.get_output_data()
        offset = 0
        hasMore = graph.fpcnt - offset - 1 > 0
        total_fp_count = min(min(len(outputData), limit),count)
        response = Documents(hasMore, offset, documentID, name, total_fp_count)
        
        # Add ptpg_graph if available
        if caller == "door_connectivity":
            ptpg_graph = ui.get_ptpg_graph() if hasattr(ui, 'get_ptpg_graph') else None
            if ptpg_graph:
                response.set_ptpg_graph(ptpg_graph)

        for index in range(min(min(len(outputData), limit),count)):
            rooms = []
            floorplanData = outputData[index].final_traversal
            name_coord = outputData[index].name_coords
            area = outputData[index].area
            widths = outputData[index].room_width
            heights = outputData[index].room_height
            k = 0
            for roomData in floorplanData:
                room = None
                x1 = roomData[0][0]
                y1 = roomData[0][1]
                wallValues = []
                for i in range(1, len(roomData)):
                    x2 = roomData[i][0]
                    y2 = roomData[i][1]
                    wall = Wall(str(uuid.uuid4()), x1, y1, x2, y2)
                    wallValues.append(wall)
                    x1 = x2
                    y1 = y2
                wallValues.append(Wall(str(uuid.uuid4()), x1, y1, roomData[0][0], roomData[0][1]))
                room = Room(str(uuid.uuid4()), nodes_list[k]["label"], nodes_list[k]["color"], wallValues,
                            circular_coordinates=roomData,name_coord = name_coord[k],area=area[k],width = widths[k],height = heights[k])  # To add handling of node index starting from 0 then 1 then 2. It should be a unique no and GPLAN should map
                k = k + 1
                rooms.append(room)
            response.append_floorplan(rooms)

        builtins.print = original_print

        return response, message

    @staticmethod
    def get_space_optimized_floorplan(request_data):
        """
        Generate a space-optimized floorplan using the negNew FloorPlan engine.
        
        Args:
            request_data: Dictionary containing:
                - request_id: Unique request identifier
                - params: Dictionary with:
                    - regions: List of rectangular regions (optional if boundary is provided)
                    - boundary: List of [x,y] points defining polygonal boundary (optional if regions provided)
                    - rooms: List of room specifications
                    - fixed_rooms: List of fixed room specifications
                    - adjacency: List of adjacency requirements
                    - non_adjacency: List of non-adjacency requirements
                    - entrance_coords: Entrance location
                - ops: List of operations to perform (e.g., ["place", "compact", "expand", "score"])
        
        Returns:
            Dictionary with response data matching the expected output format
        """
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        try:
            request_id = request_data.get('request_id', str(uuid.uuid4()))
            params = request_data.get('params', {})
            ops = request_data.get('ops', ['place', 'compact', 'expand', 'score'])
            
            # Extract parameters
            # Support EITHER regions OR boundary
            regions = params.get('regions', None)
            boundary = params.get('boundary', None)
            rooms = params.get('rooms', [])
            fixed_rooms = params.get('fixed_rooms', [])
            adjacency = params.get('adjacency', [])
            non_adjacency = params.get('non_adjacency', [])
            entrance_coords = params.get('entrance_coords', None)

            fixed_room_polygons = []
            for fixed_room in fixed_rooms:
                if not isinstance(fixed_room, dict):
                    continue
                polygon = fixed_room.get('polygon')
                if polygon:
                    fixed_room_polygons.append(polygon)
                    continue
                try:
                    fx = int(fixed_room['x'])
                    fy = int(fixed_room['y'])
                    fw = int(fixed_room['width'])
                    fh = int(fixed_room['height'])
                except Exception:
                    continue
                fixed_room_polygons.append([
                    [fx, fy],
                    [fx + fw, fy],
                    [fx + fw, fy + fh],
                    [fx, fy + fh],
                ])
            
            # If boundary is provided instead of regions, convert it
            if boundary and not regions:
                try:
                    regions = boundary_to_regions(boundary, fixed_rooms=fixed_room_polygons)
                    print(f"Converted boundary with {len(boundary)} points to {len(regions)} regions")
                except Exception as e:
                    builtins.print = original_print
                    return {
                        'request_id': request_id,
                        'status': 'error',
                        'data': {},
                        'error': {'message': f'Failed to convert boundary to regions: {str(e)}'}
                    }

            boundary_bounds = None
            if boundary:
                boundary_bounds = {
                    'min_x': min(point[0] for point in boundary),
                    'min_y': min(point[1] for point in boundary),
                    'max_x': max(point[0] for point in boundary),
                    'max_y': max(point[1] for point in boundary),
                }
            
            # Validate that we have regions (either provided or converted)
            if not regions:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'data': {},
                    'error': {'message': 'Either regions or boundary must be provided'}
                }
            
            # Operation flags
            enable_expansion = 'expand' in ops
            enable_compaction = 'compact' in ops
            max_attempts = params.get('max_attempts', 100)
            
            # Create UI object for output storage
            from GPLAN.pythongui.GuiParameters import GuiParameters
            ui = GuiParameters(graph=None)
            
            # Call the handler
            success = handle_space_optimization(
                ui=ui,
                regions=regions,
                rooms=rooms,
                fixed_rooms=fixed_rooms,
                adjacency=adjacency,
                non_adjacency=non_adjacency,
                entrance_coords=entrance_coords,
                max_attempts=max_attempts,
                enable_expansion=enable_expansion,
                enable_compaction=enable_compaction,
                boundary_bounds=boundary_bounds
            )
            
            if not success:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'data': {},
                    'error': {'message': ui.get_message()}
                }
            
            # Extract output data
            output_data = ui.get_output_data()
            if not output_data or len(output_data) == 0:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'data': {},
                    'error': {'message': 'No output data generated'}
                }
            
            result = output_data[0]
            
            # Calculate floor dimensions
            floor_width = max(r['x'] + r['width'] for r in regions) if regions else 0
            floor_height = max(r['y'] + r['height'] for r in regions) if regions else 0
            
            # Format response
            response = {
                'request_id': request_id,
                'status': 'ok',
                'data': {
                    'floor': {
                        'width': floor_width,
                        'height': floor_height,
                        'regions': regions,
                        'entrance_coords': entrance_coords
                    },
                    'placements': result['rooms'],
                    'metrics': {
                        'ops_run': ops,
                        'adjacency_score': result['metrics']['adjacency_score'] / len(adjacency) if adjacency else 1.0,
                        'satisfied_pairs': result['metrics']['satisfied_pairs'],
                        'non_adjacency_violations': result['metrics']['non_adjacency_violations'],
                        'entrance_adjacent_rooms': result['metrics'].get('entrance_adjacent_rooms', []),
                        'area_utilization': result['metrics']['area_utilization'],
                        'integrity': {
                            'overlaps': [],
                            'out_of_bounds': [],
                            'invalid_adjacent_edges': []
                        }
                    }
                },
                'error': {}
            }
            
            builtins.print = original_print
            return response
            
        except Exception as e:
            builtins.print = original_print
            import traceback
            traceback.print_exc()
            return {
                'request_id': request_data.get('request_id', 'unknown'),
                'status': 'error',
                'data': {},
                'error': {'message': str(e)}
            }

    @staticmethod
    def get_ga_optimized_floorplan(request_data):
        """
        Generate a GA-optimized floorplan using genetic algorithm with corridor generation.
        
        Args:
            request_data: Dictionary containing:
                - request_id: Unique request identifier
                - engine: Should be "GA_FloorPlan"
                - params: Dictionary with:
                    - plot_width: Width of the plot
                    - plot_height: Height of the plot
                    - corridor_width: Width of corridors (default: 3)
                    - rooms: List of room objects with walls
                    - walls: List of all walls
                    - labels: List of labels (optional)
                    - ga_config: GA configuration (optional)
                        - max_workers: Number of workers for parallel processing (default: 1)
        
        Returns:
            Dictionary with response data matching temp2.json format
        """
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        try:
            request_id = request_data.get('request_id', str(uuid.uuid4()))
            params = request_data.get('params', {})
            
            # Build floorplan_data in the format ga_current expects
            floorplan_data = {
                'plot_width': params.get('plot_width', 40),
                'plot_height': params.get('plot_height', 30),
                'rooms': params.get('rooms', []),
                'walls': params.get('walls', []),
                'labels': params.get('labels', []),
                'windows': params.get('windows', []),
                'doors': params.get('doors', [])
            }
            
            corridor_width = params.get('corridor_width', 3)
            ga_config = params.get('ga_config', None)
            
            # Create UI object for output storage
            from GPLAN.pythongui.GuiParameters import GuiParameters
            ui = GuiParameters(graph=None)
            
            # Call the GA handler
            success = handle_ga_optimization(
                ui=ui,
                floorplan_data=floorplan_data,
                corridor_width=corridor_width,
                ga_config=ga_config
            )
            
            if not success:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'engine': 'GA_FloorPlan',
                    'data': {},
                    'error': {'message': ui.get_message()}
                }
            
            # Extract output data
            outputData = ui.get_output_data() if hasattr(ui, 'get_output_data') else []
            if not outputData:
                outputData = []
            
            if not outputData or len(outputData) == 0:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'engine': 'GA_FloorPlan',
                    'data': {},
                    'error': {'message': 'No output data generated'}
                }
            
            result = outputData[0]
            
            # Format response matching temp2.json structure
            response = {
                'request_id': request_id,
                'status': 'success',
                'engine': 'GA_FloorPlan',
                'data': {
                    'floor': {
                        'plot_width': result['plot_width'],
                        'plot_height': result['plot_height']
                    },
                    'ga_optimization': {
                        'status': 'converged',
                        'solution_chromosome': result['ga_solution']
                    },
                    'rooms': result['rooms'],
                    'walls': result['walls'],
                    'labels': result['labels'],
                    'windows': result.get('windows', []),
                    'doors': result.get('doors', []),
                    'layout_matrix': result['layout_matrix']
                },
                'error': {}
            }
            
            builtins.print = original_print
            return response
            
        except Exception as e:
            builtins.print = original_print
            import traceback
            traceback.print_exc()
            return {
                'request_id': request_data.get('request_id', 'unknown'),
                'status': 'error',
                'engine': 'GA_FloorPlan',
                'data': {},
                'error': {'message': str(e)}
            }
