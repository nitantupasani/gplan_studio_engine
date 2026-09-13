"""Pins for the column designer and the interaction engine it reads.

Two halves. The first is the strain-plane sweep in
`design/rcc/_interaction_fallback.py`, which critic finding 31 promoted from a
fallback to THE v1 interaction engine: its two closed anchors (IS 456 Cl 39.3
and Cl 39.6 Puz), the shape of the domain, where the balanced point sits, and
the caching that makes a hundred identical columns cost one sweep. The second is
`design/rcc/columns.py`: the minimum-eccentricity column, the slender one, the
biaxial one, the ladder running out and the section growing, and the fail that
is still a fully populated result.

The anchor band is 3 percent, as the spec asks, and the test that follows it
states out loud where the bilinear steel law drifts further than that, because
the module discloses the same thing in its docstring and a pin is worth more
than a paragraph.
"""

from __future__ import annotations

import json
import math

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests, and an absolute GPLAN.structural
# import would resolve against the outer directory instead.
from ..analysis import ColumnForces, ForceEnvelope, StationForces
from ..codes import is456
from ..design import common as C
from ..design.rcc import _interaction_fallback as IF
from ..design.rcc import columns as CO


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def cage(b_mm, depth_mm, bars_b, bars_d, dia_mm, fck=25.0, fy=500.0, cover=40.0, tie=8.0, net=True):
    """A symmetric perimeter cage as a RectSection, built the way a detailer would."""
    area = math.pi * dia_mm * dia_mm / 4.0
    inset = cover + tie + 0.5 * dia_mm
    span_b = b_mm - 2.0 * inset
    span_d = depth_mm - 2.0 * inset
    xs = [-0.5 * span_b + index * span_b / (bars_b - 1) for index in range(bars_b)]
    ys = [-0.5 * span_d + index * span_d / (bars_d - 1) for index in range(bars_d)]
    bars = []
    for x in xs:
        bars.append((x, ys[0], area))
        bars.append((x, ys[-1], area))
    for y in ys[1:-1]:
        bars.append((xs[0], y, area))
        bars.append((xs[-1], y, area))
    return IF.rect_section(b_mm, depth_mm, fck, fy, bars, net)


def forces(pu_kn, mux_knm=0.0, muy_knm=0.0, height_m=3.0):
    return ColumnForces(
        pu_kn=pu_kn,
        mux_knm=mux_knm,
        muy_knm=muy_knm,
        lex_m=height_m,
        ley_m=height_m,
        storey=0,
    )


def geom(b_mm=300.0, depth_mm=300.0, height_mm=3000.0, element_id="col-1"):
    return {"b_mm": b_mm, "D_mm": depth_mm, "height_mm": height_mm, "element_id": element_id}


#: Zone II keeps the IS 13920 overlay out of the way where a test is about the
#: IS 456 design alone; the overlay has its own tests below.
PLAIN = {"materials": {"fck": 25, "fy": 500}, "seismic": {"zone": "II", "frame": "OMRF"}}


def bar_entry(result):
    return result.bars[0] if result.bars else {}


def steel_ratio(result):
    section = result.section
    return bar_entry(result).get("asc_mm2", 0.0) / (section["b_mm"] * section["D_mm"])


def check_named(result, name):
    for row in result.checks:
        if row.name == name:
            return row
    return None


# ---------------------------------------------------------------------------
# the interaction engine: closed anchors
# ---------------------------------------------------------------------------


def test_pure_tension_end_is_every_bar_yielded_and_no_moment():
    section = cage(300.0, 300.0, 2, 2, 16.0, fy=415.0)
    points = IF.interaction_points(section)
    expected = -is456.GAMMA_S_FACTOR * 415.0 * section.asc_mm2
    assert points[0].pu_n == pytest.approx(expected, rel=1e-12)
    assert points[0].mu_nmm == pytest.approx(0.0, abs=1e-6)
    assert IF.pure_tension_n(section) == pytest.approx(expected, rel=1e-12)


#: (b, D, bars per b face, bars per D face, dia, fck, fy) over the practical
#: design range, 0.6 to 2 percent steel. Fe 415 above about 1.2 percent drifts
#: past 3 percent and is pinned separately, deliberately, below.
ANCHOR_SECTIONS = [
    (300.0, 300.0, 2, 2, 16.0, 25.0, 500.0),
    (300.0, 300.0, 2, 2, 16.0, 25.0, 415.0),
    (300.0, 300.0, 2, 2, 20.0, 25.0, 500.0),
    (300.0, 300.0, 3, 3, 16.0, 25.0, 500.0),
    (400.0, 400.0, 3, 3, 20.0, 25.0, 500.0),
    (450.0, 450.0, 3, 3, 25.0, 30.0, 500.0),
    (600.0, 600.0, 4, 4, 20.0, 25.0, 500.0),
    (230.0, 450.0, 2, 3, 12.0, 20.0, 415.0),
    (300.0, 450.0, 2, 3, 16.0, 25.0, 500.0),
]


@pytest.mark.parametrize("b,depth,nb,nd,dia,fck,fy", ANCHOR_SECTIONS)
def test_squash_end_matches_cl_39_6_puz_within_three_percent(b, depth, nb, nd, dia, fck, fy):
    section = cage(b, depth, nb, nd, dia, fck=fck, fy=fy)
    closed = is456.cl_39_6__puz(fck, fy, section.ac_mm2, section.asc_mm2)
    swept = IF.interaction_points(section)[-1].pu_n
    assert swept == pytest.approx(IF.squash_load_n(section), rel=1e-12)
    assert swept == pytest.approx(closed, rel=0.03)


@pytest.mark.parametrize("b,depth,nb,nd,dia,fck,fy", ANCHOR_SECTIONS)
def test_cl_39_3_axial_load_is_carried_at_the_minimum_eccentricity(b, depth, nb, nd, dia, fck, fy):
    """Cl 39.3 is Puz with the 0.05 D eccentricity allowance already inside it.

    The sweep has no such allowance, so the way to anchor the clause against it
    is to ask the domain whether it really carries the Cl 39.3 load at that
    eccentricity. It does, on every section in the design range.
    """
    section = cage(b, depth, nb, nd, dia, fck=fck, fy=fy)
    pu_axial = is456.cl_39_3__pu_axial(fck, fy, section.ac_mm2, section.asc_mm2)
    assert pu_axial < IF.squash_load_n(section)
    assert IF.mu_capacity(section, pu_axial) >= 0.05 * depth * pu_axial


def test_bilinear_steel_sits_above_the_code_squash_and_the_gap_grows_with_steel():
    """The disclosed deviation, pinned so it cannot drift unnoticed.

    The IS design curve for cold worked bars reads about 0.91 of 0.87 fy at the
    squash strain of 0.002, where a bilinear law reads all of it, so the sweep
    is always the higher number and the gap grows with the steel ratio. Fe 500
    is still elastic at that strain and drifts less than Fe 415.
    """
    lean = cage(300.0, 300.0, 2, 2, 16.0, fy=415.0)
    rich = cage(300.0, 300.0, 3, 3, 16.0, fy=415.0)
    lean_gap = IF.squash_load_n(lean) / is456.cl_39_6__puz(25.0, 415.0, lean.ac_mm2, lean.asc_mm2)
    rich_gap = IF.squash_load_n(rich) / is456.cl_39_6__puz(25.0, 415.0, rich.ac_mm2, rich.asc_mm2)
    assert 1.0 < lean_gap < rich_gap < 1.05

    rich_500 = cage(300.0, 300.0, 3, 3, 16.0, fy=500.0)
    gap_500 = IF.squash_load_n(rich_500) / is456.cl_39_6__puz(25.0, 500.0, rich_500.ac_mm2, rich_500.asc_mm2)
    assert 1.0 < gap_500 < rich_gap


def test_netting_the_displaced_concrete_lowers_the_squash_load():
    netted = cage(300.0, 300.0, 3, 3, 20.0, net=True)
    gross = cage(300.0, 300.0, 3, 3, 20.0, net=False)
    assert IF.squash_load_n(netted) < IF.squash_load_n(gross)
    displaced = netted.fcd_mpa * netted.asc_mm2
    assert IF.squash_load_n(gross) - IF.squash_load_n(netted) == pytest.approx(displaced, rel=1e-12)


# ---------------------------------------------------------------------------
# the interaction engine: shape of the domain
# ---------------------------------------------------------------------------


def test_domain_ascends_in_axial_load_and_spans_both_anchors():
    section = cage(300.0, 450.0, 2, 3, 16.0)
    points = IF.interaction_points(section, 21)
    assert len(points) == 21
    loads = [point.pu_n for point in points]
    assert loads == sorted(loads)
    assert loads[0] == pytest.approx(IF.pure_tension_n(section), rel=1e-12)
    assert loads[-1] == pytest.approx(IF.squash_load_n(section), rel=1e-12)
    step = loads[1] - loads[0]
    for index in range(1, len(loads)):
        assert loads[index] - loads[index - 1] == pytest.approx(step, rel=1e-6)


def test_moment_rises_to_the_balanced_point_and_falls_after_it():
    section = cage(300.0, 300.0, 3, 3, 16.0)
    points = IF.interaction_points(section, 21)
    balanced = IF.balanced_point(section)
    peak = max(range(len(points)), key=lambda index: points[index].mu_nmm)
    rising = [points[index].mu_nmm for index in range(peak + 1)]
    falling = [points[index].mu_nmm for index in range(peak, len(points))]
    assert rising == sorted(rising)
    assert falling == sorted(falling, reverse=True)
    # the peak of a 21 point domain brackets the balanced load, and the clause
    # state sits within a percent of the true peak: IS 456 fixes Pb at 0.002
    # tension in the outermost steel, which is near the crest of this
    # constitutive law rather than exactly on it
    assert points[peak - 1].pu_n <= balanced.pu_n <= points[peak + 1].pu_n
    assert balanced.mu_nmm >= 0.99 * max(point.mu_nmm for point in points)


@pytest.mark.parametrize("fy", [415.0, 500.0])
def test_balanced_point_is_the_clause_strain_state(fy):
    """Cl 39.7.1.1 fixes Pb by 0.0035 in the concrete and 0.002 tension in the
    outermost steel layer, which is exactly where `balanced_xu_mm` puts it."""
    section = cage(300.0, 300.0, 3, 3, 16.0, fy=fy)
    xu = IF.balanced_xu_mm(section)
    strains = IF.bar_strains(section, xu)
    assert min(strains) == pytest.approx(-IF.EPS_C2, rel=1e-9)
    assert max(strains) > 0.0  # the far face is in compression
    # the outermost tension bar is past the bilinear yield strain for Fe 415,
    # and the clause state is just short of it for Fe 500, whose 0.87 fy needs
    # 0.002175: either way the sweep reports the strain, it does not assume it
    yield_strain = is456.GAMMA_S_FACTOR * fy / is456.ES_MPA
    assert (abs(min(strains)) >= yield_strain) == (fy == 415.0)
    assert 0.0 < IF.balanced_point(section).pu_n < IF.squash_load_n(section)


def test_balanced_neutral_axis_matches_the_hand_ratio():
    section = cage(300.0, 400.0, 2, 3, 20.0)
    d_eff = 400.0 - (40.0 + 8.0 + 10.0)
    expected = IF.EPS_CU / (IF.EPS_CU + IF.EPS_C2) * d_eff
    assert IF.balanced_xu_mm(section) == pytest.approx(expected, rel=1e-9)


def test_more_steel_carries_more_moment_at_the_same_axial_load():
    lean = cage(300.0, 300.0, 2, 2, 16.0)
    rich = cage(300.0, 300.0, 2, 2, 25.0)
    for pu in (0.0, 300.0e3, 800.0e3):
        assert IF.mu_capacity(rich, pu) > IF.mu_capacity(lean, pu)


def test_mu_capacity_is_zero_outside_the_domain_and_interpolates_inside():
    section = cage(300.0, 300.0, 2, 2, 16.0)
    points = IF.interaction_points(section, 21)
    assert IF.mu_capacity(section, points[0].pu_n - 1.0) == 0.0
    assert IF.mu_capacity(section, points[-1].pu_n + 1.0) == 0.0
    lower, upper = points[8], points[9]
    middle = 0.5 * (lower.pu_n + upper.pu_n)
    assert IF.mu_capacity(section, middle) == pytest.approx(
        0.5 * (lower.mu_nmm + upper.mu_nmm), rel=1e-9
    )


def test_a_deeper_plane_carries_more_moment_than_the_narrow_one():
    section = cage(300.0, 450.0, 2, 3, 16.0)
    pu = 600.0e3
    assert IF.mu_capacity(section, pu, IF.THETA_X) > IF.mu_capacity(section, pu, IF.THETA_Y)


def test_a_square_cage_is_the_same_about_both_axes():
    section = cage(300.0, 300.0, 3, 3, 16.0)
    pu = 700.0e3
    assert IF.mu_capacity(section, pu, IF.THETA_X) == pytest.approx(
        IF.mu_capacity(section, pu, IF.THETA_Y), rel=1e-9
    )


def test_strip_areas_recover_the_rectangle():
    section = cage(300.0, 450.0, 2, 3, 16.0)
    for theta in (0.0, math.pi / 2.0, math.pi / 6.0, -math.pi / 3.0):
        fibers = IF._fibers(section, round(theta, 12), IF.CONCRETE_STRIPS)
        assert float(fibers.area_strip_mm2.sum()) == pytest.approx(300.0 * 450.0, rel=0.01)


def test_interaction_points_refuses_a_domain_with_no_interior():
    section = cage(300.0, 300.0, 2, 2, 16.0)
    with pytest.raises(ValueError):
        IF.interaction_points(section, 2)


# ---------------------------------------------------------------------------
# the interaction engine: identity and cache
# ---------------------------------------------------------------------------


def test_rect_section_normalizes_so_two_builds_are_one_key():
    one = IF.rect_section(300.0, 300.0, 25.0, 500.0, [(50.0, 60.0, 201.062), (-50.0, -60.0, 201.062)])
    other = IF.rect_section(
        300.0000000001,
        300.0,
        25.0,
        500.0,
        [(-50.0, -60.0, 201.0619999), (50.0, 60.0, 201.062)],
    )
    assert one == other
    assert hash(one) == hash(other)
    assert one.bars[0].y_mm <= one.bars[-1].y_mm


def test_the_domain_cache_serves_a_repeat_of_the_same_section():
    section = cage(350.0, 350.0, 3, 3, 20.0, fck=30.0)
    IF.clear_caches()
    IF.interaction_points(section)
    first = IF.cache_info()
    IF.interaction_points(section)
    second = IF.cache_info()
    assert first.misses == 1 and first.hits == 0
    assert second.hits == 1 and second.misses == 1


def test_the_same_section_returns_an_identical_domain():
    left = cage(300.0, 300.0, 2, 2, 20.0)
    right = cage(300.0, 300.0, 2, 2, 20.0)
    IF.clear_caches()
    first = IF.interaction_points(left)
    IF.clear_caches()
    second = IF.interaction_points(right)
    assert first == second


def test_engine_note_names_the_engine_and_the_missing_dependency():
    note = IF.engine_note()
    assert IF.ENGINE_NAME in note
    assert "structuralcodes" in note


# ---------------------------------------------------------------------------
# the designer: the ordinary column
# ---------------------------------------------------------------------------


def test_short_axial_column_picks_a_plausible_cage():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    assert result.status == C.STATUS_PASS
    assert 0.008 <= steel_ratio(result) <= 0.015
    assert bar_entry(result)["count"] >= 4
    assert bar_entry(result)["dia_mm"] >= 12.0
    assert result.section["b_mm"] == 300.0 and result.section["D_mm"] == 300.0
    assert not result.resize_history


def test_the_minimum_eccentricity_is_the_moment_when_the_envelope_has_none():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    e_min = is456.cl_25_4__e_min(3000.0, 300.0)
    text = " ".join(result.notes)
    assert "minimum eccentricity" in text
    assert C.knm_to_nmm(0.0) == 0.0
    # Mux = Pu x e_min, stated in the note in kNm
    assert ("%.2f" % (900.0e3 * e_min / 1.0e6)) in text


def test_the_pure_axial_check_appears_only_when_cl_39_3_allows_it():
    wide = CO.design_column(forces(2400.0), geom(600.0, 600.0), PLAIN)
    narrow = CO.design_column(forces(900.0), geom(300.0, 300.0), PLAIN)
    assert check_named(wide, "pure_axial") is not None
    # e_min of a 300 mm column is 20 mm, more than 0.05 x 300 = 15 mm
    assert check_named(narrow, "pure_axial") is None


def test_units_cross_the_boundary_once():
    result = CO.design_column(forces(900.0, mux_knm=40.0), geom(), PLAIN)
    axial = check_named(result, "axial_capacity")
    assert axial.demand == pytest.approx(900.0e3)
    assert axial.units == "N"
    assert result.section["length_mm"] == 3000.0


def test_slender_column_takes_the_additional_moment_and_more_steel():
    short = CO.design_column(forces(900.0, height_m=3.0), geom(height_mm=3000.0), PLAIN)
    slender = CO.design_column(forces(900.0, height_m=5.0), geom(height_mm=5000.0), PLAIN)
    assert steel_ratio(slender) > steel_ratio(short)
    text = " ".join(slender.notes)
    assert "39.7.1 additional moments Max" in text
    assert "slender" in text
    assert "additional moments Max" not in " ".join(short.notes)
    assert "do not apply" in " ".join(short.notes)
    assert "39.7.1" not in set(entry.ref for entry in short.trace)


def test_the_slender_boundary_is_the_one_cl_25_1_2_draws():
    """B14: le/dim of exactly 12 is slender, so Cl 39.7.1 applies at it.

    `is456.cl_25_1_2__slenderness` calls a column short only when BOTH ratios
    are strictly below 12, and `m_to_mm` lands on exactly 12.0 for every round
    metric pair (3.6 m over 300 mm here, and 2.4/200, 3.0/250, 4.5/375 with it).
    The additional moment used to be skipped at exactly 12, so the boundary
    column was delivered a lighter cage than one a tenth of a millimetre longer
    while the note in the same result called it slender.
    """
    assert is456.cl_25_1_2__slenderness(3600.0, 3600.0, 300.0, 300.0).short is False
    ma_at, _k_at = CO._additional_moment(1100e3, 300.0, 3600.0, 3000e3, 800e3)
    ma_past, _k_past = CO._additional_moment(1100e3, 300.0, 3600.4, 3000e3, 800e3)
    assert ma_at > 0.0
    assert ma_at == pytest.approx(ma_past, rel=1e-3)
    assert CO._additional_moment(1100e3, 300.0, 3599.0, 3000e3, 800e3) == (0.0, 1.0)

    at_twelve = CO.design_column(forces(1100.0, height_m=3.6), geom(height_mm=3600.0), PLAIN)
    past_twelve = CO.design_column(forces(1100.0, height_m=3.6004), geom(height_mm=3600.4), PLAIN)
    assert steel_ratio(at_twelve) == pytest.approx(steel_ratio(past_twelve))
    text = " ".join(at_twelve.notes)
    assert "additional moments Max" in text
    assert "reaches 12" in text


def test_the_k_factor_is_recomputed_against_puz_and_the_balanced_point():
    result = CO.design_column(forces(900.0, height_m=5.0), geom(height_mm=5000.0), PLAIN)
    note = [text for text in result.notes if "additional moments Max" in text][0]
    assert "k " in note and "balanced loads" in note
    refs = set(entry.ref for entry in result.trace)
    assert "39.7.1" in refs and "39.7.1.1" in refs


def test_a_biaxial_demand_costs_more_steel_than_the_same_moment_on_one_axis():
    uniaxial = CO.design_column(forces(700.0, mux_knm=45.0), geom(), PLAIN)
    biaxial = CO.design_column(forces(700.0, mux_knm=45.0, muy_knm=35.0), geom(), PLAIN)
    assert steel_ratio(biaxial) > steel_ratio(uniaxial)
    interaction = check_named(biaxial, "biaxial_interaction")
    assert interaction.status == C.CHECK_PASS
    assert interaction.capacity == 1.0
    # the interaction sum, not the axial load, is what the cage was chosen for
    assert interaction.ratio > check_named(biaxial, "axial_capacity").ratio
    assert interaction.ratio > 0.5


def test_the_biaxial_check_uses_alpha_n_from_puz():
    result = CO.design_column(forces(700.0, mux_knm=45.0, muy_knm=35.0), geom(), PLAIN)
    refs = set(entry.ref for entry in result.trace)
    assert "39.6 alpha_n" in refs and "39.6" in refs and "39.6 Puz" in refs
    alpha = [entry for entry in result.trace if entry.ref == "39.6 alpha_n"][0]
    assert 1.0 <= alpha.output <= 2.0


# ---------------------------------------------------------------------------
# the designer: detailing
# ---------------------------------------------------------------------------


def test_ties_follow_cl_26_5_3_2():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    tie = result.stirrups[0]
    dia_long = bar_entry(result)["dia_mm"]
    allowed = is456.cl_26_5_3_2__ties(dia_long, 300.0)
    assert tie["kind"] == "tie"
    assert tie["dia_mm"] >= max(6.0, dia_long / 4.0)
    assert tie["dia_mm"] in C.STIRRUP_DIAS
    assert tie["spacing_mm"] <= allowed.pitch_mm
    assert tie["spacing_mm"] % CO.TIE_SPACING_MODULE_MM == 0
    assert tie["legs"] >= 2
    assert tie["zone_mm"] == [0.0, 3000.0]


def test_bars_carry_their_own_development_length_and_zone():
    # Finding N22: this 300 x 300 column is NOT the Cl 39.3 axially loaded case
    # (its Cl 25.4 minimum eccentricity of 20 mm is beyond 0.05 x 300), so the
    # value written on the bar is the Cl 26.2.1.1 TENSION bond one. The pin used
    # to read `True` for compression whatever the column was carrying.
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    bar = bar_entry(result)
    expected = is456.cl_26_2_1__ld(bar["dia_mm"], 500.0, 25.0, True, False)
    assert bar["ld_mm"] == pytest.approx(expected)
    assert bar["role"] == "long"
    assert bar["zone_mm"] == [0.0, 3000.0]
    assert bar["count"] == bar["bars_per_b_face"] * 2 + bar["bars_per_d_face"] * 2 - 4


def test_the_bond_stress_follows_whether_the_section_is_wholly_in_compression():
    """N22: the compression bond value only where Cl 39.3 has been proved.

    Cl 26.2.1.1 raises the design bond stress 25 percent for a bar in
    compression, so a compression Ld is a fifth shorter than the tension one.
    It used to be written on every column bar unconditionally, which leaves a
    column carrying moment with an Ld, and a lap read straight off it, 20
    percent short. Per-bar resolution of the design strain plane is not made in
    this version and the note says so.
    """
    with_moment = CO.design_column(forces(900.0, 60.0, 20.0), geom(), PLAIN)
    bar = bar_entry(with_moment)
    assert check_named(with_moment, "pure_axial") is None
    assert bar["ld_mm"] == pytest.approx(is456.cl_26_2_1__ld(bar["dia_mm"], 500.0, 25.0, True, False))
    text = " ".join(with_moment.notes)
    assert "TENSION bond stress" in text
    assert "tension lap" in text

    axial = CO.design_column(forces(1500.0), geom(450.0, 450.0), PLAIN)
    axial_bar = bar_entry(axial)
    assert check_named(axial, "pure_axial") is not None
    assert axial_bar["ld_mm"] == pytest.approx(
        is456.cl_26_2_1__ld(axial_bar["dia_mm"], 500.0, 25.0, True, True)
    )
    assert "COMPRESSION bond stress" in " ".join(axial.notes)
    assert axial_bar["ld_mm"] < is456.cl_26_2_1__ld(axial_bar["dia_mm"], 500.0, 25.0, True, False)


def test_arrangement_refuses_a_cage_that_breaks_the_periphery_rule():
    assert CO.arrange_bars(4, 32, 600.0, 600.0, 40.0, 20.0) is None
    good = CO.arrange_bars(12, 20, 600.0, 600.0, 40.0, 20.0)
    assert good is not None
    assert max(good.spacing_b_mm, good.spacing_d_mm) <= CO.PERIPHERY_SPACING_MM


def test_arrangement_refuses_a_cage_that_breaks_the_bar_gap_rule():
    assert CO.arrange_bars(20, 25, 230.0, 230.0, 40.0, 20.0) is None
    assert CO.arrange_bars(4, 16, 230.0, 230.0, 30.0, 20.0) is not None


def test_a_two_bar_face_is_held_to_the_same_cl_26_3_2_gap():
    """N21: the one gap between two corner bars is a Cl 26.3.2 gap too.

    230 x t is what `api` hands the designer for an IS 4326 confining column,
    and t goes down to 150 mm. 4-25 in a 230 x 150 leaves 24.0 mm clear across
    the 150 mm face where Cl 26.3.2 asks for 25.0, and the gap rule used to be
    applied only to faces carrying MORE than two bars, so that cage was on the
    ladder and shipped with every check row green.
    """
    assert C.min_bar_gap_mm(25, 20.0) == 25.0
    assert CO.arrange_bars(4, 25, 230.0, 150.0, 30.0, 20.0) is None
    legal = CO.arrange_bars(4, 20, 230.0, 150.0, 30.0, 20.0)
    assert legal is not None
    assert legal.spacing_d_mm - legal.dia_mm >= C.min_bar_gap_mm(20, 20.0)

    rungs, _note = CO._ladder_for(230.0, 150.0, "moderate", 0.0, 20.0)
    assert rungs
    for rung in rungs:
        gap = C.min_bar_gap_mm(rung.dia_mm, 20.0)
        assert rung.spacing_b_mm - rung.dia_mm >= gap - 1e-9
        assert rung.spacing_d_mm - rung.dia_mm >= gap - 1e-9


def test_a_section_too_thin_for_the_gap_is_grown_not_dropped():
    """N21: the tightened gap must refer the section on, never deliver nothing.

    A 230 x 115 holds no legal cage at all once the two-bar face obeys the
    clause, so the empty ladder has to reach the resize walk and come back as a
    designed, larger section with the step disclosed.
    """
    thin, note = CO._ladder_for(230.0, 115.0, "moderate", 0.0, 20.0)
    assert thin == ()
    assert note
    result = CO.design_column(
        forces(250.0, 2.0, 2.0),
        {"b_mm": 230.0, "D_mm": 115.0, "height_mm": 3000.0, "element_id": "tie-1", "role": "tie"},
        PLAIN,
    )
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert result.resize_history
    assert result.resize_history[0]["from"] == {"b_mm": 230.0, "D_mm": 115.0}
    assert result.section["D_mm"] > 115.0
    assert bar_entry(result)["count"] >= 4


def test_arrangement_is_symmetric_about_both_axes():
    arrangement = CO.arrange_bars(8, 16, 300.0, 450.0, 30.0, 20.0)
    positions = set(arrangement.positions_mm)
    assert len(positions) == 8
    for x, y in positions:
        assert (-x, y) in positions and (x, -y) in positions
    assert arrangement.asc_mm2 == pytest.approx(8 * C.bar_area_mm2(16))


def test_a_big_section_gets_intermediate_bars_from_the_ladder():
    result = CO.design_column(forces(2500.0), geom(600.0, 600.0), PLAIN)
    bar = bar_entry(result)
    assert bar["count"] >= 8
    assert max(bar["spacing_b_mm"], bar["spacing_d_mm"]) <= CO.PERIPHERY_SPACING_MM
    assert check_named(result, "bar_periphery_spacing").status == C.CHECK_PASS


def test_the_ladder_starts_at_the_cheapest_cage_the_section_can_hold():
    """N23: the first rung is the Cl 26.5.3.1 floor, not what the picker reached.

    `pick_bars` scores area excess against a target and `_arrange_up` then adds
    pairs of bars for the 300 mm periphery rule, so on 600 x 600 the lowest rung
    the search reached was 18-16 at 1.005 percent while 10-20 (0.873 percent)
    and 16-16 (0.894) both arrange legally and clear the floor.
    """
    cover = C.resolve_cover("column", "moderate", 0.0, 0.0).cover_mm
    rungs, note = CO._ladder_for(600.0, 600.0, "moderate", 0.0, 20.0)
    limits = is456.cl_26_5_3_1__long_steel_limits(600.0 * 600.0)
    assert rungs
    first = rungs[0]
    assert first.asc_mm2 >= limits.asc_min_mm2

    # the exhaustive answer the ladder now has to match
    cheapest = None
    for dia in CO.COLUMN_DIAS_MM:
        for count in range(4, CO.MAX_LONG_BARS + 1, 2):
            asc = count * C.bar_area_mm2(dia)
            if asc < limits.asc_min_mm2 or asc > limits.asc_max_mm2:
                continue
            if CO.arrange_bars(count, dia, 600.0, 600.0, cover, 20.0) is None:
                continue
            if cheapest is None or asc < cheapest:
                cheapest = asc
    assert cheapest is not None
    assert first.asc_mm2 == pytest.approx(cheapest)
    assert (first.count, first.dia_mm) == (10, 20)
    assert "0.87 percent" in note
    assert [rung.asc_mm2 for rung in rungs] == sorted(rung.asc_mm2 for rung in rungs)


def test_a_bar_capped_ladder_names_the_policy_cap_not_packing():
    """N20: the 600 mm ladder reaches its bar-count policy cap before 6 percent."""
    rungs, note = CO._ladder_for(600.0, 600.0, "moderate", 0.0, 20.0)
    evaluated = CO._Eval(
        puz_n=0.0,
        pb_x_n=0.0,
        pb_y_n=0.0,
        k_x=0.0,
        k_y=0.0,
        ma_x_nmm=0.0,
        ma_y_nmm=0.0,
        e_min_x_mm=0.0,
        e_min_y_mm=0.0,
        mux_design_nmm=0.0,
        muy_design_nmm=0.0,
        mux1_nmm=0.0,
        muy1_nmm=0.0,
        alpha_n=0.0,
        ratio=CO.RATIO_CAP,
        pu_axial_n=0.0,
        axial_only=False,
        ok=False,
    )

    assert rungs[-1].count == CO.MAX_LONG_BARS
    assert "policy cap of 20 longitudinal bars" in note
    assert "cage stopped fitting first" not in note
    assert "policy cap of 20 longitudinal bars" in CO._resize_reason((rungs[-1], evaluated))


def test_a_lightly_loaded_big_column_takes_the_cheapest_legal_cage():
    """N23 end to end: 600 x 600 at a trivial load is 10-20, not 18-16."""
    result = CO.design_column(forces(200.0), geom(600.0, 600.0), PLAIN)
    assert result.status == C.STATUS_PASS
    bar = bar_entry(result)
    assert (bar["count"], bar["dia_mm"]) == (10, 20.0)
    assert steel_ratio(result) < 0.009


def test_tie_legs_count_the_cross_ties_a_wide_face_needs():
    tight = CO.arrange_bars(8, 16, 300.0, 300.0, 30.0, 20.0)
    assert CO.tie_legs(tight) == (2, 2)
    wide = CO.arrange_bars(16, 16, 600.0, 600.0, 40.0, 20.0)
    legs_b, legs_d = CO.tie_legs(wide)
    assert legs_b >= 2 and legs_d >= 2
    assert max(legs_b, legs_d) > 2


def test_internal_legs_tie_every_bar_when_nothing_is_within_reach():
    assert CO._internal_legs(2, 400.0) == 0
    assert CO._internal_legs(5, 400.0) == 3
    assert CO._internal_legs(3, 100.0) == 0
    assert CO._internal_legs(6, 100.0) >= 1


# ---------------------------------------------------------------------------
# the designer: resize and refusal
# ---------------------------------------------------------------------------


def test_the_ladder_exhausts_and_the_section_grows():
    result = CO.design_column(forces(3000.0), geom(300.0, 300.0), PLAIN)
    assert result.status == C.STATUS_RESIZED
    assert result.resize_history
    assert result.section["b_mm"] * result.section["D_mm"] > 300.0 * 300.0
    first = result.resize_history[0]
    assert first["from"] == {"b_mm": 300.0, "D_mm": 300.0}
    assert "39.6" in first["reason"] or "Puz" in first["reason"]
    # every recorded step ends on the section that follows it, and the last one
    # ends on the section actually reported
    for step, following in zip(result.resize_history, result.resize_history[1:]):
        assert step["to"] == following["from"]
    assert result.resize_history[-1]["to"] == {
        "b_mm": result.section["b_mm"],
        "D_mm": result.section["D_mm"],
    }


def test_growth_takes_the_smaller_side_first_and_respects_the_cap():
    result = CO.design_column(forces(14000.0), geom(300.0, 300.0), PLAIN)
    assert result.status == C.STATUS_FAIL
    for step in result.resize_history:
        before = step["from"]
        after = step["to"]
        grew = "b_mm" if after["b_mm"] > before["b_mm"] else "D_mm"
        assert after[grew] - before[grew] == C.ResizePolicy().column_step_mm
        assert before[grew] <= min(before["b_mm"], before["D_mm"])
    assert max(result.section["b_mm"], result.section["D_mm"]) <= C.ResizePolicy().column_cap_mm


def test_an_impossible_column_fails_fully_populated_and_never_raises():
    result = CO.design_column(forces(14000.0), geom(300.0, 300.0), PLAIN)
    assert result.status == C.STATUS_FAIL
    assert result.governing_check
    assert result.bars and result.stirrups and result.checks
    assert result.section["b_mm"] > 0.0 and result.section["d_mm"] > 0.0
    assert any("without a passing layout" in text for text in result.warnings)
    assert any(row.status == C.CHECK_FAIL for row in result.checks)
    assert json.dumps(result.to_dict())


def test_a_column_with_no_load_still_returns_the_minimum_cage():
    result = CO.design_column(forces(0.0), geom(), PLAIN)
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert steel_ratio(result) >= 0.008


def test_a_section_too_small_for_four_bars_is_refused_not_crashed():
    """With room to grow the ladder fixes this; pinned to one attempt it refuses."""
    tiny = dict(PLAIN, resize_policy={"max_iters": 1})
    result = CO.design_column(forces(100.0), geom(90.0, 90.0, element_id="tiny"), tiny)
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "bar_arrangement"
    assert result.element_id == "tiny"
    assert any("fits" in text for text in result.warnings)
    assert json.dumps(result.to_dict())

    grown = CO.design_column(forces(100.0), geom(90.0, 90.0, element_id="tiny"), PLAIN)
    assert grown.status == C.STATUS_RESIZED
    assert grown.section["b_mm"] > 90.0


def test_the_resize_policy_bounds_the_walk():
    policy = C.ResizePolicy(max_iters=3)
    result = CO.design_column(
        forces(14000.0),
        geom(300.0, 300.0),
        {"materials": {"fck": 25, "fy": 500}, "seismic": {"zone": "II"}, "resize_policy": policy},
    )
    assert len(result.resize_history) <= 3
    assert any("iteration limit" in text or "cap" in text for text in result.warnings)


# ---------------------------------------------------------------------------
# the designer: contract, determinism, trace
# ---------------------------------------------------------------------------


def test_the_same_column_designed_twice_is_the_same_dict():
    first = CO.design_column(forces(900.0, mux_knm=30.0), geom(), PLAIN)
    second = CO.design_column(forces(900.0, mux_knm=30.0), geom(), PLAIN)
    assert first.to_dict() == second.to_dict()


def test_the_result_is_the_shared_contract():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    wire = result.to_dict()
    assert wire["element_type"] == "column"
    assert "quantities" not in wire  # finding 24
    assert set(("b_mm", "D_mm", "d_mm", "cover_mm", "length_mm")) <= set(wire["section"])
    assert wire["materials"] == {"fck_mpa": 25.0, "fy_mpa": 500.0}
    assert C.DesignResult.from_dict(wire).to_dict() == wire


def test_every_check_row_has_a_clause_and_a_unit_where_it_has_one():
    result = CO.design_column(forces(900.0, mux_knm=30.0), geom(), PLAIN)
    for row in result.checks:
        assert row.clause
        assert row.status in (C.CHECK_PASS, C.CHECK_FAIL)
    names = set(row.name for row in result.checks)
    assert {"axial_capacity", "biaxial_interaction", "longitudinal_steel_min", "tie_pitch"} <= names


def test_the_trace_carries_the_column_clauses_once_each():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    refs = [entry.ref for entry in result.trace]
    for ref in ("25.1.2", "25.3.1", "26.5.3.1", "26.5.3.2", "26.2.1", "39.6 Puz", "39.6"):
        assert ref in refs
    assert refs.count("39.6") == 1  # the ladder's rejected rungs are not traced
    for entry in result.trace:
        assert entry.code and entry.title
        assert json.dumps(entry.to_dict())


def test_the_result_names_the_interaction_engine():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    assert any(IF.ENGINE_NAME in text for text in result.notes)
    assert any("structuralcodes" in text for text in result.notes)


# ---------------------------------------------------------------------------
# the designer: inputs it accepts
# ---------------------------------------------------------------------------


def test_a_column_envelope_reaches_the_designer_through_the_converter():
    envelope = ForceEnvelope(
        element_id="col-9",
        element_type="column",
        stations=(StationForces(station=0.0, n_max_kn=850.0), StationForces(station=1.0, n_max_kn=800.0)),
        storey=1,
        length_m=3.2,
    )
    result = CO.design_column(envelope, {"b_mm": 300.0, "D_mm": 300.0, "element_id": "col-9"}, PLAIN)
    assert result.element_id == "col-9"
    assert check_named(result, "axial_capacity").demand == pytest.approx(850.0e3)
    assert result.section["length_mm"] == pytest.approx(3200.0)


def test_geometry_accepts_the_model_metre_fields():
    geometry = CO.column_geometry({"width_m": 0.3, "depth_m": 0.45, "height_m": 3.0, "id": "c7"})
    assert geometry.b_mm == 300.0 and geometry.depth_mm == 450.0
    assert geometry.height_mm == 3000.0 and geometry.clear_height_mm == 3000.0
    assert geometry.element_id == "c7"


def test_geometry_without_a_section_is_an_input_error():
    with pytest.raises(ValueError):
        CO.column_geometry({"height_mm": 3000.0})
    with pytest.raises(ValueError):
        CO.column_geometry({"b_mm": 300.0, "D_mm": 300.0})


def test_context_reads_the_options_block_and_a_plain_object():
    from_options = CO.column_context(
        {"materials": {"fck": 30, "fy": 415}, "exposure": "severe", "seismic": {"zone": "IV", "frame": "SMRF"}}
    )
    assert from_options.fck_mpa == 30.0 and from_options.fy_mpa == 415.0
    assert from_options.exposure == "severe" and from_options.zone == "IV"
    assert from_options.frame == "SMRF"
    assert CO.column_context(from_options) is from_options
    assert CO.column_context(None).fck_mpa == 25.0

    class Duck(object):
        fck_mpa = 35.0
        fy_mpa = 500.0
        agg_mm = 12.5

    duck = CO.column_context(Duck())
    assert duck.fck_mpa == 35.0 and duck.aggregate_mm == 12.5


def test_the_structural_system_is_not_read_as_a_ductility_class():
    """`system` means rc_frame outside the seismic block and SMRF inside it."""
    context = CO.column_context({"system": "rc_frame", "seismic": {"zone": "IV", "frame": "SMRF"}})
    assert context.frame == "SMRF" and context.zone == "IV"
    assert CO.column_context({"system": "load_bearing_masonry"}).frame == "OMRF"


def test_the_orchestrator_context_object_reaches_the_designer():
    """`run_rcc_design` hands every designer a detailing.DesignContext."""
    from ..design.rcc import detailing

    shared = detailing.as_context(
        {"materials": {"fck": 30, "fy": 415}, "exposure": "severe", "seismic": {"zone": "IV", "frame": "SMRF"}}
    )
    context = CO.column_context(shared)
    assert context.fck_mpa == 30.0 and context.fy_mpa == 415.0
    assert context.exposure == "severe" and context.zone == "IV" and context.frame == "SMRF"
    result = CO.design_column(forces(900.0), geom(400.0, 400.0), shared)
    assert result.materials == {"fck_mpa": 30.0, "fy_mpa": 415.0}
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED, C.STATUS_FAIL)


def test_the_exposure_drives_the_cover_that_lands_on_the_section():
    mild = CO.design_column(forces(900.0), geom(), dict(PLAIN, exposure="mild"))
    severe = CO.design_column(forces(900.0), geom(), dict(PLAIN, exposure="severe"))
    assert severe.section["cover_mm"] > mild.section["cover_mm"]
    assert severe.section["cover_mm"] == is456.table_16__nominal_cover("severe")


# ---------------------------------------------------------------------------
# the designer: the IS 13920 overlay hand-off
# ---------------------------------------------------------------------------


def test_zone_two_ordinary_frame_says_the_overlay_does_not_apply():
    result = CO.design_column(forces(900.0), geom(), PLAIN)
    assert any("does not apply" in text for text in result.notes)
    assert not any(row.name.startswith("ductile") for row in result.checks)


def test_the_overlay_runs_and_keeps_the_is456_ties_in_the_schedule():
    result = CO.design_column(forces(900.0), geom(), {"seismic": {"zone": "IV", "frame": "SMRF"}})
    kinds = [zone["kind"] for zone in result.stirrups]
    assert "confining" in kinds
    assert "tie" in kinds  # the Cl 26.5.3.2 ties survived the overlay's rewrite
    assert any(row.name.startswith("ductile") for row in result.checks)
    assert any(item["action"] == "joint_check_manual" for item in result.referrals)
    assert any("largest beam bar" in text for text in result.notes)
    assert "ductile_state" not in result.extras


def test_the_overlay_can_be_switched_off():
    result = CO.design_column(forces(900.0), geom(), {"seismic": {"zone": "V", "frame": "SMRF"}, "is13920": "off"})
    assert any("switched off" in text for text in result.notes)
    assert not any(row.name.startswith("ductile") for row in result.checks)


def test_a_column_below_the_ductile_minimum_dimension_is_disclosed():
    result = CO.design_column(forces(400.0), geom(230.0, 230.0), {"seismic": {"zone": "IV", "frame": "SMRF"}})
    assert any("7.1" in text for text in result.warnings)
    assert result.status == C.STATUS_FAIL


def test_a_missing_detailing_sibling_becomes_a_referral_not_a_crash(monkeypatch):
    from ..design import rcc

    class Empty(object):
        pass

    monkeypatch.setattr(rcc, "detailing", Empty(), raising=False)
    result = CO.design_column(forces(900.0), geom(), {"seismic": {"zone": "IV", "frame": "SMRF"}})
    assert result.status in (C.STATUS_PASS, C.STATUS_RESIZED)
    assert any("this build does not carry" in text for text in result.notes)
    assert any(item["action"] == "joint_check_manual" for item in result.referrals)
    assert json.dumps(result.to_dict())


def test_an_overlay_that_raises_is_disclosed_not_propagated(monkeypatch):
    from ..design import rcc

    class Broken(object):
        StirrupZone = None

        @staticmethod
        def apply_13920(result, kind, ctx=None, state=None):
            raise RuntimeError("overlay exploded")

    monkeypatch.setattr(rcc, "detailing", Broken(), raising=False)
    result = CO.design_column(forces(900.0), geom(), {"seismic": {"zone": "IV", "frame": "SMRF"}})
    assert any("overlay exploded" in text for text in result.warnings)
    assert any(item["action"] == "joint_check_manual" for item in result.referrals)


def test_an_unreadable_seismic_zone_takes_the_conservative_branch():
    result = CO.design_column(forces(900.0), geom(), {"seismic": {"zone": "IX"}})
    assert any("not understood" in text for text in result.warnings)
    assert json.dumps(result.to_dict())
