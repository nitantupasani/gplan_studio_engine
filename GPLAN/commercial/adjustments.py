"""Explicit, independently checked programme alternatives after a strict miss.

Only numeric demand may decrease. Geometry, use classifications, allowed floors,
accessibility, sanitary provision, fixed positions and rules remain immutable.
These alternatives never claim to satisfy a larger original programme.
"""

from copy import deepcopy
import math

from .models import BriefError, EPS, fingerprint, normalize_brief
from .program import DESK_ROLES

PROTECTED_ROLES = {"wc", "accessible_wc", "shower", "public_cafe"}
ROOM_NUMBER_FIELDS = {"capacity", "count", "min_area_m2", "preferred_area_m2"}


def _mutable_room(room):
    return room["role"] not in PROTECTED_ROLES and not room.get("locked") and not room.get("locked_geometry")


def validate_adjusted_brief(original, fitted):
    """Reject any change outside the narrowly authorised numeric demand scope."""
    if not original["building"]["allow_programme_adjustments"]:
        raise BriefError("adjustments_not_authorised", "The original brief did not authorise a modified-programme alternative.")
    fitted = normalize_brief(fitted)
    if len(original["rooms"]) != len(fitted["rooms"]):
        raise BriefError("invalid_adjustment", "Modified programmes must retain the original requirement identities.")
    # Occupancy is an operating requirement, not a quantity to erase to make
    # fire-flow checks easier. A desk shortfall is disclosed separately.
    permitted = {("people", "desks")}
    permitted.add(("amenities", "lunch_seats"))
    for index, room in enumerate(original["rooms"]):
        if _mutable_room(room):
            permitted.update(("rooms", index, field) for field in ROOM_NUMBER_FIELDS)
    changes = []

    def compare(before, after, path=()):
        if before == after:
            return
        if path in permitted:
            if isinstance(after, bool) or not isinstance(after, (int, float)) or not math.isfinite(after) or after > before:
                raise BriefError("invalid_adjustment", "Programme adjustments may only reduce the authorised numeric demand.", {"path": list(path)})
            changes.append(path)
            return
        if isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after):
            for key in before:
                compare(before[key], after[key], path + (key,))
            return
        if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
            for index, (a, b) in enumerate(zip(before, after)):
                compare(a, b, path + (index,))
            return
        raise BriefError("invalid_adjustment", "A modified programme cannot change the site, safety provisions, floor allowance, identities or locked geometry.", {"path": list(path)})

    compare(original, fitted)
    if not changes:
        raise BriefError("invalid_adjustment", "A modified-programme receipt needs an actual numeric change.")
    return fitted, changes


def constraint_deviations(original, fitted, candidate):
    """Report unmet original demand using measured output, not claimed deltas."""
    deviations = []

    def add(path, label, kind, requested, provided, unit, requirement_id=None):
        if provided + EPS >= requested:
            return
        entry = {"id": "unmet:" + path, "path": path, "label": label, "kind": kind,
                 "requested": requested, "provided": round(provided, 6), "unit": unit,
                 "detail": f"Requested {requested:g} {unit}; this alternative provides {provided:g}. The original requirement remains unmet."}
        if requirement_id is not None:
            entry["requirement_id"] = requirement_id
        deviations.append(entry)

    # Optional residual-space fit-outs do not discharge original requirements,
    # particularly while their routes still need redesign.
    all_rooms = [room for floor in candidate["floors"] for room in floor["rooms"] if not room.get("supplementary")]
    desks = sum(sum(f["kind"] == "desk" for f in room["furniture"]) for room in all_rooms if room["role"] in DESK_ROLES)
    lunch = sum(sum(f["kind"] == "lunch_chair" for f in room["furniture"]) for room in all_rooms if room["role"] == "lunch")
    add("people.staff", "Simultaneous staff", "occupancy", original["people"]["staff"], fitted["people"]["staff"], "people")
    add("people.visitors", "Simultaneous visitors", "occupancy", original["people"]["visitors"], fitted["people"]["visitors"], "people")
    add("people.desks", "Workstations", "capacity", original["people"]["desks"], desks, "desks")
    add("amenities.lunch_seats", "Lunch seating", "capacity", original["amenities"]["lunch_seats"], lunch, "seats")
    for index, requested in enumerate(original["rooms"]):
        rooms = [r for r in all_rooms if r["requirement_id"] == requested["id"]]
        path = f"rooms[{index}]"
        name, rid = requested["name"], requested["id"]
        add(path + ".count", name + " count", "quantity", requested["count"], len(rooms), "rooms", rid)
        if rooms:
            add(path + ".capacity", name + " capacity per room", "capacity", requested["capacity"],
                min(r["capacity"] for r in rooms), "places", rid)
            actual_minimum = min(r["rect"]["width"] * r["rect"]["height"] for r in rooms)
            add(path + ".min_area_m2", name + " clear area per room", "minimum_area", requested["min_area_m2"], actual_minimum, "m²", rid)
    return deviations


def deviation_cost(original, fitted):
    """Disclosed lexicographic preference: retain people/desks before amenities."""
    room_loss = 0
    area_loss = 0
    quantity_loss = 0
    for before, after in zip(original["rooms"], fitted["rooms"]):
        quantity_loss += before["count"] - after["count"]
        room_loss += before["count"] * before["capacity"] - after["count"] * after["capacity"]
        area_loss += before["count"] * (before["min_area_m2"] - after["min_area_m2"])
    return (original["people"]["staff"] - fitted["people"]["staff"],
            original["people"]["visitors"] - fitted["people"]["visitors"],
            original["people"]["desks"] - fitted["people"]["desks"],
            room_loss + original["amenities"]["lunch_seats"] - fitted["amenities"]["lunch_seats"], quantity_loss, area_loss)


def adjusted_briefs(original, diagnostics, maximum=32):
    """Compare retained room count×capacity while keeping people immutable."""
    targets = set()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get("requirement_id"):
            targets.add(diagnostic["requirement_id"])
        for check in diagnostic.get("checks", []):
            identifiers = check.get("witness", {}).get("entity_ids", [])
            for room in original["rooms"]:
                if any(f":{room['id']}" in identifier for identifier in identifiers):
                    targets.add(room["id"])
    adjustable = [r for r in original["rooms"] if _mutable_room(r)]
    # Large indivisible meeting/lunch rooms can dominate a packing miss even
    # when the last reported deficit was an office zone assigned after them.
    targets.update(r["id"] for r in adjustable if r["role"] in {"meeting", "lunch"} and r["capacity"] > 8)
    recipes = []

    def lower(value, factor, minimum=0):
        return max(minimum, min(value, math.floor(value * factor)))

    def amend(factor, count_factor=1.0, desk_factor=1.0, reduce_areas=False):
        result = deepcopy(original)
        for room in result["rooms"]:
            if not _mutable_room(room):
                continue
            if room["role"] in {"meeting", "lunch"}:
                room["count"] = max(1, math.ceil(room["count"] * count_factor))
                # Keep useful rooms: never turn an originally larger meeting
                # room into a single chair to preserve a nominal room count.
                room["capacity"] = lower(room["capacity"], factor, min(4, room["capacity"]))
            elif room["role"] in DESK_ROLES and desk_factor < 1:
                room["capacity"] = lower(room["capacity"], desk_factor, min(4, room["capacity"]))
            if reduce_areas and room["id"] in targets:
                room["min_area_m2"] = round(room["min_area_m2"] * factor, 3)
                room["preferred_area_m2"] = round(room["preferred_area_m2"] * factor, 3)
        lunch_factor = min(.9, factor) if factor < 1 or count_factor < 1 else 1
        result["amenities"]["lunch_seats"] = lower(result["amenities"]["lunch_seats"], lunch_factor, min(4, result["amenities"]["lunch_seats"]))
        result["people"]["desks"] = lower(result["people"]["desks"], desk_factor, min(4, result["people"]["desks"]))
        try:
            result, _ = validate_adjusted_brief(original, result)
        except BriefError:
            return
        recipes.append(result)

    # Fewer useful meeting rooms and unchanged desks are explored before any
    # desk-limited alternative. This replaces the old zero-programme escape.
    for count_factor in (1.0, .8, .6, .4):
        for factor in (1.0, .9, .75, .5):
            amend(factor, count_factor)
    for factor in (.75, .5):
        amend(factor, .6, reduce_areas=True)
    for desk_factor in (.9, .75, .6, .5, .375, .25, .125):
        amend(.5, .6, desk_factor=desk_factor)
    unique = {fingerprint(brief): brief for brief in recipes}
    return sorted(unique.values(), key=lambda brief: deviation_cost(original, brief))[:maximum]


def recovery_brief(original):
    """Get a useful checked starting option before spending time on refinements.

    Retain staff, visitors and desks. Reduce only already-authorised room demand;
    the normal deviation receipt records every lost room, seat and area target.
    """
    fitted = deepcopy(original)
    for room in fitted["rooms"]:
        if not _mutable_room(room):
            continue
        room["count"] = 1
        if room["role"] in {"meeting", "lunch"}:
            room["capacity"] = min(room["capacity"], 4)
        room["min_area_m2"] = 0
        room["preferred_area_m2"] = 0
    fitted["amenities"]["lunch_seats"] = min(fitted["amenities"]["lunch_seats"], 4)
    try:
        return validate_adjusted_brief(original, fitted)[0]
    except BriefError:
        return None


def restoration_briefs(original, fitted):
    """Bounded upward refinements after a fit; retain the best feasible result."""
    restored = []
    paths = [("people", "desks"), ("amenities", "lunch_seats")]
    paths += [("rooms", i, field) for i, r in enumerate(original["rooms"]) if _mutable_room(r)
              for field in ("count", "capacity", "min_area_m2")]
    for path in paths:
        before, after = original, fitted
        for key in path[:-1]:
            before, after = before[key], after[key]
        key = path[-1]
        if after[key] >= before[key]:
            continue
        result = deepcopy(fitted)
        target = result
        for component in path[:-1]:
            target = target[component]
        target[key] = math.ceil((before[key] + after[key]) / 2) if key != "min_area_m2" else round((before[key] + after[key]) / 2, 3)
        try:
            result, _ = validate_adjusted_brief(original, result)
        except BriefError:
            continue
        restored.append(result)
    return sorted(restored, key=lambda brief: deviation_cost(original, brief))


def attach_adjustment_receipt(candidate, original, fitted):
    result = deepcopy(candidate)
    result.update(fit_kind="modified_programme", fitted_brief=deepcopy(fitted),
                  original_brief_fingerprint=fingerprint(original), fitted_brief_fingerprint=fingerprint(fitted),
                  brief_fingerprint=fingerprint(original), satisfies_original_brief=False,
                  constraint_deviations=constraint_deviations(original, fitted, candidate))
    result["id"] = "modified-" + fingerprint({"original": fingerprint(original), "fitted": fingerprint(fitted), "geometry": candidate["geometry_fingerprint"]})[:16]
    result["name"] = candidate.get("name", "Office option") + " · modified programme"
    return result
