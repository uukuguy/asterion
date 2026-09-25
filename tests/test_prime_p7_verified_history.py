"""Private, offline P7 verified history contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from asterion.applications.prime.p7.broker import ArcAction
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.verified_history import (
    ArcHistoryRecord,
    ArcPredictionError,
    stable_changed_cells,
    validate_history_query,
    validate_prediction,
)


class TestVerifiedHistory(unittest.TestCase):
    def test_sequence_zero_has_distinct_hashes_and_private_frame(self) -> None:
        frame = [[1, 2], [3, 4]]
        state_hash = digest({"observation": "initial"})
        record = ArcHistoryRecord.initial(
            game_id="ls20-9607627b", seed=0, run_id="private-run",
            frame=frame, levels_completed=0, state="NOT_FINISHED",
            after_state_sha256=state_hash,
        )
        frame[0][0] = 9
        self.assertEqual(record.frame, ((1, 2), (3, 4)))
        self.assertEqual(record.sequence, 0)
        self.assertIsNone(record.action)
        self.assertIsNone(record.before_state_sha256)
        self.assertIsNone(record.before_frame_sha256)
        self.assertEqual(record.after_state_sha256, state_hash)
        self.assertEqual(record.after_frame_sha256, digest(record.frame))
        self.assertEqual(record.after_frame_sha256, record.stable_frame_sha256)
        self.assertNotEqual(record.after_state_sha256, record.after_frame_sha256)
        public = record.public_view()
        for private in ("frame", "run_id", "game_id", "seed"):
            self.assertNotIn(private, public)
        self.assertNotIn("private-run", repr(public))
        with self.assertRaises(FrozenInstanceError):
            record.state = "WIN"  # type: ignore[misc]

    def test_direct_record_replacement_cannot_hold_mutable_frame(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=0, run_id="private-run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("before"),
        )
        source = [[4]]
        with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
            replace(first, frame=source)

    def test_direct_record_rejects_mutable_nested_values_and_broken_counts(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=0, run_id="private-run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("before"),
        )
        cases = (
            {"data": (("x", [1]),)},
            {"changed_cells": ((0, 0, 0, [1]),)},
            {"changed_cell_count": 1},
            {"changed_cells_omitted": 1},
            {"sequence": 1},
            {"action": "ACTION1"},
            {"before_state_sha256": digest("before")},
            {"after_state_sha256": "bad"},
            {"state": ["NOT_FINISHED"]},
            {"frame": ((True,),)},
        )
        for changed in cases:
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
                    replace(first, **changed)

    def test_following_record_keeps_private_data_and_public_copy_is_detached(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=0, run_id="private-run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("before"),
        )
        later = ArcHistoryRecord.following(
            first, action=ArcAction("ACTION1"),
            before_state_sha256=first.after_state_sha256,
            after_state_sha256=digest("after"), frame=((1,),),
            levels_completed=0, state="NOT_FINISHED",
        )
        self.assertEqual(later.sequence, 1)
        self.assertEqual(later.before_frame_sha256, first.after_frame_sha256)
        self.assertEqual(later.changed_cells, ((0, 0, 0, 1),))
        view = later.public_view()
        view["changed_cells"].append((0, 0, 0, 9))
        self.assertEqual(later.public_view()["changed_cells"], [(0, 0, 0, 1)])
        self.assertEqual(later.data, ())
        self.assertNotIn("private-run", repr(later))
        for changed in (
            {"changed_cell_count": 2, "changed_cells_omitted": 1},
            {"changed_cells": ((0, 0, 0, 2),)},
            {"changed_cells": ((0, 0, 1, 1),)},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
                    replace(later, **changed)
        with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
            ArcHistoryRecord.following(
                first, action=ArcAction("ACTION1"), before_state_sha256=digest("wrong"),
                after_state_sha256=digest("after"), frame=((1,),),
                levels_completed=0, state="NOT_FINISHED",
            )

    def test_malformed_action_data_has_fixed_safe_error(self) -> None:
        first = ArcHistoryRecord.initial(
            game_id="game", seed=0, run_id="private-run", frame=((0,),),
            levels_completed=0, state="NOT_FINISHED", after_state_sha256=digest("before"),
        )
        with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
            ArcHistoryRecord.following(
                first, action=ArcAction("ACTION1", (("broken",),)),
                before_state_sha256=first.after_state_sha256,
                after_state_sha256=digest("after"), frame=((1,),),
                levels_completed=0, state="NOT_FINISHED",
            )

    def test_changed_cells_are_sorted_bounded_and_report_omitted_count(self) -> None:
        before = tuple(tuple(0 for _ in range(11)) for _ in range(10))
        after = tuple(tuple(1 for _ in range(11)) for _ in range(10))
        total, sample, omitted = stable_changed_cells(before, after)
        self.assertEqual((total, len(sample), omitted), (110, 80, 30))
        self.assertEqual(sample[0], (0, 0, 0, 1))
        self.assertEqual(sample[-1], (2, 7, 0, 1))
        self.assertEqual(stable_changed_cells(before, after, limit=8), (
            110, tuple((x, 0, 0, 1) for x in range(8)), 102,
        ))

    def test_changed_cells_rejects_non_rectangular_or_mismatched_grids(self) -> None:
        for before, after, limit in (
            (((0,),), ((0, 1),), 80),
            (((0, 1), (0,)), ((0, 1), (0, 1)), 80),
            (((0,),), ((False,),), 80),
            (((0,),), ((0,),), -1),
        ):
            with self.subTest(before=before, after=after, limit=limit):
                with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
                    stable_changed_cells(before, after, limit=limit)

    def test_query_bounds_reject_invalid_types_and_future(self) -> None:
        for start, limit, latest in (
            (-1, 1, 3), (0, 0, 3), (0, 33, 3), (4, 1, 3),
            (False, 1, 3), (0, True, 3), (0, 1, -1),
        ):
            with self.subTest(start=start, limit=limit, latest=latest):
                with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
                    validate_history_query(start=start, limit=limit, latest_sequence=latest)
        self.assertEqual(validate_history_query(start=3, limit=32, latest_sequence=3), (3, 32))

    def test_prediction_requires_distinguishing_expectation(self) -> None:
        action = {"name": "ACTION1", "data": {}}
        for expect in ({}, {"levels_completed": 0}, {"state": "NOT_FINISHED"}):
            with self.subTest(expect=expect):
                with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
                    validate_prediction({"action": action, "expect": expect}, current_levels=0)
        for expect in (
            {"cell": {"x": 2, "y": 3, "value": 7}},
            {"frame_sha256": digest(((1,),))},
            {"levels_completed": 1},
            {"state": "WIN"},
            {"state": "GAME_OVER"},
        ):
            with self.subTest(expect=expect):
                self.assertEqual(validate_prediction(
                    {"action": action, "expect": expect}, current_levels=0,
                )[0], "ACTION1")

    def test_action6_json_key_order_is_irrelevant(self) -> None:
        action = {"name": "ACTION6", "data": {"y": 3, "x": 2}}
        self.assertEqual(
            validate_prediction(
                {"action": action, "expect": {"state": "WIN"}}, current_levels=0,
            )[:2],
            ("ACTION6", (("x", 2), ("y", 3))),
        )

    def test_prediction_rejects_malformed_action_and_expectations(self) -> None:
        action = {"name": "ACTION1", "data": {}}
        cases = (
            ({"action": {"name": "ACTION6", "data": {"x": 1}}, "expect": {"state": "WIN"}}, 0),
            ({"action": {"name": "ACTION2", "data": {"x": 1}}, "expect": {"state": "WIN"}}, 0),
            ({"action": action, "expect": {"cell": {"x": -1, "y": 0, "value": 1}}}, 0),
            ({"action": action, "expect": {"cell": {"x": 0, "y": 0, "value": True}}}, 0),
            ({"action": action, "expect": {"frame_sha256": "bad"}}, 0),
            ({"action": action, "expect": {"state": "WIN", "mystery": 1}}, 0),
            ({"action": action, "expect": {"levels_completed": 1}}, 1),
            ({"action": action, "expect": {"state": "WIN"}}, True),
        )
        for value, current_levels in cases:
            with self.subTest(value=value, current_levels=current_levels):
                with self.assertRaisesRegex(ArcPredictionError, "^P7 prediction is unavailable$"):
                    validate_prediction(value, current_levels=current_levels)
