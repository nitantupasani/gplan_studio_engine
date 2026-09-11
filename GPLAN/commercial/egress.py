"""Obstacle-aware operational path samples and conservative route loads.

The visibility graph is exact for the selected start points in the supplied
axis-aligned obstacle geometry, but those points do not certify a whole room's
worst distance. Statutory corrected distance is explicitly left unassessed.
"""

import heapq
import math
import json
from copy import deepcopy
from functools import lru_cache

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union
from shapely.prepared import prep

from .models import EPS, assessment

MARKERS = {"wheelchair_position", "wheelchair_turning", "transfer_clearance"}


def shape(r):
    return box(r["x"], r["y"], r["x"] + r["width"], r["y"] + r["height"])


def route_samples(room, door):
    """Cache translation-invariant module paths across assignments and floors."""
    r = room["rect"]
    x, y = r["x"], r["y"]
    normalized = {"rect": {"x": 0, "y": 0, "width": r["width"], "height": r["height"]},
                  "furniture": [{"kind": f["kind"], "rect": {
                      "x": round(f["rect"]["x"] - x, 6), "y": round(f["rect"]["y"] - y, 6),
                      "width": f["rect"]["width"], "height": f["rect"]["height"]}} for f in room["furniture"]]}
    point = [round(door["point"][0] - x, 6), round(door["point"][1] - y, 6)]
    result = deepcopy(_cached_route(json.dumps([normalized, point], sort_keys=True)))
    if result:
        result["polyline"] = [[p[0] + x, p[1] + y] for p in result["polyline"]]
    return result


@lru_cache(maxsize=512)
def _cached_route(key):
    room, point = json.loads(key)
    return _compute_route_samples(room, {"point": point})


def _compute_route_samples(room, door):
    bounds = shape(room["rect"])
    furniture = [shape(obj["rect"]) for obj in room["furniture"] if obj["kind"] not in MARKERS]
    obstacles = unary_union(furniture) if furniture else Polygon()
    # Centreline clearance of 0.15 m gives physical person-width routing. The
    # separately modelled 1.2 m aisle network is checked for obstruction too.
    walkable = bounds.buffer(-.15, join_style=2).difference(obstacles.buffer(.15, join_style=2))
    if walkable.is_empty:
        return None
    dx, dy = door["point"]
    minx, miny, maxx, maxy = bounds.bounds
    end = (min(max(dx, minx + .16), maxx - .16), min(max(dy, miny + .16), maxy - .16))
    region = next((p for p in ([walkable] if walkable.geom_type == "Polygon" else walkable.geoms)
                   if p.buffer(EPS).covers(Point(end))), None)
    if region is None:
        return None
    parts = [walkable] if walkable.geom_type == "Polygon" else list(walkable.geoms)
    if len(parts) > 1 and any(p.area > .8 for p in parts if p is not region):
        # Large disconnected free space is evidence of an obstructed room, not
        # a reason to quietly omit unreachable sample points.
        return None
    points = [end]
    points.extend(list(region.exterior.coords)[:-1])
    for ring in region.interiors:
        points.extend(list(ring.coords)[:-1])
    points = list(dict.fromkeys((round(x, 6), round(y, 6)) for x, y in points))
    # Cap is part of the service's bounded geometry scope.
    if len(points) > 256:
        return None
    region = prep(region.buffer(EPS * 4))
    neighbors = [[] for _ in points]
    for i, start in enumerate(points):
        for j in range(i):
            finish = points[j]
            line = LineString([start, finish])
            if region.covers(line):
                distance = math.dist(start, finish)
                neighbors[i].append((j, distance))
                neighbors[j].append((i, distance))
    distances = [float("inf")] * len(points)
    previous = [None] * len(points)
    distances[0] = 0
    queue = [(0, 0)]
    while queue:
        current, i = heapq.heappop(queue)
        if current > distances[i] + EPS:
            continue
        for j, length in neighbors[i]:
            nxt = current + length
            if nxt < distances[j] - EPS:
                distances[j], previous[j] = nxt, i
                heapq.heappush(queue, (nxt, j))
    if any(not math.isfinite(v) for v in distances):
        return None
    worst = max(range(len(points)), key=lambda i: distances[i])
    polyline, cursor = [], worst
    while cursor is not None:
        polyline.append(list(points[cursor]))
        cursor = previous[cursor]
    polyline.append(list(door["point"]))
    return {"polyline": polyline, "distance_m": distances[worst] + math.dist(end, door["point"]),
            "sample_count": len(points), "method": "visibility-graph-obstacle-vertices-sampled-not-certified"}


def project_to_axis(point, axis):
    start, end = axis
    vx, vy = end[0] - start[0], end[1] - start[1]
    length2 = vx * vx + vy * vy
    t = max(0, min(1, ((point[0] - start[0]) * vx + (point[1] - start[1]) * vy) / length2))
    return [start[0] + t * vx, start[1] + t * vy]


@lru_cache(maxsize=64)
def _circulation_surface(key):
    rectangles, portals = json.loads(key)
    surface = unary_union([shape(r) for r in rectangles] + [Polygon(p) for p in portals])
    return surface.buffer(EPS), surface.buffer(-.15, join_style=2)


def circulation_route(floor, start, finish, shortest=False):
    """A bounded path on actual shared routes, including branches around cores.

    The old direct projection to the spine could cut through a stair or lift
    from a side-pocket door. Portal polygons connect the exact endpoints to a
    surface with 0.15 m centreline clearance; no room or core interior becomes
    part of that shared walkable surface.
    """
    key = json.dumps([[c["rect"] for c in floor["corridors"]],
                      [d["portal_polygon"] for d in floor.get("doors", []) + floor.get("exits", [])]], sort_keys=True)
    axis = tuple(tuple(point) for point in floor.get("corridor_axis", []))
    return deepcopy(_cached_circulation_route(key, tuple(start), tuple(finish), axis, shortest))


@lru_cache(maxsize=1024)
def _cached_circulation_route(key, start, finish, axis, shortest):
    surface, clear = _circulation_surface(key)
    if clear.is_empty:
        return None
    a = nearest_points(clear, Point(start))[0]
    b = nearest_points(clear, Point(finish))[0]
    parts = [clear] if clear.geom_type == "Polygon" else list(clear.geoms)
    region = next((part for part in parts if part.buffer(EPS).covers(a) and part.buffer(EPS).covers(b)), None)
    if region is None:
        return None
    a, b = list(a.coords)[0], list(b.coords)[0]
    if not surface.covers(LineString([start, a])) or not surface.covers(LineString([b, finish])):
        return None
    covered = prep(region.buffer(EPS * 4))
    if covered.covers(LineString([a, b])):
        return [list(start), list(a), list(b), list(finish)]
    # The spine and perpendicular branches normally give a short orthogonal
    # path. Accept it only when the entire centreline is inside the measured
    # clear surface; a core or an unconnected branch cannot be crossed.
    if not shortest and len(axis) == 2:
        along_spine = [a, project_to_axis(a, axis), project_to_axis(b, axis), b]
        if covered.covers(LineString(along_spine)):
            return [list(start)] + [list(point) for point in along_spine] + [list(finish)]
    points = [a, b] + list(region.exterior.coords)[:-1]
    for ring in region.interiors:
        points.extend(list(ring.coords)[:-1])
    points = list(dict.fromkeys((round(x, 6), round(y, 6)) for x, y in points))
    if len(points) > 256:
        return None
    start_index, end_index = points.index((round(a[0], 6), round(a[1], 6))), points.index((round(b[0], 6), round(b[1], 6)))
    neighbors = [[] for _ in points]
    for i, point in enumerate(points):
        for j in range(i):
            if covered.covers(LineString([point, points[j]])):
                distance = math.dist(point, points[j])
                neighbors[i].append((j, distance))
                neighbors[j].append((i, distance))
    distances, previous = [float("inf")] * len(points), [None] * len(points)
    distances[start_index] = 0
    queue = [(0, start_index)]
    while queue:
        distance, index = heapq.heappop(queue)
        if distance > distances[index] + EPS:
            continue
        if index == end_index:
            break
        for neighbor, length in neighbors[index]:
            candidate = distance + length
            if candidate < distances[neighbor] - EPS:
                distances[neighbor], previous[neighbor] = candidate, index
                heapq.heappush(queue, (candidate, neighbor))
    if not math.isfinite(distances[end_index]):
        return None
    route, index = [], end_index
    while index is not None:
        route.append(list(points[index]))
        index = previous[index]
    route.reverse()
    return [list(start)] + route + [list(finish)]


def capacity_loads(brief, floors):
    """Envelope each floor's local capacities, capped by the conserved people.

    Local worst loads may be mutually exclusive. Every shared segment uses the
    maximum credible total, never a sum of different scenarios. This conservative
    envelope covers unknown distributions without quietly choosing attendance.
    """
    peak = brief["people"]["staff"] + brief["people"]["visitors"]
    local = [min(peak, sum(r["capacity"] for r in f["rooms"] if r["role"] in {"open_office", "private_office", "focus", "meeting", "lunch", "reception", "rest"})) for f in floors]
    return {"peak": peak, "floor_loads": local,
            "stair_loads": {i: min(peak, sum(local[i:])) for i in range(1, len(floors))}}


def assess_egress(brief, plan, sampled=True):
    checks = []
    floors = plan["floors"]
    loads = capacity_loads(brief, floors)
    ground = floors[0]
    exits = ground.get("exits", [])
    if not exits:
        return [assessment("external-discharge", "failed", "escape", "A connected ground-floor exterior exit is required")]
    exterior = exits[0]
    checks.append(assessment("exterior-door-flow", "passed" if loads["peak"] <= exterior["width_m"] * 110 + EPS else "failed",
                             "escape", "Check accumulated exterior-door demand", "The ground exit carries the simultaneous population from every occupied floor.",
                             measured=loads["peak"], required=exterior["width_m"] * 110,
                             witness={"floor_index": 0, "entity_ids": [exterior["id"]]}))
    for floor in floors:
        index, axis = floor["index"], floor["corridor_axis"]
        corridor = floor["corridors"][0]
        corridor_load = loads["peak"] if index == 0 else loads["floor_loads"][index]
        checks.append(assessment(f"f{index}:corridor-flow", "passed" if corridor_load <= corridor["width_m"] * 90 + EPS else "failed",
                                 "escape", "Check the shared-route design flow", "Conservative population envelope; direct design-basis rate, not an evacuation-time simulation.",
                                 measured=corridor_load, required=corridor["width_m"] * 90,
                                 witness={"floor_index": index, "entity_ids": [corridor["id"]]}))
        stair = next((c for c in floor["cores"] if c["kind"] == "stair"), None)
        if index > 0 and not stair:
            checks.append(assessment(f"f{index}:escape-stair", "failed", "escape", "The occupied upper floor has no escape stair"))
            continue
        if index > 0:
            demand = loads["stair_loads"][index]
            checks.append(assessment(f"f{index}:stair-flow", "passed" if demand <= stair["flight_width_m"] * 45 + EPS else "failed",
                                     "escape", "Check cumulative stair demand", "This segment serves every occupied floor above it; lifts are excluded.",
                                     measured=demand, required=stair["flight_width_m"] * 45,
                                     witness={"floor_index": index, "entity_ids": [stair["id"]]}))
        for room in floor["rooms"]:
            if room["role"] in {"storage", "it", "cleaning"} and not room["capacity"] and room.get("supplementary") is not True:
                continue
            door = next((d for d in floor["doors"] if d["from"] == room["id"]), None)
            if door is None:
                continue  # Independent geometry validator reports the missing portal.
            checks.append(assessment(f"{room['id']}:door-flow", "passed" if room["capacity"] <= door["width_m"] * 110 + EPS else "failed",
                                     "escape", "Check room-door design flow", "Per-room seat maximum is retained even when staff move between spaces.",
                                     measured=room["capacity"], required=door["width_m"] * 110,
                                     witness={"floor_index": index, "entity_ids": [room["id"], door["id"]]}))
            if not sampled:
                continue
            sample = route_samples(room, door)
            if sample is None:
                checks.append(assessment(f"{room['id']}:operational-route", "failed", "escape", "Furniture obstructs an operational room route",
                                         "The obstacle-aware visibility graph cannot connect the room samples to its actual door.",
                                         witness={"floor_index": index, "entity_ids": [room["id"], door["id"]]}))
                continue
            target = stair["portal_point"] if index else exterior["point"]
            shared = circulation_route(floor, door["point"], target)
            if shared is None:
                checks.append(assessment(f"{room['id']}:shared-route", "failed", "escape", "The room cannot reach its floor exit on the actual shared circulation",
                                         "A branch connection must remain clear of room furniture, stair landings, lift shafts and walls.",
                                         witness={"floor_index": index, "entity_ids": [room["id"], door["id"]]}))
                continue
            route = sample["polyline"] + shared[1:]
            distance = sum(math.dist(a, b) for a, b in zip(route, route[1:]))
            if distance > 30 + EPS:
                # A convenient orthogonal branch route is an upper bound,
                # not evidence that the shortest measured route exceeds 30 m.
                # Resolve its exact visibility path before any failure/review.
                shortest = circulation_route(floor, door["point"], target, shortest=True)
                if shortest is not None:
                    candidate_route = sample["polyline"] + shortest[1:]
                    candidate_distance = sum(math.dist(a, b) for a, b in zip(candidate_route, candidate_route[1:]))
                    if candidate_distance < distance:
                        route, distance = candidate_route, candidate_distance
            total_distance = distance
            if index:
                total_distance += sum(next(c for c in floors[i]["cores"] if c["kind"] == "stair")["climbing_line_length_m"] for i in range(1, index + 1))
                core0 = next(c for c in ground["cores"] if c["kind"] == "stair")
                ground_route = circulation_route(ground, core0["portal_point"], exterior["point"])
                if ground_route is None:
                    checks.append(assessment(f"{room['id']}:onward-ground-route", "failed", "escape", "The stair has no clear shared path to the ground exit",
                                             witness={"floor_index": 0, "entity_ids": [core0["id"], exterior["id"]]}))
                    continue
                total_distance += sum(math.dist(a, b) for a, b in zip(ground_route, ground_route[1:]))
            # 30 m is a conservative PRODUCT target to the floor exit/core. It
            # is explicitly separate from prescribed Bbl distance calculations.
            exceeds_target = distance > 30 + EPS
            optional_review = exceeds_target and room.get("supplementary") is True
            checks.append(assessment(f"{room['id']}:operational-route", "needs_input" if optional_review else "failed" if exceeds_target else "passed", "escape",
                                     "Optional fit-out exceeds the 30 m route target; route redesign required" if optional_review else "Sampled operational path to the floor exit",
                                     (f"The measured {distance:.3f} m connected path exceeds the 30 m operational planning target. This supplementary fit-out is a proposal requiring route redesign; its furniture receives no accepted capacity credit. " if optional_review else "") +
                                     "Obstacle vertices are sampled with 0.30 m centreline clearance. The 30 m planning target is not a certified all-points or corrected Bbl check.",
                                     rule="GPLAN operational planning target v1", measured=round(distance, 3), required=30,
                                     witness={"floor_index": index, "entity_ids": [room["id"], door["id"], stair["id"] if index else exterior["id"]],
                                              "polyline": route, "start": route[0], "sample_count": sample["sample_count"],
                                              "method": sample["method"], "onward_discharge_distance_m": round(total_distance, 3)}))
    checks.append(assessment("external-discharge", "passed" if brief["site"]["discharge_confirmed"] else "needs_input", "planning",
                             "Confirm usable onward discharge to the public road",
                             "The exit and internal connection are fitted. The external route is user-confirmed." if brief["site"]["discharge_confirmed"] else "The proposed exterior segment is diagrammatic. Terrain width, gates, legal access and its public-road connection remain unverified.",
                             witness={"floor_index": 0, "entity_ids": [exterior["id"]], "polyline": exterior["external_path"]}))
    return checks
