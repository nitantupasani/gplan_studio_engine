"""Deterministic immutable catalogue generation and standalone validation."""

from copy import deepcopy
import json
import time

from .models import EPS, MAX_BODY_BYTES, CirculationError, parse_request, ring, digest, fail
from .registry import ALGORITHMS
from .algorithms import wall_graph, route
from .allocation import allocate
from .geometry import create_geometry, opening_line
from .validation import validate_candidate


def generate_circulation(payload):
    request = parse_request(payload)
    if request.circulation_room_ids:
        from .existing import generate_existing
        return generate_existing(request)
    groups, graph, roots = wall_graph(request)
    started = time.monotonic()
    candidates, diagnostics, seen = [], [], set()
    attempted, duplicates, complete = 0, 0, True

    def deadline():
        if time.monotonic() - started > 12:
            fail("search_timeout", "The bounded circulation search reached its 12-second limit. Returned candidates, if any, were fully validated.")

    for mode in request.modes:
        for root in roots:
            if len(candidates) >= request.candidate_limit:
                complete = False
                break
            attempted += 1
            try:
                deadline()
                selected = route(request, mode, groups, graph, root)
                adjusted, offsets, provenance, constrained = allocate(request, selected, groups, deadline)
                corridor, surface, centerlines, openings, notes, mouth = create_geometry(request, adjusted, selected, groups, offsets, provenance)
                served = sorted({owner for opening in openings if opening["kind"] in ("door", "opening") and opening["width"] >= request.door_width - EPS and corridor.boundary.buffer(EPS * 2).covers(opening_line(opening)) for owner in opening["room_ids"]})
                contributions = [{"room_id": room.id, "before_area": room.shape.area, "after_area": adjusted[room.id].area,
                                  "area_taken": max(0, room.shape.area - adjusted[room.id].area),
                                  "percent_taken": max(0, 100 * (room.shape.area - adjusted[room.id].area) / room.shape.area)} for room in request.rooms]
                changed = [c["room_id"] for c in contributions if c["area_taken"] > EPS]
                eligible = {r.id for r in request.rooms if not r.locked}
                scope = "single_destination" if mode == "shortest" else "all" if set(request.required) == eligible else "selected"
                algorithm = deepcopy(ALGORITHMS[mode])
                label = algorithm["label"] + (" — one selected destination (fixed wall graph)" if mode == "shortest" else " — all rooms" if scope == "all" else " — selected rooms")
                if constrained:
                    notes.append("Hard room constraints/protection limit the preferred sharing ratio; displayed contributions are actual before/after areas.")
                notes.append("Corridors are derived wall-free surfaces. Adjacent room walls and room access openings remain room-owned.")
                if mode == "shortest":
                    notes.append("Exact minimum activated wall-run length on this fixed graph; not a Euclidean path, global all-room optimum, or shortest geometry after boundary shifts. An infeasible optimum is rejected without silently substituting another route.")
                candidate = {
                    "id": "", "schema_version": "1.0", "plan_id": request.plan_id, "source_fingerprint": request.source_fingerprint,
                    "request_fingerprint": request.fingerprint, "units": request.units, "algorithm": algorithm,
                    "label": label, "coverage": {"scope": scope, "required_room_ids": list(request.required), "served_room_ids": served,
                                                   "count": len(set(served) & set(request.required)), "total": len(request.required)},
                    "contribution_policy": request.policy,
                    "adjusted_rooms": [{"id": room.id, "name": room.name, "polygon": ring(adjusted[room.id])} for room in request.rooms],
                    "corridors": [surface], "centerlines": centerlines, "openings": openings,
                    "entry": {"point": list(request.entry), "mouth": mouth},
                    "metrics": {"width": request.width, "length": sum(groups[gid].length for gid in selected),
                                "length_model": "sum_activated_reference_wall_group_lengths",
                                "centerline_length": sum(abs(line["points"][1][0] - line["points"][0][0]) + abs(line["points"][1][1] - line["points"][0][1]) for line in centerlines),
                                "area": corridor.area, "total_room_area_taken": sum(c["area_taken"] for c in contributions),
                                "changed_room_ids": changed, "protected_room_ids": [r.id for r in request.rooms if r.locked or r.protected]},
                    "contributions": contributions, "diagnostics": notes,
                }
                candidate["validation"] = validate_candidate(request, candidate)
                if not candidate["validation"]["valid"]:
                    fail("infeasible_validation", "The proposed boundary shifts fail independent geometry or access validation.", checks=candidate["validation"]["diagnostics"])
                geometry_key = digest({"rooms": candidate["adjusted_rooms"], "surfaces": [s["polygon"] for s in candidate["corridors"]], "openings": openings})
                if geometry_key in seen:
                    duplicates += 1
                    diagnostics.append({"code": "duplicate_geometry", "mode": mode, "message": "This mode produced the same validated geometry as an existing alternative; no duplicate card was added."})
                    continue
                seen.add(geometry_key)
                candidate["geometry_fingerprint"] = geometry_key
                candidate["id"] = "circulation-" + digest({"source": request.fingerprint, "mode": mode, "geometry": geometry_key})[:20]
                candidates.append(candidate)
            except CirculationError as error:
                diagnostics.append({**error.to_dict(), "mode": mode, "root": root})
                if error.code == "search_timeout":
                    complete = False
                    break
        if not complete:
            break
    candidates.sort(key=lambda c: (c["metrics"]["area"], c["metrics"]["length"], c["algorithm"]["id"], c["id"]))
    return {"schema_version": "1.0", "plan_id": request.plan_id, "source_fingerprint": request.source_fingerprint,
            "request_fingerprint": request.fingerprint, "units": request.units,
            "status": "complete" if candidates and complete else "partial" if candidates else "infeasible" if complete else "timed_out",
            "candidates": candidates, "diagnostics": diagnostics,
            "search": {"complete": complete, "attempted": attempted, "deduplicated": duplicates, "deterministic": True}}


def validate_circulation(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("request"), dict):
        fail("invalid_input", "Validation requires {request: <immutable baseline request>, candidate: <proposed candidate>}.")
    try:
        if len(json.dumps(payload, allow_nan=False).encode()) > MAX_BODY_BYTES:
            fail("invalid_candidate", "Circulation validation exceeds the 1 MB limit.")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        if isinstance(error, CirculationError):
            raise
        fail("invalid_candidate", "Validation requires bounded finite JSON values.")
    request = parse_request(payload["request"])
    candidate = payload.get("candidate")
    try:
        digest(candidate)
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("invalid_candidate", "Candidate must contain finite JSON values.")
    validation = validate_candidate(request, candidate)
    if validation["valid"]:
        # The independent checks establish geometry/access. Reproduction also
        # establishes route identity, opening preservation, provenance, labels,
        # minima and metrics instead of trusting client-provided metadata.
        catalogue = generate_circulation(request.raw)
        expected = next((item for item in catalogue["candidates"] if item["id"] == candidate.get("id")), None)
        fields = ("id", "schema_version", "plan_id", "source_fingerprint", "request_fingerprint", "units", "algorithm", "label", "coverage",
                  "contribution_policy", "adjusted_rooms", "corridors", "centerlines", "openings", "entry", "metrics", "contributions", "geometry_fingerprint", "reused_room_ids")
        matches = expected is not None and all(candidate.get(field) == expected.get(field) for field in fields)
        validation["checks"]["reproducible_candidate"] = matches
        if not matches:
            validation["valid"] = False
            validation["diagnostics"].append({"code": "reproducible_candidate", "message": "Candidate geometry, openings, provenance or algorithm metadata differs from the deterministic result for this baseline."})
    return {"schema_version": "1.0", "source_fingerprint": request.source_fingerprint,
            "candidate_id": candidate.get("id"), **validation}
