"""Bounded real support edits, objective definitions and checked setbacks."""
import copy
import json
from fractions import Fraction
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from .. import api, model as M
from ..adapters.housing import from_housing
from ..analysis.takedown import _build_runs
from ..grid import FrameParams, extract_axes
from ..placement.cores import plan_cores
from ..placement.frame import (
    _ColumnState, _Stack, _View, _housing_objective, _housing_preflight,
    _run_frame_placement_once, _warn_final_short_spans, run_frame_placement,
    _housing_search_signature, clear_housing_search_cache, housing_search_cache_diagnostics,
)
from ..placement.housing_variants import (
    SEARCH_CANDIDATE_LIMIT, WALL_STATION_LIMIT, assess, near_wall, wall_station_pool,
)

FIXTURES = Path(__file__).parent / "fixtures"


def narrow_request(storeys, variant, setback=False):
    filename = "housing_narrow_setback_search_3storey.json" if setback else "housing_narrow_search_3storey.json"
    housing = json.loads((FIXTURES / filename).read_text())
    housing["floors"] = housing["floors"][:storeys]
    return {
        "source": "housing", "housing": housing, "plot_id": "primary",
        "params": {"system": "rc_frame", "analysis_mode": "gravity_only", "placement_strategy": "wall_aligned",
                   "housing_column_variant": variant, "spans": {"max_m": 5}},
        "output": {"detail": "compact"},
    }


def checked_entry(payload):
    envelope = api.run_design(payload)
    assert envelope["status"] == "SUCCESS", envelope.get("message")
    entry = envelope["response"]["Documents"]["structural"][0]
    assert entry["housing_layout"]["eligible"], entry["housing_layout"]
    assert not entry["errors"] and not entry["partial"]
    assert entry["design"]["failed_count"] == entry["design"]["undesigned_count"] == 0
    assert not entry["design"]["referrals_outstanding"]
    assert entry["comparison_validity"]["feasible_for_ranking"], entry["comparison_validity"]
    assert entry["comparison_validity"]["valid_for_relative_cost_comparison"], entry["comparison_validity"]
    assert entry["housing_layout"]["physical_max_span_m"] <= 5
    assert entry["housing_layout"]["off_wall_column_count"] == entry["housing_layout"]["room_intrusion_count"] == 0
    assert entry["housing_layout"]["room_assessment"] == "assessed"
    return entry


@pytest.mark.parametrize("storeys", (1, 2, 3))
def test_narrow_regular_real_designs_improve_spacing_and_give_actual_alternatives(storeys):
    entries = [checked_entry(narrow_request(storeys, variant)) for variant in ("balanced", "toward_start", "toward_end")]
    audits = [entry["housing_layout"] for entry in entries]
    assert len({audit["geometry_fingerprint"] for audit in audits}) == 3
    assert audits[0]["column_stack_count"] <= 15
    assert audits[0]["close_pair_count"] <= 5
    assert audits[0]["close_pair_deficit_m"] <= 2.767
    assert all(audit["column_stack_count"] <= 18 and audit["close_pair_deficit_m"] <= 4.051 for audit in audits)


@pytest.mark.parametrize("storeys", (1, 2))
def test_lower_setback_storeys_keep_complete_design_and_comparison_eligibility(storeys):
    for variant in ("balanced", "toward_start", "toward_end"):
        checked_entry(narrow_request(storeys, variant, setback=True))


@pytest.mark.parametrize("variant", ("balanced", "toward_start", "toward_end"))
def test_three_storey_setback_repairs_frame_but_refuses_unresolved_designed_footing_overlap(variant):
    envelope = api.run_design(narrow_request(3, variant, setback=True))
    assert envelope["status"] == "SUCCESS"  # member design completes; ranking still refuses
    entry = envelope["response"]["Documents"]["structural"][0]
    audit = entry["housing_layout"]
    assert not audit["eligible"]
    assert "unresolved_foundation_topology" in audit["reasons"]
    assert not entry["comparison_validity"]["feasible_for_ranking"]
    assert not entry["comparison_validity"]["valid_for_relative_cost_comparison"]
    assert "unresolved_foundation_topology" in entry["comparison_validity"]["reasons"]
    assert not entry["errors"] and not entry["partial"]
    assert entry["design"]["failed_count"] == entry["design"]["undesigned_count"] == 0
    assert not entry["design"]["referrals_outstanding"]
    assert audit["off_wall_column_count"] == audit["room_intrusion_count"] == 0
    assert audit["room_assessment"] == "assessed"
    assert audit["column_stack_count"] == 27
    assert audit["physical_max_span_m"] == 4.572
    overlap = [warning for warning in entry["warnings"] if warning["code"] == "W_FOOTING_OVERLAP"]
    assert len(overlap) == 1
    assert set(overlap[0]["element_ids"]) == {"ftg-comb-@11.79x14.35", "ftg-stk-4-E"}
    assert "0.121 m2" in overlap[0]["message"]
    footings = {footing["id"]: footing for footing in entry["structural_model"]["footings"]}
    sections = {row["element_id"]: row["section"] for row in entry["structural_model"]["design"] if row["element_type"] == "footing"}
    rectangles = []
    for element_id in overlap[0]["element_ids"]:
        footing, section = footings[element_id], sections[element_id]
        x, y = footing["x_ft"] * .3048, footing["y_ft"] * .3048
        # Placement widths are seed rectangles. The designed section owns
        # the final dimensions consumed by the drawing, quantities and audit.
        half_width, half_height = section["bx_mm"] / 2000, section["ly_mm"] / 2000
        rectangles.append((x - half_width, y - half_height, x + half_width, y + half_height))
    a, b = rectangles
    overlap_x = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    overlap_y = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    assert overlap_x * overlap_y == pytest.approx(.121, abs=.001)
    search = entry["layout_score"]["metrics"]["housing_search"]
    assert search["full_design_candidate_attempt_count"] == 2
    assert search["full_design_distinct_eligible_layout_count"] == 0
    columns = entry["structural_model"]["columns"]
    points = {(column["storey"], round(column["x_ft"] * 304.8), round(column["y_ft"] * 304.8)) for column in columns}
    for storey in (0, 1, 2):
        assert (storey, 5080, 10973) in points
        assert (storey, 6096, 9144) in points
        assert (storey, 6096, 10287) not in points


def test_setback_preflight_rejects_physical_run_and_incomplete_single_support_repairs():
    model = from_housing(narrow_request(3, "balanced", setback=True)["housing"])[0]
    params = FrameParams(housing_column_variant="balanced")
    baseline = _run_frame_placement_once(model, params)
    written = baseline.write_back(copy.deepcopy(model))
    runs = _build_runs(written, 1, M.DisclosureLog())
    rear = next(run for run in runs if run.run_id == "run-s1-h10973-00")
    assert max(hi - lo for lo, hi in rear.spans) == pytest.approx(5.080)
    assert any(error["code"] == "E_FRAMING_DEPTH" and error["element_ids"] == ["wall-s2-v-20-0"] for error in baseline.report["errors"])
    assert not near_wall(model, 0, 6.096, 10.973)  # a tempting upper corner has no ground wall
    partial = _run_frame_placement_once(model, params, (), ({(6096, 10287)}, ((5080, 10973),)))
    assert not partial.report["errors"]
    assert _housing_preflight(model, partial, params)[0] is False  # 4.115 m side overhang remains
    final = run_frame_placement(model, params)
    assert _housing_preflight(model, final, params) == (True, 4.572)
    assert final.metrics["housing_search"]["distinct_layout_count"] == 1


def test_pool_and_work_count_are_canonical_bounded_and_preserve_required_anchors():
    model = from_housing(narrow_request(1, "balanced")["housing"])[0]
    params = FrameParams(housing_column_variant="balanced")
    seed = _run_frame_placement_once(model, params)
    result = run_frame_placement(model, params)
    metadata = result.metrics["housing_search"]
    assert 3 < metadata["generated_candidate_count"] <= SEARCH_CANDIDATE_LIMIT
    assert metadata["operation"] == "subset"
    required = {(column.x_mm, column.y_mm) for column in seed.columns if column.anchor}
    assert required <= {(column.x_mm, column.y_mm) for column in result.columns}
    pool = wall_station_pool(model, result.grid, 5)
    assert len(pool) <= WALL_STATION_LIMIT and len(pool) == len(set(pool))
    assert all(any(near_wall(model, s.index, x/1000, y/1000) for s in model.storeys) for x, y in pool)
    model.walls.reverse()
    model.rooms.reverse()
    assert wall_station_pool(model, result.grid, 5) == pool
    assert run_frame_placement(model, params).to_dict() == result.to_dict()


@pytest.mark.parametrize("other,waived", [((1700, 1700), False), ((1000, 0), True), ((1700, 0), False)])
def test_objective_counts_euclidean_pairs_while_short_span_warning_counts_unwaived_collinear_pairs(other, waived):
    model = from_housing(narrow_request(1, "balanced")["housing"])[0]
    params = FrameParams(housing_column_variant="balanced")
    axes = extract_axes(model, params)
    view = _View(model, axes, params)
    state = _ColumnState(view, plan_cores(model, axes, params), params)
    state.accepted = [_Stack(0, 0, 0, "grid", [0], 0, 0, Fraction(0), id="a"),
                      _Stack(other[0], other[1], 0, "grid", [0], 0, 0, Fraction(0), id="b")]
    if waived:
        for stack in state.accepted:
            stack.tie_keys = ["real-core-tie"]
    log = M.DisclosureLog()
    _warn_final_short_spans(state, log)
    expected_warning = other[1] == 0 and not waived
    assert len([entry for entry in log.entries if entry.code == "W_SHORT_SPAN"]) == int(expected_warning)
    objective = _housing_objective(state.accepted, (), params.min_span)
    assert objective[1] == 1 and objective[0] > 0
    model.columns = [M.Column(stack.id, stack.id, 0, stack.x_mm/1000, stack.y_mm/1000, .23, .23) for stack in state.accepted]
    assert assess(model)["close_pair_count"] == objective[1]
    assert assess(model)["close_pair_deficit_m"] == round(objective[0], 3)
    log.add("W_SHORT_SPAN", "independent grid-axis warning", stage="grid.axes")
    state.accepted[1].x_mm, state.accepted[1].y_mm = 5000, 0
    _warn_final_short_spans(state, log)
    assert [(entry.code, entry.stage) for entry in log.entries] == [("W_SHORT_SPAN", "grid.axes")]


def test_shared_pool_cache_singleflight_returns_fresh_actual_variant_frames():
    clear_housing_search_cache()
    model = from_housing(narrow_request(1, "balanced")["housing"])[0]
    variants = ("balanced", "toward_start", "toward_end")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda variant: run_frame_placement(copy.deepcopy(model), FrameParams(housing_column_variant=variant)), variants))
    counts = housing_search_cache_diagnostics()
    assert counts["pool_computation_count"] == 1
    assert counts["cache_hits"] == 2 and counts["cache_entries"] == 1
    assert [result.params_echo["housing_column_variant"] for result in results] == list(variants)
    assert len({_housing_objective(result.columns, result.beams, 2.5)[-1] for result in results}) == 3
    expected = copy.deepcopy(results[0].to_dict())
    results[0].columns[0].x_mm = 999999
    results[0].metrics["housing_search"]["selected_added"].append([999999, 999999])
    assert run_frame_placement(model, FrameParams(housing_column_variant="balanced")).to_dict() == expected
    assert not model.columns and not model.beams


def test_shared_pool_key_covers_exact_architecture_params_and_engine_context():
    model = from_housing(narrow_request(1, "balanced")["housing"])[0]
    params = FrameParams(housing_column_variant="balanced")
    baseline = _housing_search_signature(model, params, "engine-a")
    assert _housing_search_signature(model, FrameParams(housing_column_variant="toward_end"), "engine-a") == baseline
    assert _housing_search_signature(model, params, "engine-b") != baseline
    assert _housing_search_signature(model, FrameParams(housing_column_variant="balanced", jamb_clearance=.2), "engine-a") != baseline
    changed = copy.deepcopy(model)
    changed.walls[0].a = (changed.walls[0].a[0] + 1e-8, changed.walls[0].a[1])
    assert _housing_search_signature(changed, params, "engine-a") != baseline
    changed = copy.deepcopy(model)
    changed.meta["unrecognized_engineering_context"] = {"rates": [1.25, 2.5]}
    assert _housing_search_signature(changed, params, "engine-a") != baseline


def test_omitted_variant_and_referral_recipe_do_not_enter_shared_search_cache():
    clear_housing_search_cache()
    model = from_housing(narrow_request(1, "balanced")["housing"])[0]
    run_frame_placement(model)
    assert housing_search_cache_diagnostics()["requests"] == 0
    params = FrameParams(housing_column_variant="balanced")
    initial = run_frame_placement(model, params)
    initial.write_back(model)
    before = housing_search_cache_diagnostics()
    repaired = run_frame_placement(model, params, _force_secondary=(initial.panels[0].id,))
    assert housing_search_cache_diagnostics() == before
    assert repaired.metrics["housing_search"]["selected_removed"] == initial.metrics["housing_search"]["selected_removed"]
    assert repaired.metrics["housing_search"]["selected_added"] == initial.metrics["housing_search"]["selected_added"]
