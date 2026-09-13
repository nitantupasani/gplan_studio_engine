"""Independent geometric and access validation, also used before apply."""

import math
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .models import EPS, polygon, sequence, number, fail
from .geometry import opening_line, lines


def validate_candidate(request, candidate):
    if request.circulation_room_ids:
        from .existing import validate_existing_candidate
        return validate_existing_candidate(request, candidate)
    if not isinstance(candidate, dict):
        fail("invalid_candidate", "candidate must be an object.")
    checks, diagnostics = {}, []

    def check(name, valid, explanation):
        checks[name] = bool(valid)
        if not valid:
            diagnostics.append({"code": name, "message": explanation})

    check("source_matches", candidate.get("source_fingerprint") == request.source_fingerprint and candidate.get("request_fingerprint") == request.fingerprint,
          "Candidate does not belong to this immutable request baseline.")
    adjusted = {}
    for item in sequence(candidate.get("adjusted_rooms"), "candidate.adjusted_rooms", 64):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in adjusted:
            fail("invalid_candidate", "Adjusted rooms need unique stable IDs.")
        adjusted[item["id"]] = polygon(item.get("polygon"), "candidate.room.polygon")
    check("stable_room_ids", set(adjusted) == {r.id for r in request.rooms}, "Candidate must retain exactly the baseline room IDs.")
    if not checks["stable_room_ids"]:
        return {"valid": False, "checks": checks, "diagnostics": diagnostics}
    parts = []
    surfaces = sequence(candidate.get("corridors"), "candidate.corridors", 96)
    for item in surfaces:
        if not isinstance(item, dict):
            fail("invalid_candidate", "Corridor surfaces must be objects.")
        parts.append(polygon(item.get("polygon"), "candidate.corridor.polygon", item.get("holes", [])))
    corridor = unary_union(parts)
    tolerance = max(EPS * 10, request.width * 1e-6)
    area_tolerance = max(EPS * 20, corridor.area * 1e-7)
    removed = unary_union([r.shape.difference(adjusted[r.id]) for r in request.rooms])
    check("wall_free", bool(surfaces) and all(item.get("wall_free") is True and not item.get("walls") for item in surfaces), "Every circulation surface must explicitly remain wall-free.")
    check("rectangular_rooms", all(p.symmetric_difference(box(*p.bounds)).area <= area_tolerance for p in adjusted.values()), "This engine preserves rectangular room boundaries.")
    check("authorized_room_changes", all(r.shape.buffer(tolerance).covers(adjusted[r.id]) for r in request.rooms), "Rooms may only shrink inside their original polygon.")
    check("protected_geometry", all(r.shape.symmetric_difference(adjusted[r.id]).area <= area_tolerance for r in request.rooms if r.locked or r.protected), "Locked and protected room geometry must remain unchanged.")
    check("minimum_dimensions", all(adjusted[r.id].bounds[2] - adjusted[r.id].bounds[0] >= r.min_width - tolerance and adjusted[r.id].bounds[3] - adjusted[r.id].bounds[1] >= r.min_height - tolerance for r in request.rooms), "Actual post-shift room dimensions violate a hard minimum.")
    check("minimum_area", all(adjusted[r.id].area >= r.min_area - area_tolerance for r in request.rooms), "Actual post-shift room area violates a hard minimum.")
    check("maximum_aspect", all(max((p.bounds[2] - p.bounds[0]) / (p.bounds[3] - p.bounds[1]), (p.bounds[3] - p.bounds[1]) / (p.bounds[2] - p.bounds[0])) <= r.max_aspect + tolerance for r in request.rooms for p in [adjusted[r.id]]), "Actual post-shift room aspect ratio exceeds its maximum.")
    occupied = unary_union(list(adjusted.values()) + parts)
    check("fixed_envelope_holes", request.boundary.buffer(tolerance).covers(occupied), "Candidate crosses the fixed boundary or a hole.")
    check("fixed_obstacles", occupied.intersection(request.obstacles).area <= area_tolerance, "Candidate overlaps a fixed obstacle.")
    check("no_overlaps", abs(sum(p.area for p in adjusted.values()) + sum(p.area for p in parts) - occupied.area) <= area_tolerance, "Rooms and corridor surfaces must not overlap or double-count area.")
    check("gap_provenance", removed.symmetric_difference(corridor).area <= area_tolerance, "Corridors must equal authorized before-minus-after room gaps; pre-existing empty or outdoor space is excluded.")
    check("connected_surface", corridor.geom_type == "Polygon" and corridor.is_valid and corridor.area > EPS, "Corridors must form one connected polygon, including through every branch.")
    # Mitred square erosion proves width at orthogonal junctions. Opening the
    # shape again also detects thin dead branches that disappear during erosion.
    radius = request.width / 2 - tolerance
    core = corridor.buffer(-max(radius, request.width * 0.499), join_style=2)
    reconstructed = core.buffer(max(radius, request.width * 0.499), join_style=2)
    check("finite_width", not core.is_empty and core.geom_type == "Polygon" and corridor.difference(reconstructed.buffer(tolerance)).area <= area_tolerance,
          "A corridor branch or junction is narrower than requested; point contacts and disappearing thin branches are not usable routes.")
    mouths = [line for line in lines(corridor.boundary.intersection(request.boundary.exterior)) if line.length >= request.width - tolerance and line.distance(Point(request.entry)) <= tolerance]
    check("entry_access", bool(mouths), "The selected entrance does not meet a corridor mouth of the requested clear width.")
    openings = sequence(candidate.get("openings"), "candidate.openings", 1024)
    opening_ids, served, aligned = set(), set(), True
    for opening in openings:
        if not isinstance(opening, dict) or not isinstance(opening.get("id"), str) or opening["id"] in opening_ids:
            fail("invalid_candidate", "Openings need unique IDs.")
        opening_ids.add(opening["id"])
        if opening.get("orientation") not in ("h", "v") or opening.get("kind") not in ("door", "window", "opening"):
            fail("invalid_candidate", "Opening kind/orientation is invalid.")
        for field in ("x", "y", "width"):
            number(opening.get(field), f"candidate.opening.{field}", EPS if field == "width" else None)
        line = opening_line(opening)
        owners = sequence(opening.get("room_ids", []), "candidate.opening.room_ids", 64)
        if any(not isinstance(owner, str) for owner in owners):
            fail("invalid_candidate", "Opening room IDs must be strings.")
        if opening.get("entrance"):
            aligned = aligned and request.boundary.exterior.buffer(tolerance).covers(line) and corridor.boundary.buffer(tolerance).covers(line)
        elif not owners:
            aligned = False
        for owner in owners:
            if owner not in adjusted or not adjusted[owner].boundary.buffer(tolerance).covers(line):
                aligned = False
            elif opening["kind"] in ("door", "opening") and opening["width"] >= request.door_width - tolerance and corridor.boundary.buffer(tolerance).covers(line):
                served.add(owner)
    check("aligned_openings", aligned, "An opening floats off its referenced room wall or entrance mouth.")
    sources = {o.get("source_id", o["id"]) for o in openings}
    check("preserved_openings", all(o["id"] in sources for o in request.openings), "Every existing opening must be preserved or explicitly reconciled by source ID.")
    check("required_room_access", set(request.required) <= served, "A required room lacks a direct usable doorway into the connected corridor.")
    claimed = candidate.get("coverage", {})
    if not isinstance(claimed, dict):
        fail("invalid_candidate", "candidate.coverage must be an object.")
    claimed_served = sequence(claimed.get("served_room_ids", []), "candidate.coverage.served_room_ids", 64)
    if any(not isinstance(owner, str) for owner in claimed_served):
        fail("invalid_candidate", "Coverage room IDs must be strings.")
    check("coverage_matches", set(claimed_served) == served and claimed.get("count") == len(set(request.required) & served) and claimed.get("total") == len(request.required), "Reported coverage differs from directly accessible room doorways.")
    metrics = candidate.get("metrics", {})
    if not isinstance(metrics, dict):
        fail("invalid_candidate", "candidate.metrics must be an object.")
    check("area_metrics", isinstance(metrics.get("area"), (int, float)) and abs(metrics["area"] - corridor.area) <= area_tolerance and isinstance(metrics.get("total_room_area_taken"), (int, float)) and abs(metrics["total_room_area_taken"] - removed.area) <= area_tolerance, "Reported corridor and contribution areas differ from actual polygons.")
    expected = {r.id: r.shape.area - adjusted[r.id].area for r in request.rooms}
    contributions = sequence(candidate.get("contributions"), "candidate.contributions", 64)
    if any(not isinstance(c, dict) or not isinstance(c.get("room_id"), str) for c in contributions):
        fail("invalid_candidate", "Contribution rows need string room IDs.")
    check("contribution_metrics", len(contributions) == len(expected) and all(isinstance(c, dict) and c.get("room_id") in expected and isinstance(c.get("area_taken"), (int, float)) and math.isfinite(c["area_taken"]) and abs(c["area_taken"] - expected[c["room_id"]]) <= area_tolerance for c in contributions) and len({c.get("room_id") for c in contributions if isinstance(c, dict)}) == len(expected), "Per-room area contributions must match actual before/after polygons exactly.")
    return {"valid": all(checks.values()), "checks": checks, "diagnostics": diagnostics}
