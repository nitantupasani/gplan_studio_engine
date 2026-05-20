# Work History Feature Map

This document maps the main workstreams from the commit history to the files that currently own them.

Use it when you are deciding where to edit, or when you need to understand which parts of the repo grew together over time.

## 1. Door Connectivity And Minimum Dimensioning

Historical focus:
- min-dim integration into door connectivity
- irregular-room handling
- planarity after separating-triangle removal
- non-adjacency support
- circulation integration
- PTPG output and edge preservation

Current ownership files:
- [main.py](../main.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [GPLAN/pythongui/GuiParameters.py](../GPLAN/pythongui/GuiParameters.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

If you are touching this stream, change these together:
- graph augmentation in `inputgraph.py`
- triangle cleanup in `septri.py`
- dummy-node or red-edge preservation in `minimum_dimensioning.py`
- dispatch/state handling in `handlers.py` and `GuiParameters.py`
- serialization in `api.py` and the test harness

## 2. Non-Adjacency Support

Historical focus:
- API support for red edges
- multiple-door handling
- disconnected graph fixes
- separating-triangle fixes for non-adjacent constraints
- cleaner GUI plumbing for non-adj lists

Current ownership files:
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/graphoperations/](../GPLAN/source/graphoperations/)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/pythongui/GuiParameters.py](../GPLAN/pythongui/GuiParameters.py)

If you are fixing a non-adj bug, first check whether the problem is in:
- request parsing
- graph augmentation
- separating-triangle cleanup
- GUI state propagation

## 3. Space Optimization

Historical focus:
- boundary-to-regions conversion
- fixed rooms
- adjacency and non-adjacency constraints
- compaction and expansion
- API payload normalization
- test harness coverage

Current ownership files:
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [Space_Optimization/negNew.py](../Space_Optimization/negNew.py)
- [Space_Optimization/boundary_utils.py](../Space_Optimization/boundary_utils.py)
- [GPLAN/test_api_boundary_input.py](../GPLAN/test_api_boundary_input.py)
- [GPLAN/test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py)
- [GPLAN/Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py)

If you are changing this workstream, keep these contracts aligned:
- `boundary` and `regions` should remain interchangeable entry styles
- `ops` should still control expansion and compaction
- `metrics` should keep the same field names
- test scripts should mirror the API payload exactly

## 4. GA Optimization

Historical focus:
- GA porting from the standalone optimization code
- corridor generation
- room/wall/label serialization
- boundary conversion feeding the GA input
- native DLL integration
- GA config tuning and runtime safety

Current ownership files:
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py)
- [Space_Optimization/bfs.c](../Space_Optimization/bfs.c)
- [Space_Optimization/corridor_creator.c](../Space_Optimization/corridor_creator.c)
- [Space_Optimization/boundary_accessible_corridors.c](../Space_Optimization/boundary_accessible_corridors.c)
- [Space_Optimization/bfs.h](../Space_Optimization/bfs.h)
- [Space_Optimization/corridor_creator.h](../Space_Optimization/corridor_creator.h)
- [Space_Optimization/boundary_accessible_corridors.h](../Space_Optimization/boundary_accessible_corridors.h)
- [GPLAN/test_api_ga_optimization_simple.py](../GPLAN/test_api_ga_optimization_simple.py)
- [build_dlls.py](../build_dlls.py)

If you are changing GA behavior, remember:
- room ids and wall ids must remain consistent across the entire payload
- `ga_config` is part of the public contract
- the final response must still expose `ga_optimization`, `rooms`, `walls`, `labels`, and `layout_matrix`
- the native DLLs are part of the runtime dependency set on Windows

## 5. GUI And Legacy Runtime

Historical focus:
- command dispatch
- plot sizing and resize handling
- labels and output-data fixes
- circulation and floorplan mode selection
- keeping the GUI state consistent with API-driven behavior

Current ownership files:
- [main.py](../main.py)
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [GPLAN/pythongui/GuiParameters.py](../GPLAN/pythongui/GuiParameters.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

If you change GUI behavior, check both:
- the button or command path in `gui.py`
- the state object in `GuiParameters.py`

## 6. Documentation And Test Harnesses

Historical focus:
- making the feature set legible for new contributors
- keeping sample payloads current
- showing exactly how each API should be used

Current ownership files:
- [documentation/README.md](README.md)
- [documentation/repository_handover.md](repository_handover.md)
- [documentation/api_reference.md](api_reference.md)
- [documentation/testing_handover.md](testing_handover.md)
- [documentation/door_connectivity_update_guide.md](door_connectivity_update_guide.md)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)
- [GPLAN/test_api_boundary_input.py](../GPLAN/test_api_boundary_input.py)
- [GPLAN/Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py)
- [GPLAN/test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py)
- [GPLAN/test_api_ga_optimization_simple.py](../GPLAN/test_api_ga_optimization_simple.py)

If you change the API contract, update the docs and the matching test script in the same change.

## Practical Picking Guide

If you are not sure where to start, use this order:
1. Find the request entry point in `api.py` or `main.py`.
2. Find the state bridge in `handlers.py` or `GuiParameters.py`.
3. Find the algorithmic owner in `inputgraph.py`, `septri.py`, `minimum_dimensioning.py`, `negNew.py`, or `ga_current.py`.
4. Update the matching test file.
5. Update the doc page that explains that flow.

That keeps the code and the handover in sync.
