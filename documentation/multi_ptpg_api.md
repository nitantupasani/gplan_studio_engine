# Multi-PTPG Dimensioned Floorplan API

Generates dimensioned rectangular floorplans for **every topological PTPG variant** of one
adjacency graph, instead of for a single fixed topology.

This joins two GPLAN-team branches that each solved half of the problem:

| Branch | What it contributed | What it lacked |
|---|---|---|
| `QA_multi_ptpg` | Enumerates PTPG variants of an input graph (boundary-edge removal + 4-cycle diagonal flips) | Tkinter-only; one chosen variant went to `irreg_multiple_dual()`; no dimensions |
| `ptpg_floorplanner` | The "PDF algorithm" that places rooms at **exact** widths and heights on one graph | No notion of alternative topologies; Tkinter desktop app |

Neither branch was merged. Their algorithms were ported into this repository as headless
modules and the pipeline runs the second over every output of the first.

---

## 1. Pipeline

```
adjacency graph + exact room sizes
  |
  |-- InputGraph.door_connectivity()            -> base PTPG   (source/inputgraph.py)
  |-- multiple_ptpg.enumerate_ptpg_variants()   -> N variants  (source/multiple_ptpg.py)
  |-- [optional interior/exterior room filter]
  |-- ptpg_floorplanner.generate_floorplans()   -> plans per variant
  |                                                (source/ptpg_floorplanner.py)
  '-- floorplans grouped by variant             (source/multi_ptpg_pipeline.py)
```

`irreg_multiple_dual()` is **not** used. The PDF placer replaces the entire dual-construction
and dimensioning half of the engine, which is what keeps room sizes exact.

### Entry points

| Layer | Call |
|---|---|
| Engine | `GPLAN.api.Documents.get_multi_ptpg_floorplans(request_data)` |
| Backend | `POST /api/generate/multi-ptpg`, then poll `GET /api/task/<task_id>/` |
| Local dev bridge | `POST /api/generate/multi-ptpg` on `local_engine_bridge.py` (port 8027) |

---

## 2. Request

```jsonc
{
  "request_id": "optional-client-id",
  "params": {
    "nodes": [
      {"id": 0, "x": 0, "y": 0, "width": 5, "height": 4, "label": "Living", "color": "#1C4C82"}
    ],
    "edges": [{"source": 0, "target": 1, "color": "black"}],

    "plot_width": -1,                  // -1 = unconstrained; a reject filter, not a driver
    "plot_height": -1,

    "max_variants": 200,               // cap on variants returned (default 200)
    "max_depth": 2,                    // BFS depth over the transformations
    "preserve_input_edges": true,      // protect every requested adjacency
    "protected_edges": [[0, 1]],       // overrides the flag: protect only these
    "interior_rooms": [],              // must NOT sit on the outer face
    "exterior_rooms": [],              // must sit on the outer face
    "cardinal_constraints": [          // N/E/S/W pins, same shape as
      {"room": 0, "direction": "N"}    //   door_connectivity's
    ],

    "floorplans_per_variant": 5,
    "max_floorplans": 30,              // TOTAL over every arrangement (default 30);
                                       //   0 or negative lifts it
    "strictness": "relaxed",           // exact | relaxed | best_effort
    "max_boundaries_per_variant": 48,
    "time_budget_seconds": 900,

    "added_room_width": null,          // size for rooms the engine invents
    "added_room_height": null
  }
}
```

### Room sizes are exact, not minimums

This is the premise of the PDF algorithm and the main difference from
`generate/<shape>` with `minDimEnabled`. Every node must carry a positive `width` and
`height`; they are rounded to integers because the placer works on integer cells. Clients
needing sub-unit precision should pre-scale (send centimetres rather than metres).

### `strictness`

Passes are tried in order and the first that yields anything wins.

| Level | Gaps allowed | Extra walls allowed | Missing adjacency allowed |
|---|---|---|---|
| `exact` | no | no | no |
| `relaxed` (default) | yes | yes | no |
| `best_effort` | yes | yes | yes, best-scoring layouts kept |

`relaxed` is what the `ptpg_floorplanner` branch did. Use `best_effort` when the requested
exact sizes admit no true rectangular dual; the per-plan `adjacency` block then reports
exactly what was traded away.

### `preserve_input_edges` vs `protected_edges`

Both transformations work by destroying an existing adjacency, so protecting every input
edge protects everything and the search cannot leave the base graph. With
`preserve_input_edges: true` you will usually get one variant and a warning saying so.

Prefer `protected_edges`: name only the two or three adjacencies that genuinely matter
(kitchen next to dining, say) and let the rest be rearranged. `protected_edges` takes
precedence over `preserve_input_edges` whenever it is present.

### `cardinal_constraints` (N/E/S/W pins)

Same wire format as `door_connectivity`'s, normalized by the same
`GPLAN.api.normalize_cardinal_constraints`, so a client builds one payload for both
endpoints. Pins apply at two levels, and both are needed:

1. **Variant pruning.** A pinned room must be on the outer face, so any variant that
   buries it in the interior is dropped before it is dimensioned. This is where most of
   the work happens: on the shipped 8-room 2BHK, pinning the Kitchen east drops 13 of
   the 26 arrangements outright.
2. **Geometric gating.** Every placed layout is then verified, because the boundary arcs
   are a topological assignment and only the rectangles are the truth. The gate runs
   inside the candidate loop, so `floorplans_per_variant` counts *satisfying* layouts
   instead of filling with violating ones a client would have to discard.

The test is "exterior-facing, and the gap to the bounds is a recess, not a void". The
strip test alone (`GPLAN.api.plan_satisfies_cardinal`) is right for `door_connectivity`'s
gapless tilings, but `relaxed`/`best_effort` layouts here contain real empty space, and
across a void it passes a room nowhere near that side: a 4x6 toilet 11 ft short of the
north edge counted as north-facing. The recess allowance is therefore the smallest room
dimension in the layout, on the principle that a gap which could hold a room is a void.

Note the frame flip. `FloorplanResult.room_rects` puts **y=0 at the bottom**, so N is the
high-y side here, the opposite of the y-down frame `GPLAN.api.plan_satisfies_cardinal`
reads. `GPLAN.source.ptpg_floorplanner.plan_satisfies_cardinal` is the y-up version.

If nothing in the whole request can honour the pins the endpoint retries unpinned and
returns those plans with `data.cardinal.ignored: true` plus a warning naming the pins it
could not place. It never returns an empty gallery and never silently unpins.

```jsonc
"cardinal": {
  "requested": [{"room": 2, "name": "Kitchen", "direction": "E"}],
  "applied": true,      // pins were enforced on every returned plan
  "ignored": false      // true = no arrangement could honour them
}
```

Per variant: `cardinal_satisfied` is `true`/`false`, or `null` when no pins were sent.
Per plan: `cardinal_satisfied` mirrors it. `stats.variants_dropped_by_cardinal` counts
step 1's prunes.

---

## 3. Response

The endpoint is asynchronous. `POST` returns `202` with `{"task_id", "status": "started"}`;
`GET /api/task/<task_id>/` returns the payload below once the task finishes.

```jsonc
{
  "request_id": "...",
  "status": "ok",
  "engine": "MultiPTPG_FloorPlan",
  "error": null,
  "data": {
    "base_ptpg": {
      "node_count": 5,
      "edges": [[0, 1], ...],
      "outer_cycle": [0, 1, 3, 4],
      "outer_face_is_cycle": true,
      "edges_added_by_door_connectivity": [[2, 4]],
      "is_ptpg": true
    },
    "warnings": ["..."],
    "rooms": [
      {"id": 0, "name": "Living", "width": 5, "height": 4, "added_by_engine": false}
    ],
    "variant_count": 9,
    "floorplan_count": 10,
    "variants": [
      {
        "variant_id": 0,
        "depth": 0,
        "operation": "base",            // base | remove_boundary_edge | flip_diagonal
        "detail": null,                 // removed edge, or [u,v,a,b] for a flip
        "is_base": true,
        "edges": [[0, 1], ...],
        "outer_cycle": [0, 1, 3, 4],
        "added_edges": [],              // vs the base PTPG
        "removed_edges": [],
        "nodes": [{"id": 0, "x": 12.3, "y": 45.6}],   // Tutte layout, for drawing
        "status": "ok",                 // ok | no_floorplan | skipped | error
        "reason": null,
        "floorplan_count": 4,
        "floorplans": [
          {
            "rooms": [{"id": 0, "name": "Living", "x": 1.0, "y": 4.0,
                       "width": 5.0, "height": 4.0, "area": 20.0}],
            "width": 6.0, "height": 6.0, "area": 36.0,
            "is_relaxed": false,
            "boundary": {"N": [0, 1], "E": [1, 3], "S": [3, 4], "W": [4, 0]},
            "edge_labels": [{"source": 0, "target": 1, "wall": "red"}],
            "adjacency": {"satisfied": [["0","1"]], "missing": [], "extra": []},
            "encoded_matrix": [[-1, 0, 0, 0, -1, -1]]
          }
        ]
      }
    ],
    "stats": {
      "variants_generated": 9, "variants_after_filter": 9, "variants_returned": 9,
      "strictness": "best_effort", "preserve_input_edges": false,
      "protected_edges": [], "max_variants": 12, "max_depth": 2,
      "elapsed_seconds": 2.05, "truncated": false
    }
  }
}
```

Field notes:

- `edge_labels[].wall` is `green` when the two rooms share a **vertical** wall (side by
  side) and `red` when they share a **horizontal** one (above/below).
- `encoded_matrix` is row 0 = top of the plan, cells hold the **index into `rooms`**, and
  `-1` marks empty space (only possible when `is_relaxed` is true).
- `room.x`/`room.y` use y = 0 at the **bottom**, which is the opposite convention to
  `encoded_matrix`.
- `variants[].nodes` carries the Tutte embedding, so a client can draw the variant graph
  in a gallery the way the `QA_multi_ptpg` GUI did.

---

## 4. Rooms the engine invents

`door_connectivity` resolves separating triangles by deleting and flipping edges on a fixed
node set, so in practice it does not add rooms. It is not guaranteed to, so the pipeline
detects added rooms by index rather than trusting the engine's bookkeeping:

```python
ptpg_node_count = numpy.array(ptpg.matrix).shape[0]   # nodecnt is stale after the call
synthetic_ids   = range(len(client_nodes), ptpg_node_count)
```

Any index at or beyond the client's room count is engine-invented. Such a room gets the
smallest requested width and height (override with `added_room_width` /
`added_room_height`), is named `Room <i> (added)`, and is flagged `added_by_engine: true`
so a client can grey it out or reject the plan. A warning is emitted whenever this happens.

---

## 5. Failure modes

Everything except transport errors comes back as HTTP 200; inspect `status`, `error` and
`warnings`, never the status code. That is the existing house convention: tasks return
error dicts so the Celery state stays `SUCCESS`.

| Situation | Result |
|---|---|
| Fewer than 3 or more than 40 rooms | `status: error`, `ValidationError` |
| Node ids not the contiguous range `0..n-1` | `status: error`, names the first bad index |
| A room missing `width`/`height`, or non-positive | `status: error`, names the room |
| Only red (non-adjacency) edges | `status: error`. Red edges are dropped; `door_connectivity`'s non-adjacency branch is a known hang and is never taken here |
| Invalid `strictness` | `status: error`, lists the valid levels |
| `door_connectivity` fails or the graph is non-planar | `status: error`, `door_connectivity failed: ...` |
| `door_connectivity` returns `is_ptpg: false` | `status: ok` with a warning; the pipeline continues rather than falling back to `irreg_multiple_dual` |
| Outer face is not a simple cycle | `status: ok` with a warning; no variants can be derived, the base is still placed |
| Only the base variant survives | `status: ok` with a warning pointing at `protected_edges` |
| Interior/exterior constraints reject everything | `status: ok`, `variant_count: 0`, warning naming the pre-filter count |
| A variant admits no layout at the exact sizes | that variant gets `status: "no_floorplan"` and a reason; the others still return |
| Layout exceeds `plot_width`/`plot_height` | folds into the above. A tight plot is the **slowest** case, not the fastest, since every candidate is built and then rejected |
| Wall-clock budget exhausted | remaining variants get `status: "skipped"` with reason `"time budget exhausted"`, `stats.truncated: true` |
| `max_floorplans` reached | arrangements past the cap get `status: "skipped"` with a cap reason, `stats.floorplan_cap_hit: true`, plus a warning. Counted separately from the time skips so the two are never confused |
| Exception inside one variant | that variant gets `status: "error"` with the message; the others still return |

---

## 6. Cost and tuning

Runtime is roughly `variants x boundaries x compaction`. The compaction pass is the
expensive part and it runs per candidate boundary.

| Knob | Effect |
|---|---|
| `max_depth` | **The lever that matters.** Each level multiplies the variant count and costs one more of the user's adjacencies. Default 2 |
| `max_variants` | A backstop, not a display cap. Set it above the closure size or the BFS stops MID-LEVEL and returns an arbitrary slice of one depth. `stats.variant_cap_hit` plus a warning fires whenever it binds |
| `max_boundaries_per_variant` | The boundary enumeration is `O(k^4)` in outer-cycle length when the CIP machinery finds no shortcuts; this caps it |
| `floorplans_per_variant` | Stops each variant early once it has enough plans |
| `max_floorplans` | Hard cap on the TOTAL, default 30, the same size catalogue `door_connectivity` returns. Spent breadth-first: every arrangement gets one plan before any gets a second, so it costs depth before it costs arrangements. Arrangements past the cap are never dimensioned at all, which is where it buys time back on a 4BHK. `stats.floorplan_cap_hit` plus a warning naming the emptied arrangements fires whenever it binds; set it to 0 for the whole set |
| `time_budget_seconds` | Hard wall-clock stop, and the *real* bound at depth 2 for large programs. Variants are dimensioned base-first then by depth, so what gets skipped is always the most-mutated end of the set. Keep it at or below 900 so the Celery soft limit (1500 s) never fires first |

### Measured closure sizes (2026-07-30)

Node counts are after `door_connectivity`; the shipped frontend programs at
`preserve_input_edges: false`.

| Program | Rooms | Base edges | depth 1 | depth 2 | depth 3 | depth 4 |
|---|---|---|---|---|---|---|
| 2BHK | 8 | 15 (8 drawn + 7 added) | 6 | **26** | 111 | 351 |
| 3BHK | 10 | 19 | 8 | **41** | 185 | 671 |
| 4BHK | 12 | 24 | 14 | **107** | 616 | 2842 |

Enumeration is nearly free (0.02-0.8 s). Dimensioning is not: 0.6 s per variant on the
2BHK, 1.4 s on the 3BHK, 2.0 s on the 4BHK, and roughly double those when `relaxed`
returns nothing and the `best_effort` pass also runs. Hence `max_variants: 200` and
`max_depth: 2` as defaults: 200 covers the complete depth-2 closure for every shipped
program, and depth 3 fits no interactive budget.

End to end at the frontend's `time_budget_seconds: 240`, `best_effort`, one E pin:

| Program | Arrangements | Plans | Time | Outcome |
|---|---|---|---|---|
| 2BHK | 13 (of 26; 13 pruned by the pin) | 18 | 14 s | complete |
| 3BHK | 41 | 49 | 76 s | complete |
| 4BHK | 107 | 90 | 240 s | 24 arrangements skipped, reported in `warnings` |

The old defaults were `max_variants: 40`, `max_depth: 3`, and the frontend sent 12. Both
could only ever return a truncated level, so a client showing "N arrangements" was
presenting an arbitrary slice as though it were everything the brief admits.

---

## 7. Source layout

| File | Contents |
|---|---|
| `GPLAN/source/multiple_ptpg.py` | Outer-face detection, the two transformations, bounded deduplicated BFS (`stats` out-param reports why it stopped), PTPG validation, Tutte embedding, interior/exterior filter |
| `GPLAN/source/ptpg_floorplanner.py` | The PDF placer: boundary enumeration, `_pdf_place`, compaction, the strictness ladder, and the y-up cardinal gate (`plan_satisfies_cardinal`, `order_boundaries_by_cardinal`) |
| `GPLAN/source/multi_ptpg_pipeline.py` | Orchestration, validation, cardinal normalization and the pin relaxation ladder, the request/response envelope |
| `GPLAN/api.py` | `Documents.get_multi_ptpg_floorplans` |
| `local_engine_bridge.py` | Local Flask route, no Django/Redis/Celery |
| `test_multi_ptpg.py` | Test suite; run `python test_multi_ptpg.py` from the repository root |

### Fixes carried over the branch implementations

The ported code corrects defects present in the originals. Do not regress these:

- `process_ptpg_recursive` never recursed; the branch called it once, so only depth-1
  variants existed. The port runs a real bounded breadth-first closure.
- Stage 1 compared raw `(u, v, colour)` triples against a list, so protected edges were
  deleted anyway. `user_needs` is now normalised once into a set of sorted pairs.
- `find_4_cycles_filtered` did `if u > v: continue`, silently dropping the entire flip
  stage whenever `networkx` emitted an edge in descending orientation. Edges are now
  normalised instead.
- Stage 1 hardcoded `forbidden_cycles: None`, discarding accumulated history on the next
  step. The incoming set is now threaded through.
- There was no dedup, and a caller-driven BFS duplicated 45 to 63 percent of variants past
  depth 1. Variants are now keyed on `frozenset` of sorted edges.
- A flip was not guarded against the opposite diagonal already existing, which turned the
  flip into a silent edge deletion.
- Variants were never validated. Each is now checked for planarity, connectivity,
  biconnectivity, minimum degree, the internal-triangulation invariant, and a simple outer
  cycle.
- The placer's topological failsafe ignored `plot_width`/`plot_height` even though it only
  runs when a plot was supplied, so impossible plots came back with overflowing layouts.
- The placer re-triangulated its input, which would have added back the very edge a
  boundary-removal variant had just dropped. `already_ptpg=True` skips that.
