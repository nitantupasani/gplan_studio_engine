# septri_non_adj.py and shortcutresolver.py

Unit under analysis:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\irregular\septri_non_adj.py` (315 lines, read in full)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\irregular\shortcutresolver.py` (65 lines, read in full)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\irregular\septri.py` (compared by function name and by diff of extracted bodies only; a sibling task owns its internals)

## Purpose

`septri_non_adj.py` is a copy of the separating-triangle ("ST") edge-selection subsystem of `septri.py`, forked so that the edge the algorithm *adds* while eliminating an ST can be vetoed against a user-supplied non-adjacency list. It contains seven functions; all seven have a counterpart in `septri.py` and none is unique. It has exactly one importer, `GPLAN/source/inputgraph.py:42`, and that import is never dereferenced anywhere in the repository. **The module is dead: no function in it is reachable from `handlers.py` or `api.py`.**

`shortcutresolver.py` is live and small. It finds "shortcuts" on the outer boundary (`get_shortcut`, shortcutresolver.py:14) and eliminates one by inserting a new degree-4 vertex (`remove_shortcut`, shortcutresolver.py:34). Shortcuts are the input to corner-implying-path (CIP) detection, which is what fixes where the four corners of the rectangular dual can go.

## Where It Sits In The Pipeline

Order inside `InputGraph.irreg_single_dual` (inputgraph.py:202): biconnectivity augmentation, triangulation, separating-triangle elimination (inputgraph.py:256), **boundary identification / shortcut resolution (inputgraph.py:268-296)**, 4-completion (inputgraph.py:299), contraction/expansion, dual construction.

`septri_non_adj.handle_STs_with_edge_selection` would have slotted into the ST-elimination step of the door-connectivity pipeline. It does not: `InputGraph.door_connectivity` (inputgraph.py:340) calls the *septri.py* non-adjacency variant instead.

```
inputgraph.py:436-440
        if(is_non_adj):
            ptpg_matrices, extra_nodes,final_positions= st.handle_non_trivial_non_adj_ST_Door_connectivity(one_connected, self.matrix, positions, non_adj_list)
        else:
#             ptpg_matrices, extra_nodes,final_positions = st.handle_STs_with_edge_selection(one_connected, self.matrix, positions)
            ptpg_matrices, extra_nodes,final_positions = st.handle_non_trivial_ST_Door_connectivity(one_connected, self.matrix, positions)
```

`st` is `septri` (inputgraph.py:41). `st_non_adj` is `septri_non_adj` (inputgraph.py:42) and appears nowhere else.

### Question 1: function-by-function comparison

Every function in `septri_non_adj.py`, with its `septri.py` counterpart. Diffs were produced with `diff` on `sed`-extracted line ranges.

| septri_non_adj.py | septri.py counterpart | Verdict |
| --- | --- | --- |
| `sign` (L6) | `sign` (L26) | **EXACT COPY** (diff clean, including docstring) |
| `point_in_triangle` (L17) | `point_in_triangle2` (L1450) | **EXACT COPY, RENAMED**. Only differing line is the `def`. It is *not* a copy of septri's own `point_in_triangle` (L37). |
| `get_edges` (L41) | `get_edges` (L55) | **MODIFIED COPY**, one token |
| `calc_all_triangles` (L52) | `calc_all_triangles` (L1264) | **EXACT COPY** (diff clean) |
| `get_sep_triangles_and_edges` (L58) | `get_sep_triangles_and_edges` (L1218) | **MODIFIED COPY**, one line (callee rename) |
| `remove_st_edge_selection` (L103) | `remove_st_edge_selection` (L1270) | **MODIFIED COPY**, substantial |
| `handle_STs_with_edge_selection` (L253) | `handle_STs_with_edge_selection` (L1378) | **MODIFIED COPY**, substantial |

No UNIQUE functions.

**`point_in_triangle` (non_adj L17) vs `point_in_triangle` (septri L37).** These share a name but are different predicates. septri's L37 version takes 8 args and returns a pure geometric test with an epsilon:

```
septri.py:50-53
    has_neg = (d1 < 1e-7) or (d2 < 1e-7) or (d3 < 1e-7)
    has_pos = (d1 > -1e-7) or (d2 > -1e-7) or (d3 > -1e-7)

    return not (has_neg and has_pos)
```

The non_adj version takes 11 args and additionally requires the interior node to be adjacent to all three triangle vertices:

```
septri_non_adj.py:35-39
    if((adjacency[nodeId][face[0]] == 1) and (adjacency[nodeId][face[1]] == 1) and (adjacency[nodeId][face[2]] == 1) ):
        if interior_pos:
            return True

    return False
```

That body is byte-identical to `septri.point_in_triangle2` (septri.py:1468-1472). So the fork renamed `point_in_triangle2` to `point_in_triangle` and simply did not carry over septri's L37 `point_in_triangle`.

**`get_edges`.** The only difference is the modulus:

```
septri_non_adj.py:50
    return [tuple(sorted([cycle[i], cycle[(i+1)%len(cycle)]])) for i in range(len(cycle))]
septri.py:64
    return [tuple(sorted([cycle[i], cycle[(i+1)%3]])) for i in range(len(cycle))]
```

Behaviourally identical for the 3-cycles both modules actually pass in; the non_adj form is the generalised, less fragile one.

**`get_sep_triangles_and_edges`.** Diff is exactly one line, the callee rename:

```
septri_non_adj.py:72   if (point_in_triangle(origin_pos[face[0]][0], ...
septri.py:1232         if (point_in_triangle2(origin_pos[face[0]][0], ...
```

Since the two callees have identical bodies, this function is semantically an exact copy.

**`remove_st_edge_selection`: the real fork.** Five precise modifications.

1. Signature. septri takes `positions` and threads `final_positions` back out; non_adj drops that and takes `non_adj_list` in the same slot.
   ```
   septri_non_adj.py:103  def remove_st_edge_selection(st_with_internal_node, graph, total_STs, not_user_ST_flag, one_connected, all_triangles, num_nodes, non_adj_list):
   septri.py:1270         def remove_st_edge_selection(st_with_internal_node, graph, total_STs, not_user_ST_flag, one_connected, all_triangles, num_nodes,positions):
   ```
   Return arity differs: `return total_STs, graph` (septri_non_adj.py:249) vs `return total_STs, graph ,final_positions` (septri.py:1375).

2. **The non_adj_list veto.** This is the entire point of the fork and it exists nowhere in septri's `remove_st_edge_selection`:
   ```
   septri_non_adj.py:149-152
                               new_edge = (nbr, i)

                               if new_edge in non_adj_list or (new_edge[1], new_edge[0]) in non_adj_list:
                                   continue  # Skip if the new edge is in the non-adjacency list
   ```
   Both orientations are tested, and both are tuples, so the test matches a `non_adj_list` of tuples (which is the documented contract, `GPLAN/pythongui/nonadjgui.py:7`, "A list of tuples").

3. **A third fallback pass that ignores the veto.** septri has two phases (exterior-edge removal, then edge-swap). non_adj adds a third, entered only when the vetoed pass found nothing:
   ```
   septri_non_adj.py:200-202
                   # If no valid edge was found, try ignoring non-adjacency list for type 3 edges
                   if not edge_found:
                       for edge in edges:
   ```
   Its printouts are tagged `edge-added3` / `edge-removed3` (septri_non_adj.py:209, 211) versus septri's `edge-added2` / `edge-removed2`. So the fork's policy is "prefer a non-adjacency-respecting swap, but violate the constraint rather than leave an ST standing".

4. **A shadowing bug fixed.** septri reuses the outer loop variable `i` (the node interior to the ST) as the inner bookkeeping variable:
   ```
   septri.py:1297-1300
                           for i in  st_with_internal_node.keys():
                               for trngl in st_with_internal_node[i]:
                                   ...
                                   triangle_set = {..., (trngl[2], i),(i, trngl[0]),(i, trngl[1]) }
   ```
   after which `i` holds the last dictionary key, corrupting every later use of `i` in the same outer iteration (`nbr != i` at septri.py:1320, `graph_copy.add_edge(nbr, i)` at septri.py:1321). The fork renames it to `j` at all three sites:
   ```
   septri_non_adj.py:126-129
                       for j in st_with_internal_node.keys():
                           for trngl in st_with_internal_node[j]:
                               ...
                               triangle_set = {..., (trngl[2], j), (j, trngl[0]), (j, trngl[1])}
   ```
   This fix was never merged back into `septri.py`.

5. Control flow and a micro-optimisation. septri deep-copies the graph before testing the guard (septri.py:1319-1320); non_adj tests the guard against `graph` first and only then copies (septri_non_adj.py:148, 154). septri breaks out of the whole triangle loop after one successful swap (`flag1`, septri.py:1368-1373); non_adj only breaks the edge loop (`edge_found`, septri_non_adj.py:194-198) and continues with the next triangle.

**`handle_STs_with_edge_selection`.** Four differences.

1. Extra parameter: `..., positions, non_adj_list)` (septri_non_adj.py:253) vs `..., positions)` (septri.py:1378).
2. Coordinate source. septri trusts the caller's coordinates, the fork recomputes a planar layout and throws them away:
   ```
   septri_non_adj.py:276-277        # origin_pos = positions
                                    origin_pos = nx.planar_layout(graph)
   septri.py:1401-1402              origin_pos = positions
                                    # origin_pos = nx.planar_layout(graph)
   ```
   The two files are exact commented-out mirrors of each other on these two lines.
3. **The two elimination passes run in the opposite order.**
   ```
   septri_non_adj.py:305   ... remove_st_edge_selection(..., False, one_connected, ...)   # then True at :310
   septri.py:1436          ... remove_st_edge_selection(..., True,  one_connected, ...)   # then False at :1441
   ```
   `not_user_ST_flag` protects user-drawn edges (`one_connected[edge[0]][edge[1]] == 1`, septri_non_adj.py:111). The fork therefore permits destroying user edges on the *first* pass; septri protects them first and only relaxes if STs remain.
4. Return arity: `return adjacencies, []` (septri_non_adj.py:314) vs `return adjacencies, [],final_position` (septri.py:1447). The fork's 2-tuple is incompatible with the 3-tuple unpacking every live call site in `inputgraph.py` uses (inputgraph.py:437, 440).

### Question 2: reachability

Importers of `septri_non_adj` (whole tree, one hit):

- `GPLAN/source/inputgraph.py:42` `from GPLAN.source.irregular import septri_non_adj as st_non_adj`

`grep -rn "st_non_adj\." .` over the whole `GPLAN` tree returns **zero** hits. The alias is bound and never used.

Importers of `septri`:

| Importer | Reachable from handlers.py / api.py? |
| --- | --- |
| `GPLAN/source/inputgraph.py:41` (`as st`) | **Yes.** `api.py:13` `from GPLAN.handlers import *`; `handlers.py:29` `import GPLAN.source.inputgraph as inputgraph`; `api.py:8` `from GPLAN.source.inputgraph import InputGraph`. |
| `GPLAN/bdy.py:12` | **No.** `bdy` is imported only by `GPLAN/circulation.py:8`, used only at `circulation.py:114` inside `find_exterior_edges`, called only from `circulation.py:92` (`multiple_circulation`), whose only caller is the test function `circulation.py:1266` `test_multiple_circ`. `circulation.py:114` also passes 4 positional args to `bdy.Boundary.__init__`, which accepts 3 (`bdy.py:55`), so the call would raise `TypeError` if ever reached. |
| `GPLAN/source/trial/bdy.py:12` | **No importer at all.** |
| `GPLAN/source/lettershape/lshape/Lshaped.py:21` | Yes in principle (`handlers.py:10` imports Lshaped), but only `st.handle_STs` is used (Lshaped.py:27, 116). |

Chains for the three named pipelines:

**irreg_single_dual.** `api.py:1299` `handle_single(ui, graph)` -> `handlers.py:751` `def handle_single` -> `handlers.py:760` `graph.irreg_single_dual()` -> `inputgraph.py:202` -> `inputgraph.py:256` `st.handle_STs(...)` = `septri.handle_STs` (septri.py:273) and `inputgraph.py:272` `sr.get_shortcut(...)` = `shortcutresolver.get_shortcut` (shortcutresolver.py:14), plus `inputgraph.py:285` `sr.remove_shortcut(...)` (shortcutresolver.py:34).

**irreg_multiple_dual.** `api.py:1327` `handle_multiple(ui, graph)` -> `handlers.py:1041` `def handle_multiple` -> `handlers.py:1050` `graph.irreg_multiple_dual()` -> `inputgraph.py:852` -> `inputgraph.py:929` `st.handle_STs(self.matrix, positions, 20)`; boundary work is delegated to `generate_multiple_bdy` (`inputgraph.py:946`, `:1033`) -> `inputgraph.py:1453` -> `inputgraph.py:1472` `sr.get_shortcut(matrix, bdy_nodes, bdy_edges)`. **`remove_shortcut` is never called on this path.**

**door_connectivity.** `api.py:1309` / `api.py:1353` `handle_door_connectivity(ui, graph)` -> `handlers.py:1686` -> `handlers.py:1710` `graph.door_connectivity(show_graph=drawGUI, non_adj_list=non_adj_list)` (or `handlers.py:1732` without the list) -> `inputgraph.py:340` -> `inputgraph.py:437` `st.handle_non_trivial_non_adj_ST_Door_connectivity` (septri.py:700) when a non-adjacency list is present, `inputgraph.py:440` `st.handle_non_trivial_ST_Door_connectivity` (septri.py:359) otherwise, plus `st.handle_STs_Door_connectivity` (septri.py:1146) at `inputgraph.py:492` and `:502`. **The whole shortcut/CIP/4-completion block on this path is commented out, `inputgraph.py:547-576`.** `door_connectivity` returns at `inputgraph.py:520`, before that block.

Fourth entry, for completeness: `ptpg_floorplanner.get_boundaries` (`ptpg_floorplanner.py:181`) calls `sr.get_shortcut` at `ptpg_floorplanner.py:232`, reached via `api.py:1791` -> `multi_ptpg_pipeline.py:33` `from GPLAN.source import ptpg_floorplanner as pfp`.

**Verdict per module.** `septri.py`: live, used by all three pipelines. `shortcutresolver.py`: live; `get_shortcut` used by irreg_single_dual, irreg_multiple_dual and the multi-PTPG floorplanner; `remove_shortcut` used only by irreg_single_dual; neither used by door_connectivity. `septri_non_adj.py`: **entirely unreachable. No function in it is called from anywhere in the repository.** Its only effect on the running system is that importing it executes `import matplotlib.pyplot as plt` (septri_non_adj.py:4) in the server process.

The knowledge graph agrees: `graphify explain "septri_non_adj.py"` reports degree 7, all seven edges outbound `contains` edges to its own functions, and zero inbound edges from any caller.

**Verdict per function.** `septri.handle_STs` -> irreg_single_dual and irreg_multiple_dual. `septri.handle_non_trivial_ST_Door_connectivity`, `septri.handle_non_trivial_non_adj_ST_Door_connectivity`, `septri.handle_STs_Door_connectivity` -> door_connectivity only. `septri.handle_STs_with_edge_selection` (septri.py:1378) -> **dead**, its three call sites are all commented out (inputgraph.py:439, 532, 712). `shortcutresolver.get_shortcut` -> irreg_single_dual, irreg_multiple_dual, ptpg_floorplanner. `shortcutresolver.remove_shortcut` -> irreg_single_dual only. All of `septri_non_adj.*` -> dead.

### Question 3: why does septri_non_adj.py exist

Evidence, not speculation:

1. It duplicates `septri.py`'s `handle_STs_with_edge_selection` / `remove_st_edge_selection` pair, which is itself already dead inside `septri.py` (all three call sites commented out: inputgraph.py:439, 532, 712). The fork was taken from a branch that was on its way out.
2. `septri.py` implements non-adjacency differently and independently: it materialises a matrix, `non_adj_matrix[edge[0]][edge[1]] = 1` (septri.py:703-706), inside `handle_non_trivial_non_adj_ST_Door_connectivity` (septri.py:700). `septri_non_adj.py` instead does tuple membership on the raw list (septri_non_adj.py:151). Two different designs for the same requirement, in two files, only one wired up.
3. The fork carries a bug fix (`i` -> `j`, septri_non_adj.py:126/176/229 versus septri.py:1297/1344) that never travelled back to `septri.py`, and its return arity (2-tuple, septri_non_adj.py:314) is incompatible with what every live call site in `inputgraph.py` unpacks (3-tuple, inputgraph.py:437 and :440).
4. The import exists and is aliased (`inputgraph.py:42`) but is never dereferenced, sitting directly beneath the `septri` import that *is* used.

The consistent reading of that evidence: **abandoned mid-migration.** Someone forked the edge-selection ST remover to add non-adjacency support, wired the import into `inputgraph.py`, then the door-connectivity work landed on a different function inside `septri.py` (`handle_non_trivial_non_adj_ST_Door_connectivity`) and the fork was never deleted or reconciled. It is not "an older generation" (its non-adjacency logic and its `i`/`j` fix are strictly newer than septri's equivalent code), and it is not "a parallel path for a different endpoint" (no endpoint calls it). Which of "abandoned" versus "staged for a migration that stalled" is correct cannot be settled from the code alone; see Open Questions.

### Questions 4 and 5: shortcutresolver.py

**What a shortcut is.** An edge of the graph whose two endpoints are both on the outer boundary but which is not itself a boundary edge, that is, a chord of the outer cycle. `get_shortcut` (shortcutresolver.py:14) is a double loop over `bdy_nodes` with exactly that predicate:

```
shortcutresolver.py:28-31
            if(matrix[bdy_nodes[node1]][bdy_nodes[node2]] == 1
                and (bdy_nodes[node1], bdy_nodes[node2]) not in bdy_edges
                and [bdy_nodes[node2], bdy_nodes[node1]] not in shortcuts):
                shortcuts.append([bdy_nodes[node1], bdy_nodes[node2]])
```

The "non-consecutive" framing in the task prompt is correct in effect but is not how the code expresses it: consecutiveness is decided by membership in `bdy_edges`, not by index adjacency in an ordered cycle. `bdy_edges` comes from `operations.get_bdy` (`operations.py:107`), which filters the edges of a DiGraph built from the symmetric matrix (`operations.py:68`), so both orientations `(u,v)` and `(v,u)` are present and the single-orientation membership test at shortcutresolver.py:29 is safe.

**Return shape.** A list of 2-element **lists** `[u, v]`, deduplicated by orientation. Note the deliberate asymmetry at shortcutresolver.py:29-30: the boundary-edge test uses a tuple, the self-dedup test uses a list, matching the container types of each operand.

**What removing a shortcut does.** `remove_shortcut` (shortcutresolver.py:34) does *not* just delete the chord: it splits it with a new vertex. It collects the two nodes that complete triangles on the chord (shortcutresolver.py:45-50), grows the matrix by one row and column (shortcutresolver.py:51-52), zeroes the chord, and joins the new vertex `matrix.shape[0]` to all four surrounding nodes:

```
shortcutresolver.py:54-63
    adjmatrix[shortcut[0]][shortcut[1]] = 0
    adjmatrix[shortcut[1]][shortcut[0]] = 0
    adjmatrix[matrix.shape[0]][shortcut[0]] = 1
    adjmatrix[matrix.shape[0]][shortcut[1]] = 1
    adjmatrix[matrix.shape[0]][nbr_nodes[0]] = 1
    adjmatrix[matrix.shape[0]][nbr_nodes[1]] = 1
```

The result is a new degree-4 vertex where the chord used to be, which is why the caller bookkeeps it as an irregular/merged room: `inputgraph.py:287-291` appends the two endpoints to `irreg_nodes1`/`irreg_nodes2`, appends `self.nodecnt` to `mergednodes`, then `self.nodecnt += 1` and `self.edgecnt += 3`.

**Why it matters for corner assignment.** Shortcuts are the sole input to CIP detection: `cip.find_cip(bdy_ordered, shortcuts)` (`cip.py:11`) walks the boundary between the two endpoints of each shortcut and emits a path as a CIP only if no other shortcut endpoint lies strictly inside it (`cip.py:37-44`). Each CIP must then receive exactly one of the four corners of the rectangular dual: `news.find_bdy` strips the endpoints (`news.py:32`), `news.bdy_path` picks one corner per path (`news.py:46-47`), pads up to four if there are fewer (`news.py:48-52`), and slices the boundary into exactly four sides (`news.py:60-63`). Since there are only four corners, more than four CIPs is unsatisfiable, and the only lever the code has to reduce the CIP count is to remove shortcuts.

**Callers.** With anchors:

- `inputgraph.py:272` `sr.get_shortcut(...)` and `inputgraph.py:285` `sr.remove_shortcut(...)`, both in `irreg_single_dual` (inputgraph.py:202). Live.
- `inputgraph.py:1472` `sr.get_shortcut(...)` in `generate_multiple_bdy` (inputgraph.py:1453), reached from `irreg_multiple_dual` at inputgraph.py:946 and :1033. Live, `get_shortcut` only.
- `inputgraph.py:732`, `:745` in `door_connectivity2` (inputgraph.py:650). Dead: `door_connectivity2` has no callers.
- `inputgraph.py:552`, `:565` inside `door_connectivity`. Commented out.
- `ptpg_floorplanner.py:232` in `get_boundaries` (ptpg_floorplanner.py:181). Live via `multi_ptpg_pipeline.py:33`.
- `bdy.py:154`, `:167` in `Boundary.identify_bdy` (bdy.py:91). Unreachable, see the reachability table.
- `source/trial/bdy.py:152`, `:165`. No importer.
- `staircaseshape/staircaseshape.py:117`, `lettershape/zshape/zshape.py:124`, `lettershape/tshape/tshape.py:124`, `lettershape/ushape/ushape.py:127` (note: `ushape` calls the bare name `get_shortcut`, not `sr.get_shortcut`), `lettershape/lshape/Lshaped.py:247` and `:610`, `polygonal/lshape.py:364`. Shape-specific paths.
- `news.py` does **not** reference shortcuts at all; it consumes CIPs. The prompt's guess that `news.py` calls the resolver is wrong.

**Question 5: the maximum tolerated.** Four. The enforcement is a random-eviction loop in `irreg_single_dual`:

```
inputgraph.py:280-296
            if (len(cips) <= 4):
                bdys = news.bdy_path(news.find_bdy(cips), bdy_ordered)
            else:
                while (len(shortcuts) > 4):
                    index = randint(0, len(shortcuts) - 1)
                    self.matrix = sr.remove_shortcut(
                        shortcuts[index], triangular_cycles, self.matrix)
                    ...
                    shortcuts.pop(index)
                    triangular_cycles = opr.get_trngls(self.matrix)
                bdy_ordered = opr.ordered_bdy(self.bdy_nodes, self.bdy_edges)
                cips = cip.find_cip(bdy_ordered, shortcuts)
                bdys = news.bdy_path(news.find_bdy(cips), bdy_ordered)
```

Exceeding four does not raise: a uniformly random shortcut is picked and split with a new vertex, repeatedly, until at most four remain. Same constant at `bdy.py:165` and `Lshaped.py:614`. There is **no count enforcement at all** in `irreg_multiple_dual`: `generate_multiple_bdy` (inputgraph.py:1453) calls `get_shortcut` at inputgraph.py:1472 and never calls `remove_shortcut`.

## Entry Points (file:line)

- `C:\...\source\irregular\septri_non_adj.py:253` `handle_STs_with_edge_selection(one_connected, adjacency, positions, non_adj_list)` -> the module's only intended public entry. **Zero callers.**
- `C:\...\source\irregular\septri_non_adj.py:103` `remove_st_edge_selection(...)` -> called only from L305 and L310 of the same file.
- `C:\...\source\irregular\shortcutresolver.py:14` `get_shortcut(matrix, bdy_nodes, bdy_edges)`
- `C:\...\source\irregular\shortcutresolver.py:34` `remove_shortcut(shortcut, trngls, matrix)`
- `C:\...\source\inputgraph.py:42` the dangling `septri_non_adj` import
- `C:\...\source\inputgraph.py:272` and `:285` the live shortcut call sites
- `C:\...\source\inputgraph.py:1472` the multiple-dual `get_shortcut` call site
- `C:\...\source\ptpg_floorplanner.py:232` the multi-PTPG `get_shortcut` call site

## Data Structures

- `all_triangles`: list of sorted 3-element lists, from `nx.enumerate_all_cliques` filtered to size 3 and deduplicated with `np.unique(..., axis=0)` (septri_non_adj.py:53-55).
- `st_with_internal_node`: `dict[int, list[tuple[int,int,int]]]`, interior node -> the separating triangles that enclose it (septri_non_adj.py:294-297). `total_STs` is initialised as `len(st_with_internal_node)`, that is, the number of *interior nodes*, not the number of triangles (septri_non_adj.py:301).
- `separating_edge_to_triangles`, `edge_to_faces`: `dict[tuple[int,int], list]` keyed by the sorted edge tuple (septri_non_adj.py:62-63, populated at :83-84 and :96-97). Both are computed and returned but never consumed anywhere in this module.
- `non_adj_list`: list of `(u, v)` tuples per the contract in `nonadjgui.py:7`. Tested by tuple membership in both orientations at septri_non_adj.py:151.
- `shortcuts`: list of `[u, v]` **lists** (shortcutresolver.py:31).
- `bdy_edges`: list of directed `(u, v)` tuples, both orientations present (operations.py:107, built on the DiGraph from operations.py:68).
- The adjacency matrix in `remove_shortcut` is grown by one, `np.zeros([matrix.shape[0]+1, matrix.shape[0]+1], int)` with the old matrix block-copied into the top-left corner (shortcutresolver.py:51-52), so the new vertex always receives index `matrix.shape[0]`.

## Algorithm Walkthrough

**septri_non_adj.handle_STs_with_edge_selection** (septri_non_adj.py:253, dead code, described for completeness).

1. Build an `nx.Graph` from the adjacency matrix, seeding `pos` attributes from `positions` (septri_non_adj.py:268-275).
2. Discard `positions` and recompute `origin_pos = nx.planar_layout(graph)` (septri_non_adj.py:277). This is the fork's key behavioural divergence from septri.py:1401.
3. Enumerate all triangles (septri_non_adj.py:283), then for every (triangle, node) pair test `point_in_triangle`, which requires both geometric containment and full adjacency to the three vertices, and index the hits by interior node (septri_non_adj.py:286-297).
4. First elimination pass with `not_user_ST_flag = False`, so user edges are *not* protected (septri_non_adj.py:305).
5. If STs remain, a second pass with `not_user_ST_flag = True` (septri_non_adj.py:310).
6. Return `[nx.to_numpy_array(graph).astype(int)], []` (septri_non_adj.py:312-314).

**septri_non_adj.remove_st_edge_selection** (septri_non_adj.py:103), per (interior node `i`, enclosing triangle) pair:

1. *Phase 1, exterior edge.* For each of the triangle's three edges, skip it if it is a protected user edge (septri_non_adj.py:111). Compute common neighbours; the edge is "exterior" when it has exactly two common neighbours and those are `i` and the triangle's third vertex (septri_non_adj.py:121). Delete it outright, purge every ST record touching it, decrement `total_STs`, stop (septri_non_adj.py:122-137).
2. *Phase 2, constrained swap.* If no exterior edge existed, for each edge and each common neighbour `nbr` outside the triangle that is not already adjacent to `i`, propose adding `(nbr, i)` and removing the edge. **Veto the proposal if `(nbr, i)` or `(i, nbr)` is in `non_adj_list`** (septri_non_adj.py:151-152). Otherwise apply it to a deep copy, re-enumerate triangles, and accept only if the copy stays planar and the ST count strictly drops (septri_non_adj.py:154-173). On rejection the copy is restored and the search continues.
3. *Phase 3, unconstrained swap.* If phase 2 found nothing, repeat phase 2 verbatim with the veto removed (septri_non_adj.py:201-247). Same planarity and ST-count acceptance test.
4. Return `total_STs, graph` (septri_non_adj.py:249).

**shortcutresolver.get_shortcut** (shortcutresolver.py:14): O(|bdy|^2) scan over ordered pairs of boundary nodes, keeping adjacent pairs that are not boundary edges, deduplicated by reversed-orientation lookup in the accumulator.

**shortcutresolver.remove_shortcut** (shortcutresolver.py:34): scan `trngls` for the (at most two) triangles containing both shortcut endpoints and collect their third vertices into `nbr_nodes` (shortcutresolver.py:46-50). Allocate an (n+1) x (n+1) matrix, copy the old one in, clear the chord, and connect the new vertex to `shortcut[0]`, `shortcut[1]`, `nbr_nodes[0]`, `nbr_nodes[1]` symmetrically (shortcutresolver.py:54-63). Return the enlarged matrix.

## Invariants And Preconditions

- `remove_shortcut` requires `len(nbr_nodes) >= 2` (it indexes `nbr_nodes[0]` and `nbr_nodes[1]` unconditionally, shortcutresolver.py:58-59, 62-63), that is, the shortcut must be an interior chord bounded by two triangles. A chord with only one incident triangle raises `IndexError`.
- `remove_shortcut` requires `matrix` to be a NumPy array (it reads `matrix.shape[0]`, shortcutresolver.py:51). A Python list of lists fails.
- The new vertex index produced by `remove_shortcut` is always `matrix.shape[0]`, and the caller must keep `nodecnt`/`edgecnt` in sync manually (inputgraph.py:290-291 increments by 1 and 3 respectively).
- `get_shortcut` assumes `bdy_edges` contains both orientations. This holds because `operations.get_directed` (operations.py:68) builds a `nx.DiGraph` from a symmetric matrix.
- CIP -> corner assignment assumes at most four CIPs; `news.bdy_path` (news.py:60-63) and `news.find_multiple_boundary` (news.py:88-91) both index `corner_points_index[0..3]` only.
- `septri_non_adj.point_in_triangle` (septri_non_adj.py:35) requires the interior node to be adjacent to all three triangle vertices, so a geometrically-inside but non-adjacent node is *not* counted as making the triangle separating. Same rule as `septri.point_in_triangle2` (septri.py:1468).
- `septri_non_adj.remove_st_edge_selection` assumes `non_adj_list` elements are tuples (septri_non_adj.py:151); a list-of-lists would silently disable the veto.
- `total_STs` counts interior nodes, not triangles (septri_non_adj.py:301), but the acceptance test compares it against `len(separating_triangles)` (septri_non_adj.py:168, 221). The two quantities are only equal when each interior node sits inside exactly one ST.

## Failure Modes

1. **Silent no-op import.** `inputgraph.py:42` binds `st_non_adj` and nothing uses it. The only observable effect is that `import matplotlib.pyplot as plt` (septri_non_adj.py:4) runs at server start, pulling in a GUI-adjacent dependency on a headless host. Every other module in this area avoids that, `septri.py:20-24` imports shapely and networkx only.
2. **Mutation while iterating.** Both files remove from `st_with_internal_node[j]` while iterating it (septri_non_adj.py:177-181, septri.py:1345-1351), which skips the element after each removal. Present in both, so the fork did not fix it.
3. **Loop-variable shadowing in the live file.** `septri.py:1297` and `septri.py:1344` rebind `i` inside the loop that already uses `i` as the interior node, corrupting `nbr != i` (septri.py:1320) and `graph_copy.add_edge(nbr, i)` (septri.py:1321) for the remainder of that outer iteration. `septri_non_adj.py` fixed this and the fix is stranded in the dead file.
4. **Possibly-unbound `separating_triangles`.** At septri_non_adj.py:168 and :221, `separating_triangles` is read in the same condition that tests `not planar`, but it is only assigned inside the `if planar:` branch (septri_non_adj.py:163-166). Python short-circuits `(not planar) or (...)`, so this happens to be safe on the *first* non-planar hit only if a prior iteration had already bound the name; the same pattern is in septri.py:1329-1335.
5. **Dead assignment.** `final_positions = origin_pos` at septri_non_adj.py:187 and :240 is never read; the function returns a 2-tuple (septri_non_adj.py:249). If anyone re-wires the module they will get a `ValueError: not enough values to unpack` at inputgraph.py:437.
6. **Non-adjacency type mismatch in the LIVE file.** `septri.py:846-848` builds `added_edge = sorted([node1,node2])`, a Python **list**, and tests `if added_edge in non_adj_list`. When `non_adj_list` holds tuples, which is the documented contract (`nonadjgui.py:7`) and what the reference harness builds (`Test_api.py:27-31`), a list never equals a tuple and the guard never fires. The same pattern repeats at septri.py:986. The dead fork's version (septri_non_adj.py:151) compares tuple to tuple and does not have this problem.
7. **`len(cips) > 4` with `len(shortcuts) <= 4`.** One shortcut can yield two CIPs (cip.py:45-52), so five or more CIPs can coexist with four or fewer shortcuts. In that case the `while (len(shortcuts) > 4)` loop at inputgraph.py:283 never executes, `find_cip` is re-run on the unchanged list (inputgraph.py:295) and returns the same oversized CIP list, and `news.bdy_path` builds only four sides from `corner_points_index[0..3]` (news.py:60-63) while silently ignoring corners five and beyond. Wrong boundary, no error.
8. **No shortcut bound in the multiple pipeline.** `generate_multiple_bdy` never calls `remove_shortcut`. With more than four CIPs, `news.all_boundaries` falls through every branch to `return paths` (news.py:210) and `news.find_multiple_boundary` again uses only the first four corners (news.py:88-91).
9. **Broken `remove_shortcut` call signatures in the shape modules.** `Lshaped.py:616` calls `sr.remove_shortcut(shortcut[index], graph, graph.rdg_vertices, graph.rdg_vertices2, graph.to_be_merged_vertices)`, five arguments; `polygonal/lshape.py:367` does the same. `shortcutresolver.remove_shortcut` takes three (shortcutresolver.py:34). Reaching either line raises `TypeError`. `polygonal/lshape.py:364` also calls `sr.get_shortcut(graph)` with one argument where three are required, and `polygonal/lshape.py:10` uses a bare `import shortcutresolver as sr` that cannot resolve under the package layout.
10. **Random, non-deterministic shortcut eviction.** `randint(0, len(shortcuts) - 1)` at inputgraph.py:284 makes which chord gets split, and therefore the final room topology, non-reproducible across runs of the same input.

## Coupling (what breaks if you change this)

- **Deleting `septri_non_adj.py`**: nothing breaks, provided `inputgraph.py:42` is deleted in the same change. Deleting the file without the import line raises `ModuleNotFoundError` at `inputgraph` import time, which would take down `handlers.py:29` and therefore all of `api.py`.
- **Deleting only `inputgraph.py:42`**: also safe; it also removes the incidental `matplotlib.pyplot` import from the server startup path.
- **Changing `get_shortcut`'s return element type** from `[u, v]` lists to tuples: breaks `cip.find_cip`, which mutates the shortcut in place at `cip.py:31` (`shortcut[0], shortcut[1] = shortcut[1], shortcut[0]`). Tuples are immutable, so that line would raise `TypeError`.
- **Changing `remove_shortcut`'s node-insertion index**: `inputgraph.py:289` appends `self.nodecnt` to `mergednodes` on the assumption that the new vertex index equals the pre-call node count. Same assumption at `bdy.py:171`.
- **Changing the constant 4**: it is hard-coded in five places (inputgraph.py:280, :283, :743; bdy.py:165; Lshaped.py:603, :614) and is structurally implied by the four-way slicing in `news.bdy_path` (news.py:60-63) and `news.find_multiple_boundary` (news.py:88-91). Changing the loop bound alone will produce silently wrong boundaries rather than an error.
- **Changing `septri.remove_st_edge_selection`'s signature or return arity**: `inputgraph.py:437` and `:440` unpack 3-tuples from the door-connectivity handlers; `inputgraph.py:256`, `:714`, `:929` and `Lshaped.py:27`, `:116` unpack 2-tuples from `handle_STs`. The two conventions coexist.
- **Porting the `i` -> `j` fix into `septri.py`**: touches live door-connectivity behaviour. `handle_STs_with_edge_selection` in `septri.py` is itself dead, so the fix is only worth porting if the same shadowing pattern exists in the live `handle_non_trivial_*` functions, which this dossier did not audit (owned by the sibling task).

## Dead Or Duplicated Code

- **`GPLAN/source/irregular/septri_non_adj.py` (whole file, 315 lines): dead.** Zero call sites. Its only reference is the unused alias at `inputgraph.py:42`. Confirmed independently by `grep -rn "st_non_adj\." GPLAN` returning nothing and by the knowledge graph showing no inbound edges.
- **`septri.handle_STs_with_edge_selection` (septri.py:1378) and `septri.remove_st_edge_selection` (septri.py:1270): dead.** All three call sites are commented out (inputgraph.py:439, :532, :712).
- **`InputGraph.door_connectivity2` (inputgraph.py:650, ~129 lines): dead.** No callers. It contains its own copy of the shortcut block (inputgraph.py:732-755).
- **Third copy of the shortcut block, commented out**, inside the live `door_connectivity` (inputgraph.py:547-576), unreachable in any case because the function returns at inputgraph.py:520.
- **`GPLAN/source/trial/bdy.py`: dead.** No importer anywhere. It is a near-copy of `GPLAN/bdy.py` including the shortcut loop (trial/bdy.py:152-177 vs bdy.py:154-177).
- **`GPLAN/bdy.py`: unreachable from the API.** Its only importer, `circulation.py:8`, uses it at `circulation.py:114` in a call chain whose sole terminus is a test function (`circulation.py:1266`), and that call site passes four arguments to a three-parameter constructor (bdy.py:55).
- **Fourth, independent shortcut implementation**: `ptpg_floorplanner._shortcut_edges` (ptpg_floorplanner.py:336) re-derives the same "boundary-to-boundary edge that skips the cycle" notion with frozensets, in the same file that also imports and calls `sr.get_shortcut` (ptpg_floorplanner.py:232).
- **`point_in_triangle2` (septri.py:1450) vs `point_in_triangle` (septri_non_adj.py:17)**: identical bodies under two names, in two files.
- **`sign` and `calc_all_triangles`**: byte-identical duplicates across the two files.
- **`polygonal/lshape.py`**: `import shortcutresolver as sr` at line 10 is a bare import that cannot resolve under the package layout, and lines 364 and 367 call `get_shortcut` / `remove_shortcut` with argument counts the definitions do not accept. Effectively dead.

## Open Questions

1. Was `septri_non_adj.py` staged for a migration that was then redirected, or simply abandoned? The code cannot distinguish these. Settling it needs the git history of `GPLAN/source/irregular/` (commit dates of `septri_non_adj.py` versus `septri.handle_non_trivial_non_adj_ST_Door_connectivity`); `GPLAN/documentation/work_history_timeline.md` names septri commits (`758a1ac9`, `ba1f79b5`, `827205c1`, `a48d7ec3`) but never mentions `septri_non_adj.py`, and this session did not run `git log`.
2. Is the `list in [tuple, ...]` comparison at `septri.py:848` and `septri.py:986` a live bug in production, or does the deployed frontend send non-adjacency edges in a shape that makes it work? `Test_api.py:27-31` and `nonadjgui.py:7` both produce tuples, which would make the guard a permanent no-op, but the deployed request path (`api.py:1216` `non_adj_edge_list`) was not traced end to end here. This is inside `septri.py`, which the sibling task owns; flagging it rather than adjudicating it.
3. Should the `i` -> `j` shadowing fix (septri_non_adj.py:126/176/229) be salvaged into the live door-connectivity functions before `septri_non_adj.py` is deleted? Whether the same pattern exists in `handle_non_trivial_ST_Door_connectivity` (septri.py:359) and `handle_non_trivial_non_adj_ST_Door_connectivity` (septri.py:700) was not checked; only the dead `remove_st_edge_selection` (septri.py:1270) was.
4. Why does the fork invert the `not_user_ST_flag` pass order (`False` then `True` at septri_non_adj.py:305/310 versus `True` then `False` at septri.py:1436/1441)? One of the two orders protects user-drawn adjacencies and the other does not, and there is no comment in either file explaining which is intended.
5. The knowledge graph and the source agree on everything checked here; `graphify explain "septri_non_adj.py"` reported the same seven functions at the same line numbers and no inbound callers. No disagreement to record.
