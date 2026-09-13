"""Strict versioned JSON boundary; model units and coordinates are preserved."""

from dataclasses import dataclass
import hashlib
import json
import math

from shapely.geometry import Polygon, Point, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

SCHEMA_VERSION = "1.0"
EPS = 1e-7
MAX_ROOMS = 64
MAX_VERTICES = 256
MAX_OPENINGS = 512
MAX_BODY_BYTES = 1_000_000
POLICIES = ("area", "surplus", "equal", "protected")
MODES = ("spanning", "compact", "shortest", "existing")


class CirculationError(ValueError):
    def __init__(self, code, message, details=None, http_status=422):
        super().__init__(message)
        self.code, self.message = code, message
        self.details, self.http_status = details or {}, http_status

    def to_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}


def fail(code, message, **details):
    raise CirculationError(code, message, details)


def number(value, path, minimum=None, maximum=1_000_000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail("invalid_input", f"{path} must be a finite number.")
    value = float(value)
    if abs(value) > maximum or (minimum is not None and value < minimum):
        fail("invalid_input", f"{path} is outside the supported range.", minimum=minimum, maximum=maximum)
    return value


def identifier(value, path):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        fail("invalid_input", f"{path} must be a nonempty string of at most 160 characters.")
    return value


def boolean(value, path):
    if not isinstance(value, bool):
        fail("invalid_input", f"{path} must be a boolean.")
    return value


def sequence(value, path, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        fail("invalid_input", f"{path} must be an array of at most {maximum} items.")
    return value


def point(value, path):
    if not isinstance(value, list) or len(value) != 2:
        fail("invalid_input", f"{path} must be [x, y].")
    return tuple(number(v, path) for v in value)


def polygon(value, path, holes=None):
    coords = [point(p, path) for p in sequence(value, path, MAX_VERTICES)]
    if len(coords) < 3:
        fail("invalid_input", f"{path} needs at least three vertices.")
    hole_coords = [[point(p, path + '.holes') for p in sequence(h, path + '.holes', MAX_VERTICES)]
                   for h in sequence(holes or [], path + '.holes', 32)]
    if any(len(h) < 3 for h in hole_coords):
        fail("invalid_input", f"{path} contains a hole with fewer than three vertices.")
    result = Polygon(coords, hole_coords)
    if not result.is_valid or result.is_empty or result.area <= EPS:
        fail("invalid_input", f"{path} must be a valid polygon with positive area.")
    return result


def ring(poly):
    poly = orient(poly, sign=1.0)
    return [[round(x, 9), round(y, 9)] for x, y in list(poly.exterior.coords)[:-1]]


def serialize_polygon(poly):
    poly = orient(poly, sign=1.0)
    return {"polygon": ring(poly), "holes": [[[round(x, 9), round(y, 9)] for x, y in list(h.coords)[:-1]]
                                             for h in poly.interiors]}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    shape: Polygon
    min_width: float
    min_height: float
    min_area: float
    max_aspect: float
    locked: bool
    protected: bool

    @property
    def bounds(self):
        return self.shape.bounds


@dataclass(frozen=True)
class Request:
    raw: dict
    plan_id: str
    source_fingerprint: str
    fingerprint: str
    units: str
    boundary: Polygon
    rooms: tuple
    obstacles: object
    entry: tuple
    replace_entry: bool
    required: tuple
    width: float
    door_width: float
    modes: tuple
    policy: str
    openings: tuple
    candidate_limit: int
    circulation_room_ids: tuple = ()
    entry_opening_id: str = None
    wall_thickness: tuple = None


def parse_request(payload):
    if not isinstance(payload, dict):
        fail("invalid_input", "Request must be a JSON object.")
    try:
        raw = json.loads(json.dumps(payload, allow_nan=False))
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("invalid_input", "Request must contain only finite JSON values.")
    if len(json.dumps(raw).encode()) > MAX_BODY_BYTES:
        fail("invalid_input", "Circulation request exceeds the 1 MB limit.")
    if raw.get("schema_version") != SCHEMA_VERSION:
        fail("invalid_schema", "Use circulation schema_version '1.0'.")
    units = raw.get("units")
    if units not in ("ft", "m"):
        fail("invalid_input", "units must be 'ft' or 'm'; the engine performs no implicit conversion.")
    plan_id = identifier(raw.get("plan_id"), "plan_id")
    source = identifier(raw.get("source_fingerprint"), "source_fingerprint")
    boundary = polygon(raw.get("boundary"), "boundary", raw.get("holes", []))
    reused = sequence(raw.get("circulation_room_ids", []), "circulation_room_ids", MAX_ROOMS)
    if any(not isinstance(room_id, str) or not room_id for room_id in reused) or len(set(reused)) != len(reused):
        fail("invalid_input", "circulation_room_ids must contain unique stable room IDs explicitly designated as public circulation.")
    rooms = []
    for index, item in enumerate(sequence(raw.get("rooms"), "rooms", MAX_ROOMS)):
        if not isinstance(item, dict):
            fail("invalid_input", f"rooms[{index}] must be an object.")
        room_id = identifier(item.get("id"), f"rooms[{index}].id")
        shape = polygon(item.get("polygon"), f"room {room_id}.polygon")
        if not reused and shape.symmetric_difference(box(*shape.bounds)).area > EPS:
            fail("unsupported_geometry", "Boundary-shift circulation supports axis-aligned rectangular rooms. Restore a rectangular baseline or exclude the edited plan.", room_id=room_id)
        if not boundary.buffer(EPS).covers(shape):
            fail("invalid_input", "Room lies outside the boundary or overlaps a boundary hole.", room_id=room_id)
        default_min = 1.0 if units == "ft" else 0.3048
        room = Room(room_id, identifier(item.get("name", room_id), "room.name"), shape,
                    number(item.get("min_width", default_min), "room.min_width", EPS),
                    number(item.get("min_height", default_min), "room.min_height", EPS),
                    number(item.get("min_area", 0), "room.min_area", 0, 1e12),
                    number(item.get("max_aspect", 1000), "room.max_aspect", 1, 1000),
                    boolean(item.get("locked", False), "room.locked"),
                    boolean(item.get("protected", False), "room.protected"))
        if any(r.id == room_id for r in rooms):
            fail("invalid_input", "Room IDs must be unique.", room_id=room_id)
        for other in rooms:
            overlap = shape.intersection(other.shape)
            if overlap.area > EPS:
                x0, y0, x1, y1 = overlap.bounds
                overlap_width, overlap_height = x1 - x0, y1 - y0
                fail("invalid_input", f"{room.name} overlaps {other.name} "
                     f"({overlap_width:.6g} {units} × {overlap_height:.6g} {units}). "
                     "Move their shared wall before checking circulation.",
                     room_ids=[room_id, other.id], room_names=[room.name, other.name], units=units,
                     overlap_area=overlap.area, overlap_width=overlap_width, overlap_height=overlap_height)
        rooms.append(room)
    if any(room_id not in {r.id for r in rooms} for room_id in reused):
        fail("invalid_input", "circulation_room_ids references a missing room.")
    if len(rooms) < 2:
        fail("unsupported_geometry", "At least two adjacent rectangular rooms are needed to create circulation without routing through a room.")
    obstacles = unary_union([polygon(p, "obstacles") for p in sequence(raw.get("obstacles", []), "obstacles", 64)])
    if any(r.shape.intersection(obstacles).area > EPS for r in rooms):
        fail("invalid_input", "Rooms must exclude fixed obstacles; pass fixed cores as locked rooms or actual unoccupied obstacles.")
    entry = raw.get("entry")
    if not isinstance(entry, dict):
        fail("invalid_input", "entry must include a point [x, y].")
    entry_opening_id = identifier(entry["opening_id"], "entry.opening_id") if "opening_id" in entry else None
    if entry_opening_id and not reused:
        fail("unsupported_entry", "An internal saved opening is an entry only when explicitly reusing existing circulation rooms.")
    entry_point = point(entry["point"], "entry.point") if "point" in entry else None
    if entry_point is None and not (reused and entry_opening_id):
        fail("invalid_input", "entry needs a point or, for existing circulation, an opening_id.")
    if not reused and boundary.exterior.distance(Point(entry_point)) > EPS:
        fail("unsupported_entry", "Choose an entrance where a shared room wall meets the exterior boundary; routing through a room is unsupported.")
    required = sequence(raw.get("required_room_ids", [r.id for r in rooms if not r.locked and r.id not in reused]), "required_room_ids", MAX_ROOMS)
    if not required or any(not isinstance(v, str) or v not in {r.id for r in rooms} for v in required) or len(set(required)) != len(required):
        fail("invalid_input", "required_room_ids must be a nonempty array of unique existing room IDs.")
    if set(required) & set(reused):
        fail("invalid_input", "Existing circulation rooms are route surfaces, not required destination rooms; exclude them from required_room_ids.")
    width = number(raw.get("width"), "width", EPS, 100)
    door_width = number(raw.get("door_width", min(width, 2.5 if units == "ft" else 0.762)), "door_width", EPS, 30)
    modes = sequence(raw.get("modes", ["existing"] if reused else ["spanning", "compact"]), "modes", 4)
    if not modes or any(m not in MODES for m in modes) or len(set(modes)) != len(modes):
        fail("invalid_input", "modes must contain unique registered mode IDs: spanning, compact, shortest, existing.")
    if (reused and modes != ["existing"]) or (not reused and "existing" in modes):
        fail("unsupported_strategy", "Use modes ['existing'] with explicitly designated circulation_room_ids. Existing circulation is never silently carved or relabelled as a shortest route.")
    wall_thickness = None
    if reused:
        walls = raw.get("wall_thickness")
        if not isinstance(walls, dict):
            fail("invalid_input", "Existing circulation needs wall_thickness {interior, exterior} in model units to validate actual clear width.")
        wall_thickness = (number(walls.get("interior"), "wall_thickness.interior", 0, 10),
                          number(walls.get("exterior"), "wall_thickness.exterior", 0, 10))
    policy = raw.get("contribution_policy", "area")
    if policy not in POLICIES:
        fail("invalid_input", "Unknown contribution_policy.")
    limit = raw.get("candidate_limit", 6)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 12:
        fail("invalid_input", "candidate_limit must be an integer from 1 to 12.")
    openings, opening_ids = [], set()
    for item in sequence(raw.get("openings", []), "openings", MAX_OPENINGS):
        if not isinstance(item, dict):
            fail("invalid_input", "Each opening must be an object.")
        oid = identifier(item.get("id"), "opening.id")
        if oid in opening_ids:
            fail("invalid_input", "Opening IDs must be unique.")
        opening_ids.add(oid)
        if item.get("kind") not in ("door", "window", "opening") or item.get("orientation") not in ("h", "v"):
            fail("invalid_input", "Openings need kind door/window/opening and orientation h/v.")
        owners = sequence(item.get("room_ids", []), "opening.room_ids", MAX_ROOMS)
        if any(not isinstance(owner, str) or owner not in {r.id for r in rooms} for owner in owners):
            fail("invalid_input", "Opening references a missing room.", opening_id=oid)
        openings.append({"id": oid, "kind": item["kind"], "orientation": item["orientation"],
                         "x": number(item.get("x"), "opening.x"), "y": number(item.get("y"), "opening.y"),
                         "width": number(item.get("width"), "opening.width", EPS, 100),
                         "entrance": boolean(item.get("entrance", False), "opening.entrance"), "room_ids": owners})
    if reused:
        if not entry_opening_id:
            fail("existing_circulation_entry", "Choose an existing exterior entrance or protected stair-to-landing opening by entry.opening_id.")
        opening = next((o for o in openings if o["id"] == entry_opening_id), None)
        if opening is None:
            fail("existing_circulation_entry", "The selected existing entry opening is missing.", opening_id=entry_opening_id)
        actual_point = (opening["x"], opening["y"])
        if entry_point is not None and Point(entry_point).distance(Point(actual_point)) > EPS:
            fail("existing_circulation_entry", "The selected entry point no longer matches its saved opening.", opening_id=entry_opening_id)
        entry_point = actual_point
        if entry.get("replace_existing", False):
            fail("existing_circulation_entry", "Reusing a landing preserves its existing entrance; do not request entrance replacement.")
    if "seed" in raw and (isinstance(raw["seed"], bool) or not isinstance(raw["seed"], int) or abs(raw["seed"]) > 2**31 - 1):
        fail("invalid_input", "seed must be a 32-bit integer; current deterministic modes do not use randomness.")
    return Request(raw, plan_id, source, digest(raw), units, boundary, tuple(sorted(rooms, key=lambda r: r.id)),
                   obstacles, entry_point, boolean(entry.get("replace_existing", False), "entry.replace_existing"),
                   tuple(required), width, door_width, tuple(modes), policy, tuple(openings), limit,
                   tuple(sorted(reused)), entry_opening_id, wall_thickness)
