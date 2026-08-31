"""The takedown keystone battery: conservation on the committed fixtures with
hand-placed frames, the exact solver against closed-form three-moment values,
the IS 456 coefficient method against Table 12/13 arithmetic, pattern live
loading, the live reduction ladder, masonry wall eccentricities, combination
envelopes and determinism.

Placement is a parallel work stream, so every frame here is placed BY HAND:
columns on every wall endpoint, beams on every wall line, panels = rooms.
"""

from __future__ import annotations

import json
import os

import pytest

from .. import model as M
from ..adapters import housing as H
from ..adapters import plan_json as A
from ..analysis import ForceEnvelope, to_beam_forces, to_column_forces, to_slab_load
from ..analysis import takedown as T
from ..loads import (
    CASE_DL,
    CASE_LL,
    CASE_LLR,
    AreaLoad,
    CaseKind,
    LineLoad,
    LoadCase,
    LoadModel,
)
from ..loads import combos as C
from ..loads import dead as D
from ..loads import live as L

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

TOL = 0.005  # the hard conservation invariant


def _storeys(n, h=3.0):
    return [M.Storey(index=i, name="S%d" % i, bottom_z_m=i * h, height_m=h) for i in range(n)]


def _rect_poly(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _column(storey, x, y, size=0.3):
    return M.Column(
        id=M.column_id(storey, x_m=x, y_m=y),
        stack_id=M.stack_id(x_m=x, y_m=y),
        storey=storey,
        x_m=x,
        y_m=y,
        width_m=size,
        depth_m=size,
    )


def hand_place(model, slab_storeys=None, beam_depth=0.45, beam_width=0.23):
    """Columns at every wall endpoint, beams on every wall line, panels = rooms."""
    top = max(s.index for s in model.storeys)
    for storey in sorted(s.index for s in model.storeys):
        seen = set()
        for wall in sorted(model.walls_on(storey), key=lambda w: w.id):
            if M.wall_axis(wall) is None:
                continue
            for point in (wall.a, wall.b):
                key = (round(point[0], 3), round(point[1], 3))
                if key in seen:
                    continue
                seen.add(key)
                model.columns.append(_column(storey, point[0], point[1]))
            model.beams.append(
                M.Beam(id="B-s%d-%s" % (storey, wall.id), storey=storey, a=wall.a, b=wall.b, width_m=beam_width, depth_m=beam_depth)
            )
        if slab_storeys is not None and storey not in slab_storeys:
            continue
        for index, room in enumerate(sorted(model.rooms_on(storey), key=lambda r: r.id)):
            rect = M.polygon_rect(room.polygon)
            model.slabs.append(
                M.SlabPanel(
                    id=M.slab_id(storey, index),
                    storey=storey,
                    polygon=list(room.polygon),
                    thickness_m=0.125,
                    lx_m=min(rect[2], rect[3]),
                    ly_m=max(rect[2], rect[3]),
                    kind=M.SlabKind.ROOF if storey == top else M.SlabKind.FLOOR,
                )
            )
    return model


def _loadmodel(model, **dead_options):
    dl = D.build_dead(model, options=dead_options or None)
    ll, llr = L.build_live(model)
    return LoadModel(cases={CASE_DL: dl, CASE_LL: ll, CASE_LLR: llr}, combos=C.generate([CASE_DL, CASE_LL, CASE_LLR]))


@pytest.fixture(scope="module")
def plan_model():
    with open(os.path.join(FIXTURES, "plan_2bhk.json"), "r") as handle:
        payload = json.load(handle)
    return hand_place(A.from_plan(payload, storeys=2))


@pytest.fixture(scope="module")
def plan_result(plan_model):
    return T.run(plan_model, _loadmodel(plan_model))


# ---------------------------------------------------------------------------
# conservation on the committed fixtures (the keystone)
# ---------------------------------------------------------------------------


def test_conservation_on_the_plan_fixture_per_case(plan_result):
    for case in (CASE_DL, CASE_LL, CASE_LLR):
        row = plan_result.conservation[case]
        assert row["applied_kn"] > 0.0
        assert row["rel_err"] < TOL


def test_explicit_cantilever_ring_sends_full_area_load_only_to_declared_root():
    """C7: 1 kPa x 3.048 x 1.219 = 3.715512 kN at y_min.

    The old four-edge route split 1.857756 kN to y_min and y_max. Explicit
    cantilever intent must override the generated ring and leave every
    non-root reaction exactly zero.
    """
    width = 3.048
    projection = 1.219
    model = M.StructuralModel(id="c7-ring", storeys=_storeys(1))
    ring = [
        ("beam-root", (0.0, 0.0), (width, 0.0)),
        ("beam-tip", (0.0, projection), (width, projection)),
        ("beam-left", (0.0, 0.0), (0.0, projection)),
        ("beam-right", (width, 0.0), (width, projection)),
    ]
    model.beams = [
        M.Beam(id=beam_id, storey=0, a=a, b=b, width_m=0.23, depth_m=0.45)
        for beam_id, a, b in ring
    ]
    subject = M.SlabPanel(
        id="slab-s0-2",
        storey=0,
        polygon=_rect_poly(0.0, 0.0, width, projection),
        thickness_m=0.145,
        two_way=False,
        lx_m=projection,
        ly_m=width,
        span_kind="cantilever",
        cantilever_backing_edge="y_min",
        cantilever_backing_support_ids=["beam-root"],
        cantilever_backing_panel_id="slab-s0-0",
        cantilever_backspan_m=3.048,
    )

    edges = T._panel_edges(model, subject)
    assert [edge.supported for edge in edges] == [True, True, True, True]
    assert T._route_explicit_cantilever(subject, edges) is True
    log = M.DisclosureLog()
    T._assign_edge_profiles(edges, width, projection, False, log, subject.id)
    reactions = [
        edge.peak_unit
        * edge.factor
        * T._profile_area(edge.profile, edge.length(), edge.ramp_m)
        if edge.profile
        else 0.0
        for edge in edges
    ]

    assert reactions[0] == pytest.approx(width * projection, abs=1.0e-9)
    assert reactions[0] == pytest.approx(3.715512, abs=1.0e-9)
    assert reactions[1:] == pytest.approx([0.0, 0.0, 0.0], abs=1.0e-12)
    assert [member[0].id for member in edges[0].members] == ["beam-root"]
    assert [entry.code for entry in log.entries] == ["W_CANTILEVER"]

    ordinary = M.SlabPanel(
        id="slab-regular-ring",
        storey=0,
        polygon=list(subject.polygon),
        two_way=False,
        lx_m=projection,
        ly_m=width,
    )
    ordinary_edges = T._panel_edges(model, ordinary)
    ordinary_log = M.DisclosureLog()
    assert T._route_explicit_cantilever(ordinary, ordinary_edges) is False
    T._assign_edge_profiles(
        ordinary_edges,
        width,
        projection,
        False,
        ordinary_log,
        ordinary.id,
    )
    ordinary_reactions = [
        edge.peak_unit
        * edge.factor
        * T._profile_area(edge.profile, edge.length(), edge.ramp_m)
        if edge.profile
        else 0.0
        for edge in ordinary_edges
    ]
    assert ordinary_reactions == pytest.approx(
        [1.857756, 1.857756, 0.0, 0.0],
        abs=1.0e-9,
    )


def test_conservation_on_the_housing_fixture_with_its_gable_roof():
    with open(os.path.join(FIXTURES, "housing_2storey.json"), "r") as handle:
        design = json.load(handle)
    model = H.from_housing(design)[0]
    assert model.meta["roof"]["type"] == "gable"
    # slabs on the ground floor only: the gable roof loads the eave members
    hand_place(model, slab_storeys={0})
    result = T.run(model, _loadmodel(model))
    for case in (CASE_DL, CASE_LL, CASE_LLR):
        assert result.conservation[case]["rel_err"] < TOL
    # the pitched roof actually landed: LLR reached the footings
    assert result.conservation[CASE_LLR]["applied_kn"] > 0.0


def test_every_footing_load_is_downward(plan_result):
    for record in plan_result.footing_loads["columns"].values():
        assert record["p_dl_kn"] > 0.0
    for record in plan_result.footing_loads["walls"].values():
        assert record["n_dl_kn_m"] >= 0.0


# ---------------------------------------------------------------------------
# exact continuous runs vs closed form (three-moment / Clapeyron)
# ---------------------------------------------------------------------------


def test_two_span_run_matches_the_closed_form():
    """Two equal spans L, UDL w on both, knife ends.

    Three-moment at B: 2 M_B (2L) = -6 (2 w L^3 / 24) -> M_B = -w L^2 / 8.
    With w = 10, L = 4: M_B = -20 kNm.  Reactions: R_A = wL/2 + M_B/L =
    20 - 5 = 15 kN, R_B = 2 wL - 2 R_A = 50 kN.
    """
    out = T.solve_continuous(
        [{"l": 4.0, "segs": [(0.0, 4.0, 10.0, 10.0)]}, {"l": 4.0, "segs": [(0.0, 4.0, 10.0, 10.0)]}]
    )
    assert out["support_moments"] == pytest.approx([0.0, -20.0, 0.0])
    assert out["reactions"] == pytest.approx([15.0, 50.0, 15.0])
    assert sum(out["reactions"]) == pytest.approx(80.0)


def test_three_span_run_matches_the_closed_form():
    """Three equal spans L, UDL w everywhere.

    Symmetry gives M_1 = M_2 = M.  Equation at support 1:
    2 M (L + L) + M L = -6 (w L^3/24 + w L^3/24) = -w L^3 / 2
    -> 5 M L = -w L^3 / 2 -> M = -w L^2 / 10 (the classic -0.100 w L^2).
    w = 10, L = 4: M = -16 kNm; R_end = wL/2 + M/L = 16, R_int = 44.
    """
    span = {"l": 4.0, "segs": [(0.0, 4.0, 10.0, 10.0)]}
    out = T.solve_continuous([dict(span), dict(span), dict(span)])
    assert out["support_moments"] == pytest.approx([0.0, -16.0, -16.0, 0.0])
    assert out["reactions"] == pytest.approx([16.0, 44.0, 44.0, 16.0])


def test_single_span_cases_pin_the_simple_statics():
    udl = T.solve_continuous([{"l": 4.0, "segs": [(0.0, 4.0, 10.0, 10.0)]}])
    assert udl["spans"][0]["m_max"] == pytest.approx(20.0)  # w l^2 / 8
    point = T.solve_continuous([{"l": 4.0, "points": [(2.0, 25.0)]}])
    assert point["spans"][0]["m_max"] == pytest.approx(25.0)  # P l / 4
    tri = T.solve_continuous([{"l": 4.0, "segs": [(0.0, 2.0, 0.0, 20.0), (2.0, 4.0, 20.0, 0.0)]}])
    assert tri["spans"][0]["m_max"] == pytest.approx(20.0 * 16.0 / 12.0)  # p l^2 / 12
    assert tri["reactions"] == pytest.approx([20.0, 20.0])


# ---------------------------------------------------------------------------
# equivalent-UDL conversions (traced clauses)
# ---------------------------------------------------------------------------


def test_equivalent_udl_factors_are_the_classic_closed_forms():
    assert T.eq_udl_triangle_bending(10.0, 3.0) == pytest.approx(10.0)  # w lx / 3
    assert T.eq_udl_triangle_shear(10.0, 3.0) == pytest.approx(7.5)  # w lx / 4
    r = 1.5
    assert T.eq_udl_trapezoid_bending(10.0, 3.0, r) == pytest.approx(15.0 * (1.0 - 1.0 / (3.0 * r * r)))
    assert T.eq_udl_trapezoid_shear(10.0, 3.0, r) == pytest.approx(15.0 * (1.0 - 1.0 / (2.0 * r)))
    # r = 1 degenerates to the triangle values
    assert T.eq_udl_trapezoid_bending(10.0, 3.0, 1.0) == pytest.approx(T.eq_udl_triangle_bending(10.0, 3.0))


# ---------------------------------------------------------------------------
# the coefficient method (IS 456 Cl 22.5.1, Tables 12 and 13)
# ---------------------------------------------------------------------------


def _four_span_model(w_dl=10.0, w_ll=8.0, lengths=(4.0, 4.0, 4.0, 4.0)):
    m = M.StructuralModel(id="coeff", storeys=_storeys(1))
    x = 0.0
    xs = [0.0]
    for length in lengths:
        x += length
        xs.append(x)
    for x in xs:
        m.columns.append(_column(0, x, 0.0))
    dl = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    ll = LoadCase(name=CASE_LL, kind=CaseKind.LIVE)
    for i in range(len(lengths)):
        beam = M.Beam(id="B-%d" % i, storey=0, a=(xs[i], 0.0), b=(xs[i + 1], 0.0), width_m=0.23, depth_m=0.45)
        m.beams.append(beam)
        dl.line.append(LineLoad(element_id=beam.id, w1_kn_m=w_dl, w2_kn_m=w_dl, a=0.0, b=1.0, kind=CaseKind.DEAD, source="test"))
        ll.line.append(LineLoad(element_id=beam.id, w1_kn_m=w_ll, w2_kn_m=w_ll, a=0.0, b=1.0, kind=CaseKind.LIVE, source="test"))
    lm = LoadModel(cases={CASE_DL: dl, CASE_LL: ll}, combos=C.generate([CASE_DL, CASE_LL]))
    return m, lm


def test_coefficient_method_matches_table_12_and_13_arithmetic():
    """Four equal 4 m spans, DL 10 and LL 8 kN/m, UL01 = 1.5(DL + LL).

    End span mid:      1.5 (10x16/12 + 8x16/10)          = 39.2  kNm
    Interior span mid: 1.5 (10x16/16 + 8x16/12)          = 31.0  kNm
    Support next end:  1.5 (-10x16/10 - 8x16/9)          = -45.33 kNm
    End support shear: 1.5 (0.4x10x4 + 0.45x8x4)         = 45.6  kN
    Penultimate inner: 1.5 (0.55x10x4 + 0.6x8x4)         = 61.8  kN
    """
    m, lm = _four_span_model()
    result = T.run(m, lm)
    assert result.beam_runs[0]["method"] == "coeff"
    e0 = result.envelopes["B-0"]
    e1 = result.envelopes["B-1"]
    assert e0.method == "coeff"
    assert e0.stations[1].m_pos_max_knm == pytest.approx(1.5 * (10 * 16 / 12.0 + 8 * 16 / 10.0), rel=1e-6)
    assert e1.stations[1].m_pos_max_knm == pytest.approx(1.5 * (10 * 16 / 16.0 + 8 * 16 / 12.0), rel=1e-6)
    assert e0.stations[2].m_neg_min_knm == pytest.approx(1.5 * (-0.1 * 10 * 16 - 8 * 16 / 9.0), rel=1e-6)
    assert e0.stations[0].v_max_kn == pytest.approx(1.5 * (0.4 * 10 * 4 + 0.45 * 8 * 4), rel=1e-6)
    assert e1.stations[0].v_max_kn == pytest.approx(1.5 * (0.55 * 10 * 4 + 0.6 * 8 * 4), rel=1e-6)
    # reactions stay exact statics, so the invariant holds
    for case in (CASE_DL, CASE_LL):
        assert result.conservation[case]["rel_err"] < TOL


def test_unequal_spans_fail_the_guard_and_fall_back_to_exact():
    m, lm = _four_span_model(lengths=(4.0, 4.0, 4.0, 2.5))
    result = T.run(m, lm)
    assert result.beam_runs[0]["method"] == "exact"
    assert "W_ANA_COEFF_INAPPLICABLE" in [e.code for e in result.log.entries]
    reason = [r for r in result.beam_runs if r["method_reason"]][0]["method_reason"]
    assert "15 percent" in reason


def test_forcing_the_exact_method_via_opts():
    m, lm = _four_span_model()
    result = T.run(m, lm, opts={"method": "exact"})
    assert result.beam_runs[0]["method"] == "exact"


# ---------------------------------------------------------------------------
# pattern live loading
# ---------------------------------------------------------------------------


def _two_span_ll_model(w_ll=8.0, span=4.0):
    m = M.StructuralModel(id="pattern", storeys=_storeys(1))
    for i in range(3):
        m.columns.append(_column(0, span * i, 0.0))
    dl = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    ll = LoadCase(name=CASE_LL, kind=CaseKind.LIVE)
    for i in range(2):
        beam = M.Beam(id="B-%d" % i, storey=0, a=(span * i, 0.0), b=(span * (i + 1), 0.0), width_m=0.23, depth_m=0.45)
        m.beams.append(beam)
        ll.line.append(LineLoad(element_id=beam.id, w1_kn_m=w_ll, w2_kn_m=w_ll, a=0.0, b=1.0, kind=CaseKind.LIVE, source="test"))
    lm = LoadModel(cases={CASE_DL: dl, CASE_LL: ll}, combos=C.generate([CASE_DL, CASE_LL]))
    return m, lm


def test_pattern_loading_gives_a_span_maximum_above_the_all_loaded_case():
    """Two equal spans, live load only, UL01 = 1.5(DL + LL) with DL empty.

    Span 0 loaded alone: M_B = -w L^2/16, R_A = 7wL/16, max sagging at
    x = 7L/16: M = w (7L/16)^2 / 2 = 49 w L^2 / 512.  Both spans loaded gives
    only w L^2 / 16 at midspan.  With w = 8, L = 4: 12.25 vs 8.0 kNm.
    """
    m, lm = _two_span_ll_model()
    result = T.run(m, lm)
    w, span = 8.0, 4.0
    envelope = result.envelopes["B-0"]
    assert envelope.stations[1].m_pos_max_knm == pytest.approx(1.5 * 49.0 * w * span * span / 512.0, rel=1e-9)
    assert envelope.stations[1].m_pos_max_knm > 1.5 * w * span * span / 16.0
    # support moment still comes from both spans loaded
    assert envelope.stations[2].m_neg_min_knm == pytest.approx(1.5 * -w * span * span / 8.0, rel=1e-9)


def test_single_span_monolithic_end_allowance_wl2_over_24():
    """One span between two columns: SS midspan plus the disclosed partial
    fixity allowance -W l/24 at the column ends (W = w l)."""
    m = M.StructuralModel(id="mono", storeys=_storeys(1))
    m.columns.append(_column(0, 0.0, 0.0))
    m.columns.append(_column(0, 4.0, 0.0))
    m.beams.append(M.Beam(id="B-0", storey=0, a=(0.0, 0.0), b=(4.0, 0.0), width_m=0.23, depth_m=0.45))
    dl = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    dl.line.append(LineLoad(element_id="B-0", w1_kn_m=10.0, w2_kn_m=10.0, a=0.0, b=1.0, kind=CaseKind.DEAD, source="test"))
    lm = LoadModel(cases={CASE_DL: dl}, combos=C.generate([CASE_DL]))
    result = T.run(m, lm)
    envelope = result.envelopes["B-0"]
    assert envelope.stations[1].m_pos_max_knm == pytest.approx(1.5 * 20.0, rel=1e-9)  # 1.5 w l^2 / 8
    assert envelope.stations[0].m_neg_min_knm == pytest.approx(1.5 * -(40.0 * 4.0) / 24.0, rel=1e-9)
    entry = [e for e in result.log.entries if e.code == "W_ANA_COEFF_INAPPLICABLE"][0]
    assert "w l^2/24" in entry.message


# ---------------------------------------------------------------------------
# live load reduction (IS 875-2 Cl 3.2.1 / 3.2.2)
# ---------------------------------------------------------------------------


def _tower(n_storeys=5):
    m = M.StructuralModel(id="tower", storeys=_storeys(n_storeys))
    corners = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    lines = [((0.0, 0.0), (4.0, 0.0)), ((0.0, 4.0), (4.0, 4.0)), ((0.0, 0.0), (0.0, 4.0)), ((4.0, 0.0), (4.0, 4.0))]
    for s in range(n_storeys):
        for x, y in corners:
            m.columns.append(_column(s, x, y))
        for i, (a, b) in enumerate(lines):
            m.beams.append(M.Beam(id="B-s%d-%d" % (s, i), storey=s, a=a, b=b, width_m=0.23, depth_m=0.4))
        m.rooms.append(
            M.RoomPoly(id=M.room_id(s, "r"), storey=s, name="Room", occupancy=M.Occupancy.HABITABLE, polygon=_rect_poly(0, 0, 4, 4), area_m2=16.0)
        )
        m.slabs.append(
            M.SlabPanel(
                id=M.slab_id(s, 0),
                storey=s,
                polygon=_rect_poly(0, 0, 4, 4),
                thickness_m=0.125,
                lx_m=4.0,
                ly_m=4.0,
                kind=M.SlabKind.ROOF if s == n_storeys - 1 else M.SlabKind.FLOOR,
            )
        )
    return m


def test_live_reduction_ladder_reaches_40_percent_at_five_floors():
    m = _tower(5)
    result = T.run(m, _loadmodel(m))
    ground = [c for c in result.column_loads if c["storey"] == 0]
    assert ground and all(c["floors_carried"] == 5 for c in ground)
    for entry in ground:
        assert entry["reduction"] == pytest.approx(0.40)
        raw = entry["p_ll_kn"] + entry["p_llr_kn"]
        assert entry["p_ll_reduced_kn"] == pytest.approx(0.60 * raw, rel=1e-6)
    # the ladder along the stack: roof counts first
    corner_stack = M.stack_id(x_m=0.0, y_m=0.0)
    floors_by_storey = {c["storey"]: c["floors_carried"] for c in result.column_loads if c["stack_id"] == corner_stack}
    assert floors_by_storey == {4: 1, 3: 2, 2: 3, 1: 4, 0: 5}
    for case in (CASE_DL, CASE_LL, CASE_LLR):
        assert result.conservation[case]["rel_err"] < TOL


def test_reduction_is_blocked_above_5_kpa_and_conservation_uses_raw_loads():
    m = _tower(5)
    dl = D.build_dead(m)
    heavy = LoadCase(name=CASE_LL, kind=CaseKind.LIVE)
    for s in range(5):
        heavy.area.append(AreaLoad(panel_id=M.slab_id(s, 0), q_kpa=7.5, kind=CaseKind.LIVE, source="test storage"))
    lm = LoadModel(cases={CASE_DL: dl, CASE_LL: heavy}, combos=C.generate([CASE_DL, CASE_LL]))
    result = T.run(m, lm)
    ground = [c for c in result.column_loads if c["storey"] == 0][0]
    assert ground["reduction"] == pytest.approx(0.0)
    assert ground["reduction_applied"] is False
    assert ground["p_ll_reduced_kn"] == pytest.approx(ground["p_ll_kn"], rel=1e-9)
    assert result.conservation[CASE_LL]["rel_err"] < TOL


# ---------------------------------------------------------------------------
# masonry wall stresses (spec step 7)
# ---------------------------------------------------------------------------


def _masonry_two_rooms(t=0.23):
    m = M.StructuralModel(id="masonry", system=M.System.LOAD_BEARING_MASONRY, storeys=_storeys(1))

    def wall(a, b, role):
        orient = "h" if a[1] == b[1] else "v"
        pos = a[1] if orient == "h" else a[0]
        start = min(a[0], b[0]) if orient == "h" else min(a[1], b[1])
        piece = M.WallLine(id=M.wall_id(0, orient, pos, start), storey=0, a=a, b=b, thickness_m=t, role=role, bearing=True)
        m.walls.append(piece)
        return piece

    wall((0.0, 0.0), (8.0, 0.0), M.WallRole.EXTERIOR)
    wall((0.0, 4.0), (8.0, 4.0), M.WallRole.EXTERIOR)
    west = wall((0.0, 0.0), (0.0, 4.0), M.WallRole.EXTERIOR)
    east = wall((8.0, 0.0), (8.0, 4.0), M.WallRole.EXTERIOR)
    middle = wall((4.0, 0.0), (4.0, 4.0), M.WallRole.INTERIOR)
    for i, x0 in enumerate((0.0, 4.0)):
        m.rooms.append(
            M.RoomPoly(id=M.room_id(0, "r%d" % i), storey=0, name="Room", occupancy=M.Occupancy.HABITABLE, polygon=_rect_poly(x0, 0, 4, 4), area_m2=16.0)
        )
        m.slabs.append(
            M.SlabPanel(id=M.slab_id(0, i), storey=0, polygon=_rect_poly(x0, 0, 4, 4), thickness_m=0.125, lx_m=4.0, ly_m=4.0, kind=M.SlabKind.ROOF)
        )
    return m, west, east, middle


def test_wall_eccentricity_t_over_6_outside_and_zero_inside():
    """Slab reactions act at t/6 from the centreline toward their panel
    (centre-third bearing).  An exterior wall carrying one slab reads exactly
    e = t/6; the middle wall carries equal slabs both sides and reads ~0."""
    m, west, east, middle = _masonry_two_rooms()
    result = T.run(m, _loadmodel(m, parapet=False))
    stresses = {ws.wall_id: ws for ws in result.wall_stresses}
    t = 0.23
    assert stresses[west.id].e_m == pytest.approx(t / 6.0, rel=1e-9)
    assert stresses[west.id].e_over_t == pytest.approx(1.0 / 6.0, rel=1e-9)
    assert stresses[east.id].e_m == pytest.approx(t / 6.0, rel=1e-9)
    assert stresses[middle.id].e_m == pytest.approx(0.0, abs=1e-9)
    # the middle wall carries two panels: more axial per metre than the sides
    assert stresses[middle.id].n_kn_m > stresses[west.id].n_kn_m
    for case in (CASE_DL, CASE_LLR):
        assert result.conservation[case]["rel_err"] < TOL
    # walls reach the footing records with their bearing length
    assert west.id in result.footing_loads["walls"]


# ---------------------------------------------------------------------------
# secondary framing and the dependency graph
# ---------------------------------------------------------------------------


def _secondary_model():
    m = M.StructuralModel(id="secondary", storeys=_storeys(1))
    for x, y in [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)]:
        m.columns.append(_column(0, x, y))
    perimeter = [((0.0, 0.0), (6.0, 0.0)), ((0.0, 4.0), (6.0, 4.0)), ((0.0, 0.0), (0.0, 4.0)), ((6.0, 0.0), (6.0, 4.0))]
    for i, (a, b) in enumerate(perimeter):
        m.beams.append(M.Beam(id="P-%d" % i, storey=0, a=a, b=b, width_m=0.23, depth_m=0.45))
    m.beams.append(M.Beam(id="SEC-0", storey=0, a=(3.0, 0.0), b=(3.0, 4.0), width_m=0.23, depth_m=0.4, kind=M.BeamKind.SECONDARY))
    for i, x0 in enumerate((0.0, 3.0)):
        m.slabs.append(
            M.SlabPanel(id=M.slab_id(0, i), storey=0, polygon=_rect_poly(x0, 0, 3, 4), thickness_m=0.125, lx_m=3.0, ly_m=4.0, kind=M.SlabKind.ROOF)
        )
    return m


def test_secondary_beam_frames_into_the_primaries_and_conserves():
    m = _secondary_model()
    result = T.run(m, _loadmodel(m, parapet=False))
    secondary_run = [r for r in result.beam_runs if "SEC-0" in r["beam_ids"]][0]
    assert [s["kind"] for s in secondary_run["supports"]] == ["frame", "frame"]
    for case in (CASE_DL, CASE_LLR):
        assert result.conservation[case]["rel_err"] < TOL
    # both primaries picked up a mid point load: their mid sagging exceeds the
    # bare self weight value by the framing reaction share
    assert result.envelopes["P-0"].stations[1].m_pos_max_knm > 0.0


def test_cyclic_secondary_framing_hard_fails_with_the_registered_code():
    m = M.StructuralModel(id="cycle", storeys=_storeys(1))
    layout = [
        ((0.0, 1.0), (2.0, 1.0), (0.0, 1.0)),
        ((2.0, 0.0), (2.0, 2.0), (2.0, 0.0)),
        ((1.0, 2.0), (3.0, 2.0), (3.0, 2.0)),
        ((1.0, 1.0), (1.0, 3.0), (1.0, 3.0)),
    ]
    dl = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    for i, (a, b, colpt) in enumerate(layout):
        m.beams.append(M.Beam(id="CY-%d" % i, storey=0, a=a, b=b, width_m=0.23, depth_m=0.4, kind=M.BeamKind.SECONDARY))
        m.columns.append(_column(0, colpt[0], colpt[1]))
        dl.line.append(LineLoad(element_id="CY-%d" % i, w1_kn_m=5.0, w2_kn_m=5.0, a=0.0, b=1.0, kind=CaseKind.DEAD, source="test"))
    with pytest.raises(T.AnalysisError) as caught:
        T.run(m, LoadModel(cases={CASE_DL: dl}, combos=C.generate([CASE_DL])))
    assert caught.value.code == "E_FRAMING_DEPTH"
    assert caught.value.code in M.REGISTRY


def test_floating_column_hard_fails_as_a_transfer_condition():
    m = _tower(2)
    m.columns = [c for c in m.columns if c.storey != 0]  # remove the ground lift
    with pytest.raises(T.AnalysisError) as caught:
        T.run(m, _loadmodel(m))
    assert caught.value.code == "E_TRANSFER_REQUIRED"


# ---------------------------------------------------------------------------
# the conservation guard itself
# ---------------------------------------------------------------------------


def test_conservation_guard_raises_the_registered_error_code():
    row = T.check_conservation("DL", 100.0, 100.4, 0.005)
    assert row["rel_err"] == pytest.approx(0.004)
    with pytest.raises(T.AnalysisError) as caught:
        T.check_conservation("DL", 100.0, 99.0, 0.005)
    assert caught.value.code == "E_ANA_CONSERVATION"
    assert M.registry_severity("E_ANA_CONSERVATION") == M.Severity.ERROR


def test_loads_addressed_to_unknown_elements_refuse_loudly():
    m = _tower(1)
    dl = D.build_dead(m)
    dl.line.append(LineLoad(element_id="B-nowhere", w1_kn_m=5.0, w2_kn_m=5.0, a=0.0, b=1.0, kind=CaseKind.DEAD, source="test"))
    with pytest.raises(T.AnalysisError) as caught:
        T.run(m, LoadModel(cases={CASE_DL: dl}, combos=C.generate([CASE_DL])))
    assert caught.value.code == "E_BAD_ENVELOPE"


# ---------------------------------------------------------------------------
# the storey ledger (the seismic contract)
# ---------------------------------------------------------------------------


def test_storey_ledger_shape_and_halving(plan_model, plan_result):
    ledger = plan_result.storey_ledger
    assert sorted(ledger) == [0, 1]
    for level, row in ledger.items():
        assert set(row) == {"w_dl_kn", "w_ll_kn", "ll_fraction_basis_kpa", "z_m"}
        assert row["w_dl_kn"] > 0.0
    # z from Storey.bottom_z_m + height (critic resolution 2)
    storey0 = plan_model.storey(0)
    assert ledger[0]["z_m"] == pytest.approx(storey0.bottom_z_m + storey0.height_m)
    # the ground halves of walls and columns go to the foundation, so the
    # ledger total sits below the applied dead load
    total_dl = sum(row["w_dl_kn"] for row in ledger.values())
    assert total_dl < plan_result.conservation[CASE_DL]["applied_kn"]
    # roof imposed stays out of the ledger (IS 1893 Cl 7.3.2): the roof level
    # carries no floor LL in this fixture
    assert ledger[1]["w_ll_kn"] == pytest.approx(0.0)
    assert ledger[0]["ll_fraction_basis_kpa"] == pytest.approx(3.0)  # corridor governs


# ---------------------------------------------------------------------------
# envelopes and the designer converters
# ---------------------------------------------------------------------------


def test_envelopes_cover_every_element_type_with_governing_ids(plan_result):
    types = {}
    for envelope in plan_result.envelopes.values():
        types.setdefault(envelope.element_type, envelope)
    assert set(types) == {"beam", "column", "wall", "footing", "slab"}
    beam = types["beam"]
    assert beam.governing and all(v == "UL01" for v in beam.governing.values())
    assert [s.station for s in beam.stations] == [0.0, 0.5, 1.0]


def test_slab_envelope_carries_factored_and_service_pressures(plan_result):
    slab_env = [e for e in plan_result.envelopes.values() if e.element_type == "slab"][0]
    # floor panel: DL 4.625, LL 2.0 or 3.0 -> w_u = 1.5 (DL + LL)
    assert slab_env.w_u_kpa == pytest.approx(1.5 * slab_env.w_service_kpa, rel=1e-9)
    load = to_slab_load(slab_env)
    assert load.w_u_kpa == pytest.approx(slab_env.w_u_kpa)
    assert load.w_service_kpa == pytest.approx(slab_env.w_service_kpa)


def test_beam_converter_returns_positive_design_magnitudes():
    m, lm = _four_span_model()
    result = T.run(m, lm)
    forces = to_beam_forces(result.envelopes["B-0"])
    assert forces.mu_sag_mid_knm == pytest.approx(39.2, rel=1e-6)
    assert forces.mu_hog_end_a_knm == pytest.approx(0.0, abs=1e-9)  # outer end support
    assert forces.mu_hog_end_b_knm == pytest.approx(45.3333333, rel=1e-4)
    assert forces.vu_a_kn == pytest.approx(45.6, rel=1e-6)
    assert forces.combo_map()["m_pos"] == "UL01"
    with pytest.raises(ValueError):
        to_beam_forces(ForceEnvelope(element_id="x", element_type="column"))


def test_column_converter_carries_pu_lengths_and_storey(plan_result, plan_model):
    col_env = [e for e in plan_result.envelopes.values() if e.element_type == "column" and e.storey == 0][0]
    forces = to_column_forces(col_env)
    assert forces.pu_kn > 0.0
    assert forces.mux_knm == 0.0 and forces.muy_knm == 0.0
    assert forces.lex_m == pytest.approx(plan_model.storey(0).height_m)
    assert forces.storey == 0


def test_column_axial_is_factored_from_the_reduced_imposed_load():
    m = _tower(5)
    result = T.run(m, _loadmodel(m))
    ground_entry = [c for c in result.column_loads if c["storey"] == 0][0]
    envelope = result.envelopes[ground_entry["column_id"]]
    expected = 1.5 * (ground_entry["p_dl_kn"] + ground_entry["p_ll_reduced_kn"])
    assert envelope.stations[0].n_max_kn == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# trace and determinism
# ---------------------------------------------------------------------------


def test_takedown_traces_its_clause_calls():
    m, lm = _four_span_model()
    result = T.run(m, lm)
    refs = set(entry["ref"] for entry in result.trace)
    assert "Table 12" in refs and "Table 13" in refs
    assert any(entry["ref"] == "3.2.1" for entry in result.trace)  # live reduction


def test_takedown_is_deterministic_byte_for_byte(plan_model):
    lm = _loadmodel(plan_model)
    first = json.dumps(T.run(plan_model, lm).to_dict(), sort_keys=True)
    second = json.dumps(T.run(plan_model, lm).to_dict(), sort_keys=True)
    assert first == second


def test_serialized_result_shape_is_json_clean(plan_result):
    wire = plan_result.to_dict()
    text = json.dumps(wire, sort_keys=True)
    assert "storey_ledger" in wire and "envelopes" in wire and "disclosures" in wire
    parsed = json.loads(text)
    assert parsed["conservation"][CASE_DL]["rel_err"] < TOL
