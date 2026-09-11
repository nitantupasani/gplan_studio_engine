"""Deterministic, furnished use of residual geometry after programme fitting.

Optional fit-out does not replace the immutable programme. All geometry has a
real corridor door. A connected room exceeding the operational route target is
an explicitly labelled proposal, never credited to requested capacity.
"""

from copy import deepcopy
import math
import time

from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep

from .models import EPS, MAX_ROOMS, fingerprint, polygon, rect
from .program import compile_program, requirement
from .templates import EXTERIOR, PARTITION, fit_template, item

PROVENANCE = "residual_space_allocation"
SUPPORT_CATALOGUE = {
    "collaboration": {"role": "meeting", "name": "Collaboration room", "maximum_capacity": 8},
    "quiet_work": {"role": "focus", "name": "Quiet work room", "maximum_capacity": 8},
    "library": {"role": "storage", "name": "Library & resources", "maximum_capacity": 0},
    "print_storage": {"role": "storage", "name": "Print & supplies", "maximum_capacity": 0},
    "waiting": {"role": "reception", "name": "Visitor waiting", "maximum_capacity": 4},
}
CAPACITY_KEYS = ("desks", "meeting_seats", "lunch_seats", "waiting_seats")


def _shape(r):
    return box(r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"])


def _residual_rectangles(floor, brief, include_fitout=False):
    """Reconstruct free cells from required geometry, never saved slot claims."""
    occupied = [obj for group in ("rooms", "corridors", "cores", "walls") for obj in floor[group]
                if include_fitout or obj.get("provenance") != PROVENANCE]
    width, depth = brief["site"]["width_m"], brief["site"]["depth_m"]
    inside = box(EXTERIOR, EXTERIOR, width - EXTERIOR, depth - EXTERIOR)
    free = inside.difference(unary_union([_shape(o["rect"]) for o in occupied]))
    available = prep(free.buffer(EPS))
    xs = sorted({round(max(EXTERIOR, min(width - EXTERIOR, v)), 6) for obj in occupied
                 for v in (obj["rect"]["x"], obj["rect"]["x"] + obj["rect"]["width"])} | {EXTERIOR, width - EXTERIOR})
    ys = sorted({round(max(EXTERIOR, min(depth - EXTERIOR, v)), 6) for obj in occupied
                 for v in (obj["rect"]["y"], obj["rect"]["y"] + obj["rect"]["height"])} | {EXTERIOR, depth - EXTERIOR})
    cells = [[available.covers(box(xs[x], ys[y], xs[x + 1], ys[y + 1]))
              for x in range(len(xs) - 1)] for y in range(len(ys) - 1)]
    rectangles = []
    # Greedy maximal rectangles are deterministic, bounded by the source's
    # small rectilinear grid, and have disjoint area by construction.
    for y in range(len(ys) - 1):
        for x in range(len(xs) - 1):
            if not cells[y][x]:
                continue
            best, span = None, len(xs) - 1 - x
            for bottom in range(y, len(ys) - 1):
                run = 0
                while run < span and cells[bottom][x + run]:
                    run += 1
                span = min(span, run)
                if not span:
                    break
                size = (xs[x + span] - xs[x]) * (ys[bottom + 1] - ys[y])
                if best is None or size > best[0]:
                    best = size, span, bottom
            _, span, bottom = best
            for row in range(y, bottom + 1):
                for col in range(x, x + span):
                    cells[row][col] = False
            rectangles.append(rect(xs[x], ys[y], xs[x + span] - xs[x], ys[bottom + 1] - ys[y]))
    return rectangles


def _door_face(r, corridors):
    choices = []
    for corridor in corridors:
        c = corridor["rect"]
        for face, gap, low, high in (
            ("right", c["x"] - r["x"] - r["width"], max(r["y"], c["y"]), min(r["y"] + r["height"], c["y"] + c["height"])),
            ("left", r["x"] - c["x"] - c["width"], max(r["y"], c["y"]), min(r["y"] + r["height"], c["y"] + c["height"])),
            ("bottom", c["y"] - r["y"] - r["height"], max(r["x"], c["x"]), min(r["x"] + r["width"], c["x"] + c["width"])),
            ("top", r["y"] - c["y"] - c["height"], max(r["x"], c["x"]), min(r["x"] + r["width"], c["x"] + c["width"]))):
            if -EPS <= gap <= 2 * PARTITION + EPS and high - low >= 1.2 - EPS:
                choices.append((max(0, gap), -(high - low), face, (low + high) / 2, corridor["id"]))
    return min(choices) if choices else None


def _split_zone(r, face):
    # Long tails become several functional rooms, each with its own real door.
    along_y = face in {"left", "right"}
    length = r["height"] if along_y else r["width"]
    count = max(1, math.ceil(length / 7.5))
    for n in range(count):
        if along_y:
            yield rect(r["x"], r["y"] + n * length / count, r["width"], length / count)
        else:
            yield rect(r["x"] + n * length / count, r["y"], length / count, r["height"])


def _template(kind, width, depth):
    entry = SUPPORT_CATALOGUE[kind]
    if kind in {"library", "print_storage"}:
        minimum_depth = 3.4 if kind == "print_storage" else 2.4
        if width < 2.2 - EPS or depth < minimum_depth - EPS:
            return None
        furniture = []
        for row in range(1 + max(0, math.floor((depth - minimum_depth) / 1.8))):
            furniture.append(item("storage_cabinet", .1, 1.2 + row * 1.8, .6, 1.2))
        if kind == "print_storage":
            furniture.append(item("printer", .1, depth - .7, .6, .6))
        return {"width": width, "depth": depth, "furniture": furniture,
                "aisles": [rect(width - 1.2, 0, 1.2, depth), rect(0, 0, width, 1.2)],
                "template_id": "support-" + kind + "-2026-09-11", "door_y": .6, "capacity": 0}
    for capacity in range(entry["maximum_capacity"], 0, -1):
        template = fit_template(requirement("support", entry["role"], capacity), width)
        if template and template["depth"] <= depth + EPS:
            template["depth"] = depth
            template["capacity"] = capacity
            template["aisles"] += [rect(width - 1.2, 0, 1.2, depth)]
            return template
    return None


def _map_rect(obj, room, face):
    x, y, w, h = obj["x"], obj["y"], obj["width"], obj["height"]
    if face == "right":
        return rect(room["x"] + x, room["y"] + y, w, h)
    if face == "left":
        return rect(room["x"] + room["width"] - x - w, room["y"] + y, w, h)
    if face == "bottom":
        return rect(room["x"] + y, room["y"] + x, h, w)
    return rect(room["x"] + y, room["y"] + room["height"] - x - w, h, w)


def supplementary_requirements(floor, brief):
    """Canonical optional source definitions reconstructed for independent gates."""
    from .generation import portal
    sources = {}
    zones = []
    for raw in _residual_rectangles(floor, brief):
        connection = _door_face(raw, floor["corridors"])
        if min(raw["width"], raw["height"]) < 2.1 or connection is None:
            continue
        zones.extend(_split_zone(raw, connection[2]))
    zones.sort(key=lambda r: (r["y"], r["x"], r["height"], r["width"]))
    floor_count = max((len(c.get("served_floors", [0])) for c in floor["cores"]), default=1)
    remaining = max(0, MAX_ROOMS - len(compile_program(brief, floor_count)))
    quota, remainder = divmod(remaining, floor_count)
    slot_limit = min(16, quota + (1 if floor["index"] < remainder else 0))
    for slot, raw in enumerate(zones[:slot_limit]):
        connection = _door_face(raw, floor["corridors"])
        if connection is None:
            continue
        gap, _, face, along, target = connection
        # Partitions are actual reserved geometry; the existing corridor wall
        # can serve the door face where it already exists.
        margins = {side: PARTITION for side in ("left", "right", "top", "bottom")}
        margins[face] = 0 if gap >= PARTITION - EPS else PARTITION
        room_rect = rect(raw["x"] + margins["left"], raw["y"] + margins["top"],
                         raw["width"] - margins["left"] - margins["right"], raw["height"] - margins["top"] - margins["bottom"])
        width, depth = (room_rect["width"], room_rect["height"]) if face in {"left", "right"} else (room_rect["height"], room_rect["width"])
        core_pocket = target != f"f{floor['index']}:corridor"
        preferred = ("waiting" if floor["index"] == 0 else "quiet_work") if core_pocket else ("collaboration" if slot % 2 == 0 else "quiet_work")
        template, kind = None, None
        for wanted in (preferred, "library", "print_storage") if min(width, depth) >= 3 else ("print_storage", "library"):
            template = _template(wanted, width, depth)
            if template is not None:
                kind = wanted
                break
        if template is None:
            continue
        pid = f"derived:support:{floor['index']}:{slot}:{kind}"
        rid = f"f{floor['index']}:{pid}"
        source = requirement(pid, SUPPORT_CATALOGUE[kind]["role"], template["capacity"],
                             requirement_id="derived:support:" + kind, name=SUPPORT_CATALOGUE[kind]["name"],
                             provenance=PROVENANCE, supplementary=True, support_kind=kind,
                             allowed_floors=[floor["index"]], rect=room_rect,
                             expected_id=rid, min_area_m2=room_rect["width"] * room_rect["height"])
        source["furniture"] = [{**obj, "id": f"{rid}:furniture-{n + 1}", "rect": _map_rect(obj["rect"], room_rect, face)}
                               for n, obj in enumerate(template["furniture"])]
        source["aisles"] = [{"id": f"{rid}:aisle-{n}", "rect": _map_rect(obj, room_rect, face), "width_m": 1.2}
                            for n, obj in enumerate(template["aisles"])]
        source["template_id"] = template["template_id"]
        gap += margins[face]
        if face in {"left", "right"}:
            x = room_rect["x"] - gap / 2 if face == "left" else room_rect["x"] + room_rect["width"] + gap / 2
            point = [x, min(room_rect["y"] + room_rect["height"] - .6, max(room_rect["y"] + .6, along))]
        else:
            y = room_rect["y"] - gap / 2 if face == "top" else room_rect["y"] + room_rect["height"] + gap / 2
            point = [min(room_rect["x"] + room_rect["width"] - .6, max(room_rect["x"] + .6, along)), y]
        source["door"] = portal(rid + ":door", point, .95, rid, target, face in {"top", "bottom"}, thickness=gap)
        source["walls"] = []
        bands = [rect(raw["x"], raw["y"], margins["left"], raw["height"]),
                 rect(raw["x"] + raw["width"] - margins["right"], raw["y"], margins["right"], raw["height"]),
                 rect(room_rect["x"], raw["y"], room_rect["width"], margins["top"]),
                 rect(room_rect["x"], raw["y"] + raw["height"] - margins["bottom"], room_rect["width"], margins["bottom"])]
        for n, band in enumerate(bands):
            if min(band["width"], band["height"]) > EPS:
                source["walls"].append({"id": f"{rid}:wall-{n}", "rect": band, "polygon": polygon(band),
                                        "kind": "reserved_construction", "provenance": PROVENANCE})
        sources[pid] = source
    return sources


def _refresh(candidate):
    from .generation import ledger
    for floor in candidate["floors"]:
        floor["area_ledger"] = ledger(floor)
    candidate["area_ledger"] = {key: round(sum(f["area_ledger"][key] for f in candidate["floors"]), 6)
                                 for key in candidate["floors"][0]["area_ledger"]}
    candidate["geometry_fingerprint"] = fingerprint(candidate["floors"])
    candidate["score"] = [len(candidate["floors"]), round(candidate["area_ledger"]["circulation_m2"], 3),
                          round(candidate["area_ledger"]["residual_m2"], 3)]
    candidate["supplementary_capacity"] = {status: {key: 0 for key in CAPACITY_KEYS} for status in ("usable", "route_review")}
    for floor in candidate["floors"]:
        for room in floor["rooms"]:
            if not room.get("supplementary"):
                continue
            key = {"focus": "desks", "meeting": "meeting_seats", "lunch": "lunch_seats", "reception": "waiting_seats"}.get(room["role"])
            if key:
                candidate["supplementary_capacity"][room["fitout_status"]][key] += room["capacity"]


def allocate_residual_spaces(candidate, brief, validate, deadline=None, cancelled=None):
    """Add checked support geometry without risking an already checked base plan."""
    from .egress import assess_egress
    started = time.monotonic()
    if (deadline is not None and time.monotonic() >= deadline) or (cancelled and cancelled()):
        return candidate
    proposed = deepcopy(candidate)
    for floor in proposed["floors"]:
        if (deadline is not None and time.monotonic() >= deadline) or (cancelled and cancelled()):
            return candidate
        for source in supplementary_requirements(floor, brief).values():
            pid, r = source["id"], source["rect"]
            room = {**deepcopy(source), "id": source["expected_id"], "programme_id": pid,
                    "floor_index": floor["index"], "clear_polygon": polygon(r),
                    "clear_area_m2": r["width"] * r["height"], "before_area_m2": r["width"] * r["height"],
                    "contribution_m2": 0, "fitout_status": "usable"}
            for field in ("walls", "door", "expected_id"):
                room.pop(field, None)
            floor["rooms"].append(room)
            floor["doors"].append(deepcopy(source["door"]))
            floor["walls"].extend(deepcopy(source["walls"]))
        floor["reserved_areas"] = [{"id": f"f{floor['index']}:reserved-{n}", "rect": r,
                                    "name": "Reserved access / clearance", "reason": "This remaining geometry has no independently furnished room fit; keep it clear pending detailed access and construction design."}
                                   for n, r in enumerate(_residual_rectangles(floor, brief, include_fitout=True))
                                   if min(r["width"], r["height"]) >= .45 and r["width"] * r["height"] >= .5]
    _refresh(proposed)
    if (deadline is not None and time.monotonic() >= deadline) or (cancelled and cancelled()):
        return candidate
    route_checks = assess_egress(brief, proposed, sampled=True)
    for floor in proposed["floors"]:
        for room in floor["rooms"]:
            if room.get("supplementary"):
                route = next((c for c in route_checks if c["id"] == room["id"] + ":operational-route"), None)
                if route and route.get("status") == "needs_input":
                    room["fitout_status"] = "route_review"
    _refresh(proposed)
    verified = validate(proposed, brief)
    if not verified["valid"]:
        candidate = deepcopy(candidate)
        candidate["infill"] = {"status": "not_allocated", "detail": "The residual fit-out did not pass its independent geometry/access checks; the checked programme is retained.",
                               "checks": [c for c in verified["assessments"] if c["status"] == "failed"][:8]}
        return candidate
    proposed["assessments"] = verified["assessments"]
    proposed["validation_fingerprint"] = fingerprint({"geometry": proposed["geometry_fingerprint"], "brief": proposed["brief_fingerprint"]})
    proposed["infill"] = {"status": "allocated", "source": PROVENANCE,
                          "elapsed_seconds": round(time.monotonic() - started, 3),
                          "added_rooms": sum(bool(r.get("supplementary")) for f in proposed["floors"] for r in f["rooms"]),
                          "detail": "Furnished supplementary spaces are separate from requested capacity. Route-review proposals need a route redesign before use."}
    proposed["id"] = "office-infill-" + fingerprint({"base": candidate["id"], "geometry": proposed["geometry_fingerprint"]})[:16]
    return proposed
