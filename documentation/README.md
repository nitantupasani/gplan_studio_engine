# GPLAN Documentation

This folder now contains both the restored web-API documentation and the newer handover docs.

**Changing an algorithm? Start here:** [algorithms/README.md](algorithms/README.md).

The docs listed below describe the API surface: what a request looks like and what comes back. They do not
explain how the engine works inside. The algorithm pointer document does: it maps each change you might want
to make ("make rooms respect maximum dimensions", "add a new shaped floorplan") to the files that implement
it in reading order, the invariants you must not break, what breaks silently elsewhere, which copy of a
duplicated file is the live one, and which defects are already known. It is backed by 35 detailed dossiers in
`algorithms/graph/` and `algorithms/dim/`, each written against the source and independently verified.

Restored web-API docs:
- [api_flow_and_translation.md](api_flow_and_translation.md)
- [door_connectivity.md](door_connectivity.md)
- [space_optimization_api.md](space_optimization_api.md)
- [ga_optimization_api.md](ga_optimization_api.md)
- [postprocess_api.md](postprocess_api.md) - NBC post-processing of dimensioned
  floorplans (aspect bands + service-room ceilings, notched outlines allowed)
- [allocate_api.md](allocate_api.md) - the area-budget allocator behind
  `POST /api/allocate`: per-room size envelopes that sum to the plot, tiered
  surplus distribution, clear-floor-to-rectangle wall allowance

Implementation plans:
- [plans/DOOR_CONNECTIVITY_SIZING_AND_POSTPROCESS_PLAN.md](plans/DOOR_CONNECTIVITY_SIZING_AND_POSTPROCESS_PLAN.md) -
  how room size should be decided on the door_connectivity path: an area-budget
  allocator, an aspect-preserving post-processor, centre-in-plot, and a frontend
  constraints UI. Read sections 2 and 3 before touching dimensioning: they record
  measured facts that contradict several docstrings, including that 23 of 24 NBC
  ceilings are inert in the min-dim solver and that the aspect band never reaches it.
  Implementation status (2026-07-30): change A (aspect-safe post-processing) and
  change B part 1 (the allocator + endpoint, [allocate_api.md](allocate_api.md))
  are built and verified; the plan's Section 9 acceptance numbers are recorded in
  the commit messages.
- [plans/CARDINAL_CONSTRAINTS_MULTI_PTPG_PLAN.md](plans/CARDINAL_CONSTRAINTS_MULTI_PTPG_PLAN.md) -
  bringing N/E/S/W pins on the multi-PTPG (alternative arrangements) endpoint up to
  parity with the door_connectivity path. A first cut shipped 2026-07-30; this plans
  the rest. Section 1 records the settled priority (a pin outranks an adjacency, an
  adjacency outranks arrangement count) and Section 2 records the fact that decides
  the design: porting the door path's cardinal outer ring here disables Stage 1 of
  the variant search, because a Hamiltonian outer cycle leaves no interior room for
  a boundary-edge removal to promote. Read both before porting anything from
  [cardinal_constraints.md](cardinal_constraints.md). Written 2026-08-01, not yet
  built.

Handover docs for new maintainers:
1. [contribution_workflow.md](contribution_workflow.md)
2. [repository_handover.md](repository_handover.md)
3. [api_reference.md](api_reference.md)
4. [testing_handover.md](testing_handover.md)
5. [door_connectivity_update_guide.md](door_connectivity_update_guide.md)
6. [work_history_timeline.md](work_history_timeline.md)
7. [work_history_feature_map.md](work_history_feature_map.md)
