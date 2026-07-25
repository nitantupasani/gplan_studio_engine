# canonical-order-family

Four files, three of them near-copies of one another, one of them a completely different
algorithm that only shares the word "canonical" in its name.

Files under review (all paths absolute, repo root `C:\Users\nitant\Documents\GPLAN_Revamp`):

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\polygonal\canonical.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\lettershape\lshape\canonical.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\lettershape\lshape\modifiedCanonical.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\lettershape\lshape\canonicalTransition.py`

---

## Purpose

Three of the four files (`polygonal/canonical.py`, `lshape/canonical.py`,
`lshape/modifiedCanonical.py`) all contain a class literally named `canonical`
(`polygonal/canonical.py:9`, `lshape/canonical.py:9`, `modifiedCanonical.py:9`) that computes a
**canonical ordering of a triangulated planar graph**: a numbering `v1, v2, v3, ..., vn` such
that each vertex, when added, lands on the current outer face and is adjacent to a contiguous
run of already-placed vertices. The implementation computes it in reverse: it repeatedly deletes
a removable vertex from the outer face of the remaining graph, assigning it the highest
remaining index. This is the shelling / Kant style of the de Fraysseix-Pach-Pollack canonical
ordering, expressed as a peeling loop rather than as an incremental placement.

The fourth file, `canonicalTransition.py`, is not a canonical ordering implementation at all.
It **consumes** an already-computed canonical order and replays the peel to emit a
**regular edge labeling (REL)**: an adjacency matrix where entries are relabeled `2` for
"left" edges and `3` for "right" edges (`canonicalTransition.py:204-205`,
`canonicalTransition.py:211-212`). Those `2`/`3` labels are exactly what the downstream dual
constructor reads (`GPLAN\GPLAN\source\floorplangen\dual.py:131`,
`dual.py:133`, `dual.py:227`, `dual.py:229`).

So the family is really two things wearing one name:
1. a canonical-ordering computer, triplicated with drift;
2. a canonical-order-to-REL converter, single copy.

---

## Where It Sits In The Pipeline

### Reachability trace, module by module

**`lshape/modifiedCanonical.py` -> LIVE via the `lshape` API endpoint.**

- `GPLAN\GPLAN\source\lettershape\lshape\Lshaped.py:9` -- `from .modifiedCanonical import canonical`
- Instantiated at `Lshaped.py:64` (`can = canonical()`) inside `LShapedFloorplan`
  (`Lshaped.py:24`), and again at `Lshaped.py:149` inside `multipleLshapedFloorplans`
  (`Lshaped.py:113`).
- `GPLAN\GPLAN\handlers.py:10` -- `import GPLAN.source.lettershape.lshape.Lshaped as Lshaped`
- `handlers.py:945` -- `Lshaped.LShapedFloorplan(graph, nodes_data)` inside
  `handle_letter_shape` (`handlers.py:939`); dimensioned branch calls it again at
  `handlers.py:969`.
- `handlers.py:1019` -- `Lshaped.multipleLshapedFloorplans(graph, nodes_data)` inside
  `handle_multiple_l` (`handlers.py:1015`).
- `GPLAN\GPLAN\api.py:13` -- `from GPLAN.handlers import *`
- `api.py:1262` -- `handle_letter_shape(ui, graph, nodes_data=nodes_data)` under
  `if caller == 'lshape'` (`api.py:1257`), inside `Documents.get_floorplans`
  (`api.py:1215`, class `Documents` at `api.py:1181`).
- `api.py:1320` -- `handle_multiple_l(ui, graph, nodes_data=nodes_data)` under
  `if caller == 'lshape'` in the `count > 1` branch (`api.py:1314`).

Verdict: **LIVE**, endpoint `caller == "lshape"`, both the single-plan and multiple-plan paths.

**`lshape/canonicalTransition.py` -> LIVE via the same `lshape` endpoint.**

- `Lshaped.py:10` -- `from ..lshape import canonicalTransition as Canonical_LShaped`
- `Lshaped.py:70` -- `my_rel = Canonical_LShaped.Canonical_L_Shaped(can.graph_data['indexToCanOrd'], graph)`
- `Lshaped.py:155` -- same call inside `multipleLshapedFloorplans`.
- Rest of the hop chain is identical to `modifiedCanonical.py` above (`handlers.py:945` /
  `handlers.py:1019`, then `api.py:1262` / `api.py:1320`).

Verdict: **LIVE**, endpoint `caller == "lshape"`.

**`polygonal/canonical.py` -> reachable from `handlers.py`, but NOT from any `api.py` endpoint.**

- `GPLAN\GPLAN\pythongui\gui.py:33` -- `from GPLAN.source.polygonal import canonical as cano`
- `gui.py:159` and `gui.py:1840` -- `self.canonicalObject = cano.canonical()`; the second is
  inside `polygonal_inputbox` (`gui.py:1837`), which also calls
  `self.canonicalObject.displayInputGraph(...)` at `gui.py:1841`.
- `handlers.py:1502` -- `graph.polyonalinput(gclass.canonicalObject, gclass.v1, gclass.v2, gclass.vn, gclass.po, ui.get_edges(), gclass.debugcano)` inside `handle_poly` (`handlers.py:1499`).
- `GPLAN\GPLAN\source\inputgraph.py:849-850` -- `def polyonalinput(self, cano, v1, v2, vn, priority_order, edge_set, debug_cano)` -> `cano.runWithArguments(self.nodecnt, v1, v2, vn, priority_order, self, edge_set, debug_cano)`, landing on `polygonal/canonical.py:95`.
- The only caller of `handle_poly` in the whole tree is
  `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\main.py:56`
  (`elif gclass.command == "poly": handle_poly(ui, graph, True, gclass)`), driven by the tkinter
  desktop GUI method `gui.gui_class.polygonal` (`gui.py:1703-1713`, which sets
  `self.command = "poly"` at `gui.py:1712`).
- A tree-wide grep for `handle_poly` / `polyonalinput` / `canonicalObject` returns only
  `handlers.py:51`, `handlers.py:1499`, `handlers.py:1502`, `gui.py:159`, `gui.py:1840`,
  `gui.py:1841`, `inputgraph.py:849`, `main.py:56`. **`api.py` never mentions any of them.**

Verdict: **LIVE only from the desktop tkinter entry point** (`main.py:56` -> `handlers.handle_poly`).
**DEAD from the HTTP/API surface**: no `caller` value in `Documents.get_floorplans`
(`api.py:1256-1312` for `count == 1`, `api.py:1313-1345` for `count > 1`) dispatches to
`handle_poly`. `api.py:9` imports `gui`, but only to build `gui.gui_class.Nodes` objects
(`api.py:1260`, `api.py:1318`), which never touches `canonicalObject`.

Its output is consumed by the polygonal dissection drawer:
`handlers.py:51` (`draw.draw_poly(gclass.canonicalObject.graph_data, ...)`) ->
`GPLAN\GPLAN\pythongui\drawing.py:273` (`def draw_poly(...)`) ->
`drawing.py:291` (`db = poly.dissected(...)`) ->
`GPLAN\GPLAN\source\polygonal\poly.py:20` (`class dissected`), which reads
`self.graph_data['currentCanonicalOrder'][self.noOfNodes-1]` at `poly.py:35`.

**`lshape/canonical.py` -> DEAD. No importers anywhere.**

A tree-wide grep over `GPLAN\**\*.py` for `canonical` produces exactly two import statements
touching the lshape package: `Lshaped.py:9` (`modifiedCanonical`) and `Lshaped.py:10`
(`canonicalTransition`). Nothing anywhere imports `lettershape.lshape.canonical`. Its only
self-entry is the `if __name__ == "__main__"` block at `lshape/canonical.py:294-295`, and that
path calls `run()` (`lshape/canonical.py:23`) which blocks on `input()` at
`lshape/canonical.py:28`. The project knowledge graph agrees: `graphify explain "canonical"`
resolves to `lshape/canonical.py:9` and lists nine edges, all of them `contains` /
`method` edges internal to that one file, with zero inbound import or call edges.

Verdict: **DEAD**.

---

## Entry Points (file:line)

| Entry point | Anchor | Status |
| --- | --- | --- |
| `Documents.get_floorplans` | `GPLAN\GPLAN\api.py:1215` | HTTP-facing root |
| `caller == 'lshape'` (single) | `GPLAN\GPLAN\api.py:1257`, dispatch `api.py:1262` | live |
| `caller == 'lshape'` (multiple) | `GPLAN\GPLAN\api.py:1314`, dispatch `api.py:1320` | live |
| `handle_letter_shape` | `GPLAN\GPLAN\handlers.py:939` | live |
| `handle_multiple_l` | `GPLAN\GPLAN\handlers.py:1015` | live |
| `Lshaped.LShapedFloorplan` | `GPLAN\GPLAN\source\lettershape\lshape\Lshaped.py:24` | live |
| `Lshaped.multipleLshapedFloorplans` | `Lshaped.py:113` | live |
| `modifiedCanonical.canonical.runWithArguments` | `modifiedCanonical.py:80`, called `Lshaped.py:66` and `Lshaped.py:151` | live |
| `modifiedCanonical.canonical.canonical_order` | `modifiedCanonical.py:103` | live |
| `canonicalTransition.Canonical_L_Shaped` | `canonicalTransition.py:73`, called `Lshaped.py:70` and `Lshaped.py:155` | live |
| `handle_poly` | `GPLAN\GPLAN\handlers.py:1499` | GUI-only, no API caller |
| `main.py` poly branch | `GPLAN\main.py:56` | desktop only |
| `InputGraph.polyonalinput` | `GPLAN\GPLAN\source\inputgraph.py:849` | GUI-only |
| `polygonal.canonical.runWithArguments` | `polygonal\canonical.py:95` | GUI-only |
| `polygonal.canonical.canonical_order` | `polygonal\canonical.py:181` | GUI-only |
| `lshape.canonical.runWithArguments` | `lshape\canonical.py:79` | **dead, no callers** |
| `lshape.canonical.canonical_order` | `lshape\canonical.py:101` | **dead, no callers** |

---

## Data Structures

All three `canonical` classes share the same core state. Anchors below are given for the live
`modifiedCanonical.py`, with the `polygonal/canonical.py` twin in parentheses.

**Per-vertex boolean/int arrays, length `n` (`n = graph.nodecnt`):**

- `mark` (`modifiedCanonical.py:106`; `polygonal/canonical.py:186`) -- vertex has already been
  assigned a canonical index and conceptually removed from the graph.
- `out` (`modifiedCanonical.py:108`; `polygonal/canonical.py:188`) -- vertex has ever been
  exposed on the outer face. It is set once (`modifiedCanonical.py:203-204`;
  `polygonal/canonical.py:259-260`) and **never cleared**.
- `chord` (`modifiedCanonical.py:107`; `polygonal/canonical.py:187`) -- vertex currently sits on
  a chord of the outer face and is therefore not removable.
- `visited` (`modifiedCanonical.py:109`) -- **only in `modifiedCanonical.py`**. An integer count
  of how many times a vertex has appeared in an outer-face update. Seeded at
  `modifiedCanonical.py:159-160`.
- `canord` (allocated `modifiedCanonical.py:89`; `polygonal/canonical.py:178`) -- `canord[v]` is
  the canonical index of vertex `v`. Written at `modifiedCanonical.py:185` / `:266` and
  `polygonal/canonical.py:239`.

**The outer face is not an explicit list.** It is derived on the fly at each chord update as
`out AND NOT mark`, with the two base vertices forced back in:

```
outer = np.logical_and(out, np.logical_not(mark))
outer[v1] = True
outer[v2] = True
outer_surface = np.where(outer == True)[0]
```
(`modifiedCanonical.py:362-365`; identical at `polygonal/canonical.py:314-317` and
`lshape/canonical.py:272-275`.)

**`self.graph_data`** dict, built at `modifiedCanonical.py:55-57` (`polygonal/canonical.py:174-176`):

- `'iteration'` -- length-`n` array of iteration counters.
- `'marked'` -- length-`n` array, iteration index -> vertex removed at that iteration.
- `'neighbors'` -- list of per-step new-outer-face vertex lists, appended at
  `modifiedCanonical.py:346` and reversed at `modifiedCanonical.py:293`.
- `'currentCanonicalOrder'` -- `n x n` matrix, a snapshot of `canord` after every step. The
  polygonal drawer reads the last row: `poly.py:35`.
- `'indexToCanOrd'` -- length-`n` array, canonical position `i` -> vertex `vk`
  (`modifiedCanonical.py:344`). **This is the only field `Lshaped.py` reads**
  (`Lshaped.py:69-70`).

**`networkx` graph `self.G`** (`modifiedCanonical.py:13`), built from the adjacency matrix at
`modifiedCanonical.py:61-63`, with a planarity assertion at `modifiedCanonical.py:70-72`.

**`canonicalTransition.py` structures** (all 1-based during accumulation, converted to 0-based
at `canonicalTransition.py:141-149`):

- `adj_matrix` -- canonically relabeled adjacency, built by `create_canonical_matrix`
  (`canonicalTransition.py:43-53`).
- `basis_edge` -- per removed vertex, the first edge `[i+1, n_cnt]` found scanning the deleted
  vertex's row (`canonicalTransition.py:99-104`).
- `point_order` -- per removed vertex, its neighbors along the *new* outer boundary after
  deletion (`canonicalTransition.py:111-116`).
- `edge_order` -- per removed vertex, a two-element `[left, right]` pair from `get_edge_order`
  (`canonicalTransition.py:25-40`, invoked at `canonicalTransition.py:126` and `:138`), with
  three hard-coded base cases at `canonicalTransition.py:119-124`.
- `left_edges` / `right_edges` -- the two edge classes of the REL (`calculateEdges`,
  `canonicalTransition.py:164-194`).
- `rel` -- the returned labeled matrix (`generate_rel`, `canonicalTransition.py:197-215`).

---

## Algorithm Walkthrough

### A. The canonical ordering (shared skeleton)

The base configuration, using `modifiedCanonical.py` line anchors. The other two set up the same
state in the same order, but the text is not byte-identical: `polygonal/canonical.py:181-220`
has no `visited` array, prints no neighbor lists, and still pre-assigns `canord[vn] = n - 1`
(`polygonal/canonical.py:220`), which `modifiedCanonical.py:156` has commented out.

1. `canord[v1] = 0` (`:111`), `mark[v1] = mark[v2] = True` (`:113-114`),
   `out[v1] = out[v2] = out[vn] = True` (`:118-120`), `canord[v2] = 1` (`:132`).
   So `v1` and `v2` are the base edge of the outer face: they get indices 0 and 1 and are
   pre-marked so they never get chosen again.
2. The peel loop counts **down**: `for i in range(n - 1, 1, -1)` (`:165` in the `cip > 4`
   branch, `:222` in the `cip <= 4` branch; `polygonal/canonical.py:222`;
   `lshape/canonical.py:151`). Index `i` is the canonical index the chosen vertex will receive,
   so the last vertex in canonical order is chosen first.
3. Candidate set each step:
   `poss = NOT mark AND out AND NOT chord` (`polygonal/canonical.py:225`;
   `lshape/canonical.py:154`), with an extra `AND selectedNeighbor` conjunct in
   `modifiedCanonical.py:177` and `:231`.
4. After choosing `vk`: `canord[vk] = i`, `mark[vk] = True`
   (`modifiedCanonical.py:185-186`; `polygonal/canonical.py:239-240`), then the *new* outer face
   contribution is the still-unmarked neighbors of `vk`, plus `v1`/`v2`:

```
for j in neighbors:
    if mark[j] == False or j == v1 or j == v2:
        neighborlist.append(j)
```
(`modifiedCanonical.py:193-195`; `polygonal/canonical.py:247-250`;
`lshape/canonical.py:204-206`.) These get `out[j] = True` (`modifiedCanonical.py:203-204`).

5. `updatechord` (`modifiedCanonical.py:360`; `polygonal/canonical.py:312`) recomputes the chord
   flags. Its criterion is a **degree count restricted to the outer face**: for each vertex on
   `outer_surface`, count how many other outer-surface vertices it is adjacent to
   (`modifiedCanonical.py:369-372`), and set
   `chord[v] = (out_neighbor_count[v] > 2)` (`modifiedCanonical.py:374-377`;
   `polygonal/canonical.py:325-328`). Rationale visible in the code: on a simple outer path each
   interior vertex has exactly two outer-face neighbors, so a third or more means a chord.
   A vertex carrying a chord is excluded from `poss` by the `NOT chord` conjunct above.

### B. Choice of `v1`, `v2`, `vn`

**L-shape (live).** `Lshaped.py:66` and `Lshaped.py:151`:

```
can.runWithArguments(graph.nodecnt, graph.west, graph.south, graph.north, triplet, graph, graph.matrix, cip)
```

Matching the signature `runWithArguments(self, noOfNodes, v1, v2, vn, triplet, graph, matrix, cip)`
(`modifiedCanonical.py:80`), this means **`v1 = graph.west`, `v2 = graph.south`, `vn = graph.north`**.
These four cardinal vertices are created inside `add_NESW` at `Lshaped.py:560-567` and wired into
a 4-cycle by `connect_news` (`Lshaped.py:631-640`). The extra `north-south` edge is temporarily
inserted at `Lshaped.py:59-60` so the graph is fully triangulated during the peel, then removed
at `Lshaped.py:67-68`. The concave-corner vertex `graph.northeast` is created earlier at
`Lshaped.py:439` inside `connect_northeast` (`Lshaped.py:434`).

**Polygonal (GUI-only).** `handlers.py:1502` passes `gclass.v1, gclass.v2, gclass.vn`, which are
literally typed by the user into three tkinter entry boxes (`gui.py:1848-1852`) and copied out at
`gui.py:1704-1706`, defaulting to `0, 1, 2` (`gui.py:170`, `:172`, `:174`). `gclass.po` is the
free-text "priority order" from `gui.py:1854`, read at `gui.py:1709`. These reach
`polygonal/canonical.py:95` through `inputgraph.polyonalinput` (`inputgraph.py:849-850`).

### C. The next-removable-vertex criterion, per implementation

**`polygonal/canonical.py` (GUI-only): no two-neighbor condition at all.**

```
if len(self.priority_order) > 0 and self.priority_order[0] in poss_vertex:
    vk = self.priority_order[0]
    self.priority_order.remove(self.priority_order[0])
else:
    vk = poss_vertex[0]
```
(`polygonal/canonical.py:231-237`.) The only structural filter is the chord test. Selection
otherwise honours a user-supplied priority list (parsed by regex at
`polygonal/canonical.py:135-140`) and falls back to the numerically smallest candidate index.

**`lshape/canonical.py` (dead): explicit marked-neighbor count.**

```
for vi in poss_vertex:
    if (vi == self.triplet[1]):
        continue
    count = 0
    for j in (list(self.G.neighbors(vi))):
        if mark[j] and (j != v1 and j != v2):
            count += 1
    if count > 1:
        vk = vi
        break
```
(`lshape/canonical.py:174-183`.) This is the literal "at least two already-placed neighbors,
not counting the two base vertices" condition. It also hard-codes the first three peels:
`vk = north` at `i == n-1`, `vk = east` at `i == n-2`, `vk = northeast` at `i == n-3`
(`lshape/canonical.py:161-166`).

**`modifiedCanonical.py` (live): the same idea re-expressed as a `visited` counter.**

Instead of recounting marked neighbors, it counts how many times a vertex has been pushed onto
the outer face:

```
selectedNeighbor = np.zeros(n,dtype="bool")
for j in range(0,n):
    if visited[j]>=2:
        selectedNeighbor[j] = True
    else:
        selectedNeighbor[j] = False
temp_array = np.logical_and(np.logical_and(np.logical_and(np.logical_not(mark), out), np.logical_not(chord)),selectedNeighbor)
```
(`modifiedCanonical.py:171-177`, repeated at `:225-231`.) `visited` is incremented once per
removed vertex that exposes it (`updateVisited`, `modifiedCanonical.py:335-338`, called at
`modifiedCanonical.py:202` and `:283`). `visited[j] >= 2` therefore means "at least two
already-removed vertices had `j` as an unmarked neighbor", which is the same
two-placed-neighbors property, computed incrementally instead of by rescan.

### D. `canonicalTransition.Canonical_L_Shaped`

Called once per floorplan with `can.graph_data['indexToCanOrd']` and the graph object
(`Lshaped.py:70`, `Lshaped.py:155`). Steps:

1. `can_ord_origin = deepcopy(canonical_order)` (`canonicalTransition.py:74`) -- keeps the
   position -> vertex map (floats).
2. `canonical_order = ceil(...).astype(int)`, then invert it into `can_ord_final` via
   `can_ord_final[canonical_order[i]] = i` (`canonicalTransition.py:75-80`). After
   `canonical_order = can_ord_final` (`:80`) the working array is **vertex -> canonical position**.
3. `create_canonical_matrix` (`canonicalTransition.py:43-53`, called at `:81`) relabels the
   adjacency matrix into canonical-position index space.
4. Peel loop `while n_cnt > 3` (`canonicalTransition.py:98`): repeatedly take the highest
   canonical index (`n_cnt - 1`), record its basis edge (`:99-104`), delete its row and column
   (`:106-107`), recompute the outer boundary via `Update_Graph` (`:56-70`, called `:109`),
   record which of its neighbors survive on that boundary as `point_order` (`:111-116`), and
   record an `edge_order` pair (`:119-127`). Decrement (`:133`).
5. Three fixed tail entries for the base triangle (`canonicalTransition.py:134-139`), then
   1-based to 0-based conversion (`:141-149`).
6. `calculateEdges` (`:164-194`) splits edges into `left_edges` / `right_edges` from
   `edge_order` (`:170-175`) and `basis_edge` (`:176-181`), then maps everything back from
   canonical-position space to vertex space through `can_ord_origin` (`:186-191`).
7. `generate_rel` (`:197-215`) writes the REL onto a copy of `graph.matrix`: label `2` for left
   edges (`:204-205`), label `3` for right edges (`:211-212`), with the reverse direction zeroed.
   Edges where both endpoints are in the last four indices (the NESW frame) are skipped
   (`:201-202`, `:208-209`).

`Lshaped.py:71` assigns the result straight into `graph.matrix`, and `get_floorplan`
(`Lshaped.py:531-538`) feeds it to `rdg.construct_dual`
(`GPLAN\GPLAN\source\floorplangen\rdg.py:20`), which routes it into `dual.py` where the `2`/`3`
labels are read (`dual.py:131`, `:133`, `:227`, `:229`).

**Answer to "does it transform one canonical order into another, or drive a state transition
during Lshaped construction?": neither.** It is a one-shot converter from a canonical order to a
regular edge labeling. It is called exactly twice in the tree, both times from `Lshaped.py`
(`:70`, `:155`), each time with `(can.graph_data['indexToCanOrd'], graph)`.

---

## Invariants And Preconditions

1. **Input must be planar.** `displayInputGraph` returns `False` if
   `nx.check_planarity` fails (`modifiedCanonical.py:70-72`; `polygonal/canonical.py:85-87`).
   Neither `Lshaped.py:65` nor `Lshaped.py:150` checks that return value.
2. **Input must be a triangulation.** `Lshaped.py:26` tests
   `graph.nodecnt - graph.edgecnt + len(opr.get_trngls(graph.matrix)) != 1` and runs separating-
   triangle handling if violated. The temporary `north-south` edge at `Lshaped.py:59-60` exists
   to keep the NESW frame triangulated for the duration of the peel and is removed at
   `Lshaped.py:67-68`.
3. **`v1` and `v2` are permanently on the outer face.** They are pre-marked
   (`modifiedCanonical.py:113-114`) yet force-injected into `outer_surface` on every chord update
   (`modifiedCanonical.py:363-364`), and re-admitted into the neighbor list at
   `modifiedCanonical.py:194`.
4. **`out` is monotone.** It is only ever set to `True` (`modifiedCanonical.py:203-204`); the
   effective outer face is always the derived `out AND NOT mark`.
5. **`vn` must be pre-exposed.** `out[vn] = True` at `modifiedCanonical.py:120` is what makes the
   first peel possible.
6. **`modifiedCanonical` requires the NESW/NE frame to already exist** on the graph object: it
   reads `self.lshapegraph.north`, `.east`, `.west`, `.south` (`modifiedCanonical.py:143`,
   `:159-160`) and `.northeast` (`:220`). Those attributes are created by `Lshaped.add_NESW`
   (`Lshaped.py:560-567`) and `Lshaped.connect_northeast` (`Lshaped.py:439`), so
   `runWithArguments` must be called after both.
7. **`modifiedCanonical`'s `cip <= 4` branch requires the triplet to be genuinely adjacent to
   `northeast`.** `L.remove(self.triplet[0])`, `L.remove(self.triplet[2])`,
   `L.remove(self.lshapegraph.northeast)` (`modifiedCanonical.py:218-220`) all raise `ValueError`
   if the element is absent from `list(self.G.neighbors(self.triplet[1]))`.
8. **`Canonical_L_Shaped` assumes the last four canonical positions are the NESW frame**, which
   is what the `numberOfVertices - 5` guards encode (`canonicalTransition.py:201`, `:208`).
9. **`Canonical_L_Shaped` assumes `west` and `south` are the two ends of the boundary walk**:
   `Update_Graph` rotates the boundary until it starts and ends at those two
   (`canonicalTransition.py:63-69`). That matches `v1 = west`, `v2 = south` from `Lshaped.py:66`.
10. **CIP budget.** `Lshaped.py:39-40` bails with the string `"CIPs greater than 5"` if
    `len(cip) > 5`; `Lshaped.py:126-127` does the same in the multiple path.

---

## Failure Modes

1. **Empty candidate set -> `IndexError`.** `poss_vertex[0]` is indexed unguarded at
   `modifiedCanonical.py:184`, `:237`, `:239`, `:246`; `polygonal/canonical.py:235`;
   `lshape/canonical.py:169`. If the chord test plus the `visited >= 2` conjunct eliminates every
   candidate, `np.where(...)` returns an empty array and the loop crashes.
2. **`getNext` returning `-2` silently corrupts `canord`.** `modifiedCanonical.py:321-326`
   returns `-2` when no valid successor exists (printing
   `"No options available for next iteration. Should not pop according to algo"` at `:325`). The
   caller at `modifiedCanonical.py:244` assigns that to `vk`, and `canord[vk] = i`
   (`modifiedCanonical.py:266`) then writes to the second-to-last array slot via Python negative
   indexing instead of raising. `mark[-2] = True` follows at `:267`, and
   `self.G.neighbors(-2)` at `:269` will then raise a networkx error, but only after `canord` has
   been silently corrupted.
3. **`vk` can be unbound.** In `lshape/canonical.py:174-183` and in the `count > 1` search, if no
   candidate passes the loop and `flag` was never set, `vk` carries over from the previous
   iteration or is undefined on the first pass -> `UnboundLocalError` or a silently repeated
   vertex. Same shape of hazard exists there because there is no `else` fallback.
4. **`polygonal/canonical.py` hard-crashes without a live tkinter root.**
   `self.debugCano = tk.IntVar(None)` at `polygonal/canonical.py:22` runs at construction time,
   and `canonical_order` ends with `if self.debugCano.get() == 1: plt.show()`
   (`polygonal/canonical.py:290-291`). It also writes an unconditional
   `plt.savefig("./source/polygonal/lastcanonicalorder.png")` (`polygonal/canonical.py:289`), a
   path relative to the process CWD.
5. **`displayGraph` relabel collision.** `polygonal/canonical.py:302-308` relabels nodes to their
   canonical indices with `nx.relabel_nodes`. If two vertices share a `canord` value (which the
   `-2` failure above can produce) the relabel silently merges nodes.
6. **Unchecked planarity result.** `Lshaped.py:65` calls `can.displayInputGraph(...)` and discards
   the `False` return from `modifiedCanonical.py:72`, so a non-planar input proceeds into the
   peel.
7. **Massive unconditional stdout.** All three classes `print` per iteration
   (for example `modifiedCanonical.py:166-167`, `:181`, `:187`, `:191`, `:201`, `:206`, `:338`).
   The API path suppresses this by monkeypatching `builtins.print` to a no-op
   (`api.py:1219-1222`), which is the only reason it is not a throughput problem in production.

---

## Coupling (what breaks if you change this)

- **`graph_data['indexToCanOrd']` is the contract between `modifiedCanonical.py` and
  `canonicalTransition.py`.** Written at `modifiedCanonical.py:344`, read at `Lshaped.py:69-70`
  and `Lshaped.py:154-155`, consumed as the sole input to `Canonical_L_Shaped`
  (`canonicalTransition.py:73`). Changing its orientation (position -> vertex) breaks the
  inversion at `canonicalTransition.py:76-80` and therefore every downstream index.
- **`graph_data['currentCanonicalOrder']` is the contract between `polygonal/canonical.py` and
  the polygonal drawer.** Written at `polygonal/canonical.py:300`, read at `poly.py:35` via
  `drawing.py:291`. Only the last row is used.
- **The `2` / `3` REL encoding** emitted at `canonicalTransition.py:204-205` and `:211-212` is
  read by `dual.py:131`, `:133`, `:227`, `:229`. Changing the label values breaks dual
  construction for every L-shaped plan.
- **`modifiedCanonical` reads five attributes off the `InputGraph` object it is handed**:
  `north`, `east`, `west`, `south` (`modifiedCanonical.py:143`, `:159-160`, `:299-300`) and
  `northeast` (`:220`). Renaming any of them in `Lshaped.add_NESW` (`Lshaped.py:560-567`) or
  `connect_northeast` (`Lshaped.py:439`) breaks the peel.
- **The `runWithArguments` signature drifted between the twins.** `polygonal/canonical.py:95`
  takes `(noOfNodes, v1, v2, vn, priority_order, graph, edge_set, debugCano)`;
  `modifiedCanonical.py:80` takes `(noOfNodes, v1, v2, vn, triplet, graph, matrix, cip)`;
  `lshape/canonical.py:79` takes the same minus `cip`. They are **not interchangeable**, so the
  two live call sites (`inputgraph.py:850` and `Lshaped.py:66`) cannot be pointed at each other's
  module without a shim.
- **`displayInputGraph` also drifted.** `polygonal/canonical.py:69` takes an `edge_set` and
  iterates pairs (`:80-81`); `modifiedCanonical.py:48` takes an adjacency `matrix` and derives
  edges with `np.where` (`:61-63`). The `graph_data` dict is initialised in
  `displayInputGraph` for the lshape twins (`modifiedCanonical.py:55-57`) but in
  `runWithArguments` for the polygonal one (`polygonal/canonical.py:174-176`), so call order
  differs.

---

## Dead Or Duplicated Code

**Entire dead module: `GPLAN\GPLAN\source\lettershape\lshape\canonical.py`.**
Zero importers in the tree. It is a strict ancestor of `modifiedCanonical.py`: `diff -u` between
the two shows the modified version adds only `self.cip` (`modifiedCanonical.py:22`), the `cip`
parameter (`:80`, `:100`), the `visited` array and its two seeds (`:109`, `:159-160`), the
`visited >= 2` filter, and the split of the single peel loop into two CIP-dependent branches
(`:163` vs `:210`). Everything else in the file is identical.
**Deleting it would break nothing.** `Lshaped.py` imports `modifiedCanonical`
(`Lshaped.py:9`), not this file; `poly.py` never touches the lettershape package.

**Effectively dead for the API surface: `GPLAN\GPLAN\source\polygonal\canonical.py`.**
Its only route is `main.py:56` -> `handlers.handle_poly` (`handlers.py:1499`), the desktop
tkinter path. No `caller` value in `Documents.get_floorplans` reaches it. Deleting it would break
`gui.py:33` (import), `gui.py:159`, `gui.py:1840-1841`, `handlers.py:1502` and the polygonal
dissection drawer (`drawing.py:291` -> `poly.py:35`). So: dead relative to the API, live relative
to the desktop GUI. **`poly.py` would break if it were deleted**, because `poly.dissected.__init__`
reads `graph_data['currentCanonicalOrder']` (`poly.py:35`) and `graph_data['iteration']`
(`poly.py:31`), and `polygonal/canonical.py` is the only producer of that dict for the polygonal
path. **`Lshaped.py` would not break**: it never imports the polygonal module.

**Duplication across the three `canonical` classes.** Method by method, with the exact degree of
sameness:

- `updateGraphData` (`polygonal/canonical.py:293-300`, `lshape/canonical.py:251-258`,
  `modifiedCanonical.py:341-348`) is byte-identical in all three.
- `displayGraph` (`polygonal/canonical.py:302-308`, `lshape/canonical.py:260-266`,
  `modifiedCanonical.py:350-356`) is byte-identical in all three.
- `updatechord` is byte-identical between the two lshape copies (`lshape/canonical.py:270-291`,
  `modifiedCanonical.py:360-381`) and algorithmically identical but not byte-identical in the
  polygonal copy (`polygonal/canonical.py:312-332`). Two lines differ: the outer-surface debug
  print is commented out at `polygonal/canonical.py:318` while it is live at
  `lshape/canonical.py:276` and `modifiedCanonical.py:366`, and the polygonal copy has no
  counterpart to the commented per-vertex count print at `lshape/canonical.py:283` /
  `modifiedCanonical.py:373`. The reconstruction (`out AND NOT mark` with `v1`/`v2` forced in)
  and the chord test (`> 2` outer neighbors, `polygonal/canonical.py:325-328`,
  `lshape/canonical.py:284-287`, `modifiedCanonical.py:374-377`) are the same in all three, so
  nothing above depends on the difference.
- `run` is byte-identical between the two lshape copies (`lshape/canonical.py:23-45`,
  `modifiedCanonical.py:24-46`) but differs substantially in the polygonal copy
  (`polygonal/canonical.py:24-67`), which adds a block absent from the other two: it appends two
  synthetic vertices `n` and `n + 1`, wires them to `v1`, `v2` and `vn`, then reassigns
  `v1 = n`, `v2 = n + 1`, `n += 2` before calling `canonical_order`
  (`polygonal/canonical.py:44-65`). A comment typo also differs (`# inputting the graph` at
  `polygonal/canonical.py:26` versus `# inputting te graph` at `lshape/canonical.py:25`).

The `run` method in every copy blocks on `input()`
(`polygonal/canonical.py:29`, `lshape/canonical.py:28`, `modifiedCanonical.py:29`) and is only
reachable through each file's `if __name__ == "__main__"` block
(`polygonal/canonical.py:335-336`, `lshape/canonical.py:294-295`,
`modifiedCanonical.py:384-385`) -- dead in every deployment.

**Dead function inside a live module:** `process_edge` (`canonicalTransition.py:10-23`). A
tree-wide grep for `process_edge` returns only its definition line. No callers.

**Dead locals in the live module:**
- `news` is computed at `modifiedCanonical.py:143` and never read again.
- `secondary_vertices` is initialised as an empty set at `modifiedCanonical.py:144`, every line
  that would populate it is commented out (`:145-155`), and it is still printed at
  `modifiedCanonical.py:297` -- it will always print `set()`.
- `self.lshapematrix` is assigned at `modifiedCanonical.py:99` and never read.
- `self.new_node_coordinate` (`modifiedCanonical.py:18`) is only touched by `displayGraph`
  (`:350-356`), whose only call site is commented out (`:301`).
- All matplotlib figure setup in `modifiedCanonical.py:306-319` is commented out, yet
  `matplotlib.pyplot` is still imported at `modifiedCanonical.py:3`.
- `from turtle import pos` at `modifiedCanonical.py:1` and `lshape/canonical.py:1` is unused.
- `import re` at `modifiedCanonical.py:6` is unused (the regex path is commented out at `:91`).

---

## Open Questions

1. **The `cip` branch comments are inverted.** `modifiedCanonical.py:163` reads
   `if(len(self.cip)>4): #atmost 4 CIP` and prints `"cip>4 in canonical ordering "` (`:164`),
   while the `else` at `:210` carries the comment `#CIP>4` and prints
   `"cip<=4 in canonical ordering "` (`:211`). The prints match the condition; the comment on
   `:210` does not. Whether the comment or the branch structure is the error cannot be settled
   from the code.
2. **Which `cip` is actually passed.** `Lshaped.py:66` passes the `cip` computed at
   `Lshaped.py:38`, *before* `connect_northeast` (`:52`) and `add_NESW` (`:57`) mutate the graph.
   `graph.cip` is recomputed at `Lshaped.py:55` and again inside `add_NESW` via
   `find_cips_L_shaped` (`Lshaped.py:553`, `:595-628`), and `find_cips_L_shaped` always returns
   a 4-element list on the non-degenerate path (`Lshaped.py:604`, `:622`, via
   `boundary_path_single` at `Lshaped.py:490-493`). Whether the branch at
   `modifiedCanonical.py:163` was meant to test the pre-frame CIP count or the post-frame one is
   not determinable from code or comments.
3. **Why `canord[vn] = n - 1` was removed.** `lshape/canonical.py:150` and
   `polygonal/canonical.py:220` both pre-assign `canord[vn] = n - 1`;
   `modifiedCanonical.py:156` has it commented out with no explanation, alongside a second
   commented line `# canord[vn-1] = self.lshapegraph.northeast` (`:157`) that is index-confused
   on its face. In practice `north` still receives index `n-1` because `visited[north] = 2`
   (`:159`) makes it the only candidate on the first peel, so the removal is behaviour-preserving
   *if* that seeding holds. Whether that was the intent or an accident is not stated anywhere.
4. **`visited[east] = 1` (`modifiedCanonical.py:160`) versus `visited[north] = 2` (`:159`).**
   The asymmetry forces `north` first and makes `east` eligible only after one more exposure.
   The predecessor file achieved the same effect by hard-coding `north`, `east`, `northeast` for
   the first three peels (`lshape/canonical.py:161-166`). The seeding values are not explained by
   any comment. Whether `northeast` (the concave corner of the L) is still guaranteed the third
   position under the `visited` scheme is not asserted anywhere in the code, and I did not
   execute the pipeline to confirm it.
5. **Comment/behaviour mismatch in `canonicalTransition.py`.** The comment at `:75` labels
   `canonical_order` as "map from index to its canonical order" and `:79` labels `can_ord_final`
   as "map from canonical order to the vertex". Reading the consumers
   (`create_canonical_matrix` at `:49-51`, `Update_Graph` at `:63-64`, `calculateEdges` at
   `:187-190`), the actual orientations are the reverse: `can_ord_origin` / `indexToCanOrd` is
   position -> vertex, and `can_ord_final` is vertex -> position. The code is self-consistent;
   the two comments are swapped. Recorded here rather than fixed.
6. **`path1_conditions` always returns `True`.** `Lshaped.py:389-431`: `flag = True` at `:393`
   and the only assignment inside the loop is also `flag = True` (`:428`), so the function can
   never return `False`. Its caller `find_paths` (`Lshaped.py:385-386`) therefore always returns
   `path1`. This sits one hop upstream of the canonical order and shapes the `northeast`
   attachment, but it is outside the four files under review, so I am not asserting intent.
7. **`graphify` knowledge-graph coverage gap.** `graphify explain "canonical"` resolves to the
   **dead** `lshape/canonical.py:9` and reports only intra-file `contains`/`method` edges, with
   no import or call edges into or out of any of the four modules. The graph therefore neither
   confirms nor contradicts the reachability findings above; the reachability verdicts in this
   dossier come from `grep` over the source tree, not from the graph.
