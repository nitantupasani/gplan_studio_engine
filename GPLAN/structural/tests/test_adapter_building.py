"""Pins for adapters/building.py: the frontend Building payload -> StructuralModel.

Two kinds of input drive these tests. `fixtures/building_3storey.json` is the
committed payload (three storeys, a stilt ground floor, two units that do NOT
abut, a corridor and two cores), and small synthetic payloads pin the rules the
fixture cannot exercise: the four rotation maps with hand-computed coordinates,
a dressed detailedPlan whose door has to land on the rotated wall, party-wall
merging, and every refusal.
"""

from __future__ import annotations

import json
import os

import pytest

# Relative: pytest imports this package as GPLAN.GPLAN.structural.tests, so an
# absolute GPLAN.structural import would resolve against the outer directory.
from .. import model as M
from ..adapters.building import (
    ASSUMED_DOOR_WIDTH_M,
    ASSUMED_WINDOW_WIDTH_M,
    AdapterError,
    from_building,
)
from ..schema import validate_wire

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), "r") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def payload():
    return _load("building_3storey.json")


@pytest.fixture(scope="module")
def model(payload):
    return from_building(payload)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _ft(value_m):
    return round(M.m_to_ft(value_m), 6)


def _rect_ft(room):
    """Room bounding rect in feet, the frame the payload was written in."""
    return tuple(_ft(v) for v in M.polygon_rect(room.polygon))


def _axis_ft(wall):
    orient, pos, s0, s1 = M.wall_axis(wall)
    return (orient, _ft(pos), _ft(s0), _ft(s1))


def _by_name(model, name):
    matches = [r for r in model.rooms if r.name == name]
    assert len(matches) == 1, "expected exactly one room named " + name
    return matches[0]


def _codes(model):
    return sorted({w.code for w in model.warnings})


def _walls_with_openings(model):
    return [w for w in model.walls if w.openings]


def _unit(uid, x, y, w, h, rotation=0, **extra):
    unit = {
        "id": uid,
        "name": uid.upper(),
        "type": "2BHK",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "rotation": rotation,
        "isFixed": False,
        "spaces": [],
        "floorplans": [],
        "activeFloorplanIndex": 0,
    }
    unit.update(extra)
    return unit


def _floor(fid, number=0, units=(), corridors=(), kind="units", parking=()):
    return {
        "id": fid,
        "floorNumber": number,
        "label": "Floor " + str(number),
        "kind": kind,
        "units": list(units),
        "corridors": list(corridors),
        "parking": list(parking),
    }


def _building(floors, total=None, boundary=None, fixed=(), **extra):
    payload = {
        "id": "b-test",
        "name": "Test",
        "type": "Low-Rise Residential",
        "boundary": boundary or {"kind": "rect", "width": 60, "height": 60},
        "far": 1.5,
        "totalFloors": total if total is not None else len(floors),
        "fixedElements": list(fixed),
        "floors": list(floors),
    }
    payload.update(extra)
    return payload


def _floorplan(pid="p1", width=20.0, height=20.0, placements=()):
    return {
        "id": pid,
        "label": "Plan 1",
        "taskId": "t1",
        "floorWidth": width,
        "floorHeight": height,
        "createdAt": "2026-01-01",
        "placements": [dict(p, color=p.get("color", "#cccccc")) for p in placements],
    }


def _place(name, x, y, w, h):
    return {"name": name, "x": x, "y": y, "width": w, "height": h}


# The two-room plan every rotation assertion is computed against: a 20 x 12 ft
# local plan, Living on the left, Kitchen on the right.
ROT_PLAN = _floorplan(
    width=20.0,
    height=12.0,
    placements=(_place("Living", 0, 0, 12, 12), _place("Kitchen", 12, 0, 8, 12)),
)

# Unit origin (5, 3) in the floor frame; expectations are the spec's step-5
# table applied by hand with W = 20, H = 12.
ROT_EXPECTED = {
    0: {"Living": (5, 3, 12, 12), "Kitchen": (17, 3, 8, 12)},
    90: {"Living": (5, 3, 12, 12), "Kitchen": (5, 15, 12, 8)},
    180: {"Living": (13, 3, 12, 12), "Kitchen": (5, 3, 8, 12)},
    270: {"Living": (5, 11, 12, 12), "Kitchen": (5, 3, 12, 8)},
}


# --------------------------------------------------------------------------
# fixtures/building_3storey.json
# --------------------------------------------------------------------------


def test_storeys_are_contiguous_from_ground(model):
    assert [s.index for s in model.storeys] == [0, 1, 2]
    assert [s.kind.value for s in model.storeys] == ["stilt", "units", "units"]
    assert [_ft(s.bottom_z_m) for s in model.storeys] == [0.0, 10.0, 20.0]
    assert [_ft(s.height_m) for s in model.storeys] == [10.0, 10.0, 10.0]
    assert [s.source_id for s in model.storeys] == ["fl-0", "fl-1", "fl-2"]


def test_stilt_storey_is_open(model):
    """Pilotis carry no envelope: that absence is the soft-storey hook."""
    assert model.walls_on(0) == []
    assert model.rooms_on(0) == []
    assert model.storey(0).kind == M.StoreyKind.STILT


def test_units_that_do_not_abut_produce_no_party_wall(model):
    """Units sit at x 2..32 and 36..66, so nothing merges: no party wall exists."""
    assert [w.id for w in model.walls if w.role == M.WallRole.PARTY] == []
    positions = sorted({_axis_ft(w)[1] for w in model.walls_on(1) if _axis_ft(w)[0] == "v"})
    assert positions == [0.0, 2.0, 32.0, 36.0, 66.0, 84.0]
    # the two facing unit edges stay two separate exterior walls, 4 ft apart
    facing = [w for w in model.walls_on(1) if _axis_ft(w)[1] in (32.0, 36.0) and _axis_ft(w)[0] == "v"]
    assert len(facing) == 2
    assert {w.role for w in facing} == {M.WallRole.EXTERIOR}


def test_corridor_becomes_a_corridor_room_on_every_units_storey(model):
    corridors = [r for r in model.rooms if r.occupancy == M.Occupancy.CORRIDOR]
    assert [r.id for r in corridors] == ["room-s1-cor-1", "room-s2-cor-1"]
    assert _rect_ft(corridors[0]) == (2.0, 44.0, 64.0, 6.0)
    rects = model.corridor_rects(1)
    assert len(rects) == 1
    assert rects[0] == pytest.approx(tuple(M.ft_to_m(v) for v in (2.0, 44.0, 64.0, 6.0)))
    assert [r.source for r in corridors] == ["cor-1", "cor-1"]


def test_units_without_a_plan_become_one_unknown_room_each(model):
    unknown = sorted(r.id for r in model.rooms if r.interior_unknown)
    assert unknown == ["room-s1-u-a", "room-s1-u-b", "room-s2-u-a", "room-s2-u-b"]
    room = model.by_id("room-s1-u-a")
    assert room.name == "unit:2BHK"
    assert room.occupancy == M.Occupancy.OTHER
    assert _rect_ft(room) == (2.0, 2.0, 30.0, 40.0)
    assert room.unit_id == "unit-s1-u-a"
    entry = [w for w in model.warnings if w.code == "W_UNIT_NO_PLAN"]
    assert len(entry) == 1
    assert entry[0].severity == M.Severity.WARNING
    assert entry[0].element_ids == unknown


def test_cores_sit_on_every_storey(model):
    assert [(c.id, c.kind.value, c.storeys) for c in model.cores] == [
        ("core-fe-lift", "lift", [0, 1, 2]),
        ("core-fe-stair", "stairs", [0, 1, 2]),
    ]
    stair = model.by_id("core-fe-stair")
    assert (_ft(stair.x_m), _ft(stair.y_m), _ft(stair.w_m), _ft(stair.h_m)) == (69.0, 4.0, 12.0, 10.0)
    assert stair.stair_landing_hint is None
    assert [c.id for c in model.cores_on(2)] == ["core-fe-lift", "core-fe-stair"]


def test_wall_roles_and_thicknesses(model):
    assert len(model.walls) == 32
    assert len(model.walls_on(1)) == 16
    boundary = [w for w in model.walls_on(1) if w.source == "boundary"]
    assert len(boundary) == 4
    assert {_ft(w.thickness_m) for w in boundary} == {0.75}
    assert {w.role for w in boundary} == {M.WallRole.EXTERIOR}
    corridor_walls = [w for w in model.walls_on(1) if w.source == "cor-1"]
    assert len(corridor_walls) == 4
    assert {_ft(w.thickness_m) for w in corridor_walls} == {0.4}
    assert {w.role for w in corridor_walls} == {M.WallRole.INTERIOR}
    # the corridor's own room sits on one side of each of its walls
    assert all("room-s1-cor-1" in w.room_ids for w in corridor_walls)


def test_room_sides_follow_the_low_high_convention(model):
    west = next(w for w in model.walls_on(1) if _axis_ft(w) == ("v", 2.0, 2.0, 42.0))
    assert west.room_ids == (None, "room-s1-u-a")
    east = next(w for w in model.walls_on(1) if _axis_ft(w) == ("v", 32.0, 2.0, 42.0))
    assert east.room_ids == ("room-s1-u-a", None)
    north = next(w for w in model.walls_on(1) if _axis_ft(w) == ("h", 2.0, 2.0, 32.0))
    assert north.room_ids == (None, "room-s1-u-a")


def test_model_invariants_hold(model):
    assert model.validate() == []
    assert model.source == M.ModelSource.BUILDING
    assert model.system == M.System.RC_FRAME
    assert len(model.fingerprint) == 64


def test_wire_round_trip(model):
    wire = model.to_dict()
    assert validate_wire(wire) == []
    back = M.StructuralModel.from_dict(wire)
    assert json.dumps(back.to_dict(), sort_keys=True) == json.dumps(wire, sort_keys=True)


def test_adapter_is_deterministic(payload):
    first = json.dumps(from_building(payload).to_dict(), sort_keys=True)
    second = json.dumps(from_building(payload).to_dict(), sort_keys=True)
    assert first == second


def test_meta_records_the_frame_and_the_options(model):
    assert model.meta["north"] == "-y"
    assert model.meta["adapter"] == "building"
    assert model.meta["source_id"] == "bldg-fx1"
    assert model.meta["boundary_ft"] == [[0.0, 0.0], [84.0, 0.0], [84.0, 51.0], [0.0, 51.0]]
    assert model.meta["options"]["storey_height_ft"] == 10.0
    assert model.meta["options"]["assume_windows"] is False
    assert "client_grid" not in model.meta


def test_disclosed_codes_are_exactly_what_the_payload_earns(model):
    assert _codes(model) == ["W_UNIT_NO_PLAN"]


# --------------------------------------------------------------------------
# rotation (spec section 6 step 5, normative)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotation_transform(rotation):
    footprint = (20.0, 12.0) if rotation in (0, 180) else (12.0, 20.0)
    model = from_building(
        _building([_floor("f0", 0, units=[_unit("u1", 5, 3, footprint[0], footprint[1], rotation, floorplans=[ROT_PLAN])])])
    )
    for name, expected in sorted(ROT_EXPECTED[rotation].items()):
        assert _rect_ft(_by_name(model, name)) == expected, name
    # a rotation is rigid: the areas travel unchanged
    assert _by_name(model, "Living").area_m2 == pytest.approx(M.ft_to_m(12) * M.ft_to_m(12))
    assert _by_name(model, "Kitchen").area_m2 == pytest.approx(M.ft_to_m(8) * M.ft_to_m(12))
    assert model.validate() == []


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_room_ids_are_rotation_stable(rotation):
    footprint = (20.0, 12.0) if rotation in (0, 180) else (12.0, 20.0)
    model = from_building(
        _building([_floor("f0", 0, units=[_unit("u1", 5, 3, footprint[0], footprint[1], rotation, floorplans=[ROT_PLAN])])])
    )
    assert sorted(r.id for r in model.rooms) == ["room-s0-u1-kitchen-1", "room-s0-u1-living-0"]


def test_rotation_outside_the_four_quarter_turns_is_refused():
    with pytest.raises(AdapterError) as excinfo:
        from_building(_building([_floor("f0", 0, units=[_unit("u1", 0, 0, 10, 10, 45)])]))
    assert excinfo.value.code == "E_BAD_ROTATION"
    assert "45" in excinfo.value.message


# --------------------------------------------------------------------------
# dressed unit interiors
# --------------------------------------------------------------------------


def _dressed_plan(doors=(), windows=()):
    return {
        "id": "dp1",
        "source": "api",
        "width": 20.0,
        "height": 12.0,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "r1", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 12, "height": 12},
            {"id": "r2", "name": "Kitchen", "kind": "kitchen", "x": 12, "y": 0, "width": 8, "height": 12},
        ],
        "doors": list(doors),
        "windows": list(windows),
        "furniture": [],
    }


def _dressed_model(doors=(), windows=(), rotation=90):
    plan = _dressed_plan(doors, windows)
    unit = _unit("u1", 10, 4, 12, 20, rotation, detailedPlan=plan)
    return from_building(_building([_floor("f0", 0, units=[unit])]))


def test_dressed_door_maps_to_the_rotated_wall():
    """Local v-wall door at (12, 6) under rot 90 becomes an h-wall door at (16, 16)."""
    door = {"id": "d1", "orientation": "v", "x": 12, "y": 6, "width": 3, "hinge": "start", "swing": "pos"}
    model = _dressed_model(doors=[door])

    assert _rect_ft(_by_name(model, "Living Room")) == (10.0, 4.0, 12.0, 12.0)
    assert _rect_ft(_by_name(model, "Kitchen")) == (10.0, 16.0, 12.0, 8.0)

    carriers = _walls_with_openings(model)
    assert len(carriers) == 1
    wall = carriers[0]
    assert _axis_ft(wall) == ("h", 16.0, 10.0, 22.0)
    assert wall.role == M.WallRole.INTERIOR
    assert wall.room_ids == ("room-s0-u1-r1", "room-s0-u1-r2")

    opening = wall.openings[0]
    assert opening.id == wall.id + "-op0"
    assert opening.kind == M.OpeningKind.DOOR
    assert _ft(opening.offset_m) == 6.0
    assert _ft(opening.width_m) == 3.0
    assert opening.provenance == M.Provenance.DRESSED
    assert M.opening_span(wall, opening) == pytest.approx((M.ft_to_m(4.5), M.ft_to_m(7.5)))
    assert model.doors_known(0) is True
    assert "W_DOOR_ASSUMED" not in _codes(model)


def test_dressed_entry_and_window_keep_their_kinds():
    doors = [
        {"id": "d0", "orientation": "h", "x": 6, "y": 0, "width": 3.5, "hinge": "start", "swing": "pos", "entrance": True},
    ]
    windows = [{"id": "w1", "orientation": "h", "x": 6, "y": 12, "width": 4, "sillFt": 3}]
    model = _dressed_model(doors=doors, windows=windows)

    entry_wall = next(w for w in model.walls if _axis_ft(w) == ("v", 22.0, 4.0, 16.0))
    assert [o.kind.value for o in entry_wall.openings] == ["entry"]
    assert _ft(entry_wall.openings[0].offset_m) == 6.0

    window_wall = next(w for w in model.walls if _axis_ft(w) == ("v", 10.0, 4.0, 16.0))
    assert [o.kind.value for o in window_wall.openings] == ["window"]
    assert _ft(window_wall.openings[0].sill_m) == 3.0
    assert window_wall.openings[0].provenance == M.Provenance.DRESSED
    assert M.opening_assumed(window_wall.openings[0]) is False


def test_openings_are_numbered_by_offset_along_the_wall():
    doors = [
        {"id": "d-far", "orientation": "v", "x": 12, "y": 9, "width": 3},
        {"id": "d-near", "orientation": "v", "x": 12, "y": 3, "width": 3},
    ]
    model = _dressed_model(doors=doors, rotation=0)
    wall = _walls_with_openings(model)[0]
    assert _axis_ft(wall) == ("v", 22.0, 4.0, 16.0)
    offsets = [_ft(o.offset_m) for o in wall.openings]
    assert offsets == sorted(offsets)
    assert [o.id for o in wall.openings] == [wall.id + "-op0", wall.id + "-op1"]


def test_unmappable_dressed_door_is_disclosed_not_dropped():
    stray = {"id": "d-lost", "orientation": "h", "x": 6, "y": 5, "width": 3}
    model = _dressed_model(doors=[stray])
    assert _walls_with_openings(model) == []
    entry = next(w for w in model.warnings if w.code == "W_DOOR_UNMAPPED")
    assert "d-lost" in entry.message
    assert entry.severity == M.Severity.WARNING
    assert model.validate() == []


# --------------------------------------------------------------------------
# undressed unit interiors: the 0.9 m mid-wall policy
# --------------------------------------------------------------------------


UNDRESSED_PLAN = _floorplan(
    width=20.0,
    height=20.0,
    placements=(
        _place("Living Room", 0, 0, 10, 10),
        _place("Bedroom 1", 10, 0, 10, 10),
        _place("Balcony", 0, 10, 20, 4),
    ),
)


def _undressed_model(plan=None, **options):
    unit = _unit("u1", 0, 0, 20, 20, floorplans=[plan or UNDRESSED_PLAN])
    return from_building(_building([_floor("f0", 0, units=[unit])]), **options)


def test_assumed_doors_reach_every_room_once():
    model = _undressed_model()
    doors = [(w, o) for w in model.walls for o in w.openings]
    assert len(doors) == 2  # a spanning tree over three rooms
    for wall, opening in doors:
        assert opening.provenance == M.Provenance.ASSUMED_MID_WALL
        assert opening.width_m == pytest.approx(ASSUMED_DOOR_WIDTH_M)
        assert opening.kind == M.OpeningKind.DOOR
        assert _ft(opening.offset_m) == pytest.approx(_ft(wall.length_m()) / 2.0)
        assert M.opening_assumed(opening) is True
    # access hangs off the living room, never through the balcony
    living = _by_name(model, "Living Room").id
    assert all(living in wall.room_ids for wall, _ in doors)
    assert model.doors_known(0) is False
    assert "W_DOOR_ASSUMED" in _codes(model)
    assert "N_WINDOWS_NOT_ASSUMED" in _codes(model)


def test_a_room_sharing_too_little_wall_gets_no_door():
    plan = _floorplan(
        width=20.0,
        height=20.0,
        placements=(
            _place("Living Room", 0, 0, 10, 10),
            _place("Bedroom 1", 10, 0, 10, 10),
            _place("Nook", 0, 10, 2, 10),
        ),
    )
    model = _undressed_model(plan)
    nook = _by_name(model, "Nook").id
    assert all(nook not in w.room_ids for w in _walls_with_openings(model))
    entry = next(w for w in model.warnings if w.code == "W_ADJACENCY_SHORTFALL")
    assert entry.element_ids == [nook]
    assert "W_OCCUPANCY_UNKNOWN" in _codes(model)


def test_windows_are_only_assumed_when_asked_for():
    plain = _undressed_model()
    assert [o for w in plain.walls for o in w.openings if o.kind == M.OpeningKind.WINDOW] == []
    assert "N_WINDOWS_NOT_ASSUMED" in _codes(plain)

    glazed = _undressed_model(assume_windows=True)
    windows = [(w, o) for w in glazed.walls for o in w.openings if o.kind == M.OpeningKind.WINDOW]
    assert windows
    for wall, opening in windows:
        assert opening.width_m == pytest.approx(ASSUMED_WINDOW_WIDTH_M)
        assert wall.role == M.WallRole.EXTERIOR
        assert opening.provenance == M.Provenance.ASSUMED_MID_WALL
    assert "W_ASSUMED_OPENINGS" in _codes(glazed)


def test_balcony_edges_become_railings_never_bearing_walls():
    model = _undressed_model()
    balcony = _by_name(model, "Balcony").id
    railings = [w for w in model.walls if w.role == M.WallRole.RAILING]
    assert railings
    for wall in railings:
        assert balcony in wall.room_ids
        assert wall.bearing is False
        assert _ft(wall.thickness_m) == 0.35
        assert wall.openings == []


def test_occupancy_is_parsed_from_the_room_name():
    plan = _floorplan(
        width=30.0,
        height=20.0,
        placements=(
            _place("Living Room", 0, 0, 10, 10),
            _place("Master Bedroom", 10, 0, 10, 10),
            _place("Bathroom 2", 20, 0, 10, 10),
            _place("Toilet", 0, 10, 10, 10),
            _place("Kitchen", 10, 10, 10, 10),
            _place("Nook", 20, 10, 10, 10),
        ),
    )
    unit = _unit("u1", 0, 0, 30, 20, floorplans=[plan])
    model = from_building(_building([_floor("f0", 0, units=[unit])]))
    seen = {r.name: r.occupancy.value for r in model.rooms}
    assert seen == {
        "Living Room": "habitable",
        "Master Bedroom": "habitable",
        "Bathroom 2": "bath",
        "Toilet": "wc",
        "Kitchen": "kitchen",
        "Nook": "other",
    }
    entry = next(w for w in model.warnings if w.code == "W_OCCUPANCY_UNKNOWN")
    assert "Nook" in entry.message


def test_occupancy_map_overrides_the_name():
    model = _undressed_model(occupancy_map={"Balcony": "utility"})
    assert _by_name(model, "Balcony").occupancy == M.Occupancy.UTILITY


# --------------------------------------------------------------------------
# envelope merging
# --------------------------------------------------------------------------


def test_abutting_units_merge_into_one_party_wall():
    floor = _floor(
        "f0",
        0,
        units=[_unit("u1", 0, 0, 20, 20), _unit("u2", 20, 0, 20, 20)],
        corridors=[{"id": "c1", "x": 0, "y": 20, "width": 40, "height": 6}],
    )
    model = from_building(_building([floor], boundary={"kind": "rect", "width": 40, "height": 26}))

    party = [w for w in model.walls if w.role == M.WallRole.PARTY]
    assert len(party) == 1
    assert _axis_ft(party[0]) == ("v", 20.0, 0.0, 20.0)
    assert party[0].room_ids == ("room-s0-u1", "room-s0-u2")
    assert _ft(party[0].thickness_m) == 0.75  # max(t1, t2)

    # a unit edge meeting the corridor is interior, not party and not exterior
    shared = [w for w in model.walls if _axis_ft(w)[0] == "h" and _axis_ft(w)[1] == 20.0]
    assert len(shared) == 2
    assert {w.role for w in shared} == {M.WallRole.INTERIOR}
    assert all("room-s0-c1" in w.room_ids for w in shared)
    assert model.validate() == []


def test_wall_stacks_align_across_storeys():
    floor = _floor("f0", 0, units=[_unit("u1", 0, 0, 20, 20)])
    model = from_building(_building([floor], total=3, boundary={"kind": "rect", "width": 40, "height": 40}))
    stacks = model.build_wall_stacks()
    assert stacks
    assert all(sorted(stack["walls"]) == [0, 1, 2] for stack in stacks)
    assert all(stack["grounded"] for stack in stacks)


# --------------------------------------------------------------------------
# storey selection, cores, boundary
# --------------------------------------------------------------------------


def test_missing_upper_floors_repeat_the_typical_one(payload):
    taller = json.loads(json.dumps(payload))
    taller["totalFloors"] = 5
    model = from_building(taller)
    assert [s.source_id for s in model.storeys] == ["fl-0", "fl-1", "fl-2", "fl-2", "fl-2"]
    assert [s.name for s in model.storeys] == ["Stilt", "Floor 1", "Floor 2", "Floor 3", "Floor 4"]
    entry = next(w for w in model.warnings if w.code == "W_TYPICAL_REPEATED")
    assert "3, 4" in entry.message
    assert len(model.rooms_on(4)) == len(model.rooms_on(2))
    assert model.validate() == []


def test_stilt_floor_carries_parking_rooms():
    stilt = _floor(
        "f0",
        0,
        kind="stilt",
        parking=[{"id": "p1", "x": 2, "y": 2, "width": 8.2, "height": 16.4}],
    )
    model = from_building(_building([stilt, _floor("f1", 1, units=[_unit("u1", 0, 0, 20, 20)])]))
    bay = model.by_id("room-s0-p1")
    assert bay.occupancy == M.Occupancy.PARKING
    assert _rect_ft(bay) == (2.0, 2.0, 8.2, 16.4)
    assert model.walls_on(0) == []
    assert model.storey(0).kind == M.StoreyKind.STILT


def test_core_overlapping_a_unit_is_disclosed():
    fixed = [{"id": "fe1", "type": "staircase", "label": "Stair", "x": 5, "y": 5, "width": 10, "height": 8}]
    model = from_building(_building([_floor("f0", 0, units=[_unit("u1", 4, 4, 20, 20)])], fixed=fixed))
    entry = next(w for w in model.warnings if w.code == "W_CORE_UNIT_OVERLAP")
    assert entry.element_ids == ["core-fe1"]


def test_unknown_fixed_element_type_ships_as_a_shaft():
    fixed = [{"id": "fe9", "type": "gym", "label": "Gym", "x": 40, "y": 40, "width": 6, "height": 6}]
    model = from_building(_building([_floor("f0", 0)], fixed=fixed))
    assert model.by_id("core-fe9").kind == M.CoreKind.UTILITY_SHAFT
    entry = next(w for w in model.warnings if w.code == "W_OCCUPANCY_UNKNOWN")
    assert "Gym" in entry.message


def test_unit_outside_the_boundary_is_disclosed_and_kept():
    model = from_building(
        _building(
            [_floor("f0", 0, units=[_unit("u1", 50, 10, 20, 10)])],
            boundary={"kind": "rect", "width": 60, "height": 60},
        )
    )
    entry = next(w for w in model.warnings if w.code == "W_UNIT_OUTSIDE_BOUNDARY")
    assert entry.element_ids == ["room-s0-u1"]
    assert model.by_id("room-s0-u1") is not None


def test_rectilinear_polygon_boundary_becomes_six_walls():
    boundary = {"kind": "polygon", "points": [[0, 0], [30, 0], [30, 20], [10, 20], [10, 30], [0, 30]]}
    model = from_building(_building([_floor("f0", 0)], boundary=boundary))
    assert len(model.walls) == 6
    assert {w.role for w in model.walls} == {M.WallRole.EXTERIOR}
    assert model.meta["boundary_ft"][0] == [0.0, 0.0]
    assert model.validate() == []


def test_skew_boundary_edge_is_refused():
    boundary = {"kind": "polygon", "points": [[0, 0], [30, 5], [30, 20], [0, 20]]}
    with pytest.raises(AdapterError) as excinfo:
        from_building(_building([_floor("f0", 0)], boundary=boundary))
    assert excinfo.value.code == "E_BOUNDARY_NOT_RECTILINEAR"


def test_client_structural_grid_is_stored_never_imported():
    grid = {
        "xLines": [{"pos": 0, "source": "outline", "label": "1"}],
        "yLines": [{"pos": 0, "source": "outline", "label": "A"}],
        "columns": [{"id": "col-0-0", "x": 0, "y": 0, "widthFt": 1, "depthFt": 1.5, "rot": 0, "onGrid": ["1", "A"]}],
        "beams": [],
        "columnSize": {"widthFt": 1, "depthFt": 1.5},
        "warnings": [],
    }
    model = from_building(_building([_floor("f0", 0)], structuralGrid=grid))
    assert model.meta["client_grid"] == grid
    assert model.axes == []
    assert model.columns == []
    assert model.beams == []


def test_payload_shape_refusals():
    with pytest.raises(AdapterError) as no_boundary:
        from_building({"totalFloors": 1})
    assert no_boundary.value.code == "E_BAD_ENVELOPE"

    with pytest.raises(AdapterError) as no_storeys:
        from_building(_building([], total=0))
    assert no_storeys.value.code == "E_UNSUPPORTED_STOREYS"

    with pytest.raises(AdapterError) as empty:
        from_building(_building([_floor("f0", 0)], boundary={"kind": "rect", "width": 0, "height": 10}))
    assert empty.value.code == "E_EMPTY_PLAN"


def test_options_travel_into_the_geometry():
    model = from_building(
        _building([_floor("f0", 0, units=[_unit("u1", 0, 0, 20, 20)])]),
        storey_height_ft=12.5,
        exterior_wall_ft=1.0,
        system_hint="load_bearing_masonry",
    )
    assert _ft(model.storey(0).height_m) == 12.5
    assert model.system == M.System.LOAD_BEARING_MASONRY
    assert {_ft(w.thickness_m) for w in model.walls} == {1.0}
    assert model.meta["options"]["system_hint"] == "load_bearing_masonry"
