# Entry Point Wiring: `GPLAN/GPLAN/api.py` and `GPLAN/GPLAN/handlers.py`

All anchors below were read in this session. Paths are absolute-relative to
`C:\Users\nitant\Documents\GPLAN_Revamp\`.

## Purpose

This dossier maps how a request reaches the graph-theoretic pipeline. It covers
only imports, handler/route definitions, and call sites. It deliberately says
nothing about the algorithms inside `inputgraph.py`, `circulation.py`,
`multi_ptpg_pipeline.py`, the letter-shape modules, or the dimensioning solver:
sibling dossiers own those.

The single most important structural fact: **neither `api.py` nor `handlers.py`
defines an HTTP route.** Neither file imports Django, Flask, FastAPI, or any
other web framework. Both are plain library modules. HTTP lives outside them
(Django REST Framework in `gplan_backend/gplan_apis/`, plus a Flask dev bridge
in `GPLAN/local_engine_bridge.py`).

## Where It Sits In The Pipeline

Request flow, outermost to innermost:

```
HTTP  ->  gplan_backend/gplan_apis/urls.py            (Django route table)
      ->  gplan_backend/gplan_apis/views.py           (DRF APIView, request parsing)
      ->  gplan_backend/gplan_apis/tasks.py           (Celery task, calls into GPLAN)
      ->  GPLAN/GPLAN/api.py    Documents.*           (caller dispatch, cardinal pre/post pass)
      ->  GPLAN/GPLAN/handlers.py  handle_*           (flag dispatch, solver orchestration)
      ->  GPLAN/GPLAN/source/inputgraph.py InputGraph (dual generation, door connectivity)
          GPLAN/GPLAN/circulation.py                  (corridor insertion)
          GPLAN/GPLAN/source/lettershape/*            (L/T/U/Z)
          GPLAN/GPLAN/source/dimensioning/minimum_dimensioning.py
          GPLAN/GPLAN/source/multi_ptpg_pipeline.py   (separate, bypasses handlers.py)
```

A second, non-HTTP entry exists: the Tkinter GUI at `GPLAN/main.py:6`
(`from GPLAN.handlers import *`), which dispatches on `gclass.command` at
`GPLAN/main.py:39-67` and calls the same `handle_*` functions with
`drawGUI=True` and a live `gclass`.

### Division of labor: api.py vs handlers.py

They are **not** route-plus-delegate. They are two library layers:

- `api.py` owns the **caller string dispatch** and the **cardinal-constraint
  pre/post processing**. Its dispatch table is `Documents.get_floorplans`
  (`GPLAN/GPLAN/api.py:1215`), which branches first on `count == 1` vs
  `count > 1` (`api.py:1256`, `api.py:1313`) and then on `caller`
  (`api.py:1257-1311` for single, `api.py:1314-1411` for multiple). It also
  owns response serialization into `Wall`/`Room`/`Documents` dicts
  (`api.py:1427-1452`).
- `handlers.py` owns the **UI-flag dispatch** (`isDimensioned`,
  `isMinDimensioned`, `isCirculation`, `isNonAdj`, `is_multiple_door`) and the
  actual calls into `InputGraph` methods and the shape/dimension modules.
- `api.py:13` does `from GPLAN.handlers import *`, so every `handle_*` name is
  in `api.py`'s namespace by star import, not by qualified reference. There is
  no reverse dependency: `handlers.py` never imports `api.py`.

Framework evidence: `api.py:8-23` and `handlers.py:1-35` contain no web
framework import. Django REST is imported in
`gplan_backend/gplan_apis/views.py` (routes registered in
`gplan_backend/gplan_apis/urls.py:5-16`). Flask is imported at
`GPLAN/local_engine_bridge.py:28`, with routes at
`GPLAN/local_engine_bridge.py:132`, `:159`, `:180`.

## Entry Points (file:line)

### Import table, `api.py` (only imports touching `GPLAN/source` or root pipeline modules)

| Line | Import | Target |
|---|---|---|
| `api.py:8` | `from GPLAN.source.inputgraph import InputGraph` | `source/inputgraph.py` (class at `source/inputgraph.py:75`) |
| `api.py:1791` | `from GPLAN.source import multi_ptpg_pipeline` (function-local) | `source/multi_ptpg_pipeline.py` |

Non-pipeline imports for completeness: `api.py:9` (`pythongui.gui`), `api.py:13`
(`GPLAN.handlers` star import), `api.py:14` (`pythongui.GuiParameters`),
`api.py:23` (`boundary_utils` from a `sys.path`-injected `Space_Optimization`
directory, injected at `api.py:20-22`), `api.py:956` (`networkx`, function-local).

### Import table, `handlers.py`

| Line | Import | Target |
|---|---|---|
| `handlers.py:1` | `import GPLAN.source.polygonal.poly as poly` | `source/polygonal/poly.py` |
| `handlers.py:2` | `import GPLAN.input.input_for_min_dim as input_for_min_dim` | `GPLAN/input/` |
| `handlers.py:5` | `from GPLAN.source.graphoperations.operations import get_encoded_matrix` | `source/graphoperations/operations.py` |
| `handlers.py:6` | `from GPLAN.source.graphoperations.graph_crossings1 import check_intersection` | `source/graphoperations/graph_crossings1.py` |
| `handlers.py:7` | `from GPLAN.source.graphoperations import connect_graph` | `source/graphoperations/connect_graph.py` |
| `handlers.py:8` | `from GPLAN.system_functions.os_functions import delete_file` | `GPLAN/system_functions/` |
| `handlers.py:9` | `import GPLAN.source.dimensioning.minimum_dimensioning as min_dim` | `source/dimensioning/minimum_dimensioning.py` |
| `handlers.py:10` | `import GPLAN.source.lettershape.lshape.Lshaped as Lshaped` | L-shape |
| `handlers.py:11` | `import GPLAN.source.lettershape.tshape.tshape as Tshaped` | T-shape |
| `handlers.py:12` | `import GPLAN.source.lettershape.ushape.ushape as Ushaped` | U-shape |
| `handlers.py:13` | `import GPLAN.source.lettershape.zshape.zshape as Zshaped` | Z-shape |
| `handlers.py:14` | `import GPLAN.source.polygonal.limits as lim` | `source/polygonal/limits.py` |
| `handlers.py:15` | `import GPLAN.source.polygonal.newcoord as nc` | `source/polygonal/newcoord.py` |
| `handlers.py:29` | `import GPLAN.source.inputgraph as inputgraph` | `source/inputgraph.py` |
| `handlers.py:31` | `import GPLAN.circulation as cir` | root-level `GPLAN/GPLAN/circulation.py` |

GUI-only imports in the same block: `handlers.py:16` (`dimensiongui`),
`handlers.py:17` (`mindimensiongui`), `handlers.py:18` (`nonadjgui`),
`handlers.py:28` (`pythongui.gui`), `handlers.py:30` (`pythongui.drawing`), and
the lazy `tkinter.messagebox` shim at `handlers.py:21-25`. Function-local
imports reach outside the package entirely: `handlers.py:2689`
(`from negNew import FloorPlan`) and `handlers.py:2868`
(`from ga_current import ...`), both after a `sys.path` injection at
`handlers.py:2685-2687` and `handlers.py:2863-2865`.

### Pipeline modules imported by NEITHER file

These are the ones the duplication tasks should look at:

| Module | Who imports it, if anyone |
|---|---|
| `GPLAN/GPLAN/source/multiple_ptpg.py` | only `source/multi_ptpg_pipeline.py:32` |
| `GPLAN/GPLAN/source/ptpg_floorplanner.py` | only `source/multi_ptpg_pipeline.py:33` |
| `GPLAN/GPLAN/source/path_map.py` | only `source/inputgraph.py:20` (`from GPLAN.source.path_map import *`) |
| `GPLAN/GPLAN/source/multiple_circ.py` | **nobody**; it itself does a bare `import circulation` at `source/multiple_circ.py:10`, which cannot resolve under the `GPLAN.` package layout |
| `GPLAN/GPLAN/source/circulation/circulation.py` | nobody in these two files; `handlers.py:31` imports the **root** `GPLAN/GPLAN/circulation.py` instead |
| `source/boundary/`, `source/floorplangen/`, `source/irregular/`, `source/staircaseshape/`, `source/trial/` | not imported by `api.py` or `handlers.py`; reached transitively through `source/inputgraph.py` |

So `multi_ptpg_pipeline` is the only `source/` module `api.py` touches beyond
`inputgraph`, and it is reached through `Documents.get_multi_ptpg_floorplans`
only, never through `handlers.py`.

### Endpoint / handler matrix

`api.py` public surface (four `Documents` static methods) and where each lands:

| Entry (anchored) | Pipeline call site (anchored) | Purpose |
|---|---|---|
| `Documents.get_floorplans` `api.py:1215` | dispatches to `handle_*`, see rows below | The single dispatcher for every graph-based shape |
| `Documents.get_space_optimized_floorplan` `api.py:1459` | `handle_space_optimization(...)` at `api.py:1566` | Rectangle-packing optimizer; does **not** touch `InputGraph` |
| `Documents.get_ga_optimized_floorplan` `api.py:1650` | `handle_ga_optimization(...)` at `api.py:1701` | Genetic-algorithm corridor placement; does **not** touch `InputGraph` |
| `Documents.get_multi_ptpg_floorplans` `api.py:1775` | `multi_ptpg_pipeline.run(request_data)` at `api.py:1800` | PTPG variant enumeration plus exact-dimension placement; **bypasses `handlers.py` entirely** |
| `stacked_oneconnected_floorplans` `api.py:939` | constructs `InputGraph` at `api.py:1003`, then recurses into `Documents.get_floorplans` at `api.py:1006` | Composes two biconnected components of a 1-connected graph into one plan |
| `apply_cardinal_ring` `api.py:349` | mutates `graph.matrix` / `graph.edgecnt` / `graph.coordinates` in place at `api.py:365-370` | Injects a cardinal outer ring as matrix-only augmentation (no user doors) |

`Documents.get_floorplans` branch table. The outer selector is `count`
(`api.py:1256` = single, `api.py:1313` = multiple); the inner selector is the
`caller` string:

| `count` | `caller` | Call site | Handler |
|---|---|---|---|
| 1 | `lshape` | `api.py:1262` | `handle_letter_shape` (letter set at `api.py:1258`) |
| 1 | `ushape` | `api.py:1268` | `handle_letter_shape` (letter at `api.py:1267`) |
| 1 | `tshape` | `api.py:1274` | `handle_letter_shape` (letter at `api.py:1273`) |
| 1 | `zshape` | `api.py:1280` | `handle_letter_shape` (letter at `api.py:1279`) |
| 1 | `staircaseshape` | `api.py:1285` | `handle_staircase_shaped` |
| 1 | `rectangular` or `irregular`, with `rectangular=True` | `api.py:1297` | `handle_single_oc` |
| 1 | `rectangular` or `irregular`, with `rectangular=False` | `api.py:1299` | `handle_single` |
| 1 | `door_connectivity` | `api.py:1309` | `handle_door_connectivity`, preceded by `ui.set_is_multiple_door(False)` at `api.py:1304`, `normalize_cardinal_constraints` at `api.py:1305`, `apply_cardinal_ring` at `api.py:1307` |
| 1 | anything else | `api.py:1311` | no pipeline call, returns a "not handled" message |
| >1 | `lshape` | `api.py:1320` | `handle_multiple_l` |
| >1 | `rectangular` | `api.py:1325` | `handle_multiple_oc` |
| >1 | `irregular` | `api.py:1327` | `handle_multiple` |
| >1 | `door_connectivity` | `api.py:1353` | `handle_door_connectivity` after `ui.set_is_multiple_door(True)` at `api.py:1331`; see the sub-branch below |
| >1 | `multiple_l` | `api.py:1408` | `handle_multiple_l` |
| >1 | anything else | `api.py:1410` | no pipeline call |

Multiple `door_connectivity` sub-branching, all in `api.py`:

1. `api.py:1335` `if not non_adj_edge_list:` try the stacked one-connected
   composition first (`api.py:1340`); if it produced plans, return immediately
   at `api.py:1350` without ever calling `handle_door_connectivity`.
2. Otherwise `apply_cardinal_ring` at `api.py:1351`, then
   `handle_door_connectivity` at `api.py:1353`.
3. `api.py:1358` `rectangularize_output(ui)` gates the batch;
   `api.py:1360` if the gate emptied a non-empty batch and there are no
   cardinal pins, restore the ungated plans (`api.py:1363`).
4. `api.py:1365` if cardinal pins exist and zero plans satisfy them, run the
   retry ladder: spanning-tree relaxation (`api.py:1376-1380`) then cardinal
   drop (`api.py:1381`), each rebuilding a fresh `InputGraph` at `api.py:1384`
   and re-entering `handle_door_connectivity` at `api.py:1390`.
5. `api.py:1422` only the `door_connectivity` caller attaches `ptpg_graph` to
   the response (`api.py:1425`).

`handlers.py` handler definitions and their pipeline call sites:

| Handler (anchored) | Selector inside | Pipeline calls (anchored) |
|---|---|---|
| `handle_single` `handlers.py:751` | `isDimensioned==0 and isMinDimensioned==0` `handlers.py:754`; `isMinDimensioned==1` `handlers.py:769` | `connect_graph.one_connected` `:753`; `graph.irreg_single_dual()` `:760`; `inputgraph.get_final_traversal` `:764`; min-dim path `graph.irreg_multiple_dual()` `:792`, `input_for_min_dim.floorplan` `:807`, `min_dim.main` `:834` |
| `handle_single_oc` `handlers.py:1078` | `isDimensioned==0 and isMinDimensioned==0` `:1079`; `isDimensioned==1` `:1130`; `isMinDimensioned==1` `:1189` | `graph.oneconnected_dual("single")` `:1082` with `OCError` fallback `:1084` and `BCNError` fallback `:1088` both to `graph.irreg_single_dual()`; dimensioned path `oneconnected_dual("multiple")` `:1157` + `single_floorplan` `:1166`; min-dim path `oneconnected_dual("multiple")` `:1206`, `min_dim.main` `:1250` |
| `handle_multiple` `handlers.py:1041` | `isDimensioned==0` `:1044`, else `:1058` | `connect_graph.one_connected` `:1043`; `graph.irreg_multiple_dual()` `:1050`; dimensioned path `irreg_multiple_dual()` `:1068` + `graph.multiple_floorplan(...)` `:1069` |
| `handle_multiple_oc` `handlers.py:1327` | `isDimensioned==0 and isMinDimensioned==0` `:1328`; `isMinDimensioned==1` `:1350`; else dimensioned `:1452` | `graph.oneconnected_dual("multiple")` `:1331` with `OCError` `:1333` / `BCNError` `:1337` fallback to `irreg_multiple_dual()`; min-dim `oneconnected_dual` `:1365` + `min_dim.main` `:1394`; dimensioned `oneconnected_dual` `:1465` + `multiple_floorplan` `:1474` |
| `handle_letter_shape` `handlers.py:939` | `ui.get_letter()` at `:944`/`:946`/`:948`/`:950`, gated by `isDimensioned==0` at `:942` | `Lshaped.LShapedFloorplan` `:945`, `Tshaped.TShapedFloorplan` `:947`, `Zshaped.ZShapedFloorplan` `:949`, `Ushaped.UShapedFloorplan` `:951`; dimensioned branch `:968-975` then `graph.single_floorplan` `:1004` |
| `handle_multiple_l` `handlers.py:1015` | `isDimensioned==0` `:1017` | `Lshaped.multipleLshapedFloorplans` `:1019` |
| `handle_staircase_shaped` `handlers.py:1032` | none | `inputgraph.staircaseshaped(graph)` `:1034` |
| `handle_door_connectivity` `handlers.py:1686` | see below | `graph.door_connectivity(...)` `:1710` and `:1732` |
| `handle_circulation` `handlers.py:492` | six mutually exclusive flag combinations, see below | `generate_mindim_rfp` `:516`, `call_circulation_new` `:527`/`:577`/`:634`/`:685`/`:715`/`:737`; `graph.irreg_single_dual()` `:561` |
| `handle_poly` `handlers.py:1499` | none | `graph.polyonalinput(...)` `:1502` |
| `handle_limits` `handlers.py:1509` | `gclass.side` `:1590-1599` | `lim.LimitsAlgorithm` `:1603`, `nc.NewCoordinateAlgorithm` `:1615`, `inputgraph.InputGraph(...)` `:1618`, `poly.Room()` `:1577` |
| `handle_space_optimization` `handlers.py:2659` | none | `negNew.FloorPlan` `:2689`, `:2696`. No `InputGraph` |
| `handle_ga_optimization` `handlers.py:2845` | none | `ga_current` `:2868`. No `InputGraph` |

`handle_door_connectivity` branching, anchored:

- `handlers.py:1687` if not connected, `connect_graph.one_connected(graph.matrix)`.
- `handlers.py:1703` `ui.get_isNonAdj() == 1` selects the non-adjacency call
  `graph.door_connectivity(show_graph, non_adj_list=...)` at `:1710`; the
  `else` at `:1730` calls `graph.door_connectivity(show_graph)` at `:1732`.
  The non-adj return is arity-polymorphic: 3-tuple at `:1712`, 2-tuple at
  `:1717`, anything else warns and returns at `:1720`.
- `handlers.py:1745` `if (checkPTPG)` selects the rectangular-dual family; the
  `else` at `:2208` is the "not a PTPG" irregular fallback.
- Inside the PTPG branch: `:1747` `isCirculation == 1` delegates to
  `handle_circulation` and returns at `:1749`; `:1751` `isMinDimensioned == 0`
  splits again on `multiple_door` at `:1754` (`oneconnected_dual("single")`
  `:1756`, `OCError` `:1757` / `BCNError` `:1760` to `irreg_single_dual`)
  versus `:1773` (`irreg_multiple_dual()` `:1778`); `:1787`
  `isMinDimensioned == 1` is the min-dim family.
- Inside min-dim: `:1814` if rotation was requested **and** cardinal pins
  exist, rotation is forced off (`:1818`). `:1821` if cardinal pins exist,
  go straight to `graph.irreg_multiple_dual(input_dims)` at `:1830` and skip
  `oneconnected_dual` altogether; otherwise `:1832` try
  `oneconnected_dual("multiple")` at `:1833` with `OCError` `:1834` /
  `BCNError` `:1837` falling back to `irreg_multiple_dual(input_dims)`.
- Inside the non-PTPG `else`: `:2219` non-dimensioned splits on
  `multiple_door` at `:2220` (`irreg_single_dual()` `:2221`) versus `:2228`
  (`irreg_multiple_dual()` `:2232`); `:2240` min-dim calls
  `irreg_multiple_dual(input_dims)` at `:2268`.

`handle_circulation` selector table (all six are `if`/`elif` on the same
chain, so exactly one runs):

| Condition (anchored) | Meaning |
|---|---|
| `handlers.py:499` `isMinDimensioned==1 and isRemoveAddCirculation==0` | min-dimensioned circulation |
| `handlers.py:558` `isDimensionedCirculation==0 and isRemoveAddCirculation==0 and isPublic==0` | non-dimensioned single circulation |
| `handlers.py:595` `isDimensionedCirculation==1 and isRemoveAddCirculation==0 and isPublic==0` | dimensioned single circulation |
| `handlers.py:657` `isMinDimensioned==1 and isRemoveAddCirculation==1` | remove corridors, min-dim |
| `handlers.py:706` `isDimensionedCirculation==0 and isRemoveAddCirculation==1 and isPublic==0` | add/remove corridor |
| `handlers.py:729` `isDimensionedCirculation==0 and isPublic==1` | public/private circulation |

The corridor engine itself is reached through `call_circulation_new`
(`handlers.py:79`), which builds `cir.Room` at `:94`/`:98`, `cir.RFP` at
`:101`, and `cir.circulation(...)` at `:104` against the root
`GPLAN/GPLAN/circulation.py`.

### Sanity check against the API docs

Docs live at `GPLAN/documentation/` (not `documentation/` at the repo root as
the task text suggested; the second copy is `gplan_backend/GPLAN/documentation/`).

| Documented endpoint | Doc anchor | Exists in code? | Handler chain |
|---|---|---|---|
| `POST /api/generate/door_connectivity` | `GPLAN/documentation/door_connectivity.md:3` | Yes, via the generic `<slug:shape>` route `gplan_backend/gplan_apis/urls.py:8` | `GenerateFloorplanView.post` `gplan_backend/gplan_apis/views.py:803` -> `generate_floorplan_task` -> `Documents.get_floorplans` `api.py:1215` -> `handle_door_connectivity` `handlers.py:1686` |
| `POST /api/generate/multi-ptpg` | `GPLAN/documentation/multi_ptpg_api.md:39` | Yes, `urls.py:7` | `GenerateMultiPTPGFloorplanView.post` `views.py:1349` -> `Documents.get_multi_ptpg_floorplans` `api.py:1775` -> `multi_ptpg_pipeline.run` `api.py:1800` |
| `GET /api/task/<task_id>/` | `multi_ptpg_api.md:112` | Yes, `urls.py:10` | `TaskResultView.get` `views.py:1511` |
| `POST /api/generate/<shape>` with `cardinal_constraints` | `GPLAN/documentation/cardinal_constraints.md:9` | Yes, same route as door_connectivity | `cardinal_constraints` read at `views.py:851`, normalized at `api.py:1305` / `api.py:1332` |
| Local Flask bridge `/api/generate/<shape>` + `/api/task/<id>/` | `cardinal_constraints.md:189`, `multi_ptpg_api.md:40` | Yes | `GPLAN/local_engine_bridge.py:159`, `:180`, plus `:132` for multi-ptpg |

Endpoints present in code but **not** in these three documents (they are
covered, if at all, by other files in `GPLAN/documentation/`):

- `POST /api/generate/space-optimized` (`urls.py:5`, `GenerateSpaceOptimizedFloorplanView` `views.py:1127`) - has its own `space_optimization_api.md`.
- `POST /api/generate/ga-optimized` (`urls.py:6`, `GenerateGAOptimizedFloorplanView` `views.py:1184`) - has its own `ga_optimization_api.md`.
- `graphdocument/` (`urls.py:11`), `document/` (`urls.py:12`), `document/<id>/` (`urls.py:13`), `document/delete/<id>/` (`urls.py:14`), `form/message/` (`urls.py:15`), `welcome` (`urls.py:16`). None of these touch the graph pipeline; `api_reference.md` does not mention them either.

## Data Structures

Only the ones that cross the api/handlers boundary; the pipeline's internal
structures belong to sibling dossiers.

- `GuiParameters` (constructed at `api.py:1230`, also `api.py:1563` and
  `api.py:1698`) is the sole channel between `api.py` and `handlers.py`. Every
  request flag becomes a setter on it (`api.py:1230-1249`), and every result
  comes back through `ui.get_output_data()` (`api.py:1413`). It doubles as the
  message channel (`ui.get_message()` at `api.py:1264`).
- `DimParameters` (`api.py:1227` for min-dim, `api.py:1229` for dimensioned)
  carries the per-room dimension arrays. `handlers.py:1806` and
  `handlers.py:2257` unpack it when `gclass is None`, that is, on the API path.
- `InputGraph` (`source/inputgraph.py:75`) is built by the caller, not by these
  files, except at `api.py:1003` (stacked composition) and `api.py:1384`
  (cardinal retry), plus `handlers.py:1618` inside `handle_limits`.
- Response objects `Asset` `api.py:52`, `Wall` `api.py:66`, `Room` `api.py:88`,
  `Documents` `api.py:1181`. Serialization loop at `api.py:1427-1452` reads
  `final_traversal`, `name_coords`, `area`, `room_width`, `room_height` off
  each solved graph.
- Module constants: `FLOORPLAN_LIMIT = 30` at `api.py:119`,
  `CARDINAL_DIR_INDEX = {"N":0,"E":1,"S":2,"W":3}` at `api.py:123`.

## Algorithm Walkthrough

Only the wiring, not the math.

1. A DRF view parses the request and builds `InputGraph`
   (`gplan_backend/gplan_apis/views.py:829`), splitting black edges into
   adjacency and red edges into non-adjacency (`views.py:819-828`).
2. The view hands off to a Celery task, which calls
   `Documents.get_floorplans(**prepared_data)` at
   `gplan_backend/gplan_apis/tasks.py:127`.
3. `get_floorplans` silences stdout by rebinding `builtins.print`
   (`api.py:1217-1222`), builds `DimParameters` and `GuiParameters`
   (`api.py:1226-1232`), copies node colors/labels into the ui
   (`api.py:1241-1245`), then dispatches on `count` and `caller` per the matrix
   above.
4. For `door_connectivity` it additionally normalizes cardinal constraints and
   augments the graph matrix with a cardinal ring before calling the handler
   (`api.py:1305-1309` single, `api.py:1332-1352` multiple).
5. The handler runs the solver family selected by the ui flags and pushes each
   solved graph onto `ui` via `_append_output_data`.
6. `get_floorplans` reads the output back (`api.py:1413`), applies the
   post-passes for `door_connectivity` (`rectangularize_output` `api.py:1358`,
   `filter_output_by_cardinal` `api.py:1365`), then serializes at most
   `min(len(outputData), limit, count)` plans (`api.py:1418`, `api.py:1427`).
7. `builtins.print` is restored at `api.py:1454` (and at `api.py:1349` on the
   early stacked return, and in the `finally` at `api.py:1802`).

The multi-PTPG path skips steps 3 to 6 entirely: `api.py:1800` calls
`multi_ptpg_pipeline.run(request_data)` and returns its dict verbatim.

## Invariants And Preconditions

- `caller` is the only shape selector. Any unrecognized value produces a
  message and **no** pipeline call (`api.py:1311`, `api.py:1410`), so the
  response is an empty `Documents` built at `api.py:1419`.
- `count == 1` and `count > 1` reach different handler sets. `count` defaults
  to 1 at `api.py:1252-1253` and `starting_from` to 0 at `api.py:1250-1251`.
- `handle_*` functions communicate results only by mutating `ui`. Their return
  values are ignored at every `api.py` call site except
  `handle_space_optimization` (`api.py:1566`) and `handle_ga_optimization`
  (`api.py:1701`), which return a bool checked at `api.py:1580` and
  `api.py:1708`.
- `gclass is None` is the API-vs-GUI discriminator inside handlers. Every
  min-dim handler branches on it: `handlers.py:770` vs `:786`,
  `handlers.py:1788` vs `:1805`, `handlers.py:2243` vs `:2256`. When it is
  `None`, dimensions come from `ui.min_dim_inputs`; when it is set, a Tk dialog
  supplies them.
- `ui.get_is_multiple_door()` is only consulted when `gclass is None`
  (`handlers.py:1752-1753`, `handlers.py:2215`), so the multiple-door split
  exists only on the API path.
- Cardinal ring augmentation is skipped whenever pins are absent or
  non-adjacency constraints exist (`api.py:359-360`); the ring is written to
  `graph.matrix` only, never to `ui`'s edge list, so no doors are placed on
  ring edges (comment and code at `api.py:351-370`).
- Under cardinal constraints, rotation is disabled (`handlers.py:1814-1818`)
  and `oneconnected_dual` is bypassed (`handlers.py:1821-1830`).
- Per-room maximum dimensions only take effect where `get_max_dims`
  (`handlers.py:309`) is called, and that is exclusively inside
  `handle_door_connectivity` (`handlers.py:1808` and `handlers.py:2260`). A
  value is treated as a real ceiling only if `0 < value < 99999`
  (`handlers.py:329`). No other handler reads maximums.
- `stacked_oneconnected_floorplans` preconditions, all enforced at
  `api.py:953-973`: `dim_inputs` non-empty, at least 4 nodes, connected, exactly
  one articulation point, exactly two biconnected components, unique room
  labels.

## Failure Modes

Error handling in these two files, and what each maps to over HTTP.

- **`OCError` / `BCNError`** (`source/inputgraph.py:47` and `:55`) are always
  caught inside `handlers.py` and downgraded to an irregular dual. They never
  propagate to `api.py`. Catch sites: `handlers.py:359`/`:362`,
  `:613`/`:617`, `:1084`/`:1088`, `:1159`/`:1163`, `:1208`/`:1212`,
  `:1333`/`:1337`, `:1366`/`:1369`, `:1467`/`:1471`, `:1757`/`:1760`,
  `:1834`/`:1837`. HTTP consequence: **none**, the request still returns 200
  with irregular plans. `gplan_backend/gplan_apis/views.py:23` imports both
  exception classes but no `except OCError` clause exists anywhere in the
  backend, so that import is unused.
- **Generic `Exception` in `api.py`**: `api.py:1638` (space optimization) and
  `api.py:1762` (GA) return `{"status": "error", "error": {"message": str(e)}}`
  with no HTTP status of their own. `api.py:969` and `api.py:1013` swallow
  exceptions in the stacked composition and fall through to the normal
  `handle_door_connectivity` path.
- **`get_floorplans` has no try/except at all.** Anything the pipeline raises
  propagates out. It is caught two layers up: `IndexError` becomes an
  `{"error": ...}` result dict at `gplan_backend/gplan_apis/tasks.py:130-140`,
  `SoftTimeLimitExceeded` at `tasks.py:178`, and any other `Exception` at
  `tasks.py:181`. Because these are Celery task **results**, not raises, the
  HTTP layer still answers 202 on submit (`views.py:986`) and 200 on poll
  (`views.py:1540`) with an error payload inside. The 500 paths at
  `views.py:1038`, `:1175`, `:1314`, `:1502` only cover failures during request
  parsing and task submission, and `views.py:1535` returns 500 only when Celery
  itself marks the task FAILURE.
- **`builtins.print` is left patched if the pipeline raises.** `get_floorplans`
  restores it at `api.py:1454` on the success path and at `api.py:1349` on the
  stacked early return, but there is no `try/finally`, so an exception between
  `api.py:1222` and `api.py:1454` leaves `print` as a no-op process-wide. Only
  `get_multi_ptpg_floorplans` uses `finally` (`api.py:1801-1802`).
- **`show_warning` opens a Tk dialog** (`handlers.py:3056-3057` via the lazy
  `messagebox` at `handlers.py:21-25`). It is called on the headless API path,
  for example `handlers.py:1758` and `handlers.py:1835` (both inside
  `handle_door_connectivity`) and `handlers.py:1085`, `:1334`, without any
  `gclass is not None` guard. On a display-less server this raises `TclError`
  from inside an `except OCError` block, converting a recoverable fallback into
  a task failure.
- **`handle_circulation` dereferences `gclass` unconditionally** in its first
  branch: `gclass.open` at `handlers.py:504`, `gclass.ptpg` at `:523`,
  `gclass.output_data` at `:526`, `gclass.checkvar4` at `:536`. The API reaches
  this function only through `handlers.py:1748`, which forwards `gclass=None`
  when called from `api.py`. So `circulationEnabled=1` combined with
  `minDimEnabled=1` on the API path is an `AttributeError` waiting to happen.
- **`graph.multiple_dual()` at `handlers.py:1172` has no definition** in
  `source/inputgraph.py` (the class methods there are `irreg_single_dual` `:202`,
  `door_connectivity` `:340`, `single_floorplan` `:779`, `polyonalinput` `:849`,
  `irreg_multiple_dual` `:852`, `multiple_floorplan` `:1126`,
  `oneconnected_dual` `:1200`; no `multiple_dual`). That line sits inside a
  `while` retry loop that also calls `dimgui.gui_fnc`, so it is GUI-only and
  currently unreachable from the API, but it is a latent `AttributeError`.
- **`handle_single_oc` writes to a relative path** `./saved_files/input_to_limits.json`
  at `handlers.py:1114-1116` with no directory creation, and `handle_limits`
  reads that same path at `handlers.py:1513`. Working-directory dependent.

## Coupling (what breaks if you change this)

- Renaming or reordering any `caller` string breaks the dispatch at
  `api.py:1257-1311` and `api.py:1314-1411` silently: an unknown caller
  produces an empty document, not an error.
- `api.py:13`'s star import means adding any top-level name to `handlers.py`
  can shadow an `api.py` name. `handlers.py` defines `plot` (`handlers.py:474`)
  and `origin` (`handlers.py:39`), both of which land in `api.py`'s namespace.
- Changing a `handle_*` signature breaks both callers at once: `api.py`
  (keyword-free positional calls at `api.py:1262-1408`) and `GPLAN/main.py:39-67`
  (which passes `drawGUI=True` positionally).
- Any new `InputGraph` method used by `handlers.py` must exist on the retry
  graphs constructed at `api.py:1003` and `api.py:1384` too.
- The output contract is `outputData[index].final_traversal`, `.name_coords`,
  `.area`, `.room_width`, `.room_height` (`api.py:1429-1433`). Changing those
  attribute names on the solver output breaks serialization for every caller.
- `rectangularize_output` and `filter_output_by_cardinal` mutate ui state
  through `ui._set_output_data` (`api.py:427`), a private setter. Any change to
  `GuiParameters`' internals breaks the cardinal gate.
- `handle_door_connectivity` is the only consumer of `get_max_dims` and
  `solve_min_dim`; changing the max-dimension ladder cannot affect any other
  shape.
- The `Space_Optimization` and `ga_current` modules are reached by `sys.path`
  injection (`api.py:20-22`, `handlers.py:2685-2687`, `handlers.py:2863-2865`),
  not by package import. Moving that directory breaks imports at runtime only,
  never at import time.

## Dead Or Duplicated Code

**Handlers defined but never reachable from `api.py` (dead relative to the HTTP API):**

- `handle_poly` (`handlers.py:1499`) - only caller is the Tk GUI at
  `GPLAN/main.py:56`.
- `handle_limits` (`handlers.py:1509`) - only caller is `GPLAN/main.py:58`.
- `make_dissection_corridor` (`handlers.py:58`) - only caller is
  `GPLAN/main.py:20`.
- `plot` (`handlers.py:474`) - **no caller anywhere**. The `plot(...)` calls at
  `GPLAN/GPLAN/circulation.py:137` and `:147` resolve to
  `circulation.py`'s own module-level `plot`, and `handlers.py:103`/`:117` call
  `cir.plot`, not this one.
- `handle_circulation` (`handlers.py:492`) is reachable from `api.py` only
  indirectly, through `handlers.py:1748` when `circulationEnabled == 1`, and
  its first branch is `gclass`-dependent (see Failure Modes). Its direct call
  site is `GPLAN/main.py:40`.

Every other `handle_*` is reachable from `api.py`, as listed in the matrix.

**Duplicated modules:**

- `GPLAN/GPLAN/api.py` and `gplan_backend/GPLAN/GPLAN/api.py` are byte-identical
  once CRLF/LF is normalized (verified by checksum this session). Same for
  `handlers.py`. `gplan_backend/GPLAN/` is the engine consumed as a submodule,
  so this is expected duplication, not drift.
- `GPLAN/GPLAN/documentation/` and `gplan_backend/GPLAN/documentation/` are the
  same duplication; there is a third partial copy at
  `gplan_backend/docs/floorplans/`.
- `GPLAN/GPLAN/circulation.py` (root, imported at `handlers.py:31`) and
  `GPLAN/GPLAN/source/circulation/circulation.py` are two different files with
  different checksums and different APIs (`multiple_circulation(self, coord)`
  at root `circulation.py:90` versus `multiple_circulation(self)` at
  `source/circulation/circulation.py:143`). Only the root one is wired in.
- `GPLAN/GPLAN/source/multiple_circ.py` is dead: nothing imports it, and its own
  `import circulation` at line 10 is a bare top-level import that cannot
  resolve inside the `GPLAN.` package.
- `source/inputgraph.py:340` defines `door_connectivity` and `:650` defines
  `door_connectivity2`. Only `door_connectivity` is called from `handlers.py`
  (`:1710`, `:1732`); `door_connectivity2` has no call site in either file.

## Open Questions

1. Does anything call `handle_circulation`'s min-dim branch from the API in
   production? The code path exists (`api.py` `circulationEnabled` ->
   `handlers.py:1747` -> `handlers.py:499`) but would crash on
   `gclass.open` at `handlers.py:504`. Either the flag is never sent with
   `minDimEnabled`, or this is an untested crash. I did not run it.
2. `gplan_backend/gplan_apis/views.py:23` imports `OCError` and `BCNError` but
   no handler catches them. Was there once a 4xx mapping for "cannot generate
   rectangular floorplan", and is the current silent downgrade to an irregular
   dual intentional at the API contract level?
3. `show_warning` on the headless path (`handlers.py:1758`, `:1835`): does the
   deployed container have a DISPLAY or an Xvfb, or has this simply never been
   hit because `OCError` is rare on real inputs?
4. `graph.multiple_dual()` at `handlers.py:1172` names a method that does not
   exist on `InputGraph`. Was it renamed to `irreg_multiple_dual` and this call
   site missed?
5. The task brief pointed at `documentation/` at the repo root; the docs are
   actually at `GPLAN/documentation/`. Worth confirming which path other
   dossiers should cite.
6. Knowledge-graph cross-check: `graphify query` returned nodes consistent with
   every anchor above (`.get_floorplans()` at `api.py:1215`,
   `handle_door_connectivity()` at `handlers.py:1686`,
   `stacked_oneconnected_floorplans()` at `api.py:939`, `InputGraph` at
   `source/inputgraph.py:75`, `Documents` at `api.py:1181`). No disagreement
   between the graph and the code was found.
