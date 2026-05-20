# GPLAN API Reference

The public API surface in this repository lives in [GPLAN/api.py](../GPLAN/api.py) as static methods on `Documents`.

There is no Flask or FastAPI router in the repo itself. The test scripts and any external service wrapper call the `Documents` methods directly.

This document covers the three API families that matter most in practice:
- the legacy graph floorplan API used for door connectivity
- the space optimization API
- the GA optimization API

## 1. Graph Floorplan API

This is the legacy graph-based flow used by [GPLAN/Test_api.py](../GPLAN/Test_api.py) and the GUI door-connectivity path.

### Entry Point

The main entry point is `Documents.get_floorplans(...)` in [GPLAN/api.py](../GPLAN/api.py).

The `caller` argument selects the mode. For door connectivity, `caller` is `door_connectivity`.

### Request Shape

The request is assembled from these groups of fields:

- `starting_from`: first document index to read from legacy storage flows
- `count`: number of floorplans requested
- `nodes`: array of node objects
- `edges`: array of edge objects
- `rectangular`: legacy shape flag
- `corridor`: legacy corridor flag
- `dimensioned`: enable full dimensioning constraints
- `dimensionedCirculation`: circulation dimensioning flag
- `minDimEnabled`: enable minimum-dimension mode
- `removeAddCirculation`: circulation cleanup flag
- `publicEnabled`: legacy visibility flag
- `normalizeConst`: legacy normalization flag
- `non_adj`: mark that red non-adjacency edges exist
- `limit`: legacy ceiling used by the wrapper
- `corridorThickness`: corridor width hint
- `documentID`: optional document id
- `name`: optional document name
- `circulationEnabled`: circulation mode toggle

### Node Shape

Each node may contain:
- `id`
- `x`
- `y`
- `label`
- `color`
- `width`
- `height`
- `ratio`

If `width`, `height`, or `ratio` are omitted, the wrapper fills in defaults before dispatch.

### Edge Shape

Each edge contains:
- `source`
- `target`
- `color`

In this flow:
- `black` means adjacency
- `red` means non-adjacency

### What The Code Does

`Documents.get_floorplans(...)` performs the following steps:
- builds `InputGraph` from the node and edge lists
- builds `GuiParameters`
- forwards to `handle_door_connectivity` when `caller == "door_connectivity"`
- serializes the generated floorplans into a `Documents` object
- attaches `ptpg_graph` when the door-connectivity path produces one

### Response Shape

The response is a dictionary with a top-level `Documents` object:

- `documentID`: document identifier
- `name`: document name
- `count`: requested count
- `floorPlans`: array of floorplan arrays
- `ptpg_graph`: optional adjacency matrix

Each room in `floorPlans` contains:
- `_id`
- `name`
- `label_coord`
- `area`
- `width`
- `height`
- `color`
- `walls`
- `circular_coordinates`

### When To Update This Section

Update this section if you change any of the following:
- the `Documents.get_floorplans(...)` signature
- the `caller` values used by the legacy graph path
- the document serialization shape
- the meaning of red or black edges

## 2. Space Optimization API

This API generates a floorplan inside one or more rectangular regions or inside a polygonal boundary that is converted to regions first.

### Entry Point

The main entry point is `Documents.get_space_optimized_floorplan(request_data)` in [GPLAN/api.py](../GPLAN/api.py).

Internally it calls `handle_space_optimization` in [GPLAN/handlers.py](../GPLAN/handlers.py).

### Request Shape

The request has this structure:

- `request_id`: unique request identifier
- `engine`: must be `FloorPlan`
- `params`: payload object
- `ops`: list of operations to execute

### Parameters

Inside `params`, the important fields are:

- `boundary`: optional polygon vertices
- `regions`: optional rectangular region list
- `rooms`: required room list
- `fixed_rooms`: optional fixed-room list
- `adjacency`: optional adjacency pairs
- `non_adjacency`: optional non-adjacency pairs
- `entrance_coords`: optional entrance line segment
- `max_attempts`: optional retry limit

You must provide either `boundary` or `regions`. Do not provide both as the primary input. If `boundary` is present and `regions` is absent, the API converts the boundary into regions automatically.

### Room Shape

Each room entry should contain:
- `name`
- `width`
- `height`
- `max_expansion`

Fixed rooms also need:
- `x`
- `y`
- `is_fixed = true`

### Operation List

`ops` can include:
- `place`
- `compact`
- `expand`
- `score`

The wrapper uses `ops` to decide whether expansion and compaction are enabled.

### How Boundary Conversion Works

`Documents.get_space_optimized_floorplan` converts `boundary` into `regions` through `boundary_to_regions(...)`, which is backed by [Space_Optimization/boundary_utils.py](../Space_Optimization/boundary_utils.py).

That means the boundary path is not a separate engine. It is a convenience layer around the same region-based floor-optimization logic.

### Response Shape

The response uses this shape:

- `request_id`
- `status`: `ok` or `error`
- `data`
- `error`

Inside `data`:
- `floor`
- `placements`
- `metrics`

`floor` contains:
- `width`
- `height`
- `regions`
- `entrance_coords`

`placements` contains the final room placements with:
- `name`
- `x`
- `y`
- `width`
- `height`
- `rotated`
- `is_fixed`
- `original_width`
- `original_height`
- `area`

`metrics` contains:
- `ops_run`
- `adjacency_score`
- `satisfied_pairs`
- `non_adjacency_violations`
- `entrance_adjacent_rooms`
- `area_utilization`
- `integrity`

### Metric Semantics

A few details matter when you interpret the output:
- `adjacency_score` is normalized by the wrapper, so it is easier to read as a percentage-like value.
- `area_utilization` is computed from total region area versus occupied area.
- `integrity` is part of the response contract, even though the wrapper currently returns empty lists for the overlap and bounds checks.

### When To Update This Section

Update this section if you change:
- boundary conversion rules
- the set of supported `ops`
- the room or fixed-room schema
- the response metric names
- the output shape returned by `handle_space_optimization`

### Related Test Files

- [GPLAN/test_api_boundary_input.py](../GPLAN/test_api_boundary_input.py)
- [GPLAN/test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py)
- [GPLAN/Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py)

## 3. GA Optimization API

This API takes a completed floorplan, optimizes room positions with a genetic algorithm, and generates corridors.

### Entry Point

The main entry point is `Documents.get_ga_optimized_floorplan(request_data)` in [GPLAN/api.py](../GPLAN/api.py).

Internally it calls `handle_ga_optimization` in [GPLAN/handlers.py](../GPLAN/handlers.py).

### Request Shape

The request has this structure:

- `request_id`
- `engine`: must be `GA_FloorPlan`
- `params`

### Parameters

Inside `params`, the important fields are:

- `plot_width`
- `plot_height`
- `corridor_width`
- `ga_config`
- `rooms`
- `walls`
- `labels`
- `windows`
- `doors`

### Important Request Rules

Keep these rules in mind when building the payload:
- room names should be numeric strings such as `"1"`, `"2"`, `"3"`
- every room should reference wall ids that also exist in the flattened `walls` list
- labels are optional but useful for display and verification
- if you change the room ids or wall ids, keep them aligned everywhere in the payload

### GA Configuration

`ga_config` currently supports:
- `population_size`
- `num_generations`
- `mutation_rate`
- `max_workers`

The handler also adjusts tournament size for small populations so selection remains safe.

### What The Code Does

`Documents.get_ga_optimized_floorplan(...)` first normalizes the request into a `floorplan_data` dictionary, then passes it to `handle_ga_optimization`.

`handle_ga_optimization`:
- loads [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py)
- suppresses plotting during API execution
- parses the floorplan JSON
- runs the GA
- applies the best chromosome
- creates the corridor matrix
- returns the optimized rooms, walls, labels, and layout matrix

### Response Shape

The response contains:
- `request_id`
- `status`: usually `success` or `error`
- `engine`: `GA_FloorPlan`
- `data`
- `error`

Inside `data`:
- `floor`
- `ga_optimization`
- `rooms`
- `walls`
- `labels`
- `windows`
- `doors`
- `layout_matrix`

`ga_optimization` contains:
- `status`
- `solution_chromosome`

Each optimized room contains:
- `id`
- `name`
- `color`
- `walls`
- `optimized_bounds`

`optimized_bounds` currently uses:
- `min_r`
- `max_r`
- `min_c`
- `max_c`

### `layout_matrix` Semantics

The final matrix uses these values:
- `0` for empty space
- `99` for corridor cells
- positive integers for room ids
- `-1` only in intermediate matrices, not usually in the final response

### Runtime Notes

The GA engine imports DLLs from the repository root on Windows. If those DLLs are missing, the import will fail before optimization starts.

### When To Update This Section

Update this section if you change:
- the floorplan JSON structure that GA expects
- the GA configuration keys
- the optimized room response shape
- the corridor or layout matrix encoding
- the DLL loading path or runtime requirements

### Related Test File

- [GPLAN/test_api_ga_optimization_simple.py](../GPLAN/test_api_ga_optimization_simple.py)

## 4. Common Translation Pattern

A common workflow in this repository is:
1. generate or inspect a graph floorplan
2. convert the result into a placement-oriented representation
3. run space optimization
4. run GA optimization if you want corridor-aware polishing

If you add a new translator between APIs, document the input shape, output shape, and the exact file that owns the conversion.
