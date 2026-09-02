# Fixed rooms and rectilinear boundaries

Status: research roadmap, with exact rectangular corner-anchored rooms and the
housing south-west staircase milestone implemented in `door_connectivity`.

## Agreed direction (2026-09-02)

- The default staircase anchor is `SW` for now.
- The initial public fixed-space API uses named boundary anchors. Arbitrary
  absolute `x`/`y` placement is deferred until the anchored contract is stable.
- Orthogonal plot polygons will be represented and constrained directly in the
  global solver. Rectangular macro-decomposition is not the primary generation
  strategy.
- Exact boundary coverage, fixed-space invariance, and access remain hard
  acceptance conditions; fallbacks must not relax them.

## Why fixed rooms are a separate constraint class

A fixed staircase is occupied plan space with an access requirement. It is not
an ordinary room-size preference and it is not a void. Its geometry must remain
unchanged through topology selection, dimension solving, fallback relaxation,
rotation, gap closing, repair, and post-processing.

Sending `width.min == width.max` and `height.min == height.max` on an ordinary
node is insufficient:

- the minimum-dimension solver normally widens maxima to at least
  `SOLVER_UB_SLACK * minimum`;
- the fallback ladder may remove ordinary maxima;
- ordinary cardinal constraints may be ignored by the last fallback;
- cardinal exposure does not by itself mean an absolute plot coordinate;
- rectangularization and exact-fill post-processing may grow or repair rooms;
- whole-plan rotation swaps the fixed axes.

The implemented `is_fixed` contract bypasses those relaxation points, disables
rotation, treats the node as locked during gap fill, and validates the result
again after rectangularization and post-processing. All side and corner presets
(`N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`) are supported. `NW` means absolute
`left = 0`, `top = 0`; `SW` means `left = 0`, `bottom = plot height` in the
normalized plot frame, in addition to direct boundary contact.

## Yield: why a corner stair produced 3 plans and how that was fixed (2026-09-02)

The `is_fixed` contract rejects every topology that cannot land the room
exactly, so yield depends on the topologies offered. Measured on the housing
2BHK (8 rooms, 12 edges, 30 x 40 ft, 7 x 10 ft stair anchored SW): 208
topologies dimensioned, 0 anchored; the engine fell back to a spanning tree
(196 topologies, 2 anchored) and returned 3 plans with adjacencies dropped.
Two causes, both in `api.py`:

1. `build_cardinal_ring` returned None for the full brief (its DFS-preorder
   family missed both valid orders), so no ring was applied and the stair's
   boundary neighbour came from biconnectivity augmentation: a bedroom, whose
   11 ft minimum cannot share the stair's 10 ft row in any rectangular tiling.
   The ring search is now exhaustive for briefs up to 12 rooms and ranks
   orders by the fixed room's neighbour compatibility (the Kitchen, 8-13 ft
   tall, beside the stair; the Living Room, its door host, above).
2. The min-dim placement leaves a locked room recessed from its edge (it
   aligns rooms to shared interior walls and leaves the outer strip to the gap
   fill, which may not grow a lock). `rectangularize_output` now translates
   the lock onto its anchored edges first; the vacated strip closes normally.

With both, the same brief returns 24 plans on the first attempt, every
adjacency kept, every stair exact in the plot corner, in 4 s instead of 12.
The expand / top-up paths are skipped when fixed rooms exist: scaled plans
can never pass the fixed gate.

## Progressive fixed-room yield (2026-09-02)

The fixed-room route is the first engine path that can publish plans before
the complete topology pool has finished. A preserved frontend-through-bridge
probe was run before this behavior changed: the housing 2BHK, 30 x 40 ft plot,
south-west 7 x 10 ft stair, and a request for 60 returned 24 terminal plans in
4.68 s; housing kept its existing eight-plan window. Every kept plan was
30 x 40 ft and the stair remained at `(0, 30)`, size 7 x 10 ft. The live bridge
fingerprint was `st-51004ac98ebe9b4a`.

`Documents.get_floorplans(..., progress_callback=callable)` now exposes
bounded, final-style JSON previews on that route. The handler reports a solved
candidate and its normal terminal sort key, but the API never exposes that
internal graph. It deep-copies selected candidates and runs each copy through
the same rectangular, anchored fixed-room, cardinal, postprocess, and
exact-fill acceptance gates used by the terminal result. It publishes the
first valid plan, refreshes at four, and stops progress-only finalization once
the preview contains eight. Results are cached so no candidate is finalized
twice solely for progress.

Every preview carries `provisional: true`. It is a replacement snapshot, not
an append-only promise: a later topology may rank ahead of, reorder, or evict a
preview plan. That trade is explicit because proving immutable terminal
membership required finishing nearly the whole topology pool and made the
first partial slower than the old terminal result. Every plan is nevertheless
geometrically valid at emission; the terminal batch and ordering are unchanged
and authoritative.

The captured housing 2BHK automated test fingerprints every preview geometry
against its terminal batch, verifies the 30 x 40 ft frame and south-west stair
on every snapshot, and reruns the request without a callback to prove terminal
plan selection and ordering are unchanged. That fixture currently retains all
preview geometries, but callers must follow the general provisional contract.
Callback exceptions are injected in the same test and may not fail generation.

Post-change local measurements on the captured request: direct warmed calls
finished in 4.860 s with the callback and 4.375 s without it (11.1% overhead),
with callback milestones at 0.704 s for one plan and 1.860 s for eight. A real
Flask test-client poll every 0.5 s observed one plan at 1.05 s, eight at 2.09 s,
and the unchanged 24-plan success at 6.28 s; every observed preview passed the
7 x 10 ft south-west stair check. Absolute cold timings vary, so the paired
same-process comparison is the overhead measurement.

## Hard geometric invariant

Let `P` be the plot, `F` fixed occupied spaces, `V` reserved voids, and `M`
generated rooms. Exact-partition mode requires:

```text
union(M) union(F) = P minus V
```

All interiors must be pairwise disjoint. Every returned plan must also satisfy:

- fixed-wall error within the declared numeric tolerance;
- zero overlap and outside area;
- zero uncovered area in exact-partition mode;
- required shared-wall length at least the door-width threshold;
- entrance-to-stair reachability;
- stable fixed-space IDs and an explicit coordinate frame;
- no silent relaxation of fixed geometry, boundary, or fixed access.

## Ranked algorithm options

| Approach | Fixed geometry | Orthogonal boundary | Exact partition | Current-code reuse | Assessment |
| --- | --- | --- | --- | --- | --- |
| Partial rectangular-dual extension with hard wall constraints | Strong | Rectangle first | Strong | Very high | Recommended foundation |
| Fixed pseudo-void rectangles in a bounding-box dual | Strong | Promising | Strong when feasible | High | Best graph-engine extension experiment |
| Polygon macro-decomposition plus stitched subplans | Strong | Good | Possible | Medium-high | Pragmatic middle route |
| Cell exact-cover / CP-SAT or MIP | Strong | Excellent | Strong | Medium | Best general research target |
| Existing `negNew` packing | Anchored | Supported | No | Already present | Baseline only |
| Post-hoc wall pushing around an overlay | Fragile | Limited | Fragile | Superficially high | Do not use as the generator |

### 1. Partial rectangular-dual extension

For each candidate regular edge labeling, use four wall variables per room and
add hard equalities for selected fixed rectangles. Horizontal and vertical
constraints remain difference constraints, matching the existing
minimum-dimension implementation. N/E/S/W pins are useful topology filters,
but absolute wall equations or an equivalent hard acceptance gate define the
geometry.

This is the closest extension to the current engine and should remain the
foundation for rectangular plots. The tradeoff is lower topology yield: an
infeasible labeling must be rejected, never rescued by unlocking the core.

### 2. Bounding-box dual with fixed pseudo-voids

Embed an orthogonal plot in its bounding rectangle, decompose
`bbox(P) minus P` into fixed rectangular void nodes, and generate one dual
containing real rooms, occupied fixed spaces, and void rectangles. Remove void
nodes only when serializing the finished plan.

This could reuse the fixed-wall solver for L/T/U/notched boundaries. Its main
research questions are how to choose the void decomposition and contact graph,
and how to avoid topology explosion or forbidden four-way contacts.

### 3. Macro-decomposition and stitching

Partition the free domain into useful macro-rectangles, assign room groups to
the region-adjacency graph, run the existing rectangular generator per region,
and stitch the results at explicit portal walls. The coordinate-cell machinery
in `Space_Optimization/boundary_utils.py` is reusable preprocessing, although
its greedy merge objective should be replaced or augmented with cut-length and
minimum-thickness quality terms.

This route is easier to debug and is natural for the L-shaped free area around
a corner stair. A poor early cut can nevertheless hide a feasible solution,
and cross-seam adjacencies need deliberate portal assignment.

### 4. Cell exact-cover / MIP

Build an orthogonal arrangement from plot, core, and selected dimension lines.
Enumerate feasible room rectangles and solve:

- exactly one candidate per room;
- every free cell covered exactly once;
- no overlap;
- fixed candidates preselected;
- shared-edge variables for adjacency and door length;
- size, area, aspect, exterior, and non-adjacency rules.

This gives the strongest general guarantees for arbitrary orthogonal plots and
obstacles. Candidate explosion is the primary risk; pruning, coarse-to-fine
grids, column generation, or decomposition will be required for larger briefs.
SciPy/HiGHS can support an initial MIP experiment without a new solver family.

### 5. Existing `negNew` path

`Space_Optimization/negNew.py` already anchors fixed rooms and accepts polygon
boundaries. It is a useful feasibility demo and benchmark, but it is stochastic
packing: it may leave gaps and does not guarantee all requested adjacencies or
an exact partition. It should not replace the graph engine for production
floorplans without a separate exact validator.

## Recommended experiments

1. Keep an independent geometry validator as the final authority: fixed
   coordinates, coverage, overlap, outside area, shared-wall lengths, access,
   and stable IDs.
2. Continue adversarial infeasibility coverage for all side/corner presets. A
   fixed constraint must produce fewer/no plans, never an invalid fallback.
3. Add an interior lift, stair plus lift, and a shared `stack_id` across floors.
4. Benchmark pseudo-void duals, macro-decomposition, cell MIP, and `negNew` on
   L, T, U, Z, narrow-neck, multi-notch, and interior-hole plots.
5. Record per-strategy feasibility yield, topology/candidate counts, median and
   p95 runtime, timeout rate, fixed-wall error, uncovered/overlap area,
   adjacency recall, door shortfalls, sliver score, and topology diversity.

Useful structured failures include `FIXED_OUTSIDE_BOUNDARY`, `FIXED_OVERLAP`,
`NO_TOPOLOGY_WITH_HARD_CONTACTS`, `DIMENSION_INFEASIBLE`,
`ACCESS_INFEASIBLE`, `COVERAGE_INFEASIBLE`, and `TIMEOUT`.

## Initial anchored API

The first public contract derives the fixed rectangle's absolute coordinates
from its size, the normalized plot frame, and a named boundary anchor:

```json
{
  "geometry_constraints": {
    "frame": {
      "origin": "plot_north_west",
      "x_axis": "east",
      "y_axis": "south",
      "units": "ft"
    },
    "boundary": {
      "type": "orthogonal_polygon",
      "points": [[0, 0], [30, 0], [30, 40], [0, 40]]
    },
    "fixed_spaces": [
      {
        "space_id": "stairs-1",
        "role": "circulation",
        "size": {"width": 7, "height": 10},
        "anchor": "SW",
        "stack_id": "core-a",
        "access": {
          "mode": "door",
          "one_of_space_ids": ["hall", "lobby", "corridor"]
        }
      }
    ]
  }
}
```

## Future generic API

The implemented node-level `is_fixed` contract is intentionally small. A
general boundary solver should converge on an explicit geometry block:

```json
{
  "geometry_constraints": {
    "frame": {
      "origin": "plot_north_west",
      "x_axis": "east",
      "y_axis": "south",
      "units": "ft"
    },
    "boundary": {
      "type": "orthogonal_polygon",
      "points": [[0, 0], [30, 0], [30, 40], [0, 40]]
    },
    "fixed_spaces": [
      {
        "space_id": "stairs-1",
        "role": "circulation",
        "rect": {"x": 0, "y": 0, "width": 7, "height": 10},
        "lock": ["x", "y", "width", "height"],
        "boundary_contacts": ["N", "W"],
        "stack_id": "core-a",
        "access": {
          "mode": "door",
          "one_of_space_ids": ["hall", "lobby", "corridor"]
        }
      }
    ],
    "voids": []
  },
  "generation": {
    "coverage_mode": "exact_partition",
    "strategy": "rel_extension"
  },
  "relaxation_policy": {
    "fixed_geometry": "never",
    "boundary": "never",
    "fixed_access": "never"
  }
}
```

The response should include a `constraints_report` containing fixed errors,
coverage, overlap, access, every relaxation used, and strategy/REL/seed
provenance.

## Decisions to brainstorm

1. Should a stair be an accessible circulation room or an untouchable
   obstacle? Recommendation: occupied fixed space with required access to one
   of Hall/Lobby/Corridor.
2. Should the UI expose only size plus corner presets, or a generic absolute
   rectangle? Decision for v1: named boundary anchors. A generic absolute
   rectangle remains a later API extension.
3. On infeasibility, should the core move/resize? Recommendation: never;
   return fewer/no plans with a structured reason.
4. Should the first orthogonal-boundary milestone allow L-shaped rooms?
   Recommendation: keep generated rooms rectangular initially, then add
   rectilinear rooms once exact coverage and access validation are stable.
5. Which route follows the corner milestone? Decision: add orthogonal-polygon
   constraints directly to the global solver. Pseudo-void duals,
   macro-decomposition, and cell MIP remain comparison or fallback experiments,
   not the primary implementation route.

## Research references

- Chaplick et al., [Extending Partial Representations of Rectangular Duals with Given Contact Orientations](https://arxiv.org/html/2102.02013v3)
- Eppstein et al., [Area-Universal Rectangular Layouts](https://arxiv.org/abs/0901.3924)
- Kim, Lee, and Ahn, [Rectangular Partitions of a Rectilinear Polygon](https://arxiv.org/abs/2111.01970)
- Huchette, Dey, and Vielma, [Strong mixed-integer formulations for the floor layout problem](https://arxiv.org/abs/1602.07760)
