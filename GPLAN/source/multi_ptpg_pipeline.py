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
        -> [optional interior/exterior + cardinal filter]
        -> ptpg_floorplanner.generate_floorplans()   (per variant, exact dims)
        -> floorplans grouped by variant

Everything is headless and JSON-serializable; :class:`GPLAN.api.Documents`
exposes it as ``get_multi_ptpg_floorplans``.

N/E/S/W pins (``cardinal_constraints``) apply at both levels, and they have to:

* A pinned room must be ON the outer face, so any variant that buries it in the
  interior is dropped before it is ever dimensioned. This is the cheap half and
  it does most of the work, because a topological variant that makes the kitchen
  interior can never face it east however it is laid out.
* Every returned layout is then verified geometrically, because the boundary
  arcs are a topological assignment and only the placed rectangles are the truth.

The relaxation ladder mirrors ``door_connectivity``'s: pins are honoured, and if
NOTHING in the whole request can honour them the plans are returned anyway with a
warning saying so, never silently unpinned and never as an empty result.
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


def _normalize_cardinal(cardinal_constraints, node_count):
    """``[{"room": i, "direction": "N"}]`` -> ``[(i, dir_idx)]``.

    Delegates to :func:`GPLAN.api.normalize_cardinal_constraints` rather than
    re-implementing it: ``door_connectivity`` already accepts these payloads and
    two normalizers for one wire format is how N and E end up meaning different
    things on two endpoints. The import is lazy only because this module is
    reached THROUGH ``GPLAN.api``, so by call time it is already in sys.modules.
    """
    if not cardinal_constraints:
        return []
    from GPLAN.api import normalize_cardinal_constraints

    return normalize_cardinal_constraints(cardinal_constraints, node_count)


def _cardinal_payload(pins, room_names):
    """JSON view of the pins actually applied, named for the client."""
    return [
        {
            "room": int(node),
            "name": room_names[node] if node < len(room_names) else f"Room {node}",
            "direction": "NESW"[dir_idx],
        }
        for node, dir_idx in pins
    ]


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
    cardinal_pairs = _normalize_cardinal(params.get("cardinal_constraints"), len(nodes))

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
    enum_stats = {}
    try:
        variants = mptpg.enumerate_ptpg_variants(
            G_base, user_needs=user_needs, max_variants=max_variants,
            max_depth=max_depth, include_base=True, deadline=deadline,
            stats=enum_stats,
        )
    except Exception as exc:
        raise MultiPTPGError(f"variant enumeration failed: {exc}") from exc

    generated = len(variants)
    cap_hit = bool(enum_stats.get("cap_hit"))
    if cap_hit:
        # Never let a truncated search read as an exhaustive one: max_variants
        # can stop mid-level, so the returned set is then an arbitrary slice of
        # the depth it reached rather than all of it.
        warnings.append(
            f"the search stopped at the max_variants cap of {max_variants} with more "
            f"arrangements still reachable at depth {enum_stats.get('depth_reached')}; "
            "raise max_variants or lower max_depth for a complete set"
        )
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

    # A pinned room has to be on the outer face to face anything at all, so the
    # pins tighten the exterior set. Filtering here is what makes the pins cheap:
    # a variant that buries the kitchen in the interior is dropped before any
    # dimensioning is attempted on it.
    pinned_rooms = sorted({int(node) for node, _ in cardinal_pairs})
    exterior_required = sorted(set(int(r) for r in exterior_rooms) | set(pinned_rooms))
    cardinal_dropped_variants = 0

    if interior_rooms or exterior_required:
        before = len(variants)
        kept = mptpg.filter_variants_by_constraints(
            variants, interior=[int(r) for r in interior_rooms],
            exterior=exterior_required,
        )
        cardinal_dropped_variants = before - len(kept)
        if not kept:
            # Dropping every variant would return nothing at all, so keep them
            # and let the geometric gate decide per layout. A pinned room that
            # is interior in every topology usually still has SOME layout in
            # which its wall reaches the boundary.
            if pinned_rooms:
                warnings.append(
                    f"no arrangement puts every pinned room ({pinned_rooms}) on the "
                    f"outer wall, so all {before} arrangements were kept and the pins "
                    "are enforced on the placed layouts instead"
                )
                cardinal_dropped_variants = 0
            else:
                warnings.append(
                    f"all {before} variants were rejected by the interior/exterior "
                    "room constraints"
                )
                variants = kept
        else:
            variants = kept
            if cardinal_dropped_variants and pinned_rooms:
                warnings.append(
                    f"{cardinal_dropped_variants} of {before} arrangements were dropped "
                    "because they placed a pinned room away from the outer wall"
                )

    # ---- stage 3: dimensioned floorplans per variant -----------------------
    node_ids = sorted(G_base.nodes())

    def dimension_all(pins):
        """Dimension every variant, honouring ``pins``. Returns (payloads, plans, truncated)."""
        payloads = []
        plan_total = 0
        cut_short = False
        for variant_id, var in enumerate(variants):
            H = var["graph"]
            positions = _positions_from_embedding(H, outer_cycle=var.get("outer_cycle"))
            payload = _variant_payload(var, base_edges, variant_id, positions)
            payload["cardinal_satisfied"] = None if not pins else False

            if time.monotonic() > deadline:
                payload.update(status="skipped", reason="time budget exhausted",
                               floorplan_count=0, floorplans=[])
                payloads.append(payload)
                cut_short = True
                continue

            variant_edges = [(int(u), int(v)) for u, v in H.edges()]
            try:
                plans = pfp.generate_floorplans(
                    node_ids, variant_edges, widths, heights,
                    node_positions=positions, plot_w=plot_w, plot_h=plot_h,
                    limit=per_variant, already_ptpg=True,
                    max_boundaries=max_boundaries, deadline=deadline,
                    strictness=strictness, cardinal_pairs=pins,
                )
            except pfp.DeadlineExceeded:
                payload.update(status="skipped", reason="time budget exhausted",
                               floorplan_count=0, floorplans=[])
                payloads.append(payload)
                cut_short = True
                continue
            except Exception as exc:
                payload.update(status="error", reason=f"{type(exc).__name__}: {exc}",
                               floorplan_count=0, floorplans=[])
                payloads.append(payload)
                continue

            serialized = [p.to_dict(edges=variant_edges, room_names=room_names)
                          for p in plans]
            plan_total += len(serialized)
            # generate_floorplans gates on the pins, so anything it returned
            # satisfies them; say so per plan rather than making the client
            # re-derive it from geometry.
            for plan in serialized:
                plan["cardinal_satisfied"] = bool(pins)
            if pins and serialized:
                payload["cardinal_satisfied"] = True
            payload.update(
                status="ok" if serialized else "no_floorplan",
                reason=None if serialized else (
                    "no layout puts every pinned room on the direction you asked for"
                    if pins else
                    "no layout realises this topology at the requested exact room sizes"
                ),
                floorplan_count=len(serialized),
                floorplans=serialized,
            )
            payloads.append(payload)
        return payloads, plan_total, cut_short

    variant_payloads, total_plans, truncated = dimension_all(cardinal_pairs)

    # Relaxation ladder, mirroring door_connectivity's: pins outrank nothing if
    # they make the whole request empty. Retry unpinned and SAY the pins were
    # ignored, rather than returning an empty gallery or pretending they held.
    cardinal_ignored = False
    if cardinal_pairs and total_plans == 0 and time.monotonic() < deadline:
        retry_payloads, retry_plans, retry_truncated = dimension_all([])
        if retry_plans > 0:
            variant_payloads, total_plans, truncated = (
                retry_payloads, retry_plans, retry_truncated or truncated)
            cardinal_ignored = True
            asked = ", ".join(f"{c['name']} {c['direction']}"
                              for c in _cardinal_payload(cardinal_pairs, room_names))
            warnings.append(
                f"the N/E/S/W directions were ignored: no arrangement of these rooms at "
                f"these exact sizes places {asked} on the wall you asked for. The plans "
                "below are otherwise valid"
            )

    # Time, not max_variants, is the real bound on this endpoint now, so running
    # out of it is a normal outcome and must be stated. Variants are dimensioned
    # base-first then by depth, so what gets skipped is always the most-mutated
    # end of the set - the arrangements furthest from what the user drew.
    skipped = sum(1 for p in variant_payloads if p.get("status") == "skipped")
    if truncated and skipped:
        warnings.append(
            f"the {time_budget:.0f}s time budget ran out with {skipped} of "
            f"{len(variant_payloads)} arrangements not yet laid out; they are the "
            "ones furthest from the graph you drew. Raise time_budget_seconds or "
            "lower max_depth to cover them"
        )

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
        "cardinal": {
            "requested": _cardinal_payload(cardinal_pairs, room_names),
            "applied": bool(cardinal_pairs) and not cardinal_ignored,
            "ignored": cardinal_ignored,
        },
        "variant_count": len(variant_payloads),
        "floorplan_count": total_plans,
        "variants": variant_payloads,
        "stats": {
            "variants_generated": generated,
            "variants_after_filter": len(variants),
            "variants_returned": len(variant_payloads),
            "variants_dropped_by_cardinal": cardinal_dropped_variants,
            "strictness": strictness,
            "preserve_input_edges": preserve_input_edges,
            "protected_edges": [[int(u), int(v)] for u, v in user_needs],
            "max_variants": max_variants,
            "max_depth": max_depth,
            "variant_cap_hit": bool(cap_hit),
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
