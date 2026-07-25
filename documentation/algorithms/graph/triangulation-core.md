# Triangulation Core (triangularity / triangularity_non_adj / earclipping / operations)

All paths below are absolute. Every line number cited was read in this session.

Files under study:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\graphoperations\triangularity.py` (13441 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\graphoperations\triangularity_non_adj.py` (18667 bytes, i.e. 5226 bytes larger)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\graphoperations\earclipping.py` (7885 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\graphoperations\operations.py` (10665 bytes)

---

## Purpose

Turn a biconnected planar input graph into a maximal planar (fully triangulated) graph by adding chord edges inside every non-triangular interior face, and report those added edges back to the caller so that downstream stages can distinguish "real adjacency the user asked for" from "adjacency the algorithm invented".

The module does **not** mutate the adjacency matrix. `triangulate` returns `(tri_edges, positions, tri_faces)`; the caller (`inputgraph.py`) is the one that writes the edges into `self.matrix` and bumps `self.edgecnt`.

Two variants exist:

- `triangularity.py`: unconstrained, delegates the actual polygon triangulation to `earclipping.py`.
- `triangularity_non_adj.py`: takes an extra `non_adj_list` of forbidden pairs, and does **not** use `earclipping` at all (it imports it and never calls it). It has its own shapely-based diagonal insertion loop.

---

## Where It Sits In The Pipeline

Both variants sit between biconnectivity augmentation and separating-triangle handling, in every `InputGraph` entry point:

| Entry point | biconnectivity | triangulation call | next stage |
|---|---|---|---|
| `irreg_single_dual` | `inputgraph.py:218-225` | `inputgraph.py:228-230` (`trng.triangulate`) | edge-to-vertex transform `:240-252`, then ST elimination `:255-257` |
| `door_connectivity` | `inputgraph.py:365-381` | `inputgraph.py:384-392` (`trng_non_adj` or `trng`) | ST handling `:436-440`; re-triangulation on non-planar embedding `:474-488` |
| `door_connectivity2` | `inputgraph.py:671-678` | `inputgraph.py:681-683` | ST elimination `:710-715` (edge-to-vertex transform is commented out at `:694-707`) |
| `irreg_multiple_dual` | ends `inputgraph.py:893-895` | `inputgraph.py:899-901` | transform `:917-928` / `:1021-1032` (into a local `extranodes` list, `:916` / `:1020`), ST handling `:929` |

Reachability from the real entry points:

- `GPLAN\GPLAN\api.py:1309`, `:1353`, `:1390` call `handle_door_connectivity(ui, graph)`.
- `GPLAN\GPLAN\handlers.py:1686` defines it; `:1710` calls `graph.door_connectivity(show_graph=drawGUI, non_adj_list=non_adj_list)` when `ui.get_isNonAdj() == 1` (`handlers.py:1703`), otherwise `:1732` calls `graph.door_connectivity(show_graph=drawGUI)`.
- The non-adjacency flag comes from the API surface at `api.py:1302` / `api.py:1329` (`ui.set_isNonAdj(nonAdj)`), so **`triangularity_non_adj.py` is live from `api.py`**, not dead.
- `handlers.py:561` calls `graph.irreg_single_dual()`; `handlers.py:361/363/615` call `graph.irreg_multiple_dual()`.

---

## Entry Points (file:line)

`triangularity.py`

- `:28` `atan2(x, y)` - quadrant-aware angle, returns 0 for the (0,0) case (`:48-49`).
- `:51` `get_new_coordinates(nbr_dict, src)` - translate neighbours to `src` then convert to angle.
- `:77` `get_faces(edges, embedding)` - **hand-written face walk** (see below).
- `:122` `find_face_node(face)` - `[edge[0] for edge in face]`.
- `:137` `get_nontriangular_face(positions, G)` - builds the rotation system and filters faces.
- `:184` `get_tri_edges(non_tri_faces, positions)` - runs ear clipping, collects chords.
- `:227` `get_faces_after_triangulation(tri_edges, nxgraph, positions)` - re-walks faces of the augmented graph, keeps only length-3 ones.
- `:254` `triangulate(matrix, bcn_edges_added, pos)` - **the public entry point**; returns `(tri_edges, positions, tri_faces)` at `:283`.

`triangularity_non_adj.py`

- `:82` `check_if_present(list_of_tuples, list_of_list_of_tuples)` - frozenset-based "is this face already known".
- `:93` `get_faces` - superset of the plain version, extra chord-face discovery at `:139-172`.
- `:266` `get_tri_edges(non_tri_faces, positions, non_adj_list)` - own diagonal insertion, no ear clipping.
- `:430` `triangulate(matrix, bcn_edges_added, pos, non_adj_list)` - public entry point; returns at `:474`.

`earclipping.py`

- `:9` `Node`, `:24` `DoubleLinkedList` (circular, `append :48`, `remove :62`, `count :86`, `flatten :96`).
- `:108` `angleCCW(a, b)` - **never called anywhere in the repo**.
- `:119` `polygon_area(vertices)` - `abs(shoelace)/2`.
- `:128` `isConvex(vertices, vert_prev, vert_crnt, vert_next)` - area-difference test, not an angle test.
- `:143` `area(x1,y1,x2,y2,x3,y3)` - triangle area.
- `:147` `insideTriangle(a, b, c, p)` - sum-of-sub-areas point-in-triangle.
- `:176` `triangulate(vertices, max_iterations=0)` - the ear-clipping driver.

`operations.py` - see the function table under "Coupling".

---

## Data Structures

- **`positions`**: `dict {node_index: coordinate}`. Built at `triangularity.py:271` from the caller's `pos` list, or replaced by `nx.planar_layout(nxgraph)` at `:275` / `:277`.
- **embedding / rotation system**: `nodes_ordered_nbr = {node: [nbr...]}` built at `triangularity.py:150-156`, neighbours sorted by descending polar angle around the node.
- **`face`**: a Python `list` of *directed* edge tuples `[(v0,v1),(v1,v2),...,(vk,v0)]`. `find_face_node` (`:122-135`) recovers the vertex cycle as `face[i][0]`, so `face[i] == (face_vertices[i], face_vertices[i+1])`.
- **`tri_edges` / `trng_edges`**: flat `list` of `(u, v)` tuples, undirected in intent, de-duplicated only against the *current face* and against itself (`triangularity.py:210-224`).
- **`tri_faces`**: list of length-3 faces of the augmented graph, used later by `transformation.transform_edges`.
- `earclipping.triangulate` returns an `np.int64` array of shape `(k, 3)` holding **indices into the face's vertex list**, not node ids (`earclipping.py:185`, `:232`, `:249`).

---

## Algorithm Walkthrough

### 1. How faces are obtained (Q1)

**Own face-walking code, driven by coordinate geometry. Neither `networkx.PlanarEmbedding` nor `nx.check_planarity` is used to get faces.**

1. `triangularity.py:150-156` builds the combinatorial embedding from coordinates: for each node, collect neighbour coordinates (`:152`), translate + convert to angle via `get_new_coordinates` (`:153` -> `:66-75` -> `atan2` `:28-49`), sort descending by angle (`:154`).
2. `triangularity.py:157` calls `get_faces(G.edges, nodes_ordered_nbr)`.
3. `get_faces` (`:93-120`) doubles every edge into both directions (`:94-96`), then repeatedly follows the "next neighbour in rotation order" rule: `neighbors[(neighbors.index(path[-1][-2])+1) % len(neighbors)]` at `:106-107`, closing a face when the produced tuple equals `path[0]` (`:109-111`). Source is credited in the docstring at `:80-81` (a MathOverflow answer, not networkx).

**Yes, triangulation depends on the user-supplied `node_coordinates`, conditionally:**

- `InputGraph.__init__` stores them at `inputgraph.py:143` (`self.coordinates = [np.array(x) for x in node_coordinates]`), and replaces them wholesale with `nx.planar_layout` if the drawing has edge crossings (`inputgraph.py:159-164`).
- They are passed in at `inputgraph.py:230` / `:387` / `:392` / `:683` / `:901`.
- `triangularity.py:270-271`: if biconnectivity added **no** edges, the user coordinates are used directly.
- `triangularity.py:276-277`: if biconnectivity **did** add edges, the user coordinates are discarded and `nx.planar_layout(nxgraph)` is used instead. So the same input graph can be triangulated from two completely different embeddings depending on whether it was already biconnected.

**What breaks if two rooms have identical coordinates:**

- `get_new_coordinates` yields `(0, 0)` for a neighbour that coincides with the origin node, and `atan2(0,0)` falls through to the `else` at `triangularity.py:48-49` returning `0`. Two coincident neighbours therefore tie at the same angle; `sorted` is stable, so the tie is broken by adjacency insertion order, which is unrelated to the true planar rotation. The "embedding" fed to `get_faces` is then not a valid rotation system and the walk at `:105-119` emits sequences that are not faces.
- The all-identical case is guarded: `triangularity.py:272-275` replaces `positions` with `nx.planar_layout` only when `len(unique_coords) <= 1`. **Two** identical coordinates out of N does not trip this guard.
- The outer-face detector uses `mplPath.Path(np.array(face_coordinates))` (`:168`) and point containment (`:169`, `:174`). With coincident vertices the polygon is degenerate and containment is unreliable, so the outer face can be misclassified as interior and get triangulated.
- `get_tri_edges` bails out only when **every** vertex of the face shares one coordinate (`:202-204`), not on partial duplicates.
- `earclipping.isConvex` removes vertices by **coordinate equality**, not by index (`earclipping.py:132-136`), so with duplicated points it deletes more than one vertex and the area comparison at `:140` is meaningless.

Net effect of a duplicate coordinate pair: wrong faces, possibly a triangulated outer face, spurious chords, and a graph that still fails the Euler check at `inputgraph.py:255` / `:915`.

### 2. Non-triangular interior face -> ear clipping (Q2)

**Yes, `earclipping.py` is the implementation for `triangularity.py`, and it runs on the polygon of face vertices in coordinate space.**

- `triangularity.py:199-201` maps the face's vertex cycle to an `np.array` of coordinates.
- `triangularity.py:205`: `triangles = ec.triangulate(face_coordinates, 0)`. The second argument is `max_iterations`; `0` means unlimited (`earclipping.py:202` tests `max_iterations<=0`).

Ear test, step by step:

1. `earclipping.py:189-191`: a circular doubly linked list holds the vertex **indices** `0..n-1`.
2. `earclipping.py:202`: loop while more than 2 vertices remain.
3. `earclipping.py:205-211`: `i = prev`, `j = current`, `k = next`, and their coordinates.
4. **Convexity test is an AREA test, not an angle test.** `earclipping.py:213` calls `isConvex` (`:128-140`): it computes `polygon_area(vertices)` (`:130`), builds `new_vertices` by dropping every vertex whose coordinates equal `vert_crnt` (`:132-136`), computes `new_area` (`:139`), and returns `original_area - new_area >= -1e-7` (`:140`). Rationale: clipping a convex vertex shrinks the polygon; clipping a reflex vertex grows it. `polygon_area` (`:119-126`) is `abs(shoelace)/2`, so orientation is discarded.
   - `angleCCW` at `:108-117` is the *only* genuinely angular routine here and it is never called (see Dead Code).
5. **Point-in-triangle test**: `earclipping.py:216-220`. Walk `test_node` from `node.next.next` up to (excluding) `node.prev`, and for each such vertex call `insideTriangle(vert_prev, vert_crnt, vert_next, vert)` (`:219`). `insideTriangle` (`:147-174`) computes the triangle area `A` and the three sub-areas `A1, A2, A3` via `area` (`:143-145`) and declares the point inside when `abs(A - Total) < 1e-9` (`:171`). Any contained vertex sets `is_ear = False`.
6. **Zero-area ear handling**: `earclipping.py:223-230`. A collinear (zero-area) ear is rejected unless a full sweep has already failed (`stall_counter <= vertlist.size` at `:229`).
7. **Emit**: `earclipping.py:231-235` writes `[i, j, k]` into `indices` and removes `j` from the list.
8. **Forced progress**: `earclipping.py:236-245`. If a full sweep found no clippable ear, the current vertex is dropped **without emitting a triangle** so the loop terminates. This silently under-triangulates degenerate polygons.
9. `earclipping.py:249` trims `indices` to `index_counter` rows.

### 3. Exactly which edges are added, and where they are recorded (Q3)

`triangularity.py:206-224`. For each returned triangle, the three index positions are mapped back to node ids (`:207-209`). Then each of the three pairs `(v1,v2)`, `(v2,v3)`, `(v1,v3)` is appended to `tri_edges` **only if**:

- the pair is not already an edge of *this face*, in either direction (`:210-211`, `:215-216`, `:220-221`), and
- the pair is not already in `tri_edges`, in either direction (`:212-213`, `:217-218`, `:222-223`).

So only chords/diagonals of the face are recorded; the face's own boundary edges are filtered out. Note the membership test is against `face`, **not against the whole graph** - an already-existing graph edge that is not on this face would be re-added.

`tri_edges` is returned at `:225`, and surfaces as the first element of `triangulate`'s return at `:283`.

Consumption in `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py` (grep for `trng_edges`):

- Received at `:228`, `:385`, `:390`, `:477`, `:481`, `:681`, `:899`.
- Written into the adjacency matrix and counted: `:231-234`, `:394-397`, `:485-488`, `:685-688`, `:902-905`.
- Flag the floorplan as non-rectangular: `:236-237`, `:400-401`, `:691-692`, `:907-908`.
- **Edge-to-vertex transformation** (this is what makes them non-wall adjacencies): `:247-252` and `:923-928` / `:1027-1032`. Each `trng_edge` becomes a brand new dummy node wired in by `transformation.transform_edges` (`GPLAN\GPLAN\source\floorplangen\transformation.py:13-41`, matrix rewire at `:50-59`). Where the new node id is recorded differs by path:
  - `irreg_single_dual` appends directly to the instance attribute: `self.extranodes.append(self.nodecnt)` at `:241` (biconnectivity edges) and `:248` (triangulation edges). These are the only two `self.extranodes.append` sites in the file.
  - `irreg_multiple_dual` appends to a **local** list declared as `extranodes = []` at `:916` and again at `:1020`, filled at `:918` / `:924` and `:1022` / `:1028`. That local list is later attached to each generated child graph: `new_graph.extranodes = extranodes` at `:1008` and `:1093`. So the parent `InputGraph`'s own `self.extranodes` is not what the transform writes to on this path.

  Either way the recorded nodes are skipped when drawing rooms (`GPLAN\GPLAN\pythongui\drawing.py:210`, `:238`, `:262`), skipped in area accounting (`operations.py:276`), and exported to the client (`handlers.py:467`).
- Passed to `generate_multiple_bdy` at `:947` and `:1034` - but see Dead Code, that parameter is ignored.

**Important asymmetry**: `door_connectivity` (`inputgraph.py:340-520`) does **not** run the edge-to-vertex transformation at all. Instead, after ST handling, it diffs the original against the final matrix and records every newly-1 entry into `self.extraedges` (`:512-516`). `update_gclass_with_edges` (`:316-337`) then colours those edges `'red'` (`:331-332`). So on the door-connectivity path the triangulation chords stay as real graph edges and are only *marked*, not converted into corridor nodes. In `door_connectivity2` the transform is present but commented out (`:694-707`).

### 4. Outer face: deliberately left alone (Q4)

Yes, deliberately excluded, by two mechanisms in `get_nontriangular_face`:

1. `triangularity.py:160`: only faces with more than 3 edges are candidates. A triangular outer face is never touched.
2. `triangularity.py:162-181` is the explicit outer-boundary discriminator. For each candidate face it builds `mplPath.Path` from the face's vertex coordinates (`:168`) and marks the face as outer if either:
   - some graph node that is not a face vertex lies inside that polygon (`:169-171`), or
   - some chord between two face vertices (an edge of `G` that is not an edge of the face) has its midpoint inside the polygon (`:172-176`).

   Faces flagged this way are collected into `outer_face` (`:179-180`) and subtracted at `:181`.

   The logic is the inversion of the usual one: for a genuine interior face nothing else lies inside it, whereas the outer face's vertex walk traces the convex-ish outer boundary and therefore contains the rest of the drawing.

3. Special case at `triangularity.py:158-159`: if the graph has exactly 2 faces (a pure cycle), it keeps `faces[0]` arbitrarily. This is safe only because the two faces of a cycle are the same vertex sequence with opposite orientation, and both `isConvex` (via `abs` area) and `insideTriangle` are orientation-insensitive, so the same chords result either way.

The same block is byte-identical in `triangularity_non_adj.py:213-236`.

### 5. triangularity vs triangularity_non_adj (Q5)

**Duplicated verbatim (or trivially so):**

| Function | plain | non_adj | status |
|---|---|---|---|
| `atan2` | `:28-49` | `:33-54` | identical |
| `get_new_coordinates` | `:51-75` | `:56-80` | identical |
| `find_face_node` | `:122-135` | `:176-190` | identical apart from a blank line |
| `get_nontriangular_face` | `:137-182` | `:192-237` | identical |
| `get_faces_after_triangulation` | `:227-251` | `:240-264` | identical body, **but dead in the non_adj module** (nothing calls it there; `triangulate` uses `nx.chordless_cycles` at `:464` instead) |

**Genuinely different:**

- `check_if_present` (`triangularity_non_adj.py:82-90`) - non_adj only.
- `get_faces`: the first half (`non_adj :109-136`) matches `plain :93-119`, but `non_adj :139-172` adds a second pass that, for every pair of face vertices joined by a graph edge that is *not* a face edge (a chord), walks a sub-cycle restricted to the face's vertices (`:158`) and appends it as an additional face if it is new (`:162-165`). This exists because the non_adj `get_tri_edges` mutates faces in place and needs the chord-induced sub-faces to be present.
- `get_tri_edges`: completely different implementation. Plain version = ear clipping (`plain :198-224`). Non_adj version (`:266-427`) never touches `earclipping`; it scans consecutive triples `(a, b, c)` of the face's vertex cycle (`:302-305`) and tests whether `a-c` is a legal diagonal using **shapely**: build `LineString([a, c])`, intersect it with the polygon exterior (`:318-321`), classify the intersection geometry (`:322-336`), and accept when `len(inter_points) <= 2 and bbPath.contains_point(midpoint) and polygon.contains(Point(midpoint))` (`:348`). Collinear triples are skipped by a cross-product test at `:344`.
- `triangulate`: signature gains `non_adj_list` (`:430`), prints it (`:446`), **unconditionally draws and blocks on `plt.show()` (`:456-457`)**, and builds `tri_faces` from `nx.chordless_cycles` (`:464-472`) rather than re-walking faces.

**How `non_adj_list` changes the chosen diagonal:** the guard is at `triangularity_non_adj.py:349-351`. Once a diagonal `(a, c)` has passed the geometric legality test, if `(a, c)` or `(c, a)` appears in `non_adj_list` the candidate is skipped (`i += 1; continue`) and the scan advances to the next consecutive triple. There is no cost model or preference ordering: the *first* geometrically legal, non-forbidden diagonal in cycle order is taken (`:353-359`), and after insertion `i` resets to 0 so scanning restarts from the beginning of the (now shorter) face.

**When every legal diagonal is forbidden**, there are two distinct outcomes:

1. **No diagonal at all was added for the face** (`edge_added` still `False`, `:354` never reached): the fallback at `:367-425` re-runs the *identical* scan with the `non_adj_list` check removed (compare `:348-359` with `:415-421`). The non-adjacency constraint is therefore **best-effort, not a hard constraint** - it is silently abandoned wholesale for that face.
2. **Some diagonals were added, then the remainder are all forbidden**: `edge_added` is `True`, so the `not edge_added` condition at `:367` is false and the fallback never runs. The face is left with more than 3 vertices, i.e. **the graph is left non-triangulated with no error and no warning**. The author was aware: line `:366` is a commented-out `#if len(face_vertices) > 3:` that would have covered this case. Downstream, `inputgraph.py` either fails the Euler identity at `:255` / `:915`, or `check_ptpg` at `inputgraph.py:413-424` returns `False` and `handle_door_connectivity` propagates a non-PTPG result.

---

## Invariants And Preconditions

1. `positions` must be a dict keyed by every node index of the graph; `triangularity.py:271` builds it as `{i: pos[i] for i in range(len(pos))}`, so `len(pos)` must equal the node count.
2. The angular sort at `:150-156` must produce a genuine rotation system for `get_faces` to emit real faces. This holds only if the coordinates are a straight-line planar drawing with **distinct** node positions.
3. `find_face_node` assumes the face is a consistently oriented directed cycle: `face[i] == (face_vertices[i], face_vertices[i+1])`. `triangularity_non_adj.get_tri_edges.add_edge` (`:288-298`) relies on this when it does `face.remove((a,b))` / `face.remove((b,c))` / `face.insert(i, (a,c))`.
4. `earclipping.triangulate` presumes a simple, closed, non-self-crossing polygon (docstring `:178-181`). It preallocates exactly `n-2` triangle slots (`:185`); the invariant that holds is "each emitted triangle removes exactly one vertex", so at most `n-2` are ever emitted.
5. `tri_edges` must not contain an edge already present in the matrix, otherwise `self.edgecnt` drifts: `inputgraph.py:231-234` unconditionally increments per edge while `self.matrix[...] = 1` is idempotent.
6. `transform_edges` requires `tri_faces` to contain, for every added edge, the 1 or 2 triangles incident to it (`transformation.py:25`, `:38-41`); the 2-vs-1 count decides whether 2 or 3 edges were added.
7. `get_bdy` (`operations.py:85-115`) presumes a maximal planar graph: it identifies boundary edges as exactly those contained in one triangle (`:107`). Under-triangulation breaks it.

---

## Failure Modes

- **`triangularity_non_adj.triangulate` calls `plt.show()` unconditionally at `:457`.** In a headless/server context (`api.py` -> `handlers.py:1710`) this either raises or blocks the request thread. This is the single worst defect in the non-adjacency path. The plain module has the equivalent draw call commented out (`triangularity.py:278`).
- `triangularity.py:280` prints the whole `non_tri_faces` list to stdout on every call; `triangularity_non_adj.py:446` prints the non-adjacency list. Noise on every API request.
- **Under-triangulation without error.** `earclipping.py:236-245` drops a vertex without emitting a triangle when a full sweep finds no ear; `triangularity_non_adj.py:367` skips the fallback when at least one edge was added. Both leave a non-triangular face and no signal.
- **Stale convexity test.** `earclipping.py:213` passes the **original, full** `vertices` array to `isConvex` on every iteration, never the shrinking remaining polygon, and `isConvex` removes vertices by coordinate match rather than by index (`:132-136`). After the first clip the convexity verdict no longer describes the current polygon, so ears can be misjudged on concave polygons with n > 4.
- **Coordinate-dependence.** With `bcn_edges_added == True` the user's coordinates are thrown away for `nx.planar_layout` (`triangularity.py:277`), so which chords get added is not under the caller's control on that path.
- **Duplicate coordinates** break the rotation-system sort (`:154`), the outer-face containment test (`:168-176`), and `isConvex`'s vertex removal (`earclipping.py:132-136`). The degenerate guard at `:273-275` only covers the all-identical case.
- `DoubleLinkedList.remove` has a duplicated conditional at `earclipping.py:80-83`: the second `if rmv == self.first` re-tests against the just-updated `self.first`, setting `self.first = None` in the single-element case. Reachable only when the list shrinks to one element, which the `size > 2` loop guard prevents, but it is clearly a copy-paste artefact.
- `triangularity_non_adj.get_tri_edges` mutates `face` in place (`:291-294`), and `face` is an element of `non_tri_faces`, which came from `get_faces`. Callers holding those lists see them change under them.
- `flag` in `triangularity_non_adj.py:338-342` and `:405-409` compares a coordinate tuple against a `shapely.Point`, which is always unequal, and then the variable is never read. Dead computation.
- `triangularity.py:210-224` de-duplicates only against the current face, so an edge already present elsewhere in the graph can be emitted again, inflating `edgecnt` at `inputgraph.py:234`.

---

## Coupling (what breaks if you change this)

Changing the return shape of `triangulate` breaks `inputgraph.py:228`, `:385`, `:390`, `:477`, `:481`, `:681`, `:899`, plus `GPLAN\GPLAN\bdy.py:10`, `GPLAN\GPLAN\source\trial\bdy.py:10` and `GPLAN\GPLAN\source\ptpg_floorplanner.py:57` which import the module.

Changing the `tri_faces` structure breaks `transformation.transform_edges` (`transformation.py:25`, `:34-37`, `:61-63`).

Changing whether triangulation chords become `extranodes` changes the rendered floorplan: `drawing.py:210`, `:238`, `:262` and `operations.py:276` all skip `extranodes`.

`operations.py` function inventory, one line each, with importers (grep of `*.py` under `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN`):

| Function | Line | Role | Imported / called by |
|---|---|---|---|
| `intersection` | `:29` | list intersection preserving lst1 order | **only `list_comparer` at `operations.py:55`** - no external caller |
| `list_comparer` | `:42` | is there an element of lst2 whose intersection with lst1 has the given size | **nothing. Dead.** |
| `get_directed` | `:59` | `nx.DiGraph` from an adjacency matrix | `inputgraph.py:269,549,729,1470`; `bdy.py:151`; `trial/bdy.py:149`; `staircaseshape.py:39,115,136`; `multiple_ptpg.py:128`; `ptpg_floorplanner.py:230`; `tshape.py:38,66,122,142`; `zshape.py:38,66,122,142`; `canonicalTransition.py:60,85`; `Lshaped.py:86,198,241,260,312,547,608` |
| `get_trngls` | `:71` | all 3-cliques (triangular cycles) | `inputgraph.py:255,268,293,530,548,573,710,728,753,915,1469`; `bdy.py:138,150,175`; `trial/bdy.py:137,148,173`; `staircaseshape.py:38,114,135`; `multiple_ptpg.py:128`; `ptpg_floorplanner.py:229`; `tshape.py:37,65,121,141`; `zshape.py:37,65,121,141`; `canonicalTransition.py:59,84`; `Lshaped.py:26,85,115,238,311,546,607` |
| `get_bdy` | `:85` | boundary nodes/edges = directed edges lying in exactly one triangle | same set as `get_directed` (`inputgraph.py:270,550,730,1471`, `bdy.py:152`, `multiple_ptpg.py:117,128,162`, etc.) |
| `ordered_nbr_label` | `:117` | returns (2 or 3) label plus the next ordered neighbour | `floorplangen/expansion.py:218,312,360,439,471`; `floorplangen/flippable.py:130` |
| `ordered_nbr` | `:137` | next neighbour in the ordered ring around a vertex | `floorplangen/expansion.py:408`; `floorplangen/flippable.py:158,165,172` |
| `order_nbrs` | `:153` | full ordered neighbour ring around a vertex from a labelled REL matrix | `floorplangen/dual.py:124,220`; `floorplangen/expansion.py:90` |
| `get_encoded_matrix` | `:211` | rasterise room rectangles into a pixel-grid label matrix | `handlers.py:5` (import) then `:381,810,1233,1385,1873,1983,2104,2297,2409`; `pythongui/catalogue_maker.py:13`; `inputgraph.py:813,1161,1305` |
| `ordered_bdy` | `:238` | boundary nodes in circular order | `inputgraph.py:278,294,558,574,738,754,1477,1480`; `bdy.py:160,176`; `trial/bdy.py:158,174`; `staircaseshape.py:41,118,168`; `multiple_ptpg.py:129`; `ptpg_floorplanner.py:239`; `tshape.py:40,125,175`; `zshape.py:40,125,175`; `canonicalTransition.py:62,87`; `Lshaped.py:88,200,250,263,318,604,611,622` |
| `calculate_area` | `:260` | per-room area, skipping extranodes/mergednodes, folding merged parts back in | `inputgraph.py:843,1187` |

The module is imported as `opr` by `inputgraph.py:27`, `bdy.py:8`, `trial/bdy.py:8`, `floorplangen/dual.py:18`, `floorplangen/expansion.py:26`, `floorplangen/flippable.py:17`, `ptpg_floorplanner.py:55`, `staircaseshape.py:10`, `multiple_ptpg.py:125`, `tshape.py:9`, `zshape.py:8`, `ushape.py:9`, `canonicalTransition.py:1`, `Lshaped.py:15`.

---

## Dead Or Duplicated Code

Stated plainly, no invented purposes:

1. **`earclipping.angleCCW` (`earclipping.py:108-117`) is dead.** Grep across all `*.py` under `GPLAN\` finds the definition and no call site. It is the only genuinely angular helper in the file; the actual convexity test is the area test at `:128-140`.
2. **`operations.list_comparer` (`operations.py:42-57`) is dead.** No caller anywhere in the tree.
3. **`operations.intersection` (`operations.py:29-40`) is transitively dead.** Its only caller is `list_comparer` at `operations.py:55`, which is itself dead. No `opr.intersection` or `from ...operations import intersection` exists.
4. **`triangularity_non_adj.py:30` imports `earclipping as ec` and never uses it.** The non_adj `get_tri_edges` (`:266-427`) contains no `ec.` reference; grep for `ec\.` in the tree returns only `triangularity.py:205`.
5. **`triangularity_non_adj.get_faces_after_triangulation` (`:240-264`) is dead within its module.** Byte-for-byte the same as `triangularity.py:227-251`, but `triangularity_non_adj.triangulate` computes `tri_faces` from `nx.chordless_cycles` at `:464-472` instead.
6. **~130 lines of `triangularity_non_adj.get_tri_edges` are copy-pasted.** The fallback loop at `:369-425` is the constrained loop at `:302-363` with the `non_adj_list` check (`:349-351`) deleted. Any bug fix has to be applied twice.
7. **`atan2`, `get_new_coordinates`, `find_face_node`, `get_nontriangular_face` are duplicated verbatim** between the two triangularity modules (anchors in the table under Q5). Roughly 130 lines of exact duplication.
8. **`generate_multiple_bdy` ignores its `bcn_edges` and `trng_edges` parameters.** Declared at `inputgraph.py:1453`, documented at `:1460-1461`, and the body (`:1469-1483`) never references either. Callers at `:946-948` and `:1033-1034` pass them anyway.
9. **`triangularity.py:286-355` is a fully commented-out older chordality-based implementation** (`make_chordal`, `chk_chordality`, an older `triangulate`). Header comment at `:286` says "Old triangularity code based on chordality".
10. **`inputgraph.py:529-595` and `:694-707` are large commented-out blocks** inside `door_connectivity` and `door_connectivity2` (unreachable, they sit after the `return` at `:520`).
11. **`GPLAN\GPLAN\source\trial\bdy.py` is a near-duplicate of `GPLAN\GPLAN\bdy.py`** (compare `trial/bdy.py:137,148-150,158,173-174` with `bdy.py:138,150-152,160,175-176`); both import `triangularity as trng`.
12. **`GPLAN\GPLAN\source\polygonal\lshape.py:7` does `import operations as opr`** (a bare top-level import that cannot resolve under this package layout) and calls `opr.ordered_outer_boundary` (`:54,362,370`), `opr.get_outer_boundary_vertices` (`:99,321`), `opr.get_all_triangles` (`:320`) - **none of which exist in `operations.py`**. That file cannot execute against this module; treat it as dead.
13. `flag` in `triangularity_non_adj.py:338-342` and `:405-409` is computed and never read.

---

## Open Questions

1. **Knowledge-graph disagreement.** `graphify explain "triangularity.py"` lists exactly one inbound `imports_from` edge, from `GPLAN/GPLAN/source/trial/bdy.py:L10`. The source shows three more importers that the graph does not report: `inputgraph.py:36`, `bdy.py:10`, `ptpg_floorplanner.py:57`. The graph also has no node at all for `triangularity_non_adj.py` in that neighbourhood. **Code wins**; the graph's import edges for this module are incomplete.
2. Is case 2 of the forbidden-diagonal analysis (some diagonals added, remainder all forbidden, face left non-triangular, `triangularity_non_adj.py:367`) intended, or is the commented-out `:366` the correct guard? It changes the non-adjacency list from best-effort to "fail loudly", which would be a behaviour change for the `nonAdj=True` API path.
3. `plt.show()` at `triangularity_non_adj.py:457` - has the non-adjacency API path (`api.py:1302`, `handlers.py:1710`) ever actually been exercised on the server, or does it only run under the Tkinter GUI? `documentation\multi_ptpg_api.md:216` calls the non-adjacency branch "a known hang", which is consistent with this being the cause, but I did not confirm the linkage by running it.
4. Why does `triangularity.py:277` discard user coordinates whenever biconnectivity added an edge, rather than inserting the new edges into the existing drawing? The added biconnectivity edges have known endpoints with known coordinates, so a full re-layout looks unnecessary and it makes the result non-deterministic with respect to the user's input.
5. `triangularity.py:158-159` (`if len(faces) == 2: faces = [faces[0]]`) - I argued this is benign for a pure cycle because both faces are the same vertex sequence with opposite orientation. I did not verify there is no other graph shape that yields exactly 2 faces from this particular face walker.
6. The `door_connectivity` path never converts triangulation chords into dummy nodes (`inputgraph.py:512-516` only records them in `self.extraedges` for red colouring). Is the consuming client expected to treat red edges as doorless adjacencies, or is the missing `transform_edges` call an omission relative to `irreg_single_dual` (`:247-252`)?
