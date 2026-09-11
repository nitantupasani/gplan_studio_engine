# Circulation research and implementation decision

Date: 2026-09-10. Scope: existing housing and unit floorplans. This report distinguishes source inspection, independent experiments and the headless service implementation. The registry and production tests are authoritative for shipped modes; this directory contains the research evidence. Corridors are **wall-free circulation surfaces**, with access through adjacent room walls handled separately.

## Decision: retain shrinking, make the intended gaps explicit

Keep rectangular room boundary shifting as the first geometry strategy. Derive the corridor from the area deliberately removed from the original rooms, with selected wall-run and changed-side provenance. Preserve the original envelope and unrelated open space. This supplies a useful headless strategy without rebuilding a PTPG, regenerating rooms or introducing notches.

Extend the legacy shifting approach by grouping contiguous collinear contacts into wall runs. All segments in one run share coordinated offsets; every changed room side must be covered by the authorized run. This supports rectangular tilings and T contacts where a full side of one room meets multiple neighboring rooms. Independent per-contact offsets are insufficient: the `asymmetric_seam` fixture makes a topologically connected surface whose neck is only 1.2 ft wide for a requested 3 ft corridor. Coordinated run offsets prevent this failure before independent physical validation.

Reject dangling partial contacts, unhandled irregular rooms, unsupported entry locations and infeasible protected-room constraints with explicit reasons. A separate local-carving strategy is justified only if support for those geometries is required: cutting just part of a side requires notched room polygons, stronger minimum-clearance/shape rules and asset reconciliation. Do not silently convert those plans to rectangular PTPG input. The current implementation should expose its capability boundary, not claim a general polygon router.

| Strategy | What it preserves | Evidence and limitations | Decision |
| --- | --- | --- | --- |
| Legacy whole-side shifts, equal half width, implicit gaps | Room rectangles and original graph convention | No explicit saved corridor; pruning can disconnect; no protected-area policy; GUI coupling | Retain geometric idea, not the unvalidated execution path |
| Coordinated whole-side shifts plus derived gap geometry | Stable room identity, rectangles, fixed envelope and unmodified unrelated open space | Works on complete rectangular contacts and supported T partitions; requires global dimension/area checks and finite-width validation | Primary strategy |
| Local polygon carving | More precise partial-wall use and fewer unnecessary full-side losses | Changes room topology; corners/holes/doors/furniture become materially harder; needs separate constraints and tests | Explicit future strategy; not an implicit fallback |

The corridor source of truth is `union(original eligible room footprints) minus union(adjusted eligible room footprints)`, checked against the changed-side/run provenance. This formula is safe only if all losses are deliberate and the service prohibits room expansion/relocation. If a future adapter allows either, use per-room removed polygons and independently verify gain/loss accounting. The envelope-minus-rooms remainder is not a corridor: the provenance fixture has 30 sq ft of intended corridor and 500 sq ft of unrelated open space; the naive remainder incorrectly labels 530 sq ft.

## Compared sources and ownership

Immutable upstream objects were read using `git show` without changing checkouts. Web access to these repository pages was unavailable, so the Git objects, source hashes in `EXPERIMENT_RESULTS.json` and reproduction command are the evidence for source-specific findings.

| Implementation | Entry point and callers | Algorithm/output | Status |
| --- | --- | --- | --- |
| Local `GPLAN/circulation.py` | `handlers.py` imports `GPLAN.circulation`; `handle_circulation` / `call_circulation_new` | PTPG triangular-face traversal, corridor tree, rectangular side shifts | Live legacy GUI path; existing API flags do not make the GUI path headless |
| [Team main, 409e61e](https://github.com/GPLAN-team/GPLAN/blob/409e61ee57fd56757c085574554ebe57db247879/circulation.py) | Historical `main.py` / Tk GUI | Same spanning core; one greedy coverage pass; ordinary and minimum-dimension checks | Comparison source, not a replacement branch |
| [Circulation_paper, 2286259](https://github.com/GPLAN-team/GPLAN/blob/2286259b1cce1a40e47c56ee3bf0945570aa2af1/circulation.py) | Historical GUI, numeric room entry IDs | Same spanning core; candidate-restricted second greedy pass; south/top offset correction | Useful small fixes; lacks main's minimum-dimension circulation support |
| `GPLAN/source/circulation/circulation.py` | No live package callers found | Older spanning class, fixed thickness and experimental recursive alternatives | Historical duplicate; do not add a competing public service here |
| `GPLAN/source/multiple_circ.py` | No live package callers; bare `import circulation` | Experimental alternative traversal enumeration | Broken state/queue ownership, missing initialized fields and interactive entry logic; unsuitable for production enumeration |
| `Space_Optimization/corridor_creator.c` | `ga_current.py` ctypes wrapper and GA handler | Marks existing integer-grid empty gaps as corridor cells | Placement/GA helper, not constrained corridor generation on the existing exact plan |
| `Space_Optimization/bfs.c` | GA connectivity metric | Counts 4-connected components of corridor cells | Useful raster component metric; no continuous-width or doorway guarantee |
| `Space_Optimization/boundary_accessible_corridors.c` | GA boundary-access metric | Counts grid corridor contacts with boundary or boundary-reachable empty cells | Entry exposure score; does not validate a selected entry or all rooms |
| `Space_Optimization/corridor.c` and `.h` | No applicable caller | Empty source files | Stub, not an algorithm |
| New `GPLAN/circulation_engine/` | Single headless generation service and registry | Floorplan geometry to wall-run graph to constrained shifts to validated surfaces | Production owner; see `CAPABILITIES.md` and registry |

Source dossiers remain useful historical detail: [graph](../graph/circulation-root-graph.md), [geometry](../graph/circulation-root-geometry.md), [duplicate package](../graph/circulation-source-package.md), [C helpers](../dim/dim-14-ga-corridors-c.md). Their old absolute line numbers and library versions are not current contracts.

## Runtime findings and legacy defects

`run_experiments.py` executes class definitions extracted from local and both immutable upstream sources through Python AST. It deliberately excludes GUI/module imports, plotting and interactive entry points. It runs the actual `circulation_algorithm`, `remove_redundant_corridors`, `min_tree_set_cover` and `calculate_edge_move` methods, not rewritten approximations of those methods. The geometry/allocation experiments are independent mathematical fixtures, not the production solver's acceptance tests.

1. On `networkx.wheel_graph(n)` for n=5 through 12, entry `(2,3)` in the legacy one-indexed convention produces connected corridor trees in all three sources. These are abstract graph results; they do not prove physical corridor geometry or room access.
2. Actual local/main/paper pruning creates 2 components for n=6 through 8, 3 for n=9 through 11, and 4 for n=12, counting the entry corridor. Paper's repeated greedy pass does not fix this. All variants leave the explicit path-reconnection block commented out. A simple fixture also shows complete room coverage with disconnected selected corridors.
3. `min_tree_set_cover` is greedy coverage, not minimum length, minimum area, exact set cover or a connectivity algorithm. It also lacks a progress guard when remaining rooms have no candidate cover. Use explicit infeasible returns rather than a non-progressing loop.
4. Entry corridor vertex `m` is omitted from widening. Paper permits that candidate in its coverage pass, while its geometry still skips it. Access cannot be inferred from this abstract vertex; an actual entry portal and physical continuation are required.
5. The baseline local/main southward top-edge calculation uses `rel_push_L` where it should use `rel_push_T`. With corridor width 2, previous top movement -0.25 and unrelated left movement -3, original local/main choose -3 while paper chooses -1. The live local file now includes that small correction; the runner requires -1 locally and still reproduces -3 from immutable team main. This is not a reason to import the whole paper branch.
6. Legacy minimum-dimension validation allows `minimum - corridor_thickness`. New service constraints must test actual post-circulation dimensions against the actual minimum with numerical tolerance only.
7. Experimental alternative code aliases mutable queues (`queue1 = queue`, `queue2 = queue`) and builds one de-duplicated queue using the other queue's membership. It should not be used as evidence of valid independent alternatives.
8. The C scanner is orientation asymmetric: horizontal gaps qualify at `gap_len >= 2`, while vertical gaps additionally require `gap_len <= corridor_width`. It marks empty cells and does not allocate room area. Its connectivity and boundary counts are optimization scores, not hard geometric guarantees. No native library is required by the recommended headless strategy.

## Route objectives and exactness

Separate route, coverage and contribution policy. A spanning network can serve all rooms or a specified subset; changing coverage alone is not a different route algorithm. Dedupe identical physical outcomes before presenting options.

- **Spanning circulation**: entry-rooted deterministic traversal of the supported contact/run graph. The accepted result must serve every requested room. There is no shortest or area-minimal claim.
- **Compact circulation**: a connected coverage heuristic, such as incremental shortest connection plus removal of redundant leaves while retaining entry reachability and requested access. Reconnect every selected node to the entry on the original tree before geometric validation if starting from legacy pruning. Connectivity by construction does not imply finite physical width.
- **Shortest route, one destination**: exact graph shortest path using fixed nonnegative costs and an explicit destination set of feasible access nodes. A sentinel target with zero-cost connections can express multiple possible contacts for the one room. Dijkstra then minimizes cost on that declared fixed graph; it does not establish a shortest path through arbitrary polygon space. [NetworkX shortest-path documentation](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.shortest_path.html)
- **Shortest alternatives**: Yen's loopless path enumeration produces paths in increasing cost order; bound enumeration by count and wall-clock deadline. If the shortest graph route fails global allocation/geometry constraints, the first subsequently feasible enumerated route is shortest feasible only when all lower-cost paths were examined under the same fixed costs and the requested objective. If search stops earlier, label the best feasible result **shortest found**, state the bound, and do not silently return a compact result under a shortest title. [NetworkX `shortest_simple_paths`](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.simple_paths.shortest_simple_paths.html)
- **All-room/selected-room minimum network**: unioning shortest paths from entry is connected but can use more total network than sharing a longer trunk. A Steiner approximation is a potential compact heuristic for fixed terminal contacts, not a global all-room shortest solution. Rooms with alternative access nodes introduce grouped-terminal choice; do not transfer a fixed-terminal approximation factor without proving the reduction. [NetworkX Steiner approximation](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.approximation.steinertree.steiner_tree.html)

Whole-side shifting creates complete selected wall runs, even if a walking path uses only part of a run. Exact routing cost must therefore be explicit: minimum sum of selected run lengths can use node-cost shortest path, while center-to-center travel distance is a different objective. Report actual final centerline/run length separately. Allocation can move centerlines and change physical travel length; exactness on original fixed run costs does not transfer automatically to final walking distance or corridor area.

Exact graph Steiner algorithms exist, including improved subset dynamic programming, but adding one would still not solve geometry-dependent allocation and grouped room-access choices automatically. This delivery should prefer honest compact/shortest-found labels over an unimplemented global optimum claim. [Hougardy, Silvanus and Vygen, 2015](https://arxiv.org/abs/1406.0492)

## Allocation policies and actual area

For one full shared wall with equal affected lengths, the total-area preference gives offsets `dA = width * areaA/(areaA+areaB)`, `dB = width-dA`. Caps redistribute demand to the other room; reject if both feasible caps cannot supply the width. Locked or explicitly protected rooms have zero allowance. The **larger adjacent room contributes more where feasible** remains the default preference, subordinate to all hard constraints.

| Policy | Desired distribution | Strength | Limitation |
| --- | --- | --- | --- |
| Larger rooms contribute more, default | Actual contributed areas follow original room-area weights | Matches the user's preference; stable under edits | A larger narrow room may have little feasible side movement; exceptions need disclosure |
| Available area | Weights use `max(0, originalArea - minArea)` | Uses genuine area surplus before approaching room minimums | Area surplus alone does not establish side-width, aspect or door feasibility |
| Equal sharing | Equal actual area contributions where feasible | Useful neutral comparison | Equal offsets are equal area only when effective affected lengths match |
| Protected-room preferences | Hard zero for locked/protected rooms, chosen weighting among remaining contributors | Preserves specified rooms without relaxing width | Both sides protected can make a route infeasible |

Offset weights and actual area weights differ at partial contacts. A 20x20 room (area 400) beside a 10x10 room (area 100) shares only 10 ft of the large room's 20 ft edge. A width-3 split 2.4/0.6 removes **48/6 sq ft** with rectangular shifts, not the intended 4:1 ratio. For those full edges an area-corrected split 2/1 removes **40/10 sq ft**, but 20 sq ft lies beyond the selected short contact. That extra strip needs complete run provenance and width/access checks; dropping it from the rendered corridor would create unexplained area loss. A local notch using 2.4/0.6 would remove **24/6 sq ft**, and is a distinct geometry strategy.

For unequal effective lengths `LA, LB`, actual area targets require `dA/dB = weightA*LB/(weightB*LA)` before caps. A run containing several rooms needs aggregate side contributions and per-room constraints. At intersecting runs, one room loses `H*dX + W*dY - dX*dY`, not the sum of uncorrected strips. Evaluate final polygon area once per stable room and retain exact before/after reporting. A preference objective over those actual losses can be optimized subject to hard room caps; a feasible imperfect preference wins over an infeasible ideal ratio. Never imply a nonlinear local optimizer proves global allocation optimality.

Room constraints cover actual remaining width, height, area, aspect ratio, locked room geometry, obstacle/core overlap, entry/access length and affected assets. Reuse original minima; never subtract the requested corridor width from them. Treat units as request data and convert once at adapters, with area converted quadratically.

## Physical validation, provenance and persistence

Validate polygon validity, room/corridor non-overlap, envelope/holes/obstacles, per-room constraints and exact area accounting independently from route selection. Derive the union before measuring it: two crossing 3-by-20 strips have area 111 sq ft, not 120, because their 9 sq ft junction is counted once. Geometric Boolean operations and negative buffers provide the operations needed for these checks. Shapely's `minimum_clearance` is the perturbation distance to invalid geometry; it is not a corridor-width measurement. [Shapely manual](https://shapely.readthedocs.io/en/stable/manual.html)

Graph connectivity and polygon connectivity are necessary but insufficient. For the supported orthogonal model, erode the corridor by half the required width with explicit corner policy and tiny numerical tolerance, then require reachable route/portal witnesses in the same component. Check every required branch/access witness: a too-narrow dead branch can disappear during erosion while the remaining polygon stays connected. Entry and doorway caps require inward witnesses or an explicitly controlled portal extension; erosion retracts polygon ends. This finite-width model is a geometric implementation invariant, not an assertion of building-code compliance or human turning clearance.

Each promised room needs an actual shared corridor boundary segment long enough for the required access opening and reachable from the entry. A point contact, a corner shared with a triangle apex or a route through a private room is insufficient. Doors/windows/openings crossing changed sides must be relocated consistently or rejected with a conflict. Furniture intersecting removed space needs the same treatment. Corridor branches remain open to each other; no synthetic corridor perimeter walls, doors, end caps or wall export entities are generated. Adjacent room walls and deliberate access openings retain their own ownership.

Persist explicit surfaces (or a deterministic equivalent derivation), base plan fingerprint, algorithm/version/settings, stable room IDs, changed-side/run provenance, actual area changes and the original pre-circulation state needed for replacement/undo. Candidate B must replace A from that base, not shrink A's already changed rooms again. Refuse stale responses when the plan fingerprint changes. If the user edits a plan after applying circulation, either reconcile its base/provenance under a supported edit contract or require regeneration from a new intentional base; never silently restore unrelated old edits. The research fixture proves JSON round-trip derivation and base replacement preserve the same surface, while production tests must cover frontend/API persistence and undo.

## Reproduction and evidence limits

From the workspace root:

```powershell
& 'C:\Users\nitant\AppData\Local\Programs\Python\Python311\python.exe' 'GPLAN/documentation/algorithms/circulation/run_experiments.py'
```

The runner writes [EXPERIMENT_RESULTS.json](EXPERIMENT_RESULTS.json). On 2026-09-10 it passed all 10 fixture definitions with Python 3.11.9, NetworkX 3.1 and Shapely 2.0.5, plus 24 full legacy wheel-graph runs. It requires the existing immutable upstream Git objects; it does not fetch, switch branches, use GUI libraries or compile native C. C findings are source inspection, not native runtime verification. Research fixtures are not a substitute for production engine tests, HTTP contract tests or the user's live housing/unit UI acceptance.

## Independent production review, 2026-09-11

The separately authored `GPLAN/circulation_engine/tests/test_review_cases.py` passed 10 tests, including multiple malformed/tamper subcases, after the implementation addressed the findings below. Run from the outer engine directory:

```powershell
& 'C:\Users\nitant\AppData\Local\Programs\Python\Python311\python.exe' -m unittest GPLAN.circulation_engine.tests.test_review_cases -v
```

- Runtime review initially found that even two adjacent rectangles failed entry validation: Boolean overlay left separate collinear mouth segments at the original room seam. Generation and validation now merge contiguous straight segments before measuring doorway/mouth length, while preserving bends as separate runs. Simple pairs, complete T partitions and four-room fixtures now pass.
- Validation now combines independent geometry/access checks with deterministic candidate reconstruction. Tests reject changed window kind, width or position; source/request fingerprints; algorithm metadata; per-surface provenance; metric length; and centerline width/position. Malformed request or candidate ownership/coverage/metric types produce domain errors or invalid results rather than raw type exceptions.
- A 3-ft trunk with a disappearing 1-ft dead branch carries 2.5-ft-long doorway contacts into that branch. Polygon connectivity and contact length alone pass those necessary conditions, but the independent erosion/reconstruction width check correctly rejects the candidate.
- Geometry checks independently reproduce exact room-before minus room-after surfaces while leaving unrelated open space unchanged. The 400/200-sq-ft pair contributes 40/20 sq ft under the default preference; protected rooms lose zero under all four allocation policies. A tight aspect constraint overrides the preferred ratio. Feet/metres fixtures preserve scaled bounds and quadratic area conversion.
- Twelve small positive node-cost graphs compare the production shortest mode against exhaustive enumeration of all simple entry-to-destination paths and obtain the same minimum activated-run cost. This verifies the stated fixed-graph objective, not an all-room or Euclidean optimum.

The research runner was rerun after the live legacy south/top correction and still passes all 10 fixtures and 24 wheel comparisons. The immutable team-main defect remains reproducible. These checks establish bounded engine evidence; backend integration, persistence/undo, drawing/export wall ownership and live UI acceptance are separate delivery gates.

## Existing landing reuse follow-up, 2026-09-11

A generated Dutch first floor exposed a different geometry requirement. A full-height landing separates the left bedroom wall runs from the right bathroom/stair wall runs. The supported boundary-shift graph correctly has two disconnected components: linking them through the landing interior would require an explicit public-circulation role and existing portal semantics. A selected exterior seam at the bottom of the landing/stair wall cannot establish the upper-floor stair arrival. The supported solution reuses the intentionally designated landing through its actual saved stair-to-landing opening.

The fourth registered mode, `existing`, accepts explicit `circulation_room_ids`, existing wall thickness and a saved `entry.opening_id`; an internal entry also identifies the protected stair owner with `entry.stair_room_id`. Names alone never grant public passage. It returns the actual clear-floor surface and nominal source provenance while preserving every room polygon, stable ID and saved opening. Half the interior wall thickness is removed at shared room edges and full exterior thickness lies inside the outer-face envelope. A nominal 1202 by 9500 mm landing therefore gives 1100 by 9196 mm clear floor with 102 mm interior and 152 mm exterior walls. Its 1100 mm clear width meets the requested 3.5 ft (1066.8 mm); the saved 850 mm room doors and 900 mm stair portal retain their original widths.

Reuse validates direct saved access and connected finite width, takes zero room area, and neither optimizes a route nor claims a walking length. Inherited room-size exceptions remain unchanged and disclosed. Designating two existing source rooms does not remove their separator: a saved fully open separator is required. A narrow landing, doorway conflict, incorrect stair owner, private-room shortcut, occupied hole or disconnected footprint is rejected.

The independent `GPLAN/circulation_engine/tests/test_review_existing.py` passed eight tests on the final implementation, including entry and metadata tamper subcases. These reproduce the nominal-to-clear dimensions, unchanged room geometry and openings, explicit role semantics, protected stair ownership, clear-width rejection above 1100 mm, void/obstacle exclusion, retained separating walls and candidate reproducibility. Run from the outer engine directory:

```powershell
& 'C:\Users\nitant\AppData\Local\Programs\Python\Python311\python.exe' -m unittest GPLAN.circulation_engine.tests.test_review_existing -v
```
