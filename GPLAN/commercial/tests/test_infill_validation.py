"""Independent supplementary fit-out and branch-route regression checks."""
from copy import deepcopy
import unittest

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from GPLAN.commercial import generate_commercial_options, normalize_brief, validate_commercial_option
from GPLAN.commercial.adjustments import constraint_deviations
from GPLAN.commercial.egress import assess_egress, capacity_loads, circulation_route, route_samples, shape
from GPLAN.commercial.generation import portal
from GPLAN.commercial.models import polygon, rect
from GPLAN.commercial.tests.test_commercial import default_brief


class SupplementaryRoutes(unittest.TestCase):
    def test_cross_aisle_path_goes_around_the_core(self):
        corridors = [dict(id="spine", rect=rect(8, 0, 1.5, 12)), dict(id="branch", rect=rect(0, 6, 8, 1.2))]
        doors = [portal("pocket-door", [2, 6], .95, "pocket", "branch", horizontal=True),
                 portal("stair-door", [8, 3], .95, "stair", "spine")]
        floor = {"corridors": corridors, "doors": doors, "exits": []}
        route = circulation_route(floor, [2, 6], [8, 3])
        self.assertIsNotNone(route)
        surface = unary_union([shape(c["rect"]) for c in corridors] + [Polygon(d["portal_polygon"]) for d in doors])
        self.assertTrue(surface.buffer(1e-6).covers(LineString(route)))
        self.assertEqual(LineString(route).intersection(shape(rect(3, 0, 5, 5.88))).length, 0)
        self.assertGreater(LineString(route).length, 8, "the branch cannot teleport diagonally through the core")

    def test_disconnected_branch_never_gets_a_drawn_route(self):
        floor = {"corridors": [dict(id="spine", rect=rect(8, 0, 1.5, 12)), dict(id="branch", rect=rect(0, 6, 7, 1.2))],
                 "doors": [portal("pocket-door", [2, 6], .95, "pocket", "branch", horizontal=True),
                           portal("stair-door", [8, 3], .95, "stair", "spine")], "exits": []}
        self.assertIsNone(circulation_route(floor, [2, 6], [8, 3]))

    def test_zero_capacity_support_still_has_a_measured_route_review(self):
        room = {"id": "support", "role": "storage", "capacity": 0, "supplementary": True,
                "rect": rect(0, 0, 2, 3), "furniture": []}
        door = portal("support-door", [2, 1], .95, "support", "corridor")
        exit = portal("exit", [2.75, 40], .95, "corridor", "outside", horizontal=True)
        exit["external_path"] = [[2.75, 40], [2.75, 42]]
        floor = {"index": 0, "rooms": [room], "cores": [], "corridor_axis": [[2.75, 0], [2.75, 40]],
                 "corridors": [{"id": "corridor", "rect": rect(2, 0, 1.5, 40), "width_m": 1.5}], "doors": [door], "exits": [exit]}
        brief = normalize_brief({"site": {"width_m": 10, "depth_m": 45}, "people": {"staff": 2}})
        checks = assess_egress(brief, {"floors": [floor]})
        route = next(check for check in checks if check["id"] == "support:operational-route")
        self.assertEqual(route["status"], "needs_input")
        self.assertGreater(route["measured"], 30)
        self.assertIn("route redesign required", route["title"])
        self.assertIn("no accepted capacity credit", route["detail"])
        room["furniture"] = [{"kind": "storage_cabinet", "rect": rect(0, 0, 2, 3)}]
        blocked = assess_egress(brief, {"floors": [floor]})
        self.assertEqual(next(c for c in blocked if c["id"] == "support:operational-route")["status"], "failed")

    def test_supplementary_desks_cannot_hide_original_deviation(self):
        original = normalize_brief({"site": {"width_m": 20, "depth_m": 30}, "people": {"staff": 120, "desks": 120}})
        fitted = deepcopy(original)
        fitted["people"]["desks"] = 30
        rooms = [{"requirement_id": "derived:work-1", "role": "open_office", "furniture": [{"kind": "desk"}] * 30},
                 {"requirement_id": "derived:support:quiet_work", "role": "focus", "supplementary": True,
                  "fitout_status": "usable", "furniture": [{"kind": "desk"}] * 2}]
        deviations = constraint_deviations(original, fitted, {"floors": [{"rooms": rooms}]})
        self.assertEqual(next(d for d in deviations if d["path"] == "people.desks")["provided"], 30)

    def test_fast_branch_upper_bound_cannot_fail_a_shorter_valid_route(self):
        # A door at the end of the branch admits the orthogonal fast path.
        # A door on its long edge has a portal stub which already forces the
        # visibility graph, so it would not exercise the upper-bound fallback.
        room = {"id": "support", "role": "storage", "capacity": 0, "supplementary": True,
                "rect": rect(0, 12.35, 3, 11.5), "furniture": []}
        door = portal("support-door", [3, 18.1], .95, "support", "branch")
        exit = portal("exit", [8.75, 0], .95, "corridor", "outside", horizontal=True)
        exit["external_path"] = [[8.75, 0], [8.75, -2]]
        floor = {"index": 0, "rooms": [room], "cores": [], "corridor_axis": [[8.75, 0], [8.75, 22]],
                 "corridors": [{"id": "corridor", "rect": rect(8, 0, 1.5, 22), "width_m": 1.5},
                               {"id": "branch", "rect": rect(3, 17.5, 5, 1.2), "width_m": 1.2}],
                 "doors": [door], "exits": [exit]}
        inside = route_samples(room, door)["distance_m"]
        fast = circulation_route(floor, door["point"], exit["point"])
        self.assertGreater(inside + LineString(fast).length, 30)
        brief = normalize_brief({"site": {"width_m": 12, "depth_m": 25}, "people": {"staff": 2}})
        route = next(c for c in assess_egress(brief, {"floors": [floor]}) if c["id"] == "support:operational-route")
        self.assertEqual(route["status"], "passed", route)
        self.assertLess(route["measured"], 30)


class SupplementaryAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brief = normalize_brief(default_brief())
        result = generate_commercial_options(cls.brief)
        cls.option = next((option for option in result["candidates"] if any(
            room.get("supplementary") for floor in option["floors"] for room in floor["rooms"])), None)
        if cls.option is None:
            raise AssertionError("Actual generation must deliver independently checked supplementary spaces: " + str([
                option.get("infill", result["diagnostics"]) for option in result["candidates"]]))

    def extra(self, option):
        return next((floor, room) for floor in option["floors"] for room in floor["rooms"] if room.get("supplementary"))

    def failures(self, option):
        result = validate_commercial_option(option, self.brief)
        self.assertFalse(result["valid"])
        return {check["id"] for check in result["assessments"] if check["status"] == "failed"}

    def test_real_added_fitout_is_checked_without_added_population(self):
        validated = validate_commercial_option(self.option, self.brief)
        self.assertTrue(validated["valid"], [c for c in validated["assessments"] if c["status"] == "failed"])
        self.assertEqual(validated["capacity"]["desks"], self.brief["people"]["desks"])
        self.assertEqual(validated["supplementary_capacity"], self.option["supplementary_capacity"])
        loads = capacity_loads(self.brief, self.option["floors"])
        self.assertEqual(loads["peak"], self.brief["people"]["staff"] + self.brief["people"]["visitors"])
        checked = {check["id"] for check in validated["assessments"]}
        self.assertTrue(all(room["id"] + ":operational-route" in checked for floor in self.option["floors"] for room in floor["rooms"] if room.get("supplementary")))

    def test_unknown_derived_identity_cannot_authorise_a_room(self):
        option = deepcopy(self.option)
        _, room = self.extra(option)
        room["programme_id"] += ":forged"
        self.assertIn(room["id"] + ":programme", self.failures(option))

    def test_supplementary_geometry_cannot_move_into_a_core(self):
        option = deepcopy(self.option)
        floor, room = self.extra(option)
        room["rect"] = deepcopy(floor["cores"][0]["rect"])
        room["clear_polygon"] = polygon(room["rect"])
        failures = self.failures(option)
        self.assertIn(room["id"] + ":supplementary-position", failures)
        self.assertIn(f"f{floor['index']}:nonoverlap", failures)

    def test_missing_support_door_rejects(self):
        option = deepcopy(self.option)
        floor, room = self.extra(option)
        floor["doors"] = [door for door in floor["doors"] if door["from"] != room["id"]]
        self.assertIn(room["id"] + ":supplementary-door-schedule", self.failures(option))

    def test_furniture_cannot_move_into_the_reserved_aisle(self):
        option = deepcopy(self.option)
        _, room = self.extra(option)
        room["furniture"][0]["rect"] = deepcopy(room["aisles"][0]["rect"])
        self.assertIn(room["id"] + ":supplementary-schedule", self.failures(option))

    def test_supplementary_capacity_receipt_is_recomputed(self):
        option = deepcopy(self.option)
        option["supplementary_capacity"]["usable"]["desks"] += 1
        self.assertIn("supplementary-capacity", self.failures(option))

    def test_fitout_route_scope_cannot_be_relabelled(self):
        from GPLAN.commercial.infill import _refresh
        option = deepcopy(self.option)
        _, room = self.extra(option)
        room["fitout_status"] = "route_review" if room["fitout_status"] == "usable" else "usable"
        _refresh(option)
        self.assertIn(room["id"] + ":fitout-status", self.failures(option))

    def test_optional_rooms_never_replace_named_requirements(self):
        option = deepcopy(self.option)
        floor = next(f for f in option["floors"] if any(r["role"] == "meeting" and not r.get("supplementary") for r in f["rooms"]))
        room = next(r for r in floor["rooms"] if r["role"] == "meeting" and not r.get("supplementary"))
        floor["rooms"].remove(room)
        self.assertIn("complete-programme", self.failures(option))

    def test_reserved_area_cannot_hide_core_or_corridor_geometry(self):
        option = deepcopy(self.option)
        floor = option["floors"][0]
        floor.setdefault("reserved_areas", []).append({"id": "forged-reserve", "name": "Resources", "reason": "supporting use",
                                                       "rect": deepcopy(floor["cores"][0]["rect"])})
        self.assertIn("forged-reserve:reserved-area", self.failures(option))

    def test_export_manifest_retains_separate_capacity_and_route_scope(self):
        import json
        from commercial_exports import export_commercial, _entity_label
        payload, mime = export_commercial(self.brief, self.option, {"designId": "support-study", "revision": "4"}, "json")
        self.assertEqual(mime, "application/json")
        manifest = json.loads(payload)
        rooms = [r for floor in self.option["floors"] for r in floor["rooms"] if r.get("supplementary")]
        self.assertEqual({r["id"] for r in manifest["supplementary_spaces"]}, {r["id"] for r in rooms})
        self.assertEqual(manifest["supplementary_capacity"], self.option["supplementary_capacity"])
        self.assertEqual(manifest["brief"]["people"], self.brief["people"])
        self.assertEqual(manifest["option"]["capacity"]["desks"], self.brief["people"]["desks"])
        self.assertIn("adds no declared occupants", manifest["supplementary_scope"])
        for room in rooms:
            row = next(row for row in manifest["supplementary_spaces"] if row["id"] == room["id"])
            self.assertEqual(row["fitout_status"], room["fitout_status"])
        self.assertTrue(_entity_label({"id": "review", "name": "Print room", "supplementary": True,
                                       "fitout_status": "route_review"}).startswith("[ROUTE REVIEW]"))


if __name__ == "__main__":
    unittest.main()
