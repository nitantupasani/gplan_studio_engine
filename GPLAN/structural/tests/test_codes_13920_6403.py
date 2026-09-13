"""Pins for the ductile detailing (IS 13920) and bearing capacity (IS 6403) clauses.

The bearing capacity factors are cross-checked against the published Vesic style
values that the geotechnical tools tabulate; everything else is pinned against a
hand computation written out in the test, never against the implementation.
"""

from __future__ import annotations

import math

import pytest

# Relative: see the note in test_model_roundtrip.py.
from ..codes import is13920 as ductile
from ..codes import is6403 as bearing
from ..codes.trace import CLAUSE_REGISTRY, trace_into

# ---------------------------------------------------------------------------
# IS 6403: bearing capacity factors
# ---------------------------------------------------------------------------

# phi -> (Nc, Nq, Ngamma), the geofound cross-check values.
PUBLISHED_FACTORS = (
    (0.0, 5.14, 1.00, 0.00),
    (10.0, 8.35, 2.47, 1.22),
    (20.0, 14.83, 6.40, 5.39),
    (30.0, 30.14, 18.40, 22.40),
    (35.0, 46.12, 33.30, 48.03),
)


@pytest.mark.parametrize("phi_deg,nc,nq,n_gamma", PUBLISHED_FACTORS)
def test_bearing_capacity_factors_match_the_published_values(phi_deg, nc, nq, n_gamma):
    factors = bearing.bearing_capacity_factors(phi_deg)
    assert factors.nc == pytest.approx(nc, rel=0.02)
    assert factors.nq == pytest.approx(nq, rel=0.02)
    if n_gamma == 0.0:
        assert factors.n_gamma == pytest.approx(0.0, abs=1e-9)
    else:
        assert factors.n_gamma == pytest.approx(n_gamma, rel=0.02)


def test_bearing_capacity_factors_are_continuous_through_phi_zero():
    just_above = bearing.bearing_capacity_factors(0.01)
    assert just_above.nc == pytest.approx(bearing.NC_PHI_ZERO, rel=0.01)
    assert just_above.nq == pytest.approx(1.0, rel=0.01)
    assert just_above.n_gamma == pytest.approx(0.0, abs=0.01)


def test_bearing_capacity_factors_grow_with_friction():
    values = [bearing.bearing_capacity_factors(float(phi)) for phi in range(0, 41, 5)]
    for lower, higher in zip(values, values[1:]):
        assert higher.nc > lower.nc
        assert higher.nq > lower.nq
        assert higher.n_gamma > lower.n_gamma


def test_bearing_capacity_factors_reject_impossible_friction():
    with pytest.raises(ValueError):
        bearing.bearing_capacity_factors(-1.0)
    with pytest.raises(ValueError):
        bearing.bearing_capacity_factors(60.0)


# ---------------------------------------------------------------------------
# IS 6403: shape, depth, inclination
# ---------------------------------------------------------------------------


def test_shape_factors_span_strip_to_square():
    strip = bearing.shape_factors(1.0, 100.0)
    assert strip.sc == pytest.approx(1.002)
    assert strip.s_gamma == pytest.approx(0.996)
    square = bearing.shape_factors(2.0, 2.0)
    assert (square.sc, square.sq, square.s_gamma) == pytest.approx((1.2, 1.2, 0.6))
    rectangle = bearing.shape_factors(2.0, 4.0)
    assert (rectangle.sc, rectangle.sq, rectangle.s_gamma) == pytest.approx((1.1, 1.1, 0.8))


def test_shape_factors_clamp_a_swapped_pair_to_the_square_values():
    assert bearing.shape_factors(4.0, 2.0) == bearing.shape_factors(2.0, 2.0)


def test_shape_factors_reject_a_zero_side():
    with pytest.raises(ValueError):
        bearing.shape_factors(0.0, 2.0)


def test_depth_factors_credit_nothing_frictional_below_ten_degrees():
    low = bearing.depth_factors(5.0, 1.5, 2.0)
    assert low.dq == 1.0 and low.d_gamma == 1.0
    assert low.dc > 1.0
    high = bearing.depth_factors(30.0, 1.5, 2.0)
    root_nphi = math.tan(math.radians(60.0))
    assert high.dc == pytest.approx(1.0 + 0.2 * 0.75 * root_nphi)
    assert high.dq == pytest.approx(1.0 + 0.1 * 0.75 * root_nphi)
    assert high.d_gamma == high.dq


def test_depth_factors_are_unity_at_the_surface():
    surface = bearing.depth_factors(30.0, 0.0, 2.0)
    assert (surface.dc, surface.dq, surface.d_gamma) == pytest.approx((1.0, 1.0, 1.0))


def test_inclination_factors_from_vertical_to_beyond_phi():
    vertical = bearing.inclination_factors(0.0, 30.0)
    assert (vertical.ic, vertical.iq, vertical.i_gamma) == pytest.approx((1.0, 1.0, 1.0))
    tilted = bearing.inclination_factors(10.0, 30.0)
    assert tilted.ic == pytest.approx((1.0 - 10.0 / 90.0) ** 2)
    assert tilted.i_gamma == pytest.approx((1.0 - 10.0 / 30.0) ** 2)
    exhausted = bearing.inclination_factors(40.0, 30.0)
    assert exhausted.i_gamma == 0.0
    assert exhausted.ic > 0.0
    cohesive = bearing.inclination_factors(10.0, 0.0)
    assert cohesive.i_gamma == 0.0


# ---------------------------------------------------------------------------
# IS 6403: water table and local shear
# ---------------------------------------------------------------------------


def test_water_table_factor_endpoints_and_ramp():
    assert bearing.water_table_factor(-0.5, 2.0) == 0.5
    assert bearing.water_table_factor(0.0, 2.0) == 0.5
    assert bearing.water_table_factor(1.0, 2.0) == pytest.approx(0.75)
    assert bearing.water_table_factor(2.0, 2.0) == 1.0
    assert bearing.water_table_factor(5.0, 2.0) == 1.0


def test_water_table_factor_needs_a_width():
    with pytest.raises(ValueError):
        bearing.water_table_factor(1.0, 0.0)


def test_local_shear_guard_kicks_in_below_twenty_eight_degrees():
    reduced = bearing.local_shear_guard(27.9, 15.0)
    assert reduced.applied is True
    assert reduced.c_kpa == pytest.approx(10.0)
    assert math.tan(math.radians(reduced.phi_deg)) == pytest.approx(
        (2.0 / 3.0) * math.tan(math.radians(27.9))
    )
    assert reduced.phi_in_deg == 27.9 and reduced.c_in_kpa == 15.0
    assert reduced.notes and "local shear" in reduced.notes[0]


def test_local_shear_guard_leaves_dense_soil_alone():
    kept = bearing.local_shear_guard(28.0, 15.0)
    assert kept.applied is False
    assert kept.phi_deg == 28.0 and kept.c_kpa == 15.0
    assert kept.notes == ()
    assert bearing.local_shear_guard(34.0, 0.0).applied is False


# ---------------------------------------------------------------------------
# IS 6403: assembly
# ---------------------------------------------------------------------------


def test_net_safe_bearing_assembles_the_chain_and_divides_by_the_factor_of_safety():
    result = bearing.net_safe_bearing(
        c_kpa=0.0, phi_deg=30.0, gamma_knm3=18.0, b_m=2.0, l_m=2.0, df_m=1.5
    )
    factors = bearing.bearing_capacity_factors(30.0)
    shape = bearing.shape_factors(2.0, 2.0)
    depth = bearing.depth_factors(30.0, 1.5, 2.0)
    surcharge = 18.0 * 1.5
    term_q = surcharge * (factors.nq - 1.0) * shape.sq * depth.dq
    term_gamma = 0.5 * 2.0 * 18.0 * factors.n_gamma * shape.s_gamma * depth.d_gamma
    assert result.term_cohesion_kpa == 0.0
    assert result.term_surcharge_kpa == pytest.approx(term_q)
    assert result.term_width_kpa == pytest.approx(term_gamma)
    assert result.q_net_ult_kpa == pytest.approx(term_q + term_gamma)
    assert result.fos == 2.5
    assert result.q_safe_net_kpa == pytest.approx(result.q_net_ult_kpa / 2.5)
    assert result.q_safe_gross_kpa == pytest.approx(result.q_safe_net_kpa + surcharge)
    assert result.local_shear_applied is False
    assert result.water_factor == 1.0
    assert any("no water table" in note for note in result.notes)


def test_net_safe_bearing_handles_a_water_table_above_the_founding_level():
    wet = bearing.net_safe_bearing(
        c_kpa=0.0, phi_deg=32.0, gamma_knm3=19.0, b_m=2.0, l_m=2.0, df_m=1.5, gwt_depth_m=0.5
    )
    dry = bearing.net_safe_bearing(
        c_kpa=0.0, phi_deg=32.0, gamma_knm3=19.0, b_m=2.0, l_m=2.0, df_m=1.5
    )
    assert wet.water_factor == 0.5
    assert wet.surcharge_eff_kpa == pytest.approx(19.0 * 0.5 + (19.0 - 9.81) * 1.0)
    assert wet.overburden_total_kpa == pytest.approx(19.0 * 1.5)
    assert wet.q_net_ult_kpa < dry.q_net_ult_kpa
    assert any("water table" in note for note in wet.notes)


def test_net_safe_bearing_on_soft_clay_runs_through_the_local_shear_guard():
    clay = bearing.net_safe_bearing(
        c_kpa=30.0, phi_deg=0.0, gamma_knm3=18.0, b_m=2.0, l_m=3.0, df_m=1.5
    )
    assert clay.local_shear_applied is True
    assert clay.c_used_kpa == pytest.approx(20.0)
    assert clay.term_width_kpa == pytest.approx(0.0)
    shape = bearing.shape_factors(2.0, 3.0)
    depth = bearing.depth_factors(0.0, 1.5, 2.0)
    assert clay.term_cohesion_kpa == pytest.approx(20.0 * bearing.NC_PHI_ZERO * shape.sc * depth.dc)
    assert any("local shear" in note for note in clay.notes)


def test_net_safe_bearing_rejects_impossible_geometry():
    with pytest.raises(ValueError):
        bearing.net_safe_bearing(c_kpa=0.0, phi_deg=30.0, gamma_knm3=18.0, b_m=0.0, l_m=2.0, df_m=1.0)
    with pytest.raises(ValueError):
        bearing.net_safe_bearing(c_kpa=0.0, phi_deg=30.0, gamma_knm3=18.0, b_m=2.0, l_m=2.0, df_m=-0.5)
    with pytest.raises(ValueError):
        bearing.net_safe_bearing(
            c_kpa=0.0, phi_deg=30.0, gamma_knm3=18.0, b_m=2.0, l_m=2.0, df_m=1.0, fos=0.9
        )


def test_net_safe_bearing_traces_every_clause_it_walks():
    entries = []
    with trace_into(entries):
        bearing.net_safe_bearing(
            c_kpa=10.0, phi_deg=25.0, gamma_knm3=18.0, b_m=2.0, l_m=2.0, df_m=1.5, gwt_depth_m=3.0
        )
    ids = [entry.clause_id for entry in entries]
    for ref in ("5.1.3", "Table 1", "Table 2", "Table 3", "Table 4", "5.1.1", "6.1"):
        assert bearing.CODE + " " + ref in ids
    assert ids[-1] == bearing.CODE + " 6.1"
    assert entries[-1].units == "kPa"
    assert entries[-1].output["local_shear_applied"] is True


# ---------------------------------------------------------------------------
# IS 13920: beams
# ---------------------------------------------------------------------------


def test_rho_min_matches_the_clause_for_m25_fe500():
    assert ductile.cl_6_2_1__rho_min(25.0, 500.0) == pytest.approx(0.0024)
    assert ductile.cl_6_2_1__rho_min(20.0, 415.0) == pytest.approx(0.24 * math.sqrt(20.0) / 415.0)
    assert ductile.cl_6_2_1__rho_min(30.0, 500.0) > ductile.cl_6_2_1__rho_min(25.0, 500.0)


def test_rho_min_rejects_nonsense_materials():
    with pytest.raises(ValueError):
        ductile.cl_6_2_1__rho_min(0.0, 500.0)
    with pytest.raises(ValueError):
        ductile.cl_6_2_1__rho_min(25.0, 0.0)


def test_rho_max_and_the_bars_that_run_through():
    assert ductile.cl_6_2_2__rho_max() == 0.025
    assert ductile.cl_6_2_1__min_bars_each_face() == 2


def test_beam_geometry_passes_a_conforming_section():
    check = ductile.cl_6_1__beam_geometry(230.0, 450.0, 4000.0)
    assert check.ok is True
    assert check.width_over_depth == pytest.approx(230.0 / 450.0)
    assert check.max_depth_mm == pytest.approx(1000.0)
    assert check.notes == ()


def test_beam_geometry_flags_narrow_shallow_and_stubby_sections():
    narrow = ductile.cl_6_1__beam_geometry(150.0, 450.0, 4000.0)
    assert narrow.ok is False and narrow.width_ok is False and narrow.aspect_ok is True
    stubby = ductile.cl_6_1__beam_geometry(230.0, 900.0, 3000.0)
    assert stubby.depth_ok is False and stubby.aspect_ok is False
    assert stubby.max_depth_mm == pytest.approx(750.0)
    assert len(stubby.notes) == 2


def test_joint_sagging_is_half_the_hogging_capacity_at_the_face():
    assert ductile.cl_6_2_3__joint_sagging(180e6) == pytest.approx(90e6)
    assert ductile.cl_6_2_4__span_capacity_floor(180e6) == pytest.approx(45e6)
    with pytest.raises(ValueError):
        ductile.cl_6_2_3__joint_sagging(-1.0)


def test_capacity_shear_covers_both_sway_directions():
    # Vg 120 kN, hogging 150 kNm, sagging 120 kNm, clear span 4 m.
    # sway term = 1.4 x (150 + 120) / 4 = 94.5 kN.
    shear = ductile.cl_6_3_3__capacity_shear(120e3, 150e6, 120e6, 4000.0)
    assert shear.sway_term_n == pytest.approx(94.5e3)
    assert shear.v_sway_right_n == pytest.approx(214.5e3)
    assert shear.v_sway_left_n == pytest.approx(25.5e3)
    assert shear.v_design_n == pytest.approx(214.5e3)
    assert shear.governs == "sway_right"


def test_capacity_shear_governs_on_the_other_sway_when_gravity_reverses():
    shear = ductile.cl_6_3_3__capacity_shear(-120e3, 150e6, 120e6, 4000.0)
    assert shear.v_sway_left_n == pytest.approx(-214.5e3)
    assert shear.v_design_n == pytest.approx(214.5e3)
    assert shear.governs == "sway_left"


def test_capacity_shear_rejects_a_zero_span_or_a_signed_capacity():
    with pytest.raises(ValueError):
        ductile.cl_6_3_3__capacity_shear(100e3, 150e6, 120e6, 0.0)
    with pytest.raises(ValueError):
        ductile.cl_6_3_3__capacity_shear(100e3, -150e6, 120e6, 4000.0)


def test_hoop_zones_take_the_tighter_of_the_two_spacing_bounds():
    hoops = ductile.cl_6_3_5__hoop_zones(400.0, 16.0)
    assert hoops.end_zone_mm == pytest.approx(800.0)
    assert hoops.limit_depth_mm == pytest.approx(100.0)
    assert hoops.limit_bar_mm == pytest.approx(128.0)
    assert hoops.spacing_end_mm == pytest.approx(100.0)
    assert hoops.spacing_mid_mm == pytest.approx(200.0)
    assert hoops.first_hoop_mm == 50.0
    assert hoops.min_dia_mm == 8.0
    assert hoops.floor_applied is False


def test_hoop_spacing_never_falls_below_the_hundred_millimetre_floor():
    hoops = ductile.cl_6_3_5__hoop_zones(300.0, 10.0)
    assert min(hoops.limit_depth_mm, hoops.limit_bar_mm) == pytest.approx(75.0)
    assert hoops.spacing_end_mm == pytest.approx(100.0)
    assert hoops.floor_applied is True
    assert hoops.notes


def test_hoop_diameter_steps_up_on_a_long_clear_span():
    assert ductile.cl_6_3_5__hoop_zones(400.0, 16.0, 4500.0).min_dia_mm == 8.0
    long_span = ductile.cl_6_3_5__hoop_zones(400.0, 16.0, 6000.0)
    assert long_span.min_dia_mm == 10.0
    assert any("diameter" in note for note in long_span.notes)


# ---------------------------------------------------------------------------
# IS 13920: columns
# ---------------------------------------------------------------------------


def test_column_geometry_requires_twenty_beam_bar_diameters_and_three_hundred():
    small = ductile.cl_7_1__column_geometry(300.0, 300.0, 20.0)
    assert small.required_min_dim_mm == pytest.approx(400.0)
    assert small.min_dim_ok is False and small.ok is False
    ok = ductile.cl_7_1__column_geometry(450.0, 450.0, 20.0)
    assert ok.ok is True and ok.aspect_ratio == pytest.approx(1.0)
    fine_bars = ductile.cl_7_1__column_geometry(300.0, 300.0, 12.0)
    assert fine_bars.required_min_dim_mm == pytest.approx(300.0)
    assert fine_bars.ok is True


def test_column_geometry_flags_a_slender_side_ratio():
    slender = ductile.cl_7_1__column_geometry(230.0, 600.0, 12.0)
    assert slender.aspect_ratio == pytest.approx(230.0 / 600.0)
    assert slender.aspect_ok is False
    assert slender.min_dim_ok is False
    assert len(slender.notes) == 2


def test_strong_column_ratio_is_reported_never_resized():
    passing = ductile.cl_7_2_1__strong_column_ratio(300e6, 200e6)
    assert passing.ratio == pytest.approx(1.5)
    assert passing.required == 1.4 and passing.ok is True and passing.flag_only is True
    failing = ductile.cl_7_2_1__strong_column_ratio(200e6, 200e6)
    assert failing.ok is False and failing.flag_only is True and failing.notes
    vacuous = ductile.cl_7_2_1__strong_column_ratio(200e6, 0.0)
    assert vacuous.applicable is False and vacuous.ok is True and vacuous.notes


def test_confining_length_is_the_maximum_of_the_three_rules():
    # clear height governs: 3000 / 6 = 500.
    assert ductile.cl_7_6_1__confining_length(300.0, 3000.0) == pytest.approx(500.0)
    # column depth governs.
    assert ductile.cl_7_6_1__confining_length(600.0, 3000.0) == pytest.approx(600.0)
    # the 450 mm floor governs.
    assert ductile.cl_7_6_1__confining_length(250.0, 2400.0) == pytest.approx(450.0)
    with pytest.raises(ValueError):
        ductile.cl_7_6_1__confining_length(0.0, 3000.0)


def test_confining_spacing_bounds_and_floor():
    least = ductile.cl_7_6_2__confining_spacing(300.0, 16.0)
    assert least.limit_min_dim_mm == pytest.approx(75.0)
    assert least.limit_bar_mm == pytest.approx(96.0)
    assert least.spacing_mm == pytest.approx(75.0)
    assert least.governs == "least_dimension"
    assert least.floor_applied is False
    capped = ductile.cl_7_6_2__confining_spacing(500.0, 25.0)
    assert capped.spacing_mm == pytest.approx(100.0)
    assert capped.governs == "cap_100"
    floored = ductile.cl_7_6_2__confining_spacing(230.0, 12.0)
    assert floored.spacing_mm == pytest.approx(75.0)
    assert floored.floor_applied is True
    assert floored.governs == "floor_75"


def test_ash_rectangular_area_ratio_branch():
    # 300 x 300 column, 220 mm core: s 100, h 220, M25, Fe415.
    ash = ductile.cl_7_6_3__ash_rectangular(100.0, 220.0, 25.0, 415.0, 90000.0, 48400.0)
    assert ash.ash_area_ratio_mm2 == pytest.approx(205.04, rel=1e-3)
    assert ash.ash_floor_mm2 == pytest.approx(66.27, rel=1e-3)
    assert ash.ash_mm2 == ash.ash_area_ratio_mm2
    assert ash.governs == "area_ratio"
    assert ash.crossties_required is False


def test_ash_rectangular_floor_branch_on_a_large_core():
    # 800 x 800 column, 720 mm core: the area ratio term falls under the floor.
    ash = ductile.cl_7_6_3__ash_rectangular(100.0, 300.0, 25.0, 415.0, 640000.0, 518400.0)
    assert ash.ash_area_ratio_mm2 == pytest.approx(76.31, rel=1e-3)
    assert ash.ash_floor_mm2 == pytest.approx(90.36, rel=1e-3)
    assert ash.ash_mm2 == ash.ash_floor_mm2
    assert ash.governs == "floor"
    assert any("floor" in note for note in ash.notes)


def test_ash_rectangular_calls_for_crossties_past_a_three_hundred_leg():
    ash = ductile.cl_7_6_3__ash_rectangular(100.0, 340.0, 25.0, 415.0, 640000.0, 518400.0)
    assert ash.crossties_required is True
    assert any("crossties" in note for note in ash.notes)


def test_ash_rectangular_rejects_a_zero_core():
    with pytest.raises(ValueError):
        ductile.cl_7_6_3__ash_rectangular(100.0, 220.0, 25.0, 415.0, 90000.0, 0.0)


def test_joint_check_is_flagged_not_designed():
    joint = ductile.cl_9__joint_check()
    assert joint.designed is False
    assert joint.marker == "FLAGGED_NOT_DESIGNED"
    assert joint.referral == "joint_check_manual"
    assert joint.notes


# ---------------------------------------------------------------------------
# IS 13920: applicability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "zone,frame,expected",
    [
        ("I", "SMRF", True),
        ("II", "SMRF", True),
        ("III", "SMRF", True),
        ("IV", "SMRF", True),
        ("V", "SMRF", True),
        ("I", "OMRF", False),
        ("II", "OMRF", False),
        ("III", "OMRF", True),
        ("IV", "OMRF", True),
        ("V", "OMRF", True),
    ],
)
def test_applicability_matrix(zone, frame, expected):
    assert ductile.is13920_applies(zone, frame) is expected


def test_applicability_accepts_the_spellings_the_api_sends():
    assert ductile.is13920_applies("iii", "omrf") is True
    assert ductile.is13920_applies(3, "OMRF") is True
    assert ductile.is13920_applies("2", "smrf") is True
    assert ductile.is13920_applies(" II ", " OMRF ") is False


def test_applicability_rejects_an_unknown_zone_or_frame():
    with pytest.raises(ValueError):
        ductile.is13920_applies("VI", "OMRF")
    with pytest.raises(ValueError):
        ductile.is13920_applies("III", "ductile")


# ---------------------------------------------------------------------------
# data table and registry hygiene
# ---------------------------------------------------------------------------


def test_the_edition_table_carries_its_source_and_print_flags():
    assert ductile.EDITION == "2016"
    assert "IS 13920:2016" in ductile.SOURCE
    assert ductile.VERIFY_IN_PRINT
    table = ductile._TABLE
    assert table["schema_version"] == 1
    assert all(value == "print" for value in table["verify"].values())
    for path in ductile.VERIFY_IN_PRINT:
        assert ductile._get(path) is not None


def test_a_missing_table_key_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        ductile._get("beam.no_such_key")


def test_every_clause_in_both_modules_is_registered_once():
    ductile_ids = sorted(key for key in CLAUSE_REGISTRY if key.startswith(ductile.CODE + " "))
    bearing_ids = sorted(key for key in CLAUSE_REGISTRY if key.startswith(bearing.CODE + " "))
    assert len(set(ductile_ids)) == len(ductile_ids) == 15
    assert len(set(bearing_ids)) == len(bearing_ids) == 7
    assert ductile.CODE + " 6.3.3" in ductile_ids
    assert bearing.CODE + " Table 1" in bearing_ids
    for key in ductile_ids + bearing_ids:
        meta = CLAUSE_REGISTRY[key]
        assert meta.title and meta.func


def test_the_spec_aliases_point_at_the_clause_numbered_callables():
    assert ductile.cl_7_6__confining is ductile.cl_7_6_3__ash_rectangular
    assert ductile.cl_7_6__lo is ductile.cl_7_6_1__confining_length
    assert ductile.cl_7_6__spacing is ductile.cl_7_6_2__confining_spacing


def test_ductile_callables_trace_their_inputs_and_outputs():
    entries = []
    with trace_into(entries):
        ductile.cl_6_2_1__rho_min(25.0, 500.0)
        ductile.cl_7_6_3__ash_rectangular(100.0, 220.0, 25.0, 415.0, 90000.0, 48400.0)
        ductile.is13920_applies("III", "OMRF")
    assert [entry.clause_id for entry in entries] == [
        ductile.CODE + " 6.2.1",
        ductile.CODE + " 7.6.3",
        ductile.CODE + " 1.1.1",
    ]
    assert entries[0].inputs == {"fck_mpa": 25.0, "fy_mpa": 500.0}
    assert entries[0].output == pytest.approx(0.0024)
    assert entries[1].output["governs"] == "area_ratio"
    assert entries[2].output is True
