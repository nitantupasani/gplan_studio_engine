"""Explicit authorized gap surfaces and room-owned access openings."""

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .models import EPS, fail, serialize_polygon


def lines(shape):
    """Return maximal straight runs; overlay vertices must not split a doorway."""
    if shape.is_empty:
        return []
    raw = []

    def collect(part):
        if part.geom_type == "LineString":
            raw.extend(zip(list(part.coords)[:-1], list(part.coords)[1:]))
        elif hasattr(part, "geoms"):
            for item in part.geoms:
                collect(item)

    collect(shape)
    buckets = {}
    for start, end in raw:
        if abs(start[0] - end[0]) <= EPS:
            key, interval = ("v", round(start[0], 8)), sorted((start[1], end[1]))
        elif abs(start[1] - end[1]) <= EPS:
            key, interval = ("h", round(start[1], 8)), sorted((start[0], end[0]))
        else:
            continue
        buckets.setdefault(key, []).append(interval)
    result = []
    for (orientation, coordinate), intervals in sorted(buckets.items()):
        merged = []
        for low, high in sorted(intervals):
            if merged and low <= merged[-1][1] + EPS:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        result.extend(LineString([(coordinate, low), (coordinate, high)] if orientation == "v" else [(low, coordinate), (high, coordinate)]) for low, high in merged if high - low > EPS)
    return result


def opening_line(opening):
    x, y, half = opening["x"], opening["y"], opening["width"] / 2
    return LineString([(x - half, y), (x + half, y)]) if opening["orientation"] == "h" else LineString([(x, y - half), (x, y + half)])


def side_for_opening(shape, opening):
    x0, y0, x1, y1 = shape.bounds
    x, y = opening["x"], opening["y"]
    if opening["orientation"] == "h" and x0 - EPS <= x <= x1 + EPS:
        if abs(y - y0) <= EPS:
            return "top"
        if abs(y - y1) <= EPS:
            return "bottom"
    if opening["orientation"] == "v" and y0 - EPS <= y <= y1 + EPS:
        if abs(x - x0) <= EPS:
            return "left"
        if abs(x - x1) <= EPS:
            return "right"
    return None


def moved_opening(shape, old, side):
    x0, y0, x1, y1 = shape.bounds
    result = dict(old)
    margin = old["width"] / 2
    if side in ("top", "bottom"):
        if x1 - x0 < old["width"] - EPS:
            fail("infeasible_opening", "An existing opening no longer fits its room wall.", opening_id=old["id"])
        result["x"] = max(x0 + margin, min(x1 - margin, old["x"]))
        result["y"] = y0 if side == "top" else y1
    else:
        if y1 - y0 < old["width"] - EPS:
            fail("infeasible_opening", "An existing opening no longer fits its room wall.", opening_id=old["id"])
        result["y"] = max(y0 + margin, min(y1 - margin, old["y"]))
        result["x"] = x0 if side == "left" else x1
    result["moved"] = abs(result["x"] - old["x"]) > EPS or abs(result["y"] - old["y"]) > EPS
    return result


def from_contact(contact, oid, room_ids, width, kind="door", entrance=False):
    start, end = contact.coords[0], contact.coords[-1]
    mid = contact.interpolate(0.5, normalized=True)
    return {"id": oid, "kind": kind, "orientation": "h" if abs(start[1] - end[1]) <= EPS else "v",
            "x": float(mid.x), "y": float(mid.y), "width": width, "entrance": entrance,
            "room_ids": room_ids, "generated": True}


def create_geometry(request, adjusted, selected, groups, offsets, provenance):
    removed = {room.id: room.shape.difference(adjusted[room.id]) for room in request.rooms}
    corridor = unary_union([part for part in removed.values() if part.area > EPS])
    if corridor.is_empty or corridor.geom_type != "Polygon":
        fail("infeasible_connectivity", "Boundary shifts do not produce one connected corridor surface.")
    exterior_contacts = lines(corridor.boundary.intersection(request.boundary.exterior))
    mouths = [line for line in exterior_contacts if line.length >= request.width - EPS and line.distance(Point(request.entry)) <= EPS]
    if not mouths:
        fail("infeasible_entry", "The chosen entrance does not have the requested clear corridor width at the fixed envelope.")
    mouth = min(mouths, key=lambda line: (line.distance(Point(request.entry)), list(line.coords)))
    opening_results, diagnostics = [], []
    room_map = {room.id: room for room in request.rooms}
    for opening in request.openings:
        if opening["entrance"]:
            if opening["kind"] == "window":
                fail("invalid_input", "An entrance cannot be a window.", opening_id=opening["id"])
            if not request.replace_entry:
                if corridor.boundary.buffer(EPS).intersection(opening_line(opening)).length < opening["width"] - EPS:
                    fail("infeasible_entry", "The saved entrance does not lead directly into this corridor. Explicitly choose Replace entrance, or choose the entrance's current shared-wall termination.", opening_id=opening["id"])
                preserved = dict(opening, room_ids=[])
                opening_results.append(preserved)
            else:
                replacement = from_contact(mouth, opening["id"], [], min(opening["width"], request.width), opening["kind"], True)
                replacement.update(source_id=opening["id"], moved=True)
                opening_results.append(replacement)
                diagnostics.append(f"Entrance {opening['id']} moved to the explicitly selected corridor mouth.")
            continue
        owners = opening["room_ids"] or [room.id for room in request.rooms if side_for_opening(room.shape, opening)]
        if not owners:
            fail("invalid_input", "An opening does not lie on a baseline room wall.", opening_id=opening["id"])
        variants = []
        for owner in owners:
            side = side_for_opening(room_map[owner].shape, opening)
            if side is None or room_map[owner].shape.boundary.buffer(EPS).intersection(opening_line(opening)).length < opening["width"] - EPS:
                fail("invalid_input", "An existing opening must fit the baseline wall of every referenced room.", opening_id=opening["id"], room_id=owner)
            proposed = moved_opening(adjusted[owner], opening, side)
            proposed["room_ids"] = [owner]
            same = next((other for other in variants if abs(other["x"] - proposed["x"]) <= EPS and abs(other["y"] - proposed["y"]) <= EPS), None)
            if same is not None:
                same["room_ids"].append(owner)
            else:
                variants.append(proposed)
        if opening["kind"] == "window":
            if len(variants) != 1 or any(corridor.boundary.intersection(opening_line(o)).length > EPS for o in variants):
                fail("infeasible_opening", "A window would open onto newly created internal circulation. Protect its room or choose another route.", opening_id=opening["id"])
        for index, variant in enumerate(variants):
            variant["source_id"] = opening["id"]
            variant["id"] = opening["id"] if index == 0 else f"{opening['id']}-circulation-{index + 1}"
            opening_results.append(variant)
    # Access is counted only across a direct positive-length room/corridor wall.
    for room in request.rooms:
        contacts = [line for line in lines(adjusted[room.id].boundary.intersection(corridor.boundary)) if line.length >= request.door_width - EPS]
        if not contacts:
            if room.id in request.required:
                fail("infeasible_access", "A required room has no wall contact long enough for a usable corridor doorway.", room_id=room.id)
            continue
        existing = any(room.id in opening["room_ids"] and opening["kind"] in ("door", "opening")
                       and corridor.boundary.buffer(EPS).intersection(opening_line(opening)).length >= opening["width"] - EPS
                       and opening["width"] >= request.door_width - EPS for opening in opening_results)
        if not existing:
            if room.id not in request.required:
                continue
            if room.locked:
                fail("infeasible_fixed_access", "A locked room needs a preserved existing doorway into the corridor; circulation cannot add a new opening to a fixed core.", room_id=room.id)
            # Reuse a moved door that is slightly narrower than the requested
            # access, when widening it fits the same contact without conflicts.
            resized = False
            for old in opening_results:
                if room.id not in old["room_ids"] or old["kind"] not in ("door", "opening") or old["width"] >= request.door_width - EPS:
                    continue
                for contact in contacts:
                    if contact.distance(Point(old["x"], old["y"])) > EPS:
                        continue
                    proposal = from_contact(contact, old["id"], old["room_ids"], request.door_width, old["kind"])
                    x0, y0, x1, y1 = contact.bounds
                    if old["orientation"] == "h":
                        proposal["x"] = max(x0 + request.door_width / 2, min(x1 - request.door_width / 2, old["x"]))
                    else:
                        proposal["y"] = max(y0 + request.door_width / 2, min(y1 - request.door_width / 2, old["y"]))
                    if any(other is not old and opening_line(other).intersection(opening_line(proposal)).length > EPS for other in opening_results):
                        continue
                    old.update(x=proposal["x"], y=proposal["y"], width=request.door_width, resized=True)
                    diagnostics.append(f"Room {room.id} access {old['id']} widened to the requested doorway width.")
                    resized = True
                    break
                if resized:
                    break
            if resized:
                continue
            contact = max(contacts, key=lambda line: (line.length, tuple(line.coords)))
            generated = from_contact(contact, f"circulation-access-{room.id}", [room.id], request.door_width)
            for existing_opening in opening_results:
                if opening_line(existing_opening).intersection(opening_line(generated)).length > EPS:
                    fail("infeasible_opening", "A required corridor access conflicts with an existing opening; select another entrance or revise the opening first.", room_id=room.id, opening_id=existing_opening["id"])
            opening_results.append(generated)
    surface = {"id": "circulation-surface-1", **serialize_polygon(corridor), "wall_free": True,
               "provenance": [{"room_id": room.id, "sides": sorted({side for _, side in provenance[room.id]}),
                               "wall_group_ids": sorted({gid for gid, _ in provenance[room.id]}),
                               "before_area": room.shape.area, "after_area": adjusted[room.id].area}
                              for room in request.rooms if removed[room.id].area > EPS]}
    centerlines = []
    shifted_coordinates = {gid: groups[gid].coordinate + request.width / 2 - offsets[gid] for gid in selected}
    for gid in sorted(selected):
        group = groups[gid]
        coordinate = shifted_coordinates[gid]
        start, end = group.start, group.end
        for other_id in selected - {gid}:
            other = groups[other_id]
            if other.orientation != group.orientation and group.line.distance(other.line) <= EPS:
                # A T endpoint must extend to the shifted cross-run centreline;
                # retaining its original endpoint can leave a visual break.
                junction_coordinate = shifted_coordinates[other_id]
                start, end = min(start, junction_coordinate), max(end, junction_coordinate)
        points = [[coordinate, start], [coordinate, end]] if group.orientation == "v" else [[start, coordinate], [end, coordinate]]
        if not corridor.buffer(EPS).covers(LineString(points)):
            fail("infeasible_centerline", "A shifted route centreline cannot reach its junction inside the authorized corridor surface.", wall_group=gid)
        centerlines.append({"id": gid, "points": points, "room_ids": sorted(group.rooms), "width": request.width,
                            "reference_length": group.length, "reference_wall_coordinate": group.coordinate,
                            "negative_offset": offsets[gid]})
    return corridor, surface, centerlines, opening_results, diagnostics, [[float(x), float(y)] for x, y in mouth.coords]
