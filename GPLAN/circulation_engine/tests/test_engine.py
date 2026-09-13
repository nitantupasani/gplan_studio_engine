import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from shapely.geometry import Polygon

from GPLAN.circulation_engine import CirculationError, generate_circulation, get_capabilities, validate_circulation
from GPLAN.circulation_engine.algorithms import wall_graph, shortest_paths
from GPLAN.circulation_engine.models import parse_request


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def minimal_request():
    return {"schema_version": "1.0", "plan_id": "fixture-floor-1", "source_fingerprint": "fixture-revision-1", "units": "ft",
            "boundary": rectangle(0, 0, 30, 10), "holes": [], "entry": {"point": [20, 0]}, "width": 3,
            "rooms": [{"id": "large", "name": "Living", "polygon": rectangle(0, 0, 20, 10), "min_width": 6, "min_height": 6, "min_area": 36},
                      {"id": "small", "name": "Bedroom", "polygon": rectangle(20, 0, 30, 10), "min_width": 6, "min_height": 6, "min_area": 36}],
            "required_room_ids": ["large", "small"], "modes": ["spanning", "compact"], "contribution_policy": "area", "openings": [], "candidate_limit": 6}


def grid_request(columns=2, rows=2):
    payload = minimal_request()
    payload.update(boundary=rectangle(0, 0, columns * 12, rows * 12), entry={"point": [12, 0]}, rooms=[])
    for row in range(rows):
        for col in range(columns):
            payload["rooms"].append({"id": f"r{row}-{col}", "name": f"Room {row}-{col}", "polygon": rectangle(col * 12, row * 12, (col + 1) * 12, (row + 1) * 12), "min_width": 6, "min_height": 6, "min_area": 36})
    payload["required_room_ids"] = [r["id"] for r in payload["rooms"]]
    return payload


class CirculationEngineTests(unittest.TestCase):
    def candidate(self, payload=None):
        request = payload or minimal_request()
        result = generate_circulation(request)
        self.assertTrue(result["candidates"], result)
        candidate = result["candidates"][0]
        self.assertTrue(candidate["validation"]["valid"], candidate["validation"])
        return candidate

    def test_default_larger_room_contributes_more_actual_area(self):
        candidate = self.candidate()
        areas = {c["room_id"]: c["area_taken"] for c in candidate["contributions"]}
        self.assertAlmostEqual(areas["large"], 20, places=3)
        self.assertAlmostEqual(areas["small"], 10, places=3)
        self.assertEqual(candidate["metrics"]["width"], 3)
        self.assertEqual(candidate["coverage"]["count"], 2)

    def test_equal_sharing_legacy_baseline(self):
        request = minimal_request()
        request["contribution_policy"] = "equal"
        contributions = self.candidate(request)["contributions"]
        self.assertAlmostEqual(contributions[0]["area_taken"], 15, places=4)
        self.assertAlmostEqual(contributions[1]["area_taken"], 15, places=4)

    def test_surplus_uses_actual_remaining_area(self):
        request = minimal_request()
        request["contribution_policy"] = "surplus"
        request["rooms"][0]["min_area"] = 190
        candidate = self.candidate(request)
        contributions = {c["room_id"]: c["area_taken"] for c in candidate["contributions"]}
        self.assertLess(contributions["large"], contributions["small"])
        self.assertLessEqual(contributions["large"], 10.00001)

    def test_locked_and_protected_contribute_zero(self):
        for flag in ("locked", "protected"):
            request = minimal_request()
            request["rooms"][1][flag] = True
            if flag == "locked":
                request["required_room_ids"] = ["large"]
            request["contribution_policy"] = "protected"
            candidate = self.candidate(request)
            small = next(c for c in candidate["contributions"] if c["room_id"] == "small")
            self.assertAlmostEqual(small["area_taken"], 0)

    def test_larger_room_at_width_minimum_redistributes(self):
        request = minimal_request()
        request["rooms"][0]["min_width"] = 20
        candidate = self.candidate(request)
        contribution = {c["room_id"]: c["area_taken"] for c in candidate["contributions"]}
        self.assertAlmostEqual(contribution["large"], 0, places=5)
        self.assertAlmostEqual(contribution["small"], 30, places=5)

    def test_locked_core_does_not_acquire_unrequested_door(self):
        request = minimal_request()
        request["rooms"][1]["locked"] = True
        request["required_room_ids"] = ["large"]
        candidate = self.candidate(request)
        self.assertFalse(any("small" in opening["room_ids"] for opening in candidate["openings"]))
        request["required_room_ids"].append("small")
        result = generate_circulation(request)
        self.assertFalse(result["candidates"])
        self.assertEqual(result["diagnostics"][0]["code"], "infeasible_fixed_access")

    def test_two_minimum_rooms_reject_width(self):
        request = minimal_request()
        request["rooms"][0]["min_width"] = 20
        request["rooms"][1]["min_width"] = 10
        result = generate_circulation(request)
        self.assertEqual(result["status"], "infeasible")
        self.assertTrue(all(d["code"] == "infeasible_dimensions" for d in result["diagnostics"]))

    def test_impossible_width(self):
        request = minimal_request()
        request["width"] = 25
        self.assertFalse(generate_circulation(request)["candidates"])

    def test_cross_junction_and_no_double_area_counting(self):
        request = grid_request(2, 2)
        request["contribution_policy"] = "equal"
        candidate = self.candidate(request)
        self.assertTrue(candidate["validation"]["checks"]["finite_width"])
        self.assertAlmostEqual(candidate["metrics"]["area"], 3 * 24, places=4)
        # The complete vertical wall run already serves all four rooms, so
        # adding a horizontal corridor would be an unneeded duplicate option.
        self.assertEqual(len(candidate["centerlines"]), 1)

    def test_branched_network(self):
        candidate = self.candidate(grid_request(3, 3))
        self.assertGreater(len(candidate["centerlines"]), 1)
        self.assertTrue(candidate["validation"]["checks"]["finite_width"])
        self.assertEqual(candidate["coverage"]["count"], 9)
        area_taken = sum(c["area_taken"] for c in candidate["contributions"])
        self.assertAlmostEqual(area_taken, candidate["metrics"]["area"], places=4)

    def test_t_partition_partial_contacts_supported(self):
        request = minimal_request()
        request.update(boundary=rectangle(0, 0, 24, 24), entry={"point": [0, 12]})
        request["rooms"] = [
            {"id": "top", "polygon": rectangle(0, 0, 24, 12)},
            {"id": "left", "polygon": rectangle(0, 12, 12, 24)},
            {"id": "right", "polygon": rectangle(12, 12, 24, 24)}]
        request["required_room_ids"] = [r["id"] for r in request["rooms"]]
        candidate = self.candidate(request)
        contribution = {c["room_id"]: c["area_taken"] for c in candidate["contributions"]}
        self.assertGreater(contribution["top"], contribution["left"])
        self.assertAlmostEqual(contribution["top"], 2 * contribution["left"], places=3)

    def test_partial_side_ending_outdoors_is_explicitly_unsupported(self):
        request = minimal_request()
        request["rooms"][1]["polygon"] = rectangle(20, 0, 30, 8)
        with self.assertRaises(CirculationError) as raised:
            generate_circulation(request)
        self.assertEqual(raised.exception.code, "unsupported_entry")

    def test_preexisting_empty_space_and_obstacle_retained(self):
        request = minimal_request()
        request["boundary"] = rectangle(0, 0, 40, 15)
        request["obstacles"] = [rectangle(32, 3, 35, 7)]
        candidate = self.candidate(request)
        surface = Polygon(candidate["corridors"][0]["polygon"])
        self.assertEqual(surface.intersection(Polygon(rectangle(30, 0, 40, 15))).area, 0)
        self.assertAlmostEqual(surface.area, 30, places=4)

    def test_boundary_hole_preserved(self):
        request = minimal_request()
        request["boundary"] = rectangle(0, 0, 40, 15)
        request["holes"] = [rectangle(32, 3, 35, 7)]
        self.candidate(request)

    def test_irregular_room_and_one_room_rejected(self):
        for variant in ("one", "notch"):
            request = minimal_request()
            if variant == "one":
                request["rooms"] = request["rooms"][:1]
            else:
                request["rooms"][0]["polygon"] = [[0, 0], [20, 0], [20, 10], [4, 10], [4, 8], [0, 8]]
            with self.assertRaises(CirculationError) as raised:
                generate_circulation(request)
            self.assertEqual(raised.exception.code, "unsupported_geometry")

    def test_shortest_single_destination_fixed_graph_optimum(self):
        request = grid_request(3, 3)
        request["modes"] = ["shortest"]
        request["required_room_ids"] = ["r2-2"]
        candidate = self.candidate(request)
        parsed = parse_request(request)
        groups, graph, roots = wall_graph(parsed)
        distances, paths = shortest_paths(groups, graph, roots)
        # Independent exhaustive simple-path enumeration on this tiny graph.
        def enumerate_cost(node, seen, cost):
            if "r2-2" in groups[node].rooms:
                yield cost
            for neighbor in graph[node] - seen:
                yield from enumerate_cost(neighbor, seen | {neighbor}, cost + groups[neighbor].length)
        optimum = min(cost for root in roots for cost in enumerate_cost(root, {root}, groups[root].length))
        self.assertEqual(candidate["metrics"]["length"], optimum)
        self.assertEqual(candidate["algorithm"]["optimality"], "exact_fixed_wall_graph")

    def test_shortest_multi_destination_never_falls_back(self):
        request = minimal_request()
        request["modes"] = ["shortest"]
        result = generate_circulation(request)
        self.assertFalse(result["candidates"])
        self.assertEqual(result["diagnostics"][0]["code"], "unsupported_scope")

    def test_selected_scope_and_honest_heuristic_labels(self):
        request = grid_request(3, 3)
        request["required_room_ids"] = ["r0-0", "r0-1"]
        candidate = self.candidate(request)
        self.assertEqual(candidate["coverage"]["scope"], "selected")
        self.assertEqual(candidate["coverage"]["count"], 2)
        self.assertEqual(candidate["algorithm"]["optimality"], "heuristic")

    def test_opening_on_shifted_wall_is_reconciled_for_both_rooms(self):
        request = minimal_request()
        request["openings"] = [{"id": "shared-door", "kind": "door", "orientation": "v", "x": 20, "y": 5, "width": 2.5, "room_ids": ["large", "small"]}]
        candidate = self.candidate(request)
        doors = [o for o in candidate["openings"] if o.get("source_id") == "shared-door"]
        self.assertEqual(len(doors), 2)
        self.assertAlmostEqual(abs(doors[0]["x"] - doors[1]["x"]), 3, places=4)
        self.assertTrue(all(o["moved"] for o in doors))

    def test_existing_entrance_requires_explicit_replacement(self):
        request = minimal_request()
        request["openings"] = [{"id": "entry", "kind": "door", "orientation": "h", "x": 10, "y": 0, "width": 2.5, "entrance": True, "room_ids": ["large"]}]
        self.assertFalse(generate_circulation(request)["candidates"])
        request["entry"]["replace_existing"] = True
        candidate = self.candidate(request)
        entrance = next(o for o in candidate["openings"] if o.get("entrance"))
        self.assertTrue(entrance["moved"])
        self.assertEqual(entrance["room_ids"], [])

    def test_existing_narrow_room_access_is_reconciled_without_duplicate_door(self):
        request = minimal_request()
        request["door_width"] = 2.8
        request["openings"] = [{"id": "old-door", "kind": "door", "orientation": "v", "x": 20, "y": 5, "width": 2.5, "room_ids": ["large", "small"]}]
        candidate = self.candidate(request)
        self.assertEqual(len(candidate["openings"]), 2)
        self.assertTrue(all(o.get("resized") and o["width"] == 2.8 for o in candidate["openings"]))
        self.assertTrue(validate_circulation({"request": request, "candidate": candidate})["valid"])

    def test_metres_scale_once_and_preserve_ids(self):
        request = minimal_request()
        ft_candidate = self.candidate(request)
        factor = 0.3048
        request["units"] = "m"
        request["width"] *= factor
        request["entry"]["point"] = [v * factor for v in request["entry"]["point"]]
        request["boundary"] = [[v * factor for v in p] for p in request["boundary"]]
        for room in request["rooms"]:
            room["polygon"] = [[v * factor for v in p] for p in room["polygon"]]
            room["min_width"] *= factor
            room["min_height"] *= factor
            room["min_area"] *= factor * factor
        candidate = self.candidate(request)
        self.assertAlmostEqual(candidate["metrics"]["area"], ft_candidate["metrics"]["area"] * factor * factor, places=4)
        self.assertEqual([r["id"] for r in candidate["adjusted_rooms"]], ["large", "small"])

    def test_immutable_deterministic_reload_and_dedup(self):
        request = minimal_request()
        original = deepcopy(request)
        first = generate_circulation(request)
        self.assertEqual(request, original)
        self.assertEqual(first, generate_circulation(request))
        self.assertEqual(len(first["candidates"]), 1)
        self.assertEqual(first["search"]["deduplicated"], 1)
        reloaded = json.loads(json.dumps(first["candidates"][0]))
        self.assertTrue(validate_circulation({"request": request, "candidate": reloaded})["valid"])
        request["source_fingerprint"] = "later-edit"
        self.assertFalse(validate_circulation({"request": request, "candidate": reloaded})["valid"])

    def test_invalid_json_types_limits_and_nonfinite(self):
        for key, value in (("width", True), ("width", float("nan")), ("candidate_limit", 99), ("units", "cm"), ("rooms", [])):
            request = minimal_request()
            request[key] = value
            with self.assertRaises(CirculationError):
                generate_circulation(request)

    def test_top_edge_regression_without_loading_gui(self):
        legacy = Path(__file__).parents[2] / "circulation.py"
        tree = ast.parse(legacy.read_text())
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "calculate_edge_move")
        source = ast.unparse(method)
        self.assertIn("min(room_obj.rel_push_T,", source)
        top_assignments = [node for node in ast.walk(method) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == "rel_push_T" for target in node.targets)]
        self.assertTrue(top_assignments)
        self.assertTrue(all("rel_push_L" not in ast.unparse(node.value) for node in top_assignments))

    def test_no_gui_or_native_library_dependency(self):
        self.assertNotIn("tkinter", sys.modules)
        self.assertNotIn("matplotlib.pyplot", sys.modules)
        self.assertFalse(get_capabilities()["geometry"]["corridors_have_walls"])


if __name__ == "__main__":
    unittest.main()
