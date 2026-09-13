"""Pins for placement/foundations.py: strips, pads, combined footings, straps.

Numbers here are hand checkable against spec 10 with sbc = 150 kPa:
B_strip = max(w / sbc, 2t, 0.45) rounded up to 50 mm, RC past 3t;
B_pad = max(sqrt(P / sbc), 1.0) snapped up to 150 mm.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from .. import api
from .. import model as MM
from ..design import rcc
from ..design.rcc import footings as FT
from ..placement import foundations as F

SBC = 150.0
SOIL = {"type": "II", "sbc_kpa": SBC, "soft": False, "founding_depth_m": 1.5}


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _wall(storey, a, b, t=0.23, role=MM.WallRole.INTERIOR):
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
    )


def _column(storey, x, y, size=0.23):
    return MM.Column(
        id=MM.column_id(storey, x_m=x, y_m=y),
        stack_id=MM.stack_id(x_m=x, y_m=y),
        storey=storey,
        x_m=x,
        y_m=y,
        width_m=size,
        depth_m=size,
    )


def _base(storeys=1):
    model = MM.StructuralModel(id="fdn", source=MM.ModelSource.HOUSING)
    for index in range(storeys):
        model.storeys.append(
            MM.Storey(index=index, name="S%d" % index, bottom_z_m=index * 3.0, height_m=3.0)
        )
    return model


def _rect_model(w=9.0, h=12.0, t=0.23, party=False):
    """A single storey rectangle with a mid wall in each direction."""
    model = _base()
    ext = MM.WallRole.EXTERIOR
    model.walls.extend(
        [
            _wall(0, (0.0, 0.0), (w, 0.0), t=t, role=ext),
            _wall(0, (0.0, h), (w, h), t=t, role=ext),
            _wall(0, (0.0, 0.0), (0.0, h), t=t, role=MM.WallRole.PARTY if party else ext),
            _wall(0, (w, 0.0), (w, h), t=t, role=ext),
            _wall(0, (0.5 * w, 0.0), (0.5 * w, h), t=t),
        ]
    )
    return model


def _bearing(model):
    return sorted(wall.id for wall in model.walls)


# ---------------------------------------------------------------------------
# soil
# ---------------------------------------------------------------------------


def test_soil_defaults_come_from_the_catalogue_and_are_disclosed():
    model = _rect_model()
    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=None)
    soil = plan.report["soil"]
    assert soil["type"] == "II"
    assert soil["founding_depth_m"] == 1.5  # finding 30: 1.5 m everywhere
    codes = [entry.code for entry in plan.warnings]
    assert "W_ASSUMED_SBC" in codes
    assert "W_ASSUMED_FOUNDING_DEPTH" in codes


def test_resolved_soil_round_trip_preserves_assumption_disclosures():
    model = _rect_model()
    resolved = api.resolve_soil(None)
    soil = F.Soil.from_params(resolved)
    assert soil.assumed == resolved["assumed"]

    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=resolved)
    codes = [entry.code for entry in plan.warnings]
    assert "W_ASSUMED_SBC" in codes
    assert "W_ASSUMED_FOUNDING_DEPTH" in codes


def test_supplied_soil_raises_no_assumption_warning():
    model = _rect_model()
    plan = F.layout_foundations(model, _bearing(model), [], {"x": 1.0}, {}, soil=SOIL)
    codes = [entry.code for entry in plan.warnings]
    assert "W_ASSUMED_SBC" not in codes
    assert "W_ASSUMED_FOUNDING_DEPTH" not in codes
    assert plan.report["soil"]["assumed"] == []


def test_soft_soil_type_carries_its_flag():
    soil = F.Soil.from_params({"type": "III"})
    assert soil.soft is True
    assert soil.sbc_kpa == pytest.approx(75.0)
    assert "sbc_kpa" in soil.assumed


# ---------------------------------------------------------------------------
# strips
# ---------------------------------------------------------------------------


def _strips(model, loads, soil=None):
    plan = F.layout_foundations(model, _bearing(model), [], loads, {}, soil=soil or SOIL)
    return plan, {strip.id: strip for strip in plan.strips}


def test_strip_width_sits_between_two_and_three_times_the_wall_thickness():
    model = _rect_model()
    plan, strips = _strips(model, {wall.id: 40.0 for wall in model.walls})
    assert strips
    for strip in strips.values():
        # 40 / 150 = 0.267 m of pressure demand, so 2t = 0.46 m governs
        assert strip.width_m == pytest.approx(0.50)
        assert strip.width_m >= 2.0 * strip.wall_t_m - 1e-9
        assert strip.width_m <= 3.0 * strip.wall_t_m + 1e-9
        assert strip.rc is False
        assert strip.depth_m == pytest.approx(1.5)


def test_strip_width_is_rounded_up_to_fifty_millimetres():
    model = _rect_model()
    _plan, strips = _strips(model, {wall.id: 100.0 for wall in model.walls})
    # 100 / 150 = 0.6667 -> 0.70
    for strip in strips.values():
        assert strip.width_m == pytest.approx(0.70)
        assert round(strip.width_m * 1000.0) % 50 == 0


def test_a_wide_strip_is_flagged_reinforced_concrete_past_three_t():
    model = _rect_model()
    _plan, strips = _strips(model, {wall.id: 150.0 for wall in model.walls})
    for strip in strips.values():
        assert strip.width_m == pytest.approx(1.00)
        assert strip.width_m > 3.0 * strip.wall_t_m
        assert strip.rc is True
        assert "reinforced concrete strip" in strip.note


def test_a_bare_geometric_minimum_never_drops_below_450_mm():
    model = _rect_model(t=0.115)
    # Missing reactions deliberately request disclosed geometric-minimum
    # markers.  An explicitly supplied zero is a non-positive service
    # reaction and must be refused by the compression-only foundation gate.
    _plan, strips = _strips(model, {})
    for strip in strips.values():
        assert strip.width_m == pytest.approx(0.45)


def test_collinear_walls_merge_into_one_strip():
    model = _base()
    model.walls.extend(
        [
            _wall(0, (0.0, 0.0), (4.0, 0.0)),
            _wall(0, (4.0, 0.0), (9.0, 0.0)),
            _wall(0, (0.0, 6.0), (9.0, 6.0)),
        ]
    )
    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=SOIL)
    runs = [strip for strip in plan.strips if strip.orient == "h" and abs(strip.pos_m) < 1e-9]
    assert len(runs) == 1
    assert runs[0].s0_m == pytest.approx(0.0)
    assert runs[0].s1_m == pytest.approx(9.0)
    assert len(runs[0].wall_ids) == 2


def test_strips_are_mitred_by_half_the_crossing_width():
    model = _rect_model()
    _plan, strips = _strips(model, {wall.id: 40.0 for wall in model.walls})
    strip = [s for s in strips.values() if s.orient == "h" and abs(s.pos_m) < 1e-9][0]
    assert strip.mitre_m == (pytest.approx(0.25), pytest.approx(0.25))
    assert strip.length_m() == pytest.approx(9.5)
    x, _y, w, _h = strip.rect()
    assert x == pytest.approx(-0.25)
    assert w == pytest.approx(9.5)


def test_a_missing_line_load_is_disclosed_not_taken_as_zero():
    model = _rect_model()
    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=SOIL)
    assert "W_RELEASED_CAP" in [entry.code for entry in plan.warnings]
    assert all(strip.load_source == "geometric_minimum" for strip in plan.strips)
    assert any("no line load" in strip.note for strip in plan.strips)


def test_the_stack_load_reaches_the_ground_strip():
    model = _rect_model()
    upper = []
    for wall in list(model.walls):
        clone = _wall(1, wall.a, wall.b, t=wall.thickness_m, role=wall.role)
        upper.append(clone)
    model.storeys.append(MM.Storey(index=1, name="S1", bottom_z_m=3.0, height_m=3.0))
    model.walls.extend(upper)
    # the takedown may key the cumulative load on any member of the stack
    loads = {upper[0].id: 90.0}
    plan = F.layout_foundations(model, _bearing(model), [], loads, {}, soil=SOIL)
    ground = [strip for strip in plan.strips if model.by_id(strip.wall_ids[0]).storey == 0]
    assert ground
    loaded = [strip for strip in ground if strip.w_service_kn_per_m > 0.0]
    assert loaded and loaded[0].w_service_kn_per_m == pytest.approx(90.0)


def test_a_party_wall_strip_is_flagged_eccentric():
    model = _rect_model(party=True)
    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=SOIL)
    party = [strip for strip in plan.strips if strip.eccentric]
    assert len(party) == 1
    strip = party[0]
    assert strip.e_m == pytest.approx(0.5 * strip.width_m)
    assert strip.pos_m == pytest.approx(0.5 * strip.width_m)
    assert strip.rect()[0] == pytest.approx(0.0), "the strip is flush inside the party line"
    assert "party wall" in strip.note
    assert "W_ECCENTRIC_COLUMN" in [entry.code for entry in plan.warnings]

    placed = next(footing for footing in model.footings if footing.id == strip.id)
    assert placed.eccentric is True
    assert placed.e_m == pytest.approx(strip.e_m)
    geometry = rcc.strip_geometry_from_model(placed, {wall.id: wall for wall in model.walls})
    assert geometry.eccentric is True
    assert geometry.e_m == pytest.approx(strip.e_m)


def test_an_adapter_demising_wall_is_not_invented_as_a_property_boundary():
    model = _rect_model(party=True)
    model.meta["foundation_party_boundary_wall_ids"] = []
    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=SOIL)
    assert not [strip for strip in plan.strips if strip.eccentric]
    assert "W_ECCENTRIC_COLUMN" not in [entry.code for entry in plan.warnings]


def test_post_design_audit_uses_resized_rectangles_for_overlap_and_boundaries():
    model = _base()
    model.meta["plot_bounds_m"] = [-1.0, -2.0, 5.0, 2.0]
    model.footings.extend([
        MM.Footing(
            id="F1", kind=MM.FootingKind.ISOLATED, supports=["C1"],
            x_m=0.0, y_m=0.0, w_m=1.0, h_m=1.0, depth_m=1.5,
        ),
        MM.Footing(
            id="F2", kind=MM.FootingKind.ISOLATED, supports=["C2"],
            x_m=2.0, y_m=0.0, w_m=1.0, h_m=1.0, depth_m=1.5,
        ),
    ])
    results = [
        SimpleNamespace(
            element_id="F1", element_type="footing", status="pass",
            section={"bx_mm": 2400.0, "ly_mm": 1800.0},
        ),
        SimpleNamespace(
            element_id="F2", element_type="footing", status="pass",
            section={"bx_mm": 2400.0, "ly_mm": 1800.0},
        ),
    ]
    log = MM.DisclosureLog()
    api._audit_designed_foundation_geometry(model, results, log)
    codes = [entry.code for entry in log.entries]
    assert "W_FOOTING_OVERLAP" in codes, "the 0.4 m resized overlap must be checked"
    assert "W_ECCENTRIC_COLUMN" in codes, "F1 grows past the explicit x=-1.0 m plot line"
    assert all(entry.stage == "api.design.foundation_geometry" for entry in log.entries)


# ---------------------------------------------------------------------------
# pads
# ---------------------------------------------------------------------------


def test_pad_side_is_sqrt_of_load_over_sbc_snapped_up_to_150_mm():
    model = _base()
    model.columns.append(_column(0, 3.0, 3.0))
    plan = F.layout_foundations(
        model, [], [model.columns[0].id], {}, {model.columns[0].id: 600.0}, soil=SOIL
    )
    assert len(plan.pads) == 1
    pad = plan.pads[0]
    # sqrt(600 / 150) = 2.0 -> snapped up to the next 150 mm
    assert pad.w_m == pytest.approx(2.1)
    assert pad.h_m == pytest.approx(pad.w_m)
    assert pad.depth_m == pytest.approx(1.5)
    assert pad.p_service_kn == pytest.approx(600.0)


def test_a_light_column_takes_the_one_metre_minimum():
    model = _base()
    model.columns.append(_column(0, 3.0, 3.0))
    plan = F.layout_foundations(
        model, [], [model.columns[0].id], {}, {model.columns[0].id: 100.0}, soil=SOIL
    )
    assert plan.pads[0].w_m == pytest.approx(1.05)


def test_a_pad_load_may_be_keyed_on_the_stack_id():
    model = _base(storeys=2)
    lower = _column(0, 3.0, 3.0)
    upper = _column(1, 3.0, 3.0)
    model.columns.extend([lower, upper])
    plan = F.layout_foundations(
        model, [], [lower.id, upper.id], {}, {lower.stack_id: 600.0}, soil=SOIL
    )
    assert len(plan.pads) == 1
    assert plan.pads[0].column_ids == sorted([lower.id, upper.id])
    assert plan.pads[0].w_m == pytest.approx(2.1)


def test_placed_founding_level_does_not_pin_rc_pad_or_combined_thickness():
    """The placement depth is excavation level; RCC owns pad section thickness."""
    generic_depth = FT.PadGeometry.from_mapping(
        {"element_id": "F-contract", "col_bx_mm": 230.0, "col_dy_mm": 230.0, "depth_m": 1.5}
    )
    explicit_thickness = FT.PadGeometry.from_mapping(
        {
            "element_id": "F-contract-explicit",
            "col_bx_mm": 230.0,
            "col_dy_mm": 230.0,
            "placed_thickness_m": 0.45,
        }
    )
    assert generic_depth.specified_thickness_m is None
    assert explicit_thickness.specified_thickness_m == pytest.approx(0.45)

    pad_model = _base()
    pad_column = _column(0, 3.0, 3.0)
    pad_model.columns.append(pad_column)
    pad_plan = F.layout_foundations(
        pad_model, [], [pad_column.id], {}, {pad_column.id: 600.0}, soil=SOIL
    )
    placed_pad = pad_plan.pads[0]
    pad_geometry = FT.PadGeometry.from_pad_footing(
        placed_pad,
        FT.ColumnStub(pad_column.id, 230.0, 230.0, x_m=pad_column.x_m, y_m=pad_column.y_m),
    )
    assert placed_pad.depth_m == pytest.approx(1.5)
    assert pad_geometry.specified_thickness_m is None
    pad_result = FT.design_footing(
        pad_geometry, FT.FootingLoads(p_service_kn=600.0), SOIL
    )
    assert 0.0 < pad_result.section["D_mm"] < placed_pad.depth_m * 1000.0

    combined_model = _base()
    left, right = _column(0, 2.0, 2.0), _column(0, 2.8, 2.0)
    combined_model.columns.extend([left, right])
    combined_plan = F.layout_foundations(
        combined_model, [], [left.id, right.id], {}, {left.id: 100.0, right.id: 300.0}, soil=SOIL
    )
    placed_combined = combined_plan.combined[0]
    combined_geometry = FT.CombinedGeometry.from_combined_footing(
        placed_combined,
        tuple(
            FT.ColumnStub(column.id, 230.0, 230.0, x_m=column.x_m, y_m=column.y_m)
            for column in (left, right)
        ),
    )
    assert placed_combined.depth_m == pytest.approx(1.5)
    assert combined_geometry.specified_thickness_m is None
    combined_result = FT.design_combined_footing(
        combined_geometry,
        [FT.FootingLoads(p_service_kn=100.0), FT.FootingLoads(p_service_kn=300.0)],
        SOIL,
    )
    assert 0.0 < combined_result.section["D_mm"] < placed_combined.depth_m * 1000.0


def test_a_missing_axial_load_is_disclosed():
    model = _base()
    model.columns.append(_column(0, 3.0, 3.0))
    plan = F.layout_foundations(model, [], [model.columns[0].id], {}, {}, soil=SOIL)
    assert plan.pads[0].load_source == "geometric_minimum"
    assert "W_RELEASED_CAP" in [entry.code for entry in plan.warnings]


# ---------------------------------------------------------------------------
# a column that lands on a strip
# ---------------------------------------------------------------------------


def test_a_column_on_a_strip_axis_widens_it_and_reaches_the_strip_designer(monkeypatch):
    model = _rect_model()
    column = _column(0, 4.5, 6.0)
    model.columns.append(column)
    plan = F.layout_foundations(
        model,
        _bearing(model),
        [column.id],
        {wall.id: 40.0 for wall in model.walls},
        {column.id: 600.0},
        soil=SOIL,
    )
    assert plan.pads == []
    hosts = [strip for strip in plan.strips if strip.widenings]
    assert len(hosts) == 1
    widening = hosts[0].widenings[0]
    assert widening.column_id == column.id
    assert widening.at_m == pytest.approx(6.0)
    assert widening.width_m == pytest.approx(2.1)
    assert widening.taper_m == pytest.approx(1.0)
    assert widening.effective_length_m > 0.0
    assert widening.line_load_kn_per_m == pytest.approx(600.0 / widening.effective_length_m)
    assert hosts[0].w_service_kn_per_m == pytest.approx(40.0 + widening.line_load_kn_per_m)
    assert "widened locally" in hosts[0].note
    assert any("lands on strip" in note for note in plan.report["notes"])

    placed = next(footing for footing in model.footings if footing.id == hosts[0].id)
    assert placed.w_service_kn_per_m == pytest.approx(hosts[0].w_service_kn_per_m)
    restored = MM.StructuralModel.from_dict(model.to_dict())
    restored_footing = next(footing for footing in restored.footings if footing.id == placed.id)
    assert restored_footing.w_service_kn_per_m == pytest.approx(placed.w_service_kn_per_m)

    captured = {}

    def fake_design(geometry, loads, soil, ctx):
        captured["load"] = loads.n_service_kn_per_m
        return SimpleNamespace(add_note=lambda _note: None)

    monkeypatch.setattr(rcc, "design_strip_footing", fake_design)
    rcc._design_one_strip(
        placed,
        {wall.id: wall for wall in model.walls},
        {wall.id: 40.0 for wall in model.walls},
        SOIL,
        None,
    )
    assert captured["load"] == pytest.approx(hosts[0].w_service_kn_per_m)


def test_a_column_off_the_strip_axis_keeps_its_own_pad():
    model = _rect_model()
    column = _column(0, 4.5 + 1.0, 6.0)
    model.columns.append(column)
    plan = F.layout_foundations(
        model,
        _bearing(model),
        [column.id],
        {wall.id: 40.0 for wall in model.walls},
        {column.id: 600.0},
        soil=SOIL,
    )
    assert len(plan.pads) == 1
    assert all(strip.widenings == [] for strip in plan.strips)


def test_separate_widening_zones_use_the_governing_local_load_not_their_sum():
    model = _base()
    wall = _wall(0, (0.0, 2.0), (20.0, 2.0), role=MM.WallRole.INTERIOR)
    columns = [_column(0, 3.0, 2.0), _column(0, 17.0, 2.0)]
    model.walls.append(wall)
    model.columns.extend(columns)
    plan = F.layout_foundations(
        model,
        [wall.id],
        [column.id for column in columns],
        {wall.id: 40.0},
        {column.id: 300.0 for column in columns},
        soil=SOIL,
    )

    strip = plan.strips[0]
    assert len(strip.widenings) == 2
    increment = strip.widenings[0].line_load_kn_per_m
    assert strip.w_service_kn_per_m == pytest.approx(40.0 + increment)


# ---------------------------------------------------------------------------
# combined footings
# ---------------------------------------------------------------------------


def test_overlapping_pads_collapse_into_one_combined_footing_on_the_resultant():
    model = _base()
    left = _column(0, 2.0, 2.0)
    right = _column(0, 2.8, 2.0)
    model.columns.extend([left, right])
    plan = F.layout_foundations(
        model, [], [left.id, right.id], {}, {left.id: 100.0, right.id: 300.0}, soil=SOIL
    )
    assert plan.pads == []
    assert len(plan.combined) == 1
    combined = plan.combined[0]
    assert combined.p_service_kn == pytest.approx(400.0)
    # resultant at (2 x 100 + 2.8 x 300) / 400 = 2.6
    assert combined.resultant_x_m == pytest.approx(2.6)
    assert combined.centroid_offset_ratio <= 0.05
    assert combined.x_m == pytest.approx(2.6, abs=0.05 * combined.w_m)
    assert sorted(combined.column_ids) == sorted([left.id, right.id])
    # the rectangle still covers both original pads
    x, y, w, h = combined.rect()
    for pad_x, side in ((2.0, 1.05), (2.8, 1.5)):
        assert x <= pad_x - 0.5 * side + 1e-9
        assert x + w >= pad_x + 0.5 * side - 1e-9


def test_a_chain_of_three_pads_collapses_once():
    model = _base()
    columns = [_column(0, x, 2.0) for x in (2.0, 2.8, 3.6)]
    model.columns.extend(columns)
    plan = F.layout_foundations(
        model, [], [c.id for c in columns], {}, {c.id: 200.0 for c in columns}, soil=SOIL
    )
    assert plan.pads == []
    assert len(plan.combined) == 1
    assert len(plan.combined[0].column_ids) == 3
    assert plan.combined[0].centroid_offset_ratio <= 0.05


def test_pads_further_apart_than_the_gap_stay_apart():
    model = _base()
    columns = [_column(0, 2.0, 2.0), _column(0, 6.0, 2.0)]
    model.columns.extend(columns)
    plan = F.layout_foundations(
        model, [], [c.id for c in columns], {}, {c.id: 100.0 for c in columns}, soil=SOIL
    )
    assert len(plan.pads) == 2
    assert plan.combined == []


def test_combined_cover_note_names_the_designer_as_bearing_area_owner():
    model = _base()
    columns = [_column(0, 2.0, 2.0), _column(0, 2.8, 2.0)]
    model.columns.extend(columns)
    plan = F.layout_foundations(
        model, [], [column.id for column in columns], {}, {column.id: 300.0 for column in columns}, soil=SOIL
    )

    assert len(plan.combined) == 1
    assert "bearing area is set by the designer" in plan.combined[0].note


def test_a_combined_footing_passes_the_party_boundary_ladder():
    model = _base()
    model.walls.extend(
        [
            _wall(0, (0.0, 0.0), (0.0, 12.0), role=MM.WallRole.PARTY),
            _wall(0, (6.0, 0.0), (6.0, 12.0), role=MM.WallRole.EXTERIOR),
        ]
    )
    edge = _column(0, 0.0, 6.0)
    inner = _column(0, 1.5, 6.0)
    model.columns.extend([edge, inner])
    plan = F.layout_foundations(
        model, [], [edge.id, inner.id], {}, {edge.id: 300.0, inner.id: 300.0}, soil=SOIL
    )

    assert len(plan.combined) == 1
    combined = plan.combined[0]
    assert combined.rect()[0] == pytest.approx(0.0)
    assert combined.eccentric is True
    assert combined.e_m == pytest.approx(0.75)
    assert "bearing area is set by the designer" in combined.note
    assert "W_ECCENTRIC_COLUMN" in [entry.code for entry in plan.warnings]


# ---------------------------------------------------------------------------
# boundaries and straps
# ---------------------------------------------------------------------------


def _boundary_model(interior_x=None, interior_load=300.0, width=9.0):
    model = _base()
    model.meta["plot_bounds_m"] = [0.0, 0.0, width, 12.0]
    edge = _column(0, 0.0, 6.0)
    model.columns.append(edge)
    ids = [edge.id]
    loads = {edge.id: 300.0}
    if interior_x is not None:
        inner = _column(0, interior_x, 6.0)
        model.columns.append(inner)
        ids.append(inner.id)
        loads[inner.id] = interior_load
    return model, ids, loads


def test_a_footing_on_the_plot_line_goes_flush_and_takes_a_strap():
    model, ids, loads = _boundary_model(interior_x=3.0)
    plan = F.layout_foundations(model, [], ids, {}, loads, soil=SOIL)
    edge = [pad for pad in plan.pads if pad.eccentric][0]
    # sqrt(300 / 150) = 1.414 -> 1.5 m square, so the flush centre is 0.75 m in
    assert edge.w_m == pytest.approx(1.5)
    assert edge.x_m == pytest.approx(0.75)
    assert edge.e_m == pytest.approx(0.75)
    assert len(plan.straps) == 1
    strap = plan.straps[0]
    assert strap.from_id == edge.id
    assert strap.length_m() == pytest.approx(2.25)
    assert strap.e_m == pytest.approx(0.75)
    assert "carries the couple" in strap.note


def test_a_party_wall_is_a_boundary_even_without_a_plot_outline():
    model = _base()
    model.walls.append(_wall(0, (0.0, 0.0), (0.0, 12.0), role=MM.WallRole.PARTY))
    model.walls.append(_wall(0, (9.0, 0.0), (9.0, 12.0), role=MM.WallRole.EXTERIOR))
    edge = _column(0, 0.0, 6.0)
    inner = _column(0, 3.0, 6.0)
    model.columns.extend([edge, inner])
    plan = F.layout_foundations(
        model, [], [edge.id, inner.id], {}, {edge.id: 300.0, inner.id: 300.0}, soil=SOIL
    )
    assert [pad for pad in plan.pads if pad.eccentric]
    assert len(plan.straps) == 1


def test_an_internal_party_line_does_not_teleport_far_side_pads():
    model = _base()
    model.walls.extend(
        [
            _wall(0, (0.0, 0.0), (0.0, 12.0), role=MM.WallRole.EXTERIOR),
            _wall(0, (4.5, 0.0), (4.5, 12.0), role=MM.WallRole.PARTY),
            _wall(0, (9.0, 0.0), (9.0, 12.0), role=MM.WallRole.EXTERIOR),
        ]
    )
    left = _column(0, 1.0, 3.0)
    right = _column(0, 8.0, 9.0)
    model.columns.extend([left, right])
    plan = F.layout_foundations(
        model, [], [left.id, right.id], {}, {left.id: 150.0, right.id: 150.0}, soil=SOIL
    )

    centres = sorted((pad.load_x_m, pad.x_m, pad.eccentric) for pad in plan.pads)
    assert centres == [(1.0, 1.0, False), (8.0, 8.0, False)]
    assert plan.straps == []


def test_no_interior_footing_within_six_metres_combines_instead():
    # 6.25 m apart, so the strap search fails; the resultant sits right of the
    # bounding box centre, so the rectangle grows away from the boundary
    model, ids, loads = _boundary_model(interior_x=7.0, interior_load=900.0, width=14.0)
    plan = F.layout_foundations(model, [], ids, {}, loads, soil=SOIL)
    assert plan.straps == []
    assert len(plan.combined) == 1
    combined = plan.combined[0]
    assert combined.p_service_kn == pytest.approx(1200.0)
    assert combined.resultant_x_m == pytest.approx(5.25)
    assert combined.centroid_offset_ratio <= 0.05
    assert any("combined with" in note for note in plan.report["notes"])


def test_a_combine_that_would_recross_the_boundary_is_refused():
    model, ids, loads = _boundary_model(interior_x=7.0)
    plan = F.layout_foundations(model, [], ids, {}, loads, soil=SOIL)
    assert plan.straps == []
    assert plan.combined == []
    assert any("across the boundary" in note for note in plan.report["notes"])
    assert "W_ECCENTRIC_COLUMN" in [entry.code for entry in plan.warnings]


def test_a_lonely_boundary_footing_keeps_its_eccentricity_and_warns():
    model, ids, loads = _boundary_model()
    plan = F.layout_foundations(model, [], ids, {}, loads, soil=SOIL)
    assert plan.straps == []
    assert plan.combined == []
    pad = plan.pads[0]
    assert pad.eccentric is True
    assert pad.e_m == pytest.approx(0.75)
    assert pad.w_m == pytest.approx(1.5), "the footing is never shrunk to hide the eccentricity"
    assert "W_ECCENTRIC_COLUMN" in [entry.code for entry in plan.warnings]


def test_without_a_plot_outline_nothing_is_called_eccentric():
    model = _base()
    model.columns.append(_column(0, 0.0, 6.0))
    plan = F.layout_foundations(
        model, [], [model.columns[0].id], {}, {model.columns[0].id: 300.0}, soil=SOIL
    )
    assert plan.straps == []
    assert plan.pads[0].eccentric is False
    assert any("no plot or party boundary" in note for note in plan.report["notes"])


def test_a_surviving_pad_strip_overlap_is_disclosed():
    model = _base()
    wall = _wall(0, (0.0, 2.0), (10.0, 2.0), role=MM.WallRole.INTERIOR)
    column = _column(0, 5.0, 2.35)
    model.walls.append(wall)
    model.columns.append(column)
    plan = F.layout_foundations(
        model, [wall.id], [column.id], {wall.id: 40.0}, {column.id: 600.0}, soil=SOIL
    )

    assert len(plan.pads) == 1
    overlap = [entry for entry in plan.warnings if entry.code == "W_FOOTING_OVERLAP"]
    assert len(overlap) == 1
    assert set(overlap[0].element_ids) == {plan.pads[0].id, plan.strips[0].id}
    assert "share" in overlap[0].message


# ---------------------------------------------------------------------------
# demands, model writes and determinism
# ---------------------------------------------------------------------------


def test_every_footing_carries_its_demands():
    model = _rect_model()
    column = _column(0, 3.0, 3.0)
    model.columns.append(column)
    plan = F.layout_foundations(
        model,
        _bearing(model),
        [column.id],
        {wall.id: 40.0 for wall in model.walls},
        {column.id: 600.0},
        soil=SOIL,
    )
    payload = plan.to_dict()
    for row in payload["strips"]:
        assert row["demands"]["w_service_kn_per_m"] == 40.0
        assert row["demands"]["source"] == "takedown"
    for row in payload["pads"]:
        assert row["demands"]["p_service_kn"] == 600.0
    assert payload["report"]["load_contract"].startswith("wall_loads[wall_id]")


def test_footings_land_on_the_model_and_the_write_is_idempotent():
    model = _rect_model()
    column = _column(0, 3.0, 3.0)
    model.columns.append(column)
    args = (
        model,
        _bearing(model),
        [column.id],
        {wall.id: 40.0 for wall in model.walls},
        {column.id: 600.0},
    )
    F.layout_foundations(*args, soil=SOIL)
    assert model.footings
    kinds = {footing.kind for footing in model.footings}
    assert MM.FootingKind.STRIP in kinds
    assert MM.FootingKind.ISOLATED in kinds
    assert all(footing.placed_by == F.PLACED_BY for footing in model.footings)
    assert model.validate() == []
    first = json.dumps(model.to_dict(), sort_keys=True)
    F.layout_foundations(*args, soil=SOIL)
    assert json.dumps(model.to_dict(), sort_keys=True) == first


def test_plan_output_is_byte_identical_on_a_repeat_run():
    model = _rect_model()
    columns = [_column(0, x, 2.0) for x in (2.0, 2.8, 6.0)]
    model.columns.extend(columns)
    args = (
        model,
        _bearing(model),
        [c.id for c in columns],
        {wall.id: 55.0 for wall in model.walls},
        {c.id: 250.0 for c in columns},
    )
    first = json.dumps(F.layout_foundations(*args, soil=SOIL, write_back=False).to_dict(), sort_keys=True)
    second = json.dumps(F.layout_foundations(*args, soil=SOIL, write_back=False).to_dict(), sort_keys=True)
    assert first == second


def test_every_disclosure_code_is_registered():
    model = _rect_model(party=True)
    plan = F.layout_foundations(model, _bearing(model), [], {}, {}, soil=None)
    assert plan.warnings
    for entry in plan.warnings:
        assert entry.code in MM.REGISTRY
        assert entry.severity == MM.REGISTRY[entry.code][0]
