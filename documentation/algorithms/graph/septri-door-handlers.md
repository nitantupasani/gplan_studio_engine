# septri.py: door-connectivity ST handlers

Scope: `handle_non_trivial_ST_Door_connectivity` (L359), `handle_non_trivial_non_adj_ST_Door_connectivity` (L700), `handle_STs_Door_connectivity` (L1146), `remove_st_edge_selection` (L1270), `handle_STs_with_edge_selection` (L1378), all in
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\irregular\septri.py` (1471 lines; whole file read this session).
Detection / edge-cover machinery (`handle_STs` L273, `get_sep_triangles_and_edges` L1218, `calc_all_triangles` L1264, cover functions L66-L219, `point_in_triangle` L37, `point_in_triangle2` L1450) belongs to the sibling dossier `septri-detection-covers`; only call sites are cited here.

All paths below are absolute; `septri.py` alone means the file above.

## Purpose

These are the separating-triangle (ST) eliminators used by the **door-connectivity** flow. Unlike the classic `handle_STs` (septri.py:273), which destroys an ST by *bisecting* one of its edges and inserting a dummy vertex (septri.py:238-244, `extra_nodes` returned at 357), the door-connectivity handlers destroy STs **without adding any vertex**: they either delete an ST edge that borders only one triangular face, or perform a diagonal flip (delete the edge, add the edge joining the two opposite vertices). The point is to keep the room count fixed (no dummy rooms, no room merging) and to spend the graph's "sacrificial" edges (the ones biconnectivity augmentation and triangulation added) before touching edges the user actually asked for.

The user's requested adjacencies are carried in `one_connected`, which is a snapshot of the adjacency matrix taken *before* augmentation (inputgraph.py:360-361, i.e. before the bcn edges at inputgraph.py:377-379 and the triangulation edges at inputgraph.py:394-397). Everything in these two handlers keys off `one_connected[a][b] != 1` meaning "this edge is not user-requested, it is safe to spend".

## Where It Sits In The Pipeline

Live chain (verified):

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py:1309` and `api.py:1353` call `handle_door_connectivity(ui, graph)`.
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py:1686` `def handle_door_connectivity(...)`, which calls `graph.door_connectivity(show_graph=drawGUI, non_adj_list=non_adj_list)` at handlers.py:1710 (non-adjacency branch, gated by `ui.get_isNonAdj() == 1` at handlers.py:1703) or `graph.door_connectivity(show_graph=drawGUI)` at handlers.py:1732 (plain branch).
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py:340` `def door_connectivity(self, show_graph=False, non_adj_list=None)`: biconnect, triangulate, then
  - inputgraph.py:437 -> `st.handle_non_trivial_non_adj_ST_Door_connectivity(one_connected, self.matrix, positions, non_adj_list)` when `is_non_adj`;
  - inputgraph.py:440 -> `st.handle_non_trivial_ST_Door_connectivity(one_connected, self.matrix, positions)` otherwise.
- Post-check: `st.handle_STs_Door_connectivity(self.matrix, self.coordinates)` at inputgraph.py:492 (after re-triangulation) and inputgraph.py:502 (no re-triangulation needed); its result feeds `check_ptpg` (inputgraph.py:413-424) and the method's return at inputgraph.py:520.

Not reachable: `handle_STs_with_edge_selection` and therefore `remove_st_edge_selection`. See Dead Or Duplicated Code.

## Entry Points (file:line)

- septri.py:359 `handle_non_trivial_ST_Door_connectivity(one_connected, adjacency, positions)` - live, plain door-connectivity path.
- septri.py:700 `handle_non_trivial_non_adj_ST_Door_connectivity(one_connected, adjacency, positions, non_adj_list)` - live, non-adjacency door-connectivity path.
- septri.py:1146 `handle_STs_Door_connectivity(adjacency, positions)` - live, read-only ST checker.
- septri.py:1270 `remove_st_edge_selection(st_with_internal_node, graph, total_STs, not_user_ST_flag, one_connected, all_triangles, num_nodes, positions)` - dead (called only from septri.py:1436 and septri.py:1441).
- septri.py:1378 `handle_STs_with_edge_selection(one_connected, adjacency, positions)` - dead (all call sites commented out: inputgraph.py:439, inputgraph.py:532, inputgraph.py:712).

## Data Structures

Built identically in all three live functions (septri.py:360-413, 710-766, 1161-1214):

- `graph`: `nx.Graph`, node `i` carries attribute `pos = positions[i]` (septri.py:362-363). Edges mirror `adjacency` (septri.py:364-367).
- `positions`: a **dict** `{node_index: (x, y)}`, not a list. Proof of dict-ness: `positions.values()` at septri.py:507 and the caller's `self.coordinates = final_positions; self.coordinates = [v for v in self.coordinates.values()]` at inputgraph.py:442-443.
- `all_triangles`: every 3-clique, from `nx.enumerate_all_cliques` (septri.py:371-373), deduped by `np.unique`.
- `trianlular_faces` (sic): triangles with no vertex inside them (septri.py:396). Only used as a local sink; never returned.
- `edge_to_faces: {(u,v) sorted tuple: [face tuples]}` (septri.py:397-400). In the door handlers each face is stored as `tuple(face)` (septri.py:400 / 753), whereas `handle_STs` stores the raw list (septri.py:328) and `handle_STs_Door_connectivity` also stores the raw list (septri.py:1201). `len(edge_to_faces[edge])` is the exterior/interior test: 1 = boundary edge of the triangulated region, 2 = interior edge.
- `separating_triangles: [tuple(sorted(3 vertices))]`, `separating_edges`, `separating_edge_to_triangles: {edge: [ST, ...]}` (septri.py:404-413).
- `total_STs = len(separating_triangles)` (septri.py:414 / 767): the budget used by the revert test `len(new_separating_triangles) > total_STs - 1`.
- Non-adjacency variant only: `non_adj_matrix` built at septri.py:703-706 and **never read again** (only other mentions of `non_adj_list` are the membership tests at septri.py:848 and 986).
- Edge-selection (dead) variant: `st_with_internal_node: {internal_node: [ST tuples]}` built at septri.py:1417-1428 with `point_in_triangle2` (septri.py:1450), which additionally requires the interior node to be adjacent to all three triangle vertices (septri.py:1468), i.e. a genuine K4.

## Algorithm Walkthrough

### Q1. "Trivial" vs "non trivial": the classification does not exist in the code

There is **no** trivial/non-trivial test anywhere in the engine. A repo-wide grep for `trivial` in `.py` files (excluding `node_modules`) hits only: the two function names (septri.py:359, septri.py:700), their two call sites (inputgraph.py:437, inputgraph.py:440), and unrelated code (`trivialL()` in `source/lettershape/lshape/Lshaped.py:77`, prose comments in `source/floorplangen/contraction.py:4` and `expansion.py:3`, a Tkinter comment in `Space_Optimization/uinegNew.py:5483`). No branch, flag, or predicate classifies an ST as trivial. The only historical trace is a changelog line, `GPLAN/documentation/work_history_timeline.md:76` ("Removal of NonTrivial ST / Bug fix in NonTrivial ST removal").

What the code *does* classify, and what the names should be read as, is two orthogonal binary distinctions, both quoted verbatim:

1. **User edge vs non-user edge**: `if(one_connected[edge[0]][edge[1]]!=1 and (len(edge_to_faces[edge]) == 1)):` (septri.py:444) and `if (one_connected[edge[0]][edge[1]]!=1 and len(edge_to_faces[edge]) == 2):` (septri.py:478). The later passes drop the guard literally: `if(True and (len(edge_to_faces[edge]) == 1)):` (septri.py:580) and `if (True and len(edge_to_faces[edge]) == 2):` (septri.py:611). The comment at septri.py:557 calls the non-removable case "separating triangle was given from user".
2. **Exterior vs interior edge**: `len(edge_to_faces[edge]) == 1` (delete outright) vs `== 2` (must be flipped, because deleting an interior edge would leave a quadrilateral face).

Nothing is "done for trivial ones" because the category is not represented. If the question is "what is the alternative treatment", the answer is `handle_STs` (septri.py:273): it covers STs with subdivided edges and dummy vertices (septri.py:238-244) and returns `extra_nodes_pair` (septri.py:353, 357); the door handlers never do that and always return `[]` (septri.py:697, 1144).

### Q2. `handle_non_trivial_ST_Door_connectivity` (septri.py:359-697), phase by phase

Phase A, build (septri.py:360-368): `nx.Graph` from `adjacency` with `pos` attributes; `origin_pos = positions` (same object, not a copy, at septri.py:368).

Phase B, detect (septri.py:371-413): all 3-cliques (septri.py:371-373); for each, scan every other node with `point_in_triangle` (septri.py:388-390, geometry only, no adjacency requirement); no interior point -> face, recorded in `edge_to_faces` (septri.py:396-400); interior point -> ST, recorded in `separating_triangles` / `separating_edges` / `separating_edge_to_triangles` (septri.py:404-413). `total_STs` at septri.py:414.

Phase C, Case 1, delete non-user exterior edges, iterated to a fixpoint (septri.py:428-462). `while(removed)` (septri.py:429) restarts the whole sweep after any deletion. For each key of `separating_edge_to_triangles` it first skips edges whose STs are all already gone (`all_trig_done`, septri.py:432-440), then tests septri.py:444. On a hit: `graph.remove_edge` (septri.py:447), the face lists of the deleted edge's triangle are trimmed (septri.py:450-454), and every ST containing that edge is dropped with `total_STs -= 1` (septri.py:457-462).

Phase D, Case 2, flip non-user interior edges (septri.py:465-559). Guard at septri.py:478. The two opposite vertices `node1`, `node2` are recovered from the two incident faces (septri.py:480-493). The flip is `graph.remove_edge(edge)` (septri.py:496) plus `graph.add_edge(sorted([node1,node2]))` (septri.py:499-500). Feasibility check (septri.py:503-528): recompute triangles (septri.py:503), require `nx.is_planar` (septri.py:504), re-derive positions/adjacency and recount STs with `get_sep_triangles_and_edges` (septri.py:520); if `(not planar) or (len(new_separating_triangles) > total_STs-1)` (septri.py:521) the flip is undone (septri.py:523-524) and the loop continues (septri.py:528, `print("changes revoked")` at 527). On success, `edge_to_faces` is surgically rewritten for the new diagonal and the two rewritten faces (septri.py:532-545, ending with `del edge_to_faces[edge]`), then the STs containing the removed edge are dropped and `total_STs` decremented (septri.py:549-555). The `else` at septri.py:556-559 only sets `not_removed = True`, a variable that is never read afterwards.

Phase E, Case 3, delete exterior edges **including user edges** (septri.py:560-595), announced by `print("user gave ST")` (septri.py:562) and a TODO to actually ask the user (septri.py:561). Structurally a copy of Case 1 with the guard replaced by `True` (septri.py:580); the ST removal loop iterates `list(separating_triangles)` and removes in place (septri.py:592-595).

Phase F, Case 4, flip interior edges including user edges (septri.py:597-692), a copy of Case 2 with the guard replaced by `True` (septri.py:611) and *without* the `total_STs -= 1` decrement (compare septri.py:552 with septri.py:683-687).

Phase G, return (septri.py:694-697): `positions = origin_pos` then `return adjacencies, [], positions`.

**Which edge is chosen, and by what priority.** Priority is by *pass*, not by any scoring function: (1) non-user exterior, (2) non-user interior flip, (3) user exterior, (4) user interior flip. Within a pass the choice is simply the first eligible key encountered while iterating `separating_edge_to_triangles`, i.e. Python dict insertion order, which follows the `np.unique`-sorted triangle order from septri.py:373. There is no tie-break, no preference for the edge that kills the most STs (that idea lives in the cover functions, septri.py:159-219, used only by `handle_STs`).

**Vertex or room merging: none.** No node is added or deleted anywhere in septri.py:359-697; only `graph.remove_edge` / `graph.add_edge` are called. The returned `extra_nodes` is the literal `[]` at septri.py:697, so the caller's merge bookkeeping at inputgraph.py:446-450 (`mergednodes`, `irreg_nodes1`, `irreg_nodes2`) never runs on this path.

### Q3. Diff of `handle_non_trivial_non_adj_ST_Door_connectivity` (septri.py:700-1144) against the previous function

Method: `sed -n '359,698p'` vs `sed -n '700,1144p'` piped through `diff -u`. Result: **the second function is a line-for-line copy of the first plus one extra pass, with exactly the deltas listed below.** Everything not listed differs only in whitespace or comment text (for example `## case 1 - we remove exrerior edge which is not given by user.` at septri.py:427 vs `##Case 1 - we remove exterior edge which is not given by user and is an exterior edge.` at septri.py:773).

Blocks that differ:

1. **Prologue (septri.py:701-708)**: builds `non_adj_matrix` from `non_adj_list`. Never read afterwards.
2. **Dropped debug (septri.py:415-422)**: `import matplotlib.pyplot as plt` plus the commented "BEFORE ST REMOVEAL" plot exist only in the first function.
3. **Case 1**: identical logic (septri.py:429-462 vs 775-808); the copy adds a no-op `continue` (septri.py:809) and a commented cleanup block (septri.py:810-812).
4. **Case 2, non-adjacency guard (septri.py:845-852)**: the copy computes `added_edge` *before* touching the graph and skips the flip when the new diagonal is forbidden:
   `if added_edge in non_adj_list: continue` / `else: graph.remove_edge(...); graph.add_edge(...)`. The original just removes then adds (septri.py:495-500).
5. **Case 2, relayout target**: original writes `positions = nx.planar_layout(graph)` (septri.py:517); copy writes `origin_pos = nx.planar_layout(graph)` (septri.py:869).
6. **Case 2, revert branch**: the original ends the revert with `continue` (septri.py:528); the copy has no `continue` (after septri.py:879), so it falls through into the `edge_to_faces` surgery and ST bookkeeping (septri.py:883-905) for a flip that was just undone.
7. **Case 2, counter**: original decrements `total_STs -= 1` when dropping STs (septri.py:552); the copy does not (septri.py:901-903). The copy adds `continue` at septri.py:906 and its `else` (septri.py:907-909) drops the "given from user" comment.
8. **Case 3**: original prints `"user gave ST"` and resets `remove_edges = []` (septri.py:562-563); the copy does neither (septri.py:911-912). Original removes STs while iterating `list(separating_triangles)` (septri.py:592-595); the copy buffers into `removing_st` (septri.py:939-946) and appends a `continue` (septri.py:947) plus the same commented cleanup block (septri.py:948-950).
9. **Case 4**: same three deltas as Case 2, that is the non-adjacency guard (septri.py:984-990), the missing `continue` in the revert branch (after septri.py:1017), and an `else: continue` without `not_removed = True` (septri.py:1045-1046).
10. **Case 5, new (septri.py:1048-1140)**: "remove irrespective of non-adjacency". Verified with a second diff (`sed -n '953,1046p'` vs `sed -n '1049,1140p'`): it is Case 4 with exactly two edits, the non-adjacency guard replaced by an unconditional remove/add (septri.py:1080-1082) and the `else` branch restoring `not_removed = True` (septri.py:1138-1139). Nothing else differs.
11. **Epilogue**: the original does `positions = origin_pos` before returning (septri.py:695-697); the copy returns without it (septri.py:1141-1144).

So `non_adj_list` changes exactly three things: it gates the two interior flips (septri.py:848, 986), it motivates the dead `non_adj_matrix` (septri.py:703-706), and it forces a fifth fallback pass that ignores the gate (septri.py:1048-1140).

### Q4. Role of `one_connected`

`one_connected` is the pre-augmentation adjacency matrix (inputgraph.py:360-361), so `one_connected[u][v] == 1` means "the user drew this door adjacency". The parameter is read in exactly two places per handler, both in the *first* two passes: septri.py:444 and septri.py:478 in the plain handler, septri.py:790 and septri.py:828 in the non-adjacency handler. It therefore enables the "spend only augmentation edges" branch: Cases 1 and 2 may only delete or flip edges that biconnectivity augmentation (inputgraph.py:377-379) or triangulation (inputgraph.py:394-397) introduced. Cases 3, 4 and 5 replace the same test with `True` (septri.py:580, 611) or drop it (septri.py:928, 966, 1062), so once the cheap edges are exhausted the handler starts destroying user-requested adjacencies.

Why one-connectivity matters: the input the user draws may be only 1-connected and is certainly not triangulated; the pipeline must biconnect and triangulate it before an ST-free PTPG exists, and those synthetic edges are exactly the edges whose removal costs the user nothing (they resurface as `extraedges`, drawn red, at inputgraph.py:513-516 and 331-332). Every ST in a triangulated graph must lose one of its three edges; preserving door intent means preferring a synthetic edge. In `remove_st_edge_selection` the same matrix serves the same purpose through `not_user_ST_flag` (septri.py:1283-1284, 1316-1317).

Naming caveat: the argument is named `one_connected` in both septri and inputgraph, but it is not a connectivity flag, it is a matrix snapshot.

### Q5. `handle_STs_Door_connectivity` and `remove_st_edge_selection`

`handle_STs_Door_connectivity` (septri.py:1146-1217) is **not** a wrapper around anything. Its body is a verbatim copy of the detection half of `handle_STs` (septri.py:288-341 vs 1161-1214, with `edge_to_faces[edge].append(face)` at septri.py:1201) and it ends at `return separating_triangles` (septri.py:1217). It removes nothing: it is the pass/fail oracle for the whole door-connectivity method, consumed by `check_ptpg` at inputgraph.py:422-424 via inputgraph.py:492/502 and returned at inputgraph.py:520. Its docstring (septri.py:1147-1157) still describes `handle_STs` and lists a `num_expected_outputs` parameter that the signature does not have.

`remove_st_edge_selection` (septri.py:1270-1375) is the alternative, user-choice-aware eliminator (dead, see below). Its inputs are `st_with_internal_node` (built by the caller at septri.py:1417-1428, keyed by the vertex *inside* the ST) and `not_user_ST_flag`. The flag is the user-choice hook: when it is True, every candidate edge that the user drew is skipped, `if(not_user_ST_flag and (one_connected[edge[0]][edge[1]]==1)): continue` (septri.py:1283-1284 for strategy A, septri.py:1316-1317 for strategy B). Two strategies per ST:

- Strategy A, plain deletion (septri.py:1286-1308): compute `nx.common_neighbors(graph, edge[0], edge[1])`; if the only two common neighbors are the internal node `i` and the ST's third vertex (`len(nbrs)==2 and (i in nbrs) and (third_node in nbrs)`, septri.py:1294), the edge borders nothing else and is deleted (septri.py:1295), the affected entries of `st_with_internal_node` and `all_triangles` are pruned (septri.py:1297-1304), and `total_STs -= 1` (septri.py:1306).
- Strategy B, flip onto the internal node (septri.py:1315-1369): on a `deepcopy` of the graph, add `(nbr, i)` and remove `edge`, provided `nbr` is outside the triangle, is not already adjacent to `i`, and the edge still exists (septri.py:1320-1323). Feasibility is then tested exactly as in the big handlers: `nx.is_planar` (septri.py:1328), recount STs via `get_sep_triangles_and_edges` (septri.py:1334), and revert if `(not planar) or (len(separating_triangles) > total_STs-1)` (septri.py:1335-1342). On success it recomputes `nx.planar_layout` into `final_positions` (septri.py:1360-1361), recounts `total_STs` (septri.py:1366) and commits `graph = graph_copy` (septri.py:1367).

Conflict handling when the user choice is infeasible: the handler simply gives up on that ST inside the pass. The escalation lives in the caller, `handle_STs_with_edge_selection` (septri.py:1378-1447), which runs the restricted pass first, `remove_st_edge_selection(..., True, ...)` at septri.py:1436, and then, only `if total_STs > 0` (septri.py:1440), re-runs it unrestricted, `remove_st_edge_selection(..., False, ...)` at septri.py:1441. That is the same "sacrifice user edges as a last resort" ladder as Cases 3-5 in the live handlers. If even the unrestricted pass fails (every candidate flip reverted), there is no error and no signal: septri.py:1443-1447 returns the adjacency as-is, and the surviving STs would only be caught later by `check_ptpg`.

### Q6. Reachability

- `handle_non_trivial_ST_Door_connectivity`: **live**. api.py:1309 / api.py:1353 -> handlers.py:1686 -> handlers.py:1732 -> inputgraph.py:340 -> inputgraph.py:440.
- `handle_non_trivial_non_adj_ST_Door_connectivity`: **live**. api.py:1303 sets the non-adjacency list -> handlers.py:1703-1710 -> inputgraph.py:340 -> inputgraph.py:437.
- `handle_STs_Door_connectivity`: **live**, as the checker at inputgraph.py:492 and inputgraph.py:502 (the third mention, inputgraph.py:431, is commented out).
- `handle_STs_with_edge_selection`: **dead**. Every call site is a comment: inputgraph.py:439, inputgraph.py:532, inputgraph.py:712. Nothing in handlers.py or api.py references it (grep for the name across the repo returns only septri.py:1378, the three commented inputgraph lines, and the independent copy in `source/irregular/septri_non_adj.py:253`).
- `remove_st_edge_selection`: **dead by transitivity**. Its only call sites are septri.py:1436 and septri.py:1441, inside the dead function.

### Q7. Return values

| Function | Returns | Consumed at |
| --- | --- | --- |
| `handle_non_trivial_ST_Door_connectivity` (septri.py:697) | `adjacencies` (list of one `numpy` int matrix, `[nx.to_numpy_array(graph).astype(int)]`, septri.py:696), `[]` (extra nodes), `positions` (dict) | inputgraph.py:440, unpacked into `ptpg_matrices, extra_nodes, final_positions`; matrix at inputgraph.py:444, coordinates at inputgraph.py:442-443, merge bookkeeping at inputgraph.py:446-450 (never entered, since `extra_nodes` is `[]`) |
| `handle_non_trivial_non_adj_ST_Door_connectivity` (septri.py:1144) | same three, same shapes (septri.py:1143) | inputgraph.py:437 |
| `handle_STs_Door_connectivity` (septri.py:1217) | `separating_triangles` only, a list of sorted 3-tuples | inputgraph.py:492/502 -> `check_ptpg` (inputgraph.py:422-424) -> returned as the second element of `door_connectivity` at inputgraph.py:520 |
| `handle_STs_with_edge_selection` (septri.py:1447) | `adjacencies`, `[]`, `final_position` | dead |
| `remove_st_edge_selection` (septri.py:1375) | `total_STs`, `graph` (nx), `final_positions` | septri.py:1436, 1441 (dead) |
| `handle_STs` (septri.py:357), for contrast | `adjacencies` (up to `num_expected_outputs` matrices, septri.py:346-356) and `extra_nodes_pair` (list of `{dummy_vertex: [u, v]}`, septri.py:244) - **two** values, no positions | inputgraph.py:713-714 in `door_connectivity2` |

Differences from plain `handle_STs`: (a) arity 3 vs 2, the third being the possibly-relaid-out `positions` dict, because these handlers can invalidate the straight-line embedding; (b) exactly one adjacency matrix instead of N alternatives, since there is no cover enumeration; (c) node count is preserved and `extra_nodes` is always empty, so the rdg-relevant lists `mergednodes` / `irreg_nodes1` / `irreg_nodes2` (inputgraph.py:447-450) stay empty and no irregular/dummy rooms are produced; (d) the door handlers *delete* adjacencies (which is why `extraedges` at inputgraph.py:513-516 only records *added* edges), whereas `handle_STs` only ever adds vertices and edges.

## Invariants And Preconditions

- Input must already be biconnected and triangulated: the callers do that first (inputgraph.py:366-397) and the flip logic assumes every interior edge has exactly two incident triangular faces (septri.py:480-481).
- `positions` must be a dict keyed by `0..n-1` with `(x, y)` values: used as `positions[i]` (septri.py:363), `positions.values()` (septri.py:507), and `.values()` again by the caller (inputgraph.py:443).
- `adjacency` must be square, symmetric, 0/1 (septri.py:364-367 reads both triangles of the matrix).
- Node set is never modified. The returned matrix has the same size and index order as the input, which the caller relies on when diffing against `original_one_connected` (inputgraph.py:513-516).
- `one_connected` must be the *pre-augmentation* matrix; if it were captured after augmentation, Cases 1 and 2 would find no eligible edge and every ST would be resolved by sacrificing a user edge.
- The revert test is a monotonicity invariant, not an optimality one: a flip is kept only if the recomputed ST count is at most `total_STs - 1` (septri.py:521, 654, 873, 1011, 1103, and septri.py:1335 in the dead path).
- Success is not asserted inside these functions; the only ST-free assertion is `check_ptpg(handle_STs_Door_connectivity(...))` at inputgraph.py:492-520.

## Failure Modes

1. **Non-adjacency variant applies bookkeeping to reverted flips.** The `continue` present at septri.py:528 is missing from the corresponding revert branches at septri.py:873-879, 1011-1017 and 1103-1109. After a revert the code still runs septri.py:883-896 (which ends in `del edge_to_faces[edge]` for an edge that is back in the graph) and septri.py:900-905 (which drops STs that still exist). Downstream that yields a corrupted `edge_to_faces` and silently under-reported STs, which `handle_STs_Door_connectivity` will later catch as `check_ptpg == False`.
2. **The non-adjacency guard can never fire on the API path.** `added_edge = sorted([node1, node2])` is a `list` (septri.py:846, 984) and is tested with `in non_adj_list` (septri.py:848, 986), but the list supplied by the request builder contains **tuples**: `non_adj_edges = [(e["source"], e["target"]) ...]` at `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\local_engine_bridge.py:66-67`, passed unchanged through api.py:1303 -> `GuiParameters.set_non_adj_list` (`GPLAN/GPLAN/pythongui/GuiParameters.py:212-213`) -> handlers.py:1708 -> inputgraph.py:437. `[a, b] in [(a, b)]` is `False` in Python, and the tuples are not sorted either, so the flip is free to create a forbidden adjacency. Needs a runtime check to confirm end to end.
3. **`total_STs` drifts.** It is decremented in Case 1 (septri.py:459) and Case 3 (septri.py:594) and in Case 2 of the plain handler (septri.py:552), but not in Case 4 of the plain handler (septri.py:683-687) nor in Cases 2/4/5 of the non-adjacency handler (septri.py:901-903, 1039-1041, 1131-1133). Since the revert threshold is `total_STs - 1`, a stale, too-large `total_STs` makes later flips too easy to accept.
4. **Positions plumbing is inconsistent and partly lost.** `final_positions` is assigned (septri.py:518, 651, 870, 1008, 1100) but never returned. The plain handler's Case 2 relayout writes to `positions` (septri.py:517), which is then overwritten by `positions = origin_pos` at septri.py:695, discarding it; Case 4 writes to `origin_pos` (septri.py:650), which survives. The non-adjacency handler always writes relayouts to `origin_pos` (septri.py:869, 1007, 1099) and never copies them into `positions` before `return ... positions` (septri.py:1144), so it effectively returns the input coordinates unless a revert happened (septri.py:878, 1016, 1108). The caller then re-checks the embedding and may re-triangulate (inputgraph.py:471-491), which papers over this.
5. **ST recount uses stale coordinates.** `get_sep_triangles_and_edges(all_triangles, num_nodes, positions, adjacency)` (septri.py:520, 653, 872, 1010, 1102) is called with the *pre-flip* `positions` even though the topology just changed, so the geometric interior test can misclassify. `point_in_triangle2` (septri.py:1450-1470) partly compensates by also requiring K4 adjacency (septri.py:1468), and it returns `None` (falsy) instead of `False` on the negative path (no `return False`).
6. **No guard against creating a parallel adjacency.** The flip adds `(node1, node2)` without checking whether that edge already exists (septri.py:499-500, 632-633, 851-852, 989-990, 1081-1082). If it does, `add_edge` is a no-op and the removal at septri.py:496 leaves a quadrilateral face while `edge_to_faces` is rewritten at septri.py:532 as if two triangles existed. The dead `remove_st_edge_selection` does guard this (`graph_copy.has_edge(nbr,i)==False`, septri.py:1320).
7. **`KeyError` exposure on `edge_to_faces`.** Cases 3-5 re-iterate the same `separating_edge_to_triangles` keys and index `edge_to_faces[edge]` (septri.py:580, 611, 928, 966, 1062) after Case 2 may have deleted keys (septri.py:545). The only protection is the `all_trig_done` skip (septri.py:598-606); with the reverted-flip bug (item 1) that protection is exactly what gets corrupted.
8. **List mutated while iterated.** septri.py:450-454 removes from `edge_to_faces[curr_edge]` while looping over `edge_to_faces[edge]` (the same list when `curr_edge == edge`). Harmless only because exterior edges have exactly one face.
9. **User intent is destroyed silently.** Cases 3-5 delete user edges with no record: `extraedges` (inputgraph.py:513-516) tracks only *added* edges, so a dropped door adjacency never surfaces in the response. The TODO acknowledging this is at septri.py:561 ("give choice / take choice from user to remove or not to remove"); the only trace is `print("user gave ST")` at septri.py:562.
10. **`not_removed` is written and never read** (septri.py:416, 424, 558, 691, 770, 908, 1139): there is no failure signal out of these functions.
11. **Dead-path bugs in `remove_st_edge_selection`** (moot today, land mines if it is revived): the internal-node variable `i` is shadowed by the inner loops `for i in st_with_internal_node.keys()` at septri.py:1297 and septri.py:1344, so after the first prune `i` refers to some other node for the remainder of the sweep; `edge` is shadowed by the comprehension variable at septri.py:1301 and 1350; lists are mutated while being iterated at septri.py:1302 and 1351 (silently skips entries); and `total_STs = len(st_with_internal_node)` (septri.py:1432) counts distinct interior *nodes*, not separating triangles, so a node inside three STs counts once and the revert threshold at septri.py:1335 is wrong from the start.

## Coupling (what breaks if you change this)

- **Return arity and types** are hard-wired at inputgraph.py:437 and inputgraph.py:440 (three values), inputgraph.py:442-443 (`final_positions` must be a dict), inputgraph.py:444 (`ptpg_matrices[0]` must be a numpy matrix), inputgraph.py:445 (`np.count_nonzero(self.matrix == 1) / 2` assumes a 0/1 symmetric matrix). Adding dummy vertices here would immediately activate the merge bookkeeping at inputgraph.py:446-450, which the rest of the door path has not been exercised with.
- **`handle_STs_Door_connectivity` is the acceptance test.** Any change that leaves an ST behind flips `check_ptpg` to False (inputgraph.py:422-424) and changes `door_connectivity`'s second return value (inputgraph.py:520), which handlers.py:1712-1720 unpacks. Note the checker uses `point_in_triangle` (septri.py:1189) while the handlers' internal recount uses `point_in_triangle2` (septri.py:1232-1234) with the extra K4 requirement, so the two disagree by construction: the handler can believe an ST is gone while the checker still reports it.
- **`one_connected` capture point.** Moving inputgraph.py:360-361 after the augmentation calls (inputgraph.py:377-397) would make Cases 1 and 2 no-ops.
- **Edge deletions feed the red-edge rendering.** `extraedges` (inputgraph.py:513-516) is compared against `original_one_connected`, and edges land in the UI as red at inputgraph.py:331-332. Changing what these handlers add or remove changes the red/black edge report the frontend receives.
- **Re-triangulation loop.** If these handlers leave a non-planar straight-line embedding, inputgraph.py:471-491 re-triangulates and adds edges back, potentially reintroducing STs; the checker then runs on the retriangulated matrix (inputgraph.py:492).
- **Non-adjacency contract.** Fixing failure mode 2 (list vs tuple) will start rejecting flips that are accepted today, which will push more STs into Case 5 (septri.py:1048) and change outputs for every non-adjacency plan.

## Dead Or Duplicated Code

- `handle_STs_with_edge_selection` (septri.py:1378-1447) and `remove_st_edge_selection` (septri.py:1270-1375): dead. All external call sites are commented out (inputgraph.py:439, 532, 712).
- `non_adj_matrix` (septri.py:703-706): computed, never read.
- `final_positions` (septri.py:518, 651, 870, 1008, 1100): assigned, never returned.
- `not_removed` (septri.py:416, 424, 558, 691, 770, 908, 1139) and `trianlular_faces` (septri.py:375, 396, 728, 749, 1176, 1197): write-only.
- `remove_edges` (septri.py:425, 448, 563, 584, 772, 794, 932): collected, only used by commented-out cleanup blocks (septri.py:810-812, 948-950).
- `import matplotlib.pyplot as plt` at septri.py:417: unused, inside a function, for a commented-out plot (septri.py:419-422).
- Massive intra-file duplication: Case 3 is Case 1 with the user guard replaced by `True`; Case 4 is Case 2 likewise; Case 5 (septri.py:1048-1140) is Case 4 minus the non-adjacency guard (verified by diff, two edits total); the entire second handler is the first handler plus the eleven deltas listed in Q3; and `handle_STs_Door_connectivity` (septri.py:1161-1214) duplicates the detection half of `handle_STs` (septri.py:288-341). Detection blocks are duplicated a fourth time in `get_sep_triangles_and_edges` (septri.py:1218-1260), with `point_in_triangle2` instead of `point_in_triangle`.
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\irregular\septri_non_adj.py` holds its own `remove_st_edge_selection` (line 103) and `handle_STs_with_edge_selection` (line 253). The module is imported as `st_non_adj` at inputgraph.py:42 but never dereferenced (a grep for `st_non_adj.` in inputgraph.py returns nothing), so that file is dead too.
- The whole tree is mirrored under `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\GPLAN\...` (identical line numbers in the grep output); per project memory the engine source of truth is the `GPLAN/` submodule.

## Open Questions

- What did "non trivial" originally mean? No predicate exists in the code (see Q1); only `GPLAN/documentation/work_history_timeline.md:76` records the phrase. Anyone renaming these functions should confirm with the original author whether "non trivial" meant "ST that cannot be killed by simple edge bisection" (i.e. the door-connectivity constraint that forbids dummy rooms).
- Is the missing `continue` in the non-adjacency revert branches (failure mode 1) an intentional divergence or a copy-paste slip? The plain handler has it at septri.py:528 and 661; the copy lost it in all three places.
- Is failure mode 2 (list vs tuple in the non-adjacency membership test) actually hit in production? It should be confirmed with a request carrying red edges before "fixing" it, since fixing it will change existing plan outputs.
- Should Cases 3-5 be allowed at all without user confirmation, given the TODO at septri.py:561 and the fact that a deleted user adjacency is not reported anywhere in the response?
- Why do the handlers detect with `point_in_triangle` (septri.py:388) but re-verify with `point_in_triangle2` (septri.py:1232), whose K4 requirement (septri.py:1468) is strictly stronger? This is the sibling dossier's territory, but it directly determines whether the `total_STs - 1` guard is comparing like with like.
- Knowledge graph agreement: `graphify explain "handle_non_trivial_ST_Door_connectivity()"` reports exactly the call edges the code shows (`get_edges` L397, `point_in_triangle` L388, `get_sep_triangles_and_edges` L520, `calc_all_triangles` L503). No contradiction found; the graph merely omits the `check_intersection` call at septri.py:515 and the `nx.planar_layout` calls.
