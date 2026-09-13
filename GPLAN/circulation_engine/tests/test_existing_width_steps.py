"""Exact square clearance must preserve short wall steps and reject bottlenecks."""
from copy import deepcopy
import unittest

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from GPLAN.circulation_engine import generate_circulation, validate_circulation
from GPLAN.circulation_engine.existing import _clear_width, width_is_valid
from GPLAN.circulation_engine.tests.test_review_existing import existing_payload


class ExistingWidthStepTests(unittest.TestCase):
    def test_captured_centifeet_widening_step_retains_full_clear_width(self):
        # Actual clear footprint after moving Bedroom 1's west wall +0.01ft.
        # The GEOS mitred-buffer reconstruction introduced diagonal slivers at
        # this short step and incorrectly reported an available width of2ft.
        clear = Polygon([(17.39666666666667, 30.89), (21.013333333333332, 30.89),
                         (21.013333333333332, 21.869999999999997), (21.003333333333334, 21.869999999999997),
                         (21.003333333333334, .72), (17.39666666666667, .72),
                         (17.39666666666667, 17.599999999999998)])
        self.assertTrue(width_is_valid(clear, 3.5))
        self.assertAlmostEqual(_clear_width(clear), 3.606666666666664, places=4)
        self.assertFalse(width_is_valid(clear, 3.62))

    def test_edited_existing_landing_generates_and_revalidates_without_room_changes(self):
        payload = existing_payload()
        # Move only the short bedroom's landing-facing edge0.003048m (0.01ft)
        # into that bedroom; the landing widens and all actual doors follow.
        shifted = 4 - .003048
        landing = next(room for room in payload["rooms"] if room["id"] == "landing")
        landing["polygon"] = [[4, 0], [5.202, 0], [5.202, 9.5], [shifted, 9.5], [shifted, 6.4], [4, 6.4]]
        bedroom = next(room for room in payload["rooms"] if room["id"] == "bed1")
        bedroom["polygon"] = [[0, 6.4], [shifted, 6.4], [shifted, 9.5], [0, 9.5]]
        next(opening for opening in payload["openings"] if opening["id"] == "bed1-door")["x"] = shifted
        before = deepcopy(payload)
        response = generate_circulation(payload)
        self.assertEqual(len(response["candidates"]), 1, response)
        candidate = response["candidates"][0]
        self.assertGreaterEqual(candidate["metrics"]["clear_width"], 1.1 - 1e-6)
        self.assertEqual(candidate["metrics"]["total_room_area_taken"], 0)
        for room in candidate["adjusted_rooms"]:
            original = next(value for value in before["rooms"] if value["id"] == room["id"])
            self.assertTrue(Polygon(room["polygon"]).equals(Polygon(original["polygon"])))
        self.assertTrue(validate_circulation({"request": payload, "candidate": candidate})["valid"])
        self.assertEqual(payload, before)

    def test_true_narrow_neck_and_dead_end_branch_still_fail(self):
        neck = unary_union([box(0, 0, 4, 6), box(1, 6, 3, 8), box(0, 8, 4, 14)])
        self.assertFalse(width_is_valid(neck, 3.5), "A2ft connecting neck cannot serve a3.5ft route")
        branch = unary_union([box(0, 0, 4, 14), box(4, 5, 10, 7)])
        self.assertFalse(width_is_valid(branch, 3.5), "A disappearing2ft branch must remain rejected")
        self.assertTrue(width_is_valid(branch, 2))

    def test_hole_clearance_and_negative_coordinates_remain_geometric(self):
        ring = Polygon([(-10, -10), (10, -10), (10, 10), (-10, 10)],
                       [[(-6, -6), (6, -6), (6, 6), (-6, 6)]])
        self.assertTrue(width_is_valid(ring, 3.5))
        self.assertFalse(width_is_valid(ring, 4.1))


if __name__ == "__main__":
    unittest.main()
