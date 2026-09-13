"""Requested corridor clearance and longitudinal room doorway size are separate."""
import unittest

from GPLAN.circulation_engine import generate_circulation, validate_circulation
from GPLAN.circulation_engine.tests.test_engine import minimal_request


class RequestedWidthTests(unittest.TestCase):
    def test_one_foot_corridor_keeps_standard_room_doors_and_explicit_entry_choice(self):
        request = minimal_request()
        request.update(width=1, door_width=2.8)
        request["entry"]["replace_existing"] = True
        request["openings"] = [{"id": "entry", "kind": "door", "orientation": "h", "x": 10, "y": 0,
                                "width": 3, "entrance": True, "room_ids": ["large"]}]
        result = generate_circulation(request)
        self.assertTrue(result["candidates"], result)
        for candidate in result["candidates"]:
            self.assertEqual(candidate["metrics"]["width"], 1)
            self.assertEqual(candidate["coverage"]["count"], 2)
            entrance = next(opening for opening in candidate["openings"] if opening.get("entrance"))
            self.assertEqual(entrance["width"], 1)
            self.assertEqual(entrance["source_id"], "entry")
            for room_id in request["required_room_ids"]:
                access = next(opening for opening in candidate["openings"] if room_id in opening["room_ids"])
                self.assertEqual(access["width"], 2.8)
            self.assertTrue(validate_circulation({"request": request, "candidate": candidate})["valid"])


if __name__ == "__main__":
    unittest.main()
