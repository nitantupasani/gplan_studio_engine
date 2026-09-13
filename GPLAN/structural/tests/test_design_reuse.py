"""Exact-context engineering reuse, concurrency, isolation and fresh provenance."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from .. import api
from ..design_reuse import (
    EngineeringCache, clear_design_cache, design_cache_diagnostics,
    engineering_signature, reuse_design_pass,
)
from ..model import Beam, Column, DisclosureLog, StructuralModel
from .test_housing_variants import request


def signature(model=None, payload=None, resolved=None, engine="engine-a", referral=False):
    return engineering_signature(
        model or StructuralModel(), payload or request(1), resolved or {},
        "rc_frame", True, engine, referral=referral,
    )


def test_signature_excludes_only_explicit_variant_and_search_provenance():
    a = StructuralModel(meta={"frame_placement": {"metrics": {"housing_search": {"selected_rank": 0}}}})
    b = copy.deepcopy(a)
    b.meta["frame_placement"]["metrics"]["housing_search"]["selected_rank"] = 2
    left, right = request(1, "balanced"), request(1, "toward_end")
    assert signature(a, left, vars(api._Resolved(left, {}))) == signature(b, right, vars(api._Resolved(right, {})))
    b.meta["frame_placement"]["stair_slabs"] = [{"length_m": 3.5}]
    assert signature(a, left) != signature(b, left)


@pytest.mark.parametrize("field,value", [
    ("grades", {"concrete": "M30"}), ("soil", {"sbc_kpa": 220}),
    ("spans", {"max_m": 4.0}), ("spans", {"min_m": 2.0}),
    ("code_profile", "another-profile"), ("analysis_mode", "code_complete"),
    ("live_load_kpa", 4), ("rates", {"schedule": "different-rates"}),
    ("storey_height_ft", 12), ("wind", {"basic_speed_ms": 42}),
])
def test_signature_separates_all_engineering_request_context(field, value):
    left = request(1)
    right = copy.deepcopy(left)
    right["params"][field] = value
    assert signature(payload=left) != signature(payload=right)


@pytest.mark.parametrize("field,value", [("trace", True), ("detail", "full"),
                                        ("include_boq", False), ("generated_at", "2026-09-05")])
def test_signature_conservatively_separates_output_context(field, value):
    left, right = request(1), request(1)
    right["output"][field] = value
    assert signature(payload=left) != signature(payload=right)


def test_signature_preserves_exact_si_topology_architecture_and_build():
    model = StructuralModel(
        columns=[Column("c", "stack-c", 0, 1.0, 0.0, 0.23, 0.30)],
        beams=[Beam("b", 0, (1.0, 0.0), (4.0, 0.0), 0.23)],
    )
    base = signature(model)
    changed = copy.deepcopy(model)
    changed.columns[0].x_m += 1e-10
    assert signature(changed) != base  # wire-rounded geometry would miss this
    changed = copy.deepcopy(model)
    changed.beams[0].id = "different-member-identity"
    assert signature(changed) != base
    changed = request(1)
    changed["housing"]["floors"][0]["boundary"][0][0] = 0.01
    assert signature(model, changed) != base
    assert signature(model, engine="engine-b") != base
    assert signature(model, resolved={"unexpected_future_option": 123}) != base
    assert signature(model, referral=True) != base


def test_cache_coalesces_same_key_and_other_keys_continue_independently():
    cache = EngineeringCache()
    entered, release = Event(), Event()

    def slow():
        entered.set()
        assert release.wait(5)
        return {"member": [1]}

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.run, "same", slow)
        assert entered.wait(5)
        second = pool.submit(cache.run, "same", slow)
        other = pool.submit(cache.run, "different", lambda: {"other": 2})
        assert other.result(timeout=5) == {"other": 2}
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    a["member"].append(9)
    assert b == {"member": [1]}
    assert cache.run("same", slow) == b
    assert cache.diagnostics()["expensive_design_invocation_count"] == 2
    assert cache.diagnostics()["cache_hits"] == 2


def test_cache_is_bounded_and_never_retains_failure():
    cache = EngineeringCache(limit=2)
    for key in ("a", "b", "a", "c", "b"):
        cache.run(key, lambda: key)
    assert cache.diagnostics()["cache_entries"] == 2
    assert cache.diagnostics()["expensive_design_invocation_count"] == 4
    with pytest.raises(ValueError):
        cache.run("failure", lambda: (_ for _ in ()).throw(ValueError("refused")))
    assert cache.run("failure", lambda: "repaired") == "repaired"
    assert cache.diagnostics()["failed_invocation_count"] == 1


def test_failed_concurrent_requests_each_keep_their_own_partial_state():
    cache = EngineeringCache()
    entered, joined = Event(), Event()
    states = [{}, {}]

    # The second request enters while the first owns the Future. Observing
    # the Future wait avoids a timing-dependent sleep in this regression.
    def first_compute():
        entered.set()
        assert joined.wait(5)
        states[0]["completed_stage"] = "foundations"
        raise ValueError("member design stopped")

    def second_compute():
        states[1]["completed_stage"] = "foundations"
        raise ValueError("member design stopped")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.run, "same-failure", first_compute)
        assert entered.wait(5)
        pending = cache._pending["same-failure"]
        original_result = pending.result

        def observed_result(*args, **kwargs):
            joined.set()
            return original_result(*args, **kwargs)

        pending.result = observed_result
        second = pool.submit(cache.run, "same-failure", second_compute)
        for future in (first, second):
            with pytest.raises(ValueError, match="member design stopped"):
                future.result(timeout=5)
    assert states == [{"completed_stage": "foundations"}] * 2
    assert cache.diagnostics()["expensive_design_invocation_count"] == 2
    assert cache.diagnostics()["failed_invocation_count"] == 2
    assert cache.diagnostics()["cache_hits"] == 0
    assert cache.diagnostics()["cache_entries"] == 0


def test_cached_mutations_preserve_actual_candidate_metadata_and_options():
    clear_design_cache()
    first, second = request(1, "balanced"), request(1, "toward_end")
    a = StructuralModel(meta={"candidate": "first", "frame_placement": {"metrics": {"housing_search": {"selected_rank": 0}}}})
    b = StructuralModel(meta={"candidate": "second", "frame_placement": {"metrics": {"housing_search": {"selected_rank": 2}}}})
    opts_a, opts_b = api._Resolved(first, {}), api._Resolved(second, {})
    log_a, log_b = DisclosureLog(), DisclosureLog()

    def compute(pass_log):
        a.meta["foundation_plan"] = {"support": "c"}
        a.footings = ["engineered-footing"]
        a.meta["frame_placement"]["designed_foundation"] = "c"
        opts_a.params["computed_context"] = "gravity"
        opts_a.origins["computed_context"] = "design"
        opts_a.mark_unapplied("params.wind", "gravity scope")
        pass_log.add("N_GRAVITY_ONLY", "computed for this pass")
        return {"results": [1]}

    # This unit exercises replay; production callers must first establish key equality.
    reuse_design_pass("unit-pass", a, opts_a, log_a, compute)
    result = reuse_design_pass("unit-pass", b, opts_b, log_b, lambda _: pytest.fail("duplicate design"))
    assert b.meta["candidate"] == "second"
    assert b.meta["foundation_plan"] == {"support": "c"}
    assert b.meta["frame_placement"]["metrics"]["housing_search"]["selected_rank"] == 2
    assert b.meta["frame_placement"]["designed_foundation"] == "c"
    assert opts_b.housing_column_variant == "toward_end"
    assert opts_b.params["housing_column_variant"] == "toward_end"
    assert opts_b.params["computed_context"] == "gravity"
    assert opts_b.unapplied == opts_a.unapplied
    assert log_b.to_dict() == log_a.to_dict()
    result["results"].append(3)
    b.meta["foundation_plan"]["support"] = "mutated"
    assert a.meta["foundation_plan"]["support"] == "c"
    clear_design_cache()


def test_production_repeat_has_identical_response_and_actual_request_provenance():
    clear_design_cache()
    payload = request(1)
    cold = api.run_design(payload)
    assert cold["status"] == "SUCCESS", cold["message"]
    after_cold = design_cache_diagnostics()
    warm = api.run_design(payload)
    assert warm == cold
    assert design_cache_diagnostics()["expensive_design_invocation_count"] == after_cold["expensive_design_invocation_count"]
    assert design_cache_diagnostics()["cache_hits"] > after_cold["cache_hits"]
    warm["response"]["Documents"]["structural"][0]["design"]["failed_count"] = 777
    assert api.run_design(payload) == cold
    clear_design_cache()


def test_production_narrow_variants_never_reuse_distinct_engineering():
    clear_design_cache()
    housing = json.loads((Path(__file__).parent / "fixtures/housing_narrow_25x45_1storey.json").read_text())
    entries = []
    for variant in ("balanced", "toward_start", "toward_end"):
        payload = request(1, variant)
        payload["housing"] = housing
        envelope = api.run_design(payload)
        assert envelope["status"] == "SUCCESS", envelope["message"]
        entry = envelope["response"]["Documents"]["structural"][0]
        assert entry["housing_layout"]["eligible"] is True
        assert entry["housing_layout"]["variant"] == variant
        assert entry["options_echo"]["values"]["housing_column_variant"] == variant
        assert entry["input_ref"]["hash"] == api.payload_hash(payload)
        entries.append(entry)
    same_geometry = len({entry["housing_layout"]["geometry_fingerprint"] for entry in entries})
    diagnostics = design_cache_diagnostics()
    # A broader search may produce genuine alternatives; only truly identical
    # full framed contexts may share their engineering pass.
    assert diagnostics["expensive_design_invocation_count"] >= same_geometry
    if same_geometry == 1:
        assert diagnostics["expensive_design_invocation_count"] == 1
        assert diagnostics["cache_hits"] == 2
    assert len({entry["input_ref"]["hash"] for entry in entries}) == 3
    clear_design_cache()


def _single_bay_requests():
    from .housing_search_fixtures import design_request
    variants = ("balanced", "toward_start", "toward_end")
    payloads = [design_request("regular_generated_2", variant) for variant in variants]
    for payload in payloads:
        payload["housing"]["id"] = "single-bay-reuse"
        floor = payload["housing"]["floors"][0]
        payload["housing"]["floors"] = [floor]
        floor["boundary"] = [[0, 0], [12, 0], [12, 12], [0, 12]]
        generated = floor["boundaryContent"]["generated"]
        generated.update(genW=12, genH=12)
        plan = generated["plans"][0]
        plan.update(floorWidth=12, floorHeight=12)
        plan["placements"] = [{"name": "Living Room", "x": 0, "y": 0, "width": 12, "height": 12}]
    return payloads


def test_production_parallel_repeated_layout_uses_one_pass_and_fresh_provenance():
    clear_design_cache()
    variants = ("balanced", "toward_start", "toward_end")
    payloads = _single_bay_requests()
    with ThreadPoolExecutor(max_workers=3) as pool:
        envelopes = list(pool.map(api.run_design, payloads))
    entries = []
    for variant, payload, envelope in zip(variants, payloads, envelopes):
        assert envelope["status"] == "SUCCESS", envelope["message"]
        entry = envelope["response"]["Documents"]["structural"][0]
        assert entry["housing_layout"]["eligible"] is True
        assert entry["housing_layout"]["variant"] == variant
        assert entry["options_echo"]["values"]["housing_column_variant"] == variant
        assert entry["placement"]["params"]["housing_column_variant"] == variant
        assert entry["input_ref"]["hash"] == api.payload_hash(payload)
        assert entry["housing_layout"]["summary"]
        entries.append(entry)
    assert len({entry["housing_layout"]["geometry_fingerprint"] for entry in entries}) == 1
    assert design_cache_diagnostics()["expensive_design_invocation_count"] == 1
    assert design_cache_diagnostics()["cache_hits"] == 2
    assert len({entry["input_ref"]["hash"] for entry in entries}) == 3
    clear_design_cache()


def test_fallback_rechecks_full_result_without_counting_repeated_geometry(monkeypatch):
    clear_design_cache()
    payload = _single_bay_requests()[1]
    original_attempt = api._design_one_attempt

    def force_initial_refusal(model, source, current_request, opts, ref, housing_recipe=None):
        entry = original_attempt(model, source, current_request, opts, ref, housing_recipe)
        if housing_recipe is None:
            entry["design"]["referrals_outstanding"] = [{"action": "add_secondary_beams", "count": 1}]
        return entry

    monkeypatch.setattr(api, "_design_one_attempt", force_initial_refusal)
    envelope = api.run_design(payload)
    entry = envelope["response"]["Documents"]["structural"][0]
    assert entry["housing_layout"]["eligible"] is True
    assert entry["housing_layout"]["variant"] == "toward_start"
    assert entry["options_echo"]["values"]["housing_column_variant"] == "toward_start"
    assert entry["input_ref"]["hash"] == api.payload_hash(payload)
    assert not entry["design"]["referrals_outstanding"]
    search = entry["layout_score"]["metrics"]["housing_search"]
    assert search["full_design_candidate_attempt_count"] == 2
    assert search["full_design_distinct_layout_count"] == 1
    assert search["full_design_distinct_eligible_layout_count"] == 1
    assert search["checked_legacy_fallback_used"] is True
    assert search["full_design_attempts"][0]["reasons"] == ["unresolved_referral"]
    assert search["objective_stage"] == "final_after_referrals"
    assert search == entry["structural_model"]["meta"]["frame_placement"]["metrics"]["housing_search"]
    assert search == entry["report"]["layout_metrics"]["metrics"]["housing_search"]
    assert design_cache_diagnostics()["expensive_design_invocation_count"] == 1
    assert design_cache_diagnostics()["cache_hits"] == 1
    clear_design_cache()


def test_referral_repair_rechecks_exact_frame_signature(monkeypatch):
    clear_design_cache()
    payload = request(1)
    opts = api._Resolved(payload, {})
    placement = api._Placement()
    model = StructuralModel(beams=[Beam("b", 0, (0.0, 0.0), (4.0, 0.0), 0.23)])
    log = DisclosureLog()

    def compute(current, options, pass_log, placed):
        return {"designed_span": current.beams[0].span_m()}

    monkeypatch.setattr(api, "_design_once", compute)
    original = api._housing_design_pass(model, opts, log, placement, payload)
    model.beams[0].b = (3.0, 0.0)
    repaired = api._housing_design_pass(model, opts, log, placement, payload, referral=True)
    repeated = api._housing_design_pass(model, opts, log, placement, payload, referral=True)
    assert original == {"designed_span": 4.0}
    assert repaired == repeated == {"designed_span": 3.0}
    assert design_cache_diagnostics()["expensive_design_invocation_count"] == 2
    assert design_cache_diagnostics()["referral_requests"] == 2
    assert design_cache_diagnostics()["referral_cache_hits"] == 1
    clear_design_cache()


def test_housing_referral_replaces_old_column_pairs_but_retains_grid_and_errors():
    log = DisclosureLog()
    old_pair = log.add("W_SHORT_SPAN", "old adjacent columns", ["old-a", "old-b"], stage=api._frame._STAGE_COLS)
    grid_gap = log.add("W_SHORT_SPAN", "independent close grid axes", ["x0", "x1"], stage="grid")
    error = log.add("E_SPAN_OVER_MAX", "physical run remains over cap", ["beam"], stage="api.analysis")
    model = StructuralModel(warnings=[old_pair, grid_gap, error])
    api._clear_replaced_housing_span_warnings(model, log)
    assert model.warnings == log.entries == [grid_gap, error]


@pytest.mark.parametrize("reason", ["unresolved_foundation_topology", "quantity_sanity_check_failed",
                                    "invalid_analysis_or_foundation_topology", "cost_not_computed"])
def test_complete_candidate_gate_includes_all_comparison_blockers(reason):
    entry = {"housing_layout": {"eligible": True, "reasons": []},
             "comparison_validity": {"feasible_for_ranking": False, "valid_for_relative_cost_comparison": False,
                                     "reasons": [reason]}}
    assert api._housing_attempt_reasons(entry, api._Resolved(request(1), {})) == [reason]


def test_intentionally_unpriced_output_does_not_trigger_geometry_retry():
    payload = _single_bay_requests()[0]
    payload["output"]["include_boq"] = False
    entry = api.run_design(payload)["response"]["Documents"]["structural"][0]
    assert entry["housing_layout"]["eligible"] is True
    assert entry["comparison_validity"]["feasible_for_ranking"] is False
    assert entry["comparison_validity"]["reasons"] == ["cost_not_computed"]
    search = entry["layout_score"]["metrics"]["housing_search"]
    assert search["full_design_candidate_attempt_count"] == 1
    assert search["checked_legacy_fallback_used"] is False


def test_narrow_three_storey_foundation_overlap_triggers_checked_legacy_fallback():
    from .test_housing_support_search import narrow_request

    payload = narrow_request(3, "toward_end")
    envelope = api.run_design(payload)
    assert envelope["status"] == "SUCCESS", envelope["message"]
    entry = envelope["response"]["Documents"]["structural"][0]
    assert entry["housing_layout"]["eligible"] is True
    assert entry["comparison_validity"]["feasible_for_ranking"] is True
    assert entry["comparison_validity"]["valid_for_relative_cost_comparison"] is True
    assert not entry["comparison_validity"]["reasons"]
    assert entry["housing_layout"]["variant"] == "toward_end"
    assert entry["input_ref"]["hash"] == api.payload_hash(payload)
    search = entry["layout_score"]["metrics"]["housing_search"]
    assert search["full_design_candidate_attempt_count"] == 2
    assert search["checked_legacy_fallback_used"] is True
    assert search["full_design_attempts"][0]["reasons"] == ["unresolved_foundation_topology"]
    assert search["full_design_attempts"][1]["reasons"] == []


@pytest.mark.parametrize("reason", ["unresolved_foundation_topology", "quantity_sanity_check_failed"])
def test_both_failed_comparison_attempts_leave_final_housing_candidate_ineligible(monkeypatch, reason):
    payload = _single_bay_requests()[0]
    original_attempt = api._design_one_attempt

    def block_both(model, source, current_request, opts, ref, housing_recipe=None):
        entry = original_attempt(model, source, current_request, opts, ref, housing_recipe)
        entry["comparison_validity"].update(feasible_for_ranking=False, valid_for_relative_cost_comparison=False,
                                             valid_for_absolute_cost=False, reasons=[reason])
        return entry

    monkeypatch.setattr(api, "_design_one_attempt", block_both)
    entry = api.run_design(payload)["response"]["Documents"]["structural"][0]
    assert entry["housing_layout"]["eligible"] is False
    assert entry["housing_layout"]["reasons"] == [reason]
    assert entry["comparison_validity"]["feasible_for_ranking"] is False
    assert "Both bounded candidate attempts remain ineligible" in entry["housing_layout"]["summary"]
    search = entry["layout_score"]["metrics"]["housing_search"]
    assert search["full_design_candidate_attempt_count"] == 2
    assert search["full_design_distinct_eligible_layout_count"] == 0
    assert all(not attempt["eligible"] and attempt["reasons"] == [reason] for attempt in search["full_design_attempts"])
