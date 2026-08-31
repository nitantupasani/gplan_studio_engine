"""Pins for the masonry code layer: IS 1905 tables, IS 4326 tables, SP 20 vectors.

Every number asserted here is either a printed grid corner, an interpolation
whose arithmetic is written out in the assertion, or an end to end wall check
whose hand arithmetic lives in vectors/sp20/wall_examples.yaml. A table edit
that moves a value moves a test, which is the point.
"""

from __future__ import annotations

import os

import pytest
import yaml

# Relative: see the note in test_model_roundtrip.py.
from ..codes.is1905 import (
    CodeInputError,
    area_reduction_factor,
    basic_compressive_stress,
    check_max_slenderness,
    effective_height,
    effective_length,
    effective_thickness,
    max_slenderness,
    permissible_compressive_stress,
    permissible_shear,
    permissible_tension,
    shape_modification_factor,
    slenderness_ratio,
    stress_reduction_factor,
)
from ..codes.is1905 import tables as is1905_tables
from ..codes.is4326 import (
    check_openings,
    gable_band,
    lintel_band,
    opening_limits,
    plinth_band,
    roof_band,
    seismic_category,
    vertical_bars,
)
from ..codes.is4326 import tables as is4326_tables
from ..codes.trace import trace_into
from ..model import Opening, OpeningKind, WallLine

VECTORS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vectors", "sp20", "wall_examples.yaml")

THIRD = 1.0 / 3.0
SIXTH = 1.0 / 6.0
TWELFTH = 1.0 / 12.0
TWENTY_FOURTH = 1.0 / 24.0


def _close(value, expected):
    return value == pytest.approx(expected, rel=1e-5, abs=1e-6)


# ---------------------------------------------------------------------------
# data file hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("loader", [is1905_tables, is4326_tables], ids=["is1905", "is4326"])
def test_every_table_block_carries_its_provenance(loader):
    data = loader()
    assert data["source"]
    assert data["edition"]
    for key in sorted(data):
        block = data[key]
        if not isinstance(block, dict):
            continue
        assert "source" in block, key + " has no source"
        assert "edition" in block, key + " has no edition"
        # Every block states its print-verification status. "print" means the
        # block has not been read back against the printed standard; anything
        # else must start with "verified" and name what it was read against
        # (task J4, 2026-08-30). A block with no marker at all is the bug this
        # assertion exists to catch.
        marker = block.get("verify")
        assert isinstance(marker, str) and marker, key + " carries no verify marker"
        assert marker == "print" or marker.startswith("verified "), (
            key + " has an unreadable verify marker: " + repr(marker)
        )


# ---------------------------------------------------------------------------
# IS 1905 Table 8
# ---------------------------------------------------------------------------


def test_table_8_corners():
    # Corners of the printed IS 1905:1987 Table 8, read against the print on
    # 2026-08-30. The 3.5 N/mm2 H1 cell is the one Amendment No. 1 (August
    # 2010) corrects from the printed 8.35 to 0.35.
    assert basic_compressive_stress(3.5, "H1") == pytest.approx(0.35)
    assert basic_compressive_stress(3.5, "L2") == pytest.approx(0.25)
    assert basic_compressive_stress(40.0, "H1") == pytest.approx(3.05)
    assert basic_compressive_stress(40.0, "L2") == pytest.approx(0.95)


def test_table_8_interpolates_on_unit_strength_only():
    # 8.75 sits midway between the 7.5 (0.74) and 10.0 (0.96) columns of M1.
    assert basic_compressive_stress(8.75, "M1") == pytest.approx(0.85)
    # The grade is categorical: M2 at the same strength reads its own row,
    # the printed 0.59 and 0.81.
    assert basic_compressive_stress(8.75, "M2") == pytest.approx(0.5 * (0.59 + 0.81))


def test_table_8_clamps_above_the_last_column_and_refuses_below_the_first():
    assert basic_compressive_stress(60.0, "M1") == pytest.approx(basic_compressive_stress(40.0, "M1"))
    with pytest.raises(CodeInputError):
        basic_compressive_stress(3.0, "M1")
    with pytest.raises(CodeInputError):
        basic_compressive_stress(10.0, "M9")


def test_table_8_is_case_insensitive_on_the_grade():
    assert basic_compressive_stress(10.0, "h2") == basic_compressive_stress(10.0, "H2")


# ---------------------------------------------------------------------------
# IS 1905 Tables 4, 5, 6 and Cl 4.6.1
# ---------------------------------------------------------------------------


def test_table_4_effective_height_cases():
    assert effective_height(3.0, "full", "full") == pytest.approx(2.25)
    assert effective_height(3.0, "full", "lateral") == pytest.approx(2.55)
    assert effective_height(3.0, "lateral", "full") == pytest.approx(2.55)
    assert effective_height(3.0, "lateral", "lateral") == pytest.approx(3.0)
    assert effective_height(3.0, "free", "full") == pytest.approx(4.5)
    assert effective_height(3.0, "free", "lateral") == pytest.approx(6.0)


def test_table_4_refuses_a_wall_free_at_the_bottom():
    with pytest.raises(CodeInputError):
        effective_height(3.0, "full", "free")
    with pytest.raises(CodeInputError):
        effective_height(3.0, "full", "propped")


def test_table_5_effective_length_cases():
    assert effective_length(4.0, ("continuous", "continuous")) == pytest.approx(3.2)
    assert effective_length(4.0, ("continuous", "cross_wall")) == pytest.approx(3.6)
    assert effective_length(4.0, ("cross_wall", "continuous")) == pytest.approx(3.6)
    assert effective_length(4.0, ("cross_wall", "cross_wall")) == pytest.approx(4.0)
    assert effective_length(4.0, ("continuous", "free")) == pytest.approx(6.0)
    assert effective_length(4.0, ("cross_wall", "free")) == pytest.approx(8.0)


def test_table_5_refuses_a_wall_free_at_both_ends():
    with pytest.raises(CodeInputError):
        effective_length(4.0, ("free", "free"))
    with pytest.raises(CodeInputError):
        effective_length(4.0, ("cross_wall",))


def test_table_6_solid_stiffened_and_cavity():
    assert effective_thickness(0.23) == pytest.approx(0.23)
    # Grid corners: Tp/t = 1 is unity everywhere, Tp/t = 3 at Sp/Wp = 6 is 2.0.
    assert effective_thickness(0.2, pier_spacing_m=1.2, pier_width_m=0.2, pier_depth_m=0.2) == pytest.approx(0.2)
    assert effective_thickness(0.2, pier_spacing_m=1.2, pier_width_m=0.2, pier_depth_m=0.6) == pytest.approx(0.4)
    # Sp/Wp = 20 collapses every row back to unity.
    assert effective_thickness(0.2, pier_spacing_m=4.0, pier_width_m=0.2, pier_depth_m=0.6) == pytest.approx(0.2)
    # Interior point: Tp/t = 2, Sp/Wp = 9 sits midway between 1.3 and 1.2.
    assert effective_thickness(0.2, pier_spacing_m=1.8, pier_width_m=0.2, pier_depth_m=0.4) == pytest.approx(0.2 * 1.25)
    # Cavity: the greater of 2/3 the sum and the thicker leaf.
    assert effective_thickness(0.29, cavity_leaves_m=(0.115, 0.115)) == pytest.approx(2.0 / 3.0 * 0.23)
    assert effective_thickness(0.35, cavity_leaves_m=(0.23, 0.05)) == pytest.approx(0.23)


def test_table_6_refuses_a_half_described_pier():
    with pytest.raises(CodeInputError):
        effective_thickness(0.23, pier_spacing_m=1.2, pier_width_m=0.2)
    with pytest.raises(CodeInputError):
        effective_thickness(0.23, cavity_leaves_m=(0.115,))
    with pytest.raises(CodeInputError):
        effective_thickness(0.0)


def test_slenderness_takes_the_lesser_term_and_tolerates_no_length():
    assert slenderness_ratio.clause_meta.clause_id == "IS1905:1987 Cl 4.6.1"
    assert slenderness_ratio(2.1375, 3.6, 0.23) == pytest.approx(2.1375 / 0.23)
    assert slenderness_ratio(3.6, 2.1375, 0.23) == pytest.approx(2.1375 / 0.23)
    assert slenderness_ratio(2.025, None, 0.23) == pytest.approx(2.025 / 0.23)
    with pytest.raises(CodeInputError):
        slenderness_ratio(2.0, None, 0.0)


def test_slenderness_caps_are_27_on_cement_and_20_on_lime():
    assert max_slenderness("M1") == pytest.approx(27.0)
    assert max_slenderness("M3") == pytest.approx(27.0)
    assert max_slenderness("L1") == pytest.approx(20.0)
    assert check_max_slenderness(27.0, 2, "M1") is True
    assert check_max_slenderness(27.01, 2, "M1") is False
    assert check_max_slenderness(20.0, 2, "L2") is True
    assert check_max_slenderness(20.5, 2, "L1") is False
    # A cement mortar tolerates a slenderness a lime mortar does not.
    assert check_max_slenderness(24.0, 3, "H1") is True
    assert check_max_slenderness(24.0, 3, "L1") is False
    with pytest.raises(CodeInputError):
        check_max_slenderness(10.0, 0, "M1")


# ---------------------------------------------------------------------------
# IS 1905 Table 9
# ---------------------------------------------------------------------------


def test_table_9_corners():
    assert stress_reduction_factor(6, 0.0).ks == pytest.approx(1.00)
    assert stress_reduction_factor(6, THIRD).ks == pytest.approx(1.00)
    assert stress_reduction_factor(27, 0.0).ks == pytest.approx(0.43)
    # The last row stops at e/t = 1/6: past that the printed table is blank.
    assert stress_reduction_factor(27, SIXTH).ks == pytest.approx(0.22)
    assert stress_reduction_factor(22, THIRD).ks == pytest.approx(0.24)


def test_table_9_bilinear_midpoint():
    # SR 9 is midway between rows 8 and 10; e/t 0.0625 is midway between the
    # 1/24 and 1/12 columns. Corners 0.95, 0.94, 0.88, 0.87 average to 0.91.
    result = stress_reduction_factor(9.0, 0.5 * (TWENTY_FOURTH + TWELFTH))
    assert result.ok is True
    assert result.ks == pytest.approx(0.25 * (0.95 + 0.94 + 0.88 + 0.87))


def test_table_9_interpolates_on_one_axis_at_a_time():
    # Column e/t = 1/6 only: SR 9 sits midway between 0.93 and 0.85.
    assert stress_reduction_factor(9.0, SIXTH).ks == pytest.approx(0.89)
    # Row SR = 12 only: e/t midway between 1/6 (0.78) and 1/4 (0.75).
    assert stress_reduction_factor(12.0, 0.5 * (SIXTH + 0.25)).ks == pytest.approx(0.765)


def test_table_9_clamps_below_the_first_row():
    assert stress_reduction_factor(4.0, 0.0).ks == pytest.approx(1.00)
    assert stress_reduction_factor(0.0, SIXTH).ks == pytest.approx(1.00)


def test_table_9_returns_none_when_the_eccentricity_leaves_the_table():
    result = stress_reduction_factor(12.0, 0.4)
    assert result.ks is None
    assert result.ok is False
    assert "1/3" in result.reason
    assert result.e_over_t == pytest.approx(0.4)


def test_table_9_returns_none_for_a_cell_the_print_leaves_blank():
    result = stress_reduction_factor(27.0, THIRD)
    assert result.ks is None
    assert result.ok is False
    assert "blank" in result.reason


def test_table_9_returns_none_above_the_last_row():
    result = stress_reduction_factor(30.0, 0.0)
    assert result.ks is None
    assert result.ok is False
    assert "27" in result.reason


def test_table_9_refuses_a_negative_eccentricity():
    with pytest.raises(CodeInputError):
        stress_reduction_factor(10.0, -0.01)


# ---------------------------------------------------------------------------
# IS 1905 Cl 5.4
# ---------------------------------------------------------------------------


def test_area_reduction_factor_endpoints():
    assert area_reduction_factor(0.0) == pytest.approx(0.70)
    assert area_reduction_factor(0.1) == pytest.approx(0.85)
    assert area_reduction_factor(0.138) == pytest.approx(0.907)
    # The formula reaches 1.0 exactly at the 0.2 m2 threshold and stays there.
    assert area_reduction_factor(0.2) == pytest.approx(1.0)
    assert area_reduction_factor(5.0) == pytest.approx(1.0)
    with pytest.raises(CodeInputError):
        area_reduction_factor(-0.1)


def test_shape_modification_factor_defaults_to_unity_and_interpolates():
    assert shape_modification_factor() == pytest.approx(1.0)
    assert shape_modification_factor(0.5) == pytest.approx(1.0)
    assert shape_modification_factor(1.0) == pytest.approx(1.2)
    assert shape_modification_factor(1.25) == pytest.approx(1.35)
    # The printed Table 10 ends with a flat "2.0 to 4.0" band at 1.8; there is
    # no 2.0 anywhere in it.
    assert shape_modification_factor(3.0) == pytest.approx(1.8)
    assert shape_modification_factor(6.0) == pytest.approx(1.8)
    with pytest.raises(CodeInputError):
        shape_modification_factor(0.0)


def test_permissible_compressive_stress_is_the_product():
    assert permissible_compressive_stress(0.59, 0.911196, 1.0, 1.0) == pytest.approx(0.59 * 0.911196)
    assert permissible_compressive_stress(0.96, 0.9, 0.907, 1.2) == pytest.approx(0.96 * 0.9 * 0.907 * 1.2)
    with pytest.raises(CodeInputError):
        permissible_compressive_stress(0.59, None, 1.0, 1.0)
    with pytest.raises(CodeInputError):
        permissible_compressive_stress(-0.1, 0.9, 1.0, 1.0)


def test_permissible_shear_rises_with_dead_stress_then_caps_at_half_an_mpa():
    entries = []
    with trace_into(entries):
        permissible_shear(0.6, "M1")
    assert [entry.clause_id for entry in entries] == ["IS1905:1987 Cl 5.4.3"]
    assert permissible_shear(0.0, "M1") == pytest.approx(0.1)
    assert permissible_shear(0.6, "M1") == pytest.approx(0.2)
    # 0.1 + 2.4/6 lands exactly on the cap.
    assert permissible_shear(2.4, "M1") == pytest.approx(0.5)
    assert permissible_shear(3.0, "H2") == pytest.approx(0.5)
    assert permissible_shear(50.0, "H1") == pytest.approx(0.5)
    with pytest.raises(CodeInputError):
        permissible_shear(-0.1, "M1")


def test_permissible_shear_is_restricted_to_mortar_not_leaner_than_m1():
    # The printed clause reads "in case of walls built in mortar not leaner
    # than Grade M1"; a leaner grade gets no shear value from the formula,
    # mirroring the permitted_mortars restriction the tension clause carries.
    for grade in ("H1", "H2", "M1"):
        assert permissible_shear(0.6, grade) == pytest.approx(0.2), grade
    for grade in ("M2", "M3", "L1", "L2"):
        assert permissible_shear(0.6, grade) == 0.0, grade
        assert permissible_shear(0.0, grade) == 0.0, grade
    with pytest.raises(CodeInputError):
        permissible_shear(0.6, "M9")


def test_permissible_tension_is_zero_under_the_default_policy():
    entries = []
    with trace_into(entries):
        permissible_tension("normal_to_bed", "H1")
    assert [entry.clause_id for entry in entries] == ["IS1905:1987 Cl 5.4.2"]
    assert permissible_tension("normal_to_bed", "H1") == pytest.approx(0.0)
    assert permissible_tension("parallel_to_bed", "M1") == pytest.approx(0.0)


def test_permissible_tension_under_the_flexural_policy():
    assert permissible_tension("normal_to_bed", "M1", policy="allow_flexural_tension") == pytest.approx(0.07)
    assert permissible_tension("parallel_to_bed", "H1", policy="allow_flexural_tension") == pytest.approx(0.14)
    # Weaker mortars stay at zero even with the policy on.
    assert permissible_tension("parallel_to_bed", "M3", policy="allow_flexural_tension") == pytest.approx(0.0)
    assert permissible_tension("normal_to_bed", "L1", policy="allow_flexural_tension") == pytest.approx(0.0)
    with pytest.raises(CodeInputError):
        permissible_tension("diagonal", "M1", policy="allow_flexural_tension")
    with pytest.raises(CodeInputError):
        permissible_tension("normal_to_bed", "M1", policy="ignore_tension")


# ---------------------------------------------------------------------------
# IS 4326 seismic category
# ---------------------------------------------------------------------------


def test_seismic_category_at_ordinary_importance():
    assert [seismic_category(zone) for zone in ("II", "III", "IV", "V")] == ["B", "C", "D", "E"]
    assert [seismic_category(zone) for zone in (2, 3, 4, 5)] == ["B", "C", "D", "E"]


def test_seismic_category_bumps_one_step_for_an_important_building():
    assert [seismic_category(zone, 1.5) for zone in ("II", "III", "IV", "V")] == ["C", "D", "E", "E"]
    assert seismic_category("III", 2.0) == "D"
    # Just under the threshold nothing moves.
    assert seismic_category("III", 1.49) == "C"


def test_seismic_category_refuses_an_unknown_zone():
    with pytest.raises(CodeInputError):
        seismic_category("VI")
    with pytest.raises(CodeInputError):
        seismic_category(0)


# ---------------------------------------------------------------------------
# IS 4326 Table 4
# ---------------------------------------------------------------------------


def test_opening_limits_grid():
    # The printed IS 4326:1993 Table 4 has three category columns, "A and B",
    # "C" and "D and E", read against the print on 2026-08-30.
    rules = opening_limits(2, "D")
    assert rules.b5_corner_min_m == pytest.approx(0.450)
    assert rules.b4_pier_min_m == pytest.approx(0.560)
    assert rules.opening_ratio_max == pytest.approx(0.42)
    assert rules.h3_vertical_gap_min_m == pytest.approx(0.600)
    # b5 is zero for A and B together, 230 only at C, 450 for D and E.
    assert opening_limits(1, "A").b5_corner_min_m == pytest.approx(0.0)
    assert opening_limits(1, "B").b5_corner_min_m == pytest.approx(0.0)
    assert opening_limits(1, "C").b5_corner_min_m == pytest.approx(0.230)
    # b4 is 340 for A and B, 450 at C, 560 for D and E.
    assert opening_limits(1, "B").b4_pier_min_m == pytest.approx(0.340)
    assert opening_limits(1, "C").b4_pier_min_m == pytest.approx(0.450)
    assert opening_limits(1, "E").b4_pier_min_m == pytest.approx(0.560)
    # Ratio falls with height, and each class is tighter than the one above.
    assert [opening_limits(n, "B").opening_ratio_max for n in (1, 2, 3)] == [0.60, 0.50, 0.42]
    assert [opening_limits(n, "C").opening_ratio_max for n in (1, 2, 3)] == [0.55, 0.46, 0.37]
    assert [opening_limits(n, "E").opening_ratio_max for n in (1, 2, 3)] == [0.50, 0.42, 0.33]


def test_opening_limits_clamp_a_taller_stack_to_the_last_encoded_row():
    assert opening_limits(6, "D").storeys == 3
    assert opening_limits(6, "D").opening_ratio_max == pytest.approx(opening_limits(3, "D").opening_ratio_max)
    with pytest.raises(CodeInputError):
        opening_limits(0, "D")
    with pytest.raises(CodeInputError):
        opening_limits(2, "F")


def _opening(name, s0_m, width_m, sill_m, head_m, kind=OpeningKind.WINDOW):
    return Opening(
        id=name,
        kind=kind,
        offset_m=s0_m + 0.5 * width_m,
        width_m=width_m,
        sill_m=sill_m,
        head_m=head_m,
    )


def _breached_wall():
    """A 4.0 m segment carrying one of every Table 4 breach at category D."""
    return WallLine(
        id="wall-breached",
        storey=0,
        a=(0.0, 0.0),
        b=(4.0, 0.0),
        thickness_m=0.23,
        openings=[
            # jamb only 0.10 m from the corner, against a 0.45 m minimum
            _opening("o1-door", 0.10, 1.20, 0.0, 2.10, kind=OpeningKind.DOOR),
            _opening("o2-window", 1.90, 1.00, 0.90, 2.10),
            # only a 0.20 m pier from o2, against a 0.45 m minimum
            _opening("o3-window", 3.10, 0.60, 0.90, 2.10),
            # stacked over o1 with a 0.30 m gap, against a 0.60 m minimum
            _opening("o4-vent", 0.10, 1.20, 2.40, 3.00),
        ],
    )


def test_check_openings_fires_every_table_4_check_once():
    rules = opening_limits(2, "D")
    violations = check_openings(_breached_wall(), rules)
    fired = sorted(set(v.check for v in violations))
    assert fired == ["b4_pier", "b5_corner", "h3_vertical_gap", "opening_ratio"]
    by_check = {}
    for violation in violations:
        by_check.setdefault(violation.check, []).append(violation)
    assert _close(by_check["b5_corner"][0].value, 0.10)
    assert by_check["b5_corner"][0].opening_ids == ("o1-door",)
    assert _close(by_check["b4_pier"][0].value, 0.20)
    assert by_check["b4_pier"][0].opening_ids == ("o2-window", "o3-window")
    assert _close(by_check["h3_vertical_gap"][0].value, 0.30)
    assert by_check["h3_vertical_gap"][0].opening_ids == ("o1-door", "o4-vent")
    assert all(v.clause_id == "IS4326:1993 Table 4" for v in violations)
    assert all(v.wall_id == "wall-breached" for v in violations)


def test_check_openings_measures_the_ratio_on_the_union_of_the_spans():
    rules = opening_limits(2, "D")
    violations = check_openings(_breached_wall(), rules)
    ratio = [v for v in violations if v.check == "opening_ratio"]
    assert len(ratio) == 1
    # o4 stacks over o1, so the union is 1.20 + 1.00 + 0.60 = 2.80 of 4.00 m.
    assert _close(ratio[0].value, 0.70)
    # Printed Table 4 row 2(b), the "D and E" column: 0.42 at two storeys.
    assert _close(ratio[0].limit, 0.42)
    assert ratio[0].units == "ratio"


def test_check_openings_reports_both_corners():
    violations = check_openings(_breached_wall(), opening_limits(2, "D"))
    corners = [v for v in violations if v.check == "b5_corner"]
    assert len(corners) == 2
    assert _close(corners[1].value, 4.0 - 3.70)
    assert corners[1].opening_ids == ("o3-window",)


def test_check_openings_skips_the_corner_rule_at_a_t_junction():
    violations = check_openings(_breached_wall(), opening_limits(2, "D"), corner_ends=(False, False))
    assert not [v for v in violations if v.check == "b5_corner"]
    # The other three checks are unaffected by the end condition.
    assert sorted(set(v.check for v in violations)) == ["b4_pier", "h3_vertical_gap", "opening_ratio"]


def test_check_openings_passes_a_compliant_wall():
    wall = WallLine(
        id="wall-clean",
        storey=0,
        a=(0.0, 0.0),
        b=(4.0, 0.0),
        thickness_m=0.23,
        openings=[_opening("d1", 1.60, 0.90, 0.0, 2.10, kind=OpeningKind.DOOR)],
    )
    assert check_openings(wall, opening_limits(2, "D")) == []
    # No openings at all is trivially compliant.
    wall.openings = []
    assert check_openings(wall, opening_limits(2, "E")) == []


def test_check_openings_skips_the_stack_rule_without_sill_and_head_data():
    wall = WallLine(
        id="wall-no-heights",
        storey=0,
        a=(0.0, 0.0),
        b=(6.0, 0.0),
        thickness_m=0.23,
        openings=[
            _opening("a1", 1.00, 1.00, None, None),
            _opening("a2", 1.00, 1.00, None, None),
        ],
    )
    assert not [v for v in check_openings(wall, opening_limits(2, "D")) if v.check == "h3_vertical_gap"]


def test_check_openings_refuses_a_zero_length_wall():
    wall = WallLine(id="wall-nil", storey=0, a=(0.0, 0.0), b=(0.0, 0.0), thickness_m=0.23)
    with pytest.raises(CodeInputError):
        check_openings(wall, opening_limits(2, "D"))


# ---------------------------------------------------------------------------
# IS 4326 Table 6 bands
# ---------------------------------------------------------------------------


def test_lintel_band_steps_up_with_span_and_category():
    assert lintel_band(4.5, "B").bar_dia_mm == 8
    assert lintel_band(4.5, "E").bar_dia_mm == 10
    assert lintel_band(6.0, "D").bar_dia_mm == 10
    spec = lintel_band(8.0, "E")
    assert (spec.bars_n, spec.bar_dia_mm) == (4, 12)
    # Four bars need two layers, so the band deepens from 75 to 150 mm.
    assert spec.depth_mm == 150
    assert lintel_band(5.0, "D").depth_mm == 75
    assert lintel_band(5.0, "D").link_dia_mm == 6
    assert lintel_band(5.0, "D").link_spacing_mm == 150
    assert lintel_band(5.0, "D").width_source == "wall_thickness"
    # Category A takes no band at all.
    assert lintel_band(5.0, "A") is None


def test_band_span_past_the_last_table_row_is_refused():
    with pytest.raises(CodeInputError):
        lintel_band(9.0, "D")
    with pytest.raises(CodeInputError):
        lintel_band(0.0, "D")


@pytest.mark.parametrize(
    "roof_type,roof_band_is_none,gable_band_is_none",
    [
        ("flat", True, True),
        ("gable", False, False),
        ("hip", False, True),
        ("shed", False, False),
    ],
)
def test_band_selection_matrix_across_the_four_roof_types(roof_type, roof_band_is_none, gable_band_is_none):
    roof = roof_band(5.0, "D", roof_type)
    assert (roof is None) is roof_band_is_none
    gable = gable_band("D", roof_type)
    assert (gable is None) is gable_band_is_none
    if gable is not None:
        assert gable.kind == "gable"
    if roof is not None:
        assert roof.kind == "roof"
    # The lintel band is there whatever the roof does.
    assert lintel_band(5.0, "D") is not None


def test_roof_band_returns_only_for_a_cast_in_situ_flat_slab():
    assert roof_band(5.0, "D", "flat") is None
    forced = roof_band(5.0, "D", "flat", cast_in_situ_slab=False)
    assert forced is not None
    assert "not a cast-in-situ slab" in forced.note
    assert roof_band(5.0, "A", "gable") is None
    with pytest.raises(CodeInputError):
        roof_band(5.0, "D", "barrel")


def test_plinth_band_is_mandatory_on_soft_soil_and_for_categories_d_and_e():
    assert plinth_band("B") is None
    assert plinth_band("C") is None
    assert plinth_band("D") is not None
    assert plinth_band("E") is not None
    soft = plinth_band("B", soft_soil=True)
    assert soft is not None
    assert "soft or filled soil" in soft.note
    # With no span the nominal two 8 mm bar band is used.
    assert (soft.bars_n, soft.bar_dia_mm, soft.depth_mm) == (2, 8, 75)
    # A span picks the Table 6 row instead.
    assert plinth_band("E", span_m=7.0).bar_dia_mm == 10
    assert plinth_band("A", soft_soil=True) is None


def test_gable_band_covers_gable_and_shed_but_never_hip():
    assert gable_band("D", "gable") is not None
    assert gable_band("D", "shed") is not None
    assert gable_band("D", "hip") is None
    assert gable_band("D", "flat") is None
    assert gable_band("A", "gable") is None
    assert "shed end wall" in gable_band("E", "shed").note


# ---------------------------------------------------------------------------
# IS 4326 Table 7 vertical steel
# ---------------------------------------------------------------------------


def test_vertical_bars_are_not_required_below_category_c():
    assert vertical_bars(3, 0, "A") is None
    assert vertical_bars(3, 0, "B") is None


def test_vertical_bar_lookups():
    # Printed IS 4326:1993 Table 7: category C is Nil below three storeys.
    assert vertical_bars(1, 0, "C") is None
    assert vertical_bars(2, 0, "C") is None
    assert vertical_bars(1, 0, "D").dia_mm == 10
    assert vertical_bars(1, 0, "E").dia_mm == 12
    # Two storeys, bottom then top: D is 12 over 10, E is 16 over 12.
    assert [vertical_bars(2, i, "D").dia_mm for i in (0, 1)] == [12, 10]
    assert [vertical_bars(2, i, "E").dia_mm for i in (0, 1)] == [16, 12]
    assert [vertical_bars(3, i, "C").dia_mm for i in (0, 1, 2)] == [12, 10, 10]
    assert [vertical_bars(3, i, "D").dia_mm for i in (0, 1, 2)] == [12, 12, 10]
    assert [vertical_bars(3, i, "E").dia_mm for i in (0, 1, 2)] == [16, 16, 12]


def test_vertical_bar_positions_are_zero_based_from_the_ground():
    assert [vertical_bars(3, i, "E").position for i in (0, 1, 2)] == ["bottom", "middle", "top"]
    assert vertical_bars(2, 0, "D").position == "bottom"
    assert vertical_bars(2, 1, "D").position == "top"
    assert vertical_bars(1, 0, "D").position == "bottom"


def test_vertical_bar_locations_add_the_jambs_at_category_d():
    assert vertical_bars(3, 0, "C").locations == ("corner", "junction")
    assert vertical_bars(3, 0, "D").locations == ("corner", "junction", "jamb")
    assert vertical_bars(3, 0, "E").locations == ("corner", "junction", "jamb")
    assert vertical_bars(3, 0, "E").bars_per_location == 1
    assert vertical_bars(3, 0, "E").steel_grade == "Fe415"


def test_vertical_bars_refuse_a_stack_the_table_does_not_cover():
    with pytest.raises(CodeInputError):
        vertical_bars(4, 0, "D")
    with pytest.raises(CodeInputError):
        vertical_bars(3, 3, "D")
    with pytest.raises(CodeInputError):
        vertical_bars(3, -1, "D")


# ---------------------------------------------------------------------------
# tracing
# ---------------------------------------------------------------------------


def test_the_compressive_chain_lands_in_the_trace_sink_in_order():
    entries = []
    with trace_into(entries):
        heff = effective_height(2.85, "full", "full")
        leff = effective_length(3.6, ("cross_wall", "cross_wall"))
        teff = effective_thickness(0.23)
        ratio = slenderness_ratio(heff, leff, teff)
        reduction = stress_reduction_factor(ratio, 0.0)
        fb = basic_compressive_stress(7.5, "M1")
        ka = area_reduction_factor(0.828)
        kp = shape_modification_factor()
        permissible_compressive_stress(fb, reduction.ks, ka, kp)
    assert [entry.clause_id for entry in entries] == [
        "IS1905:1987 Table 4",
        "IS1905:1987 Table 5",
        "IS1905:1987 Table 6",
        "IS1905:1987 Cl 4.6.1",
        "IS1905:1987 Table 9",
        "IS1905:1987 Table 8",
        "IS1905:1987 Cl 5.4.1.2",
        "IS1905:1987 Table 10",
        "IS1905:1987 Cl 5.4.1",
    ]
    assert entries[4].output["ks"] == pytest.approx(0.911196, rel=1e-5)
    assert entries[5].inputs == {"unit_strength_mpa": 7.5, "mortar_grade": "M1"}
    assert entries[-1].units == "MPa"


def test_the_is4326_callables_trace_too():
    entries = []
    with trace_into(entries):
        category = seismic_category("IV", 1.0)
        rules = opening_limits(2, category)
        check_openings(_breached_wall(), rules)
        lintel_band(5.0, category)
        roof_band(5.0, category, "flat")
        vertical_bars(2, 0, category)
    assert [entry.clause_id for entry in entries] == [
        "IS4326:1993 Table 1",
        "IS4326:1993 Table 4",
        "IS4326:1993 Cl 8.3",
        "IS4326:1993 Table 6 lintel",
        "IS4326:1993 Table 6 roof",
        "IS4326:1993 Table 7",
    ]
    assert entries[0].output == "D"
    # The exempted roof band is an explicit None in the trace, not a silence.
    assert entries[4].output is None
    assert isinstance(entries[2].output, list)
    assert entries[2].output[0]["check"] == "b5_corner"


# ---------------------------------------------------------------------------
# SP 20 style end to end vectors
# ---------------------------------------------------------------------------


def _load_vectors():
    with open(VECTORS, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _run_example(example):
    """The whole callable chain for one vector, returning the computed values."""
    geometry = example["geometry"]
    materials = example["materials"]
    loads = example["loads"]

    thickness = float(geometry["thickness_m"])
    heff = effective_height(geometry["clear_height_m"], geometry["top_restraint"], geometry["bottom_restraint"])
    ends = geometry["end_conditions"]
    leff = None if ends is None else effective_length(geometry["length_m"], ends)
    teff = effective_thickness(thickness)
    ratio = slenderness_ratio(heff, leff, teff)
    ok = check_max_slenderness(ratio, materials["storeys"], materials["mortar_grade"])
    fb = basic_compressive_stress(materials["unit_strength_mpa"], materials["mortar_grade"])
    reduction = stress_reduction_factor(ratio, loads["e_over_t"])
    ka = area_reduction_factor(geometry["loaded_area_m2"])
    kp = shape_modification_factor(geometry["unit_h_over_w"], materials["unit_strength_mpa"])
    fc = permissible_compressive_stress(fb, reduction.ks, ka, kp)
    fa = float(loads["axial_kn_per_m"]) / (1000.0 * thickness)

    computed = {
        "heff_m": heff,
        "leff_m": leff,
        "teff_m": teff,
        "slenderness_ratio": ratio,
        "slenderness_ok": ok,
        "fb_mpa": fb,
        "ks": reduction.ks,
        "ka": ka,
        "kp": kp,
        "fc_mpa": fc,
        "fa_mpa": fa,
        "utilization_compression": fa / fc,
        "fs_mpa": None,
        "tau_mpa": None,
        "utilization_shear": None,
    }
    if loads["dead_axial_kn_per_m"] is not None and loads["shear_kn"] is not None:
        fd = float(loads["dead_axial_kn_per_m"]) / (1000.0 * thickness)
        fs = permissible_shear(fd, materials["mortar_grade"])
        tau = float(loads["shear_kn"]) / (1000.0 * thickness * float(geometry["length_m"]))
        computed["fs_mpa"] = fs
        computed["tau_mpa"] = tau
        computed["utilization_shear"] = tau / fs
    return computed


def test_the_vector_file_is_labelled_for_print_verification():
    data = _load_vectors()
    assert data["source"]
    assert data["edition"]
    assert data["verify"] == "print"
    assert len(data["examples"]) == 3
    assert [e["id"] for e in data["examples"]] == ["sp20-w1", "sp20-w2", "sp20-w3"]
    for example in data["examples"]:
        assert example["verify"] == "print"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_sp20_wall_examples_end_to_end(index):
    example = _load_vectors()["examples"][index]
    computed = _run_example(example)
    expected = example["expected"]
    for key in sorted(expected):
        if key == "verdict":
            continue
        want = expected[key]
        got = computed[key]
        if want is None:
            assert got is None, example["id"] + " " + key + " should have no value"
        elif isinstance(want, bool):
            assert got is want, example["id"] + " " + key
        else:
            assert _close(got, want), example["id"] + " " + key + ": " + repr(got) + " vs " + repr(want)
    assert expected["verdict"] == "OK"
    assert computed["utilization_compression"] < 1.0
    if computed["utilization_shear"] is not None:
        assert computed["utilization_shear"] < 1.0


def test_the_small_pier_vector_is_the_one_that_loses_area_factor():
    examples = {e["id"]: e for e in _load_vectors()["examples"]}
    assert _run_example(examples["sp20-w1"])["ka"] == pytest.approx(1.0)
    assert _run_example(examples["sp20-w2"])["ka"] == pytest.approx(1.0)
    assert _run_example(examples["sp20-w3"])["ka"] == pytest.approx(0.907)
