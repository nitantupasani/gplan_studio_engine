# Connectivity Augmentation (GPLAN engine)

Unit: `GPLAN/GPLAN/source/graphoperations/{connect_graph,biconnectivity,biconnectivity_non_adj,oneconnectivity}.py`

All paths below are relative to `C:\Users\nitant\Documents\GPLAN_Revamp\`. Every line number cited was read in this session.

---

## Purpose

Take a raw room-adjacency graph (a numpy 0/1 adjacency matrix built in `InputGraph.__init__`, `GPLAN/GPLAN/source/inputgraph.py:118`) and force it to satisfy the structural precondition of the rest of the engine: the graph handed to triangulation must be **2-vertex-connected (biconnected)**, because triangulation, boundary/CIP extraction and the REL machinery all assume a single simple outer cycle.

Two separate repairs exist, run in this order:

1. **1-connectivity repair**: if the graph has more than one connected component, `connect_graph.one_connected` (`GPLAN/GPLAN/source/graphoperations/connect_graph.py:9`) stitches the components into a path.
2. **2-connectivity repair (biconnectivity augmentation)**: if the graph has articulation points, `biconnectivity.biconnect` (`GPLAN/GPLAN/source/graphoperations/biconnectivity.py:86`) or, when the user supplied a non-adjacency list, `biconnectivity_non_adj.biconnect` (`GPLAN/GPLAN/source/graphoperations/biconnectivity_non_adj.py:223`) returns a set/list of extra edges that the caller writes into the matrix.

`oneconnectivity.py` is **not** part of this repair chain despite its name. It is the helper library for the *legacy exact-rectangular* path `InputGraph.oneconnected_dual` (`GPLAN/GPLAN/source/inputgraph.py:1200`), which deliberately does **not** repair a 1-connected graph: it splits it into blocks, lays each block out separately, and merges the encoded matrices. See "Algorithm Walkthrough / oneconnectivity.py".

---

## Where It Sits In The Pipeline

```
api.py  ->  handlers.handle_* (handle_door_connectivity / handle_single / handle_multiple)
              |
              +-- graph.is_connected()            inputgraph.py:181
              |     if False: connect_graph.one_connected(graph.matrix)
              |         handlers.py:752-753, 1042-1043, 1687-1688 ; main.py:34-35
              |
              +-- InputGraph.door_connectivity()  inputgraph.py:340
                    |
                    +-- bcn.is_biconnected(self.matrix)          inputgraph.py:367 / 375
                    +-- bcn_non_adj.biconnect(matrix, non_adj)   inputgraph.py:369   (non-adjacency mode)
                    +-- bcn.biconnect(matrix)                    inputgraph.py:376   (normal mode)
                    +-- write edges into matrix, edgecnt += 1    inputgraph.py:377-380
                    +-- trng.triangulate(..., bcn_edges_added)   inputgraph.py:385-392
                    +-- separating-triangle removal              inputgraph.py:436-440
                    +-- self.extraedges <- diff(original, final) inputgraph.py:512-516
```

The same `is_biconnected -> biconnect -> write into matrix -> triangulate` block is copy-pasted into five call sites:

| Caller | is_biconnected | biconnect |
| --- | --- | --- |
| `InputGraph.irreg_single_dual` | inputgraph.py:219 | inputgraph.py:220 |
| `InputGraph.door_connectivity` (non-adj branch) | inputgraph.py:367 | inputgraph.py:369 (`bcn_non_adj`) |
| `InputGraph.door_connectivity` (normal branch) | inputgraph.py:375 | inputgraph.py:376 |
| `InputGraph.door_connectivity2` | inputgraph.py:672 | inputgraph.py:673 |
| `InputGraph.irreg_multiple_dual` | inputgraph.py:886 | inputgraph.py:887 |
| `ptpg_floorplanner.get_boundaries` | ptpg_floorplanner.py:214 | ptpg_floorplanner.py:215 |
| `bdy.py` (and its clone `source/trial/bdy.py`) | bdy.py:101 / trial/bdy.py:101 | bdy.py:102 / trial/bdy.py:102 |

Only `door_connectivity` ever passes a non-adjacency list, so `biconnectivity_non_adj` has exactly one production caller (`inputgraph.py:369`).

---

## Entry Points (file:line)

### `GPLAN/GPLAN/source/graphoperations/biconnectivity.py` (4877 bytes)

| Line | Signature | Role |
| --- | --- | --- |
| :18 | `is_biconnected(matrix)` | Wraps `nx.from_numpy_array` + `nx.is_biconnected`; the gate every caller checks first (`biconnectivity.py:28-29`). |
| :31 | `get_cutvertices(nxgraph)` | `list(nx.articulation_points(nxgraph))` (`biconnectivity.py:39`). |
| :42 | `get_biconnected_components(nxgraph)` | Returns the `nx.biconnected_components` **generator** (not a list) (`biconnectivity.py:50`). |
| :53 | `same_component(components, node1, node2)` | Linear scan over a **precomputed** component list; True if some component holds both nodes (`biconnectivity.py:63-66`). |
| :68 | `sort_list(components, neighbors)` | Reorders an articulation point's neighbours so that same-component neighbours are consecutive, in `components` order (`biconnectivity.py:77-84`). |
| :86 | `biconnect(matrix)` | The augmentation itself; returns a **set** of `(u, v)` edges to add (`biconnectivity.py:115-116`). |

### `GPLAN/GPLAN/source/graphoperations/biconnectivity_non_adj.py` (13079 bytes, ~2.7x)

| Line | Signature | Role |
| --- | --- | --- |
| :8 | `is_biconnected(matrix)` | Byte-identical body to `biconnectivity.py:18`. |
| :21 | `get_cutvertices(nxgraph)` | Byte-identical body to `biconnectivity.py:31`. |
| :32 | `get_biconnected_components(nxgraph)` | Byte-identical body to `biconnectivity.py:42`. |
| :43 | `same_component(nxgraph, node1, node2)` | Same intent as `biconnectivity.py:53` but takes the graph and **recomputes** components on every call (`biconnectivity_non_adj.py:53`). |
| :59 | `sort_list(nxgraph, neighbors)` | Same intent as `biconnectivity.py:68`, recomputes components (`biconnectivity_non_adj.py:69`), dedups via `temp_list` instead of a `seen` set. |
| :79 | `find_valid_edge(block1, block2, non_adj_list)` | First cross-block pair not forbidden. **Never called anywhere in the tree** (dead). |
| :95 | `find_valid_edge_multi(block1, block2, non_adj_list, potential_edges)` | All cross-block pairs not forbidden and not already proposed; used only by `make_biconnected_permutations` (`biconnectivity_non_adj.py:304, 314`). |
| :114 | `find_blocks(nxgraph, ap)` | Copies the graph, removes the articulation point, returns `nx.connected_components` of the remainder as lists (`biconnectivity_non_adj.py:126-131`). |
| :135 | `find_valid_edges(blocks, non_adj)` | Enumerates **every** cross-block vertex pair not in the non-adjacency set (`biconnectivity_non_adj.py:149-156`). |
| :160 | `connect_blocks(blocks, valid_edges, non_adj)` | Union-find / Kruskal spanning tree over blocks; picks the lexicographically smallest legal edge per merge (`biconnectivity_non_adj.py:196-204`). |
| :223 | `biconnect(matrix, non_adj_list)` | The non-adjacency-aware augmentation; returns a **list** of edges. |
| :256 | `make_biconnected_permutations(matrix, non_adj_list)` | Brute-force enumeration of up to 20 minimal, planar biconnecting edge sets. **Never called**: grep for the name across the whole `GPLAN` tree returns only this definition, with no reference anywhere else, not even a commented-out one. |

### `GPLAN/GPLAN/source/graphoperations/oneconnectivity.py` (5690 bytes)

| Line | Signature | Role |
| --- | --- | --- |
| :12 | `get_biconnected_components(nxgraph)` | Same as `biconnectivity.py:42` but forces `list(...)` (`oneconnectivity.py:19`), which is why `inputgraph.py:1218` can index it. |
| :22 | `get_adj_matrix(matrix, component)` | Numpy fancy-index submatrix `matrix[l][:,l]` for one block (`oneconnectivity.py:29-31`). |
| :33 | `get_dict(component)` | Global-vertex-id -> local-index map for a block (`oneconnectivity.py:40-44`). |
| :46 | `recurse(list, i, final, individual)` | Cartesian product of per-block candidate encoded matrices, accumulated into `final` (`oneconnectivity.py:53-60`). |
| :62 | `merge(em_list)` | Rotates each block's encoded matrix so shared cut-vertex corners line up, pads to equal height, concatenates horizontally (`oneconnectivity.py:93-163`). |
| :165 | `convert_to_rel(em, nodecnt)` | Turns a merged encoded matrix back into a REL adjacency matrix with the 4 NEWS vertices wired in (`oneconnectivity.py:183-203`). |

### `GPLAN/GPLAN/source/graphoperations/connect_graph.py` (673 bytes)

| Line | Signature | Role |
| --- | --- | --- |
| :3 | `dfs(v, nodes, visited, graph)` | Plain recursive DFS marking `visited` (`connect_graph.py:4-8`). |
| :9 | `one_connected(graph)` | Mutates the adjacency matrix in place, chaining one representative vertex per connected component into a path (`connect_graph.py:19-21`). |

---

## Data Structures

- **`matrix`**: `np.zeros((n, n), int)` symmetric 0/1 adjacency (`inputgraph.py:118-121`). Every function here takes/returns this, never a `networkx` object across module boundaries (except `get_cutvertices` / `get_biconnected_components`, which take an `nxgraph`).
- **`nxgraph`**: throwaway `nx.from_numpy_array(matrix)` built fresh inside each function (`biconnectivity.py:28, 94`; `biconnectivity_non_adj.py:18, 232, 267`). Node labels are plain ints 0..n-1, so returned edge tuples are directly usable as matrix indices.
- **`components`**: iterable of `set`s of vertices, one per biconnected block. Note the two-way split: `biconnectivity.get_biconnected_components` returns a **generator** (`biconnectivity.py:50`), `oneconnectivity.get_biconnected_components` returns a **list** (`oneconnectivity.py:19`).
- **`blocks`** (non-adj only): list of lists, the connected components of `G - ap` (`biconnectivity_non_adj.py:130-131`). These **exclude** the articulation point itself.
- **`non_adj_list`**: list of `(u, v)` int tuples. Built in `local_engine_bridge.py:66-67` from edges the frontend marked `color == "red"`, threaded through `api.get_floorplans(..., non_adj_edge_list=...)` (`api.py:1216`) -> `ui.set_non_adj_list` (`api.py:1303`) -> `handlers.py:1708` -> `graph.door_connectivity(non_adj_list=...)` (`handlers.py:1710`). `find_valid_edges` does `set(non_adj)` (`biconnectivity_non_adj.py:146`), so elements must be hashable (tuples, not lists).
- **`bcn_edges`**: the return value. `set` from `biconnectivity.biconnect`, `list` from `biconnectivity_non_adj.biconnect`. Callers only iterate it, so the type difference is currently invisible.
- **`self.extraedges`**: `list` of `[i, j]` **lists** on the `InputGraph` (`inputgraph.py:135`). Populated only in `door_connectivity` (`inputgraph.py:516`).

---

## Algorithm Walkthrough

### 1. `connect_graph.one_connected` (0-connected -> 1-connected)

Hand-rolled recursive DFS. `dfs` (`connect_graph.py:3-8`) marks reachability; `one_connected` (`connect_graph.py:9-21`) collects the first unvisited vertex of each component into `parents`, then links `parents[i] <-> parents[i+1]` for all i, writing `True` (which becomes `1` in the int matrix) into both triangles (`connect_graph.py:19-21`). Result: a **path** of component representatives. It returns `None` and mutates the caller's matrix.

Consequence worth stating plainly: a path of representatives creates fresh articulation points, so `one_connected` guarantees the biconnectivity stage will have work to do.

### 2. Cut vertices and biconnected components: **networkx, not a hand-written DFS lowpoint**

There is **no** DFS/lowpoint implementation anywhere in these four files. Both modules delegate:

- `list(nx.articulation_points(nxgraph))` at `biconnectivity.py:39` and `biconnectivity_non_adj.py:29`.
- `nx.biconnected_components(nxgraph)` at `biconnectivity.py:50`, `biconnectivity_non_adj.py:40`, `oneconnectivity.py:19`.
- `nx.is_biconnected(nxgraph)` at `biconnectivity.py:29` and `biconnectivity_non_adj.py:19`.
- `biconnectivity_non_adj.find_blocks` additionally uses `nx.connected_components` on `G - ap` (`biconnectivity_non_adj.py:130`).

The only hand-written DFS in this unit is `connect_graph.dfs` (`connect_graph.py:3`), and it is plain reachability, not lowpoint. (`InputGraph.is_connected` at `inputgraph.py:181-192` has a second, independent hand-written DFS for the same purpose.)

### 3. `biconnectivity.biconnect` (`biconnectivity.py:86-116`) - which edges get added

```
nxgraph              = from_numpy_array(matrix)                 :94
articulation_points  = get_cutvertices(nxgraph)                 :95
components           = list(get_biconnected_components(nxgraph)) :97   # computed ONCE
for each articulation point ap:                                  :101
    neighbors = list(nx.neighbors(nxgraph, ap))                  :102
    neighbors = sort_list(components, neighbors)                 :103   # group by block
    for consecutive pair (n_j, n_j+1):                           :104
        if not same_component(components, n_j, n_j+1):           :105
            added_edges.add((n_j, n_j+1))                        :106
            ...prune step (below)                                :107-114
bicon_edges = added_edges - removed_edges                        :115
```

**The rule, stated exactly**: for each cut vertex `ap`, its neighbours are sorted so that neighbours belonging to the same biconnected block are consecutive (in `nx.biconnected_components` iteration order). Then an edge is added between **each consecutive pair of neighbours that straddle a block boundary**. So the added edge always joins a *neighbour of the cut vertex in block A* to a *neighbour of the cut vertex in block B*, forming a triangle with the cut vertex. If `ap` touches k blocks, this proposes k-1 edges, chaining the blocks in component order. The cut vertex itself is never an endpoint of the edge it triggers.

The prune step at `biconnectivity.py:107-114`: if `(ap, n_j)` (either orientation) is already in `added_edges` from an earlier articulation point's pass, both orientations of `(ap, n_j)` go into `removed_edges`, and the same for `n_j+1`. The final set is the difference (`biconnectivity.py:115`). This can only fire when one articulation point is a neighbour of another. The code carries no comment or proof for why the earlier edge becomes redundant; it is a heuristic.

**Caching note**: `components` is computed once at `biconnectivity.py:97` and reused (comment at `:96`), whereas `same_component`/`sort_list` in the non-adj twin recompute it per call. This is safe here because `nxgraph` is never mutated inside `biconnect` (there is no `add_edge` between `:94` and `:116`), so the cached and recomputed values are identical.

### 4. Where the returned edge list goes in `inputgraph.py`

The variable is named **`bcn_edges`** at every call site: `inputgraph.py:218/220` (`irreg_single_dual`), `inputgraph.py:365/369/376` (`door_connectivity`), `inputgraph.py:671/673` (`door_connectivity2`), `inputgraph.py:885/887` (`irreg_multiple_dual`).

What happens to it:

- Written straight into the matrix and `edgecnt` bumped: `inputgraph.py:221-224`, `377-380`, `674-677`, `888-891`.
- Reduced to a boolean flag `bcn_edges_added = len(bcn_edges) > 0` (`inputgraph.py:225, 381, 678, 892`) and passed as the second positional argument to `trng.triangulate(...)` (`inputgraph.py:228-230, 385-392, 681-683, 899-901`). That flag is the only thing triangulation learns about augmentation.
- Sets `self.nonrect = True` if any edge was added (`inputgraph.py:236-237, 400-401, 691-692, 907-908`).
- In `irreg_single_dual` only, each bcn edge is turned into an extra vertex via `transform.transform_edges`, and that vertex id is appended to `self.extranodes` (`inputgraph.py:240-245`). This is the "treat it specially" mechanism for the irregular path. The equivalent block in `door_connectivity2` is commented out (`inputgraph.py:694-707`).

**Is the added-edge set recorded for later special treatment (e.g. excluded from door placement)?**
Not as a distinct set, and not by identity. `bcn_edges` is a **local** variable in every method; it is never stored on `self`. The only persistent record is `self.extraedges` (`inputgraph.py:135`), and it is built in `door_connectivity` at `inputgraph.py:512-516` by **diffing the pre-augmentation matrix snapshot `original_one_connected` (`inputgraph.py:360`) against the final matrix**. That diff lumps together biconnectivity edges, triangulation edges and separating-triangle-removal edges: there is no way to tell them apart afterwards.

`self.extraedges` is consumed in exactly one place: `InputGraph.update_gclass_with_edges` (`inputgraph.py:316-337`), which colours those edges `'red'` in the edge list returned to the GUI/API (`inputgraph.py:328-332`). That return value reaches the caller via `ui.set_edges(graph.update_gclass_with_edges(gclass))` (`handlers.py:1727, 1738`). Grep for `extraedges` across the whole `GPLAN` tree returns only `inputgraph.py:135, 324, 331, 512, 516` plus documentation. **Nothing excludes these edges from door placement.** The only downstream behaviour is the colour flag.

### 5. `biconnectivity_non_adj.biconnect` (`biconnectivity_non_adj.py:223-249`) - what is different

Different repair rule entirely:

```
articulation_points = get_cutvertices(nxgraph)                :233   # on the ORIGINAL graph
for point in articulation_points:                             :239
    neighbors = sort_list(nxgraph, neighbors)                 :240-241   # computed, only printed
    blocks      = find_blocks(nxgraph, point)                 :244   # components of G - point
    valid_edges = find_valid_edges(blocks, non_adj_list)      :245   # ALL legal cross-block pairs
    bcn_edges   = connect_blocks(blocks, valid_edges, non_adj_list)  :246
    selected_edges.extend(bcn_edges)                          :247
return selected_edges                                         :249
```

Constraint mechanism: `find_valid_edges` (`biconnectivity_non_adj.py:135-158`) enumerates **every** pair (u in block_i, v in block_j, i < j) and keeps it only if neither `(u, v)` nor `(v, u)` is in `set(non_adj)` (`biconnectivity_non_adj.py:146, 155`). So the non-adjacency list is a hard filter on the candidate pool, and unlike `biconnectivity.biconnect` the endpoints need **not** be neighbours of the cut vertex: any vertex of any block qualifies.

Selection rule: `connect_blocks` (`biconnectivity_non_adj.py:160-222`) runs Kruskal with path-compressing union-find over block indices (`find`/`union` at `:184-193`). `valid_edges.sort()` (`:196`) is a plain lexicographic sort of `(u, v)` tuples with no weights, so the chosen edge for each block merge is the **lexicographically smallest legal cross-block pair**, i.e. biased hard toward low-numbered rooms. The result is a spanning tree over the blocks: k-1 edges for k blocks.

**When no legal repair edge exists: no exception is raised.** `connect_blocks:209-221` checks whether all blocks ended up in one union-find class, and if not it walks `non_adj` itself and adds forbidden edges to `selected_edges` until the blocks are connected. The non-adjacency constraint is silently violated with no warning, no return-code, and no record. `biconnectivity_non_adj.py` contains no `raise` statement at all. The commented-out code at `inputgraph.py:370-373` shows an abandoned intent to detect "No Biconnectivity augmentation found" and return `False`; `handlers.py:1712-1716` still has the matching 3-tuple unpacking and `show_warning("No augmentation found")` branch, which the current 2-tuple return from `inputgraph.py:520` can never trigger.

**Is the extra size real algorithm or copied code?** Both, roughly half and half.

Line-for-line duplicates of `biconnectivity.py` (identical bodies, only docstring wording differs):

| Function | biconnectivity.py | biconnectivity_non_adj.py | Verdict |
| --- | --- | --- | --- |
| `is_biconnected` | :18-29 | :8-19 | identical body |
| `get_cutvertices` | :31-40 | :21-30 | identical body |
| `get_biconnected_components` | :42-51 | :32-41 | identical body |
| `same_component` | :53-66 | :43-57 | near-duplicate; signature differs (`components` vs `nxgraph`), non-adj recomputes components at `:53` |
| `sort_list` | :68-84 | :59-77 | near-duplicate; signature differs, non-adj recomputes at `:69` and dedups with `temp_list` instead of a `seen` set |

Genuinely new code in the non-adj file: `find_valid_edge` (:79, dead), `find_valid_edge_multi` (:95), `find_blocks` (:114), `find_valid_edges` (:135), `connect_blocks` (:160), the rewritten `biconnect` (:223), and `make_biconnected_permutations` (:256, dead). `make_biconnected_permutations` alone is 94 lines (:256-349) and is unreachable.

`make_biconnected_permutations` (for the record, since it is dead): union-find over block tuples (:282-291), collects candidate edges with relaxation when a block has none (:312-315), then brute-forces `combinations(potential_edges, r)` for r = 1..len (:317-318), keeps combos that make the graph biconnected (:323), strips redundant edges by removal test (:327-333), keeps only planar results (:338-339), and caps at 20 sets (:342-343). Exponential in the candidate count.

### 6. `oneconnectivity.py` - what it actually handles

It does **not** repair connectivity. It is the block-decomposition helper for `InputGraph.oneconnected_dual` (`inputgraph.py:1200`), the legacy exact-rectangular-dual path, which handles the case biconnectivity augmentation cannot: producing a *true rectangular* dual for a graph that has cut vertices, by laying out each biconnected block separately and gluing the layouts at the cut vertex.

`oneconnected_dual` is the sole caller of every `onc.*` symbol:

- `inputgraph.py:1209-1210`: raises `BCNError` (defined `inputgraph.py:55-60`) immediately if the input **is** biconnected. The method is 1-connected-only, exactly the inverse of `biconnect`'s applicability.
- `inputgraph.py:1217-1218`: cut vertices from `bcn.get_cutvertices`, blocks from `onc.get_biconnected_components`.
- `inputgraph.py:1236-1241`: raises `OCError` (`inputgraph.py:47-52`) if any cut vertex lies in more than 2 blocks, or any block contains more than 2 cut vertices. So only *chains* of blocks are supported.
- `inputgraph.py:1244-1246`: `onc.get_adj_matrix` / `onc.get_dict` per block.
- `inputgraph.py:1257-1263`: recursive `InputGraph` per block, laid out by `irreg_multiple_dual`.
- `inputgraph.py:1287-1299`: keeps only per-block floorplans where every cut vertex of that block occupies exactly 2 of the 4 corners (so the blocks can be butted together).
- `inputgraph.py:1323`: `raise OCError` when no such floorplan exists.
- `inputgraph.py:1328`: `onc.recurse` builds the cross-product of per-block choices; `inputgraph.py:1331`: `onc.merge` glues encoded matrices; `inputgraph.py:1333`: `onc.convert_to_rel` rebuilds a REL.

Handlers call it inside try/except and fall back to the irregular path on either exception: `handlers.py:358-362, 611-619, 1082-1088, 1157-1165, 1206-1214, 1331-1339, 1365-1369, 1465-1473, 1756-1760, 1833-1837`.

### 7. `connect_graph.py` - is it dead?

**No, it is live and reachable from both `handlers.py` and `api.py`.** Imported at `handlers.py:7` (`from GPLAN.source.graphoperations import connect_graph`) and called at:

- `handlers.py:752-753` in `handle_single`
- `handlers.py:1042-1043` in `handle_multiple`
- `handlers.py:1686-1688` in `handle_door_connectivity`
- `main.py:34-35` (which gets the name via `from GPLAN.handlers import *`, `main.py:6`)

`api.py` does `from GPLAN.handlers import *` (`api.py:13`) and dispatches to `handle_door_connectivity` / `handle_single` / `handle_multiple` (`api.py:1297-1353`), so the API path reaches it. Each call is guarded by `if not graph.is_connected():` using the separate DFS at `inputgraph.py:181`.

---

## Invariants And Preconditions

1. **Input to `biconnect` must be a square symmetric numpy int matrix.** `nx.from_numpy_array` is called on it directly (`biconnectivity.py:94`), and returned edge endpoints are used as raw matrix indices by the caller (`inputgraph.py:378-379`).
2. **`biconnect` is only called when `is_biconnected` is False.** Every call site guards it (`inputgraph.py:219, 367, 375, 672, 886`; `ptpg_floorplanner.py:214`). On an already-biconnected graph `articulation_points` would be empty and it would return an empty set anyway, but the contract is the guard.
3. **`biconnect` never mutates its input.** It builds a throwaway `nxgraph` (`biconnectivity.py:94`) and returns edges; the caller does the writing. Same for the non-adj twin (`biconnectivity_non_adj.py:232`).
4. **`connect_graph.one_connected` DOES mutate its input in place** and returns `None` (`connect_graph.py:19-21`). Callers rely on the mutation (`handlers.py:753`).
5. **`connect_graph.one_connected` does not update `edgecnt` or `edgeset`.** After it runs, `graph.edgecnt` under-counts the true edge count of `graph.matrix`. Nothing in `handlers.py:751-753` corrects this.
6. **`oneconnected_dual` requires a non-biconnected input** (`inputgraph.py:1209-1210`) and a block chain with fan-out <= 2 (`inputgraph.py:1236-1241`).
7. **`biconnectivity_non_adj.find_valid_edges` requires hashable `non_adj` elements** because of `set(non_adj)` (`biconnectivity_non_adj.py:146`). The live producer supplies tuples (`local_engine_bridge.py:66-67`).
8. **The order of the two repairs matters**: `one_connected` runs in the handler *before* `door_connectivity` (`handlers.py:1687-1688` then `:1710`), and `biconnect` cannot fix a disconnected graph (`nx.articulation_points` on a disconnected graph reports per-component cut vertices only; a graph with two components and no cut vertices yields zero augmentation edges).

---

## Failure Modes

1. **No post-condition check.** Neither `biconnect` verifies its own output. After `inputgraph.py:377-380` writes the edges, nothing re-runs `is_biconnected`. If the heuristic under-repairs, the failure surfaces much later inside triangulation or boundary extraction as a confusing error.
2. **`biconnectivity.biconnect` prune step can delete a needed edge.** `biconnectivity.py:107-114` removes previously added edges `(ap, n)` on the basis that a new edge exists, with no proof of redundancy and no re-verification.
3. **`biconnectivity_non_adj.biconnect` recomputes nothing between articulation points.** `articulation_points` (`:233`) and every `find_blocks` call (`:244`) run against the unmodified `nxgraph`; `selected_edges` are never added back to it. Edges chosen for cut vertex A that also fix cut vertex B are not noticed, so B gets its own redundant edges. The output is not minimal.
4. **Silent non-adjacency violation.** `connect_blocks:211-221` adds edges taken directly from the non-adjacency list when the legal pool cannot span the blocks. No exception, no flag, no log. The user gets a floorplan that violates a constraint they set.
5. **`KeyError` in that same fallback.** `node_to_block` is built only from block members (`biconnectivity_non_adj.py:177-179`), which exclude the articulation point (`find_blocks` removes it at `:127`). If a `non_adj` pair mentions the current articulation point, `node_to_block[u]` at `:214-215` raises `KeyError`.
6. **`connect_blocks` mutates its `valid_edges` argument** via in-place `.sort()` (`biconnectivity_non_adj.py:196`).
7. **Recursion depth.** `connect_graph.dfs` (`:3-8`) and `InputGraph.is_connected.dfs` (`inputgraph.py:182-186`) are both unbounded-depth Python recursion; a long path graph of a few thousand rooms would hit the recursion limit. Also `connect_graph.dfs` is O(n) per vertex scan, so O(n^2) overall.
8. **Debug prints on the hot path.** `biconnectivity_non_adj.py:237, 242, 273, 297, 313` print on every call. `api.py:1217-1219` installs a null print to suppress them, so they are noise-only in production but slow in the GUI path.
9. **Cost.** `find_valid_edges` (`:149-156`) is O(sum over block pairs of |B_i| * |B_j|), i.e. O(n^2) per articulation point, and `sort_list`/`same_component` in the non-adj module recompute `nx.biconnected_components` on every invocation (`:53, :69`).
10. **Dead error-handling path in the caller.** `handlers.py:1712-1716` handles a 3-tuple `(graph, checkPTPG, possible)` return from `door_connectivity` that the current implementation never produces (it returns a 2-tuple at `inputgraph.py:520`).

---

## Coupling (what breaks if you change this)

- **Changing the return type of `biconnectivity.biconnect`** (currently a `set`) breaks seven call sites that iterate it and index `edge[0]`/`edge[1]`: `inputgraph.py:221, 377, 674, 888`; `ptpg_floorplanner.py:215`; `bdy.py:102`; `source/trial/bdy.py:102`.
- **Changing which edges are added** changes `bcn_edges_added` and therefore the branch taken inside `trng.triangulate` (`inputgraph.py:228-230, 385-392, 681-683, 899-901`), and changes `self.nonrect` (`inputgraph.py:236-237` etc.), and in `irreg_single_dual` changes the number and ids of `self.extranodes` created by `transform.transform_edges` (`inputgraph.py:240-245`), which shifts every downstream node index.
- **Changing `self.extraedges` population** (`inputgraph.py:512-516`) changes which edges the frontend renders red (`inputgraph.py:328-332` -> `handlers.py:1727/1738`), and since `local_engine_bridge.py:66-67` reads red edges back as the non-adjacency list, a round-trip through the UI would re-interpret augmentation edges as forbidden adjacencies. That coupling is worth checking before touching either end.
- **Adding a `raise` to `biconnectivity_non_adj`** requires a new except-branch in `door_connectivity` (`inputgraph.py:366-373`) and in `handlers.handle_door_connectivity` (`handlers.py:1710-1721`); the currently-dead 3-tuple branch at `handlers.py:1712-1716` is the intended landing spot.
- **`oneconnectivity.get_biconnected_components` must keep returning a list**, because `inputgraph.py:1227, 1231-1234, 1244-1246, 1250` index and re-iterate it. Making it a generator like its `biconnectivity.py` twin silently breaks `oneconnected_dual`.
- **Deleting `connect_graph.py`** breaks `handlers.py:7` at import time, which breaks `api.py:13` (`from GPLAN.handlers import *`) and thus the whole API.

---

## Dead Or Duplicated Code

Stated plainly:

- **`biconnectivity_non_adj.find_valid_edge` (`:79-93`) is dead.** Grep over the whole `GPLAN` tree finds only its definition.
- **`biconnectivity_non_adj.make_biconnected_permutations` (`:256-349`) is dead.** 94 lines, zero references. Grep over the whole `GPLAN` tree finds only the definition at `biconnectivity_non_adj.py:256`; nothing calls it and no commented-out line names it either. The commented line at `inputgraph.py:368` reads `# bcn_edges = bcn_new.biconnect(self.matrix, non_adj_list)`, i.e. a call to `biconnect` on a module alias `bcn_new` that is never imported (`inputgraph.py:24-25` bind only `bcn` and `bcn_non_adj`); it does not reference `make_biconnected_permutations`.
- **`biconnectivity_non_adj.py:6` `from networkx import second_order_centrality`** is an unused import. So is **`biconnectivity.py:14` `from os import remove`**.
- **`sort_list` is a dead computation inside `biconnectivity_non_adj.biconnect`.** Lines `:240-242` compute and print the sorted neighbour list, then `:244-246` build the repair from `find_blocks` and ignore `neighbors` entirely. Deleting lines 240-242 would not change the result.
- **Three functions are line-for-line duplicates** between the two biconnectivity modules: `is_biconnected` (`biconnectivity.py:18` vs `biconnectivity_non_adj.py:8`), `get_cutvertices` (`:31` vs `:21`), `get_biconnected_components` (`:42` vs `:32`). Two more, `same_component` and `sort_list`, are near-duplicates that diverged only by the component-caching optimisation applied to `biconnectivity.py:97` (comment at `:96`).
- **`get_biconnected_components` exists a third time** in `oneconnectivity.py:12`, differing only by the `list(...)` wrapper.
- **`GPLAN/GPLAN/source/trial/bdy.py` is a clone of `GPLAN/GPLAN/bdy.py`**: both call `bcn.is_biconnected` at their line 101 and `bcn.biconnect` at their line 102, with the same surrounding code (`bdy.py:101-102`, `trial/bdy.py:101-102`). Neither is imported by `handlers.py` or `api.py`.
- **The `door_connectivity2` edge-to-vertex block (`inputgraph.py:694-707`) is commented out**, so unlike `irreg_single_dual` it leaves bcn edges as plain adjacencies.
- **`inputgraph.py:529-539`** is a commented-out duplicate of the separating-triangle block, sitting after an unconditional `return` at `:520`, hence unreachable even if uncommented.
- **`connect_graph.py` is NOT dead** (see section 7 above): `handlers.py:7, 752-753, 1042-1043, 1687-1688` and `main.py:34-35`.

---

## Open Questions

1. **Why does the prune step at `biconnectivity.py:107-114` exist?** It removes edges `(ap, n)` added on an earlier articulation point's iteration. There is no comment, no test, and no post-condition check. It is not obvious that the removed edge is always redundant; a graph where two cut vertices are adjacent and each needs its own repair could plausibly be under-repaired. Needs a targeted test.
2. **Is `biconnectivity.biconnect` correct when a single cut vertex separates 3+ blocks whose neighbour sets interleave?** `sort_list` orders neighbours by `nx.biconnected_components` iteration order, which is DFS-dependent and not documented as stable. Chaining consecutive pairs assumes a linear order over blocks.
3. **Should the non-adjacency fallback at `connect_blocks:211-221` be an error instead?** The commented-out code at `inputgraph.py:370-373` plus the live-but-unreachable handler branch at `handlers.py:1712-1716` suggest someone intended exactly that and the wiring was never finished. Which behaviour is wanted: fail loudly, or silently violate?
4. **Was `make_biconnected_permutations` meant to replace `biconnect` in the non-adj path?** It produces up to 20 minimal *planar* biconnecting edge sets, which is strictly better input for triangulation than one arbitrary spanning tree. No call site ever existed: the commented block at `inputgraph.py:368-373` calls `bcn_new.biconnect` (an alias never imported) and the surrounding comments talk about a `bcn_edges_set` from which "we have to choose 1", which is a permutation-style API but is not this function by name. So the intent is only circumstantial. Deleting it or finishing a migration to it are both defensible; leaving it is not.
5. **Should augmentation edges be excluded from door placement?** They currently are not. `self.extraedges` (`inputgraph.py:516`) lumps bcn edges together with triangulation and ST edges and is used only for red colouring (`inputgraph.py:328-332`). If door placement should skip invented adjacencies, `bcn_edges` needs to be persisted separately at `inputgraph.py:377`, before triangulation overwrites the picture.
6. **`connect_graph.one_connected` leaves `edgecnt` stale** (`connect_graph.py:19-21` vs `handlers.py:753`). Does any downstream consumer read `graph.edgecnt` before `door_connectivity` recomputes it at `inputgraph.py:445`? Not traced in this session.
7. **Knowledge graph agreement**: `graphify explain "biconnectivity"` reports the same six functions at lines 18/31/42/53/68/86 and one inbound import edge from `source/trial/bdy.py:6`. It does **not** list the live importers (`inputgraph.py:24`, `ptpg_floorplanner.py:56`, `bdy.py:6`), so its inbound-edge coverage is incomplete. No contradiction with the code, just missing edges.
