"""Semantic programme compilation: people are conserved across seat scenarios."""

from copy import deepcopy
import math

from .models import BriefError, MAX_ROOMS, authorized_floors

DESK_ROLES = {"open_office", "private_office", "focus"}
FUNCTIONS = {"meeting": "bijeenkomstfunctie", "lunch": "bijeenkomstfunctie",
             "pantry": "supporting_service", "wc": "supporting_service",
             "accessible_wc": "supporting_service", "storage": "supporting_service",
             "it": "supporting_service", "cleaning": "supporting_service"}


def requirement(identifier, role, capacity=0, **kwargs):
    return {"id": identifier, "requirement_id": identifier, "role": role,
            "name": role.replace("_", " ").title(), "required_capacity": capacity,
            "capacity": capacity, "min_area_m2": 0, "preferred_area_m2": 0,
            "protect_capacity": True, "locked": False, "provenance": "derived",
            "use_function": FUNCTIONS.get(role, "kantoorfunctie"), **kwargs}


def compile_program(brief, floor_count=None):
    """Expand immutable room identities, then add only uncovered capacities."""
    rooms = []
    for source in brief["rooms"]:
        for n in range(source["count"]):
            room = deepcopy(source)
            room["id"] = f"{source['id']}:{n + 1}" if source["count"] > 1 else source["id"]
            room["requirement_id"] = source["id"]
            room["required_capacity"] = source["capacity"]
            room["use_function"] = FUNCTIONS.get(source["role"], "kantoorfunctie")
            if not room.get("allowed_floors") and brief["building"]["client_rooms_ground_floor"] and room["role"] in {"reception", "meeting"}:
                room["allowed_floors"] = [0]
            rooms.append(room)
    explicit_desks = sum(r["required_capacity"] for r in rooms if r["role"] in DESK_ROLES)
    remaining = max(0, brief["people"]["desks"] - explicit_desks)
    chunk = 8 if brief["building"]["allow_office_split"] and not brief["building"]["keep_teams_together"] else max(1, remaining)
    for n in range(math.ceil(remaining / chunk)):
        rooms.append(requirement(f"derived:work-{n + 1}", "open_office", min(chunk, remaining - n * chunk), name=f"Work zone {n + 1}"))
    amenities = brief["amenities"]
    existing_lunch = sum(r["capacity"] for r in rooms if r["role"] == "lunch")
    if amenities["lunch_seats"] > existing_lunch:
        rooms.append(requirement("derived:lunch", "lunch", amenities["lunch_seats"] - existing_lunch,
                                 allowed_floors=[0], name="Lunch & break room"))
    if amenities["pantry"] != "none" and not any(r["role"] == "pantry" for r in rooms):
        rooms.append(requirement("derived:pantry", "pantry", equipment=amenities["pantry"], allowed_floors=[0]))
    peak = brief["people"]["staff"] + brief["people"]["visitors"]
    wc_count = amenities.get("wc_count", 0) if amenities["wc_policy"] == "specified" else max(amenities.get("wc_count", 0) or 0, math.ceil(peak / amenities["policy_people_per_wc"]))
    existing_wc = sum(max(1, r["capacity"]) for r in rooms if r["role"] == "wc")
    floors = floor_count or 1
    # wc_count is ordinary fixtures. Accessible provision is additional: its
    # availability is not assumed when satisfying the ordinary sanitary policy.
    accessible_floors = range(floors) if brief["building"]["accessibility"] == "all_floors" else [0]
    if amenities["accessible_wc"]:
        for floor in accessible_floors:
            if not any(r["role"] == "accessible_wc" and r.get("allowed_floors") == [floor] for r in rooms):
                rooms.append(requirement(f"derived:accessible-wc-{floor}", "accessible_wc", 1,
                                         allowed_floors=[floor], stack_id="wet-accessible"))
    ordinary_by_floor = [0] * floors
    for n in range(max(0, wc_count - existing_wc)):
        ordinary_by_floor[n % floors] += 1
    for floor, fixtures in enumerate(ordinary_by_floor):
        if fixtures:
            rooms.append(requirement(f"derived:wc-block-{floor}", "wc", fixtures,
                                     name="Ordinary WC block", allowed_floors=[floor]))
    # Every occupied floor retains a nearby sanitary fixture, regardless of an
    # area-ledger surplus elsewhere. Added provision is disclosed in the result.
    for floor in range(floors):
        if not any(r["role"] in {"wc", "accessible_wc"} and r.get("allowed_floors") == [floor] for r in rooms):
            rooms.append(requirement(f"derived:local-wc-{floor}", "wc", 1, allowed_floors=[floor]))
    if len(rooms) > MAX_ROOMS:
        raise BriefError("programme_limit", "Furniture zones and per-floor amenities exceed the 64-room bounded search scope.", {"expanded_rooms": len(rooms)})
    return rooms


def lower_area(room):
    """Optimistic physical-furniture lower bound, never a feasibility promise."""
    cap = room["required_capacity"]
    physical = {"open_office": 1.64 * cap, "private_office": 1.64 * cap,
                "focus": 1.64 * cap, "meeting": 0.6 * cap,
                "lunch": 0.6 * cap, "wc": 2.1, "accessible_wc": 5.5,
                "pantry": 2.0, "rest": 3.0}.get(room["role"], 1.0)
    return max(room["min_area_m2"], physical)


def estimated_area(room):
    cap = room["required_capacity"]
    target = {"open_office": 6.5 * cap, "private_office": max(9, 7 * cap),
              "focus": max(7, 7 * cap), "meeting": max(10, 2.25 * cap),
              "lunch": max(8, 1.8 * cap), "pantry": 8,
              "wc": max(4.5, 3 * cap), "accessible_wc": 7,
              "reception": 10, "rest": 9, "shower": 5}.get(room["role"], 6)
    return max(room["min_area_m2"], room["preferred_area_m2"], target)


def occupancy_scenarios(brief, rooms):
    """No mutually exclusive scenario is added to another scenario."""
    staff, visitors = brief["people"]["staff"], brief["people"]["visitors"]
    meeting = sum(r.get("required_capacity", r.get("capacity", 0)) for r in rooms if r["role"] == "meeting")
    lunch = sum(r.get("required_capacity", r.get("capacity", 0)) for r in rooms if r["role"] == "lunch")
    visitor_meeting = min(visitors, meeting)
    staff_meeting = min(staff, max(0, meeting - visitor_meeting))
    staff_lunch = min(staff, lunch)
    return [
        {"id": "normal-work", "name": "Normal work", "staff": staff, "visitors": visitors,
         "total_people": staff + visitors, "distribution": {"work": staff, "visitors": visitors}},
        {"id": "client-meeting", "name": "Client meetings", "staff": staff, "visitors": visitors,
         "total_people": staff + visitors, "distribution": {"work": staff - staff_meeting,
             "meeting": staff_meeting + visitor_meeting, "other_visitors": visitors - visitor_meeting}},
        {"id": "lunch", "name": "Lunch with other staff still working", "staff": staff,
         "visitors": visitors, "total_people": staff + visitors,
         "distribution": {"lunch": staff_lunch, "work": staff - staff_lunch, "visitors": visitors}},
    ]


def estimate(brief):
    rooms = compile_program(brief)
    net = sum(estimated_area(r) for r in rooms)
    lower = sum(lower_area(r) for r in rooms)
    plate = brief["site"]["width_m"] * brief["site"]["depth_m"]
    floors = authorized_floors(brief)
    return {"schema_version": "1.0", "net_area_m2": round(net, 2), "hard_area_lower_bound_m2": round(lower, 2),
            "buildable_area_m2": plate, "min_floors": max(1, math.ceil(net / (plate * 0.7))),
            "area_range_m2": [round(net / 0.8, 2), round(net / 0.65, 2)],
            **brief["people"], "meeting_rooms": sum(r["role"] == "meeting" for r in rooms),
            "meeting_seats": sum(r["capacity"] for r in rooms if r["role"] == "meeting"),
            "lunch_seats": sum(r["capacity"] for r in rooms if r["role"] == "lunch"),
            "requirements": rooms, "occupancy_scenarios": occupancy_scenarios(brief, rooms),
            "authorized_floor_counts": floors,
            "assumptions": ["Furniture planning targets include local desk aisles; shared routes are separate.",
                "20–35% preliminary allowance for shared routes, walls and services; cores are fitted separately.",
                f"Sanitary planning ratio: one WC per {brief['amenities']['policy_people_per_wc']} people is a provisional policy, not Dutch statutory law.",
                "The WC count covers ordinary fixtures; accessible fixtures are additional and never reduce it.",
                "Meeting and lunch seats redistribute staff; visitors increase the simultaneous population.",
                "A geometric fit does not establish legal approval, NEN conformity or verified site discharge."],
            "issues": [] if floors else ["The allowed height excludes all requested floor counts."]}
