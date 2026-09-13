"""Regression gates for preliminary gravity-only option comparison.

These tests deliberately separate candidate generation from an optimization
claim.  A candidate is eligible only after physical-span, member, foundation
and quantity checks have completed.
"""

from __future__ import annotations

import json
import os

import pytest

from .. import api
from ..placement import foundations as F


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _plan():
    with open(os.path.join(FIXTURES, "plan_2bhk.json"), "r") as handle:
        return json.load(handle)


def _building():
    with open(os.path.join(FIXTURES, "building_3storey.json"), "r") as handle:
        return json.load(handle)


def _request(cap_m=5.0, storeys=2):
    return {
        "source": "plan",
        "plan": _plan(),
        "storeys": storeys,
        "params": {
            "system": "rc_frame",
            "analysis_mode": "gravity_only",
            "placement_strategy": "economy_grid",
            "spans": {"min_m": 2.5, "max_m": cap_m},
        },
        "output": {"detail": "full"},
    }


def _g3_housing_request(cap_m):
    """The reproducible 30 x 40 ft benchmark, four total floors (G+3)."""
    floors = []
    for level in range(4):
        segments = []
        for index, x in enumerate((10.0, 15.0, 20.0), 1):
            segments.append({
                "id": "g3-v-%d-%d" % (level, index),
                "x1": x, "y1": 0.0, "x2": x, "y2": 40.0,
            })
        for index, y in enumerate((10.0, 13.333, 20.0, 26.667, 30.0), 1):
            segments.append({
                "id": "g3-h-%d-%d" % (level, index),
                "x1": 0.0, "y1": y, "x2": 30.0, "y2": y,
            })
        floors.append({
            "id": "g3-floor-%d" % level,
            "level": level,
            "label": ("Ground", "First", "Second", "Third")[level],
            "boundary": [[0.0, 0.0], [30.0, 0.0], [30.0, 40.0], [0.0, 40.0]],
            "segments": segments,
            "shapes": [{
                "id": "g3-stair-shape-%d" % level,
                "points": [[0.0, 0.0], [7.0, 0.0], [7.0, 10.0], [0.0, 10.0]],
                "core": {"id": "g3-stair", "kind": "stairs"},
            }],
            "regionContent": {},
        })
    return {
        "source": "housing",
        "housing": {
            "id": "gravity-g3-regression",
            "name": "Gravity G+3 regression",
            "floors": floors,
            "wallDisplay": {"showInteriorWalls": True, "interiorWallFt": 1.0 / 3.0},
            "roof": "flat",
            "entry": [15.0, 40.0],
        },
        "plot_id": "primary",
        "params": {
            "system": "rc_frame",
            "analysis_mode": "gravity_only",
            "placement_strategy": "economy_grid",
            "spans": {"max_m": cap_m},
        },
        "output": {"detail": "compact", "include_boq": True, "include_quantities": True},
    }


@pytest.fixture(scope="module")
def gravity_design():
    envelope = api.run_design(_request())
    return envelope["response"]["Documents"]["structural"][0]


def test_options_publish_the_explicit_scope_and_candidate_vocabulary():
    entry = api.run_options()["response"]["Documents"]["structural"][0]
    assert entry["analysis_modes"] == list(api.ANALYSIS_MODES)
    assert entry["placement_strategies"] == list(api.PLACEMENT_STRATEGIES)


def test_gravity_mode_has_no_lateral_cases_or_ductile_overlay(gravity_design):
    assert gravity_design["analysis"]["method"] == "tributary_takedown_v1_gravity_only"
    assert set(gravity_design["analysis"]["cases_used"]) == {"DL", "LL", "LLR"}
    assert gravity_design["analysis"]["seismic"] is None
    assert gravity_design["analysis"]["wind"] is None
    assert gravity_design["analysis"]["storey_shears"] == {"x": {}, "y": {}}
    assert gravity_design["options_echo"]["values"]["analysis_mode"] == "gravity_only"
    assert gravity_design["design"]["failed_count"] == 0
    assert "IS13920" not in " ".join(gravity_design["design"]["code_set"])
    assert any(row["code"] == "N_GRAVITY_ONLY" for row in gravity_design["warnings"])


def test_30_by_40_candidate_uses_at_least_the_3_by_4_regular_grid(gravity_design):
    score = gravity_design["layout_score"]["metrics"]
    assert score["axis_count"]["x"] == 3
    assert score["axis_count"]["y"] == 4
    assert score["minimum_regular_grid_columns"] == 12
    assert score["candidate_generator"] == "economy_grid_v0"
    assert len(gravity_design["structural_model"]["columns"]) >= 24  # 12 stacks x G+1 minimum


def test_every_physical_span_respects_the_requested_cap(gravity_design):
    runs = gravity_design["structural_model"]["analysis"]["beam_runs"]
    # floor beams only: plinth ties are reported apart (plinth_max_span_m)
    physical = [float(hi) - float(lo) for run in runs if not run.get("plinth") for lo, hi in run["spans"]]
    assert physical
    assert max(physical) <= 5.0 + 1e-6
    assert gravity_design["analysis"]["physical_max_span_m"] == pytest.approx(max(physical))
    assert gravity_design["analysis"]["physical_span_count"] == len(physical)
    assert gravity_design["analysis"]["drawn_fragments_straddling_supports"] == []
    assert not [
        beam_id
        for run in runs
        for beam_id in run.get("fragments_straddling_supports", [])
    ]


def test_cost_badge_is_relative_and_placeholder_rate_is_not_absolute(gravity_design):
    validity = gravity_design["comparison_validity"]
    assert validity["analysis_scope"] == "preliminary_gravity_comparison"
    assert validity["feasible_for_ranking"] is True
    assert validity["valid_for_relative_cost_comparison"] is True
    assert validity["valid_for_absolute_cost"] is False
    assert validity["cost_basis"] == "indicative_placeholder_rates"
    assert validity["not_for_construction"] is True
    assert validity["claim"].startswith("eligible for like-for-like comparison")


def test_infeasible_design_never_carries_an_eligible_comparison_claim():
    request = _request()
    request["params"]["analysis_mode"] = "code_complete"
    request["params"]["placement_strategy"] = "wall_aligned"
    entry = api.run_design(request)["response"]["Documents"]["structural"][0]
    validity = entry["comparison_validity"]
    assert validity["feasible_for_ranking"] is False
    assert validity["reasons"]
    assert validity["claim"].startswith("not eligible for candidate ranking")


def test_missing_required_design_row_blocks_cost_ranking(monkeypatch):
    original = api._design_members

    def drop_one_footing(*args, **kwargs):
        rows = original(*args, **kwargs)
        footing_id = next(
            row.element_id for row in rows if row.element_type == "footing"
        )
        return [row for row in rows if row.element_id != footing_id]

    monkeypatch.setattr(api, "_design_members", drop_one_footing)
    entry = api.run_design(_request())["response"]["Documents"]["structural"][0]
    validity = entry["comparison_validity"]
    assert entry["design"]["undesigned_count"] > 0
    assert "required_element_undesigned" in validity["reasons"]
    assert validity["feasible_for_ranking"] is False
    assert validity["valid_for_relative_cost_comparison"] is False
    assert validity["claim"].startswith("not eligible for candidate ranking")


def test_cost_ranking_is_blocked_when_boq_was_not_computed():
    request = _request()
    request["output"]["include_boq"] = False
    entry = api.run_design(request)["response"]["Documents"]["structural"][0]
    validity = entry["comparison_validity"]
    assert "cost_not_computed" in validity["reasons"]
    assert validity["feasible_for_ranking"] is False
    assert validity["valid_for_relative_cost_comparison"] is False
    assert validity["valid_for_absolute_cost"] is False
    assert validity["cost_basis"] == "not_computed"
    assert validity["claim"].startswith("not eligible for candidate ranking")


def test_unresolved_foundation_geometry_warning_blocks_cost_ranking(monkeypatch):
    original = api._foundations.layout_foundations

    def add_overlap_warning(*args, **kwargs):
        plan = original(*args, **kwargs)
        plan.warnings.append(
            api.make_disclosure(
                "W_FOOTING_OVERLAP",
                "synthetic post-placement overlap for ranking regression",
                ["F-test-a", "F-test-b"],
                stage="placement.foundations",
            )
        )
        return plan

    monkeypatch.setattr(api._foundations, "layout_foundations", add_overlap_warning)
    entry = api.run_design(_request())["response"]["Documents"]["structural"][0]
    validity = entry["comparison_validity"]
    assert "unresolved_foundation_topology" in validity["reasons"]
    assert validity["feasible_for_ranking"] is False
    assert validity["claim"].startswith("not eligible for candidate ranking")


@pytest.mark.parametrize("cap_m", [5.0, 4.0])
def test_g3_housing_benchmark_is_end_to_end_feasible(cap_m):
    envelope = api.run_design(_g3_housing_request(cap_m))
    assert envelope["status"] == "SUCCESS"
    entry = envelope["response"]["Documents"]["structural"][0]
    assert entry["status"] != "refused"
    assert len(entry["structural_model"]["storeys"]) == 4
    assert entry["design"]["failed_count"] == 0
    assert entry["layout_score"]["hard_violation_count"] == 0
    assert entry["analysis"]["physical_max_span_m"] <= cap_m + 1e-6
    assert entry["analysis"]["drawn_fragments_straddling_supports"] == []
    assert entry["comparison_validity"]["valid_for_relative_cost_comparison"] is True
    model = entry["structural_model"]
    expected_sections = {
        0: {(300, 380)},
        1: {(300, 300)},
        2: {(230, 300)},
        3: {(230, 230)},
    }
    for storey, expected in expected_sections.items():
        assert {
            (column["b_mm"], column["d_mm"])
            for column in model["columns"]
            if column["storey"] == storey
        } == expected
    assert all(slab["thickness_mm"] >= 150 for slab in model["slabs"])
    assert all(
        row["section"]["D_mm"] >= 150
        for row in model["design"]
        if row["element_type"] == "slab" and "D_mm" in row.get("section", {})
    )
    warning_codes = {row["code"] for row in entry["warnings"]}
    assert "W_STEEL_DENSITY_BAND" not in warning_codes
    assert "W_CONCRETE_DENSITY_BAND" not in warning_codes


@pytest.mark.parametrize("reaction_kn", [-5.0, 0.0])
def test_foundation_layout_itself_rejects_non_positive_direct_input(reaction_kn):
    # The API gate must not be the only protection: direct callers cannot have
    # a zero or tension reaction silently replaced by geometric minimum sizing.
    with pytest.raises(F.FoundationLoadError) as error:
        F.layout_foundations(
            F.StructuralModel(id="neg"),
            column_loads={"stk-non-positive": reaction_kn},
            write_back=False,
        )
    assert error.value.code == "E_GRAVITY_UPLIFT"


@pytest.mark.parametrize("field,value", [
    ("analysis_mode", "gravity-ish"),
    ("placement_strategy", "six_columns_please"),
])
def test_unknown_scope_controls_are_rejected_at_the_request_boundary(field, value):
    request = _request()
    request["params"][field] = value
    envelope = api.run_layout(request)
    assert envelope["status"] == "ERROR"
    assert envelope["response"]["Documents"]["error"]["field"] == "params." + field


def test_complex_building_gravity_economy_refuses_instead_of_using_dense_defaults():
    envelope = api.run_layout({
        "source": "building",
        "building": _building(),
        "params": {
            "system": "auto",
            "analysis_mode": "gravity_only",
            "placement_strategy": "economy_grid",
            "spans": {"max_m": 5.0},
        },
    })
    assert envelope["status"] == "ERROR"
    entry = envelope["response"]["Documents"]["structural"][0]
    assert entry["status"] == "refused"
    codes = {row["code"] for row in entry["errors"]}
    assert "E_SPAN_OVER_MAX" in codes
    assert "design" not in entry, "a refused economy layout must not fall through to dense member design"
