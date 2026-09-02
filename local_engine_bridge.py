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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify
from GPLAN.api import Documents, FLOORPLAN_LIMIT
from GPLAN.source.inputgraph import InputGraph

app = Flask(__name__)

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8027
BRIDGE_CAPABILITIES = [
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


@app.get("/api/local-bridge/health/")
def local_bridge_health():
    """Compatibility probe used by the designer before selecting this bridge."""
    return jsonify({"status": "ok", "capabilities": BRIDGE_CAPABILITIES})


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
# Structural module (documentation/structural_api.md).
#
# Register both slash forms so POST request bodies never depend on a redirect.
# Engine imports remain lazy through Documents, isolating floorplan generation
# from an unavailable optional structural dependency.
# ---------------------------------------------------------------------------


def _structural_refusal(envelope):
    if not isinstance(envelope, dict):
        return None
    documents = (envelope.get("response") or {}).get("Documents") or {}
    error = documents.get("error")
    return error if isinstance(error, dict) else None


def _structural_500(exc):
    traceback.print_exc()
    return jsonify({"status": "error", "data": {},
                    "error": {"message": str(exc),
                              "type": type(exc).__name__}}), 500


def _structural_counts(envelope):
    documents = (envelope.get("response") or {}).get("Documents") or {}
    summary = documents.get("batch_summary") or {}
    plans = summary.get("plans", 0)
    return "%s entr%s, %s refused" % (
        plans, "y" if plans == 1 else "ies", summary.get("refused", 0))


@app.get("/api/structural/options/")
@app.get("/api/structural/options")
def structural_options():
    try:
        return jsonify(Documents.structural_options()), 200
    except Exception as exc:
        return _structural_500(exc)


@app.post("/api/structural/layout/")
@app.post("/api/structural/layout")
def structural_layout():
    try:
        envelope = Documents.layout_structure(request.get_json(force=True) or {})
    except Exception as exc:
        return _structural_500(exc)
    error = _structural_refusal(envelope)
    if error:
        print("[bridge] structural layout: refused - %s" % error.get("message"))
        return jsonify(envelope), 400
    print("[bridge] structural layout: %s; %s" %
          (envelope.get("message"), _structural_counts(envelope)))
    return jsonify(envelope), 200


@app.post("/api/structural/check/")
@app.post("/api/structural/check")
def structural_check():
    try:
        envelope = Documents.check_structure(request.get_json(force=True) or {})
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
    task_id = str(uuid.uuid4())
    try:
        envelope = Documents.design_structure(request.get_json(force=True) or {})
    except Exception as exc:
        traceback.print_exc()
        with _results_lock:
            _results[task_id] = {
                "status": "FAILURE",
                "error": {"message": str(exc), "type": type(exc).__name__},
            }
        print("[bridge] structural design: stage raised - %s" % exc)
        return jsonify({"task_id": task_id, "status": "started"}), 202
    error = _structural_refusal(envelope)
    if error:
        print("[bridge] structural design: refused - %s" % error.get("message"))
        return jsonify(envelope), 400
    with _results_lock:
        _results[task_id] = envelope
    print("[bridge] structural design: %s; %s" %
          (envelope.get("message"), _structural_counts(envelope)))
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
