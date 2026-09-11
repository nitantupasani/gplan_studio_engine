"""Local engine bridge for gplan-building-designer development.

Serves the endpoints the designer frontend needs with no Django, Celery, or
Redis. Floorplan generation is queued on one local worker so POST returns
promptly and GET polling can expose cumulative progress before completion.
This lets you test engine changes (e.g. cardinal constraints) end-to-end
before deploying.

Run:      python GPLAN/local_engine_bridge.py          (from GPLAN_Revamp root)
          -> http://localhost:8027
Frontend: GPLAN_LOCAL_ENGINE=1 npm run dev             (designer repo)
          vite proxies /api and /users here instead of api.gplan.in.

Endpoints:
    POST /api/generate/<shape>       queue Documents.get_floorplans, return task id
    POST /api/postprocess/floorplans NBC post-processing, synchronous 200
    POST /api/allocate               area-budget allocation, synchronous 200
    GET  /api/structural/options/    structural capability discovery, sync 200
    POST /api/structural/layout/     structural placement, synchronous 200
    POST /api/structural/check/      re-check an edited model, synchronous 200
    POST /api/structural/design/     full structural pipeline, task id (fake async)
    GET  /api/task/<task_id>/        return PENDING/PROGRESS/final stored state
    POST /users/auth/token/refresh/  dummy token so the frontend auth flow passes
    POST /api/v1/authentication/login/  same

Every structural route is registered in both its trailing-slash and its bare
form (finding 37): the frontend calls the slashed path, the Django spec writes
the bare one, and a POST body does not survive an APPEND_SLASH redirect.
"""
import os
import sys
import copy
import concurrent.futures
import json
import uuid
import base64
import socket
import threading
import traceback
import hashlib
from functools import lru_cache
from pathlib import Path

from werkzeug.exceptions import BadRequest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify
from GPLAN.api import Documents, FLOORPLAN_LIMIT
from GPLAN.source.inputgraph import InputGraph

app = Flask(__name__)

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8027
BRIDGE_CAPABILITIES = [
    "circulation_v1",
    "fixed_rooms_v1",
    "fixed_anchor_sw",
    "structural_layout_v1",
    "structural_design_v1",
]

_results = {}
_results_lock = threading.Lock()
# GPLAN temporarily replaces process-global builtins.print while generating.
# A single worker preserves the old serialized execution model while allowing
# the Flask request thread to return a task id immediately.
_generation_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gplan-generation")
_house_jobs = {}
_house_cache = {}


def _house_engine():
    from GPLAN.housing.schema import normalize_request
    from GPLAN.housing import concepts  # noqa: F401

    if not callable(getattr(Documents, "get_house_concepts", None)):
        raise ImportError("This engine does not support house_concepts_v1")
    return Documents.get_house_concepts, normalize_request


@lru_cache(maxsize=1)
def _house_engine_fingerprint():
    """Include programme data in addition to the engine code in house caches."""
    import GPLAN.api as api

    root = Path(api.__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if (path.is_file() and "__pycache__" not in path.parts
                and path.suffix.lower() in {".py", ".json", ".yaml", ".yml"}):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:24]


@app.get("/api/local-bridge/health/")
@app.get("/api/capabilities/")
@app.get("/api/capabilities")
def local_bridge_health():
    """Compatibility probe used by the designer before selecting this bridge."""
    capabilities = list(BRIDGE_CAPABILITIES)
    body = {"status": "ok", "capabilities": capabilities}
    try:
        _house_engine()
        capabilities.append("house_concepts_v1")
        body["engine_fingerprint"] = _house_engine_fingerprint()
    except Exception:
        pass
    return jsonify(body)


def _circulation_response(operation):
    from GPLAN.circulation_engine.http import MAX_BODY_BYTES, dispatch, error_response
    if operation == "options":
        body, code = dispatch(operation)
        return jsonify(body), code
    if (request.content_length or 0) > MAX_BODY_BYTES:
        body, code = error_response("body_too_large", "Circulation accepts at most 1 MB per request.", 413)
        return jsonify(body), code
    from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
    try:
        # A terminated/chunked WSGI stream can have no Content-Length. Read
        # only the limit plus one sentinel byte instead of caching it all.
        raw = request.stream.read(MAX_BODY_BYTES + 1)
    except RequestEntityTooLarge:
        body, code = error_response("body_too_large", "Circulation accepts at most 1 MB per request.", 413)
        return jsonify(body), code
    except BadRequest:
        body, code = error_response("invalid_json", "Send a JSON request body.", 400)
        return jsonify(body), code
    if len(raw) > MAX_BODY_BYTES:
        body, code = error_response("body_too_large", "Circulation accepts at most 1 MB per request.", 413)
        return jsonify(body), code
    try:
        if not request.is_json:
            raise ValueError("JSON content type required")
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        body, code = error_response("invalid_json", "Send a JSON request body.", 400)
        return jsonify(body), code
    try:
        body, code = dispatch(operation, payload)
    except Exception:
        app.logger.exception("Circulation operation failed")
        body, code = error_response("internal_error", "Circulation could not complete this request.", 500)
    return jsonify(body), code


@app.get("/api/circulation/options/")
@app.get("/api/circulation/options")
def circulation_options():
    return _circulation_response("options")


@app.post("/api/circulation/generate/")
@app.post("/api/circulation/generate")
def circulation_generate():
    return _circulation_response("generate")


@app.post("/api/circulation/validate/")
@app.post("/api/circulation/validate")
def circulation_validate():
    return _circulation_response("validate")


def _fake_jwt():
    """Unsigned JWT-shaped token with a far-future exp - only parsed client-side."""
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(b'{"exp":4102444800}').rstrip(b"=")
    return (header + b"." + payload + b".x").decode()


@app.post("/users/auth/token/refresh/")
def refresh():
    return jsonify({"access": _fake_jwt()})


@app.post("/api/v1/authentication/login/")
def login():
    return jsonify({"access": _fake_jwt(), "refresh": _fake_jwt()})


def _prepare(data, shape):
    """Mirror gplan_apis.views.GenerateFloorplanView request preparation."""
    nodes_list = data.get("nodes", [])
    edges_list = data.get("edges", [])
    for node in nodes_list:
        node.setdefault("color", "#1C4C82")
        node.setdefault("ratio", {"max": 99999, "min": 3})
    nodes_list.sort(key=lambda node: node["id"])
    nodes = [[node.get("x", 0), node.get("y", 0)] for node in nodes_list]
    edges = [[e["source"], e["target"], e.get("color", "black")]
             for e in edges_list if e.get("color", "black") == "black"]
    non_adj_edges = [(e["source"], e["target"])
                     for e in edges_list if e.get("color", "black") == "red"]
    graph = InputGraph(len(nodes), len(edges), edges, nodes)

    non_adj = data.get("non_adj", False)
    if len(non_adj_edges) == 0:
        non_adj = False

    dimensioned = data.get("dimensioned", False)
    min_dim_enabled = data.get("minDimEnabled", False)
    max_dim_enabled = data.get("maxDimEnabled", False)
    dim_inputs = {
        "min_width": [], "max_width": [], "min_height": [], "max_height": [],
        "min_ratio": [], "max_ratio": [], "min_area": [], "max_area": [],
        "plot_width": -1, "plot_height": -1,
        "symmetric": False, "optimal_floorplan": 0, "rotation_enabled": 1,
    }
    # minDim: client dims are minimums only, so max stays open unless the client
    # opts in with maxDimEnabled (then the room ceilings are honoured).
    open_max = min_dim_enabled and not max_dim_enabled
    if dimensioned or min_dim_enabled:
        for node in nodes_list:
            default_min = 0 if dimensioned else 3
            if node.get("width") is not None:
                dim_inputs["min_width"].append(node["width"].get("min", default_min) or default_min)
                dim_inputs["max_width"].append(
                    99999 if open_max else (node["width"].get("max", 99999) or 99999))
                # explicit per-room area rule, index-aligned with the width
                # arrays; same maxDimEnabled opt-in as the span ceilings
                dim_inputs["min_area"].append(node.get("min_area") or 0)
                dim_inputs["max_area"].append(
                    0 if open_max else (node.get("max_area") or 0))
            if node.get("height") is not None:
                dim_inputs["min_height"].append(node["height"].get("min", default_min) or default_min)
                dim_inputs["max_height"].append(
                    99999 if open_max else (node["height"].get("max", 99999) or 99999))
            if node.get("ratio") is not None:
                dim_inputs["min_ratio"].append(node["ratio"].get("min", 0.5) or 0.5)
                dim_inputs["max_ratio"].append(node["ratio"].get("max", 2) or 2)
        dim_inputs["plot_width"] = data.get("plot_width", 0)
        dim_inputs["plot_height"] = data.get("plot_height", 0)
        dim_inputs["symmetric"] = data.get("symmetric", False)
        dim_inputs["optimal_floorplan"] = data.get("optimal_floorplan", 1)
        dim_inputs["rotation_enabled"] = data.get("rotation_enabled", 1)
        # Hard plot-fit opt-in: strict_plot_width/height carry the caller's
        # REAL footprint (plot_width/plot_height keep their slack rejection-cap
        # role for backends and clients that predate the flag). When present,
        # the strict pair replaces the solver plot and enforce_plot rides on
        # dim_inputs so the engine solves the full pool under the real cap.
        if min_dim_enabled and data.get("enforce_plot"):
            strict_w = data.get("strict_plot_width") or 0
            strict_h = data.get("strict_plot_height") or 0
            if strict_w > 0 and strict_h > 0:
                dim_inputs["plot_width"] = strict_w
                dim_inputs["plot_height"] = strict_h
                dim_inputs["enforce_plot"] = True

    return dict(
        starting_from=data.get("starting_from", 0),
        count=data.get("count", 0),
        caller=shape,
        nodes_list=nodes_list,
        graph=graph,
        edges_list=edges,
        non_adj_edge_list=non_adj_edges,
        rectangular=data.get("rectangular", False),
        corridor=data.get("corridor", False),
        dimensioned=dimensioned,
        dimensionedCirculation=data.get("dimensionedCirculation", False),
        minDimEnabled=min_dim_enabled,
        removeAddCirculation=data.get("removeAddCirculation", False),
        publicEnabled=data.get("publicEnabled", False),
        nonAdj=non_adj,
        normalize_const=data.get("normalizeConst", False),
        limit=data.get("limit", FLOORPLAN_LIMIT),
        corridor_thickness=data.get("corridorThickness", None),
        documentID=data.get("documentID", None),
        name=data.get("name", None),
        dim_inputs=dim_inputs,
        circulationEnabled=data.get("circulationEnabled", 0),
        cardinal_constraints=data.get("cardinal_constraints", []),
        postProcessEnabled=data.get("postProcessEnabled", False),
        postprocess_options=data.get("postprocess_options", None),
    )


@app.post("/api/postprocess/floorplans")
def postprocess_floorplans():
    """Local stand-in for the Django post-processing endpoint.

    Synchronous like the real one: pure geometry, returns 200 with the result
    directly (no task id, no polling).
    """
    try:
        body = request.get_json(force=True) or {}
        response, message = Documents.postprocess_floorplans(body)
        plans = response["Documents"]["floorPlans"]
        changed = sum(1 for r in response["Documents"]["postprocess"]
                      if r and r.get("changed"))
        print(f"[bridge] postprocess: {changed}/{len(plans)} plans adjusted")
        return jsonify({"message": message, "response": response}), 200
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"status": "error", "data": {},
                        "error": {"message": str(exc),
                                  "type": type(exc).__name__}}), 500


@app.post("/api/allocate")
def allocate_program():
    """Local stand-in for the Django allocation endpoint. Synchronous like
    the real one: pure arithmetic, 200 with the result directly; semantic
    problems (ValueError) come back as the same 400 envelope."""
    try:
        body = request.get_json(force=True) or {}
        response, message = Documents.allocate_program(body)
        alloc = response["allocation"]
        print(f"[bridge] allocate: {len(alloc['rooms'])} rooms, "
              f"plot {alloc['plot']['width']}x{alloc['plot']['height']}, "
              f"fits={alloc['fits']}")
        return jsonify({"message": message, "response": response}), 200
    except ValueError as exc:
        return jsonify({"status": "error", "data": {},
                        "error": {"message": str(exc),
                                  "type": "ValidationError"}}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"status": "error", "data": {},
                        "error": {"message": str(exc),
                                  "type": type(exc).__name__}}), 500


# ---------------------------------------------------------------------------
# structural module (documentation/structural_api.md)
#
# Registered BEFORE the /api/generate/<shape> catch-all, next to the
# postprocess routes. The engine call always happens inside the route body,
# never at import time, so a structural package that cannot import takes only
# these four routes down and leaves generation working.
# ---------------------------------------------------------------------------


def _structural_refusal(envelope):
    """The engine's own error block, when the request was one it will not run.

    The structural entry points never raise for a bad request: they return
    their ERROR envelope with `response.Documents.error` naming the field.
    That block is the difference between "this request is wrong" (400) and
    "here is your answer, and one plan came back refused" (200, envelope
    status ERROR, partial model attached).
    """
    if not isinstance(envelope, dict):
        return None
    documents = (envelope.get("response") or {}).get("Documents") or {}
    error = documents.get("error")
    return error if isinstance(error, dict) else None


def _structural_500(exc):
    """A stage that raised out of the engine, in the bridge's error shape."""
    traceback.print_exc()
    return jsonify({"status": "error", "data": {},
                    "error": {"message": str(exc),
                              "type": type(exc).__name__}}), 500


def _structural_counts(envelope):
    """'2 entries, 1 refused' for the console line."""
    documents = (envelope.get("response") or {}).get("Documents") or {}
    summary = documents.get("batch_summary") or {}
    return "%s entr%s, %s refused" % (
        summary.get("plans", 0),
        "y" if summary.get("plans", 0) == 1 else "ies",
        summary.get("refused", 0))


@app.get("/api/structural/options/")
@app.get("/api/structural/options")
def structural_options():
    """Static capability discovery: systems, zones, soils, grades, limits.

    Pure and cheap, takes no request; the frontend reads it so it never
    hardcodes a grade list or a zone factor.
    """
    try:
        envelope = Documents.structural_options()
        return jsonify(envelope), 200
    except Exception as exc:
        return _structural_500(exc)


@app.post("/api/structural/layout/")
@app.post("/api/structural/layout")
def structural_layout():
    """Structural placement, synchronous like the real one: pure geometry,
    200 with the result directly (no task id, no polling). Footings come back
    as unsized markers - sizing needs a takedown layout does not run.

    A request the engine refuses to run is a 400 carrying the engine's own
    error envelope verbatim, so the caller keeps the field name AND the
    disclaimer; a plan that came back refused is still a 200.
    """
    try:
        body = request.get_json(force=True) or {}
        envelope = Documents.layout_structure(body)
    except Exception as exc:
        return _structural_500(exc)
    error = _structural_refusal(envelope)
    if error:
        print("[bridge] structural layout: refused - %s" % error.get("message"))
        return jsonify(envelope), 400
    print("[bridge] structural layout: %s; %s"
          % (envelope.get("message"), _structural_counts(envelope)))
    return jsonify(envelope), 200


@app.post("/api/structural/check/")
@app.post("/api/structural/check")
def structural_check():
    """Re-check a structural_model this engine returned, possibly hand-edited.

    The bridge is ALWAYS synchronous here; Django picks sync or async by size.
    Nothing moves an element: the answer is a verdict, the hard violations,
    the score and the per-member checks.
    """
    try:
        body = request.get_json(force=True) or {}
        envelope = Documents.check_structure(body)
    except Exception as exc:
        return _structural_500(exc)
    error = _structural_refusal(envelope)
    if error:
        print("[bridge] structural check: refused - %s" % error.get("message"))
        return jsonify(envelope), 400
    print("[bridge] structural check: %s" % envelope.get("message"))
    return jsonify(envelope), 200


@app.post("/api/structural/design/")
@app.post("/api/structural/design")
def structural_design():
    """Full structural pipeline. Fake-async, exactly like the generate routes:
    computed synchronously here (no Celery, no Redis locally), stored under a
    task id in the terminal shape the poller expects, answered 202 so the
    frontend polls GET /api/task/<id>/ the same way it does against Django.

    A request the engine will not run is a 400 straight away rather than a
    task that fails a poll later; a stage that raises becomes a stored
    FAILURE, which is what the generate routes do.
    """
    task_id = str(uuid.uuid4())
    try:
        body = request.get_json(force=True) or {}
        envelope = Documents.design_structure(body)
    except Exception as exc:
        traceback.print_exc()
        with _results_lock:
            _results[task_id] = {"status": "FAILURE",
                                 "error": {"message": str(exc),
                                           "type": type(exc).__name__}}
        print("[bridge] structural design: stage raised - %s" % exc)
        return jsonify({"task_id": task_id, "status": "started"}), 202
    error = _structural_refusal(envelope)
    if error:
        print("[bridge] structural design: refused - %s" % error.get("message"))
        return jsonify(envelope), 400
    with _results_lock:
        _results[task_id] = envelope
    print("[bridge] structural design: %s; %s"
          % (envelope.get("message"), _structural_counts(envelope)))
    return jsonify({"task_id": task_id, "status": "started"}), 202


@app.post("/api/generate/multi-ptpg")
def generate_multi_ptpg():
    """Local stand-in for the Django multi-PTPG endpoint (no Celery, no Redis).

    Registered before the ``<shape>`` route so Flask does not route it there;
    the response envelope matches the backend so the frontend polls identically.
    """
    task_id = str(uuid.uuid4())
    try:
        body = request.get_json(force=True)
        params = body.get("params", {})
        pins = params.get("cardinal_constraints") or []
        print(f"[bridge] multi-ptpg: rooms={len(params.get('nodes', []))} "
              f"edges={len(params.get('edges', []))} "
              f"strictness={params.get('strictness', 'relaxed')} "
              f"max_variants={params.get('max_variants', 'default')} "
              f"max_depth={params.get('max_depth', 'default')} "
              f"max_floorplans={params.get('max_floorplans', 'default')} "
              f"pins={len(pins)}")
        result = Documents.get_multi_ptpg_floorplans(body)
        data = result.get("data") or {}
        card = data.get("cardinal") or {}
        print(f"[bridge] multi-ptpg: done - {data.get('variant_count', 0)} variants, "
              f"{data.get('floorplan_count', 0)} floorplans"
              + (f", pins {'IGNORED' if card.get('ignored') else 'applied'}"
                 if pins else ""))
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "error", "engine": "MultiPTPG_FloorPlan",
                  "data": {}, "error": {"message": str(exc)}}
    with _results_lock:
        _results[task_id] = result
    return jsonify({"task_id": task_id, "status": "started"}), 202


def _house_owner():
    header = request.headers.get("Authorization", "").strip()
    identity = "credential:%s" % header if header else "ip:%s" % (request.remote_addr or "")
    return hashlib.sha256(identity.encode()).hexdigest()


def _house_catalogue(value, require_options=False):
    """Keep the bridge's progress/terminal gate identical to the Django task."""
    catalogue = json.loads(json.dumps(value, allow_nan=False))
    if (not isinstance(catalogue, dict)
            or catalogue.get("schema_version") != "house_concepts_v1"):
        raise ValueError("Invalid house catalogue schema_version")
    if catalogue.get("units") != "mm":
        raise ValueError("House catalogue geometry must use millimetres")
    options = catalogue.get("options")
    if not isinstance(options, list) or (require_options and not options):
        raise ValueError("House catalogue must contain complete validated options")
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("Invalid house option")
        validation = option.get("validation")
        floors = option.get("floors")
        if (not isinstance(validation, dict) or validation.get("valid") is not True
                or not isinstance(floors, list) or len(floors) not in (3, 4)
                or any(not isinstance(floor, dict) or not isinstance(floor.get("rooms"), list) or not floor["rooms"]
                       for floor in floors)):
            raise ValueError("House option is incomplete or has not passed validation")
    return catalogue


def _house_envelope(catalogue):
    catalogue = _house_catalogue(catalogue)
    count = len(catalogue["options"])
    return {"message": "%d validated whole-house option%s generated." %
                       (count, "" if count == 1 else "s"),
            "response": {"HouseConcepts": catalogue}}


def _house_cancelled():
    return {"status": "CANCELLED", "message": "House generation cancelled.",
            "error": {"type": "Cancelled", "message": "House generation cancelled."}}


def _run_house_generation(task_id, payload, engine):
    with _results_lock:
        job = _house_jobs[task_id]
        cached = _house_cache.get(job["cache_key"])
    if job["cancel"].is_set():
        return
    sequence = 0

    def report(value):
        nonlocal sequence
        try:
            catalogue = _house_catalogue(value, require_options=True)
            metadata = {
                "partial": True, "complete": False, "provisional": True,
                "progress": {"sequence": sequence + 1,
                             "ready": len(catalogue["options"]),
                             "requested": payload["requested_options"]},
                **_house_envelope(catalogue),
            }
            with _results_lock:
                if job["cancel"].is_set():
                    return
                _results[task_id] = {"task_id": task_id, "status": "PROGRESS",
                                     "result": metadata}
                sequence += 1
        except Exception:
            # An observer failure or unfinished stack never fails the solve.
            return

    report.is_cancelled = job["cancel"].is_set
    try:
        result = copy.deepcopy(cached) if cached is not None else _house_envelope(
            engine(payload, progress_callback=report))
        result["status"] = "SUCCESS"
        with _results_lock:
            if not job["cancel"].is_set():
                _results[task_id] = result
                _house_cache[job["cache_key"]] = copy.deepcopy(result)
    except Exception as exc:
        traceback.print_exc()
        with _results_lock:
            if not job["cancel"].is_set():
                _results[task_id] = {"status": "FAILURE",
                                     "error": {"message": str(exc),
                                               "type": type(exc).__name__}}


@app.post("/api/generate/house_concepts")
@app.post("/api/generate/house_concepts/")
def generate_house_concepts():
    """Validate first, then use the same one-worker queue as floor generation."""
    try:
        body = request.get_json(force=True)
    except BadRequest as exc:
        return jsonify({"status": "error", "data": {},
                        "error": {"message": str(exc), "type": "ValidationError"}}), 400
    if not isinstance(body, dict):
        return jsonify({"status": "error", "data": {},
                        "error": {"message": "Request body must be a JSON object",
                                  "type": "ValidationError"}}), 400
    try:
        engine, normalize = _house_engine()
    except Exception:
        return jsonify({"status": "error", "data": {},
                        "error": {"message": "This engine does not support house_concepts_v1",
                                  "type": "CapabilityUnavailable"}}), 503
    try:
        payload = json.loads(json.dumps(normalize(body), allow_nan=False))
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"status": "error", "data": {},
                        "error": {"message": str(exc), "type": "ValidationError"}}), 400
    task_id = str(uuid.uuid4())
    try:
        owner = _house_owner()
        cache_data = {"request": payload, "owner": owner,
                      "engine": _house_engine_fingerprint(), "schema": "house_concepts_v1"}
        cache_key = hashlib.sha256(json.dumps(cache_data, sort_keys=True,
                                             allow_nan=False).encode()).hexdigest()
        with _results_lock:
            _house_jobs[task_id] = {"owner": owner, "cache_key": cache_key,
                                    "cancel": threading.Event(), "future": None}
            cached = _house_cache.get(cache_key)
            _results[task_id] = copy.deepcopy(cached) if cached is not None else {
                "task_id": task_id, "status": "PENDING", "result": None}
        if cached is None:
            future = _generation_executor.submit(_run_house_generation, task_id, payload, engine)
            with _results_lock:
                _house_jobs[task_id]["future"] = future
        return jsonify({"task_id": task_id, "status": "started"}), 202
    except Exception:
        traceback.print_exc()
        with _results_lock:
            _house_jobs.pop(task_id, None)
            _results.pop(task_id, None)
        return jsonify({"status": "error", "data": {},
                        "error": {"message": "House generation could not be queued; retry shortly",
                                  "type": "ServiceUnavailable"}}), 503


@app.post("/api/task/<task_id>/cancel/")
@app.post("/api/task/<task_id>/cancel")
def cancel_house_task(task_id):
    with _results_lock:
        job = _house_jobs.get(task_id)
        if job is None:
            return jsonify({"status": "error", "data": {},
                            "error": {"message": "House task not found", "type": "NotFound"}}), 404
        if job["owner"] != _house_owner():
            return jsonify({"status": "error", "data": {},
                            "error": {"message": "This house task belongs to another caller",
                                      "type": "PermissionDenied"}}), 403
        state = (_results.get(task_id) or {}).get("status")
        if state in {"SUCCESS", "FAILURE", "CANCELLED"}:
            return jsonify({"task_id": task_id, "status": "complete"})
        job["cancel"].set()
        _results[task_id] = _house_cancelled()
        future = job["future"]
    if future is not None:
        # Only queued work can be cancelled this way; running GPLAN is stopped
        # cooperatively between floor solves, never by interrupting global state.
        future.cancel()
    return jsonify({"task_id": task_id, "status": "cancelled"})


def _run_floorplan_generation(task_id, shape, kwargs):
    """Run one queued generation and publish Celery-shaped progress."""
    sequence = 0
    requested = int(kwargs.get("count") or 0)

    def publish_progress(partial_result):
        nonlocal sequence
        try:
            # Round-trip through JSON before exposing the snapshot. This both
            # detaches it from engine mutation and enforces the bridge's wire
            # contract (no numpy values, graph objects, NaN, or callbacks).
            partial = json.loads(json.dumps(
                copy.deepcopy(partial_result), allow_nan=False))
            documents = partial.get("response", {}).get("Documents", {})
            floorplans = documents.get("floorPlans")
            if not isinstance(floorplans, list) or not floorplans:
                return
            ready = len(floorplans)
            documents["count"] = ready
            sequence += 1
            result = {
                "partial": True,
                "complete": False,
                "provisional": bool(partial.get("provisional", True)),
                "progress": {
                    "sequence": sequence,
                    "ready": ready,
                    "requested": requested,
                },
                "message": partial.get("message", ""),
                "response": partial["response"],
            }
            with _results_lock:
                _results[task_id] = {
                    "task_id": task_id,
                    "status": "PROGRESS",
                    "result": result,
                }
        except Exception:
            # A progress transport failure must not fail generation.
            return

    try:
        floorplans, message = Documents.get_floorplans(
            **kwargs, progress_callback=publish_progress)
        result = {"status": "SUCCESS", "message": message,
                  "response": floorplans.to_dict()}
        print(f"[bridge] {shape}: done - "
              f"{len(result['response']['Documents']['floorPlans'])} floorplans; {message!r}")
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "FAILURE", "error": {"message": str(exc)}}
    with _results_lock:
        _results[task_id] = result


@app.post("/api/generate/<shape>")
def generate(shape):
    task_id = str(uuid.uuid4())
    with _results_lock:
        _results[task_id] = {
            "task_id": task_id,
            "status": "PENDING",
            "result": None,
        }
    try:
        kwargs = _prepare(request.get_json(force=True), shape)
        print(f"[bridge] {shape}: nodes={len(kwargs['nodes_list'])} "
              f"edges={len(kwargs['edges_list'])} "
              f"cardinal={kwargs['cardinal_constraints']}")
        _generation_executor.submit(
            _run_floorplan_generation, task_id, shape, kwargs)
    except Exception as exc:
        traceback.print_exc()
        with _results_lock:
            _results[task_id] = {
                "status": "FAILURE", "error": {"message": str(exc)}}
    return jsonify({"task_id": task_id, "status": "started"}), 202


@app.get("/api/task/<task_id>/")
def task(task_id):
    with _results_lock:
        result = _results.get(task_id)
    if result is None:
        return jsonify({"status": "PENDING"})
    return jsonify(result)


if __name__ == "__main__":
    # Werkzeug enables address reuse for quick restarts. On Windows that can
    # allow an old and a new development bridge to listen on the same port,
    # randomly routing requests to different engine checkouts. Refuse to start
    # while any listener is already present so test results are deterministic.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex((BRIDGE_HOST, BRIDGE_PORT)) == 0:
            raise SystemExit(
                "[bridge] port 8027 is already in use. Stop the stale local "
                "engine bridge before starting this checkout."
            )
    app.run(host=BRIDGE_HOST, port=BRIDGE_PORT, debug=False)
