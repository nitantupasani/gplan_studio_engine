# Structural layout and design: `/api/structural/*`

The engine surface of the structural module. Specified in
`GPLAN_Revamp/structural_research/specs/08-api-backend.md` under the 42
resolutions in `structural_research/CRITIC_RESOLUTIONS.md`; status and phases in
`documentation/plans/STRUCTURAL_MODULE_PLAN.md`. Engine and bridge implemented
2026-08-30.

Four entry points, and nothing else is public:

| Endpoint | Method | Mode | Answers |
|---|---|---|---|
| `/api/structural/options/` | GET | sync 200 | what this engine accepts and what it caps |
| `/api/structural/layout/` | POST | sync 200 | placement only: grid, columns, beams, slabs, walls, bands, unsized footing markers, layout score |
| `/api/structural/design/` | POST | 202 + poll `GET /api/task/<id>/` | the full pipeline: loads, takedown, foundations, member design, quantities, clause-traced report |
| `/api/structural/check/` | POST | sync 200 (Django: 202 when large) | re-check a `structural_model`, possibly hand-edited |

Code:

```
GPLAN/structural/                          the module; api.py owns every rule
GPLAN/structural/api.py                    run_options/run_layout/run_design/run_check
GPLAN/api.py  Documents.structural_options thin facade, lazy import inside each
              Documents.layout_structure   method so a broken structural package
              Documents.design_structure   cannot take get_floorplans down with it
              Documents.check_structure
GPLAN/local_engine_bridge.py               the same four routes for local dev
GPLAN/structural/schema/                    structural_response.schema.json (shipped)
gplan_backend gplan_apis/views/structural.py   NOT YET: wave 7, with the pinned
              gplan_apis/tasks/structural.py   Celery names and throttle scopes
```

## Why this exists

The designer already draws a structural grid. `structuralGrid.ts` in the
frontend derives axes from wall centrelines and drops columns at their
crossings, which is a good picture and no engineering: it knows no load, no
code, no soil, and it cannot tell a caller that a column is floating, that a
5.4 m span needs a deeper beam, or what the building costs. The engine is the
source of truth for all of that.

What the module adds over the seed, all of it disclosed rather than assumed
away:

- a real grid decision (axes from walls, corridors, cores and the outline, with
  inserted axes when a span runs past the catalogue cap), and a system decision
  that delegates to `choose_system` and reports the IS 4326 category, the
  clause-cited refusal ladder and the trace that produced it;
- a load path: IS 875 dead and imposed loads by room occupancy, IS 1893
  equivalent-static seismic, optional IS 875-3 wind, IS 456 combinations, a
  tributary takedown and a rigid-diaphragm distribution;
- member design to IS 456, IS 13920, IS 6403, IS 1905 and IS 4326, each result
  carrying its checks, its governing clause, its bars with development lengths
  and its referrals;
- quantities, a bar bending schedule and a priced bill;
- one disclosure ladder (ERROR / WARNING / NOTE with registry codes from
  `model.REGISTRY`) and the PRELIMINARY ENGINEERING NOTICE on every single
  response, refusals included. The product is the disclosed report, not a
  number that looks confident.

## The request

One shape for `layout` and `design`; `check` differs (see below). The
discriminator is `source`, and exactly the block it names must be present.

```jsonc
POST /api/structural/layout/
{
  "schema_version": "structural-1.1",   // optional; unknown MAJOR -> refused
  "source": "plan",                     // REQUIRED: plan | building | housing

  // exactly one of these three, matching source:
  "plan":     { /* door_connectivity output, any envelope shape, see below */ },
  "building": { /* frontend Building JSON: boundary, totalFloors, floors[].units,
                   corridors, fixedElements, kind */ },
  "housing":  { /* frontend HousingDesign JSON: floors[].boundary/plots/shapes/
                   segments/regionContent, wallDisplay, roof, entry */ },

  "plan_index": 0,        // plan source only, which floorPlans[i]; default 0
  "storeys": 2,           // REQUIRED for plan (a plan carries no storey count);
                          // ignored for building (totalFloors) and housing (floors)
  "plot_id": "plot-2",    // housing only, optional: one stack instead of all
  "resolved_regions": {}, // housing only, optional: regions the client resolved

  "params": { /* every knob optional, see Options below */ },
  "output": {
    "include_report": true,
    "include_boq": true,
    "include_quantities": true,
    "trace": false,          // clause traces are elided unless asked for
    "report_format": "json",
    "generated_at": null,    // the ONLY way a timestamp enters a response
    "validate_only": false   // design only: validate and stop, for a cheap
                             // pre-dispatch check in the view
  }
}
```

`check` posts a model back instead of a plan:

```jsonc
POST /api/structural/check/
{
  "source": "model",
  "model": { /* a structural_model returned by layout or design, possibly edited */ },
  "params": { /* re-sent; the model does not embed mutable params */ },
  "scope": "full"          // "placement" = hard rules + score only; "full" adds
                           // loads, takedown and the per-member checks
}
```

`run_check` never moves an element. It answers about the model it was handed.

### Envelope acceptance

The `plan` block is accepted in every shape the engine speaks, mirroring
`postprocess_floorplans`:

```
{"floorPlans": [[room, ...], ...]}                    bare batch
[room, ...]                                           a single bare plan
{"Documents": {"floorPlans": [...]}}                  Documents envelope
{"status", "message", "response": {"Documents": ...}} full engine envelope
```

The request ITSELF may also arrive wrapped: a body of
`{"response": {"Documents": {<request>}}}` or `{"Documents": {<request>}}` is
unwrapped, and hashes to the same `input_ref.hash` as the bare form, so the
backend's dedup cache sees one entry either way.

### The unit contract

Stated once and never mixed:

| Where | Unit |
|---|---|
| all geometry crossing the boundary | FEET, y-DOWN, `*_ft` suffix |
| section dimensions | MILLIMETRES, `b_mm` / `d_mm` / `thickness_mm` |
| forces, moments, loads, stresses | SI: `_kn`, `_knm`, `_kpa`, `_mpa` |
| everything inside `structural/` | SI metres and kN, converted ONCE on ingest |

Feet in, feet out, SI in between, and every numeric key carries its unit as a
suffix. The response echoes the contract in `units`:

```json
{"geometry": "ft", "sections": "mm", "forces": "kN", "moments": "kNm",
 "loads": "kPa", "stresses": "MPa"}
```

`params.spans` accepts either `min_m`/`max_m` or `min_ft`/`max_ft`; the metric
values are canonical and feet are converted on the way in.

## Housing column alternatives: one to three total storeys

Housing Structure can request separate deterministic layouts at the same chosen
span cap. This is an opt-in addition; omitting the parameter preserves the
existing plan, building and housing workflows.

```jsonc
{
  "source": "housing",
  "housing": { /* existing HousingDesign with 1, 2 or 3 total floors */ },
  "plot_id": "primary",
  "params": {
    "system": "rc_frame",
    "analysis_mode": "gravity_only",
    "placement_strategy": "wall_aligned",
    "housing_column_variant": "toward_start",
    "spans": { "min_m": 2.5, "max_m": 5.0 }
  },
  "output": { "detail": "compact", "include_boq": true }
}
```

`housing_column_variant` accepts `balanced`, `toward_start` or `toward_end`.
The options endpoint publishes these values and their scope in
`housing_column_variants`. Other sources, four total floors, another structural
system, `code_complete`, or `economy_grid` reject this parameter. Ground counts
as one storey. The span cap is never silently raised.

The labels select the first, second and third distinct candidates from one
deterministic search. Its three initial guide seeds retain the earlier combined,
lower-wall and higher-wall choices. It then explores optional support removals,
row or column subsets, real wall repositions and paired bearing repairs.
Corners, core supports, corridor ties and party-wall anchors remain protected.
Omitting the variant retains the earlier placement path; opting into `balanced`
now requests the first ranked search candidate.

Each distinct guide seed has at most 128 finite-wall stations, drawn from real
endpoints, wall crossings, existing axes and admissible span stations. Optional
repositions move at least 400 mm. Initial search evaluates at most 48 complete
frames: three seeds, up to eight bearing repairs, eight paired repairs, twelve
single removals, six support subsets and eight repositions, with remaining work
available to compound removals. Canonical coordinates and fixed operation quotas
determine the work; elapsed time never selects a partial winner.

Every candidate repeats continuity, framing repair and final span warnings.
Finite-wall and room assessment, physical BeamRun spans and supported framing
depth gate placement selection. Surviving final frames are ordered by total
close-pair deficit, close-pair count, optional stacks, coordinate-line regularity,
total beam length and canonical geometry. The preferred 2.5 m spacing remains
an objective, not a universal hard minimum. `W_SHORT_SPAN` concerns adjacent
collinear final columns and retains its corridor/core-tie exceptions; the
Euclidean crowding metrics include every unique same-storey stack pair.

Placement preflight cannot establish member-design success. The selected frame
enters the complete production design pipeline. A secondary-beam referral
replays its exact selected support recipe. If final checks still fail, the
engine tries the actual request's earlier wall-supported seed on fresh inputs
once. Only a fully eligible fallback can replace the initial result. There are
at most two candidate design attempts, each with the existing one referral
re-pass, so at most four engineering-pass invocations before reuse. Both failed
attempts remain disclosed if neither completes. Final column geometry determines
distinctness after these repairs and fallbacks; fewer than three real layouts
can therefore be returned under the three request labels.

Every candidate, column slide and later beam-support promotion must keep the
column center within 0.30 m of a finite eligible architectural wall segment on
each storey where the column exists. Extended guide lines, railings and parapets
do not satisfy this requirement. The final audit runs again before every
gravity-design pass, including the bounded referral re-pass, and refuses any
remaining off-wall column with `E_HOUSING_COLUMN_OFF_WALL`.

Room intrusion is a separate assessment: a center strictly inside a known
enclosed room polygon and more than 0.30 m from every eligible same-floor wall.
Open parking, green, void, corridor, balcony and stair/lift circulation areas are
exempt from the room-intrusion count, but still require wall alignment for these
Housing variants. Their existing structural/door/core checks also apply. Unknown
room internals are reported for the affected columns and cannot earn comparison
eligibility. Confirmed room intrusions retain `E_HOUSING_ROOM_INTRUSION`.

An opt-in entry includes `housing_layout`:

| Field | Meaning |
|---|---|
| `variant`, `summary`, `axis_adjustments` | Requested variant, deterministic explanation and actual changed guide coordinates in metres. A different label does not imply different columns. |
| `geometry_fingerprint` | SHA-256 of sorted final `(storey, x_m, y_m)` column centers rounded to millimetres. Use it to collapse identical column layouts. |
| `column_stack_count`, `closest_column_centres_m` | Final support positions across the building and closest centers on a shared storey. |
| `off_wall_column_count`, `off_wall_column_ids` | Number and IDs of final per-storey column instances more than 0.30 m from every finite eligible same-storey wall. Open or unknown room occupancy does not waive this check. |
| `close_pair_count`, `close_pair_deficit_m` | Unique stack pairs closer than `min_span`, and sum of the missing distances to that preference. Uses straight-line center distance and includes intentional corridor/core exceptions; this is a crowding comparison, not a safety verdict. |
| `room_intrusion_count` | Number of affected stacks when fully assessed; `null` if any column remains unassessed. |
| `confirmed_room_intrusion_count`, `room_intrusion_column_ids` | Confirmed affected stacks and precise column IDs, even when another area is unassessed. |
| `room_assessment`, `assessed_column_count`, `unassessed_column_ids`, `unassessed_storeys` | `assessed`, `partial` or `unassessed`, with the assessment scope. An unrelated unknown room does not unassess a known-room column. |
| `wall_alignment_tolerance_m` | The disclosed 0.30 m allowance for near-wall centers. |
| `physical_max_span_m`, `requested_max_span_m` | Final analyzed floor-beam span and the unchanged requested cap. Physical span stays `null` on placement-only or interrupted runs. |
| `eligible`, `reasons` | Whether the fully calculated candidate satisfies wall alignment, room, span, member, referral, foundation and applicable quantity checks. A layout-only result is ineligible with `full_design_required`. |

Search diagnostics use the existing extensible
`structural_model.meta.frame_placement.metrics.housing_search` map and its
placement-score mirrors. They distinguish generated placement candidates,
distinct placement layouts, the two-attempt limit, actual design attempts,
distinct final attempted layouts, eligible final layouts and checked fallback
use. Placement counts never claim completed design eligibility. The returned
`housing_layout` and `comparison_validity` apply to the selected final response.
This adds diagnostic values within existing metadata; the schema remains
`structural-1.1`.

Final foundation and quantity blockers also enter the Housing eligibility gate
and the bounded fallback decision. For example, completing every beam and column
does not make a layout eligible when sized footings still overlap. Deliberately
omitting BOQ output blocks cost comparison but does not by itself trigger a new
engineering attempt or invalidate the engineering layout.

An internal engineering cache reuses only an identical full-design signature.
It includes exact unrounded SI architecture, member/support topology and IDs,
storeys, loads, materials, analysis/code/span/rate inputs, every resolved and
request/output option, and the source/data/schema engine fingerprint. Only the
requested variant and explicit search provenance are excluded. Referral repair
produces a new signature. The cache stores at most twelve completed engineering
passes per Python process; concurrent identical passes share work, while other
contexts proceed independently. Passes that raise exceptions are not reused.
Completed identical-context results retain every check, including failures;
final eligibility is recomputed for each response. Cached mutations are
isolated, and quantities, reports, request hashes, option echoes,
labels and responses are constructed freshly for each caller. No cost or pass
result crosses different engineering contexts.

The common placement pool has its own exact architecture/placement-parameter/
engine key and at most six completed pools per process. It returns independent
copies for each requested label, and referral recipe replay bypasses the pool
cache. Neither cache spans worker processes, disk or Redis. Operational counters
are available through `design_reuse.design_cache_diagnostics()` and
`placement.frame.housing_search_cache_diagnostics()` for probes; they stay out of
wire responses so response determinism does not depend on cache history.

`comparison_validity` remains authoritative for cost ranking. In addition to
its existing analysis, foundation, member and quantity checks, it rejects
`housing_off_wall_columns`, `housing_room_intrusion` and
`housing_room_assessment_incomplete`. Do not rank a
layout by price before these checks, and do not equate fewer columns with lower
cost. At least two distinct eligible final column layouts in the same comparison
cohort are needed for a relative cost winner. Repeated layouts remain selectable
and count once. Quantities and the completed subtotal determine cost; fewer
supports alone never establish a lower price. These are bounded preliminary
alternatives, not a global optimum or construction approval.

## The response

Every response of every endpoint uses the engine envelope, and
`Documents.structural` is ALWAYS a list: length 1 for a plan or a building, one
entry per built plot stack for housing, always beside a `batch_summary`. Every
response carries the verbatim `disclaimer`, including a refusal and a validation
failure.

### Layout (the first detail level)

Real output, 2BHK fixture, two storeys, elided where a list repeats:

```jsonc
{
  "status": "SUCCESS",                 // "ERROR" only when nothing usable came back
  "message": "structural layout: rc_frame, 2 storeys, score 79",
  "disclaimer": "PRELIMINARY ENGINEERING NOTICE. ...",   // verbatim, always
  "response": { "Documents": {
    "schema_version": "structural-1.1",
    "engine_fingerprint": "st-9f0a...",   // schema + data table versions
    "batch_summary": {"plans": 1, "ok": 0, "warnings": 1, "refused": 0,
                      "schema_version": "structural-1.1"},
    "structural": [ {
      "schema_version": "structural-1.1",
      "engine_fingerprint": "st-9f0a...",
      "units": {"geometry": "ft", "sections": "mm", "forces": "kN",
                "moments": "kNm", "loads": "kPa", "stresses": "MPa"},
      "source": "plan",
      "system": "rc_frame",              // the system actually used
      "status": "ok_with_warnings",      // ok | ok_with_warnings | refused
      "partial": false,                  // true = refused, geometry shown anyway
      "footings_sized": false,           // layout NEVER sizes a footing
      "disclaimer": "PRELIMINARY ENGINEERING NOTICE. ...",

      "input_ref": {"source": "plan", "plan_index": 0, "plot_id": null,
                    "model_id": "plan-0",
                    "hash": "sha256:47f472b9a2a0..."},   // the dedup key

      "options_echo": {                  // what actually ran, and where it came from
        "values":  {"seismic_zone": "III", "frame_ductility": "OMRF", ...},
        "origins": {"seismic_zone": "default",
                    "frame_ductility": "derived from seismic_zone III", ...},
        "unapplied": []                  // options accepted and NOT used, per field
      },

      "placement": {
        "system": "rc_frame",
        "valid": true,
        "axes_source": "placement.frame",
        "system_decision": {             // finding 27: choose_system's answer, verbatim
          "system_requested": "auto", "system": "rc_frame", "system_used": "rc_frame",
          "category": "C", "labeled": false, "refused": null,
          "trace": ["category C from IS 4326 Table 1 on zone III (from params.zone) at importance 1.00",
                    "2 storey(s), 6.10 m tall; category C admits 4 storey(s) up to 15.0 m",
                    "row 4: load bearing masonry does not close the cover: panel pnl-s0-0 spans 9.14 m the short way, past the 4.50 m cap, and no eligible wall closes it",
                    "row 7: no masonry row fits; rc_frame"]
        },
        "params": { /* the frame placer's own params echo */ },
        "report": { /* the frame placer's own report */ },
        "layout_score": { /* the same block as below */ }
      },

      "layout_score": {                  // finding 33: the placer's metrics, mirrored
        "score": 79,
        "score_version": "frame-1",      // mandatory: scores are only comparable
                                         // within one formula id
        "valid": true,
        "hard_violation_count": 0,
        "hard_violations": {"E_TRANSFER_REQUIRED": 0, "E_SPAN_OVER_MAX": 0,
                            "E_CANTILEVER_SPAN": 0, "E_FRAMING_DEPTH": 0,
                            "E_GRID_COARSE": 0, "E_MERGE_FLOOR": 0},
        "metrics": {
          "axis_count": {"x": 4, "x_inserted": 0, "y": 6, "y_inserted": 0},
          "span_histogram": {"lt_2_5": 44, "2_5_3": 0, "3_4": 16, "4_5": 10,
                             "5_6": 0, "6_7_5": 0, "gt_7_5": 0,
                             "pct_in_2_5_to_5": 37.1},
          "columns_per_100m2": 21.53,
          "beams_under_walls_pct": 100,
          "column_eccentricity_mm": {"max": 0, "mean": 0},   // mm, not m
          "torsion_proxy_pct": {"x": 3.2, "y": 4.8},
          "load_path_depth": 3
        }
      },

      "structural_model": {
        "id": "plan-0", "schema_version": "structural-1.1", "source": "plan",
        "system": "rc_frame", "fingerprint": "...",
        "units": { /* as above */ },
        "meta": {"adapter": "plan_json", "north": "-y", "plan_index": 0,
                 "options": { /* every adapter option, echoed */ }},
        "storeys": [{"index": 0, "name": "Ground", "bottom_z_ft": 0.0,
                     "height_ft": 10.0, "kind": "units",
                     "source_id": "floorPlans[0]"}],
        "axes": {"x": [{"id": "gx-1", "dir": "x", "pos_ft": 0.0, "label": "1",
                        "source": "outline", "storeys": [0, 1]}],
                 "y": [ /* labelled A, B, C ...; x axes are numbered */ ]},
        "columns": [{"id": "col-1-A-s0", "stack_id": "stk-1-A", "storey": 0,
                     "x_ft": 0.0, "y_ft": 0.0, "b_mm": 230, "d_mm": 300,
                     "rot": 0, "on_grid": ["1", "A"],
                     "placed_by": "placement.frame.corner", "code_refs": []}],
        "beams": [{"id": "beam-s0-x1-0", "storey": 0,
                   "a_ft": [0.0, 0.0], "b_ft": [0.0, 12.9987],
                   "b_mm": 230, "d_mm": 350, "kind": "primary",
                   "supports_wall_id": null,
                   "placed_by": "placement.frame.primary", "code_refs": []}],
        "slabs": [{"id": "slab-s0-0", "storey": 0,
                   "polygon_ft": [[0.0, 0.0], [7.9987, 0.0], [7.9987, 12.9987], [0.0, 12.9987]],
                   "thickness_mm": 100, "two_way": true,
                   "lx_ft": 7.9987, "ly_ft": 12.9987,
                   "edge_continuity": {"e0": "beam:disc", "e1": "beam:cont",
                                       "e2": "beam:cont", "e3": "beam:disc"},
                   "kind": "floor", "support_ids": [],
                   "placed_by": "placement.frame.slab"}],
        "walls": [{"id": "wall-s0-h-0-0", "storey": 0,
                   "a_ft": [0.0, 0.0], "b_ft": [15.0, 0.0],
                   "thickness_ft": 0.75, "role": "exterior",
                   "material": "brick_masonry", "bearing": null,
                   "openings": [], "room_ids": [null, "room-s0-r-bed1"],
                   "source": "edge:outside|r-bed1"}],
        "lintels": [{"id": "lin-wall-s0-h-13-0-op0", "wall_id": "wall-s0-h-13-0",
                     "opening_id": "wall-s0-h-13-0-op0", "span_ft": 3.937,
                     "placed_by": "placement.frame.lintel_infill"}],
        "bands": [],                    // masonry systems only
        "cores": [],                    // stair and lift shafts, when present
        "rooms": [{"id": "room-s0-r-living", "storey": 0, "name": "Living Room",
                   "occupancy": "habitable",
                   "polygon_ft": [[0.0, 19.0], [15.0, 19.0], [15.0, 35.0], [0.0, 35.0]],
                   "area_sqft": 240.0, "unit_id": null,
                   "interior_unknown": false, "source": "r-living"}],
        "footings": [{"id": "ftg-stk-1-A", "kind": "isolated",
                      "supports": ["col-1-A-s0"], "x_ft": 0.0, "y_ft": 0.0,
                      "w_ft": null, "h_ft": null, "depth_ft": null,
                      "placed_by": "api.layout_marker"}],   // MARKERS, unsized
        "loads": null, "analysis": null, "design": [], "quantities": null,
        "warnings": [ /* the same Disclosure objects as below */ ]
      },

      "errors": [],                      // Disclosure objects, severity "error"
      "warnings": [{                     // severity "warning" or "note"
        "code": "W_DOOR_ASSUMED",        // registry code, one per condition
        "severity": "warning",
        "message": "13 door(s) were assumed at 0.9 m wide, mid wall, on the longest run each adjacent room pair shares; the plan carried none",
        "element_ids": ["wall-s0-h-13-0-op0", "..."],
        "clause": null,
        "stage": "adapters.plan_json"
      }]
    } ]
  } }
}
```

`status` stays `"SUCCESS"` with any number of warnings. It is `"ERROR"` only
when no usable model came back: a refused entry still ships its geometry with
`"status": "refused"`, `"partial": true` and the reason on the ladder, so the UI
has something to draw and the reader can see how far the pipeline got.

Layout carries NO sized footing (finding 18): a footing is sized from a takedown
that layout never runs, so the markers come back with `w_ft`, `h_ft` and
`depth_ft` all null at the ground column stacks.

### Design (the second detail level)

Everything above, with `footings_sized: true` and real footing dimensions, plus
five blocks. `structural_model.loads`, `.analysis`, `.design` and `.quantities`
are now populated, and the entry-level blocks summarize them and point at them
by name rather than serializing them twice:

```jsonc
{
  "status": "SUCCESS",
  "message": "structural design: rc_frame, 1 entry, 60 member design failure(s)",
  "response": { "Documents": { "structural": [ {
    /* ... every layout key, plus: */
    "footings_sized": true,             // ftg-stk-1-A is now 3.4449 x 3.4449 ft
                                        // at 4.9213 ft depth
    "analysis": {
      "method": "tributary_takedown_v1",
      "storey_weight_source": "gravity takedown pass 1 (the seismic weights come from the takedown ledger, which is why the takedown runs twice)",
      "referral_re_passes": 0,
      "cases_used": ["DL", "EQX+", "EQX-", "EQY+", "EQY-", "LL", "LLR"],
      "combos_used": ["1.5DL+1.5LL+1.5LLR", "1.2DL+1.2LL+1.2LLR+1.2EQX+",
                      "1.5DL+1.5EQX+", "0.9DL+1.5EQX+", "..."],
      "combos": [ /* every combination, with its factors */ ],
      "seismic": {"code": "IS 1893-1:2016", "method": "equivalent static (Cl 7.6)",
                  "zone": "III", "soil": "II", "system": "omrf",
                  "z": 0.16, "i": 1.0, "r": 3.0, "height_m": 6.096,
                  "seismic_weight_kn": 3199.597,
                  "plan_dims_m": {"x": 9.144, "y": 12.192},
                  "storey_weights": [ ... ],   // the takedown ledger, per storey
                  "directions": { ... },       // Ta, Ah and base shear per axis
                  "cases": [ ... ]},           // EQX+/-, EQY+/- with storey forces
      "wind": null,                     // null unless params.wind.basic_speed_ms
      "storey_shears": {"x": {"0": 213.306, "1": 156.664}, "y": { ... }},
      "lateral": { /* diaphragm distribution, with its assumptions listed */ },
      "foundations": {"pads": [...], "strips": [...], "combined": [...],
                      "straps": [...], "report": {"soil": {...}, ...},
                      "warnings": [...]},
      "loads_ref": "structural_model.loads",       // the bulky blocks live once
      "takedown_ref": "structural_model.analysis"
    },

    "design": {
      "code_set": ["IS 456:2000", "IS 1893 (Part 1):2016", "IS 13920:2016",
                   "IS 1905:1987"],
      "materials": {"concrete": "M25", "steel": "Fe500", "mortar": "M1"},
      "results_ref": "structural_model.design",
      "results_count": 208,
      "trace_included": false,          // output.trace turns the clause traces on
      "failed": [{"element_id": "beam-s0-x1-2", "element_type": "beam",
                  "check": "ductile_beam_depth", "utilization": 1.081917,
                  "warnings": ["IS 13920 Cl 6.1: depth 350.0 mm above the Cl 6.1.3 cap of 323.5 mm (clear span / 4); the ductile overlay does not resize a section"]}],
      "failed_count": 60,
      "undesigned": [], "undesigned_count": 0,
      "coverage": {                     // per class: what was placed vs designed
        "beam":   {"placed": 110, "designed": 110, "undesigned": [], "undesigned_count": 0},
        "column": {"placed": 48, "designed": 48, "undesigned": [], "undesigned_count": 0},
        "slab":   {"placed": 26, "designed": 26, "undesigned": [], "undesigned_count": 0},
        "footing":{"placed": 24, "designed": 24, "undesigned": [], "undesigned_count": 0},
        "lintel": {"placed": 26, "designed": 0, "undesigned": ["lin-..."],
                   "undesigned_count": 26,
                   "reason": "the v1 design layer owns beam, column, footing, slab; this class is placed and quantified but not designed"}
      },
      "referrals": { /* every referral the designers raised, by action */ },
      "referrals_applied": [],          // what the ONE bounded re-pass acted on
      "referrals_outstanding": [], "referrals_outstanding_ids": [],
      "referral_re_passes": 0           // 0 or 1, never 2 (finding 19)
    },

    "quantities": {
      "takeoff_ref": "structural_model.quantities.takeoff",
      "bbs_ref": "structural_model.quantities.bbs",
      "boq_ref": "structural_model.quantities.boq",
      "totals": {"concrete_m3": 116.51, "formwork_m2": 713.94,
                 "masonry_m3": 77.74, "steel_kg": 11031.316,
                 "excavation_m3": 131.78},
      "builtup_area_m2": 222.97,
      "bbs_total_with_wastage_kg": 11031.316,
      "boq_total": 2706059.65, "currency": "INR"
    },

    "report_status": "ok_with_warnings",
    "report": {
      "summary": {"status": "ok_with_warnings", "system": "rc_frame",
                  "storeys": 2, "height_m": 6.096,
                  "seismic": {"zone": "III", "ta_s": 0.181, "ah": 0.066667,
                              "base_shear_kn": 213.306, "by_direction": {...}},
                  "totals": {"cost": 2706059.65, "currency": "INR",
                             "cost_per_m2": 12136.58, "steel_kg_per_m2": 49.475, ...},
                  "element_counts": {"columns": 48, "beams": 110, "slabs": 26,
                                     "footings": 24, "bands": 0, "lintels": 26,
                                     "walls_bearing": 0},
                  "layout_score": {"score": 79, "score_version": "frame-1"},
                  "engineer_review_required": false,
                  "disclosure_counts": {"error": 0, "warning": 83, "note": 7},
                  "blocked_element_count": 60, "refusal_reasons": []},
      "element_cards": [{"element_id": "col-1-A-s0", "element_class": "column",
                         "storey": 0,
                         "geometry_ref": "placement.storeys[0].columns#col-1-A-s0",
                         "status": "blocked", "design_status": "fail",
                         "section": "230x300",
                         "reinforcement": "6-12, confining 12@75, ties 8@190",
                         "governing": {"check": "ductile_column_min_dim",
                                       "clause": "IS13920:2016 7.1",
                                       "utilization": 1.304},
                         "utilization_max": 1.304, "checks": [ ... ]}],
      "element_cards_total": 208, "cards_elided": 60,
      "layout_metrics": { ... }, "disclosures": [ ... ],
      "blocked_elements": [ ... ], "warnings_summary": { ... },
      "bbs": { ... }, "boq": { ... },
      "trace_available": false,
      "meta": {"report_version": "report-1", "schema_version": "structural-1.1",
               "generated_at": null},   // null unless output.generated_at was given
      "disclaimer": "PRELIMINARY ENGINEERING NOTICE. ..."
    }
  } ] } }
}
```

A design with failed members is still `"SUCCESS"`: `design.failed` is populated,
the message counts the failures, and each failed member names its check, its
utilization and the clause it broke. The report is the product; disclosure is
the culture. `"ERROR"` means the pipeline itself could not run.

### Check

```jsonc
{ "status": "SUCCESS",
  "message": "structural check: PASS, 0 hard violation(s), 208 element check(s)",
  "response": { "Documents": { "structural": [ {
    "schema_version": "structural-1.1", "engine_fingerprint": "st-...",
    "units": { ... }, "source": "model", "system": "rc_frame",
    "scope": "full",                    // or "placement"
    "verdict": "PASS",                  // PASS | FAIL
    "hard_violations": [ /* Disclosure objects; a FAIL names the element */ ],
    "layout_score": {"score": 79, "score_version": "frame-1",
                     "placed": { /* the metrics carried forward */ },
                     "recomputed": { /* counted on the model as handed in */ },
                     "hard_violation_count": 0, "basis": "..."},
    "element_checks": [{"element_id": "beam-s0-x1-0", "element_type": "beam",
                        "status": "pass", "pass": true,
                        "check": "flexure_top_right",
                        "clause": "IS456:2000 G-1.1(b)", "utilization": 0.965209}],
    "element_check_count": 208, "element_checks_failed": 0,
    "changed_hint": [], "analysis": { ... }, "options_echo": { ... },
    "input_ref": { ... }, "errors": [], "warnings": [ ... ],
    "status": "ok", "disclaimer": "PRELIMINARY ENGINEERING NOTICE. ..."
  } ] } } }
```

There is no `structural_model` in a check response: a check answers ABOUT a
model, it never restates one, and it never moves an element.

### Refusals

A request the engine will not run comes back as the same envelope with
`status: "ERROR"`, an empty `structural` list and the reason under
`Documents.error`. The bridge maps exactly this to HTTP 400, verbatim, so the
caller keeps the field name AND the notice:

```jsonc
{ "status": "ERROR",
  "message": "a plan carries no storey information, so storeys is required",
  "disclaimer": "PRELIMINARY ENGINEERING NOTICE. ...",
  "response": { "Documents": {
    "schema_version": "structural-1.1", "engine_fingerprint": "st-...",
    "structural": [],
    "batch_summary": {"plans": 0, "ok": 0, "warnings": 0, "refused": 0, ...},
    "error": {"message": "a plan carries no storey information, so storeys is required",
              "type": "ValidationError",     // or "EngineError" with a "code"
              "field": "storeys"}
  } } }
}
```

## The algorithm

`run_design` is the single orchestrator and its sequence is fixed
(finding 18). `run_layout` runs the same first three steps and stops, which is
why layout and design can never disagree on geometry.

1. **Unwrap and validate.** Envelope shapes collapsed, `schema_version` major
   checked, `source` and its block checked, params enums and ranges checked,
   storey caps by system and IS 4326 category, rooms per floor, housing floor
   count. Every refusal names its field.
2. **Adapt.** `adapters/plan_json.py`, `adapters/building.py` or
   `adapters/housing.py` produce one `StructuralModel` per plan (per built plot
   stack for housing): SI metres, y-down, storey 0 = ground, grid-derived kebab
   element ids, openings synthesized ONLY here (0.9 m doors, windows only when
   the target system is masonry).
3. **Place.** `choose_system` decides the system and reports its trace; then
   `grid.extract_axes` plus `placement/frame.py` (columns, primary and secondary
   beams, slabs, plinth beams, lintels over infill openings) or
   `placement/masonry.py` (bearing walls, bands, lintels). The frame placer's
   metrics block plus `score_version` is the layout score. **`run_layout` stops
   here**, adding unsized footing markers at the ground column stacks.
4. **Load model.** IS 875-1 dead loads, IS 875-2 imposed by room occupancy, then
   IS 1893 equivalent-static seismic (which needs the storey weight ledger, so
   the gravity takedown runs once first to weigh the storeys), optional IS 875-3
   wind, then the IS 456 combination roster.
5. **Takedown.** Tributary load path down to the footings, with a conservation
   check that refuses rather than losing load.
6. **Foundations.** `layout_foundations` sizes pads, strips, combined footings
   and straps from the takedown SERVICE loads and the resolved soil.
7. **Diaphragm.** Rigid-diaphragm distribution of the storey shears, with the
   torsion proxy and the pier stiffnesses.
8. **Member design.** Beams, columns, slabs and footings to IS 456 / IS 13920 /
   IS 6403; masonry walls to IS 1905 / IS 4326. Each result carries its checks,
   governing clause, bars with `ld_mm`, and any referrals.
9. **One bounded referral re-pass.** If the designers referred
   `add_secondary_beams` or `confined_masonry_conversion`, placement is re-entered
   ONCE, loads and design re-run once, and then the loop stops: whatever is still
   referred is disclosed as `W_COARSE_ITER`, never chased.
10. **Quantities and report.** Take-off, bar bending schedule, priced bill, then
    the report with the disclosure ladder and the verbatim notice.

Determinism is a contract, not an accident: sorted iteration throughout, no RNG,
no wall clock inside a computed value (`report.meta.generated_at` is null unless
`output.generated_at` is supplied), and `input_ref.hash` is a sha256 over the
canonical request. Two identical calls return byte-identical JSON, which is what
the backend's Redis dedup key rests on.

## Options

Every knob is optional. The resolved value and its origin come back in
`options_echo`, and `GET /api/structural/options/` publishes the same lists
generated from the constants the pipeline enforces (finding 42), so a client can
never drift from the engine by hardcoding an enum.

| `params.*` | Accepts | Default | Origin of the default |
|---|---|---|---|
| `system` | `auto`, `rc_frame`, `load_bearing_masonry`, `confined_masonry` | `auto` | delegated to `placement.masonry.choose_system`; the decision trace ships in the response |
| `code_profile` | `IS` | `IS` | only profile implemented in v1 |
| `seismic_zone` | `II`, `III`, `IV`, `V` | `III` | disclosed as `origin: default` |
| `importance_factor` | a positive number, or an IS 1893 Table 8 category | `1.0` | IS 1893 Table 8, residential |
| `frame_ductility` | `OMRF`, `SMRF` | `OMRF` up to zone III, `SMRF` above | derived from `seismic_zone`, and the echo says so (finding 41) |
| `soil` | `{type: I\|II\|III, sbc_kpa, soft, founding_depth_m}`, or the words `hard` / `medium` / `soft` | `{type: "II", sbc_kpa: 150.0, soft: false, founding_depth_m: 1.5}` | `data/soil_defaults.yaml`; ONE mapping table feeds seismic, foundations and the earthwork take-off (finding 30) |
| `grades.concrete` | `M20` .. `M40` | `M25` | `design/common.CONCRETE_GRADES_MPA` |
| `grades.steel` | `Fe415`, `Fe500`, `Fe550` | `Fe500` | `design/common.REBAR_GRADES_MPA` |
| `grades.mortar` | `H1`, `H2`, `M1`, `M2`, `M3`, `L1`, `L2` | `M1` | `codes/is1905.MORTAR_GRADES` |
| `grades.masonry_unit_mpa` | 3.5, 5.0, 7.5, 10.0, 12.5 | `7.5` | `design/masonry.DEFAULT_UNIT_STRENGTHS_MPA` |
| `exposure` | IS 456 Table 3 exposure words | `moderate` | design layer default |
| `spans.min_m` / `min_ft` | metres, or feet converted on the way in | `2.5 m` (8.20 ft) | `grid.FrameParams.min_span` (finding 35) |
| `spans.max_m` / `max_ft` | as above, hard ceiling 7.5 m | `5.0 m` (16.40 ft) | `grid.FrameParams.max_primary_span` |
| `cantilever.max_m` | metres; above 2.5 m the request is refused | `2.0 m` | `grid.FrameParams.cantilever_cap`; refusal at `placement.frame.REFUSE_CANTILEVER_M` (finding 3) |
| `slab.t_max_mm` | mm | `FrameParams.slab_t_max_mm` | `grid.FrameParams` |
| `walls.exterior_ft` / `interior_ft` | feet | adapter defaults (0.75 / 0.4 ft on the plan source) | the adapter |
| `storey_height_ft` | feet | `10.0` | adapter default |
| `live_load_kpa` | a number | none | ACCEPTED AND NOT APPLIED in v1: imposed loads come from IS 875-2 by occupancy. The override is echoed in `options_echo.unapplied` and disclosed on the ladder rather than silently dropped |
| `wind.basic_speed_ms` | m/s | none | wind is skipped unless a basic speed is given |
| `wind.terrain_category` | 1 .. 4 | `2` | IS 875-3 |

| `output.*` | Default | Effect |
|---|---|---|
| `include_report` | `true` | the `report` block |
| `include_boq` | `true` | the priced bill inside quantities |
| `include_quantities` | `true` | take-off and BBS |
| `trace` | `false` | clause traces are elided by default (size); `true` fills `design[].trace` and `analysis.trace` without changing a single number |
| `report_format` | `"json"` | `"html"` is later |
| `generated_at` | `null` | the ONLY way a timestamp enters a response |
| `validate_only` | `false` | design only: validate and return without placing |

Caps, all published under `options.limits` and all enforced:
`max_storeys_rc` 12, `max_storeys_masonry` 4 (3 in zone V),
`max_rooms_per_floor` 60, `max_housing_floors` 3, `max_cantilever_m` 2.0,
`refuse_cantilever_m` 2.5, `min_span_m` 2.5, `max_span_m` 5.0,
`hard_max_span_m` 7.5, `max_body_bytes` 2000000, `referral_re_passes` 1.

## Tests

Two batteries, both run from the repository root.

```
python -m pytest GPLAN/structural/tests -q     # the package battery, ~60 s
python test_structural_api.py                  # the root battery, ~25 s
```

The package battery pins every stage from the inside: adapters, grid, placement,
cores, foundations, loads, takedown, diaphragm, the design layer per material,
quantities, report, the trace sink, and `tests/test_api_pipeline.py` for the four
entry points end to end against
`schema/structural_response.schema.json` (validated with `jsonschema` when it is
installed, by hand when it is not).

The root battery stands where a caller stands: it imports `GPLAN.api.Documents`
and nothing else, runs the four methods over the three shipped fixtures
(`GPLAN/structural/tests/fixtures/`), and asserts the envelope shape, the
verbatim disclaimer on every path including a validation failure and a stopped
pipeline, byte-identical determinism on repeat calls, and that layout stays
inside its 5 s synchronous budget (measured 0.03 to 0.09 s per fixture; design
runs 1.6 to 10.8 s, which is why design is the async one).

The bridge routes are thin wrappers over the same four methods, so neither
battery starts a Flask server. To exercise them locally:

```
python GPLAN/local_engine_bridge.py            # http://localhost:8027
curl http://localhost:8027/api/structural/options/
```
