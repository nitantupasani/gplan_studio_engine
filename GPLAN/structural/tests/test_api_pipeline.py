"""End to end battery for `structural/api.py`: the four entry points, wired.

This is the first test in the package that runs the whole pipeline. Every other
battery pins one stage against hand numbers; this one asserts that the stages
join up, that the wire shape is the one `schema/structural_response.schema.json`
describes, and that two identical requests produce byte-identical bytes, which
is what the backend's Redis dedup key rests on.

The three shipped fixtures are all run through `run_design`, which is expensive
(seconds, not milliseconds), so every pipeline run is a module-scoped fixture
and the assertions read the cached result. Anything that needs to mutate a
result deep-copies it first.

`jsonschema` is used when it is installed and skipped when it is not: the shipped
schema is validated by hand against `schema.validate_wire` plus the structural
assertions below either way, so the battery never depends on a package the
engine does not pin.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time

import pytest

from .. import api
from .. import report as R
from .. import schema as S
from ..adapters.housing import split_plot_stacks
from ..codes import is1905
from ..data._loader import load_yaml
from ..design import common as DC
from ..design import masonry as DM
from ..grid import FrameParams
from ..model import RC_SLAB_MIN_THICKNESS_MM, REGISTRY, StructuralModel, System
from ..placement import frame as PF
from ..placement import masonry as PM

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schema",
    "structural_response.schema.json",
)

try:  # optional: the engine pins no jsonschema, so the battery must not either
    import jsonschema as _jsonschema
except ImportError:  # pragma: no cover - exercised on a machine without it
    _jsonschema = None

#: Wall-clock ceilings per fixture, seconds. These are guards against a
#: pathological regression, not performance targets: the measured local times
#: when this battery was written were 1.6 s (plan, 208 members), 2.1 s (housing,
#: 255) and 9.4 s (building, 775), and the beam designer's bar search is the
#: whole cost. A slower CI box gets room; a runaway loop does not.
BUDGET_S = {"plan": 20.0, "housing": 20.0, "building": 60.0}

#: The classes the v1 RC design layer owns; everything the placer puts down in
#: one of these must come back with a DesignResult or an ERROR that names it.
DESIGNED_CLASSES = ("columns", "beams", "slabs", "footings")


def _load(name):
    with open(os.path.join(FIXTURES, name), "r") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# payloads and cached pipeline runs
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def payloads():
    return {
        "plan": {"source": "plan", "plan": _load("plan_2bhk.json"), "storeys": 2},
        "building": {"source": "building", "building": _load("building_3storey.json")},
        "housing": {"source": "housing", "housing": _load("housing_2storey.json")},
    }


@pytest.fixture(scope="module")
def layouts(payloads):
    out = {}
    for name in sorted(payloads):
        started = time.time()
        out[name] = (api.run_layout(copy.deepcopy(payloads[name])), time.time() - started)
    return out


@pytest.fixture(scope="module")
def designs(payloads):
    out = {}
    for name in sorted(payloads):
        started = time.time()
        out[name] = (api.run_design(copy.deepcopy(payloads[name])), time.time() - started)
    return out


@pytest.fixture(scope="module")
def options():
    return api.run_options()


@pytest.fixture(scope="module")
def validator():
    if _jsonschema is None:
        return None
    with open(SCHEMA_PATH, "r") as handle:
        schema = json.load(handle)
    _jsonschema.Draft202012Validator.check_schema(schema)
    return _jsonschema.Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# shared assertions
# ---------------------------------------------------------------------------


def _entries(envelope):
    return envelope["response"]["Documents"]["structural"]


def _assert_envelope(envelope, validator):
    """Every rule the wire schema states, checked with or without jsonschema."""
    round_tripped = json.loads(json.dumps(envelope))

    if validator is not None:
        problems = sorted(validator.iter_errors(round_tripped), key=lambda e: list(e.path))
        assert not problems, "\n".join(
            "%s: %s" % (list(item.path), item.message) for item in problems[:5]
        )

    assert envelope["status"] in ("SUCCESS", "ERROR")
    assert isinstance(envelope["message"], str)
    assert R.disclaimer_matches(envelope["disclaimer"])

    documents = round_tripped["response"]["Documents"]
    assert documents["schema_version"] == S.STRUCTURAL_SCHEMA_VERSION
    assert documents["engine_fingerprint"].startswith("st-")
    assert isinstance(documents["structural"], list), "Documents.structural is always a list"
    summary = documents["batch_summary"]
    assert summary["plans"] == len(documents["structural"])
    assert summary["ok"] + summary["warnings"] + summary["refused"] == summary["plans"]

    for entry in documents["structural"]:
        assert entry["schema_version"] == S.STRUCTURAL_SCHEMA_VERSION
        assert entry["units"] == S.UNITS
        assert R.disclaimer_matches(entry["disclaimer"])


def _assert_model_wire(entry):
    problems = S.validate_wire(entry["structural_model"])
    assert not problems, problems


# ---------------------------------------------------------------------------
# run_design: the three fixtures, end to end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_design_returns_a_valid_envelope_for_every_source(designs, validator, name):
    envelope, _ = designs[name]
    assert envelope["status"] == "SUCCESS"
    _assert_envelope(envelope, validator)
    for entry in _entries(envelope):
        _assert_model_wire(entry)
        assert entry["footings_sized"] is True
        assert entry["system"] in tuple(member.value for member in System)


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_design_carries_the_verbatim_disclaimer_everywhere_it_is_promised(designs, name):
    envelope, _ = designs[name]
    assert R.disclaimer_matches(envelope["disclaimer"])
    for entry in _entries(envelope):
        assert R.disclaimer_matches(entry["disclaimer"])
        assert R.disclaimer_matches(entry["report"]["disclaimer"])


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_design_list_is_non_empty_and_every_result_is_shaped(designs, name):
    envelope, _ = designs[name]
    for entry in _entries(envelope):
        results = entry["structural_model"]["design"]
        assert results, "a designed model with no design results is a silent gap"
        assert entry["design"]["results_count"] == len(results)
        assert entry["design"]["results_ref"] == "structural_model.design"
        for row in results:
            assert row["element_id"]
            assert row["element_type"]
            assert row["status"] in (DC.STATUS_PASS, DC.STATUS_RESIZED, DC.STATUS_FAIL)


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_design_uses_the_project_minimum_slab_thickness_end_to_end(designs, name):
    """Placement and member design publish the same 150 mm-or-thicker slab."""
    for entry in _entries(designs[name][0]):
        model = entry["structural_model"]
        assert model["slabs"]
        assert all(
            slab["thickness_mm"] >= RC_SLAB_MIN_THICKNESS_MM
            for slab in model["slabs"]
        )
        panel_ids = {slab["id"] for slab in model["slabs"]}
        slab_results = [
            row for row in model["design"] if row["element_id"] in panel_ids
        ]
        assert slab_results
        assert all(
            row["section"]["thickness_mm"] >= RC_SLAB_MIN_THICKNESS_MM
            for row in slab_results
        )
        sectioned_slabs = [
            row
            for row in model["design"]
            if row["element_type"] == "slab" and "D_mm" in row.get("section", {})
        ]
        assert sectioned_slabs
        assert all(
            row["section"]["D_mm"] >= RC_SLAB_MIN_THICKNESS_MM
            for row in sectioned_slabs
        )


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_design_populates_quantities_and_the_boq(designs, name):
    envelope, _ = designs[name]
    for entry in _entries(envelope):
        quantities = entry["structural_model"]["quantities"]
        takeoff = quantities["takeoff"]
        assert takeoff["totals"]["concrete_m3"] > 0.0
        assert takeoff["builtup_area_m2"] > 0.0
        assert takeoff["concrete"], "the concrete take-off ships a row per class"

        boq = quantities["boq"]
        assert boq is not None
        assert boq["items"], "a priced bill with no lines is not a bill"
        assert boq["total"] > 0.0
        assert entry["quantities"]["boq_total"] == boq["total"]
        assert entry["quantities"]["totals"] == takeoff["totals"]


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_every_designable_element_is_designed_or_explicitly_blocked(designs, name):
    """No element of a class the design layer owns disappears without a reason."""
    envelope, _ = designs[name]
    for entry in _entries(envelope):
        model = entry["structural_model"]
        designed = {row["element_id"] for row in model["design"]}
        disclosed = {}
        for item in model["warnings"]:
            for element_id in item["element_ids"]:
                disclosed.setdefault(element_id, []).append(item["code"])

        for slot in DESIGNED_CLASSES:
            for element in model[slot]:
                assert element["id"] in designed or element["id"] in disclosed, (
                    "%s %s was placed but neither designed nor named by a disclosure"
                    % (slot, element["id"])
                )
                for code in disclosed.get(element["id"], ()):
                    assert code in REGISTRY, "a disclosure code must be in the registry"

        # anything the design layer did not reach is listed by id, not lost
        assert entry["design"]["undesigned_count"] == len(
            [
                element["id"]
                for slot in DESIGNED_CLASSES
                for element in model[slot]
                if element["id"] not in designed
                and "E_" not in "".join(disclosed.get(element["id"], []))
            ]
        )

        # the classes v1 does not design are named in the coverage block rather
        # than left as a silent gap
        coverage = entry["design"]["coverage"]
        for slot in ("lintel", "band"):
            row = coverage[slot]
            if row["placed"] and row["undesigned_count"]:
                assert row["reason"]


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_design_stays_inside_its_wall_clock_budget(designs, name):
    _, elapsed = designs[name]
    assert elapsed < BUDGET_S[name], "%s design took %.1f s" % (name, elapsed)


def test_design_reports_the_seismic_case_roster_it_actually_built(designs):
    envelope, _ = designs["plan"]
    entry = _entries(envelope)[0]
    analysis = entry["analysis"]
    assert analysis["method"] == "tributary_takedown_v1"
    assert set(analysis["cases_used"]) >= {"DL", "LL", "LLR"}
    assert [name for name in analysis["cases_used"] if name.startswith("EQ")], (
        "zone III with a storey ledger must produce the four equivalent static cases"
    )
    assert analysis["seismic"]["zone"] == "III"
    assert analysis["seismic"]["system"] == "omrf", "the delivered RC frame uses its ductility row"
    assert entry["options_echo"]["values"]["seismic_system"] == "omrf"
    assert analysis["storey_shears"]["x"], "a seismic case implies a storey shear"


# ---------------------------------------------------------------------------
# run_layout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_layout_returns_a_valid_envelope(layouts, validator, name):
    envelope, _ = layouts[name]
    assert envelope["status"] == "SUCCESS"
    _assert_envelope(envelope, validator)
    for entry in _entries(envelope):
        _assert_model_wire(entry)


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_layout_never_places_a_thin_rc_slab(layouts, name):
    for entry in _entries(layouts[name][0]):
        slabs = entry["structural_model"]["slabs"]
        assert slabs
        assert all(
            slab["thickness_mm"] >= RC_SLAB_MIN_THICKNESS_MM for slab in slabs
        )


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_layout_carries_no_sized_footing(layouts, name):
    """Finding 18: unsized markers at the column stacks, never a sized footing."""
    envelope, _ = layouts[name]
    for entry in _entries(envelope):
        assert entry["footings_sized"] is False
        footings = entry["structural_model"]["footings"]
        assert footings, "a placed frame gets a marker under every ground stack"
        for footing in footings:
            assert footing["w_ft"] is None
            assert footing["h_ft"] is None
            assert footing["depth_ft"] is None
            assert footing["supports"]
        columns = {c["id"] for c in entry["structural_model"]["columns"]}
        for footing in footings:
            assert set(footing["supports"]) <= columns


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_layout_score_is_populated_and_versioned(layouts, name):
    envelope, _ = layouts[name]
    for entry in _entries(envelope):
        score = entry["layout_score"]
        assert score["score"] is not None, "the rc_frame path always scores its layout"
        assert 0 <= score["score"] <= 100
        assert score["score_version"], "finding 33 makes score_version mandatory"
        assert score["metrics"], "the metrics block is mirrored field for field"
        assert "axis_count" in score["metrics"]


def test_layout_and_design_agree_on_the_geometry(layouts, designs):
    """run_design runs the same placement prefix, so the frames must match."""
    layout_entry = _entries(layouts["plan"][0])[0]
    design_entry = _entries(designs["plan"][0])[0]
    for slot in ("columns", "beams", "slabs"):
        assert [row["id"] for row in layout_entry["structural_model"][slot]] == [
            row["id"] for row in design_entry["structural_model"][slot]
        ]
    assert layout_entry["layout_score"]["score"] == design_entry["layout_score"]["score"]


def test_design_does_not_reuse_the_placed_founding_level_as_rc_thickness(designs):
    """A 1.5 m founding level belongs to excavation, not the RC pad section."""
    entry = _entries(designs["plan"][0])[0]
    founding_levels_mm = [
        float(footing["depth_ft"]) * 304.8
        for footing in entry["structural_model"]["footings"]
        if footing["depth_ft"] is not None
    ]
    designed_thicknesses_mm = [
        float(row["section"]["D_mm"])
        for row in entry["structural_model"]["design"]
        if row["element_type"] == "footing" and row["section"].get("D_mm") is not None
    ]
    assert founding_levels_mm and designed_thicknesses_mm
    # The placement model is serialized in feet to six decimals, then brought
    # back to millimetres here, so allow that wire-rounding noise.
    assert min(founding_levels_mm) == pytest.approx(1500.0, abs=0.1)
    assert max(designed_thicknesses_mm) < min(founding_levels_mm)


# ---------------------------------------------------------------------------
# determinism (the backend dedup key depends on it)
# ---------------------------------------------------------------------------


def test_two_layout_runs_are_byte_identical(payloads):
    first = json.dumps(api.run_layout(copy.deepcopy(payloads["plan"])), sort_keys=True)
    second = json.dumps(api.run_layout(copy.deepcopy(payloads["plan"])), sort_keys=True)
    assert first == second


def test_two_design_runs_are_byte_identical(payloads, designs):
    cached = json.dumps(designs["plan"][0], sort_keys=True)
    repeat = json.dumps(api.run_design(copy.deepcopy(payloads["plan"])), sort_keys=True)
    assert cached == repeat


def test_the_payload_hash_is_stable_and_key_order_blind(payloads):
    plain = dict(payloads["plan"])
    reordered = dict(reversed(list(plain.items())))
    assert api.payload_hash(plain) == api.payload_hash(reordered)
    assert api.payload_hash(plain).startswith("sha256:")
    assert len(api.payload_hash(plain)) == len("sha256:") + 64


def test_a_run_does_not_mutate_the_request_it_was_given(payloads):
    payload = copy.deepcopy(payloads["plan"])
    before = json.dumps(payload, sort_keys=True)
    api.run_layout(payload)
    assert json.dumps(payload, sort_keys=True) == before


def test_the_trace_flag_gates_every_clause_trace(payloads, designs):
    """Size discipline: trace off by default, on by asking, and no number moves."""
    quiet_entry = _entries(designs["housing"][0])[0]
    assert quiet_entry["design"]["trace_included"] is False
    assert quiet_entry["report"]["trace_available"] is False
    assert all(row["trace"] == [] for row in quiet_entry["structural_model"]["design"])
    assert all(row["trace_elided"] for row in quiet_entry["structural_model"]["design"])
    assert quiet_entry["structural_model"]["analysis"]["trace"] == []

    loud = api.run_design(copy.deepcopy(payloads["housing"]), output={"trace": True})
    loud_entry = _entries(loud)[0]
    assert loud_entry["design"]["trace_included"] is True
    assert loud_entry["report"]["trace_available"] is True
    assert any(row["trace"] for row in loud_entry["structural_model"]["design"])

    # asking for the working resolves the size regime to `full` too: a caller who
    # wanted the clause trace and got a summary would have to guess a second flag
    assert loud_entry["detail"]["level"] == api.DETAIL_FULL
    assert loud_entry["detail"]["origin"] == "derived from output.trace"

    # turning tracing on changes what is shown, never what was computed
    assert loud_entry["quantities"]["totals"] == quiet_entry["quantities"]["totals"]
    assert loud_entry["design"]["failed_count"] == quiet_entry["design"]["failed_count"]
    assert loud_entry["layout_score"]["score"] == quiet_entry["layout_score"]["score"]
    assert len(json.dumps(loud)) > len(json.dumps(designs["housing"][0]))


# ---------------------------------------------------------------------------
# the size regime (output.detail): what a default response may leave out
# ---------------------------------------------------------------------------

#: The default response of the 775-member building must cross Celery, Redis and
#: then the wire to a browser, so it is budgeted. The number is bytes of the
#: CANONICAL encoding `api.canonical_json` produces, which is what DRF renders
#: and what the backend hashes. The universal 150 mm slab floor makes more of
#: the deliberately difficult building fixture fail member checks; failed rows
#: remain whole by policy, so its compact response is now about 2.14 MB. Full
#: detail remains above 8 MB. These are ceilings, not targets: they catch a
#: bulk block that stopped being elided, not normal drift in actionable failure
#: rows.
DESIGN_BUDGET_BYTES = {"plan": 1000000, "housing": 1200000, "building": 2250000}


def _wire_bytes(payload):
    """What the response weighs on the wire, in bytes, the way api.py encodes it."""
    return len(api.canonical_json(payload).encode("utf-8"))


@pytest.fixture(scope="module")
def full_designs(payloads):
    """The same three fixtures at `output.detail=full`."""
    out = {}
    for name in sorted(payloads):
        out[name] = api.run_design(
            copy.deepcopy(payloads[name]), output={"detail": api.DETAIL_FULL}
        )
    return out


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_the_default_response_stays_inside_its_wire_budget(designs, name):
    """The whole point of the regime: the default payload is small enough to ship."""
    size = _wire_bytes(designs[name][0])
    assert size < DESIGN_BUDGET_BYTES[name], "%s design response is %d bytes" % (name, size)


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_full_detail_is_reachable_and_is_strictly_more(designs, full_designs, name):
    compact = designs[name][0]
    whole = full_designs[name]
    assert _wire_bytes(whole) > _wire_bytes(compact)
    for entry in _entries(compact):
        assert entry["detail"]["level"] == api.DETAIL_COMPACT
        assert entry["detail"]["origin"] == "default"
        assert entry["detail"]["request_flag"] == "output.detail"
    for entry in _entries(whole):
        assert entry["detail"]["level"] == api.DETAIL_FULL
        assert entry["detail"]["origin"] == "request"
        assert entry["detail"]["design_rows_compact"] == 0


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_both_levels_validate_against_the_shipped_schema(designs, full_designs, validator, name):
    _assert_envelope(designs[name][0], validator)
    _assert_envelope(full_designs[name], validator)
    for entry in _entries(designs[name][0]) + _entries(full_designs[name]):
        _assert_model_wire(entry)


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_a_compact_response_carries_every_disclosure_and_the_disclaimer(
    designs, full_designs, name
):
    """Tier 1: the ladder and the notice are never what gets cut."""
    compact = _entries(designs[name][0])[0]
    whole = _entries(full_designs[name])[0]

    def ladder(entry):
        return sorted(
            (row["code"], row["severity"], row["message"])
            for row in entry["errors"] + entry["warnings"]
        )

    assert ladder(compact) == ladder(whole), "compaction must not drop a disclosure"
    assert ladder(compact), "a run this size raises something"
    for text in (
        designs[name][0]["disclaimer"],
        compact["disclaimer"],
        compact["report"]["disclaimer"],
    ):
        assert R.disclaimer_matches(text)


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_a_compact_response_carries_the_whole_boq_and_the_layout_metrics(
    designs, full_designs, name
):
    compact = _entries(designs[name][0])[0]
    whole = _entries(full_designs[name])[0]
    assert compact["structural_model"]["quantities"]["boq"] == (
        whole["structural_model"]["quantities"]["boq"]
    )
    assert compact["report"]["boq"] == whole["report"]["boq"]
    assert compact["report"]["boq"]["items"], "a priced bill with no lines is not a bill"
    assert compact["quantities"]["totals"] == whole["quantities"]["totals"]
    assert compact["report"]["summary"]["totals"] == whole["report"]["summary"]["totals"]
    assert compact["report"]["layout_metrics"] == whole["report"]["layout_metrics"]
    assert compact["layout_score"] == whole["layout_score"]

    # the take-off class rows and their measurement bases survive whole
    lean = compact["structural_model"]["quantities"]["takeoff"]["concrete"]
    rich = whole["structural_model"]["quantities"]["takeoff"]["concrete"]
    assert len(lean) == len(rich)
    for left, right in zip(lean, rich):
        assert left["volume_exact_m3"] == right["volume_exact_m3"]
        assert left["count"] == right["count"]
        assert left["basis"] == right["basis"]
        assert left["element_ids_total"] == len(right["element_ids"])


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_every_element_keeps_its_governing_check_at_the_default_level(
    designs, full_designs, name
):
    """Tier 1: the section, the reinforcement and the governing check, per element."""
    compact = _entries(designs[name][0])[0]
    whole = _entries(full_designs[name])[0]
    rich = {row["element_id"]: row for row in whole["structural_model"]["design"]}
    rows = compact["structural_model"]["design"]
    assert sorted(rich) == sorted(row["element_id"] for row in rows), (
        "compaction must not drop a design result"
    )
    for row in rows:
        source = rich[row["element_id"]]
        assert row["status"] == source["status"]
        assert row["utilization_max"] == source["utilization_max"]
        assert row["governing_check"] == source["governing_check"]
        assert row["section"], row["element_id"]
        if row["detail"] == api.DETAIL_COMPACT:
            assert row["checks_total"] == len(source["checks"])
            assert isinstance(row["reinforcement"], str)
            if source["checks"]:
                assert len(row["checks"]) == 1, "the governing row, and only it"
                named = row["checks"][0]
                assert named["clause"] == next(
                    check["clause"]
                    for check in source["checks"]
                    if check["name"] == named["name"]
                )
            # the section dimensions are the designed ones, not the placer's
            for key, value in row["section"].items():
                assert source["section"][key] == value


@pytest.mark.parametrize("name", ["plan", "building", "housing"])
def test_a_blocked_or_failed_element_is_never_abbreviated(designs, full_designs, name):
    """Tier 2: what a user must act on ships whole at every level."""
    compact = _entries(designs[name][0])[0]
    whole = _entries(full_designs[name])[0]
    rich = {row["element_id"]: row for row in whole["structural_model"]["design"]}

    blocked = set()
    for row in compact["errors"] + compact["warnings"]:
        if row["severity"] == "error":
            blocked.update(row["element_ids"])

    kept = 0
    for row in compact["structural_model"]["design"]:
        if row["status"] != "fail" and row["element_id"] not in blocked:
            continue
        kept += 1
        assert row["detail"] == api.DETAIL_FULL, row["element_id"]
        source = dict(rich[row["element_id"]])
        source.pop("detail", None)
        assert dict(row, detail=None) == dict(source, detail=None), row["element_id"]
    assert kept == compact["detail"]["design_rows_full"]
    assert kept == compact["design"]["failed_count"] + len(
        blocked & set(rich)
    ) - len(
        {one for one in blocked if one in rich and rich[one]["status"] == "fail"}
    )


def test_full_detail_restores_every_block_the_default_level_elides(designs, full_designs):
    """Every `_elided` marker at compact is a block `full` hands back."""
    compact = _entries(designs["building"][0])[0]
    whole = _entries(full_designs["building"])[0]

    lean_model = compact["structural_model"]
    rich_model = whole["structural_model"]

    # the load cases, the takedown and the lateral distribution
    assert lean_model["loads"]["cases"]["DL"]["line"] == []
    assert lean_model["loads"]["cases"]["DL"]["line_total"] == len(
        rich_model["loads"]["cases"]["DL"]["line"]
    )
    assert lean_model["analysis"]["envelopes"] == {}
    assert lean_model["analysis"]["envelopes_total"] == len(rich_model["analysis"]["envelopes"])
    assert lean_model["analysis"]["envelopes_ref"]
    assert rich_model["analysis"]["envelopes"], "full hands the envelopes back"
    assert compact["analysis"]["lateral"]["base_forces"] == {}
    assert whole["analysis"]["lateral"]["base_forces"]

    # the schedules, whose aggregates are identical either way
    lean_bbs = lean_model["quantities"]["bbs"]
    rich_bbs = rich_model["quantities"]["bbs"]
    assert lean_bbs["items"] == []
    assert lean_bbs["items_total"] == rich_bbs["items_total"]
    assert lean_bbs["total_with_wastage_kg"] == rich_bbs["total_with_wastage_kg"]
    assert lean_bbs["mass_by_class"] == rich_bbs["mass_by_class"]
    assert rich_bbs["items"], "full hands the bar schedule back"
    assert lean_model["quantities"]["takeoff"]["concrete_by_element"] == []
    assert rich_model["quantities"]["takeoff"]["concrete_by_element"]

    # the cards, whose fields are the design rows in the same response
    assert compact["report"]["element_cards"] == []
    assert compact["report"]["element_cards_total"] == len(
        compact["structural_model"]["design"]
    )
    assert compact["report"]["cards_elided"] == compact["report"]["element_cards_total"]
    assert compact["report"]["detail"]["element_cards_ref"] == "structural_model.design"
    assert whole["report"]["element_cards"], "full renders the cards"
    assert whole["report"]["cards_elided"] >= 0

    # the model's own ladder points at the entry's, which is whole either way
    assert lean_model["warnings_ref"]
    assert lean_model["warnings_total"] == len(compact["errors"]) + len(compact["warnings"])
    assert all(row["severity"] == "error" for row in lean_model["warnings"])


def test_the_detail_level_is_echoed_and_published(designs, options):
    entry = _entries(designs["building"][0])[0]
    echo = entry["options_echo"]["values"]["output"]
    assert echo["detail"] == api.DEFAULT_DETAIL == api.DETAIL_COMPACT
    assert entry["options_echo"]["origins"]["detail"] == "default"

    published = _entries(options)[0]["detail"]
    assert published["levels"] == list(api.DETAIL_LEVELS)
    assert published["default"] == api.DEFAULT_DETAIL
    assert published["request_flag"] == "output.detail"
    assert published["trace_implies"] == api.DETAIL_FULL
    assert published["policy"], "the regime is documented on the wire, not only in code"
    blocks = {row["block"] for row in published["policy"]}
    assert "structural_model.design[]" in blocks
    for row in published["policy"]:
        assert row["kept"] and row["reason"]
    defaults = _entries(options)[0]["defaults"]["output"]["value"]
    assert defaults["detail"] == api.DEFAULT_DETAIL


def test_the_detail_level_is_accepted_on_params_too_and_validated(payloads):
    envelope = api.run_design(
        copy.deepcopy(payloads["plan"]), params={"detail": api.DETAIL_FULL}
    )
    assert _entries(envelope)[0]["detail"]["level"] == api.DETAIL_FULL

    payload = copy.deepcopy(payloads["plan"])
    payload["output"] = {"detail": "everything"}
    error = _failure(payload, runner=api.run_design)
    assert error["field"] == "output.detail"
    assert "compact" in error["message"]


def test_neither_level_moves_a_number(designs, full_designs):
    """`full` and `compact` are two views of one run, never two runs."""
    for name in ("plan", "building", "housing"):
        compact = _entries(designs[name][0])[0]
        whole = _entries(full_designs[name])[0]
        assert compact["system"] == whole["system"]
        assert compact["status"] == whole["status"]
        assert compact["design"]["results_count"] == whole["design"]["results_count"]
        assert compact["design"]["failed_count"] == whole["design"]["failed_count"]
        assert compact["design"]["coverage"] == whole["design"]["coverage"]
        assert compact["quantities"] == whole["quantities"]
        assert compact["report"]["summary"] == whole["report"]["summary"]
        assert compact["analysis"]["storey_shears"] == whole["analysis"]["storey_shears"]
        assert compact["analysis"]["combos_used"] == whole["analysis"]["combos_used"]
        assert compact["analysis"]["combos_ref"] == "structural_model.loads.combos"
        assert compact["structural_model"]["loads"]["combos"] == (
            whole["structural_model"]["loads"]["combos"]
        )


def test_two_compact_runs_are_byte_identical(payloads, designs):
    """The regime must not cost the backend its Redis dedup key."""
    again = api.run_design(copy.deepcopy(payloads["building"]))
    assert api.canonical_json(again) == api.canonical_json(designs["building"][0])


def test_an_out_of_range_plan_index_is_refused_with_its_registry_code(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["plan_index"] = 9
    error = _failure(payload)
    assert error["code"] == "E_BAD_ENVELOPE"
    assert error["code"] in REGISTRY
    assert "plan_index" in error["message"]


def test_the_report_never_reads_the_clock_unless_a_caller_injects_one(payloads):
    envelope = api.run_design(copy.deepcopy(payloads["housing"]))
    entry = _entries(envelope)[0]
    assert entry["report"]["meta"]["generated_at"] is None

    stamped = api.run_design(
        copy.deepcopy(payloads["housing"]), output={"generated_at": "2026-01-01T00:00:00Z"}
    )
    assert _entries(stamped)[0]["report"]["meta"]["generated_at"] == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# the one bounded referral re-pass (finding 19)
# ---------------------------------------------------------------------------


@pytest.fixture
def referring_slab_designer(monkeypatch):
    """Make every slab refer `add_secondary_beams`, and count the re-places.

    No shipped fixture triggers the referral on its own: the frame placer's own
    feedback loop already subdivides any panel the slab designer would refuse
    (measured, with the secondary spacing clamped to 3.5 m the short side of a
    delivered panel never reaches the 4.5 m the deflection check needs). The
    trigger is therefore injected at the designer boundary, which is exactly the
    seam the orchestrator's re-pass reads, and the referral keeps firing after
    the re-pass so "at most once" is what is actually under test.
    """
    from ..design.rcc import slabs as slab_module

    calls = {"design": 0, "replace": 0}
    real_design = slab_module.design_slab
    real_replace = PF.insert_secondary_beams

    def referring(panel, load, ctx=None):
        calls["design"] += 1
        result = real_design(panel, load, ctx)
        result.add_referral(
            "add_secondary_beams",
            {"element_id": result.element_id, "spacing_m": [2.5, 3.0]},
        )
        return result

    def counting(model, params=None, panel_ids=()):
        calls["replace"] += 1
        return real_replace(model, params, panel_ids)

    monkeypatch.setattr(slab_module, "design_slab", referring)
    monkeypatch.setattr(PF, "insert_secondary_beams", counting)
    return calls


def test_the_referral_re_pass_runs_exactly_once_and_then_stops(payloads, referring_slab_designer):
    envelope = api.run_design(copy.deepcopy(payloads["plan"]))
    entry = _entries(envelope)[0]

    assert entry["design"]["referral_re_passes"] == 1
    assert referring_slab_designer["replace"] == 1, "placement is re-entered once, never twice"
    assert entry["design"]["referrals_applied"][0]["action"] == "add_secondary_beams"
    assert entry["design"]["referrals_applied"][0]["panels"]

    # the referral still fires after the re-pass, and is disclosed rather than chased
    assert entry["design"]["referrals"]["add_secondary_beams"]
    assert {"action": "add_secondary_beams", "count": len(
        entry["design"]["referrals"]["add_secondary_beams"]
    )} in entry["design"]["referrals_outstanding"]
    assert entry["design"]["referrals_outstanding_ids"]
    assert "W_COARSE_ITER" in {item["code"] for item in entry["warnings"]}
    assert envelope["status"] == "SUCCESS", "an open referral is a warning, not a refusal"


def test_a_stage_that_cannot_run_comes_back_as_a_disclosed_partial(payloads, monkeypatch):
    """A raising stage is a labeled refusal with the placed geometry, not a traceback."""
    from ..analysis import takedown as takedown_module

    def exploding(model, loadmodel, opts=None):
        raise takedown_module.AnalysisError(
            "E_ANA_CONSERVATION", "synthetic conservation failure for the battery"
        )

    monkeypatch.setattr(takedown_module, "run", exploding)
    envelope = api.run_design(copy.deepcopy(payloads["plan"]))

    assert envelope["status"] == "ERROR"
    assert R.disclaimer_matches(envelope["disclaimer"])
    entry = _entries(envelope)[0]
    assert entry["status"] == "refused"
    assert entry["partial"] is True
    assert "synthetic conservation failure" in entry["stopped_at"]
    assert entry["structural_model"]["columns"], "the partial still carries its geometry"
    assert "E_ANA_CONSERVATION" in {item["code"] for item in entry["errors"]}


def test_without_a_referral_the_re_pass_never_runs(designs):
    for name in ("plan", "building", "housing"):
        entry = _entries(designs[name][0])[0]
        assert entry["design"]["referral_re_passes"] == 0
        assert entry["design"]["referrals_applied"] == []
        assert entry["design"]["referrals_outstanding"] == []


# ---------------------------------------------------------------------------
# run_check
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def designed_model(designs):
    return copy.deepcopy(_entries(designs["plan"][0])[0]["structural_model"])


def test_check_round_trips_a_designed_model_to_pass(designed_model, validator):
    envelope = api.run_check({"source": "model", "model": copy.deepcopy(designed_model)})
    _assert_envelope(envelope, validator)
    entry = _entries(envelope)[0]
    assert entry["verdict"] == "PASS"
    assert entry["hard_violations"] == []
    assert entry["scope"] == "full"
    assert entry["element_checks"], "scope full re-checks every designed member"
    for row in entry["element_checks"]:
        assert row["element_id"]
        assert row["pass"] in (True, False)


def test_check_placement_scope_is_fast_and_carries_the_score(designed_model, validator):
    started = time.time()
    envelope = api.run_check(
        {"source": "model", "model": copy.deepcopy(designed_model), "scope": "placement"}
    )
    elapsed = time.time() - started
    _assert_envelope(envelope, validator)
    entry = _entries(envelope)[0]
    assert entry["verdict"] == "PASS"
    assert entry["element_checks"] == [], "placement scope runs no member design"
    assert entry["layout_score"]["score"] is not None
    assert entry["layout_score"]["score_version"]
    assert entry["layout_score"]["recomputed"]["column_count"] == len(designed_model["columns"])
    assert elapsed < 10.0, "the placement scope is the sync branch"


def test_check_fails_and_names_the_column_nudged_off_its_axis(designed_model):
    nudged = copy.deepcopy(designed_model)
    moved = nudged["columns"][0]
    moved["x_ft"] = moved["x_ft"] + 3.0

    envelope = api.run_check({"source": "model", "model": nudged, "scope": "placement"})
    entry = _entries(envelope)[0]
    assert entry["verdict"] == "FAIL"
    assert entry["hard_violations"], "a column off its axis is a specific failure, not a shrug"
    codes = {item["code"] for item in entry["hard_violations"]}
    assert "W_ECCENTRIC_COLUMN" in codes
    named = [
        item for item in entry["hard_violations"] if moved["id"] in item["element_ids"]
    ]
    assert named, "the failure names the element that moved"
    assert R.disclaimer_matches(envelope["disclaimer"])


def test_check_reports_the_clause_of_the_governing_check(designed_model):
    envelope = api.run_check({"source": "model", "model": copy.deepcopy(designed_model)})
    rows = _entries(envelope)[0]["element_checks"]
    assert rows
    assert all(row["clause"] for row in rows), "a verdict without its clause is not a check"
    assert all(row["check"] for row in rows)
    assert rows == sorted(rows, key=lambda row: (row["element_type"], row["element_id"]))


def test_check_never_returns_a_moved_model(designed_model):
    envelope = api.run_check({"source": "model", "model": copy.deepcopy(designed_model)})
    entry = _entries(envelope)[0]
    assert "structural_model" not in entry, "a check answers about a model, it does not restate one"


def test_check_reports_a_duplicated_element_id(designed_model):
    broken = copy.deepcopy(designed_model)
    broken["columns"].append(copy.deepcopy(broken["columns"][0]))
    envelope = api.run_check({"source": "model", "model": broken, "scope": "placement"})
    entry = _entries(envelope)[0]
    assert entry["verdict"] == "FAIL"
    assert "E_BAD_ENVELOPE" in {item["code"] for item in entry["hard_violations"]}


def test_check_rejects_a_hand_edited_slab_below_the_project_minimum(designed_model):
    edited = copy.deepcopy(designed_model)
    slab = edited["slabs"][0]
    slab["thickness_mm"] = RC_SLAB_MIN_THICKNESS_MM - 1.0

    envelope = api.run_check({"source": "model", "model": edited, "scope": "placement"})
    entry = _entries(envelope)[0]

    assert entry["verdict"] == "FAIL"
    violations = [
        item
        for item in entry["hard_violations"]
        if item["code"] == "E_SLAB_THICKNESS_MIN"
    ]
    assert violations
    assert slab["id"] in violations[0]["element_ids"]


# ---------------------------------------------------------------------------
# housing: one entry per built plot stack (finding 16)
# ---------------------------------------------------------------------------


def test_housing_returns_one_entry_per_built_plot_stack(payloads, designs):
    housing = payloads["housing"]["housing"]
    built = [stack for stack in split_plot_stacks(housing) if stack["built"]]
    assert built, "the housing fixture has at least one built stack"

    envelope, _ = designs["housing"]
    entries = _entries(envelope)
    assert len(entries) == len(built)
    assert envelope["response"]["Documents"]["batch_summary"]["plans"] == len(built)
    ids = [entry["input_ref"]["model_id"] for entry in entries]
    assert len(set(ids)) == len(ids), "one model id per stack"


def test_a_single_plan_and_a_building_still_come_back_as_a_list(designs):
    for name in ("plan", "building"):
        entries = _entries(designs[name][0])
        assert isinstance(entries, list)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# validation: every rule names its field
# ---------------------------------------------------------------------------


def _failure(payload, runner=None):
    envelope = (runner or api.run_layout)(payload)
    assert envelope["status"] == "ERROR"
    assert R.disclaimer_matches(envelope["disclaimer"]), (
        "finding 29: a refusal carries the notice too"
    )
    documents = envelope["response"]["Documents"]
    assert documents["structural"] == []
    assert documents["batch_summary"]["plans"] == 0
    return documents["error"]


def test_validation_rejects_an_unknown_schema_version(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["schema_version"] = "structural-2"
    error = _failure(payload)
    assert error["field"] == "schema_version"
    assert "structural-1" in error["message"]


def test_validation_requires_a_source(payloads):
    payload = copy.deepcopy(payloads["plan"])
    del payload["source"]
    assert _failure(payload)["field"] == "source"


def test_validation_rejects_an_unknown_source(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["source"] = "sketch"
    assert _failure(payload)["field"] == "source"


def test_validation_requires_the_block_the_source_names():
    error = _failure({"source": "building"})
    assert error["field"] == "building"


def test_validation_rejects_two_source_blocks(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["building"] = payloads["building"]["building"]
    assert _failure(payload)["field"] == "building"


def test_validation_requires_storeys_for_a_plan(payloads):
    payload = copy.deepcopy(payloads["plan"])
    del payload["storeys"]
    error = _failure(payload)
    assert error["field"] == "storeys"
    assert "storey" in error["message"]


def test_validation_caps_rc_storeys(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["storeys"] = api.MAX_STOREYS_RC + 1
    error = _failure(payload)
    assert error["field"] == "storeys"
    assert str(api.MAX_STOREYS_RC) in error["message"]


def test_validation_caps_masonry_storeys_and_tightens_them_in_zone_v(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["storeys"] = api.MAX_STOREYS_MASONRY + 1
    payload["params"] = {"system": "load_bearing_masonry"}
    error = _failure(payload)
    assert error["field"] == "storeys"
    assert str(api.MAX_STOREYS_MASONRY) in error["message"]

    payload["storeys"] = api.MAX_STOREYS_MASONRY_ZONE_V + 1
    payload["params"] = {"system": "load_bearing_masonry", "seismic_zone": "V"}
    error = _failure(payload)
    assert error["field"] == "storeys"
    assert str(api.MAX_STOREYS_MASONRY_ZONE_V) in error["message"]


def test_validation_caps_rooms_per_floor():
    rooms = []
    for index in range(api.MAX_ROOMS_PER_FLOOR + 1):
        x0 = float(index)
        points = [[x0, 0.0], [x0 + 1.0, 0.0], [x0 + 1.0, 10.0], [x0, 10.0]]
        walls = []
        for edge in range(4):
            a = points[edge]
            b = points[(edge + 1) % 4]
            walls.append(
                {
                    "_id": "r%d-w%d" % (index, edge),
                    "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1],
                    "assets": [],
                }
            )
        rooms.append(
            {
                "_id": "r%d" % index,
                "name": "Bedroom %d" % index,
                "label_coord": [x0 + 0.5, 5.0],
                "area": 10.0,
                "width": 1.0,
                "height": 10.0,
                "assets": [],
                "color": "#1C4C82",
                "walls": walls,
                "circular_coordinates": points,
            }
        )
    error = _failure({"source": "plan", "plan": {"floorPlans": [rooms]}, "storeys": 1})
    assert error["field"].startswith("floors[")
    assert error["field"].endswith("].rooms")
    assert str(api.MAX_ROOMS_PER_FLOOR) in error["message"]


def test_validation_rejects_a_negative_plan_index(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["plan_index"] = -1
    assert _failure(payload)["field"] == "plan_index"


def test_validation_rejects_an_unknown_system(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"system": "steel_frame"}
    error = _failure(payload)
    assert error["field"] == "params.system"
    assert "load_bearing_masonry" in error["message"]


def test_validation_rejects_an_unknown_seismic_zone(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"seismic_zone": "VI"}
    assert _failure(payload)["field"] == "params.seismic_zone"


def test_validation_rejects_an_unknown_grade(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"grades": {"concrete": "M15"}}
    assert _failure(payload)["field"] == "params.grades.concrete"

    payload["params"] = {"grades": {"steel": "Fe250"}}
    assert _failure(payload)["field"] == "params.grades.steel"

    payload["params"] = {"grades": {"mortar": "Z9"}}
    assert _failure(payload)["field"] == "params.grades.mortar"


def test_validation_rejects_a_code_profile_this_engine_does_not_speak(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"code_profile": "EC-NL"}
    assert _failure(payload)["field"] == "params.code_profile"


def test_validation_holds_the_span_band(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"spans": {"min_m": 1.0}}
    assert _failure(payload)["field"] == "params.spans.min"

    payload["params"] = {"spans": {"max_m": api.HARD_MAX_SPAN_M + 1.0}}
    assert _failure(payload)["field"] == "params.spans.max"


def test_validation_refuses_a_cantilever_past_the_metric_refusal_length(payloads):
    """Finding 3: the caps are METRES, 2.0 allowed and 2.5 refused."""
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"cantilever": {"max_m": api.REFUSE_CANTILEVER_M + 0.1}}
    error = _failure(payload)
    assert error["field"] == "params.cantilever.max_m"
    assert "2.5" in error["message"]


def test_validation_rejects_a_slab_target_below_the_project_minimum(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"slab": {"t_max_mm": RC_SLAB_MIN_THICKNESS_MM - 1.0}}
    error = _failure(payload)
    assert error["field"] == "params.slab.t_max_mm"
    assert "150 mm project minimum" in error["message"]


def test_validation_rejects_an_unknown_soil(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"soil": "quicksand"}
    assert _failure(payload)["field"] == "params.soil"

    payload["params"] = {"soil": {"type": "IV"}}
    assert _failure(payload)["field"] == "params.soil.type"


def test_validation_caps_housing_floors(payloads):
    payload = copy.deepcopy(payloads["housing"])
    floor = copy.deepcopy(payload["housing"]["floors"][-1])
    while len(payload["housing"]["floors"]) <= api.MAX_HOUSING_FLOORS:
        extra = copy.deepcopy(floor)
        extra["level"] = len(payload["housing"]["floors"])
        extra["id"] = "hf-%d" % extra["level"]
        payload["housing"]["floors"].append(extra)
    assert _failure(payload)["field"] == "housing.floors"


def test_check_validation_names_its_fields(designed_model):
    error = _failure({"source": "model", "model": copy.deepcopy(designed_model), "scope": "sideways"},
                     runner=api.run_check)
    assert error["field"] == "scope"

    error = _failure({"source": "model", "model": {"schema_version": "structural-1.0"}},
                     runner=api.run_check)
    assert error["field"] == "model"


def test_run_design_refuses_the_same_requests_run_layout_does(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"seismic_zone": "IX"}
    assert _failure(payload, runner=api.run_design)["field"] == "params.seismic_zone"


def test_validate_only_short_circuits_before_any_placement(payloads):
    envelope = api.run_design(copy.deepcopy(payloads["building"]), output={"validate_only": True})
    assert envelope["status"] == "SUCCESS"
    entry = _entries(envelope)[0]
    assert entry["validate_only"] is True
    assert "structural_model" not in entry
    assert R.disclaimer_matches(entry["disclaimer"])


# ---------------------------------------------------------------------------
# run_options: generated from the shipped constants, never a second literal
# ---------------------------------------------------------------------------


def test_options_envelope_is_valid(options, validator):
    assert options["status"] == "SUCCESS"
    _assert_envelope(options, validator)


def test_the_shipped_schema_file_is_a_real_draft_2020_12_document():
    with open(SCHEMA_PATH, "r") as handle:
        schema = json.load(handle)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("structural_response-1.1.json")
    # every $ref resolves inside the document
    text = json.dumps(schema)
    for name in set(re.findall(r'"#/\$defs/([A-Za-z_]+)"', text)):
        assert name in schema["$defs"], "dangling $ref to " + name
    if _jsonschema is not None:
        _jsonschema.Draft202012Validator.check_schema(schema)


def test_the_battery_still_checks_the_envelope_without_jsonschema(designs):
    """The engine pins no jsonschema, so the hand checks must stand alone."""
    for name in ("plan", "housing"):
        _assert_envelope(designs[name][0], None)


def test_options_limits_are_the_constants_the_pipeline_enforces(options):
    limits = _entries(options)[0]["limits"]
    defaults = FrameParams()

    assert limits["max_cantilever_m"] == defaults.cantilever_cap
    assert limits["refuse_cantilever_m"] == PF.REFUSE_CANTILEVER_M
    assert limits["min_span_m"] == defaults.min_span
    assert limits["max_span_m"] == defaults.max_primary_span
    assert limits["max_storeys_masonry"] == max(PM.MAX_STOREYS_BY_CATEGORY.values())
    assert limits["max_storeys_masonry_zone_v"] == PM.MAX_STOREYS_BY_CATEGORY["E"]
    assert limits["max_storeys_rc"] == api.MAX_STOREYS_RC
    assert limits["max_rooms_per_floor"] == api.MAX_ROOMS_PER_FLOOR
    assert limits["referral_re_passes"] == api.REFERRAL_RE_PASSES == 1

    # finding 3: the cantilever caps are metres, and 2.0 ft would be nonsense
    assert limits["max_cantilever_m"] == 2.0
    assert limits["refuse_cantilever_m"] == 2.5


def test_options_enums_are_generated_from_the_design_layer(options):
    documents = _entries(options)[0]

    assert documents["grades"]["concrete"] == [
        "M" + str(int(value)) for value in DC.CONCRETE_GRADES_MPA
    ]
    assert documents["grades"]["steel"] == [
        "Fe" + str(int(value)) for value in DC.REBAR_GRADES_MPA
    ]
    assert documents["grades"]["mortar"] == list(is1905.MORTAR_GRADES)
    assert documents["grades"]["masonry_unit_mpa"] == list(DM.DEFAULT_UNIT_STRENGTHS_MPA)
    # the narrow lists the API spec printed are gone (finding 42)
    assert "M40" in documents["grades"]["concrete"]
    assert "H2" in documents["grades"]["mortar"]


def test_options_zones_and_soils_come_from_the_data_tables(options):
    documents = _entries(options)[0]
    zones = load_yaml("is1893")["zone_factor"]["values"]
    assert documents["seismic_zones"] == {str(k): float(v) for k, v in zones.items()}

    soil_table = load_yaml("soil_defaults")
    assert documents["soils"]["types"] == sorted(str(k) for k in soil_table["types"])
    assert documents["soils"]["aliases"] == {
        str(k): str(v) for k, v in soil_table["aliases"].items()
    }
    assert documents["soils"]["defaults"]["founding_depth_m"] == 1.5


def test_options_freeze_the_system_vocabulary(options):
    documents = _entries(options)[0]
    assert documents["systems"] == ["auto"] + list(PM.REQUESTABLE_SYSTEMS)
    assert documents["systems_returned"] == [member.value for member in System]
    assert "masonry" not in documents["systems"], "finding 26 retired the bare word"


def test_options_publish_the_whole_disclosure_registry(options):
    codes = _entries(options)[0]["disclosure_codes"]
    assert set(codes) == set(REGISTRY)
    for code in sorted(REGISTRY):
        assert codes[code]["severity"] == REGISTRY[code][0].value


def test_options_are_pure(options):
    assert json.dumps(api.run_options(), sort_keys=True) == json.dumps(options, sort_keys=True)


# ---------------------------------------------------------------------------
# the soil table and the options echo (findings 29, 30)
# ---------------------------------------------------------------------------


def test_one_soil_table_maps_the_http_words_onto_the_code_types():
    assert api.resolve_soil("hard")["type"] == "I"
    assert api.resolve_soil("medium")["type"] == "II"
    assert api.resolve_soil("soft")["type"] == "III"
    assert api.resolve_soil({"type": "III"})["soft"] is True
    assert api.resolve_soil(None)["founding_depth_m"] == 1.5
    assert api.resolve_soil({"sbc_kpa": 220.0})["sbc_kpa"] == 220.0
    assert "sbc_kpa" in api.resolve_soil(None)["assumed"]


def test_the_resolved_soil_reaches_the_seismic_context_and_the_foundations(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"soil": "soft", "seismic_zone": "IV"}
    envelope = api.run_design(payload)
    entry = _entries(envelope)[0]

    assert entry["options_echo"]["values"]["soil"]["type"] == "III"
    assert entry["analysis"]["seismic"]["soil"] == "III"
    soil = entry["analysis"]["foundations"]["report"]["soil"]
    assert soil["type"] == "III"
    assert soil["soft"] is True
    assert soil["founding_depth_m"] == 1.5
    assert entry["structural_model"]["quantities"]["takeoff"]["options_echo"][
        "founding_depth_m"
    ] == 1.5


def test_the_options_echo_names_the_origin_of_every_default(designs):
    echo = _entries(designs["plan"][0])[0]["options_echo"]
    assert echo["values"]["seismic_zone"] == "III"
    assert echo["origins"]["seismic_zone"] == "default"
    assert echo["values"]["frame_ductility"] == "OMRF"
    assert "seismic_zone" in echo["origins"]["frame_ductility"], (
        "finding 41: the ductility default is derived from the zone, and says so"
    )
    assert echo["origins"]["soil"].endswith("soil_defaults.yaml")


def test_zone_four_resolves_to_smrf(payloads):
    payload = copy.deepcopy(payloads["plan"])
    payload["params"] = {"seismic_zone": "IV"}
    envelope = api.run_layout(payload)
    echo = _entries(envelope)[0]["options_echo"]
    assert echo["values"]["frame_ductility"] == "SMRF"


def test_an_accepted_but_unapplied_option_is_disclosed_not_swallowed(payloads):
    payload = copy.deepcopy(payloads["housing"])
    payload["params"] = {"live_load_kpa": 4.0}
    envelope = api.run_design(payload)
    entry = _entries(envelope)[0]
    echo = entry["options_echo"]
    assert echo["values"]["live_load_kpa"] == 4.0
    fields = [row["field"] for row in echo["unapplied"]]
    assert "params.live_load_kpa" in fields
    assert all(row["reason"] for row in echo["unapplied"])


# ---------------------------------------------------------------------------
# system resolution (finding 27) and envelope acceptance
# ---------------------------------------------------------------------------


def test_auto_delegates_to_choose_system_and_carries_its_trace(designs):
    entry = _entries(designs["plan"][0])[0]
    decision = entry["placement"]["system_decision"]
    assert decision["system_requested"] == "auto"
    assert decision["system"] == entry["system"]
    assert decision["trace"], "the response shows why the system is what it is"
    assert decision["category"] in ("A", "B", "C", "D", "E")


def test_a_refused_masonry_request_falls_back_labeled_rather_than_failing(payloads):
    payload = copy.deepcopy(payloads["building"])
    payload["params"] = {"system": "load_bearing_masonry"}
    envelope = api.run_layout(payload)
    assert envelope["status"] == "SUCCESS"
    entry = _entries(envelope)[0]
    decision = entry["placement"]["system_decision"]
    assert decision["system_requested"] == "load_bearing_masonry"
    assert decision["refused"] is not None
    assert decision["refused"]["clause"]
    assert "W_RELEASED_CAP" in {item["code"] for item in entry["warnings"]}


@pytest.mark.parametrize("shape", ["bare", "documents", "envelope"])
def test_the_plan_envelope_is_accepted_in_every_shape_the_engine_speaks(shape):
    full = _load("plan_2bhk.json")
    documents = full["response"]["Documents"]
    plan = {
        "bare": {"floorPlans": documents["floorPlans"]},
        "documents": {"Documents": documents},
        "envelope": full,
    }[shape]
    envelope = api.run_layout({"source": "plan", "plan": plan, "storeys": 2})
    assert envelope["status"] == "SUCCESS"
    entry = _entries(envelope)[0]
    assert entry["structural_model"]["columns"]
    assert entry["layout_score"]["score"] is not None


def test_a_bare_room_list_is_accepted_too():
    documents = _load("plan_2bhk.json")["response"]["Documents"]
    envelope = api.run_layout(
        {"source": "plan", "plan": documents["floorPlans"][0], "storeys": 1}
    )
    assert envelope["status"] == "SUCCESS"


def test_the_request_may_arrive_inside_the_engine_envelope(payloads):
    wrapped = {"response": {"Documents": copy.deepcopy(payloads["plan"])}}
    direct = json.dumps(api.run_layout(copy.deepcopy(payloads["plan"])), sort_keys=True)
    assert json.dumps(api.run_layout(wrapped), sort_keys=True) == direct


# ---------------------------------------------------------------------------
# the fingerprint the backend hangs its cache on
# ---------------------------------------------------------------------------


def test_the_engine_fingerprint_is_stable_within_a_build():
    first = api.structural_fingerprint()
    assert first == api.structural_fingerprint()
    assert first.startswith("st-")
    assert len(first) == len("st-") + 16


def test_the_engine_fingerprint_changes_for_a_code_only_rollout(monkeypatch):
    monkeypatch.setattr(api, "available_tables", lambda: [])
    monkeypatch.setattr(
        api,
        "_runtime_source_components",
        lambda: [("placement/frame.py", b"candidate = 1\n")],
    )
    api._FINGERPRINT_CACHE.clear()
    first = api.structural_fingerprint()

    monkeypatch.setattr(
        api,
        "_runtime_source_components",
        lambda: [("placement/frame.py", b"candidate = 2\n")],
    )
    api._FINGERPRINT_CACHE.clear()
    second = api.structural_fingerprint()

    assert first != second
    api._FINGERPRINT_CACHE.clear()


def test_the_engine_fingerprint_changes_for_a_json_schema_only_rollout(monkeypatch):
    monkeypatch.setattr(api, "available_tables", lambda: [])
    monkeypatch.setattr(api, "_runtime_source_components", lambda: [])
    monkeypatch.setattr(
        api,
        "_runtime_schema_components",
        lambda: [("schema/structural_response.schema.json", b'{"version": 1}')],
    )
    api._FINGERPRINT_CACHE.clear()
    first = api.structural_fingerprint()

    monkeypatch.setattr(
        api,
        "_runtime_schema_components",
        lambda: [("schema/structural_response.schema.json", b'{"version": 2}')],
    )
    api._FINGERPRINT_CACHE.clear()
    second = api.structural_fingerprint()

    assert first != second
    api._FINGERPRINT_CACHE.clear()


def test_the_model_round_trips_through_its_own_wire_shape(designed_model):
    rebuilt = StructuralModel.from_dict(copy.deepcopy(designed_model))
    assert [c.id for c in rebuilt.columns] == [c["id"] for c in designed_model["columns"]]
    assert [b.id for b in rebuilt.beams] == [b["id"] for b in designed_model["beams"]]
    assert not S.validate_wire(rebuilt.to_dict())
