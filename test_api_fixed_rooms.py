"""Hard fixed-room tests for min-dimensioned door_connectivity.

Run from the engine repository root::

    python -m pytest -q test_api_fixed_rooms.py

The production-path test deliberately enables enforce_plot,
rectangularize_output and post-processing exact fill together.  Those are the
three stages that used to widen, grow or scale a min==max staircase.
"""
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.api import Documents, normalize_fixed_rooms, plan_satisfies_fixed
from GPLAN.source.dimensioning.minimum_dimensioning import upper_bound
from GPLAN.source.inputgraph import InputGraph


def _node(index, label, min_w, max_w, min_h, max_h, fixed=False,
          anchor=None):
    angle = 2 * math.pi * index / 6
    node = {
        "id": index,
        "x": 0.5 + 0.4 * math.cos(angle),
        "y": 0.5 + 0.4 * math.sin(angle),
        "label": label,
        "color": "#1C4C82",
        "width": {"min": min_w, "max": max_w},
        "height": {"min": min_h, "max": max_h},
        "ratio": {"min": 0.5, "max": 3},
    }
    if fixed:
        node["is_fixed"] = True
        node["fixed_anchor"] = anchor
    return node


def _request(two_fixed=False, stair_anchor="NW", plot_width=30,
             plot_height=24):
    nodes = [
        _node(0, "Living Room", 6, 18, 6, 16),
        _node(1, "Dining", 5, 14, 5, 12),
        _node(2, "Kitchen", 5, 12, 5, 10),
        _node(3, "Bedroom", 6, 14, 6, 14),
        _node(4, "Bathroom", 4, 8, 4, 8,
              fixed=two_fixed, anchor="NW" if two_fixed else None),
        _node(5, "Staircase", 7, 7, 10, 10,
              fixed=True, anchor=stair_anchor),
    ]
    if two_fixed:
        nodes[4]["width"] = {"min": 6, "max": 6}
        nodes[4]["height"] = {"min": 6, "max": 6}

    pairs = [(0, 1), (0, 2), (0, 3), (3, 4), (0, 5)]
    edges = [[a, b, "black"] for a, b in pairs]
    dim_inputs = {
        "min_width": [n["width"]["min"] for n in nodes],
        "max_width": [n["width"]["max"] for n in nodes],
        "min_height": [n["height"]["min"] for n in nodes],
        "max_height": [n["height"]["max"] for n in nodes],
        "min_ratio": [0.5] * len(nodes),
        "max_ratio": [3] * len(nodes),
        "min_area": [0] * len(nodes),
        "max_area": [0] * len(nodes),
        "plot_width": plot_width,
        "plot_height": plot_height,
        "symmetric": False,
        "optimal_floorplan": 1,
        # The engine must turn this off because a fixed 7x10 axis band cannot
        # survive the legacy width/height swap.
        "rotation_enabled": 1,
        "enforce_plot": True,
    }
    graph = InputGraph(
        len(nodes), len(edges), edges, [[n["x"], n["y"]] for n in nodes])
    return nodes, edges, dim_inputs, graph


def _generate(two_fixed=False, stair_anchor="NW", plot_width=30,
              plot_height=24):
    nodes, edges, dim_inputs, graph = _request(
        two_fixed=two_fixed, stair_anchor=stair_anchor,
        plot_width=plot_width, plot_height=plot_height)
    response, message = Documents.get_floorplans(
        starting_from=0,
        count=8,
        caller="door_connectivity",
        nodes_list=nodes,
        graph=graph,
        rectangular=True,
        minDimEnabled=True,
        nonAdj=False,
        limit=8,
        corridor_thickness=0.5,
        dim_inputs=dim_inputs,
        edges_list=edges,
        non_adj_edge_list=[],
        # No explicit cardinal entry: fixed_anchor injects its hard directions.
        cardinal_constraints=[],
        postProcessEnabled=True,
        postprocess_options={
            "target_width": plot_width,
            "target_height": plot_height,
            "prefer_rectangle": False,
            "exact_fill": True,
        },
    )
    return response.to_dict()["Documents"], message


def _room_rect(room):
    xs = []
    ys = []
    for wall in room["walls"]:
        xs.extend((wall["x1"], wall["x2"]))
        ys.extend((wall["y1"], wall["y2"]))
    return min(xs), min(ys), max(xs), max(ys)


def _plan_rect(plan):
    rects = [_room_rect(room) for room in plan]
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def _overlap_area(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * \
        max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def test_fixed_node_hardens_view_opened_maxima_and_solver_slack():
    nodes, _edges, dim_inputs, _graph = _request()
    # Simulate an older production view opening all minDim maximums.
    dim_inputs["max_width"][5] = 99999
    dim_inputs["max_height"][5] = 99999
    fixed = normalize_fixed_rooms(nodes, dim_inputs, True)
    assert fixed == [{
        "room": 5, "width": 7.0, "height": 10.0,
        "anchor": "NW", "directions": (0, 3),
    }]
    assert dim_inputs["min_width"][5] == dim_inputs["max_width"][5] == 7
    assert dim_inputs["min_height"][5] == dim_inputs["max_height"][5] == 10
    assert dim_inputs["min_area"][5] == dim_inputs["max_area"][5] == 70
    assert upper_bound(7, 7) > 7, "normal room ceilings keep solver slack"
    assert upper_bound(7, 7, exact=True) == 7, "fixed equality bypasses slack"


def test_nw_stair_is_exact_through_enforce_plot_rectangularize_and_postprocess():
    document, message = _generate()
    plans = document["floorPlans"]
    assert plans, message
    assert document.get("postprocess") is not None
    assert document.get("plot_fit") is not None
    assert len(document["postprocess"]) == len(plans)
    assert len(document["plot_fit"]) == len(plans)
    assert any(row["fits"] for row in document["plot_fit"]), document["plot_fit"]

    for plan in plans:
        stair = next(room for room in plan if room["name"] == "Staircase")
        sx0, sy0, sx1, sy1 = _room_rect(stair)
        px0, py0, _px1, _py1 = _plan_rect(plan)
        assert abs((sx1 - sx0) - 7) <= 0.05
        assert abs((sy1 - sy0) - 10) <= 0.05
        assert abs(sx0) <= 0.05, "fixed NW stair is not at absolute left=0"
        assert abs(sy0) <= 0.05, "fixed NW stair is not at absolute top=0"
        assert abs(sx0 - px0) <= 0.05, "fixed NW stair lost its west contact"
        assert abs(sy0 - py0) <= 0.05, "fixed NW stair lost its north contact"


def test_sw_stair_is_exact_and_locked_to_the_real_plot_bottom():
    document, message = _generate(stair_anchor="SW")
    plans = document["floorPlans"]
    assert plans, message

    for plan in plans:
        stair = next(room for room in plan if room["name"] == "Staircase")
        sx0, sy0, sx1, sy1 = _room_rect(stair)
        px0, _py0, _px1, py1 = _plan_rect(plan)
        assert abs((sx1 - sx0) - 7) <= 0.05
        assert abs((sy1 - sy0) - 10) <= 0.05
        assert abs(sx0) <= 0.05, "fixed SW stair is not at absolute left=0"
        assert abs(sy1 - 24) <= 0.05, "fixed SW stair is not at plot bottom=24"
        assert abs(sx0 - px0) <= 0.05, "fixed SW stair lost its west contact"
        assert abs(sy1 - py1) <= 0.05, "fixed SW stair lost its south contact"


def _generate_housing_2bhk():
    """Run the exact 30x40 payload produced by housingUnitForApi."""
    specs = [
        ("Living Room", 14, 22, 13, 24),
        ("Dining", 9, 16, 10, 16),
        ("Kitchen", 7, 12, 8, 13),
        ("Bedroom", 10, 14, 11, 16),
        ("Bedroom 2", 10, 14, 11, 16),
        ("Bathroom", 5, 8, 7, 10),
        ("Toilet", 4, 6, 5, 8),
        ("Staircase", 7, 7, 10, 10),
    ]
    nodes = [
        _node(i, label, min_w, max_w, min_h, max_h,
              fixed=label == "Staircase",
              anchor="SW" if label == "Staircase" else None)
        for i, (label, min_w, max_w, min_h, max_h) in enumerate(specs)
    ]
    pairs = [
        (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 7),
        (1, 2), (1, 4), (1, 6), (3, 5), (4, 5), (4, 6),
    ]
    edges = [[a, b, "black"] for a, b in pairs]
    dim_inputs = {
        "min_width": [n["width"]["min"] for n in nodes],
        "max_width": [n["width"]["max"] for n in nodes],
        "min_height": [n["height"]["min"] for n in nodes],
        "max_height": [n["height"]["max"] for n in nodes],
        "min_ratio": [1] * len(nodes),
        "max_ratio": [2.4, 2, 2.4, 1.8, 1.8, 2, 2.2, 10 / 7],
        "min_area": [0] * 7 + [70],
        "max_area": [0] * 7 + [70],
        "plot_width": 30,
        "plot_height": 40,
        "symmetric": False,
        "optimal_floorplan": 1,
        "rotation_enabled": 1,
        "enforce_plot": True,
    }
    graph = InputGraph(
        len(nodes), len(edges), edges,
        [[n["x"], n["y"]] for n in nodes])
    response, message = Documents.get_floorplans(
        starting_from=0,
        count=30,
        caller="door_connectivity",
        nodes_list=nodes,
        graph=graph,
        rectangular=True,
        minDimEnabled=True,
        nonAdj=False,
        limit=30,
        corridor_thickness=0.5,
        dim_inputs=dim_inputs,
        edges_list=edges,
        non_adj_edge_list=[],
        cardinal_constraints=[],
        postProcessEnabled=True,
        postprocess_options={
            "target_width": 30,
            "target_height": 40,
            "prefer_rectangle": False,
            "exact_fill": True,
        },
    )
    return response.to_dict()["Documents"], message


def test_housing_2bhk_30x40_sw_request_fills_plot_with_exact_stairs():
    """Fixed core, exact plot envelope, and catalogue size are all hard.

    The pre-fix pipeline kept only the rare compacted topology whose south
    edge already happened to equal 40, then exact-fill resized the Staircase
    and the validator rolled the whole plan back.  That produced one plan
    with a large unused east strip.  Relative SW candidates must instead be
    aligned into the plot frame and filled around an immutable core.
    """
    document, message = _generate_housing_2bhk()
    plans = document["floorPlans"]
    assert plans, message
    assert len(plans) > 1, "fixed filtering collapsed a feasible catalogue"
    assert len(document["postprocess"]) == len(plans)
    for index, plan in enumerate(plans):
        rects = [_room_rect(room) for room in plan]
        stair = next(room for room in plan if room["name"] == "Staircase")
        sx0, sy0, sx1, sy1 = _room_rect(stair)
        px0, py0, px1, py1 = _plan_rect(plan)
        assert abs((sx1 - sx0) - 7) <= 0.05
        assert abs((sy1 - sy0) - 10) <= 0.05
        assert abs(sx0) <= 0.05
        assert abs(sy1 - 40) <= 0.05
        assert abs(px0) <= 0.05
        assert abs(py0) <= 0.05
        assert abs(px1 - 30) <= 0.05
        assert abs(py1 - 40) <= 0.05
        # An exact bbox is insufficient: the old UI labelled the only result
        # "Empty space" because a residual strip/notch remained. Rectangular,
        # non-overlapping rooms must cover the client's 99.5% fill threshold.
        assert all(_overlap_area(a, b) <= 0.01
                   for i, a in enumerate(rects)
                   for b in rects[i + 1:])
        covered = sum((x1 - x0) * (y1 - y0)
                      for x0, y0, x1, y1 in rects)
        assert covered >= 30 * 40 * 0.995
        assert abs(covered - 30 * 40) <= 1.2
        report = document["postprocess"][index]
        assert report["gapless_after"]
        assert report["extent_after"] == [30.0, 40.0]


def test_nw_lock_rejects_a_translated_whole_plan():
    spec = [{
        "room": 0, "width": 7.0, "height": 10.0,
        "anchor": "NW", "directions": (0, 3),
    }]
    translated = SimpleNamespace(final_traversal=[
        [(5, 4), (12, 4), (12, 14), (5, 14)],
        [(12, 4), (18, 4), (18, 14), (12, 14)],
    ])
    assert not plan_satisfies_fixed(translated, spec)


def test_incompatible_hard_nw_rooms_return_no_invalid_fallback():
    document, message = _generate(two_fixed=True)
    assert document["floorPlans"] == []
    assert "hard" in message.lower()
    assert "no invalid fallback" in message.lower()


def test_fixed_band_must_be_exact():
    nodes, _edges, dim_inputs, _graph = _request()
    nodes[5]["width"] = {"min": 7, "max": 8}
    try:
        normalize_fixed_rooms(nodes, dim_inputs, True)
    except ValueError as exc:
        assert "equal positive width min/max" in str(exc)
    else:
        raise AssertionError("a non-equality fixed width was accepted")


# ---------------------------------------------------------------------------
# the housing 2BHK brief with the mandatory south-west stair (2026-09-02)
# ---------------------------------------------------------------------------

_HOUSING_2BHK_REQUEST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_api_fixed_rooms_housing_2bhk.json")


def _housing_2bhk_kwargs():
    """The exact request the housing page sends for a 2BHK on a 30 x 40 ft
    plot with the 7 x 10 ft stair core anchored SW (captured 2026-09-02)."""
    import json
    from local_engine_bridge import _prepare

    with open(_HOUSING_2BHK_REQUEST, "r") as handle:
        payload = json.load(handle)
    return payload, _prepare(payload, "door_connectivity")


def test_ring_builder_finds_the_full_2bhk_ring_and_a_row_compatible_neighbour():
    """The DFS-preorder family found no ring for the 12-edge brief, so the
    stair ran unringed and its boundary neighbour was whatever biconnectivity
    chose (a bedroom, whose 11 ft minimum can never share a 10 ft stair row).
    The exhaustive search finds both valid orders and picks the one whose
    stair neighbours can tile: the Kitchen (8-13 ft tall) beside the stair,
    the Living Room (its door host) above it."""
    from GPLAN.api import (_ring_orders_exhaustive, build_cardinal_ring,
                           fixed_cardinal_pairs)

    payload, kwargs = _housing_2bhk_kwargs()
    nodes = payload["nodes"]
    edges = kwargs["edges_list"]
    fixed = normalize_fixed_rooms(nodes, dict(kwargs["dim_inputs"]), True)
    pairs = fixed_cardinal_pairs(fixed)
    labels = [node["label"] for node in nodes]
    n = len(nodes)
    adjset = {i: set() for i in range(n)}
    for edge in edges:
        adjset[int(edge[0])].add(int(edge[1]))
        adjset[int(edge[1])].add(int(edge[0]))
    pins = {}
    for node, direction in pairs:
        pins.setdefault(node, set()).add(direction)

    orders = _ring_orders_exhaustive(n, adjset, edges, pins)
    assert len(orders) == 2, orders

    ring = build_cardinal_ring(n, edges, pairs, nodes_list=nodes, fixed_rooms=fixed)
    assert ring is not None, "the full brief has a valid ring; None starved the stair of it"
    _ring_edges, coords = ring
    order = sorted(range(n), key=lambda v: math.atan2(coords[v][1] - 0.5, coords[v][0] - 0.5) % (2 * math.pi))
    stair = labels.index("Staircase")
    k = order.index(stair)
    neighbours = {labels[order[k - 1]], labels[order[(k + 1) % n]]}
    assert neighbours == {"Kitchen", "Living Room"}, [labels[v] for v in order]


def test_housing_2bhk_sw_stair_yields_a_catalogue_with_every_adjacency_kept():
    """Before: 3 plans, all from the spanning-tree retry (adjacencies dropped).
    After: the full graph tiles around the anchored stair on the first attempt,
    every plan keeps the stair exactly at 7 x 10 in the plot's south-west
    corner and fills the 30 x 40 ft plot; no relaxation, no dropped plans."""
    _payload, kwargs = _housing_2bhk_kwargs()
    response, message = Documents.get_floorplans(**kwargs)
    plans = response.to_dict()["Documents"]["floorPlans"]
    assert len(plans) >= 20, (len(plans), message)
    assert "relaxed" not in message, message
    assert "dropped because hard fixed-room" not in message, message
    for plan in plans:
        stair = next(room for room in plan if room["name"] == "Staircase")
        sx0, sy0, sx1, sy1 = _room_rect(stair)
        assert abs((sx1 - sx0) - 7) <= 0.05
        assert abs((sy1 - sy0) - 10) <= 0.05
        assert abs(sx0) <= 0.05 and abs(sy1 - 40) <= 0.05, (sx0, sy1)
        px0, py0, px1, py1 = _plan_rect(plan)
        assert abs(px0) <= 0.05 and abs(py0) <= 0.05
        assert abs(px1 - 30) <= 0.05 and abs(py1 - 40) <= 0.05, (px1, py1)


def test_anchor_translation_moves_a_recessed_lock_only_into_free_space():
    from GPLAN.api import _anchor_locked_rects

    spec = [{"room": 1, "width": 7.0, "height": 10.0, "anchor": "SW",
             "directions": (2, 3), "bottom": 40.0}]
    # stair recessed 3 ft from the west edge, nothing beside it: moves to x=0
    rects = [(0.0, 0.0, 20.0, 30.0), (3.0, 30.0, 10.0, 40.0), (10.0, 30.0, 20.0, 40.0)]
    moved = _anchor_locked_rects(rects, spec, 0.01)
    assert moved[1] == (0.0, 30.0, 7.0, 40.0)
    assert moved[0] == rects[0] and moved[2] == rects[2]
    # the west spot is taken: the lock stays where it is
    rects = [(0.0, 0.0, 20.0, 30.0), (3.0, 30.0, 10.0, 40.0), (0.0, 30.0, 3.0, 40.0)]
    assert _anchor_locked_rects(rects, spec, 0.01)[1] == (3.0, 30.0, 10.0, 40.0)
    # an expanded (scaled) lock is never translated
    rects = [(0.0, 0.0, 20.0, 30.0), (3.0, 30.0, 11.8, 40.0)]
    assert _anchor_locked_rects(rects, spec, 0.01)[1] == (3.0, 30.0, 11.8, 40.0)
