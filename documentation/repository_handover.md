# GPLAN Repository Handover

This repository has two main execution surfaces:
- the legacy GUI and graph-floorplan flow
- the API and script-driven optimization flow

If you are new to the codebase, start here. The goal of this document is to explain where the logic lives, how requests move through the repo, and which files usually need to change together.

## Where To Start

The main entry points are:
- [main.py](../main.py)
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/api.py](../GPLAN/api.py)

`main.py` boots the GUI, builds `GuiParameters`, and dispatches the current command. `api.py` exposes the same capabilities as static methods on `Documents` so the test scripts and external service wrappers can call them directly.

## The Three Main Flows

### 1. Door Connectivity / Legacy Graph Flow

This is the classic graph-based floorplan pipeline.

1. The GUI command is set to `door_connectivity` in [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py).
2. `main.py` or `Documents.get_floorplans(...)` forwards to `handle_door_connectivity` in [GPLAN/handlers.py](../GPLAN/handlers.py).
3. `handle_door_connectivity` prepares the UI state, normalizes non-adjacency edges, and calls `InputGraph.door_connectivity`.
4. `InputGraph.door_connectivity` in [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py) performs biconnectivity augmentation, triangulation, separating-triangle cleanup, and PTPG checks.
5. The irregular cleanup helpers in [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py) and the dimensioning cleanup in [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py) preserve the final layout and edge semantics.
6. `Documents.get_floorplans` serializes the result into the document response and attaches `ptpg_graph` when available.

### 2. Space Optimization Flow

This path is API-first and is used for boundary-based floor planning.

1. `Documents.get_space_optimized_floorplan` reads the request payload.
2. If the request contains `boundary`, `api.py` converts it into rectangular regions using `Space_Optimization/boundary_utils.py`.
3. `handle_space_optimization` loads [Space_Optimization/negNew.py](../Space_Optimization/negNew.py).
4. The engine places the rooms, applies expansion or compaction if requested, and computes metrics.
5. The wrapper returns `floor`, `placements`, and `metrics` in the API response.

The GUI path in `main.py` still has a placeholder branch for `space_optimization`. In practice, this feature is exercised through the API and the test scripts.

### 3. GA Optimization Flow

This path optimizes an already-built floorplan with a genetic algorithm.

1. `Documents.get_ga_optimized_floorplan` builds a `floorplan_data` structure from the request.
2. `handle_ga_optimization` loads [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py).
3. The GA parser converts rooms and walls into a grid model.
4. The optimizer runs, applies the best chromosome, and generates corridors.
5. The wrapper returns optimized rooms, walls, labels, and the final `layout_matrix`.

## Module Map

The repo is organized by problem domain rather than by HTTP endpoint.

- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py): graph representation, door-connectivity transforms, and dual-generation hooks.
- [GPLAN/source/graphoperations/](../GPLAN/source/graphoperations/): connectivity, triangulation, crossings, and graph augmentation helpers.
- [GPLAN/source/irregular/](../GPLAN/source/irregular/): irregular-shape and separating-triangle logic.
- [GPLAN/source/dimensioning/](../GPLAN/source/dimensioning/): constraint graphs, minimum dimensioning, and final cleanup.
- [GPLAN/source/floorplangen/](../GPLAN/source/floorplangen/): floorplan transformation helpers such as duals, flips, contraction, and expansion.
- [GPLAN/source/boundary/](../GPLAN/source/boundary/): boundary-specific helpers.
- [GPLAN/source/circulation/](../GPLAN/source/circulation/): circulation-related helpers.
- [GPLAN/source/lettershape/](../GPLAN/source/lettershape/): L/U/T/Z shape variants.
- [GPLAN/source/polygonal/](../GPLAN/source/polygonal/): polygonal and rectangular boundary support.
- [GPLAN/source/staircaseshape/](../GPLAN/source/staircaseshape/): staircase-specific support.
- [Space_Optimization/negNew.py](../Space_Optimization/negNew.py): space-optimization engine.
- [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py): GA corridor optimizer.
- [GPLAN/system_functions/os_functions.py](../GPLAN/system_functions/os_functions.py): operating-system helpers used by legacy flows.

## Test Harness Map

The scripts under [GPLAN/](../GPLAN/) are direct-run harnesses, not pytest suites.

- [GPLAN/Test_api.py](../GPLAN/Test_api.py): general graph and door-connectivity harness.
- [GPLAN/test_api_boundary_input.py](../GPLAN/test_api_boundary_input.py): boundary-to-regions examples and backward-compatibility checks.
- [GPLAN/Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py): multi-scenario space-optimization suite.
- [GPLAN/test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py): editable single-request runner.
- [GPLAN/test_api_ga_optimization_simple.py](../GPLAN/test_api_ga_optimization_simple.py): editable GA runner.

## What Usually Changes Together

When you make a change, update the owning layer and the surrounding contract together.

- Door-connectivity changes usually require edits in [GPLAN/handlers.py](../GPLAN/handlers.py), [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py), [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py), [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py), [GPLAN/api.py](../GPLAN/api.py), and the graph test harnesses.
- Space-optimization changes usually require edits in [GPLAN/api.py](../GPLAN/api.py), [GPLAN/handlers.py](../GPLAN/handlers.py), [Space_Optimization/negNew.py](../Space_Optimization/negNew.py), and the space-optimization test scripts.
- GA changes usually require edits in [GPLAN/api.py](../GPLAN/api.py), [GPLAN/handlers.py](../GPLAN/handlers.py), [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py), and the GA test script.

## Practical Rules For New Contributors

- `main.py` currently does not implement the space-optimization GUI branch. That work is API-driven.
- The GA code expects the native DLLs in the repository root before it can run on Windows.
- If request or response fields change, update the matching documentation and the nearest test script in the same change.
- When working on door connectivity, preserve red-edge semantics and dummy-node remapping together.

## Next Reads

- [door_connectivity_update_guide.md](door_connectivity_update_guide.md)
- [api_reference.md](api_reference.md)
- [testing_handover.md](testing_handover.md)
- [work_history_timeline.md](work_history_timeline.md)
- [work_history_feature_map.md](work_history_feature_map.md)
