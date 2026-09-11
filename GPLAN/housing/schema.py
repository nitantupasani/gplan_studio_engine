"""Strict, inexpensive validation of the integer-millimetre house contract.

This module deliberately imports neither the legacy API nor a solver, so HTTP
adapters can reject unsupported required inputs before starting a worker.
"""
from copy import deepcopy
import hashlib
import json
import math

from . import SCHEMA_VERSION


class HouseRequestError(ValueError):
    pass


def _integer(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
        raise HouseRequestError(f"{name} must be an integer.")
    value = int(value)
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise HouseRequestError(f"{name} is outside the supported range {minimum}–{maximum}.")
    return value


def _object(value, name, allowed):
    if not isinstance(value, dict):
        raise HouseRequestError(f"{name} must be an object.")
    unknown = set(value) - set(allowed)
    if unknown:
        raise HouseRequestError(f"Unsupported {name} fields: {', '.join(sorted(unknown))}. No required constraint is silently ignored.")
    return value


def normalize_request(request_data):
    raw = deepcopy(_object(request_data, "request", {
        "schema_version", "units", "plot", "programme_profile", "requested_options", "storeys",
        "parking", "setbacks", "roof", "search", "constraint_policy", "walls", "household",
        "locked_cores", "design_revision", "request_fingerprint",
    }))
    if raw.get("schema_version") != SCHEMA_VERSION or raw.get("units") != "mm":
        raise HouseRequestError("Expected schema_version house_concepts_v1 and units mm; coordinates must be integer millimetres.")
    if raw.get("programme_profile", "NL_concept_v1") != "NL_concept_v1":
        raise HouseRequestError("Only programme_profile NL_concept_v1 is currently supported.")
    plot = _object(raw.get("plot"), "plot", {"polygon", "front_edge", "entry", "party_wall_edges"})
    points = plot.get("polygon")
    if not isinstance(points, list):
        raise HouseRequestError("plot.polygon must contain the four rectangle corners.")
    if len(points) == 5 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) != 4 or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points):
        raise HouseRequestError("The initial house generator supports a single axis-aligned rectangular plot.")
    points = [[_integer(v, "plot coordinate", -100000000, 100000000) for v in p] for p in points]
    xs, ys = {p[0] for p in points}, {p[1] for p in points}
    if len(xs) != 2 or len(ys) != 2 or len({tuple(p) for p in points}) != 4:
        raise HouseRequestError("The initial house generator supports a single axis-aligned rectangular plot.")
    for a, b in zip(points, points[1:] + points[:1]):
        if (a[0] == b[0]) == (a[1] == b[1]):
            raise HouseRequestError("Plot vertices must follow the rectangle boundary in order.")
    if min(max(xs) - min(xs), max(ys) - min(ys)) < 1000 or max(max(xs) - min(xs), max(ys) - min(ys)) > 100000:
        raise HouseRequestError("Plot dimensions must be between 1 and 100 metres.")
    front = _integer(plot.get("front_edge", 0), "plot.front_edge", 0, 3)
    if plot.get("party_wall_edges"):
        raise HouseRequestError("Party-wall exposure constraints are not supported by this initial detached-house profile.")
    if plot.get("entry") is not None:
        raise HouseRequestError("A locked plot entry point is not supported yet; the generator must choose a clear entrance route.")
    policy = _object(raw.get("constraint_policy", {}), "constraint_policy", {"required", "preferred"})
    if policy.get("required"):
        raise HouseRequestError("Unsupported required constraint_policy entries. Use the typed supported fields; mandatory constraints are never relaxed.")
    if policy.get("preferred"):
        raise HouseRequestError("Generic preferred constraints are not supported; use parking, setbacks, roof and household fields.")
    if raw.get("locked_cores"):
        raise HouseRequestError("Authored core locks are not supported by the initial corner-core topology search; no interior lock will be silently moved.")
    modes = {"g+1_attic", "g+2_attic"}
    storeys = _object(raw.get("storeys", {}), "storeys", {"mode", "allow"})
    mode = storeys.get("mode", "auto")
    allow = storeys.get("allow", ["g+1_attic", "g+2_attic"])
    if not isinstance(mode,str) or mode not in modes | {"auto"} or not isinstance(allow, list) or not allow or any(not isinstance(m,str) or m not in modes for m in allow):
        raise HouseRequestError("storeys must use auto, g+1_attic or g+2_attic, with supported allow values.")
    if mode != "auto" and mode not in allow:
        raise HouseRequestError("The requested storey mode is excluded by storeys.allow.")
    parking = _object(raw.get("parking", {}), "parking", {"preference", "cars"})
    preference = parking.get("preference", "front")
    cars = _integer(parking.get("cars", 0 if preference == "none" else 1), "parking.cars", 0, 1)
    if not isinstance(preference,str) or preference not in {"front", "none"} or (preference == "none" and cars):
        raise HouseRequestError("Parking supports front with zero/one car, or none with zero cars.")
    setbacks = _object(raw.get("setbacks", {}), "setbacks", {"front_mm", "side_mm", "rear_mm"})
    setbacks = {k: _integer(setbacks.get(k, d), f"setbacks.{k}", 0, 30000) for k, d in [("front_mm", 0), ("side_mm", 300), ("rear_mm", 1200)]}
    walls = _object(raw.get("walls", {}), "walls", {"interior_mm", "exterior_mm"})
    walls = {k: _integer(walls.get(k, d), f"walls.{k}", 50, 500) for k, d in [("interior_mm", 100), ("exterior_mm", 200)]}
    roof = _object(raw.get("roof", {}), "roof", {"type", "pitch_deg", "knee_wall_mm", "ridge_axis", "overhang_mm", "thickness_mm"})
    if roof.get("type", "gable") != "gable":
        raise HouseRequestError("Only a gable roof is currently supported.")
    pitch = roof.get("pitch_deg", 45)
    if isinstance(pitch, bool) or not isinstance(pitch, (int, float)) or not math.isfinite(pitch) or not 30 <= pitch <= 55:
        raise HouseRequestError("roof.pitch_deg must be between 30 and 55 degrees.")
    axis = roof.get("ridge_axis")
    if axis is not None and (not isinstance(axis,str) or axis not in {"x", "y"}):
        raise HouseRequestError("roof.ridge_axis must be x or y.")
    normalized_roof = {"type": "gable", "pitch_deg": float(pitch), "overhang_mm": _integer(roof.get("overhang_mm", 300), "roof.overhang_mm", 0, 800), "thickness_mm": _integer(roof.get("thickness_mm", 180), "roof.thickness_mm", 0, 500)}
    if "knee_wall_mm" in roof:
        normalized_roof["knee_wall_mm"] = _integer(roof["knee_wall_mm"], "roof.knee_wall_mm", 500, 2100)
    if axis:
        normalized_roof["ridge_axis"] = axis
    household = _object(raw.get("household", {}), "household", {"bedrooms", "bathroom_wc"})
    bedrooms = _integer(household.get("bedrooms", 2), "household.bedrooms", 1, 5)
    bathroom_wc = household.get("bathroom_wc", "combined")
    if not isinstance(bathroom_wc,str) or bathroom_wc not in {"combined", "separate"}:
        raise HouseRequestError("household.bathroom_wc must be combined or separate.")
    search = _object(raw.get("search", {}), "search", {"budget_ms", "seed", "max_candidates"})
    result = {
        "schema_version": SCHEMA_VERSION, "units": "mm", "programme_profile": "NL_concept_v1",
        "plot": {"polygon": points, "front_edge": front},
        "requested_options": _integer(raw.get("requested_options", 5), "requested_options", 1, 5),
        "storeys": {"mode": mode, "allow": list(dict.fromkeys(allow))},
        "parking": {"preference": preference, "cars": cars}, "setbacks": setbacks,
        "walls": walls, "roof": normalized_roof, "household": {"bedrooms": bedrooms, "bathroom_wc": bathroom_wc},
        "constraint_policy": {"required": [], "preferred": []},
        "search": {"budget_ms": _integer(search.get("budget_ms", 30000), "search.budget_ms", 1, 120000), "seed": _integer(search.get("seed", 0), "search.seed", 0, 2147483647), "max_candidates": _integer(search.get("max_candidates", 72), "search.max_candidates", 1, 200)},
    }
    for k in ("design_revision", "request_fingerprint"):
        if k in raw:
            if not isinstance(raw[k], (str, int)) or isinstance(raw[k], bool):
                raise HouseRequestError(f"{k} must be a string or integer.")
            result[k] = raw[k]
    return result


def request_fingerprint(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


validate_request = normalize_request
