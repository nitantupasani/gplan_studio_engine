"""Strict rectangular candidate source with reserved circulation and stack geometry.

There is no residential allocator or minimum/envelope relaxation on this path.
Alternative offset/ordering/floor-count configurations are real bounded packing
attempts. Failure of this source cannot prove that all possible layouts fail.
"""

from copy import deepcopy
import math

from .models import EPS, area, fingerprint, polygon, rect
from .program import compile_program, occupancy_scenarios
from .templates import EXTERIOR, PARTITION, fit_template, stair_template


def local_dimensions(brief):
    site = brief["site"]
    if site["entrance_side"] in {"south", "north"}:
        return site["width_m"], site["depth_m"]
    return site["depth_m"], site["width_m"]


def transform_point(p, site):
    x, y = p
    if site.get("_mirror_x"):
        x = site["_local_width"] - x
    side = site["entrance_side"]
    # SVG/editor frame: +x east, +y south. Local y=0 is the chosen entrance.
    if side == "south":
        return [x, site["depth_m"] - y]
    if side == "east":
        return [site["width_m"] - y, x]
    if side == "west":
        return [y, x]
    return [x, y]


def transform_rect(r, site):
    points = [transform_point(p, site) for p in polygon(r)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def inverse_rect(r, site):
    def inverse(p):
        x, y = p
        if site["entrance_side"] == "south":
            result = [x, site["depth_m"] - y]
        elif site["entrance_side"] == "east":
            result = [y, site["width_m"] - x]
        elif site["entrance_side"] == "west":
            result = [y, x]
        else:
            result = [x, y]
        if site.get("_mirror_x"):
            result[0] = site["_local_width"] - result[0]
        return result
    points = [inverse(p) for p in polygon(r)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def transform_floor(floor, site):
    floor["envelope"] = [transform_point(p, site) for p in floor["envelope"]]
    floor["corridor_axis"] = [transform_point(p, site) for p in floor["corridor_axis"]]
    for key in ("rooms", "corridors", "cores", "walls"):
        for obj in floor[key]:
            obj["rect"] = transform_rect(obj["rect"], site)
            for field in ("polygon", "clear_polygon"):
                if field in obj:
                    obj[field] = [transform_point(p, site) for p in obj[field]]
            for child in obj.get("furniture", []):
                child["rect"] = transform_rect(child["rect"], site)
            for child in obj.get("aisles", []):
                child["rect"] = transform_rect(child["rect"], site)
            for field in ("flights", "landings"):
                if field in obj:
                    obj[field] = [transform_rect(r, site) for r in obj[field]]
            if obj.get("void"):
                obj["void"] = transform_rect(obj["void"], site)
            if obj.get("portal_point"):
                obj["portal_point"] = transform_point(obj["portal_point"], site)
    for door in floor["doors"] + floor["exits"]:
        door["point"] = transform_point(door["point"], site)
        door["segment"] = [transform_point(p, site) for p in door["segment"]]
        if door.get("portal_polygon"):
            door["portal_polygon"] = [transform_point(p, site) for p in door["portal_polygon"]]
        if door.get("external_path"):
            door["external_path"] = [transform_point(p, site) for p in door["external_path"]]


def portal(identifier, point, width, source, target, horizontal=False, thickness=PARTITION):
    x, y = point
    segment = [[x - width / 2, y], [x + width / 2, y]] if horizontal else [[x, y - width / 2], [x, y + width / 2]]
    opening = rect(x - width / 2, y - thickness / 2 - .01, width, thickness + .02) if horizontal else rect(x - thickness / 2 - .01, y - width / 2, thickness + .02, width)
    return {"id": identifier, "point": point, "width_m": width, "clear_width_m": width,
            "height_m": 2.1, "segment": segment, "portal_polygon": polygon(opening),
            "from": source, "to": target, "room_id": source,
            "operation": "outward_recessed_or_clear_of_route", "hardware_status": "requires_review"}


def reserve_core_approach(floor, core, side, corridor):
    """Give the side of a compact core a real, unobstructed cross-wing route."""
    bounds = core["rect"]
    y = bounds["y"] + bounds["height"] + PARTITION
    wing = next(slot for slot in floor["_bins"] if slot["side"] == side and abs(slot["y"] - y) < EPS)
    if y + 1.2 + PARTITION > wing["end"]:
        return False
    x = EXTERIOR if side == "left" else corridor["x"] + corridor["width"]
    width = corridor["x"] - EXTERIOR if side == "left" else wing["x"] + wing["width"] - x
    approach = rect(x, y, width, 1.2)
    floor["corridors"].append({"id": core["id"] + ":approach", "name": "Stair approach" if core["kind"] == "stair" else "Lift access",
                              "kind": "core_approach", "core_id": core["id"], "rect": approach,
                              "polygon": polygon(approach), "width_m": 1.2, "clear_height_m": 2.1,
                              "protection": "construction_specification_unverified"})
    # The cross-aisle opens directly onto the spine, through an actual gap in
    # its partition reservation. No geometry is hidden beneath a drawn route.
    divider_x = corridor["x"] - PARTITION if side == "left" else corridor["x"] + corridor["width"]
    walls = []
    for wall in floor["walls"]:
        r = wall["rect"]
        if abs(r["x"] - divider_x) > EPS or abs(r["width"] - PARTITION) > EPS or r["y"] >= y + 1.2 or r["y"] + r["height"] <= y:
            walls.append(wall)
            continue
        for suffix, top, bottom in (("before", r["y"], y), ("after", y + 1.2, r["y"] + r["height"])):
            if bottom > top + EPS:
                piece = rect(r["x"], top, r["width"], bottom - top)
                walls.append({**wall, "id": wall["id"] + ":" + suffix, "rect": piece, "polygon": polygon(piece)})
    floor["walls"] = walls
    separator = rect(wing["x"], y + 1.2, wing["width"], PARTITION)
    floor["walls"].append({"id": core["id"] + ":approach-partition", "rect": separator,
                           "polygon": polygon(separator), "kind": "reserved_construction"})
    wing["y"] = y + 1.2 + PARTITION
    return True


def start_floor(brief, count, index, offset, core_position="entrance"):
    width, depth = local_dimensions(brief)
    peak = brief["people"]["staff"] + brief["people"]["visitors"]
    corridor_width = max(1.5, math.ceil(peak / 90 * 10) / 10)
    corridor_x = (width - corridor_width) * offset
    left_width = corridor_x - EXTERIOR - PARTITION
    right_x = corridor_x + corridor_width + PARTITION
    right_width = width - EXTERIOR - right_x
    if min(left_width, right_width) < 2.5:
        return None, "The buildable width cannot contain both room wings and the reserved clear route."
    corridor = rect(corridor_x, EXTERIOR, corridor_width, depth - 2 * EXTERIOR)
    floor = {"index": index, "elevation_m": index * brief["building"]["floor_height_m"],
             "envelope": polygon(rect(0, 0, width, depth)), "rooms": [], "cores": [],
             "corridors": [{"id": f"f{index}:corridor", "rect": corridor, "polygon": polygon(corridor),
                            "width_m": corridor_width, "clear_height_m": 2.1,
                            "protection": "construction_specification_unverified"}],
             "corridor_axis": [[corridor_x + corridor_width / 2, 0 if index == 0 else EXTERIOR], [corridor_x + corridor_width / 2, depth - EXTERIOR]],
             "doors": [], "exits": [], "walls": [],
             "_bins": [{"side": "left", "x": EXTERIOR, "width": left_width, "y": EXTERIOR, "end": depth - EXTERIOR},
                       {"side": "right", "x": right_x, "width": right_width, "y": EXTERIOR, "end": depth - EXTERIOR}]}
    for r in (rect(0, 0, width, EXTERIOR), rect(0, depth - EXTERIOR, width, EXTERIOR),
              rect(0, EXTERIOR, EXTERIOR, depth - 2 * EXTERIOR),
              rect(width - EXTERIOR, EXTERIOR, EXTERIOR, depth - 2 * EXTERIOR),
              rect(corridor_x - PARTITION, EXTERIOR, PARTITION, depth - 2 * EXTERIOR),
              rect(corridor_x + corridor_width, EXTERIOR, PARTITION, depth - 2 * EXTERIOR)):
        floor["walls"].append({"id": f"f{index}:wall-{len(floor['walls'])}", "rect": r,
                               "polygon": polygon(r), "kind": "reserved_construction"})
    if count > 1:
        # Upper-floor population bound is conservative: everybody may be above
        # ground. Actual cumulative loads are independently recomputed later.
        stair_width = max(1.2, min(2.4, math.ceil(peak / 45 * 10) / 10))
        template = stair_template(brief["building"]["floor_height_m"], stair_width)
        if template["width"] > left_width + EPS or template["depth"] > depth - 2 * EXTERIOR:
            return None, "The continuous stair flight and landing module does not fit the clear wing dimensions."
        x = corridor_x - PARTITION - template["width"]
        y = (depth - template["depth"]) / 2 if core_position == "central" else EXTERIOR
        core = {"id": f"f{index}:stair", "kind": "stair", "stack_id": "main-stair",
                "rect": rect(x, y, template["width"], template["depth"]),
                "served_floors": list(range(count)), **template,
                "portal_point": [corridor_x - PARTITION / 2, y + .2 + template["landing_depth_m"] / 2],
                "protection": "reserved_enclosure_rating_unverified", "longitudinal_position": core_position}
        core["polygon"] = polygon(core["rect"])
        for key in ("flights", "landings"):
            core[key] = [rect(x + r["x"], y + r["y"], r["width"], r["height"]) for r in core[key]]
        core["void"] = rect(x + core["void"]["x"], y + core["void"]["y"], core["void"]["width"], core["void"]["height"])
        floor["cores"].append(core)
        floor["doors"].append(portal(f"f{index}:stair-door", core["portal_point"], min(stair_width, 1.5),
                                      core["id"], f"f{index}:corridor"))
        if core_position == "central":
            after = {**floor["_bins"][0], "y": y + template["depth"] + PARTITION}
            floor["_bins"][0]["end"] = y - PARTITION
            floor["_bins"].append(after)
        else:
            floor["_bins"][0]["y"] = y + template["depth"] + PARTITION
        if not reserve_core_approach(floor, core, "left", corridor):
            return None, "The stair approach cannot retain its clear cross-wing access."
        if brief["building"]["accessibility"] == "all_floors":
            if right_width < 2.5 or depth < 3.2:
                return None, "The step-free policy requires a lift shaft and clear landing that do not fit."
            lift_rect = rect(right_x, EXTERIOR, 2.5, 2.7)
            floor["cores"].append({"id": f"f{index}:lift", "kind": "lift", "stack_id": "passenger-lift",
                                    "rect": lift_rect, "polygon": polygon(lift_rect),
                                    "served_floors": list(range(count)), "car_width_m": 1.1,
                                    "car_depth_m": 1.4, "evacuation_route": False,
                                    "portal_point": [right_x - PARTITION / 2, EXTERIOR + 1.35]})
            floor["doors"].append(portal(f"f{index}:lift-door", [right_x - PARTITION / 2, EXTERIOR + 1.35],
                                          .95, f"f{index}:lift", f"f{index}:corridor"))
            floor["_bins"][1]["y"] = EXTERIOR + 2.7 + PARTITION
            if not reserve_core_approach(floor, floor["cores"][-1], "right", corridor):
                return None, "The lift approach cannot retain its clear cross-wing access."
    # A protected wet-service riser has actual reserved area on every floor.
    # It is placed in the same right-hand service band as the lift.
    shaft_y = floor["_bins"][1]["y"]
    shaft_rect = rect(width - EXTERIOR - .5, shaft_y, .5, .5)
    floor["cores"].append({"id": f"f{index}:services", "kind": "service_shaft", "stack_id": "wet-services",
                            "rect": shaft_rect, "polygon": polygon(shaft_rect), "served_floors": list(range(count))})
    floor["_bins"][1]["y"] = shaft_y + .5 + PARTITION
    if index == 0:
        exit_width = max(.95, math.ceil(peak / 110 * 10) / 10)
        if exit_width > corridor_width:
            return None, "The accumulated entrance-door flow exceeds the reserved corridor width."
        door = portal("f0:exterior-exit", [corridor_x + corridor_width / 2, EXTERIOR / 2],
                      exit_width, "f0:corridor", "external-discharge", True, EXTERIOR)
        door.update({"destination": "public-road-via-adjoining-terrain", "discharge_confirmed": brief["site"]["discharge_confirmed"],
                     "external_path": [[corridor_x + corridor_width / 2, EXTERIOR / 2], [corridor_x + corridor_width / 2, -1.5]],
                     "external_width_m": corridor_width, "external_status": "user_confirmed" if brief["site"]["discharge_confirmed"] else "unverified"})
        floor["exits"].append(door)
    return floor, None


def place_room(floor, bin_index, requirement, template):
    target = floor["_bins"][bin_index]
    x, y, width, depth = target["x"], target["y"], target["width"], template["depth"]
    right = target["side"] == "right"
    identifier = f"f{floor['index']}:{requirement['id']}"
    room = {**deepcopy(requirement), "id": identifier, "programme_id": requirement["id"],
            "floor_index": floor["index"], "rect": rect(x, y, width, depth),
            "clear_area_m2": width * depth, "before_area_m2": width * depth, "contribution_m2": 0,
            "capacity": requirement["required_capacity"], "furniture": [], "aisles": [],
            "template_id": template["template_id"]}
    room["clear_polygon"] = polygon(room["rect"])
    for n, obj in enumerate(template["furniture"]):
        r = obj["rect"]
        fx = x + (width - r["x"] - r["width"] if right else r["x"])
        room["furniture"].append({**obj, "id": f"{identifier}:furniture-{n + 1}",
                                  "rect": rect(fx, y + r["y"], r["width"], r["height"])})
    counting = {"open_office": "desk", "private_office": "desk", "focus": "desk", "meeting": "meeting_chair",
                "lunch": "lunch_chair", "wc": "wc_fixture", "accessible_wc": "wc_fixture",
                "reception": "reception_chair", "rest": "rest_bed", "shower": "shower_tray"}.get(room["role"])
    if counting:
        room["capacity"] = sum(f["kind"] == counting for f in room["furniture"])
    for n, r in enumerate(template["aisles"]):
        ax = x + (width - r["x"] - r["width"] if right else r["x"])
        room["aisles"].append({"id": f"{identifier}:aisle-{n}", "rect": rect(ax, y + r["y"], r["width"], r["height"]), "width_m": 1.2})
    door_x = x - PARTITION / 2 if right else x + width + PARTITION / 2
    room_door = portal(f"{identifier}:door", [door_x, y + template["door_y"]], .95,
                       identifier, f"f{floor['index']}:corridor")
    floor["doors"].append(room_door)
    floor["rooms"].append(room)
    separator = rect(x, y + depth, width, PARTITION)
    floor["walls"].append({"id": f"{identifier}:partition", "rect": separator,
                           "polygon": polygon(separator), "kind": "reserved_construction"})
    target["y"] = y + depth + PARTITION


def ledger(floor):
    # Openings are portals through construction reservations. Their thresholds
    # are assigned to construction rather than counted twice as clear rooms.
    gross = abs(sum(floor["envelope"][i][0] * floor["envelope"][(i + 1) % 4][1] - floor["envelope"][(i + 1) % 4][0] * floor["envelope"][i][1] for i in range(4))) / 2
    values = {"gross_m2": gross, "room_clear_m2": sum(area(r["rect"]) for r in floor["rooms"]),
              "circulation_m2": sum(area(r["rect"]) for r in floor["corridors"]),
              "core_service_m2": sum(area(r["rect"]) for r in floor["cores"]),
              "wall_structure_m2": sum(area(r["rect"]) for r in floor["walls"])}
    values["residual_m2"] = gross - sum(v for k, v in values.items() if k != "gross_m2")
    return {k: round(v, 6) for k, v in values.items()}


def pack_candidate(brief, floor_count, offset=.5, ordering=0, spacious=False, core_position="entrance"):
    rooms = compile_program(brief, floor_count)
    floors = []
    for i in range(floor_count):
        floor, reason = start_floor(brief, floor_count, i, offset, core_position)
        if floor is None:
            return None, {"code": "core_or_width_deficit", "detail": reason, "floor_count": floor_count}
        floors.append(floor)
    width, depth = local_dimensions(brief)
    frame = {**brief["site"], "_mirror_x": brief["building"]["core_side"] == "right", "_local_width": width}
    locked = [r for r in rooms if r.get("locked_geometry")]
    for room in sorted(locked, key=lambda r: (r["locked_geometry"]["floor_index"], r["id"])):
        lock = room["locked_geometry"]
        index = lock["floor_index"]
        if index >= floor_count or (room.get("allowed_floors") and index not in room["allowed_floors"]):
            return None, {"code": "locked_floor_conflict", "requirement_id": room["requirement_id"], "detail": "The fixed room's floor is outside this authorised assignment."}
        local = inverse_rect(lock["rect"], frame)
        placed = False
        for b, slot in enumerate(floors[index]["_bins"]):
            if abs(slot["x"] - local["x"]) > EPS or abs(slot["width"] - local["width"]) > EPS:
                continue
            if local["y"] < slot["y"] - EPS or local["y"] + local["height"] + PARTITION > slot["end"] + EPS:
                continue
            template = fit_template({**room, "min_area_m2": max(room["min_area_m2"], local["width"] * local["height"])}, local["width"], spacious=False)
            if template is None or template["depth"] > local["height"] + EPS:
                continue
            template["depth"] = local["height"]
            previous = dict(slot)
            slot["y"] = local["y"]
            place_room(floors[index], b, room, template)
            floors[index]["_bins"].pop(b)
            if local["y"] - PARTITION > previous["y"] + EPS:
                floors[index]["_bins"].append({**previous, "end": local["y"] - PARTITION})
            if local["y"] + local["height"] + PARTITION < previous["end"] - EPS:
                floors[index]["_bins"].append({**previous, "y": local["y"] + local["height"] + PARTITION})
            placed = True
            break
        if not placed:
            return None, {"code": "locked_geometry_conflict", "requirement_id": room["requirement_id"],
                          "detail": "The exact locked rectangle conflicts with the reserved core/corridor, another lock, or the full-wing furniture fit; its coordinates were not moved."}
    rooms = [r for r in rooms if not r.get("locked_geometry")]
    # Fixed-floor essentials are fitted first. Accessible toilet/service bands
    # retain the same x/y arrangement across floors before user room assignment.
    def order(room):
        fixture = 0 if room["role"] == "accessible_wc" else 1
        floor_constraint = 0 if room.get("allowed_floors") else 1
        priority = room["required_capacity"] if ordering == 0 else room["min_area_m2"]
        return fixture, floor_constraint, -priority, room["id"]
    rooms.sort(key=order)
    for room in rooms:
        eligible = room.get("allowed_floors") or list(range(floor_count))
        fits = []
        for index in eligible:
            if index >= floor_count:
                continue
            for b, slot in enumerate(floors[index]["_bins"]):
                template = fit_template(room, slot["width"], spacious)
                if template is None or slot["y"] + template["depth"] + PARTITION > slot["end"] + EPS:
                    continue
                # Minimise loss from full-wing strips, with optional balanced
                # assignment. Ground-facing requirements retain hard eligibility.
                priority = index if ordering == 0 else (slot["y"] / depth if ordering == 1 else -index)
                score = (priority, template["depth"], slot["y"], b)
                if room["role"] == "accessible_wc":
                    score = (0 if b == 1 else 1, index, slot["y"], b)
                fits.append((score, index, b, template))
        if not fits:
            from .room_fit import room_fit_issue
            available = [slot for index in eligible if index < floor_count for slot in floors[index]["_bins"]]
            return None, {**room_fit_issue(room, available, "remaining_slots", spacious), "floor_count": floor_count}
        _, index, b, template = min(fits, key=lambda f: f[0])
        place_room(floors[index], b, room, template)
    if any(not any(r["role"] not in {"wc", "accessible_wc"} for r in floor["rooms"]) for floor in floors):
        return None, {"code": "empty_occupied_floor", "detail": "This floor assignment leaves a requested floor without programme rooms.", "floor_count": floor_count}
    for floor in floors:
        del floor["_bins"]
        floor["area_ledger"] = ledger(floor)
        transform_floor(floor, frame)
    all_rooms = [r for f in floors for r in f["rooms"]]
    capacity = {"desks": sum(r["capacity"] for r in all_rooms if r["role"] in {"open_office", "private_office", "focus"}),
                "meeting_seats": sum(r["capacity"] for r in all_rooms if r["role"] == "meeting"),
                "lunch_seats": sum(r["capacity"] for r in all_rooms if r["role"] == "lunch"),
                "wc_fixtures": sum(max(1, r["capacity"]) for r in all_rooms if r["role"] in {"wc", "accessible_wc"}),
                "staff": brief["people"]["staff"], "visitors": brief["people"]["visitors"]}
    total = {key: round(sum(f["area_ledger"][key] for f in floors), 6) for key in floors[0]["area_ledger"]}
    candidate = {"id": "office-" + fingerprint({"floors": floors, "capacity": capacity})[:16],
                 "name": f"{floor_count} floor{'s' if floor_count > 1 else ''} · {'balanced' if ordering else 'compact'} programme",
                 "floors": floors, "capacity": capacity, "area_ledger": total,
                 "occupancy_scenarios": occupancy_scenarios(brief, all_rooms),
                 "score": [floor_count, round(total["circulation_m2"], 3), round(total["residual_m2"], 3)],
                 "candidate_source": "strict_rectangular_spine_packing", "status": "review_required",
                 "core_configuration": {"side": brief["building"]["core_side"], "longitudinal_position": core_position},
                 "brief_fingerprint": fingerprint(brief), "geometry_fingerprint": fingerprint(floors)}
    return candidate, None
