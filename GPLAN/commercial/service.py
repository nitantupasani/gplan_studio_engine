"""Public bounded, cancellable commercial orchestration entrypoints."""

from copy import deepcopy
import time

from .models import (
    BriefError, ENGINE_VERSION, MAX_ATTEMPTS, MAX_CANDIDATES, MAX_SECONDS,
    MAX_ADJUSTED_SECONDS, MAX_ADJUSTED_BRIEFS,
    RULE_PROFILE, SCHEMA_VERSION, authorized_floors, assessment, fingerprint,
    normalize_brief, unsupported_reasons,
)
from .generation import pack_candidate
from .program import compile_program, lower_area
from .preflight import preflight
from .rules_nl import SOURCE_LEDGER
from .validation import validate_candidate
from .infill import allocate_residual_spaces
from .adjustments import (adjusted_briefs, attach_adjustment_receipt,
                          constraint_deviations, deviation_cost,
                          restoration_briefs, validate_adjusted_brief)
from .adjustments import recovery_brief


def options():
    return {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
            "scope": {"category": "commercial", "subtype": "office", "country": "NL", "regime": "new_build",
                      "geometry": "rectangular", "min_floors": 1, "max_floors": 4, "max_rooms": 64},
            "rules_profile": deepcopy(SOURCE_LEDGER), "search": {"max_attempts": MAX_ATTEMPTS,
                 "max_seconds": MAX_SECONDS + 6.0, "strict_max_seconds": MAX_SECONDS,
                 "fitout_reserved_seconds": 6.0, "modified_programme_max_seconds": MAX_ADJUSTED_SECONDS,
                 "max_candidates": MAX_CANDIDATES},
            "candidate_source": "strict_rectangular_spine_packing"}


def estimate_commercial_fit(brief):
    normal = normalize_brief(brief)
    result = preflight(normal)
    result["brief"] = normal
    result["brief_fingerprint"] = fingerprint(normal)
    result["issues"].extend(unsupported_reasons(normal))
    result["rules_profile"] = deepcopy(SOURCE_LEDGER)
    return result


def _generate_strict(brief, progress=None, cancelled=None, deadline=None, quick=False):
    start = time.monotonic()
    seconds = 4.0 if quick else MAX_SECONDS
    attempts_limit = 12 if quick else MAX_ATTEMPTS
    end = min(start + seconds, deadline if deadline is not None else float("inf"))
    brief = normalize_brief(brief)
    result = {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
              "status": "no_feasible_candidate_found_within_budget", "brief": brief,
              "brief_fingerprint": fingerprint(brief), "candidates": [], "diagnostics": [],
              "rules_profile": deepcopy(SOURCE_LEDGER), "search": {"attempts": 0, "budget_seconds": seconds,
                  "max_attempts": attempts_limit, "floor_counts_examined": [], "stopped_by": "search_space_exhausted",
                  "candidate_source": "strict_rectangular_spine_packing", "global_optimality_claim": False}}

    def emit(stage, fraction, message):
        if progress:
            progress({"stage": stage, "message": message,
                      "completed_attempts": result["search"]["attempts"], "maximum_attempts": attempts_limit})

    def stop(check_attempts=True):
        if cancelled and cancelled():
            result["status"] = "cancelled"
            result["candidates"] = []
            result["search"]["stopped_by"] = "cancelled"
            return True
        if time.monotonic() >= end:
            result["search"]["stopped_by"] = "deadline"
            return True
        if check_attempts and result["search"]["attempts"] >= attempts_limit:
            result["search"]["stopped_by"] = "attempt_limit"
            return True
        return False

    emit("programme", .05, "Compiling semantic requirements and conserved occupancy scenarios")
    unsupported = unsupported_reasons(brief)
    if unsupported:
        result.update(status="unsupported_geometry", diagnostics=unsupported)
        return result
    floors = authorized_floors(brief)
    optimistic = sum(lower_area(r) for r in compile_program(brief))
    gross = brief["site"]["width_m"] * brief["site"]["depth_m"]
    if not floors or optimistic > gross * max(floors):
        result.update(status="infeasible_proven_by_bound", diagnostics=[{
            "code": "hard_area_bound" if floors else "height_bound", "minimum_net_area_m2": optimistic,
            "maximum_gross_area_m2": gross * max(floors, default=0),
            "detail": "Even the optimistic physical-furniture/hard-area lower bound exceeds all authorised gross floor area." if floors else "The allowed height excludes every requested floor count."}])
        return result
    if brief["people"]["staff"] + brief["people"]["visitors"] > 150 or any(r["required_capacity"] > 150 for r in compile_program(brief)):
        result["diagnostics"] = [{"code": "independent_route_scope", "detail": "The one-spine/one-stair candidate source cannot establish the additional independent exits for a population or room above 150 people. A wider route-topology search is required; no general infeasibility is claimed."}]
        result["search"]["stopped_by"] = "candidate_source_scope"
        return result
    seen = set()
    # Reserve comparable attempt coverage for each authorised floor count.
    # Otherwise the first two counts consume almost the entire global limit.
    per_floor_limit = max(1, attempts_limit // len(floors))
    for count in floors:
        if stop():
            break
        result["search"]["floor_counts_examined"].append(count)
        emit("cores", .12 + .12 * count, f"Reserving continuous cores and testing {count} floor{'s' if count > 1 else ''}")
        floor_candidates = 0
        floor_attempts = 0
        orderings = ((3, 1, 2) if count > 1 else (1,)) if quick else ((1, 3, 2, 0) if count > 1 else (1, 2, 0))
        # Compare core/assignment families at the same offset before spending
        # the short recipe budget on three variations of one failing family.
        for offset in (.5, .45, .55):
            for ordering in orderings:
                for spacious in ((False,) if quick else (True, False)):
                    if stop() or floor_attempts >= per_floor_limit:
                        break
                    result["search"]["attempts"] += 1
                    floor_attempts += 1
                    emit("fitting", 0, f"Fitting the {'modified programme' if quick else 'unchanged'} capacities into {count} reserved floor envelopes")
                    candidate, deficit = pack_candidate(brief, count, offset, 1 if ordering == 3 else ordering,
                                                         spacious, core_position="central" if count > 1 and ordering in (1, 2) else "entrance")
                    if candidate is None:
                        if deficit not in result["diagnostics"]:
                            result["diagnostics"].append(deficit)
                        continue
                    if candidate["geometry_fingerprint"] in seen:
                        continue
                    seen.add(candidate["geometry_fingerprint"])
                    emit("circulation", 0, "Measuring the reserved clear routes and real room/core door connections")
                    emit("checking", .65, "Rechecking clear geometry, furniture, stair continuity and obstacle-aware route witnesses")
                    validation = validate_candidate(candidate, brief, sampled=True, include_rules=True)
                    if stop(check_attempts=False):
                        break
                    if not validation["valid"]:
                        failed = [c for c in validation["assessments"] if c["status"] == "failed"]
                        result["diagnostics"].append({"code": "candidate_rejected", "floor_count": count,
                                                       "checks": failed[:6], "failed_check_count": len(failed)})
                        continue
                    candidate["assessments"] = validation["assessments"]
                    candidate["validation_fingerprint"] = fingerprint({"geometry": candidate["geometry_fingerprint"], "brief": candidate["brief_fingerprint"]})
                    result["candidates"].append(candidate)
                    floor_candidates += 1
                    if floor_candidates >= 1:
                        break
                if floor_candidates or floor_attempts >= per_floor_limit or stop():
                    break
            if floor_candidates or floor_attempts >= per_floor_limit or stop():
                break
        if len(result["candidates"]) >= MAX_CANDIDATES:
            result["search"]["stopped_by"] = "candidate_limit"
            break
        if quick and result["candidates"]:
            result["search"]["stopped_by"] = "first_checked_adjustment"
            break
        # Compare one extra authorised floor after the smallest feasible count.
        if result["candidates"] and count > len(result["candidates"][0]["floors"]):
            result["search"]["stopped_by"] = "preferred_and_extra_floor_compared"
            break
    if result["search"]["attempts"] >= attempts_limit and result["search"]["stopped_by"] == "search_space_exhausted":
        result["search"]["stopped_by"] = "attempt_limit"
    if result["candidates"] and result["status"] != "cancelled":
        result["status"] = "review_required"
        result["candidates"].sort(key=lambda c: c["score"])
    elif result["status"] != "cancelled":
        result["diagnostics"].append({"code": "bounded_search_miss", "detail": "No checked candidate was found by the bounded rectangular spine search. Other topologies, additional independent exits or a changed authorised brief may still fit."})
    result["search"]["elapsed_seconds"] = round(time.monotonic() - start, 3)
    result["diagnostics"] = result["diagnostics"][:24]
    emit("complete", 1, "Commercial options are ready for review" if result["candidates"] else "Search finished with the recorded constraints and limitations")
    return result


def generate_commercial_options(brief, progress=None, cancelled=None, deadline=None):
    original = normalize_brief(brief)
    started = time.monotonic()
    # Optional fit-out has its own bounded finishing allowance; it must not
    # halve the strict source's established twelve-second programme search.
    total_budget = MAX_ADJUSTED_SECONDS if original["building"]["allow_programme_adjustments"] else MAX_SECONDS + 6.0
    end = min(started + total_budget, deadline if deadline is not None else float("inf"))
    search_end = max(started, end - min(6.0, total_budget / 2))

    def fit_out(result):
        if result["status"] == "cancelled" or not result["candidates"]:
            return
        if progress:
            progress({"stage": "fitting", "message": "Allocating real furnished support spaces and checking their access and routes."})
        for index, candidate in enumerate(result["candidates"]):
            if time.monotonic() >= end or (cancelled and cancelled()):
                break
            fitted = candidate.get("fitted_brief", original)
            result["candidates"][index] = allocate_residual_spaces(
                candidate, fitted, lambda plan, _: validate_commercial_option(plan, original), end, cancelled)
        if cancelled and cancelled():
            result.update(status="cancelled", candidates=[])

    if not original["building"]["allow_programme_adjustments"]:
        def programme_progress(event):
            if progress and event["stage"] != "complete":
                progress(event)
        result = _generate_strict(original, programme_progress, cancelled, search_end)
        fit_out(result)
        result["search"]["budget_seconds"] = total_budget
        result["search"].update(programme_budget_seconds=MAX_SECONDS, fitout_reserved_seconds=6.0)
        result["search"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if progress:
            progress({"stage": "complete", "message": "Commercial search and supplementary fit-out checks are complete."})
        return result

    def child_progress(event):
        if progress and event["stage"] != "complete":
            progress(event)

    result = _generate_strict(original, child_progress, cancelled, search_end)
    strict_search = deepcopy(result["search"])
    strict_diagnostics = deepcopy(result["diagnostics"])
    original_status = result["status"]
    result["search"].update(budget_seconds=MAX_ADJUSTED_SECONDS, strict_search=strict_search,
                            original_status=original_status, modified_briefs_examined=0,
                            adjustment_attempts=0, max_modified_briefs=MAX_ADJUSTED_BRIEFS,
                            adjustment_policy="preserve_staff_and_visitors_maximise_desks_then_total_room_places",
                            feasible_modified_briefs=0, upward_refinements_examined=0,
                            fitout_reserved_seconds=6.0)

    def finish():
        fit_out(result)
        result["search"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if progress:
            progress({"stage": "complete", "message": "Modified-programme option ready; unmet original requirements are listed." if result["status"] == "modified_programme" else "Commercial search finished with the recorded scope and constraints."})
        return result

    if result["candidates"] or result["status"] in {"cancelled", "unsupported_geometry"}:
        return finish()
    if not authorized_floors(original) or strict_search.get("stopped_by") == "candidate_source_scope":
        return finish()
    result["diagnostics"].append({"code": "original_programme_unfitted", "detail": "The original requirements did not fit the checked search. Comparing useful room counts and capacities while retaining staff, visitors, site, floor allowance, locks, access and sanitary provisions. Desks are reduced only in explicitly disclosed alternatives."})
    recipes = adjusted_briefs(original, result["diagnostics"], MAX_ADJUSTED_BRIEFS)
    recovery = recovery_brief(original) if original["building"].get("auto_add_floors") else None
    if recovery:
        recipes.append(recovery)
    tried, refinement_ids = set(), set()
    best_cost = None
    while recipes and result["search"]["modified_briefs_examined"] < MAX_ADJUSTED_BRIEFS:
        recipes.sort(key=lambda fitted: deviation_cost(original, fitted))
        # Establish a measured fallback first, then improve retained demand.
        # A long sequence of near-original misses must not consume every retry.
        fitted = recipes.pop(recipes.index(recovery)) if recovery is not None else recipes.pop(0)
        recovery = None
        identity = fingerprint(fitted)
        cost = deviation_cost(original, fitted)
        if identity in tried or (best_cost is not None and cost >= best_cost):
            continue
        tried.add(identity)
        if cancelled and cancelled():
            result.update(status="cancelled", candidates=[])
            result["search"]["stopped_by"] = "cancelled"
            break
        if time.monotonic() >= search_end:
            result["search"]["stopped_by"] = "deadline"
            break
        result["search"]["modified_briefs_examined"] += 1
        index = result["search"]["modified_briefs_examined"]
        if identity in refinement_ids:
            result["search"]["upward_refinements_examined"] += 1
        if progress:
            progress({"stage": "adjusting", "message": f"Comparing retained programme capacity: checking alternative {index} within the shared search budget.",
                      "modified_brief_index": index, "maximum_modified_briefs": MAX_ADJUSTED_BRIEFS})
        attempted = _generate_strict(fitted, child_progress, cancelled, search_end, quick=True)
        result["search"]["adjustment_attempts"] += attempted["search"]["attempts"]
        result["search"]["attempts"] = strict_search["attempts"] + result["search"]["adjustment_attempts"]
        if attempted["status"] == "cancelled":
            result.update(status="cancelled", candidates=[])
            result["search"]["stopped_by"] = "cancelled"
            break
        if not attempted["candidates"]:
            continue
        candidate = attempted["candidates"][0]
        deviations = constraint_deviations(original, fitted, candidate)
        if not deviations:
            # Relaxed planning targets can uncover geometry that still meets all
            # original hard requirements. Recheck it against that original brief.
            exact = deepcopy(candidate)
            exact["brief_fingerprint"] = fingerprint(original)
            verified = validate_candidate(exact, original)
            if not verified["valid"]:
                continue
            exact.update(assessments=verified["assessments"], fit_kind="requested_programme", satisfies_original_brief=True)
            result.update(status="review_required", candidates=[exact])
            result["search"]["stopped_by"] = "original_programme_recovered"
            result["search"]["fitted_search"] = attempted["search"]
            return finish()
        else:
            candidate = attach_adjustment_receipt(candidate, original, fitted)
            candidate["original_search"] = {"status": original_status, "diagnostics": strict_diagnostics, "search": strict_search}
            verified = validate_commercial_option(candidate, original)
            if not verified["valid"]:
                continue
            candidate["assessments"] = verified["assessments"]
            result.update(status="modified_programme", candidates=[candidate])
            best_cost = cost
            result["search"]["feasible_modified_briefs"] += 1
            result["search"]["retention_shortfall_score"] = list(cost)
            for restored in restoration_briefs(original, fitted):
                restored_id = fingerprint(restored)
                if restored_id not in tried:
                    refinement_ids.add(restored_id)
                    recipes.append(restored)
        result["search"]["stopped_by"] = "best_checked_modified_programme"
        result["search"]["fitted_search"] = attempted["search"]
    if result["candidates"]:
        result["diagnostics"].append({"code": "modified_programme_available", "detail": "The best checked alternative within the shared budget retains the declared staff and visitors. Workstations are prioritised before total meeting/lunch places; upward refinements were tested where budget allowed. Global optimality is not claimed.",
                                       "constraint_deviations": result["candidates"][0]["constraint_deviations"]})
    elif result["status"] != "cancelled":
        result["diagnostics"].append({"code": "adjustments_exhausted", "detail": "The bounded smaller-programme retries also found no checked layout. Required geometry, stairs, site limits and safety checks were retained; this envelope still needs a different supported configuration."})
    return finish()


def validate_commercial_option(option, brief):
    normal = normalize_brief(brief)
    try:
        if option.get("fit_kind") == "modified_programme":
            fitted, _ = validate_adjusted_brief(normal, option.get("fitted_brief"))
            internal = deepcopy(option)
            internal["brief_fingerprint"] = fingerprint(fitted)
            result = validate_candidate(internal, fitted)
            deviations = constraint_deviations(normal, fitted, internal)
            receipt_ok = bool(deviations) and option.get("satisfies_original_brief") is False
            receipt_ok &= option.get("brief_fingerprint") == fingerprint(normal)
            receipt_ok &= option.get("original_brief_fingerprint") == fingerprint(normal)
            receipt_ok &= option.get("fitted_brief_fingerprint") == fingerprint(fitted)
            receipt_ok &= option.get("constraint_deviations") == deviations
            if not receipt_ok:
                result["assessments"].append(assessment("modified-programme-receipt", "failed", "programme", "The modified-programme receipt does not match the measured unmet requirements",
                                                       "Original and fitted fingerprints, disclosure and independently recomputed differences must agree."))
                result.update(valid=False, status="invalid")
            result.update(fit_kind="modified_programme", satisfies_original_brief=False,
                          fitted_brief=fitted, constraint_deviations=deviations,
                          brief_fingerprint=fingerprint(normal), original_brief_fingerprint=fingerprint(normal),
                          fitted_brief_fingerprint=fingerprint(fitted))
            return result
        if option.get("fitted_brief") or option.get("constraint_deviations"):
            raise BriefError("invalid_adjustment", "A fitted programme must be explicitly identified as modified_programme.")
        return validate_candidate(option, normal)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        return {"schema_version": SCHEMA_VERSION, "valid": False, "status": "invalid",
                "assessments": [assessment("invalid-geometry-contract", "failed", "geometry",
                                           "The edited option has incomplete or unsupported geometry", str(exc))]}


preview = estimate_commercial_fit
generate = generate_commercial_options
validate = validate_commercial_option
