"""Measured room limits within the solver's reserved rectangular slots.

These are individual template limits, not whole-building feasibility claims.
Sanitary provision and locked geometry are never reduced by this advice.
"""

import math

from .models import EPS
from .templates import PARTITION, fit_template


def fits_slot(room, slot, spacious=False):
    template = fit_template(room, slot["width"], spacious)
    return bool(template and slot["y"] + template["depth"] + PARTITION <= slot["end"] + EPS)


def room_fit_issue(room, slots, scope="individual_room", spacious=False):
    issue = {"code": "room_fit_deficit", "requirement_id": room["requirement_id"],
             "label": room["name"], "required_capacity": room["required_capacity"],
             "minimum_area_m2": room["min_area_m2"], "scope": scope,
             "detail": f"{room['name']}: not enough space on an eligible floor."}
    if scope == "remaining_slots":
        # A tail left by one packing order is NOT a room-capacity bound. In a
        # wide wing, even the table rotation can change when seats are reduced.
        # Only empty-floor preflight or a checked complete option may suggest
        # changing the user's programme.
        issue.update(code="room_placement_conflict",
                     detail=f"{room['name']}: the room arrangement needs to change.")
        return issue
    if room.get("locked") or room["role"] in {"wc", "accessible_wc", "pantry"}:
        return issue
    # Area and capacity can both bind. Every offered combination is fitted,
    # with the area rounded DOWN so the displayed limit itself remains usable.
    choices = []
    reducible = room["role"] in {"meeting", "lunch", "open_office", "private_office", "focus", "reception"}
    for slot in slots:
        area = math.floor(max(0, slot["end"] - slot["y"] - PARTITION) * slot["width"] * 10) / 10
        test = {**room, "min_area_m2": min(room["min_area_m2"], area),
                "preferred_area_m2": min(room["preferred_area_m2"], area)}
        minimum_capacity = 0 if room["role"] == "reception" else 1
        low, high = (minimum_capacity if reducible else room["required_capacity"]), room["required_capacity"]
        best = None
        while low <= high:
            capacity = (low + high) // 2
            if fits_slot({**test, "required_capacity": capacity}, slot, spacious):
                best = capacity
                low = capacity + 1
            else:
                high = capacity - 1
        if best is not None:
            choices.append((test["min_area_m2"] == room["min_area_m2"], best, area, test))
    if not choices:
        issue["detail"] = f"{room['name']}: needs a wider or deeper room; lowering capacity alone will not fit."
        return issue
    _, capacity, area, test = max(choices, key=lambda item: item[:3])
    suggested = {}
    if capacity < room["required_capacity"]:
        suggested["capacity"] = capacity
    if test["min_area_m2"] < room["min_area_m2"]:
        suggested["min_area_m2"] = area
    if (spacious or "min_area_m2" in suggested) and test["preferred_area_m2"] < room["preferred_area_m2"]:
        suggested["preferred_area_m2"] = area
    if suggested:
        issue["suggested_values"] = suggested
        issue["suggestion_basis"] = "Maximum individual room fit in the checked slots; other rooms and routes still need generation."
    return issue
