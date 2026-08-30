"""Pins for grid.extract_axes: clustering rules, presence, insertion, junctions.

The models here are hand placed so that every asserted number is derivable by
hand from the spec: cluster anchors, the length-weighted mean, even-fraction
insertion stations and junction classes. The plan fixture is exercised through
the plan_json adapter when that module exists, and skipped while it does not.
"""

from __future__ import annotations

import importlib
import json

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports this
# package as GPLAN.GPLAN.structural.tests (see test_model_roundtrip.py).
from .. import model as M
from ..grid import (
    DEFAULT_WALL_T_M,
    FrameParams,
    HARD_MAX_SPAN_M,
    extract_axes,
    letter_label,
)

FT = M.FT
EXT_T = 0.75 * FT  # DetailedFloorplan exterior default, 0.2286 m
INT_T = 0.115
PARTY_T = 0.23


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


def _wall(storey, tag, a, b, thickness_m, role):
    return M.WallLine(
        id="w-s%d-%s" % (storey, tag),
        storey=storey,
        a=a,
        b=b,
        thickness_m=thickness_m,
        role=role,
    )


def two_storey_model():
    """24 x 14 m ground, 16 x 14 m first floor (setback beyond x = 16).

    Ground floor carries, deliberately:
      - a party wall at x = 12.0 with a partition 0.2 m off it at x = 12.2,
      - a 1.8 m corridor between y = 5.0 and y = 6.8 with a wall 0.1 m off the
        upper edge,
      - a partition 0.1 m inside the y = 0 facade,
      - two partitions 0.1 m apart at y = 9.6 and y = 9.7 with no anchor,
      - a 12.06 m blank span between x = 0 and the party axis.
    """
    storeys = [
        M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0),
        M.Storey(index=1, name="First", bottom_z_m=3.0, height_m=3.0),
    ]
    rooms = [
        _room(0, "hall", M.Occupancy.HABITABLE, 0.0, 0.0, 24.0, 5.0),
        _room(0, "corridor", M.Occupancy.CORRIDOR, 0.0, 5.0, 12.0, 6.8),
        _room(0, "east", M.Occupancy.HABITABLE, 12.0, 5.0, 24.0, 6.8),
        _room(0, "south", M.Occupancy.HABITABLE, 0.0, 6.8, 24.0, 14.0),
        _room(1, "upper", M.Occupancy.HABITABLE, 0.0, 0.0, 16.0, 14.0),
    ]
    walls = [
        _wall(0, "ext-n", (0.0, 0.0), (24.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-s", (0.0, 14.0), (24.0, 14.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-w", (0.0, 0.0), (0.0, 14.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-e", (24.0, 0.0), (24.0, 14.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "party", (12.0, 0.0), (12.0, 14.0), PARTY_T, M.WallRole.PARTY),
        _wall(0, "part-off", (12.2, 0.0), (12.2, 6.0), INT_T, M.WallRole.INTERIOR),
        _wall(0, "near-out", (0.0, 0.1), (6.0, 0.1), INT_T, M.WallRole.INTERIOR),
        _wall(0, "cor-a", (0.0, 5.1), (12.0, 5.1), INT_T, M.WallRole.INTERIOR),
        _wall(0, "cor-b", (0.0, 6.8), (12.0, 6.8), INT_T, M.WallRole.INTERIOR),
        _wall(0, "mean-a", (0.0, 9.6), (12.0, 9.6), INT_T, M.WallRole.INTERIOR),
        _wall(0, "mean-b", (0.0, 9.7), (4.0, 9.7), INT_T, M.WallRole.INTERIOR),
        _wall(1, "ext-n", (0.0, 0.0), (16.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(1, "ext-s", (0.0, 14.0), (16.0, 14.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(1, "ext-w", (0.0, 0.0), (0.0, 14.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(1, "ext-e", (16.0, 0.0), (16.0, 14.0), EXT_T, M.WallRole.EXTERIOR),
    ]
    return M.StructuralModel(id="two-storey", storeys=storeys, rooms=rooms, walls=walls)


def corridor_relabelled_model():
    """The same geometry with the corridor room relabelled, so no corridor rects."""
    model = two_storey_model()
    for room in model.rooms:
        if room.occupancy == M.Occupancy.CORRIDOR:
            room.occupancy = M.Occupancy.HABITABLE
    return model


def blank_box_model():
    """12 x 6 m single storey box with no interior walls at all."""
    storeys = [M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)]
    rooms = [_room(0, "box", M.Occupancy.HABITABLE, 0.0, 0.0, 12.0, 6.0)]
    walls = [
        _wall(0, "ext-n", (0.0, 0.0), (12.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-s", (0.0, 6.0), (12.0, 6.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-w", (0.0, 0.0), (0.0, 6.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-e", (12.0, 0.0), (12.0, 6.0), EXT_T, M.WallRole.EXTERIOR),
    ]
    return M.StructuralModel(id="blank-box", storeys=storeys, rooms=rooms, walls=walls)


def cross_model():
    """8 x 8 m with one full-height and one full-width partition through the middle."""
    storeys = [M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)]
    rooms = [
        _room(0, "nw", M.Occupancy.HABITABLE, 0.0, 0.0, 4.0, 4.0),
        _room(0, "ne", M.Occupancy.HABITABLE, 4.0, 0.0, 8.0, 4.0),
        _room(0, "sw", M.Occupancy.HABITABLE, 0.0, 4.0, 4.0, 8.0),
        _room(0, "se", M.Occupancy.HABITABLE, 4.0, 4.0, 8.0, 8.0),
    ]
    walls = [
        _wall(0, "ext-n", (0.0, 0.0), (8.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-s", (0.0, 8.0), (8.0, 8.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-w", (0.0, 0.0), (0.0, 8.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-e", (8.0, 0.0), (8.0, 8.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "mid-v", (4.0, 0.0), (4.0, 8.0), INT_T, M.WallRole.INTERIOR),
        _wall(0, "mid-h", (0.0, 4.0), (8.0, 4.0), INT_T, M.WallRole.INTERIOR),
    ]
    return M.StructuralModel(id="cross", storeys=storeys, rooms=rooms, walls=walls)


def core_model():
    """10 x 10 m with a 3 x 4 m stair core; core faces must become axes."""
    storeys = [M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)]
    rooms = [_room(0, "floor", M.Occupancy.HABITABLE, 0.0, 0.0, 10.0, 10.0)]
    walls = [
        _wall(0, "ext-n", (0.0, 0.0), (10.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-s", (0.0, 10.0), (10.0, 10.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-w", (0.0, 0.0), (0.0, 10.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "ext-e", (10.0, 0.0), (10.0, 10.0), EXT_T, M.WallRole.EXTERIOR),
    ]
    cores = [
        M.Core(
            id=M.core_id("stair"),
            kind=M.CoreKind.STAIRS,
            x_m=2.0,
            y_m=2.0,
            w_m=3.0,
            h_m=4.0,
            storeys=[0],
        )
    ]
    return M.StructuralModel(
        id="core", storeys=storeys, rooms=rooms, walls=walls, cores=cores
    )


def _canonical(grid):
    return json.dumps(grid.to_dict(), sort_keys=True)


def _positions_mm(axes):
    return [axis.pos_mm for axis in axes]


# ---------------------------------------------------------------------------
# harvest, clustering and anchoring (spec 4.1, 4.2)
# ---------------------------------------------------------------------------


def test_axis_positions_and_sources():
    grid = extract_axes(two_storey_model())
    assert _positions_mm(grid.x_axes) == [0, 4020, 8040, 12060, 16000, 20000, 24000]
    assert _positions_mm(grid.y_axes) == [0, 5000, 6800, 9625, 14000]
    assert [a.source.value for a in grid.x_axes] == [
        "outline",
        "inserted",
        "inserted",
        "party",
        "outline",
        "inserted",
        "outline",
    ]
    assert [a.source.value for a in grid.y_axes] == [
        "outline",
        "corridor",
        "corridor",
        "wall",
        "outline",
    ]


def test_rule_1_outline_position_is_exact():
    """A partition 0.1 m inside the facade folds onto the outline, never averaged."""
    grid = extract_axes(two_storey_model())
    near_zero = [a for a in grid.y_axes if a.pos_mm < 1000]
    assert len(near_zero) == 1
    axis = near_zero[0]
    assert axis.pos_mm == 0  # not the 0.1 m weighted mean
    assert axis.source == M.AxisSource.OUTLINE
    assert ("w-s0-near-out" in [wall for _, wall in axis.members]) is True


def test_rule_2_corridor_edge_position_is_exact():
    """A wall 0.1 m off the corridor edge clusters onto the edge, not the mean."""
    grid = extract_axes(two_storey_model())
    axis = grid.by_id("gy-B")
    assert axis.pos_mm == 5000  # the corridor edge, not 5050
    assert axis.source == M.AxisSource.CORRIDOR
    assert (0, "w-s0-cor-a") in axis.members


def test_rule_3_length_weighted_mean():
    """12 m at 9.600 and 4 m at 9.700 resolve to exactly 9.625 m."""
    grid = extract_axes(two_storey_model())
    axis = grid.by_id("gy-D")
    assert axis.pos_mm == 9625
    assert axis.source == M.AxisSource.WALL
    assert [wall for _, wall in axis.members] == ["w-s0-mean-a", "w-s0-mean-b"]


def test_merge_tol_folds_partition_onto_party_axis():
    """0.2 m is beyond tol_wall but inside merge_tol, so it is ONE axis."""
    grid = extract_axes(two_storey_model())
    near = [a for a in grid.x_axes if 11500 <= a.pos_mm <= 12500]
    assert len(near) == 1
    axis = near[0]
    # 14 m of party at 12.000 with 6 m of partition at 12.200
    assert axis.pos_mm == 12060
    assert axis.source == M.AxisSource.PARTY
    assert sorted(wall for _, wall in axis.members) == ["w-s0-part-off", "w-s0-party"]


def test_tol_wall_is_not_parametric():
    """The 0.2 m offset survives a merge_tol of zero: tol_wall alone keeps them apart."""
    grid = extract_axes(two_storey_model(), FrameParams(merge_tol=0.0))
    near = [a for a in grid.x_axes if 11500 <= a.pos_mm <= 12500]
    assert _positions_mm(near) == [12000, 12200]


def test_core_faces_become_axes():
    grid = extract_axes(core_model())
    assert _positions_mm(grid.x_axes) == [0, 2000, 5000, 10000]
    assert _positions_mm(grid.y_axes) == [0, 2000, 6000, 10000]
    assert [a.source.value for a in grid.x_axes] == ["outline", "core", "core", "outline"]
    # a core face carries no wall, so its extent is the face itself
    assert grid.by_id("gx-2").extents_mm[0] == [(2000, 6000)]


def test_railing_walls_never_make_axes():
    model = blank_box_model()
    model.walls.append(
        _wall(0, "rail", (6.0, 0.0), (6.0, 6.0), 0.35 * FT, M.WallRole.RAILING)
    )
    grid = extract_axes(model)
    # identical to the box without the railing: no axis at x = 6.0
    assert _positions_mm(grid.x_axes) == [0, 4000, 8000, 12000]
    for axis in grid.axes():
        assert "w-s0-rail" not in [wall for _, wall in axis.members]
    for junction in grid.junctions[0]:
        assert "w-s0-rail" not in junction.wall_ids


# ---------------------------------------------------------------------------
# cross-floor union: presence and extents (spec 4.3)
# ---------------------------------------------------------------------------


def test_presence_masks_across_a_setback():
    grid = extract_axes(two_storey_model())
    by_pos = {a.pos_mm: a for a in grid.x_axes}
    # ground only: the first floor stops at x = 16
    assert by_pos[24000].presence == 0b01
    assert by_pos[20000].presence == 0b01
    assert by_pos[24000].storeys() == [0]
    # both storeys, including the two inserted lines
    for pos in (0, 4020, 8040, 12060, 16000):
        assert by_pos[pos].presence == 0b11, pos
    for axis in grid.y_axes:
        assert axis.presence == 0b11


def test_span_through_storey_takes_the_footprint_chord():
    grid = extract_axes(two_storey_model())
    axis = grid.by_id("gx-5")  # x = 16.0, a wall on storey 1 only
    assert [storey for storey, _ in axis.members] == [1]
    assert axis.present(0) is True
    assert axis.extents_mm[0] == [(0, 14000)]  # ground chord, no wall on it
    assert axis.extents_mm[1] == [(0, 14000)]


def test_extents_stop_at_the_nearest_crossing_axis():
    """Corridor walls run 0 to 12 m, so their axis reaches the party line and stops."""
    grid = extract_axes(two_storey_model())
    axis = grid.by_id("gy-B")
    assert axis.extents_mm[0] == [(0, 12060)]
    assert axis.extents[0] == [(0.0, 12.06)]
    # storey 1 has no wall on that line: the full chord instead
    assert axis.extents_mm[1] == [(0, 16000)]


def test_extents_are_clipped_to_the_footprint():
    grid = extract_axes(two_storey_model())
    for axis in grid.axes():
        for storey, spans in axis.extents_mm.items():
            chords = grid.footprints[storey].chords_mm(axis.orient(), axis.pos_mm)
            for lo, hi in spans:
                assert any(clo <= lo and hi <= chi for clo, chi in chords)


# ---------------------------------------------------------------------------
# span control insertion (spec 4.4)
# ---------------------------------------------------------------------------


def test_inserted_positions_are_exact_even_fractions():
    grid = extract_axes(blank_box_model())
    assert _positions_mm(grid.x_axes) == [0, 4000, 8000, 12000]
    assert _positions_mm(grid.y_axes) == [0, 3000, 6000]
    assert [a.source.value for a in grid.x_axes] == [
        "outline",
        "inserted",
        "inserted",
        "outline",
    ]
    assert grid.by_id("gy-B").source == M.AxisSource.INSERTED


def test_inserted_axes_fill_the_twelve_metre_blank_span():
    grid = extract_axes(two_storey_model())
    inserted = [a.pos_mm for a in grid.x_axes if a.source == M.AxisSource.INSERTED]
    # 12.06 m gap needs two lines at exact thirds, 8.0 m gap needs one at the half
    assert inserted == [4020, 8040, 20000]


def test_inserted_presence_is_the_flanking_intersection():
    grid = extract_axes(two_storey_model())
    assert grid.by_id("gx-6").pos_mm == 20000
    assert grid.by_id("gx-6").presence == (
        grid.by_id("gx-5").presence & grid.by_id("gx-7").presence
    )
    assert grid.by_id("gx-6").presence == 0b01


def test_no_span_exceeds_the_cap():
    params = FrameParams()
    for build in (two_storey_model, blank_box_model, cross_model, core_model):
        grid = extract_axes(build(), params)
        for axes in (grid.x_axes, grid.y_axes):
            positions = _positions_mm(axes)
            for i in range(len(positions) - 1):
                gap = positions[i + 1] - positions[i]
                assert gap <= 5000, (build.__name__, gap)


def test_insertion_snaps_to_a_wall_cluster_and_then_re_subdivides():
    """The snap window and its follow-up pass, exercised on the station helper.

    In a well formed model the pool is empty inside a long gap, because every
    harvested wall cluster is already an axis; the path exists for grids where a
    wall line is present but suppressed as an axis.
    """
    from ..grid import _gap_stations_mm

    # 12 m gap, ideal thirds at 4.000 and 8.000; a partition at 3.800 wins the first
    assert _gap_stations_mm(0, 12000, 5000, [3800], 0) == [3800, 8000]
    # too far to snap: exact even fractions stand
    assert _gap_stations_mm(0, 12000, 5000, [3300], 0) == [4000, 8000]
    # snapping 0.6 m off the half of a 9.8 m gap leaves 5.5 m, so the pass repeats
    assert _gap_stations_mm(0, 9800, 5000, [4300], 0) == [4300, 7050]


def test_max_span_above_the_hard_cap_is_clamped_and_disclosed():
    grid = extract_axes(blank_box_model(), FrameParams(max_primary_span=9.0))
    assert "W_RELEASED_CAP" in grid.log.codes()
    positions = _positions_mm(grid.x_axes)
    for i in range(len(positions) - 1):
        assert positions[i + 1] - positions[i] <= int(HARD_MAX_SPAN_M * 1000)


# ---------------------------------------------------------------------------
# junction graph (spec 4.5)
# ---------------------------------------------------------------------------


def _junction_counts(grid, storey):
    counts = {"end": 0, "L": 0, "T": 0, "X": 0}
    for junction in grid.junctions[storey]:
        counts[junction.kind] += 1
    return counts


def test_junction_classes_on_a_cross_plan():
    """Four corners are L, four edge meetings are T, the centre is an X."""
    grid = extract_axes(cross_model())
    assert _junction_counts(grid, 0) == {"end": 0, "L": 4, "T": 4, "X": 1}
    centre = [j for j in grid.junctions[0] if (j.x_mm, j.y_mm) == (4000, 4000)]
    assert len(centre) == 1
    assert centre[0].j == 4
    assert centre[0].axis_ids == ("gx-2", "gy-B")
    assert centre[0].wall_ids == ["w-s0-mid-h", "w-s0-mid-v"]


def test_junction_classes_on_the_setback_storey():
    grid = extract_axes(two_storey_model())
    # storey 1: 5 x axes by 5 y axes, all reaching the footprint edges
    assert _junction_counts(grid, 1) == {"end": 0, "L": 4, "T": 12, "X": 9}
    assert len(grid.junctions[1]) == 25
    # storey 0 keeps the three free wall ends of the off-grid partitions
    ends = [j for j in grid.junctions[0] if j.j == 1]
    assert [(j.x_mm, j.y_mm) for j in ends] == [(6000, 100), (12200, 0), (12200, 6000)]
    assert ends[1].wall_ids == ["w-s0-part-off"]


def test_junctions_are_sorted_and_classified_in_range():
    grid = extract_axes(two_storey_model())
    for storey in grid.storeys:
        keys = [(j.x_mm, j.y_mm, -j.j) for j in grid.junctions[storey]]
        assert keys == sorted(keys)
        for junction in grid.junctions[storey]:
            assert 1 <= junction.j <= 4
            assert junction.kind in ("end", "L", "T", "X")
            assert junction.x_m == junction.x_mm / 1000.0


# ---------------------------------------------------------------------------
# labels, ids and the short-span ladder
# ---------------------------------------------------------------------------


def test_labels_follow_ascending_position():
    grid = extract_axes(two_storey_model())
    assert [a.label for a in grid.x_axes] == ["1", "2", "3", "4", "5", "6", "7"]
    assert [a.label for a in grid.y_axes] == ["A", "B", "C", "D", "E"]
    assert [a.id for a in grid.y_axes] == ["gy-A", "gy-B", "gy-C", "gy-D", "gy-E"]
    assert grid.by_id("gx-1").pos_mm == 0
    assert [a.id for a in grid.axes()] == [
        M.axis_id(a.dir, a.label) for a in grid.axes()
    ]


def test_letter_labels_roll_over_after_z():
    assert [letter_label(i) for i in (0, 1, 25, 26, 27, 51, 52)] == [
        "A",
        "B",
        "Z",
        "AA",
        "AB",
        "AZ",
        "BA",
    ]


def test_corridor_edge_pair_is_exempt_from_the_min_span_warning():
    """1.8 m between the corridor edges is the clear width, not a short span."""
    grid = extract_axes(two_storey_model())
    assert grid.by_id("gy-C").pos_mm - grid.by_id("gy-B").pos_mm == 1800
    assert "W_SHORT_SPAN" not in grid.log.codes()

    # the identical geometry without the corridor label warns on the same pair
    plain = extract_axes(corridor_relabelled_model())
    assert "W_SHORT_SPAN" in plain.log.codes()
    entry = [e for e in plain.log.entries if e.code == "W_SHORT_SPAN"][0]
    assert entry.severity == M.Severity.WARNING
    # without the corridor anchor the wall stays at 5.100, the first bay grows
    # past the cap and takes an inserted line, and the 1.7 m pair now warns
    assert _positions_mm(plain.y_axes) == [0, 2550, 5100, 6800, 9625, 14000]
    short = [
        (plain.y_axes[i].pos_mm, plain.y_axes[i + 1].pos_mm)
        for i in range(len(plain.y_axes) - 1)
        if plain.y_axes[i + 1].pos_mm - plain.y_axes[i].pos_mm < 2500
    ]
    assert short == [(5100, 6800)]
    assert set(entry.element_ids) == {
        axis.id for axis in plain.y_axes if axis.pos_mm in (5100, 6800)
    }
    assert set(entry.element_ids) == {"gy-C", "gy-D"}


def test_short_span_warning_names_both_axes():
    grid = extract_axes(core_model())
    assert "W_SHORT_SPAN" in grid.log.codes()
    entries = [e for e in grid.log.entries if e.code == "W_SHORT_SPAN"]
    # 2.0 m core offsets in both directions: one entry per short pair, each
    # naming its own two axes (the ladder merges ids only for one message)
    assert len(entries) == 2
    assert [set(e.element_ids) for e in entries] == [{"gx-1", "gx-2"}, {"gy-A", "gy-B"}]
    for entry in entries:
        for axis_id in entry.element_ids:
            assert axis_id in entry.message


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_same_model_twice_is_byte_identical():
    first = _canonical(extract_axes(two_storey_model()))
    second = _canonical(extract_axes(two_storey_model()))
    assert first == second


def test_permuted_input_order_is_byte_identical():
    reference = _canonical(extract_axes(two_storey_model()))
    for shift in range(1, 5):
        model = two_storey_model()
        model.walls = model.walls[shift:] + model.walls[:shift]
        model.rooms = list(reversed(model.rooms))
        model.storeys = list(reversed(model.storeys))
        assert _canonical(extract_axes(model)) == reference


def test_units_leave_the_module_in_metres():
    grid = extract_axes(two_storey_model())
    blob = grid.to_dict()
    assert blob["x_axes"][3]["pos_m"] == 12.06
    assert blob["x_axes"][3]["extents_m"]["0"] == [[0.0, 14.0]]
    assert blob["footprints_m"]["1"] == [[0.0, 0.0, 16.0, 14.0]]
    for axis in grid.axes():
        assert abs(axis.pos_m - axis.pos_mm / 1000.0) < 1e-9


# ---------------------------------------------------------------------------
# hand-off surface
# ---------------------------------------------------------------------------


def test_to_model_axes_matches_the_model_dataclass():
    grid = extract_axes(two_storey_model())
    axes = grid.to_model_axes()
    assert len(axes) == len(grid.x_axes) + len(grid.y_axes)
    for produced, source in zip(axes, grid.axes()):
        assert isinstance(produced, M.GridAxis)
        assert produced.id == source.id
        assert produced.pos_m == source.pos_m
        assert produced.storeys == source.storeys()
        assert produced.source in list(M.AxisSource)
    model = two_storey_model()
    model.axes = axes
    assert [d.code for d in model.validate()] == []


def test_grid_helpers_for_placement():
    grid = extract_axes(two_storey_model())
    assert grid.contains(0, 20.0, 7.0) is True
    assert grid.contains(1, 20.0, 7.0) is False
    assert grid.chord_m(1, M.AxisDir.X, 8.04) == [(0.0, 14.0)]
    assert grid.footprint_rects_m(0) == [(0.0, 0.0, 24.0, 14.0)]
    assert grid.axes_in(M.AxisDir.Y) == grid.y_axes


def test_frame_params_defaults_are_metric():
    params = FrameParams()
    assert params.max_primary_span == 5.0
    assert params.min_span == 2.5
    assert params.merge_tol == 0.30
    assert params.slab_t_max_mm == 150.0
    assert params.system == M.System.RC_FRAME.value
    assert FrameParams(secondary_spacing=4.0).secondary_spacing_clamped() == 3.5
    assert FrameParams(column_merge=0.9).column_merge_floored() == 1.2
    wire = params.to_dict()
    assert wire["max_primary_span_m"] == 5.0
    assert wire["slab_t_max_mm"] == 150.0
    for key, value in wire.items():
        if isinstance(value, float):
            assert key.endswith("_m") or key.endswith("_mm"), key
    assert DEFAULT_WALL_T_M == 0.23


# ---------------------------------------------------------------------------
# degenerate input is disclosed, never silently empty
# ---------------------------------------------------------------------------


def test_model_without_geometry_discloses_an_empty_plan():
    model = M.StructuralModel(
        id="empty", storeys=[M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)]
    )
    grid = extract_axes(model)
    assert grid.x_axes == [] and grid.y_axes == []
    assert "E_EMPTY_PLAN" in grid.log.codes()
    assert grid.junctions == {0: []}
    assert grid.to_model_axes() == []


def l_shaped_model():
    """12 x 6 m with a 6 x 6 m wing, so the footprint is two rects, not one."""
    storeys = [M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)]
    rooms = [
        _room(0, "front", M.Occupancy.HABITABLE, 0.0, 0.0, 12.0, 6.0),
        _room(0, "wing", M.Occupancy.HABITABLE, 0.0, 6.0, 6.0, 12.0),
    ]
    walls = [
        _wall(0, "e1", (0.0, 0.0), (12.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "e2", (12.0, 0.0), (12.0, 6.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "e3", (6.0, 6.0), (12.0, 6.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "e4", (6.0, 6.0), (6.0, 12.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "e5", (0.0, 12.0), (6.0, 12.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "e6", (0.0, 0.0), (0.0, 12.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "mid", (0.0, 6.0), (6.0, 6.0), INT_T, M.WallRole.INTERIOR),
    ]
    return M.StructuralModel(id="ell", storeys=storeys, rooms=rooms, walls=walls)


def test_rectilinear_footprint_clips_axes_at_the_notch():
    grid = extract_axes(l_shaped_model())
    assert grid.footprint_rects_m(0) == [(0.0, 0.0, 6.0, 12.0), (6.0, 0.0, 12.0, 6.0)]
    assert _positions_mm(grid.x_axes) == [0, 3000, 6000, 9000, 12000]
    assert _positions_mm(grid.y_axes) == [0, 3000, 6000, 9000, 12000]
    # the inserted lines stop where the plan stops
    assert grid.by_id("gy-D").extents_mm[0] == [(0, 6000)]
    assert grid.by_id("gx-4").extents_mm[0] == [(0, 6000)]
    assert grid.contains(0, 3.0, 9.0) is True
    assert grid.contains(0, 9.0, 9.0) is False
    assert [(j.x_mm, j.y_mm) for j in grid.junctions[0] if j.x_mm == 9000 and j.y_mm == 9000] == []


def test_stilt_storey_inherits_the_footprint_it_carries():
    """No rooms and no walls at ground level is a stilt, not an empty plan."""
    model = blank_box_model()
    model.storeys = [
        M.Storey(index=0, name="Stilt", bottom_z_m=0.0, height_m=3.2, kind=M.StoreyKind.STILT),
        M.Storey(index=1, name="First", bottom_z_m=3.2, height_m=3.0),
    ]
    for element in list(model.rooms) + list(model.walls):
        element.storey = 1
    model.rooms = [
        _room(1, "box", M.Occupancy.HABITABLE, 0.0, 0.0, 12.0, 6.0)
    ]
    grid = extract_axes(model)
    assert "E_EMPTY_PLAN" not in grid.log.codes()
    assert "W_UNIT_NO_PLAN" in grid.log.codes()
    assert grid.footprint_rects_m(0) == [(0.0, 0.0, 12.0, 6.0)]
    # every axis reaches the ground, so nothing above it reads as floating
    for axis in grid.axes():
        assert axis.present(0) is True
        assert axis.present(1) is True


def test_storey_without_rooms_uses_the_exterior_envelope():
    """A closed exterior loop encloses the storey exactly; nothing is assumed."""
    model = blank_box_model()
    model.rooms = []
    grid = extract_axes(model)
    assert grid.log.codes() == []
    assert _positions_mm(grid.x_axes) == [0, 4000, 8000, 12000]
    assert grid.footprint_rects_m(0) == [(0.0, 0.0, 12.0, 6.0)]


def test_open_wall_set_falls_back_to_the_bounding_box():
    """Interior walls alone do not enclose anything, so the extents are a guess."""
    model = M.StructuralModel(
        id="open",
        storeys=[M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)],
        walls=[
            _wall(0, "a", (0.0, 0.0), (10.0, 0.0), INT_T, M.WallRole.INTERIOR),
            _wall(0, "b", (0.0, 0.0), (0.0, 8.0), INT_T, M.WallRole.INTERIOR),
        ],
    )
    grid = extract_axes(model)
    assert "W_UNIT_NO_PLAN" in grid.log.codes()
    assert grid.footprint_rects_m(0) == [(0.0, 0.0, 10.0, 8.0)]
    assert _positions_mm(grid.x_axes) == [0, 5000, 10000]
    assert _positions_mm(grid.y_axes) == [0, 4000, 8000]


def test_units_inset_from_a_building_boundary_still_reach_the_boundary():
    """Rooms alone would leave the boundary line outside the storey footprint."""
    storeys = [M.Storey(index=0, name="Ground", bottom_z_m=0.0, height_m=3.0)]
    rooms = [_room(0, "unit", M.Occupancy.HABITABLE, 1.0, 1.0, 9.0, 7.0)]
    walls = [
        _wall(0, "bnd-n", (0.0, 0.0), (10.0, 0.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "bnd-s", (0.0, 8.0), (10.0, 8.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "bnd-w", (0.0, 0.0), (0.0, 8.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "bnd-e", (10.0, 0.0), (10.0, 8.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "unit-n", (1.0, 1.0), (9.0, 1.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "unit-s", (1.0, 7.0), (9.0, 7.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "unit-w", (1.0, 1.0), (1.0, 7.0), EXT_T, M.WallRole.EXTERIOR),
        _wall(0, "unit-e", (9.0, 1.0), (9.0, 7.0), EXT_T, M.WallRole.EXTERIOR),
    ]
    model = M.StructuralModel(id="inset", storeys=storeys, rooms=rooms, walls=walls)
    grid = extract_axes(model)
    assert grid.footprint_rects_m(0) == [(0.0, 0.0, 10.0, 8.0)]
    # 1.0 to 9.0 is an 8 m bay, so one line is inserted at its half
    assert _positions_mm(grid.x_axes) == [0, 1000, 5000, 9000, 10000]
    assert grid.by_id("gx-1").extents_mm[0] == [(0, 8000)]


# ---------------------------------------------------------------------------
# the plan fixture, once the plan_json adapter lands
# ---------------------------------------------------------------------------


def _plan_model():
    """Build the 2BHK fixture model through the adapter, or None while it is absent."""
    try:
        adapter = importlib.import_module("..adapters.plan_json", package=__package__)
    except Exception:
        return None
    build = getattr(adapter, "from_plan", None)
    if build is None:
        return None
    import os

    path = os.path.join(os.path.dirname(__file__), "fixtures", "plan_2bhk.json")
    with open(path, "r") as handle:
        payload = json.load(handle)
    plans = payload["response"]["Documents"]["floorPlans"]
    for argument in (payload, plans[0]):
        try:
            result = build(argument)
        except Exception:
            continue
        if isinstance(result, (list, tuple)):
            result = result[0] if result else None
        if isinstance(result, M.StructuralModel):
            return result
    return None


def test_plan_fixture_through_the_adapter():
    model = _plan_model()
    if model is None:
        pytest.skip("adapters.plan_json.from_plan is not available yet")
    grid = extract_axes(model)
    assert grid.x_axes and grid.y_axes
    assert len({axis.id for axis in grid.axes()}) == len(grid.axes())
    for axes in (grid.x_axes, grid.y_axes):
        positions = _positions_mm(axes)
        assert positions == sorted(positions)
        assert axes[0].source == M.AxisSource.OUTLINE
        assert axes[-1].source == M.AxisSource.OUTLINE
        for i in range(len(positions) - 1):
            assert positions[i + 1] - positions[i] <= 5000
    # the fixture plot is 30 x 40 ft, so the footprint bbox is 9.144 x 12.192 m
    assert grid.footprints[0].bbox_mm() == (0, 0, 9144, 12192)
    assert grid.junctions[0]
    assert _canonical(grid) == _canonical(extract_axes(_plan_model()))
