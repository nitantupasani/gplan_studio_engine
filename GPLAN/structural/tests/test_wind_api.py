"""API seam regression for the optional IS 875-3 wind load path."""

from __future__ import annotations

import json
import os

from .. import api


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fixture(name):
    with open(os.path.join(FIXTURES, name), "r") as handle:
        return json.load(handle)


def test_requested_wind_reaches_the_public_load_model_with_model_storey_indices():
    # Before C8, this request stopped at WindContext.__init__: api.py passed
    # basic_speed_ms to a dataclass whose field is Vb_ms. Fixing that keyword
    # alone still left build_wind without width_m, depth_m, or level rows.
    payload = {
        "source": "plan",
        "plan": _fixture("plan_2bhk.json"),
        "storeys": 2,
        "params": {
            "wind": {"basic_speed_ms": 50.0, "terrain_category": 2},
        },
    }
    envelope = api.run_design(payload)
    assert envelope["status"] == "SUCCESS"

    entry = envelope["response"]["Documents"]["structural"][0]
    wind_names = ["WX+", "WX-", "WY+", "WY-"]
    assert entry["analysis"]["wind"]["cases"] == wind_names
    assert set(wind_names) <= set(entry["analysis"]["cases_used"])
    assert set(wind_names) <= set(entry["structural_model"]["loads"]["cases"])

    model_indices = sorted(
        storey["index"] for storey in entry["structural_model"]["storeys"]
    )
    assert [
        row["storey"]
        for row in entry["structural_model"]["loads"]["cases"]["WX+"]["storey"]
    ] == model_indices
    messages = [
        warning["message"] for warning in entry["structural_model"]["warnings"]
    ]
    assert not any("static wind method could not run" in message for message in messages)
