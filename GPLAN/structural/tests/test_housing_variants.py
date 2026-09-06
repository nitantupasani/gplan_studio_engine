"""Housing-only alternatives: different real layouts, shared caps and room guards."""
import copy
import json
from fractions import Fraction
from pathlib import Path

import pytest

from .. import api, grid, model as M
from ..adapters.housing import from_housing
from ..analysis.takedown import AnalysisError
from ..placement.cores import plan_cores
from ..placement.frame import _ColumnState, _Stack, _View, enforce_continuity, run_frame_placement
from ..placement.housing_variants import assess, near_wall, point_assessment

FIXTURES = Path(__file__).parent / "fixtures"


def request(storeys=2, variant="balanced", cap=5.0):
    housing = json.loads((FIXTURES / "housing_corner_core_2bhk.json").read_text())
    ground = housing["floors"][0]
    housing["floors"] = []
    for level in range(storeys):
        floor = copy.deepcopy(ground)
        floor.update(id="variant-floor-%d" % level, level=level)
        floor["shapes"][0]["id"] = "variant-stair-%d" % level
        housing["floors"].append(floor)
    return {
        "source": "housing", "housing": housing, "plot_id": "primary",
        "params": {"system": "rc_frame", "analysis_mode": "gravity_only", "placement_strategy": "wall_aligned", "housing_column_variant": variant, "spans": {"max_m": cap}},
        "output": {"detail": "compact"},
    }


@pytest.fixture(scope="module", params=[1, 2, 3])
def designed_variants(request):
    count = request.param
    return count, {
        variant: api.run_design(globals()["request"](count, variant))
        for variant in grid.HOUSING_COLUMN_VARIANTS
    }


def test_housing_variants_are_distinct_checked_wall_respecting_layouts(designed_variants):
    storeys, envelopes = designed_variants
    fingerprints = set()
    for variant, envelope in envelopes.items():
        assert envelope["status"] == "SUCCESS", envelope.get("message")
        entry = envelope["response"]["Documents"]["structural"][0]
        assert api.validate_wire(entry["structural_model"]) == []
        try:
            import jsonschema
        except ImportError:
            jsonschema = None
        if jsonschema is not None:
            schema = json.loads((FIXTURES.parent.parent / "schema/structural_response.schema.json").read_text())
            jsonschema.Draft202012Validator(schema).validate(envelope)
        layout = entry["housing_layout"]
        assert layout["variant"] == variant
        assert len(entry["structural_model"]["storeys"]) == storeys
        assert layout["eligible"] is True
        assert layout["room_assessment"] == "assessed"
        assert layout["room_intrusion_count"] == 0
        assert layout["off_wall_column_count"] == 0
        assert layout["off_wall_column_ids"] == []
        assert not layout["room_intrusion_column_ids"]
        assert layout["physical_max_span_m"] <= 5.0 + 1e-6
        assert entry["design"]["failed_count"] == 0
        assert not entry["errors"]
        assert entry["comparison_validity"]["feasible_for_ranking"], entry["comparison_validity"]
        assert entry["comparison_validity"]["valid_for_relative_cost_comparison"], entry["comparison_validity"]
        assert entry["options_echo"]["values"]["housing_column_variant"] == variant
        assert layout["summary"]
        fingerprints.add(layout["geometry_fingerprint"])
    assert len(fingerprints) == 3
    for envelope in envelopes.values():
        consolidated = envelope["response"]["Documents"]["structural"][0]["housing_layout"]
        assert consolidated["column_stack_count"] <= 14
        assert consolidated["closest_column_centres_m"] >= 2.133
        assert consolidated["close_pair_count"] <= 4
        assert consolidated["close_pair_deficit_m"] <= 1.466
        assert "bounded wall-supported search" in consolidated["summary"]


@pytest.mark.parametrize("updates", [
    {"housing_column_variant": "unknown"}, {"analysis_mode": "code_complete"},
    {"placement_strategy": "economy_grid"}, {"system": "auto"},
])
def test_housing_variant_scope_rejects_unsupported_params(updates):
    payload = request()
    payload["params"].update(updates)
    envelope = api.run_design(payload)
    assert envelope["status"] == "ERROR"
    assert envelope["response"]["Documents"]["error"]["field"] == "params.housing_column_variant"


def test_housing_variants_reject_four_total_storeys_and_plan_workflow():
    assert api.run_design(request(4))["status"] == "ERROR"
    payload = request()
    payload.update(source="plan", plan=json.loads((FIXTURES / "plan_2bhk.json").read_text()), storeys=2)
    payload.pop("housing")
    assert api.run_design(payload)["response"]["Documents"]["error"]["field"] == "params.housing_column_variant"


def test_housing_variant_grid_preserves_anchors_and_uses_actual_wall_snap_positions(monkeypatch):
    model = from_housing(request()["housing"])[0]
    baseline = grid.extract_axes(model)
    pools = []
    original = grid._insert_span_control
    def capture(axes, direction, params, footprints, snap_pool, log):
        pools.extend(snap_pool)
        return original(axes, direction, params, footprints, snap_pool, log)
    monkeypatch.setattr(grid, "_insert_span_control", capture)
    alternative = grid.extract_axes(model, grid.FrameParams(housing_column_variant="toward_start"))
    protected = lambda g: {(a.dir.value, a.pos_mm, a.source.value) for a in g.axes() if a.source.value in ("outline", "corridor", "party", "core")}
    assert protected(alternative) == protected(baseline)
    assert 5040 not in pools  # old weighted mean is not a real wall member
    assert 4915 in pools and 5182 in pools
    assert all(b.pos_mm-a.pos_mm <= 5000 for axes in (alternative.x_axes, alternative.y_axes) for a, b in zip(axes, axes[1:]))


def test_housing_search_preserves_omitted_variant_geometry_and_repeat_order():
    model = from_housing(request()["housing"])[0]
    legacy = run_frame_placement(copy.deepcopy(model))
    params = grid.FrameParams(housing_column_variant="balanced")
    balanced = run_frame_placement(copy.deepcopy(model), params)
    assert [(c.x_mm, c.y_mm) for c in legacy.columns] == [
        (0, 0), (0, 1219), (0, 5040), (0, 9144), (0, 12192),
        (2134, 9144), (2134, 12192), (4267, 0), (4267, 1219),
        (4267, 5040), (4267, 9144), (4267, 12192), (9144, 0),
        (9144, 2520), (9144, 5040), (9144, 8534), (9144, 12192),
    ]
    assert all(c.exists == [0, 1] for c in legacy.columns)
    assert "housing_search" not in legacy.metrics
    assert len(balanced.columns) <= 14
    model.walls.reverse()
    model.rooms.reverse()
    assert run_frame_placement(model, params).to_dict() == balanced.to_dict()


def _room(tag, x0, x1, occupancy=M.Occupancy.HABITABLE, unknown=False):
    return M.RoomPoly(tag, 0, tag, occupancy, [(x0, 0), (x1, 0), (x1, 4), (x0, 4)], (x1-x0)*4, interior_unknown=unknown)


def test_room_guard_distinguishes_known_unknown_and_open_rooms():
    model = M.StructuralModel(storeys=[M.Storey(0, "Ground", 0, 3)], rooms=[_room("known", 0, 4), _room("unknown", 4, 8, unknown=True), _room("parking", 8, 12, M.Occupancy.PARKING)])
    model.walls = [M.WallLine("edge", 0, (0, 0), (0, 4), .23, M.WallRole.EXTERIOR)]
    assert point_assessment(model, 0, 2, 2) == "intrusion"
    assert point_assessment(model, 0, .142, 2) == "clear"
    assert point_assessment(model, 0, 6, 2) == "unassessed"
    assert point_assessment(model, 0, 10, 2) == "clear"
    # A distant room's unknown internals do not unassess the known-room column.
    model.columns = [M.Column("known-column", "known-stack", 0, 2, 2, .23, .23)]
    assert assess(model)["room_assessment"] == "assessed"
    assert assess(model)["room_intrusion_count"] == 1
    model.columns.append(M.Column("unknown-column", "unknown-stack", 0, 6, 2, .23, .23))
    audit = assess(model)
    assert audit["room_assessment"] == "partial"
    assert audit["room_intrusion_count"] is None
    assert audit["confirmed_room_intrusion_count"] == 1
    assert audit["unassessed_column_ids"] == ["unknown-column"]
    view = _View(model, grid.extract_axes(model), grid.FrameParams(housing_column_variant="balanced"))
    assert not view.housing_wall_allowed(10000, 2000, [0])
    assert not view.housing_wall_allowed(2000, 2000, [0])
    assert not view.housing_wall_allowed(6000, 2000, [0])
    assert view.housing_wall_allowed(142, 2000, [0])


def test_housing_wall_guard_uses_finite_eligible_walls_on_exact_storeys():
    model = M.StructuralModel(storeys=[M.Storey(0, "Ground", 0, 3), M.Storey(2, "Upper", 6, 3)])
    model.walls = [M.WallLine("ground", 0, (0, 0), (0, 4), .23, M.WallRole.EXTERIOR)]
    view = _View(model, grid.extract_axes(model), grid.FrameParams(housing_column_variant="balanced"))
    assert view.housing_wall_allowed(300, 2000, [0])
    assert not view.housing_wall_allowed(301, 2000, [0])
    assert not view.housing_wall_allowed(0, 4400, [0])  # beyond the finite end
    assert not view.housing_wall_allowed(0, 2000, [0, 2])
    for role in (M.WallRole.RAILING, M.WallRole.PARAPET):
        model.walls.append(M.WallLine(role.value, 2, (0, 0), (0, 4), .23, role))
    assert not view.housing_wall_allowed(0, 2000, [2])
    model.walls.append(M.WallLine("upper", 2, (0, 0), (0, 4), .23, M.WallRole.EXTERIOR))
    assert view.housing_wall_allowed(0, 2000, [0, 2])
    assert not view.housing_wall_allowed(0, 2000, [0, 1, 2])


def test_housing_open_room_columns_still_require_walls_during_placement():
    model = from_housing(request(1)["housing"])[0]
    for room in model.rooms:
        room.occupancy = M.Occupancy.PARKING
    legacy = run_frame_placement(copy.deepcopy(model), grid.FrameParams(max_primary_span=4.0))
    assert any((c.x_mm, c.y_mm) == (6705, 2520) for c in legacy.columns)
    guarded = run_frame_placement(model, grid.FrameParams(max_primary_span=4.0, housing_column_variant="balanced"))
    assert guarded.columns
    assert all(near_wall(model, s, c.x_mm/1000, c.y_mm/1000) for c in guarded.columns for s in c.exists)
    assert not any((c.x_mm, c.y_mm) == (6705, 2520) for c in guarded.columns)


def test_housing_continuity_repair_cannot_slide_off_an_upper_wall():
    from .test_placement_frame import slide_model
    model = slide_model()
    for room in model.rooms:
        room.occupancy = M.Occupancy.PARKING
    results = {}
    for variant in (None, "balanced"):
        params = grid.FrameParams(housing_column_variant=variant)
        axes = grid.extract_axes(model, params)
        view = _View(model, axes, params)
        state = _ColumnState(view, plan_cores(model, axes, params), params)
        stack = _Stack(x_mm=10800, y_mm=4000, anchor=100, origin="wall", exists=[1], top=1, base=1, score=Fraction(100), w_dir="h")
        results[variant] = enforce_continuity(view, [stack], state, params, M.DisclosureLog())
    assert [(c.x_mm, c.y_mm) for c in results[None]] == [(10000, 4000)]
    assert not near_wall(model, 1, 10, 4)
    assert results["balanced"] == []


def test_housing_final_audit_rejects_off_wall_open_room_columns_and_cost_ranking():
    payload = request(1)
    model = from_housing(payload["housing"])[0]
    for room in model.rooms:
        room.occupancy = M.Occupancy.PARKING
    model.columns = [M.Column("late-open-column", "late-stack", 0, 6.705, 2.52, .23, .23)]
    assert point_assessment(model, 0, 6.705, 2.52) == "clear"
    audit = assess(model)
    assert audit["room_intrusion_count"] == 0
    assert audit["off_wall_column_count"] == 1
    assert audit["off_wall_column_ids"] == ["late-open-column"]
    opts = api._Resolved(payload, {})
    with pytest.raises(AnalysisError, match="E_HOUSING_COLUMN_OFF_WALL"):
        api._design_once(model, opts, M.DisclosureLog(), api._Placement())
    entry = api._entry_head(model, "housing", payload, opts, api._Placement(), "test")
    entry.update(status="ok_with_warnings", analysis={"physical_max_span_m": 4}, design={"failed_count": 0}, errors=[], comparison_validity={"feasible_for_ranking": True, "valid_for_relative_cost_comparison": True, "valid_for_absolute_cost": True, "reasons": []})
    api._finish_housing_layout(entry, model, opts)
    assert entry["housing_layout"]["eligible"] is False
    assert entry["housing_layout"]["reasons"] == ["housing_off_wall_columns"]
    comparison = entry["comparison_validity"]
    assert comparison["reasons"] == ["housing_off_wall_columns"]
    assert not comparison["feasible_for_ranking"]
    assert not comparison["valid_for_relative_cost_comparison"]
    assert not comparison["valid_for_absolute_cost"]


def test_housing_off_wall_count_reports_each_storey_column_id():
    model = M.StructuralModel(storeys=[M.Storey(0, "Ground", 0, 3), M.Storey(2, "Upper", 6, 3)])
    model.walls = [M.WallLine("ground", 0, (0, 0), (0, 4), .23, M.WallRole.EXTERIOR)]
    model.columns = [M.Column("ground-on", "on-stack", 0, 0, 2, .23, .23), M.Column("upper-off", "on-stack", 2, 0, 2, .23, .23), M.Column("ground-off", "off-stack", 0, 2, 2, .23, .23), M.Column("upper-off-2", "off-stack", 2, 2, 2, .23, .23)]
    audit = assess(model)
    assert audit["off_wall_column_count"] == 3
    assert audit["off_wall_column_ids"] == ["ground-off", "upper-off", "upper-off-2"]


def test_room_guard_uses_finite_wall_segments_and_rechecks_final_geometry():
    model = from_housing(request(1)["housing"])[0]
    # The former 4 m kitchen column is on an extended guide, not a real wall.
    model.columns = [M.Column("late-column", "late-stack", 0, 6.705, 2.52, .23, .23)]
    opts = api._Resolved(request(1), {})
    with pytest.raises(AnalysisError, match="E_HOUSING_ROOM_INTRUSION"):
        api._design_once(model, opts, M.DisclosureLog(), api._Placement())


def test_four_metre_variant_does_not_return_the_former_kitchen_column():
    envelope = api.run_design(request(1, "balanced", 4.0))
    entry = envelope["response"]["Documents"]["structural"][0]
    assert entry["housing_layout"]["room_intrusion_count"] == 0
    assert not any(abs(c["x_ft"]-22)<.01 and abs(c["y_ft"]-8.27)<.01 for c in entry["structural_model"]["columns"])
    if entry["housing_layout"]["eligible"]:
        assert entry["analysis"]["physical_max_span_m"] <= 4.0 + 1e-6
    else:
        assert not entry["comparison_validity"]["feasible_for_ranking"]


def test_unassessed_room_geometry_cannot_receive_candidate_or_cost_eligibility():
    payload = request(1)
    model = from_housing(payload["housing"])[0]
    model.rooms[0].interior_unknown = True
    room = model.rooms[0]
    x = sum(p[0] for p in room.polygon)/len(room.polygon)
    y = sum(p[1] for p in room.polygon)/len(room.polygon)
    model.columns = [M.Column("unknown", "unknown", 0, x, y, .23, .23)]
    opts = api._Resolved(payload, {})
    entry = api._entry_head(model, "housing", payload, opts, api._Placement(), "test")
    entry.update(status="ok_with_warnings", analysis={"physical_max_span_m": 4}, design={"failed_count": 0}, errors=[])
    api._finish_housing_layout(entry, model, opts)
    assert entry["housing_layout"]["eligible"] is False
    assert "housing_room_assessment_incomplete" in entry["comparison_validity"]["reasons"]
