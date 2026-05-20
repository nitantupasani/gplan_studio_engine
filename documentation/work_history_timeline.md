# Work History Timeline

This document summarizes what the QA branch has focused on from July 2024 to the current head. It is based on the commit history and grouped into phases so a new maintainer can see how the code evolved.

## How To Read This

The repo did not evolve as isolated features. Most work happened as connected changes across the graph pipeline, API wrappers, GUI state, and optimization engines.

Use this timeline if you want to understand:
- why a file exists
- which feature introduced a code path
- which bug fixes were responding to earlier work
- where to start if you need to modify an old feature

## Phase 1: July 2024 - Door Connectivity, Min-Dim, and Early API Wiring

Representative commits:
- `dfa82c31` - Added min_dim to door connectivity for rectangular fixed optimal floorpln in rectangular might need to implement same fix for irregular later
- `dfee9a79` - k4 Removal readded in Door_connectivity
- `02643f77` - Removed unnecessary plane drawings from door_connectivity
- `015f9233` - Fixes in merging |circulation | irregular | min_dim
- `34d3a446` - Merged two circulation functions together
- `9269c50b` - min dim bug fixed
- `3df463a6` - dimensioning api support added in gplan
- `b7071c3f` - min_dimensioning api support adapter with backend.
- `dff65117` - Added irregular mindim to door_connectivity
- `61f9258c` - Fix in irregular mindim +Doorconnectivity

What changed in this period:
- minimum-dimension logic was attached to the existing door-connectivity pipeline
- irregular floorplans started sharing the same min-dim handling as rectangular ones
- the codebase started to separate visual cleanup from core graph logic
- API support for dimensioning entered the repo
- room-name and output-data bugs were fixed so the flow could be serialized reliably

Files that mattered most:
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [GPLAN/pythongui/GuiParameters.py](../GPLAN/pythongui/GuiParameters.py)

## Phase 2: August 2024 - Non-Adjacency, Multiple Door Cases, and Graph Output Stability

Representative commits:
- `930b27ce` - Non-Adjacency Modification
- `40cc9073` - Output data fix |Multiple Door
- `8b1d21f9` - Multiple_door in Non dimensioned and Non PTPG
- `db4229ed` - Multiple in Door connectivity non dimensioned non PTPG
- `598589e0` - Added check for Graph being connected
- `7c4c097a` - Area , Height , widht , room name coords
- `c22ba4f5` - Append Output data fix
- `24e5dca2` - moved nonAdjList to GuiParams for api

What changed in this period:
- non-adjacency support became a first-class input instead of a side case
- multiple-door and non-PTPG variations were wired into the same flow
- graph connectivity checks were added earlier in the pipeline
- output payloads were stabilized so tests and GUI consumers saw the same data
- `nonAdjList` moved into GUI state so the API could read it consistently

Files that mattered most:
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/pythongui/GuiParameters.py](../GPLAN/pythongui/GuiParameters.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

## Phase 3: September 2024 - Planarity, Separating Triangles, and Non-Adj Door-Conn Cleanup

Representative commits:
- `859dfe1f` - Check planarity after removal of separating triangles in door connectivity
- `089c3070` / `6e62141f` - Fixed Auxilary functions for triangulation
- `79649671` / `fa93c61d` - Multiple in biconnectivity / Different Approach MultipleBCN
- `e5b1c22c` / `0f921401` - Removal of NonTrivial ST / Bug fix in NonTrivial ST removal
- `e324ecdd` / `27819cce` - New Separating triangle check
- `618445f1` / `8e5d9c9e` - Triangulation fix
- `679f4e54` - Non_adj_merge fix

What changed in this period:
- the pipeline became much more careful about planarity after separating triangle removal
- separating-triangle removal logic was repeatedly hardened
- biconnectivity and triangulation fixes were merged into the door-connectivity workflow
- the non-adjacency branch was aligned with the same cleanup rules as the standard branch

Files that mattered most:
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/graphoperations/](../GPLAN/source/graphoperations/)
- [GPLAN/handlers.py](../GPLAN/handlers.py)

## Phase 4: October 2024 - Non-Adj List Plumbing and Final Door-Conn Stabilization

Representative commits:
- `758a1ac9` - Original graph edge check in septri removal
- `ba1f79b5` - Minor fix in septri
- `082b01b3` - Non adj list in door_conn

What changed in this period:
- the separator-triangle cleanup started preserving original graph edges more carefully
- non-adjacent edge lists were threaded into the door-connectivity flow
- the feature was stabilized enough to move the non-adjacency list into `GuiParams` for the API path

Files that mattered most:
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)
- [GPLAN/pythongui/GuiParameters.py](../GPLAN/pythongui/GuiParameters.py)
- [GPLAN/api.py](../GPLAN/api.py)

## Phase 5: November-December 2024 - Non-Adj API, Biconnectivity Fixes, and Disconnected Graph Handling

Representative commits:
- `8508cb93` - Non_adj api
- `cd1bb609` - added non adjacent edges support to generate floorplan
- `72089336` - Nonadj gui fix for api
- `3d317355` - Feature: Solves Disconnected Graph
- `c336982f` - Fix: Separating triangle code for non-adjacency constrainta
- `68180ee2` - Fix: Non_Adjacency Biconnectivity Fix
- `ee3e82a2` - Fix: Non-Adj biconnected graph
- `6cc673bb` - Fix: Non-Triangular Faces
- `322aaf34` - Fix in Hnnadling ST
- `cee23827` - Fix: Separating Triangle
- `3b585681` - Fix:Scale plot size

What changed in this period:
- the non-adjacency API became a visible supported surface
- disconnected graphs were handled instead of failing silently
- the non-adjacency and biconnectivity paths were fixed repeatedly
- plot scaling and GUI/API consistency were cleaned up at the same time

Files that mattered most:
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

## Phase 6: January-February 2025 - Circulation Integration, Boundary-Aware Door Connectivity, and API Contract Tweaks

Representative commits:
- `ee29efe8` - Added: Circulation with Door_connectivity
- `5b96ce23` - Added: Bound area door connectivity
- `c67f5f7c` - Rotate plot dims
- `a1b8b881` - API param change
- `e2b8da81` - Extra edge colour + mindim length
- `8f618b28` - Plot resize message in api
- `ef43f5d8` - Fix:plot rotation door connnectivity
- `c795ea20` - Add: Max workers in circulation API
- `d4f092fd` - Update: PTPG in output of door_connectivity API
- `efc8a620` - Update: Use SerialExec when workers == 1
- `e7259964` - Fix:2 Node edge case in door_connectivity

What changed in this period:
- circulation became integrated with door connectivity
- boundary-aware door connectivity was added
- plot dimension rotation and API parameter handling were updated
- the API started exposing PTPG data in its output
- the runtime got a single-worker serial path for stability
- the 2-node edge case in door connectivity was fixed

Files that mattered most:
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

## Phase 7: March-April 2025 - Optimal Min-Dim and Boundary Refinement

Representative commits:
- `0856bac9` - Fix:Non_adj
- `c1c92c3f` - Optimal path selection
- `827205c1` - Fix: septri Identification
- `ebd10310` - shrink removed
- `f6b2c9fc` - Optimising Min Dim floorplans
- `4a20dc07` - Optimal_integration initial
- `a48d7ec3` - Fix: septri removal
- `b9087a82` - Fix: Allow Rotation
- `81f77fa4` / `353736c7` - Update: optimal bdy
- `41d768da` - Add:limits per bdy in multiple optimal
- `b82fd47f` - Fix:Optimal

What changed in this period:
- the min-dim branch became more optimal-path aware
- separating-triangle identification and removal got additional fixes
- shrinking and rotation constraints were refined
- boundary-specific optimal handling was added

Files that mattered most:
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

## Phase 8: October 2025 - Space Optimization Integration

Representative commits:
- `01b8feda` - Integrate Space Optimization
- `30714ed3` - Modify: test files (space optimization)

What changed in this period:
- the repository gained the space-optimization engine as a supported workflow
- the API and test harnesses were updated to use the new engine

Files that mattered most:
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py)
- [GPLAN/Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py)
- [Space_Optimization/negNew.py](../Space_Optimization/negNew.py)

## Phase 9: December 2025 - GA Port, GA API, and Boundary Conversion

Representative commits:
- `844e737a` - Port GA_Optimized
- `96735420` - Add: GA_optimiaztion API
- `68bfb8ca` - Fix: sapce_optimization handler
- `5ef86eb1` - Add: Boundary -> regions conversion in API
- `1c900a1d` - Update: Use pre-existing algo for boundary->regions
- `17869950` - Add: Script to compile Util dlls

What changed in this period:
- the GA optimization engine was ported into the repository
- the GA API wrapper was formalized
- the boundary-to-regions converter was added to the API layer
- the build flow for native utility DLLs was added

Files that mattered most:
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py)
- [Space_Optimization/boundary_utils.py](../Space_Optimization/boundary_utils.py)
- [build_dlls.py](../build_dlls.py)

## Phase 10: January 2026 - API Docs, DLL Imports, and Link Cleanup

Representative commits:
- `e48f9147` - Update:dll imports + DOCS
- `86ed6aa7` - Create api_flow_and_translation.md
- `36095b33` - Update ga_optimization_api.md
- `d787cae6` - Update API link for space optimization
- `edb80444` - Fix GA Optimization API link
- `2bd1a65d` - Update:ga_config
- `07c0e8d1` - Fix URL formatting in space optimization API docs
- `db543c39` - Update ga_optimization_api.md
- `26c60024` / `91f9558f` - Update: API links in docs

What changed in this period:
- the repo started codifying the workflow in documentation
- DLL imports were adjusted for the space/GA engine path
- API documentation links were cleaned up so the docs could be used as a handover reference

Files that mattered most:
- [documentation/README.md](README.md)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py)

## Phase 11: February-April 2026 - Maintenance, Edge Cases, and Final Tuning

Representative commits:
- `c795ea20` - Add: Max workers in circulation API
- `d4f092fd` - Update: PTPG in output of door_connectivity API
- `efc8a620` - Update: Use SerialExec when workers == 1
- `33b53987` - Update: Use SerialExec when workers == 1
- `e7259964` - Fix:2 Node edge case in door_connectivity
- `ad2df400` - Fix: separating_Triangle removal bug
- `62415bdf` - Fix:Handle degenerate faces and fallback layout
- `57578968` - Update:space optimization api
- `235bd1d2` - Increase overlap penalty; update room name docs
- `c30f517e` - Update: Space optimization API
- `4a20dc07` - Optimal_integration initial

What changed in this period:
- the code focused on robustness rather than introducing brand-new subsystems
- door connectivity got better output and more defensive edge-case handling
- GA/space optimization were tuned and the API contracts were refined
- docs and runtime behavior were kept in sync with the implementation

Files that mattered most:
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [Space_Optimization/ga_current.py](../Space_Optimization/ga_current.py)
- [documentation/README.md](README.md)

## Current Takeaway

The project evolved from a door-connectivity and minimum-dimensioning codebase into a multi-mode floorplan platform with:
- legacy graph floorplan generation
- non-adjacency handling
- circulation-aware and boundary-aware door connectivity
- space optimization from boundary or region input
- GA-based corridor optimization
- API and test wrappers around all of the above

If you are trying to understand why a file exists, this timeline is the shortest path from the current code to the original reason it was added.
