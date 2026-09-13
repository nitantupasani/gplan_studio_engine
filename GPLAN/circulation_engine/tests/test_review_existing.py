"""Independent review of existing landing reuse and saved stair-portal semantics."""
from copy import deepcopy
import unittest

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from GPLAN.circulation_engine import CirculationError, generate_circulation, validate_circulation
from GPLAN.circulation_engine.models import parse_request, ring


def existing_payload():
    """Nominal 1202x9500 mm landing -> 1100x9196 mm clear floor.

    Interior walls are 102 mm centered on shared edges; both exterior ends
    occupy the full 152 mm inside the envelope. Room doors are 850 mm; the
    stair portal is 900 mm. All figures are explicitly metres here.
    """
    rooms = []
    for rid, name, bounds in (
        ("bed2", "Bedroom 2", (0, 0, 4, 6.4)),
        ("bed1", "Bedroom 1", (0, 6.4, 4, 9.5)),
        ("landing", "Landing", (4, 0, 5.202, 9.5)),
        ("bath", "Bathroom / WC", (5.202, 0, 8, 5.3)),
        ("stair", "Staircase", (5.202, 5.3, 8, 9.5)),
    ):
        rooms.append({"id": rid, "name": name, "polygon": ring(box(*bounds)), "min_width": .8,
                      "min_height": .8, "min_area": 1, "max_aspect": 20,
                      "locked": rid == "stair", "protected": rid == "stair"})
    openings = []
    for oid, x, y, width, other in (
        ("stair-portal", 5.202, 7.4, .9, "stair"),
        ("bed2-door", 4, 3.2, .85, "bed2"),
        ("bed1-door", 4, 8, .85, "bed1"),
        ("bath-door", 5.202, 2.6, .85, "bath"),
    ):
        openings.append({"id": oid, "kind": "door", "orientation": "v", "x": x, "y": y,
                         "width": width, "room_ids": ["landing", other], "entrance": False})
    return {"schema_version": "1.0", "plan_id": "existing-first-floor", "source_fingerprint": "nominal-first-floor",
            "units": "m", "boundary": ring(box(0, 0, 8, 9.5)), "holes": [], "rooms": rooms,
            "openings": openings, "obstacles": [], "circulation_room_ids": ["landing"], "modes": ["existing"],
            "entry": {"opening_id": "stair-portal", "stair_room_id": "stair"},
            "required_room_ids": ["bed1", "bed2", "bath"], "width": 1.0668, "door_width": .85,
            "wall_thickness": {"interior": .102, "exterior": .152}, "contribution_policy": "area"}


class ExistingCirculationReviewTests(unittest.TestCase):
    def candidate(self, payload):
        response = generate_circulation(payload)
        self.assertEqual(len(response.get("candidates", [])), 1, response)
        return response["candidates"][0]

    def assert_generation_rejected(self, payload):
        try:
            result = generate_circulation(payload)
        except CirculationError:
            return
        self.assertFalse(result.get("candidates"), result)

    def assert_validation_rejected(self, payload, candidate):
        try:
            result = validate_circulation({"request": payload, "candidate": candidate})
        except CirculationError:
            return
        self.assertFalse(result["valid"], result)

    def test_authored_nominal_to_clear_floor_and_zero_room_loss(self):
        payload = existing_payload()
        candidate = self.candidate(payload)
        clear = unary_union([Polygon(s["polygon"], s.get("holes", [])) for s in candidate["corridors"]])
        expected = box(4.051, .152, 5.151, 9.348)
        self.assertLess(clear.symmetric_difference(expected).area, 1e-7)
        self.assertAlmostEqual(clear.bounds[2] - clear.bounds[0], 1.1, places=6)
        self.assertAlmostEqual(clear.bounds[3] - clear.bounds[1], 9.196, places=6)
        before = {r["id"]: Polygon(r["polygon"]) for r in payload["rooms"]}
        after = {r["id"]: Polygon(r["polygon"]) for r in candidate["adjusted_rooms"]}
        self.assertEqual(set(before), set(after))
        self.assertTrue(all(before[rid].equals(after[rid]) for rid in before))
        self.assertEqual(candidate["metrics"]["total_room_area_taken"], 0)
        self.assertTrue(all(c["area_taken"] == 0 for c in candidate["contributions"]))
        self.assertEqual(candidate["algorithm"]["id"], "existing")
        self.assertEqual(candidate["coverage"]["count"], 3)
        self.assertTrue(validate_circulation({"request": payload, "candidate": candidate})["valid"])

    def test_850mm_room_doors_and_900mm_stair_portal_are_preserved(self):
        payload = existing_payload()
        candidate = self.candidate(payload)
        normalized = list(parse_request(payload).openings)
        self.assertEqual(candidate["openings"], normalized)
        self.assertEqual(next(o for o in candidate["openings"] if o["id"] == "bed2-door")["width"], .85)
        self.assertEqual(next(o for o in candidate["openings"] if o["id"] == "stair-portal")["width"], .9)
        self.assertFalse(any(o.get("generated") or o.get("moved") for o in candidate["openings"]))

    def test_public_role_is_explicit_and_does_not_follow_room_names(self):
        explicit = existing_payload()
        next(r for r in explicit["rooms"] if r["id"] == "landing")["name"] = "Custom circulation zone A"
        self.assertEqual(self.candidate(explicit)["algorithm"]["id"], "existing")
        implicit = existing_payload()
        implicit.pop("circulation_room_ids")
        self.assert_generation_rejected(implicit)
        # An explicitly named Staircase alone is not authority to route through
        # private room interiors or synthesize an internal entry in shift mode.
        implicit["modes"] = ["spanning"]
        self.assert_generation_rejected(implicit)

    def test_stair_entry_requires_real_saved_portal_and_correct_protected_owner(self):
        changes = [
            lambda p: p["entry"].update(opening_id="missing-door"),
            lambda p: p["entry"].update(opening_id="bed1-door"),
            lambda p: p["entry"].update(stair_room_id="bed1"),
            lambda p: p["entry"].update(point=[5.202, 6.4]),
            lambda p: p["entry"].update(replace_existing=True),
            lambda p: next(r for r in p["rooms"] if r["id"] == "stair").update(locked=False, protected=False),
            lambda p: next(o for o in p["openings"] if o["id"] == "stair-portal").update(kind="window"),
            lambda p: next(o for o in p["openings"] if o["id"] == "stair-portal").update(width=.5),
        ]
        for i, mutate in enumerate(changes):
            with self.subTest(case=i):
                payload = existing_payload()
                mutate(payload)
                self.assert_generation_rejected(payload)

    def test_requested_width_uses_clear_floor_instead_of_nominal_room_width(self):
        payload = existing_payload()
        payload["width"] = 1.101
        self.assert_generation_rejected(payload)
        # 1.101m is less than the nominal1.202m width but exceeds the actual
        # clear1.100m. Removing required wall metadata must never assume zero.
        payload = existing_payload()
        payload.pop("wall_thickness")
        self.assert_generation_rejected(payload)

    def test_hole_or_obstacle_cannot_be_reclassified_as_public_circulation(self):
        hole = [[4.4, 4], [4.8, 4], [4.8, 5], [4.4, 5]]
        for key in ("holes", "obstacles"):
            with self.subTest(occupied_void=key):
                payload = existing_payload()
                payload[key] = [hole]
                self.assert_generation_rejected(payload)
        # A genuinely unchanged courtyard outside the landing remains empty.
        payload = existing_payload()
        payload["boundary"] = ring(box(0, 0, 10, 9.5))
        payload["holes"] = [[[8.5, 3], [9.5, 3], [9.5, 4], [8.5, 4]]]
        candidate = self.candidate(payload)
        clear = unary_union([Polygon(s["polygon"], s.get("holes", [])) for s in candidate["corridors"]])
        self.assertEqual(clear.intersection(Polygon(payload["holes"][0])).area, 0)

    def test_new_wall_separated_reuse_room_is_not_an_open_network(self):
        payload = existing_payload()
        # Designating another existing room as public is allowed input intent,
        # but the separating wall and only850mm doorway cannot become an open
        # 1066.8mm corridor junction simply by assigning both source IDs.
        payload["circulation_room_ids"].append("bed1")
        payload["required_room_ids"].remove("bed1")
        self.assert_generation_rejected(payload)

    def test_candidate_metadata_clear_geometry_and_room_tampering_are_rejected(self):
        payload = existing_payload()
        candidate = self.candidate(payload)
        changes = {
            "reuse_ids": lambda c: c.update(reused_room_ids=["bed1"]),
            "wall_metadata": lambda c: c["corridors"][0].update(wall_thickness={"interior": 0, "exterior": 0}),
            "source_polygon": lambda c: c["corridors"][0].update(source_polygon=ring(box(4, 0, 5.202, 9))),
            "clear_polygon": lambda c: c["corridors"][0].update(polygon=ring(box(4, .152, 5.202, 9.348))),
            "room_polygon": lambda c: c["adjusted_rooms"][0].update(polygon=ring(box(0, 0, 1, 1))),
            "door_width": lambda c: c["openings"][0].update(width=1.2),
        }
        for name, mutate in changes.items():
            with self.subTest(tamper=name):
                changed = deepcopy(candidate)
                mutate(changed)
                self.assert_validation_rejected(payload, changed)
        changed_request = deepcopy(payload)
        changed_request["wall_thickness"]["interior"] = 0
        self.assert_validation_rejected(changed_request, candidate)


if __name__ == "__main__":
    unittest.main()
