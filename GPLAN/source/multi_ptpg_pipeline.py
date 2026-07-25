"""Multi-PTPG dimensioned floorplan pipeline.

Joins the two GPLAN-team branches that each solved half of the problem:

* ``QA_multi_ptpg`` turned one adjacency graph into *many* PTPG variants but
  could only hand a single chosen variant to ``irreg_multiple_dual()``, and only
  through a Tkinter gallery.
* ``ptpg_floorplanner`` turned *one* PTPG plus exact room sizes into dimensioned
  rectangular floorplans, but had no notion of alternative topologies.

The pipeline here runs the second over every output of the first:

    adjacency graph
        -> InputGraph.door_connectivity()            (base PTPG)
        -> multiple_ptpg.enumerate_ptpg_variants()   (topological variants)
        -> [optional interior/exterior filter]
        -> ptpg_floorplanner.generate_floorplans()   (per variant, exact dims)
        -> floorplans grouped by variant

Everything is headless and JSON-serializable; :class:`GPLAN.api.Documents`
exposes it as ``get_multi_ptpg_floorplans``.
"""

import copy
import time
import traceback

import numpy as np
import networkx as nx

from GPLAN.source.inputgraph import InputGraph
from GPLAN.source import multiple_ptpg as mptpg
from GPLAN.source import ptpg_floorplanner as pfp


DEFAULT_TIME_BUDGET = 900.0          # seconds; below the 1500 s Celery soft limit
DEFAULT_FLOORPLANS_PER_VARIANT = 5
MAX_NODES = 40


class MultiPTPGError(Exception):
    """Input that the pipeline cannot process at all."""


def _positions_from_embedding(G, outer_cycle=None, scale=100.0):
    """Tutte layout as plain float pairs, for both the placer and the client."""
    pos = mptpg.planar_tutte_embedding(G, outer_cycle=outer_cycle)
    return {n: (float(p[0]) * scale, float(p[1]) * scale) for n, p in pos.items()}


def _edge_list(G):
    return sorted(mptpg._norm_edge(u, v) for u, v in G.edges())


def build_base_ptpg(nodes, edges, deadline=None):
    """Run door_connectivity and return (ptpg_graph_object, is_ptpg, base_nx_graph).

    ``door_connectivity`` mutates and returns the InputGraph it is called on, so
    it is handed a deep copy; the caller's graph stays as the user drew it.
    """
    node_count = len(nodes)
    coordinates = [[float(n.get("x", 0)), float(n.get("y", 0))] for n in nodes]
    edge_triples = [[int(e["source"]), int(e["target"]), e.get("color", "black")]
                    for e in edges]

    graph = InputGraph(node_count, len(edge_triples), edge_triples, coordinates)
    working = copy.deepcopy(graph)
    result = working.door_connectivity(show_graph=False)
    ptpg = result[0] if isinstance(result, tuple) else result
    is_ptpg = bool(result[1]) if isinstance(result, tuple) and len(result) > 1 else True

    matrix = np.array(ptpg.matrix)
    G = nx.from_numpy_array(matrix)
    return ptpg, is_ptpg, G


def _room_dimensions(nodes, ptpg_node_count, dummy_width=None, dummy_height=None):
    """Exact width/height per PTPG node, inventing sizes for any node door_connectivity added.

    Separating-triangle removal can introduce rooms the client never asked for.
    They still need a size, so they default to the smallest room the client did
    send - large enough to be placeable, small enough not to distort the plan.
    """
    widths = {}
    heights = {}
    names = []
    for i, node in enumerate(nodes):
        w = node.get("width")
        h = node.get("height")
        if w is None or h is None:
            raise MultiPTPGError(
                f"node {node.get('id', i)} is missing an exact width/height; "
                "this API places rooms at exact sizes, not minimums"
            )
        w = int(round(float(w)))
        h = int(round(float(h)))
        if w <= 0 or h <= 0:
            raise MultiPTPGError(
                f"node {node.get('id', i)} has a non-positive dimension ({w}x{h})"
            )
        widths[i] = w
        heights[i] = h
        names.append(node.get("label") or f"Room {i}")

    synthetic = []
    if ptpg_node_count > len(nodes):
        fallback_w = int(dummy_width) if dummy_width else (min(widths.values()) if widths else 1)
        fallback_h = int(dummy_height) if dummy_height else (min(heights.values()) if heights else 1)
        for i in range(len(nodes), ptpg_node_count):
            widths[i] = max(1, fallback_w)
            heights[i] = max(1, fallback_h)
            names.append(f"Room {i} (added)")
            synthetic.append(i)

    return widths, heights, names, synthetic


def _variant_payload(var, base_edges, variant_id, positions):
    edges = _edge_list(var['graph'])
    base_set = set(base_edges)
    edge_set = set(edges)
    return {
        "variant_id": variant_id,
        "depth": var.get("depth", 0),
        "operation": var.get("operation", "base"),
        "detail": list(var["detail"]) if var.get("detail") else None,
        "is_base": bool(var.get("is_base", False)),
        "edges": [[int(u), int(v)] for u, v in edges],
        "outer_cycle": [int(n) for n in var.get("outer_cycle") or []],
        "added_edges": [[int(u), int(v)] for u, v in sorted(edge_set - base_set)],
        "removed_edges": [[int(u), int(v)] for u, v in sorted(base_set - edge_set)],
        "nodes": [
            {"id": int(n), "x": round(positions[n][0], 4), "y": round(positions[n][1], 4)}
            for n in sorted(positions)
        ],
    }


def generate_multi_ptpg_floorplans(params):
    """Full pipeline. ``params`` is the request body; returns the ``data`` payload."""
    started = time.monotonic()

    nodes = params.get("nodes") or []
    edges = params.get("edges") or []
    if not nodes:
        raise MultiPTPGError("params.nodes is required and must be non-empty")
    if len(nodes) < 3:
        raise MultiPTPGError("at least 3 rooms are required to build a PTPG")
    if len(nodes) > MAX_NODES:
        raise MultiPTPGError(f"at most {MAX_NODES} rooms are supported (got {len(nodes)})")
    if not edges:
        raise MultiPTPGError("params.edges is required and must be non-empty")

    nodes = sorted(nodes, key=lambda n: n.get("id", 0))
    for expected, node in enumerate(nodes):
        if int(node.get("id", expected)) != expected:
            raise MultiPTPGError(
                "node ids must be the contiguous range 0..n-1; "
                f"expected {expected}, got {node.get('id')}"
            )

    # Red (non-adjacency) edges are dropped: door_connectivity's non-adjacency
    # branch is a documented hang, and this pipeline never needs it.
    black_edges = [e for e in edges if e.get("color", "black") != "red"]
    if not black_edges:
        raise MultiPTPGError("no black (adjacency) edges in params.edges")

    time_budget = float(params.get("time_budget_seconds") or DEFAULT_TIME_BUDGET)
    deadline = started + max(5.0, time_budget)

    max_variants = int(params.get("max_variants", mptpg.DEFAULT_MAX_VARIANTS))
    max_depth = int(params.get("max_depth", mptpg.DEFAULT_MAX_DEPTH))
    per_variant = int(params.get("floorplans_per_variant", DEFAULT_FLOORPLANS_PER_VARIANT))
    max_boundaries = int(params.get("max_boundaries_per_variant", pfp.DEFAULT_MAX_BOUNDARIES))
    strictness = params.get("strictness", "relaxed")
    if strictness not in pfp.STRICTNESS_LEVELS:
        raise MultiPTPGError(f"strictness must be one of {list(pfp.STRICTNESS_LEVELS)}")
    preserve_input_edges = bool(params.get("preserve_input_edges", True))
    protected_edges = params.get("protected_edges")
    plot_w = int(params.get("plot_width", -1) or -1)
    plot_h = int(params.get("plot_height", -1) or -1)
    interior_rooms = params.get("interior_rooms") or []
    exterior_rooms = params.get("exterior_rooms") or []

    # ---- stage 1: base PTPG ------------------------------------------------
    try:
        ptpg, is_ptpg, G_base = build_base_ptpg(nodes, black_edges, deadline=deadline)
    except MultiPTPGError:
        raise
    except Exception as exc:
        raise MultiPTPGError(f"door_connectivity failed: {exc}") from exc

    if G_base.number_of_nodes() < 3:
        raise MultiPTPGError("the PTPG collapsed to fewer than 3 rooms")

    # The matrix shape is authoritative: door_connectivity leaves self.nodecnt
    # stale, and separating-triangle removal is the one step that could append
    # rooms the client never asked for.
    widths, heights, room_names, synthetic = _room_dimensions(
        nodes, G_base.number_of_nodes(),
        params.get("added_room_width"), params.get("added_room_height"),
    )
    engine_dummies = list(getattr(ptpg, "mergednodes", []) or []) + \
        list(getattr(ptpg, "extranodes", []) or [])

    base_edges = _edge_list(G_base)
    base_outer, outer_is_cycle = mptpg.boundary_nodes(G_base)
    input_pairs = {mptpg._norm_edge(int(e["source"]), int(e["target"])) for e in black_edges}
    added_by_dc = sorted(set(base_edges) - input_pairs)

    warnings = []
    if synthetic:
        warnings.append(
            f"door_connectivity added {len(synthetic)} room(s) not present in the "
            f"input (ids {synthetic}); they were sized from the smallest requested "
            "room and are flagged as added_by_engine in rooms[]"
        )
    if engine_dummies:
        warnings.append(
            f"the engine recorded merged/extra room bookkeeping ({engine_dummies}); "
            "the returned plans treat every matrix index as its own rectangle"
        )
    if not is_ptpg:
        warnings.append(
            "door_connectivity could not fully remove the separating triangles, so "
            "the base graph is not a strict PTPG; plans are still produced but "
            "adjacency guarantees are weaker"
        )
    if not outer_is_cycle:
        # Both transformations walk the outer cycle, so without one the variant
        # search cannot leave the base graph. Say so instead of quietly
        # returning a single "variant".
        warnings.append(
            "the base PTPG's outer face is not a simple cycle, so no topological "
            "variants can be derived from it; only the base graph was placed"
        )

    # ---- stage 2: variant enumeration --------------------------------------
    # Both transformations destroy an existing adjacency, so protecting every
    # input edge protects everything and the search cannot leave the base
    # graph. `protected_edges` is the useful middle ground: name only the
    # adjacencies that actually matter and let the rest be rearranged.
    if protected_edges is not None:
        user_needs = sorted(
            mptpg._norm_edge(int(e[0]), int(e[1]))
            for e in protected_edges if len(e) >= 2
        )
    elif preserve_input_edges:
        user_needs = sorted(input_pairs)
    else:
        user_needs = []
    try:
        variants = mptpg.enumerate_ptpg_variants(
            G_base, user_needs=user_needs, max_variants=max_variants,
            max_depth=max_depth, include_base=True, deadline=deadline,
        )
    except Exception as exc:
        raise MultiPTPGError(f"variant enumeration failed: {exc}") from exc

    generated = len(variants)
    for var in variants:
        var["outer_cycle"] = mptpg.boundary_nodes(var["graph"])[0]

    if generated == 1 and outer_is_cycle:
        msg = ("no topological variant of the base PTPG survived validation; every "
               "boundary edge and interior diagonal is either protected or cannot "
               "be transformed without breaking the PTPG")
        if user_needs:
            msg += (". Every transformation removes an existing adjacency, so "
                    "protecting all of them leaves nothing to change: retry with "
                    "preserve_input_edges=false, or list only the adjacencies you "
                    "need in protected_edges")
        warnings.append(msg)

    if interior_rooms or exterior_rooms:
        before = len(variants)
        variants = mptpg.filter_variants_by_constraints(
            variants, interior=[int(r) for r in interior_rooms],
            exterior=[int(r) for r in exterior_rooms],
        )
        if not variants:
            warnings.append(
                f"all {before} variants were rejected by the interior/exterior "
                "room constraints"
            )

    # ---- stage 3: dimensioned floorplans per variant -----------------------
    node_ids = sorted(G_base.nodes())
    variant_payloads = []
    total_plans = 0
    truncated = False

    for variant_id, var in enumerate(variants):
        H = var["graph"]
        positions = _positions_from_embedding(H, outer_cycle=var.get("outer_cycle"))
        payload = _variant_payload(var, base_edges, variant_id, positions)

        if time.monotonic() > deadline:
            payload.update(status="skipped", reason="time budget exhausted",
                           floorplan_count=0, floorplans=[])
            variant_payloads.append(payload)
            truncated = True
            continue

        variant_edges = [(int(u), int(v)) for u, v in H.edges()]
        try:
            plans = pfp.generate_floorplans(
                node_ids, variant_edges, widths, heights,
                node_positions=positions, plot_w=plot_w, plot_h=plot_h,
                limit=per_variant, already_ptpg=True,
                max_boundaries=max_boundaries, deadline=deadline,
                strictness=strictness,
            )
        except pfp.DeadlineExceeded:
            payload.update(status="skipped", reason="time budget exhausted",
                           floorplan_count=0, floorplans=[])
            variant_payloads.append(payload)
            truncated = True
            continue
        except Exception as exc:
            payload.update(status="error", reason=f"{type(exc).__name__}: {exc}",
                           floorplan_count=0, floorplans=[])
            variant_payloads.append(payload)
            continue

        serialized = [p.to_dict(edges=variant_edges, room_names=room_names) for p in plans]
        total_plans += len(serialized)
        payload.update(
            status="ok" if serialized else "no_floorplan",
            reason=None if serialized else (
                "no layout realises this topology at the requested exact room sizes"
            ),
            floorplan_count=len(serialized),
            floorplans=serialized,
        )
        variant_payloads.append(payload)

    return {
        "base_ptpg": {
            "node_count": int(G_base.number_of_nodes()),
            "edges": [[int(u), int(v)] for u, v in base_edges],
            "outer_cycle": [int(n) for n in base_outer],
            "outer_face_is_cycle": bool(outer_is_cycle),
            "edges_added_by_door_connectivity": [[int(u), int(v)] for u, v in added_by_dc],
            "is_ptpg": bool(is_ptpg),
        },
        "warnings": warnings,
        "rooms": [
            {
                "id": i,
                "name": room_names[i],
                "width": widths[i],
                "height": heights[i],
                "added_by_engine": i in synthetic,
            }
            for i in node_ids
        ],
        "variant_count": len(variant_payloads),
        "floorplan_count": total_plans,
        "variants": variant_payloads,
        "stats": {
            "variants_generated": generated,
            "variants_after_filter": len(variants),
            "variants_returned": len(variant_payloads),
            "strictness": strictness,
            "preserve_input_edges": preserve_input_edges,
            "protected_edges": [[int(u), int(v)] for u, v in user_needs],
            "max_variants": max_variants,
            "max_depth": max_depth,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "truncated": truncated,
        },
    }


def run(request_data):
    """Envelope wrapper matching the other GPLAN engine entry points."""
    request_id = (request_data or {}).get("request_id", "unknown")
    params = (request_data or {}).get("params") or {}
    try:
        data = generate_multi_ptpg_floorplans(params)
        return {
            "request_id": request_id,
            "status": "ok",
            "engine": "MultiPTPG_FloorPlan",
            "data": data,
            "error": None,
        }
    except MultiPTPGError as exc:
        return {
            "request_id": request_id,
            "status": "error",
            "engine": "MultiPTPG_FloorPlan",
            "data": {},
            "error": {"message": str(exc), "type": "ValidationError"},
        }
    except Exception as exc:
        return {
            "request_id": request_id,
            "status": "error",
            "engine": "MultiPTPG_FloorPlan",
            "data": {},
            "error": {
                "message": str(exc),
                "type": type(exc).__name__,
                "traceback": traceback.format_exc(limit=8),
            },
        }
