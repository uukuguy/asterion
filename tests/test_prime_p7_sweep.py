from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestPrimeP7Sweep(unittest.TestCase):
    def test_round_robin_attempts_one_next_level_per_game(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(
                SweepConfig(arc_root=root / "arc", runs_root=root / "runs", games=("a-1", "b-2"), global_token_cap=100, max_attempts=2)
            )
            attempts: list[tuple[str, int]] = []

            def attempt(game_id: str, level: int, _timeout: float) -> int:
                attempts.append((game_id, level))
                return 0

            scheduler._attempt = attempt  # type: ignore[method-assign]
            scheduler._next_level = lambda game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._attempt_result = lambda _game_id, _level: True  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("a-1", 1), ("b-2", 1)])
        self.assertEqual(result.attempted, 2)

    def test_failed_game_is_blocked_until_the_sweep_ends(self) -> None:
        from tools.run_prime_p7_sweep import SweepConfig, SweepScheduler

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scheduler = SweepScheduler(
                SweepConfig(arc_root=root / "arc", runs_root=root / "runs", games=("a-1", "b-2"), global_token_cap=100, max_attempts=2)
            )
            attempts: list[tuple[str, int]] = []

            def attempt(game_id: str, level: int, _timeout: float) -> int:
                attempts.append((game_id, level))
                return 1 if game_id == "a-1" else 0

            scheduler._attempt = attempt  # type: ignore[method-assign]
            scheduler._next_level = lambda _game_id: 1  # type: ignore[method-assign]
            scheduler._is_complete = lambda _game_id, _level: False  # type: ignore[method-assign]
            scheduler._attempt_result = lambda game_id, _level: game_id == "b-2"  # type: ignore[method-assign]
            result = scheduler.run()

        self.assertEqual(attempts, [("a-1", 1), ("b-2", 1)])
        self.assertEqual(result.blocked, ("a-1",))

    def test_usage_is_summed_and_missing_usage_stops_after_model_activity(self) -> None:
        from tools.run_prime_p7_sweep import read_run_usage

        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            trace = run / "trace"
            trace.mkdir()
            (trace / "prime-trace.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"kind": "arc.usage.reported", "payload": {"input_tokens": 4, "output_tokens": 6}}),
                        json.dumps({"kind": "arc.usage.reported", "payload": {"input_tokens": 3, "output_tokens": 2}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(read_run_usage(run), (7, 8, False))

            (trace / "prime-trace.jsonl").write_text("", encoding="utf-8")
            (run / "worker-cells.jsonl").write_text("{}\n", encoding="utf-8")
            self.assertEqual(read_run_usage(run), (0, 0, True))


if __name__ == "__main__":
    unittest.main()
