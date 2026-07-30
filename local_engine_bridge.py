"""Local engine bridge for gplan-building-designer development.

Serves the two endpoints the designer frontend needs, calling the LOCAL
GPLAN engine synchronously - no Django/Celery/Redis required. Lets you test
engine changes (e.g. cardinal constraints) end-to-end before deploying.

Run:      python GPLAN/local_engine_bridge.py          (from GPLAN_Revamp root)
          -> http://localhost:8027
Frontend: GPLAN_LOCAL_ENGINE=1 npm run dev             (designer repo)
          vite proxies /api and /users here instead of api.gplan.in.

Endpoints:
    POST /api/generate/<shape>       run Documents.get_floorplans, return task id
    POST /api/postprocess/floorplans NBC post-processing, synchronous 200
    GET  /api/task/<task_id>/        return the stored result
    POST /users/auth/token/refresh/  dummy token so the frontend auth flow passes
    POST /api/v1/authentication/login/  same
"""
import os
import sys
import json
import uuid
import base64
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify
from GPLAN.api import Documents, FLOORPLAN_LIMIT
from GPLAN.source.inputgraph import InputGraph

app = Flask(__name__)

_results = {}
_results_lock = threading.Lock()


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
        "min_ratio": [], "max_ratio": [], "plot_width": -1, "plot_height": -1,
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


@app.post("/api/generate/<shape>")
def generate(shape):
    task_id = str(uuid.uuid4())
    try:
        kwargs = _prepare(request.get_json(force=True), shape)
        print(f"[bridge] {shape}: nodes={len(kwargs['nodes_list'])} "
              f"edges={len(kwargs['edges_list'])} "
              f"cardinal={kwargs['cardinal_constraints']}")
        floorplans, message = Documents.get_floorplans(**kwargs)
        result = {"status": "SUCCESS", "message": message,
                  "response": floorplans.to_dict()}
        print(f"[bridge] {shape}: done - "
              f"{len(result['response']['Documents']['floorPlans'])} floorplans; {message!r}")
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "FAILURE", "error": {"message": str(exc)}}
    with _results_lock:
        _results[task_id] = result
    return jsonify({"task_id": task_id, "status": "started"}), 202


@app.get("/api/task/<task_id>/")
def task(task_id):
    with _results_lock:
        result = _results.get(task_id)
    if result is None:
        return jsonify({"status": "PENDING"})
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8027, debug=False)
