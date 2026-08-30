"""Pins for the lateral chain: seismic forces, wind forces, rigid-diaphragm shares.

Every number below is hand-checkable from the clause it names; nothing is
copied back out of the implementation. The seismic golden vector is the classic
textbook four-storey block, line by line.

Imports are relative for the reason given in the other test modules: an
absolute GPLAN.structural import would give the clause registry a second module
identity.
"""

from __future__ import annotations

import json

import pytest

from ..analysis import diaphragm
from ..analysis.diaphragm import LateralContext, masonry_modulus, pier_stiffness
from ..codes import is875
from ..loads import seismic
from ..loads.seismic import SeismicContext, build_seismic
from ..loads.wind import WindContext, build_wind, roof_uplift_check, wall_panel_pressures
from ..model import (
    Column,
    DisclosureLog,
    Material,
    Occupancy,
    Opening,
    OpeningKind,
    Provenance,
    RoomPoly,
    Storey,
    StructuralModel,
    WallLine,
    WallRole,
    column_id,
    stack_id,
    wall_id,
)


# ---------------------------------------------------------------------------
# fixtures built in the test, so every input is visible next to its expectation
# ---------------------------------------------------------------------------


def _equal_storeys(count, w_kn=2000.0, height=3.0):
    """`count` storeys of equal weight, 0-based, level i at (i + 1) x height."""
    return [
        {"storey": index, "w_dl_kn": w_kn, "z_top_m": height * (index + 1)}
        for index in range(count)
    ]


def _model(storeys, height_m=3.0, room=(0.0, 0.0, 6.0, 4.0)):
    model = StructuralModel(
        id="lateral-fixture",
        storeys=[
            Storey(index=index, name="S" + str(index), bottom_z_m=height_m * index, height_m=height_m)
            for index in range(storeys)
        ],
    )
    x, y, w, h = room
    for index in range(storeys):
        model.rooms.append(
            RoomPoly(
                id="room-s" + str(index),
                storey=index,
                name="hall",
                occupancy=Occupancy.HABITABLE,
                polygon=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                area_m2=w * h,
            )
        )
    return model


def _column(model, storey, x, y, width=0.3, depth=0.3):
    column = Column(
        id=column_id(storey, x_m=x, y_m=y),
        stack_id=stack_id(x_m=x, y_m=y),
        storey=storey,
        x_m=x,
        y_m=y,
        width_m=width,
        depth_m=depth,
    )
    model.columns.append(column)
    return column


def _wall(model, storey, a, b, thickness=0.23, openings=(), role=WallRole.INTERIOR):
    orient = "h" if abs(a[1] - b[1]) < 1e-9 else "v"
    pos = a[1] if orient == "h" else a[0]
    start = min(a[0], b[0]) if orient == "h" else min(a[1], b[1])
    line = WallLine(
        id=wall_id(storey, orient, pos, start),
        storey=storey,
        a=a,
        b=b,
        thickness_m=thickness,
        role=role,
        material=Material.BRICK_MASONRY,
        openings=list(openings),
    )
    model.walls.append(line)
    return line


def _four_columns(model, storey, xs=(0.0, 6.0), ys=(0.0, 4.0), width=0.3, depth=0.3):
    for x in xs:
        for y in ys:
            _column(model, storey, x, y, width, depth)


# ===========================================================================
# IS 1893 equivalent static
# ===========================================================================


def test_seismic_golden_four_storey_block_line_by_line():
    # Four storeys of 2000 kN at 3 m centres, zone III, soil II, SMRF, infilled,
    # base plan 20 m square. Every line is the printed clause worked by hand.
    ctx = SeismicContext(zone="III", soil="II", importance=1.0, system="smrf", infilled=True)
    cases, report = build_seismic(_equal_storeys(4), {"x_m": 20.0, "y_m": 20.0}, ctx)

    assert report["seismic_weight_kn"] == 8000.0
    assert report["height_m"] == 12.0
    # Table 3, Table 8, Table 9.
    assert report["z"] == 0.16
    assert report["i"] == 1.0
    assert report["r"] == 5.0

    block = report["directions"]["x"]
    # Cl 7.6.2(c): Ta = 0.09 h / sqrt(d) = 0.09 x 12 / sqrt(20).
    assert block["ta_s"] == pytest.approx(0.09 * 12.0 / (20.0 ** 0.5), rel=1e-12)
    assert block["ta_s"] == pytest.approx(0.2414953, abs=1e-7)
    # Cl 6.4.2: 0.10 s < Ta < 0.55 s on soil II, so the 2.5 plateau.
    assert block["sa_g"] == 2.5
    assert block["sa_branch"] == "plateau"
    # Ah = (0.16 / 2) x 2.5 / (5 / 1.0) = 0.04.
    assert block["ah"] == pytest.approx(0.04, rel=1e-12)
    assert block["min_coefficient_governs"] is False
    assert block["ah_min"] == 0.011
    # VB = 0.04 x 8000.
    assert block["base_shear_kn"] == pytest.approx(320.0, rel=1e-12)

    # Cl 7.6.3 with equal weights at h, 2h, 3h, 4h: shares 1 : 4 : 9 : 16 of 30.
    shares = [row["qi_kn"] for row in block["qi"]]
    assert shares == pytest.approx([320.0 * n / 30.0 for n in (1, 4, 9, 16)], rel=1e-12)
    assert sum(shares) == pytest.approx(320.0, rel=1e-12)
    assert [row["h_i_m"] for row in block["qi"]] == [3.0, 6.0, 9.0, 12.0]
    assert [row["share"] for row in block["qi"]] == pytest.approx(
        [1 / 30.0, 4 / 30.0, 9 / 30.0, 16 / 30.0], rel=1e-12
    )

    # A square plan shakes identically both ways.
    assert report["directions"]["y"]["base_shear_kn"] == pytest.approx(320.0, rel=1e-12)


def test_seismic_emits_both_signs_on_both_axes_in_a_fixed_order():
    ctx = SeismicContext(system="smrf")
    cases, _ = build_seismic(_equal_storeys(4), {"x_m": 20.0, "y_m": 20.0}, ctx)
    assert [case["name"] for case in cases] == ["EQX+", "EQX-", "EQY+", "EQY-"]

    plus, minus = cases[0], cases[1]
    assert all(force["fy_kn"] == 0.0 for force in plus["storey_forces"])
    assert [force["fx_kn"] for force in minus["storey_forces"]] == pytest.approx(
        [-force["fx_kn"] for force in plus["storey_forces"]], rel=1e-12
    )
    # The Y cases carry their force on fy, not fx.
    assert all(force["fx_kn"] == 0.0 for force in cases[2]["storey_forces"])
    assert cases[2]["storey_forces"][0]["fy_kn"] > 0.0
    # The documented storey-force shape, exactly.
    assert set(plus["storey_forces"][0]) == {"storey", "fx_kn", "fy_kn", "z_m", "source"}


def test_seismic_minimum_base_shear_floor_governs_and_says_so():
    # 30 storeys, 90 m, 15 m base dimension, zone II: Ta = 0.09 x 90 / sqrt(15)
    # = 2.0916 s, Sa/g = 1.36 / Ta = 0.6503, Ah = 0.05 x 0.6503 / 5 = 0.00650,
    # under the Cl 7.2.2 floor of 0.007 for zone II.
    ctx = SeismicContext(zone="II", soil="II", system="smrf", infilled=True)
    rows = _equal_storeys(30, w_kn=1000.0)
    _, report = build_seismic(rows, {"x_m": 15.0, "y_m": 15.0}, ctx)
    block = report["directions"]["x"]

    assert block["ta_s"] == pytest.approx(0.09 * 90.0 / (15.0 ** 0.5), rel=1e-12)
    assert block["sa_branch"] == "decay"
    assert block["ah_computed"] == pytest.approx(0.05 * block["sa_g"] / 5.0, rel=1e-12)
    assert block["ah_computed"] < 0.007
    assert block["min_coefficient_governs"] is True
    assert block["ah"] == 0.007
    assert block["ah_clause"].endswith("7.2.2")
    assert block["base_shear_kn"] == pytest.approx(0.007 * 30000.0, rel=1e-12)


def test_table_10_live_fraction_is_applied_here_and_reported_per_storey():
    ctx = SeismicContext(system="omrf")
    rows = [
        {"storey": 0, "w_dl_kn": 1000.0, "w_ll_kn": 200.0, "ll_basis_kpa": 2.0, "z_top_m": 3.0},
        {"storey": 1, "w_dl_kn": 1000.0, "w_ll_kn": 200.0, "ll_basis_kpa": 5.0, "z_top_m": 6.0},
        {
            "storey": 2,
            "w_dl_kn": 800.0,
            "w_ll_kn": 150.0,
            "ll_basis_kpa": 1.5,
            "z_top_m": 9.0,
            "roof": True,
        },
    ]
    _, report = build_seismic(rows, {"x_m": 10.0, "y_m": 12.0}, ctx)

    # Table 10: 0.25 at or below 3 kPa, 0.50 above. Cl 7.3.2 drops the roof.
    assert report["ll_fraction"] == {"0": 0.25, "1": 0.50, "2": 0.0}
    weights = {row["storey"]: row["w_kn"] for row in report["storey_weights"]}
    assert weights[0] == pytest.approx(1000.0 + 0.25 * 200.0)
    assert weights[1] == pytest.approx(1000.0 + 0.50 * 200.0)
    assert weights[2] == pytest.approx(800.0)
    assert report["seismic_weight_kn"] == pytest.approx(1050.0 + 1100.0 + 800.0)


def test_a_storey_without_a_live_basis_takes_the_conservative_row_and_discloses_it():
    log = DisclosureLog()
    ctx = SeismicContext(system="omrf")
    rows = [{"storey": 0, "w_dl_kn": 1000.0, "w_ll_kn": 400.0, "z_top_m": 3.0}]
    _, report = build_seismic(rows, {"x_m": 10.0, "y_m": 10.0}, ctx, log=log)

    assert report["ll_fraction"]["0"] == 0.50
    assert report["storey_weights"][0]["ll_basis_assumed"] is True
    assert "W_LOAD_OCCUPANCY_FALLBACK" in log.codes()
    assert "W_LOAD_OCCUPANCY_FALLBACK" in [
        entry["code"] for entry in report["disclosures"]["disclosures"]
    ]


def test_the_structural_system_is_required_and_nothing_defaults_it():
    # Finding 41: no OMRF default is baked in anywhere below structural/api.py.
    with pytest.raises(ValueError) as excinfo:
        SeismicContext()
    assert "system" in str(excinfo.value)
    with pytest.raises(ValueError):
        SeismicContext(system="  ")
    # An unknown system is a lookup failure in the code module, not a fallback.
    with pytest.raises(KeyError):
        build_seismic(_equal_storeys(1), {"x_m": 8.0, "y_m": 8.0}, SeismicContext(system="wood"))


def test_only_five_percent_damping_is_tabulated():
    with pytest.raises(ValueError) as excinfo:
        SeismicContext(system="omrf", damping=0.07)
    assert "damping" in str(excinfo.value)


def test_hi_is_measured_from_the_base_elevation_not_from_the_storey_index():
    # Finding 2: a 4.2 m stilt makes hi and the index disagree, and hi wins.
    ctx = SeismicContext(system="omrf")
    rows = [
        {"storey": 0, "w_dl_kn": 1000.0, "z_top_m": 4.2},
        {"storey": 1, "w_dl_kn": 1000.0, "z_top_m": 7.2},
    ]
    _, report = build_seismic(rows, {"x_m": 10.0, "y_m": 10.0}, ctx)
    block = report["directions"]["x"]
    assert [row["h_i_m"] for row in block["qi"]] == [4.2, 7.2]
    weighted = [1000.0 * 4.2 ** 2, 1000.0 * 7.2 ** 2]
    total = sum(weighted)
    assert [row["qi_kn"] for row in block["qi"]] == pytest.approx(
        [block["base_shear_kn"] * value / total for value in weighted], rel=1e-12
    )


def test_base_z_offsets_every_height():
    ctx = SeismicContext(system="omrf")
    rows = [{"storey": 0, "w_dl_kn": 1000.0, "z_top_m": 13.0}]
    _, report = build_seismic(rows, {"x_m": 10.0, "y_m": 10.0}, ctx, base_z_m=10.0)
    assert report["height_m"] == 3.0
    assert report["directions"]["x"]["qi"][0]["h_i_m"] == 3.0


def test_seismic_is_deterministic():
    ctx = SeismicContext(system="smrf")
    first = build_seismic(_equal_storeys(3), {"x_m": 12.0, "y_m": 9.0}, ctx)
    second = build_seismic(_equal_storeys(3), {"x_m": 12.0, "y_m": 9.0}, ctx)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_seismic_traces_the_clauses_it_used():
    entries = []
    ctx = SeismicContext(zone="III", soil="II", system="smrf")
    build_seismic(_equal_storeys(2), {"x_m": 10.0, "y_m": 10.0}, ctx, trace=entries)
    refs = {entry.code + " " + entry.ref for entry in entries}
    for expected in ("Table 3", "Table 9", "6.4.2", "7.6.2(c)", "7.2.2", "7.6.1", "7.6.3"):
        assert seismic.CODE + " " + expected in refs


# ===========================================================================
# IS 875 (Part 3) static wind
# ===========================================================================


def test_k2_interpolates_at_the_midpoint_between_tabulated_heights():
    # Table 2, terrain category 2: 1.00 at 10 m, 1.05 at 15 m.
    assert is875.part3_k2(2, 10.0) == 1.00
    assert is875.part3_k2(2, 15.0) == 1.05
    assert is875.part3_k2(2, 12.5) == pytest.approx(1.025, rel=1e-12)
    # Under the table the 10 m row stands, and the range says so.
    assert is875.part3_k2(2, 3.0) == 1.00
    assert is875.part3_k2_range(3.0) == "below_table"


def test_wind_storey_force_arithmetic_on_a_two_storey_box():
    # Vb 44 m/s, terrain 2, both levels under 10 m so k2 = 1.00 and Vz = Vb.
    # pz = 0.6 x 44^2 / 1000 = 1.1616 kPa. Plan 10 m (X) x 8 m (Y), h = 6 m.
    # Wind along X blows on the 8 m faces: w = 8, l = 10, h/w = 0.75, l/w = 1.25,
    # Table 5 gives 0.7 windward and -0.25 leeward, so Cnet = 0.95.
    # Tributary heights 3.0 m and 1.5 m (the bottom half storey goes to ground).
    ctx = WindContext(Vb_ms=44.0, terrain_category=2)
    envelope = {"width_m": 10.0, "depth_m": 8.0, "storey_z_tops": [3.0, 6.0]}
    cases, report = build_wind(envelope, ctx)

    assert report["levels"][0]["pz_kpa"] == pytest.approx(1.1616, rel=1e-12)
    assert [level["tributary_h_m"] for level in report["levels"]] == [3.0, 1.5]

    block = report["directions"]["x"]
    assert block["b_perp_m"] == 8.0
    assert block["h_over_w"] == pytest.approx(0.75)
    assert block["l_over_w"] == pytest.approx(1.25)
    assert block["cnet"] == pytest.approx(0.95, rel=1e-12)
    assert [row["f_kn"] for row in block["levels"]] == pytest.approx(
        [1.1616 * 0.95 * 8.0 * 3.0, 1.1616 * 0.95 * 8.0 * 1.5], rel=1e-12
    )
    assert block["base_shear_kn"] == pytest.approx(1.1616 * 0.95 * 8.0 * 4.5, rel=1e-12)

    # Wind along Y blows on the 10 m faces instead.
    assert report["directions"]["y"]["b_perp_m"] == 10.0
    assert [case["name"] for case in cases] == ["WX+", "WX-", "WY+", "WY-"]
    assert cases[1]["storey_forces"][0]["fx_kn"] == pytest.approx(
        -cases[0]["storey_forces"][0]["fx_kn"], rel=1e-12
    )
    assert set(cases[0]["storey_forces"][0]) == {"storey", "fx_kn", "fy_kn", "z_m", "source"}


def test_the_static_method_warns_above_twenty_metres():
    log = DisclosureLog()
    ctx = WindContext(Vb_ms=44.0)
    envelope = {
        "width_m": 20.0,
        "depth_m": 20.0,
        "storey_z_tops": [2.5 * n for n in range(1, 11)],  # 25 m
    }
    _, report = build_wind(envelope, ctx, log=log)
    limits = report["static_limits"]
    assert report["height_m"] == 25.0
    assert limits["height_ok"] is False
    assert limits["within_static_method"] is False
    assert any("above the 20.0 m" in reason for reason in limits["reasons"])
    assert "W_WIND_STATIC_LIMIT" in log.codes()

    # A 6 m box of the same footprint stays inside every gate.
    _, calm = build_wind({"width_m": 20.0, "depth_m": 20.0, "storey_z_tops": [3.0, 6.0]}, ctx)
    assert calm["static_limits"]["within_static_method"] is True


def test_a_slender_block_trips_the_slenderness_and_friction_gates():
    ctx = WindContext(Vb_ms=44.0)
    envelope = {"width_m": 40.0, "depth_m": 3.0, "storey_z_tops": [3.0 * n for n in range(1, 7)]}
    _, report = build_wind(envelope, ctx)
    reasons = " ".join(report["static_limits"]["reasons"])
    assert "height over least width" in reasons
    assert "plan aspect" in reasons
    assert report["static_limits"]["friction_negligible"] is False


def test_kd_ka_kc_are_off_by_default_and_all_applied_when_asked_for():
    envelope = {"width_m": 10.0, "depth_m": 8.0, "storey_z_tops": [3.0, 6.0]}
    _, plain = build_wind(envelope, WindContext(Vb_ms=44.0))
    row = plain["directions"]["x"]["levels"][0]
    assert (row["kd"], row["ka"], row["kc"]) == (1.0, 1.0, 1.0)
    assert row["pd_kpa"] == pytest.approx(row["pz_kpa"], rel=1e-12)

    _, reduced = build_wind(envelope, WindContext(Vb_ms=44.0, use_kd_ka_kc=True))
    row = reduced["directions"]["x"]["levels"][0]
    # Tributary area 8 m x 3 m = 24 m2, Table 4 between 10 m2 (1.0) and 25 m2 (0.9).
    expected_ka = is875.part3_ka(24.0)
    assert (row["kd"], row["kc"]) == (0.9, 0.9)
    assert row["ka"] == pytest.approx(expected_ka, rel=1e-12)
    assert row["pd_kpa"] == pytest.approx(row["pz_kpa"] * 0.9 * 0.9 * expected_ka, rel=1e-12)


def test_cpi_stays_out_of_the_frame_shear_and_comes_back_from_the_panel_hook():
    envelope = {"width_m": 10.0, "depth_m": 8.0, "storey_z_tops": [3.0, 6.0]}
    ctx = WindContext(Vb_ms=44.0, permeability="normal")
    _, report = build_wind(envelope, ctx)
    block = report["directions"]["x"]
    # Cnet is external only: windward minus leeward, no internal term.
    assert block["cnet"] == pytest.approx(block["cpe_windward"] - block["cpe_leeward"], rel=1e-12)

    panels = wall_panel_pressures(envelope, ctx)
    assert panels["cpi"] == {"magnitude": 0.2, "plus": 0.2, "minus": -0.2}
    face = panels["levels"][0]["directions"]["x"]["faces"]["windward"]
    pd = panels["levels"][0]["directions"]["x"]["pd_kpa"]
    assert face["p_net_cpi_plus_kpa"] == pytest.approx(pd * (0.7 - 0.2), rel=1e-12)
    assert face["p_net_cpi_minus_kpa"] == pytest.approx(pd * (0.7 + 0.2), rel=1e-12)
    assert face["p_net_governing_kpa"] == pytest.approx(pd * 0.9, rel=1e-12)


def test_pitched_roof_uplift_against_nine_tenths_of_the_roof_dead_load():
    log = DisclosureLog()
    ctx = WindContext(Vb_ms=44.0)
    # h/w 0.4 and a 10 degree pitch: Table 6 windward Cpe -1.2, Cpi +0.2, so the
    # net outward pressure is 1.4 pd. A 0.35 kPa sheet roof resists 0.315 kPa.
    checked = roof_uplift_check(10.0, 0.4, 1.1616, 0.35, ctx, log)
    assert checked["cpe_windward"] == pytest.approx(-1.2, rel=1e-12)
    assert checked["uplift_kpa"] == pytest.approx(1.1616 * 1.4, rel=1e-12)
    assert checked["resistance_kpa"] == pytest.approx(0.315, rel=1e-12)
    assert checked["uplift_governs"] is True
    assert "W_WIND_UPLIFT" in log.codes()

    heavy = roof_uplift_check(10.0, 0.4, 1.1616, 5.0, ctx, DisclosureLog())
    assert heavy["uplift_governs"] is False


def test_wind_needs_a_speed_or_a_zone_and_defaults_neither():
    with pytest.raises(ValueError):
        build_wind({"width_m": 8.0, "depth_m": 8.0, "storey_z_tops": [3.0]}, WindContext())
    _, report = build_wind(
        {"width_m": 8.0, "depth_m": 8.0, "storey_z_tops": [3.0]}, WindContext(zone="4")
    )
    assert report["vb_ms"] == 47.0
    assert "Fig. 1" in report["vb_source"]


def test_wind_is_deterministic():
    envelope = {"width_m": 10.0, "depth_m": 8.0, "storey_z_tops": [3.0, 6.0]}
    ctx = WindContext(Vb_ms=44.0)
    assert json.dumps(build_wind(envelope, ctx), sort_keys=True) == json.dumps(
        build_wind(envelope, ctx), sort_keys=True
    )


# ===========================================================================
# rigid diaphragm
# ===========================================================================


def test_a_symmetric_four_column_storey_splits_its_shear_equally():
    model = _model(1)
    _four_columns(model, 0)
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)})
    block = result.storey(0, "x")

    assert block.cr_x_m == pytest.approx(3.0)
    assert block.cr_y_m == pytest.approx(2.0)
    assert block.esi_m == pytest.approx(0.0, abs=1e-12)
    # Each of the four identical columns takes a quarter of the direct shear.
    assert [share.v_direct_kn for share in block.elements] == pytest.approx([25.0] * 4, rel=1e-12)
    # The accidental eccentricity of Cl 7.8.2 still adds a torsional share, and
    # symmetry makes it the same for all four, so the totals stay equal.
    assert len({round(share.v_kn, 9) for share in block.elements}) == 1
    assert all(share.v_torsion_kn > 0.0 for share in block.elements)

    # 12 Ec Ic / h^3 with Ec = 5000 sqrt(25) = 25000 MPa, I = 0.3^4 / 12.
    expected_k = 12.0 * 25000.0 * 1000.0 * (0.3 ** 4 / 12.0) / 27.0
    assert block.elements[0].k_kn_m == pytest.approx(expected_k, rel=1e-12)
    assert block.sum_k_kn_m == pytest.approx(4.0 * expected_k, rel=1e-12)
    # Columns bend in double curvature: M = V h / 2 at both ends.
    assert block.elements[0].m_top_knm == pytest.approx(block.elements[0].v_kn * 1.5, rel=1e-12)
    assert block.elements[0].m_bot_knm == pytest.approx(block.elements[0].m_top_knm, rel=1e-12)


def test_mixed_column_sections_split_the_shear_by_stiffness():
    # Two columns on the same grid line, so the torsional lever is zero and the
    # split is pure stiffness: k goes as the cube of the dimension along X.
    model = _model(1, room=(0.0, 0.0, 6.0, 4.0))
    _column(model, 0, 0.0, 0.0, width=0.23, depth=0.23)
    _column(model, 0, 6.0, 0.0, width=0.30, depth=0.23)
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 0.0)})
    block = result.storey(0, "x")

    slim, stout = block.elements[0], block.elements[1]
    assert stout.k_kn_m / slim.k_kn_m == pytest.approx((0.30 / 0.23) ** 3, rel=1e-12)
    assert slim.d_m == pytest.approx(0.0, abs=1e-12)
    assert [share.v_torsion_kn for share in block.elements] == [0.0, 0.0]
    total = slim.k_kn_m + stout.k_kn_m
    assert slim.v_kn == pytest.approx(100.0 * slim.k_kn_m / total, rel=1e-12)
    assert stout.v_kn == pytest.approx(100.0 * stout.k_kn_m / total, rel=1e-12)
    assert slim.v_kn + stout.v_kn == pytest.approx(100.0, rel=1e-12)


def test_the_torsional_share_is_additive_only_and_never_relieves_an_element():
    # A stiff wall along the y = 0 edge pulls the rigidity centre off the mass
    # centre; every element still gains shear, none is relieved.
    model = _model(1)
    _four_columns(model, 0)
    _wall(model, 0, (0.0, 0.0), (6.0, 0.0), thickness=0.23)
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)})
    block = result.storey(0, "x")

    assert block.cr_y_m < 1.0  # dragged down to the wall
    assert block.esi_m > 0.0
    offsets = {share.element_id: share.d_m for share in block.elements}
    assert min(offsets.values()) < 0.0 < max(offsets.values())
    # Both sides of the rigidity centre gain, which is the conservative choice.
    for share in block.elements:
        assert share.v_torsion_kn >= 0.0
        if abs(share.d_m) > 1e-9:
            assert share.v_kn > share.v_direct_kn
    assert sum(share.v_kn for share in block.elements) > 100.0
    assert "additive only" in " ".join(result.assumptions)


def test_an_eccentric_wall_layout_trips_the_five_percent_torsion_gate():
    log = DisclosureLog()
    model = _model(1)
    _four_columns(model, 0)
    _wall(model, 0, (0.0, 0.0), (6.0, 0.0), thickness=0.23)
    result = diaphragm.run(
        model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)}, log=log
    )
    block = result.storey(0, "x")

    assert block.bi_m == pytest.approx(4.0)
    assert abs(block.esi_m) > 0.05 * block.bi_m
    assert block.torsion_irregular is True
    assert "W_EQ_TORSION_IRREGULAR" in log.codes()
    # Cl 7.8.2 branches, both reported, the more severe one used.
    assert block.ed_amplified_m == pytest.approx(1.5 * block.esi_m + 0.05 * 4.0, rel=1e-12)
    assert block.ed_reduced_m == pytest.approx(block.esi_m - 0.05 * 4.0, rel=1e-12)
    assert block.ed_governing_m == pytest.approx(block.ed_amplified_m, rel=1e-12)

    # A centred layout of the same columns stays inside the gate.
    plain = _model(1)
    _four_columns(plain, 0)
    calm = diaphragm.run(plain, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)})
    assert calm.storey(0, "x").torsion_irregular is False


def test_storey_drift_is_checked_against_the_code_limit():
    log = DisclosureLog()
    model = _model(1)
    _four_columns(model, 0, width=0.2, depth=0.2)
    result = diaphragm.run(
        model, {"x": {0: 200.0}}, centres_of_mass={0: (3.0, 2.0)}, log=log
    )
    block = result.storey(0, "x")

    expected_k = 4.0 * 12.0 * 25000.0 * 1000.0 * (0.2 ** 4 / 12.0) / 27.0
    assert block.sum_k_kn_m == pytest.approx(expected_k, rel=1e-12)
    assert block.drift_m == pytest.approx(200.0 / expected_k, rel=1e-12)
    assert block.drift_limit_m == pytest.approx(0.004 * 3.0, rel=1e-12)
    assert block.drift_exceeded is True
    assert "W_EQ_DRIFT" in log.codes()

    stiff = _model(1)
    _four_columns(stiff, 0, width=0.45, depth=0.45)
    quiet = diaphragm.run(stiff, {"x": {0: 200.0}}, centres_of_mass={0: (3.0, 2.0)})
    assert quiet.storey(0, "x").drift_exceeded is False


def test_the_masonry_pier_formula_at_a_hand_computed_point():
    # Em = 550 fm = 2750 MPa = 2 750 000 kN/m2; h/L = 1 so the denominator is
    # 1 + 3 = 4, and k = 2 750 000 x 0.23 / 4 = 158 125 kN/m.
    em = masonry_modulus(5.0)
    assert em == 2750.0
    assert pier_stiffness(em, 0.23, 3.0, 3.0) == pytest.approx(158125.0, rel=1e-12)
    # h/L = 2: denominator 8 + 6 = 14.
    assert pier_stiffness(em, 0.23, 6.0, 3.0) == pytest.approx(2750.0 * 1000.0 * 0.23 / 14.0, rel=1e-12)
    # The cantilever variant quadruples the cubic term: 4 + 3 = 7.
    assert pier_stiffness(em, 0.23, 3.0, 3.0, cantilever=True) == pytest.approx(
        2750.0 * 1000.0 * 0.23 / 7.0, rel=1e-12
    )


def test_a_wall_with_no_known_openings_takes_the_disclosed_gross_knockdown():
    log = DisclosureLog()
    model = _model(1)
    _four_columns(model, 0)
    wall = _wall(model, 0, (0.0, 0.0), (6.0, 0.0), thickness=0.23)
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)}, log=log)
    share = result.element(0, "x", wall.id)

    gross = pier_stiffness(masonry_modulus(5.0), 0.23, 3.0, 6.0)
    assert share.k_kn_m == pytest.approx(0.8 * gross, rel=1e-12)
    assert "knockdown" in share.stiffness_source
    assert "W_ASSUMED_OPENINGS" in log.codes()


def test_dressed_openings_split_the_wall_into_piers():
    log = DisclosureLog()
    model = _model(1)
    _four_columns(model, 0)
    door = Opening(
        id="op-1",
        kind=OpeningKind.DOOR,
        offset_m=3.0,
        width_m=1.0,
        provenance=Provenance.DRESSED,
    )
    wall = _wall(model, 0, (0.0, 0.0), (6.0, 0.0), thickness=0.23, openings=[door])
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)}, log=log)
    share = result.element(0, "x", wall.id)

    # A 1.0 m door centred at 3.0 m leaves two 2.5 m piers of full storey height.
    assert len(share.piers) == 2
    assert [pier["length_m"] for pier in share.piers] == pytest.approx([2.5, 2.5])
    one_pier = pier_stiffness(masonry_modulus(5.0), 0.23, 3.0, 2.5)
    assert share.k_kn_m == pytest.approx(2.0 * one_pier, rel=1e-12)
    assert "piers between dressed openings" in share.stiffness_source
    assert "W_ASSUMED_OPENINGS" not in log.codes()


def test_two_dressed_openings_give_three_piers_at_their_own_heights():
    model = _model(1)
    _four_columns(model, 0)
    door = Opening(
        id="op-d",
        kind=OpeningKind.DOOR,
        offset_m=1.5,
        width_m=1.0,
        sill_m=0.0,
        head_m=2.1,
        provenance=Provenance.DRESSED,
    )
    window = Opening(
        id="op-w",
        kind=OpeningKind.WINDOW,
        offset_m=4.5,
        width_m=1.0,
        sill_m=0.9,
        head_m=2.1,
        provenance=Provenance.DRESSED,
    )
    wall = _wall(model, 0, (0.0, 0.0), (6.0, 0.0), thickness=0.23, openings=[door, window])
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)})
    share = result.element(0, "x", wall.id)

    # Door over 1.0 to 2.0 m and window over 4.0 to 5.0 m leave 1.0, 2.0, 1.0 m
    # piers; each takes the height of the tallest opening it flanks, 2.1 m for
    # the first two and the 1.2 m window height for the last.
    assert [pier["length_m"] for pier in share.piers] == pytest.approx([1.0, 2.0, 1.0])
    assert [pier["height_m"] for pier in share.piers] == pytest.approx([2.1, 2.1, 1.2])
    em = masonry_modulus(5.0)
    expected = (
        pier_stiffness(em, 0.23, 2.1, 1.0)
        + pier_stiffness(em, 0.23, 2.1, 2.0)
        + pier_stiffness(em, 0.23, 1.2, 1.0)
    )
    assert share.k_kn_m == pytest.approx(expected, rel=1e-12)


def test_wall_shear_per_metre_and_the_cantilever_moment_accumulate_down():
    model = _model(2)
    for storey in range(2):
        _four_columns(model, storey)
        _wall(model, storey, (0.0, 0.0), (6.0, 0.0), thickness=0.23)
    result = diaphragm.run(
        model,
        {"x": {0: 150.0, 1: 90.0}},
        centres_of_mass={0: (3.0, 2.0), 1: (3.0, 2.0)},
    )
    upper = [share for share in result.storey(1, "x").elements if share.element_type == "wall"][0]
    lower = [share for share in result.storey(0, "x").elements if share.element_type == "wall"][0]

    assert upper.v_per_m_kn_m == pytest.approx(upper.v_kn / 6.0, rel=1e-12)
    assert upper.m_base_knm == pytest.approx(upper.v_kn * 3.0, rel=1e-12)
    # The moment carried into the storey below is the one that left the storey above.
    assert lower.m_top_knm == pytest.approx(upper.m_base_knm, rel=1e-12)
    assert lower.m_base_knm == pytest.approx(upper.m_base_knm + lower.v_kn * 3.0, rel=1e-12)
    assert upper.stack_id is not None and upper.stack_id == lower.stack_id


def test_only_walls_parallel_to_the_shaking_participate():
    model = _model(1)
    along_x = _wall(model, 0, (0.0, 0.0), (6.0, 0.0))
    along_y = _wall(model, 0, (0.0, 0.0), (0.0, 4.0))
    result = diaphragm.run(model, {"x": {0: 60.0}, "y": {0: 60.0}}, centres_of_mass={0: (3.0, 2.0)})

    x_ids = [share.element_id for share in result.storey(0, "x").elements]
    y_ids = [share.element_id for share in result.storey(0, "y").elements]
    assert x_ids == [along_x.id]
    assert y_ids == [along_y.id]


def test_parapets_railings_and_hairline_walls_are_not_lateral_elements():
    model = _model(1)
    _four_columns(model, 0)
    parapet = _wall(model, 0, (0.0, 0.0), (6.0, 0.0), role=WallRole.PARAPET)
    thin = _wall(model, 0, (0.0, 4.0), (6.0, 4.0), thickness=0.075)
    result = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)})
    ids = [share.element_id for share in result.storey(0, "x").elements]
    assert parapet.id not in ids
    assert thin.id not in ids
    assert len(ids) == 4


def test_a_direction_with_nothing_resisting_it_is_an_error_on_the_ladder():
    log = DisclosureLog()
    model = _model(1)
    _wall(model, 0, (0.0, 0.0), (6.0, 0.0))
    result = diaphragm.run(model, {"y": {0: 40.0}}, centres_of_mass={0: (3.0, 2.0)}, log=log)
    assert result.storey(0, "y") is None
    assert "E_NO_BEARING_DIRECTION" in log.codes()


def test_the_missing_mass_ledger_falls_back_to_the_area_centroid_and_says_so():
    log = DisclosureLog()
    model = _model(1)
    _four_columns(model, 0)
    result = diaphragm.run(model, {"x": {0: 100.0}}, log=log)
    block = result.storey(0, "x")
    assert (block.cm_x_m, block.cm_y_m) == pytest.approx((3.0, 2.0))
    assert "plan area centroid" in result.cm_source
    assert "W_TORSION" in log.codes()
    assert any("centre of mass" in line for line in result.assumptions)


def test_cracked_sections_scale_the_stiffness_without_moving_the_shares():
    model = _model(1)
    _four_columns(model, 0)
    gross = diaphragm.run(model, {"x": {0: 100.0}}, centres_of_mass={0: (3.0, 2.0)})
    cracked = diaphragm.run(
        model,
        {"x": {0: 100.0}},
        LateralContext(cracked_sections=True),
        centres_of_mass={0: (3.0, 2.0)},
    )
    assert cracked.storey(0, "x").sum_k_kn_m == pytest.approx(
        0.7 * gross.storey(0, "x").sum_k_kn_m, rel=1e-12
    )
    # Uniform modifiers cannot change a ratio, only the drift.
    assert [share.v_kn for share in cracked.storey(0, "x").elements] == pytest.approx(
        [share.v_kn for share in gross.storey(0, "x").elements], rel=1e-12
    )
    assert cracked.storey(0, "x").drift_m == pytest.approx(
        gross.storey(0, "x").drift_m / 0.7, rel=1e-12
    )


def test_storey_shears_come_from_the_plain_force_dicts_by_accumulation():
    ctx = SeismicContext(zone="III", soil="II", system="smrf")
    cases, _ = build_seismic(_equal_storeys(4), {"x_m": 20.0, "y_m": 20.0}, ctx)
    shears = diaphragm.storey_shears_from_case(cases[0])
    forces = [320.0 * n / 30.0 for n in (1, 4, 9, 16)]
    assert shears["x"][3] == pytest.approx(forces[3], rel=1e-12)
    assert shears["x"][2] == pytest.approx(forces[3] + forces[2], rel=1e-12)
    assert shears["x"][0] == pytest.approx(320.0, rel=1e-12)
    assert shears["y"] == {}
    # The minus case gives the same magnitudes.
    assert diaphragm.storey_shears_from_case(cases[1])["x"] == pytest.approx(shears["x"])


def test_the_overturning_summary_differences_the_shears_back_into_forces():
    model = _model(2)
    for storey in range(2):
        _four_columns(model, storey)
    result = diaphragm.run(
        model,
        {"x": {0: 150.0, 1: 90.0}},
        centres_of_mass={0: (3.0, 2.0), 1: (3.0, 2.0)},
    )
    summary = result.overturning["x"]
    assert summary["base_shear_kn"] == 150.0
    assert [row["f_kn"] for row in summary["levels"]] == pytest.approx([60.0, 90.0])
    assert summary["overturning_moment_knm"] == pytest.approx(60.0 * 3.0 + 90.0 * 6.0, rel=1e-12)
    # The base storey shares reach the footing loads.
    assert set(result.base_forces["x"]) == {
        share.element_id for share in result.storey(0, "x").elements
    }


def test_the_lateral_result_serializes_and_is_deterministic():
    model = _model(2)
    for storey in range(2):
        _four_columns(model, storey)
        _wall(model, storey, (0.0, 0.0), (6.0, 0.0))
    shears = {"x": {0: 150.0, 1: 90.0}, "y": {0: 150.0, 1: 90.0}}
    first = diaphragm.run(model, shears, centres_of_mass={0: (3.0, 2.0), 1: (3.0, 2.0)})
    second = diaphragm.run(model, shears, centres_of_mass={0: (3.0, 2.0), 1: (3.0, 2.0)})
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )
    payload = first.to_dict()
    assert payload["materials"]["ec_mpa"] == pytest.approx(25000.0)
    assert payload["materials"]["em_mpa"] == pytest.approx(2750.0)
    assert [entry["storey"] for entry in payload["storeys"]] == [0, 0, 1, 1]


def test_every_disclosure_code_this_module_raises_is_in_the_registry():
    # make_disclosure raises on an unregistered code, so a run that trips every
    # branch is itself the registry check.
    log = DisclosureLog()
    masonry = _model(1)
    _four_columns(masonry, 0, width=0.2, depth=0.2)
    _wall(masonry, 0, (0.0, 0.0), (6.0, 0.0))
    diaphragm.run(masonry, {"x": {0: 400.0}, "y": {0: 400.0}}, log=log)

    flexible = _model(1)
    _four_columns(flexible, 0, width=0.2, depth=0.2)
    diaphragm.run(flexible, {"x": {0: 400.0}}, log=log)

    one_way = _model(1)
    _wall(one_way, 0, (0.0, 0.0), (6.0, 0.0))
    diaphragm.run(one_way, {"y": {0: 400.0}}, log=log)

    assert set(log.codes()) >= {
        "E_NO_BEARING_DIRECTION",
        "W_ASSUMED_OPENINGS",
        "W_EQ_DRIFT",
        "W_EQ_TORSION_IRREGULAR",
        "W_TORSION",
    }
