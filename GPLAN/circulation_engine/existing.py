"""Reuse explicitly designated public circulation and its saved openings.

This is an annotation/validation strategy, never an allocation or carving mode.
The clear surface subtracts existing wall material from the designated footprint;
all source room polygons and openings remain unchanged.
"""

from copy import deepcopy

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from .geometry import lines, opening_line
from .models import EPS, CirculationError, digest, fail, polygon, ring, sequence, serialize_polygon
from .registry import ALGORITHMS


def _parallel_overlap(first, second, tolerance=EPS):
    a, b = first.bounds, second.bounds
    vertical = abs(a[0] - a[2]) <= tolerance
    if vertical:
        if abs(b[0] - b[2]) > tolerance or abs(a[0] - b[0]) > tolerance:
            return None
        low, high = max(a[1], b[1]), min(a[3], b[3])
        return LineString([(a[0], low), (a[0], high)]) if high - low > tolerance else None
    if abs(b[1] - b[3]) > tolerance or abs(a[1] - b[1]) > tolerance:
        return None
    low, high = max(a[0], b[0]), min(a[2], b[2])
    return LineString([(low, a[1]), (high, a[1])]) if high - low > tolerance else None


def _square_boundary_band(shape, radius):
    """Exact square expansion of an orthogonal polygon's boundary.

    GEOS offset buffering can simplify short steps relative to the buffer
    radius, introducing diagonal edges during reconstruction. Explicit edge
    rectangles retain authored steps without changing the width tolerance.
    """
    bands = []
    for boundary in [shape.exterior, *shape.interiors]:
        coordinates = list(boundary.coords)
        for first, second in zip(coordinates, coordinates[1:]):
            bands.append(box(min(first[0], second[0]) - radius, min(first[1], second[1]) - radius,
                             max(first[0], second[0]) + radius, max(first[1], second[1]) + radius))
    return unary_union(bands)


def width_is_valid(shape, width):
    tolerance = max(EPS * 10, width * 1e-6)
    radius = max(width / 2 - tolerance, width * 0.499)
    core = shape.difference(_square_boundary_band(shape, radius))
    if core.is_empty or core.geom_type != "Polygon":
        return False
    reconstructed = unary_union([core, _square_boundary_band(core, radius)])
    return shape.difference(reconstructed.buffer(tolerance)).area <= max(EPS * 20, shape.area * 1e-7)


def _clear_width(shape):
    x0, y0, x1, y1 = shape.bounds
    low, high = 0.0, min(x1 - x0, y1 - y0)
    for _ in range(28):
        middle = (low + high) / 2
        if width_is_valid(shape, middle):
            low = middle
        else:
            high = middle
    return low


def _portal_reaches_clear(opening, nominal, clear, required_width, max_inset):
    """Check the saved wall-centre portal against the parallel clear room face."""
    portal = opening_line(opening)
    a = portal.bounds
    for face in lines(clear.boundary):
        b = face.bounds
        if opening["orientation"] == "v":
            if abs(b[0] - b[2]) > EPS or abs(a[0] - b[0]) > max_inset + EPS * 10:
                continue
            overlap = min(a[3], b[3]) - max(a[1], b[1])
            approach = box(min(a[0], b[0]), max(a[1], b[1]), max(a[0], b[0]), min(a[3], b[3]))
        else:
            if abs(b[1] - b[3]) > EPS or abs(a[1] - b[1]) > max_inset + EPS * 10:
                continue
            overlap = min(a[2], b[2]) - max(a[0], b[0])
            approach = box(max(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]), max(a[1], b[1]))
        if overlap >= required_width - EPS * 10 and (approach.area <= EPS or nominal.buffer(EPS).covers(approach)):
            return True
    return False


def existing_geometry(request):
    marked = set(request.circulation_room_ids)
    rooms = {r.id: r for r in request.rooms}
    nominal = unary_union([rooms[rid].shape for rid in marked])
    if nominal.geom_type != "Polygon" or not nominal.is_valid:
        fail("existing_circulation_disconnected", "The designated existing landing/circulation rooms do not form one connected footprint. Select the landing serving this floor.")
    for rid in marked:
        coordinates = list(rooms[rid].shape.exterior.coords)
        if any(abs(a[0] - b[0]) > EPS and abs(a[1] - b[1]) > EPS for a, b in zip(coordinates, coordinates[1:])):
            fail("unsupported_existing_circulation", "Existing circulation reuse currently supports orthogonal public landing/hall polygons.", room_id=rid)
    # A shared boundary between two marked rooms still owns its original wall.
    # Only a saved opening covering that complete separator makes union safe.
    for index, rid in enumerate(sorted(marked)):
        for other in sorted(marked)[index + 1:]:
            shared = rooms[rid].shape.boundary.intersection(rooms[other].shape.boundary)
            if shared.length > EPS:
                open_parts = [opening_line(o) for o in request.openings if o["kind"] == "opening" and set(o["room_ids"]) == {rid, other}]
                if not open_parts or shared.difference(unary_union(open_parts).buffer(EPS)).length > EPS * 10:
                    fail("unsupported_existing_circulation_join", "These circulation rooms retain an internal wall or door. Reuse one connected landing, or an explicitly fully open shared separator; this mode does not remove existing walls.", room_ids=[rid, other])
    interior, exterior = request.wall_thickness
    other_edges = [edge for r in request.rooms if r.id not in marked for edge in lines(r.shape.boundary)]
    wall_strips = []
    for edge in lines(nominal.boundary):
        overlaps = [part for other in other_edges if (part := _parallel_overlap(edge, other)) is not None]
        shared = unary_union(overlaps)
        outside = edge.difference(shared)
        if not shared.is_empty and interior > 0:
            wall_strips.append(shared.buffer(interior / 2, cap_style=2, join_style=2))
        if not outside.is_empty and exterior > 0:
            # Existing plan envelope is the exterior wall's outer face.
            wall_strips.append(outside.buffer(exterior, cap_style=2, join_style=2))
    clear = nominal.difference(unary_union(wall_strips))
    if clear.is_empty or clear.geom_type != "Polygon" or not clear.is_valid:
        fail("existing_circulation_clearance", "Existing wall material leaves no connected clear landing/circulation floor.")
    if not width_is_valid(clear, request.width):
        fail("existing_circulation_width", "The existing landing/circulation is narrower than the requested clear width, including at its branches. Choose a smaller width or edit the existing landing first; no rooms were changed.", requested_width=request.width, available_clear_width=_clear_width(clear))
    saved = {o["id"]: o for o in request.openings}
    # Validate every preserved source opening against its actual owner wall.
    for opening in request.openings:
        owners = opening["room_ids"]
        if not owners or len(set(owners)) != len(owners):
            fail("existing_circulation_opening", "Existing circulation needs unambiguous saved opening room IDs.", opening_id=opening["id"])
        if any(not rooms[owner].shape.boundary.buffer(EPS * 10).covers(opening_line(opening)) for owner in owners):
            fail("existing_circulation_opening", "A saved opening is not aligned with every referenced original room wall; repair that opening before reusing circulation.", opening_id=opening["id"])
    entry = saved[request.entry_opening_id]
    entry_owners = set(entry["room_ids"])
    if entry["kind"] not in ("door", "opening") or entry["width"] < request.door_width - EPS or not (entry_owners & marked):
        fail("existing_circulation_entry", "The selected saved entry must be a usable doorway/opening into a designated landing.", opening_id=entry["id"])
    entry_line = opening_line(entry)
    exterior_entry = entry["entrance"] and request.boundary.exterior.buffer(EPS * 10).covers(entry_line) and entry_owners <= marked
    stair_id = request.raw["entry"].get("stair_room_id")
    stair_entry = (isinstance(stair_id, str) and stair_id in rooms and stair_id not in marked
                   and entry_owners - marked == {stair_id} and (rooms[stair_id].locked or rooms[stair_id].protected))
    if not exterior_entry and not stair_entry:
        fail("existing_circulation_entry", "Choose a saved exterior entrance into the hall, or explicitly identify the protected stair room owning the stair-to-landing opening with entry.stair_room_id.", opening_id=entry["id"])
    max_inset = max(interior / 2, exterior)
    if not _portal_reaches_clear(entry, nominal, clear, request.door_width, max_inset):
        fail("existing_circulation_entry", "The saved entry does not reach the clear landing floor at the required doorway width after existing wall thickness is accounted for.", opening_id=entry["id"])
    served = set()
    for opening in request.openings:
        owners = set(opening["room_ids"])
        destinations = owners - marked
        if (opening["kind"] in ("door", "opening") and opening["width"] >= request.door_width - EPS
                and owners & marked and len(destinations) == 1
                and nominal.boundary.buffer(EPS * 10).covers(opening_line(opening))
                and _portal_reaches_clear(opening, nominal, clear, request.door_width, max_inset)):
            served.update(destinations)
    if not set(request.required) <= served:
        fail("existing_circulation_access", "Some selected rooms do not have a usable saved doorway directly into this landing/circulation. Select the rooms it serves or repair their access; private-room shortcuts are not counted.", room_ids=sorted(set(request.required) - served))
    return nominal, clear, entry, sorted(served), "exterior" if exterior_entry else "stair"


def validate_existing_candidate(request, candidate):
    checks, diagnostics = {}, []

    def check(name, valid, message):
        checks[name] = bool(valid)
        if not valid:
            diagnostics.append({"code": name, "message": message})

    if not isinstance(candidate, dict):
        fail("invalid_candidate", "candidate must be an object.")
    check("source_matches", candidate.get("source_fingerprint") == request.source_fingerprint and candidate.get("request_fingerprint") == request.fingerprint, "Existing circulation candidate is stale or belongs to a different baseline.")
    nominal, clear, entry, served, entry_kind = existing_geometry(request)
    reused = candidate.get("reused_room_ids")
    check("designated_reuse", reused == list(request.circulation_room_ids), "Only explicitly designated existing circulation rooms may be reused.")
    adjusted = {}
    for item in sequence(candidate.get("adjusted_rooms"), "candidate.adjusted_rooms", 64):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in adjusted:
            fail("invalid_candidate", "Adjusted rooms need unique stable IDs.")
        adjusted[item["id"]] = polygon(item.get("polygon"), "candidate.room.polygon")
    check("stable_room_ids", set(adjusted) == {r.id for r in request.rooms}, "All original rooms, including the landing and fixed stair, must retain their IDs.")
    check("unchanged_rooms", all(r.id in adjusted and r.shape.symmetric_difference(adjusted[r.id]).area <= EPS * 20 for r in request.rooms), "Existing circulation reuse cannot shrink, expand, move or delete any room.")
    surfaces = sequence(candidate.get("corridors"), "candidate.corridors", 1)
    if len(surfaces) != 1 or not isinstance(surfaces[0], dict):
        fail("invalid_candidate", "Existing circulation must contain exactly one clear floor surface.")
    surface = surfaces[0]
    actual = polygon(surface.get("polygon"), "candidate.corridor.polygon", surface.get("holes", []))
    source = polygon(surface.get("source_polygon"), "candidate.corridor.source_polygon", surface.get("source_holes", []))
    check("existing_source_provenance", source.symmetric_difference(nominal).area <= EPS * 20, "The source footprint must equal the explicitly designated existing circulation rooms.")
    check("existing_clear_geometry", actual.symmetric_difference(clear).area <= EPS * 20, "The reused surface must equal the existing clear floor after the supplied wall thickness is applied.")
    check("wall_free", surface.get("wall_free") is True and not surface.get("walls"), "Reuse adds a wall-free floor annotation and no new walls.")
    check("finite_width", width_is_valid(actual, request.width), "Every existing circulation branch must preserve the requested actual clear width.")
    check("fixed_envelope_obstacles", request.boundary.buffer(EPS).covers(actual) and actual.intersection(request.obstacles).area <= EPS, "Existing circulation must remain in its fixed envelope and outside obstacles.")
    check("preserved_openings", candidate.get("openings") == list(request.openings), "Reusing existing circulation must preserve every saved opening without moving, adding, deleting or widening it.")
    coverage = candidate.get("coverage")
    if not isinstance(coverage, dict):
        fail("invalid_candidate", "candidate.coverage must be an object.")
    check("required_room_access", set(request.required) <= set(served), "A required room lacks direct saved doorway access to the existing circulation.")
    check("coverage_matches", coverage.get("served_room_ids") == served and coverage.get("required_room_ids") == list(request.required) and coverage.get("count") == len(set(request.required) & set(served)) and coverage.get("total") == len(request.required), "Existing circulation coverage must reflect direct saved doorway access.")
    metrics = candidate.get("metrics")
    if not isinstance(metrics, dict):
        fail("invalid_candidate", "candidate.metrics must be an object.")
    check("area_metrics", isinstance(metrics.get("area"), (int, float)) and abs(metrics["area"] - clear.area) <= EPS * 20 and metrics.get("total_room_area_taken") == 0, "Existing corridor area is its actual clear floor; total room area taken must remain zero.")
    expected_contributions = [{"room_id": r.id, "before_area": r.shape.area, "after_area": r.shape.area, "area_taken": 0.0, "percent_taken": 0.0} for r in request.rooms]
    check("zero_contributions", candidate.get("contributions") == expected_contributions, "Every unchanged room must report its actual original area and zero contribution.")
    return {"valid": all(checks.values()), "checks": checks, "diagnostics": diagnostics}


def generate_existing(request):
    result = {"schema_version": "1.0", "plan_id": request.plan_id, "source_fingerprint": request.source_fingerprint,
              "request_fingerprint": request.fingerprint, "units": request.units, "status": "infeasible", "candidates": [], "diagnostics": [],
              "search": {"complete": True, "attempted": 1, "deduplicated": 0, "deterministic": True}}
    try:
        nominal, clear, entry, served, entry_kind = existing_geometry(request)
        scope = "all" if set(request.required) == {r.id for r in request.rooms if not r.locked and r.id not in request.circulation_room_ids} else "selected"
        surface = {"id": "existing-circulation-surface-1", **serialize_polygon(clear), "wall_free": True,
                   "source_polygon": ring(nominal), "source_holes": serialize_polygon(nominal)["holes"],
                   "provenance": [{"room_id": rid, "kind": "existing_circulation", "before_area": next(r.shape.area for r in request.rooms if r.id == rid),
                                    "after_area": next(r.shape.area for r in request.rooms if r.id == rid)} for rid in request.circulation_room_ids]}
        candidate = {"id": "", "schema_version": "1.0", "plan_id": request.plan_id, "source_fingerprint": request.source_fingerprint,
                     "request_fingerprint": request.fingerprint, "units": request.units, "algorithm": deepcopy(ALGORITHMS["existing"]),
                     "label": "Existing landing/circulation — " + ("all rooms" if scope == "all" else "selected rooms"),
                     "reused_room_ids": list(request.circulation_room_ids), "contribution_policy": request.policy,
                     "coverage": {"scope": scope, "required_room_ids": list(request.required), "served_room_ids": served,
                                  "count": len(set(request.required) & set(served)), "total": len(request.required)},
                     "adjusted_rooms": [{"id": r.id, "name": r.name, "polygon": ring(r.shape)} for r in request.rooms],
                     "corridors": [surface], "centerlines": [], "openings": deepcopy(list(request.openings)),
                     "entry": {"point": list(request.entry), "opening_id": entry["id"], "kind": entry_kind, "mouth": [list(p) for p in opening_line(entry).coords]},
                     "metrics": {"width": request.width, "clear_width": _clear_width(clear), "length": 0.0,
                                 "length_model": "not_measured_existing_surface", "centerline_length": 0.0,
                                 "area": clear.area, "clear_area": clear.area, "source_area": nominal.area,
                                 "total_room_area_taken": 0.0, "changed_room_ids": [], "protected_room_ids": [r.id for r in request.rooms if r.locked or r.protected]},
                     "contributions": [{"room_id": r.id, "before_area": r.shape.area, "after_area": r.shape.area, "area_taken": 0.0, "percent_taken": 0.0} for r in request.rooms],
                     "diagnostics": ["Existing public landing/circulation is reused through its saved access openings; every room and opening remains unchanged.",
                                     "The highlighted surface is the actual clear floor. Existing walls keep their original position; no corridor walls or new doors are created.",
                                     "No route optimization or walking-length measurement is claimed; room contribution policies take zero area in this reuse mode.",
                                     "Original room dimensions and any pre-existing dimensional-rule exceptions are inherited unchanged; reuse does not resize or certify those rooms."]}
        candidate["validation"] = validate_existing_candidate(request, candidate)
        if not candidate["validation"]["valid"]:
            fail("existing_circulation_validation", "The existing circulation candidate fails independent validation.", checks=candidate["validation"]["diagnostics"])
        candidate["geometry_fingerprint"] = digest({"rooms": candidate["adjusted_rooms"], "surfaces": candidate["corridors"], "openings": candidate["openings"]})
        candidate["id"] = "circulation-" + digest({"source": request.fingerprint, "mode": "existing", "geometry": candidate["geometry_fingerprint"]})[:20]
        result.update(status="complete", candidates=[candidate])
    except CirculationError as error:
        result["diagnostics"].append({**error.to_dict(), "mode": "existing"})
    return result
