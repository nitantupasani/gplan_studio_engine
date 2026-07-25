# lshaped-core

Unit: `GPLAN/GPLAN/source/lettershape/lshape/Lshaped.py` (641 lines, 24 KB).
Sibling task `canonical-order-family` owns `canonical.py`, `canonicalTransition.py`, `modifiedCanonical.py`; they are treated here as black boxes, with every call site into them anchored. Black box does not mean shape-agnostic: `Lshaped.py:9-10` are their only importers in the repo, and both of the ones actually used read L-specific state (`triplet`, `cip`, `graph.northeast`, `graph.north/east/south/west`), so the REL half of the pipeline is L-aware even though the dual half is not.

All paths below are absolute where they name a file for the reader; anchors use repo-relative `file:line` for brevity and all resolve under `C:\Users\nitant\Documents\GPLAN_Revamp\`.

---

## Purpose

`Lshaped.py` produces an L-shaped floorplan from a plane triangulated adjacency graph by **augmenting the graph with one extra "northeast" vertex, generating an ordinary rectangular dual of the augmented graph, and then deleting the northeast room from the output**. The notch left by the deleted corner room is the L.

It is not a separate geometry engine. It reuses the rectangular pipeline's dual constructor verbatim (`rdg.construct_dual`, `GPLAN/GPLAN/source/lettershape/lshape/Lshaped.py:536`) and, on one of its two branches, the rectangular pipeline's contraction/expansion REL generator (`Lshaped.py:100-108`). What is genuinely local to this module is: choosing where on the boundary the notch goes (`find_triplet`, `find_paths`), inserting the NE vertex (`connect_northeast`), and re-deriving the four NEWS boundary paths so that NE lands on both the north and the east boundary (`add_NESW`, `find_cips_L_shaped`).

Two entry functions exist: single floorplan (`LShapedFloorplan`) and multiple floorplans (`multipleLshapedFloorplans`), one per candidate notch position.

## Where It Sits In The Pipeline

HTTP boundary (local bridge), then API dispatch, then handler, then this module:

- `GPLAN/local_engine_bridge.py:159` `@app.post("/api/generate/<shape>")`, with `caller=shape` at `GPLAN/local_engine_bridge.py:108` and the call at `GPLAN/local_engine_bridge.py:167` `Documents.get_floorplans(**kwargs)`.
- `GPLAN/GPLAN/api.py:1215` `def get_floorplans(starting_from, count, caller, nodes_list, graph, rectangular, ...)`.
  - `count == 1` and `caller == 'lshape'`: `GPLAN/GPLAN/api.py:1257-1262`, builds `nodes_data` as `gui.gui_class.Nodes(node['id'], node['x'], node['y'])` (`api.py:1260`) and calls `handle_letter_shape(ui, graph, nodes_data=nodes_data)` (`api.py:1262`).
  - `count > 1` and `caller == 'lshape'`: `GPLAN/GPLAN/api.py:1314-1320`, calls `handle_multiple_l(ui, graph, nodes_data=nodes_data)` (`api.py:1320`).
  - `caller == "multiple_l"` also reaches `handle_multiple_l` (`GPLAN/GPLAN/api.py:1407-1408`), but with no `nodes_data`, so it falls back to `gclass.app.nodes_data` at `GPLAN/GPLAN/handlers.py:1016` and will raise `AttributeError` when `gclass is None` (which is what `api.py:1408` passes).
- `GPLAN/GPLAN/handlers.py:10` `import GPLAN.source.lettershape.lshape.Lshaped as Lshaped`.
- `GPLAN/GPLAN/handlers.py:945` `Lshaped.LShapedFloorplan(graph, nodes_data)` (undimensioned single).
- `GPLAN/GPLAN/handlers.py:969` `Lshaped.LShapedFloorplan(graph, gclass.app.nodes_data)` (dimensioned single).
- `GPLAN/GPLAN/handlers.py:1019` `Lshaped.multipleLshapedFloorplans(graph, nodes_data)` (multiple).

So the module is **reachable**, not dead. The endpoint that exposes L-shaped plans is `POST /api/generate/lshape` on the local Flask bridge (`GPLAN/local_engine_bridge.py:159`), which routes into `Documents.get_floorplans(caller='lshape')`. The Tk GUI reaches the same handler through `command = "letter_shape"` (`GPLAN/GPLAN/pythongui/gui.py:1947-1951`).

Downstream, results are converted by `inputgraph.get_final_traversal(graph)` (`GPLAN/GPLAN/handlers.py:954` and `handlers.py:1027`) and serialised into `Room`/`Wall` objects at `GPLAN/GPLAN/api.py:1427-1452`.

## Entry Points (file:line)

Public (called from outside the module):

- `GPLAN/GPLAN/source/lettershape/lshape/Lshaped.py:24` `LShapedFloorplan(graph, nodes_data)`
- `GPLAN/GPLAN/source/lettershape/lshape/Lshaped.py:113` `multipleLshapedFloorplans(graph, nodes_data)`

Internal (full inventory, in file order):

| line | function | role |
|---|---|---|
| `Lshaped.py:24` | `LShapedFloorplan` | single-plan orchestrator |
| `Lshaped.py:77` | `trivialL` | fallback when no triplet exists |
| `Lshaped.py:113` | `multipleLshapedFloorplans` | multi-plan orchestrator |
| `Lshaped.py:197` | `find_multiple_triplet` | all admissible notch anchors |
| `Lshaped.py:236` | `find_cips` | boundary + shortcuts + CIPs |
| `Lshaped.py:258` | `find_triplet` | first admissible notch anchor |
| `Lshaped.py:305` | `find_paths` | boundary path `path1` for NE |
| `Lshaped.py:389` | `path1_conditions` | validity predicate (no-op, always True) |
| `Lshaped.py:434` | `connect_northeast` | inserts the NE vertex |
| `Lshaped.py:454` | `add_edges` | matrix helper |
| `Lshaped.py:462` | `new_matrix` | matrix growth helper |
| `Lshaped.py:470` | `boundary_path_single` | 4 boundary paths with NE forced as a corner |
| `Lshaped.py:498` | `get_rel` | **dead and broken**, see Dead Or Duplicated Code |
| `Lshaped.py:531` | `get_floorplan` | dual construction + NE registered as extra node |
| `Lshaped.py:541` | `add_NESW` | 4-completion (N, E, S, W) |
| `Lshaped.py:593` | `find_cips_L_shaped` | CIP repair so NE is a corner |
| `Lshaped.py:631` | `connect_news` | wires the NEWS cycle |

Calls into the sibling canonical family (black boxes, exact arguments):

- `Lshaped.py:9` `from .modifiedCanonical import canonical` (note: `canonical.py` in the same directory is **not** imported here).
- `Lshaped.py:10` `from ..lshape import canonicalTransition as Canonical_LShaped`.
- `Lshaped.py:64` `can = canonical()`; `Lshaped.py:65` `can.displayInputGraph(graph.nodecnt, graph.matrix, nodes_data)`; `Lshaped.py:66` `can.runWithArguments(graph.nodecnt, graph.west, graph.south, graph.north, triplet, graph, graph.matrix, cip)`; result read at `Lshaped.py:69-70` as `can.graph_data['indexToCanOrd']`.
- `Lshaped.py:70` `my_rel = Canonical_LShaped.Canonical_L_Shaped(can.graph_data['indexToCanOrd'], graph)`, assigned to `graph.matrix` at `Lshaped.py:71`.
- The identical four calls repeat in the multi path at `Lshaped.py:149`, `Lshaped.py:150`, `Lshaped.py:151`, `Lshaped.py:155`.

Argument-order note worth recording: `runWithArguments(self, noOfNodes, v1, v2, vn, triplet, graph, matrix, cip)` (`GPLAN/GPLAN/source/lettershape/lshape/modifiedCanonical.py:80`), so `v1 = graph.west`, `v2 = graph.south`, `vn = graph.north`. The `canonical.py` variant has a 7-parameter signature without `cip` (`GPLAN/GPLAN/source/lettershape/lshape/canonical.py:79`), so it is not interchangeable with the call made here.

## Data Structures

Everything is carried on the mutated `InputGraph` instance. Attributes **defined by `InputGraph.__init__`** and used here: `matrix`, `nodecnt`, `edgecnt`, `bdy_nodes`, `bdy_edges`, `mergednodes`, `irreg_nodes1`, `irreg_nodes2`, `extranodes`, `coordinates`, `room_x/room_y/room_width/room_height`, `rel_matrix_list`, `graph_list`, `fpcnt`, `nodecnt_list` (`GPLAN/GPLAN/source/inputgraph.py:115-155`).

Attributes **invented by this module** (they do not exist on a fresh `InputGraph`; a grep of `inputgraph.py` for `self.north`, `self.northeast`, `self.cip`, `self.user_matrix`, `self.rdg_vertices`, `self.node_count_required` returns nothing):

- `graph.northeast` (`Lshaped.py:439`), `graph.original_node_count` (`Lshaped.py:436`).
- `graph.north`, `graph.east`, `graph.south`, `graph.west` (`Lshaped.py:560-567`).
- `graph.cip` (`Lshaped.py:55`, `Lshaped.py:78`, `Lshaped.py:94`), `graph.user_matrix` (`Lshaped.py:54`, `Lshaped.py:92`).
- `graph.node_count_required`, `graph.edge_count_required` (`Lshaped.py:556-557`).
- `graph.rdg_vertices`, `graph.rdg_vertices2`, `graph.to_be_merged_vertices` are **read but never written anywhere in the repo** (`Lshaped.py:616-617`); see Failure Modes.

Index layout after augmentation (this is the load-bearing invariant of the whole module):

```
0 .. n-1        original rooms (plus any dummies added by separating-triangle handling)
n               northeast  (Lshaped.py:439)
n+1 n+2 n+3 n+4 north, east, south, west (Lshaped.py:560-567)
```

`graph.nodecnt` ends at `n+5`. `rdg.construct_dual` allocates `nodecnt - 4` rooms (`GPLAN/GPLAN/source/floorplangen/rdg.py:69-72`), so it returns `n+1` rectangles: the real rooms plus the NE rectangle.

`path1`: an ordered list of boundary vertices, always starting `[a, b, c]` from the triplet (`Lshaped.py:342-345`) and optionally extended along the clockwise boundary (`Lshaped.py:357-379`). It is the set of vertices the NE vertex attaches to.

`cip` / `graph.cip`: for `find_cips` a list of critical independent paths from `cip.find_cip` (`Lshaped.py:253`); after `find_cips_L_shaped` it is redefined to exactly four boundary paths (`Lshaped.py:604` / `Lshaped.py:622`), the N, E, S, W chains.

## Algorithm Walkthrough

### Phase table (single-plan path)

| # | phase | lines | consumes | produces |
|---|---|---|---|---|
| 1 | separating-triangle elimination | `Lshaped.py:26-35` | `graph.matrix`, `graph.coordinates` | de-ST'd matrix, `mergednodes`, `irreg_nodes1/2`; recomputes `nodecnt`, `edgecnt` |
| 2 | CIP computation | `Lshaped.py:38-41` via `find_cips` `Lshaped.py:236-255` | matrix | `cip` list, and as a side effect `graph.bdy_nodes`, `graph.bdy_edges` |
| 3 | notch anchor selection | `Lshaped.py:44` via `find_triplet` `Lshaped.py:258-302` | `bdy_nodes`, `bdy_edges` | triplet `(a,b,c)` or `-1` |
| 3a | fallback | `Lshaped.py:47` via `trivialL` `Lshaped.py:77-110` | matrix | full plan, returns early |
| 4 | notch path | `Lshaped.py:50` via `find_paths` `Lshaped.py:305-386` | triplet, `cip`, boundary | `path1` |
| 5 | NE insertion | `Lshaped.py:52` via `connect_northeast` `Lshaped.py:434-451` | `path1` | `(n+1) x (n+1)` matrix with NE joined to every vertex of `path1` |
| 6 | CIP recomputation on the pre-NE matrix | `Lshaped.py:55` | `graph.matrix` (still the pre-NE matrix at this point) | `graph.cip` |
| 7 | 4-completion | `Lshaped.py:57` via `add_NESW` `Lshaped.py:541-590` (which calls `find_cips_L_shaped` `Lshaped.py:593-628` and `connect_news` `Lshaped.py:631-641`) | NE matrix, `path1`, `graph.cip` | `(n+5) x (n+5)` matrix, NEWS indices set |
| 8 | temporary N-S chord | `Lshaped.py:59-60`, removed at `Lshaped.py:67-68` | matrix | matrix with an extra edge only for the canonical-order run |
| 9 | canonical order | `Lshaped.py:64-66` (black box `modifiedCanonical`) | `nodecnt`, west/south/north, triplet, matrix, `cip` | `can.graph_data['indexToCanOrd']` |
| 10 | REL construction | `Lshaped.py:70-71` (black box `canonicalTransition`) | canonical order, graph | REL matrix, stored back into `graph.matrix` |
| 11 | dual + NE registration | `Lshaped.py:74` via `get_floorplan` `Lshaped.py:531-538` | REL, `nodecnt`, `mergednodes`, `irreg_nodes1` | `room_x/room_y/room_width/room_height`; NE appended to `graph.extranodes` (`Lshaped.py:533`) |

### The strategy question, settled from the call sequence

It is **rectangular dual first, then carve**, done by adding one extra vertex, not by any geometric subtraction and not by leaving a corner region empty in the topology.

Evidence chain: `connect_northeast` adds a genuine graph vertex (`Lshaped.py:439-440`) and joins it to `path1` (`Lshaped.py:446`). `add_NESW` then does the standard 4-completion on the augmented graph (`Lshaped.py:560-585`).

Of the two stages that follow, only the dual constructor is shared and L-unaware. `rdg.construct_dual(graph.matrix, graph.nodecnt, ...)` (`Lshaped.py:536`) is the same call the rectangular pipeline makes at `GPLAN/GPLAN/source/inputgraph.py:313`, with the same four arguments, and it knows nothing about the notch. The REL stage above it is L-specific: `Lshaped.py:66` passes `triplet` and `cip` into `runWithArguments`, which stores them as `self.triplet` and `self.cip` and stores the whole `InputGraph` as `self.lshapegraph` (`GPLAN/GPLAN/source/lettershape/lshape/modifiedCanonical.py:97-101`); `canonical_order` then branches on `len(self.cip) > 4` (`modifiedCanonical.py:162-163`) and, on the `<= 4` branch, builds `L = list(self.G.neighbors(self.triplet[1]))` and removes the NE vertex from it by name (`modifiedCanonical.py:217-220`). `canonicalTransition.Canonical_L_Shaped` likewise reads the NEWS attributes this module invents (see Coupling, `canonicalTransition.py:155-156`).

The "rectangular dual first, then carve" conclusion is unaffected by that, because none of the L-awareness in the REL stage removes a region: at the moment `rdg.construct_dual` returns, the plan is still a full rectangle of `n+1` rooms. The L appears only because `get_floorplan` registers NE as an extra node (`Lshaped.py:533`) and `get_final_traversal` then drops every node in `graph.extranodes` from the output (`GPLAN/GPLAN/source/inputgraph.py:1620-1622`). The NE room's rectangle is the missing corner.

### Where the concave corner comes from

Not a fifth exterior vertex in the NEWS sense, and not a special canonical-order start. It is an **ordinary interior vertex, `graph.northeast`, created at `Lshaped.py:439`**:

```
graph.northeast = graph.nodecnt      # Lshaped.py:439
graph.nodecnt += 1                   # Lshaped.py:440
```

Its room is forced into the top-right corner by `add_NESW`, which chooses the north CIP as the one containing both `path1[0]` and NE, and the east CIP as the one containing both `path1[-1]` and NE:

```
for i in range(len(cips)):
    if path1[0] in cips[i] and graph.northeast in cips[i]:      # Lshaped.py:574
        n_cip = i
    if path1[len(path1) - 1] in cips[i] and graph.northeast in cips[i]:   # Lshaped.py:576
        e_cip = i
```

so NE is adjacent to both `graph.north` and `graph.east` (`Lshaped.py:579-580`), i.e. its rectangle touches both the top and the right edge of the bounding rectangle. `find_cips_L_shaped` guarantees NE is one of the four corner points by seeding `corner_points = [graph.northeast]` before computing the boundary split (`Lshaped.py:596-597`, consumed at `Lshaped.py:604` and `Lshaped.py:622`). Deleting that corner room yields the concave corner.

### The `trivialL` branch

Taken when `find_triplet` returns `-1` (`Lshaped.py:45-47`). It picks `path1` randomly rather than from a triplet: from a random prefix of a random CIP (`Lshaped.py:81-82`) or, when there are no CIPs, from a random prefix of the ordered boundary (`Lshaped.py:85-89`). It then runs the same NE insertion and 4-completion (`Lshaped.py:83`/`Lshaped.py:90`, `Lshaped.py:96`) but **skips the canonical-order family entirely** and instead derives the REL by contraction/expansion (`Lshaped.py:99-108`) before calling the same `get_floorplan` (`Lshaped.py:110`).

### The multi-plan path

`multipleLshapedFloorplans` (`Lshaped.py:113-194`) repeats phases 1-2 verbatim (`Lshaped.py:115-127` duplicates `Lshaped.py:26-41`), enumerates every admissible triplet with `find_multiple_triplet` (`Lshaped.py:130`), and loops phases 4-10 per triplet (`Lshaped.py:136-155`). For each it wraps the REL into a fresh `InputGraph` (`Lshaped.py:162`) with `extranodes = [graph.northeast]` (`Lshaped.py:170`) and appends it to `graph.graph_list` (`Lshaped.py:172`). Duals are built in a second pass at `Lshaped.py:188-192`. There is no `trivialL` fallback here: an empty `tripletSet` silently yields zero floorplans.

## Invariants And Preconditions

1. **NEWS must be the last four indices.** `exp.basecase` hard-codes `nodecnt-4 .. nodecnt-1` as N, E, S, W (`GPLAN/GPLAN/source/floorplangen/expansion.py:39-48`) and `rdg.construct_dual` drops exactly the last four (`GPLAN/GPLAN/source/floorplangen/rdg.py:69-77`). `add_NESW` allocates them last, after NE (`Lshaped.py:560-567`), which satisfies this.
2. **NE must be strictly before NEWS**, otherwise it would be dropped as an exterior vertex instead of becoming a room. Guaranteed by ordering: `connect_northeast` runs at `Lshaped.py:52`, `add_NESW` at `Lshaped.py:57`.
3. **`find_cips` must run before `find_triplet`.** `find_triplet` reads `graph.bdy_nodes`/`graph.bdy_edges` (`Lshaped.py:263`) which are only populated as a side effect of `find_cips` (`Lshaped.py:244`). The ordering at `Lshaped.py:38` then `Lshaped.py:44` is load-bearing; reordering them raises `AttributeError`/empty-boundary errors.
4. **`graph.cip` must be set before `add_NESW`.** `find_cips_L_shaped` opens with `cips = graph.cip` (`Lshaped.py:595`). Set at `Lshaped.py:55` (single) and `Lshaped.py:141` (multi) and `Lshaped.py:94` (trivial).
5. **`find_cips_L_shaped` must yield exactly four paths**, because `add_NESW` indexes `cips[(n_cip + 2) % 4]` and `cips[(e_cip + 2) % 4]` (`Lshaped.py:581-582`).
6. **CIP count must be at most 5** at entry (`Lshaped.py:39`), the classic 4-completion feasibility bound relaxed by one for the notch.
7. **The graph must be a plane triangulation without separating triangles** when it reaches the canonical order; phase 1 enforces this via `st.handle_STs` (`Lshaped.py:26-35`) using the Euler check `nodecnt - edgecnt + #triangles != 1`.
8. `nodes_data` must be a sequence of objects with `.pos_x`/`.pos_y` (`GPLAN/GPLAN/source/lettershape/lshape/modifiedCanonical.py:49-53`); `api.py:1260` supplies `gui.gui_class.Nodes`.

## Failure Modes

Graph classes and inputs that break L-shaped construction, and whether the code detects them:

1. **More than 5 CIPs.** Detected, but the detection is useless: `LShapedFloorplan` returns the string `"CIPs greater than 5"` (`Lshaped.py:39-40`) and the caller discards the return value (`GPLAN/GPLAN/handlers.py:945`). Execution continues to `graph.final_traversal = inputgraph.get_final_traversal(graph)` (`handlers.py:954`) over the untouched zero-filled `room_x/room_y/room_width/room_height` from `InputGraph.__init__` (`GPLAN/GPLAN/source/inputgraph.py:127-131`), so the API emits degenerate zero-area rooms instead of an error. Same silent-string return in the multi path (`Lshaped.py:126-127`).
2. **No admissible triplet** (every boundary triple `a,b,c` has the chord `(a,c)`, or an alternative common neighbour). Detected at `Lshaped.py:45` and routed to `trivialL`, which picks a random notch path instead. In the multi path there is no such fallback: an empty `tripletSet` from `Lshaped.py:130` simply skips the loop body and produces zero plans.
3. **More than 4 shortcuts after NE insertion.** Not survivable. `find_cips_L_shaped:614-618` enters `while len(shortcut) > 4` and calls
   `sr.remove_shortcut(shortcut[index], graph, graph.rdg_vertices, graph.rdg_vertices2, graph.to_be_merged_vertices)` (`Lshaped.py:616-617`).
   Two independent defects: `graph.rdg_vertices` is never assigned anywhere in the repo (the only other occurrence is the equally unreachable `GPLAN/GPLAN/source/polygonal/lshape.py:367`), so this raises `AttributeError`; and even with the attribute present the arity is wrong, since `sr.remove_shortcut(shortcut, trngls, matrix)` takes three parameters (`GPLAN/GPLAN/source/irregular/shortcutresolver.py:34`). Any graph whose boundary carries five or more shortcuts crashes here.
4. **`path1` endpoints not co-located with NE in any CIP.** `n_cip`/`e_cip` are only assigned inside the `if` bodies at `Lshaped.py:574-577`; if neither condition ever fires, `Lshaped.py:579` raises `UnboundLocalError`. There is no guard.
5. **Fewer than four CIPs after augmentation.** Handled by a random-corner repair (`Lshaped.py:603-605`) that consumes the **stale, pre-NE** `graph.cip` computed at `Lshaped.py:55` against a boundary list recomputed post-NE at `Lshaped.py:604`. This branch can therefore split the boundary at corner points that are not on the current CIP structure.
6. **Non-planar augmented graph.** Not detected. `displayInputGraph` returns `False` when `nx.check_planarity` fails (`GPLAN/GPLAN/source/lettershape/lshape/modifiedCanonical.py:70-72`), but the return value is discarded at `Lshaped.py:65`, so the canonical order runs on a non-planar graph.
7. **`find_paths` may return `None`.** The `return path1` is guarded by `if path1_conditions(...)` (`Lshaped.py:385-386`). `path1_conditions` initialises `flag = True` (`Lshaped.py:393`) and never sets it `False` (the only assignment in the body is `flag = True` at `Lshaped.py:428`), so today it always returns truthy and the `None` path is unreachable. The guard is decorative; if anyone "fixes" `path1_conditions` to actually reject, `connect_northeast(graph, None)` will raise at `Lshaped.py:456`.
8. **`len(cip)` of 3 or fewer.** `find_paths` only extends `path1` for `len(cip) == 5` (`Lshaped.py:357`) or `len(cip) == 4` (`Lshaped.py:374`). Otherwise `path1` stays the bare triplet `[a,b,c]`, i.e. the notch is forced to the minimum width with no diagnostic.
9. **Two-room graphs.** Special-cased with a hard-coded CIP set `[[0], [0, 1], [1, 2], [2, 0]]` when `edgecnt == 3 and nodecnt == 3` (`Lshaped.py:600-601`); note `nodecnt` there already includes NE, so this fires for 2 original rooms.
10. **Dimensioned L requests run the U-shape generator too.** In `handle_letter_shape` the `elif` chain is commented out (`GPLAN/GPLAN/handlers.py:970-974`), leaving `Ushaped.UShapedFloorplan(graph)` at `GPLAN/GPLAN/handlers.py:975` inside the `if L Shape` block, so it executes immediately after `LShapedFloorplan` on every dimensioned L request. This is a handler defect, not a `Lshaped.py` defect, but it is on the only dimensioned path into this module.
11. **`graph.edgecnt` accumulates across iterations in the multi path.** `add_edges` increments it per edge (`Lshaped.py:457`) and the loop restores only `graph.matrix` and `graph.nodecnt` (`Lshaped.py:184-185`), never `edgecnt`. The `InputGraph` built at `Lshaped.py:162` therefore receives an inflated edge count from the second triplet onward.

## Coupling (what breaks if you change this)

- **`rdg.construct_dual` contract.** Consumed at `Lshaped.py:536` and `Lshaped.py:189`. It returns exactly four arrays sized `nodecnt - 4` (`GPLAN/GPLAN/source/floorplangen/rdg.py:69-89`). Changing its return arity or its "last four are NEWS" assumption breaks this module identically to the rectangular one.
- **`get_final_traversal`'s extranodes filter.** The L only exists because `GPLAN/GPLAN/source/inputgraph.py:1620-1622` skips `graph.extranodes`. If that filter changes shape (for instance to a list-of-lists), the NE room reappears and the plan becomes a plain rectangle. Note `handlers.py:981-982` already wraps `graph.extranodes` into a list-of-lists on the dimensioned path, after `Lshaped.py:533` appended a bare integer.
- **NEWS index allocation order.** `Lshaped.py:560-567` must stay N, E, S, W to match `exp.basecase` (`GPLAN/GPLAN/source/floorplangen/expansion.py:39-48`) and `news.add_news` (`GPLAN/GPLAN/source/boundary/news.py:265-269`).
- **`modifiedCanonical.runWithArguments` signature.** `Lshaped.py:66` passes 8 positional arguments matching `modifiedCanonical.py:80`. The sibling `canonical.py:79` has 7 parameters, so swapping the import at `Lshaped.py:9` back to `canonical` breaks the call.
- **`Canonical_L_Shaped` return.** `Lshaped.py:71` assigns the return straight into `graph.matrix` and treats it as a REL. It reads `graph.north/west/south/east` internally (`GPLAN/GPLAN/source/lettershape/lshape/canonicalTransition.py:155-156`), so the attributes invented at `Lshaped.py:560-567` are part of its contract.
- **`handlers.py:1002` `graph.nodecnt -= 4`** compensates for the NEWS vertices this module leaves in `nodecnt`. If `add_NESW` ever stops mutating `nodecnt`, that line silently corrupts the dimensioned path.
- **`api.py:1448` indexes `nodes_list[k]`** per traversal entry, so the number of rooms surviving `get_final_traversal` must equal `len(nodes_list)`. That balance depends on exactly one NE node being in `extranodes` and on separating-triangle dummies being in `mergednodes`.

## Dead Or Duplicated Code

Stated plainly, no charitable reinterpretation:

- **`get_rel` (`Lshaped.py:498-528`) is dead and cannot run.** No call site exists in this file or anywhere in the repo. It also would not execute: `cntr.contract(graph.matrix, goodnodes)` at `Lshaped.py:505` and `Lshaped.py:509` passes 2 arguments to a 3-parameter function (`GPLAN/GPLAN/source/floorplangen/contraction.py:187`) and unpacks 2 return values from a 4-value return; it sets `graph.contraction = []` at `Lshaped.py:500` but then reads `graph.contractions` at `Lshaped.py:515`; and `k` is referenced at `Lshaped.py:520` after a `while` that may never assign it.
- **`connect_news` (`Lshaped.py:631-641`) duplicates `news.connect_news` (`GPLAN/GPLAN/source/boundary/news.py:230-247`).** Same eight assignments, one using `graph.north/east/south/west` and the other using `nodecnt + k` offsets. The `news` module is already imported at `Lshaped.py:17`.
- **`boundary_path_single` (`Lshaped.py:470-495`) is a copy of `news.bdy_path` (`GPLAN/GPLAN/source/boundary/news.py:35-65`)**, with two edits: `corner_points` is pre-seeded by the caller with NE (`Lshaped.py:596-597`), and paths that already contain NE do not contribute a random corner (`Lshaped.py:472-474`). The remaining 20 lines, including the four boundary slices, are line-for-line identical.
- **`add_NESW` (`Lshaped.py:541-590`) reimplements `news.add_news` (`GPLAN/GPLAN/source/boundary/news.py:249-271`)** with the matrix growth inlined via `new_matrix` (`Lshaped.py:462-467`, itself a copy of the `np.zeros` + block-assign idiom at `news.py:263-264`).
- **`trivialL`'s REL block (`Lshaped.py:99-108`) is copied from the rectangular single-dual pipeline (`GPLAN/GPLAN/source/inputgraph.py:303-312`)**, verbatim down to the `while len(cntrs) != 0` loop. This is reuse of `contraction`/`expansion` by import (`Lshaped.py:19-20`), but the orchestration around them is duplicated rather than factored. The same block is duplicated again in the sibling letter shapes (`GPLAN/GPLAN/source/lettershape/tshape/tshape.py:133-134`, `GPLAN/GPLAN/source/lettershape/zshape/zshape.py:133-134`, `GPLAN/GPLAN/source/staircaseshape/staircaseshape.py:127`).
- **`find_multiple_triplet` (`Lshaped.py:197-235`) duplicates `find_triplet` (`Lshaped.py:258-302`).** Identical boundary walk, identical chord test, identical alternative-neighbour test; the only differences are collecting into a list versus breaking, and `H.edges` versus `H.edges()` at `Lshaped.py:227` (both valid on a NetworkX `OutEdgeView`, so this is cosmetic, not a bug).
- **Phase 1 of the two entry points is duplicated:** `Lshaped.py:26-41` and `Lshaped.py:115-127` are the same separating-triangle block plus CIP guard.
- **`GPLAN/GPLAN/source/lettershape/lshape/canonical.py` is not used by this module.** `Lshaped.py:9` imports `canonical` from `modifiedCanonical`, and a repo-wide grep for `modifiedCanonical|import canonical` finds only `Lshaped.py:9-10`. `canonical.py` has no importer; ownership of that fact belongs to the sibling task, recorded here as an observation.
- **`GPLAN/GPLAN/source/polygonal/lshape.py:26` defines a second `LShapedFloorplan(graph)`** which nothing imports (no `polygonal.lshape` import exists in the tree). It is an older, unreachable duplicate of the same idea, and it carries the same broken `sr.remove_shortcut` five-argument call at `GPLAN/GPLAN/source/polygonal/lshape.py:367`.
- **Debug `print` calls are pervasive** (`Lshaped.py:41`, `51`, `53`, `56`, `61`, `69`, `79`, `95`, `330`, `340`, `353-354`, `359`, `362`, `367`, `371`, `381-382`, `448-449`, `485-486`, `527-528`, `587-588`, `627`, `194`). They are suppressed only because `api.py:1217-1222` monkey-patches `builtins.print` to a no-op for the duration of `get_floorplans`.

## Open Questions

1. **Inputs beyond the adjacency graph.** The only extra argument is `nodes_data` (`Lshaped.py:24`), and its sole use is `can.displayInputGraph(graph.nodecnt, graph.matrix, nodes_data)` at `Lshaped.py:65`, which reads `.pos_x`/`.pos_y` into `self.node_coordinate` (`modifiedCanonical.py:49-53`) for a plotting block that is commented out (`modifiedCanonical.py:74-77`). So **there is no user-chosen corner room and no dimension input into this module**: the notch position is chosen by `find_triplet` taking the first admissible boundary triple (`Lshaped.py:294-295`) or, in `trivialL`, by `randint` (`Lshaped.py:81-82`, `Lshaped.py:89`). Dimensions are applied afterwards by `graph.single_floorplan(...)` at `GPLAN/GPLAN/handlers.py:1004-1005`. Open question: is the absence of a corner-selection parameter intentional, or was a UI control planned? `find_multiple_triplet` exists to enumerate all choices, which suggests the latter.
2. **`nodes_data` length mismatch.** `displayInputGraph` is called at `Lshaped.py:65` **after** the graph grew to `n+5` nodes, so `noOfNodes` is `n+5` while `nodes_data` still has `n` entries. Harmless today because the coordinates are only used by dead plotting code, but any future consumer of `self.node_coordinate` will read a short list.
3. **Stale `graph.cip` in the `len(cips) < 4` branch.** `Lshaped.py:55` computes CIPs on the pre-NE matrix, and `find_cips_L_shaped` at `Lshaped.py:603-605` consumes them alongside a post-NE boundary. Whether this was intended (NE deliberately excluded from CIP derivation) or is a sequencing slip is not determinable from the code.
4. **`multipleLshapedFloorplans` never resets `graph.edgecnt`** between triplets (`Lshaped.py:184-185`), and the `InputGraph` created at `Lshaped.py:162` receives `graph.coordinates` of length `n` against `nodecnt = n+5`. The crossing check tolerates it (`get_points_edges` loops over `len(x_list)`, `GPLAN/GPLAN/source/graphoperations/graph_crossings.py:171-180`, so the 5 added vertices are silently ignored), but if the check does return `True`, `inputgraph.py:162-165` replaces `self.coordinates` with a planar layout of all `n+5` nodes, changing the array's length mid-flight. Unclear whether any downstream consumer depends on that length.
5. **`Lshaped.py:59-60` adds a north-south edge before the canonical order and removes it at `Lshaped.py:67-68`.** The comment-free code does not say why the canonical-order routine needs that chord. Confirming its role belongs to the `canonical-order-family` task.
6. **`path1_conditions` (`Lshaped.py:389-431`) computes `leftOfB`/`rightofB` and then throws the result away.** The loop at `Lshaped.py:426-429` sets `flag = True` where it presumably meant `flag = False`. Whether the intended predicate was "no vertex may see both sides of `b`" cannot be confirmed from the code alone, and flipping it would change which triplets are accepted.
7. **Knowledge graph agreement.** `graphify explain "Lshaped.py"` reports the same import edges and the same contained functions (`LShapedFloorplan` L24, `trivialL` L77, `multipleLshapedFloorplans` L113, `find_cips` L236, `find_paths` L305, `get_rel` L498, `add_NESW` L541, `find_cips_L_shaped` L593). No disagreement with the source was found. The graph does not record that `get_rel` is uncalled.
