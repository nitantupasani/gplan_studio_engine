"""Pins for placement/frame.py: the full RC frame placement pipeline.

The two fixtures drive the REAL pipeline end to end (plan_json and building
adapters); the synthetic models are hand-sized so that every asserted number
(scores, stations, thicknesses, slide distances) is derivable from the spec by
hand. Internal mm values are asserted through the internal dataclasses, wire
values through to_dict(); both are covered.
"""

from __future__ import annotations

import json
import os
import time
from fractions import Fraction

import pytest

from .. import model as M
from ..grid import FrameParams, extract_axes
from ..adapters.building import from_building
from ..adapters.plan_json import from_plan
from ..placement.cores import plan_cores
from ..placement.frame import (
    SCORE_VERSION,
    FrameResult,
    _ColumnState,
    _Stack,
    _View,
    enforce_continuity,
    insert_secondary_beams,
    place_lintels_for_infill,
    run_frame_placement,
)

FT = M.FT
EXT = 0.75 * FT  # 0.2286 m exterior default
INT = 0.115

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _room(storey, name, occupancy, x0, y0, x1, y1):
    return M.RoomPoly(
        id=M.room_id(storey, name),
        storey=storey,
        name=name,
        occupancy=occupancy,
        polygon=_rect(x0, y0, x1, y1),
        area_m2=(x1 - x0) * (y1 - y0),
    )


def _wall(storey, tag, a, b, thickness_m=EXT, role=M.WallRole.EXTERIOR):
    return M.WallLine(
        id="w-s%d-%s" % (storey, tag),
        storey=storey,
        a=a,
        b=b,
        thickness_m=thickness_m,
        role=role,
    )


def _box_walls(storey, x0, y0, x1, y1):
    return [
        _wall(storey, "n", (x0, y0), (x1, y0)),
        _wall(storey, "s", (x0, y1), (x1, y1)),
        _wall(storey, "w", (x0, y0), (x0, y1)),
        _wall(storey, "e", (x1, y0), (x1, y1)),
    ]


def _storeys(n, h=3.0):
    return [M.Storey(index=i, name="S%d" % i, bottom_z_m=i * h, height_m=h) for i in range(n)]


def plan_model():
    with open(os.path.join(_FIXTURES, "plan_2bhk.json"), "r") as handle:
        return from_plan(json.load(handle), storeys=2)


def building_model():
    with open(os.path.join(_FIXTURES, "building_3storey.json"), "r") as handle:
        return from_building(json.load(handle))


def two_bay_model():
    """8 x 4 m, two 4 x 4 rooms and a mid partition: every metric hand-checkable."""
    return M.StructuralModel(
        id="two-bay",
        storeys=_storeys(1),
        rooms=[
            _room(0, "a", M.Occupancy.HABITABLE, 0, 0, 4, 4),
            _room(0, "b", M.Occupancy.HABITABLE, 4, 0, 8, 4),
        ],
        walls=_box_walls(0, 0, 0, 8, 4)
        + [_wall(0, "mid", (4.0, 0.0), (4.0, 4.0), INT, M.WallRole.INTERIOR)],
    )


def corridor_model():
    """12 x 12 m with a 1.8 m corridor across the middle."""
    return M.StructuralModel(
        id="corridor",
        storeys=_storeys(1),
        rooms=[
            _room(0, "n", M.Occupancy.HABITABLE, 0, 0, 12, 5),
            _room(0, "c", M.Occupancy.CORRIDOR, 0, 5, 12, 6.8),
            _room(0, "s", M.Occupancy.HABITABLE, 0, 6.8, 12, 12),
        ],
        walls=_box_walls(0, 0, 0, 12, 12)
        + [
            _wall(0, "ca", (0.0, 5.0), (12.0, 5.0), INT, M.WallRole.INTERIOR),
            _wall(0, "cb", (0.0, 6.8), (12.0, 6.8), INT, M.WallRole.INTERIOR),
        ],
    )


def dressed_door_model():
    """10 x 8 m, mid wall at x = 5 with a DRESSED 0.9 m door centred at 4.0 m."""
    mid = _wall(0, "mid", (5.0, 0.0), (5.0, 8.0), INT, M.WallRole.INTERIOR)
    mid.openings.append(
        M.Opening(
            id=M.opening_id(mid.id, 0),
            kind=M.OpeningKind.DOOR,
            offset_m=4.0,
            width_m=0.9,
            provenance=M.Provenance.DRESSED,
        )
    )
    return M.StructuralModel(
        id="door",
        storeys=_storeys(1),
        rooms=[
            _room(0, "a", M.Occupancy.HABITABLE, 0, 0, 5, 8),
            _room(0, "b", M.Occupancy.HABITABLE, 5, 0, 10, 8),
        ],
        walls=_box_walls(0, 0, 0, 10, 8) + [mid],
    )


def undodgeable_door_model():
    """A dressed door so wide every 50 mm slide station stays inside it."""
    v = _wall(0, "mid-v", (5.0, 0.0), (5.0, 3.0), INT, M.WallRole.INTERIOR)
    v.openings.append(
        M.Opening(
            id=M.opening_id(v.id, 0),
            kind=M.OpeningKind.DOOR,
            offset_m=1.5,
            width_m=2.4,
            provenance=M.Provenance.DRESSED,
        )
    )
    h = _wall(0, "mid-h", (0.0, 1.5), (10.0, 1.5), INT, M.WallRole.INTERIOR)
    return M.StructuralModel(
        id="door-drop",
        storeys=_storeys(1),
        rooms=[
            _room(0, "a", M.Occupancy.HABITABLE, 0, 0, 5, 1.5),
            _room(0, "b", M.Occupancy.HABITABLE, 5, 0, 10, 1.5),
            _room(0, "c", M.Occupancy.HABITABLE, 0, 1.5, 5, 3),
            _room(0, "d", M.Occupancy.HABITABLE, 5, 1.5, 10, 3),
            _room(0, "s", M.Occupancy.HABITABLE, 0, 3, 10, 6),
        ],
        walls=_box_walls(0, 0, 0, 10, 6)
        + [v, h, _wall(0, "mid-y3", (0.0, 3.0), (10.0, 3.0), INT, M.WallRole.INTERIOR)],
    )


def feedback_box_model():
    """6 x 8 m open box; with the span cap released to 7.5 m only y = 4 is
    gridded, so the first panel is the full 6 x 8 and the loop must resolve it."""
    return M.StructuralModel(
        id="feedback",
        storeys=_storeys(1),
        rooms=[_room(0, "hall", M.Occupancy.HABITABLE, 0, 0, 6, 8)],
        walls=_box_walls(0, 0, 0, 6, 8),
    )


def transfer_model():
    """Storey 1 shifted 3 m east of the ground: unrepairable floating columns."""
    return M.StructuralModel(
        id="transfer",
        storeys=_storeys(2),
        rooms=[
            _room(0, "g", M.Occupancy.HABITABLE, 0, 0, 10, 8),
            _room(1, "u", M.Occupancy.HABITABLE, 3, 0, 13, 8),
        ],
        walls=_box_walls(0, 0, 0, 10, 8) + _box_walls(1, 3, 0, 13, 8),
    )


def slide_model():
    """Storey 1 overhangs the ground by 0.8 m east: slide-repairable."""
    return M.StructuralModel(
        id="slide",
        storeys=_storeys(2),
        rooms=[
            _room(0, "g", M.Occupancy.HABITABLE, 0, 0, 10, 8),
            _room(1, "u", M.Occupancy.HABITABLE, 0, 0, 10.8, 8),
        ],
        walls=_box_walls(0, 0, 0, 10, 8) + _box_walls(1, 0, 0, 10.8, 8),
    )


def cantilever_model(overhang=2.3):
    """Storey 1 extends east beyond the ground by `overhang` metres."""
    return M.StructuralModel(
        id="cant",
        storeys=_storeys(2),
        rooms=[
            _room(0, "g", M.Occupancy.HABITABLE, 0, 0, 10, 8),
            _room(1, "u", M.Occupancy.HABITABLE, 0, 0, 10 + overhang, 8),
        ],
        walls=_box_walls(0, 0, 0, 10, 8) + _box_walls(1, 0, 0, 10 + overhang, 8),
    )


def tall_ground_model(height=4.2):
    return M.StructuralModel(
        id="tie",
        storeys=[M.Storey(index=0, name="G", bottom_z_m=0.0, height_m=height)],
        rooms=[_room(0, "hall", M.Occupancy.HABITABLE, 0, 0, 8, 6)],
        walls=_box_walls(0, 0, 0, 8, 6),
    )


def _canonical(result):
    return json.dumps(result.to_dict(), sort_keys=True)


def _footprint_area(result, storey):
    return sum(
        (x1 - x0) * (y1 - y0)
        for x0, y0, x1, y1 in result.grid.footprints[storey].rects
    )


def _covered(beams, orient, pos, lo, hi, lateral):
    pieces = []
    for beam in beams:
        if beam.orient != orient or abs(beam.pos_mm - pos) > lateral:
            continue
        piece = (max(lo, beam.lo_mm), min(hi, beam.hi_mm))
        if piece[1] > piece[0]:
            pieces.append(piece)
    pieces.sort()
    total = 0
    end = None
    for plo, phi in pieces:
        if end is None or plo > end:
            total += phi - plo
            end = phi
        elif phi > end:
            total += phi - end
            end = phi
    return total


# ---------------------------------------------------------------------------
# the plan fixture, end to end through the adapter
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def plan_result():
    return run_frame_placement(plan_model())


@pytest.fixture(scope="module")
def building_result():
    return run_frame_placement(building_model())


def test_plan_fixture_is_valid_and_scored(plan_result):
    r = plan_result
    assert isinstance(r, FrameResult)
    assert r.valid is True
    assert sum(r.metrics["hard_violations"].values()) == 0
    assert r.metrics["score_version"] == SCORE_VERSION
    assert 0 <= r.metrics["score"] <= 100
    assert r.columns and r.beams and r.panels


def test_plan_fixture_footprint_corners_have_columns(plan_result):
    cols = {(c.x_mm, c.y_mm) for c in plan_result.columns}
    # the 30 x 40 ft plot: bbox corners must carry a column exactly
    for corner in ((0, 0), (9144, 0), (0, 12192), (9144, 12192)):
        assert corner in cols, corner
    # every footprint corner has a column within the merge window
    for storey in (0, 1):
        for pos, lo, hi in plan_result.grid.footprints[storey].boundary_lines("v"):
            for corner in ((pos, lo), (pos, hi)):
                near = min(
                    max(abs(cx - corner[0]), abs(cy - corner[1])) for cx, cy in cols
                )
                assert near <= 1500, corner


def test_plan_fixture_masonry_walls_fully_beam_covered(plan_result):
    """Every masonry wall >= 115 mm and > 1.5 m is covered at its level."""
    r = plan_result
    model = plan_model()
    total = checked = 0
    for wall in model.walls:
        t_mm = round(wall.thickness_m * 1000)
        axis = M.wall_axis(wall)
        length = round((axis[3] - axis[2]) * 1000)
        if wall.material != M.Material.BRICK_MASONRY or t_mm < 115 or length <= 1500:
            continue
        total += 1
        orient, pos_m, s0, s1 = axis
        level_beams = [b for b in r.beams if b.level_key == str(wall.storey)]
        covered = _covered(
            level_beams, orient, round(pos_m * 1000), round(s0 * 1000), round(s1 * 1000),
            max(60, t_mm // 2),
        )
        if covered >= 0.98 * length:
            checked += 1
    assert total > 0
    assert checked == total
    assert r.metrics["beams_under_walls_pct"] == 100


def test_plan_fixture_panels_tile_each_storey_exactly(plan_result):
    for storey in (0, 1):
        panel_area = sum(p.area_mm2() for p in plan_result.panels if p.level == storey)
        assert panel_area == _footprint_area(plan_result, storey)


def test_plan_fixture_door_stance_is_disclosed(plan_result):
    assumptions = plan_result.report["assumptions"]
    assert any(a.startswith("doors unknown: mid-third rule applied") for a in assumptions)


def test_plan_fixture_balcony_panels_are_cantilever_kind(plan_result):
    kinds = {p.kind for p in plan_result.panels}
    assert "cantilever" in kinds  # the 5 ft balcony strip
    assert "slab" in kinds


def test_plan_fixture_column_sizes_follow_the_two_storey_rung(plan_result):
    for stack in plan_result.columns:
        assert (stack.w_mm, stack.d_mm) == (230, 300)  # 2 storeys carried
        assert stack.rot in (0, 90)


# ---------------------------------------------------------------------------
# the building fixture, end to end
# ---------------------------------------------------------------------------


def test_building_fixture_runs_fast_and_valid():
    model = building_model()
    start = time.time()
    r = run_frame_placement(model)
    elapsed = time.time() - start
    assert elapsed < 5.0
    assert r.valid is True
    assert sum(r.metrics["hard_violations"].values()) == 0


def test_building_fixture_panels_tile_and_classify(building_result):
    r = building_result
    for storey in (0, 1, 2):
        panel_area = sum(p.area_mm2() for p in r.panels if p.level == storey)
        assert panel_area == _footprint_area(r, storey)
    kinds = {p.kind for p in r.panels}
    assert "stair" in kinds and "opening" in kinds  # the two fixed-element cores


def test_building_fixture_bbox_corners_have_columns(building_result):
    cols = {(c.x_mm, c.y_mm) for c in building_result.columns}
    for corner in ((0, 0), (25603, 0), (0, 15545), (25603, 15545)):
        assert corner in cols, corner


def test_building_fixture_no_overspans_and_bounded_load_path(building_result):
    r = building_result
    for beam in r.beams:
        if beam.kind in (M.BeamKind.PRIMARY, M.BeamKind.SECONDARY):
            assert beam.span_mm <= 7500, beam.id
    assert r.metrics["load_path_depth"] <= 3
    assert r.metrics["beams_under_walls_pct"] == 100


def test_building_fixture_plinth_connects_all_ground_columns(building_result):
    r = building_result
    ground = [c for c in r.columns if 0 in c.exists and not c.transfer]
    plinths = [b for b in r.beams if b.kind == M.BeamKind.PLINTH]
    assert plinths and all(b.level_key == "P" for b in plinths)
    assert all(b.id.startswith("pbeam-") for b in plinths)
    index = {i: i for i in range(len(ground))}

    def find(i):
        while index[i] != i:
            index[i] = index[index[i]]
            i = index[i]
        return i

    def union(i, j):
        index[find(i)] = find(j)

    def at(x, y):
        for i, c in enumerate(ground):
            if abs(c.x_mm - x) <= 60 and abs(c.y_mm - y) <= 60:
                return i
        return None

    for beam in plinths:
        (x1, y1), (x2, y2) = beam.points_mm()
        a, b = at(x1, y1), at(x2, y2)
        assert a is not None and b is not None, beam.id
        union(a, b)
    roots = {find(i) for i in range(len(ground))}
    assert len(roots) == 1  # one connected plinth diaphragm


# ---------------------------------------------------------------------------
# corridor rule
# ---------------------------------------------------------------------------


def test_no_column_strictly_inside_the_corridor_and_both_edges_framed():
    r = run_frame_placement(corridor_model())
    assert r.valid is True
    for c in r.columns:
        strictly_inside = 0 < c.x_mm < 12000 and 5000 < c.y_mm < 6800
        assert not strictly_inside, (c.x_mm, c.y_mm)
    level = [b for b in r.beams if b.level_key == "0"]
    for edge in (5000, 6800):
        assert _covered(level, "h", edge, 0, 12000, 60) >= int(0.98 * 12000), edge


def test_corridor_edge_columns_do_not_raise_the_merge_floor():
    r = run_frame_placement(corridor_model())
    codes = {e.code for e in r.log.entries}
    assert "E_MERGE_FLOOR" not in codes


# ---------------------------------------------------------------------------
# door avoidance
# ---------------------------------------------------------------------------


def test_dressed_door_slides_the_column_to_the_jamb():
    model = dressed_door_model()
    assert model.doors_known() is True
    r = run_frame_placement(model)
    on_wall = sorted(c.y_mm for c in r.columns if abs(c.x_mm - 5000) <= 100)
    # forbidden interval: 3550 - 150 .. 4450 + 150 = (3400, 4600) open
    for y in on_wall:
        assert not (3400 < y < 4600), y
    # the mid station slid to exactly jamb + clearance
    assert 3400 in on_wall
    assert "W_COLUMN_IN_DOOR" not in {e.code for e in r.log.entries}
    assert r.report["assumptions"][0] == "doors read from dressed plan"


def test_undodgeable_door_drops_the_candidate_and_discloses():
    r = run_frame_placement(undodgeable_door_model())
    codes = {e.code for e in r.log.entries}
    assert "W_COLUMN_IN_DOOR" in codes
    entry = [e for e in r.log.entries if e.code == "W_COLUMN_IN_DOOR"][0]
    assert "w-s0-mid-v" in entry.element_ids
    for c in r.columns:
        if abs(c.x_mm - 5000) <= 60:
            assert not (0 < c.y_mm < 3000), c.y_mm


# ---------------------------------------------------------------------------
# slab feedback loop (spec 5.5)
# ---------------------------------------------------------------------------


def test_feedback_resolves_the_6x8_panel_with_one_secondary_each():
    """Released cap leaves one interior axis; the loop reinstates its primary,
    then breaks each 6 x 4 panel with exactly ONE secondary and t <= 150."""
    r = run_frame_placement(feedback_box_model(), FrameParams(max_primary_span=7.5))
    assert r.valid is True
    secondaries = [b for b in r.beams if b.kind == M.BeamKind.SECONDARY]
    assert [(b.orient, b.pos_mm, b.lo_mm, b.hi_mm) for b in secondaries] == [
        ("v", 3000, 0, 4000),
        ("v", 3000, 4000, 8000),
    ]
    slabs = [p for p in r.panels if p.kind == "slab"]
    assert len(slabs) == 4
    for panel in slabs:
        assert (panel.lx_mm, panel.ly_mm) == (3000, 4000)
        assert panel.t_mm == 125  # ceil5((3000 - 230) / 23)
        assert panel.t_mm <= 150
    codes = {e.code for e in r.log.entries}
    assert "W_COARSE_ITER" not in codes
    assert "E_GRID_COARSE" not in codes
    assert "W_THICK_SLAB" not in codes


def test_feedback_secondary_station_is_deterministic():
    a = _canonical(run_frame_placement(feedback_box_model(), FrameParams(max_primary_span=7.5)))
    b = _canonical(run_frame_placement(feedback_box_model(), FrameParams(max_primary_span=7.5)))
    assert a == b


def test_insert_secondary_beams_is_the_bounded_replace_entry():
    model = two_bay_model()
    base = run_frame_placement(model)
    target = [p.id for p in base.panels if p.kind == "slab"][:1]
    forced = insert_secondary_beams(model, panel_ids=target)
    base_n = sum(1 for b in base.beams if b.kind == M.BeamKind.SECONDARY)
    forced_n = sum(1 for b in forced.beams if b.kind == M.BeamKind.SECONDARY)
    assert forced_n > base_n
    again = insert_secondary_beams(model, panel_ids=target)
    assert _canonical(forced) == _canonical(again)


# ---------------------------------------------------------------------------
# vertical continuity (spec 5.2)
# ---------------------------------------------------------------------------


def test_setback_stack_slides_within_one_metre():
    """The slide-along-axis repair: an 0.8 m overhang corner walks back onto
    the ground footprint in 50 mm steps and records the displacement."""
    model = slide_model()
    params = FrameParams()
    grid = extract_axes(model, params)
    view = _View(model, grid, params)
    state = _ColumnState(view, plan_cores(model, grid, params), params)
    log = M.DisclosureLog()
    stack = _Stack(
        x_mm=10800, y_mm=0, anchor=100, origin="corner",
        exists=[1], top=1, base=1, score=Fraction(100), w_dir="h",
    )
    kept = enforce_continuity(view, [stack], state, params, log)
    assert len(kept) == 1
    repaired = kept[0]
    assert (repaired.x_mm, repaired.y_mm) == (10000, 0)
    assert repaired.slid_mm == -800
    assert repaired.slide_dir == "x"
    assert abs(repaired.slid_mm) <= 1000
    assert repaired.transfer is False


def test_slid_column_is_disclosed_in_repairs():
    # any full run that slides must land W_SLID and a repairs entry; the plan
    # and building fixtures do not slide, so drive the mechanism result shape
    r = run_frame_placement(slide_model())
    for entry in r.report["repairs"]:
        assert set(entry) == {"column", "d_mm", "dir"}
    slid = [c for c in r.columns if c.slid_mm]
    assert len(slid) == len(r.report["repairs"])


def test_floating_column_returns_transfer_error_with_full_placement():
    r = run_frame_placement(transfer_model())
    assert r.valid is False
    codes = {e.code for e in r.log.entries}
    assert "E_TRANSFER_REQUIRED" in codes
    assert r.metrics["hard_violations"]["E_TRANSFER_REQUIRED"] >= 1
    transfers = [c for c in r.columns if c.transfer]
    assert transfers, "the floating stack is kept in the output"
    assert all(c.unsupported == [0] for c in transfers)
    # the batch still returns a FULL placement
    assert r.columns and r.beams and r.panels
    assert r.report["errors"]
    # one entry per floating stack: each names its own stack and storeys, so
    # the ladder keeps them apart instead of collapsing onto the first message
    entries = [e for e in r.log.entries if e.code == "E_TRANSFER_REQUIRED"]
    assert all(e.clause == "IS 1893 Cl 7.1" for e in entries)
    ids = sorted(i for e in entries for i in e.element_ids)
    assert ids == sorted(c.id for c in transfers)
    for entry in entries:
        assert entry.element_ids[0] in entry.message


# ---------------------------------------------------------------------------
# cantilever ladder (spec 5.4 rule 4)
# ---------------------------------------------------------------------------


def test_cantilever_within_warning_band_frames_and_warns():
    r = run_frame_placement(cantilever_model(2.3))
    assert r.valid is True
    codes = {e.code for e in r.log.entries}
    assert "W_CANTILEVER" in codes
    cants = [b for b in r.beams if b.kind == M.BeamKind.CANTILEVER and b.level_key == "1"]
    assert cants and all(b.span_mm == 2300 for b in cants)
    spandrels = [b for b in r.beams if b.kind == M.BeamKind.SPANDREL]
    assert spandrels and spandrels[0].pos_mm == 12300  # the tip edge
    assert {p.kind for p in r.panels if p.level == 1} >= {"cantilever", "slab"}


def test_cantilever_within_auto_band_is_silent():
    r = run_frame_placement(cantilever_model(1.8))
    codes = {e.code for e in r.log.entries}
    assert "W_CANTILEVER" not in codes
    assert any(b.kind == M.BeamKind.CANTILEVER for b in r.beams)


def test_cantilever_beyond_refusal_is_an_error():
    r = run_frame_placement(transfer_model())  # the 3 m shift is > 2.5 m deep
    assert "E_CANTILEVER_SPAN" in {e.code for e in r.log.entries}
    assert r.valid is False


def test_short_backspan_is_disclosed():
    """A 2.0 m projection off a 2.5 m backspan is under the 1.5x rule."""
    model = M.StructuralModel(
        id="backspan",
        storeys=_storeys(2),
        rooms=[
            _room(0, "g", M.Occupancy.HABITABLE, 0, 0, 2.5, 8),
            _room(1, "u", M.Occupancy.HABITABLE, 0, 0, 4.5, 8),
        ],
        walls=_box_walls(0, 0, 0, 2.5, 8) + _box_walls(1, 0, 0, 4.5, 8),
    )
    r = run_frame_placement(model)
    assert r.valid is True
    assert "W_BACKSPAN" in {e.code for e in r.log.entries}


# ---------------------------------------------------------------------------
# plinth and tie levels
# ---------------------------------------------------------------------------


def test_plinth_beams_connect_all_ground_columns_of_the_plan_fixture(plan_result):
    ground = [c for c in plan_result.columns if 0 in c.exists and not c.transfer]
    plinths = [b for b in plan_result.beams if b.kind == M.BeamKind.PLINTH]
    ends = set()
    for beam in plinths:
        assert beam.width_mm == 230 and beam.depth_mm == 300
        (x1, y1), (x2, y2) = beam.points_mm()
        ends.add((x1, y1))
        ends.add((x2, y2))
    for c in ground:
        assert any(abs(c.x_mm - x) <= 60 and abs(c.y_mm - y) <= 60 for x, y in ends), c.id


def test_tie_level_appears_only_above_the_trigger():
    tall = run_frame_placement(tall_ground_model(4.2))
    ties = [b for b in tall.beams if b.kind == M.BeamKind.TIE]
    assert ties and all(b.level_key == "T0" and b.storey == 0 for b in ties)
    assert all(b.width_mm == 230 and b.depth_mm == 300 for b in ties)
    low = run_frame_placement(tall_ground_model(3.0))
    assert not any(b.kind == M.BeamKind.TIE for b in low.beams)


# ---------------------------------------------------------------------------
# thumb pre-sizes (spec 5.3)
# ---------------------------------------------------------------------------


def test_column_ladder_and_beam_depth_formula():
    r = run_frame_placement(two_bay_model())
    for stack in r.columns:
        assert (stack.w_mm, stack.d_mm) == (230, 230)  # single storey
    for beam in r.beams:
        if beam.kind == M.BeamKind.PRIMARY:
            # clamp(ceil25(4000 / 12), 300, 750) = 350, width 230 under 6 m
            assert beam.depth_mm == 350
            assert beam.width_mm == 230


def test_tall_ladder_rungs():
    def tower(n):
        rooms = []
        walls = []
        for i in range(n):
            rooms.append(_room(i, "f", M.Occupancy.HABITABLE, 0, 0, 8, 6))
            walls.extend(_box_walls(i, 0, 0, 8, 6))
        return M.StructuralModel(id="t%d" % n, storeys=_storeys(n), rooms=rooms, walls=walls)

    r3 = run_frame_placement(tower(3))
    assert {(c.w_mm, c.d_mm) for c in r3.columns} == {(300, 300)}
    assert "W_TALL" not in {e.code for e in r3.log.entries}
    r6 = run_frame_placement(tower(6))
    assert {(c.w_mm, c.d_mm) for c in r6.columns} == {(380, 450)}
    assert "W_TALL" in {e.code for e in r6.log.entries}


# ---------------------------------------------------------------------------
# the metrics block and the score formula (spec section 7, finding 33)
# ---------------------------------------------------------------------------


def test_score_hand_computed_on_the_two_bay_fixture():
    """Every number verifiable by hand:

    6 columns on the 3 x 2 grid, 7 primary spans of exactly 4.0 m (all in the
    2.5..5 band), 0 eccentricity (every column on a wall), 0 torsion by
    symmetry, axes exactly at the ideal count, walls 100 pct covered.
    columns_per_100m2 = 6 * 100 / 32 = 18.75, distance over the band = 11.75,
    deduction min(8, round(23.5)) = 8. Score = 100 - 8 = 92.
    """
    r = run_frame_placement(two_bay_model())
    assert sorted((c.x_mm, c.y_mm) for c in r.columns) == [
        (0, 0), (0, 4000), (4000, 0), (4000, 4000), (8000, 0), (8000, 4000),
    ]
    assert r.metrics == {
        "score": 92,
        "score_version": "frame-1",
        "hard_violations": {
            "E_TRANSFER_REQUIRED": 0,
            "E_CANTILEVER_SPAN": 0,
            "E_FRAMING_DEPTH": 0,
            "E_GRID_COARSE": 0,
            "E_SPAN_OVER_MAX": 0,
            "E_MERGE_FLOOR": 0,
        },
        "span_histogram": {
            "lt_2_5": 0,
            "2_5_3": 0,
            "3_4": 0,
            "4_5": 7,
            "5_6": 0,
            "6_7_5": 0,
            "gt_7_5": 0,
            "pct_in_2_5_to_5": 100.0,
        },
        "axis_count": {"x": 3, "y": 2, "x_inserted": 0, "y_inserted": 0},
        "column_eccentricity_mm": {"mean": 0, "max": 0},
        "torsion_proxy_pct": {"x": 0.0, "y": 0.0},
        "columns_per_100m2": 18.75,
        "beams_under_walls_pct": 100,
        "load_path_depth": 3,
    }


def test_metrics_block_is_canonical(plan_result, building_result):
    canonical = {
        "score",
        "score_version",
        "hard_violations",
        "span_histogram",
        "axis_count",
        "column_eccentricity_mm",
        "torsion_proxy_pct",
        "columns_per_100m2",
        "beams_under_walls_pct",
        "load_path_depth",
    }
    for r in (plan_result, building_result):
        assert set(r.metrics) == canonical
        assert set(r.metrics["hard_violations"]) == {
            "E_TRANSFER_REQUIRED",
            "E_CANTILEVER_SPAN",
            "E_FRAMING_DEPTH",
            "E_GRID_COARSE",
            "E_SPAN_OVER_MAX",
            "E_MERGE_FLOOR",
        }
        histogram = dict(r.metrics["span_histogram"])
        pct = histogram.pop("pct_in_2_5_to_5")
        assert 0.0 <= pct <= 100.0
        assert set(histogram) == {"lt_2_5", "2_5_3", "3_4", "4_5", "5_6", "6_7_5", "gt_7_5"}
        assert sum(histogram.values()) == sum(
            1 for b in r.beams if b.kind == M.BeamKind.PRIMARY
        )


def test_hard_violation_floors_the_score():
    r = run_frame_placement(transfer_model())
    hv = sum(r.metrics["hard_violations"].values())
    assert hv >= 2  # transfer stacks + refused cantilever
    assert r.metrics["score"] <= max(0, 100 - 30 * hv) + 0  # -30 each, floored


# ---------------------------------------------------------------------------
# determinism (spec section 10)
# ---------------------------------------------------------------------------


def test_plan_fixture_byte_identical_on_repeat_and_permutation():
    reference = _canonical(run_frame_placement(plan_model()))
    assert _canonical(run_frame_placement(plan_model())) == reference
    for shift in (3, 11):
        model = plan_model()
        model.walls = model.walls[shift:] + model.walls[:shift]
        model.rooms = list(reversed(model.rooms))
        assert _canonical(run_frame_placement(model)) == reference


def test_building_fixture_byte_identical_on_repeat():
    a = _canonical(run_frame_placement(building_model()))
    b = _canonical(run_frame_placement(building_model()))
    assert a == b


def test_element_ids_are_unique_and_model_derived(plan_result):
    ids = [c.id for c in plan_result.columns]
    ids += [b.id for b in plan_result.beams]
    ids += [p.id for p in plan_result.panels]
    assert len(ids) == len(set(ids))
    for stack in plan_result.columns:
        assert stack.id.startswith("stk-")
    for beam in plan_result.beams:
        assert beam.id.startswith("beam-") or beam.id.startswith("pbeam-")
    for panel in plan_result.panels:
        assert panel.id.startswith("slab-s")


# ---------------------------------------------------------------------------
# write_back: downstream waves read the model alone
# ---------------------------------------------------------------------------


def test_write_back_installs_the_placement_on_the_model(plan_result):
    model = plan_model()
    plan_result.write_back(model)
    assert model.axes and model.columns and model.beams and model.slabs
    assert [d.code for d in model.validate()] == []
    # per-storey columns via model helpers, sharing the stack id
    by_stack = {}
    for column in model.columns:
        assert column.id.startswith("col-")
        assert column.placed_by.startswith("placement.frame.")
        by_stack.setdefault(column.stack_id, []).append(column.storey)
    for stack in plan_result.columns:
        assert sorted(by_stack[stack.id]) == sorted(stack.exists)
    for beam in model.beams:
        assert isinstance(beam.kind, M.BeamKind)
    top = max(s.index for s in model.storeys)
    for slab in model.slabs:
        expected = M.SlabKind.ROOF if slab.storey == top else M.SlabKind.FLOOR
        assert slab.kind == expected
    meta = model.meta["frame_placement"]
    assert meta["score_version"] == SCORE_VERSION
    assert meta["valid"] is True
    assert meta["metrics"] == plan_result.metrics
    assert {w.code for w in model.warnings} >= {e.code for e in plan_result.log.entries}


def test_write_back_keeps_stair_and_shaft_records_in_meta(building_result):
    model = building_model()
    building_result.write_back(model)
    meta = model.meta["frame_placement"]
    assert len(meta["stair_slabs"]) == len(building_result.stair_slabs) == 6
    assert meta["core_notes"]
    assert any(n["note"] == "lift_pit" for n in meta["core_notes"])


# ---------------------------------------------------------------------------
# lintels over masonry infill (finding 40)
# ---------------------------------------------------------------------------


def test_place_lintels_for_infill_covers_every_masonry_opening():
    model = plan_model()
    openings = sum(len(w.openings) for w in model.walls)
    lintels = place_lintels_for_infill(model)
    assert len(lintels) == openings > 0
    for lin in lintels:
        wall = model.by_id(lin.wall_id)
        opening = next(o for o in wall.openings if o.id == lin.opening_id)
        assert lin.span_m == pytest.approx(opening.width_m + 0.3)
        assert lin.id.startswith("lin-" + wall.id)
        assert lin.placed_by == "placement.frame.lintel_infill"
    # idempotent: a second call replaces, never duplicates
    again = place_lintels_for_infill(model)
    assert len(model.lintels) == len(again) == openings


def test_lintels_skip_non_masonry_walls():
    model = dressed_door_model()
    for wall in model.walls:
        if wall.id == "w-s0-mid":
            wall.material = M.Material.RC
    lintels = place_lintels_for_infill(model)
    assert all(lin.wall_id != "w-s0-mid" for lin in lintels)


# ---------------------------------------------------------------------------
# result wire shape + frontend parity (finding 12: the map is client-side,
# so the wire must carry everything the StructuralGrid mapping needs)
# ---------------------------------------------------------------------------


def test_result_wire_shape(plan_result):
    wire = plan_result.to_dict()
    assert set(wire) == {
        "axes",
        "columns",
        "beams",
        "panels",
        "shaft_walls",
        "stair_slabs",
        "core_notes",
        "params",
        "metrics",
        "report",
        "valid",
    }
    assert set(wire["report"]) == {"summary", "errors", "warnings", "assumptions", "repairs"}
    assert wire["params"]["max_primary_span_m"] == 5.0
    assert wire["valid"] is True


def test_wire_carries_everything_the_frontend_grid_map_needs(plan_result):
    """Parity fixture (spec section 8 as a test, not shipped code): build the
    StructuralGrid-shaped dict the frontend derives and check nothing is
    missing or mistyped."""
    wire = plan_result.to_dict()
    closed = {"outline", "corridor", "party", "inserted"}
    source_map = lambda s: s if s in ("outline", "corridor", "party") else "inserted"
    grid = {
        "xLines": [
            {"pos": a["pos_m"] / M.FT, "source": source_map(a["source"]), "label": a["label"]}
            for a in wire["axes"]["x"]
        ],
        "yLines": [
            {"pos": a["pos_m"] / M.FT, "source": source_map(a["source"]), "label": a["label"]}
            for a in wire["axes"]["y"]
        ],
        "columns": [
            {
                "x": c["x_m"] / M.FT,
                "y": c["y_m"] / M.FT,
                "widthFt": c["width_mm"] / 304.8,
                "depthFt": c["depth_mm"] / 304.8,
                "rot": c["rot"],
                "onGrid": c["on_grid"],
            }
            for c in wire["columns"]
        ],
        "beams": [
            {
                "x1": b["x1_m"] / M.FT,
                "y1": b["y1_m"] / M.FT,
                "x2": b["x2_m"] / M.FT,
                "y2": b["y2_m"] / M.FT,
                "widthFt": b["width_mm"] / 304.8,
            }
            for b in wire["beams"]
            if b["level"] == 0 and b["kind"] in ("primary", "secondary")
        ],
        "warnings": [w["message"] for w in wire["report"]["warnings"]],
    }
    assert grid["xLines"] and grid["yLines"] and grid["columns"] and grid["beams"]
    for line in grid["xLines"] + grid["yLines"]:
        assert line["source"] in closed
        assert isinstance(line["label"], str) and line["label"]
    for column in grid["columns"]:
        assert column["rot"] in (0, 90)
        assert isinstance(column["onGrid"], bool)
    sizes = sorted((c["width_mm"], c["depth_mm"]) for c in wire["columns"])
    assert sizes[len(sizes) // 2] == (230, 300)  # the modal columnSize
    for beam in wire["beams"]:
        assert beam["kind"] in {k.value for k in M.BeamKind}
    for key in ("x1_m", "y1_m", "x2_m", "y2_m", "span_m"):
        assert all(isinstance(b[key], float) for b in wire["beams"])


def test_units_leave_the_module_in_metres(plan_result):
    wire = plan_result.to_dict()
    # the plan is 9.144 x 12.192 m: every coordinate must be in that range
    for c in wire["columns"]:
        assert 0.0 <= c["x_m"] <= 9.144 + 1e-9
        assert 0.0 <= c["y_m"] <= 12.192 + 1e-9
        assert c["width_mm"] >= 100  # sections stay mm
    for a in wire["axes"]["x"]:
        assert 0.0 <= a["pos_m"] <= 9.144 + 1e-9
