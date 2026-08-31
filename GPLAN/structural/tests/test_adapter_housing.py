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
        assert m_to_ft(wall.thickness_m) == pytest.approx(0.75, abs=FT_TOL)
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


def _generated(gen_w, gen_h, placements, plan_id="pl-1", plan_w=None, plan_h=None):
    plan_w = gen_w if plan_w is None else plan_w
    plan_h = gen_h if plan_h is None else plan_h
    return {
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


def test_four_floors_are_refused():
    floors = [
        _floor(level, "L%d" % level, _rect(0, 0, 30, 40), segments=[("seg-a", 0, 20, 30, 20)])
        for level in range(4)
    ]
    with pytest.raises(housing.AdapterError) as refusal:
        housing.from_housing(_design(floors))
    assert refusal.value.code == "E_UNSUPPORTED_STOREYS"
    assert "3" in refusal.value.message
    with pytest.raises(housing.AdapterError):
        housing.split_plot_stacks(_design(floors))


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
