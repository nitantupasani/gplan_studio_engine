"""End to end proof of the LOAD BEARING MASONRY branch of `run_design`.

Why this battery exists
-----------------------
`test_api_pipeline.py` runs the three shipped fixtures, and `choose_system`
escalates every one of them to `rc_frame`: the 2BHK plan is refused with
"panel spans 9.14 m the short way, past the 4.50 m cap", and the shipped housing
fixture draws no interior wall on its first floor, so its upper slab has nothing
to sit on either. The masonry placer, the IS 4326 band and vertical steel tables,
the IS 1905 wall designer, the strip foundations and the masonry take off were
therefore all unit tested and never once run together. That is the whole housing
product, so this file runs it.

`housing_masonry.json` is a 30 ft x 40 ft two storey house built to what
`placement/masonry.py` actually requires rather than to what looks plausible:

* every wall is 230 mm (`wallDisplay.interiorWallFt` 0.75 ft = 228.6 mm), which
  clears the 190 mm `min_bearing_t_mm` screen, and the exterior default is the
  same 0.75 ft, so no wall is confined-only;
* the drawn `segments` cut the plot into five regions whose SHORT side is at
  most 14 ft (4.267 m), under the 4.5 m `max_panel_short_span_m` cap, so the
  greedy cover of spec 5 closes with the perimeter plus three promotions;
* both floors carry the IDENTICAL segment and shape set, so every wall stack is
  grounded and full height and no wall fails the "masonry never transfers"
  screen on the upper storey;
* bearing lines run in both directions on both storeys, so the spec 5.6
  both-directions rule and the 8 m cross wall spacing rule pass without a
  pilaster;
* the stair core sits on one whole region on both floors;
* the synthesized openings clear IS 4326 Table 4: every door is 0.9 m and the
  3.5 ft entry sits on the x = 0 wall, far enough from a corner for b5 and from
  its neighbour for b4, and every segment ratio stays under the category C two
  storey limit of 0.42.

Three assertions in here were `xfail(strict=True)` when the battery was written:
masonry wall design coverage keyed against the wrong element_type and id,
`report.summary.system` naming the requested system after an escalation, and
core tie columns judged against the IS 13920 frame minimum. They were real
defects in modules that battery could not edit; all three are now fixed and the
tests are ordinary, each carrying what was wrong in its own docstring.
"""

from __future__ import annotations

import copy
import json
import os

import pytest

from .. import api
from .. import report as R
from ..adapters.housing import from_housing
from ..codes import is4326
from ..model import REGISTRY, System, ft_to_m, wall_axis
from ..placement import masonry as PM

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

#: The plot, feet. The whole fixture is built on this rectangle.
PLOT_W_FT = 30.0
PLOT_H_FT = 40.0

#: `MasonryParams.max_panel_short_span_m`, in feet, which is what the fixture is
#: drawn against. Every region's short side has to come in under this.
PANEL_CAP_FT = PM.MasonryParams().max_panel_short_span_m / ft_to_m(1.0)

#: 0.75 ft in millimetres, the one wall thickness this house uses.
WALL_T_MM = 228.6

#: Seismic category the default zone III at importance 1.0 lands on.
CATEGORY = "C"

STOREYS = 2


def _load(name):
    with open(os.path.join(FIXTURES, name), "r") as handle:
        return json.load(handle)


def _entries(envelope):
    return envelope["response"]["Documents"]["structural"]


def _rect_from_key(key):
    """The region key "x,y;x,y;..." as (x0, y0, x1, y1) in feet."""
    points = []
    for part in key.split(";"):
        head, _, tail = part.partition(",")
        points.append((float(head), float(tail)))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# ---------------------------------------------------------------------------
# cached runs: the pipeline is seconds, not milliseconds
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def design():
    return _load("housing_masonry.json")


@pytest.fixture(scope="module")
def model(design):
    """The adapter output, exactly as `run_design` under params.system auto builds it.

    `auto` means the orchestrator cannot know the target system when it adapts,
    so the hint is rc_frame and `assume_windows` is off (finding 10). Windows
    arrive in the forced-masonry run below.
    """
    models = from_housing(
        copy.deepcopy(design),
        storey_height_ft=api.DEFAULT_STOREY_HEIGHT_FT,
        system_hint=System.RC_FRAME.value,
        assume_windows=False,
    )
    assert len(models) == 1, "the fixture draws one plot stack"
    return models[0]


@pytest.fixture(scope="module")
def auto_entry(design):
    """`run_design` with params.system left at its default, "auto"."""
    envelope = api.run_design({"source": "housing", "housing": copy.deepcopy(design)})
    assert envelope["status"] == "SUCCESS", envelope["message"]
    entries = _entries(envelope)
    assert len(entries) == 1
    return (envelope, entries[0])


@pytest.fixture(scope="module")
def auto_full(design):
    """The same run at `output.detail=full`.

    `compact` is the shipped default and it projects a passing design row down to
    its governing check, so the IS 1905 working and the masonry prescription only
    ride at `full`. Both levels are asserted: `full` for the engineering content,
    `compact` for what a default response still has to carry.
    """
    envelope = api.run_design(
        {"source": "housing", "housing": copy.deepcopy(design)}, output={"detail": "full"}
    )
    assert envelope["status"] == "SUCCESS", envelope["message"]
    return (envelope, _entries(envelope)[0])


@pytest.fixture(scope="module")
def forced_entry(design):
    """The same house with masonry asked for outright, which turns windows on."""
    envelope = api.run_design(
        {
            "source": "housing",
            "housing": copy.deepcopy(design),
            "params": {"system": System.LOAD_BEARING_MASONRY.value},
        }
    )
    assert envelope["status"] == "SUCCESS", envelope["message"]
    return (envelope, _entries(envelope)[0])


@pytest.fixture(scope="module")
def essential_entry(design):
    """The masonry house in zone IV with a Table 8 category-word importance."""
    envelope = api.run_design(
        {
            "source": "housing",
            "housing": copy.deepcopy(design),
            "params": {
                "system": System.LOAD_BEARING_MASONRY.value,
                "seismic_zone": "IV",
                "importance_factor": "essential",
            },
        },
        output={"detail": "full"},
    )
    assert envelope["status"] == "SUCCESS", envelope["message"]
    return (envelope, _entries(envelope)[0])


@pytest.fixture(scope="module")
def confined_zone_iv_entry(design):
    """The same geometry built as confined masonry in zone IV."""
    envelope = api.run_design(
        {
            "source": "housing",
            "housing": copy.deepcopy(design),
            "params": {
                "system": System.CONFINED_MASONRY.value,
                "seismic_zone": "IV",
            },
        }
    )
    assert envelope["status"] == "SUCCESS", envelope["message"]
    return (envelope, _entries(envelope)[0])


@pytest.fixture(scope="module")
def refusal_entry():
    """Negative control: masonry forced onto the 2BHK plan that cannot take it."""
    envelope = api.run_design(
        {
            "source": "plan",
            "plan": _load("plan_2bhk.json"),
            "storeys": 2,
            "params": {"system": System.LOAD_BEARING_MASONRY.value},
        }
    )
    return (envelope, _entries(envelope)[0])


# ---------------------------------------------------------------------------
# the fixture itself: arithmetic only, so it cannot drift into agreeing with
# the code it feeds
# ---------------------------------------------------------------------------


def test_fixture_is_a_two_storey_house_on_a_30_by_40_plot(design):
    assert len(design["floors"]) == STOREYS
    assert [floor["level"] for floor in design["floors"]] == [0, 1]
    for floor in design["floors"]:
        xs = [p[0] for p in floor["boundary"]]
        ys = [p[1] for p in floor["boundary"]]
        assert max(xs) - min(xs) == PLOT_W_FT
        assert max(ys) - min(ys) == PLOT_H_FT


def test_fixture_walls_are_230_mm_throughout(design):
    interior_ft = design["wallDisplay"]["interiorWallFt"]
    assert interior_ft == 0.75
    assert round(ft_to_m(interior_ft) * 1000.0, 1) == WALL_T_MM
    assert WALL_T_MM >= PM.MasonryParams().min_bearing_t_mm, (
        "230 mm has to clear the load bearing minimum, or every wall is confined-only"
    )


def test_fixture_repeats_the_same_walls_and_core_on_both_floors(design):
    """A masonry wall never transfers, so the upper storey must repeat the lower."""
    ground, first = design["floors"]

    def segment_key(floor):
        return sorted(
            (seg["x1"], seg["y1"], seg["x2"], seg["y2"]) for seg in floor["segments"]
        )

    assert segment_key(ground) == segment_key(first)
    assert segment_key(ground), "the fixture draws interior walls, unlike housing_2storey"

    def shape_key(floor):
        return sorted(
            (tuple(tuple(p) for p in shape["points"]), shape["core"]["kind"])
            for shape in floor["shapes"]
        )

    assert shape_key(ground) == shape_key(first)
    assert [shape["core"]["kind"] for shape in ground["shapes"]] == ["stairs"]
    assert {shape["core"]["id"] for shape in ground["shapes"]} == {
        shape["core"]["id"] for shape in first["shapes"]
    }, "one stair core identity across both storeys"


def test_fixture_regions_tile_the_plot_and_stay_under_the_panel_cap(design):
    """Every drawn region is short enough on one side to be a legal slab panel."""
    for floor in design["floors"]:
        rects = [_rect_from_key(key) for key in floor["regionContent"]]
        for shape in floor["shapes"]:
            xs = [p[0] for p in shape["points"]]
            ys = [p[1] for p in shape["points"]]
            rects.append((min(xs), min(ys), max(xs), max(ys)))

        area = 0.0
        for rect in rects:
            width, height = rect[2] - rect[0], rect[3] - rect[1]
            area += width * height
            assert min(width, height) <= PANEL_CAP_FT + 1e-9, (
                "region %s is %.1f x %.1f ft; the short side must stay under the "
                "%.2f ft (4.50 m) panel cap" % (rect, width, height, PANEL_CAP_FT)
            )
        assert round(area, 6) == PLOT_W_FT * PLOT_H_FT, "the regions tile the plot exactly"

        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                assert _overlap(a[0], a[2], b[0], b[2]) * _overlap(a[1], a[3], b[1], b[3]) == 0.0


def test_fixture_unit_plans_fill_their_regions_without_going_stale(design):
    """genW/genH match the region bbox, so no plan is rescaled at adapt time."""
    for floor in design["floors"]:
        for key, content in floor["regionContent"].items():
            x0, y0, x1, y1 = _rect_from_key(key)
            generated = content["generated"]
            assert generated["genW"] == x1 - x0
            assert generated["genH"] == y1 - y0
            plan = [
                item for item in generated["plans"] if item["id"] == generated["selectedPlanId"]
            ][0]
            covered = sum(p["width"] * p["height"] for p in plan["placements"])
            assert covered == generated["genW"] * generated["genH"], (
                "the placed rooms tile region %s" % key
            )


# ---------------------------------------------------------------------------
# from_housing
# ---------------------------------------------------------------------------


def test_from_housing_builds_bearing_grade_walls_in_both_directions(model):
    assert [storey.index for storey in model.storeys] == [0, 1]
    assert model.walls, "the adapter derived walls"
    for wall in model.walls:
        assert round(wall.thickness_m * 1000.0, 1) == WALL_T_MM, wall.id
    for storey in (0, 1):
        axes = {wall_axis(wall)[0] for wall in model.walls if wall.storey == storey}
        assert axes == {"h", "v"}, "storey %d draws walls both ways" % storey


def test_from_housing_grounds_every_wall_stack(model):
    """No masonry wall may float: every upper wall sits on one below it."""
    stacks = model.build_wall_stacks()
    assert stacks
    for stack in stacks:
        assert stack["grounded"], stack["stack_id"]
        assert sorted(int(key) for key in stack["walls"]) == [0, 1], stack["stack_id"]
        assert stack["max_offset_m"] == 0.0


def test_from_housing_synthesizes_doors_and_the_entry(model):
    kinds = [
        opening.kind.value for wall in model.walls for opening in wall.openings
    ]
    assert kinds.count("entry") == 1, "one 3.5 ft entry, on the ground storey"
    assert kinds.count("door") >= 8, "a door per interface of the spanning tree, both floors"
    codes = [entry.code for entry in model.disclosure_log().entries]
    assert "W_DOOR_ASSUMED" in codes
    assert "N_WINDOWS_NOT_ASSUMED" in codes, "auto does not target masonry, so no windows"


# ---------------------------------------------------------------------------
# choose_system: the answer this whole task turns on
# ---------------------------------------------------------------------------


def test_choose_system_answers_load_bearing_masonry_without_escalating(model):
    decision = PM.choose_system(model, PM.MasonryParams())
    assert decision.system == System.LOAD_BEARING_MASONRY.value
    assert decision.requested == "auto"
    assert decision.category == CATEGORY
    assert decision.refused is None, "a real answer, not a labeled fallback"
    assert not decision.labeled
    assert any("row 4" in line for line in decision.trace), decision.trace


def test_run_design_resolves_masonry_and_places_it(auto_entry):
    _envelope, entry = auto_entry
    assert entry["system"] == System.LOAD_BEARING_MASONRY.value
    placement = entry["placement"]
    assert placement["system"] == System.LOAD_BEARING_MASONRY.value
    assert placement["valid"] is True
    assert placement["system_decision"]["refused"] is None
    assert placement["system_decision"]["system_requested"] == "auto"
    assert "masonry" in placement, "the masonry placement is the delivered geometry"
    assert "masonry_attempt" not in placement, (
        "masonry_attempt only appears when the placer escalated back to a frame"
    )
    assert entry["structural_model"]["system"] == System.LOAD_BEARING_MASONRY.value


def test_run_layout_agrees_with_run_design_on_the_system(design):
    envelope = api.run_layout({"source": "housing", "housing": copy.deepcopy(design)})
    assert envelope["status"] == "SUCCESS"
    entry = _entries(envelope)[0]
    assert entry["system"] == System.LOAD_BEARING_MASONRY.value
    assert entry["footings_sized"] is False, "layout runs no takedown, so it sizes no footing"


# ---------------------------------------------------------------------------
# IS 1893 Table 8 importance and Table 9 masonry system keys
# ---------------------------------------------------------------------------


def test_seismic_demand_uses_the_bands_the_placer_actually_built(auto_full):
    """C9: two placed bands select urm_bands, not the frame ductility row."""
    _envelope, entry = auto_full
    masonry = entry["placement"]["masonry"]
    assert len(masonry["bands"]) == 2
    assert masonry["vertical_bars"] == []

    seismic = entry["analysis"]["seismic"]
    assert seismic["system"] == "urm_bands"
    assert seismic["r"] == 2.0
    assert seismic["directions"]["x"]["base_shear_kn"] == pytest.approx(
        233.30013128755218
    )
    assert entry["options_echo"]["values"]["seismic_system"] == "urm_bands"

    wall = next(
        row
        for row in entry["structural_model"]["design"]
        if row["element_id"] == "wall-s0-h-0-0@s0"
    )
    shear = next(row for row in wall["checks"] if row["name"] == "shear")
    # Correctly separate core/interior wall pieces change diaphragm stiffness
    # allocation: 42.899146701 direct + 7.123621549 torsional kN over
    # 228.6 * 9144 mm2 gives 0.023930693 MPa (six-decimal wire rounding).
    assert shear["demand"] == pytest.approx(0.023931)


def test_essential_importance_is_resolved_once_for_placement_loads_and_design(
    essential_entry,
):
    """B26: the Table 8 word resolves to 1.5 for every engineering consumer."""
    _envelope, entry = essential_entry
    echo = entry["options_echo"]
    assert echo["values"]["importance_factor"] == "essential"
    assert "Table 8" in echo["origins"]["importance_factor"]

    placement = entry["placement"]
    assert placement["masonry"]["params"]["importance"] == 1.5
    assert placement["system_decision"]["category"] == "E"
    assert placement["masonry"]["vertical_bars"]
    assert {row["dia_mm"] for row in placement["masonry"]["vertical_bars"]} == {12, 16}

    seismic = entry["analysis"]["seismic"]
    assert seismic["context"]["importance"] == 1.5
    assert seismic["importance_factor"] == 1.5
    assert seismic["importance_source"] == "given directly in the SeismicContext"
    assert seismic["system"] == "urm_bands_vertical"
    assert seismic["r"] == 2.5
    assert seismic["directions"]["x"]["base_shear_kn"] == pytest.approx(
        419.94023631759393
    )

    building = next(
        row
        for row in entry["structural_model"]["design"]
        if row["element_type"] == "masonry_building"
    )
    assert building["prescription"]["category"] == "E"


def test_confined_masonry_uses_its_own_table_9_row(confined_zone_iv_entry):
    """C9: confining elements select confined_masonry, never zone-IV SMRF."""
    _envelope, entry = confined_zone_iv_entry
    assert entry["system"] == System.CONFINED_MASONRY.value
    assert entry["placement"]["masonry"]["tie_columns"]

    seismic = entry["analysis"]["seismic"]
    assert seismic["system"] == "confined_masonry"
    assert seismic["r"] == 3.0
    assert seismic["directions"]["x"]["base_shear_kn"] == pytest.approx(240.83081513395234)


# ---------------------------------------------------------------------------
# the bearing set and the slab cover
# ---------------------------------------------------------------------------


def test_bearing_lines_run_in_both_directions_on_every_storey(auto_entry):
    _envelope, entry = auto_entry
    bearing = set(entry["placement"]["masonry"]["bearing_walls"])
    assert bearing

    walls = {wall["id"]: wall for wall in entry["structural_model"]["walls"]}
    for wall_id in bearing:
        assert walls[wall_id]["bearing"] is True, "write_back marks the model wall"

    for storey in (0, 1):
        lines = {"h": set(), "v": set()}
        for wall_id in bearing:
            wall = walls[wall_id]
            if wall["storey"] != storey:
                continue
            if wall["a_ft"][1] == wall["b_ft"][1]:
                lines["h"].add(wall["a_ft"][1])
            else:
                lines["v"].add(wall["a_ft"][0])
        assert len(lines["h"]) >= 2, "storey %d: two bearing lines running in x" % storey
        assert len(lines["v"]) >= 2, "storey %d: two bearing lines running in y" % storey

    # the same set on both storeys, which is what makes the stacks grounded
    per_storey = {}
    for wall_id in bearing:
        per_storey.setdefault(walls[wall_id]["storey"], set()).add(
            (walls[wall_id]["a_ft"][0], walls[wall_id]["a_ft"][1])
        )
    assert per_storey[0] == per_storey[1]


def test_every_slab_panel_is_inside_the_cap_with_no_open_edge(auto_entry):
    _envelope, entry = auto_entry
    masonry = entry["placement"]["masonry"]
    panels = masonry["panels"]
    cap = PM.MasonryParams().max_panel_short_span_m
    assert len(panels) >= 10, "six panels a storey, two storeys"
    for panel in panels:
        assert panel["short_span_m"] <= cap + 1e-9, panel
        assert panel["unsupported_m"] == 0.0, panel
    assert masonry["cover_gaps"] == [], "the cover closed with no gap left over"
    assert masonry["pilasters"] == [], "no cross wall gap needed a pilaster"
    assert masonry["demoted"] == []
    assert masonry["hybrid_beams"] == [], "no RC beam line had to be injected"


# ---------------------------------------------------------------------------
# IS 4326: bands, vertical steel, Table 4
# ---------------------------------------------------------------------------


def test_bands_are_placed_with_table_6_bar_schedules(auto_entry):
    _envelope, entry = auto_entry
    schedule = entry["placement"]["masonry"]["band_schedule"]
    by_id = {row["band_id"]: row for row in schedule}

    lintels = [row for row in schedule if row["kind"] == "lintel"]
    assert sorted(row["storey"] for row in lintels) == [0, 1], "a lintel band per storey"
    for row in lintels:
        spec = row["spec"]
        assert spec is not None, row
        reference = is4326.lintel_band(row["span_m"], CATEGORY)
        assert spec["bars_n"] == reference.bars_n
        assert spec["bar_dia_mm"] == reference.bar_dia_mm
        assert spec["depth_mm"] == reference.depth_mm
        assert spec["link_dia_mm"] == reference.link_dia_mm
        assert spec["link_spacing_mm"] == reference.link_spacing_mm
        assert spec["category"] == CATEGORY
        assert spec["steel_grade"] == "Fe415"
        assert row["closed_loop"] is True and row["open_ends"] == []
        assert row["wall_ids"], "the band names the walls it runs over"

    # the two bands that are legitimately absent say which clause lets them be
    assert by_id["band-plinth-s0"]["spec"] is None
    assert "8.4.7" in by_id["band-plinth-s0"]["note"]
    assert by_id["band-roof-s1"]["spec"] is None
    assert "8.4.6" in by_id["band-roof-s1"]["note"], "a cast in situ flat roof is its own band"

    bands = {band["id"]: band for band in entry["structural_model"]["bands"]}
    for row in lintels:
        assert row["band_id"] in bands, "a scheduled band is on the model"
        assert bands[row["band_id"]]["placed_by"] == "placement.masonry"


def test_a_two_storey_category_c_house_takes_no_table_7_vertical_steel(auto_entry):
    # Corrected against the print on 2026-08-30 (task J4). The printed
    # IS 4326:1993 Table 7 gives category C "Nil" at one and at two storeys and
    # only starts at three, so a two storey category C house schedules no
    # vertical bars at all. This file used to carry 10 mm for C at every row,
    # and this test used to assert corner and junction bars here.
    _envelope, entry = auto_entry
    assert (STOREYS, CATEGORY) == (2, "C"), "the row this test is about"
    assert is4326.vertical_bars(STOREYS, 0, CATEGORY) is None
    assert is4326.vertical_bars(STOREYS, 1, CATEGORY) is None
    assert entry["placement"]["masonry"]["vertical_bars"] == []
    # Three storeys is where category C first takes steel, 12 mm at the bottom.
    three = is4326.vertical_bars(3, 0, CATEGORY)
    assert three is not None and three.dia_mm == 12
    assert set(three.locations) == {"corner", "junction"}, (
        "category C bars only at corners and junctions; jambs start at category D"
    )


def test_table_4_opening_checks_run_and_pass_when_the_openings_are_there(forced_entry):
    """Asking for masonry outright turns window synthesis on (finding 10).

    With windows the Table 4 rows actually have geometry to measure, and the
    fixture is drawn so that every one of them passes: no jamb inside 230 mm of
    a corner, no pier under 450 mm, and no segment over the category C two
    storey opening ratio of 0.46.
    """
    _envelope, entry = forced_entry
    masonry = entry["placement"]["masonry"]
    assert masonry["violations_resolved"] == [], "nothing had to be strengthened or demoted"

    rows = [
        check
        for report in masonry["per_wall_reports"]
        for check in report["checks"]
        if check["check"] == "table_4"
    ]
    ran = [row for row in rows if row.get("status") == "ASSUMED-OPENINGS"]
    assert ran, "with windows on, the Table 4 checks have openings to measure"
    for row in ran:
        assert row["ok"] is True, row
        assert row["clause_id"] == "IS4326:1993 Table 4"

    # Printed IS 4326:1993 Table 4, the "C" column at two storeys: b5 230 mm,
    # b4 450 mm, ratio 0.46. Corrected against the print on 2026-08-30 (task
    # J4); this used to read 0.34 and 0.42 because category C was filed with
    # A and B. The fixture still clears every one of them.
    limits = is4326.opening_limits(STOREYS, CATEGORY)
    assert (limits.b5_corner_min_m, limits.b4_pier_min_m, limits.opening_ratio_max) == (
        0.23,
        0.45,
        0.46,
    ), "the limits this fixture was drawn against"

    codes = [item["code"] for item in entry["warnings"]]
    assert "W_ASSUMED_OPENINGS" in codes, "assumed geometry is labeled, never passed off as drawn"


# ---------------------------------------------------------------------------
# the IS 1905 wall design
# ---------------------------------------------------------------------------


def _wall_results(entry):
    return [
        result
        for result in entry["structural_model"]["design"]
        if result["element_type"] == "masonry_wall"
    ]


def test_every_bearing_wall_carries_a_masonry_design_result(auto_full):
    _envelope, entry = auto_full
    bearing = set(entry["placement"]["masonry"]["bearing_walls"])
    results = _wall_results(entry)
    assert {result["section"]["wall_id"] for result in results} == bearing, (
        "one IS 1905 design per bearing wall per storey, no more and no fewer"
    )

    for result in results:
        assert result["status"] == "pass", result["element_id"]
        assert 0.0 < result["utilization_max"] <= 1.0, result["element_id"]
        assert result["governing_check"], result["element_id"]
        names = {check["name"] for check in result["checks"]}
        assert {"slenderness", "compression", "shear", "tension"} <= names, result["element_id"]
        for check in result["checks"]:
            assert check["clause"].startswith("IS1905:1987"), check
        assert result["materials"]["material"] == "masonry"
        assert result["section"]["thickness_mm"] == WALL_T_MM

        prescription = result["prescription"]
        assert prescription, result["element_id"]
        assert prescription["passes"] is True
        assert prescription["mortar_grade"], result["element_id"]
        assert prescription["unit_strength_mpa"] > 0.0, result["element_id"]
        assert prescription["steps"], "the prescription says how it got there"

    demands = {result["masonry"]["segment"]["n_kn_per_m"] for result in results}
    assert min(demands) > 0.0, "the wall demand came from the takedown, not from a stub"


def test_a_default_response_still_carries_every_wall_verdict(auto_entry):
    """`compact` may shorten a wall row; it may not make one disappear."""
    _envelope, entry = auto_entry
    results = _wall_results(entry)
    assert {result["section"]["wall_id"] for result in results} == set(
        entry["placement"]["masonry"]["bearing_walls"]
    )
    for result in results:
        assert result["status"] == "pass", result["element_id"]
        assert result["utilization_max"] > 0.0, result["element_id"]
        assert result["governing_check"], result["element_id"]
        assert result["checks"], "the governing check row survives compaction"
        assert result["checks_total"] == 4, "and says how many rows full would show"


def test_the_building_result_rolls_the_walls_up_into_one_specification(auto_full):
    _envelope, entry = auto_full
    rolled = [
        result
        for result in entry["structural_model"]["design"]
        if result["element_type"] == "masonry_building"
    ]
    assert len(rolled) == 1
    result = rolled[0]
    assert result["status"] == "pass"
    assert result["section"]["walls_designed"] == len(_wall_results(entry))
    assert result["section"]["walls_failed"] == 0
    bands = result["prescription"]["bands"]["bands"]
    assert [row["band_id"] for row in bands if row["required"]] == [
        "band-lintel-s0",
        "band-lintel-s1",
    ]


# ---------------------------------------------------------------------------
# foundations
# ---------------------------------------------------------------------------


def test_strip_footings_are_laid_under_every_ground_bearing_wall_and_sized(auto_entry):
    """`layout_foundations` LAYS every masonry strip and sizes it for placement.

    A strip is laid here, from the takedown's own service line load against the
    resolved SBC, and the note on each row says which rule set its width. The
    DESIGN of the same strips (their verdict, their thickness and their
    governing check) is asserted in the two tests after this one.
    """
    _envelope, entry = auto_entry
    bearing_ground = {
        wall_id
        for wall_id in entry["placement"]["masonry"]["bearing_walls"]
        if wall_id.startswith("wall-s0-")
    }
    strips = entry["analysis"]["foundations"]["strips"]
    assert {wall for strip in strips for wall in strip["wall_ids"]} == bearing_ground, (
        "a strip under every ground bearing wall and under nothing else"
    )
    assert entry["analysis"]["foundations"]["pads"] == [], (
        "the core tie columns land on the strips and are carried by widenings"
    )

    depth = api.resolve_soil(None)["founding_depth_m"]
    for strip in strips:
        assert strip["kind"] == "strip"
        assert strip["width_m"] > 0.0, strip["id"]
        assert strip["depth_m"] == depth, strip["id"]
        assert round(strip["wall_t_m"] * 1000.0, 1) == WALL_T_MM, strip["id"]
        assert strip["width_m"] > strip["wall_t_m"], "a strip spreads wider than its wall"
        assert strip["demands"]["source"] == "takedown"
        assert strip["demands"]["w_service_kn_per_m"] > 0.0, (
            "%s was sized from a real service line load" % strip["id"]
        )
        assert strip["note"], "the sizing rule that produced this width is stated"
        pressure = strip["demands"]["w_service_kn_per_m"] / strip["width_m"]
        assert pressure <= api.resolve_soil(None)["sbc_kpa"] + 1e-6, (
            "%s: %.1f kPa under the strip against the %.0f kPa SBC"
            % (strip["id"], pressure, api.resolve_soil(None)["sbc_kpa"])
        )

    footings = {item["id"]: item for item in entry["structural_model"]["footings"]}
    assert {strip["id"] for strip in strips} <= set(footings)
    for strip in strips:
        wire = footings[strip["id"]]
        assert wire["kind"] == "strip"
        assert wire["w_ft"] and wire["h_ft"] and wire["depth_ft"], wire
        assert wire["placed_by"] == "placement.foundations"
    assert entry["footings_sized"] is True


def _strip_designs(entry):
    return [
        result
        for result in entry["structural_model"]["design"]
        if result["element_type"] == "footing" and result["section"].get("kind") == "strip"
    ]


def test_every_strip_under_a_bearing_wall_is_designed_with_a_verdict(auto_full):
    """The gap this test used to pin: the strips were placed and never designed.

    `design/rcc/footings.design_strip_footing` now designs every one of them off
    the takedown's wall line loads, and each comes back with a real width, a real
    thickness, a plain-or-reinforced verdict and a governing check. This house
    comes out plain on every strip: at 30 to 34 kN/m on 150 kPa the 0.50 m width
    the placer laid leaves a 135.7 mm projection past the 228.6 mm wall, and
    IS 456 Cl 34.1.3 spreads that through 137.5 mm of unreinforced concrete,
    inside the 150 mm minimum edge thickness. That verdict IS the answer, so
    there is no reinforcement and none is invented.
    """
    _envelope, entry = auto_full
    strips = entry["analysis"]["foundations"]["strips"]
    designs = _strip_designs(entry)
    assert {result["element_id"] for result in designs} == {strip["id"] for strip in strips}, (
        "one design per placed strip, no more and no fewer"
    )

    sbc = api.resolve_soil(None)["sbc_kpa"]
    for result in designs:
        section = result["section"]
        assert result["status"] in ("pass", "resized"), result["element_id"]
        assert section["verdict"] in ("plain_concrete", "reinforced_concrete"), result["element_id"]
        assert section["width_mm"] > section["wall_t_mm"], "a strip spreads wider than its wall"
        assert section["D_mm"] >= 150.0, "IS 456 Cl 34.1.2 minimum edge thickness"
        assert section["projection_mm"] == pytest.approx(
            0.5 * (section["width_mm"] - section["wall_t_mm"]), rel=1e-9
        )
        assert section["q_allow_kpa"] == pytest.approx(sbc)
        assert 0.0 < section["q_service_kpa"] <= sbc + 1e-6, result["element_id"]
        assert result["governing_check"], result["element_id"]
        assert result["utilization_max"] > 0.0, result["element_id"]

        names = {check["name"] for check in result["checks"]}
        assert "bearing pressure" in names
        if section["verdict"] == "plain_concrete":
            assert {"plain concrete spread", "projection", "edge thickness"} <= names
            assert not result["bars"], "a plain concrete footing has no reinforcement to detail"
            assert section["reinforced"] is False
            # the thickness is the projection carried through the Cl 34.1.3 spread
            assert section["plain_thickness_required_mm"] == section["D_mm"]
            assert section["plain_thickness_required_mm"] <= section["plain_thickness_cap_mm"]
        else:
            assert {"one-way shear", "flexure", "steel transverse"} <= names
            assert [bar["role"] for bar in result["bars"]] == [
                "strip_transverse_bottom",
                "strip_longitudinal_bottom",
            ]

    assert {result["section"]["verdict"] for result in designs} == {"plain_concrete"}, (
        "a 230 mm wall at 30 kN/m on 150 kPa ground needs no reinforced strip"
    )
    assert {round(result["section"]["width_mm"], 1) for result in designs} == {500.0}
    assert {round(result["section"]["D_mm"], 1) for result in designs} == {150.0}
    assert {result["governing_check"] for result in designs} == {"plain concrete spread"}


def test_no_footing_in_this_house_is_reported_undesigned(auto_entry):
    """The 7 undesigned footings of the measured run are 0, and the code is precise.

    Both halves of gap 6.9: the strips are designed, so nothing is left for
    `_disclose_undesigned` to name; and the code it WOULD name them under is
    `N_ELEMENT_UNDESIGNED` ("placed and quantified, but no designer reached it")
    rather than the borrowed `N_SHAFT_WALL_UNDESIGNED` ("shaft walls carry a
    prescription, not a design"), which is a statement about a different class.
    """
    _envelope, entry = auto_entry
    coverage = entry["design"]["coverage"]["footing"]
    assert coverage["placed"] == len(entry["analysis"]["foundations"]["strips"])
    assert coverage["designed"] == coverage["placed"]
    assert coverage["undesigned"] == []
    assert coverage["undesigned_count"] == 0
    assert entry["design"]["undesigned_count"] == 0
    assert entry["design"]["undesigned"] == []

    codes = {item["code"] for item in entry["warnings"]}
    assert "N_ELEMENT_UNDESIGNED" not in codes, "nothing is left undesigned to disclose"
    assert "N_ELEMENT_UNDESIGNED" in REGISTRY, "and the precise code exists for when something is"
    assert REGISTRY["N_ELEMENT_UNDESIGNED"][1] != REGISTRY["N_SHAFT_WALL_UNDESIGNED"][1], (
        "the two codes must not say the same thing, or the borrow is back"
    )

    # the plain verdict is stated on the ladder, so a reader can tell "designed,
    # needs no steel" from "nobody designed it"
    plain = [item for item in entry["warnings"] if item["code"] == "N_PLAIN_CONCRETE_FOOTING"]
    assert len(plain) == 1, "one entry naming every plain strip"
    assert sorted(plain[0]["element_ids"]) == sorted(
        strip["id"] for strip in entry["analysis"]["foundations"]["strips"]
    )
    assert plain[0]["severity"] == "note"
    assert plain[0]["clause"] == "IS 456 Cl 34.1.3"


# ---------------------------------------------------------------------------
# quantities and report
# ---------------------------------------------------------------------------


def test_the_take_off_and_boq_carry_the_masonry_volume(auto_entry):
    _envelope, entry = auto_entry
    takeoff = entry["structural_model"]["quantities"]["takeoff"]
    assert takeoff["totals"]["masonry_m3"] > 0.0

    rows = takeoff["masonry"]
    assert rows, "the take off breaks the masonry down by thickness and bearing role"
    bearing_rows = [row for row in rows if row["bearing"]]
    assert bearing_rows, "the bearing walls are measured as bearing"
    assert {
        wall for row in bearing_rows for wall in row["wall_ids"]
    } == set(entry["placement"]["masonry"]["bearing_walls"])
    for row in rows:
        assert row["thickness_mm"] == round(WALL_T_MM)
        assert row["volume_m3"] > 0.0
        assert row["gross_m3"] >= row["volume_m3"], "openings are deducted, not added"

    boq = entry["structural_model"]["quantities"]["boq"]
    masonry_items = [item for item in boq["items"] if item["item"] == "Masonry"]
    assert masonry_items, "the bill prices the masonry"
    assert round(sum(item["qty"] for item in masonry_items), 2) == round(
        takeoff["totals"]["masonry_m3"], 2
    )
    for item in masonry_items:
        assert item["unit"] == "m3"
        assert item["amount"] > 0.0
    assert entry["quantities"]["totals"]["masonry_m3"] == takeoff["totals"]["masonry_m3"]


def test_this_house_no_longer_trips_the_rc_frame_density_bands(auto_entry):
    """The measured gap of IMPLEMENTATION_STATUS 6.10, closed and pinned here.

    On 2026-08-30 this run came back carrying `W_STEEL_DENSITY_BAND` ("1.02 kg
    per m2 of built-up area, outside the 2.50 to 7.00 kg/m2 calibration band")
    and `W_CONCRETE_DENSITY_BAND` ("0.020 m3 per m2, outside the 0.10 to 0.20
    m3/m2 band"). Both were correct arithmetic and both were wrong advice: a
    load-bearing masonry house carries almost no reinforced concrete, so those
    two frame heuristics called a correct design wrong on every masonry run, in
    front of exactly the reader who has to trust the warnings. The bands are per
    system now, out of `data/density_bands.yaml`, and this house sits inside its
    own.
    """
    _envelope, entry = auto_entry
    codes = {item["code"] for item in entry["warnings"]}
    assert "W_STEEL_DENSITY_BAND" not in codes
    assert "W_CONCRETE_DENSITY_BAND" not in codes

    boq = entry["structural_model"]["quantities"]["boq"]
    assert boq["system"] == System.LOAD_BEARING_MASONRY.value
    assert boq["system_label"] == "load bearing masonry"
    # The two numbers that used to be warnings, still measured and still
    # reported. They are bounded by their own bands rather than pinned to a
    # digit on purpose: how much RC a masonry house here carries depends on
    # whether its strip footings and its floor plate are designed yet, which is
    # live work (IMPLEMENTATION_STATUS 6.9), and a band that a landing designer
    # can break was never a band. The exact 2026-08-30 figures are pinned in
    # test_quantities.py, where they are hand-fed constants and cannot drift.
    for name in ("steel", "concrete"):
        check = boq["density_checks"][name]
        assert check["status"] == "inside", check
        assert check["disclosed"] is False
        assert check["band_source"].endswith("the load_bearing_masonry row")
        low, high = check["band"]
        assert low < boq[check["metric"]] < high, check
    assert "for load bearing masonry" in boq["density_basis"]


def test_the_walling_volume_is_the_density_this_house_is_judged_on(auto_entry):
    """The check that replaces the two that were wrong: m3 of wall per m2 of floor.

    A masonry house's structure IS its walling, so that is the density worth a
    reader's attention, and it is the one the RC bands never looked at. 0.54
    m3/m2 here: 230 mm walls, 3.0 m storeys, a heavily subdivided plan.
    """
    _envelope, entry = auto_entry
    boq = entry["structural_model"]["quantities"]["boq"]
    check = boq["density_checks"]["masonry"]
    assert check["metric"] == "masonry_m3_per_m2"
    assert check["band"] == [0.10, 0.80]
    assert check["status"] == "inside", check
    assert 0.40 < boq["masonry_m3_per_m2"] < 0.70
    assert "m3/m2 of masonry" in boq["density_basis"]


def test_the_report_names_the_masonry_system_and_carries_the_disclaimer(auto_entry):
    envelope, entry = auto_entry
    report = entry["report"]
    assert report["summary"]["system"] == System.LOAD_BEARING_MASONRY.value
    assert report["summary"]["system"] == entry["system"], (
        "the report and the entry agree on what was built"
    )
    assert report["summary"]["storeys"] == STOREYS
    assert report["summary"]["element_counts"]["walls_bearing"] == len(
        entry["placement"]["masonry"]["bearing_walls"]
    )
    assert report["summary"]["totals"]["masonry_m3"] > 0.0

    for text in (envelope["disclaimer"], entry["disclaimer"], report["disclaimer"]):
        assert R.disclaimer_matches(text), "the disclaimer rides verbatim on every path"

    # a card per designed element. `compact` ships only the cards a reader must
    # act on and says how many it held back, so the totals are the invariant here
    # and the card content is asserted on the full run below.
    walls = _wall_results(entry)
    assert report["element_cards_total"] >= len(walls)
    assert report["element_cards_total"] == len(report["element_cards"]) + report["cards_elided"]


def test_the_report_carries_a_card_for_every_masonry_wall(auto_full):
    _envelope, entry = auto_full
    report = entry["report"]
    assert report["cards_elided"] == 0, "full detail holds nothing back"
    cards = {
        str(card["element_id"]): card
        for card in report["element_cards"]
        if card["element_class"] == "masonry_wall"
    }
    walls = _wall_results(entry)
    assert set(cards) == {result["element_id"] for result in walls}
    for card in cards.values():
        assert card["design_status"] == "pass", card
        assert card["utilization_max"] > 0.0, card
        assert card["section"], card
    assert any(
        card["element_class"] == "masonry_building" for card in report["element_cards"]
    ), "the rolled-up building specification gets a card of its own"


def test_the_masonry_run_is_byte_identical_twice(design):
    payload = {"source": "housing", "housing": design}
    first = api.run_design(
        copy.deepcopy(payload), output={"generated_at": "2026-01-01T00:00:00Z"}
    )
    second = api.run_design(
        copy.deepcopy(payload), output={"generated_at": "2026-01-01T00:00:00Z"}
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# negative control: masonry forced onto a plan that cannot take it
# ---------------------------------------------------------------------------


def test_forcing_masonry_on_the_2bhk_plan_is_refused_with_its_clause(refusal_entry):
    envelope, entry = refusal_entry
    assert envelope["status"] == "SUCCESS", "a refusal still returns a designed building"
    assert R.disclaimer_matches(envelope["disclaimer"])

    assert entry["system"] == System.RC_FRAME.value, "the fallback is what was built"
    placement = entry["placement"]
    assert placement["system"] == System.RC_FRAME.value

    refused = placement["system_decision"]["refused"]
    assert refused is not None, "a refusal is disclosed, never silently swallowed"
    assert refused["code"] in REGISTRY, refused["code"]
    assert refused["clause"], "the refusal cites the clause it rests on"
    assert "4.50 m cap" in refused["reason"], refused["reason"]
    assert placement["system_decision"]["system_requested"] == (
        System.LOAD_BEARING_MASONRY.value
    )
    assert placement["system_decision"]["labeled"] is True

    assert "masonry_attempt" in placement, (
        "the abandoned attempt is reported, so a reader can see what was tried"
    )
    assert "masonry" not in placement, "no masonry geometry was delivered"

    released = [item for item in entry["warnings"] if item["code"] == "W_RELEASED_CAP"]
    assert released, "the ladder carries the fallback as a WARNING, not as a silent pass"
    assert refused["clause"] in {item.get("clause") for item in released}
    assert System.LOAD_BEARING_MASONRY.value in released[0]["message"]

    assert entry["status"] != R.STATUS_REFUSED, "output was produced, so this is not a refusal"
    assert entry["structural_model"]["columns"], "the rc_frame fallback really was placed"
    assert not [
        result
        for result in entry["structural_model"]["design"]
        if result["element_type"] == "masonry_wall"
    ], "no masonry wall was designed on the escalated run"


# ---------------------------------------------------------------------------
# the three defects this battery pinned, now closed. Each test states what was
# wrong and what fixed it, so a regression reads as the named defect coming
# back rather than as an anonymous assertion.
# ---------------------------------------------------------------------------


def test_coverage_counts_the_designed_masonry_walls(auto_entry):
    """`design.coverage.wall` counts the masonry wall designer's own results.

    Was: `api._design_coverage` looked for element_type "wall" and
    `_disclose_undesigned` for the bare wall id, while design/masonry.py emits
    spec 06's frozen `masonry_wall` and `<wall_id>@s<storey>`, so all fourteen
    passing walls were reported designed 0 of 14 and named in an
    N_SHAFT_WALL_UNDESIGNED note. Both now key through `api._design_ids`, which
    keeps the storey in the key: a stack designed on storey 0 and not on storey
    1 still reads as half covered.
    """
    _envelope, entry = auto_entry
    coverage = entry["design"]["coverage"]["wall"]
    designed = len(_wall_results(entry))
    assert coverage["placed"] == designed
    assert coverage["designed"] == designed
    assert coverage["undesigned_count"] == 0
    assert not [
        item for item in entry["design"]["undesigned"] if item.startswith("wall-")
    ]


def test_the_report_system_follows_the_delivered_system_after_an_escalation(refusal_entry):
    """The report and the model both name the system that was actually built.

    Was: `report._system_word` preferred `model.system`, which the adapters set
    from the REQUESTED system and which only `placement/masonry.write_back` ever
    rewrote, so an escalated run reported load_bearing_masonry over an RC frame.
    `api._Placement.system` is now the single source of truth: the frame branch
    writes it back into the model the way the masonry branch always did, and the
    report reads the placement block first.
    """
    _envelope, entry = refusal_entry
    assert entry["report"]["summary"]["system"] == System.RC_FRAME.value
    assert entry["structural_model"]["system"] == System.RC_FRAME.value


def test_masonry_tie_columns_are_not_judged_against_the_is13920_frame_minimum(
    auto_entry, auto_full
):
    """A confining column is exempt from the Cl 7.1 frame geometry clause.

    Was: the placer frames a core corner with a 230 mm tie column
    (placement/masonry.TIE_COLUMN_WIDTH_MM), api._design_members sent it to
    design_column, and the zone III ductile overlay failed all eight of them on
    Cl 7.1.1's 300 mm least dimension at utilization 1.304. IS 13920 Cl 7 sizes
    frame members; IS 4326 does not put a confining column under it. The placer
    now stamps `TIE_COLUMN_CODE_REF` on the Column, api maps that to
    `COLUMN_ROLE_TIE`, and the overlay skips Cl 7.1 for it and says so in a NOTE.
    """
    _envelope, entry = auto_entry
    ties = {tie["id"] for tie in entry["placement"]["masonry"]["tie_columns"]}
    assert ties, "the stair core is framed with tie columns"
    assert entry["design"]["failed_count"] == 0, entry["design"]["failed"]

    # The exemption is disclosed, never silent: every one of these columns is a
    # tie column, so none of them carries the frame geometry check and every one
    # of them says in a NOTE that the clause was skipped and why.
    _full_envelope, full = auto_full
    rows = [
        row for row in full["structural_model"]["design"] if row["element_type"] == "column"
    ]
    assert len(rows) == full["design"]["coverage"]["column"]["placed"]
    for row in rows:
        assert not [
            check for check in row["checks"] if check["name"] == "ductile_column_min_dim"
        ], row["element_id"] + " was still judged against the IS 13920 frame minimum"
        assert [
            note for note in row["notes"] if "IS 4326 confining (tie) column" in note
        ], row["element_id"] + " took the exemption without disclosing it"
