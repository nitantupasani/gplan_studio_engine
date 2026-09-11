"""Real strict misses, bounded programme alternatives and forged receipts."""

from copy import deepcopy
import time
import unittest

from GPLAN.commercial import generate_commercial_options, normalize_brief, validate_commercial_option
from GPLAN.commercial.adjustments import adjusted_briefs, deviation_cost, restoration_briefs, validate_adjusted_brief
from GPLAN.commercial.models import BriefError, fingerprint
from GPLAN.commercial.tests.test_commercial import default_brief


def meeting_twenty_brief():
    brief = default_brief()
    brief["people"].update(staff=40, visitors=10, desks=40)
    # Reproduces the reported UI task: five ground-floor meetings, not two.
    brief["rooms"][0].update(capacity=20, count=5)
    brief["rooms"][2]["count"] = 2
    brief["amenities"].update(lunch_seats=20, pantry="reheat")
    brief["building"]["allow_programme_adjustments"] = True
    return brief


def large_single_floor_brief():
    return {"site": {"width_m": 20, "depth_m": 25}, "people": {"staff": 120, "desks": 120, "visitors": 0},
            "building": {"floor_strategy": "single", "allow_programme_adjustments": True},
            "amenities": {"lunch_seats": 20}}


class ProgrammeAlternatives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = normalize_brief(meeting_twenty_brief())
        cls.result = generate_commercial_options(cls.original)
        if not cls.result["candidates"]:
            raise AssertionError(str(cls.result["diagnostics"]))
        cls.option = cls.result["candidates"][0]

    def test_reported_five_twenty_seat_meetings_keep_population_and_desks(self):
        self.assertEqual(self.result["status"], "modified_programme")
        self.assertEqual(self.result["brief"], self.original)
        self.assertEqual(self.option["fit_kind"], "modified_programme")
        self.assertFalse(self.option["satisfies_original_brief"])
        self.assertEqual(self.option["fitted_brief"]["people"]["staff"], 40)
        self.assertEqual(self.option["fitted_brief"]["people"]["visitors"], 10)
        self.assertEqual(self.option["capacity"]["desks"], 40)
        self.assertGreaterEqual(self.option["capacity"]["meeting_seats"], 54)
        self.assertGreaterEqual(self.option["capacity"]["lunch_seats"], 18)
        self.assertTrue(any(d.get("requirement_id") == "meeting" for d in self.option["constraint_deviations"]))
        self.assertFalse(any(d["kind"] == "occupancy" for d in self.option["constraint_deviations"]))
        programme_rooms = [r for f in self.option["floors"] for r in f["rooms"] if not r.get("supplementary")]
        meetings = [r for r in programme_rooms if r["role"] == "meeting"]
        self.assertEqual(len(meetings), self.option["fitted_brief"]["rooms"][0]["count"])
        self.assertTrue(all(r["floor_index"] == 0 for r in meetings))
        self.assertEqual(sum(r["role"] == "storage" for r in programme_rooms), 2)
        self.assertLess(self.result["search"]["elapsed_seconds"], 30)
        result = validate_commercial_option(self.option, self.original)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["constraint_deviations"], self.option["constraint_deviations"])

    def test_opt_in_is_required(self):
        brief = deepcopy(self.original)
        brief["building"]["allow_programme_adjustments"] = False
        self.assertFalse(validate_commercial_option(self.option, brief)["valid"])
        result = generate_commercial_options(brief)
        self.assertFalse(result["candidates"])
        self.assertNotEqual(result["status"], "modified_programme")

    def test_receipt_cannot_hide_a_difference(self):
        option = deepcopy(self.option)
        option["constraint_deviations"] = []
        result = validate_commercial_option(option, self.original)
        self.assertFalse(result["valid"])
        self.assertTrue(result["constraint_deviations"])

    def test_false_original_fit_claim_rejected(self):
        option = deepcopy(self.option)
        option["satisfies_original_brief"] = True
        self.assertFalse(validate_commercial_option(option, self.original)["valid"])

    def test_site_accessibility_floor_and_sanitary_changes_rejected(self):
        for group, key, value in [("site", "width_m", 25), ("building", "max_floors", 4),
                                   ("building", "accessibility", "ground_floor"), ("amenities", "accessible_wc", False),
                                   ("amenities", "policy_people_per_wc", 100)]:
            with self.subTest(group=group, key=key):
                option = deepcopy(self.option)
                option["fitted_brief"][group][key] = value
                option["fitted_brief_fingerprint"] = fingerprint(normalize_brief(option["fitted_brief"]))
                self.assertFalse(validate_commercial_option(option, self.original)["valid"])

    def test_geometry_stays_mandatory_for_modified_programme(self):
        option = deepcopy(self.option)
        option["floors"][1]["cores"] = [c for c in option["floors"][1]["cores"] if c["kind"] != "stair"]
        self.assertFalse(validate_commercial_option(option, self.original)["valid"])

    def test_fitted_dimensions_still_need_furniture(self):
        option = deepcopy(self.option)
        room = next(r for f in option["floors"] for r in f["rooms"] if r["role"] == "meeting")
        room["furniture"].remove(next(f for f in room["furniture"] if f["kind"] == "meeting_chair"))
        self.assertFalse(validate_commercial_option(option, self.original)["valid"])

    def test_broad_single_floor_retry_keeps_staff_and_reports_desk_shortage(self):
        brief = large_single_floor_brief()
        result = generate_commercial_options(brief)
        self.assertTrue(result["candidates"], result["diagnostics"])
        self.assertEqual(result["status"], "modified_programme")
        option = result["candidates"][0]
        self.assertEqual(len(option["floors"]), 1)
        self.assertLess(option["capacity"]["desks"], 120)
        self.assertGreaterEqual(option["capacity"]["desks"], 15)
        self.assertEqual(option["fitted_brief"]["people"]["staff"], 120)
        self.assertEqual(option["fitted_brief"]["people"]["visitors"], 0)
        self.assertFalse(any(d["kind"] == "occupancy" for d in option["constraint_deviations"]))
        self.assertTrue(any(d["path"] == "people.desks" for d in option["constraint_deviations"]))
        self.assertTrue(validate_commercial_option(option, brief)["valid"])

    def test_cancellation_during_adjustments_cannot_return_option(self):
        cancelled = {"value": False}
        def progress(event):
            if event["stage"] == "adjusting":
                cancelled["value"] = True
        result = generate_commercial_options(self.original, progress=progress, cancelled=lambda: cancelled["value"])
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(result["candidates"])

    def test_expired_shared_deadline_does_not_start_modified_search(self):
        result = generate_commercial_options(self.original, deadline=time.monotonic() - 1)
        self.assertFalse(result["candidates"])
        self.assertEqual(result["search"]["modified_briefs_examined"], 0)

    def test_automatic_alternatives_cannot_erase_declared_population(self):
        alternatives = adjusted_briefs(self.original, [])
        self.assertTrue(any(b["rooms"][0]["count"] < 5 and b["people"]["desks"] == 40 for b in alternatives))
        for brief in alternatives:
            self.assertEqual((brief["people"]["staff"], brief["people"]["visitors"]), (40, 10))
            self.assertGreaterEqual(brief["people"]["desks"], 4)
            self.assertTrue(all(r["count"] >= 1 for r in brief["rooms"]))
        for key, value in [("staff", 1), ("visitors", 0)]:
            modified = deepcopy(alternatives[0])
            modified["people"][key] = value
            with self.subTest(key=key), self.assertRaises(BriefError):
                validate_adjusted_brief(self.original, modified)

    def test_ranking_values_total_places_before_nominal_room_count(self):
        useful, tiny = deepcopy(self.original), deepcopy(self.original)
        useful["rooms"][0].update(count=3, capacity=18)
        tiny["rooms"][0].update(count=5, capacity=5)
        self.assertLess(deviation_cost(self.original, useful), deviation_cost(self.original, tiny))
        refinements = restoration_briefs(self.original, useful)
        self.assertTrue(refinements)
        self.assertTrue(all(deviation_cost(self.original, b) < deviation_cost(self.original, useful) for b in refinements))

    def test_population_over_source_scope_is_not_reduced_to_bypass_exit_checks(self):
        brief = meeting_twenty_brief()
        brief["people"].update(staff=151, visitors=0, desks=40)
        result = generate_commercial_options(brief)
        self.assertFalse(result["candidates"])
        self.assertEqual(result["search"]["modified_briefs_examined"], 0)
        self.assertEqual(result["search"]["stopped_by"], "candidate_source_scope")


if __name__ == "__main__":
    unittest.main()
