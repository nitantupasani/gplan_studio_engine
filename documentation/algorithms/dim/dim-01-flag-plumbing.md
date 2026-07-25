# dim-01: Flag Plumbing (dimensioning inputs, payload to consumer)

Scope: every dimensioning input named in the task (`minDimEnabled`, `maxDimEnabled`,
`plot_width`, `plot_height`, strictness levels `exact` / `relaxed` / `best_effort`), traced
from the HTTP body to the line that consumes it. All line numbers below were read, not
inferred.

Repos touched:

- `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\gplan_apis\views.py` (production HTTP layer)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\local_engine_bridge.py` (local dev HTTP layer)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py` (engine facade, `Documents`)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\pythongui\GuiParameters.py` (`DimParameters`, `GuiParameters`)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\input\input_for_min_dim.py`, `...\input\input_template.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py` (the LP / longest-path solve)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py`, `...\source\path_map.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\multi_ptpg_pipeline.py`, `...\source\ptpg_floorplanner.py` (strictness lives here and only here)

---

## Purpose

There is no single "dimension parameter parser" in this system. There are **four independent
payload parsers** with **four different default sets**, feeding **two structurally unrelated
consumers** (`DimParameters` for the door-connectivity min-dim solver, plain dicts for
space-opt / GA / multi-PTPG). This dossier maps each flag to the exact read site and calls
out the ones that are parsed and never read.

## Where It Sits In The Pipeline

```
HTTP body
  |
  +-- views.py GenerateFloorplanView            -> dim_inputs dict -> Celery -> Documents.get_floorplans
  +-- local_engine_bridge._prepare              -> dim_inputs dict            -> Documents.get_floorplans
  +-- Documents.get_space_optimized_floorplan   -> params dict     -> handle_space_optimization
  +-- Documents.get_ga_optimized_floorplan      -> floorplan_data  -> handle_ga_optimization
  +-- multi_ptpg_pipeline.generate_...          -> locals          -> ptpg_floorplanner.enumerate...

Documents.get_floorplans
  -> DimParameters (api.py:1227 / 1229)
  -> GuiParameters.min_dim_inputs (api.py:1232)
  -> handle_door_connectivity (handlers.py:1686)
       -> ui.min_dim_inputs.get_*() (handlers.py:1806, 2257)
       -> get_max_dims(ui) (handlers.py:1808, 2260)
       -> graph.irreg_multiple_dual(input_dims) -> path_map.dim_on_paths_bdy   [plot dims, mins only]
       -> input_for_min_dim.get_floorplan_details(..., max_width=, max_height=)
       -> solve_min_dim -> minimum_dimensioning.main(data, plot_width, plot_height)
            -> upper_bound() (minimum_dimensioning.py:158)   [the 99999 comparison]
            -> construct_constraintgraphX/Y                  [the actual constraints]
  -> api.rectangularize_output(ui) -> _room_size_caps / _fill_gaps / repair_dimensions
```

---

## Entry Points (file:line)

| Flag | Parsed (prod) | Parsed (local bridge) | Notes |
|---|---|---|---|
| `minDimEnabled` | `views.py:835` | `local_engine_bridge.py:75` | camelCase JSON -> `min_dim_enabled` snake local |
| `maxDimEnabled` | `views.py:839` | `local_engine_bridge.py:76` | never leaves the HTTP layer, see below |
| `plot_width` | `views.py:903` | `local_engine_bridge.py:99` | already snake_case in JSON, no transform |
| `plot_height` | `views.py:904` | `local_engine_bridge.py:100` | already snake_case in JSON, no transform |
| `plot_width` (GA) | `api.py:1684` | n/a | different default (40) |
| `plot_height` (GA) | `api.py:1685` | n/a | different default (30) |
| `plot_width` / `plot_height` (multi-PTPG) | `multi_ptpg_pipeline.py:180-181` | same | different default (-1) |
| `strictness` | `multi_ptpg_pipeline.py:175` | echoed for logging at `local_engine_bridge.py:145` | multi-PTPG only |

---

## Data Structures

### `DimParameters` (`GuiParameters.py:13-102`)

Fields declared `GuiParameters.py:14-24`, constructor `GuiParameters.py:25`, assignments
`GuiParameters.py:26-35`. Name-mangled private attrs (`_DimParameters__min_width` etc.),
accessed only through getters `GuiParameters.py:38-102`.

Constructed at exactly two sites:

- `api.py:1227` (minDim branch): min/max width, min/max height, plot_width, plot_height,
  isOptimalEnabled, isRotationAllowed. **No ratios, no symmetric.**
- `api.py:1229` (legacy `dimensioned` branch): adds min_ratio, max_ratio, symmetric; omits
  isRotationAllowed.

Stored on the UI object at `api.py:1232` via `set_min_dim_inputs` (`GuiParameters.py:144-146`),
attribute `GuiParameters.min_dim_inputs` (declared `GuiParameters.py:130`).

### `dim_inputs` dict (the wire format between HTTP layer and engine)

Keys and their pre-population defaults: `views.py:856-868` and `local_engine_bridge.py:77-81`.
Both initialise `plot_width: -1, plot_height: -1`, then overwrite with `0` when
`dimensioned or min_dim_enabled` (`views.py:903-904`, `local_engine_bridge.py:99-100`).

### min-dim payload node (`input_template.py:42-48`, `70-76`, `95-99`)

`min_width` / `min_height` always written; `max_width` / `max_height` written **only when not
None** (`input_template.py:45-48`, `73-76`). So an uncapped run produces nodes with no
`max_*` key at all, and `node.get('max_height')` in `minimum_dimensioning.py:195` returns
`None`.

---

## Algorithm Walkthrough Per Flag

### 1. `minDimEnabled`

1. **Parsed**: `views.py:835` (`request.data.get("minDimEnabled", False)`), local bridge
   `local_engine_bridge.py:75`. camelCase JSON key -> `min_dim_enabled` snake_case local.
2. **Defaulted**: `False` at both sites. Also gates the whole dim block:
   `views.py:878` `if dimensioned or min_dim_enabled:` and `local_engine_bridge.py:85`.
3. **Stored**: forwarded verbatim as the `minDimEnabled` key of `prepared_data`
   (`views.py:921`, `local_engine_bridge.py:117`) -> `Documents.get_floorplans` kwarg
   (`api.py:1216`) -> `GuiParameters.set_isMinDimensioned(minDimEnabled)` (`api.py:1231`),
   which normalises `None` to `0` (`GuiParameters.py:175-180`) into `__isMinDimensioned`.
4. **Read downstream**: `api.py:1226` (decides which `DimParameters` overload is built), and
   in handlers via `get_isMinDimensioned()`:
   - `handlers.py:1751` (door-connectivity, PTPG branch: `== 0` -> undimensioned dual)
   - `handlers.py:1787` (door-connectivity, PTPG branch: `== 1` -> min-dim solve)
   - `handlers.py:2219` (door-connectivity, non-PTPG / irregular branch; a compound test
     `get_isDimensioned() == 0 and get_isMinDimensioned() == 0`, so unlike the PTPG twin at
     `handlers.py:1751` it also reads `dimensioned`), `handlers.py:2240` (`== 1` -> min-dim solve)
   - `handlers.py:499`, `657` (circulation), `754`, `769` (`handle_single`), `1079`, `1189`
     (`handle_single_oc`), `1328`, `1350` (`handle_multiple_oc`)
5. **Dead?** No. Live and load-bearing.

### 2. `maxDimEnabled`: parsed at the HTTP layer, invisible to the engine

1. **Parsed**: `views.py:839`, `local_engine_bridge.py:76`. camelCase -> `max_dim_enabled`.
2. **Defaulted**: `False`.
3. **Stored**: **nowhere**. It is not a key of `prepared_data` (`views.py:910-933`) and not a
   kwarg of `_prepare`'s return (`local_engine_bridge.py:105-129`). It is not a parameter of
   `Documents.get_floorplans` (`api.py:1215-1216`).
4. **Read**: only at the parse site itself, as a branch on how to fill `max_width` /
   `max_height`:
   - `views.py:888-892`: `if min_dim_enabled and not max_dim_enabled: max_width = 99999`
     else `_bound(node["width"], "max", 99999)`
   - `views.py:895-899`: same for height
   - `local_engine_bridge.py:84` computes `open_max = min_dim_enabled and not max_dim_enabled`,
     applied at `local_engine_bridge.py:91` and `:95`
5. **Dead?** Not dead, but **the engine has no concept of it.** `grep -rn "maxDimEnabled\|max_dim_enabled"`
   over `GPLAN\GPLAN\` returns **zero matches**. The engine re-derives "did the caller supply
   ceilings?" by *sniffing the values*: `get_max_dims` (`handlers.py:309-335`) scans the max
   lists and returns `None, None` unless some entry satisfies `0 < float(value) < 99999`
   (`handlers.py:329`). This is a value-sniffing contract, not a flag contract, and it is the
   root of the coupling described below.

### 3. `plot_width` / `plot_height` (door-connectivity path)

1. **Parsed**: `views.py:903-904`, `local_engine_bridge.py:99-100`. Snake_case in JSON already;
   no name transform. Read **only inside** the `if dimensioned or min_dim_enabled:` block, so a
   plot sent without `minDimEnabled` is silently discarded (the dict keeps the `-1` from
   `views.py:863-864`).
2. **Defaulted**: `0` here (`views.py:903`), but `-1` in the dict initialiser
   (`views.py:863-864` / `local_engine_bridge.py:79`). Two different "no plot" sentinels for
   the same key.
3. **Stored**: `DimParameters.__plot_width` / `__plot_height` (`GuiParameters.py:30-31`),
   built at `api.py:1227` (minDim) and `api.py:1229` (legacy dimensioned).
4. **Read downstream** (door-connectivity):
   - `handlers.py:1806` and `handlers.py:2257` unpack them via `get_plot_width()` /
     `get_plot_height()` (`GuiParameters.py:62-72`).
   - `handlers.py:1810` / `2262`: packed into `input_dims = [min_width, min_height, plot_width, plot_height]`.
   - `handlers.py:1812` / `2264`: `if plot_width == 0 and plot_height == 0: input_dims = []`
     (turns off boundary pre-selection entirely).
   - `inputgraph.py:967-973` and `inputgraph.py:1052-1057`: `input_dims[2]`/`[3]` unpacked and
     handed to `path_map.dim_on_paths_bdy`. **Boundary pre-selection, not a constraint**: the
     plot is used as a target total in `path_map.py:149-150`
     (`width_diff = plot_width - total_width`) and filtered at `path_map.py:163-164`
     (`0 <= x <= 0.2 * plot_width`). This is the "collapses the boundary pool" behaviour.
   - `handlers.py:1895` / `2323`: `solve_min_dim(floorplan_data, plot_width, plot_height, ...)`.
   - `handlers.py:2005` / `2436`: **axes swapped** (`plot_height, plot_width`) for the rotation pass.
   - `minimum_dimensioning.py:822-823`: written into module globals.
   - `minimum_dimensioning.py:229-231`: `if plot_width > 0: edgesX[2*rooms+1][0] = -1 * plot_width`
     (the real X constraint edge).
   - `minimum_dimensioning.py:311-313`: same for `plot_height` on Y.
   - `handlers.py:2120-2121` / `2567-2568`: the expand fallback calls `solve_min_dim(floorplan_data, 0, 0, ...)`,
     i.e. plot cap dropped entirely.
   - `inputgraph.py:597-639` (`scale_plot_dimension`), called at `handlers.py:2173` / `2619`:
     expand-only rescale, `scale = max(1.0, plot/extent)` (`inputgraph.py:616-619`), plans
     ranked by required growth (`inputgraph.py:624-628`).
   - `handlers.py:2207` / `2647`: echoed back into `ui._set_dim_constraints`.
5. **Dead?** No, but see Dead Or Duplicated for the **one-connected stacked path, where the
   caller's plot is hardcoded away**.

### 4. `plot_width` / `plot_height` (GA path)

- Parsed `api.py:1684-1685`, defaults **40 / 30** (nothing like the door-connectivity 0/-1).
- Stored in a plain dict `floorplan_data` (`api.py:1683-1691`), passed to
  `handle_ga_optimization` (`api.py:1701-1705`, handler at `handlers.py:2845`).
- Read: `handlers.py:3029-3030` (`int(floorplan_data["plot_width"])`) and inside
  `Space_Optimization\ga_current.py:61-62`, `:468-469` where they size the grid
  (`ga_current.py:472`, `:475`) and clamp room extents (`ga_current.py:538`, `:540`, `:552`).
- No `DimParameters`, no `min_dim`, no 99999 anywhere on this path.

### 5. `plot_width` / `plot_height` (multi-PTPG path)

- Parsed `multi_ptpg_pipeline.py:180-181`, default **-1**.
- Read in `ptpg_floorplanner.py:865` (passed into the placer) and `ptpg_floorplanner.py:889`
  (`plot_w > 0 or plot_h > 0` gates a fallback pass).

### 6. `space_optimization` has no plot and no dim flags at all

`Documents.get_space_optimized_floorplan` (`api.py:1458`) reads `regions`, `boundary`, `rooms`,
`fixed_rooms`, `adjacency`, `non_adjacency`, `entrance_coords`, `max_attempts`
(`api.py:1493-1499`, `:1559`). There is **no** `plot_width`, `plot_height`, `minDimEnabled`,
`maxDimEnabled`, or `strictness`. Per-room sizing is `room['width']`, `room['height']`,
`room.get('max_expansion', 20)` (`handlers.py:2713-2718`) and
`fixed_room.get('max_expansion', 0)` (`handlers.py:2737`).

### 7. Strictness levels `exact` / `relaxed` / `best_effort`

1. **Parsed**: `multi_ptpg_pipeline.py:175` (`params.get("strictness", "relaxed")`).
2. **Validated**: `multi_ptpg_pipeline.py:176-177` against `pfp.STRICTNESS_LEVELS`, raising
   `MultiPTPGError`. Second validation inside the placer at `ptpg_floorplanner.py:840-841`.
   Canonical tuple: `ptpg_floorplanner.py:816` = `("exact", "relaxed", "best_effort")`.
   Default `"relaxed"` at `multi_ptpg_pipeline.py:175` and `ptpg_floorplanner.py:822`.
3. **Stored**: a local string only. Never on `DimParameters`, never on `GuiParameters`.
4. **Read downstream**: `multi_ptpg_pipeline.py:312` (passed to the placer),
   `multi_ptpg_pipeline.py:365` (echoed into the response), and the ladder itself:
   - `ptpg_floorplanner.py:954` `results = run_pass(is_relaxed=False)` (always; this is `exact`)
   - `ptpg_floorplanner.py:956-957` `if not results and strictness in ("relaxed","best_effort"): results = keep_best(run_pass(is_relaxed=True))`
   - `ptpg_floorplanner.py:959-960` `if not results and strictness == "best_effort": results = keep_best(run_pass(is_relaxed=True, require_all=False))`
   - the `relaxed` flag reaches geometry at `ptpg_floorplanner.py:542`, `:774`, `:806`
     (`if not relaxed and not actual_edges.issubset(required_edges)`), and is serialised at
     `ptpg_floorplanner.py:136` (`"is_relaxed"`).
5. **Dead?** No, but **entirely absent from the three handlers this dossier was asked about.**
   `handle_door_connectivity`, `handle_space_optimization`, `handle_ga_optimization` never see
   it. Sending `strictness` to `/api/generate/door_connectivity` is a no-op. The token
   `"relaxed"` that appears in `api.py:1032`, `:1042-1043`, `:1143-1144`, `:1367`, `:1380` is an
   unrelated concept: cardinal-constraint adjacency relaxation, matched by substring on a
   message string (`api.py:1042`), not the strictness enum.

---

## The Actual Constraints Or Formulas

### The 99999 sentinel: HYPOTHESIS CONFIRMED, WITH ONE IMPORTANT CORRECTION

**Where 99999 is assigned as the default max:**

- `views.py:889` `max_width = 99999` and `views.py:896` `max_height = 99999`, taken whenever
  `min_dim_enabled and not max_dim_enabled`.
- `views.py:891` / `:898`: even in the opt-in case, a missing/`None`/`"none"` `max` defaults to
  `99999` via `_bound` (`views.py:869-876`).
- `local_engine_bridge.py:91` / `:95`: identical, `99999 if open_max else (node[...].get("max", 99999) or 99999)`.
- `api.py:991-993`: the stacked one-connected composer re-fills missing entries with 99999.
- Ratio default at `local_engine_bridge.py:61` (`{"max": 99999, "min": 3}`).

**Is that sentinel passed into the linear program as a real upper bound? No.**
Three separate layers compare against it and drop it:

1. `handlers.py:322-333` `get_max_dims.usable()`: returns the list only if some element
   satisfies `0 < float(value) < 99999` (`handlers.py:329`). An all-99999 list returns `None`,
   so `max_width`/`max_height` at `handlers.py:1808` are `None`.
2. `input_template.py:45-48` and `:73-76`: `None` means the `max_width`/`max_height` keys are
   never written into the node dict at all.
3. `minimum_dimensioning.py:175`: `if value <= 0 or value >= 99999: return open_ub` where
   `open_ub = DEFAULT_UB_FACTOR * low` (`minimum_dimensioning.py:168`,
   `DEFAULT_UB_FACTOR = 5` at `minimum_dimensioning.py:148`).

**Crucial correction to the team's mental model:** the constraint is **not skipped**. The
sentinel is *replaced by a finite bound of 5x that room's own minimum*, and that finite bound
is written into the constraint graph as a real edge:

- `minimum_dimensioning.py:195` `up_len = upper_bound(node.get('max_height'), low_len)`
- `minimum_dimensioning.py:198` `up_width = upper_bound(node.get('max_width'), low_width)`
- `minimum_dimensioning.py:238` `edgesX[right_wall][left_wall] = -1 * ub_width[i]`
- `minimum_dimensioning.py:320` `edgesY[top_wall_i][bottom_wall_i] = -1 * ub_len[i]`

So "minimums only plus a sentinel maximum of 99999" actually means **"every room is bounded
above at 5x its own minimum"**. A room with `min = 3` can reach 15 and no further, regardless of
what the client sent. That is precisely the documented failure mode at
`documentation/door_connectivity.md:42-44` (a service room stretching until it outgrows a
habitable one) and it is the reason `maxDimEnabled` exists.

Verified numerically (`upper_bound(supplied, low=3)`):

| supplied | result |
|---|---|
| `None` | 15.0 |
| `99999` | 15.0 |
| `100000` | 15.0 |
| `0` | 15.0 |
| `30` | 15.0 (clamped by `open_ub`) |
| `12` | 12.0 |
| `4` | 7.5 (widened to `SOLVER_UB_SLACK * low`) |
| `3` | 7.5 (widened) |

Formula, `minimum_dimensioning.py:167-177`:

```
open_ub = 5 * low
ub      = open_ub                            if supplied is None / <=0 / >=99999
        = min(open_ub, max(supplied, 2.5*low)) otherwise
```

`SOLVER_UB_SLACK` is env-tunable at `minimum_dimensioning.py:155`
(`GPLAN_SOLVER_UB_SLACK`, default `2.5`). Note the consequence at the last two rows: **a
supplied ceiling below 2.5x the minimum is silently widened**, so a caller who sends
`min=3, max=4` gets an effective ceiling of 7.5.

### Other 99999 comparison sites (all "treat as open"), each is its own copy of the rule

- `api.py:480-481` `_room_bounds` fills missing entries with `99999.0`, then
  `api.py:499-502` `if hw <= 0 or hw >= 99999: hw = _INF`; aspect at `api.py:508`
  (`ratio if ratio and 1.0 <= ratio < 99999 else _INF`).
- `api.py:665` `_room_size_caps`: `return v if 0 < v < 99999 else None`.
- `handlers.py:329` `get_max_dims`: `0 < float(value) < 99999`.
- `minimum_dimensioning.py:175`: `value <= 0 or value >= 99999`.

Four independent implementations of "is this an open sentinel". Three use `>= 99999`, one uses
`< 99999` inverted, and `api.py:508` uses `< 99999` for ratio. A client sending `max: 99998`
gets a real cap in all four; `99999` is open in all four; the boundary is consistent today only
by accident of everyone hardcoding the same literal.

### Plot constraint edges (the only place the plot becomes a hard constraint)

`minimum_dimensioning.py:229-231` and `:311-313`. Both are gated `> 0`, so `0` and the `-1`
sentinel both mean "no plot constraint". The plot's *other* use (`path_map.dim_on_paths_bdy`) is
a filter over candidate boundaries, not a constraint on the solve.

---

## Invariants And Preconditions

1. `DimParameters` is only ever constructed when `minDimEnabled or dimensioned`
   (`api.py:1225-1229`). Otherwise `ui.min_dim_inputs` is `None`, and every reader guards for it:
   `handlers.py:318-320`, `api.py:460-462`, `api.py:650-652`.
2. `min_width` / `min_height` are per-room lists indexed by node id; the HTTP layer only appends
   when the node actually carries a `width` / `height` object (`views.py:881`, `:893`). A payload
   where some nodes carry `width` and others do not produces **misaligned lists** with no error.
3. Dummy rooms created by separating-triangle removal have no entry in the max lists. Handled by
   `input_for_min_dim._at` (`input_for_min_dim.py:6-13`, returns `None` on `IndexError`), by
   `api.py:659-660`, and by `api.py:486-490`.
4. `plot_width == 0 and plot_height == 0` is the documented "no plot" case
   (`handlers.py:1812`, `:2264`). `-1` is **not** handled there: `-1 != 0`, so `input_dims`
   survives and `dim_on_paths_bdy` runs with `plot_width = -1`, making
   `0 <= x <= 0.2 * -1` unsatisfiable at `path_map.py:163` and emptying the width pool. Reachable
   only by a direct in-process caller that supplies `dim_inputs` with the raw `-1` initialiser
   (`views.py:863`) while setting `minDimEnabled`. Not reachable through the normal HTTP flow,
   because `views.py:903-904` always overwrites. Latent trap, not a live bug.
5. `solve_min_dim`'s `capped` argument must equal `max_width is not None or max_height is not None`
   (`handlers.py:1896`, `:2006`, `:2121`, `:2324`, `:2437`, `:2568`). Five duplicated copies of
   the same expression; nothing enforces they stay in sync.

---

## Failure Modes

1. **Silent ceiling widening.** A `max` below `2.5 * min` is raised to `2.5 * min`
   (`minimum_dimensioning.py:177`). No warning is emitted at this layer. Documented at
   `documentation/door_connectivity.md:48-51`.
2. **Silent ceiling capping.** A `max` above `5 * min` is lowered to `5 * min`
   (`minimum_dimensioning.py:177`, the `min(open_ub, ...)`). This is **not documented**;
   `door_connectivity.md:48-51` only describes the widening direction.
3. **Ceiling release.** A topology infeasible under the ceilings is retried with `max_width` /
   `max_height` popped from every node (`handlers.py:349-352`) and the run is flagged
   (`handlers.py:2202-2203` -> `"Room maximum dimensions were released for some floorplans."`).
4. **Gap-fill overrun.** `rectangularize_output` (`api.py:801`) runs the capped fill
   (`api.py:834-836`), then an uncapped one if a hole remains (`api.py:840`), then reports
   (`api.py:846-847`, message at `api.py:872-874`).
5. **Plot expansion.** No plan fits -> retry with the plot dropped (`handlers.py:2069-2079`,
   `handlers.py:2120-2121`), then expand-only rescale (`handlers.py:2173` ->
   `inputgraph.py:597`). Client detects it by the keyword `expanded`
   (`documentation/door_connectivity.md:151`).
6. **`get_symmetric()` raises.** `DimParameters.__init__` accepts `symmetric`
   (`GuiParameters.py:25`) but the body (`GuiParameters.py:26-35`) **never assigns it**.
   `__symmetric` is only a class annotation (`GuiParameters.py:22`), which creates no attribute.
   `dimensiongui.gui_fnc` calls `dim_parameters.get_symmetric()` at `dimensiongui.py:12`, which
   raises `AttributeError: 'DimParameters' object has no attribute '_DimParameters__symmetric'`
   (reproduced). Unreached today because no live API caller takes the `dimensioned`-without-
   `minDimEnabled` branch through `dimensiongui`, but it is a live landmine on that path.

---

## Coupling (what breaks if you change this)

- **Change the 99999 literal anywhere and you must change it in four places**: `handlers.py:329`,
  `minimum_dimensioning.py:175`, `api.py:499-502`, `api.py:665`, plus the two producers
  (`views.py:889/891/896/898`, `local_engine_bridge.py:91/95`) and `api.py:991-993`.
- **Change `DEFAULT_UB_FACTOR` (`minimum_dimensioning.py:148`)** and every uncapped room's
  reachable size changes; this is the single knob controlling "how big can a bathroom get".
- **Remove `maxDimEnabled` from `views.py:888/895`** and every legacy client that sends
  `max: 5` on a bedroom suddenly gets it enforced (widened to 2.5x, capped at 5x), which will
  shrink batches.
- **Add a `dim_inputs` key** and you must add it to `views.py:856-868`,
  `local_engine_bridge.py:77-81`, and `api.py:990-996` (the stacked composer builds its own
  `sub_dims` and will `KeyError` at `api.py:1227` / `:1229` for any key it forgot).
- **`DimParameters.__init__` positional order** is `(min_width, max_width, plot_height, plot_width, isOptimalEnabled, ...)`
  (`GuiParameters.py:25`). Note `plot_height` precedes `plot_width`. Both call sites
  (`api.py:1227`, `:1229`) use keywords, so this is currently safe; any positional call would
  transpose the plot.
- **The rotation pass swaps the plot axes** (`handlers.py:2005`, `:2436`) but not the per-room
  ceilings; `_room_size_caps` compensates by using `max(max_width, max_height)` as a single span
  cap (`api.py:646-647`, `:671`).

---

## Dead Or Duplicated Code

### Answer to "do the three handlers share dimension parsing?": THREE SEPARATE COPIES, no sharing

| | door_connectivity | space_optimization | ga_optimization |
|---|---|---|---|
| Parse site | `views.py:856-907` / `local_engine_bridge.py:77-103` | `api.py:1493-1499`, `:1559` | `api.py:1683-1694` |
| Container | `dim_inputs` dict -> `DimParameters` (`api.py:1227`) | raw lists/dicts | `floorplan_data` dict |
| Handler | `handlers.py:1686` | `handlers.py:2659` | `handlers.py:2845` |
| `plot_width` default | 0 (dict init -1) | **absent** | 40 |
| `plot_height` default | 0 (dict init -1) | **absent** | 30 |
| `minDimEnabled` | yes | **absent** | **absent** |
| `maxDimEnabled` | HTTP layer only | **absent** | **absent** |
| 99999 sentinel | yes | **absent** | **absent** |
| strictness | **absent** | **absent** | **absent** |

They share nothing: not a function, not a constant, not a default. `space_optimization` uses
`max_expansion` (`handlers.py:2717`, `:2737`) as its only ceiling concept; `ga_optimization`
uses the plot as a grid size (`ga_current.py:472`, `:475`), not as an upper bound.

Add multi-PTPG as a fourth copy: `multi_ptpg_pipeline.py:180-181`, default `-1`.

### Genuinely dead / never-read items

1. **`dimensions_needed` and `corridors_needed`**: written into every min-dim payload
   (`input_for_min_dim.py:72-73`) and **read by nothing in the repo**. A repo-wide grep for both
   names returns only the three lines in `input_for_min_dim.py` that write them
   (`:21`, `:72`, `:73`). Dead payload fields.
2. **`floorplan_limit`**: set to `100000` at `input_for_min_dim.py:24`, emitted at
   `input_for_min_dim.py:75`, never read by `minimum_dimensioning.py`. A repo-wide grep on the
   name is misleading here: `inputgraph.py:139` declares an unrelated attribute of the same name
   (value `500`) that is genuinely live (`inputgraph.py:866`, `:999`, `:1084`). The two are
   different objects; only the payload key is dead.
3. **`symmetric`**: parsed at `views.py:905` and `local_engine_bridge.py:101`, threaded into
   `DimParameters(symmetric=...)` at `api.py:1229`, and **dropped on the floor** by the
   constructor (`GuiParameters.py:26-35` has no assignment). The only reader
   (`dimensiongui.py:12`) raises `AttributeError`. Effectively a dead flag with a booby trap.
4. **`min_ratio` / `max_ratio` on the minDim path**: parsed (`views.py:900-902`) and stored in
   `dim_inputs`, but `api.py:1227` (the minDim constructor call) **does not pass them**, so
   `DimParameters.__min_ratio` / `__max_ratio` stay at their `[]` defaults
   (`GuiParameters.py:25`, `:34-35`). The one downstream reader,
   `_room_bounds` at `api.py:482` (`col(params.get_max_aspect_ratio, 0.0)`), therefore always
   gets `[]` and the aspect cap is always `_INF` (`api.py:508`). The docs already say so
   (`documentation/door_connectivity.md:457-458` context and `api.py:457` comment "the ratio
   band that min-dim itself ignores"). **Dead on the door-connectivity path.**
5. **`dimensioned` on the door-connectivity path**: `api.py:1229` builds a full
   `DimParameters` from it, but nothing inside `handle_door_connectivity` (which spans
   `handlers.py:1686` up to `handle_space_optimization` at `handlers.py:2659`) uses it to switch
   dimensioning on. It is read as a branch condition exactly once, at `handlers.py:2219`
   (`if (ui.get_isDimensioned() == 0 and ui.get_isMinDimensioned() == 0 ):`), on the non-PTPG
   branch, and there it acts only as a negative guard on the *non-dimensioned* single-dual path.
   For `dimensioned: true` + `minDimEnabled: false` the outcome differs by branch:
   - PTPG branch: `handlers.py:1751` tests only `get_isMinDimensioned() == 0`, which is true, so
     an **undimensioned** dual is produced.
   - non-PTPG branch: `handlers.py:2219` is false (`get_isDimensioned() == 1`) and the `elif` at
     `handlers.py:2240` is false (`get_isMinDimensioned() == 0`), so neither branch runs and
     **no dual is produced at all**.

   Every other appearance of `get_isDimensioned()` in the handler is a pass-through argument into
   `input_for_min_dim.floorplan(...)` (`handlers.py:1870`, `:1980`, `:2101`, `:2294`, `:2406`,
   `:2537`), which sets the dead `dimensions_needed` field from item 1. Marked
   `DEPRECATED` at `documentation/door_connectivity.md:21`. Dead as a dimensioning switch for
   this caller: it can suppress output, but it can never produce a dimensioned floorplan.
6. **Plot dims are hardcoded away on the stacked one-connected path.** `api.py:994` sets
   `"plot_width": 0, "plot_height": 0` in `sub_dims` (also `optimal_floorplan: 0`,
   `rotation_enabled: 0` at `api.py:995`), so a one-connected graph with no red edges routed
   through `stacked_oneconnected_floorplans` (`api.py:1340-1350`) **ignores the client's
   `plot_width` / `plot_height` entirely** and returns early at `api.py:1350` before the normal
   path runs. Not dead code, but a silent flag drop for a whole class of inputs.

### Duplicated blocks

- The min-dim body of `handle_door_connectivity` exists twice inside the same function: PTPG
  branch `handlers.py:1787-2207`, non-PTPG branch `handlers.py:2240-2647`. Same reads
  (`:1806` vs `:2257`, `:1808` vs `:2260`, `:1810-1813` vs `:2262-2265`), same solve calls
  (`:1895` vs `:2323`, `:2005` vs `:2436`, `:2121` vs `:2568`), same rescale (`:2173` vs `:2619`).
  Divergence: the PTPG branch has the cardinal-constraint guards at `handlers.py:1814-1838`
  (rotation disabled under pins, `irreg_multiple_dual` forced); the non-PTPG branch at
  `handlers.py:2268` calls `graph.irreg_multiple_dual(input_dims)` unconditionally with no
  cardinal handling. Second divergence: the two copies do not even test the same flags. The PTPG
  entry condition is `get_isMinDimensioned() == 0` alone (`handlers.py:1751`); the non-PTPG one
  is `get_isDimensioned() == 0 and get_isMinDimensioned() == 0` (`handlers.py:2219`). With
  `dimensioned: true` and `minDimEnabled: false` the PTPG copy emits an undimensioned dual while
  the non-PTPG copy falls through both branches and emits nothing.
- `generate_mindim_rfp` (`handlers.py:356-472`) is a third, older copy that calls
  `min_dim.main` directly at `handlers.py:390` with **no** `max_width`/`max_height`
  (`handlers.py:383-387`) and no `solve_min_dim` release path.
- `views.py:856-907` and `local_engine_bridge.py:77-103` are the same parser twice. Divergence:
  prod has `_bound` (`views.py:869-876`) which tolerates `None` and the string `"none"`; the
  bridge uses `.get(k, d) or d` (`local_engine_bridge.py:89-98`), which additionally coerces a
  legitimate `0` to the default. Prod defaults ratio to `0.5 / 2` (`views.py:901-902`); the
  bridge also defaults `0.5 / 2` (`local_engine_bridge.py:97-98`) but pre-seeds node ratio to
  `{"max": 99999, "min": 3}` at `local_engine_bridge.py:61`, which prod does not do.

---

## Open Questions

1. Is the *downward* clamp at `minimum_dimensioning.py:177` (`min(open_ub, ...)`) intended? A
   client sending `max = 40` on a `min = 3` room gets 15. The docstring
   (`minimum_dimensioning.py:161-165`) says "never looser than the historical bound", which
   describes it, but `door_connectivity.md:48-51` does not mention it and a client reading the
   docs would expect 40.
2. Should `get_max_dims` (`handlers.py:309`) be replaced by an explicit `maxDimEnabled` kwarg on
   `Documents.get_floorplans`? Today the engine cannot distinguish "client opted out" from
   "client opted in but every room genuinely has no ceiling", because both arrive as all-99999.
3. Is `api.py:994` (plot forced to 0 on the stacked path) deliberate, or an oversight? The
   composite is rescaled per component at `api.py:1013+`, so a plot cap may be meaningless
   pre-fusion, but the client gets no warning that their plot was ignored.
4. `dimensions_needed` / `corridors_needed` / `floorplan_limit`: were these consumed by an older
   `min_dim` implementation? Nothing in the current tree reads them.
5. `symmetric` is parsed at three layers and assigned at none. Delete the parameter, or fix
   `GuiParameters.py:26-35` to assign `self.__symmetric = symmetric`?
6. Should `strictness` be extended to `door_connectivity`? It is currently a multi-PTPG-only
   concept (`ptpg_floorplanner.py:816`), while door-connectivity has its own ad-hoc ladder
   (solver release `handlers.py:349-352`, plot expansion `handlers.py:2069`, gapless override
   `api.py:840`, cardinal relaxation `api.py:1376-1406`) with no name and no client control.
