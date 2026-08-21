# Area-budget allocation: `POST /api/allocate`

Change B (part 1) of
`documentation/plans/DOOR_CONNECTIVITY_SIZING_AND_POSTPROCESS_PLAN.md`.
Implemented 2026-07-30.

On the shipped min-dim path room size is a residue: the solver minimises onto
the request minimums and the gapless fill pushes the plot's leftover area into
whichever room can reach a notch. The allocator is the missing decision. Given
a room list, a plot and the NBC rulebook it returns, per room, the envelope
the room SHOULD occupy, such that the allocated areas sum to the plot area
whenever the program fits. Generation sends the allocated targets as the
solver minimums (the one lever the solver honours, see plan Section 2.2), so
the minimal-area solution already fills the plot and the gap fill has nothing
left to redistribute.

Pure function, no solver, no Celery, no cache. Code:

```
GPLAN/source/dimensioning/allocator.py     pure, unit-tested (test_allocator.py)
GPLAN/api.py  Documents.allocate_program   thin facade, (response, message)
gplan_backend gplan_apis/views.py          AllocateProgramView, AllowAny,
                                           throttle scope allocate_program 1000/hour
GPLAN/local_engine_bridge.py               same route for local dev
designer      src/services/gplanApi.ts     allocateProgram()
```

## Request

```jsonc
POST /api/allocate
{
  "rooms": [
    {"name": "Living Room"},
    {"name": "Bedroom", "max_width": 12},   // per-room overrides, CLEAR feet
    ...
  ],
  "plot_width": 36, "plot_height": 28,      // feet
  "wall_allowance_ft": 0.4,                 // optional, see below
  "tier_share": [1.0, 1.0, 1.0]             // optional, see below
}
```

Semantic problems return 400 with `error.type: "ValidationError"` and a
message naming every offender, e.g. `"Living Room: max_width 8 is below the
10 ft minimum"`. A user maximum below the NBC minimum is an error, never a
silent clamp.

## Response

`{"message", "response": {"allocation": {...}}}`, answering in ~3 ms for a
12-room program. All room numbers are **RECTANGLE feet**: NBC minimums are
clear-floor figures, and walls are drawn centred on room-rectangle edges, so
the allocator adds `wall_allowance_ft` (default 0.4, two interior half-walls)
per axis on top of the clear bounds. Rectangles tile the plot exactly under
the centreline convention, so rect areas are what must sum to the plot.

```jsonc
{
  "fits": true,
  "plot": {"width": 36, "height": 28, "area": 1008},
  "wall_allowance_ft": 0.4,
  "tier_share": [1, 1, 1],
  "program_min_area": 610.54,     // sum of rect floors
  "program_max_area": 1422.86,    // sum of rect ceilings; the change-C
                                  // threshold: a plot above this cannot be
                                  // legally filled and the plan centres
  "target_bbox": {"width": 36, "height": 28},
  "surplus": 397.46,              // plot - floors (fits only)
  "remainder": 0.0,               // surplus nobody could absorb (fits only)
  "rooms": [
    {"name": "Living Room", "canonical": "Living Room", "known": true,
     "tier": 1,
     "min_width": 10.4, "min_height": 11.9,
     "max_width": 22.4, "max_height": 19.49,
     "min_area": 123.76, "max_area": 436.6,
     "ar_lo": 0.4545, "ar_hi": 2.2,
     "allocated_area": 255.71,
     "target_width": 18.0, "target_height": 14.0,   // 0.5 ft rounded shape
     "at_cap": false, "clear_area": 239.36},
    ...
  ]
}
```

When the program does not fit the plot (`fits: false`), allocation stays at
the floors (generate at minimums, overflow the plot, label it - the settled
product decision), and the response adds:

```jsonc
{
  "shortfall_sqft": 50.54,
  "smallest_plot": {"width": 29.2, "height": 20.9},
  "drivers": [{"room": "Living Room", "min_area": 123.8}, ...]  // top 3
}
```

## The algorithm

1. Canonicalise names via `nbc_rules.canonical_name`; unknown types get
   `ROOM_FALLBACK` (no area rule, span/aspect caps only), UNLESS the request
   carries `rules` (since 2026-08-21, engine PR 2): the body's optional
   `rules` is the same per-type patch as `postprocess_options.rules`
   (`{"Store": {"min_area": 54, ...}}`), merged over the NBC rule for known
   names and defining unknown names when complete; the enforce_plot fill
   allocator inside generation reads the same dict off the request's
   `postprocess_options.rules`. A pack floor above an NBC ceiling is
   therefore kept in the envelope instead of being undone. `Corridor` is a
   KNOWN type since 2026-08-21 (the rulebook row mirrors the designer's):
   a room labelled Corridor now allocates as tier 3 with the 3.5 x 7 ft
   floors, 6 x 18 ft caps, 28-90 sqft band and 4.5 aspect (rect envelope
   roughly 3.9 x 8.4 .. 6.4 x 15.4 ft with the wall allowance) instead of
   the 6 x 8 .. 18 x 18 fallback, `known` reads true, and the `enforce_plot`
   fill caps read the same row. The allocator still takes no per-request
   `rules` (that is engine PR 2); the designer's measured corridor verdict
   (2026-08-06, taken against the fallback-era envelope) is to be
   re-measured on the bridge.
2. `rect_bounds(rule)`: clear NBC bounds -> rectangle bounds. The area floor
   beats the shape floor (a 3.5x5 Toilet backfills its height to 18/3.5) and
   the area cap beats the shape cap (a 22x24 Living Room caps its height at
   420/22). Per-room overrides intersect afterwards.
3. Surplus = plot area - sum of floors. Distributed by tier:

   | Tier | Rooms | Rule |
   |---|---|---|
   | 1 | Living Room, Master Bedroom, Bedroom(s), Kitchen | surplus shared proportionally to each room's rectangle minimum, capped at its own ceiling |
   | 2 | Dining, Study | what tier 1 could not absorb |
   | 3 | everything else + unknown types | stay at minimum unless 1 and 2 are capped |

   `tier_share` caps the fraction of the surplus a tier may absorb (default
   `[1,1,1]`: each tier takes all it can, the confirmed product decision -
   on the default 2BHK that means Living 255.7 sqft while Dining stays at
   its 97.8 floor). Whatever the shares strand is offered to every room in
   a final pass, so the plot stays full whenever the program has capacity.
4. Shaping: each allocated area becomes a `target_width x target_height`
   following the plot's own aspect ratio, clamped to the room's rect bounds
   and aspect band, rounded to 0.5 ft, never below 2.0 ft per axis (spans
   under 2 ft kill the topology in the min-dim solver).

`test_allocator.py` (32 checks) pins the plan 4.6 worked example to 0.1 sqft
and the acceptance properties: totals, envelope respect, monotonicity in plot
area, the infeasible report, tier_share, validation, speed.

## Wired into generation (change B part 2, 2026-07-30)

The door_connectivity generate request now accepts NEW per-node `min_area` /
`max_area` fields (sqft, flat numbers beside the `width`/`height` bands;
same `maxDimEnabled` opt-in as the span ceilings). They travel
`views.py` / `local_engine_bridge.py` -> `dim_inputs` -> `DimParameters`
(`get_min_area`/`get_max_area`) and drive the POST-SOLVE layers only - the
min-dim solver reads exactly four lengths per room and cannot use area:

- `api._room_size_caps`: the gap-fill area cap is
  `min(max_w * max_h, max_area)` instead of the bare span product
  (1.04x-1.42x looser than NBC for every room type);
- `api._room_bounds`: `repair_dimensions` bands take the explicit rule
  (`minarea = max(min_w * min_h, min_area)`, `maxarea = min(product,
  max_area)`);
- NBC post-processing: a request area cap tightens (never loosens) the
  rulebook's own cap via `build_bounds(user_min_a, user_max_a)`.

**Correction to the plan's mechanism, from measurement (2026-07-30).**
Section 4.7 of the plan proposed sending the ALLOCATED targets as the
solver minimums. Measured on the shipped 2BHK against the bridge, that is
worse on every axis: 12 plans with bounding boxes 1.26x-1.88x of the plot,
because a gapless tiling needs slack over the sum of its minimums (the
same stacking argument as plan Section 2.5 correction 2) and budget-sized
minimums double-count that slack. What the designer actually sends is its
existing band() minimums plus the allocation's ENVELOPE: area-capped rect
ceilings as the per-node maxima, `min_area`/`max_area`, the aspect cap,
and `postProcessEnabled: true`. The tier hierarchy still holds because
`_fill_gaps` hands slack to the largest headroom first and the real area
caps stop every room at its NBC ceiling.

Measured on the shipped defaults against the bridge (2026-07-30, baseline
= pre-allocator): 2BHK **29 plans shown, all 29 free of any hard rulebook
error, at 0.91x-1.22x of the plot** (baseline 30 shown, 0 error-free;
allocated-targets-as-minimums variant: 12 shown, 12 error-free, 1.26x-1.88x
oversized). 3BHK 9 -> 2 plans (its sparse 10-room/10-edge graph is the
known out-of-scope root cause); 4BHK 25 plans, 0 error-free (same graph
problem).
