"""Pins for adapters/plan_json.py and the shared adapters/_geom.py helpers.

The happy path is driven by the committed door_connectivity fixture, so the
numbers below are the fixture's real geometry, recomputed here rather than
copied from the adapter. The refusal cases are synthetic: each one breaks
exactly one rule the adapter is supposed to refuse on.
"""

from __future__ import annotations

import json
import os

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests.
from .. import model as M
from ..adapters import _geom as G
from ..adapters import plan_json as A
from ..adapters._geom import AdapterError

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

FT = M.FT

# The fixture is a 30 x 40 ft 2BHK: eight rooms, gapless, ptpg adjacency present.
PLAN_W_FT = 30.0
PLAN_H_FT = 40.0
ROOM_COUNT = 8

# Recomputed by hand from the fixture rectangles, not read back from the adapter.
EXTERIOR_WALLS = 11
INTERIOR_WALLS = 13
EXTERIOR_FT = 2.0 * (PLAN_W_FT + PLAN_H_FT)
INTERIOR_FT = 131.0
PTPG_EDGES = 13


def _load(name):
    with open(os.path.join(FIXTURES, name), "r") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def payload():
    return _load("plan_2bhk.json")


@pytest.fixture(scope="module")
def rooms(payload):
    return payload["response"]["Documents"]["floorPlans"][0]


@pytest.fixture(scope="module")
def model(payload):
    return A.from_plan(payload, storeys=2)


# ---------------------------------------------------------------------------
# synthetic plan builder for the refusal cases
# ---------------------------------------------------------------------------


def room(rid, name, x, y, w, h, **extra):
    """A minimal engine Room dict: rectangle, feet, y-down."""
    out = {
        "_id": rid,
        "name": name,
        "width": w,
        "height": h,
        "area": w * h,
        "circular_coordinates": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
    }
    out.update(extra)
    return out


def two_room_plan():
    return [room("a", "Bedroom 1", 0, 0, 10, 10), room("b", "Kitchen", 10, 0, 10, 10)]


def openings_on(model, storey=0, kind=None):
    out = []
    for wall in model.walls_on(storey):
        for opening in wall.openings:
            if kind is None or opening.kind == kind:
                out.append((wall, opening))
    return out


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_model_shape_and_provenance(model):
    assert model.schema_version == "structural-1.1"
    assert model.source == M.ModelSource.PLAN_JSON
    assert model.system == M.System.RC_FRAME
    assert model.id == "plan-0"
    assert len(model.fingerprint) == 64
    assert model.meta["north"] == "-y"
    assert model.meta["adapter"] == "plan_json"


def test_model_validates_clean(model):
    assert model.validate() == []


def test_storey_repetition_carries_per_storey_ids(model):
    assert [s.index for s in model.storeys] == [0, 1]
    assert [s.name for s in model.storeys] == ["Ground", "Floor 1"]
    assert model.storeys[0].bottom_z_m == pytest.approx(0.0)
    assert model.storeys[1].bottom_z_m == pytest.approx(10.0 * FT)
    for storey in model.storeys:
        assert storey.height_m == pytest.approx(10.0 * FT)
        assert storey.kind == M.StoreyKind.UNITS

    assert len(model.rooms_on(0)) == ROOM_COUNT
    assert len(model.rooms_on(1)) == ROOM_COUNT
    assert len(model.walls_on(0)) == len(model.walls_on(1))

    # The two storeys are the same plan, re-suffixed, not a second derivation.
    for lower, upper in zip(model.walls_on(0), model.walls_on(1)):
        assert lower.id.replace("-s0-", "-s1-") == upper.id
        assert lower.a == upper.a and lower.b == upper.b
        assert len(lower.openings) == len(upper.openings)
    assert model.meta["roof_storey_index"] == 1


def test_room_polygons_match_the_fixture(model, rooms):
    by_source = dict((r.source, r) for r in model.rooms_on(0))
    assert sorted(by_source) == sorted(r["_id"] for r in rooms)
    for raw in rooms:
        record = by_source[raw["_id"]]
        xs = [p[0] for p in raw["circular_coordinates"]]
        ys = [p[1] for p in raw["circular_coordinates"]]
        box = G.polygon_bbox(record.polygon)
        assert M.m_to_ft(box.x) == pytest.approx(min(xs), abs=1e-6)
        assert M.m_to_ft(box.y) == pytest.approx(min(ys), abs=1e-6)
        assert M.m_to_ft(box.w) == pytest.approx(raw["width"], abs=1e-6)
        assert M.m_to_ft(box.h) == pytest.approx(raw["height"], abs=1e-6)
        assert record.area_m2 == pytest.approx(raw["area"] * FT * FT)
        assert record.id == "room-s0-" + raw["_id"]
        assert record.interior_unknown is False


# ---------------------------------------------------------------------------
# wall extraction
# ---------------------------------------------------------------------------


def test_wall_counts_and_lengths(model):
    walls = model.walls_on(0)
    exterior = [w for w in walls if w.role == M.WallRole.EXTERIOR]
    interior = [w for w in walls if w.role == M.WallRole.INTERIOR]
    assert len(exterior) == EXTERIOR_WALLS
    assert len(interior) == INTERIOR_WALLS
    assert sum(M.m_to_ft(w.length_m()) for w in exterior) == pytest.approx(EXTERIOR_FT)
    assert sum(M.m_to_ft(w.length_m()) for w in interior) == pytest.approx(INTERIOR_FT)


def test_wall_roles_thicknesses_and_sides(model):
    for wall in model.walls_on(0):
        assert M.wall_axis(wall) is not None, wall.id
        assert wall.length_m() > 0.0
        assert wall.bearing is None
        assert wall.material == M.Material.BRICK_MASONRY
        outside = [rid for rid in wall.room_ids if rid is None]
        if wall.role == M.WallRole.EXTERIOR:
            assert len(outside) == 1
            assert wall.thickness_m == pytest.approx(0.75 * FT)
        else:
            assert outside == []
            assert wall.thickness_m == pytest.approx(0.4 * FT)


def test_room_ids_follow_the_wall_normal(model):
    by_id = dict((w.id, w) for w in model.walls_on(0))
    # Horizontal wall at y = 13 over x 0..8: bedroom 1 above, bathroom below.
    horizontal = by_id["wall-s0-h-13-0"]
    assert horizontal.a == pytest.approx((0.0, 13.0 * FT))
    assert horizontal.b == pytest.approx((8.0 * FT, 13.0 * FT))
    assert horizontal.room_ids == ("room-s0-r-bed1", "room-s0-r-bath")
    # Vertical wall at x = 15 over y 0..13: bedroom 2 right, bedroom 1 left.
    vertical = by_id["wall-s0-v-15-0"]
    assert vertical.a == pytest.approx((15.0 * FT, 0.0))
    assert vertical.b == pytest.approx((15.0 * FT, 13.0 * FT))
    assert vertical.room_ids == ("room-s0-r-bed2", "room-s0-r-bed1")


def test_no_two_walls_left_unmerged(model):
    """Collinear neighbours sharing a signature must have been merged into one wall."""
    groups = {}
    for wall in model.walls_on(0):
        orient, pos, s0, s1 = M.wall_axis(wall)
        key = (orient, round(pos, 6), wall.role.value, round(wall.thickness_m, 6), wall.room_ids)
        groups.setdefault(key, []).append((round(s0, 6), round(s1, 6)))
    for key, runs in sorted(groups.items()):
        runs.sort()
        for (_, end), (start, _) in zip(runs, runs[1:]):
            assert start > end + G.LINE_TOL_M, "unmerged collinear run in " + str(key)


def test_near_collinear_lines_cluster_at_115_mm():
    """Edges 0.2 ft apart (61 mm) are one centreline, per the 115 mm tolerance."""
    plan = [
        room("a", "Bedroom 1", 0.0, 0.0, 15.0, 10.0),
        room("b", "Bedroom 2", 15.0, 0.0, 15.0, 10.0),
        room("c", "Living Room", 0.0, 10.0, 15.2, 10.0),
        room("d", "Kitchen", 15.2, 10.0, 14.8, 10.0),
    ]
    model = A.from_plan(plan)
    interior_v = [
        w
        for w in model.walls_on(0)
        if w.role == M.WallRole.INTERIOR and M.wall_axis(w)[0] == "v"
    ]
    assert len(interior_v) == 2
    positions = set(round(M.m_to_ft(M.wall_axis(w)[1]), 6) for w in interior_v)
    assert positions == set([15.1])


# ---------------------------------------------------------------------------
# openings
# ---------------------------------------------------------------------------


def test_doors_assumed_with_provenance(model):
    doors = openings_on(model, 0, M.OpeningKind.DOOR)
    assert len(doors) == PTPG_EDGES
    for wall, opening in doors:
        assert wall.role == M.WallRole.INTERIOR
        assert opening.provenance == M.Provenance.ASSUMED_MID_WALL
        assert opening.width_m == pytest.approx(A.DOOR_WIDTH_M)
        assert opening.offset_m == pytest.approx(0.5 * wall.length_m())
        assert opening.sill_m is None and opening.head_m is None
        assert opening.id == wall.id + "-op0"
    assert model.doors_known(0) is False
    assert all(M.opening_assumed(o) for _, o in doors)


def test_every_ptpg_edge_got_a_door(model, payload, rooms):
    matrix = payload["response"]["Documents"]["ptpg_graph"]
    ids = [r["_id"] for r in rooms]
    doored = set()
    for wall in model.walls_on(0):
        if any(o.kind == M.OpeningKind.DOOR for o in wall.openings):
            doored.add(frozenset(rid.replace("room-s0-", "") for rid in wall.room_ids))
    expected = 0
    for i in range(len(matrix)):
        for j in range(i + 1, len(matrix)):
            if matrix[i][j]:
                expected += 1
                assert frozenset([ids[i], ids[j]]) in doored, (ids[i], ids[j])
    assert expected == PTPG_EDGES


def test_assumed_doors_are_disclosed_once(model):
    codes = [w.code for w in model.warnings]
    assert codes.count("W_DOOR_ASSUMED") == 1
    entry = [w for w in model.warnings if w.code == "W_DOOR_ASSUMED"][0]
    assert entry.severity == M.Severity.WARNING
    assert str(PTPG_EDGES) in entry.message
    assert entry.stage == "adapters.plan_json"
    # Both storeys' openings are named, not just the ground floor's.
    assert len(entry.element_ids) == PTPG_EDGES * 2
    assert all(model.by_id(eid) is not None for eid in entry.element_ids)


def test_every_room_is_reachable_through_doors(model):
    edges = {}
    for wall in model.walls_on(0):
        if not any(o.kind == M.OpeningKind.DOOR for o in wall.openings):
            continue
        a, b = wall.room_ids
        edges.setdefault(a, set()).add(b)
        edges.setdefault(b, set()).add(a)
    start = "room-s0-r-living"
    seen = set([start])
    queue = [start]
    while queue:
        node = queue.pop(0)
        for other in sorted(edges.get(node, ())):
            if other not in seen:
                seen.add(other)
                queue.append(other)
    assert seen == set(r.id for r in model.rooms_on(0))


def test_reachability_repair_doors_a_stranded_room(payload):
    """A truncated adjacency graph strands the bedrooms; the repair pass doors them."""
    sparse = [[0, 1], [0, 2], [0, 5], [0, 6], [0, 7], [3, 4]]
    model = A.from_plan(payload, adjacency_edges=sparse)
    doors = openings_on(model, 0, M.OpeningKind.DOOR)
    assert len(doors) == len(sparse) + 1
    repaired = [w.id for w, _ in doors if "room-s0-r-bed1" in w.room_ids and "room-s0-r-bath" in w.room_ids]
    assert repaired == ["wall-s0-h-13-0"]


def test_shortfall_pair_gets_no_door(payload):
    model = A.from_plan(payload, adjacency_shortfalls=[["r-bath", "r-toilet"]])
    doors = openings_on(model, 0, M.OpeningKind.DOOR)
    assert len(doors) == PTPG_EDGES - 1
    for wall, _ in doors:
        assert set(wall.room_ids) != set(["room-s0-r-bath", "room-s0-r-toilet"])
    entries = [w for w in model.warnings if w.code == "W_ADJACENCY_SHORTFALL"]
    assert len(entries) == 1
    assert "r-bath" in entries[0].message and "r-toilet" in entries[0].message


def test_a_door_never_grows_wider_than_its_wall():
    """2.8 ft passes the shortfall gate but is narrower than a 0.9 m door leaf."""
    plan = [
        room("a", "Bedroom 1", 0.0, 0.0, 10.0, 10.0),
        room("b", "Bathroom", 10.0, 0.0, 10.0, 2.85),
        room("c", "Kitchen", 10.0, 2.85, 10.0, 7.15),
    ]
    model = A.from_plan(plan)
    doors = openings_on(model, 0, M.OpeningKind.DOOR)
    narrow = [o for w, o in doors if w.id == "wall-s0-v-10-0"]
    assert len(narrow) == 1
    assert M.m_to_ft(narrow[0].width_m) == pytest.approx(2.85)
    assert narrow[0].offset_m == pytest.approx(0.5 * 2.85 * FT)
    entry = [w for w in model.warnings if w.code == "W_DOOR_ASSUMED"][0]
    assert "narrowed" in entry.message


def test_windows_are_not_assumed_by_default(model):
    assert openings_on(model, 0, M.OpeningKind.WINDOW) == []
    codes = [w.code for w in model.warnings]
    assert codes.count("N_WINDOWS_NOT_ASSUMED") == 1
    note = [w for w in model.warnings if w.code == "N_WINDOWS_NOT_ASSUMED"][0]
    assert note.severity == M.Severity.NOTE


def test_assume_windows_places_one_per_habitable_exterior_wall(payload):
    model = A.from_plan(payload, assume_windows=True)
    windows = openings_on(model, 0, M.OpeningKind.WINDOW)
    # bedroom 1 (west + north), bedroom 2 (east + north), living (west), dining (east)
    assert len(windows) == 6
    for wall, opening in windows:
        assert wall.role == M.WallRole.EXTERIOR
        room = [rid for rid in wall.room_ids if rid is not None][0]
        assert model.by_id(room).occupancy == M.Occupancy.HABITABLE
        assert opening.width_m == pytest.approx(A.WINDOW_WIDTH_M)
        assert opening.sill_m == pytest.approx(A.WINDOW_SILL_M)
        assert opening.head_m == pytest.approx(A.WINDOW_HEAD_M)
        assert opening.provenance == M.Provenance.ASSUMED_MID_WALL
    codes = [w.code for w in model.warnings]
    assert codes.count("W_ASSUMED_OPENINGS") == 1
    assert "N_WINDOWS_NOT_ASSUMED" not in codes


def test_dressed_doors_win_over_synthesis(payload):
    dressed = [
        {"orientation": "v", "x": 15.0, "y": 29.5, "width": 3.0, "sill": 0.0, "head": 7.0},
        {"orientation": "h", "x": 100.0, "y": 100.0, "width": 3.0},
    ]
    model = A.from_plan(payload, doors=dressed)
    doors = openings_on(model, 0, M.OpeningKind.DOOR)
    assert len(doors) == 1
    wall, opening = doors[0]
    assert wall.id == "wall-s0-v-15-24"
    assert opening.provenance == M.Provenance.DRESSED
    assert M.m_to_ft(opening.offset_m) == pytest.approx(5.5)
    assert M.m_to_ft(opening.width_m) == pytest.approx(3.0)
    assert model.doors_known(0) is True

    codes = [w.code for w in model.warnings]
    assert codes.count("W_DOOR_UNMAPPED") == 1
    assert "W_DOOR_ASSUMED" not in codes


# ---------------------------------------------------------------------------
# occupancy
# ---------------------------------------------------------------------------


def test_occupancy_from_room_names(model):
    got = dict((r.source, r.occupancy) for r in model.rooms_on(0))
    assert got["r-living"] == M.Occupancy.HABITABLE
    assert got["r-dining"] == M.Occupancy.HABITABLE
    assert got["r-bed1"] == M.Occupancy.HABITABLE
    assert got["r-kitchen"] == M.Occupancy.KITCHEN
    assert got["r-bath"] == M.Occupancy.BATH
    assert got["r-toilet"] == M.Occupancy.WC
    assert got["r-balcony"] == M.Occupancy.BALCONY
    assert "W_OCCUPANCY_UNKNOWN" not in [w.code for w in model.warnings]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Bathroom 2", M.Occupancy.BATH),
        ("Master Bedroom", M.Occupancy.HABITABLE),
        ("Master Bath", M.Occupancy.BATH),
        ("Master Toilet", M.Occupancy.WC),
        ("Guest Bathroom", M.Occupancy.BATH),
        ("Hall", M.Occupancy.HABITABLE),
        ("Hallway", M.Occupancy.CORRIDOR),
        ("Washroom", M.Occupancy.BATH),
        ("Wash Area", M.Occupancy.UTILITY),
        ("WC 1", M.Occupancy.WC),
        ("Store", M.Occupancy.STORAGE),
        ("Staircase", M.Occupancy.STAIR),
        ("Zone Q", None),
    ],
)
def test_name_kind_is_complete_token_tolerant(name, expected):
    assert A.occupancy_for_name(name) == expected


def test_unknown_name_falls_back_to_other_and_discloses():
    plan = [room("a", "Zone Q", 0, 0, 10, 10), room("b", "Kitchen", 10, 0, 10, 10)]
    model = A.from_plan(plan)
    got = dict((r.source, r.occupancy) for r in model.rooms_on(0))
    assert got["a"] == M.Occupancy.OTHER
    assert got["b"] == M.Occupancy.KITCHEN
    entries = [w for w in model.warnings if w.code == "W_OCCUPANCY_UNKNOWN"]
    assert len(entries) == 1
    assert "Zone Q" in entries[0].message
    assert entries[0].element_ids == ["room-s0-a"]


def test_occupancy_map_overrides_by_id_and_by_name():
    model = A.from_plan(two_room_plan(), occupancy_map={"a": "storage", "Kitchen": M.Occupancy.UTILITY})
    got = dict((r.source, r.occupancy) for r in model.rooms_on(0))
    assert got["a"] == M.Occupancy.STORAGE
    assert got["b"] == M.Occupancy.UTILITY
    assert "W_OCCUPANCY_UNKNOWN" not in [w.code for w in model.warnings]


def test_occupancy_map_refuses_an_unknown_value():
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(two_room_plan(), occupancy_map={"a": "bedroom"})
    assert excinfo.value.code == "E_BAD_ENVELOPE"


# ---------------------------------------------------------------------------
# envelopes, options and determinism
# ---------------------------------------------------------------------------


def test_every_envelope_unwraps_to_the_same_model(payload, rooms):
    documents = payload["response"]["Documents"]
    full = A.from_plan(payload).to_dict()
    assert A.from_plan(payload["response"]).to_dict() == full
    assert A.from_plan(documents).to_dict() == full
    assert A.from_plan({"floorPlans": [rooms], "ptpg_graph": documents["ptpg_graph"]}).to_dict()["walls"] == full["walls"]

    # A bare room list carries no ptpg graph, so only the geometry can match:
    # the doors then come from the reachability pass alone.
    bare = A.from_plan(rooms).to_dict()
    assert A.from_plan({"floorPlans": [rooms]}).to_dict()["walls"] == bare["walls"]
    assert bare["walls"] != full["walls"]
    assert [w["id"] for w in bare["walls"]] == [w["id"] for w in full["walls"]]
    assert bare["rooms"] == full["rooms"]


def test_plan_index_is_bounds_checked(payload):
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(payload, plan_index=3)
    assert excinfo.value.code == "E_BAD_ENVELOPE"


def test_plot_and_options_land_in_meta(payload):
    plot = {"width": 30.0, "height": 40.0}
    model = A.from_plan(payload, plot=plot, storeys=3, assume_windows=True)
    assert model.meta["plot"] == plot
    assert model.meta["plot_fit"]["fits"] is True
    assert model.meta["options"]["storeys"] == 3
    assert model.meta["options"]["assume_windows"] is True
    assert model.meta["options"]["exterior_wall_ft"] == 0.75
    assert model.meta["bbox_ft"] == [0.0, 0.0, PLAN_W_FT, PLAN_H_FT]
    assert model.meta["source_room_ids"][0] == "r-living"


def test_wall_thickness_options_are_honoured(payload):
    model = A.from_plan(payload, exterior_wall_ft=1.0, interior_wall_ft=0.5)
    for wall in model.walls_on(0):
        expected = 1.0 if wall.role == M.WallRole.EXTERIOR else 0.5
        assert wall.thickness_m == pytest.approx(expected * FT)


def test_ids_and_output_are_deterministic(payload):
    first = A.from_plan(payload, storeys=2)
    second = A.from_plan(payload, storeys=2)
    assert first.to_dict() == second.to_dict()
    assert first.fingerprint == second.fingerprint
    # A different option must not silently reuse the same dedup key.
    assert A.from_plan(payload, storeys=3).fingerprint != first.fingerprint


def test_wire_round_trip(model):
    wire = model.to_dict()
    assert M.StructuralModel.from_dict(wire).to_dict() == wire


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_overlapping_rooms_are_refused():
    plan = [room("a", "Bedroom", 0, 0, 10, 10), room("b", "Kitchen", 5, 0, 10, 10)]
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(plan)
    assert excinfo.value.code == "E_ROOM_OVERLAP"
    assert "a" in excinfo.value.message and "b" in excinfo.value.message


def test_void_between_rooms_is_refused():
    plan = [room("a", "Bedroom", 0, 0, 10, 10), room("b", "Kitchen", 12, 0, 10, 10)]
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(plan)
    assert excinfo.value.code == "E_PLAN_NOT_GAPLESS"
    assert excinfo.value.message.startswith(A.NOT_GAPLESS_MESSAGE)
    assert "door_connectivity" in excinfo.value.message


def test_gapless_relative_tolerance_has_an_absolute_void_floor_and_residual_note():
    """A 1.25 sqft void is tiny relative to 10,000 sqft but must still refuse."""
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(
            [
                room("a", "Bedroom", 0, 0, 50, 100),
                room("b", "Kitchen", 50.0125, 0, 49.9875, 100),
            ]
        )
    assert excinfo.value.code == "E_PLAN_NOT_GAPLESS"

    accepted = A.from_plan(
        [
            room("a", "Bedroom", 0, 0, 50, 100),
            room("b", "Kitchen", 50.0075, 0, 49.9925, 100),
        ]
    )
    note = [entry for entry in accepted.warnings if entry.code == "N_GAPLESS_RESIDUAL"]
    assert len(note) == 1
    assert note[0].element_ids == ["room-s0-a", "room-s0-b"]
    assert "0.750 sqft" in note[0].message


def test_non_rectangular_room_is_refused():
    l_shape = {
        "_id": "L",
        "name": "Living Room",
        "circular_coordinates": [[0, 0], [10, 0], [10, 10], [5, 10], [5, 20], [0, 20]],
    }
    plan = [l_shape, room("b", "Kitchen", 10, 0, 10, 20)]
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(plan)
    assert excinfo.value.code == "E_NOT_RECTANGULAR"


def test_stated_dimensions_must_match_the_outline():
    plan = two_room_plan()
    plan[1]["width"] = 12.0
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(plan)
    assert excinfo.value.code == "E_NOT_RECTANGULAR"
    assert "width" in excinfo.value.message


@pytest.mark.parametrize(
    "payload_in,code",
    [
        ([], "E_EMPTY_PLAN"),
        ("not a plan", "E_BAD_ENVELOPE"),
        (None, "E_BAD_ENVELOPE"),
        ({"floorPlans": []}, "E_EMPTY_PLAN"),
        ({"floorPlans": "no"}, "E_BAD_ENVELOPE"),
    ],
)
def test_bad_payloads_are_refused(payload_in, code):
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(payload_in)
    assert excinfo.value.code == code


def test_storeys_and_system_are_validated():
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(two_room_plan(), storeys=0)
    assert excinfo.value.code == "E_UNSUPPORTED_STOREYS"
    with pytest.raises(AdapterError) as excinfo:
        A.from_plan(two_room_plan(), system_hint="masonry")
    assert excinfo.value.code == "E_BAD_ENVELOPE"


def test_system_hint_reaches_the_model():
    model = A.from_plan(two_room_plan(), system_hint="load_bearing_masonry")
    assert model.system == M.System.LOAD_BEARING_MASONRY
    assert M.System(A.from_plan(two_room_plan(), system_hint=M.System.MIXED).system) == M.System.MIXED


# ---------------------------------------------------------------------------
# _geom: the shared helpers the other two adapters import
# ---------------------------------------------------------------------------


def test_adapter_error_is_registry_checked():
    error = AdapterError("E_ROOM_OVERLAP", "two rooms overlap", {"element_ids": ["r1", "r2"]})
    assert error.code == "E_ROOM_OVERLAP"
    assert str(error).startswith("E_ROOM_OVERLAP: ")
    disclosure = error.to_disclosure()
    assert disclosure.severity == M.Severity.ERROR
    assert disclosure.element_ids == ["r1", "r2"]
    with pytest.raises(ValueError):
        AdapterError("E_MADE_UP", "not registered")
    with pytest.raises(ValueError):
        AdapterError("W_DOOR_ASSUMED", "warnings are disclosed, never raised")


def test_cluster_values_caps_each_cluster_at_the_tolerance():
    assert G.cluster_values([0.0, 0.05, 0.1, 1.0], 0.115) == pytest.approx([0.05, 1.0])
    # Chaining must not drag a cluster past the tolerance.
    assert G.cluster_values([0.0, 0.1, 0.2, 0.3], 0.115) == pytest.approx([0.05, 0.25])
    assert G.cluster_index(0.09, [0.05, 1.0], 0.115) == 0
    assert G.cluster_index(0.5, [0.05, 1.0], 0.115) is None


def test_merge_intervals_closes_abutting_runs():
    assert G.merge_intervals([(0.0, 1.0), (1.0, 2.0)]) == [(0.0, 2.0)]
    assert G.merge_intervals([(1.0, 2.0), (0.0, 0.5)]) == [(0.0, 0.5), (1.0, 2.0)]
    assert G.merge_intervals([(0.0, 2.0), (0.5, 1.0)]) == [(0.0, 2.0)]
    assert G.interval_overlap(0.0, 2.0, 1.0, 5.0) == pytest.approx(1.0)
    assert G.interval_overlap(0.0, 1.0, 1.0, 5.0) == 0.0


def test_polygon_helpers_agree_with_the_model():
    rect = G.Rect(1.0, 2.0, 3.0, 4.0)
    loop = G.rect_polygon(rect)
    assert loop == [(1.0, 2.0), (4.0, 2.0), (4.0, 6.0), (1.0, 6.0)]
    assert G.polygon_signed_area(loop) == pytest.approx(12.0)
    assert G.polygon_area(loop) == pytest.approx(12.0)
    assert G.polygon_bbox(loop) == rect
    assert G.is_rectilinear(loop) is True
    assert G.is_axis_aligned_rect(loop) is True
    assert G.is_rectilinear([(0, 0), (1, 1), (2, 0), (1, -1)]) is False
    assert G.rects_overlap_area((0, 0, 2, 2), (1, 1, 2, 2)) == pytest.approx(1.0)
    assert G.rects_overlap((0, 0, 2, 2), (2, 0, 2, 2)) is False
    with pytest.raises(AdapterError):
        G.require_rectilinear([(0, 0), (1, 1), (2, 0), (1, -1)], "E_BOUNDARY_NOT_RECTILINEAR", "skew")


def test_fingerprint_is_stable_and_order_independent():
    assert G.fingerprint({"a": 1, "b": 2}) == G.fingerprint({"b": 2, "a": 1})
    assert G.fingerprint({"a": 1}) != G.fingerprint({"a": 2})
    assert len(G.fingerprint([1, 2, 3])) == 64
