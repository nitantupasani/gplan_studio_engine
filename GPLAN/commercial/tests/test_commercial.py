"""Run: python -m unittest GPLAN.commercial.tests.test_commercial -v."""

from copy import deepcopy
import math
import time
import unittest
from unittest.mock import patch

from GPLAN.commercial import BriefError, generate_commercial_options, normalize_brief, validate_commercial_option
from GPLAN.commercial.egress import capacity_loads
from GPLAN.commercial.generation import pack_candidate
from GPLAN.commercial.models import fingerprint
from GPLAN.commercial.program import compile_program, occupancy_scenarios, requirement
from GPLAN.commercial.rules_nl import accessibility_sector_trigger, exit_requirement, office_distance_limit, single_route_protection
from GPLAN.commercial.templates import fit_template


def default_brief():
    return {"site": {"width_m": 20, "depth_m": 30}, "people": {"staff": 36, "visitors": 4, "desks": 36},
            "building": {"floor_strategy": "auto", "max_floors": 3},
            "rooms": [{"id": "meeting", "role": "meeting", "capacity": 8, "count": 2},
                      {"id": "reception", "role": "reception", "capacity": 0, "min_area_m2": 10},
                      {"id": "storage", "role": "storage", "capacity": 0, "min_area_m2": 6}],
            "amenities": {"lunch_seats": 16}}


class RulesAndProgramme(unittest.TestCase):
    def test_density_is_strict_and_office_never_60(self):
        self.assertEqual(office_distance_limit(10, 120, True), 30)
        self.assertEqual(office_distance_limit(10, 120.001, True), 45)
        self.assertEqual(office_distance_limit(1, 10000, True), 45)
        self.assertEqual(office_distance_limit(1, 10000), 30)

    def test_separate_population_triggers(self):
        self.assertEqual(exit_requirement(150)["minimum_exits"], 1)
        self.assertEqual(exit_requirement(151)["minimum_exits"], 2)
        self.assertEqual(exit_requirement(151)["minimum_separation_m"], 5)
        self.assertFalse(exit_requirement(37)["outward_swing_required"])
        self.assertTrue(exit_requirement(38)["outward_swing_required"])
        self.assertFalse(exit_requirement(100)["panic_hardware_required"])
        self.assertTrue(exit_requirement(101)["panic_hardware_required"])
        self.assertEqual(single_route_protection(37, 8), "protected")
        self.assertEqual(single_route_protection(37, 8.001), "extra_protected")
        self.assertEqual(single_route_protection(151, 3.3), "safety_route")

    def test_accessibility_aggregates_floors(self):
        self.assertFalse(accessibility_sector_trigger([200, 200]))
        self.assertTrue(accessibility_sector_trigger([200, 200.01]))

    def test_seats_do_not_double_count_staff(self):
        brief = normalize_brief(default_brief())
        scenarios = occupancy_scenarios(brief, compile_program(brief))
        self.assertEqual({s["total_people"] for s in scenarios}, {40})
        self.assertTrue(all(sum(s["distribution"].values()) == 40 for s in scenarios))
        self.assertEqual(scenarios[1]["distribution"]["meeting"], 16)

    def test_room_names_do_not_select_rulebook(self):
        brief = default_brief()
        brief["rooms"][0]["name"] = "Bedroom kitchen study"
        rooms = compile_program(normalize_brief(brief))
        meeting = [r for r in rooms if r["requirement_id"] == "meeting"]
        self.assertEqual([r["use_function"] for r in meeting], ["bijeenkomstfunctie"] * 2)
        self.assertEqual(sum(r["required_capacity"] for r in meeting), 16)

    def test_accessible_wc_area_is_not_enough(self):
        self.assertIsNone(fit_template(requirement("wc", "accessible_wc", 1, min_area_m2=20), 2.9))
        self.assertIsNotNone(fit_template(requirement("wc", "accessible_wc", 1), 3.0))

    def test_invalid_numbers_and_duplicate_ids(self):
        for value in (True, float("nan"), float("inf"), "20"):
            with self.subTest(value=value):
                brief = default_brief()
                brief["site"]["width_m"] = value
                with self.assertRaises(BriefError):
                    normalize_brief(brief)
        brief = default_brief()
        brief["rooms"][1]["id"] = "meeting"
        with self.assertRaises(BriefError):
            normalize_brief(brief)

    def test_ui_alias_edits_override_previously_derived_values(self):
        brief = normalize_brief(default_brief())
        brief["building"]["client_rooms_ground"] = False
        brief["building"]["allowed_height_m"] = 20
        brief["site"]["max_height_m"] = 7
        edited = normalize_brief(brief)
        self.assertFalse(edited["building"]["client_rooms_ground_floor"])
        self.assertEqual(edited["building"]["allowed_height_m"], 7)

    def test_no_residential_fallback_for_public_cafe(self):
        brief = default_brief()
        brief["amenities"]["public_cafe"] = True
        self.assertEqual(generate_commercial_options(brief)["status"], "unsupported_geometry")

    def test_ordinary_wcs_are_not_replaced_by_accessible_fixture(self):
        brief = default_brief()
        brief["amenities"].update(wc_policy="specified", wc_count=3, accessible_wc=True)
        rooms = compile_program(normalize_brief(brief), 2)
        self.assertGreaterEqual(sum(r["capacity"] for r in rooms if r["role"] == "wc"), 3)
        self.assertEqual(sum(r["capacity"] for r in rooms if r["role"] == "accessible_wc"), 2)

    def test_wide_meeting_room_rotates_real_furniture_to_use_available_width(self):
        requested = requirement("meeting", "meeting", 18)
        narrow = fit_template(requested, 6.0)
        wide = fit_template(requested, 8.9)
        self.assertLess(wide["depth"], narrow["depth"])
        self.assertEqual(sum(f["kind"] == "meeting_chair" for f in wide["furniture"]), 18)
        self.assertTrue(all(f["rect"]["width"] >= .55 for f in wide["furniture"] if f["kind"] == "meeting_chair"))
        self.assertTrue(any(a["y"] >= 3.6 and a["height"] >= 1.2 for a in wide["aisles"]))

    def test_derived_wc_blocks_group_fixtures_without_reducing_provision(self):
        brief = default_brief()
        brief["amenities"].update(wc_policy="specified", wc_count=6)
        rooms = compile_program(normalize_brief(brief), 1)
        ordinary = [r for r in rooms if r["role"] == "wc"]
        self.assertEqual(len(ordinary), 1)
        self.assertEqual(ordinary[0]["required_capacity"], 6)
        template = fit_template(ordinary[0], 8.9)
        self.assertEqual(sum(f["kind"] == "wc_fixture" for f in template["furniture"]), 6)
        self.assertEqual(sum(f["kind"] == "handwash" for f in template["furniture"]), 6)

    def test_bounded_attempts_do_not_starve_later_authorised_floor_counts(self):
        counts = []
        def miss(brief, floor_count, *args, **kwargs):
            counts.append(floor_count)
            return None, {"code": "test_no_topology"}
        with patch("GPLAN.commercial.service.pack_candidate", side_effect=miss):
            result = generate_commercial_options(default_brief())
        self.assertEqual(result["search"]["floor_counts_examined"], [1, 2, 3])
        self.assertEqual([counts.count(n) for n in (1, 2, 3)], [16, 16, 16])

    def test_151_people_cannot_pass_single_exit_source(self):
        brief = default_brief()
        brief["people"].update(staff=151, desks=151, visitors=0)
        result = generate_commercial_options(brief)
        self.assertFalse(result["candidates"])
        self.assertEqual(result["search"]["stopped_by"], "candidate_source_scope")

    def test_single_floor_with_reception_waiting_seats(self):
        brief = {"site": {"width_m": 14, "depth_m": 18}, "people": {"staff": 4, "visitors": 2},
                 "rooms": [{"id": "welcome", "role": "reception", "capacity": 2}], "amenities": {"lunch_seats": 4}}
        result = generate_commercial_options(brief)
        self.assertTrue(result["candidates"], result["diagnostics"])
        room = next(r for r in result["candidates"][0]["floors"][0]["rooms"] if r["role"] == "reception")
        self.assertEqual(sum(f["kind"] == "reception_chair" for f in room["furniture"]), 2)

    def test_sixty_staff_twenty_visitors_have_real_multifloor_option(self):
        brief = default_brief()
        brief["people"].update(staff=60, desks=60, visitors=20)
        brief["building"]["max_floors"] = 4
        result = generate_commercial_options(brief)
        self.assertTrue(result["candidates"], result["diagnostics"])
        self.assertEqual(result["candidates"][0]["capacity"]["desks"], 60)

    def test_exact_four_floors_remains_authorised(self):
        brief = default_brief()
        brief["building"].update(floor_strategy="exact", floor_count=4)
        result = generate_commercial_options(brief)
        self.assertTrue(result["candidates"], result["diagnostics"])
        self.assertEqual(len(result["candidates"][0]["floors"]), 4)

    def test_hard_area_bound_is_distinct_from_search_miss(self):
        brief = default_brief()
        brief["rooms"][0]["min_area_m2"] = 9000
        self.assertEqual(generate_commercial_options(brief)["status"], "infeasible_proven_by_bound")
        narrow = {"site": {"width_m": 5, "depth_m": 100}, "people": {"staff": 8}, "building": {"floor_strategy": "exact", "floor_count": 2}}
        self.assertEqual(generate_commercial_options(narrow)["status"], "no_feasible_candidate_found_within_budget")

    def test_cancellation_and_timeout_are_not_infeasibility(self):
        self.assertEqual(generate_commercial_options(default_brief(), cancelled=lambda: True)["status"], "cancelled")
        result = generate_commercial_options(default_brief(), deadline=time.monotonic() - 1)
        self.assertEqual(result["status"], "no_feasible_candidate_found_within_budget")
        self.assertEqual(result["search"]["stopped_by"], "deadline")


class WholeBuildingMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brief = normalize_brief(default_brief())
        cls.result = generate_commercial_options(cls.brief)
        if not cls.result["candidates"]:
            raise AssertionError(str(cls.result["diagnostics"]))
        cls.option = cls.result["candidates"][0]

    def assertInvalid(self, mutation):
        option = deepcopy(self.option)
        mutation(option)
        result = validate_commercial_option(option, self.brief)
        self.assertFalse(result["valid"], result)
        return [c for c in result["assessments"] if c["status"] == "failed"]

    def test_real_default_preserves_capacity_and_ledger(self):
        self.assertEqual(self.result["status"], "review_required")
        self.assertIn(len(self.option["floors"]), [2, 3])
        self.assertEqual(self.option["capacity"]["desks"], 36)
        self.assertEqual(self.option["capacity"]["meeting_seats"], 16)
        self.assertEqual(self.option["capacity"]["lunch_seats"], 16)
        self.assertTrue(validate_commercial_option(self.option, self.brief)["valid"])
        ledger = self.option["area_ledger"]
        self.assertAlmostEqual(ledger["gross_m2"], sum(v for k, v in ledger.items() if k != "gross_m2"), places=4)
        self.assertTrue(all(r["contribution_m2"] == 0 for f in self.option["floors"] for r in f["rooms"]))
        self.assertTrue(any(c["status"] == "not_assessed" and c["category"] == "escape" for c in self.option["assessments"]))

    def test_remove_desk_rejected_even_if_metadata_preserved(self):
        def mutation(option):
            room = next(r for f in option["floors"] for r in f["rooms"] if r["role"] == "open_office")
            desk = next(f for f in room["furniture"] if f["kind"] == "desk")
            room["furniture"].remove(desk)
        self.assertInvalid(mutation)

    def test_shrink_furniture_to_epsilon_rejected(self):
        def mutation(option):
            desk = next(f for floor in option["floors"] for r in floor["rooms"] for f in r["furniture"] if f["kind"] == "desk")
            desk["rect"]["width"] = .001
        self.assertInvalid(mutation)

    def test_desk_without_its_chair_is_not_furnished_capacity(self):
        def mutation(option):
            room = next(r for f in option["floors"] for r in f["rooms"] if r["role"] == "open_office")
            room["furniture"].remove(next(f for f in room["furniture"] if f["kind"] == "chair"))
        self.assertInvalid(mutation)

    def test_stair_and_lift_only_rejected(self):
        self.assertInvalid(lambda o: o["floors"][1].update(cores=[c for c in o["floors"][1]["cores"] if c["kind"] != "stair"]))

    def test_missing_stair_portal_rejected(self):
        self.assertInvalid(lambda o: o["floors"][1].update(doors=[d for d in o["floors"][1]["doors"] if d["from"] != "f1:stair"]))

    def test_misaligned_stair_stack_rejected(self):
        def mutation(option):
            next(c for c in option["floors"][1]["cores"] if c["kind"] == "stair")["rect"]["x"] += .2
        self.assertInvalid(mutation)

    def test_faked_stair_width_rejected(self):
        def mutation(option):
            next(c for c in option["floors"][1]["cores"] if c["kind"] == "stair")["flight_width_m"] = 3.0
        self.assertInvalid(mutation)

    def test_faked_aisle_width_rejected(self):
        def mutation(option):
            room = next(r for f in option["floors"] for r in f["rooms"] if r["role"] == "open_office")
            room["aisles"][0]["rect"]["height"] = .1
        self.assertInvalid(mutation)

    def test_missing_exterior_exit_rejected(self):
        self.assertInvalid(lambda o: o["floors"][0].update(exits=[]))

    def test_outside_envelope_rejected(self):
        self.assertInvalid(lambda o: o["floors"][0]["rooms"][0]["rect"].update(x=-1))

    def test_stale_programme_rejected(self):
        brief = deepcopy(self.brief)
        brief["people"]["desks"] += 1
        self.assertFalse(validate_commercial_option(self.option, brief)["valid"])

    def test_cumulative_lower_stair_load(self):
        floors = [{"rooms": [{"role": "open_office", "capacity": cap}]} for cap in (10, 20, 30, 40)]
        brief = normalize_brief({"site": {"width_m": 20, "depth_m": 30}, "people": {"staff": 80}})
        loads = capacity_loads(brief, floors)
        self.assertEqual(loads["stair_loads"], {1: 80, 2: 70, 3: 40})

    def test_south_exit_matches_svg_cardinal(self):
        self.assertGreater(self.option["floors"][0]["exits"][0]["point"][1], 29.7)

    def test_own_strip_position_lock_preserves_exact_rectangle(self):
        room = next(r for f in self.option["floors"] for r in f["rooms"] if r["requirement_id"] == "storage")
        brief = deepcopy(self.brief)
        source = next(r for r in brief["rooms"] if r["id"] == "storage")
        source.update(locked=True, locked_geometry={"floor_index": room["floor_index"], "rect": deepcopy(room["rect"])})
        result = generate_commercial_options(brief)
        self.assertTrue(result["candidates"], result["diagnostics"])
        locked = next(r for f in result["candidates"][0]["floors"] for r in f["rooms"] if r["requirement_id"] == "storage")
        self.assertEqual(locked["rect"], room["rect"])
        self.assertEqual(locked["floor_index"], room["floor_index"])

    def test_fake_route_axis_rejected(self):
        self.assertInvalid(lambda o: o["floors"][1].update(corridor_axis=[[0, 0], [0, 30]]))

    def test_core_side_mirrors_complete_usable_stack(self):
        brief = deepcopy(self.brief)
        brief["building"]["core_side"] = "right"
        result = generate_commercial_options(brief)
        self.assertTrue(result["candidates"], result["diagnostics"])
        option = result["candidates"][0]
        self.assertTrue(validate_commercial_option(option, brief)["valid"])
        left = next(c for c in self.option["floors"][0]["cores"] if c["kind"] == "stair")
        right = next(c for c in option["floors"][0]["cores"] if c["kind"] == "stair")
        self.assertGreater(right["rect"]["x"], left["rect"]["x"])

    def test_central_core_preserves_routes_and_discharge(self):
        # General ranking may prefer an entrance core after furniture packing
        # improves. Exercise an explicitly central, genuinely accepted stack.
        option, deficit = pack_candidate(self.brief, 3, .5, 1, True, core_position="central")
        self.assertIsNotNone(option, deficit)
        self.assertEqual(option["core_configuration"]["longitudinal_position"], "central")
        self.assertEqual(len(option["floors"]), 3)
        stair = next(c for c in option["floors"][0]["cores"] if c["kind"] == "stair")
        self.assertGreater(stair["rect"]["y"], 5)
        self.assertLess(stair["rect"]["y"] + stair["rect"]["height"], 25)
        checks = validate_commercial_option(option, self.brief)
        self.assertTrue(checks["valid"])
        self.assertTrue(any(c["id"] == "ground-exit-connection" and c["status"] == "passed" for c in checks["assessments"]))


if __name__ == "__main__":
    unittest.main()
