"""Pins for RC beam design and the detailing engine it shares.

The flexure and shear vectors are worked by hand in the SP 16 style and the
arithmetic is written out in each test docstring, so a reader can check the
engine against a calculator rather than against itself. Every hand number is
taken at the effective depth the cover stack actually produces (Table 16
moderate cover 30 mm, an 8 mm stirrup, half the chosen bar), not at a round
figure, because that is the depth the design uses.

Beyond the vectors: the resize ladder reaches every status the contract names,
a beam that cannot be made to work still comes back fully populated, results are
byte for byte deterministic, and every check row cites a clause that is really
in the clause registry.
"""

from __future__ import annotations

import json
import math

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests, and an absolute GPLAN.structural
# import would resolve against the outer directory instead.
from ..analysis import BeamForces, ForceEnvelope, StationForces, to_beam_forces
from ..codes import is13920, is456
from ..codes.trace import CLAUSE_REGISTRY
from ..design import common as C
from ..design.rcc import beams
from ..design.rcc import detailing as D


# ---------------------------------------------------------------------------
# fixtures: two material contexts, one non-seismic, one ductile
# ---------------------------------------------------------------------------


def m20_fe415(**kwargs):
    """M20 with Fe415 in zone II: no ductile overlay, the SP 16 vector case."""
    options = dict(
        concrete=C.Concrete(fck_mpa=20.0),
        steel=C.RebarSteel(fy_mpa=415.0),
        zone="II",
        frame="OMRF",
    )
    options.update(kwargs)
    return D.DesignContext(**options)


def m25_fe500_ductile(**kwargs):
    """M25 with Fe500 in zone V on a special moment frame: overlay on."""
    options = dict(
        concrete=C.Concrete(fck_mpa=25.0),
        steel=C.RebarSteel(fy_mpa=500.0),
        zone="V",
        frame="SMRF",
    )
    options.update(kwargs)
    return D.DesignContext(**options)


def station(result, name):
    for row in result.extras["flexure"]:
        if row["station"] == name:
            return row
    raise AssertionError("no station " + name + " in " + repr([r["station"] for r in result.extras["flexure"]]))


def check(result, name):
    for row in result.checks:
        if row.name == name:
            return row
    raise AssertionError("no check " + name + " in " + repr([row.name for row in result.checks]))


def has_check(result, name):
    return any(row.name == name for row in result.checks)


def role_area_mm2(result, role):
    return sum(
        float(bar["count"]) * C.bar_area_mm2(float(bar["dia_mm"]))
        for bar in result.bars
        if bar.get("role") == role
    )


# ---------------------------------------------------------------------------
# worked vector 1: singly reinforced, 230 x 450, M20, Fe415, 100 kNm
# ---------------------------------------------------------------------------


def test_singly_reinforced_sp16_vector():
    """230 x 450 overall, M20, Fe415, Mu = 100 kNm sagging, by hand.

    Cover stack: Table 16 moderate 30 mm + 8 mm stirrup + half a 20 mm bar, so
    d = 450 - 30 - 8 - 10 = 402 mm.

    xu,max/d = 0.0035 / (0.0055 + 0.87 x 415 / 200000) = 0.47911
    K = 0.36 x 0.47911 x (1 - 0.42 x 0.47911) = 0.13777
    Mu,lim = 0.13777 x 20 x 230 x 402^2 = 102.4 kNm, above the 100 kNm demand,
    so the section is singly reinforced.

    4.6 Mu / (fck b d^2) = 460e6 / (20 x 230 x 161604) = 0.61880
    Ast = 0.5 (20/415) (1 - sqrt(1 - 0.61880)) x 230 x 402
        = 0.02410 x 0.38258 x 92460 = 852 mm2

    The catalogue answer is 2-20 + 2-12 = 628.3 + 226.2 = 854.5 mm2, which is
    the smallest area band that covers 852 mm2 and fits the 154 mm between the
    stirrup legs.
    """
    result = beams.design_beam(
        BeamForces(
            mu_hog_end_a_knm=0.0,
            mu_hog_end_b_knm=0.0,
            mu_sag_mid_knm=100.0,
            vu_a_kn=80.0,
            vu_b_kn=80.0,
        ),
        beams.BeamGeometry(b_mm=230.0, D_mm=450.0, span_mm=5000.0, support="ss", element_id="beam-sp16"),
        m20_fe415(),
    )

    assert result.status == C.STATUS_PASS
    assert result.resize_history == []
    assert result.section["b_mm"] == 230.0
    assert result.section["D_mm"] == 450.0
    assert result.section["cover_mm"] == 30.0
    assert result.section["d_mm"] == pytest.approx(402.0)

    mid = station(result, "bottom_mid")
    assert mid["mu_lim_nmm"] == pytest.approx(102.4e6, rel=0.005)
    assert mid["ast_req_mm2"] == pytest.approx(852.0, rel=0.005)
    assert mid["ast_prov_mm2"] == pytest.approx(854.52, rel=1e-4)
    assert mid["ast_prov_mm2"] >= mid["ast_req_mm2"]
    assert mid["doubly"] is False
    row = check(result, "flexure_bottom_mid")
    assert row.demand == pytest.approx(100e6)
    assert row.capacity >= row.demand
    assert row.status == C.CHECK_PASS

    # Every bottom bar runs the full span and carries its own Ld (finding 24).
    bottom = [bar for bar in result.bars if bar["role"] == "bottom_mid"]
    assert bottom, "the beam has bottom steel"
    assert sum(bar["count"] * C.bar_area_mm2(bar["dia_mm"]) for bar in bottom) == pytest.approx(854.52, rel=1e-4)
    for bar in bottom:
        assert bar["zone_mm"] == [0.0, 5000.0]
        assert bar["ld_mm"] == pytest.approx(is456.cl_26_2_1__ld(bar["dia_mm"], 415.0, 20.0))

    # Ld for a 20 mm Fe415 bar in M20: tau_bd = 1.2 x 1.6 = 1.92,
    # Ld = 20 x 0.87 x 415 / (4 x 1.92) = 940 mm, 47 diameters.
    twenty = [bar for bar in bottom if bar["dia_mm"] == 20.0]
    assert twenty and twenty[0]["ld_mm"] == pytest.approx(940.1, rel=0.002)


def test_cover_is_re_resolved_against_the_selected_main_bar():
    """B18: Cl 26.4.1 makes mild-exposure cover follow a 25 mm beam bar.

    The initial Table 16 cover is 20 mm before flexure chooses a bar. This
    300 x 600 beam needs a 25 mm longitudinal bar, so its delivered cover must
    be re-resolved to 25 mm and the effective depth must be based on that
    second pass. Before the re-resolve, this same result retained 20 mm cover.
    """
    result = beams.design_beam(
        BeamForces(240.0, 240.0, 240.0, 100.0, 100.0),
        beams.BeamGeometry(300.0, 600.0, 5000.0, "continuous", element_id="beam-cover-diameter"),
        m25_fe500_ductile(exposure="mild", zone="II", frame="OMRF"),
    )

    main_dia = max(
        bar["dia_mm"] for bar in result.bars if bar["role"] in ("top_left", "top_right", "bottom_mid")
    )
    assert main_dia == 25.0
    assert result.section["cover_mm"] == C.resolve_cover("beam", "mild", 0.0, main_dia).cover_mm
    assert result.section["cover_mm"] >= main_dia
    assert result.section["d_mm"] == pytest.approx(600.0 - 25.0 - 8.0 - 0.5 * main_dia)


def test_min_and_max_steel_rows_are_the_is456_clauses():
    """Cl 26.5.1.1: 0.85 b d / fy at the bottom, 0.04 bD as the ceiling."""
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 100.0, 80.0, 80.0),
        beams.BeamGeometry(230.0, 450.0, 5000.0, "ss"),
        m20_fe415(),
    )
    minimum = check(result, "min_steel_bottom_mid")
    assert minimum.demand == pytest.approx(is456.cl_26_5_1_1__min_tension_steel(230.0, 402.0, 415.0))
    assert minimum.demand == pytest.approx(0.85 * 230.0 * 402.0 / 415.0, rel=1e-9)
    ceiling = check(result, "max_steel_bottom_mid")
    assert ceiling.capacity == pytest.approx(0.04 * 230.0 * 450.0)
    assert ceiling.status == C.CHECK_PASS


# ---------------------------------------------------------------------------
# worked vector 2: doubly reinforced after the depth cap
# ---------------------------------------------------------------------------


def test_doubly_reinforced_after_the_depth_cap():
    """230 x 400 asked for 220 kNm on a 4.0 m span: depth first, then Asc.

    The policy cap is max(1.5 x 400, 4000/8) = 600 mm, so the ladder adds
    25 mm at a time from 400 to 600 and only then turns to compression steel.

    At D = 600 with 32 mm bottom bars, d = 600 - 30 - 8 - 16 = 546 mm and
    Mu,lim = 0.13777 x 20 x 230 x 546^2 = 188.9 kNm, short of 220 kNm, so
    Mu2 = 31.1 kNm has to be carried by a compression couple:
    d' = 30 + 8 + 6 = 44 mm, d'/d = 0.081, fsc = 353.8 MPa (SP 16 Table F),
    Asc = 31.1e6 / ((353.8 - 0.446 x 20) x (546 - 44)) = 180 mm2, which the
    catalogue rounds up to the smallest pair that fits.
    """
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 220.0, 90.0, 90.0),
        beams.BeamGeometry(230.0, 400.0, 4000.0, "continuous", element_id="beam-doubly"),
        m20_fe415(),
    )

    assert result.status == C.STATUS_RESIZED
    assert result.section["D_mm"] == 600.0, "the ladder stops at the depth cap"
    assert 540.0 <= result.section["d_mm"] <= 555.0

    depth_steps = [step for step in result.resize_history if "D_mm" in step["from"]]
    assert len(depth_steps) == 8, "400 to 600 in 25 mm steps"
    assert depth_steps[0]["from"]["D_mm"] == 400.0
    assert depth_steps[-1]["to"]["D_mm"] == 600.0
    assert all("flexure" in step["reason"] for step in depth_steps)

    doubly_step = [step for step in result.resize_history if "doubly_reinforced" in step["from"]]
    assert len(doubly_step) == 1, "compression steel is a disclosed ladder step of its own"
    assert "cap" in doubly_step[0]["reason"]

    mid = station(result, "bottom_mid")
    assert mid["doubly"] is True
    assert mid["mu_lim_nmm"] == pytest.approx(188.9e6, rel=0.01)
    assert mid["asc_req_mm2"] > 0.0
    assert mid["asc_prov_mm2"] >= mid["asc_req_mm2"]

    compression = [bar for bar in result.bars if bar["role"] == "top_mid"]
    assert compression, "the compression steel is detailed as full length top bars"
    assert check(result, "flexure_bottom_mid").status == C.CHECK_PASS
    assert check(result, "flexure_bottom_mid").clause == "IS456:2000 G-1.2"


# ---------------------------------------------------------------------------
# worked vector 3: shear
# ---------------------------------------------------------------------------


def test_shear_needs_designed_stirrups_not_only_the_minimum():
    """230 x 500, Vu = 150 kN each end: the ends carry designed stirrups.

    d = 500 - 30 - 8 - 8 = 454 mm with 16 mm bars.
    tau_v = 150000 / (230 x 454) = 1.44 MPa, under the M20 Table 20 cap of
    2.8 MPa, so the section is legal and the stirrups do the rest.
    Vus = Vu - tau_c b d with tau_c from Table 19 at the pt actually provided,
    Asv/sv = Vus / (0.87 x 415 x 454), and a two legged 8 mm stirrup
    (100.5 mm2) at that pitch is what the catalogue offers first.
    """
    result = beams.design_beam(
        BeamForces(60.0, 60.0, 80.0, 150.0, 150.0),
        beams.BeamGeometry(230.0, 500.0, 4500.0, "continuous", element_id="beam-shear"),
        m20_fe415(),
    )
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)

    end = result.extras["shear"][0]
    assert end["tau_v_mpa"] == pytest.approx(150000.0 / (230.0 * end["d_mm"]), rel=1e-9)
    assert end["tau_c_max_mpa"] == 2.8
    assert end["tau_c_mpa"] == pytest.approx(is456.table_19__tau_c(end["pt_pct"], 20.0))
    assert end["vus_n"] > 0.0, "the concrete alone does not carry this shear"

    asv_per_mm = is456.cl_40_4__vertical_stirrups(end["vus_n"], 415.0, end["d_mm"])
    assert end["stirrups"]["asv_per_mm_req"] == pytest.approx(
        max(asv_per_mm, is456.cl_26_5_1_6__min_stirrups(230.0, 415.0))
    )
    assert end["stirrups"]["spacing_mm"] < end["stirrups"]["max_spacing_mm"], "tighter than the maximum"
    assert end["stirrups"]["spacing_mm"] % 5.0 == 0.0, "spacings round down to a 5 mm module"
    assert check(result, "stirrups_a").status == C.CHECK_PASS

    # Three zones: a tighter 2d end zone at each end, the maximum spacing between.
    zones = result.stirrups
    assert len(zones) == 3
    assert zones[0]["zone_mm"][0] == 0.0
    assert zones[-1]["zone_mm"][1] == 4500.0
    assert zones[0]["spacing_mm"] < zones[1]["spacing_mm"]
    assert zones[0]["zone_mm"][1] == pytest.approx(2.0 * result.extras["shear"][0]["d_mm"])


def test_table_20_cap_is_a_section_failure_and_resizes_the_beam():
    """Vu = 300 kN on 230 x 400 M20: tau_v = 3.7 MPa, over the 2.8 MPa cap.

    300000 / (230 x 354) = 3.69 MPa at the placed depth. No amount of shear
    steel is allowed past Table 20, so the ladder deepens the section until
    tau_v falls under 2.8: b d >= 300000 / 2.8 = 107143 mm2, so d >= 466 mm
    and D >= 466 + 30 + 8 + 8 = 512, which the 25 mm ladder reaches at 525.
    """
    trial_depth = 400.0 - 30.0 - 8.0 - 8.0
    assert 300000.0 / (230.0 * trial_depth) > is456.table_20__tau_c_max(20.0)

    result = beams.design_beam(
        BeamForces(60.0, 60.0, 80.0, 300.0, 300.0),
        beams.BeamGeometry(230.0, 400.0, 4000.0, "continuous", element_id="beam-cap"),
        m20_fe415(),
    )
    assert result.status == C.STATUS_RESIZED
    assert result.section["D_mm"] == 525.0
    reasons = [step["reason"] for step in result.resize_history]
    assert any("Table 20" in reason and "section limit" in reason for reason in reasons)

    for name in ("shear_stress_a", "shear_stress_b"):
        row = check(result, name)
        assert row.capacity == 2.8
        assert row.status == C.CHECK_PASS
        assert row.demand <= 2.8


def test_b17_supplied_interior_shear_designs_and_checks_the_middle_cage():
    """B17: the station just outside 2d needs more than minimum stirrups.

    On this 230 x 450 M25/Fe500 beam the delivered d is 406 mm, so 2d is
    812 mm.  Analysis supplies Vu = 119 kN at x = 820 mm, outside that end
    zone.  With 2-12 bottom bars, pt = 0.2422 percent and tau_c = 0.3598 MPa:

      Vus = 119000 - 0.3598 x 230 x 406 = 85404 N
      Asv/s = 85404 / (0.87 x 500 x 406) = 0.4836 mm2/mm

    Two-leg 8 mm stirrups therefore need 205 mm pitch.  The old path discarded
    this station, emitted no stirrups_middle row and left 8 mm at 300 mm.
    """
    envelope = ForceEnvelope(
        element_id="beam-middle-shear",
        element_type="beam",
        stations=(
            StationForces(station=0.0, v_max_kn=200.0),
            StationForces(station=0.205, v_max_kn=119.0),
            StationForces(station=0.5, v_max_kn=0.0),
            StationForces(station=1.0, v_max_kn=200.0),
        ),
    )
    forces = to_beam_forces(envelope)
    assert forces.shear_stations == (
        (0.0, 200.0),
        (0.205, 119.0),
        (0.5, 0.0),
        (1.0, 200.0),
    )

    result = beams.design_beam(
        forces,
        beams.BeamGeometry(230.0, 450.0, 4000.0, "continuous", element_id="beam-middle-shear"),
        m25_fe500_ductile(zone="II", frame="OMRF"),
    )
    d_mm = result.section["d_mm"]
    assert d_mm == pytest.approx(406.0)
    bottom_area = role_area_mm2(result, "bottom_mid")
    pt_pct = 100.0 * bottom_area / (230.0 * d_mm)
    tau_c_mpa = is456.table_19__tau_c(pt_pct, 25.0)
    expected_vus = 119000.0 - tau_c_mpa * 230.0 * d_mm
    expected_asv = expected_vus / (0.87 * 500.0 * d_mm)

    row = check(result, "stirrups_middle")
    assert row.demand == pytest.approx(expected_asv)
    assert row.capacity >= row.demand
    assert 119000.0 / (230.0 * d_mm) < is456.table_20__tau_c_max(25.0)
    old_minimum = D.choose_stirrups(
        is456.cl_26_5_1_6__min_stirrups(230.0, 500.0),
        is456.cl_26_5_1_5__max_stirrup_spacing(d_mm),
    )
    assert old_minimum.spacing_mm == 300.0
    assert old_minimum.asv_per_mm_prov < row.demand
    middle_zone = [zone for zone in result.stirrups if zone["zone_mm"][0] < 820.0 < zone["zone_mm"][1]][0]
    assert middle_zone["spacing_mm"] == 205.0
    assert not any("end shears only" in note for note in result.notes)


# ---------------------------------------------------------------------------
# worked vector 4: serviceability
# ---------------------------------------------------------------------------


def test_deflection_governs_a_shallow_beam_and_is_recorded_as_a_resize():
    """5.0 m span on a 250 mm deep beam: span/d fails Cl 23.2.1 before anything else.

    d = 250 - 30 - 8 - 6 = 206 mm with 12 mm bars, so span/d = 24.3 against a
    simply supported basic 20 times the Fig 4 tension factor. The moment is
    small, so the ladder is driven by deflection alone and the reason recorded
    in resize_history says so.
    """
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 20.0, 30.0, 30.0),
        beams.BeamGeometry(230.0, 250.0, 5000.0, "ss", element_id="beam-shallow"),
        m20_fe415(),
    )
    assert result.status == C.STATUS_RESIZED
    assert result.section["D_mm"] > 250.0
    assert result.resize_history, "the resize is disclosed, not silent"
    assert all("span over effective depth" in step["reason"] for step in result.resize_history)

    service = result.extras["serviceability"]
    assert service["basic"] == 20.0, "simply supported"
    assert service["mf_tension"] == pytest.approx(is456.fig_4__mf_tension(service["fs_mpa"], service["pt_pct"]))
    assert service["long_span_factor"] == 1.0, "5 m is inside the 10 m rule"
    assert service["span_over_d"] <= service["allowed"] + 1e-9
    assert check(result, "span_over_depth").status == C.CHECK_PASS


def test_cantilever_uses_the_seven_rule_and_reports_a_span_placement_should_have_refused():
    """Cl 23.2.1 basic l/d is 7 for a cantilever, and 2.5 m is the placement cap."""
    ok = beams.design_beam(
        BeamForces(40.0, 0.0, 0.0, 45.0, 5.0),
        beams.BeamGeometry(230.0, 450.0, 2000.0, "cantilever", element_id="beam-cant"),
        m20_fe415(),
    )
    assert ok.extras["serviceability"]["basic"] == 7.0
    assert ok.extras["serviceability"]["long_span_factor"] == 1.0
    assert not any("E_CANTILEVER_SPAN" in text for text in ok.warnings)
    top = [bar for bar in ok.bars if bar["role"] == "top_left"]
    assert top and all(bar["zone_mm"] == [0.0, 2000.0] for bar in top), "hogging steel runs the full length"
    assert not has_check(ok, "flexure_top_right"), "one root, one set of rows"

    long_one = beams.design_beam(
        BeamForces(40.0, 0.0, 0.0, 45.0, 5.0),
        beams.BeamGeometry(230.0, 450.0, 3000.0, "cantilever", element_id="beam-cant-long"),
        m20_fe415(),
    )
    assert any("E_CANTILEVER_SPAN" in text for text in long_one.warnings)
    assert any("2500" in text for text in long_one.warnings)


def test_b16_support_reaches_the_rcc_dispatch_and_the_api_dispatch():
    """B16: placement kind and analysed end continuity reach both call sites.

    The cantilever must take basic l/d 7 and full-length top steel.  The
    ordinary beam has zero hogging at both ends, so it is simply supported and
    takes basic l/d 20.  Before B16 both dispatches omitted `support`, making
    both sections silently continuous at basic l/d 26.
    """
    from types import SimpleNamespace

    from .. import api as structural_api
    from .. import model as M
    from ..design import rcc

    cantilever = M.Beam(
        id="beam-support-cant",
        storey=0,
        a=(0.0, 0.0),
        b=(2.0, 0.0),
        width_m=0.23,
        depth_m=0.45,
        kind=M.BeamKind.CANTILEVER,
    )
    simple = M.Beam(
        id="beam-support-ss",
        storey=0,
        a=(0.0, 1.0),
        b=(4.0, 1.0),
        width_m=0.23,
        depth_m=0.45,
        kind=M.BeamKind.PRIMARY,
    )
    envelopes = {
        cantilever.id: ForceEnvelope(
            element_id=cantilever.id,
            element_type="beam",
            stations=(
                StationForces(station=0.0, m_neg_min_knm=-40.0, v_max_kn=45.0),
                StationForces(station=0.5, v_max_kn=20.0),
                StationForces(station=1.0, v_max_kn=5.0),
            ),
        ),
        simple.id: ForceEnvelope(
            element_id=simple.id,
            element_type="beam",
            stations=(
                StationForces(station=0.0, v_max_kn=60.0),
                StationForces(station=0.5, m_pos_max_knm=60.0, v_max_kn=0.0),
                StationForces(station=1.0, v_max_kn=60.0),
            ),
        ),
    }
    model = M.StructuralModel(id="beam-support-routing", beams=[cantilever, simple])
    analysis = SimpleNamespace(envelopes=envelopes, footing_loads={})
    design_options = {
        "materials": {"fck": 25.0, "fy": 500.0},
        "seismic": {"zone": "II", "frame": "OMRF"},
    }

    rcc_results = {
        result.element_id: result
        for result in rcc.run_rcc_design(model, analysis, design_options)
    }
    assert rcc_results[cantilever.id].section["support"] == "cantilever"
    assert rcc_results[cantilever.id].extras["serviceability"]["basic"] == 7.0
    assert rcc_results[simple.id].section["support"] == "ss"
    assert rcc_results[simple.id].extras["serviceability"]["basic"] == 20.0

    class _Options(object):
        soil = {}

        @staticmethod
        def design_options():
            return dict(design_options)

    api_results = {
        result.element_id: result
        for result in structural_api._design_members(
            model,
            analysis,
            None,
            _Options(),
            "rc_frame",
            M.DisclosureLog(),
        )
    }
    assert api_results[cantilever.id].section["support"] == "cantilever"
    assert api_results[cantilever.id].extras["serviceability"]["basic"] == 7.0
    assert api_results[simple.id].section["support"] == "ss"
    assert api_results[simple.id].extras["serviceability"]["basic"] == 20.0


# ---------------------------------------------------------------------------
# worked vector 5: the ductile overlay
# ---------------------------------------------------------------------------


def test_capacity_shear_governs_over_the_analysis_shear_in_a_ductile_frame():
    """IS 13920 Cl 6.3.3 on a 300 x 500, 3.7 m clear span, zone V SMRF beam.

    The analysis shear is 80 kN. The provided steel gives hogging and sagging
    capacities Mu,A and Mu,B at the faces, and the sway term is
    1.4 (Mu,A + Mu,B) / L_clear, which for capacities of roughly 121 and 94 kNm
    over 3.7 m is about 81 kN. The design shear is therefore about 161 kN, over
    twice the analysis value, and the hoops are designed for it.
    """
    ctx = m25_fe500_ductile()
    geom = beams.BeamGeometry(300.0, 500.0, 4000.0, "continuous", clear_span_mm=3700.0, element_id="beam-ductile")
    result = beams.design_beam(BeamForces(120.0, 120.0, 90.0, 80.0, 80.0), geom, ctx)

    assert D.ductile_required(ctx) is True
    ductile = result.extras["ductile"]
    assert ductile["applied"] is True
    assert ductile["edition"] == is13920.EDITION

    shear = ductile["shear_a"]
    assert shear["v_gravity_n"] == pytest.approx(80000.0)
    assert shear["v_design_n"] > shear["v_gravity_n"] * 1.5, "the capacity shear governs"
    expected = is13920.cl_6_3_3__capacity_shear(
        80000.0,
        station(result, "top_left")["mu_cap_nmm"],
        station(result, "bottom_mid")["mu_cap_nmm"],
        3700.0,
    )
    assert shear["v_design_n"] == pytest.approx(expected.v_design_n)
    assert shear["sway_term_n"] == pytest.approx(1.4 * (expected.v_design_n - 80000.0) / 1.4)

    # Hoops: 2d end zones, first hoop 50 mm from the face, the d/4 or 8 db
    # pitch with the 100 mm floor, and the d/2 pitch between them.
    hoops = is13920.cl_6_3_5__hoop_zones(result.section["d_mm"], ductile.get("dia_long_min_mm", 12.0), 3700.0)
    assert ductile["end_zone_mm"] == pytest.approx(2.0 * result.section["d_mm"])
    assert ductile["first_hoop_mm"] == 50.0
    assert ductile["hoop_spacing_end_mm"] >= is13920.HOOP_SPACING_FLOOR_MM
    assert ductile["hoop_spacing_mid_mm"] == pytest.approx(result.section["d_mm"] / 2.0)

    zones = result.stirrups
    assert [zone["kind"] for zone in zones] == ["confining", "shear", "confining"]
    assert zones[0]["first_mm"] == 50.0
    assert zones[0]["spacing_mm"] <= ductile["hoop_spacing_end_mm"]
    assert zones[1]["spacing_mm"] <= ductile["hoop_spacing_mid_mm"]
    assert zones[0]["dia_mm"] >= hoops.min_dia_mm

    # The base IS 456 stirrup rows are replaced, not left beside the hoops.
    assert not has_check(result, "stirrups_a")
    assert check(result, "ductile_hoops_a").status == C.CHECK_PASS
    assert any("Cl 6.3.3" in note and "governs" in note for note in result.notes)


def test_ductile_stirrup_notes_describe_the_final_end_and_middle_schedule():
    """N26: no IS 456 end note may survive after the hoop schedule replaces it."""
    result = beams.design_beam(
        BeamForces(120.0, 120.0, 90.0, 80.0, 80.0),
        beams.BeamGeometry(300.0, 500.0, 4000.0, "continuous", clear_span_mm=3700.0, element_id="beam-notes"),
        m25_fe500_ductile(),
    )

    schedule_notes = [note for note in result.notes if note.startswith("final stirrup schedule at ")]
    assert len(schedule_notes) == 3
    assert all("after the IS 13920 overlay" in note for note in schedule_notes)
    assert any("at end a" in note and ("%.0f mm" % result.stirrups[0]["spacing_mm"]) in note for note in schedule_notes)
    assert any("at middle" in note and ("%.0f mm" % result.stirrups[1]["spacing_mm"]) in note for note in schedule_notes)
    assert any("at end b" in note and ("%.0f mm" % result.stirrups[-1]["spacing_mm"]) in note for note in schedule_notes)
    assert not any(note.startswith("end a stirrups:") or note.startswith("end b stirrups:") for note in result.notes)


def test_the_ductile_overlay_adds_bars_for_rho_min_and_never_resizes_the_section():
    """Cl 6.2.1 rho_min = 0.24 sqrt(fck)/fy on b d, top and bottom, everywhere."""
    ctx = m25_fe500_ductile()
    geom = beams.BeamGeometry(300.0, 500.0, 4000.0, "continuous", clear_span_mm=3700.0)
    result = beams.design_beam(BeamForces(120.0, 120.0, 90.0, 80.0, 80.0), geom, ctx)

    rho_min = is13920.cl_6_2_1__rho_min(25.0, 500.0)
    assert rho_min == pytest.approx(0.24 * math.sqrt(25.0) / 500.0)
    floor = rho_min * 300.0 * result.section["d_mm"]

    through = [bar for bar in result.bars if bar["role"] == "top_through"]
    assert through, "two bars run through on each face in a ductile frame"
    provided = sum(bar["count"] * C.bar_area_mm2(bar["dia_mm"]) for bar in through)
    assert provided >= floor * 0.95
    assert any("Cl 6.2.1" in note for note in result.notes)

    assert result.section["b_mm"] == 300.0 and result.section["D_mm"] == 500.0
    assert check(result, "ductile_rho_min_bottom_mid").status == C.CHECK_PASS
    assert check(result, "ductile_rho_max_bottom_mid").capacity == pytest.approx(
        is13920.cl_6_2_2__rho_max() * 300.0 * result.section["d_mm"]
    )
    assert check(result, "ductile_joint_sagging").demand == pytest.approx(
        0.5 * max(station(result, "top_left")["mu_cap_nmm"], station(result, "top_right")["mu_cap_nmm"])
    )


def test_a_rho_min_top_up_feeds_the_capacity_shear_it_creates():
    """Bars added for Cl 6.2.1 raise the hinge capacities Cl 6.3.3 is built from.

    M30 with Fe415 puts rho_min at 0.24 sqrt(30) / 415 = 0.0032, which on a
    lightly loaded 300 x 600 beam is more steel than the moments ask for. The
    design shear must be computed from the steel the beam ends up with, not
    from the steel it had before the overlay added to it.
    """
    ctx = D.DesignContext(
        concrete=C.Concrete(fck_mpa=30.0), steel=C.RebarSteel(fy_mpa=415.0), zone="V", frame="SMRF"
    )
    geom = beams.BeamGeometry(300.0, 600.0, 5000.0, "continuous", clear_span_mm=4700.0)
    result = beams.design_beam(BeamForces(60.0, 60.0, 40.0, 70.0, 70.0), geom, ctx)

    assert any("Cl 6.2.1 raised the bottom mid steel" in note for note in result.notes)
    expected = is13920.cl_6_3_3__capacity_shear(
        70000.0,
        station(result, "top_left")["mu_cap_nmm"],
        station(result, "bottom_mid")["mu_cap_nmm"],
        4700.0,
    )
    assert result.extras["ductile"]["shear_a"]["v_design_n"] == pytest.approx(expected.v_design_n)
    assert result.extras["ductile"]["shear_a"]["v_design_n"] > 70000.0


def test_b15_zero_hogging_uses_final_through_capacity_in_both_sway_directions():
    """B15 published vector: nominal ends still have provided top steel.

    The 300 x 500 beam has zero analysed hogging at both ends, 95 kNm sagging,
    95 kN gravity shear and Lclear = 3770 mm.  Cl 6.2.1 grows the top-through
    group to 3-12 (339.3 mm2), about 63.4 kNm capacity.  Counting that built
    section raises the sway term from the old 36.3 kN to about 59.8 kN and the
    design shear from 131.3 kN to about 154.8 kN.
    """
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 95.0, 95.0, 95.0),
        beams.BeamGeometry(
            300.0,
            500.0,
            4000.0,
            "continuous",
            clear_span_mm=3770.0,
            element_id="beam-zero-hog-capacity",
        ),
        m25_fe500_ductile(),
    )
    through = [bar for bar in result.bars if bar["role"] == "top_through"]
    assert [(bar["count"], bar["dia_mm"]) for bar in through] == [(3, 12.0)]
    through_area = role_area_mm2(result, "top_through")
    through_d = (
        result.section["D_mm"]
        - result.section["cover_mm"]
        - result.section["stirrup_dia_mm"]
        - 0.5 * max(bar["dia_mm"] for bar in through)
    )
    through_capacity = D.moment_capacity_nmm(300.0, through_d, 25.0, 500.0, through_area)
    assert through_capacity == pytest.approx(63.4e6, rel=0.02)

    sag_capacity = station(result, "bottom_mid")["mu_cap_nmm"]
    expected = is13920.cl_6_3_3__capacity_shear(
        95000.0,
        through_capacity,
        sag_capacity,
        3770.0,
    )
    old = is13920.cl_6_3_3__capacity_shear(95000.0, 0.0, sag_capacity, 3770.0)
    for end in ("shear_a", "shear_b"):
        shear = result.extras["ductile"][end]
        assert shear["v_design_n"] == pytest.approx(expected.v_design_n)
        assert shear["sway_term_n"] == pytest.approx(expected.sway_term_n)
        assert shear["v_design_n"] == pytest.approx(
            max(abs(expected.v_sway_right_n), abs(expected.v_sway_left_n))
        )
        observed_hog = shear["sway_term_n"] * 3770.0 / 1.4 - sag_capacity
        assert observed_hog == pytest.approx(through_capacity)
        assert shear["v_design_n"] == pytest.approx(154.8e3, rel=0.003)
        assert shear["v_design_n"] > old.v_design_n + 20.0e3


def test_n24_nominal_hogging_still_emits_joint_and_span_capacity_floors():
    """N24: Cl 6.2.3 and 6.2.4 never disappear on zero-hog envelopes.

    The final 3-12 top-through group has about 64.0 kNm capacity.  Therefore
    the joint sagging floor is about 32.0 kNm and the along-span floor about
    16.0 kNm.  Both rows were absent on this exact old-behaviour vector.
    """
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 95.0, 95.0, 95.0),
        beams.BeamGeometry(300.0, 500.0, 4000.0, "continuous", clear_span_mm=3770.0),
        m25_fe500_ductile(),
    )
    through = [bar for bar in result.bars if bar["role"] == "top_through"]
    through_area = role_area_mm2(result, "top_through")
    through_d = (
        result.section["D_mm"]
        - result.section["cover_mm"]
        - result.section["stirrup_dia_mm"]
        - 0.5 * max(bar["dia_mm"] for bar in through)
    )
    through_capacity = D.moment_capacity_nmm(300.0, through_d, 25.0, 500.0, through_area)
    sag_capacity = station(result, "bottom_mid")["mu_cap_nmm"]

    joint = check(result, "ductile_joint_sagging")
    span = check(result, "ductile_span_capacity_floor")
    assert joint.demand == pytest.approx(is13920.cl_6_2_3__joint_sagging(through_capacity))
    assert joint.capacity == pytest.approx(sag_capacity)
    assert span.demand == pytest.approx(is13920.cl_6_2_4__span_capacity_floor(through_capacity))
    assert span.capacity == pytest.approx(min(sag_capacity, through_capacity))
    assert joint.status == C.CHECK_PASS and span.status == C.CHECK_PASS

    # A heavily loaded sagging section can already own its full-length top
    # steel under the established `top_mid` compression role.  Five bars
    # (3-25 + 2-16) provide 1874.7 mm2 at d = 397.5 mm as hogging steel, for
    # 120.6 kNm.  The capacity rows and both sway pairings must name that
    # physical group rather than reverting to zero or to the sagging capacity.
    doubly = beams.design_beam(
        BeamForces(0.0, 0.0, 345.214444, 12.901629, 130.058290),
        beams.BeamGeometry(230.0, 300.0, 2438.0, "ss", clear_span_mm=2208.0),
        m25_fe500_ductile(zone="III", frame="OMRF"),
    )
    top_mid = [bar for bar in doubly.bars if bar["role"] == "top_mid"]
    assert [(bar["count"], bar["dia_mm"]) for bar in top_mid] == [
        (3, 25.0),
        (2, 16.0),
    ]
    top_mid_area = role_area_mm2(doubly, "top_mid")
    top_mid_d = 450.0 - 32.0 - 8.0 - 0.5 * 25.0
    top_mid_capacity = D.moment_capacity_nmm(230.0, top_mid_d, 25.0, 500.0, top_mid_area)
    assert top_mid_capacity == pytest.approx(120.6e6, rel=0.002)
    doubly_sag_capacity = station(doubly, "bottom_mid")["mu_cap_nmm"]
    assert check(doubly, "ductile_joint_sagging").demand == pytest.approx(0.5 * top_mid_capacity)
    assert check(doubly, "ductile_joint_sagging").capacity == pytest.approx(doubly_sag_capacity)
    assert check(doubly, "ductile_span_capacity_floor").demand == pytest.approx(0.25 * top_mid_capacity)
    assert check(doubly, "ductile_span_capacity_floor").capacity == pytest.approx(top_mid_capacity)
    for end in ("shear_a", "shear_b"):
        shear = doubly.extras["ductile"][end]
        observed_hog = shear["sway_term_n"] * 2208.0 / 1.4 - doubly_sag_capacity
        assert observed_hog == pytest.approx(top_mid_capacity)


def test_the_overlay_is_skipped_outside_its_applicability_and_says_so():
    result = beams.design_beam(
        BeamForces(60.0, 60.0, 80.0, 90.0, 90.0),
        beams.BeamGeometry(230.0, 450.0, 4000.0, "continuous"),
        m20_fe415(zone="II", frame="OMRF"),
    )
    assert "ductile" not in result.extras
    assert any("does not apply" in note for note in result.notes)
    assert not any(row.name.startswith("ductile_") for row in result.checks)

    off = beams.design_beam(
        BeamForces(60.0, 60.0, 80.0, 90.0, 90.0),
        beams.BeamGeometry(230.0, 450.0, 4000.0, "continuous"),
        m25_fe500_ductile(is13920="off"),
    )
    assert any("switched off" in note for note in off.notes)
    assert not any(row.name.startswith("ductile_") for row in off.checks)


def test_the_overlay_is_idempotent_on_the_schedule():
    """Running the ductile rules twice must not double the hoops."""
    ctx = m25_fe500_ductile()
    geom = beams.BeamGeometry(300.0, 500.0, 4000.0, "continuous", clear_span_mm=3700.0)
    result = beams.design_beam(BeamForces(120.0, 120.0, 90.0, 80.0, 80.0), geom, ctx)
    before = [dict(zone) for zone in result.stirrups]

    state = dict(result.extras["ductile"])
    del state  # the input state is private; re-run through the public path
    again = beams.design_beam(BeamForces(120.0, 120.0, 90.0, 80.0, 80.0), geom, ctx)
    assert [dict(zone) for zone in again.stirrups] == before


def test_apply_13920_without_a_state_discloses_rather_than_passing_silently():
    result = C.DesignResult(element_id="beam-x", element_type="beam")
    D.apply_13920(result, "beam", m25_fe500_ductile())
    assert result.warnings and "did not run" in result.warnings[0]
    assert result.checks == []


# ---------------------------------------------------------------------------
# torsion
# ---------------------------------------------------------------------------


def test_torsion_folds_into_equivalent_shear_and_moment():
    """Cl 41: Ve = Vu + 1.6 Tu / b and Me1 = Mu + Tu (1 + D/b) / 1.7."""
    plain = beams.design_beam(
        BeamForces(40.0, 40.0, 60.0, 70.0, 70.0),
        beams.BeamGeometry(230.0, 500.0, 4500.0, "continuous"),
        m20_fe415(),
    )
    twisted = beams.design_beam(
        BeamForces(40.0, 40.0, 60.0, 70.0, 70.0, tu_knm=18.0),
        beams.BeamGeometry(230.0, 500.0, 4500.0, "continuous"),
        m20_fe415(),
    )
    torsion = twisted.extras["torsion"]
    assert torsion["ve_a_n"] == pytest.approx(is456.cl_41_3_1__equiv_shear(70000.0, 18e6, 230.0))
    assert torsion["mt_nmm"] == pytest.approx(18e6 * (1.0 + 500.0 / 230.0) / 1.7)
    assert torsion["me1_mid_nmm"] == pytest.approx(60e6 + torsion["mt_nmm"])

    assert station(twisted, "bottom_mid")["mu_nmm"] > station(plain, "bottom_mid")["mu_nmm"]
    assert station(twisted, "bottom_mid")["ast_prov_mm2"] >= station(plain, "bottom_mid")["ast_prov_mm2"]
    assert twisted.extras["shear"][0]["ve_n"] > plain.extras["shear"][0]["ve_n"]
    assert check(twisted, "torsion_transverse_steel").status == C.CHECK_PASS
    assert any("Cl 41" in note for note in twisted.notes)


def test_n25_me2_midspan_is_carried_by_full_length_top_steel():
    """N25: Cl 41.4.2 Me2 belongs on the top face at midspan.

    For 300 x 500, Tu = 40 kNm and Mu,mid = 10 kNm:

      Mt  = 40 (1 + 500/300) / 1.7 = 62.745 kNm
      Me2 = Mt - Mu = 52.745 kNm

    The published review vector needs about 337.5 mm2 on that face; the
    catalogue supplies 3-12 = 339.3 mm2 over all 9000 mm.  The old code merely
    reported Me2 and left 2-12 = 226.2 mm2 cage bars through midspan.
    """
    span_mm = 9000.0
    result = beams.design_beam(
        BeamForces(10.0, 10.0, 10.0, 50.0, 50.0, tu_knm=40.0),
        beams.BeamGeometry(300.0, 500.0, span_mm, "continuous", element_id="beam-me2-mid"),
        m25_fe500_ductile(zone="II", frame="OMRF"),
    )
    mt_nmm = 40.0e6 * (1.0 + 500.0 / 300.0) / 1.7
    me2_nmm = mt_nmm - 10.0e6
    torsion = result.extras["torsion"]
    assert torsion["mt_nmm"] == pytest.approx(mt_nmm)
    assert torsion["me2_mid_nmm"] == pytest.approx(me2_nmm)

    top_mid = station(result, "top_mid")
    assert top_mid["face"] == "top"
    assert top_mid["mu_nmm"] == pytest.approx(me2_nmm)
    assert check(result, "flexure_top_mid").demand == pytest.approx(me2_nmm)
    assert check(result, "flexure_top_mid").status == C.CHECK_PASS

    through = [bar for bar in result.bars if bar["role"] == "top_through"]
    assert through
    assert all(bar["zone_mm"] == [0.0, span_mm] for bar in through)
    assert role_area_mm2(result, "top_through") == pytest.approx(3.0 * C.bar_area_mm2(12.0))
    assert role_area_mm2(result, "top_through") >= 337.5
    left = [bar for bar in result.bars if bar["role"] == "top_left"]
    right = [bar for bar in result.bars if bar["role"] == "top_right"]
    assert left[0]["zone_mm"][1] < span_mm / 2.0
    assert right[0]["zone_mm"][0] > span_mm / 2.0
    assert any("Me2 at midspan" in note and "full-length top-through" in note for note in result.notes)


# ---------------------------------------------------------------------------
# contract: statuses, disclosure, determinism, clauses
# ---------------------------------------------------------------------------


def test_every_status_is_reachable():
    passing = beams.design_beam(
        BeamForces(0.0, 0.0, 100.0, 80.0, 80.0),
        beams.BeamGeometry(230.0, 450.0, 5000.0, "ss"),
        m20_fe415(),
    )
    resized = beams.design_beam(
        BeamForces(0.0, 0.0, 220.0, 90.0, 90.0),
        beams.BeamGeometry(230.0, 400.0, 4000.0, "continuous"),
        m20_fe415(),
    )
    failed = beams.design_beam(
        BeamForces(0.0, 0.0, 900.0, 700.0, 700.0),
        beams.BeamGeometry(230.0, 400.0, 4000.0, "continuous"),
        m20_fe415(),
    )
    assert {passing.status, resized.status, failed.status} == {
        C.STATUS_PASS,
        C.STATUS_RESIZED,
        C.STATUS_FAIL,
    }


def test_a_beam_that_cannot_pass_still_returns_a_full_result():
    """Disclose, never hide: no exception, no empty result, a named governing check."""
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 900.0, 700.0, 700.0),
        beams.BeamGeometry(230.0, 400.0, 4000.0, "continuous", element_id="beam-hopeless"),
        m20_fe415(),
    )
    assert result.status == C.STATUS_FAIL
    assert result.element_id == "beam-hopeless"
    assert result.governing_check
    assert result.utilization_max > 1.0
    assert any(row.status == C.CHECK_FAIL for row in result.checks)
    assert result.bars, "the last section tried is still detailed"
    assert result.stirrups
    assert result.trace
    assert result.warnings and any("exhausted" in text for text in result.warnings)

    wire = result.to_dict()
    for key in ("b_mm", "D_mm", "d_mm", "cover_mm", "length_mm"):
        assert key in wire["section"]
    assert wire["materials"]["fck_mpa"] == 20.0 and wire["materials"]["fy_mpa"] == 415.0
    assert "quantities" not in wire, "finding 24: quantities.py is the sole take-off owner"
    assert json.dumps(wire)  # JSON safe end to end


def test_a_section_the_cover_stack_swallows_is_refused_not_raised():
    """80 mm deep with 30 mm cover leaves nothing to design; say so, do not throw."""
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 10.0, 10.0, 10.0),
        beams.BeamGeometry(230.0, 80.0, 3000.0, "ss", element_id="beam-sliver"),
        m20_fe415(),
    )
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "section_depth"
    assert result.section["D_mm"] == 80.0
    assert result.materials["fck_mpa"] == 20.0
    assert result.checks and result.checks[0].clause in CLAUSE_REGISTRY
    assert any("effective depth" in text for text in result.warnings)
    assert json.dumps(result.to_dict())


def test_results_are_deterministic():
    def build():
        return beams.design_beam(
            BeamForces(120.0, 120.0, 90.0, 80.0, 80.0),
            beams.BeamGeometry(300.0, 500.0, 4000.0, "continuous", clear_span_mm=3700.0, element_id="beam-det"),
            m25_fe500_ductile(),
        ).to_dict()

    first = build()
    second = build()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@pytest.mark.parametrize(
    "forces,geom,ctx_name",
    [
        (BeamForces(0.0, 0.0, 100.0, 80.0, 80.0), (230.0, 450.0, 5000.0, "ss"), "m20"),
        (BeamForces(60.0, 60.0, 80.0, 300.0, 300.0), (230.0, 400.0, 4000.0, "continuous"), "m20"),
        (BeamForces(120.0, 120.0, 90.0, 80.0, 80.0), (300.0, 500.0, 4000.0, "continuous"), "ductile"),
        (BeamForces(40.0, 0.0, 0.0, 45.0, 5.0), (230.0, 450.0, 2000.0, "cantilever"), "m20"),
        (BeamForces(0.0, 0.0, 900.0, 700.0, 700.0), (230.0, 400.0, 4000.0, "continuous"), "m20"),
    ],
)
def test_every_check_row_cites_a_registered_clause(forces, geom, ctx_name):
    ctx = m20_fe415() if ctx_name == "m20" else m25_fe500_ductile()
    result = beams.design_beam(forces, beams.BeamGeometry(*geom), ctx)
    assert result.checks, "a design always states its checks"
    traced = {entry.clause_id for entry in result.trace}
    for row in result.checks:
        assert row.clause in CLAUSE_REGISTRY, row.name + " cites " + repr(row.clause)
        assert row.clause in traced, row.name + " has no trace entry for " + row.clause
        assert row.status in (C.CHECK_PASS, C.CHECK_FAIL, D.CHECK_WARN)
        assert row.units


def test_the_si_boundary_is_crossed_exactly_once():
    result = beams.design_beam(
        BeamForces(75.0, 65.0, 90.0, 55.0, 45.0),
        beams.BeamGeometry(230.0, 500.0, 4000.0, "continuous"),
        m20_fe415(),
    )
    assert station(result, "top_left")["mu_nmm"] == pytest.approx(75.0 * 1e6)
    assert station(result, "top_right")["mu_nmm"] == pytest.approx(65.0 * 1e6)
    assert station(result, "bottom_mid")["mu_nmm"] == pytest.approx(90.0 * 1e6)
    assert result.extras["shear"][0]["vu_n"] == pytest.approx(55.0 * 1e3)
    assert result.extras["shear"][1]["vu_n"] == pytest.approx(45.0 * 1e3)
    assert result.section["length_mm"] == 4000.0


def test_anchorage_at_a_simple_support_is_a_warning_not_a_member_failure():
    """Cl 26.2.3.3: 1.3 M1/V + Lo against Ld, with a hook where it is short."""
    result = beams.design_beam(
        BeamForces(0.0, 0.0, 100.0, 80.0, 80.0),
        beams.BeamGeometry(230.0, 450.0, 5000.0, "ss", support_width_mm=230.0),
        m20_fe415(),
    )
    row = check(result, "anchorage_simple_support")
    assert row.clause == "IS456:2000 26.2.3.3"
    assert row.status in (C.CHECK_PASS, D.CHECK_WARN)
    assert row.status != C.CHECK_FAIL, "a support detail assumption never fails the member"

    tight = beams.design_beam(
        BeamForces(0.0, 0.0, 100.0, 400.0, 400.0),
        beams.BeamGeometry(230.0, 700.0, 5000.0, "ss", support_width_mm=100.0),
        m20_fe415(),
    )
    if check(tight, "anchorage_simple_support").status == D.CHECK_WARN:
        assert tight.status != C.STATUS_FAIL
        assert any("26.2.3.3" in text for text in tight.warnings)


def test_a_continuous_beam_curtails_its_hogging_steel_and_discloses_the_convention():
    span = 5000.0
    result = beams.design_beam(
        BeamForces(90.0, 90.0, 70.0, 100.0, 100.0),
        beams.BeamGeometry(230.0, 500.0, span, "continuous", clear_span_mm=4770.0),
        m20_fe415(),
    )
    top_left = [bar for bar in result.bars if bar["role"] == "top_left"]
    top_right = [bar for bar in result.bars if bar["role"] == "top_right"]
    bottom = [bar for bar in result.bars if bar["role"] == "bottom_mid"]
    assert top_left and top_right and bottom
    assert all(bar["zone_mm"] == [0.0, span] for bar in bottom), "bottom bars run the full span in v1"
    reach = top_left[0]["zone_mm"][1]
    assert top_left[0]["zone_mm"][0] == 0.0
    assert reach == pytest.approx(span - top_right[0]["zone_mm"][0])
    expected = 0.3 * 4770.0 + top_left[0]["ld_mm"] + D.cutoff_extension_mm(result.section["d_mm"], top_left[0]["dia_mm"])
    assert reach == pytest.approx(min(span, expected))
    assert any("curtailment" in note for note in result.notes)


def test_side_face_steel_appears_on_a_deep_web():
    result = beams.design_beam(
        BeamForces(200.0, 200.0, 150.0, 150.0, 150.0),
        beams.BeamGeometry(300.0, 800.0, 6000.0, "continuous"),
        m20_fe415(),
    )
    side = [bar for bar in result.bars if bar["role"] == "side_face"]
    assert side, "IS 456 Cl 26.5.1.3 applies above a 750 mm web"
    assert side[0]["max_spacing_mm"] <= 300.0
    row = check(result, "side_face_steel")
    assert row.demand == pytest.approx(0.001 * 300.0 * 800.0)
    assert row.status == C.CHECK_PASS


# ---------------------------------------------------------------------------
# the detailing engine on its own
# ---------------------------------------------------------------------------


def test_context_reads_the_api_options_block_verbatim():
    ctx = D.as_context(
        {
            "materials": {"fck": 30, "fy": 500},
            "exposure": "severe",
            "fire_rating_h": 1.0,
            "aggregate_mm": 20,
            "seismic": {"zone": "IV", "frame": "OMRF"},
            "is13920": "auto",
        }
    )
    assert ctx.fck_mpa == 30.0 and ctx.fy_mpa == 500.0
    assert ctx.fy_stirrup_mpa == 500.0
    assert ctx.exposure == "severe"
    assert ctx.zone == "IV" and ctx.frame == "OMRF"
    assert D.ductile_required(ctx) is True, "zone IV is ductile even for an ordinary frame"
    assert D.ductile_required(D.as_context({"seismic": {"zone": "II", "frame": "OMRF"}})) is False
    assert D.ductile_required(D.as_context({"seismic": {"zone": "II", "frame": "SMRF"}})) is True
    assert D.as_context(ctx) is ctx
    assert D.as_context(None).fck_mpa == 25.0
    with pytest.raises(ValueError):
        D.as_context({"is13920": "sometimes"})


def test_choose_stirrups_walks_the_ladder_and_respects_the_floor():
    light = D.choose_stirrups(0.0, 300.0)
    assert (light.legs, light.dia_mm, light.spacing_mm) == (2, 8, 300.0)
    assert light.ok

    # 100.5 mm2 of two legged 8 mm at 75 mm is 1.34 mm2/mm; ask for more and
    # the ladder must move up a size rather than pack them tighter.
    heavy = D.choose_stirrups(1.5, 300.0)
    assert heavy.spacing_mm >= D.SPACING_FLOOR_MM
    assert heavy.dia_mm > 8 or heavy.legs > 2
    assert heavy.asv_per_mm_prov >= 1.5

    impossible = D.choose_stirrups(50.0, 300.0)
    assert impossible.ok is False
    assert "floor" in impossible.note

    shallow = D.choose_stirrups(0.0, 60.0)
    assert shallow.spacing_mm == 60.0 and shallow.ok, "a code cap below the floor wins"


def test_merge_stirrup_zones_resolves_overlaps_with_the_tighter_spacing():
    zones = [
        D.StirrupZone(0.0, 1000.0, 2, 8, 100.0, "confining", first_mm=50.0),
        D.StirrupZone(0.0, 4000.0, 2, 8, 250.0, "shear"),
        D.StirrupZone(3000.0, 4000.0, 2, 8, 100.0, "confining"),
    ]
    merged = D.merge_stirrup_zones(zones, 4000.0)
    assert [(zone.from_mm, zone.to_mm, zone.spacing_mm, zone.kind) for zone in merged] == [
        (0.0, 1000.0, 100.0, "confining"),
        (1000.0, 3000.0, 250.0, "shear"),
        (3000.0, 4000.0, 100.0, "confining"),
    ]
    assert merged[0].first_mm == 50.0
    # Order in must not change the answer.
    assert D.merge_stirrup_zones(list(reversed(zones)), 4000.0) == merged
    # Neighbours with the same set merge into one run.
    same = D.merge_stirrup_zones(
        [D.StirrupZone(0.0, 1000.0, 2, 8, 150.0), D.StirrupZone(1000.0, 2000.0, 2, 8, 150.0)], 2000.0
    )
    assert len(same) == 1 and same[0].to_mm == 2000.0
    assert D.merge_stirrup_zones([], 1000.0) == []


def test_moment_capacity_is_the_inverse_of_the_annex_g_steel_equation():
    """The area annex_g__ast_singly returns must read back as the moment asked for.

    Not to the last digit: the printed closed form carries 4.6 where the exact
    inverse carries 4 / 0.87 = 4.5977, so the tabulated steel is a twentieth of
    a percent generous. The capacity must land on the safe side of that, which
    is what stops a section that provides exactly the tabulated area from
    reading short and buying itself a resize.
    """
    for mu in (40e6, 80e6, 120e6):
        ast = is456.annex_g__ast_singly(mu, 230.0, 400.0, 25.0, 500.0)
        capacity = D.moment_capacity_nmm(230.0, 400.0, 25.0, 500.0, ast)
        assert capacity >= mu
        assert capacity == pytest.approx(mu, rel=1e-3)

    # More steel means more capacity, deeper means more capacity, and the
    # singly reinforced value never claims more than Annex G's limit.
    small = D.moment_capacity_nmm(230.0, 400.0, 25.0, 500.0, 600.0)
    large = D.moment_capacity_nmm(230.0, 400.0, 25.0, 500.0, 900.0)
    deeper = D.moment_capacity_nmm(230.0, 450.0, 25.0, 500.0, 600.0)
    assert large > small and deeper > small
    assert D.moment_capacity_nmm(230.0, 400.0, 25.0, 500.0, 1e6) == pytest.approx(
        is456.annex_g__mu_lim(230.0, 400.0, 25.0, 500.0)
    )
    assert D.moment_capacity_nmm(230.0, 400.0, 25.0, 500.0, 0.0) == 0.0

    # Compression steel adds the second couple on top of Mu,lim.
    balanced = D.ast_balanced_mm2(230.0, 400.0, 25.0, 500.0)
    doubly = D.moment_capacity_nmm(230.0, 400.0, 25.0, 500.0, balanced + 400.0, 400.0, 45.0)
    assert doubly > is456.annex_g__mu_lim(230.0, 400.0, 25.0, 500.0)


def test_clause_of_only_admits_registered_callables():
    assert D.clause_of(is456.cl_40_1__tau_v) == "IS456:2000 40.1"
    assert D.clause_of(is456.cl_40_1__tau_v) in CLAUSE_REGISTRY
    with pytest.raises(ValueError):
        D.clause_of(lambda: None)


def test_support_and_geometry_normalisation():
    assert D.normalize_support("Simply Supported") == D.SUPPORT_SS
    assert D.normalize_support("cont") == D.SUPPORT_CONTINUOUS
    with pytest.raises(ValueError):
        D.normalize_support("propped")

    geom = beams.as_beam_geometry({"b_mm": 230, "D_mm": 450, "span_mm": 4000, "support": "ss", "id": "beam-7"})
    assert isinstance(geom, beams.BeamGeometry)
    assert geom.element_id == "beam-7" and geom.support == "ss"
    assert geom.clear_span == pytest.approx(4000.0 - 230.0)
    assert beams.as_beam_geometry(geom) is geom
    with pytest.raises(ValueError):
        beams.as_beam_geometry({"b_mm": 230})
    with pytest.raises(ValueError):
        beams.BeamGeometry(0.0, 450.0, 4000.0)


def test_development_length_and_cutoff_come_from_the_clauses():
    ctx = m20_fe415()
    assert D.development_length_mm(16, ctx) == pytest.approx(is456.cl_26_2_1__ld(16, 415.0, 20.0))
    assert D.development_length_mm(16, ctx, compression=True) < D.development_length_mm(16, ctx)
    assert D.cutoff_extension_mm(400.0, 16.0) == 400.0
    assert D.cutoff_extension_mm(100.0, 16.0) == 192.0
    zone = D.hogging_zone_mm("a", 5000.0, 4770.0, 800.0, 400.0)
    assert zone.role == "top_left" and zone.from_mm == 0.0
    assert zone.to_mm == pytest.approx(0.3 * 4770.0 + 800.0 + 400.0)
    far = D.hogging_zone_mm("b", 5000.0, 4770.0, 800.0, 400.0)
    assert far.to_mm == 5000.0 and far.from_mm == pytest.approx(5000.0 - zone.to_mm)


def test_the_package_exports_lazily_and_registers_the_material():
    from ..design import rcc

    for name in ("design_beam", "design_column", "design_slab", "design_footing", "run_rcc_design"):
        assert callable(getattr(rcc, name)), name + " is a public export of design/rcc"
    result = rcc.design_beam(
        BeamForces(0.0, 0.0, 60.0, 60.0, 60.0),
        {"b_mm": 230, "D_mm": 450, "span_mm": 4000, "support": "continuous"},
        {"materials": {"fck": 25, "fy": 500}},
    )
    assert result.element_type == "beam"
    assert result.status in C.STATUSES
    assert C.get_designer("rcc") is rcc.run_rcc_design


def test_run_rcc_design_never_loses_an_element():
    """A member with no placed geometry comes back failed and named, not dropped."""
    from ..analysis import ForceEnvelope, StationForces
    from ..design import rcc

    envelope = ForceEnvelope(
        element_id="beam-nowhere",
        element_type="beam",
        stations=(
            StationForces(station=0.0, m_neg_min_knm=-40.0, v_max_kn=50.0),
            StationForces(station=0.5, m_pos_max_knm=60.0),
            StationForces(station=1.0, m_neg_min_knm=-40.0, v_max_kn=50.0),
        ),
    )

    class _EmptyModel(object):
        beams = []

    results = rcc.run_rcc_design(_EmptyModel(), [envelope], {"materials": {"fck": 25, "fy": 500}})
    assert len(results) == 1
    assert results[0].element_id == "beam-nowhere"
    assert results[0].status == C.STATUS_FAIL
    assert results[0].warnings
