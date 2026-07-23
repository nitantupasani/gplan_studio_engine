"""Cardinal-constraint engine tests (door_connectivity, minDim, multiple).

Run: python GPLAN/test_api_cardinal_constraints.py
See documentation/cardinal_constraints.md for the API contract.

T1: Kitchen (node 2) must face N -> in every plan its top wall == plan top (y min).
T2: same but E -> right wall == plan right edge.
T3: impossible combo (same room N+S) -> ladder still returns plans.
T4: no constraints -> baseline unchanged (plans exist).
T5: entrance rule: entry-adjacent room pinned to S.
"""
import os
import sys
import time

# Run from anywhere: the outer GPLAN directory (this file's parent) is the package root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from GPLAN.api import Documents, normalize_cardinal_constraints, spanning_tree_edges
from GPLAN.source.inputgraph import InputGraph

def make_request(cardinal):
    # 5 rooms: 0 Living, 1 Bed, 2 Kitchen, 3 Bath, 4 Dining
    nodes = []
    labels = ["Living", "Bed", "Kitchen", "Bath", "Dining"]
    import math
    for i, lab in enumerate(labels):
        ang = 2 * math.pi * i / 5
        nodes.append({
            "id": i, "x": 0.5 + 0.4 * math.cos(ang), "y": 0.5 + 0.4 * math.sin(ang),
            "label": lab, "color": "#1C4C82",
            "width": {"min": 3, "max": 99999}, "height": {"min": 3, "max": 99999},
            "ratio": {"min": 3, "max": 99999},
        })
    edges_pairs = [(0,1),(0,2),(0,3),(0,4),(1,2),(2,4)]
    edges = [[a, b, "black"] for a, b in edges_pairs]
    return nodes, edges

def run(cardinal, count=6, plot_width=0, plot_height=0):
    nodes, edges = make_request(cardinal)
    coords = [[n["x"], n["y"]] for n in nodes]
    graph = InputGraph(len(nodes), len(edges), edges, coords)
    dim_inputs = {
        "min_width": [3]*5, "max_width": [99999]*5,
        "min_height": [3]*5, "max_height": [99999]*5,
        "min_ratio": [3]*5, "max_ratio": [99999]*5,
        "plot_width": plot_width, "plot_height": plot_height,
        "symmetric": False, "optimal_floorplan": 0, "rotation_enabled": 0,
    }
    fps, msg = Documents.get_floorplans(
        starting_from=0, count=count, caller="door_connectivity",
        nodes_list=nodes, graph=graph, rectangular=True,
        minDimEnabled=True, nonAdj=False, limit=count, corridor_thickness=0.5,
        dim_inputs=dim_inputs, edges_list=edges, non_adj_edge_list=[],
        cardinal_constraints=cardinal,
    )
    return fps.to_dict()["Documents"]["floorPlans"], msg

def bounds(plan):
    xs, ys = [], []
    for room in plan:
        for w in room["walls"]:
            xs += [w["x1"], w["x2"]]; ys += [w["y1"], w["y2"]]
    return min(xs), max(xs), min(ys), max(ys)

def room_bounds(room):
    xs, ys = [], []
    for w in room["walls"]:
        xs += [w["x1"], w["x2"]]; ys += [w["y1"], w["y2"]]
    return min(xs), max(xs), min(ys), max(ys)

def check_side(plans, room_name, side):
    """Room's <side> face is exterior: no other room intersects the strip
    between that face and the plot boundary on that side."""
    EPS = 1e-6
    ok, tot = 0, 0
    for plan in plans:
        minx, maxx, miny, maxy = bounds(plan)
        target = next((r for r in plan if r["name"] == room_name), None)
        if target is None:
            continue
        tot += 1
        rx0, rx1, ry0, ry1 = room_bounds(target)
        if side == "N":
            strip = (rx0, rx1, miny, ry0)
        elif side == "S":
            strip = (rx0, rx1, ry1, maxy)
        elif side == "W":
            strip = (minx, rx0, ry0, ry1)
        else:
            strip = (rx1, maxx, ry0, ry1)
        sx0, sx1, sy0, sy1 = strip
        blocked = False
        for other in plan:
            if other is target:
                continue
            ox0, ox1, oy0, oy1 = room_bounds(other)
            ix = min(ox1, sx1) - max(ox0, sx0)
            iy = min(oy1, sy1) - max(oy0, sy0)
            if ix > EPS and iy > EPS:
                blocked = True
                break
        ok += (not blocked)
    return ok, tot

def main():
    t0 = time.time()
    print("== T1: Kitchen -> N ==")
    plans, msg = run([{"room": 2, "direction": "N"}])
    ok, tot = check_side(plans, "Kitchen", "N")
    print(f"plans={len(plans)} kitchen-on-top {ok}/{tot} msg={msg!r}")
    assert len(plans) > 0 and ok == tot and tot > 0, "T1 FAILED"

    print("== T2: Kitchen -> E ==")
    plans, msg = run([{"room": 2, "direction": "E"}])
    ok, tot = check_side(plans, "Kitchen", "E")
    print(f"plans={len(plans)} kitchen-on-right {ok}/{tot} msg={msg!r}")
    assert len(plans) > 0 and ok == tot and tot > 0, "T2 FAILED"

    print("== T3: impossible (Kitchen N + S, Living N, Bed N, Bath N, Dining N) ==")
    plans, msg = run([
        {"room": 2, "direction": "N"}, {"room": 2, "direction": "S"},
        {"room": 0, "direction": "N"}, {"room": 1, "direction": "N"},
        {"room": 3, "direction": "N"}, {"room": 4, "direction": "N"},
    ])
    print(f"plans={len(plans)} msg={msg!r}")
    assert len(plans) > 0, "T3 FAILED (no plans at all)"

    print("== T4: no constraints (baseline) ==")
    plans, msg = run([])
    print(f"plans={len(plans)} msg={msg!r}")
    assert len(plans) > 0, "T4 FAILED"

    print("== T5: two constraints: Bed -> S (entry target), Kitchen -> N ==")
    plans, msg = run([{"room": 1, "direction": "S"}, {"room": 2, "direction": "N"}])
    ok1, tot1 = check_side(plans, "Bed", "S")
    ok2, tot2 = check_side(plans, "Kitchen", "N")
    print(f"plans={len(plans)} bed-S {ok1}/{tot1} kitchen-N {ok2}/{tot2} msg={msg!r}")
    assert len(plans) > 0 and ok1 == tot1 and ok2 == tot2, "T5 FAILED"

    print("== T6: wheel graph, interior hub -> N (needs adjacency relaxation) ==")
    # hub 0 connected to rim 1-4; rim cycle closes -> hub is interior in every
    # embedding, so hub->N is impossible without dropping rim edges.
    import math
    nodes = []
    for i, lab in enumerate(["Hub", "R1", "R2", "R3", "R4"]):
        ang = 2 * math.pi * i / 5
        nodes.append({
            "id": i, "x": 0.5 + 0.4 * math.cos(ang), "y": 0.5 + 0.4 * math.sin(ang),
            "label": lab, "color": "#1C4C82",
            "width": {"min": 3, "max": 99999}, "height": {"min": 3, "max": 99999},
            "ratio": {"min": 3, "max": 99999},
        })
    edges = [[0,1,"black"],[0,2,"black"],[0,3,"black"],[0,4,"black"],
             [1,2,"black"],[2,3,"black"],[3,4,"black"],[4,1,"black"]]
    coords = [[n["x"], n["y"]] for n in nodes]
    graph = InputGraph(len(nodes), len(edges), edges, coords)
    dim_inputs = {
        "min_width": [3]*5, "max_width": [99999]*5,
        "min_height": [3]*5, "max_height": [99999]*5,
        "min_ratio": [3]*5, "max_ratio": [99999]*5,
        "plot_width": 0, "plot_height": 0,
        "symmetric": False, "optimal_floorplan": 0, "rotation_enabled": 0,
    }
    fps, msg = Documents.get_floorplans(
        starting_from=0, count=6, caller="door_connectivity",
        nodes_list=nodes, graph=graph, rectangular=True,
        minDimEnabled=True, nonAdj=False, limit=6, corridor_thickness=0.5,
        dim_inputs=dim_inputs, edges_list=edges, non_adj_edge_list=[],
        cardinal_constraints=[{"room": 0, "direction": "N"}],
    )
    plans = fps.to_dict()["Documents"]["floorPlans"]
    ok, tot = check_side(plans, "Hub", "N")
    print(f"plans={len(plans)} hub-N {ok}/{tot} msg={msg!r}")
    assert len(plans) > 0, "T6 FAILED (no plans)"
    assert ("relaxed" in msg) or (ok == tot and tot > 0), "T6 FAILED (no relaxation and hub not N)"

    print("== T7: plot dims present (dim_on_paths_bdy active): Kitchen -> N, Bed -> S ==")
    # Regression: with plot_width/plot_height set (the production designer path),
    # dim_on_paths_bdy used to rearrange the four boundary paths after the
    # cardinal filter, scrambling the N/E/S/W assignment.
    plans, msg = run([{"room": 2, "direction": "N"}, {"room": 1, "direction": "S"}],
                     plot_width=30, plot_height=20)
    ok1, tot1 = check_side(plans, "Kitchen", "N")
    ok2, tot2 = check_side(plans, "Bed", "S")
    print(f"plans={len(plans)} kitchen-N {ok1}/{tot1} bed-S {ok2}/{tot2} msg={msg!r}")
    assert len(plans) > 0, "T7 FAILED (no plans)"
    if "ignored" not in msg:
        assert ok1 == tot1 and ok2 == tot2 and tot1 > 0, "T7 FAILED (cardinal violated with plot dims)"

    print("== T8: 13-room designer-like unit, plot 54x40: Balcony -> W, Utility -> N, Bedroom2 -> E ==")
    labels = ["Living Room", "Dining", "Kitchen", "Master Bedroom", "Bedroom",
              "Bedroom 2", "Bedroom 3", "Bathroom", "Bathroom 2", "Toilet",
              "Utility", "Balcony", "Study"]
    import math
    nodes = []
    for i, lab in enumerate(labels):
        ang = 2 * math.pi * i / len(labels)
        nodes.append({
            "id": i, "x": 0.5 + 0.4 * math.cos(ang), "y": 0.5 + 0.4 * math.sin(ang),
            "label": lab, "color": "#1C4C82",
            "width": {"min": 4, "max": 99999}, "height": {"min": 4, "max": 99999},
            "ratio": {"min": 3, "max": 99999},
        })
    edges_pairs = [(0, 1), (0, 11), (0, 12), (0, 8), (1, 2), (1, 5), (2, 10), (2, 4),
                   (4, 7), (4, 9), (4, 3), (4, 11), (3, 6), (5, 8)]
    edges = [[a, b, "black"] for a, b in edges_pairs]
    coords = [[n["x"], n["y"]] for n in nodes]
    graph = InputGraph(len(nodes), len(edges), edges, coords)
    n = len(labels)
    dim_inputs = {
        "min_width": [4]*n, "max_width": [99999]*n,
        "min_height": [4]*n, "max_height": [99999]*n,
        "min_ratio": [3]*n, "max_ratio": [99999]*n,
        "plot_width": 54, "plot_height": 40,
        "symmetric": False, "optimal_floorplan": 0, "rotation_enabled": 0,
    }
    cardinal = [{"room": 11, "direction": "W"}, {"room": 10, "direction": "N"},
                {"room": 5, "direction": "E"}]
    fps, msg = Documents.get_floorplans(
        starting_from=0, count=8, caller="door_connectivity",
        nodes_list=nodes, graph=graph, rectangular=True,
        minDimEnabled=True, nonAdj=False, limit=8, corridor_thickness=0.5,
        dim_inputs=dim_inputs, edges_list=edges, non_adj_edge_list=[],
        cardinal_constraints=cardinal,
    )
    plans = fps.to_dict()["Documents"]["floorPlans"]
    okW, totW = check_side(plans, "Balcony", "W")
    okN, totN = check_side(plans, "Utility", "N")
    okE, totE = check_side(plans, "Bedroom 2", "E")
    print(f"plans={len(plans)} balcony-W {okW}/{totW} utility-N {okN}/{totN} "
          f"bedroom2-E {okE}/{totE} msg={msg!r}")
    assert len(plans) > 0, "T8 FAILED (no plans)"
    if "ignored" not in msg:
        assert okW == totW and okN == totN and okE == totE and totW > 0, \
            "T8 FAILED (cardinal violated on 13-room unit)"

    print(f"ALL CARDINAL TESTS PASSED in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
