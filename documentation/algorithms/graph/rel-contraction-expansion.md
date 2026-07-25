# REL construction by contraction and expansion

Unit: `GPLAN/GPLAN/source/floorplangen/contraction.py` (231 lines) and
`GPLAN/GPLAN/source/floorplangen/expansion.py` (548 lines).

All line anchors below were read in this session. Repo root is
`C:\Users\nitant\Documents\GPLAN_Revamp`; paths are given relative to it.

---

## Purpose

These two modules turn a properly triangulated planar graph (PTPG) that has already
been 4-completed (the four exterior N, E, S, W vertices attached) into a **Regular
Edge Labelling**: an orientation plus 2-colouring of every interior edge such that
the two colour classes form two directed acyclic path systems, S-to-N and W-to-E.

The method is the classical contract-then-expand scheme:

1. `contraction.contract` (contraction.py:187) repeatedly deletes a degree-4 or
   degree-5 interior vertex by merging it into one of its neighbours, recording each
   merge on a stack, until no further merge is possible.
2. `expansion.basecase` (expansion.py:29) labels the trivial remaining graph.
3. `expansion.expand` (expansion.py:53) pops merges off the stack in reverse order,
   reinserting each deleted vertex and choosing labels for its incident edges from a
   ten-case table (`case_a` .. `case_j`, expansion.py:203-547).

The output is a single square integer matrix that is simultaneously the adjacency
matrix and the REL. It is consumed by `rdg.construct_dual`.

---

## Where It Sits In The Pipeline

```
api.py:13 (from GPLAN.handlers import *)
  -> handlers.handle_door_connectivity (handlers.py:1686)  [api.py:1309, api.py:1353]
       -> InputGraph.door_connectivity (inputgraph.py:340)      # biconnect / triangulate / PTPG-ify
       -> InputGraph.irreg_multiple_dual (inputgraph.py:852)    [handlers.py:1830]
            -> generate_multiple_rel (inputgraph.py:1412)       [called at 986-987 and 1072-1073]
                 -> news.add_news            (inputgraph.py:1424)
                 -> cntr.degrees/goodnodes/contract (inputgraph.py:1427-1430)
                 -> exp.basecase + exp.expand loop  (inputgraph.py:1432-1434)
                 -> flp.* flip closure       (inputgraph.py:1437-1449)
            -> rdg.construct_dual            (inputgraph.py:1118)
  -> handlers.handle_single / handle_multiple ... -> InputGraph.irreg_single_dual
       (inputgraph.py:202) -> contraction/expansion at inputgraph.py:304-312
       -> rdg.construct_dual (inputgraph.py:313)
```

There are exactly **three live call sites** of this unit in `inputgraph.py`
(`irreg_single_dual` at 304-312, `door_connectivity2` at 764-772, and
`generate_multiple_rel` at 1427-1434), of which `door_connectivity2` is dead (see
Dead Or Duplicated Code).

`rdg.py` does **not** call contraction or expansion at all (Grep for
`contraction|expansion|cntr|contract|expand|basecase|goodnodes` over
`source/floorplangen/rdg.py` returns no matches). The coupling is one-directional:
`inputgraph.py` hands `rdg.construct_dual` the finished REL matrix.

---

## Entry Points (file:line)

Contraction:
- `contraction.py:23` `degrees(matrix)` -> per-node degree list.
- `contraction.py:35` `goodnodes(matrix, degrees)` -> initial candidate list.
- `contraction.py:52` `is_goodvertex(matrix, degrees, node)` -> eligibility predicate.
- `contraction.py:84` `cntr_nbr(matrix, node)` -> picks the merge target, or `(-1, [])`.
- `contraction.py:124` `update_adjmat(matrix, node, nbr)` -> in-place merge.
- `contraction.py:143` `update_degrees(degrees, node, nbr, mut_nbrs)`.
- `contraction.py:160` `check(...)` -> refresh candidate membership.
- `contraction.py:187` `contract(matrix, goodnodes, degrees)` -> **main driver**.

Expansion:
- `expansion.py:29` `basecase(matrix, nodecnt)` -> **labels the trivial REL**.
- `expansion.py:53` `expand(matrix, nodecnt, cntrs)` -> **pops one record, main driver**.
- `expansion.py:73` `get_case(matrix, nodecnt, cntr)` -> normalises `mut_nbrs` order and
  returns one of the ten case functions.
- `expansion.py:178` `handle_orig_nbrs(...)` -> hands the merged-in edges back.
- `expansion.py:203, 253, 275, 297, 345, 393, 424, 456, 506, 528` `case_a` .. `case_j`.

Callers:
- `inputgraph.py:32-33` imports (`cntr`, `exp`).
- `inputgraph.py:304-312` (`irreg_single_dual`), `inputgraph.py:764-772`
  (`door_connectivity2`, dead), `inputgraph.py:1427-1434` (`generate_multiple_rel`).

---

## Data Structures

### The REL is one matrix, not two

There is **no separate T1 matrix and T2 matrix inside this unit**. Both relations
live in the single `nodecnt x nodecnt` integer numpy array called `matrix` (and
`self.matrix` / `news_matrix` / `rel_matrix` at the call sites). Entry semantics:

| `matrix[u][v]` | meaning |
| --- | --- |
| `0` | no edge, or the reverse direction of a labelled edge |
| `1` | edge present, not yet labelled (input adjacency; also the four outer NEWS cycle edges, permanently) |
| `2` | directed edge `u -> v` in the **T1 / label-2** relation |
| `3` | directed edge `u -> v` in the **T2 / label-3** relation |

A labelled edge is stored **one-directional**: when `basecase` sets
`matrix[node][nodecnt-4] = 2` it immediately sets `matrix[nodecnt-4][node] = 0`
(expansion.py:42-43). Every case function follows the same discipline, and helpers
therefore always test both orientations, e.g. `opr.ordered_nbr_label` at
operations.py:132 (`matrix[centre][next] == 2 or matrix[next][centre] == 2`).

### Orientation convention (anchored)

`basecase` (expansion.py:39-49) is the ground truth for orientation. For every
interior vertex `node` still adjacent to N:

```
matrix[node][nodecnt-4] = 2   # node -> N   (expansion.py:42)
matrix[nodecnt-2][node] = 2   # S -> node   (expansion.py:44)
matrix[node][nodecnt-3] = 3   # node -> E   (expansion.py:46)
matrix[nodecnt-1][node] = 3   # W -> node   (expansion.py:48)
```

So:

- **Label 2 = T1 = the South-to-North relation (bottom to top).**
- **Label 3 = T2 = the West-to-East relation (left to right).**

This is confirmed downstream, not just inferred: `dual.populate_t1_matrix` starts its
DFS at `nodecnt - 2` (South) and terminates at `nodecnt - 4` (North)
(dual.py:34-35, dual.py:82), collecting children via `matrix[centre][child] == 2`
(dual.py:133); `dual.populate_t2_matrix` starts at `nodecnt - 1` (West) and
terminates at `nodecnt - 3` (East) (dual.py:152-153, dual.py:196), collecting
children via `matrix[centre][child] == 3` (dual.py:229).

Note for readers coming from the literature: **this codebase's "T1" is the vertical
(bottom-to-top) relation, not the horizontal one.** Geometrically T1's path bundle
fixes x and width (`rdg.py:82-83` reads `t1_matrix`), and T2's fixes y and height
(`rdg.py:88-89`). The names `t1_matrix` / `t2_matrix` in `rdg.py:43-45` are *not*
the relations; they are the derived path-index grids built by `dual.py`.

### The four NEWS vertices

They occupy the **last four indices**, in the order N, E, S, W:
`news.add_news` (news.py:249) allocates a matrix 4 larger (news.py:263-264) and wires
`bdy[0] -> nodecnt` (N), `bdy[1] -> nodecnt+1` (east), `bdy[2] -> nodecnt+2` (south),
`bdy[3] -> nodecnt+3` (west) (news.py:265-268). After `nodecnt += 4` at the call site
(inputgraph.py:301, inputgraph.py:1426) they are `nodecnt-4 = N`, `nodecnt-3 = E`,
`nodecnt-2 = S`, `nodecnt-1 = W`, exactly as `basecase` and `dual.py` assume.

Their participation:
- They are **never contracted**: `goodnodes` iterates `range(matrix.shape[0] - 4)`
  (contraction.py:47) and `is_goodvertex` re-guards with the same bound
  (contraction.py:63).
- They are **never a merge target**: `cntr_nbr` skips any `nbr > matrix.shape[0]-5`
  (contraction.py:97-98).
- The four outer-cycle edges N-W, W-S, S-E, N-E written by `connect_news`
  (news.py:240-247) are never relabelled. `basecase` excludes `nodecnt-3` and
  `nodecnt-1` from its loop (expansion.py:40-41) and N-S is not an edge, so those four
  entries stay `1` forever. They are invisible to `opr.order_nbrs`, which only
  collects entries equal to 2 or 3 (operations.py:164-167).

### The contraction record

`contract` builds `cntrs`, a plain Python list used as a **LIFO stack**
(appended at contraction.py:214-217, popped at expansion.py:64). Each element is a
dict with exactly four keys (contraction.py:214-217):

```python
{'node':      node,                              # the vertex being deleted
 'nbr':       nbr,                               # the vertex it is merged INTO (retained)
 'mut_nbrs':  mut_nbrs,                          # np array, the 2 common neighbours (the contracted edge's triangle)
 'node_nbrs': np.where(matrix[node] == 1)[0]}    # snapshot of ALL of node's neighbours, taken BEFORE the merge
```

`node_nbrs` is captured at contraction.py:217, one line **before** `update_adjmat`
mutates the matrix at contraction.py:218. That ordering is load-bearing.

The matrix is never resized. A contracted `node` simply has an all-zero row/column
and `degrees[node] = 0` (contraction.py:158).

---

## Algorithm Walkthrough

### 1. Eligibility: what is a "good vertex"

`is_goodvertex` (contraction.py:52-82), quoted:

```python
if node < matrix.shape[0] - 4:                 # 63: interior indices only, never NEWS
    if degrees[node] == 5:                     # 64
        ... heavy_nbrcnt counted over degrees[nbr] >= 20   # 66-69
        if heavy_nbrcnt <= 1: return True      # 70-71
    elif degrees[node] == 4:                   # 72
        ... heavynbr collected over degrees[nbr] >= 20     # 74-77
        if (len(heavynbr) <= 1) \
        or (len(heavynbr) == 2
            and matrix[heavynbr[0]][heavynbr[1]] != 1):    # 78-80
            return True
return False                                   # 82
```

So the test is: **degree exactly 4 or exactly 5**, index in the interior range, plus a
"heavy neighbour" restriction with a hard-coded threshold of degree >= 20
(contraction.py:68, contraction.py:76). Degree 5 allows at most one heavy neighbour;
degree 4 allows at most one, or two provided the two heavy neighbours are
**not adjacent to each other** (contraction.py:80). There is no outer-face test beyond
the index bound, and no separating-triangle test here.

### 2. The separating-triangle test lives in `cntr_nbr`

`cntr_nbr` (contraction.py:84-122) scans `node`'s neighbours in ascending index order
and returns the first one that is safe to merge into:

- skip the four NEWS vertices (contraction.py:97-98);
- compute `mut_nbrs = intersect1d(nbrs, node_nbrs)`, the common neighbours
  (contraction.py:101-103). If the count is not 2 it only **prints**
  `"Input graph might contain a complex triangle."` and keeps going
  (contraction.py:104-105);
- for every other neighbour `vertex` of `node`, intersect `vertex`'s neighbourhood
  with `nbr`'s neighbourhood; if any common vertex is outside `mut_nbrs ∪ {node}`,
  the candidate is rejected (contraction.py:106-119). This is exactly the "merging
  `node` into `nbr` must not create a multi-edge or a separating triangle" condition.
- returns `(-1, [])` when no neighbour qualifies (contraction.py:122).

### 3. The merge

`update_adjmat` (contraction.py:124-141): zero out every edge incident to `node`, and
connect each of `node`'s other neighbours to `nbr`. `nbr` is **retained**, `node` is
**removed**.

`update_degrees` (contraction.py:143-158): `degrees[nbr] += degrees[node] - 4`,
`degrees[mut_nbrs[0]] -= 1`, `degrees[mut_nbrs[1]] -= 1`, `degrees[node] = 0`.

### 4. The contraction loop and its termination condition

```python
cntrs = []                       # 201
gd = deque(goodnodes); gd_set = set(goodnodes)   # 202-203
attempts = len(gd)               # 204
while attempts > 0:              # 205
    node = gd.popleft(); gd_set.discard(node)    # 206-207
    nbr, mut_nbrs = cntr_nbr(matrix, node)       # 208
    if nbr == -1:                # 209
        gd.append(node); gd_set.add(node); attempts -= 1; continue   # 210-213
    cntrs.append({...})          # 214-217
    update_adjmat(...); update_degrees(...)      # 218-219
    check(..., nbr); check(..., mut_nbrs[0]); check(..., mut_nbrs[1])  # 220-222
    attempts = len(gd)           # 223
goodnodes[:] = list(gd); return matrix, degrees, goodnodes, cntrs      # 224-225
```

**The termination condition is not "the graph is down to N, E, S, W plus one interior
vertex".** It is purely "one full rotation through the current candidate deque
produced no contraction" (the `attempts` counter, contraction.py:204, 212, 223).
There is no check on the residual node count, no assertion, no exception, and no error
return: `contract` always returns normally (contraction.py:225).

The intended irreducible graph is the four NEWS vertices plus a single interior vertex
adjacent to all four; that is what `basecase` is written for. If contraction stalls
earlier, nothing detects it (see Failure Modes).

`check` (contraction.py:160-185) only refreshes candidate membership for `nbr` and the
two mutual neighbours, i.e. exactly the three vertices whose degree changed.

### 5. Base case

`basecase` (expansion.py:39-50) walks every `node` with `matrix[nodecnt-4][node] == 1`
excluding E and W, and applies the four assignments quoted in Data Structures. On the
intended irreducible graph that is one vertex and produces the trivial REL.

### 6. Expansion driver

`expand` (expansion.py:53-70):

```python
cntr = cntrs.pop()                                # 64  LIFO: reverse of contraction order
case = get_case(matrix, nodecnt, cntr)            # 65  may SWAP cntr['mut_nbrs'] in place
matrix = case(matrix, nodecnt, nbr, node,
              cntr['mut_nbrs'][0], cntr['mut_nbrs'][1], cntr['node_nbrs'])   # 68-69
```

Note the ordering subtlety: `get_case` mutates `cntr['mut_nbrs']` (expansion.py:107,
119, 122, 131, 143, 147, 158, 161, 168, 172) and the swapped order is what line 68-69
reads. `get_case` is a **normaliser as much as a dispatcher**.

`handle_orig_nbrs` (expansion.py:178-200) is called first inside every case body. For
each `alpha` in the recorded `node_nbrs` other than `nbr`, `mut_nbr1`, `mut_nbr2`, it
moves the label from the `nbr`-`alpha` edge onto the `node`-`alpha` edge, preserving
both direction and colour, and zeroes the old entry (expansion.py:192-199). That is
how the reinserted vertex takes back the neighbours it had donated to `nbr`. The only
edges left undecided are the three of the triangle `node`, `nbr`, `mut_nbr1`,
`mut_nbr2`, and those are what the case body assigns.

### 7. The case analysis in `get_case` (expansion.py:99-175)

Dispatch is on the label **and direction** of the two edges `nbr`-`mut_nbr1` and
`nbr`-`mut_nbr2`. Four top-level blocks x four sub-branches = 16 raw combinations,
collapsed to ten cases by swapping `mut_nbrs[0]` and `mut_nbrs[1]`:

| block | raw config (`nbr`-`mut1`, `nbr`-`mut2`) | swap? | case | line |
| --- | --- | --- | --- | --- |
| 1 (99) | 2 out, 3 out | no | `case_a` | 101 |
| 1 | 2 out, 2 out | rotational walk 103-108 | `case_b` | 109 |
| 1 | 2 out, 3 in | no | `case_d` | 111 |
| 1 | 2 out, 2 in | no | `case_f` | 113 |
| 2 (117) | 2 in, 3 out | yes (119) | `case_e` | 120 |
| 2 | 2 in, 2 out | yes (122) | `case_f` | 123 |
| 2 | 2 in, 3 in | no | `case_h` | 125 |
| 2 | 2 in, 2 in | walk 127-132 | `case_i` | 133 |
| 3 (137) | 3 out, 3 out | walk 139-144 | `case_c` | 145 |
| 3 | 3 out, 2 out | yes (147) | `case_a` | 148 |
| 3 | 3 out, 3 in | no | `case_g` | 150 |
| 3 | 3 out, 2 in | no | `case_e` | 152 |
| 4 (156) | 3 in, 3 out | yes (158) | `case_g` | 159 |
| 4 | 3 in, 2 out | yes (161) | `case_d` | 162 |
| 4 | 3 in, 3 in | walk 164-169 | `case_j` | 170 |
| 4 | 3 in, 2 in | yes (172) | `case_h` | 173 |

("out" = directed away from `nbr`, i.e. `matrix[nbr][mut] == L`; "in" =
`matrix[mut][nbr] == L`.)

After normalisation each case sees a canonical configuration. This is the checkable
core of the dispatcher:

| case | canonical config after `get_case` |
| --- | --- |
| A | `nbr -> mut1 : 2`, `nbr -> mut2 : 3` |
| B | `nbr -> mut1 : 2`, `nbr -> mut2 : 2` |
| C | `nbr -> mut1 : 3`, `nbr -> mut2 : 3` |
| D | `nbr -> mut1 : 2`, `mut2 -> nbr : 3` |
| E | `nbr -> mut1 : 3`, `mut2 -> nbr : 2` |
| F | `nbr -> mut1 : 2`, `mut2 -> nbr : 2` |
| G | `nbr -> mut1 : 3`, `mut2 -> nbr : 3` |
| H | `mut1 -> nbr : 2`, `mut2 -> nbr : 3` |
| I | `mut1 -> nbr : 2`, `mut2 -> nbr : 2` |
| J | `mut1 -> nbr : 3`, `mut2 -> nbr : 3` |

The four **symmetric** configurations (B, C, I, J: both edges same colour and same
direction) cannot be distinguished by labels, so `get_case` disambiguates them by a
rotational walk around `nbr`: starting at `mut_nbr1`, step counter-clockwise
(`opr.order_nbrs(..., cw=False)`, expansion.py:90) until `mut_nbr2` is reached; if an
edge of the *other* colour is met first, swap (expansion.py:103-108 for B, 127-132 for
I, 139-144 for C, 164-169 for J). That fixes which side of `nbr` the removed vertex
sat on.

### 8. The ten case bodies

Two shapes exist. B, C, I, J are unconditional (their orientation was already fixed by
the walk). A, D, E, F, G, H additionally query the rotational successor of `mut_nbr1`
around `nbr` and test whether that successor was one of the removed vertex's original
neighbours.

| case | probe | branch predicate(s) | assignments (anchors) |
| --- | --- | --- | --- |
| **A** (203) | `ordered_nbr_label(nbr, mut_nbr1, cw=True)` (218-219) | label 2 and successor in `node_nbrs` | `mut1->node:3`, `node->mut2:3`, `nbr->node:2` (224-226) |
| A | | label 2, successor not in `node_nbrs` | `node->mut1:2`, `node->mut2:3`, `node->nbr:2`, and the `nbr`-`mut1` edge is reversed and recoloured: `nbr->mut1:=0`, `mut1->nbr:3` (230-234) |
| A | | label 3, successor in `node_nbrs` | `node->mut1:2`, `mut2->node:2`, `nbr->node:3` (239-241) |
| A | | label 3, successor not in `node_nbrs` | `nbr->mut2:=0`, `mut2->nbr:2`, `node->nbr:3`, `node->mut1:2`, `node->mut2:3` (245-249) |
| **B** (253) | none | unconditional | `mut2->node:3`, `node->mut1:3`, `nbr->node:2` (269-271) |
| **C** (275) | none | unconditional | `mut1->node:2`, `node->mut2:2`, `nbr->node:3` (291-293) |
| **D** (297) | `ordered_nbr_label(nbr, mut_nbr1, cw=False)` (312-313), the only **counter-clockwise** probe | label 2, successor in `node_nbrs` | `node->mut1:3`, `mut2->node:3`, `nbr->node:2` (318-320) |
| D | | label 2, not in | `nbr->mut1:3` (recolour, same direction), `node->mut1:2`, `mut2->node:3`, `node->nbr:2` (324-327) |
| D | | label 3, in | `node->mut1:2`, `mut2->node:2`, `node->nbr:3` (332-334) |
| D | | label 3, not in | `mut2->nbr:2` (recolour), `mut2->node:3`, `node->mut1:2`, `nbr->node:3` (338-341) |
| **E** (345) | `ordered_nbr_label(nbr, mut_nbr1, cw=True)` (360-361) | label 2, in | `node->mut1:3`, `mut2->node:3`, `node->nbr:2` (366-368) |
| E | | label 2, not in | `mut2->nbr:3` (recolour), `mut2->node:2`, `node->mut1:3`, `nbr->node:2` (372-375) |
| E | | label 3, in | `node->mut1:2`, `mut2->node:2`, `nbr->node:3` (380-382) |
| E | | label 3, not in | `nbr->mut1:2` (recolour), `node->nbr:3`, `node->mut1:3`, `mut2->node:2` (386-389) |
| **F** (393) | `ordered_nbr(nbr, mut_nbr1, cw=True)`, label ignored (408) | successor in `node_nbrs` | `node->mut1:2`, `mut2->node:2`, `nbr->node:3` (412-414) |
| F | | not in | same two T1 edges, opposite T2 direction: `node->mut1:2`, `mut2->node:2`, `node->nbr:3` (418-420) |
| **G** (424) | `ordered_nbr_label(...)[1]`, label discarded (439-440) | successor in `node_nbrs` | `node->mut1:3`, `mut2->node:3`, `node->nbr:2` (444-446) |
| G | | not in | `node->mut1:3`, `mut2->node:3`, `nbr->node:2` (450-452) |
| **H** (456) | `ordered_nbr_label(nbr, mut_nbr1, cw=True)` (471-472) | label 2, in | `node->mut1:3`, `mut2->node:3`, `node->nbr:2` (477-479) |
| H | | label 2, not in | `mut1->nbr:=0`, `nbr->mut1:3` (reverse + recolour), `mut1->node:2`, `mut2->node:3`, `nbr->node:2` (483-487) |
| H | | label 3, in | `mut1->node:2`, `node->mut2:2`, `node->nbr:3` (492-494) |
| H | | label 3, not in | `mut2->nbr:=0`, `nbr->mut2:2` (reverse + recolour), `mut1->node:2`, `mut2->node:3`, `nbr->node:3` (498-502) |
| **I** (506) | none | unconditional | `mut1->node:3`, `node->mut2:3`, `node->nbr:2` (522-524) |
| **J** (528) | none | unconditional | `node->mut1:2`, `mut2->node:2`, `node->nbr:3` (543-546) |

Reading of the two-way probe: the "successor in `node_nbrs`" branches insert `node` on
the side where it still owns the surrounding fan, so only the three triangle edges need
labels. The "not in `node_nbrs`" branches additionally **rotate a label around `nbr`**
(the extra assignments that touch `nbr`-`mut1` or `nbr`-`mut2` and are not incident to
`node` at all) to keep `nbr`'s own four blocks contiguous after `node` steals part of
its fan.

`case_f` and `case_g` are the degenerate pairs: both branches assign the same two
outer edges and differ only in the direction of the `node`-`nbr` edge (expansion.py:414
vs 420; 446 vs 452).

---

## Invariants And Preconditions

**Preconditions on entry to `contract`:**

1. `matrix` is a PTPG adjacency matrix with entries in `{0, 1}` only, already
   4-completed, so the last four indices are N, E, S, W in that order
   (news.py:263-268, inputgraph.py:299-301 / 1424-1426).
2. `degrees` and `goodnodes` were produced from the *same* matrix
   (inputgraph.py:1427-1429). `contract` mutates both in place.
3. Every interior edge is in exactly one triangle pair, i.e. any two adjacent vertices
   have exactly 2 common neighbours. `cntr_nbr` only warns when this fails
   (contraction.py:104-105).

**Invariants maintained during contraction:**

4. NEWS vertices are never deleted and never merged into (contraction.py:47, 63, 97-98).
5. `cntrs` is a strict stack; `expand` must consume it fully and in reverse
   (expansion.py:64, driven by `while len(cntrs) != 0` at inputgraph.py:311-312 /
   771-772 / 1433-1434).

**Invariants the labelling must satisfy at every expansion step:**

6. Every labelled edge is stored one-directional: at most one of `matrix[u][v]`,
   `matrix[v][u]` is nonzero once labelled. Every case body that reverses an edge
   explicitly zeroes the old entry (expansion.py:233-234, 245-246, 483-484, 498-499);
   the ones that only recolour without reversing do not (expansion.py:324, 338, 372,
   386), which is correct only because direction is unchanged there.
7. **The four-block invariant.** Around each interior vertex, in rotational order, the
   incident edges must form four contiguous, **nonempty** groups: incoming T2 (3 in),
   outgoing T1 (2 out), outgoing T2 (3 out), incoming T1 (2 in), in cyclic order.
   **Nothing in contraction.py or expansion.py checks this.** It is silently assumed
   by three places:
   - `opr.order_nbrs` orientation fix-up, which finds the block boundary by scanning
     runs (operations.py:187-206);
   - `dual.get_t1_ordered_children`, which does `while matrix[ordered_nbrs[index]][centre]
     != 3: index = (index + 1) % len(...)` then skips the whole incoming-3 run then
     collects the outgoing-2 run (dual.py:129-135);
   - `dual.get_t2_ordered_children`, the analogous walk for label 3 (dual.py:225-231).

   All three are unbounded modular `while` loops. A vertex missing any one of the four
   groups makes them spin forever. This is the enforcement mechanism: **hang, not
   error**.
8. The four outer NEWS cycle edges stay at value `1` and are ignored by every
   rotational helper (operations.py:164-167).

---

## Failure Modes

1. **Contraction stalls before the graph is trivial. Silent corruption, not an
   exception.** `contract` exits as soon as one full pass of the deque yields no
   contraction (contraction.py:205, 212, 223); it never inspects how many interior
   vertices remain and never raises. `basecase` then loops over **every** node still
   adjacent to N (expansion.py:39-41) and labels each of them as if it were the unique
   central vertex. The result is a matrix that is not a REL. The symptom surfaces much
   later, usually as a hang inside `dual.get_t1_ordered_children` / `get_t2_ordered_children`
   (dual.py:129-135, 225-231) or as garbage room rectangles from `rdg.get_dimensions`
   (rdg.py:76-89). This is the classic failure mode asked about: **no infinite loop and
   no exception in contraction itself, an infinite loop downstream.**

2. **`get_case` falls through to `print("ERROR")` and returns `None`**
   (expansion.py:114-115, 134-135, 153-154, 174-175). The caller then executes
   `case(...)` at expansion.py:68 and dies with
   `TypeError: 'NoneType' object is not callable`. This is the only hard error path in
   the unit, and it triggers when an edge between `nbr` and a mutual neighbour is
   unlabelled (value 0 or 1 in both directions) at expansion time.

3. **"Input graph might contain a complex triangle."** `cntr_nbr` prints this
   (contraction.py:105) and continues regardless. If `len(mut_nbrs) < 2`, the very next
   step `update_degrees` indexes `mut_nbrs[0]` and `mut_nbrs[1]` (contraction.py:156-157)
   and raises `IndexError`; `expand` would likewise index `cntr['mut_nbrs'][0..1]`
   (expansion.py:69). If `len(mut_nbrs) > 2`, the extras are silently dropped and the
   labelling is wrong. The warning is not a guard.

4. **Stale candidate set can cause a premature stall.** After a merge, `check` is called
   only for `nbr`, `mut_nbrs[0]`, `mut_nbrs[1]` (contraction.py:220-222). But
   `is_goodvertex` also depends on *neighbours'* degrees crossing the heavy threshold of
   20 (contraction.py:68, 76). When `degrees[mut_nbrs[i]]` drops below 20
   (contraction.py:156-157), vertices adjacent to it may become good and are never
   re-added to the deque. That makes failure mode 1 reachable on graphs where a full
   contraction does exist.

5. **Rotational walks in `get_case` assume `mut_nbr2` is in `nbr`'s labelled
   neighbourhood.** The walks at expansion.py:104-108, 128-132, 140-144, 165-169 loop
   `while vertex != mut_nbr2` over `_nbr_ord` (built at expansion.py:90 from labelled
   edges only). If `mut_nbr2` never appears, the loop never terminates.

6. `handle_orig_nbrs` moves whatever is in `matrix[nbr][alpha]` including the value `1`
   (expansion.py:194-199), so an unlabelled leftover edge is silently propagated rather
   than flagged.

---

## Coupling (what breaks if you change this)

- **Label-to-direction meaning (2 = S-to-N, 3 = W-to-E)** is hard-coded in at least
  five places outside this unit: `dual.populate_t1_matrix` / `get_t1_ordered_children`
  (dual.py:34-35, 129-135), `dual.populate_t2_matrix` / `get_t2_ordered_children`
  (dual.py:152-153, 225-231), `operations.order_nbrs` (operations.py:164-206),
  `operations.ordered_nbr_label` (operations.py:132), and all of `flippable.py`
  (flippable.py:34-62, 130-144, 162-178). Swapping 2 and 3 breaks every one of them.
- **NEWS index layout (last four = N, E, S, W)** is assumed by `basecase`
  (expansion.py:40-49), `contraction.goodnodes` / `cntr_nbr` (contraction.py:47, 97),
  `operations.order_nbrs` special cases (operations.py:181-186), and `dual.py`
  (dual.py:35, 82, 153, 196). It is produced by `news.add_news` (news.py:265-268).
- **One-directional storage of labelled edges.** `opr.ordered_nbr_label`
  (operations.py:132) and every `A or B` orientation test in `flippable.py` assume it.
- **`cntrs` record shape.** `expand` reads exactly the keys `node`, `nbr`, `mut_nbrs`,
  `node_nbrs` (expansion.py:66-69); `get_case` mutates `mut_nbrs` in place, so it must
  remain a mutable indexable (currently a numpy array from `np.intersect1d`,
  contraction.py:101).
- **Return contract.** `contract` returns the 4-tuple
  `(matrix, degrees, goodnodes, cntrs)` (contraction.py:225), unpacked identically at
  inputgraph.py:306-307, 766-767, 1429-1430. `expand` returns just `matrix`
  (expansion.py:70).
- **Downstream consumer.** The finished REL matrix goes to
  `rdg.construct_dual(matrix, nodecnt, mergednodes, irreg_nodes)` (rdg.py:20), called at
  inputgraph.py:313, 773, 1118, 1338, 1353. `construct_dual` immediately feeds it to
  `dual.populate_t1_matrix` and `dual.populate_t2_matrix` (rdg.py:43-45) and then to
  `get_dimensions` (rdg.py:47), which derives x/width from the T1 grid (rdg.py:82-83)
  and y/height from the T2 grid (rdg.py:88-89). In the multiple-floorplan path the same
  matrix is also stored as `self.rel_matrix_list` (inputgraph.py:1003-1004, 1088-1089)
  and re-read by `opr.get_encoded_matrix` in `single_floorplan`
  (inputgraph.py:811-814).

### Where nondeterminism enters (question 7)

**Not in this unit.** Contraction is fully deterministic given the input matrix:

- `goodnodes` produces candidates in ascending index order (contraction.py:47-49);
- the deque evolves deterministically (contraction.py:206, 210, 223);
- `cntr_nbr` returns the **first** contractible neighbour in ascending index order
  (`np.where` output is sorted, contraction.py:95-96, 121);
- there is no `random`, no set iteration over unordered keys, and no hashing-dependent
  ordering in either file (`gd_set` is used only for membership tests,
  contraction.py:174-180).

So `contract` + `basecase` + `expand` yields **exactly one REL** per input. Call-site
evidence: `generate_multiple_rel` seeds its list with that single matrix
(`rel_matrix.append(news_matrix)`, inputgraph.py:1436) and every additional REL comes
from `flippable.py`: `flp.get_flippable_edges` / `get_flippable_vertices`
(inputgraph.py:1438-1440) and `flp.resolve_flippable_edge` /
`resolve_flippable_vertex` (inputgraph.py:1442, 1446-1447), deduplicated by
`np.array_equal` (inputgraph.py:1443, 1448). The `for mat in rel_matrix:` loop at
inputgraph.py:1437 iterates a list that is appended to inside the body, so it is a
breadth-first closure over the flip graph, not a single round.

The second source of REL variety is **not** tie-breaking either: it is the choice of
boundary, `for bdys in selected_list` (inputgraph.py:981, 1067), each `bdys` giving a
different N/E/S/W attachment before contraction runs. The only genuine randomness in the
neighbourhood is `randint` in shortcut removal (inputgraph.py:284 in
`irreg_single_dual`, inputgraph.py:744 in the dead `door_connectivity2`); it is absent
from `irreg_multiple_dual` and from `generate_multiple_rel`.

Answer: **multiple RELs come from `flippable.py` plus multiple boundaries, not from
contraction tie-breaking.**

---

## Dead Or Duplicated Code

- **`InputGraph.door_connectivity2` (inputgraph.py:650) is dead.** Its contraction and
  expansion block (inputgraph.py:764-772) plus the `rdg.construct_dual` call
  (inputgraph.py:773) are unreachable. A repo-wide Grep for `door_connectivity2` finds
  only the `def` at inputgraph.py:650, the identical copy under `gplan_backend/`, and
  knowledge-graph artifacts under `graphify-out/`. No caller.
- **`InputGraph.door_connectivity` (inputgraph.py:340) contains a fully commented-out
  copy** of the same contraction / expansion / `construct_dual` block
  (inputgraph.py:583-593). It is a stale duplicate of inputgraph.py:304-315.
- **`contraction.check`'s non-set branch (contraction.py:181-185) is unreachable from
  `contract`**, which always passes `gd_set` (contraction.py:220-222). It is a
  compatibility shim for the pre-optimisation signature.
- **`gplan_backend/GPLAN/GPLAN/source/floorplangen/contraction.py` and `expansion.py`
  are byte-identical** to the primary copies (verified with `diff -q`, no output). That
  directory is the backend's submodule checkout of the same engine, not a fork.
- **Other importers of this unit, all outside the api.py / handlers.py flow:**
  `GPLAN/GPLAN/bdy.py:13-14`, `source/trial/bdy.py:13-14`,
  `source/lettershape/{ushape,zshape,tshape}/*.py` and
  `source/lettershape/lshape/Lshaped.py:19-20`,
  `source/staircaseshape/staircaseshape.py:14-15`, and
  `source/polygonal/lshape.py:11-12`. The last one uses flat imports
  (`import contraction as cntr`) that cannot resolve when the project is imported as a
  package, so that module is not loadable from the served pipeline. The lettershape
  modules are pulled into `inputgraph`'s namespace by the star imports at
  inputgraph.py:16-19 but their floorplan entry points are commented out at
  inputgraph.py:1485-1494.
- **`expansion.basecase`'s loop over `range(matrix.shape[0])` (expansion.py:39)** is
  wider than necessary for the intended irreducible graph (one vertex); it is only
  meaningful, and then harmful, when contraction stalled.

---

## Open Questions

1. **Naming clash with the literature and with `rdg.py`.** In this codebase T1 is the
   vertical (S-to-N, label 2) relation, while much of the REL literature calls the
   horizontal one T1. Anyone reading `rdg.py:43-45` should also note that `t1_matrix` /
   `t2_matrix` there are path-index grids built by `dual.py`, not the relations
   themselves. Worth a comment in the source; not a bug.
2. **Is the heavy-vertex threshold of 20 (contraction.py:68, 76) tuned or arbitrary?**
   It is the only magic number in the eligibility test and it directly controls how
   often contraction stalls. No comment or reference in the file.
3. **Does `contract` provably reach the trivial graph on every valid PTPG produced by
   the upstream stages?** The theory says yes for a 4-connected triangulation, but the
   stale-candidate gap in failure mode 4 means the implementation does not obviously
   inherit that guarantee. There is no test, assertion, or logging that would show a
   stall in production.
4. **`case_d` is the only case that probes counter-clockwise** (`False` passed
   positionally at expansion.py:313) while A, E, F, G, H all use `cw=True`. Given that
   D and E are mirror configurations (`2 out / 3 in` vs `3 out / 2 in`), this asymmetry
   is plausibly intentional but is undocumented. If it is a typo, the effect would be a
   wrong label choice only in the sub-case where D's clockwise and counter-clockwise
   successors disagree, which would show up as a downstream hang rather than an error.
5. **Knowledge-graph disagreement.** `graphify explain "contraction"` lists importers
   `Lshaped.py`, `lshape.py`, `tshape.py`, `ushape.py`, `zshape.py`,
   `staircaseshape.py`, `trial/bdy.py` but **omits `source/inputgraph.py:32`**, which is
   the only importer on the live path. Grep confirms the import exists. Follow the code:
   the graph's import edge set for this node is incomplete.
