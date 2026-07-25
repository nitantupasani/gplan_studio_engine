# graph_crossings.py vs graph_crossings1.py

Verdict up front:

| File | Status |
| --- | --- |
| `GPLAN/GPLAN/source/graphoperations/graph_crossings1.py` | **LIVE.** Called on every InputGraph construction and on four independent pipelines. |
| `GPLAN/GPLAN/source/graphoperations/graph_crossings.py` | **DEAD as executable code.** It is still *imported* (module body runs) on the handlers import chain, but no function in it is ever called from anything reachable from `handlers.py` or `api.py`. Its only live importer has the call site commented out. Its one real caller lives in an unreachable subtree. |

---

## Purpose

Both modules answer one boolean question: given per-vertex `(x, y)` coordinates and an adjacency matrix, do any two drawn straight-line edges cross at a point that is not a shared vertex? Module docstring, `graph_crossings1.py:1-7`: "This file handles graphs that have a planar embedding but input has crossings (eg: K4)".

The engine needs this because a graph can be planar (abstractly) while the coordinates the user drew are a non-planar *embedding*. Downstream code (triangulation, separating-triangle removal, boundary/CIP enumeration) reads the coordinates as a real embedding and produces garbage if edges cross. So callers use `check_intersection` as a guard and, when it fires, either throw away the user coordinates and substitute `networkx.planar_layout`, or branch into a re-triangulation path.

The module never rejects the input and never deletes an edge. It only returns a flag; the *caller* re-embeds.

`graph_crossings.py` is the older, buggy revision. `graph_crossings1.py` is the fixed copy that everything live uses. They were never merged, and the old file was never deleted.

---

## Where It Sits In The Pipeline

### `graph_crossings1.py` = LIVE. Four independent reach chains.

**Chain A: every InputGraph construction (single dual, multiple dual, everything).**
- `GPLAN/GPLAN/api.py:8` `from GPLAN.source.inputgraph import InputGraph`
- `GPLAN/GPLAN/source/inputgraph.py:28` `from GPLAN.source.graphoperations import graph_crossings1 as gc`
- `GPLAN/GPLAN/source/inputgraph.py:115` `def __init__(self, nodecnt, edgecnt, edgeset, node_coordinates)`
- `GPLAN/GPLAN/source/inputgraph.py:161` `if (gc.check_intersection(x_coord, y_coord, self.matrix)):`
- On True, `GPLAN/GPLAN/source/inputgraph.py:162-164` replaces `self.coordinates` with `nx.planar_layout(graph)`.
- Constructed at `GPLAN/GPLAN/api.py:1003` and `GPLAN/GPLAN/api.py:1384`. This chain runs for *every* graph the engine sees, so it covers single dual and multiple dual as well.

**Chain B: door connectivity.**
- `GPLAN/GPLAN/api.py:1309`, `:1353`, `:1390` all call `handle_door_connectivity(...)`
- `GPLAN/GPLAN/handlers.py:1686` `def handle_door_connectivity(ui, graph, drawGUI = False, gclass = None)`
- `GPLAN/GPLAN/handlers.py:1710` / `:1732` `graph.door_connectivity(...)`
- `GPLAN/GPLAN/source/inputgraph.py:340` `def door_connectivity(self, show_graph = False, non_adj_list = None)`
- `GPLAN/GPLAN/source/inputgraph.py:471` `is_not_planar_embedding = check_intersection(x_coords,y_coords, self.matrix)` (import at `GPLAN/GPLAN/source/inputgraph.py:44`)
- Reaction here is **different** from Chain A: `GPLAN/GPLAN/source/inputgraph.py:474` branches into `trng.triangulate(...)` (`:481-483`) and adds the resulting edges (`:485-488`). The False branch at `:501` skips straight to `st.handle_STs_Door_connectivity`.

**Chain C: separating-triangle removal inside door connectivity.**
- `GPLAN/GPLAN/source/inputgraph.py:41` `from GPLAN.source.irregular import septri as st`, invoked at `GPLAN/GPLAN/source/inputgraph.py:440` / `:492`
- `GPLAN/GPLAN/source/irregular/septri.py:20` `from GPLAN.source.graphoperations.graph_crossings1 import check_intersection as check_intersection`
- Five call sites: `septri.py:515`, `:648` (inside `handle_non_trivial_ST_Door_connectivity`, `septri.py:359`) and `septri.py:867`, `:1005`, `:1097` (inside `handle_non_trivial_non_adj_ST_Door_connectivity`, `septri.py:700`)
- Reaction at `GPLAN/GPLAN/source/irregular/septri.py:516-517`: `if(is_not_planar_embedding): positions = nx.planar_layout(graph)`.

**Chain D: multi-PTPG boundary enumeration.**
- `GPLAN/GPLAN/api.py:1791` `from GPLAN.source import multi_ptpg_pipeline`, called at `GPLAN/GPLAN/api.py:1800`
- `GPLAN/GPLAN/source/multi_ptpg_pipeline.py:33` `from GPLAN.source import ptpg_floorplanner as pfp`
- `GPLAN/GPLAN/source/ptpg_floorplanner.py:58` `from GPLAN.source.graphoperations import graph_crossings1 as gc`
- `GPLAN/GPLAN/source/ptpg_floorplanner.py:181` `def get_boundaries(...)`, called at `GPLAN/GPLAN/source/ptpg_floorplanner.py:847`
- `GPLAN/GPLAN/source/ptpg_floorplanner.py:206` `if gc.check_intersection([c[0] for c in coords], [c[1] for c in coords], mat):` then `:207` swaps in `nx.planar_layout`. Wrapped in `try/except Exception` (`:205`, `:208-209`) which falls back to `planar_layout` unconditionally on any error.

**Also imported but never called on that path:** `GPLAN/GPLAN/handlers.py:6` `from GPLAN.source.graphoperations.graph_crossings1 import check_intersection as check_intersection`. The only reference inside `handlers.py` is `handlers.py:1698`, which is commented out. That import is vestigial; the live uses are in `inputgraph.py` and `septri.py`.

### `graph_crossings.py` = DEAD.

Two importers exist:

**Importer 1: `GPLAN/GPLAN/bdy.py:9`** `from GPLAN.source.graphoperations import graph_crossings as gc`.
This file *is* reachable: `GPLAN/GPLAN/handlers.py:31` `import GPLAN.circulation as cir` -> `GPLAN/GPLAN/circulation.py:8` `import GPLAN.bdy` -> `GPLAN/GPLAN/bdy.py:9`. So the module body of `graph_crossings.py` executes on every handlers import.
But the *only* reference to `gc` in the whole of `bdy.py` is `GPLAN/GPLAN/bdy.py:84`, which is commented out:
```python
        # if(gc.check_intersection(x_coord, y_coord, self.matrix)):
```
along with the whole surrounding block (`bdy.py:81-89`). No function in `graph_crossings.py` is ever invoked through this path.

**Importer 2: `GPLAN/GPLAN/source/trial/bdy.py:9`** `from ..graphoperations import graph_crossings as gc`.
This one *does* call it, live and uncommented, at `GPLAN/GPLAN/source/trial/bdy.py:84`:
```python
        if(gc.check_intersection(x_coord, y_coord, self.matrix)):
```
But `source/trial/bdy.py` is unreachable. Its only importers are `GPLAN/custom_circ_entry.py:7` (a standalone top-level script, imported by no `.py` in the tree) and `GPLAN/GPLAN/source/multiple_circ.py:9`, and `multiple_circ.py` is itself imported by nothing (its own `import circulation` at `multiple_circ.py:10` is a bare top-level name that does not resolve inside the `GPLAN.` package). Neither is reachable from `handlers.py` or `api.py`.

**Conclusion for `graph_crossings.py`:** its code never runs beyond module-level definitions. Do not attribute a purpose to it. It is a superseded copy.

---

## Entry Points (file:line)

The public surface is identical in both files (same names, same signatures, same return shapes):

| Symbol | `graph_crossings.py` | `graph_crossings1.py` |
| --- | --- | --- |
| `class Point` | `:12` | `:11` |
| `display(p, q) -> str` | `:17` | `:16` |
| `eq(p, q) -> bool` | `:21` | `:20` |
| `sort_by_x(points) -> list` | `:28` | `:27` |
| `orientation(p1, p2, p3) -> int` | `:43` | `:42` |
| `onSegment(p1, p2, p3) -> bool` | `:78` | `:77` |
| `doIntersect_endpts(p1, q1, p2, q2) -> bool` | `:95` | `:94` |
| `get_points_edges(x_list, y_list, adj)` | `:155` | `:154` |
| **`check_intersection(x_coord, y_coord, A) -> bool`** | `:192` | `:191` |
| `main()` (self-test, `__main__` only) | `:254` | `:283` |

`check_intersection` is the only symbol any caller imports. `sort_by_x` and `display` are dead in both files (`sort_by_x` is never called; `check_intersection` inlines the same `sorted(...)` at `graph_crossings1.py:218`).

External call sites, all against `graph_crossings1`:
- `GPLAN/GPLAN/source/inputgraph.py:161` -> `gc.check_intersection`
- `GPLAN/GPLAN/source/inputgraph.py:471` -> `check_intersection`
- `GPLAN/GPLAN/source/irregular/septri.py:515`, `:648`, `:867`, `:1005`, `:1097`
- `GPLAN/GPLAN/source/ptpg_floorplanner.py:206`

---

## Data Structures

- **`Point`** (`graph_crossings1.py:11-14`): two floats, `x` and `y`. **No `__eq__`, no `__hash__`.** Equality and `in` therefore fall back to *identity*. This is load-bearing (see Invariants).
- **`points: list[Point]`** (`graph_crossings1.py:170-171`): built by index, so `points[i]` is vertex `i`. Index is the vertex id.
- **`edges: dict[int, list[Point]]`** (`graph_crossings1.py:173-186`): key is a synthetic sequential edge id `key_var`; value is a two-element list `[left_point, right_point]` where "left" means smaller `x` (`graph_crossings1.py:182-185`). The two entries are *the same objects* from `points`, not copies.
- **`left_pts` / `right_pts: list[Point]`** (`graph_crossings1.py:207-208`): positional projections of `edges.values()`, so index into these lists == edge id.
- **`traversed: list[int]`** (`graph_crossings1.py:215`): the active set. Edge ids whose left endpoint has been passed and whose right endpoint has not. A plain Python list, not a balanced tree, despite the docstring.
- **`check_count: int`** (`graph_crossings1.py:224`, `:260`): a leftover from the old windowing logic. In `graph_crossings1.py` it is assigned but **never read** (its only former reader, the `range(...)` at `graph_crossings.py:234`, is the line that was commented out at `graph_crossings1.py:245`).

Return shape: `bool` `True` on a crossing, `bool` `False` on clean termination, or **implicit `None`** if the loop falls off the end. All three are consumed as truthy/falsy by every caller, so `None` reads as "no crossing".

---

## Algorithm Walkthrough

### What counts as a crossing

Two straight segments, drawn between the two endpoints' `(x, y)` coordinates, that intersect anywhere **except** at a shared endpoint. The shared-endpoint exclusion is explicit and comes first (`graph_crossings1.py:125-126`):

```python
    if((eq(p1,p2)) or (eq(p1,q2)) or (eq(q1,p2)) or (eq(q1,q2))):
        return False
```

Note this uses `eq` (coordinate equality, `graph_crossings1.py:20-25`), not identity, so two *distinct* vertices drawn at the same coordinate also suppress a crossing report between their incident edges.

### The geometric predicate

Standard CLRS-style four-orientation test, `doIntersect_endpts` (`graph_crossings1.py:94-152`).

The primitive is a **cross-product sign test**, not a parametric solve. `orientation` (`graph_crossings1.py:42-75`), decisive line `graph_crossings1.py:63`:

```python
    val = ((p2.y - p1.y) * (p3.x - p2.x)) - ((p2.x - p1.x) * (p3.y - p2.y))
```
returning `1` clockwise (`:67`), `2` counter-clockwise (`:71`), `0` collinear (`:75`). No epsilon, exact zero comparison.

General case (`graph_crossings1.py:131-132`): the four orientations `o1..o4` (`:119-122`) satisfy `o1 != o2 and o3 != o4`, i.e. each segment straddles the other's supporting line.

Four collinear special cases (`graph_crossings1.py:136-149`), each of the form `if ((oN == 0) and onSegment(...))`. `onSegment` (`graph_crossings1.py:77-92`) is a pure axis-aligned bounding-box containment test (`:89-90`); it does **not** re-verify collinearity, it relies entirely on the `oN == 0` guard in the caller.

No intersection *point* is ever computed. The routine is a pure yes/no.

### How crossings are found

The docstring (`graph_crossings1.py:192-196`) claims a sweep line with "a self-balancing binary search tree". **There is no tree in the code and no y-ordering.** What is actually implemented:

1. `get_points_edges` (`graph_crossings1.py:206`) builds `points` and `edges` by scanning the full upper triangle of the adjacency matrix (`graph_crossings1.py:178-186`).
2. Sort the *vertices* by x (`graph_crossings1.py:218`). Note: the event queue is over vertices, not over the 2E segment endpoints; that is equivalent here only because every segment endpoint is a vertex.
3. For each vertex `p` in x order (`graph_crossings1.py:228`):
   - If `p` is the left endpoint of one or more edges (`:231`), collect those edge ids (`:233`), append them to `traversed` (`:238`), and if `traversed` already held other edges (`:242`) test **every newly activated edge against every previously active edge** (`graph_crossings1.py:244-254`). Return `True` immediately on the first hit (`:252`). Edges activated together are skipped against each other because they share `p`.
   - Then deactivate: while `p` is the right endpoint of some still-active edge (`:264`), collect all edge ids whose right endpoint is `p` (`:266`) and remove each from `traversed` (`:267-268`).
   - Terminate `False` when `traversed` is empty at the last vertex (`:270-271` and again `:280-281`).

Because of the `range(0, ...)` at `graph_crossings1.py:246`, the inner comparison is **exhaustive against the whole active set**. That makes this a brute-force active-set sweep, not Bentley-Ottmann: it never orders segments by y and never processes swap events. It is correct (it cannot miss a pair, since any crossing pair is simultaneously active at the moment the later one activates) but it gives up the log factor.

### Complexity as implemented

Let `V` = vertex count, `E` = edge count.

- `get_points_edges`: `O(V^2)` unconditionally, it walks the whole matrix (`graph_crossings1.py:178-179`).
- Sort: `O(V log V)` (`graph_crossings1.py:218`).
- Main loop, per vertex `p`: `p in left_pts` is `O(E)` (`:231`), the enumerate comprehension is `O(E)` (`:233`), the deactivation guard `right_pts.index(p)` plus the `indices` comprehension are `O(E)` each (`:264`, `:266`).
- Predicate calls: for each vertex, `deg(p) x |traversed|` calls, bounded by `deg(p) x E`. Summed over all vertices, `sum(deg(p)) = 2E`, so **`O(E^2)` calls to `doIntersect_endpts`**, each `O(1)`.

**Total: `O(V^2 + V*E + E^2)`, i.e. `O(E^2)` for a dense-ish graph and `O(V^2)` for the near-triangulated planar graphs GPLAN actually feeds it** (where `E = O(V)`). Not the `O((V+E) log V)` the docstring implies.

The old `graph_crossings.py` had the same asymptotic bound in the worst case but a much smaller constant because of its (incorrect) window.

### What it does about crossings

Nothing, inside this module. It returns a flag. Reactions are entirely caller-side and are **not uniform**:

| Caller | Reaction on `True` |
| --- | --- |
| `inputgraph.py:161` (`InputGraph.__init__`) | Discards the drawn coordinates entirely: `self.coordinates = [np.array(x) for x in new_node_coordinates]` from `nx.planar_layout` (`inputgraph.py:162-164`). Re-embed. |
| `inputgraph.py:471` (`door_connectivity`) | Does **not** re-embed. Branches into `trng.triangulate(...)` and adds the returned edges to the matrix (`inputgraph.py:474`, `:481-488`). |
| `septri.py:515`, `:648`, `:867`, `:1005`, `:1097` | `positions = nx.planar_layout(graph)` (`septri.py:516-517`). Re-embed. |
| `ptpg_floorplanner.py:206` | `coords = list(nx.planar_layout(...).values())` (`ptpg_floorplanner.py:207`). Re-embed. |

No caller rejects the input, raises, or removes an edge on a crossing.

---

## Invariants And Preconditions

1. **Identity, not value, drives the active set.** `Point` has no `__eq__` (`graph_crossings1.py:11-14`), so `p in left_pts` (`:231`), the `x == p` comprehensions (`:233`, `:266`) and `right_pts.index(p)` (`:264`) are all identity comparisons. This works only because `edges` stores the *same* `Point` objects that `points` holds (`graph_crossings1.py:183-185`) and `sorted_by_x` sorts that same list (`:218`). Any refactor that copies points, or that adds `__eq__` to `Point`, silently changes the semantics of the whole loop.
2. `len(x_coord) == len(y_coord) == A.shape[0]`. `get_points_edges` mixes `len(x_list)` and `len(y_list)` in its bounds (`graph_crossings1.py:178-179`) and indexes `adj[i][j]` with no bounds check (`:181`).
3. `A` must be symmetric with `1` for present edges. Only the strict upper triangle is read (`graph_crossings1.py:179`), and the test is `== 1`, not truthiness (`:181`), so a weighted or boolean-typed matrix with non-1 values is read as "no edge".
4. Every edge's left endpoint is visited no later than its right endpoint. Guaranteed by the left/right assignment at `graph_crossings1.py:182-185` (left = smaller x) combined with the stable `sorted(..., key=p.x)` at `:218` (ties break on original vertex index, which matches the `points[i].x <= points[j].x` tie rule).
5. Every edge id ends up in `traversed` exactly once, so the `traversed.remove(i)` at `graph_crossings1.py:268` has something to remove.
6. Exact arithmetic. `orientation` at `graph_crossings1.py:63-75` compares the cross product against exactly `0`. Coordinates arriving as floats (e.g. the normalized `(p[0]-min)/rx` at `ptpg_floorplanner.py:204`) can make a truly-collinear configuration test as non-collinear, or vice versa.
7. The graph must have at least one vertex; `sorted_by_x[0]` at `graph_crossings1.py:221` indexes unconditionally.

---

## Failure Modes

1. **`check_intersection` can return `None`.** If the last vertex is reached with `traversed` non-empty, neither `graph_crossings1.py:271` nor `:281` fires and the function falls off the end. Every caller uses the result in a boolean context, so `None` is silently read as "planar, no crossing". Empirically reproduced against the file's own test data (see Dead Or Duplicated Code below): `graph_crossings.py` returns `None` for its Example 2 and Example 8; `graph_crossings1.py` returns `False` and `True` respectively.
2. **`traversed.remove(i)` raises `ValueError`** (`graph_crossings1.py:268`) if invariant 5 is ever violated. `ptpg_floorplanner.py:205-209` is the only caller that guards with `try/except Exception`; `inputgraph.py:161`, `inputgraph.py:471` and all five `septri.py` sites are unguarded and would propagate.
3. **`while` at `graph_crossings1.py:264` is a loop with no counter.** It relies on the body removing every id whose right endpoint is `p`, so the guard must go false on the second evaluation. It terminates for well-formed input, but it is structurally an unbounded loop where `graph_crossings.py:249` was a plain `if`.
4. **Coincident distinct vertices suppress detection.** `eq` at `graph_crossings1.py:125` is coordinate-based, so two different rooms drawn at the same point make all their incident edge pairs report "no crossing".
5. **Degenerate zero-length edges** (both endpoints identical) make `orientation` return `0` for everything and are filtered out by the `eq` guard at `:125` anyway, so they are never reported.
6. `check_count` (`graph_crossings1.py:224`, `:260`) is dead state: written twice, read nowhere. Anyone reading the file will assume it participates in the windowing and it does not.
7. **Docstring lies about the data structure.** `graph_crossings1.py:192-196` describes "a self-balancing binary search tree"; the implementation is a Python `list` (`:215`) with `O(E)` membership tests.

---

## Coupling (what breaks if you change this)

- **`check_intersection` is on the hot path of every single request.** `InputGraph.__init__` (`inputgraph.py:115`) calls it at `inputgraph.py:161` for every graph, and `api.py:1003` / `api.py:1384` construct `InputGraph`. Making it stricter (e.g. reporting shared-endpoint touches, or reporting the coincident-vertex case) would flip more inputs onto the `nx.planar_layout` re-embed branch at `inputgraph.py:162-164`, discarding user-drawn coordinates and changing which boundary/CIP candidates get enumerated downstream. That changes generated floorplans, not just a diagnostic.
- **`door_connectivity` uses the flag for a different decision.** At `inputgraph.py:474` a `True` triggers `trng.triangulate` and *adds edges to the matrix* (`inputgraph.py:485-488`). A false positive here mutates the graph.
- **Five `septri.py` sites** (`:515`, `:648`, `:867`, `:1005`, `:1097`) call it inside separating-triangle search loops. Making it slower directly multiplies into those loops.
- **Return-type change is breaking.** If you "fix" the implicit `None` by returning `True` on fall-through, previously-silent inputs start re-embedding. If you make it raise instead, four of the six call sites are unguarded (`ptpg_floorplanner.py:205` is the only one with a `try`).
- **Adding `__eq__`/`__hash__` to `Point`** silently rewrites the semantics of `graph_crossings1.py:231`, `:233`, `:264` and `:266` from identity to value. Do not do it without rewriting the active-set logic.
- **Deleting `graph_crossings.py`** requires touching `GPLAN/GPLAN/bdy.py:9` and `GPLAN/GPLAN/source/trial/bdy.py:9`. `bdy.py:9` is safe to delete outright (its only user, `bdy.py:84`, is commented out). `source/trial/bdy.py:84` is a real call, but that file is unreachable, so repointing it at `graph_crossings1` is a no-op for behaviour and is the safe move.

---

## Dead Or Duplicated Code

### The duplication, measured

`diff -u graph_crossings.py graph_crossings1.py` produces four hunks. Two are the `main()` self-test block (Examples 1-7 commented out in the newer file, `graph_crossings1.py:341-412`) and are behaviourally irrelevant. The three that matter:

**1. The decisive fix, `graph_crossings.py:234` -> `graph_crossings1.py:245-246`.**

Old (`graph_crossings.py:234`):
```python
                    for j in range(len(traversed) - len(indices_p) - check_count, len(traversed) - len(indices_p)):
```
New (`graph_crossings1.py:245-246`):
```python
                    # for j in range(len(traversed) - len(indices_p) - check_count, len(traversed) - len(indices_p)):
                    for j in range(0, len(traversed) - len(indices_p)):
```
The old version compared each newly activated edge only against the `check_count` **most recently** activated edges, where `check_count` was the degree of the *previous* vertex (`graph_crossings.py:246`). Any crossing between a new edge and an older active edge outside that window was missed. The new version compares against the entire active set. This is the whole reason `graph_crossings1.py` exists.

**2. Multi-edge deactivation, `graph_crossings.py:249-252` -> `graph_crossings1.py:263-271`.**

Old:
```python
        if((p in right_pts) and (right_pts.index(p) in traversed)):
            traversed.remove(right_pts.index(p))
```
`list.index` returns only the *first* match, so a vertex that is the right endpoint of k edges deactivated only one of them, leaving k-1 stale ids in `traversed` forever. New:
```python
        while ((p in right_pts) and (right_pts.index(p) in traversed)):
            indices = [i for i,x in enumerate(right_pts) if x == p]
            for i in indices:
                traversed.remove(i)
```

**3. Terminal fall-through, added at `graph_crossings1.py:280-281`:**
```python
        if((len(traversed) == 0) and (p == sorted_by_x[-1])):
                return False
```
The old file only had that check nested *inside* the removal branch (`graph_crossings.py:251-252`), so a run that emptied `traversed` without entering that branch fell off the end and returned `None`.

**4. Stray import removed:** `graph_crossings.py:10` `from turtle import right` is gone in `graph_crossings1.py`. `turtle` is unused (the name `right` is never referenced) and pulls in `tkinter`. That import still executes today via `handlers.py:31 -> circulation.py:8 -> bdy.py:9 -> graph_crossings.py:10`. It happens to succeed in this environment (verified: `python -c "import turtle"` prints ok), but it is an unnecessary GUI-toolkit dependency on the server import path.

No function was renamed, no signature changed, and no return shape changed between the two files. `check_intersection(x_coord, y_coord, A)` is identical in name, arity and declared type in both (`graph_crossings.py:192` / `graph_crossings1.py:191`).

### Empirical confirmation of the bug

Loading both modules side by side and running the test matrices embedded in their own `main()` blocks:

```
Ex1: old=True   new=True
Ex2: old=None   new=False
Ex4: old=True   new=True
Ex6: old=True   new=True
Ex7: old=True   new=True
Ex8: old=None   new=True
```

Example 8 (`graph_crossings1.py:414-424`, annotated in the newer file as "Expected output: Non-planar") is the smoking gun: the old file returns `None`, which every caller reads as "no crossing". The old implementation is not merely slower, it is wrong.

### Other dead code found

- `GPLAN/GPLAN/source/graphoperations/graph_crossings.py` in its entirety: no reachable caller (see Where It Sits In The Pipeline).
- `sort_by_x` (`graph_crossings1.py:27-40`) and `display` (`graph_crossings1.py:16-18`): never called outside the `__main__` self-test. `check_intersection` inlines the same sort at `:218`.
- `check_count` (`graph_crossings1.py:224`, `:260`): written, never read.
- `prev_index = 0` (`graph_crossings1.py:263`): assigned, never read; its only user is commented out at `:272`.
- `GPLAN/GPLAN/handlers.py:6`: imports `check_intersection`, whose sole in-file reference (`handlers.py:1698`) is commented out.
- `GPLAN/GPLAN/bdy.py:81-89`: the entire crossing-check block in `Boundary.__init__` is commented out, including the `node_coordinates` handling at `:79`.
- **Separately broken, found while tracing:** `GPLAN/GPLAN/circulation.py:114` calls `bdy.Boundary(len(graph1), edgecnt, edgeset, coord)` with four arguments, but (a) the module imports `import GPLAN.bdy` at `circulation.py:8`, which binds the name `GPLAN`, not `bdy`, so this line raises `NameError`, and (b) `GPLAN/GPLAN/bdy.py:55` declares `def __init__(self, nodecnt, edgecnt, edgeset)`, three parameters. `circulation.find_exterior_edges` cannot run as written. This is not part of the crossings duplication but it is the same rot: `GPLAN/GPLAN/bdy.py` looks like a stale copy of `GPLAN/GPLAN/source/trial/bdy.py`, whose `Boundary` does take the coordinates argument and does call `gc.check_intersection` at `source/trial/bdy.py:84`.

### Recommendation

Delete `GPLAN/GPLAN/source/graphoperations/graph_crossings.py`. Before deleting: drop the unused import at `GPLAN/GPLAN/bdy.py:9` (its only consumer at `bdy.py:84` is already commented out), and repoint `GPLAN/GPLAN/source/trial/bdy.py:9` at `graph_crossings1` (that file is unreachable, so this cannot change behaviour, and leaving it pointed at the buggy copy is a trap for whoever revives it). Optionally rename `graph_crossings1.py` back to `graph_crossings.py` in the same commit and update the six importers: `handlers.py:6`, `inputgraph.py:28`, `inputgraph.py:44`, `septri.py:20`, `ptpg_floorplanner.py:58`, plus the two `bdy.py` lines.

---

## Open Questions

1. **The knowledge graph disagrees with the code on reachability.** `graphify explain "graph_crossings"` reports exactly one inbound edge, `trial/bdy.py [imports_from] GPLAN/GPLAN/source/trial/bdy.py:L9`. It does **not** list `GPLAN/GPLAN/bdy.py:9`, which is the importer that actually executes on the handlers import chain. Code wins: `GPLAN/GPLAN/bdy.py:9` is real and I read it. The graph's importer edges for this node are incomplete; do not use it alone to justify a delete.
2. Why does `door_connectivity` react to a crossing by re-triangulating (`inputgraph.py:474`, `:481-488`) rather than re-embedding, when `InputGraph.__init__` (`inputgraph.py:161-164`) already re-embedded the same object minutes earlier in the same request? If `__init__` guaranteed a crossing-free embedding, the check at `inputgraph.py:471` should be unreachable-True. Either the coordinates are mutated in between (they are, at `inputgraph.py:442-443`) and the second check is the meaningful one, or one of the two is redundant. Not resolved from the code alone.
3. Is `check_intersection` returning `None` (failure mode 1) ever hit in production, and if so on which pipeline? All six call sites swallow it as falsy, so it would present as "crossings silently not detected", not as an error. No logging exists at any call site.
4. Is `GPLAN/GPLAN/bdy.py` supposed to be a live module at all? It is imported only to satisfy `circulation.py:8`, and the one function that would use it (`circulation.find_exterior_edges`, `circulation.py:100-122`) cannot run because of the `NameError` and arity mismatch noted above. Whether `bdy.py` should be deleted alongside `graph_crossings.py`, or repaired to match `source/trial/bdy.py`, is a call I cannot make from the code.
5. The `try/except Exception` at `ptpg_floorplanner.py:205-209` silently falls back to `nx.planar_layout` on *any* exception from `check_intersection`. Whether that mask is intentional (defensive) or is hiding the `ValueError` from failure mode 2 in the multi-PTPG pipeline is unknown; nothing logs the swallowed exception.
