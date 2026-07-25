# dim-04: convert_adj_equ_sym (the constraint builder)

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\dimensioning\convert_adj_equ_sym.py` (124 lines, read in full).

---

## Correction to the task premise (read this first)

The task states the chain is "driven by `minimum_dimensioning.py`". **That is false.**
`minimum_dimensioning.py` never touches this module. Its only imports are
`collections.defaultdict`, `json`, `os` (`minimum_dimensioning.py:1-3`), and a repo-wide
grep for `convert_adj_equ` returns hits only in `floorplan_to_st.py`, `solve_linear.py`
and the module itself. The file is 845 lines and contains no reference to
`convert_adj_equ_sym`, `floorplan_to_st`, `solve_linear`, `scipy` or `numpy`.

There are two independent, unrelated dimensioning solvers in this package:

| | LP solver chain (this dossier) | Longest-path solver |
|---|---|---|
| Files | `floorplan_to_st.py` -> `convert_adj_equ_sym.py` -> `solve_linear.py` | `minimum_dimensioning.py` |
| Method | `scipy.optimize.linprog` on a network-flow LP (`solve_linear.py:76`, `:140`) | Bellman-Ford-ish longest path on a constraint graph (`minimum_dimensioning.py:388`, `:466`) |
| Entered from | `inputgraph.single_floorplan` / `multiple_floorplan` (`inputgraph.py:821`, `:1167`) | `handlers.solve_min_dim` -> `min_dim.main` (`handlers.py:346`, `:352`, `:390`) |
| Production door-connectivity flow | not used | used (`handlers.py:1894`, `:2004`, `:2120`, `:2322`, `:2435`, `:2567`, all inside `handle_door_connectivity` at `handlers.py:1686`) |

So `convert_adj_equ_sym` is on the older "dimensioned floorplan" GUI path, not the
min-dim path that the deployed door-connectivity API exercises. It is still live code
(reachable from `handlers.py:621, 628, 924, 931, 1004, 1069, 1166, 1173, 1474`), but it is
not what the current production run hits.

---

## Purpose

Turn a 0/1 adjacency matrix of one directional s-t graph (vertical or horizontal) into
the four numpy arrays that `scipy.optimize.linprog` needs: objective `f`, inequality LHS
`A`, equality LHS `Aeq`, equality RHS `Beq`. It emits network-flow conservation
equalities, block-symmetry equalities, an optional plot-total equality, and the LHS rows
for per-room min/max dimension inequalities. It does **not** produce the inequality RHS
(`b`); that is built downstream in `solve_linear`.

## Where It Sits In The Pipeline

```
inputgraph.single_floorplan (inputgraph.py:779)
  -> block_checker.block_checker  (inputgraph.py:817)      builds ver_list / hor_list
  -> floorplan_to_st.floorplan_to_st (inputgraph.py:821)
       -> builds VER (floorplan_to_st.py:54-77) and HOR (floorplan_to_st.py:79-101)
       -> convert_adj_equ_sym(VER, ver_list, plot_width)   (floorplan_to_st.py:103-104)
       -> convert_adj_equ_sym(HOR, hor_list, plot_height)  (floorplan_to_st.py:105-106)
       -> solve_linear(...)                                (floorplan_to_st.py:108-109)
```

Called exactly twice per floorplan, once per axis. Both calls run the identical code; the
axis is entirely encoded in which matrix is passed.

## Entry Points (file:line)

- `convert_adj_equ_sym(DGPH, room_list, plot_dimension)` : `convert_adj_equ_sym.py:15`
- Callers: `floorplan_to_st.py:103` (vertical, gives widths) and `floorplan_to_st.py:105`
  (horizontal, gives heights). Import at `floorplan_to_st.py:15`.
- Nested helper `ismember(d, k)` : `convert_adj_equ_sym.py:69`
- Nested helper `any(M)` : `convert_adj_equ_sym.py:100` (shadows the builtin inside the
  enclosing function from that point on)

There are no other functions in the file.

## Data Structures

### Inputs

- `DGPH` : `N x N` numpy int/float array, `N = len(DGPH)` (`convert_adj_equ_sym.py:33`).
  Node 0 is the super-source (north for VER, west for HOR); node `v` for `v in 1..N-1` is
  the room whose 0-based encoded label is `v-1`. Built at `floorplan_to_st.py:68-77` (VER)
  and `:93-101` (HOR): a source-adjacency row is stacked on top of the room-to-room
  adjacency matrix, then a zero column is inserted at index 0 (`floorplan_to_st.py:76`,
  `:101`). Therefore `N = (number of cells in the encoded matrix) + 1`.
  **There is no explicit sink node.** Rooms touching the far boundary simply have
  out-degree 0.
- `room_list` : Python list of lists of **0-based encoded room labels**, in consecutive
  pairs: `room_list[2i]` and `room_list[2i+1]` are the two blocks that must match.
  Produced by `block_checker.py:95` (`ver_list`) and `:96` (`hor_list`); the labels come
  from `E[j][k]` at `block_checker.py:76, 81, 86, 91` where `E` is the un-incremented
  encoded matrix. Empty list when there are no symmetry constraints.
- `plot_dimension` : scalar. `-1` is the sentinel for "no plot constraint"
  (`convert_adj_equ_sym.py:117`).

### Internal

- `lineq_temp` : `N x N**2` dense array (`convert_adj_equ_sym.py:34`). Column `N*i + j`
  holds the incidence vector of edge `i -> j`: `+1` at row `i`, `-1` at row `j`
  (`:41-42`). Memory is O(N^3) floats even though only `M` columns are ever non-zero.
- `LINEQ` : after `:45-55`, an `N x M` node-edge incidence matrix. `LINEQ[v][e] = +1` if
  `v` is the tail of edge `e`, `-1` if `v` is the head, `0` otherwise. Edges are
  enumerated in row-major `(i, j)` order at `:48-52`, so **the first `z` edges are exactly
  the out-edges of the source** (see the objective, below).
- `count` (`:52`) = `M` = number of `1` entries in `DGPH` = number of edges.
- `n = len(LINEQ[0])` = `M` (`:58`).
- `z = np.sum(DGPH[0])` = out-degree of the source (`:60`).

## Algorithm Walkthrough

1. `:33-42` Build the padded incidence matrix `lineq_temp`.
2. `:44-55` Compact it: keep only the `M` columns that correspond to real edges, reshape
   `(M, N)` and transpose to `(N, M)`. `LINEQ` is now the incidence matrix.
3. `:57-63` Objective `f` = `1 x M` zeros with `1` in the first `z` positions.
4. `:68-80` Build `A`, the per-room dimension LHS block (see below).
5. `:82-98` Build `symm_eq_mat`, the block-symmetry equality rows.
6. `:100-109` Build `Aeq`, the flow-conservation rows.
7. `:111-116` Append the symmetry rows to `Aeq`; allocate `Beq` as zeros.
8. `:117-122` If `plot_dimension != -1`, prepend `f` as a new equality row and prepend the
   plot dimension to `Beq`.
9. `:124` Return `[f, A, Aeq, Beq]`.

---

## The Actual Constraints Or Formulas

### 1. VARIABLES

**One decision variable per EDGE of the s-t graph, not per room.**

Let `x in R^M` where `M = sum(DGPH)` = the number of `1` entries = number of directed
edges. Variable indexing is established implicitly by the enumeration order of the loop at
`convert_adj_equ_sym.py:48-52`: edges are numbered in row-major `(i, j)` order of `DGPH`.
That ordering is load-bearing (the objective at `:62-63` depends on it) and is never
recorded anywhere, so there is no explicit edge->index map to inspect.

`x_e` is a flow. Room dimensions are *derived* quantities, never variables:

```
dim(room r) = sum of x_e over all edges e entering node r+1
```

This is computed downstream at `solve_linear.py:80` (`W = -1 * A_VER @ X1`) and
`solve_linear.py:145` for the other axis.

Count as a function of input, for the vertical call (`floorplan_to_st.py:103`):
`M = |{rooms adjacent to north}| + |{ordered vertical room-adjacency pairs}|`, and
`N = n_cells + 1`. Verified empirically: a 3-room vertical chain (`N=4`, 3 edges) gives
`f.shape == (1, 3)`, `A.shape == (6, 3)`.

### 2. EQUATION FAMILIES

Four families. Note `A` is an inequality *LHS only*; the RHS lives in `solve_linear`.

**Family A: per-room minimum (inequality rows, lower half of `A`)**
Emitted at `convert_adj_equ_sym.py:73-80`. For every node `v in 1..N-1`:

```
- sum_{e in in-edges(v)} x_e  <=  b_min[v-1]
```

`solve_linear.py:56` sets `b_min_VER = -min_width`, so with `A_ub x <= b_ub` this is
`dim(room v-1) >= min_width[v-1]`.

**Family B: per-room maximum (inequality rows, upper half of `A`)**
Same loop, `A_max = A` at `:77`, stacked at `:80`. For every node `v in 1..N-1`:

```
  sum_{e in in-edges(v)} x_e  <=  b_max[v-1]
```

`solve_linear.py:57` sets `b_max_VER = max_width`, so this is
`dim(room v-1) <= max_width[v-1]`.

Row 0 (the source, which has no in-edges) is dropped from both halves at `:78-79`.
Resulting `A` shape: `(2*(N-1), M)`. Verified: `N=4` chain gives

```
A = [[-1  0  0]     <- -dim(room0)
     [ 0 -1  0]     <- -dim(room1)
     [ 0  0 -1]     <- -dim(room2)
     [ 1  0  0]     <-  dim(room0)
     [ 0  1  0]     <-  dim(room1)
     [ 0  0  1]]    <-  dim(room2)
```

**Family C: network flow conservation (equality)**
Emitted at `convert_adj_equ_sym.py:106-109`. For every node `v` that has at least one
out-edge AND at least one in-edge (the `any(ismember(...))` test at `:108`):

```
sum_{e in out-edges(v)} x_e  -  sum_{e in in-edges(v)} x_e  =  0
```

RHS zero from `Beq = np.zeros(...)` at `:116`. The source is excluded automatically (no
in-edges) and every far-boundary room is excluded (no out-edges).

Verified on the branching graph `0->1, 0->2, 1->3, 2->3` with edges ordered
`e0=(0,1), e1=(0,2), e2=(1,3), e3=(2,3)`:

```
Aeq rows: [-1  0  1  0]   node 1:  x2 - x0 = 0
          [ 0 -1  0  1]   node 2:  x3 - x1 = 0
```

**Family D: symmetry / equal-block equalities**
Emitted at `convert_adj_equ_sym.py:85-98` (row construction) and `:112-113` (append). For
each pair index `i in 0 .. floor(len(room_list)/2) - 1`:

```
sum_{r in room_list[2i]} dim(r)  =  sum_{r in room_list[2i+1]} dim(r)
```

Mechanically the row is `sum_j A[room_list[2i][j]] - sum_k A[room_list[2i+1][k]]` (`:90`,
`:96`, `:98`). Because `A` rows `0 .. N-2` are the *negated* in-edge indicators, the row
evaluates to `-(block1 total) + (block2 total)`, set `= 0` by the zero `Beq`. Verified:
`room_list = [[0],[1]]` on the branching graph produces the extra row `[-1 1 0 0]`, i.e.
`dim(room0) == dim(room1)`.

**Family E: plot total (equality, optional)**
Emitted at `convert_adj_equ_sym.py:117-122`. If `plot_dimension != -1`:

```
sum_{e in out-edges(source)} x_e  =  plot_dimension
```

prepended as the FIRST row of `Aeq` with `plot_dimension` as the first entry of `Beq`.
Verified: `plot_dimension=10` on the branching graph gives first `Aeq` row `[1 1 0 0]` and
`Beq = [[10, 0, 0]]`.

**Objective (not a constraint but same shape)**
`f` at `:59-63` is the indicator of the source's out-edges, so the LP minimizes
`sum_{e out of source} x_e`, which equals the total plot dimension along that axis. The
inline comment at `:64` records that the author was unsure why only the source cut is
used. Correctness depends entirely on the row-major edge ordering putting the source's
`z` edges first; there is no assertion enforcing that.

### PATH ENUMERATION: there is none

No graph traversal of any kind occurs in this file. There is no DFS, no BFS, no
topological sort, no `networkx` call, no recursion. The only loops are dense matrix
sweeps over `range(0, N)` (`:38-39`, `:48-49`, `:73`, `:107`). Path-sum semantics (every
source-to-sink path sums to the same total) are **not enumerated** and are **not written
out as constraints**; they are enforced implicitly by Family C plus Family E, which is the
standard flow-based encoding. So the answer to "are ALL paths enumerated or a subset" is:
neither, the module never enumerates paths at all, and the number of constraints stays
linear in `N` rather than exponential.

### 3. SYMBOLIC OR NUMERIC

**Purely numeric numpy. There is no sympy anywhere.** The module name suffix `_sym`
means *symmetry* (Family D), not *symbolic*. Stated plainly because the name is
misleading.

The only import is `import numpy as np` (`convert_adj_equ_sym.py:13`). Exact library calls
used: `np.zeros` (`:34, :59, :83, :88, :94, :116, :120`), `np.array` (`:47, :75, :115`),
`np.append` (`:51`), `np.reshape` (`:54`), `np.transpose` (`:55`), `np.sum` (`:60`),
`np.dot` (`:76`), `np.delete` (`:78, :79`), `np.vstack` (`:80, :113, :119`), `np.hstack`
(`:122`). A repo-wide `grep -rln "sympy" --include=*.py` over
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` returns zero files.

### 4. WHERE MIN AND MAX ENTER

Minimums and maximums do **not** enter this module at all. `convert_adj_equ_sym` never
receives `min_width`, `max_width`, `min_height` or `max_height`: its signature is
`(DGPH, room_list, plot_dimension)` (`:15`). What it contributes is only the coefficient
rows (Families A and B), i.e. the linear expressions `+/- dim(room r)`.

The actual numbers enter in `solve_linear.py`:

- vertical / widths: `b_min_VER = -min_width` (`solve_linear.py:56`),
  `b_max_VER = max_width` (`:57`), stacked into `b_VER` (`:62`), fed as `b_ub` (`:76`).
- horizontal / heights: `b_min_HOR` / `b_max_HOR` at `solve_linear.py:115-121` (fallback
  branch) or `:123-129` (aspect-ratio-tightened branch), fed as `b_ub` (`:140`).

The row order of `b_VER` (all mins, then all maxes) must match the row order of `A`
(`A_min` block then `A_max` block, `convert_adj_equ_sym.py:80`). That coupling is
undocumented in both files.

The one dimensional cap that *does* enter this module is `plot_dimension` (Family E),
which is a plot-level total, not a per-room maximum.

For completeness, the *other* solver handles maxima differently: `minimum_dimensioning.py`
puts per-room upper bounds on negative-weight reverse edges
(`minimum_dimensioning.py:238`, `:320`) after widening them through `upper_bound()`
(`minimum_dimensioning.py:158-177`).

### 5. OUTPUT CONTRACT

`return [f, A, Aeq, Beq]` at `convert_adj_equ_sym.py:124`. Let `M` = number of edges,
`N` = `len(DGPH)`, `R = N-1` = number of rooms/cells, `K` = number of nodes with both in-
and out-edges, `S = floor(len(room_list)/2)`, `P = 1` if `plot_dimension != -1` else `0`.

| Name | Type | Shape | Row meaning | Column meaning |
|---|---|---|---|---|
| `f` | `np.ndarray` float64 | `(1, M)` | the single objective row | edge `e`; value `1` for the source's out-edges (first `z`), else `0` |
| `A` | `np.ndarray`, platform-default integer (`int32` on this Windows box) | `(2R, M)` | rows `0..R-1`: `-dim(room r)`; rows `R..2R-1`: `+dim(room r)` | edge `e` |
| `Aeq` | `np.ndarray` float64 | `(P + K + S, M)` | row 0 (if `P=1`): plot total; next `K` rows: flow conservation (`out - in`); last `S` rows: symmetry differences | edge `e` |
| `Beq` | `np.ndarray` float64 | `(1, P + K + S)` | **2-D row vector, not 1-D** | equality index, aligned with `Aeq` rows |

Notes on the contract that bite:

- `A` comes out with integer dtype (it is built from `ismember`'s Python `0/1` lists via
  `np.array` at `:75` and `np.dot(A, -1)` at `:76`), while `Aeq` and `Beq` are float64.
  The exact integer width is the platform default, not a fixed `int64`: reproduced here on
  Windows with Python 3.11.9 and numpy 1.26.0, `A.dtype` is `int32`. The part that matters
  downstream is only that `A` is integer while `Aeq`/`Beq` are float.
- `Beq` is shape `(1, K+S+P)`, not `(K+S+P,)`. `scipy.optimize.linprog` is called with it
  directly at `solve_linear.py:76` and `:140` and tolerates the extra axis, but any
  consumer doing `len(Beq)` gets `1`.
- When `K == 0` and `S == 0` and `P == 0`, `Aeq` is `np.array([])` with shape `(0,)`, not
  `(0, M)`. `solve_linear.py:66` and `:132` special-case exactly this with
  `if not Aeq_VER.tolist():` and skip the LP entirely, returning unit dimensions
  (`solve_linear.py:67-74`, `:133-138`).
- `solve_linear` assumes `2R == len(min_width) + len(max_width)` and splits `W` at
  `l/2` (`solve_linear.py:81-85`). Nothing checks that `R == len(min_width)`.

### 6. FUNCTION INVENTORY AND LIVENESS

| Function | Line | Callers | Status |
|---|---|---|---|
| `convert_adj_equ_sym` | `:15` | `floorplan_to_st.py:103`, `floorplan_to_st.py:105` | live |
| `ismember` (nested) | `:69` | `:74`, `:108` (twice) | live |
| `any` (nested) | `:100` | `:108` (twice) | live |

Nothing in this file is dead. Repo-wide grep for `convert_adj_equ` over
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` confirms `floorplan_to_st.py` is the sole
importer (`floorplan_to_st.py:15`).

---

## Invariants And Preconditions

1. `DGPH` is square, `N x N`, with `DGPH[i][j] in {0, 1}`; node 0 is the only source and
   has no in-edges (guaranteed by the zero-column insertion at `floorplan_to_st.py:76`,
   `:101`).
2. The graph must be acyclic and every room must be reachable from the source, otherwise
   the flow system has no meaningful solution. Nothing in this file checks either.
3. **The edge ordering must be row-major**, because `f` (`:62-63`) assumes the source's
   `z` out-edges occupy indices `0..z-1`. This holds only because the loop at `:48-49`
   iterates `i` outermost starting at `0`.
4. `room_list` entries must be valid 0-based room labels in `0 .. N-2`, since they index
   into `A` at `:90` and `:96` and are expected to land in the `A_min` block. A label
   `>= N-1` would silently index into the `A_max` block and flip the sign of that term.
5. `len(room_list)` is assumed even; `int(room_num/2)` at `:83, :85, :112` silently drops
   a trailing odd element.
6. `plot_dimension == -1` is the sentinel for "unconstrained" (`:117`). A plot dimension
   of literally `-1` cannot be expressed. `0` is NOT the sentinel here (unlike
   `minimum_dimensioning.py:229` and `:311`, which use `> 0`).
7. Row block ordering of `A` (mins first, maxes second) must match `b` construction in
   `solve_linear.py:62` and `:121`/`:129`.

## Failure Modes

All three of the following were reproduced by direct invocation.

1. **`plot_dimension != -1` on a graph with no internal node raises `ValueError`.**
   `Aeq` is `np.array([])` with shape `(0,)` and `np.vstack((f, Aeq))` at `:119` fails
   with `all the input array dimensions except for the concatenation axis must match
   exactly, but along dimension 1, the array at index 0 has size 2 and the array at index
   1 has size 0`. Reachable whenever the encoded matrix is a single band along the axis
   in question (every room touches both the source boundary and the far boundary) *and* a
   plot dimension was supplied. Not caught anywhere in `floorplan_to_st.py` or
   `inputgraph.py:821`.
2. **Symmetry constraints on a graph with no internal node raise the same `ValueError`**
   at `:113` (`np.vstack((Aeq, symm_eq_mat[i]))` with `Aeq` shape `(0,)`).
3. **Silent wrong answer if room labels exceed `N-2`** (see invariant 4). No bounds check.
4. `lineq_temp` is `N x N**2` (`:34`), so allocation is O(N^3) floats. At 100 cells that
   is about 8 MB per call and 2 calls per floorplan candidate (`floorplan_to_st.py:103`
   and `:105`); at 300 cells it is about 216 MB per call. There is no sparse path.
5. `np.append` in a loop at `:51` reallocates the whole `LINEQ` buffer on every edge,
   making construction O(M^2 * N) in copies.
6. Infeasibility is not detected here. It surfaces later as
   `value_opti_ver.success == False` (`solve_linear.py:86`, `:146`), propagated as
   `status` and checked at `inputgraph.py:827`.

## Coupling (what breaks if you change this)

- **Edge ordering** (`:48-52`): changing it silently corrupts `f` (`:62-63`), which is
  both the objective and the plot-total equality row (`:118`). No test would catch this
  as a shape error.
- **`A` row layout** (`:78-80`): `solve_linear.py:82` slices `W[0:l/2]` to recover
  dimensions and `solve_linear.py:62` builds `b_VER` as `hstack(-mins, maxes)`. Any
  reordering of the `A_min`/`A_max` blocks must be mirrored in both places.
- **`A` semantics as "negated in-edge indicator"**: relied on by
  `solve_linear.py:80` (`W = -1 * A_VER @ X1`) *and* by the symmetry construction at
  `:90-98` inside this same file. Two independent consumers of one implicit sign
  convention.
- **`room_list` label base**: `block_checker.py:76/81/86/91` emits 0-based labels while
  `floorplan_to_st.py:49-51` increments the encoded matrix by 1 before building `DGPH`.
  The two conventions happen to cancel because `A` row `r` corresponds to node `r+1`.
  Changing the increment in `floorplan_to_st.py` breaks symmetry silently, not loudly.
- **`Beq` being 2-D**: any refactor of `solve_linear` that does `len(Beq)` or `Beq[i]`
  will read the wrong thing.
- **`plot_dimension == -1` sentinel**: `inputgraph.py:821-823` forwards `plot_width` /
  `plot_height` straight through, so the sentinel must be preserved by every UI/API layer
  that fills those values.

## Dead Or Duplicated Code

- **Duplicated fork:** `GPLAN\GPLAN\pythongui\final.py:1153` defines `Convert_adj_equ`, an
  older copy of this algorithm (same `lineq_temp` trick at `final.py:1155-1176`, same
  nested `ismember` at `:1191` and nested `any` at `:1204`, same `f` construction at
  `:1182-1187`, same flow-conservation loop at `:1210-1212`). It differs: no symmetry, no
  plot-dimension equality, and it emits only the `A_min` half (`final.py:1194-1200`), so
  it has no maximum-dimension rows at all. It also builds `lineq_temp` with a different
  double condition (`final.py:1163-1166`). `final.py` is imported by
  `GPLAN\GPLAN\pythongui\gui.py:27`, so it is not unreachable, but it is a stale parallel
  implementation.
- **Duplicated docstring:** lines `1-12` of `convert_adj_equ_sym.py` are near-identical
  package boilerplate, also present at `floorplan_to_st.py:1-12` and
  `solve_linear.py:1-12`, and it describes the whole package rather than the file. The
  three copies are not byte-identical: `solve_linear.py:6` says "stored in separate files"
  while `convert_adj_equ_sym.py:6` and `floorplan_to_st.py:6` carry the typo "seperate",
  and `floorplan_to_st.py:7-8` wraps the `floorplan_to_st` bullet at a different point than
  `convert_adj_equ_sym.py:7-8`. The differences are cosmetic and affect no constraint or
  sizing claim.
- **Redundant statements inside the function:**
  - `:45` `LINEQ = []` is immediately overwritten by `:47` `LINEQ = np.array(LINEQ)`.
  - `:77` `A_max = A` is an alias, made harmless only because `:79` rebinds it via
    `np.delete`.
  - `:88` and `:94` allocate full `(room_num/2, n)` matrices `add_mat` / `subt_mat` inside
    the per-pair loop but use only row `i` of each, so `S` full matrices are allocated and
    discarded per call.
  - `:83` allocates `symm_eq_mat` with shape `(0, n)` when `room_list` is empty.
- **Shadowing:** the nested `any` at `:100` shadows the builtin for the remainder of
  `convert_adj_equ_sym`. It is functionally equivalent for the `0/1` lists it receives, so
  it is redundant rather than wrong, but it is a trap for future edits (the builtin is not
  recoverable inside that scope).
- The inline question at `:64` ("need explanation, if we want to minimise inflow why dont
  we take all vertices adj to northor west") is an unresolved author note, not a comment
  describing behaviour.
- `GPLAN\GPLAN\source\dimensioning\__init__.py` is an empty file.

## Open Questions

1. Is the LP chain still exercised by the deployed API? `api.py:13` does
   `from GPLAN.handlers import *`, and `handlers.py` reaches both solvers, but I found no
   direct call to `single_floorplan` / `multiple_floorplan` from `api.py`, whereas
   `solve_min_dim` (the `minimum_dimensioning.py` path) is called from
   `handlers.py:1894, 2004, 2120, 2322, 2435, 2567`. The LP chain may be GUI-only.
2. Why is the objective restricted to the source cut (`:62-63`)? Under flow conservation
   every source-to-sink cut carries the same total, so it is correct on a well-formed
   s-t graph, but the author's own comment at `:64` shows this was never confirmed. If the
   graph is ever built with a room that is a source-side dead end, this silently becomes
   the wrong objective.
3. Where, if anywhere, is acyclicity of `DGPH` guaranteed? `floorplan_to_st.py:60-66` and
   `:85-91` derive adjacency from scanning the encoded matrix, which should be acyclic for
   a valid rectangular dissection, but nothing validates it.
4. Are the degenerate-graph `ValueError`s at `:113` and `:119` ever hit in practice, or is
   a single-band floorplan impossible upstream? `inputgraph.py:821` has no try/except
   around the call.
5. Does any caller ever pass an odd-length `room_list`? `block_checker.py:95-96` extends by
   two at a time so it should always be even, but the guard at `:83` silently truncates
   rather than raising.
