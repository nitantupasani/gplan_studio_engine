"""Arithmetic validation of the structural input fixtures.

Raw JSON only: these files are the adapters' inputs, so nothing here may import
the adapters (a fixture that only agrees with the code it feeds proves nothing).
Every check recomputes the geometry from the coordinates in the file.
"""

from __future__ import annotations

import json
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# Door-width floor the engine uses when deciding a shared wall is passable.
MIN_DOOR_FT = 2.8


def _load(name):
    with open(os.path.join(FIXTURES, name), "r") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def plan():
    return _load("plan_2bhk.json")


@pytest.fixture(scope="module")
def plan_rooms(plan):
    return plan["response"]["Documents"]["floorPlans"][0]


def _rect(room):
    """(x0, y0, x1, y1) from circular_coordinates, min/max so winding is irrelevant."""
    xs = [p[0] for p in room["circular_coordinates"]]
    ys = [p[1] for p in room["circular_coordinates"]]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _shared_edge_ft(ra, rb):
    """Length of the wall segment two axis-aligned rectangles genuinely share."""
    ax0, ay0, ax1, ay1 = ra
    bx0, by0, bx1, by1 = rb
    best = 0.0
    if ax1 == bx0 or bx1 == ax0:
        best = max(best, _overlap(ay0, ay1, by0, by1))
    if ay1 == by0 or by1 == ay0:
        best = max(best, _overlap(ax0, ax1, bx0, bx1))
    return best


# --------------------------------------------------------------------------
# plan_2bhk.json
# --------------------------------------------------------------------------


def test_plan_envelope_is_a_full_door_connectivity_response(plan):
    assert plan["status"] == "SUCCESS"
    docs = plan["response"]["Documents"]
    for key in ("count", "floorPlans", "ptpg_graph", "adjacency_shortfalls", "plot_fit"):
        assert key in docs, "envelope is missing %s" % key
    assert docs["count"] == 1
    assert len(docs["floorPlans"]) == 1
    assert len(docs["floorPlans"][0]) == 8, "the 2BHK fixture is an 8 room plan"


def test_plan_carries_the_2bhk_program_under_stable_ids(plan_rooms):
    ids = [r["_id"] for r in plan_rooms]
    names = [r["name"] for r in plan_rooms]
    assert len(set(ids)) == len(ids), "duplicate room _id in %s" % ids
    assert len(set(names)) == len(names), "duplicate room name in %s" % names
    assert ids == ["r-living", "r-kitchen", "r-dining", "r-bed1", "r-bed2",
                   "r-bath", "r-toilet", "r-balcony"]
    assert names == ["Living Room", "Kitchen", "Dining", "Bedroom 1", "Bedroom 2",
                     "Bathroom", "Toilet", "Balcony"]
    for room in plan_rooms:
        assert room["color"] == "#1C4C82"
        assert room["assets"] == []


def test_plan_label_coord_is_the_room_centre(plan_rooms):
    for room in plan_rooms:
        x0, y0, x1, y1 = _rect(room)
        assert room["label_coord"] == [(x0 + x1) / 2.0, (y0 + y1) / 2.0], (
            "%s label_coord %s is not the centre of (%s, %s)-(%s, %s)"
            % (room["_id"], room["label_coord"], x0, y0, x1, y1))


def test_plan_declared_dims_match_the_loop(plan_rooms):
    for room in plan_rooms:
        x0, y0, x1, y1 = _rect(room)
        assert x1 - x0 == room["width"], "%s width %s vs loop %s" % (
            room["_id"], room["width"], x1 - x0)
        assert y1 - y0 == room["height"], "%s height %s vs loop %s" % (
            room["_id"], room["height"], y1 - y0)
        assert room["area"] == room["width"] * room["height"], (
            "%s area %s vs w*h %s" % (room["_id"], room["area"],
                                      room["width"] * room["height"]))


def test_plan_loops_are_axis_aligned_rectangles(plan_rooms):
    for room in plan_rooms:
        loop = room["circular_coordinates"]
        assert len(loop) == 4, "%s has %d vertices" % (room["_id"], len(loop))
        x0, y0, x1, y1 = _rect(room)
        assert loop == [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], (
            "%s loop is not the [tl, tr, br, bl] rectangle: %s" % (room["_id"], loop))


def test_plan_walls_close_each_rectangle(plan_rooms):
    for room in plan_rooms:
        loop = room["circular_coordinates"]
        walls = room["walls"]
        assert len(walls) == 4, "%s has %d walls" % (room["_id"], len(walls))
        for i, wall in enumerate(walls):
            a = loop[i]
            b = loop[(i + 1) % 4]
            assert [wall["x1"], wall["y1"]] == a, (
                "%s wall %d starts at (%s, %s), loop says %s"
                % (room["_id"], i, wall["x1"], wall["y1"], a))
            assert [wall["x2"], wall["y2"]] == b, (
                "%s wall %d ends at (%s, %s), loop says %s"
                % (room["_id"], i, wall["x2"], wall["y2"], b))
            assert wall["x1"] == wall["x2"] or wall["y1"] == wall["y2"], (
                "%s wall %d is not axis aligned" % (room["_id"], i))
        assert walls[-1]["x2"] == walls[0]["x1"] and walls[-1]["y2"] == walls[0]["y1"], (
            "%s wall run does not close" % room["_id"])


def test_plan_wall_ids_are_unique_across_the_plan(plan_rooms):
    ids = [w["_id"] for r in plan_rooms for w in r["walls"]]
    assert len(set(ids)) == len(ids) == 32, "expected 32 distinct wall ids, got %d/%d" % (
        len(set(ids)), len(ids))


def test_plan_rooms_do_not_overlap(plan_rooms):
    rects = [(r["_id"], _rect(r)) for r in plan_rooms]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            (ida, (ax0, ay0, ax1, ay1)) = rects[i]
            (idb, (bx0, by0, bx1, by1)) = rects[j]
            inter = _overlap(ax0, ax1, bx0, bx1) * _overlap(ay0, ay1, by0, by1)
            assert inter == 0, "%s and %s overlap by %s sqft" % (ida, idb, inter)


def test_plan_bbox_is_the_30x40_plot(plan_rooms):
    rects = [_rect(r) for r in plan_rooms]
    assert min(r[0] for r in rects) == 0.0
    assert min(r[1] for r in rects) == 0.0
    assert max(r[2] for r in rects) == 30.0
    assert max(r[3] for r in rects) == 40.0


def test_plan_is_gapless(plan_rooms):
    total = sum(r["area"] for r in plan_rooms)
    assert total == 30.0 * 40.0 == 1200.0, (
        "room areas sum to %s, the 30 x 40 bbox is 1200 sqft" % total)


def test_plan_plot_fit_matches_the_geometry(plan):
    fit = plan["response"]["Documents"]["plot_fit"][0]
    assert fit["fits"] is True
    assert fit["plan_width"] == fit["plot_width"] == 30.0
    assert fit["plan_height"] == fit["plot_height"] == 40.0
    assert fit["overflow_width"] == 0
    assert fit["overflow_height"] == 0


def test_plan_ptpg_graph_is_symmetric_with_a_zero_diagonal(plan, plan_rooms):
    graph = plan["response"]["Documents"]["ptpg_graph"]
    n = len(plan_rooms)
    assert len(graph) == n, "graph is %dx? for %d rooms" % (len(graph), n)
    for i, row in enumerate(graph):
        assert len(row) == n, "graph row %d has %d entries" % (i, len(row))
        assert row[i] == 0, "graph diagonal %d is %s" % (i, row[i])
        for j, v in enumerate(row):
            assert v in (0, 1), "graph[%d][%d] = %s is not 0/1" % (i, j, v)
            assert v == graph[j][i], "graph[%d][%d] != graph[%d][%d]" % (i, j, j, i)


def test_plan_ptpg_graph_matches_the_shared_walls(plan, plan_rooms):
    graph = plan["response"]["Documents"]["ptpg_graph"]
    rects = [_rect(r) for r in plan_rooms]
    ids = [r["_id"] for r in plan_rooms]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            run = _shared_edge_ft(rects[i], rects[j])
            expected = 1 if run >= MIN_DOOR_FT else 0
            assert graph[i][j] == expected, (
                "%s and %s share %s ft of wall, graph says %s (door floor %s ft)"
                % (ids[i], ids[j], run, graph[i][j], MIN_DOOR_FT))


def test_plan_adjacency_shortfalls_is_one_empty_list_per_plan(plan):
    docs = plan["response"]["Documents"]
    assert docs["adjacency_shortfalls"] == [[]]
    assert len(docs["adjacency_shortfalls"]) == len(docs["floorPlans"])


# --------------------------------------------------------------------------
# building_3storey.json
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def building():
    return _load("building_3storey.json")


def _boundary_extent(boundary):
    if boundary["kind"] == "rect":
        return (0.0, 0.0, float(boundary["width"]), float(boundary["height"]))
    xs = [p[0] for p in boundary["points"]]
    ys = [p[1] for p in boundary["points"]]
    return (min(xs), min(ys), max(xs), max(ys))


def _placed(item):
    return (float(item["x"]), float(item["y"]),
            float(item["x"]) + float(item["width"]),
            float(item["y"]) + float(item["height"]))


def _assert_inside(rect, extent, label):
    bx0, by0, bx1, by1 = extent
    x0, y0, x1, y1 = rect
    assert x0 >= bx0 and y0 >= by0 and x1 <= bx1 and y1 <= by1, (
        "%s spans (%s, %s)-(%s, %s), boundary is (%s, %s)-(%s, %s)"
        % (label, x0, y0, x1, y1, bx0, by0, bx1, by1))


def test_building_has_three_floors_matching_total_floors(building):
    assert building["totalFloors"] == 3
    assert len(building["floors"]) == 3, "floors carries %d entries" % len(building["floors"])
    assert [f["floorNumber"] for f in building["floors"]] == [0, 1, 2]
    assert [f["id"] for f in building["floors"]] == ["fl-0", "fl-1", "fl-2"]


def test_building_ground_floor_is_an_empty_stilt(building):
    ground = building["floors"][0]
    assert ground["kind"] == "stilt"
    assert ground["units"] == []
    assert ground["parking"] == []
    assert ground["corridors"] == []


def test_building_upper_floors_repeat_the_same_two_units(building):
    upper = [f for f in building["floors"] if f["kind"] == "units"]
    assert len(upper) == 2
    assert upper[0]["units"] == upper[1]["units"], "the typical floors are not identical"
    for floor in upper:
        assert [u["id"] for u in floor["units"]] == ["u-a", "u-b"]
        for unit in floor["units"]:
            assert unit["width"] == 30 and unit["height"] == 40, (
                "%s is %sx%s, expected 30x40" % (unit["id"], unit["width"], unit["height"]))
            assert unit["rotation"] in (0, 90, 180, 270)
            assert unit["spaces"] == [] and unit["floorplans"] == [], (
                "%s is meant to be undressed" % unit["id"])
            assert unit["activeFloorplanIndex"] == 0


def test_building_units_are_inside_the_boundary(building):
    extent = _boundary_extent(building["boundary"])
    for floor in building["floors"]:
        for unit in floor["units"]:
            _assert_inside(_placed(unit), extent, "%s/%s" % (floor["id"], unit["id"]))


def test_building_units_do_not_overlap_each_other(building):
    for floor in building["floors"]:
        units = floor["units"]
        for i in range(len(units)):
            for j in range(i + 1, len(units)):
                a = _placed(units[i])
                b = _placed(units[j])
                inter = _overlap(a[0], a[2], b[0], b[2]) * _overlap(a[1], a[3], b[1], b[3])
                assert inter == 0, "%s: %s and %s overlap by %s sqft" % (
                    floor["id"], units[i]["id"], units[j]["id"], inter)


def test_building_fixed_elements_are_inside_the_boundary_and_disjoint(building):
    extent = _boundary_extent(building["boundary"])
    elements = building["fixedElements"]
    assert [e["id"] for e in elements] == ["fe-stair", "fe-lift"]
    assert elements[0]["type"] == "staircase" and elements[1]["type"] == "lift"
    for element in elements:
        _assert_inside(_placed(element), extent, element["id"])
    a = _placed(elements[0])
    b = _placed(elements[1])
    inter = _overlap(a[0], a[2], b[0], b[2]) * _overlap(a[1], a[3], b[1], b[3])
    assert inter == 0, "the stair and the lift overlap by %s sqft" % inter


def test_building_cores_clear_every_unit(building):
    for element in building["fixedElements"]:
        core = _placed(element)
        for floor in building["floors"]:
            for unit in floor["units"]:
                r = _placed(unit)
                inter = (_overlap(core[0], core[2], r[0], r[2])
                         * _overlap(core[1], core[3], r[1], r[3]))
                assert inter == 0, "%s overlaps %s/%s by %s sqft" % (
                    element["id"], floor["id"], unit["id"], inter)


def test_building_corridor_is_inside_the_boundary_and_clears_the_units(building):
    extent = _boundary_extent(building["boundary"])
    for floor in building["floors"]:
        for corridor in floor["corridors"]:
            rect = _placed(corridor)
            _assert_inside(rect, extent, "%s/%s" % (floor["id"], corridor["id"]))
            assert corridor["role"] == "spine"
            for unit in floor["units"]:
                r = _placed(unit)
                inter = (_overlap(rect[0], rect[2], r[0], r[2])
                         * _overlap(rect[1], rect[3], r[1], r[3]))
                assert inter == 0, "%s overlaps %s by %s sqft" % (
                    corridor["id"], unit["id"], inter)


# --------------------------------------------------------------------------
# housing_2storey.json
#
# regionContent keys in a real HousingDesign come from the frontend's
# regionKey(points) over the DERIVED faces, and the adapter matches content by
# resolved_regions rather than by parsing the key. The key here is written in
# that normalized "x,y;x,y;..." form so the shape is realistic; the checks below
# only exercise arithmetic the fixture can be held to on its own.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def housing():
    return _load("housing_2storey.json")


def _fmt(value):
    f = float(value)
    return str(int(f)) if f == int(f) else repr(f)


def _loop_key(points):
    return ";".join("%s,%s" % (_fmt(p[0]), _fmt(p[1])) for p in points)


def _parse_loop_key(key):
    out = []
    for part in key.split(";"):
        x, y = part.split(",")
        out.append([float(x), float(y)])
    return out


def _assert_rectilinear_loop(points, label):
    assert len(points) >= 4 and len(points) % 2 == 0, (
        "%s has %d vertices; a rectilinear loop has an even count of at least 4"
        % (label, len(points)))
    n = len(points)
    for i in range(n):
        a = points[i]
        b = points[(i + 1) % n]
        horizontal = a[1] == b[1]
        vertical = a[0] == b[0]
        assert horizontal != vertical, (
            "%s edge %d (%s -> %s) is diagonal or degenerate" % (label, i, a, b))
        c = points[(i + 2) % n]
        nxt_horizontal = b[1] == c[1]
        assert nxt_horizontal != horizontal, (
            "%s edge %d does not turn at %s" % (label, i, b))


def _on_segment(p, a, b):
    """Point p lies on the axis-aligned segment a-b (endpoints included)."""
    if a[0] == b[0] == p[0]:
        return min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    if a[1] == b[1] == p[1]:
        return min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
    return False


def _covered_by(edge, carriers):
    a, b = edge
    return any(_on_segment(a, c[0], c[1]) and _on_segment(b, c[0], c[1])
               for c in carriers)


def test_housing_shell(housing):
    assert housing["id"] == "hd-fx1"
    assert housing["name"] == "Fixture House"
    assert housing["roof"] == "gable"
    assert housing["createdAt"] == "2026-08-29T00:00:00Z"
    assert housing["wallDisplay"]["showInteriorWalls"] is True
    assert 0.0 < housing["wallDisplay"]["interiorWallFt"] < 1.0
    assert [f["level"] for f in housing["floors"]] == [0, 1]
    assert [f["label"] for f in housing["floors"]] == ["Ground", "First"]
    assert [f["id"] for f in housing["floors"]] == ["hf-ground", "hf-first"]


def test_housing_boundaries_are_closed_rectilinear_loops(housing):
    for floor in housing["floors"]:
        _assert_rectilinear_loop(floor["boundary"], "%s boundary" % floor["id"])
    ground, first = housing["floors"]
    assert ground["boundary"] == first["boundary"], "the plot changes between floors"
    assert ground["boundary"] == [[0, 0], [30, 0], [30, 40], [0, 40]]


def test_housing_entry_sits_on_the_ground_boundary(housing):
    loop = housing["floors"][0]["boundary"]
    entry = housing["entry"]
    n = len(loop)
    hits = [i for i in range(n) if _on_segment(entry, loop[i], loop[(i + 1) % n])]
    assert hits, "entry %s is not on the ground boundary %s" % (entry, loop)


def test_housing_segments_are_axis_aligned_and_inside_the_boundary(housing):
    ground = housing["floors"][0]
    xs = [p[0] for p in ground["boundary"]]
    ys = [p[1] for p in ground["boundary"]]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    assert len(ground["segments"]) == 3
    assert [s["id"] for s in ground["segments"]] == ["seg-h1", "seg-v1", "seg-v2"]
    for seg in ground["segments"]:
        horizontal = seg["y1"] == seg["y2"]
        vertical = seg["x1"] == seg["x2"]
        assert horizontal != vertical, "%s is diagonal or degenerate" % seg["id"]
        for x in (seg["x1"], seg["x2"]):
            assert bx0 <= x <= bx1, "%s runs to x=%s, plot is %s..%s" % (
                seg["id"], x, bx0, bx1)
        for y in (seg["y1"], seg["y2"]):
            assert by0 <= y <= by1, "%s runs to y=%s, plot is %s..%s" % (
                seg["id"], y, by0, by1)
    assert housing["floors"][1]["segments"] == [], "the first floor draws no walls"


def test_housing_cores_are_identical_across_floors(housing):
    cores = {}
    for floor in housing["floors"]:
        shaped = [s for s in floor["shapes"] if "core" in s]
        assert len(shaped) == 1, "%s carries %d core shapes" % (floor["id"], len(shaped))
        shape = shaped[0]
        cores[floor["id"]] = shape
        _assert_rectilinear_loop(shape["points"], "%s core" % floor["id"])
    ground = cores["hf-ground"]
    first = cores["hf-first"]
    assert ground["core"]["id"] == first["core"]["id"] == "core-stairs"
    assert ground["core"]["kind"] == first["core"]["kind"] == "stairs"
    assert ground["points"] == first["points"], (
        "core footprints differ: %s vs %s" % (ground["points"], first["points"]))
    assert ground["id"] != first["id"], "the two copies share a shape id"


def test_housing_core_is_inside_the_plot(housing):
    loop = housing["floors"][0]["boundary"]
    bx0 = min(p[0] for p in loop)
    bx1 = max(p[0] for p in loop)
    by0 = min(p[1] for p in loop)
    by1 = max(p[1] for p in loop)
    for floor in housing["floors"]:
        for shape in floor["shapes"]:
            for x, y in shape["points"]:
                assert bx0 <= x <= bx1 and by0 <= y <= by1, (
                    "%s/%s vertex (%s, %s) is outside the plot"
                    % (floor["id"], shape["id"], x, y))


def test_housing_region_key_is_a_normalized_rectilinear_loop(housing):
    content = housing["floors"][0]["regionContent"]
    assert len(content) == 1, "the ground floor carries %d region entries" % len(content)
    key = list(content)[0]
    points = _parse_loop_key(key)
    _assert_rectilinear_loop(points, "region %s" % key)
    assert _loop_key(points) == key, "%s is not in normalized form" % key
    assert housing["floors"][1]["regionContent"] == {}


def test_housing_region_edges_lie_on_drawn_walls(housing):
    """Every edge of the content-carrying region is boundary or a drawn segment."""
    ground = housing["floors"][0]
    loop = ground["boundary"]
    carriers = [(loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))]
    carriers += [([s["x1"], s["y1"]], [s["x2"], s["y2"]]) for s in ground["segments"]]
    points = _parse_loop_key(list(ground["regionContent"])[0])
    n = len(points)
    for i in range(n):
        edge = (points[i], points[(i + 1) % n])
        assert _covered_by(edge, carriers), (
            "region edge %s -> %s is not carried by the boundary or a segment"
            % (edge[0], edge[1]))


def test_housing_region_bbox_matches_the_generated_size(housing):
    ground = housing["floors"][0]
    key = list(ground["regionContent"])[0]
    points = _parse_loop_key(key)
    generated = ground["regionContent"][key]["generated"]
    width = max(p[0] for p in points) - min(p[0] for p in points)
    height = max(p[1] for p in points) - min(p[1] for p in points)
    assert width == generated["genW"], "region is %s wide, genW is %s" % (
        width, generated["genW"])
    assert height == generated["genH"], "region is %s tall, genH is %s" % (
        height, generated["genH"])


def test_housing_generated_block_resolves_its_selected_plan(housing):
    ground = housing["floors"][0]
    generated = list(ground["regionContent"].values())[0]["generated"]
    assert generated["requestedType"] == generated["builtType"] == "1BHK"
    plans = generated["plans"]
    assert len(plans) == 1
    plan_ids = [p["id"] for p in plans]
    assert generated["selectedPlanId"] in plan_ids, (
        "selectedPlanId %s is not one of %s" % (generated["selectedPlanId"], plan_ids))
    plan = plans[0]
    assert plan["floorWidth"] == generated["genW"]
    assert plan["floorHeight"] == generated["genH"]


def test_housing_placements_tile_the_generated_polygon_exactly(housing):
    ground = housing["floors"][0]
    generated = list(ground["regionContent"].values())[0]["generated"]
    plan = generated["plans"][0]
    placements = plan["placements"]
    assert len(placements) == 4, "expected 4 rooms, got %d" % len(placements)
    total = sum(p["width"] * p["height"] for p in placements)
    assert total == generated["genW"] * generated["genH"], (
        "placements cover %s sqft, the %sx%s polygon is %s sqft"
        % (total, generated["genW"], generated["genH"],
           generated["genW"] * generated["genH"]))
    rects = [_placed(p) for p in placements]
    assert min(r[0] for r in rects) == 0 and min(r[1] for r in rects) == 0
    assert max(r[2] for r in rects) == generated["genW"]
    assert max(r[3] for r in rects) == generated["genH"]


def test_housing_placements_do_not_overlap(housing):
    ground = housing["floors"][0]
    generated = list(ground["regionContent"].values())[0]["generated"]
    placements = generated["plans"][0]["placements"]
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            a = _placed(placements[i])
            b = _placed(placements[j])
            inter = _overlap(a[0], a[2], b[0], b[2]) * _overlap(a[1], a[3], b[1], b[3])
            assert inter == 0, "%s and %s overlap by %s sqft" % (
                placements[i]["name"], placements[j]["name"], inter)
