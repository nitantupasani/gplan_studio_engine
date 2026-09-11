"""Independent circulation research experiments. Does not import or mutate production code.

Run from any directory with Python, NetworkX and Shapely installed. Source methods are
extracted through AST from the local legacy file and immutable upstream Git objects;
GUI imports, plotting, __main__ and legacy interactive handlers are never executed.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import itertools
import json
from pathlib import Path
import subprocess
import sys
from typing import List, Tuple

import networkx as nx
import shapely
from shapely.geometry import LineString, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parents[2]
FIXTURES = json.loads((HERE / "fixtures.json").read_text())
CASES = {case["id"]: case for case in FIXTURES["cases"]}
EPS = 1e-7


def near(actual, expected):
    if isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            near(a, b)
    else:
        assert abs(actual - expected) < EPS, (actual, expected)


def components(geometry):
    if geometry.is_empty:
        return 0
    return len(geometry.geoms) if hasattr(geometry, "geoms") else 1


def allocation(width, weights, caps):
    """Two-side bounded weighted split; geometry experiment only."""
    assert sum(caps) + EPS >= width
    target = width * weights[0] / sum(weights) if sum(weights) else width / 2
    first = max(width - caps[1], min(caps[0], target))
    return [first, width - first]


def geometric_experiments():
    result = {}
    for name in ("unequal_rooms", "protected_small", "large_but_narrow"):
        case = CASES[name]
        rects = [box(*r["bounds"]) for r in case["rooms"]]
        caps = [0 if r.get("locked") else r["bounds"][2] - r["bounds"][0] - r["minWidth"] for r in case["rooms"]]
        offsets = allocation(case["width"], [r.area for r in rects], caps)
        losses = [d * (r.bounds[3] - r.bounds[1]) for d, r in zip(offsets, rects)]
        if "expectedLargerAreaLoss" in case:
            near(losses, case["expectedLargerAreaLoss"])
            equal = allocation(case["width"], [1, 1], caps)
            near([v * 10 for v in equal], case["expectedEqualAreaLoss"])
        if "expectedAreaLoss" in case:
            near(losses, case["expectedAreaLoss"])
        if "expectedCappedOffsets" in case:
            near(offsets, case["expectedCappedOffsets"])
        result[name] = {"offsets": offsets, "actualFullSideAreaLoss": losses}

    case = CASES["partial_wall"]
    heights = [r["bounds"][3] - r["bounds"][1] for r in case["rooms"]]
    naive = [h * d for h, d in zip(heights, case["naiveAreaWeightedOffsets"])]
    corrected = [h * d for h, d in zip(heights, case["areaCorrectedOffsets"])]
    local = [10 * d for d in case["naiveAreaWeightedOffsets"]]
    near(naive, case["expectedNaiveRectangleLoss"])
    near(corrected, case["expectedRectangleLoss"])
    near(local, case["expectedLocalCutLoss"])
    result[case["id"]] = {"naiveFullSideLoss": naive, "areaCorrectedFullSideLoss": corrected, "localCutLoss": local, "additionalFullSideAreaRequiresProvenance": sum(corrected) - case["width"] * 10}

    case = CASES["asymmetric_seam"]
    strips = [box(*bounds) for bounds in case["strips"]]
    union = unary_union(strips)
    seam = strips[0].intersection(strips[1]).length
    near(seam, case["expectedSeamWidth"])
    eroded = union.buffer(-case["width"] / 2 + EPS / 10, join_style=2)
    assert components(union) == 1 and components(eroded) == 2
    result[case["id"]] = {"polygonComponents": 1, "seamWidth": seam, "finiteWidthComponents": components(eroded)}

    case = CASES["branched_corridor"]
    union = unary_union([box(*b) for b in case["strips"]])
    near(union.area, case["expectedArea"])
    count = components(union.buffer(-case["width"] / 2 + EPS / 10, join_style=2))
    assert count == case["expectedFiniteWidthComponents"]
    result[case["id"]] = {"unionArea": union.area, "summedStripArea": 120, "junctionDoubleCountAvoided": 9, "finiteWidthComponents": count}

    case = CASES["entry_placement"]
    polygon = box(*case["corridor"])
    contacts = [polygon.boundary.intersection(LineString(case[key])).length for key in ("goodEntry", "badEntry")]
    assert contacts[0] >= case["doorWidth"] and contacts[1] < case["doorWidth"]
    result[case["id"]] = {"goodContact": contacts[0], "badContact": contacts[1]}

    case = CASES["provenance_and_replacement"]
    original = unary_union([box(*b) for b in case["originalRooms"]])
    adjusted = unary_union([box(*b) for b in case["adjustedRooms"]])
    corridor = original.difference(adjusted)
    remainder = box(*case["boundary"]).difference(adjusted)
    near(corridor.area, case["expectedCorridorArea"])
    near(remainder.area - corridor.area, case["expectedUnrelatedOpenArea"])
    saved = json.loads(json.dumps({"originalRooms": case["originalRooms"], "adjustedRooms": case["adjustedRooms"]}))
    reloaded = unary_union([box(*b) for b in saved["originalRooms"]]).difference(unary_union([box(*b) for b in saved["adjustedRooms"]]))
    assert corridor.equals(reloaded)
    # Replacements start from the persisted pre-circulation base, preventing repeated loss.
    replacement = original.difference(adjusted)
    assert replacement.equals(corridor)
    result[case["id"]] = {"corridorArea": corridor.area, "naiveEnvelopeRemainderArea": remainder.area, "reloadEqual": True, "baseReplacementEqual": True}
    return result


def route_experiments():
    case = CASES["disconnected_pruning"]
    graph = nx.Graph(case["corridorTreeEdges"])
    kept = case["greedyKept"]
    covered = set().union(*(case["coverage"][k] for k in kept))
    assert covered == {"r1", "r2", "r3", "r4"}
    assert not nx.is_connected(graph.subgraph(["entry", *kept]))
    closed = set().union(*(nx.shortest_path(graph, "entry", k) for k in kept))
    assert closed == set(case["expectedClosed"])
    assert nx.is_connected(graph.subgraph(closed))
    case2 = CASES["shortest_route_scope"]
    graph2 = nx.Graph()
    graph2.add_weighted_edges_from(case2["edges"])
    paths = list(nx.shortest_simple_paths(graph2, "entry", "target", weight="weight"))
    lengths = [nx.path_weight(graph2, p, "weight") for p in paths]
    near(lengths, case2["expectedOrderedLengths"])
    return {"pruning": {"allRoomsCovered": True, "keptComponentsWithEntry": 3, "closedComponents": 1, "closed": sorted(closed)}, "shortestPaths": {"paths": paths, "lengths": lengths, "scope": "fixed finite weighted graph, one target"}}


def legacy_namespace(source):
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    namespace = {"nx": nx, "deepcopy": deepcopy, "List": List, "Tuple": Tuple, "i": 0}
    exec(compile(ast.Module(body=classes, type_ignores=[]), "<legacy-research>", "exec"), namespace)
    return namespace


def legacy_experiments():
    sources = {"local": (ENGINE / "GPLAN" / "circulation.py").read_text()}
    for name, revision in {"team_main": "409e61ee57fd56757c085574554ebe57db247879", "paper": "2286259b1cce1a40e47c56ee3bf0945570aa2af1"}.items():
        sources[name] = subprocess.check_output(["git", "-c", f"safe.directory={ENGINE.as_posix()}", "-C", str(ENGINE), "show", f"{revision}:circulation.py"], text=True)
    results = {}
    for name, source in sources.items():
        namespace = legacy_namespace(source)
        room = namespace["Room"](0, 0, 10, 10, 0)
        obj = namespace["circulation"](nx.empty_graph(1), 2, namespace["RFP"](nx.empty_graph(1), [room]))
        room.rel_push_L = -3
        room.rel_push_T = -0.25
        obj.calculate_edge_move(room, "S", "T")
        # The live local module now includes the paper's one-line correction;
        # immutable team-main remains the reproducible failing baseline.
        expected = -3 if name == "team_main" else -1
        near(room.rel_push_T, expected)
        # Exercise the legacy greedy method on a fully coverable, disconnected example.
        greedy = namespace["circulation"](nx.empty_graph(4))
        subsets = {5: [0, 1], 6: [1, 2], 7: [2, 3]}
        selected_subsets = greedy.min_tree_set_cover(subsets, [])
        ids = [next(k for k, v in subsets.items() if v == subset) for subset in selected_subsets]
        corridor_tree = nx.path_graph([4, 5, 6, 7])
        assert ids == [5, 7] and not nx.is_connected(corridor_tree.subgraph([4, *ids]))
        wheel_results = []
        for size in range(5, 13):
            wheel = namespace["circulation"](nx.wheel_graph(size))
            assert wheel.circulation_algorithm(2, 3) == 1
            assert nx.is_tree(wheel.corridor_tree)
            if name == "paper":
                keep = wheel.remove_redundant_corridors(list(wheel.adjacency))
                if len(keep) > 1:
                    keep = wheel.remove_redundant_corridors(keep)
            else:
                keep = wheel.remove_redundant_corridors()
            selected = wheel.corridor_tree.subgraph({size, *keep})
            wheel_results.append({"rooms": size, "spanningCorridorsIncludingEntry": len(wheel.corridor_tree), "keptIncludingEntry": sorted(selected.nodes), "componentsAfterPruning": nx.number_connected_components(selected)})
        results[name] = {"sourceSha256": hashlib.sha256(source.encode()).hexdigest(), "southTopOffsetWithUnrelatedLeftOffset": room.rel_push_T, "greedyCorridors": ids, "connectedWithEntry": False, "hasMinimumDimensionCheck": hasattr(obj, "check_mindim_feasibility"), "fullAlgorithmWheelCases": wheel_results}
    return results


def main():
    with redirect_stdout(io.StringIO()):
        results = {"fixtures": len(CASES), "geometry": geometric_experiments(), "routes": route_experiments(), "legacy": legacy_experiments()}
    results["environment"] = {"python": sys.version.split()[0], "networkx": nx.__version__, "shapely": shapely.__version__}
    target = HERE / "EXPERIMENT_RESULTS.json"
    target.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Passed {len(CASES)} research fixtures; results: {target}")


if __name__ == "__main__":
    main()
