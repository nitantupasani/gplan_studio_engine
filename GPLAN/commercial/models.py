"""Strict, bounded JSON contract. Every dimension in this package is metres."""

from copy import deepcopy
import hashlib
import json
import math

SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "commercial-office-1.0"
RULE_PROFILE = "nl-office-newbuild-2026-09-11-design-basis"
MAX_ROOMS = 64
MAX_CANDIDATES = 3
MAX_ATTEMPTS = 48
MAX_SECONDS = 12.0
MAX_ADJUSTED_SECONDS = 30.0
MAX_ADJUSTED_BRIEFS = 32
EPS = 1e-6
ROLES = (
    "open_office", "meeting", "private_office", "focus", "reception",
    "storage", "printing", "it", "cleaning", "rest", "lunch", "pantry",
    "wc", "accessible_wc", "lockers", "shower", "public_cafe",
)


class BriefError(ValueError):
    def __init__(self, code, message, details=None, http_status=422):
        super().__init__(message)
        self.code, self.message = code, message
        self.details, self.http_status = details or {}, http_status

    def to_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}


def number(value, path, minimum=0, maximum=1_000_000, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BriefError("invalid_input", f"{path} must be a finite number.", {"field": path})
    if not minimum <= value <= maximum or (integer and int(value) != value):
        raise BriefError("invalid_input", f"{path} is outside the supported range.",
                         {"field": path, "minimum": minimum, "maximum": maximum})
    return int(value) if integer else float(value)


def choice(value, choices, path):
    if value not in choices:
        raise BriefError("invalid_input", f"{path} must be one of {', '.join(choices)}.", {"field": path})
    return value


def flag(value, path):
    if not isinstance(value, bool):
        raise BriefError("invalid_input", f"{path} must be a boolean.", {"field": path})
    return value


def object_value(value, path):
    if not isinstance(value, dict):
        raise BriefError("invalid_input", f"{path} must be an object.", {"field": path})
    return value


def text_value(value, path, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BriefError("invalid_input", f"{path} must be a nonempty string of at most {maximum} characters.")
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def normalize_brief(data):
    object_value(data, "brief")
    try:
        if len(json.dumps(data, allow_nan=False)) > 1_000_000:
            raise BriefError("invalid_input", "Commercial briefs must be at most 1 MB.")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, BriefError):
            raise
        raise BriefError("invalid_input", "Brief must contain JSON-compatible finite values.") from exc
    result = deepcopy(data)
    version = result.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise BriefError("unsupported_schema", f"Commercial schema {version} is unsupported.")
    result["schema_version"] = SCHEMA_VERSION
    result["rules_profile"] = choice(result.get("rules_profile", RULE_PROFILE), [RULE_PROFILE], "rules_profile")
    site = object_value(result.setdefault("site", {}), "site")
    for name in ("width_m", "depth_m"):
        site[name] = number(site.get(name), f"site.{name}", 3, 200)
    site["entrance_side"] = choice(site.get("entrance_side", "south"),
                                    ["south", "north", "east", "west"], "site.entrance_side")
    site["regime"] = choice(site.get("regime", "new_build"),
                            ["new_build", "existing", "alteration"], "site.regime")
    for name in ("discharge_confirmed", "buildable_confirmed"):
        site[name] = flag(site.get(name, False), f"site.{name}")
    site.setdefault("address", "")
    people = object_value(result.setdefault("people", {}), "people")
    people["staff"] = number(people.get("staff", 20), "people.staff", 1, 1000, True)
    people["visitors"] = number(people.get("visitors", 0), "people.visitors", 0, 1000, True)
    people["desks"] = number(people.get("desks", people["staff"]), "people.desks", 1, 1000, True)
    if "headcount" in people:
        people["headcount"] = number(people["headcount"], "people.headcount", people["staff"], 100_000, True)
    building = object_value(result.setdefault("building", {}), "building")
    building["floor_strategy"] = choice(building.get("floor_strategy", "single"),
                                         ["single", "exact", "auto"], "building.floor_strategy")
    for name in ("floor_count", "max_floors"):
        building[name] = number(building.get(name, 1 if name == "floor_count" else 4),
                                f"building.{name}", 1, 4, True)
    building["floor_height_m"] = number(building.get("floor_height_m", 3.3), "building.floor_height_m", 2.8, 5.0)
    building["accessibility"] = choice(building.get("accessibility", "all_floors"),
                                        ["all_floors", "ground_floor"], "building.accessibility")
    building["keep_teams_together"] = flag(building.get("keep_teams_together", False), "building.keep_teams_together")
    building["client_rooms_ground_floor"] = flag(building.get("client_rooms_ground", building.get("client_rooms_ground_floor", True)), "building.client_rooms_ground_floor")
    building["allow_office_split"] = flag(building.get("allow_office_split", True), "building.allow_office_split")
    building["core_side"] = choice(building.get("core_side", "left"), ["left", "right"], "building.core_side")
    building["allow_programme_adjustments"] = flag(building.get("allow_programme_adjustments", False), "building.allow_programme_adjustments")
    building["auto_add_floors"] = flag(building.get("auto_add_floors", False), "building.auto_add_floors")
    if site.get("max_height_m") is not None:
        building["allowed_height_m"] = number(site["max_height_m"], "site.max_height_m", 2.8, 30)
    elif building.get("allowed_height_m") is not None:
        building["allowed_height_m"] = number(building["allowed_height_m"], "building.allowed_height_m", 2.8, 30)
    rooms = result.setdefault("rooms", [])
    if not isinstance(rooms, list) or len(rooms) > MAX_ROOMS:
        raise BriefError("invalid_input", f"rooms must be a list with at most {MAX_ROOMS} requirements.")
    used = set()
    for i, room in enumerate(rooms):
        object_value(room, f"rooms[{i}]")
        room["id"] = text_value(room.get("id", f"user-room-{i + 1}"), f"rooms[{i}].id")
        if room["id"] in used or room["id"].startswith("derived:"):
            raise BriefError("invalid_input", "Room IDs must be unique and may not start with derived:.")
        used.add(room["id"])
        room["role"] = choice(room.get("role"), ROLES, f"rooms[{i}].role")
        room["name"] = text_value(room.get("name", room["role"].replace("_", " ").title()), f"rooms[{i}].name")
        room["count"] = number(room.get("count", 1), f"rooms[{i}].count", 1, 64, True)
        room["capacity"] = number(room.get("capacity", 1), f"rooms[{i}].capacity", 0, 1000, True)
        room["min_area_m2"] = number(room.get("min_area_m2", 0), f"rooms[{i}].min_area_m2", 0, 10_000)
        room["preferred_area_m2"] = number(room.get("preferred_area_m2", room["min_area_m2"]),
                                           f"rooms[{i}].preferred_area_m2", 0, 10_000)
        room["protect_capacity"] = flag(room.get("protect_capacity", True), f"rooms[{i}].protect_capacity")
        room["locked"] = flag(room.get("locked", False), f"rooms[{i}].locked")
        room.setdefault("provenance", "user_entered")
        if room.get("locked_geometry") is not None:
            lock = object_value(room["locked_geometry"], f"rooms[{i}].locked_geometry")
            lock["floor_index"] = number(lock.get("floor_index"), "locked_geometry.floor_index", 0, 3, True)
            fixed = object_value(lock.get("rect"), "locked_geometry.rect")
            for key in ("x", "y", "width", "height"):
                fixed[key] = number(fixed.get(key), f"locked_geometry.rect.{key}", .01 if key in {"width", "height"} else 0, 200)
        if "allowed_floors" in room:
            if not isinstance(room["allowed_floors"], list):
                raise BriefError("invalid_input", "allowed_floors must be a list of zero-based floor indices; empty means any authorised floor.")
            room["allowed_floors"] = sorted(set(number(f, "allowed_floors", 0, 3, True) for f in room["allowed_floors"]))
    if sum(r["count"] for r in rooms) > MAX_ROOMS:
        raise BriefError("invalid_input", "Expanded room counts exceed the 64-room search limit.")
    amenities = object_value(result.setdefault("amenities", {}), "amenities")
    amenities["wc_policy"] = choice(amenities.get("wc_policy", "auto"),
                                     ["auto", "planning_ratio", "specified"], "amenities.wc_policy")
    amenities["policy_people_per_wc"] = number(amenities.get("policy_people_per_wc", 20),
                                               "amenities.policy_people_per_wc", 1, 100, True)
    if amenities.get("wc_count") is not None:
        amenities["wc_count"] = number(amenities["wc_count"], "amenities.wc_count", 0, 100, True)
    elif amenities["wc_policy"] == "specified":
        raise BriefError("invalid_input", "A specified sanitary policy needs wc_count.")
    amenities["accessible_wc"] = flag(amenities.get("accessible_wc", True), "amenities.accessible_wc")
    amenities["pantry"] = choice(amenities.get("pantry", "tea"), ["none", "tea", "reheat", "cooking"], "amenities.pantry")
    amenities["lunch_seats"] = number(amenities.get("lunch_seats", min(people["staff"], 8)),
                                       "amenities.lunch_seats", 0, 1000, True)
    amenities["public_cafe"] = flag(amenities.get("public_cafe", False), "amenities.public_cafe")
    return result


def authorized_floors(brief):
    b = brief["building"]
    floors = [1] if b["floor_strategy"] == "single" else ([b["floor_count"]] if b["floor_strategy"] == "exact" else list(range(1, b["max_floors"] + 1)))
    if b.get("auto_add_floors"):
        floors = sorted(set(floors + list(range(max(floors) + 1, 5))))
    if b.get("allowed_height_m") is not None:
        floors = [n for n in floors if n * b["floor_height_m"] <= b["allowed_height_m"] + EPS]
    return floors


def unsupported_reasons(brief):
    reasons = []
    site = brief["site"]
    if site["regime"] != "new_build":
        reasons.append("Existing buildings and alterations require a separately implemented rule profile.")
    if brief["amenities"]["public_cafe"] or any(r["role"] == "public_cafe" for r in brief["rooms"]):
        reasons.append("Public hospitality and independent mixed-use occupancy are outside this office generator.")
    for key in ("polygon", "buildable_polygon", "floor_envelopes", "columns", "fixed_objects", "fixed_cores"):
        if site.get(key):
            reasons.append(f"Explicit {key} geometry is not supported by the rectangular office candidate source.")
    if any(room.get("rect") or room.get("polygon") for room in brief["rooms"]):
        reasons.append("Use locked_geometry for supported full-wing room coordinates; arbitrary interior room polygons need a different placement source.")
    if any(room.get("locked") and not room.get("locked_geometry") for room in brief["rooms"]):
        reasons.append("A room position is locked but no supported baseline geometry was supplied. Unlock it explicitly before generating a new placement.")
    if any(room.get("locked_geometry") and room["count"] != 1 for room in brief["rooms"]):
        reasons.append("A position lock applies to one room instance. Split the repeated requirement into individual IDs before locking it.")
    return reasons


def rect(x, y, width, height):
    return {"x": round(x, 6), "y": round(y, 6), "width": round(width, 6), "height": round(height, 6)}


def polygon(r):
    x, y, w, h = r["x"], r["y"], r["width"], r["height"]
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def area(r):
    return r["width"] * r["height"]


def assessment(identifier, status, category, title, detail="", **kwargs):
    return {"id": identifier, "status": status, "category": category, "title": title,
            "detail": detail, **kwargs}
