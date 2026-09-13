"""Independent whole-house geometry acceptance and invalid-mutation tests.

The golden house below is hand-dimensioned.  It does not call a room solver or
the validation face/roof helpers to construct its expected geometry.  Mutations
exercise final output, including metadata that a repair or adapter could alter.

Run from the engine repository, preloading the inner package because this
repository also has an outer GPLAN package marker::

    python -c "import GPLAN.housing, pytest; raise SystemExit(pytest.main(['-q', '--import-mode=importlib', 'test_house_concepts_validation.py']))"
"""
from copy import deepcopy
import math
import os
import sys

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.housing.programs import get_profile
from GPLAN.housing.validation import (
    clear_face_polygon, largest_usable_rectangle, polygon_area_m2,
    roof_height_mm, roof_height_zone, roof_vertical_clearance_deduction_mm,
    room_circulation_fits, modeled_stair_footprints, validate_house_candidate,
)


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def points(geometry):
    return [list(point) for point in list(geometry.exterior.coords)[:-1]]


def room(floor, role, polygon, face, suffix=None):
    shape = Polygon(face)
    x0, y0, x1, y1 = shape.bounds
    return {
        "id": floor + ":" + (suffix or role), "role": role, "kind": role,
        "name": "Translated display name " + (suffix or role), "polygon": polygon,
        "clear_polygon": face, "clear_area_m2": shape.area / 1e6,
        "area_m2": Polygon(polygon).area / 1e6, "dimension_basis": "overall",
        "clear_width_mm": x1 - x0, "clear_depth_mm": y1 - y0,
    }


def door(floor, identifier, source, target, segment, kind="door", external_role=None):
    result = {"id": floor + ":door:" + identifier, "kind": kind,
              "from_room_id": floor + ":" + source,
              "to_room_id": floor + ":" + target if target else None, "segment": segment}
    if external_role:
        result["external_role"] = external_role
    return result


def window(floor, role, segment):
    return {"id": floor + ":window:" + role, "room_id": floor + ":" + role,
            "segment": segment, "sill_mm": 900, "height_mm": 1200}


def valid_fixture():
    request = {
        "schema_version": "house_concepts_v1", "units": "mm", "programme_profile": "NL_concept_v1",
        "plot": {"polygon": rect(0, 0, 11000, 22000), "front_edge": 0},
        "parking": {"preference": "front", "cars": 1},
        "storeys": {"mode": "g+1_attic", "allow": ["g+1_attic", "g+2_attic"]},
        "household": {"bedrooms": 2, "bathroom_wc": "combined"},
        "walls": {"interior_mm": 100, "exterior_mm": 200},
        "roof": {"type": "gable", "pitch_deg": 45, "overhang_mm": 300, "thickness_mm": 180},
        "setbacks": {"front_mm": 1000, "side_mm": 300, "rear_mm": 1200},
    }
    footprint = rect(1000, 6000, 9500, 15500)
    stair = rect(1000, 6000, 3250, 10250)
    stair_face = rect(1200, 6200, 3200, 10200)
    platform = rect(1200, 9200, 3200, 10200)
    opening = rect(1200, 6200, 3200, 9200)
    arrival = rect(2200, 9200, 3200, 10200)
    core = {
        "id": "main_stair", "kind": "stairs", "form": "u_return", "orientation": 0,
        "polygon": stair, "width_mm": 2250, "depth_mm": 4250,
        "opening_polygon": opening, "arrival_polygon": arrival,
        "platform_polygon": platform, "top_platform_depth_mm": 1000,
        "flight_count": 2, "flight_width_mm": 900, "well_width_mm": 200,
        "landing_depth_mm": 1000, "riser_count": 18, "riser_height_mm": 3000 / 18,
        "going_mm": 250, "floor_height_mm": 3000, "slab_thickness_mm": 200,
        "service_zone": rect(2000, 10750, 2100, 10850),
    }
    floors = []
    ground_rooms = [
        room("ground", "stair", stair, stair_face),
        room("ground", "entrance", rect(3250, 6000, 4650, 12000), rect(3300, 6200, 4600, 11950)),
        room("ground", "wc", rect(1000, 10250, 3250, 12000), rect(1200, 10300, 3200, 11950)),
        room("ground", "kitchen", rect(4650, 6000, 9500, 12000), rect(4700, 6200, 9300, 11950)),
        room("ground", "living", rect(1000, 12000, 9500, 15500), rect(1200, 12050, 9300, 15300)),
    ]
    ground_doors = [
        door("ground", "entrance", "entrance", None, [[3500, 6000], [4400, 6000]], external_role="entrance"),
        door("ground", "stair", "stair", "entrance", [[3250, 9250], [3250, 10150]]),
        door("ground", "wc", "entrance", "wc", [[3250, 10750], [3250, 11650]]),
        door("ground", "living", "entrance", "living", [[3500, 12000], [4400, 12000]]),
        door("ground", "kitchen", "entrance", "kitchen", [[4650, 6700], [4650, 7700]], "opening"),
        door("ground", "open_plan", "living", "kitchen", [[6000, 12000], [7000, 12000]], "opening"),
    ]
    floors.append({"id": "ground", "role": "ground", "rooms": ground_rooms, "doors": ground_doors,
                   "circulation_root_room_id": "ground:entrance", "windows": [
                       window("ground", "kitchen", [[6000, 6000], [7200, 6000]]),
                       window("ground", "living", [[5000, 15500], [6500, 15500]])]})
    first_rooms = [
        room("first", "stair", stair, stair_face),
        room("first", "landing", rect(3250, 6000, 4650, 15500), rect(3300, 6200, 4600, 15300)),
        room("first", "bathroom_wc", rect(1000, 10250, 3250, 15500), rect(1200, 10300, 3200, 15300)),
        room("first", "bedroom", rect(4650, 6000, 9500, 10600), rect(4700, 6200, 9300, 10550), "bedroom_1"),
        room("first", "bedroom", rect(4650, 10600, 9500, 15500), rect(4700, 10650, 9300, 15300), "bedroom_2"),
    ]
    floors.append({"id": "first", "role": "first", "rooms": first_rooms,
                   "circulation_root_room_id": "first:landing", "doors": [
                       door("first", "stair", "stair", "landing", [[3250, 9250], [3250, 10150]]),
                       door("first", "bathroom", "landing", "bathroom_wc", [[3250, 12500], [3250, 13400]]),
                       door("first", "bedroom_1", "landing", "bedroom_1", [[4650, 8200], [4650, 9100]]),
                       door("first", "bedroom_2", "landing", "bedroom_2", [[4650, 12000], [4650, 12900]])],
                   "windows": [window("first", "bedroom_1", [[9500, 7500], [9500, 8700]]),
                               window("first", "bedroom_2", [[9500, 12500], [9500, 13700]])]})
    hobby = [[4650, 6000], [9500, 6000], [9500, 15500], [1000, 15500], [1000, 10250], [4650, 10250]]
    hobby_face = [[4700, 6200], [9300, 6200], [9300, 15300], [1200, 15300], [1200, 10300], [4700, 10300]]
    attic_rooms = [room("attic", "stair", stair, stair_face),
                   room("attic", "attic_landing", rect(3250, 6000, 4650, 10250), rect(3300, 6200, 4600, 10200)),
                   room("attic", "hobby", hobby, hobby_face)]
    qualified_area = 0
    for item in attic_rooms[1:]:
        threshold, left, right = (2100, 1480, 9020) if item["role"] == "attic_landing" else (2300, 1680, 8820)
        face = Polygon(item["clear_polygon"])
        occupied = face.intersection(box(left, 6000, right, 15500))
        low = face.difference(occupied)
        item.update({"occupied_min_height_mm": threshold, "occupied_zone": points(occupied),
                     "occupied_area_m2": occupied.area / 1e6,
                     "low_headroom_storage_polygons": [] if low.is_empty else
                     [points(p) for p in (list(low.geoms) if hasattr(low, "geoms") else [low])]})
        qualified_area += occupied.area / 1e6
    floors.append({"id": "attic", "role": "attic", "rooms": attic_rooms,
                   "circulation_root_room_id": "attic:attic_landing", "doors": [
                       door("attic", "stair", "stair", "attic_landing", [[3250, 9250], [3250, 10150]]),
                       door("attic", "hobby", "attic_landing", "hobby", [[3450, 10250], [4350, 10250]])],
                   "windows": [window("attic", "hobby", [[5000, 15500], [6500, 15500]])]})
    for level, floor in enumerate(floors):
        floor.update({"level": level, "label": floor["role"], "program_id": floor["role"] + "_NL_v1",
                      "height_mm": 1500 if floor["role"] == "attic" else 3000,
                      "elevation_mm": level * 3000, "has_outgoing_stair": level < 2,
                      "core_id": "main_stair", "stair_room_id": floor["id"] + ":stair",
                      "stair_orientation": 0, "stair_opening_polygon": deepcopy(opening),
                      "stair_platform_polygon": deepcopy(platform),
                      "stair_arrival_polygon": deepcopy(arrival)})
    walk = unary_union([box(3400, 0, 4500, 6000), box(3950, 2050, 7500, 3150)])
    spaces = [
        {"id": "front", "kind": "open", "role": "forecourt", "polygon": rect(0, 0, 11000, 6000)},
        {"id": "left", "kind": "open", "role": "forecourt", "polygon": rect(0, 6000, 1000, 15500)},
        {"id": "right", "kind": "open", "role": "forecourt", "polygon": rect(9500, 6000, 11000, 15500)},
        {"id": "parking", "kind": "parking", "role": "parking_bay", "polygon": rect(7500, 100, 10000, 5100),
         "car_polygon": rect(7800, 250, 9700, 4950)},
        {"id": "drive", "kind": "open", "role": "vehicle_access", "polygon": rect(7350, 0, 10150, 5100)},
        {"id": "walk", "kind": "open", "role": "pedestrian_access", "polygon": points(walk)},
        {"id": "garden", "kind": "green", "role": "garden", "polygon": rect(0, 15500, 11000, 22000)},
    ]
    roof = {"type": "gable", "pitch_deg": 45, "knee_wall_mm": 1500, "ridge_axis": "y",
            "overhang_mm": 300, "thickness_mm": 180, "base_elevation_mm": 6000,
            "ridge_height_mm": 12050, "headroom_zones": [
                {"min_height_mm": 2100, "polygon": rect(1480, 6000, 9020, 15500)},
                {"min_height_mm": 2300, "polygon": rect(1680, 6000, 8820, 15500)}]}
    option = {"id": "hand_drawn_reference", "units": "mm", "walls": deepcopy(request["walls"]),
              "site": {"plot_polygon": deepcopy(request["plot"]["polygon"]), "footprint": footprint,
                       "front_boundary": [[0, 0], [11000, 0]], "entrance_point": [3950, 6000], "spaces": spaces},
              "floors": floors, "cores": [core], "roof": roof,
              "metrics": {"plot_area_m2": 242.0, "footprint_area_m2": 80.75,
                          "regular_floor_area_m2": 161.5, "garden_area_m2": 71.5,
                          "regular_storeys": 2, "bedrooms": 2,
                          "attic_gross_area_m2": 80.75, "attic_headroom_qualified_area_m2": qualified_area}}
    return option, request, get_profile()


def violations(option, request, profile):
    result = validate_house_candidate(option, request, profile)
    assert not result["valid"], "The invalid mutation unexpectedly passed all hard gates."
    return {item["id"] for item in result["violations"]}


def mark_actual_party_wall_contact(option, request, profile):
    # The reference footprint is set back from the plot's east edge.  Move that
    # boundary onto the east house wall before declaring it a party wall.
    request["plot"]["polygon"] = rect(0, 0, 9500, 22000)
    option["site"]["plot_polygon"] = deepcopy(request["plot"]["polygon"])
    request["plot"]["party_wall_edges"] = [1]


def test_hand_drawn_complete_house_passes_independent_acceptance():
    option, request, profile = valid_fixture()
    result = validate_house_candidate(option, request, profile)
    assert result["valid"], result["violations"]
    assert not result["violations"]
    assert {check["status"] for check in result["checks"]} == {"passed", "not_assessed"}
    assert {"dutch_regulations", "vehicle_manoeuvring", "nen_area_measurement", "fire_safety"} <= set(result["not_assessed"])


def test_polygon_area_and_finished_faces_do_not_use_bounding_box_or_double_count_stair():
    option, request, profile = valid_fixture()
    result = validate_house_candidate(option, request, profile)
    assert result["valid"], result["violations"]
    measures = result["measurements"]
    assert measures["plot_area_m2"] == 242
    assert measures["footprint_area_m2"] == 80.75
    assert measures["regular_floor_area_m2"] == 161.5
    assert measures["gross_floor_area_m2"] == 242.25
    assert measures["garden_area_m2"] == 71.5
    assert 0 < measures["attic_headroom_qualified_area_m2"] < measures["attic_gross_area_m2"]
    attic = measures["floors"][-1]
    assert attic["stair_allocation_area_m2"] == 9.5625
    hobby = next(item for item in attic["rooms"] if item["role"] == "hobby")
    assert hobby["allocation_area_m2"] == 65.2375
    assert hobby["clear_area_m2"] == 59.36
    assert hobby["clear_area_m2"] < hobby["overall_width_mm"] * hobby["overall_depth_mm"] / 1e6
    assert polygon_area_m2([[0, 0], [4000, 0], [4000, 1000], [1000, 1000], [1000, 4000], [0, 4000]]) == 7


def test_wall_faces_use_full_exterior_half_interior_and_no_phantom_merged_wall():
    footprint = box(0, 0, 10000, 10000)
    face = clear_face_polygon(box(0, 0, 1500, 3000), footprint, 100, 200)
    assert face.bounds == (200, 200, 1450, 2950)
    assert face.area / 1e6 == 3.4375
    merged = Polygon([[0, 0], [4000, 0], [4000, 2000], [2000, 2000], [2000, 4000], [0, 4000]])
    face = clear_face_polygon(merged, footprint, 100, 200)
    assert face.area == 10_062_500
    assert largest_usable_rectangle(face).area == 6_562_500


@pytest.mark.parametrize("mutator,code", [
    (lambda o, r, p: o["floors"][0]["rooms"][0].__setitem__("polygon", rect(900,6000,3250,9250)), ".containment"),
    (lambda o, r, p: o["floors"][0]["rooms"][1].__setitem__("polygon", rect(3200, 6000, 4650, 11000)), ".overlap."),
    (lambda o, r, p: o["floors"][0]["rooms"].pop(), ".exact_coverage"),
    (lambda o, r, p: o["floors"][0]["rooms"][0]["polygon"][0].__setitem__(0, 1000.25), ".coordinates"),
    (lambda o, r, p: o["floors"][0]["rooms"][0].__setitem__("polygon", [[1000,6000],[3250,9250],[3250,6000],[1000,9250]]), ".simple"),
    (lambda o, r, p: o["floors"][0]["rooms"][2].__setitem__("role", "parking"), ".indoor_role"),
    (lambda o, r, p: o["site"]["spaces"].pop(), "site.residual_classification"),
    (lambda o, r, p: o["site"]["spaces"][-1].__setitem__("polygon", rect(0, 15000, 11000, 22000)), ".building_overlap"),
    (lambda o, r, p: r["setbacks"].__setitem__("side_mm", 1500), "site.setback."),
    (lambda o, r, p: o.__setitem__("units", "ft"), "contract.units"),
    (lambda o, r, p: o["walls"].__setitem__("exterior_mm", 100), "walls.request"),
    (lambda o, r, p: o["metrics"].__setitem__("regular_floor_area_m2", 242.0), "measurements.regular_floor_area_m2"),
])
def test_geometry_units_and_area_mutations_reject(mutator, code):
    option, request, profile = valid_fixture()
    mutator(option, request, profile)
    assert any(code in item for item in violations(option, request, profile))


def test_profile_bounds_apply_after_repair_and_do_not_trust_names_or_room_constraints():
    option, request, profile = valid_fixture()
    wc = option["floors"][0]["rooms"][2]
    wc["name"] = "Palace / luxury spa / translated alias"
    wc["constraints"] = {"min_width_mm": 1, "max_width_mm": 100000, "max_area_m2": 100000}
    profile["room_rules"]["wc"]["max_area_m2"] = 3.0
    assert "floor.ground.room.ground:wc.maximum_area" in violations(option, request, profile)
    profile["room_rules"]["wc"]["max_area_m2"] = 5.0
    profile["room_rules"]["wc"]["min_width_mm"] = 2100
    assert "floor.ground.room.ground:wc.minimum_dimensions" in violations(option, request, profile)


@pytest.mark.parametrize("mutator,code", [
    (lambda o, r, p: o["floors"][1]["doors"][2].__setitem__("segment", [[4600,8200],[4600,9100]]), ".contact"),
    (lambda o, r, p: o["floors"][1]["doors"][2].__setitem__("segment", [[4650,8200],[4650,9000]]), ".width"),
    (lambda o, r, p: o["floors"][1]["doors"][2].__setitem__("segment", [[4650,6000],[4650,6900]]), ".finished_clearance"),
    (lambda o, r, p: o["floors"][1]["doors"].pop(), ".circulation.connected"),
    (lambda o, r, p: o["floors"][1].__setitem__("circulation_root_room_id", "first:bedroom_1"), ".circulation.root"),
    (lambda o, r, p: o["floors"][0]["doors"][0].__setitem__("segment", [[3500,11000],[4400,11000]]), ".site_entry"),
    (lambda o, r, p: o["floors"][0]["doors"][-1].__setitem__("kind", "door"), ".programme.open_kitchen_living"),
    (lambda o, r, p: o["floors"][1]["windows"][0].__setitem__("segment", [[4650,7500],[4650,8700]]), ".exterior_contact"),
    (mark_actual_party_wall_contact, ".party_wall"),
    (lambda o, r, p: o["floors"][1]["windows"].pop(), ".exterior_window"),
])
def test_actual_openings_and_exposure_mutations_reject(mutator, code):
    option, request, profile = valid_fixture()
    mutator(option, request, profile)
    assert any(code in item for item in violations(option, request, profile))


def test_connected_room_graph_still_rejects_bedroom_through_route():
    option, request, profile = valid_fixture()
    first = option["floors"][1]
    first["doors"].pop()
    first["doors"].append(door("first", "private_transit", "bedroom_1", "bedroom_2", [[6000,10600],[6900,10600]]))
    report = validate_house_candidate(option, request, profile)
    assert not report["valid"]
    assert "floor.first.circulation.privacy" in {item["id"] for item in report["violations"]}
    assert next(check for check in report["checks"] if check["id"] == "floor.first.circulation.connected")["status"] == "passed"


def test_optional_garden_door_requires_an_actual_ground_level_garden():
    option, request, profile = valid_fixture()
    option["floors"][0]["doors"].append(door("ground", "garden", "living", None,
                                           [[7000,15500],[8000,15500]], external_role="garden"))
    assert validate_house_candidate(option, request, profile)["valid"]
    option["site"]["spaces"][-1]["role"] = "forecourt"
    option["site"]["spaces"][-1]["kind"] = "open"
    option["metrics"]["garden_area_m2"] = 0
    assert "floor.ground.door.ground:door:garden.garden_contact" in violations(option, request, profile)


@pytest.mark.parametrize("mutator,code", [
    (lambda o, r, p: o["site"]["spaces"][3].__setitem__("polygon", rect(7500,100,9800,5100)), ".fit"),
    (lambda o, r, p: o["site"]["spaces"][3].__setitem__("car_polygon", rect(6000,250,9700,4950)), ".car_fit"),
    (lambda o, r, p: o["site"]["spaces"][4].__setitem__("polygon", rect(7350,500,10150,5100)), ".straight_vehicle_approach"),
    (lambda o, r, p: o["site"]["spaces"][5].__setitem__("polygon", rect(3900,0,4500,6000)), "site.pedestrian_connectivity"),
    (lambda o, r, p: o["site"]["spaces"][5].__setitem__("polygon", points(unary_union([box(3400,0,4500,6000),box(3950,2050,8500,3150)]))), "site.pedestrian_unblocked"),
    (lambda o, r, p: o["site"]["spaces"][5].__setitem__("polygon", rect(3400,1000,4500,6000)), "site.pedestrian_connectivity"),
    (lambda o, r, p: r["plot"].__setitem__("front_edge", 2), "site.request_frontage"),
    (lambda o, r, p: r["parking"].__setitem__("cars", 2), "site.parking_count"),
])
def test_real_parking_and_pedestrian_access_mutations_reject(mutator, code):
    option, request, profile = valid_fixture()
    mutator(option, request, profile)
    assert any(code in item for item in violations(option, request, profile))


@pytest.mark.parametrize("mutator,code", [
    (lambda o, r, p: o["floors"][1].__setitem__("stair_orientation", 90), ".stairs.orientation"),
    (lambda o, r, p: o["floors"][1].__setitem__("stair_opening_polygon", rect(1050,6000,3250,9250)), ".stairs.opening_alignment"),
    (lambda o, r, p: o["floors"][1].__setitem__("stair_arrival_polygon", rect(2250,8100,3200,9100)), ".stairs.arrival_alignment"),
    (lambda o, r, p: o["floors"][1]["rooms"][0].__setitem__("polygon", rect(1000,6000,3300,9250)), ".stairs.coordinates"),
    (lambda o, r, p: o["cores"][0].__setitem__("riser_count", 17), "stairs.rise_count"),
    (lambda o, r, p: o["cores"][0].__setitem__("going_mm", 310), "stairs.physical_fit"),
    (lambda o, r, p: o["cores"][0].__setitem__("flight_width_mm", 1000), "stairs.physical_fit"),
    (lambda o, r, p: o["cores"][0].__setitem__("service_zone", rect(5000,7000,5100,7100)), "services.declared_alignment"),
    (lambda o, r, p: o["floors"][-1].__setitem__("has_outgoing_stair", True), ".stack.outgoing_stair"),
    (lambda o, r, p: o["floors"][1].__setitem__("elevation_mm", 2800), ".stack.elevation"),
    (lambda o, r, p: o["floors"][1].__setitem__("role", "second"), "stack.floor_order"),
    (lambda o, r, p: r["storeys"].__setitem__("mode", "g+2_attic"), "stack.requested_mode"),
    (lambda o, r, p: r["household"].__setitem__("bedrooms", 3), "programme.household_bedrooms"),
    (lambda o, r, p: r["household"].__setitem__("bathroom_wc", "separate"), ".programme.upper_wc"),
    (lambda o, r, p: r.__setitem__("locked_cores", [{"polygon":rect(4000,8000,6000,11000)}]), "constraints.authored_locks"),
])
def test_shared_stair_and_whole_house_programme_mutations_reject(mutator, code):
    option, request, profile = valid_fixture()
    mutator(option, request, profile)
    assert any(code in item for item in violations(option, request, profile))


@pytest.mark.parametrize("mutator,code", [
    (lambda o, r, p: o["roof"].__setitem__("knee_wall_mm", 500), "stairs.attic_arrival_headroom"),
    (lambda o, r, p: o["roof"].__setitem__("pitch_deg", 60), "roof.geometry"),
    (lambda o, r, p: o["roof"].__setitem__("ridge_axis", "x"), "roof.renderer_axis"),
    (lambda o, r, p: o["roof"].__setitem__("base_elevation_mm", 3000), "roof.base_elevation"),
    (lambda o, r, p: o["roof"].__setitem__("ridge_height_mm", 9999), "roof.ridge_elevation"),
    (lambda o, r, p: o["roof"]["headroom_zones"][0].__setitem__("polygon", o["site"]["footprint"]), ".geometry"),
    (lambda o, r, p: o["floors"][-1]["rooms"][-1].__setitem__("occupied_zone", o["floors"][-1]["rooms"][-1]["clear_polygon"]), ".attic.occupied_zone"),
    (lambda o, r, p: o["floors"][-1]["rooms"][-1].__setitem__("occupied_min_height_mm", 1000), ".attic.height_threshold"),
    (lambda o, r, p: o["floors"][-1]["rooms"][-1].__setitem__("low_headroom_storage_polygons", []), ".attic.storage_classification"),
    (lambda o, r, p: o["floors"][-1]["windows"][0].__setitem__("segment", [[9500,11000],[9500,12500]]), ".attic.window_gable"),
    (lambda o, r, p: o["floors"][-1]["windows"][0].__setitem__("height_mm", 5000), ".attic.window_headroom"),
])
def test_roof_planes_and_occupied_attic_mutations_reject(mutator, code):
    option, request, profile = valid_fixture()
    mutator(option, request, profile)
    assert any(code in item for item in violations(option, request, profile))


def test_roof_height_uses_span_axis_overhang_thickness_and_qualified_polygon():
    footprint = box(1000, 6000, 9500, 15500)
    roof = {"pitch_deg": 45, "knee_wall_mm": 1500, "ridge_axis": "y", "overhang_mm": 300, "thickness_mm": 180}
    assert roof_height_mm([1000, 6000], footprint, roof) == pytest.approx(1620)
    assert roof_height_mm([5250, 6000], footprint, roof) == pytest.approx(5870)
    assert roof_height_zone(footprint, roof, 2300).bounds == pytest.approx((1680, 6000, 8820, 15500))
    roof["ridge_axis"] = "x"
    assert roof_height_mm([1000, 6000], footprint, roof) == pytest.approx(1620)
    assert roof_height_zone(footprint, roof, 2300).bounds == pytest.approx((1000, 6680, 9500, 14820))


def test_steep_roof_clearance_accounts_for_normal_shell_thickness():
    roof = {"pitch_deg": 55, "knee_wall_mm": 1500, "ridge_axis": "y", "overhang_mm": 0, "thickness_mm": 180}
    actual_vertical_shell = 106.68 / math.cos(math.radians(55))
    assert actual_vertical_shell > 180
    assert roof_vertical_clearance_deduction_mm(roof) == pytest.approx(actual_vertical_shell)
    assert roof_height_mm([0, 0], box(0, 0, 8000, 10000), roof) == pytest.approx(1500 - actual_vertical_shell)
    roof["thickness_mm"] = 250
    assert roof_vertical_clearance_deduction_mm(roof) == 250


def test_merged_room_with_narrow_neck_has_no_usable_internal_route():
    from shapely.geometry import LineString
    left, right = box(0, 0, 3000, 3000), box(5000, 0, 8000, 3000)
    openings = [(LineString([[0, 1000], [0, 1900]]), 0),
                (LineString([[8000, 1000], [8000, 1900]]), 0)]
    pinched = unary_union([left, box(3000, 1400, 5000, 1600), right])
    assert pinched.geom_type == "Polygon"
    assert largest_usable_rectangle(pinched).area == 9e6
    assert not room_circulation_fits(pinched, openings, 850)
    accessible = unary_union([left, box(3000, 1050, 5000, 1950), right])
    assert room_circulation_fits(accessible, openings, 850)


def test_g_plus_two_is_three_regular_floors_and_one_attic():
    option, request, profile = valid_fixture()
    second = deepcopy(option["floors"][1])

    def rename(value):
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return value.replace("first", "second") if isinstance(value, str) else value

    second = rename(second)
    option["floors"].insert(2, second)
    for index, floor in enumerate(option["floors"]):
        floor.update({"level": index, "elevation_mm": index * 3000, "has_outgoing_stair": index < 3})
    request["storeys"]["mode"] = "g+2_attic"
    option["roof"].update({"base_elevation_mm": 9000, "ridge_height_mm": 15050})
    option["metrics"].update({"bedrooms": 4, "regular_storeys": 3, "regular_floor_area_m2": 242.25})
    result = validate_house_candidate(option, request, profile)
    assert result["valid"], result["violations"]
    assert result["measurements"]["gross_floor_area_m2"] == 323
    assert result["measurements"]["regular_storeys"] == 3
    assert len(result["measurements"]["floors"]) == 4


def test_door_on_a_real_shared_wall_still_cannot_arrive_mid_flight():
    option, request, profile = valid_fixture()
    false_arrival = rect(2200, 8200, 3200, 9200)
    option["cores"][0]["arrival_polygon"] = false_arrival
    for floor in option["floors"]:
        floor["stair_arrival_polygon"] = deepcopy(false_arrival)
        stair_door = next(item for item in floor["doors"] if item["id"].endswith(":stair"))
        stair_door["segment"] = [[3250, 8250], [3250, 9150]]
    result = validate_house_candidate(option, request, profile)
    assert not result["valid"]
    assert "stairs.arrival_clearance" in {item["id"] for item in result["violations"]}
    assert all(item["status"] == "passed" for item in result["checks"] if item["id"].endswith(".circulation.connected"))


def test_slab_opening_cannot_erase_the_level_top_platform():
    option, request, profile = valid_fixture()
    full_core = deepcopy(option["cores"][0]["polygon"])
    option["cores"][0]["opening_polygon"] = full_core
    for floor in option["floors"]:
        floor["stair_opening_polygon"] = deepcopy(full_core)
    assert "stairs.opening_geometry" in violations(option, request, profile)


def test_platform_is_required_and_its_depth_counts_in_the_true_stair_run():
    option, request, profile = valid_fixture()
    del option["cores"][0]["platform_polygon"]
    assert "stairs.platform.coordinates" in violations(option, request, profile)
    option, request, profile = valid_fixture()
    option["cores"][0]["top_platform_depth_mm"] = 1500
    assert "stairs.physical_fit" in violations(option, request, profile)


def test_rounding_spare_stays_before_turn_without_a_gap_at_the_top_platform():
    option, _, _ = valid_fixture()
    core = option["cores"][0]
    face = box(1152, 6152, 3199, 10199)
    core["platform_polygon"] = rect(1152, 9199, 3199, 10199)
    core["arrival_polygon"] = rect(2199, 9199, 3199, 10199)
    opening = box(1152, 6152, 3199, 9199)
    modeled = modeled_stair_footprints(core, face)
    assert modeled["upper"].bounds == (2252, 7199, 3152, 9199)
    assert modeled["turn"].bounds == (1152, 6199, 3152, 7199)
    assert modeled["turn"].bounds[1] - face.bounds[1] == 47
    assert all(opening.covers(polygon) for polygon in modeled.values())
    assert modeled["upper"].boundary.intersection(Polygon(core["platform_polygon"]).boundary).length == 900


@pytest.mark.parametrize("quarter_turns", [1, 2, 3])
def test_integer_world_geometry_validates_for_each_rotated_frontage(quarter_turns):
    option, request, profile = valid_fixture()
    polygon_keys = {"polygon", "plot_polygon", "footprint", "clear_polygon", "occupied_zone", "car_polygon",
                    "arrival_polygon", "opening_polygon", "service_zone", "stair_opening_polygon",
                    "stair_arrival_polygon", "platform_polygon", "stair_platform_polygon", "front_boundary", "segment"}

    def rotate(point):
        x, y = point
        for _ in range(quarter_turns):
            x, y = y, -x
        return [x, y]

    def transform(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in polygon_keys:
                    result[key] = [rotate(point) for point in item]
                elif key == "entrance_point":
                    result[key] = rotate(item)
                elif key == "low_headroom_storage_polygons":
                    result[key] = [[rotate(point) for point in polygon] for polygon in item]
                elif key in {"orientation", "stair_orientation"}:
                    result[key] = (item - quarter_turns * 90) % 360
                elif key == "ridge_axis" and quarter_turns % 2:
                    result[key] = "x" if item == "y" else "y"
                else:
                    result[key] = transform(item)
            return result
        return [transform(item) for item in value] if isinstance(value, list) else value

    result = validate_house_candidate(transform(option), transform(request), profile)
    assert result["valid"], result["violations"]


@pytest.mark.parametrize("bad", [None, [], 7, {"site": None}, {"site": {"plot_polygon": [[0, 0], [math.nan, 0], [1, 1], [0, 1]]}}])
def test_malformed_options_reject_without_aborting_search(bad):
    _, request, profile = valid_fixture()
    report = validate_house_candidate(bad, request, profile)
    assert report["valid"] is False
    assert report["violations"]
