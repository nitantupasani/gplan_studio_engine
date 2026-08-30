"""Pins for placement/cores.py: shaft vs columns mode, trimmers, flights.

The building fixture carries a stairs core (12 x 10 ft) and a lift core
(8 x 8 ft) on all three storeys, so it drives the columns mode end to end; a
synthetic 5-storey tower drives shaft mode. Every asserted number is hand
derivable: the stair run is the core long side minus the landing strips, the
rise is half the storey height, and the trimmer count is edges x levels.
"""

from __future__ import annotations

import json
import os

import pytest

from .. import model as M
from ..grid import FrameParams, extract_axes
from ..adapters.building import from_building
from ..placement.cores import (
    LANDING_DEPTH_MM,
    SHAFT_WALL_T_LOW_MM,
    SHAFT_WALL_T_MM,
    CorePlan,
    frame_core_openings,
    plan_cores,
)
from ..placement.frame import run_frame_placement

FT = M.FT
EXT = 0.75 * FT

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def building_model():
    with open(os.path.join(_FIXTURES, "building_3storey.json"), "r") as handle:
        return from_building(json.load(handle))


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _room(storey, name, x0, y0, x1, y1):
    return M.RoomPoly(
        id=M.room_id(storey, name),
        storey=storey,
        name=name,
        occupancy=M.Occupancy.HABITABLE,
        polygon=_rect(x0, y0, x1, y1),
        area_m2=(x1 - x0) * (y1 - y0),
    )


def _wall(storey, tag, a, b):
    return M.WallLine(
        id="w-s%d-%s" % (storey, tag),
        storey=storey,
        a=a,
        b=b,
        thickness_m=EXT,
        role=M.WallRole.EXTERIOR,
    )


def _box_walls(storey, x0, y0, x1, y1):
    return [
        _wall(storey, "n", (x0, y0), (x1, y0)),
        _wall(storey, "s", (x0, y1), (x1, y1)),
        _wall(storey, "w", (x0, y0), (x0, y1)),
        _wall(storey, "e", (x1, y0), (x1, y1)),
    ]


def core_tower(storey_count, stair_hint=None, lift=True):
    """16 x 10 m tower: a 3 x 4 stairs core and a 2.4 x 2.4 lift core."""
    storeys = [
        M.Storey(index=i, name="S%d" % i, bottom_z_m=3.0 * i, height_m=3.0)
        for i in range(storey_count)
    ]
    rooms = []
    walls = []
    for i in range(storey_count):
        rooms.append(_room(i, "floor", 0, 0, 16, 10))
        walls.extend(_box_walls(i, 0, 0, 16, 10))
    cores = [
        M.Core(
            id=M.core_id("st"),
            kind=M.CoreKind.STAIRS,
            x_m=6.0,
            y_m=3.0,
            w_m=3.0,
            h_m=4.0,
            storeys=list(range(storey_count)),
            stair_landing_hint=stair_hint,
        )
    ]
    if lift:
        cores.append(
            M.Core(
                id=M.core_id("lf"),
                kind=M.CoreKind.LIFT,
                x_m=10.5,
                y_m=3.0,
                w_m=2.4,
                h_m=2.4,
                storeys=list(range(storey_count)),
            )
        )
    return M.StructuralModel(
        id="tower%d" % storey_count, storeys=storeys, rooms=rooms, walls=walls, cores=cores
    )


def _edge_cover(beams, rect, tag):
    """Length of trimmer/header/landing beams lying on one core edge."""
    x0, y0, x1, y1 = rect
    if tag in ("n", "s"):
        orient, pos, lo, hi = "h", (y0 if tag == "n" else y1), x0, x1
    else:
        orient, pos, lo, hi = "v", (x0 if tag == "w" else x1), y0, y1
    total = 0
    for beam in beams:
        if beam.orient == orient and abs(beam.pos_mm - pos) <= 10:
            total += max(0, min(hi, beam.hi_mm) - max(lo, beam.lo_mm))
    return total, hi - lo


# ---------------------------------------------------------------------------
# plan_cores: mode decision, anchors, door edges
# ---------------------------------------------------------------------------


def test_three_storeys_run_in_columns_mode_with_corner_anchors():
    model = building_model()
    grid = extract_axes(model)
    plan = plan_cores(model, grid)
    assert isinstance(plan, CorePlan)
    assert plan.mode == "columns"
    assert len(plan.anchors_mm) == 8  # two cores, four corners each
    assert plan.shaft_walls == []
    assert set(plan.core_rects_mm) == {"core-fe-lift", "core-fe-stair"}
    # the door edge probe is deterministic: both cores open toward the units
    assert plan.door_edges == {"core-fe-lift": "s", "core-fe-stair": "w"}
    assert plan.shaft_rects_mm() == []


def test_five_storeys_run_in_shaft_mode_with_panels_minus_the_door_edge():
    model = core_tower(5)
    grid = extract_axes(model)
    params = FrameParams()
    plan = plan_cores(model, grid, params)
    assert plan.mode == "shaft"
    assert len(plan.shaft_walls) == 6  # 4 edges minus the door edge, per core
    for wall in plan.shaft_walls:
        assert wall.t_mm == SHAFT_WALL_T_MM
        assert wall.base_storey == 0 and wall.top_storey == 4
        assert wall.edge != plan.door_edges[wall.core_id]
    assert "N_SHAFT_WALL_UNDESIGNED" in plan.log.codes()
    assert sorted(plan.shaft_rects_mm()) == sorted(plan.core_rects_mm.values())


def test_shaft_threshold_follows_the_parameter_and_low_rise_thickness():
    model = core_tower(2)
    grid = extract_axes(model)
    plan = plan_cores(model, grid, FrameParams(shaft_min_storeys=1))
    assert plan.mode == "shaft"
    assert plan.shaft_walls and all(w.t_mm == SHAFT_WALL_T_LOW_MM for w in plan.shaft_walls)
    assert plan_cores(model, grid, FrameParams()).mode == "columns"


# ---------------------------------------------------------------------------
# frame_core_openings: trimmers, headers, landings, flights, notes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def building_openings():
    model = building_model()
    grid = extract_axes(model)
    plan = plan_cores(model, grid)
    return model, plan, frame_core_openings(model, grid, plan)


def test_trimmers_frame_every_core_edge_on_every_level(building_openings):
    model, plan, (beams, slabs, notes) = building_openings
    trimmers = [b for b in beams if b.kind == M.BeamKind.TRIMMER]
    assert len(trimmers) == 2 * 3 * 4  # two cores, three levels, four edges
    for cid, rect in sorted(plan.core_rects_mm.items()):
        for storey in (0, 1, 2):
            level = [b for b in trimmers if b.core_id == cid and b.level == storey]
            for tag in ("n", "e", "s", "w"):
                covered, length = _edge_cover(level, rect, tag)
                assert covered >= length, (cid, storey, tag)


def test_stair_landing_beams_default_to_both_ends(building_openings):
    model, plan, (beams, slabs, notes) = building_openings
    landings = [b for b in beams if b.kind == M.BeamKind.LANDING]
    assert len(landings) == 2 * 3  # both short ends, three levels, stairs only
    rect = plan.core_rects_mm["core-fe-stair"]
    stations = sorted({b.pos_mm for b in landings})
    assert stations == [rect[0] + LANDING_DEPTH_MM, rect[2] - LANDING_DEPTH_MM]
    for beam in landings:
        assert beam.core_id == "core-fe-stair"
        assert (beam.lo_mm, beam.hi_mm) == (rect[1], rect[3])


def test_stair_slab_records_carry_the_flight_geometry(building_openings):
    model, plan, (beams, slabs, notes) = building_openings
    assert len(slabs) == 6  # two flights per storey, three storeys
    rect = plan.core_rects_mm["core-fe-stair"]
    run_mm = (rect[2] - rect[0]) - 2 * LANDING_DEPTH_MM
    for slab in slabs:
        assert slab.core_id == "core-fe-stair"
        assert slab.flight in (1, 2)
        assert round(slab.span_m * 1000) == run_mm
        assert slab.width_m == pytest.approx((rect[3] - rect[1]) / 2000.0)
        assert slab.rise_m == pytest.approx(3.048 / 2.0)
        assert 0.0 < slab.incline_deg < 90.0
        wire = slab.to_dict()
        assert set(wire) == {
            "id", "core_id", "storey", "flight", "span_m", "width_m", "rise_m", "incline_deg",
        }
    ids = [s.id for s in slabs]
    assert ids == sorted(ids) and len(set(ids)) == 6


def test_lift_notes_mark_the_pit_and_the_machine_room(building_openings):
    model, plan, (beams, slabs, notes) = building_openings
    lift = [n for n in notes if n["core_id"] == "core-fe-lift"]
    assert {"core_id": "core-fe-lift", "storey": 0, "note": "lift_pit"} in lift
    assert {"core_id": "core-fe-lift", "storey": 2, "note": "machine_room_load"} in lift
    assert all(str(n["note"]).startswith("door_edge_assumed") or n["note"] in ("lift_pit", "machine_room_load") for n in notes)


def test_far_landing_hint_places_one_line_opposite_the_entry():
    model = core_tower(3, stair_hint="far")
    grid = extract_axes(model)
    plan = plan_cores(model, grid)
    beams, slabs, notes = frame_core_openings(model, grid, plan)
    landings = [b for b in beams if b.kind == M.BeamKind.LANDING]
    assert len(landings) == 1 * 3  # one line per level
    both = core_tower(3, stair_hint=None)
    grid_b = extract_axes(both)
    plan_b = plan_cores(both, grid_b)
    beams_b, _slabs, _notes = frame_core_openings(both, grid_b, plan_b)
    assert len([b for b in beams_b if b.kind == M.BeamKind.LANDING]) == 2 * 3


def test_frame_core_openings_is_deterministic(building_openings):
    model, plan, (beams, slabs, notes) = building_openings
    grid = extract_axes(model)
    beams2, slabs2, notes2 = frame_core_openings(model, grid, plan)
    key = lambda b: (b.level, b.orient, b.pos_mm, b.lo_mm, b.hi_mm, b.core_id, b.kind.value)
    assert [key(b) for b in beams] == [key(b) for b in beams2]
    assert [s.to_dict() for s in slabs] == [s.to_dict() for s in slabs2]
    assert notes == notes2


# ---------------------------------------------------------------------------
# integration through run_frame_placement
# ---------------------------------------------------------------------------


def test_columns_mode_puts_a_column_on_every_core_corner():
    r = run_frame_placement(core_tower(3))
    assert r.valid is True
    cols = {(c.x_mm, c.y_mm) for c in r.columns}
    for corner in (
        (6000, 3000), (9000, 3000), (6000, 7000), (9000, 7000),  # stairs
        (10500, 3000), (12900, 3000), (10500, 5400), (12900, 5400),  # lift
    ):
        assert corner in cols, corner
    assert r.shaft_walls == []


def test_shaft_mode_omits_core_columns_and_ships_shaft_walls():
    r = run_frame_placement(core_tower(5))
    assert r.valid is True
    assert len(r.shaft_walls) == 6
    stair = (6000, 3000, 9000, 7000)
    lift = (10500, 3000, 12900, 5400)
    for rect in (stair, lift):
        for c in r.columns:
            inside = (
                rect[0] - 115 <= c.x_mm <= rect[2] + 115
                and rect[1] - 115 <= c.y_mm <= rect[3] + 115
            )
            assert not inside, (c.x_mm, c.y_mm)
    codes = {e.code for e in r.log.entries}
    assert "N_SHAFT_WALL_UNDESIGNED" in codes
    wire = r.to_dict()
    assert len(wire["shaft_walls"]) == 6
    assert all(w["t_mm"] == SHAFT_WALL_T_MM for w in wire["shaft_walls"])


def test_shaft_mode_header_beam_replaces_the_door_edge_trimmer():
    r = run_frame_placement(core_tower(5))
    headers = [b for b in r.beams if b.kind == M.BeamKind.LINTEL and b.note == "shaft_header"]
    assert len(headers) == 2 * 5  # one per core per level
    trimmers = [b for b in r.beams if b.kind == M.BeamKind.TRIMMER]
    assert len(trimmers) == 2 * 5 * 3  # the other three edges
    # all four stair edges are still framed (header counts as the fourth side)
    stair = (6000, 3000, 9000, 7000)
    for storey in range(5):
        level = [b for b in headers + trimmers if b.storey == storey and b.core_id == "core-st"]
        for tag in ("n", "e", "s", "w"):
            covered, length = _edge_cover(level, stair, tag)
            assert covered >= length, (storey, tag)


def test_stair_faces_become_stair_panels_and_flights_are_recorded():
    r = run_frame_placement(core_tower(5))
    stair_levels = sorted({p.level for p in r.panels if p.kind == "stair"})
    assert stair_levels == [0, 1, 2, 3, 4]
    opening_levels = sorted({p.level for p in r.panels if p.kind == "opening"})
    assert opening_levels == [0, 1, 2, 3, 4]
    assert len(r.stair_slabs) == 2 * 5
    # stair and opening panels never carry a slab thickness or reach the model
    for p in r.panels:
        if p.kind in ("stair", "opening"):
            assert p.t_mm is None
    model = core_tower(5)
    r.write_back(model)
    assert all(s.kind in (M.SlabKind.FLOOR, M.SlabKind.ROOF) for s in model.slabs)
    written_ids = {s.id for s in model.slabs}
    for p in r.panels:
        if p.kind in ("stair", "opening"):
            assert p.id not in written_ids


def test_area_conservation_holds_around_shaft_rings():
    """The ring of slab around a shaft traces with the shaft as a hole, so the
    panel areas still tile the storey exactly."""
    r = run_frame_placement(core_tower(5))
    for storey in range(5):
        footprint = sum(
            (x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in r.grid.footprints[storey].rects
        )
        panels = sum(p.area_mm2() for p in r.panels if p.level == storey)
        assert panels == footprint, storey


def test_offset_shaft_flags_torsion():
    """A single far-west shaft dominates the stiffness; the centroid offset
    exceeds 5 pct of the plan dimension and W_TORSION lands."""
    model = core_tower(5, lift=False)
    for core in model.cores:
        core.x_m, core.y_m = 0.5, 3.0
    r = run_frame_placement(model)
    assert "W_TORSION" in {e.code for e in r.log.entries}
    assert max(r.metrics["torsion_proxy_pct"]["x"], r.metrics["torsion_proxy_pct"]["y"]) > 5.0


def test_core_notes_ride_the_result_and_the_meta():
    r = run_frame_placement(core_tower(5))
    notes = {(n["core_id"], n["note"]) for n in r.core_notes}
    assert ("core-lf", "lift_pit") in notes
    assert ("core-lf", "machine_room_load") in notes
    assert any(note.startswith("door_edge_assumed") for _cid, note in notes)
    assert any(a.startswith("core core-lf: door_edge_assumed") for a in r.report["assumptions"])
    assert "cores modelled as RC shafts (prescription, not design)" in r.report["assumptions"]
