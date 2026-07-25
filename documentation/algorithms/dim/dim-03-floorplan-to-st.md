# dim-03: floorplan_to_st + block_checker (Stage 1 of the LP dimensioning chain)

Scope: `GPLAN/GPLAN/source/dimensioning/floorplan_to_st.py` and
`GPLAN/GPLAN/source/dimensioning/block_checker.py`, both under
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\`.

All paths below are absolute-relative to that repo root:
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\...`

---

## Purpose

`floorplan_to_st` converts a *combinatorial, unit-grid* rectangular dual (the
"encoded matrix") into **two square 0/1 adjacency matrices** that encode two
s-t planar digraphs, one per axis, then hands each to `convert_adj_equ_sym` to
be turned into an LP, then hands both LPs to `solve_linear`. It is the entry
point of the linear-programming dimensioning path.

`block_checker` is a **precondition validator for symmetry constraints**. It
parses the user's symmetry string, verifies each named room group tiles a solid
axis-aligned rectangle inside the encoded matrix, and returns the two room
lists (top row, left column) whose dimensions the LP will be forced to equate.

---

## Where It Sits In The Pipeline

**Correction to the task premise: `minimum_dimensioning.py` is NOT the driver of
this chain.** A repo-wide grep for `floorplan_to_st` / `block_checker` finds no
reference inside `minimum_dimensioning.py`. That file is an independent,
*alternative* dimensioning engine (integer constraint graph + longest path,
`construct_constraintgraphX/Y` at `source/dimensioning/minimum_dimensioning.py:225`
and `:307`, driven by `main()` at `:767`). The two engines never call each other.

The real chain:

```
handlers.handle_single / handle_multiple / handle_single_oc /
handle_multiple_oc / handle_letter_shape / handle_circulation
        (only on the "isDimensioned == 1" branch)
   -> inputgraph.InputGraph.single_floorplan   (source/inputgraph.py:779)
      inputgraph.InputGraph.multiple_floorplan (source/inputgraph.py:1126)
        -> operations.get_encoded_matrix       (source/graphoperations/operations.py:211)
        -> bc.block_checker                    (source/inputgraph.py:817, :1164)
        -> fpts.floorplan_to_st                (source/inputgraph.py:821, :1167)
             -> convert_adj_equ_sym  x2        (source/dimensioning/floorplan_to_st.py:103, :105)
             -> solve_linear         x1        (source/dimensioning/floorplan_to_st.py:108)
        -> dual.get_coordinates                (source/inputgraph.py:838, :1181)
```

The `isMinDimensioned == 1` branch (`handlers.py:769`, `:1189`, `:1350`,
`:1787`, `:2240`) goes to `min_dim.main` instead and never touches this file.
So the LP chain and the min-dim chain are two disjoint dimensioning modes
selected by the `dimensioned` vs `minDimEnabled` flags handed in at
`GPLAN/api.py:1230-1231`.

Headless reachability is real, not GUI-only: `dimensiongui.gui_fnc` short-circuits
to `ui.get_min_dim_inputs()` when `gclass is None`
(`GPLAN/pythongui/dimensiongui.py:10-12`), so `handlers.py:917` returns without
opening Tk.

---

## Entry Points (file:line)

| Symbol | Definition | Callers |
|---|---|---|
| `floorplan_to_st(E, min_width, min_height, max_width, max_height, ver_list, hor_list, min_ar, max_ar, plot_width, plot_height)` | `source/dimensioning/floorplan_to_st.py:18` | `source/inputgraph.py:821`, `source/inputgraph.py:1167` |
| `block_checker(E, symm_rooms)` | `source/dimensioning/block_checker.py:4` | `source/inputgraph.py:817`, `source/inputgraph.py:1164` |
| `unique(l)` (nested in `block_checker`) | `source/dimensioning/block_checker.py:17` | `block_checker.py:77, 82, 87, 92` |
| `isblock(l)` (nested in `block_checker`) | `source/dimensioning/block_checker.py:22` | `block_checker.py:64, 65` |

Imports of the two modules: `source/inputgraph.py:39` (`as fpts`) and
`source/inputgraph.py:43` (`as bc`).

Exact call sites (single-floorplan variant):

```python
# source/inputgraph.py:813-823
encoded_matrix = opr.get_encoded_matrix(
    rel_matrix.shape[0] - 4, self.room_x[i], self.room_y[i],
    self.room_width[i], self.room_height[i])
encoded_matrix_deepcopy = copy.deepcopy(encoded_matrix)

[boolean, ver_list, hor_list] = bc.block_checker(
    encoded_matrix_deepcopy, symm_rooms)
if boolean:
    [width, height, hor_dgph, status] = fpts.floorplan_to_st(
        encoded_matrix_deepcopy, min_width, min_height, max_width, max_height,
        ver_list, hor_list, min_ar, max_ar, plot_width, plot_height)
else:
    status = False
```

`source/inputgraph.py:1164-1171` is the same code with
`self.graph_list[i]` substituted for `self`.

---

## Data Structures

### 1. INPUT CONTRACT: the encoded matrix `E`

`E` is a **2-D integer numpy array produced by
`operations.get_encoded_matrix` (`source/graphoperations/operations.py:211-236`)**:

```python
# operations.py:225-235
mat_width  = int(max(a + b for a, b in zip(room_x, room_width)))
mat_height = int(max(a + b for a, b in zip(room_y, room_height)))
encoded_matrix = np.zeros((mat_height, mat_width), int)
for node in range(nodecnt):
    encoded_matrix[y : y + room_height[node], x : x + room_width[node]] = node
```

Therefore:

* **Shape** = `(mat_height, mat_width)` = the *unit-grid* bounding box of the
  combinatorial floorplan. **Rows are y (grid rows), columns are x (grid
  columns).** These are grid cells, not metres: at this point every room has
  integer unit width/height from the dual construction.
* **Cell value = room index**, 0-based, matching the node index of the input
  graph (`encoded_matrix[...] = node`). It is **not** a block id and not a wall id.
* **Row 0 is the top / north edge** of the plan, **column 0 is the left / west
  edge**. This is confirmed downstream: `dual.get_coordinates` accumulates
  `ymin` from row 0 downwards and comments "not subtracting height because code
  requires top left corner" (`source/floorplangen/dual.py:314-319`).
* Every room occupies exactly one solid axis-aligned rectangle of cells (that
  is the definition of a rectangular dual), and the rectangles tile the grid
  with no gaps and no overlaps.
* `nodecnt` passed in is `rel_matrix.shape[0] - 4` (`inputgraph.py:814`), i.e.
  the four exterior/cardinal nodes of the REL are excluded; only real rooms
  (plus merged/extra dummy nodes) appear as cell values.

**How adjacency is recovered.** Two rooms are adjacent iff they occupy
orthogonally neighbouring cells. `floorplan_to_st` recovers this by scanning:

* vertical adjacency = walk *down* each column and record every value change
  (`floorplan_to_st.py:60-66`);
* horizontal adjacency = walk *right* along each row and record every value
  change (`floorplan_to_st.py:85-91`).

A value change from `a` to `b` while walking down column `j` means room `b`
sits directly below room `a`, and the cells where that change occurs are exactly
the cells of their shared horizontal wall.

**Worked example, 2x2.**

```
E = [[0, 1],
     [2, 3]]
```

Four unit rooms: room 0 top-left, room 1 top-right, room 2 bottom-left,
room 3 bottom-right. Adjacencies: 0-1 (horizontal), 2-3 (horizontal),
0-2 (vertical), 1-3 (vertical). Rooms 0 and 3 are only corner-touching, so no
adjacency (the scan never sees a 0 -> 3 transition).

Running lines 42-101 of `floorplan_to_st.py` on this `E` (verified by executing
the code) gives node numbering `node 0 = source`, `node k = room k-1`:

```
VER (int32, 5x5)              HOR (float64, 5x5)
     0  1  2  3  4                 0    1    2    3    4
0 [  0  1  1  0  0 ]          0 [  0.   1.   0.   1.   0. ]
1 [  0  0  0  1  0 ]          1 [  0.   0.   1.   0.   0. ]
2 [  0  0  0  0  1 ]          2 [  0.   0.   0.   0.   0. ]
3 [  0  0  0  0  0 ]          3 [  0.   0.   0.   0.   1. ]
4 [  0  0  0  0  0 ]          4 [  0.   0.   0.   0.   0. ]
```

`VER[0][1]=VER[0][2]=1`: the north source feeds rooms 0 and 1 (the top row).
`VER[1][3]=1`: room 0 is directly above room 2. `VER[2][4]=1`: room 1 above
room 3. `HOR[0][1]=HOR[0][3]=1`: the west source feeds rooms 0 and 2 (the left
column). `HOR[1][2]=1`: room 0 left of room 1. `HOR[3][4]=1`: room 2 left of
room 3.

### 2. What a node and an edge in the s-t graph mean

Derived from the construction, not from the docstring.

**Nodes.** `len_dgph = np.amax(E)` after the global +1 shift
(`floorplan_to_st.py:49-53`) equals `max room id + 1` = the room count. Both
`ver_dgph` and `hor_dgph` are `len_dgph x len_dgph` room-by-room matrices
(`:54`, `:79`). One extra row is prepended (`north_adj` at `:55`, `west_adj` at
`:80`; stacked at `:70-74` and `:95-99`) and one all-zero column is inserted at
index 0 (`:76`, `:101`).

So the final `VER` / `HOR` are `(n+1) x (n+1)` and:

* **node 0 = the single source** (north for `VER`, west for `HOR`);
* **node k, for k in 1..n, = room k-1** (a room of the floorplan).

**A node is a ROOM, not a wall segment and not a slice.** There is **no sink
node t**: nothing is appended for south/east. The name "s-t graph" is aspirational.

**Edges.** `VER[a][b] = 1` (set at `:65` on `ver_dgph`, shifted by the column
insert at `:76`) means "room b is directly below room a". Physically the edge
**is the shared horizontal wall segment** between the two rooms. `HOR[a][b] = 1`
(set at `:90`) means "room b is directly to the right of room a"; the edge is
the shared **vertical** wall segment. Source edges: `north_adj[0][r] = 1` at
`:58` for every room touching row 0 (its wall segment is that room's slice of
the north plot boundary); `west_adj[0][r] = 1` at `:83` for every room touching
column 0.

**Edge variables are lengths, node throughput is a room dimension.**
`convert_adj_equ_sym` creates one LP variable per 1-entry of the matrix
(`convert_adj_equ_sym.py:38-54`) and imposes flow conservation at every node
that has both in-edges and out-edges (`convert_adj_equ_sym.py:107-109`).
`solve_linear` then reads a room's dimension off its **in-edge sum**:

```python
# solve_linear.py:80
W = (-1) * np.dot(A_VER, X1)     # A_VER row r == minus the in-edge indicator of node r
```

So in `VER` the flow on an edge is the **horizontal length** of that shared
horizontal wall, conservation at a room says (sum of top wall segments) =
(sum of bottom wall segments) = **the room's width**, and the total flow leaving
the north source is the **plot width**. Symmetrically in `HOR` the flow is the
**vertical length** of a shared vertical wall, and node throughput is the
room's **height**, total source outflow = **plot height**. This is why
`floorplan_to_st.py:104` passes `plot_width` with `VER` and `:106` passes
`plot_height` with `HOR`, despite the confusing "VER/HOR" naming.

### 3. One graph or two? Where the transpose is

**Two graphs, and there is no transpose anywhere.** The vertical construction
occupies `floorplan_to_st.py:54-77` and the horizontal construction
`:79-101`; they are **hand-duplicated code with `i`/`j` and `rows`/`columns`
swapped**, not a second call on `E.T`:

* vertical: `for i in range(0, columns): for j in range(0, rows):` (`:60-61`),
  source row from `E[0][i]` (`:58`);
* horizontal: `for i in range(0, rows): for j in range(0, columns):` (`:85-86`),
  source row from `E[i][0]` (`:83`).

`convert_adj_equ_sym` is then called twice, once per graph
(`floorplan_to_st.py:103` and `:105`), and `solve_linear` is called **once** with
both LPs (`:108`), because the horizontal LP's bounds depend on the vertical
LP's solution through the aspect-ratio coupling (`solve_linear.py:90-129`).

### 4. OUTPUT CONTRACT crossing into `convert_adj_equ_sym`

`convert_adj_equ_sym(DGPH, room_list, plot_dimension)`
(`source/dimensioning/convert_adj_equ_sym.py:15`). To build a valid stage-2
input from scratch you need exactly these three things:

**(a) `DGPH`** - a square `numpy.ndarray` of shape `(n+1, n+1)` where `n` is the
room count, values in `{0, 1}`, interpreted as a directed adjacency matrix:

* index 0 = the source (north for the vertical call, west for the horizontal
  call). Column 0 is all zeros (inserted at `floorplan_to_st.py:76` / `:101`),
  i.e. the source has no in-edges.
* index `k` (1..n) = room `k-1`.
* `DGPH[a][b] == 1` means an edge a -> b: "b immediately below a" for the
  vertical graph, "b immediately right of a" for the horizontal graph;
  `DGPH[0][b] == 1` means room `b-1` touches the north (resp. west) boundary.
* Diagonal is zero; the graph must be a DAG with node 0 the unique source.
* Ordering matters: `convert_adj_equ_sym.py:60-63` sets the objective to the
  first `z = sum(DGPH[0])` LP variables, and that is only the source's
  out-edges because `:48-52` enumerates edges in **row-major order** of `DGPH`.
  Row 0 must therefore be the source row.

**dtype gotcha:** `VER` is `int` (built from `np.zeros(..., int)` at
`floorplan_to_st.py:54-55`) but `HOR` is **float64** (`np.zeros([...])` without
`int` at `:79-80`). Both work because `DGPH[i][j] == 1` is true for `1.0`, but
the asymmetry is real and is visible in the returned `hor_dgph`.

**(b) `room_list`** - a Python `list` of `list[int]`, **even length**, consumed
in consecutive pairs `(room_list[2i], room_list[2i+1])`
(`convert_adj_equ_sym.py:85-98`). Each inner list holds **0-based room ids**
(the raw values of `E` before `floorplan_to_st`'s +1 shift), and the two lists
of a pair are constrained to have equal total dimension. Element values index
`A` directly at `:90` and `:96`, which is correct because row 0 of `A` (the
source) was deleted at `:78-79`, so `A[r]` is the node `r+1` = room `r` row.
An empty list means "no symmetry constraints" and is the normal case.
`floorplan_to_st.py:104` passes `ver_list` here, `:106` passes `hor_list`.

**(c) `plot_dimension`** - a scalar. **`-1` is the sentinel for "unconstrained"**
(`convert_adj_equ_sym.py:117`); any other value adds one equality row forcing the
total source outflow to equal it. `plot_width` goes with the `VER` call,
`plot_height` with the `HOR` call.

**Return of `convert_adj_equ_sym`** (`convert_adj_equ_sym.py:124`), i.e. what
stage 2 hands to `solve_linear`, with `n_edges` = number of 1-entries in `DGPH`
and `N = n+1`:

| Name | Type / shape | Meaning |
|---|---|---|
| `f` | `ndarray (1, n_edges)` | objective; 1 on the source's out-edges (first `z` columns), 0 elsewhere. Minimises the plot dimension. |
| `A` | `ndarray (2N-2, n_edges)` | `vstack(-A_in, +A_in)` with the source row deleted; rows `0..N-2` give minus-the-dimension of room `r`, rows `N-1..2N-3` give plus-the-dimension. Used as `A_ub`. |
| `Aeq` | `ndarray (k, n_edges)` | flow conservation rows for nodes with both in- and out-edges, plus one row per symmetry pair, plus (prepended) the plot-dimension row when `plot_dimension != -1`. |
| `Beq` | `ndarray (1, k)` | zeros, with `plot_dimension` prepended when applicable. Note this is 2-D `(1,k)`, not 1-D. |

**Return of `floorplan_to_st` itself** (`floorplan_to_st.py:114`):

```python
return [width, height, hor_dgph, status]
```

* `width`, `height`: whatever `solve_linear` returned, rounded to 3 dp at
  `:111-112`. From `solve_linear.py:80` / `:145` these are column vectors of
  shape `(2n, 1)`: the **first n entries are the per-room dimensions**, the
  last n are their negations. The caller immediately transposes and flattens
  (`inputgraph.py:831-834`), so it silently keeps all `2n` values.
* `hor_dgph`: the **`n x n` float64** horizontal room-to-room matrix **without**
  the west row/column (`:79`, mutated at `:90`). Note this is *not* the `HOR`
  that went into the LP. It is consumed by `dual.get_coordinates`
  (`inputgraph.py:838`, `source/floorplangen/dual.py:235`), which transposes it
  at `dual.py:274` and uses `find`/`find_sp` on each room's row to locate the
  room immediately to its left.
* `status`: Python `bool`, `ver_success and hor_success` from
  `solve_linear.py:153`.

### 5. What `block_checker.py` actually checks

The file contains **one module-level function and two functions nested inside
it**. Full enumeration:

| # | Function | Line | What it tests | Returns on failure |
|---|---|---|---|---|
| 1 | `block_checker(E, symm_rooms)` | `block_checker.py:4` | For each *pair* of room groups in the symmetry string, that **both** groups form solid axis-aligned rectangles ("blocks") in `E`. | `[False, ver_list, hor_list]` at `:101` where the lists still hold the entries accumulated for the pairs that *did* pass (`:95-96`). Callers ignore the lists when the bool is false (`inputgraph.py:820`, `:1166`). |
| 2 | `unique(l)` (nested) | `block_checker.py:17` | Nothing. Pure helper: `np.unique(l).tolist()`, i.e. dedupe + sort. | n/a, cannot fail on valid input |
| 3 | `isblock(l)` (nested) | `block_checker.py:22` | Marks every cell whose value is in `l` with `-1` (`:27-28`), computes the bounding box and the marked-cell count (`:36-43`), and tests `count > 0 and count == (right-left+1)*(bottom-top+1)` (`:45`), i.e. **the marked cells exactly fill their bounding rectangle**. | `[False, [], []]` at `:50` |

No function in `block_checker.py` is dead code. `block_checker` has two callers
(`inputgraph.py:817`, `:1164`, confirmed by a repo-wide grep for `bc.` which
returns only those two lines plus the import at `:43`); `isblock` is called at
`:64` and `:65`; `unique` at `:77`, `:82`, `:87`, `:92`.

**Symmetry-string format.** Lines `:5` and `:12-15`: split on `,`, then in each
piece replace `+` with a space and strip `(` and `)`. So `"(0+1),(2+3)"` becomes
groups `["0","1"]` and `["2","3"]`, parsed to ints at `:57` and `:62`. Groups
are consumed **two at a time** (`:52-62`); a trailing odd group is silently
ignored because the loop bound is `int(symm_num / 2)`.

**On success**, for each passing pair `isblock` returns two corner pairs
(`:46-47`):

* `ver_rooms = [[top,left],[top,right]]` - the block's **top row**. Lines
  `:74-77` collect `E[top][left..right]`, deduped: the rooms whose **widths**
  add up to the block's width.
* `hor_rooms = [[top,left],[bottom,left]]` - the block's **left column**. Lines
  `:79-82` collect `E[top..bottom][left]`, deduped: the rooms whose **heights**
  add up to the block's height.

These become `ver_list` / `hor_list` (`:95-96`), extended two entries at a time
so the pairing survives into `convert_adj_equ_sym.py:85-98`.

**Empty-string behaviour (the common case).** `"".split(',')` is `['']`, so
`symm_num == 1`, `int(1/2) == 0`, the loop body never runs, `ret == []`, and
`all(...)` over an empty list is `True`. `block_checker("")` returns
`[True, [], []]` and the LP proceeds unconstrained. This function is therefore
on the hot path of every dimensioned floorplan, not just symmetric ones.

**What it does NOT check:** it never verifies that the two blocks of a pair are
the same size or the same shape, never verifies the room ids exist in `E`, and
never verifies the two groups are disjoint. Equality of the two blocks is
enforced later, numerically, by the LP equality rows built at
`convert_adj_equ_sym.py:83-98`.

---

## Algorithm Walkthrough (`floorplan_to_st`)

1. `:42-48` read `rows`/`columns`, copy `E` into a fresh `np.array`, then read
   `rows`/`columns` **again**. `np.array(ndarray)` copies by default, so the
   caller's `encoded_matrix_deepcopy` is never mutated.
2. `:49-51` add 1 to every cell. From here on cell value `v` means room `v-1`.
   This shift exists only so that "0" can later mean "the source column".
3. `:53` `len_dgph = np.amax(E)` = number of rooms (assumes contiguous ids).
4. `:54-58` allocate `ver_dgph (n x n, int)` and `north_adj (1 x n, int)`; mark
   `north_adj[0][r] = 1` for every distinct value in **row 0**.
5. `:60-66` for each column, walk top to bottom carrying `temp`; on every value
   change set `ver_dgph[temp-1][new-1] = 1` and update `temp`. Note `temp` is
   only initialised inside the `j == 0` branch, so it leaks across columns if
   `rows == 0` (never happens for a real plan).
6. `:68-76` stack `north_adj` on top of `ver_dgph` and insert a zero column at
   index 0, giving the `(n+1) x (n+1)` `VER`.
7. `:77` `N = len(VER)` - assigned and never read. Dead.
8. `:79-101` the same six steps for the horizontal direction, producing
   `hor_dgph` (float64) and `HOR`.
9. `:103-106` two calls to `convert_adj_equ_sym`, `VER` with `ver_list` and
   `plot_width`, `HOR` with `hor_list` and `plot_height`.
10. `:108-109` one call to `solve_linear` with both LP triples plus all the
    per-room min/max width, min/max height and min/max aspect-ratio lists.
11. `:111-114` round to 3 dp and return `[width, height, hor_dgph, status]`.

---

## The Actual Constraints Or Formulas

Let `x_e >= 1` be the LP variable for edge `e` of a graph (`bounds=(1,None)` at
`solve_linear.py:76` and `:140`), `In(r)` the in-edges of node `r`,
`Out(r)` the out-edges.

* **Room dimension:** `dim(r) = sum_{e in In(r)} x_e`. Implemented as
  `A[r] = -indicator(In(r))` (`convert_adj_equ_sym.py:73-80`) and
  `W = -A_VER @ X1` (`solve_linear.py:80`).
* **Flow conservation (the geometric consistency condition):** for every node
  with both in- and out-edges, `sum_{In(r)} x_e - sum_{Out(r)} x_e = 0`
  (`convert_adj_equ_sym.py:106-109`, rows of `LINEQ` where +1 marks the tail and
  -1 marks the head, `:38-42`).
* **Per-room bounds:** `A_ub @ x <= b_ub` with
  `b = hstack(-min_dims, +max_dims)` (`solve_linear.py:56-62`), i.e.
  `-dim(r) <= -min_r` and `dim(r) <= max_r`.
* **Symmetry:** for pair `i`, `sum_{r in group1} dim(r) - sum_{r in group2} dim(r) = 0`
  (`convert_adj_equ_sym.py:85-98`, `:112-113`). Since `A[r]` is the *negated*
  indicator, `add_mat - subt_mat` equals `-(sum group1) + (sum group2)`; equated
  to 0 it is the intended equality.
* **Plot size:** `sum_{e in Out(source)} x_e = plot_dimension`, added as an
  equality row only when `plot_dimension != -1`
  (`convert_adj_equ_sym.py:117-122`).
* **Objective:** minimise `sum_{e in Out(source)} x_e`, i.e. minimise the plot
  dimension (`convert_adj_equ_sym.py:58-63`). The source-code comment at `:64`
  is the original authors questioning this choice.
* **Aspect ratio (applied only to the second solve):**
  `min_height_mod[i] = max(min_height[i], min_ar[i]*width[i])`,
  `max_height_mod[i] = min(max_height[i], max_ar[i]*width[i])`
  (`solve_linear.py:90-107`). If any `min > max`, the AR constraints are
  dropped entirely with a printed warning and the raw height bounds are used
  (`solve_linear.py:108-121`).

---

## Invariants And Preconditions

1. **Room ids are contiguous `0..n-1` and every id appears in `E`.**
   `len_dgph = np.amax(E)` (`floorplan_to_st.py:53`) is the *only* source of the
   room count. A missing id yields an isolated node with a zero-width room; an
   id above the count silently enlarges every matrix.
2. **Every room is one solid rectangle in `E`.** Violated, the column/row scans
   would emit spurious adjacencies and flow conservation would be infeasible.
3. **`len(min_width) == len(max_width) == len(min_height) == len(max_height) ==
   len(min_ar) == len(max_ar) == len_dgph`.** `A` has `2*len_dgph` rows and
   `b_VER` has `2*len(min_width)` entries (`solve_linear.py:56-62`); a mismatch
   is a `scipy` shape error, not a graceful failure. `inputgraph.py:797-810`
   pads these lists for merged and extra (dummy) nodes precisely to preserve this.
4. **Row 0 of `DGPH` is the source row, column 0 is all zeros.** Required by the
   objective construction (`convert_adj_equ_sym.py:60-63`) and by the
   `np.delete(..., 0, 0)` at `:78-79`.
5. **`ver_list` / `hor_list` hold 0-based room ids** and have even length.
6. **`plot_width`/`plot_height == -1` means unconstrained.** Any other value,
   including 0, adds a hard equality.
7. **`symm_rooms` must be a `str`.** `block_checker.py:5` calls `.split` on it
   unconditionally.
8. `floorplan_to_st` does not mutate its `E` argument (the `np.array` at `:44`
   copies), so `inputgraph.py:838` can reuse `encoded_matrix` afterwards.

---

## Failure Modes

* **Symmetry group is not a rectangle** -> `isblock` returns
  `[False, [], []]` (`block_checker.py:50`) -> `block_checker` returns False ->
  `inputgraph.py:826` / `:1171` sets `status = False` and the loop `continue`s
  to the next REL. No exception, no message; the floorplan is silently skipped.
* **LP infeasible** -> `linprog(...).success == False`
  (`solve_linear.py:86`, `:146`) -> `status == False` -> same silent skip. The
  returned `W`/`H` in that case are garbage derived from whatever `x` scipy
  left behind, but the caller never reads them because it checks `status` first.
* **`Aeq` empty** (a graph with no node having both in- and out-edges, e.g. a
  single-room plan and no plot constraint) -> `solve_linear.py:66-74` /
  `:132-138` bypasses the LP entirely and returns a vector of `+1`s and `-1`s
  with `success = True`. Every room gets dimension 1. This is a silent
  degenerate path, not an error.
* **All RELs fail** -> `self.floorplan_exist` stays False and
  `handlers.py:926-932` re-prompts in a `while` loop. With `gclass is None`
  (headless) `dimgui.gui_fnc` returns the *same* parameters every time, so this
  becomes an **infinite loop**.
* **Aspect ratio contradiction** -> printed message at `solve_linear.py:113-114`
  and the AR constraints are dropped. Not a failure, but a silent constraint
  relaxation.
* **Symmetry ids out of range** -> `A[temp1[j]]` at `convert_adj_equ_sym.py:90`
  raises `IndexError`. `block_checker` does not validate the ids.
* **Not a current failure mode, but a future one:** `method='interior-point'`
  (`solve_linear.py:76`, `:140`) is deprecated. The SciPy deprecation warning
  names 1.11.0 as the removal target, but the solver was not actually dropped in
  the 1.11 line. `GPLAN/requirements.txt:13` pins `scipy==1.11.2` and the
  interpreter in this environment has 1.11.3; running
  `linprog([1.0], A_ub=[[1.0]], b_ub=[5.0], bounds=(1,None), method='interior-point')`
  there returns `success=True` with only a `DeprecationWarning`. The LP chain
  runs today. It will break on a future SciPy that removes the solver, so
  switching to `method='highs'` is a real but not-yet-active migration.

---

## Coupling (what breaks if you change this)

* **Node numbering (`node k = room k-1`)** is assumed by
  `convert_adj_equ_sym.py:78-79` (delete row 0) and `:90`/`:96` (`A[room_id]`).
  Add a sink node or reorder rows and both the symmetry rows and the per-room
  bound rows silently address the wrong rooms.
* **Row-major edge enumeration** (`convert_adj_equ_sym.py:48-52`) is what makes
  "the first `z` variables are the source's out-edges" true at `:60-63`. Any
  change to the enumeration order breaks the objective and the plot-size
  equality without any error.
* **`hor_dgph` return shape (`n x n`, no west row/col)** is consumed by
  `dual.get_coordinates` (`source/floorplangen/dual.py:235`, transposed at
  `:274`). Returning `HOR` instead of `hor_dgph` would shift every room's x by
  one index.
* **`width`/`height` are length-`2n` column vectors**, and
  `inputgraph.py:831-834` transposes and flattens without slicing. Changing
  `solve_linear` to return only the first `n` entries would fix a latent bug but
  would change what `room_width`/`room_height` contain and therefore what
  `opr.calculate_area` (`inputgraph.py:843`) sees.
* **`-1` as the "no plot constraint" sentinel** is spread across
  `floorplan_to_st.py:104,106` and `convert_adj_equ_sym.py:117`. Callers that
  pass `0` or `None` get very different behaviour.
* **The symmetry string grammar** (`(a+b),(c+d)`) is parsed only in
  `block_checker.py:12-15` and produced by `DimParameters.get_symmetric()` via
  `dimensiongui.gui_fnc`. Nothing validates it.
* Changing `block_checker`'s empty-string behaviour (`[True, [], []]`) would
  break every non-symmetric dimensioned floorplan, since that is the default.

---

## Dead Or Duplicated Code

* **`floorplan_to_st.py:42-43`** computes `rows`/`columns`, then `:47-48`
  computes them again from the same data. The first pair is dead.
* **`floorplan_to_st.py:77`**: `N = len(VER)` is assigned and never read. Dead.
* **`floorplan_to_st.py:45-46`**: commented-out hardcoded test matrix
  `E=[[5,5,5,5,6],[3,3,4,4,4],[0,1,1,2,2]]`. Useful as a fixture, but dead.
* **`floorplan_to_st.py:54-77` vs `:79-101`** are the same algorithm written
  twice with the loop axes swapped. A single helper taking `E` and `E.T` would
  collapse them; the duplication is also why `VER` is `int` and `HOR` is
  `float64` (`:54-55` pass `int`, `:79-80` do not).
* **`block_checker.py:8-9`**: `hor_rooms = []` and `ver_rooms = []` in the outer
  scope are never read. The names used later (`:46-47`) are locals of `isblock`.
  Dead.
* **`block_checker.py:23`**: `list = []` shadows the builtin and is never used.
  Dead.
* **`block_checker.py:56`, `:61`**: `temp1_sz` / `temp2_sz` are assigned and
  never read inside `block_checker` (the names are re-derived in
  `convert_adj_equ_sym.py:87`, `:93`). Dead.
* **Unused imports of these two modules:** `GPLAN/bdy.py:18-19` and
  `GPLAN/source/trial/bdy.py:18-19` import `floorplan_to_st as fpts` and
  `block_checker as bc` but never reference `fpts` or `bc` anywhere in those
  files (confirmed by grep). Dead imports.
* **`GPLAN/pythongui/final.py:925`** contains a *different, older*
  `floorplan_to_st(A, user_rooms, total_rooms)` and `final.py:1224` an older
  `solve_linear` with a different signature. `final.py` is a self-contained
  legacy single-file GUI; nothing in `GPLAN/api.py` or `GPLAN/handlers.py`
  imports it. Duplicated legacy code.
* **Whole-repo duplication:** an identical copy of every file discussed here
  exists under `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\`
  (the submodule checkout). Edits must land in the engine repo.
* `inputgraph.py:815` `copy.deepcopy(encoded_matrix)` is defensive but
  unnecessary: neither `block_checker` (which copies at `block_checker.py:26`)
  nor `floorplan_to_st` (which copies at `floorplan_to_st.py:44`) mutates it.
* **Not dead, but worth stating plainly:** this entire LP chain is *unreachable*
  in the min-dimensioning mode used by the production door-connectivity path,
  which runs `minimum_dimensioning.main` instead (`handlers.py:769`, `:1189`,
  `:1350`, `:1787`, `:2240`). It is live only when `isDimensioned == 1`.

---

## Open Questions

1. Is `isDimensioned == 1` ever set by the deployed frontend, or is the whole LP
   chain effectively legacy in production? `GPLAN/api.py:1230` takes
   `dimensioned` from the request; tracing which callers set it was outside
   this dive.
2. `solve_linear` returns `W` of length `2n` (dimensions followed by their
   negations) and `inputgraph.py:833-834` assigns the whole thing to
   `room_width`. Is downstream code relying on the extra `n` entries, or is this
   a latent bug masked by everything indexing only `0..n-1`?
3. ~~What SciPy version is pinned, and does `method='interior-point'` still
   work?~~ **Answered.** `GPLAN/requirements.txt:13` pins `scipy==1.11.2`,
   the installed interpreter is on 1.11.3, and `method='interior-point'`
   (`solve_linear.py:76`, `:140`) still solves there, emitting only a
   `DeprecationWarning`. So this says nothing about question 1: the chain is
   runnable, and whether it runs depends purely on the `isDimensioned` flag.
4. `multiple_floorplan` at `inputgraph.py:1160` reads
   `self.graph_list.rel_matrix_list` (attribute on a *list*), which looks like it
   should be `self.graph_list[i].rel_matrix_list`. Does that path ever execute?
5. The objective comment at `convert_adj_equ_sym.py:64` questions whether
   minimising only the source's out-flow is the intended objective. Was this
   ever resolved, and does it match the published GPLAN paper?
6. No sink node is ever created. Is the total dimension at the south/east
   boundary genuinely pinned by conservation alone for every REL the generator
   can emit, including ones containing merged/dummy nodes?
