"""Production designs across recesses, openings, cores and room carriers."""
import math

import pytest

from .. import api
from ..adapters.housing import from_housing
from .housing_search_fixtures import CASE_NAMES, design_request


def finite_wall_distance(column, wall):
    x, y = column["x_ft"], column["y_ft"]
    ax, ay = wall["a_ft"]
    bx, by = wall["b_ft"]
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    fraction = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length2)) if length2 else 0
    return math.hypot(x - ax - fraction * dx, y - ay - fraction * dy) * 0.3048


@pytest.mark.parametrize("name", CASE_NAMES)
@pytest.mark.parametrize("variant", ("balanced", "toward_start", "toward_end"))
def test_extended_housing_fixtures_complete_the_actual_design(name, variant):
    payload = design_request(name, variant)
    original = from_housing(payload["housing"])[0]
    if name == "detailed_openings_2":
        assert sum(o.kind.value == "door" for w in original.walls for o in w.openings) == 2
        assert sum(o.kind.value == "window" for w in original.walls for o in w.openings) == 2
    if name.startswith("stair_"):
        assert len(original.cores) == 1 and original.cores[0].storeys == [0, 1]
    assert original.rooms and all(not room.interior_unknown for room in original.rooms)

    envelope = api.run_design(payload)
    assert envelope["status"] == "SUCCESS", envelope.get("message")
    entry = envelope["response"]["Documents"]["structural"][0]
    audit = entry["housing_layout"]
    assert audit["eligible"] is True, (name, variant, entry.get("errors"), audit)
    assert audit["variant"] == variant
    assert audit["room_assessment"] == "assessed" and audit["room_intrusion_count"] == 0
    assert audit["off_wall_column_count"] == 0 and audit["off_wall_column_ids"] == []
    assert audit["physical_max_span_m"] is not None and audit["physical_max_span_m"] <= 5.0
    assert audit["requested_max_span_m"] == 5.0
    assert not entry["errors"] and not entry["partial"]
    assert entry["design"]["failed_count"] == 0
    assert entry["design"]["undesigned_count"] == 0
    assert not entry["design"]["referrals_outstanding"]
    assert entry["comparison_validity"]["feasible_for_ranking"] is True
    assert entry["quantities"]["boq_total"] > 0

    model = entry["structural_model"]
    assert api.validate_wire(model) == []
    for column in model["columns"]:
        walls = [wall for wall in model["walls"] if wall["storey"] == column["storey"]
                 and wall["role"] not in ("railing", "parapet")]
        # Wire coordinates round feet; reserve 1 mm only for that serialization.
        assert walls and min(finite_wall_distance(column, wall) for wall in walls) <= 0.301
    if name == "detailed_openings_2":
        # The dressed door occupies x=12 ft, y=4.5..7.5 ft on each floor.
        assert not any(abs(c["x_ft"] - 12) < 0.1 and 4.5 < c["y_ft"] < 7.5 for c in model["columns"])
