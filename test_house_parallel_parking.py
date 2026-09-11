"""Real three-bedroom house search and independent frontage-parking gates."""
from copy import deepcopy

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from GPLAN.housing.concepts import enumerate_site_envelopes, generate_house_concepts
from GPLAN.housing.programs import get_profile
from GPLAN.housing.schema import normalize_request
from GPLAN.housing.validation import validate_house_candidate


def request(front=0):
    width, depth = (9754, 12192) if front % 2 == 0 else (12192, 9754)
    return {"schema_version": "house_concepts_v1", "units": "mm",
            "plot": {"polygon": [[0, 0], [width, 0], [width, depth], [0, depth]], "front_edge": front},
            "storeys": {"mode": "g+1_attic", "allow": ["g+1_attic"]},
            "household": {"bedrooms": 3}, "parking": {"preference": "front", "cars": 1},
            "walls": {"interior_mm": 102, "exterior_mm": 152},
            "setbacks": {"front_mm": 0, "side_mm": 0, "rear_mm": 0},
            "search": {"budget_ms": 30000}, "requested_options": 5}


@pytest.fixture(scope="module")
def catalogue():
    result = generate_house_concepts(request())
    assert len(result["options"]) == 5, result["rejections"]
    return result


def test_original_three_bedroom_front_parking_brief_keeps_all_hard_room_constraints(catalogue):
    normalized = normalize_request(request())
    for option in catalogue["options"]:
        assert option["differences"]["parking"] == "parallel"
        assert [floor["role"] for floor in option["floors"]] == ["ground", "first", "attic"]
        assert option["metrics"]["bedrooms"] == 3
        assert all(floor["solver"]["hard_bounds_relaxed"] is False for floor in option["floors"])
        report = validate_house_candidate(option, normalized, get_profile())
        assert report["valid"], report["violations"]
        assert "vehicle_manoeuvring" in report["not_assessed"]
        site = option["site"]
        bay = next(space for space in site["spaces"] if space["role"] == "parking_bay")
        bay_shape = Polygon(bay["polygon"])
        x0, y0, x1, y1 = bay_shape.bounds
        assert (x1 - x0, y1 - y0) == (5200, 2600)
        assert bay["orientation"] == "parallel"
        assert site["parking_access_status"] == "frontage_access_envelope_reserved"
        walk = unary_union([Polygon(space["polygon"]) for space in site["spaces"] if space["role"] == "pedestrian_access"])
        assert walk.intersection(Polygon(bay["car_polygon"])).area == 0
        assert walk.distance(bay_shape) == 0


@pytest.mark.parametrize("front", [1, 2, 3])
def test_parallel_bay_rotates_with_requested_frontage(front):
    raw = request(front)
    raw["requested_options"] = 1
    result = generate_house_concepts(raw)
    assert len(result["options"]) == 1, result["rejections"]
    option = result["options"][0]
    bay = next(space for space in option["site"]["spaces"] if space["role"] == "parking_bay")
    x0, y0, x1, y1 = Polygon(bay["polygon"]).bounds
    assert (x1 - x0, y1 - y0) == ((2600, 5200) if front % 2 else (5200, 2600))
    report = validate_house_candidate(option, normalize_request(raw), get_profile())
    assert report["valid"], report["violations"]


@pytest.mark.parametrize("damage, expected", [
    ("short_bay", ".fit"), ("thin_bay", ".fit"), ("wrong_orientation", ".orientation"),
    ("blocked_frontage", ".frontage_vehicle_access"), ("car_in_path", "site.pedestrian_unblocked"),
    ("building_overlap", ".building_overlap"), ("false_approach_claim", ".access_status"),
])
def test_parallel_parking_and_access_are_measured_independently(catalogue, damage, expected):
    option = deepcopy(catalogue["options"][0])
    site = option["site"]
    bay = next(space for space in site["spaces"] if space["role"] == "parking_bay")
    drive = next(space for space in site["spaces"] if space["role"] == "vehicle_access")
    path = next(space for space in site["spaces"] if space["role"] == "pedestrian_access")
    x0, y0, x1, y1 = Polygon(bay["polygon"]).bounds
    points = lambda shape: [list(point) for point in list(shape.exterior.coords)[:-1]]
    if damage == "short_bay":
        bay["polygon"] = points(box(x0, y0, x0 + 4900, y1))
    elif damage == "thin_bay":
        bay["polygon"] = points(box(x0, y0, x1, y0 + 2400))
    elif damage == "wrong_orientation":
        bay["orientation"] = "diagonal"
    elif damage == "blocked_frontage":
        drive["polygon"] = points(Polygon(drive["polygon"]).intersection(box(0, 50, 20000, 20000)))
    elif damage == "car_in_path":
        path["polygon"] = points(Polygon(path["polygon"]).union(Polygon(bay["polygon"])))
    elif damage == "building_overlap":
        bay["polygon"] = points(box(x0, y0, x1, Polygon(site["footprint"]).bounds[1] + 100))
    elif damage == "false_approach_claim":
        site["parking_access_status"] = "straight_clear_approach_reserved"
    report = validate_house_candidate(option, normalize_request(request()), get_profile())
    assert not report["valid"]
    assert any(expected in violation["id"] for violation in report["violations"]), report["violations"]


def test_parallel_search_preserves_existing_order_and_does_not_drop_required_parking():
    raw = request()
    envelopes = enumerate_site_envelopes(normalize_request(raw))
    modes = [item["parking_mode"] for item in envelopes]
    assert "parallel" in modes and modes.index("parallel") > modes.index("front_access_side")
    raw["plot"]["polygon"] = [[0, 0], [6500, 0], [6500, 12192], [0, 12192]]
    result = generate_house_concepts(raw)
    assert result["options"] == []
    assert any("infeasible" in rejection["reason"] for rejection in result["rejections"])
