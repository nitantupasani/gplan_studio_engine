"""Check individual room fit against empty reserved floors before searching."""

from .models import EPS, authorized_floors
from .program import compile_program, estimate, estimated_area
from .generation import start_floor
from .templates import PARTITION, fit_template


def preflight(brief):
    result = estimate(brief)
    counts = authorized_floors(brief)
    issues = []
    slots = {}
    # No layout search: only empty envelopes with real stairs/services reserved.
    for count in counts:
        for index in range(count):
            for offset in (.5, .45, .55):
                for position in ("entrance", "central") if count > 1 else ("entrance",):
                    floor, _ = start_floor(brief, count, index, offset, position)
                    if floor:
                        slots.setdefault(index, []).extend(floor["_bins"])
    seen = set()
    rooms = compile_program(brief)
    for room in rooms:
        if room["requirement_id"] in seen:
            continue
        seen.add(room["requirement_id"])
        eligible = room.get("allowed_floors") or list(slots)
        available = [slot for index in eligible for slot in slots.get(index, [])]
        fits = False
        for slot in available:
            template = fit_template(room, slot["width"], False)
            if template and slot["y"] + template["depth"] + PARTITION <= slot["end"] + EPS:
                fits = True
                break
        if not fits:
            issues.append({"code": "room_fit_deficit", "requirement_id": room["requirement_id"],
                           "label": room["name"], "required_capacity": room["required_capacity"],
                           "detail": f"{room['name']}: the requested size or capacity will not fit on an eligible floor."})
    ground_rooms = [room for room in rooms if room.get("allowed_floors") == [0]]
    ground_area = sum(estimated_area(room) for room in ground_rooms)
    if ground_area > result["buildable_area_m2"] * .7:
        issues.append({"code": "estimated_ground_floor_deficit",
                       "detail": f"Ground-floor rooms need about {ground_area:.0f} m²; about {result['buildable_area_m2'] * .7:.0f} m² is available after circulation. Extra floors cannot move rooms fixed to Ground."})
    if counts and result["min_floors"] > max(counts):
        issues.append({"code": "estimated_area_deficit", "detail": f"About {result['min_floors']} floors are needed; at most {max(counts)} fit the floor and height limits."})
    if not counts:
        issues.append({"code": "height_bound", "detail": "The height limit leaves no available floor."})
    result["preflight_issues"] = issues
    result["preflight_summary"] = " ".join(item["detail"] for item in issues[:2]) or "No individual room conflicts found. Overall layout and routes are checked during generation."
    return result
