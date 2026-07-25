# dim-09: Concept Trace (eight documented dimensioning concepts to code)

All paths absolute. All line numbers were read before citing. Every path below is rooted at
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN`, written here as `GPLAN\...`.

## Purpose

Eight concepts appear in the GPLAN markdown documentation but had never been mapped to code.
This dossier resolves each one to an implementing function with `file:line`, or states that the
concept is documentation-only. Seven of the eight are implemented. Two of those seven differ from
their documented semantics in ways that matter to a client, and one documented behaviour
(the "server opens the upper bound" clause of `minDimEnabled`) exists in the local development
bridge but not in the in-repo mirror of the production HTTP view.

## Where It Sits In The Pipeline

Two independent pipelines are involved. They share almost nothing.

**A. The production door-connectivity min-dim pipeline** (concepts 1 to 6):

```
HTTP view (out of tree: gplan_backend; in-repo mirrors:
  GPLAN\local_engine_bridge.py:55  _prepare
  GPLAN\GPLAN\Test_api.py:7        post)
  -> builds dim_inputs{min_width,max_width,min_height,max_height,plot_width,plot_height,...}
  -> GPLAN\GPLAN\api.py:1215  Documents.get_floorplans(minDimEnabled=..., dim_inputs=...)
     -> api.py:1227  DimParameters(...)          (GPLAN\GPLAN\pythongui\GuiParameters.py:13)
     -> api.py:1230  GuiParameters.set_isMinDimensioned(...)
     -> api.py:1353  handle_door_connectivity(ui, graph)
        -> GPLAN\GPLAN\handlers.py:1686  handle_door_connectivity
           -> handlers.py:1745  if (checkPTPG):  ... two near-duplicate min-dim blocks
              PTPG branch     handlers.py:1787-2207
              non-PTPG branch handlers.py:2240-2651
           -> handlers.py:1808  get_max_dims(ui)
           -> handlers.py:1830/1836/1838  graph.irreg_multiple_dual(input_dims)
              -> GPLAN\GPLAN\source\inputgraph.py:852  irreg_multiple_dual
                 -> inputgraph.py:972 / 1057  dim_on_paths_bdy(...)  (GPLAN\GPLAN\source\path_map.py:99)
           -> handlers.py:1894  solve_min_dim(...)  (handlers.py:338)
              -> GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:767  main
                 -> minimum_dimensioning.py:181  input_constraints -> :158 upper_bound
           -> handlers.py:2069  expand-only fallback -> inputgraph.py:597 scale_plot_dimension
     -> api.py:1358  rectangularize_output(ui)    (api.py:801)
        -> api.py:710 _fill_gaps, api.py:621 repair_dimensions
```

**B. The multi-PTPG PDF placer** (concepts 7 and 8), which does not touch A at all:

```
GPLAN\GPLAN\api.py:1775  Documents.get_multi_ptpg_floorplans
  -> GPLAN\GPLAN\source\multi_ptpg_pipeline.py:175  strictness validation
     -> multi_ptpg_pipeline.py:77   _room_dimensions   (exact sizes gate)
     -> multi_ptpg_pipeline.py:308  pfp.generate_floorplans(..., strictness=...)
        -> GPLAN\GPLAN\source\ptpg_floorplanner.py:819  generate_floorplans
           -> ptpg_floorplanner.py:954-960  the strictness ladder
              -> ptpg_floorplanner.py:603  _pdf_place
```

## Entry Points (file:line)

- `GPLAN\GPLAN\api.py:1215` `Documents.get_floorplans` (the only engine entry that reads `minDimEnabled`)
- `GPLAN\GPLAN\api.py:1775` `Documents.get_multi_ptpg_floorplans`
- `GPLAN\GPLAN\handlers.py:1686` `handle_door_connectivity`
- `GPLAN\GPLAN\handlers.py:309` `get_max_dims`
- `GPLAN\GPLAN\handlers.py:338` `solve_min_dim`
- `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:158` `upper_bound`
- `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:767` `main`
- `GPLAN\GPLAN\source\inputgraph.py:597` `scale_plot_dimension`
- `GPLAN\GPLAN\source\inputgraph.py:852` `irreg_multiple_dual`
- `GPLAN\GPLAN\source\path_map.py:99` `dim_on_paths_bdy`
- `GPLAN\GPLAN\api.py:801` `rectangularize_output`
- `GPLAN\GPLAN\source\ptpg_floorplanner.py:819` `generate_floorplans`
- `GPLAN\GPLAN\source\multi_ptpg_pipeline.py:77` `_room_dimensions`
- Transport (not engine): `GPLAN\local_engine_bridge.py:55` `_prepare`, `GPLAN\GPLAN\Test_api.py:7` `post`

## Data Structures

- `dim_inputs: dict` built by the HTTP layer. Keys `min_width, max_width, min_height, max_height,
  min_ratio, max_ratio, plot_width, plot_height, symmetric, optimal_floorplan, rotation_enabled`
  (`GPLAN\local_engine_bridge.py:77-81`, `GPLAN\GPLAN\Test_api.py:53-65`). All the per-room entries are
  parallel lists indexed by node id.
- `DimParameters` (`GPLAN\GPLAN\pythongui\GuiParameters.py:13-97`): private lists with getters
  `get_min_width`/`get_max_width`/`get_min_height`/`get_max_height`/`get_plot_width`/`get_plot_height`/
  `get_max_aspect_ratio`. This is the single carrier of dimension intent from the API into the handlers.
- `floorplan_data: dict` built by `GPLAN\GPLAN\input\input_for_min_dim.py:60` `get_floorplan_details`
  -> `{"nodes", "edges", "floorplan_type", "dimensions_needed", "corridors_needed",
  "corridor_width", "floorplan_limit", "boundary_rooms"}`. Each node dict carries `min_width`,
  `min_height`, and optionally `max_width`/`max_height` (`input_for_min_dim.py:27-38`). Dummy rooms
  from separating-triangle removal get only `min_*` keys (`input_for_min_dim.py:41-49`).
- Module-global constraint graphs in `minimum_dimensioning.py`: `edgesX`, `edgesY` (dense
  `2(rooms+1)` square matrices, `minimum_dimensioning.py:213-214`), `lb_width`/`ub_width`/
  `lb_len`/`ub_len` (`:41-44`, filled at `:200-203`).
- `rects: list[(x0,y0,x1,y1)]` in `GPLAN\GPLAN\api.py` gapless-fill code, derived from
  `plan.final_traversal` at `api.py:820-826`.
- `caps: list[(span_cap, area_cap) | None]` from `api.py:640` `_room_size_caps`.
- `bounds: list[dict | None]` with keys `minw,minh,maxw,maxh,minarea,maxarea,aspect` from
  `api.py:453` `_room_bounds`.
- `FloorplanResult` (`GPLAN\GPLAN\source\ptpg_floorplanner.py:84`) carrying `is_relaxed`,
  `encoded_matrix`, `room_rects`, `boundary`, `edge_labels`.

## Algorithm Walkthrough

### The eight-row ledger

| # | Concept | Doc citation (file + section) | Implementing code (file:line) | Does the code match the doc? | Verdict |
|---|---|---|---|---|---|
| 1 | `minDimEnabled` (minimums-only dimensioning) | `GPLAN\documentation\door_connectivity.md`, section "### Fields" / tab Request, lines 31-38 ("Used if dimensions are to be sent. By default dimensions are **minimums only** ... the server opens the upper bound (`max` is ignored and treated as 99999)"); also `GPLAN\documentation\api_reference.md:34` under "### Request Shape" | Transport: `GPLAN\local_engine_bridge.py:75,84-95`; `GPLAN\GPLAN\Test_api.py:38,66-113,148`. Engine: `GPLAN\GPLAN\api.py:1226-1232`; `GPLAN\GPLAN\handlers.py:1787` and `:2240` (`ui.get_isMinDimensioned() == 1`); lower bound applied at `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:194-203` and edge `edgesX[left][right] = lb_width[i]` at `:237` | The mode switch and the "min is a hard lower bound" half are fully implemented and traced end to end. The "max is ignored and treated as 99999" half is done **only by the transport layer**: `local_engine_bridge.py:84` computes `open_max = min_dim_enabled and not max_dim_enabled` and substitutes 99999 at `:91` and `:95`. `Test_api.py:84-90` and `:107-113` (the in-repo mirror of the production Django view) pass the client's `max` through verbatim and never compute `open_max`. The engine never zeroes a max: `api.py:1227` forwards `dim_inputs['max_width']`/`['max_height']` unconditionally whenever `minDimEnabled` is true. | PARTIAL. Differs in exactly one place: the guarantee "`max` is ignored" is not enforced anywhere in the engine, only in `local_engine_bridge.py`. On the `Test_api.py`-shaped path a client sending `minDimEnabled: true` with a real `width.max` gets that ceiling applied even though the doc promises it will be ignored. |
| 2 | `maxDimEnabled` (opt-in per-room ceilings) | `GPLAN\documentation\door_connectivity.md`, "### Fields" / tab Request, lines 40-74 | The literal name exists at exactly one non-doc, non-test site in the tree: `GPLAN\local_engine_bridge.py:76` (`data.get("maxDimEnabled", False)`), used at `:84`. Engine-side there is no such flag; the engine infers "the caller supplied ceilings" from the values themselves: `GPLAN\GPLAN\handlers.py:309-335` `get_max_dims` returns the list only if some entry satisfies `0 < float(value) < 99999` (`:329`), and `GPLAN\GPLAN\api.py:640-672` `_room_size_caps` applies the same `0 < v < 99999` sentinel test at `:665`. The ceilings then reach the solver via `handlers.py:1881` -> `GPLAN\GPLAN\input\input_for_min_dim.py:34` -> node `max_width`/`max_height` -> `minimum_dimensioning.py:195,198`. | The observable behaviour the doc describes (ceilings honoured when supplied, 99999 meaning open, `DEFAULT_UB_FACTOR = 5` bound when open at `minimum_dimensioning.py:148,168`) is implemented. The **mechanism** is not a flag: it is 99999-sentinel sniffing. `GPLAN\test_max_dimensions.py:94-113` confirms this by exercising `Documents.get_floorplans` with a hand-built `dim_inputs` and no `maxDimEnabled` key at all. | PARTIAL. Differs in that `maxDimEnabled` is a transport-only concept implemented solely in the local development bridge. The engine has no opt-in: it treats any `max` in the open interval `(0, 99999)` as binding. A production HTTP view that forwards client maxima verbatim (as `Test_api.py` does) makes `maxDimEnabled` a no-op, and per-room ceilings then apply whether or not the client opted in. |
| 3 | Maximum-Dimension Degradation Ladder | `GPLAN\documentation\door_connectivity.md`, "### Fields" / `maxDimEnabled`, the numbered list at lines 44-69 | No single named function. Rung 1: `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:147-177` (`SOLVER_UB_SLACK`, `upper_bound`). Rung 2: `GPLAN\GPLAN\handlers.py:338-353` `solve_min_dim` (deepcopy, retry with `node.pop('max_width'/'max_height')` at `:349-351`), flag propagated at `handlers.py:1897,2007,2122,2325,2438,2569`, message emitted at `handlers.py:2202-2203` and `:2650-2651`. Rung 3: `handlers.py:2069-2121` (and the duplicate at `:2505-2569`) - the plot-cap-only retry still passes `max_width=max_width, max_height=max_height` at `:2112` and calls `solve_min_dim(floorplan_data, 0, 0, ...)` at `:2120-2121`. Rung 4: `GPLAN\GPLAN\api.py:640-672` `_room_size_caps`, `:697-707` `_headroom`, `:710-784` `_fill_gaps`, driven from `:834-847` inside `rectangularize_output`; message at `api.py:872-874`. | All four rungs match the documented text, including both warning strings verbatim ("Room maximum dimensions were released for some floorplans.", `handlers.py:2203`; "Room maximum dimensions were exceeded while closing gaps in some floorplans.", `api.py:873-874`) and the span/area cap formulation `(max(w,h), w*h)` at `api.py:671`, the descending-headroom ordering at `api.py:735`, and the uncapped closing pass at `api.py:840`. | MATCH |
| 4 | `SOLVER_UB_SLACK` (2.5x ceiling widening) | `GPLAN\documentation\door_connectivity.md`, `maxDimEnabled` rung 1, lines 48-51 | `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:155` `SOLVER_UB_SLACK = float(os.environ.get("GPLAN_SOLVER_UB_SLACK", "2.5"))`; consumed at `:177` `return min(open_ub, max(value, SOLVER_UB_SLACK * low))` inside `upper_bound` (`:158`), which feeds `ub_width`/`ub_len` at `:195,198,201-203`, which become the negative back-edges `edgesX[right][left] = -ub_width[i]` (`:238`) and the Y equivalent. | Value, default and semantics match. Two details the doc leaves out: the widening is bracketed above by `DEFAULT_UB_FACTOR * low` (5x, `:148,168`), so the effective bound is `min(5*low, max(supplied, 2.5*low))` - a supplied ceiling above 5x is narrowed, not just widened; and the constant is environment-overridable (`GPLAN_SOLVER_UB_SLACK`). Sentinel handling matches: `value <= 0 or value >= 99999` falls back to the open bound (`:175-176`). | MATCH |
| 5 | `plot_width` / `plot_height` cap and the expand-only fallback | `GPLAN\documentation\door_connectivity.md`, "### Fields" / tab Request, lines 142-157 | Cap: `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:229-231` (`if plot_width > 0: edgesX[2*rooms+1][0] = -1 * plot_width`) and `:311-313` for Y; set from the caller at `:822-823`. "Send 0 for no cap": `GPLAN\GPLAN\handlers.py:1812-1813` and `:2264-2265` (`if plot_width == 0 and plot_height == 0: input_dims = []`). Fallback: `handlers.py:2069-2079` (warning "No floorplan fits the given plot dimensions; room dimensions were kept and the plot was expanded to fit.", `:2074-2075`), retry solve with `(0, 0)` at `:2120-2121`, then `graph.scale_plot_dimension(plot_width, plot_height, valid)` at `:2173`. Expand-only clamp and ranking: `GPLAN\GPLAN\source\inputgraph.py:612-628` (`scale_h = max(1.0, scale_h)`, `scale_w = max(1.0, scale_w)`, `diff = max(1.0, grow_w) * max(1.0, grow_h)`), reorder at `:642-646`. Duplicate fallback for the non-PTPG branch at `handlers.py:2505-2516` and `:2619`. | Matches the documented contract point for point: cap applied only when `> 0`; rooms never scaled below their solved minimum-satisfying size (scale clamped to `>= 1`); rooms do grow to fill a plot that is larger than needed on an axis; batch ordered by required plot growth ascending; the client-detectable keyword `expanded` is present in the emitted string. | MATCH |
| 6 | `dim_on_paths_bdy()` boundary selector and the exhaustive cardinal search | `GPLAN\documentation\cardinal_constraints.md`, "## Interactions", third bullet, lines 71-83 | Selector: `GPLAN\GPLAN\source\path_map.py:99-216` `dim_on_paths_bdy` (20 percent width/height pointers at `:163-164`; helper `paths_after_select_bdy` at `:48-97`; reflection dedup `remove_reflections` at `:28-34`; three-attempt threshold ladder 0.2/count==4, 0.3/count==4, 0.3/count>=3 at `:204-214`). Call sites: `GPLAN\GPLAN\source\inputgraph.py:972-973` and `:1057-1058`, guarded by `elif (len(input_dims) > 0)` at `:967` and `:1052`. Cardinal skip: `inputgraph.py:959-966` and `:1045-1051` (`selected_list = cip_list`). Per-boundary cap lift: `inputgraph.py:862-866` (`self.floorplan_per_bdy_limit = self.floorplan_limit`), with the constants at `:139-141` (`floorplan_limit = 500`, `floorplan_per_bdy_limit = 20`); the lifted cap is consumed at `handlers.py:1862` and `:2095`. Boundary filter with 8 symmetries: `inputgraph.py:1365` `filter_boundaries_by_cardinal`, called at `:951` and `:1037`. | Matches. The documented 500-candidate global ceiling is `floorplan_limit = 500` (`inputgraph.py:139`), enforced at `:999-1000` and `:1084-1085`. One nuance the doc does not state: `dim_on_paths_bdy` only ever runs when a plot cap was supplied, because `input_dims` is emptied when both plot dimensions are 0 (`handlers.py:1812-1813`), so on the common `plot_width: 0` request the selector is inert with or without cardinal pins. A second nuance: if the selector returns nothing the code silently reverts to the full candidate list (`inputgraph.py:978-979`, `:1064-1065`). | MATCH |
| 7 | strictness levels `exact`, `relaxed`, `best_effort` | `GPLAN\documentation\multi_ptpg_api.md`, "### `strictness`", lines 84-96 (table of gaps / extra walls / missing adjacency) | `GPLAN\GPLAN\source\ptpg_floorplanner.py:816` `STRICTNESS_LEVELS = ("exact", "relaxed", "best_effort")`; ladder at `:954-960` (`run_pass(is_relaxed=False)`, then `keep_best(run_pass(is_relaxed=True))` for relaxed/best_effort, then `keep_best(run_pass(is_relaxed=True, require_all=False))` for best_effort only); rejection of unknown levels at `:840-841`. Pass semantics in `_pdf_place` (`:603-611`) and the required/actual edge check at `:801-806`. Validation and default at `GPLAN\GPLAN\source\multi_ptpg_pipeline.py:175-177`; forwarded at `:312`; echoed into `stats` at `:365`. | Matches the documented ordering and the documented cell values. One undocumented refinement: `keep_best` (`ptpg_floorplanner.py:948-952`) is applied to the **relaxed** pass as well as to best-effort, so a `relaxed` request is additionally filtered to the layouts with the fewest extra walls, which the doc's table does not mention. This narrows the result set; it never widens it, so it does not contradict the table. | MATCH |
| 8 | "Exact Room Sizes, Not Minimums" (multi-PTPG PDF placer contract) | `GPLAN\documentation\multi_ptpg_api.md`, "### Room sizes are exact, not minimums", lines 76-81 | `GPLAN\GPLAN\source\multi_ptpg_pipeline.py:77-115` `_room_dimensions`: missing `width`/`height` raises `MultiPTPGError("... this API places rooms at exact sizes, not minimums")` (`:90-94`), integer rounding `int(round(float(w)))` (`:95-96`), non-positive rejection (`:97-100`), invented-room sizing from `added_room_width`/`added_room_height` or the smallest client room (`:105-113`). Placer side: `GPLAN\GPLAN\source\ptpg_floorplanner.py:843-844` (`rw`/`rh` as ints) and the contract statement in the docstring at `:836`; `_pdf_place` consumes `rw`/`rh` at `:631,637,654` and the compaction helper mutates only x and y (`:466-477`). | Matches, including the documented "rounded to integers because the placer works on integer cells" and the "pre-scale, send centimetres" consequence (rounding is unconditional at `:95-96`). The synthetic-room path documented in "## 4. Rooms the engine invents" also matches (`:105-113`). | MATCH |

### Rung-by-rung detail for the ladder (concept 3)

1. **Solver widening.** `minimum_dimensioning.input_constraints` (`:181`) calls `upper_bound`
   (`:158`) per axis per room. With no supplied max, or the 99999 sentinel, the bound is
   `5 * min` (`:148,168`). With a supplied max in `(0, 99999)` the bound is
   `min(5*min, max(supplied, 2.5*min))` (`:177`). The bound becomes a negative back-edge in the
   X and Y constraint graphs (`:238` and the Y analogue at `:307+`), so an infeasible bound shows
   up as a longest-path failure and `main` returns `[False, None]` (`:831-833`).
2. **Per-topology release.** `handlers.solve_min_dim` (`:338`) deepcopies the payload only when
   `capped` (`:345`), runs `min_dim.main` (`:346`), and on failure strips `max_width`/`max_height`
   from every node (`:349-351`) and reruns. It returns `(status, out_data, released)`; the third
   element is `bool(status)`, so it is True only when the release actually produced a plan.
3. **Plot-cap-only retry.** `handlers.py:2069` fires when no plan survived the capped pass. It
   still hands the ceilings to `get_floorplan_details` (`:2112`) and only zeroes the plot in the
   `solve_min_dim(..., 0, 0, ...)` call (`:2120-2121`). Ordering then goes through
   `scale_plot_dimension` (`:2173`).
4. **Gapless fill.** `rectangularize_output` (`api.py:801`) computes `caps` (`:834`), runs the
   capped fill (`:836`), and only if the plan is still not gapless runs the uncapped fill
   (`:840`) and sets `caps_broken` when a ceiling was actually exceeded (`:846-847`).
5. **Undocumented fifth step.** `repair_dimensions` (`api.py:621`, gated by
   `REPAIR_DIMENSIONS = os.environ.get("GPLAN_REPAIR_DIMS", "1") == "1"` at `:618`) runs after
   the fill (`api.py:856-858`) and re-solves the shared wall lines against the full band from
   `_room_bounds` (`api.py:453-510`: min/max width, min/max height, min/max area, aspect). This
   can move a room back inside its ceiling after step 4 broke it, and it is not mentioned in
   `door_connectivity.md` at all.

## The Actual Constraints Or Formulas

- Upper bound per room axis (`minimum_dimensioning.py:168-177`):
  `open_ub = DEFAULT_UB_FACTOR * low` with `DEFAULT_UB_FACTOR = 5` (`:148`);
  `ub = open_ub` if `supplied is None`, unparseable, `<= 0`, or `>= 99999`;
  otherwise `ub = min(open_ub, max(supplied, SOLVER_UB_SLACK * low))` with
  `SOLVER_UB_SLACK = 2.5` (`:155`).
- Constraint-graph encoding (`minimum_dimensioning.py:237-240`):
  `edgesX[2i-1][2i] = lb_width[i]`, `edgesX[2i][2i-1] = -ub_width[i]`.
- Plot cap (`minimum_dimensioning.py:229-231`, `:311-313`):
  `if plot_width > 0: edgesX[2*rooms+1][0] = -plot_width` (same shape for Y).
- Expand-only scaling (`inputgraph.py:616-619`):
  `scale_w = max(1.0, plot_width/width if width > 0 and plot_width > 0 else 1.0)`, same for height.
- Expansion ranking key (`inputgraph.py:624-626`):
  `diff = max(1, (width*scale_w)/plot_width) * max(1, (height*scale_h)/plot_height)`, sorted ascending
  (`:642`).
- Room ceilings in the fill (`api.py:671`): `caps[i] = (max(max_w, max_h), max_w * max_h)`.
- Axis limit given the other axis (`api.py:687-694`):
  `min(span_cap, area_cap / other_side)` when `other_side > 0`, else `span_cap`.
- Fill visit order (`api.py:735`): descending `_headroom = area_cap - current_area`, recomputed each
  round; uncapped rooms are `float('inf')` (`api.py:705`).
- Gapless test (`api.py:787-798`): `abs(sum(room areas) - bounds_area) <= bounds_area * 1e-3`.
- `dim_on_paths_bdy` acceptance window (`path_map.py:163-164`):
  keep a path when `0 <= plot_width - total_width <= 0.2 * plot_width` (and the height analogue),
  relaxed to 0.3 and then to `count >= 3` at `path_map.py:204-214`.
- Multi-PTPG size rounding (`multi_ptpg_pipeline.py:95-96`): `int(round(float(w)))`.
- Adjacency score used by `keep_best` (`ptpg_floorplanner.py:944-946`):
  `-(len(required - actual) + len(actual - required))`.

## Invariants And Preconditions

- `dim_inputs['max_width']` and `['max_height']` are always present keys whenever `minDimEnabled`
  is true; `api.py:1227` indexes them without `.get`, so a caller that omits either raises `KeyError`.
- 99999 is the universal "open" sentinel. It is tested independently in four places and must stay
  consistent: `handlers.py:329`, `api.py:665`, `api.py:499-502`, `minimum_dimensioning.py:175`.
- `get_max_dims` returns the whole list or `None`; it never returns a partially cleaned list
  (`handlers.py:322-333`). A list of all-99999 entries is treated as no ceiling at all.
- Dummy rooms created by separating-triangle removal have no `max_width`/`max_height` key
  (`input_for_min_dim.py:41-49`), so `_room_size_caps` leaves them uncapped
  (`api.py:670-671`) and `_room_bounds` returns `None` for them (`api.py:496-498`).
- `input_dims` is `[]` whenever both plot dimensions are 0 (`handlers.py:1812-1813`,
  `:2264-2265`), which is what disables `dim_on_paths_bdy`.
- In the expand fallback loop the success index is contiguous: `i` is incremented at
  `handlers.py:2100` and decremented with a `graph_list.pop()` on failure at `:2167-2168`, so
  `valid` is exactly `[0..k-1]`. `scale_plot_dimension` reorders `self.graph_list` in place
  (`inputgraph.py:642-646`) and the caller then re-filters by `i in valid` (`handlers.py:2176`).
  This is only correct **because** `valid` is contiguous from 0.
- `minimum_dimensioning` is module-global state; `main` calls `reinitialize()` first
  (`:769`, definition at `:729-752`). It is not reentrant and not thread safe.
- `_fill_gaps` guarantees rooms stay axis-aligned rectangles and never overlap; it only ever moves
  a side outward to the nearest obstruction (`api.py:740-783`), bounded by a 200-iteration guard
  (`:732`).
- `repair_dimensions` moves shared wall lines only, so gaplessness and adjacency survive
  (`api.py:624-626`), and the caller re-verifies with `_rects_overlap` and `_is_gapless` before
  accepting the repair (`api.py:857-858`).
- Multi-PTPG requires every client node to carry positive `width` and `height`
  (`multi_ptpg_pipeline.py:90-100`); there is no minimums mode on that endpoint.

## Failure Modes

- **`maxDimEnabled` silently inert.** Any HTTP view that is not `local_engine_bridge.py` and does
  not implement `open_max` will apply client ceilings unconditionally under `minDimEnabled`, which
  contradicts `door_connectivity.md:33-38`. `Test_api.py:84-113` is exactly such a view.
- **`min == max` requests.** The doc explicitly warns against `min = max` (`door_connectivity.md:36-37`).
  The code's reason is `upper_bound`: a supplied `max == min` is widened to `2.5 * min`
  (`minimum_dimensioning.py:177`), so exact sizing is unobtainable on this path by construction.
- **No plan under the plot cap.** `min_dim.main` returns `[False, None]` per topology
  (`minimum_dimensioning.py:831-833`); if every topology fails, `floorplan_found` stays False and
  the expand-only fallback at `handlers.py:2069` runs. If that also finds nothing, the batch is
  empty and only the warning string is returned.
- **Ceilings too tight.** Rung 2 strips them per topology (`handlers.py:349-351`) and the message
  gains the "released" notice (`:2203`). Rung 4 can additionally exceed them while closing holes
  (`api.py:840,846-847`) and the message gains the "exceeded while closing gaps" notice
  (`api.py:873-874`). A batch carrying neither notice is inside its ceilings, as documented.
- **Warning loss across the cardinal retry.** `api.py:1400-1405` re-captures `ui.get_message()`
  after a retry precisely because the earlier capture at `:1359` predates it. If a future edit
  reorders those, "plot was expanded" and both max-dimension notices disappear from the response.
- **`dim_on_paths_bdy` returns nothing.** Falls back to the unfiltered `cip_list`
  (`inputgraph.py:978-979`, `:1064-1065`), so a bad plot ratio degrades to the full sweep rather
  than to zero plans. It also prints heavily to stdout (`path_map.py:75,93,110,120,124-125,135,
  142,152,166-167,173-177,181,185,188,200,208,213`); that output is suppressed only because
  `api.get_floorplans` monkeypatches `builtins.print` at `api.py:1217-1222` and restores it at
  `:1454`. An exception between those two lines leaks a dead `print`.
- **Multi-PTPG strictness typo.** Rejected twice: `multi_ptpg_pipeline.py:176-177` raises
  `MultiPTPGError`, and `ptpg_floorplanner.py:840-841` raises `ValueError` if it somehow gets
  through.
- **Multi-PTPG sub-unit sizes.** `int(round(...))` at `multi_ptpg_pipeline.py:95-96` silently
  collapses 0.4 to 0 and then raises "non-positive dimension" at `:97-100`.

## Coupling (what breaks if you change this)

- **Change the 99999 sentinel** and you must change all four sites listed under Invariants plus
  both transport files (`local_engine_bridge.py:91,95`; `Test_api.py:88,111`) plus the default in
  `local_engine_bridge.py:61` / `Test_api.py:18`.
- **Change `DEFAULT_UB_FACTOR` or `SOLVER_UB_SLACK`** (`minimum_dimensioning.py:148,155`) and the
  `test_max_dimensions.py` fixtures break by design: `LOOSE_CAPS` at `test_max_dimensions.py:78`
  is built as 3x the minimum specifically to sit between 2.5x and 5x (comment at `:76-77`).
- **Change `_room_size_caps` to a per-axis cap** and the rotation pass breaks: the span cap is
  deliberately `max(max_w, max_h)` because the rotation pass may already have swapped axes
  (`api.py:644-648`).
- **Disable `repair_dimensions`** (set `GPLAN_REPAIR_DIMS=0`, `api.py:618`) and room measurements
  revert to whatever the greedy fill produced; the arrangement is unaffected.
- **Remove the cardinal skip of `dim_on_paths_bdy`** (`inputgraph.py:959-966`, `:1045-1051`) and
  the N/E/S/W path assignment is scrambled again, because `paths_after_select_bdy` rebuilds the
  four paths at arbitrary even/odd slots (`path_map.py:62-73`).
- **Raise `floorplan_per_bdy_limit`** (`inputgraph.py:140`) and the min-dim loops at
  `handlers.py:1862` and `:2095` do proportionally more `solve_min_dim` work; under cardinal pins
  it is already lifted to 500 (`inputgraph.py:866`).
- **Touch `scale_plot_dimension`'s reorder** (`inputgraph.py:642-646`) and you must preserve the
  contiguity assumption described under Invariants, or the caller's `i in valid` filter
  (`handlers.py:2176`) selects wrong plans.
- **Edit either min-dim block in `handlers.py`** and you must edit the other: `handlers.py:1787-2207`
  (PTPG) and `handlers.py:2240-2651` (non-PTPG) are near-identical copies selected by
  `if (checkPTPG):` at `handlers.py:1745`.
- **Multi-PTPG is fully decoupled** from all of the above: it never calls
  `irreg_multiple_dual`, `min_dim.main`, `rectangularize_output`, or `scale_plot_dimension`
  (stated at `multi_ptpg_api.md:31-32`, and confirmed by the call graph in
  `multi_ptpg_pipeline.py:308-312`).

## Dead Or Duplicated Code

- **Duplicated min-dim handler blocks.** `GPLAN\GPLAN\handlers.py:1787-2207` and
  `:2240-2651` are near-verbatim copies of the same min-dim algorithm, including both
  `max_dims_released` warnings (`:2202-2203` and `:2650-2651`), both expand-only fallbacks
  (`:2069-2079` and `:2505-2516`), and both `scale_plot_dimension` calls (`:2173` and `:2619`).
  Every one of the eight concepts that touches the handler exists twice.
- **Duplicated transport preparation.** `GPLAN\local_engine_bridge.py:55-129` and
  `GPLAN\GPLAN\Test_api.py:7-159` are two copies of the same request-preparation logic. They have
  already drifted: only the bridge implements `maxDimEnabled` and `open_max`.
- **`Test_api.py` is a mirror, not the production view.** It does `from api import *` at
  `Test_api.py:1` and defines a bare `post(request, shape)` at `:7` with no Django decorator.
  The real view lives in the separate `gplan_backend` repository and is not in this tree.
  Anything it claims about production behaviour must be verified there.
- **`minimum_dimensioning.py` merge scar.** `:770`, `:805-813` still carry raw conflict markers
  (`# <<<<<<< main`, `# =======`, `# >>>>>>> Door_connectivity_cleanup`) around a commented-out
  `json.load` branch. Dead but load-bearing to nobody.
- **`minimum_dimensioning.py:1-21`** is a commented-out file-based input harness, and `:844-845`
  calls `main("input_to_min_dim.json")` with one argument against a three-argument signature
  (`:767`). That `__main__` block would raise `TypeError` if executed.
- **`handlers.py:390`** in `generate_mindim_rfp` calls `min_dim.main(...)` directly rather than
  `solve_min_dim`, so that GUI-era path gets no ceiling release. It also receives no
  `max_width`/`max_height` (`:383-387`), so it is uncapped by construction. Not on the API path.
- **`path_map.py:199-200`** has an `else` attached to `if width_paths:` whose message text
  ("No combination of walls found ...") is printed whenever `width_paths` is empty even if
  `height_paths` succeeded. Cosmetic, but the message is misleading.

## Open Questions

1. Does the production Django view in `gplan_backend` implement `maxDimEnabled` and `open_max`
   the way `local_engine_bridge.py:84-95` does? This tree cannot answer it, and the answer decides
   whether ledger rows 1 and 2 are PARTIAL only locally or PARTIAL in production. Resolve by
   grepping `gplan_apis/views.py` in the backend repo for `maxDimEnabled`.
2. `repair_dimensions` (`api.py:621`) is a fifth ladder rung that the `maxDimEnabled` section of
   `door_connectivity.md` does not mention. It runs by default (`GPLAN_REPAIR_DIMS` defaults to
   "1", `api.py:618`) and can pull a room back inside its ceiling after rung 4 broke it, which
   means the documented "a batch carrying neither warning is fully within its ceilings" is
   conservative but the converse ("a batch carrying the warning has a violation") may no longer
   hold: `caps_broken` is set at `api.py:846-847` **before** the repair runs at `:856`.
3. `keep_best` on the relaxed pass (`ptpg_floorplanner.py:957`) filters by adjacency score even
   when no adjacency can be missing. Is the extra-wall filtering intentional, or should
   `keep_best` apply only to the best-effort pass? The doc table implies the latter.
4. I read `push_chain` (`ptpg_floorplanner.py:466-477`) and confirmed it mutates only indices 0
   and 1 of each rect. I did not read the rest of `compact_and_resolve_overlaps`
   (`:456-600`), so "exact sizes survive compaction" is verified for the push phase only, not for
   the pull-together phase.
5. `dim_on_paths_bdy` is fed `input_dims[0]`/`input_dims[1]`, which are the **minimum** widths and
   heights (`handlers.py:1810`, consumed at `inputgraph.py:968-969`). Fitting boundaries against
   minimums while the plot cap is an absolute upper bound is a deliberate choice per the
   door-connectivity memory note, but no doc states it. Worth documenting.
6. `local_engine_bridge.py:99-100` defaults `plot_width`/`plot_height` to 0 while
   `dim_inputs` initialises them to -1 (`:79`). The -1 value is only reachable when neither
   `dimensioned` nor `minDimEnabled` is set, in which case nothing reads it. Confirm no
   downstream code treats -1 as a cap: `minimum_dimensioning.py:229` tests `> 0`, so it does not,
   but `multi_ptpg_pipeline.py:180-181` uses -1 as its own "unconstrained" sentinel, which is a
   different convention in the same repo.
