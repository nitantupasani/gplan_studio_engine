# NBC Post-Processing API

Post-processes dimensioned floorplans against the NBC rulebook: brings rooms
inside their aspect bands and service-room ceilings. Added 2026-07-25.

**Priority order changed 2026-08-01.** The outline is no longer the least
important property: the plot cap outranks everything, a rectangular outline
outranks the NBC ceilings, and the ceilings are enforced only as far as a
rectangle allows. Two phases were added (4: reclose the outline, 5: grow toward
the plot) and `prefer_rectangle: false` restores the old notch-accepting
behaviour. What that costs is measured in "The rectangle-vs-ceilings trade"
below; read it before flipping the default either way.

## Why this exists

The dimensioned catalogue (`door_connectivity` + `minDimEnabled`) returns
**gapless rectangular tilings**, and that gaplessness is exactly what deforms
rooms. Room areas must sum to the bounding box, so whatever slack the solver
leaves is redistributed into whichever room can reach it, and when the room
ceilings block a topology they are released rather than failing the plan. The
measured result (unit-defaults audit, 2026-07-25): bathrooms of 54x8 ft,
utilities of 9x28 ft, kitchens at 3.1x their area cap.

The post-processor moves that slack back out of the service rooms: rooms are
trimmed toward their architectural limits, and a notch in the boundary (a
recess, a light well, a setback) is an acceptable price where nothing else
reaches them. Since 2026-08-01 it is the LAST price paid, not the first: the
outline is reclosed wherever the tiling allows, and the trims that cannot be
reclosed are given back rather than shipped as notches.

## The algorithm

Three phases, pure geometry over axis-aligned room rectangles (feet, y-down
screen space, matching the `door_connectivity` wall coordinates). Implemented
in `GPLAN/source/postprocessing/postprocess.py`; NBC rule table in
`GPLAN/source/postprocessing/nbc_rules.py`.

1. **Repair (in-tile).** `api.repair_dimensions` moves the shared coordinate
   lines of the rectangular dissection, now with bounds built from the NBC
   rules and per-room aspect bands (`_axis_targets` gained an optional
   asymmetric `ar_lo <= w/h <= ar_hi` band). Gapless-preserving,
   adjacency-preserving. Rolled back if it would grow the plan footprint more
   than `max_bbox_growth` (3% per axis by default): NBC minimum floors must
   rebalance the tiling, not balloon it.

2. **Trim (exterior).** A room still past its ceilings or aspect band is
   trimmed inward from a **fully exterior side**: the entire strip from that
   side to the plan bounding box must be empty, so every notch created is
   connected to the outside and interior holes are impossible by
   construction. Requested adjacencies (doors) are inviolable: every
   protected pair keeps at least `min_door_overlap` (2 ft, the solver's own
   black-edge constant) of shared wall, and a trim that would break one is
   capped or skipped. NBC and user minimums are floors. An area violation is
   fixed on whichever axis has an exterior side available.

3. **Absorb (capped).** Rooms grow back into the notches, ordered by
   remaining headroom, but never past their own span/area ceilings or aspect
   band. This is the capped twin of `api._fill_gaps`; the uncapped pass that
   produced the original inflation is never run. Trim and absorb alternate up
   to `max_passes` times.

4. **Close (rectangle preference, 2026-08-01).** A plan that came in gapless
   and would leave notched climbs a ladder: (a) capped absorption; (b) one
   absorption round with the span and area ceilings widened by
   `notch_close_slack`, the aspect band still hard, kept only if the outline
   actually closes; (c) the trims are redone from the repaired tiling keeping
   only the ones a neighbour can absorb, so the outline stays a rectangle and
   the reclaimable slack still moves from the bathroom into the living room.
   Rooms left past their ceiling by that trade are named in
   `over_ceiling_rooms` and in the plan note. `prefer_rectangle: false` skips
   the whole phase.

5. **Fill (plot preference, 2026-08-01).** A gapless plan smaller than
   `target_width` x `target_height` grows toward it by advancing WHOLE boundary
   sides, each by the smallest headroom the rooms on that side have inside
   their own ceilings, so the outline stays a rectangle and no room passes its
   cap. One room at its ceiling pins its whole side; that is the intended
   reading of "fill the plot within the constraints". Never shrinks.

`plot_width`/`plot_height` are a HARD cap on every phase above: no phase may
push the bounding box outside the plot, and a plan that already overflows it
(the engine's expand fallback) is capped at its own extent rather than cut into
its room minimums.

Every phase is validated afterwards (no overlaps, no interior holes, doors
kept, footprint growth bounded, plot cap respected, all rooms still mutually
reachable through shared walls); a phase that breaks an invariant is rolled
back for that plan and noted in the report. A trim+absorb round whose residual
notches exceed `max_notch_ratio` of the bounding box also rolls back.

The whole sequence then faces ONE gate: no room may regress on any rulebook
dimension and the plan score may not worsen, else every change is reverted.
The gate moved AFTER phases 4 and 5 in the same change, because reverting the
trims for the rectangle changes what the gate is judging.

### The rectangle-vs-ceilings trade

They are not both achievable. A gapless tiling forces the bounding box's slack
into some room, so on most topologies a rectangular outline means at least one
service room stays over its ceiling. Measured on the shipped 2BHK default (8
rooms, 14 edges, 36x28 ft, local bridge, 2026-08-01), through the real client
including its own hard-rulebook filter:

| mode | catalogue |
|---|---|
| `prefer_rectangle: true` (default) | 12 plans, all 12 free of hard rulebook errors, every outline a full rectangle |
| `prefer_rectangle: false` (old behaviour) | 29 plans, all 29 free of hard rulebook errors, every outline notched |

Both extremes are honest; they answer different questions. The rectangle-first
default is a product decision (a plan the client can draw as one rectangle),
not a claim that it is architecturally better. The 17-plan difference is plans
whose ONLY compliant form has notches: the client hides them because their
kept-rectangle form breaks a hard rule (usually the area ordering, a service
room inflated past a habitable one).

### Hard guarantees vs best effort

Guaranteed on every processed plan:

- rooms stay axis-aligned rectangles and never overlap;
- no interior holes: all empty space connects to the plan boundary;
- every requested adjacency keeps >= 2 ft of shared wall (door survives);
- room minimums (user + NBC floors) are never violated by the processor;
- the footprint never grows beyond the configured margin, EXCEPT toward an
  explicit `target_*` rectangle (phase 5) and never past `plot_*`;
- an outline that was a full rectangle stays one under the default
  `prefer_rectangle`;
- **aspect is monotone**: no phase leaves any room more slender than where
  it started or its band, whichever is looser. The aspect band is a floor as
  well as a ceiling in `_axis_ceilings`, so a trim can no longer take a
  room's short axis below `long/ar_hi` (the measured 12x7 -> 12x5.667
  bathroom regression);
- **no room regresses on any rulebook limit**: a per-room quality vector
  (aspect band, min area, min width, area ceiling, span ceiling) is compared
  before/after, and any component flipping healthy -> broken reverts the
  whole plan. The plan-wide integer score (10*errors + warnings) remains as
  a tiebreak for what the vector cannot see (the cross-room area hierarchy).

Best effort, with honest reporting when unreachable:

- ceilings and aspect bands. Two structural cases resist local repair and are
  left in `issues_after` instead of being forced: a **door-locked** room
  (its protected door partners sit at both extreme ends of its long side at
  exactly the minimum overlap, so any trim severs a door), and a **spanning**
  room (its length equals the sum of its neighbours' minimums across a full
  stack, e.g. a dining room running the full depth of the plan - only a
  different arrangement fixes that, which is `multi-ptpg`'s job, not
  post-processing's).

Measured on the default 4BHK program (30 plans): rulebook violations
`max_area` 204 -> 107, `aspect` 133 -> 98, worst plan score 111 -> 42;
~30 ms per plan.

## API surface 1: inline flag on the dimensioned catalogue

`POST /api/generate/<shape>` (and `Documents.get_floorplans`) accepts:

```jsonc
{
  // ... normal door_connectivity request ...
  "minDimEnabled": true,
  "postProcessEnabled": true,          // default false
  "postprocess_options": { }           // optional, see options below
}
```

Only applied when `minDimEnabled` and `caller == "door_connectivity"`
(dimensionless duals are integer grids the rulebook does not apply to). The
flag participates in the backend request hash, so flagged and unflagged
batches cache separately.

Response changes:

- room geometry (`walls`, `circular_coordinates`, `width`, `height`, `area`,
  `label_coord`) is rewritten in place - same envelope, same parser;
- `response.Documents.postprocess` = per-plan report array, index-aligned
  with `floorPlans` (`null` = plan passed through untouched, e.g. it
  contained merged L-shaped rooms);
- the task `message` gains: `"Post-processing adjusted N of M floorplans
  toward NBC room limits and aspect bands; plan outlines may carry notches."`

## API surface 2: standalone endpoint

`POST /api/postprocess/floorplans` - synchronous, returns **200 with the
result directly** (pure geometry; no task_id, no polling). Mirrored in
`local_engine_bridge.py` for local development. Throttle scope
`postprocess_floorplan` (300/hour).

```jsonc
{
  // either a bare batch:
  "floorPlans": [[ { "name", "walls", "circular_coordinates", ... }, ... ]],
  // or a full previous response envelope (both accepted):
  "response": { "Documents": { "floorPlans": [ ... ] } },

  // optional: the requested adjacencies (doors), as node-index pairs or
  // room-name pairs. STRONGLY recommended - without it the processor only
  // protects each room's single largest shared wall.
  "edges": [[0, 1], [1, 2]],

  "options": { }                        // see below
}
```

Engine facade: `Documents.postprocess_floorplans(request_data)` in
`GPLAN/api.py` (returns `(response_dict, message)`).

Response:

```jsonc
{
  "message": "Post-processed 6 floorplan(s). Post-processing adjusted ...",
  "response": {
    "Documents": {
      "documentID": "...", "name": "...", "count": 6,
      "floorPlans": [ ... same room-dict format, geometry rewritten ... ],
      "postprocess": [ { /* report */ }, null, ... ]
    }
  }
}
```

## Options

All optional; defaults in `postprocess.DEFAULT_OPTIONS`.

| key | default | meaning |
|---|---|---|
| `repair` | `true` | phase 1 on/off |
| `trim` | `true` | phase 2 on/off (the notch-creating phase) |
| `absorb` | `true` | phase 3 on/off |
| `max_passes` | `3` | trim+absorb rounds |
| `min_door_overlap` | `2.0` | ft of shared wall every protected pair keeps |
| `aspect` | `null` | global w/h band, e.g. `{"min": 0.5, "max": 1.5}`; intersected with each room type's own band |
| `rules` | `null` | per-type overrides, e.g. `{"Bathroom": {"max_area": 60, "max_aspect": 1.8}}` (keys of `nbc_rules.NBC_RULES` entries) |
| `tolerance` | `0.02` | fraction past a limit before the processor acts |
| `max_bbox_growth` | `0.03` | per-axis footprint growth allowed to the repair phase |
| `max_notch_ratio` | `0.25` | a trim+absorb round leaving notches beyond this fraction of the bounding box rolls back. Measured on a 7-room/12-plan live batch (2026-07-30): real trims open 0.08-0.24, median ~0.13, so the plan's suggested 0.12 would have reverted half the batch |
| `plot_width` / `plot_height` | `null` | HARD cap on the plan extent, ft, orientation agnostic. Every phase respects it. On the generation path it defaults to the request's own plot |
| `target_width` / `target_height` | `null` | the rectangle phase 5 grows toward. Send the REAL footprint, not the plot cap: the shipped client's plot carries 1.6x slack (a rejection cap), and filling toward that would oversize every plan |
| `prefer_rectangle` | `true` | phase 4. `false` = pre-2026-08-01 behaviour, ship the notches |
| `fill_target` | `true` | phase 5 on/off |
| `notch_close_slack` | `0.25` | how far past its span/area ceiling a room may go **to close the outline**. The aspect band is never relaxed, so the reclose cannot reproduce the 54x8 bathroom |

Aspect semantics: each room type carries a slenderness cap from the rulebook
(`max_aspect`, long/short - bedroom 1.8, bathroom 2.0, balcony 3.5 ...),
applied as the symmetric band `[1/cap, cap]` on w/h. The `aspect` option
intersects an additional global band, so `{"min": 0.5, "max": 1.5}`
tightens every room toward squareness but never loosens a type's own cap.
The band is also visible to the objective: `nbc_rules.plan_issues` accepts
the caller band (so work toward it earns credit instead of scoring
neutral-or-worse) and now scores span-ceiling breaches (`rule:
"max_width"`, warning), which previously earned a span-motivated trim zero
credit.

Related plumbing (2026-07-30): the min-dim `DimParameters` construction in
`api.get_floorplans` now carries `min_ratio`/`max_ratio` through, so
`_room_bounds` emits a real aspect cap for `repair_dimensions` on the
GENERATION path too (previously the ratio the client sent was discarded and
every room's band was infinite). `max_ratio` is honoured as a slenderness
cap when `1 <= max_ratio < 99999`; `min_ratio` only as a genuine sub-1 w/h
lower band - the wire carries sentinels (designer sends `min: 1`, one
legacy default sends `min: 3`) that must not be read as "force landscape".

## The per-plan report

```jsonc
{
  "changed": true,
  "score_before": 31, "score_after": 11,        // plan_sanity_score (10/error, 1/warning)
  "issues_before": [ {"severity", "room", "rule", "message"}, ... ],
  "issues_after":  [ ... ],                      // residual violations - always disclosed
  "gapless_before": true, "gapless_after": false,
  "notch_area": 76.8, "notch_ratio": 0.192,      // empty area inside the bbox / bbox area
  "interior_hole_area": 0.0,                     // always ~0 by construction
  "doors_preserved": true,
  "rectangle_restored": false,                   // phase 4 closed the notches by growth
  "trims_reverted_for_rectangle": true,          // phase 4 kept the rectangle instead
  "over_ceiling_rooms": ["Bathroom", "Kitchen"], // what that trade left over-cap
  "plot_fit": true,
  "filled_toward_plot": [2.0, 0.0],              // phase 5 gain per axis, ft
  "extent_before": [23.0, 30.0], "extent_after": [25.0, 30.0],
  "phase_notes": ["repair rolled back (would grow the plan footprint ...)"],
  "rooms": [
    { "name": "Bathroom",
      "before": {"width": 20, "height": 8, "area": 160, "aspect": 2.5},
      "after":  {"width": 8.5, "height": 8, "area": 68, "aspect": 1.06},
      "actions": ["trimmed 11.5 ft from E"] },
    ...
  ]
}
```

`notch_ratio` is the honesty metric: it says how much of the bounding box the
plan no longer fills. High values on 2BHK+ plans expose upstream inflation
(released ceilings + gap fill), not post-processor damage - the rooms are
right, the void is what the inflation was.

## The rulebook

`nbc_rules.py` mirrors the designer frontend's
`src/constants/nbcRules.ts` (NBC 2016 Part 3 Section 1 clause 8 derived):
per-type min/max area, min/max W x H, slenderness cap, room class, plus the
`AREA_ORDERING` hierarchy (no wet/service room matches or beats a habitable
one, kitchen < living, balcony < living, ...) and `plan_issues` /
`plan_sanity_score`, which are ports of the client-side validator used to
rank the catalogue. **Keep the two files in sync** - a change to one without
the other makes the server repair to one standard and the client score to
another. Room names are matched via `base_room_name` (strips numeric
suffixes) plus an alias table ("Bath" -> Bathroom, "WC" -> Toilet, ...);
unknown types get a fallback (aspect cap 3.0, span cap 18 ft, no area rule).

## Frontend companion notes (not yet wired)

The designer client gates non-rectangular plans out of mixed batches
(`isRectangularArrangement` in `gplanApi.ts`) and places windows with flush
edge tests (`dummyPlan.ts`). Before turning `postProcessEnabled` on from the
designer: relax that gate (overlap check stays, drop the area==bbox
requirement or accept plans whose report says `doors_preserved`), and give
window placement the same strip-intersection treatment the entrance already
has. Rendering itself is already notch-safe (`deriveWalls` classifies
exterior walls per room edge).

## Tests

`python test_api_postprocess.py` from the engine repo root - synthetic
invariants, a live engine batch with the inline flag, the standalone facade,
and options behaviour. Backend: `python smoke_test_postprocess.py` from the
`gplan_backend` root (Django routing -> view -> Celery-eager task -> engine;
set `GPLAN_ENGINE_ROOT` to test an engine checkout other than the
submodule). Both bridge endpoints exercised by the designer harnesses'
pattern (`local_engine_bridge.py` on :8027).
