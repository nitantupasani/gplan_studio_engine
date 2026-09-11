# Commercial office engine

The independent package uses metres and plain JSON dictionaries. Public functions
are `estimate_commercial_fit(brief)`, `generate_commercial_options(brief,
progress=None, cancelled=None, deadline=None)`, and
`validate_commercial_option(option, brief)`. `deadline` is an absolute
`time.monotonic()` timestamp; progress receives `{stage, message}` and real attempt
counters, without invented percentages. Cancellation is a zero-argument callable.
No function applies a plan.

```json
{
  "schema_version": "1.0",
  "site": {"width_m": 18, "depth_m": 24, "entrance_side": "south",
    "regime": "new_build", "buildable_confirmed": false,
    "discharge_confirmed": false, "address": ""},
  "people": {"staff": 32, "visitors": 4, "desks": 32},
  "building": {"floor_strategy": "auto", "max_floors": 3,
    "floor_height_m": 3.3, "accessibility": "all_floors",
    "client_rooms_ground_floor": true, "allow_office_split": true},
  "rooms": [{"id": "meeting-8", "role": "meeting", "name": "Meeting room",
    "count": 1, "capacity": 8, "min_area_m2": 0,
    "preferred_area_m2": 20, "protect_capacity": true}],
  "amenities": {"wc_policy": "planning_ratio", "policy_people_per_wc": 20,
    "accessible_wc": true, "pantry": "tea", "lunch_seats": 12,
    "public_cafe": false},
  "rules_profile": "nl-office-newbuild-2026-09-11-design-basis"
}
```

`floor_strategy` is `single`, `exact` (`floor_count`) or `auto` (`max_floors`),
bounded to 1–4. Room `allowed_floors` uses zero-based indices. The original strict
search preserves every hard capacity regardless of its display name. `locked` requires baseline position
geometry. A count-one `locked_geometry: {floor_index,rect}` reserves an exact
full-wing strip before the other rooms are fitted, with free intervals above and
below it. Locks that conflict with cores, the corridor or another lock fail;
unsupported interior placements are never moved silently. Split repeated room
groups into individual requirements before assigning a position lock.
`building.core_side` selects `left` or `right` for the complete aligned stack
family, measured looking into the building from the selected entrance. The
right-hand alternative reflects all local geometry and revalidates it. Position
locks remain fixed in world coordinates and can reject an incompatible side.
The bounded search compares a central longitudinal stair position with an
entrance-side position. Both reserve aligned landings and enclosure geometry
before fitting the free room intervals and checking onward ground discharge.

Generation returns `{schema_version, engine_version, status, brief,
brief_fingerprint, candidates, diagnostics, search}`. Candidates contain
`{id, floors, capacity, area_ledger, assessments, occupancy_scenarios, score}`.
Each floor contains `{index,elevation_m,envelope,rooms,corridors,cores,doors,
exits,walls,area_ledger}`. Rectangles are `{x,y,width,height}`; polygons are
`[[x,y],...]`; furniture is `{id,kind,rect,capacity}`. All are in metres, with
positive x east and positive y south, matching the SVG editor coordinate frame.

Assessment statuses are `passed`, `failed`, `needs_input`, `not_assessed`.
Categories separate geometry, capacity, escape, accessibility, environment,
services and planning. Witnesses have floor index, entity IDs and/or polylines.
No generic statutory compliance result is produced. A geometrically accepted
candidate remains `review_required`: source applicability, construction ratings,
supporting-use rules, daylight, ventilation design and site evidence still need
review. Source links are research evidence, not an operative 2026 consolidation.

`wc_count` means ordinary WC fixtures; accessible WCs are additional. Automatic
provision uses the disclosed project planning ratio and every occupied floor
retains a nearby sanitary fixture. Derived ordinary fixtures share a furnished WC
block on each floor, retaining the original fixture count and clear access aisles.
Reception `capacity` means waiting seats;
the reception desk remains separate furniture and cannot stand in for chairs.

This first candidate source packs furniture-backed rectangular rooms on both
sides of a reserved spine, searches assignment orders and corridor offsets, and
reserves aligned stair/lift/service modules before fitting rooms. It deliberately
does not invoke the legacy dimensioner's envelope/minimum relaxations. A bounded
search miss is not proof of infeasibility. An absolute net-area lower bound can
prove a brief too large; no dimensional topology search claim is made.
Wide meeting and lunch rooms orient their real tables and chairs across the room
where this reduces depth while retaining front, back and corridor-side aisles.
Attempt quotas give each authorised floor count comparable search coverage.

The supported topology has one corridor spine and one continuous stair stack
when needed. Populations above 150, layouts requiring further independent exits,
and geometries failing the conservative sampled 30 m operational target do not
produce accepted candidates. That source limitation is separate from a proof of
infeasibility. The all-points prescribed corrected Bbl distance, protections and
supporting assembly-use rule implementation remain specialist review scope.

Mutations must be independently revalidated. The validator recomputes capacities,
areas, furniture containment, opening adjacency, connected stairs and cumulative
loads; it does not trust a saved passed badge or area ledger. Future furniture or
wall edits invalidate route witnesses and require fresh validation.

## Explicit adjusted-programme alternatives

`building.allow_programme_adjustments` defaults to false in the engine. When
enabled, a failed original search is followed by up to 32 programme alternatives
and upward refinements within a shared 30-second limit. Declared staff and visitor
numbers remain immutable, including the population used for exits and sanitary
provision. The bounded alternatives first compare useful meeting/lunch room
counts and seating capacities while preserving desks. Desk shortages are a
separate last-resort alternative; they never reduce the declared occupancy.
The ranking minimises lost desks, then lost total room/lunch places, then lost
room count and clear-area demand. It therefore prefers fewer useful meeting rooms
over many nearly empty rooms. After finding a valid plan, remaining search budget
tests higher capacities and retains the best checked result. This is a bounded
retention search, not a global maximum claim. There is no one-person/zero-visitor
escape recipe. Site geometry, authorised floors, use classifications, accessibility,
sanitary policy and position locks cannot change. Capacity protection continues
to apply to ordinary replanning; this explicit policy authorises visibly marked
alternative capacities without rewriting the original brief.

An alternative returns `status` and `fit_kind: modified_programme`, its
`fitted_brief`, original/fitted fingerprints, `satisfies_original_brief: false`,
and measured `constraint_deviations` containing requested/provided values.
`original_search` retains the original outcome and diagnostics with the option.
Validation takes the original brief, restricts the permitted numerical changes,
revalidates the fitted geometry and recomputes the unmet original requirements.
Forged differences, missing stairs, changed site/access rules and falsely claimed
original fit are rejected. A modified option remains a study requiring review.

The reported 20 × 30 m case requests 40 staff, 10 visitors, 40 desks, five
ground-floor 20-seat meetings, two storage rooms, reception, reheat pantry and 20
lunch seats. It produces a validated three-floor alternative retaining all 40
desks, 40 staff, 10 visitors and both storage rooms, with three 18-seat meetings
and 18 lunch seats. Those original room/seating shortages remain explicit after
applying the study. Impossible protected geometry or unsupported exit topology
still returns an explicit failure rather than fabricated floorplans.

Additional checks: `python -m unittest GPLAN.commercial.tests.test_adjustments -v`.

## Furnished residual spaces

After programme fitting and capacity-restoration attempts, the engine reconstructs
remaining rectangles and adds named collaboration, quiet-work, waiting, library
and print/storage fit-outs where physical furniture, partitions and a real door
fit. Cross-wing approaches connect the pockets beside compact stair/lift cores
to the spine. These clear routes and core landings remain unfurnished.

Supplementary rooms retain provenance, a deterministic source identity and
`fitout_status: usable|route_review`. Independent validation reconstructs their
slots and checks physical furniture, doors, clear aisles and actual shared-route
paths. A connected optional room exceeding the 30 m product route target stays a
visible proposal requiring route redesign, with its measured path and witness.
Required programme rooms retain the existing acceptance gate. Supplementary
furniture is reported separately in `supplementary_capacity` and never erases an
original requirement shortage or adds staff/visitors. Remaining clearance areas
are named and remain in the residual area ledger.

The ordinary public call retains up to 12 seconds for programme search plus a
reserved 6-second finishing allowance, within an 18-second total. The opt-in
programme-adjustment call retains its 30-second total, reserving 6 seconds for
fit-out. Both honour an earlier caller deadline and retain the checked base plan
when optional allocation cannot complete. These allowances are exposed by
`options().search` and returned search metadata.
