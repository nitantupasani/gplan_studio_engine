"""Independent acceptance gates for metric Dutch whole-house concepts.

These checks use the returned geometry after legacy solver rounding and repair.
They deliberately do not use a candidate's score, declared dimensions, graph
edges, or earlier validation report as proof of feasibility.  Numerical limits
belong to a versioned *concept* profile, not to a building-regulation claim.

Room polygons tile the gross floor plate.  Interior walls are centred on their
shared edges; exterior walls lie inside the footprint, matching planIslands.ts.
The stair room contributes to that tiling once.  The shared core is an overlay.
"""

from __future__ import annotations

from collections import Counter, deque
from itertools import combinations
import math
from numbers import Real
from typing import Any, Mapping

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


MM2_PER_M2 = 1_000_000.0
GEOMETRY_EPS_MM = 0.01
# Only for a physical integer-mm core edge compared with a finished wall face
# at a half millimetre.  Room minima, overlap and door widths do not use this.
CORE_GRID_EPS_MM = 1.01
AREA_EPS_MM2 = 0.1
MEASUREMENT_EPS_M2 = 0.005001
RENDERER_ROOF_NORMAL_THICKNESS_MM = 0.35 * 304.8
PRIVATE_TRANSIT_ROLES = frozenset({
    "bedroom", "wc", "bathroom", "bathroom_wc", "utility", "eaves_storage",
    "storage", "pantry", "coats",
})
EXTERIOR_ROOM_ROLES = frozenset({"living", "kitchen", "bedroom", "study", "hobby"})
UNASSESSED = (
    ("dutch_regulations", "Dutch regulation and permit compliance is not assessed."),
    ("structural_design", "Structural members, foundations and load paths are not assessed."),
    ("fire_safety", "Fire resistance, compartmentation and escape certification are not assessed."),
    ("daylight_ventilation", "Window contact is checked; daylight and ventilation performance are not assessed."),
    ("accessibility", "Concept circulation is checked; accessibility certification is not assessed."),
    ("vehicle_manoeuvring", "Only a straight on-plot vehicle approach is checked; turning, reversing and public-road access are not assessed."),
    ("nen_area_measurement", "Polygon and roof-height areas are concept estimates, not certified NEN usable area."),
    ("stair_construction", "Concept stair envelopes are checked; detailed structure, balustrades and fabrication are not assessed."),
    ("plumbing_design", "A shared wet-service reservation is checked; pipe sizing, falls and plumbing design are not assessed."),
)


def polygon_area_m2(points: list) -> float:
    """True polygon area; never the product of displayed overall dimensions."""
    return float(Polygon(points).area / MM2_PER_M2)


def clear_face_polygon(room_polygon: Any, footprint: Any,
                       interior_mm: float, exterior_mm: float) -> Any:
    """Derive finished faces from allocation polygons, without phantom cell walls.

    Returns a Shapely geometry.  A disconnected or empty result is evidence of
    an unusable room, and is rejected by the caller rather than repaired here.
    """
    room = room_polygon if hasattr(room_polygon, "geom_type") else Polygon(room_polygon)
    house = footprint if hasattr(footprint, "geom_type") else Polygon(footprint)
    internal_faces = room.buffer(-float(interior_mm) / 2.0, join_style=2)
    exterior_wall = house.boundary.buffer(float(exterior_mm), join_style=2)
    return internal_faces.difference(exterior_wall)


def geometry_polygon(geometry: Any) -> list[list[float]]:
    """A simple exterior ring for a verified polygon; measurements can use .5 mm."""
    if geometry.geom_type != "Polygon" or geometry.is_empty:
        return []
    return [[round(float(x), 6), round(float(y), 6)]
            for x, y in list(geometry.exterior.coords)[:-1]]


def roof_vertical_clearance_deduction_mm(roof: Mapping) -> float:
    """Conservatively match the current section/model's 0.35 ft roof shell.

    The request supplies a vertical clearance budget.  The common viewer shell
    has a fixed thickness normal to its slope, whose vertical depth increases
    with pitch.  A request may increase, but cannot undercut, that rendered shell.
    """
    cosine = math.cos(math.radians(float(roof.get("pitch_deg", 0))))
    modeled = RENDERER_ROOF_NORMAL_THICKNESS_MM / max(cosine, 1e-9)
    return max(float(roof.get("thickness_mm", roof.get("roof_thickness_mm", 150))), modeled)


def roof_height_mm(point: tuple[float, float] | list, footprint: Any,
                   roof: Mapping) -> float:
    """Conservative clear height below the two planar faces of a gable roof."""
    house = footprint if hasattr(footprint, "geom_type") else Polygon(footprint)
    x0, y0, x1, y1 = house.bounds
    overhang = float(roof.get("overhang_mm", 0))
    x0, y0, x1, y1 = x0 - overhang, y0 - overhang, x1 + overhang, y1 + overhang
    coordinate, lower, upper = ((point[1], y0, y1) if roof.get("ridge_axis") == "x"
                                 else (point[0], x0, x1))
    run = max(0.0, min(coordinate - lower, upper - coordinate))
    return (float(roof.get("knee_wall_mm", 0)) +
            run * math.tan(math.radians(float(roof.get("pitch_deg", 0)))) -
            roof_vertical_clearance_deduction_mm(roof))


def roof_height_zone(footprint: Any, roof: Mapping, height_mm: float) -> Any:
    """Intersect the footprint with the exact gable strip above a clear height."""
    house = footprint if hasattr(footprint, "geom_type") else Polygon(footprint)
    x0, y0, x1, y1 = house.bounds
    tangent = math.tan(math.radians(float(roof.get("pitch_deg", 0))))
    if tangent <= 0:
        return Polygon()
    setback = max(0.0, (float(height_mm) + roof_vertical_clearance_deduction_mm(roof) -
                        float(roof.get("knee_wall_mm", 0))) / tangent - float(roof.get("overhang_mm", 0)))
    if roof.get("ridge_axis") == "x":
        return Polygon() if y0 + setback >= y1 - setback else house.intersection(
            box(x0, y0 + setback, x1, y1 - setback))
    return Polygon() if x0 + setback >= x1 - setback else house.intersection(
        box(x0 + setback, y0, x1 - setback, y1))


def largest_usable_rectangle(polygon: Any) -> Any:
    """Largest axis-aligned rectangle inside a small orthogonal room face.

    Coordinates come from the final face, not the solver's decomposition cells.
    Thus merged L rooms lose no area to imaginary partition walls.  The bounded
    rectangular first milestone normally has only two to six x/y coordinates.
    """
    if polygon.is_empty or polygon.geom_type != "Polygon":
        return Polygon()
    ring = list(polygon.exterior.coords)
    x_values = sorted({round(p[0], 6) for p in ring})
    y_values = sorted({round(p[1], 6) for p in ring})
    if len(x_values) > 40 or len(y_values) > 40:
        return Polygon()
    best = Polygon()
    tolerant = polygon.buffer(GEOMETRY_EPS_MM, join_style=2)
    x_pairs = sorted(combinations(x_values, 2), key=lambda p: p[1] - p[0], reverse=True)
    y_pairs = sorted(combinations(y_values, 2), key=lambda p: p[1] - p[0], reverse=True)
    for x0, x1 in x_pairs:
        for y0, y1 in y_pairs:
            if (x1 - x0) * (y1 - y0) <= best.area + AREA_EPS_MM2:
                continue
            candidate = box(x0, y0, x1, y1)
            if tolerant.covers(candidate):
                best = candidate
    return best


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value: Any) -> bool:
    return _is_number(value) and float(value).is_integer()


def _same_geometry(a: Any, b: Any) -> bool:
    return a.symmetric_difference(b).area <= AREA_EPS_MM2


def _covered(container: Any, content: Any) -> bool:
    return container.buffer(GEOMETRY_EPS_MM, join_style=2).covers(content)


def _line_on(line: Any, boundary: Any) -> bool:
    return line.difference(boundary.buffer(GEOMETRY_EPS_MM)).length <= GEOMETRY_EPS_MM


def _orthogonal(polygon: Any) -> bool:
    points = list(polygon.exterior.coords)
    return all(abs(a[0] - b[0]) <= GEOMETRY_EPS_MM or
               abs(a[1] - b[1]) <= GEOMETRY_EPS_MM
               for a, b in zip(points, points[1:]))


def _rectangle(polygon: Any) -> bool:
    return polygon.geom_type == "Polygon" and _same_geometry(polygon, box(*polygon.bounds))


def _dimensions(geometry: Any) -> tuple[float, float]:
    if geometry.is_empty:
        return 0.0, 0.0
    x0, y0, x1, y1 = geometry.bounds
    return float(x1 - x0), float(y1 - y0)


def _dimension_band(width: float, depth: float, rule: Mapping, maximum: bool = False) -> bool:
    prefix = "max" if maximum else "min"
    default = math.inf if maximum else 0.0
    a = float(rule.get(prefix + "_width_mm", default))
    b = float(rule.get(prefix + "_depth_mm", default))
    if maximum:
        fits = lambda w, d: w <= a + GEOMETRY_EPS_MM and d <= b + GEOMETRY_EPS_MM
    else:
        fits = lambda w, d: w + GEOMETRY_EPS_MM >= a and d + GEOMETRY_EPS_MM >= b
    return fits(width, depth) or fits(depth, width)


def _shifted_span_fits(line: Any, room_face: Any, inset_mm: float) -> bool:
    """Check both doorway jambs clear finished faces on an incident room side."""
    a, b = list(line.coords)
    delta = float(inset_mm) + 0.5
    if abs(a[0] - b[0]) <= GEOMETRY_EPS_MM:
        shifts = ((delta, 0), (-delta, 0))
    elif abs(a[1] - b[1]) <= GEOMETRY_EPS_MM:
        shifts = ((0, delta), (0, -delta))
    else:
        return False
    return any(_covered(room_face, LineString([
        (a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)])) for dx, dy in shifts)


def room_circulation_fits(face: Any, incident_openings: list[tuple[Any, float]],
                          minimum_width_mm: float = 850) -> bool:
    """Verify actual doors reach the useful room body at a continuous clear width.

    A connected polygon or contact graph alone can conceal a narrow neck in a
    merged L room.  Erosion tests a movable clear-width envelope, and all actual
    door approaches must reach the same component as the useful room rectangle.
    """
    if face.is_empty or face.geom_type != "Polygon" or not incident_openings:
        return False
    radius = minimum_width_mm / 2
    centre_space = face.buffer(-radius + 0.01, join_style=2)
    components = list(centre_space.geoms) if hasattr(centre_space, "geoms") else [centre_space]
    useful = largest_usable_rectangle(face)
    if useful.is_empty:
        return False
    for component in components:
        if component.is_empty or not _covered(component, useful.centroid):
            continue
        all_doors_fit = True
        for line, inset in incident_openings:
            midpoint = line.interpolate(0.5, normalized=True)
            a, b = list(line.coords)
            offset = inset + radius
            offsets = ((offset, 0), (-offset, 0)) if abs(a[0] - b[0]) <= GEOMETRY_EPS_MM else ((0, offset), (0, -offset))
            if not any(_covered(component, Point(midpoint.x + dx, midpoint.y + dy)) for dx, dy in offsets):
                all_doors_fit = False
                break
        if all_doors_fit:
            return True
    return False


class _Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def check(self, identifier: str, passed: bool, message: str, **evidence: Any) -> bool:
        item = {"id": identifier, "status": "passed" if passed else "failed", "message": message}
        if evidence:
            item["evidence"] = evidence
        self.checks.append(item)
        return bool(passed)

    def polygon(self, value: Any, identifier: str, integer: bool = True) -> Any | None:
        valid_points = (isinstance(value, (list, tuple)) and len(value) >= 4 and
                        all(isinstance(p, (list, tuple)) and len(p) == 2 and
                            all((_integer(v) if integer else _is_number(v)) for v in p)
                            for p in value))
        if not self.check(identifier + ".coordinates", valid_points,
                          "Polygon coordinates must be finite integer millimetres." if integer else
                          "Derived polygon coordinates must be finite millimetres."):
            return None
        geometry = Polygon(value)
        if not self.check(identifier + ".simple", geometry.is_valid and geometry.area > AREA_EPS_MM2,
                          "Polygon must have positive area and a simple, valid boundary."):
            return None
        if not self.check(identifier + ".orthogonal", _orthogonal(geometry),
                          "The initial house validator supports orthogonal room and site polygons."):
            return None
        return geometry

    def line(self, value: Any, identifier: str) -> Any | None:
        valid = (isinstance(value, (list, tuple)) and len(value) == 2 and
                 all(isinstance(p, (list, tuple)) and len(p) == 2 and all(_integer(v) for v in p)
                     for p in value))
        if not self.check(identifier + ".coordinates", valid,
                          "Opening endpoints must be finite integer millimetres."):
            return None
        line = LineString(value)
        if not self.check(identifier + ".span", line.length > GEOMETRY_EPS_MM,
                          "Opening must have positive span."):
            return None
        return line

    def finish(self, measurements: dict | None = None) -> dict:
        violations = [dict(item) for item in self.checks if item["status"] == "failed"]
        return {
            "valid": not violations,
            "checks": self.checks + [
                {"id": identifier, "status": "not_assessed", "message": message}
                for identifier, message in UNASSESSED],
            "violations": violations,
            "not_assessed": [identifier for identifier, _ in UNASSESSED],
            "measurements": measurements or {},
            "measurement_basis": "Finished room faces; gross floor plates; approximate roof-clearance area.",
        }


def _profile_rules(profile: Mapping) -> Mapping:
    return profile.get("room_rules", {})


def _assumption(profile: Mapping, key: str, default: float) -> float:
    assumptions = profile.get("assumptions", {})
    value = assumptions.get(key, profile.get(key, default)) if isinstance(assumptions, Mapping) else profile.get(key, default)
    return float(value) if _is_number(value) else default


def _reachable(graph: Mapping[str, set], root: str, stop_private: set[str] | None = None) -> set:
    found, pending = set(), deque([root])
    while pending:
        node = pending.popleft()
        if node in found:
            continue
        found.add(node)
        if stop_private and node in stop_private and node != root:
            continue
        pending.extend(graph.get(node, set()) - found)
    return found


def validate_house_candidate(option: Mapping, request: Mapping, profile: Mapping | None = None) -> dict:
    """Return a fresh acceptance report; malformed or infeasible options reject.

    The solver must call this only after millimetre conversion, repair, room
    merging and opening placement.  The function has no solver dependency and
    never relaxes a failed rule in response to a search shortfall.
    """
    report = _Report()
    if not isinstance(option, Mapping) or not isinstance(request, Mapping):
        report.check("contract.object", False, "House option and request must be objects.")
        return report.finish()
    if profile is None:
        from .programs import get_profile
        profile = get_profile(request.get("programme_profile", "NL_concept_v1"))
    if not isinstance(profile, Mapping):
        report.check("profile.object", False, "A versioned programme profile is required.")
        return report.finish()
    try:
        return _validate(option, request, profile, report)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as error:
        # Untrusted candidate metadata must reject instead of aborting the job.
        report.check("contract.malformed", False,
                     "House candidate contains malformed required metadata.", error=str(error))
        return report.finish()


def _validate(option: Mapping, request: Mapping, profile: Mapping, report: _Report) -> dict:
    report.check("contract.units", request.get("units") == "mm" and option.get("units", "mm") == "mm",
                 "The whole-house contract uses millimetres.")
    report.check("contract.profile", request.get("programme_profile", "NL_concept_v1") ==
                 profile.get("id", profile.get("name", "NL_concept_v1")),
                 "The requested versioned programme profile must be the validation profile.")
    site = option.get("site", {})
    plot = report.polygon(site.get("plot_polygon"), "site.plot")
    footprint = report.polygon(site.get("footprint"), "site.footprint")
    request_plot = report.polygon(request.get("plot", {}).get("polygon"), "request.plot")
    if plot is None or footprint is None or request_plot is None:
        return report.finish()
    report.check("site.request_plot", _same_geometry(plot, request_plot),
                 "Returned plot must preserve the requested plot exactly.")
    report.check("site.rectangle_support", _rectangle(plot) and _rectangle(footprint),
                 "The initial provider supports axis-aligned rectangular plots and footprints.")
    report.check("site.building_containment", _covered(plot, footprint),
                 "Building footprint must lie inside the plot.")
    walls = request.get("walls", {"interior_mm": 100, "exterior_mm": 200})
    interior, exterior = walls.get("interior_mm", 100), walls.get("exterior_mm", 200)
    if not report.check("walls.dimensions", _integer(interior) and _integer(exterior) and
                        0 < interior <= 1000 and 0 < exterior <= 1500,
                        "Positive integer wall thicknesses are required for finished-face measurements."):
        return report.finish()
    echoed_walls = option.get("walls", walls)
    report.check("walls.request", echoed_walls.get("interior_mm") == interior and
                 echoed_walls.get("exterior_mm") == exterior,
                 "Returned wall thicknesses must preserve the request.")
    site_data = _validate_site(option, request, profile, report, plot, footprint)
    floors = option.get("floors", [])
    if not report.check("stack.complete", isinstance(floors, list) and 2 <= len(floors) <= 4,
                        "A supported house has two or three regular floors and an optional attic."):
        return report.finish()
    floor_data = []
    all_ids: list[str] = []
    for floor in floors:
        floor_data.append(_validate_floor(floor, option, request, profile, report,
                                           footprint, interior, exterior, all_ids))
    report.check("identity.unique", len(all_ids) == len(set(all_ids)),
                 "Floor, room, door and window IDs must be globally unique within a house.")
    _validate_stack(option, request, profile, report, footprint, floor_data, interior, exterior)
    roof_data = _validate_roof(option, request, profile, report, footprint, floor_data)
    measurements = _validate_measurements(option, profile, report, plot, footprint,
                                          site_data, floor_data, roof_data)
    return report.finish(measurements)


def _validate_site(option: Mapping, request: Mapping, profile: Mapping, report: _Report,
                   plot: Any, footprint: Any) -> dict:
    site = option["site"]
    spaces = site.get("spaces", [])
    report.check("site.spaces", isinstance(spaces, list) and bool(spaces),
                 "Outdoor areas must be explicitly classified as site spaces.")
    parsed = []
    space_ids = []
    for index, space in enumerate(spaces):
        identifier = str(space.get("id", ""))
        space_ids.append(identifier)
        polygon = report.polygon(space.get("polygon"), "site.space." + (identifier or str(index)))
        if polygon is None:
            continue
        role = space.get("role", "garden" if space.get("kind") == "green" else
                         "parking_bay" if space.get("kind") == "parking" else "forecourt")
        report.check("site.space." + identifier + ".role", role in {
            "garden", "parking_bay", "vehicle_access", "pedestrian_access", "forecourt",
            "cycle_storage", "outdoor_storage"}, "Every outdoor polygon has a supported site role.")
        report.check("site.space." + identifier + ".containment", _covered(plot, polygon),
                     "Outdoor polygons must lie inside the plot.")
        report.check("site.space." + identifier + ".building_overlap",
                     polygon.intersection(footprint).area <= AREA_EPS_MM2,
                     "Parking, paths and garden must not overlap the building interior.")
        parsed.append((space, role, polygon))
    report.check("site.space_ids", all(space_ids) and len(space_ids) == len(set(space_ids)),
                 "Site-space IDs must be present and unique.")
    outdoor_union = unary_union([polygon for _, _, polygon in parsed]) if parsed else Polygon()
    remainder = plot.difference(footprint).difference(outdoor_union)
    report.check("site.residual_classification", remainder.area <= AREA_EPS_MM2,
                 "All land outside the footprint must have an explicit site classification.",
                 unclassified_area_m2=remainder.area / MM2_PER_M2)
    for (a, role_a, geom_a), (b, role_b, geom_b) in combinations(parsed, 2):
        incompatible = (role_a == "garden" or role_b == "garden" or
                        role_a in {"cycle_storage", "outdoor_storage"} or
                        role_b in {"cycle_storage", "outdoor_storage"} or
                        role_a == role_b == "parking_bay")
        if incompatible:
            report.check("site.nonoverlap." + str(a["id"]) + "." + str(b["id"]),
                         geom_a.intersection(geom_b).area <= AREA_EPS_MM2,
                         "Garden, storage and distinct parking bays must not double-book land.")
    front_index = request.get("plot", {}).get("front_edge", 0)
    requested_points = list(plot.exterior.coords)[:-1]
    # Use request order, because Shapely may normalise orientation in later operations.
    supplied_points = request.get("plot", {}).get("polygon", requested_points)
    if supplied_points and supplied_points[0] == supplied_points[-1]:
        supplied_points = supplied_points[:-1]
    valid_front_index = isinstance(front_index, int) and not isinstance(front_index, bool) and \
        0 <= front_index < len(supplied_points)
    report.check("site.front_edge_index", valid_front_index,
                 "Frontage must reference one of the requested plot edges.")
    front = report.line(site.get("front_boundary"), "site.front_boundary")
    if front is not None and valid_front_index:
        expected_front = LineString([supplied_points[front_index],
                                     supplied_points[(front_index + 1) % len(supplied_points)]])
        report.check("site.request_frontage", front.hausdorff_distance(expected_front) <= GEOMETRY_EPS_MM,
                     "Public access must use the requested frontage, including its direction.")
        for offset, key in ((0, "front_mm"), (1, "side_mm"), (2, "rear_mm"), (3, "side_mm")):
            edge_index = (front_index + offset) % len(supplied_points)
            boundary = LineString([supplied_points[edge_index], supplied_points[(edge_index + 1) % len(supplied_points)]])
            minimum = request.get("setbacks", {}).get(key, 0)
            report.check("site.setback." + str(edge_index), _integer(minimum) and minimum >= 0 and
                         footprint.distance(boundary) + GEOMETRY_EPS_MM >= minimum,
                         "The footprint must preserve every explicitly requested frontage, side and rear setback.",
                         minimum_mm=minimum, actual_mm=footprint.distance(boundary))
    entrance_value = site.get("entrance_point")
    entrance_valid = (isinstance(entrance_value, (list, tuple)) and len(entrance_value) == 2 and
                      all(_integer(value) for value in entrance_value))
    report.check("site.entrance_point", entrance_valid,
                 "The house must identify an integer-millimetre entrance point.")
    entrance = Point(entrance_value) if entrance_valid else None
    if entrance is not None:
        report.check("site.entrance_on_house", entrance.distance(footprint.boundary) <= GEOMETRY_EPS_MM,
                     "The site entrance must terminate on the actual house perimeter.")
    bays = [(space, geometry) for space, role, geometry in parsed if role == "parking_bay"]
    cars_requested = request.get("parking", {}).get("cars", 1)
    report.check("site.parking_count", _integer(cars_requested) and len(bays) == cars_requested,
                 "On-plot parking must satisfy the requested car count without assuming street parking.",
                 requested=cars_requested, actual=len(bays))
    car_geometries = []
    vehicle_geometry = unary_union([geometry for _, role, geometry in parsed
                                    if role in {"vehicle_access", "parking_bay"}])
    bay_width = _assumption(profile, "parking_bay_width_mm", 2500)
    bay_depth = _assumption(profile, "parking_bay_depth_mm", 5000)
    approach_width = _assumption(profile, "vehicle_approach_width_mm", 2800)
    for space, bay in bays:
        identifier = "site.parking." + str(space["id"])
        report.check(identifier + ".rectangle", _rectangle(bay),
                     "The initial parking bay must be a rectangle.")
        if front is None:
            continue
        a, b = list(front.coords)
        front_horizontal = abs(a[1] - b[1]) <= GEOMETRY_EPS_MM
        x0, y0, x1, y1 = bay.bounds
        along, normal = (x1 - x0, y1 - y0) if front_horizontal else (y1 - y0, x1 - x0)
        report.check(identifier + ".fit", along >= bay_width and normal >= bay_depth,
                     "A parked car must fit a bay aligned with the checked straight approach.",
                     width_mm=along, depth_mm=normal)
        car = report.polygon(space["car_polygon"], identifier + ".car") if "car_polygon" in space else bay
        if car is not None:
            cw, cd = _dimensions(car)
            report.check(identifier + ".car_fit", _covered(bay, car) and _rectangle(car) and
                         ((cw >= 1800 and cd >= 4500) or (cd >= 1800 and cw >= 4500)),
                         "The represented parked vehicle must fit the bay with credible dimensions.")
            car_geometries.append(car)
        half = max(approach_width, along) / 2
        centre = bay.centroid
        if front_horizontal:
            approach = box(centre.x - half, min(a[1], y0), centre.x + half, max(a[1], y1))
        else:
            approach = box(min(a[0], x0), centre.y - half, max(a[0], x1), centre.y + half)
        report.check(identifier + ".straight_vehicle_approach",
                     _covered(plot, approach) and _covered(vehicle_geometry, approach) and
                     approach.intersection(footprint).area <= AREA_EPS_MM2 and
                     approach.intersection(front).length + GEOMETRY_EPS_MM >= approach_width,
                     "A continuous straight vehicle envelope must connect the chosen frontage to the bay.")
    paths = [geometry for _, role, geometry in parsed if role == "pedestrian_access"]
    report.check("site.pedestrian_path", bool(paths),
                 "An independent pedestrian route must be explicitly provided.")
    if paths and front is not None and entrance is not None:
        walkable = unary_union(paths)
        obstacles = unary_union(car_geometries + [footprint])
        report.check("site.pedestrian_unblocked", walkable.intersection(obstacles).area <= AREA_EPS_MM2,
                     "The pedestrian route must remain clear with all represented cars parked.")
        minimum_width = _assumption(profile, "pedestrian_clear_width_mm", 900)
        radius = minimum_width / 2
        # Slightly reduce the radius only for robust exact-minimum-width corridors.
        centre_space = walkable.difference(obstacles).buffer(-radius + 0.01, join_style=2)
        components = list(centre_space.geoms) if hasattr(centre_space, "geoms") else [centre_space]
        connects = any(not component.is_empty and component.distance(front) <= radius + GEOMETRY_EPS_MM
                       and component.distance(entrance) <= radius + GEOMETRY_EPS_MM
                       for component in components)
        report.check("site.pedestrian_connectivity", connects,
                     "A route of the minimum clear width must continuously join frontage and entrance.",
                     minimum_width_mm=minimum_width)
        for space, bay in bays:
            report.check("site.parking." + str(space["id"]) + ".pedestrian_connection",
                         walkable.distance(bay) <= GEOMETRY_EPS_MM,
                         "The parking bay must connect to the independent pedestrian route.")
    return {"spaces": parsed, "entrance": entrance, "front": front}


def _validate_floor(floor: Mapping, option: Mapping, request: Mapping, profile: Mapping,
                    report: _Report, footprint: Any, interior: float, exterior: float,
                    all_ids: list) -> dict:
    floor_id = str(floor.get("id", ""))
    base = "floor." + floor_id
    all_ids.append(floor_id)
    report.check(base + ".id", bool(floor_id), "Every floor needs a stable ID.")
    rooms = floor.get("rooms", [])
    report.check(base + ".rooms", isinstance(rooms, list) and bool(rooms),
                 "Every returned floor must contain its complete solved programme.")
    data: dict[str, dict] = {}
    rules = _profile_rules(profile)
    for index, room in enumerate(rooms):
        room_id = str(room.get("id", ""))
        room_base = base + ".room." + (room_id or str(index))
        all_ids.append(room_id)
        report.check(room_base + ".id", bool(room_id), "Every room needs a stable ID.")
        role = room.get("role")
        report.check(room_base + ".typed_role", role in rules,
                     "Every room must use a semantic role defined by the versioned profile.")
        report.check(room_base + ".indoor_role", role not in {
            "parking", "parking_bay", "garden", "vehicle_access", "pedestrian_access", "forecourt"},
            "Site spaces must never enter the indoor room graph or floor accounting.")
        geometry = report.polygon(room.get("polygon"), room_base)
        if geometry is None:
            continue
        report.check(room_base + ".containment", _covered(footprint, geometry),
                     "Every room allocation must lie inside the building footprint.")
        if room.get("cells"):
            cells = [report.polygon(value, room_base + ".cell." + str(i))
                     for i, value in enumerate(room["cells"])]
            good_cells = [cell for cell in cells if cell is not None]
            report.check(room_base + ".cell_union", len(good_cells) == len(cells) and
                         _same_geometry(unary_union(good_cells), geometry),
                         "Solver cells must exactly reconstruct the final merged room.")
            report.check(room_base + ".cell_nonoverlap", all(
                a.intersection(b).area <= AREA_EPS_MM2 for a, b in combinations(good_cells, 2)),
                "Merged solver cells must not overlap.")
        face = clear_face_polygon(geometry, footprint, interior, exterior)
        face_ok = report.check(room_base + ".finished_face", face.geom_type == "Polygon" and
                               not face.is_empty and face.is_valid and not face.interiors,
                               "Finished wall faces must leave one connected, usable room polygon.")
        functional = largest_usable_rectangle(face) if face_ok else Polygon()
        width, depth = _dimensions(functional)
        overall_width, overall_depth = _dimensions(face)
        rule = rules.get(role, {})
        # Attic minimum occupancy is evaluated on the independent roof-qualified
        # part below.  Its overall hard maxima and finished-face area still apply.
        if floor.get("role") != "attic" or role in {"stair", "eaves_storage", "storage"}:
            report.check(room_base + ".minimum_dimensions", _dimension_band(width, depth, rule),
                         "A contained finished-face rectangle must meet the room's hard minimum dimensions.",
                         width_mm=width, depth_mm=depth)
            report.check(room_base + ".minimum_area", face.area / MM2_PER_M2 + 1e-8 >=
                         float(rule.get("min_area_m2", 0)),
                         "The final finished-face polygon must meet the room's hard minimum area.",
                         area_m2=face.area / MM2_PER_M2)
        report.check(room_base + ".maximum_dimensions", _dimension_band(overall_width, overall_depth, rule, True),
                     "Hard room dimension maxima must survive solver repair and merging.",
                     width_mm=overall_width, depth_mm=overall_depth)
        report.check(room_base + ".maximum_area", face.area / MM2_PER_M2 <=
                     float(rule.get("max_area_m2", math.inf)) + 1e-8,
                     "Hard room area maxima must survive solver repair and merging.")
        for key, actual in (("clear_area_m2", face.area / MM2_PER_M2),
                            ("area_m2", geometry.area / MM2_PER_M2)):
            if key in room:
                report.check(room_base + ".measure." + key, _is_number(room[key]) and
                             abs(float(room[key]) - actual) <= MEASUREMENT_EPS_M2,
                             "Declared room areas must match actual polygons.", actual=actual)
        if "clear_width_mm" in room or "clear_depth_mm" in room:
            measured = (room.get("clear_width_mm"), room.get("clear_depth_mm"))
            expected = (overall_width, overall_depth) if room.get("dimension_basis") == "overall" else (width, depth)
            valid_dimensions = all(_is_number(value) for value in measured) and (
                all(abs(float(a) - b) <= 1.01 for a, b in zip(measured, expected)) or
                all(abs(float(a) - b) <= 1.01 for a, b in zip(reversed(measured), expected)))
            report.check(room_base + ".measure.clear_dimensions", valid_dimensions,
                         "Declared clear dimensions must use the final finished face and stated basis.",
                         actual_width_mm=expected[0], actual_depth_mm=expected[1])
        if "clear_polygon" in room:
            declared_face = report.polygon(room["clear_polygon"], room_base + ".declared_clear", integer=False)
            report.check(room_base + ".measure.clear_polygon", declared_face is not None and
                         _same_geometry(face, declared_face),
                         "A declared finished-face polygon must match independent wall deductions.")
        data[room_id] = {"room": room, "polygon": geometry, "face": face,
                         "functional": functional, "role": role}
    for (id_a, a), (id_b, b) in combinations(data.items(), 2):
        report.check(base + ".overlap." + id_a + "." + id_b,
                     a["polygon"].intersection(b["polygon"]).area <= AREA_EPS_MM2,
                     "Room allocations must not overlap, including the stair room.")
    union = unary_union([room["polygon"] for room in data.values()])
    report.check(base + ".exact_coverage", _same_geometry(union, footprint),
                 "The final rooms, including the stair allocation, must exactly tile the whole floor plate.",
                 uncovered_area_m2=footprint.difference(union).area / MM2_PER_M2,
                 outside_area_m2=union.difference(footprint).area / MM2_PER_M2)
    _validate_programme(floor, data, request, profile, report, base)
    doors, graph = _validate_openings(floor, data, option, request, profile, report,
                                     footprint, interior, exterior, all_ids)
    return {"floor": floor, "rooms": data, "doors": doors, "graph": graph,
            "gross_area_m2": union.area / MM2_PER_M2}


def _validate_programme(floor: Mapping, rooms: Mapping, request: Mapping, profile: Mapping,
                        report: _Report, base: str) -> None:
    counts = Counter(item["role"] for item in rooms.values())
    role = floor.get("role")
    required = {
        "ground": {"entrance": 1, "wc": 1, "stair": 1, "living": 1, "kitchen": 1},
        "first": {"landing": 1, "stair": 1, "bedroom": 1},
        "second": {"landing": 1, "stair": 1},
        "attic": {"attic_landing": 1, "stair": 1},
    }.get(role)
    report.check(base + ".role", required is not None,
                 "Floor roles must be ground, first, second or attic.")
    if required is None:
        return
    for room_role, minimum in required.items():
        report.check(base + ".programme." + room_role, counts[room_role] >= minimum,
                     "The required semantic room programme must remain complete after solving.",
                     required=minimum, actual=counts[room_role])
    report.check(base + ".programme.single_stair", counts["stair"] == 1,
                 "One shared-core stair allocation must be present exactly once per floor.")
    if role == "first":
        separate = request.get("household", {}).get("bathroom_wc", "combined") == "separate"
        satisfied = (counts["bathroom"] >= 1 and counts["wc"] >= 1) if separate else counts["bathroom_wc"] >= 1
        report.check(base + ".programme.upper_wc", satisfied,
                     "The first-floor bathroom/WC arrangement must preserve the household request.")
    if role == "second":
        report.check(base + ".programme.occupied_extension", any(counts[r] for r in
                     {"bedroom", "study", "utility", "bathroom", "bathroom_wc"}),
                     "A second full floor must contain a coherent additional room programme.")
    if role == "attic":
        report.check(base + ".programme.roof_use", any(counts[r] for r in
                     {"hobby", "bedroom", "study", "utility", "eaves_storage"}),
                     "The attic must identify its occupied or storage use.")


def _validate_openings(floor: Mapping, rooms: Mapping, option: Mapping, request: Mapping,
                       profile: Mapping, report: _Report, footprint: Any,
                       interior: float, exterior: float, all_ids: list) -> tuple[list, dict]:
    base = "floor." + str(floor.get("id", ""))
    graph = {room_id: set() for room_id in rooms}
    checked_doors = []
    entrance_rooms = []
    minimum_door_width = _assumption(profile, "minimum_door_width_mm", 850)
    for index, door in enumerate(floor.get("doors", [])):
        door_id = str(door.get("id", ""))
        all_ids.append(door_id)
        door_base = base + ".door." + (door_id or str(index))
        report.check(door_base + ".id", bool(door_id), "Every opening needs a stable ID.")
        line = report.line(door.get("segment"), door_base)
        source, target = door.get("from_room_id"), door.get("to_room_id")
        kind = door.get("kind")
        valid_refs = source in rooms and (target is None or target in rooms) and source != target
        report.check(door_base + ".references", valid_refs,
                     "Doors must reference their actual incident rooms, or the exterior.")
        report.check(door_base + ".kind", kind in {"door", "opening"},
                     "A room-graph edge must be realised as a door or an open passage.")
        if line is None or not valid_refs:
            continue
        width_ok = report.check(door_base + ".width", line.length + GEOMETRY_EPS_MM >= minimum_door_width,
                               "Every usable door or passage must meet the hard clear-span assumption.",
                               width_mm=line.length, minimum_mm=minimum_door_width)
        source_room = rooms[source]
        incident_boundary = source_room["polygon"].boundary.intersection(
            footprint.boundary if target is None else rooms[target]["polygon"].boundary)
        contact_ok = report.check(door_base + ".contact", _line_on(line, incident_boundary),
                                  "The full opening segment must lie on the actual common boundary.")
        source_clear = _shifted_span_fits(line, source_room["face"], exterior if target is None else interior / 2)
        target_clear = True if target is None else _shifted_span_fits(line, rooms[target]["face"], interior / 2)
        jamb_ok = report.check(door_base + ".finished_clearance", source_clear and target_clear,
                               "Door jambs and both incident sides must clear the final wall faces.")
        valid = width_ok and contact_ok and jamb_ok and kind in {"door", "opening"}
        if target is not None and valid:
            graph[source].add(target)
            graph[target].add(source)
        if target is None:
            external_role = door.get("external_role")
            report.check(door_base + ".external_role", external_role in {"entrance", "garden"},
                         "An external door must identify entrance or garden access.")
            if external_role == "entrance":
                report.check(door_base + ".entrance_floor", floor.get("role") == "ground",
                             "The public entrance must be on the ground floor.")
                report.check(door_base + ".entrance_room", source_room["role"] == "entrance",
                             "The public entrance must serve the entrance circulation room.")
                entrance_point = option.get("site", {}).get("entrance_point")
                match = isinstance(entrance_point, (list, tuple)) and len(entrance_point) == 2 and \
                    all(_is_number(v) for v in entrance_point) and line.distance(Point(entrance_point)) <= GEOMETRY_EPS_MM
                report.check(door_base + ".site_entry", match,
                             "The actual entrance doorway must meet the reserved pedestrian route.")
                if valid:
                    entrance_rooms.append(source)
            if external_role == "garden":
                gardens = unary_union([Polygon(space["polygon"]) for space in option.get("site", {}).get("spaces", [])
                                       if space.get("role") == "garden"])
                report.check(door_base + ".garden_floor", floor.get("role") == "ground",
                             "A direct garden doorway must be at the actual ground-floor garden level.")
                report.check(door_base + ".garden_contact", not gardens.is_empty and _line_on(line, gardens.boundary),
                             "A garden doorway must actually meet a reserved garden polygon; no-garden cases must omit it.")
        checked_doors.append({"door": door, "line": line, "valid": valid})
    root = floor.get("circulation_root_room_id")
    expected_root_roles = {"ground": {"entrance"}, "first": {"landing"}, "second": {"landing"},
                           "attic": {"attic_landing"}}.get(floor.get("role"), set())
    root_ok = report.check(base + ".circulation.root", root in rooms and rooms[root]["role"] in expected_root_roles,
                           "Circulation must start at the ground entrance or the actual upper landing.")
    if floor.get("role") == "ground":
        report.check(base + ".circulation.entrance", len(entrance_rooms) == 1 and root in entrance_rooms,
                     "Exactly one valid public entrance must reach the circulation root.")
    if root_ok:
        reached = _reachable(graph, root)
        report.check(base + ".circulation.connected", reached == set(rooms),
                     "Every room must be traversable through actual valid openings from this floor's arrival.",
                     unreachable=sorted(set(rooms) - reached))
        private = {room_id for room_id, item in rooms.items() if item["role"] in PRIVATE_TRANSIT_ROLES | {"stair"}}
        without_private_transit = _reachable(graph, root, private)
        report.check(base + ".circulation.privacy", without_private_transit == set(rooms),
                     "Bedrooms, toilets, bathrooms, utility, storage and stair flights must not be required through-routes.",
                     inaccessible_without_private_transit=sorted(set(rooms) - without_private_transit))
        stair_ids = [room_id for room_id, item in rooms.items() if item["role"] == "stair"]
        report.check(base + ".circulation.stair_arrival", len(stair_ids) == 1 and
                     root in graph.get(stair_ids[0], set()),
                     "The shared stair must have a real opening directly into the floor's entrance or landing.")
    route_width = _assumption(profile, "minimum_room_route_width_mm", minimum_door_width)
    for room_id, item in rooms.items():
        incident = [(opening["line"], exterior if opening["door"].get("to_room_id") is None else interior / 2)
                    for opening in checked_doors if opening["valid"] and room_id in
                    {opening["door"].get("from_room_id"), opening["door"].get("to_room_id")}]
        report.check(base + ".room." + room_id + ".internal_circulation",
                     room_circulation_fits(item["face"], incident, route_width),
                     "Every actual doorway must reach the useful room body through a continuous clear-width route.",
                     minimum_width_mm=route_width)
    for index, pair in enumerate(floor.get("required_connections", [])):
        valid = isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] in rooms and pair[1] in rooms
        report.check(base + ".required_connection." + str(index), valid and pair[1] in graph.get(pair[0], set()),
                     "Required programme contacts must have real, valid openings.")
    if floor.get("role") == "ground":
        living = {room_id for room_id, item in rooms.items() if item["role"] == "living"}
        kitchen = {room_id for room_id, item in rooms.items() if item["role"] == "kitchen"}
        open_connection = any(item["valid"] and item["door"].get("kind") == "opening" and
                              {item["door"].get("from_room_id"), item["door"].get("to_room_id")} & living and
                              {item["door"].get("from_room_id"), item["door"].get("to_room_id")} & kitchen
                              for item in checked_doors)
        report.check(base + ".programme.open_kitchen_living", bool(open_connection),
                     "The ground-floor kitchen and living programme must have its intended open connection.")
    party_segments = []
    plot_points = request.get("plot", {}).get("polygon", [])
    for edge in request.get("plot", {}).get("party_wall_edges", []):
        if isinstance(edge, int) and 0 <= edge < len(plot_points):
            party_segments.append(LineString([plot_points[edge], plot_points[(edge + 1) % len(plot_points)]]))
        else:
            report.check(base + ".party_wall_reference", False, "Party-wall edges must reference actual plot edges.")
    valid_windows = Counter()
    for index, window in enumerate(floor.get("windows", [])):
        window_id = str(window.get("id", ""))
        all_ids.append(window_id)
        window_base = base + ".window." + (window_id or str(index))
        report.check(window_base + ".id", bool(window_id), "Every window needs a stable ID.")
        line = report.line(window.get("segment"), window_base)
        room_id = window.get("room_id")
        refs_ok = report.check(window_base + ".room_reference", room_id in rooms,
                               "Windows must reference their actual room.")
        if line is None or not refs_ok:
            continue
        contact = rooms[room_id]["polygon"].boundary.intersection(footprint.boundary)
        exposed = report.check(window_base + ".exterior_contact", _line_on(line, contact),
                                "A window must lie completely on an actual exterior room wall.")
        party_free = report.check(window_base + ".party_wall", not any(
            line.intersection(party.buffer(GEOMETRY_EPS_MM)).length > GEOMETRY_EPS_MM for party in party_segments),
            "Party-wall contact cannot count as an exposed window wall.")
        clear = report.check(window_base + ".finished_clearance", _shifted_span_fits(line, rooms[room_id]["face"], exterior),
                              "The window span must fit within the room's finished exterior wall face.")
        if exposed and party_free and clear:
            valid_windows[room_id] += 1
    for room_id, item in rooms.items():
        requires = bool(_profile_rules(profile).get(item["role"], {}).get("requires_exterior", item["role"] in EXTERIOR_ROOM_ROLES))
        if requires:
            report.check(base + ".room." + room_id + ".exterior_window", valid_windows[room_id] > 0,
                         "The occupied room requires at least one geometrically valid exposed-wall window.")
    return checked_doors, graph


def _validate_stack(option: Mapping, request: Mapping, profile: Mapping, report: _Report,
                    footprint: Any, floors: list, interior: float, exterior: float) -> None:
    roles = [item["floor"].get("role") for item in floors]
    regular_count = sum(role != "attic" for role in roles)
    has_attic = "attic" in roles
    expected_roles = ["ground", "first"] + (["second"] if regular_count == 3 else []) + (["attic"] if has_attic else [])
    report.check("stack.floor_order", regular_count in {2, 3} and roles == expected_roles,
                 "G+1 has two regular floors; G+2 has three; any attic is one separate final roof floor.",
                 roles=roles, regular_storeys=regular_count)
    mode = "g+" + str(regular_count - 1) + ("_attic" if has_attic else "")
    storeys = request.get("storeys", {})
    requested_mode = storeys.get("mode", "auto")
    allowed = storeys.get("allow", ["g+1_attic", "g+2_attic"])
    report.check("stack.requested_mode", mode in allowed and (requested_mode == "auto" or requested_mode == mode),
                 "The complete floor stack must preserve the requested and allowed storey modes.",
                 actual=mode, requested=requested_mode)
    elevation = 0
    regular_height = _assumption(profile, "regular_floor_height_mm", 3000)
    for index, item in enumerate(floors):
        floor = item["floor"]
        base = "floor." + str(floor.get("id", ""))
        height = floor.get("height_mm")
        report.check(base + ".stack.level", floor.get("level") == index,
                     "Floor level numbers must be consecutive from ground level zero.")
        height_ok = report.check(base + ".stack.height", _integer(height) and 500 <= height <= 4500,
                                 "Floor heights must be credible positive integer millimetres.")
        if floor.get("role") != "attic":
            report.check(base + ".stack.regular_height", height == regular_height,
                         "Regular floor spacing must match the versioned concept profile.")
        report.check(base + ".stack.elevation", floor.get("elevation_mm") == elevation,
                     "Each floor elevation must equal the sum of the preceding floor heights.",
                     expected_elevation_mm=elevation)
        report.check(base + ".stack.outgoing_stair", floor.get("has_outgoing_stair") is (index < len(floors) - 1),
                     "Every lower floor needs an outgoing stair; the final floor must have none.")
        if height_ok:
            elevation += height
    bedroom_count = sum(item["role"] == "bedroom" for floor in floors for item in floor["rooms"].values())
    requested_bedrooms = request.get("household", {}).get("bedrooms", 2)
    report.check("programme.household_bedrooms", _integer(requested_bedrooms) and bedroom_count >= requested_bedrooms,
                 "The complete house must retain the requested bedroom count without silent programme downgrade.",
                 requested=requested_bedrooms, actual=bedroom_count)
    report.check("constraints.authored_locks", not request.get("locked_cores"),
                 "Authored coordinate locks require a supported lock solver; the initial provider must reject them.")
    cores = option.get("cores", [])
    stair_cores = [core for core in cores if core.get("kind") == "stairs"]
    if not report.check("stairs.shared_core", len(stair_cores) == 1,
                        "The complete house must have one explicitly shared stair core."):
        return
    core = stair_cores[0]
    core_id = core.get("id")
    report.check("stairs.core_id", isinstance(core_id, str) and bool(core_id),
                 "The shared core needs a stable ID.")
    polygon = report.polygon(core.get("polygon"), "stairs.core")
    opening = report.polygon(core.get("opening_polygon"), "stairs.opening")
    arrival = report.polygon(core.get("arrival_polygon"), "stairs.arrival")
    platform = report.polygon(core.get("platform_polygon"), "stairs.platform", integer=False)
    if polygon is None or opening is None or arrival is None or platform is None:
        return
    core_face = clear_face_polygon(polygon, footprint, interior, exterior)
    x0, y0, x1, y1 = footprint.bounds
    sx0, sy0, sx1, sy1 = polygon.bounds
    corner = ((abs(sx0 - x0) <= GEOMETRY_EPS_MM or abs(sx1 - x1) <= GEOMETRY_EPS_MM) and
              (abs(sy0 - y0) <= GEOMETRY_EPS_MM or abs(sy1 - y1) <= GEOMETRY_EPS_MM))
    report.check("stairs.corner_support", _rectangle(polygon) and _covered(footprint, polygon) and corner,
                 "The initial shared stair must be a supported rectangular corner core.")
    core_width, core_depth = core.get("width_mm"), core.get("depth_mm")
    actual_width, actual_depth = _dimensions(polygon)
    report.check("stairs.declared_dimensions", _integer(core_width) and _integer(core_depth) and
                 sorted((core_width, core_depth)) == sorted((actual_width, actual_depth)),
                 "The declared shared-core size must match its actual allocation, including rotated frontages.")
    top_platform_depth = core.get("top_platform_depth_mm")
    platform_size = _dimensions(platform)
    face_size = _dimensions(core_face)
    report.check("stairs.top_platform", _rectangle(platform) and _covered(core_face.buffer(CORE_GRID_EPS_MM, join_style=2), platform) and
                 _is_number(top_platform_depth) and top_platform_depth >= 900 and
                 abs(min(platform_size) - top_platform_depth) <= CORE_GRID_EPS_MM and
                 abs(max(platform_size) - min(face_size)) <= CORE_GRID_EPS_MM,
                 "A full-width flat floor-level platform must be reserved beyond the upper flight's final tread.")
    # Quantised slab/platform edges may differ from half-wall faces by .5 mm.
    # The wall-edge fringe is not a missing flight or an opening over a landing.
    flight_envelope = core_face.difference(platform.buffer(CORE_GRID_EPS_MM, join_style=2))
    report.check("stairs.opening_geometry", _rectangle(opening) and _covered(polygon, opening) and
                 _covered(opening.buffer(CORE_GRID_EPS_MM, join_style=2), flight_envelope) and
                 opening.intersection(platform).area <= AREA_EPS_MM2,
                 "The stair opening must clear both flights and their turn landing while retaining the floor-level platform.")
    arrival_width, arrival_depth = _dimensions(arrival)
    minimum_arrival = _assumption(profile, "minimum_arrival_width_mm", 900)
    report.check("stairs.arrival_clearance", _rectangle(arrival) and _covered(platform, arrival) and
                 min(arrival_width, arrival_depth) + GEOMETRY_EPS_MM >= minimum_arrival,
                 "Each stair arrival needs an unobstructed clear rectangle on the retained flat floor-level platform.")
    orientation = core.get("orientation")
    report.check("stairs.orientation", orientation in {0, 90, 180, 270},
                 "The supported return stair must declare a cardinal flight orientation.")
    platform_bounds, face_bounds = platform.bounds, core_face.bounds
    arrival_edge = {0: 3, 90: 0, 180: 1, 270: 2}.get(orientation)
    report.check("stairs.platform_orientation", arrival_edge is not None and
                 abs(platform_bounds[arrival_edge] - face_bounds[arrival_edge]) <= CORE_GRID_EPS_MM,
                 "The flat platform must lie at the actual upper-flight arrival end specified by its orientation.")
    centre = arrival.centroid
    canonical_across = {0: centre.x - sx0, 90: centre.y - sy0,
                        180: sx1 - centre.x, 270: sy1 - centre.y}.get(orientation, 0)
    handedness = core.get("handedness", "right")
    report.check("stairs.arrival_handedness", handedness in {"left", "right"} and
                 ((canonical_across < min(actual_width, actual_depth) / 2) if handedness == "left" else
                  (canonical_across > min(actual_width, actual_depth) / 2)),
                 "The retained arrival must be on the side of the actual ascending upper flight.")
    for item in floors:
        floor = item["floor"]
        base = "floor." + str(floor.get("id", ""))
        stair_rooms = [value for value in item["rooms"].values() if value["role"] == "stair"]
        stair_id = stair_rooms[0]["room"].get("id") if len(stair_rooms) == 1 else None
        report.check(base + ".stairs.coordinates", len(stair_rooms) == 1 and
                     _same_geometry(stair_rooms[0]["polygon"], polygon),
                     "The actual stair room must occupy the same coordinates on every floor.")
        report.check(base + ".stairs.core_reference", floor.get("core_id") == core_id and
                     floor.get("stair_room_id") == stair_id,
                     "Every floor must reference its actual stair allocation and shared core.")
        report.check(base + ".stairs.orientation", floor.get("stair_orientation") == orientation,
                     "All floor stair flights must preserve the shared orientation.")
        floor_opening = report.polygon(floor.get("stair_opening_polygon"), base + ".stairs.opening")
        floor_arrival = report.polygon(floor.get("stair_arrival_polygon"), base + ".stairs.arrival")
        floor_platform = report.polygon(floor.get("stair_platform_polygon"), base + ".stairs.platform", integer=False)
        report.check(base + ".stairs.opening_alignment", floor_opening is not None and
                     _same_geometry(floor_opening, opening),
                     "Slab openings must align exactly through the complete stair stack.")
        report.check(base + ".stairs.arrival_alignment", floor_arrival is not None and
                     _same_geometry(floor_arrival, arrival),
                     "Every connected level must preserve the shared arrival envelope.")
        report.check(base + ".stairs.platform_alignment", floor_platform is not None and
                     _same_geometry(floor_platform, platform),
                     "Every stair/landing door must be served by the same retained flat platform at its floor elevation.")
        root = floor.get("circulation_root_room_id")
        actual_arrival = any(door["valid"] and
                             {door["door"].get("from_room_id"), door["door"].get("to_room_id")} == {stair_id, root} and
                             _shifted_span_fits(door["line"], arrival, interior / 2)
                             for door in item["doors"])
        report.check(base + ".stairs.arrival_door", actual_arrival,
                     "The actual stair/landing doorway must open into the shared clear arrival envelope.")
    form = core.get("form")
    risers, rise = core.get("riser_count"), core.get("riser_height_mm")
    going, flight_width = core.get("going_mm"), core.get("flight_width_mm")
    landing_depth, well = core.get("landing_depth_mm"), core.get("well_width_mm")
    stair_height = core.get("floor_height_mm")
    numeric = all(_is_number(value) for value in (risers, rise, going, flight_width, landing_depth, well, stair_height))
    report.check("stairs.return_form", form == "u_return" and core.get("flight_count", 2) == 2,
                 "The initial credible stair envelope is a two-flight return stair.")
    if report.check("stairs.dimensions_present", numeric,
                    "Stair geometry must state rise, count, going, flight width, well and landing depth."):
        report.check("stairs.rise_count", _integer(risers) and 12 <= risers <= 24 and int(risers) % 2 == 0 and
                     140 <= rise <= 200 and abs(risers * rise - stair_height) <= 1.01,
                     "The supported equal-flight riser count and rise must exactly reach the floor-to-floor height.")
        report.check("stairs.floor_height", stair_height == regular_height and all(
            item["floor"].get("height_mm") == stair_height for item in floors[:-1]),
            "The shared stair rise must match every connected floor transition.")
        report.check("stairs.step_proportions", 220 <= going <= 350 and 550 <= 2 * rise + going <= 700,
                     "Rise and going must fit the versioned credible concept-step envelope.")
        report.check("stairs.flight_clearance", flight_width >= 900 and landing_depth >= flight_width and well >= 0,
                     "Both flights and the turn landing need sufficient clear width.")
        short, long = sorted(_dimensions(core_face))
        run = (math.ceil(risers / 2) - 1) * going + landing_depth + (top_platform_depth if _is_number(top_platform_depth) else math.inf)
        required_width = 2 * flight_width + well
        report.check("stairs.physical_fit", short + GEOMETRY_EPS_MM >= required_width and long + GEOMETRY_EPS_MM >= run,
                     "Both tread runs, the half-height turn landing and the separate floor-level platform must fit the finished core.",
                     clear_width_mm=short, clear_depth_mm=long, required_width_mm=required_width, required_depth_mm=run)
        flight_shapes = modeled_stair_footprints(core, core_face)
        report.check("stairs.modeled_envelope", all(
            _covered(opening.buffer(CORE_GRID_EPS_MM, join_style=2), shape) for shape in flight_shapes.values()),
            "Actual fixed-going flights and the half-height turn must fit the opening; spare core clearance stays beyond them.")
        high_flight = flight_shapes["upper"]
        report.check("stairs.flight_platform_connection", high_flight.intersection(platform).area <= AREA_EPS_MM2 and
                     high_flight.boundary.intersection(platform.boundary).length + GEOMETRY_EPS_MM >= flight_width,
                     "The full width of the upper flight's final tread must meet the retained floor-level platform directly.")
        face_w, face_d = _dimensions(core_face)
        orientation_fits = (face_d >= face_w if orientation in {0, 180} else face_w >= face_d)
        report.check("stairs.flight_axis", orientation in {0, 90, 180, 270} and orientation_fits,
                     "The declared flight orientation must align with the fitted long core axis.")
        slab_thickness = core.get("slab_thickness_mm", 200)
        report.check("stairs.regular_headroom", _is_number(slab_thickness) and 100 <= slab_thickness <= 400 and
                     stair_height - slab_thickness >= _assumption(profile, "minimum_arrival_headroom_mm", 2100),
                     "The repeated open-core flight stack must retain the modeled clear height below the next flight/slab.")
    sanitary_per_floor = []
    for item in floors:
        wet_rooms = [value["polygon"] for value in item["rooms"].values()
                     if value["role"] in {"wc", "bathroom", "bathroom_wc"}]
        if wet_rooms:
            sanitary_per_floor.append(unary_union(wet_rooms))
    if len(sanitary_per_floor) >= 2:
        common = sanitary_per_floor[0]
        for geometry in sanitary_per_floor[1:]:
            common = common.intersection(geometry)
        components = list(common.geoms) if hasattr(common, "geoms") else [common]
        rectangles = [largest_usable_rectangle(geometry) for geometry in components
                      if geometry.geom_type == "Polygon"]
        minimum_shaft = _assumption(profile, "minimum_service_shaft_mm", 100)
        report.check("services.shared_reservation", any(min(_dimensions(rectangle)) >= minimum_shaft
                     for rectangle in rectangles),
                     "Sanitary floor allocations must share a credible vertical service-shaft reservation.")
        if "service_zone" in core:
            zone = report.polygon(core["service_zone"], "services.declared_zone")
            report.check("services.declared_alignment", zone is not None and _covered(common, zone) and
                         min(_dimensions(zone)) >= minimum_shaft,
                         "The declared service reservation must lie in the common sanitary zone on every served floor.")


def _stair_pose(core: Mapping, face: Any) -> dict:
    """Place fixed-going flights from the actual platform, leaving front spare."""
    arrival = Polygon(core["arrival_polygon"])
    platform = Polygon(core["platform_polygon"])
    x0, y0, x1, y1 = face.bounds
    along_y = core.get("orientation") in {0, 180}
    short0, short1, long0, long1 = (x0, x1, y0, y1) if along_y else (y0, y1, x0, x1)
    arrival_short = arrival.centroid.x if along_y else arrival.centroid.y
    arrival_long = arrival.centroid.y if along_y else arrival.centroid.x
    flight_width, well = core["flight_width_mm"], core["well_width_mm"]
    if arrival_short < (short0 + short1) / 2:
        low_short = (short1 - flight_width, short1)
        high_short = (short1 - 2 * flight_width - well, short1 - flight_width - well)
    else:
        low_short = (short0, short0 + flight_width)
        high_short = (short0 + flight_width + well, short0 + 2 * flight_width + well)
    near_is_min = arrival_long < (long0 + long1) / 2
    low_risers = int(core["riser_count"]) // 2
    high_risers = int(core["riser_count"]) - low_risers
    run = (max(low_risers, high_risers) - 1) * core["going_mm"]
    near = platform.bounds[3 if along_y else 2] if near_is_min else platform.bounds[1 if along_y else 0]
    direction = 1 if near_is_min else -1
    return {"along_y": along_y, "low_short": low_short, "high_short": high_short,
            "across": (min(low_short[0], high_short[0]), max(low_short[1], high_short[1])),
            "near": near, "direction": direction, "run": run,
            "low_risers": low_risers, "high_risers": high_risers}


def modeled_stair_footprints(core: Mapping, face: Any) -> dict:
    """Derive actual flight/turn footprints using the shared viewer convention."""
    pose = _stair_pose(core, face)

    def rectangle(short_limits: tuple, distance0: float, distance1: float) -> Any:
        long = [pose["near"] + pose["direction"] * distance for distance in (distance0, distance1)]
        if pose["along_y"]:
            return box(short_limits[0], min(long), short_limits[1], max(long))
        return box(min(long), short_limits[0], max(long), short_limits[1])

    return {"lower": rectangle(pose["low_short"], 0, pose["run"]),
            "upper": rectangle(pose["high_short"], 0, pose["run"]),
            "turn": rectangle(pose["across"], pose["run"], pose["run"] + core["landing_depth_mm"])}


def _stair_roof_clearance(core: Mapping, face: Any, footprint: Any, roof: Mapping) -> float:
    """Minimum roof clearance at all corners of every explicitly modeled tread."""
    required = ("riser_count", "riser_height_mm", "going_mm", "flight_width_mm", "landing_depth_mm", "floor_height_mm", "well_width_mm")
    if not all(_is_number(core.get(key)) for key in required) or face.is_empty or not core.get("platform_polygon"):
        return -math.inf
    pose = _stair_pose(core, face)
    low_risers, high_risers, run = pose["low_risers"], pose["high_risers"], pose["run"]
    clearances = []

    def plate(short_limits: tuple, distance0: float, distance1: float, elevation: float) -> None:
        for short in short_limits:
            for distance in (distance0, distance1):
                long = pose["near"] + pose["direction"] * distance
                point = (short, long) if pose["along_y"] else (long, short)
                clearances.append(core["floor_height_mm"] - elevation + roof_height_mm(point, footprint, roof))

    for step in range(1, low_risers):
        plate(pose["low_short"], (step - 1) * core["going_mm"], step * core["going_mm"], step * core["riser_height_mm"])
    for step in range(1, high_risers):
        plate(pose["high_short"], run - step * core["going_mm"], run - (step - 1) * core["going_mm"],
              (low_risers + step) * core["riser_height_mm"])
    plate(pose["across"], run, run + core["landing_depth_mm"], low_risers * core["riser_height_mm"])
    return min(clearances) if clearances else -math.inf


def _validate_roof(option: Mapping, request: Mapping, profile: Mapping, report: _Report,
                   footprint: Any, floors: list) -> dict:
    roof = option.get("roof", {})
    roof_request = request.get("roof", {})
    valid_type = report.check("roof.type", roof.get("type") == "gable",
                               "The initial attic provider requires an explicit two-plane gable roof.")
    pitch, knee = roof.get("pitch_deg"), roof.get("knee_wall_mm")
    thickness = roof.get("thickness_mm", roof.get("roof_thickness_mm", 150))
    overhang = roof.get("overhang_mm", 0)
    geometry_ok = report.check("roof.geometry", _is_number(pitch) and 30 <= pitch <= 55 and
                               _integer(knee) and 500 <= knee <= 2100 and _integer(thickness) and
                               0 <= thickness <= 500 and _integer(overhang) and 0 <= overhang <= 800 and
                               roof.get("ridge_axis") in {"x", "y"},
                               "Pitch, knee wall, overhang and thickness must define a credible supported gable.")
    for key in ("type", "pitch_deg", "knee_wall_mm", "ridge_axis", "overhang_mm", "thickness_mm"):
        if key in roof_request:
            report.check("roof.request." + key, roof.get(key) == roof_request[key],
                         "Hard requested roof parameters must survive candidate search and repair.")
    if not valid_type or not geometry_ok:
        return {}
    report.check("roof.thickness_basis", roof.get("thickness_basis", "vertical_clearance") == "vertical_clearance" and
                 _is_number(roof.get("renderer_normal_thickness_mm", RENDERER_ROOF_NORMAL_THICKNESS_MM)) and
                 abs(roof.get("renderer_normal_thickness_mm", RENDERER_ROOF_NORMAL_THICKNESS_MM) -
                     RENDERER_ROOF_NORMAL_THICKNESS_MM) <= 1e-6,
                 "Roof clearance uses the greater of the requested vertical deduction and the common viewer's sloped shell.",
                 effective_vertical_deduction_mm=roof_vertical_clearance_deduction_mm(roof))
    width, depth = _dimensions(footprint)
    expected_axis = "x" if width >= depth else "y"
    report.check("roof.renderer_axis", roof.get("ridge_axis") == expected_axis,
                 "The initial result must match the common viewer's longest-footprint-axis gable.")
    attic = [item for item in floors if item["floor"].get("role") == "attic"]
    base_elevation = (attic[0]["floor"].get("elevation_mm") if len(attic) == 1 else
                      sum(item["floor"].get("height_mm", 0) for item in floors))
    report.check("roof.base_elevation", _is_number(base_elevation) and roof.get("base_elevation_mm") == base_elevation,
                 "The roof base must align with the actual attic floor elevation or final regular-floor top.")
    span = depth if roof["ridge_axis"] == "x" else width
    ridge = float(base_elevation) + knee + (span / 2 + overhang) * math.tan(math.radians(pitch))
    report.check("roof.ridge_elevation", _is_number(roof.get("ridge_height_mm")) and
                 abs(roof["ridge_height_mm"] - ridge) <= 1.01,
                 "The stated roof ridge must follow its span, pitch, overhang, knee wall and floor elevation.",
                 expected_ridge_height_mm=ridge)
    occupied_height = _assumption(profile, "occupied_headroom_mm", 2100)
    arrival_height = _assumption(profile, "minimum_arrival_headroom_mm", 2100)
    occupied_zone = roof_height_zone(footprint, roof, occupied_height)
    zones = roof.get("headroom_zones", [])
    report.check("roof.headroom_zones", isinstance(zones, list) and bool(zones),
                 "The roof must expose independently verifiable height zones.")
    seen_heights = set()
    for index, zone in enumerate(zones):
        minimum = zone.get("min_height_mm")
        if not report.check("roof.zone." + str(index) + ".height", _is_number(minimum) and minimum > 0,
                            "Every declared roof zone needs a positive clear-height threshold."):
            continue
        geometry = report.polygon(zone.get("polygon"), "roof.zone." + str(index), integer=False)
        expected = roof_height_zone(footprint, roof, minimum)
        report.check("roof.zone." + str(index) + ".geometry", geometry is not None and
                     not expected.is_empty and geometry.hausdorff_distance(expected) <= 1.01 and
                     geometry.difference(expected.buffer(1.01, join_style=2)).area <= AREA_EPS_MM2,
                     "Reported headroom zones must follow the actual sloping roof planes.")
        seen_heights.add(float(minimum))
    report.check("roof.required_height_zones", occupied_height in seen_heights and arrival_height in seen_heights,
                 "Occupied area and stair arrival must each have their required height zone.")
    qualified_clear_area = 0.0
    attic_gross_area = 0.0
    for item in attic:
        floor = item["floor"]
        base = "floor." + str(floor["id"])
        attic_gross_area += item["gross_area_m2"]
        report.check(base + ".attic.knee_height", floor.get("height_mm") == knee,
                     "The attic storey represents its knee-wall band, not a false full-height storey.")
        for room_id, room_data in item["rooms"].items():
            role, face, room = room_data["role"], room_data["face"], room_data["room"]
            room_base = base + ".room." + room_id
            if role == "stair":
                continue
            if role in {"eaves_storage", "storage"}:
                report.check(room_base + ".attic.storage_status", not room.get("habitable", False) and
                             float(room.get("occupied_area_m2", 0)) == 0,
                             "Low-eaves storage must not be presented as habitable or occupied usable area.")
                continue
            profile_minimum = arrival_height if role == "attic_landing" else occupied_height
            minimum = room.get("occupied_min_height_mm", profile_minimum)
            if not report.check(room_base + ".attic.height_threshold", _is_number(minimum) and
                                minimum >= profile_minimum,
                                "A room may request greater headroom, but may never weaken the profile threshold."):
                minimum = profile_minimum
            zone = roof_height_zone(footprint, roof, minimum)
            expected_occupied = face.intersection(zone)
            declared = report.polygon(room.get("occupied_zone"), room_base + ".occupied_zone", integer=False)
            report.check(room_base + ".attic.occupied_zone", declared is not None and
                         not expected_occupied.is_empty and expected_occupied.geom_type == "Polygon" and
                         declared.hausdorff_distance(expected_occupied) <= 1.01 and
                         declared.difference(expected_occupied.buffer(1.01, join_style=2)).area <= AREA_EPS_MM2,
                         "Occupied attic space must be the actual finished face inside the qualified roof-height zone.")
            rectangle = largest_usable_rectangle(expected_occupied)
            rule = _profile_rules(profile).get(role, {})
            report.check(room_base + ".attic.minimum_dimensions", _dimension_band(*_dimensions(rectangle), rule),
                         "The height-qualified attic area must contain the required usable room rectangle.")
            report.check(room_base + ".attic.minimum_area", expected_occupied.area / MM2_PER_M2 + 1e-8 >=
                         float(rule.get("min_area_m2", 0)),
                         "Only the actual height-qualified polygon may satisfy an attic room's minimum occupied area.")
            low = face.difference(zone)
            storage_values = room.get("low_headroom_storage_polygons", [])
            storage = [report.polygon(value, room_base + ".low_storage." + str(index), integer=False)
                       for index, value in enumerate(storage_values)]
            storage_polygons = [polygon for polygon in storage if polygon is not None]
            storage_union = unary_union(storage_polygons)
            report.check(room_base + ".attic.storage_classification", len(storage_polygons) == len(storage) and
                         storage_union.symmetric_difference(low).area <= max(AREA_EPS_MM2, low.length * 1.01) and
                         all(a.intersection(b).area <= AREA_EPS_MM2 for a, b in combinations(storage_polygons, 2)),
                         "Every low-height remainder must be explicitly classified as nonoccupied eaves storage.")
            if "occupied_area_m2" in room:
                report.check(room_base + ".attic.occupied_measure", _is_number(room["occupied_area_m2"]) and
                             abs(room["occupied_area_m2"] - expected_occupied.area / MM2_PER_M2) <= MEASUREMENT_EPS_M2,
                             "The declared occupied attic area must use the qualified polygon, not its bounding box.")
            qualified_clear_area += expected_occupied.area / MM2_PER_M2
        for door in item["doors"]:
            if door["valid"]:
                clear = min(roof_height_mm(point, footprint, roof) for point in door["line"].coords)
                report.check(base + ".attic.door_headroom." + str(door["door"].get("id")), clear + GEOMETRY_EPS_MM >= arrival_height,
                             "Actual attic door and circulation spans must clear the roof planes.", headroom_mm=clear)
        for window in floor.get("windows", []):
            line = LineString(window["segment"])
            a, b = list(line.coords)
            gable_edge = abs(a[0] - b[0]) <= GEOMETRY_EPS_MM if roof["ridge_axis"] == "x" else abs(a[1] - b[1]) <= GEOMETRY_EPS_MM
            report.check(base + ".attic.window_gable." + str(window.get("id")), gable_edge,
                         "The initial attic windows must use real gable walls, not imaginary full-height eave walls.")
            sill, height = window.get("sill_mm", 900), window.get("height_mm", 1200)
            clear = min(roof_height_mm(point, footprint, roof) for point in line.coords)
            report.check(base + ".attic.window_headroom." + str(window.get("id")), _integer(sill) and
                         _integer(height) and sill >= 0 and height >= 600 and clear + GEOMETRY_EPS_MM >= sill + height,
                         "The complete vertical gable-window rectangle must fit beneath the roof.")
        cores = [core for core in option.get("cores", []) if core.get("kind") == "stairs"]
        if len(cores) == 1 and cores[0].get("arrival_polygon"):
            core = cores[0]
            arrival = Polygon(core["arrival_polygon"])
            headroom = min(roof_height_mm(point, footprint, roof) for point in arrival.exterior.coords)
            report.check("stairs.attic_arrival_headroom", headroom + GEOMETRY_EPS_MM >= arrival_height,
                         "The whole stair arrival envelope must retain the required roof clearance.",
                         minimum_clear_height_mm=headroom)
            walls = request.get("walls", {"interior_mm": 100, "exterior_mm": 200})
            face = clear_face_polygon(core["polygon"], footprint, walls["interior_mm"], walls["exterior_mm"])
            flight_clearance = _stair_roof_clearance(core, face, footprint, roof)
            report.check("stairs.attic_flight_headroom", flight_clearance + GEOMETRY_EPS_MM >= arrival_height,
                         "Both modeled stair flights and their turn landing must clear the actual roof planes.",
                         minimum_clear_height_mm=flight_clearance)
    return {"attic_gross_area_m2": attic_gross_area,
            "attic_headroom_qualified_area_m2": qualified_clear_area,
            "attic_headroom_qualified_gross_area_m2": occupied_zone.area / MM2_PER_M2 if attic else 0.0,
            "roof_ridge_height_mm": ridge}


def _validate_measurements(option: Mapping, profile: Mapping, report: _Report, plot: Any,
                           footprint: Any, site_data: dict, floors: list, roof_data: dict) -> dict:
    regular_floors = [item for item in floors if item["floor"].get("role") != "attic"]
    garden = unary_union([polygon for _, role, polygon in site_data.get("spaces", []) if role == "garden"])
    rooms = [room for floor in floors for room in floor["rooms"].values()]
    measurements = {
        "plot_area_m2": plot.area / MM2_PER_M2,
        "footprint_area_m2": footprint.area / MM2_PER_M2,
        "regular_floor_area_m2": sum(item["gross_area_m2"] for item in regular_floors),
        "garden_area_m2": garden.area / MM2_PER_M2,
        "bedrooms": sum(room["role"] == "bedroom" for room in rooms),
        "regular_storeys": len(regular_floors),
        "gross_floor_area_m2": sum(item["gross_area_m2"] for item in floors),
        "clear_room_area_m2": sum(room["face"].area for room in rooms if room["role"] != "stair") / MM2_PER_M2,
        **roof_data,
    }
    stated = option.get("metrics", {})
    mandatory = {"plot_area_m2", "footprint_area_m2", "regular_floor_area_m2", "garden_area_m2", "bedrooms", "regular_storeys"}
    for key in sorted(mandatory | (set(stated) & set(measurements))):
        actual = measurements[key]
        tolerance = MEASUREMENT_EPS_M2 if key.endswith("_m2") else 1.01 if key.endswith("_mm") else 0
        report.check("measurements." + key, _is_number(stated.get(key)) and abs(stated[key] - actual) <= tolerance,
                     "Declared measurements must preserve independently measured plot, footprint, floors and roof areas.",
                     expected=actual, declared=stated.get(key))
    measurements["floors"] = [{
        "id": item["floor"].get("id"), "role": item["floor"].get("role"),
        "gross_area_m2": item["gross_area_m2"],
        "clear_room_area_m2": sum(room["face"].area for room in item["rooms"].values() if room["role"] != "stair") / MM2_PER_M2,
        "stair_allocation_area_m2": sum(room["polygon"].area for room in item["rooms"].values() if room["role"] == "stair") / MM2_PER_M2,
        "rooms": [{"id": room_id, "role": room["role"], "allocation_area_m2": room["polygon"].area / MM2_PER_M2,
                   "clear_area_m2": room["face"].area / MM2_PER_M2,
                   "clear_width_mm": _dimensions(room["functional"])[0],
                   "clear_depth_mm": _dimensions(room["functional"])[1],
                   "overall_width_mm": _dimensions(room["face"])[0],
                   "overall_depth_mm": _dimensions(room["face"])[1],
                   "clear_polygon": geometry_polygon(room["face"])}
                  for room_id, room in item["rooms"].items()],
    } for item in floors]
    return measurements
