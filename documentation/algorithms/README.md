# GPLAN Algorithm Pointer Document

## How to use this document

This document is for anyone about to change GPLAN engine code: it tells you which files a change touches, in what order to read them, which invariants the change must preserve, what breaks silently, and what a green test actually proves. It is not the API reference: request and response schemas live one folder up, in files such as [door_connectivity.md](../door_connectivity.md).

One rule overrides everything here: **source code wins over any document, including this one.** Every structural claim below carries a `file:line` anchor. Anchors were correct when written, and they drift when code moves. A claim whose anchor no longer matches is a signal to re-read the source, not a licence to trust the prose.

**Which revision the anchors describe.** Every anchor in this document was checked against engine-repo commit `a2c0baaf` ("Repair room measurements after the tiling is fixed"). Two commits have landed on `main` since then, so some anchors are now off by a known, constant amount.

`db740b28` ("Fix the letter-shape endpoints and the headless non-adjacency draw") and `cda480bb` ("Fix the rotated-pass merge-node lookup and the unassigned symmetric field") together shift `handlers.py` like this:

| anchor range in this document | add to get the current line |
|---|---|
| up to and including `:941` | no change |
| `:942` to `:1743` | **+13** |
| `:1744` and beyond | **+12** |

Spot-check values: `handle_single_oc` is documented as `:1078` and is now `:1091`; `handle_door_connectivity` is documented as `:1686` and is now `:1699`; `handle_space_optimization` is documented as `:2659` and is now `:2671`.

Two other files moved. `pythongui/GuiParameters.py` gained 5 lines in the `DimParameters` constructor, so `class GuiParameters` is now `:110` rather than `:105`. `source/graphoperations/triangularity_non_adj.py` gained 3 lines at `:456`, so anchors below that point are +3.

Anchors in `api.py`, `inputgraph.py`, `path_map.py`, `circulation.py`, the rest of the `source/` tree, `Space_Optimization/` and the test scripts are unaffected. When an anchor misses by roughly one of the amounts above, apply the offset before concluding the claim is wrong; when it misses by anything else, re-read the source.

Reliability is part of the navigation. Each dossier in the two reference layers (sections 9 and 10) carries a verdict from an independent verification pass: SOUND (no claim refuted), MINOR_ERRORS (some claims corrected in place), or UNRELIABLE (enough refuted claims that details cannot be trusted). Claims taken from non-SOUND dossiers were re-verified before landing in sections 1 through 8; when you go past this document into a non-SOUND dossier, re-verify its anchors yourself before acting on them.

Link conventions: dossier pointers are `graph/<id>.md` or `dim/<id>.md`. All 35 dossiers are published alongside this file in `GPLAN/documentation/algorithms/`, and every link was checked: 35 dossier links and 59 source links resolve, with no dossier left unlinked.

Source pointers are relative to `documentation/algorithms/`: `../../GPLAN/...` for the engine package (so `documentation/algorithms/../../GPLAN/api.py` is `GPLAN_Revamp/GPLAN/GPLAN/api.py`), `../../Space_Optimization/...` for the space-optimization tree, `../../test_*.py` and `../../local_engine_bridge.py` for the repo-root scripts, and `../door_connectivity.md` for the flat API docs one folder up. The Django backend is a **sibling repository**, not part of the engine tree: `gplan_backend/gplan_apis/views.py` means `GPLAN_Revamp/gplan_backend/gplan_apis/views.py`, which is `../../../gplan_backend/gplan_apis/views.py` from `documentation/algorithms/`. Backend anchors in this document are written in the short `gplan_backend/...` form for readability; prefix them with `../../../` to open them.

Never edit the mirror at `gplan_backend/GPLAN`: it is a submodule checkout of the same engine, and changes belong in the top-level tree that pushes to `nitantupasani/gplan_engine`.

## Find your entry point

| I want to... | Go to |
|---|---|
| Understand how a request flows end to end | [1. The pipeline in one page](#1-the-pipeline-in-one-page) |
| Know which endpoint, caller string, or flag reaches which handler | [2. Endpoint to algorithm map](#2-endpoint-to-algorithm-map) |
| Add or modify a shaped floorplan (L, T, U, Z, staircase, polygonal) | [3.1](#31-add-or-modify-a-shaped-floorplan-l-t-u-z-staircase-polygonal) |
| Change triangulation or connectivity repair | [3.2](#32-change-triangulation-or-connectivity-repair) |
| Change separating-triangle handling | [3.3](#33-change-separating-triangle-handling) |
| Change boundary, corner, or cardinal behaviour | [3.4](#34-change-boundary-corner-or-cardinal-behaviour) |
| Change REL construction or the rectangular dual | [3.5](#35-change-rel-construction-or-the-rectangular-dual) |
| Change corridor or circulation behaviour | [3.6](#36-change-corridor-or-circulation-behaviour) |
| Change the one-connected path or the stacked multiple-door composition | [3.7](#37-change-the-one-connected-path-or-the-stacked-multiple-door-composition) |
| Make rooms respect maximum dimensions, or change the degradation ladder | [4.1](#41-make-rooms-respect-maximum-dimensions-or-change-the-degradation-ladder) |
| Change plot-dimension fitting or the expand fallback | [4.2](#42-change-plot-dimension-fitting-or-the-expand-fallback) |
| Change the LP core | [4.3](#43-change-the-lp-core-itself) |
| Change the boundary pool or fix the batch collapse | [4.4](#44-change-the-boundary-pool-dim_on_paths_bdy-or-fix-the-batch-collapse) |
| Change multi-PTPG exact sizing or strictness | [4.5](#45-change-multi-ptpg-exact-sizing-or-strictness) |
| Change space-optimization or GA sizing | [4.6](#46-change-space-optimization-or-ga-sizing) |
| Add a field to the response, or change the serialization shape | [4.7](#47-change-the-response-payload-the-ui-object-or-the-serialization-shape) |
| Change the gapless pass, room-size caps, or dimension repair in api.py | [4.8](#48-change-apipy-post-processing-gapless-fill-size-caps-dimension-repair) |
| Check a cross-module rule before editing | [5. Global invariants](#5-global-invariants) |
| Decide whether breakage is pre-existing | [6. Known defects and traps](#6-known-defects-and-traps) |
| Confirm which copy of a file is live before opening it | [7. Dead code and duplications](#7-dead-code-and-duplications) |
| Know what a green test run actually proves | [8. Verifying a change](#8-verifying-a-change-tests-and-what-they-actually-pin) |
| Deep reference, graph side | [9. Graph algorithm reference](#9-graph-algorithm-reference-the-dossiers) |
| Deep reference, dimensioning side | [10. Dimensioning reference](#10-dimensioning-reference-the-dossiers) |
| See what this document still does not cover | [Known gaps in this document](#known-gaps-in-this-document) |

---

## 1. The pipeline in one page

Every graph-based shape enters the engine through one function, `Documents.get_floorplans` ([api.py:1215](../../GPLAN/api.py)), and leaves it through one attribute, `final_traversal`, read back at api.py:1429. Neither `api.py` nor `handlers.py` defines an HTTP route; the route table lives in the backend repo and in a Flask dev bridge, both mapped in [section 2](#2-endpoint-to-algorithm-map).

```
HTTP  POST /api/generate/<shape>
  |  gplan_backend/gplan_apis/urls.py:8            Django route table
  v
  |  gplan_backend/gplan_apis/views.py:803         DRF view; builds InputGraph at views.py:829
  v
  |  gplan_backend/gplan_apis/tasks.py:127         Celery task -> Documents.get_floorplans(**prepared_data)
  v
api.py:1215  Documents.get_floorplans             branch on count (1256 single / 1313 multiple),
  |                                               then on caller (1257-1311 / 1314-1411)
  v
handlers.py  handle_*                             branch on ui flags (isDimensioned, isMinDimensioned,
  |   handle_single            handlers.py:751     isCirculation, isNonAdj, is_multiple_door)
  |   handle_single_oc         handlers.py:1078
  |   handle_multiple          handlers.py:1041
  |   handle_multiple_oc       handlers.py:1327
  |   handle_letter_shape      handlers.py:939
  |   handle_door_connectivity handlers.py:1686
  v
InputGraph   source/inputgraph.py:75
  |   irreg_single_dual   inputgraph.py:202   (classic chain, below)
  |   irreg_multiple_dual inputgraph.py:852   (same spine, catalogue form)
  |   oneconnected_dual   inputgraph.py:1200  (cut-vertex form, calls irreg_multiple_dual at :1263)
  v
classic chain inside irreg_single_dual, in call order (inputgraph.py:202-315):
  1 biconnectivity augmentation  source/graphoperations/biconnectivity.py:18,:86   @ inputgraph.py:219-224
  2 triangulation                source/graphoperations/triangularity.py:254       @ inputgraph.py:228
  3 edge-to-vertex transform     source/floorplangen/transformation.py:13          @ inputgraph.py:242,:249
  4 separating-triangle removal  source/irregular/septri.py:273                    @ inputgraph.py:256
  5 boundary + CIP identification source/graphoperations/operations.py:85,:238
                                 source/irregular/shortcutresolver.py:14
                                 source/boundary/cip.py:11                         @ inputgraph.py:270-296
  6 NEWS 4-completion            source/boundary/news.py:249                       @ inputgraph.py:299
  7 contraction                  source/floorplangen/contraction.py:187            @ inputgraph.py:304-306
  8 expansion                    source/floorplangen/expansion.py:29,:53           @ inputgraph.py:310-312
  9 rectangular dual             source/floorplangen/rdg.py:20                     @ inputgraph.py:313
  v
api.py:1358 rectangularize_output -> api.py:1365 filter_output_by_cardinal -> api.py:1427-1452 serialize
```

Stages 1, 3 and 4 are conditional: biconnect runs only when `bcn.is_biconnected` fails (inputgraph.py:219-220), the transform loops run once per added edge (inputgraph.py:240-252), and `handle_STs` runs only when the Euler test at inputgraph.py:255 detects separating triangles. The full 27-call table, with the exact condition on each call, is in [single-dual core](graph/inputgraph-single-dual-core.md). `irreg_multiple_dual` (inputgraph.py:852) runs the same spine but replaces stages 6 to 8 with `generate_multiple_rel` (inputgraph.py:1412) and defers stage 9 to a post-loop at inputgraph.py:1116-1121; see [multi-dual and doors](graph/inputgraph-multidual-doors.md). Stages 7 and 8 are documented in [REL contraction and expansion](graph/rel-contraction-expansion.md); stage 9 and the flip enumeration in [dual, rdg and flippable](graph/dual-rdg-flippable.md).

**Three siblings bypass this chain entirely.** Multi-PTPG goes `Documents.get_multi_ptpg_floorplans` (api.py:1775) straight to `multi_ptpg_pipeline.run` (api.py:1800) and never touches `handlers.py` or `InputGraph` ([entrypoint wiring](graph/entrypoint-wiring.md), [concept trace](dim/dim-09-concept-trace.md)). Space optimization goes api.py:1459 to `handle_space_optimization` (api.py:1566, handlers.py:2659) into the `sys.path`-injected `negNew` module at handlers.py:2689, with no `InputGraph`. GA optimization goes api.py:1650 to `handle_ga_optimization` (api.py:1701, handlers.py:2845) into `ga_current` at handlers.py:2868, also with no `InputGraph` ([entrypoint wiring](graph/entrypoint-wiring.md) for all three).

**Where dimensioning attaches.** The live min-dim path hangs off `handle_door_connectivity` ([handlers.py:1686](../../GPLAN/handlers.py)): `get_max_dims` at handlers.py:1808, `irreg_multiple_dual(input_dims)` at handlers.py:1830/1836/1838, then per-candidate `solve_min_dim` (handlers.py:338) at handlers.py:1894, which calls `minimum_dimensioning.main` (source/dimensioning/minimum_dimensioning.py:767). The expand-only fallback runs `scale_plot_dimension` (inputgraph.py:597) at handlers.py:2173, and the gapless pass runs back in `rectangularize_output` (api.py:801). Note the whole block exists twice, PTPG at handlers.py:1787-2207 and non-PTPG at handlers.py:2240-2651. The older path is `single_floorplan` ([inputgraph.py:779](../../GPLAN/source/inputgraph.py)), which consumes `rel_matrix_list` and calls `floorplan_to_st`, and which cannot follow `irreg_single_dual` (see [invariant G2](#5-global-invariants)). Anchors and the eight-concept ledger are in [concept trace](dim/dim-09-concept-trace.md); the HTTP contract is one folder up in [door_connectivity.md](../door_connectivity.md).

---

## 2. Endpoint to algorithm map

Neither [api.py](../../GPLAN/api.py) nor [handlers.py](../../GPLAN/handlers.py) defines an HTTP route: both are plain library modules with no web-framework import (`api.py:8-23`, `handlers.py:1-35`), and every route lives either in the Django table at gplan_backend/gplan_apis/urls.py:4-15 or in the Flask dev bridge [local_engine_bridge.py](../../local_engine_bridge.py) (Flask imported at `local_engine_bridge.py:28`).

### Routes

| HTTP endpoint | Route | View (file:line) | Engine method (api.py) | Through handlers.py? |
|---|---|---|---|---|
| `POST /api/generate/<shape>` | urls.py:8 | `GenerateFloorplanView` views.py:797, `.post` views.py:803, Celery hop tasks.py:127 | `Documents.get_floorplans` `api.py:1215` | Yes, every `handle_*` in the table below |
| `POST /api/generate/multi-ptpg` | urls.py:7 | `GenerateMultiPTPGFloorplanView` views.py:1319, `.post` views.py:1349, task tasks.py:865 | `Documents.get_multi_ptpg_floorplans` `api.py:1775`, import `api.py:1791`, call `api.py:1800` | **No. Bypasses handlers.py entirely**, see below |
| `POST /api/generate/space-optimized` | urls.py:5 | `GenerateSpaceOptimizedFloorplanView` views.py:1122, `.post` views.py:1127, task tasks.py:485 | `Documents.get_space_optimized_floorplan` `api.py:1459` | Yes, `handle_space_optimization` called at `api.py:1566`, defined [handlers.py:2659](../../GPLAN/handlers.py). **Never touches `InputGraph`** |
| `POST /api/generate/ga-optimized` | urls.py:6 | `GenerateGAOptimizedFloorplanView` views.py:1179, `.post` views.py:1184, task tasks.py:746 | `Documents.get_ga_optimized_floorplan` `api.py:1650` | Yes, `handle_ga_optimization` called at `api.py:1701`, defined `handlers.py:2845`. **Never touches `InputGraph`** |
| `GET /api/task/<task_id>/` | urls.py:9 | `TaskResultView` views.py:1506, `.get` views.py:1511 | none, result lookup only | No |
| Flask `POST /api/generate/multi-ptpg` | `local_engine_bridge.py:132` | n/a (in-process) | `api.py:1775` | No |
| Flask `POST /api/generate/<shape>` | `local_engine_bridge.py:159` | n/a, payload built by `_prepare` | `api.py:1215` | Yes |
| Flask `GET /api/task/<task_id>/` | `local_engine_bridge.py:180` | n/a, in-memory dict | none | No |

Multi-PTPG is the one path that never enters the flag-dispatch layer: `api.py:1800` calls `multi_ptpg_pipeline.run(request_data)` and returns its dict verbatim, so no `GuiParameters`, no `handle_*`, and none of the min-dim solver stack participates. Its only `InputGraph` use is `door_connectivity` at [multi_ptpg_pipeline.py:68](../../GPLAN/source/multi_ptpg_pipeline.py). Space-optimized and GA go through handlers.py but build no graph at all: their handlers reach `negNew` (`handlers.py:2689`) and `ga_current` (`handlers.py:2868`) by `sys.path` injection.

In-process entry is also supported and is how the repo's test scripts drive the engine: `Documents.get_floorplans` (`api.py:1215`) and `Documents.get_multi_ptpg_floorplans` (`api.py:1775`) are called directly, with no server and no port (see [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)).

### Caller-string dispatch inside `Documents.get_floorplans` (`api.py:1215`)

The outer selector is `count` (`api.py:1256` single, `api.py:1313` multiple); the inner selector is the `caller` string, which is the shape slug from the URL.

| `count` | `caller` | Call site | Handler |
|---|---|---|---|
| 1 | `lshape` | `api.py:1262` | `handle_letter_shape` `handlers.py:939` (letter set `api.py:1258`) |
| 1 | `ushape` | `api.py:1268` | `handle_letter_shape` `handlers.py:939`. **Dead on arrival**, see below |
| 1 | `tshape` | `api.py:1274` | `handle_letter_shape` `handlers.py:939`. **Dead on arrival**, see below |
| 1 | `zshape` | `api.py:1280` | `handle_letter_shape` `handlers.py:939`. **Dead on arrival**, see below |
| 1 | `staircaseshape` | `api.py:1285` | `handle_staircase_shaped` `handlers.py:1032` |
| 1 | `rectangular`/`irregular`, `rectangular=True` | `api.py:1297` | `handle_single_oc` `handlers.py:1078` |
| 1 | `rectangular`/`irregular`, `rectangular=False` | `api.py:1299` | `handle_single` `handlers.py:751` |
| 1 | `door_connectivity` | `api.py:1309` | `handle_door_connectivity` `handlers.py:1686`, preceded by `set_is_multiple_door(False)` `api.py:1304`, `normalize_cardinal_constraints` `api.py:1305`, `apply_cardinal_ring` `api.py:1307` |
| 1 | anything else | `api.py:1311` | none: message only, **empty document, no error** |
| >1 | `lshape` | `api.py:1320` | `handle_multiple_l` `handlers.py:1015` |
| >1 | `rectangular` | `api.py:1325` | `handle_multiple_oc` `handlers.py:1327` |
| >1 | `irregular` | `api.py:1327` | `handle_multiple` `handlers.py:1041` |
| >1 | `door_connectivity` | `api.py:1353` | `handle_door_connectivity` `handlers.py:1686` after `set_is_multiple_door(True)` `api.py:1331`; the stacked one-connected composition at `api.py:1335-1350` can return before the handler is ever called |
| >1 | `multiple_l` | `api.py:1408` | `handle_multiple_l` `handlers.py:1015` |
| >1 | anything else | `api.py:1410` | none: message only, **empty document, no error** |

Renaming a slug therefore fails silently: an unrecognized `caller` produces the empty `Documents` built at `api.py:1419`, not a 4xx.

**`ushape`, `tshape` and `zshape` cannot reach their shape code over HTTP.** Only the `lshape` branch builds a `nodes_data` list and passes it: `api.py:1259-1261` constructs `gui.gui_class.Nodes` objects and `api.py:1262` calls `handle_letter_shape(ui, graph, nodes_data=nodes_data)`. The other three call `handle_letter_shape(ui, graph)` with no `nodes_data` (`api.py:1268`, `api.py:1274`, `api.py:1280`), and the handler's second statement is unconditional: `nodes_data = nodes_data if nodes_data is not None else gclass.app.nodes_data` (`handlers.py:941`, after an `assert` at `handlers.py:940`). Python evaluates the `else` branch whenever `nodes_data` is `None`, so there is no short circuit to save it. On the API path `gclass` is `None` (the parameter defaults to `None` at `handlers.py:939` and no `api.py` call site supplies it), so all three raise `AttributeError: 'NoneType' object has no attribute 'app'` before any letter-shape code runs. `POST /api/generate/ushape`, `/tshape` and `/zshape` therefore fail for every input. Either pass `nodes_data` from the three call sites or make `handlers.py:941` fall back to `[]` when `gclass` is `None`. `staircaseshape` is unaffected: `api.py:1285` calls `handle_staircase_shaped`, a different handler (`handlers.py:1032`) with no `nodes_data` line. Consequence for [recipe 3.1](#31-add-or-modify-a-shaped-floorplan-l-t-u-z-staircase-polygonal): you cannot exercise a T, U or Z edit through the bridge until this is fixed.

### Flags that select a solver family

| Flag | Parsed (Django) | Parsed (Flask bridge) | First read in the engine |
|---|---|---|---|
| `minDimEnabled` | views.py:835 | `local_engine_bridge.py:75` | `api.py:1226` (which `DimParameters` overload), `api.py:1231` `set_isMinDimensioned`, then `handlers.py:1751` / `handlers.py:1787` |
| `maxDimEnabled` | views.py:839 | `local_engine_bridge.py:76` | **Never. Transport-only**, see below |
| `circulationEnabled` | views.py:846 | `local_engine_bridge.py:127` | `api.py:1232` `set_isCirculation`, read at `handlers.py:1747` (delegates to `handle_circulation` `handlers.py:492`) |
| `non_adj` plus red edges | views.py:843, red edges split at views.py:824 (black at views.py:819) | `local_engine_bridge.py:70` | `api.py:1302` / `api.py:1329` `set_isNonAdj`, read at `handlers.py:1703` |
| `cardinal_constraints` | views.py:851 | `local_engine_bridge.py:128` | `api.py:1305` / `api.py:1332` normalize, ring applied `api.py:1307` / `api.py:1351` |
| `plot_width` / `plot_height` (door-connectivity) | views.py:903-904 | `local_engine_bridge.py:99-100` | `DimParameters` `api.py:1227`, unpacked `handlers.py:1806` and `handlers.py:2257` |
| `plot_width` / `plot_height` (GA) | `api.py:1684-1685`, defaults 40 / 30 | n/a | `handle_ga_optimization` `handlers.py:2845` |
| `plot_width` / `plot_height` (multi-PTPG) | `multi_ptpg_pipeline.py:180-181`, default -1 | same | threaded into `generate_floorplans` as `plot_w`/`plot_h` (`ptpg_floorplanner.py:820`); the reject filter is `ptpg_floorplanner.py:783` inside `_pdf_place` (`:603`), which returns `None` when the packed extent exceeds either positive plot dimension, repeated as the failsafe guard at `ptpg_floorplanner.py:912`. A clamp-into-plot pass runs earlier at `ptpg_floorplanner.py:545-549` |
| `strictness` | `multi_ptpg_pipeline.py:175`, validated `:176-177` | echoed for logging `local_engine_bridge.py:145` | `ptpg_floorplanner.py:954`, `:956-957`, `:959-960`. Multi-PTPG only, a no-op on every other endpoint |

`maxDimEnabled` never leaves the HTTP layer: it is not a key of `prepared_data` (views.py:910-933) and not a parameter of `Documents.get_floorplans` (`api.py:1215`). It only chooses whether the parser writes the open sentinel (views.py:888-892 for width, views.py:895-899 for height; `local_engine_bridge.py:76` and `:84`, applied at `:91` and `:95`). The engine re-derives the same fact by sniffing values: `get_max_dims` (`handlers.py:309-335`) returns `None, None` unless some entry satisfies `0 < value < 99999` (`handlers.py:329`), and it is called only from `handle_door_connectivity` (`handlers.py:1808`, `handlers.py:2260`). The sentinel semantics are [invariant G6](#5-global-invariants); the client-observable consequence is in [section 6](#6-known-defects-and-traps) under doc and test mismatches.

For the wiring detail see [entry-point wiring](graph/entrypoint-wiring.md), for flag plumbing see [flag plumbing](dim/dim-01-flag-plumbing.md), for the multi-PTPG internals see [multi-PTPG enumeration](graph/multi-ptpg-enumeration.md).

---

## 3. Change recipes: graph and topology

Each recipe names its owning dossiers with their verdicts. Anchors quoted here from MINOR_ERRORS or UNRELIABLE dossiers were re-checked when this document was assembled; if you go deeper into those dossiers, re-verify before citing.

### 3.1 Add or modify a shaped floorplan (L, T, U, Z, staircase, polygonal)

Owning dossiers: [L-shape core](graph/lshaped-core.md) (MINOR_ERRORS), [letter shapes T/U/Z/staircase](graph/letter-shapes-tuzs.md) (SOUND), [polygonal floorplans](graph/polygonal-floorplans.md) (MINOR_ERRORS).

**Read this before you start.** Three of the four letter-shape endpoints are dead on arrival: `POST /api/generate/ushape`, `/tshape` and `/zshape` raise `AttributeError` at `handlers.py:941` because only `api.py:1262` passes `nodes_data` and `gclass` is `None` on the API path. The full anchor set is in [section 2](#2-endpoint-to-algorithm-map). Practical effect: you can edit `tshape.py`, `zshape.py` or `ushape.py` all you like, but you cannot observe the result over HTTP until that line is fixed, and an `AttributeError` from the bridge is that bug, not yours. `lshape` is reachable in its non-dimensioned form only; the dimensioned branch dereferences `gclass` at `handlers.py:969` and fails the same way.

**Files in reading order**

1. [handlers.py](../../GPLAN/handlers.py) `handle_letter_shape`, 939-1013. The dispatch at 942-953, the `nodes_data`/`gclass` line at 941, and the mis-indented dimensioned branch at 968-975 where `Ushaped.UShapedFloorplan` sits inside the L branch. That mis-indentation is real but **GUI-only**: the dimensioned branch calls `dimgui.gui_fnc(..., gclass)` at handlers.py:965 and then `gclass.app.nodes_data` at handlers.py:969, so an HTTP request dies before line 975 ([invariant G8](#5-global-invariants), entry in [section 6](#6-known-defects-and-traps)).
2. [Lshaped.py](../../GPLAN/source/lettershape/lshape/Lshaped.py) `LShapedFloorplan` 24-75, then `connect_northeast` 434-451 and `find_cips_L_shaped` 593-628. The notch is one ordinary vertex, `graph.northeast` (Lshaped.py:439), pinned to a bounding-box corner by seeding `corner_points` (Lshaped.py:596-597) and deleted from the output later.
3. [tshape.py](../../GPLAN/source/lettershape/tshape/tshape.py) `TShapedFloorplan` 64-98 and `find_cips_T_shaped` 170-177: the two shape-defining blocks (dummy injection, corner pinning).
4. The clones: [zshape.py](../../GPLAN/source/lettershape/zshape/zshape.py):73 (one changed constant, `paths[3]`), [ushape.py](../../GPLAN/source/lettershape/ushape/ushape.py):96 (one dummy), [staircaseshape.py](../../GPLAN/source/staircaseshape/staircaseshape.py) 65-75 and 167.
5. Canonical order, per shape. L imports `modifiedCanonical` (Lshaped.py:9) and `canonicalTransition` (Lshaped.py:10), not the sibling `canonical.py`. The polygonal path uses a different implementation entirely, `source/polygonal/canonical.py:95`, reached through [handlers.py](../../GPLAN/handlers.py):1502 and `polyonalinput` ([inputgraph.py](../../GPLAN/source/inputgraph.py):849-850). T, Z, U and staircase use **no** canonical order: they copy the contraction/expansion block (tshape.py:130-136, identical to inputgraph.py:304-312), as does L's `trivialL` fallback (Lshaped.py:99-108). Which copy is live is settled in [canonical order family](graph/canonical-order-family.md).

**Invariants**

- T, U, Z and staircase are near-clones of one another; nine helper functions exist as near-identical copies across the four files plus Lshaped.py (see the table in [letter shapes T/U/Z/staircase](graph/letter-shapes-tuzs.md)). An edit usually must be replicated in each clone.
- NEWS must be the last four indices ([invariant G11](#5-global-invariants)): `exp.basecase` hard-codes `nodecnt-4 .. nodecnt-1` ([expansion.py](../../GPLAN/source/floorplangen/expansion.py):39-48) and `construct_dual` drops exactly the last four ([rdg.py](../../GPLAN/source/floorplangen/rdg.py):69-72).
- Every dummy room must be registered in `graph.extranodes` (Lshaped.py:533, tshape.py:84-85, staircaseshape.py:83-84).
- Structural gate: exactly 6 CIPs for T/U/Z/staircase (tshape.py:69, staircaseshape.py:67), at most 5 for L (Lshaped.py:39).

**What breaks silently**

- Skip the `extranodes` registration and the dummy renders as a real room: [drawing.py](../../GPLAN/pythongui/drawing.py):210, :238, :262 and [handlers.py](../../GPLAN/handlers.py):467 filter on nothing else, and `get_final_traversal` drops only that list ([inputgraph.py](../../GPLAN/source/inputgraph.py):1620-1622).
- The `len(cip) != 6` bail-out returns a string that callers discard (handlers.py:947/949/951, inputgraph.py:1497), so geometry stays at its `np.zeros` initial value (inputgraph.py:128) and the endpoint still reports success.
- Copying `Lshaped.get_rel` (Lshaped.py:498-528) into a new shape gives a `TypeError`: it calls `cntr.contract(matrix, goodnodes)` with 2 arguments (Lshaped.py:505) against the 3-parameter [contraction.py](../../GPLAN/source/floorplangen/contraction.py):187.
- The polygonal package is API-dead: `handle_poly` (handlers.py:1499) is called only from `main.py:56`, never from [api.py](../../GPLAN/api.py). See [section 7](#7-dead-code-and-duplications).

**Tests to run**

No test pins any shaped-floorplan behaviour. All three scripts drive either `caller="door_connectivity"` (`test_max_dimensions.py:108-113`) or the multi-PTPG placer (`test_multi_ptpg.py:58`); see [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin). Exercise shapes by hand through [local_engine_bridge.py](../../local_engine_bridge.py), which is the only stated verification route for this recipe and for 3.2, 3.3, 3.5, 3.6 and 3.7. The run and poll protocol is in [section 8, Running the Flask bridge](#running-the-flask-bridge); note that `ushape`, `tshape` and `zshape` return a `FAILURE` result there until `handlers.py:941` is fixed.

### 3.2 Change triangulation or connectivity repair

Owning dossiers: [connectivity augmentation](graph/connectivity-augmentation.md) (MINOR_ERRORS), [triangulation core](graph/triangulation-core.md) (MINOR_ERRORS).

**Files in reading order**

1. [inputgraph.py](../../GPLAN/source/inputgraph.py) `irreg_single_dual` 219-234: the guard, the write-back into `self.matrix`, the `edgecnt` bumps. Two of the three sibling blocks are true copies of it, calling the same modules: 671-688 (`bcn.biconnect` at :673, `trng.triangulate` at :681) and 886-905 (`bcn.biconnect` at :887, `trng.triangulate` at :899). Imports are `bcn` at inputgraph.py:24 and `trng` at inputgraph.py:36.
2. **The fourth block is not a copy.** `door_connectivity`'s augmentation at inputgraph.py:365-397 branches on `is_non_adj` twice, at inputgraph.py:366 and inputgraph.py:384, and on the true side runs different modules: `bcn_non_adj.biconnect(self.matrix, non_adj_list)` at inputgraph.py:369 (import `bcn_non_adj` at inputgraph.py:25) and `trng_non_adj.triangulate(self.matrix, bcn_edges_added, self.coordinates, non_adj_list)` at inputgraph.py:385 (import `trng_non_adj` at inputgraph.py:37). The false side, inputgraph.py:375-376 and inputgraph.py:390-392, is the plain pair. Replicating a `biconnectivity.py` or `triangularity.py` fix into 365-397 without also fixing `biconnectivity_non_adj.py` and `triangularity_non_adj.py` leaves every non-adjacency request on the old behaviour. The write-back and `edgecnt` bumps at inputgraph.py:377-380 and inputgraph.py:394-397 are shared by both sides.
3. [connect_graph.py](../../GPLAN/source/graphoperations/connect_graph.py) `one_connected` 9-21.
4. [biconnectivity.py](../../GPLAN/source/graphoperations/biconnectivity.py) `biconnect` 86-116, with `is_biconnected` 18-29.
5. [biconnectivity_non_adj.py](../../GPLAN/source/graphoperations/biconnectivity_non_adj.py) `biconnect` 223-249 and `connect_blocks` 160-222.
6. [triangularity.py](../../GPLAN/source/graphoperations/triangularity.py) `triangulate` 254-283, `get_nontriangular_face` 137-182, `get_tri_edges` 184-225.
7. [earclipping.py](../../GPLAN/source/graphoperations/earclipping.py) `triangulate` 176-249.
8. [triangularity_non_adj.py](../../GPLAN/source/graphoperations/triangularity_non_adj.py) `get_tri_edges` 266-427 and `triangulate` 430-474 (shapely-based, no ear clipping).

**Invariants**

- `biconnect` never mutates its input; the caller writes the edges and bumps the count (inputgraph.py:221-224).
- Only the boolean `bcn_edges_added` reaches triangulation (inputgraph.py:225, 228-230), and when it is true the user coordinates are discarded for `nx.planar_layout` (triangularity.py:276-277).
- `tri_edges` must not contain an edge already in the matrix, or `edgecnt` drifts (inputgraph.py:231-234); dedup is only against the current face (triangularity.py:210-224).
- Boundary detection presumes maximal planarity: `get_bdy` keeps directed edges lying in exactly one triangle ([operations.py](../../GPLAN/source/graphoperations/operations.py):107).

**What breaks silently**

- Under-triangulation with no signal: earclipping.py:236-245 drops a vertex without emitting a triangle, and triangularity_non_adj.py:367 skips its fallback once any diagonal was added. The victims are the Euler gate at inputgraph.py:255 and `opr.get_bdy` (operations.py:85-115), which then returns a wrong outer cycle.
- `one_connected` mutates the matrix in place but leaves `edgecnt` stale (connect_graph.py:19-21 against handlers.py:753).
- `connect_blocks` adds edges taken straight from the non-adjacency list when the legal pool cannot span the blocks (biconnectivity_non_adj.py:209-221): no exception, no flag. See [section 6](#6-known-defects-and-traps).
- `triangularity_non_adj.py:457` calls `plt.show()` unconditionally, blocking the request thread on the non-adjacency API path (handlers.py:1710). See [section 6](#6-known-defects-and-traps).

**Tests to run**

No test pins this behaviour. `test_max_dimensions.py` runs the whole door-connectivity path in-process, so a crash or an empty catalogue surfaces there ([section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)).

### 3.3 Change separating-triangle handling

Owning dossiers: [separating-triangle detection and covers](graph/septri-detection-covers.md) (MINOR_ERRORS), [door-connectivity ST handlers](graph/septri-door-handlers.md) (SOUND).

**Files in reading order**

1. [inputgraph.py](../../GPLAN/source/inputgraph.py):255-265, the Euler gate and `st.handle_STs(self.matrix, positions, 1)`. Compare inputgraph.py:929, which passes `20`. The literal is the count of alternative resolutions requested: one for the single-dual path, up to twenty for the multiple-dual path.
2. [septri.py](../../GPLAN/source/irregular/septri.py) `handle_STs` 273-357 and `point_in_triangle` 37-53 (a geometric point-in-triangle test on the drawing, not a topological one).
3. [septri.py](../../GPLAN/source/irregular/septri.py) `get_multiple_separating_edge_covers` 197-219, `get_separating_edge_cover` 159-177, `generate_alternate_graph` 102-138, `get_graph_cover` 140-157.
4. [septri.py](../../GPLAN/source/irregular/septri.py) `remove_separating_triangles` 221-271, the bisect-and-retriangulate step.
5. [septri.py](../../GPLAN/source/irregular/septri.py) `handle_non_trivial_ST_Door_connectivity` 359-697, its non-adjacency copy 700-1144, and the read-only checker `handle_STs_Door_connectivity` 1146-1217.

**Invariants**

- `extra_nodes` is `{new_label: [u, v]}`, unpacked positionally at inputgraph.py:262-265 and 942-945; `irreg_nodes1` is the absorbing room (inputgraph.py:1591, operations.py:279-282).
- New vertex labels are consecutive from `graph.number_of_nodes()` (septri.py:236, 242, 270), so node label equals matrix index after `nx.to_numpy_array` (septri.py:356).
- Arity differs by family: `handle_STs` returns 2 values (septri.py:357), the door handlers return 3 (consumed at inputgraph.py:437, 440).
- The door handlers add no vertex; `extra_nodes` is always `[]` (septri.py:697, 1144), so merge bookkeeping at inputgraph.py:446-450 never runs.
- `one_connected` must stay the pre-augmentation snapshot (inputgraph.py:360-361), or the "spend synthetic edges first" passes find nothing.

**What breaks silently**

- The `1e-7` band at septri.py:50-51 classifies a near-edge node as outside, so a real separating triangle lands in `edge_to_faces` and `remove_separating_triangles` (septri.py:247-250) re-triangulates around it. See [section 6](#6-known-defects-and-traps).
- Detection and re-verification disagree by construction: the checker uses `point_in_triangle` (septri.py:1189) while the handler recount uses `point_in_triangle2` with an extra K4 gate (septri.py:1232-1234, 1468). The victim is `check_ptpg` (inputgraph.py:413-424), which flips the entire door path.
- Cases 3 to 5 delete user-drawn adjacencies with no record: `extraedges` tracks only added edges (inputgraph.py:513-516).
- Changing `handle_STs`'s return arity breaks [bdy.py](../../GPLAN/bdy.py):139, `source/trial/bdy.py:138` and Lshaped.py:27, :116.

**Tests to run**

No test pins ST handling. `test_max_dimensions.py` and `test_api_cardinal_constraints.py` both drive `door_connectivity`, so they cover the door handlers as smoke only ([section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)).

### 3.4 Change boundary, corner, or cardinal behaviour

Owning dossiers: [boundary, NEWS and CIP](graph/boundary-news-cip.md) (SOUND), [single-dual core](graph/inputgraph-single-dual-core.md) (SOUND), [multi-dual and doors](graph/inputgraph-multidual-doors.md) (SOUND).

**Files in reading order**

1. [inputgraph.py](../../GPLAN/source/inputgraph.py):267-301, the whole unit in one block: `get_bdy`, `get_shortcut`, `find_cip`, `find_bdy`/`bdy_path`, `add_news`.
2. [operations.py](../../GPLAN/source/graphoperations/operations.py) `get_bdy` 85-115 and `ordered_bdy` 238-258.
3. [shortcutresolver.py](../../GPLAN/source/irregular/shortcutresolver.py) `get_shortcut` 14-31 and `remove_shortcut` 34-64.
4. [cip.py](../../GPLAN/source/boundary/cip.py) `find_cip` 11-53, the entire file.
5. [news.py](../../GPLAN/source/boundary/news.py) `find_bdy` 21-33, `bdy_path` 35-65, `multiple_corners` 95-119, `all_boundaries` 121-210, `add_news` 249-271.
6. [inputgraph.py](../../GPLAN/source/inputgraph.py) `filter_boundaries_by_cardinal` 1365-1409, applied at 951 and 1037.

**The api.py half of the same feature.** Boundary and CIP code is only where cardinal pins are *enforced*. Parsing, ring augmentation, output filtering and the fallback ladder all live in [api.py](../../GPLAN/api.py), and a cardinal change that skips them is half a change. Read these in this order, after the six files above:

7. `normalize_cardinal_constraints`, defined api.py:126, called api.py:1305 (single) and api.py:1332 (multiple). Turns the request list into `(node, dir_idx)` pairs against the `CARDINAL_DIR_INDEX` map at api.py:123.
8. `apply_cardinal_ring`, defined api.py:349, called api.py:1307 (single) and api.py:1351 (multiple). Adds boundary-ring edges so the pinned rooms can reach the outer face.
9. `_ring_order_satisfies`, api.py:153. The admissibility test `apply_cardinal_ring` uses: whether a cyclic order admits a four-arc N, E, S, W split under rotation and reflection with every pin inside its arc. It mirrors `filter_boundaries_by_cardinal` (inputgraph.py:1365), so the two must be changed together ([invariant G12](#5-global-invariants)).
10. `plan_satisfies_cardinal`, api.py:374, with the `dir_idx` to strip mapping at api.py:401-408 (0 north, 1 east, 2 south, 3 west). This is the geometric re-check on finished plans.
11. `filter_output_by_cardinal`, defined api.py:418, called api.py:1365 and api.py:1394. Drops plans that fail the geometric check.
12. **The degradation ladder, api.py:1365-1406.** When the filter empties the batch, api.py:1374-1382 builds up to two retry attempts: rung 1 keeps the pins but relaxes the adjacency set to a spanning tree (`spanning_tree_edges` at api.py:1376, defined api.py:1148; note `" Adjacency constraints were relaxed to satisfy cardinal directions."` at api.py:1379-1380, appended only when the tree really is smaller, api.py:1378); rung 2 restores the original edges and drops the pins entirely, with the note `" Cardinal constraints could not be satisfied and were ignored."` at api.py:1381-1382. Each attempt rebuilds an `InputGraph`, re-applies the ring and re-runs `handle_door_connectivity` (api.py:1383-1390), re-runs the gapless pass and the filter (api.py:1392-1394), and breaks on the first non-empty result (api.py:1398-1406). The `"ignored"` substring the cardinal test skips on is produced at api.py:1382 and nowhere else, so any change to the ladder changes what `test_api_cardinal_constraints.py:187` and `:233` actually check.

**Invariants**

- NEWS vertices are appended last, in N, E, S, W order, and the whole engine assumes it arithmetically: [invariant G11](#5-global-invariants).
- Consecutive arcs share their corner node (news.py:60-63), which the rotation and reflection identity depends on (inputgraph.py:1396-1403); the four-path candidate shape is [invariant G12](#5-global-invariants).
- `add_news` assumes exactly four boundary paths; the shortcut-destruction loop at inputgraph.py:283-296 exists only to force the CIP count down to four ([invariant G3](#5-global-invariants)).
- Cardinal constraints affect the multiple-dual path only ([invariant G10](#5-global-invariants)); `irreg_single_dual` (inputgraph.py:202-315) ignores `self.cardinal_constraints` entirely.

**What breaks silently**

- Reordering NEWS in `add_news` raises nothing; the plan comes out rotated or transposed via dual.py:35, :82, :153, :196.
- `len(cips) > 4` while `len(shortcuts) <= 4`: the loop at inputgraph.py:283 never runs, and inputgraph.py:294-296 hands `bdy_path` more than four corner candidates.
- `sr.remove_shortcut` adds a vertex without refreshing `self.bdy_nodes` / `self.bdy_edges`, so inputgraph.py:294 rebuilds the boundary from stale lists. See [section 6](#6-known-defects-and-traps).
- An empty filtered `cip_list` is not rescued by the fallback at inputgraph.py:978-979, because the filter overwrote `cip_list` at inputgraph.py:951. The result is zero floorplans, handled only by the ladder at api.py:1365-1406.

**Tests to run**

`test_api_cardinal_constraints.py`. Note what it pins: `check_side` (:71-103) is a strip-intersection test on direction only, never a width, height or plot fit. Two cases skip their real assertion when the message contains `"ignored"`: T7 at `:187` and T8 at `:233`. T3 has no such guard; `test_api_cardinal_constraints.py:126` is a bare `assert len(plans) > 0`, which is all T3 pins even though it is the deliberate impossible-constraints case. (An earlier draft of this recipe listed `:126` among the `"ignored"` guards; that was wrong, and [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin) has always described it correctly.) Full analysis in [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin).

### 3.5 Change REL construction or the rectangular dual

Owning dossiers: [REL contraction and expansion](graph/rel-contraction-expansion.md) (SOUND), [REL to rectangular dual](graph/dual-rdg-flippable.md) (SOUND).

**Files in reading order**

1. [inputgraph.py](../../GPLAN/source/inputgraph.py):304-315: `degrees`, `goodnodes`, `contract`, `basecase`, the `expand` loop, `construct_dual`.
2. [contraction.py](../../GPLAN/source/floorplangen/contraction.py) `contract` 187-225, then `is_goodvertex` 52-82 and `cntr_nbr` 84-122.
3. [expansion.py](../../GPLAN/source/floorplangen/expansion.py) `basecase` 29-50, `expand` 53-70, `get_case` 73-175 (a normaliser as much as a dispatcher), then the ten case bodies 203-547.
4. [rdg.py](../../GPLAN/source/floorplangen/rdg.py) `construct_dual` 20-51 and `get_dimensions` 54-89.
5. [dual.py](../../GPLAN/source/floorplangen/dual.py) `populate_t1_matrix` 21-65 and `populate_t2_matrix` 139-176 (opposite axis conventions).
6. [flippable.py](../../GPLAN/source/floorplangen/flippable.py) `get_flippable_edges` 20-64, `get_flippable_vertices` 66-118, `resolve_flippable_edge` 120-145, `resolve_flippable_vertex` 147-178, driven by `generate_multiple_rel` (inputgraph.py:1412-1450).

**Invariants**

- `exp.expand` must shrink `cntrs` or the loop at inputgraph.py:311-312 never terminates. There is no iteration guard; the pop is at expansion.py:64.
- Label 2 is the S-to-N relation, label 3 the W-to-E relation, stored one-directional (expansion.py:42-48) and assumed by dual.py:133, :229, operations.py:132 and all of flippable.py ([invariant G11](#5-global-invariants)).
- Around each interior vertex the incident edges must form four contiguous nonempty label blocks. Nothing checks it; violation hangs dual.py:129-135 and :225-231 rather than raising.
- The NEWS label sentinels in the REL are load-bearing for `oneconnected_dual` corner detection: inputgraph.py:1269-1276 reads literal `3` and `2` entries against `n-1`, `n-4`, `n-3`, `n-2` to recover `[nw, ne, se, sw]` ([invariant G3](#5-global-invariants)).

**What breaks silently**

- Contraction stalls after one barren pass through the deque (contraction.py:205, 212, 223) and never reports it; `basecase` then labels every node still adjacent to N (expansion.py:39-41). The victim is `dual.get_t1_ordered_children` (dual.py:129-135), which hangs.
- Change how `add_news` numbers the exterior vertices or how labels are encoded and every one-connected input starts raising `OCError` at inputgraph.py:1323, because the corner scan at inputgraph.py:1269-1276 stops matching.
- `rdg.py:77-78` silently skips a node missing from T1, leaving a zero-width room; the T2 branch has no matching guard and raises `ValueError` from `np.argmax` (rdg.py:86).
- `generate_multiple_rel` computes the entire flip closure (inputgraph.py:1437-1449) before `floorplan_limit` can stop anything (inputgraph.py:999).

**Tests to run**

No test pins REL or dual output. `test_max_dimensions.py` exercises the path end to end, but its strongest assertion is that every room clears its own minimum (:208-217). `test_multi_ptpg.py` does not touch this code: the PDF placer replaces dual construction (`ptpg_floorplanner.py:819-963`). See [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin).

### 3.6 Change corridor or circulation behaviour

Owning dossiers: [circulation graph half](graph/circulation-root-graph.md) (SOUND), [circulation geometry half](graph/circulation-root-geometry.md) (MINOR_ERRORS).

The live implementation is the root [circulation.py](../../GPLAN/circulation.py), imported as `cir` at [handlers.py](../../GPLAN/handlers.py):31. `source/circulation/circulation.py` and `source/multiple_circ.py` have no importer anywhere in the tree, so edits there change nothing ([section 7](#7-dead-code-and-duplications)).

**Files in reading order**

1. [handlers.py](../../GPLAN/handlers.py) `call_circulation_new` 79-306, the only place the module is used: `cir.Room` at 92-99, `cir.RFP` at 101, `cir.circulation` at 104, `circulation_algorithm` at 116, `adjust_RFP_to_circulation` at 230.
2. [handlers.py](../../GPLAN/handlers.py) `handle_circulation` 492 onward, with the six `call_circulation_new` call sites at 527, 577, 634, 685, 715, 737.
3. [circulation.py](../../GPLAN/circulation.py) `__init__` 52-77 and `circulation_algorithm` 235-305, the BFS over triangular faces that splices in corridor vertices.
4. [circulation.py](../../GPLAN/circulation.py) `remove_corridor` 149-233, `remove_redundant_corridors` 384-443, `min_tree_set_cover` 341-382.
5. [circulation.py](../../GPLAN/circulation.py) `adjust_RFP_to_circulation` 446-526, the geometry half. Its five steps, re-read and anchored for this document rather than taken from the MINOR_ERRORS dossier: the optional minimisation at circulation.py:460-461 (`remove_redundant_corridors` only when `rem_red_rooms == 1`); the corridor loop at circulation.py:475-487, deliberately starting at `start + 1` so the first corridor (the entry door) never shifts a boundary; per corridor, `corridor_boundary_rooms` at circulation.py:481 then `add_corridor_between_2_rooms` at circulation.py:483 (defined circulation.py:529), which is what actually records the pushes into `temp_push_states` and `done_rooms`; the transfer of `room.target` into `rel_push_T/B/L/R` at circulation.py:491-502; the single application pass `push_edges(room)` at circulation.py:505-506; and the optional feasibility check at circulation.py:510-524 (`check_dimensions_feasibility` for the dimensioned case, `check_mindim_feasibility` at circulation.py:519 for the min-dim case), whose result is stored as `is_dimensioning_successful`. A graph with no corridors returns at circulation.py:525-526 without touching geometry. The deeper per-edge machinery (`add_corridor_between_2_rooms` at circulation.py:529, `push_edges` at circulation.py:824) is where the dossier's anchors were unreliable; verify those against the file before citing them (see [circulation geometry half](graph/circulation-root-geometry.md)).

**Invariants**

- Rooms occupy `0 .. m-1` and corridors `m .. m+k-1` in BFS order (circulation.py:285); corridor `m` is the entry door and is excluded from minimisation (circulation.py:394, :421).
- Entry vertices arrive 1-indexed and are converted at circulation.py:250.
- The entry edge must be exterior. The only detection is a `remove_edge` failure returning `0` (circulation.py:268-271), checked at handlers.py:118.
- `self.adjacency` values are sorted room pairs (circulation.py:291-293); `remove_corridor`'s membership test at circulation.py:169 depends on it.
- `adjust_RFP_to_circulation` is written to run once per object: `temp_push_states` (circulation.py:57) and `done_rooms` (circulation.py:77) are initialised in `__init__` and never cleared, while `add_corridor_between_2_rooms` (circulation.py:529-615) only appends to them (circulation.py:554-558, :567-571, :580-584, :593-597) and then re-walks the whole accumulated list at circulation.py:609. Yet handlers.py:262 calls the method a second time on the same object, after handlers.py:230, so the second run replays the first run's pushes.

**What breaks silently**

- **The gclass trap on the API path**: `circulationEnabled=1` over HTTP raises `AttributeError` before any circulation runs, because `handle_circulation` dereferences `gclass` unconditionally and the API passes `None`. Full anchors in [section 6](#6-known-defects-and-traps); the general rule is [invariant G8](#5-global-invariants).
- `remove_corridor`'s swap at circulation.py:161-162 reads the already reassigned `v1`, collapsing `(5, 3)` to `(3, 3)`; the call then falls through to "The rooms are not adjacent" at circulation.py:230.
- `min_tree_set_cover` can spin forever: the universe is every room (circulation.py:355) but subsets come only from corridors above `m` (circulation.py:394), so a room covered solely by the door corridor never leaves `X` (loop at circulation.py:362-379).
- `plot` ends in `plt.show()` (circulation.py:956) and is called twice per run from handlers.py:103 and :117. See [section 6](#6-known-defects-and-traps).

**Tests to run**

No test pins circulation. None of the three scripts sets `circulationEnabled` ([section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)), and the path is reachable only from the Tk GUI entry point `GPLAN/main.py:40`.

### 3.7 Change the one-connected path or the stacked multiple-door composition

Owning dossiers: [InputGraph single-dual core](graph/inputgraph-single-dual-core.md) (SOUND) for `oneconnected_dual`, [entry-point wiring](graph/entrypoint-wiring.md) (SOUND) for the api.py composition. Neither dossier owns `stacked_oneconnected_floorplans` as a unit; the anchors below were read for this document.

A one-connected input is a graph with a cut vertex, typically two wings joined through one room. Two entirely different mechanisms handle it, and which one you get depends on where the request enters.

**Files in reading order**

1. [inputgraph.py](../../GPLAN/source/inputgraph.py) `oneconnected_dual` at inputgraph.py:1200. It splits the graph at the cut vertex, builds a dual per component through `irreg_multiple_dual` at inputgraph.py:1263, recovers each component's four corner rooms from the REL label sentinels at inputgraph.py:1269-1277, and stitches the components. `"single"` and `"multiple"` are the two modes, chosen by the string argument.
2. The guard that makes it a fallback rather than a primary path: `if (bcn.is_biconnected(self.matrix)): raise BCNError` at inputgraph.py:1209-1210. A graph that is already biconnected, which is every graph that has been through `door_connectivity`'s augmentation, exits here immediately.
3. The three `OCError` raise sites, inputgraph.py:1238 (a cut vertex shared by more than two components), inputgraph.py:1241 (more than two components) and inputgraph.py:1323 (an empty encoded matrix after the corner scan). These are control flow, not failures ([invariant G5](#5-global-invariants)): the corner scan at inputgraph.py:1269-1276 failing to match is what makes inputgraph.py:1323 fire, which is why any change to NEWS numbering or REL label encoding breaks every one-connected input at once ([invariant G3](#5-global-invariants)).
4. The call sites that matter for HTTP: `handlers.py:1756` (`oneconnected_dual("single")`, non-min-dim door connectivity) and `handlers.py:1833` (`oneconnected_dual("multiple")`, min-dim door connectivity), each wrapped in `except inputgraph.OCError` / `except inputgraph.BCNError` blocks that fall back to `irreg_multiple_dual(input_dims)` at handlers.py:1836 and handlers.py:1838. Under cardinal pins the whole branch is skipped: the guard at handlers.py:1821 sends the run straight to `irreg_multiple_dual(input_dims)` at handlers.py:1830 instead, and the comment at handlers.py:1822-1829 explains why (by that point `door_connectivity` has already made the graph biconnected, so `oneconnected_dual` would always raise `BCNError`) ([invariant G10](#5-global-invariants)). The GUI-only call sites are handlers.py:358, :611, :1082, :1157, :1206, :1331, :1365 and :1465.
5. [api.py](../../GPLAN/api.py) `stacked_oneconnected_floorplans` at api.py:939, with its per-rectangle serializer `_stacked_room_dict` at api.py:878. This is the newer path and it does **not** go through `InputGraph.oneconnected_dual`.
6. The composition's call site and early return, api.py:1335-1350: it runs only for `count > 1`, `caller == "door_connectivity"` and an **empty** `non_adj_edge_list` (`api.py:1335`), and when it produces anything it builds its own `Documents` at api.py:1346-1348, restores `builtins.print` at api.py:1349 and returns at api.py:1350, **before** `apply_cardinal_ring` (api.py:1351) and `handle_door_connectivity` (api.py:1353) are ever called.
7. `ui.set_is_multiple_door(True)` at api.py:1331 (and `False` at api.py:1304). Inside handlers it is read at handlers.py:1753 and handlers.py:2215, unpacked alongside the min-dim inputs at handlers.py:1806 and handlers.py:2257, and it selects the output ordering at handlers.py:2193 and handlers.py:2203 (and the non-PTPG copies at handlers.py:2666 and handlers.py:2674).

**Invariants**

- The stacked composition owns the whole response when it fires. Anything you add to the normal door-connectivity path (the gapless pass, the cardinal ladder, the ptpg_graph attachment at api.py:1422-1425) is **not** applied to a stacked result, because api.py:1350 returns first. Adding a response field means adding it in two places.
- `is_multiple_door` and `optimal_floorplan` are mutually exclusive selectors at handlers.py:2193 and handlers.py:2203: the optimal-area branch is guarded by `multiple_door is not True`.
- The REL label sentinels `3` and `2` read at inputgraph.py:1269-1276 are the same convention as [invariant G11](#5-global-invariants). There is no symbolic constant.
- `oneconnected_dual("multiple")` resets `self.area` at inputgraph.py:1346 and never refills it (see [section 6](#6-known-defects-and-traps)), so anything downstream that trusts `area` must recompute. `GuiParameters._append_output_data` does recompute it, through the nested `find_areas` at GuiParameters.py:398-404, but only when `len(graph_new.area) < graph_new.nodecnt` (GuiParameters.py:410-411).

**What breaks silently**

- Turning an `OCError` into a raised error converts a routine fallback into a task failure ([invariant G5](#5-global-invariants)).
- Widening the `if not non_adj_edge_list` guard at api.py:1335 silently diverts non-adjacency requests into a path that never applies the cardinal ring.
- `show_warning` is called from inside the `except OCError` handler at handlers.py:1835, and it opens a Tk dialog with no `gclass` guard (see [section 6](#6-known-defects-and-traps)). On a headless host the fallback itself is what raises.

**Tests to run**

None. No test in the repository builds a one-connected input or asserts anything about the stacked composition. Exercise it through the bridge with a cut-vertex graph, `count > 1`, `caller` `door_connectivity` and no non-adjacency edges ([section 8, Running the Flask bridge](#running-the-flask-bridge)).

---

## 4. Change recipes: dimensioning and output

Recipes 4.1 through 4.6 cover the two solver stacks and the two standalone engines. Recipes 4.7 and 4.8 cover what happens to the geometry after a solver returns: the `ui` object, the serialization loop, and the api.py post-processing that is the last code to touch client geometry.

**A note on numbers in this section.** Three figures quoted here (16 rooms over ceiling, the 19-room uncapped baseline, and the 2 / 14 / 30 plan counts) are **measured observations from specific runs**, not properties of the source, and nothing in the repository pins them. They are labelled where they appear. Treat them as dated evidence that a behaviour existed, not as anchors.

### 4.1 Make rooms respect maximum dimensions, or change the degradation ladder

Owned by [concept trace](dim/dim-09-concept-trace.md) (SOUND, the rung-by-rung ledger), with [flag plumbing](dim/dim-01-flag-plumbing.md) (MINOR_ERRORS) for how a ceiling reaches the engine and [solver driver](dim/dim-06-min-dimensioning-driver.md) (UNRELIABLE, re-verify its anchors) for rung 1.

**Files in reading order**

1. [handlers.py](../../GPLAN/handlers.py) `get_max_dims`, handlers.py:309-335: decides whether any ceiling exists at all.
2. [minimum_dimensioning.py](../../GPLAN/source/dimensioning/minimum_dimensioning.py) `upper_bound`, minimum_dimensioning.py:158-177, with `DEFAULT_UB_FACTOR = 5` at :148 and `SOLVER_UB_SLACK` at :155. Rung 1.
3. handlers.py:338-353 `solve_min_dim`: rung 2, the per-topology release.
4. handlers.py:2069-2121, and its near-verbatim duplicate at handlers.py:2505-2569: rung 3, the plot-cap-only retry.
5. [api.py](../../GPLAN/api.py) `_room_size_caps` at api.py:640 and `_fill_gaps` at api.py:710, driven from api.py:834-840. Rung 4.
6. `repair_dimensions` at api.py:621, env gate `REPAIR_DIMENSIONS` at api.py:618, called at api.py:856. An undocumented fifth rung.

**Invariants**

- The engine has no `maxDimEnabled` flag; a ceiling is inferred by the 99999 sentinel test at handlers.py:329, and the sentinel plus the widening formula are [invariant G6](#5-global-invariants). An all-sentinel list yields `(None, None)` at handlers.py:335.
- Only `handle_door_connectivity` (handlers.py:1686) reads maxima: `get_max_dims` is called at handlers.py:1808 and handlers.py:2260 and nowhere else.
- The solver never sees a raw ceiling. It sees `min(5*low, max(supplied, 2.5*low))`, minimum_dimensioning.py:177, which becomes the negative back-edge at minimum_dimensioning.py:238.
- `capped` must equal `max_width is not None or max_height is not None`; six copies of that expression exist (handlers.py:1896, :2006, :2121, :2324, :2437, :2568; verified by grep during assembly).
- The PTPG block handlers.py:1787-2207 and the non-PTPG block handlers.py:2240-2651 are copies selected by `if (checkPTPG):` at handlers.py:1745. Edit both.

**What breaks silently**

- Tighten `upper_bound` to honour the raw maximum and the catalogue collapses; the reason is measured, not theoretical (comment at minimum_dimensioning.py:149-154).
- Change `_room_size_caps` to a per-axis cap and the rotation pass breaks: the span cap is deliberately `max(max_w, max_h)` at api.py:671 because the rotation pass may have swapped axes (handlers.py:2004-2006).
- `caps_broken` is set at api.py:847 **before** `repair_dimensions` runs at api.py:856, so a batch can carry the breach warning while the final measurements are inside their ceilings.
- Reword either warning string (handlers.py:2203, api.py:873-874) and the substring checks at test_max_dimensions.py:41,43 break.

**Tests to run**

`python test_max_dimensions.py`, run as a script from the engine repo root. It pins reporting of ceiling breaches, not enforcement. **Measured observation, dossier verification pass, not re-run for this document:** the suite reported a green pass while 16 rooms exceeded their ceilings. That number is a run result printed by the script, not a value in source, and no assertion holds it; expect it to move. What each of its checks proves, and what nothing pins (the `SOLVER_UB_SLACK` widening, the `DEFAULT_UB_FACTOR` fallback, the `repair_dimensions` band), is in [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin). Rungs 4 and 5 of the ladder are api.py code and have their own recipe, [4.8](#48-change-apipy-post-processing-gapless-fill-size-caps-dimension-repair).

### 4.2 Change plot-dimension fitting or the expand fallback

Owned by [concept trace](dim/dim-09-concept-trace.md) (SOUND) and [InputGraph multi-dual](graph/inputgraph-multidual-doors.md) (SOUND), with [door-connectivity handler](dim/dim-07-door-connectivity-handler.md) (MINOR_ERRORS, re-verify anchors) for the fallback loop.

**Files in reading order**

1. handlers.py:1810-1813 (mirror handlers.py:2262-2265): `input_dims` is built, then blanked when both plot dims are 0.
2. minimum_dimensioning.py:229-231 and :311-313: the plot cap as a single negative sink-to-source arc, installed only when the value is `> 0`.
3. handlers.py:2069-2079 (warning) and handlers.py:2120-2121 (`solve_min_dim(floorplan_data, 0, 0, ...)`), duplicated at handlers.py:2505-2516 and :2567-2568.
4. [inputgraph.py](../../GPLAN/source/inputgraph.py) `scale_plot_dimension` at inputgraph.py:597, clamp at :616-619, growth ranking at :624-626, in-place reorder at :642-646.
5. handlers.py:2173 (call) and handlers.py:2176 (`if i in valid`), mirrored at :2619 and :2622.

**Invariants**

- `0` means "no cap" everywhere on this path: minimum_dimensioning.py:229 and :311 gate on `> 0`, which is exactly what makes the fallback's `0, 0` work.
- `input_dims` is emptied only when **both** dims are 0 (handlers.py:1812). One axis at 0 still runs the boundary pre-selector.
- Scaling is expand-only: `scale_h = max(1.0, scale_h)`, `scale_w = max(1.0, scale_w)` at inputgraph.py:618-619.
- `valid` must be contiguous from 0, because `scale_plot_dimension` reorders `graph_list` in place (inputgraph.py:642-646) while the caller filters by pre-reorder index (handlers.py:2176). Contiguity holds only because rejects are popped at handlers.py:2166-2168.

**What breaks silently**

- Treat 0 as a real cap at minimum_dimensioning.py:229 and the fallback at handlers.py:2120-2121 can never succeed.
- Stop popping rejected candidates and handlers.py:2176 emits the wrong plans with correct-looking geometry.
- Reword the fallback string at handlers.py:2074-2075: clients detect expansion by the keyword `expanded` in the accumulated message.

**Tests to run**

None pin this. test_max_dimensions.py:101 sends `plot_width: 0, plot_height: 0`, so the whole plot path is out of scope there. test_api_cardinal_constraints.py:181-182 (30x20) and :214 (54x40) supply plots and assert nothing about extents; those runs emitted the "plot was expanded to fit" string with no assertion reacting. The only plot-fit assertion anywhere in the repository is test_multi_ptpg.py:216-218, on a different endpoint. See [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin).

### 4.3 Change the LP core itself

Owned by [floorplan_to_st](dim/dim-03-floorplan-to-st.md) (MINOR_ERRORS), [convert_adj_equ_sym](dim/dim-04-convert-adj-equ.md) (MINOR_ERRORS) and [solve_linear](dim/dim-05-solve-linear.md) (SOUND); the separate longest-path solver is [solver driver](dim/dim-06-min-dimensioning-driver.md) (UNRELIABLE, verify anything you take from it).

Read this first: **there are two solvers and they never call each other.** `minDimEnabled` reaches `min_dim.main` (minimum_dimensioning.py:767) via `solve_min_dim`; `dimensioned` reaches the scipy LP via `InputGraph.single_floorplan` / `multiple_floorplan`. The fork is at api.py:1226-1229. If you are fixing oversized rooms on the door-connectivity endpoint, the LP files are not the lever.

**Files in reading order**

1. api.py:1226-1229: which `DimParameters` overload is built, and therefore which solver runs.
2. inputgraph.py:817 (`block_checker`) and inputgraph.py:821 (`floorplan_to_st`), mirrored at :1164 and :1167. These are the LP chain's only entry.
3. [floorplan_to_st.py](../../GPLAN/source/dimensioning/floorplan_to_st.py):18, which builds two st-graphs and returns `[width, height, hor_dgph, status]` at :114.
4. [convert_adj_equ_sym.py](../../GPLAN/source/dimensioning/convert_adj_equ_sym.py):15, called twice at floorplan_to_st.py:103 and :105.
5. [solve_linear.py](../../GPLAN/source/dimensioning/solve_linear.py):16, two `linprog` calls at solve_linear.py:76 and :140, invoked once at floorplan_to_st.py:108.
6. For the other chain: minimum_dimensioning.py:225 and :307 (constraint-graph builders), :388 / :466 (longest path), :547 (`compute_placement`), :767 (`main`).

**Invariants**

- One LP variable per st-graph edge, not per room; a room's dimension is its in-edge sum (`W = -1 * A_VER @ X1`, solve_linear.py:80). Row order of `b_ub` (`hstack(-mins, maxes)`, solve_linear.py:56-62) must match the `A_min`/`A_max` stacking at convert_adj_equ_sym.py:80.
- The plot sentinel differs between the two chains: `-1` means unconstrained in the LP (convert_adj_equ_sym.py:117); `> 0` gates the cap in min-dim (minimum_dimensioning.py:229). A caller sending `0` to the LP pins the plot to zero.
- `construct_constraintgraphX` must run before `construct_constraintgraphY` (minimum_dimensioning.py:828-829): the X builder writes cross-axis overlap edges into `edgesY` at :277-285 and :295-303.
- `minimum_dimensioning` is module-global state; `main` calls `reinitialize()` first (minimum_dimensioning.py:769, definition at :729). Not reentrant, not thread safe.

**What breaks silently**

- An infeasible LP does not raise. `method='interior-point'` returns `success=False` with a plausible-looking `x`; `W`/`H` are still computed at solve_linear.py:80 and returned. The caller discards them at inputgraph.py:827-828 and the candidate vanishes with no message.
- One room with `min_height_mod > max_height_mod` drops aspect ratios for **every** room (solve_linear.py:108-121), and the only signal is a `print` that api.py suppresses.
- `block_checker("")` returns `[True, [], []]`, so block_checker.py:4 is on the hot path of every dimensioned plan, not just symmetric ones.
- Tuning `GPLAN_SOLVER_UB_SLACK` (minimum_dimensioning.py:155) does nothing to the LP path.

**Tests to run**

None. The LP chain runs only under `dimensioned` without `minDimEnabled` (the fork at api.py:1226-1229), and no script in the repository sends that combination. `test_max_dimensions.py:110` sends `minDimEnabled: True` and `test_api_cardinal_constraints.py:52` sends `minDimEnabled=True`, so both take the min-dim solver; `test_multi_ptpg.py` sends no dimensioning flags at all (a grep for `minDimEnabled` across the three files matches only `test_max_dimensions.py:110` and `test_api_cardinal_constraints.py:52`, `:167`, `:222`) and drives a different entry point, `Documents.get_multi_ptpg_floorplans`. The conclusion stands: `solve_linear`, `convert_adj_equ_sym` and `block_checker` have no coverage in this repository, and any change there is unguarded. (An earlier draft said all three scripts send `minDimEnabled` and cited `test_api_cardinal_constraints.py:42-48`; both were wrong.)

### 4.4 Change the boundary pool, dim_on_paths_bdy, or fix the batch collapse

Owned by [InputGraph multi-dual](graph/inputgraph-multidual-doors.md) (SOUND) and [concept trace](dim/dim-09-concept-trace.md) (SOUND), with the collapse analysis in [door-connectivity handler](dim/dim-07-door-connectivity-handler.md) (MINOR_ERRORS, check its anchors before quoting it). **The deep reference for `path_map.py` itself is [the source/ circulation package](graph/circulation-source-package.md)** (MINOR_ERRORS): despite the directory-derived name, that dossier owns `path_map.py` and is the only line-by-line account of `dim_on_paths_bdy` at path_map.py:99 and of `paths_after_select_bdy` at path_map.py:48. Read it before changing the pool construction. The full collapse narrative, including why the expand fallback cannot rescue it, is the canonical entry in [section 6](#6-known-defects-and-traps).

**Files in reading order**

1. handlers.py:1810-1813: `input_dims` is the only channel into the selector.
2. inputgraph.py:959-966 (cardinal skip, `selected_list = cip_list`), the `elif (len(input_dims) > 0)` guard at inputgraph.py:967, and the call at inputgraph.py:972-973. Mirrored at :1045-1051, :1052 and :1057-1058.
3. [path_map.py](../../GPLAN/source/path_map.py) `dim_on_paths_bdy` at path_map.py:99: pool construction at :102-135, the filtering step at :115-122, the acceptance gate at :163-164, the three-rung ladder at :203-216.
4. inputgraph.py:978-979 and :1064-1065: the silent revert to the full candidate list when the selector returns nothing.
5. inputgraph.py:862-866 (per-boundary cap lifted under cardinal pins) with the constants at inputgraph.py:139-141.

**Invariants**

- The selector runs only when no cardinal pins are set and `input_dims` is non-empty (inputgraph.py:959, :967).
- The pool is derived only from `bdy_edges` (path_map.py:102-109) and is built once, before the retry ladder. Rooms outside it contribute 0, not an error (path_map.py:146-147).
- The pointer gate is hardcoded to `0.2` at path_map.py:163-164, while the ladder parameterises only `threshold_ratio` (path_map.py:204-214). Rungs 2 and 3 cannot reopen the gate that rejected everything.
- The per-boundary cap is read at handlers.py:1862, :2095, :2287 and :2532, and is raised from 20 to 500 under cardinal pins at inputgraph.py:866.

**What breaks silently**

- A **total** collapse is caught by inputgraph.py:978-979 and reverts to the full `cip_list`. A **partial** collapse is not: `selected_list` is non-empty but was scored against wrong totals, and the good boundaries are gone.
- The expand fallback iterates the already-built `graph_list_by_bdy` at handlers.py:2092 and never regenerates boundaries, so it removes the solver cap but not the pre-selection. That is the mechanism behind the batch collapse ([section 6](#6-known-defects-and-traps)). The specific 2 / 14 / 30 plan counts for 2, 3 and 4 BHK are a **measured observation recorded in project memory on 2026-07-24**, not something in source and not pinned by any test; the mechanism is anchored, the numbers are evidence. Of the three, only 30 has a source explanation: it is the truncation ceiling `FLOORPLAN_LIMIT = 30` at api.py:119, applied at api.py:1418 and api.py:1427, not a generation count.
- Remove the cardinal skip at inputgraph.py:959-966 and the N/E/S/W path assignment is scrambled, because `paths_after_select_bdy` (path_map.py:48) rebuilds the four paths at arbitrary slots.

**Tests to run**

None. No test asserts anything about which boundaries survive selection, or about plot containment on this path (see [4.2](#42-change-plot-dimension-fitting-or-the-expand-fallback)). test_api_cardinal_constraints.py exercises the skip branch, but its assertions are directional only.

### 4.5 Change multi-PTPG exact sizing or strictness

Owned by [multi-PTPG enumeration](graph/multi-ptpg-enumeration.md) (MINOR_ERRORS, re-verify anchors) and [concept trace](dim/dim-09-concept-trace.md) (SOUND), with the contract itself in [tests and contracts](dim/dim-15-tests-and-contracts.md) (SOUND).

**Files in reading order**

1. [multi_ptpg_pipeline.py](../../GPLAN/source/multi_ptpg_pipeline.py) `_room_dimensions` at multi_ptpg_pipeline.py:77-115.
2. multi_ptpg_pipeline.py:174-181: strictness parsing and validation, plot dims read as `-1`-defaulted knobs.
3. multi_ptpg_pipeline.py:307-313: the placer call.
4. [ptpg_floorplanner.py](../../GPLAN/source/ptpg_floorplanner.py):816 `STRICTNESS_LEVELS`, :819 `generate_floorplans`, :954-960 the ladder.

**Invariants**

- Sizes are exact, never minimums: a node missing `width` or `height` raises at multi_ptpg_pipeline.py:90-94, and both are coerced with `int(round(float(...)))` at :95-96, rejected if non-positive at :97-100.
- Engine-invented rooms get `added_room_width`/`added_room_height` or the smallest client room. Those two request keys are read at multi_ptpg_pipeline.py:201 and passed positionally into `_room_dimensions`, whose parameters are named `dummy_width`/`dummy_height` (multi_ptpg_pipeline.py:77); the fallback itself is multi_ptpg_pipeline.py:105-113, where `fallback_w`/`fallback_h` default to `min(widths.values())` and `min(heights.values())` when the keys are absent (multi_ptpg_pipeline.py:107-108) and every synthetic room is floored at 1 (multi_ptpg_pipeline.py:110-111). Grep for the literal key names finds only multi_ptpg_pipeline.py:201.
- The ladder is: exact pass always (`run_pass(is_relaxed=False)`, ptpg_floorplanner.py:954), relaxed only if empty (:956-957), `require_all=False` only for `best_effort` (:959-960). Unknown levels are rejected twice, at multi_ptpg_pipeline.py:176-177 and ptpg_floorplanner.py:840-841.
- Nothing in the compactor can resize a room; that is the mechanism the exact-size contract rests on ([tests and contracts](dim/dim-15-tests-and-contracts.md)). Re-checked for this document: `compact_and_resolve_overlaps` (ptpg_floorplanner.py:456) copies each rect into a mutable list at ptpg_floorplanner.py:459 and every write inside the function targets index 0 or index 1 only (the x and y slots), at ptpg_floorplanner.py:467-468, :509-516, :551-552 and :564-575; the write-back at ptpg_floorplanner.py:580-581 carries indices 2 and 3 through unchanged. Width and height are never assigned after `_room_dimensions` sets them.

**What breaks silently**

- Teach the compactor to shrink a room to fit a plot and only test_multi_ptpg.py:94 will notice.
- Sub-unit inputs collapse: `0.4` rounds to `0` at multi_ptpg_pipeline.py:95-96 and then raises the "non-positive dimension" error, which reads as a validation bug rather than a rounding one.
- `keep_best` (ptpg_floorplanner.py:948-952) is applied to the relaxed pass too (:957), narrowing a `relaxed` result set in a way the documented table does not describe.
- This path shares nothing with the door-connectivity chain: no `irreg_multiple_dual`, no `min_dim.main`, no `rectangularize_output`.

**Tests to run**

`python test_multi_ptpg.py`, as a script, never under pytest. It carries the only exact-size assertion in the repository and the only plot-fit assertion; the full breakdown, including its two known holes (integer-only inputs, engine-added rooms skipped), is in [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin).

### 4.6 Change space-optimization or GA sizing

Owned by [negNew sizing core](dim/dim-10-negnew-sizing-core.md) (SOUND), [GA sizing core](dim/dim-13-ga-sizing-core.md) (SOUND) and [GA corridors C layer](dim/dim-14-ga-corridors-c.md) (MINOR_ERRORS), with [flag plumbing](dim/dim-01-flag-plumbing.md) for why these share no parsing with the rest.

**Files in reading order**

1. handlers.py:2659 `handle_space_optimization`: the `sys.path` insert at handlers.py:2685-2687 and the `negNew` import at handlers.py:2689, room construction at handlers.py:2713-2718, the run at handlers.py:2751-2755.
2. [negNew.py](../../Space_Optimization/negNew.py) `generate_layout` at negNew.py:1675, the placement loop `place_rooms_with_constraints_optimized` at :1036, `expand_rooms_optimized` at :1172, `_total_expansion_used` at :347, `Room.rotate` at :34.
3. handlers.py:2845 `handle_ga_optimization`: the `sys.path` insert at handlers.py:2863-2865 and the `ga_current` import at handlers.py:2868 (both import anchors verified against source during assembly).
4. [ga_current.py](../../Space_Optimization/ga_current.py) `WEIGHTS` at ga_current.py:116, `apply_chromosome` at :651, `calculate_fitness` at :1026, `run_ga` at :1210, the three `ctypes.CDLL` loads at :83, :87, :91.
5. The C sources behind those loads, per [GA corridors C layer](dim/dim-14-ga-corridors-c.md).

**Invariants**

- Neither engine has a minimum or maximum dimension concept. negNew treats the caller's `width`/`height` as an exact starting size; the only ceiling is `max_expansion`, a budget on the summed width and height deltas in grid units (negNew.py:347-359), defaulted to 20 at handlers.py:2717 against negNew's own default of 3 (negNew.py:644).
- The GA chromosome is one `(dr, dc)` integer displacement per room; `apply_chromosome` (ga_current.py:651) only translates. No gene encodes size, and no fitness weight references dimensions (ga_current.py:116-125).
- Gene order is `sorted(room_ids)`, assumed independently at ga_current.py:1226, ga_current.py:654 and in the handler's own index map.
- The three shared libraries are loaded at import time (ga_current.py:83, :87, :91), so a missing `.so`/`.dll` fails the handler import at handlers.py:2868.

**What breaks silently**

- `handle_ga_optimization` writes `ga_current` module globals with no reset: `ga_current.POPULATION_SIZE` at handlers.py:2875, `ga_current.NUM_GENERATIONS` at handlers.py:2877 and `ga_current.INITIAL_MUTATION_RATE` at handlers.py:2879, each guarded only by the presence of the corresponding `ga_config` key, plus `ga_current.TOURNAMENT_SIZE` recomputed unconditionally from the (possibly leaked) population size at handlers.py:2885. Nothing restores the module defaults, so one request's config leaks into every later request that omits `ga_config`, in the same worker process. The values are echoed at handlers.py:2889-2892, which is the only way to notice.
- The handler rebuilds its own layout matrix at handlers.py:2956-2970 before recarving corridors at handlers.py:2973, using a different placement routine from the fitness function's. The corridors the client receives are not provably the corridors the GA scored.
- Reorder anything in `calculate_fitness` so a C wrapper runs before the `corridor_creator` call at ga_current.py:1086 and C reads an int64 buffer as int32: no crash, just wrong counts.
- These paths share no code, no constant and no default with the LP or min-dim chains. There is no 99999 sentinel here, no `plot_width` on space-optimization at all, and a `plot_width` default of 40 on the GA path.

**Tests to run**

None exist. No test file in the repository invokes `handle_space_optimization` or `handle_ga_optimization` ([section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)). Any change here is verified by running the endpoint, not by a suite.

### 4.7 Change the response payload, the `ui` object, or the serialization shape

**No dossier owns this as a unit.** [Entry-point wiring](graph/entrypoint-wiring.md) (SOUND) covers the call sites, [flag plumbing](dim/dim-01-flag-plumbing.md) (MINOR_ERRORS) covers `DimParameters`, and [negNew IO boundary](dim/dim-11-negnew-io-boundary.md) (UNRELIABLE) covers the space-optimization response only. The reading order below was assembled for this document.

This is the recipe behind [invariant G4](#5-global-invariants). Handlers return nothing useful; they push results onto a `ui` object, and `api.py` reads five attributes off each plan. Adding a per-room or per-plan field means touching every one of the following.

**Files in reading order**

1. [GuiParameters.py](../../GPLAN/pythongui/GuiParameters.py) `class GuiParameters` at GuiParameters.py:105. This is the class behind every `ui` parameter in `handlers.py`. Its constructor is GuiParameters.py:345 and it is the **only** place the API constructs one, at api.py:1230, in the fluent chain `GuiParameters(graph=graph).set_isDimensioned(...)...set_isCirculation(...)`.
2. The output channel, four methods: `_append_output_data` (GuiParameters.py:389), which appends a plan object and then derives `area` via the nested `find_areas` (GuiParameters.py:398-404, invoked at :410-411) and `name_coords` (GuiParameters.py:420-423); `_set_output_data` (GuiParameters.py:426), which replaces the whole batch and is what the gapless pass and the cardinal filter use; `get_output_data` (GuiParameters.py:384); and `print_gui` (GuiParameters.py:379), the message channel, which appends through `set_message` (GuiParameters.py:324) and is read back by `get_message` (GuiParameters.py:329) at every `api.py` message assembly point. Every one of them forks on `gclass is not None` and writes to the Tk object instead when a GUI is attached ([invariant G8](#5-global-invariants)).
3. The one side channel that is not a plan attribute: `set_ptpg_graph` (GuiParameters.py:137), written from `handlers.py:1745` and read back at api.py:1423, attached to the response at api.py:1425 for `door_connectivity` only (guard at api.py:1422).
4. **The serialization contract, api.py:1427-1452.** The loop at api.py:1427 runs `min(min(len(outputData), limit), count)` times (bound computed at api.py:1418), and per plan reads exactly five attributes: `final_traversal` (api.py:1429), `name_coords` (api.py:1430), `area` (api.py:1431), `room_width` (api.py:1432) and `room_height` (api.py:1433). Anything not on that list does not reach the client. Walls are built from consecutive traversal points and the `Room` object is constructed at api.py:1448-1449, carrying `circular_coordinates`, `name_coord`, `area`, `width` and `height`. `builtins.print` is restored at api.py:1454 and the response returned at api.py:1456.
5. The second, independent serializer: `stacked_oneconnected_floorplans` (api.py:939) with `_stacked_room_dict` (api.py:878) builds room dicts itself and returns at api.py:1350 before the loop above ever runs ([recipe 3.7](#37-change-the-one-connected-path-or-the-stacked-multiple-door-composition)). A field added only at api.py:1448 is missing from every stacked response.
6. The transport mapping, in the sibling backend repo: `gplan_backend/gplan_apis/tasks.py:127` calls the engine, `tasks.py:142` wraps the return as `{"message": ..., "response": floorplans.to_dict()}`, and `tasks.py:130-140` is the error-to-payload mapping that turns an `IndexError` into a dict with `error`, `details`, `caller`, `nodes` and `edges` keys instead of a floorplan. The request side is `views.py:803` (`GenerateFloorplanView.post`), which assembles `prepared_data` at `views.py:910-933`; a request field that is not a key there never reaches `Documents.get_floorplans`. Prefix these with `../../../` to open them from `documentation/algorithms/`.

**Invariants**

- Results travel by mutation, not by return value. `handle_*` return values are discarded at nearly every `api.py` call site; the two exceptions are `handle_space_optimization` (api.py:1566) and `handle_ga_optimization` (api.py:1701) ([invariant G4](#5-global-invariants)).
- `final_traversal` is the geometry currency and is not idempotent ([invariant G13](#5-global-invariants)): api.py:859-862 rewrites it wholesale, and `get_final_traversal` appends without clearing (inputgraph.py:1588, :1622). Note the mixed element types, lists from api.py:859 and tuples from inputgraph.py:1574-1577; a serializer that indexes them must accept both.
- The five per-plan attributes must all have the same length as the room count, and `name_coords` is indexed with the same `k` as `nodes_list` (api.py:1448). A field of a different length silently truncates or raises inside the loop.
- Every `GuiParameters` accessor forks on `gclass`. A new setter that forgets the fork works over HTTP and silently drops data in the desktop tool.

**What breaks silently**

- Adding a value that a handler only returns, never pushes onto `ui`, discards it with no error ([invariant G4](#5-global-invariants)).
- Adding a field at api.py:1448 without adding it to `_stacked_room_dict` (api.py:878) gives a response whose shape depends on whether the input had a cut vertex.
- The backend never validates the engine's response shape; `tasks.py:142` serializes whatever `to_dict()` returns, so a shape change surfaces at the client, not in the worker.

**Tests to run**

None. All three scripts call the engine in-process and read `to_dict()["Documents"]["floorPlans"]` directly, so they exercise the api.py serializer but assert nothing about its shape, and they pin **zero** of the Django, Celery and DRF layer ([section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)). After a response-shape change, run the backend separately from `GPLAN_Revamp/gplan_backend` and exercise the real route; the engine-side smoke test is the Flask bridge ([section 8, Running the Flask bridge](#running-the-flask-bridge)).

### 4.8 Change api.py post-processing: gapless fill, size caps, dimension repair

**No dossier owns this code.** [Entry-point wiring](graph/entrypoint-wiring.md) explicitly scopes itself to imports, handler definitions and call sites, and says nothing about the algorithms inside; [concept trace](dim/dim-09-concept-trace.md) names these functions as ladder rungs but does not walk them. The reading order and anchors below were assembled for this document, and this is the thinnest coverage in the whole reference: treat the source as the only authority here.

This is the last code that touches client geometry. It runs after the solver, after rotation, and after the candidate batch is chosen, and it can move every wall in every plan.

**Files in reading order**

1. [api.py](../../GPLAN/api.py) `rectangularize_output` at api.py:801. The whole gapless pass. Called twice on the multiple-door path, at api.py:1358 and again per retry attempt at api.py:1392, and its return value is the gated batch.
2. `_room_size_caps` at api.py:640: builds the per-room ceiling used by the fill, deliberately as a single span cap `max(max_w, max_h)` at api.py:671 because the rotation pass may already have swapped axes (handlers.py:2004-2006).
3. `_fill_gaps` at api.py:710, called twice from inside `rectangularize_output`: first with the caps enforced (api.py:834-836), then, only if the plan is still not gapless, with `enforce=False` (api.py:840). A gapless rectangle is required; honouring every ceiling is preferred, and that trade is the reason for the second call.
4. The breach warning: `caps_broken` is initialised at api.py:811 and set at api.py:847 when the uncapped pass exceeded a cap, then reported once for the whole batch at api.py:872-874 through `ui.print_gui`. `test_max_dimensions.py:41` and `:43` match on those strings.
5. `repair_dimensions` at api.py:621, gated by the environment flag `REPAIR_DIMENSIONS` at api.py:618 (`GPLAN_REPAIR_DIMS`, default on) and checked again at api.py:628. It is called at api.py:856 with `_room_bounds(ui, len(rects))`, re-solves the coordinate lines against the full band, and is accepted only if the result is still non-overlapping and gapless (api.py:857-858).
6. The write-back, api.py:859-865: `final_traversal` is replaced with four-corner lists (api.py:859-862), then `room_width` (:863), `room_height` (:864) and `area` (:865) are recomputed from the rectangles, and `name_coords` is re-centred at api.py:866-869. This is the wholesale rewrite named in [invariant G13](#5-global-invariants).

**Invariants**

- Order is load-bearing: capped fill, then uncapped fill, then repair. `caps_broken` is decided at api.py:847, **before** `repair_dimensions` runs at api.py:856, so a batch can carry the breach warning while the final measurements are back inside their ceilings.
- A plan that cannot be made gapless is dropped, not fixed: the `continue` at api.py:848-849 skips it, surviving plans are collected at api.py:870, and the batch is replaced wholesale by `ui._set_output_data(kept)` at api.py:871. The empty-batch rescue lives in the caller, at api.py:1360-1364.
- `repair_dimensions` moves shared walls only, which is what preserves the arrangement, the gaplessness and every adjacency. A repair that moved a room would invalidate the dual.
- The pass writes lists where `inputgraph.get_final_traversal` writes tuples (inputgraph.py:1574-1577). Consumers must accept both.

**What breaks silently**

- Changing `_room_size_caps` to a per-axis cap breaks the rotation pass, because the axes may already be swapped (api.py:671 against handlers.py:2004-2006).
- Rewording the warning at api.py:873-874 breaks the substring checks at `test_max_dimensions.py:41` and `:43` without failing anything loudly.
- Setting `GPLAN_REPAIR_DIMS=0` silently removes rung 5 of the max-dimension ladder; nothing reports that the flag is off.
- Because this pass runs after the solver, a room can end up outside the band the solver honoured, and the only signal is the batch-level warning string.

**Tests to run**

`python test_max_dimensions.py`, which reaches this code through the door-connectivity path but pins only the warning strings and the per-room minimum (`:208-217`). Nothing pins the gapless property itself, the repair band, or the `REPAIR_DIMENSIONS` gate. See [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin).

---

## 5. Global invariants

These hold across module boundaries. Each one is a place where an edit in one file changes behaviour in another file that never imports it. Single-module rules stay in the dossiers. Recipes reference these by number (G1 through G14).

**G1. `InputGraph`'s attribute names are a public contract, read by attribute access rather than through methods.** The attributes are declared in `__init__` ([inputgraph.py:115-156](../../GPLAN/source/inputgraph.py)). Consumers reach in directly: `api.py` reads `plan.name_coords` (api.py:1430) and writes `graph.cardinal_constraints` (api.py:1305, api.py:1386); `handlers.py` reads `graph.graph_list_by_bdy` (handlers.py:1859), `graph.floorplan_per_bdy_limit` (handlers.py:1862), `graph.dummy_node_adjacencies` (handlers.py:821). Because every access is an attribute lookup, a rename fails at runtime in the consumer, not at import. See [InputGraph single-dual core](graph/inputgraph-single-dual-core.md).

**G2. `room_x` / `room_y` / `room_width` / `room_height` change shape depending on which generator last ran.** They are flat arrays after `irreg_single_dual` (inputgraph.py:313-315), lists of arrays after `irreg_multiple_dual` or `oneconnected_dual("multiple")` (inputgraph.py:1342-1358), and collapsed back to the winning candidate by `single_floorplan` (inputgraph.py:835, which also collapses `extranodes`/`mergednodes`/`irreg_nodes1`). Two consequences: `single_floorplan` cannot follow `irreg_single_dual`, which leaves flat arrays and an empty `rel_matrix_list`; and calling it twice without re-running `irreg_multiple_dual` indexes an already-collapsed list. The retry loop only works because handlers.py:930 regenerates before the second call at handlers.py:931. See [InputGraph single-dual core](graph/inputgraph-single-dual-core.md) and [InputGraph dimensioning hooks](dim/dim-02-inputgraph-hooks.md).

**G3. 4-completion assumes exactly four boundary paths, and the REL label sentinels are load-bearing for corner detection.** `news.add_news` is called with `bdys` at inputgraph.py:299-300; the shortcut-destruction loop at inputgraph.py:283-292 exists only to force the CIP count down so that assumption holds. Downstream, `oneconnected_dual` finds the four corner rooms by reading the literal REL values `3` and `2` out of each matrix (inputgraph.py:1269-1276). Changing how `news.add_news` numbers the exterior vertices, or how expansion colours edges, makes every one-connected input raise `OCError` at inputgraph.py:1323. See [boundary NEWS and CIP](graph/boundary-news-cip.md).

**G4. `handle_*` functions communicate results only by mutating the `ui` object; their return values are ignored at nearly every `api.py` call site.** The exceptions are `handle_space_optimization` (api.py:1566) and `handle_ga_optimization` (api.py:1701). Results come back via `ui.get_output_data()` (api.py:1413), and the serialization contract is exactly `final_traversal`, `name_coords`, `area`, `room_width`, `room_height` (api.py:1429-1433). Adding a result that is only returned, never pushed onto `ui`, is silently discarded. See [entrypoint wiring](graph/entrypoint-wiring.md).

**G5. `OCError` and `BCNError` are control flow, not errors.** Both are defined in inputgraph.py (:47 and :55) and always caught inside `handlers.py`, then downgraded to the irregular dual (for example handlers.py:1757 and handlers.py:1760 falling back to `irreg_single_dual` at :1761). They never propagate to `api.py` and never become a non-200 response. Code that lets one escape converts a routine fallback into a task failure. See [entrypoint wiring](graph/entrypoint-wiring.md).

**G6. 99999 is the universal "open maximum" sentinel, and an open bound is not an absent bound.** `get_max_dims` treats a list as carrying a ceiling only if some entry satisfies `0 < float(value) < 99999` (handlers.py:329). The solver applies the same test at [minimum_dimensioning.py:175](../../GPLAN/source/dimensioning/minimum_dimensioning.py) and substitutes `DEFAULT_UB_FACTOR * low` (minimum_dimensioning.py:148, :168). A supplied ceiling becomes `min(5*low, max(supplied, 2.5*low))` (minimum_dimensioning.py:155, :177), so ceilings below 2.5x the minimum are widened and ceilings above 5x are narrowed. Changing the literal requires changing every sentinel test together. See [concept trace](dim/dim-09-concept-trace.md).

**G7. `matrix`, `nodecnt` and `edgecnt` are mutated in place by every augmentation stage, so any pre-augmentation copy goes stale.** Biconnectivity edges are written at inputgraph.py:221-224, triangulation edges at inputgraph.py:231-234, and both counts are recomputed from the matrix after separating-triangle removal at inputgraph.py:260-261. The same object is what `api.py` attaches to the response as `ptpg_graph` (api.py:1425) after handlers publishes it. Holding a snapshot taken before `door_connectivity` and comparing it afterwards is exactly how `extraedges` is derived; holding one and *using* it as the graph is a bug. See [InputGraph single-dual core](graph/inputgraph-single-dual-core.md) and [multi-dual and doors](graph/inputgraph-multidual-doors.md).

**G8. `gclass is None` is the API-versus-GUI discriminator inside handlers.** Every min-dim handler branches on it: handlers.py:1788 (GUI, Tk dialogs supply dimensions) versus handlers.py:1806 (API, dimensions unpacked from `ui.min_dim_inputs`). Any code that dereferences `gclass` without that guard is GUI-only or a latent API crash, `handle_circulation`'s first branch being the live example ([section 6](#6-known-defects-and-traps)). See [entrypoint wiring](graph/entrypoint-wiring.md).

**G9. `len(node_coordinates)` must equal `nodecnt`, and the embedding must stay index-aligned with matrix rows.** `__init__` splits the coordinates into x and y lists and calls `gc.check_intersection(x_coord, y_coord, self.matrix)` at inputgraph.py:159-161, replacing them with a planar layout when the drawing self-intersects (inputgraph.py:162-164). Triangulation then consumes `self.coordinates` as the planar embedding (inputgraph.py:228-230). A mismatched length indexes past the end; a mis-ordered list produces a valid-looking but wrong triangulation. See [InputGraph single-dual core](graph/inputgraph-single-dual-core.md).

**G10. Cardinal constraints affect only the multiple-dual path.** `filter_boundaries_by_cardinal` (inputgraph.py:1365) is called only from inside `irreg_multiple_dual` (inputgraph.py:951, :1037), and the per-boundary cap lift lives there too (inputgraph.py:862-866). A single-dual run ignores `cardinal_constraints` entirely, which is why handlers.py:1821-1830 forces `irreg_multiple_dual` and skips `oneconnected_dual` when pins are present. See [InputGraph single-dual core](graph/inputgraph-single-dual-core.md).

**G11. The NEWS vertices occupy the last four indices in N, E, S, W order, and label 2 means South-to-North while label 3 means West-to-East.** The layout is produced by [news.py:265-268](../../GPLAN/source/boundary/news.py) and assumed arithmetically by [expansion.py:39-49](../../GPLAN/source/floorplangen/expansion.py), [contraction.py:47](../../GPLAN/source/floorplangen/contraction.py), `dual.py`, `rdg.py`, `operations.order_nbrs`, and `api.py:123` (`CARDINAL_DIR_INDEX`). Nothing is symbolic: the convention lives as `nodecnt - 4` arithmetic in seven files. See [boundary NEWS and CIP](graph/boundary-news-cip.md) and [REL contraction and expansion](graph/rel-contraction-expansion.md).

**G12. A boundary candidate is exactly four paths in N, E, S, W order, with consecutive paths sharing their corner node.** Produced by `generate_multiple_bdy` (inputgraph.py:1483), preserved under rotation and reflection by `filter_boundaries_by_cardinal` (inputgraph.py:1400-1403), and depended on by `news.add_news` (inputgraph.py:1424), by `_ring_order_satisfies` (api.py:153-161), and by `plan_satisfies_cardinal`'s dir_idx mapping (api.py:401-408). Change the order and the cardinal feature silently mislabels directions rather than failing. See [multi-dual and doors](graph/inputgraph-multidual-doors.md).

**G13. `final_traversal` is the geometry currency between the engine and every consumer, and `get_final_traversal` is not idempotent.** It is read by api.py:1429 to build walls and `circular_coordinates`, by api.py:382 for the cardinal check, rewritten wholesale by api.py:859-862, and rescaled by `scale_plot_dimension` (inputgraph.py:605, :630-633). `get_final_traversal` appends without clearing (inputgraph.py:1588, :1622), so handlers resets both traversal lists on cloned plans (handlers.py:1974-1975). Note api.py:859 writes lists while inputgraph.py:1574-1577 writes tuples; consumers must accept both. See [multi-dual and doors](graph/inputgraph-multidual-doors.md).

**G14. The nested `graph_list_by_bdy` and the `(i, j)` with `i >= j` shape of `dummy_node_adjacencies` are both consumed outside the module that builds them.** `store_dummy_node_adjacencies` emits the ordered-pair set (inputgraph.py:1505-1508); it arrives at the min-dim solver as the `dummy_node_adj` payload field (handlers.py:821). `graph_list_by_bdy` is one inner list per boundary (inputgraph.py:1013-1014, :1097-1098), and handlers iterates that nesting to apply `floorplan_per_bdy_limit` (handlers.py:1859-1862). Flattening the list disables the per-boundary cap without any error. See [multi-dual and doors](graph/inputgraph-multidual-doors.md) and [flag plumbing](dim/dim-01-flag-plumbing.md).

---

## 6. Known defects and traps

Everything below was either established in a dossier marked SOUND or re-checked against the source in this repository. Do not treat any of these as a regression you introduced, and do not build on top of one without reading the owning dossier first.

Two entries here are sourced from dossiers marked UNRELIABLE (`LimitsAlgorithm` from dim-08, space-optimization integrity from dim-11). Both are tagged **[re-checked against source]** inline, which means the specific anchors in that entry were opened and confirmed for this document even though the rest of the owning dossier was not. Any entry without that tag came from a SOUND dossier. The reliability promise in [How to use this document](#how-to-use-this-document) is carried down to entry level this way, and the two defects that could **not** be re-checked are quarantined in [Reported but not re-verified](#reported-but-not-re-verified) at the end of this section.

### Crashes waiting to happen

**`show_warning` opens a Tk dialog on the headless API path.** [`handlers.py`](../../GPLAN/handlers.py)`:3056-3057` calls `messagebox.showinfo`, and it is invoked from inside `except OCError` blocks at `handlers.py:1758` and `handlers.py:1835` (also `:1085`, `:1334`) with no `gclass is not None` guard. On a display-less server this raises `TclError` from inside the exception handler, turning a recoverable fallback to `irreg_single_dual` / `irreg_multiple_dual` into a task failure. Trigger: any `OCError` on the door-connectivity or single-OC path in a container without a display. Owner: [entry-point wiring](graph/entrypoint-wiring.md).

**`handle_circulation` dereferences `gclass` unconditionally.** Its first branch reads `gclass.open` ([`handlers.py`](../../GPLAN/handlers.py)`:504`), `gclass.ptpg` (`:523`), `gclass.output_data` (`:526`) and `gclass.checkvar4` (`:536`); the remove-corridor min-dim branch repeats the same dereference at `handlers.py:661`. `call_circulation_new` additionally reads `gclass.entry_door` at `handlers.py:83` and `gclass.rem` at `handlers.py:104`. The API reaches this function only via `handlers.py:1748`, which forwards `gclass=None` (api.py:1309 supplies it). Trigger: `circulationEnabled=1` over HTTP (with or without `minDimEnabled`), which is an `AttributeError` on `NoneType` before any circulation runs. This is the live instance of [invariant G8](#5-global-invariants). Owners: [entry-point wiring](graph/entrypoint-wiring.md), [circulation root geometry](graph/circulation-root-geometry.md).

**Both circulation min-dim branches unpack five values from a six-value helper.** [`handlers.py`](../../GPLAN/handlers.py)`:512` and `handlers.py:669` write `min_width, min_height, plot_width, plot_height, optimal_floorplan = mindimgui.gui_fnc(...)`, but [`mindimensiongui.py`](../../GPLAN/pythongui/mindimensiongui.py) returns six values on **both** of its branches: `mindimensiongui.py:157` is the GUI return (`min_width, min_height, plot_width.get(), plot_height.get(), optimal_floorplan.get(), allow_rotation.get()`) and `mindimensiongui.py:22` is the API return taken when `gclass == None` (the guard is at `mindimensiongui.py:20`). Trigger: the GUI circulation min-dim path, an unconditional `ValueError` against the return at `:157`. The API path never gets there: it dies earlier on `gclass.open` (`handlers.py:504`). The same helper is unpacked correctly, into six names, by the GUI branch of `handle_door_connectivity` at `handlers.py:1801`; only the two circulation call sites get it wrong. Owner: [circulation root geometry](graph/circulation-root-geometry.md).

**`graph.multiple_dual()` names a method that does not exist.** [`handlers.py`](../../GPLAN/handlers.py)`:1172` calls it inside the GUI dimensioned retry loop; `InputGraph` defines `irreg_single_dual`, `irreg_multiple_dual`, `single_floorplan`, `multiple_floorplan`, `oneconnected_dual` and `door_connectivity`, and nothing named `multiple_dual`. Trigger: the GUI retry loop only, so it is latent, not live. Owner: [entry-point wiring](graph/entrypoint-wiring.md).

**`multiple_floorplan` raises on its first loop iteration.** [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:1160` reads `self.graph_list.rel_matrix_list`, and `graph_list` is a plain Python list. Trigger: any call, meaning the two GUI dimensioned-multiple call sites at `handlers.py:1069` and `handlers.py:1474`. Owner: [inputgraph multi-dual and doors](graph/inputgraph-multidual-doors.md).

**`is_connected` uses recursive DFS.** The inner `dfs` at [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:182-186` recurses once per edge traversal. Trigger: a deep path-shaped graph raises `RecursionError` instead of answering; called from `handlers.py:752`, `:1042`, `:1687`. Owner: [inputgraph single-dual core](graph/inputgraph-single-dual-core.md).

**~~`triangularity_non_adj.triangulate` calls `plt.show()` unconditionally.~~ FIXED in `db740b28`.** [`triangularity_non_adj.py`](../../GPLAN/source/graphoperations/triangularity_non_adj.py)`:456-457`, reached from `door_connectivity` at `inputgraph.py:385` and `:477` whenever a non-adjacency list is present, so every such request built a figure and called `show` on the worker. The sibling [`triangularity.py`](../../GPLAN/source/graphoperations/triangularity.py)`:278` keeps the identical `nx.draw_networkx` call commented out and has no `plt.show()`; this copy was missed when the module was forked. Both lines are now commented to match. Owner: [triangulation core](graph/triangulation-core.md).

**Circulation's `plot` helper also calls `plt.show()`.** [`circulation.py`](../../GPLAN/circulation.py)`:941` defines `plot` and `:956` calls `plt.show()`; `call_circulation_new` invokes it at `handlers.py:103` and `handlers.py:117`. Trigger: the same headless condition as above, on any circulation-enabled request. Owner: [circulation root geometry](graph/circulation-root-geometry.md).

**L-shape shortcut removal calls a three-parameter function with five arguments.** [`Lshaped.py`](../../GPLAN/source/lettershape/lshape/Lshaped.py)`:616-617` calls `sr.remove_shortcut(shortcut[index], graph, graph.rdg_vertices, graph.rdg_vertices2, graph.to_be_merged_vertices)` while [`shortcutresolver.py`](../../GPLAN/source/irregular/shortcutresolver.py)`:34` is `remove_shortcut(shortcut, trngls, matrix)`. `graph.rdg_vertices` is never assigned anywhere, so the `AttributeError` fires first. Trigger: an L-shape whose boundary carries five or more shortcuts after NE insertion (`Lshaped.py:614`). Owner: [L-shaped core](graph/lshaped-core.md).

**~~`DimParameters.get_symmetric()` reads an attribute that is never assigned.~~ FIXED in `cda480bb`.** At commit `a2c0baaf`, [`GuiParameters.py`](../../GPLAN/pythongui/GuiParameters.py)`:22` declared `__symmetric` as a class annotation only and the constructor assigned every other field but not that one, while [`dimensiongui.py`](../../GPLAN/pythongui/dimensiongui.py)`:12` calls the getter unconditionally on the headless path. That made every `dimensioned`-without-`minDimEnabled` API call raise `AttributeError` before the LP chain was entered, across six handlers. The constructor now assigns `self.__symmetric = symmetric if isinstance(symmetric, str) else "()"`. The coercion matters as much as the assignment: `block_checker` splits the value on `,`, and the API layer sends the boolean `False` (`views.py:865`, `local_engine_bridge.py:80`), so storing the raw value would have replaced one crash with another. `"()"` is the no-symmetry sentinel the GUI's Free Dimensions button already used. Owner: [flag plumbing](dim/dim-01-flag-plumbing.md).

**`./saved_files/input_to_limits.json` is a cwd-relative path with no directory creation.** [`handlers.py`](../../GPLAN/handlers.py)`:1114-1116` writes it from `handle_single_oc`, and `handle_limits` reads it back at `handlers.py:1513`. The read is wrapped in a bare `except` at `:1518-1519` that warns but does not return, so execution falls through to `handlers.py:1522` with an empty dict and raises `KeyError: 'nodecnt'` at `handlers.py:1536`. Trigger: running from any working directory where `saved_files/` does not exist. Owners: [entry-point wiring](graph/entrypoint-wiring.md), [polygonal limits](dim/dim-08-polygonal-limits.md).

**~~Stale loop variable in the non-PTPG rotation pass.~~ FIXED in `cda480bb`.** [`handlers.py`](../../GPLAN/handlers.py)`:2426` (now `:2438`) loops on `itr2` but indexed `graph.graph_list[i].matrix[merge_node][j]` with `j` left over from the bound-area loop at `:2375`. A rotated candidate's merged dummy room therefore received either minimum 1 or the maximum over all rooms, instead of the maximum over its own neighbours: silently wrong dimensions rather than a crash, whenever the earlier loop had bound `j`. Now indexes `itr2`, matching the unrotated branch. The sibling copies (`:2315`, `:2558`) were already correct. Owner: [door-connectivity handler](dim/dim-07-door-connectivity-handler.md).

### Silent wrong behavior

**`builtins.print` is left patched process-wide if the pipeline raises.** [`api.py`](../../GPLAN/api.py)`:1217-1222` rebinds `builtins.print` to a no-op and restores it only at `api.py:1454` and, on the stacked early return, `api.py:1349`. There is no `try/finally` (only `get_multi_ptpg_floorplans` uses one). Trigger: any exception between those lines silences `print` for the rest of the worker process. Owner: [entry-point wiring](graph/entrypoint-wiring.md).

**The dimension-fit boundary pool collapses, and every fallback reuses it.** This is the canonical narrative for the mechanism behind [recipe 4.4](#44-change-the-boundary-pool-dim_on_paths_bdy-or-fix-the-batch-collapse). `dim_on_paths_bdy` builds its room pool once from `bdy_edges` at [`path_map.py`](../../GPLAN/source/path_map.py)`:102-135`, filtering `room_w`/`room_h` down to boundary rooms at `:115-122`. Rooms missing from that pool contribute zero rather than an error (`:146-147`), so `total_width` goes to 0, the hard-coded gate `0 <= x <= 0.2 * plot_width` at `:163-164` rejects every path, and all three relaxation rungs at `:203-216` close over the same pool, so rungs 2 and 3 cannot reach the gate that failed. The expand-only fallback then iterates the already-built `graph.graph_list_by_bdy` at [`handlers.py`](../../GPLAN/handlers.py)`:2092-2094` and only drops the solver plot cap at `:2120-2121`; it never regenerates boundaries. Trigger: a request with a plot cap and no cardinal pins (cardinal pins skip the selector at `inputgraph.py:959-966` / `:1045-1051`). Everything above this sentence is anchored source. What follows is not: the 2 / 14 / 30 plan counts for 2, 3 and 4 BHK are a **measured observation**, and the note that a fix design for this collapse was verified on **2026-07-24** comes from the maintainer's project memory, not from any file in this repository or any dossier. No path is given because none exists to give; if you need the fix design, ask the maintainer rather than searching for it. Owners: [door-connectivity handler](dim/dim-07-door-connectivity-handler.md), [min-dimensioning driver](dim/dim-06-min-dimensioning-driver.md).

**`single_floorplan` pads dimension arrays from the first floorplan only.** [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:797-810` appends defaults for `len(self.mergednodes[0])` merged nodes and `len(self.extranodes[0])` extra nodes, then reuses those same padded arrays for every REL in the loop at `:811`. Trigger: any REL after the first with a different merged or extra node count gets wrong-length constraint arrays handed to `floorplan_to_st`. **Open question:** whether that count is constant across RELs is unresolved; the owning dossier lists it under Open Questions. Owner: [inputgraph single-dual core](graph/inputgraph-single-dual-core.md).

**The shortcut-removal loop recomputes CIPs against a stale boundary.** [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:282-296` removes shortcuts and hand-increments `nodecnt` and `edgecnt` (`:290-291`), refreshing `triangular_cycles` at `:293` but rebuilding `bdy_ordered` at `:294` from `self.bdy_nodes` / `self.bdy_edges`, last written at `:270` before any removal. Trigger: a graph with more than four shortcuts, where the boundary provably changed. Owner: [inputgraph single-dual core](graph/inputgraph-single-dual-core.md), Open Questions.

**`oneconnected_dual("multiple")` resets `area` and never refills it.** [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:1346` sets `self.area = []`, and the per-floorplan loop at `:1352-1362` appends to `room_x`, `mergednodes`, `extranodes` and `irreg_nodes1/2` but never to `area`. Trigger: every one-connected multiple run; downstream consumers see an empty area list. Owner: [inputgraph single-dual core](graph/inputgraph-single-dual-core.md).

**Infeasible candidates and non-PTPG graphs vanish without a message.** A candidate that fails the longest-path solve is popped at [`handlers.py`](../../GPLAN/handlers.py)`:1964-1967` with no counter and no warning. Worse, when the graph is not a PTPG after augmentation the API branch is literally `pass#Later on return the error message to front` at `handlers.py:2216`, after `ui._set_output_data([])` at `:2209`. Trigger: any separating triangle that survives elimination; the caller receives an empty batch and a generic success message. Owner: [door-connectivity handler](dim/dim-07-door-connectivity-handler.md).

**Non-adjacency constraints are silently violated to force biconnectivity.** [`biconnectivity_non_adj.py`](../../GPLAN/source/graphoperations/biconnectivity_non_adj.py)`:211-220` falls back to adding edges taken straight from the `non_adj` list when the legal pool cannot span the blocks, with no exception, flag or log. The same block indexes `node_to_block[u]` at `:214-215`, which raises `KeyError` when the pair mentions the current articulation point. Trigger: a red-edge request whose blocks cannot be joined by any permitted edge. Owner: [connectivity augmentation](graph/connectivity-augmentation.md).

**A dimensioned L-shape request also runs the U-shape generator, on the GUI only.** In `handle_letter_shape` the `elif` chain is commented out at [`handlers.py`](../../GPLAN/handlers.py)`:970-974`, leaving `Ushaped.UShapedFloorplan(graph)` at `:975` inside the `if L Shape` block, so it executes immediately after `LShapedFloorplan` at `:969`. **Trigger: a dimensioned L request from the Tk desktop app only.** This is a [G8](#5-global-invariants) discriminator case, and an earlier draft of this document mis-stated the trigger as "every dimensioned L request": the enclosing branch is unreachable over HTTP, because `handlers.py:965` calls `dimgui.gui_fnc(ui, old_dims, ..., gclass)` and `handlers.py:969` then reads `gclass.app.nodes_data`, both with `gclass = None` on the API path. An HTTP dimensioned L request therefore raises before line 975 is reached. Note also that the U generator would not produce a wrong plan if it did run: `Ushaped.UShapedFloorplan` (`ushape.py:67`) calls `find_cips` (`ushape.py:123`) whose first statement (`ushape.py:124`) calls the unqualified name `get_trngls`, which `ushape.py` neither defines nor imports, so it raises `NameError` immediately (see Table 1 in [section 7](#7-dead-code-and-duplications)). Owner: [L-shaped core](graph/lshaped-core.md).

**Separating-triangle detection misses near-boundary nodes.** [`septri.py`](../../GPLAN/source/irregular/septri.py)`:50-51` uses a `1e-7` band in the point-in-triangle sign test, so a node within `1e-7` of a triangle edge counts as outside and the separating triangle is treated as a face. Trigger: near-collinear coordinates; the failure surfaces later as a bad dual, not as a reported separating triangle. Owner: [septri detection and covers](graph/septri-detection-covers.md).

**`LimitsAlgorithm` returns the farthest obstacle, not the nearest.** **[re-checked against source]**, because the owning dossier dim-08 is UNRELIABLE. [`limits.py`](../../GPLAN/source/polygonal/limits.py)`:425-426` and `:429-430` print `min(...)` while `:427` and `:431` return `max(...)`. The case-3 block additionally indexes `self.rooms[i]` rather than `self.rooms[nbd_rooms[i]]` (`:293`), clobbers `n` (`:294`), and is guarded by a tautology (`:295`). Trigger: any wall move through a room with more than one neighbour; the wall is permitted to pass through the nearest neighbouring vertex. GUI-only path. Owner: [polygonal limits](dim/dim-08-polygonal-limits.md).

**Space-optimization integrity is hardcoded empty and `adjacency_score` can go negative.** **[re-checked against source]**, because the owning dossier dim-11 is UNRELIABLE. [`api.py`](../../GPLAN/api.py)`:1625-1629` emits `overlaps`, `out_of_bounds` and `invalid_adjacent_edges` as literal `[]`, never computed. `api.py:1620` divides a raw score that gains `+1` per satisfied edge ([`negNew.py`](../../Space_Optimization/negNew.py)`:793`) and loses `2` per non-adjacency violation (`negNew.py:805`), so the quotient can fall below zero. Trigger: any space-optimized response; clients treating empty `integrity` as a health signal are reading a placeholder. Owner: [negNew IO boundary](dim/dim-11-negnew-io-boundary.md).

### Doc and test mismatches

**`maxDimEnabled` is a no-op on any transport that forwards maxima verbatim.** Only [`local_engine_bridge.py`](../../local_engine_bridge.py)`:84` computes `open_max` and substitutes the 99999 sentinel; the engine infers ceilings by value sniffing ([invariant G6](#5-global-invariants), mechanics in [section 2](#2-endpoint-to-algorithm-map)). Trigger: a client sending `minDimEnabled: true` with a real `width.max` through a view that passes maxima through gets that ceiling applied, contradicting the documented "max is ignored and treated as 99999". Owner: [concept trace](dim/dim-09-concept-trace.md), ledger rows 1 and 2.

**The test suite is green while rooms exceed their ceilings.** [`test_max_dimensions.py`](../../test_max_dimensions.py) pins reporting, not enforcement: T3 (`:201-206`) accepts any breach count so long as a warning substring exists and the count does not exceed the uncapped baseline. **Measured observation from the dossier verification pass, not re-run for this document and not pinned anywhere in source:** that run reported a green pass with 16 rooms over ceiling against an uncapped baseline of 19. Both numbers are printed diagnostics, so expect them to drift. [`test_api_cardinal_constraints.py`](../../test_api_cardinal_constraints.py) asserts direction only and never a number, and skips its real checks whenever the message contains `"ignored"` (`:187`, `:233`; T3 at `:126` has no such guard and asserts only `len(plans) > 0`). Trigger: any change that stops enforcing caps but keeps printing the warning. Full analysis in [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin). Owner: [tests and contracts](dim/dim-15-tests-and-contracts.md).

**Under pytest the suite is vacuous.** `test_max_dimensions.py` and `test_api_cardinal_constraints.py` expose no `test_*` functions, so pytest collects nothing; `test_multi_ptpg.py` exposes six, but every assertion goes through a `check()` that records instead of raising (`:25-31`). Trigger: any CI that runs `pytest` over this repo. Run them as scripts. Owner: [tests and contracts](dim/dim-15-tests-and-contracts.md).

**`door_connectivity.md` describes the plot dimension as a cap only.** The doc omits the second, stricter use: `dim_on_paths_bdy` additionally requires a boundary to fill at least 80 percent of the plot ([`path_map.py`](../../GPLAN/source/path_map.py)`:163-164`, relaxed at `:204-214`), which makes the plot a target rather than a cap, and it omits that the expand-only fallback reuses the pre-filtered pool. It also never mentions `floorplan_per_bdy_limit = 20` or `floorplan_limit = 500`, the real generation bounds. Owner: [door-connectivity handler](dim/dim-07-door-connectivity-handler.md), Documented Behaviour Versus Actual.

**A dead defensive branch guards a return arity that no longer exists.** [`handlers.py`](../../GPLAN/handlers.py)`:1712-1721` branches on `len(result) == 3` and shows "No augmentation found", but `door_connectivity` returns 2-tuples at [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:359` and `:520`; the 3-tuple return is commented out at `:370-373`. Trigger: a genuinely unaugmentable non-adjacency request cannot surface the intended error and proceeds silently. Owner: [inputgraph multi-dual and doors](graph/inputgraph-multidual-doors.md).

**`space_optimization_api.md` and the handler disagree on `max_expansion`.** [`handlers.py`](../../GPLAN/handlers.py)`:2717` reads `room.get('max_expansion', 20)`, so an omitted value grants a room 20 units of growth; the dossier records the doc as promising 0, and `Room.__init__` defaults to 3. Trigger: any request that omits `max_expansion`. Owner: [negNew IO boundary](dim/dim-11-negnew-io-boundary.md).

### Reported but not re-verified

These come from dossiers marked UNRELIABLE. The **anchors below were located and confirmed to point at the code the claim describes**, but the failure itself was not reproduced, so the claim is a lead, not an established defect. Read the source at these lines before acting.

- **Fixed rooms can land in the wrong place under a `boundary` request (Y-flip mismatch).** Regions are flipped by `y_out = max_y - (y_in + height)` where `max_y` is taken over the **kept regions**, at [`boundary_utils.py`](../../Space_Optimization/boundary_utils.py)`:153-157`. Fixed rooms are flipped separately by `y_engine = boundary_max_y - (y_req + height_req)` at [`handlers.py`](../../GPLAN/handlers.py)`:2726-2727`, where `boundary_max_y` comes from the **polygon** bounds computed at [`api.py`](../../GPLAN/api.py)`:1537-1544`. The two agree only when the regions actually reach the polygon's top edge. Not reproduced. [negNew IO boundary](dim/dim-11-negnew-io-boundary.md).
- **Sending both `boundary` and `regions` corrupts fixed-room placement instead of erroring.** The conversion is guarded by `if boundary and not regions` at `api.py:1524`, so an explicit `regions` list wins, but `boundary_bounds` is still computed from the polygon at `api.py:1537-1544` and then shifts and flips every fixed room at `handlers.py:2726-2727`. Not reproduced. [negNew IO boundary](dim/dim-11-negnew-io-boundary.md).
- **`paths_after_select_bdy` can leave a `None` slot.** `remaining = [w for w in selected_bdy if w != wall]` at [`path_map.py`](../../GPLAN/source/path_map.py)`:66` removes **all** equal copies, not one, so if two of the four boundary paths are equal lists the circular fill at `path_map.py:69-73` leaves one slot of `rearr_bdy` (initialised to `[None] * 4` at `path_map.py:62`) unset, and the iteration at `path_map.py:79` raises `TypeError: 'NoneType' is not iterable`. Whether two of the four paths can actually be equal was not established. [min-dimensioning driver](dim/dim-06-min-dimensioning-driver.md).

### Triaged, reproduced, and still open

A separate pass mined every dossier for defects that produce wrong dimensions or crashes, then verified each one against source with a reachability proof and, where possible, a live reproduction. 211 candidates were mined, 60 were rejected at triage as unreachable or out of scope, and 10 survived to verification: **6 confirmed, 3 unreachable, 1 deliberate**.

**Anchors in this subsection are against the current `main` (`db740b28`), not `a2c0baaf`.** They need no offset.

Two of the six are already fixed and are recorded above: the stale `j` in the rotated merge-node loop (`cda480bb`) and the unassigned `__symmetric` (`cda480bb`). The remaining four are open. Each has a reviewed patch that was deliberately **not applied**, so treat them as known-broken rather than as regressions:

| Defect | Where | Effect |
|---|---|---|
| `handle_single_oc` dereferences `gclass.open` | [`handlers.py`](../../GPLAN/handlers.py)`:1140` and `:1193` | **Crash on every dimensioned or min-dimensioned `rectangular`/`irregular` API request.** Reproduced from `api.py:1297` with `gclass=None`. A second defect hides behind it: the min-dim branch unpacks 5 names from `mindimgui.gui_fnc`, which returns 6 |
| Merged dummy rooms capped at 10 | [`inputgraph.py`](../../GPLAN/source/inputgraph.py)`:800-801` | `single_floorplan` caps merged dummy rooms at `max_width`/`max_height` of **10**, while the extranode loop 6 lines below (`:807-808`) and `multiple_floorplan` (`:1147-1155`) both use **10000**. Confirmed by an A/B run over an identical REL |
| The 0.3 retry rung is a no-op | [`path_map.py`](../../GPLAN/source/path_map.py)`:163-164` vs `:204-206` | `attempt_with_threshold` takes `threshold_ratio` as a parameter, but the two pointer gates hardcode `0.2`, so `attempt_with_threshold(0.3, ...)` at `:206` repeats the `0.2` attempt exactly. The documented widening ladder has one real rung, not two |
| Rooms outside the boundary pool count as zero | [`path_map.py`](../../GPLAN/source/path_map.py)`:99-109` | Path totals skip rooms absent from `outer_rooms`, understating the widths and heights used for plot fitting, so plans are judged to fit a plot they do not fit |

The last two are the mechanism behind the boundary-pool collapse seen in door-connectivity batches: the pool shrinks, nothing fits the plot, and the retry that was supposed to widen the gate does not widen it.

One finding was ruled **DELIBERATE** and must not be "fixed" casually: the rotation pass swaps only the plot axes, so a rotated plan applies each room's `min_width` to its final height. One was ruled **UNREACHABLE** in a way worth knowing: `multiple_floorplan` reads `rel_matrix_list` off a plain list at `inputgraph.py:1160` and would crash every dimensioned multi-floorplan request, but a different crash fires 16 lines earlier on every reachable path, so it is dead code behind a live bug.

---

## 7. Dead code and duplications

GPLAN carries several complete copies of the same algorithm, only one of which runs. Before editing anything under `source/`, confirm you are in the copy that the import graph actually reaches. Every claim below is anchored to an import site or a call site.

### Table 1: Duplicated implementations, which copy is live

| Family | Live copy (import site that proves it) | Dead or divergent copies | Verdict source |
| --- | --- | --- | --- |
| Edge-crossing detection | [graph_crossings1.py](../../GPLAN/source/graphoperations/graph_crossings1.py), imported at `handlers.py:6`, `inputgraph.py:28`, `inputgraph.py:44`, `septri.py:20`, `ptpg_floorplanner.py:58`; called at `inputgraph.py:161` and `inputgraph.py:471` | [graph_crossings.py](../../GPLAN/source/graphoperations/graph_crossings.py). Imported at `bdy.py:9` and `source/trial/bdy.py:9` only. `bdy.py`'s sole use is commented out; `source/trial/bdy.py` has no importer. Old windowing bug returns `None` where the new file returns `True` | [graph crossings duplication](graph/graph-crossings-duplication.md) |
| Separating-triangle removal | [septri.py](../../GPLAN/source/irregular/septri.py), imported `inputgraph.py:41` as `st`, called at `inputgraph.py:256`, `:437`, `:440`, `:492`, `:929` | [septri_non_adj.py](../../GPLAN/source/irregular/septri_non_adj.py). Imported at `inputgraph.py:42` as `st_non_adj`; a tree-wide grep for `st_non_adj.` returns zero hits. Carries an unmerged `i`->`j` shadowing fix and a 2-tuple return incompatible with the 3-tuple unpacking at `inputgraph.py:437`/`:440` | [septri vs septri_non_adj](graph/septri-nonadj-duplication.md) |
| Canonical ordering | [modifiedCanonical.py](../../GPLAN/source/lettershape/lshape/modifiedCanonical.py), imported at `Lshaped.py:9`, entry `modifiedCanonical.py:80`. Used by every L-shape plan | [polygonal/canonical.py](../../GPLAN/source/polygonal/canonical.py) (entry `:95`) is imported only at `gui.py:33` and reached only through `main.py:56`, so it is desktop-GUI-only. [lshape/canonical.py](../../GPLAN/source/lettershape/lshape/canonical.py) (entry `:79`) has **zero importers** anywhere | [canonical order family](graph/canonical-order-family.md) |
| Corridor insertion | root [circulation.py](../../GPLAN/circulation.py), imported at `handlers.py:31` as `cir`; constructed at `handlers.py:104` with 4 args | [source/circulation/circulation.py](../../GPLAN/source/circulation/circulation.py): no importer, 2-arg `__init__` at `:53`, an older 872-line subset. [source/multiple_circ.py](../../GPLAN/source/multiple_circ.py): no importer, and its own bare `import circulation` at `source/multiple_circ.py:10` cannot resolve inside the `GPLAN.` package | [root circulation](graph/circulation-root-graph.md), [source circulation package](graph/circulation-source-package.md) |
| Space-optimization engine | [negNew.py](../../Space_Optimization/negNew.py), imported at `handlers.py:2689` inside `handle_space_optimization` after a `sys.path` insert at `handlers.py:2685-2687` | [uinegNew.py](../../Space_Optimization/uinegNew.py) is a Tk desktop front end that *imports* the engine (`uinegNew.py:6`). Nothing imports `uinegNew`; verified, zero `import uinegNew` hits repo-wide. Legacy relative to the API, still runnable standalone | [uinegNew verdict](dim/dim-12-uinegnew-live-or-legacy.md) |
| `timing_decorator` | class-level copy at `inputgraph.py:168-176`, which shadows the module one for every method decoration (`:178`, `:339`, `:778`, `:848`, `:851`, `:1125`, `:1199`) | module-level copy at `inputgraph.py:65-73`, identical body, used only by the module functions at `:1364` and `:1452` | [inputgraph single-dual core](graph/inputgraph-single-dual-core.md) |
| LP constraint builder | [convert_adj_equ_sym.py](../../GPLAN/source/dimensioning/convert_adj_equ_sym.py), sole importer `floorplan_to_st.py:15` | `Convert_adj_equ` at `pythongui/final.py:1153`, a stale fork with no symmetry rows, no plot equality and no maximum-dimension rows. `final.py` is reachable (imported at `gui.py:27`) but only from the Tk GUI | [convert_adj_equ_sym](dim/dim-04-convert-adj-equ.md) |
| Letter-shape generators | No canonical copy. `tshape.py` (`handlers.py:11`), `ushape.py` (`handlers.py:12`), `zshape.py` (`handlers.py:13`), `staircaseshape.py` (star-imported at `inputgraph.py:19`) and `Lshaped.py` each carry their own fork of `new_matrix`, `connect_news`, `add_edges`, `find_cips`, `get_rel`, `get_floorplan`, `add_NESW`, `boundary_path_single` | `zshape.py` is `tshape.py` with one changed line (`zshape.py:73`). `ushape.py` cannot execute at all: it uses helper names it neither defines nor imports (`get_trngls`, `get_directed`, `get_bdy`, `ordered_bdy`, `get_shortcut` among them; the import block is `ushape.py:1-16`). The **first** failure on the real entry path is `ushape.py:124`, the opening statement of `find_cips` (`ushape.py:123`), which `UShapedFloorplan` (`ushape.py:67`) calls at `ushape.py:68`, so the function raises `NameError` before producing any geometry. The occurrence at `ushape.py:38` is inside `path_lister`, which is only reached later at `ushape.py:71`. `Lshaped.get_rel` has already drifted out of sync with `contraction.contract` | [letter shapes T/U/Z/staircase](graph/letter-shapes-tuzs.md) |
| Native corridor library | `corridor_creator.c`, loaded at `ga_current.py:87` | `corridor_creator` is defined a second time in `bfs.c:110` with 6 args instead of 7 and is never called. `corridor.c` is a 0-byte source still on the build list, shipping a 69 KB `corridor.so` that nothing dlopens | [GA corridor C layer](dim/dim-14-ga-corridors-c.md) |
| Whole-engine mirror | The engine package this document's `../../GPLAN/...` links resolve to, that is `GPLAN_Revamp/GPLAN/GPLAN/`, inside the repo checked out at `GPLAN_Revamp/GPLAN` | `gplan_backend/GPLAN` (that is `../../../gplan_backend/GPLAN/` from `documentation/algorithms/`) is the same engine consumed as a submodule. Verified byte-identical after newline normalization for `handlers.py`, `api.py` and `source/inputgraph.py`. **Edit only the top-level `GPLAN`**, consistent with the recorded rule that the engine source of truth is `nitantupasani/gplan_engine` | [entry point wiring](graph/entrypoint-wiring.md) |

### Table 2: Dead or GUI-only code an agent might otherwise edit

| Symbol (file:line) | Why it is unreachable | Dossier |
| --- | --- | --- |
| `InputGraph.door_connectivity2` (`inputgraph.py:650`) | No call site anywhere. Returns `None`, incompatible with the `(graph, checkPTPG)` unpacking at `handlers.py:1718`/`:1732`. Superseded by `door_connectivity` (`inputgraph.py:340`) | [inputgraph multi-dual and doors](graph/inputgraph-multidual-doors.md) |
| `InputGraph.polyonalinput` (`inputgraph.py:849`) and `handle_poly` (`handlers.py:1499`) | Only call chain is `main.py:56` -> `handlers.py:1502`. No `caller` value in `Documents.get_floorplans` dispatches to `handle_poly`. GUI-only | [inputgraph single-dual core](graph/inputgraph-single-dual-core.md) |
| `handle_limits` (`handlers.py:1509`) | Sole caller is `main.py:58` | [entry point wiring](graph/entrypoint-wiring.md) |
| `plot` (`handlers.py:474`) | No caller anywhere. `handlers.py:103`/`:117` call `cir.plot`; `circulation.py:137`/`:147` resolve to their own module-level `plot` at `circulation.py:941` | [entry point wiring](graph/entrypoint-wiring.md) |
| `InputGraph.extraedges` (`inputgraph.py:135`) | Written only by `door_connectivity` at `inputgraph.py:516`. After `irreg_single_dual` it is still `[]`, so `update_gclass_with_edges` colours every edge black | [inputgraph single-dual core](graph/inputgraph-single-dual-core.md) |
| `InputGraph.nodecnt_list` (`inputgraph.py:132`) | Documented as a list, never appended to. Assigned a bare scalar at `inputgraph.py:1009`, `:1094` and `Lshaped.py:171`, read as a scalar at `inputgraph.py:1119`. Misnamed scalar | [inputgraph single-dual core](graph/inputgraph-single-dual-core.md) |
| `septri.handle_STs_with_edge_selection` (`septri.py:1378`) and `remove_st_edge_selection` (`septri.py:1270`) | All three call sites are commented out: `inputgraph.py:439`, `:532`, `:712` | [septri vs septri_non_adj](graph/septri-nonadj-duplication.md) |
| `InputGraph.multiple_floorplan` (`inputgraph.py:1126`) | First statement in its plan loop, `inputgraph.py:1160`, reads `.rel_matrix_list` off a Python list, an unconditional `AttributeError`. Both call sites (`handlers.py:1069`, `:1474`) are GUI dimensioned-multiple paths | [inputgraph multi-dual and doors](graph/inputgraph-multidual-doors.md) |
| `circulation.multiple_circulation` (`circulation.py:90`), `find_exterior_edges` (`:100`), `donot_include` (`:125`), `disp_rel_push` (`:80`), `wheel_graph` (`:894`), `complete_graph` (`:921`), `is_subgraph` (`:958`) | Zero call sites, or called only from a commented-out test. `find_exterior_edges` also cannot run: `nx.to_numpy_matrix` is gone in NetworkX 3.x, and `bdy` is unbound given `import GPLAN.bdy` at `circulation.py:8` | [root circulation](graph/circulation-root-graph.md) |
| `GPLAN/bdy.py` and `source/trial/bdy.py` | `bdy.py` is imported only by `circulation.py:8` for the dead `find_exterior_edges`; `source/trial/bdy.py` has no importer at all | [graph crossings duplication](graph/graph-crossings-duplication.md) |
| `check_intersection` import at `handlers.py:6` | Vestigial. Its only in-file reference, `handlers.py:1698`, is commented out | [graph crossings duplication](graph/graph-crossings-duplication.md) |
| `process_edge` (`canonicalTransition.py:10`) | Definition is the only occurrence in the tree | [canonical order family](graph/canonical-order-family.md) |
| `run_ga`'s `room_dimensions` parameter (`ga_current.py:1213`) and `WEIGHTS["boundary_corridor"]` (`ga_current.py:121`) | `handlers.py:2935-2941` never passes `room_dimensions`, so it is always `None`. The weight is literally `0`, so the boundary-corridor count is multiplied out of the fitness | [GA corridor C layer](dim/dim-14-ga-corridors-c.md) |
| `uinegNew.py:1130`, `uinegNew.py:1247`, `uinegNew.py:6000` | The first two are shadowed at class-construction time by later definitions of the same names (`:1292`, `:1401`). `:6000` is a nested local `update_output_display` inside `generate_floor_plan`; all callers go through `self.`, which resolves to `uinegNew.py:3605` | [uinegNew verdict](dim/dim-12-uinegnew-live-or-legacy.md) |

Two structural notes. First, "imported" is not "called": `septri_non_adj` (`inputgraph.py:42`) and `check_intersection` (`handlers.py:6`) are bound names whose only observable effect is running the imported module body. Second, GUI-only is a distinct verdict from dead: `polygonal/canonical.py`, `handle_poly`, `handle_limits` and `pythongui/final.py` all execute under `main.py`, so deleting them breaks the desktop tool even though no HTTP request reaches them.

### Rules of thumb

Before editing any module under `source/`, grep for its import in `handlers.py`, `api.py` and `inputgraph.py`; those three files, plus `main.py` for the GUI-only question, decide reachability for everything in the engine. Treat an unimported module as dead until you have found a live import, and treat an imported-but-never-dereferenced alias the same way. When you are editing a letter shape, expect to repeat the edit in each clone (`tshape.py`, `zshape.py`, `ushape.py`, `staircaseshape.py`, and often `Lshaped.py`), because there is no shared base to fix once. Never edit `gplan_backend/GPLAN`: it is a submodule checkout of the same engine, and your change belongs in the top-level `GPLAN` tree that pushes to `nitantupasani/gplan_engine`.

---

## 8. Verifying a change: tests and what they actually pin

Three scripts sit at the engine repo root, one level above the `GPLAN/` package, and are the entire executable specification of this engine's behaviour. All three call the engine **in-process**: there is no server, no port, no deployed URL. `test_max_dimensions.py:31` inserts the repo root on `sys.path` and `:33` does `from GPLAN.api import Documents`; `test_api_cardinal_constraints.py:17-19` does the same plus `normalize_cardinal_constraints, spanning_tree_edges`; `test_multi_ptpg.py:16` and `:18` likewise. A grep for `http|requests|urllib|localhost|port|subprocess` across the three files finds nothing ([tests and contracts](dim/dim-15-tests-and-contracts.md), "Where It Sits"). So a green run means local engine code behaved, and nothing more: these tests pin **zero** of the Django/Celery/serialization layer. The route table (`gplan_backend/gplan_apis/urls.py:8`), the DRF view (`views.py:803`), the `prepared_data` assembly at `views.py:910-933`, the Celery call at `tasks.py:127`, the result assembly at `tasks.py:142`, and the error-to-payload mapping at `tasks.py:130-140` are all untested here ([entrypoint wiring](graph/entrypoint-wiring.md)). Those files are in the **sibling** repository at `GPLAN_Revamp/gplan_backend`, which is `../../../gplan_backend/` from `documentation/algorithms/`; the short form used above is for readability. If you change the response shape, run that backend separately from `GPLAN_Revamp/gplan_backend` (its own README and `DEPLOYMENT.md` describe the Django and Celery start-up; this document does not duplicate them) and exercise the real HTTP route. For engine-side smoke testing without Django, use the Flask bridge below. The recipe for a response-shape change is [4.7](#47-change-the-response-payload-the-ui-object-or-the-serialization-shape).

### test_max_dimensions.py

Exercises `Documents.get_floorplans` ([api.py](../../GPLAN/api.py):1215) on the `door_connectivity` min-dim path, via `build_request` at [test_max_dimensions.py](../../test_max_dimensions.py):81-113 and the single engine call at `:117`.

Strongest REAL assertions: T2 at `:185-188` builds `clean = [p for p in loose_plans if not breaches([p], LOOSE_CAPS)]` and requires `len(clean) > 0`, that is, at least one whole plan in which every room fits inside 3x its minimum on both axes. That is the strongest sizing assertion in the file. T4 at `:208-217` is an absolute lower bound: every returned room clears its own minimum in at least one orientation.

Weaknesses: this file **pins reporting of ceiling breaches, not enforcement**. T3 at `:201-206` accepts any breach count as long as a warning substring exists and the count does not exceed the uncapped baseline. **Measured observation, dossier verification pass, not re-run for this document:** that run was green with 16 rooms over ceiling against an uncapped baseline of 19. Neither figure appears in source or in any assertion, so neither is greppable and both should be re-measured rather than quoted. T5 at `:220-225` says "keep the plan count" but `min(len(open_plans), 1)` collapses the bound to `>= 1`. The `check()` harness at `:51-57` **records** failures and never raises; the only failure signal is the exit code at `:231`. Message strings at `:41` and `:43` are load-bearing: rewording [handlers.py](../../GPLAN/handlers.py):2203, `:2651` or [api.py](../../GPLAN/api.py):873-874 breaks T1 and silently loosens T2/T3. `:101` sends `plot_width: 0, plot_height: 0`, so no plot machinery is under test.

### test_api_cardinal_constraints.py

Exercises the same `get_floorplans` entry, with `rotation_enabled: 0` (`:47`), through `run` at [test_api_cardinal_constraints.py](../../test_api_cardinal_constraints.py):38-56.

REAL assertions are geometric but directional only. `check_side` at `:71-103` is a strip-intersection test: it builds the rectangle between a room's face and the plot bound and requires no other room overlaps it. T1 `:111` and T2 `:117` assert `len(plans) > 0 and ok == tot and tot > 0`. T8 `:233-235` asserts three pins hold on a 13-room graph.

Weaknesses: this file **asserts direction only, never a number**. No width, height, area or plot-fit assertion appears anywhere in it. T7 supplies a 30x20 plot (`:181-182`) and T8 a 54x40 plot (`:214`) and neither checks the extents. Worse, `:187` and `:233` skip the real check whenever the message contains `"ignored"`, so an engine that always fell to the bottom ladder rung would leave only `len(plans) > 0` in force. T5 `:138` omits the `tot > 0` guard, so an empty room match passes vacuously. T3 sets up the documented contradiction case and asserts only `len(plans) > 0` (`:126`). The file uses bare `assert`, so it aborts on first failure.

### test_multi_ptpg.py

Exercises `Documents.get_multi_ptpg_floorplans` ([api.py](../../GPLAN/api.py):1775), which delegates at `:1800` to [multi_ptpg_pipeline.py](../../GPLAN/source/multi_ptpg_pipeline.py) and bypasses `handlers.py` entirely ([multi-PTPG enumeration](graph/multi-ptpg-enumeration.md)). Entry point: `call` at [test_multi_ptpg.py](../../test_multi_ptpg.py):58-59.

Strongest REAL assertions: the exact-size check at `:90` (`(room["width"], room["height"]) != want`) reported at `:94`, a universal quantifier over every variant, plan and room, and the only exactness assertion in the suite. `:216-218` asserts every plan from a 20x20 plot has `p["width"] <= 20 and p["height"] <= 20`, the only plot-fit assertion anywhere in the three files. `:211-212` pins the reject filter (`plot_width=3` gives exactly 0 plans). `:166-167` pins the top rung of the strictness ladder (`exact` finds exactly 0). `:99-101` pins exact dual adjacency, `:121-123` variant distinctness, `:125-126` exactly one base.

Weaknesses: the inputs at `:45-46` are already integers, so the rounding path is never exercised, and `requested.get` at `:89` returns `None` for engine-added rooms, so synthetic-room sizing is silently skipped. Timing assertions at `:82` and `:119` flake on a loaded box. `check()` at `:25-31` never raises, so under `pytest` all six `test_*` functions pass unconditionally.

### Change to test

| Recipe family | Run this |
|---|---|
| Max dims and the release ladder | [test_max_dimensions.py](../../test_max_dimensions.py). It pins reporting, not enforcement; the ladder *firing* has **no test pins this** |
| Plot fitting, multi-PTPG path | [test_multi_ptpg.py](../../test_multi_ptpg.py) `:211-212`, `:216-218` |
| Plot fitting, min-dim path | **no test pins this** (dim-15 gaps 8 and 9: expansion warning observed in a run, no assertion reacted) |
| Cardinal direction | [test_api_cardinal_constraints.py](../../test_api_cardinal_constraints.py) T1/T2/T5/T8, direction only |
| Cardinal ladder rungs and ring augmentation | **no test pins this** (gaps 12 and 13). The code is taught in [recipe 3.4](#34-change-boundary-corner-or-cardinal-behaviour), items 7 to 12: `normalize_cardinal_constraints` api.py:126, `apply_cardinal_ring` api.py:349, `_ring_order_satisfies` api.py:153, `plan_satisfies_cardinal` api.py:374, `filter_output_by_cardinal` api.py:418, ladder api.py:1365-1406 |
| Response payload or serialization shape | **no test pins this**. See [recipe 4.7](#47-change-the-response-payload-the-ui-object-or-the-serialization-shape); verify by running the backend and the bridge |
| api.py post-processing: gapless fill, size caps, dimension repair | **no test pins the property**, only the warning strings. See [recipe 4.8](#48-change-apipy-post-processing-gapless-fill-size-caps-dimension-repair) |
| Letter shapes, one-connected path, stacked composition | **no test pins this**. Bridge only, and `ushape`/`tshape`/`zshape` fail before reaching shape code ([section 2](#2-endpoint-to-algorithm-map)) |
| Multi-PTPG exact sizing | [test_multi_ptpg.py](../../test_multi_ptpg.py) `:90`, `:94`; sub-unit rounding and synthetic rooms **no test pins this** (gaps 15, 16) |
| Multi-PTPG strictness | [test_multi_ptpg.py](../../test_multi_ptpg.py) `:166-171` |
| Graph topology, PTPG variants | [test_multi_ptpg.py](../../test_multi_ptpg.py) `:121-129`, `:141-151` |
| Graph topology, min-dim dual | **no test pins this**: the only adjacency assertions in all three files are `test_multi_ptpg.py:99-101`, on the PDF placer |
| Circulation | **no test pins this**. No script sets `circulationEnabled`, and the path crashes on the API anyway ([section 6](#6-known-defects-and-traps)) |
| Space optimization | **no test pins this**. `Documents.get_space_optimized_floorplan` ([api.py](../../GPLAN/api.py):1459) is imported by no script |
| GA | **no test pins this**. `Documents.get_ga_optimized_floorplan` ([api.py](../../GPLAN/api.py):1650) is imported by no script |

### How to run

From `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN`: `python test_max_dimensions.py`, `python test_api_cardinal_constraints.py`, `python test_multi_ptpg.py`. Exit code is 1 if any check failed, 0 otherwise (`test_max_dimensions.py:231`, `test_multi_ptpg.py:238`); the cardinal file exits non-zero on the first failed `assert`. Read the printed diagnostics, not just the exit code: a pass line can sit next to a non-zero "rooms over ceiling" count, which is exactly what the last recorded run did.

**Reported as runnable and green during the dossier verification pass; not re-run for this document, and not verifiable from source.** Treat "green" as a dated observation. The counts attached to it are structural and were re-checked by grep: 14 `check()` calls in `test_max_dimensions.py`, 34 in `test_multi_ptpg.py`, 0 in `test_api_cardinal_constraints.py` (which uses 11 bare `assert`s across 8 T-cases), and 6 `def test_` functions in `test_multi_ptpg.py` against 0 in the other two. (One draft section had the per-script `check()` numbers swapped; this is the corrected mapping.) The `no display found. Using :0.0` line at import is Tk-shim noise, not a failure. Never run these under `pytest`: the first two expose no `test_*` functions so pytest collects nothing, and the third collects six that cannot fail.

### Running the Flask bridge

Six of the recipes in sections 3 and 4 have no test at all, and for those the bridge is the stated verification route. It is a single-process Flask app that imports the engine directly, so a bridge run exercises exactly the code a Celery worker would, minus Django, Celery and the database.

1. Start it from the **engine repo root**, `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN`, the same directory the three test scripts run from: `python local_engine_bridge.py`. The server binds `127.0.0.1:8027` (`local_engine_bridge.py:190`).
2. Routes are `POST /api/generate/multi-ptpg` (`local_engine_bridge.py:132`), `POST /api/generate/<shape>` (`local_engine_bridge.py:159`) and `GET /api/task/<task_id>/` (`local_engine_bridge.py:180`).
3. **A POST does not return the plan.** Both generate routes run the engine synchronously, store the result in an in-memory dict, and then return HTTP **202** with `{"task_id": ..., "status": "started"}` (`local_engine_bridge.py:156` and `local_engine_bridge.py:177`). Read the `task_id` out of that body.
4. Fetch the result with `GET /api/task/<task_id>/`. An unknown id returns `{"status": "PENDING"}` (`local_engine_bridge.py:185-186`); a finished one returns either `{"status": "SUCCESS", "message": ..., "response": <floorplans.to_dict()>}` (`local_engine_bridge.py:168-169`) or `{"status": "FAILURE", "error": {"message": ...}}` (`local_engine_bridge.py:174`). Because the work happens before the 202, the result is already there on the first poll.
5. The bridge also prints a one-line summary per request, including the floorplan count and the engine message (`local_engine_bridge.py:170-171` for the shape route), and dumps a traceback to the console on failure (`local_engine_bridge.py:173`). Read the console, not just the JSON: engine warnings arrive in `message`, and an `AttributeError` from `handlers.py:941` on `ushape`, `tshape` or `zshape` shows up as a `FAILURE` result, not as a bad plan.
6. The bridge builds the engine call arguments itself in `_prepare` (`local_engine_bridge.py:55`, called at `local_engine_bridge.py:163`), so the request body it accepts is not identical to the Django one. Read `_prepare` before assuming a field is honoured; the flag columns in [section 2](#2-endpoint-to-algorithm-map) list the bridge-side line for each flag.

---

## 9. Graph algorithm reference: the dossiers

Twenty dossiers under `graph/` cover the graph-theoretic half of the engine, from the request boundary down to corridor geometry. Each one is a standalone reference with its own entry-point table, data-structure inventory, walkthrough, and dead-code findings. Use this index to pick the right one, then read that dossier rather than guessing from source. Entries marked MINOR_ERRORS were verified against source and found substantially correct but with at least one anchor or claim that did not hold; re-verify anchors you take from them.

### Orchestration and wiring

**[Entry point wiring: api.py and handlers.py](graph/entrypoint-wiring.md)**
Owns how a request reaches the pipeline: imports, handler definitions, and call sites, and nothing about the algorithms inside the modules they call. Primary sources are [api.py](../../GPLAN/api.py) and [handlers.py](../../GPLAN/handlers.py); the caller-string dispatch table is `Documents.get_floorplans` at `api.py:1215`, and `api.py:13` pulls every `handle_*` name in by star import. Records the fact that neither file defines an HTTP route: both are plain library modules (verdict: SOUND).
Read this when you are adding a new `caller` value, a new handler, or tracing which flag reaches which solver.
**Scope limit worth knowing:** this dossier covers imports, handler definitions and call sites, and deliberately says nothing about the algorithms inside. That leaves the api.py post-processing block (`rectangularize_output` api.py:801, `_room_size_caps` api.py:640, `_fill_gaps` api.py:710, `repair_dimensions` api.py:621) without any deep reference in either section 9 or section 10, even though it is the last code to touch client geometry. [Recipe 4.8](#48-change-apipy-post-processing-gapless-fill-size-caps-dimension-repair) is the only walkthrough of it that exists, and it was written against source rather than distilled from a dossier.

**[InputGraph: the single-dual core](graph/inputgraph-single-dual-core.md)**
Owns the single-plan half of the central mutable object: construction, connectivity check, the classic rectangular-dual chain, the cut-vertex variant, and turning one REL into a dimensioned plan. Source is [inputgraph.py](../../GPLAN/source/inputgraph.py), with `__init__` at `inputgraph.py:115`, `irreg_single_dual` at `inputgraph.py:202`, `single_floorplan` at `inputgraph.py:779`, and `oneconnected_dual` at `inputgraph.py:1200`. Also documents `OCError` (`inputgraph.py:47`) and `BCNError` (`inputgraph.py:55`) as the fallback signal handlers key off (verdict: SOUND).
Read this when you are changing the canonical stage order or the one-connected fallback.

**[InputGraph: multi-dual and door connectivity](graph/inputgraph-multidual-doors.md)**
Owns the other half of the same file: graph conditioning for the door-connectivity API, catalogue generation across boundaries and RELs, plot fitting, and traversal output. Anchors in [inputgraph.py](../../GPLAN/source/inputgraph.py) include `door_connectivity` at `inputgraph.py:340`, `scale_plot_dimension` at `inputgraph.py:597`, `irreg_multiple_dual` at `inputgraph.py:852`, and `get_final_traversal` at `inputgraph.py:1580`. It also marks `door_connectivity2` (`inputgraph.py:650`) as having no callers (verdict: SOUND).
Read this when you are changing how many candidate plans are produced, or how solved rectangles become client polygons.

### Preprocessing

**[Connectivity augmentation](graph/connectivity-augmentation.md)**
Owns the two repairs that force the input graph to satisfy the precondition of everything downstream: component stitching, then biconnectivity augmentation. Sources are [connect_graph.py](../../GPLAN/source/graphoperations/connect_graph.py) (`one_connected` at `connect_graph.py:9`), [biconnectivity.py](../../GPLAN/source/graphoperations/biconnectivity.py) (`biconnect` at `biconnectivity.py:86`), and its non-adjacency fork. It separates out `oneconnectivity.py`, which despite its name serves `oneconnected_dual` and is not part of the repair chain (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when a graph is being rejected before triangulation, or when you are editing the non-adjacency augmentation variant.

**[Triangulation core](graph/triangulation-core.md)**
Owns the step that turns a biconnected planar graph into a maximal planar one by adding chords inside every non-triangular interior face, and reports those added edges so later stages can tell invented adjacency from requested adjacency. Sources are [triangularity.py](../../GPLAN/source/graphoperations/triangularity.py) (public `triangulate` at `triangularity.py:254`), its non-adjacency fork (`triangulate` at `triangularity_non_adj.py:430`), and [earclipping.py](../../GPLAN/source/graphoperations/earclipping.py). The module returns edges rather than mutating the matrix; the caller writes them in (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when you are changing edge provenance or how forbidden pairs constrain chord insertion.

**[Graph crossings: the live file and the dead one](graph/graph-crossings-duplication.md)**
Owns one boolean question: given per-vertex coordinates and an adjacency matrix, do two drawn edges cross away from a shared vertex. [graph_crossings1.py](../../GPLAN/source/graphoperations/graph_crossings1.py) is the live copy, reached on every `InputGraph` construction at `inputgraph.py:161` and again inside door connectivity at `inputgraph.py:471`; the older `graph_crossings.py` is dead as executable code. The dossier records that the module never rejects input, it only sets a flag and the caller re-embeds (verdict: SOUND).
Read this before deleting either file, or when a valid graph is silently losing its user-drawn coordinates.

### Separating triangles

**[Separating triangles: detection and edge covers](graph/septri-detection-covers.md)**
Owns the detection predicates and the cover-and-removal core: find every separating triangle in the current drawing, pick an edge set that hits all of them, subdivide each chosen edge with a fresh vertex, and re-triangulate locally. Source is [septri.py](../../GPLAN/source/irregular/septri.py), with `handle_STs` at `septri.py:273` as the only entry point in scope reachable from handlers. The stage is gated by an Euler-style count at `inputgraph.py:255` (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when you are changing how many structurally different plans one graph yields, or how dummy rooms become L-shaped rooms.

**[Separating triangles: the door-connectivity handlers](graph/septri-door-handlers.md)**
Owns the ST eliminators used by the door-connectivity flow, which destroy separating triangles without adding any vertex: delete an ST edge bordering a single triangular face, or flip a diagonal. Sources are `handle_non_trivial_ST_Door_connectivity` at `septri.py:359`, its non-adjacency twin at `septri.py:700`, and the read-only checker `handle_STs_Door_connectivity` at `septri.py:1146`. The pre-augmentation snapshot `one_connected` (`inputgraph.py:360-361`) is what marks an edge as safe to spend (verdict: SOUND).
Read this when you are changing which edges the algorithm is allowed to sacrifice to keep room count fixed.

**[septri_non_adj and shortcutresolver](graph/septri-nonadj-duplication.md)**
Owns two small units: the forked non-adjacency ST module and the shortcut resolver. [septri_non_adj.py](../../GPLAN/source/irregular/septri_non_adj.py) is imported at `inputgraph.py:42` and never dereferenced; all seven of its functions have counterparts in `septri.py`. [shortcutresolver.py](../../GPLAN/source/irregular/shortcutresolver.py) is live: `get_shortcut` at `shortcutresolver.py:14` and `remove_shortcut` at `shortcutresolver.py:34` feed corner-implying-path detection (verdict: SOUND).
Read this before "fixing" the non-adjacency ST fork, or when boundary corner choices look wrong.

### Boundary and REL

**[Boundary labeling: CIPs and the NEWS 4-completion](graph/boundary-news-cip.md)**
Owns 4-completion: where the four corners of the bounding rectangle must fall on the outer cycle, and how the outer cycle is split into four arcs with N, E, S, W vertices attached. Sources are [cip.py](../../GPLAN/source/boundary/cip.py) (`find_cip` at `cip.py:11`) and [news.py](../../GPLAN/source/boundary/news.py) (`add_news` at `news.py:249`). Compass semantics for the whole engine are fixed at `news.py:265-268`, where the four vertices are appended in N, E, S, W order (verdict: SOUND).
Read this when you are touching corner selection, cardinal constraints, or anything that indexes `nodecnt-4` through `nodecnt-1`.

**[The canonical-order family](graph/canonical-order-family.md)**
Owns four files: three near-copies of a canonical-ordering class computed by peeling removable vertices off the outer face, plus one converter that is a different algorithm. The copies are at `polygonal/canonical.py:9`, `lshape/canonical.py:9`, and `modifiedCanonical.py:9`; [canonicalTransition.py](../../GPLAN/source/lettershape/lshape/canonicalTransition.py) consumes an order and emits REL labels 2 and 3 at `canonicalTransition.py:204-205` (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when you are editing L-shape REL generation and need to know which of the three copies is actually live.

**[REL construction: the contraction-expansion core](graph/rel-contraction-expansion.md)**
Owns the conversion of a 4-completed PTPG into a Regular Edge Labelling by contract-then-expand. Sources are [contraction.py](../../GPLAN/source/floorplangen/contraction.py) (`contract` at `contraction.py:187`) and [expansion.py](../../GPLAN/source/floorplangen/expansion.py) (`basecase` at `expansion.py:29`, `expand` at `expansion.py:53`, ten case functions across `expansion.py:203-547`). It documents that adjacency and labels share one matrix rather than two (verdict: SOUND).
Read this when a generated plan has edges oriented the wrong way, or when you are adding a case to the expansion table.

**[REL to rectangular dual: dual, rdg, flippable](graph/dual-rdg-flippable.md)**
Owns two downstream jobs: turning a REL into T1 and T2 path matrices and reading grid-unit rectangles off them, and enumerating neighbouring RELs by flips. Sources are [dual.py](../../GPLAN/source/floorplangen/dual.py), [rdg.py](../../GPLAN/source/floorplangen/rdg.py) (`construct_dual` at `rdg.py:20`), and [flippable.py](../../GPLAN/source/floorplangen/flippable.py). It separates out `transformation.py`, whose `transform_edges` at `transformation.py:13` runs before contraction, not after (verdict: SOUND).
Read this when you are changing grid coordinates or how many RELs are enumerated per boundary.

### Shaped and polygonal floorplans

**[L-shaped floorplans](graph/lshaped-core.md)**
Owns L-shape generation: add one extra northeast vertex, build an ordinary rectangular dual of the augmented graph, then delete the northeast room so the notch becomes the L. Source is [Lshaped.py](../../GPLAN/source/lettershape/lshape/Lshaped.py), with `LShapedFloorplan` at `Lshaped.py:24`, `multipleLshapedFloorplans` at `Lshaped.py:113`, and the reused dual constructor at `Lshaped.py:536` (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when you are changing where the notch goes or how many L variants a graph produces.

**[Letter shapes T, U, Z and staircase](graph/letter-shapes-tuzs.md)**
Owns the non-L shape generators, which add fake exterior rooms to the adjacency matrix before the standard 4-completion and dual pipeline, then register them in `graph.extranodes` so the renderer subtracts them. Entry points are `TShapedFloorplan` at `tshape.py:64`, `UShapedFloorplan` at `ushape.py:67`, `ZShapedFloorplan` at `zshape.py:64`, and `StaircaseShapedFloorplan` at `staircaseshape.py:65`. It confirms the clone family: [zshape.py](../../GPLAN/source/lettershape/zshape/zshape.py) is [tshape.py](../../GPLAN/source/lettershape/tshape/tshape.py) with one semantic constant changed, and `ushape.py` carries an unrepaired refactor (verdict: SOUND).
Read this when you are adding a new letter shape or fixing one that never returns a plan.

**[Polygonal floorplans](graph/polygonal-floorplans.md)**
Owns plans whose outer boundary is a polygon rather than a rectangle, built by canonical-order incremental dissection with rooms stored as explicit corner lists instead of rectangles. Sources are [poly.py](../../GPLAN/source/polygonal/poly.py) and [newcoord.py](../../GPLAN/source/polygonal/newcoord.py) (`NewCoordinateAlgorithm` at `newcoord.py:8`); `polygonal/lshape.py` is dead. The package is reachable only through `handle_poly` at `handlers.py:1499`, called from the Tkinter entry point and never from `api.py` (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when you are asked to expose polygonal plans over HTTP, or to move the wall-move algorithm onto the API surface.

**[Multi-PTPG enumeration](graph/multi-ptpg-enumeration.md)**
Owns the exact-dimension path: enumerate alternative PTPGs on a fixed node set by deleting boundary edges and flipping diagonals, then place rooms at exact widths and heights per variant. Sources are `enumerate_ptpg_variants` at `multiple_ptpg.py:241`, `generate_floorplans` at `ptpg_floorplanner.py:819`, and [multi_ptpg_pipeline.py](../../GPLAN/source/multi_ptpg_pipeline.py) (`run` at `multi_ptpg_pipeline.py:376`, reached from `api.py:1775`). This path deliberately bypasses `irreg_multiple_dual` and the LP dimensioning stack (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when you are changing exact-size generation, which is a separate stack from the min-dim flow.

### Circulation

**[The source/ circulation package](graph/circulation-source-package.md)**
Owns three files that share a directory but not a purpose: `source/circulation/circulation.py` and `source/multiple_circ.py` are standalone-runnable scripts with no importers anywhere, while [path_map.py](../../GPLAN/source/path_map.py) is live and is not about corridors at all. `dim_on_paths_bdy` at `path_map.py:99` filters candidate boundary decompositions against plot dimensions, called from `inputgraph.py:972` and `inputgraph.py:1057`, and falls back to the unfiltered list when it returns empty (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when boundary candidates collapse under plot dimensions and nothing fits the plot ([recipe 4.4](#44-change-the-boundary-pool-dim_on_paths_bdy-or-fix-the-batch-collapse)).

**[Circulation: the graph half](graph/circulation-root-graph.md)**
Owns corridor insertion at the graph level: subdivide edges with corridor vertices so every room touches a corridor and the corridors form a connected tree off one entry door. Source is [circulation.py](../../GPLAN/circulation.py), with `circulation_algorithm` at `circulation.py:235` (a BFS over triangular faces) producing `circulation_graph`, `adjacency`, and `corridor_tree` at `circulation.py:302-304`, plus pruning via `min_tree_set_cover` at `circulation.py:341` (verdict: SOUND).
Read this when you are changing corridor topology or the entry-door seed.

**[Circulation: the geometry half](graph/circulation-root-geometry.md)**
Owns turning the abstract corridor list into coordinates: open a gap of the corridor thickness along each shared wall, propagate the shifts so the plan stays tiled, apply them in one pass, then check dimensional feasibility. Anchors in [circulation.py](../../GPLAN/circulation.py) are `adjust_RFP_to_circulation` at `circulation.py:446`, `add_corridor_between_2_rooms` at `circulation.py:529`, `push_edges` at `circulation.py:824`, and `check_dimensions_feasibility` at `circulation.py:843`. The corridor is never an object: it is the void left after both rooms retreat (verdict: MINOR_ERRORS, cross-check line anchors before relying on them).
Read this when corridors overlap rooms, or when a dimensioned run reports infeasible after corridor insertion.

---

## 10. Dimensioning reference: the dossiers

Fifteen dossiers cover the dimensioning surface. Each one was written against source read in full, and each carries a verdict from an independent verification pass: SOUND (no claim refuted), MINOR_ERRORS (some claims corrected in place), or UNRELIABLE (enough refuted claims that the dossier's structure survives but its details do not). Read the verdict before you trust a line anchor.

### Input plumbing

**[Flag plumbing: dimensioning inputs, payload to consumer](dim/dim-01-flag-plumbing.md)**
Owns the trace of every dimensioning input (`minDimEnabled`, `maxDimEnabled`, `plot_width`, `plot_height`, strictness) from HTTP body to the line that reads it. Its finding is that there is no single parser: four independent payload parsers with four different default sets feed two structurally unrelated consumers, `DimParameters` for the door-connectivity solver and plain dicts for space-opt, GA and multi-PTPG. Primary sources are [api.py](../../GPLAN/api.py) (`DimParameters` built at `api.py:1227` and `api.py:1229`, stored at `api.py:1232`), [GuiParameters.py](../../GPLAN/pythongui/GuiParameters.py) (`DimParameters` at `GuiParameters.py:13-102`), plus the two HTTP layers `gplan_backend/gplan_apis/views.py:835` and `local_engine_bridge.py:75`. It also names the flags that are parsed and never read, `maxDimEnabled` among them (`views.py:839`). (MINOR_ERRORS.) Read this when you are adding or renaming a dimensioning request field and need to know every parser you must touch.

**[InputGraph dimensioning hooks](dim/dim-02-inputgraph-hooks.md)**
Owns the hand-off from [inputgraph.py](../../GPLAN/source/inputgraph.py) into the LP dimensioner: `single_floorplan` (`inputgraph.py:779`) and `multiple_floorplan` (`inputgraph.py:1126`) are the only methods in the class that call `GPLAN/source/dimensioning`, via imports at `inputgraph.py:39` (`floorplan_to_st`) and `inputgraph.py:43` (`block_checker`). It establishes that dimension constraints are not attributes of `InputGraph` at all: they are call-scoped parameters owned by `handlers.py`, and the callee mutates the caller's lists in place while padding for merged and extra nodes (`inputgraph.py:797-810`). It also records that `minimum_dimensioning.py` is never imported here. (SOUND.) Read this when you are changing the constraint arguments a candidate topology is dimensioned with.

### The LP chain

**[Stage 1: floorplan_to_st and block_checker](dim/dim-03-floorplan-to-st.md)**
Owns the conversion of a unit-grid rectangular dual into two s-t digraph adjacency matrices, one per axis, and the symmetry precondition check. Sources are [floorplan_to_st.py](../../GPLAN/source/dimensioning/floorplan_to_st.py) (entry at `floorplan_to_st.py:18`, `convert_adj_equ_sym` twice at `:103` and `:105`, `solve_linear` at `:108`) and [block_checker.py](../../GPLAN/source/dimensioning/block_checker.py) (`block_checker.py:4`), called from `inputgraph.py:817` and `inputgraph.py:821`. It documents that the LP chain and the min-dim chain are disjoint modes selected by the `dimensioned` versus `minDimEnabled` flags. (MINOR_ERRORS.) Read this when you are changing how the encoded matrix becomes solver input, or touching symmetry groups.

**[Stage 2: convert_adj_equ_sym, the constraint builder](dim/dim-04-convert-adj-equ.md)**
Owns the construction of the four numpy arrays `scipy.optimize.linprog` needs (objective `f`, inequality LHS `A`, equality LHS `Aeq`, equality RHS `Beq`) from one directional s-t adjacency matrix, in [convert_adj_equ_sym.py](../../GPLAN/source/dimensioning/convert_adj_equ_sym.py) (entry at `convert_adj_equ_sym.py:15`, plot-constraint sentinel at `:117`). It opens with a correction to its own task premise, and that correction is the load-bearing result for anyone navigating this area: the brief said the chain is driven by `minimum_dimensioning.py`, which is false. `minimum_dimensioning.py` imports only `defaultdict`, `json` and `os` (`minimum_dimensioning.py:1-3`) and never references this module. The two solvers are siblings, not stages. Note that the inequality RHS `b` is not built here; it is built in `solve_linear`. (MINOR_ERRORS, 5 refuted claims.) Read this when you are adding or removing an LP constraint class.

**[Stage 3: solve_linear.py](dim/dim-05-solve-linear.md)**
Owns the two actual linear programs in [solve_linear.py](../../GPLAN/source/dimensioning/solve_linear.py): the width solve at `solve_linear.py:76` and the height solve at `solve_linear.py:140`, both `scipy.optimize.linprog` with `method='interior-point'`, entry at `solve_linear.py:16`. It records that widths are solved first, per-room height windows are then derived from the widths and the aspect-ratio lists, and that one inconsistent room silently drops aspect-ratio constraints for every room. (SOUND.) Read this when you are debugging infeasible LP results or changing the aspect-ratio handling.

**[minimum_dimensioning.py, the min-dim driver](dim/dim-06-min-dimensioning-driver.md)**
Owns the solver the production door-connectivity path actually runs: [minimum_dimensioning.py](../../GPLAN/source/dimensioning/minimum_dimensioning.py), a hand-rolled longest-path relaxation over two per-axis difference-constraint graphs, no scipy, entry `main()` at `minimum_dimensioning.py:767`, with `upper_bound` at `:158`, `construct_constraintgraphX/Y` at `:225` and `:307`, and `reinitialize` at `:729`. It flags that the whole module is module-level global state and is neither reentrant nor thread-safe, and that its sole importer is `handlers.py:9`. (UNRELIABLE, 2 refuted claims.) Treat unverified claims in this dossier as leads, not facts; check the source before relying on a line anchor. Read this when you are changing how minimum dimensions or coordinates are computed under a plot cap.

### The door-connectivity driver

**[handle_door_connectivity](dim/dim-07-door-connectivity-handler.md)**
Owns the production request handler in [handlers.py](../../GPLAN/handlers.py), lines 1686 to 2657: it augments the graph to a PTPG, enumerates rectangular-dual candidates, runs each through the min-dim solver under an optional plot cap, and mutates `ui` with the survivors, returning `None` always. Key anchors: `get_max_dims` at `handlers.py:309`, `solve_min_dim` at `handlers.py:338`, callers at `api.py:1309` and `api.py:1353`, and the real candidate pool `graph.graph_list_by_bdy` at `inputgraph.py:148`. The PTPG and non-PTPG branches are near-duplicate blocks, which is why edits here are usually needed twice. (MINOR_ERRORS, 6 refuted claims.) Read this when you are changing candidate selection, batch ordering, or the plot-cap fallback behaviour.

**[Concept trace: eight documented concepts to code](dim/dim-09-concept-trace.md)**
Owns the mapping from concepts that appear only in the GPLAN markdown documentation to the function that implements them, or a statement that the concept is documentation-only. Seven of eight are implemented; two differ from their documented semantics in ways a client can observe. It spans both the door-connectivity pipeline (`api.py:1215`, `handlers.py:1686`, `minimum_dimensioning.py:158`, `dim_on_paths_bdy` at [path_map.py](../../GPLAN/source/path_map.py)`:99`) and the multi-PTPG placer ([ptpg_floorplanner.py](../../GPLAN/source/ptpg_floorplanner.py)`:819`). (SOUND.) Read this when a document promises behaviour and you need to find the code that either delivers it or does not.

### Polygonal limits

**[polygonal/limits.py](dim/dim-08-polygonal-limits.md)**
Owns [limits.py](../../GPLAN/source/polygonal/limits.py), whose name misleads: it computes no per-room min/max dimensions and produces no LP bounds. It answers a single question, how far one wall of one room can be dragged before colliding with a vertex or edge of that room or its adjacent neighbours, returning the reachable pair at `limits.py:427` and `limits.py:431` and gating the caller through `self.proceed` (`limits.py:11-28`). Its one caller is `handle_limits` (`handlers.py:1509`, call at `handlers.py:1603`), reached only from the Tkinter desktop app (`main.py:58`), so the module is unreachable in the deployed API. (UNRELIABLE, 5 refuted claims.) Treat unverified claims in this dossier as leads, not facts; check the source before relying on a line anchor. Read this when you are working on interactive wall dragging, or deciding whether this module can be deleted.

### Space optimization

**[negNew.py placement and sizing core](dim/dim-10-negnew-sizing-core.md)**
Owns the randomized constructive packer: given rooms whose width and height the caller already decided, it searches x/y positions with no overlap, containment in the region union, and requested adjacencies respected. Sizing is an afterthought layered on placement, rooms may be transposed and grown in whole units up to a per-room `max_expansion`; there is no dimension solver and no LP. Source is [negNew.py](../../Space_Optimization/negNew.py) (class `FloorPlan` at `negNew.py:219`, run entry `generate_layout` at `negNew.py:1675`), imported via sys.path injection at `handlers.py:2685-2687` then `handlers.py:2689`, driven from `handlers.py:2751`. (SOUND.) Read this when you are changing packing, compaction or the expansion budget.

**[Space optimization API boundary](dim/dim-11-negnew-io-boundary.md)**
Owns the input and output surfaces around that engine, deliberately excluding the algorithm. Three separable jobs: polygon to rectangles in [boundary_utils.py](../../Space_Optimization/boundary_utils.py) (`decompose_boundary_into_rectangles` at `boundary_utils.py:41`), dict to object graph in `handle_space_optimization` ([handlers.py](../../GPLAN/handlers.py)`:2659-2843`), and object graph back to dict at `handlers.py:2776-2833` reshaped by [api.py](../../GPLAN/api.py)`:1590-1636`, all entered from `api.py:1459`, the `def get_space_optimized_floorplan` line (`api.py:1458` is its `@staticmethod` decorator; sections 1 and 2 use `:1459` and this blurb previously disagreed with them). There is no serialization code in `negNew.py` at all. (UNRELIABLE, 3 refuted claims.) Treat unverified claims in this dossier as leads, not facts; check the source before relying on a line anchor. Read this when you are changing the space-optimization request or response schema.

**[uinegNew.py: live or legacy](dim/dim-12-uinegnew-live-or-legacy.md)**
Owns the liveness question for [uinegNew.py](../../Space_Optimization/uinegNew.py), and settles it: legacy for the deployed API, still runnable standalone as a desktop GUI. It is not a fork of `negNew.py`; it imports the production engine at `uinegNew.py:6`, and a repo-wide grep finds zero `import uinegNew` anywhere. Its `__main__` block at `uinegNew.py:6858` still launches a working Tk tool against the current engine. The deployed API touches exactly three files in that directory: `negNew.py`, `boundary_utils.py` and `ga_current.py`. (MINOR_ERRORS.) Read this when you are deciding whether a `negNew.py` change must be mirrored into the GUI, or whether the GUI can be dropped.

### GA optimization

**[GA sizing core: ga_current.py](dim/dim-13-ga-sizing-core.md)**
Owns encoding, fitness, selection, crossover, mutation and the evolution loop in [ga_current.py](../../Space_Optimization/ga_current.py) (`run_ga` at `ga_current.py:1210`, `calculate_fitness` at `:1026`, decoder `apply_chromosome` at `:651`), imported via sys.path injection at `handlers.py:2863-2865`. Its headline conclusion is that this engine does not size rooms, it translates them: a room's cell set is frozen at parse time (`ga_current.py:548-557`) and every operator only adds an integer `(dr, dc)` offset, so no gene encodes width, height or area. (SOUND.) Read this when you are tuning GA fitness weights or changing the chromosome.

**[GA corridor C layer and the GA handler](dim/dim-14-ga-corridors-c.md)**
Owns the native bridge and `handle_ga_optimization`. Three C translation units supply the corridor primitives the fitness function calls once per individual: `corridor_creator` (the 7-argument variant Python calls, `corridor_creator.c:34`), `count_corridor_components` (`bfs.c:38`), and `count_boundary_accessible_corridors`. The handler is [handlers.py](../../GPLAN/handlers.py)`:2845`, with ctypes call sites at `ga_current.py:1086`, `:1109` and `:1120`, and one final carve on the winning chromosome at `handlers.py:2973`. Note that `corridor.c` is a zero-byte file that is still compiled and shipped and that nothing loads. (MINOR_ERRORS.) Read this when you are changing corridor carving or rebuilding the shared libraries.

### Executable contracts

**[The dimensioning tests and the multi-PTPG exact-sizes contract](dim/dim-15-tests-and-contracts.md)**
Owns what is actually pinned by the three test scripts, [test_max_dimensions.py](../../test_max_dimensions.py), [test_api_cardinal_constraints.py](../../test_api_cardinal_constraints.py) and [test_multi_ptpg.py](../../test_multi_ptpg.py), all of which call the engine in-process with no server or port. The gap it documents matters: `test_max_dimensions.py` pins reporting of ceiling breaches, not enforcement, and the dossier's own run recorded a green pass with 16 rooms over their ceilings (a measured observation, not a pinned value, and not re-run for this document); the cardinal test pins direction and never a number; `test_multi_ptpg.py:90` and `:94` hold the only exact-size assertion, and `:216-218` the only plot-fit check. Engine entry points are [api.py](../../GPLAN/api.py)`:1215` and `api.py:1775`. (SOUND.) The digest of this dossier, with the change-to-test table, is [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin). Read the dossier itself when you need the full gap list.

---

## Known gaps in this document

Things this document does not cover, or covers only partly. They are listed so you do not spend time looking for coverage that is not here. Each one says what would close it.

**~~Publishing is not done.~~ CLOSED.** The 35 dossiers are published in `GPLAN/documentation/algorithms/` next to this file. All 35 dossier links and all 59 source links were checked mechanically after the copy: none broken, no dossier unlinked.

**No deep reference owns the api.py post-processing block.** `rectangularize_output` (api.py:801), `_room_size_caps` (api.py:640), `_fill_gaps` (api.py:710) and `repair_dimensions` (api.py:621) have [recipe 4.8](#48-change-apipy-post-processing-gapless-fill-size-caps-dimension-repair) and nothing else: no dossier, no test, no line-by-line walkthrough of the fill algorithm itself. Closing it: a dossier on that block, at the depth of the existing 35.

**No deep reference owns the response and serialization surface.** [Recipe 4.7](#47-change-the-response-payload-the-ui-object-or-the-serialization-shape) names the class, the setters, the serialization loop and the transport mapping, but `GuiParameters` has no dossier of its own, and neither does the `Documents` / `Room` / `Wall` object model in api.py. Closing it: a dossier covering `pythongui/GuiParameters.py` and the api.py response classes together.

**Corridor geometry is anchored at the top level only.** [Recipe 3.6](#36-change-corridor-or-circulation-behaviour) item 5 now carries verified anchors for the five steps of `adjust_RFP_to_circulation` (circulation.py:446-526), but the per-edge machinery below it, `add_corridor_between_2_rooms` (circulation.py:529) and `push_edges` (circulation.py:824), is documented only in a MINOR_ERRORS dossier whose interior anchors were not confirmed. Closing it: a re-verification pass over [circulation geometry half](graph/circulation-root-geometry.md).

**Two defects are leads, not findings.** The three bullets under [Reported but not re-verified](#reported-but-not-re-verified) now carry anchors that were confirmed to point at the described code, but none of the three failures was reproduced, and both owning dossiers are UNRELIABLE. Closing it: reproduce each one, or delete it.

**Numbers that are observations, not anchors.** The 16-rooms-over-ceiling result, the 19-room uncapped baseline, the 2 / 14 / 30 plan counts, and the "runnable and green" status of the three scripts are all measurements from earlier runs, labelled as such wherever they appear. None was re-run for this document. Closing it: re-run the three scripts and re-date the numbers.

**Anchor drift is live, not hypothetical.** Anchors are against commit `a2c0baaf`; `main` is now `db740b28`. The drift is known and constant, and the offset table in [How to use this document](#how-to-use-this-document) converts an anchor to its current line. The offsets were not applied to the 180 KB of anchors in this file, because a mechanical rewrite would break the correspondence with the dossiers, which are still written against `a2c0baaf`. Closing it: a single pass that re-verifies and rewrites anchors in this file and all 35 dossiers together, or a check script that applies the offset table automatically.

**~~Three endpoints are documented as broken rather than fixed.~~ FIXED in `db740b28`.** `POST /api/generate/ushape|tshape|zshape` raised `AttributeError` at `handlers.py:941`, which resolved `nodes_data` as `gclass.app.nodes_data` with no guard while `api.py` passes `nodes_data` only for the L shape and never passes `gclass`. All three were reproduced failing and now pass that line. Two further defects in the same function's dimensioned branch were fixed with it: the commented-out `elif` chain had left `Ushaped.UShapedFloorplan` at the L branch's indent, so a dimensioned L shape ran two generators over one graph, and a dimensioned T, Z or U shape matched no branch, ran no generator, and dimensioned whatever matrix arrived. The other three shapes now raise instead of returning a plan built from a stale matrix, so dimensioned T, Z and U remain unimplemented, but they fail loudly rather than silently.

**Untested surfaces this document names but cannot demonstrate.** Circulation, space optimization, GA, the LP chain, shaped floorplans, the one-connected path and the stacked composition have no test coverage at all ([section 8](#8-verifying-a-change-tests-and-what-they-actually-pin)). For those, "verify your change" means running the bridge or the endpoint by hand and reading the output, and this document cannot tell you what a correct output looks like beyond the invariants listed in each recipe.

---

## Maintaining this document

**Publishing step, required before any dossier link works.** This document and its 35 dossiers are written to live in `GPLAN/documentation/algorithms/`, a directory that does not exist yet. To publish:

1. Create `GPLAN/documentation/algorithms/` in the engine repo (the existing `GPLAN/documentation/` holds the flat API docs, including the `door_connectivity.md` that `../door_connectivity.md` targets).
2. Copy `dossiers/graph/` to `documentation/algorithms/graph/` and `dossiers/dim/` to `documentation/algorithms/dim/`. The directory names must stay `graph` and `dim`, matching the two group names in `dossier_manifest.json` and the 20 plus 15 links in sections 9 and 10. If you rename either group, rename it in the manifest and in every link in the same commit.
3. Copy this file in as `documentation/algorithms/POINTER_DOC.md`, or whatever name the index expects.
4. Re-check the links: 20 `graph/<id>.md`, 15 `dim/<id>.md`, and the source-relative `../../GPLAN/...`, `../../Space_Optimization/...`, `../../test_*.py`, `../../local_engine_bridge.py` and `../door_connectivity.md` targets. Backend anchors are written in the short `gplan_backend/...` form and need `../../../` prefixed to resolve.

Until step 2 is done, every dossier link in this document is dead; that is recorded in [Known gaps in this document](#known-gaps-in-this-document).

This document was generated from dossiers produced by agents reading the source, then merged and cross-checked in an editorial pass. Every claim carries a `file:line` anchor, and a number of contested anchors (import sites, expression counts, file locations, test check counts) were re-verified against the working tree during assembly. Anchors are against engine-repo commit `a2c0baaf` and drift when code moves: treat a mismatched anchor as a signal to re-verify the claim against the source, never as truth in itself. When you re-verify a `handlers.py` or `GuiParameters.py` anchor, check whether the uncommitted work described in [How to use this document](#how-to-use-this-document) is still in the tree before concluding the anchor is wrong, and re-base the whole file's anchors in one pass once that work lands. When you change engine behaviour, update the owning dossier and the affected recipe together, and re-run the relevant script from [section 8](#8-verifying-a-change-tests-and-what-they-actually-pin); per project practice, documentation updates ship with the change, not after it. If a dossier's verdict is MINOR_ERRORS or UNRELIABLE, a re-verification pass that corrects its anchors should also upgrade its verdict line, so the reliability signal stays honest.
