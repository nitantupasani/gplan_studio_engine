from copy import deepcopy
import unittest
from unittest.mock import patch

from GPLAN.commercial import estimate_commercial_fit, normalize_brief
from GPLAN.commercial.generation import pack_candidate, start_floor
from GPLAN.commercial.program import compile_program
from GPLAN.commercial.program import requirement
from GPLAN.commercial.room_fit import fits_slot, room_fit_issue
from GPLAN.commercial.service import generate_commercial_options
from GPLAN.commercial.tests.test_commercial import default_brief


class RoomFitLimits(unittest.TestCase):
    def test_capacity_limit_fits_and_next_seat_does_not(self):
        room = requirement('meeting', 'meeting', 40, min_area_m2=20)
        slot = {'width': 5, 'y': 2, 'end': 12}
        snapshot = deepcopy(room)
        issue = room_fit_issue(room, [slot])
        capacity = issue['suggested_values']['capacity']
        self.assertGreater(capacity, 0)
        self.assertLess(capacity, 40)
        self.assertTrue(fits_slot({**room, 'required_capacity': capacity}, slot))
        self.assertFalse(fits_slot({**room, 'required_capacity': capacity + 1}, slot))
        self.assertEqual(room, snapshot)
        self.assertNotIn('min_area_m2', issue['suggested_values'])

    def test_combined_area_and_seat_limits_are_tested_together(self):
        room = requirement('meeting', 'meeting', 100, min_area_m2=500, preferred_area_m2=550)
        slot = {'width': 5.4, 'y': 0, 'end': 14}
        suggestion = room_fit_issue(room, [slot])['suggested_values']
        changed = {**room, **suggestion, 'required_capacity': suggestion['capacity']}
        self.assertTrue(fits_slot(changed, slot, spacious=True))
        self.assertLess(suggestion['min_area_m2'], 500)
        self.assertEqual(suggestion['preferred_area_m2'], suggestion['min_area_m2'])

    def test_no_fake_numeric_limit_for_impossible_width_or_locked_rooms(self):
        room = requirement('meeting', 'meeting', 40)
        slot = {'width': 3, 'y': 0, 'end': 30}
        self.assertNotIn('suggested_values', room_fit_issue(room, [slot]))
        self.assertNotIn('suggested_values', room_fit_issue({**room, 'locked': True}, [{'width': 5, 'y': 0, 'end': 10}]))
        self.assertNotIn('suggested_values', room_fit_issue(requirement('wc', 'wc', 20), [slot]))

    def test_remaining_space_is_distinguished_from_empty_room_limit(self):
        room = requirement('meeting', 'meeting', 40)
        empty = {'width': 5, 'y': 0, 'end': 16}
        occupied = {**empty, 'y': 9}
        earlier = room_fit_issue(room, [empty])
        current = room_fit_issue(room, [occupied], 'remaining_slots')
        self.assertEqual(current['scope'], 'remaining_slots')
        self.assertIn('suggested_values', earlier)
        self.assertEqual(current['code'], 'room_placement_conflict')
        self.assertNotIn('suggested_values', current, 'A leftover strip is not the capacity limit for the room')

    def test_zero_seat_reception_can_have_an_area_only_change(self):
        room = requirement('reception', 'reception', 0, min_area_m2=100, preferred_area_m2=100)
        slot = {'width': 5, 'y': 0, 'end': 12}
        suggestion = room_fit_issue(room, [slot])['suggested_values']
        self.assertNotIn('capacity', suggestion)
        self.assertTrue(fits_slot({**room, **suggestion}, slot, spacious=True))

    def test_1200_square_metres_fits_twenty_seats_but_not_this_ground_allocation(self):
        brief = default_brief()
        brief['site'].update(width_m=30, depth_m=40)
        brief['people'].update(staff=100, visitors=50, desks=100)
        brief['building'].update(max_floors=4, auto_add_floors=True)
        brief['rooms'][0].update(count=10, capacity=20)
        brief['rooms'][1]['count'] = 3
        brief['rooms'][2]['count'] = 2
        brief['amenities'].update(lunch_seats=20, pantry='reheat')
        brief = normalize_brief(brief)
        self.assertFalse(estimate_commercial_fit(brief)['preflight_issues'])
        floor, _ = start_floor(brief, 1, 0, .5)
        meeting = next(room for room in compile_program(brief) if room['role'] == 'meeting')
        self.assertTrue(any(fits_slot(meeting, slot) for slot in floor['_bins']))
        candidate, failure = pack_candidate(brief, 1)
        self.assertIsNone(candidate)
        self.assertEqual(failure['code'], 'room_placement_conflict')
        self.assertNotIn('suggested_values', failure)

    def test_route_failure_is_not_lost_when_smaller_programmes_fail(self):
        brief = normalize_brief(default_brief())
        brief['building']['allow_programme_adjustments'] = True
        fitted = deepcopy(brief)
        fitted['rooms'][0]['capacity'] -= 1
        strict = {'schema_version': '1.0', 'status': 'no_feasible_candidate_found_within_budget',
                  'brief': brief, 'candidates': [], 'diagnostics': [], 'search': {'attempts': 1}}
        rejected = deepcopy(strict)
        check = {'id': 'f0:meeting:operational-route', 'status': 'failed', 'measured': 32.346, 'required': 30}
        rejected['diagnostics'] = [{'code': 'candidate_rejected', 'checks': [check]}]
        with patch('GPLAN.commercial.service._generate_strict', side_effect=[strict, rejected]), \
             patch('GPLAN.commercial.service.adjusted_briefs', return_value=[fitted]):
            result = generate_commercial_options(brief)
        failure = next(d for d in result['diagnostics'] if d['code'] == 'adjusted_candidate_rejected')
        self.assertEqual(failure['scope'], 'modified_programme_attempt')
        self.assertEqual(failure['checks'], [check])


if __name__ == '__main__':
    unittest.main()
