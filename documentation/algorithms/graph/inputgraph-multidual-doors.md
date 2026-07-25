# inputgraph-multidual-doors

Scope: the multi-plan and door-connectivity orchestration inside
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py`.
Covered members: `InputGraph.door_connectivity`, `InputGraph.scale_plot_dimension`,
`InputGraph.door_connectivity2`, `InputGraph.irreg_multiple_dual`,
`InputGraph.multiple_floorplan`, and the module-level helpers
`filter_boundaries_by_cardinal`, `generate_multiple_rel`, `generate_multiple_bdy`,
`staircaseshaped`, `store_dummy_node_adjacencies`, `check_overlap`, `remove_dups`,
`merge_traversal`, `get_circular_traversal`, `get_final_traversal`.

Explicitly NOT covered (sibling dossier `inputgraph-single-dual-core`):
`__init__`, `irreg_single_dual`, `single_floorplan`, `oneconnected_dual`,
`polyonalinput`.

All line numbers below were read in this session.

---

## Purpose

This half of `inputgraph.py` does two separable jobs.

1. **Graph conditioning for the door-connectivity API** (`door_connectivity`,
   inputgraph.py:340). It takes the user's room-adjacency graph plus an optional
   non-adjacency ("red edge") list, augments it to a biconnected, triangulated,
   separating-triangle-free plane graph, and answers one question to its caller:
   is the result a PTPG (inputgraph.py:520)? It produces no floorplan geometry
   beyond a 2-node degenerate special case (inputgraph.py:354-359).

2. **Catalogue generation** (`irreg_multiple_dual`, inputgraph.py:852). From a
   conditioned graph it enumerates candidate outer boundaries, enumerates RELs
   (regular edge labelings) per boundary, and materializes the cross product as a
   list of child `InputGraph` objects, each holding one rectangular-dual topology.
   `scale_plot_dimension` (inputgraph.py:597) is the expand-only plot fitter run
   after the min-dim solver, and `get_final_traversal` (inputgraph.py:1580)
   converts solved room rectangles into the per-room polygon list that is
   serialized to clients.

---

## Where It Sits In The Pipeline

```
api.py  Documents.get_floorplans
  caller == "door_connectivity"
    single: api.py:1301-1309   multiple: api.py:1328-1353 (+ retry ladder api.py:1390)
        |
        v
handlers.py:1686  handle_door_connectivity
        |
        +-- graph.door_connectivity(...)          handlers.py:1710 (non-adj) / 1732 (plain)
        |       -> inputgraph.py:340 .. 520   returns (graph, checkPTPG)
        |
        +-- if checkPTPG:  handlers.py:1745
        |       min-dim path -> graph.irreg_multiple_dual(input_dims)
        |                       handlers.py:1830 / 1836 / 1838
        |                       -> inputgraph.py:852 .. 1121
        |
        +-- per-candidate min-dim solve loop      handlers.py:1859-1967
        +-- plot-expansion fallback loop          handlers.py:2092-2168
        |       -> graph.scale_plot_dimension(...) handlers.py:2173
        |       (non-PTPG twin of the same loop -> handlers.py:2619)
        |
        v
api.py:1358 rectangularize_output -> api.py:859 rewrites plan.final_traversal
api.py:1365 filter_output_by_cardinal -> api.py:374 plan_satisfies_cardinal (reads final_traversal, api.py:382)
api.py:1429 floorplanData = outputData[index].final_traversal  ->  walls + circular_coordinates
```

`get_final_traversal` is called from many places in handlers.py; the ones on the
door-connectivity path are handlers.py:1928, 1951, 2038, 2061, 2155, 2603.

---

## Entry Points (file:line)

In-scope definitions:

| Symbol | Definition | Real call sites |
| --- | --- | --- |
| `InputGraph.door_connectivity` | inputgraph.py:340 | handlers.py:1710, handlers.py:1732 (only these two) |
| `InputGraph.scale_plot_dimension` | inputgraph.py:597 | handlers.py:2173, handlers.py:2619 |
| `InputGraph.door_connectivity2` | inputgraph.py:650 | **none** (see Dead Or Duplicated Code) |
| `InputGraph.irreg_multiple_dual` | inputgraph.py:852 | handlers.py:361, 363, 615, 618, 627, 792, 923, 930, 1050, 1068, 1161, 1164, 1210, 1213, 1335, 1338, 1368, 1370, 1469, 1472, 1778, 1830, 1836, 1838, 2232, 2268; also inputgraph.py:1263 inside `oneconnected_dual` |
| `InputGraph.multiple_floorplan` | inputgraph.py:1126 | handlers.py:1069, handlers.py:1474 (GUI dimensioned-multiple paths only) |
| `filter_boundaries_by_cardinal` | inputgraph.py:1365 | inputgraph.py:951, inputgraph.py:1037 (internal only); referenced in prose at api.py:158 |
| `generate_multiple_rel` | inputgraph.py:1412 | inputgraph.py:986, inputgraph.py:1072 |
| `generate_multiple_bdy` | inputgraph.py:1453 | inputgraph.py:946, inputgraph.py:1033 |
| `staircaseshaped` | inputgraph.py:1496 | handlers.py:1034 |
| `store_dummy_node_adjacencies` | inputgraph.py:1502 | inputgraph.py:259 (`irreg_single_dual`, out of scope) and inputgraph.py:936 |
| `check_overlap` | inputgraph.py:1512 | inputgraph.py:1598, inputgraph.py:1609 |
| `remove_dups` | inputgraph.py:1535 | inputgraph.py:1606, inputgraph.py:1614 |
| `merge_traversal` | inputgraph.py:1554 | inputgraph.py:1604, inputgraph.py:1612 |
| `get_circular_traversal` | inputgraph.py:1572 | inputgraph.py:1587 |
| `get_final_traversal` | inputgraph.py:1580 | handlers.py:151, 199, 216, 549, 590, 647, 717, 747, 764, 870, 887, 935, 954, 1011, 1027, 1036, 1125, 1180, 1293, 1494, 1769, 1928, 1951, 2038, 2061, 2155, 2224, 2362, 2474, 2603; pythongui/GuiParameters.py:407 |

`api.py` never calls any in-scope function directly. It reaches them only through
`handle_door_connectivity` (api.py:1309, 1353, 1390) and reads the `final_traversal`
field they produce (api.py:382, 859, 1429).

---

## Data Structures

- `self.matrix`: NxN int adjacency matrix, mutated in place by every augmentation
  step (inputgraph.py:378-379, 395-396, 486-487).
- `cip_list` / `selected_list`: list of *boundary candidates*. Each candidate is a
  list of exactly 4 node paths, ordered N, E, S, W, adjacent paths sharing their
  end node. Produced by `generate_multiple_bdy` (inputgraph.py:1481-1482), consumed
  by `generate_multiple_rel` -> `news.add_news` (inputgraph.py:1424).
- `rel_matrices`: list of NxN labeled matrices (the REL / regular edge labeling)
  returned by `generate_multiple_rel` (inputgraph.py:1450).
- `self.graph_list`: flat list of child `InputGraph` plan objects
  (inputgraph.py:1012, 1096).
- `self.graph_list_by_bdy`: list of lists, one inner list per boundary that yielded
  at least one plan (inputgraph.py:1013-1014, 1097-1098). handlers.py iterates this
  nested form so it can apply `floorplan_per_bdy_limit` per boundary
  (handlers.py:1859-1862, 2092-2095, 2284-2287, 2529-2532).
- `self.cardinal_constraints`: list of `(node, dir_idx)` with dir_idx 0..3 = N,E,S,W
  (declared inputgraph.py:151-156, set from api.py:1305 / api.py:1334).
- `self.dummy_node_adjacencies`: set of `(i, j)` pairs with i >= j from the
  post-ST-removal matrix (inputgraph.py:1502-1509); forwarded to children at
  inputgraph.py:1010 and read by handlers.py:821, 2309, 2421, 2552 as the
  `dummy_node_adj` field of the min-dim solver input.
- `circular_traversal` / `final_traversal`: list per room of `(x, y)` tuples walking
  the room outline counter-clockwise from its lower-left corner
  (inputgraph.py:1572-1578). `final_traversal` drops merged and extra nodes
  (inputgraph.py:1620-1622).
- `self.extraedges`: `[i, j]` pairs added by augmentation, diffed against the
  pre-augmentation matrix (inputgraph.py:513-516), rendered red in the returned
  graph edge set (inputgraph.py:328-332).

---

## Algorithm Walkthrough

### Q1. `irreg_multiple_dual` stage by stage (inputgraph.py:852-1121)

Stage 0, cardinal override: if `self.cardinal_constraints` is non-empty the
per-boundary plan cap is raised to the global cap, `floorplan_per_bdy_limit =
floorplan_limit` (inputgraph.py:862-866; defaults are 500 and 20 at
inputgraph.py:139-140).

Stage 1, degenerate case: 2 nodes / 1 edge returns a hardcoded 2-room dual and a
hardcoded REL (inputgraph.py:869-884).

Stage 2, biconnectivity augmentation: `bcn.biconnect` (inputgraph.py:886-892).

Stage 3, triangulation: `trng.triangulate` (inputgraph.py:899-905).

Stage 4, branch on Euler check `nodecnt - edgecnt + #triangles != 1`
(inputgraph.py:915). Both branches do the same work; they differ only in whether
separating triangles must be removed.

**Branch A (separating triangles present), inputgraph.py:916-1014**

- augmentation edges are turned into vertices via `transform.transform_edges`
  (inputgraph.py:917-928);
- `st.handle_STs(self.matrix, positions, 20)` returns up to 20 alternative
  ST-free matrices (inputgraph.py:929);
- outer loop over those matrices: `for cnt in range(len(ptpg_matrices))`
  (inputgraph.py:932);
- **boundaries are produced here**: `generate_multiple_bdy(...)` at
  inputgraph.py:946, returning `cip_list`;
- optional cardinal filter at inputgraph.py:950-952, optional dimension-fit
  pre-selection `dim_on_paths_bdy` at inputgraph.py:972, with the empty-result
  fallback `selected_list = cip_list` at inputgraph.py:978-979;
- **boundary loop**: `for bdys in selected_list:` at **inputgraph.py:981**;
- **RELs are produced here**: `rel_matrices = generate_multiple_rel(bdys, matrix,
  ...)` at **inputgraph.py:986**;
- **cross product is materialized here**: `for i in rel_matrices:` at
  **inputgraph.py:997**, each iteration constructing a fresh child
  `InputGraph` (inputgraph.py:998) and appending it to `self.graph_list`
  (inputgraph.py:1012) and to the per-boundary bucket (inputgraph.py:1011,
  1013-1014). `self.fpcnt` increments at inputgraph.py:1002 and the global cap is
  enforced at inputgraph.py:999-1001.

**Branch B (already a PTPG), inputgraph.py:1016-1108**

Same shape without `handle_STs` and without the ptpg-matrix loop:
`generate_multiple_bdy` at **inputgraph.py:1033**, cardinal filter at
inputgraph.py:1036-1038, selector at inputgraph.py:1045-1065, boundary loop
`for bdys in selected_list:` at **inputgraph.py:1067**, `generate_multiple_rel` at
**inputgraph.py:1072**, cross-product loop `for i in rel_matrices:` at
**inputgraph.py:1082**, appends at inputgraph.py:1095-1098. Note branch B forces
`mergednodes / irreg_nodes1 / irreg_nodes2 = []` on every child
(inputgraph.py:1090-1092) while branch A copies the ST-removal merge data
(inputgraph.py:1005-1007).

Stage 5, dualization: after both branches, every child in `graph_list_by_bdy` is
turned into room rectangles by `rdg.construct_dual` (inputgraph.py:1116-1121). Note
this loops `graph_list_by_bdy`, not `graph_list`, so a child that never made it
into a bucket would keep zero geometry.

So the answer to "where does the cross product become the list of output plans":
inputgraph.py:981 x 997 in branch A, inputgraph.py:1067 x 1082 in branch B.

### Q2. What `generate_multiple_bdy` varies (inputgraph.py:1453-1483)

It varies **corner assignments only**. Sequence:

- triangles, directed graph, boundary nodes/edges (inputgraph.py:1469-1471);
- `sr.get_shortcut` (inputgraph.py:1472) - the shortcuts are computed but this
  function never removes any; the shortcut-removal loop lives in the single-dual
  code (for example inputgraph.py:743-753 in `door_connectivity2`), not here;
- special case for the 3-node triangle: three hardcoded candidates
  (inputgraph.py:1473-1475);
- otherwise `cip.find_cip(bdy_ordered, shortcuts)` -> `news.find_bdy(cips)` ->
  `news.multiple_corners(...)` -> `news.all_boundaries(...)` ->
  `news.find_multiple_boundary(...)` (inputgraph.py:1477-1482).

Called modules, all under `GPLAN\GPLAN\source\`:

- `graphoperations/operations.py` as `opr` (`get_trngls`, `get_directed`, `get_bdy`,
  `ordered_bdy`);
- `irregular/shortcutresolver.py` as `sr` (`get_shortcut`);
- `boundary/cip.py` as `cip` (`find_cip`);
- `boundary/news.py` as `news`: `find_bdy` (news.py:21), `multiple_corners`
  (news.py:95, enumerates every choice of one corner node per CIP path),
  `all_boundaries` (news.py:121, pads a 1/2/3-corner set up to 4 corners using
  `itertools.combinations` / `combinations_with_replacement`), `find_multiple_boundary`
  (news.py:67, slices the ordered outer cycle at the 4 corner indices into 4 paths).

It touches nothing in `GPLAN\source\trial\`. It does not mutate `matrix`, and
returns `matrix, cip_list, nodecnt, edgecnt, mergednodes, irreg_nodes1,
irreg_nodes2, bdy_edges` unchanged apart from `cip_list` and `bdy_edges`
(inputgraph.py:1483) - the `mergednodes`/`irreg_nodes*` arguments are pass-through.

### Q3. What `generate_multiple_rel` varies (inputgraph.py:1412-1450)

It varies **flips**, both edge flips and vertex flips, over one seed REL:

- `news.add_news(bdys, matrix, nodecnt, edgecnt)` performs 4-completion for the
  given boundary (inputgraph.py:1424);
- contraction: `cntr.degrees`, `cntr.goodnodes`, `cntr.contract`
  (inputgraph.py:1427-1430) from `floorplangen/contraction.py`;
- expansion: `exp.basecase` then `exp.expand` until no contractions remain
  (inputgraph.py:1432-1434) from `floorplangen/expansion.py` - this yields the
  single seed REL appended at inputgraph.py:1435-1436;
- flip enumeration from `floorplangen/flippable.py`: `flp.get_flippable_edges`
  (inputgraph.py:1438, defined flippable.py:20), `flp.get_flippable_vertices`
  (inputgraph.py:1439, flippable.py:66), `flp.resolve_flippable_edge`
  (inputgraph.py:1442, flippable.py:120), `flp.resolve_flippable_vertex`
  (inputgraph.py:1446, flippable.py:147). New RELs are appended only when not
  already present by `np.array_equal` (inputgraph.py:1443, 1448).

The expansion choice itself is not varied; the loop `for mat in rel_matrix:`
(inputgraph.py:1437) iterates a list that grows while being iterated, so flips are
applied transitively to newly discovered RELs as well, giving the flip-graph
closure rather than a single flip layer.

### Q4. How `door_connectivity` differs from `irreg_multiple_dual` (inputgraph.py:340-520)

`door_connectivity` is a **conditioning** pass, not a generator. It shares stages
1-3 with `irreg_multiple_dual` (degenerate case inputgraph.py:354-359, biconnect
inputgraph.py:365-381, triangulate inputgraph.py:384-397) and then diverges:

- **`non_adj_list` parameter** (inputgraph.py:340): an optional list of node pairs
  the user marked as *must not be adjacent* (the red edges of the API). Its only
  effect is to set `is_non_adj = True` (inputgraph.py:349-351) and to swap three
  algorithm implementations for non-adjacency-aware twins:
  `bcn_non_adj.biconnect(self.matrix, non_adj_list)` (inputgraph.py:369) instead of
  `bcn.biconnect` (inputgraph.py:376); `trng_non_adj.triangulate(..., non_adj_list)`
  (inputgraph.py:385-387 and again at inputgraph.py:477-479) instead of
  `trng.triangulate` (inputgraph.py:390-392, 481-483); and the non-adj ST handler
  below.
- **Different septri handlers.** Instead of `st.handle_STs(matrix, positions, 20)`
  (what `irreg_multiple_dual` uses, inputgraph.py:929), it calls
  `st.handle_non_trivial_non_adj_ST_Door_connectivity(one_connected, self.matrix,
  positions, non_adj_list)` (inputgraph.py:437) when non-adjacency is present, or
  `st.handle_non_trivial_ST_Door_connectivity(one_connected, self.matrix, positions)`
  (inputgraph.py:440) otherwise. Both are defined in
  `source/irregular/septri.py` at septri.py:700 and septri.py:359 and both return
  `adjacencies, [], positions` (septri.py:1144, septri.py:697) - a **single**
  matrix wrapped in a list, an always-empty extra-nodes list, and the positions.
  It then re-verifies with `st.handle_STs_Door_connectivity(self.matrix,
  self.coordinates)` (inputgraph.py:492 or inputgraph.py:502, defined
  septri.py:1146, returning the surviving separating-triangle list at
  septri.py:1217).
- **Planarity repair.** After ST removal it re-checks the straight-line embedding
  with `check_intersection` (inputgraph.py:471) and re-triangulates if the drawing
  self-intersects (inputgraph.py:474-493).
- **Return value.** `return self, check_ptpg(separating_triangles1)`
  (inputgraph.py:520), where `check_ptpg` is the nested predicate at
  inputgraph.py:413-424 that is simply "no separating triangles left". The early
  degenerate exit returns `self, True` (inputgraph.py:359). It never returns
  floorplans; `handle_door_connectivity` then decides between the RFP path and the
  irregular path on that boolean (handlers.py:1745).

**Contract comparison against `GPLAN\documentation\door_connectivity.md`.**
(The path given in the task, `GPLAN_Revamp\documentation\door_connectivity.md`,
does not exist; the file lives at
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\documentation\door_connectivity.md`,
with a copy under `gplan_backend\GPLAN\documentation\`.)

Matches:

- red vs black edges as non-adjacency vs adjacency (doc line 140) maps onto the
  `non_adj_list` switch at inputgraph.py:349-351 / 369 / 385 / 437.
- `ptpg_graph` response field (doc line 190) is the augmented matrix that
  `door_connectivity` leaves behind, published at handlers.py:1724 and
  handlers.py:1735 and attached to the response at api.py:1422-1425.
- `plot_width` / `plot_height` "expand-only, batch ordered by required plot growth,
  least first" (doc lines 142-156) is exactly `scale_plot_dimension`
  (inputgraph.py:616-626 clamp and rank, inputgraph.py:642-646 reorder), invoked in
  the fallback at handlers.py:2173.
- `circular_coordinates` / `walls` (doc lines 206-220) are built from
  `final_traversal` at api.py:1429-1447.

Mismatches / gaps to flag:

1. **`non_adj` failure path is documented nowhere and is dead in code.**
   handlers.py:1712-1716 branches on `len(result) == 3` and shows "No augmentation
   found" when the third element is falsy, but `door_connectivity` has only two
   `return` statements (inputgraph.py:359 and inputgraph.py:520) and both return a
   2-tuple. The 3-tuple return that branch expects is commented out at
   inputgraph.py:370-373. So a genuinely unaugmentable non-adjacency request cannot
   surface the intended error; it will instead proceed with whatever
   `bcn_non_adj.biconnect` returned.
2. **The doc describes the HTTP surface, not this method.** Every field it lists
   (`count`, `limit`, `minDimEnabled`, `maxDimEnabled`, `rotation_enabled`,
   `plot_width`) is consumed in `api.py` / `handlers.py`. `InputGraph.door_connectivity`
   takes only `show_graph` and `non_adj_list` (inputgraph.py:340). Anyone reading
   the doc as a description of the engine entry point will look for parameters that
   are not there.
3. **`cardinal_constraints` is absent from `door_connectivity.md`** even though it
   is a top-level request field on this exact endpoint (api.py:1305, api.py:1332-1334)
   and changes the search strategy (inputgraph.py:862-866, 950-952, 959-966). It is
   documented only in the separate `cardinal_constraints.md`.
4. **`rectangular : bool` "remove this" and `dimensioned : bool` "DEPRECATED"**
   (doc lines 12-21) still steer live code on this path: `rectangular` selects
   `handle_single_oc` vs `handle_single` at api.py:1295-1299, and the door path
   passes `rectangular=True` internally at api.py:1008. The doc's "remove this"
   understates their current effect.
5. The doc's degenerate-case behavior is unstated: a 2-node/1-edge graph is
   short-circuited to a fixed unit-square pair (inputgraph.py:354-359) with no
   dimensioning applied at all.

### Q5. Is `door_connectivity2` reachable? No: dead code.

Grepping the entire repository for `door_connectivity2` returns hits in exactly
two places: its definition at inputgraph.py:650, and the knowledge-graph artifact
`graphify-out\graph.json.bak-20260725` (labels such as
`"InputGraph.door_connectivity2 (legacy door-connectivity full pipeline)"`). There
is **no** call site in `handlers.py`, `api.py`, `pythongui/`, or any test. Its body
is the old full single-dual pipeline: `st.handle_STs(self.matrix, positions, 1)`
(inputgraph.py:714), boundary identification with random shortcut removal
(inputgraph.py:727-756), 4-completion (inputgraph.py:759-761), contraction /
expansion (inputgraph.py:763-772) and `rdg.construct_dual` (inputgraph.py:773).
It returns `None` (inputgraph.py:667 or fall-through at inputgraph.py:775), which is
incompatible with the `(graph, checkPTPG)` unpacking every caller of the live
`door_connectivity` performs (handlers.py:1718, 1732) - so it is superseded, not a
drop-in alternative.

Note the same body also survives as a large commented-out block at the tail of
`door_connectivity` itself (inputgraph.py:529-595), which is where it was forked
from.

### Q6. `scale_plot_dimension` (inputgraph.py:597-646)

Runs only over plans whose index is in `valid`; everything else is skipped
(inputgraph.py:599-601). For each such plan:

- computes the plan's natural bounding extent by scanning `final_traversal`
  (inputgraph.py:605-610); this is why it must run **after** `get_final_traversal`;
- computes `scale_h = plot_height / height`, `scale_w = plot_width / width`, both
  guarded against zero, then **clamps both to >= 1.0** (inputgraph.py:616-619). That
  clamp is the "expand-only fit" contract: rooms are never shrunk below their
  min-dim solution; an axis that overflows the requested plot is left at natural
  size and the plot is conceptually enlarged;
- computes a growth score `diff = max(1, grow_w) * max(1, grow_h)`
  (inputgraph.py:624-626) and records `[diff, i]` (inputgraph.py:628);
- rescales geometry in place: every `final_traversal` point (inputgraph.py:630-633)
  and every `room_height`, `room_width`, `room_x`, `room_y`, `area`
  (inputgraph.py:634-639);
- finally sorts by `diff` ascending and rewrites `self.graph_list` in that order
  (inputgraph.py:642-646), so the plan needing the least plot growth is first.

`valid` is the caller's list of plan indices that the plot-relaxed min-dim solve
actually succeeded on: built at handlers.py:2091 and appended at handlers.py:2157
(and the non-PTPG twin at handlers.py:2604), then passed at handlers.py:2173 /
handlers.py:2619 and used again immediately after to decide which plans are emitted
(handlers.py:2174-2178, 2620-2624). So `valid` gates both "which plans get scaled"
and "which plans reach the client".

Sharp edge: the reorder at inputgraph.py:642-646 writes the ranked plans into the
**first** `len(reorder_mapping)` slots of a deepcopy of `graph_list`, but the caller
selects output by the *pre-sort* index set `valid` (handlers.py:2176). The two
agree only when `valid` happens to be `[0, 1, ..., n-1]`, which is the case on the
fallback path because every failed plan is popped from `graph_list`
(handlers.py:2167-2168). Any future change that leaves failed plans in the list
would silently mis-associate scaled geometry with output indices.

### Q7. `filter_boundaries_by_cardinal` (inputgraph.py:1365-1409)

It filters **boundary candidates by which of the 4 boundary paths a pinned node
lies on**, and it does so over all 8 symmetries of the rectangle:

- no constraints -> passthrough (inputgraph.py:1382-1383);
- `reflected = [list(reversed(path)) for path in reversed(bdys)]` produces the
  mirrored walk (inputgraph.py:1400);
- for each of `(bdys, reflected)` it tries all 4 rotations
  `candidate[rot:] + candidate[:rot]` (inputgraph.py:1401-1403);
- a rotation is kept when `all(node in rotated[dir_idx] for node, dir_idx in
  cardinal_constraints)` (inputgraph.py:1404), deduplicated by the tuple-of-tuples
  key (inputgraph.py:1405-1408).

Relation to `GPLAN\documentation\cardinal_constraints.md` (again, not at the path
given in the task; the file is at
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\documentation\cardinal_constraints.md`):

- doc lines 88-96 ("tries all 8 symmetries (4 rotations x 2 reflections) of every
  boundary candidate from `generate_multiple_bdy`") matches inputgraph.py:1400-1403
  exactly;
- doc lines 26-32 (semantics: a constrained room becomes adjacent to the N/E/S/W
  exterior vertex during 4-completion) matches the mechanism, since the kept
  ordering is what `news.add_news` wires up at inputgraph.py:1424;
- doc lines 72-82 (exhaustive search: `dim_on_paths_bdy` skipped, per-boundary cap
  lifted to the global limit) matches inputgraph.py:959-966 / 1045-1051 and
  inputgraph.py:862-866;
- doc lines 46-54 (geometric post-verification in api.py) matches api.py:374-409
  and api.py:1365.

One code detail the doc does not state: if the cardinal filter empties `cip_list`,
the generic "revert to old cip list" fallback at inputgraph.py:978-979 /
inputgraph.py:1064-1065 does **not** rescue it, because the filter is applied to
`cip_list` itself (inputgraph.py:951, 1037) before `selected_list` is derived from
it. An empty filtered `cip_list` therefore yields zero plans for that ptpg matrix,
which is precisely the condition the api.py ladder (api.py:1365-1406) and the
outer-ring augmentation (doc lines 100-135) exist to handle.

### Q8. Traversal helpers (inputgraph.py:1512-1625)

- `get_circular_traversal(room_x, room_y, room_width, room_height, room_index)`
  (inputgraph.py:1572-1578) returns the 4 corner tuples of one room rectangle in
  the order lower-left, upper-left, upper-right, lower-right.
- `check_overlap(list, edge)` (inputgraph.py:1512-1533) tests whether a given axis
  -aligned edge is collinear and overlapping with polygon side `i` of `list`,
  returning that side's index or -1. It handles the vertical case
  (inputgraph.py:1513-1522) and the horizontal case (inputgraph.py:1524-1532)
  separately; a diagonal edge falls through to -1.
- `merge_traversal(list1, list2, index)` (inputgraph.py:1554-1559) splices `list2`
  into `list1` after position `index`.
- `remove_dups(traversal)` (inputgraph.py:1535-1552) keeps only points occurring
  exactly once, which is how the two rooms' shared corner points get eliminated
  after splicing. Note it deletes *both* copies of any repeated point, not one.
- `get_final_traversal(graph)` (inputgraph.py:1580-1625) is the driver:
  1. builds a rectangle polygon for every room (inputgraph.py:1586-1588);
  2. for each `(irreg_node, merged_node)` pair it fuses the merged dummy room's
     polygon into the irregular room's polygon: find the shared side
     (inputgraph.py:1595-1598), rotate the second polygon so the contact point is
     first (inputgraph.py:1602), splice (inputgraph.py:1604), drop shared corners
     (inputgraph.py:1606), and handle partial overlap with a second rotate-and-splice
     (inputgraph.py:1608-1615). This is what turns an L-shaped or T-shaped room
     (created by ST removal) into a single non-rectangular outline;
  3. emits only rooms that are neither merged nodes nor extra nodes
     (inputgraph.py:1620-1622) and returns `graph.final_traversal`
     (inputgraph.py:1625).

Consuming field: `final_traversal`. It is read by api.py:1429 to build the `walls`
array and the `circular_coordinates` field of every serialized room
(api.py:1435-1448); overwritten wholesale by the gapless pass at api.py:859-862;
read by the cardinal geometric verifier at api.py:382; read by
`scale_plot_dimension` at inputgraph.py:605 and rescaled at inputgraph.py:630-633;
and drawn by the GUI at pythongui/drawing.py:47 and pythongui/drawing.py:61.

---

## Invariants And Preconditions

1. `door_connectivity` must be called before `irreg_multiple_dual` on the
   door-connectivity path: handlers.py:1710/1732 runs first and only then
   handlers.py:1830/1836/1838. After it, the graph is biconnected, so
   `oneconnected_dual` would always raise `BCNError` (commented explicitly at
   handlers.py:1821-1829).
2. Every boundary candidate is exactly 4 paths in N,E,S,W order, consecutive paths
   sharing an endpoint. `filter_boundaries_by_cardinal` preserves this under
   rotation and reflection (inputgraph.py:1400-1403); `news.add_news` depends on it
   (inputgraph.py:1424).
3. `dir_idx` is 0..3 = N,E,S,W and must index the boundary-path list, not a screen
   axis (inputgraph.py:151-156, inputgraph.py:1404).
4. `self.fpcnt` counts children created and is capped by `floorplan_limit`
   (inputgraph.py:999-1002, 1084-1087); the per-boundary cap
   `floorplan_per_bdy_limit` is enforced by the *caller* in handlers.py, not here
   (handlers.py:1862, 2095, 2287, 2532).
5. `graph_list_by_bdy` is the authoritative nested structure. Any plan not in a
   bucket never gets `construct_dual` geometry (inputgraph.py:1116-1121).
6. `scale_plot_dimension` requires `final_traversal` and `area` already populated on
   each valid plan (inputgraph.py:605, inputgraph.py:639); handlers.py satisfies
   this at handlers.py:2149 and handlers.py:2155.
7. `get_final_traversal` is not idempotent: it appends to `graph.circular_traversal`
   and `graph.final_traversal` (inputgraph.py:1588, 1622) without clearing them.
   handlers.py works around this by resetting both on cloned plans
   (handlers.py:1974-1975, handlers.py:2402).
8. Both door-connectivity ST handlers return an empty extra-nodes list
   (septri.py:697, septri.py:1144), so the merge bookkeeping at
   inputgraph.py:446-450 is currently unreachable and `mergednodes` stays empty on
   this path.

---

## Failure Modes

- **`multiple_floorplan` raises immediately.** inputgraph.py:1160 reads
  `rel_matrix = self.graph_list.rel_matrix_list` - `graph_list` is a Python list
  (inputgraph.py:147), which has no `rel_matrix_list` attribute, so this is an
  unconditional `AttributeError` the first time the loop body runs. Both call sites
  (handlers.py:1069, handlers.py:1474) are GUI "dimensioned multiple" paths, not the
  API door-connectivity path. Additionally inputgraph.py:1191-1196 indexes
  `room_x[i]` with the *plan* index `i`, which is a room index confusion.
- **Empty cardinal filter yields no plans**: inputgraph.py:951 / 1037 can return an
  empty `cip_list`, and the empty-selection fallback at inputgraph.py:978 restores
  only `cip_list` (already empty). Handled upstream by the api.py ladder
  (api.py:1365-1406).
- **`selected_list` fallback masks a bad dimension fit**: when `dim_on_paths_bdy`
  rejects every boundary, inputgraph.py:978-979 / 1064-1065 silently revert to the
  full unfiltered list, so a plot-infeasible request degrades into an exhaustive
  sweep rather than an error.
- **Non-adjacency augmentation failure is unreportable**: see Q4 mismatch 1
  (handlers.py:1712-1716 vs inputgraph.py:359/520).
- **`scale_plot_dimension` shadows its loop variable**: the outer loop uses `i`
  (inputgraph.py:599) and the inner traversal loop reuses `i`
  (inputgraph.py:630-633). By the time `reorder_mapping.append([diff, i])` runs at
  inputgraph.py:628 the value is still correct (the append precedes the inner loop),
  but any statement added after inputgraph.py:633 that expects the outer `i` will
  read the clobbered value.
- **`remove_dups` removes both duplicates** (inputgraph.py:1546-1548). For polygons
  where a legitimate vertex coincides with another room's vertex more than twice,
  the fused outline loses points.
- **`check_overlap` only handles axis-aligned edges** (inputgraph.py:1513, 1524);
  any non-axis-aligned geometry silently returns -1 and the merge at
  inputgraph.py:1601 never fires, leaving the dummy room unmerged and therefore
  dropped from output at inputgraph.py:1620-1622 - a hole in the plan, which is what
  `rectangularize_output` (api.py:859) later has to heal.
- **Deep matplotlib import guarded**: `show_graph=True` imports matplotlib lazily
  (inputgraph.py:405, 496, 505); the server path never passes it.

---

## Coupling (what breaks if you change this)

- **Boundary-path order** (`bdys` = [N,E,S,W]): changing it breaks
  `filter_boundaries_by_cardinal` (inputgraph.py:1404), `news.add_news`
  (inputgraph.py:1424), `_ring_order_satisfies` in api.py:153-161 which explicitly
  mirrors the filter, and `plan_satisfies_cardinal`'s dir_idx mapping
  (api.py:401-408).
- **`final_traversal` shape** (list per room of point pairs): consumed by
  api.py:1429-1447 (walls, circular_coordinates), api.py:382-391 (cardinal check),
  api.py:859-862 (gapless rewrite), inputgraph.py:605 and 630-633
  (`scale_plot_dimension`), pythongui/drawing.py:47 and :61. Note api.py:859 writes
  **lists** `[x, y]` while inputgraph.py:1574-1577 writes **tuples**; anything doing
  identity or type checks on the elements must accept both.
- **`(graph, checkPTPG)` return arity of `door_connectivity`**: unpacked at
  handlers.py:1718 and handlers.py:1732. Changing it also requires fixing the
  already-stale 3-tuple branch at handlers.py:1712.
- **`graph_list_by_bdy` nesting**: handlers.py iterates it at four sites
  (handlers.py:1859, 2092, 2284, 2529) and depends on inner-list-per-boundary to
  apply `floorplan_per_bdy_limit`. Flattening it would silently disable that cap.
- **`dummy_node_adjacencies` set format** `(i, j)` with `i >= j`
  (inputgraph.py:1505-1508): read as `dummy_node_adj` by the min-dim solver input
  at handlers.py:821, 2309, 2421, 2552.
- **`floorplan_per_bdy_limit` override under cardinal constraints**
  (inputgraph.py:866): removing it re-caps the exhaustive search that
  `cardinal_constraints.md` lines 72-82 promises.
- **`self.graph_list` ordering after `scale_plot_dimension`**: handlers.py:2174-2178
  and 2620-2624 emit by index membership in `valid`; the reorder at
  inputgraph.py:642-646 assumes those indices are dense from 0.

---

## Dead Or Duplicated Code

- **`door_connectivity2` (inputgraph.py:650-775) is dead.** Zero call sites outside
  its own definition anywhere in the repo; the only other hits are stale nodes in
  `graphify-out\graph.json.bak-20260725`. It returns `None`, incompatible with the
  live 2-tuple contract.
- **Commented-out duplicate of the same pipeline** at inputgraph.py:529-595, inside
  `door_connectivity` after its `return` at inputgraph.py:520 - unreachable even if
  uncommented in place.
- **Unreachable merge bookkeeping** at inputgraph.py:446-450: both door-connectivity
  ST handlers hardcode an empty extra-nodes list (septri.py:697, septri.py:1144).
- **Commented-out biconnectivity-failure return** at inputgraph.py:370-373, whose
  removal orphaned the handler branch at handlers.py:1712-1716.
- **Commented-out `get_circular_traversal` prototype** at inputgraph.py:1561-1570,
  superseded by the parameterized version at inputgraph.py:1572.
- **Commented-out `lettershape` dispatcher** at inputgraph.py:1485-1494;
  `staircaseshaped` (inputgraph.py:1496) is the surviving one-line wrapper around
  `StaircaseShapedFloorplan`, called once at handlers.py:1034.
- **`multiple_floorplan` (inputgraph.py:1126) is effectively dead**: its first
  executable statement inside the plan loop raises `AttributeError`
  (inputgraph.py:1160). Its two call sites (handlers.py:1069, handlers.py:1474) are
  GUI-only dimensioned-multiple paths, never the API door-connectivity path.
- **Branch A and branch B of `irreg_multiple_dual`** (inputgraph.py:916-1014 vs
  inputgraph.py:1016-1108) are near-identical copies of the boundary/REL/child-plan
  logic; only the ST handling and the merge-node propagation differ. A fix applied
  to one and not the other is the most likely regression in this file. Note the
  branch B copy at inputgraph.py:1039-1043 redundantly assigns `start_time1` twice.
- **Duplicated timing decorator**: a module-level `timing_decorator`
  (inputgraph.py:65) and an identical class-level one (inputgraph.py:168); the
  class-level one shadows the module-level one for methods defined after
  inputgraph.py:168, which includes every in-scope method.
- **`generate_multiple_bdy` computes `shortcuts`** (inputgraph.py:1472) and passes
  them to `cip.find_cip` (inputgraph.py:1478) but never removes any, unlike the
  single-dual variants (compare inputgraph.py:743-753).

---

## Open Questions

1. Is the "No augmentation found" path (handlers.py:1712-1716) meant to be revived?
   The 3-tuple return it needs exists only as comments at inputgraph.py:370-373, and
   `bcn_non_adj.biconnect` apparently returns a set of edge sets there ("Here
   multiple edge sets are there we have to choose 1 here", inputgraph.py:373). What
   does it actually return today, and is silently taking whatever it gives correct?
2. Documentation path drift: the task referenced
   `GPLAN_Revamp\documentation\door_connectivity.md` and
   `GPLAN_Revamp\documentation\cardinal_constraints.md`, which do not exist. The
   live copies are under `GPLAN\documentation\` with duplicates under
   `gplan_backend\GPLAN\documentation\`. Which copy is canonical, and are the two
   in sync?
3. `scale_plot_dimension`'s reorder writes ranked plans into `new_graph_list[0..n-1]`
   (inputgraph.py:644-645) while the caller filters output by the original `valid`
   indices (handlers.py:2176). Is the dense-index assumption intentional, or should
   the reorder also rewrite `valid`?
4. `irreg_multiple_dual` never resets `self.graph_list` / `self.graph_list_by_bdy`
   on entry; handlers.py:1841 clears `graph_list` after the call but not
   `graph_list_by_bdy`. Is calling `irreg_multiple_dual` twice on the same
   `InputGraph` (which the api.py retry ladder avoids by building a fresh
   `InputGraph` at api.py:1384) ever intended?
5. The knowledge graph node `inputgraph_door_connectivity2` is labeled "legacy
   door-connectivity full pipeline" and is still edge-connected in
   `graphify-out\graph.json.bak-20260725`. The code says it is unreferenced. The
   graph and the code agree that it is legacy; the graph does not mark it dead. Not
   a contradiction, but the graph should probably record the zero-call-site fact.
6. `filter_boundaries_by_cardinal` is decorated with `@timing_decorator`
   (inputgraph.py:1364) but is a hot inner-loop function called once per ptpg matrix
   (inputgraph.py:951); is the per-call log line acceptable at 500-candidate scale?
