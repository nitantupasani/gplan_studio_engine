# Boundary Labeling: `boundary/cip.py`, `boundary/news.py`, `trial/bdy.py`

Unit id: `graph/boundary-news-cip`
Repo root for all paths: `C:\Users\nitant\Documents\GPLAN_Revamp`
All line anchors below were read in this session.

---

## Purpose

This unit performs the **4-completion** of an already-triangulated, biconnected,
separating-triangle-free planar graph (a PTPG). It answers two questions:

1. Where must the four corners of the bounding rectangle fall on the outer cycle?
   Corner-implying paths (CIPs) are computed from the graph's *shortcuts*
   (`GPLAN/GPLAN/source/boundary/cip.py:11`).
2. Given a choice of four corners, split the outer cycle into four contiguous
   arcs and attach four new exterior vertices N, E, S, W, one per arc
   (`GPLAN/GPLAN/source/boundary/news.py:249`).

The output of this unit is the adjacency matrix that the REL machinery
(contraction / expansion / T1-T2 dual) actually consumes. `news.add_news` is the
single place where the compass semantics of the whole engine are fixed: the
NEWS vertices are appended at indices `nodecnt .. nodecnt+3` in the order
**N, E, S, W** (`news.py:265-268`), and every downstream module hard-codes
`nodecnt-4 = N`, `nodecnt-3 = E`, `nodecnt-2 = S`, `nodecnt-1 = W`.

`GPLAN/GPLAN/source/trial/bdy.py` is **not** the multi-boundary enumerator. It is
a stripped-down copy of `InputGraph`'s boundary-identification prologue used only
by circulation code that the HTTP API never reaches. See Dead Or Duplicated Code.

---

## Where It Sits In The Pipeline

Production entry is `GPLAN/GPLAN/api.py` -> `GPLAN/GPLAN/handlers.py` ->
`InputGraph.irreg_multiple_dual` / `irreg_single_dual` in
`GPLAN/GPLAN/source/inputgraph.py`.

```
biconnectivity augmentation      inputgraph.py:218-225
triangulation                    inputgraph.py:228-234
edge->vertex transformation      inputgraph.py:240-252
separating-triangle elimination  inputgraph.py:255-265
--- THIS UNIT ---
outer boundary identification    opr.get_bdy         operations.py:85
                                 opr.ordered_bdy     operations.py:238
shortcut detection               sr.get_shortcut     shortcutresolver.py:14
CIP computation                  cip.find_cip        cip.py:11
corner choice + 4 arcs           news.find_bdy/bdy_path   news.py:21 / news.py:35
                                 (multiple: news.multiple_corners / all_boundaries /
                                  find_multiple_boundary   news.py:95 / 121 / 67)
cardinal filter (optional)       filter_boundaries_by_cardinal  inputgraph.py:1365
4-completion (+4 vertices)       news.add_news       news.py:249
--- END UNIT ---
contraction                      cntr.goodnodes      contraction.py:47  (skips last 4)
expansion base case              exp.basecase        expansion.py:39-49 (uses nodecnt-4..-1)
T1/T2 dual + coordinates         dual.py:35,82,127,153,196,223 ; rdg.py:69-75
```

Single-dual path: `inputgraph.py:267-301` (boundary identification through
`news.add_news`), identical block repeated at `inputgraph.py:727-761`.
Multiple-dual path: `generate_multiple_bdy` (`inputgraph.py:1453`) produces a
list of candidate boundaries, then `generate_multiple_rel` (`inputgraph.py:1412`)
calls `news.add_news` once per candidate at `inputgraph.py:1424`.

---

## Entry Points (file:line)

| Anchor | Symbol | Role |
|---|---|---|
| `GPLAN/GPLAN/source/boundary/cip.py:11` | `find_cip(bdy_ordered, shortcuts)` | the whole of cip.py (53 lines / ~1.7 KB); returns list of CIPs |
| `GPLAN/GPLAN/source/boundary/news.py:21` | `find_bdy(cip)` | strips the two shortcut endpoints off each CIP |
| `GPLAN/GPLAN/source/boundary/news.py:35` | `bdy_path(paths, bdy)` | **single** boundary: random corner per CIP, 4 arcs |
| `GPLAN/GPLAN/source/boundary/news.py:67` | `find_multiple_boundary(corner_points, boundary)` | corner tuples -> 4 arcs each |
| `GPLAN/GPLAN/source/boundary/news.py:95` | `multiple_corners(paths)` | odometer over the cartesian product of CIP interiors |
| `GPLAN/GPLAN/source/boundary/news.py:121` | `all_boundaries(paths, boundary)` | pads corner tuples of size 0/1/2/3 up to 4 |
| `GPLAN/GPLAN/source/boundary/news.py:212` | `news_edges(matrix, cip, source_node)` | joins one arc to one exterior vertex |
| `GPLAN/GPLAN/source/boundary/news.py:230` | `connect_news(matrix, nodecnt)` | the N-E-S-W-N outer 4-cycle |
| `GPLAN/GPLAN/source/boundary/news.py:249` | `add_news(bdy, matrix, nodecnt, edgecnt)` | **the 4-completion**; grows matrix by 4 |
| `GPLAN/GPLAN/source/trial/bdy.py:23` | `class Boundary` | copy of the InputGraph prologue (not in the API path) |
| `GPLAN/GPLAN/source/trial/bdy.py:91` | `Boundary.identify_bdy()` | returns the 4 arcs, never 4-completes |
| `GPLAN/GPLAN/source/trial/bdy.py:179` | `main()` | hexagon demo, prints exterior edges |

Consumption sites:
- `GPLAN/GPLAN/source/inputgraph.py:279,281,295,296` (irreg_single_dual)
- `GPLAN/GPLAN/source/inputgraph.py:739,741,755,756,759` (second single path)
- `GPLAN/GPLAN/source/inputgraph.py:1478-1482` (generate_multiple_bdy)
- `GPLAN/GPLAN/source/inputgraph.py:1424` (generate_multiple_rel -> add_news)
- `GPLAN/GPLAN/source/ptpg_floorplanner.py:240-247` (independent CIP enumerator)
- `GPLAN/GPLAN/source/lettershape/*/`, `GPLAN/GPLAN/source/staircaseshape/staircaseshape.py:120`
  reuse `cip.find_cip` and `news.find_bdy` for letter-shaped plots.

---

## Data Structures

- **`bdy_ordered` / `boundary`**: `list[int]`, the outer cycle in circular order,
  each boundary node exactly once, no repeat of the first node at the end
  (`operations.py:238-258`). Orientation (CW vs CCW) is whichever direction
  `ordered_bdy` happens to walk from `bdy_nodes[0]`.
- **`shortcuts`**: `list[list[int]]` of length-2 **mutable lists**
  (`shortcutresolver.py:31`). A shortcut is an edge between two boundary
  vertices that is *not* a boundary edge, i.e. a chord of the outer cycle
  (`shortcutresolver.py:28-30`).
- **`cip`** (return of `find_cip`): `list[list[int]]`. Each element is a
  contiguous boundary arc **including both of its shortcut endpoints**, length
  >= 3. This is *not* a partition of the boundary: CIPs overlap at shortcut
  endpoints, can be zero in number, and need not cover the cycle.
- **`paths`** (return of `find_bdy`, `news.py:30-33`): the same list with the two
  endpoints removed (`path[1:len(path)-1]`), so each entry is the CIP *interior*.
  This is the set the corner must be chosen from.
- **`bdys`** (return of `bdy_path` / one element of `find_multiple_boundary`):
  exactly 4 lists, `[N_arc, E_arc, S_arc, W_arc]`. Consecutive arcs **share their
  boundary corner node**: `bdys[i][-1] == bdys[i+1][0]`, and `bdys[3][-1] == bdys[0][0]`
  (see the slicing at `news.py:60-63`, each slice ends at `index+1`).
- **`cip_list`** (return of `generate_multiple_bdy`, `inputgraph.py:1483`): a list
  of such 4-tuples, one per candidate boundary labeling.
- **`cardinal_constraints`**: `list[(node, dir_idx)]`, `dir_idx` 0..3 = N,E,S,W
  (`inputgraph.py:151-156`, `api.py:123`).

---

## Algorithm Walkthrough

### 1. Identifying the outer boundary cycle

Not coordinate-based, not planar-face-walking. It is a **triangle-incidence
count**: `opr.get_bdy` (`operations.py:85-115`) counts, for every ordered vertex
pair, how many triangular cycles contain both (`operations.py:99-106`), and keeps
the directed edges lying in **exactly one** triangle (`operations.py:107`). In a
triangulated planar graph every interior edge is in two triangles and every outer
edge in one, so this yields the outer cycle. `bdy_nodes` is the de-duplicated
vertex list in edge-discovery order (`operations.py:108-114`), which is *not*
circular order. `opr.ordered_bdy` (`operations.py:238-258`) then walks
`bdy_edges` greedily from `bdy_nodes[0]` to produce the circular order. Note both
`(u,v)` and `(v,u)` survive the filter, so the walk direction is whatever the
first unvisited neighbour in `bdy_nodes` order happens to be; the code never
normalizes orientation. This is exactly the freedom that
`filter_boundaries_by_cardinal` compensates for with its reflection
(`inputgraph.py:1392-1400`).

`self.bdy_nodes` / `self.bdy_edges` are computed once at `inputgraph.py:270-271`
(and `:730-731`) and reused.

### 2. `find_cip` in full (cip.py:11-53, the entire file)

```
21-24  shortcut_endpts = flat list of every shortcut's two vertices
25     cip = []
26     for shortcut in shortcuts:
27-28    pos_1, pos_2 = positions of the two endpoints in bdy_ordered
29-31    if pos_1 > pos_2: swap positions AND swap shortcut[0]/shortcut[1] IN PLACE
32       path_1 = bdy_ordered[pos_1+1 : pos_2]                 # arc strictly between
33-34    path_2 = bdy_ordered[pos_2+1 :] + bdy_ordered[0 : pos_1]  # the complementary arc
35-44    path_N_cip = 1 unless the arc's interior contains ANY shortcut endpoint
45-48    if path_1 qualifies: re-attach shortcut[0] at front, shortcut[1] at end, append
49-52    if path_2 qualifies: re-attach shortcut[1] at front, shortcut[0] at end, append
53     return cip
```

**Definition as implemented.** A shortcut splits the outer cycle into two arcs. An
arc is a **corner implying path** iff its *interior* (the vertices strictly
between the shortcut's two endpoints) contains no endpoint of any shortcut at
all, its own shortcut included. The returned CIP is that arc plus its two
bounding endpoints. Geometrically: the two endpoints of a shortcut are adjacent
in the graph but non-consecutive on the boundary, so in any rectangular dual they
cannot both lie on one side of the rectangle without the chord crossing the
interior; therefore a rectangle corner has to be placed inside that arc. Hence
"corner implying".

**What it returns.** A `list` of paths that is *not* a partition of the boundary
and is *not* guaranteed to be non-empty:
- zero shortcuts -> `cip == []` (very common: a convex-ish outer cycle);
- one shortcut -> **two** CIPs (both arcs qualify), so `len(cip)` can exceed
  `len(shortcuts)` by up to 2x;
- CIPs share their endpoints with each other and may leave parts of the boundary
  uncovered.
Each returned CIP has length >= 3, because an arc of length 0 would mean the two
endpoints are consecutive on the cycle, which would make the edge a boundary edge
and therefore not a shortcut (`shortcutresolver.py:29`). Consequently
`find_bdy`'s stripped interiors have length >= 1.

**Side effect worth knowing.** Line 31 mutates the caller's `shortcuts` list in
place (its elements are lists, `shortcutresolver.py:31`). `inputgraph.py:287-288`
reads `shortcuts[index][0]` / `[1]` after `find_cip` has run, so it may see the
swapped order. Harmless today (the pair is used symmetrically) but real.

### 3. From CIPs to the four cardinal arcs

`find_bdy` (`news.py:30-33`) drops both endpoints of each CIP, leaving the
candidate corner positions.

**Single boundary, `bdy_path` (`news.py:35-65`).**
- `news.py:46-47`: pick **one uniformly random** vertex from each CIP interior.
  This is the corner for that CIP.
- `news.py:48-52`: if fewer than 4 corners were produced (fewer than 4 CIPs),
  top up with random distinct boundary vertices.
- `news.py:53-58`: re-derive the corners' indices by scanning `bdy` in order, so
  `corner_points_index` is ascending. **The order in which corners were chosen is
  discarded**; arc 0 always starts at the boundary-array-first corner.
- `news.py:60-63`: the four arcs, each closed on the next corner
  (`[idx0:idx1+1]`, `[idx1:idx2+1]`, `[idx2:idx3+1]`, `[idx3:] + [0:idx0+1]`).
  The last arc wraps, so the four arcs always cover the whole cycle.

There is **no feasibility check** here. "At most four CIPs" is enforced by the
caller, not by news.py: `inputgraph.py:280` tests `if len(cips) <= 4`, and the
else-branch (`inputgraph.py:283-296`) destroys shortcuts until `len(shortcuts) <= 4`.
Consecutive CIPs are not "merged"; when there are fewer than four CIPs the
missing corners are simply invented at random boundary vertices.

**Multiple boundaries, the enumeration used by `irreg_multiple_dual`.**
`generate_multiple_bdy` (`inputgraph.py:1477-1482`) chains three functions:
1. `multiple_corners(paths)` (`news.py:95-119`): an odometer over indices, one
   index per CIP, emitting the full cartesian product of the CIP interiors. Count =
   `prod(len(interior_i))`. With zero CIPs (`paths == []`) it emits exactly one
   empty tuple `[[]]` (the `next < 0` exit at `news.py:115-116` fires immediately).
2. `all_boundaries(corner_tuples, boundary)` (`news.py:121-210`): branches on
   `len(paths[0])`, i.e. on the **number of CIPs**, and pads each tuple to 4
   corners:
   - 3 CIPs (`news.py:132-139`): add one free boundary vertex.
   - 2 CIPs (`news.py:140-164`): add two free vertices, plus the degenerate
     families where one of the two chosen corners is doubled (a side of the
     rectangle collapses onto a single room).
   - 1 CIP (`news.py:165-190`): three free vertices, plus doubled variants.
   - 0 CIPs (`news.py:191-209`): every `C(m,4)` choice of 4 boundary vertices,
     plus every `[i,i,j,k]` and every `[i,i,j,j]` degenerate family, `m = len(boundary)`.
   - 4 or more CIPs: falls through to `return paths` (`news.py:210`) unchanged.
3. `find_multiple_boundary(corner_tuples, boundary)` (`news.py:67-93`): for each
   tuple, scan `boundary` in order collecting indices, emitting an index twice when
   the tuple contains that node twice (`news.py:83-85`), then slice out the same
   four arcs as `bdy_path` (`news.py:88-91`).

**What varies between successive candidates**: only the four corner vertices on
the fixed outer cycle. The cycle itself, its orientation, and the arc-0 start rule
never vary. The compass assignment is therefore an arbitrary rotation determined by
boundary-array order, not by geometry.

**What bounds the count**: nothing inside news.py. `all_boundaries` in the 0-CIP
case is `O(m^4)` in the boundary length. The bound is applied downstream:
`self.floorplan_limit = 500` (`inputgraph.py:139`) checked at `inputgraph.py:999`
and `:1084`, `self.floorplan_per_bdy_limit = 20` (`inputgraph.py:140`, raised to
`floorplan_limit` under cardinal pins at `inputgraph.py:862-866`), and
`FLOORPLAN_LIMIT = 30` at the API surface (`api.py:119`). A dimension-based
pre-selector `dim_on_paths_bdy` (`GPLAN/GPLAN/source/path_map.py:99`) trims
`cip_list` when `input_dims` is supplied (`inputgraph.py:972-973`, `:1057-1058`),
and is deliberately skipped under cardinal constraints (`inputgraph.py:959-966`,
`:1045-1051`).

### 4. Attaching the four exterior vertices

`add_news` (`news.py:249-271`):
- `news.py:263-264`: allocate an `(n+4) x (n+4)` int matrix and copy the old one
  into the top-left block. So the four new vertices are indices `n .. n+3` where
  `n == matrix.shape[0]`.
- `news.py:265-268`, the edge-adding loops (each `news_edges` call is the loop at
  `news.py:224-227`, which sets `matrix[source][node] = matrix[node][source] = 1`
  for **every** vertex of the arc):

```
edgecnt += news_edges(adjmatrix, bdy[0], nodecnt)       # N   (no comment in source)
edgecnt += news_edges(adjmatrix, bdy[1], nodecnt + 1)   # east
edgecnt += news_edges(adjmatrix, bdy[2], nodecnt + 2)   # south
edgecnt += news_edges(adjmatrix, bdy[3], nodecnt + 3)   # west
```

  Yes: each cardinal vertex is joined to *every* vertex of its arc, and because
  consecutive arcs share their corner node, **each corner vertex gets edges to two
  NEWS vertices**. That overlap is what makes the completed graph triangulated at
  the corners.
- `news.py:269`: `edgecnt += 4` for the outer ring.
- `news.py:270` -> `connect_news` (`news.py:240-247`): `N-W`, `W-S`, `S-E`, `N-E`.
  That is the 4-cycle **N - E - S - W - N**; N and S are non-adjacent, E and W are
  non-adjacent, as a 4-completion requires.

Note `news_edges` returns the number of arc vertices, not the number of *new*
edges, so `edgecnt` double-counts the two corner vertices shared between arcs.
`edgecnt` is only used as a loop/bookkeeping number here, never to rebuild the
matrix.

### 5. What inputgraph.py receives and how the indices are consumed

After `news.add_news`, `inputgraph.py:301` (and `:761`) does `self.nodecnt += 4`.
So in the post-completion index space:

| index | direction |
|---|---|
| `nodecnt - 4` | **N** |
| `nodecnt - 3` | **E** |
| `nodecnt - 2` | **S** |
| `nodecnt - 1` | **W** |

Verified at the consumption sites, not just from the comments:
- `contraction.py:47`: `for node in range(matrix.shape[0] - 4)` - the four NEWS
  vertices are excluded from contraction ("interior vertex only").
- `expansion.py:39-49`: base case iterates neighbours of `nodecnt-4` excluding
  `nodecnt-3` and `nodecnt-1` (i.e. N's neighbours excluding E and W), labels
  `node -> N` and `S -> node` as 2 (T1) and `node -> E`, `W -> node` as 3 (T2).
- `dual.py:35` starts the T1 (north-south) DFS at `nodecnt-2`; `dual.py:82`
  comments the recursion base `source == nodecnt - 4` as "every S-N ends at N";
  `dual.py:127` comments `centre == nodecnt - 2` as "south".
- `dual.py:153` starts the T2 (west-east) DFS at `nodecnt-1`; `dual.py:196` ends at
  `nodecnt-3` (east); `dual.py:223` comments `centre == nodecnt-1` (west).
- `rdg.py:69-75`: room arrays are sized `nodecnt-4` and nodes `>= nodecnt-4` are
  skipped, so the NEWS vertices never become rooms.
- `operations.py:181-186` (`order_nbrs`) special-cases `centre == nodecnt-2`
  (south) and `centre == nodecnt-1` (west) against `nodecnt-4` (north).

`api.py:123` encodes the same mapping for the public API:
`CARDINAL_DIR_INDEX = {"N": 0, "E": 1, "S": 2, "W": 3}`, with the comment at
`api.py:121-122` naming `news.add_news` as the authority.

---

## Invariants And Preconditions

1. **Input is a PTPG.** The matrix reaching this unit is biconnected, fully
   triangulated, and separating-triangle-free (`inputgraph.py:218-265`).
   `get_bdy`'s "edge in exactly one triangle" test is only a correct outer-cycle
   test on a triangulation (`operations.py:99-107`).
2. **`bdy_ordered` is a simple cycle listing**, first node not repeated at the end;
   `bdy_path`'s wrap-around slice at `news.py:63` assumes it.
3. **The four arcs share corners**: `bdys[i][-1] == bdys[i+1][0]` cyclically. Both
   `bdy_path` (`news.py:60-63`) and `find_multiple_boundary` (`news.py:88-91`)
   produce this, and `filter_boundaries_by_cardinal` explicitly relies on it being
   preserved under rotation and reflection (`inputgraph.py:1396-1399`).
4. **The four arcs cover the whole boundary** including the wrap segment, even when
   more than four corner indices were collected (extras are absorbed into arc 3).
5. **NEWS vertices are the last four indices, in N,E,S,W order.** Every module
   listed above hard-codes this. There is no symbolic constant anywhere.
6. **CIP interiors are non-empty** (length >= 3 before `find_bdy` strips two).
   `multiple_corners` (`news.py:110`) and `bdy_path` (`news.py:47`) index into them
   without a guard. `ptpg_floorplanner.py:241` does not trust this and filters
   `if len(p) > 0`.
7. **Corner tuples contain each node at most twice.** `find_multiple_boundary`'s
   `corner_point.count(i) == 2` branch (`news.py:83-85`) has no `== 3` case; a
   triple would silently produce the wrong index list.
8. **`len(boundary) >= 4`** for `bdy_path`'s top-up loop to terminate; the 3-node
   graph is special-cased before it is ever called (`inputgraph.py:275-276`,
   `:735-736`, `:1473-1475`).

---

## Failure Modes

**Nothing in cip.py or news.py raises a custom exception. There is no
`BoundaryError`.** Failures are silent, or surface as crashes far downstream.

1. **More than four CIPs** (`len(cips) > 4`, `inputgraph.py:280`). The engine does
   *not* fail; it destroys shortcuts. `inputgraph.py:283-293` picks a random
   shortcut, calls `sr.remove_shortcut` (`shortcutresolver.py:34-64`) which inserts
   a new degree-4 vertex splitting the chord, records it in
   `mergednodes`/`irreg_nodes1`/`irreg_nodes2` (so the room re-merges later as a
   non-rectangular room), and repeats while `len(shortcuts) > 4`.
   - *Gotcha A*: the loop condition is on `len(shortcuts)`, but the trigger is on
     `len(cips)`, and one shortcut can yield two CIPs. If `len(cips) > 4` while
     `len(shortcuts) <= 4`, the while body never executes and `inputgraph.py:294-296`
     recomputes the identical CIP set and calls `bdy_path` with more than four
     corner candidates. The result is a boundary where some CIP contains no corner:
     a graph with no rectangular dual, handed to expansion anyway.
   - *Gotcha B*: `sr.remove_shortcut` adds a vertex and rewires the boundary, yet
     `self.bdy_nodes` / `self.bdy_edges` are **not** recomputed. `inputgraph.py:294`
     re-derives `bdy_ordered` from the stale lists, so the new vertex is missing
     from the boundary the CIPs are computed on.
2. **A shortcut that "survives"** does not raise. It just means a CIP exists whose
   interior got no corner, and the downstream `exp.expand` / `dual.py` traversal
   either produces a geometrically wrong plan or raises an
   `IndexError`/`RecursionError` from the T1/T2 walk. There is no guard in this
   unit.
3. **Zero CIPs.** `find_bdy` returns `[]`. In the single path `bdy_path` fabricates
   4 random corners (`news.py:48-52`); in the multiple path `multiple_corners`
   returns `[[]]` and `all_boundaries`'s `len(paths[0]) == 0` branch
   (`news.py:191-209`) enumerates every 4-subset of the boundary. Both work; the
   single path is simply non-deterministic.
4. **Empty candidate list after cardinal filtering.** `filter_boundaries_by_cardinal`
   returns `[]` when no rotation/reflection satisfies the pins
   (`inputgraph.py:1389-1409`). `inputgraph.py:978-979` and `:1064-1065` then do
   `if len(selected_list) == 0: selected_list = cip_list` - but `cip_list` was
   *overwritten* by the filtered list at `inputgraph.py:951` / `:1037`, so this
   "revert" restores nothing. The result is zero floorplans, `fpcnt == 0`. That is
   the intended signal: `api.py:1365` sees
   `len(filter_output_by_cardinal(ui, cardinal_pairs)) == 0` and walks the fallback
   ladder (spanning-tree adjacency, then drop the pins entirely) at
   `api.py:1376-1406`.
5. **Boundary shorter than 4 with no CIPs** would spin forever in `bdy_path`'s
   `while(corner_vertex in corner_points)` (`news.py:50-51`). Guarded only by the
   3-node special case.
6. **`randint(0, -1)`** at `news.py:47` (`ValueError: empty range`) if a CIP
   interior were ever empty. Argued unreachable via `find_cip` (see Invariant 6),
   but `bdy_path` is also called from letter-shape code paths that build `paths`
   differently.

---

## Coupling (what breaks if you change this)

- **Change the N,E,S,W order in `add_news` (`news.py:265-268`)** and you break, at
  minimum: `expansion.py:39-49`, `dual.py:35/82/127/153/196/223`,
  `operations.py:181-186`, `contraction.py:47`, `rdg.py:69-75`, plus
  `api.py:123` and the whole cardinal-constraint feature. Nothing is symbolic; the
  order lives in seven files as arithmetic on `nodecnt`.
- **Change the arc corner-sharing convention** (`news.py:60-63`) and
  `filter_boundaries_by_cardinal`'s rotation/reflection identity breaks
  (`inputgraph.py:1396-1408`), and the 4-completed graph stops being triangulated
  at the corners, which breaks contraction.
- **Change `add_news` to grow the matrix by anything other than 4** and every
  `nodecnt - 4` / `shape[0] - 4` above breaks.
- **Change `find_cip`'s return shape** and you break `news.find_bdy`
  (`news.py:32`), `ptpg_floorplanner.py:240-247`, and the five letter-shape
  modules (`tshape.py:126`, `zshape.py:126`, `ushape.py:130`,
  `staircaseshape.py:120`, `Lshaped.py`), all of which call `find_cip` directly.
- **`cip.find_cip` mutates `shortcuts` in place** (`cip.py:31`). Any caller that
  reuses the list after calling it inherits reordered pairs
  (`inputgraph.py:287-288` does exactly this).
- **`add_news` returns `edgecnt` that over-counts** the shared corner edges
  (`news.py:265-269`). If anyone starts trusting that number to size a matrix or
  validate Euler's formula, it will be wrong by the number of corners.
- **`generate_multiple_bdy` returns `cip_list` before any bound is applied**
  (`inputgraph.py:1483`). Making `all_boundaries` more generous directly inflates
  the `O(m^4)` candidate set with no throttle until `inputgraph.py:999`.

---

## Dead Or Duplicated Code

- **`GPLAN/GPLAN/source/trial/bdy.py` and `GPLAN/GPLAN/bdy.py` are near-identical
  twins.** A `diff` of the two differs only in import style (relative
  `..graphoperations` vs absolute `GPLAN.source.graphoperations`), the presence of
  a `node_coordinates` constructor argument and the crossing check
  (`trial/bdy.py:55,79,81-89`; commented out in the root copy), and whitespace. The
  boundary-identification bodies (`trial/bdy.py:147-177` vs `bdy.py:149-179`) are
  character-for-character the same logic.
- **Both are copies of `InputGraph.irreg_single_dual`'s prologue.**
  `trial/bdy.py:91-177` reproduces `inputgraph.py:211-296` (biconnectivity,
  triangulation, edge->vertex transformation, separating-triangle elimination,
  boundary identification, CIP, shortcut destruction) and then stops: it returns
  `bdys` and never calls `news.add_news`. It duplicates no *function bodies* from
  news.py or cip.py; it calls `cip.find_cip` and `news.bdy_path` / `news.find_bdy`
  by import (`trial/bdy.py:20-21,159,161,175,176`).
- **Neither is reachable from `api.py` or `handlers.py`.**
  `GPLAN/GPLAN/circulation.py:8` does `import GPLAN.bdy` (which binds the name
  `GPLAN`, not `bdy`) and then calls `bdy.Boundary(...)` at `circulation.py:114`
  - that is a `NameError` waiting to happen. Its only caller is
  `Circulation.multiple_circulation` (`circulation.py:90-98`), which is invoked
  nowhere in `handlers.py` or `api.py` (handlers uses only `cir.Room`, `cir.RFP`,
  `cir.circulation`, `cir.plot`: `handlers.py:94-117,257-259`).
  `GPLAN/GPLAN/source/multiple_circ.py:9` imports `GPLAN.source.trial.bdy`, but
  `multiple_circ.py:10` does a bare `import circulation` that cannot resolve, and
  nothing imports `multiple_circ`.
- **`GPLAN/GPLAN/source/trial/` has no `__init__.py`** (only `bdy.py`), so it is a
  namespace package at best.
- **`bdy.py:179` / `trial/bdy.py:179` `main()`** is a hexagon smoke test that prints
  exterior edges. Not a library entry point.
- **`inputgraph.py:559-579` is a commented-out third copy** of the same boundary
  identification + `add_news` block.
- **`news.all_boundaries`'s 3-CIP branch is buggy** (`news.py:132-139`): the
  `for i in diff_options` loop at `news.py:137` is dedented out of the
  `for path in paths` loop at `news.py:133`, so only the **last** corner tuple is
  ever used, and `temp` is never reduced by the tuple's own nodes (unlike the
  2-CIP and 1-CIP branches at `news.py:144-145` and `news.py:169-170`). Effect:
  with exactly 3 CIPs the enumeration collapses to `len(boundary)` candidates all
  sharing one corner triple.
- **`ptpg_floorplanner.py:249-271` reimplements the fallback** that news.py lacks
  (brute-force 4-splits of the cycle when the CIP machinery returns nothing),
  duplicating the intent of `all_boundaries`'s 0-CIP branch.

---

## Open Questions

1. **Gotcha A above** (`len(cips) > 4` with `len(shortcuts) <= 4`) looks like a
   genuine hole: `inputgraph.py:283` never enters its loop, and the code proceeds
   with a boundary that violates the CIP corner theorem. I could not construct a
   concrete graph in this session to confirm it is reachable after
   separating-triangle elimination. Worth a targeted test.
2. **Gotcha B** (stale `self.bdy_nodes` / `self.bdy_edges` after
   `sr.remove_shortcut`, `inputgraph.py:285-294`) is visible in the code but I have
   not observed the resulting misbehaviour at runtime.
3. `find_cip` never asserts that every CIP received a corner, and `bdy_path`'s
   random corner choice (`news.py:47`) makes single-dual output
   **non-deterministic** across runs on the same input. Is that intentional? No
   seeding is done anywhere in this unit.
4. **Knowledge-graph disagreement.** `graphify explain "find_cip"` lists only the
   five letter-shape/staircase callers plus the containing file, and misses
   `inputgraph.py:279,295,739,755,1478` and `ptpg_floorplanner.py:240`. It also
   files `trial/bdy.py` as a live node with no indication that it is unreachable
   from `api.py`/`handlers.py`. Source wins; the graph's caller set for
   `boundary/cip.py` is incomplete.
5. `news_edges`'s return value (arc length, not new-edge count) makes `add_news`'s
   `edgecnt` over-count by the number of corner vertices (`news.py:223-228`,
   `:265-269`). No consumer appears to depend on the exact value today, but
   `generate_multiple_rel` (`inputgraph.py:1424`) passes it around; whether any
   later dimensioning code trusts it was not traced.
