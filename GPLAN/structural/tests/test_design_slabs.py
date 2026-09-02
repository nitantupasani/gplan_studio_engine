"""Pins for slab design: Annex D panels, Table 12 strips and the stair mode.

The arithmetic these tests assert is worked out longhand in the docstrings, so
a reader can check the coefficient reads and the strip statics without running
anything. The one metre strip makes the unit boundary easy to follow: a
pressure of w kPa is a line load of w N/mm on a metre of slab, so a moment
coefficient times w times lx squared comes out directly in N.mm.

The two behaviours that are policy rather than arithmetic get their own pins:
the Cl 22.5.1 guard discloses instead of refusing (spec 05 section 5.1), and a
panel whose span/d is still short at the 150 mm cap comes back `resized` with
an `add_secondary_beams` referral rather than being thickened (finding 40).
"""

from __future__ import annotations

import json
import math

import pytest

from ..analysis import SlabLoad
from ..codes import is456
from ..design import common as C
from ..design.rcc import slabs
from ..model import REGISTRY, SlabPanel
from ..placement.cores import StairSlab

# ---------------------------------------------------------------------------
# panel builders
# ---------------------------------------------------------------------------

#: Placement writes the outline anticlockwise in the y-down plan frame, so the
#: edge keys run e0 = y_min, e1 = x_max, e2 = y_max, e3 = x_min.
EDGE_ORDER = ("y_min", "x_max", "y_max", "x_min")


def panel(
    x_extent_m,
    y_extent_m,
    continuity=(True, True, True, True),
    thickness_m=0.15,
    support=("beam", "beam", "beam", "beam"),
    two_way=None,
    element_id="sl-0-A",
):
    """A rectangular SlabPanel with x_extent along x and y_extent along y."""
    outline = [(0.0, 0.0), (x_extent_m, 0.0), (x_extent_m, y_extent_m), (0.0, y_extent_m)]
    edges = {}
    for index in range(4):
        word = "cont" if continuity[index] else "disc"
        edges["e%d" % index] = support[index] + ":" + word
    return SlabPanel(
        id=element_id,
        storey=0,
        polygon=outline,
        thickness_m=thickness_m,
        two_way=two_way,
        lx_m=min(x_extent_m, y_extent_m),
        ly_m=max(x_extent_m, y_extent_m),
        edge_continuity=edges,
    )


def options(**overrides):
    """Designer options; API dispatch adds the actual per-panel DL/LL split."""
    base = {"fck": 25, "fy": 500, "exposure": "moderate", "imposed_kpa": 2.0}
    base.update(overrides)
    return base


def by_name(result, name):
    for row in result.checks:
        if row.name == name:
            return row
    raise AssertionError("no check named " + name + " in " + str([r.name for r in result.checks]))


def bars_with(result, prefix):
    return [bar for bar in result.bars if str(bar["role"]).startswith(prefix)]


def cantilever_panel(backspan_m=2.0, complete=True):
    """The C7 balcony: 1.2 m projection from the x_min backing edge."""
    subject = panel(
        1.2,
        3.0,
        continuity=(False, False, False, True),
        thickness_m=0.15,
        support=("free", "free", "free", "beam"),
        two_way=False,
        element_id="sl-balcony",
    )
    subject.span_kind = "cantilever"
    if complete:
        subject.cantilever_backing_edge = "x_min"
        subject.cantilever_backing_support_ids = ["beam-root"]
        subject.cantilever_backing_panel_id = "sl-backspan"
        subject.cantilever_backspan_m = backspan_m
        subject.support_ids = ["beam-root"]
    return subject


def c7_building_payload():
    """The verifier's partial-width balcony request, without test shortcuts."""
    return {
        "id": "c7",
        "name": "C7",
        "type": "Low-Rise Residential",
        "boundary": {"kind": "rect", "width": 20, "height": 20},
        "far": 1.5,
        "totalFloors": 1,
        "fixedElements": [],
        "floors": [
            {
                "id": "fl-1",
                "floorNumber": 1,
                "label": "Floor 1",
                "kind": "units",
                "corridors": [],
                "parking": [],
                "units": [
                    {
                        "id": "u1",
                        "name": "U1",
                        "type": "2BHK",
                        "x": 0,
                        "y": 0,
                        "width": 20,
                        "height": 20,
                        "rotation": 0,
                        "isFixed": False,
                        "spaces": [],
                        "activeFloorplanIndex": 0,
                        "floorplans": [
                            {
                                "id": "p-c7",
                                "label": "C7",
                                "taskId": "t",
                                "floorWidth": 20,
                                "floorHeight": 20,
                                "createdAt": "2026-01-01",
                                "placements": [
                                    {
                                        "name": "Living Room",
                                        "x": 0,
                                        "y": 0,
                                        "width": 20,
                                        "height": 10,
                                        "color": "#ccc",
                                    },
                                    {
                                        "name": "Balcony",
                                        "x": 5,
                                        "y": 10,
                                        "width": 10,
                                        "height": 4,
                                        "color": "#ccc",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _element_dicts(value, element_id):
    """All public response records for one element id."""
    found = []
    if isinstance(value, dict):
        if value.get("element_id") == element_id:
            found.append(value)
        for child in value.values():
            found.extend(_element_dicts(child, element_id))
    elif isinstance(value, list):
        for child in value:
            found.extend(_element_dicts(child, element_id))
    return found


# ---------------------------------------------------------------------------
# the unit boundary and the direction vocabulary
# ---------------------------------------------------------------------------


def test_line_load_on_a_one_metre_strip_is_the_pressure_number():
    """1 kN/m2 x 1000 mm = 1 kN/m = 1000 N / 1000 mm = 1 N/mm."""
    assert slabs._line_load_n_per_mm(1.0) == pytest.approx(1.0)
    assert slabs._line_load_n_per_mm(11.25) == pytest.approx(11.25)


def test_table26_case_map_is_total_over_the_nine_printed_cases():
    """Every (long discontinuous, short discontinuous) pair is one of the nine."""
    seen = set()
    for long_disc in (0, 1, 2):
        for short_disc in (0, 1, 2):
            seen.add(slabs.table26_case(long_disc, short_disc))
    assert seen == set(range(1, 10))
    assert slabs.table26_case(0, 0) == 1  # interior
    assert slabs.table26_case(2, 0) == 6  # two long edges discontinuous
    assert slabs.table26_case(0, 2) == 5  # two short edges discontinuous
    assert slabs.table26_case(2, 2) == 9  # four edges discontinuous
    with pytest.raises(ValueError):
        slabs.table26_case(3, 0)


def test_the_long_edges_are_the_supports_of_the_short_span():
    """A 3.6 x 4.5 panel spans 3.6 between the two edges of length 4.5.

    Table 26 pins the reading: case 6 is "two long edges discontinuous" and its
    alpha_x_neg column is all dashes, so the long edges (length ly) are the ones
    that carry the short-span support moment.
    """
    geometry = slabs.panel_geometry(panel(3.6, 4.5))
    assert geometry.lx_mm == pytest.approx(3600.0)
    assert geometry.ly_mm == pytest.approx(4500.0)
    assert geometry.short_axis == "x"
    assert geometry.long_side_tags == ("x_min", "x_max")
    assert geometry.short_side_tags == ("y_min", "y_max")
    assert geometry.sides["x_min"].length_mm == pytest.approx(4500.0)
    assert geometry.sides["y_min"].length_mm == pytest.approx(3600.0)


def test_case_number_follows_the_continuity_mask():
    """Two adjacent discontinuous edges are case 4, whichever pair they are."""
    # e0 = y_min (short edge), e3 = x_min (long edge) discontinuous.
    geometry = slabs.panel_geometry(panel(3.6, 4.5, continuity=(False, True, True, False)))
    assert geometry.case == 4
    # Both long edges discontinuous, both short edges continuous: case 6.
    geometry = slabs.panel_geometry(panel(3.6, 4.5, continuity=(True, False, True, False)))
    assert geometry.case == 6
    # Both short edges discontinuous, both long edges continuous: case 5.
    geometry = slabs.panel_geometry(panel(3.6, 4.5, continuity=(False, True, False, True)))
    assert geometry.case == 5


# ---------------------------------------------------------------------------
# two-way panels
# ---------------------------------------------------------------------------


def test_two_way_interior_panel_matches_hand_computed_table_26():
    """3.6 x 4.5 interior panel, 150 mm, w_u = 10 kPa, M25/Fe500.

    ly/lx = 4.5 / 3.6 = 1.25, so Table 26 case 1 interpolates halfway between
    its 1.2 and 1.3 columns:

        alpha_x_neg = (0.043 + 0.047) / 2 = 0.045
        alpha_x_pos = (0.032 + 0.036) / 2 = 0.034
        alpha_y_neg = 0.032 (constant down the column)
        alpha_y_pos = 0.024

    On a one metre strip w = 10 N/mm and lx = 3600 mm, so w lx^2 =
    10 x 3600^2 = 129 600 000 N.mm and

        Mx_neg = 0.045 x 129.6e6 = 5 832 000 N.mm  (5.832 kNm/m)
        Mx_pos = 0.034 x 129.6e6 = 4 406 400 N.mm
        My_neg = 0.032 x 129.6e6 = 4 147 200 N.mm
        My_pos = 0.024 x 129.6e6 = 3 110 400 N.mm

    The flexure rows report the largest moment in each direction, which is the
    support moment on both.
    """
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())

    coefficients = is456.annex_d__table26(1, 1.25)
    assert coefficients.alpha_x_neg == pytest.approx(0.045)
    assert coefficients.alpha_x_pos == pytest.approx(0.034)

    assert result.section["table_26_case"] == 1
    assert result.extras["method"] == "table26"
    assert by_name(result, "flexure x").demand == pytest.approx(5832000.0)
    assert by_name(result, "flexure y").demand == pytest.approx(4147200.0)
    assert result.status == C.STATUS_PASS
    assert result.resize_history == []


def test_two_way_panel_puts_support_steel_only_on_continuous_edges():
    """Case 4: the top mesh appears at the two continuous edges and nowhere else."""
    # e0 = y_min and e3 = x_min discontinuous, so x_max and y_max are continuous.
    result = slabs.design_slab(
        panel(4.0, 3.5, continuity=(False, True, True, False)),
        SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5),
        options(),
    )
    roles = sorted(bar["role"] for bar in result.bars if "_top_" in bar["role"])
    assert roles == ["mesh_x_top_y_max", "mesh_y_top_x_max"]
    # The short span runs along y here, so its supports are the y_min/y_max sides.
    assert result.section["short_axis"] == "y"


def test_support_band_runs_three_tenths_of_the_span_from_its_own_edge():
    """Annex D-1.6: the top mesh reaches 0.3 l into the span from the support."""
    result = slabs.design_slab(
        panel(3.6, 4.5, continuity=(True, True, True, True)),
        SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7),
        options(),
    )
    low = [bar for bar in result.bars if bar["role"] == "mesh_x_top_x_min"][0]
    high = [bar for bar in result.bars if bar["role"] == "mesh_x_top_x_max"][0]
    assert low["zone_mm"] == pytest.approx([0.0, 0.3 * 3600.0])
    assert high["zone_mm"] == pytest.approx([3600.0 - 0.3 * 3600.0, 3600.0])
    bottom = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]
    assert bottom["zone_mm"] == pytest.approx([0.0, 3600.0])


def test_short_span_bars_are_outermost_so_d_y_sits_one_bar_in():
    """d_y = d_x - (dia_x + dia_y)/2, which is d_x - dia at equal mesh sizes."""
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    dia_x = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]["dia_mm"]
    dia_y = [bar for bar in result.bars if bar["role"] == "mesh_y_bottom"][0]["dia_mm"]
    assert dia_x == dia_y
    assert result.section["d_y_mm"] == pytest.approx(result.section["d_x_mm"] - dia_x)
    assert result.section["d_x_mm"] == pytest.approx(
        result.section["D_mm"] - result.section["cover_mm"] - 0.5 * dia_x
    )


# ---------------------------------------------------------------------------
# corner torsion mesh, Annex D-1.8 and D-1.9
# ---------------------------------------------------------------------------


def test_corner_torsion_mesh_only_where_an_edge_is_discontinuous():
    """Case 4 has one corner with two discontinuous edges, two with one, one with none.

    e0 = y_min and e3 = x_min are discontinuous, so the corner x_min_y_min has
    both its edges discontinuous, x_min_y_max and x_max_y_min have one each, and
    x_max_y_max has none and takes no mesh.
    """
    result = slabs.design_slab(
        panel(4.0, 3.5, continuity=(False, True, True, False)),
        SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5),
        options(),
    )
    corners = sorted(set(bar["corner"] for bar in result.bars if "corner" in bar))
    assert corners == ["x_max_y_min", "x_min_y_max", "x_min_y_min"]
    assert "x_max_y_max" not in corners

    both = [bar for bar in result.bars if bar.get("corner") == "x_min_y_min"]
    one = [bar for bar in result.bars if bar.get("corner") == "x_min_y_max"]
    # Four layers at each corner: two directions, top and bottom.
    assert len(both) == 4
    assert sorted(bar["role"].rsplit("_", 2)[-2] + "_" + bar["role"].rsplit("_", 1)[-1] for bar in both) == [
        "x_bottom",
        "x_top",
        "y_bottom",
        "y_top",
    ]
    assert both[0]["discontinuous_edges"] == 2
    assert one[0]["discontinuous_edges"] == 1


def test_corner_mesh_area_is_three_quarters_and_the_d_1_9_half_of_it():
    """D-1.8 gives 0.75 Ast_mid at a two-edge corner, D-1.9 halves it at a one-edge corner."""
    result = slabs.design_slab(
        panel(4.0, 3.5, continuity=(False, True, True, False)),
        SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5),
        options(),
    )
    both = [bar for bar in result.bars if bar.get("corner") == "x_min_y_min"][0]
    one = [bar for bar in result.bars if bar.get("corner") == "x_min_y_max"][0]
    assert one["ast_req_mm2_per_m"] == pytest.approx(0.5 * both["ast_req_mm2_per_m"])
    # The band is one fifth of the short span, and the bars run that far.
    assert both["zone_mm"][1] == pytest.approx(result.section["lx_mm"] / 5.0)


def test_a_corners_free_panel_uses_table_27_and_takes_no_torsion_mesh():
    """All four edges discontinuous with corners not held down is the D-2 case."""
    result = slabs.design_slab(
        panel(3.6, 4.5, continuity=(False, False, False, False)),
        SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7),
        options(),
    )
    assert result.extras["method"] == "table27"
    assert [bar for bar in result.bars if "corner" in bar] == []
    coefficients = is456.annex_d__table27(1.25)
    assert by_name(result, "flexure x").demand == pytest.approx(
        coefficients.alpha_x * 10.0 * 3600.0 * 3600.0
    )


def test_corners_held_down_keeps_the_panel_on_table_26():
    result = slabs.design_slab(
        panel(3.6, 4.5, continuity=(False, False, False, False)),
        SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7),
        options(corners_held_down=True),
    )
    assert result.extras["method"] == "table26"
    assert result.section["table_26_case"] == 9
    assert [bar for bar in result.bars if "corner" in bar] != []


# ---------------------------------------------------------------------------
# one-way panels and the Clause 22.5.1 guard
# ---------------------------------------------------------------------------


def test_one_way_interior_strip_takes_the_table_12_coefficients():
    """2.4 x 6.0 strip, ly/lx = 2.5, both long edges continuous, w_u = 32 kPa.

    The combined factored pressure cannot be split into dead and imposed, so
    both Table 12 rows are read and the heavier coefficient is taken:

        span, interior:    max(1/16, 1/12) = 1/12  = 0.083333
        support, interior: max(1/12, 1/9)  = 1/9   = 0.111111

    On a metre strip w = 32 N/mm and lx = 2400 mm, so w lx^2 = 32 x 2400^2 =
    184 320 000 N.mm and

        Mx_pos = 184 320 000 / 12 = 15 360 000 N.mm
        Mx_neg = 184 320 000 /  9 = 20 480 000 N.mm
    """
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, True, False, True)),
        SlabLoad(w_u_kpa=32.0, w_service_kpa=21.0),
        options(),
    )
    assert result.extras["method"] == "table12"
    assert result.section["two_way"] is False
    assert by_name(result, "flexure x").demand == pytest.approx(20480000.0)
    top = [bar for bar in result.bars if "_top_" in bar["role"]]
    assert sorted(bar["role"] for bar in top) == ["mesh_x_top_x_max", "mesh_x_top_x_min"]


def test_guard_is_satisfied_for_a_strip_continuous_at_both_supports():
    """Continuity at both supports puts the panel inside a run of three spans."""
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, True, False, True)),
        SlabLoad(w_u_kpa=32.0, w_service_kpa=21.0),
        options(),
    )
    assert result.warnings == []
    assert "disclosures" not in result.extras
    assert any("Cl 22.5.1 assumed" in note for note in result.notes)


def test_guard_failure_still_uses_the_coefficients_and_discloses_the_code():
    """Spec 05 section 5.1: disclose, never refuse. The moments still come out."""
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, True, False, False)),
        SlabLoad(w_u_kpa=12.0, w_service_kpa=8.0),
        options(),
    )
    assert result.extras["method"] == "table12"
    codes = [entry["code"] for entry in result.extras["disclosures"]]
    assert codes == ["W_ANA_COEFF_INAPPLICABLE"]
    assert any(text.startswith("W_ANA_COEFF_INAPPLICABLE:") for text in result.warnings)
    # An end span: 1/10 on the span and 1/9 at the one continuous support.
    assert by_name(result, "flexure x").demand == pytest.approx(12.0 * 2400.0 * 2400.0 / 9.0)
    assert len([bar for bar in result.bars if "_top_" in bar["role"]]) == 1


def test_guard_fails_when_the_imposed_load_exceeds_the_dead_load():
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, True, False, True)),
        SlabLoad(w_u_kpa=32.0, w_service_kpa=21.0),
        options(imposed_kpa=12.0, dead_kpa=9.0),
    )
    codes = [entry["code"] for entry in result.extras["disclosures"]]
    assert "W_ANA_COEFF_INAPPLICABLE" in codes
    assert any("exceeds dead" in text for text in result.warnings)


def test_guard_fails_on_a_stated_run_of_two_spans():
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, True, False, True)),
        SlabLoad(w_u_kpa=32.0, w_service_kpa=21.0),
        options(continuous_spans=2),
    )
    assert any("fewer than the three" in text for text in result.warnings)


def test_a_strip_discontinuous_at_both_supports_takes_wl2_over_eight():
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, False, False, False)),
        SlabLoad(w_u_kpa=12.0, w_service_kpa=8.0),
        options(),
    )
    assert result.extras["method"] == "ss"
    assert by_name(result, "flexure x").demand == pytest.approx(12.0 * 2400.0 * 2400.0 / 8.0)
    assert [bar for bar in result.bars if "_top_" in bar["role"]] == []


def test_one_way_transverse_steel_is_the_distribution_minimum():
    """0.12 percent of the gross section, on the 5d or 450 spacing row."""
    result = slabs.design_slab(
        panel(2.4, 6.0, continuity=(False, True, False, True)),
        SlabLoad(w_u_kpa=32.0, w_service_kpa=21.0),
        options(),
    )
    depth = result.section["D_mm"]
    distribution = [bar for bar in result.bars if bar["role"] == "mesh_y_bottom"][0]
    assert distribution["ast_req_mm2_per_m"] == pytest.approx(0.0012 * 1000.0 * depth)
    allowed = by_name(result, "bar spacing y").capacity
    assert allowed == pytest.approx(
        min(5.0 * result.section["d_y_mm"], 450.0)
    )


def test_an_unsupported_side_demotes_a_square_panel_to_one_way_with_a_warning():
    result = slabs.design_slab(
        panel(
            3.6,
            4.0,
            continuity=(False, True, True, True),
            support=("free", "beam", "beam", "beam"),
        ),
        SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7),
        options(),
    )
    assert result.section["two_way"] is False
    assert any("carry no beam or wall" in text for text in result.warnings)


# ---------------------------------------------------------------------------
# C7: explicit cantilever and support-topology routes
# ---------------------------------------------------------------------------


def test_balcony_cantilever_matches_root_hogging_vector_and_top_anchorage():
    """C7 hand vector: 1.2 m projection x 3.0 m width, D=150 mm.

    On the one metre strip, w_u=11.45 kPa is 11.45 N/mm.  With the
    identified x_min root and projection a=1200 mm:

        Mu(root) = w a^2 / 2 = 11.45 x 1200^2 / 2
                 = 8,244,000 N.mm/m, hogging
        Vu(root) = w a = 13,740 N/m

    Moderate exposure and an 8 mm outer top bar give d=150-30-4=116 mm:

        Vu(d) = 11.45 x (1200-116) = 12,411.8 N
        tau_v = 12,411.8 / (1000 x 116) = 0.106998276 MPa

    Ast,min=0.0012 x 1000 x 150=180 mm2/m, so 8 at 270 provides
    186.185185 mm2/m.  Ld=388.392857 mm and the 3 m root takes 12 bars.
    Fig 4 gives MF=1.599368619, hence the cantilever deflection capacity is
    7 x MF=11.195580336 against a/d=10.344827586.

    The old route used the Table 12 end-support value w a^2/9=1,832,000
    N.mm/m, exactly 4.5 times low, emitted a full bottom main mesh and only a
    0.3a top band, and never reached the basic cantilever ratio 7.
    """
    result = slabs.design_slab(
        cantilever_panel(),
        SlabLoad(w_u_kpa=11.45, w_service_kpa=7.5),
        options(),
    )

    assert result.status == C.STATUS_PASS
    assert result.extras["slab_mode"] == "cantilever"
    assert result.extras["method"] == "cantilever"
    assert result.extras["backing_edge"] == "x_min"
    assert result.section["cantilever_axis"] == "x"
    assert result.section["projection_mm"] == pytest.approx(1200.0)
    assert by_name(result, "flexure main").demand == pytest.approx(8244000.0)
    assert result.extras["root_shear_n"] == pytest.approx(13740.0)
    assert result.extras["shear_at_d_n"] == pytest.approx(12411.8)
    assert by_name(result, "shear").demand == pytest.approx(0.10699827586206896)

    main = [bar for bar in result.bars if bar["role"] == "mesh_cantilever_main_top"][0]
    assert main["face"] == "top"
    assert main["zone_mm"] == pytest.approx([0.0, 1200.0])
    assert main["count"] == 12
    assert main["dia_mm"] == 8.0
    assert main["spacing_mm"] == pytest.approx(270.0)
    assert main["ld_mm"] == pytest.approx(388.39285714285717)
    assert main["anchor_zone_mm"] == pytest.approx([-main["ld_mm"], 0.0])
    assert main["anchorage_ends"] == 1
    assert main["ast_prov_mm2_per_m"] == pytest.approx(186.1851851851852)

    distribution = [
        bar for bar in result.bars if bar["role"] == "mesh_cantilever_distribution_top"
    ][0]
    assert distribution["face"] == "top"
    assert distribution["anchorage_ends"] == 0
    assert not [bar for bar in result.bars if bar.get("face") == "bottom"]
    assert result.extras["deflection_route"] == "cl_23_2_1_cantilever"
    assert result.extras["deflection_basic_ld"] == pytest.approx(7.0)
    assert by_name(result, "deflection").demand == pytest.approx(10.344827586206897)
    assert by_name(result, "deflection").capacity == pytest.approx(11.195580335917844)
    assert "W_ANA_COEFF_INAPPLICABLE" not in [
        entry["code"] for entry in result.extras.get("disclosures", [])
    ]


def test_public_building_api_preserves_partial_width_balcony_cantilever_intent():
    """C7 public seam: generated perimeter beams do not erase slab intent.

    The exact 20 x 20 ft request creates a 10 x 4 ft balcony panel with a
    quantized 1219 mm projection. Its y_min root is backed by the Living Room
    panel over 3048 mm. With the 150 mm project-minimum slab, public
    w_u=9.75 kPa:

        Mu(root) = 9.75 x 1219^2 / 2 = 7,244,059.875 N.mm/m

    Old behavior counted four generated edge beams, silently made this an
    ordinary panel, and emitted bottom x/y meshes with no hogging-root check.
    """
    from .. import api as structural_api

    envelope = structural_api.run_design(
        {
            "source": "building",
            "building": c7_building_payload(),
            "output": {"detail": "full"},
        }
    )

    assert envelope["status"] == "SUCCESS"
    matches = _element_dicts(envelope, "slab-s0-3")
    design = [row for row in matches if row.get("slab_mode") == "cantilever"][0]
    assert design["method"] == "cantilever"
    assert design["status"] == C.STATUS_PASS
    assert design["backing_edge"] == "y_min"
    assert design["backing_panel_id"] == "slab-s0-0"
    assert design["backing_support_ids"] == ["beam-s0-yB-1"]
    assert design["backspan_mm"] == pytest.approx(3048.0)
    assert design["projection_mm"] == pytest.approx(1219.0)
    assert design["root_moment_nmm"] == pytest.approx(7244059.875)
    assert any("root hogging" in note for note in design["notes"])

    main = [bar for bar in design["bars"] if bar["role"] == "mesh_cantilever_main_top"][0]
    assert main["face"] == "top"
    assert main["zone_mm"] == pytest.approx([0.0, 1219.0])
    assert main["anchor_zone_mm"] == pytest.approx([-main["ld_mm"], 0.0])
    assert not [bar for bar in design["bars"] if bar.get("face") == "bottom"]
    assert not [
        bar
        for bar in design["bars"]
        if bar.get("role") in ("mesh_x_bottom", "mesh_y_bottom")
    ]


def test_cantilever_without_identified_backing_is_refused_not_spanned():
    result = slabs.design_slab(
        cantilever_panel(complete=False),
        SlabLoad(w_u_kpa=11.45, w_service_kpa=7.5),
        options(),
    )

    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "cantilever backing support"
    assert result.bars == []
    assert result.checks == []
    disclosures = result.extras["disclosures"]
    assert [entry["code"] for entry in disclosures] == ["E_CANTILEVER_BACKING"]
    assert disclosures[0]["severity"] == "error"
    assert disclosures[0]["code"] in REGISTRY
    assert result.extras["method"] == "refused_cantilever"
    assert not any("simply supported" in note.lower() for note in result.notes)


def test_cantilever_refuses_when_backspan_cannot_develop_the_top_bars():
    result = slabs.design_slab(
        cantilever_panel(backspan_m=0.2),
        SlabLoad(w_u_kpa=11.45, w_service_kpa=7.5),
        options(),
    )

    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "cantilever backing support"
    assert result.bars == []
    row = by_name(result, "cantilever development length")
    assert row.demand == pytest.approx(388.39285714285717)
    assert row.capacity == pytest.approx(200.0)
    assert row.status == C.CHECK_FAIL
    assert [entry["code"] for entry in result.extras["disclosures"]] == [
        "E_CANTILEVER_BACKING"
    ]


def test_one_way_panel_uses_the_only_opposed_supported_pair_even_when_long():
    """C7's second vector spans 6 m between its two 3 m supported edges.

    With w_u=12 N/mm, simple-span Mu=12 x 6000^2 / 8=54,000,000
    N.mm/m.  The old unconditional geo.lx route used 3000 mm and returned
    13,500,000 N.mm/m, four times low, with the main layer in the wrong plan
    direction.
    """
    subject = panel(
        3.0,
        6.0,
        continuity=(False, False, False, False),
        support=("beam", "free", "beam", "free"),
        thickness_m=0.4,
    )
    result = slabs.design_slab(
        subject,
        SlabLoad(w_u_kpa=12.0, w_service_kpa=8.0),
        options(),
    )

    assert result.extras["method"] == "ss"
    assert result.section["design_span_mm"] == pytest.approx(6000.0)
    assert result.section["one_way_axis"] == "y"
    assert by_name(result, "flexure y").demand == pytest.approx(54000000.0)
    main = [bar for bar in result.bars if bar["role"] == "mesh_y_bottom"][0]
    distribution = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]
    assert main["zone_mm"] == pytest.approx([0.0, 6000.0])
    assert result.section["d_y_mm"] > result.section["d_x_mm"]
    assert main["layer"] == 1
    assert distribution["layer"] == 1


# ---------------------------------------------------------------------------
# spacing, shear and the deflection ladder
# ---------------------------------------------------------------------------


def test_the_hundred_millimetre_pitch_floor_bumps_the_diameter():
    """A 1.8 m strip under 80 kPa wants about 736 mm2/m of short-span steel.

    At 8 mm the pitch would be 1000 x 50.27 / 736 = 68 mm, under the 100 mm
    placing floor, so the mesh steps up to 10 mm where 1000 x 78.54 / 736 =
    107 mm rounds down to 100 mm and clears the floor.
    """
    result = slabs.design_slab(
        panel(1.8, 5.0, continuity=(False, False, False, False)),
        SlabLoad(w_u_kpa=80.0, w_service_kpa=53.0),
        options(),
    )
    main = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]
    assert main["dia_mm"] == 10.0
    assert main["spacing_mm"] >= slabs.MIN_MESH_SPACING_MM
    assert main["spacing_mm"] % slabs.SPACING_MODULE_MM == 0.0
    # The pitch that was refused: 8 mm bars would have gone under the floor.
    assert C.spacing_for_area(main["ast_req_mm2_per_m"], 8, 300.0, 10.0) < slabs.MIN_MESH_SPACING_MM


def test_pitch_never_exceeds_the_clause_26_3_3_cap():
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    row = by_name(result, "bar spacing x")
    assert row.capacity == pytest.approx(min(3.0 * result.section["d_x_mm"], 300.0))
    assert row.status == C.CHECK_PASS
    for bar in result.bars:
        assert bar["spacing_mm"] <= 450.0


def test_shear_is_taken_at_d_from_the_support_with_the_depth_factor():
    """tau_v = w (lx/2 - d) / (1000 d), capacity k(D) tau_c on the provided steel."""
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    depth = result.section["D_mm"]
    d_x = result.section["d_x_mm"]
    shear_force = 10.0 * (0.5 * 3600.0 - d_x)
    assert by_name(result, "shear").demand == pytest.approx(shear_force / (1000.0 * d_x))

    provided = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]["ast_prov_mm2_per_m"]
    pt = 100.0 * provided / (1000.0 * d_x)
    expected = is456.cl_40_2_1_1__k_solid_slab(depth) * is456.table_19__tau_c(pt, 25.0)
    assert by_name(result, "shear").capacity == pytest.approx(expected)
    assert by_name(result, "shear cap").capacity == pytest.approx(
        0.5 * is456.table_20__tau_c_max(25.0)
    )


def test_two_way_deflection_uses_clause_24_1_inside_its_guard():
    """Short span 3.5 m and imposed 2 kPa are both inside the Note, so 40 x 0.8."""
    result = slabs.design_slab(
        panel(3.5, 4.0), SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5), options(imposed_kpa=2.0)
    )
    assert result.extras["deflection_route"] == "cl_24_1"
    assert by_name(result, "deflection").capacity == pytest.approx(32.0)


def test_outside_the_guard_deflection_falls_back_to_the_beam_rule():
    """A 3.6 m short span is past the 3.5 m Note limit, so Cl 23.2.1 is used."""
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    assert result.extras["deflection_route"] == "cl_23_2_1"
    assert any("Cl 24.1 Note is limited" in note for note in result.notes)
    assert by_name(result, "deflection").capacity > 26.0  # continuous basic 26 x MF


def test_missing_imposed_split_changes_the_route_but_not_the_project_minimum():
    """B19 plus the project floor: routing may differ; neither result is thin.

    For this 3.4 x 4.0 m interior panel starting at 120 mm, using the whole
    7.5 kPa service pressure misses the Cl 24.1 imposed-load guard and the
    Cl 23.2.1 route would pass thinner. Supplying the actual 2.0 kPa imposed
    pressure takes Cl 24.1. The 150 mm project floor governs both routes.
    """
    subject = panel(3.4, 4.0, thickness_m=0.12)
    load = SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5)
    no_split = slabs.design_slab(
        subject,
        load,
        {"fck": 25, "fy": 500, "exposure": "moderate"},
    )
    split = slabs.design_slab(subject, load, options(imposed_kpa=2.0))

    assert no_split.extras["deflection_route"] == "cl_23_2_1"
    assert no_split.section["D_mm"] == pytest.approx(150.0)
    assert split.extras["deflection_route"] == "cl_24_1"
    assert split.section["D_mm"] == pytest.approx(150.0)
    fallback = " ".join(no_split.notes).lower()
    assert "routing fallback" in fallback
    assert "larger span/depth ratio" in fallback
    assert "thinner slab" in fallback
    assert "conservative reading" not in fallback
    assert no_split.resize_history[0]["from"] == pytest.approx(120.0)
    assert no_split.resize_history[-1]["to"] == pytest.approx(150.0)


def test_the_ladder_thickens_ten_millimetres_at_a_time():
    result = slabs.design_slab(
        panel(4.0, 3.5, thickness_m=0.125), SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5), options()
    )
    assert result.status == C.STATUS_RESIZED
    steps = result.resize_history
    assert steps
    for step in steps:
        assert step["to"] - step["from"] <= 10.0 + 1e-9
        assert step["reason"]
    assert steps[0]["from"] == pytest.approx(125.0)
    assert result.section["D_mm"] <= 150.0


def test_deflection_ladder_stops_at_150_and_refers_secondary_beams():
    """Finding 40: at the cap the panel is referred, not thickened further.

    A 5.5 x 6.0 panel simply supported all round cannot meet span/d at 150 mm:
    5500 / 116 = 47.4 against roughly 21 from the Cl 23.2.1 route. The result
    still comes back fully designed, the failing row is left visible, and the
    referral carries the suggested secondary-beam spacing.
    """
    result = slabs.design_slab(
        panel(6.0, 5.5, continuity=(False, False, False, False), thickness_m=0.125),
        SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5),
        options(),
    )
    assert result.section["D_mm"] == pytest.approx(150.0)
    assert result.status == C.STATUS_RESIZED
    assert result.governing_check == "deflection"
    assert by_name(result, "deflection").status == C.CHECK_FAIL

    referrals = [item for item in result.referrals if item["action"] == "add_secondary_beams"]
    assert len(referrals) == 1
    detail = referrals[0]["detail"]
    assert detail["suggested_spacing_m"] == [2.5, 3.5]
    assert detail["reason"] == "span/d"
    assert detail["thickness_mm"] == pytest.approx(150.0)
    assert "add_secondary_beams" in C.REFERRAL_ACTIONS

    codes = [entry["code"] for entry in result.extras["disclosures"]]
    assert "W_THICK_SLAB" in codes
    # The result is still a complete design, not a stub.
    assert result.bars and result.checks and result.section["d_x_mm"] > 0.0


def test_a_strength_failure_at_the_cap_stays_a_failure():
    """Only a deflection shortfall is answered by the referral; strength is not."""
    result = slabs.design_slab(
        panel(4.0, 5.0, continuity=(False, False, False, False), thickness_m=0.15),
        SlabLoad(w_u_kpa=140.0, w_service_kpa=95.0),
        options(),
    )
    assert result.status == C.STATUS_FAIL
    assert by_name(result, "flexure x").status == C.CHECK_FAIL
    assert [item for item in result.referrals if item["action"] == "add_secondary_beams"]


def test_the_ladder_always_terminates_and_stays_inside_the_policy():
    policy = C.ResizePolicy()
    for pressure in (5.0, 12.0, 30.0, 60.0, 120.0):
        result = slabs.design_slab(
            panel(4.2, 5.0, thickness_m=0.1),
            SlabLoad(w_u_kpa=pressure, w_service_kpa=pressure / 1.5),
            options(),
        )
        assert len(result.resize_history) <= policy.max_iters
        assert result.section["D_mm"] <= policy.slab_cap_mm + 1e-9
        assert result.status in C.STATUSES


# ---------------------------------------------------------------------------
# stair flights (critic finding 40)
# ---------------------------------------------------------------------------


def flight(span_m=2.7, width_m=1.2, rise_m=1.5, element_id="stair-c1-s0-f1"):
    return StairSlab(
        id=element_id,
        core_id="c1",
        storey=0,
        flight=1,
        span_m=span_m,
        width_m=width_m,
        rise_m=rise_m,
        incline_deg=math.degrees(math.atan2(rise_m, span_m)),
    )


def test_stair_waist_honours_the_project_minimum_after_span_over_twenty():
    """2.7 m going gives 140 mm by span/20, so the project floor governs at 150."""
    result = slabs.design_stair_flight(flight(), SlabLoad(w_u_kpa=7.5, w_service_kpa=5.0), options())
    assert result.extras["slab_mode"] == "stair_flight"
    assert result.section["waist_mm"] >= 150.0
    assert all(item["from"] >= 150.0 for item in result.resize_history)
    assert result.section["span_mm"] == pytest.approx(2700.0)


def test_stair_steel_follows_the_simply_supported_span_moment():
    """Mu = w L^2 / 8 on the plan projection, with the waist weight added in.

    A 2.7 m flight rising 1.5 m sits at atan(1.5 / 2.7) = 29.05 degrees, and its
    1.5 m rise divides into 10 risers of 150 mm. At a 150 mm waist the self
    weight on plan is 25 x 0.150 / cos(29.05) = 4.29 kPa for the waist plus
    25 x 0.075 = 1.875 kPa for the step triangles, both factored by 1.5.
    """
    result = slabs.design_stair_flight(flight(), SlabLoad(w_u_kpa=7.5, w_service_kpa=5.0), options())
    pressures = result.extras["design_pressure_kpa"]
    waist_m = result.section["waist_mm"] / 1000.0
    cosine = math.cos(math.radians(result.section["incline_deg"]))
    assert pressures["waist_u_kpa"] == pytest.approx(1.5 * 25.0 * waist_m / cosine)
    assert pressures["steps_u_kpa"] == pytest.approx(1.5 * 25.0 * 0.5 * 0.150)
    assert pressures["total_u_kpa"] == pytest.approx(
        7.5 + pressures["waist_u_kpa"] + pressures["steps_u_kpa"]
    )
    assert result.section["risers"] == 10
    assert result.section["riser_mm"] == pytest.approx(150.0)

    span = result.section["span_mm"]
    expected_mu = pressures["total_u_kpa"] * span * span / 8.0
    assert by_name(result, "flexure main").demand == pytest.approx(expected_mu)

    main = [bar for bar in result.bars if bar["role"] == "mesh_main_bottom"][0]
    d_main = result.section["d_main_mm"]
    assert main["ast_req_mm2_per_m"] == pytest.approx(
        max(
            is456.annex_g__ast_singly(expected_mu, 1000.0, d_main, 25.0, 500.0),
            0.0012 * 1000.0 * result.section["waist_mm"],
        )
    )
    assert main["zone_mm"] == pytest.approx([0.0, span])
    assert main["ld_mm"] > 0.0


def test_a_longer_flight_wants_a_thicker_waist_and_more_steel():
    short = slabs.design_stair_flight(
        flight(span_m=2.4, rise_m=1.5), SlabLoad(w_u_kpa=7.5, w_service_kpa=5.0), options()
    )
    long = slabs.design_stair_flight(
        flight(span_m=3.6, rise_m=1.5), SlabLoad(w_u_kpa=7.5, w_service_kpa=5.0), options()
    )
    assert long.section["waist_mm"] > short.section["waist_mm"]
    short_steel = [bar for bar in short.bars if bar["role"] == "mesh_main_bottom"][0]
    long_steel = [bar for bar in long.bars if bar["role"] == "mesh_main_bottom"][0]
    assert long_steel["ast_prov_mm2_per_m"] > short_steel["ast_prov_mm2_per_m"]


def test_stair_carries_distribution_steel_and_the_landing_note():
    result = slabs.design_stair_flight(flight(), SlabLoad(w_u_kpa=7.5, w_service_kpa=5.0), options())
    distribution = [bar for bar in result.bars if bar["role"] == "mesh_distribution_bottom"]
    assert len(distribution) == 1
    assert distribution[0]["ast_req_mm2_per_m"] == pytest.approx(
        0.0012 * 1000.0 * result.section["waist_mm"]
    )
    assert any(note.startswith("landing check:") for note in result.notes)
    assert any("separate elements" in note for note in result.notes)


def test_stair_self_weight_can_be_left_to_the_takedown():
    result = slabs.design_stair_flight(
        flight(), SlabLoad(w_u_kpa=16.75, w_service_kpa=11.0), options(stair_self_weight_included=True)
    )
    pressures = result.extras["design_pressure_kpa"]
    assert pressures["waist_u_kpa"] == pytest.approx(0.0)
    assert pressures["steps_u_kpa"] == pytest.approx(0.0)
    assert pressures["total_u_kpa"] == pytest.approx(16.75)


def test_a_flight_with_no_span_fails_without_raising():
    result = slabs.design_stair_flight(
        flight(span_m=0.0), SlabLoad(w_u_kpa=7.5, w_service_kpa=5.0), options()
    )
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "geometry"


# ---------------------------------------------------------------------------
# contract: determinism, the result shape, the trace, the registry
# ---------------------------------------------------------------------------


def test_cantilever_handoff_wire_is_additive_and_regular_wire_is_unchanged():
    from .. import model as M

    added = {
        "span_kind",
        "cantilever_backing_edge",
        "cantilever_backing_support_ids",
        "cantilever_backing_panel_id",
        "cantilever_backspan_ft",
    }
    regular_wire = M._slab_to_wire(panel(3.0, 4.0))
    assert added.isdisjoint(regular_wire)

    subject = cantilever_panel()
    wire = M._slab_to_wire(subject)
    assert added <= set(wire)
    rebuilt = M._slab_from_wire(wire)
    assert rebuilt.kind == subject.kind
    assert rebuilt.span_kind == "cantilever"
    assert rebuilt.cantilever_backing_edge == "x_min"
    assert rebuilt.cantilever_backing_support_ids == ["beam-root"]
    assert rebuilt.cantilever_backing_panel_id == "sl-backspan"
    assert rebuilt.cantilever_backspan_m == pytest.approx(2.0, abs=1.0e-5)


def test_placement_handoff_resolves_root_support_panel_and_backspan():
    from .. import model as M
    from ..placement import frame

    cant_outline = [(0, 0), (1200, 0), (1200, 3000), (0, 3000)]
    back_outline = [(-2000, 0), (0, 0), (0, 3000), (-2000, 3000)]
    cantilever = frame._Panel(
        level=0,
        outline_mm=cant_outline,
        region=frame._Footprint.from_polygons([cant_outline]),
        kind="cantilever",
        rect_mm=(0, 0, 1200, 3000),
        edge_support=["free", "free", "free", "beam"],
        edge_cont=[False, False, False, True],
        id="sl-balcony",
    )
    backing = frame._Panel(
        level=0,
        outline_mm=back_outline,
        region=frame._Footprint.from_polygons([back_outline]),
        kind="slab",
        rect_mm=(-2000, 0, 0, 3000),
        id="sl-backspan",
    )
    root = frame._PBeam(
        level_key="0",
        level_rank=2,
        storey=0,
        kind=M.BeamKind.PRIMARY,
        orient="v",
        pos_mm=0,
        lo_mm=0,
        hi_mm=3000,
        id="beam-root",
    )

    handoff = frame._cantilever_handoff(
        cantilever, [cantilever, backing], [root], []
    )
    assert handoff == {
        "backing_edge": "x_min",
        "backing_support_ids": ["beam-root"],
        "backing_panel_id": "sl-backspan",
        "backspan_m": 2.0,
    }


def test_api_dispatch_supplies_each_panel_actual_dead_and_imposed_area_loads(monkeypatch):
    from types import SimpleNamespace

    from .. import api as structural_api
    from .. import model as M
    from ..analysis import ForceEnvelope
    from ..loads import AreaLoad, CaseKind, LoadCase, LoadModel

    subject = panel(3.4, 4.0, element_id="sl-api-split")
    model = M.StructuralModel(id="slab-split-dispatch")
    model.slabs = [subject]
    analysis = SimpleNamespace(
        envelopes={
            subject.id: ForceEnvelope(
                element_id=subject.id,
                element_type="slab",
                w_u_kpa=11.25,
                w_service_kpa=7.5,
            )
        },
        footing_loads={"columns": {}, "walls": {}},
    )
    loadmodel = LoadModel(
        cases={
            "DL": LoadCase(
                name="DL",
                kind=CaseKind.DEAD,
                area=[
                    AreaLoad(subject.id, 3.75, CaseKind.DEAD, "self_weight"),
                    AreaLoad(subject.id, 1.0, CaseKind.DEAD, "finishes"),
                    AreaLoad("other-panel", 99.0, CaseKind.DEAD, "not_this_panel"),
                ],
            ),
            "LL": LoadCase(
                name="LL",
                kind=CaseKind.LIVE,
                area=[AreaLoad(subject.id, 2.0, CaseKind.LIVE, "occupancy")],
            ),
            "LLR": LoadCase(name="LLR", kind=CaseKind.ROOF_LIVE),
        }
    )
    captured = []

    def fake_design(_panel, _load, ctx):
        captured.append(dict(ctx))
        return C.DesignResult(element_id=subject.id, element_type="slab")

    monkeypatch.setattr(slabs, "design_slab", fake_design)
    results = structural_api._design_members(
        model,
        analysis,
        None,
        structural_api._Resolved({"params": {}}, {}),
        "rc_frame",
        M.DisclosureLog(),
        loadmodel=loadmodel,
    )

    assert len(results) == 1
    assert captured[0]["dead_kpa"] == pytest.approx(4.75)
    assert captured[0]["imposed_kpa"] == pytest.approx(2.0)


def test_api_promotes_cantilever_backing_error_to_the_blocking_ladder():
    from types import SimpleNamespace

    from .. import api as structural_api
    from .. import model as M
    from ..analysis import ForceEnvelope

    subject = cantilever_panel(complete=False)
    model = M.StructuralModel(id="cantilever-refusal-dispatch")
    model.slabs = [subject]
    analysis = SimpleNamespace(
        envelopes={
            subject.id: ForceEnvelope(
                element_id=subject.id,
                element_type="slab",
                w_u_kpa=11.45,
                w_service_kpa=7.5,
            )
        },
        footing_loads={"columns": {}, "walls": {}},
    )
    log = M.DisclosureLog()
    results = structural_api._design_members(
        model,
        analysis,
        None,
        structural_api._Resolved({"params": {}}, {}),
        "rc_frame",
        log,
    )

    assert results[0].status == C.STATUS_FAIL
    errors = [entry for entry in log.entries if entry.severity == M.Severity.ERROR]
    assert [(entry.code, entry.element_ids) for entry in errors] == [
        ("E_CANTILEVER_BACKING", [subject.id])
    ]


def test_design_is_deterministic():
    subject = panel(4.0, 3.5, continuity=(False, True, True, False), thickness_m=0.125)
    load = SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5)
    first = slabs.design_slab(subject, load, options()).to_dict()
    second = slabs.design_slab(subject, load, options()).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    stair_first = slabs.design_stair_flight(flight(), SlabLoad(7.5, 5.0), options()).to_dict()
    stair_second = slabs.design_stair_flight(flight(), SlabLoad(7.5, 5.0), options()).to_dict()
    assert json.dumps(stair_first, sort_keys=True) == json.dumps(stair_second, sort_keys=True)


def test_every_bar_carries_its_own_ld_and_zone():
    """Finding 24: the schedule reads ld_mm and zone_mm off the bar, never a default."""
    result = slabs.design_slab(
        panel(4.0, 3.5, continuity=(False, True, True, False)),
        SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5),
        options(),
    )
    assert result.bars
    for bar in result.bars:
        assert bar["ld_mm"] > 0.0
        assert len(bar["zone_mm"]) == 2
        assert bar["zone_mm"][1] > bar["zone_mm"][0]
        assert bar["count"] >= 1
        assert bar["spacing_mm"] > 0.0
    assert result.stirrups == []


def test_result_round_trips_through_its_dict():
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    wire = result.to_dict()
    assert json.loads(json.dumps(wire)) == wire
    rebuilt = C.DesignResult.from_dict(wire)
    assert rebuilt.to_dict() == wire
    assert rebuilt.element_type == "slab"
    assert "quantities" not in wire


def test_disclosure_codes_are_registry_codes():
    result = slabs.design_slab(
        panel(6.0, 5.5, continuity=(False, False, False, False), thickness_m=0.125),
        SlabLoad(w_u_kpa=11.25, w_service_kpa=7.5),
        options(),
    )
    entries = result.extras["disclosures"]
    assert entries
    for entry in entries:
        assert entry["code"] in REGISTRY
        assert entry["stage"] == "design.rcc.slabs"
        assert entry["element_ids"] == [result.element_id]


def test_trace_carries_the_clauses_the_design_read():
    result = slabs.design_slab(panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    refs = set(entry.code + " " + entry.ref for entry in result.trace)
    for clause in ("IS456:2000 Table 26", "IS456:2000 G-1.1(b)", "IS456:2000 Table 19", "IS456:2000 26.5.2.1"):
        assert clause in refs
    # The ladder's abandoned rungs are not on the wire: only the design reported.
    assert len(result.trace) < 200


def test_context_reads_a_plain_options_mapping_and_an_object():
    from_mapping = slabs.slab_context({"fck": 30, "fy": 415, "exposure": "severe"})
    assert from_mapping.fck_mpa == 30.0
    assert from_mapping.fy_mpa == 415.0
    assert from_mapping.exposure == "severe"

    nested = slabs.slab_context({"materials": {"fck": 20, "fy": 500}, "exposure": "mild"})
    assert nested.fck_mpa == 20.0

    assert slabs.slab_context(None).fck_mpa == 25.0
    assert slabs.slab_context(from_mapping) is from_mapping

    policy = slabs.slab_context({"resize_policy": {"slab_cap_mm": 200.0}}).policy
    assert policy.slab_cap_mm == pytest.approx(200.0)


def test_material_grades_reach_the_result_and_the_design():
    result = slabs.design_slab(
        panel(3.6, 4.5), SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options(fck=30, fy=415)
    )
    assert result.materials["concrete_grade"] == "M30"
    assert result.materials["steel_grade"] == "Fe415"
    assert by_name(result, "shear cap").capacity == pytest.approx(
        0.5 * is456.table_20__tau_c_max(30.0)
    )


def test_a_panel_with_no_thickness_starts_the_ladder_from_a_derived_one():
    bare = panel(3.6, 4.5, thickness_m=None)
    result = slabs.design_slab(bare, SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    assert result.section["D_mm"] >= 150.0
    assert any("carried no thickness" in note for note in result.notes)


def test_a_panel_with_no_span_fails_without_raising():
    empty = SlabPanel(id="deg", storey=0, polygon=[], thickness_m=0.125, lx_m=0.0, ly_m=0.0)
    result = slabs.design_slab(empty, SlabLoad(w_u_kpa=10.0, w_service_kpa=6.7), options())
    assert result.status == C.STATUS_FAIL
    assert result.governing_check == "geometry"
    assert result.materials["concrete_grade"] == "M25"


def test_a_pitch_the_catalogue_cannot_reach_is_flagged_not_squeezed_silently():
    """Past the largest mesh bar the pitch is reported as it stands, with a note."""
    result = slabs.design_slab(
        panel(4.0, 9.0, continuity=(False, False, False, False), thickness_m=0.4),
        SlabLoad(w_u_kpa=400.0, w_service_kpa=260.0),
        options(),
    )
    main = [bar for bar in result.bars if bar["role"] == "mesh_x_bottom"][0]
    assert main["dia_mm"] == float(slabs.MESH_DIAS_MM[-1])
    assert main["spacing_mm"] < slabs.MIN_MESH_SPACING_MM
    assert any("placing floor" in note for note in result.notes)
    assert result.status in C.STATUSES


def test_a_placement_two_way_flag_that_disagrees_is_noted_not_obeyed():
    subject = panel(2.4, 6.0, continuity=(False, True, False, True), two_way=True)
    result = slabs.design_slab(subject, SlabLoad(w_u_kpa=32.0, w_service_kpa=21.0), options())
    assert result.section["two_way"] is False
    assert any("placement recorded this panel as two-way" in note for note in result.notes)
