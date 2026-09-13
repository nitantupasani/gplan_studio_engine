"""Pins for codes/is456.py: classic IS 456 vectors, table provenance, trace coverage.

The numbers below are the ones an engineer checks a new implementation against:
the limiting neutral axis depths, the 0.138 Mu,lim coefficient, the SP 16 style
singly reinforced case, Table 19 spot values against the closed form, 47 bar
diameters of development length, e_min, and the biaxial exponent ladder.
"""

from __future__ import annotations

import math

import pytest

# Relative: see the note in test_model_roundtrip.py.
from ..codes import is456
from ..codes.trace import CLAUSE_REGISTRY, trace_into
from ..data._loader import load_yaml

TABLES = load_yaml("is456_tables")
FIGS = load_yaml("is456_figs")


# ---------------------------------------------------------------------------
# materials and general
# ---------------------------------------------------------------------------


def test_ec_is_5000_root_fck():
    assert is456.cl_6_2_3_1__ec(25.0) == pytest.approx(25000.0)
    assert is456.cl_6_2_3_1__ec(20.0) == pytest.approx(5000.0 * math.sqrt(20.0))
    with pytest.raises(ValueError):
        is456.cl_6_2_3_1__ec(0.0)


def test_table_5_and_table_16_exposure_ladders():
    assert is456.table_5__min_grade("mild") == 20.0
    assert is456.table_5__min_grade("very_severe") == 35.0
    assert is456.table_16__nominal_cover("mild") == 20.0
    assert is456.table_16__nominal_cover("moderate") == 30.0
    assert is456.table_16__nominal_cover("severe") == 45.0
    assert is456.table_16__nominal_cover("very severe") == 50.0
    assert is456.table_16__nominal_cover("extreme") == 75.0
    with pytest.raises(ValueError):
        is456.table_16__nominal_cover("tropical")


def test_fire_cover_steps_up_to_the_next_tabulated_rating():
    assert is456.table_16a__fire_cover("beam", 1.0) == 20.0
    assert is456.table_16a__fire_cover("beam_simply_supported", 2.0) == 40.0
    assert is456.table_16a__fire_cover("beam_continuous", 2.0) == 30.0
    # 1.2 h is not tabulated: it takes the 1.5 h row, never the 1.0 h row.
    assert is456.table_16a__fire_cover("slab_simply_supported", 1.2) == 25.0
    assert is456.table_16a__fire_cover("column", 4.0) == 40.0
    assert is456.cl_26_4_2_2__footing_cover() == 50.0


# ---------------------------------------------------------------------------
# flexure, Annex G
# ---------------------------------------------------------------------------


def test_xu_max_over_d_reproduces_the_published_trio():
    assert is456.annex_g__xu_max_over_d(250.0) == pytest.approx(0.53, abs=0.005)
    assert is456.annex_g__xu_max_over_d(415.0) == pytest.approx(0.48, abs=0.005)
    assert is456.annex_g__xu_max_over_d(500.0) == pytest.approx(0.46, abs=0.005)
    assert is456.annex_g__xu_max_over_d(550.0) == pytest.approx(0.44, abs=0.005)
    # Monotone: a stronger steel yields later, so the limiting axis rises higher.
    ratios = [is456.annex_g__xu_max_over_d(fy) for fy in (250.0, 415.0, 500.0, 550.0)]
    assert ratios == sorted(ratios, reverse=True)


def test_mu_lim_matches_the_0_138_coefficient_for_m20_fe415():
    b_mm, d_mm, fck_mpa = 230.0, 415.0, 20.0
    mu_lim = is456.annex_g__mu_lim(b_mm, d_mm, fck_mpa, 415.0)
    expected = 0.138 * fck_mpa * b_mm * d_mm * d_mm
    assert mu_lim == pytest.approx(expected, rel=0.005)
    # The same coefficient falls out per unit section.
    assert is456.annex_g__mu_lim(1.0, 1.0, 1.0, 415.0) == pytest.approx(0.138, rel=0.005)
    assert is456.annex_g__mu_lim(1.0, 1.0, 1.0, 500.0) == pytest.approx(0.133, rel=0.01)
    assert is456.annex_g__mu_lim(1.0, 1.0, 1.0, 250.0) == pytest.approx(0.148, rel=0.01)


def test_singly_reinforced_sp16_style_case():
    b_mm, d_mm, fck_mpa, fy_mpa = 230.0, 415.0, 20.0, 415.0
    mu_nmm = 100.0e6
    assert mu_nmm < is456.annex_g__mu_lim(b_mm, d_mm, fck_mpa, fy_mpa)

    ast = is456.annex_g__ast_singly(mu_nmm, b_mm, d_mm, fck_mpa, fy_mpa)
    expected = (
        0.5
        * (fck_mpa / fy_mpa)
        * (1.0 - math.sqrt(1.0 - 4.6 * mu_nmm / (fck_mpa * b_mm * d_mm * d_mm)))
        * b_mm
        * d_mm
    )
    assert ast == pytest.approx(expected, rel=1e-12)
    assert 780.0 < ast < 840.0

    # Independent check: put the answer back into the Annex G moment expression.
    # It returns Mu to 0.05 percent (the closed form rounds 4/0.87 to 4.6).
    recovered = 0.87 * fy_mpa * ast * d_mm * (1.0 - ast * fy_mpa / (b_mm * d_mm * fck_mpa))
    assert recovered == pytest.approx(mu_nmm, rel=2e-3)


def test_singly_refuses_a_demand_past_the_closed_form_range():
    with pytest.raises(ValueError):
        is456.annex_g__ast_singly(400.0e6, 230.0, 415.0, 20.0, 415.0)


def test_sp16_table_f_fsc_grid_and_interpolation():
    assert is456.sp16_table_f__fsc(415.0, 0.05) == pytest.approx(355.0)
    assert is456.sp16_table_f__fsc(415.0, 0.10) == pytest.approx(353.0)
    assert is456.sp16_table_f__fsc(415.0, 0.15) == pytest.approx(342.0)
    assert is456.sp16_table_f__fsc(415.0, 0.20) == pytest.approx(329.0)
    assert is456.sp16_table_f__fsc(500.0, 0.10) == pytest.approx(412.0)
    assert is456.sp16_table_f__fsc(250.0, 0.20) == pytest.approx(217.0)
    # Midpoint of the 0.15 to 0.20 step for Fe415.
    assert is456.sp16_table_f__fsc(415.0, 0.175) == pytest.approx(0.5 * (342.0 + 329.0))
    # Flat outside the tabulated d'/d range.
    assert is456.sp16_table_f__fsc(415.0, 0.01) == pytest.approx(355.0)
    assert is456.sp16_table_f__fsc(415.0, 0.40) == pytest.approx(329.0)
    # Never above the design yield stress.
    assert is456.sp16_table_f__fsc(415.0, 0.05) < 0.87 * 415.0


def test_doubly_reinforced_splits_and_reassembles():
    b_mm, d_mm, dprime_mm, fck_mpa, fy_mpa = 230.0, 415.0, 50.0, 20.0, 415.0
    mu_lim = is456.annex_g__mu_lim(b_mm, d_mm, fck_mpa, fy_mpa)
    mu_nmm = 1.4 * mu_lim
    out = is456.annex_g__doubly(mu_nmm, b_mm, d_mm, dprime_mm, fck_mpa, fy_mpa)

    assert out.mu_lim_nmm == pytest.approx(mu_lim)
    assert out.asc_mm2 > 0.0 and out.ast2_mm2 > 0.0
    # Compression couple carries exactly the excess moment.
    net = out.fsc_mpa - is456.CONCRETE_DESIGN_FACTOR * fck_mpa
    mu2 = out.asc_mm2 * net * (d_mm - dprime_mm)
    assert mu_lim + mu2 == pytest.approx(mu_nmm, rel=1e-12)
    # Tension part 2 balances the compression couple.
    assert out.ast2_mm2 * 0.87 * fy_mpa == pytest.approx(out.asc_mm2 * net, rel=1e-12)
    # Balanced part carries Mu,lim on the limiting lever arm.
    ratio = is456.annex_g__xu_max_over_d(fy_mpa)
    assert out.ast1_mm2 * 0.87 * fy_mpa * (d_mm - 0.42 * ratio * d_mm) == pytest.approx(mu_lim, rel=1e-12)
    # More demand needs more of both.
    heavier = is456.annex_g__doubly(1.8 * mu_lim, b_mm, d_mm, dprime_mm, fck_mpa, fy_mpa)
    assert heavier.asc_mm2 > out.asc_mm2
    assert heavier.ast1_mm2 + heavier.ast2_mm2 > out.ast1_mm2 + out.ast2_mm2


def test_doubly_below_mu_lim_degenerates_to_a_singly_reinforced_section():
    out = is456.annex_g__doubly(60.0e6, 230.0, 415.0, 50.0, 20.0, 415.0)
    assert out.ast2_mm2 == 0.0
    assert out.asc_mm2 == 0.0
    assert out.ast1_mm2 > 0.0
    with pytest.raises(ValueError):
        is456.annex_g__doubly(60.0e6, 230.0, 40.0, 50.0, 20.0, 415.0)


# ---------------------------------------------------------------------------
# shear, Clause 40
# ---------------------------------------------------------------------------


def test_tau_v_is_vu_over_bd():
    assert is456.cl_40_1__tau_v(100.0e3, 230.0, 415.0) == pytest.approx(100.0e3 / (230.0 * 415.0))
    with pytest.raises(ValueError):
        is456.cl_40_1__tau_v(100.0e3, 0.0, 415.0)


def test_table_19_closed_form_hits_the_classic_spot_values():
    assert is456.table_19__tau_c(0.75, 25.0) == pytest.approx(0.57, rel=0.02)
    assert is456.table_19__tau_c(0.25, 20.0) == pytest.approx(0.36, rel=0.03)
    assert is456.table_19__tau_c(1.00, 25.0) == pytest.approx(0.64, rel=0.02)
    assert is456.table_19__tau_c(2.00, 20.0) == pytest.approx(0.79, rel=0.02)
    assert is456.table_19__tau_c(3.00, 40.0) == pytest.approx(1.01, rel=0.02)


def test_table_19_closed_form_tracks_the_printed_grid_within_three_percent():
    block = TABLES["table_19_tau_c"]
    worst = 0.0
    for grade, row in sorted(block["grades"].items()):
        for pt, printed in zip(block["pt"], row):
            computed = is456.table_19__tau_c(float(pt), float(grade))
            worst = max(worst, abs(computed - printed) / printed)
            assert computed == pytest.approx(printed, rel=0.03), (grade, pt)
    assert worst < 0.03


def test_table_19_clamps_pt_and_fck_at_the_printed_edges():
    assert is456.table_19__tau_c(0.05, 25.0) == is456.table_19__tau_c(0.15, 25.0)
    assert is456.table_19__tau_c(5.00, 25.0) == is456.table_19__tau_c(3.00, 25.0)
    assert is456.table_19__tau_c(1.00, 60.0) == is456.table_19__tau_c(1.00, 40.0)
    # More tension steel is never weaker.
    values = [is456.table_19__tau_c(pt, 25.0) for pt in (0.15, 0.5, 1.0, 2.0, 3.0)]
    assert values == sorted(values)


def test_table_20_caps():
    assert is456.table_20__tau_c_max(20.0) == 2.8
    assert is456.table_20__tau_c_max(25.0) == 3.1
    assert is456.table_20__tau_c_max(30.0) == 3.5
    assert is456.table_20__tau_c_max(35.0) == 3.7
    assert is456.table_20__tau_c_max(40.0) == 4.0
    assert is456.table_20__tau_c_max(60.0) == 4.0
    # A non-standard grade steps DOWN to the tabulated grade below it.
    assert is456.table_20__tau_c_max(22.0) == 2.8
    # The cap always sits above the Table 19 strength.
    assert is456.table_20__tau_c_max(25.0) > is456.table_19__tau_c(3.0, 25.0)


def test_k_solid_slab_steps_from_1_30_to_1_00():
    assert is456.cl_40_2_1_1__k_solid_slab(150.0) == pytest.approx(1.30)
    assert is456.cl_40_2_1_1__k_solid_slab(100.0) == pytest.approx(1.30)
    assert is456.cl_40_2_1_1__k_solid_slab(200.0) == pytest.approx(1.20)
    assert is456.cl_40_2_1_1__k_solid_slab(250.0) == pytest.approx(1.10)
    assert is456.cl_40_2_1_1__k_solid_slab(300.0) == pytest.approx(1.00)
    assert is456.cl_40_2_1_1__k_solid_slab(450.0) == pytest.approx(1.00)


def test_stirrup_rules():
    asv_over_sv = is456.cl_40_4__vertical_stirrups(50.0e3, 415.0, 415.0)
    assert asv_over_sv == pytest.approx(50.0e3 / (0.87 * 415.0 * 415.0))
    # A 2 legged 8 mm stirrup at that rate lands on a sane spacing.
    spacing = 2.0 * (math.pi / 4.0) * 8.0 * 8.0 / asv_over_sv
    assert 100.0 < spacing < 400.0
    # Negative Vus asks for nothing, never for negative steel.
    assert is456.cl_40_4__vertical_stirrups(-10.0e3, 415.0, 415.0) == 0.0

    assert is456.cl_26_5_1_6__min_stirrups(230.0, 415.0) == pytest.approx(0.4 * 230.0 / (0.87 * 415.0))
    # fy above 415 is capped by the clause, so Fe500 gets the Fe415 minimum.
    assert is456.cl_26_5_1_6__min_stirrups(230.0, 500.0) == is456.cl_26_5_1_6__min_stirrups(230.0, 415.0)

    assert is456.cl_26_5_1_5__max_stirrup_spacing(415.0) == pytest.approx(300.0)
    assert is456.cl_26_5_1_5__max_stirrup_spacing(300.0) == pytest.approx(225.0)


# ---------------------------------------------------------------------------
# torsion, Clause 41
# ---------------------------------------------------------------------------


def test_equivalent_shear_and_moment():
    assert is456.cl_41_3_1__equiv_shear(100.0e3, 20.0e6, 230.0) == pytest.approx(100.0e3 + 1.6 * 20.0e6 / 230.0)

    out = is456.cl_41_4_2__equiv_moment(100.0e6, 20.0e6, 230.0, 450.0)
    mt = 20.0e6 * (1.0 + 450.0 / 230.0) / 1.7
    assert out.mt_nmm == pytest.approx(mt)
    assert out.me1_nmm == pytest.approx(100.0e6 + mt)
    # Mt below Mu leaves no moment on the opposite face.
    assert out.me2_nmm == 0.0

    big = is456.cl_41_4_2__equiv_moment(5.0e6, 20.0e6, 230.0, 450.0)
    assert big.me2_nmm == pytest.approx(big.mt_nmm - 5.0e6)


def test_torsion_transverse_steel_takes_the_greater_of_the_two_rules():
    plain = is456.cl_41_4_3__transverse(20.0e6, 100.0e3, 170.0, 390.0, 415.0, 150.0)
    assert plain.asv_floor_mm2 == 0.0
    assert plain.asv_req_mm2 == pytest.approx(plain.asv_mm2)

    floored = is456.cl_41_4_3__transverse(
        1.0e6, 10.0e3, 170.0, 390.0, 415.0, 150.0, b_mm=230.0, tau_ve_mpa=1.4, tau_c_mpa=0.5
    )
    assert floored.asv_floor_mm2 == pytest.approx(0.9 * 230.0 * 150.0 / (0.87 * 415.0))
    assert floored.asv_req_mm2 == pytest.approx(floored.asv_floor_mm2)
    assert floored.asv_req_mm2 > floored.asv_mm2


# ---------------------------------------------------------------------------
# serviceability, Clause 23.2.1
# ---------------------------------------------------------------------------


def test_basic_span_depth_and_long_span_factor():
    assert is456.cl_23_2_1__basic_ld("cantilever") == 7.0
    assert is456.cl_23_2_1__basic_ld("simply_supported") == 20.0
    assert is456.cl_23_2_1__basic_ld("ss") == 20.0
    assert is456.cl_23_2_1__basic_ld("continuous") == 26.0
    with pytest.raises(ValueError):
        is456.cl_23_2_1__basic_ld("propped")

    assert is456.cl_23_2_1_c__long_span_factor(8.0) == 1.0
    assert is456.cl_23_2_1_c__long_span_factor(10.0) == 1.0
    assert is456.cl_23_2_1_c__long_span_factor(12.5) == pytest.approx(0.8)


def test_service_stress_and_fig_4_modification_factor():
    # Fe415 fully stressed at service.
    assert is456.cl_23_2_1__fs(415.0, 1000.0, 1000.0) == pytest.approx(240.7)
    assert is456.cl_23_2_1__fs(500.0, 1000.0, 1000.0) == pytest.approx(290.0)
    # Providing more steel than required drops the service stress.
    assert is456.cl_23_2_1__fs(415.0, 800.0, 1000.0) < is456.cl_23_2_1__fs(415.0, 1000.0, 1000.0)

    # The chart pin: 1 percent steel at fs 240 gives a factor of 1.0.
    assert is456.fig_4__mf_tension(240.0, 1.0) == pytest.approx(1.0, abs=0.02)
    # Lightly reinforced slabs get a big factor, and it is capped at 2.0.
    assert is456.fig_4__mf_tension(240.0, 0.30) == pytest.approx(1.49, abs=0.03)
    assert is456.fig_4__mf_tension(145.0, 0.20) == pytest.approx(2.0)
    assert is456.fig_4__mf_tension(120.0, 0.10) == pytest.approx(2.0)
    # Monotone: more steel means a smaller factor, a higher stress means a smaller factor.
    row = [is456.fig_4__mf_tension(240.0, pt) for pt in (0.2, 0.5, 1.0, 2.0, 3.0)]
    assert row == sorted(row, reverse=True)
    column = [is456.fig_4__mf_tension(fs, 1.0) for fs in (120.0, 190.0, 240.0, 290.0)]
    assert column == sorted(column, reverse=True)
    # Never outside the plotted range, including off the axes.
    for fs in (60.0, 120.0, 240.0, 400.0):
        for pt in (0.01, 1.0, 6.0):
            assert 0.80 <= is456.fig_4__mf_tension(fs, pt) <= 2.00
    # Bilinear midpoint between two tabulated curves.
    mid = is456.fig_4__mf_tension(0.5 * (215.0 + 240.0), 1.0)
    assert mid == pytest.approx(0.5 * (is456.fig_4__mf_tension(215.0, 1.0) + is456.fig_4__mf_tension(240.0, 1.0)))


def test_fig_5_and_fig_6_grids():
    assert is456.fig_5__mf_compression(0.0) == pytest.approx(1.0)
    assert is456.fig_5__mf_compression(3.0) == pytest.approx(1.5)
    assert is456.fig_5__mf_compression(5.0) == pytest.approx(1.5)
    values = [is456.fig_5__mf_compression(pc) for pc in (0.0, 0.5, 1.0, 2.0, 3.0)]
    assert values == sorted(values)

    assert is456.fig_6__mf_flanged(1.0) == pytest.approx(1.0)
    assert is456.fig_6__mf_flanged(0.30) == pytest.approx(0.80)
    assert is456.fig_6__mf_flanged(0.10) == pytest.approx(0.80)
    assert 0.80 <= is456.fig_6__mf_flanged(0.55) <= 1.0


# ---------------------------------------------------------------------------
# detailing, Clause 26
# ---------------------------------------------------------------------------


def test_min_and_max_beam_steel():
    assert is456.cl_26_5_1_1__min_tension_steel(230.0, 415.0, 415.0) == pytest.approx(0.85 * 230.0 * 415.0 / 415.0)
    assert is456.cl_26_5_1_1b__max_steel(230.0, 450.0) == pytest.approx(0.04 * 230.0 * 450.0)
    assert is456.cl_26_5_1_1__min_tension_steel(230.0, 415.0, 500.0) < is456.cl_26_5_1_1__min_tension_steel(
        230.0, 415.0, 415.0
    )


def test_side_face_steel_trigger_and_area():
    shallow = is456.cl_26_5_1_3__side_face(230.0, 600.0)
    assert shallow.required is False
    deep = is456.cl_26_5_1_3__side_face(230.0, 800.0)
    assert deep.required is True
    assert deep.area_mm2 == pytest.approx(0.001 * 230.0 * 800.0)
    assert deep.area_per_face_mm2 == pytest.approx(0.5 * deep.area_mm2)
    assert deep.max_spacing_mm == pytest.approx(230.0)
    assert is456.cl_26_5_1_3__side_face(400.0, 900.0).max_spacing_mm == pytest.approx(300.0)
    # The torsion flag drops the trigger to 450 mm.
    assert is456.cl_26_5_1_3__side_face(230.0, 500.0, torsion=True).required is True


def test_bar_spacing_rules():
    assert is456.cl_26_3_2__min_bar_spacing(16.0) == pytest.approx(25.0)
    assert is456.cl_26_3_2__min_bar_spacing(32.0) == pytest.approx(32.0)
    assert is456.cl_26_3_2__min_bar_spacing(16.0, agg_mm=40.0) == pytest.approx(45.0)

    assert is456.cl_26_3_3__max_spacing_flexure("slab_main", 120.0) == pytest.approx(300.0)
    assert is456.cl_26_3_3__max_spacing_flexure("slab_main", 80.0) == pytest.approx(240.0)
    assert is456.cl_26_3_3__max_spacing_flexure("slab_distribution", 120.0) == pytest.approx(450.0)
    assert is456.cl_26_3_3__max_spacing_flexure("slab_distribution", 80.0) == pytest.approx(400.0)
    assert is456.cl_26_3_3__max_spacing_flexure("beam", 415.0, fy_mpa=415.0) == pytest.approx(180.0)
    with pytest.raises(ValueError):
        is456.cl_26_3_3__max_spacing_flexure("column", 300.0)

    assert is456.table_15__clear_spacing(250.0) == pytest.approx(300.0)
    assert is456.table_15__clear_spacing(415.0) == pytest.approx(180.0)
    assert is456.table_15__clear_spacing(500.0) == pytest.approx(150.0)
    assert is456.table_15__clear_spacing(415.0, redistribution_pct=30.0) == pytest.approx(235.0)


def test_development_length_is_47_diameters_for_m20_fe415():
    assert is456.cl_26_2_1_1__tau_bd(20.0, deformed=False) == pytest.approx(1.2)
    assert is456.cl_26_2_1_1__tau_bd(20.0) == pytest.approx(1.92)
    assert is456.cl_26_2_1_1__tau_bd(25.0) == pytest.approx(1.4 * 1.6)
    assert is456.cl_26_2_1_1__tau_bd(50.0) == is456.cl_26_2_1_1__tau_bd(40.0)

    ld_per_dia = is456.cl_26_2_1__ld(1.0, 415.0, 20.0)
    assert ld_per_dia == pytest.approx(47.0, rel=0.01)
    assert is456.cl_26_2_1__ld(16.0, 415.0, 20.0) == pytest.approx(16.0 * ld_per_dia)
    # A stronger concrete bonds better, a stronger steel needs more length.
    assert is456.cl_26_2_1__ld(16.0, 415.0, 25.0) < is456.cl_26_2_1__ld(16.0, 415.0, 20.0)
    assert is456.cl_26_2_1__ld(16.0, 500.0, 20.0) > is456.cl_26_2_1__ld(16.0, 415.0, 20.0)
    # Compression bond is 1.25 times tension bond, so Ld drops by that factor.
    assert is456.cl_26_2_1__ld(16.0, 415.0, 20.0, compression=True) == pytest.approx(
        is456.cl_26_2_1__ld(16.0, 415.0, 20.0) / 1.25
    )


def test_simple_support_anchorage_check():
    short = is456.cl_26_2_3_3__simple_support_anchorage(30.0e6, 100.0e3, 200.0, 600.0)
    assert short.available_mm == pytest.approx(1.3 * 30.0e6 / 100.0e3 + 200.0)
    assert short.ok is False
    assert short.ratio < 1.0
    generous = is456.cl_26_2_3_3__simple_support_anchorage(60.0e6, 100.0e3, 200.0, 600.0)
    assert generous.ok is True
    with pytest.raises(ValueError):
        is456.cl_26_2_3_3__simple_support_anchorage(30.0e6, 0.0, 200.0, 600.0)


# ---------------------------------------------------------------------------
# columns, Clauses 25, 39 and 26.5.3
# ---------------------------------------------------------------------------


def test_e_min_classic_vector():
    assert is456.cl_25_4__e_min(3000.0, 450.0) == pytest.approx(21.0)
    # The 20 mm floor bites on small stocky columns.
    assert is456.cl_25_4__e_min(2000.0, 230.0) == pytest.approx(20.0)
    assert is456.cl_25_3__max_unsupported(230.0) == pytest.approx(13800.0)


def test_slenderness_verdict():
    short = is456.cl_25_1_2__slenderness(3000.0, 3000.0, 300.0, 300.0)
    assert short.lambda_x == pytest.approx(10.0)
    assert short.short is True
    slender = is456.cl_25_1_2__slenderness(4000.0, 3000.0, 300.0, 230.0)
    assert slender.lambda_x == pytest.approx(13.333333, rel=1e-6)
    assert slender.short is False
    with pytest.raises(ValueError):
        is456.cl_25_1_2__slenderness(3000.0, 3000.0, 0.0, 230.0)


def test_pu_axial_and_puz_arithmetic():
    fck, fy = 25.0, 415.0
    gross = 300.0 * 300.0
    asc = 0.01 * gross
    ac = gross - asc
    pu = is456.cl_39_3__pu_axial(fck, fy, ac, asc)
    puz = is456.cl_39_6__puz(fck, fy, ac, asc)
    assert pu == pytest.approx(0.4 * fck * ac + 0.67 * fy * asc)
    assert puz == pytest.approx(0.45 * fck * ac + 0.75 * fy * asc)
    # Puz is the squash load, so it always exceeds the design axial capacity.
    assert puz > pu
    # More steel lifts both.
    asc2 = 0.02 * gross
    assert is456.cl_39_3__pu_axial(fck, fy, gross - asc2, asc2) > pu


def test_alpha_n_ladder():
    assert is456.cl_39_6__alpha_n(0.2, 1.0) == pytest.approx(1.0)
    assert is456.cl_39_6__alpha_n(0.8, 1.0) == pytest.approx(2.0)
    assert is456.cl_39_6__alpha_n(0.5, 1.0) == pytest.approx(1.5)
    assert is456.cl_39_6__alpha_n(0.05, 1.0) == pytest.approx(1.0)
    assert is456.cl_39_6__alpha_n(0.95, 1.0) == pytest.approx(2.0)
    with pytest.raises(ValueError):
        is456.cl_39_6__alpha_n(100.0, 0.0)


def test_biaxial_interaction_sum():
    assert is456.cl_39_6__biaxial_ratio(50.0e6, 0.0, 100.0e6, 100.0e6, 1.0) == pytest.approx(0.5)
    assert is456.cl_39_6__biaxial_ratio(50.0e6, 50.0e6, 100.0e6, 100.0e6, 1.0) == pytest.approx(1.0)
    assert is456.cl_39_6__biaxial_ratio(50.0e6, 50.0e6, 100.0e6, 100.0e6, 2.0) == pytest.approx(0.5)
    # Sign of the moment does not change the utilisation.
    assert is456.cl_39_6__biaxial_ratio(-50.0e6, 50.0e6, 100.0e6, 100.0e6, 1.5) == pytest.approx(
        is456.cl_39_6__biaxial_ratio(50.0e6, 50.0e6, 100.0e6, 100.0e6, 1.5)
    )
    with pytest.raises(ValueError):
        is456.cl_39_6__biaxial_ratio(50.0e6, 50.0e6, 0.0, 100.0e6, 1.5)


def test_additional_moment_and_k_factor():
    ma = is456.cl_39_7_1__additional_moment(500.0e3, 300.0, 4500.0)
    assert ma == pytest.approx(500.0e3 * 300.0 * (4500.0 / 300.0) ** 2 / 2000.0)
    # Squarely proportional to slenderness.
    assert is456.cl_39_7_1__additional_moment(500.0e3, 300.0, 9000.0) == pytest.approx(4.0 * ma)

    assert is456.cl_39_7_1_1__k(700.0e3, 1500.0e3, 700.0e3) == pytest.approx(1.0)
    assert is456.cl_39_7_1_1__k(1500.0e3, 1500.0e3, 700.0e3) == pytest.approx(0.0)
    assert is456.cl_39_7_1_1__k(1100.0e3, 1500.0e3, 700.0e3) == pytest.approx(0.5)
    # Below the balanced load the factor is clamped at 1.0, never above it.
    assert is456.cl_39_7_1_1__k(100.0e3, 1500.0e3, 700.0e3) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        is456.cl_39_7_1_1__k(500.0e3, 700.0e3, 700.0e3)


def test_column_longitudinal_limits_and_ties():
    gross = 300.0 * 300.0
    limits = is456.cl_26_5_3_1__long_steel_limits(gross)
    assert limits.asc_min_mm2 == pytest.approx(0.008 * gross)
    assert limits.asc_max_mm2 == pytest.approx(0.06 * gross)
    assert limits.asc_lap_warn_mm2 == pytest.approx(0.04 * gross)
    assert limits.min_bars == 4
    assert limits.min_dia_mm == 12.0
    assert limits.max_periphery_spacing_mm == 300.0

    ties = is456.cl_26_5_3_2__ties(32.0, 400.0)
    assert ties.dia_mm == pytest.approx(8.0)
    # Least of the 400 mm section, 16 x 32 = 512 mm and the 300 mm cap.
    assert ties.pitch_mm == pytest.approx(300.0)
    small = is456.cl_26_5_3_2__ties(16.0, 230.0)
    assert small.dia_mm == pytest.approx(6.0)
    assert small.pitch_mm == pytest.approx(230.0)
    mixed = is456.cl_26_5_3_2__ties(25.0, 400.0, dia_long_min_mm=12.0)
    assert mixed.pitch_mm == pytest.approx(192.0)


# ---------------------------------------------------------------------------
# slabs, Annex D and Clauses 24 and 26.5.2
# ---------------------------------------------------------------------------


def test_table_26_carries_all_nine_cases_over_the_full_ratio_grid():
    block = TABLES["annex_d_table_26"]
    assert [float(r) for r in block["ratios"]] == [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0]
    assert sorted(int(k) for k in block["cases"]) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    for case, data in sorted(block["cases"].items()):
        assert len(data["alpha_x_neg"]) == 8, case
        assert len(data["alpha_x_pos"]) == 8, case
        # Every case carries a positive midspan coefficient in both directions.
        assert all(v is not None and v > 0.0 for v in data["alpha_x_pos"]), case
        assert data["alpha_y_pos"] is not None and data["alpha_y_pos"] > 0.0, case
        # Support coefficients, where they exist, exceed the span coefficients.
        for neg, pos in zip(data["alpha_x_neg"], data["alpha_x_pos"]):
            if neg is not None:
                assert neg > pos, case


def test_table_26_interpolates_case_1_at_the_midpoint():
    at_10 = is456.annex_d__table26(1, 1.0)
    at_11 = is456.annex_d__table26(1, 1.1)
    mid = is456.annex_d__table26(1, 1.05)
    assert at_10.alpha_x_neg == pytest.approx(0.032)
    assert at_10.alpha_x_pos == pytest.approx(0.024)
    assert mid.alpha_x_neg == pytest.approx(0.5 * (at_10.alpha_x_neg + at_11.alpha_x_neg))
    assert mid.alpha_x_neg == pytest.approx(0.0345)
    assert mid.alpha_x_pos == pytest.approx(0.026)
    # The long-span coefficients do not vary with the ratio.
    assert mid.alpha_y_neg == pytest.approx(0.032)
    assert mid.alpha_y_pos == pytest.approx(0.024)
    # Flat above the tabulated range, and rising with the ratio.
    assert is456.annex_d__table26(1, 3.0).alpha_x_pos == pytest.approx(0.049)
    series = [is456.annex_d__table26(1, r).alpha_x_pos for r in (1.0, 1.25, 1.5, 2.0)]
    assert series == sorted(series)


def test_table_26_accepts_case_names_and_reports_missing_edges_as_zero():
    assert is456.annex_d__table26("interior", 1.2) == is456.annex_d__table26(1, 1.2)
    assert is456.annex_d__table26("four_edges_discontinuous", 1.0) == is456.annex_d__table26(9, 1.0)
    free = is456.annex_d__table26(9, 1.5)
    assert free.alpha_x_neg == 0.0
    assert free.alpha_y_neg == 0.0
    assert free.alpha_x_pos == pytest.approx(0.089)
    assert free.alpha_y_pos == pytest.approx(0.056)
    # Case 6 is continuous on the short edges only.
    case6 = is456.annex_d__table26(6, 1.0)
    assert case6.alpha_x_neg == 0.0
    assert case6.alpha_y_neg == pytest.approx(0.045)
    with pytest.raises(ValueError):
        is456.annex_d__table26(10, 1.0)
    with pytest.raises(ValueError):
        is456.annex_d__table26(1, 0.9)


def test_table_27_simply_supported_panel():
    at_10 = is456.annex_d__table27(1.0)
    assert at_10.alpha_x == pytest.approx(0.062)
    assert at_10.alpha_y == pytest.approx(0.062)
    assert is456.annex_d__table27(2.0).alpha_x == pytest.approx(0.118)
    assert is456.annex_d__table27(1.05).alpha_x == pytest.approx(0.5 * (0.062 + 0.074))
    # Table 27 gives more midspan moment than the restrained Table 26 case 1.
    assert is456.annex_d__table27(1.0).alpha_x > is456.annex_d__table26(1, 1.0).alpha_x_pos
    with pytest.raises(ValueError):
        is456.annex_d__table27(0.5)


def test_corner_torsion_and_two_way_span_depth_and_min_slab_steel():
    both = is456.annex_d_1_8__corner_torsion(500.0, 4000.0)
    assert both.ast_mm2 == pytest.approx(375.0)
    assert both.band_mm == pytest.approx(800.0)
    assert both.layers == 4
    one = is456.annex_d_1_8__corner_torsion(500.0, 4000.0, discontinuous_edges=1)
    assert one.ast_mm2 == pytest.approx(0.5 * both.ast_mm2)
    assert is456.annex_d_1_8__corner_torsion(500.0, 4000.0, discontinuous_edges=0).ast_mm2 == 0.0
    with pytest.raises(ValueError):
        is456.annex_d_1_8__corner_torsion(500.0, 4000.0, discontinuous_edges=3)

    hysd = is456.cl_24_1__two_way_ld("continuous", 415.0, 3.0, 2.0)
    assert hysd.ratio == pytest.approx(32.0)
    assert hysd.applicable is True
    mild = is456.cl_24_1__two_way_ld("continuous", 250.0, 3.0, 2.0)
    assert mild.ratio == pytest.approx(40.0)
    assert is456.cl_24_1__two_way_ld("simply_supported", 415.0, 3.0, 2.0).ratio == pytest.approx(28.0)
    assert is456.cl_24_1__two_way_ld("continuous", 415.0, 4.5, 2.0).applicable is False
    assert is456.cl_24_1__two_way_ld("continuous", 415.0, 3.0, 4.0).applicable is False

    assert is456.cl_26_5_2_1__min_slab_steel(150.0, 415.0) == pytest.approx(0.0012 * 1000.0 * 150.0)
    assert is456.cl_26_5_2_1__min_slab_steel(150.0, 250.0) == pytest.approx(0.0015 * 1000.0 * 150.0)
    assert is456.cl_26_5_2_1__min_slab_steel(150.0, 500.0, width_mm=500.0) == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# footings, Clauses 31 and 34
# ---------------------------------------------------------------------------


def test_punching_capacity_for_m25_is_1_25():
    square = is456.cl_31_6_3__punching(1.0, 25.0, 1.0)
    assert square.tau_c_mpa == pytest.approx(1.25)
    assert square.ks == pytest.approx(1.0)
    assert square.capacity_mpa == pytest.approx(1.25)
    assert square.ratio == pytest.approx(0.8)
    # ks caps at 1.0 no matter how square the column is.
    assert is456.cl_31_6_3__punching(1.0, 25.0, 2.0).ks == pytest.approx(1.0)
    # An elongated column knocks the capacity down.
    oblong = is456.cl_31_6_3__punching(1.0, 25.0, 0.25)
    assert oblong.ks == pytest.approx(0.75)
    assert oblong.capacity_mpa == pytest.approx(0.9375)
    assert is456.cl_31_6_3__punching(1.0, 20.0, 1.0).tau_c_mpa == pytest.approx(0.25 * math.sqrt(20.0))


def test_footing_bending_section_band_and_edge():
    assert is456.cl_34_2_3_2__bending_section(1500.0, 300.0) == pytest.approx(600.0)
    assert is456.cl_34_2_3_2__bending_section(300.0, 400.0) == 0.0
    assert is456.cl_34_3_1_2__band_distribution(1.0) == pytest.approx(1.0)
    assert is456.cl_34_3_1_2__band_distribution(2.0) == pytest.approx(2.0 / 3.0)
    assert is456.cl_34_3_1_2__band_distribution(3.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        is456.cl_34_3_1_2__band_distribution(0.5)
    assert is456.cl_34_1_2__min_edge_thickness() == 150.0


def test_bearing_stress_is_capped_at_twice_the_area_ratio():
    fck = 25.0
    tight = is456.cl_34_4__bearing(fck, 4.0e4, 1.0e4)
    assert tight.area_ratio == pytest.approx(2.0)
    assert tight.stress_mpa == pytest.approx(0.9 * fck)
    # A huge spread cannot lift the stress past 0.9 fck.
    assert is456.cl_34_4__bearing(fck, 1.0e8, 1.0e4).stress_mpa == pytest.approx(0.9 * fck)
    loose = is456.cl_34_4__bearing(fck, 2.25e4, 1.0e4)
    assert loose.area_ratio == pytest.approx(1.5)
    assert loose.stress_mpa == pytest.approx(0.45 * fck * 1.5)
    assert is456.cl_34_4__bearing(fck, 1.0e4, 1.0e4).stress_mpa == pytest.approx(0.45 * fck)
    with pytest.raises(ValueError):
        is456.cl_34_4__bearing(fck, 1.0e4, 0.0)


def test_min_dowels():
    dowels = is456.cl_34_4_3__min_dowels(300.0 * 300.0)
    assert dowels.area_mm2 == pytest.approx(450.0)
    assert dowels.min_bars == 4
    with pytest.raises(ValueError):
        is456.cl_34_4_3__min_dowels(0.0)


# ---------------------------------------------------------------------------
# data provenance
# ---------------------------------------------------------------------------


def test_every_table_block_names_its_source_and_edition():
    for name, block in sorted(TABLES.items()):
        if not isinstance(block, dict):
            continue
        assert "source" in block, name
        assert "edition" in block, name
        assert "IS 456" in block["source"] or "SP 16" in block["source"], name
    assert "IS 456:2000" in TABLES["source"]
    assert TABLES["edition"].startswith("2000")


def test_transcribed_and_digitized_blocks_are_flagged_for_print_verification():
    # Every transcribed block states its print-verification status. "print"
    # means it has not been read back against the printed standard; anything
    # else must start with "verified" and name what it was read against.
    # Task J4 (2026-08-30) closed the six IS 456 tables below against the
    # Public.Resource.Org BIS scan of IS 456:2000 and left SP 16 Table F and
    # the three digitized figures open, because neither SP 16 nor a readable
    # rendering of Figures 4, 5 and 6 could be obtained.
    verified = (
        "annex_d_table_26",
        "annex_d_table_27",
        "table_12_moment_coefficients",
        "table_15_clear_spacing",
        "table_16a_fire_cover",
        "table_19_tau_c",
    )
    for name in verified:
        marker = TABLES[name]["verify"]
        assert marker.startswith("verified "), name + ": " + repr(marker)
        assert "IS 456:2000" in marker, name
    assert TABLES["sp16_table_f_fsc"]["verify"] == "print"
    for name in ("fig_4_mf_tension", "fig_5_mf_compression", "fig_6_mf_flanged"):
        assert FIGS[name]["verify"] == "print", name
        assert "source" in FIGS[name] and "edition" in FIGS[name], name


def test_fig_4_grid_shape_matches_its_axes():
    block = FIGS["fig_4_mf_tension"]
    assert len(block["fs_mpa"]) == len(block["mf"])
    for fs in block["fs_mpa"]:
        row = block["mf"][int(fs)]
        assert len(row) == len(block["pt"]), fs
        assert all(block["mf_min"] <= v <= block["mf_max"] for v in row), fs


def test_table_12_coefficients_are_carried_for_the_one_way_path():
    block = TABLES["table_12_moment_coefficients"]
    fixed = block["dead_and_imposed_fixed"]
    assert fixed["span_end"] == pytest.approx(1.0 / 12.0)
    assert fixed["span_interior"] == pytest.approx(1.0 / 16.0)
    assert fixed["support_near_end"] == pytest.approx(-1.0 / 10.0)
    assert fixed["support_interior"] == pytest.approx(-1.0 / 12.0)
    moving = block["imposed_not_fixed"]
    assert moving["span_end"] == pytest.approx(1.0 / 10.0)
    assert moving["support_near_end"] == pytest.approx(-1.0 / 9.0)


# ---------------------------------------------------------------------------
# registration and tracing
# ---------------------------------------------------------------------------

#: One valid call per decorated callable; the coverage test keeps this honest.
CALL_VECTORS = {
    "annex_d_1_8__corner_torsion": ((500.0, 4000.0), {"discontinuous_edges": 2}),
    "annex_d__table26": ((1, 1.2), {}),
    "annex_d__table27": ((1.5,), {}),
    "annex_g__ast_singly": ((100.0e6, 230.0, 415.0, 20.0, 415.0), {}),
    "annex_g__doubly": ((150.0e6, 230.0, 415.0, 50.0, 20.0, 415.0), {}),
    "annex_g__mu_lim": ((230.0, 415.0, 20.0, 415.0), {}),
    "annex_g__xu_max_over_d": ((415.0,), {}),
    "cl_23_2_1__basic_ld": (("continuous",), {}),
    "cl_23_2_1__fs": ((415.0, 800.0, 900.0), {}),
    "cl_23_2_1_c__long_span_factor": ((12.0,), {}),
    "cl_24_1__two_way_ld": (("continuous", 415.0, 3.0, 2.0), {}),
    "cl_25_1_2__slenderness": ((3000.0, 3000.0, 300.0, 230.0), {}),
    "cl_25_3__max_unsupported": ((230.0,), {}),
    "cl_25_4__e_min": ((3000.0, 450.0), {}),
    "cl_26_2_1_1__tau_bd": ((20.0,), {}),
    "cl_26_2_1__ld": ((16.0, 415.0, 20.0), {}),
    "cl_26_2_3_3__simple_support_anchorage": ((30.0e6, 100.0e3, 200.0, 600.0), {}),
    "cl_26_3_2__min_bar_spacing": ((16.0,), {}),
    "cl_26_3_3__max_spacing_flexure": (("slab_main", 120.0), {}),
    "cl_26_4_2_2__footing_cover": ((), {}),
    "cl_26_5_1_1__min_tension_steel": ((230.0, 415.0, 415.0), {}),
    "cl_26_5_1_1b__max_steel": ((230.0, 450.0), {}),
    "cl_26_5_1_3__side_face": ((230.0, 800.0), {}),
    "cl_26_5_1_5__max_stirrup_spacing": ((415.0,), {}),
    "cl_26_5_1_6__min_stirrups": ((230.0, 415.0), {}),
    "cl_26_5_2_1__min_slab_steel": ((150.0, 415.0), {}),
    "cl_26_5_3_1__long_steel_limits": ((52900.0,), {}),
    "cl_26_5_3_2__ties": ((20.0, 300.0), {}),
    "cl_31_6_3__punching": ((1.0, 25.0, 1.0), {}),
    "cl_34_1_2__min_edge_thickness": ((), {}),
    "cl_34_2_3_2__bending_section": ((1500.0, 300.0), {}),
    "cl_34_3_1_2__band_distribution": ((1.5,), {}),
    "cl_34_4__bearing": ((25.0, 1.0e6, 1.0e5), {}),
    "cl_34_4_3__min_dowels": ((90000.0,), {}),
    "cl_39_3__pu_axial": ((25.0, 415.0, 88000.0, 2000.0), {}),
    "cl_39_6__alpha_n": ((500.0e3, 1500.0e3), {}),
    "cl_39_6__biaxial_ratio": ((50.0e6, 30.0e6, 90.0e6, 80.0e6, 1.5), {}),
    "cl_39_6__puz": ((25.0, 415.0, 88000.0, 2000.0), {}),
    "cl_39_7_1__additional_moment": ((500.0e3, 300.0, 4000.0), {}),
    "cl_39_7_1_1__k": ((500.0e3, 1500.0e3, 700.0e3), {}),
    "cl_40_1__tau_v": ((100.0e3, 230.0, 415.0), {}),
    "cl_40_2_1_1__k_solid_slab": ((150.0,), {}),
    "cl_40_4__vertical_stirrups": ((50.0e3, 415.0, 415.0), {}),
    "cl_41_3_1__equiv_shear": ((100.0e3, 20.0e6, 230.0), {}),
    "cl_41_4_2__equiv_moment": ((100.0e6, 20.0e6, 230.0, 450.0), {}),
    "cl_41_4_3__transverse": ((20.0e6, 100.0e3, 170.0, 390.0, 415.0, 150.0), {}),
    "cl_6_2_3_1__ec": ((25.0,), {}),
    "fig_4__mf_tension": ((240.0, 1.0), {}),
    "fig_5__mf_compression": ((0.5,), {}),
    "fig_6__mf_flanged": ((0.5,), {}),
    "sp16_table_f__fsc": ((415.0, 0.1), {}),
    "table_15__clear_spacing": ((415.0,), {}),
    "table_16__nominal_cover": (("moderate",), {}),
    "table_16a__fire_cover": (("beam", 2.0), {}),
    "table_19__tau_c": ((0.75, 25.0), {}),
    "table_20__tau_c_max": ((25.0,), {}),
    "table_5__min_grade": (("moderate",), {}),
}


def _decorated_callables():
    """Every public clause callable the module exposes, by name."""
    found = {}
    for name in dir(is456):
        if name.startswith("_"):
            continue
        obj = getattr(is456, name)
        if callable(obj) and hasattr(obj, "clause_meta"):
            found[name] = obj
    return found


def test_call_vectors_cover_every_decorated_callable():
    assert sorted(CALL_VECTORS) == sorted(_decorated_callables())
    assert len(CALL_VECTORS) >= 50


def test_every_callable_is_registered_under_a_unique_is456_clause_id():
    """Each callable claims its own clause id and that id reaches the bibliography.

    Entry IDENTITY is deliberately not asserted: CLAUSE_REGISTRY is keyed by
    clause id for the whole process, and test_trace.py registers demo callables
    on two real IS 456 ids (G-1.1(b) and G-1.2), so in a full-suite run the last
    module imported owns those two keys. What has to hold is that every callable
    here claims a distinct id and that report.py can cite it.
    """
    callables = _decorated_callables()
    ids = []
    for name, func in sorted(callables.items()):
        meta = func.clause_meta
        assert meta.code == "IS456:2000", name
        assert meta.ref, name
        assert meta.title, name
        assert meta.func == name, name
        registered = CLAUSE_REGISTRY.get(meta.clause_id)
        assert registered is not None, name
        assert registered.code == meta.code, name
        assert registered.ref == meta.ref, name
        ids.append(meta.clause_id)
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("name", sorted(CALL_VECTORS))
def test_every_callable_emits_its_own_trace_entry(name):
    func = getattr(is456, name)
    args, kwargs = CALL_VECTORS[name]
    entries = []
    with trace_into(entries):
        output = func(*args, **kwargs)
    assert entries, name
    # Nested clause calls land first; the callable itself closes the list.
    outer = entries[-1]
    assert outer.code == "IS456:2000"
    assert outer.ref == func.clause_meta.ref
    assert outer.units == func.clause_meta.units
    record = outer.to_dict()
    assert set(record) == {"code", "ref", "title", "symbol", "inputs", "output", "units", "latex"}
    if hasattr(output, "_asdict"):
        assert record["output"] == {k: v for k, v in output._asdict().items()}
    else:
        assert record["output"] == output


def test_units_are_declared_on_every_dimensional_callable():
    dimensionless = {
        "annex_d__table26",
        "annex_d__table27",
        "annex_g__xu_max_over_d",
        "cl_23_2_1__basic_ld",
        "cl_23_2_1_c__long_span_factor",
        "cl_24_1__two_way_ld",
        "cl_25_1_2__slenderness",
        "cl_34_3_1_2__band_distribution",
        "cl_39_6__alpha_n",
        "cl_39_6__biaxial_ratio",
        "cl_39_7_1_1__k",
        "cl_40_2_1_1__k_solid_slab",
        "fig_4__mf_tension",
        "fig_5__mf_compression",
        "fig_6__mf_flanged",
    }
    allowed = {"mm", "mm2", "mm2/mm", "N", "N.mm", "MPa"}
    for name, func in sorted(_decorated_callables().items()):
        units = func.clause_meta.units
        if name in dimensionless:
            assert units == "", name
        else:
            assert units in allowed, (name, units)


def test_calls_are_deterministic_and_free_of_sink_side_effects():
    first = [is456.table_19__tau_c(pt, 25.0) for pt in (0.15, 0.75, 1.5, 3.0)]
    entries = []
    with trace_into(entries):
        traced = [is456.table_19__tau_c(pt, 25.0) for pt in (0.15, 0.75, 1.5, 3.0)]
    second = [is456.table_19__tau_c(pt, 25.0) for pt in (0.15, 0.75, 1.5, 3.0)]
    assert first == traced == second
    assert len(entries) == 4
    assert [e.inputs["pt"] for e in entries] == [0.15, 0.75, 1.5, 3.0]


def test_nested_clause_calls_are_recorded_in_derivation_order():
    entries = []
    with trace_into(entries):
        is456.annex_g__mu_lim(230.0, 415.0, 20.0, 415.0)
    assert [e.ref for e in entries] == ["G-1.1", "G-1.1(b)"]

    entries = []
    with trace_into(entries):
        is456.cl_26_2_1__ld(16.0, 415.0, 20.0)
    assert [e.ref for e in entries] == ["26.2.1.1", "26.2.1"]
