"""Metric, strict adapter around GPLAN's existing longest-path dimensioner.

Topology templates describe only contact/order, not finished room rectangles.
Every floor is dimensioned by minimum_dimensioning.main, then its existing
constraint graphs are solved again with exact envelope and hard upper bounds.
The legacy API's relaxed retries, NBC allocator and geometric fill are bypassed.
"""
from copy import deepcopy
from dataclasses import dataclass
import math
import threading

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from GPLAN.source.dimensioning import minimum_dimensioning as minimum_dimensioning
from .programs import ROOM_KINDS, ROOM_NAMES, program_id

MM_PER_FOOT = 304.8
INDOOR_CIRCULATION_CLEAR_MM = 1000
EDITOR_COORDINATE_GRID_MM = .01 * MM_PER_FOOT
WALL_REQUEST_ROUNDING_MM = .5
SOLVER_LOCK = threading.RLock()
SOLVER_NAME = "GPLAN.source.dimensioning.minimum_dimensioning.main + longest_path"


def mm_to_feet(value):
    return float(value) / MM_PER_FOOT


def feet_to_mm(value):
    return int(round(float(value) * MM_PER_FOOT))


class FloorSolveError(ValueError):
    pass


@dataclass
class Cell:
    key: str
    role: str
    rect: tuple
    min_w: float
    min_d: float
    max_w: float = 20000
    max_d: float = 20000
    fixed: bool = False


def polygon_points(poly):
    return [[int(round(x)), int(round(y))] for x, y in list(poly.exterior.coords)[:-1]]


def clear_face_shape(room, footprint, walls):
    # Gross room boundaries describe partition centrelines, except the outside
    # footprint boundary, which is the exterior wall's outside face.
    shape = room.buffer(-walls["interior_mm"] / 2, join_style=2)
    shape = shape.intersection(footprint.buffer(-walls["exterior_mm"], join_style=2))
    return shape


def _cell(key, role, rect, width, depth, fixed=False, max_w=20000, max_d=20000):
    return Cell(key, role, rect, width, depth, max_w, max_d, fixed)


def build_blueprint(role, width, depth, walls, variant="kitchen_front", bedrooms=2, separate_wc=False):
    """Slicing topologies with a common front-left U-return core.

    Integers in rect are ordinal cut lines used ONLY to infer wall contacts.
    The real core and room sizes below enter the dimensional solver as bounds.
    """
    ext, half = walls["exterior_mm"], walls["interior_mm"] / 2
    core_w = int(math.ceil(2000 + ext + half))
    # A physical U-return needs a 1m turn landing + 2m tread run + a
    # SEPARATE 1m flat departure/arrival platform. A side door may only open
    # over that last platform, never over the upper flight's final treads.
    core_d = int(math.ceil(4000 + ext + half))
    # Target 1 m clear after wall faces. The current house importer stores wall
    # coordinates on a 0.01 ft lattice; its integer-mm request can also round a
    # displayed wall down by up to 0.5 mm. Account for both bounded conversions
    # before the integer-mm solve, keeping every import phase at least 1 m
    # without resizing saved plans (102 mm walls -> 1104 mm gross).
    hall_w = math.ceil(math.ceil((INDOOR_CIRCULATION_CLEAR_MM + 2 * half + WALL_REQUEST_ROUNDING_MM)
                                / EDITOR_COORDINATE_GRID_MM) * EDITOR_COORDINATE_GRID_MM)
    if role == "ground":
        # Keep the existing 900 mm entrance and 100 mm jambs, even with thin walls.
        hall_w = max(hall_w, 900 + 2 * 100)
    wc_d = 1250 + 2 * half
    edge_room = ext + half
    # Node-local minima include only wall faces that are present in the final
    # room. Merged-cell edges receive no wall deduction.
    stair = _cell("stair", "stair", (0, 0, 1, 2), core_w, core_d, True)
    if role == "ground":
        cells = [stair, _cell("entrance", "entrance", (1, 0, 2, 3), hall_w, core_d + wc_d),
                 _cell("wc", "wc", (0, 2, 1, 3), 1000 + edge_room, wc_d, max_d=2400)]
        if variant == "living_front":
            cells += [_cell("living", "living", (2, 0, 4, 3), 2500 + edge_room, max(3000,math.ceil(14000000/max(1,width-core_w-hall_w-edge_room))) + edge_room),
                      _cell("kitchen", "kitchen", (0, 3, 4, 5), 2500 + 2 * ext, 2200 + edge_room)]
            links = [("entrance", "stair"), ("entrance", "wc"), ("entrance", "living"), ("living", "kitchen")]
        else:
            cells += [_cell("kitchen", "kitchen", (2, 0, 4, 2), 2300 + edge_room, max(2400, math.ceil(7000000 / max(1, width-core_w-hall_w-edge_room))) + edge_room),
                      _cell("living", "living", (2, 2, 4, 3), 2300 + edge_room, 900),
                      _cell("living", "living", (0, 3, 4, 5), 2500 + 2 * ext, 2500 + edge_room)]
            links = [("entrance", "stair"), ("entrance", "wc"), ("entrance", "kitchen"), ("entrance", "living"), ("kitchen", "living")]
        return cells, links, core_w, core_d
    if role in {"first", "second"}:
        bath_role = "bathroom" if separate_wc else "bathroom_wc"
        room_role = "bedroom" if role == "first" else "study"
        if bedrooms >= 3 and role == "first":
            # Rear pair reached from an L-shaped landing; no bedroom is a
            # circulation route. The bathroom stays on the wet service side.
            cells = [stair,
                _cell("landing", "landing", (1, 0, 2, 2), hall_w, core_d),
                _cell("bedroom_1", "bedroom", (2, 0, 5, 2), 2500 + edge_room, 2500 + edge_room),
                _cell("landing", "landing", (0, 2, 5, 3), 2500, hall_w),
                _cell("bath", bath_role, (0, 3, 1, 5), 1750 + edge_room, 2050 + edge_room, max_d=6000),
                _cell("bedroom_2", "bedroom", (1, 3, 3, 5), 2600 + 2 * half, 2900 + edge_room),
                _cell("bedroom_3", "bedroom", (3, 3, 5, 5), 2500 + edge_room, 2600 + edge_room)]
            links = [("landing", "stair"), ("landing", "bath")] + [("landing", f"bedroom_{i}") for i in range(1, 4)]
        else:
            cells = [stair,
                _cell("landing", "landing", (1, 0, 2, 5), hall_w, core_d + 2100 + edge_room),
                _cell("bath", bath_role, (0, 2, 1, 5), 1750 + edge_room, 2100 + edge_room, max_d=6500),
                _cell("bedroom_1" if role == "first" else "study", room_role, (2, 0, 4, 2), 2500 + edge_room, max(2700, math.ceil(7500000 / max(1, width-core_w-hall_w-edge_room))) + edge_room),
                _cell("bedroom_2" if role == "first" else "bedroom_extra", "bedroom", (2, 2, 4, 5), 2500 + edge_room, 2800 + edge_room)]
            links = [("landing", "stair"), ("landing", "bath"), ("landing", cells[3].key), ("landing", cells[4].key)]
        if separate_wc:
            # Explicit separate-WC topology, rather than silently combining the
            # requested programme. Bath column splits vertically below stairs.
            bath = next(c for c in cells if c.key == "bath")
            x0, y0, x1, y1 = bath.rect
            bath.rect = (x0, y0, x1, y0 + (y1 - y0) * .55)
            bath.min_d = 1900 + 2 * half
            cells.append(_cell("wc", "wc", (x0, bath.rect[3], x1, y1), 1000 + edge_room, 1250 + edge_room, max_d=2400))
            links.append(("landing", "wc"))
        return cells, links, core_w, core_d
    if role == "attic":
        cells = [stair,
            _cell("landing", "attic_landing", (1, 0, 2, 2), hall_w, core_d),
            _cell("hobby", "hobby", (2, 0, 4, 5), 2300 + edge_room, 2600 + 2 * ext),
            _cell("hobby", "hobby", (0, 2, 2, 5), 2200 + ext, 2200 + edge_room)]
        return cells, [("landing", "stair"), ("landing", "hobby")], core_w, core_d
    raise FloorSolveError(f"Unsupported floor role {role}.")


def _touch(a, b):
    x0, y0, x1, y1 = a
    u0, v0, u1, v1 = b
    return ((x1 == u0 or u1 == x0) and min(y1, v1) > max(y0, v0)) or ((y1 == v0 or v1 == y0) and min(x1, u1) > max(x0, u0))


def compile_floor_constraints(cells, links, width, depth):
    xmax = max(c.rect[2] for c in cells)
    ymax = max(c.rect[3] for c in cells)
    requested = {frozenset(p) for p in links}
    data = {"nodes": [], "edges": [], "boundary_rooms": {k: [] for k in ("north", "south", "east", "west")}}
    for i, c in enumerate(cells):
        x0, y0, x1, y1 = c.rect
        data["nodes"].append({"id": i, "label": c.key, "room_x": x0 * 10., "room_y": y1 * 10., "room_width": (x1 - x0) * 10., "room_height": (y1 - y0) * 10.,
            "min_width": mm_to_feet(c.min_w), "min_height": mm_to_feet(c.min_d), "max_width": mm_to_feet(c.min_w if c.fixed else c.max_w), "max_height": mm_to_feet(c.min_d if c.fixed else c.max_d), "is_fixed": c.fixed})
        for boundary, at in [("west", x0 == 0), ("east", x1 == xmax), ("south", y0 == 0), ("north", y1 == ymax)]:
            if at:
                data["boundary_rooms"][boundary].append(i)
    for i, a in enumerate(cells):
        for j, b in enumerate(cells[i + 1:], i + 1):
            if _touch(a.rect, b.rect):
                # Black edges in the existing solver still impose 2ft contact.
                # Required doors use a strict 1050mm span, never the relaxed rung.
                data["edges"].append({"source": i, "target": j, "color": "red" if frozenset((a.key, b.key)) in requested else "black"})
    return data


def _strict_dimension(cells, data, width, depth):
    """Use the existing GPLAN dimensioner with extra hard graph edges.

    No monkey patching or global default changes: per-call graphs are amended
    under the same-process lock, then GPLAN's compute_placement/longest_path
    solve them. Legacy main reinitializes state on its next call.
    """
    with SOLVER_LOCK:
        ok, _ = minimum_dimensioning.main(deepcopy(data), mm_to_feet(width) + 1e-7, mm_to_feet(depth) + 1e-7, overlap_floor=mm_to_feet(1050))
        if not ok:
            raise FloorSolveError("GPLAN minimum-dimension solve found this programme topology infeasible within the envelope.")
        sink = 2 * len(cells) + 1
        for edges, edge_set, dimension, boundary, axis in [
            (minimum_dimensioning.edgesX, minimum_dimensioning.edges_setx, width, data["boundary_rooms"]["east"], "x"),
            (minimum_dimensioning.edgesY, minimum_dimensioning.edges_sety, depth, data["boundary_rooms"]["north"], "y"),
        ]:
            # Existing plot cap plus this lower edge fixes the exact envelope.
            edges[0][sink] = mm_to_feet(dimension)
            edge_set.append((0, sink))
            for i in boundary:
                wall = 2 * (i + 1) if axis == "x" else 2 * (i + 1) - 1
                edges[sink][wall] = 0
                edge_set.append((sink, wall))
            for i, c in enumerate(cells):
                before = 2 * i + (1 if axis == "x" else 2)
                after = 2 * i + (2 if axis == "x" else 1)
                maximum = c.min_w if c.fixed and axis == "x" else c.min_d if c.fixed else c.max_w if axis == "x" else c.max_d
                # The legacy graph uses exact float comparisons. A sub-micron
                # numerical tolerance prevents a 2400mm upper edge oscillating
                # on binary-float subtraction; the final integer-mm hard gate
                # still checks the original unmodified bounds.
                edges[after][before] = -mm_to_feet(maximum) - 1e-7
        minimum_dimensioning.placementx.clear()
        minimum_dimensioning.placementy.clear()
        native_success = minimum_dimensioning.compute_placement()
        residual = max((edges[a][b]-(placement[b]-placement[a])
                        for placement, edges, edge_set in [
                            (minimum_dimensioning.placementx,minimum_dimensioning.edgesX,minimum_dimensioning.edges_setx),
                            (minimum_dimensioning.placementy,minimum_dimensioning.edgesY,minimum_dimensioning.edges_sety)]
                        for a,b in edge_set), default=0)
        # The original solver can report False for a 1e-15ft subtraction
        # residual on an otherwise feasible maximum edge. Independently verify
        # EVERY native inequality to sub-micron precision before accepting its
        # placements. A geometric/room constraint is never waived here.
        if not math.isfinite(residual) or residual > 1e-6:
            raise FloorSolveError("GPLAN exact-envelope solve cannot preserve all mandatory dimensions and door spans.")
        # Read native float placements rather than the legacy four-decimal-foot
        # renderer. Quantize shared walls ONCE to integer mm to prevent slivers.
        px, py = minimum_dimensioning.placementx, minimum_dimensioning.placementy
        rects = []
        for i, cell in enumerate(cells):
            rect = (feet_to_mm(px[2 * i + 1]), feet_to_mm(py[2 * i + 2]), feet_to_mm(px[2 * i + 2]), feet_to_mm(py[2 * i + 1]))
            if rect[2] - rect[0] < cell.min_w - 1 or rect[3] - rect[1] < cell.min_d - 1 or rect[2] - rect[0] > (cell.min_w if cell.fixed else cell.max_w) + 1 or rect[3] - rect[1] > (cell.min_d if cell.fixed else cell.max_d) + 1:
                raise FloorSolveError("The strict post-solver dimension gate rejected a room bound.")
            rects.append(rect)
        shapes = [box(*r) for r in rects]
        total = unary_union(shapes)
        envelope = box(0, 0, width, depth)
        if total.symmetric_difference(envelope).area > 1 or sum(s.area for s in shapes) - total.area > 1:
            raise FloorSolveError("GPLAN result did not exactly tile the requested envelope after millimetre rounding.")
        return rects, {"native_exact_status":bool(native_success),"verified_max_constraint_residual_mm":max(0,residual)*MM_PER_FOOT,"numeric_tolerance_mm":1e-6*MM_PER_FOOT}


def _segments(line):
    if line.geom_type == "LineString":
        pts = list(line.coords)
        return [(a, b) for a, b in zip(pts, pts[1:]) if a != b]
    if hasattr(line, "geoms"):
        return [s for g in line.geoms for s in _segments(g)]
    return []


def _make_door(a, b, room_a, room_b, opening_id, kind="door", width=850, preferred_point=None):
    shared = a.boundary.intersection(b.boundary)
    segments = _segments(shared)
    segments = [s for s in segments if math.dist(*s) >= width + 200]
    if not segments:
        raise FloorSolveError(f"No unrelaxed usable door span between {room_a} and {room_b}.")
    if preferred_point is None:
        first, last = max(segments, key=lambda s: math.dist(*s))
    else:
        first, last = min(segments, key=lambda s: math.dist(((s[0][0]+s[1][0])/2,(s[0][1]+s[1][1])/2), preferred_point))
    length = math.dist(first, last)
    size = min(width if width > 850 else 1500, length - 200) if kind == "opening" else width
    mx, my = (first[0] + last[0]) / 2, (first[1] + last[1]) / 2
    if preferred_point:
        if first[0] == last[0]:
            my = min(max(preferred_point[1], min(first[1], last[1]) + size/2 + 100), max(first[1], last[1]) - size/2 - 100)
        else:
            mx = min(max(preferred_point[0], min(first[0], last[0]) + size/2 + 100), max(first[0], last[0]) - size/2 - 100)
    dx, dy = (last[0] - first[0]) / length * size / 2, (last[1] - first[1]) / length * size / 2
    return {"id": opening_id, "from_room_id": room_a, "to_room_id": room_b, "segment": [[round(mx-dx),round(my-dy)],[round(mx+dx),round(my+dy)]], "kind": kind, "clear_width_mm": round(size)}


def solve_floor(role, level, width, depth, walls, profile, variant="kitchen_front", bedrooms=2, separate_wc=False):
    cells, links, core_w, core_d = build_blueprint(role, width, depth, walls, variant, bedrooms, separate_wc)
    counts={c.key:sum(other.key==c.key for other in cells) for c in cells}
    max_x,max_y=max(c.rect[2] for c in cells),max(c.rect[3] for c in cells)
    for cell in cells:
        if cell.fixed or counts[cell.key]!=1:
            continue
        rule=profile["room_rules"][cell.role]
        x0,y0,x1,y1=cell.rect
        allowance_x=sum(walls["exterior_mm"] if boundary else walls["interior_mm"]/2 for boundary in (x0==0,x1==max_x))
        allowance_y=sum(walls["exterior_mm"] if boundary else walls["interior_mm"]/2 for boundary in (y0==0,y1==max_y))
        cell.min_w=max(cell.min_w,rule["min_width_mm"]+allowance_x)
        cell.min_d=max(cell.min_d,rule["min_depth_mm"]+allowance_y)
        cell.max_w=min(cell.max_w,rule["max_width_mm"]+allowance_x)
        cell.max_d=min(cell.max_d,rule["max_depth_mm"]+allowance_y)
    for cell in cells:
        # Physical partition lines use integer mm. Round minima upward and
        # maxima downward before the fractional-foot solve, including odd
        # interior wall thicknesses with half-mm finished-face offsets.
        cell.min_w,cell.min_d=math.ceil(cell.min_w),math.ceil(cell.min_d)
        cell.max_w,cell.max_d=math.floor(cell.max_w),math.floor(cell.max_d)
    data = compile_floor_constraints(cells, links, width, depth)
    rects, numeric_proof = _strict_dimension(cells, data, width, depth)
    envelope = box(0, 0, width, depth)
    grouped = {}
    for cell, rect in zip(cells, rects):
        grouped.setdefault(cell.key, {"role": cell.role, "cells": []})["cells"].append(box(*rect))
    shapes, rooms = {}, []
    for key, item in grouped.items():
        shape = unary_union(item["cells"])
        if shape.geom_type != "Polygon" or shape.interiors:
            raise FloorSolveError("A merged programme room is disconnected or has an unsupported hole.")
        shapes[key] = shape
        clear = clear_face_shape(shape, envelope, walls)
        if clear.is_empty or clear.geom_type != "Polygon":
            raise FloorSolveError("A room has no connected usable space after wall faces.")
        usable = [clear.intersection(c) for c in item["cells"]]
        largest = max(usable, key=lambda p: p.area)
        x0, y0, x1, y1 = largest.bounds
        if len(polygon_points(shape)) > 4:
            x0, y0, x1, y1 = clear.bounds
        rule = deepcopy(profile["room_rules"][item["role"]])
        # Name and room kind are display metadata; semantic rules are explicit.
        room = {"id": f"{role}:{key}", "role": item["role"], "kind": ROOM_KINDS.get(item["role"], "other"),
            "name": ROOM_NAMES[item["role"]] + (" " + key.rsplit("_",1)[-1] if key.startswith("bedroom_") and key[-1].isdigit() else ""),
            "polygon": polygon_points(shape), "cells": [polygon_points(c) for c in item["cells"]],
            "clear_polygon": [list(p) for p in list(clear.exterior.coords)[:-1]], "clear_width_mm": round(x1-x0), "clear_depth_mm": round(y1-y0), "clear_area_m2": round(clear.area/1e6, 4),
            "dimension_basis": "overall" if len(polygon_points(shape)) > 4 else "clear_rectangle", "constraints": rule}
        rooms.append(room)
    doors = []
    for a, b in links:
        kind = "opening" if {grouped[a]["role"], grouped[b]["role"]} == {"kitchen", "living"} or "stair" in (a,b) else "door"
        doors.append(_make_door(shapes[a], shapes[b], f"{role}:{a}", f"{role}:{b}", f"{role}:door:{a}:{b}", kind=kind, width=900 if "stair" in (a,b) else 850,
                                preferred_point=(core_w, math.floor(core_d - walls["interior_mm"]/2)-500) if "stair" in (a,b) else None))
    root = "entrance" if role == "ground" else "landing"
    if role == "ground":
        edge = box(0,-1000,width,0)
        door = _make_door(shapes[root], edge, f"{role}:{root}", None, "ground:door:entrance", width=900)
        door["external_role"] = "entrance"
        doors.append(door)
        garden_key = "kitchen" if variant == "living_front" else "living"
        garden = _make_door(shapes[garden_key], box(0,depth,width,depth+1000), f"{role}:{garden_key}", None, "ground:door:garden", width=1000)
        garden["external_role"] = "garden"
        doors.append(garden)
    windows = []
    for key, shape in shapes.items():
        if grouped[key]["role"] not in {"living","kitchen","bedroom","study","hobby"}:
            continue
        exposed = shape.boundary.intersection(envelope.boundary)
        candidates = [s for s in _segments(exposed) if math.dist(*s) >= 1400]
        # Reserve doors on their wall, use another wall or a disjoint interval.
        for a,b in sorted(candidates, key=lambda s: -math.dist(*s)):
            length = math.dist(a,b)
            for fraction in (.5,.25,.75):
                mx,my = a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction
                dx,dy = (b[0]-a[0])/length*500,(b[1]-a[1])/length*500
                segment=[[round(mx-dx),round(my-dy)],[round(mx+dx),round(my+dy)]]
                line=LineString(segment)
                if line.distance(Point(a)) < 150 or line.distance(Point(b)) < 150:
                    continue
                if any(line.distance(LineString(d["segment"])) < 150 for d in doors):
                    continue
                windows.append({"id": f"{role}:window:{key}", "room_id": f"{role}:{key}", "segment": segment})
                break
            else:
                continue
            break
    height = profile["regular_floor_height_mm"]
    return {"id": role, "role": role, "level": level, "label": {"ground":"Ground floor","first":"First floor","second":"Second floor","attic":"Attic"}[role],
        "height_mm": height, "elevation_mm": level * height, "program_id": program_id(role,width*depth/1e6,variant if role=="ground" else f"{bedrooms}bed" if role=="first" else "standard"),
        "rooms": rooms, "doors": doors, "windows": windows, "walls": deepcopy(walls),
        "circulation_root_room_id": f"{role}:{root}", "stair_room_id": f"{role}:stair", "core_id": "main_stair", "has_outgoing_stair": role != "attic",
        "required_connections": [[f"{role}:{a}",f"{role}:{b}"] for a,b in links],
        "solver": {"name": SOLVER_NAME, "topology_source": "NL_concept_v1_contact_templates", "legacy_units": "ft", "contract_units": "mm", "output_grid_mm": 1, "grid_scope":"physical_partition_and_opening_geometry", "derived_coordinate_precision":"fractional_mm_finished_faces_and_roof_zones", "strict_envelope": True, "hard_bounds_relaxed": False, "door_overlap_mm": 1050, "solver_nodes": len(cells), **numeric_proof},
    }, (core_w,core_d)
