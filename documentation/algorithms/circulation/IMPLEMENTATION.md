# Headless circulation implementation and ownership

Implemented 2026-09-11. The public engine entry point is
[`GPLAN.circulation_engine`](../../../GPLAN/circulation_engine/__init__.py), schema
`1.0`, algorithm version `1.0.0`. Read [RESEARCH.md](RESEARCH.md) for the
status-quo comparison and experiments, and [CAPABILITIES.md](CAPABILITIES.md) for
the supported geometry and exact-versus-heuristic claims. The existing-landing
extension below was added after a normal Dutch first floor exposed that an
already connected landing must not be forced through the wall-seam graph.

## Reusing an existing landing or hall

The explicit `existing` mode accepts `circulation_room_ids`,
`wall_thickness: {interior, exterior}`, and `entry.opening_id`. For an upper
floor, `entry.stair_room_id` explicitly identifies the protected/locked stair
owner of that saved stair-to-landing doorway. At ground level, an existing
exterior entrance into the designated hall is accepted. Stable semantic IDs
come from the adapter; a room is never treated as public transit merely because
its name resembles a corridor. This mode is implemented in
[`existing.py`](../../../GPLAN/circulation_engine/existing.py).

The mode bypasses both wall-graph routing and allocation. All original room
polygons, IDs and openings remain unchanged. `reused_room_ids` identifies those
same existing public rooms, and each contribution remains zero. Generic sizing
presets that the original Dutch plan did not satisfy are inherited without
worsening: annotating a landing does not resize bedrooms or claim to recertify
the original architecture. Explicit required destinations exclude the reused
circulation room IDs and must have usable saved doors directly into that public
surface. No private-room shortcut or newly generated door can establish access.

The output corridor polygon is the **clear floor** of the designated source
footprint, with `source_polygon`/`source_holes` retaining that nominal footprint.
Interior room boundaries remove half the supplied interior wall thickness;
exterior boundaries remove the full exterior thickness because existing plan
envelopes follow the wall's outer face. Existing walls retain their position:
consumers must not apply the new-corridor wall offset to reused circulation.
The exact Dutch fixture's 1202 × 9500 mm nominal landing becomes
1100 × 9196 mm clear floor with 102 mm interior and 152 mm exterior walls. Its
850 mm room doors and 900 mm stair portal remain exactly their existing sizes.

Clear width is validated through every branch, separately from the requested
doorway width. Orthogonal square erosion and reconstruction use explicit edge
rectangles so short wall steps remain exact; GEOS offset simplification had
introduced diagonal slivers and incorrectly reduced a 3.61 ft landing's measured
width to 2 ft after a 0.01 ft wall move. The connected-core and full-branch
reconstruction checks still reject genuine narrow necks and dead-end branches.
Door approaches must connect their original wall position to
the clear floor inside the designated source footprint. Multiple designated
public rooms are supported only when a saved full-width `opening` covers the
entire internal separator; simply unioning rooms must never erase an existing
wall or doorway. Unsupported joins or inadequate clearance produce an explicit
existing-circulation diagnostic without falling back to carving.

`metrics.area`/`clear_area` report clear floor area, `source_area` reports the
nominal footprint, and `total_room_area_taken` remains zero. `clear_width` is the
measured limiting width under the declared orthogonal clearance model. No
walking length is invented: `length_model` is
`not_measured_existing_surface`, `centerlines` is empty and consumers omit the
length value. The algorithm is labelled **Existing landing/circulation** with
`optimality: not_optimized`, never spanning or shortest.

Independent validation checks exact unchanged rooms/openings, the authorized
source footprint and wall-derived clear floor, direct existing access, entry
ownership and zero contributions. Public validation then reproduces the same
candidate to reject altered reuse IDs, source/clear geometry, wall settings,
metrics or opening semantics. The reviewer suite includes the exact Dutch
dimensions, unsuitable private/stair/window entry cases, too-narrow clear floor,
voids, hidden internal separators and candidate tampering.

## Decision and ownership

For **new** circulation, the service retains rectangular room boundary shifting and derives corridor
surfaces from the intended gaps. It does not derive circulation from the entire
plot-minus-rooms remainder. A corridor is the union of each original room minus
its adjusted room, so empty garden/courtyard space and fixed cores never become
circulation accidentally. These saved polygons are annotated `wall_free: true`;
they are not rooms and must not create physical perimeter walls in a consumer.

The old algorithm's approach is extended in two necessary ways: touching
collinear shared-wall segments share one pair of offsets, and allocation works
on actual post-shift room areas under hard constraints. A distinct polygon
carving strategy is not registered. Irregular room polygons and shifted sides
that are only partly shared with other rooms are rejected explicitly. T
partitions work when the contiguous contact union covers each shifted full side.
Those restrictions apply to changing room boundaries. Explicit `existing`
reuse can retain valid irregular room polygons and orthogonal public landings
unchanged, subject to its separate clear-floor and saved-access checks above.

| Responsibility | Canonical owner |
| --- | --- |
| Public types, finite JSON validation, bounds, stable IDs, units | [`models.py`](../../../GPLAN/circulation_engine/models.py) |
| Registered modes, labels, versions, runtime/capability boundaries | [`registry.py`](../../../GPLAN/circulation_engine/registry.py) |
| Contact grouping, connected traversal, pruning, exact fixed-graph shortest | [`algorithms.py`](../../../GPLAN/circulation_engine/algorithms.py) |
| Global coordinated offsets and actual-area contribution policies | [`allocation.py`](../../../GPLAN/circulation_engine/allocation.py) |
| Gap union, provenance, entrance contacts, shifted door/window reconciliation | [`geometry.py`](../../../GPLAN/circulation_engine/geometry.py) |
| Existing public landing/hall reuse, original stair/entry ownership, physical wall clearance and immutable access | [`existing.py`](../../../GPLAN/circulation_engine/existing.py) |
| Independent polygon, clearance, area, identity and doorway checks | [`validation.py`](../../../GPLAN/circulation_engine/validation.py) |
| Immutable generation, deterministic IDs/dedup, ranking, bounded search, apply validation | [`service.py`](../../../GPLAN/circulation_engine/service.py) |
| Thin shared HTTP error/status adaptation for Django and Flask | [`http.py`](../../../GPLAN/circulation_engine/http.py) |

The engine has no GUI, global mutable request state, plotting calls, network or
filesystem side effects. It uses the existing Shapely and SciPy dependencies;
these modes need no native GPLAN corridor DLL/`.so`. Each request owns fresh
graphs, solver inputs and output polygons.

## Routing and allocation

Each node is a complete shared-wall run. Its positive cost is the full original
run length, because activating it moves complete rectangular sides. Runs meet
when their original line segments intersect. The entry must terminate a
supported run on the original exterior boundary; the service never obtains
entry access by passing through a bedroom or another private room.

`spanning` visits this graph breadth first until all requested rooms have a
selected incident run. `compact` incrementally attaches a path with a low added
length per newly covered room, then removes a run only when both connectivity
and coverage survive. It makes no global minimum claim. `shortest` requires one
destination and uses Dijkstra with full node/run costs. Its result minimizes the
sum of activated original wall-run lengths on that fixed graph. The geometry
must then pass allocation and validation; an infeasible graph optimum is
rejected, not replaced while retaining an exact label.

`metrics.length` reports that declared reference-run cost and is accompanied by
`length_model: sum_activated_reference_wall_group_lengths`. Physical shifted
centerlines extend to adjoining shifted junctions and have a separate measured
`metrics.centerline_length`. Neither value is claimed to be the shortest
Euclidean walking route through an arbitrary polygon.

For each selected run, the allocation variable is the inward movement of its
negative-coordinate side; the positive side moves by `width - offset`. A room's
final width and height include every incident selected side. SLSQP minimizes
actual removed-area deviations from a proportional target, using the following
per-room weights:

| Policy | Target weight |
| --- | --- |
| `area` (default) | Original room area |
| `surplus` | Original area minus the larger of minimum area and minimum width × minimum height |
| `equal` | One, giving equal actual removed areas where feasible |
| `protected` | Original room area, with the selected protections retained |

Locked and protected rooms contribute zero under **every** policy. The
`protected` choice exposes that preference explicitly; without differing room
protections its allocation is equivalent to `area`. Preferences never weaken
minimum width, height, area or maximum aspect ratio. Collinear coordination and
hard constraints can prevent the ideal proportions; candidate diagnostics say
so, and per-room contribution rows always report the actual polygon areas.
Corner areas are counted exactly once through polygon union/difference.

## Clearance, access and existing openings

Independent validation requires the corridor to be one valid polygon, free of
room overlap, inside the original boundary including holes, and disjoint from
fixed obstacles. Mitred erosion by just below half the requested width must
produce one connected nonempty core. Dilating that core back must cover the
corridor; this second check detects thin dead branches that vanish during
erosion. Requested room doorways must directly meet the corridor on an adjusted
room wall with enough contact length. Graph coverage alone is never sufficient.

Overlay operations sometimes split one straight entrance contact at the old
room seam. Contact extraction coalesces collinear pieces without merging around
bends, so asymmetric contribution does not make a valid full-width entrance
appear too narrow. The entry's reference point remains on the mouth; an
explicitly replaced entrance is located at the actual mouth midpoint.

Existing openings are preserved on their owning adjusted wall or reconciled
into room-facing openings on the two sides of a new corridor, retaining their
`source_id`. Windows that would become internal corridor windows are rejected.
An existing narrower room access can be widened to the requested doorway width
when it fits the same wall contact without conflicting with another opening;
this is reported explicitly and does not add a duplicate doorway.
An existing entrance that cannot reach the new corridor is rejected unless
`entry.replace_existing` explicitly authorizes replacement. A locked core gets
no new door merely because circulation touches it; if it is explicitly required,
it must have a compatible existing doorway. Generated access doors belong to
requested rooms; no doors separate corridor branches.

Corridor width is the clear **surface** width. Consumers must place adjacent
room wall material within the room side of this boundary to avoid consuming
the promised corridor width. Room minima must be supplied in the same geometric
convention by the frontend adapter. Furniture/asset placement stays in that
adapter, which must reconcile or reject objects outside an adjusted room.

## Contract, persistence and verification

```python
from GPLAN.circulation_engine import (
    get_capabilities, generate_circulation, validate_circulation,
)

catalogue = generate_circulation(request)
check = validate_circulation({"request": request, "candidate": catalogue["candidates"][0]})
assert check["valid"]
```

Generation does not mutate the request. Candidates carry both the caller's
source fingerprint and an engine SHA-256 fingerprint of the complete request,
including settings. The engine checks actual geometry independently, then
public apply validation regenerates the deterministic candidate and compares
semantic geometry, provenance, openings, metrics and algorithm metadata. A
forged label, shortened window, altered centerline or stale baseline is rejected
even if its remaining polygon checks look plausible. Serialization round trips
are covered; candidate replacement always starts with the immutable baseline.

The catalogue ranks only feasible candidates, by area then declared run length.
Equivalent room/surface/opening geometry appears once, with a structured
`duplicate_geometry` explanation. `search.complete`, status and diagnostics
disclose time/candidate limits. A rejected route is never shown as an alternative.

Run from the outer `GPLAN/` directory with the installed engine dependencies:

```text
python -m unittest discover -s GPLAN/circulation_engine/tests -v
python documentation/algorithms/circulation/run_experiments.py
```

The production suite covers actual proportional/equal/surplus allocation,
protected/locked constraints, infeasible widths, connected branching and T
partitions, fixed obstacles/holes/outdoor space, room identity, units,
entry/opening changes, stale source rejection, JSON bounds, deterministic
reload/dedup, GUI-free import and the legacy south/top-edge regression. The
independent reviewer suite adds malformed and forged candidate cases, a thin
dead branch with apparently valid doorway lengths, and exhaustive fixed-graph
shortest comparisons.

## Historical code ownership

| Existing implementation | Status after this addition |
| --- | --- |
| [`GPLAN/circulation.py`](../../../GPLAN/circulation.py) | Retained for legacy GUI callers; the paper's independent `rel_push_T` southward fix is applied. Its unconnected greedy pruning is not used by this service. |
| [`source/circulation/circulation.py`](../../../GPLAN/source/circulation/circulation.py) | Historical standalone duplicate, no new API owner; retained for comparison. |
| [`source/multiple_circ.py`](../../../GPLAN/source/multiple_circ.py) | Historical standalone enumeration fork; unsupported as a service algorithm. |
| [`Space_Optimization/corridor_creator.c`](../../../Space_Optimization/corridor_creator.c) | Raster gap labelling used by the GA optimizer; separate grid/native-library prerequisites. |
| [`Space_Optimization/boundary_accessible_corridors.c`](../../../Space_Optimization/boundary_accessible_corridors.c) | Raster boundary-contact metric, not a continuous circulation route solver. |
| [`Space_Optimization/corridor.c`](../../../Space_Optimization/corridor.c) | Historical stub, not a registered mode. |

No team branch was merged and no legacy handler was wholesale replaced. The new
existing-plan endpoints use this package directly, independently of the old
`circulationEnabled` generation flag.
