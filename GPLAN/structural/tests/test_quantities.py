"""Pins for the one quantity owner: take-off, bar schedule, rates and the bill.

Critic finding 24 gives `quantities.py` the whole take-off, so these tests are
arithmetic tests before they are anything else. The golden vector is a
two-storey two-bay frame whose every cubic metre, square metre and kilogram is
worked by hand below; if a measurement convention moves, one of these numbers
moves with it and the test says which.

THE GOLDEN FRAME
================

Two storeys of 3.000 m. Three x lines at 0, 4 and 8 m, two y lines at 0 and 5 m,
so six column stacks, two bays in x and one in y. Columns 300 x 300, beams
230 x 450, slab 125 thick, pads 1.5 x 1.5 x 0.4 founded 1.5 m down. Everything
M25 / Fe500. Six columns, seven beams and one 8 x 5 slab panel per storey.

Columns, 12 of them (spec 1.2: clear height is the storey less the deepest beam
framing into the head)

    clear height        3.000 - 0.450                        = 2.550 m
    volume each         0.30 x 0.30 x 2.550                  = 0.2295 m3
    volume total        12 x 0.2295                          = 2.7540 m3
    formwork each       2 x (0.30 + 0.30) x 2.550            = 3.060 m2
    formwork total      12 x 3.060                           = 36.720 m2

Beams, 14 of them, clear span = centreline span less half a column at each end

    x beams (8)  clear 4.000 - 0.150 - 0.150                 = 3.700 m
                 volume 0.23 x 0.45 x 3.700                  = 0.38295 m3
                 total  8 x 0.38295                          = 3.06360 m3
                 formwork (2 x (0.450 - 0.125) + 0.230) x 3.700
                        = (0.650 + 0.230) x 3.700            = 3.256 m2
                 total  8 x 3.256                            = 26.048 m2
    y beams (6)  clear 5.000 - 0.300                         = 4.700 m
                 volume 0.23 x 0.45 x 4.700                  = 0.48645 m3
                 total  6 x 0.48645                          = 2.91870 m3
                 formwork 0.880 x 4.700                      = 4.136 m2
                 total  6 x 4.136                            = 24.816 m2
    beams        volume 3.06360 + 2.91870                    = 5.98230 m3
                 formwork 26.048 + 24.816                    = 50.864 m2

Slab, 2 panels of 8.000 x 5.000 = 40.000 m2 gross, 125 thick. The beam plan
footprints are cut out of the panel (spec 1.2, no double count with the full
depth beams); half a beam width, 0.115, lies inside the panel on every edge line
and the whole 0.230 on the interior x = 4 line.

    y = 0 line, two x beams   (3.700 + 3.700) x 0.115        = 0.8510 m2
    y = 5 line, two x beams                                  = 0.8510 m2
    x = 0 line, one y beam    4.700 x 0.115                  = 0.5405 m2
    x = 8 line, one y beam                                   = 0.5405 m2
    x = 4 line, one y beam    4.700 x 0.230                  = 1.0810 m2
    footprints                                               = 3.8640 m2
    net panel   40.000 - 3.864                               = 36.136 m2
    volume each 36.136 x 0.125                               = 4.5170 m3
    volume total 2 x 4.5170                                  = 9.0340 m3
    formwork (soffit only) 2 x 36.136                        = 72.272 m2

Footings, 6 pads

    volume each  1.5 x 1.5 x 0.4                             = 0.9000 m3
    volume total 6 x 0.9000                                  = 5.4000 m3
    formwork each (side shutters) 2 x (1.5 + 1.5) x 0.4      = 2.400 m2
    formwork total 6 x 2.400                                 = 14.400 m2

    concrete total 2.7540 + 5.9823 + 9.0340 + 5.4000         = 23.1703 m3
    formwork total 36.720 + 50.864 + 72.272 + 14.400         = 174.256 m2

Earthwork per pad, working space 0.300, founding depth 1.500 (which is NOT past
the 1.5 m slope threshold, so no slope allowance is taken)

    pit       2.1 x 2.1 x 1.500                              = 6.6150 m3
    PCC       1.7 x 1.7 x 0.100                              = 0.2890 m3
    pad                                                      = 0.9000 m3
    pedestal  0.09 x (1.500 - 0.100 - 0.400)                 = 0.0900 m3
    backfill  6.6150 - 0.9000 - 0.0900 - 0.2890             = 5.3360 m3
    disposal  6.6150 - 5.3360                                = 1.2790 m3
    x 6       excavation 39.690, PCC 1.734, backfill 32.016, disposal 7.674

Bars. Unit masses are d^2/162 from data/steel_mass.yaml: 8 -> 0.395,
10 -> 0.617, 12 -> 0.888, 16 -> 1.578 kg/m. Every bar below carries its own
ld_mm, so nothing here takes the flat 50d fallback.

    column longitudinal 4-16, ld 800, zone 0..3000, one lap per storey
        cut 3.000 + 0.800                                    = 3.800 m
        each 4 x 3.800 x 1.578                               = 23.9856 kg
        total 12 x 23.9856                                   = 287.8272 kg
    column ties 8 at 150 over 3000, cover 40 in a 300 x 300
        a = b = 300 - 2 x 40                                 = 220 mm
        cut 2 x (0.220 + 0.220) + 20 x 0.008                 = 1.040 m
        count floor(3000 / 150) + 1                          = 21
        each 21 x 1.040 x 0.395                              = 8.6268 kg
        total 12 x 8.6268                                    = 103.5216 kg
    beam bottom 3-16, ld 800, anchored both ends
        x beams cut 4.000 + 2 x 0.800                        = 5.600 m
                each 3 x 5.600 x 1.578                       = 26.5104 kg
                total 8 x 26.5104                            = 212.0832 kg
        y beams cut 5.000 + 1.600                            = 6.600 m
                each 3 x 6.600 x 1.578                       = 31.2444 kg
                total 6 x 31.2444                            = 187.4664 kg
    beam stirrups 8 at 150, cover 25 in a 230 x 450
        a = 180, b = 400; cut 2 x (0.180 + 0.400) + 0.160    = 1.320 m
        x beams count floor(4000 / 150) + 1                  = 27
                each 27 x 1.320 x 0.395                      = 14.0778 kg
                total 8 x 14.0778                            = 112.6224 kg
        y beams count floor(5000 / 150) + 1                  = 34
                each 34 x 1.320 x 0.395                      = 17.7276 kg
                total 6 x 17.7276                            = 106.3656 kg
    slab main mesh 40 no 10 at 200, ld 500, zone 0..5000
        cut 5.000 + 1.000                                    = 6.000 m
        each 40 x 6.000 x 0.617                              = 148.08 kg
        total 2 x 148.08                                     = 296.16 kg
    slab distribution 25 no 8 at 200, ld 400, zone 0..8000
        cut 8.000 + 0.800                                    = 8.800 m
        each 25 x 8.800 x 0.395                              = 86.90 kg
        total 2 x 86.90                                      = 173.80 kg
    footing mesh 10 no 12 at 150 each way, ld 600, zone 0..1500. The zone is
    already the pad cover to cover and the footing designer resolved that
    anchorage inside the pad, so NO development length is added at either end
    (finding B28: the old two-ended rule cut a 2.796 m bar for a 1.500 m pad).
    A footing bar is shape L, so one 90 degree bend adds 8d = 96 mm.
        cut 1.500 + 0.096                                    = 1.596 m
        each way 10 x 1.596 x 0.888                          = 14.17248 kg
        total 12 x 14.17248                                  = 170.06976 kg

    columns 287.8272 + 103.5216                              = 391.3488 kg
    beams   212.0832 + 187.4664 + 112.6224 + 106.3656        = 618.5376 kg
    slabs   296.16 + 173.80                                  = 469.96 kg
    footings                                                 = 170.06976 kg
    schedule total                                           = 1649.91616 kg
    with 3 percent wastage                                   = 1699.4136448 kg

Built-up area is the gross plate, 2 x 40.000 = 80.000 m2, so the two density
metrics are 1699.4136448 / 80 = 21.243 kg/m2 and 23.1703 / 80 = 0.28963 m3/m2.
Both are outside the spec's calibration bands (2.5 to 7 kg/m2 and 0.10 to
0.20 m3/m2), which is itself pinned below: the bands are a heuristic stated per
square metre of built-up area, and a two-storey building on an 80 m2 plate
carries its foundations over a small area, so it trips them.
"""

from __future__ import annotations

import json
import math

import pytest

# Relative: the engine repo root carries its own __init__.py, so pytest imports
# this package as GPLAN.GPLAN.structural.tests.
from .. import quantities as Q
from ..data._loader import load_yaml
from ..design.common import DesignResult
from ..model import (
    REGISTRY,
    Band,
    BandKind,
    Beam,
    BeamKind,
    Column,
    Core,
    CoreKind,
    Footing,
    FootingKind,
    Lintel,
    Material,
    Opening,
    OpeningKind,
    Provenance,
    RoomPoly,
    Occupancy,
    SlabKind,
    SlabPanel,
    Storey,
    StructuralModel,
    System,
    WallLine,
    WallRole,
)

X_LINES = (0.0, 4.0, 8.0)
Y_LINES = (0.0, 5.0)

#: The sentence a blocked element's rows carry, shared by concrete and steel.
_BLOCKED_NOTE = Q._BLOCKED_BASIS


# ---------------------------------------------------------------------------
# the golden frame
# ---------------------------------------------------------------------------


def _column_design(element_id):
    result = DesignResult(element_id=element_id, element_type="column")
    result.section = {"b_mm": 300.0, "D_mm": 300.0, "cover_mm": 40.0, "length_mm": 3000.0}
    result.materials = {"concrete_grade": "M25", "steel_grade": "Fe500"}
    result.add_bar("long", 4, 16.0, 800.0, [0.0, 3000.0])
    result.add_stirrup([0.0, 3000.0], 2, 8.0, 150.0, kind="tie")
    return result


def _beam_design(element_id, span_mm):
    result = DesignResult(element_id=element_id, element_type="beam")
    result.section = {
        "b_mm": 230.0,
        "D_mm": 450.0,
        "cover_mm": 25.0,
        "length_mm": span_mm,
        "clear_span_mm": span_mm - 300.0,
    }
    result.materials = {"concrete_grade": "M25", "steel_grade": "Fe500"}
    result.add_bar("bottom_mid", 3, 16.0, 800.0, [0.0, span_mm])
    result.add_stirrup([0.0, span_mm], 2, 8.0, 150.0, kind="shear")
    return result


def _slab_design(element_id):
    result = DesignResult(element_id=element_id, element_type="slab")
    result.section = {"b_mm": 1000.0, "D_mm": 125.0, "thickness_mm": 125.0, "cover_mm": 20.0}
    result.materials = {"concrete_grade": "M25", "steel_grade": "Fe500"}
    result.add_bar("mesh_main", 40, 10.0, 500.0, [0.0, 5000.0], spacing_mm=200.0)
    result.add_bar("mesh_distribution", 25, 8.0, 400.0, [0.0, 8000.0], spacing_mm=200.0)
    return result


def _footing_design(element_id):
    result = DesignResult(element_id=element_id, element_type="footing")
    result.section = {"bx_mm": 1500.0, "ly_mm": 1500.0, "D_mm": 400.0, "cover_mm": 50.0}
    result.materials = {"concrete_grade": "M25", "steel_grade": "Fe500"}
    result.add_bar("mesh_x", 10, 12.0, 600.0, [0.0, 1500.0], spacing_mm=150.0)
    result.add_bar("mesh_y", 10, 12.0, 600.0, [0.0, 1500.0], spacing_mm=150.0)
    return result


def golden_frame():
    """The two-storey two-bay frame the module docstring works out by hand."""
    model = StructuralModel(id="golden-frame")
    designs = []
    for index in (0, 1):
        model.storeys.append(Storey(index=index, name="L" + str(index), bottom_z_m=3.0 * index, height_m=3.0))

    for storey in (0, 1):
        for xi, x in enumerate(X_LINES):
            for yi, y in enumerate(Y_LINES):
                element_id = "col-%d-%d-s%d" % (xi, yi, storey)
                model.columns.append(
                    Column(
                        id=element_id,
                        stack_id="stk-%d-%d" % (xi, yi),
                        storey=storey,
                        x_m=x,
                        y_m=y,
                        width_m=0.30,
                        depth_m=0.30,
                    )
                )
                designs.append(_column_design(element_id))
        for yi, y in enumerate(Y_LINES):
            for bay in range(len(X_LINES) - 1):
                element_id = "beam-x%d-%d-s%d" % (yi, bay, storey)
                model.beams.append(
                    Beam(
                        id=element_id,
                        storey=storey,
                        a=(X_LINES[bay], y),
                        b=(X_LINES[bay + 1], y),
                        width_m=0.23,
                        depth_m=0.45,
                        kind=BeamKind.PRIMARY,
                    )
                )
                designs.append(_beam_design(element_id, 4000.0))
        for xi, x in enumerate(X_LINES):
            element_id = "beam-y%d-s%d" % (xi, storey)
            model.beams.append(
                Beam(
                    id=element_id,
                    storey=storey,
                    a=(x, Y_LINES[0]),
                    b=(x, Y_LINES[1]),
                    width_m=0.23,
                    depth_m=0.45,
                    kind=BeamKind.PRIMARY,
                )
            )
            designs.append(_beam_design(element_id, 5000.0))
        element_id = "slab-s%d" % storey
        model.slabs.append(
            SlabPanel(
                id=element_id,
                storey=storey,
                polygon=[(0.0, 0.0), (8.0, 0.0), (8.0, 5.0), (0.0, 5.0)],
                thickness_m=0.125,
                kind=SlabKind.ROOF if storey == 1 else SlabKind.FLOOR,
            )
        )
        designs.append(_slab_design(element_id))

    for xi, x in enumerate(X_LINES):
        for yi, y in enumerate(Y_LINES):
            element_id = "ftg-%d-%d" % (xi, yi)
            model.footings.append(
                Footing(
                    id=element_id,
                    kind=FootingKind.ISOLATED,
                    supports=["col-%d-%d-s0" % (xi, yi)],
                    x_m=x,
                    y_m=y,
                    w_m=1.5,
                    h_m=1.5,
                    depth_m=1.5,
                )
            )
            designs.append(_footing_design(element_id))
    return model, designs


def _volume(takeoff, element_class):
    """The single concrete row for a class; classes never split grade here."""
    rows = [row for row in takeoff.concrete if row.element_class == element_class]
    assert len(rows) == 1, element_class + " should have exactly one row, got " + str(len(rows))
    return rows[0].volume_m3


def _formwork(takeoff, element_class):
    rows = [row for row in takeoff.formwork if row.element_class == element_class]
    assert len(rows) == 1
    return rows[0].area_m2


def _codes(log):
    return [entry.code for entry in log.sorted_entries()]


# ---------------------------------------------------------------------------
# golden vector: concrete
# ---------------------------------------------------------------------------


def test_golden_frame_concrete_volumes_are_the_hand_computed_ones():
    """Column 2.7540, beam 5.98230, slab 9.0340, footing 5.4000, total 23.1703 m3."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)

    assert _volume(takeoff, "column") == pytest.approx(2.7540)
    assert _volume(takeoff, "beam") == pytest.approx(5.98230)
    assert _volume(takeoff, "slab") == pytest.approx(9.0340)
    assert _volume(takeoff, "footing") == pytest.approx(5.4000)
    assert takeoff.concrete_m3 == pytest.approx(23.1703)


def test_golden_frame_column_is_measured_over_the_clear_height():
    """0.30 x 0.30 x (3.000 - 0.450) = 0.2295 m3, and the convention is disclosed."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    rows = [row for row in takeoff.concrete_by_element if row.element_class == "column"]
    assert len(rows) == 12
    for row in rows:
        assert row.volume_m3 == pytest.approx(0.2295)
    assert "N_COLUMN_HEIGHT_CONVENTION" in _codes(takeoff.disclosures)


def _mixed_depth_line():
    """One storey, three columns in a line under a 600 beam and a 300 beam.

    Finding B29: the clear height belongs to the column, so the column under the
    300 deep beam is 2.700 m, not the 2.400 m a storey-wide maximum gives it.
    The fourth column stands off the line with no beam over it at all.
    """
    model = StructuralModel(id="mixed-depth")
    model.storeys.append(Storey(index=0, name="G", bottom_z_m=0.0, height_m=3.0))
    for name, x, y in (("deep", 0.0, 0.0), ("both", 4.0, 0.0), ("shallow", 8.0, 0.0), ("lonely", 0.0, 5.0)):
        model.columns.append(
            Column(id="col-" + name, stack_id="stk-" + name, storey=0, x_m=x, y_m=y, width_m=0.30, depth_m=0.30)
        )
    model.beams.append(
        Beam(id="beam-deep", storey=0, a=(0.0, 0.0), b=(4.0, 0.0), width_m=0.23, depth_m=0.60)
    )
    model.beams.append(
        Beam(id="beam-shallow", storey=0, a=(4.0, 0.0), b=(8.0, 0.0), width_m=0.23, depth_m=0.30)
    )
    return model


def test_a_column_stops_under_the_beam_that_reaches_it_not_the_storeys_deepest():
    """The head beam is this column's own: 3.000 - 0.300 for the shallow end."""
    takeoff = Q.take_off(_mixed_depth_line(), [])
    rows = {row.element_id: row for row in takeoff.concrete_by_element if row.element_class == "column"}
    assert rows["col-deep"].volume_m3 == pytest.approx(0.09 * (3.0 - 0.60))
    assert rows["col-both"].volume_m3 == pytest.approx(0.09 * (3.0 - 0.60))
    # 0.09 x 2.700 = 0.243; the storey-wide maximum measured this column at 0.216
    assert rows["col-shallow"].volume_m3 == pytest.approx(0.09 * (3.0 - 0.30))
    assert _volume(takeoff, "column") == pytest.approx(0.09 * (2.40 + 2.40 + 2.70 + 2.40))
    assert _formwork(takeoff, "column") == pytest.approx(1.2 * (2.40 + 2.40 + 2.70 + 2.40))
    for name in ("col-deep", "col-both", "col-shallow"):
        assert "no beam frames into this column" not in rows[name].basis


def test_a_column_no_beam_reaches_falls_back_to_the_storey_and_says_so():
    """The fallback is allowed, silence about it is not."""
    takeoff = Q.take_off(_mixed_depth_line(), [])
    rows = {row.element_id: row for row in takeoff.concrete_by_element if row.element_class == "column"}
    lonely = rows["col-lonely"]
    assert lonely.volume_m3 == pytest.approx(0.09 * (3.0 - 0.60))
    assert "no beam frames into this column's head" in lonely.basis
    assert "deepest beam on the storey, 600 mm, was deducted instead" in lonely.basis
    message = [
        row for row in takeoff.disclosures.entries if row.code == "N_COLUMN_HEIGHT_CONVENTION"
    ][0].message
    assert "THAT column's head" in message


def test_golden_frame_beam_clear_span_deducts_the_columns_at_both_ends():
    """4.000 m centre to centre becomes 3.700 m clear, 5.000 m becomes 4.700 m."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    rows = {row.element_id: row.volume_m3 for row in takeoff.concrete_by_element if row.element_class == "beam"}
    assert rows["beam-x0-0-s0"] == pytest.approx(0.23 * 0.45 * 3.700)
    assert rows["beam-y1-s1"] == pytest.approx(0.23 * 0.45 * 4.700)


def test_beam_clear_span_falls_back_to_the_column_faces_without_a_design():
    """With no designed clear_span_mm the geometry is used: 4.000 - 2 x 0.150."""
    model, _ = golden_frame()
    takeoff = Q.take_off(model, [])
    rows = {row.element_id: row.volume_m3 for row in takeoff.concrete_by_element if row.element_class == "beam"}
    assert rows["beam-x0-0-s0"] == pytest.approx(0.23 * 0.45 * 3.700)


def test_golden_frame_slab_deducts_the_beam_footprints_once():
    """40.000 gross less 3.8640 of beam footprint leaves 36.136 m2 of panel."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    rows = [row for row in takeoff.concrete_by_element if row.element_class == "slab"]
    assert len(rows) == 2
    for row in rows:
        assert row.volume_m3 == pytest.approx(36.136 * 0.125)
    assert "beam footprints 3.864 m2" in rows[0].basis


def test_concrete_rows_carry_both_the_rounded_and_the_exact_volume():
    """Spec 1.2: rows round to 0.01 m3, totals sum before rounding, both ship."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    row = [item for item in takeoff.concrete if item.element_class == "beam"][0].to_dict()
    assert row["volume_m3"] == pytest.approx(5.98)
    assert row["volume_exact_m3"] == pytest.approx(5.9823)
    assert takeoff.to_dict()["totals"]["concrete_m3"] == pytest.approx(23.17)


def test_a_class_the_model_does_not_carry_ships_as_a_zero_row():
    """Never raise on a missing class: emit the class with zero and say why."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    present = {row.element_class for row in takeoff.concrete}
    assert present == set(Q.CONCRETE_CLASSES)
    for name in ("stair", "band", "lintel", "plinth_beam"):
        row = [item for item in takeoff.concrete if item.element_class == name][0]
        assert row.volume_m3 == 0.0
        assert "no elements of this class" in row.basis


def test_a_blocked_element_takes_no_quantity_and_says_so():
    """An ERROR upstream zeroes the element's rows; the ladder rule, not a guess."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs, {"blocked_element_ids": ["col-0-0-s0"]})
    rows = {row.element_id: row for row in takeoff.concrete_by_element}
    assert rows["col-0-0-s0"].volume_m3 == 0.0
    assert "blocked this element" in rows["col-0-0-s0"].basis
    assert _volume(takeoff, "column") == pytest.approx(11 * 0.2295)


def test_a_blocked_element_loses_its_steel_too():
    """Concrete and steel have to agree: a blocked element weighs nothing in both."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs, {"blocked_element_ids": ["col-0-0-s0"]})
    rows = [item for item in takeoff.bbs.items if item.element_id == "col-0-0-s0"]
    assert rows and all(item.total_mass_kg == 0.0 for item in rows)
    assert all(_BLOCKED_NOTE in item.notes for item in rows)
    assert takeoff.bbs.mass_by_class["column"] == pytest.approx(11 * (23.9856 + 8.6268))


def test_a_blocked_footing_digs_no_pit():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs, {"blocked_element_ids": ["ftg-0-0"]})
    assert len(takeoff.earthwork.footings) == 5
    assert takeoff.earthwork.excavation_m3 == pytest.approx(5 * 6.6150)


# ---------------------------------------------------------------------------
# golden vector: formwork
# ---------------------------------------------------------------------------


def test_golden_frame_formwork_areas_are_the_hand_computed_ones():
    """Column 36.720, beam 50.864, slab 72.272, footing 14.400, total 174.256 m2."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)

    assert _formwork(takeoff, "column") == pytest.approx(36.720)
    assert _formwork(takeoff, "beam") == pytest.approx(50.864)
    assert _formwork(takeoff, "slab") == pytest.approx(72.272)
    assert _formwork(takeoff, "footing") == pytest.approx(14.400)
    assert takeoff.formwork_m2 == pytest.approx(174.256)


def test_beam_side_shutter_stops_under_the_slab():
    """One x beam: (2 x (0.450 - 0.125) + 0.230) x 3.700 = 3.256 m2."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    assert _formwork(takeoff, "beam") / 14 != pytest.approx(3.256)  # the two spans differ
    assert _formwork(takeoff, "beam") == pytest.approx(8 * 3.256 + 6 * 4.136)


def test_slab_formwork_is_the_soffit_only_and_the_edges_are_disclosed():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    assert _formwork(takeoff, "slab") == pytest.approx(2 * 36.136)
    assert "N_FORMWORK_EDGES_IGNORED" in _codes(takeoff.disclosures)


# ---------------------------------------------------------------------------
# golden vector: earthwork
# ---------------------------------------------------------------------------


def test_golden_frame_earthwork_is_the_hand_computed_pit():
    """Per pad 6.6150 pit, 0.2890 PCC, 5.3360 backfill, 1.2790 disposal."""
    model, designs = golden_frame()
    earth = Q.take_off(model, designs).earthwork

    assert len(earth.footings) == 6
    pit = earth.footings[0]
    assert pit.excavation_m3 == pytest.approx(6.6150)
    assert pit.pcc_m3 == pytest.approx(0.2890)
    assert pit.footing_m3 == pytest.approx(0.9000)
    assert pit.pedestal_m3 == pytest.approx(0.0900)
    assert pit.backfill_m3 == pytest.approx(5.3360)
    assert pit.disposal_m3 == pytest.approx(1.2790)
    assert pit.slope_factor == pytest.approx(1.0)

    assert earth.excavation_m3 == pytest.approx(39.690)
    assert earth.pcc_m3 == pytest.approx(1.734)
    assert earth.backfill_m3 == pytest.approx(32.016)
    assert earth.disposal_m3 == pytest.approx(7.674)


def test_a_pit_past_the_threshold_takes_the_flat_slope_allowance():
    """1.8 m is past 1.5 m, so excavation carries the flat 1.1 and the NOTE."""
    model, designs = golden_frame()
    for footing in model.footings:
        footing.depth_m = 1.8
    takeoff = Q.take_off(model, designs)
    pit = takeoff.earthwork.footings[0]
    assert pit.slope_factor == pytest.approx(1.1)
    assert pit.excavation_m3 == pytest.approx(2.1 * 2.1 * 1.8 * 1.1)
    assert "N_SLOPE_ALLOWANCE_FLAT" in _codes(takeoff.disclosures)


def test_a_footing_with_no_founding_depth_takes_the_default_and_warns():
    """Spec 1.6: 1.5 m default, W_ASSUMED_FOUNDING_DEPTH, never a silent depth."""
    model, designs = golden_frame()
    for footing in model.footings:
        footing.depth_m = None
    takeoff = Q.take_off(model, designs)
    pit = takeoff.earthwork.footings[0]
    assert pit.depth_assumed is True
    assert pit.depth_m == pytest.approx(1.5)
    assert "W_ASSUMED_FOUNDING_DEPTH" in _codes(takeoff.disclosures)


def test_a_founded_footing_does_not_raise_the_assumed_depth_warning():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    assert "W_ASSUMED_FOUNDING_DEPTH" not in _codes(takeoff.disclosures)
    assert "N_SLOPE_ALLOWANCE_FLAT" not in _codes(takeoff.disclosures)


# ---------------------------------------------------------------------------
# IS 1200 deduction edge cases
# ---------------------------------------------------------------------------


def _bare_slab_model(core_w, core_h):
    """One 6 x 4 panel, no beams, and one core punched through it."""
    model = StructuralModel(id="panel")
    model.storeys.append(Storey(index=0, name="G", bottom_z_m=0.0, height_m=3.0))
    model.slabs.append(
        SlabPanel(
            id="slab-s0",
            storey=0,
            polygon=[(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)],
            thickness_m=0.125,
            kind=SlabKind.ROOF,
        )
    )
    model.cores.append(
        Core(id="core-1", kind=CoreKind.UTILITY_SHAFT, x_m=2.0, y_m=2.0, w_m=core_w, h_m=core_h, storeys=[0])
    )
    return model


def test_a_slab_opening_of_exactly_a_tenth_of_a_square_metre_is_not_deducted():
    """IS 1200 Part 5 Cl 4.4 reads "exceeding", so 0.100 m2 exactly stays in."""
    takeoff = Q.take_off(_bare_slab_model(0.25, 0.40), [])
    assert _volume(takeoff, "slab") == pytest.approx(24.0 * 0.125)
    assert "openings deducted 0 m2" in takeoff.concrete_by_element[0].basis


def test_a_slab_opening_just_over_the_limit_is_deducted():
    """0.25 x 0.44 = 0.110 m2 exceeds the limit, so the panel loses it."""
    takeoff = Q.take_off(_bare_slab_model(0.25, 0.44), [])
    assert _volume(takeoff, "slab") == pytest.approx((24.0 - 0.11) * 0.125)


def _masonry_model():
    """One 6 m bearing wall with a door and a vent, one 3 m partition, one band."""
    model = StructuralModel(id="masonry")
    model.storeys.append(Storey(index=0, name="G", bottom_z_m=0.0, height_m=3.0))
    model.slabs.append(
        SlabPanel(
            id="slab-s0",
            storey=0,
            polygon=[(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)],
            thickness_m=0.12,
            kind=SlabKind.ROOF,
        )
    )
    wall = WallLine(
        id="wall-a",
        storey=0,
        a=(0.0, 0.0),
        b=(6.0, 0.0),
        thickness_m=0.23,
        role=WallRole.EXTERIOR,
        material=Material.BRICK_MASONRY,
        bearing=True,
    )
    wall.openings.append(
        Opening(
            id="wall-a/o0",
            kind=OpeningKind.DOOR,
            offset_m=1.0,
            width_m=0.9,
            sill_m=0.0,
            head_m=2.1,
            provenance=Provenance.DRESSED,
        )
    )
    wall.openings.append(
        Opening(
            id="wall-a/o1",
            kind=OpeningKind.WINDOW,
            offset_m=4.0,
            width_m=0.25,
            sill_m=1.5,
            head_m=1.9,
            provenance=Provenance.DRESSED,
        )
    )
    model.walls.append(wall)
    model.walls.append(
        WallLine(
            id="wall-b",
            storey=0,
            a=(0.0, 2.0),
            b=(3.0, 2.0),
            thickness_m=0.115,
            role=WallRole.INTERIOR,
            material=Material.BRICK_MASONRY,
            bearing=False,
        )
    )
    model.bands.append(Band(id="band-lintel-s0", kind=BandKind.LINTEL, storey=0, wall_ids=["wall-a"], level_m=2.1))
    model.lintels.append(Lintel(id="wall-a/lin0", wall_id="wall-a", opening_id="wall-a/o0", span_m=0.9 + 2 * 0.15))
    model.meta["masonry_placement"] = {
        "lintel_schedule": [
            {
                "id": "wall-a/lin0",
                "wall_id": "wall-a",
                "storey": 0,
                "clear_span_m": 0.9,
                "bearing_mm": 150.0,
                "depth_mm": 150.0,
            }
        ]
    }
    return model


def test_masonry_opening_of_exactly_a_tenth_of_a_square_metre_is_not_deducted():
    """The 0.25 x 0.40 vent is exactly 0.1 m2 and stays; the 0.9 x 2.1 door goes.

    Bearing wall: 6.000 long, 0.230 thick, clear height 3.000 - 0.120 slab
    - 0.075 band = 2.805, so gross 6 x 0.23 x 2.805 = 3.8709 m3. The door
    deducts 0.9 x 2.1 x 0.23 = 0.4347 m3 and the lintel over it deducts its own
    1.2 x 0.23 x 0.15 = 0.0414 m3 (finding N36), so 0.4761 off, 3.3948 left.
    """
    takeoff = Q.take_off(_masonry_model(), [])
    bearing = [row for row in takeoff.masonry if row.bearing][0]
    assert bearing.thickness_mm == 230
    assert bearing.gross_m3 == pytest.approx(3.8709)
    assert bearing.deductions_m3 == pytest.approx(0.4347 + 0.0414)
    assert bearing.volume_m3 == pytest.approx(3.3948)


def test_a_band_crossing_a_wall_shortens_the_wall_and_carries_its_own_volume():
    """The band takes 0.075 off the wall's clear height and adds 0.1035 m3 of RC."""
    takeoff = Q.take_off(_masonry_model(), [])
    partition = [row for row in takeoff.masonry if not row.bearing][0]
    # wall-b carries no band, so it keeps the full 3.000 - 0.120 = 2.880
    assert partition.volume_m3 == pytest.approx(3.0 * 0.115 * 2.880)
    assert _volume(takeoff, "band") == pytest.approx(6.0 * 0.23 * 0.075)
    assert _formwork(takeoff, "band") == pytest.approx((2 * 0.075 + 0.23) * 6.0)


def test_masonry_is_keyed_by_thickness_class_and_bearing_split():
    takeoff = Q.take_off(_masonry_model(), [])
    keys = [(row.thickness_mm, row.bearing) for row in takeoff.masonry]
    assert keys == [(115, False), (230, True)]
    assert "N_PARTITION_M3_CONVENTION" in _codes(takeoff.disclosures)


def test_assumed_doors_reach_the_masonry_deduction_as_a_warning():
    """Housing plans carry synthesized doors; a deduction off one says so."""
    model = _masonry_model()
    model.walls[0].openings[0].provenance = Provenance.ASSUMED_MID_WALL
    takeoff = Q.take_off(model, [])
    assert "W_DOOR_ASSUMED" in _codes(takeoff.disclosures)


def test_a_lintel_is_measured_over_its_bearings():
    """0.9 clear + 2 x 0.150 bearing = 1.200 run, x 0.230 wall x 0.150 deep."""
    takeoff = Q.take_off(_masonry_model(), [])
    assert _volume(takeoff, "lintel") == pytest.approx(1.2 * 0.23 * 0.15)
    assert _formwork(takeoff, "lintel") == pytest.approx((2 * 0.15 + 0.23) * 1.2)


def test_a_lintel_inside_the_panel_is_given_back_to_the_walling():
    """Finding N36: the opening deduction is head to sill, so the lintel is inside it.

    Before this, the same 0.0414 m3 was billed once as lintel concrete and once
    as brickwork. The two rows now agree to the cubic millimetre.
    """
    model = _masonry_model()
    takeoff = Q.take_off(model, [])
    lintel_m3 = _volume(takeoff, "lintel")
    bearing = [row for row in takeoff.masonry if row.bearing][0]

    model.lintels = []
    model.meta["masonry_placement"] = {"lintel_schedule": []}
    without = [row for row in Q.take_off(model, []).masonry if row.bearing][0]

    assert lintel_m3 == pytest.approx(1.2 * 0.23 * 0.15)
    assert without.volume_m3 - bearing.volume_m3 == pytest.approx(lintel_m3)
    assert "a lintel inside the panel is deducted in full" in bearing.basis


def _masonry_model_under_a_beam(depth_m=0.45):
    """The same house with an RC beam spanning over the 6 m bearing wall."""
    model = _masonry_model()
    model.beams.append(
        Beam(
            id="beam-over-a",
            storey=0,
            a=(0.0, 0.0),
            b=(6.0, 0.0),
            width_m=0.23,
            depth_m=depth_m,
            kind=BeamKind.PRIMARY,
        )
    )
    return model


def test_a_wall_stops_under_the_beam_over_it_not_under_the_slab():
    """Finding N36: 3.000 - 0.450 beam - 0.075 band, not 3.000 - 0.120 slab.

    The 0.330 m of wall the old rule measured through the beam is beam concrete
    that the concrete row already carries.
    """
    takeoff = Q.take_off(_masonry_model_under_a_beam(), [])
    bearing = [row for row in takeoff.masonry if row.bearing][0]
    assert bearing.gross_m3 == pytest.approx(6.0 * 0.23 * (3.0 - 0.45 - 0.075))
    assert "the beam that spans over the wall" in bearing.basis

    # wall-b runs at y = 2.0 and no beam is over it, so it keeps the slab rule
    partition = [row for row in takeoff.masonry if not row.bearing][0]
    assert partition.volume_m3 == pytest.approx(3.0 * 0.115 * (3.0 - 0.12))


def test_a_beam_shallower_than_the_slab_never_lengthens_the_wall():
    """The plate is over the wall either way, so the deduction never goes down."""
    takeoff = Q.take_off(_masonry_model_under_a_beam(0.10), [])
    bearing = [row for row in takeoff.masonry if row.bearing][0]
    assert bearing.gross_m3 == pytest.approx(6.0 * 0.23 * (3.0 - 0.12 - 0.075))


def test_a_beam_on_another_line_is_not_a_beam_over_this_wall():
    """The collinearity test is what keeps the next grid line out of the answer."""
    model = _masonry_model()
    model.beams.append(
        Beam(id="beam-elsewhere", storey=0, a=(0.0, 4.0), b=(6.0, 4.0), width_m=0.23, depth_m=0.6)
    )
    takeoff = Q.take_off(model, [])
    bearing = [row for row in takeoff.masonry if row.bearing][0]
    assert bearing.gross_m3 == pytest.approx(6.0 * 0.23 * (3.0 - 0.12 - 0.075))


# ---------------------------------------------------------------------------
# stairs
# ---------------------------------------------------------------------------


def _stair_design():
    result = DesignResult(element_id="stair-c1-f0", element_type="slab")
    result.section = {
        "b_mm": 1000.0,
        "D_mm": 150.0,
        "waist_mm": 150.0,
        "span_mm": 2400.0,
        "width_mm": 1000.0,
        "rise_mm": 1500.0,
        "incline_deg": 32.0,
        "risers": 8,
        "riser_mm": 187.5,
        "going_mm": 300.0,
        "cover_mm": 20.0,
    }
    result.materials = {"concrete_grade": "M20", "steel_grade": "Fe500"}
    return result


def test_a_stair_flight_is_the_inclined_waist_plus_the_step_triangles():
    """2.400 / cos(32 deg) x 1.000 x 0.150 + 0.5 x 0.300 x 0.1875 x 1.000 x 8."""
    model = _masonry_model()
    model.meta["frame_placement"] = {
        "stair_slabs": [
            {
                "id": "stair-c1-f0",
                "core_id": "core-1",
                "storey": 0,
                "flight": 0,
                "span_m": 2.4,
                "width_m": 1.0,
                "rise_m": 1.5,
                "incline_deg": 32.0,
            }
        ]
    }
    takeoff = Q.take_off(model, [_stair_design()])
    inclined = 2.4 / math.cos(math.radians(32.0)) * 1.0
    expected = inclined * 0.150 + 0.5 * 0.300 * 0.1875 * 1.0 * 8
    assert _volume(takeoff, "stair") == pytest.approx(expected)
    assert _formwork(takeoff, "stair") == pytest.approx(inclined)
    row = [item for item in takeoff.concrete if item.element_class == "stair"][0]
    assert row.grade == "M20"


def test_a_flight_with_no_designed_waist_is_measured_as_zero_and_says_so():
    model = _masonry_model()
    model.meta["frame_placement"] = {
        "stair_slabs": [{"id": "stair-x", "storey": 0, "span_m": 2.4, "width_m": 1.0, "rise_m": 1.5,
                         "incline_deg": 32.0}]
    }
    takeoff = Q.take_off(model, [])
    row = [item for item in takeoff.concrete_by_element if item.element_class == "stair"][0]
    assert row.volume_m3 == 0.0
    assert "no designed waist thickness" in row.basis


# ---------------------------------------------------------------------------
# bar bending schedule
# ---------------------------------------------------------------------------


def test_the_unit_mass_table_is_the_d_squared_over_162_one():
    """Pinned values, and agreement with d^2/162 to better than 0.2 percent."""
    assert Q.UNIT_MASS_KG_M == {8: 0.395, 10: 0.617, 12: 0.888, 16: 1.578, 20: 2.469, 25: 3.854, 32: 6.313}
    for dia, quoted in sorted(Q.UNIT_MASS_KG_M.items()):
        exact = dia * dia / 162.0
        assert abs(quoted - exact) / exact < 0.002, dia
    assert Q.STOCK_LENGTH_M == pytest.approx(12.0)


def test_the_bar_catalogue_is_read_not_duplicated():
    """Finding 25: rebar.yaml belongs to the design layer, this module reads it."""
    rebar = load_yaml("rebar")
    assert Q.STIRRUP_HOOK_DIA == pytest.approx(float(rebar["bend_allowances"]["stirrup_two_hook_dia"]))
    assert Q.BEND_90_DIA == pytest.approx(float(rebar["bend_allowances"]["hook_90_deg_dia"]))


def test_golden_frame_bar_masses_are_the_hand_computed_ones():
    """391.3488 columns, 618.5376 beams, 469.96 slabs, 170.06976 footings."""
    model, designs = golden_frame()
    bbs = Q.build_bbs(designs)

    assert bbs.mass_by_class["column"] == pytest.approx(391.3488)
    assert bbs.mass_by_class["beam"] == pytest.approx(618.5376)
    assert bbs.mass_by_class["slab"] == pytest.approx(469.96)
    assert bbs.mass_by_class["footing"] == pytest.approx(170.06976)
    assert bbs.total_kg == pytest.approx(1649.91616)
    assert sum(bbs.mass_by_dia.values()) == pytest.approx(bbs.total_kg)


def test_a_column_longitudinal_bar_takes_one_lap_per_storey():
    """3.000 zone + one 0.800 lap = 3.800 m, 4 bars x 1.578 = 23.9856 kg."""
    bbs = Q.build_bbs([_column_design("col-0-0-s0")])
    longitudinal = [item for item in bbs.items if item.shape_code == Q.SHAPE_STRAIGHT][0]
    assert longitudinal.cut_length_m == pytest.approx(3.800)
    assert longitudinal.total_mass_kg == pytest.approx(23.9856)
    assert "one lap per storey" in longitudinal.notes[0]


def test_a_closed_link_is_two_a_plus_b_plus_a_flat_twenty_d():
    """230 x 450 at 25 cover: 2 x (0.180 + 0.400) + 20 x 0.008 = 1.320 m, 27 off."""
    bbs = Q.build_bbs([_beam_design("beam-x0-0-s0", 4000.0)])
    link = [item for item in bbs.items if item.shape_code == Q.SHAPE_STIRRUP][0]
    assert link.cut_length_m == pytest.approx(1.320)
    assert link.count == 27
    assert link.total_mass_kg == pytest.approx(27 * 1.320 * 0.395)
    assert "no bend deduction" in link.notes[0]


def test_a_four_leg_link_is_measured_as_two_closed_links():
    result = _beam_design("beam-4leg", 4000.0)
    result.stirrups[0]["legs"] = 4
    bbs = Q.build_bbs([result])
    link = [item for item in bbs.items if item.shape_code == Q.SHAPE_STIRRUP][0]
    assert link.count == 54
    assert "4 legs measured as 2 closed links" in link.notes


def test_a_bar_that_carries_its_own_ld_is_not_given_the_flat_fifty_d():
    """Finding 24: the designer's ld_mm wins; 50d is only the missing-ld fallback."""
    stated = DesignResult(element_id="beam-with-ld", element_type="beam")
    stated.section = {"b_mm": 230.0, "D_mm": 450.0, "cover_mm": 25.0}
    stated.add_bar("bottom_mid", 2, 16.0, 640.0, [0.0, 3000.0])

    missing = DesignResult(element_id="beam-no-ld", element_type="beam")
    missing.section = {"b_mm": 230.0, "D_mm": 450.0, "cover_mm": 25.0}
    missing.bars = [{"role": "bottom_mid", "count": 2, "dia_mm": 16.0, "layer": 1, "zone_mm": [0.0, 3000.0]}]

    bbs = Q.build_bbs([stated, missing])
    by_element = {item.element_id: item for item in bbs.items}
    assert by_element["beam-with-ld"].cut_length_m == pytest.approx(3.0 + 2 * 0.640)
    assert by_element["beam-no-ld"].cut_length_m == pytest.approx(3.0 + 2 * 0.800)
    assert "N_LAP_50D_FLAT" in _codes(bbs.disclosures)
    entry = [row for row in bbs.disclosures.entries if row.code == "N_LAP_50D_FLAT"][0]
    assert entry.element_ids == ["beam-no-ld"]


def test_the_golden_frame_never_takes_the_flat_lap_fallback():
    model, designs = golden_frame()
    assert "N_LAP_50D_FLAT" not in _codes(Q.take_off(model, designs).disclosures)


def test_a_run_longer_than_the_stock_length_takes_an_extra_lap():
    """13.000 + 2 x 0.500 = 14.000 m needs one lap past the 12 m mill length."""
    result = DesignResult(element_id="beam-long", element_type="beam")
    result.section = {"b_mm": 230.0, "D_mm": 450.0, "cover_mm": 25.0}
    result.add_bar("bottom_mid", 2, 16.0, 500.0, [0.0, 13000.0])
    item = Q.build_bbs([result]).items[0]
    assert item.cut_length_m == pytest.approx(14.5)
    assert "1 stock lap(s) at 12 m" in item.notes


def test_a_footing_bar_is_an_l_and_a_beam_top_bar_is_an_l():
    """v1 shape codes are STR, L and STP only, and the deferral is disclosed."""
    footing = _footing_design("ftg-0-0")
    beam = DesignResult(element_id="beam-top", element_type="beam")
    beam.section = {"b_mm": 230.0, "D_mm": 450.0, "cover_mm": 25.0}
    beam.add_bar("top_left", 2, 12.0, 600.0, [0.0, 1000.0])
    bbs = Q.build_bbs([footing, beam])
    shapes = {item.element_id: item.shape_code for item in bbs.items}
    assert shapes["ftg-0-0"] == Q.SHAPE_L
    assert shapes["beam-top"] == Q.SHAPE_L
    assert bbs.shape_codes_deferred is True
    assert "N_BBS_SHAPE_CODES_DEFERRED" in _codes(bbs.disclosures)
    assert bbs.to_dict()["shape_codes"] == list(Q.SHAPE_CODES)


def test_a_footing_mesh_bar_takes_no_development_length_past_the_pad():
    """Finding B28: a pad bar's zone IS the pad, so nothing is added at its ends.

    The golden pad is 1.500 x 1.500 and its mesh bar's zone is 0..1500 with
    ld 600. The old rule added that ld at BOTH ends and cut 2.796 m of straight
    bar for a 1.500 m pad, 83 percent more steel than the pad can hold.
    """
    bbs = Q.build_bbs([_footing_design("ftg-0-0")])
    bars = [item for item in bbs.items if item.shape_code == Q.SHAPE_L]
    assert len(bars) == 2, "one mesh set each way"
    for bar in bars:
        assert bar.cut_length_m == pytest.approx(1.500 + Q.BEND_90_DIA * 12.0 / 1000.0)
        assert bar.cut_length_m <= 1.500 + Q.BEND_90_DIA * 12.0 / 1000.0 + 1e-9, (
            "a scheduled bar may not be longer than the pad it lies in"
        )
        assert bar.total_mass_kg == pytest.approx(10 * 1.596 * 0.888)
        assert "no development length added here" in bar.notes[0]
        assert not any("at each end" in note for note in bar.notes)


def test_a_slab_bar_still_anchors_into_its_support_at_each_end():
    """B28 is a per-class rule, not "footing and slab": a slab is NOT a pad.

    A slab bar's zone is the span, so the anchorage into the support at each end
    genuinely lies outside it and is measured, exactly as before.
    """
    bbs = Q.build_bbs([_slab_design("slab-s0")])
    by_mark = {item.bar_mark: item for item in bbs.items}
    assert by_mark["S1-M1"].cut_length_m == pytest.approx(5.000 + 2 * 0.500)
    assert by_mark["S1-M2"].cut_length_m == pytest.approx(8.000 + 2 * 0.400)
    assert "anchored 0.5 m at each end" in by_mark["S1-M1"].notes[0]


def test_a_bar_that_states_its_own_anchorage_ends_overrides_its_class():
    """Where a class rule does not fit, the DESIGNER says so, not this module."""
    result = DesignResult(element_id="beam-detailed", element_type="beam")
    result.section = {"b_mm": 230.0, "D_mm": 450.0, "cover_mm": 25.0}
    result.add_bar("bottom_mid", 2, 16.0, 800.0, [0.0, 4000.0])
    result.bars[0]["anchorage_ends"] = 1
    item = Q.build_bbs([result]).items[0]
    assert item.cut_length_m == pytest.approx(4.000 + 0.800)
    assert "one lap per storey" in item.notes[0]
    assert "1 anchorage end(s) stated by the design" in item.notes[0]


def test_a_link_on_a_section_with_no_cover_ships_at_zero_and_says_why():
    """Finding 25 forbids a bar-schedule cover default; the gap is disclosed."""
    result = DesignResult(element_id="beam-no-cover", element_type="beam")
    result.section = {"b_mm": 230.0, "D_mm": 450.0}
    result.add_stirrup([0.0, 3000.0], 2, 8.0, 150.0)
    bbs = Q.build_bbs([result])
    assert bbs.items[0].cut_length_m == 0.0
    assert bbs.items[0].total_mass_kg == 0.0
    assert any("never defaulted" in note for note in bbs.items[0].notes)
    entry = [row for row in bbs.disclosures.entries if row.code == "N_NO_BEND_DEDUCTION"][0]
    assert entry.element_ids == ["beam-no-cover"]


def test_wastage_is_added_disclosed_and_overridable():
    model, designs = golden_frame()
    default = Q.build_bbs(designs)
    assert default.wastage_pct == pytest.approx(3.0)
    assert default.total_with_wastage_kg == pytest.approx(1649.91616 * 1.03)
    assert "N_WASTAGE_3PCT" in _codes(default.disclosures)

    richer = Q.build_bbs(designs, {"wastage_pct": 5.0})
    assert richer.total_kg == pytest.approx(default.total_kg)
    assert richer.total_with_wastage_kg == pytest.approx(1649.91616 * 1.05)
    message = [row for row in richer.disclosures.entries if row.code == "N_WASTAGE_3PCT"][0].message
    assert "5.0 percent" in message


def test_masses_round_to_the_stated_precision_on_the_wire():
    model, designs = golden_frame()
    wire = Q.build_bbs(designs).to_dict()
    assert wire["total_kg"] == pytest.approx(1649.916)
    assert wire["total_with_wastage_kg"] == pytest.approx(1699.414)
    assert wire["mass_by_dia"]["16"] == pytest.approx(687.377, abs=1e-3)


def test_bar_marks_are_stable_and_shaped_like_the_spec():
    """Class letter, element number, role letter, set number: "C1-L1"."""
    model, designs = golden_frame()
    bbs = Q.build_bbs(designs)
    marks = {item.element_id + "|" + item.shape_code: item.bar_mark for item in bbs.items}
    assert marks["col-0-0-s0|STR"] == "C1-L1"
    assert marks["col-0-0-s0|STP"] == "C1-T1"
    assert bbs.items[0].bar_mark == Q.build_bbs(designs).items[0].bar_mark
    slab_marks = sorted(item.bar_mark for item in bbs.items if item.element_class == "slab")
    assert slab_marks == ["S1-M1", "S1-M2", "S2-M1", "S2-M2"]


def test_items_elide_past_the_cap_but_the_aggregates_do_not():
    model, designs = golden_frame()
    bbs = Q.build_bbs(designs, {"bbs_max_items": 3})
    assert bbs.items_elided is True
    assert bbs.items_total == len(bbs.items)
    assert bbs.total_kg == pytest.approx(1649.91616)
    wire = bbs.to_dict()
    assert len(wire["items"]) == 3
    assert wire["items_total"] == len(bbs.items)


def test_detail_full_asked_for_by_name_hands_over_every_row():
    """Finding B30: the consumer that must do arithmetic row by row gets them all.

    `report._zero_blocked_bbs` subtracts a blocked element's mass out of the
    aggregates and can only do it from the rows, which is why `api.py` asks for
    `DETAIL_FULL` by name. It used to be handed `bbs_max_items` rows anyway, so
    every blocked element sorting past the cap kept its full reinforcement.
    """
    model, designs = golden_frame()
    bbs = Q.build_bbs(designs, {"bbs_max_items": 3})

    full = bbs.to_dict(Q.DETAIL_FULL)
    assert len(full["items"]) == len(bbs.items)
    assert full["items_total"] == len(bbs.items)
    assert full["items_elided"] is False, "nothing was dropped, so nothing is declared dropped"

    # The level the options carry does NOT lift the cap: a normal run's wire
    # payload is unchanged, which is the whole reason the uncap is keyed on the
    # explicit argument.
    default = bbs.to_dict()
    assert len(default["items"]) == 3
    assert default["items_elided"] is True
    assert default["items_total"] == len(bbs.items)

    compact = bbs.to_dict(Q.DETAIL_COMPACT)
    assert compact["items"] == []
    assert compact["items_elided"] is True
    assert compact["total_kg"] == full["total_kg"] == default["total_kg"]


def test_a_serialized_design_result_takes_off_to_the_same_numbers():
    """run_design hands over objects, a cached response hands over dicts."""
    model, designs = golden_frame()
    live = Q.build_bbs(designs).to_dict()
    wire = Q.build_bbs([result.to_dict() for result in designs]).to_dict()
    assert live == wire


# ---------------------------------------------------------------------------
# rates
# ---------------------------------------------------------------------------


def test_load_rates_reads_the_shipped_placeholder_schedule():
    schedule = Q.load_rates()
    assert schedule.name == "default_india"
    assert schedule.currency == "INR"
    assert schedule.placeholder is True
    assert schedule.lookup("concrete_m3", "M25") == pytest.approx(7800.0)
    assert schedule.lookup("excavation_m3") == pytest.approx(220.0)
    assert schedule.keys_of("formwork_m2") == ["beam", "column", "footing", "slab"]
    assert "PLACEHOLDER" in schedule.source


def test_overrides_merge_over_the_base_and_are_named_as_the_rate_source():
    """A district rate is a merge, and every merged leaf reports as "override"."""
    schedule = Q.load_rates("default_india", {"concrete_m3": {"M25": 8100}, "excavation_m3": 250})
    assert schedule.lookup("concrete_m3", "M25") == pytest.approx(8100.0)
    assert schedule.lookup("concrete_m3", "M20") == pytest.approx(7200.0)
    assert schedule.lookup("excavation_m3") == pytest.approx(250.0)
    assert schedule.overridden == ("concrete_m3.M25", "excavation_m3")
    assert schedule.source_of("concrete_m3.M25") == "override"
    assert schedule.source_of("concrete_m3.M20") == "default_india"


def test_overrides_may_arrive_wrapped_in_an_items_block():
    schedule = Q.load_rates("default_india", {"items": {"steel_kg": {"Fe500": 91}}})
    assert schedule.lookup("steel_kg", "Fe500") == pytest.approx(91.0)
    assert schedule.source_of("steel_kg.Fe500") == "override"


def test_an_unknown_schedule_name_raises_naming_the_ones_that_exist():
    with pytest.raises(ValueError) as excinfo:
        Q.load_rates("bihar_2019")
    assert "bihar_2019" in str(excinfo.value)
    assert "default_india" in str(excinfo.value)


def test_rates_accept_a_name_a_mapping_or_a_schedule():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    by_name = Q.price(takeoff, "default_india")
    by_mapping = Q.price(takeoff, {"schedule": "default_india"})
    by_object = Q.price(takeoff, Q.load_rates())
    assert by_name.total == by_mapping.total == by_object.total
    with pytest.raises(ValueError):
        Q.price(takeoff, 17)


def test_a_bare_items_shaped_mapping_is_read_as_an_override_set():
    """Pricing at the shipped rates would silently ignore what was asked for."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    boq = Q.price(takeoff, {"steel_kg": {"Fe500": 100}})
    steel = [line for line in boq.items if line.item == "Reinforcement"][0]
    assert steel.rate == pytest.approx(100.0)
    assert steel.rate_source == "override"


# ---------------------------------------------------------------------------
# bill of quantities
# ---------------------------------------------------------------------------


def test_the_boq_total_is_exactly_the_sum_of_the_amounts():
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert boq.items
    assert boq.total == pytest.approx(sum(line.amount for line in boq.items))
    assert boq.total == round(sum(line.amount for line in boq.items), 2)
    assert boq.total == pytest.approx(sum(boq.subtotals.values()))
    assert sorted(boq.subtotals) == ["concrete", "earthwork", "formwork", "masonry", "steel"]
    assert [line.sl for line in boq.items] == list(range(1, len(boq.items) + 1))


def test_every_boq_line_names_where_its_rate_came_from():
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs), Q.load_rates("default_india", {"steel_kg": {"Fe500": 91}}))
    steel = [line for line in boq.items if line.item == "Reinforcement"][0]
    assert steel.rate_source == "override"
    assert steel.rate == pytest.approx(91.0)
    concrete = [line for line in boq.items if line.item == "Concrete"][0]
    assert concrete.rate_source == "default_india"


def test_reinforcement_is_priced_off_the_schedule_including_wastage():
    """Steel has exactly one source (finding 24): the BBS, wastage included."""
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    boq = Q.price(takeoff)
    steel = [line for line in boq.items if line.item == "Reinforcement"][0]
    assert steel.unit == "kg"
    assert steel.qty == pytest.approx(round(1649.91616 * 1.03, 3))
    assert steel.amount == pytest.approx(round(steel.qty * 78.0, 2))
    assert "3.0 percent wastage" in steel.spec


def test_the_placeholder_flag_and_its_disclosure_propagate():
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert boq.placeholder_rates is True
    assert "W_PLACEHOLDER_RATES" in _codes(boq.disclosures)


def test_a_real_schedule_does_not_raise_the_placeholder_warning():
    model, designs = golden_frame()
    schedule = {
        "name": "district_2026",
        "placeholder": False,
        "currency": "INR",
        "items": {
            "concrete_m3": {"M25": 8000},
            "steel_kg": {"Fe500": 80},
            "formwork_m2": {"column": 600, "beam": 550, "slab": 470, "footing": 380},
            "excavation_m3": 200,
            "pcc_m3": 5500,
            "backfill_m3": 130,
        },
    }
    boq = Q.price(Q.take_off(model, designs), schedule)
    assert boq.schedule == "district_2026"
    assert boq.placeholder_rates is False
    assert "W_PLACEHOLDER_RATES" not in _codes(boq.disclosures)


def test_a_rate_the_schedule_does_not_carry_is_substituted_and_named():
    """Never price at zero in silence: say which rate stood in for which."""
    model, designs = golden_frame()
    for result in designs:
        result.materials["steel_grade"] = "Fe415"
        if result.element_type == "column":
            result.materials["concrete_grade"] = "M40"
    takeoff = Q.take_off(model, designs)
    assert takeoff.steel_grade == "Fe415"
    boq = Q.price(takeoff)
    m40 = [line for line in boq.items if line.spec.startswith("M40")][0]
    assert m40.rate == pytest.approx(8400.0)
    assert m40.rate_source == "default_india (M30 substituted for M40)"
    steel = [line for line in boq.items if line.item == "Reinforcement"][0]
    assert steel.rate_source == "default_india (Fe500 substituted for Fe415)"


def test_a_115_wall_is_priced_off_the_nearest_tabulated_thickness():
    takeoff = Q.take_off(_masonry_model(), [])
    boq = Q.price(takeoff)
    partition = [line for line in boq.items if line.spec.startswith("115")][0]
    assert partition.rate == pytest.approx(5900.0)
    assert partition.rate_source == "default_india (block_190 substituted for a 115 mm wall)"
    bearing = [line for line in boq.items if line.spec.startswith("230")][0]
    assert bearing.rate_source == "default_india"


def test_band_and_lintel_shuttering_are_priced_at_the_beam_rate():
    takeoff = Q.take_off(_masonry_model(), [])
    boq = Q.price(takeoff)
    band = [line for line in boq.items if line.spec == "shuttering to band"][0]
    assert band.rate == pytest.approx(560.0)
    assert band.rate_source == "default_india (beam formwork rate applied to band)"


def test_a_line_with_no_rate_at_all_is_left_out_rather_than_priced_at_zero():
    """data/rates.yaml has no disposal rate, so no disposal line is invented."""
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert not [line for line in boq.items if "Disposal" in line.item]
    assert [line for line in boq.items if "Backfilling" in line.item]


def test_zero_quantity_rows_never_reach_the_bill():
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert all(line.qty > 0.0 for line in boq.items)
    assert not [line for line in boq.items if "stair" in line.spec]


# ---------------------------------------------------------------------------
# density metrics and the calibration bands
# ---------------------------------------------------------------------------


def test_the_density_metrics_are_per_square_metre_of_builtup_area():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    boq = Q.price(takeoff)
    assert takeoff.builtup_area_m2 == pytest.approx(80.0)
    assert boq.steel_kg_per_m2 == pytest.approx(1649.91616 * 1.03 / 80.0)
    assert boq.concrete_m3_per_m2 == pytest.approx(23.1703 / 80.0)
    assert boq.cost_per_m2 == pytest.approx(boq.total / 80.0)


def test_the_calibration_bands_stay_quiet_inside_the_band():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    boq = Q.price(takeoff, None, {"steel_band_kg_m2": (0.0, 100.0), "concrete_band_m3_m2": (0.0, 1.0)})
    assert "W_STEEL_DENSITY_BAND" not in _codes(boq.disclosures)
    assert "W_CONCRETE_DENSITY_BAND" not in _codes(boq.disclosures)


def test_the_calibration_bands_fire_on_an_absurd_design():
    """Ten times the steel and twice the concrete trips both bands, with numbers."""
    model, designs = golden_frame()
    for result in designs:
        for bar in result.bars:
            bar["count"] = int(bar["count"]) * 10
        if result.element_type == "slab":
            result.section["thickness_mm"] = 250.0
            result.section["D_mm"] = 250.0
    boq = Q.price(Q.take_off(model, designs))
    codes = _codes(boq.disclosures)
    assert "W_STEEL_DENSITY_BAND" in codes
    assert "W_CONCRETE_DENSITY_BAND" in codes
    message = [row for row in boq.disclosures.entries if row.code == "W_STEEL_DENSITY_BAND"][0].message
    assert "kg per m2 of built-up area" in message
    assert "2.50 to 7.00" in message
    # The one thing the old sentence never said: which system it judged.
    assert "calibration band for low-rise reinforced concrete" in message


def test_the_shipped_bands_are_the_spec_ones_and_are_stated_in_the_basis():
    assert Q.STEEL_DENSITY_BAND_KG_M2 == (2.5, 7.0)
    assert Q.CONCRETE_DENSITY_BAND_M3_M2 == (0.10, 0.20)
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert "2.50 to 7.00 kg/m2" in boq.density_basis
    assert "0.10 to 0.20 m3/m2" in boq.density_basis
    assert "not a code limit" in boq.density_basis


def test_the_rc_frame_basis_sentence_is_byte_for_byte_what_it_always_was():
    """The RC path is the control: same bands, same words, same bytes.

    This is the whole promise of making the bands per system. `rc_frame` is the
    row the two hard-coded numbers became, so an RC take-off has to come out of
    `price` indistinguishable from the version before the table existed.
    """
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert boq.density_basis == (
        "densities are per square metre of built-up area; the calibration bands are "
        "2.50 to 7.00 kg/m2 of reinforcement and 0.10 to 0.20 m3/m2 of concrete, "
        "a heuristic for low-rise reinforced concrete that catches take-off bugs "
        "and absurd designs, not a code limit"
    )


def test_the_golden_frame_trips_both_bands_because_it_is_a_small_plate():
    """22.9 kg/m2 and 0.290 m3/m2 on an 80 m2 plate: the heuristic says look."""
    model, designs = golden_frame()
    boq = Q.price(Q.take_off(model, designs))
    assert boq.steel_kg_per_m2 > 7.0
    assert boq.concrete_m3_per_m2 > 0.20
    assert "W_STEEL_DENSITY_BAND" in _codes(boq.disclosures)
    assert "W_CONCRETE_DENSITY_BAND" in _codes(boq.disclosures)


def test_a_model_with_no_area_forms_no_density_and_says_so():
    model = StructuralModel(id="empty")
    model.storeys.append(Storey(index=0, name="G", bottom_z_m=0.0, height_m=3.0))
    takeoff = Q.take_off(model, [])
    boq = Q.price(takeoff)
    assert takeoff.builtup_area_m2 == 0.0
    assert "cannot be formed" in takeoff.builtup_basis
    assert boq.total == 0.0
    assert boq.cost_per_m2 == 0.0
    assert "W_STEEL_DENSITY_BAND" not in _codes(boq.disclosures)


# ---------------------------------------------------------------------------
# the bands are per system (data/density_bands.yaml)
# ---------------------------------------------------------------------------
#
# The gap this closes. Until 2026-08-30 there were two bands, 2.50 to 7.00 kg/m2
# and 0.10 to 0.20 m3/m2, and they were low-rise RC FRAME numbers applied to
# every system. The measured masonry run below came out at 1.02 kg/m2 and 0.020
# m3/m2 and tripped both: correct arithmetic, wrong advice, on a design that was
# right. A load-bearing masonry house legitimately carries almost no reinforced
# concrete, so a warning that fires on all of them teaches its reader to stop
# reading warnings, which is the one failure a warning must not have.

#: The masonry run of IMPLEMENTATION_STATUS 6.10, end to end through
#: `api.run_design` on tests/fixtures/housing_masonry.json (30 x 40 ft, two
#: storeys, 230 mm walls): 222.97 m2 built up, 227.17 kg of reinforcement,
#: 4.43 m3 of concrete (tie columns and IS 4326 bands, no slab and no designed
#: strip footing at that moment) and 117.48 m3 of walling. These four numbers
#: are the whole reason the bands are per system, so they are written down here
#: as the historical figure rather than re-measured: the pipeline's RC content
#: moves as designers land, and this test is about the bands, not the pipeline.
MEASURED_MASONRY_AREA_M2 = 222.97
MEASURED_MASONRY_STEEL_KG = 227.17
MEASURED_MASONRY_CONCRETE_M3 = 4.43
MEASURED_MASONRY_MASONRY_M3 = 117.48


def _takeoff_of(
    system,
    steel_kg=MEASURED_MASONRY_STEEL_KG,
    concrete_m3=MEASURED_MASONRY_CONCRETE_M3,
    masonry_m3=MEASURED_MASONRY_MASONRY_M3,
    area_m2=MEASURED_MASONRY_AREA_M2,
):
    """A take-off carrying four aggregates and nothing else.

    `price` reads exactly these: the built-up area, the concrete total, the
    masonry total and the schedule's mass. Building them by hand keeps the band
    arithmetic separate from the measurement arithmetic the golden frame pins.
    """
    takeoff = Q.QuantityTakeoff(builtup_area_m2=area_m2, system=str(getattr(system, "value", system)))
    takeoff.concrete.append(
        Q.ElementQuantity(element_class="band", grade="M25", volume_m3=concrete_m3, basis="hand", count=1)
    )
    takeoff.masonry.append(
        Q.MasonryQuantity(
            thickness_mm=229,
            bearing=True,
            volume_m3=masonry_m3,
            deductions_m3=0.0,
            basis="hand",
            count=1,
        )
    )
    takeoff.bbs = Q.BarBendingSchedule(
        total_kg=steel_kg / 1.03, total_with_wastage_kg=steel_kg, wastage_pct=3.0
    )
    return takeoff


def test_the_measured_masonry_house_stops_tripping_the_frame_bands():
    """1.02 kg/m2 and 0.020 m3/m2: right for masonry, and now judged as masonry."""
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY))
    assert boq.steel_kg_per_m2 == pytest.approx(1.0188, abs=5e-4)
    assert boq.concrete_m3_per_m2 == pytest.approx(0.01987, abs=5e-5)
    assert boq.masonry_m3_per_m2 == pytest.approx(0.52689, abs=5e-5)
    codes = _codes(boq.disclosures)
    assert "W_STEEL_DENSITY_BAND" not in codes
    assert "W_CONCRETE_DENSITY_BAND" not in codes
    assert [boq.density_checks[name]["status"] for name in ("concrete", "masonry", "steel")] == [
        "inside",
        "inside",
        "inside",
    ]


def test_the_very_same_numbers_still_trip_the_bands_when_called_a_frame():
    """The control for the test above: the fix is the system, not the numbers.

    The two sentences pinned here are, to the digit, the two the measured masonry
    run carried on 2026-08-30 before the bands were per system, plus the clause
    naming which system is being judged. A frame that measures 1.02 kg/m2 really
    is wrong and really should still be told so.
    """
    boq = Q.price(_takeoff_of(System.RC_FRAME))
    entries = {row.code: row.message for row in boq.disclosures.entries}
    assert entries["W_STEEL_DENSITY_BAND"] == (
        "reinforcement works out at 1.02 kg per m2 of built-up area, outside the "
        "2.50 to 7.00 kg/m2 calibration band for low-rise reinforced concrete; "
        "check the take-off and the design before trusting the cost"
    )
    assert entries["W_CONCRETE_DENSITY_BAND"] == (
        "concrete works out at 0.020 m3 per m2 of built-up area, outside the "
        "0.10 to 0.20 m3/m2 calibration band for low-rise reinforced concrete; "
        "check the take-off and the design before trusting the cost"
    )


def test_the_masonry_bands_are_named_in_the_basis_and_the_message():
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY, steel_kg=0.0))
    assert boq.system == "load_bearing_masonry"
    assert boq.system_label == "load bearing masonry"
    assert boq.density_basis == (
        "densities are per square metre of built-up area; the calibration bands are "
        "0.40 to 5.00 kg/m2 of reinforcement, 0.01 to 0.25 m3/m2 of concrete and "
        "0.10 to 0.80 m3/m2 of masonry, a heuristic for load bearing masonry that "
        "catches take-off bugs and absurd designs, not a code limit"
    )
    message = [row for row in boq.disclosures.entries if row.code == "W_STEEL_DENSITY_BAND"][0].message
    assert "calibration band for load bearing masonry" in message
    assert "0.40 to 5.00" in message


def test_a_genuinely_absurd_masonry_takeoff_still_trips_both_bands():
    """Ten times the steel and twenty times the concrete: the warning still works.

    A band wide enough not to slander a correct masonry design still has to catch
    a take-off bug, or it is decoration.
    """
    boq = Q.price(
        _takeoff_of(
            System.LOAD_BEARING_MASONRY,
            steel_kg=MEASURED_MASONRY_STEEL_KG * 10.0,
            concrete_m3=MEASURED_MASONRY_CONCRETE_M3 * 20.0,
        )
    )
    codes = _codes(boq.disclosures)
    assert "W_STEEL_DENSITY_BAND" in codes
    assert "W_CONCRETE_DENSITY_BAND" in codes
    assert boq.density_checks["steel"]["status"] == "outside"
    assert boq.density_checks["concrete"]["status"] == "outside"
    assert boq.density_checks["masonry"]["status"] == "inside"


def test_the_masonry_volume_check_is_the_number_a_reader_sanity_checks_there():
    """A masonry house that measured no walling is a take-off bug, and it says so."""
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY, masonry_m3=0.0))
    check = boq.density_checks["masonry"]
    assert check["status"] == "outside"
    assert check["metric"] == "masonry_m3_per_m2"
    assert check["band"] == [0.10, 0.80]
    assert "masonry works out at 0.000 m3 per m2 of built-up area" in check["message"]
    assert "0.10 to 0.80 m3/m2 calibration band for load bearing masonry" in check["message"]


def test_the_masonry_volume_check_stays_quiet_on_an_ordinary_masonry_house():
    for volume in (0.15 * 222.97, MEASURED_MASONRY_MASONRY_M3, 0.75 * 222.97):
        boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY, masonry_m3=volume))
        assert boq.density_checks["masonry"]["status"] == "inside", volume


def test_an_rc_frame_is_not_judged_on_its_masonry_at_all():
    """Infill quantity is a partition-layout question; the silence is deliberate."""
    check = Q.price(_takeoff_of(System.RC_FRAME)).density_checks["masonry"]
    assert check["status"] == "not_checked"
    assert check["band"] is None
    assert check["disclosed"] is False
    assert check["message"] == ""


def test_the_masonry_volume_finding_reaches_the_payload_whatever_the_registry_holds():
    """The check reports its verdict on the BOQ, and raises when the code exists.

    `model.REGISTRY` is the authority on disclosure codes and it does not yet
    hold `W_MASONRY_DENSITY_BAND`; the registry lives in `model.py`, which this
    module does not own. So the verdict always lands in `boq.density_checks`, and
    the ladder entry appears the moment the code is registered, with no change
    here. Both halves of that are asserted, so this test is the record of the
    contract either way.
    """
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY, masonry_m3=0.0))
    check = boq.density_checks["masonry"]
    assert check["disclosure_code"] == "W_MASONRY_DENSITY_BAND"
    assert check["status"] == "outside"
    assert check["message"], "the finding is on the payload whether or not it is on the ladder"
    registered = "W_MASONRY_DENSITY_BAND" in REGISTRY
    assert check["disclosure_code_registered"] is registered
    assert check["disclosed"] is registered
    assert ("W_MASONRY_DENSITY_BAND" in _codes(boq.disclosures)) is registered


def test_a_caller_band_beats_the_system_table():
    """`price(..., {"steel_band_kg_m2": ...})` means what it says, on any system."""
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY), None, {"steel_band_kg_m2": (10.0, 20.0)})
    assert boq.density_checks["steel"]["band"] == [10.0, 20.0]
    assert boq.density_checks["steel"]["band_source"] == "caller override"
    assert "W_STEEL_DENSITY_BAND" in _codes(boq.disclosures)
    # and the untouched checks still come off the table
    assert boq.density_checks["concrete"]["band_source"].endswith("the load_bearing_masonry row")


def test_a_caller_masonry_band_turns_the_check_on_for_a_frame_too():
    boq = Q.price(_takeoff_of(System.RC_FRAME), None, {"masonry_band_m3_m2": (0.0, 0.10)})
    check = boq.density_checks["masonry"]
    assert check["band"] == [0.0, 0.10]
    assert check["band_source"] == "caller override"
    assert check["status"] == "outside"


def test_an_empty_band_option_asks_for_the_system_table_rather_than_failing():
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY), None, {"steel_band_kg_m2": []})
    assert boq.density_checks["steel"]["band"] == [0.40, 5.00]
    assert boq.density_checks["steel"]["band_source"].endswith("the load_bearing_masonry row")


def test_an_unknown_system_falls_back_to_the_frame_row_and_names_the_substitution():
    boq = Q.price(_takeoff_of("rammed_earth"))
    assert boq.system == "rammed_earth"
    assert boq.density_checks["steel"]["band"] == [2.50, 7.00]
    assert boq.density_checks["steel"]["band_source"] == (
        "data/density_bands.yaml, the rc_frame row (substituted: the table carries "
        "no row for system rammed_earth)"
    )


def test_a_hand_built_takeoff_that_names_no_system_says_so_rather_than_pretending():
    boq = Q.price(_takeoff_of(""))
    assert boq.system == ""
    assert boq.system_label == "low-rise reinforced concrete"
    assert boq.density_checks["steel"]["band_source"] == (
        "data/density_bands.yaml, the rc_frame row (the take-off names no system)"
    )


def test_a_model_with_no_area_checks_nothing_and_says_which_bands_it_would_have():
    boq = Q.price(_takeoff_of(System.LOAD_BEARING_MASONRY, area_m2=0.0))
    for name in Q.DENSITY_BAND_CHECKS:
        assert boq.density_checks[name]["status"] in ("no_area", "not_checked"), name
        assert boq.density_checks[name]["disclosed"] is False
    assert "load bearing masonry" in boq.density_basis


def test_the_take_off_carries_the_system_it_measured():
    """`price` cannot see the model, so the take-off has to bring the system."""
    model, designs = golden_frame()
    assert Q.take_off(model, designs).system == "rc_frame"
    model.system = System.LOAD_BEARING_MASONRY
    takeoff = Q.take_off(model, designs)
    assert takeoff.system == "load_bearing_masonry"
    assert takeoff.to_dict()["system"] == "load_bearing_masonry"


def test_the_band_table_is_provenance_tagged_and_covers_every_system():
    table = load_yaml("density_bands")
    for key in ("source", "edition", "schema_version", "systems", "checks", "default_system"):
        assert key in table, key
    assert str(table["source"]).strip()
    assert str(table["edition"]).strip()
    assert set(Q.DENSITY_BANDS) == {member.value for member in System}, (
        "every system the model can deliver needs a row, or price would substitute"
    )
    assert Q.DEFAULT_BAND_SYSTEM == System.RC_FRAME.value
    for name, row in sorted(table["systems"].items()):
        assert str(row["label"]).strip(), name
        assert str(row["basis"]).strip(), name
        assert str(row["uncertainty"]).strip(), name
        # NOT the "print" marker the transcribed tables carry: there is no
        # printed standard behind a calibration heuristic, so a marker saying
        # "read this back against the book" would be a lie and would inflate
        # the print-verification debt of IMPLEMENTATION_STATUS 5.2 with rows no
        # book can settle. The vocabulary says what would actually settle each.
        assert row["verify"] in ("inherited", "measured", "unmeasured"), name
    assert table["systems"]["rc_frame"]["verify"] == "inherited"
    assert table["systems"]["load_bearing_masonry"]["verify"] == "measured"
    assert table["systems"]["confined_masonry"]["verify"] == "unmeasured"
    for check, meta in sorted(table["checks"].items()):
        for key in ("metric", "band_key", "noun", "unit", "disclosure_code"):
            assert str(meta[key]).strip(), check + "." + key


def test_every_tabulated_band_is_an_ordered_pair_or_a_deliberate_null():
    for system in sorted(Q.DENSITY_BANDS):
        for check in Q.DENSITY_BAND_CHECKS:
            band = Q.DENSITY_BANDS[system][check]
            if band is None:
                continue
            assert len(band) == 2, (system, check)
            assert 0.0 <= band[0] < band[1], (system, check, band)


def test_the_two_shipped_codes_are_registered_and_the_third_declares_its_gap():
    """An unregistered code is a load-time refusal unless the row declares it.

    Registry codes only: a check naming a code `model.REGISTRY` does not hold
    would raise the first time it fired, so `quantities.py` refuses to import it
    at all. `pending_registration` is the one documented exemption, and it is
    what keeps the masonry check honest rather than inventing a code locally.
    """
    checks = load_yaml("density_bands")["checks"]
    assert checks["steel"]["disclosure_code"] in REGISTRY
    assert checks["concrete"]["disclosure_code"] in REGISTRY
    assert not checks["steel"].get("pending_registration")
    assert not checks["concrete"].get("pending_registration")
    if "W_MASONRY_DENSITY_BAND" in REGISTRY:
        assert not checks["masonry"].get("pending_registration"), (
            "the code is registered now; drop the exemption from the table"
        )
    else:
        assert checks["masonry"]["pending_registration"] is True
        assert checks["masonry"]["disclosure_code"] == "W_MASONRY_DENSITY_BAND"


def test_the_rc_frame_row_is_the_two_numbers_the_module_always_carried():
    row = Q.DENSITY_BANDS["rc_frame"]
    assert row["steel"] == (2.5, 7.0)
    assert row["concrete"] == (0.10, 0.20)
    assert row["masonry"] is None
    assert Q.STEEL_DENSITY_BAND_KG_M2 is row["steel"]
    assert Q.CONCRETE_DENSITY_BAND_M3_M2 is row["concrete"]


def test_the_band_provenance_is_available_to_a_report():
    provenance = Q.band_provenance()
    assert provenance["table"] == "data/density_bands.yaml"
    assert provenance["default_system"] == "rc_frame"
    assert "load_bearing_masonry" in provenance["systems"]
    assert provenance["systems"]["confined_masonry"]["uncertainty"]
    assert json.dumps(provenance)


def test_builtup_area_falls_back_to_the_rooms_when_no_slab_is_placed():
    model = StructuralModel(id="rooms")
    model.storeys.append(Storey(index=0, name="G", bottom_z_m=0.0, height_m=3.0))
    model.rooms.append(
        RoomPoly(
            id="room-1",
            storey=0,
            name="Living",
            occupancy=Occupancy.HABITABLE,
            polygon=[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)],
            area_m2=12.0,
        )
    )
    takeoff = Q.take_off(model, [])
    assert takeoff.builtup_area_m2 == pytest.approx(12.0)
    assert "falls back to the sum of the room areas" in takeoff.builtup_basis


# ---------------------------------------------------------------------------
# determinism and the wire shape
# ---------------------------------------------------------------------------


def test_the_take_off_is_deterministic():
    model, designs = golden_frame()
    first = json.dumps(Q.take_off(model, designs).to_dict(), sort_keys=True)
    second = json.dumps(Q.take_off(model, designs).to_dict(), sort_keys=True)
    assert first == second


def test_the_take_off_does_not_depend_on_the_order_of_the_design_results():
    model, designs = golden_frame()
    forward = json.dumps(Q.take_off(model, designs).to_dict(), sort_keys=True)
    reversed_order = json.dumps(Q.take_off(model, list(reversed(designs))).to_dict(), sort_keys=True)
    assert forward == reversed_order


def test_pricing_is_deterministic():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    first = json.dumps(Q.price(takeoff).to_dict(), sort_keys=True)
    second = json.dumps(Q.price(takeoff).to_dict(), sort_keys=True)
    assert first == second


def test_every_emitted_dict_is_json_and_key_sorted():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    boq = Q.price(takeoff)
    for payload in (takeoff.to_dict(), takeoff.bbs.to_dict(), boq.to_dict(), Q.load_rates().to_dict()):
        text = json.dumps(payload)
        assert json.loads(text) == payload
    wire = takeoff.bbs.to_dict()
    # Diameters sort as numbers, not as text: an 8 comes before a 10.
    assert [int(key) for key in wire["mass_by_dia"]] == sorted(int(key) for key in wire["mass_by_dia"])
    assert list(wire["mass_by_class"]) == sorted(wire["mass_by_class"])
    assert list(boq.to_dict()["subtotals"]) == sorted(boq.subtotals)


def test_the_options_echo_carries_every_resolved_knob():
    model, designs = golden_frame()
    echo = Q.take_off(model, designs, {"wastage_pct": 4.5}).to_dict()["options_echo"]
    assert echo["wastage_pct"] == pytest.approx(4.5)
    assert echo["lap_dia_multiple"] == pytest.approx(50.0)
    assert echo["steel_band_kg_m2"] == [2.5, 7.0]
    # Empty is the shipped masonry default and it means "ask the system table";
    # rc_frame's row says do not check masonry at all.
    assert echo["masonry_band_m3_m2"] == []
    assert set(echo) == set(Q._OPTION_FIELDS)


def test_options_coerce_from_a_mapping_an_instance_or_nothing():
    assert Q.QuantityOptions.coerce(None).wastage_pct == pytest.approx(3.0)
    supplied = Q.QuantityOptions(wastage_pct=7.0)
    assert Q.QuantityOptions.coerce(supplied) is supplied
    assert Q.QuantityOptions.coerce({"bbs_max_items": 12}).bbs_max_items == 12
    assert Q.QuantityOptions.coerce({"unknown_knob": 1}).wastage_pct == pytest.approx(3.0)
    with pytest.raises(ValueError):
        Q.QuantityOptions.coerce({"steel_band_kg_m2": (1.0,)})
    with pytest.raises(ValueError):
        Q.QuantityOptions.coerce([1, 2])


# ---------------------------------------------------------------------------
# disclosure hygiene
# ---------------------------------------------------------------------------


def test_every_disclosure_is_a_registered_code_emitted_once():
    model, designs = golden_frame()
    takeoff = Q.take_off(model, designs)
    boq = Q.price(takeoff)
    for log in (takeoff.disclosures, takeoff.bbs.disclosures, boq.disclosures):
        codes = [entry.code for entry in log.entries]
        assert len(codes) == len(set(codes)), codes
        for code in codes:
            assert code in REGISTRY, code
        for entry in log.entries:
            assert entry.severity == REGISTRY[entry.code][0]
            assert entry.stage == "quantities"
            assert entry.message


def test_the_take_off_carries_the_bar_schedule_disclosures_too():
    """One ladder reaches the report: the schedule's notes ride on the take-off."""
    model, designs = golden_frame()
    codes = _codes(Q.take_off(model, designs).disclosures)
    for code in ("N_BBS_SHAPE_CODES_DEFERRED", "N_NO_BEND_DEDUCTION", "N_WASTAGE_3PCT"):
        assert code in codes


def test_the_expected_notes_all_fire_on_a_model_that_earns_them():
    """Every v1 simplification the spec lists, raised once, on one model."""
    model = _masonry_model()
    model.columns.append(
        Column(id="col-x", stack_id="stk-x", storey=0, x_m=0.0, y_m=0.0, width_m=0.23, depth_m=0.23)
    )
    model.footings.append(
        Footing(
            id="ftg-x",
            kind=FootingKind.ISOLATED,
            supports=["col-x"],
            x_m=0.0,
            y_m=0.0,
            w_m=1.2,
            h_m=1.2,
            depth_m=2.0,
        )
    )
    result = DesignResult(element_id="ftg-x", element_type="footing")
    result.section = {"bx_mm": 1200.0, "ly_mm": 1200.0, "D_mm": 350.0, "cover_mm": 50.0}
    result.materials = {"concrete_grade": "M25", "steel_grade": "Fe500"}
    result.bars = [{"role": "mesh_x", "count": 8, "dia_mm": 12.0, "layer": 1, "zone_mm": [0.0, 1200.0]}]
    codes = _codes(Q.take_off(model, [result]).disclosures)
    for code in (
        "N_COLUMN_HEIGHT_CONVENTION",
        "N_FORMWORK_EDGES_IGNORED",
        "N_PARTITION_M3_CONVENTION",
        "N_SLOPE_ALLOWANCE_FLAT",
        "N_LAP_50D_FLAT",
        "N_BBS_SHAPE_CODES_DEFERRED",
        "N_NO_BEND_DEDUCTION",
        "N_WASTAGE_3PCT",
    ):
        assert code in codes, code


def test_the_take_off_never_raises_on_an_empty_model():
    """Disclose, never explode: an empty model still yields a complete envelope."""
    takeoff = Q.take_off(StructuralModel(id="void"), None)
    assert takeoff.concrete_m3 == 0.0
    assert takeoff.formwork_m2 == 0.0
    assert takeoff.masonry_m3 == 0.0
    assert takeoff.steel_kg == 0.0
    assert len(takeoff.concrete) == len(Q.CONCRETE_CLASSES)
    assert len(takeoff.formwork) == len(Q.FORMWORK_CLASSES)
    assert json.dumps(takeoff.to_dict())
