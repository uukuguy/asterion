import unittest


class FrameAnalysisTests(unittest.TestCase):
    def test_summarize_frame_returns_bounded_counts_and_components(self) -> None:
        from asterion.applications.prime.p7.frame_analysis import summarize_frame

        result = summarize_frame(
            [
                [4, 4, 4, 4],
                [4, 1, 1, 4],
                [4, 1, 4, 2],
                [4, 4, 4, 4],
            ]
        )

        self.assertEqual(result["shape"], [4, 4])
        self.assertEqual(result["counts"], {1: 3, 2: 1, 4: 12})
        self.assertEqual(
            result["components"],
            [
                {"value": 1, "bbox": [1, 1, 2, 2], "size": 3},
                {"value": 2, "bbox": [3, 2, 3, 2], "size": 1},
            ],
        )


if __name__ == "__main__":
    unittest.main()
