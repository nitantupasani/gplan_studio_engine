"""New Dutch houses retain at least 1 m clear indoor circulation after import."""
import math
import unittest

from shapely.geometry import Polygon

from GPLAN.circulation_engine.existing import _clear_width, width_is_valid
from GPLAN.housing.programs import get_profile
from GPLAN.housing.solver import build_blueprint, solve_floor


class HouseCirculationWidthTests(unittest.TestCase):
    def test_actual_floor_halls_and_both_landing_branches_target_one_metre(self):
        cases = [("ground", 0, "kitchen_front", 2), ("ground", 0, "living_front", 2),
                 ("first", 1, "kitchen_front", 2), ("first", 1, "kitchen_front", 3),
                 ("second", 2, "kitchen_front", 2), ("attic", 3, "kitchen_front", 2)]
        for interior in (100, 101, 102):
            for role, level, variant, bedrooms in cases:
                with self.subTest(interior=interior, role=role, variant=variant, bedrooms=bedrooms):
                    walls = {"interior_mm": interior, "exterior_mm": 152}
                    # Use the actual captured regular-floor envelope. The
                    # old and new templates both reject 10000 by 11000 mm for this
                    # two-bedroom topology at the unchanged strict tiling gate.
                    width, depth = (9192, 9500) if role in {"first", "second"} and bedrooms == 2 else (10000, 11000)
                    floor, core = solve_floor(role, level, width, depth, walls, get_profile(), variant, bedrooms)
                    self.assertEqual(core, (math.ceil(2000 + 152 + interior / 2), math.ceil(4000 + 152 + interior / 2)))
                    hall = next(room for room in floor["rooms"] if room["role"] in {"entrance", "landing", "attic_landing"})
                    clear = Polygon(hall["clear_polygon"])
                    self.assertTrue(width_is_valid(clear, 1000))
                    self.assertGreaterEqual(_clear_width(clear), 1000)
                    self.assertLess(_clear_width(clear), 1005, "Only the small import storage allowance is added")
                    for door in floor["doors"]:
                        if ":stair" in (door["from_room_id"] or "") or ":stair" in (door["to_room_id"] or "") or door.get("external_role") == "entrance":
                            self.assertEqual(door["clear_width_mm"], 900)

    def test_coordinate_rounding_at_different_phases_never_reduces_clear_width_below_one_metre(self):
        quantum = 3.048
        quantize = lambda value: math.floor(value / quantum + .5) * quantum
        for interior in (50, 100, 101, 102, 151, 152, 200, 500):
            walls = {"interior_mm": interior, "exterior_mm": 152}
            cells, _, _, _ = build_blueprint("first", 10000, 11000, walls, bedrooms=3)
            landing_cells = [cell for cell in cells if cell.key == "landing"]
            for span in (landing_cells[0].min_w, landing_cells[1].min_d):
                self.assertGreaterEqual(span - interior, 1000)
                self.assertLess(span - interior, 1005)
                for phase in [index * quantum / 32 for index in range(-64, 65)]:
                    # A displayed wall may round down by almost 0.5 mm in the
                    # integer-mm generation request (e.g. 152.4 -> 152).
                    rounded_clear = quantize(phase + span) - quantize(phase) - (interior + .499)
                    self.assertGreaterEqual(rounded_clear, 1000 - 1e-9)
        default_cells, _, _, _ = build_blueprint("first", 10000, 11000, {"interior_mm": 102, "exterior_mm": 152})
        self.assertEqual(next(cell for cell in default_cells if cell.key == "landing").min_w, 1104)

    def test_thin_wall_ground_hall_still_fits_unchanged_entrance_and_jambs(self):
        walls = {"interior_mm": 50, "exterior_mm": 152}
        floor, _ = solve_floor("ground", 0, 10000, 11000, walls, get_profile())
        hall = next(room for room in floor["rooms"] if room["role"] == "entrance")
        self.assertGreaterEqual(hall["clear_width_mm"], 1000)
        self.assertEqual(Polygon(hall["polygon"]).bounds[2] - Polygon(hall["polygon"]).bounds[0], 1100)
        entry = next(door for door in floor["doors"] if door.get("external_role") == "entrance")
        self.assertEqual(entry["clear_width_mm"], 900)


if __name__ == "__main__":
    unittest.main()
