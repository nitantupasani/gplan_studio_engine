# dim-05: solve_linear.py, the linear solve

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\dimensioning\solve_linear.py` (154 lines, one function).

## Purpose

`solve_linear` turns two encoded st-graphs (the vertical one and the horizontal one, already reduced to LP matrices by `convert_adj_equ_sym`) into concrete room widths and heights by running two independent linear programs through `scipy.optimize.linprog`. It runs the width LP first, derives per-room height windows from the widths and the aspect-ratio lists, then runs the height LP against those derived windows.

## Where It Sits In The Pipeline

Real chain:

```
inputgraph.InputGraph.single_floorplan   (inputgraph.py:779)
inputgraph.InputGraph.multiple_floorplan (inputgraph.py:1126)
        |
        v  fpts.floorplan_to_st(...)      (inputgraph.py:821 and inputgraph.py:1167)
floorplan_to_st.floorplan_to_st          (floorplan_to_st.py:18)
        |-- convert_adj_equ_sym(VER, ver_list, plot_width)   (floorplan_to_st.py:103-104)
        |-- convert_adj_equ_sym(HOR, hor_list, plot_height)  (floorplan_to_st.py:105-106)
        `-- solve_linear(...)                                (floorplan_to_st.py:108-109)
                    |
                    `-- scipy.optimize.linprog x2  (solve_linear.py:76, solve_linear.py:140)
```

Reached from the API through `handlers.handle_single` (`handlers.py:924`, `handlers.py:931`), `handlers.handle_single_oc` (`handlers.py:1166`, `handlers.py:1173`), `handlers.handle_letter_shape` (`handlers.py:1004`), `handlers.handle_circulation` (`handlers.py:621`, `handlers.py:628`), `handlers.handle_multiple` (`handlers.py:1069`), `handlers.handle_multiple_oc` (`handlers.py:1474`). Those handlers are dispatched from `api.py:1262-1327`, and are the `dimensioned=True` branch that builds `DimParameters` at `api.py:1229`.

### CORRECTION TO THE TASK PREMISE: minimum_dimensioning.py never calls solve_linear

The brief said this chain is "driven by `minimum_dimensioning.py`". It is not. There are **zero** call sites of `solve_linear` (or `floorplan_to_st`, or `convert_adj_equ_sym`) inside `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py`. That file imports only `collections.defaultdict`, `json`, `os` (`minimum_dimensioning.py:1-3`) and implements a completely separate, hand-rolled longest-path / Bellman-Ford-style solver over a constraint graph:

- `pos_longest_path` (`minimum_dimensioning.py:388`)
- `longest_path` (`minimum_dimensioning.py:466`)
- `compute_placement` (`minimum_dimensioning.py:547`)
- `main` (`minimum_dimensioning.py:767`)

The two solvers are siblings, selected by a different API flag:

| flag at `api.py:1226-1229` | solver actually used |
| --- | --- |
| `minDimEnabled=True` | `min_dim.main` (`handlers.py:346`, `handlers.py:352`) -> longest path, no scipy |
| `dimensioned=True` | `graph.single_floorplan` / `multiple_floorplan` -> `floorplan_to_st` -> `solve_linear` -> scipy LP |

Everything below about the LP therefore describes the `dimensioned=True` path only. The concrete parameter values that "arrive" come from `floorplan_to_st.py:108-109` and, one level up, `inputgraph.py:821-823` / `inputgraph.py:1167-1169`.

## Entry Points (file:line)

- `solve_linear(f_VER, A_VER, Aeq_VER, Beq_VER, f_HOR, A_HOR, Aeq_HOR, Beq_HOR, min_width, max_width, min_height, max_height, min_ar, max_ar)` defined at `solve_linear.py:16`.
- Its only call site in the package: `floorplan_to_st.py:108-109`.
- Imported at `floorplan_to_st.py:14` (`from .solve_linear import solve_linear`).
- A same-named but different-signature copy exists in the frozen monolithic GUI script at `GPLAN\GPLAN\pythongui\final.py:1224` (`solve_linear(N, f_VER, A_VER, b_VER, Aeq_VER, Beq_VER, f_HOR, A_HOR, Aeq_HOR, Beq_HOR, inp_area)`), called at `final.py:1144`. That is a separate legacy module, not this file.

## Data Structures

Produced by `convert_adj_equ_sym` (`convert_adj_equ_sym.py:15`) and consumed here.

Let `DGPH` be the st-graph adjacency matrix, `N = len(DGPH)` (`convert_adj_equ_sym.py:33`), and `n = count` the number of 1-entries in `DGPH`, i.e. the number of directed edges (`convert_adj_equ_sym.py:48-54`).

- **Decision vector `x`**: length `n`, one variable per st-graph EDGE, not per room. Physically the flow on that edge, which is the dimension carried across that adjacency.
- **`LINEQ`**: `N x n` signed incidence matrix, `+1` at the tail vertex, `-1` at the head vertex (`convert_adj_equ_sym.py:38-42`, transposed at `convert_adj_equ_sym.py:55`).
- **`A` before stacking**: `A[i] = ismember(LINEQ[i], -1)`, the 0/1 indicator of the **in-edges of vertex i** (`convert_adj_equ_sym.py:69-75`). So `(A @ x)_i = ` total in-flow of vertex `i` = **the dimension of room `i`**.
- **`A_VER` / `A_HOR` as passed in**: `vstack(-A[1:], +A[1:])`, shape `2*(N-1) x n` (`convert_adj_equ_sym.py:76-80`). Row 0 (the source, north or west node) is deleted at `convert_adj_equ_sym.py:78-79`.
- **`f_VER` / `f_HOR`**: shape `(1, n)`, zeros except the first `z` entries set to 1, where `z = sum(DGPH[0])` = out-degree of the source (`convert_adj_equ_sym.py:58-64`). Because edges are enumerated row-major (`convert_adj_equ_sym.py:48-52`), those first `z` positions are exactly the source's out-edges.
- **`Aeq_VER` / `Aeq_HOR`**: the `LINEQ` rows of vertices that have both an out-edge and an in-edge (`convert_adj_equ_sym.py:106-109`), plus one symmetry row per symmetric pair (`convert_adj_equ_sym.py:83-98`, stacked at `convert_adj_equ_sym.py:112-113`), plus, when `plot_dimension != -1`, `f` prepended as the first row (`convert_adj_equ_sym.py:117-119`).
- **`Beq_VER` / `Beq_HOR`**: zeros of length `len(Aeq)` (`convert_adj_equ_sym.py:116`), with `plot_dimension` prepended as element 0 when a plot size is given (`convert_adj_equ_sym.py:120-122`).
- **`ver_list` / `hor_list`**: symmetric room-id groups from `block_checker` (`block_checker.py:95-96`, returned at `block_checker.py:101`), computed in `inputgraph.py:817-818` and `inputgraph.py:1164-1165`.
- **Locals built here**: `b_VER` (`solve_linear.py:56-62`), `b_HOR` (`solve_linear.py:115-129`), `min_AR_height` / `max_AR_height` (`solve_linear.py:90-94`), `min_height_mod` / `max_height_mod` (`solve_linear.py:96-107`).
- **Return `[W, H, status]`** (`solve_linear.py:154`): `W` and `H` are `2p x 1` column vectors, first half positive dimensions, second half the same values negated. Verified empirically (see Failure Modes).

## Algorithm Walkthrough

1. `p = len(min_height)` (`solve_linear.py:53`). Everything downstream assumes `p == N-1 == room count`.
2. `empty_ver` / `empty_hor` allocated (`solve_linear.py:54-55`) and **never used again**. Dead locals.
3. Build the width right-hand side: `b_min_VER = -min_width`, `b_max_VER = +max_width`, concatenated (`solve_linear.py:56-62`).
4. Width branch (`solve_linear.py:66`): if `Aeq_VER` is empty, skip the LP entirely, set every width to 1 by hand (`solve_linear.py:67-74`) and `ver_success = True`. Otherwise run the LP (`solve_linear.py:76`), recover `W = -1 * A_VER @ X1` (`solve_linear.py:80`), slice the first half into `a`, the list of `p` widths (`solve_linear.py:82-85`).
5. Aspect ratios: `min_AR_height[i] = min_ar[i] * a[i]`, `max_AR_height[i] = max_ar[i] * a[i]` (`solve_linear.py:90-94`). Tighten the caller's height window: `min_height_mod[i] = max(min_height[i], min_AR_height[i])` (`solve_linear.py:98-102`), `max_height_mod[i] = min(max_height[i], max_AR_height[i])` (`solve_linear.py:103-107`).
6. Consistency check: if any `min_height_mod[i] > max_height_mod[i]`, set `flag1 = 1` (`solve_linear.py:108-111`), print a warning (`solve_linear.py:113-114`) and **silently drop the aspect-ratio constraints entirely**, falling back to raw `min_height` / `max_height` (`solve_linear.py:115-121`). Otherwise use the AR-tightened window (`solve_linear.py:123-129`). Note this is global: one bad room disables aspect ratios for all rooms.
7. Height branch (`solve_linear.py:132`): same shape as step 4. LP at `solve_linear.py:140`, `H = -1 * A_HOR @ X2` at `solve_linear.py:145`.
8. `status = ver_success and hor_success` (`solve_linear.py:153`), return `[W, H, status]` (`solve_linear.py:154`).

## The Actual Constraints Or Formulas

### 1. Which solver

**`scipy.optimize.linprog` with `method='interior-point'`**, called twice, both in this file:

- Width solve: `solve_linear.py:76`
  ```python
  value_opti_ver = scipy.optimize.linprog(f_VER, A_ub=A_VER, b_ub=b_VER, A_eq=Aeq_VER, b_eq=Beq_VER, bounds=(1,None), method='interior-point', callback=None, options=None, x0=None)
  ```
- Height solve: `solve_linear.py:140`
  ```python
  value_opti_hor = scipy.optimize.linprog(f_HOR, A_ub=A_HOR, b_ub=b_HOR, A_eq=Aeq_HOR, b_eq=Beq_HOR, bounds=(1,None), method='interior-point', callback=None, options=None, x0=None)
  ```

Import at `solve_linear.py:14`. There is no hand-rolled simplex in this file.

There is a **second, non-scipy path**: the `if not Aeq_*.tolist()` branches at `solve_linear.py:66-74` (widths) and `solve_linear.py:132-138` (heights). These do not solve anything. They hard-code every dimension to `1` and report success. Reached only when `Aeq` came back empty, which requires no internal vertex with both in and out edges, no symmetry rows, and `plot_dimension == -1` (`convert_adj_equ_sym.py:106-119`).

Installed SciPy in this environment is **1.11.3**, where `method='interior-point'` still runs but emits `DeprecationWarning: method='interior-point' is deprecated and will be removed in SciPy 1.11.0`. Verified by running it. This is a hard upgrade blocker (see Coupling).

### 2. Full formulation, width LP (the VER graph)

Variables: `x in R^n`, one per edge of the vertical st-graph. Edge flow = a width contribution.

**Objective** (`c = f_VER`, built at `convert_adj_equ_sym.py:58-64`, passed at `solve_linear.py:76`, produced for the caller at `floorplan_to_st.py:103-104`):

```
minimize   sum over e in out-edges(north source)  of  x_e
```

In floorplan terms this is **the total plot width**, i.e. the sum of the widths of the rooms touching the north boundary. It is not the sum of all room widths and it is not a dummy feasibility objective. It is a genuine "make the plan as narrow as possible" objective.

**Equality constraints** `A_eq x = b_eq` (`Aeq_VER`, `Beq_VER`; passed at `solve_linear.py:76`):

| row block | source | meaning |
| --- | --- | --- |
| row 0, present only if `plot_width != -1` | `convert_adj_equ_sym.py:117-119` prepends `f`; rhs at `convert_adj_equ_sym.py:120-122` | `sum of source out-flows = plot_width`. Exact plot-width pin. Makes the objective degenerate when active. |
| one row per internal vertex `v` | `convert_adj_equ_sym.py:106-109` | `sum out-flow(v) - sum in-flow(v) = 0`. Flow conservation: the total width of the rooms directly above a room equals the total width of the rooms directly below it. This is what makes the tiling gapless. rhs 0 (`convert_adj_equ_sym.py:116`). |
| one row per symmetric pair | `convert_adj_equ_sym.py:83-98`, stacked `convert_adj_equ_sym.py:112-113` | `sum of widths of group A - sum of widths of group B = 0`. Groups come from `ver_list` (`block_checker.py:95`), passed at `floorplan_to_st.py:104`. rhs 0. |

**Inequality constraints** `A_ub x <= b_ub` (`A_VER` from `convert_adj_equ_sym.py:76-80`, `b_VER` built at `solve_linear.py:56-62`). `A_VER` has `2*(N-1)` rows, `b_VER` has `2p` entries, and the whole thing only lines up because `p == N-1`.

| rows | matrix | rhs | meaning |
| --- | --- | --- | --- |
| `0 .. p-1` | `-A[i+1]` = negated in-edge indicator of room `i` (`convert_adj_equ_sym.py:76`, `:78`) | `-min_width[i]` (`solve_linear.py:56`, `:60`, `:62`) | `-width_i <= -min_width[i]`, i.e. **`width_i >= min_width[i]`** |
| `p .. 2p-1` | `+A[i+1]` (`convert_adj_equ_sym.py:77`, `:79`) | `+max_width[i]` (`solve_linear.py:57`, `:61`, `:62`) | **`width_i <= max_width[i]`** |

So the per-room minimum lands in the **first half of `b_ub`, negated**, and the per-room maximum in the **second half of `b_ub`, as-is**. Neither ever touches `bounds`.

**Variable bounds** (`solve_linear.py:76`): `bounds=(1, None)`, applied uniformly to all `n` edge variables:

```
x_e >= 1   for every edge e
```

A hard floor of 1 unit on every single adjacency flow. This is the only place `bounds` is used, and it carries no per-room information at all.

**Solution recovery** (`solve_linear.py:77-85`): `X1 = value_opti_ver['x']`, reshaped to a column, then `W = -1 * A_VER @ X1 = [ +in-flow ; -in-flow ] = [ widths ; -widths ]`. `a = W[0:p]` flattened to a list.

### 3. Full formulation, height LP (the HOR graph)

Identical structure over the horizontal st-graph (`HOR`, built at `floorplan_to_st.py:79-101`), whose edge flows are heights.

- Objective `f_HOR`: `minimize sum of out-flows of the west source` = **total plot height**.
- `A_eq`/`b_eq` = `Aeq_HOR`/`Beq_HOR` from `convert_adj_equ_sym.py:105-106` call at `floorplan_to_st.py:105-106`; row 0 pins `plot_height` when `plot_height != -1`; internal rows are flow conservation across vertical cuts; symmetry rows come from `hor_list`.
- `A_ub` = `A_HOR`, `b_ub` = `b_HOR`. **`b_HOR` is not the caller's `min_height`/`max_height` in the normal case**: it is the aspect-ratio-tightened window `min_height_mod` / `max_height_mod` (`solve_linear.py:123-129`), which depends on the widths just solved. Only when `flag1 == 1` does it fall back to the raw caller values (`solve_linear.py:115-121`).
- Bounds: `bounds=(1, None)` (`solve_linear.py:140`).
- Recovery: `H = -1 * A_HOR @ X2` (`solve_linear.py:145`).

### 4. What concretely arrives at the call site

`floorplan_to_st.py:108-109` passes, in order: `f_VER, A_VER, Aeq_VER, Beq_VER` (from `floorplan_to_st.py:103-104`), `f_HOR, A_HOR, Aeq_HOR, Beq_HOR` (from `floorplan_to_st.py:105-106`), then the caller's raw lists `min_width, max_width, min_height, max_height, min_ar, max_ar`.

Those six lists originate at `inputgraph.py:821-823` / `inputgraph.py:1167-1169` and are the caller's lists **after being padded in place** for merged and extra nodes:

- `single_floorplan`, merged nodes: `min_width=0, min_height=0, max_width=10, max_height=10, min_ar=0, max_ar=10000` (`inputgraph.py:797-803`). Note the `10`, not `10000`, for merged nodes on this path.
- `single_floorplan`, extra nodes: `min=0`, `max=10000`, `min_ar=0`, `max_ar=10000` (`inputgraph.py:804-810`).
- `multiple_floorplan`, merged nodes: `max_width=10000, max_height=10000` (`inputgraph.py:1144-1150`); extra nodes the same (`inputgraph.py:1151-1157`).

The real-room values come from `DimParameters` on the API path: `dimensiongui.gui_fnc` returns them straight through when `gclass is None` (`dimensiongui.py:10-12`), fed from `api.py:1229` (`dim_inputs['min_width']`, `['max_width']`, `['min_ratio']`, `['max_ratio']`, `['plot_width']`, `['plot_height']`, `['symmetric']`).

`plot_width` / `plot_height` reach `convert_adj_equ_sym` as the third argument (`floorplan_to_st.py:104`, `:106`) and the **only** value that disables the plot equality is exactly `-1` (`convert_adj_equ_sym.py:117`). The GUI "Free Plot Size" button sets `-1` (`dimensiongui.py:194-196`); the GUI default is `0` (`dimensiongui.py:53-54`). A caller sending `0` therefore pins the total plot width to zero and guarantees infeasibility.

### 5. HYPOTHESIS: SOLVER_UB_SLACK widens upper bounds by 2.5x

**REFUTED for this file. PARTIALLY CONFIRMED elsewhere, for a different solver.**

Grep results across `solve_linear.py`, the whole `dimensioning` package, and `GPLAN\GPLAN\api.py`:

- `solve_linear.py`: **no occurrence** of `SOLVER_UB_SLACK` and **no literal `2.5`**. The LP in this file never widens anything. `b_VER` uses `max_width` verbatim (`solve_linear.py:57`), `b_HOR` uses `max_height` or the AR-tightened `max_height_mod` verbatim (`solve_linear.py:116`, `solve_linear.py:124`).
- `GPLAN\GPLAN\api.py`: **no occurrence** of `SOLVER_UB_SLACK` and no literal `2.5`.
- The constant exists only at **`minimum_dimensioning.py:155`**:
  ```python
  SOLVER_UB_SLACK = float(os.environ.get("GPLAN_SOLVER_UB_SLACK", "2.5"))
  ```
  Value `2.5` by default, overridable at process start by the env var `GPLAN_SOLVER_UB_SLACK`. Its sibling `DEFAULT_UB_FACTOR = 5` is at `minimum_dimensioning.py:148`.

**Exactly what it multiplies and under what condition** (`minimum_dimensioning.py:158-177`):

```python
low = float(low)                       # :167  the room's minimum on this axis
open_ub = DEFAULT_UB_FACTOR * low      # :168  5 x minimum
if supplied is None:      return open_ub          # :169-170
try: value = float(supplied)                      # :171-172
except (TypeError, ValueError): return open_ub    # :173-174
if value <= 0 or value >= 99999: return open_ub   # :175-176
return min(open_ub, max(value, SOLVER_UB_SLACK * low))   # :177
```

It multiplies `low`, the **per-room minimum width or minimum height**, and only on line 177, i.e. only when the caller supplied a usable ceiling (not `None`, parseable, strictly positive, strictly below the `99999` "open" sentinel). The result is a **floor on the ceiling, clamped by 5x**, not a blanket 2.5x widening:

- supplied `< 2.5 * low`  ->  widened up to `2.5 * low`
- `2.5 * low <= supplied <= 5 * low`  ->  used unchanged, no widening at all
- supplied `> 5 * low`  ->  clamped down to `5 * low`

The widened value lands in `ub_len` / `ub_width` (`minimum_dimensioning.py:195`, `:198`, `:200-203`) and from there into the **longest-path constraint graph**, not into any LP: `edgesX[right_wall][left_wall] = -1 * ub_width[i]` (`minimum_dimensioning.py:238`) and `edgesY[top_wall][bottom_wall] = -1 * ub_len[i]` (`minimum_dimensioning.py:320`).

The documentation is self-consistent: `documentation\door_connectivity.md:48-49` says "the **longest-path solve** widens each supplied ceiling", and that is accurate. The exact ceilings are re-applied later in `api._fill_gaps` (defined `api.py:710`, called `api.py:836` and `api.py:840`), and the release-on-infeasible retry is `handlers.solve_min_dim` (`handlers.py:338-353`). None of that touches `solve_linear.py`.

Other `2.5` hits in the repo are unrelated: `Space_Optimization\uinegNew.py:3865` (a wall thickness) and a commented-out line at `uinegNew.py:6318`. Doc/test mentions at `GPLAN\test_max_dimensions.py:9` and `:76`.

## Invariants And Preconditions

- `len(min_width) == len(max_width) == len(min_height) == len(max_height) == len(min_ar) == len(max_ar) == p`, and `p == N-1 == A_VER.shape[0]/2`. Nothing asserts this. If the caller's lists are the wrong length, `np.hstack` at `solve_linear.py:62` silently yields a `b_ub` whose length disagrees with `A_ub`, and scipy raises a shape error.
- `Aeq_VER` and `Aeq_HOR` must be numpy arrays: `.tolist()` is called on them unguarded at `solve_linear.py:66` and `solve_linear.py:132`.
- `min_ar[i] <= max_ar[i]` is assumed but not checked; the pairwise consistency check at `solve_linear.py:108-111` catches the downstream symptom only.
- `bounds=(1, None)` means no edge flow can ever be below 1. Any room whose true optimal dimension is under 1 unit cannot be represented.
- The plot equality is disabled by the single literal `-1` (`convert_adj_equ_sym.py:117`). Any other falsy-looking value (`0`, `None` coerced) is treated as a real plot dimension.
- The width LP must complete before the height LP: `min_height_mod` at `solve_linear.py:98-102` depends on `a`, the solved widths. The two solves are not independent.

## Failure Modes

**Infeasible LP.** `method='interior-point'` does **not** raise and does **not** return `x=None`. Verified by direct execution: it returns `status=2`, `success=False`, and `x` set to the last interior-point iterate, which is a plausible-looking but wrong vector.

- The file reads only `value_opti_ver['x']` (`solve_linear.py:77`) and `value_opti_ver.success` (`solve_linear.py:86`); likewise `solve_linear.py:142`, `solve_linear.py:146`. The `status` integer and `message` are never inspected.
- `W` and `H` are still computed from the garbage iterate (`solve_linear.py:80`, `solve_linear.py:145`) and still returned (`solve_linear.py:154`) alongside `status=False` (`solve_linear.py:153`).
- `floorplan_to_st.py:111-112` still rounds them and `floorplan_to_st.py:114` still returns them.
- The caller discards them: `inputgraph.py:827-828` (`if (status == False): continue`) and `inputgraph.py:1173-1174`. `floorplan_exist` stays `False` (`inputgraph.py:830`, `inputgraph.py:1176`), and the GUI handlers loop re-prompting for dimensions (`handlers.py:926-932`).

Reproduced end to end (2x2 grid, `min_width=[5,5,5,5]`, `plot_width=3`): returned `status=False` with `W = [5.715, 5.715, 5.715, 5.715, -5.715, -5.715, -5.715, -5.715]`. Feasible control run (`min_width=[3,1,1,1]`) returned `status=True`, `W = [3, 1, 3, 1, -3, -1, -3, -1]`, showing flow conservation forcing room 2 to match room 0's column width.

**Aspect ratios silently discarded.** If a single room has `min_height_mod[i] > max_height_mod[i]`, `flag1` is set (`solve_linear.py:108-111`) and aspect ratios are dropped for **every** room (`solve_linear.py:112-121`). The only signal is a `print` to stdout at `solve_linear.py:113-114`, and `api.py:1222` replaces `builtins.print` with a no-op for the whole API call, so this warning is invisible in production.

**Returned vectors are double length.** `W` and `H` are `2p x 1`, second half negated (`solve_linear.py:80`, `solve_linear.py:145`; the hand-built fallbacks at `solve_linear.py:68-72` and `solve_linear.py:133-137` mirror the same shape). `floorplan_to_st.py:111-114` does not truncate. `inputgraph.py:831-834` flattens the full `2p` vector into `self.room_width` / `self.room_height`, which are then handed to `dual.get_coordinates` (`inputgraph.py:838`). Confirmed empirically: a 4-room plan produces `width.shape == (8,1)` with contents `[1,1,1,1,-1,-1,-1,-1]`.

**Rounding and post-processing.** No integer rounding anywhere. The only rounding is `np.round(width, 3)` and `np.round(height, 3)` at `floorplan_to_st.py:111-112`, and separately `round(..., 3)` on the derived coordinates at `inputgraph.py:840` and `inputgraph.py:842` (and `inputgraph.py:1184`, `inputgraph.py:1186`). No explicit numeric tolerance is set: `options=None` at `solve_linear.py:76` and `solve_linear.py:140` leaves scipy defaults.

**SciPy deprecation.** `method='interior-point'` warns on 1.11.3 and is scheduled for removal. On a SciPy where it is gone, both `linprog` calls raise `ValueError`, which nothing in this file or in `floorplan_to_st.py` catches. Worse, if someone "fixes" it by switching to `method='highs'`, an infeasible solve returns `x=None`, and `np.dot(A_VER, X1)` at `solve_linear.py:80` will raise instead of quietly producing a discarded vector. That is a behaviour change, not a drop-in swap.

## Coupling (what breaks if you change this)

- **Row ordering of `A_ub` is a contract with `convert_adj_equ_sym`.** `b_VER = hstack(-min_width, max_width)` at `solve_linear.py:62` only matches because `convert_adj_equ_sym.py:80` stacks `A_min` above `A_max`. Reorder either side and every minimum becomes a maximum.
- **Sign convention of the recovery step.** `W = -1 * A_VER @ X1` (`solve_linear.py:80`) depends on `A_min = -A` at `convert_adj_equ_sym.py:76`. Change the negation in either file and widths come out negative.
- **`bounds=(1, None)`** is the de-facto minimum feature size of the whole engine on this path. Lowering it to 0 admits degenerate zero-width rooms; raising it inflates every plan.
- **The aspect-ratio coupling makes the height LP depend on the width LP.** Any attempt to parallelise the two solves, or to swap their order, changes results.
- **The plot-size sentinel `-1`** is decided in `convert_adj_equ_sym.py:117` but produced in `dimensiongui.py:195-196` and by API callers via `api.py:1229`. Three files must agree.
- **`SOLVER_UB_SLACK` changes do nothing to this path.** Tuning `GPLAN_SOLVER_UB_SLACK` affects only `minimum_dimensioning.upper_bound` and therefore only `minDimEnabled` requests. If a `dimensioned=True` request is producing oversized rooms, this constant is not the lever.
- **SciPy version pin.** `method='interior-point'` must keep existing. Upgrading SciPy past its removal breaks the entire `dimensioned=True` API surface.

## Dead Or Duplicated Code

Enumerating every function in `solve_linear.py`: there is exactly **one**, `solve_linear` at `solve_linear.py:16`. It is **not** dead: called at `floorplan_to_st.py:108`, which is called at `inputgraph.py:821` and `inputgraph.py:1167`, which are reached from live API handlers.

Dead or duplicated items found:

- **`empty_ver` (`solve_linear.py:54`) and `empty_hor` (`solve_linear.py:55`)**: allocated via `np.empty_like` and never read. Dead locals.
- **The `not Aeq_*.tolist()` fallback branches** (`solve_linear.py:66-74`, `solve_linear.py:132-138`): reachable but degenerate. They do not solve anything, they assign width 1 and height 1 to every room and report `success = True`. Effectively a stub that fakes success.
- **`a = np.ones(p)` at `solve_linear.py:67`**: the only reason the aspect-ratio block at `solve_linear.py:90-94` does not crash in the fallback branch. It makes the AR-derived heights equal to `min_ar[i]` and `max_ar[i]` verbatim.
- **`GPLAN\GPLAN\pythongui\final.py:1224`**: a duplicate `solve_linear` with a different signature and an `inp_area` argument, called only from `final.py:1144` within that same monolithic legacy GUI file. Not imported by the package. Legacy duplicate.
- **The module docstring** at `solve_linear.py:1-12` is byte-identical to the ones in `convert_adj_equ_sym.py:1-12` and `floorplan_to_st.py:1-12`. Triplicated, and its claim that `floorplan_to_st` "Calls solve_linear and convert_adj_equ_sym" is the only accurate part.
- **`minimum_dimensioning.py` is not part of this chain at all** despite living in the same package and sharing the module-level naming. Its `print_placements` (`minimum_dimensioning.py:536`), `print_edges` (`:568`), `print_rot` (`:678`), and `print_input` (`:687`) are debug-only helpers, and its `__main__` block at `minimum_dimensioning.py:844-845` calls `main("input_to_min_dim.json")` with one argument against a three-argument signature (`minimum_dimensioning.py:767`), so it is broken as a script entry point.

## Open Questions

1. Is the `2p`-length `W`/`H` return (widths then negated widths) intentional? `inputgraph.py:833-834` assigns the full flattened vector to `self.room_width` / `self.room_height`. I did not trace `dual.get_coordinates` (`inputgraph.py:838`) or `opr.calculate_area` (`inputgraph.py:843-845`) to see whether they slice to the first `p` entries or silently read the negative tail.
2. Why is `f` (the objective) reused verbatim as the plot-dimension equality row (`convert_adj_equ_sym.py:118`)? When a plot size is given the objective is pinned to a constant, so the LP degenerates to pure feasibility. Is that the intent, or should the objective switch to something else (area, deviation from targets) when the plot is fixed?
3. `inputgraph.py:800-801` pads merged nodes with `max_width=10` / `max_height=10` while `inputgraph.py:1147-1148` uses `10000` for the same concept. One of the two is almost certainly a typo, and the `10` version silently caps merged nodes at ten units.
4. The in-code comment at `convert_adj_equ_sym.py:64` ("need explanation, if we want to minimise inflow why dont we take all vertices adj to north or west") is an unresolved authorial doubt. My reading is that the code is correct because row-major edge enumeration puts the source's out-edges first, but this should be asserted rather than relied on.
5. What is the intended migration off `method='interior-point'`? A naive swap to `'highs'` changes the infeasible-path behaviour from "returns garbage with status False" to "raises on `np.dot(A, None)`".
6. Does any production API request actually take the `dimensioned=True` path, or is `minDimEnabled` the only one exercised? That determines whether the SciPy deprecation is urgent or dormant.
