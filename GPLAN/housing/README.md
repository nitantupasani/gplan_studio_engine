`Documents.get_house_concepts(request_data, progress_callback=None)` returns a
`house_concepts_v1` catalogue. Transport adapters wrap it in
`response.HouseConcepts`. The callback receives replacement catalogue snapshots
containing only complete independently validated houses. An optional
`callback.is_cancelled()` is checked between solves and before publication.

The supported initial scope is a single axis-aligned rectangular detached plot,
one perpendicular bay, a bay with straight front access beside the house, or
a 5200 by 2600 mm bay parallel to the frontage,
ground plus one/two full floors and a gable attic. A complete house has a shared
corner U-return stair, actual circulation doors, aligned sanitary service space,
separate outdoor geometry, and roof-derived occupied/storage zones. Required
unsupported entry/core/party-wall/general constraints are rejected explicitly.
Requested bedroom counts are minimum household requirements. A separate bathroom
and WC is never silently replaced with a combined room.

`schema.py` validates the request cheaply without importing a solver.
`programs.py` defines explicit semantic NL concept roles and finished-face bands;
footprint area determines a programme band. Display names do not select rules.
`concepts.py` searches site/core/ground-layout/floor-programme alternatives in a
bounded deterministic order and deduplicates whole-house geometry.
`solver.py` compiles contact templates into GPLAN's existing
`minimum_dimensioning.main` input. It then uses the same existing longest-path
constraint graphs with exact-envelope equalities and hard upper edges. Every
returned floor has run the actual dimensioner; the seed rectangles describe
topology only. There is no NBC allocation, BHK downgrade, relaxed overlap ladder,
or post-hoc stretching on this path. Legacy solver defaults are unchanged.
`validation.py` independently checks the final geometry and actual openings,
including dimensions after wall deductions, site access with a parked car,
privacy, stairs/platforms/slab openings, roof headroom and area accounting.

The millimetre contract uses integer physical partition, site, core and opening
coordinates. The legacy solver boundary explicitly converts through 304.8 mm/ft
and preserves fractional feet. Shared partition lines quantize once to 1 mm.
Finished-face polygons can retain half-millimetre coordinates for odd interior
wall thicknesses; roof intersections also retain derived fractional precision.
The adapter verifies every native inequality to 0.000305 mm before quantization.
Some feasible native solutions report `False` due to an approximately 1e-15 ft
subtraction residual. Such a result is accepted only after this independent
inequality proof and the unchanged integer-mm/whole-house hard gates; the floor
provenance reports the native status and measured residual.

The default physical stair has two 900 mm flights and a 200 mm well, 18 risers
over a 3000 mm storey, 250 mm goings, a 1000 mm mid landing, and a distinct
1000 mm floor-level platform. Its clear envelope is 2000 by 4000 mm. The
front 2000 by 3000 mm slab opening excludes the rear flat platform. A 900 mm
side opening connects the platform to the floor's circulation room. Gross core
dimensions include the actual exterior/partition wall allowances.

New indoor entrance halls and landings target at least 1000 mm clear width.
Their nominal partition span includes the interior wall thickness plus the
request's maximum 0.5 mm wall-rounding allowance, and is rounded upward to the
editor's 0.01 ft coordinate lattice, then to integer millimetres. This prevents
import rounding from producing a passage below 1 m:
102 mm partitions use a 1104 mm nominal span and 1002 mm source clear width.
An entrance hall can be wider when needed to retain the existing 900 mm door
and its two 100 mm jambs. Stair dimensions, door sizes and outdoor pedestrian
paths retain their own dimensions; saved houses are not resized.

The NL profile is a versioned concept design assumption set, not regulatory or
structural certification. Regular storeys default to 3000 mm, the attic knee
wall to 1500 mm and the gable pitch to 45 degrees. Headroom deducts at least the
renderer roof's 106.68 mm normal thickness projected vertically. Parking access
reserves a straight approach; turning manoeuvres, road permission, fire,
structure, daylight calculations and NEN area measurement remain unassessed.
Parallel frontage parking reserves a 2800 mm forecourt and a clear envelope
from the frontage to the bay, plus an independent pedestrian path around the
represented parked car. Bay dimensions rotate with the requested frontage.
This checks reserved access land; it does not establish a feasible turning or
parallel-parking manoeuvre. Existing perpendicular/side alternatives are searched
first, preserving the existing catalogue order where those alternatives fit.

When five distinct complete houses do not fit the programme, site and search
budget, the catalogue contains fewer with counted rejection reasons. Complete
validated alternatives interleave both stair/parking sides and both ground
living/kitchen arrangements before adding bedroom/storey variants. The same
seed and normalized inputs produce the same geometry and IDs. All floor solves
within a house worker are sequential because the legacy dimensioner uses mutable
module state. Process isolation is required for broader solver concurrency.

Run the real solver regression fixtures from the engine repository root with:

```powershell
python -c "import GPLAN.housing, pytest; raise SystemExit(pytest.main(['--import-mode=importlib','-q','test_house_concepts_solver.py','test_house_concepts_validation.py']))"
```

Pre-importing the inner engine package avoids the repository's existing outer
`GPLAN/__init__.py` pytest name collision. Fixtures cover all four frontage
directions, both full-storey modes, the 11278 by 11582 mm screenshot, the
9144 by 12192 mm default canvas, equal-area narrow/deep and wide/shallow plots,
fractional-unit/wall precision, separate WC, hard failures, repeatability and
cancellation. Validation mutation tests deliberately damage doors, rooms,
parking paths, platforms, stair openings, roofs and declared measurements.
