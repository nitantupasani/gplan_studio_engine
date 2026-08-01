# Cardinal (Exterior-Facing) Constraints

Added 2026-07-15. Lets a client require that specific rooms face specific compass
directions in generated floorplans, and that the unit entrance lands on an exterior
wall on a chosen side.

**This document describes the `door_connectivity` path.** The multi-PTPG
(alternative arrangements) endpoint has its own, smaller cardinal implementation
(see [multi_ptpg_api.md](multi_ptpg_api.md) section 2) and the two are not
interchangeable: its geometric gate is y-up and adds a recess-not-void allowance
that this one does not have, so identical geometry can pass one engine's pin and
fail the other's.

Before porting anything from here to there, read
[plans/CARDINAL_CONSTRAINTS_MULTI_PTPG_PLAN.md](plans/CARDINAL_CONSTRAINTS_MULTI_PTPG_PLAN.md)
sections 1, 2 and 6. In particular the outer-ring augmentation below behaves
differently in that engine: a Hamiltonian outer cycle leaves no interior room for
a boundary-edge removal to promote, so it disables Stage 1 of the variant search,
and its ring edges must be excluded from that placer's adjacency firewall because
the placer works at exact sizes and cannot grow rooms to realize them.

## Request

`POST /api/generate/<shape>` (effective for `door_connectivity` with `count > 1`,
the production multiple/min-dim path) accepts an optional top-level field:

```json
"cardinal_constraints": [
  { "room": 2, "direction": "N" },
  { "room": 0, "direction": "S" }
]
```

- `room` — node id from `nodes` (0-based, same ids as `edges` use).
- `direction` — `"N" | "E" | "S" | "W"`. Output frame is y-down: N = smaller y
  (top of the drawing), E = larger x.
- Multiple entries per room are allowed (corner placement) but opposite pairs
  (N+S or E+W on one room) are unsatisfiable and trigger the fallback below.
- Entrances are a client-side convention: pin the room the entry opens into.

## Semantics

A constrained room is made adjacent to the corresponding exterior vertex
(N/E/S/W) during 4-completion, so its wall on that side is exterior — no other
room ever sits between it and that side of the plot. Min-dim compaction may
recess the wall slightly from the overall bounding box (a notch of outside
space); the guarantee is exterior exposure, not flush alignment.

## Priority / fallback

Cardinal constraints outrank adjacency wishes. The engine tries, in order:

1. All requested adjacencies + cardinal constraints.
2. A spanning tree of the adjacencies (fewest edges that keep rooms connected)
   + cardinal constraints. The response `message` gains
   `"Adjacency constraints were relaxed to satisfy cardinal directions."`
3. All adjacencies, cardinal constraints dropped. `message` gains
   `"Cardinal constraints could not be satisfied and were ignored."`

A response is therefore always produced if the graph itself is solvable.

Constrained attempts (1 and 2) are **verified geometrically after
generation**: `plan_satisfies_cardinal` / `filter_output_by_cardinal` in
`GPLAN/api.py` check every solved plan's room rectangles (strip test on
`final_traversal`) and keep only plans satisfying all pins, across the whole
generated catalogue — up to `count` satisfying plans are returned
(`FLOORPLAN_LIMIT` is 30). An attempt whose output contains zero satisfying
plans counts as failed and moves the ladder along, so returned plans either
all satisfy the pins or the message carries the "ignored" notice.

Note the display contract on top of this: the engine always answers, and
`gplan-building-designer` re-verifies every returned plan geometrically
(strip-intersection per pinned room, `planSatisfiesCardinal` in
`src/features/cardinal.ts`). When any plan satisfies the pins, only
satisfying plans are shown. When none do (step-3 ladder fallback, or a
backend that ignores the field), the designer degrades to the previous
method: the generated plans are shown with a ⚠ warning note naming the cause
instead of failing with no output. An error is raised only when the engine
returned nothing usable at all.

## Interactions

- The min-dim **rotation pass** (`rotation_enabled`) is disabled when cardinal
  constraints are present (it would rotate rooms off their side).
- The one-connected exact construction is bypassed in favour of
  `irreg_multiple_dual`, which owns the boundary filter.
- The search is **exhaustive** (2026-07-18): the dimension-fit boundary
  selector (`dim_on_paths_bdy`) is skipped entirely under cardinal
  constraints — it both narrowed the candidate space and rearranged the four
  boundary paths (scrambling the N/E/S/W assignment; originally mitigated by
  re-filtering its output, 2026-07-15). Instead every cardinal-satisfying
  boundary is constructed, every REL of each boundary is enumerated (full
  flip-graph), and the per-boundary min-dim cap (`floorplan_per_bdy_limit`)
  is lifted to the global `floorplan_limit` (500). Dimension fit is enforced
  by the min-dim solver per candidate; direction is enforced by the geometric
  post-check. Worst-case runtime grows with the catalogue — the global
  500-candidate ceiling keeps it bounded.
- Results are cached per payload as usual; the field participates in the
  cache key.

## Engine internals

`InputGraph.cardinal_constraints` (list of `(node, dir_idx)`, 0..3 = N,E,S,W) →
`filter_boundaries_by_cardinal` in `source/inputgraph.py` tries all **8
symmetries** (4 rotations × 2 reflections) of every boundary candidate from
`generate_multiple_bdy` and keeps the orientations that put each pinned room
on its required path. Reflection is essential, not an optimization: the
boundary enumeration walks the outer cycle in one direction only, so pin
combinations whose cyclic order matches the mirror orientation (e.g. E, N, W
in clockwise order) are satisfiable **only** by the reflected boundary —
before 2026-07-18 those requests always fell through to the "ignored" ladder
rung. Ladder + normalization live in `GPLAN/api.py`
(`normalize_cardinal_constraints`, `spanning_tree_edges`).

### Cardinal outer-ring augmentation (2026-07-18, evening)

The 8-symmetry filter can only reorient boundaries that exist — but which
rooms CAN appear on a boundary at all is fixed earlier, by the planar
embedding chosen during augmentation. For sparse inputs (not biconnected —
the designer's normal case: unit graphs are usually forests, sometimes
disconnected), `door_connectivity()` biconnects with `bcn.biconnect` and
embeds with `nx.planar_layout`, neither of which knows about the pins. A
pinned room could land interior in **every** enumerated boundary
(`filter_boundaries_by_cardinal` then returns zero candidates for every
ptpg-matrix), and since sparse graphs are forests the spanning-tree
relaxation rung is a no-op — the ladder went straight to "ignored" no matter
what. Observed on the 13-room 4BHK designer unit with Kitchen→N: Kitchen was
on the outer boundary in 0 of 106 candidates.

Fix: `build_cardinal_ring` / `apply_cardinal_ring` in `GPLAN/api.py`, applied
before `handle_door_connectivity` whenever pins are present (and on the
constrained ladder retry). It adds a Hamiltonian outer cycle through all
rooms, ordered so pinned rooms sit contiguously per direction in N,E,S,W
cyclic order (corner pins — one room, two adjacent directions — at their two
groups' interface), with circle coordinates realizing the cycle as a planar
straight-line drawing: components and subtrees follow DFS preorder, so tree
edges are non-crossing chords. The ring makes the graph biconnected, so the
engine skips `bcn.biconnect`/`planar_layout` and keeps this embedding — the
outer boundary IS the ring and every pin is boundary-capable by
construction. Ring edges go into the adjacency **matrix only** (engine
augmentation, same status as bcn edges): no doors are placed on them and the
user edge list is untouched. The builder returns None — old pipeline,
unchanged behavior — for opposite-direction pins, three-plus-direction pins,
non-adjacency requests, ordering conflicts (a pin ordering the tree structure
cannot realize), or crossing chords (dense/biconnected inputs, which the old
path already handles: T8 passes pre-ring). Verifier: `_ring_order_satisfies`
checks the cyclic order against all 8 symmetries the downstream filter can
accept. Effect on the failing unit: 0 → 11/11 satisfying plans, 302s → 8.6s
(the aimed boundaries also dimension much faster than the 500-candidate
unconstrained sweep).

## Gapless rectangular outlines

`rectangularize_output` in `GPLAN/api.py` (2026-07-18): every
door-connectivity multiple-generation plan is post-processed so the floorplan
fills its bounding rectangle with no empty spaces. Rooms must all be
rectangles (plans with merged/irregular rooms are dropped); boundary notches
and holes left by min-dim recessing or deleted dummy rooms are healed by
greedy wall extension (each room's sides push outward to the nearest
obstruction until fixpoint); plans that still fail exact coverage (room areas
summing to the bounds area) are dropped. Under cardinal constraints the fill
runs BEFORE the geometric pin check, so pins are verified against the final
geometry. If the gate would empty a non-cardinal batch, the ungated plans are
returned with the note `"Some floorplans have a non-rectangular outline."`
rather than nothing. The designer applies the same coverage test client-side
(`isRectangularArrangement` in `gplanApi.ts`).

Prior art: the deprecated LP dimensioning flow (`dimensioned` flag →
`floorplan_to_st.py` → `solve_linear.py`) is gapless by construction — it
solves the dissection's widths/heights and repacks coordinates — but it is
not used by the production door-connectivity min-dim path (door-overlap
constraints only exist in the wall-based solver) and it too leaves holes
where augmentation dummy rooms are deleted, so the serialization-level fill
above is needed regardless of dimensioning mode.

## One-connected graphs: stacked composition

`stacked_oneconnected_floorplans` in `GPLAN/api.py` (2026-07-18). When the
input graph is exactly two biconnected components sharing one cut vertex
(two wings joined by a hall), floorplans are composed instead of augmented:
each component's plans are generated through the full pipeline with the
cut-vertex room pinned to the seam side via the cardinal machinery (E|W for a
horizontal stack, S|N for vertical, both orders tried), the second component
is scaled so the cut-room spans match, and the plans are fused into one whose
cut room spans the seam. Composites are kept only when no rooms overlap and
every user pin passes the geometric strip test. Falls back silently to the
normal biconnectivity-augmentation path when the topology doesn't fit
(≠2 components, >1 cut vertex, duplicate room labels, red edges) or nothing
valid composes — a 2-node component (pendant room) currently yields no
component plans, so such graphs keep the old path. The response message gains
`"One-connected graph composed as two stacked component duals joined at
'<room>'."`

Context: `oneconnected_dual` (the legacy exact rectangular path) applies ONLY
to 1-connected inputs — it raises `BCNError` immediately on any biconnected
graph — and inside door_connectivity it can never succeed at the point it
was called, because `door_connectivity()` has already augmented the graph to
biconnected. For a biconnected PTPG, `irreg_multiple_dual` IS the rectangular
generator: with no dummy vertices its output duals are exact rectangular
floorplans.

## Local testing

`python GPLAN/local_engine_bridge.py` serves `/api/generate/<shape>` +
`/api/task/<id>/` from the local engine (no Django/Redis/Celery); pair with
`GPLAN_LOCAL_ENGINE=1 npm run dev` in `gplan-building-designer`.
