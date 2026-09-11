from copy import deepcopy
import unittest

from GPLAN.commercial import estimate_commercial_fit, generate_commercial_options, normalize_brief, validate_commercial_option
from GPLAN.commercial.models import authorized_floors
from GPLAN.commercial.tests.test_commercial import default_brief


class AutomaticFloors(unittest.TestCase):
    def test_floor_growth_keeps_all_requested_capacity(self):
        brief = default_brief()
        brief['building'].update(floor_strategy='single', auto_add_floors=True)
        snapshot = deepcopy(brief)
        result = generate_commercial_options(brief)
        self.assertTrue(result['candidates'], result['diagnostics'])
        candidate = result['candidates'][0]
        self.assertGreater(len(candidate['floors']), 1)
        self.assertEqual(candidate['capacity']['desks'], 36)
        self.assertEqual(candidate['capacity']['meeting_seats'], 16)
        self.assertTrue(validate_commercial_option(candidate, brief)['valid'])
        self.assertEqual(brief, snapshot)

    def test_height_and_opt_out_are_respected(self):
        brief = default_brief()
        brief['building'].update(floor_strategy='single', auto_add_floors=True)
        brief['site']['max_height_m'] = 6.6
        self.assertEqual(authorized_floors(normalize_brief(brief)), [1, 2])
        brief['building']['auto_add_floors'] = False
        self.assertEqual(authorized_floors(normalize_brief(brief)), [1])

    def test_preflight_names_indivisible_room_before_search(self):
        brief = default_brief()
        brief['building']['auto_add_floors'] = True
        brief['rooms'][0].update(capacity=100, min_area_m2=500)
        result = estimate_commercial_fit(brief)
        self.assertTrue(any(item.get('requirement_id') == 'meeting' for item in result['preflight_issues']))
        self.assertNotIn('candidates', result)

    def test_large_meetings_return_disclosed_recovery_plan(self):
        brief = default_brief()
        brief['building'].update(floor_strategy='single', auto_add_floors=True, allow_programme_adjustments=True)
        brief['rooms'][0].update(capacity=40, count=5, min_area_m2=80)
        result = generate_commercial_options(brief)
        self.assertTrue(result['candidates'], result['diagnostics'])
        candidate = result['candidates'][0]
        self.assertEqual(candidate['capacity']['desks'], 36)
        self.assertEqual(candidate['fit_kind'], 'modified_programme')
        self.assertTrue(candidate['constraint_deviations'])
        self.assertTrue(validate_commercial_option(candidate, brief)['valid'])


if __name__ == '__main__':
    unittest.main()
