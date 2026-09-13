"""Wave 6, task F2: four defects fixed at the source, one battery.

1. `model.DisclosureLog.append` deduped on the CODE alone, so two genuinely
   different conditions sharing a registry code collapsed and the later message
   was lost. The key is now (code, message): identical conditions still merge
   their element ids, distinct ones survive in producer order.
2. `loads.storey_weight_rows` tallies the seismic storey weights straight off
   the model and the gravity cases, so weighing a building no longer requires a
   whole gravity takedown pass. Cross-checked here against the takedown ledger
   on the committed plan fixture, and hand-checked on a model whose every
   contribution is one line of arithmetic.
3. `loads.live.build_live` takes an imposed-load override, honours it, traces it
   against the code value it replaced and discloses it. Absent, the case is byte
   for byte the one the code alone produces.
4. `setup.py` declares package_data, so `data/*.yaml` and `schema/*.json` reach
   a built wheel. The deploy installs with `pip install -e`, which runs from the
   checkout, so this was latent rather than live.
"""

from __future__ import annotations

import ast
import glob
import json
import os

import pytest

from .. import model as M
from .. import report as R
from ..adapters import plan_json as A
from ..analysis import takedown as T
from ..codes import is875
from ..codes.trace import trace_into
from ..loads import (
    CASE_DL,
    CASE_LL,
    CASE_LLR,
    AreaLoad,
    CaseKind,
    LineLoad,
    LoadCase,
    LoadModel,
    storey_weight_rows,
)
from ..loads import combos as C
from ..loads import dead as D
from ..loads import live as L
from ..loads.seismic import SeismicContext, build_seismic

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SETUP_PY = os.path.join(REPO_ROOT, "setup.py")

RCC = 25.0  # kN/m3, IS 875-1 Table 1


# ---------------------------------------------------------------------------
# model helpers (placement is a parallel stream; frames here are hand placed)
# ---------------------------------------------------------------------------


def _rect_poly(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _storeys(n, h=3.0):
    return [M.Storey(index=i, name="S%d" % i, bottom_z_m=i * h, height_m=h) for i in range(n)]


def _room(storey, name, x, y, w, h, occupancy=M.Occupancy.HABITABLE):
    return M.RoomPoly(
        id=M.room_id(storey, name),
        storey=storey,
        name=name,
        occupancy=occupancy,
        polygon=_rect_poly(x, y, w, h),
        area_m2=w * h,
    )


def _slab(storey, index, x, y, w, h, kind=M.SlabKind.FLOOR):
    return M.SlabPanel(
        id=M.slab_id(storey, index),
        storey=storey,
        polygon=_rect_poly(x, y, w, h),
        thickness_m=0.125,
        lx_m=min(w, h),
        ly_m=max(w, h),
        kind=kind,
    )


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


def hand_place(model, beam_depth=0.45, beam_width=0.23):
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
                M.Beam(
                    id="B-s%d-%s" % (storey, wall.id),
                    storey=storey,
                    a=wall.a,
                    b=wall.b,
                    width_m=beam_width,
                    depth_m=beam_depth,
                )
            )
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


@pytest.fixture(scope="module")
def plan_model():
    with open(os.path.join(FIXTURES, "plan_2bhk.json"), "r") as handle:
        payload = json.load(handle)
    return hand_place(A.from_plan(payload, storeys=2))


@pytest.fixture(scope="module")
def plan_loads(plan_model):
    live, roof_live = L.build_live(plan_model)
    return LoadModel(
        cases={CASE_DL: D.build_dead(plan_model), CASE_LL: live, CASE_LLR: roof_live},
        combos=C.generate([CASE_DL, CASE_LL, CASE_LLR]),
    )


@pytest.fixture(scope="module")
def plan_takedown(plan_model, plan_loads):
    return T.run(plan_model, plan_loads)


def occupancy_model():
    """One storey of four occupancies plus a landing, and a roof above."""
    model = M.StructuralModel(storeys=_storeys(2))
    model.rooms = [
        _room(0, "Bedroom", 0.0, 0.0, 4.0, 3.0),
        _room(0, "Bath", 4.0, 0.0, 2.0, 3.0, occupancy=M.Occupancy.BATH),
        _room(0, "Balcony", 6.0, 0.0, 2.0, 3.0, occupancy=M.Occupancy.BALCONY),
        _room(0, "Store", 8.0, 0.0, 2.0, 3.0, occupancy=M.Occupancy.STORAGE),
    ]
    model.slabs = [
        _slab(0, 0, 0.0, 0.0, 4.0, 3.0),
        _slab(0, 1, 4.0, 0.0, 2.0, 3.0),
        _slab(0, 2, 6.0, 0.0, 2.0, 3.0),
        _slab(0, 3, 8.0, 0.0, 2.0, 3.0),
        _slab(0, 4, 10.0, 0.0, 1.5, 3.0, kind=M.SlabKind.LANDING),
        _slab(1, 0, 0.0, 0.0, 10.0, 3.0, kind=M.SlabKind.ROOF),
    ]
    return model


def _areas(case):
    return {load.panel_id: load for load in case.area}


# ---------------------------------------------------------------------------
# fix 1: the ladder keys on (code, message)
# ---------------------------------------------------------------------------


def test_two_conditions_under_one_code_both_survive():
    log = M.DisclosureLog()
    first = log.add("W_COARSE_ITER", "placement stopped at the coarse limit", ["col-1-A-s0"])
    second = log.add("W_COARSE_ITER", "referrals are still open after the re-place pass", [])
    assert first is not second
    assert [entry.message for entry in log.entries] == [
        "placement stopped at the coarse limit",
        "referrals are still open after the re-place pass",
    ]
    assert log.codes() == ["W_COARSE_ITER"]
    assert log.counts() == {"error": 0, "warning": 2, "note": 0}


def test_the_identical_condition_still_merges_element_ids():
    log = M.DisclosureLog()
    first = log.add("W_ASSUMED_SBC", "default sbc assumed", ["ftg-b"])
    again = log.add("W_ASSUMED_SBC", "default sbc assumed", ["ftg-a", "ftg-b"], clause="IS 6403")
    assert again is first
    assert len(log.entries) == 1
    assert first.element_ids == ["ftg-a", "ftg-b"]
    assert first.clause == "IS 6403"  # backfilled onto the surviving entry


def test_distinct_messages_keep_their_own_element_ids():
    log = M.DisclosureLog()
    log.add("W_SHORT_SPAN", "axes gx-1 and gx-2 are 2000 mm apart", ["gx-1", "gx-2"])
    log.add("W_SHORT_SPAN", "axes gy-A and gy-B are 2000 mm apart", ["gy-A", "gy-B"])
    assert [entry.element_ids for entry in log.entries] == [
        ["gx-1", "gx-2"],
        ["gy-A", "gy-B"],
    ]
    for entry in log.entries:
        for element_id in entry.element_ids:
            assert element_id in entry.message


def test_the_severity_ladder_and_the_wire_shape_survive_the_split():
    log = M.DisclosureLog()
    log.add("W_TALL", "seven storeys", [])
    log.add("N_WASTAGE_3PCT", "3 percent", [])
    log.add("W_TALL", "thumb rules end at six", [])
    log.add("E_GRID_COARSE", "no admissible grid", ["gx-1"])
    assert [entry.code for entry in log.sorted_entries()] == [
        "E_GRID_COARSE",
        "W_TALL",
        "W_TALL",
        "N_WASTAGE_3PCT",
    ]
    wire = log.to_dict()
    assert [row["message"] for row in wire["disclosures"]][1:3] == [
        "seven storeys",
        "thumb rules end at six",
    ]
    assert wire["counts"] == {"error": 1, "warning": 2, "note": 1}


def test_the_model_ladder_and_its_log_view_keep_both_messages():
    model = M.StructuralModel(storeys=_storeys(1))
    model.add_warning("W_RELEASED_CAP", "a placement cap was relaxed", ["col-1-A-s0"])
    model.add_warning("W_RELEASED_CAP", "the imposed load came from the request", [])
    view = model.disclosure_log()
    assert len(view.entries) == 2
    assert [entry.message for entry in view.entries] == [
        "a placement cap was relaxed",
        "the imposed load came from the request",
    ]


def test_the_report_merge_point_keeps_both_messages():
    first = M.DisclosureLog()
    first.add("W_ASSUMED_SBC", "default sbc assumed", ["ftg-a"])
    second = M.DisclosureLog()
    second.add("W_ASSUMED_SBC", "the borelog sbc was unreadable", ["ftg-b"])
    merged = R.collect_disclosures(first, second)
    assert [entry.message for entry in merged.entries] == [
        "default sbc assumed",
        "the borelog sbc was unreadable",
    ]
    assert [entry.element_ids for entry in merged.entries] == [["ftg-a"], ["ftg-b"]]
    # the stage logs are still untouched
    assert len(first.entries) == 1 and len(second.entries) == 1


def test_appending_the_same_pair_twice_is_deterministic():
    def build():
        log = M.DisclosureLog()
        for message in ("second condition", "first condition", "second condition"):
            log.add("W_TORSION", message, ["core-1"])
        return [(entry.code, entry.message, tuple(entry.element_ids)) for entry in log.entries]

    assert build() == build()
    assert len(build()) == 2


# ---------------------------------------------------------------------------
# fix 2: storey weights without a takedown pass
# ---------------------------------------------------------------------------


def test_storey_weight_rows_agree_with_the_takedown_ledger(plan_model, plan_loads, plan_takedown):
    rows = storey_weight_rows(plan_model, plan_loads)
    ledger = plan_takedown.storey_ledger
    assert [row["storey"] for row in rows] == sorted(ledger)
    for row in rows:
        booked = ledger[row["storey"]]
        for key, ledger_key in (("w_dl_kn", "w_dl_kn"), ("w_ll_kn", "w_ll_kn")):
            expected = booked[ledger_key]
            if abs(expected) < 1e-9:
                assert abs(row[key]) < 1e-9, key
                continue
            assert abs(row[key] - expected) / abs(expected) <= 0.02, (row["storey"], key)
        assert row["z_top_m"] == pytest.approx(booked["z_m"], abs=1e-6)
        basis = booked["ll_fraction_basis_kpa"]
        assert row["ll_basis_kpa"] == (None if not basis else pytest.approx(basis))


def test_the_rows_carry_the_shape_build_seismic_documents(plan_model, plan_loads):
    rows = storey_weight_rows(plan_model, plan_loads)
    assert rows, "the plan fixture has storeys to weigh"
    for row in rows:
        assert set(row) == {"storey", "w_dl_kn", "w_ll_kn", "ll_basis_kpa", "z_top_m", "roof"}
        assert isinstance(row["storey"], int)
        assert row["w_dl_kn"] > 0.0
        assert row["z_top_m"] > 0.0
    assert [row["roof"] for row in rows] == [False] * (len(rows) - 1) + [True]
    assert [row["storey"] for row in rows] == sorted(row["storey"] for row in rows)


def test_the_rows_drive_build_seismic_to_the_takedown_answer(plan_model, plan_loads, plan_takedown):
    """Feeding the helper and feeding the takedown ledger give one base shear."""
    from_ledger = []
    top = max(plan_takedown.storey_ledger)
    for level in sorted(plan_takedown.storey_ledger):
        booked = plan_takedown.storey_ledger[level]
        basis = booked["ll_fraction_basis_kpa"]
        from_ledger.append(
            {
                "storey": int(level),
                "z_top_m": booked["z_m"],
                "w_dl_kn": booked["w_dl_kn"],
                "w_ll_kn": booked["w_ll_kn"],
                "ll_basis_kpa": None if not basis else float(basis),
                "roof": int(level) == int(top),
            }
        )
    plan_dims = {"x_m": 10.0, "y_m": 8.0}
    ctx = SeismicContext(zone="III", soil="II", importance=1.0, system="omrf")
    _, direct = build_seismic(storey_weight_rows(plan_model, plan_loads), plan_dims, ctx)
    _, booked = build_seismic(from_ledger, plan_dims, ctx)
    assert direct["seismic_weight_kn"] == pytest.approx(booked["seismic_weight_kn"], rel=0.02)
    assert direct["directions"]["x"]["base_shear_kn"] == pytest.approx(
        booked["directions"]["x"]["base_shear_kn"], rel=0.02
    )


def test_every_contribution_lands_where_the_convention_says():
    """One hand-computed model: slab, beam, wall halves, column self weight."""
    model = M.StructuralModel(storeys=_storeys(2))
    model.slabs = [_slab(0, 0, 0.0, 0.0, 4.0, 5.0), _slab(1, 0, 0.0, 0.0, 4.0, 5.0)]
    model.walls = [
        M.WallLine(
            id="wall-s1",
            storey=1,
            a=(0.0, 0.0),
            b=(4.0, 0.0),
            thickness_m=0.23,
        )
    ]
    model.columns = [_column(0, 0.0, 0.0), _column(1, 0.0, 0.0)]
    dead = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    dead.area = [
        AreaLoad(panel_id=model.slabs[0].id, q_kpa=5.0, kind=CaseKind.DEAD, source="hand"),
        AreaLoad(panel_id=model.slabs[1].id, q_kpa=5.0, kind=CaseKind.DEAD, source="hand"),
    ]
    dead.line = [
        LineLoad(
            element_id="wall-s1",
            w1_kn_m=10.0,
            w2_kn_m=10.0,
            a=0.0,
            b=1.0,
            kind=CaseKind.DEAD,
            source="hand",
        )
    ]
    live = LoadCase(name=CASE_LL, kind=CaseKind.LIVE)
    live.area = [
        AreaLoad(panel_id=model.slabs[0].id, q_kpa=2.0, kind=CaseKind.LIVE, source="hand"),
        AreaLoad(panel_id=model.slabs[1].id, q_kpa=3.0, kind=CaseKind.LIVE, source="hand"),
    ]
    rows = storey_weight_rows(model, LoadModel(cases={CASE_DL: dead, CASE_LL: live}))

    column_kn = RCC * 0.3 * 0.3 * 3.0  # 6.75 kN per storey height
    slab_kn = 5.0 * 4.0 * 5.0  # 100 kN
    wall_kn = 10.0 * 4.0  # 40 kN on the storey 1 wall
    assert [row["storey"] for row in rows] == [0, 1]
    # level 0: its slab, half the wall above, half of each column meeting there
    assert rows[0]["w_dl_kn"] == pytest.approx(slab_kn + 0.5 * wall_kn + column_kn)
    # level 1: its slab, the other wall half, the top half of the storey 1 column
    assert rows[1]["w_dl_kn"] == pytest.approx(slab_kn + 0.5 * wall_kn + 0.5 * column_kn)
    # the ground half of the storey 0 column goes to the foundation, not to a level
    assert rows[0]["w_ll_kn"] == pytest.approx(2.0 * 20.0)
    assert rows[1]["w_ll_kn"] == pytest.approx(3.0 * 20.0)
    assert [row["ll_basis_kpa"] for row in rows] == [2.0, 3.0]
    assert [row["z_top_m"] for row in rows] == [3.0, 6.0]
    assert [row["roof"] for row in rows] == [False, True]


def test_the_roof_imposed_load_is_kept_out_of_the_weight():
    """IS 1893 Cl 7.3.2: LLR never enters w_ll_kn."""
    model = M.StructuralModel(storeys=_storeys(1))
    model.slabs = [_slab(0, 0, 0.0, 0.0, 4.0, 5.0, kind=M.SlabKind.ROOF)]
    roof_live = LoadCase(name=CASE_LLR, kind=CaseKind.ROOF_LIVE)
    roof_live.area = [
        AreaLoad(panel_id=model.slabs[0].id, q_kpa=1.5, kind=CaseKind.ROOF_LIVE, source="hand")
    ]
    rows = storey_weight_rows(model, LoadModel(cases={CASE_LLR: roof_live}))
    assert [(row["w_dl_kn"], row["w_ll_kn"], row["ll_basis_kpa"]) for row in rows] == [
        (0.0, 0.0, None)
    ]


def test_a_load_naming_an_element_the_model_lacks_is_refused():
    model = M.StructuralModel(storeys=_storeys(1))
    model.slabs = [_slab(0, 0, 0.0, 0.0, 4.0, 5.0)]
    stray = LoadCase(name=CASE_DL, kind=CaseKind.DEAD)
    stray.area = [AreaLoad(panel_id="slab-nope", q_kpa=5.0, kind=CaseKind.DEAD, source="hand")]
    with pytest.raises(ValueError) as excinfo:
        storey_weight_rows(model, LoadModel(cases={CASE_DL: stray}))
    assert "slab-nope" in str(excinfo.value)


def test_weighing_twice_is_byte_identical(plan_model, plan_loads):
    first = storey_weight_rows(plan_model, plan_loads)
    second = storey_weight_rows(plan_model, plan_loads)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# fix 3: the imposed-load override is applied, traced and disclosed
# ---------------------------------------------------------------------------


def test_no_override_is_byte_identical_to_the_code_only_path():
    plain_model = occupancy_model()
    override_model = occupancy_model()
    plain_entries = []
    none_entries = []
    with trace_into(plain_entries):
        plain_ll, plain_llr = L.build_live(plain_model)
    with trace_into(none_entries):
        none_ll, none_llr = L.build_live(override_model, None)
    assert plain_ll.to_dict() == none_ll.to_dict()
    assert plain_llr.to_dict() == none_llr.to_dict()
    assert [entry.to_dict() for entry in plain_entries] == [
        entry.to_dict() for entry in none_entries
    ]
    assert not any(entry.code == "request" for entry in none_entries)
    assert [w.code for w in plain_model.warnings] == [w.code for w in override_model.warnings]
    assert "W_LIVE_LOAD_OVERRIDDEN" not in [w.code for w in override_model.warnings]


def test_a_scalar_override_moves_the_habitable_panels_only():
    model = occupancy_model()
    ll, llr = L.build_live(model, 3.5)
    plain_ll, plain_llr = L.build_live(occupancy_model())
    loads = _areas(ll)
    plain = _areas(plain_ll)
    bedroom = M.slab_id(0, 0)
    assert plain[bedroom].q_kpa == pytest.approx(is875.part2_imposed("residential_room"))
    assert loads[bedroom].q_kpa == pytest.approx(3.5)
    assert "request override" in loads[bedroom].source
    assert "residential_room" in loads[bedroom].source
    for panel in (M.slab_id(0, 1), M.slab_id(0, 2), M.slab_id(0, 3), M.slab_id(0, 4)):
        assert loads[panel].q_kpa == pytest.approx(plain[panel].q_kpa), panel
        assert loads[panel].source == plain[panel].source, panel
    # the roof imposed load is Table 2 and is never overridden
    assert llr.to_dict() == plain_llr.to_dict()


def test_the_override_is_disclosed_naming_what_it_replaced():
    model = occupancy_model()
    L.build_live(model, 3.5)
    entries = [w for w in model.warnings if w.code == "W_LIVE_LOAD_OVERRIDDEN"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.severity == M.Severity.WARNING
    assert entry.clause == "IS 875-2:1987 Table 1"
    assert entry.stage == "loads.live"
    assert "residential_room 2.00 -> 3.50 kPa" in entry.message
    assert entry.element_ids == [M.slab_id(0, 0)]


def test_the_override_is_traced_against_the_code_value():
    model = occupancy_model()
    entries = []
    with trace_into(entries):
        L.build_live(model, 3.5)
    records = [entry for entry in entries if entry.code == "request"]
    assert len(records) == 1
    record = records[0]
    assert record.ref == "live_load_kpa"
    assert record.units == "kPa"
    assert record.output == pytest.approx(3.5)
    assert record.inputs["occupancy_key"] == "residential_room"
    assert record.inputs["code_q_kpa"] == pytest.approx(2.0)
    assert record.inputs["replaced"] == "IS 875-2:1987 Table 1"
    # the Table 1 record it replaced is still on the sheet, before it
    table1 = [entry for entry in entries if entry.ref == "Table 1"]
    assert table1 and entries.index(table1[0]) < entries.index(record)


def test_a_mapping_override_reaches_each_occupancy():
    model = occupancy_model()
    ll, _ = L.build_live(model, {"toilet_bath": 4.0, "balcony": 5.0, "corridor_stair": 6.0})
    loads = _areas(ll)
    assert loads[M.slab_id(0, 1)].q_kpa == pytest.approx(4.0)  # bath
    assert loads[M.slab_id(0, 2)].q_kpa == pytest.approx(5.0)  # balcony
    assert loads[M.slab_id(0, 4)].q_kpa == pytest.approx(6.0)  # landing
    assert loads[M.slab_id(0, 4)].note == "stair landing"
    assert loads[M.slab_id(0, 0)].q_kpa == pytest.approx(2.0)  # habitable untouched
    entry = [w for w in model.warnings if w.code == "W_LIVE_LOAD_OVERRIDDEN"][0]
    assert "balcony 3.00 -> 5.00 kPa" in entry.message
    assert "corridor_stair 3.00 -> 6.00 kPa" in entry.message
    assert "toilet_bath 2.00 -> 4.00 kPa" in entry.message


def test_a_mapping_may_be_keyed_by_model_occupancy():
    by_occupancy = occupancy_model()
    by_key = occupancy_model()
    ll_a, _ = L.build_live(by_occupancy, {M.Occupancy.BATH: 4.0, "kitchen": 3.25})
    ll_b, _ = L.build_live(by_key, {"toilet_bath": 4.0, "residential_room": 3.25})
    assert ll_a.to_dict() == ll_b.to_dict()
    assert L.resolve_live_override({M.Occupancy.BATH: 4.0}) == {"toilet_bath": 4.0}
    assert L.resolve_live_override(2.5) == {"residential_room": 2.5}


def test_an_override_that_matches_no_panel_says_so_beside_the_one_that_did():
    """Two conditions, one code: fix 1 is what lets the second one be read."""
    model = occupancy_model()
    L.build_live(model, {"residential_room": 3.5, "garage_light": 7.5})
    entries = [w for w in model.warnings if w.code == "W_LIVE_LOAD_OVERRIDDEN"]
    assert len(entries) == 2
    assert "residential_room 2.00 -> 3.50 kPa" in entries[0].message
    assert "garage_light 7.50 kPa" in entries[1].message
    assert "nothing was replaced there" in entries[1].message


def test_an_override_the_engine_cannot_honour_is_refused_not_dropped():
    model = occupancy_model()
    for bad in ({"nope": 2.0}, {"balcony": 0.0}, {"balcony": "heavy"}, -1.0, True):
        with pytest.raises(ValueError):
            L.build_live(occupancy_model(), bad)
    with pytest.raises(ValueError) as excinfo:
        L.build_live(model, {"bath": 2.0, "wc": 4.0})
    assert "toilet_bath" in str(excinfo.value)
    # roof keys are Table 2 and are not in the overridable vocabulary
    with pytest.raises(ValueError):
        L.build_live(occupancy_model(), {"roof_accessible": 2.0})
    assert "roof_accessible" not in L.OVERRIDABLE_KEYS


def test_the_override_carries_through_to_the_storey_weights():
    plain = occupancy_model()
    heavy = occupancy_model()
    plain_rows = storey_weight_rows(plain, LoadModel(cases={CASE_LL: L.build_live(plain)[0]}))
    heavy_rows = storey_weight_rows(heavy, LoadModel(cases={CASE_LL: L.build_live(heavy, 3.5)[0]}))
    # the 4 x 3 bedroom panel alone moves, by (3.5 - 2.0) x 12 m2
    assert heavy_rows[0]["w_ll_kn"] - plain_rows[0]["w_ll_kn"] == pytest.approx(18.0)
    # the Table 10 selector still reads the heaviest panel at the level, the
    # 5.0 kPa store, which the override did not touch
    assert heavy_rows[0]["ll_basis_kpa"] == pytest.approx(5.0)
    assert plain_rows[0]["ll_basis_kpa"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# fix 4: the data and schema files reach a built wheel
# ---------------------------------------------------------------------------


def _setup_tree():
    with open(SETUP_PY, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=SETUP_PY)


def _module_literal(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError("setup.py has no module-level " + name)


def _setup_kwargs(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            return {kw.arg: kw.value for kw in node.keywords}
    raise AssertionError("setup.py calls no setup()")


def test_setup_py_passes_package_data_and_include_flag_to_setup():
    kwargs = _setup_kwargs(_setup_tree())
    assert "package_data" in kwargs, "a wheel without package_data ships no tables"
    assert "include_package_data" in kwargs
    flag = kwargs["include_package_data"]
    assert isinstance(flag, ast.Constant) and flag.value is False


def test_the_package_data_globs_resolve_to_files_on_disk():
    declared = _module_literal(_setup_tree(), "package_data")
    assert set(declared) == {"GPLAN.structural", "GPLAN.structural.data"}
    resolved = {}
    for package, patterns in sorted(declared.items()):
        package_dir = os.path.join(REPO_ROOT, *package.split("."))
        assert os.path.isdir(package_dir), package_dir
        assert os.path.isfile(os.path.join(package_dir, "__init__.py")), package
        for pattern in patterns:
            hits = glob.glob(os.path.join(package_dir, pattern.replace("/", os.sep)))
            assert hits, package + " -> " + pattern + " matches nothing on disk"
            for hit in hits:
                resolved[os.path.abspath(hit)] = True
    structural = os.path.join(REPO_ROOT, "GPLAN", "structural")
    shipped = glob.glob(os.path.join(structural, "data", "*.yaml"))
    shipped += glob.glob(os.path.join(structural, "schema", "*.json"))
    assert shipped, "the package carries data and schema files to cover"
    for path in shipped:
        assert os.path.abspath(path) in resolved, path + " would be missing from a wheel"


def test_the_dependency_list_is_untouched():
    declared = _module_literal(_setup_tree(), "packages")
    assert "PyYAML==6.0.1" in declared
    assert not [name for name in declared if name.lower().startswith("structuralcodes")]
