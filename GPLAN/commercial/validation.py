"""Independent geometric acceptance of serialized plans and edited candidates."""

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from .egress import MARKERS, assess_egress, shape
from .generation import ledger
from .models import EPS, assessment, authorized_floors, fingerprint, normalize_brief
from .program import DESK_ROLES, compile_program
from .rules_nl import rule_assessments

CAPACITY_KINDS = {"open_office": {"desk"}, "private_office": {"desk"}, "focus": {"desk"},
                  "meeting": {"meeting_chair"}, "lunch": {"lunch_chair"},
                  "wc": {"wc_fixture"}, "accessible_wc": {"wc_fixture"},
                  "reception": {"reception_chair"}, "rest": {"rest_bed"}, "shower": {"shower_tray"}}

# Independent minimum physical object dimensions, orientation-independent.
# These protect counts against serialized epsilon-size furniture. They are
# product template assumptions, not statutory office-area rules.
OBJECT_MINIMA = {"desk": (.8, 1.6), "chair": (.6, .6), "meeting_chair": (.55, .6),
                "lunch_chair": (.55, .6), "reception_chair": (.55, .6), "meeting_table": (1.2, 1.6),
                "lunch_table": (1.2, 1.6), "wc_fixture": (.7, .8),
                "handwash": (.4, .4), "wheelchair_turning": (1.5, 1.5),
                "transfer_clearance": (.9, .9), "wheelchair_position": (.9, 1.1),
                "rest_bed": (.8, 1.9), "shower_tray": (1.2, 1.2),
                "printer": (.6, .6), "storage_cabinet": (.6, 1.2)}


def validate_candidate(plan, brief, sampled=True, include_rules=True, check_fingerprint=True):
    checks = []

    def check(identifier, condition, category, title, detail="", **kwargs):
        checks.append(assessment(identifier, "passed" if condition else "failed", category, title, detail, **kwargs))

    floors = plan.get("floors", [])
    if not isinstance(floors, list) or not 1 <= len(floors) <= 4:
        return {"valid": False, "status": "invalid", "assessments": [assessment("floor-count", "failed", "geometry", "A commercial plan needs one to four floors")]}
    check("authorised-floor-count", len(floors) in authorized_floors(brief), "geometry", "Use only the authorised floor count")
    if check_fingerprint:
        expected = fingerprint(brief)
        check("brief-fingerprint", plan.get("brief_fingerprint") == expected, "geometry", "The option matches the current immutable programme",
              "A changed programme invalidates a saved candidate and its checks.")
    required = {r["id"]: r for r in compile_program(brief, len(floors))}
    seen_programme, identifiers, computed_desks = set(), set(), 0
    whole_capacity = {"desks": 0, "meeting_seats": 0, "lunch_seats": 0, "wc_fixtures": 0}
    supplementary_capacity = {status: {key: 0 for key in ("desks", "meeting_seats", "lunch_seats", "waiting_seats")}
                              for status in ("usable", "route_review")}
    stairs, lifts, service_stacks = {}, {}, {}
    envelope = shape({"x": 0, "y": 0, "width": brief["site"]["width_m"], "height": brief["site"]["depth_m"]})
    for index, floor in enumerate(floors):
        supplementary = {}
        if any(room.get("supplementary") is True for room in floor["rooms"]):
            # Rebuild authorised support spaces from the base floor geometry.
            # A caller's role, label or derived-looking ID cannot authorise one.
            from .infill import supplementary_requirements
            supplementary = supplementary_requirements(floor, brief)
        seen_supplementary = set()
        check(f"f{index}:floor-index", floor["index"] == index and abs(floor["elevation_m"] - index * brief["building"]["floor_height_m"]) < EPS,
              "geometry", "Floors form an ordered, continuous elevation sequence")
        check(f"f{index}:envelope", Polygon(floor["envelope"]).symmetric_difference(envelope).area < EPS,
              "geometry", "The floor remains inside the fixed buildable envelope")
        entities = floor["rooms"] + floor["corridors"] + floor["cores"] + floor.get("walls", [])
        shapes = []
        for obj in entities:
            identifier = obj["id"]
            check(identifier + ":identity", identifier not in identifiers, "geometry", "Keep unique geometry identities")
            identifiers.add(identifier)
            r = obj["rect"]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in r.values()) or r["width"] <= 0 or r["height"] <= 0:
                check(identifier + ":dimensions", False, "geometry", "Geometry needs positive finite dimensions")
                continue
            s = shape(r)
            check(identifier + ":containment", envelope.buffer(EPS).covers(s), "geometry", "Preserve the strict buildable envelope",
                  witness={"floor_index": index, "entity_ids": [identifier]})
            if "clear_polygon" in obj or "polygon" in obj:
                check(identifier + ":polygon", Polygon(obj.get("clear_polygon", obj.get("polygon"))).symmetric_difference(s).area < EPS,
                      "geometry", "The clear polygon matches its measured rectangle")
            shapes.append((obj, s))
        overlap = []
        for i, (a, sa) in enumerate(shapes):
            for b, sb in shapes[:i]:
                if sa.intersection(sb).area > EPS:
                    overlap.append([a["id"], b["id"]])
        check(f"f{index}:nonoverlap", not overlap, "geometry", "Rooms, cores, circulation and walls have disjoint area",
              witness={"floor_index": index, "overlaps": overlap[:10]})
        reserved_shapes = []
        occupied = unary_union([s for _, s in shapes])
        for reserve in floor.get("reserved_areas", []):
            identifier, r = reserve.get("id", f"f{index}:unknown-reserve"), reserve.get("rect", {})
            dimensions = all(isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool) and
                             math.isfinite(r[key]) for key in ("x", "y", "width", "height"))
            dimensions = dimensions and r["width"] > 0 and r["height"] > 0
            check(identifier + ":reserved-dimensions", dimensions, "geometry", "Reserved residual areas have finite positive geometry")
            if not dimensions:
                continue
            reserved = shape(r)
            free = envelope.buffer(EPS).covers(reserved) and reserved.intersection(occupied).area < EPS and \
                all(reserved.intersection(other).area < EPS for other in reserved_shapes)
            check(identifier + ":reserved-area", free and identifier not in identifiers, "geometry",
                  "Name only actual unoccupied residual area; core landings and access routes remain separate",
                  witness={"floor_index": index, "entity_ids": [identifier]})
            identifiers.add(identifier)
            reserved_shapes.append(reserved)
        for room in floor["rooms"]:
            rid = room["id"]
            extra = room.get("supplementary") is True
            source = (supplementary if extra else required).get(room.get("programme_id"))
            seen = seen_supplementary if extra else seen_programme
            check(rid + ":programme", source is not None and room.get("programme_id") not in seen, "capacity",
                  "Use only independently authorised supplementary space definitions" if extra else "Preserve every immutable programme item exactly once")
            seen.add(room.get("programme_id"))
            if source is None:
                continue
            if extra:
                check(rid + ":supplementary-identity", rid == f"f{index}:" + source["id"] and
                      room.get("provenance") == "residual_space_allocation" and room.get("support_kind") == source.get("support_kind") and
                      room.get("required_capacity") == source["required_capacity"] and room.get("capacity") == source["required_capacity"] and room.get("fitout_status") in supplementary_capacity,
                      "capacity", "Retain the derived support-space identity, semantic use and fit-out scope")
                fixed = source.get("locked_geometry", {"floor_index": index, "rect": source.get("rect")})
                check(rid + ":supplementary-position", fixed.get("rect") is not None and fixed["floor_index"] == index and
                      shape(room["rect"]).symmetric_difference(shape(fixed["rect"])).area < EPS,
                      "geometry", "Keep supplementary fit-out inside its independently derived residual slot")
                expected = source.get("furniture", [])
                actual = room.get("furniture", [])
                remaining = list(actual)
                schedule_matches = bool(expected) and len(expected) == len(actual)
                for item in expected:
                    match = next((candidate for candidate in remaining if candidate["kind"] == item["kind"] and
                                  shape(candidate["rect"]).symmetric_difference(shape(item["rect"])).area < EPS), None)
                    if match is None:
                        schedule_matches = False
                    else:
                        remaining.remove(match)
                check(rid + ":supplementary-schedule", schedule_matches, "capacity",
                      "Retain the real furniture schedule that authorises this supplementary use")
                expected_aisles = source.get("aisles", [])
                actual_aisles = room.get("aisles", [])
                aisle_schedule = bool(expected_aisles) and len(expected_aisles) == len(actual_aisles) and all(
                    any(shape(a["rect"]).symmetric_difference(shape(b.get("rect", b))).area < EPS for a in actual_aisles)
                    for b in expected_aisles)
                check(rid + ":supplementary-aisle-schedule", aisle_schedule, "capacity",
                      "Retain the authorised support-space equipment access clearances")
                expected_door = source.get("door")
                actual_doors = [door for door in floor["doors"] if door.get("from") == rid]
                door_schedule = expected_door is not None and len(actual_doors) == 1
                if door_schedule:
                    actual_door = actual_doors[0]
                    door_schedule = actual_door["id"] == expected_door["id"] and actual_door.get("to") == expected_door.get("to") and math.dist(actual_door["point"], expected_door["point"]) < EPS and \
                        abs(actual_door["width_m"] - expected_door["width_m"]) < EPS and \
                        Polygon(actual_door["portal_polygon"]).symmetric_difference(Polygon(expected_door["portal_polygon"])).area < EPS
                check(rid + ":supplementary-door-schedule", door_schedule, "geometry",
                      "Retain the actual supplementary doorway into its reserved access route")
                walls = {wall["id"]: wall for wall in floor.get("walls", [])}
                expected_walls = source.get("walls", [])
                walls_match = bool(expected_walls) and all(wall["id"] in walls and
                    walls[wall["id"]].get("provenance") == "residual_space_allocation" and
                    shape(walls[wall["id"]]["rect"]).symmetric_difference(shape(wall["rect"])).area < EPS for wall in expected_walls)
                check(rid + ":supplementary-partitions", walls_match, "geometry",
                      "Keep the actual construction reservations around each supplementary fit-out")
            check(rid + ":semantics", room["role"] == source["role"] and room["requirement_id"] == source["requirement_id"] and room.get("use_function") == source["use_function"],
                  "capacity", "Display names do not change the semantic requirement or use function")
            check(rid + ":eligible-floor", not source.get("allowed_floors") or index in source["allowed_floors"], "capacity", "Preserve hard floor eligibility")
            if source.get("locked_geometry"):
                fixed = source["locked_geometry"]
                check(rid + ":fixed-position", index == fixed["floor_index"] and shape(room["rect"]).symmetric_difference(shape(fixed["rect"])).area < EPS,
                      "geometry", "Preserve the exact locked room rectangle and floor")
            room_shape = shape(room["rect"])
            check(rid + ":minimum-area", room_shape.area + EPS >= source["min_area_m2"], "capacity", "Preserve the final clear-area minimum",
                  measured=room_shape.area, required=source["min_area_m2"])
            check(rid + ":clear-area-ledger", abs(room["clear_area_m2"] - room_shape.area) < 1e-4 and
                  abs(room["before_area_m2"] - room["contribution_m2"] - room_shape.area) < 1e-4,
                  "geometry", "Measure clear room area independently of corridor area")
            count = 0
            furniture_shapes = []
            for furniture in room["furniture"]:
                r = furniture["rect"]
                s = shape(r)
                check(furniture["id"] + ":fit", r["width"] > 0 and r["height"] > 0 and room_shape.buffer(EPS).covers(s),
                      "capacity", "Fit every furniture or clearance module inside the final clear room",
                      witness={"floor_index": index, "entity_ids": [rid, furniture["id"]]})
                minimum = OBJECT_MINIMA.get(furniture["kind"])
                if minimum:
                    actual = sorted([r["width"], r["height"]])
                    check(furniture["id"] + ":physical-size", all(a + EPS >= m for a, m in zip(actual, minimum)),
                          "capacity", "Preserve the furniture module's physical dimensions")
                check(furniture["id"] + ":unique", furniture["id"] not in identifiers, "capacity", "Each furniture object has one identity")
                identifiers.add(furniture["id"])
                if furniture["kind"] in CAPACITY_KINDS.get(source["role"], set()):
                    # A serialized desk/chair is one actual usable place; callers
                    # cannot hide a capacity loss by changing a multiplier.
                    count += 1
                if furniture["kind"] not in MARKERS:
                    furniture_shapes.append((furniture, s))
            for i, (a, sa) in enumerate(furniture_shapes):
                for b, sb in furniture_shapes[:i]:
                    integrated = {a["kind"], b["kind"]} == {"sink", "worktop"}
                    if not integrated and sa.intersection(sb).area > EPS:
                        check(rid + ":furniture-overlap", False, "capacity", "Furniture modules may not occupy the same clear space",
                              witness={"floor_index": index, "entity_ids": [a["id"], b["id"]]})
            if source["role"] in CAPACITY_KINDS:
                check(rid + ":required-capacity", count >= source["required_capacity"] and room["capacity"] == count,
                      "capacity", "Final furniture preserves the required capacity", measured=count, required=source["required_capacity"],
                      witness={"floor_index": index, "entity_ids": [rid]})
            else:
                count = room["capacity"]
            kinds = [f["kind"] for f in room["furniture"]]
            schedule_ok = True
            if source["role"] in DESK_ROLES:
                schedule_ok = kinds.count("chair") >= count
            elif source["role"] in {"meeting", "lunch"}:
                table_kind = "meeting_table" if source["role"] == "meeting" else "lunch_table"
                tables = [f for f in room["furniture"] if f["kind"] == table_kind]
                schedule_ok = bool(tables) and max(max(f["rect"]["width"], f["rect"]["height"]) for f in tables) + EPS >= max(1.6, math.ceil(count / 2) * .7)
                schedule_ok &= "wheelchair_position" in kinds
            elif source["role"] == "reception":
                schedule_ok = "reception_desk" in kinds
            elif source["role"] in {"wc", "accessible_wc"}:
                schedule_ok = "handwash" in kinds
            elif source["role"] == "pantry":
                schedule_ok = "worktop" in kinds and "sink" in kinds
                if source.get("equipment") == "cooking":
                    schedule_ok &= "cooking_equipment" in kinds
            check(rid + ":furniture-schedule", schedule_ok, "capacity", "Retain the equipment and clearances behind each usable place")
            if extra:
                key = "desks" if source["role"] in DESK_ROLES else {"meeting": "meeting_seats", "lunch": "lunch_seats", "reception": "waiting_seats"}.get(source["role"])
                if key and room.get("fitout_status") in supplementary_capacity:
                    supplementary_capacity[room["fitout_status"]][key] += count
            elif source["role"] in DESK_ROLES:
                whole_capacity["desks"] += count
            if not extra and source["role"] == "meeting":
                whole_capacity["meeting_seats"] += count
            if not extra and source["role"] == "lunch":
                whole_capacity["lunch_seats"] += count
            if not extra and source["role"] in {"wc", "accessible_wc"}:
                whole_capacity["wc_fixtures"] += count
            aisles = [shape(a["rect"]) for a in room.get("aisles", [])]
            aisle_union = unary_union(aisles)
            # The wheelchair position at a table is a reservation, not a solid
            # obstacle. The actual equipment must leave the aisle network clear.
            obstructed = any(aisle_union.intersection(s).area > EPS for _, s in furniture_shapes)
            aisle_widths = all(min(a["rect"]["width"], a["rect"]["height"]) >= 1.2 - EPS and room_shape.buffer(EPS).covers(shape(a["rect"])) for a in room.get("aisles", []))
            check(rid + ":aisles", bool(aisles) and aisle_union.geom_type == "Polygon" and not obstructed and aisle_widths,
                  "capacity", "Retain the connected internal furniture access aisles",
                  witness={"floor_index": index, "entity_ids": [rid]})
            if source["role"] == "accessible_wc":
                turn = next((f for f in room["furniture"] if f["kind"] == "wheelchair_turning"), None)
                transfer = next((f for f in room["furniture"] if f["kind"] == "transfer_clearance"), None)
                fixture = any(f["kind"] == "wc_fixture" for f in room["furniture"])
                free = turn is not None and transfer is not None and fixture and min(turn["rect"]["width"], turn["rect"]["height"]) >= 1.5 - EPS
                if free:
                    free = not any(shape(turn["rect"]).intersection(s).area > EPS or shape(transfer["rect"]).intersection(s).area > EPS for _, s in furniture_shapes)
                check(rid + ":accessible-fixture", free, "accessibility", "Fit the accessible WC turning and transfer reservations")
        if supplementary:
            check(f"f{index}:supplementary-complete", seen_supplementary == set(supplementary), "geometry",
                  "Keep the complete independently derived supplementary fit-out")
        corridor_union = unary_union([shape(c["rect"]) for c in floor["corridors"]])
        check(f"f{index}:corridor-connected", corridor_union.geom_type == "Polygon", "geometry", "The shared circulation surface is connected")
        for corridor in floor["corridors"]:
            check(corridor["id"] + ":clear-width", min(corridor["rect"]["width"], corridor["rect"]["height"]) + EPS >= corridor["width_m"] >= 1.2 and corridor.get("clear_height_m", 0) >= 2.1,
                  "accessibility", "Retain actual shared-route clear width and height")
        axis_surface = unary_union([corridor_union] + [Polygon(d["portal_polygon"]) for d in floor["exits"]])
        # The axis has a boundary endpoint at y=0 in local coordinates; the
        # exterior opening covers that endpoint through the outside wall.
        check(f"f{index}:axis", axis_surface.buffer(EPS).covers(LineString(floor["corridor_axis"])),
              "geometry", "The route axis follows the actual circulation geometry")
        door_sources = set()
        objects = {o["id"]: o for o in floor["rooms"] + floor["cores"]}
        for door in floor["doors"]:
            origin = objects.get(door["from"])
            opening = Polygon(door["portal_polygon"])
            connected = origin is not None and opening.intersection(shape(origin["rect"])).area > EPS and opening.intersection(corridor_union).area > EPS
            geometric_width = LineString(door["segment"]).length
            portal_consistent = opening.buffer(EPS).covers(LineString(door["segment"])) and LineString(door["segment"]).distance(Point(door["point"])) < EPS
            check(door["id"] + ":usable-portal", connected and portal_consistent and abs(geometric_width - door["width_m"]) < EPS and door["width_m"] >= .85,
                  "geometry", "The actual clear door portal connects its room or core to circulation",
                  witness={"floor_index": index, "entity_ids": [door["id"], door["from"]]})
            if connected:
                door_sources.add(door["from"])
        check(f"f{index}:all-room-doors", all(r["id"] in door_sources for r in floor["rooms"]), "geometry", "Every room has a usable corridor door")
        for core in floor["cores"]:
            if core["kind"] == "stair":
                stairs[index] = core
                check(core["id"] + ":portal", core["id"] in door_sources, "escape", "The stair has an actual landing-to-corridor portal")
                core_door = next((d for d in floor["doors"] if d["from"] == core["id"]), None)
                check(core["id"] + ":portal-position", core_door is not None and math.dist(core["portal_point"], core_door["point"]) < EPS,
                      "escape", "The stair route uses its actual doorway")
                flights, landings = core.get("flights", []), core.get("landings", [])
                core_shape = shape(core["rect"])
                geometry_ok = len(flights) == 2 and len(landings) == 2 and all(core_shape.buffer(EPS).covers(shape(r)) for r in flights + landings)
                geometry_ok = geometry_ok and core.get("riser_count", 0) >= 2 and abs(core.get("riser_count", 0) * core.get("riser_height_m", 0) - brief["building"]["floor_height_m"]) < EPS
                geometry_ok = geometry_ok and core.get("riser_height_m", 1) <= .18 + EPS and core.get("going_m", 0) >= .28 - EPS and core.get("landing_depth_m", 0) >= core.get("flight_width_m", 1)
                if geometry_ok:
                    flight_width = core["flight_width_m"]
                    expected_run = (core["riser_count"] / 2 - 1) * core["going_m"]
                    geometry_ok = all(abs(min(f["width"], f["height"]) - min(flight_width, expected_run)) < EPS and abs(max(f["width"], f["height"]) - max(flight_width, expected_run)) < EPS for f in flights)
                    geometry_ok &= shape(flights[0]).intersection(shape(flights[1])).area < EPS
                    geometry_ok &= all(shape(f).distance(shape(l)) < EPS for f in flights for l in landings)
                    geometry_ok &= all(min(l["width"], l["height"]) >= flight_width - EPS for l in landings)
                    geometry_ok &= shape(landings[0]).intersection(shape(landings[1])).area < EPS
                check(core["id"] + ":flight-landing", geometry_ok, "escape", "Fit two flights, landings and the full floor-to-floor rise")
            elif core["kind"] == "lift":
                lifts[index] = core
                check(core["id"] + ":lift-access", core["id"] in door_sources and core.get("evacuation_route") is False,
                      "accessibility", "The passenger lift has clear access and is excluded from evacuation")
            elif core["kind"] == "service_shaft":
                service_stacks[index] = core
        recomputed = ledger(floor)
        check(f"f{index}:ledger", recomputed["residual_m2"] >= -EPS and all(abs(floor["area_ledger"].get(k, -1) - v) < 1e-4 for k, v in recomputed.items()),
              "geometry", "The non-overlapping area ledger balances to the gross plate")
    check("complete-programme", seen_programme == set(required), "capacity", "Keep every required room, amenity and workstation zone")
    for key, capacity in whole_capacity.items():
        check("building-capacity:" + key, capacity == plan["capacity"].get(key, capacity), "capacity", "Recompute the whole-building furniture capacity", measured=capacity, required=plan["capacity"].get(key, capacity))
    check("required-desks", whole_capacity["desks"] >= brief["people"]["desks"], "capacity", "Preserve the requested desk count", measured=whole_capacity["desks"], required=brief["people"]["desks"])
    if any(room.get("supplementary") is True for floor in floors for room in floor["rooms"]) or "supplementary_capacity" in plan:
        check("supplementary-capacity", plan.get("supplementary_capacity") == supplementary_capacity, "capacity",
              "Report supplementary furniture separately from accepted original programme capacity")
    whole_ledger = {k: sum(ledger(f)[k] for f in floors) for k in ledger(floors[0])}
    check("building-area-ledger", all(abs(plan["area_ledger"].get(k, -1) - v) < 1e-4 for k, v in whole_ledger.items()),
          "geometry", "The building ledger equals the independently measured floors")
    for name, stacks, required_stack in (("stair", stairs, len(floors) > 1), ("lift", lifts, len(floors) > 1 and brief["building"]["accessibility"] == "all_floors"), ("services", service_stacks, True)):
        if required_stack:
            aligned = set(stacks) == set(range(len(floors)))
            if aligned:
                ref = stacks[0]
                aligned = all(c["stack_id"] == ref["stack_id"] and shape(c["rect"]).symmetric_difference(shape(ref["rect"])).area < EPS and c["served_floors"] == list(range(len(floors))) for c in stacks.values())
            check(name + ":continuous-stack", aligned, "escape" if name == "stair" else "accessibility", "Keep the complete aligned " + name + " stack across occupied floors")
    exits = floors[0].get("exits", [])
    exterior_valid = bool(exits)
    for door in exits:
        opening = Polygon(door["portal_polygon"])
        corridor_union = unary_union([shape(c["rect"]) for c in floors[0]["corridors"]])
        exterior_valid &= opening.intersection(corridor_union).area > EPS and opening.difference(envelope).area > EPS
        exterior_valid &= door.get("width_m", 0) >= .85 and len(door.get("external_path", [])) >= 2
        exterior_valid &= abs(LineString(door["segment"]).length - door["width_m"]) < EPS and opening.buffer(EPS).covers(LineString(door["segment"]))
    check("ground-exit-connection", exterior_valid, "escape", "Continue the ground corridor through an actual exterior opening")
    peak = brief["people"]["staff"] + brief["people"]["visitors"]
    if peak > 150 or any(r["capacity"] > 150 for f in floors for r in f["rooms"]):
        check("independent-exit-scope", False, "escape", "This candidate source cannot establish the additional independent exits required by this population",
              "A single-spine/one-stair candidate is not accepted for a >150-person room or building population.")
    if not any(c["status"] == "failed" for c in checks):
        route_checks = assess_egress(brief, plan, sampled=sampled)
        checks.extend(route_checks)
        if sampled:
            by_id = {item["id"]: item for item in route_checks}
            for floor in floors:
                for room in floor["rooms"]:
                    if room.get("supplementary") is not True:
                        continue
                    route = by_id.get(room["id"] + ":operational-route", {})
                    expected_status = "route_review" if route.get("status") == "needs_input" else "usable" if route.get("status") == "passed" else None
                    check(room["id"] + ":fitout-status", expected_status is not None and room.get("fitout_status") == expected_status,
                          "escape", "Recompute whether the optional fit-out needs route redesign before use")
    if include_rules:
        checks.extend(rule_assessments(brief, plan))
    valid = not any(c["status"] == "failed" for c in checks)
    # Summarise routine success while retaining all failures and useful witnesses.
    return {"schema_version": "1.0", "valid": valid, "status": "review_required" if valid else "invalid",
            "assessments": checks, "capacity": whole_capacity, "supplementary_capacity": supplementary_capacity,
            "geometry_fingerprint": fingerprint(floors), "brief_fingerprint": fingerprint(brief)}
