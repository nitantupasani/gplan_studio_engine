# dim-02: Dimensioning hooks on `InputGraph`

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py`
Scope: only the dimensioning hand-off. Dual construction, boundary enumeration and REL generation are out of scope except where they set up the solver arguments.

## Purpose

`InputGraph` owns the graph and the set of candidate rectangular duals. Two of its methods, `single_floorplan` and `multiple_floorplan`, are the only places in the class that call into `GPLAN/source/dimensioning`. They take a dimensionless candidate (integer grid layout), encode it as a cell matrix, and hand that matrix plus per-room dimension constraints to the LP dimensioner (`floorplan_to_st` -> `convert_adj_equ_sym` -> `scipy.optimize.linprog`). The returned widths and heights overwrite `room_width` / `room_height`, and x/y are then recomputed from the horizontal digraph.

Critical framing fact: **`minimum_dimensioning.py` is never imported or called from `inputgraph.py`.** The import list is `inputgraph.py:11-44`; the only two dimensioning imports are:

- `inputgraph.py:39` `from GPLAN.source.dimensioning import floorplan_to_st as fpts`
- `inputgraph.py:43` `from GPLAN.source.dimensioning import block_checker as bc`

The min-dim solver (`min_dim.main`) is driven entirely from `handlers.py` (import at `handlers.py:9`, call sites at `handlers.py:346`, `handlers.py:352`, `handlers.py:390`, `handlers.py:834`, `handlers.py:1250`, `handlers.py:1394`, and inside the door-connectivity loops around `handlers.py:2120`). Handlers reads `graph.graph_list[i].room_*` and writes results back onto those objects (`handlers.py:417-421`, `handlers.py:2145-2149`). So there are two distinct dimensioning paths and only the older LP path is an `InputGraph` method.

## Where It Sits In The Pipeline

```
handlers.py: dimgui.gui_fnc(...)             -> min_width/max_width/min_height/max_height/symm/min_ar/max_ar/plot_w/plot_h
handlers.py: graph.oneconnected_dual("multiple")  (or graph.irreg_multiple_dual())
                                             -> self.rel_matrix_list, per-candidate room_x/room_y/room_width/room_height
handlers.py: graph.single_floorplan(...)     -> inputgraph.py:779
    opr.get_encoded_matrix                   -> inputgraph.py:813
    bc.block_checker                         -> inputgraph.py:817
    fpts.floorplan_to_st                     -> inputgraph.py:821   <== the solver hand-off
        convert_adj_equ_sym (x2)             -> floorplan_to_st.py:103-106
        solve_linear (scipy linprog x2)      -> floorplan_to_st.py:108
    dual.get_coordinates                     -> inputgraph.py:838
    opr.calculate_area                       -> inputgraph.py:843
handlers.py: while graph.floorplan_exist == False: re-prompt and retry (handlers.py:623, 926, 1168)
```

The parallel min-dim path (production door-connectivity) never enters `InputGraph`: `handlers.py:2101-2121` builds `floorplan_data` from `graph.graph_list[i]` and calls `solve_min_dim`, then `graph.scale_plot_dimension(...)` at `handlers.py:2173` and `handlers.py:2619`.

## Entry Points (file:line)

| Entry | Location |
| --- | --- |
| `InputGraph.single_floorplan(min_width, min_height, max_width, max_height, symm_rooms, min_ar, max_ar, plot_width, plot_height)` | `inputgraph.py:779-780` |
| `InputGraph.multiple_floorplan(same signature)` | `inputgraph.py:1126-1127` |
| `InputGraph.scale_plot_dimension(plot_width, plot_height, valid)` | `inputgraph.py:597` |
| `InputGraph.irreg_multiple_dual(input_dims=[])` (plot-aware boundary pre-selector) | `inputgraph.py:852`, uses `input_dims` at `inputgraph.py:967-973` and `inputgraph.py:1052-1058` |
| Solver call: `bc.block_checker` | `inputgraph.py:817-818`, `inputgraph.py:1164-1165` |
| Solver call: `fpts.floorplan_to_st` | `inputgraph.py:821-823`, `inputgraph.py:1167-1169` |

External callers:
- `single_floorplan`: `handlers.py:621`, `handlers.py:628`, `handlers.py:924`, `handlers.py:931`, `handlers.py:1004`, `handlers.py:1166`, `handlers.py:1173`
- `multiple_floorplan`: `handlers.py:1069`, `handlers.py:1474`
- `scale_plot_dimension`: `handlers.py:2173`, `handlers.py:2619`

## Data Structures

### 1. Per-room min/max width and height: not attributes

There is **no** `self.min_width`, `self.max_width`, `self.min_height`, `self.max_height`, `self.min_ar`, `self.max_ar` anywhere in `inputgraph.py`. A grep for `min_width|min_height|max_width|max_height|min_dim|max_dim` over the file returns only docstrings (`inputgraph.py:784-787`, `inputgraph.py:1131-1134`), the two method signatures, and the padding loops. `__init__` (`inputgraph.py:115-156`) initialises no dimension-constraint attribute.

Consequence: dimension constraints are **call-scoped parameters**, owned by `handlers.py`, produced by `dimgui.gui_fnc` (`handlers.py:605-606`, `handlers.py:917-918`, `handlers.py:1153-1154`, `handlers.py:1460-1461`, `handlers.py:1066`) and re-supplied on every retry.

They are, however, **mutated in place by the callee**. `single_floorplan` appends one padding entry per merged node and per extra node to the caller's own lists:

- `inputgraph.py:797-803` (merged nodes: `min_width` 0, `min_height` 0, `max_width` 10, `max_height` 10, `min_ar` 0, `max_ar` 10000)
- `inputgraph.py:804-810` (extra nodes: 0 / 0 / 10000 / 10000 / 0 / 10000)
- `multiple_floorplan` does the same at `inputgraph.py:1144-1150` and `inputgraph.py:1151-1157`, except the merged-node ceiling is 10000 rather than 10.

### 2. Attributes that hold dimensions

| Attribute | Init | Meaning |
| --- | --- | --- |
| `self.room_x`, `self.room_y` | `inputgraph.py:128-129` (`np.zeros(nodecnt)`) | lower-left corner per room |
| `self.room_height`, `self.room_width` | `inputgraph.py:130-131` (`np.zeros(nodecnt)`) | per-room extent |
| `self.area` | `inputgraph.py:136` (`[]`) | per-room area, filled at `inputgraph.py:843` |
| `self.rel_matrix_list` | `inputgraph.py:137` (`[]`) | candidate RELs, the loop domain of `single_floorplan` |
| `self.floorplan_exist` | `inputgraph.py:138` (`False`) | success flag polled by handlers |
| `self.graph_list`, `self.graph_list_by_bdy` | `inputgraph.py:147-148` | per-candidate child `InputGraph` objects |
| `self.mergednodes`, `self.irreg_nodes1/2`, `self.extranodes` | `inputgraph.py:124-126`, `inputgraph.py:134` | irregular-room bookkeeping, consumed by `calculate_area` |
| `self.floorplan_limit`, `self.floorplan_per_bdy_limit` | `inputgraph.py:139-140` | candidate caps (500, 20) |

Set from outside: the dimensionless values are written by `rdg.construct_dual` (`inputgraph.py:313-315`, `inputgraph.py:773-775`, `inputgraph.py:1118-1121`, `inputgraph.py:1338-1339`, `inputgraph.py:1353-1358`), and by `handlers.py:417-421` / `handlers.py:2145-2149` for the min-dim path. `handlers.py:978-1000` deliberately re-wraps `room_x/room_y/room_width/room_height/extranodes/mergednodes/irreg_nodes1` into single-element lists of lists before calling `single_floorplan`, with a comment stating exactly why.

### 3. The encoded matrix

`opr.get_encoded_matrix(nodecnt, room_x, room_y, room_width, room_height)` at `operations.py:211-236`. It allocates `np.zeros((mat_height, mat_width), int)` where `mat_width = int(max(x+w))` and `mat_height = int(max(y+h))` (`operations.py:225-227`) and paints `encoded_matrix[y:y+h, x:x+w] = node` for `node in range(nodecnt)` (`operations.py:232-235`).

So `E` is a **unit-cell raster of room ids**, row 0 = top (north), column 0 = left (west), each cell holding a 0-based room index. It is not an adjacency list and not a list of rooms.

## Algorithm Walkthrough (`single_floorplan`, `inputgraph.py:779-847`)

1. `inputgraph.py:797-810`: pad the six constraint lists so their length matches the room count in the encoded matrix (real rooms + merged nodes + extra nodes).
2. `inputgraph.py:811`: `for i in range(len(self.rel_matrix_list)):` iterate candidates.
3. `inputgraph.py:812-814`: raster the i-th candidate: `opr.get_encoded_matrix(rel_matrix.shape[0] - 4, self.room_x[i], self.room_y[i], self.room_width[i], self.room_height[i])`. The `- 4` strips the N/E/S/W vertices.
4. `inputgraph.py:815`: `encoded_matrix_deepcopy = copy.deepcopy(encoded_matrix)` (the pristine `encoded_matrix` is reused at line 838).
5. `inputgraph.py:817-818`: symmetry feasibility test.
6. `inputgraph.py:820-823`: if symmetry is satisfiable, run the LP.
7. `inputgraph.py:827-828`: on failure `continue` to the next candidate; `inputgraph.py:829-830` on success set `self.floorplan_exist = True`.
8. `inputgraph.py:831-834`: transpose and flatten into `self.room_width` / `self.room_height`.
9. `inputgraph.py:835`: collapse the per-candidate bookkeeping lists to the winning candidate's entry.
10. `inputgraph.py:838`: recompute coordinates from the horizontal digraph.
11. `inputgraph.py:839-842`: round x and y to 3 decimals.
12. `inputgraph.py:843-845`: compute areas.
13. `inputgraph.py:847`: `break`. First feasible candidate wins.

`multiple_floorplan` (`inputgraph.py:1126-1196`) is the same shape without the `break`, writing into `self.graph_list[i].*` instead of `self.*`, plus a trailing re-index loop at `inputgraph.py:1191-1196`.

## The Actual Constraints Or Formulas

### The exact call expression (the hand-off contract)

`inputgraph.py:821-823`:

```python
[width, height, hor_dgph, status] = fpts.floorplan_to_st(
    encoded_matrix_deepcopy, min_width, min_height, max_width, max_height, ver_list, hor_list, min_ar,
    max_ar, plot_width, plot_height)
```

Identical expression at `inputgraph.py:1167-1169`.

Argument contract (callee signature at `floorplan_to_st.py:18`). Let `R` = number of distinct rooms in the raster = `max(E) + 1`.

| # | Name | Type | Meaning / how to build it by hand |
| --- | --- | --- | --- |
| 1 | `encoded_matrix_deepcopy` | `np.ndarray[int]`, shape `(mat_height, mat_width)` | Unit-cell raster of **room ids** (0-based node indices), built at `inputgraph.py:813` by `operations.py:211-236`. Row 0 is the north edge, column 0 the west edge. Every room must occupy an axis-aligned rectangle of cells. `floorplan_to_st.py:49-51` adds 1 to every cell, then derives the vertical st-graph from column runs (`floorplan_to_st.py:57-66`) and the horizontal st-graph from row runs (`floorplan_to_st.py:82-91`). Not an adjacency list, not a room list. |
| 2 | `min_width` | `list[number]`, length `R` | Lower bound on each room's width, indexed by room id. Padded at `inputgraph.py:798`, `inputgraph.py:805`. |
| 3 | `min_height` | `list[number]`, length `R` | Lower bound on height. `p = len(min_height)` is what `solve_linear.py:53` uses as the room count, so this list defines the expected `R`. |
| 4 | `max_width` | `list[number]`, length `R` | Upper bound on width. |
| 5 | `max_height` | `list[number]`, length `R` | Upper bound on height. |
| 6 | `ver_list` | `list[list[int]]`, even length, from `block_checker` | Groups of room ids whose **widths** must sum equal, paired consecutively: element `2i` must equal element `2i+1`. Built at `block_checker.py:74-77` and `block_checker.py:84-87` from the top row of each symmetric block; returned at `block_checker.py:101`. Empty list means no symmetry. |
| 7 | `hor_list` | `list[list[int]]`, even length | Same but for **heights**, taken from the left column of each block (`block_checker.py:79-82`, `block_checker.py:89-92`). |
| 8 | `min_ar` | `list[number]`, length `R` | Minimum aspect ratio, applied as `height >= min_ar[i] * width[i]` (`solve_linear.py:93`, `solve_linear.py:99-102`). |
| 9 | `max_ar` | `list[number]`, length `R` | Maximum aspect ratio, `height <= max_ar[i] * width[i]` (`solve_linear.py:94`, `solve_linear.py:103-107`). |
| 10 | `plot_width` | number | Forwarded to `convert_adj_equ_sym(VER, ver_list, plot_width)` at `floorplan_to_st.py:103-104`. In `convert_adj_equ_sym.py:117-122`, if it is not `-1` it becomes an **equality** row: total floorplan width must equal exactly this. `-1` disables it. It is not an upper bound. |
| 11 | `plot_height` | number | Same for the horizontal system, `floorplan_to_st.py:105-106`. |

Preceding block_checker call, `inputgraph.py:817-818`:

```python
[boolean, ver_list, hor_list] = bc.block_checker(
    encoded_matrix_deepcopy, symm_rooms)
```

`symm_rooms` is a **string**, e.g. `"(1+2),(3)"`, split on commas and stripped of `+()` at `block_checker.py:5-15`; consecutive pairs are the room groups compared. An empty string still parses (one group), and `all(...)` over an empty `ret` returns True.

### What the LP actually solves

- Objective: minimise total inflow at the source, `f` set to 1 on edges leaving the north/west node (`convert_adj_equ_sym.py:59-63`).
- Flow conservation equality per internal st-graph node (`convert_adj_equ_sym.py:106-109`).
- Symmetry equalities appended (`convert_adj_equ_sym.py:83-98`, `convert_adj_equ_sym.py:112-113`).
- Inequalities: `A = vstack(-A, A)` against `b = hstack(-min, max)` (`convert_adj_equ_sym.py:76-80`, `solve_linear.py:56-62`), i.e. `min <= dim <= max` per room.
- Two independent `scipy.optimize.linprog(..., bounds=(1,None), method='interior-point')` solves, one for widths (`solve_linear.py:76`), one for heights (`solve_linear.py:140`), with the width solution feeding the aspect-ratio tightening in between (`solve_linear.py:90-129`).
- `status = ver_success and hor_success` (`solve_linear.py:153`).

### What comes back and where it is stored

`floorplan_to_st.py:114`: `return [width, height, hor_dgph, status]`, with `width`/`height` rounded to 3 decimals at `floorplan_to_st.py:111-112`.

| Return slot | Type | Stored into (single_floorplan) | Stored into (multiple_floorplan) |
| --- | --- | --- | --- |
| `width` | `np.ndarray` shape `(2R, 1)` | `self.room_width = width.flatten()` at `inputgraph.py:831`, `inputgraph.py:833` | `self.graph_list[i].room_width` at `inputgraph.py:1177`, `inputgraph.py:1179` |
| `height` | `np.ndarray` shape `(2R, 1)` | `self.room_height = height.flatten()` at `inputgraph.py:832`, `inputgraph.py:834` | `self.graph_list[i].room_height` at `inputgraph.py:1178`, `inputgraph.py:1180` |
| `hor_dgph` | `np.ndarray` `(R, R)` float | consumed, not stored: passed to `dual.get_coordinates` at `inputgraph.py:838` | `inputgraph.py:1181-1182` |
| `status` | bool | drives `self.floorplan_exist` at `inputgraph.py:830` | `status_list` at `inputgraph.py:1172`, flag at `inputgraph.py:1176` |

Coordinates are **not** returned by the solver. They are derived afterwards:

- `inputgraph.py:838`: `self.room_x, self.room_y = dual.get_coordinates(encoded_matrix, self.nodecnt + 4, self.room_width, self.room_height, hor_dgph)` (`dual.py:235-250` returns two `np.zeros(nodecnt-4)` arrays).
- `inputgraph.py:839-842`: in-place rounding to 3 decimals.
- `inputgraph.py:1181-1186`: same for the multiple variant, but with `rel_matrix.shape[0]` as the node count instead of `self.nodecnt + 4`.
- `inputgraph.py:843-845` / `inputgraph.py:1187-1189`: `self.area = opr.calculate_area(...)`.

### Length gotcha on the returned dimension vectors

`solve_linear.py:80` computes `W = (-1) * np.dot(A_VER, X1)` where `A_VER` is the stacked `vstack(A_min, A_max)` of `convert_adj_equ_sym.py:80`. That makes `W` have `2R` rows: the first `R` are the widths, the last `R` are their negatives. `solve_linear.py:82-85` slices only the first half for its internal aspect-ratio work, but `solve_linear.py:154` returns the full `W`. Therefore `self.room_width` and `self.room_height` after `inputgraph.py:833-834` have length `2R`, with the trailing `R` entries negative. The degenerate branch (`solve_linear.py:66-74`, `solve_linear.py:132-138`) has the same shape: `R` ones followed by `R` minus-ones. Downstream consumers only index `0..R-1`, so it goes unnoticed, but any `len(room_width)` or `sum(...)` over these arrays is wrong.

## Invariants And Preconditions

1. `len(min_width) == len(min_height) == len(max_width) == len(max_height) == len(min_ar) == len(max_ar) == R` where `R = max(E)+1`. Enforced only by the padding loops at `inputgraph.py:797-810`, which assume the caller supplied exactly one entry per real room.
2. `self.mergednodes` and `self.extranodes` must be **lists of lists**: `inputgraph.py:797` and `inputgraph.py:804` index `[0]`, and `inputgraph.py:835` indexes `[i]`.
3. `self.room_x`, `self.room_y`, `self.room_width`, `self.room_height` must be **lists indexed by candidate** at entry (`inputgraph.py:814` uses `self.room_x[i]`), and become flat per-room arrays on exit (`inputgraph.py:833-834`). The type of these four attributes changes across the call.
4. Room rasterisation requires integer-ish dimensionless coordinates; `operations.py:228-231` casts to int, so any pre-dimensioned float layout is silently truncated.
5. `plot_width` / `plot_height` are exact totals unless `-1` (`convert_adj_equ_sym.py:117-122`).
6. `symm_rooms` must be a string; `block_checker.py:5` calls `.split(',')` on it.
7. `self.rel_matrix_list` (single) and `self.graph_list` (multiple) define the candidate set and must be aligned index-for-index with the per-candidate geometry lists.

## Failure Modes

At this layer there is **no try/except and no exception raised**. Failure is a flag plus a skip:

- Symmetry infeasible: `inputgraph.py:825-826` sets `status = False` without calling the LP.
- LP infeasible: `status` comes back False from `solve_linear.py:153`.
- Either way: `inputgraph.py:827-828` `if (status == False): continue`, i.e. the candidate is skipped silently. `multiple_floorplan` records it in `status_list` first (`inputgraph.py:1172-1174`).
- Success: `self.floorplan_exist = True` (`inputgraph.py:830`, `inputgraph.py:1176`).
- If every candidate fails, `floorplan_exist` stays `False` from `inputgraph.py:138` and the method returns normally, leaving `self.room_width` etc. at their pre-call values.
- The caller is responsible for the retry: `handlers.py:623-629`, `handlers.py:926-932`, `handlers.py:1168-1174` all loop `while (graph.floorplan_exist == False)`, re-prompt via `dimgui.gui_fnc`, regenerate duals and call again. There is no iteration cap, so a headless caller with a non-interactive `gui_fnc` would spin forever.
- `floorplan_exist` is never reset to `False` between calls, so once one candidate succeeds the retry loop can never re-trigger even if a later call fails.
- Solver-side noise: `solve_linear.py:113-114` prints "For the given aspect ratio constraints and dimensions room cannot be drawn" and silently falls back to dimensions-only bounds rather than failing. `inputgraph.py:819` and `inputgraph.py:824` print the raw solver output on every candidate.

Latent crashes rather than clean failures:

- `inputgraph.py:797` `len(self.mergednodes[0])` raises `IndexError` when `self.mergednodes` is `[]`. `irreg_multiple_dual` never assigns `self.mergednodes` as a list of lists (it keeps them local at `inputgraph.py:939-945` and attaches them to the child graphs at `inputgraph.py:1005-1007`; the only self-assignment is the empty `[]` at `inputgraph.py:876`). So the sequences `graph.irreg_multiple_dual()` then `graph.single_floorplan(...)` at `handlers.py:923-924`, `handlers.py:930-931`, `handlers.py:615-621` and `handlers.py:1161-1166` cannot work. `single_floorplan` is only viable after `oneconnected_dual("multiple")` (which builds the list-of-lists shape at `inputgraph.py:1342-1362`) or after the manual re-wrap at `handlers.py:980-1000`.
- Even if step 1 passed, `self.room_x[i]` at `inputgraph.py:814` would be a scalar after `irreg_multiple_dual`, because that method writes geometry onto `graph_list_by_bdy[i][cnt]` (`inputgraph.py:1118-1121`), never onto `self.room_x`.
- `handlers.py:1172` calls `graph.multiple_dual()`. No such method exists on `InputGraph` (full method list: `inputgraph.py:115, 168, 181, 202, 316, 340, 597, 650, 779, 849, 852, 1126, 1200`). That retry branch raises `AttributeError`.

## Coupling (what breaks if you change this)

- **Encoded-matrix format.** `operations.py:211-236` is shared by `inputgraph.py:813`, `inputgraph.py:1161`, `inputgraph.py:1305-1309` and by handlers' min-dim path (`handlers.py:381`, `handlers.py:2104`). Changing the raster convention (room ids, row/column origin) breaks both dimensioning families and `dual.get_coordinates`.
- **Constraint list length.** Any change to how merged/extra nodes are appended (`inputgraph.py:797-810`) must stay in sync with `max(E)+1`, otherwise `solve_linear.py:53` sizes `p` wrong and the aspect-ratio loops at `solve_linear.py:92-107` go out of range.
- **In-place mutation of caller lists.** `single_floorplan` and `multiple_floorplan` append to the caller's `min_width`/`max_ar` lists. `handlers.py:624` and `handlers.py:927` then reuse those same (now longer) lists as `old_dims` for the retry prompt, and `handlers.py:633` publishes them as `dim_constraints`. Making the padding non-mutating would change what handlers sees; keeping it means repeated calls keep growing the lists.
- **Attribute type flip.** Everything downstream of `single_floorplan` (`get_final_traversal` at `inputgraph.py:1580`, drawing, catalogue export) assumes `room_width` is flat after the call and per-candidate before it. `handlers.py:978-1000` exists solely to satisfy the before-shape.
- **`floorplan_exist` semantics.** Three handler loops poll it (`handlers.py:623`, `handlers.py:926`, `handlers.py:1168`). Changing it to raise instead would need all three rewritten.
- **`plot_width` meaning.** It is an exact equality here (`convert_adj_equ_sym.py:117-122`) but an upper cap / expand-only target in the min-dim path (`inputgraph.py:612-619` in `scale_plot_dimension`, and `handlers.py:2072-2079` where the plot cap is dropped and the plot is enlarged). The two paths disagree; unifying them touches both.
- **`irreg_multiple_dual(input_dims)`.** The plot-aware boundary pre-selector `dim_on_paths_bdy` (`path_map.py:99`, called at `inputgraph.py:972-973` and `inputgraph.py:1057-1058`) narrows the candidate pool by min room dims and plot size *before* any solver runs, and is deliberately bypassed under cardinal constraints (`inputgraph.py:959-966`, `inputgraph.py:1045-1051`). Changing it changes which candidates the solver ever sees, with an empty-result fallback at `inputgraph.py:978-979` and `inputgraph.py:1064-1065`.

## Dead Or Duplicated Code

Checked by grepping the whole of `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` for each name.

- **`multiple_floorplan` (`inputgraph.py:1126`): referenced but non-functional, effectively dead.** Callers exist (`handlers.py:1069`, `handlers.py:1474`), but line `inputgraph.py:1160` reads `rel_matrix = self.graph_list.rel_matrix_list` and `self.graph_list` is a plain Python list (`inputgraph.py:147`, appended at `inputgraph.py:1012` and `inputgraph.py:1096`), so the first loop iteration raises `AttributeError: 'list' object has no attribute 'rel_matrix_list'`. The trailing loop at `inputgraph.py:1191-1196` is additionally nonsense: it re-indexes `room_x` by the candidate index `i` after `inputgraph.py:1181` already replaced it with a per-room coordinate array. One caller is itself broken downstream anyway (`handlers.py:1074` iterates `range(len(graph.fpcnt))` on an int).
- **`single_floorplan` (`inputgraph.py:779`): live but reachable only through two of its seven call sites.** Working callers: `handlers.py:1004` (L-shape, with the manual list-wrap at `handlers.py:980-1000`) and `handlers.py:1166` when `oneconnected_dual("multiple")` succeeded at `handlers.py:1157`. The `irreg_multiple_dual` fallbacks (`handlers.py:615-621`, `handlers.py:923-924`, `handlers.py:930-931`, `handlers.py:1161-1166`) hit the `IndexError` described above.
- **`handlers.py:1172` `graph.multiple_dual()`: calls a method that does not exist.** Dead branch that would raise `AttributeError` the moment the first attempt fails.
- **`scale_plot_dimension` (`inputgraph.py:597`): live.** Called at `handlers.py:2173` and `handlers.py:2619`. It also shadows its own loop variable `i` at `inputgraph.py:630` inside the `for i in range(len(self.graph_list))` at `inputgraph.py:599`, which corrupts the outer index; it happens to work because the outer `i` is only used before line 630 (captured into `reorder_mapping` at `inputgraph.py:628`).
- **Duplicated `timing_decorator`:** defined at module scope (`inputgraph.py:65-73`) and again identically inside the class (`inputgraph.py:168-176`). The class-level one shadows the module one for all `@timing_decorator` uses inside the class body.
- **Large commented-out block** at `inputgraph.py:540-595`, a dead copy of the merged-node / `construct_dual` sequence, plus the dead attribute resets at `inputgraph.py:1110-1114`.
- **Duplicated dual-construction branches:** `inputgraph.py:932-1014` and `inputgraph.py:1016-1098` are near-identical bodies of `irreg_multiple_dual` (with and without ST handling), including two copies of the `input_dims` / `dim_on_paths_bdy` block.
- **`floorplan_to_st` name collision:** an unrelated `def floorplan_to_st(A, user_rooms, total_rooms)` exists at `pythongui/final.py:925`. It is not the one imported here.
- Not dead, worth naming: `self.floorplan_limit_undimensioned` (`inputgraph.py:141`) is assigned and never read anywhere in `inputgraph.py`.

## Open Questions

1. Is the `2R`-length `room_width` / `room_height` (second half negated, `solve_linear.py:80` and `solve_linear.py:154`) intentional, or should `floorplan_to_st` slice to the first half before returning? Anything computing `len()` or `sum()` over these arrays is currently wrong.
2. Is `multiple_floorplan` expected to work at all, or is the LP multiple path fully superseded by the min-dim loop in `handlers.py:2092-2160`? If superseded, `handlers.py:1069` and `handlers.py:1474` should be removed rather than left to raise.
3. Should `plot_width` / `plot_height` be an equality (current LP behaviour, `convert_adj_equ_sym.py:117-122`) or an upper cap? The min-dim path treats the plot as expandable (`handlers.py:2072-2079`, `inputgraph.py:612-619`). Callers pass `0` for "no plot" in the min-dim path (`handlers.py:1812-1813`) but the LP path expects `-1`, and I found no site that normalises between them.
4. `single_floorplan` pads merged-node `max_width`/`max_height` to 10 (`inputgraph.py:800-801`) while `multiple_floorplan` pads to 10000 (`inputgraph.py:1147-1148`). Is the 10 a deliberate cap on dummy rooms or a typo? It silently constrains every irregular layout that goes through the single path.
5. `self.floorplan_exist` is never reset between invocations. Should `single_floorplan` clear it at entry so the handler retry loops behave correctly on a second failing round?
