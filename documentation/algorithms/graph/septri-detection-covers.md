# septri: separating-triangle detection and edge-cover removal

Scope: the detection predicates and the cover/removal core of
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\irregular\septri.py`.
Covered symbols: `sign` (L26), `point_in_triangle` (L37), `get_edges` (L55), `add_edge_to_cover` (L66),
`generate_alternate_graph` (L102), `get_graph_cover` (L140), `get_separating_edge_cover` (L159),
`get_multiple_separating_edge_covers` (L197), `remove_separating_triangles` (L221), `handle_STs` (L273),
`get_sep_triangles_and_edges` (L1218), `calc_all_triangles` (L1264), `point_in_triangle2` (L1450).
The door-connectivity handlers (`handle_non_trivial_ST_Door_connectivity` L359,
`handle_non_trivial_non_adj_ST_Door_connectivity` L700, `handle_STs_Door_connectivity` L1146,
`remove_st_edge_selection` L1270, `handle_STs_with_edge_selection` L1378) belong to the sibling dossier
and are referenced here only as consumers.

## Purpose

A rectangular dual exists for a planar triangulated graph only if the graph has no separating triangle
(a 3-cycle with vertices both inside and outside it). This module finds every such triangle in the
straight-line drawing the pipeline is carrying, then destroys all of them at once by picking a set of
edges that hits every separating triangle, subdividing each chosen edge with a fresh vertex, and
re-triangulating locally. Each inserted vertex becomes an extra "room" that is later merged back into
one of the two endpoint rooms, producing an L-shaped (irregular) room instead of a rectangle. The
module can produce several different such edge sets so the caller gets several structurally different
floorplans from one input graph.

## Where It Sits In The Pipeline

`handlers.py` -> `InputGraph.irreg_single_dual` / `InputGraph.irreg_multiple_dual` -> `st.handle_STs`
-> boundary identification -> 4-completion -> contraction/expansion -> `rdg.construct_dual`.

- `GPLAN\GPLAN\handlers.py:561,709,732,760` call `graph.irreg_single_dual()`;
  `GPLAN\GPLAN\handlers.py:361,363,792,923,1050,1068` (and more) call `graph.irreg_multiple_dual()`.
  So this code is live from the handler layer.
- `GPLAN\GPLAN\source\inputgraph.py:41` `from GPLAN.source.irregular import septri as st`.
- Call sites of `handle_STs`:
  - `inputgraph.py:256` inside `irreg_single_dual` (def at `inputgraph.py:202`), `num_expected_outputs = 1`.
  - `inputgraph.py:714` inside `door_connectivity2` (def at `inputgraph.py:650`), `num_expected_outputs = 1`.
  - `inputgraph.py:929` inside `irreg_multiple_dual` (def at `inputgraph.py:852`), `num_expected_outputs = 20`.
  - Also `GPLAN\GPLAN\bdy.py:139`, `GPLAN\GPLAN\source\trial\bdy.py:138`,
    `GPLAN\GPLAN\source\lettershape\lshape\Lshaped.py:27,116`.
- The stage is gated: `inputgraph.py:255` and `inputgraph.py:710` and `inputgraph.py:915` run it only when
  `self.nodecnt - self.edgecnt + len(opr.get_trngls(self.matrix)) != 1`. `opr.get_trngls`
  (`GPLAN\GPLAN\source\graphoperations\operations.py:71-83`) counts every 3-clique, not faces, so the test
  is "number of 3-cycles differs from the number of interior faces predicted by Euler", i.e. extra
  non-facial 3-cycles exist.
- The detection helpers `get_sep_triangles_and_edges` (L1218) and `calc_all_triangles` (L1264) are NOT used by
  `handle_STs`; their only callers are the door-connectivity handlers and
  `remove_st_edge_selection` (`septri.py:503,520,525,636,653,658,855,872,877,993,1010,1015,1085,1102,1107,1327,1334,1339,1363,1414`).

## Entry Points (file:line)

- `GPLAN\GPLAN\source\irregular\septri.py:273` `handle_STs(adjacency, positions, num_expected_outputs)` - the
  only entry point of this scope reachable from `handlers.py`.
- `GPLAN\GPLAN\source\irregular\septri.py:1218` `get_sep_triangles_and_edges(all_triangles, num_nodes, origin_pos, adjacency)`
  - detection entry point used only by the door-connectivity family.
- `GPLAN\GPLAN\source\irregular\septri.py:1264` `calc_all_triangles(graph)` - triangle enumeration used only by the
  door-connectivity family.
- Internal, called only from `handle_STs`: `get_multiple_separating_edge_covers` (L197 called at L346),
  `remove_separating_triangles` (L221 called at L352), `point_in_triangle` (L37 called at L316),
  `get_edges` (L55 called at L325 and L335).

## Data Structures

Built in `handle_STs` at `septri.py:303-341`:

- `graph`: `nx.Graph` built from the adjacency matrix, every node carrying attribute `pos = positions[i]`
  (`septri.py:288-295`).
- `all_triangles`: list of sorted 3-element lists, every 3-clique of the graph (`septri.py:299-301`).
  Elements are `numpy` integers because of the `np.unique` round trip at L301.
- `trianlular_faces` (sic, L303, L324): triangles with no other node drawn inside them, treated as real faces.
- `separating_triangles` (L304, L333): list of `tuple(sorted(face))` for triangles that do have a node inside.
- `separating_edges` (L305, L336, deduped at L344): every edge belonging to at least one separating triangle,
  as `tuple(sorted((u, v)))`.
- `separating_edge_to_triangles` (L306, L338-341): `dict edge -> list of separating triangles containing it`.
  This is the incidence structure of the hitting-set problem.
- `edge_to_faces` (L307, L326-328): `dict edge -> list of facial triangles containing it` (1 or 2 entries).
  Used only by `remove_separating_triangles` for local re-triangulation; separating triangles are deliberately
  absent from it.
- `covers` (L346): list of `frozenset`s of edges, one per output floorplan.
- `extra_nodes` (`septri.py:237,244,271`): `dict new_vertex_label -> [endpoint0, endpoint1]` of the edge that was
  subdivided. This is the only record of the insertion returned to the caller.
- `extra_nodes_pair` (L349, L353): one `extra_nodes` dict per cover.

`get_edges(cycle)` (L55-64) returns the 3 edges of a 3-cycle as sorted tuples. Note the hard-coded `% 3`
at L64: it is only correct for cycles of length 3 even though it iterates `range(len(cycle))`.

## Algorithm Walkthrough

### 1. Triangle enumeration

`handle_STs` inlines the enumeration at `septri.py:299-301`; `calc_all_triangles` (L1264-1268) is the identical
three lines factored out for the door handlers. Both call `nx.enumerate_all_cliques(graph)`, materialise the
whole generator with `list(...)`, keep the cliques of size 3, sort each, and run `np.unique(..., axis=0)`.

Complexity as written: `enumerate_all_cliques` enumerates cliques of every size, which is exponential in the
worst case (O(n * 3^(n/3)) cliques for a general graph); the code pays for all of them and then throws away
everything that is not a triangle. On the planar triangulations this pipeline actually feeds it, cliques cap
at size 4 and the count is O(V), so real cost is roughly O(V) cliques plus O(T log T) for the sort inside
`np.unique`. The `sorted` plus `np.unique` dedup is redundant work: `enumerate_all_cliques` already yields
each clique exactly once, so no duplicates can exist. There is no early exit and no triangle-specific
enumeration (a neighbour-intersection scan would be O(E * sqrt(E))).

### 2. Separation test (geometric, not topological)

`handle_STs` at `septri.py:309-341`: for each triangle `face`, loop over every `NodeID` not in the face
(L311-312) and call `point_in_triangle` with the three vertex coordinates and the node coordinate
(L316-318). The first node found inside sets `flag = True` and breaks (L319-320). If no node is inside, the
triangle is recorded as a face in `edge_to_faces` (L322-328); otherwise it is recorded as a separating
triangle with all three of its edges (L330-341).

So the operational definition is: **a 3-clique is a separating triangle iff at least one other graph node's
drawn position lies strictly inside the drawn triangle**. It is a point-in-triangle test on `positions`, not a
connectivity or embedding-combinatorial test. Consequences:

- Correctness depends entirely on `positions` being a valid planar straight-line drawing of the same graph.
  Positions come from `trng.triangulate` (`inputgraph.py:228,681,899`), i.e. from the user-drawn coordinates
  carried through triangulation. If a node is inside the triangle in the drawing but not enclosed by it in the
  embedding (or the drawing has crossings), the classification is wrong in both directions.
- Cost is O(T * V) point tests on top of enumeration.
- A triangle bounding the outer face is also flagged, because every remaining node is geometrically inside it.
  That is intentional in effect rather than by accident: 4-completion (`news.add_news`, `inputgraph.py:299,759`)
  later adds four exterior vertices, so a triangle enclosing everything really does separate the graph in the
  4-completed instance. (Inference from pipeline order, not from a comment in `septri.py`.)

`point_in_triangle` (L37-53) computes the three orientation determinants via `sign` (L26-35) and returns
`not (has_neg and has_pos)` where `has_neg = any d < 1e-7` (L50) and `has_pos = any d > -1e-7` (L51). Because of
the epsilon, the function returns True only when all three determinants are at least `1e-7` in absolute value
and share a sign: points exactly on an edge, exactly at a vertex, or within ~1e-7 of an edge return False.
It is a strict-interior test with a tolerance band.

### 3. Building the cover problem

`get_multiple_separating_edge_covers` (L197) -> `get_separating_edge_cover` (L159) -> `generate_alternate_graph`
(L102) -> `get_graph_cover` (L140).

`generate_alternate_graph` (L102-138) builds an `nx.Graph` whose **nodes are separating edges** and whose
**edges tie together edges of the same separating triangle**:

1. `node_edges` seeds with every separating edge shared by more than one separating triangle (L117).
2. For each separating triangle (L119-129), count how many of its three edges are not yet in `node_edges`
   (L121). If all three are new, pick two at random (L123-126); if two are new, pick one at random
   (L127-128); otherwise add nothing. Net effect: every separating triangle ends up with at least two of its
   edges present as nodes of the alternate graph.
3. For each separating triangle (L131-136), take its edges that are in `node_edges` (L132). If all three are
   present, add the 3-cycle among them (L134); otherwise (exactly two) add the single edge between them (L136).

It is a hypergraph-cover reduction: the hypergraph is "triangles as hyperedges over separating edges", and
each hyperedge is approximated by an ordinary edge (or triangle) between two (or three) of its elements. A
vertex cover of the alternate graph hits at least one node per alternate edge, therefore at least one
separating edge per separating triangle.

`get_graph_cover(graph, cover)` (L140-157) computes a **vertex cover**, not an independent set and not an edge
cover, despite the docstring at L141 and L148 saying "edge cover": it repeatedly picks a random edge (L154),
removes both endpoints from the graph (L155), and appends both endpoints to `cover` (L156), recursing until no
edges remain (L151-152). That is the textbook maximal-matching 2-approximation for minimum vertex cover. It
mutates and destroys the alternate graph it is given, which is fine because the alternate graph is freshly
built per call at L175.

`get_separating_edge_cover` (L159-177) is now a thin wrapper: it ignores its `edge_cover` argument, builds a
fresh alternate graph (L175), returns `get_graph_cover(alternate_graph, [])` (L176-177). The original greedy
"pick the separating edge covering the most triangles, recurse" implementation is commented out at
L179-195. Because the live path never mutates `separating_triangles` / `separating_edges` /
`separating_edge_to_triangles`, the function is safe to call repeatedly on the same inputs, which is exactly
what the multi-cover loop needs.

Result: a list of separating edges such that every separating triangle has at least one of its edges in the
list. Because both endpoints of each matched alternate edge are taken, the cover is generally larger than
necessary: for an isolated separating triangle, two of its edges are selected where one would suffice, which
means two extra rooms instead of one.

### 4. Multiple covers

`get_multiple_separating_edge_covers(expected_count, ...)` (L197-219) loops while `len(covers) < expected_count`
(L211), converting each randomized cover to a `frozenset` and inserting it into a `set` (L212-215). Distinctness
comes purely from randomness in two places: the random choices of which triangle edges become alternate-graph
nodes (L124-128) and the random edge picked in `get_graph_cover` (L154). There is no systematic enumeration,
so a graph with few separating triangles simply cannot yield many distinct covers.

The stopping rule is a futility counter: it resets to 0 whenever a new cover is found (L214), breaks when
`futility_counter > expected_count/2` (L216-217), and increments once per iteration (L218). So the loop gives
up after roughly `expected_count/2 + 1` consecutive iterations that produced a duplicate. Consequences:
`len(covers)` can be less than `expected_count`; with `expected_count = 1` the loop runs exactly one iteration;
with `expected_count = 20` (`inputgraph.py:929`) it does at most about 11 wasted iterations before giving up.
When there are no separating triangles at all, `get_graph_cover` returns `[]` and the loop spins to the futility
break with a single empty cover.

### 5. Applying a cover

`handle_STs` L350-354: for each cover, copy the graph (L351), call `remove_separating_triangles` with the cover
and a `copy.deepcopy(edge_to_faces)` (L352) so covers do not corrupt each other, and collect the resulting
`extra_nodes` dict and mutated graph copy.

`remove_separating_triangles(graph, separating_edges, edge_to_faces)` (L221-271), per covering edge:

- L235 snapshots `pos` for all nodes once, before any bisection, so every midpoint uses original coordinates.
- L236 `total_no_of_vertices = graph.number_of_nodes()` is the label of the first new vertex; L270 increments it.
- L240 `graph.remove_edge(edge[0], edge[1])` destroys the 3-cycle, which is what kills the separating triangle.
- L241 midpoint position; L242 `graph.add_node(total_no_of_vertices, pos = position)` inserts the new vertex.
- L243 `graph.add_edges_from([(new, edge[0]), (new, edge[1])])` re-attaches both endpoints.
- L244 `extra_nodes[total_no_of_vertices] = [edge[0], edge[1]]` records the insertion. This dict is the only
  thing returned (L271).
- L247-250: for each **facial** triangle incident to the removed edge (1 for a boundary edge, 2 for an interior
  edge), find the opposite vertex (L249) and add `new -- other_vertex` (L250). This is the "new vertex inserted
  into the two faces adjacent to the removed edge" step: each old face becomes two faces and the graph stays
  triangulated. Separating triangles are not in `edge_to_faces`, so only genuine faces are split.
- L253-269: `edge_to_faces` bookkeeping. The old face is removed from the two surviving edges (L255-256), the two
  new faces are appended (L257-258), empty lists are created for the three edges incident to the new vertex if
  missing (L261-266), and the new faces are registered on them (L267-269). L267 assigns rather than appends, so
  the new vertex's edge to `other_vertex` is set to exactly `[new_triangle0, new_triangle1]`.

Nothing named `mergednodes`, `positions`, or `irreg_nodes` exists inside `septri.py`. Those arrays live in the
caller: `inputgraph.py:262-265` (single dual), `inputgraph.py:722-725` (`door_connectivity2`),
`inputgraph.py:942-945` (multiple dual) translate `extra_nodes` into
`mergednodes.append(new_vertex)`, `irreg_nodes1.append(extra_nodes[...][key][0])`,
`irreg_nodes2.append(extra_nodes[...][key][1])`.

`handle_STs` finally converts each mutated graph copy back to an integer adjacency matrix with
`nx.to_numpy_array(graph).astype(int)` (L356) and returns `(adjacencies, extra_nodes_pair)` (L357).

### 6. What the caller does with the results

- `inputgraph.py:258` / `718` / `935`: `self.matrix = ptpg_matrices[i]`, then `self.nodecnt` and `self.edgecnt`
  are recomputed from the matrix (`inputgraph.py:260-261,719-720,937-938`).
- `inputgraph.py:259,936`: `store_dummy_node_adjacencies(self.matrix)` (def at `inputgraph.py:1502`).
- `mergednodes` / `irreg_nodes1` flow into `rdg.construct_dual(self.matrix, self.nodecnt, self.mergednodes, self.irreg_nodes1)`
  at `inputgraph.py:313-315` and `773-775`. Note that `construct_dual`
  (`GPLAN\GPLAN\source\floorplangen\rdg.py:20-51`) accepts those two arguments and never uses them: its body only
  calls `dual.populate_t1_matrix`, `dual.populate_t2_matrix` and `get_dimensions` (rdg.py:43-51).
- The real consumers of the merge information are:
  - `opr.calculate_area` (`GPLAN\GPLAN\source\graphoperations\operations.py:260-284`): skips rooms whose index is in
    `mergednodes` (L276) and adds the merged room's area onto the irregular room (L279-282). Called at
    `inputgraph.py:843-845`.
  - `get_final_traversal` (`inputgraph.py:1580-1625`): merges the circular traversal of each merged node into the
    traversal of the corresponding `irreg_nodes1` room (L1591-1617), then emits only rooms that are neither
    merged nodes nor extra nodes (L1620-1622). This is where the L-shaped room is actually formed.
  - `generate_multiple_bdy` (`inputgraph.py:1453,1483`) takes `mergednodes, irreg_nodes1, irreg_nodes2` and returns
    them untouched: a pure pass-through.
- `irreg_nodes2` (the second endpoint) is stored (`inputgraph.py:265,725,945,1007`) but I found no consumer that
  reads it for geometry; see Open Questions.

### 7. `get_sep_triangles_and_edges` and `point_in_triangle2`

`get_sep_triangles_and_edges` (L1218-1260) is the same classification loop as `handle_STs` L309-341, refactored
into a function that returns the four structures (L1260), with three differences:

1. It calls `point_in_triangle2` (L1232-1234) instead of `point_in_triangle`, passing `NodeID`, `face` and
   `adjacency` in addition to the coordinates.
2. There is no `break` after `flag = True` (L1235-1236), so it scans all nodes for every triangle even after a
   hit. Same result, more work.
3. It dedups `separating_edges` itself at L1258 (in `handle_STs` this happens at the call site, L344).

`point_in_triangle2` (L1450-1472) differs from `point_in_triangle` in two ways:

- Exact comparisons `d < 0` / `d > 0` (L1463-1464) instead of the `1e-7` band, so degenerate cases go the other
  way: a node lying exactly on an edge or at a vertex of the triangle is treated as **inside** by
  `point_in_triangle2` and as **outside** by `point_in_triangle`.
- An extra adjacency gate at L1468: the candidate node must be adjacent to all three triangle vertices before
  the function returns True (L1469-1470). This restricts detection to "trivial" separating triangles whose
  interior node is joined to all three corners.
- The adjacency gate and the interior test are nested `if`s with no `else` (`septri.py:1468-1470`), but the
  function does end with an explicit `return False` at `septri.py:1472`, so every non-matching case returns
  `False`, not `None`. The function body spans `septri.py:1450-1472`, and 1472 is the last content line of the
  file (`wc -l` reports 1471 only because that line has no trailing newline). Both call sites use the result
  directly as an `if` condition (`septri.py:1232` and `septri.py:1422`), so the distinction does not change
  any downstream behaviour.

So they are not redundant copies: `point_in_triangle` implements "any node strictly inside" and
`point_in_triangle2` implements "an adjacent node inside or on the boundary". The duplicated `sign` computation
(L1460-1462 versus L47-49) is copy-paste, but the predicate semantics genuinely differ.

## Invariants And Preconditions

- `positions` must be a straight-line planar drawing of `adjacency` with the same index space; `handle_STs` reads
  `positions[i]` for every node index (`septri.py:291,316-318`) and never validates planarity.
- `adjacency` is assumed symmetric: the graph is built by scanning the full matrix (`septri.py:292-295`).
- New vertex labels are consecutive integers starting at `graph.number_of_nodes()` (`septri.py:236,242,270`), and
  since `networkx` iterates nodes in insertion order, `nx.to_numpy_array` (L356) yields a matrix where row index
  equals node label. Callers rely on this when they use `key` from `extra_nodes` directly as a room index
  (`inputgraph.py:263,723,943`).
- `edge_to_faces` contains only non-separating triangles (`septri.py:322-328`), so the re-triangulation loop at
  L247 never tries to preserve a separating triangle.
- Every cover edge is an edge of the current graph and appears in `edge_to_faces` for at least one face;
  `remove_separating_triangles` would raise `KeyError` at L247 or `NetworkXError` at L240 otherwise.
- Each cover is applied to a fresh graph copy and a deep copy of `edge_to_faces` (`septri.py:351-352`), so the
  covers are independent.
- `get_separating_edge_cover` does not mutate its inputs, which is what makes repeated sampling in
  `get_multiple_separating_edge_covers` (L211-218) legitimate.
- `generate_alternate_graph` guarantees every separating triangle contributes at least two nodes to the alternate
  graph (L119-129), so `relevant_edges` at L132 always has length 2 or 3 and L136 never indexes out of range.

## Failure Modes

- **Coordinate dependence.** A drawing with edge crossings or degenerate (collinear) triples makes the
  point-in-triangle classification wrong, and there is no check. `septri.py` imports `check_intersection`
  (L20) and uses it only inside the door-connectivity handlers (L515, L648, L867, L1005, L1097), never in
  `handle_STs`.
- **Near-boundary nodes are missed.** The `1e-7` band at `septri.py:50-51` makes a node lying within `1e-7` of a
  triangle edge count as outside, so that separating triangle is silently treated as a face and lands in
  `edge_to_faces`. Downstream, the dual construction then fails or produces an invalid floorplan rather than
  reporting a separating triangle.
- **Over-removal.** The 2-approximation vertex cover (`septri.py:154-156`) adds both endpoints of every matched
  alternate edge, so more edges are bisected than needed and more irregular rooms are produced than necessary.
- **Fewer outputs than requested.** `get_multiple_separating_edge_covers` can return fewer than
  `expected_count` covers because of the futility break at L216-217; `irreg_multiple_dual` asks for 20
  (`inputgraph.py:929`) and iterates over `len(ptpg_matrices)` (`inputgraph.py:932`), so it tolerates this.
- **Recursion depth.** `get_graph_cover` recurses once per matched edge (L157). With a very large alternate graph
  this can hit Python's recursion limit; the loop is trivially tail-recursive and could be a `while`.
- **Stale positions.** `handle_STs` gives the new vertices a `pos` inside the graph copy (L242) but returns only
  adjacency matrices and `extra_nodes` (L357). The caller's `positions` list keeps its old length. Anything that
  wanted coordinates after this stage would be one-to-one wrong; in practice `inputgraph.py` does not read
  `positions` again after L257 / L715 / L929 in those code paths.
- **Full clique enumeration.** `nx.enumerate_all_cliques` is materialised with `list()` at L299 and L1265; on a
  dense or non-planar input (which can reach here if triangulation misbehaves) this is exponential in time and
  memory with no guard.
- **Empty-cover churn.** If detection finds nothing, the Euler gate at `inputgraph.py:255` was still satisfied
  by something else, and the module spends the futility loop producing a single empty cover and then copies the
  graph for nothing (L351-354).

## Coupling (what breaks if you change this)

- **`extra_nodes` shape.** `dict new_label -> [endpoint0, endpoint1]` is unpacked positionally at
  `inputgraph.py:263-265`, `722-725`, `942-945`. Changing it to, say, a tuple of three items or reordering the
  endpoints silently swaps which room becomes L-shaped (`irreg_nodes1` is the absorber, see
  `inputgraph.py:1591` and `operations.py:279-282`).
- **Return arity.** `handle_STs` returns 2 values (`septri.py:357`) while the door-connectivity variants return 3
  (positions included, e.g. `inputgraph.py:437,440`). Adding positions to `handle_STs` breaks all six call sites
  listed above, including `bdy.py:139`, `trial/bdy.py:138` and `Lshaped.py:27,116`.
- **Node-label = matrix-index identity.** Any change to how new vertices are labelled or how the matrix is
  materialised (L356) breaks `mergednodes` indexing in `operations.calculate_area` and
  `inputgraph.get_final_traversal`.
- **`edge_to_faces` semantics.** `remove_separating_triangles` assumes entries are lists of triangles that are
  faces, mutable in place, and deep-copyable. `handle_STs` stores lists (`septri.py:328`) while
  `handle_non_trivial_ST_Door_connectivity` stores tuples (`septri.py:400`); a shared helper would have to pick one.
- **`point_in_triangle` epsilon.** Loosening or tightening L50-51 changes which triangles are classified as
  faces, which changes `edge_to_faces`, which changes the re-triangulation in `remove_separating_triangles`.
  It is also used by the door handlers (`septri.py:388` and the equivalent loops in the other handlers), so a
  change there is cross-scope.
- **`get_edges` `% 3`.** Hard-coded at L64; reusing this helper for longer cycles would produce wrong edges.

## Dead Or Duplicated Code

- `add_edge_to_cover` (L66-100) is **dead**. Its only reference in the repository is inside the commented-out
  greedy block at `septri.py:192`. Nothing else calls it (verified by repo-wide grep of `*.py` under
  `GPLAN\GPLAN`).
- The greedy cover implementation at `septri.py:179-195` is commented out; the live `get_separating_edge_cover`
  returns at L177 before any of it, and the `edge_cover` parameter (L159) is unused.
- The docstrings at L13, L141 and L148 call `get_graph_cover` an "edge cover"; the code computes a vertex cover
  of the alternate graph (L154-156). The module docstring at L16 is accurate about bisection.
- `handle_STs` duplicates `calc_all_triangles` inline (L299-301 versus L1264-1268) and duplicates the whole
  classification loop of `get_sep_triangles_and_edges` (L309-341 versus L1225-1257), which is duplicated again
  in `handle_non_trivial_ST_Door_connectivity` (L370-413).
- `from shapely.geometry import Point, Polygon` (L23) is unused anywhere in this file (grep for `Polygon` and
  `Point(` finds only the import).
- `GPLAN\GPLAN\source\irregular\septri_non_adj.py` carries near-identical copies of `calc_all_triangles` (L52)
  and `get_sep_triangles_and_edges` (L58), imported as `st_non_adj` at `inputgraph.py:42`.
- `handle_STs_with_edge_selection` (`septri.py:1378`) is commented out at every call site
  (`inputgraph.py:439,532,712`); it is the only other consumer of `calc_all_triangles`/`point_in_triangle2` in
  this file besides the live door handlers.
- `trianlular_faces` (`septri.py:303,324`) is populated and never read; only `edge_to_faces` matters.
  `triangular_faces` in `get_sep_triangles_and_edges` (L1219,1240) is likewise never returned (L1260).
- `GPLAN\GPLAN\bdy.py:139` and `GPLAN\GPLAN\source\trial\bdy.py:138` are separate copies of a boundary pipeline
  that also call `handle_STs`; `source\trial\` looks like a scratch copy.

## Open Questions

- `irreg_nodes2` (the second endpoint of each bisected edge) is recorded at `inputgraph.py:265,725,945` and
  passed around (`inputgraph.py:1007,1483`) but I found no code that reads it to place or size geometry. Is it
  vestigial, or is it consumed in a module I did not scan (dimensioning, GUI)?
- The outer-face triangle is always flagged as separating by the geometric test. I argued above that this is
  benign because 4-completion adds exterior vertices afterwards, but nothing in `septri.py` states this, and I
  did not find a test that pins the behaviour. Worth confirming against a K4 input.
- `handle_STs` never re-checks that the output is separating-triangle free. Bisection plus local
  re-triangulation should not create a new separating triangle (the new vertex has degree 3 or 4 and sits on a
  former edge), but there is no assertion and no second pass. Is there a case, for example a cover edge whose
  two faces share the opposite vertex, where a new separating triangle appears?
- `remove_separating_triangles` deep-copies `edge_to_faces` per cover (L352) but reads `origin_pos` once
  (L235) from the copied graph; if a future cover contained an edge incident to a previously inserted vertex,
  `origin_pos` would lack that vertex. Today covers contain only original edges, so this is latent, not a bug.
- Knowledge-graph disagreement (minor): `graphify explain "handle_STs()"` lists only
  `Lshaped.py:27` and `Lshaped.py:116` as callers and misses `inputgraph.py:256`, `714` and `929`, which are the
  paths actually reachable from `handlers.py`. Source wins; the graph's caller edges for this node are incomplete.
