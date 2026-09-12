"""Actual checks for proposed remedies, not a badge based on drawn geometry."""
from fractions import Fraction
import json
from pathlib import Path

import pytest

from ..api import run_design
from ..model import BeamKind
from ..placement.frame import _Framer, _PBeam, _Stack
from .housing_search_fixtures import design_request, rect


def open_room_request(cap=5, strategy="economy_grid"):
    payload = design_request("mixed_carriers_3")
    payload["params"]["placement_strategy"] = strategy
    payload["params"]["spans"]["max_m"] = cap
    if strategy == "economy_grid":
        payload["params"].pop("housing_column_variant")
    for floor in payload["housing"]["floors"]:
        floor["boundary"] = rect(0, 0, 42, 31.17)
        generated = floor["boundaryContent"]["generated"]
        generated.update(genW=42, genH=31.17)
        plan = generated["plans"][0]
        plan.pop("detailedPlan", None)
        plan.update(floorWidth=42, floorHeight=31.17, placements=[
            {"name": "Living Room", "x": 0, "y": 0, "width": 42, "height": 31.17},
        ])
    return payload


@pytest.mark.parametrize("cap,inside", [(5, 2), (4, 6), (3.5, 6)])
def test_open_room_remedies_pass_real_design_and_disclose_room_columns(cap, inside):
    envelope = run_design(open_room_request(cap))
    entry = envelope["response"]["Documents"]["structural"][0]
    assert not entry["partial"] and not entry["errors"]
    assert entry["analysis"]["physical_max_span_m"] <= cap
    assert entry["design"]["failed_count"] == 0
    assert entry["design"]["results_count"] > 0
    assert entry["comparison_validity"]["feasible_for_ranking"]
    audit = entry["housing_layout"]
    assert audit["eligible"] and audit["room_assessment"] == "assessed"
    assert audit["room_intrusion_count"] == inside
    assert audit["off_wall_column_count"] == inside * 3
    assert audit["variant"] == "support_grid"
    model = entry["structural_model"]
    ground = {(c["x_ft"], c["y_ft"]) for c in model["columns"] if c["storey"] == 0}
    assert all((c["x_ft"], c["y_ft"]) in ground for c in model["columns"])
    assert all("free" not in row["ends"] and row["chain"] <= 2
               for row in entry["placement"]["beam_supports"])
    # Match the API battery's optional schema check without skipping the
    # engineering assertions when jsonschema is not installed.
    try:
        import jsonschema
    except ImportError:
        return
    schema = json.loads((Path(__file__).parents[1] / "schema" / "structural_response.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(envelope)


def test_wall_only_open_room_remains_unresolved_not_silently_allowed_room_supports():
    entry = run_design(open_room_request(strategy="wall_aligned"))["response"]["Documents"]["structural"][0]
    assert not entry["housing_layout"]["eligible"]
    assert not entry["comparison_validity"]["feasible_for_ranking"]
    assert entry["housing_layout"]["room_intrusion_count"] == 0
    assert any(row["code"] in ("E_SPAN_OVER_MAX", "E_FRAMING_DEPTH") for row in entry["errors"])


@pytest.mark.parametrize("reverse", [False, True])
def test_later_receiving_beam_does_not_hide_bearing_depth(reverse):
    framer = _Framer.__new__(_Framer)
    framer.stacks = [_Stack(x, y, 0, "test", [0], 0, 0, Fraction(0))
                     for x, y in ((0, 0), (6000, 0), (0, 6000), (6000, 6000), (0, 3000))]
    def beam(orient, pos, lo, hi, supports):
        return _PBeam(level_key="0", level_rank=0, storey=0, kind=BeamKind.SECONDARY,
                      orient=orient, pos_mm=pos, lo_mm=lo, hi_mm=hi, supports=supports, note="slab_feedback")
    bottom = beam("h", 0, 0, 6000, ("col", "col"))
    top = beam("h", 6000, 0, 6000, ("col", "col"))
    dependent = beam("h", 3000, 0, 3000, ("col", "free"))
    receiver = beam("v", 3000, 0, 6000, ("beam", "beam"))
    beams = [bottom, top, dependent, receiver]
    if reverse:
        beams.reverse()
    framer._refresh_end_supports(beams)
    framer._recompute_chains(beams)
    assert dependent.supports == ("col", "beam")
    assert receiver.chain == 2
    assert dependent.chain == 3  # must reach the repair ladder, not read as chain 2
