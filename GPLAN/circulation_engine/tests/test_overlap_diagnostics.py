"""Separate floating point edge noise from real overlapping room footprints."""
import math
import unittest

from shapely.geometry import Polygon

from GPLAN.circulation_engine import CirculationError, generate_circulation, validate_circulation
from GPLAN.circulation_engine.models import EPS, parse_request
from GPLAN.circulation_engine.tests.test_review_existing import existing_payload


def payload_in(units):
    payload = existing_payload()
    if units == "m":
        return payload
    factor = 1 / .3048
    payload["units"] = "ft"
    payload["boundary"] = [[x * factor, y * factor] for x, y in payload["boundary"]]
    for room in payload["rooms"]:
        room["polygon"] = [[x * factor, y * factor] for x, y in room["polygon"]]
    for opening in payload["openings"]:
        for field in ("x", "y", "width"):
            opening[field] *= factor
    payload["wall_thickness"] = {key: value * factor for key, value in payload["wall_thickness"].items()}
    payload["width"] *= factor
    payload["door_width"] *= factor
    return payload


class RoomOverlapDiagnosticsTests(unittest.TestCase):
    def test_floating_point_near_coincident_edge_keeps_unchanged_existing_route(self):
        for units in ("m", "ft"):
            with self.subTest(units=units):
                payload = payload_in(units)
                landing = next(room for room in payload["rooms"] if room["id"] == "landing")
                left = min(x for x, _ in landing["polygon"])
                shifted = math.nextafter(left, -math.inf)
                landing["polygon"] = [[shifted if x == left else x, y] for x, y in landing["polygon"]]
                bedroom = next(room for room in payload["rooms"] if room["id"] == "bed2")
                area = Polygon(landing["polygon"]).intersection(Polygon(bedroom["polygon"])).area
                self.assertGreater(area, 0)
                self.assertLess(area, EPS)
                request = parse_request(payload)
                self.assertEqual(next(room for room in request.rooms if room.id == "landing").bounds[0], shifted)
                response = generate_circulation(payload)
                self.assertEqual(len(response["candidates"]), 1, response)
                candidate = response["candidates"][0]
                self.assertEqual(candidate["metrics"]["total_room_area_taken"], 0)
                self.assertTrue(validate_circulation({"request": payload, "candidate": candidate})["valid"])

    def test_real_sliver_stays_rejected_with_named_dimensions_in_model_units(self):
        for units in ("m", "ft"):
            with self.subTest(units=units):
                payload = payload_in(units)
                factor = 1 if units == "m" else 1 / .3048
                landing = next(room for room in payload["rooms"] if room["id"] == "landing")
                left = min(x for x, _ in landing["polygon"])
                landing["polygon"] = [[x - .001 * factor if x == left else x, y] for x, y in landing["polygon"]]
                with self.assertRaises(CirculationError) as caught:
                    parse_request(payload)
                error = caught.exception
                self.assertEqual(error.code, "invalid_input")
                self.assertIn("Landing overlaps Bedroom 2", error.message)
                self.assertIn(f" {units} × ", error.message)
                self.assertIn("Move their shared wall", error.message)
                self.assertEqual(error.details["room_ids"], ["landing", "bed2"])
                self.assertEqual(error.details["room_names"], ["Landing", "Bedroom 2"])
                self.assertEqual(error.details["units"], units)
                self.assertAlmostEqual(error.details["overlap_width"], .001 * factor)
                self.assertAlmostEqual(error.details["overlap_height"], 6.4 * factor)
                self.assertAlmostEqual(error.details["overlap_area"], .0064 * factor ** 2)
                self.assertGreater(error.details["overlap_area"], EPS)


if __name__ == "__main__":
    unittest.main()
