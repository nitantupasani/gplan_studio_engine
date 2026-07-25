# inputgraph-single-dual-core

Scope: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py`, the module-level exceptions and decorator (lines 47-73), `InputGraph.__init__` (115), `is_connected` (181), `irreg_single_dual` (202), `update_gclass_with_edges` (316), `single_floorplan` (779), `polyonalinput` (849), `oneconnected_dual` (1200).

Out of scope (sibling dossier `inputgraph-multidual-doors`): `door_connectivity` (340), `scale_plot_dimension` (597), `door_connectivity2` (650), `irreg_multiple_dual` (852), `multiple_floorplan` (1126), and the module-level helpers from 1364 onward. Def-line inventory used to fix these boundaries: `grep -n "^    def |^def "` over the file returned exactly the offsets cited here.

---

## Purpose

`InputGraph` is the single mutable object the whole GPLAN pipeline passes around. It holds an adjacency matrix plus per-room geometry arrays, and its methods mutate that same object in place rather than returning new values. This dossier covers the *single*-dual half of the class: build the object from an edge list, check connectivity, run the classic rectangular-dual pipeline once (`irreg_single_dual`), run the cut-vertex variant (`oneconnected_dual`), and turn one already-generated REL into a dimensioned floorplan (`single_floorplan`).

`irreg_single_dual` is the canonical GPLAN algorithm chain: biconnectivity augmentation, triangulation, edge-to-vertex transformation, separating-triangle elimination, boundary/CIP identification, 4-completion (NEWS), contraction, expansion, rectangular dual construction. Everything else in the file is a variation on that spine.

`OCError` / `BCNError` are the control-flow signal that the exact one-connected path failed, and every caller in `handlers.py` treats them as "fall back to the irregular path".

## Where It Sits In The Pipeline

```
main.py:22  /  api.py:1003, api.py:1384  /  local_engine_bridge.py:68
        -> InputGraph(nodecnt, edgecnt, edgeset, node_coordinates)   inputgraph.py:115
                |
        handlers.handle_single (handlers.py:751)
        handlers.handle_single_oc (handlers.py:1078)
        handlers.handle_circulation (handlers.py:492)
        handlers.handle_door_connectivity (handlers.py:1686)
                |
        graph.is_connected()          inputgraph.py:181
        graph.irreg_single_dual()     inputgraph.py:202
        graph.oneconnected_dual(s)    inputgraph.py:1200
        graph.single_floorplan(...)   inputgraph.py:779   (needs irreg_multiple_dual first)
```

`api.py` never calls any in-scope method directly. A grep of `api.py` for `\.irreg_single_dual|\.single_floorplan|\.oneconnected_dual|\.polyonalinput|\.update_gclass_with_edges|\.is_connected\(|OCError|BCNError` returns exactly one hit, `api.py:960`, and that is `nx.is_connected(g)` on a networkx graph, not the method. A grep of `api.py` for `graph\.[a-z_]+\(` returns no matches at all. `api.py` reaches these methods only through the handler wrappers it imports at `api.py:13` (`from GPLAN.handlers import *`) and calls at `api.py:1297` (`handle_single_oc`), `api.py:1299` (`handle_single`), `api.py:1309`, `api.py:1353`, `api.py:1390` (`handle_door_connectivity`), `api.py:1325` (`handle_multiple_oc`), `api.py:1327` (`handle_multiple`).

## Entry Points (file:line)

Definitions:

| Symbol | Definition | Decorated |
| --- | --- | --- |
| `OCError` | inputgraph.py:47 | n/a |
| `BCNError` | inputgraph.py:55 | n/a |
| `timing_decorator` (module level) | inputgraph.py:65 | applied at 1364, 1452 |
| `InputGraph.__init__` | inputgraph.py:115 | no |
| `InputGraph.timing_decorator` (class level, shadows the module one inside the class body) | inputgraph.py:168 | n/a |
| `InputGraph.is_connected` | inputgraph.py:181 | yes, `@timing_decorator` at inputgraph.py:178 |
| `InputGraph.irreg_single_dual` | inputgraph.py:202 | **no decorator** |
| `InputGraph.update_gclass_with_edges` | inputgraph.py:316 | **no decorator** |
| `InputGraph.single_floorplan` | inputgraph.py:779 | yes, inputgraph.py:778 |
| `InputGraph.polyonalinput` | inputgraph.py:849 | yes, inputgraph.py:848 |
| `InputGraph.oneconnected_dual` | inputgraph.py:1200 | yes, inputgraph.py:1199 |

Call sites in `handlers.py` (the only production caller; `main.py` is the Tk GUI driver):

- `is_connected`: handlers.py:752 (`handle_single`), handlers.py:1042 (`handle_multiple`), handlers.py:1687 (`handle_door_connectivity`); also main.py:34.
- `irreg_single_dual`: handlers.py:561, 709, 732 (three branches of `handle_circulation`), handlers.py:760 (`handle_single`, non-dimensioned), handlers.py:1086 and 1089 (`handle_single_oc`, OCError/BCNError fallbacks), handlers.py:1759 and 1761 (`handle_door_connectivity`, same fallbacks), handlers.py:2221 (`handle_door_connectivity`, non-PTPG branch). Commented out at handlers.py:1501.
- `oneconnected_dual("single")`: handlers.py:1082, handlers.py:1756.
- `oneconnected_dual("multiple")`: handlers.py:358, 611, 1157, 1206, 1331, 1365, 1465, 1833.
- `single_floorplan`: handlers.py:621 and 628 (`handle_circulation`), handlers.py:924 and 931 (`handle_single`, dimensioned, in a retry loop), handlers.py:1004 (`handle_letter_shape`), handlers.py:1166 and 1173 (`handle_single_oc`).
- `update_gclass_with_edges`: handlers.py:1727 and handlers.py:1738, both inside `handle_door_connectivity`, both wrapped as `ui.set_edges(graph.update_gclass_with_edges(gclass))`.
- `polyonalinput`: handlers.py:1502 only, inside `handle_poly` (handlers.py:1499). `handle_poly` itself is called only from main.py:56 under `gclass.command == "poly"`.

## Data Structures

### Everything `__init__` creates (inputgraph.py:115-166)

| Attribute | Line | Type | Meaning |
| --- | --- | --- | --- |
| `nodecnt` | 116 | int | Node count. Mutated upward by every augmentation step. |
| `edgecnt` | 117 | int | Edge count. Mutated upward by every augmentation step. |
| `matrix` | 118 | `np.ndarray[int]`, shape (nodecnt, nodecnt) | Symmetric 0/1 adjacency, filled from `edgeset` at 119-121 using only `edges[0]` and `edges[1]`; any third element of an edge tuple (the colour that `update_gclass_with_edges` emits) is ignored. |
| `bdy_nodes` | 122 | list | Outer boundary nodes, filled by `opr.get_bdy` at 270. |
| `bdy_edges` | 123 | list | Outer boundary edges, filled by `opr.get_bdy` at 270. |
| `irreg_nodes1` | 124 | list (list-of-lists after `irreg_multiple_dual`) | First endpoint of each merged/irregular pair. |
| `irreg_nodes2` | 125 | list | Second endpoint of each merged/irregular pair. |
| `mergednodes` | 126 | list | Dummy nodes introduced by separating-triangle removal (263) and shortcut removal (289) that must be merged back into their parent room. |
| `degrees` | 127 | `None`, later `np.ndarray` from `cntr.degrees` (304) | Per-node degree used by contraction. |
| `room_x` | 128 | `np.zeros(nodecnt)` | Left x of each room. |
| `room_y` | 129 | `np.zeros(nodecnt)` | Bottom y of each room. |
| `room_height` | 130 | `np.zeros(nodecnt)` | Room heights. |
| `room_width` | 131 | `np.zeros(nodecnt)` | Room widths. |
| `nodecnt_list` | 132 | list | Documented at 103 as "node count for each rel matrix", but never appended to. `irreg_multiple_dual` assigns a bare int into it (`new_graph.nodecnt_list = self.nodecnt` at 1009 and 1094). Effectively a misnamed scalar. Not touched by anything in this dossier's scope. |
| `nonrect` | 133 | bool | Set True at 237 whenever any biconnectivity or triangulation edge was added, i.e. the dual will not be a clean rectangle. |
| `extranodes` | 134 | list (list-of-lists after `irreg_multiple_dual`) | Nodes created by edge-to-vertex transformation (241, 248). |
| `extraedges` | 135 | list of `[i, j]` | Edges added relative to the original one-connected matrix. Populated **only** by `door_connectivity` at inputgraph.py:516. `irreg_single_dual` never writes it. |
| `area` | 136 | list | Per-room area, filled by `opr.calculate_area` at 843. |
| `rel_matrix_list` | 137 | list of `np.ndarray` | Regular edge labelings. `irreg_single_dual` never appends to this; `irreg_multiple_dual` (1004, 1089) and `oneconnected_dual` (1334) do. |
| `floorplan_exist` | 138 | bool | Set True at 830 when `floorplan_to_st` succeeds. The GUI retry loop at handlers.py:926 spins on it. |
| `floorplan_limit` | 139 | int, 500 | Global cap on multiple floorplans. |
| `floorplan_per_bdy_limit` | 140 | int, 20 | Per-boundary cap; raised to `floorplan_limit` at 866 when cardinal constraints are set. |
| `floorplan_limit_undimensioned` | 141 | int, 500 | Cap for the undimensioned multiple path. |
| `fpcnt` | 142 | int, 0 | Count of generated floorplans. Set at 1341 by `oneconnected_dual("multiple")`. |
| `coordinates` | 143 | list of `np.ndarray` | Planar embedding positions, one per node, from the caller. |
| `dummy_node_adjacencies` | 144 | `set` of `(i, j)` | Adjacency snapshot taken after separating-triangle dummy nodes are inserted, via `store_dummy_node_adjacencies` (defined at 1502) called at 259. Only written inside the ST branch, so it stays an empty set when the input has no separating triangles. |
| `circular_traversal` | 145 | list | Per-room circular wall traversal; written by handlers (handlers.py:1975, 2401), not by anything in scope. |
| `final_traversal` | 146 | list | Filled by `inputgraph.get_final_traversal(graph)` in handlers (for example handlers.py:764). |
| `graph_list` | 147 | list of `InputGraph` | One child graph per generated floorplan. Populated by `irreg_multiple_dual`. |
| `graph_list_by_bdy` | 148 | list of list of `InputGraph` | Same, grouped by boundary candidate; consumed in handlers.py:1859, 2092, 2284, 2529. |
| `logger` | 149 | `logging.Logger` | The module logger created at 63. |
| `name_coords` | 150 | list | Room-label centre coordinates; written by the GUI parameter layer (GuiParameters.py:423) and read by api.py:866, 1430. |
| `cardinal_constraints` | 156 | list of `(node, dir_idx)`, `dir_idx` 0..3 = N,E,S,W | Exterior-facing pins. Set from outside at api.py:1305, 1334, 1386. Comment block at 151-155 documents the ordering. |

`__init__` also does a crossing repair at 159-166: it extracts x and y from `node_coordinates`, calls `gc.check_intersection(x_coord, y_coord, self.matrix)` at 161, and if the drawing self-intersects it replaces `self.coordinates` with `nx.planar_layout` output (162-164). This runs before any algorithm sees the coordinates, so triangulation always gets a crossing-free embedding.

### Geometry array shape contract

Three different shapes coexist under the same names:

- After `irreg_single_dual` (313-315): `room_x/room_y/room_width/room_height` are flat `np.ndarray`, one entry per room.
- After `irreg_multiple_dual` or `oneconnected_dual("multiple")` (1342-1358): they are **lists of arrays**, one per floorplan, and `extranodes`/`mergednodes`/`irreg_nodes1/2` become lists of lists (1347-1350, 1359-1362).
- After `single_floorplan` (833-838): flattened back down to a single flat array for the chosen floorplan.

This is the single largest source of confusion in the file.

## Algorithm Walkthrough

### `is_connected` (181-200)

Recursive DFS over `self.matrix` (inner `dfs` at 182-186), starting at node 0, then `all(visited)` at 195. Prints "Graph is connected." / "Graph is not connected." at 197/199 and returns the bool. It does not repair anything; the caller does, for example handlers.py:753 `connect_graph.one_connected(graph.matrix)`.

Note the inner loop at 184 rebinds the name `is_connected` as the loop variable (`for neighbor, is_connected in enumerate(...)`), shadowing the method name inside `dfs`. Harmless here because `dfs` recurses by name `dfs`, not by `self.is_connected`.

### `irreg_single_dual` (202-315), exact call order

Line 211: early return for the degenerate 2-node / 1-edge graph. It writes hardcoded geometry at 212-215 and returns at 216 having made **zero** calls. Everything below is skipped.

| # | Call | Line | Module | Conditional on |
| --- | --- | --- | --- | --- |
| 1 | `bcn.is_biconnected(self.matrix)` | 219 | `graphoperations/biconnectivity.py:18` | always (unless the 211 early return fired) |
| 2 | `bcn.biconnect(self.matrix)` | 220 | `graphoperations/biconnectivity.py:86` | only if `not bcn.is_biconnected(...)` |
| 3 | `trng.triangulate(self.matrix, bcn_edges_added, self.coordinates)` | 228 | `graphoperations/triangularity.py:254` | always |
| 4 | `transform.transform_edges(...)` | 242 | `floorplangen/transformation.py:13` | once per edge in `bcn_edges` (loop 240-245); zero times if the graph was already biconnected |
| 5 | `transform.transform_edges(...)` | 249 | `floorplangen/transformation.py:13` | once per edge in `trng_edges` (loop 247-252) |
| 6 | `opr.get_trngls(self.matrix)` | 255 | `graphoperations/operations.py:71` | always, inside the Euler test `nodecnt - edgecnt + len(triangles) != 1` |
| 7 | `st.handle_STs(self.matrix, positions, 1)` | 256 | `irregular/septri.py:273` | only if the Euler test at 255 is true (separating triangles present). The literal `1` asks for one output matrix; `irreg_multiple_dual` passes `20` at 929. |
| 8 | `store_dummy_node_adjacencies(self.matrix)` | 259 | same module, `inputgraph.py:1502` | same condition as 7 |
| 9 | `opr.get_trngls(self.matrix)` | 268 | `graphoperations/operations.py:71` | always |
| 10 | `opr.get_directed(self.matrix)` | 269 | `graphoperations/operations.py:59` | always |
| 11 | `opr.get_bdy(triangular_cycles, digraph)` | 270 | `graphoperations/operations.py:85` | always |
| 12 | `sr.get_shortcut(self.matrix, self.bdy_nodes, self.bdy_edges)` | 272 | `irregular/shortcutresolver.py:14` | always |
| 13 | `opr.ordered_bdy(self.bdy_nodes, self.bdy_edges)` | 278 | `graphoperations/operations.py:238` | only in the `else` of `edgecnt == 3 and nodecnt == 3` (275). The triangle case hardcodes `bdys = [[0], [0,1], [1,2], [2,0]]` at 276 and makes no calls. |
| 14 | `cip.find_cip(bdy_ordered, shortcuts)` | 279 | `boundary/cip.py:11` | same as 13 |
| 15 | `news.find_bdy(cips)` then `news.bdy_path(..., bdy_ordered)` | 281 | `boundary/news.py:21` and `boundary/news.py:35` | only if `len(cips) <= 4` |
| 16 | `sr.remove_shortcut(shortcuts[index], triangular_cycles, self.matrix)` | 285 | `irregular/shortcutresolver.py:34` | only in the `else` at 282, looped `while len(shortcuts) > 4` (283), on a random index from 284 |
| 17 | `opr.get_trngls(self.matrix)` | 293 | `graphoperations/operations.py:71` | each iteration of the 283 loop |
| 18 | `opr.ordered_bdy(...)` | 294 | `graphoperations/operations.py:238` | only in the `> 4` branch, after the loop |
| 19 | `cip.find_cip(...)` | 295 | `boundary/cip.py:11` | same branch |
| 20 | `news.find_bdy` + `news.bdy_path` | 296 | `boundary/news.py:21`, `:35` | same branch |
| 21 | `news.add_news(bdys, self.matrix, self.nodecnt, self.edgecnt)` | 299 | `boundary/news.py:249` | always (4-completion; `nodecnt += 4` at 301) |
| 22 | `cntr.degrees(self.matrix)` | 304 | `floorplangen/contraction.py:23` | always |
| 23 | `cntr.goodnodes(self.matrix, self.degrees)` | 305 | `floorplangen/contraction.py:35` | always |
| 24 | `cntr.contract(self.matrix, goodnodes, self.degrees)` | 306 | `floorplangen/contraction.py:187` | always |
| 25 | `exp.basecase(self.matrix, self.nodecnt)` | 310 | `floorplangen/expansion.py:29` | always |
| 26 | `exp.expand(self.matrix, self.nodecnt, cntrs)` | 312 | `floorplangen/expansion.py:53` | looped `while len(cntrs) != 0` (311) |
| 27 | `rdg.construct_dual(self.matrix, self.nodecnt, self.mergednodes, self.irreg_nodes1)` | 313 | `floorplangen/rdg.py:20` | always; returns `[room_x, room_y, room_width, room_height]` |

Mutation side effects worth remembering: `matrix` and `edgecnt` are updated in place at 221-224 (biconnectivity edges) and 231-234 (triangulation edges); `nonrect` is set at 237; `nodecnt`/`edgecnt` are recomputed from the matrix at 260-261 after `handle_STs`; the shortcut-removal loop hand-increments `nodecnt += 1` and `edgecnt += 3` at 290-291.

`irreg_single_dual` produces geometry only. It never appends to `rel_matrix_list`.

### `oneconnected_dual(string)` (1200-1362)

Everything `irreg_single_dual` does not do for cut-vertex graphs.

1. **Guard** (1209-1210): `if bcn.is_biconnected(self.matrix): raise BCNError`. This method is exclusively for one-connected input; a biconnected graph is rejected immediately.
2. **Cut-vertex and component decomposition** (1213-1218): deepcopy the matrix, build `nx.from_numpy_array`, then `bcn.get_cutvertices(nxgraph)` (`biconnectivity.py:31`) and `onc.get_biconnected_components(nxgraph)` (`oneconnectivity.py:12`).
3. **Feasibility check** (1225-1241): count how many components each cut vertex belongs to and how many cut vertices each component holds. If any cut vertex sits in more than 2 components (1236-1238) or any component holds more than 2 cut vertices (1239-1241), `raise OCError`. This is the structural restriction: the block-cut tree must be a path, not a branching tree.
4. **Per-component sub-solve** (1244-1263): for each component build a sub-adjacency matrix via `onc.get_adj_matrix` (1245, `oneconnectivity.py:22`) and an index remap via `onc.get_dict` (1246, `:33`), construct a fresh `InputGraph` (1257-1260) with a `nx.planar_layout` embedding (1255), and call `graph.irreg_multiple_dual()` at 1263. So `oneconnected_dual` is a *client* of the multiple-dual path, not of `irreg_single_dual`.
5. **Corner identification** (1265-1277): read the NEWS labels out of each REL matrix to find the four corner rooms `[nw, ne, se, sw]`.
6. **Corner filter** (1284-1299): keep only those component floorplans where every cut vertex of that component occupies exactly 2 of the 4 corners. That is the gluing precondition: a cut vertex must own a whole corner of its block so two blocks can be butted together along it.
7. **Re-index and collect** (1301-1318): invert the dict (1301), build the encoded matrix with `opr.get_encoded_matrix` (1305, `operations.py:211`), map every cell back to global node ids (1313-1315), append.
8. **Second failure gate** (1321-1323): if any component produced zero surviving encoded matrices, `raise OCError`.
9. **Merge** (1326-1334): `onc.recurse(ems, 0, final, individual)` (1328, `oneconnectivity.py:46`) enumerates the cartesian product of per-component choices, `onc.merge` (1331, `:62`) glues each combination into one encoded matrix, `onc.convert_to_rel` (1333, `:165`) turns it back into a REL which is appended to `self.rel_matrix_list`.
10. **The `string` parameter** selects the output shape, and nothing else:
    - `"single"` (1337-1339): one `rdg.construct_dual(self.rel_matrix_list[0], nodes + 4, [], [])`; flat arrays; `fpcnt` untouched.
    - `"multiple"` (1340-1362): sets `fpcnt = len(rel_matrix_list)` (1341), resets `room_x/y/width/height`, `area`, `extranodes`, `mergednodes`, `irreg_nodes1/2` to empty lists (1342-1350), then loops `construct_dual` per REL appending to those lists (1352-1358) and pushes an empty list into `mergednodes`/`irreg_nodes1`/`irreg_nodes2`/`extranodes` per floorplan (1359-1362).
    - Any other string silently produces nothing but a populated `rel_matrix_list`. There is no `else` branch.

    Note `construct_dual` is passed `nodes + 4` where `nodes = len(matrix)` captured at 1215, i.e. the *original* node count plus NEWS, and empty `mergednodes`/`irreg_nodes` lists (1339, 1353-1354). One-connected output is assumed to have no merged or irregular nodes.

### `single_floorplan` (779-847)

This is the dimensioning stage. It does **not** generate a dual: it consumes `self.rel_matrix_list` and the per-floorplan geometry that `irreg_multiple_dual` (or the manual wrapping in `handle_letter_shape`) produced.

- Parameters (779-780): `min_width, min_height, max_width, max_height, symm_rooms, min_ar, max_ar, plot_width, plot_height`. Docstring at 784-792 says the width/height/aspect ones are per-room lists, `symm_rooms` is a string, and the plot dims are scalars.
- **Padding for synthetic rooms** (797-810): the caller supplies constraints only for real rooms, so the method appends defaults for each merged node (797-803: min 0, max 10, ar 0..10000) and each extra node (804-810: min 0, max 10000, ar 0..10000). It indexes `self.mergednodes[0]` and `self.extranodes[0]`, i.e. the counts from the **first** floorplan only, but then reuses the same padded arrays for every REL in the loop at 811.
- **Per-REL attempt loop** (811-847):
  - `opr.get_encoded_matrix(rel_matrix.shape[0] - 4, self.room_x[i], self.room_y[i], self.room_width[i], self.room_height[i])` at 813-814 (`operations.py:211`) turns the dimensionless dual into a room-id grid.
  - `bc.block_checker(encoded_matrix_deepcopy, symm_rooms)` at 817-818 (`dimensioning/block_checker.py:4`) returns `[boolean, ver_list, hor_list]`. Symmetry constraints enter here.
  - **The floorplangen/dimensioning function that consumes the constraints is `fpts.floorplan_to_st`** at 821-823, defined at `dimensioning/floorplan_to_st.py:18` with signature `floorplan_to_st(E, min_width, min_height, max_width, max_height, ver_list, hor_list, min_ar, max_ar, plot_width, plot_height)`. Every user constraint (min/max width, min/max height, min/max aspect ratio, plot width, plot height) is passed straight into it. It returns `[width, height, hor_dgph, status]`.
  - If `block_checker` said False, `status = False` (825-826). If `status` is False the loop `continue`s to the next REL (827-828); otherwise `self.floorplan_exist = True` (830).
  - On success: transpose and flatten width/height into `self.room_width`/`self.room_height` (831-834); collapse the list-of-lists attributes to the chosen index at 835 (`self.extranodes, self.mergednodes, self.irreg_nodes1 = self.extranodes[i], self.mergednodes[i], self.irreg_nodes1[i]`); recompute coordinates with `dual.get_coordinates(encoded_matrix, self.nodecnt + 4, self.room_width, self.room_height, hor_dgph)` at 838 (`floorplangen/dual.py:235`); round to 3 decimals (839-842); compute `self.area` with `opr.calculate_area` at 843-845 (`operations.py:260`); `break` at 847.
- If no REL satisfies the constraints, the loop ends with `floorplan_exist` still False. The GUI handles this by re-prompting in a `while` loop at handlers.py:926-932.

### `update_gclass_with_edges` (316-337)

Rebuilds an edge list from the current (post-augmentation) matrix and colours it.

- Scans the upper triangle of `self.matrix` (320-323) collecting `(i, j)` into a set.
- Builds `edge_set = [[start, end, 'black'] for start, end in edges]` at 326.
- Recolours to `'red'` any edge present in `self.extraedges` in either orientation (328-332).
- **Mutates** `gclass.value[2] = edge_set` at 335 when `gclass is not None` (334), prints it at 336, and returns `edge_set` at 337.

So it mutates exactly two things: `gclass.value[2]` (the GUI's edge model) and nothing on `self`. It reads `self.matrix` and `self.extraedges`.

Its dependency is `handle_door_connectivity`: handlers.py:1727 and handlers.py:1738 feed its return value into `ui.set_edges(...)` right after `door_connectivity` returned, so the UI redraws the augmented graph with the newly added edges in red. `self.extraedges` is populated **only** by `door_connectivity` at inputgraph.py:516 (diffing `original_one_connected` captured at 360 against the final matrix at 513-516). If `update_gclass_with_edges` were called after `irreg_single_dual` instead, `extraedges` would still be `[]` from line 135 and every edge would come back black.

### `polyonalinput` (849-850)

Two lines. It delegates everything to `cano.runWithArguments(self.nodecnt, v1, v2, vn, priority_order, self, edge_set, debug_cano)` at 850, where `cano` is `gclass.canonicalObject`. The matching callee is `runWithArguments` at `GPLAN/source/polygonal/canonical.py:95`, signature `runWithArguments(self, noOfNodes, v1, v2, vn, priority_order, graph, edge_set, debugCano)`. It passes the `InputGraph` itself as the `graph` argument, so the canonical-order code writes results back onto this object.

**Reachability: it is not reachable from `api.py`.** The only caller is `handlers.handle_poly` at handlers.py:1502, and `handle_poly` (handlers.py:1499) is called only from main.py:56 under `gclass.command == "poly"`, which is the Tk GUI. `api.py` imports the handlers namespace at api.py:13 but never calls `handle_poly` (its dispatch calls at api.py:1262-1408 cover `handle_letter_shape`, `handle_staircase_shaped`, `handle_single_oc`, `handle_single`, `handle_door_connectivity`, `handle_multiple_l`, `handle_multiple_oc`, `handle_multiple` only). Plainly: `polyonalinput` is dead code on the server path, alive only in the desktop GUI.

## Invariants And Preconditions

1. `len(node_coordinates) == nodecnt`, otherwise the crossing check at inputgraph.py:159-161 indexes past the end. `self.coordinates` must stay index-aligned with matrix rows because `trng.triangulate` (228) uses it as the planar embedding.
2. Edge tuples passed to `__init__` need at least two elements; extras are ignored (inputgraph.py:119-121). The `[start, end, 'black']` triples that `update_gclass_with_edges` returns (326) round-trip safely.
3. The graph must be connected before `irreg_single_dual`. Nothing inside the method enforces it: `handle_single` (handlers.py:752-753), `handle_multiple` (handlers.py:1042-1043), `handle_door_connectivity` (handlers.py:1687-1688) and main.py:34-35 do the check and call `connect_graph.one_connected` to repair.
4. `oneconnected_dual` requires a **non**-biconnected graph (inputgraph.py:1209-1210 raises `BCNError` otherwise) and requires each cut vertex in at most 2 components and each component holding at most 2 cut vertices (1236-1241).
5. `single_floorplan` requires `rel_matrix_list` non-empty and `room_x/room_y/room_width/room_height/extranodes/mergednodes/irreg_nodes1` to be **lists indexed by floorplan** (779-814, 835). It cannot follow `irreg_single_dual`, which leaves flat arrays (313) and an empty `rel_matrix_list` (137, never appended in that method). Callers satisfy it by running `irreg_multiple_dual` first (handlers.py:923, 930, 1165) or by manually wrapping each attribute in a one-element list (handlers.py:980-1000 in `handle_letter_shape`).
6. `exp.expand` must shrink `cntrs`, otherwise the `while len(cntrs) != 0` at inputgraph.py:311-312 never terminates. There is no iteration guard.
7. `news.add_news` at 299 assumes exactly four boundary paths in `bdys`; the shortcut loop at 283 exists solely to force the CIP count down to at most 4 so that assumption holds.
8. In `oneconnected_dual("multiple")` (1340-1362), `fpcnt` must equal `len(rel_matrix_list)` and every parallel list (`room_x`, `mergednodes`, `extranodes`, ...) must end up the same length. `area` is reset to `[]` at 1346 and never refilled in that branch.

## Failure Modes

- **`BCNError`** (defined inputgraph.py:55, docstring 56-59: "Raised when one-connected code gets biconnected graph as input"). Raised at exactly one place, inputgraph.py:1210. Caught in handlers.py at 362, 617, 1088, 1163, 1212, 1337, 1369, 1471, 1760, 1837. The handling is always "use the irregular path instead", either by calling `irreg_single_dual` (handlers.py:1089, 1761) or by having already computed the irregular result. Comment at handlers.py:1827-1828 spells this out: after the door-connectivity path the graph is biconnected, so `oneconnected_dual` would always raise `BCNError`.
- **`OCError`** (defined inputgraph.py:47, docstring 48-50: "Raised when one-connected code can not generate rectangular floorplan"). Raised at three places, all inside `oneconnected_dual`: 1238 (a cut vertex in more than 2 components), 1241 (a component with more than 2 cut vertices), 1323 (some component produced zero corner-compatible floorplans). Caught in handlers.py at 359, 613, 1084, 1159, 1208, 1333, 1366, 1467, 1757, 1834. Handling is the same fallback plus, on the single path, a `show_warning("Can not generate rectangular floorplan.")` (handlers.py:1085, 1758).
- No other exception type is defined or raised in this file's in-scope region. Failures elsewhere surface as `IndexError` / `ValueError` from the callee modules, unguarded.
- **Silent failure of `single_floorplan`**: when no REL satisfies the constraints, the method simply returns with `floorplan_exist == False` (138, never flipped at 830). Callers must check; handlers.py:926 loops on it, handlers.py:1004 does not.
- **Silent no-op in `oneconnected_dual`**: a `string` other than `"single"`/`"multiple"` falls through 1337-1340 leaving no geometry.
- **Recursion depth**: `is_connected`'s DFS (182-186) is recursive, so a path-shaped graph deeper than Python's recursion limit raises `RecursionError` rather than answering.

## Coupling (what breaks if you change this)

- **`__init__` attribute names are a public contract.** `api.py` reads `plan.name_coords` (api.py:866, 1430) and writes `graph.cardinal_constraints` (api.py:1305, 1334, 1386); handlers reads `graph.graph_list_by_bdy` (handlers.py:1859, 2092, 2284, 2529), `graph.fpcnt` (handlers.py:1052), `graph.floorplan_exist` (handlers.py:926), `graph.matrix` (handlers.py:1724), `graph.edgecnt` (handlers.py:1726), `graph.coordinates` (handlers.py:1728). Renaming any of them breaks callers silently because most access is by attribute, not through a method.
- **The geometry shape flip at line 835** (`self.extranodes = self.extranodes[i]` etc.) permanently destroys the list-of-lists form on the object. Calling `single_floorplan` twice without re-running `irreg_multiple_dual` in between would index into an already-collapsed list. The GUI retry loop only works because handlers.py:930 re-runs `irreg_multiple_dual` before the second `single_floorplan` at 931.
- **`irreg_single_dual` cannot feed `single_floorplan`.** Anyone "optimising" the dimensioned path by swapping `irreg_multiple_dual` (handlers.py:923) for `irreg_single_dual` will hit an empty `rel_matrix_list` and a zero-iteration loop at inputgraph.py:811, producing `floorplan_exist == False` forever.
- **`oneconnected_dual` depends on `irreg_multiple_dual`** (inputgraph.py:1263) and on the exact NEWS labelling convention (`3` and `2` sentinel values in the REL, inputgraph.py:1269-1276). Changing how `news.add_news` numbers the four exterior vertices, or how `rdg`/`dual` encode labels, silently breaks corner detection and every one-connected input starts raising `OCError` at 1323.
- **`update_gclass_with_edges` depends on `door_connectivity` having filled `extraedges`** (inputgraph.py:516). It also mutates `gclass.value[2]` in place (335), so the GUI's edge model and `ui.set_edges` (handlers.py:1727, 1738) both see the change.
- **The `st.handle_STs(..., 1)` literal at 256** is what distinguishes the single path from the multiple path (`20` at 929). Changing it changes how many alternative separating-triangle resolutions are explored.
- **`filter_boundaries_by_cardinal` (inputgraph.py:1365, out of scope) is not wired into `irreg_single_dual`.** Cardinal constraints set on the object at inputgraph.py:156 affect only the multiple-dual path (the `floorplan_per_bdy_limit` bump at 862-866). A single-dual run ignores them entirely.

## Dead Or Duplicated Code

- **`polyonalinput` (849-850) is dead on the API/server path.** Only caller is handlers.py:1502 inside `handle_poly`, whose only caller is main.py:56 (Tk GUI). `api.py` never dispatches to `handle_poly`.
- **`self.extraedges` (135) is dead for every path in this dossier.** Only writer is `door_connectivity` (inputgraph.py:516); a repo-wide grep for `extraedges` over `*.py` returns only inputgraph.py:135, 324, 331, 512 (comment), 516.
- **`self.nodecnt_list` (132) is effectively dead and misnamed.** The docstring at 103 promises a list per REL, but nothing appends. `irreg_multiple_dual` assigns a scalar into it (inputgraph.py:1009, 1094) and `Lshaped.py:171` does the same. It is then read as a scalar at inputgraph.py:1119 and Lshaped.py:190.
- **`timing_decorator` is defined twice**, identically, at module level (inputgraph.py:65-73) and inside the class body (inputgraph.py:168-176). The class-level copy shadows the module one for all method decorations (178, 339, 778, 848, 851, 1125, 1199); the module-level copy serves the module functions (1364, 1452). Pure duplication.
- **`irreg_single_dual` and `door_connectivity`/`irreg_multiple_dual` duplicate the same eight-stage pipeline** with divergent details. Compare inputgraph.py:219-315 against 365-520 and 885-1120. Lines 543-594 and 696-703 are commented-out copies of the same stages, left in place.
- **`self.circular_traversal` (145) is never written by this module**; handlers writes it (handlers.py:1975, 2401) using module functions `get_circular_traversal` (inputgraph.py:1572) and `get_final_traversal` (1580).
- **`is_connected` duplicates functionality already in networkx** (`nx.is_connected`, used at api.py:960 and multiple_ptpg.py:158) with a hand-rolled recursive DFS.
- `bdy.py:44,72` and `source/trial/bdy.py:44,72` carry a verbatim copy of the `nodecnt_list` docstring and initialiser, so `InputGraph`'s attribute block has been copy-pasted into at least two other classes.

## Open Questions

1. `single_floorplan` pads the dimension arrays using `len(self.mergednodes[0])` and `len(self.extranodes[0])` (inputgraph.py:797, 804) but then applies those same padded arrays to **every** REL in the loop at 811. If floorplan `i > 0` has a different number of merged or extra nodes, the arrays passed to `fpts.floorplan_to_st` at 821-823 are the wrong length. Is this a latent bug, or is the merged/extra count guaranteed constant across the RELs `irreg_multiple_dual` emits? Not resolvable from the in-scope code.
2. The `len(shortcuts) > 4` branch (inputgraph.py:282-296) recomputes `triangular_cycles` inside the loop (293) but recomputes `bdy_ordered` at 294 from `self.bdy_nodes` / `self.bdy_edges`, which were last written at 270 **before** any shortcut was removed. Shortcut removal adds a vertex and three edges (289-291), so the boundary should have changed. Is the stale boundary intentional, or a missed `opr.get_bdy` refresh?
3. `oneconnected_dual` reuses the loop variable `i` for both the outer per-component loop (1250) and the inner per-index loop (1303). After the inner loop finishes, the outer `i` is clobbered, and `ems.append(em)` at 1318 executes with the mutated `i`. `ems.append` does not use `i`, so it may be harmless, but `dicts[i]` at 1284 in the next iteration is reached only after `i` is reassigned by the `for i in range(0, len(components))` header, so the damage is contained. Worth confirming no other read of the outer `i` exists between 1303 and 1318.
4. `oneconnected_dual("multiple")` resets `self.area = []` at 1346 and never refills it, unlike the `mergednodes`/`extranodes` lists that get an empty entry per floorplan at 1359-1362. Do downstream consumers tolerate an empty `area`?
5. The knowledge graph node for `irreg_single_dual` (`graphify explain "irreg_single_dual"`) records only one outgoing edge, `calls store_dummy_node_adjacencies` at L202/L259, and misses the other 26 call sites listed above. The graph is under-extracted for cross-module calls; the code table in this dossier is authoritative.
