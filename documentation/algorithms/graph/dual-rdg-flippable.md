# Dossier: REL to rectangular dual (dual.py, rdg.py, transformation.py, flippable.py)

Unit id: `dual-rdg-flippable`
Files owned by this dossier (all paths absolute, engine copy):
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\floorplangen\dual.py` (12770 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\floorplangen\rdg.py` (4142 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\floorplangen\transformation.py` (2994 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\floorplangen\flippable.py` (7574 bytes)

Sibling task `rel-contraction-expansion` owns `contraction.py` and `expansion.py`. Their product, the labelled matrix produced by `exp.basecase` / `exp.expand`, is only an input here.

---

## Purpose

These four files cover two separate jobs that both sit downstream of the REL.

1. **REL to dimensionless geometry.** `dual.py` turns a Regular Edge Labeling (an adjacency matrix whose non-zero entries are `2` for one colour class and `3` for the other) into two path matrices, T1 and T2. `rdg.py` reads integer x/y/width/height off those matrices. The output is a grid-unit floorplan, not a metric one.
2. **REL enumeration.** `flippable.py` finds the two Eppstein flip sites (flippable edge, flippable degree-4 vertex) and rewrites label entries to produce a neighbouring REL. `inputgraph.generate_multiple_rel` drives repeated flips to enumerate the REL family for a fixed boundary.

`transformation.py` is a **different pipeline stage entirely**: it does not flip coordinates, normalise orientation, or relabel a REL. It subdivides an augmentation edge into a dummy vertex, and it runs **before** contraction/expansion, not after. See section 3 of Algorithm Walkthrough.

---

## Where It Sits In The Pipeline

Server path, all anchors read this session:

```
api.py:1299 handle_single / api.py:1327 handle_multiple  (from GPLAN.handlers import * at api.py:13)
  -> handlers.py:1086 graph.irreg_single_dual()        [single]
  -> handlers.py:1161 graph.irreg_multiple_dual()      [multiple]
```

`irreg_single_dual` (inputgraph.py:202) in order:

| Stage | Anchor |
|---|---|
| biconnectivity augmentation | inputgraph.py:219-224 |
| triangulation | inputgraph.py:228-234 |
| **edge to dummy vertex (transformation.py)** | inputgraph.py:242, inputgraph.py:249 |
| separating triangle elimination (`st.handle_STs(..., 1)`) | inputgraph.py:256, mergednodes filled at inputgraph.py:262-265 |
| boundary / CIP / shortcut removal (fills mergednodes again) | inputgraph.py:272-296, inputgraph.py:289 |
| 4-completion (`news.add_news`) | inputgraph.py:299 |
| contraction (sibling dossier) | inputgraph.py:304-307 |
| expansion (sibling dossier) | inputgraph.py:310-312 |
| **dual coordinates (`rdg.construct_dual`)** | inputgraph.py:313-315 |

`irreg_multiple_dual` (inputgraph.py:852) is the same skeleton but forked: `transform.transform_edges` at inputgraph.py:919/925 (ST branch) and inputgraph.py:1023/1029 (no-ST branch), `generate_multiple_rel` at inputgraph.py:986 and inputgraph.py:1072, and `rdg.construct_dual` deferred into a post-loop at inputgraph.py:1118-1121.

`oneconnected_dual` (inputgraph.py:1200) calls `rdg.construct_dual` at inputgraph.py:1338 (single) and inputgraph.py:1353 (multiple) on merged per-component RELs, passing empty mergednodes/irreg lists.

Post-LP repack: `dual.get_coordinates` is called only after `fpts.floorplan_to_st`, at inputgraph.py:838 (`single_floorplan`) and inputgraph.py:1181 (`multiple_floorplan`).

Merged-room stitching happens **after** all of this, in `inputgraph.get_final_traversal` (inputgraph.py:1580), called from handlers.py:549, 590, 764, 935, 1125, 1180 and others.

---

## Entry Points (file:line)

dual.py
- `dual.py:21` `populate_t1_matrix(matrix, nodecnt)`
- `dual.py:67` `get_n_s_paths(matrix, nodecnt, source, path, nspaths, t1longestdist, t1longestdistval)` (recursive DFS)
- `dual.py:113` `get_t1_ordered_children(matrix, nodecnt, centre)`
- `dual.py:139` `populate_t2_matrix(matrix, nodecnt)`
- `dual.py:179` `get_w_e_paths(...)` (recursive DFS)
- `dual.py:209` `get_t2_ordered_children(...)`
- `dual.py:235` `get_coordinates(encoded_matrix, nodecnt, room_width, room_height, hor_dgph)` (post-LP only)

rdg.py (whole file, 2 functions)
- `rdg.py:20` `construct_dual(matrix, nodecnt, mergednodes, irreg_nodes)`
- `rdg.py:54` `get_dimensions(matrix, nodecnt, t1_matrix, t2_matrix)`

transformation.py (5 functions)
- `transformation.py:13` `transform_edges(matrix, edge, faces, positions)` (only public entry actually called)
- `transformation.py:43` `find_common_node(nbr_face, edge)`
- `transformation.py:50` `update_matrix(adjmatrix, edge, common_node, extra_node)`
- `transformation.py:61` `find_new_faces(edge, common_node, extra_node)`
- `transformation.py:65` `find_nbr(matrix, vertex)`: **dead, no caller anywhere in the repo**

flippable.py
- `flippable.py:20` `get_flippable_edges(orig_matrix, news_matrix, nodecnt)`
- `flippable.py:66` `get_flippable_vertices(matrix, news_matrix, nodecnt)`
- `flippable.py:120` `resolve_flippable_edge(edge, rel)`
- `flippable.py:147` `resolve_flippable_vertex(vertex, neighbours, rel)`

Sole caller of all four flippable entries: `inputgraph.generate_multiple_rel` (inputgraph.py:1412), at inputgraph.py:1438, 1439, 1442, 1446.

---

## Data Structures

**Labelled REL matrix** (`rel`, `news_matrix`, `self.matrix` after expansion): `nodecnt x nodecnt` int array. `m[u][v] == 2` and `m[u][v] == 3` are the two directed colour classes; `1` survives only as the plain adjacency in the un-expanded matrix. `order_nbrs` (operations.py:164-167) collects a vertex's REL neighbours as exactly the union of `matrix[centre] in {2,3}` and `matrix[:,centre] in {2,3}`, which is the definition of "REL neighbour" used everywhere in this unit.

**NEWS indexing.** `news.add_news` wires bdy[0]->`nodecnt`, bdy[1]->`nodecnt+1` (east), bdy[2]->`nodecnt+2` (south), bdy[3]->`nodecnt+3` (west) (news.py `add_news`, the four `news_edges` calls with the inline `#east/#south/#west` comments). After `self.nodecnt += 4` the constants used in dual.py resolve to: north = `nodecnt-4`, east = `nodecnt-3`, south = `nodecnt-2`, west = `nodecnt-1`. That matches dual.py:35 (DFS source `nodecnt-2` = south), dual.py:82 (base case `nodecnt-4` = north), dual.py:153 (source `nodecnt-1` = west), dual.py:196 (sink `nodecnt-3` = east).

**T1 matrix** (`dual.py:59`): built as a list of N-to-S rows then `.transpose()`, so the final shape is `(levels, paths)`. `t1_matrix[d][p]` = the vertex occupying N-S distance level `d` on path index `p`. Empty fallback is `np.empty((cols, 0), int)`.

**T2 matrix** (`dual.py:176`): **not** transposed, shape `(paths, levels)`. `t2_matrix[p][d]` = vertex on W-E path `p` at distance `d` from west. Empty fallback `np.empty((0, cols), int)`.

The two matrices therefore have opposite axis conventions, and `rdg.get_dimensions` compensates by slicing rows for T1 (`t1_matrix[1:-1]`, rdg.py:76) and columns for T2 (`t2_matrix[:, 1:-1]`, rdg.py:84).

**Outputs of `construct_dual`** (rdg.py:48-51, returned as a 4-element list): `room_x`, `room_y`, `room_width`, `room_height`, each `np.zeros(nodecnt - 4)` (rdg.py:69-72). Callers unpack them straight onto the InputGraph attributes of exactly those names (inputgraph.py:313, 773, 1118, 1338, 1353). There are no other coordinate attributes; `room_x`/`room_y` is the **top-left / origin corner**, per the comment at dual.py:314 ("not subtracting height because code requires top left corner") and the corner expansion in `get_circular_traversal` (inputgraph.py:1574-1577), which builds `(x,y)`, `(x, y+h)`, `(x+w, y+h)`, `(x+w, y)`.

---

## Algorithm Walkthrough

### 1. rdg.py is the orchestrator only of the last hop, not of the whole pipeline

`rdg.py` has exactly **two** functions: `construct_dual` (rdg.py:20) and `get_dimensions` (rdg.py:54). Its module docstring (rdg.py:6-15) advertises five (`get_rectangular_coordinates`, `get_direction`, `construct_dual`, `construct_floorplan`, `get_dimensions`); **three of those five do not exist in the file**. The docstring is stale.

`construct_dual` does not sequence contraction or expansion. Its whole body is:

```
rdg.py:43   t1_matrix = dual.populate_t1_matrix(matrix, nodecnt)
rdg.py:45   t2_matrix = dual.populate_t2_matrix(matrix, nodecnt)
rdg.py:47   room_x, room_y, room_width, room_height = get_dimensions(matrix, nodecnt, t1_matrix, t2_matrix)
rdg.py:48-51 return [room_x, room_y, room_width, room_height]
```

Contraction and expansion are sequenced by the **callers**, not by rdg: inputgraph.py:304-312 runs `cntr.degrees` / `cntr.goodnodes` / `cntr.contract` / `exp.basecase` / `exp.expand` and only then calls `rdg.construct_dual` at inputgraph.py:313. So rdg.py is a two-step orchestrator (T1 matrix, T2 matrix, read off dimensions), and the pipeline orchestrator is `InputGraph.irreg_single_dual` / `irreg_multiple_dual` / `oneconnected_dual`.

**Room assignment is not done by rdg.py either.** `construct_dual` accepts `mergednodes` and `irreg_nodes` (rdg.py:20, documented rdg.py:26-27) and **never reads either parameter in the body** (rdg.py:43-51). They are dead parameters at every one of the six call sites (inputgraph.py:313-315, 773-775, 1118-1121, 1338-1339, 1353-1354, plus lettershape/staircase copies such as Lshaped.py:536-537).

Full call sequence with anchors, single-dual path:

```
handlers.py:1086  graph.irreg_single_dual()
  inputgraph.py:242/249  transform.transform_edges(...)          -> transformation.py:13
  inputgraph.py:256      st.handle_STs(...)                       (sibling / septri)
  inputgraph.py:299      news.add_news(...)
  inputgraph.py:306      cntr.contract(...)                       (sibling dossier)
  inputgraph.py:310-312  exp.basecase / exp.expand                (sibling dossier)
  inputgraph.py:313      rdg.construct_dual(self.matrix, self.nodecnt, self.mergednodes, self.irreg_nodes1)
      rdg.py:43          dual.populate_t1_matrix                  -> dual.py:21
          dual.py:34     dual.get_n_s_paths                       -> dual.py:67 (recursive)
              dual.py:104 dual.get_t1_ordered_children            -> dual.py:113
                  dual.py:124 opr.order_nbrs(cw=True)             -> operations.py:153
      rdg.py:45          dual.populate_t2_matrix                  -> dual.py:139
          dual.py:152    dual.get_w_e_paths                       -> dual.py:179 (recursive)
              dual.py:200 dual.get_t2_ordered_children            -> dual.py:209
      rdg.py:47          get_dimensions                           -> rdg.py:54
  -> writes self.room_x, self.room_y, self.room_width, self.room_height (inputgraph.py:313)
handlers.py:1125  inputgraph.get_final_traversal(graph)           -> inputgraph.py:1580 (merged-room stitching)
```

Attribute mapping is one-to-one and positional: element 0 of the returned list -> `room_x`, 1 -> `room_y`, 2 -> `room_width`, 3 -> `room_height`. No other attribute is populated by this stage.

### 2. dual.py: how x and y are actually computed

It is **neither pure path counting nor pure longest-path distance**: it is both, on orthogonal axes. Longest-path distance fixes the *level* a vertex occupies inside the matrix; the *path index* becomes the coordinate.

**T1 / x axis.**

- Loop A, `dual.py:105-109` inside `get_n_s_paths`: a plain recursive DFS from south (`nodecnt-2`, dual.py:35) that enumerates **every** simple S-to-N path, reversing each on arrival at north (dual.py:88). Children come from `get_t1_ordered_children` (dual.py:113), which orders the REL neighbours **clockwise** (`opr.order_nbrs(..., cw=True)`, dual.py:124), skips past the label-3 block twice (dual.py:129-132), then takes the contiguous run of label-2 out-edges (dual.py:133-135). The comment at dual.py:62-64 explains the reversal: the code walks S->N clockwise and reverses so the stored order is the N->S anticlockwise order.
- Loop B, `dual.py:91-97`: for each stored N-to-S path, `t1longestdist[node] = max(t1longestdist[node], i)` where `i` is the index in the path. This is the **longest-path (topological) distance from north**, accumulated over all enumerated paths. `t1longestdistval` is the max over all vertices and becomes the number of grid levels (`cols = t1longestdistval + 1`, dual.py:36).
- Loop C, `dual.py:40-58`: each path is re-expanded into a fixed-width row of length `cols`. A vertex is advanced only when the next vertex's longest distance has been reached (`t1longestdist[path[path_index + 1]] <= distance`, dual.py:46), which is exactly "stretch each room down to its longest-path level". A path is rejected (dual.py:49-52) when at some level it would place a vertex that already appears in that level's `col_vertices` set while the immediately preceding accepted row holds a different vertex, i.e. non-contiguous reuse of a vertex across path indices.
- `dual.py:59`: transpose, so rows are levels and columns are path indices.

**Read-off, `rdg.py:73-83` (the x loop).** For node `n`, `np.where(t1_matrix[1:-1] == n)` (rdg.py:76) yields `(row=level, col=path index)` with the north and south rows stripped. Then:

```
rdg.py:79  counts   = np.bincount(row)
rdg.py:80  max_row  = np.argmax(counts)
rdg.py:81  indexes, = np.where(row == max_row)
rdg.py:82  room_x[node]     = col[indexes[0]]
rdg.py:83  room_width[node] = col[indexes[-1]] - col[indexes[0]] + 1
```

So **x = the smallest path index at the level where the node spans the most paths**, and **width = a difference of path indices** (last minus first, plus one). **Tie-breaking is `np.argmax`, which returns the lowest index on ties**, i.e. the level closest to north wins.

**T2 / y axis, `rdg.py:84-89`.** Symmetric with the axes swapped, because `populate_t2_matrix` does not transpose:

```
rdg.py:84  row, col = np.where(t2_matrix[:, 1:-1] == node)   # row = path index, col = level from west
rdg.py:85  counts   = np.bincount(col)
rdg.py:86  max_col  = np.argmax(counts)
rdg.py:88  room_y[node]      = row[indexes[0]]
rdg.py:89  room_height[node] = row[indexes[-1]] - row[indexes[0]] + 1
```

**y = the smallest W-E path index at the west-distance level where the node spans the most paths; height = a difference of path indices.** Note the T2 longest-distance bookkeeping is inline in the recursion head (dual.py:194-195) rather than in a post-arrival loop as in T1, but the effect is identical.

No face traversal is involved anywhere in dual.py.

**`dual.get_coordinates` (dual.py:235) is a different, later thing.** It is not part of the REL-to-dual read-off. It re-packs x/y **after** the LP has replaced grid widths/heights with real ones, by column-scanning the encoded matrix and stacking `ymin += room_height` (dual.py:319) and `xmax = xmin + room_width` (dual.py:317). Only two callers, both post-LP: inputgraph.py:838 and inputgraph.py:1181.

### 3. transformation.py: what it actually transforms (all 2994 bytes accounted for)

Not coordinate flips. Not orientation normalisation. Not REL relabelling. It is **edge subdivision: one augmentation edge becomes one dummy vertex**, run before the REL exists at all.

Byte-for-byte account of the file:

| Lines | Content | Status |
|---|---|---|
| 1-10 | module docstring, claims two functions (`transform`, `find_nbr`); the real public entry is named `transform_edges`, so the docstring is stale | stale doc |
| 11 | `import numpy as np` | live |
| 13-41 | `transform_edges`: find the 1 or 2 triangular faces containing `edge` (line 25), grow the adjacency by one row/col (26-27), and for each such face insert one dummy vertex (28-37), interpolate its embedding position as the edge midpoint (32-33), replace the face by two new faces (34-37). Returns `(adjmatrix, faces, positions, 2)` for an external edge, `(..., 3)` for an internal one (38-41) | live |
| 43-48 | `find_common_node`: the apex of the face not on `edge`; defaults to `0` | live, called at 29 |
| 50-59 | `update_matrix`: delete `edge`, wire `extra_node` to both endpoints and to the apex | live, called at 31 |
| 61-63 | `find_new_faces`: the two replacement triangles | live, called at 34 |
| 65-79 | `find_nbr`: returns the set of `== 1` neighbours of a vertex | **dead** |

`find_nbr` has **no caller in the repository**: `grep -rn "find_nbr"` over `GPLAN` and `gplan_backend` returns only the definition (transformation.py:65) and the stale docstring mention (transformation.py:9), plus the identical lines in the `gplan_backend` submodule checkout.

Callers of `transform_edges`, with anchors:
- `inputgraph.py:242` and `inputgraph.py:249` (live, `irreg_single_dual`)
- `inputgraph.py:919`, `925`, `1023`, `1029` (live, `irreg_multiple_dual`, both branches)
- `inputgraph.py:697` and `inputgraph.py:704`: **commented out**, inside the dead `door_connectivity2`
- `trial\bdy.py:125` and `trial\bdy.py:131`: **unreachable**, see Dead Or Duplicated Code

So transformation.py is **not** dead, but exactly one of its five functions is.

### 4. flippable.py: what a flip is and how enumeration is bounded

**Flippable edge** (`get_flippable_edges`, flippable.py:20). Candidates are all directed REL entries labelled 2 or 3 (flippable.py:31-37). NEWS vertices are excluded because the caller passes `nodecnt - 4` (inputgraph.py:1438) and the filter at flippable.py:40-41 drops any endpoint `>= nodecnt`. For a surviving edge `(u,v)`, `intersection` is the two common neighbours in the plain 0/1 adjacency (flippable.py:42-44). The edge is flippable iff the 4-cycle `u - i0 - v - i1 - u` **alternates** labels, tested in both alternation phases:

- flippable.py:45-53: `(u,i0)` is 3, `(u,i1)` is 2, `(v,i1)` is 3, `(v,i0)` is 2;
- flippable.py:54-62: the mirror case, `(u,i0)` is 2, `(u,i1)` is 3, `(v,i1)` is 2, `(v,i0)` is 3.

Each test is direction-agnostic (`m[a,b] == k or m[b,a] == k`), so it tests the *colour* of the 4-cycle side, not its orientation. This is the standard Eppstein condition: the edge is the diagonal of an alternating (colour-alternating) quadrilateral.

**Flippable vertex, the "flippable wheel"** (`get_flippable_vertices`, flippable.py:66). There is no function or symbol named "wheel" in the file. The analogue is a **degree-4 vertex whose link 4-cycle alternates**: degrees are counted on the REL matrix (flippable.py:77-78), degree-4 non-NEWS vertices are collected (flippable.py:82-84), the four neighbours are put into cyclic order by walking adjacency (flippable.py:87-95), and the same two alternation phases are tested around `temp[0..3]` (flippable.py:96-105 and 106-115). Geometrically this is the "pinwheel" of four rooms around a small room, which can be rotated.

**How a flip rewrites the matrices.**

`resolve_flippable_edge` (flippable.py:120) copies the REL (flippable.py:129) and rewrites **one entry**. It reads the label of the next clockwise neighbour of `edge[0]` after `edge[1]` (flippable.py:130-131, `opr.ordered_nbr_label(..., True)[0]`) and then:

| current `rel[u,v]` | next-nbr label | rewrite | anchor |
|---|---|---|---|
| 2 | 3 | `rel[u,v] = 3` (recolour, same direction) | flippable.py:134 |
| 2 | 2 | `rel[u,v] = 0`, `rel[v,u] = 3` (recolour + reverse) | flippable.py:136-137 |
| 3 | 3 | `rel[u,v] = 2` | flippable.py:140 |
| 3 | 2 | `rel[u,v] = 0`, `rel[v,u] = 2` | flippable.py:142-143 |

Note the T1 and T2 relations are not two separate matrices at this point: they are the `2` and `3` entries of one matrix. So "how a flip rewrites T1/T2" is literally "it moves one entry between the 2-class and the 3-class, sometimes reversing the arc".

`resolve_flippable_vertex` (flippable.py:147) rewrites **six entries** around the degree-4 vertex: it first normalises the neighbour list to clockwise order (flippable.py:158-161), rotates it until `new_rel[vertex, neighbours[0]] == 3` (flippable.py:162-164), then applies one of two 6-line rewrites depending on the incoming label (flippable.py:165-171 and 172-178). This is the pinwheel rotation.

**Enumeration driver and bounds** (`generate_multiple_rel`, inputgraph.py:1412). It builds the seed REL via add_news / contract / basecase / expand (inputgraph.py:1424-1434), seeds `rel_matrix = [news_matrix]` (inputgraph.py:1435-1436), and then:

```
inputgraph.py:1437  for mat in rel_matrix:            # iterating a list that is appended to inside the loop
inputgraph.py:1438      flippable_edges    = flp.get_flippable_edges(matrix, mat, nodecnt - 4)
inputgraph.py:1439      flippable_vertices, nbrs = flp.get_flippable_vertices(matrix, mat, nodecnt - 4)
inputgraph.py:1441-1444   for each flippable edge:   new_rel = resolve_flippable_edge(...)  ; append if not already present
inputgraph.py:1445-1449   for each flippable vertex: new_rel = resolve_flippable_vertex(...); append if not already present
inputgraph.py:1450  return rel_matrix
```

Because Python re-checks the list length each iteration, `for mat in rel_matrix` over a growing list is a **breadth-first closure of the flip graph**. The bound is therefore:

- **Fixpoint, not a count.** The loop stops when a full pass over every discovered REL produces no new matrix.
- **Deduplication** by exact matrix equality: `if not any(np.array_equal(new_rel, i) for i in rel_matrix)` (inputgraph.py:1443 and 1448). This is O(|rel_matrix|) numpy comparisons per candidate, so the dedup cost is quadratic in the number of RELs.
- **There is no count limit inside `generate_multiple_rel`.** The caps live in the consumer: `self.floorplan_limit = 500` (inputgraph.py:139) checked at inputgraph.py:999 and inputgraph.py:1084, and `self.floorplan_per_bdy_limit = 20` (inputgraph.py:140), which is *not* consulted in inputgraph.py at all. It is read only in handlers.py:1862, 2095, 2287, 2532. Under cardinal constraints the per-boundary cap is deliberately raised to the global limit (inputgraph.py:866).

Important consequence: `generate_multiple_rel` computes the **entire** flip closure before any cap applies, then the caller throws most of it away. On a large graph the enumeration cost is paid in full.

`rdg.py` does not call flippable. `flippable.py` never calls dual or rdg.

### 5. Merged rooms from separating-triangle resolution

Where the merged nodes come from:
- ST elimination: `st.handle_STs` returns `extra_nodes`, and the dummy key is appended to `mergednodes` with the two halves recorded in `irreg_nodes1`/`irreg_nodes2` (inputgraph.py:262-265, and inputgraph.py:942-945 in the multiple path).
- Shortcut removal (>4 CIPs): `mergednodes.append(self.nodecnt)` (inputgraph.py:289, also inputgraph.py:749).

Where they are **not** used:
- `mergednodes` appears in this unit exactly once, as the unused third parameter of `rdg.construct_dual` (rdg.py:20, docstring rdg.py:26). Grep over `dual.py`, `transformation.py`, `flippable.py` returns **no** occurrence of `mergednodes` at all. So the dual stage treats a merged room as two completely independent rectangles.

Where the stitching actually happens: **`inputgraph.get_final_traversal` (inputgraph.py:1580)**, in three phases.

1. inputgraph.py:1586-1588: every node, dummies included, gets a 4-corner rectangle ring from `get_circular_traversal` (inputgraph.py:1572-1578).
2. inputgraph.py:1591-1618: `for i, j in zip(graph.irreg_nodes1, graph.mergednodes)` walks the parent ring's edges (1595-1596), finds the collinear overlapping edge on the dummy ring with `check_overlap` (inputgraph.py:1598, defined at inputgraph.py:1512), rotates the dummy ring so the shared edge is first (inputgraph.py:1602), splices the dummy's corners into the parent's ring with `merge_traversal` (inputgraph.py:1604, defined inputgraph.py:1554), and drops every point that now appears twice with `remove_dups` (inputgraph.py:1606, defined inputgraph.py:1535). A second partial-overlap pass at inputgraph.py:1609-1615 handles the case where only part of the shared edge coincides. The merged ring is written back at inputgraph.py:1617.
3. inputgraph.py:1620-1622: dummy and augmentation nodes are excluded from the output (`if (i not in graph.mergednodes) and (i not in graph.extranodes)`).

**The shape irregularity produced.** `remove_dups` (inputgraph.py:1535-1552) keeps only points with frequency exactly 1. Two axis-aligned rectangles sharing a partial edge contribute 8 corners; the two coincident corners cancel, leaving **6 vertices, i.e. an L-shaped orthogonal polygon**. Where the shared edge coincides exactly, more points cancel and the result degenerates to a plain rectangle (a "T" or "+" is not reachable from a single merge, but chained merges through the same parent iterate the loop and can produce more complex orthogonal polygons since `node1 = traversal` at inputgraph.py:1616 feeds the next merge).

Area accounting matches the same convention: `opr.calculate_area` (operations.py:260) skips dummies outright (operations.py:276) and folds their rectangle area into the parent (operations.py:279-282).

So the answer to "where are merged rooms stitched back" is: **not in dual.py, rdg.py, transformation.py or flippable.py at all; only in `inputgraph.get_final_traversal`, at the polygon level, long after coordinates exist.**

---

## Invariants And Preconditions

1. **The input matrix to `construct_dual` must already be a fully expanded REL on a 4-completed graph.** `dual.get_t1_ordered_children` (dual.py:129-135) and `get_t2_ordered_children` (dual.py:225-231) spin `index = (index + 1) % len(ordered_nbrs)` with no iteration cap; if a vertex has no label-3 block or no label-2 block the loop never exits. Same for `operations.order_nbrs` (operations.py:169-178).
2. **NEWS vertices occupy the last four indices in N, E, S, W order.** dual.py:35, 82, 153, 196 hard-code `nodecnt-2`, `nodecnt-4`, `nodecnt-1`, `nodecnt-3`. Changing `news.add_news`'s wiring order silently transposes the whole floorplan.
3. **`nodecnt` passed to `construct_dual` must be the post-4-completion count**, since the output arrays are `np.zeros(nodecnt - 4)` (rdg.py:69-72). Callers honour this: inputgraph.py:1119 passes `nodecnt_list + 4`, inputgraph.py:1339 passes `nodes + 4`.
4. **`rdg.get_dimensions` assumes T1 is level-major and T2 is path-major.** Making `populate_t2_matrix` transpose (to match T1) would silently swap y with the west-distance level.
5. **`get_flippable_edges` assumes every candidate edge lies in exactly two triangles**, since it indexes `intersection[0]` and `intersection[1]` unconditionally (flippable.py:45-52). This holds only because the caller passes the **4-completed** adjacency (inputgraph.py:1424-1425, `matrix` is reassigned by `add_news` before the deepcopy), which is maximal planar.
6. **`get_flippable_vertices` assumes the link of a degree-4 vertex is a 4-cycle** (flippable.py:88-95).
7. **`resolve_flippable_vertex` mutates its `neighbours` argument in place** (`neighbours.reverse()` at flippable.py:161, `pop(0)`/`append` at flippable.py:163-164). The caller passes the list stored in `flippable_vertices_neighbours` (inputgraph.py:1446-1447), so the stored ordering is destroyed after the first use. Currently harmless because each entry is used once.
8. **`room_x`/`room_y` are top-left origins, and coordinates are grid units, not metres**, until the LP replaces them.
9. **`transform_edges` requires `faces` to be a list of triangles expressed as 3 directed tuples** and matches by `edge in face or reversed_edge in face` (transformation.py:24-25). It also mutates `faces` and `positions` in place (transformation.py:32-37) while returning them.

---

## Failure Modes

**Can dual.py produce zero-width rooms?**

Strictly, `get_dimensions` cannot compute a width below 1 for a node that appears in T1: `col[indexes[-1]] - col[indexes[0]] + 1` (rdg.py:83) is at least 1. Zero-width rooms arise a different way: a node **absent** from T1 keeps its pre-initialised `np.zeros` entry, because of the explicit skip:

```
rdg.py:77-78    if row.shape[0] == 0:  # remove this later
                    continue
```

That comment is in the source. So yes, a zero-width, zero-height room is a reachable output, and the only "guard" is a silent `continue` that leaves the zeros in place. The single downstream consumer that recognises 0 as a sentinel is `opr.calculate_area` (operations.py:276, `if room_width[i] == 0 ... continue`) and the GUI drawer `pythongui\final.py:872`. Nothing raises, nothing warns, and `get_encoded_matrix` (operations.py:232-235) will simply write nothing for that node, leaving whatever room id occupied that cell.

Other failure modes, all anchored:

1. **Asymmetric guard: the T2 branch has none.** rdg.py:76-78 guards T1 emptiness; rdg.py:84-87 does not. If a node appears in T1 but not in T2, `np.bincount` on the empty index array returns an empty array and `np.argmax` raises `ValueError: attempt to get argmax of an empty sequence` (verified against the installed numpy 1.26.0 in this environment). The crash is an uncaught `ValueError` inside `construct_dual`.
2. **Order-dependent path rejection.** The validity test at dual.py:49-52 (and dual.py:166-169) compares the candidate against **only** `rows_list[-1]`, the last accepted row, not against all accepted rows. Whether a path survives therefore depends on DFS discovery order. Dropping a path removes a grid column, so a room's width can silently under-count, or a room can vanish from T1 entirely and hit failure mode above.
3. **Exponential path enumeration.** `get_n_s_paths` (dual.py:67) and `get_w_e_paths` (dual.py:179) are unbounded recursive DFS over **all** simple source-to-sink paths, with the full path list materialised in memory (dual.py:99, dual.py:198). No depth cap, no count cap. On larger graphs this is the dominant cost of dual construction and can also hit Python's recursion limit.
4. **`get_coordinates` can raise on an empty column.** dual.py:320-321: `xmax = xmax[xmax != 0]` then `xmin = min(xmax)`; if every entry was filtered out, `min` on an empty array raises `ValueError`. Related, `find` (dual.py:267-271) returns `[0]` when nothing matches, which silently means "align to room 0" rather than "no predecessor".
5. **`get_coordinates` shadows builtins.** `any` is redefined at dual.py:255 inside `get_coordinates`, so the builtin is unavailable in that scope. Currently intentional but a live trap for anyone editing the function.
6. **`get_flippable_edges` IndexError.** flippable.py:45 indexes `intersection[1]` without a length check; a boundary or non-triangulated edge yields fewer than two common neighbours and crashes.
7. **Infinite loops in flippable.** flippable.py:90-95 `while(len(neighbors) != 0)` with an inner `for ... break` that may find no adjacent candidate spins forever. flippable.py:162 `while(new_rel[vertex, neighbours[0]] != 3)` spins forever if no outgoing label-3 edge exists at that vertex.
8. **Silent wrong wiring in transformation.** `find_common_node` (transformation.py:43-48) initialises `other_node = 0` and returns it unchanged if the face contains no third vertex, so a malformed face wires the dummy vertex to node 0.
9. **Quadratic REL dedup.** inputgraph.py:1443 and 1448 do a full linear scan of every accumulated REL for every candidate. With hundreds of RELs this is the hot spot of `generate_multiple_rel`, and the closure is computed in full before `floorplan_limit` (inputgraph.py:999) can stop anything.
10. **Merged-room stitching is best-effort.** `get_final_traversal` (inputgraph.py:1591-1618) `break`s after the first overlapping edge it finds (inputgraph.py:1618). If `check_overlap` returns -1 for every edge, the merge is silently skipped and the parent stays a bare rectangle while the dummy is still excluded at inputgraph.py:1621, losing area from the drawing.

---

## Coupling (what breaks if you change this)

- **Change the NEWS index order in `news.add_news`** -> dual.py:35/82/153/196 all break silently, producing a rotated or transposed floorplan rather than an error.
- **Make `populate_t2_matrix` transpose (to match T1)** -> rdg.py:84-89 silently swaps y with west-distance level. Nothing raises.
- **Change the return arity or order of `construct_dual`** -> six unpacking sites break: inputgraph.py:313, 773, 1118, 1338, 1353, plus `Lshaped.py:189`, `Lshaped.py:536`, `tshape.py:86`, `ushape.py:91`, `zshape.py:86`, `staircaseshape.py:85`.
- **Change the meaning of `room_x`/`room_y` from top-left to any other corner** -> `get_circular_traversal` (inputgraph.py:1574-1577), `handlers.py:98-99` (circulation `Room` construction), `opr.get_encoded_matrix` (operations.py:232-235) and `dual.get_coordinates` (dual.py:314-319) all silently disagree.
- **Change the REL label encoding (2/3)** -> everything in this unit plus `operations.order_nbrs` (operations.py:164-167) and the sibling contraction/expansion module.
- **Change `resolve_flippable_*` to mutate `rel` in place instead of copying** (flippable.py:129, 157) -> `generate_multiple_rel`'s BFS (inputgraph.py:1437-1449) would corrupt already-enumerated RELs, since it flips off `mat` repeatedly.
- **Add a cap inside `generate_multiple_rel`** -> changes which floorplans reach `floorplan_limit`, which changes the ordering and content of the catalogue that `api.py` post-filters. This is the cheapest available perf lever for the slow-generation problem.
- **`transform_edges` mutates `faces`/`positions` in place** -> a caller that reuses the pre-call lists (inputgraph.py:242 and 249 rely on the returned values) would see aliasing.
- **Removing the `continue` at rdg.py:77** without fixing the underlying T1 gap -> converts a silent zero-area room into an `IndexError` at rdg.py:80.

---

## Dead Or Duplicated Code

- **`transformation.py:65` `find_nbr`** is dead. No caller in `GPLAN` or `gplan_backend`; only the definition and the stale docstring reference at transformation.py:9.
- **`rdg.py` module docstring (rdg.py:6-15)** advertises `get_rectangular_coordinates`, `get_direction` and `construct_floorplan`; none of the three exists in the file. Stale documentation, not code.
- **`rdg.construct_dual`'s `mergednodes` and `irreg_nodes` parameters (rdg.py:20)** are never read (body rdg.py:43-51). Dead parameters at all six call sites.
- **`InputGraph.door_connectivity2` (inputgraph.py:650)** is dead: grep for `door_connectivity2` returns only the definition (and its copy in the `gplan_backend` submodule). It contains a full second copy of the boundary / 4-completion / contraction / expansion / `rdg.construct_dual` sequence, of which the tail (inputgraph.py:578-595) is itself commented out.
- **`InputGraph.door_connectivity` (inputgraph.py:340)**, the live one called from handlers.py:1710 and 1732, `return`s at inputgraph.py:520 and never reaches its own commented-out dual code (inputgraph.py:578-595). It is a pre-processor that only prepares the matrix; the dual is built afterwards by `irreg_single_dual` (handlers.py:1759/1761).
- **`source\trial\bdy.py`** imports `rdg`, `transformation`, `flippable` (trial\bdy.py:15-17) and duplicates the pipeline (trial\bdy.py:125/131 call `transform_edges`). It is imported only by `source\multiple_circ.py:9`, which nothing imports, and by a commented-out line in `circulation\circulation.py:12`. **Unreachable from `api.py` and `handlers.py`.**
- **`pythongui\final.py:704 compute_coordinates`** is a near-verbatim copy of `dual.get_coordinates` (dual.py:235), same inner helpers (`ismember`, `any`, `find_sp`, `find`) and same `xR`/`xmax` scan. It is reachable only through the Tk GUI (`pythongui\gui.py:27`), not through the server dual path.
- **`gplan_backend\GPLAN\GPLAN\source\floorplangen\*.py`** is a byte-identical checkout of all four files (verified with `diff -q`, no differences). It is the submodule copy, not divergent code.
- **`lettershape\{lshape,tshape,ushape,zshape}` and `staircaseshape`** each re-implement the pipeline tail around `rdg.construct_dual` (Lshaped.py:189/536, tshape.py:86, ushape.py:91, zshape.py:86, staircaseshape.py:85). Live but heavily duplicated with `irreg_single_dual`.

---

## Open Questions

1. **What does `# remove this later` at rdg.py:77 refer to?** It is the only thing preventing an `IndexError` when a node is missing from T1, and there is no matching guard on the T2 side (rdg.py:84-87). Whether the intended fix is a guard on both sides or a fix in `populate_t1_matrix`'s path-rejection rule (dual.py:49-52) is not recorded anywhere in the source.
2. **Is the path-rejection rule at dual.py:49-52 correct, or is comparing only against `rows_list[-1]` a bug?** The `col_vertices` sets look like an optimisation added over an older "scan the whole matrix" check (the comment at dual.py:38 says exactly that). If the original check scanned all accepted rows rather than just the previous one, the current form is a behaviour change, not just a speedup. Not resolvable from the code alone; needs the pre-optimisation revision.
3. **Does the flip closure in `generate_multiple_rel` actually reach every REL of the graph?** Eppstein's theorem covers edge flips plus degree-4 vertex rotations, but `get_flippable_edges` excludes any edge with a NEWS endpoint (flippable.py:40-41 with `nodecnt - 4` from inputgraph.py:1438). Whether that exclusion loses RELs was not verified here.
4. **`GPLAN_ENGINE_LEARNINGS.md:254-256` says a room's `x` is "the index of the first path containing it".** The code is more specific: it is the first path index **at the level where the room spans the most paths**, chosen by `np.argmax` on a bincount, with ties resolved to the level nearest north (rdg.py:79-82). The doc also says children are ordered "anticlockwise via `opr.order_nbrs`" while the code passes `cw=True` (dual.py:124, dual.py:220) and reverses the path on arrival (dual.py:88), which the in-file comment at dual.py:62-64 explains. Following the code; the doc should be tightened.
5. **Is `floorplan_per_bdy_limit` (inputgraph.py:140) meant to bound REL enumeration?** It is set in `InputGraph.__init__` and raised in `irreg_multiple_dual` (inputgraph.py:866), but it is never read inside `inputgraph.py`; the only reads are in handlers.py (1862, 2095, 2287, 2532). If the intent was to cap the flip closure, that intent is not implemented.
6. **What produces "flippable wheel" terminology?** No such symbol exists in flippable.py. The degree-4 pinwheel in `get_flippable_vertices` (flippable.py:66) is presumably what the term refers to, but the source never names it.
