"""Pins for placement/masonry.py: system choice, cover, Table 4, bands, steel.

Every model here is hand built so each asserted number is derivable by hand:
a 9 x 12 m plot on a 4.5 m module, 230 mm walls unless a test wants a thin one,
storey height 3.0 m. The housing fixture is exercised through the real adapter,
because the point of that case is the DISCLOSED outcome of a plan whose interior
walls are four inches thick, not a number chosen here.
"""

from __future__ import annotations

import json

import pytest

from .. import model as MM
from ..adapters.housing import from_housing
from ..placement import masonry as M

CAP = 4.5


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _wall(storey, a, b, t=0.23, role=MM.WallRole.INTERIOR, openings=()):
    orient = "h" if abs(a[1] - b[1]) < 1e-9 else "v"
    pos = a[1] if orient == "h" else a[0]
    start = min(a[0], b[0]) if orient == "h" else min(a[1], b[1])
    return MM.WallLine(
        id=MM.wall_id(storey, orient, pos, start),
        storey=storey,
        a=a,
        b=b,
        thickness_m=t,
        role=role,
        openings=list(openings),
    )


def _opening(wall, index, offset, width, head=2.1, sill=0.9, kind=MM.OpeningKind.WINDOW):
    return MM.Opening(
        id=MM.opening_id(wall.id, index),
        kind=kind,
        offset_m=offset,
        width_m=width,
        sill_m=sill,
        head_m=head,
        provenance=MM.Provenance.DRESSED,
    )


def _model(storeys=2, roof="gable", w=9.0, h=12.0, interior_t=0.23, interiors=True, core=False):
    """A rectangular plot with a 4.5 m module of interior walls."""
    model = MM.StructuralModel(id="syn", source=MM.ModelSource.HOUSING)
    height = 3.0
    for index in range(storeys):
        model.storeys.append(
            MM.Storey(index=index, name="S%d" % index, bottom_z_m=index * height, height_m=height)
        )
    model.meta["roof"] = {"type": roof, "rise_ratio": 0.25 if roof == "shed" else 0.3}
    for index in range(storeys):
        ext = MM.WallRole.EXTERIOR
        walls = [
            _wall(index, (0.0, 0.0), (w, 0.0), role=ext),
            _wall(index, (0.0, h), (w, h), role=ext),
            _wall(index, (0.0, 0.0), (0.0, h), role=ext),
            _wall(index, (w, 0.0), (w, h), role=ext),
        ]
        if interiors:
            walls.extend(
                [
                    _wall(index, (0.0, 4.0), (w, 4.0), t=interior_t),
                    _wall(index, (0.0, 8.0), (w, 8.0), t=interior_t),
                    _wall(index, (0.5 * w, 0.0), (0.5 * w, h), t=interior_t),
                ]
            )
        model.walls.extend(walls)
        model.rooms.append(
            MM.RoomPoly(
                id=MM.room_id(index, "all"),
                storey=index,
                name="Unit",
                occupancy=MM.Occupancy.HABITABLE,
                polygon=[(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)],
                area_m2=w * h,
            )
        )
    if core:
        model.cores.append(
            MM.Core(
                id=MM.core_id("stair"),
                kind=MM.CoreKind.STAIRS,
                x_m=6.0,
                y_m=9.0,
                w_m=2.0,
                h_m=2.5,
                storeys=list(range(storeys)),
            )
        )
    return model


def _thin_interior_model(storeys=2):
    """Perimeter 230, interiors 150: the wall census row 5 case."""
    model = _model(storeys=storeys, interiors=False)
    for index in range(storeys):
        for y in (3.0, 6.0, 9.0):
            model.walls.append(_wall(index, (0.0, y), (9.0, y), t=0.15))
        for x in (3.0, 6.0):
            model.walls.append(_wall(index, (x, 0.0), (x, 12.0), t=0.15))
    return model


def _housing_model():
    """The shipped housing fixture through the real adapter, windows assumed on."""
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fixtures", "housing_2storey.json"), "r", encoding="utf-8") as handle:
        design = json.load(handle)
    return from_housing(design, assume_windows=True)[0]


def _place(model, **kwargs):
    return M.place(model, M.MasonryParams(**kwargs))


# ---------------------------------------------------------------------------
# choose_system: the seven row decision table
# ---------------------------------------------------------------------------


def test_category_comes_from_the_zone_and_is_traced():
    model = _model()
    decision = M.choose_system(model, M.MasonryParams(zone="V"))
    assert decision.category == "E"
    assert any("IS 4326 Table 1" in line and "zone V" in line for line in decision.trace)


def test_category_override_is_honoured():
    model = _model()
    decision = M.choose_system(model, M.MasonryParams(category="b"))
    assert decision.category == "B"
    assert any("request override" in line for line in decision.trace)


def test_category_override_must_be_a_real_category():
    with pytest.raises(ValueError):
        M.choose_system(_model(), M.MasonryParams(category="Z"))


def test_row_one_honours_a_legal_override():
    decision = M.choose_system(_model(), M.MasonryParams(system="load_bearing_masonry", zone="III"))
    assert decision.system == "load_bearing_masonry"
    assert decision.refused is None
    assert decision.labeled is False
    assert any(line.startswith("row 1:") for line in decision.trace)


def test_row_one_ignores_a_system_outside_the_frozen_vocabulary():
    decision = M.choose_system(_model(), M.MasonryParams(system="steel_frame"))
    assert decision.requested == "auto"
    assert any("not in the frozen vocabulary" in line for line in decision.trace)


def test_row_two_refuses_four_storey_masonry_in_category_e():
    model = _model(storeys=4)
    decision = M.choose_system(model, M.MasonryParams(system="load_bearing_masonry", zone="V"))
    assert decision.category == "E"
    assert decision.system == "rc_frame"
    assert decision.labeled is True
    assert decision.refused is not None
    assert decision.refused.code == "E_MASONRY_LIMIT"
    assert "IS4326" in decision.refused.clause
    assert "4 storeys" in decision.refused.reason
    assert any(line.startswith("row 2:") for line in decision.trace)
    # the fallback is produced in the same call: never an empty batch
    assert decision.to_dict()["system_used"] == "rc_frame"
    assert decision.to_dict()["system_requested"] == "load_bearing_masonry"


def test_row_two_does_not_fire_below_the_cap():
    decision = M.choose_system(
        _model(storeys=3), M.MasonryParams(system="load_bearing_masonry", zone="V")
    )
    assert decision.system == "load_bearing_masonry"
    assert decision.refused is None


def test_row_three_needs_promotion_disallowed_to_fire():
    model = _model(interiors=False)
    for wall in model.walls:
        if wall.role == MM.WallRole.EXTERIOR and abs(wall.a[0] - wall.b[0]) < 1e-9:
            wall.thickness_m = 0.10  # no eligible line running in y at all
    decision = M.choose_system(model, M.MasonryParams(allow_promote=False))
    assert decision.system == "rc_frame"
    assert any(line.startswith("row 3:") and "running in v" in line for line in decision.trace)


def test_row_four_picks_load_bearing_masonry_when_the_cover_closes():
    decision = M.choose_system(_model(), M.MasonryParams(zone="IV"))
    assert decision.system == "load_bearing_masonry"
    assert any(line.startswith("row 4:") and "closes the cover" in line for line in decision.trace)


def test_row_five_picks_confined_when_the_census_is_dominated_by_thin_walls():
    decision = M.choose_system(_thin_interior_model(), M.MasonryParams())
    assert decision.system == "confined_masonry"
    assert any(line.startswith("row 5:") for line in decision.trace)


def test_row_six_thick_perimeter_thin_interior():
    decision = M.choose_system(_housing_model(), M.MasonryParams())
    assert decision.system == "confined_masonry"
    assert any(line.startswith("row 6:") and "115 mm" in line for line in decision.trace)


def test_row_six_falls_to_rc_frame_above_two_storeys():
    model = _model(storeys=3, interior_t=0.10)
    decision = M.choose_system(model, M.MasonryParams())
    assert decision.system == "rc_frame"
    assert any(line.startswith("row 6:") and "past the" in line for line in decision.trace)


# ---------------------------------------------------------------------------
# eligibility invariants (spec 4 and the spec 13 property)
# ---------------------------------------------------------------------------


def test_no_thin_wall_and_no_floating_wall_ever_bears():
    for model in (_model(), _thin_interior_model(), _housing_model(), _model(interior_t=0.10)):
        placement = M.place(model)
        by_id = {wall.id: wall for wall in model.walls}
        stacks = {}
        for stack in model.build_wall_stacks():
            for wall_id in stack["walls"].values():
                stacks[wall_id] = stack
        for wall_id in placement.bearing_walls:
            wall = by_id[wall_id]
            assert wall.thickness_m * 1000.0 > 115.0
            assert stacks[wall_id]["grounded"] is True
            present = set(int(s) for s in stacks[wall_id]["walls"])
            assert set(range(0, wall.storey + 1)).issubset(present)


def test_slenderness_screen_is_reported_per_wall():
    placement = _place(_model(), zone="IV")
    row = placement.per_wall_reports[0]
    screen = [check for check in row.checks if check["check"] == "SR"][0]
    assert screen["clause_id"] == "IS1905:1987 Cl 5.2"
    assert screen["limit"] == 27.0
    assert screen["ok"] is True
    # 0.75 x 3.0 / 0.23 = 9.78
    assert abs(screen["value"] - 9.7826) < 1e-3


# ---------------------------------------------------------------------------
# greedy cover
# ---------------------------------------------------------------------------


def test_cover_is_complete_on_the_all_230_model():
    placement = _place(_model(), zone="IV")
    assert placement.system.system == "load_bearing_masonry"
    assert placement.cover_gaps == []
    assert placement.panels
    for panel in placement.panels:
        assert panel.needs(CAP) == []
        assert panel.unsupported_m == pytest.approx(0.0, abs=1e-9)
        assert panel.short_span_m <= CAP + 1e-9


def test_cover_holds_both_directions_on_every_storey():
    model = _model()
    placement = _place(model, zone="IV")
    for storey in (0, 1):
        on_storey = [wall for wall in model.walls if wall.storey == storey]
        ok, why = M._both_directions(on_storey, placement.bearing_walls, storey)
        assert ok, why


def test_perimeter_is_seeded_bearing():
    model = _model()
    placement = _place(model, zone="IV")
    perimeter = [
        wall.id for wall in model.walls if wall.role == MM.WallRole.EXTERIOR
    ]
    assert set(perimeter).issubset(set(placement.bearing_walls))
    assert any("seeded" in line for line in placement.trace)


def test_cross_wall_gap_injects_a_pilaster_when_no_wall_can_be_promoted():
    model = _model(h=20.0, interiors=False)
    for index in (0, 1):
        model.walls.append(_wall(index, (4.5, 0.0), (4.5, 20.0)))
    placement = _place(model, zone="IV")
    assert placement.cover_gaps == []
    assert placement.pilasters, "a 20 m run with no cross wall must take a pilaster"
    pilaster = placement.pilasters[0]
    assert pilaster.projection_mm == pytest.approx(3.0 * 230.0)
    assert "W_RELEASED_CAP" in [entry.code for entry in placement.warnings]


def test_cross_wall_gap_prefers_promoting_a_wall_over_a_pilaster():
    model = _model()
    placement = _place(model, zone="IV")
    assert placement.pilasters == []
    assert any("cross wall spacing" in line and "promoted" in line for line in placement.trace)


# ---------------------------------------------------------------------------
# the housing fixture: the disclosed thin-interior outcome
# ---------------------------------------------------------------------------


def test_housing_fixture_discloses_the_thin_interior_rule():
    model = _housing_model()
    placement = M.place(model)
    # the perimeter is 0.75 ft and bears; every interior wall is four inches and
    # can never bear, so rule 7.4 replaces their support with RC beam lines and
    # the system escalates when even that cannot close the cover
    assert any("rule 7.4" in line and "can never bear" in line for line in placement.trace)
    assert placement.system.refused is not None
    assert "escalated to" in placement.system.refused.reason
    assert placement.system.labeled is True
    assert placement.system.system == "rc_frame"
    # the ladder describes the shipped result, so it carries the escalation and
    # not the beam lines of the attempt that was abandoned; the trace keeps those
    assert "E_SPAN_OVER_MAX" in [entry.code for entry in placement.warnings]
    assert "W_TERTIARY" not in [entry.code for entry in placement.warnings]
    assert placement.hybrid_beams == []


def test_a_hybrid_beam_line_that_does_close_the_cover_is_kept_and_disclosed():
    # ground storey solved by masonry, upper storey needing a wall that floats:
    # rule 7.5 puts an RC beam line on its axis and the system stands
    model = _model(w=8.0, h=12.0, interiors=False)
    model.walls.append(_wall(0, (0.0, 4.0), (8.0, 4.0)))
    model.walls.append(_wall(0, (0.0, 8.0), (8.0, 8.0)))
    floating = _wall(1, (4.0, 0.0), (4.0, 12.0))
    model.walls.append(floating)
    placement = M.place(model, M.MasonryParams(system="load_bearing_masonry", zone="IV"))
    assert placement.system.system == "load_bearing_masonry"
    assert placement.cover_gaps == []
    assert any("rule 7.5" in line and "does not stack to the ground" in line for line in placement.trace)
    assert "W_TERTIARY" in [entry.code for entry in placement.warnings]
    assert len(placement.hybrid_beams) == 1
    beam = placement.hybrid_beams[0]
    assert beam.storey == 1
    assert beam.supports_wall_id == floating.id
    assert beam.a == (4.0, 0.0) and beam.b == (4.0, 12.0)
    assert floating.id not in placement.bearing_walls
    # the beam line carries tie columns at its ends and at most 4.5 m apart
    ends = sorted(tie.y_m for tie in placement.tie_columns if abs(tie.x_m - 4.0) < 1e-9)
    assert ends[0] == pytest.approx(0.0)
    assert ends[-1] == pytest.approx(12.0)
    assert max(b - a for a, b in zip(ends, ends[1:])) <= 4.5 + 1e-9


def test_housing_fixture_still_schedules_infill_lintels():
    placement = M.place(_housing_model())
    assert placement.system.system == "rc_frame"
    assert placement.bands == []
    assert placement.vertical_bars == []
    assert placement.lintel_schedule, "finding 40: infill openings still take lintels"
    assert all(row.depth_mm >= 150.0 for row in placement.lintel_schedule)


def test_housing_fixture_labels_assumed_openings():
    model = _housing_model()
    placement = M.place(model)
    rows = [row for row in placement.per_wall_reports if row.assumed_openings]
    assert rows, "the housing adapter synthesizes doors, so some rows must be labeled"


def test_resolve_fixpoint_terminates_within_three_passes():
    for model in (_housing_model(), _model(interior_t=0.10), _thin_interior_model()):
        placement = M.place(model)
        passes = [line for line in placement.trace if line.startswith("resolve pass")]
        completed = [line for line in passes if "complete" in line]
        assert len(completed) <= 3


# ---------------------------------------------------------------------------
# IS 4326 Table 4 and the demote / strengthen policy
# ---------------------------------------------------------------------------


def _model_with_corner_opening():
    model = _model()
    north = [wall for wall in model.walls if wall.storey == 0 and wall.a == (0.0, 0.0) and wall.b == (9.0, 0.0)][0]
    north.openings.append(_opening(north, 0, offset=0.8, width=1.2))
    return model, north


def test_table_four_corner_breach_triggers_strengthen_with_jamb_columns():
    model, north = _model_with_corner_opening()
    placement = _place(model, zone="IV")  # category D wants 450 mm to the corner
    assert north.id in placement.bearing_walls, "a needed wall is strengthened, not demoted"
    resolved = [row for row in placement.violations_resolved if row["wall_id"] == north.id]
    assert resolved and resolved[0]["action"] == "STRENGTHENED"
    assert resolved[0]["checks"] == ["b5_corner"]
    assert resolved[0]["tie_columns"] == 2
    jambs = [tie for tie in placement.tie_columns if "jamb" in tie.reason]
    assert {round(tie.x_m, 3) for tie in jambs} == {0.2, 1.4}
    assert all(tie.w_mm == 230.0 for tie in jambs)


def test_strengthened_wall_report_carries_the_clause_and_the_remedies():
    model, north = _model_with_corner_opening()
    placement = _place(model, zone="IV")
    row = [r for r in placement.per_wall_reports if r.wall_id == north.id][0]
    assert row.action == "STRENGTHENED"
    breach = [check for check in row.checks if check["check"] == "b5_corner"][0]
    assert breach["clause_id"] == "IS4326:1993 Table 4"
    assert breach["limit"] == pytest.approx(0.45)
    assert breach["value"] == pytest.approx(0.2)
    assert breach["resolved_by"] == "STRENGTHENED"
    assert len(breach["remedies"]) == 3


def test_category_a_is_exempt_from_table_four():
    model, north = _model_with_corner_opening()
    placement = _place(model, category="A")
    row = [r for r in placement.per_wall_reports if r.wall_id == north.id][0]
    statuses = [check.get("status") for check in row.checks]
    assert "EXEMPT" in statuses
    assert placement.violations_resolved == []


def test_a_wall_with_no_openings_reports_not_run_rather_than_pass():
    placement = _place(_model(), zone="IV")
    row = [r for r in placement.per_wall_reports if r.wall_id in placement.bearing_walls][0]
    table4 = [check for check in row.checks if check["check"] == "table_4"]
    assert table4 and table4[0]["status"] == "NOT-RUN"
    assert table4[0]["ok"] is None


def test_redundant_wall_with_a_breach_is_demoted_not_strengthened():
    # a fourth interior line the cover does not need; give it a corner breach
    model = _model()
    for index in (0, 1):
        extra = _wall(index, (0.0, 10.0), (9.0, 10.0))
        extra.openings.append(_opening(extra, 0, offset=0.8, width=1.2))
        model.walls.append(extra)
    placement = _place(model, zone="IV")
    demoted = {row["wall_id"] for row in placement.demoted}
    assert demoted or placement.violations_resolved == []
    for row in placement.demoted:
        assert row["rule"].startswith("7.1")
        assert row["wall_id"] not in placement.bearing_walls


# ---------------------------------------------------------------------------
# promotion is advisory, never a geometry edit
# ---------------------------------------------------------------------------


def test_thickness_promotion_is_a_request_and_leaves_the_plan_alone():
    model = _model(interior_t=0.15)
    before = {wall.id: wall.thickness_m for wall in model.walls}
    placement = M.place(model, M.MasonryParams(system="load_bearing_masonry", zone="III"))
    assert placement.promoted, "a 150 mm wall the cover needs must raise a change request"
    request = placement.promoted[0]
    assert request.field == "thickness_mm"
    assert request.current_mm == pytest.approx(150.0)
    assert request.requested_mm == pytest.approx(230.0)
    assert {wall.id: wall.thickness_m for wall in model.walls} == before
    assert "W_RELEASED_CAP" in [entry.code for entry in placement.warnings]


def test_promotion_is_refused_when_allow_promote_is_off():
    model = _model(interior_t=0.15)
    placement = M.place(
        model, M.MasonryParams(system="load_bearing_masonry", zone="III", allow_promote=False)
    )
    assert placement.promoted == []


# ---------------------------------------------------------------------------
# bands
# ---------------------------------------------------------------------------


def _band(placement, kind, storey=None):
    rows = [row for row in placement.band_schedule if row.kind == kind]
    if storey is not None:
        rows = [row for row in rows if row.storey == storey]
    return rows


def test_lintel_band_is_a_closed_loop_on_every_storey():
    placement = _place(_model(), zone="IV")
    for storey in (0, 1):
        rows = _band(placement, "lintel", storey)
        assert len(rows) == 1
        assert rows[0].closed_loop is True
        assert rows[0].open_ends == []
        assert rows[0].spec["bar_dia_mm"] >= 8
        assert rows[0].spec["concrete_grade"] == "M20"
    assert {band.id for band in placement.bands} >= {"band-lintel-s0", "band-lintel-s1"}


def test_gable_band_on_a_gable_roof_and_none_on_a_hip():
    gable = _place(_model(roof="gable"), zone="IV")
    hip = _place(_model(roof="hip"), zone="IV")
    rows = _band(gable, "gable")
    assert len(rows) == 1
    assert len(rows[0].wall_ids) == 2, "a gable has two raking end walls"
    assert rows[0].level_m > _band(gable, "roof")[0].level_m
    assert _band(hip, "gable") == []
    assert any("no raking end wall" in line for line in hip.trace)


def test_shed_roof_bands_the_single_high_end_wall():
    shed = _place(_model(roof="shed"), zone="IV")
    rows = _band(shed, "gable")
    assert len(rows) == 1
    assert len(rows[0].wall_ids) == 1


def test_flat_roof_omits_the_roof_band_with_the_code_exception_disclosed():
    flat = _place(_model(roof="flat"), zone="IV")
    row = _band(flat, "roof")[0]
    assert row.spec is None
    assert row.wall_ids == []
    assert "Cl 8.4.6" in row.note
    assert any("roof band" in line and "omitted" in line for line in flat.trace)


def test_precast_flat_roof_puts_the_band_back():
    flat = _place(_model(roof="flat"), zone="IV", cast_in_situ_slab=False)
    row = _band(flat, "roof")[0]
    assert row.spec is not None
    assert row.wall_ids


def test_plinth_band_is_mandatory_in_category_d_and_recommended_in_c():
    strong = _place(_model(), zone="IV")
    mild = _place(_model(), zone="III")
    assert _band(strong, "plinth")[0].spec is not None
    assert _band(mild, "plinth")[0].spec is None
    assert "recommended, not required" in _band(mild, "plinth")[0].note


def test_soft_soil_forces_the_plinth_band():
    mild = _place(_model(), zone="III", soil={"soft": True})
    assert _band(mild, "plinth")[0].spec is not None
    assert "soft or filled soil" in _band(mild, "plinth")[0].note


# ---------------------------------------------------------------------------
# lintels
# ---------------------------------------------------------------------------


def _model_with_lintels():
    model = _model()
    south = [w for w in model.walls if w.storey == 0 and w.a == (0.0, 12.0)][0]
    south.openings.append(_opening(south, 0, offset=2.0, width=1.2, head=2.1))
    south.openings.append(_opening(south, 1, offset=6.0, width=1.2, head=2.1))
    south.openings.append(_opening(south, 2, offset=8.0, width=0.8, head=1.2))
    east = [w for w in model.walls if w.storey == 0 and w.a == (9.0, 0.0)][0]
    east.openings.append(_opening(east, 0, offset=3.0, width=0.9, head=2.1))
    east.openings.append(_opening(east, 1, offset=4.1, width=0.9, head=2.1))
    return model, south, east


def test_openings_at_band_level_are_absorbed_and_the_odd_one_gets_a_lintel():
    model, south, _east = _model_with_lintels()
    placement = _place(model, zone="IV")
    ids = {row.opening_ids[0] for row in placement.lintel_schedule}
    assert south.openings[2].id in ids, "the 1.2 m head sits 900 mm below the band"
    assert south.openings[0].id not in ids
    assert any("absorbed into the band" in line for line in placement.trace)


def test_lintel_depth_and_bearing_follow_the_rule():
    model, south, _east = _model_with_lintels()
    placement = _place(model, zone="IV")
    row = [r for r in placement.lintel_schedule if r.opening_ids == [south.openings[2].id]][0]
    assert row.clear_span_m == pytest.approx(0.8)
    assert row.depth_mm == 150.0  # 800/12 = 67 -> the 150 mm floor governs
    assert row.bearing_mm == 115.0  # under 0.9 m, the reduced seating is admitted
    assert "115 mm seating admitted" in row.note


def test_adjacent_lintels_within_the_tolerance_merge_into_one_run():
    model = _model()
    # three heads at 2.1 make that the modal band level, so the pair at 1.2 is
    # not absorbed and has to merge into a single run instead
    south = [w for w in model.walls if w.storey == 0 and w.a == (0.0, 12.0)][0]
    for index, offset in enumerate((1.0, 4.0, 7.0)):
        south.openings.append(_opening(south, index, offset=offset, width=1.0, head=2.1))
    east = [w for w in model.walls if w.storey == 0 and w.a == (9.0, 0.0)][0]
    east.openings.append(_opening(east, 0, offset=3.0, width=0.9, head=1.2))
    east.openings.append(_opening(east, 1, offset=4.1, width=0.9, head=1.2))
    placement = _place(model, zone="IV")
    rows = [r for r in placement.lintel_schedule if r.wall_id == east.id]
    assert len(rows) == 1
    assert rows[0].merged is True
    assert sorted(rows[0].opening_ids) == sorted([east.openings[0].id, east.openings[1].id])
    assert rows[0].clear_span_m == pytest.approx(2.0)  # 2.55 - 0.55


# ---------------------------------------------------------------------------
# vertical steel and tie columns
# ---------------------------------------------------------------------------


def test_vertical_bars_sit_at_every_corner_and_junction_for_category_d():
    model = _model()
    placement = _place(model, zone="IV")
    assert placement.system.category == "D"
    points = {(round(bar.x_m, 3), round(bar.y_m, 3)) for bar in placement.vertical_bars}
    for corner in ((0.0, 0.0), (9.0, 0.0), (0.0, 12.0), (9.0, 12.0)):
        assert corner in points
    for junction in ((4.5, 0.0), (4.5, 4.0), (4.5, 12.0), (0.0, 4.0), (9.0, 4.0)):
        assert junction in points
    assert {bar.position for bar in placement.vertical_bars} <= {"corner", "junction", "jamb"}
    # Printed IS 4326:1993 Table 7 gives a two storey category D stack 12 mm at
    # the bottom storey and 10 mm at the top, so the bars no longer merge into
    # one full height run of a single diameter. Corrected against the print on
    # 2026-08-30 (task J4); this used to read 10 mm from storey 0 to storey 1.
    by_storey = {}
    for bar in placement.vertical_bars:
        assert bar.from_storey == bar.to_storey, "one run per storey once the dias differ"
        by_storey.setdefault(bar.from_storey, set()).add(bar.dia_mm)
    assert by_storey == {0: {12}, 1: {10}}
    assert all(bar.clause == "IS4326:1993 Table 7" for bar in placement.vertical_bars)


def test_category_c_takes_no_table_seven_bars_below_three_storeys():
    # Corrected against the print on 2026-08-30 (task J4). The printed
    # IS 4326:1993 Table 7 gives category C "Nil" for both the one and the two
    # storey rows; its first bars appear at three storeys. This file used to
    # carry 10 mm for C at every row, so this test used to expect corner and
    # junction bars here.
    #
    # KNOWN GAP recorded with that correction: the Cl 8.3.3 strengthen remedy
    # takes its jamb bar diameter from Table 7, so with C now Nil it places no
    # jamb_strengthen bar either, while the resolution detail string still
    # names one. The wall is still strengthened, by the two RC tie columns the
    # same remedy places, which is asserted below. Closing the gap is a change
    # in placement/masonry.py, not in this data.
    model, _north = _model_with_corner_opening()
    placement = _place(model, zone="III")
    assert placement.system.category == "C"
    assert placement.vertical_bars == []
    resolved = placement.violations_resolved
    assert [row["action"] for row in resolved] == ["STRENGTHENED"]
    assert resolved[0]["tie_columns"] == 2


def test_categories_a_and_b_take_no_vertical_steel():
    placement = _place(_model(), zone="II")
    assert placement.system.category == "B"
    assert placement.vertical_bars == []
    assert any("takes none from IS 4326 Table 7" in line for line in placement.trace)


def test_confined_system_ties_every_corner_and_junction():
    model = _model()
    placement = M.place(model, M.MasonryParams(system="confined_masonry", zone="IV"))
    assert placement.system.system == "confined_masonry"
    points = {(round(tie.x_m, 3), round(tie.y_m, 3)) for tie in placement.tie_columns}
    for corner in ((0.0, 0.0), (9.0, 0.0), (0.0, 12.0), (9.0, 12.0)):
        assert corner in points
    assert all(tie.w_mm == 230.0 for tie in placement.tie_columns)
    assert any("confined masonry baseline" in tie.reason for tie in placement.tie_columns)


def test_confined_system_breaks_a_long_panel_with_an_intermediate_tie():
    model = _model(h=20.0, interiors=False)
    for index in (0, 1):
        model.walls.append(_wall(index, (4.5, 0.0), (4.5, 20.0)))
    placement = M.place(model, M.MasonryParams(system="confined_masonry", zone="IV"))
    intermediate = [tie for tie in placement.tie_columns if "unconfined panel length" in tie.reason]
    assert intermediate, "a 20 m run must be broken into 4.5 m panels"
    cap = M.MasonryParams().confined_panel_cap(3.0)
    assert cap == pytest.approx(4.5)


def test_core_corners_are_always_tied():
    model = _model(core=True)
    placement = _place(model, zone="IV")
    core_ties = [tie for tie in placement.tie_columns if "core corner" in tie.reason]
    assert len(core_ties) == 4
    points = {(round(tie.x_m, 3), round(tie.y_m, 3)) for tie in core_ties}
    assert points == {(6.0, 9.0), (8.0, 9.0), (6.0, 11.5), (8.0, 11.5)}


def test_a_four_storey_stack_says_table_seven_has_no_row_for_it():
    # categories A to D admit 4 storeys, but Table 7 is transcribed to 3, so the
    # bars are not invented and the gap is disclosed rather than passed over
    model = _model(storeys=4)
    placement = M.place(model, M.MasonryParams(system="load_bearing_masonry", zone="IV"))
    assert placement.system.system == "load_bearing_masonry"
    assert placement.vertical_bars == []
    assert "W_TALL" in [entry.code for entry in placement.warnings]
    assert any("vertical steel not scheduled" in line for line in placement.trace)


def test_a_wall_promoted_for_cross_wall_spacing_still_meets_table_four():
    # the y = 4 line is not needed for the cover; the cross wall spacing pass
    # promotes it afterwards, and its 300 mm pier must still be caught
    model = _model()
    late = [w for w in model.walls if w.storey == 0 and w.a == (0.0, 4.0)][0]
    late.openings.append(_opening(late, 0, offset=1.0, width=1.0))
    late.openings.append(_opening(late, 1, offset=2.3, width=1.0))
    placement = _place(model, zone="IV")
    assert late.id in placement.bearing_walls
    resolved = [row for row in placement.violations_resolved if row["wall_id"] == late.id]
    assert resolved and resolved[0]["action"] == "STRENGTHENED"
    assert "b4_pier" in resolved[0]["checks"]
    row = [r for r in placement.per_wall_reports if r.wall_id == late.id][0]
    breach = [check for check in row.checks if check["check"] == "b4_pier"][0]
    assert breach["value"] == pytest.approx(0.3)
    # Printed IS 4326:1993 Table 4 row 3, the "D and E" column: the minimum
    # pier width b4 is 560 mm, not the 450 this file used to carry.
    # Corrected against the print on 2026-08-30 (task J4).
    assert breach["limit"] == pytest.approx(0.56)
    assert breach["resolved_by"] == "STRENGTHENED"


def test_an_interior_wall_running_into_a_t_junction_skips_the_corner_rule():
    model = _model()
    interior = [w for w in model.walls if w.storey == 0 and w.a == (0.0, 4.0)][0]
    interior.openings.append(_opening(interior, 0, offset=0.8, width=1.2))
    placement = _place(model, zone="IV")
    row = [r for r in placement.per_wall_reports if r.wall_id == interior.id][0]
    assert [check for check in row.checks if check["check"] == "b5_corner"] == []


def test_lintels_for_infill_is_the_frame_path_entry_point():
    model, south, east = _model_with_lintels()
    elements, rows = M.lintels_for_infill(model)
    assert len(rows) == len(elements)
    covered = {opening_id for row in rows for opening_id in row.opening_ids}
    # no band in a frame, so nothing is absorbed: every opening is covered
    assert covered == {opening.id for opening in south.openings + east.openings}
    only_south = M.lintels_for_infill(model, wall_ids=[south.id])[1]
    assert {row.wall_id for row in only_south} == {south.id}


def test_point_load_hook_is_applied_by_the_caller_after_takedown():
    model = _model(core=True)
    placement = _place(model, zone="IV")
    before = len(placement.tie_columns)
    added = M.tie_columns_for_point_loads(
        placement,
        [
            {"x_m": 4.5, "y_m": 8.0, "p_kn": 40.0, "wall_id": "landing"},
            {"x_m": 4.5, "y_m": 4.0, "p_kn": 10.0},
        ],
        placement.params,
    )
    assert len(added) == 1
    assert added[0].x_m == pytest.approx(4.5)
    assert "point load" in added[0].reason
    assert len(placement.tie_columns) == before + 1
    assert M.POINT_LOAD_LIMIT_KN == 25.0


# ---------------------------------------------------------------------------
# write back and determinism
# ---------------------------------------------------------------------------


def test_write_back_puts_the_geometry_on_the_model_and_is_idempotent():
    model = _model(core=True)
    placement = _place(model, zone="IV")
    placement.write_back(model)
    assert model.system == MM.System.LOAD_BEARING_MASONRY
    assert [band.id for band in model.bands] == sorted(band.id for band in model.bands)
    assert all(band.placed_by == M.PLACED_BY for band in model.bands)
    assert all(column.placed_by == M.PLACED_BY for column in model.columns)
    assert model.validate() == []
    bearing = set(placement.bearing_walls)
    assert all(wall.bearing == (wall.id in bearing) for wall in model.walls)
    first = json.dumps(model.to_dict(), sort_keys=True)
    _place(model, zone="IV").write_back(model)
    assert json.dumps(model.to_dict(), sort_keys=True) == first


def test_placement_output_is_byte_identical_on_a_repeat_run():
    for model in (_model(), _model(roof="hip"), _housing_model(), _thin_interior_model()):
        first = json.dumps(M.place(model).to_dict(), sort_keys=True)
        second = json.dumps(M.place(model).to_dict(), sort_keys=True)
        assert first == second


def test_every_disclosure_code_is_registered():
    for model in (_model(), _housing_model(), _model(interior_t=0.15), _thin_interior_model()):
        for entry in M.place(model).warnings:
            assert entry.code in MM.REGISTRY
            assert entry.severity == MM.REGISTRY[entry.code][0]


# ---------------------------------------------------------------------------
# findings C3, B5, B6: rule ordering, cover freshness, the row 6b dry run
# ---------------------------------------------------------------------------


def _floating_wall_model(t=0.23):
    """The rule 7.5 fixture with the floating wall's thickness a parameter."""
    model = _model(w=8.0, h=12.0, interiors=False)
    model.walls.append(_wall(0, (0.0, 4.0), (8.0, 4.0)))
    model.walls.append(_wall(0, (0.0, 8.0), (8.0, 8.0)))
    floating = _wall(1, (4.0, 0.0), (4.0, 12.0), t=t)
    model.walls.append(floating)
    return model, floating


def test_an_ungrounded_thin_wall_takes_the_beam_line_not_a_dead_promotion():
    # finding C3: rule 7.3 used to fire before rule 7.5's stacked/grounded
    # screen, so lifting the ungrounded 150 mm wall was a no-op that removed it
    # from gap resolution, the gap stayed open and the system escalated to
    # confined_masonry with E_SPAN_OVER_MAX; the very next attempt closed the
    # same panel with the rule 7.5 beam line it refused to try under LBM
    model, floating = _floating_wall_model(t=0.15)
    placement = M.place(model, M.MasonryParams(system="load_bearing_masonry", zone="IV"))
    assert placement.system.system == "load_bearing_masonry"
    assert placement.system.refused is None
    assert placement.cover_gaps == []
    assert any("rule 7.5" in line and "does not stack to the ground" in line for line in placement.trace)
    assert len(placement.hybrid_beams) == 1
    assert placement.hybrid_beams[0].supports_wall_id == floating.id
    assert floating.id not in placement.bearing_walls
    assert placement.promoted == []
    assert not any(
        entry.code == "W_RELEASED_CAP" and "kept bearing" in entry.message for entry in placement.warnings
    )


def test_floating_wall_thickness_does_not_change_the_delivered_system():
    # finding C3's monotonicity contract: only the floating wall's thickness
    # varies, and both thicknesses take the same rule 7.5 beam line under
    # load bearing masonry
    thick, _ = _floating_wall_model(t=0.23)
    thin, _ = _floating_wall_model(t=0.15)
    at_230 = M.place(thick, M.MasonryParams(system="load_bearing_masonry", zone="IV"))
    at_150 = M.place(thin, M.MasonryParams(system="load_bearing_masonry", zone="IV"))
    assert at_230.system.system == at_150.system.system == "load_bearing_masonry"
    assert len(at_230.hybrid_beams) == len(at_150.hybrid_beams) == 1
    assert [tie.id for tie in at_230.tie_columns] == [tie.id for tie in at_150.tie_columns]


def _stale_cover_model():
    """Perimeter 230 and two stacked grounded 150 mm lines where ONE suffices."""
    model = _model(storeys=1, w=7.5, h=8.0, interiors=False)
    model.walls.append(_wall(0, (0.0, 4.0), (7.5, 4.0), t=0.15))
    model.walls.append(_wall(0, (0.0, 5.0), (7.5, 5.0), t=0.15))
    return model


def test_resolve_rounds_read_a_fresh_cover_so_one_lift_suffices():
    # finding B5: the 12 round loop used to re-run against the round-1 cover
    # snapshot, so the y=4 lift was invisible to round 2 and the y=5 wall was
    # lifted for a gap that was already closed; the fresh cover stops after one
    needed = MM.wall_id(0, "h", 4.0, 0.0)
    placement = M.place(_stale_cover_model(), M.MasonryParams(system="load_bearing_masonry", zone="III"))
    assert placement.system.system == "load_bearing_masonry"
    assert placement.cover_gaps == []
    assert [request.wall_id for request in placement.promoted] == [needed]
    assert needed in placement.bearing_walls
    releases = [
        entry for entry in placement.warnings if entry.code == "W_RELEASED_CAP" and "kept bearing" in entry.message
    ]
    assert [entry.element_ids for entry in releases] == [[needed]]


def test_promotion_requests_never_name_a_non_bearing_wall():
    # finding B5's report half: an un-honoured request used to survive into
    # placement.promoted and W_RELEASED_CAP beside a NON-BEARING report row
    for model in (_stale_cover_model(), _model(interior_t=0.15)):
        placement = M.place(model, M.MasonryParams(system="load_bearing_masonry", zone="III"))
        bearing = set(placement.bearing_walls)
        rows = {row.wall_id: row for row in placement.per_wall_reports}
        for request in placement.promoted:
            assert request.wall_id in bearing
            assert rows[request.wall_id].action == "PROMOTED-REQUEST"
        for entry in placement.warnings:
            if entry.code == "W_RELEASED_CAP" and "kept bearing" in entry.message:
                assert set(entry.element_ids) <= bearing


def test_finish_reconciles_an_orphan_promotion_request():
    # finding B5, belt and braces: whatever route leaves a lift out of the
    # final bearing set, the finish pass drops the request, its resolution row
    # and its W_RELEASED_CAP, and traces the drop; before the fix the method
    # did not exist and the orphan shipped
    placer = M.MasonryPlacer(M.MasonryParams())
    placer._trace = []
    placer._warnings = []
    placer._lifted = {"w-keep", "w-orphan"}
    placer._promoted = [
        M.GeometryChangeRequest(
            wall_id=name, storey=0, field="thickness_mm", current_mm=150.0, requested_mm=230.0, reason="rule 7.3"
        )
        for name in ("w-keep", "w-orphan")
    ]
    placer._resolved = [
        {"wall_id": name, "action": "PROMOTED-REQUEST", "rule": "7.3", "clause_id": "IS1905:1987 Cl 4.1"}
        for name in ("w-keep", "w-orphan")
    ]
    for name in ("w-keep", "w-orphan"):
        placer._warn(
            "W_RELEASED_CAP",
            "wall %s is kept bearing at 150 mm on the condition that it is built at 230 mm" % name,
            [name],
            clause="IS1905:1987 Cl 4.1",
        )
    placer._reconcile_promotions({0: ["w-keep"]})
    assert [request.wall_id for request in placer._promoted] == ["w-keep"]
    assert placer._lifted == {"w-keep"}
    assert [row["wall_id"] for row in placer._resolved] == ["w-keep"]
    named = [tuple(entry.element_ids) for entry in placer._warnings if entry.code == "W_RELEASED_CAP"]
    assert named == [("w-keep",)]
    assert any("w-orphan" in line and "dropped" in line for line in placer._trace)


def _census_hole_model(storeys=2):
    """Perimeter 230 with one 150 mm spine: a 21 percent confined share, the
    band between census rows 5 and 6 that finding B6 pins."""
    model = _model(storeys=storeys, w=9.0, h=8.0, interiors=False)
    for index in range(storeys):
        model.walls.append(_wall(index, (0.0, 4.0), (9.0, 4.0), t=0.15))
    return model


def test_row_6b_tries_confined_masonry_before_falling_to_rc_frame():
    # finding B6: with the confined share at 21 percent neither census row
    # fired and the table fell straight to rc_frame without asking whether
    # confined masonry closes the cover; it does, so it is delivered
    decision = M.choose_system(_census_hole_model(), M.MasonryParams())
    assert decision.system == "confined_masonry"
    assert decision.refused is None
    assert any(line.startswith("row 6b:") and "closes the cover" in line for line in decision.trace)
    placement = M.place(_census_hole_model(), M.MasonryParams())
    assert placement.system.system == "confined_masonry"
    assert placement.cover_gaps == []
    assert placement.bearing_walls


def test_row_6b_carries_the_census_storey_cap():
    # the census rows cap confined masonry at 3 storeys, and the new row must
    # not hand a 4 storey building what rows 5 and 6 would refuse; the refusal
    # to try is traced, never silent
    decision = M.choose_system(_census_hole_model(storeys=4), M.MasonryParams(zone="II"))
    assert decision.system == "rc_frame"
    assert any(line.startswith("row 6b:") and "past the 3 storey cap" in line for line in decision.trace)


def test_row_6b_discloses_when_confined_does_not_close_either():
    # a 230 mm spine keeps rows 5 and 6 quiet but leaves a 9 x 8 m panel that
    # no wall in any class can close: the confined dry run fails too, and the
    # trace says so before row 7 fires
    model = _model(storeys=2, w=9.0, h=12.0, interiors=False)
    for index in range(2):
        model.walls.append(_wall(index, (0.0, 4.0), (9.0, 4.0)))
    decision = M.choose_system(model, M.MasonryParams())
    assert decision.system == "rc_frame"
    assert any(line.startswith("row 6b:") and "does not close the cover" in line for line in decision.trace)
    assert any(line.startswith("row 7:") for line in decision.trace)
