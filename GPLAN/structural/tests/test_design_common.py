"""Pins for the shared design contract: materials, cover, the result, bar picking.

This is the module every material designer writes to (critic finding 6), so the
tests here are contract tests: the cover ladder, the effective-depth arithmetic
layering depends on, the DesignResult round trip and its deliberate absence of a
`quantities` field (finding 24), the resize defaults, and the bar-selection
engine on cases that can be checked by hand from the catalogue.
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests, and an absolute GPLAN.structural
# import would resolve against the outer directory instead.
from ..codes import is456
from ..codes.trace import trace_into
from ..data._loader import load_yaml
from ..design import common as C


# ---------------------------------------------------------------------------
# unit boundary
# ---------------------------------------------------------------------------


def test_unit_conversions_are_the_one_boundary():
    assert C.kn_to_n(12.5) == pytest.approx(12500.0)
    assert C.knm_to_nmm(2.5) == pytest.approx(2.5e6)
    assert C.m_to_mm(3.6) == pytest.approx(3600.0)
    assert C.n_to_kn(C.kn_to_n(7.0)) == pytest.approx(7.0)
    assert C.nmm_to_knm(C.knm_to_nmm(7.0)) == pytest.approx(7.0)
    assert C.mm_to_m(C.m_to_mm(7.0)) == pytest.approx(7.0)


def test_module_rounding_goes_the_way_it_says():
    assert C.round_down_mm(157.08, 10.0) == pytest.approx(150.0)
    assert C.round_up_mm(157.08, 25.0) == pytest.approx(175.0)
    assert C.round_down_mm(300.0, 10.0) == pytest.approx(300.0)
    assert C.round_up_mm(300.0, 25.0) == pytest.approx(300.0)
    with pytest.raises(ValueError):
        C.round_down_mm(100.0, 0.0)


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fck", C.CONCRETE_GRADES_MPA)
def test_concrete_grade_constants(fck):
    concrete = C.Concrete(fck_mpa=fck)
    assert concrete.gamma_c == 1.5
    assert concrete.density_knm3 == 25.0
    assert concrete.grade == "M" + str(int(fck))
    assert concrete.ec_mpa == pytest.approx(5000.0 * math.sqrt(fck))
    assert concrete.ec_mpa == pytest.approx(is456.cl_6_2_3_1__ec(fck))
    assert concrete.fcd_mpa == pytest.approx(0.446 * fck)


def test_concrete_from_grade_and_unknown_grade():
    assert C.Concrete.from_grade("M30") == C.Concrete(fck_mpa=30.0)
    assert C.Concrete.from_grade(25) == C.Concrete(fck_mpa=25.0)
    with pytest.raises(ValueError):
        C.Concrete(fck_mpa=45.0)
    with pytest.raises(ValueError):
        C.Concrete.from_grade("M45")


@pytest.mark.parametrize("fy", C.REBAR_GRADES_MPA)
def test_rebar_grade_constants(fy):
    steel = C.RebarSteel(fy_mpa=fy)
    assert steel.gamma_s == 1.15
    assert steel.es_mpa == 200000.0
    assert steel.grade == "Fe" + str(int(fy))
    assert steel.fyd_mpa == pytest.approx(0.87 * fy)


def test_rebar_from_grade_and_unknown_grade():
    assert C.RebarSteel.from_grade("Fe500") == C.RebarSteel(fy_mpa=500.0)
    with pytest.raises(ValueError):
        C.RebarSteel(fy_mpa=250.0)


def test_exposure_grade_check_warns_and_never_fails():
    """Table 5 wants M30 at severe exposure; M25 designs anyway, disclosed."""
    assert C.check_exposure_grade(25.0, "severe") is not None
    assert "Table 5" in C.check_exposure_grade(25.0, "severe")
    assert C.check_exposure_grade(30.0, "severe") is None
    assert C.check_exposure_grade(40.0, "extreme") is None
    assert C.check_exposure_grade(20.0, "mild") is None


def test_materials_block_is_the_result_dict():
    block = C.materials_block(C.Concrete(fck_mpa=25.0), C.RebarSteel(fy_mpa=500.0))
    assert block == {
        "fck_mpa": 25.0,
        "fy_mpa": 500.0,
        "concrete_grade": "M25",
        "steel_grade": "Fe500",
    }


def test_masonry_material_normalises_and_validates():
    material = C.MasonryMaterial(unit_strength_mpa=7.5, mortar_grade="m1")
    assert material.mortar_grade == "M1"
    assert material.to_dict() == {"unit_strength_mpa": 7.5, "mortar_grade": "M1"}
    with pytest.raises(ValueError):
        C.MasonryMaterial(unit_strength_mpa=7.5, mortar_grade="M9")
    with pytest.raises(ValueError):
        C.MasonryMaterial(unit_strength_mpa=0.0, mortar_grade="M1")


# ---------------------------------------------------------------------------
# rebar catalogue: data/rebar.yaml is the only table
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rebar():
    return load_yaml("rebar")


def test_catalogue_dias_come_from_the_yaml(rebar):
    assert C.MAIN_DIAS == tuple(rebar["main_dias_mm"])
    assert C.STIRRUP_DIAS == tuple(rebar["stirrup_dias_mm"])
    assert set(C.STIRRUP_DIAS).issubset(set(C.MAIN_DIAS))


@pytest.mark.parametrize("dia", (8, 10, 12, 16, 20, 25, 32))
def test_catalogue_area_and_mass_match_the_yaml(rebar, dia):
    assert C.bar_area_mm2(dia) == rebar["bars"][dia]["area_mm2"]
    assert C.unit_mass_kg_m(dia) == rebar["bars"][dia]["unit_mass_kg_m"]
    assert C.bar_area_mm2(dia) == pytest.approx(math.pi / 4.0 * dia * dia, rel=0.005)


def test_catalogue_rejects_a_diameter_it_does_not_stock():
    with pytest.raises(ValueError):
        C.bar_area_mm2(14)
    with pytest.raises(ValueError):
        C.unit_mass_kg_m(6)


def test_bend_allowances_come_from_the_yaml(rebar):
    bends = rebar["bend_allowances"]
    assert C.BEND_ALLOWANCES["hook_135_deg_dia"] == bends["hook_135_deg_dia"]
    assert C.BEND_ALLOWANCES["hook_90_deg_dia"] == bends["hook_90_deg_dia"]
    # 10 dia per 135 degree hook, floored at 75 mm: a 6 mm hook is the floor.
    assert C.hook_allowance_mm(8) == pytest.approx(80.0)
    assert C.hook_allowance_mm(6) == pytest.approx(75.0)
    assert C.hook_allowance_mm(20, 90) == pytest.approx(160.0)
    assert C.stirrup_hook_allowance_mm(8) == pytest.approx(160.0)
    with pytest.raises(ValueError):
        C.hook_allowance_mm(8, 45)


# ---------------------------------------------------------------------------
# cover ladder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exposure,expected",
    (("mild", 20.0), ("moderate", 30.0), ("severe", 45.0), ("very_severe", 50.0), ("extreme", 75.0)),
)
def test_cover_ladder_follows_table_16(exposure, expected):
    cover = C.resolve_cover("beam", exposure, fire_rating_h=0.0, bar_dia_mm=12.0)
    assert cover.cover_mm == pytest.approx(expected)
    assert "Table 16" in cover.note
    assert "Table 16A" not in cover.note  # no fire period asked for


@pytest.mark.parametrize(
    "rating,expected", ((0.5, 20.0), (1.0, 20.0), (2.0, 40.0), (3.0, 60.0), (4.0, 70.0))
)
def test_cover_ladder_takes_the_fire_period_when_it_governs(rating, expected):
    """Table 16A beam row, against mild exposure (20 mm) and a 12 mm bar."""
    cover = C.resolve_cover("beam", "mild", fire_rating_h=rating, bar_dia_mm=12.0)
    assert cover.cover_mm == pytest.approx(max(20.0, expected))
    assert "Table 16A" in cover.note


def test_cover_takes_the_bar_diameter_when_it_governs():
    cover = C.resolve_cover("beam", "mild", fire_rating_h=0.0, bar_dia_mm=32.0)
    assert cover.cover_mm == pytest.approx(32.0)
    assert "bar diameter" in cover.note


def test_cover_of_a_footing_is_floored_at_fifty():
    cover = C.resolve_cover("footing", "mild", fire_rating_h=0.0, bar_dia_mm=16.0)
    assert cover.cover_mm == pytest.approx(50.0)
    assert "26.4.2.2" in cover.note
    # Severe exposure still wins over the floor when it is larger.
    assert C.resolve_cover("footing", "extreme", 0.0, 16.0).cover_mm == pytest.approx(75.0)


def test_cover_unpacks_as_a_pair_and_is_traced():
    entries = []
    with trace_into(entries):
        cover_mm, note = C.resolve_cover("slab", "moderate", 1.0, 10.0)
    assert cover_mm == pytest.approx(30.0)
    assert note
    refs = [entry.ref for entry in entries]
    assert "Table 16" in refs and "Table 16A" in refs


# ---------------------------------------------------------------------------
# bar gaps and effective depth
# ---------------------------------------------------------------------------


def test_min_bar_gap_delegates_to_the_clause():
    assert C.min_bar_gap_mm(20.0) == pytest.approx(is456.cl_26_3_2__min_bar_spacing(20.0, 20.0))
    assert C.min_bar_gap_mm(16.0) == pytest.approx(25.0)  # aggregate 20 + 5 governs
    assert C.min_bar_gap_mm(32.0) == pytest.approx(32.0)  # the bar governs


def test_min_vertical_gap_is_the_larger_of_fifteen_two_thirds_agg_and_the_bar():
    assert C.min_vertical_gap_mm(10.0, 20.0) == pytest.approx(15.0)
    assert C.min_vertical_gap_mm(20.0, 20.0) == pytest.approx(20.0)
    assert C.min_vertical_gap_mm(10.0, 40.0) == pytest.approx(26.666667)


def test_effective_depth_single_layer():
    assert C.effective_depth(500.0, 30.0, 8.0, 20.0, layers=1) == pytest.approx(452.0)


def test_effective_depth_with_two_layers_drops_by_half_a_pitch():
    """Pitch is bar + vertical gap = 20 + 20; two equal layers cost half of it."""
    one = C.effective_depth(500.0, 30.0, 8.0, 20.0, layers=1)
    two = C.effective_depth(500.0, 30.0, 8.0, 20.0, layers=2)
    assert C.layer_pitch_mm(20.0) == pytest.approx(40.0)
    assert two == pytest.approx(one - 20.0)
    assert two == pytest.approx(432.0)
    three = C.effective_depth(500.0, 30.0, 8.0, 20.0, layers=3)
    assert three == pytest.approx(one - 40.0)


def test_clear_width_between_stirrup_legs():
    assert C.clear_width_mm(230.0, 30.0, 8.0) == pytest.approx(154.0)


# ---------------------------------------------------------------------------
# bar selection
# ---------------------------------------------------------------------------


def _layer_fits(layer, width_avail_mm):
    """The Cl 26.3.2 feasibility rule, recomputed independently of the engine."""
    gap = is456.cl_26_3_2__min_bar_spacing(max(layer), 20.0)
    return sum(layer) + gap * (len(layer) - 1) <= width_avail_mm + 1e-9


def test_pick_bars_one_layer_in_a_230_web():
    """1000 mm2 between the stirrup legs of a 230 x D beam, 30 cover, 8 stirrup.

    154 mm clear. 2-20 + 2-16 gives 1030 mm2 (3 percent over) in one layer and
    needs 40 + 32 + 3 x 25 = 147 mm, so it fits; every layout with less excess
    needs a second layer or more bars.
    """
    width = C.clear_width_mm(230.0, 30.0, 8.0)
    layout = C.pick_bars(1000.0, width)
    assert layout.ok
    assert layout.ast_prov_mm2 >= 1000.0
    assert layout.layers == 1
    assert layout.d_adjust_mm == pytest.approx(0.0)
    assert layout.bars == ((2, 20), (2, 16))
    assert layout.label == "2-20 + 2-16"
    assert layout.count == 4
    assert layout.width_used_mm == pytest.approx(147.0)
    assert _layer_fits(layout.layer_dias_mm[0], width)


def test_pick_bars_layout_is_symmetric():
    """At most one odd group: the odd bars sit on the centreline, the rest pair."""
    for required in (400.0, 700.0, 1000.0, 1500.0, 2200.0):
        layout = C.pick_bars(required, 230.0)
        odd = [count for count, _ in layout.bars if count % 2]
        assert len(odd) <= 1, layout.label


def test_pick_bars_falls_to_two_layers_when_the_width_runs_out():
    layout = C.pick_bars(2000.0, 150.0)
    assert layout.ok
    assert layout.ast_prov_mm2 >= 2000.0
    assert layout.layers == 2
    assert layout.d_adjust_mm > 0.0
    assert len(layout.layer_dias_mm) == 2
    for layer in layout.layer_dias_mm:
        assert _layer_fits(layer, 150.0)


def test_two_layer_d_adjust_matches_effective_depth_for_equal_layers():
    """Two equal layers of 20 mm bars: the centroid drops half a pitch, 20 mm."""
    layout = C.pick_bars(1250.0, 100.0)
    assert layout.bars == ((4, 20),)
    assert layout.layers == 2
    assert layout.d_adjust_mm == pytest.approx(20.0)
    one = C.effective_depth(450.0, 30.0, 8.0, 20.0, layers=1)
    two = C.effective_depth(450.0, 30.0, 8.0, 20.0, layers=2)
    assert one - layout.d_adjust_mm == pytest.approx(two)


def test_pick_bars_respects_the_clear_spacing_rule_everywhere():
    for required in (300.0, 900.0, 1800.0, 3000.0):
        for width in (120.0, 154.0, 240.0, 340.0):
            layout = C.pick_bars(required, width)
            assert layout.layers <= 2
            for layer in layout.layer_dias_mm:
                assert _layer_fits(layer, width), (required, width, layout.label)


def test_pick_bars_discloses_a_requirement_the_catalogue_cannot_meet():
    layout = C.pick_bars(9000.0, 154.0)
    assert layout.ok is False
    assert layout.note
    assert layout.ast_prov_mm2 > 0.0
    assert layout.bars  # never an empty result


def test_pick_bars_discloses_a_width_nothing_fits():
    layout = C.pick_bars(500.0, 30.0)
    assert layout.ok is False
    assert "26.3.2" in layout.note
    assert layout.bars == ((2, 8),)
    assert layout.layers == 1


def test_pick_bars_is_deterministic():
    first = C.pick_bars(1234.0, 154.0)
    second = C.pick_bars(1234.0, 154.0)
    assert first == second
    assert first.to_dict() == second.to_dict()


def test_pick_bars_honours_the_prefs():
    prefs = C.BarPrefs(dias_mm=(12, 16, 20), min_dia_mm=12, max_distinct_dias=1, max_layers=1)
    layout = C.pick_bars(1000.0, 300.0, prefs)
    assert len(layout.bars) == 1
    assert layout.bars[0][1] in (12, 16, 20)
    assert layout.layers == 1


def test_pick_bars_traces_the_gap_clause_once_per_diameter():
    entries = []
    with trace_into(entries):
        C.pick_bars(1000.0, 154.0)
    refs = [entry.ref for entry in entries]
    assert refs.count("26.3.2") == len(C.MAIN_DIAS)


def test_spacing_for_area_rounds_down_to_the_module():
    # 10 mm bars, 500 mm2/m: 78.54 * 1000 / 500 = 157.1 mm, down to 150.
    assert C.spacing_for_area(500.0, 10) == pytest.approx(150.0)
    # 8 mm bars, 200 mm2/m: 251.3 mm, down to 250.
    assert C.spacing_for_area(200.0, 8) == pytest.approx(250.0)
    # The clause cap wins before the rounding.
    assert C.spacing_for_area(100.0, 8) == pytest.approx(300.0)
    assert C.spacing_for_area(100.0, 8, max_spacing_mm=450.0) == pytest.approx(450.0)
    # Never zero, whatever is asked for.
    assert C.spacing_for_area(1e6, 8) == pytest.approx(10.0)


def test_spacing_for_area_never_under_provides():
    for required in (150.0, 335.0, 500.0, 900.0):
        for dia in (8, 10, 12):
            spacing = C.spacing_for_area(required, dia, max_spacing_mm=1e6)
            assert C.area_for_spacing(dia, spacing) >= required - 1e-9


def test_area_for_spacing_is_the_inverse():
    assert C.area_for_spacing(10, 150.0) == pytest.approx(78.54 * 1000.0 / 150.0)
    with pytest.raises(ValueError):
        C.area_for_spacing(10, 0.0)


# ---------------------------------------------------------------------------
# the result contract
# ---------------------------------------------------------------------------


def _sample_result():
    result = C.DesignResult(element_id="beam-1-A-0", element_type="beam")
    result.section = {"b_mm": 230.0, "D_mm": 450.0, "d_mm": 412.0, "cover_mm": 30.0, "length_mm": 4200.0}
    result.materials = C.materials_block(C.Concrete(fck_mpa=25.0), C.RebarSteel(fy_mpa=500.0))
    result.add_bar("bottom_mid", 3, 16.0, ld_mm=752.0, zone_mm=(0.0, 4200.0), layer=1)
    result.add_bar("top_left", 2, 16.0, ld_mm=752.0, zone_mm=(0.0, 1300.0), layer=1)
    result.add_stirrup((0.0, 824.0), 2, 8.0, 100.0, kind="shear")
    result.add_check("flexure midspan", "IS456:2000 G-1.1(a)", 120.0e6, 150.0e6, units="N.mm")
    result.add_check("shear end A", "IS456:2000 40.4", 90.0e3, 100.0e3, units="N")
    result.add_check("span/d", "IS456:2000 23.2.1", 18.0, 20.0, units="")
    return result


def test_design_result_finalize_picks_the_worst_ratio():
    result = _sample_result().finalize()
    assert result.utilization_max == pytest.approx(0.9)
    assert result.governing_check == "shear end A"
    assert result.status == C.STATUS_PASS


def test_design_result_finalize_cannot_claim_pass_with_a_failed_row():
    result = _sample_result()
    result.add_check("shear cap", "IS456:2000 Table 20", 3.4, 3.1, units="MPa")
    result.finalize()
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "shear cap"
    assert result.utilization_max == pytest.approx(3.4 / 3.1)


def test_design_result_resize_history_marks_the_status():
    result = _sample_result()
    result.add_resize(450.0, 475.0, "span/d")
    assert result.status == C.STATUS_RESIZED
    assert result.resize_history == [{"from": 450.0, "to": 475.0, "reason": "span/d"}]
    result.finalize()
    assert result.status == C.STATUS_RESIZED


def test_design_result_fail_with_is_fully_populated():
    result = _sample_result()
    result.fail_with(
        "shear cap",
        reason="tau_v exceeds tau_c,max at both ends",
        clause="IS456:2000 Table 20",
        demand=3.4,
        capacity=3.1,
        units="MPa",
    )
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "shear cap"
    assert result.warnings == ["tau_v exceeds tau_c,max at both ends"]
    # Still a complete result: section, materials, bars and checks all survive.
    assert result.section["b_mm"] == 230.0
    assert result.bars and result.stirrups
    assert len(result.checks) == 4
    assert result.utilization_max > 1.0


def test_design_result_fail_with_pins_a_governing_check_that_has_no_ratio():
    result = C.DesignResult(element_id="col-1-A-0", element_type="column")
    result.add_check("axial", "IS456:2000 39.3", 400.0e3, 900.0e3, units="N")
    result.fail_with("geometry IS 13920 Cl 7.1", reason="least dimension below 300 mm")
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "geometry IS 13920 Cl 7.1"
    assert result.utilization_max == pytest.approx(400.0 / 900.0)


def test_check_row_ratio_and_verdict():
    row = C.CheckRow.evaluate("flexure", "G-1.1(a)", 150.0, 100.0, units="N.mm")
    assert row.ratio == pytest.approx(1.5)
    assert row.status == C.CHECK_FAIL
    assert row.ok is False
    exact = C.CheckRow.evaluate("flexure", "G-1.1(a)", 100.0, 100.0)
    assert exact.status == C.CHECK_PASS
    # A zero capacity is full utilization, and stays a finite number.
    zero = C.CheckRow.evaluate("punching", "31.6.3", 10.0, 0.0)
    assert zero.ratio == C.RATIO_CAP
    assert zero.status == C.CHECK_FAIL
    assert math.isfinite(zero.to_dict()["ratio"])
    nothing = C.CheckRow.evaluate("torsion", "41.3.1", 0.0, 0.0)
    assert nothing.ratio == 0.0
    assert nothing.status == C.CHECK_PASS


def test_bars_carry_their_own_ld_and_zone():
    """Finding 24: the schedule reads ld_mm and zone_mm off the bar, no defaults."""
    result = _sample_result()
    for bar in result.to_dict()["bars"]:
        assert "ld_mm" in bar and bar["ld_mm"] > 0.0
        assert "zone_mm" in bar and len(bar["zone_mm"]) == 2
    with pytest.raises(ValueError):
        result.add_bar("top_right", 2, 16.0, ld_mm=None, zone_mm=(0.0, 100.0))
    with pytest.raises(ValueError):
        result.add_bar("top_right", 2, 16.0, ld_mm=752.0, zone_mm=None)
    with pytest.raises(ValueError):
        result.add_bar("top_right", 2, 16.0, ld_mm=752.0, zone_mm=(0.0,))


def test_design_result_has_no_quantities_field():
    """Finding 24: quantities.py is the sole take-off owner."""
    names = {f.name for f in dataclasses.fields(C.DesignResult)}
    assert "quantities" not in names
    result = _sample_result().finalize()
    assert not hasattr(result, "quantities")
    assert "quantities" not in result.to_dict()


def test_design_result_round_trip():
    entries = []
    with trace_into(entries):
        is456.annex_g__mu_lim(230.0, 412.0, 25.0, 500.0)
    result = _sample_result()
    result.trace = list(entries)
    result.add_note("curtailment run full length, disclosed conservative")
    result.add_warning("simple support anchorage short; hook added")
    result.add_referral("add_secondary_beams", {"suggested_spacing_m": 3.0})
    result.finalize()

    wire = result.to_dict()
    again = C.DesignResult.from_dict(wire).to_dict()
    assert again == wire
    assert json.loads(json.dumps(wire)) == wire
    assert "G-1.1(b)" in [entry["ref"] for entry in wire["trace"]]
    assert wire["referrals"][0]["action"] == "add_secondary_beams"
    assert wire["status"] == C.STATUS_PASS
    assert wire["governing_check"] == "shear end A"


def test_design_result_dict_is_stable_across_identical_builds():
    assert _sample_result().finalize().to_dict() == _sample_result().finalize().to_dict()


def test_extras_carry_a_material_specific_field():
    """Finding 6: masonry keeps `prescription` as an extension, not a new class."""
    result = C.DesignResult(element_id="wall-0-x-1200", element_type="masonry_wall")
    result.extras["prescription"] = {"thickness_mm": 230, "mortar_grade": "M1"}
    wire = result.finalize().to_dict()
    assert wire["prescription"] == {"thickness_mm": 230, "mortar_grade": "M1"}
    assert C.DesignResult.from_dict(wire).extras["prescription"] == wire["prescription"]


def test_warnings_and_notes_do_not_repeat():
    result = C.DesignResult(element_id="slab-0-1", element_type="slab")
    result.add_warning("panel stuck at 150 mm")
    result.add_warning("panel stuck at 150 mm")
    result.add_note("corner torsion mesh provided")
    result.add_note("corner torsion mesh provided")
    assert result.warnings == ["panel stuck at 150 mm"]
    assert result.notes == ["corner torsion mesh provided"]


def test_referral_vocabulary_is_the_one_run_design_executes():
    """Finding 19 dropped combine_footings and strap_required from the design side."""
    assert "add_secondary_beams" in C.REFERRAL_ACTIONS
    assert "combine_footings" not in C.REFERRAL_ACTIONS
    assert "strap_required" not in C.REFERRAL_ACTIONS


# ---------------------------------------------------------------------------
# resize policy
# ---------------------------------------------------------------------------


def test_resize_policy_defaults():
    policy = C.ResizePolicy()
    assert policy.beam_depth_step_mm == 25.0
    assert policy.beam_width_seq_mm == (230.0, 300.0)
    assert policy.column_step_mm == 50.0
    assert policy.column_cap_mm == 600.0
    assert policy.slab_step_mm == 10.0
    assert policy.slab_cap_mm == 150.0
    assert policy.footing_depth_step_mm == 50.0
    assert policy.footing_plan_step_mm == 100.0
    assert policy.max_iters == 12


def test_beam_depth_cap_is_the_larger_of_one_and_a_half_d0_and_span_over_eight():
    policy = C.ResizePolicy()
    assert policy.beam_depth_cap(450.0, 6000.0) == pytest.approx(750.0)  # span/8
    assert policy.beam_depth_cap(450.0, 4000.0) == pytest.approx(675.0)  # 1.5 D0
    assert C.default_beam_depth_cap(300.0, 3000.0) == pytest.approx(450.0)


def test_resize_policy_round_trip_keeps_the_numbers():
    policy = C.ResizePolicy(column_cap_mm=750.0, max_iters=6)
    wire = policy.to_dict()
    assert "beam_depth_cap" not in wire  # a callable is not wire data
    back = C.ResizePolicy.from_dict(wire)
    assert back.to_dict() == wire
    assert back.column_cap_mm == 750.0
    assert back.max_iters == 6
    assert back.beam_depth_cap(400.0, 8000.0) == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# material dispatch
# ---------------------------------------------------------------------------


def test_material_registry_is_total():
    assert tuple(sorted(C.MATERIAL_DESIGNERS)) == tuple(sorted(C.MATERIALS))
    assert C.MATERIALS == ("rcc", "masonry", "steel", "timber")


def test_register_and_get_designer():
    previous = C.MATERIAL_DESIGNERS["timber"]
    try:
        C.register_designer("timber", lambda element, ctx: None)
        assert callable(C.get_designer("timber"))
    finally:
        C.MATERIAL_DESIGNERS["timber"] = previous
    with pytest.raises(ValueError):
        C.register_designer("bamboo", lambda: None)
    with pytest.raises(ValueError):
        C.get_designer("bamboo")
    with pytest.raises(ValueError):
        C.register_designer("timber", "not callable")
