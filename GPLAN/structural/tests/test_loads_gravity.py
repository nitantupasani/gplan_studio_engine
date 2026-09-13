"""Pins for loads/__init__.py, loads/dead.py, loads/live.py and loads/combos.py.

Numbers are recomputed by hand next to each assertion from the data tables:
    rcc 25 kN/m3, brick 20, plaster 20.4 x 12 mm both faces, floor finish 1.5,
    flat roof finish 2.0, sunken 4.25 @ 250 mm, residential 2.0, corridor 3.0,
    roofs 0.75 / 1.5, sloping-roof rule 0.75 - 0.02(alpha - 10) floored 0.4.
"""

from __future__ import annotations

import json
import math
import os

import pytest

from .. import model as M
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

PLASTER_2F = 2.0 * 20.4 * 0.012  # kN per m2 of wall face, both faces
BRICK_230 = 20.0 * 0.23 + PLASTER_2F  # 5.0896 kN/m2
GABLE_COS = 1.0 / math.sqrt(1.0 + 0.6 * 0.6)


def _storeys(n, h=3.0):
    return [M.Storey(index=i, name="S%d" % i, bottom_z_m=i * h, height_m=h) for i in range(n)]


def _rect_poly(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _room(storey, name, x, y, w, h, occupancy=M.Occupancy.HABITABLE, unknown=False):
    return M.RoomPoly(
        id=M.room_id(storey, name),
        storey=storey,
        name=name,
        occupancy=occupancy,
        polygon=_rect_poly(x, y, w, h),
        area_m2=w * h,
        interior_unknown=unknown,
    )


def _slab(storey, index, x, y, w, h, kind=M.SlabKind.FLOOR, t=0.125):
    return M.SlabPanel(
        id=M.slab_id(storey, index),
        storey=storey,
        polygon=_rect_poly(x, y, w, h),
        thickness_m=t,
        lx_m=min(w, h),
        ly_m=max(w, h),
        kind=kind,
    )


def _wall(storey, a, b, t=0.23, role=M.WallRole.INTERIOR, bearing=None):
    orient = "h" if a[1] == b[1] else "v"
    pos = a[1] if orient == "h" else a[0]
    start = min(a[0], b[0]) if orient == "h" else min(a[1], b[1])
    return M.WallLine(
        id=M.wall_id(storey, orient, pos, start),
        storey=storey,
        a=a,
        b=b,
        thickness_m=t,
        role=role,
        bearing=bearing,
    )


def _perimeter_walls(storey, x, y, w, h, t=0.23):
    return [
        _wall(storey, (x, y), (x + w, y), t, role=M.WallRole.EXTERIOR),
        _wall(storey, (x, y + h), (x + w, y + h), t, role=M.WallRole.EXTERIOR),
        _wall(storey, (x, y), (x, y + h), t, role=M.WallRole.EXTERIOR),
        _wall(storey, (x + w, y), (x + w, y + h), t, role=M.WallRole.EXTERIOR),
    ]


def _area_total(case, panel_id=None):
    return sum(a.q_kpa for a in case.area if panel_id is None or a.panel_id == panel_id)


def _line_loads_on(case, element_id):
    return [x for x in case.line if x.element_id == element_id]


def _codes(model):
    return sorted(set(w.code for w in model.warnings))


# ---------------------------------------------------------------------------
# dead: slabs
# ---------------------------------------------------------------------------


def test_slab_dead_load_takes_finish_by_role():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5, kind=M.SlabKind.FLOOR))
    m.slabs.append(_slab(0, 1, 4, 0, 4, 5, kind=M.SlabKind.ROOF))
    dl = D.build_dead(m, options={"parapet": False})
    # An explicitly thin legacy panel is normalized to the 150 mm project
    # minimum: 25 x 0.150 = 3.750 self; finishes then follow the panel role.
    assert _area_total(dl, M.slab_id(0, 0)) == pytest.approx(3.750 + 1.5)
    assert _area_total(dl, M.slab_id(0, 1)) == pytest.approx(3.750 + 2.0)


def test_sunken_fill_lands_on_bath_panels_scaled_by_depth():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.rooms.append(_room(0, "bath", 0, 0, 2, 2, occupancy=M.Occupancy.BATH))
    m.slabs.append(_slab(0, 0, 0, 0, 2, 2, kind=M.SlabKind.FLOOR))
    plain = D.build_dead(m, options={"parapet": False})
    sunken = D.build_dead(m, options={"parapet": False, "sunken_bath": True, "sunken_depth_m": 0.125})
    # 4.25 kPa at the 250 mm reference depth, halved for a 125 mm sink
    assert _area_total(sunken) - _area_total(plain) == pytest.approx(4.25 * 0.5)


# ---------------------------------------------------------------------------
# dead: beams
# ---------------------------------------------------------------------------


def test_beam_web_self_weight_deducts_the_adjacent_slab():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5, t=0.125))
    m.beams.append(M.Beam(id="B-web", storey=0, a=(0.0, 0.0), b=(4.0, 0.0), width_m=0.23, depth_m=0.45))
    dl = D.build_dead(m, options={"parapet": False})
    loads = _line_loads_on(dl, "B-web")
    assert len(loads) == 1
    # The same 150 mm project minimum is used for the slab already counted as
    # area load: 25 x 0.23 x (0.45 - 0.150) = 1.725 kN/m.
    assert loads[0].w1_kn_m == pytest.approx(25.0 * 0.23 * 0.300)
    assert loads[0].w2_kn_m == pytest.approx(loads[0].w1_kn_m)


def test_plinth_beam_web_uses_the_full_depth():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5, t=0.125))
    m.beams.append(M.Beam(id="B-pl", storey=0, a=(0.0, 0.0), b=(4.0, 0.0), width_m=0.23, depth_m=0.45, kind=M.BeamKind.PLINTH))
    dl = D.build_dead(m, options={"parapet": False})
    assert _line_loads_on(dl, "B-pl")[0].w1_kn_m == pytest.approx(25.0 * 0.23 * 0.45)


# ---------------------------------------------------------------------------
# dead: walls
# ---------------------------------------------------------------------------


def test_wall_self_weight_rides_on_the_wall_with_plaster_both_faces():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    wall = _wall(0, (0.0, 0.0), (4.0, 0.0))
    m.walls.append(wall)
    dl = D.build_dead(m, options={"parapet": False})
    loads = _line_loads_on(dl, wall.id)
    assert len(loads) == 1
    # (20 x 0.23 + 2 x 20.4 x 0.012) x 3.0 clear = 15.2688 kN/m, on the wall
    # itself: the takedown routes it through find_wall_support
    assert loads[0].w1_kn_m == pytest.approx(BRICK_230 * 3.0)


def test_wall_clear_height_deducts_the_beam_over_it():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    wall = _wall(0, (0.0, 0.0), (4.0, 0.0))
    m.walls.append(wall)
    m.beams.append(M.Beam(id="B-over", storey=0, a=(0.0, 0.0), b=(4.0, 0.0), width_m=0.23, depth_m=0.45))
    dl = D.build_dead(m, options={"parapet": False})
    assert _line_loads_on(dl, wall.id)[0].w1_kn_m == pytest.approx(BRICK_230 * (3.0 - 0.45))


def test_opening_deduction_is_off_by_default_and_exact_when_on():
    def build(deduct, provenance):
        m = M.StructuralModel(id="t", storeys=_storeys(1))
        wall = _wall(0, (0.0, 0.0), (4.0, 0.0))
        wall.openings.append(
            M.Opening(id=M.opening_id(wall.id, 0), kind=M.OpeningKind.DOOR, offset_m=2.0, width_m=1.0, sill_m=0.0, head_m=2.1, provenance=provenance)
        )
        m.walls.append(wall)
        dl = D.build_dead(m, options={"parapet": False, "deduct_openings": deduct})
        return m, _line_loads_on(dl, wall.id)[0].w1_kn_m

    _, w_default = build(False, M.Provenance.DRESSED)
    m_on, w_deducted = build(True, M.Provenance.DRESSED)
    assert w_default == pytest.approx(BRICK_230 * 3.0)
    # 1.0 x 2.1 m2 of wall face removed, smeared over the 4 m length
    assert w_deducted == pytest.approx(BRICK_230 * 3.0 - 1.0 * 2.1 * BRICK_230 / 4.0)
    assert "W_ASSUMED_OPENINGS" not in _codes(m_on)
    m_assumed, _ = build(True, M.Provenance.ASSUMED_MID_WALL)
    assert "W_ASSUMED_OPENINGS" in _codes(m_assumed)


def test_partition_with_no_support_smears_over_its_panel_and_discloses():
    m = M.StructuralModel(id="t", storeys=_storeys(2))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5))
    orphan = _wall(1, (1.0, 2.0), (3.0, 2.0), t=0.115)
    m.walls.append(orphan)
    dl = D.build_dead(m, options={"parapet": False})
    assert not _line_loads_on(dl, orphan.id)
    smear = [a for a in dl.area if orphan.id in a.note]
    assert len(smear) == 1
    w_line = (20.0 * 0.115 + PLASTER_2F) * 3.0
    assert smear[0].q_kpa == pytest.approx(w_line * 2.0 / 20.0)  # exact weight / panel area
    entry = [w for w in m.warnings if w.code == "W_UNIT_NO_PLAN"][0]
    assert orphan.id in entry.element_ids


def test_floating_wall_with_no_panel_is_an_error_disclosure_never_hidden():
    m = M.StructuralModel(id="t", storeys=_storeys(2))
    orphan = _wall(1, (1.0, 2.0), (3.0, 2.0), t=0.115)
    m.walls.append(orphan)
    dl = D.build_dead(m, options={"parapet": False})
    assert "E_TRANSFER_REQUIRED" in _codes(m)
    # the weight still rides on the wall: the takedown will refuse to route it
    assert len(_line_loads_on(dl, orphan.id)) == 1


def test_parapet_default_on_flat_roof_and_toggle():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.walls.extend(_perimeter_walls(0, 0, 0, 4, 5))
    on = D.build_dead(m)
    off = D.build_dead(m, options={"parapet": False})
    parapet_loads = [x for x in on.line if x.note == "parapet"]
    assert parapet_loads and not [x for x in off.line if x.note == "parapet"]
    w_par = (20.0 * 0.115 + PLASTER_2F) * 0.9
    # every emitted parapet load is uniform at w_par
    for load in parapet_loads:
        assert load.w1_kn_m == pytest.approx(w_par)
        assert load.w2_kn_m == pytest.approx(w_par)


# ---------------------------------------------------------------------------
# dead + live: pitched roofs (projected-area v1)
# ---------------------------------------------------------------------------


def _gable_model(rtype="gable"):
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.walls.extend(_perimeter_walls(0, 0, 0, 8, 4))
    m.rooms.append(_room(0, "hall", 0, 0, 8, 4))
    m.meta["roof"] = {"type": rtype, "rise_ratio": 0.3 if rtype in ("gable", "hip") else 0.25}
    m.meta["roof_storey_index"] = 0
    return m


def _line_integral(load, model):
    element = model.by_id(load.element_id)
    length = element.span_m() if isinstance(element, M.Beam) else element.length_m()
    return 0.5 * (load.w1_kn_m + load.w2_kn_m) * (load.b - load.a) * length


def test_gable_roof_goes_one_way_to_the_two_eaves():
    m = _gable_model("gable")
    dl = D.build_dead(m, options={"parapet": False})
    roof_loads = [x for x in dl.line if "roof" in x.note]
    q_plan = 0.35 / GABLE_COS
    # both long (horizontal) eaves take q S/2 = q_plan x 2.0 uniformly
    assert roof_loads
    for load in roof_loads:
        assert load.w1_kn_m == pytest.approx(q_plan * 2.0)
    total = sum(_line_integral(x, m) for x in roof_loads)
    assert total == pytest.approx(q_plan * 32.0)
    assert "N_SLOPE_ALLOWANCE_FLAT" in _codes(m)


def test_hip_roof_tributaries_conserve_the_plan_area_load():
    m = _gable_model("hip")
    dl = D.build_dead(m, options={"parapet": False})
    roof_loads = [x for x in dl.line if "roof" in x.note]
    q_plan = 0.35 / GABLE_COS
    total = sum(_line_integral(x, m) for x in roof_loads)
    assert total == pytest.approx(q_plan * 32.0, rel=1e-6)
    # short (vertical) eaves carry triangles: their loads start or end at zero
    vertical = [x for x in roof_loads if m.by_id(x.element_id).a[0] == m.by_id(x.element_id).b[0]]
    assert vertical and any(min(x.w1_kn_m, x.w2_kn_m) == pytest.approx(0.0, abs=1e-9) for x in vertical)


def test_sloped_roof_live_load_uses_the_part2_formula_with_its_floor():
    m = _gable_model("gable")
    _, llr = L.build_live(m)
    # alpha = atan(0.6) = 30.96 deg -> 0.75 - 0.02 x 20.96 = 0.33 floored at 0.4
    loads = llr.line
    assert loads
    for load in loads:
        assert load.w1_kn_m == pytest.approx(0.4 * 2.0)


# ---------------------------------------------------------------------------
# dead + live: unknown interiors (critic finding 39)
# ---------------------------------------------------------------------------


def test_interior_unknown_takes_the_partition_allowance_and_residential_live():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.rooms.append(_room(0, "unit", 0, 0, 4, 5, occupancy=M.Occupancy.OTHER, unknown=True))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5, kind=M.SlabKind.FLOOR))
    dl = D.build_dead(m, options={"parapet": False})
    allowance = [a for a in dl.area if "allowance" in a.source or "unknown" in a.note]
    assert len(allowance) == 1 and allowance[0].q_kpa == pytest.approx(1.0)
    assert "W_UNIT_NO_PLAN" in _codes(m)
    ll, _ = L.build_live(m)
    assert ll.area[0].q_kpa == pytest.approx(2.0)
    assert "W_LOAD_OCCUPANCY_FALLBACK" not in _codes(m)


# ---------------------------------------------------------------------------
# live: occupancies, roofs, splits
# ---------------------------------------------------------------------------


def test_live_load_reads_the_room_occupancy_per_panel():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.rooms.append(_room(0, "bed", 0, 0, 4, 5))
    m.rooms.append(_room(0, "pass", 4, 0, 2, 5, occupancy=M.Occupancy.CORRIDOR))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5))
    m.slabs.append(_slab(0, 1, 4, 0, 2, 5))
    ll, llr = L.build_live(m)
    by_panel = {a.panel_id: a for a in ll.area}
    assert by_panel[M.slab_id(0, 0)].q_kpa == pytest.approx(2.0)
    assert by_panel[M.slab_id(0, 1)].q_kpa == pytest.approx(3.0)
    assert not llr.area


def test_panel_spanning_rooms_takes_the_maximum_and_discloses():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.rooms.append(_room(0, "bed", 0, 0, 4, 5))
    m.rooms.append(_room(0, "pass", 4, 0, 2, 5, occupancy=M.Occupancy.CORRIDOR))
    m.slabs.append(_slab(0, 0, 0, 0, 6, 5))  # spans both rooms
    ll, _ = L.build_live(m)
    assert ll.area[0].q_kpa == pytest.approx(3.0)
    assert "max of" in ll.area[0].note
    assert "W_LOAD_OCCUPANCY_FALLBACK" in _codes(m)


def test_roof_panels_land_in_llr_at_075_or_15_with_terrace_access():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.rooms.append(_room(0, "bed", 0, 0, 4, 5))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5, kind=M.SlabKind.ROOF))
    ll, llr = L.build_live(m)
    assert not ll.area and llr.area[0].q_kpa == pytest.approx(0.75)
    assert llr.area[0].kind == CaseKind.ROOF_LIVE
    m.cores.append(M.Core(id=M.core_id("st"), kind=M.CoreKind.STAIRS, x_m=0, y_m=0, w_m=1, h_m=2, storeys=[0]))
    _, llr2 = L.build_live(m)
    assert llr2.area[0].q_kpa == pytest.approx(1.5)


def test_landing_panels_carry_the_stair_load():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.slabs.append(_slab(0, 0, 0, 0, 2, 1.2, kind=M.SlabKind.LANDING))
    ll, _ = L.build_live(m)
    assert ll.area[0].q_kpa == pytest.approx(3.0)


def test_unmapped_occupancy_falls_back_and_discloses():
    m = M.StructuralModel(id="t", storeys=_storeys(1))
    m.rooms.append(_room(0, "void", 0, 0, 4, 5, occupancy=M.Occupancy.VOID))
    m.slabs.append(_slab(0, 0, 0, 0, 4, 5))
    ll, _ = L.build_live(m)
    assert ll.area[0].q_kpa == pytest.approx(2.0)
    assert "W_LOAD_OCCUPANCY_FALLBACK" in _codes(m)


# ---------------------------------------------------------------------------
# combos
# ---------------------------------------------------------------------------


def test_gravity_only_roster_is_one_combo_per_kind():
    out = C.generate(["DL", "LL", "LLR"])
    assert [c.id for c in out] == ["UL01", "SL01", "WS01"]
    assert out[0].factor_map() == {"DL": 1.5, "LL": 1.5, "LLR": 1.5}
    assert out[1].factor_map() == {"DL": 1.0, "LL": 1.0, "LLR": 1.0}
    assert out[2].allowable_stress_factor == pytest.approx(1.0)


def test_seismic_roster_expands_the_exact_table_18_set():
    out = C.generate(["DL", "LL", "EQX+", "EQX-", "EQY+", "EQY-"])
    uls = [c for c in out if c.kind == "ULS"]
    assert [c.id for c in uls] == ["UL%02d" % i for i in range(1, 14)]
    # first lateral block: EQX+
    assert uls[1].factor_map() == {"DL": 1.2, "LL": 1.2, "EQX+": 1.2}
    assert uls[2].factor_map() == {"DL": 1.5, "EQX+": 1.5}
    assert uls[3].factor_map() == {"DL": 0.9, "EQX+": 1.5}
    # roster order is fixed: EQX+, EQX-, EQY+, EQY-
    assert uls[4].factor_map()["EQX-"] == pytest.approx(1.2)
    assert uls[10].factor_map()["EQY-"] == pytest.approx(1.2)
    sls = [c for c in out if c.kind == "SLS"]
    assert len(sls) == 1 + 2 * 4
    assert sls[2].factor_map() == {"DL": 1.0, "LL": 0.8, "EQX+": 0.8}
    ws = [c for c in out if c.kind == "WS"]
    assert len(ws) == 5
    assert all(c.allowable_stress_factor == pytest.approx(1.25) for c in ws[1:])


def test_wind_and_seismic_never_share_a_combination():
    out = C.generate(["DL", "LL", "EQX+", "EQX-", "WX+", "WX-"])
    laterals = set(["EQX+", "EQX-", "WX+", "WX-"])
    for combo in out:
        present = laterals & set(combo.factor_map())
        assert len(present) <= 1
    assert C.laterals_present(["WX+", "EQX+", "DL"]) == ["EQX+", "WX+"]


def test_unknown_case_names_are_ignored_and_only_present_cases_expand():
    out = C.generate(["DL"])
    assert [c.id for c in out] == ["UL01", "SL01", "WS01"]
    assert out[0].factor_map() == {"DL": 1.5}


# ---------------------------------------------------------------------------
# load model serialization
# ---------------------------------------------------------------------------


def _sample_loadmodel():
    dl = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    dl.area.append(AreaLoad(panel_id="S-1", q_kpa=4.625, kind=CaseKind.DEAD, source="test"))
    dl.line.append(LineLoad(element_id="B-1", w1_kn_m=1.5, w2_kn_m=2.5, a=0.25, b=0.75, kind=CaseKind.DEAD, source="test"))
    return LoadModel(cases={CASE_DL: dl}, combos=C.generate([CASE_DL]))


def test_loadmodel_roundtrips_byte_identical():
    lm = _sample_loadmodel()
    d1 = lm.to_dict()
    d2 = LoadModel.from_dict(d1).to_dict()
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)


def test_build_twice_is_deterministic_on_the_committed_plan_fixture():
    with open(os.path.join(FIXTURES, "plan_2bhk.json"), "r") as handle:
        payload = json.load(handle)
    from ..adapters import plan_json as A

    def build():
        m = A.from_plan(payload, storeys=2)
        for index, room in enumerate(sorted(m.rooms, key=lambda r: (r.storey, r.id))):
            kind = M.SlabKind.ROOF if room.storey == 1 else M.SlabKind.FLOOR
            m.slabs.append(_slab(room.storey, index, *M.polygon_rect(room.polygon), kind=kind))
        dl = D.build_dead(m)
        ll, llr = L.build_live(m)
        lm = LoadModel(cases={CASE_DL: dl, CASE_LL: ll, CASE_LLR: llr}, combos=C.generate([CASE_DL, CASE_LL, CASE_LLR]))
        return json.dumps(lm.to_dict(), sort_keys=True)

    assert build() == build()
