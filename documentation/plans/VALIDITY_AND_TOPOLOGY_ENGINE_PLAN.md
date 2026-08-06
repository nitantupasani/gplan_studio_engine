# Engine plan: architectural validity and topology diversity

STATUS 2026-08-06 (same day, second pass): **E1, E2a and E3 are IMPLEMENTED
and bridge-verified**; E4 and E5 stay open. Engine batteries after the
changes: test_multi_ptpg 104/104 (T3g added for E1's groups), test_api_postprocess
49/49, test_api_cardinal_constraints all pass, test_max_dimensions 14/14 (T2
caught and forced the E3 warning-contract fix below). Per-change outcomes:

- **E1 implemented as `protected_edge_groups`** (disjunctive, keep-one-of-each
  -group), NOT as the flat `protected_edges` this plan originally sketched.
  The flat field already existed engine-side, unused; wiring the client to it
  was measured to COLLAPSE the search (2BHK: 30 plans/17 topologies -> 8/2),
  because a bedroom with two hall edges needs ONE of them and protecting both
  forbids exactly the valid variants that trade one hall wall for the other.
  Groups (multiple_ptpg.normalise_protected_groups, _deletion_blocked; pipeline
  `protected_edge_groups` param, stats echo; client derivation in
  multiPtpg.ts): 2BHK 20/23 valid (was 25/30, but hall access now holds BY
  CONSTRUCTION and dimensioning wastes nothing on stranded variants), 3BHK
  25/30 valid up from 19/30 at 13 valid topologies, 4BHK 73s instead of 240s.
- **E2a implemented**: `_shared_wall_length` + per-plan `adjacency_shortfalls`
  on the door response (api.py serialization loop), judged against the
  REQUESTED edges at the request's `min_door_overlap` (default 2 ft), message
  names the affected plan count; client maps the pairs onto
  `plan.missingAdjacencies` (doorConnectivity.ts).
- **E3 implemented**: `_scaled_caps` + `GAP_FILL_SLACK` (1.5x) bounded pass
  between the capped and uncapped fills in `rectangularize_output`; the
  uncapped pass survives as last resort only. Contract fix forced by
  test_max_dimensions T2: the over-ceiling warning is now judged on FINAL
  geometry, not on whether the uncapped pass ran - the bounded pass overshoots
  too, and a silent 1.4x bathroom is still a lie.
- **E2b IMPLEMENTED too** (third pass, same day, user order: "each adjacency
  must be at least big enough to fit a door"). Three coupled fixes in the
  min-dim path, all verified on the shipped 2BHK brief:
  * `DOOR_OVERLAP_FLOOR = 3.0` in `minimum_dimensioning.py`, applied to RED
    adjacencies. Ground truth uncovered on the way: in this solver's input
    RED marks the BRIEFED door edges (black = triangulation extras), and the
    legacy red floor was 0.1 ft - THE source of the 0.0-0.3 ft corner slivers.
    A first patch raised the black floor instead; measurement caught it.
  * `input_adjacency` orientation classifier rewritten: the old exact `==`
    chain defaulted corner contacts and float jitter to a garbage type-3,
    wiring feasible-but-meaningless constraints (solver reported success with
    the pair 8 ft apart). Now tolerance-based on which walls touch AND
    perpendicular overlap; corner-contact pairs are SKIPPED (nothing to
    orient) and E2a disclosure names them on the finished plan.
  * `solve_min_dim` is a four-rung ladder (full -> legacy-0.1 overlap ->
    ceilings stripped -> both), each rung on a fresh deepcopy - min_dim.main
    mutates its input in place (1-based bumps), and re-solving a touched dict
    double-bumps ids and crashes `tblr_rooms` (found the hard way).
  * Client `MIN_DOOR_OVERLAP_FT` 2 -> 3: the post-process trim used to
    "protect" doors down to 2.0 ft, below the dresser's 2.8 ft placeable
    minimum, quietly re-carving what the solver had guaranteed.
  Measured on the 2BHK brief: Kitchen-Dining shared wall now 8.25-14.0 ft in
  30/30 door plans (was routinely 2.0-2.8); remaining shortfalls are
  Living~Dining 30x and Living~Bedroom 2 13x, see E6.
- **E7 IMPLEMENTED 2026-08-06 (fourth pass, same day): priority-edge
  catalogue ordering** (`priority_edges` on multi-ptpg). User concern:
  arrangements keeping the living room's access adjacencies (Living to each
  bedroom, Living to a bath) should LEAD the catalogue, with relaxed
  diversity after, because list order is load-bearing twice in stage 3: the
  max_floorplans cap fills round-robin from the front and never dimensions
  the arrangements past it, and the time budget cuts the tail, so the order
  decides which arrangements get laid out at all under a budget. E7 is a
  stable sort of the variant list by how many priority pairs each keeps
  (membership in the variant's edge set is the whole truth, the search only
  deletes and flips edges), base/depth order preserved inside each tier; it
  never filters, unlike protected_edge_groups, which stays the tool when a
  guarantee rather than a lead is wanted, and the two compose. Per-variant
  `priority_satisfied`/`priority_missing` plus a top-level `priority` echo
  appear only when the field was sent, so old clients see unchanged
  responses; degraded outcomes (pair not in the base arrangement, no
  arrangement keeps all) are warned, never silent. Battery: test_multi_ptpg
  116/116 (T12 added: orders keepers first, filters nothing, echo matches).
- **E6, NEW, not implemented: separating-triangle resolution deletes briefed
  edges and should prefer sacrificing non-briefed ones.** On the shipped 2BHK
  brief the door path's ST handling deterministically REPLACES the briefed
  Living-Dining edge with a non-briefed Kitchen-Bedroom 2 diagonal before any
  candidate is enumerated, so every plan of the batch realises L-D at 0.00 ft
  (now visible thanks to E2a; the dossier's "cases 3 to 5 delete user-drawn
  adjacencies with no record" was this). The resolution has a choice of
  diagonal; it should weigh briefed-ness. Owning code:
  `source/irregular/septri.py` door handlers (359-1144) - delicate, thin test
  cover, deliberately not touched in this pass.
- **New residual, out of this plan's scope**: at the 4BHK's 9-10 rooms the
  PLACER (`ptpg_floorplanner._pdf_place`), not the enumeration, is the
  bottleneck - graph-protected variants still arrive with interior holes and
  briefed walls unrealised (12 of 17 plans with holes, plans dropping 8-11
  briefed walls geometrically). Multi-PTPG validity at that scale needs placer
  fidelity work; door_connectivity plus the client gate carry the type
  meanwhile.

Original plan below, kept for the record. Written 2026-08-06 from bridge
measurements across the 2BHK / 3BHK / 4BHK default briefs (frontend repo,
`scripts/exp2bhk.ts` harness through the real client). The frontend half of the
same effort SHIPPED the same day and is documented in the designer repo's
CLAUDE.md: equal-bedroom briefs, `prefer_rectangle: false` on generation, and a
client-side validity gate (`planAllIssues`) that hides non-compliant plans
behind a toggle. This document is the engine half, ordered by measured impact.

## The evidence base

Validity below = zero hard issues under the client audit: rulebook (min area /
min width / aspect / hierarchy / exposure), door-width (>= 2.8 ft) hall access
for bedrooms and kitchen, a guest-reachable bath/WC, utility-on-kitchen,
reachability from the living room through dry rooms, no interior holes, no wet
or service room 1.5x past its practical ceiling (1.6x for others).

| brief | multi-ptpg valid | door_connectivity valid | dominant failure |
|---|---|---|---|
| 2BHK old (8 rooms, 14 edges) | 14/30 | 0/12 | variant search drops Kitchen-Utility (8x); door WCs 1.9-2.5x over cap |
| 2BHK shipped (7 rooms, 11 edges) | 25/30 | 22/22 | 5x a bedroom's or the guest bath's last hall edge dropped |
| 3BHK old (10 rooms, 10 edges) | 0/13 | 0/30 | every door plan realises Dining-Bedroom 2 at 0.00 ft; multi strands rooms |
| 3BHK shipped (8 rooms, 14 edges) | 19/30 | 20/28 | same last-hall-edge mechanism |
| 4BHK old (12 rooms, 13 edges) | 0/11 | 0/30 | interior balconies, 128 sqft baths, unreachable rooms |
| 4BHK shipped (9 rooms, 15 edges) | 6/30 (30 distinct topologies) | 13/30 | variant search strands bedrooms at this room count |
| 4BHK rejected variants (10 rooms w/ WC, 17-19 edges) | 1/25 and 1/30 | 0-12/30 | denser hall hubs make the search drop MORE hall edges; bedroom-only baths create separating-triangle cul-de-sacs |

Three engine-side mechanisms produce the residual invalid plans, and no brief
tuning removes them (measured: densifying edges backfires - the 2BHK toilet's
third edge took multi from 25/30 to 12/30; the 4BHK's full both-hall
redundancy, hall degree 8, took it to 1/30):

1. **The multi-PTPG variant search deletes load-bearing edges.** Every
   remaining invalid multi plan across all three types is a variant that
   dropped a bedroom's last hall edge, the guest bath's hall edge, or
   Kitchen-Utility.
2. **The door path's adjacency guarantee is combinatorial, not metric.** The
   dimensioning can realise a briefed edge as a 0.0-0.3 ft corner contact
   (3BHK old brief: Dining-Bedroom 2 at 0.00 ft in 28 of 28 plans). No door
   fits; `min_door_overlap` post-processing cannot resurrect a zero-length
   wall.
3. **The gap fill inflates rooms past their ceilings.** On 8+ room briefs the
   plot cap is unsatisfiable, the batch expands, and `_fill_gaps` +
   `rectangularize_output` hand the slack to rooms: WCs land at 1.5-3x their
   practical maximum. `prefer_rectangle: false` (client-shipped) lets the
   post-process trim them back at the cost of notched outlines, which is a
   mitigation, not a fix.

## Changes, by priority

### E1. Protected edges in the multi-PTPG variant search  [highest impact]

Request field `protected_edges: [nodeIndexPair, ...]` on
`POST /api/generate/multi-ptpg`. The variant search
(`multi_ptpg_pipeline` -> variant enumeration; boundary-edge removal and
diagonal flips) never deletes a protected edge; a variant whose op would
require it is skipped. `preserve_input_edges` stays as the all-edges special
case. Fallback when protection leaves no variants: return the base arrangement
with a warning naming the binding protections (mirror the cardinal
`ignored` pattern, never an empty batch).

Client derivation (frontend change, same day it lands): protect each bedroom's
hall edges, one hall edge of one wet room (guest access), and Kitchen-Utility
when a Utility exists.

Expected effect, from the failure ledgers: 2BHK 25/30 -> ~30/30, 3BHK 19/30 ->
~26+/30, and it is the unblocking condition for a 10-room 4BHK multi batch
(today 1-12/30 with bedrooms stranded in most plans).

Verify: rerun the frontend harness briefs; assert no plan drops a protected
edge; `test_multi_ptpg.py` gains a protected-edges case.

### E2. Metric floor for briefed adjacencies in door dimensioning

A briefed edge must be realised with shared wall >= the request's
`min_door_overlap` (default 2 ft) or be REPORTED as dropped on the plan.
Options, in cost order: (a) post-solve check per plan + demote/annotate, so
the client can gate honestly; (b) LP constraint in `solve_min_dim` tying the
overlap variables of briefed neighbours to >= the floor, releasing per
topology when infeasible exactly like the ceiling ladder. Start with (a):
it is serialization-only and turns mechanism 2 from silent to disclosed.

Verify: 3BHK old brief - 28/28 plans must either realise Dining-Bedroom 2 at
>= 2 ft or carry it in a `missing_adjacencies` field.

### E3. Gap-fill discipline: cap growth at the ceilings

`api._fill_gaps` and the expansion fallback currently grow rooms without
bound; the fix is to stop each room at its supplied max area/spans and leave
the residual as open space (the client already renders open space and the
post-processor already reports it). This makes rectangle-first viable again
for briefs that want it; until then `prefer_rectangle: false` stands in.

Verify: 8-room 2BHK old brief, rectangle mode: WCs must stay <= 1.5x cap.

### E4. Arrangement identity on door plans

Door plans carry no equivalent of multi-ptpg's variant id, so the client
dedupes arrangements by a centroid-relation heuristic (measured exact on the
2BHK batch: 12 plans -> 6 arrangement pairs). Serialize the REL/boundary
index per plan (`arrangement_id`) so grouping and "distinct arrangements
first" ordering are exact. Small change in the door handler's response
assembly.

### E5. Multiple triangulations on the door path  [largest, optional]

`irreg_multiple_dual` triangulates ONCE (`source/inputgraph.py:899`); the
catalogue then varies boundaries and RELs of that single graph, so every door
plan realises the same adjacency graph by construction (separating-triangle
covers, the one in-engine source of alternatives, rarely fire). True
"different adjacency graph" diversity from this engine means enumerating the
diagonal choices of non-triangular faces during triangulation and running the
downstream pipeline per triangulation. Only worth building if that guarantee
must come from door_connectivity rather than from multi-PTPG, which already
provides it.

## Order of work

E1 -> E2(a) -> E3, then E4 as a small follow-up; E5 only on demand. E1 and E2
are what the shipped frontend gate is waiting on: today it HIDES the residual
invalid plans; with E1+E2 the engines mostly stop producing them.
