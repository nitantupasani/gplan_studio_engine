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

The relaxation ladder here is SHALLOWER than ``door_connectivity``'s: it has one
rung. Pins are honoured on every returned plan, and if NOTHING in the whole
request honours them the plans are returned unpinned with a warning saying so,
never silently and never as an empty result. The door path additionally spends
adjacencies to keep the pins (its spanning-tree rung) before it ever unpins;
this endpoint does not yet, so a pin that the arrangements cannot hold is given
up sooner than the settled priority (pins outrank adjacencies, adjacencies
outrank arrangement count) wants. The graded ladder is planned in
``documentation/plans/CARDINAL_CONSTRAINTS_MULTI_PTPG_PLAN.md``; do not describe
this one as mirroring the door path's.
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
# Total floorplans across ALL arrangements, matching door_connectivity's
# FLOORPLAN_LIMIT so both generators hand the client the same size catalogue.
# Set max_floorplans to 0 or a negative number to lift it.
DEFAULT_MAX_FLOORPLANS = 30
MAX_NODES = 40


class MultiPTPGError(Exception):
    """Input that the pipeline cannot process at all."""


def _apply_floorplan_cap(payloads, cap):
    """Trim the batch to ``cap`` floorplans total, breadth-first.

    Round-robin across arrangements, never first-come. One arrangement's FIRST
    plan outranks another's second, so the cap costs depth inside an arrangement
    before it costs whole arrangements: a 30-plan cap over 26 arrangements
    returns all 26, four of them twice. Slicing the concatenated list instead
    would return every option of the first handful and silently drop the rest of
    the gallery, which is the same failure the old max_variants cap had.

    Returns ``(total_kept, cap_hit, variants_emptied)``.
    """
    total = sum(len(p.get("floorplans") or []) for p in payloads)
    if cap <= 0 or total <= cap:
        return total, False, 0

    keep = [0] * len(payloads)
    remaining = cap
    depth = 0
    while remaining > 0:
        progressed = False
        for i, payload in enumerate(payloads):
            plans = payload.get("floorplans") or []
            if depth >= len(plans):
                continue
            progressed = True
            keep[i] += 1
            remaining -= 1
            if remaining == 0:
                break
        if not progressed:
            break
        depth += 1

    emptied = 0
    for i, payload in enumerate(payloads):
        plans = payload.get("floorplans") or []
        if not plans or keep[i] == len(plans):
            continue
        payload["floorplans"] = plans[:keep[i]]
        payload["floorplan_count"] = keep[i]
        if keep[i] == 0:
            emptied += 1
            payload["status"] = "skipped"
            payload["reason"] = (
                f"the {cap}-floorplan cap was filled by other arrangements"
            )
    return cap - remaining, True, emptied


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


def _sanitize_pins(raw_entries, pairs, room_names, warnings):
    """Up-front pin hygiene; returns the pairs that are worth attempting.

    Three things used to be discovered only after two full dimensioning passes
    (or never):

    * entries normalization dropped (room index out of range - e.g. a pin on a
      room ``door_connectivity`` invented, which is not a client room - or an
      unrecognised direction) were silent;
    * a room pinned to OPPOSITE directions (N+S or E+W) is unsatisfiable by
      construction, yet ran the full pinned pass and the full unpinned retry
      before answering ``ignored`` with a message blaming the room sizes;
    * three or more directions on one room can never all hold (a corner room
      occupies exactly two adjacent arcs).

    Contradictory rooms lose their pins HERE, each with a warning naming the
    room, so the remaining pins still get their honest attempt.
    """
    normalized_count = len(pairs)
    raw_count = 0
    for entry in raw_entries or []:
        if isinstance(entry, dict) or (hasattr(entry, "__len__") and len(entry) >= 2):
            raw_count += 1
    # Duplicates collapse in normalization too, so this is a lower bound; it
    # still catches the silent-drop cases worth naming.
    if raw_count > normalized_count:
        warnings.append(
            f"{raw_count - normalized_count} cardinal pin(s) were dropped during "
            "normalization: the room index is not one of the request's rooms "
            "(pins on engine-added rooms are not supported) or the direction "
            "was not one of N/E/S/W, or the pin was a duplicate"
        )

    by_room = {}
    for node, dir_idx in pairs:
        by_room.setdefault(node, []).append(dir_idx)

    keep = []
    for node, dirs in by_room.items():
        name = room_names[node] if node < len(room_names) else f"Room {node}"
        dir_names = "+".join("NESW"[d] for d in sorted(dirs))
        if len(dirs) > 2:
            warnings.append(
                f"the pins on {name} ({dir_names}) were dropped: a room can face "
                "at most two adjacent directions (a corner)"
            )
            continue
        if len(dirs) == 2 and (dirs[1] - dirs[0]) % 4 == 2:
            warnings.append(
                f"the pins on {name} ({dir_names}) were dropped: opposite "
                "directions on one room can never both hold"
            )
            continue
        keep.append(node)

    keep_set = set(keep)
    return [(n, d) for n, d in pairs if n in keep_set]


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
    for e in black_edges:
        s, t = int(e.get("source", -1)), int(e.get("target", -1))
        if not (0 <= s < len(nodes)) or not (0 <= t < len(nodes)):
            raise MultiPTPGError(
                f"edge ({s}, {t}) names a room outside 0..{len(nodes) - 1}"
            )

    # door_connectivity has no deadline hook and runs effectively unbounded on
    # disconnected input (a 9-node forest was observed running past four
    # minutes), so reject it up front with a fixable message instead of letting
    # the worker hang before any deadline is ever consulted.
    conn = nx.Graph()
    conn.add_nodes_from(range(len(nodes)))
    conn.add_edges_from((int(e["source"]), int(e["target"])) for e in black_edges)
    if not nx.is_connected(conn):
        comps = sorted((sorted(c) for c in nx.connected_components(conn)),
                       key=len, reverse=True)
        label = lambda i: nodes[i].get("label") or f"Room {i}"
        isolated = "; ".join(
            ", ".join(label(i) for i in comp) for comp in comps[1:4]
        )
        raise MultiPTPGError(
            f"the adjacency graph is disconnected ({len(comps)} separate groups). "
            f"Rooms not connected to the main group: {isolated}. Add adjacencies "
            "linking every room before generating arrangements"
        )

    time_budget = float(params.get("time_budget_seconds") or DEFAULT_TIME_BUDGET)
    deadline = started + max(5.0, time_budget)

    max_variants = int(params.get("max_variants", mptpg.DEFAULT_MAX_VARIANTS))
    max_depth = int(params.get("max_depth", mptpg.DEFAULT_MAX_DEPTH))
    per_variant = int(params.get("floorplans_per_variant", DEFAULT_FLOORPLANS_PER_VARIANT))
    max_floorplans = int(params.get("max_floorplans", DEFAULT_MAX_FLOORPLANS))
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

    warnings = []
    client_names = [n.get("label") or f"Room {i}" for i, n in enumerate(nodes)]
    # ``requested`` in the response reports what the CLIENT asked for; the
    # sanitized list is what the pipeline attempts.
    requested_pairs = list(cardinal_pairs)
    cardinal_pairs = _sanitize_pins(
        params.get("cardinal_constraints"), cardinal_pairs, client_names, warnings)

    # A room in both interior_rooms and cardinal_constraints is unsatisfiable by
    # construction (a pinned room must reach the outer wall). The pin outranks
    # the interior mark - cardinal constraints have priority - and the response
    # says which one won rather than letting the filter empty and blame the pins.
    pinned_set = {n for n, _ in cardinal_pairs}
    interior_conflicts = sorted(pinned_set & {int(r) for r in interior_rooms})
    if interior_conflicts:
        named = ", ".join(client_names[i] for i in interior_conflicts)
        warnings.append(
            f"{named} appeared in both interior_rooms and cardinal_constraints; "
            "a pinned room must reach the outer wall, so the pin won and the "
            "interior mark was dropped for it"
        )
        interior_rooms = [r for r in interior_rooms if int(r) not in pinned_set]

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
        cyc, is_cyc = mptpg.boundary_nodes(var["graph"])
        var["outer_cycle"] = cyc
        var["outer_is_cycle"] = is_cyc

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
    cardinal_filter_emptied = False

    if interior_rooms or exterior_required:
        before = len(variants)
        kept = mptpg.filter_variants_by_constraints(
            variants, interior=[int(r) for r in interior_rooms],
            exterior=exterior_required,
        )
        cardinal_dropped_variants = before - len(kept)
        if not kept:
            # Dropping every variant would return nothing at all, so keep them
            # and let the geometry decide per layout. A room that is interior
            # in every topology usually still has SOME layout in which its
            # wall reaches the boundary (relaxed layouts contain voids). The
            # drop count is KEPT: it is the funnel metric, and zeroing it in
            # exactly the case where the filter was most aggressive hid what
            # happened.
            if pinned_rooms:
                warnings.append(
                    f"no arrangement puts every pinned room ({pinned_rooms}) on the "
                    f"outer wall, so all {before} arrangements were kept and the pins "
                    "are enforced on the placed layouts instead"
                )
                cardinal_filter_emptied = True
            elif exterior_required:
                # exterior_rooms without pins used to empty the whole request
                # here; same keep-all treatment, disclosed.
                warnings.append(
                    f"no arrangement puts every exterior-required room "
                    f"({exterior_required}) on the outer wall, so all {before} "
                    "arrangements were kept; check each plan's geometry for the "
                    "exposure you need"
                )
                cardinal_filter_emptied = True
            else:
                warnings.append(
                    f"all {before} variants were rejected by the interior room "
                    "constraints"
                )
                variants = kept
        else:
            variants = kept
            if cardinal_dropped_variants and pinned_rooms:
                warnings.append(
                    f"{cardinal_dropped_variants} of {before} arrangements were dropped "
                    "because they placed a pinned room away from the outer wall"
                )

    # Arc-order feasibility, the stronger half of the topological pre-filter.
    # Membership says every pinned room is somewhere on the outer cycle; with
    # two or more pins the cyclic ORDER must also admit a rotation/reflection
    # that puts each pin inside its own N/E/S/W arc, which is exactly the
    # predicate the door path uses to order its ring (api._ring_order_satisfies,
    # pure, both orientations, all rotations - the same 8 symmetries the
    # boundary filter downstream can accept). A variant that fails it walks
    # every boundary through every strictness pass and can never satisfy, so
    # pruning here is pure savings.
    if cardinal_pairs and variants and not cardinal_filter_emptied:
        from GPLAN.api import _ring_order_satisfies

        pins_map = {}
        for node, dir_idx in cardinal_pairs:
            pins_map.setdefault(node, set()).add(dir_idx)

        def order_admits_pins(var):
            # An open-path boundary (outer face not a simple cycle) is unknown
            # territory, not a proof of impossibility: never prune on it.
            if not var.get("outer_is_cycle"):
                return True
            order = list(var.get("outer_cycle") or [])
            if len(order) < 3:
                return True
            try:
                return _ring_order_satisfies(order, pins_map)
            except ValueError:
                # 3+ directions on one room; _sanitize_pins rejects that
                # upstream, but never let a predicate error drop a variant.
                return True

        before_arc = len(variants)
        arc_kept = [v for v in variants if order_admits_pins(v)]
        arc_dropped = before_arc - len(arc_kept)
        if arc_kept:
            variants = arc_kept
            if arc_dropped:
                cardinal_dropped_variants += arc_dropped
                warnings.append(
                    f"{arc_dropped} more arrangement(s) were dropped because their "
                    "outer-wall order cannot put every pinned room on its own "
                    "direction, whatever the room sizes"
                )
        elif arc_dropped:
            cardinal_filter_emptied = True
            warnings.append(
                "no arrangement's outer-wall order can put every pinned room on "
                f"its own direction, so all {before_arc} arrangements were kept "
                "and the pins are enforced on the placed layouts instead"
            )

    # ---- stage 3: dimensioned floorplans per variant -----------------------
    node_ids = sorted(G_base.nodes())

    def dimension_all(pins):
        """Dimension every variant, honouring ``pins``.

        Returns ``(payloads, plans, truncated, cap_info)``.
        """
        payloads = []
        cut_short = False
        placed = 0          # arrangements that produced at least one floorplan
        cap_skipped = 0     # arrangements never attempted because the cap was full
        for variant_id, var in enumerate(variants):
            H = var["graph"]
            positions = _positions_from_embedding(H, outer_cycle=var.get("outer_cycle"))
            payload = _variant_payload(var, base_edges, variant_id, positions)
            payload["cardinal_satisfied"] = None if not pins else False

            # Once that many arrangements have a plan each, the round-robin cap
            # is already full at depth 1 and nothing a further arrangement
            # produces could survive it. Skipping the dimensioning outright is
            # where the cap buys its time back: a 4BHK enumerates 107
            # arrangements and only the first 30 are worth laying out.
            if 0 < max_floorplans <= placed:
                payload.update(status="skipped",
                               reason=(f"the {max_floorplans}-floorplan cap was already "
                                       "filled by earlier arrangements"),
                               floorplan_count=0, floorplans=[])
                payloads.append(payload)
                cap_skipped += 1
                continue

            if time.monotonic() > deadline:
                payload.update(status="skipped", reason="time budget exhausted",
                               floorplan_count=0, floorplans=[])
                payloads.append(payload)
                cut_short = True
                continue

            variant_edges = [(int(u), int(v)) for u, v in H.edges()]
            boundary_stats = {}
            try:
                plans = pfp.generate_floorplans(
                    node_ids, variant_edges, widths, heights,
                    node_positions=positions, plot_w=plot_w, plot_h=plot_h,
                    limit=per_variant, already_ptpg=True,
                    max_boundaries=max_boundaries, deadline=deadline,
                    strictness=strictness, cardinal_pairs=pins,
                    stats=boundary_stats,
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
            if serialized:
                placed += 1
            # generate_floorplans gates on the pins, so anything it returned
            # satisfies them; say so per plan rather than making the client
            # re-derive it from geometry.
            for plan in serialized:
                plan["cardinal_satisfied"] = bool(pins)
            if pins and serialized:
                payload["cardinal_satisfied"] = True
            truncated_here = bool(boundary_stats.get("truncated"))
            payload["boundaries_truncated"] = truncated_here
            reason = None
            if not serialized:
                reason = (
                    "no layout puts every pinned room on the direction you asked for"
                    if pins else
                    "no layout realises this topology at the requested exact room sizes"
                )
                if truncated_here:
                    # Do not blame the room sizes for a truncation: the cap cut
                    # the boundary list before every candidate was tried.
                    reason += (
                        f" within the first {boundary_stats.get('raw_kept')} of "
                        f"{boundary_stats.get('raw_total')} candidate boundaries; "
                        "raise max_boundaries_per_variant (0 lifts the cap) to "
                        "try the rest"
                    )
            payload.update(
                status="ok" if serialized else "no_floorplan",
                reason=reason,
                floorplan_count=len(serialized),
                floorplans=serialized,
            )
            payloads.append(payload)

        plan_total, fp_cap_hit, cap_emptied = _apply_floorplan_cap(payloads, max_floorplans)
        cap_info = {
            "hit": fp_cap_hit or cap_skipped > 0,
            "variants_emptied": cap_emptied,
            "variants_skipped": cap_skipped,
        }
        return payloads, plan_total, cut_short, cap_info

    variant_payloads, total_plans, truncated, cap_info = dimension_all(cardinal_pairs)

    # Relaxation ladder, ONE rung (shallower than door_connectivity's; the
    # graded ladder is planned): when the pinned pass returns nothing at all,
    # retry unpinned and SAY the pins were ignored, rather than returning an
    # empty gallery or pretending they held.
    cardinal_ignored = False
    cardinal_retry_failed = False
    cardinal_retry_skipped = False
    if cardinal_pairs and total_plans == 0:
        if time.monotonic() >= deadline:
            cardinal_retry_skipped = True
            warnings.append(
                "the time budget expired before the unpinned retry could run: no "
                "plans were produced and whether the pins are satisfiable was "
                "never determined. Raise time_budget_seconds"
            )
        else:
            retry_payloads, retry_plans, retry_truncated, retry_cap = dimension_all([])
            if retry_plans > 0:
                variant_payloads, total_plans, truncated, cap_info = (
                    retry_payloads, retry_plans, retry_truncated or truncated, retry_cap)
                cardinal_ignored = True
                asked = ", ".join(f"{c['name']} {c['direction']}"
                                  for c in _cardinal_payload(cardinal_pairs, room_names))
                warnings.append(
                    f"the N/E/S/W directions were ignored: no arrangement of these rooms at "
                    f"these exact sizes places {asked} on the wall you asked for. The plans "
                    "below are otherwise valid"
                )
            else:
                # The retry just proved the pins were NOT the cause; the kept
                # payloads still blame them, so correct each reason.
                cardinal_retry_failed = True
                for payload in variant_payloads:
                    if payload.get("status") == "no_floorplan":
                        payload["reason"] = (
                            "no layout realises this topology at the requested "
                            "exact room sizes; the unpinned retry failed too, so "
                            "the pins are not the cause"
                        )
                warnings.append(
                    "no arrangement produced a layout with OR without the N/E/S/W "
                    "pins: the exact room sizes admit no rectangular layout for "
                    "any arrangement. Adjust the room dimensions"
                )

    # Time, not max_variants, is the real bound on this endpoint now, so running
    # out of it is a normal outcome and must be stated. Variants are dimensioned
    # base-first then by depth, so what gets skipped is always the most-mutated
    # end of the set - the arrangements furthest from what the user drew.
    # Count only the arrangements TIME dropped: the cap marks its own skips with
    # the same status, and blaming those on the clock would send the user off to
    # raise time_budget_seconds for a limit that has nothing to do with it.
    skipped = sum(1 for p in variant_payloads
                  if p.get("status") == "skipped"
                  and p.get("reason") == "time budget exhausted")
    if truncated and skipped:
        warnings.append(
            f"the {time_budget:.0f}s time budget ran out with {skipped} of "
            f"{len(variant_payloads)} arrangements not yet laid out; they are the "
            "ones furthest from the graph you drew. Raise time_budget_seconds or "
            "lower max_depth to cover them"
        )

    # No silent caps on this endpoint. Say the batch was cut and to what, so a
    # 30-plan catalogue never reads as everything the brief admits.
    cap_lost = cap_info["variants_emptied"] + cap_info["variants_skipped"]
    if cap_info["hit"]:
        warnings.append(
            f"the batch was capped at {max_floorplans} floorplans in total"
            + (f", so {cap_lost} of {len(variant_payloads)} arrangements returned "
               "none; plans are spread one per arrangement before any arrangement "
               "gets a second" if cap_lost else "")
            + ". Raise max_floorplans, or set it to 0, for the whole set"
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
            "requested": _cardinal_payload(requested_pairs, room_names),
            "attempted": _cardinal_payload(cardinal_pairs, room_names),
            # From evidence, not from the absence of the ignore flag: every
            # returned plan passed the geometric gate, so "applied" is true
            # exactly when pinned plans exist. A zero-plan response used to
            # claim applied: true over an empty gallery.
            "applied": bool(cardinal_pairs) and not cardinal_ignored and total_plans > 0,
            "ignored": cardinal_ignored,
            # Third state the binary pair could not express: the pins were
            # neither held nor proven unsatisfiable (sizes fail everywhere, or
            # the clock ran out before the retry).
            "undetermined": bool(cardinal_pairs) and total_plans == 0
                and (cardinal_retry_failed or cardinal_retry_skipped),
        },
        "variant_count": len(variant_payloads),
        "floorplan_count": total_plans,
        "variants": variant_payloads,
        "stats": {
            "variants_generated": generated,
            "variants_after_filter": len(variants),
            "variants_returned": len(variant_payloads),
            "variants_dropped_by_cardinal": cardinal_dropped_variants,
            "variants_kept_by_cardinal_fallback": bool(cardinal_filter_emptied),
            "variants_with_boundary_cap_truncation": sum(
                1 for p in variant_payloads if p.get("boundaries_truncated")),
            "strictness": strictness,
            "preserve_input_edges": preserve_input_edges,
            "protected_edges": [[int(u), int(v)] for u, v in user_needs],
            "max_variants": max_variants,
            "max_depth": max_depth,
            "variant_cap_hit": bool(cap_hit),
            "max_floorplans": max_floorplans,
            "floorplan_cap_hit": bool(cap_info["hit"]),
            "variants_emptied_by_floorplan_cap": cap_info["variants_emptied"],
            "variants_skipped_by_floorplan_cap": cap_info["variants_skipped"],
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
