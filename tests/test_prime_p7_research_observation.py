"""Pure raw-board helpers preserve data and expose bounded omissions."""
import importlib
import importlib.util
import unittest


class TestP7ResearchObservation(unittest.TestCase):
    def setUp(self):
        name = 'asterion.applications.prime.p7.research_observation'
        self.assertIsNotNone(importlib.util.find_spec(name))
        self.helpers = importlib.import_module(name)

    def test_grid_detaches_last_frame_and_all_colors_are_components(self):
        frame = [[[9, 9], [9, 9]], [[4, 4], [255, 0]]]
        grid = self.helpers.grid(frame)
        grid[0][0] = 8
        self.assertEqual(frame[-1][0][0], 4)
        value = self.helpers.geometry(frame)
        self.assertEqual(value['shape'], [2, 2])
        self.assertEqual(value['counts'], {0: 1, 4: 2, 255: 1})
        self.assertEqual([x['value'] for x in value['components']], [4, 255, 0])
        self.assertEqual(value['components'][0]['bbox'], [0, 0, 1, 0])
        filtered = self.helpers.geometry(frame, colors=[255], limit=1)
        self.assertEqual([x['value'] for x in filtered['components']], [255])

    def test_render_and_diff_report_exact_bounds_and_omissions(self):
        rendered = self.helpers.render([[0, 255], [4, 8]], max_cells=2)
        self.assertIn('FF', rendered['text'])
        self.assertEqual(rendered['window'], [0, 0, 2, 1])
        self.assertEqual(rendered['omitted_cells'], 2)
        delta = self.helpers.diff([[1, 2], [3, 4]], [[1, 9, 5]], limit=1)
        self.assertEqual(delta['changed_cell_count'], 4)
        self.assertEqual(delta['changed_cells'], [{'x': 1, 'y': 0, 'before': 2, 'after': 9}])
        self.assertEqual(delta['changed_cells_omitted'], 3)

    def test_invalid_data_and_invalid_caps_reject_without_coercion(self):
        for frame in ([[True]], [[1], [2, 3]], [[-1]], [[256]], []):
            with self.subTest(frame=frame):
                with self.assertRaises(ValueError):
                    self.helpers.grid(frame)
        with self.assertRaises(ValueError):
            self.helpers.geometry([[1]], limit=0)
        with self.assertRaises(ValueError):
            self.helpers.render([[1]], max_cells=True)
