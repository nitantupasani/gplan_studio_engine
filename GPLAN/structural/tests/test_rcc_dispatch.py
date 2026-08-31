"""What `design/rcc/run_rcc_design` hands each designer, pinned end to end.

Every other design battery calls one designer with hand-built inputs. This one
pins the DISPATCH: the real 2BHK fixture is walked through the adapter, frame
placement, the load model, the takedown and `layout_foundations`, and the whole
placed structure is designed in one call. It exists because the dispatch was
wrong in a way no single-designer test could see: `design_slab` and
`design_footing` were called with their arguments in the wrong slots, so every
slab came back `fail` under the literal element id "slab" and every footing came
back `fail` with "column section 0 mm x 0 mm is not a section", while the batch
still reported one result per element and looked healthy from the outside.

Three things are asserted that a single-designer test cannot reach:

* slabs and footings are walked off the MODEL, not off the force envelopes, so a
  combined footing (two column stacks merged into one rectangle, which carries
  no envelope of its own) is designed rather than skipped;
* the geometry each designer is handed is complete on its own, in particular
  that a column mapping carries its section depth AND its height, so the
  designer never has to fall back to the envelope's unsupported length;
* the shipped signatures are what the dispatch calls, name for name and slot for
  slot, so a future signature change fails loudly here instead of quietly
  designing the wrong member.

The fixture soil is 120 kPa rather than the 150 kPa the api defaults to. That is
not a knob to make a number come out: at 150 kPa every pad on this plan stands
clear of its neighbours and no combined footing is ever placed, so the merged
case would go untested. At 120 kPa the same real pipeline merges two pairs of
pads, which is exactly the case the dispatch used to lose.
"""

from __future__ import annotations

import inspect
import json
import os
import time

import pytest

from .. import api
from .. import model as M
from ..adapters.plan_json import from_plan
from ..analysis import (
    BeamForces,
    ColumnForces,
    ForceEnvelope,
    SlabLoad,
    StationForces,
    to_beam_forces,
    to_column_forces,
    to_slab_load,
)
from ..analysis import takedown as T
from ..design import common as C
from ..design import rcc
from ..design.rcc import beams as BM
from ..design.rcc import columns as CO
from ..design.rcc import detailing as D
from ..design.rcc import footings as FT
from ..design.rcc import slabs as SL
from ..loads import CASE_DL, CASE_LL, CASE_LLR, LoadModel
from ..loads import combos as CB
from ..loads.dead import build_dead
from ..loads.live import build_live
from ..placement import foundations as FDN
from ..placement.frame import run_frame_placement

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

#: See the module docstring: weak enough that two pairs of pads merge on the
#: real plan, which is the only way this fixture ever produces a combined
#: footing and therefore the only way the merged branch gets exercised.
SOIL = {"type": "II", "sbc_kpa": 120.0, "soft": False, "founding_depth_m": 1.5}

#: The options block spec 05 section 11 documents, soil included.
OPTIONS = {
    "materials": {"fck": 25, "fy": 500},
    "seismic": {"zone": "III", "frame": "OMRF"},
    "exposure": "moderate",
    "soil": SOIL,
}

#: Wall-clock ceiling for the whole integration pass. The measured local time
#: when this battery was written was 1.6 s (0.5 s of pipeline, 1.1 s of design
#: over 206 members); this is a guard against a runaway loop, not a target.
BUDGET_S = 20.0


# ---------------------------------------------------------------------------
# the pipeline, run once for the whole module
# ---------------------------------------------------------------------------


def _run_pipeline():
    """adapter -> placement -> loads -> takedown -> foundations -> RC design."""
    started = time.time()
    with open(os.path.join(FIXTURES, "plan_2bhk.json"), "r") as handle:
        model = from_plan(json.load(handle), storeys=2)
    run_frame_placement(model).write_back(model)

    live, roof_live = build_live(model)
    loads = LoadModel(cases={CASE_DL: build_dead(model), CASE_LL: live, CASE_LLR: roof_live})
    loads.combos = CB.generate(sorted(loads.cases))
    takedown = T.run(model, loads)

    ledger = takedown.footing_loads.get("columns") or {}
    column_loads = dict(
        (str(key), float(row.get("p_dl_kn", 0.0)) + float(row.get("p_ll_reduced_kn", 0.0)))
        for key, row in sorted(ledger.items())
    )
    wall_ledger = takedown.footing_loads.get("walls") or {}
    wall_loads = dict(
        (str(key), float(row.get("n_dl_kn_m", 0.0)) + float(row.get("n_ll_kn_m", 0.0)))
        for key, row in sorted(wall_ledger.items())
    )
    ground = min((column.storey for column in model.columns), default=0)
    FDN.layout_foundations(
        model,
        bearing_wall_ids=sorted(
            wall.id
            for wall in model.walls
            if wall.bearing and wall.storey == min((w.storey for w in model.walls), default=0)
        ),
        column_ids=sorted(column.id for column in model.columns if column.storey == ground),
        wall_loads=wall_loads,
        column_loads=column_loads,
        soil=SOIL,
    )

    results = rcc.run_rcc_design(model, takedown, OPTIONS)
    return {
        "model": model,
        "takedown": takedown,
        "results": results,
        "by_key": dict(((item.element_type, item.element_id), item) for item in results),
        "seconds": time.time() - started,
    }


@pytest.fixture(scope="module")
def run():
    return _run_pipeline()


def _of_kind(run, kind):
    return [item for item in run["results"] if item.element_type == kind]


# ---------------------------------------------------------------------------
# the batch as a whole
# ---------------------------------------------------------------------------


def test_the_whole_placed_structure_is_designed_inside_the_budget(run):
    """One result per placed member of every designed class, and no duplicates."""
    assert run["seconds"] < BUDGET_S, "the dispatch battery took %.1f s" % run["seconds"]
    model = run["model"]
    assert model.columns and model.beams and model.slabs and model.footings

    assert len(_of_kind(run, "slab")) == len(model.slabs)
    assert len(_of_kind(run, "footing")) == len(model.footings)
    assert len(_of_kind(run, "column")) == len(model.columns)
    assert len(_of_kind(run, "beam")) == len(model.beams)
    assert len(run["by_key"]) == len(run["results"]), "an element was designed twice"

    kinds = []
    for item in run["results"]:
        if not kinds or kinds[-1] != item.element_type:
            kinds.append(item.element_type)
    assert kinds == list(rcc.MEMBER_KINDS), "results are grouped in MEMBER_KINDS order"
    for kind in rcc.MEMBER_KINDS:
        ids = [item.element_id for item in _of_kind(run, kind)]
        assert ids == sorted(ids), kind + " results are not in element id order"

    # determinism: the same inputs design to the same wire bytes
    again = rcc.run_rcc_design(run["model"], run["takedown"], OPTIONS)
    assert [item.to_dict() for item in again] == [item.to_dict() for item in run["results"]]


# ---------------------------------------------------------------------------
# slabs: design_slab(panel, load, ctx), not design_slab(load, panel, ctx)
# ---------------------------------------------------------------------------


def test_every_slab_is_designed_under_its_own_id_and_none_of_them_fail(run):
    """The panel reaches the first argument, so the geometry is a panel, not a load.

    With the arguments swapped `panel_geometry` read the SlabLoad, found no lx or
    ly on it, and every panel came back `fail` on "geometry" with the literal
    element id "slab". Both halves of that signature are pinned here.
    """
    slabs = _of_kind(run, "slab")
    placed = dict((panel.id, panel) for panel in run["model"].slabs)
    assert len(slabs) == len(placed) >= 20

    assert sorted(item.element_id for item in slabs) == sorted(placed)
    assert not any(item.element_id == "slab" for item in slabs), "the id fell back to 'slab'"
    assert not any(item.governing_check == "geometry" for item in slabs)

    failed = [item.element_id for item in slabs if item.status == C.STATUS_FAIL]
    assert failed == [], "slabs came back failed: " + ", ".join(failed)

    for item in slabs:
        panel = placed[item.element_id]
        assert item.section["lx_mm"] == pytest.approx(panel.lx_m * 1000.0, abs=1.0)
        assert item.section["ly_mm"] == pytest.approx(panel.ly_m * 1000.0, abs=1.0)
        assert item.section["D_mm"] > 0.0
        assert item.bars, item.element_id + " was designed without any mesh"


# ---------------------------------------------------------------------------
# footings: the column section, and the merged rectangle that has no envelope
# ---------------------------------------------------------------------------


def test_every_pad_is_designed_against_the_section_of_the_column_it_carries(run):
    """The pad geometry carries a real ColumnStub, so no pad is refused for it.

    A footing built the wrong way round arrived with a zero column section and
    `_pad_body` refused it: status fail, governing_check "column section". Every
    pad here instead carries the placed column's own b and D in millimetres.
    """
    model = run["model"]
    columns = dict((column.id, column) for column in model.columns)
    pads = [
        item
        for item in _of_kind(run, "footing")
        if item.section.get("kind") in ("isolated", "strap")
    ]
    assert len(pads) >= 10

    assert not any("is not a section" in text for item in pads for text in item.warnings)
    assert not any(item.governing_check == "column section" for item in pads)
    assert not any(item.status == C.STATUS_FAIL for item in pads)

    for item in pads:
        footing = next(one for one in model.footings if one.id == item.element_id)
        column = columns[sorted(footing.supports)[0]]
        assert item.section["column_bx_mm"] == pytest.approx(column.width_m * 1000.0, abs=1.0)
        assert item.section["column_dy_mm"] == pytest.approx(column.depth_m * 1000.0, abs=1.0)
        assert item.section["bx_mm"] > item.section["column_bx_mm"]
        assert item.bars, item.element_id + " was designed without a mat"


def test_a_merged_combined_footing_is_designed_even_though_it_has_no_envelope(run):
    """`layout_foundations` merges two stacks; the merge has no force envelope.

    This is the case a walk over `analysis.envelopes` cannot see at all, which is
    why footings are walked off the model. Both columns must reach
    `design_combined_footing`: the per column check rows name them.
    """
    model = run["model"]
    merged = [one for one in model.footings if one.kind == M.FootingKind.COMBINED]
    assert merged, "the fixture no longer produces a combined footing at this SBC"

    for footing in merged:
        assert footing.id not in run["takedown"].envelopes, (
            "the merged rectangle now has an envelope; the model walk is still correct "
            "but this test no longer proves it is needed"
        )
        item = run["by_key"][("footing", footing.id)]
        assert item.section["kind"] == "combined"
        assert item.status != C.STATUS_FAIL
        assert item.bars
        names = " ".join(row.name for row in item.checks)
        for column_id in footing.supports:
            assert column_id in names, column_id + " never reached the combined designer"


# ---------------------------------------------------------------------------
# columns: the geometry has to stand up on its own
# ---------------------------------------------------------------------------


def test_the_column_geometry_carries_its_depth_and_its_height(run):
    """`column_geometry` resolves the mapping with NO forces to fall back on.

    The dispatch used to hand columns `{b_mm, D_mm, storey}` and nothing else, so
    the height came from the force envelope's unsupported length and a column
    whose envelope carried none was refused outright. The mapping is now complete
    on its own, which is what calling `column_geometry(geom)` without forces
    proves.
    """
    model = run["model"]
    column = sorted(model.columns, key=lambda one: one.id)[0]
    height_m = model.storey(column.storey).height_m
    geom = rcc._column_geometry(column, height_m)

    assert geom["depth_mm"] == pytest.approx(column.depth_m * 1000.0, abs=1e-6)
    assert geom["b_mm"] == pytest.approx(column.width_m * 1000.0, abs=1e-6)
    assert geom["height_mm"] == pytest.approx(height_m * 1000.0, abs=1e-6)

    resolved = CO.column_geometry(geom)  # no forces: the mapping must suffice
    assert resolved.depth_mm == pytest.approx(column.depth_m * 1000.0, abs=1e-6)
    assert resolved.b_mm == pytest.approx(column.width_m * 1000.0, abs=1e-6)
    assert resolved.height_mm == pytest.approx(height_m * 1000.0, abs=1e-6)
    assert resolved.clear_height_mm == resolved.height_mm
    assert resolved.element_id == column.id

    for item in _of_kind(run, "column"):
        assert item.section["b_mm"] > 0.0 and item.section["D_mm"] > 0.0
        assert item.section["length_mm"] > 0.0
        assert not any("needs a height" in text for text in item.warnings)
        assert not any("needs b_mm" in text for text in item.warnings)


def test_beams_are_designed_from_the_placed_section_and_the_envelope(run):
    """Every beam envelope finds its placed section; most of them design clean."""
    model = run["model"]
    beams = _of_kind(run, "beam")
    placed = dict((beam.id, beam) for beam in model.beams)
    assert sorted(item.element_id for item in beams) == sorted(placed)
    assert not any("no placed beam" in text for item in beams for text in item.warnings)

    passing = [item for item in beams if item.status != C.STATUS_FAIL]
    assert len(passing) * 2 > len(beams), "most beams should design without failing"
    for item in passing:
        beam = placed[item.element_id]
        assert item.section["b_mm"] == pytest.approx(beam.width_m * 1000.0, abs=1.0)
        assert item.section["length_mm"] == pytest.approx(beam.span_m() * 1000.0, abs=1.0)


# ---------------------------------------------------------------------------
# the signature contract: what the dispatch calls, slot for slot
# ---------------------------------------------------------------------------

#: The shipped designer signatures the dispatch is written against. A rename or
#: a reorder here is a cross-module change, not a local one.
SHIPPED_SIGNATURES = (
    (BM.design_beam, ("forces", "geom", "ctx")),
    (CO.design_column, ("forces", "geom", "ctx")),
    (SL.design_slab, ("panel", "load", "ctx")),
    (SL.design_stair_flight, ("stair", "load", "ctx")),
    (FT.design_footing, ("footing", "loads", "soil", "ctx")),
    (FT.design_combined_footing, ("footing", "loads", "soil", "ctx")),
    (rcc.design_beam, ("forces", "geom", "ctx")),
    (rcc.design_column, ("forces", "geom", "ctx")),
    (rcc.design_slab, ("panel", "load", "ctx")),
    (rcc.design_stair_flight, ("stair", "load", "ctx")),
    (rcc.design_footing, ("footing", "loads", "soil", "ctx")),
    (rcc.design_combined_footing, ("footing", "loads", "soil", "ctx")),
)


def test_the_shipped_designer_signatures_are_the_ones_the_dispatch_calls():
    for designer, names in SHIPPED_SIGNATURES:
        actual = tuple(inspect.signature(designer).parameters)
        assert actual == names, (
            designer.__module__ + "." + designer.__name__ + " takes " + repr(actual)
            + " but run_rcc_design calls it as " + repr(names)
        )


def _one_column(storey=0, x=0.0, y=0.0, width=0.23, depth=0.30):
    return M.Column(
        id=M.column_id(storey, x_m=x, y_m=y),
        stack_id=M.stack_id(x_m=x, y_m=y),
        storey=storey,
        x_m=x,
        y_m=y,
        width_m=width,
        depth_m=depth,
    )


def test_every_designer_takes_the_positional_call_the_dispatch_makes():
    """Call every designer exactly as `run_rcc_design` does, positionally.

    No keywords anywhere: a silent reorder of two same-typed parameters would
    survive a keyword call and is precisely the drift this pins.
    """
    ctx = D.as_context(OPTIONS)

    beam = M.Beam(id="beam-x", storey=0, a=(0.0, 0.0), b=(4.0, 0.0), width_m=0.23, depth_m=0.45)
    beam_result = rcc.design_beam(
        BeamForces(40.0, 40.0, 60.0, 60.0, 60.0), rcc._beam_geometry(beam), ctx
    )
    assert beam_result.element_type == "beam" and beam_result.element_id == "beam-x"
    assert beam_result.bars and beam_result.section["b_mm"] == 230.0

    column = _one_column()
    column_result = rcc.design_column(
        ColumnForces(pu_kn=900.0, mux_knm=0.0, muy_knm=0.0, lex_m=3.0, ley_m=3.0, storey=0),
        rcc._column_geometry(column, 3.0),
        ctx,
    )
    assert column_result.element_type == "column" and column_result.element_id == column.id
    assert column_result.section["length_mm"] == pytest.approx(3000.0)

    panel = M.SlabPanel(
        id="slab-x",
        storey=0,
        polygon=[(0.0, 0.0), (4.0, 0.0), (4.0, 5.0), (0.0, 5.0)],
        thickness_m=0.125,
        lx_m=4.0,
        ly_m=5.0,
        edge_continuity={"e0": "beam:cont", "e1": "beam:cont", "e2": "beam:cont", "e3": "beam:cont"},
    )
    slab_result = rcc.design_slab(panel, SlabLoad(w_u_kpa=12.0, w_service_kpa=8.0), ctx)
    assert slab_result.element_type == "slab" and slab_result.element_id == "slab-x"
    assert slab_result.status != C.STATUS_FAIL
    assert slab_result.section["lx_mm"] == pytest.approx(4000.0)

    stair = {
        "id": "stair-x",
        "core_id": "core-x",
        "storey": 0,
        "flight": 1,
        "span_m": 1.1576,
        "width_m": 1.524,
        "rise_m": 1.524,
        "incline_deg": 52.79,
    }
    stair_load, stair_ctx = rcc.stair_design_inputs(ctx)
    stair_result = rcc.design_stair_flight(stair, stair_load, stair_ctx)
    assert stair_result.element_type == "slab" and stair_result.element_id == "stair-x"
    assert stair_result.section["waist_mm"] == pytest.approx(100.0)
    assert stair_result.extras["design_pressure_kpa"]["applied_u_kpa"] == pytest.approx(4.5)

    pad = FT.PadGeometry(
        element_id="ftg-x",
        column=rcc._column_stub(column),
        placed_bx_m=1.8,
        placed_ly_m=1.8,
        placed_depth_m=1.5,
    )
    pad_result = rcc.design_footing(pad, FT.FootingLoads(p_service_kn=420.0), SOIL, ctx)
    assert pad_result.element_type == "footing" and pad_result.element_id == "ftg-x"
    assert pad_result.status != C.STATUS_FAIL
    assert pad_result.section["column_bx_mm"] == 230.0
    assert pad_result.section["q_allow_kpa"] == pytest.approx(SOIL["sbc_kpa"])

    other = _one_column(x=3.0)
    combined = FT.CombinedGeometry(
        element_id="ftg-comb-x",
        columns=(rcc._column_stub(column), rcc._column_stub(other)),
        placed_bx_m=1.8,
        placed_ly_m=5.0,
        placed_depth_m=1.5,
    )
    combined_result = rcc.design_combined_footing(
        combined,
        [FT.FootingLoads(p_service_kn=420.0), FT.FootingLoads(p_service_kn=380.0)],
        SOIL,
        ctx,
    )
    assert combined_result.element_id == "ftg-comb-x"
    assert combined_result.section["kind"] == "combined"
    assert combined_result.status != C.STATUS_FAIL


def test_the_options_soil_is_what_reaches_the_footing_designer():
    """`soil` rides on the options block and nothing else in it carries ground."""
    assert rcc._soil_of(OPTIONS) == SOIL
    assert rcc._soil_of(None) is None
    assert rcc._soil_of({"materials": {"fck": 30}}) is None

    class _Opts(object):
        soil = {"sbc_kpa": 90.0}

    assert rcc._soil_of(_Opts()) == {"sbc_kpa": 90.0}

    column = _one_column()
    pad = FT.PadGeometry(element_id="ftg-x", column=rcc._column_stub(column))
    weak = rcc.design_footing(pad, FT.FootingLoads(p_service_kn=420.0), {"sbc_kpa": 90.0}, None)
    firm = rcc.design_footing(pad, FT.FootingLoads(p_service_kn=420.0), {"sbc_kpa": 250.0}, None)
    assert weak.section["q_allow_kpa"] == pytest.approx(90.0)
    assert firm.section["q_allow_kpa"] == pytest.approx(250.0)
    assert weak.section["bx_mm"] > firm.section["bx_mm"], "weaker ground must give a bigger pad"


# ---------------------------------------------------------------------------
# routing every footing kind, and disclosing what cannot be fed
# ---------------------------------------------------------------------------


class _Analysis(object):
    """The slice of a takedown result the dispatch reads, hand built."""

    def __init__(self, envelopes=None, footing_loads=None):
        self.envelopes = dict(envelopes or {})
        self.footing_loads = dict(footing_loads or {})


def _foundation_model():
    """Two storeys, four stacks, one of each footing kind the placer emits.

    Two storeys on purpose: `Footing.supports` then names one column PER STOREY
    of every stack it carries, and a footing carries a stack, not a column. A
    dispatch that read the support list literally would design this combined
    rectangle against the two lifts of one stack and never see the other.

    The bearing wall under `ftg-strip` is on the model and carries a line load in
    the takedown's wall ledger, because a strip is the one footing whose demand
    is a line load and whose geometry is read off the WALL it carries: which of
    the rectangle's two dimensions is the width follows from the wall's own
    direction, not from which number is smaller.
    """
    model = M.StructuralModel(id="routing", source=M.ModelSource.HOUSING)
    columns = []
    for index in (0, 1):
        model.storeys.append(
            M.Storey(index=index, name="S%d" % index, bottom_z_m=index * 3.0, height_m=3.0)
        )
        columns.extend(_one_column(storey=index, x=x) for x in (0.0, 3.0, 6.0, 9.0))
    model.columns.extend(columns)
    stack_of = lambda x: [one.id for one in columns if one.x_m == x]  # noqa: E731
    model.footings.extend(
        [
            M.Footing(
                id="ftg-iso",
                kind=M.FootingKind.ISOLATED,
                supports=stack_of(0.0),
                x_m=0.0,
                y_m=0.0,
                w_m=1.8,
                h_m=1.8,
                depth_m=1.5,
            ),
            M.Footing(
                id="ftg-comb",
                kind=M.FootingKind.COMBINED,
                supports=stack_of(3.0) + stack_of(6.0),
                x_m=4.5,
                y_m=0.0,
                w_m=1.8,
                h_m=5.0,
                depth_m=1.5,
            ),
            M.Footing(
                id="ftg-strip",
                kind=M.FootingKind.STRIP,
                supports=["wall-0-h-0-0"],
                x_m=0.0,
                y_m=6.0,
                w_m=9.0,
                h_m=0.9,
                depth_m=1.5,
            ),
            M.Footing(
                id="ftg-strap",
                kind=M.FootingKind.STRAP,
                supports=["ftg-iso", "ftg-edge"],
                x_m=4.5,
                y_m=0.0,
                w_m=9.0,
                h_m=0.0,
            ),
            M.Footing(
                id="ftg-edge",
                kind=M.FootingKind.ISOLATED,
                supports=stack_of(9.0),
                x_m=9.4,
                y_m=0.0,
                w_m=1.8,
                h_m=1.8,
                depth_m=1.5,
            ),
        ]
    )
    model.walls.append(
        M.WallLine(
            id="wall-0-h-0-0",
            storey=0,
            a=(0.0, 6.0),
            b=(9.0, 6.0),
            thickness_m=0.23,
            role=M.WallRole.INTERIOR,
            bearing=True,
        )
    )
    ledger = dict(
        (column.stack_id, {"p_dl_kn": 300.0, "p_ll_reduced_kn": 120.0}) for column in columns
    )
    return model, _Analysis(
        footing_loads={
            "columns": ledger,
            "walls": {"wall-0-h-0-0": {"n_dl_kn_m": 60.0, "n_ll_kn_m": 20.0}},
        }
    )


def test_each_footing_kind_reaches_its_own_designer_or_a_named_skip():
    model, analysis = _foundation_model()
    results = dict(
        (item.element_id, item) for item in rcc.run_rcc_design(model, analysis, OPTIONS)
    )
    assert sorted(results) == ["ftg-comb", "ftg-edge", "ftg-iso", "ftg-strap", "ftg-strip"]

    assert results["ftg-iso"].section["kind"] == "strap"  # tied back by ftg-strap
    assert results["ftg-edge"].section["kind"] == "strap"

    combined = results["ftg-comb"]
    assert combined.section["kind"] == "combined"
    assert combined.status != C.STATUS_FAIL
    # one column per STACK, so the two lifts of a stack are not read as two columns
    named = " ".join(row.name for row in combined.checks)
    ground = [one.id for one in model.columns if one.storey == 0 and one.x_m in (3.0, 6.0)]
    assert len(ground) == 2 and all(one in named for one in ground)
    assert "-s1" not in named, "an upper lift was read as a second column"

    # The strip reaches its own designer now (task J1): the wall it carries gives
    # it its thickness and its direction, the wall ledger gives it its line load,
    # and the verdict is a real one. `h_m` 0.9 is the width because the wall runs
    # along x, and `w_m` 9.0 is the run.
    strip = results["ftg-strip"]
    assert strip.status != C.STATUS_FAIL, strip.warnings
    assert strip.section["verdict"] in (FT.STRIP_VERDICT_PLAIN, FT.STRIP_VERDICT_RC)
    assert strip.section["wall_t_mm"] == pytest.approx(230.0)
    assert strip.section["length_mm"] == pytest.approx(9000.0)
    assert strip.section["width_mm"] >= 900.0, "the placed 0.9 m width is the floor, not the 9 m run"
    assert strip.governing_check

    skipped = results["ftg-strap"]
    assert skipped.status == C.STATUS_FAIL
    assert skipped.governing_check == "not designed"
    assert skipped.warnings == [rcc.UNDESIGNED_FOOTING_KINDS["strap"]]
    assert skipped.extras["disclosures"], "ftg-strap was skipped without a disclosure"
    entry = skipped.extras["disclosures"][0]
    assert entry["code"] in M.REGISTRY, "skips must carry a registry code"
    assert entry["code"] == "N_ELEMENT_UNDESIGNED", "the skip names the real condition, not a borrowed code"
    assert entry["element_ids"] == ["ftg-strap"]
    assert not skipped.bars, "a skipped footing must not come back detailed"
    assert "strip" not in rcc.UNDESIGNED_FOOTING_KINDS, "a strip is designed now, not skipped"


def test_a_strap_pad_is_designed_as_one_and_refers_the_beam_out():
    """The strap element names the two pads it ties; each is designed eccentric."""
    model, analysis = _foundation_model()
    results = dict(
        (item.element_id, item) for item in rcc.run_rcc_design(model, analysis, OPTIONS)
    )
    tied = results["ftg-edge"]
    assert tied.section["column_offset_x_mm"] != 0.0
    actions = [item["action"] for item in tied.referrals]
    assert "strap_required" in actions
    detail = next(item["detail"] for item in tied.referrals if item["action"] == "strap_required")
    assert detail["partner_footing_id"] == "ftg-iso"
    assert detail["strap_span_m"] == pytest.approx(9.0)


def test_an_element_that_cannot_be_fed_fails_by_name_instead_of_by_invention():
    """No load, no column, no panel load: three disclosed failures, no guesses."""
    model, _ = _foundation_model()
    results = dict(
        (item.element_id, item) for item in rcc.run_rcc_design(model, _Analysis(), OPTIONS)
    )
    starved = results["ftg-iso"]
    assert starved.status == C.STATUS_FAIL
    assert starved.governing_check == "service load"
    assert any(model.columns[0].id in text for text in starved.warnings)
    assert not starved.bars, "a footing with no load must not come back detailed"

    orphan = M.StructuralModel(id="orphan", source=M.ModelSource.HOUSING)
    orphan.storeys.append(M.Storey(index=0, name="S0", bottom_z_m=0.0, height_m=3.0))
    orphan.footings.append(
        M.Footing(id="ftg-orphan", kind=M.FootingKind.ISOLATED, supports=["col-gone"])
    )
    orphan.slabs.append(
        M.SlabPanel(
            id="slab-unloaded",
            storey=0,
            polygon=[(0.0, 0.0), (4.0, 0.0), (4.0, 5.0), (0.0, 5.0)],
            thickness_m=0.125,
            lx_m=4.0,
            ly_m=5.0,
        )
    )
    out = dict((item.element_id, item) for item in rcc.run_rcc_design(orphan, _Analysis(), OPTIONS))
    assert out["ftg-orphan"].governing_check == "column section"
    assert any("col-gone" in text for text in out["ftg-orphan"].warnings)
    assert out["slab-unloaded"].governing_check == "load"
    assert any("no slab envelope" in text for text in out["slab-unloaded"].warnings)


def test_an_envelope_with_no_placed_element_is_still_reported():
    """The union of the two rosters: neither walk may drop an element silently."""
    envelope = ForceEnvelope(
        element_id="beam-nowhere",
        element_type="beam",
        stations=(
            StationForces(station=0.0, m_neg_min_knm=-40.0, v_max_kn=50.0),
            StationForces(station=0.5, m_pos_max_knm=60.0),
            StationForces(station=1.0, m_neg_min_knm=-40.0, v_max_kn=50.0),
        ),
    )
    model = M.StructuralModel(id="empty", source=M.ModelSource.HOUSING)
    results = rcc.run_rcc_design(model, [envelope], OPTIONS)
    assert [item.element_id for item in results] == ["beam-nowhere"]
    assert results[0].status == C.STATUS_FAIL
    assert any("no placed beam" in text for text in results[0].warnings)


def test_the_converters_are_the_only_designer_inputs(run):
    """Finding 20: an envelope reaches a designer through its converter, or not at all.

    The three converters refuse an envelope of the wrong kind, so a dispatch that
    crossed the wires would raise here rather than design the wrong member.
    """
    envelopes = run["takedown"].envelopes
    beam = next(one for one in envelopes.values() if one.element_type == "beam")
    column = next(one for one in envelopes.values() if one.element_type == "column")
    slab = next(one for one in envelopes.values() if one.element_type == "slab")

    assert to_beam_forces(beam).mu_sag_mid_knm >= 0.0
    assert to_column_forces(column).pu_kn > 0.0
    assert to_slab_load(slab).w_u_kpa > 0.0
    for wrong in (column, slab):
        with pytest.raises(ValueError):
            to_beam_forces(wrong)
    with pytest.raises(ValueError):
        to_slab_load(beam)


# ---------------------------------------------------------------------------
# final orchestrator wiring: stair flights, adapter height and edited footings
# ---------------------------------------------------------------------------


def _structural_entry(envelope):
    return envelope["response"]["Documents"]["structural"][0]


def test_meta_stair_flight_reaches_the_package_dispatch_with_its_own_identity():
    """A flight has no envelope; its meta id and 3.0/4.5 kPa load still design."""
    flight = {
        "id": "stair-core-a-s0-f1",
        "core_id": "core-a",
        "storey": 0,
        "flight": 1,
        "span_m": 1.1576,
        "width_m": 1.524,
        "rise_m": 1.524,
        "incline_deg": 52.79,
    }
    model = M.StructuralModel(id="stair-dispatch", source=M.ModelSource.BUILDING)
    model.meta["frame_placement"] = {"stair_slabs": [dict(flight)]}
    before = json.dumps(model.meta, sort_keys=True)

    results = rcc.run_rcc_design(model, _Analysis(), OPTIONS)

    assert [item.element_id for item in results] == [flight["id"]]
    result = results[0]
    assert result.element_type == "slab"
    assert result.extras["slab_mode"] == "stair_flight"
    assert result.section["waist_mm"] == pytest.approx(100.0)
    assert result.section["risers"] == 10
    assert result.extras["design_pressure_kpa"]["applied_u_kpa"] == pytest.approx(4.5)
    assert result.extras["design_pressure_kpa"]["total_u_kpa"] > 4.5
    assert len(result.bars) == 2
    assert len(result.checks) == 10
    assert json.dumps(model.meta, sort_keys=True) == before, "design must not rewrite placement meta"


def test_an_unrouted_meta_stair_is_explicitly_undesigned_in_api_accounting():
    """Coverage and the ladder name a missed meta flight instead of hiding it."""
    flight = {
        "id": "stair-core-missed-s0-f1",
        "core_id": "core-missed",
        "storey": 0,
        "flight": 1,
        "span_m": 1.2,
        "width_m": 1.0,
        "rise_m": 1.5,
        "incline_deg": 51.34,
    }
    model = M.StructuralModel(id="stair-accounting", source=M.ModelSource.BUILDING)
    model.meta["frame_placement"] = {"stair_slabs": [flight]}
    log = M.DisclosureLog()

    missing = api._disclose_undesigned(model, [], M.System.RC_FRAME.value, log)
    coverage = api._design_coverage(model, [], M.System.RC_FRAME.value)

    assert missing == [flight["id"]]
    assert coverage["stair"] == {
        "placed": 1,
        "designed": 0,
        "undesigned": [flight["id"]],
        "undesigned_count": 1,
        "reason": "no analysis demand reached these elements",
    }
    entries = [entry for entry in log.entries if entry.code == "N_ELEMENT_UNDESIGNED"]
    assert len(entries) == 1
    assert entries[0].element_ids == [flight["id"]]


@pytest.fixture(scope="module")
def building_stair_design():
    with open(os.path.join(FIXTURES, "building_3storey.json"), "r") as handle:
        building = json.load(handle)
    envelope = api.run_design(
        {"source": "building", "building": building, "output": {"detail": "full"}}
    )
    return _structural_entry(envelope)


def test_building_stair_results_reach_coverage_and_nonzero_quantities(building_stair_design):
    """The six real flights produce sections, coverage, concrete and formwork."""
    entry = building_stair_design
    model = entry["structural_model"]
    flights = model["meta"]["frame_placement"]["stair_slabs"]
    placed_ids = sorted(flight["id"] for flight in flights)
    results = [
        row
        for row in model["design"]
        if row.get("section", {}).get("waist_mm") is not None
    ]

    assert len(placed_ids) == 6
    assert sorted(row["element_id"] for row in results) == placed_ids
    for row in results:
        assert row["status"] == C.STATUS_PASS
        assert row["section"]["waist_mm"] == pytest.approx(100.0)
        assert row["section"]["risers"] == 10
        assert row["design_pressure_kpa"]["applied_u_kpa"] == pytest.approx(4.5)
        assert len(row["bars"]) == 2
        assert len(row["checks"]) == 10

    coverage = entry["design"]["coverage"]["stair"]
    assert coverage == {
        "placed": 6,
        "designed": 6,
        "undesigned": [],
        "undesigned_count": 0,
    }
    undisclosed = [
        row
        for row in entry["warnings"]
        if row["code"] == "N_ELEMENT_UNDESIGNED"
        and set(row["element_ids"]) & set(placed_ids)
    ]
    assert undisclosed == []

    takeoff = model["quantities"]["takeoff"]
    concrete = next(row for row in takeoff["concrete"] if row["class"] == "stair")
    formwork = next(row for row in takeoff["formwork"] if row["class"] == "stair")
    assert concrete["count"] == 6
    assert concrete["volume_exact_m3"] == pytest.approx(2.557023, abs=1e-6)
    assert formwork["count"] == 6
    assert formwork["area_exact_m2"] == pytest.approx(17.501604, abs=1e-6)


def test_housing_omission_uses_the_adapter_10_4_ft_default(monkeypatch):
    """Only an explicit request may send storey_height_ft into from_housing."""
    from ..adapters import housing as housing_adapter

    with open(os.path.join(FIXTURES, "housing_2storey.json"), "r") as handle:
        housing = json.load(handle)

    actual = housing_adapter.from_housing
    calls = []

    def recording_adapter(*args, **kwargs):
        calls.append(dict(kwargs))
        return actual(*args, **kwargs)

    monkeypatch.setattr(housing_adapter, "from_housing", recording_adapter)

    request = {"source": "housing", "housing": housing}
    opts = api._Resolved(request, {})
    models = api._adapt(request, "housing", opts)
    assert "storey_height_ft" not in calls[0]
    assert models
    assert all(M.m_to_ft(storey.height_m) == pytest.approx(10.4) for model in models for storey in model.storeys)
    assert opts.echo()["values"]["storey_height_ft"] == pytest.approx(10.4)
    assert opts.echo()["origins"]["storey_height_ft"] == "adapters.housing.from_housing default"

    explicit = {
        "source": "housing",
        "housing": housing,
        "params": {"storey_height_ft": 9.25},
    }
    explicit_opts = api._Resolved(explicit, {})
    explicit_models = api._adapt(explicit, "housing", explicit_opts)
    assert calls[1]["storey_height_ft"] == pytest.approx(9.25)
    assert all(
        M.m_to_ft(storey.height_m) == pytest.approx(9.25)
        for model in explicit_models
        for storey in model.storeys
    )
    assert explicit_opts.echo()["origins"]["storey_height_ft"] == "request"


def test_full_check_keeps_edited_footing_and_reports_resize_as_failure(run, monkeypatch):
    """A posted 0.5 ft pad stays 152.4 mm at design entry and cannot pass true."""
    wire = run["model"].to_dict()
    edited = next(row for row in wire["footings"] if row["kind"] == "isolated")
    edited_id = edited["id"]
    edited["w_ft"] = 0.5
    edited["h_ft"] = 0.5
    edited["depth_ft"] = 0.5

    def foundation_relayout_is_forbidden(*args, **kwargs):
        raise AssertionError("run_check must not call layout_foundations")

    monkeypatch.setattr(api._foundations, "layout_foundations", foundation_relayout_is_forbidden)
    entry = _structural_entry(api.run_check({"source": "model", "model": wire, "scope": "full"}))
    row = next(item for item in entry["element_checks"] if item["element_id"] == edited_id)

    assert row["status"] == C.STATUS_RESIZED
    assert row["pass"] is False
    assert row["geometry_changed"] is True
    assert row["resize_history"]
    plan_step = row["resize_history"][0]
    assert plan_step["from"] == "152.4 mm x 152.4 mm"
    assert plan_step["to"] == "900 mm x 1200 mm"
    assert edited_id in entry["changed_hint"]
    assert entry["element_checks_failed"] >= 1

    disclosures = [
        item for item in entry["warnings"] if item["code"] == "N_CHECK_FOOTINGS_AS_GIVEN"
    ]
    assert len(disclosures) == 1
    assert disclosures[0]["stage"] == "api.check.foundation"
    assert edited_id in disclosures[0]["element_ids"]
