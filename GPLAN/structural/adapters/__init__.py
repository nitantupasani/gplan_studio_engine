"""Input adapters: engine plans and frontend payloads to the canonical model.

Three adapters share one contract. Each consumes its own payload shape in FEET
(y-down, origin top-left, the frame door_connectivity and both frontend models
already use), converts to SI metres exactly once at ingestion, and returns a
`StructuralModel` whose every assumption is disclosed on the model's ladder:

  - `plan_json.from_plan`   one engine floor plan, repeated over storeys
  - `building.from_building` the frontend Building payload, multi-storey
  - `housing.from_housing`  a HousingDesign, one model per built plot stack

`_geom.AdapterError` is the shared refusal type: it is raised only when the
structure is underivable or the geometry lies (voids, overlaps, non-rectangular
rooms, unrecognized envelopes). Everything else ships labeled, never hidden.

Opening synthesis belongs to this layer and to no other (finding 10): doors are
0.9 m, windows are assumed only when the caller asks for them.

This module deliberately re-exports nothing; import the adapter you need
directly, so one adapter's import cost is never paid by the others.
"""

from __future__ import annotations
