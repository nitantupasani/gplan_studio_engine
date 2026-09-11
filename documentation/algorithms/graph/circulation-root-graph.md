# circulation-root-graph

Update 2026-09-11: this dossier describes the retained legacy GUI graph path.
The current existing-plan service is owned by
[`circulation_engine`](../circulation/IMPLEMENTATION.md). Its connected pruning
and finite-width/access validation replace coverage-only pruning for new APIs.
The [research experiments](../circulation/RESEARCH.md) reproduce disconnected
legacy pruning using actual methods from local and both verified team commits.

Graph-algorithm half of `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\circulation.py`.
Scope: `circulation.__init__` (line 52) through `remove_redundant_corridors` (line 384), plus module-level helpers at lines 894 to 975.
Out of scope (sibling dossier `circulation-root-geometry`): `Point`/`Edge`/`Room`/`RFP` (lines 14 to 46), `adjust_RFP_to_circulation` and everything from line 446 to 892, and `main()` (line 978).

---

## Purpose

Given a PTPG (properly triangulated planar graph) whose vertices are rooms and whose edges are room adjacencies, this half of the module inserts a **spanning circulation**: it subdivides graph edges with new "corridor" vertices so that every room touches at least one corridor, and the corridors themselves form a connected tree hanging off a single entry door.

The core is `circulation_algorithm` (line 235), a BFS over the triangular faces of the PTPG seeded at one exterior edge. It produces three artifacts consumed downstream:

- `self.circulation_graph` (line 302): the original graph with corridor vertices spliced in.
- `self.adjacency` (line 303): `{corridor_vertex: [roomA, roomB]}`, the pair of rooms each corridor was inserted between.
- `self.corridor_tree` (line 304): the induced subgraph on corridor vertices only.

The rest of the in-scope code is optional post-processing: `remove_redundant_corridors` (line 384) + `min_tree_set_cover` (line 341) prune the spanning circulation down to a minimum set cover of rooms, and `remove_corridor` (line 149) / `donot_include` (line 125) delete individual corridors by edge contraction. `multiple_circulation` (line 90) and `find_exterior_edges` (line 100) were meant to enumerate one circulation per exterior edge; both are broken and unreachable (see Dead Or Duplicated Code).

---

## Where It Sits In The Pipeline

**Liveness verdict: root `circulation.py` is the LIVE implementation. `source\circulation\circulation.py` and `source\multiple_circ.py` are both dead.**

Exact import lines:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py:31` -> `import GPLAN.circulation as cir` (this is the root file).
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py` has **no** circulation import of its own. It reaches the module transitively through `api.py:13` -> `from GPLAN.handlers import *`.
- Nothing anywhere imports `GPLAN.source.circulation.circulation`. A repo-wide grep for `source.circulation` / `source/circulation` / `multiple_circ` outside those three files returns zero hits.
- `source\multiple_circ.py:10` does `import circulation` (bare, not `GPLAN.circulation`), which cannot resolve under the `GPLAN.` package layout. It is unimportable as well as unimported.

Call chain into the live file:

```
api.py:1232  ui...set_isCirculation(circulationEnabled)
api.py:1309 / 1353 / 1390  handle_door_connectivity(ui, graph)      # gclass defaults to None
handlers.py:1747-1748      if ui.get_isCirculation() == 1: handle_circulation(ui, graph, drawGUI, gclass)
handlers.py:492            handle_circulation(...)                    # 5 branches by dimensioning mode
handlers.py:527/577/634/685/715/737  call_circulation_new(...)
handlers.py:104            circulation_obj = cir.circulation(g, ui.get_corridor_thickness(), rfp, gclass.rem)
handlers.py:116            circulation_obj.circulation_algorithm(entry[0], entry[1])
handlers.py:160 / 226      circulation_obj.remove_corridor(circulation_obj.circulation_graph, x[0], x[1])
handlers.py:230            circulation_obj.adjust_RFP_to_circulation()   # -> remove_redundant_corridors at circulation.py:461
```

Only four names from the module are touched by `handlers.py`: `cir.circulation`, `cir.Room`, `cir.RFP`, `cir.plot`.

Important caveat on which *endpoint* this serves: `handle_circulation` dereferences `gclass` unconditionally (`gclass.open` at `handlers.py:504`, `gclass.ptpg` at 523, `gclass.output_data[0]` at 526) and `call_circulation_new` reads `entry = gclass.entry_door` at `handlers.py:83`. The API path (`api.py:1309`) passes `gclass=None`. So circulation is effectively reachable only from the Tk GUI entry point (`GPLAN\main.py:40` calls `handle_circulation(ui, graph, True, gclass)` with a real `gclass`); the headless API path would raise `AttributeError: 'NoneType' object has no attribute 'entry_door'` before the algorithm ran. See Open Questions.

**Older vs newer, quantified.** Root `circulation.py` is 1306 lines; `source\circulation\circulation.py` is 872 lines. A line-level diff shows **644 lines identical** between them, i.e. about 74 percent of the older file survives verbatim inside the root file, and the root file adds roughly 660 lines on top. The root file is unambiguously the **newer superset**:

| Feature | root `circulation.py` | `source\circulation\circulation.py` |
| --- | --- | --- |
| `__init__` signature | `(graph, thickness=0.1, rfp=None, opti=1)` (line 52) | `(graph, rfp=None)` (line 53), thickness hardcoded 0.1 (line 60) |
| dimensioning fields (`is_dimensioned`, `dimension_constraints`, `room_area`, ...) | lines 63 to 71 | absent |
| `remove_corridor`, `donot_include` | lines 149, 125 | absent |
| `min_tree_set_cover`, `list_intersect`, `remove_redundant_corridors`, `corridor_tree` | lines 341, 323, 384, 73 | absent |
| `check_dimensions_feasibility`, `check_mindim_feasibility` | lines 843, 869 | absent |
| `find_exterior_edges` via `bdy.Boundary` | line 100 | absent |
| `multiple_circulation_fixed_entry` (recursive multi-circulation) | dropped | line 81 |
| `is_subgraph` | module level, unused (line 958) | method, used at line 178 |

Both files share the same `circulation_algorithm` BFS core (root line 235, old line 197).

---

## Entry Points (file:line)

Live, called from outside the module:

- `GPLAN\GPLAN\circulation.py:52` -> `circulation.__init__(graph, thickness, rfp, opti)`; called at `handlers.py:104`.
- `GPLAN\GPLAN\circulation.py:235` -> `circulation.circulation_algorithm(v1, v2)`; called at `handlers.py:116`. Returns `1` on success, `0` on a non-exterior entry edge.
- `GPLAN\GPLAN\circulation.py:149` -> `circulation.remove_corridor(graph, v1, v2)`; called at `handlers.py:160` and `handlers.py:226`.
- `GPLAN\GPLAN\circulation.py:941` -> `plot(graph, m)`; called at `handlers.py:103` and `handlers.py:117`.

Live, called only from inside the module (from the out-of-scope `adjust_RFP_to_circulation`):

- `GPLAN\GPLAN\circulation.py:384` -> `remove_redundant_corridors()`; called at `circulation.py:461`, guarded by `if(self.rem_red_rooms == 1)` at line 460.
- `GPLAN\GPLAN\circulation.py:341` -> `min_tree_set_cover(A, b)`; called at `circulation.py:425`.
- `GPLAN\GPLAN\circulation.py:323` -> `list_intersect(l1, l2)`; called at `circulation.py:364`.
- `GPLAN\GPLAN\circulation.py:307` -> `corridor_boundary_rooms(corridor_vertex)`; called at `circulation.py:481` and `circulation.py:144`.

Not reachable from any entry point: `disp_rel_push` (line 80), `multiple_circulation` (line 90), `find_exterior_edges` (line 100), `donot_include` (line 125), `wheel_graph` (line 894), `complete_graph` (line 921), `is_subgraph` (line 958).

---

## Data Structures

State set by `__init__` (lines 53 to 77) that this half owns:

- `self.graph` (line 53): the input PTPG, `m = len(self.graph)` rooms, never mutated by `circulation_algorithm` (it deep-copies at line 243).
- `self.circulation_graph` (line 55, written line 302): rooms `0..m-1` plus corridor vertices `m, m+1, ...`.
- `self.adjacency` (line 54, written line 303): `dict` mapping corridor vertex -> sorted `[roomA, roomB]` pair that corridor was inserted between. This is the module's contract with `adjust_RFP_to_circulation` and with `handlers.py:156` / `handlers.py:222`.
- `self.corridor_tree` (line 73, written line 304): `nx.induced_subgraph(circulation_graph, range(m, len(circulation_graph)))`, the corridor-only subgraph.
- `self.corridor_thickness` (line 58): from the `thickness` parameter, used by the geometry half only.
- `self.rem_red_rooms` (line 74): from the `opti` parameter. See "What `opti` switches" below.
- `self.exterior_edges` (line 62): filled only by the dead `find_exterior_edges`.
- `self.multiple_circ` (line 61): filled only by the dead `multiple_circulation`.

Module global `i = 0` (line 12) is a print counter, incremented at `circulation.py:479` and read at `circulation.py:316`. Cosmetic only.

**Vertex numbering convention.** Rooms occupy `0 .. m-1` where `m = len(self.graph)`. Corridor vertices occupy `m .. m + k - 1` in insertion order, established at `circulation.py:285`:

```python
corridor_vertices = [x+m for x in range(len(adjacency))]
```

This remap is only correct because `n` (the next vertex id, initialised `n = m` at lines 248 to 249) and `corridor_counter` (line 255) are incremented in lockstep inside the loop (lines 277 and 280). Corridor vertex `m` is always the **entry door**: it is the corridor placed on the seed exterior edge. `plot` colours exactly this range red (`nodelist=list(range(m,len(graph)))`, line 952), and `adjust_RFP_to_circulation` skips it geometrically by starting its loop at `start + 1` (`circulation.py:475`).

---

## Algorithm Walkthrough

### `circulation_algorithm(v1, v2)` (line 235)

Yes: it inserts a corridor vertex on the entry edge and then grows the circulation by walking the adjacent triangles, BFS order.

**Phase 0, setup (lines 243 to 257).** Deep-copy the input graph (243). `n = m = len(graph)` (248, 249). Seed tuple `s = (v1-1, v2-1, -1)` (250): the caller's entry vertices are **1-indexed** and converted to 0-indexed here, and `-1` is the sentinel for "no previous corridor". `adjacency = {}` and `corridor_counter = 0` (254, 255). `queue = [s]` (256, 257).

**Phase 1, BFS over faces (lines 260 to 282).** Pop the front tuple `s = (a, b, prev_corridor)` (262). Snapshot the common neighbours of `a` and `b` (263) and keep only those that are **rooms**, `ne < m` (264). For each such `ne`, meaning for the triangle `(a, b, ne)`:

- Add edges `a-n` and `b-n` (265, 266): the new corridor vertex `n` subdivides edge `a-b`.
- Remove edge `a-b` (268) inside a `try`. On failure print `"WARNING!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE"` and `return 0` (270, 271).
- If `prev_corridor > 0`, add edge `n-prev_corridor` (273 to 275): this is what chains corridors into a connected tree.
- Add edge `n-ne` (276): the corridor also touches the apex room of the triangle.
- `n += 1` (277).
- Record `adjacency[corridor_counter] = [a, b]` (279), `corridor_counter += 1` (280).
- Enqueue the two new frontier edges `(ne, a, n-1)` and `(ne, b, n-1)` (281, 282), each carrying the corridor just created as their `prev`.

So **per step the circulation graph gains exactly one vertex and four edges** (`a-n`, `b-n`, `ne-n`, and `n-prev` when `prev` exists) and loses one edge (`a-b`).

The exterior-edge guard is emergent, not an explicit check. A PTPG exterior edge borders exactly one triangle, so line 263 yields one room and the `for` body runs once. An interior edge borders two triangles, so the body runs twice; on the second pass `graph.remove_edge(a, b)` at line 268 raises because the edge was already deleted, the `except` fires, and the function returns `0`. `handlers.py:118` treats `0` as "give up, return None".

**Phase 2, renumber and publish (lines 285 to 305).** Remap integer keys `0..k-1` to actual vertex ids `m..m+k-1` (285, 288), sort each room pair (291 to 293), print the room-block adjacency matrix (297, 300), then assign `self.circulation_graph`, `self.adjacency`, `self.corridor_tree` (302 to 304) and `return 1`.

### `find_exterior_edges(coord)` (line 100) and `donot_include(graph_size, circ, v)` (line 125)

Neither "excludes exterior edges from hosting corridors". They do different things and neither is live.

- `find_exterior_edges` **collects** the exterior edges rather than excluding them, so `multiple_circulation` (line 90) can seed one circulation per exterior edge (line 96, 97). It rebuilds an edge set from the adjacency matrix (110 to 113), hands it to `bdy.Boundary(...).identify_bdy()` (114, 115), and flattens the returned boundary walks into consecutive pairs (116 to 122). It is exterior edges that are *usable* as entry edges, per the Phase 1 guard above.
- `donot_include` **isolates a room**: for room `v`, it finds every neighbour of `v` in the circulation graph whose id is `>= graph_size`, meaning every corridor touching `v` (139 to 141), then calls `remove_corridor` on each (143 to 145). The docstring at line 126 states the intent: "make the room corresponding to v isolated (no corridor connects it)". This is the "private room" feature; the live code path implements the same idea differently through `gclass.public_rooms(corridors)` at `handlers.py:157`.

Both are dead. `find_exterior_edges` cannot run at all: line 107 calls `nx.to_numpy_matrix`, which was removed in NetworkX 3.0 and is absent from the installed NetworkX 3.1, and line 114 calls bare `bdy.Boundary` while the only import is `import GPLAN.bdy` at line 8, which binds the name `GPLAN`, not `bdy`, so line 114 is a `NameError` even if line 107 were fixed.

### `remove_corridor(graph, v1, v2)` (line 149)

Removing a corridor is implemented as **reversing the subdivision by edge contraction**, not by node deletion. The comments at lines 173 to 175 record that deleting the vertex and re-adding `v1-v2` did not work; approach 3 is what ships.

Legality gate, three nested checks (165 to 169):

1. `v1 < m and v2 < m`: both arguments must be rooms, else print "The two vertices passed must correspond to rooms" (232).
2. `self.graph.has_edge(v1, v2)`: the rooms must be adjacent in the *original* graph, else "The rooms are not adjacent" (230).
3. `[v1,v2] in self.adjacency.values()`: a corridor must actually sit between them, else "There is no corridor vertex between these rooms" (228).

Then it looks up the corridor vertex `i` by reverse dictionary lookup (171), finds the room `r` that completes the triangle via common neighbours of `i` with `v1` and with `v2` (177 to 183), and decides which of `i-v1` or `i-v2` to contract based on whether corridors already join `r-v1` (`c1`, line 187) or `r-v2` (`c2`, line 189):

- neither (`i` is a leaf corridor): contract `v1-i` arbitrarily (194).
- `c1` only: contract `v2-i` (199).
- `c2` only: contract `v1-i` (203).
- both (`i` is interior to two faces): pick randomly and delete the spurious adjacency `v[p]-r` (215 to 218).

Finally `self.circulation_graph = mod_circ` and `del self.adjacency[i]` (221, 223).

### `min_tree_set_cover(A, b)` (line 341) and `remove_redundant_corridors` (line 384)

**The set-cover instance.** Universe `X = list(range(len(self.graph)))`, that is **all rooms** (line 355). Each subset is a corridor's coverage list. `A` is `rooms_dict` built in `remove_redundant_corridors` (lines 395 to 402): for corridor `c` separating `[r0, r1]`, its coverage is `[r0, r1] + list(nx.common_neighbors(self.graph, r0, r1))`, i.e. the two rooms it splits **plus** the apex rooms of the one or two triangles on that edge. So a corridor "covers" three or four rooms. `b` is a pre-forced list of corridors that must be in the answer.

**The algorithm is greedy, not exact.** Lines 356 to 358 pre-subtract everything already covered by `b`. Line 359 takes `L = list(A.values())`. The loop at 362 to 379 repeatedly scores every subset by `list_intersect` (line 364, which is `len(set(X) & set(l))`, line 337), picks the arg-max (368), appends that **subset** to `msc` (377), and subtracts it from `X` (379). Ties are broken by `list.index`, so the lowest-numbered corridor wins; the commented block at 370 to 374 is an abandoned random tie-break. Classic greedy set cover with the `H_n` approximation factor, no exactness claim.

Note the return type: `min_tree_set_cover` returns a list of **room lists**, not corridor ids.

**How `remove_redundant_corridors` uses it.**

- Step 1a (390 to 402): build `rooms_dict`, corridor -> covered rooms, restricted to `x > m` (line 394). The strict `>` deliberately drops corridor `m`, the entry door, per the comment at 396 to 397.
- Step 1b (406 to 412): build `corridors_dict`, room -> corridors touching it, `i >= m` (line 410).
- Step 2, forced corridors (415 to 423): every room whose corridor list has length exactly 1 forces that corridor into the answer, unless it is the door corridor `m` (line 421). These are rooms with no alternative access.
- Then `msc_corridors = self.min_tree_set_cover(rooms_dict, corridors)` (425), and each returned room-list is mapped back to a corridor id by reverse value lookup (427):
  `list(rooms_dict.keys())[list(rooms_dict.values()).index(x)]`.
- Returns `corridors`, the list of corridor vertices to keep (443).

**How the pruning bites.** `remove_redundant_corridors` never edits `circulation_graph`. It returns a whitelist. The pruning happens in the geometry half: `circulation.py:457` defaults `required_corridors` to every corridor, line 460 to 461 replaces it with the whitelist when `rem_red_rooms == 1`, and the corridor-widening loop at 475 to 483 skips any corridor not in `required_corridors` via the `else: continue` at 484 to 485. So a pruned corridor simply never gets physical width carved out of the floorplan; it stays in the graph as a zero-thickness artifact.

**Step 3 is commented out.** Lines 431 to 441 would have re-added the corridor-tree path vertices between every kept pair so the kept corridors stay connected. It is dead, and it is the only reader of `self.corridor_tree` (line 438).

### Module helpers, verdict per function

- `wheel_graph(n)` (line 894): **test scaffolding, dead.** Builds a wheel adjacency matrix plus circular coordinates. Its only call site in the whole repo is `circulation.py:1268`, inside `main()`'s `test_multiple_circ`, which is itself commented out at line 1294.
- `complete_graph(n)` (line 921): **test scaffolding, dead.** Only referenced at `circulation.py:1275` and `circulation.py:1282`, both inside comments.
- `plot(graph, m)` (line 941): **LIVE.** Called from `handlers.py:103` and `handlers.py:117`, and internally at `circulation.py:137` and `147`. It calls `plt.show()` at line 956 (blocking).
- `is_subgraph(g1, k)` (line 958): **dead, and buggy.** Zero call sites anywhere in the repo. Its loop at 969 to 972 varies `i` from 4 to `k` for the wheel size but always draws subgraphs of size `k` (`itertools.combinations(g1, k)`), so it can only ever match `nx.wheel_graph(k)`; the `i` loop is wasted work. It is the descendant of the *method* `is_subgraph` at `source\circulation\circulation.py:72`, which was actually used there at line 178.

### What `opti` switches (line 52, line 74)

`opti` is stored as `self.rem_red_rooms` (line 74) and read at exactly one place, `circulation.py:460`:

```python
if(self.rem_red_rooms == 1):
    required_corridors = self.remove_redundant_corridors()
```

- `opti == 1`: **minimum circulation.** Only the greedy set-cover corridors get physical width.
- anything else, in practice `0`: **full spanning circulation.** Every corridor in `self.adjacency` gets width.

The signature default is `1`, but `handlers.py:104` always passes `gclass.rem` explicitly, whose default is `0` (`pythongui\gui.py:133`) and which is only set to `1` by the GUI checkbox handler `radio_sel("redundant")` at `pythongui\gui.py:2080` ("The redundant corridors will be removed"), and reset by `radio_desel` at `pythongui\gui.py:2089` to `2090` ("The whole spanning circulation will be displayed"). So in practice the default behaviour is the full spanning circulation and `opti=1` is a user-facing GUI toggle only.

---

## Invariants And Preconditions

1. Input `self.graph` must be a properly triangulated planar graph. The BFS at `circulation.py:263` assumes every processed edge has exactly one remaining room-side common neighbour.
2. The entry edge `(v1-1, v2-1)` must be an **exterior** edge. Violating this is detected only indirectly, by the `remove_edge` failure at lines 268 to 271, and yields return code `0`.
3. Caller passes entry vertices **1-indexed**; line 250 subtracts 1.
4. Rooms are `0 .. m-1`, corridors are `m .. m+k-1`, contiguous, insertion-ordered. Assumed by line 285, line 394, line 410, line 952, and by `adjust_RFP_to_circulation` at line 475.
5. Corridor vertex `m` is the entry door and is excluded from both minimisation (line 394, line 421) and geometric widening (line 475).
6. `self.adjacency` values are always sorted room pairs (lines 291 to 293). `remove_corridor` relies on this for its `[v1,v2] in self.adjacency.values()` membership test at line 169.
7. `self.graph` is never mutated by `circulation_algorithm`; only the deep copy at line 243 is. `remove_corridor` also reads `self.graph` at line 167, so it must stay pristine.
8. Every room must appear in at least one corridor's coverage list, otherwise `min_tree_set_cover` cannot terminate. See Failure Modes.

---

## Failure Modes

1. **`remove_corridor` swap is broken (lines 161 to 162).**
   ```python
   v1 = v1 if v1 < v2 else v2
   v2 = v2 if v1 < v2 else v1
   ```
   Line 162 reads the **already reassigned** `v1`. With input `(5, 3)`: line 161 sets `v1 = 3`; line 162 then evaluates `3 < 3` as false and sets `v2 = v1 = 3`. Both variables end as `3` and the original `5` is lost, so the function silently operates on the non-edge `(3,3)` and falls through to "The rooms are not adjacent" at line 230. Any caller passing an unordered pair, for example `handlers.py:160` iterating `gclass.public_rooms(corridors)`, hits this whenever `x[0] > x[1]`.
2. **`np.random.randint()` with no arguments (line 216)** raises `TypeError`. This is the `c1 and c2` branch of `remove_corridor`, i.e. removing a corridor interior to two faces. Also `p = np.random.randint()%2` and then `v[p]`; the modulo suggests the author meant a bounded call.
3. **`find_exterior_edges` cannot execute.** `nx.to_numpy_matrix` (line 107) does not exist in the installed NetworkX 3.1, and bare `bdy` (line 114) is unbound given `import GPLAN.bdy` at line 8. Both are `AttributeError` / `NameError`. This takes `multiple_circulation` (line 90) down with it.
4. **`min_tree_set_cover` can spin forever (lines 362 to 379).** If any room in `X` is covered by no subset in `L`, then `max(intersections_count)` is 0, `j` is 0, `X` is filtered by `L[0]` which removes nothing, and the `while(len(X) > 0)` loop never exits. This is reachable: `X` is *all* rooms (line 355) but `L` is built only from corridors with id `> m` (line 394), so the rooms covered exclusively by the door corridor `m` are in the universe but absent from every subset unless the caller's forced list `b` happens to include a corridor covering them.
5. **Reverse-lookup collision (line 427).** `list(rooms_dict.values()).index(x)` returns the *first* corridor whose coverage list equals `x`. Two corridors with identical coverage lists collapse to the same id, so the answer can contain a duplicate and silently omit a needed corridor.
6. **Duplicates in the returned whitelist.** `remove_redundant_corridors` appends greedy picks (line 427) onto a list that already holds forced corridors (line 423) with no dedup. Harmless downstream because line 477 only does a membership test, but the printed "CORRIDORS" at line 429 is misleading.
7. **`plot` blocks (line 956).** `plt.show()` is a blocking call under an interactive Matplotlib backend, and it is invoked twice per circulation from `handlers.py:103` and `handlers.py:117`. Fine in the Tk GUI; a hang in any headless context.
8. **Return code `0` is not an exception.** `circulation_algorithm` returns `0` after having already mutated its local graph and leaves `self.circulation_graph` / `self.adjacency` at their `__init__` values (empty). `handlers.py:118` checks it, but any new caller that forgets to will read stale empty state.
9. **`if s[2]>0` (line 273)** uses `>` where the sentinel is `-1`. Correct only because corridor ids start at `m >= 1`. Fragile if numbering ever changes.

---

## Coupling (what breaks if you change this)

- **Vertex numbering.** `handlers.py` does not touch ids directly, but `adjust_RFP_to_circulation` (`circulation.py:466` to `487`) computes `start = min(adjacency.keys())`, `end = max(...)` and iterates `range(start+1, end+1)`. That loop assumes corridor ids are contiguous and that the smallest is the door. Change the numbering scheme in `circulation_algorithm` and the geometry half silently widens the wrong corridors.
- **`self.adjacency` shape.** `handlers.py:156` and `handlers.py:222` pass the whole dict to `gclass.public_rooms(corridors)`, and `handlers.py:160` / `226` feed the result back into `remove_corridor` as room pairs. `corridor_boundary_rooms` (line 318) destructures values as exactly `[a, b]`. Changing values to 3-tuples or unsorted pairs breaks `remove_corridor`'s membership test at line 169 and `corridor_boundary_rooms` at line 318.
- **`min_tree_set_cover` return type.** It returns room lists, not corridor ids, and `remove_redundant_corridors:427` performs the reverse lookup. Changing it to return ids requires deleting lines 426 to 427.
- **`plot` signature.** `handlers.py:103` calls `cir.plot(g, n)` with the pre-circulation graph, `handlers.py:117` with the post-circulation graph. The `m` argument is only the red-node cutoff (line 952).
- **`opti` / `rem_red_rooms`.** Sourced from the GUI (`pythongui\gui.py:2080`) and threaded through `handlers.py:104`. Removing the parameter breaks that call site.
- **`corridor_thickness`.** Set at line 58 from the constructor, consumed entirely by the geometry half, sourced from `ui.get_corridor_thickness()` at `handlers.py:104`.
- **`bdy` import.** Line 8 `import GPLAN.bdy` exists solely for `find_exterior_edges`. Since that function is broken and dead, the import is inert.

---

## Dead Or Duplicated Code

Duplicated files, stated plainly:

- `GPLAN\GPLAN\source\circulation\circulation.py` (872 lines) is an **older, smaller copy** of the root file. 644 of its lines are byte-identical to lines in the root file. Nothing imports it. Dead.
- `GPLAN\GPLAN\source\multiple_circ.py` (307 lines) is a third fork of the same class, split out for multi-circulation. Its `import circulation` at line 10 cannot resolve under the `GPLAN.` package. Nothing imports it. Dead and unimportable.
- `gplan_backend\GPLAN\GPLAN\handlers.py` mirrors `GPLAN\GPLAN\handlers.py` line for line at the anchors checked (79, 492, 527, 577, 634, 685, 715, 737, 1748), consistent with the recorded submodule relationship.

Dead within the in-scope region of the live file:

| Symbol | Line | Status |
| --- | --- | --- |
| `disp_rel_push` | 80 | Debug printer. Zero call sites repo-wide. Dead. |
| `multiple_circulation` | 90 | Called only from the commented-out `test_multiple_circ` (line 1270, invocation commented at 1294). Also depends on the broken `find_exterior_edges`. Dead. |
| `find_exterior_edges` | 100 | Called only by `multiple_circulation`. Cannot run (NetworkX 3.1 lacks `to_numpy_matrix`; bare `bdy` unbound). Dead. |
| `donot_include` | 125 | Zero call sites. Superseded by the `public_private` path at `handlers.py:157` to `160`. Dead. |
| `self.exterior_edges` | 62 | Written only by dead `find_exterior_edges`. Dead field. |
| `self.multiple_circ` | 61 | Written only by dead `multiple_circulation`. Dead field. |
| `self.corridor_tree` | 73, 304 | Computed every run, read only at line 438 which is inside a comment block (431 to 441). Dead field with live write cost. |
| `remove_redundant_corridors` Step 3 | 431 to 441 | Commented out. The connectivity guarantee it provided does not exist. |
| `min_tree_set_cover` random tie-break | 370 to 374 | Commented out alternative. |
| `remove_corridor` approaches 1 and 2 | 173 to 174 | Comment-only record of abandoned attempts. |
| `wheel_graph` | 894 | Test fixture generator, only call site is inside the commented-out test at 1268. Dead. |
| `complete_graph` | 921 | Only referenced inside comments at 1275 and 1282. Dead. |
| `is_subgraph` | 958 | Zero call sites. Also logically broken (varies wheel size but fixes subgraph size at `k`). Dead. |

---

## Open Questions

1. **Is circulation reachable at all from the deployed HTTP API?** `handle_circulation` and `call_circulation_new` dereference `gclass` unconditionally (`handlers.py:83, 504, 523, 526`), yet the API path enters via `handle_door_connectivity(ui, graph)` at `api.py:1309` with `gclass=None`, and `handlers.py:1747` gates on `ui.get_isCirculation() == 1` which `api.py:1232` can set. Either no deployed request ever sets `circulationEnabled=1`, or that request crashes. Not resolvable from static reading; needs a live request with `circulationEnabled=1`.
2. **Is the `remove_corridor` swap bug masked in practice?** Does `gclass.public_rooms(corridors)` at `handlers.py:157` always emit sorted pairs? If yes, the line 161 to 162 defect is latent rather than active. `public_rooms` lives in `pythongui\gui.py` and was not read for this dossier.
3. **Was `min_tree_set_cover` intended to run on the corridor tree?** The name says "tree set cover" and `self.corridor_tree` exists, but the implementation is a plain greedy set cover over room coverage lists (lines 355 to 379) and never touches `corridor_tree`. The commented Step 3 (431 to 441) is the only tree-aware logic and it is disabled, so the "minimum" circulation is not guaranteed connected.
4. **Should line 394 be `>= m` rather than `> m`?** The comment at 396 to 397 says the `>` is deliberate to skip the door corridor, but this is exactly the condition that can strand rooms outside every subset and hang the greedy loop (Failure Mode 4).
5. **Knowledge-graph cross-check.** `graphify-out\GRAPH_REPORT.md` lists a `custom_circ` community (line 610) and separate `multiple_circ` community (line 578) alongside the root circulation community (line 414), consistent with the three-fork picture, and does not flag the forks as dead. Where the graph is silent on liveness and the code is not, the code wins: only root `circulation.py` is imported.
