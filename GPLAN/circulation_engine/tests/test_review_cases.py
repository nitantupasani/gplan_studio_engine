"""Independent adversarial acceptance checks from the circulation research review.

These tests exercise public generation/validation and independently reconstruct
geometry or enumerate graph optima; they do not mirror the production solver.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import networkx as nx
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from GPLAN.circulation_engine import CirculationError, generate_circulation, validate_circulation
from GPLAN.circulation_engine.algorithms import WallGroup, route
from GPLAN.circulation_engine.models import parse_request, ring
from GPLAN.circulation_engine.validation import validate_candidate


def room(rid, bounds, scale=1):
    return {"id": rid, "name": rid, "polygon": ring(box(*(v * scale for v in bounds))),
            "min_width": 4 * scale, "min_height": 4 * scale, "min_area": 16 * scale * scale,
            "max_aspect": 4}


def pair_payload(scale=1, units="ft", with_window=False):
    payload = {"schema_version": "1.0", "plan_id": "review-plan", "source_fingerprint": "review-original",
               "units": units, "boundary": ring(box(0, 0, 40 * scale, 20 * scale)),
               "rooms": [room("large", (0, 0, 20, 20), scale), room("small", (20, 0, 30, 20), scale)],
               "entry": {"point": [20 * scale, 0]}, "width": 3 * scale, "door_width": 2.5 * scale,
               "required_room_ids": ["large", "small"], "modes": ["spanning", "compact"],
               "contribution_policy": "area"}
    if with_window:
        payload["openings"] = [{"id": "west-window", "kind": "window", "orientation": "v", "x": 0,
                                "y": 10 * scale, "width": 3 * scale, "room_ids": ["large"]}]
    return payload


def grid_payload():
    payload = pair_payload()
    payload.update(boundary=ring(box(0, 0, 20, 20)), entry={"point": [0, 10]},
                   rooms=[room("nw", (0, 0, 10, 10)), room("ne", (10, 0, 20, 10)),
                          room("sw", (0, 10, 10, 20)), room("se", (10, 10, 20, 20))],
                   required_room_ids=["nw", "ne", "sw", "se"])
    return payload


class IndependentReviewTests(unittest.TestCase):
    def candidate(self, payload):
        result = generate_circulation(payload)
        self.assertTrue(result.get("candidates"), result)
        return result["candidates"][0]

    def assert_rejected(self, payload, candidate):
        try:
            result = validate_circulation({"request": payload, "candidate": candidate})
        except CirculationError:
            return
        self.assertFalse(result.get("valid"), result)

    def test_surface_is_exact_room_loss_and_does_not_absorb_open_space(self):
        payload = pair_payload()
        candidate = self.candidate(payload)
        originals = unary_union([Polygon(r["polygon"]) for r in payload["rooms"]])
        adjusted = unary_union([Polygon(r["polygon"]) for r in candidate["adjusted_rooms"]])
        surface = unary_union([Polygon(r["polygon"], r.get("holes", [])) for r in candidate["corridors"]])
        self.assertLess(surface.symmetric_difference(originals.difference(adjusted)).area, 1e-6)
        self.assertAlmostEqual(surface.area, 60, places=5)
        self.assertAlmostEqual(Polygon(payload["boundary"]).difference(adjusted).area - surface.area, 200, places=5)
        self.assertTrue(all(s.get("wall_free") is True and not s.get("walls") for s in candidate["corridors"]))

    def test_larger_room_preference_and_protected_room_zero_area(self):
        payload = pair_payload()
        candidate = self.candidate(payload)
        lost = {item["room_id"]: item["area_taken"] for item in candidate["contributions"]}
        self.assertAlmostEqual(lost["large"], 40, places=3)
        self.assertAlmostEqual(lost["small"], 20, places=3)
        for policy in ("area", "surplus", "equal", "protected"):
            with self.subTest(policy=policy):
                protected = deepcopy(payload)
                protected["contribution_policy"] = policy
                protected["rooms"][1]["protected"] = True
                generated = self.candidate(protected)
                change = next(item for item in generated["contributions"] if item["room_id"] == "small")
                self.assertAlmostEqual(change["area_taken"], 0, places=6)

    def test_actual_aspect_caps_override_area_preference(self):
        payload = pair_payload()
        payload["rooms"][0]["max_aspect"] = 1.05
        generated = self.candidate(payload)
        large = Polygon(next(r["polygon"] for r in generated["adjusted_rooms"] if r["id"] == "large"))
        w, h = large.bounds[2] - large.bounds[0], large.bounds[3] - large.bounds[1]
        self.assertLessEqual(max(w / h, h / w), 1.05 + 1e-6)
        self.assertTrue(validate_circulation({"request": payload, "candidate": generated})["valid"])

    def test_unit_scaling_has_equivalent_geometry_and_quadratic_area(self):
        feet = self.candidate(pair_payload())
        metres = self.candidate(pair_payload(0.3048, "m"))
        self.assertAlmostEqual(metres["metrics"]["area"], feet["metrics"]["area"] * 0.3048 ** 2, places=5)
        feet_rooms = {r["id"]: Polygon(r["polygon"]).bounds for r in feet["adjusted_rooms"]}
        for r in metres["adjusted_rooms"]:
            for actual, original in zip(Polygon(r["polygon"]).bounds, feet_rooms[r["id"]]):
                self.assertAlmostEqual(actual, original * 0.3048, places=4)

    def test_full_side_t_partition_can_derive_one_corridor(self):
        payload = pair_payload()
        payload["rooms"] = [room("left", (0, 0, 20, 20)), room("top", (20, 0, 30, 10)), room("bottom", (20, 10, 30, 20))]
        payload["required_room_ids"] = ["left", "top", "bottom"]
        generated = self.candidate(payload)
        self.assertEqual(generated["coverage"]["count"], 3)
        self.assertTrue(validate_circulation({"request": payload, "candidate": generated})["valid"])

    def test_disappearing_thin_branch_with_doorways_is_rejected(self):
        payload = grid_payload()
        candidate = self.candidate(payload)
        # A 3-ft horizontal trunk plus a 1-ft upper dead branch. The branch's
        # door contacts are 2.5 ft long but its circulation clearance is only 1 ft.
        bounds = {"nw": (0, 0, 9.5, 8.5), "ne": (10.5, 0, 20, 8.5),
                  "sw": (0, 11.5, 10, 20), "se": (10, 11.5, 20, 20)}
        adjusted = {rid: box(*coords) for rid, coords in bounds.items()}
        surface = box(0, 0, 20, 20).difference(unary_union(list(adjusted.values())))
        self.assertEqual(surface.geom_type, "Polygon")
        self.assertEqual(surface.buffer(-1.49999, join_style=2).geom_type, "Polygon")
        candidate["adjusted_rooms"] = [{"id": rid, "polygon": ring(shape)} for rid, shape in adjusted.items()]
        candidate["corridors"][0].update(polygon=ring(surface), holes=[])
        candidate["metrics"].update(area=surface.area, total_room_area_taken=surface.area)
        for item in candidate["contributions"]:
            item["area_taken"] = 100 - adjusted[item["room_id"]].area
        candidate["openings"] = [
            {"id": "narrow-nw", "kind": "door", "orientation": "v", "x": 9.5, "y": 4, "width": 2.5, "room_ids": ["nw"]},
            {"id": "narrow-ne", "kind": "door", "orientation": "v", "x": 10.5, "y": 4, "width": 2.5, "room_ids": ["ne"]},
            {"id": "wide-sw", "kind": "door", "orientation": "h", "x": 5, "y": 11.5, "width": 2.5, "room_ids": ["sw"]},
            {"id": "wide-se", "kind": "door", "orientation": "h", "x": 15, "y": 11.5, "width": 2.5, "room_ids": ["se"]},
        ]
        check = validate_candidate(parse_request(payload), candidate)
        self.assertFalse(check["checks"]["finite_width"], check)
        self.assert_rejected(payload, candidate)

    def test_opening_semantics_and_metadata_cannot_be_forged(self):
        payload = pair_payload(with_window=True)
        candidate = self.candidate(payload)
        edits = {
            "window_kind": lambda c: next(o for o in c["openings"] if o["id"] == "west-window").update(kind="door"),
            "window_width": lambda c: next(o for o in c["openings"] if o["id"] == "west-window").update(width=1),
            "window_position": lambda c: next(o for o in c["openings"] if o["id"] == "west-window").update(y=4),
            "source_fingerprint": lambda c: c.update(source_fingerprint="stale-plan"),
            "request_fingerprint": lambda c: c.update(request_fingerprint="other-request"),
            "surface_provenance": lambda c: c["corridors"][0].update(provenance=[]),
            "metric_length": lambda c: c["metrics"].update(length=c["metrics"].get("length", 0) + 100),
            "centerline_width": lambda c: c["centerlines"][0].update(width=99),
            "centerline_position": lambda c: c["centerlines"][0]["points"][0].__setitem__(0, 999),
            "algorithm": lambda c: c.update(algorithm={"id": "unimplemented-global-shortest", "version": "999"}),
        }
        for name, edit in edits.items():
            with self.subTest(tamper=name):
                changed = deepcopy(candidate)
                edit(changed)
                self.assert_rejected(payload, changed)

    def test_malformed_request_rejected_with_domain_error(self):
        cases = [
            lambda p: p.update(width=True), lambda p: p.update(width=float("nan")),
            lambda p: p.update(units="cm"), lambda p: p.update(modes=[["spanning"]]),
            lambda p: p["rooms"][0].update(locked="false"),
            lambda p: p.update(openings=[{"id": "bad-owner", "kind": "door", "orientation": "v", "x": 20, "y": 5, "width": 2.5, "room_ids": [[]]}]),
            lambda p: p.update(required_room_ids=[{}]),
        ]
        for index, change in enumerate(cases):
            with self.subTest(case=index):
                payload = pair_payload()
                change(payload)
                with self.assertRaises(CirculationError):
                    parse_request(payload)

    def test_malformed_candidate_returns_validation_failure_or_domain_error(self):
        payload = pair_payload()
        candidate = self.candidate(payload)
        edits = [lambda c: c.update(coverage=[]), lambda c: c.update(metrics=[]),
                 lambda c: c["openings"][0].update(room_ids=[[]]),
                 lambda c: c["openings"][0].update(entrance="false")]
        for index, edit in enumerate(edits):
            with self.subTest(case=index):
                changed = deepcopy(candidate)
                edit(changed)
                self.assert_rejected(payload, changed)

    def test_shortest_node_weight_route_matches_exhaustive_small_optimum(self):
        # Compare against all simple paths, independent of Dijkstra's implementation.
        for seed in range(12):
            graph = nx.gnp_random_graph(6, 0.55, seed=seed)
            graph.add_edges_from([(i, i + 1) for i in range(5)])
            lengths = {node: 1 + ((node * 7 + seed * 3) % 11) for node in graph}
            groups = {str(n): WallGroup(str(n), "v", n, 0, lengths[n], (f"r{n}",), ("destination",) if n == 5 else (), True) for n in graph}
            adjacency = {str(n): {str(other) for other in graph.neighbors(n)} for n in graph}
            selected = route(SimpleNamespace(required=("destination",)), "shortest", groups, adjacency, "0")
            optimum = min(sum(lengths[n] for n in path) for path in nx.all_simple_paths(graph, 0, 5))
            self.assertEqual(sum(groups[n].length for n in selected), optimum)


if __name__ == "__main__":
    unittest.main()
