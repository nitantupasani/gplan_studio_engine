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

Handover docs for new maintainers:
1. [contribution_workflow.md](contribution_workflow.md)
2. [repository_handover.md](repository_handover.md)
3. [api_reference.md](api_reference.md)
4. [testing_handover.md](testing_handover.md)
5. [door_connectivity_update_guide.md](door_connectivity_update_guide.md)
6. [work_history_timeline.md](work_history_timeline.md)
7. [work_history_feature_map.md](work_history_feature_map.md)
