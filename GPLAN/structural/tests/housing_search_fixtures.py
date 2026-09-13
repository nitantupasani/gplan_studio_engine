"""Small, explicit Housing inputs for production column-search acceptance."""
from copy import deepcopy


def rect(x, y, width, height):
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def content(level, width=24, height=24, detailed=False, recess=False, openings=False):
    rooms = []
    names = ["Living Room", "Kitchen", "Bedroom", "Bedroom 2"]
    for y in range(0, height, 12):
        for x in range(0, width, 12):
            if recess and x == 12 and y == 12:
                continue
            index = len(rooms)
            rooms.append({"id": "room-%d" % index, "name": names[index],
                          "kind": "kitchen" if index == 1 else "bedroom" if index > 1 else "living",
                          "x": x, "y": y, "width": 12, "height": 12})
    plan = {"id": "plan-%d" % level, "label": "Floor %d" % level,
            "floorWidth": width, "floorHeight": height,
            "placements": [{k: r[k] for k in ("name", "x", "y", "width", "height")} for r in rooms]}
    if detailed:
        plan["detailedPlan"] = {
            "id": "detail-%d" % level, "source": "api", "width": width, "height": height,
            "exteriorWall": 0.75, "interiorWall": 1 / 3, "rooms": rooms,
            "doors": ([{"id": "door-middle", "orientation": "v", "x": 12, "y": 6, "width": 3}]
                      if openings else []),
            "windows": ([{"id": "window-north", "orientation": "h", "x": 18, "y": 0,
                          "width": 4, "sillFt": 3, "headFt": 7}] if openings else []),
            "furniture": [],
        }
    return {"generated": {"requestedType": "custom", "builtType": "custom",
                          "selectedPlanId": plan["id"], "genW": width, "genH": height,
                          "plans": [plan]}}


CASE_NAMES = (
    "regular_generated_2", "detailed_openings_2", "l_recess_detailed_1",
    "stair_southwest_2", "stair_northeast_2", "mixed_carriers_3", "stepped_outline_3",
)


def housing_case(name):
    if name not in CASE_NAMES:
        raise ValueError(name)
    storeys = int(name.rsplit("_", 1)[1])
    floors = []
    for level in range(storeys):
        width, height = 24, 24
        if name == "stepped_outline_3" and level > 0:
            width, height = (24, 12) if level == 1 else (12, 12)
        recess = name == "l_recess_detailed_1"
        boundary = [[0, 0], [24, 0], [24, 12], [12, 12], [12, 24], [0, 24]] if recess else rect(0, 0, width, height)
        detail = name in ("detailed_openings_2", "l_recess_detailed_1") or (name == "mixed_carriers_3" and level == 1)
        floor = {"id": "floor-%d" % level, "level": level, "label": "Floor %d" % level,
                 "boundary": boundary, "segments": [], "plots": [], "regionContent": {}, "shapes": [],
                 "boundaryContent": content(level, width, height, detail, recess, name == "detailed_openings_2")}
        if name.startswith("stair_"):
            x, y = (0, 0) if "southwest" in name else (18, 16)
            floor["shapes"] = [{"id": "stairs-%d" % level, "points": rect(x, y, 6, 8),
                                 "core": {"id": "stairs", "kind": "stairs"}}]
        floors.append(floor)
    return {"id": name, "name": name.replace("_", " "), "floors": floors,
            "wallDisplay": {"showInteriorWalls": True, "interiorWallFt": 1 / 3},
            "roof": "flat", "entry": [6, 0], "createdAt": "2026-09-05T00:00:00Z"}


def design_request(name, variant="balanced"):
    return {"source": "housing", "housing": deepcopy(housing_case(name)), "plot_id": "primary",
            "params": {"system": "rc_frame", "analysis_mode": "gravity_only",
                       "placement_strategy": "wall_aligned", "housing_column_variant": variant,
                       "spans": {"min_m": 2.5, "max_m": 5.0}},
            "output": {"detail": "compact", "include_boq": True,
                       "include_quantities": True, "include_report": True}}
