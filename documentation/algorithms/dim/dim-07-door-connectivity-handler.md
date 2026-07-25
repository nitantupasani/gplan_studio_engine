# dim-07: `handle_door_connectivity` (the door-connectivity request handler)

All paths absolute. All line numbers verified by reading the cited region.

Primary file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py`
Handler region: lines 1686 to 2657 (next `def` starts at 2659).

---

## Purpose

Takes an already-constructed `InputGraph` (adjacency plus non-adjacency edges) plus a
`GuiParameters` bag, augments the graph to a PTPG, enumerates rectangular-dual candidates,
runs each candidate through the minimum-dimensioning longest-path solver under an optional
plot cap, and pushes the survivors into `ui`'s output list. It returns `None` always; every
result and every error travels through mutation of `ui`.

## Where It Sits In The Pipeline

- Called from `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py:1309` (count == 1,
  single plan) and `api.py:1353` (count > 1, batch), plus a cardinal-constraint retry at
  `api.py:1390`.
- Request translation happens before it: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\local_engine_bridge.py:60-129`
  (local test server) and `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\gplan_apis\views.py:839`
  (deployed backend).
- Post-filters run after it, inside api.py, not inside the handler:
  `rectangularize_output` (`api.py:801`), `filter_output_by_cardinal` (`api.py:418`),
  and the final truncation at `api.py:1418` / `api.py:1427`.

---

## Entry Points (file:line)

| Symbol | Location |
| --- | --- |
| `handle_door_connectivity` | `handlers.py:1686` |
| `origin` (module global passed to every `drawFunction`) | `handlers.py:39` |
| `drawFunction` | `handlers.py:41` |
| `get_max_dims` | `handlers.py:309` |
| `solve_min_dim` | `handlers.py:338` |
| `handle_circulation` (delegated to, then early `return`) | `handlers.py:492`, called at `handlers.py:1748`, return at `1749` |
| `show_warning` | `handlers.py:3056` |
| `get_encoded_matrix` | `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\graphoperations\operations.py:211` |
| `input_for_min_dim.floorplan` | `...\GPLAN\GPLAN\input\input_for_min_dim.py:16` |
| `floorplan.get_floorplan_details` | `input_for_min_dim.py:60` |
| `min_dim.main` (`minimum_dimensioning`) | `...\GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:767` |
| `InputGraph.is_connected` | `...\GPLAN\GPLAN\source\inputgraph.py:181` |
| `connect_graph.one_connected` | `...\GPLAN\GPLAN\source\graphoperations\connect_graph.py:9` |
| `InputGraph.door_connectivity` | `inputgraph.py:340` |
| `InputGraph.update_gclass_with_edges` | `inputgraph.py:316` |
| `InputGraph.oneconnected_dual` | `inputgraph.py:1200` |
| `InputGraph.irreg_multiple_dual` | `inputgraph.py:852` |
| `InputGraph.irreg_single_dual` | called at `handlers.py:1759`, `1761`, `2221` |
| `InputGraph.scale_plot_dimension` | `inputgraph.py:597` |
| `inputgraph.get_final_traversal` | `inputgraph.py:1580` |
| `dim_on_paths_bdy` | `...\GPLAN\GPLAN\source\path_map.py:99` |
| `mindimgui.gui_fnc` (GUI only) | called at `handlers.py:1801`, `2253` |
| `nonadjgui.gui_non_adj` (GUI only) | called at `handlers.py:1705` |

---

## Data Structures

- `ui`: `GuiParameters` (`...\GPLAN\GPLAN\pythongui\GuiParameters.py`). Output sink.
  `_append_output_data` at `GuiParameters.py:389`, `_set_output_data` at `426`,
  `_set_multiple_output_found` at `448`, `_set_dim_constraints` at `452`, `print_gui` at `379`.
  Note: `_set_multiple_output_found` and `_set_dim_constraints` write **only** when a `gclass`
  exists (`GuiParameters.py:449`, `453`), i.e. they are no-ops on the whole API path.
- `graph`: `InputGraph` (`inputgraph.py`, ctor fields at `inputgraph.py:125-156`).
  - `graph.graph_list` (`inputgraph.py:147`): flat accepted-candidate list. The handler wipes it
    at `handlers.py:1841` / `2271` and rebuilds it itself.
  - `graph.graph_list_by_bdy` (`inputgraph.py:148`): list of lists, one inner list per selected
    boundary, each holding that boundary's REL-derived candidate graphs. **This is the real pool.**
  - `graph.fpcnt` (`inputgraph.py:142`): total candidates the generator produced.
  - `graph.floorplan_limit = 500` (`inputgraph.py:139`), `graph.floorplan_per_bdy_limit = 20`
    (`inputgraph.py:140`).
  - `graph.cardinal_constraints` (`inputgraph.py:156`).
- `floorplan_data`: dict built by `input_for_min_dim.floorplan.get_floorplan_details`
  (`input_for_min_dim.py:60`), with `nodes` / `edges` / `boundary_rooms` keys, consumed by
  `min_dim.main` (`minimum_dimensioning.py:767`).
- `areas_mapping`: list of `((boundArea - area_sum, area_sum), index)` built at `handlers.py:1949`,
  `2059`, `2385`, `2497`; sorted at `2184`, `2194`, `2632`, `2640` to order the batch.
- `valid`: list of accepted indices used only in the expand-only fallback (`handlers.py:2091`, `2525`).

---

## Algorithm Walkthrough

### A. Payload in / graph normalisation (1686-1743)

1. `handlers.py:1687-1688`: if `graph.is_connected()` (`inputgraph.py:181`) is false, force
   connectivity in place with `connect_graph.one_connected` (`connect_graph.py:9-21`).
   That helper writes `True` into the matrix but never increments `edgecnt`; `edgecnt` is
   recomputed later at `inputgraph.py:445`.
2. `handlers.py:1703`: `ui.get_isNonAdj() == 1` splits into two nearly identical branches.
   - Non-adjacency branch `1704-1728`: non-adj list from `nonadjgui.gui_non_adj` (`1705`, GUI only)
     or `ui.get_non_adj_list()` (`1708`); `graph.door_connectivity(show_graph=drawGUI, non_adj_list=...)`
     at `1710`.
   - Plain branch `1730-1739`: `graph.door_connectivity(show_graph=drawGUI)` at `1732`.
3. `handlers.py:1712-1721`: defensive unpack of the return tuple (see Dead Code: this is dead).
4. `handlers.py:1724-1728` / `1735-1739`. Publish the augmented PTPG back onto `ui`:
   `set_ptpg_graph`, `set_edgeCount`, `set_edges(graph.update_gclass_with_edges(gclass))`
   (`inputgraph.py:316`), `set_nodeCoordinates`.
5. `handlers.py:1741-1743`: reset `multiple_door`, clear the output list, clear the
   multiple-output flag.

`InputGraph.door_connectivity` (`inputgraph.py:340`) itself does: biconnectivity augmentation
(`inputgraph.py:365-380`), triangulation (`384-397`), separating-triangle elimination
(`436-450`), planarity re-check and possible re-triangulation (`471-510`), extra-edge bookkeeping
(`513-516`), and returns `(self, check_ptpg(separating_triangles1))` at `inputgraph.py:520`.

### B. PTPG branch (1745-2207)

6. `handlers.py:1745`: `if (checkPTPG):`.
7. `handlers.py:1747-1749`. Circulation short-circuit: delegate to `handle_circulation` and
   `return`. Nothing after this runs, including the timing print at `2656`.
8. `handlers.py:1751`: `ui.get_isMinDimensioned() == 0` gives the non-dimensioned path
   (`1751-1786`): `oneconnected_dual("single")` (`1756`) with `irreg_single_dual` fallbacks
   (`1759`, `1761`), or `irreg_multiple_dual()` (`1778`) when `multiple_door`.
9. `handlers.py:1787`: `elif (ui.get_isMinDimensioned() == 1):` is the min-dim path, the one
   that matters for this dossier.

**Dimensioning inputs** (`1788-1818`):
   - GUI: `mindimgui.gui_fnc` at `1801`.
   - API: unpacked from `ui.min_dim_inputs` at `1806`
     (`min_width, min_height, plot_width, plot_height, optimal_floorplan, allow_rotation, multiple_door`).
   - `get_max_dims(ui)` at `1808` (helper at `handlers.py:309-335`) returns the per-room ceiling
     lists, or `(None, None)` when every entry is the 99999 sentinel (`handlers.py:328-333`).
   - `input_dims = [min_width, min_height, plot_width, plot_height]` at `1810`, blanked to `[]`
     at `1812-1813` **only when both plot dims are 0**.
   - `allow_rotation` forced off under cardinal constraints at `1814-1818`.

**Candidate generation** (`1821-1838`):
   - Cardinal path: `graph.irreg_multiple_dual(input_dims)` directly at `1830`.
   - Otherwise `try: graph.oneconnected_dual("multiple")` at `1833`, with
     `except OCError -> irreg_multiple_dual(input_dims)` at `1836` and
     `except BCNError -> irreg_multiple_dual(input_dims)` at `1838`.
   - `number_of_floorplans = graph.fpcnt` at `1839`; `graph.graph_list = []` at `1841`
     (throws away the flat list the generator just built at `inputgraph.py:1012` / `1096`).

**Candidate filtering loop** (`1859-1968`):
   - Outer loop over boundaries `for bdy_itr in range(len(graph.graph_list_by_bdy))` at `1859`.
   - Inner loop over RELs of that boundary at `1861`, with the per-boundary accept cap
     `if bdy_fplans >= graph.floorplan_per_bdy_limit: break` at `1862`.
   - Candidate appended to `graph.graph_list` at `1866`, deep-copied into `original_graph_list`
     at `1867-1868`.
   - `get_encoded_matrix` at `1873`, `get_floorplan_details` at `1876-1882` (carries
     `max_width` / `max_height`).
   - `solve_min_dim(floorplan_data, plot_width, plot_height, capped)` at `1894-1896`.
   - Accept: `status == True` at `1898` -> `bdy_fplans += 1` at `1899`, geometry copied back at
     `1920-1924`, bound-area metric at `1937-1949`, `final_traversal` computed at `1951`.
   - Reject: `1964-1967` decrements `i` and pops the candidate off both lists. No message.

**Rotation pass** (`1969-2066`): duplicates every accepted plan from `original_graph_list`,
re-solves with `plot_height` and `plot_width` **swapped** (`2004-2006`), and on success writes the
geometry back transposed (`2030-2033`). Note that `1971` rebinds `number_of_floorplans` to
`len(graph.graph_list)`, using it as the loop bound at `1972` and the index offset at `1977`, so the
`graph.fpcnt` value assigned at `1839` does not survive this block. Same at `2398-2404` non-PTPG.

**Expand-only fallback** (`2069-2181`): see the dedicated section below.

**Response assembly** (`2183-2207`):
   - `2183` `elif optimal_floorplan == 1 and multiple_door is not True:`, single best plan by
     `areas_mapping.sort()` (`2184-2189`).
   - `2193` `elif multiple_door == 1:`, every accepted plan appended in `areas_mapping` order
     (`2194-2199`).
   - `2200-2203` timing plus the `max_dims_released` warning.
   - `2207` `ui._set_dim_constraints(...)` (no-op on the API path).

### C. Non-PTPG branch (2208-2651)

Structurally a copy of B with `irreg_multiple_dual` only (no `oneconnected_dual`) and with the
dummy-merge-node preprocessing added at `2306-2319` / `2418-2431` / `2549-2562`:
warning at `2211-2216`, non-dimensioned path at `2219-2239`, min-dim path at `2240-2651`,
generation at `2268`, filter loop at `2284-2395`, rotation pass at `2396-2504`,
expand-only fallback at `2505-2627`, response assembly at `2631-2651`.

### D. Response out

The handler writes nothing to a socket. Callers read `ui.get_output_data()`
(`api.py:1354`, `1413`, `1415`) and `ui.get_message()` (`api.py:1359`).

---

## Answers To The Specific Questions

### 2. How many candidates does the handler try, and where does the count come from?

There is no single constant. Four separate limits stack:

| Limit | Value | Location |
| --- | --- | --- |
| Global generator cap on `fpcnt` | 500 | `inputgraph.py:139`, enforced at `inputgraph.py:999` and `1084` |
| Accepted plans per boundary | 20 | `inputgraph.py:140`, enforced at `handlers.py:1862`, `2095`, `2287`, `2532` |
| Number of boundaries | data dependent, after `dim_on_paths_bdy` filtering (skipped entirely under cardinal pins, `inputgraph.py:959-966` / `1045-1051`) | `inputgraph.py:972` / `1057`, selection logic at `path_map.py:99-216` |
| Rotation duplication | x2 when `allow_rotation` | `handlers.py:1969-1977`, `2396-2404` |
| Final truncation | `min(min(len(outputData), limit), count)` | `api.py:1418` and `api.py:1427` |

The handler itself iterates **every** REL of **every** selected boundary and accepts up to 20 per
boundary (`handlers.py:1859-1862`). Under cardinal constraints even the per-boundary cap is lifted
to the global 500 (`inputgraph.py:862-866`).

**On the observed 2 / 14 / 30 for 2 / 3 / 4 BHK:**

- **30 is a cap, not a generation count.** `FLOORPLAN_LIMIT = 30` at `api.py:119`, and the frontend
  additionally pins both knobs to at least 30:
  `limit: Math.max(count, 30)` at
  `C:\Users\nitant\Documents\GPLAN_Revamp\gplan-building-designer\src\services\gplanApi.ts:441`
  and `count: Math.max(count, 30)` at `gplanApi.ts:444`.
  Truncation happens at `api.py:1418` / `api.py:1427`. A 4BHK returning exactly 30 is the batch
  hitting that ceiling. It says nothing about how many the handler produced.
- **2 and 14 sit below the cap**, so they are genuine post-filter counts. No constant in the code
  produces either number. They are the product of (boundaries surviving `dim_on_paths_bdy`) x
  (RELs per boundary that the longest-path solve accepts), capped at 20 per boundary, doubled by
  the rotation pass, and then reduced again by the gapless gate `rectangularize_output`
  (`api.py:801`) and, when cardinal pins are present, `filter_output_by_cardinal` (`api.py:418`).
- Both 2 and 14 are even, which is **consistent with** the rotation duplication at
  `handlers.py:1969-1977` (`rotation_enabled` defaults to 1 at `local_engine_bridge.py:103`), but
  I did not execute anything, and the rotated pass re-solves independently at `handlers.py:2004`,
  so evenness is not guaranteed by the code. I state this as consistency, not proof.

**Verdict: no code path produces 2, 14 or 30 as such, except that 30 is exactly the API/frontend
truncation ceiling (`api.py:119`, `gplanApi.ts:441`/`444`, applied at `api.py:1418`).** The other
two are emergent from the boundary and REL combinatorics for that particular graph.

### 3. Hypothesis: plot_width / plot_height are upper caps, not targets

**Verdict: BOTH, under different conditions.** Three distinct uses:

**(a) Cap: the main solve.** `solve_min_dim(floorplan_data, plot_width, plot_height, ...)` at
`handlers.py:1894-1896` (and `2004-2006` rotated, `2322-2324`, `2435-2437`) forwards to
`min_dim.main` (`minimum_dimensioning.py:767`), which installs them as globals at
`minimum_dimensioning.py:822-823` and turns each into a single negative-weight back-edge in the
constraint graph:
```
minimum_dimensioning.py:229-231   if plot_width  > 0: edgesX[2*rooms+1][0] = -1 * plot_width
minimum_dimensioning.py:311-313   if plot_height > 0: edgesY[2*rooms+1][0] = -1 * plot_height
```
That is a pure upper bound on the total span. Nothing pushes the layout toward the plot. Note the
`> 0` guards: a plot dim of 0 disables the cap entirely.

**(b) Cap plus a fill-at-least-80% target, in boundary pre-selection.**
`irreg_multiple_dual` passes the plot dims into `dim_on_paths_bdy` at `inputgraph.py:967-973`
(and the mirror at `1052-1058`), but only on the `elif` arm of a three-way branch. The first arm is
`if self.cardinal_constraints: selected_list = cip_list` (`inputgraph.py:959-966` and `1045-1051`),
with an explicit comment saying the dimension-fit pre-selector is deliberately skipped. So the
precondition is `not self.cardinal_constraints AND len(input_dims) > 0`: any request carrying
cardinal pins never runs this filter and never sees the 80-percent band, whatever plot dims were
sent. `input_dims` itself is decided by the handler at `handlers.py:1810-1813`. Inside `path_map.py`:
```
path_map.py:149-150   width_diff  = plot_width  - total_width
                      height_diff = plot_height - total_height
path_map.py:163       pointers_w = [... if 0 <= x <= 0.2 * plot_width]
path_map.py:164       pointers_h = [... if 0 <= x <= 0.2 * plot_height]
path_map.py:82-88     remaining_wt = plot_wt - total_width
                      threshold_ratio * plot_ht >= remaining_ht >= 0
                      threshold_ratio * plot_wt >= remaining_wt >= 0
```
The `>= 0` half is a cap. The `<= 0.2 * plot_*` half is a **target**: a boundary whose rooms total
less than 80 percent of the plot is rejected as "not a good fit" (`path_map.py:93`). The threshold
relaxes to 0.3 and then to a `count >= 3` rule at `path_map.py:204-214`. This is the mechanism
that collapses the candidate pool.

**(c) Target: the expand-only fallback.** `graph.scale_plot_dimension(plot_width, plot_height, valid)`
at `handlers.py:2173` (and `2619`), implemented at `inputgraph.py:597-646`:
```
inputgraph.py:616-617  scale_h = plot_height / height if height > 0 and plot_height > 0 else 1.0
                       scale_w = plot_width  / width  if width  > 0 and plot_width  > 0 else 1.0
inputgraph.py:618-619  scale_h = max(1.0, scale_h);  scale_w = max(1.0, scale_w)
```
Here the plot dims scale plans **up** to fill the plot, clamped so nothing ever shrinks. Plans are
then ranked by required plot growth at `inputgraph.py:624-626` and reordered at `642-646`.

**(d) A gate, not a comparison.** `handlers.py:1812` `if plot_width == 0 and plot_height == 0:`
blanks `input_dims`, disabling (b) entirely. Note the `and`: sending one dim as 0 and the other
non-zero still runs `dim_on_paths_bdy`, where the zero axis degenerates the filter to
`0 <= x <= 0` (`path_map.py:163` or `164`).

### 4. Hypothesis: the expand-only fallback reuses a previously collapsed pool

**Verdict: CONFIRMED.**

- Fallback branch: `handlers.py:2069` `if not floorplan_found:` (PTPG), mirror at
  `handlers.py:2505` (non-PTPG).
- The pool it draws from: `graph.graph_list_by_bdy`, iterated at `handlers.py:2092-2094`
  (and `2529-2531`), the identical structure walked by the first pass at `handlers.py:1859-1861`.
- **No regeneration happens.** Exactly one generation call executes per min-dim invocation:
  `handlers.py:1830`, or `1836` / `1838` via the `except` handlers (PTPG), or `2268` (non-PTPG).
  Grep finds six `irreg_multiple_dual` call sites inside 1686-2657 (`handlers.py:1778`, `1830`,
  `1836`, `1838`, `2232`, `2268`), but the two extra ones, `1778` and `2232`, sit on the
  `isMinDimensioned == 0` paths and cannot co-execute with the min-dim path. What matters here is
  that lines 2069-2181 and 2505-2627 contain no call at all, so the fallback never regenerates.
- **That pool was filtered earlier by the plot dims.** The single generation call received
  `input_dims` containing `plot_width` and `plot_height` (`handlers.py:1810`), and
  `irreg_multiple_dual` used them at `inputgraph.py:967-973` / `1052-1058` to run
  `dim_on_paths_bdy`, keeping only boundaries whose room spans land in the
  `[0.8 * plot, 1.0 * plot]` band described above. There are two escape hatches, not one. First,
  cardinal pins bypass the filter outright: `if self.cardinal_constraints: selected_list = cip_list`
  at `inputgraph.py:959-966` / `1045-1051` takes the branch before the dimension arm is reached.
  Second, `inputgraph.py:978-979` / `1064-1065` restores the full `cip_list` if the selection came
  back completely empty. Absent pins, and absent a total wipeout, the pool is collapsed.
- What the fallback changes: only the argument to `solve_min_dim`, at
  `handlers.py:2120-2121` `solve_min_dim(floorplan_data, 0, 0, ...)` (and `2567-2568`), which
  disables the plot cap inside the solver via the `> 0` guards at
  `minimum_dimensioning.py:229` / `311`. The per-room ceilings still apply, as the comments at
  `handlers.py:2117-2119` state.
- The per-boundary cap is still enforced in the fallback (`handlers.py:2095`, `2532`).
- The pool objects are the same instances, not copies (`handlers.py:2099`, with the author's own
  comment "may cause issues later might need to deepcopy"). This is safe only because the fallback
  runs exclusively when the first pass accepted nothing, so nothing was mutated: every failed
  candidate was popped at `handlers.py:1966-1967`.

**Practical consequence:** on a request without cardinal pins, a plot that no boundary can fill to
80 percent produces a tiny `selected_list`, and the expand-only fallback then reuses that same tiny
list rather than re-deriving boundaries with the plot constraint removed. The fallback fixes the
solver cap but not the boundary pre-selection. With cardinal pins the pre-selector never ran
(`inputgraph.py:959-966` / `1045-1051`), so the fallback reuses the full `cip_list`-derived pool and
this starvation mode does not apply.

### 5. minDimEnabled, maxDimEnabled, strictness

- **minDimEnabled**: read, four times, always through `ui.get_isMinDimensioned()`
  (`GuiParameters.py:172`), set from the request at `api.py:1231`:
  - `handlers.py:1751` `if (ui.get_isMinDimensioned() == 0):` (PTPG non-dimensioned path).
  - `handlers.py:1787` `elif (ui.get_isMinDimensioned() == 1):` (PTPG min-dim path).
  - `handlers.py:2219` `if (ui.get_isDimensioned() == 0 and ui.get_isMinDimensioned() == 0):` (non-PTPG non-dimensioned path).
  - `handlers.py:2240` `elif (ui.get_isMinDimensioned() == 1):` (non-PTPG min-dim path).
- **maxDimEnabled**: **the handler never reads it.** The token does not appear anywhere in
  `handlers.py`. It is consumed upstream at `local_engine_bridge.py:76` and `84`, where
  `open_max = min_dim_enabled and not max_dim_enabled` decides whether the per-node maxima are
  forwarded verbatim or replaced by the 99999 sentinel (`local_engine_bridge.py:91`, `95`); the
  deployed backend does the same at `gplan_backend\gplan_apis\views.py:839`. The handler sees only
  the downstream effect, via `get_max_dims(ui)` at `handlers.py:1808` and `2260`, whose sentinel
  filter is `handlers.py:328-333` (`if 0 < float(value) < 99999`). An all-sentinel list yields
  `(None, None)`, which then makes `capped` false at `handlers.py:1896` and disables the
  ceiling-release retry inside `solve_min_dim` (`handlers.py:345-353`).
- **strictness**: **the handler never reads it.** The token appears nowhere in `handlers.py`.
  It belongs to the multi-PTPG pipeline only: `...\source\ptpg_floorplanner.py:822`, `840-841`,
  `956`, `959`, and `...\source\multi_ptpg_pipeline.py:175-177`, `312`, `365`.

### 6. Error responses and which failure maps to which

The handler has no exception boundary and no structured error object. Everything is a warning
string on `ui`, or silence.

| Internal failure | Handler response | Lines |
| --- | --- | --- |
| Longest-path solve infeasible for one candidate (`compute_placement` returns False at `minimum_dimensioning.py:559`/`563`, `main` returns `[False, None]` at `833`) | **Silent drop.** Candidate popped, loop continues. No message, no counter. | `handlers.py:1964-1967`, `2166-2168`, `2392-2395`, `2614-2616` |
| Every candidate infeasible under the plot cap (`floorplan_found` still False) | Warning "No floorplan fits the given plot dimensions; room dimensions were kept and the plot was expanded to fit." then the expand-only fallback. GUI gets a `messagebox.showwarning`; API gets `ui.print_gui`, which appends to `ui.get_message()` (`GuiParameters.py:379-380`) | `handlers.py:2069-2079` and `2505-2516` |
| Per-room ceilings had to be stripped for at least one topology (`solve_min_dim` returns `released=True`) | "Warning: Room maximum dimensions were released for some floorplans." | set at `handlers.py:353`; aggregated at `1897`, `2007`, `2122`, `2325`, `2438`, `2569`; emitted at `2202-2203` and `2650-2651` |
| Graph is not a PTPG after augmentation (`checkPTPG` false) | GUI: `messagebox.showwarning` at `2212-2213`. **API: nothing at all**. `handlers.py:2216` is literally `pass#Later on return the error message to front`. The caller cannot tell. | `handlers.py:2208-2216` |
| One-connected structure too complex (`OCError`) | `show_warning("Can not generate rectangular floorplan.")` then fall through to the irregular generator | `handlers.py:1758`, `1835` (the `1835` one is unreachable, see below) |
| Biconnected graph handed to `oneconnected_dual` (`BCNError`) | Swallowed; falls through to `irreg_multiple_dual` | `handlers.py:1837-1838`, `1760-1761` |
| Augmentation impossible | `show_warning("No augmentation found")` and early `return` (**dead**, see below) | `handlers.py:1714-1716` |
| Unexpected tuple shape from `door_connectivity` | `show_warning("Unexpected return value from door_connectivity")` and early `return` (**dead**) | `handlers.py:1719-1721` |
| Even the expand-only fallback finds nothing | No message. `valid` stays empty, `ui` output list stays empty, `api.py:1419` builds a `Documents` with count 0 and the generic success message. | `handlers.py:2170-2179`, `2618-2625` |
| **Timeout** | **No timeout handling exists.** `time.time()` appears eleven times in 1686-2657 (`handlers.py:1709`, `1731`, `1764`, `1779`, `1807`, `2200`, `2222`, `2233`, `2267`, `2648`, `2656`) and every one of them only feeds a `ui.print_gui` timing string, including the four on the non-dimensioned branches (`1764`, `1779`, `2222`, `2233`). There is no deadline, no cancellation, no wall-clock guard anywhere in 1686-2657. A pathological graph runs until the 500-candidate generator cap (`inputgraph.py:139`) stops it. | n/a |

Also note `show_warning` (`handlers.py:3056-3057`) calls `messagebox.showinfo`, a tkinter call.
Reaching it on a headless server would attempt a display connection. On the API min-dim path it is
in practice unreachable (see below).

### 7. Code that can never execute

Stated plainly:

1. **`handlers.py:1712-1716` and `1719-1721` are dead.** `InputGraph.door_connectivity`
   (`inputgraph.py:340`) has exactly two `return` statements, `inputgraph.py:359`
   (`return self, True`) and `inputgraph.py:520` (`return self, check_ptpg(...)`). Both are
   2-tuples, on both the non-adj and plain paths. `len(result) == 3` is never true, so the
   `possible` check and `show_warning("No augmentation found")` never run; the `else` at `1719`
   never runs either. The 3-tuple return the code guards against is commented out at
   `inputgraph.py:371-373`.
2. **`handlers.py:1833` success path and `1834-1836` `OCError` handler are unreachable in this
   handler.** `oneconnected_dual` raises `BCNError` on its first two lines when the matrix is
   biconnected (`inputgraph.py:1209-1210`). By line 1833, `door_connectivity` has already run
   `bcn.biconnect` and written the edges (`inputgraph.py:375-380`) plus triangulation edges
   (`394-397`), so the graph is biconnected. Only the `except BCNError` at `handlers.py:1837-1838`
   fires. The author documents exactly this at `handlers.py:1825-1829` for the cardinal case; it
   holds for the non-cardinal case too. The same reasoning makes `handlers.py:1756-1758`
   (`oneconnected_dual("single")` and its `OCError` handler) unreachable in the non-dimensioned
   PTPG branch.
3. **Every `ui._set_multiple_output_found(...)` call is a no-op on the API path.**
   `GuiParameters.py:448-450` writes only when `get_gclass()` is not None. Affected lines:
   `handlers.py:1743`, `1776`, `1785`, `1845`, `2082`, `2178`, `2199`, `2210`, `2230`, `2239`,
   `2275`, `2519`, `2624`, `2643` (fourteen). Same for `ui._set_dim_constraints`
   (`GuiParameters.py:452-454`), which has three call sites inside 1686-2657:
   `handlers.py:2207`, `2259` and `2647` (the non-PTPG min-dim response assembly, immediately
   before the timing print at `2648`).
4. **`min_graph` computed in both fallbacks is discarded; `min_area` is not.**
   `handlers.py:2158-2160` picks the minimum-area index, then `handlers.py:2179` unconditionally
   sets `min_graph = 0`. Identical at `handlers.py:2607-2609` versus `2625`. `min_graph` is only
   ever read afterwards by `drawFunction` under `drawGUI` (`2181`, `2627`), so the index selection
   is dead work on the API path. `min_area` does survive: it is printed at `handlers.py:2170`
   (`"Floorplan Areas Possible:", areas, "\nOptimal Area:", min_area`) and at the non-PTPG mirror
   `2618`, both before the `min_graph = 0` overwrite. Neither value influences the returned
   geometry.
5. **`room_name` in the PTPG min-dim branch is dead.** Initialised empty at `handlers.py:1905` and
   `2014`; the loop that would populate it is commented out at `1913-1918` and `2022-2027`; it is
   never read in that branch. (In the non-PTPG branch it *is* populated at `2342-2346` / `2586-2590`
   and read at `2638`, but only under `drawGUI`.)
6. **`optimal_floorplan == 0` blocks are effectively unreachable through the bridge.**
   `handlers.py:1927-1934`, `2037-2044`, `2361-2366`, `2473-2478`. `local_engine_bridge.py:102`
   defaults `optimal_floorplan` to 1 whenever `minDimEnabled`. Separately, those blocks are also
   semantically wrong: the `break` at `1934` / `2044` / `2366` / `2478` exits only the inner
   `rel_itr` loop, so the outer boundary loop at `1859` keeps going and one plan per boundary is
   emitted, not one plan total.
7. **`handlers.py:2427` uses a stale loop variable.** Inside the non-PTPG rotation pass, the loop
   variable is `itr2` (`handlers.py:2426`) but the matrix is indexed
   `graph.graph_list[i].matrix[merge_node][j]`: `j` is left over from the bound-area loop at
   `handlers.py:2375`. This is not dead, it is a wrong-index bug, and it raises `NameError` if that
   earlier loop never bound `j` on this call. The three sibling copies get it right:
   `handlers.py:2315` and `2558` use `j` with `j` as the loop variable.
8. **`handlers.py:2656-2657` duplicates the timing print.** Both min-dim exits already printed it
   at `2200-2201` and `2648-2649`, so a min-dim request emits "Time taken" twice into
   `ui.get_message()`. Conversely the circulation `return` at `1749` skips `2656` entirely.
9. **Near-total duplication.** `handlers.py:1724-1728` versus `1735-1739`; the PTPG min-dim block
   `1787-2207` versus the non-PTPG block `2240-2651`; the first-pass loop `1859-1968` versus the
   fallback loop `2092-2168`; the forward pass versus the rotation pass `1969-2066`. Four
   near-identical copies of the same candidate-evaluation body exist in this one function.
10. **`generate_mindim_rfp` (`handlers.py:356-471`) is not called by this handler at all** and uses
    the old two-value `min_dim.main` contract at `handlers.py:390` without the ceiling-release
    retry. It is stale relative to the code path documented here.

---

## The Actual Constraints Or Formulas

- **Plot cap in the solver.** For rooms `1..n`, node `2n+1` is the right/top wall and node `0` the
  left/bottom wall. The cap is a single edge `edgesX[2n+1][0] = -plot_width`
  (`minimum_dimensioning.py:230`) and `edgesY[2n+1][0] = -plot_height`
  (`minimum_dimensioning.py:312`), only when the value is `> 0`. Feasibility is decided by
  `longest_path` on each constraint graph (`minimum_dimensioning.py:557`, `561`).
- **Per-room bounds.** `edgesX[left][right] = lb_width[i]`, `edgesX[right][left] = -ub_width[i]`
  (`minimum_dimensioning.py:237-238`); Y mirror at `319-320`.
- **Ceiling release ladder.** `solve_min_dim` (`handlers.py:338-353`): solve once with ceilings; on
  failure, deep-copy the payload, `pop('max_width')` / `pop('max_height')` from every node
  (`handlers.py:349-351`), solve again, and report `released = bool(status)` (`353`).
- **Boundary fit band.** From `path_map.py:82-88` and `163-164`, a boundary path is kept when
  `0 <= plot_dim - total_dim <= threshold * plot_dim`, with `threshold` walking 0.2 -> 0.3 and the
  accept rule walking `count == 4` -> `count >= 3` (`path_map.py:204-214`).
- **Batch ordering.** Normal path: `sort()` on `((boundArea - area_sum), area_sum)`
  (`handlers.py:1949`, `2184`). Fallback path: `sort()` on
  `max(1, grow_w) * max(1, grow_h)` where `grow = (extent * scale) / plot`
  (`inputgraph.py:624-626`, `642`).
- **Expand-only scaling.** `scale = max(1.0, plot / extent)` per axis (`inputgraph.py:616-619`),
  applied to `final_traversal`, `room_height`, `room_width`, `room_x`, `room_y`, `area`
  (`inputgraph.py:630-639`).

## Invariants And Preconditions

1. `graph` must be connected on entry, or is forced connected in place (`handlers.py:1687-1688`).
2. After `door_connectivity` returns, `graph.matrix` is biconnected and triangulated
   (`inputgraph.py:375-397`). Everything downstream assumes this, which is why `oneconnected_dual`
   always throws.
3. `graph.graph_list` indices `0..k-1` are exactly the accepted candidates in acceptance order:
   `i` increments on accept (`handlers.py:1869`) and is decremented with a `pop` on reject
   (`1965-1967`). The index list stays dense. **The fallback's `if i in valid` filter at
   `handlers.py:2176` and `2622` is correct only because of this density**, since
   `scale_plot_dimension` reorders `graph_list` (`inputgraph.py:642-646`) while `valid` holds
   pre-reorder indices. Make rejects stop popping and this silently returns the wrong plans.
4. The expand-only fallback runs only when the first pass accepted nothing, therefore
   `graph.graph_list` is empty at `handlers.py:2089` even though nothing explicitly resets it
   there (contrast `handlers.py:1841`, which does reset).
5. `graph_list_by_bdy` entries are shared objects, not copies (`handlers.py:1866`, `2099`).
   Invariant 4 is what keeps that safe.
6. `plot_width == 0 and plot_height == 0` disables both the boundary pre-selector and the solver
   cap; a single zero disables only half of each. The pre-selector is additionally skipped whenever
   `graph.cardinal_constraints` is truthy (`inputgraph.py:959-966` / `1045-1051`), independently of
   the plot dims.
7. `get_max_dims` returns `(None, None)` unless at least one value is strictly inside
   `(0, 99999)` (`handlers.py:329`).

## Failure Modes

- Silent candidate loss: an infeasible topology vanishes with no counter and no message
  (`handlers.py:1964-1967`).
- Silent empty batch: not-a-PTPG on the API path emits nothing (`handlers.py:2216`).
- Pool starvation: on requests without cardinal pins, `dim_on_paths_bdy` collapses `selected_list`,
  the expand-only fallback reuses the collapsed pool, and the response is a handful of
  near-identical plans (see question 4). Cardinal-pinned requests skip that filter
  (`inputgraph.py:959-966` / `1045-1051`) and so cannot starve this way.
- `NameError` risk at `handlers.py:2427` (stale `j`) and `IndexError` risk at `handlers.py:2181` /
  `2627` (`graph.graph_list[min_graph]` with an empty list), the latter only under `drawGUI`.
- No timeout: unbounded runtime up to the 500-candidate generator cap.
- Warnings are delivered as substrings of a single accumulated message
  (`GuiParameters.py:324-327`), so clients must string-match, e.g. the documented `expanded`
  keyword at `documentation/door_connectivity.md:150-151`.

## Coupling (what breaks if you change this)

- `graph.floorplan_per_bdy_limit` (`inputgraph.py:140`) is read by four loops here
  (`1862`, `2095`, `2287`, `2532`) and rewritten by `irreg_multiple_dual` under cardinal
  constraints (`inputgraph.py:866`). Changing it changes batch size on every door-connectivity call.
- `solve_min_dim`'s 3-tuple return (`handlers.py:353`) is consumed at six call sites here
  (`1894`, `2004`, `2120`, `2322`, `2435`, `2567`). `generate_mindim_rfp` still uses the old
  2-tuple `min_dim.main` contract at `handlers.py:390`.
- `scale_plot_dimension` (`inputgraph.py:597`) both mutates geometry and reorders `graph_list`;
  the handler's `valid` filter depends on that reorder writing exactly slots `0..k-1`
  (`inputgraph.py:643-646`). See invariant 3.
- `dim_on_paths_bdy` thresholds (`path_map.py:163-164`, `204-214`) set how many boundaries reach the
  handler on non-cardinal requests. Loosening them raises plan counts and runtime; tightening them
  pushes more requests into the expand-only fallback. Cardinal-pinned requests are unaffected,
  because they take the `cip_list` arm at `inputgraph.py:959-966` / `1045-1051`.
- `api.py:1418` / `1427` truncate to `min(len(outputData), limit, count)` with `FLOORPLAN_LIMIT = 30`
  (`api.py:119`). Raising the handler's yield does nothing visible until this is raised too.
- `rectangularize_output` (`api.py:801`) can drop plans the handler accepted; `api.py:1360-1364`
  restores the ungated set when the gate empties the batch.
- Anything reading `ui._set_multiple_output_found` on the API path will read stale state, because
  the setter is a GUI-only no-op (`GuiParameters.py:448-450`).

## Documented Behaviour Versus Actual

- `documentation/door_connectivity.md:144-151` says `plot_width` is an "upper cap ... applied only
  when > 0" and that the fallback is expand-only. **Both accurate** for the solver
  (`minimum_dimensioning.py:229`) and for `scale_plot_dimension` (`inputgraph.py:616-619`).
- The doc **omits** the second, stricter use: `dim_on_paths_bdy` additionally requires a boundary to
  fill at least 80 percent (then 70 percent) of the plot (`path_map.py:163-164`, `204-214`). Under
  that filter the plot dimension is a target, not just a cap. The filter is conditional: it runs
  only when `not self.cardinal_constraints` and `len(input_dims) > 0`
  (`inputgraph.py:959-973` / `1045-1058`).
- The doc **omits** that the expand-only fallback reuses the same pre-filtered boundary pool rather
  than regenerating without the plot constraint (`handlers.py:2092` versus the single generation
  call at `1830`/`1836`/`1838`).
- `documentation/door_connectivity.md:55-56` claims the plot-expansion fallback "drops only the
  plot cap; the ceilings continue to apply inside it." **Accurate**: `handlers.py:2120-2121` passes
  `0, 0` but keeps `max_width` / `max_height` in `floorplan_data` (`2107-2113`).
- `documentation/door_connectivity.md:40-69` documents `maxDimEnabled` as an API flag. **Accurate at
  the API boundary**, but the flag never reaches this handler; it is resolved to sentinel values
  upstream (`local_engine_bridge.py:84-95`) and re-detected here by `get_max_dims`
  (`handlers.py:328-333`).
- `documentation/door_connectivity.md:88-90` and `100-102` describe `limit` and `count`. Neither is
  visible to the handler; both act only at `api.py:1418`/`1427`.
- The doc does not mention `floorplan_per_bdy_limit = 20` or `floorplan_limit = 500`
  (`inputgraph.py:139-140`), which are the real generation bounds.

## Dead Or Duplicated Code

See question 7 above for the enumerated list with line numbers. Summary: two dead defensive
branches (`1712-1716`, `1719-1721`), two unreachable exception paths (`1756-1758`, `1833-1836`),
seventeen no-op setter calls on the API path (fourteen `_set_multiple_output_found`, three
`_set_dim_constraints`), two discarded min-graph computations
(`2158-2160`/`2179`, `2607-2609`/`2625`), one dead local (`room_name` at `1905`, `2014`), four
effectively-unreachable `optimal_floorplan == 0` blocks, one stale-variable bug (`2427`), one
duplicated timing print (`2656-2657`), and four near-identical copies of the candidate-evaluation
body inside a single 970-line function.

## Open Questions

1. Is `checkPTPG` ever false in production? It is `check_ptpg(separating_triangles1)`
   (`inputgraph.py:413-424`, `520`), and the ~440-line non-PTPG branch (`handlers.py:2208-2651`)
   exists solely for that case. If separating-triangle elimination at `inputgraph.py:436-450`
   always succeeds, that entire branch is dead and the duplication could be deleted. I did not
   trace `st.handle_non_trivial_ST_Door_connectivity` far enough to answer.
2. Exact per-BHK candidate counts require running the engine. I have shown 30 is the API cap
   (`api.py:119`, `gplanApi.ts:441`/`444`) and that 2 and 14 are emergent, but I have not executed
   anything, so I cannot say how many candidates were generated before truncation, nor how many
   `rectangularize_output` (`api.py:801`) dropped.
3. `handlers.py:1812` gates on `plot_width == 0 and plot_height == 0`. Was `or` intended? With one
   axis zero and no cardinal pins, `dim_on_paths_bdy` runs with a degenerate `0 <= x <= 0` window on that axis
   (`path_map.py:163` or `164`), which will reject nearly everything and then fall back to the full
   `cip_list` at `inputgraph.py:978-979`. That fallback probably masks the issue.
4. Does the rotation pass reliably double the batch? It re-solves with swapped plot dims
   (`handlers.py:2004-2006`), so a plan accepted upright can be rejected rotated. Whether the
   observed even counts (2, 14) come from reliable doubling needs a run to confirm.
5. `graph.graph_list = []` at `handlers.py:1841` discards the flat list `irreg_multiple_dual` built
   at `inputgraph.py:1012`/`1096`. The `graph.fpcnt` value read into `number_of_floorplans` at
   `handlers.py:1839` is then read exactly once, by the print at `1855`, before the name is
   shadowed: `handlers.py:1971` reassigns `number_of_floorplans = len(graph.graph_list)` inside the
   rotation pass, and `1972` (`for itr in range(number_of_floorplans)`) and `1977`
   (`i = itr + number_of_floorplans`) use it as a loop bound and an index offset, so from `1971`
   onward it is load-bearing control flow for the rotation duplication, not a print value. The
   non-PTPG mirror does the same at `handlers.py:2398`, `2399`, `2404`. A consequence: with
   `allow_rotation` on, the print at `2090` reports the accepted-plan count from `1971`, not
   `graph.fpcnt`. Is any caller still relying on `graph.fpcnt` itself? `api.py:1417` computes
   `hasMore = graph.fpcnt - offset - 1 > 0` from the untouched counter, which will not match the
   actual returned batch.
