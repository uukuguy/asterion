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

    def test_patches_preserve_shapes_even_with_equal_centers_and_counts(self):
        self.assertTrue(hasattr(self.helpers, 'patches'))
        frame = [[9, 0, 0, 0, 9, 0], [0, 15, 0, 0, 15, 0], [0, 0, 255, 255, 0, 0]]
        result = self.helpers.patches(frame, [[0, 0, 3, 3], [3, 0, 6, 3]])
        first, second = result['patches']
        self.assertEqual(result['shape'], [3, 6])
        self.assertEqual(first['pixels'][1][1], second['pixels'][1][1])
        self.assertEqual(first['counts'], second['counts'])
        self.assertEqual(first['counts'], {0: 6, 9: 1, 15: 1, 255: 1})
        self.assertNotEqual(first['pixels'], second['pixels'])

    def test_patches_detach_pixels_windows_and_preserve_input_order(self):
        self.assertTrue(hasattr(self.helpers, 'patches'))
        frame = [[[9, 9]], [[0, 255]]]
        windows = [[1, 0, 2, 1], [0, 0, 1, 1], [1, 0, 2, 1]]
        result = self.helpers.patches(frame, windows)
        self.assertEqual([p['pixels'] for p in result['patches']], [[[255]], [[0]], [[255]]])
        result['patches'][0]['pixels'][0][0] = 7
        result['patches'][0]['window'][0] = 0
        self.assertEqual(frame[-1], [[0, 255]])
        self.assertEqual(windows[0], [1, 0, 2, 1])
        self.assertEqual(result['patches'][2]['pixels'], [[255]])
        self.assertEqual(self.helpers.patches(((0, 255),), ((0, 0, 2, 1),))['patches'][0]['counts'], {0: 1, 255: 1})

    def test_patches_reject_invalid_windows_and_aggregate_caps(self):
        self.assertTrue(hasattr(self.helpers, 'patches'))
        frame = [[0] * 64 for _ in range(64)]
        invalid = [None, {}, [], [[0, 0, 1, 1]] * 65, [None], [[0, 0, 1]],
                   [[0, 0, 1, 1, 2]], [[False, 0, 1, 1]], [[0, 0, 1.0, 1]],
                   [[-1, 0, 1, 1]], [[0, 0, 65, 1]], [[0, 0, 1, 65]],
                   [[1, 0, 1, 1]], [[0, 1, 1, 1]], [[0, 0, 64, 64], [0, 0, 1, 1]],
                   [[0, 0, 64, 64]] * 2]
        for windows in invalid:
            with self.subTest(windows=windows):
                with self.assertRaises(ValueError):
                    self.helpers.patches(frame, windows)
        self.assertEqual(len(self.helpers.patches(frame, [[0, 0, 64, 64]])['patches'][0]['pixels']), 64)
        self.assertEqual(len(self.helpers.patches(frame, [[0, 0, 8, 8]] * 64)['patches']), 64)
