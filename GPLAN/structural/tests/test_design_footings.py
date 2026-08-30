"""Pins for footing design: bearing capacity, plan, depth, steel, dowels.

The vectors here are hand-computed and written out in the docstring that uses
them, so a reader can check the arithmetic without running anything: the IS 6403
chain on a 1.5 m square pad, the punching and one-way shear depths that a pad is
sized by, the Cl 34.3.1.2 central band on a 2:1 rectangle, the Cl 34.4 bearing
transfer that puts dowels in, and for the wall strip the width that a line load
buys, the Cl 34.1.3 spread that decides plain against reinforced, and the
Cl 34.2.3.2(b) masonry bending section that the reinforced case is designed at.

The behavioural pins matter as much as the numbers: a footing that cannot be
made to work still returns a fully populated result with status fail, the same
input twice gives the same dict, the strap case refers the beam out instead of
pretending to design it, and a plain concrete strip comes back with a verdict
and no reinforcement rather than with steel nothing asked for.
"""

from __future__ import annotations

import json
import math

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests, and an absolute GPLAN.structural
# import would resolve against the outer directory instead.
from ..codes import is456, is6403
from ..codes.trace import trace_into
from ..design import common as C
from ..design.rcc import footings as FT


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def pad(column_mm=(300.0, 300.0), **kwargs):
    """A pad geometry with a square column at the centre unless told otherwise."""
    return FT.PadGeometry(
        element_id=kwargs.pop("element_id", "F-C1"),
        column=FT.ColumnStub(column_id="C1", bx_mm=column_mm[0], dy_mm=column_mm[1]),
        **kwargs
    )


def rows(result):
    return {row.name: row for row in result.checks}


def bars(result, role):
    return [bar for bar in result.bars if bar["role"] == role]


# ---------------------------------------------------------------------------
# bearing capacity: the IS 6403 chain and the stated-SBC shortcut
# ---------------------------------------------------------------------------


def test_is6403_chain_matches_the_hand_vector():
    """phi 30, c 0, gamma 18 kN/m3, Df 1.5 m, B = L = 1.5 m, FOS 2.5.

    Nq = e^(pi tan30) tan^2(60) = 6.1337 x 3 = 18.401
    Nc = (Nq - 1) cot 30 = 17.401 / 0.57735 = 30.140
    Ngamma = 2 (Nq + 1) tan 30 = 2 x 19.401 x 0.57735 = 22.402
    shape, B/L = 1: sc = sq = 1.2, sgamma = 0.6
    depth, Df/B = 1, root Nphi = tan 60 = 1.7321: dc = 1.3464, dq = dgamma = 1.1732
    surcharge q = 18 x 1.5 = 27 kPa, no water table so W' = 1
    cohesion term  = 0
    surcharge term = 27 x 17.401 x 1.2 x 1.1732            = 661.45 kPa
    width term     = 0.5 x 1.5 x 18 x 22.402 x 0.6 x 1.1732 = 212.89 kPa
    q_net_ult = 874.34 kPa, q_safe_net = 874.34 / 2.5       = 349.74 kPa
    q_safe_gross = 349.74 + 27                              = 376.74 kPa
    """
    chain = is6403.net_safe_bearing(c_kpa=0.0, phi_deg=30.0, gamma_knm3=18.0, b_m=1.5, l_m=1.5, df_m=1.5)
    assert chain.nq == pytest.approx(18.401, rel=1e-3)
    assert chain.nc == pytest.approx(30.140, rel=1e-3)
    assert chain.n_gamma == pytest.approx(22.402, rel=1e-3)
    assert chain.term_cohesion_kpa == 0.0
    assert chain.term_surcharge_kpa == pytest.approx(661.45, rel=1e-3)
    assert chain.term_width_kpa == pytest.approx(212.89, rel=1e-3)
    assert chain.q_net_ult_kpa == pytest.approx(874.34, rel=1e-3)
    assert chain.q_safe_net_kpa == pytest.approx(349.74, rel=1e-3)
    assert chain.q_safe_gross_kpa == pytest.approx(376.74, rel=1e-3)

    # and the design layer reads that same number for a 1.5 m square pad, having
    # converted its own millimetres to the metres the chain speaks.
    allow = FT.allowable_pressure(FT.SoilProfile(), 1500.0, 1500.0)
    assert allow.q_allow_kpa == pytest.approx(349.74, rel=1e-3)
    assert allow.source.startswith("IS 6403")


def test_a_stated_sbc_is_used_as_given_and_says_so():
    allow = FT.allowable_pressure(FT.SoilProfile(sbc_kpa=185.0), 2000.0, 2000.0)
    assert allow.q_allow_kpa == 185.0
    assert allow.source == "user SBC"
    assert any("was not walked" in note for note in allow.notes)

    entries = []
    with trace_into(entries):
        FT.allowable_pressure(FT.SoilProfile(sbc_kpa=185.0), 2000.0, 2000.0)
    assert not [entry for entry in entries if entry.code == is6403.CODE]


def test_the_chain_is_traced_clause_by_clause_when_it_runs():
    entries = []
    with trace_into(entries):
        FT.allowable_pressure(FT.SoilProfile(), 1800.0, 2400.0)
    ids = [entry.clause_id for entry in entries]
    for ref in ("Table 1", "Table 2", "Table 3", "6.1"):
        assert is6403.CODE + " " + ref in ids


def test_the_soil_profile_reads_the_request_block_and_the_placer_shape():
    from_request = FT.SoilProfile.from_params({"phi_deg": 34.0, "founding_depth_m": 2.0, "water_table_m": 3.0})
    assert from_request.sbc_kpa is None
    assert from_request.phi_deg == 34.0
    assert from_request.df_m == 2.0
    assert from_request.gwt_depth_m == 3.0

    class PlacerSoil(object):
        sbc_kpa = 165.0
        founding_depth_m = 1.2
        water_table_m = None

    from_placer = FT.SoilProfile.from_params(PlacerSoil())
    assert from_placer.sbc_kpa == 165.0
    assert from_placer.df_m == 1.2


# ---------------------------------------------------------------------------
# plan sizing
# ---------------------------------------------------------------------------


def test_plan_area_covers_the_service_load_with_the_self_weight_allowance():
    """800 kN service on 150 kPa: A = 800 x 1.1 / 150 = 5.87 m2, side 2.42 m,
    rounded up to the 100 mm plan step is 2.5 m square (6.25 m2)."""
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert result.section["bx_mm"] == 2500.0
    assert result.section["ly_mm"] == 2500.0
    assert result.section["q_max_kpa"] == pytest.approx(800.0 / 6.25, rel=1e-6)
    assert rows(result)["bearing pressure"].status == C.CHECK_PASS
    # one step smaller would not carry the load with its self weight
    assert 800.0 * 1.1 / (2.4 * 2.4) > 150.0


def test_plan_aspect_follows_the_column():
    """A 900 x 450 column asks for a 2:1 footing, not a square."""
    result = FT.design_footing(
        pad(column_mm=(900.0, 450.0)), FT.FootingLoads(p_service_kn=2000.0), FT.SoilProfile(sbc_kpa=350.0)
    )
    assert result.section["bx_mm"] == 3600.0
    assert result.section["ly_mm"] == 1800.0


def test_the_plan_never_closes_on_the_column_face():
    tiny = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=5.0), FT.SoilProfile(sbc_kpa=300.0))
    assert tiny.section["bx_mm"] >= 300.0 + 2.0 * FT.MIN_PROJECTION_MM
    assert tiny.section["D_mm"] >= is456.cl_34_1_2__min_edge_thickness()


def test_eccentricity_outside_the_kern_enlarges_the_plan():
    """200 kN with 100 kNm is e = 500 mm: the kern needs B >= 6e = 3000 mm,
    where the pressure alone would have been happy with 1100 mm."""
    eccentric = FT.design_footing(
        pad(), FT.FootingLoads(p_service_kn=200.0, mx_service_knm=100.0), FT.SoilProfile(sbc_kpa=200.0)
    )
    concentric = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=200.0), FT.SoilProfile(sbc_kpa=200.0))
    assert concentric.section["bx_mm"] == 1100.0
    assert eccentric.section["bx_mm"] >= 3000.0
    assert eccentric.section["bx_mm"] > concentric.section["bx_mm"]

    check = rows(eccentric)
    assert check["kern x"].demand == pytest.approx(500.0)
    assert check["kern x"].capacity == pytest.approx(eccentric.section["bx_mm"] / 6.0)
    assert check["kern x"].status == C.CHECK_PASS
    # the base stays in contact and the gradient is kept, not averaged away
    assert eccentric.section["q_min_kpa"] >= -1e-6
    assert eccentric.section["q_max_kpa"] > eccentric.section["q_min_kpa"]
    # and the sizing says which rule it was that enlarged the plan
    sized = FT.size_plan(
        200.0, FT.ColumnStub("C1", 300.0, 300.0), FT.SoilProfile(sbc_kpa=200.0), FT.FootingContext(), ex_mm=500.0
    )
    assert sized.driver == "kern eccentricity"
    assert sized.bx_mm == 3000.0


def test_the_pressure_gradient_reaches_the_design_moments():
    """The heavy edge of an eccentric pad carries more moment than the light one,
    so the two cantilevers cannot both be the concentric value."""
    concentric = FT._Field(2400.0, 2400.0, 300.0, 300.0, 0.0, 0.0, 1.0e6, 0.0, 0.0)
    eccentric = FT._Field(2400.0, 2400.0, 300.0, 300.0, 0.0, 0.0, 1.0e6, 200.0, 0.0)
    _f0, m0 = concentric.cantilever("x", 1.0)
    _fp, m_plus = eccentric.cantilever("x", 1.0)
    _fm, m_minus = eccentric.cantilever("x", -1.0)
    assert m_plus > m0 > m_minus
    # the two sides still add up to the concentric total: it is a redistribution
    assert m_plus + m_minus == pytest.approx(2.0 * m0, rel=1e-9)


# ---------------------------------------------------------------------------
# depth: which check sizes the footing
# ---------------------------------------------------------------------------


def test_punching_governs_a_compact_pad_on_rock():
    """1000 kN on 600 kPa needs only a 1.4 m pad, so the 300 mm column punches
    through it long before the 550 mm cantilever shears in one way."""
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=1000.0), FT.SoilProfile(sbc_kpa=600.0))
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert result.governing_check == "two-way shear"
    check = rows(result)
    assert check["two-way shear"].ratio > check["one-way shear x"].ratio
    assert check["two-way shear"].clause == "IS 456 Cl 31.6.3"
    assert check["two-way shear"].status == C.CHECK_PASS
    # the capacity is ks x 0.25 sqrt(fck) with ks = 1 for a square column
    assert check["two-way shear"].capacity == pytest.approx(0.25 * math.sqrt(25.0), rel=1e-9)


def test_one_way_shear_governs_a_wide_pad_on_ordinary_soil():
    """800 kN on 150 kPa spreads to 2.5 m: the 1.1 m cantilever governs and the
    punching perimeter, four times (300 + d), has room to spare."""
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert result.governing_check == "one-way shear x"
    check = rows(result)
    assert check["one-way shear x"].ratio > check["two-way shear"].ratio
    assert check["one-way shear x"].clause == "IS 456 Cl 40.1, Table 19"
    # tau_c is read at the steel the mat actually gets, not at a guess
    steel = [bar for bar in result.bars if bar["role"].startswith("mesh")][0]
    pt = 100.0 * C.area_for_spacing(steel["dia_mm"], steel["spacing_mm"]) / (1000.0 * result.section["d_mm"])
    assert check["one-way shear x"].capacity == pytest.approx(is456.table_19__tau_c(pt, 25.0), rel=1e-6)


def test_the_depth_solver_answers_with_a_depth_that_stays_safe_above_itself():
    field = FT._Field(2500.0, 2500.0, 300.0, 300.0, 0.0, 0.0, 1.2e6, 0.0, 0.0)
    ctx = FT.FootingContext()
    demand = FT._required_d_punching(field, ctx, 1.0)
    assert demand.d_req_mm is not None
    for extra in (0.0, 25.0, 100.0, 400.0):
        d_mm = demand.d_req_mm + extra
        crit = field.critical(d_mm)
        inside = field.load_in(crit.x_lo_mm, crit.x_hi_mm, crit.y_lo_mm, crit.y_hi_mm)
        tau_v = max(field.pu_n - inside, 0.0) / (crit.perimeter_mm * d_mm)
        assert tau_v <= is456.cl_31_6_3__punching(tau_v, 25.0, 1.0).capacity_mpa + 1e-6


def test_overall_depth_is_the_effective_depth_plus_the_cover_and_bar_stack():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    dia = max(bar["dia_mm"] for bar in result.bars if bar["role"].startswith("mesh"))
    assert result.section["cover_mm"] == 50.0
    assert result.section["d_mm"] == pytest.approx(result.section["D_mm"] - 50.0 - 1.5 * dia)
    assert result.section["D_mm"] >= 150.0


def test_a_depth_bump_for_the_dowels_is_disclosed():
    """A 600 mm column needs 1800 mm2 of dowels; the compression development
    length of the bars that gives cannot hide inside a shallow pad."""
    result = FT.design_footing(
        pad(column_mm=(600.0, 600.0)), FT.FootingLoads(p_service_kn=1200.0), FT.SoilProfile(sbc_kpa=300.0)
    )
    assert result.status == C.STATUS_RESIZED
    assert any("dowel anchorage" in step["reason"] for step in result.resize_history)
    check = rows(result)
    assert check["dowel anchorage"].demand <= check["dowel anchorage"].capacity
    assert check["dowel anchorage"].demand == pytest.approx(
        is456.cl_26_2_1__ld(bars(result, "dowel")[0]["dia_mm"], 500.0, 25.0, compression=True)
    )


# ---------------------------------------------------------------------------
# steel: minimum, spacing and the Cl 34.3.1.2 central band
# ---------------------------------------------------------------------------


def test_band_steel_splits_the_short_direction_two_over_beta_plus_one():
    """beta 2 puts 2/(2+1) = 2/3 of the short-direction steel in the central band,
    so the band spacing is s / (f beta) = 0.75 s and the outer strips take the rest."""
    steel = FT.band_steel(40.0e6, 500.0, 600.0, FT.FootingContext(), beta=2.0, short_dim_mm=1800.0)
    assert steel.band_fraction == pytest.approx(2.0 / 3.0)
    assert steel.spacing_band_mm < steel.steel.spacing_mm
    assert steel.spacing_outer_mm > steel.spacing_band_mm
    assert steel.spacing_band_mm == pytest.approx(
        C.round_down_mm(steel.steel.spacing_mm / (steel.band_fraction * 2.0), 10.0)
    )


def test_a_rectangular_footing_gets_a_band_and_two_outer_strips():
    """900 x 450 column, 2000 kN on 350 kPa: a 3600 x 1800 footing, beta exactly 2."""
    result = FT.design_footing(
        pad(column_mm=(900.0, 450.0)), FT.FootingLoads(p_service_kn=2000.0), FT.SoilProfile(sbc_kpa=350.0)
    )
    assert result.section["bx_mm"] / result.section["ly_mm"] == 2.0
    band = bars(result, "mesh_y_bottom_band")
    outer = bars(result, "mesh_y_bottom_outer")
    uniform = bars(result, "mesh_x_bottom")
    assert len(band) == 1 and len(outer) == 1 and len(uniform) == 1
    assert band[0]["spacing_mm"] < outer[0]["spacing_mm"]
    assert band[0]["direction"] == "y" and uniform[0]["direction"] == "x"
    assert any("34.3.1.2" in note and "66.7 percent" in note for note in result.notes)
    # the band is the width of the footing, so the outer strips share what is left
    assert outer[0]["strip"].startswith("outer bands")


def test_a_square_footing_has_no_band():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert not bars(result, "mesh_x_bottom_band")
    assert len(bars(result, "mesh_x_bottom")) == 1
    assert len(bars(result, "mesh_y_bottom")) == 1


def test_the_mat_never_falls_below_the_minimum_steel_or_past_the_spacing_cap():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=250.0), FT.SoilProfile(sbc_kpa=200.0))
    check = rows(result)
    minimum = is456.cl_26_5_2_1__min_slab_steel(result.section["D_mm"], 500.0, 1000.0)
    for axis in ("x", "y"):
        assert check["steel " + axis].demand >= minimum - 1e-6
        assert check["steel " + axis].capacity >= check["steel " + axis].demand
        assert check["bar spacing " + axis].demand <= check["bar spacing " + axis].capacity
        assert check["bar spacing " + axis].capacity == pytest.approx(
            is456.cl_26_3_3__max_spacing_flexure("slab", result.section["d_mm"], 500.0)
        )


def test_the_bar_diameter_is_capped_by_what_the_projection_can_develop():
    """Ld is proportional to the diameter and so is the bend, so a bar developed
    in a short projection solves in closed form. A mat worked to its moment is
    capped by it; a mat sitting on the minimum steel is not, because it never
    reaches the stress that would need the length."""
    context = FT.FootingContext()
    worked = FT.anchorage_dia_cap_mm(500.0, context, 1.0)
    nominal = FT.anchorage_dia_cap_mm(500.0, context, 0.2)
    per_mm = is456.cl_26_2_1__ld(1.0, 500.0, 25.0)
    assert worked == pytest.approx(500.0 / (per_mm - 8.0))
    assert worked < 13.0 < nominal

    result = FT.design_footing(
        pad(column_mm=(900.0, 300.0)), FT.FootingLoads(p_service_kn=1200.0), FT.SoilProfile(sbc_kpa=250.0)
    )
    long_way = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]
    assert long_way["dia_mm"] <= 12.0
    check = rows(result)
    assert check["bar anchorage x"].status == C.CHECK_PASS
    assert check["bar anchorage y"].status == C.CHECK_PASS


def test_a_short_projection_ends_the_bars_in_a_bend_and_says_so():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=300.0), FT.SoilProfile(sbc_kpa=250.0))
    assert any("standard 90 degree bend" in note for note in result.notes)
    assert any("Ast_flexure/Ast_provided" in note for note in result.notes)
    assert rows(result)["bar anchorage x"].status == C.CHECK_PASS


def test_every_bar_carries_its_own_development_length():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert result.bars
    for bar in result.bars:
        assert bar["ld_mm"] > 0.0
        assert len(bar["zone_mm"]) == 2


# ---------------------------------------------------------------------------
# dowels and the Cl 34.4 bearing transfer
# ---------------------------------------------------------------------------


def test_dowels_are_at_least_half_a_percent_of_the_column_in_four_bars():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    group = bars(result, "dowel")[0]
    assert group["count"] >= 4
    assert group["count"] * C.bar_area_mm2(group["dia_mm"]) >= 0.005 * 300.0 * 300.0
    assert rows(result)["dowel steel"].status == C.CHECK_PASS


def test_the_bearing_check_puts_the_excess_force_into_the_dowels():
    """1500 kN service on a 300 mm column is 2250 kN factored, 25.0 MPa on the
    face. The permissible stress is 0.45 fck sqrt(A1/A2) capped at 0.9 fck =
    22.5 MPa, so 225 kN has to travel through steel at 0.67 fy = 335 MPa, which
    is 672 mm2 and beats the Cl 34.4.3 half a percent minimum of 450 mm2."""
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=1500.0), FT.SoilProfile(sbc_kpa=300.0))
    check = rows(result)
    assert check["dowel steel"].demand == pytest.approx(672.0, rel=0.02)
    assert check["dowel steel"].demand > 0.005 * 300.0 * 300.0
    assert check["bearing at column face"].demand == pytest.approx(2250.0e3, rel=1e-6)
    assert check["bearing at column face"].status == C.CHECK_PASS
    assert any("excess at 0.67 fy" in note for note in result.notes)

    spec = FT.dowels(
        2250.0e3, FT.ColumnStub("C1", 300.0, 300.0), 2300.0, 2300.0, 0.0, 0.0, 650.0, 50.0, 12.0, FT.FootingContext()
    )
    assert spec.frustum_ratio == pytest.approx(2.0)  # capped by the clause
    assert spec.bearing_capacity_mpa == pytest.approx(0.9 * 25.0)
    assert spec.excess_n == pytest.approx((25.0 - 22.5) * 90000.0, rel=1e-6)


def test_the_frustum_is_similar_and_concentric_with_the_column():
    """A1 is the largest frustum area similar to and concentric with the column,
    so sqrt(A1/A2) is a scale factor with three ceilings: the 2:1 spread through
    the depth (1 + 4D/c), the nearest plan edge (2 x edge / c), and the clause
    cap of 2 that turns 0.45 fck into 0.9 fck."""
    context = FT.FootingContext()
    column = FT.ColumnStub("C1", 300.0, 300.0)

    thin = FT.dowels(200.0e3, column, 3000.0, 3000.0, 0.0, 0.0, 50.0, 50.0, 12.0, context)
    assert thin.frustum_ratio == pytest.approx(1.0 + 4.0 * 50.0 / 300.0, rel=1e-9)

    tight = FT.dowels(200.0e3, column, 500.0, 500.0, 0.0, 0.0, 500.0, 50.0, 12.0, context)
    assert tight.frustum_ratio == pytest.approx(500.0 / 300.0, rel=1e-9)
    assert tight.bearing_capacity_mpa == pytest.approx(0.45 * 25.0 * tight.frustum_ratio)

    roomy = FT.dowels(200.0e3, column, 3000.0, 3000.0, 0.0, 0.0, 600.0, 50.0, 12.0, context)
    assert roomy.frustum_ratio == pytest.approx(2.0)
    assert roomy.bearing_capacity_mpa == pytest.approx(0.9 * 25.0)


# ---------------------------------------------------------------------------
# punching geometry
# ---------------------------------------------------------------------------


def test_the_critical_perimeter_is_clipped_at_the_edge_of_the_footing():
    inside = FT.punching_critical(300.0, 300.0, 0.0, 0.0, 2000.0, 2000.0, 400.0)
    assert inside.sides == 4
    assert inside.perimeter_mm == pytest.approx(4.0 * 700.0)
    assert inside.area_mm2 == pytest.approx(700.0 * 700.0)

    at_the_edge = FT.punching_critical(300.0, 300.0, 850.0, 0.0, 2000.0, 2000.0, 400.0)
    assert at_the_edge.sides == 3
    assert at_the_edge.perimeter_mm == pytest.approx(700.0 + 2.0 * 500.0)
    assert at_the_edge.area_mm2 == pytest.approx(500.0 * 700.0)


# ---------------------------------------------------------------------------
# combined footings
# ---------------------------------------------------------------------------


def combined_pair(p1=600.0, p2=800.0, spacing_m=4.0, column_mm=300.0):
    geometry = FT.CombinedGeometry(
        element_id="FC-1",
        columns=(
            FT.ColumnStub("C1", column_mm, column_mm, x_m=0.0, y_m=0.0),
            FT.ColumnStub("C2", column_mm, column_mm, x_m=spacing_m, y_m=0.0),
        ),
    )
    return geometry, [FT.FootingLoads(p_service_kn=p1), FT.FootingLoads(p_service_kn=p2)]


def test_the_combined_rectangle_sits_its_centroid_on_the_load_resultant():
    """600 kN at x = 0 and 800 kN at x = 4 m put the resultant at 2.286 m; the
    rectangle is symmetric about it, so the pressure really is uniform."""
    geometry, loads = combined_pair()
    result = FT.design_combined_footing(geometry, loads, FT.SoilProfile(sbc_kpa=150.0))
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert result.section["centroid_offset_ratio"] <= 0.05
    assert rows(result)["centroid on the resultant"].status == C.CHECK_PASS
    resultant_m = (600.0 * 0.0 + 800.0 * 4.0) / 1400.0
    assert resultant_m == pytest.approx(2.2857, rel=1e-3)
    assert result.section["q_service_kpa"] <= result.section["q_allow_kpa"] + 1e-9


def test_the_combined_footing_hogs_between_the_columns_and_gets_top_steel():
    geometry, loads = combined_pair()
    result = FT.design_combined_footing(geometry, loads, FT.SoilProfile(sbc_kpa=150.0))
    assert result.section["m_hog_knm"] < 0.0
    assert result.section["m_sag_knm"] > 0.0
    top = bars(result, "long_top")[0]
    bottom = bars(result, "long_bottom")[0]
    assert top["face"] == "top" and bottom["face"] == "bottom"
    assert top["zone_mm"][0] < top["zone_mm"][1]
    assert any("hogging between the columns" in note for note in result.notes)
    check = rows(result)
    assert check["longitudinal flexure hogging"].demand > 0.0
    assert check["longitudinal flexure hogging"].status == C.CHECK_PASS


def test_the_combined_moment_diagram_is_the_beam_on_a_uniform_pressure():
    """Two 500 kN columns 3 m apart on a 4 m footing: w = 1000 / 4 = 250 kN/m,
    the shear crosses zero at 500 / 250 = 2.0 m from the left edge, and the
    moment there is 250 x 2^2 / 2 - 500 x (2 - 0.5) = 500 - 750 = -250 kNm."""
    beam = FT._Beam(
        w_n_per_mm=1000.0e3 / 4000.0,
        length_mm=4000.0,
        stations_mm=(500.0, 3500.0),
        loads_n=(500.0e3, 500.0e3),
    )
    assert beam.shear_n(2000.0) == pytest.approx(0.0, abs=1e-6)
    assert beam.moment_nmm(2000.0) == pytest.approx(-250.0e6, rel=1e-9)
    sag, hog = beam.extremes()
    assert hog == pytest.approx(-250.0e6, rel=1e-9)
    assert sag == pytest.approx(beam.moment_nmm(500.0), rel=1e-9)
    assert beam.moment_nmm(4000.0) == pytest.approx(0.0, abs=1.0)


def test_a_beam_shear_section_needs_room_between_the_supports():
    """1000 kN and 300 kN 3.5 m apart on 400 kPa strong soil give a 6 m x 0.6 m
    rectangle that is really a beam. It comes back designed deep rather than
    refused: a section closer than d to a column face sheds its load straight
    into that face and is not a shear section, so once the clear span is under
    2d the interior window closes instead of reporting an unsatisfiable stress."""
    columns = (
        FT.ColumnStub("C1", 300.0, 300.0, x_m=0.0, y_m=0.0),
        FT.ColumnStub("C2", 300.0, 300.0, x_m=3.5, y_m=0.0),
    )
    result = FT.design_combined_footing(
        FT.CombinedGeometry(element_id="FC-beam", columns=columns),
        [FT.FootingLoads(p_service_kn=1000.0), FT.FootingLoads(p_service_kn=300.0)],
        FT.SoilProfile(sbc_kpa=400.0),
    )
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert result.governing_check == "longitudinal shear"
    assert result.section["D_mm"] > 1000.0
    assert rows(result)["longitudinal shear"].status == C.CHECK_PASS


def test_punching_is_checked_under_every_column_of_a_combined_footing():
    geometry, loads = combined_pair()
    result = FT.design_combined_footing(geometry, loads, FT.SoilProfile(sbc_kpa=150.0))
    names = [row.name for row in result.checks]
    assert "two-way shear C1" in names
    assert "two-way shear C2" in names
    assert "transverse band C1" in names
    assert "transverse band C2" in names
    assert len(bars(result, "band_transverse")) == 2
    assert len(bars(result, "dowel")) == 2


def test_the_combined_designer_refuses_anything_but_two_columns():
    geometry = FT.CombinedGeometry(element_id="FC-2", columns=(FT.ColumnStub("C1", 300.0, 300.0),))
    result = FT.design_combined_footing(geometry, [FT.FootingLoads(p_service_kn=500.0)], FT.SoilProfile(sbc_kpa=150.0))
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "combined footing inputs"
    assert result.checks  # a refusal is still a populated result
    assert any("exactly-two-column" in text for text in result.warnings)


# ---------------------------------------------------------------------------
# the strap case: referred out, pad still designed
# ---------------------------------------------------------------------------


def test_a_strap_pad_refers_the_beam_out_with_its_moment_balance():
    """A column 0.6 m off the pad centre with a 4 m strap: the balance
    R1 = P S / (S - e) = 600 x 4 / 3.4 = 705.9 kN, and the interior footing is
    relieved by P e / (S - e) = 600 x 0.6 / 3.4 = 105.9 kN."""
    geometry = FT.PadGeometry(
        element_id="F-boundary",
        column=FT.ColumnStub("C1", 300.0, 300.0),
        col_offset_x_m=0.6,
        kind="strap",
        strap_partner_id="F-interior",
        strap_span_m=4.0,
    )
    result = FT.design_footing(geometry, FT.FootingLoads(p_service_kn=600.0), FT.SoilProfile(sbc_kpa=180.0))
    referral = [item for item in result.referrals if item["action"] == "strap_required"]
    assert len(referral) == 1
    detail = referral[0]["detail"]
    assert detail["r1_service_kn"] == pytest.approx(705.88, rel=1e-3)
    assert detail["partner_relief_kn"] == pytest.approx(105.88, rel=1e-3)
    assert detail["strap_moment_knm"] == pytest.approx(360.0)
    assert detail["partner_footing_id"] == "F-interior"
    assert any("NOT designed" in text for text in result.warnings)
    # the pad itself is designed, on the raised reaction and a uniform pressure
    assert result.section["bx_mm"] > 0.0
    assert result.section["q_max_kpa"] == pytest.approx(result.section["q_min_kpa"])
    assert result.section["q_max_kpa"] == pytest.approx(
        705.88 / (C.mm_to_m(result.section["bx_mm"]) * C.mm_to_m(result.section["ly_mm"])), rel=1e-3
    )
    assert bars(result, "dowel")


def test_a_strap_with_no_usable_span_designs_the_pad_as_handed_over():
    geometry = FT.PadGeometry(
        element_id="F-boundary",
        column=FT.ColumnStub("C1", 300.0, 300.0),
        col_offset_x_m=0.6,
        kind="strap",
        strap_partner_id="F-interior",
        strap_span_m=0.0,
    )
    result = FT.design_footing(geometry, FT.FootingLoads(p_service_kn=600.0), FT.SoilProfile(sbc_kpa=180.0))
    assert any("strap geometry is unusable" in text for text in result.warnings)
    assert [item for item in result.referrals if item["action"] == "strap_required"]


def test_design_never_creates_or_merges_a_footing():
    """Finding 19: the designer sizes what placement handed it and nothing else.
    The only referral it may raise is the strap one, which asks for no new
    element, and a plain pad raises none at all."""
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert result.referrals == []
    assert "combine_footings" not in json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# contract: disclosure, determinism, serialization
# ---------------------------------------------------------------------------


def test_a_footing_that_cannot_be_designed_fails_without_raising():
    for loads in (FT.FootingLoads(p_service_kn=0.0), FT.FootingLoads(p_service_kn=-10.0)):
        result = FT.design_footing(pad(), loads, FT.SoilProfile(sbc_kpa=150.0))
        assert result.status == C.STATUS_FAIL
        assert result.governing_check == "service load"
        assert result.checks
        assert result.warnings

    broken = FT.design_footing(
        pad(column_mm=(0.0, 300.0)), FT.FootingLoads(p_service_kn=500.0), FT.SoilProfile(sbc_kpa=150.0)
    )
    assert broken.status == C.STATUS_FAIL
    assert broken.governing_check == "column section"


def test_an_impossible_joint_is_refused_by_the_clause_that_refuses_it():
    """2000 kN service on a 230 mm column is 56.7 MPa at the face: bearing plus
    the 6 percent of dowels IS 456 Cl 26.5.3.1 allows cannot carry it, and the
    failed row is the one that gets named, not the depth driver."""
    result = FT.design_footing(
        pad(column_mm=(230.0, 230.0)), FT.FootingLoads(p_service_kn=2000.0), FT.SoilProfile(sbc_kpa=200.0)
    )
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "dowel steel ratio"
    failed = [row for row in result.checks if row.status == C.CHECK_FAIL]
    assert [row.name for row in failed] == ["dowel steel ratio"]
    assert result.section["D_mm"] > 0.0  # still a fully populated result
    assert result.bars


def test_the_resize_history_reads_in_the_order_it_happened():
    geometry = FT.PadGeometry(
        element_id="F-order",
        column=FT.ColumnStub("C1", 600.0, 600.0),
        placed_bx_m=1.0,
        placed_ly_m=1.0,
        placed_depth_m=0.3,
    )
    result = FT.design_footing(geometry, FT.FootingLoads(p_service_kn=1200.0), FT.SoilProfile(sbc_kpa=300.0))
    reasons = [step["reason"] for step in result.resize_history]
    assert reasons[0].startswith("plan enlarged")
    assert reasons[1].startswith("depth set by")
    assert any(reason.startswith("depth increased for") for reason in reasons[2:])
    # every step names a real from and to
    for step in result.resize_history:
        assert step["from"] and step["to"] and step["from"] != step["to"]


def test_bar_count_puts_the_end_bars_one_cover_in():
    assert FT.bar_count(2500.0, 50.0, 200.0) == 13  # 2400 / 200 = 12 spaces
    assert FT.bar_count(1000.0, 50.0, 3000.0) == 2  # never fewer than two
    assert FT.bar_count(1800.0, 0.0, 150.0) == 13


def test_the_result_round_trips_through_its_dict():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    wire = result.to_dict()
    assert json.loads(json.dumps(wire)) == wire
    again = C.DesignResult.from_dict(wire)
    assert again.to_dict() == wire
    assert "quantities" not in wire  # finding 24: quantities.py owns the take-off
    assert wire["element_type"] == "footing"


def test_two_runs_of_the_same_input_give_the_same_dict():
    first = FT.design_footing(
        pad(column_mm=(300.0, 450.0)),
        FT.FootingLoads(p_service_kn=950.0, mx_service_knm=40.0),
        FT.SoilProfile(),
    ).to_dict()
    second = FT.design_footing(
        pad(column_mm=(300.0, 450.0)),
        FT.FootingLoads(p_service_kn=950.0, mx_service_knm=40.0),
        FT.SoilProfile(),
    ).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    geometry, loads = combined_pair()
    third = FT.design_combined_footing(geometry, loads, FT.SoilProfile(sbc_kpa=150.0)).to_dict()
    fourth = FT.design_combined_footing(geometry, loads, FT.SoilProfile(sbc_kpa=150.0)).to_dict()
    assert json.dumps(third, sort_keys=True) == json.dumps(fourth, sort_keys=True)


def test_the_trace_carries_the_clauses_the_checks_quote():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    ids = set(entry.clause_id for entry in result.trace)
    for ref in ("31.6.3", "40.1", "Table 19", "G-1.1(b)", "26.5.2.1", "34.4", "34.4.3", "26.2.1", "34.1.2"):
        assert "IS456:2000 " + ref in ids
    # the search itself is not in the trace: only the section that was adopted
    assert len([entry for entry in result.trace if entry.ref == "31.6.3"]) <= 2


def test_a_broken_context_is_disclosed_rather_than_raised():
    """The designer is the last thing between a bad payload and a 500: a grade
    the catalogue does not carry comes back as a failed result, not a traceback."""
    result = FT.design_footing(
        pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0), {"materials": {"fck": 27}}
    )
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "internal error"
    assert any("M27" in text or "27" in text for text in result.warnings)

    combined_geometry, combined_loads = combined_pair()
    broken = FT.design_combined_footing(combined_geometry, combined_loads, FT.SoilProfile(sbc_kpa=150.0), 42)
    assert broken.status == C.STATUS_FAIL
    assert broken.warnings


def test_a_combined_footing_records_the_change_from_the_placed_rectangle():
    columns = (
        FT.ColumnStub("C1", 300.0, 300.0, x_m=0.0, y_m=0.0),
        FT.ColumnStub("C2", 300.0, 300.0, x_m=4.0, y_m=0.0),
    )
    geometry = FT.CombinedGeometry(
        element_id="FC-placed", columns=columns, placed_bx_m=4.0, placed_ly_m=1.2, placed_depth_m=0.4
    )
    loads = [FT.FootingLoads(p_service_kn=600.0), FT.FootingLoads(p_service_kn=800.0)]
    result = FT.design_combined_footing(geometry, loads, FT.SoilProfile(sbc_kpa=150.0))
    assert result.status == C.STATUS_RESIZED
    assert any("resultant" in step["reason"] for step in result.resize_history)
    assert result.section["length_mm"] >= 4000.0 + 300.0 + 2.0 * FT.MIN_PROJECTION_MM


def test_a_combined_footing_offset_on_both_axes_says_what_it_designed():
    columns = (
        FT.ColumnStub("C1", 300.0, 300.0, x_m=0.0, y_m=0.0),
        FT.ColumnStub("C2", 300.0, 300.0, x_m=4.0, y_m=1.5),
    )
    result = FT.design_combined_footing(
        FT.CombinedGeometry(element_id="FC-skew", columns=columns),
        [FT.FootingLoads(p_service_kn=600.0), FT.FootingLoads(p_service_kn=600.0)],
        FT.SoilProfile(sbc_kpa=150.0),
    )
    assert any("offset on both axes" in text for text in result.warnings)
    assert result.section["longitudinal_axis"] == "x"


def test_the_units_boundary_converts_once_in_and_once_out():
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    for key in ("bx_mm", "ly_mm", "D_mm", "d_mm", "cover_mm"):
        assert key in result.section
    si = result.extras["si"]
    assert si["bx_m"] == pytest.approx(result.section["bx_mm"] / 1000.0)
    assert si["depth_m"] == pytest.approx(result.section["D_mm"] / 1000.0)
    # the pressure the soil block speaks stays in kPa, the concrete in MPa
    assert result.section["q_allow_kpa"] == 150.0
    assert result.section["qu_mpa"] < 1.0


def test_the_context_is_built_from_the_options_block():
    ctx = FT.FootingContext.coerce(
        {"materials": {"fck": 30, "fy": 415}, "exposure": "severe", "aggregate_mm": 20, "resize_policy": {"max_iters": 4}}
    )
    assert ctx.fck_mpa == 30.0
    assert ctx.fy_mpa == 415.0
    assert ctx.exposure == "severe"
    assert ctx.policy.max_iters == 4
    result = FT.design_footing(pad(), FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0), ctx)
    assert result.materials["fck_mpa"] == 30.0
    assert result.section["cover_mm"] == 50.0  # severe is 45, the earth face floor is 50


def test_the_designer_takes_the_call_the_rcc_package_dispatches():
    """`run_rcc_design` calls every member designer as (demands, geometry, ctx):
    the envelope, a plain geometry mapping in millimetres and the shared
    DesignContext all land in the right slots and design a footing."""
    from ..analysis import ForceEnvelope, StationForces
    from ..design.rcc import detailing

    envelope = ForceEnvelope(
        element_id="ftg-C1",
        element_type="footing",
        stations=(StationForces(station=0.0, n_max_kn=740.0, n_min_kn=520.0),),
    )
    geometry = {
        "element_id": "ftg-C1",
        "b_mm": 1500.0,
        "D_mm": 1500.0,
        "depth_mm": 400.0,
        "supports": ["C1"],
        "col_bx_mm": 300.0,
        "col_dy_mm": 300.0,
    }
    result = FT.design_footing(envelope, geometry, detailing.DesignContext())
    assert result.element_id == "ftg-C1"
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert result.materials["fck_mpa"] == 25.0
    assert result.section["bx_mm"] >= 1500.0
    assert result.bars

    # the column section has no default: a mapping without one is disclosed
    bare = dict(geometry)
    bare.pop("col_bx_mm")
    bare.pop("col_dy_mm")
    refused = FT.design_footing(envelope, bare, detailing.DesignContext())
    assert refused.status == C.STATUS_FAIL
    assert refused.governing_check == "column section"
    assert any("col_bx_mm" in text for text in refused.warnings)


def test_loads_come_off_a_footing_force_envelope():
    from ..analysis import ForceEnvelope, StationForces

    envelope = ForceEnvelope(
        element_id="ftg-C1",
        element_type="footing",
        stations=(StationForces(station=0.0, n_max_kn=740.0, n_min_kn=520.0),),
    )
    loads = FT.FootingLoads.from_envelope(envelope)
    assert loads.p_service_kn == 740.0
    assert loads.factored_p_kn() == pytest.approx(1110.0)
    with pytest.raises(ValueError):
        FT.FootingLoads.from_envelope(ForceEnvelope(element_id="b1", element_type="beam"))


def test_the_placed_size_is_the_starting_point_and_every_change_is_recorded():
    geometry = FT.PadGeometry(
        element_id="F-placed",
        column=FT.ColumnStub("C1", 300.0, 300.0),
        placed_bx_m=1.5,
        placed_ly_m=1.5,
        placed_depth_m=0.3,
    )
    result = FT.design_footing(geometry, FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert result.status == C.STATUS_RESIZED
    assert len(result.resize_history) >= 2
    assert result.resize_history[0]["from"] == "1500 mm x 1500 mm"
    assert result.resize_history[0]["to"] == "2500 mm x 2500 mm"
    assert any(step["from"] == "300 mm" for step in result.resize_history)


def test_a_generous_placed_depth_is_kept_rather_than_shaved():
    geometry = FT.PadGeometry(
        element_id="F-deep",
        column=FT.ColumnStub("C1", 300.0, 300.0),
        placed_depth_m=1.0,
    )
    result = FT.design_footing(geometry, FT.FootingLoads(p_service_kn=800.0), FT.SoilProfile(sbc_kpa=150.0))
    assert result.section["D_mm"] == 1000.0
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)


# ---------------------------------------------------------------------------
# the wall strip: a line load, a projection, and a plain or reinforced verdict
# ---------------------------------------------------------------------------


def strip(wall_t_mm=230.0, length_m=6.0, **kwargs):
    """A strip geometry under one wall run, thickness in millimetres for reading."""
    return FT.StripGeometry(
        element_id=kwargs.pop("element_id", "ftg-strip-w1"),
        wall_t_m=wall_t_mm / 1000.0,
        length_m=length_m,
        **kwargs
    )


def design_strip(n_kn_per_m, sbc_kpa, wall_t_mm=230.0, ctx=None, **kwargs):
    return FT.design_strip_footing(
        strip(wall_t_mm=wall_t_mm, **kwargs),
        FT.StripLoads(n_service_kn_per_m=n_kn_per_m),
        FT.SoilProfile(sbc_kpa=sbc_kpa),
        ctx,
    )


def test_a_lightly_loaded_wall_on_good_soil_is_a_plain_concrete_strip():
    """230 mm wall, 90 kN/m service, 200 kPa SBC, M25.

    width   B = 90 x 1.10 / 200 = 0.495 m, up to the 100 mm plan step = 500 mm
            (the geometric floor is 230 + 2 x 75 = 380 -> 400 mm, so bearing wins)
    project a = (500 - 230) / 2                                 = 135 mm
    pressure q = 90 / 0.500                                     = 180 kPa
    spread  Cl 34.1.3 k = 0.9 sqrt(100 x 0.180 / 25 + 1)
                        = 0.9 sqrt(1.72) = 0.9 x 1.311488       = 1.180339
            D >= 135 x 1.180339 = 159.35 mm, up to the 50 mm depth step = 200 mm
            200 mm is inside the 600 mm plain cap, so this is PLAIN concrete
    verdict a bearing check and a projection check, no steel at all
    """
    result = design_strip(90.0, 200.0)
    section = result.section
    assert result.status == C.STATUS_PASS
    assert section["verdict"] == FT.STRIP_VERDICT_PLAIN
    assert section["reinforced"] is False
    assert section["width_mm"] == 500.0
    assert section["width_driver"] == "bearing pressure"
    assert section["projection_mm"] == pytest.approx(135.0)
    assert section["q_service_kpa"] == pytest.approx(180.0)
    assert section["plain_spread_factor"] == pytest.approx(1.180339, rel=1e-5)
    assert section["plain_thickness_required_mm"] == 200.0
    assert section["D_mm"] == 200.0

    assert result.bars == [], "a plain concrete footing has no reinforcement to detail"
    assert result.stirrups == []
    names = [row.name for row in result.checks]
    assert names == ["bearing pressure", "plain concrete spread", "projection", "edge thickness"]
    assert rows(result)["plain concrete spread"].demand == pytest.approx(159.3458, rel=1e-5)
    assert rows(result)["plain concrete spread"].clause == "IS 456 Cl 34.1.3"
    assert result.governing_check == "bearing pressure"
    assert result.utilization_max == pytest.approx(0.9)
    assert any("plain concrete spread footing" in note for note in result.notes)


def test_a_heavily_loaded_wall_needs_a_reinforced_strip_and_gets_one():
    """300 mm wall, 320 kN/m service, 120 kPa SBC, M25 and Fe500.

    width   B = 320 x 1.10 / 120 = 2.933 m, up to the plan step   = 3000 mm
    project a = (3000 - 300) / 2                                  = 1350 mm
    pressure q = 320 / 3.000                                      = 106.667 kPa
    spread  k = 0.9 sqrt(100 x 0.106667 / 25 + 1) = 0.9 sqrt(1.426667)
                                                                  = 1.074988
            plain would need 1350 x 1.074988 = 1451 -> 1500 mm, past the 600 mm
            this design pours unreinforced, so the strip is REINFORCED
    pressure qu = 1.5 x 320 / 3.000 m                             = 160 kPa = 0.16 MPa
    moment  the Cl 34.2.3.2(b) section is at t/4 from the centreline, so the arm
            is 3000/2 - 300/4 = 1425 mm and
            Mu = 0.16 x 1425^2 / 2 x 1000                         = 162.45 kNm per m
    shear   at d from the wall FACE (Cl 34.2.4.1): with d = 445 mm,
            tau_v = 0.16 x (1350 - 445) / 445                     = 0.3254 MPa
    depth   d 445 + 50 cover + half a 10 mm bar                   = 500 mm
    """
    result = design_strip(320.0, 120.0, wall_t_mm=300.0)
    section = result.section
    assert result.status == C.STATUS_PASS
    assert section["verdict"] == FT.STRIP_VERDICT_RC
    assert section["reinforced"] is True
    assert section["width_mm"] == 3000.0
    assert section["projection_mm"] == pytest.approx(1350.0)
    assert section["plain_spread_factor"] == pytest.approx(1.074988, rel=1e-5)
    assert section["plain_thickness_required_mm"] == 1500.0
    assert section["plain_thickness_required_mm"] > section["plain_thickness_cap_mm"]
    assert section["D_mm"] == 500.0
    assert section["d_mm"] == pytest.approx(500.0 - 50.0 - 5.0)
    assert section["qu_mpa"] == pytest.approx(0.16, rel=1e-9)

    checks = rows(result)
    assert checks["flexure"].demand == pytest.approx(162.45e6, rel=1e-6)
    assert checks["flexure"].clause == "IS 456 Cl 34.2.3.2, G-1.1(b)"
    assert checks["one-way shear"].demand == pytest.approx(0.16 * (1350.0 - 445.0) / 445.0, rel=1e-6)
    assert checks["one-way shear"].clause.startswith("IS 456 Cl 34.2.4.1")
    assert result.governing_check == "one-way shear"
    assert all(row.status == C.CHECK_PASS for row in result.checks)

    roles = [bar["role"] for bar in result.bars]
    assert roles == ["strip_transverse_bottom", "strip_longitudinal_bottom"]
    main = bars(result, "strip_transverse_bottom")[0]
    dist = bars(result, "strip_longitudinal_bottom")[0]
    assert main["direction"] == "transverse" and main["face"] == "bottom"
    assert dist["direction"] == "longitudinal"
    assert main["ld_mm"] > 0.0 and dist["ld_mm"] > 0.0
    assert checks["steel transverse"].capacity >= checks["steel transverse"].demand
    assert checks["steel longitudinal"].demand == pytest.approx(
        is456.cl_26_5_2_1__min_slab_steel(500.0, 500.0, 1000.0)
    )
    assert dist["spacing_mm"] <= is456.cl_26_3_3__max_spacing_flexure("distribution", section["d_mm"], 500.0)


def test_the_projection_boundary_flips_the_verdict_and_nothing_else_changes():
    """The same 230 mm wall on the same 150 kPa ground, on each side of the cap.

    150 kN/m  B = 150 x 1.10 / 150 = 1.100 m exactly, a = (1100 - 230)/2 = 435 mm,
              q = 150 / 1.1 = 136.364 kPa, k = 0.9 sqrt(1.545455) = 1.118847,
              plain D >= 435 x 1.118847 = 486.7 -> 500 mm, INSIDE the 600 cap: plain
    200 kN/m  B = 200 x 1.10 / 150 = 1.467 -> 1500 mm, a = 635 mm,
              q = 200 / 1.5 = 133.333 kPa, k = 0.9 sqrt(1.533333) = 1.114451,
              plain D >= 635 x 1.114451 = 707.7 -> 750 mm, PAST the cap: reinforced,
              and the reinforced answer is 300 mm thick, less than half the plain one
    """
    plain = design_strip(150.0, 150.0)
    reinforced = design_strip(200.0, 150.0)

    assert plain.section["verdict"] == FT.STRIP_VERDICT_PLAIN
    assert plain.section["width_mm"] == 1100.0
    assert plain.section["projection_mm"] == pytest.approx(435.0)
    assert plain.section["plain_thickness_required_mm"] == 500.0
    assert plain.section["D_mm"] == 500.0
    assert plain.bars == []
    assert plain.governing_check == "plain concrete spread"

    assert reinforced.section["verdict"] == FT.STRIP_VERDICT_RC
    assert reinforced.section["width_mm"] == 1500.0
    assert reinforced.section["projection_mm"] == pytest.approx(635.0)
    assert reinforced.section["plain_thickness_required_mm"] == 750.0
    assert reinforced.section["D_mm"] == 300.0
    assert reinforced.bars

    # the cap is the only thing that moved between them, and it is stated on both
    assert plain.section["plain_thickness_cap_mm"] == FT.PLAIN_STRIP_MAX_THICKNESS_MM
    assert reinforced.section["plain_thickness_cap_mm"] == FT.PLAIN_STRIP_MAX_THICKNESS_MM
    assert plain.section["plain_thickness_required_mm"] <= FT.PLAIN_STRIP_MAX_THICKNESS_MM
    assert reinforced.section["plain_thickness_required_mm"] > FT.PLAIN_STRIP_MAX_THICKNESS_MM


def test_the_plain_cap_is_a_stated_convention_the_caller_can_move():
    """It is not a code number, so raising it keeps the same strip plain."""
    ctx = FT.FootingContext(plain_strip_max_thickness_mm=1000.0)
    moved = design_strip(200.0, 150.0, ctx=ctx)
    assert moved.section["verdict"] == FT.STRIP_VERDICT_PLAIN
    assert moved.section["D_mm"] == 750.0
    assert moved.bars == []

    from_options = FT.FootingContext.coerce({"plain_strip_max_thickness_mm": 1000.0})
    assert from_options.plain_strip_max_thickness_mm == 1000.0
    assert FT.FootingContext.coerce({}).plain_strip_max_thickness_mm == FT.PLAIN_STRIP_MAX_THICKNESS_MM


def test_the_plain_spread_factor_is_the_clause_and_never_relaxes_past_45_degrees():
    """0.9 sqrt(100 q / fck + 1), floored at 1.0 so D is never under the projection."""
    assert FT.plain_spread_factor(150.0, 25.0) == pytest.approx(0.9 * math.sqrt(100 * 0.15 / 25.0 + 1.0))
    assert FT.plain_spread_factor(250.0, 20.0) == pytest.approx(0.9 * math.sqrt(100 * 0.25 / 20.0 + 1.0))
    # the raw expression dips under 1.0 at a very low pressure; the floor holds
    assert 0.9 * math.sqrt(100 * 0.02 / 20.0 + 1.0) < 1.0
    assert FT.plain_spread_factor(20.0, 20.0) == 1.0
    # and it rises with pressure and falls with concrete grade, both monotone
    assert FT.plain_spread_factor(200.0, 25.0) > FT.plain_spread_factor(100.0, 25.0)
    assert FT.plain_spread_factor(200.0, 30.0) < FT.plain_spread_factor(200.0, 25.0)


def test_the_bending_section_is_the_masonry_one_not_the_wall_face():
    """IS 456 Cl 34.2.3.2(b): halfway between the wall centreline and its face.

    That puts the section a quarter of the wall thickness from the centre, so the
    arm out to the edge is the face projection PLUS t/4, and the moment is bigger
    than the concrete-wall rule in (a) would give. On the 300 mm wall above:
    face projection 1350 mm, bending arm 1425 mm, ratio 1425/1350 = 1.0556.
    """
    assert FT._strip_flexure_arm_mm(3000.0, 300.0) == pytest.approx(1425.0)
    assert FT._strip_face_arm_mm(3000.0, 300.0) == pytest.approx(1350.0)
    assert FT._strip_flexure_arm_mm(3000.0, 300.0) - FT._strip_face_arm_mm(3000.0, 300.0) == pytest.approx(75.0)

    # the concrete-wall form of the same clause is deliberately the shorter arm
    assert is456.cl_34_2_3_2__bending_section(3000.0, 300.0) == pytest.approx(1350.0)

    result = design_strip(320.0, 120.0, wall_t_mm=300.0)
    at_face = 1000.0 * 0.16 * 1350.0 * 1350.0 / 2.0
    assert rows(result)["flexure"].demand > at_face, "the masonry section carries the larger moment"


def test_the_width_comes_from_the_line_load_and_the_self_weight_allowance():
    """Halve the ground and the strip doubles; the pressure never passes the SBC."""
    firm = design_strip(120.0, 200.0)
    soft = design_strip(120.0, 100.0)
    assert soft.section["width_mm"] > firm.section["width_mm"]
    for result in (firm, soft):
        assert result.section["q_service_kpa"] <= result.section["q_allow_kpa"] + 1e-9

    plan = FT.size_strip(120.0, 230.0, FT.SoilProfile(sbc_kpa=200.0), FT.FootingContext(), length_mm=6000.0)
    assert plan.width_mm == pytest.approx(700.0)  # 120 x 1.10 / 200 = 0.66 m -> 700 mm
    assert plan.driver == "bearing pressure"
    bare = FT.size_strip(120.0, 230.0, FT.SoilProfile(sbc_kpa=200.0), FT.FootingContext(self_weight_allowance=0.0), length_mm=6000.0)
    assert bare.width_mm == pytest.approx(600.0)  # 120 / 200 = 0.60 m exactly


def test_a_strip_never_narrows_past_its_wall_or_past_the_placed_width():
    """Two floors under the bearing width, and neither is a code rule pretending to be one."""
    tiny = design_strip(5.0, 300.0)
    assert tiny.section["width_mm"] == pytest.approx(
        C.round_up_mm(230.0 + 2.0 * FT.MIN_STRIP_PROJECTION_MM, 100.0)
    )
    assert tiny.section["width_driver"] == "minimum projection"
    assert tiny.section["projection_mm"] >= FT.MIN_STRIP_PROJECTION_MM

    generous = FT.design_strip_footing(
        strip(placed_width_m=1.2),
        FT.StripLoads(n_service_kn_per_m=90.0),
        FT.SoilProfile(sbc_kpa=200.0),
    )
    assert generous.section["width_mm"] == 1200.0, "a placed width that covers the demand is kept exactly"
    assert generous.section["width_driver"] == "the placed width"
    assert generous.resize_history == []

    narrow = FT.design_strip_footing(
        strip(placed_width_m=0.45),
        FT.StripLoads(n_service_kn_per_m=90.0),
        FT.SoilProfile(sbc_kpa=200.0),
    )
    assert narrow.status == C.STATUS_RESIZED
    assert narrow.section["width_mm"] == 500.0
    assert narrow.resize_history[0]["from"] == "450 mm"
    assert narrow.resize_history[0]["to"] == "500 mm"


def test_a_strip_with_no_wall_or_no_load_is_refused_by_name():
    """A strip designed against an invented wall or load is a wrong number."""
    no_wall = FT.design_strip_footing(
        FT.StripGeometry(element_id="ftg-strip-bare", length_m=6.0),
        FT.StripLoads(n_service_kn_per_m=90.0),
        FT.SoilProfile(sbc_kpa=200.0),
    )
    assert no_wall.status == C.STATUS_FAIL
    assert no_wall.governing_check == "wall section"
    assert any("wall_t_m" in text for text in no_wall.warnings)
    assert not no_wall.bars

    no_load = design_strip(0.0, 200.0)
    assert no_load.status == C.STATUS_FAIL
    assert no_load.governing_check == "service load"
    assert not no_load.bars


def test_the_strip_loads_come_off_the_takedown_wall_ledger():
    """`footing_loads["walls"][id]` is dead plus REDUCED imposed, per metre run."""
    row = {"n_dl_kn_m": 40.0, "n_ll_raw_kn_m": 18.0, "n_ll_kn_m": 12.0, "floors_carried": 2.0}
    loads = FT.StripLoads.from_wall_ledger(row, "wall-s0-h-0-0")
    assert loads.n_service_kn_per_m == pytest.approx(52.0)
    assert loads.factored_kn_per_m() == pytest.approx(78.0)
    assert loads.wall_id == "wall-s0-h-0-0"
    assert FT.StripLoads.from_wall_ledger(52.0).n_service_kn_per_m == pytest.approx(52.0)
    assert FT.StripLoads(n_service_kn_per_m=52.0, nu_kn_per_m=70.0).factored_kn_per_m() == 70.0


def test_the_strip_geometry_reads_the_placer_and_the_model_the_same_way():
    """The placer's StripFooting and the model's Footing give the same geometry.

    Which of the model rectangle's two dimensions is the WIDTH is decided by the
    wall's own direction, never by which number is smaller: a short heavily
    loaded run is legitimately wider than it is long.
    """
    from ..design import rcc

    class _Placed(object):
        id = "ftg-strip-wall-a"
        wall_ids = ["wall-a"]
        orient = "h"
        width_m = 0.6
        wall_t_m = 0.23
        eccentric = False

        def length_m(self):
            return 9.0

    from_placer = FT.StripGeometry.from_strip_footing(_Placed())
    assert from_placer.wall_t_m == 0.23
    assert from_placer.placed_width_m == 0.6
    assert from_placer.length_m == 9.0

    class _Wall(object):
        id = "wall-a"
        a = (0.0, 6.0)
        b = (9.0, 6.0)
        thickness_m = 0.23

    class _ModelFooting(object):
        id = "ftg-strip-wall-a"
        supports = ["wall-a"]
        w_m = 9.0
        h_m = 0.6
        depth_m = 1.5  # the FOUNDING depth, not a thickness, and never read as one

    from_model = rcc.strip_geometry_from_model(_ModelFooting(), {"wall-a": _Wall()})
    assert from_model.wall_t_m == 0.23
    assert from_model.placed_width_m == pytest.approx(0.6)
    assert from_model.length_m == pytest.approx(9.0)
    assert from_model.orient == "h"

    class _WallV(_Wall):
        a = (6.0, 0.0)
        b = (6.0, 9.0)

    class _ModelFootingV(_ModelFooting):
        w_m = 0.6
        h_m = 9.0

    turned = rcc.strip_geometry_from_model(_ModelFootingV(), {"wall-a": _WallV()})
    assert turned.orient == "v"
    assert turned.placed_width_m == pytest.approx(0.6)
    assert turned.length_m == pytest.approx(9.0)

    # a short wide run: the wall still decides, so the 2.4 m width is not read as
    # a 1.2 m one just because 1.2 is the smaller number
    class _ModelFootingWide(_ModelFooting):
        w_m = 1.2
        h_m = 2.4

    wide = rcc.strip_geometry_from_model(_ModelFootingWide(), {"wall-a": _Wall()})
    assert wide.placed_width_m == pytest.approx(2.4)
    assert wide.length_m == pytest.approx(1.2)


def test_a_strip_result_round_trips_and_repeats_itself():
    result = design_strip(320.0, 120.0, wall_t_mm=300.0)
    back = C.DesignResult.from_dict(result.to_dict())
    assert back.to_dict() == result.to_dict()
    again = design_strip(320.0, 120.0, wall_t_mm=300.0)
    assert json.dumps(again.to_dict(), sort_keys=True) == json.dumps(result.to_dict(), sort_keys=True)
    assert json.dumps(result.to_dict())  # the whole thing is JSON, no NaN and no inf


def test_the_strip_designer_never_raises_and_takes_the_dispatch_call():
    """A broken context is disclosed, and mappings land in the right slots."""
    broken = FT.design_strip_footing(strip(), FT.StripLoads(n_service_kn_per_m=90.0), None, object())
    assert broken.status == C.STATUS_FAIL
    assert any("internal error" in text for text in broken.warnings)

    result = FT.design_strip_footing(
        {"element_id": "ftg-strip-map", "wall_t_mm": 230.0, "length_mm": 6000.0},
        {"n_dl_kn_m": 70.0, "n_ll_kn_m": 20.0},
        {"sbc_kpa": 200.0},
        {"materials": {"fck": 25, "fy": 500}},
    )
    assert result.element_id == "ftg-strip-map"
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert result.section["width_mm"] == 500.0
    assert result.materials["fck_mpa"] == 25.0
