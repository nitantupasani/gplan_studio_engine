"""adapters/housing.py: HousingDesign -> one StructuralModel per built plot stack.

The committed fixture drives the happy path (a real two storey house with a
generated 1BHK, a stair core, a gable roof and an entry); the synthetic designs
built here drive the paths a single fixture cannot hold at once: several plots,
the caller-resolved region path, a stale generated plan, and the four refusals.

Feet are the payload's units and metres are the model's, so every assertion that
names a coordinate converts with `m_to_ft` and reads in the numbers the fixture
was written with.
"""

from __future__ import annotations

import copy
import json
import os

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests and an absolute GPLAN.structural
# import would resolve against the outer directory instead.
from ..adapters import housing
from ..model import (
    CoreKind,
    ModelSource,
    Occupancy,
    OpeningKind,
    Provenance,
    StoreyKind,
    System,
    WallRole,
    ft_to_m,
    m_to_ft,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

#: Coordinate tolerance in FEET; the adapter's own geometry tolerance is 1 mm.
FT_TOL = 1e-6


def _load(name):
    with open(os.path.join(FIXTURES, name), "r") as fh:
        return json.load(fh)


@pytest.fixture
def design():
    return _load("housing_2storey.json")


@pytest.fixture
def model(design):
    models = housing.from_housing(design)
    return models[0]


def _rect_ft(room):
    """(x, y, w, h) of a RoomPoly in feet."""
    xs = [m_to_ft(p[0]) for p in room.polygon]
    ys = [m_to_ft(p[1]) for p in room.polygon]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _wall_ft(wall):
    """(x1, y1, x2, y2) of a WallLine centreline in feet."""
    return (m_to_ft(wall.a[0]), m_to_ft(wall.a[1]), m_to_ft(wall.b[0]), m_to_ft(wall.b[1]))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Master Bedroom", Occupancy.HABITABLE),
        ("Master Bath", Occupancy.BATH),
        ("Guest Toilet", Occupancy.WC),
    ],
)
def test_room_name_matching_uses_complete_tokens_and_wet_rooms_win(name, expected):
    occupancy, recognized = housing._occupancy_for_name(name)
    assert recognized is True
    assert occupancy == expected


def _openings(model, kind):
    out = []
    for wall in model.walls:
        for opening in wall.openings:
            if opening.kind == kind:
                out.append((wall, opening))
    return out


def _codes(model):
    return sorted(entry.code for entry in model.warnings)


# --------------------------------------------------------------------------
# the committed fixture: one built stack, two storeys
# --------------------------------------------------------------------------


def test_fixture_yields_exactly_one_model_for_the_primary_stack(design):
    models = housing.from_housing(design)
    assert len(models) == 1, "the fixture draws one plot, so one model"
    model = models[0]
    assert model.source == ModelSource.HOUSING
    assert model.system == System.RC_FRAME
    assert model.id == "hd-fx1-primary"
    assert model.meta["plot_id"] == "primary"
    assert len(model.fingerprint) == 64, "the fingerprint is a sha256 hex digest"


def test_split_plot_stacks_reports_the_primary_stack_as_built(design):
    stacks = housing.split_plot_stacks(design)
    assert [s["plot_id"] for s in stacks] == ["primary"]
    assert stacks[0]["built"] is True
    assert [record["level"] for record in stacks[0]["floors"]] == [0, 1]


def test_storeys_are_two_at_10_4_ft_with_a_half_foot_plinth_on_meta(model):
    assert [s.index for s in model.storeys] == [0, 1]
    assert [s.name for s in model.storeys] == ["Ground", "First"]
    for storey in model.storeys:
        assert m_to_ft(storey.height_m) == pytest.approx(10.4, abs=FT_TOL)
        assert storey.kind == StoreyKind.UNITS
    assert m_to_ft(model.storeys[0].bottom_z_m) == pytest.approx(0.0, abs=FT_TOL)
    assert m_to_ft(model.storeys[1].bottom_z_m) == pytest.approx(10.4, abs=FT_TOL)
    # the plinth is meta, never a storey: the z datum stays the ground floor level
    assert model.meta["plinth_height_ft"] == pytest.approx(0.5)
    assert model.meta["north"] == "-y"


def test_gable_roof_lands_on_meta_with_its_rise_ratio(model):
    assert model.meta["roof"] == {
        "type": "gable",
        "rise_ratio": 0.3,
        "overhang_ft": 1.0,
        "on": "bbox",
    }


def test_flat_is_the_default_roof_when_the_payload_names_none(design):
    design.pop("roof")
    model = housing.from_housing(design)[0]
    assert model.meta["roof"]["type"] == "flat"
    assert model.meta["roof"]["rise_ratio"] == 0.0


def test_the_stair_core_is_one_element_standing_on_both_storeys(model):
    assert len(model.cores) == 1
    core = model.cores[0]
    assert core.id == "core-core-stairs"
    assert core.kind == CoreKind.STAIRS
    assert core.storeys == [0, 1]
    assert m_to_ft(core.x_m) == pytest.approx(20.0, abs=FT_TOL)
    assert m_to_ft(core.y_m) == pytest.approx(26.0, abs=FT_TOL)
    assert m_to_ft(core.w_m) == pytest.approx(7.0, abs=FT_TOL)
    assert m_to_ft(core.h_m) == pytest.approx(10.0, abs=FT_TOL)
    assert core.stair_landing_hint is None
    assert "W_NO_STAIR" not in _codes(model)


def test_the_generated_plan_lands_at_absolute_floor_coordinates(model):
    """The fixture's 1BHK fills the (0,0)-(14,22) region, so local == absolute."""
    placed = sorted(
        [r for r in model.rooms if r.unit_id == "region-0"], key=lambda r: r.id
    )
    assert [r.name for r in placed] == ["Living Room", "Kitchen", "Bathroom", "Bedroom 1"]
    assert [_rect_ft(r) for r in placed] == [
        pytest.approx((0.0, 0.0, 14.0, 9.0), abs=FT_TOL),
        pytest.approx((0.0, 9.0, 8.0, 6.0), abs=FT_TOL),
        pytest.approx((8.0, 9.0, 6.0, 6.0), abs=FT_TOL),
        pytest.approx((0.0, 15.0, 14.0, 7.0), abs=FT_TOL),
    ]
    assert [r.occupancy for r in placed] == [
        Occupancy.HABITABLE,
        Occupancy.KITCHEN,
        Occupancy.BATH,
        Occupancy.HABITABLE,
    ]
    for room in placed:
        assert room.storey == 0
        assert room.interior_unknown is False
    # the region itself is not also a room: its unit plan replaced it
    assert not [r for r in model.rooms if r.id == "room-s0-region-0"]
    assert "W_STALE_GENERATED" not in _codes(model)


def test_the_placed_plan_gets_derived_interior_walls_and_assumed_doors(model):
    interior = [w for w in model.walls if w.storey == 0 and w.role == WallRole.INTERIOR]
    lines = sorted(_wall_ft(w) for w in interior)
    assert lines == [
        # derived from the placed plan: each pair of collinear room interfaces
        # (living/kitchen with living/bath, kitchen/bed with bath/bed) is ONE wall
        pytest.approx((0.0, 9.0, 14.0, 9.0), abs=FT_TOL),
        pytest.approx((0.0, 15.0, 14.0, 15.0), abs=FT_TOL),
        pytest.approx((0.0, 22.0, 30.0, 22.0), abs=FT_TOL),  # seg-h1
        pytest.approx((8.0, 9.0, 8.0, 15.0), abs=FT_TOL),
        pytest.approx((14.0, 0.0, 14.0, 22.0), abs=FT_TOL),  # seg-v1
        pytest.approx((18.0, 22.0, 18.0, 40.0), abs=FT_TOL),  # seg-v2
    ]

    doors = _openings(model, OpeningKind.DOOR)
    assert len(doors) == 3, "four rooms need three doors to all be reachable"
    for _wall, opening in doors:
        assert opening.width_m == pytest.approx(0.9), "the unified assumed door width"
        assert opening.provenance == Provenance.ASSUMED_MID_WALL
    assert "W_DOOR_ASSUMED" in _codes(model)
    assert model.doors_known(0) is False


def test_the_entry_opening_sits_on_the_south_wall_of_the_ground_storey(model):
    entries = _openings(model, OpeningKind.ENTRY)
    assert len(entries) == 1
    wall, opening = entries[0]
    assert wall.storey == 0
    assert wall.role == WallRole.EXTERIOR
    x1, y1, x2, y2 = _wall_ft(wall)
    assert (y1, y2) == pytest.approx((40.0, 40.0), abs=FT_TOL), "north is -y, so south is max y"
    assert (x1, x2) == pytest.approx((0.0, 30.0), abs=FT_TOL)
    assert m_to_ft(opening.offset_m) == pytest.approx(15.0, abs=FT_TOL), "entry [15, 40]"
    assert m_to_ft(opening.width_m) == pytest.approx(3.5, abs=FT_TOL)
    assert opening.provenance == Provenance.ENTRY_POINT
    assert model.meta["entry_ft"] == pytest.approx([15.0, 40.0], abs=FT_TOL)


def test_the_entry_falls_back_to_the_southernmost_run_midpoint(design):
    design.pop("entry")
    model = housing.from_housing(design)[0]
    _wall, opening = _openings(model, OpeningKind.ENTRY)[0]
    assert m_to_ft(opening.offset_m) == pytest.approx(15.0, abs=FT_TOL)
    assert model.meta["entry_ft"] == pytest.approx([15.0, 40.0], abs=FT_TOL)


def test_boundary_walls_are_exterior_and_drawn_walls_interior(model):
    exterior = [w for w in model.walls if w.storey == 0 and w.role == WallRole.EXTERIOR]
    assert len(exterior) == 4
    for wall in exterior:
        assert m_to_ft(wall.thickness_m) == pytest.approx(0.5, abs=FT_TOL)
    drawn = [w for w in model.walls if w.storey == 0 and w.role == WallRole.INTERIOR]
    for wall in drawn:
        assert m_to_ft(wall.thickness_m) == pytest.approx(1.0 / 3.0, abs=1e-4), (
            "interior thickness comes from wallDisplay.interiorWallFt")
    core_walls = [w for w in model.walls if w.role == WallRole.CORE]
    assert len(core_walls) == 8, "four core edges on each of the two storeys"


def test_the_model_passes_its_own_invariants_and_round_trips(model):
    assert model.validate() == []
    wire = model.to_dict()
    assert wire["source"] == "housing"
    assert wire["meta"]["roof"]["type"] == "gable"
    assert len(wire["rooms"]) == len(model.rooms)


def test_two_runs_of_one_payload_are_byte_identical(design):
    first = housing.from_housing(design)[0]
    second = housing.from_housing(copy.deepcopy(design))[0]
    assert first.fingerprint == second.fingerprint
    assert first.to_dict() == second.to_dict()


# --------------------------------------------------------------------------
# synthetic designs
# --------------------------------------------------------------------------


def _rect(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _floor(level, label, boundary, segments=(), shapes=(), plots=(), region_content=None):
    return {
        "id": "hf-%d" % level,
        "level": level,
        "label": label,
        "boundary": boundary,
        "segments": [
            {"id": s[0], "x1": s[1], "y1": s[2], "x2": s[3], "y2": s[4]} for s in segments
        ],
        "shapes": list(shapes),
        "plots": list(plots),
        "regionContent": dict(region_content or {}),
    }


def _design(floors, roof=None, entry=None, interior_wall_ft=1.0 / 3.0):
    payload = {
        "id": "hd-syn",
        "name": "Synthetic",
        "floors": floors,
        "wallDisplay": {"showInteriorWalls": True, "interiorWallFt": interior_wall_ft},
        "createdAt": "2026-08-29T00:00:00Z",
    }
    if roof is not None:
        payload["roof"] = roof
    if entry is not None:
        payload["entry"] = entry
    return payload


def _core_shape(shape_id, core_id, kind, x, y, w, h):
    return {"id": shape_id, "points": _rect(x, y, w, h), "core": {"id": core_id, "kind": kind}}


def _generated(gen_w, gen_h, placements, plan_id="pl-1", plan_w=None, plan_h=None, detailed=None):
    plan_w = gen_w if plan_w is None else plan_w
    plan_h = gen_h if plan_h is None else plan_h
    content = {
        "generated": {
            "requestedType": "1BHK",
            "builtType": "1BHK",
            "selectedPlanId": plan_id,
            "genW": gen_w,
            "genH": gen_h,
            "plans": [
                {
                    "id": plan_id,
                    "label": "Plan 1",
                    "floorWidth": plan_w,
                    "floorHeight": plan_h,
                    "placements": [
                        {"name": p[0], "x": p[1], "y": p[2], "width": p[3], "height": p[4]}
                        for p in placements
                    ],
                }
            ],
        }
    }
    if detailed is not None:
        content["generated"]["plans"][0]["detailedPlan"] = detailed
    return content


def test_two_built_plots_give_two_models_and_plot_id_filters_to_one():
    plots = [{"id": "plot-b", "boundary": _rect(40, 0, 30, 40)}]
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-a", 0, 20, 30, 20), ("seg-b", 40, 20, 70, 20)],
        plots=plots,
    )
    design = _design([floor])

    stacks = housing.split_plot_stacks(design)
    assert [s["plot_id"] for s in stacks] == ["primary", "plot-b"]
    assert [s["built"] for s in stacks] == [True, True]
    # a wall belongs to the plot that contains it, never to both
    assert [s["id"] for s in stacks[0]["floors"][0]["segments"]] == ["seg-a"]
    assert [s["id"] for s in stacks[1]["floors"][0]["segments"]] == ["seg-b"]

    models = housing.from_housing(design)
    assert [m.meta["plot_id"] for m in models] == ["primary", "plot-b"]
    assert [m.id for m in models] == ["hd-syn-primary", "hd-syn-plot-b"]
    assert models[0].fingerprint != models[1].fingerprint

    only = housing.from_housing(design, plot_id="plot-b")
    assert len(only) == 1
    assert only[0].meta["plot_id"] == "plot-b"
    # filtering changes the request record, never the structure or its dedup key
    assert only[0].fingerprint == models[1].fingerprint
    slices = ("storeys", "axes", "walls", "rooms", "cores")
    assert [only[0].to_dict()[k] for k in slices] == [models[1].to_dict()[k] for k in slices]
    assert only[0].meta["options"]["plot_id"] == "plot-b"
    assert models[1].meta["options"]["plot_id"] is None
    xs = [m_to_ft(w.a[0]) for w in only[0].walls]
    assert min(xs) >= 40.0 - FT_TOL, "the second model carries only its own plot"


def test_fingerprint_changes_for_roof_entry_and_design_name():
    """Every design field that reaches the model must invalidate its dedup key (N9)."""
    floor = _floor(0, "Ground", _rect(0, 0, 30, 20), segments=[("split", 0, 10, 30, 10)])
    baseline = _design([floor])
    roof_changed = copy.deepcopy(baseline)
    roof_changed["roof"] = {"type": "gable", "riseRatio": 0.3, "overhangFt": 1.0}
    entry_changed = copy.deepcopy(baseline)
    entry_changed["entry"] = [0, 4]
    name_changed = copy.deepcopy(baseline)
    name_changed["name"] = "Synthetic renamed"

    fingerprints = {
        housing.from_housing(payload)[0].fingerprint
        for payload in (baseline, roof_changed, entry_changed, name_changed)
    }
    assert len(fingerprints) == 4


def test_a_parking_only_plot_is_reported_unbuilt_and_produces_no_model():
    plots = [
        {"id": "plot-park", "boundary": _rect(40, 0, 20, 20), "content": {"space": {"kind": "parking"}}},
        {"id": "plot-green", "boundary": _rect(40, 25, 20, 15), "content": {"space": {"kind": "green"}}},
    ]
    floor = _floor(
        0, "Ground", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)], plots=plots
    )
    design = _design([floor])

    stacks = dict((s["plot_id"], s["built"]) for s in housing.split_plot_stacks(design))
    assert stacks == {"primary": True, "plot-park": False, "plot-green": False}

    models = housing.from_housing(design)
    assert [m.meta["plot_id"] for m in models] == ["primary"]
    assert models[0].meta["stacks"] == [
        {"plot_id": "primary", "built": True},
        {"plot_id": "plot-green", "built": False},
        {"plot_id": "plot-park", "built": False},
    ]

    with pytest.raises(housing.AdapterError) as refusal:
        housing.from_housing(design, plot_id="plot-park")
    assert refusal.value.code == "E_EMPTY_PLAN"


def test_resolved_regions_carry_their_own_content_and_skip_derivation():
    """The caller's faces are the frontend's own; no key parsing is needed."""
    floor = _floor(0, "Ground", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)])
    design = _design([floor])
    resolved = {
        "hf-0": [
            {"points": _rect(0, 0, 30, 20), "content": {"space": {"kind": "parking"}}},
            {"points": _rect(0, 20, 30, 20), "content": {"space": {"kind": "lobby"}}},
        ]
    }
    model = housing.from_housing(design, resolved_regions=resolved)[0]
    assert model.meta["regions"] == "caller"
    rooms = sorted(model.rooms, key=lambda r: r.id)
    assert [r.id for r in rooms] == ["room-s0-region-0", "room-s0-region-1"]
    assert [r.occupancy for r in rooms] == [Occupancy.PARKING, Occupancy.LOBBY]
    assert [_rect_ft(r) for r in rooms] == [
        pytest.approx((0.0, 0.0, 30.0, 20.0), abs=FT_TOL),
        pytest.approx((0.0, 20.0, 30.0, 20.0), abs=FT_TOL),
    ]
    assert [r.interior_unknown for r in rooms] == [False, False]
    assert "W_REGION_CONTENT_UNMATCHED" not in _codes(model)


def test_resolved_content_is_not_falsely_disclosed_as_dropped():
    """Content may arrive on resolved faces and regionContent together (N10)."""
    parking = {"space": {"kind": "parking"}}
    lobby = {"space": {"kind": "lobby"}}
    first_key = "0,0;30,0;30,20;0,20"
    second_key = "0,20;30,20;30,40;0,40"
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-a", 0, 20, 30, 20)],
        region_content={first_key: parking, second_key: lobby},
    )
    resolved = {
        "hf-0": [
            {"points": _rect(0, 0, 30, 20), "content": parking},
            {"points": _rect(0, 20, 30, 20)},
        ]
    }
    model = housing.from_housing(_design([floor]), resolved_regions=resolved)[0]
    assert [room.occupancy for room in sorted(model.rooms, key=lambda room: room.id)] == [
        Occupancy.PARKING,
        Occupancy.LOBBY,
    ]
    assert "W_REGION_CONTENT_UNMATCHED" not in _codes(model)


def test_derived_regions_take_content_by_interior_point_containment():
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-a", 0, 20, 30, 20)],
        region_content={
            "0,20;30,20;30,40;0,40": {"space": {"kind": "corridor"}},
            "an opaque key": {"space": {"kind": "lobby"}},
        },
    )
    model = housing.from_housing(_design([floor]))[0]
    assert model.meta["regions"] == "polygonize"
    by_id = dict((r.id, r) for r in model.rooms)
    assert by_id["room-s0-region-1"].occupancy == Occupancy.CORRIDOR
    assert by_id["room-s0-region-0"].interior_unknown is True, "the unlabeled half"
    assert "W_REGION_CONTENT_UNMATCHED" in _codes(model), "the opaque key is disclosed"
    assert "W_UNIT_NO_PLAN" in _codes(model)


def test_boundary_content_routes_a_whole_plot_generated_plan_into_rooms():
    """A segment-free floor can store its plan only on boundaryContent (C2)."""
    floor = _floor(0, "Ground", _rect(0, 0, 30, 20))
    floor["boundaryContent"] = _generated(
        30, 20, [("Living Room", 0, 0, 30, 12), ("Bedroom 1", 0, 12, 30, 8)]
    )
    model = housing.from_housing(_design([floor]))[0]
    rooms = sorted((room.name, _rect_ft(room)) for room in model.rooms)
    assert rooms == [
        ("Bedroom 1", pytest.approx((0.0, 12.0, 30.0, 8.0), abs=FT_TOL)),
        ("Living Room", pytest.approx((0.0, 0.0, 30.0, 12.0), abs=FT_TOL)),
    ]
    assert "W_UNIT_NO_PLAN" not in _codes(model)
    assert "W_REGION_CONTENT_UNMATCHED" not in _codes(model)


def test_additional_plot_content_routes_a_generated_plan_into_its_stack():
    """An additional plot's own content is just as structural as regionContent (C2)."""
    plot = {
        "id": "plot-b",
        "boundary": _rect(40, 0, 12, 10),
        "content": _generated(12, 10, [("Living Room", 0, 0, 12, 10)]),
    }
    floor = _floor(0, "Ground", _rect(0, 0, 30, 20), plots=[plot])
    model = housing.from_housing(_design([floor]))[0]
    assert model.meta["plot_id"] == "plot-b"
    room = model.rooms[0]
    assert room.name == "Living Room"
    assert _rect_ft(room) == pytest.approx((40.0, 0.0, 12.0, 10.0), abs=FT_TOL)
    assert "W_REGION_CONTENT_UNMATCHED" not in _codes(model)


def test_drawn_shape_content_routes_a_generated_plan_into_its_own_face():
    """A non-core shape's content is not allowed to disappear after parsing (C2)."""
    shape = {
        "id": "shape-unit",
        "points": _rect(10, 5, 12, 10),
        "content": _generated(12, 10, [("Living Room", 0, 0, 12, 10)]),
    }
    floor = _floor(0, "Ground", _rect(0, 0, 30, 20), shapes=[shape])
    model = housing.from_housing(_design([floor]))[0]
    rooms = [room for room in model.rooms if room.unit_id is not None]
    assert len(rooms) == 1
    assert rooms[0].name == "Living Room"
    assert _rect_ft(rooms[0]) == pytest.approx((10.0, 5.0, 12.0, 10.0), abs=FT_TOL)
    assert "W_REGION_CONTENT_UNMATCHED" not in _codes(model)


def test_region_key_prefers_its_equal_host_face_over_a_nested_shape():
    """The island at the host origin used to steal the host's content (B3)."""
    outer = housing._normalize_loop(housing._loop_m(_rect(0, 0, 30, 20)))
    inner = housing._normalize_loop(housing._loop_m(_rect(0, 0, 6, 6)))
    faces = [
        {"loop": inner, "interior": housing._interior_point(inner), "content": None, "core": None},
        {"loop": outer, "interior": housing._interior_point(outer), "content": None, "core": None},
    ]
    content = {"space": {"kind": "lobby"}}
    unmatched = housing._match_region_content(faces, {"0,0;30,0;30,20;0,20": content})
    assert unmatched == []
    assert faces[0]["content"] is None
    assert faces[1]["content"] == content


def test_generated_plan_is_carved_around_a_nested_core_face():
    """The host face is net of the core, so its generated rooms must be net too (N7)."""
    core = _core_shape("shape-core", "core-stairs", "stairs", 10, 5, 6, 6)
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 20),
        shapes=[core],
        region_content={
            "0,0;30,0;30,20;0,20": _generated(30, 20, [("Living Room", 0, 0, 30, 20)])
        },
    )
    model = housing.from_housing(_design([floor]))[0]
    placed_area = sum(room.area_m2 for room in model.rooms if room.unit_id is not None)
    core_area = sum(room.area_m2 for room in model.rooms if room.occupancy == Occupancy.STAIR)
    assert placed_area == pytest.approx(ft_to_m(1.0) ** 2 * (30.0 * 20.0 - 6.0 * 6.0))
    assert placed_area + core_area == pytest.approx(ft_to_m(1.0) ** 2 * 30.0 * 20.0)
    assert "W_CORE_UNIT_OVERLAP" not in _codes(model)
    assert model.validate() == []


#: The user's saved 30 x 40 ft 2BHK (library design "Housing 2BHK", plan 1), the plan
#: behind the mid-room-columns report. The stair placement carries the client's float
#: noise on purpose: it is what the carve has to survive.
CORNER_CORE_PLAN = [
    ("Living Room", 0, 17, 14, 13),
    ("Dining", 0, 4, 14, 13),
    ("Kitchen", 14, 0, 16, 16.12),
    ("Bedroom", 14, 16.12, 16, 11.88),
    ("Bedroom 2", 14, 28, 16, 12),
    ("Bathroom", 7, 30, 7, 10),
    ("Toilet", 0, 0, 14, 4),
    ("Staircase", 0, 29.999999999999996, 7, 10.000000000000004),
]


def test_boundary_content_survives_a_core_touching_the_plot_corner():
    """A mandatory stair core at the plot corner notches the boundary face, so no
    face EQUALS the boundary; the plan on boundaryContent must still be read.
    Dropping it solved the frame for an empty plot: outline + core edges + even
    span stations, every interior column in the middle of a room."""
    core = _core_shape("shape-core", "core-stairs", "stairs", 0, 30, 7, 10)
    floor = _floor(0, "Ground", _rect(0, 0, 30, 40), shapes=[core])
    floor["boundaryContent"] = _generated(30, 40, CORNER_CORE_PLAN)
    model = housing.from_housing(_design([floor]))[0]
    codes = _codes(model)
    assert "W_UNIT_NO_PLAN" not in codes
    assert "W_REGION_CONTENT_UNMATCHED" not in codes
    placed = [room for room in model.rooms if room.unit_id is not None]
    assert sorted(room.name for room in placed) == sorted(
        name for name, _x, _y, _w, _h in CORNER_CORE_PLAN if name != "Staircase"
    ), "the stair placement is carved away by the core, the seven rooms stay"
    stairs = [room for room in model.rooms if room.occupancy == Occupancy.STAIR]
    assert len(stairs) == 1
    # the plan is placed in the PLOT frame at scale 1, not fitted to the notched face
    kitchen = next(room for room in placed if room.name == "Kitchen")
    assert _rect_ft(kitchen) == pytest.approx((14.0, 0.0, 16.0, 16.12), abs=FT_TOL)
    placed_area = sum(room.area_m2 for room in placed)
    assert placed_area + stairs[0].area_m2 == pytest.approx(ft_to_m(1.0) ** 2 * 30.0 * 40.0)
    # the plan's walls reach the model: the dining/kitchen line at x = 14 ft
    interior = [_wall_ft(w) for w in model.walls if w.role == WallRole.INTERIOR]
    assert any(abs(x1 - 14.0) < FT_TOL and abs(x2 - 14.0) < FT_TOL for x1, _y1, x2, _y2 in interior)
    assert "W_CORE_UNIT_OVERLAP" not in codes
    assert model.validate() == []


def test_boundary_content_survives_a_core_on_a_full_plot_edge():
    """With the core across a whole edge the remaining face is a smaller rectangle;
    the plan must not be shrunk into it, it was authored for the plot."""
    core = _core_shape("shape-core", "core-stairs", "stairs", 0, 30, 30, 10)
    floor = _floor(0, "Ground", _rect(0, 0, 30, 40), shapes=[core])
    floor["boundaryContent"] = _generated(
        30, 40, [("Living Room", 0, 0, 30, 30), ("Staircase", 0, 30, 30, 10)]
    )
    model = housing.from_housing(_design([floor]))[0]
    codes = _codes(model)
    assert "W_UNIT_NO_PLAN" not in codes
    assert "W_REGION_CONTENT_UNMATCHED" not in codes
    placed = [room for room in model.rooms if room.unit_id is not None]
    assert [room.name for room in placed] == ["Living Room"]
    assert _rect_ft(placed[0]) == pytest.approx((0.0, 0.0, 30.0, 30.0), abs=FT_TOL)
    assert len([room for room in model.rooms if room.occupancy == Occupancy.STAIR]) == 1
    assert model.validate() == []


def test_boundary_content_beside_a_partition_and_a_core_is_still_disclosed():
    """Two eligible faces inside the boundary is derivation drift, not a guess."""
    core = _core_shape("shape-core", "core-stairs", "stairs", 0, 30, 7, 10)
    floor = _floor(
        0, "Ground", _rect(0, 0, 30, 40), segments=[("seg-1", 15, 0, 15, 40)], shapes=[core]
    )
    floor["boundaryContent"] = _generated(30, 40, [("Living Room", 0, 0, 30, 40)])
    model = housing.from_housing(_design([floor]))[0]
    codes = _codes(model)
    assert "W_REGION_CONTENT_UNMATCHED" in codes
    assert "W_UNIT_NO_PLAN" in codes
    assert not [room for room in model.rooms if room.unit_id is not None]


def test_a_carved_placement_equal_to_its_blocker_leaves_no_sliver():
    """The client's float noise opened a zero-height row that survived as a room."""
    pieces = housing._unblocked_rectangles(
        0.0,
        ft_to_m(29.999999999999996),
        ft_to_m(7.0),
        ft_to_m(10.000000000000004),
        [(0.0, ft_to_m(30.0), ft_to_m(7.0), ft_to_m(10.0))],
    )
    assert pieces == []


def test_a_region_border_with_no_drawn_wall_is_not_a_wall():
    """Open plan is a real answer: only drawn geometry becomes a WallLine."""
    floor = _floor(0, "Ground", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)])
    resolved = {
        "hf-0": [
            {"points": _rect(0, 0, 30, 20)},
            {"points": _rect(0, 20, 15, 20)},
            {"points": _rect(15, 20, 15, 20)},
        ]
    }
    model = housing.from_housing(_design([floor]), resolved_regions=resolved)[0]
    assert len(model.rooms) == 3
    interior = [_wall_ft(w) for w in model.walls if w.role == WallRole.INTERIOR]
    assert interior == [pytest.approx((0.0, 20.0, 30.0, 20.0), abs=FT_TOL)], (
        "the drawn segment is a wall; the x=15 border between two regions is not")
    assert len([w for w in model.walls if w.role == WallRole.EXTERIOR]) == 4


def test_collinear_spans_drawn_twice_merge_into_one_wall():
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-a", 0, 20, 20, 20), ("seg-b", 10, 20, 30, 20)],
    )
    model = housing.from_housing(_design([floor]))[0]
    on_line = [w for w in model.walls if abs(m_to_ft(w.a[1]) - 20.0) < FT_TOL]
    assert len(on_line) == 1, "the overlapping runs are one wall, never two"
    assert _wall_ft(on_line[0]) == pytest.approx((0.0, 20.0, 30.0, 20.0), abs=FT_TOL)


def test_centrelines_within_115_mm_are_one_wall():
    """0.115 m is the grid-regularization tolerance; 0.3 ft is inside it."""
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-a", 0, 20, 30, 20), ("seg-b", 10, 20.3, 20, 20.3)],
    )
    model = housing.from_housing(_design([floor]))[0]
    interior = [w for w in model.walls if w.role == WallRole.INTERIOR]
    assert len(interior) == 1
    assert _wall_ft(interior[0]) == pytest.approx((0.0, 20.0, 30.0, 20.0), abs=FT_TOL), (
        "the longer run holds the centreline the shorter one is absorbed into")

    apart = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-a", 0, 20, 30, 20), ("seg-b", 10, 20.6, 20, 20.6)],
    )
    two = housing.from_housing(_design([apart]))[0]
    assert len([w for w in two.walls if w.role == WallRole.INTERIOR]) == 2, (
        "0.6 ft is past the tolerance, so these are two walls")


def test_a_wall_drawn_along_the_plot_edge_still_belongs_to_the_plot():
    """It merges into the boundary wall rather than being dropped for sitting on it."""
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 40),
        segments=[("seg-edge", 0, 0, 30, 0), ("seg-a", 0, 20, 30, 20)],
    )
    stack = housing.split_plot_stacks(_design([floor]))[0]
    assert [s["id"] for s in stack["floors"][0]["segments"]] == ["seg-a", "seg-edge"]
    model = housing.from_housing(_design([floor]))[0]
    north = [w for w in model.walls if abs(m_to_ft(w.a[1])) < FT_TOL and abs(m_to_ft(w.b[1])) < FT_TOL]
    assert len(north) == 1, "the duplicate run is absorbed, never doubled"
    assert north[0].role == WallRole.EXTERIOR, "absorbing an interior run cannot demote it"
    assert "seg-edge" in (north[0].source or "")


def test_a_generated_block_with_no_plan_degrades_to_an_unknown_interior():
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 22),
        segments=[("seg-v", 14, 0, 14, 22)],
        region_content={"0,0;14,0;14,22;0,22": _generated(14, 22, [])},
    )
    model = housing.from_housing(_design([floor]))[0]
    room = [r for r in model.rooms if r.id == "room-s0-region-0"][0]
    assert room.interior_unknown is True, "no plan means the partition allowance path"
    assert room.unit_id is None
    assert "W_UNIT_NO_PLAN" in _codes(model)
    assert "W_DOOR_ASSUMED" not in _codes(model)


def test_a_generated_plan_is_translated_by_its_region_origin():
    """Same 1BHK, region at x=16: every placement moves with the region."""
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 22),
        segments=[("seg-v", 16, 0, 16, 22)],
        region_content={
            "16,0;30,0;30,22;16,22": _generated(
                14,
                22,
                [
                    ("Living Room", 0, 0, 14, 9),
                    ("Kitchen", 0, 9, 8, 6),
                    ("Bathroom", 8, 9, 6, 6),
                    ("Bedroom 1", 0, 15, 14, 7),
                ],
            )
        },
    )
    model = housing.from_housing(_design([floor]))[0]
    placed = sorted([r for r in model.rooms if r.unit_id], key=lambda r: r.id)
    assert [_rect_ft(r) for r in placed] == [
        pytest.approx((16.0, 0.0, 14.0, 9.0), abs=FT_TOL),
        pytest.approx((16.0, 9.0, 8.0, 6.0), abs=FT_TOL),
        pytest.approx((24.0, 9.0, 6.0, 6.0), abs=FT_TOL),
        pytest.approx((16.0, 15.0, 14.0, 7.0), abs=FT_TOL),
    ]
    assert "W_STALE_GENERATED" not in _codes(model)


def test_detailed_plan_geometry_overrides_placements_and_maps_its_door():
    """An inline wall edit lives only in detailedPlan; structure must read it."""
    detail = {
        "id": "detail-1",
        "source": "api",
        "width": 18,
        "height": 20,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 9, "height": 20},
            {"id": "kitchen", "name": "Kitchen", "kind": "kitchen", "x": 9, "y": 0, "width": 9, "height": 20},
        ],
        "doors": [
            {"id": "door-1", "orientation": "v", "x": 9, "y": 10, "width": 3}
        ],
        "windows": [],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 18, 20))
    floor["boundaryContent"] = _generated(
        18,
        20,
        [("Living Room", 0, 0, 12, 20), ("Kitchen", 12, 0, 6, 20)],
        detailed=detail,
    )
    model = housing.from_housing(_design([floor]))[0]

    placed = sorted([room for room in model.rooms if room.unit_id], key=lambda room: room.name)
    assert [_rect_ft(room) for room in placed] == [
        pytest.approx((9.0, 0.0, 9.0, 20.0), abs=FT_TOL),
        pytest.approx((0.0, 0.0, 9.0, 20.0), abs=FT_TOL),
    ]
    interior = [_wall_ft(wall) for wall in model.walls if wall.role == WallRole.INTERIOR]
    assert any(
        abs(x1 - 9.0) < FT_TOL and abs(x2 - 9.0) < FT_TOL
        for x1, _y1, x2, _y2 in interior
    )
    assert not any(
        abs(x1 - 12.0) < FT_TOL and abs(x2 - 12.0) < FT_TOL
        for x1, _y1, x2, _y2 in interior
    ), "stale placements must not leak their old shared wall into structure"
    doors = _openings(model, OpeningKind.DOOR)
    assert len(doors) == 1
    wall, opening = doors[0]
    assert _wall_ft(wall) == pytest.approx((9.0, 0.0, 9.0, 20.0), abs=FT_TOL)
    assert m_to_ft(opening.width_m) == pytest.approx(3.0, abs=FT_TOL)
    assert opening.provenance == Provenance.DRESSED
    assert "W_DOOR_ASSUMED" not in _codes(model)


def test_detailed_plan_dimensions_are_the_frame_for_edited_room_geometry():
    detail = {
        "id": "detail-resized",
        "source": "api",
        "width": 18,
        "height": 20,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 18, "height": 20}
        ],
        "doors": [],
        "windows": [],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 18, 20))
    floor["boundaryContent"] = _generated(
        18,
        20,
        [("Living Room", 0, 0, 12, 20)],
        plan_w=12,
        plan_h=20,
        detailed=detail,
    )
    model = housing.from_housing(_design([floor]))[0]
    room = next(room for room in model.rooms if room.unit_id)
    assert _rect_ft(room) == pytest.approx((0.0, 0.0, 18.0, 20.0), abs=FT_TOL)
    assert "W_STALE_GENERATED" not in _codes(model)


def test_detailed_plan_preserves_an_l_room_outline_and_its_reflex_walls():
    detail = {
        "id": "detail-l",
        "source": "api",
        "width": 12,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {
                "id": "living-l",
                "name": "Living Room",
                "kind": "living",
                "x": 0,
                "y": 0,
                "width": 12,
                "height": 10,
                "outline": [[0, 0], [12, 0], [12, 4], [6, 4], [6, 10], [0, 10]],
            },
            {"id": "bed", "name": "Bedroom", "kind": "bedroom", "x": 6, "y": 4, "width": 6, "height": 6},
        ],
        "doors": [],
        "windows": [],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 12, 10))
    floor["boundaryContent"] = _generated(
        12, 10, [("Living Room", 0, 0, 12, 10)], detailed=detail
    )
    model = housing.from_housing(_design([floor]))[0]

    living = next(room for room in model.rooms if room.name == "Living Room")
    assert [(m_to_ft(x), m_to_ft(y)) for x, y in living.polygon] == pytest.approx(
        [(0, 0), (12, 0), (12, 4), (6, 4), (6, 10), (0, 10)], abs=FT_TOL
    )
    assert living.area_m2 == pytest.approx(ft_to_m(1.0) ** 2 * 84.0)
    interior = [_wall_ft(wall) for wall in model.walls if wall.role == WallRole.INTERIOR]
    assert any(wall == pytest.approx((6.0, 4.0, 6.0, 10.0), abs=FT_TOL) for wall in interior)
    assert any(wall == pytest.approx((6.0, 4.0, 12.0, 4.0), abs=FT_TOL) for wall in interior)
    assert model.validate() == []


def test_detailed_room_union_marks_a_recess_as_exterior_wall():
    detail = {
        "id": "detail-recess",
        "source": "api",
        "width": 12,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {
                "id": "living-recess",
                "name": "Living Room",
                "kind": "living",
                "x": 0,
                "y": 0,
                "width": 12,
                "height": 10,
                "outline": [[0, 0], [12, 0], [12, 4], [8, 4], [8, 10], [0, 10]],
            }
        ],
        "doors": [],
        "windows": [],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 12, 10))
    floor["boundaryContent"] = _generated(
        12, 10, [("Living Room", 0, 0, 12, 10)], detailed=detail
    )
    model = housing.from_housing(_design([floor]))[0]

    exterior = [_wall_ft(wall) for wall in model.walls if wall.role == WallRole.EXTERIOR]
    assert any(wall == pytest.approx((8.0, 4.0, 8.0, 10.0), abs=FT_TOL) for wall in exterior)
    assert any(wall == pytest.approx((8.0, 4.0, 12.0, 4.0), abs=FT_TOL) for wall in exterior)


def test_detailed_wall_role_splits_where_an_exterior_run_becomes_shared():
    """One collinear room edge may be facade first and party wall second."""
    detail = {
        "id": "detail-mixed-role",
        "source": "api",
        "width": 10,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 10, "height": 5},
            {"id": "bed", "name": "Bedroom", "kind": "bedroom", "x": 5, "y": 5, "width": 5, "height": 5},
        ],
        "doors": [],
        "windows": [],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 10, 10))
    floor["boundaryContent"] = _generated(
        10, 10, [("Living Room", 0, 0, 10, 10)], detailed=detail
    )
    model = housing.from_housing(_design([floor]))[0]

    middle = sorted(
        (wall.role, _wall_ft(wall))
        for wall in model.walls
        if abs(m_to_ft(wall.a[1]) - 5.0) < FT_TOL
        and abs(m_to_ft(wall.b[1]) - 5.0) < FT_TOL
    )
    assert middle == [
        (WallRole.EXTERIOR, pytest.approx((0.0, 5.0, 5.0, 5.0), abs=FT_TOL)),
        (WallRole.INTERIOR, pytest.approx((5.0, 5.0, 10.0, 5.0), abs=FT_TOL)),
    ]


def test_drawn_shape_role_wins_over_its_detailed_unit_envelope():
    """A Mix unit's carrier borders the plot interior, not the weather."""
    detail = {
        "id": "detail-shape",
        "source": "api",
        "width": 12,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 12, "height": 10}
        ],
        "doors": [],
        "windows": [],
        "furniture": [],
    }
    shape = {
        "id": "shape-unit",
        "points": _rect(10, 5, 12, 10),
        "content": _generated(12, 10, [], detailed=detail),
    }
    floor = _floor(0, "Ground", _rect(0, 0, 30, 20), shapes=[shape])
    model = housing.from_housing(_design([floor]))[0]

    carrier_walls = [wall for wall in model.walls if "shape-unit" in (wall.source or "")]
    assert len(carrier_walls) == 4
    assert all(wall.role == WallRole.INTERIOR for wall in carrier_walls)
    assert all(
        m_to_ft(wall.thickness_m) == pytest.approx(1.0 / 3.0, abs=FT_TOL)
        for wall in carrier_walls
    )


def test_dressed_windows_suppress_assumptions_and_plot_entry_wins_once():
    detail = {
        "id": "detail-openings",
        "source": "api",
        "width": 10,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 10, "height": 10}
        ],
        "doors": [
            {"id": "unit-entry", "orientation": "h", "x": 5, "y": 10, "width": 3, "entrance": True}
        ],
        "windows": [
            {"id": "north-window", "orientation": "h", "x": 5, "y": 0, "width": 3, "sillFt": 3, "headFt": 7}
        ],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 10, 10))
    floor["boundaryContent"] = _generated(
        10, 10, [("Living Room", 0, 0, 10, 10)], detailed=detail
    )
    model = housing.from_housing(_design([floor], entry=[5, 10]), assume_windows=True)[0]

    entries = _openings(model, OpeningKind.ENTRY)
    assert len(entries) == 1
    assert entries[0][1].provenance == Provenance.ENTRY_POINT
    windows = _openings(model, OpeningKind.WINDOW)
    assert len(windows) == 1
    assert windows[0][1].provenance == Provenance.DRESSED
    assert m_to_ft(windows[0][1].width_m) == pytest.approx(3.0, abs=FT_TOL)
    assert "W_ASSUMED_OPENINGS" not in _codes(model)
    assert "W_DOOR_UNMAPPED" not in _codes(model)


def test_plot_entry_does_not_delete_a_detailed_internal_unit_entry():
    detail = {
        "id": "detail-unit-entry",
        "source": "api",
        "width": 12,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 12, "height": 10}
        ],
        "doors": [
            {"id": "unit-entry", "orientation": "h", "x": 6, "y": 10, "width": 3, "entrance": True}
        ],
        "windows": [],
        "furniture": [],
    }
    shape = {
        "id": "shape-unit",
        "points": _rect(10, 5, 12, 10),
        "content": _generated(12, 10, [], detailed=detail),
    }
    floor = _floor(0, "Ground", _rect(0, 0, 30, 20), shapes=[shape])
    model = housing.from_housing(_design([floor], entry=[15, 20]))[0]

    entries = _openings(model, OpeningKind.ENTRY)
    assert len(entries) == 2
    assert sorted(opening.provenance for _wall, opening in entries) == [
        Provenance.DRESSED,
        Provenance.ENTRY_POINT,
    ]
    dressed_wall = next(wall for wall, opening in entries if opening.provenance == Provenance.DRESSED)
    assert dressed_wall.role == WallRole.INTERIOR
    assert _wall_ft(dressed_wall) == pytest.approx((10.0, 15.0, 22.0, 15.0), abs=FT_TOL)
    assert "W_DOOR_UNMAPPED" not in _codes(model)


def test_unmapped_dressed_window_is_disclosed_instead_of_silently_lost():
    detail = {
        "id": "detail-floating-window",
        "source": "api",
        "width": 10,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 10, "height": 10}
        ],
        "doors": [],
        "windows": [
            {"id": "floating", "orientation": "h", "x": 5, "y": 5, "width": 3}
        ],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 10, 10))
    floor["boundaryContent"] = _generated(10, 10, [], detailed=detail)
    model = housing.from_housing(_design([floor]))[0]

    assert _openings(model, OpeningKind.WINDOW) == []
    assert "W_DOOR_UNMAPPED" in _codes(model)


def test_detailed_stair_room_is_still_carved_out_by_its_fixed_core():
    core = _core_shape("shape-core", "core-stairs", "stairs", 0, 6, 4, 4)
    detail = {
        "id": "detail-core",
        "source": "api",
        "width": 10,
        "height": 10,
        "exteriorWall": 0.75,
        "interiorWall": 0.4,
        "rooms": [
            {"id": "living", "name": "Living Room", "kind": "living", "x": 0, "y": 0, "width": 10, "height": 6},
            {"id": "stair", "name": "Staircase", "kind": "other", "x": 0, "y": 6, "width": 4, "height": 4},
            {"id": "bed", "name": "Bedroom", "kind": "bedroom", "x": 4, "y": 6, "width": 6, "height": 4},
        ],
        "doors": [],
        "windows": [],
        "furniture": [],
    }
    floor = _floor(0, "Ground", _rect(0, 0, 10, 10), shapes=[core])
    floor["boundaryContent"] = _generated(
        10,
        10,
        [("Living Room", 0, 0, 10, 6), ("Staircase", 0, 6, 4, 4), ("Bedroom", 4, 6, 6, 4)],
        detailed=detail,
    )
    model = housing.from_housing(_design([floor]))[0]

    assert sorted(room.name for room in model.rooms) == ["Bedroom", "Living Room", "stairs"]
    assert len([room for room in model.rooms if room.occupancy == Occupancy.STAIR]) == 1
    assert sum(room.area_m2 for room in model.rooms) == pytest.approx(ft_to_m(1.0) ** 2 * 100.0)
    assert "W_CORE_UNIT_OVERLAP" not in _codes(model)
    assert model.validate() == []


def test_a_stale_generated_plan_is_uniformly_rescaled_and_centred():
    """The region drifted to 14x22 under a 16x24 plan: min-scale, never anisotropic."""
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 30, 22),
        segments=[("seg-v", 14, 0, 14, 22)],
        region_content={
            "0,0;14,0;14,22;0,22": _generated(
                16, 24, [("Living Room", 0, 0, 16, 12), ("Bedroom 1", 0, 12, 16, 12)]
            )
        },
    )
    model = housing.from_housing(_design([floor]))[0]
    assert "W_STALE_GENERATED" in _codes(model)
    placed = sorted([r for r in model.rooms if r.unit_id], key=lambda r: r.id)
    # scale = min(14/16, 22/24) = 0.875; residual (22 - 21) ft is centred on y
    assert [_rect_ft(r) for r in placed] == [
        pytest.approx((0.0, 0.5, 14.0, 10.5), abs=1e-6),
        pytest.approx((0.0, 11.0, 14.0, 10.5), abs=1e-6),
    ]
    aspect = [round(r[2] / r[3], 6) for r in [_rect_ft(p) for p in placed]]
    assert aspect == [round(16.0 / 12.0, 6)] * 2, "a uniform scale keeps every proportion"


def test_a_fractional_region_uses_the_plan_frame_not_the_generation_request():
    """The client floors plan dimensions, but genW/genH remain the stale reference (B4)."""
    plan = _generated(
        13.12,
        22.97,
        [("Living Room", 0, 0, 13, 22)],
        plan_w=13,
        plan_h=22,
    )
    floor = _floor(
        0,
        "Ground",
        _rect(0, 0, 13.12, 22.97),
        region_content={"0,0;13.12,0;13.12,22.97;0,22.97": plan},
    )
    model = housing.from_housing(_design([floor]))[0]
    room = next(room for room in model.rooms if room.unit_id is not None)
    scale = 13.12 / 13.0
    assert _rect_ft(room) == pytest.approx(
        (0.0, 0.5 * (22.97 - 22.0 * scale), 13.12, 22.0 * scale), abs=FT_TOL
    )
    assert "W_STALE_GENERATED" not in _codes(model)


def test_windows_are_only_assumed_when_the_caller_asks(design):
    quiet = housing.from_housing(design)[0]
    assert "N_WINDOWS_NOT_ASSUMED" in _codes(quiet)
    assert not _openings(quiet, OpeningKind.WINDOW)

    loud = housing.from_housing(design, assume_windows=True)[0]
    windows = _openings(loud, OpeningKind.WINDOW)
    assert windows, "masonry needs opening data for the IS 4326 checks"
    assert "W_ASSUMED_OPENINGS" in _codes(loud)
    assert "N_WINDOWS_NOT_ASSUMED" not in _codes(loud)
    for wall, opening in windows:
        assert wall.role == WallRole.EXTERIOR
        assert opening.width_m == pytest.approx(1.2)
        assert opening.sill_m == pytest.approx(0.9)


def test_a_two_storey_stack_without_a_stair_is_disclosed_not_refused():
    floors = [
        _floor(0, "Ground", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)]),
        _floor(1, "First", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)]),
    ]
    model = housing.from_housing(_design(floors))[0]
    assert len(model.storeys) == 2
    assert model.cores == []
    assert "W_NO_STAIR" in _codes(model)


def test_a_parking_only_ground_storey_is_marked_stilt():
    floors = [
        _floor(0, "Ground", _rect(0, 0, 30, 40)),
        _floor(1, "First", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)]),
    ]
    resolved = {
        "hf-0": [{"points": _rect(0, 0, 30, 40), "content": {"space": {"kind": "parking"}}}],
        "hf-1": [{"points": _rect(0, 0, 30, 20)}, {"points": _rect(0, 20, 30, 20)}],
    }
    model = housing.from_housing(_design(floors), resolved_regions=resolved)[0]
    assert [s.kind for s in model.storeys] == [StoreyKind.STILT, StoreyKind.UNITS]


def test_boundary_parking_with_the_mandatory_stair_core_is_stilt():
    """A multi-storey parking floor has a core, which must not preempt stilt (N8)."""
    ground_core = _core_shape("shape-g", "core-stairs", "stairs", 20, 26, 7, 10)
    first_core = _core_shape("shape-1", "core-stairs", "stairs", 20, 26, 7, 10)
    ground = _floor(0, "Ground", _rect(0, 0, 30, 40), shapes=[ground_core])
    ground["boundaryContent"] = {"space": {"kind": "parking"}}
    first = _floor(
        1,
        "First",
        _rect(0, 0, 30, 40),
        segments=[("split", 0, 20, 30, 20)],
        shapes=[first_core],
    )
    model = housing.from_housing(_design([ground, first]))[0]
    assert [storey.kind for storey in model.storeys] == [StoreyKind.STILT, StoreyKind.UNITS]


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------


def test_ground_plus_three_is_accepted_and_a_fifth_floor_is_refused():
    floors = [
        _floor(
            level,
            "L%d" % level,
            _rect(0, 0, 30, 40),
            segments=[("seg-a-%d" % level, 0, 20, 30, 20)],
            shapes=[_core_shape("shape-%d" % level, "core-stairs", "stairs", 20, 26, 7, 10)],
        )
        for level in range(4)
    ]
    models = housing.from_housing(_design(floors))
    assert len(models) == 1
    assert [storey.index for storey in models[0].storeys] == [0, 1, 2, 3]
    assert [record["level"] for record in housing.split_plot_stacks(_design(floors))[0]["floors"]] == [0, 1, 2, 3]

    fifth = _floor(
        4,
        "L4",
        _rect(0, 0, 30, 40),
        segments=[("seg-a-4", 0, 20, 30, 20)],
        shapes=[_core_shape("shape-4", "core-stairs", "stairs", 20, 26, 7, 10)],
    )
    too_many = floors + [fifth]
    with pytest.raises(housing.AdapterError) as refusal:
        housing.from_housing(_design(too_many))
    assert refusal.value.code == "E_UNSUPPORTED_STOREYS"
    assert "4" in refusal.value.message
    with pytest.raises(housing.AdapterError):
        housing.split_plot_stacks(_design(too_many))


def test_a_core_whose_copies_differ_is_refused():
    floors = [
        _floor(
            0,
            "Ground",
            _rect(0, 0, 30, 40),
            segments=[("seg-a", 0, 20, 30, 20)],
            shapes=[_core_shape("shape-g", "core-stairs", "stairs", 20, 26, 7, 10)],
        ),
        _floor(
            1,
            "First",
            _rect(0, 0, 30, 40),
            segments=[("seg-a", 0, 20, 30, 20)],
            shapes=[_core_shape("shape-1", "core-stairs", "stairs", 21, 26, 7, 10)],
        ),
    ]
    with pytest.raises(housing.AdapterError) as refusal:
        housing.from_housing(_design(floors))
    assert refusal.value.code == "E_CORE_MISMATCH"
    assert refusal.value.details["core_id"] == "core-stairs"


def test_a_stack_that_starts_above_the_ground_is_refused():
    plots = [{"id": "plot-b", "boundary": _rect(40, 0, 30, 40)}]
    floors = [
        _floor(0, "Ground", _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)]),
        _floor(
            1,
            "First",
            _rect(0, 0, 30, 40),
            segments=[("seg-a", 0, 20, 30, 20), ("seg-b", 40, 20, 70, 20)],
            plots=plots,
        ),
    ]
    with pytest.raises(housing.AdapterError) as refusal:
        housing.from_housing(_design(floors))
    assert refusal.value.code == "E_STACK_DISCONTINUOUS"


def test_an_unknown_plot_id_and_an_empty_design_are_refused(design):
    with pytest.raises(housing.AdapterError) as unknown:
        housing.from_housing(design, plot_id="plot-nope")
    assert unknown.value.code == "E_BAD_ENVELOPE"

    with pytest.raises(housing.AdapterError) as empty:
        housing.from_housing(_design([]))
    assert empty.value.code == "E_UNSUPPORTED_STOREYS"

    bare = _design([_floor(0, "Ground", _rect(0, 0, 30, 40))])
    with pytest.raises(housing.AdapterError) as unbuilt:
        housing.from_housing(bare)
    assert unbuilt.value.code == "E_EMPTY_PLAN"


def test_an_unknown_system_hint_is_refused(design):
    with pytest.raises(housing.AdapterError) as refusal:
        housing.from_housing(design, system_hint="timber_frame")
    assert refusal.value.code == "E_BAD_ENVELOPE"
    assert housing.from_housing(design, system_hint="load_bearing_masonry")[0].system == (
        System.LOAD_BEARING_MASONRY
    )


def test_storey_height_and_wall_options_are_honoured(design):
    model = housing.from_housing(
        design, storey_height_ft=9.0, exterior_wall_ft=0.9, interior_wall_ft=0.5
    )[0]
    assert m_to_ft(model.storeys[1].bottom_z_m) == pytest.approx(9.0, abs=FT_TOL)
    assert model.meta["interior_wall_ft"] == pytest.approx(0.5)
    exterior = [w for w in model.walls if w.role == WallRole.EXTERIOR]
    assert exterior and all(
        w.thickness_m == pytest.approx(ft_to_m(0.9)) for w in exterior
    )


def _site_house(generated=False, covered=False):
    floor = _floor(0, "Ground", _rect(0, 0, 30, 30), segments=[
        ("facade", 20, 0, 20, 30), ("site", 20, 15, 30, 15),
        ("shared", 0, 15, 20, 15),
    ])
    indoor = [
        {"points": _rect(0, 0, 20, 15), "content": {"space": {"kind": "other", "customName": "Living"}}},
        {"points": _rect(0, 15, 20, 15), "content": {"space": {"kind": "other", "customName": "Bedroom"}}},
    ]
    if generated:
        floor["segments"] = floor["segments"][:2]
        detail = {"id": "detail", "source": "api", "width": 20, "height": 30,
                  "exteriorWall": 0.5, "interiorWall": 1 / 3,
                  "rooms": [{"id": "living", "name": "Living", "kind": "living", "x": 0, "y": 0, "width": 20, "height": 15},
                            {"id": "bed", "name": "Bedroom", "kind": "bedroom", "x": 0, "y": 15, "width": 20, "height": 15}],
                  "doors": [], "windows": [], "furniture": []}
        indoor = [{"points": _rect(0, 0, 20, 30), "content": _generated(20, 30, [], detailed=detail)}]
    resolved = {"hf-0": indoor + [
        {"points": _rect(20, 0, 10, 15), "content": {"space": {"kind": "open"}}},
        {"points": _rect(20, 15, 10, 15), "content": {"space": {"kind": "parking"}}},
    ]}
    floors = [floor]
    if covered:
        floors.append(_floor(1, "First", _rect(0, 0, 30, 30)))
        resolved["hf-1"] = [{"points": _rect(0, 0, 30, 30), "content": {"space": {"kind": "other", "customName": "Living"}}}]
    design = _design(floors)
    design["wallDisplay"]["exteriorWallFt"] = 0.5
    return housing.from_housing(design, resolved_regions=resolved)[0]


def test_generated_and_drawn_house_share_identical_wall_geometry():
    def walls(model):
        return sorted((tuple(round(n, 7) for n in _wall_ft(wall)), wall.role, round(wall.thickness_m, 7)) for wall in model.walls)
    drawn, generated = _site_house(), _site_house(generated=True)
    assert walls(drawn) == walls(generated)
    for wall in drawn.walls:
        assert max(m_to_ft(wall.a[0]), m_to_ft(wall.b[0])) <= 20 + FT_TOL
        expected = 0.5 if wall.role == WallRole.EXTERIOR else 1 / 3
        assert m_to_ft(wall.thickness_m) == pytest.approx(expected)
    assert len([wall for wall in drawn.walls if wall.role == WallRole.INTERIOR]) == 1


@pytest.mark.parametrize("generated", [False, True])
def test_outdoor_parking_and_open_sky_do_not_create_columns_beams_or_slabs(generated):
    from ..grid import extract_axes
    from ..placement.frame import run_frame_placement
    model = _site_house(generated)
    grid = extract_axes(model)
    assert max(rect[2] for rect in grid.footprints[0].rects) == round(ft_to_m(20) * 1000)
    placed = run_frame_placement(model)
    placed.write_back(model)
    assert model.columns
    for column in model.columns:
        assert m_to_ft(column.x_m) <= 20 + 0.01
    for beam in model.beams:
        assert max(m_to_ft(beam.a[0]), m_to_ft(beam.b[0])) <= 20 + 0.01
    for slab in model.slabs:
        assert all(m_to_ft(point[0]) <= 20 + 0.01 for point in slab.polygon)


def test_parking_below_a_built_floor_retains_its_support_projection():
    from ..grid import extract_axes
    grid = extract_axes(_site_house(covered=True))
    assert grid.footprints[0].rects == grid.footprints[1].rects
    assert max(rect[2] for rect in grid.footprints[0].rects) == round(ft_to_m(30) * 1000)


def test_courtyard_remains_a_hole_in_the_structural_footprint():
    from ..grid import extract_axes
    court = _rect(10, 10, 10, 10)
    floor = _floor(0, "Ground", _rect(0, 0, 30, 30), shapes=[
        {"id": "court", "points": court, "content": {"space": {"kind": "open"}}},
    ])
    model = housing.from_housing(_design([floor]))[0]
    grid = extract_axes(model)
    cx, cy = round(ft_to_m(15) * 1000), round(ft_to_m(15) * 1000)
    assert not any(x0 < cx < x1 and y0 < cy < y1 for x0, y0, x1, y1 in grid.footprints[0].rects)


def test_structural_adapter_uses_both_editor_wall_settings(design):
    design["wallDisplay"] = {"exteriorWallFt": 0.8, "interiorWallFt": 0.4}
    model = housing.from_housing(design)[0]
    assert all(m_to_ft(wall.thickness_m) == pytest.approx(0.8 if wall.role == WallRole.EXTERIOR else 0.4) for wall in model.walls)


def test_an_explicit_open_sky_upper_floor_does_not_inherit_a_frame_from_below():
    from ..grid import extract_axes
    ground = _floor(0, "Ground", _rect(0, 0, 30, 30), segments=[("room", 15, 0, 15, 30)])
    upper = _floor(1, "Open", _rect(0, 0, 30, 30))
    upper["boundaryContent"] = {"space": {"kind": "open"}}
    grid = extract_axes(housing.from_housing(_design([ground, upper]))[0])
    assert not grid.footprints[0].is_empty()
    assert grid.footprints[1].is_empty()
