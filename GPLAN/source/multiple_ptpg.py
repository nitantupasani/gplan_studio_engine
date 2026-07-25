"""Enumeration of topological PTPG variants.

Headless port of ``multiple_ptpg.py`` from the GPLAN-team/GPLAN branch
``QA_multi_ptpg``, plus the bounded search the branch's own ``explained_doc.md``
recommends but never implemented.

A PTPG here is a planar graph that is triangulated on every interior face while
its outer face stays a simple cycle - the shape :meth:`InputGraph.door_connectivity`
produces. Two transformations map one PTPG to another:

  Stage 1 - **Boundary edge removal.** Drop an outer-cycle edge ``(u,v)`` whose
  single common neighbour ``w`` is interior. The triangle ``u-v-w`` merges into
  the outer face, so the result is still internally triangulated.

  Stage 2 - **4-cycle diagonal flip.** An interior edge ``(u,v)`` is the shared
  diagonal of the quadrilateral ``u-a-v-b`` formed by its two incident
  triangles. Replace it with ``(a,b)`` when ``a`` and ``b`` have exactly two
  common neighbours (``u`` and ``v``) and are not already adjacent.

The branch applied one round of these and called the result "all variants".
:func:`enumerate_ptpg_variants` runs the real breadth-first closure instead,
bounded by ``max_variants``/``max_depth`` because the reachable set is
exponential in the number of flippable 4-cycles.

Fixes carried over the branch implementation:

* ``user_needs`` is normalised once into a set of sorted 2-tuples; the branch
  tested raw ``(u,v,colour)`` triples against it in stage 1, so user-protected
  edges were never actually protected there.
* Outer edges are stored as sorted tuples in a set, so the interior-edge filter
  in :func:`find_4_cycles_filtered` cannot silently miss a match.
* A flip is rejected when the opposite diagonal already exists.
* Every emitted variant is validated as a PTPG and deduplicated by its edge set,
  so the same graph is never generated twice down two different paths.
"""

import numpy as np
import networkx as nx


DEFAULT_MAX_VARIANTS = 40
DEFAULT_MAX_DEPTH = 3


def _norm_edge(u, v):
    return (u, v) if u <= v else (v, u)


def _edge_key(G):
    """Canonical, hashable identity of a graph over a fixed node set."""
    return frozenset(_norm_edge(u, v) for u, v in G.edges())


def normalise_user_needs(user_needs):
    """Accept ``[(u,v)]``, ``[(u,v,colour)]`` or ``[[u,v,colour]]`` uniformly."""
    out = set()
    for e in user_needs or []:
        if len(e) >= 2:
            out.add(_norm_edge(e[0], e[1]))
    return out


def get_outer_face(G):
    """Outer-face nodes and edges: an edge is outer iff it has one common neighbour."""
    outer_edges = []
    outer_nodes_set = set()
    adj = {n: set(neighbors) for n, neighbors in G.adjacency()}
    for u, v in G.edges():
        if len(adj[u] & adj[v]) == 1:
            outer_edges.append(_norm_edge(u, v))
            outer_nodes_set.add(u)
            outer_nodes_set.add(v)
    return sorted(outer_nodes_set), outer_edges


def get_outer_face_cycle(G):
    """Outer-face nodes in cyclic order, or ``[]`` when the walk is not a simple cycle."""
    outer_nodes, outer_edges = get_outer_face(G)
    if not outer_edges:
        return []

    outer_adj = {}
    for u, v in outer_edges:
        outer_adj.setdefault(u, []).append(v)
        outer_adj.setdefault(v, []).append(u)

    # Every node of a simple outer cycle has exactly two outer neighbours.
    if any(len(nbrs) != 2 for nbrs in outer_adj.values()):
        return []

    start_u, start_v = outer_edges[0]
    cycle = [start_u, start_v]
    prev, current = start_u, start_v
    while True:
        candidates = [n for n in outer_adj[current] if n != prev]
        if not candidates:
            break
        nxt = candidates[0]
        if nxt == start_u:
            break
        if nxt in cycle:
            return []       # walk closed early: not a simple cycle
        cycle.append(nxt)
        prev, current = current, nxt

    if len(cycle) != len(outer_adj):
        return []
    return cycle


def boundary_nodes(G):
    """Boundary nodes for reporting, with the engine's own detector as a fallback.

    :func:`get_outer_face_cycle` is deliberately strict - it returns nothing
    unless the outer face is a simple cycle, which is what the variant
    transformations require. Some graphs that ``door_connectivity`` calls a PTPG
    have a boundary that ``opr.get_bdy`` reports as an open path instead. Those
    still need a boundary for the interior/exterior filter and for the client to
    draw, so fall back to the engine routine the placer already relies on.
    """
    cycle = get_outer_face_cycle(G)
    if cycle:
        return cycle, True
    try:
        from GPLAN.source.graphoperations import operations as opr

        matrix = nx.to_numpy_array(G, nodelist=sorted(G.nodes()), dtype=int)
        bn, be = opr.get_bdy(opr.get_trngls(matrix), opr.get_directed(matrix))
        ordered = opr.ordered_bdy(bn, be)
        return [int(n) for n in ordered], False
    except Exception:
        nodes, _ = get_outer_face(G)
        return [int(n) for n in nodes], False


def find_4_cycles_filtered(G, outer_edges):
    """Quads ``(u, a, v, b)`` where the interior edge ``(u, v)`` is the diagonal."""
    outer_set = set(outer_edges)
    quads = []
    adj = {n: set(neighbors) for n, neighbors in G.adjacency()}
    for u, v in G.edges():
        e = _norm_edge(u, v)
        if e in outer_set:
            continue
        common = adj[e[0]] & adj[e[1]]
        if len(common) == 2:
            a, b = sorted(common)
            quads.append((e[0], a, e[1], b))
    return quads


def is_valid_ptpg(G, expected_nodes=None):
    """A variant is usable only if it is still an internally triangulated planar graph."""
    if G.number_of_nodes() < 3:
        return False
    if expected_nodes is not None and G.number_of_nodes() != expected_nodes:
        return False
    if not nx.is_connected(G):
        return False
    if min(dict(G.degree()).values()) < 2:
        return False
    # The boundary machinery downstream (opr.get_bdy, cip.find_cip, the placer's
    # shortcut walk) assumes a 2-connected graph; a variant that drops below
    # that has no well-defined outer face to walk.
    if not nx.is_biconnected(G):
        return False
    adj = {n: set(nbrs) for n, nbrs in G.adjacency()}
    for u, v in G.edges():
        if len(adj[u] & adj[v]) not in (1, 2):
            return False
    if not nx.check_planarity(G, counterexample=False)[0]:
        return False
    return len(get_outer_face_cycle(G)) >= 3


def process_ptpg_recursive(G, user_needs, forbidden_cycles):
    """One transformation step: every PTPG reachable from ``G`` by a single edit.

    Kept under the branch's original name and signature. Returns a list of
    ``{'graph': H, 'forbidden_cycles': set|None, 'operation': str, 'detail': tuple}``.
    """
    if forbidden_cycles is None:
        forbidden_cycles = set()

    results = []
    user_needs_set = normalise_user_needs(user_needs)
    outer_nodes, outer_edges = get_outer_face(G)
    outer_node_set = set(outer_nodes)

    # ---- STAGE 1: boundary edge removal ------------------------------------
    for u, v in outer_edges:
        e = _norm_edge(u, v)
        if e in user_needs_set:
            continue
        # The triangle collapsing into the outer face must hang off an interior
        # apex; otherwise removal would leave a chord across the new outer face.
        if set(nx.common_neighbors(G, u, v)) & outer_node_set:
            continue
        H = G.copy()
        H.remove_edge(u, v)
        results.append({
            'graph': H,
            'forbidden_cycles': set(forbidden_cycles),
            'operation': 'remove_boundary_edge',
            'detail': (e[0], e[1]),
        })

    # ---- STAGE 2: 4-cycle diagonal flip ------------------------------------
    adj = {n: set(neighbors) for n, neighbors in G.adjacency()}
    for cyc in find_4_cycles_filtered(G, outer_edges):
        u, a, v, b = cyc
        cyc_key = tuple(sorted(cyc))
        if cyc_key in forbidden_cycles:
            continue

        diag1 = _norm_edge(u, v)
        diag2 = _norm_edge(a, b)
        if diag1 in user_needs_set:
            continue
        if G.has_edge(*diag2):
            continue
        # a and b may only meet at u and v, else the flip creates a chord.
        if len(adj[a] & adj[b]) != 2:
            continue

        H = G.copy()
        H.remove_edge(*diag1)
        H.add_edge(*diag2)
        new_forbidden = set(forbidden_cycles)
        new_forbidden.add(cyc_key)
        results.append({
            'graph': H,
            'forbidden_cycles': new_forbidden,
            'operation': 'flip_diagonal',
            'detail': (diag1[0], diag1[1], diag2[0], diag2[1]),
        })

    return results


def enumerate_ptpg_variants(G, user_needs=None, max_variants=DEFAULT_MAX_VARIANTS,
                            max_depth=DEFAULT_MAX_DEPTH, include_base=True,
                            deadline=None):
    """Breadth-first closure of the two transformations, bounded and deduplicated.

    Returns a list of dicts ordered base-first then by depth:
    ``{'graph', 'forbidden_cycles', 'depth', 'operation', 'detail', 'is_base'}``.
    """
    import time

    expected_nodes = G.number_of_nodes()
    user_needs_set = normalise_user_needs(user_needs)

    base = {
        'graph': G.copy(),
        'forbidden_cycles': set(),
        'depth': 0,
        'operation': 'base',
        'detail': None,
        'is_base': True,
    }
    seen = {_edge_key(G)}
    variants = [base] if include_base else []
    frontier = [base]
    depth = 0

    while frontier and depth < max_depth and len(variants) < max_variants:
        if deadline is not None and time.monotonic() > deadline:
            break
        depth += 1
        next_frontier = []
        for parent in frontier:
            if len(variants) >= max_variants:
                break
            if deadline is not None and time.monotonic() > deadline:
                break
            for step in process_ptpg_recursive(parent['graph'], user_needs_set,
                                               parent['forbidden_cycles']):
                H = step['graph']
                key = _edge_key(H)
                if key in seen:
                    continue
                if not is_valid_ptpg(H, expected_nodes):
                    seen.add(key)       # never revisit a dead end
                    continue
                seen.add(key)
                child = {
                    'graph': H,
                    'forbidden_cycles': step['forbidden_cycles'],
                    'depth': depth,
                    'operation': step['operation'],
                    'detail': step['detail'],
                    'is_base': False,
                }
                variants.append(child)
                next_frontier.append(child)
                if len(variants) >= max_variants:
                    break
        frontier = next_frontier

    return variants[:max_variants]


def planar_tutte_embedding(G, outer_cycle=None, tol=1e-6, max_iters=1000):
    """Tutte barycentric embedding, normalised to the unit square."""
    if outer_cycle is None:
        outer_cycle = get_outer_face_cycle(G)
    if not outer_cycle or len(outer_cycle) < 3:
        return nx.spring_layout(G, seed=42)

    interior_nodes = set(G.nodes()) - set(outer_cycle)
    k = len(outer_cycle)

    radius = 5.0
    pos = {}
    for i, node in enumerate(outer_cycle):
        angle = 2 * np.pi * i / k
        pos[node] = np.array([radius * np.cos(angle), radius * np.sin(angle)])
    for node in interior_nodes:
        pos[node] = np.array([0.0, 0.0])

    adj = {n: list(G.neighbors(n)) for n in G.nodes()}
    for _ in range(max_iters):
        max_move = 0.0
        for node in interior_nodes:
            neighbors = adj[node]
            if not neighbors:
                continue
            avg = np.mean([pos[nbr] for nbr in neighbors], axis=0)
            move = float(np.linalg.norm(pos[node] - avg))
            if move > max_move:
                max_move = move
            pos[node] = avg
        if max_move < tol:
            break

    all_points = np.array(list(pos.values()))
    min_xy = all_points.min(axis=0)
    max_xy = all_points.max(axis=0)
    scale = max(max_xy - min_xy)
    if scale == 0:
        scale = 1.0
    return {node: (pos[node] - min_xy) / scale for node in pos}


def filter_variants_by_constraints(variants, interior=None, exterior=None):
    """Keep variants whose outer cycle honours the interior/exterior node marks.

    ``interior`` nodes must not appear on the outer face; ``exterior`` nodes must.
    Each variant is annotated with its ``outer_cycle`` either way.
    """
    interior = set(interior or [])
    exterior = set(exterior or [])
    kept = []
    for var in variants:
        outer = var.get('outer_cycle')
        if not outer:
            outer, _ = boundary_nodes(var['graph'])
            var['outer_cycle'] = outer
        outer_set = set(outer)
        if interior and interior & outer_set:
            continue
        if exterior and not exterior.issubset(outer_set):
            continue
        kept.append(var)
    return kept
